import argparse
import csv
import logging
import os
import sys
from datetime import datetime, timedelta, date, timezone
from pathlib import Path
from time import sleep
from typing import List, Dict, Optional

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
# Seleium
# =====================
driver = None
tabs = None
PROFILE_DIR = Path.home() / "AppData" / "Local" / "selenium_chrome"
PURCHASES_URL = "https://jp.mercari.com/mypage/purchases"

# =====================
# ログ
# =====================
APP_NAME = "mercari"
APP_LOG_LEVEL =logging.DEBUG
logger = logging.getLogger(APP_NAME)

# =====================
# Retry / Wait 設定（チューニング用）
# =====================

# 一覧ページ用表示待ち時間
LIST_WAIT_SEC = 10

# 詳細ページ用表示待ち時間
DETAIL_WAIT_SEC = 10

# リトライ制御
RETRY_MAX_COUNT = 5               # 最大リトライ回数
RETRY_BASE_INTERVAL = 3.0         # 初回待機秒
RETRY_INTERVAL_MULTIPLIER = 2.0   # 倍率（例: 1.2 / 1.5 / 2.0）

# =====================
# 「もっと見る」対応
# =====================
MORE_CLICK_SLEEP_SEC = 3.0         # 「もっと見る」クリック後の初回待機秒
MORE_CLICK_SLEEP_MULTIPLIER = 2.0  # 倍率（例: 1.2 / 1.5 / 2.0）
MORE_CLICK_CONFIRM_INTERVAL = 1000 # 何回ごとに継続確認するか
MAX_NO_GROW_COUNT = 5              # 行数が増えない状態の許容回数

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
def setup_logger() -> None:
    """
    関数名: setup_logger
    ルートロガーを初期化し、標準出力およびログファイルへ出力する。

    引数:
        なし

    戻り値:
        None
    """
    jst = timezone(timedelta(hours=9))
    today = datetime.now(jst).strftime("%Y%m%d")

    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    log_file = log_dir / f"mercari_purchase_csv_export_{today}.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
    )

    # --- 重複handler防止 ---
    if root_logger.handlers:
        return

    # --- Console ---
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    # --- File ---
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)


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
    options.add_argument(f"--user-data-dir={PROFILE_DIR}")

    service = Service()
    return webdriver.Chrome(service=service, options=options)


def wait_for_manual_login(driver: webdriver.Chrome, tabs: TabController) -> None:
    """
    関数名: wait_for_manual_login
    手動ログインを促して処理を中断する

    引数:
        driver (webdriver.Chrome): WebDriverインスタンス
        tabs (TabController): タブ管理クラス

    戻り値:
        None
    """
    login_url = LOGIN_URL
    # テスト用URL
    if DEBUG:
        login_url = "file:///C:/work/02_%E3%83%A1%E3%83%AB%E3%82%AB%E3%83%AA%E8%B3%BC%E5%85%A5%E5%B1%A5%E6%AD%B4CSV%E5%87%BA%E5%8A%9B/0116%E5%85%A5%E6%89%8B%E8%B3%87%E6%96%99/%E8%B3%BC%E5%85%A5%E3%81%97%E3%81%9F%E5%95%86%E5%93%81%20-%20%E3%83%86%E3%82%B9%E3%83%88.mhtml"

    tabs.use_list_page()
    driver.get(login_url)
    input(
        "【確認】\n"
        "Chromeでメルカリにログインし、\n"
        "購入履歴ページを表示したのちに Enterキーを押してください。\n"
    )


