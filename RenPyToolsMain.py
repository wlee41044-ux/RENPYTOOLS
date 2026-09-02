#!/usr/bin/env python3
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

import RenPyAIPatcher as core
import RenPyToolsApp as ui_module
from auto_decompile import can_auto_decompile, prepare_decompiled_source, run_auto_decompile_self_test
from fast_scan import collect_rpy_fast, run_fast_scan_self_test
from RenPyAIPatcher import PatcherApp
from RenPyExtractor import resolve_game_folder
from RenPyToolsApp import RenPyToolsApp, run_ui_self_test

# Replace the original broad Path.rglob scanner everywhere at runtime.
core.collect_rpy = collect_rpy_fast
ui_module.collect_rpy = collect_rpy_fast
ui_module.UI_VERSION = "0.4.2"


class RenPyToolsMain(RenPyToolsApp):
    """Main UI with Winlator-friendly scanning and automatic decompilation."""

    def __init__(self):
        self.route = "home"
        self.flow_step = 0
        self._history_file_groups = {}
        self._selected_history_path = None
        self.hq_workspace = None
        self.hq_manifest = None
        self._scan_busy = False
        self._original_source_path = None
        self._apply_game_override = None
        self._last_prepare_was_decompile = False

        PatcherApp.__init__(self)

        self.hq_profile = tk.StringVar(master=self, value="ChatGPT (안전)")
        self.title("RenPy Tools 0.4.2")
        self.geometry("1180x760")
        self.minsize(900, 620)
        self._extend_styles()
        self.render()

    def _thread_scan_text(self, text):
        self.after(0, lambda t=text: self.scan.set(t))

    def _prepare_source(self, path, status=None):
        """Recognize plain scripts, otherwise decompile once and retry."""
        original = str(Path(path))
        try:
            root, files = collect_rpy_fast(Path(original))
            game = self.resolve_game_for_apply(original, reject_decompiled=False)
            return {
                "source": original,
                "root": root,
                "files": files,
                "original": original,
                "apply_game": str(game) if game else "",
                "decompiled": False,
                "stats": {},
            }
        except Exception as first_error:
            if not can_auto_decompile(original):
                raise first_error

        if status:
            status("번역용 파일이 없어서 자동으로 디컴파일하고 있어요...")
        prepared, stats = prepare_decompiled_source(original, status=status)
        root, files = collect_rpy_fast(prepared)
        game = resolve_game_folder(original)
        return {
            "source": str(prepared),
            "root": root,
            "files": files,
            "original": original,
            "apply_game": str(game),
            "decompiled": True,
            "stats": stats,
        }

    def _adopt_prepared_source(self, result):
        self._original_source_path = result["original"]
        self._apply_game_override = result.get("apply_game") or None
        self._last_prepare_was_decompile = bool(result.get("decompiled"))
        self.source_path.set(result["source"])
        if result.get("decompiled"):
            stats = result.get("stats", {})
            self.scan.set(
                f"자동 디컴파일 완료 · RPY/RPYM {len(result['files'])}개 · "
                f"디컴파일 성공 {stats.get('decompiled', 0)}개"
            )
        else:
            self.scan.set(f"게임 인식 완료 · {result['root'].name} · RPY/RPYM {len(result['files'])}개")

    def _select_game_folder(self, next_route=None):
        """Shared picker for HQ/update. Compiled games are prepared automatically."""
        path = filedialog.askdirectory(title="Ren'Py 게임 폴더 선택")
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
        """Prepare a game in the background so Winlator never freezes during recognition."""
        if self._scan_busy:
            return
        path = filedialog.askdirectory(title="Ren'Py 게임 폴더 선택")
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

        threading.Thread(target=job, daemon=True, name="renpy-auto-prepare").start()

    def _finish_quick_prepare(self, result, error):
        self._scan_busy = False
        if error:
            self.scan.set("게임을 인식하지 못했습니다.")
            messagebox.showerror("RenPy Tools", error)
            return
        self._adopt_prepared_source(result)
        if result.get("decompiled"):
            self.scan.set(self.scan.get() + " · 번역을 시작합니다.")
        else:
            self.scan.set(self.scan.get() + " · 번역을 시작합니다.")
        self.start_quick_translation()

    def signature(self, options):
        """Keep history tied to the real game path, not the decompile cache."""
        result = super().signature(options)
        history_source = options.get("history_source_path")
        if history_source:
            try:
                result["source_path"] = str(Path(history_source).resolve())
            except Exception:
                result["source_path"] = str(history_source)
        return result

    def start_quick_translation(self):
        source = self.source_path.get()
        try:
            collect_rpy_fast(Path(source))
        except Exception as exc:
            messagebox.showerror("RenPy Tools", str(exc))
            return

        apply_game = Path(self._apply_game_override) if self._apply_game_override else self.resolve_game_for_apply(
            source, reject_decompiled=False
        )
        if apply_game is None or not Path(apply_game).is_dir():
            messagebox.showerror("RenPy Tools", "선택한 원본 게임에서 game 폴더를 찾지 못했습니다.")
            return

        if not self.source_lang.get():
            self.source_lang.set("자동 감지")
        if not self.target_lang.get():
            self.target_lang.set("한국어")
        if not self.provider.get():
            self.provider.set("무료 자동 선택 (추천)")

        workers = max(1, min(4, int(self.google_workers.get() or 3)))
        output_base = self._original_source_path or source
        self.output_zip = self._automatic_output(output_base)
        self.job_options = {
            "source_path": source,
            "history_source_path": self._original_source_path or source,
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
        if self._last_prepare_was_decompile:
            self.status.set("자동 디컴파일 완료 · 번역을 시작합니다.")
        threading.Thread(target=self.worker, daemon=True).start()


def run_all_self_tests():
    code = run_fast_scan_self_test()
    if code:
        return code
    code = run_auto_decompile_self_test()
    if code:
        return code
    return run_ui_self_test()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_all_self_tests())
    RenPyToolsMain().mainloop()
