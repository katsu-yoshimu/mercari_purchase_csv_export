from typing import Optional

import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

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
        TabController を初期化する。

        Args:
            driver (webdriver.Chrome): Selenium WebDriver
        """
        self.driver = driver
        self._list_tab: Optional[str] = None
        self._detail_tab: Optional[str] = None

    def _is_tab_alive(self, handle: Optional[str]) -> bool:
        """
        指定したタブハンドルが現在も存在するか確認する。

        Args:
            handle (Optional[str]): ウィンドウハンドル

        Returns:
            bool: 存在していれば True
        """
        return handle is not None and handle in self.driver.window_handles

    def _wait_document_ready(self, timeout: int = 5) -> None:
        """
        document.readyState == 'complete' になるまで待機する。

        - about:blank の場合は即時通過
        - DOM 未初期化による事故を防ぐための最小待機
        """
        WebDriverWait(self.driver, timeout).until(
            lambda d: d.execute_script(
                "return document.readyState"
            ) == "complete"
        )

    def use_list_page(self) -> None:
        """
        一覧ページタブを利用する。

        - 未登録、または手動で閉じられていた場合:
            - 現在のタブを一覧ページタブとして再登録
        - 登録済みの場合:
            - 一覧ページタブへ切り替え

        切替後は document.readyState を待機する。
        """
        if not self._is_tab_alive(self._list_tab):
            self._list_tab = self.driver.current_window_handle
            self._wait_document_ready()
            return

        self.driver.switch_to.window(self._list_tab)
        self._wait_document_ready()

    def use_detail_page(self) -> None:
        """
        詳細ページタブを利用する。

        - 未登録、または手動で閉じられていた場合:
            - 新規タブを作成
        - 登録済みの場合:
            - 詳細ページタブへ切り替え

        切替後は document.readyState を待機する。
        """
        if not self._is_tab_alive(self._detail_tab):
            self.driver.execute_script("window.open();")
            self._detail_tab = self.driver.window_handles[-1]
            self.driver.switch_to.window(self._detail_tab)
            self._wait_document_ready()
            return

        self.driver.switch_to.window(self._detail_tab)
        self._wait_document_ready()
