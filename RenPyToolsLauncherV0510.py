#!/usr/bin/env python3
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

import RenPyToolsApp as ui_module
from RenPyToolsLauncherV059 import RenPyToolsV059
from v050_manual_merge import merge_apply_and_build_exe
from v0510_async_merge import distribution_hint, run_async

ui_module.UI_VERSION = "0.5.10"


class RenPyToolsV0510(RenPyToolsV059):
    """v0.5.10: keep Winlator responsive during HQ merge and emit run-to-patch EXE."""

    def __init__(self):
        self._merge_busy = False
        self._merge_progress_win = None
        super().__init__()
        ui_module.UI_VERSION = "0.5.10"
        self.title("RenPy Tools 0.5.10")
        self.render()

    def _open_merge_progress(self, file_count):
        win = tk.Toplevel(self)
        self._merge_progress_win = win
        win.title("RenPy Tools - 조합 중")
        win.transient(self)
        win.resizable(False, False)
        try:
            win.grab_set()
        except Exception:
            pass
        win.protocol("WM_DELETE_WINDOW", lambda: None)

        frame = ttk.Frame(win, padding=24)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="번역 결과를 조합하고 있어요", style="Section.TLabel").pack(anchor="w")
        ttk.Label(
            frame,
            text=(
                f"결과 파일 {file_count}개 확인 → 패치 구성 → 게임 적용 → 배포용 EXE 생성\n"
                "이 작업은 백그라운드에서 진행되므로 Winlator가 응답 없음으로 멈추지 않아요."
            ),
            style="Muted.TLabel",
            justify="left",
        ).pack(anchor="w", pady=(8, 14))
        bar = ttk.Progressbar(frame, mode="indeterminate", length=430)
        bar.pack(fill="x")
        bar.start(12)
        self._merge_progress_bar = bar
        try:
            win.update_idletasks()
            x = self.winfo_rootx() + max(20, (self.winfo_width() - win.winfo_reqwidth()) // 2)
            y = self.winfo_rooty() + max(20, (self.winfo_height() - win.winfo_reqheight()) // 2)
            win.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def _close_merge_progress(self):
        try:
            bar = getattr(self, "_merge_progress_bar", None)
            if bar:
                bar.stop()
        except Exception:
            pass
        try:
            if self._merge_progress_win and self._merge_progress_win.winfo_exists():
                self._merge_progress_win.grab_release()
                self._merge_progress_win.destroy()
        except Exception:
            pass
        self._merge_progress_win = None

    def _merge_rows(self, rows):
        if self._merge_busy:
            messagebox.showinfo("RenPy Tools", "이미 조합 작업이 진행 중입니다.")
            return
        if not self.combine_manifest or not self.combine_game_path:
            return

        uncertain = [
            row for row in rows
            if row.get("needs_confirmation") and not row.get("manual") and not row.get("verified")
        ]
        if uncertain:
            ok = messagebox.askyesno(
                "RenPy Tools",
                f"게임ID 없이 내용만 일치하는 파일이 {len(uncertain)}개 포함되어 있습니다.\n"
                "다른 게임의 결과가 아닌지 파일명을 확인했나요?\n\n계속 합성할까요?",
            )
            if not ok:
                return

        files = [Path(row["path"]) for row in rows]
        if not files:
            messagebox.showinfo("RenPy Tools", "합성할 번역 결과가 없습니다.")
            return

        manifest = self.combine_manifest
        game_path = self.combine_game_path
        self._merge_busy = True
        self._open_merge_progress(len(files))

        def work():
            return merge_apply_and_build_exe(self, manifest, files, game_path)

        run_async(self, work, self._finish_merge_async, name="renpytools-hq-merge")

    def _finish_merge_async(self, result, error):
        self._merge_busy = False
        self._close_merge_progress()
        if error is not None:
            messagebox.showerror("RenPy Tools", f"합성/패치 실패\n\n{error}")
            return

        backup = f"\n기존 패치 백업: {result['backup']}" if result.get("backup") else ""
        hint = distribution_hint(result["exe"])
        messagebox.showinfo(
            "RenPy Tools",
            f"합성 + 게임 패치 + 배포용 EXE 생성 완료!\n\n"
            f"번역: {result['translations']:,}문장\n"
            f"사용한 결과 파일: {result['files']}개\n"
            f"게임 적용 위치: {result['destination']}"
            f"{backup}\n\n{hint}"
        )


if __name__ == "__main__":
    RenPyToolsV0510().mainloop()
