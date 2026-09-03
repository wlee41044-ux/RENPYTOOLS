#!/usr/bin/env python3
import sys
import threading
import time
from pathlib import Path
from tkinter import messagebox

import RenPyToolsApp as ui_module
from RenPyToolsMain import RenPyToolsMain, run_all_self_tests as run_v043_tests
from v044_smart_picker import choose_renpy_game, hq_workspace_for, run_v044_picker_self_test
from v043_features import build_hq_chunks_streaming

ui_module.UI_VERSION = "0.4.5"


class RenPyToolsV045(RenPyToolsMain):
    """v0.4.5 UX overlay: robust Winlator smart picker + real Downloads HQ output."""

    def __init__(self):
        super().__init__()
        ui_module.UI_VERSION = "0.4.5"
        self.title("RenPy Tools 0.4.5")
        self.render()

    def _choose_game(self, title="Ren'Py 게임 선택"):
        return choose_renpy_game(self, title=title)

    def _select_game_folder(self, next_route=None):
        path = self._choose_game("업데이트할 Ren'Py 게임 선택")
        if not path:
            return False
        try:
            self.scan.set("게임 파일을 확인하고 있어요...")
            self.update_idletasks()
            result = self._prepare_source(path, status=lambda text: self.scan.set(text))
        except Exception as exc:
            messagebox.showerror("RenPy Tools", str(exc))
            return False

        self._adopt_prepared_source(result)
        self._history_file_groups = {}
        if next_route:
            self.route = next_route
            self.render()
        return True

    def start_quick_from_picker(self):
        if self._scan_busy:
            return
        path = self._choose_game("번역할 Ren'Py 게임 선택")
        if not path:
            return

        self._original_source_path = path
        self._apply_game_override = None
        self.source_path.set(path)
        self.scan.set("게임을 확인하고 있어요...")
        self._scan_busy = True

        def job():
            try:
                result = self._prepare_source(path, status=self._thread_scan_text)
                error = None
            except Exception as exc:
                result = None
                error = str(exc)
            self.after(0, lambda r=result, e=error: self._finish_quick_prepare(r, e))

        threading.Thread(target=job, daemon=True, name="renpy-smart-quick-prepare").start()

    def prepare_hq_from_picker(self):
        if self._hq_busy:
            return
        path = self._choose_game("고품질 번역할 Ren'Py 게임 선택")
        if not path:
            return

        service = self.hq_service.get()
        plan = self.hq_plan.get()
        model = self.hq_model.get()
        target_lang = self.target_lang.get()
        self._hq_busy = True
        self.hq_status.set("게임 파일을 확인하고 있어요...")
        self.route = "hq_preparing"
        self.render()

        def job():
            try:
                prepared = self._prepare_source(path, status=self._thread_hq_status)
                workspace = hq_workspace_for(path, time.strftime("%Y%m%d_%H%M%S"))
                self._thread_hq_status("휴대폰 Downloads에 고품질 번역 파일을 만들고 있어요...")
                manifest = build_hq_chunks_streaming(
                    prepared["source"],
                    workspace,
                    service,
                    plan,
                    model,
                    target_lang,
                    status=self._thread_hq_status,
                )
                error = None
            except Exception as exc:
                prepared, workspace, manifest = None, None, None
                error = str(exc)
            self.after(
                0,
                lambda p=prepared, w=workspace, m=manifest, e=error: self._finish_hq_prepare(p, w, m, e),
            )

        threading.Thread(target=job, daemon=True, name="renpy-hq-downloads-prepare").start()


def run_all_self_tests():
    code = run_v043_tests()
    if code:
        return code
    return run_v044_picker_self_test()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_all_self_tests())
    RenPyToolsV045().mainloop()