# =====================
# タブ管理クラス
# =====================
class TabController:
    """
    Selenium のタブ管理を完全に隠蔽するクラス。

    - 一覧ページタブ
    - 詳細ページタブ（1タブ再利用）

    責務:
        - タブの作成
        - タブの切替
        - 手動クローズ時の自動復旧
        - 最低限の安定待機（document.readyState）
    """

    def __init__(self, driver: webdriver.Chrome) -> None:
        """
        関数名: __init__
        TabController を初期化する。

        引数:
            driver (webdriver.Chrome): Selenium WebDriver
        """
        self.driver = driver
        self._list_tab: Optional[str] = None
        self._detail_tab: Optional[str] = None

    def _is_tab_alive(self, handle: Optional[str]) -> bool:
        """
        関数名: _is_tab_alive
        指定したタブハンドルが現在も存在するか確認する。

        引数:
            handle (Optional[str]): ウィンドウハンドル

        戻り値:
            bool: 存在していれば True
        """
        return handle is not None and handle in self.driver.window_handles

    def _wait_document_ready(self, timeout: int = 5) -> None:
        """
        関数名: _wait_document_ready
        document.readyState == 'complete' になるまで待機する。

        - about:blank の場合は即時通過
        - DOM 未初期化による事故を防ぐための最小待機

        引数:
            なし

        戻り値:
            None
        """
        WebDriverWait(self.driver, timeout).until(
            lambda d: d.execute_script(
                "return document.readyState"
            ) == "complete"
        )

    def use_list_page(self) -> None:
        """
        関数名: use_list_page
        一覧ページタブを利用する。

        - 未登録、または手動で閉じられていた場合:
            - 現在のタブを一覧ページタブとして再登録
        - 登録済みの場合:
            - 一覧ページタブへ切り替え

        切替後は document.readyState を待機する。

        引数:
            なし

        戻り値:
            None
        """
        if not self._is_tab_alive(self._list_tab):
            self._list_tab = self.driver.current_window_handle
            self._wait_document_ready()
            return

        self.driver.switch_to.window(self._list_tab)
        self._wait_document_ready()

    def use_detail_page(self) -> None:
        """
        関数名: use_detail_page
        詳細ページタブを利用する。

        - 未登録、または手動で閉じられていた場合:
            - 新規タブを作成
        - 登録済みの場合:
            - 詳細ページタブへ切り替え

        切替後は document.readyState を待機する。

        引数:
            なし

        戻り値:
            None
        """
        if not self._is_tab_alive(self._detail_tab):
            self.driver.execute_script("window.open();")
            self._detail_tab = self.driver.window_handles[-1]
            self.driver.switch_to.window(self._detail_tab)
            self._wait_document_ready()
            return

        self.driver.switch_to.window(self._detail_tab)
        self._wait_document_ready()


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

        logger.info("スナップショット保存(PNG): %s", png_path)
        logger.info("スナップショット保存(HTML): %s", html_path)
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


def append_csv(
    path: Path,
    rows: List[Dict[str, str]],
) -> None:
    """
    関数名: append_csv
    CSVファイルに購入履歴データを追記する。

    引数:
        path (Path): 出力先CSVパス
        rows (List[Dict[str, str]]): 追記する購入履歴データ

    戻り値:
        None
    """
    is_new = not path.exists()

    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(
                [
                    "No.",
                    "商品名",
                    "金額",
                    "購入日時",
                    "商品ID／注文番号",
                    "詳細ページ",
                ]
            )

        for r in rows:
            writer.writerow(
                [
                    r.get("no", ""),
                    r["item_name"],
                    r.get("price", ""),
                    r["purchase_datetime"],
                    r.get("item_or_order_id", ""),
                    r["detail_url"],
                ]
            )


# =====================
# Main logic
# =====================
def extract_new_rows(
    items,
    start_index: int,
    from_date: date,
    to_date: date,
    datetime_format: str,
    already_output_count: int,
) -> tuple[List[Dict[str,str]], bool, int]:
    """
    関数名: extract_new_rows
    購入履歴情報リストの追加分からCSV追記用データを抽出する

    引数:
        items (List[Dict[str, str]]): 購入履歴情報リスト（全件）
        start_index (int): 処理開始リスト番号
        from_date (date): 抽出開始日
        to_date (date): 抽出終了日
        datetime_format (str): 日付フォーマット
        already_output_count (int): 出力件数（出力済）

    戻り値:
        rows (List[Dict[str, str]]): CSV追記用データ
        reached_past (bool): Fromより過去に到達したか
        total_write_count (int): 出力件数（総件数）
    """
    global driver, tabs
    rows = []
    total_output_count = already_output_count

    # --- JSで全行の必要情報を一括取得 (通信はここでの1回のみ) ---
    js_code = """
return Array.from(document.querySelectorAll("ul[data-testid='purchase-item-list'] > li")).map(li => {
    const a = li.querySelector("a");
    const nameElem = li.querySelector("[data-testid='item-label']");
    
    // 対策: 複数の候補から日付テキストを探す
    let dateText = "";
    if (nameElem) {
        // 1. 商品名要素の親から見て、日付らしい形式のテキストを持つ要素を検索
        const container = li.innerText;
        const dateMatch = container.match(/\d{4}\/\d{2}\/\d{2} \d{2}:\d{2}/);
        if (dateMatch) {
            dateText = dateMatch[0];
        } else {
            // 2. 正規表現で見つからない場合、従来のセレクタの周辺をより広く探索
            const spans = li.querySelectorAll("span");
            for (let s of spans) {
                if (s.textContent.includes("/") && s.textContent.includes(":")) {
                    dateText = s.textContent.trim();
                    break;
                }
            }
        }
    }

    return {
        url: a ? a.href : "",
        name: nameElem ? nameElem.textContent.trim() : "不明な商品",
        date: dateText
    };
});
"""
    all_items_data = driver.execute_script(js_code)
    
    for item in all_items_data[start_index:]:
        detail_url = item["url"]
        item_name = item["name"]
        dt_text = item["date"]
        print(item)

        purchase_dt = datetime.strptime(dt_text, datetime_format)
        purchase_date = purchase_dt.date()

        if purchase_date < from_date:
            return rows, True, total_output_count

        if from_date <= purchase_date <= to_date:
            total_output_count += 1
            rows.append(
                {
                    "no": total_output_count,
                    "detail_url": detail_url,
                    "item_name": item_name,
                    "purchase_datetime": purchase_dt.strftime(datetime_format),
                }
            )

    return rows, False, total_output_count


