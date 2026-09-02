#!/usr/bin/env python3
import sys
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import RenPyAIPatcher as core
import RenPyToolsApp as ui_module
from auto_decompile import can_auto_decompile, prepare_decompiled_source, run_auto_decompile_self_test
from fast_scan import collect_rpy_fast, run_fast_scan_self_test
from RenPyAIPatcher import PatcherApp, LANGS, SOURCE_CODES, PROVIDERS
from RenPyExtractor import resolve_game_folder
from RenPyToolsApp import RenPyToolsApp, run_ui_self_test
from v043_features import (
    AI_CATALOG,
    GOOGLE_BATCH_CHARS,
    GOOGLE_BATCH_ITEMS,
    build_hq_chunks_streaming,
    history_metrics,
    hq_limits_for,
    make_google_batches_v043,
    models_for,
    plans_for,
    run_v043_self_test,
)

# Winlator-friendly script discovery and v0.4.3 Google request packing.
core.collect_rpy = collect_rpy_fast
ui_module.collect_rpy = collect_rpy_fast
core.make_batches = make_google_batches_v043
core.BATCH_SIZE = GOOGLE_BATCH_ITEMS
core.BATCH_CHAR_LIMIT = GOOGLE_BATCH_CHARS
ui_module.UI_VERSION = "0.4.3"


