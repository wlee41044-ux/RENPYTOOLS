#!/usr/bin/env python3
import sys
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

import RenPyToolsApp as ui_module
import RenPyToolsLauncherV048 as v048_launcher
import v048_master_hq as master_hq
from RenPyToolsLauncherV049 import RenPyToolsV049, run_all_self_tests as run_v049_tests
from v048_master_hq import master_status, profile_for
from v050_manual_merge import (
    build_master_workflow_v050,
    find_latest_workspace,
    find_matching_results,
    load_workspace_manifest,
    merge_apply_and_build_exe,
    run_v050_self_test,
    scan_master_results_v050,
)

# The inherited v0.4.8 methods resolve these names in their own module globals.
# Upgrade only those call sites; keep v048_master_hq.build_master_workflow itself
# untouched so the v0.5.0 wrapper can safely call the original implementation.
v048_launcher.build_master_workflow = build_master_workflow_v050
v048_launcher.scan_master_results = scan_master_results_v050
ui_module.UI_VERSION = "0.5.0"


class RenPyToolsV050(RenPyToolsV049):
    """v0.5.0: manual HQ result merge -> auto apply -> one-file distribution EXE."""

    def __init__(self):
        self.combine_game_path = None
        self.combine_workspace = None
        self.combine_manifest = None
        self.combine_rows = []
        self.combine_listbox = None
        super().__init__()
        v048_launcher.build_master_workflow = build_master_workflow_v050
        v048_launcher.scan_master_results = scan_master_results_v050
        ui_module.UI_VERSION = "0.5.0"
        self.title("RenPy Tools 0.5.0")
        self.render()

    # ------------------------------------------------------------------
    # HQ receive screen: progress detection stays automatic, final merge does not.
    # ------------------------------------------------------------------
    def page_hq_ready(self):
        self.flow_header(2)
        ttk.Label(self.container, text="전체 번역 파일 준비 완료", style="HomeTitle.TLabel").pack(anchor="center")
        ttk.Label(
            self.container,
            text="AI에 현재 작업 TXT를 올리고, 같은 채팅에서 0 / . / 다음 중 하나만 보내며 계속 받으세요.",
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
            text="AI 결과는 게임이름TL_001.txt, 게임이름TL_002.txt ... 형식으로 받습니다. 자동 조합은 하지 않아요.",
            style="Muted.Card.TLabel",
        ).pack(anchor="w", pady=(4, 10))

        progress_card, progress = ui_module.card(body, padding=15)
        progress_card.pack(fill="x", pady=(4, 10))
        self._master_bar = ttk.Progressbar(progress, mode="determinate", maximum=100)
        self._master_bar.pack(fill="x", pady=(2, 6))
        ttk.Label(progress, textvariable=self.master_status_text, style="Card.TLabel").pack(anchor="w")
        ttk.Label(progress, textvariable=self.master_next_text, style="Muted.Card.TLabel", wraplength=900).pack(anchor="w", pady=(3, 0))

        steps = [
            "1. 현재 전체작업 TXT를 선택한 AI 채팅에 첨부합니다.",
            "2. AI가 준 게임이름TL_....txt 파일을 휴대폰 Download에 저장합니다.",
            "3. 중간에 멈추면 같은 채팅에 0, . 또는 다음을 보냅니다.",
            "4. AI가 '모든 번역이 끝났습니다.'라고 하면 홈의 조합하기에서 게임을 선택합니다.",
            "5. 검색된 결과를 일괄 합성 또는 선택 합성하면 게임 적용 + 배포용 EXE 생성까지 진행됩니다.",
        ]
        for text in steps:
            ttk.Label(body, text=text, style="Card.TLabel").pack(anchor="w", pady=3)

        row = ttk.Frame(body, style="Card.TFrame")
        row.pack(fill="x", pady=(12, 0))
        ttk.Button(row, text="선택한 AI 열기", style="Primary.TButton", command=self.open_selected_ai).pack(side="left")
        ttk.Button(row, text="작업 폴더 열기", style="Secondary.TButton", command=self.open_hq_workspace).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="번역 결과 지금 찾기", style="Secondary.TButton", command=self.scan_master_now).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="조합하기", style="Primary.TButton", command=lambda: self._go("combine")).pack(side="right")
        ttk.Button(row, text="홈으로", style="Secondary.TButton", command=self.nav_home).pack(side="right", padx=(0, 8))

        self._update_master_widgets()
        self._schedule_master_scan(1000)

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
            f"감지된 번역 {state['completed']:,} / {state['total']:,}문장 · {state['percent']}% · "
            f"전체작업 {state['current_part']}/{state['part_count']}"
        )
        if state["done"]:
            self.master_next_text.set("✓ 모든 번역 결과를 찾았어요. 자동 조합하지 않습니다 · '조합하기'에서 파일을 확인하세요.")
        else:
            self.master_next_text.set(
                f"현재 첨부할 파일: {state['current_file']} · 다음 ID: {state['next_id']} · "
                "이미 올린 파일이면 같은 채팅에 0 / . / 다음 중 하나만 보내세요."
            )
        return state

    # ------------------------------------------------------------------
    # Manual merge screen requested by the user.
    # ------------------------------------------------------------------
    def page_combine(self):
        self.topbar("조합하기", "게임을 먼저 고른 뒤 게임이름TL 결과만 검색해서 직접 합성합니다.")
        outer, body = ui_module.card(self.container, padding=22)
        outer.pack(fill="both", expand=True, padx=60)

        selected_name = Path(self.combine_game_path).name if self.combine_game_path else "아직 게임을 선택하지 않았어요"
        ttk.Label(body, text=f"조합할 게임: {selected_name}", style="Section.TLabel").pack(anchor="w")
        ttk.Button(body, text="조합할 게임 선택", style="Big.TButton", command=self.choose_combine_game).pack(anchor="w", pady=(8, 12))

        if not self.combine_game_path:
            ttk.Label(
                body,
                text="게임을 선택하면 Download에서 '게임이름TL'로 시작하는 번역 결과를 자동 검색합니다.",
                style="Muted.Card.TLabel",
            ).pack(anchor="w")
            return

        if not self.combine_workspace or not self.combine_manifest:
            ttk.Label(
                body,
                text="이 게임의 고품질 번역 작업 폴더(master_manifest.json)를 찾지 못했습니다.",
                style="Muted.Card.TLabel",
            ).pack(anchor="w", pady=(4, 8))
            ttk.Button(body, text="다시 검색", style="Secondary.TButton", command=self.refresh_combine_results).pack(anchor="w")
            return

        prefix = self.combine_manifest.get("result_prefix", "게임TL")
        ttk.Label(
            body,
            text=f"검색어: {prefix} · 작업 폴더: {self.combine_workspace.name}",
            style="Muted.Card.TLabel",
        ).pack(anchor="w", pady=(0, 8))

        list_frame = ttk.Frame(body, style="Card.TFrame")
        list_frame.pack(fill="both", expand=True)
        self.combine_listbox = tk.Listbox(list_frame, selectmode=tk.EXTENDED, height=12)
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.combine_listbox.yview)
        self.combine_listbox.configure(yscrollcommand=scroll.set)
        self.combine_listbox.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        for row in self.combine_rows:
            verified = "✓ID" if row["verified"] else "이름검증"
            self.combine_listbox.insert(
                tk.END,
                f"{row['path'].name}   |   {row['count']:,}문장   |   {row['first_id']}~{row['last_id']}   |   {verified}"
            )

        if not self.combine_rows:
            self.combine_listbox.insert(tk.END, f"{prefix}로 시작하는 유효한 TXT 결과를 찾지 못했습니다.")
            self.combine_listbox.configure(state=tk.DISABLED)

        buttons = ttk.Frame(body, style="Card.TFrame")
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text="다시 검색", style="Secondary.TButton", command=self.refresh_combine_results).pack(side="left")
        ttk.Button(buttons, text="모두 선택", style="Secondary.TButton", command=self.select_all_combine_results).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="선택 합성 + 패치", style="Primary.TButton", command=self.merge_selected_results).pack(side="right")
        ttk.Button(buttons, text="일괄 합성 + 패치", style="Primary.TButton", command=self.merge_all_results).pack(side="right", padx=(0, 8))

        ttk.Label(
            body,
            text="합성 성공 시 선택한 게임에 바로 적용하고, Download에 게임이름TL.exe 배포파일도 생성합니다.",
            style="Muted.Card.TLabel",
        ).pack(anchor="w", pady=(10, 0))

    def choose_combine_game(self):
        path = self._choose_game("조합할 Ren'Py 게임 선택")
        if not path:
            return
        self.combine_game_path = str(path)
        self._load_combine_context()
        self.render()

    def _load_combine_context(self):
        self.combine_workspace = None
        self.combine_manifest = None
        self.combine_rows = []
        if not self.combine_game_path:
            return
        try:
            workspace = find_latest_workspace(self.combine_game_path)
            if workspace is None:
                return
            manifest = load_workspace_manifest(workspace)
            rows = find_matching_results(self.combine_game_path, workspace, manifest)
            self.combine_workspace = Path(workspace)
            self.combine_manifest = manifest
            self.combine_rows = rows
        except Exception as exc:
            messagebox.showerror("RenPy Tools", f"번역 결과 검색 실패\n\n{exc}")

    def refresh_combine_results(self):
        self._load_combine_context()
        self.render()

    def select_all_combine_results(self):
        if self.combine_listbox and self.combine_rows:
            self.combine_listbox.selection_set(0, tk.END)

    def merge_all_results(self):
        if not self.combine_rows:
            messagebox.showinfo("RenPy Tools", "합성할 번역 결과가 없습니다.")
            return
        self._merge_rows(self.combine_rows)

    def merge_selected_results(self):
        if not self.combine_listbox or not self.combine_rows:
            return
        indexes = list(self.combine_listbox.curselection())
        if not indexes:
            messagebox.showinfo("RenPy Tools", "합성할 파일을 하나 이상 선택하세요.")
            return
        rows = [self.combine_rows[i] for i in indexes if i < len(self.combine_rows)]
        self._merge_rows(rows)

    def _merge_rows(self, rows):
        if not self.combine_manifest or not self.combine_game_path:
            return
        files = [row["path"] for row in rows]
        try:
            result = merge_apply_and_build_exe(self, self.combine_manifest, files, self.combine_game_path)
        except Exception as exc:
            messagebox.showerror("RenPy Tools", f"합성/패치 실패\n\n{exc}")
            return
        backup = f"\n기존 패치 백업: {result['backup']}" if result.get("backup") else ""
        messagebox.showinfo(
            "RenPy Tools",
            f"합성 + 게임 패치 + 배포파일 생성 완료!\n\n"
            f"번역: {result['translations']:,}문장\n"
            f"사용한 결과 파일: {result['files']}개\n"
            f"배포용 파일: {result['exe']}\n"
            f"게임 적용 위치: {result['destination']}"
            f"{backup}"
        )


def run_all_self_tests():
    code = run_v049_tests()
    if code:
        return code
    return run_v050_self_test()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_all_self_tests())
    RenPyToolsV050().mainloop()
