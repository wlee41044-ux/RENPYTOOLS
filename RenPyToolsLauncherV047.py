#!/usr/bin/env python3
import os
import subprocess
import sys
import webbrowser
from tkinter import messagebox, ttk

import RenPyToolsApp as ui_module
from RenPyToolsLauncher import RenPyToolsV046, run_all_self_tests as run_v046_tests

ui_module.UI_VERSION = "0.4.7"
CHATGPT_URL = "https://chatgpt.com/"


class RenPyToolsV047(RenPyToolsV046):
    """v0.4.7: add a phone-friendly ChatGPT handoff from the semi-auto HQ screen."""

    def __init__(self):
        super().__init__()
        ui_module.UI_VERSION = "0.4.7"
        self.title("RenPy Tools 0.4.7")
        self.render()

    def page_hq_ready(self):
        super().page_hq_ready()

        handoff = ttk.Frame(self.container)
        handoff.pack(fill="x", padx=60, pady=(8, 0))
        ttk.Button(
            handoff,
            text="ChatGPT 열기",
            style="Primary.TButton",
            command=self.open_chatgpt,
        ).pack(side="left")
        ttk.Button(
            handoff,
            text="ChatGPT 열고 '다음' 복사",
            style="Secondary.TButton",
            command=self.open_chatgpt_with_next,
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            handoff,
            text="분할 화면 사용법",
            style="Secondary.TButton",
            command=self.show_split_screen_help,
        ).pack(side="left", padx=(8, 0))
        ttk.Label(
            handoff,
            text="Android 분할 화면 자체는 기기 기능이라 RenPy Tools가 강제로 고정할 수는 없어요.",
            style="Subtitle.TLabel",
        ).pack(side="left", padx=(14, 0))

    def _try_open_url(self, url):
        """Best-effort URL handoff. Works on Windows and does not crash under Wine/Winlator."""
        errors = []
        try:
            if hasattr(os, "startfile"):
                os.startfile(url)
                return True
        except Exception as exc:
            errors.append(str(exc))

        try:
            if webbrowser.open(url, new=1):
                return True
        except Exception as exc:
            errors.append(str(exc))

        try:
            subprocess.Popen(
                ["cmd", "/c", "start", "", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception as exc:
            errors.append(str(exc))

        if errors:
            messagebox.showinfo(
                "RenPy Tools",
                "ChatGPT를 자동으로 열지 못했어요.\n브라우저에서 chatgpt.com을 열어주세요.\n\n" + errors[-1],
            )
        return False

    def open_chatgpt(self):
        self._try_open_url(CHATGPT_URL)

    def open_chatgpt_with_next(self):
        self.copy_next_message()
        self._try_open_url(CHATGPT_URL)

    def show_split_screen_help(self):
        messagebox.showinfo(
            "분할 화면으로 사용하기",
            "1. 'ChatGPT 열기'를 눌러 ChatGPT를 여세요.\n"
            "2. Android의 최근 앱 화면을 여세요.\n"
            "3. ChatGPT 앱 아이콘의 '분할 화면으로 열기'를 선택하세요.\n"
            "4. 다른 쪽 앱으로 Winlator를 선택하세요.\n\n"
            "기기/Android 버전에 따라 메뉴 이름은 조금 다를 수 있어요.\n"
            "한 번 분할해두면 RenPy Tools와 ChatGPT를 옆에 두고 계속 '다음' 작업을 할 수 있어요.",
        )


def run_all_self_tests():
    return run_v046_tests()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_all_self_tests())
    RenPyToolsV047().mainloop()
