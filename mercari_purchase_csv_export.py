import argparse
import csv
import logging
import os
import sys
from datetime import datetime, timedelta, date, timezone
from pathlib import Path
from time import sleep
from typing import List, Dict

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

DATETIME_FORMAT = "%Y/%m/%d %H:%M"
LOGIN_URL = "https://jp.mercari.com/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/143.0.0.0 Safari/537.36"
)
INTERVAL_SEC = 3.0

DEBUG = False
logger = None
IGNORE_TIMEOUT = False


def setup_logger() -> logging.Logger:
    """
    ログ設定を行う。

    Returns:
        logging.Logger: 設定済みロガー
    """
    jst = timezone(timedelta(hours=9))
    today = datetime.now(jst).strftime("%Y%m%d")

    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    log_file = log_dir / f"mercari_purchase_csv_export_{today}.log"

    logger_obj = logging.getLogger("mercari")
    logger_obj.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s"
    )

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(
        log_file, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    if not logger_obj.handlers:
        logger_obj.addHandler(stream_handler)
        logger_obj.addHandler(file_handler)

    return logger_obj


def save_debug_snapshot(driver: webdriver.Chrome, prefix: str) -> None:
    """
    ブラウザのスクリーンショット（PNG）とHTMLを保存する。

    Args:
        driver (webdriver.Chrome): WebDriver
        prefix (str): ファイル名プレフィックス
    """
    jst = timezone(timedelta(hours=9))
    timestamp = datetime.now(jst).strftime("%Y%m%d_%H%M%S")

    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    png_path = log_dir / f"{prefix}_{timestamp}.png"
    html_path = log_dir / f"{prefix}_{timestamp}.html"

    try:
        driver.save_screenshot(str(png_path))
        html_path.write_text(driver.page_source, encoding="utf-8")

        logger.debug("スナップショット保存(PNG): %s", png_path)
        logger.debug("スナップショット保存(HTML): %s", html_path)

    except Exception:
        logger.exception("スナップショット保存中にエラーが発生しました。")


def parse_args() -> argparse.Namespace:
    """
    コマンドライン引数を解析する。

    Returns:
        argparse.Namespace: パース済み引数
    """
    parser = argparse.ArgumentParser(
        description="メルカリ購入履歴CSV出力"
    )

    parser.add_argument(
        "--from-date",
        help=(
            "出力対象 From 日付 (yyyy/mm/dd)\n"
            "省略時： 昨日"
        ),
    )
    parser.add_argument(
        "--to-date",
        help=(
            "出力対象 To 日付 (yyyy/mm/dd)\n"
            "省略時： From 日付"
        ),
    )
    parser.add_argument(
        "--csv-path",
        help=(
            "出力CSVファイルパス\n"
            "省略時： output/購入履歴_{From日付:yyyymmdd}_{To日付:yyyymmdd}.csv"
        ),
    )

    parser.add_argument(
        "--ignore-timeout",
        action="store_true",
        help=(
            "詳細ページの表示待ちタイムアウト時に"
            "例外を送出せず処理を継続する\n"
            "省略時： 例外発生時に処理を継続しない"
        ),
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    return parser.parse_args()


def setup_driver() -> webdriver.Chrome:
    """Selenium WebDriverを初期化する"""
    options = Options()
    options.add_argument(f"--user-agent={USER_AGENT}")
    options.add_argument("--disable-blink-features=AutomationControlled")

    service = Service()
    return webdriver.Chrome(service=service, options=options)


def wait_for_manual_login(driver: webdriver.Chrome) -> None:
    """手動ログインを促して処理を中断する"""
    login_url = LOGIN_URL
    # テスト用URL
    if DEBUG:
        login_url = "file:///C:/work/02_%E3%83%A1%E3%83%AB%E3%82%AB%E3%83%AA%E8%B3%BC%E5%85%A5%E5%B1%A5%E6%AD%B4CSV%E5%87%BA%E5%8A%9B/0109%E5%85%A5%E6%89%8B%E8%B3%87%E6%96%99/%E8%B3%BC%E5%85%A5%E3%81%97%E3%81%9F%E5%95%86%E5%93%81%20-%20%E3%83%A1%E3%83%AB%E3%82%AB%E3%83%AA.mhtml"

    driver.get(login_url)
    input(
        "【確認】\n"
        "Chromeでメルカリにログインし、\n"
        "購入履歴ページを表示したのちに Enterキーを押してください。\n"
    )


def collect_purchase_items(
    driver: webdriver.Chrome,
    from_date: date,
    to_date: date,
) -> List[Dict[str, str]]:
    """購入履歴から対象明細を抽出する"""
    results: List[Dict[str, str]] = []

    # --- 商品代金 要素の表示待ち（最大5秒） ---
    try:
        WebDriverWait(driver, 5).until(
            EC.visibility_of_element_located(
                (By.XPATH, "//ul[@data-testid='purchase-item-list']/li")
            )
        )
        logger.debug("購入履歴の一覧表の表示を確認しました。")
    except TimeoutException:
        save_debug_snapshot(driver, "timeout_purchase_list_")
        logger.warning("購入履歴の一覧表の表示待ちがタイムアウトしました。")
        raise

    items = driver.find_elements(
        By.XPATH,
        "//ul[@data-testid='purchase-item-list']/li",
    )

    for item in items:
        detail_url = item.find_element(
            By.XPATH,
            "./a",
        ).get_attribute("href")

        item_name = item.find_element(
            By.XPATH,
            ".//p[@data-testid='item-label']",
        ).text

        datetime_text = item.find_element(
            By.XPATH,
            ".//p[@data-testid='item-label']"
            "/following-sibling::div//span",
        ).text

        purchase_dt = datetime.strptime(datetime_text, DATETIME_FORMAT)
        purchase_date = purchase_dt.date()

        # 降順前提：From日付より古くなったら終了
        if purchase_date < from_date:
            break

        if from_date <= purchase_date <= to_date:
            results.append(
                {
                    "detail_url": detail_url,
                    "item_name": item_name,
                    "purchase_datetime": purchase_dt.strftime(DATETIME_FORMAT),
                }
            )

    return results


def enrich_items_with_detail(
    driver: webdriver.Chrome,
    items: List[Dict[str, str]],
) -> None:
    """
    明細ごとに詳細ページを開き、
    金額・商品ID／注文番号を items に追記する（破壊的更新）
    """
    total = len(items)

    if total == 0:
        logger.info("詳細取得対象の明細はありません。")
        return
    
    for index, item in enumerate(items, start=1):
        detail_url = item["detail_url"]
        # テスト用URL
        if DEBUG:
            detail_url = "file:///C:/work/02_%E3%83%A1%E3%83%AB%E3%82%AB%E3%83%AA%E8%B3%BC%E5%85%A5%E5%B1%A5%E6%AD%B4CSV%E5%87%BA%E5%8A%9B/0109%E5%85%A5%E6%89%8B%E8%B3%87%E6%96%99/%E5%8F%96%E5%BC%95%E7%94%BB%E9%9D%A2%20-%20%E3%83%A1%E3%83%AB%E3%82%AB%E3%83%AA.mhtml"

        detail = fetch_purchase_detail(driver, detail_url)

        item["price"] = detail["price"]

        # 商品ID優先、なければ注文番号
        if detail["item_id"]:
            item["item_or_order_id"] = detail["item_id"]
        else:
            item["item_or_order_id"] = detail["order_number"]

        # 5件ごと、1件目、および、最終件で進捗表示
        if index % 5 == 0 or index == total or index == 1:
            progress = (index / total) * 100
            logger.info(
                f"{datetime.now()}: [進捗] {progress:.1f}% "
                f"({index}/{total} 件処理済)"
            )

        # アクセス間隔
        sleep(INTERVAL_SEC)


def write_csv(csv_path: str, items: List[Dict[str, str]]) -> None:
    """CSVファイルを出力する"""
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(
            file,
            quoting=csv.QUOTE_MINIMAL,
        )

        writer.writerow(
            [
                "No.",
                "商品名",
                "金額",
                "購入日時",
                "商品ID／注文番号",
            ]
        )

        for index, item in enumerate(items, start=1):
            writer.writerow(
                [
                    index,
                    item["item_name"],
                    item.get("price", ""),
                    item["purchase_datetime"],
                    item.get("item_or_order_id", ""),
                ]
            )


def get_text_or_empty(
    driver: webdriver.Chrome,
    xpath: str,
) -> str:
    """
    XPATHに一致するすべての要素のテキストを連結して返す。
    存在しない場合は空文字を返す。
    """
    try:
        elements = driver.find_elements(By.XPATH, xpath)
        texts: List[str] = [
            element.text.strip()
            for element in elements
            if element.text and element.text.strip()
        ]

        return "".join(texts)

    except WebDriverException:
        return ""


def fetch_purchase_detail(
    driver: webdriver.Chrome,
    detail_url: str,
) -> Dict[str, str]:
    """
    詳細URLを開き、金額・商品ID・注文番号を取得する

    Args:
        driver (webdriver.Chrome): WebDriver
        detail_url (str): 詳細ページURL
    
    Returns:
        {
            "price": str,
            "item_id": str,
            "order_number": str,
        }
    """
    driver.get(detail_url)
    logger.debug(f"詳細URL: {detail_url}")

    # --- 商品代金 要素の表示待ち（最大5秒） ---
    try:
        WebDriverWait(driver, 5).until(
            EC.visibility_of_element_located(
                (By.XPATH, '//span[contains(text(), "商品代金")]')
            )
        )
        logger.debug("詳細の商品代金の表示を確認しました。")
    except TimeoutException:
        save_debug_snapshot(driver, "timeout_detail_price")
        logger.warning("詳細の商品代金の表示待ちがタイムアウトしました。")
        if not IGNORE_TIMEOUT:
            raise
        
    # 金額（2パターン対応）
    price = get_text_or_empty(
        driver,
        (
            '//span[contains(text(), "商品代金")]'
            '/parent::div/parent::div/following-sibling::div'
        ),
    )

    if not price:
        price = get_text_or_empty(
            driver,
            (
                '//p[contains(text(), "商品代金")]'
                '/parent::div/following-sibling::div'
            ),
        )

    # --- 商品ID または 注文番号 の存在待ち（最大5秒） ---
    try:
        WebDriverWait(driver, 5).until(
            lambda d: (
                d.find_elements(By.XPATH, '//p[@data-partner-id="item-id"]')
                or d.find_elements(By.XPATH, '//p[contains(text(), "注文番号")]')
            )
        )
        logger.debug("詳細の商品ID／注文番号の表示を確認しました。")

    except TimeoutException:
        save_debug_snapshot(driver, "timeout_detail_id_or_order")
        logger.warning("詳細の商品ID／注文番号の表示待ちがタイムアウトしました。")
        if not IGNORE_TIMEOUT:
            raise
        
    # 商品ID
    item_id = get_text_or_empty(
        driver,
        '//p[@data-partner-id="item-id"]',
    )

    # 注文番号
    order_number = get_text_or_empty(
        driver,
        (
            '//p[contains(text(), "注文番号")]'
            '/parent::div/following-sibling::div//p'
        ),
    )

    return {
        "price": price,
        "item_id": item_id,
        "order_number": order_number,
    }


def resolve_csv_path(
    csv_path: str,
    from_date: date,
    to_date: date
) -> Path:
    """
    CSV出力パスを決定する。

    Args:
        csv_path (str): --csv-path で指定されたパス（None可）
        from_date (date): From日付
        to_date (date): To日付

    Returns:
        Path: CSV出力パス
    """
    filename = (
        f"購入履歴_{from_date.strftime('%y%m%d')}_"
        f"{to_date.strftime('%y%m%d')}.csv"
    )

    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    # --csv-path 未指定
    if not csv_path:
        return output_dir / filename

    path = Path(csv_path)

    # 絶対パス指定
    if path.is_absolute():
        if path.is_dir():
            return path / filename
        return path

    # 相対パス指定 → output ディレクトリ基準
    resolved = output_dir / path
    if resolved.is_dir():
        return resolved / filename

    return resolved


def main() -> None:
    """
    メイン処理。
    """
    global DEBUG, IGNORE_TIMEOUT, logger

    # --- スクリプトのあるディレクトリに移動 ---
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    logger = setup_logger()
    args = parse_args()

    # --- DEBUG、IGNORE_TIMEOUT フラグ反映 ---
    DEBUG = args.debug
    IGNORE_TIMEOUT = args.ignore_timeout

    # --- 日本時間で「今日」を取得 ---
    jst = timezone(timedelta(hours=9))
    today_jst = datetime.now(jst).date()

    # from-date：省略時は「昨日」
    if args.from_date:
        from_date = datetime.strptime(args.from_date, "%Y/%m/%d").date()
    else:
        from_date = today_jst - timedelta(days=1)

    # to-date：省略時は from-date と同じ
    if args.to_date:
        to_date = datetime.strptime(args.to_date, "%Y/%m/%d").date()
    else:
        to_date = from_date
    
    # csv-path：省略時は自動生成
    csv_path = resolve_csv_path(
        args.csv_path,
        from_date,
        to_date,
    )

    # 実行条件表示
    logger.info(
        f"メルカリ購入履歴CSV出力処理を実行します。\n"
        f"　検索条件 From : {from_date.strftime("%Y/%m/%d")}\n"
        f"　検索条件 To   : {to_date.strftime("%Y/%m/%d")}\n"
        f"　CSV出力先     : {csv_path}"
    )

    driver = setup_driver()
    try:
        wait_for_manual_login(driver)

        logger.info(f"購入履歴ページ解析処理を実行します。")
        items = collect_purchase_items(
            driver,
            from_date,
            to_date,
        )
        
        logger.info(f"取引明細ページ解析処理を実行します。")
        enrich_items_with_detail(driver, items)
        
        logger.info(f"CSV出力処理を実行します。")
        write_csv(csv_path, items)

        logger.info(
            f"メルカリ購入履歴CSV出力処理が完了しました。\n"
            f"　検索条件 From : {from_date.strftime("%Y/%m/%d")}\n"
            f"　検索条件 To   : {to_date.strftime("%Y/%m/%d")}\n"
            f"　CSV出力先     : {csv_path}\n"
            f"　出力件数      : {len(items)} 件"
        )

    except Exception:
        logger.exception("予期しないエラーが発生しました。")

    finally:
        input("\nメルカリ購入履歴CSV出力処理が終了しました。Enterキーを押してください。")
        driver.quit()


if __name__ == "__main__":
    main()
