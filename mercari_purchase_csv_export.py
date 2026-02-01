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
from urllib3.exceptions import ReadTimeoutError


# =====================
# グローバル設定
# =====================
logger = None
error_count = 0
DEBUG = False
IGNORE_TIMEOUT = True
LOGIN_URL = "https://jp.mercari.com/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/143.0.0.0 Safari/537.36"
)
INTERVAL_SEC = 3.0

# =====================
# Retry / Wait 設定（チューニング用）
# =====================

# 一覧ページ用表示待ち時間
LIST_WAIT_SEC = 10

# 詳細ページ用表示待ち時間
DETAIL_WAIT_SEC = 10

# リトライ制御
RETRY_MAX_COUNT = 5          # 最大リトライ回数
RETRY_BASE_INTERVAL = 3.0    # 初期待機秒
RETRY_INTERVAL_MULTIPLIER = 2.0  # 倍率（例: 1.2 / 1.5 / 2.0）

# =====================
# 「もっと見る」対応
# =====================
MORE_CLICK_SLEEP_SEC = 3          # 「もっと見る」クリック後の待機秒
MORE_CLICK_CONFIRM_INTERVAL = 5   # 何回ごとに継続確認するか

# =====================
# 引数
# =====================
def parse_args() -> argparse.Namespace:
    """
    関数名: parse_args
    コマンドライン引数を解析する。

    引数:
        なし

    戻り値:
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
        "--stop-timeout",
        action="store_true",
        help=(
            "詳細ページの表示待ちタイムアウト時に"
            "例外を送出して処理を中断する\n"
            "省略時： 例外発生時に処理を中断しない"
        ),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    return parser.parse_args()


# =====================
# Logger
# =====================
def setup_logger() -> logging.Logger:
    """
    関数名: parse_args
    コマンドライン引数を解析する。

    引数:
        なし

    戻り値:
        argparse.Namespace: パース済み引数
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


# =====================
# Selenium
# =====================
def setup_driver() -> webdriver.Chrome:
    """
    関数名: setup_driver
    Selenium WebDriverを初期化する

    引数:
        なし

    戻り値:
        webdriver.Chrome: 初期化されたChromeドライバー
    """
    options = Options()
    options.add_argument(f"--user-agent={USER_AGENT}")
    options.add_argument("--disable-blink-features=AutomationControlled")

    service = Service()
    return webdriver.Chrome(service=service, options=options)


def wait_for_manual_login(driver: webdriver.Chrome) -> None:
    """
    関数名: wait_for_manual_login
    手動ログインを促して処理を中断する

    引数:
        driver (webdriver.Chrome): WebDriverインスタンス

    戻り値:
        None
    """
    login_url = LOGIN_URL
    # テスト用URL
    if DEBUG:
        login_url = "file:///C:/work/02_%E3%83%A1%E3%83%AB%E3%82%AB%E3%83%AA%E8%B3%BC%E5%85%A5%E5%B1%A5%E6%AD%B4CSV%E5%87%BA%E5%8A%9B/0116%E5%85%A5%E6%89%8B%E8%B3%87%E6%96%99/%E8%B3%BC%E5%85%A5%E3%81%97%E3%81%9F%E5%95%86%E5%93%81%20-%20%E3%83%86%E3%82%B9%E3%83%88.mhtml"

    driver.get(login_url)
    input(
        "【確認】\n"
        "Chromeでメルカリにログインし、\n"
        "購入履歴ページを表示したのちに Enterキーを押してください。\n"
    )


# =====================
# Utility
# =====================
def save_debug_snapshot(driver: webdriver.Chrome, prefix: str) -> None:
    """
    関数名: save_debug_snapshot
    ブラウザのスクリーンショット（PNG）とHTMLを保存する。

    引数:
        driver (webdriver.Chrome): WebDriverインスタンス
        prefix (str): ファイル名プレフィックス

    戻り値:
        None
    """
    global error_count

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
        error_count += 1

    except Exception:
        logger.exception("スナップショット保存中にエラーが発生しました。")


