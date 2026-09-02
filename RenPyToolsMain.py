#!/usr/bin/env python3
import sys
import threading
from pathlib import Path
import tkinter as tk

from RenPyAIPatcher import PatcherApp, collect_rpy
from RenPyToolsApp import RenPyToolsApp, run_ui_self_test


class RenPyToolsMain(RenPyToolsApp):
    """Launch shim that initializes Tk-owned variables after the real root exists."""

    def __init__(self):
        self.route = "home"
        self.flow_step = 0
        self._history_file_groups = {}
        self._selected_history_path = None
        self.hq_workspace = None
        self.hq_manifest = None

        # Call the stable v0.3.7 base initializer directly. It creates the one
        # and only Tk root, then invokes RenPyToolsApp.render().
        PatcherApp.__init__(self)

        self.hq_profile = tk.StringVar(master=self, value="ChatGPT (안전)")
        self.title("RenPy Tools 0.4.0")
        self.geometry("1180x760")
        self.minsize(900, 620)
        self._extend_styles()
        self.render()

    def start_quick_translation(self):
        """Use the current Settings values; defaults still produce one-click mode."""
        source = self.source_path.get()
        try:
            collect_rpy(Path(source))
        except Exception as exc:
            from tkinter import messagebox
            messagebox.showerror("RenPy Tools", str(exc))
            return

        apply_game = self.resolve_game_for_apply(source, reject_decompiled=False)
        if apply_game is None:
            from tkinter import messagebox
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


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_ui_self_test())
    RenPyToolsMain().mainloop()
