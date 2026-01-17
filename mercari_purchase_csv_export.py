import argparse
import csv
from datetime import datetime, timedelta, date
from time import sleep
from typing import List, Dict

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import WebDriverException

DATETIME_FORMAT = "%Y/%m/%d %H:%M"
LOGIN_URL = "https://jp.mercari.com/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/143.0.0.0 Safari/537.36"
)
INTERVAL_SEC = 3.0


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を解析する"""
    today = date.today()
    default_from = today.strftime("%Y/%m/%d")

    parser = argparse.ArgumentParser(description="メルカリ購入履歴CSV出力")
    parser.add_argument(
        "--from-date",
        default=default_from,
        help="出力対象From日付 (yyyy/mm/dd)",
    )
    parser.add_argument(
        "--to-date",
        default=default_from,
        help="出力対象To日付 (yyyy/mm/dd)",
    )
    parser.add_argument(
        "--csv-path",
        default="購入履歴.csv",
        help="出力CSVファイルパス",
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
    # ★ToDo★ コメントアウト：テスト用URL
    # LOGIN_URL = "file:///C:/work/02_%E3%83%A1%E3%83%AB%E3%82%AB%E3%83%AA%E8%B3%BC%E5%85%A5%E5%B1%A5%E6%AD%B4CSV%E5%87%BA%E5%8A%9B/%E8%B3%BC%E5%85%A5%E3%81%97%E3%81%9F%E5%95%86%E5%93%81%20-%20%E3%83%A1%E3%83%AB%E3%82%AB%E3%83%AA.mhtml"
    driver.get(LOGIN_URL)
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
        print("詳細取得対象の明細はありません。")
        return
    
    for index, item in enumerate(items, start=1):
        detail_url = item["detail_url"]
        # ★ToDo★ コメントアウト：テスト用URL
        # detail_url = "file:///C:/work/02_%E3%83%A1%E3%83%AB%E3%82%AB%E3%83%AA%E8%B3%BC%E5%85%A5%E5%B1%A5%E6%AD%B4CSV%E5%87%BA%E5%8A%9B/%E5%8F%96%E5%BC%95%E7%94%BB%E9%9D%A2%20-%20%E3%83%A1%E3%83%AB%E3%82%AB%E3%83%AA.mhtml"

        detail = fetch_purchase_detail(driver, detail_url)

        item["price"] = detail["price"]

        # 商品ID優先、なければ注文番号
        if detail["item_id"]:
            item["item_or_order_id"] = detail["item_id"]
        else:
            item["item_or_order_id"] = detail["order_number"]

        # 5件ごと、または最終件で進捗表示
        if index % 5 == 0 or index == total:
            progress = (index / total) * 100
            print(
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

    Returns:
        {
            "price": str,
            "item_id": str,
            "order_number": str,
        }
    """
    driver.get(detail_url)

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

    item_id = get_text_or_empty(
        driver,
        '//p[@data-partner-id="item-id"]',
    )

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


def main() -> None:
    args = parse_args()

    from_date = datetime.strptime(args.from_date, "%Y/%m/%d").date()
    to_date = datetime.strptime(args.to_date, "%Y/%m/%d").date()

    driver = setup_driver()
    try:
        wait_for_manual_login(driver)

        print(f"\n{datetime.now()}: 購入履歴ページ解析処理を実行します。")
        items = collect_purchase_items(
            driver,
            from_date,
            to_date,
        )
        
        print(f"\n{datetime.now()}: 取引明細ページ解析処理を実行します。")
        enrich_items_with_detail(driver, items)
        
        print(f"\n{datetime.now()}: CSV出力処理を実行します。")
        write_csv(args.csv_path, items)

        print(
            f"\n{datetime.now()}: 処理が完了しました。\n"
            f"検索条件 From : {args.from_date}\n"
            f"検索条件 To   : {args.to_date}\n"
            f"CSV出力先     : {args.csv_path}\n"
            f"出力件数      : {len(items)} 件"
        )

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