def resolve_csv_path(
    csv_path: str,
    from_date: date,
    to_date: date
) -> Path:
    """
    関数名: resolve_csv_path
    CSV出力パスを決定する。

    引数:
        csv_path (str): --csv-path で指定されたパス（None可）
        from_date (date): From日付
        to_date (date): To日付

    戻り値:
        Path: 解決されたCSV出力先フルパス
    """
    filename = (
        f"購入履歴_{from_date.strftime('%Y%m%d')}_"
        f"{to_date.strftime('%Y%m%d')}.csv"
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


def get_text_or_empty(
    driver: webdriver.Chrome,
    xpath: str,
) -> str:
    """
    関数名: get_text_or_empty
    XPATHに一致するすべての要素のテキストを連結して返す。
    存在しない場合は空文字を返す。

    引数:
        driver (webdriver.Chrome): WebDriverインスタンス
        xpath (str): 検索対象のXPath文字列

    戻り値:
        str: 連結されたテキストまたは空文字
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


# =====================
# Main logic
# =====================
def more_click(
    driver: webdriver.Chrome,
    DATETIME_FORMAT: str,
    from_date: date,
) -> None:
    more_click_count = 0

    while True:
        items = driver.find_elements(
            By.XPATH,
            "//ul[@data-testid='purchase-item-list']/li",
        )

        last_date_text = items[-1].find_element(
            By.XPATH,
            ".//p[@data-testid='item-label']"
            "/following-sibling::div//span",
        ).text
        last_date = datetime.strptime(last_date_text, DATETIME_FORMAT).date()

        logger.info(
            "一覧件数=%d / 最終行購入日=%s / From=%s / 判定=%s",
            len(items),
            last_date,
            from_date,
            "最終行 ＜ From" if last_date and last_date < from_date else "最終行 ≧ From",
        )

        # 最終行 < From → この一覧で処理開始
        if last_date and last_date < from_date:
            return

        # From <= 最終行 → もっと見る
        try:
            more_click_count += 1
            logger.info("「もっと見る」クリック %d 回目", more_click_count)

            # 5回ごとに継続確認
            if more_click_count % MORE_CLICK_CONFIRM_INTERVAL == 0:
                c = input(
                    "[C] 継続 / [E] 中止 → "
                ).strip().upper()
                if c == "E":
                    logger.info("ユーザー操作により処理を中止しました。")
                    raise Exception("「もっと見る」クリックにて処理を中止しました")

            more_btn = driver.find_element(
                By.XPATH,
                '//button//span[contains(text(),"もっと見る")]'
            )
            more_btn.click()
            sleep(MORE_CLICK_SLEEP_SEC)

        except WebDriverException:
            # クリックできないとき、再度ページを確認
            logger.exception("「もっと見る」ボタンが見つかりません。")
            input(
                "【確認】購入履歴ページを再表示したら Enterキーを押してください。"
            )
            # 再トライ
            continue

    return


def collect_purchase_items(
    driver: webdriver.Chrome,
    from_date: date,
    to_date: date,
) -> List[Dict[str, str]]:
    """
    関数名: collect_purchase_items
    購入履歴から対象明細を抽出する

    引数:
        driver (webdriver.Chrome): WebDriverインスタンス
        from_date (date): 抽出開始日
        to_date (date): 抽出終了日

    戻り値:
        List[Dict[str, str]]: 商品名、購入日時、詳細ページURLを含む辞書のリスト
    """
    DATETIME_FORMAT = "%Y/%m/%d %H:%M"

    results: List[Dict[str, str]] = []

    # --- 商品代金 要素の表示待ち ---
    try:
        WebDriverWait(driver, LIST_WAIT_SEC).until(
            EC.visibility_of_element_located(
                (By.XPATH, "//ul[@data-testid='purchase-item-list']/li")
            )
        )
        logger.debug("購入履歴の一覧表の表示を確認しました。")
    except TimeoutException:
        save_debug_snapshot(driver, "timeout_purchase_list_")
        logger.warning(
            "購入履歴の一覧表の表示待ちがタイムアウトしました。"
            "ページを再表示してください。"
        )
        input(
            "【確認】購入履歴ページを再表示したら Enterキーを押してください。"
        )
        # 再トライ
        return collect_purchase_items(driver, from_date, to_date)

    # 「もっと見る」クリック対応
    more_click(driver, DATETIME_FORMAT, from_date)

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
    関数名: enrich_items_with_detail
    明細ごとに詳細ページを開き、
    金額・商品ID／注文番号を items に追記する（破壊的更新）

    引数:
        driver (webdriver.Chrome): WebDriverインスタンス
        items (List[Dict[str, str]]): 更新対象の商品情報のリスト

    戻り値:
        None
    """
    total = len(items)

    if total == 0:
        logger.info("詳細取得対象の明細はありません。")
        return
    
    for index, item in enumerate(items, start=1):
        detail_url = item["detail_url"]
        # テスト用URL
        if DEBUG:
            detail_url = "file:///C:/work/02_%E3%83%A1%E3%83%AB%E3%82%AB%E3%83%AA%E8%B3%BC%E5%85%A5%E5%B1%A5%E6%AD%B4CSV%E5%87%BA%E5%8A%9B/0116%E5%85%A5%E6%89%8B%E8%B3%87%E6%96%99/%E5%8F%96%E5%BC%95%E7%94%BB%E9%9D%A2%20-%20%E3%83%A1%E3%83%AB%E3%82%AB%E3%83%AA.mhtml"

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
    """
    関数名: write_csv
    CSVファイルを出力する

    引数:
        csv_path (str): 出力先パス
        items (List[Dict[str, str]]): 出力データ（辞書のリスト）

    戻り値:
        None
    """
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


def fetch_purchase_detail(
    driver: webdriver.Chrome,
    detail_url: str,
) -> Dict[str, str]:
    """
    関数名: fetch_purchase_detail
    詳細URLを開き、金額・商品ID・注文番号を取得する

    引数:
        driver (webdriver.Chrome): WebDriverインスタンス
        detail_url (str): 詳細ページURL
    
    戻り値:
        Dict[str, str]: "price", "item_id", "order_number" をキーに持つ辞書
    """
    last_exception: Exception | None = None

    for retry in range(1, RETRY_MAX_COUNT + 1):
        try:
            logger.info(
                f"詳細取得開始 retry={retry}/{RETRY_MAX_COUNT} url={detail_url}"
            )

            # --- URLアクセス ---
            driver.get(detail_url)

            # --- 商品代金 要素の表示待ち ---
            try:
                WebDriverWait(driver, DETAIL_WAIT_SEC).until(
                    lambda d: (
                        d.find_elements(By.XPATH, '//span[contains(text(), "商品代金")]')
                        or d.find_elements(By.XPATH, '//p[contains(text(), "商品代金")]')
                    )
                )
            except TimeoutException as e:
                label = "商品代金"
                raise TimeoutException(f"timeout at [{label}]") from e

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

            # --- 商品ID または 注文番号 要素の表示待ち ---
            try:
                WebDriverWait(driver, DETAIL_WAIT_SEC).until(
                    lambda d: (
                        d.find_elements(By.XPATH, '//p[@data-partner-id="item-id"]')
                        or d.find_elements(By.XPATH, '//p[contains(text(), "注文番号")]')
                    )
                )
            except TimeoutException as e:
                label = "商品ID／注文番号"
                raise TimeoutException(f"timeout at [{label}]") from e

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

            # --- リトライ条件判定 ---
            if price and (item_id or order_number):
                return {
                    "price": price,
                    "item_id": item_id,
                    "order_number": order_number,
                }

            logger.warning(
                f"取得条件未達（price:{price} / item_id:{item_id} / order_number:{order_number} 不足）"
            )

        except Exception as e:
            if isinstance(e, (TimeoutException, WebDriverException, ReadTimeoutError)):
                # 想定内エラー
                logger.warning(
                    "詳細取得リトライ %d/%d 失敗: %s: %s",
                    retry,
                    RETRY_MAX_COUNT,
                    type(e).__name__,
                    str(e).rstrip(),
                )
                last_exception = e
            else:
                # 想定外
                logger.exception("想定外エラーが発生しました。")
                last_exception = e
                break

        # --- リトライ待機 ---
        if retry < RETRY_MAX_COUNT:
            wait_sec = RETRY_BASE_INTERVAL * (RETRY_INTERVAL_MULTIPLIER ** (retry - 1))
            logger.info(f"{wait_sec} 秒後にリトライします。")
            sleep(wait_sec)

    # --- リトライアウト ---
    save_debug_snapshot(driver, f"retryout_detail_r{RETRY_MAX_COUNT}")
    logger.error("詳細取得がリトライアウトしました。")

    if last_exception:
        logger.error(f"最終エラー内容: {str(last_exception).rstrip()}")
        if not IGNORE_TIMEOUT:
            raise RuntimeError(
                f"詳細取得リトライアウト: {detail_url}"
            ) from last_exception
        
    return {
        "price": "",
        "item_id": "",
        "order_number": "",
    }


def execute_once(
    driver: webdriver.Chrome,
    from_date: date,
    to_date: date,
    csv_path: Path,
) -> None:
    """
    関数名: execute_once
    一連の解析・出力処理を1回実行する

    引数:
        driver (webdriver.Chrome): WebDriverインスタンス
        from_date (date): 検索条件 From
        to_date (date): 検索条件 To
        csv_path (Path): 出力先CSVパス

    戻り値:
        None
    """
    global error_count
    error_count = 0

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

    if error_count > 0:
        error_count_info = f"{error_count} 件  ★★★  ログファイルとスナップショットファイルをご確認ください  ★★★"
    else:
        error_count_info = f"{error_count} 件"
        
    logger.info(
        f"メルカリ購入履歴CSV出力処理が完了しました。\n"
        f"　検索条件 From : {from_date.strftime("%Y/%m/%d")}\n"
        f"　検索条件 To   : {to_date.strftime("%Y/%m/%d")}\n"
        f"　CSV出力先     : {csv_path}\n"
        f"　出力件数      : {len(items)} 件\n"
        f"　エラー件数    : {error_count_info}"
    )


# =====================
# Interactive prompt
# =====================
def prompt_reexecute_params(
    from_date: date,
    to_date: date,
    csv_path: Path,
) -> tuple[date, date, Path]:
    """
    関数名: prompt_reexecute_params
    再実行用のパラメータを対話形式で入力・確認する

    引数:
        from_date (date): 現在の From日付
        to_date (date): 現在の To日付
        csv_path (Path): 現在の CSVパス

    戻り値:
        tuple[date, date, Path]: (新From日付, 新To日付, 新CSVパス)
    """
    while True:
        print("\n【入力】検索条件を入力してください。")
        # From
        while True:
            s = input(
                f"検索条件 From yyyy/mm/dd [{from_date.strftime('%Y/%m/%d')}] : "
            ).strip()
            if not s:
                break
            try:
                from_date = datetime.strptime(s, "%Y/%m/%d").date()
                break
            except ValueError:
                print("日付形式が不正です。yyyy/mm/dd で入力してください。")

        # To
        while True:
            s = input(
                f"検索条件 To   yyyy/mm/dd [{to_date.strftime('%Y/%m/%d')}] : "
            ).strip()
            if not s:
                break
            try:
                to_date = datetime.strptime(s, "%Y/%m/%d").date()
                break
            except ValueError:
                print("日付形式が不正です。yyyy/mm/dd で入力してください。")

        default_csv = resolve_csv_path(None, from_date, to_date)

        s = input(f"CSV出力先 [{default_csv}] : ").strip()
        new_csv = (
            resolve_csv_path(s, from_date, to_date)
            if s else default_csv
        )

        print("\n【確認】入力内容を確認してください。\n"
            f"　検索条件 From : {from_date.strftime("%Y/%m/%d")}\n"
            f"　検索条件 To   : {to_date.strftime("%Y/%m/%d")}\n"
            f"　CSV出力先     : {new_csv}"
        )

        while True:
            print("\n【注意】[C] 続行 を行う前に購入履歴ページを表示してください。")
            c = input("[C] 続行 / [R] 再入力 / [E] 終了 → ").strip().upper()
            if c in ("C", "R", "E"):
                break
            print("入力が不正です。C / R / E を入力してください。")

        if c == "C":
            return from_date, to_date, new_csv
        if c == "E":
            raise SystemExit


# =====================
# main
# =====================
def main() -> None:
    """
    関数名: main
    メイン処理。引数の解析、ドライバ起動、ループ処理を制御する。

    引数:
        なし

    戻り値:
        None
    """
    global DEBUG, IGNORE_TIMEOUT, logger

    # --- スクリプトのあるディレクトリに移動 ---
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    logger = setup_logger()
    args = parse_args()

    # --- DEBUG、IGNORE_TIMEOUT フラグ反映 ---
    DEBUG = args.debug
    IGNORE_TIMEOUT = not args.stop_timeout

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
    
    # csv-path：自動生成
    csv_path = resolve_csv_path(
        None,
        from_date,
        to_date,
    )

    driver = setup_driver()
    try:
        wait_for_manual_login(driver)

        while True:
            try:
                from_date, to_date, csv_path = prompt_reexecute_params(
                    from_date, to_date, csv_path
                )
            except SystemExit:
                break

            # 実行条件表示
            logger.info(
                f"メルカリ購入履歴CSV出力処理を実行します。\n"
                f"　検索条件 From : {from_date.strftime("%Y/%m/%d")}\n"
                f"　検索条件 To   : {to_date.strftime("%Y/%m/%d")}\n"
                f"　CSV出力先     : {csv_path}"
            )
            try:
                execute_once(driver, from_date, to_date, csv_path)
            except Exception:
                logger.exception("予期しないエラーが発生しました。")

            while True:
                cmd = input(
                    "\n[E] + Enter: 終了 / [R] + Enter: 再実行 → "
                ).strip().upper()
                if cmd in ("E", "R"):
                    break
                print("入力が不正です。E または R を入力してください。")

            if cmd == "E":
                break

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