class RenPyToolsMain(RenPyToolsApp):
    """Main UI with auto-decompile, large-game HQ prep and resumable history."""

    def __init__(self):
        self.route = "home"
        self.flow_step = 0
        self._history_file_groups = {}
        self._selected_history_path = None
        self.hq_workspace = None
        self.hq_manifest = None
        self._scan_busy = False
        self._hq_busy = False
        self._original_source_path = None
        self._apply_game_override = None
        self._last_prepare_was_decompile = False
        self._resume_history_path = None

        PatcherApp.__init__(self)

        # HQ selection is deliberately data-driven so model/plan profiles can be
        # updated later without rewriting the translation pipeline.
        self.hq_service = tk.StringVar(master=self, value="ChatGPT")
        self.hq_plan = tk.StringVar(master=self, value="잘 모르겠어요")
        self.hq_model = tk.StringVar(master=self, value="자동 추천")
        self.hq_profile = tk.StringVar(master=self, value="ChatGPT (안전)")  # old UI compatibility
        self.hq_status = tk.StringVar(master=self, value="")
        self.hq_profile_hint = tk.StringVar(master=self, value="")

        self.title("RenPy Tools 0.4.3")
        self.geometry("1180x760")
        self.minsize(900, 620)
        self._extend_styles()
        self.render()

    def render(self):
        if getattr(self, "route", "home") == "hq_preparing":
            self.clear()
            self.page_hq_preparing()
            return
        super().render()

    def _thread_scan_text(self, text):
        self.after(0, lambda t=text: self.scan.set(t))

    def _thread_hq_status(self, text):
        self.after(0, lambda t=text: self.hq_status.set(t))

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
        """Shared picker for update flow. HQ uses its own background path."""
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

    # ------------------------------------------------------------------
    # Quick translation / auto decompile
    # ------------------------------------------------------------------
    def start_quick_from_picker(self):
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

    # ------------------------------------------------------------------
    # High quality translation - plan/model profiles + large-file streaming
    # ------------------------------------------------------------------
    def _normalize_hq_selection(self):
        services = list(AI_CATALOG)
        if self.hq_service.get() not in services:
            self.hq_service.set(services[0])
        plans = plans_for(self.hq_service.get())
        if self.hq_plan.get() not in plans:
            preferred = "잘 모르겠어요" if "잘 모르겠어요" in plans else plans[0]
            self.hq_plan.set(preferred)
        models = models_for(self.hq_service.get(), self.hq_plan.get())
        if self.hq_model.get() not in models:
            self.hq_model.set(models[0])
        limits = hq_limits_for(self.hq_service.get(), self.hq_plan.get(), self.hq_model.get())
        self.hq_profile_hint.set(
            f"RenPy Tools 안전 분할: 파일당 최대 약 {limits['max_items']}문장 / {limits['max_chars']:,}자"
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
        limits = hq_limits_for(self.hq_service.get(), self.hq_plan.get(), self.hq_model.get())
        self.hq_profile_hint.set(
            f"RenPy Tools 안전 분할: 파일당 최대 약 {limits['max_items']}문장 / {limits['max_chars']:,}자"
        )

    def page_hq_select(self):
        self._normalize_hq_selection()
        self.flow_header(1)
        ttk.Label(self.container, text="고품질 번역", style="HomeTitle.TLabel").pack(anchor="center")
        ttk.Label(
            self.container,
            text="사용 중인 AI·요금제·모델에 맞춰 번역 파일을 안전한 크기로 나눠드려요.",
            style="Subtitle.TLabel",
        ).pack(anchor="center", pady=(4, 18))

        outer, body = ui_module.card(self.container, padding=24)
        outer.pack(fill="x", padx=100)

        ttk.Label(body, text="사용할 AI", style="Card.TLabel").pack(anchor="w")
        service_combo = ttk.Combobox(body, textvariable=self.hq_service, values=list(AI_CATALOG), state="readonly")
        service_combo.pack(fill="x", pady=(4, 10))

        ttk.Label(body, text="사용 중인 요금제", style="Card.TLabel").pack(anchor="w")
        self._hq_plan_combo = ttk.Combobox(
            body, textvariable=self.hq_plan, values=plans_for(self.hq_service.get()), state="readonly"
        )
        self._hq_plan_combo.pack(fill="x", pady=(4, 10))

        ttk.Label(body, text="사용할 모델 / 추론 모드", style="Card.TLabel").pack(anchor="w")
        self._hq_model_combo = ttk.Combobox(
            body,
            textvariable=self.hq_model,
            values=models_for(self.hq_service.get(), self.hq_plan.get()),
            state="readonly",
        )
        self._hq_model_combo.pack(fill="x", pady=(4, 8))

        ttk.Label(body, textvariable=self.hq_profile_hint, style="Muted.Card.TLabel").pack(anchor="w", pady=(0, 14))
        ttk.Label(
            body,
            text="표시되는 크기는 서비스의 공식 최대치가 아니라 누락·JSON 손상을 줄이기 위한 RenPy Tools의 보수적인 안전값입니다.",
            style="Muted.Card.TLabel",
            wraplength=820,
        ).pack(anchor="w", pady=(0, 14))
        ttk.Button(body, text="게임 선택하고 파일 준비하기", style="Big.TButton", command=self.prepare_hq_from_picker).pack(anchor="center")

        service_combo.bind("<<ComboboxSelected>>", self._refresh_hq_service)
        self._hq_plan_combo.bind("<<ComboboxSelected>>", self._refresh_hq_plan)
        self._hq_model_combo.bind("<<ComboboxSelected>>", self._refresh_hq_hint)

    def prepare_hq_from_picker(self):
        if self._hq_busy:
            return
        path = filedialog.askdirectory(title="Ren'Py 게임 폴더 선택")
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
                original_game = resolve_game_folder(path)
                base = original_game.parent
                workspace = base / "RenPyTools_HighQuality" / time.strftime("%Y%m%d_%H%M%S")
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

        threading.Thread(target=job, daemon=True, name="renpy-hq-stream-prepare").start()

    def page_hq_preparing(self):
        self.flow_header(2)
        ttk.Label(self.container, text="파일을 준비하고 있어요...", style="HomeTitle.TLabel").pack(anchor="center")
        ttk.Label(self.container, textvariable=self.hq_status, style="Subtitle.TLabel").pack(anchor="center", pady=(6, 18))
        outer, body = ui_module.card(self.container, padding=30)
        outer.pack(fill="x", padx=100)
        ttk.Label(
            body,
            text="큰 파일도 한 번에 메모리에 올리지 않고 줄 단위로 읽어 나누는 중이에요.",
            style="Section.TLabel",
        ).pack(anchor="center")
        bar = ttk.Progressbar(body, mode="indeterminate")
        bar.pack(fill="x", pady=(18, 8))
        bar.start(12)
        ttk.Label(
            body,
            text="Winlator에서 화면이 멈추지 않도록 백그라운드에서 처리합니다.",
            style="Muted.Card.TLabel",
        ).pack(anchor="center")

    def _finish_hq_prepare(self, prepared, workspace, manifest, error):
        self._hq_busy = False
        if error:
            self.route = "hq_select"
            self.render()
            messagebox.showerror("RenPy Tools", f"고품질 번역 파일 준비 실패\n\n{error}")
            return
        self._adopt_prepared_source(prepared)
        self.hq_workspace = workspace
        self.hq_manifest = manifest
        self.route = "hq_ready"
        self.render()

    # ------------------------------------------------------------------
    # Translation history - status shortcut + resume
    # ------------------------------------------------------------------
    def page_history(self):
        self.topbar("번역 기록", "게임별 기록을 확인하고, 멈춘 번역은 그대로 이어서 진행할 수 있어요.")
        rows = self.list_history_files()
        if not rows:
            ttk.Label(self.container, text="아직 저장된 번역 기록이 없어요.", style="Subtitle.TLabel").pack(anchor="center", pady=80)
            return

        holder = ttk.Frame(self.container)
        holder.pack(fill="both", expand=True)
        for path, data in rows[:12]:
            sig = data.get("signature", {})
            name = Path(sig.get("source_path", "게임")).name or "게임"
            metrics = history_metrics(data)
            outer, body = ui_module.card(holder, padding=14)
            outer.pack(fill="x", pady=5)

            left = ttk.Frame(body, style="Card.TFrame")
            left.pack(side="left", fill="x", expand=True)
            ttk.Label(left, text=name, style="Section.TLabel").pack(anchor="w")
            ttk.Label(
                left,
                text=(
                    f"{metrics['percent']}% · 번역 {metrics['success']}/{metrics['total']} · "
                    f"실패 {metrics['failed']} · 대기 {metrics['pending']}"
                ),
                style="Muted.Card.TLabel",
            ).pack(anchor="w", pady=(3, 0))

            actions = ttk.Frame(body, style="Card.TFrame")
            actions.pack(side="right")
            ttk.Button(
                actions, text="번역 현황", style="Secondary.TButton",
                command=lambda p=path: self.show_history_status(p),
            ).pack(side="left", padx=(0, 6))
            resume_state = "normal" if metrics["success"] < metrics["total"] else "disabled"
            ttk.Button(
                actions, text="번역 다시 재개", style="Primary.TButton", state=resume_state,
                command=lambda p=path: self.resume_history(p),
            ).pack(side="left", padx=(0, 6))
            ttk.Button(
                actions, text="기록 열기", style="Secondary.TButton",
                command=lambda p=path: self.open_history_detail(p),
            ).pack(side="left")

    def show_history_status(self, path):
        data = self.load_json(Path(path))
        metrics = history_metrics(data)
        sig = data.get("signature", {})
        win = tk.Toplevel(self)
        win.title("번역 현황")
        win.geometry("620x300")
        wrap = ttk.Frame(win, padding=22)
        wrap.pack(fill="both", expand=True)
        ttk.Label(wrap, text=Path(sig.get("source_path", "게임")).name or "게임", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            wrap,
            text=f"진행률 {metrics['percent']}% · 성공 {metrics['success']} · 실패 {metrics['failed']} · 대기 {metrics['pending']}",
        ).pack(anchor="w", pady=(8, 12))
        bar = ttk.Progressbar(wrap, mode="determinate", maximum=max(metrics["total"], 1), value=metrics["success"])
        bar.pack(fill="x")
        ttk.Label(
            wrap,
            text=f"전체 {metrics['total']}문장 · 마지막 저장된 기록을 기준으로 표시합니다.",
        ).pack(anchor="w", pady=(8, 18))
        buttons = ttk.Frame(wrap)
        buttons.pack(fill="x")
        if metrics["success"] < metrics["total"]:
            ttk.Button(
                buttons,
                text="번역 다시 재개",
                style="Primary.TButton",
                command=lambda p=path, w=win: (w.destroy(), self.resume_history(p)),
            ).pack(side="right")
        ttk.Button(buttons, text="닫기", command=win.destroy).pack(side="left")

    def resume_history(self, path):
        if self._scan_busy:
            return
        data = self.load_json(Path(path))
        sig = data.get("signature", {})
        source = sig.get("source_path", "")
        if not source or not Path(source).exists():
            messagebox.showerror("RenPy Tools", "기록에 저장된 원본 게임 폴더를 찾지 못했습니다. 게임 위치가 바뀌었다면 새로 선택해주세요.")
            return

        if sig.get("source_lang") in SOURCE_CODES:
            self.source_lang.set(sig["source_lang"])
        if sig.get("target_lang") in LANGS:
            self.target_lang.set(sig["target_lang"])
        if sig.get("provider") in PROVIDERS:
            self.provider.set(sig["provider"])

        self._resume_history_path = Path(path)
        self._scan_busy = True
        self._original_source_path = source
        self._apply_game_override = None
        self.source_path.set(source)
        self.route = "quick_select"
        self.render()
        self.scan.set("저장된 번역 기록을 불러오고 게임 파일을 확인하고 있어요...")

        def job():
            try:
                result = self._prepare_source(source, status=self._thread_scan_text)
                error = None
            except Exception as exc:
                result = None
                error = str(exc)
            self.after(0, lambda r=result, e=error: self._finish_resume_prepare(r, e))

        threading.Thread(target=job, daemon=True, name="renpy-history-resume").start()

    def _finish_resume_prepare(self, result, error):
        self._scan_busy = False
        if error:
            messagebox.showerror("RenPy Tools", f"번역 재개 준비 실패\n\n{error}")
            return
        self._adopt_prepared_source(result)
        self.scan.set(self.scan.get() + " · 이전 성공 번역을 불러와 이어서 시작합니다.")
        self.start_quick_translation()


def run_all_self_tests():
    code = run_fast_scan_self_test()
    if code:
        return code
    code = run_auto_decompile_self_test()
    if code:
        return code
    code = run_v043_self_test()
    if code:
        return code
    return run_ui_self_test()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_all_self_tests())
    RenPyToolsMain().mainloop()
