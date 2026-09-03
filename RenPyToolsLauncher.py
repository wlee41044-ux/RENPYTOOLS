#!/usr/bin/env python3
import sys
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

import RenPyToolsApp as ui_module
from RenPyToolsMain import RenPyToolsMain, run_all_self_tests as run_v043_tests
from v044_smart_picker import choose_renpy_game, hq_workspace_for, run_v044_picker_self_test
from v043_features import build_hq_chunks_streaming
from v046_semiauto import (
    COMBINED_NAME,
    GUIDE_NAME,
    PACKAGE_NAME,
    apply_v046_profiles,
    create_relay_package,
    relay_status,
    run_v046_self_test,
    scan_downloaded_translations,
)

# Apply the larger model-aware HQ profiles before any UI is rendered.
apply_v046_profiles()
ui_module.UI_VERSION = "0.4.6"


class RenPyToolsV046(RenPyToolsMain):
    """v0.4.6: Winlator path fix + larger HQ chunks + semi-auto AI relay."""

    def __init__(self):
        self._relay_scan_busy = False
        self._relay_after = None
        self._relay_package_path = None
        self._relay_combined_path = None
        super().__init__()
        ui_module.UI_VERSION = "0.4.6"
        self.title("RenPy Tools 0.4.6")
        self.relay_status_text = tk.StringVar(master=self, value="")
        self.relay_next_text = tk.StringVar(master=self, value="")
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

    # ------------------------------------------------------------------
    # HQ preparation + one-time AI work package
    # ------------------------------------------------------------------
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
                self._thread_hq_status("AI 작업용 ZIP을 만들고 있어요...")
                package = create_relay_package(workspace)
                error = None
            except Exception as exc:
                prepared, workspace, manifest, package = None, None, None, None
                error = str(exc)
            self.after(
                0,
                lambda p=prepared, w=workspace, m=manifest, z=package, e=error: self._finish_hq_relay_prepare(p, w, m, z, e),
            )

        threading.Thread(target=job, daemon=True, name="renpy-hq-semiauto-prepare").start()

    def _finish_hq_relay_prepare(self, prepared, workspace, manifest, package, error):
        self._relay_package_path = Path(package) if package else None
        self._relay_combined_path = None
        self._finish_hq_prepare(prepared, workspace, manifest, error)

    # ------------------------------------------------------------------
    # Semi-auto AI relay screen
    # ------------------------------------------------------------------
    def page_hq_ready(self):
        self.flow_header(2)
        ttk.Label(self.container, text="반자동 AI 번역 준비 완료", style="HomeTitle.TLabel").pack(anchor="center")
        ttk.Label(
            self.container,
            text="작업 ZIP은 처음 한 번만 AI에 올리고, 이후에는 같은 대화에서 '다음'만 보내면 돼요.",
            style="Subtitle.TLabel",
        ).pack(anchor="center", pady=(4, 14))

        outer, body = ui_module.card(self.container, padding=22)
        outer.pack(fill="both", expand=True, padx=60)

        steps = [
            "1. AI_작업패키지.zip을 ChatGPT 같은 AI 대화에 한 번 첨부하세요.",
            "2. '첫 지시문 복사'를 눌러 같이 보내세요.",
            "3. AI가 돌려준 chunk JSON을 휴대폰 Downloads에 저장하세요.",
            "4. RenPy Tools가 자동 감지하면 같은 AI 대화에 '다음'만 보내세요.",
        ]
        for text in steps:
            ttk.Label(body, text=text, style="Card.TLabel").pack(anchor="w", pady=4)

        if self.hq_workspace:
            ttk.Label(body, text=f"작업 폴더: {self.hq_workspace}", style="Muted.Card.TLabel").pack(anchor="w", pady=(10, 2))
            ttk.Label(body, text=f"AI 작업 ZIP: {Path(self.hq_workspace) / PACKAGE_NAME}", style="Muted.Card.TLabel").pack(anchor="w")

        progress_card, progress = ui_module.card(body, padding=16)
        progress_card.pack(fill="x", pady=(14, 8))
        ttk.Label(progress, text="반자동 진행 상황", style="Section.TLabel").pack(anchor="w")
        self._relay_bar = ttk.Progressbar(progress, mode="determinate", maximum=100)
        self._relay_bar.pack(fill="x", pady=(10, 5))
        ttk.Label(progress, textvariable=self.relay_status_text, style="Card.TLabel").pack(anchor="w")
        ttk.Label(progress, textvariable=self.relay_next_text, style="Muted.Card.TLabel").pack(anchor="w", pady=(3, 0))

        row = ttk.Frame(body, style="Card.TFrame")
        row.pack(fill="x", pady=(10, 0))
        ttk.Button(row, text="작업 폴더 열기", style="Secondary.TButton", command=self.open_hq_workspace).pack(side="left")
        ttk.Button(row, text="첫 지시문 복사", style="Primary.TButton", command=self.copy_relay_guide).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="'다음' 복사", style="Secondary.TButton", command=self.copy_next_message).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="번역 파일 지금 찾기", style="Secondary.TButton", command=self.scan_relay_now).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="홈으로", style="Secondary.TButton", command=self.nav_home).pack(side="right")

        self._update_relay_widgets()
        self._schedule_relay_scan(900)

    def copy_relay_guide(self):
        if not self.hq_workspace:
            return
        path = Path(self.hq_workspace) / GUIDE_NAME
        try:
            text = path.read_text(encoding="utf-8")
            marker = "2. 아래 문장을 함께 보내세요.\n\n"
            prompt = text.split(marker, 1)[1].split("\n\n[그 다음부터]", 1)[0] if marker in text else text
            self.clipboard_clear()
            self.clipboard_append(prompt.strip())
            self.update()
            messagebox.showinfo("RenPy Tools", "첫 AI 지시문을 복사했어요.")
        except Exception as exc:
            messagebox.showerror("RenPy Tools", str(exc))

    def copy_next_message(self):
        self.clipboard_clear()
        self.clipboard_append("다음")
        self.update()

    def _update_relay_widgets(self):
        if not self.hq_workspace:
            return None
        try:
            state = relay_status(self.hq_workspace)
        except Exception as exc:
            self.relay_status_text.set(f"진행 상황 확인 실패: {exc}")
            return None

        self._relay_bar.configure(value=state["percent"])
        self.relay_status_text.set(
            f"완료 {state['completed']} / {state['total']} · {state['percent']}%"
        )
        if state["done"]:
            self.relay_next_text.set("모든 번역 파일을 감지했어요. 자동 조합을 확인하는 중이에요...")
            self._auto_combine_relay(state)
        else:
            self.relay_next_text.set(f"다음 작업: {state['next_file']} · AI에 '다음'을 보내고 결과 JSON을 Downloads에 저장하세요.")
        return state

    def _auto_combine_relay(self, state):
        if not self.hq_workspace or not state.get("done"):
            return
        output = Path(self.hq_workspace) / COMBINED_NAME
        if output.is_file():
            self._relay_combined_path = output
            self.relay_next_text.set(f"✓ 자동 조합 완료 · {output.name}")
            return
        try:
            ui_module.combine_hq_chunks(
                Path(self.hq_workspace) / "manifest.json",
                [Path(x) for x in state.get("translated_files", [])],
                output,
            )
            self._relay_combined_path = output
            self.relay_next_text.set(f"✓ 모든 청크 감지 + 자동 조합 완료 · {output.name}")
        except Exception as exc:
            self.relay_next_text.set(f"번역 파일은 모두 감지됐지만 자동 조합 실패: {exc}")

    def _schedule_relay_scan(self, delay=2500):
        try:
            if self._relay_after is not None:
                self.after_cancel(self._relay_after)
        except Exception:
            pass
        self._relay_after = self.after(delay, self._relay_auto_scan)

    def scan_relay_now(self):
        self._start_relay_scan(manual=True)

    def _relay_auto_scan(self):
        self._relay_after = None
        if getattr(self, "route", "") != "hq_ready":
            return
        self._start_relay_scan(manual=False)

    def _start_relay_scan(self, manual=False):
        if self._relay_scan_busy or not self.hq_workspace:
            if not manual and getattr(self, "route", "") == "hq_ready":
                self._schedule_relay_scan()
            return
        self._relay_scan_busy = True
        workspace = Path(self.hq_workspace)
        preferred = self._original_source_path or self.source_path.get()

        def job():
            try:
                imported = scan_downloaded_translations(workspace, preferred_path=preferred)
                error = None
            except Exception as exc:
                imported = []
                error = str(exc)
            self.after(0, lambda i=imported, e=error, m=manual: self._finish_relay_scan(i, e, m))

        threading.Thread(target=job, daemon=True, name="renpy-semiauto-download-watch").start()

    def _finish_relay_scan(self, imported, error, manual):
        self._relay_scan_busy = False
        if error:
            if manual:
                messagebox.showerror("RenPy Tools", f"Downloads 확인 실패\n\n{error}")
        elif imported and manual:
            messagebox.showinfo("RenPy Tools", f"번역 파일 {len(imported)}개를 찾았어요.")
        state = self._update_relay_widgets()
        if getattr(self, "route", "") == "hq_ready" and not (state and state.get("done")):
            self._schedule_relay_scan()


def run_all_self_tests():
    code = run_v043_tests()
    if code:
        return code
    code = run_v044_picker_self_test()
    if code:
        return code
    return run_v046_self_test()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_all_self_tests())
    RenPyToolsV046().mainloop()