def collect_purchase_items(
    # driver: webdriver.Chrome,
    # tabs: TabController,
    from_date: date,
    to_date: date,
    csv_path: str,
) -> int:
    """
    関数名: collect_purchase_items
    購入履歴から対象明細を抽出しCSV出力する

    引数:
        driver (webdriver.Chrome): WebDriverインスタンス
        tabs (TabController): タブ管理クラス
        from_date (date): 抽出開始日
        to_date (date): 抽出終了日
        csv_path (Path): 出力先CSVパス

    戻り値:
        int: 出力件数
    """
    global driver, tabs
    DATETIME_FORMAT = "%Y/%m/%d %H:%M"
    
    # --- CSVファイルがあれば削除 ---
    if csv_path.exists():
        logger.info("CSVファイルを削除します: %s", csv_path)
        csv_path.unlink()

    # --- 購入履歴の一覧表 要素の表示待ち ---
    while True:
        try:
            tabs.use_list_page()
            WebDriverWait(driver, LIST_WAIT_SEC).until(
                EC.visibility_of_element_located(
                    (By.XPATH, "//ul[@data-testid='purchase-item-list']/li")
                )
            )
            logger.info("購入履歴の一覧表の表示を確認しました。")
            break
        except TimeoutException:
            save_debug_snapshot(driver, "timeout_purchase_list")
            logger.warning("購入履歴の一覧表の表示待ちでタイムアウトしました。")
            input(
                "【確認】購入履歴ページを再表示したのちに Enterキーを押してください。\n"
            )
        
    processed_count = 0  # 前回処理済みの一覧行数
    no_grow_count = 0    # 行数が増えなかった連続回数
    more_click_count = 0 # 「もっと見る」クリック回数
    output_count = 0     # CSVファイルのNo.

    while True:
        tabs.use_list_page()
        items = driver.find_elements(
            By.XPATH,
            "//ul[@data-testid='purchase-item-list']/li",
        )
        # 処理経過表示
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

        # 追加行を抽出
        rows, reached_past, output_count = extract_new_rows(
            items,
            processed_count,
            from_date,
            to_date,
            DATETIME_FORMAT,
            output_count,
        )

        # 追加行を一時ファイル出力
        if rows:
            logger.info(f"購入履歴ページ解析処理を実行します。")
            enrich_items_with_detail(rows)

            logger.info(f"CSV出力処理を実行します。")
            append_csv(csv_path, rows)

        if reached_past:
            logger.info(
                "Fromより過去に到達したため、"
                "一覧ページのデータ抽出処理を終了します。"
            )
            break
        
        # 行数増加の無のとき、カウントアップ／有のとき、リセット
        if processed_count == len(items):
            no_grow_count += 1
        else:
            no_grow_count = 0

        if no_grow_count >= MAX_NO_GROW_COUNT:
            logger.info(
                f"行数増加なし連続回数が許容回数（{MAX_NO_GROW_COUNT}回）を超過したため、"
                "一覧ページからデータ抽出処理を終了します。"
            )
            break

        processed_count = len(items)
        more_click_count += 1
        wait_sec = MORE_CLICK_SLEEP_SEC * (MORE_CLICK_SLEEP_MULTIPLIER ** (no_grow_count))
        logger.info(f"[もっと見る]クリック {more_click_count} 回目、{wait_sec} 秒後に一覧ページを確認します。")

        # 5回ごとに継続確認
        if more_click_count % MORE_CLICK_CONFIRM_INTERVAL == 0:
            c = input(
                "[C] 継続 / [E] 中止 → "
            ).strip().upper()
            if c == "E":
                logger.info(
                    "ユーザー操作により一覧ページのデータ抽出処理を中止し、"
                    f"抽出済データ[{processed_count}件]で処理を継続します。"
                )
                break    
        
        # 「もっと見る」クリック
        try:
            tabs.use_list_page()
            more_btn = driver.find_element(
                By.XPATH,
                '//button//span[contains(text(),"もっと見る")]'
            )
            more_btn.click()
            sleep(wait_sec)

        except WebDriverException:
            # クリックできないとき、再度ページを確認
            logger.exception("「もっと見る」ボタンが見つかりません。")
            input(
                "【確認】購入履歴ページを再表示したのちに Enterキーを押してください。\n"
            )
            # 再トライ
            continue

    return output_count


