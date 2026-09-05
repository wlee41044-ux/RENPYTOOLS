#!/usr/bin/env python3
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import RenPyToolsApp as ui_module
import RenPyToolsLauncherV050 as v050_launcher
from RenPyToolsLauncherV058 import RenPyToolsV058
from v059_hq_result_discovery import (
    find_matching_results_v059,
    install_v059_hq_contract,
    result_row_for_path,
)

install_v059_hq_contract()
v050_launcher.find_matching_results = find_matching_results_v059
ui_module.UI_VERSION = "0.5.9"


class RenPyToolsV059(RenPyToolsV058):
    """v0.5.9: detect AI-renamed HQ result files and allow direct multi-file selection."""

    def __init__(self):
        super().__init__()
        install_v059_hq_contract()
        v050_launcher.find_matching_results = find_matching_results_v059
        ui_module.UI_VERSION = "0.5.9"
        self.title("RenPy Tools 0.5.9")
        self.render()

    def page_combine(self):
        self.topbar("조합하기", "파일명이 달라도 내용/게임ID로 찾고, 필요하면 TXT를 직접 선택할 수 있어요.")
        outer, body = ui_module.card(self.container, padding=22)
        outer.pack(fill="both", expand=True, padx=60)

        selected_name = Path(self.combine_game_path).name if self.combine_game_path else "아직 게임을 선택하지 않았어요"
        ttk.Label(body, text=f"조합할 게임: {selected_name}", style="Section.TLabel").pack(anchor="w")
        ttk.Button(body, text="조합할 게임 선택", style="Big.TButton", command=self.choose_combine_game).pack(anchor="w", pady=(8, 12))

        if not self.combine_game_path:
            ttk.Label(
                body,
                text="게임을 선택하면 Download의 TXT를 게임ID/내용으로 확인합니다. AI가 파일명을 바꿔도 찾을 수 있어요.",
                style="Muted.Card.TLabel",
            ).pack(anchor="w")
            return

        if not self.combine_workspace or not self.combine_manifest:
            ttk.Label(
                body,
                text="이 게임의 고품질 번역 작업 정보(master_manifest.json)를 찾지 못했습니다.",
                style="Muted.Card.TLabel",
            ).pack(anchor="w", pady=(4, 8))
            ttk.Button(body, text="다시 검색", style="Secondary.TButton", command=self.refresh_combine_results).pack(anchor="w")
            return

        prefix = self.combine_manifest.get("result_prefix", "게임TL")
        ttk.Label(
            body,
            text=f"권장 파일명: {prefix}_001.txt ... · 이름이 달라도 game_id/번역 ID가 맞으면 검색합니다.",
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
            if row.get("verified"):
                check = "✓ 게임ID"
            elif row.get("manual"):
                check = "직접선택"
            elif row.get("name_match"):
                check = "✓ 파일명"
            elif row.get("needs_confirmation"):
                check = "⚠ 내용일치"
            else:
                check = "내용검증"
            self.combine_listbox.insert(
                tk.END,
                f"{row['path'].name}   |   {row['count']:,}문장   |   {row['first_id']}~{row['last_id']}   |   {check}"
            )

        if not self.combine_rows:
            self.combine_listbox.insert(tk.END, "자동으로 찾은 번역 결과가 없습니다. 아래 '파일 직접 선택'을 눌러보세요.")
            self.combine_listbox.configure(state=tk.DISABLED)

        buttons = ttk.Frame(body, style="Card.TFrame")
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text="다시 검색", style="Secondary.TButton", command=self.refresh_combine_results).pack(side="left")
        ttk.Button(buttons, text="파일 직접 선택", style="Secondary.TButton", command=self.choose_combine_files).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="모두 선택", style="Secondary.TButton", command=self.select_all_combine_results).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="선택 합성 + 패치", style="Primary.TButton", command=self.merge_selected_results).pack(side="right")
        ttk.Button(buttons, text="일괄 합성 + 패치", style="Primary.TButton", command=self.merge_all_results).pack(side="right", padx=(0, 8))

        ttk.Label(
            body,
            text="게임ID가 없는 이름 다른 파일은 ⚠ 내용일치로 표시합니다. 직접 선택한 파일은 사용자가 확인한 것으로 처리합니다.",
            style="Muted.Card.TLabel",
        ).pack(anchor="w", pady=(10, 0))

    def choose_combine_files(self):
        if not self.combine_manifest or not self.combine_workspace:
            messagebox.showinfo("RenPy Tools", "먼저 조합할 게임을 선택하세요.")
            return
        paths = filedialog.askopenfilenames(
            parent=self,
            title="조합할 번역 TXT 선택",
            filetypes=[("번역 결과 TXT", "*.txt"), ("모든 파일", "*.*")],
        )
        if not paths:
            return

        existing = set()
        for row in self.combine_rows:
            try:
                existing.add(str(Path(row["path"]).resolve()).lower())
            except Exception:
                existing.add(str(row["path"]).lower())

        added = 0
        rejected = []
        prefix = self.combine_manifest.get("result_prefix", "")
        for raw in paths:
            path = Path(raw)
            row = result_row_for_path(
                path,
                self.combine_manifest,
                prefix=prefix,
                manual=True,
                workspace=self.combine_workspace,
            )
            if row is None:
                rejected.append(path.name)
                continue
            try:
                key = str(path.resolve()).lower()
            except Exception:
                key = str(path).lower()
            if key in existing:
                continue
            existing.add(key)
            self.combine_rows.append(row)
            added += 1

        self.combine_rows.sort(key=lambda row: row.get("mtime", 0))
        self.render()
        if rejected:
            messagebox.showwarning(
                "RenPy Tools",
                f"{added}개 파일을 추가했어요.\n\n번역 ID가 없거나 다른 게임 ID인 파일 {len(rejected)}개는 제외했습니다:\n"
                + "\n".join(rejected[:8]),
            )
        elif added:
            messagebox.showinfo("RenPy Tools", f"번역 결과 {added}개를 직접 추가했어요.")

    def _merge_rows(self, rows):
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
        return super()._merge_rows(rows)


if __name__ == "__main__":
    RenPyToolsV059().mainloop()
