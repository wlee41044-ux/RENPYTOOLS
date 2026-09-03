#!/usr/bin/env python3
import os
import sys
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

import RenPyToolsApp as ui_module
from RenPyToolsLauncherV047 import RenPyToolsV047, run_all_self_tests as run_v047_tests
from v044_smart_picker import hq_workspace_for
from v048_master_hq import (
    COMBINED_NAME,
    MASTER_BASENAME,
    MASTER_MANIFEST,
    PROFILE_INFO,
    apply_v048_profiles,
    build_master_workflow,
    master_status,
    models_for,
    plans_for,
    profile_for,
    run_v048_self_test,
    scan_master_results,
    write_combined_if_done,
)

apply_v048_profiles()
ui_module.UI_VERSION = "0.4.8"

AI_URLS = {
    "ChatGPT": "https://chatgpt.com/",
    "Gemini": "https://gemini.google.com/",
    "Claude": "https://claude.ai/",
}


class RenPyToolsV048(RenPyToolsV047):
    """v0.4.8: one large master TXT per context-sized part, then 'next' in the same AI chat."""

    def __init__(self):
        self._master_scan_busy = False
        self._master_after = None
        super().__init__()
        apply_v048_profiles()
        ui_module.UI_VERSION = "0.4.8"
        self.title("RenPy Tools 0.4.8")
        self.master_status_text = tk.StringVar(master=self, value="")
        self.master_next_text = tk.StringVar(master=self, value="")
        self.render()

    # ------------------------------------------------------------------
    # Detailed provider / plan / model selection
    # ------------------------------------------------------------------
    def _normalize_hq_selection(self):
        services = list(PROFILE_INFO)
        if self.hq_service.get() not in services:
            self.hq_service.set(services[0])
        plans = plans_for(self.hq_service.get())
        if self.hq_plan.get() not in plans:
            preferred = "잘 모르겠어요" if "잘 모르겠어요" in plans else plans[0]
            self.hq_plan.set(preferred)
        models = models_for(self.hq_service.get(), self.hq_plan.get())
        if self.hq_model.get() not in models:
            self.hq_model.set(models[0])
        self._set_profile_hint()

    def _set_profile_hint(self):
        info = profile_for(self.hq_service.get(), self.hq_plan.get(), self.hq_model.get())
        context = f"{info['context_tokens']:,}" if info["context_tokens"] else "공식 고정값 미확인"
        output = f"{info['max_output_tokens']:,}" if info["max_output_tokens"] else "공식 고정값 미확인"
        self.hq_profile_hint.set(
            f"컨텍스트 참고 {context}토큰 · 최대 출력 참고 {output}토큰 · "
            f"RenPy Tools 전체작업 목표 {info['safe_master_tokens']:,}토큰 · "
            f"1회 번역 출력 목표 {info['safe_output_tokens']:,}토큰"
        )

    def _refresh_hq_service(self, *_):
        plans = plans_for(self.hq_service.get())
        self._hq_plan_combo.configure(values=plans)
        preferred = "잘 모르겠어요" if "잘 모르겠어요" in plans else plans[0]
        self.hq_plan.set(preferred)
        self._refresh_hq_plan()

    def _refresh_hq_plan(self, *_):
        models = models_for(self.hq_service.get(), self.hq_plan.get())
        self._hq_model_combo.configure(values=models)
        self.hq_model.set(models[0])
        self._refresh_hq_hint()

    def _refresh_hq_hint(self, *_):
        self._set_profile_hint()

    def page_hq_select(self):
        self._normalize_hq_selection()
        self.flow_header(1)
        ttk.Label(self.container, text="고품질 번역", style="HomeTitle.TLabel").pack(anchor="center")
        ttk.Label(
            self.container,
            text="수백 개 청크 대신, 선택한 AI의 컨텍스트에 맞는 큰 TXT 작업 파일 몇 개만 만들어요.",
            style="Subtitle.TLabel",
        ).pack(anchor="center", pady=(4, 16))

        outer, body = ui_module.card(self.container, padding=22)
        outer.pack(fill="x", padx=90)

        ttk.Label(body, text="AI 서비스", style="Card.TLabel").pack(anchor="w")
        service_combo = ttk.Combobox(body, textvariable=self.hq_service, values=list(PROFILE_INFO), state="readonly")
        service_combo.pack(fill="x", pady=(4, 9))

        ttk.Label(body, text="요금제", style="Card.TLabel").pack(anchor="w")
        self._hq_plan_combo = ttk.Combobox(
            body, textvariable=self.hq_plan, values=plans_for(self.hq_service.get()), state="readonly"
        )
        self._hq_plan_combo.pack(fill="x", pady=(4, 9))

        ttk.Label(body, text="모델", style="Card.TLabel").pack(anchor="w")
        self._hq_model_combo = ttk.Combobox(
            body,
            textvariable=self.hq_model,
            values=models_for(self.hq_service.get(), self.hq_plan.get()),
            state="readonly",
        )
        self._hq_model_combo.pack(fill="x", pady=(4, 8))

        ttk.Label(body, textvariable=self.hq_profile_hint, style="Muted.Card.TLabel", wraplength=880).pack(anchor="w")
        info = profile_for(self.hq_service.get(), self.hq_plan.get(), self.hq_model.get())
        ttk.Label(
            body,
            text=info["note"] + " · 표시된 최대치는 모델/서비스 참고치이며 실제 앱 사용량 한도와는 별개예요.",
            style="Muted.Card.TLabel",
            wraplength=880,
        ).pack(anchor="w", pady=(5, 14))
        ttk.Button(body, text="게임 선택하고 전체 번역 파일 만들기", style="Big.TButton", command=self.prepare_hq_from_picker).pack(anchor="center")

        service_combo.bind("<<ComboboxSelected>>", self._refresh_hq_service)
        self._hq_plan_combo.bind("<<ComboboxSelected>>", self._refresh_hq_plan)
        self._hq_model_combo.bind("<<ComboboxSelected>>", self._refresh_hq_hint)

    # ------------------------------------------------------------------
    # Build context-sized master TXT files instead of hundreds of chunks
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
                self._thread_hq_status("AI 컨텍스트에 맞춰 전체 번역 TXT를 만들고 있어요...")
                manifest = build_master_workflow(
                    prepared["source"], workspace, service, plan, model, target_lang,
                    status=self._thread_hq_status,
                )
                error = None
            except Exception as exc:
                prepared, workspace, manifest = None, None, None
                error = str(exc)
            self.after(0, lambda p=prepared, w=workspace, m=manifest, e=error: self._finish_master_prepare(p, w, m, e))

        threading.Thread(target=job, daemon=True, name="renpy-master-hq-prepare").start()

    def _finish_master_prepare(self, prepared, workspace, manifest, error):
        self._hq_busy = False
        if error:
            self.route = "hq_select"
            self.render()
            messagebox.showerror("RenPy Tools", f"전체 번역 파일 준비 실패\n\n{error}")
            return
        self._adopt_prepared_source(prepared)
        self.hq_workspace = Path(workspace)
        self.hq_manifest = manifest
        self.route = "hq_ready"
        self.render()

    # ------------------------------------------------------------------
    # Same-chat continuation screen: upload once, then type 'next'
    # ------------------------------------------------------------------
    def page_hq_ready(self):
        self.flow_header(2)
        ttk.Label(self.container, text="전체 번역 파일 준비 완료", style="HomeTitle.TLabel").pack(anchor="center")
        ttk.Label(
            self.container,
            text="현재 전체작업 TXT를 AI에 한 번 올린 뒤, 같은 채팅에서 '다음'만 보내며 계속 번역받으세요.",
            style="Subtitle.TLabel",
        ).pack(anchor="center", pady=(4, 14))

        outer, body = ui_module.card(self.container, padding=20)
        outer.pack(fill="both", expand=True, padx=58)

        info = profile_for(self.hq_service.get(), self.hq_plan.get(), self.hq_model.get())
        ttk.Label(
            body,
            text=(
                f"{self.hq_service.get()} · {self.hq_plan.get()} · {self.hq_model.get()}  |  "
                f"1회 출력 목표 약 {info['safe_output_tokens']:,}토큰"
            ),
            style="Section.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            body,
            text="AI는 출력 한도 끝까지 억지로 채우지 않고 완전한 문장에서 멈추도록 파일 안에 지시되어 있어요.",
            style="Muted.Card.TLabel",
        ).pack(anchor="w", pady=(4, 10))

        progress_card, progress = ui_module.card(body, padding=15)
        progress_card.pack(fill="x", pady=(4, 10))
        self._master_bar = ttk.Progressbar(progress, mode="determinate", maximum=100)
        self._master_bar.pack(fill="x", pady=(2, 6))
        ttk.Label(progress, textvariable=self.master_status_text, style="Card.TLabel").pack(anchor="w")
        ttk.Label(progress, textvariable=self.master_next_text, style="Muted.Card.TLabel", wraplength=900).pack(anchor="w", pady=(3, 0))

        steps = [
            "1. 아래에 표시된 현재 전체작업 TXT를 선택한 AI 채팅에 첨부하고 번역을 시작하세요.",
            "2. AI가 RenPyTools_Result_....txt를 주면 휴대폰 Download에 저장하세요.",
            "3. RenPy Tools가 자동 감지합니다. 같은 채팅에 '다음'이라고 보내세요.",
            "4. 전체작업 파일이 여러 개일 때만, 현재 파트가 끝난 뒤 다음 TXT를 한 번 더 첨부하세요.",
        ]
        for text in steps:
            ttk.Label(body, text=text, style="Card.TLabel").pack(anchor="w", pady=3)

        row = ttk.Frame(body, style="Card.TFrame")
        row.pack(fill="x", pady=(12, 0))
        ttk.Button(row, text="선택한 AI 열기", style="Primary.TButton", command=self.open_selected_ai).pack(side="left")
        ttk.Button(row, text="작업 폴더 열기", style="Secondary.TButton", command=self.open_hq_workspace).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="번역 결과 지금 찾기", style="Secondary.TButton", command=self.scan_master_now).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="홈으로", style="Secondary.TButton", command=self.nav_home).pack(side="right")

        self._update_master_widgets()
        self._schedule_master_scan(1000)

    def open_selected_ai(self):
        url = AI_URLS.get(self.hq_service.get())
        if not url:
            messagebox.showinfo("RenPy Tools", "선택한 AI의 웹 주소를 자동으로 정하지 못했어요. AI 앱/브라우저를 직접 열어주세요.")
            return
        self._try_open_url(url)

    def _update_master_widgets(self):
        if not self.hq_workspace:
            return None
        try:
            state = master_status(self.hq_workspace)
        except Exception as exc:
            self.master_status_text.set(f"진행 상황 확인 실패: {exc}")
            return None
        self._master_bar.configure(value=state["percent"])
        self.master_status_text.set(
            f"번역 완료 {state['completed']:,} / {state['total']:,}문장 · {state['percent']}% · "
            f"전체작업 {state['current_part']}/{state['part_count']}"
        )
        if state["done"]:
            output = write_combined_if_done(self.hq_workspace)
            self.master_next_text.set(f"✓ 전체 번역 감지 완료 · 자동 조합 완료: {Path(output).name if output else COMBINED_NAME}")
        else:
            self.master_next_text.set(
                f"현재 첨부할 파일: {state['current_file']} · 다음 ID: {state['next_id']} · "
                "이 파일을 이미 AI에 올렸다면 같은 채팅에 '다음'이라고만 보내세요."
            )
        return state

    def _schedule_master_scan(self, delay=2600):
        try:
            if self._master_after is not None:
                self.after_cancel(self._master_after)
        except Exception:
            pass
        self._master_after = self.after(delay, self._master_auto_scan)

    def _master_auto_scan(self):
        self._master_after = None
        if getattr(self, "route", "") != "hq_ready":
            return
        self._start_master_scan(manual=False)

    def scan_master_now(self):
        self._start_master_scan(manual=True)

    def _start_master_scan(self, manual=False):
        if self._master_scan_busy or not self.hq_workspace:
            if not manual and getattr(self, "route", "") == "hq_ready":
                self._schedule_master_scan()
            return
        self._master_scan_busy = True
        workspace = Path(self.hq_workspace)
        preferred = self._original_source_path or self.source_path.get()

        def job():
            try:
                imported, _ = scan_master_results(workspace, preferred_path=preferred)
                error = None
            except Exception as exc:
                imported, error = 0, str(exc)
            self.after(0, lambda i=imported, e=error, m=manual: self._finish_master_scan(i, e, m))

        threading.Thread(target=job, daemon=True, name="renpy-master-result-watch").start()

    def _finish_master_scan(self, imported, error, manual):
        self._master_scan_busy = False
        if error and manual:
            messagebox.showerror("RenPy Tools", f"Downloads 확인 실패\n\n{error}")
        elif imported and manual:
            messagebox.showinfo("RenPy Tools", f"새 번역 {imported:,}문장을 찾았어요.")
        state = self._update_master_widgets()
        if getattr(self, "route", "") == "hq_ready" and not (state and state.get("done")):
            self._schedule_master_scan()


def run_all_self_tests():
    code = run_v047_tests()
    if code:
        return code
    return run_v048_self_test()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_all_self_tests())
    RenPyToolsV048().mainloop()