def enrich_items_with_detail(
    # driver: webdriver.Chrome,
    # tabs: TabController,
    items: List[Dict[str, str]],
) -> None:
    """
    関数名: enrich_items_with_detail
    明細ごとに詳細ページを開き、
    金額・商品ID／注文番号を items に追記する（破壊的更新）

    引数:
        driver (webdriver.Chrome): WebDriverインスタンス
        tabs (TabController): タブ管理クラス
        items (List[Dict[str, str]]): 更新対象の商品情報のリスト

    戻り値:
        None
    """
    global driver, tabs
    total = len(items)

    if total == 0:
        logger.info("詳細取得対象の明細はありません。")
        return
    
    for index, item in enumerate(items, start=1):
        detail_url = item["detail_url"]
        # テスト用URL
        if DEBUG:
            detail_url = "file:///C:/work/02_%E3%83%A1%E3%83%AB%E3%82%AB%E3%83%AA%E8%B3%BC%E5%85%A5%E5%B1%A5%E6%AD%B4CSV%E5%87%BA%E5%8A%9B/0116%E5%85%A5%E6%89%8B%E8%B3%87%E6%96%99/%E5%8F%96%E5%BC%95%E7%94%BB%E9%9D%A2%20-%20%E3%83%A1%E3%83%AB%E3%82%AB%E3%83%AA.mhtml"

        detail = fetch_purchase_detail(detail_url)

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


def fetch_purchase_detail(
    # driver: webdriver.Chrome,
    # tabs: TabController,
    detail_url: str,
) -> Dict[str, str]:
    """
    関数名: fetch_purchase_detail
    詳細URLを開き、金額・商品ID・注文番号を取得する

    引数:
        driver (webdriver.Chrome): WebDriverインスタンス
        tabs (TabController): タブ管理クラス
        detail_url (str): 詳細ページURL
    
    戻り値:
        Dict[str, str]: "price", "item_id", "order_number" をキーに持つ辞書
    """
    global driver, tabs
    last_exception: Exception | None = None

    for retry in range(1, RETRY_MAX_COUNT + 1):
        try:
            logger.info(
                f"詳細取得開始 retry={retry}/{RETRY_MAX_COUNT} url={detail_url}"
            )

            # --- URLアクセス ---
            tabs.use_detail_page()
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

                driver = setup_driver()
                tabs = TabController(driver)
                wait_for_manual_login(driver, tabs)

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
    # driver: webdriver.Chrome,
    # tabs: TabController,
    from_date: date,
    to_date: date,
    csv_path: Path,
) -> None:
    """
    関数名: execute_once
    一連の解析・出力処理を1回実行する

    引数:
        driver (webdriver.Chrome): WebDriverインスタンス
        tabs (TabController): タブ管理クラス
        from_date (date): 検索条件 From
        to_date (date): 検索条件 To
        csv_path (Path): 出力先CSVパス

    戻り値:
        None
    """
    global driver, tabs
    global error_count
    error_count = 0

    logger.info(f"購入履歴ページ解析処理を実行します。")
    no_write_count = collect_purchase_items(
        # driver,
        # tabs,
        from_date,
        to_date,
        csv_path,
    )
    
    if error_count > 0:
        error_count_info = f"{error_count} 件  ★★★  ログファイルとスナップショットファイルをご確認ください  ★★★"
    else:
        error_count_info = f"{error_count} 件"
        
    logger.info(
        f"メルカリ購入履歴CSV出力処理が完了しました。\n"
        f"　検索条件 From : {from_date.strftime('%Y/%m/%d')}\n"
        f"　検索条件 To   : {to_date.strftime('%Y/%m/%d')}\n"
        f"　CSV出力先     : {csv_path}\n"
        f"　出力件数      : {no_write_count} 件\n"
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
                new_to_date = datetime.strptime(s, "%Y/%m/%d").date()
                if new_to_date < from_date:
                    print(f"To は From [{from_date.strftime('%Y/%m/%d')}] 以降で入力してください。")
                    continue
                to_date = new_to_date
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
            f"　検索条件 From : {from_date.strftime('%Y/%m/%d')}\n"
            f"　検索条件 To   : {to_date.strftime('%Y/%m/%d')}\n"
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
    global DEBUG, IGNORE_TIMEOUT
    global driver, tabs

    # --- スクリプトのあるディレクトリに移動 ---
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    setup_logger()
    logging.getLogger(APP_NAME).setLevel(APP_LOG_LEVEL)
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
    tabs = TabController(driver)
    try:
        wait_for_manual_login(driver, tabs)

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
                f"　検索条件 From : {from_date.strftime('%Y/%m/%d')}\n"
                f"　検索条件 To   : {to_date.strftime('%Y/%m/%d')}\n"
                f"　CSV出力先     : {csv_path}"
            )
            try:
                execute_once(from_date, to_date, csv_path)
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
