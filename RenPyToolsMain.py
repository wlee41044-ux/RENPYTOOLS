#!/usr/bin/env python3
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

import RenPyAIPatcher as core
import RenPyToolsApp as ui_module
from fast_scan import collect_rpy_fast, run_fast_scan_self_test
from RenPyAIPatcher import PatcherApp
from RenPyToolsApp import RenPyToolsApp, run_ui_self_test

# Replace the original broad Path.rglob scanner everywhere at runtime.
# The stable translation code stays unchanged; only file discovery is lighter.
core.collect_rpy = collect_rpy_fast
ui_module.collect_rpy = collect_rpy_fast
ui_module.UI_VERSION = "0.4.1"


class RenPyToolsMain(RenPyToolsApp):
    """Launch shim that initializes Tk-owned variables after the real root exists."""

    def __init__(self):
        self.route = "home"
        self.flow_step = 0
        self._history_file_groups = {}
        self._selected_history_path = None
        self.hq_workspace = None
        self.hq_manifest = None
        self._scan_busy = False

        PatcherApp.__init__(self)

        self.hq_profile = tk.StringVar(master=self, value="ChatGPT (안전)")
        self.title("RenPy Tools 0.4.1")
        self.geometry("1180x760")
        self.minsize(900, 620)
        self._extend_styles()
        self.render()

    def _select_game_folder(self, next_route=None):
        """Lightweight picker used by HQ/update flows."""
        path = filedialog.askdirectory(title="Ren'Py 게임 폴더 선택")
        if not path:
            return False
        try:
            root, files = collect_rpy_fast(Path(path))
        except Exception as exc:
            messagebox.showerror("RenPy Tools", str(exc))
            return False

        self.source_path.set(path)
        self.scan.set(f"게임 인식 완료 · {root.name} · RPY/RPYM {len(files)}개")
        self._history_file_groups = {}
        if next_route:
            self.route = next_route
            self.render()
        return True

    def start_quick_from_picker(self):
        """Scan a selected game in a background thread before starting translation."""
        if self._scan_busy:
            return
        path = filedialog.askdirectory(title="Ren'Py 게임 폴더 선택")
        if not path:
            return

        self.source_path.set(path)
        self.scan.set("게임을 확인하고 있어요... 큰 게임도 화면이 멈추지 않게 백그라운드에서 찾는 중이에요.")
        self._scan_busy = True

        def job():
            try:
                root, files = collect_rpy_fast(Path(path))
                result = (root, len(files), None)
            except Exception as exc:
                result = (None, 0, str(exc))
            self.after(0, lambda r=result: self._finish_quick_scan(path, r))

        threading.Thread(target=job, daemon=True, name="renpy-fast-scan").start()

    def _finish_quick_scan(self, path, result):
        self._scan_busy = False
        root, count, error = result
        if error:
            self.scan.set("게임을 인식하지 못했습니다.")
            messagebox.showerror("RenPy Tools", error)
            return
        self.source_path.set(path)
        self.scan.set(f"게임 인식 완료 · {root.name} · RPY/RPYM {count}개 · 번역을 시작합니다.")
        self.start_quick_translation()

    def start_quick_translation(self):
        source = self.source_path.get()
        try:
            collect_rpy_fast(Path(source))
        except Exception as exc:
            messagebox.showerror("RenPy Tools", str(exc))
            return

        apply_game = self.resolve_game_for_apply(source, reject_decompiled=False)
        if apply_game is None:
            messagebox.showerror("RenPy Tools", "선택한 폴더에서 원본 game 폴더를 찾지 못했습니다.")
            return

        if not self.source_lang.get():
            self.source_lang.set("자동 감지")
        if not self.target_lang.get():
            self.target_lang.set("한국어")
        if not self.provider.get():
            self.provider.set("무료 자동 선택 (추천)")

        workers = max(1, min(4, int(self.google_workers.get() or 3)))
        self.output_zip = self._automatic_output(source)
        self.job_options = {
            "source_path": source,
            "source_lang": self.source_lang.get(),
            "target_lang": self.target_lang.get(),
            "provider": self.provider.get(),
            "google_workers": workers,
            "base_url": "",
            "model": "",
            "auto_apply": True,
            "apply_game_path": str(apply_game),
        }
        self.route = "quick_progress"
        self.page = 3
        self.render()
        threading.Thread(target=self.worker, daemon=True).start()


def run_all_self_tests():
    code = run_fast_scan_self_test()
    if code:
        return code
    return run_ui_self_test()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_all_self_tests())
    RenPyToolsMain().mainloop()
