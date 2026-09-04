#!/usr/bin/env python3
import shutil
import time
from pathlib import Path

from tkinter import messagebox, ttk

import RenPyToolsApp as ui_module
from RenPyToolsLauncherV053 import RenPyToolsV053
from v043_features import history_metrics

ui_module.UI_VERSION = "0.5.4"


class RenPyToolsV054(RenPyToolsV053):
    """v0.5.4: strict decompile prep + full retranslation from history."""

    def __init__(self):
        self._force_retranslate_once = False
        super().__init__()
        ui_module.UI_VERSION = "0.5.4"
        self.title("RenPy Tools 0.5.4")
        self.render()

    def load_saved_memory(self, options):
        if getattr(self, "_force_retranslate_once", False):
            self._force_retranslate_once = False
            self.add_log("[번역 다시하기] 이전 번역 결과를 사용하지 않고 전체 문장을 새로 번역합니다.")
            return {}, {}
        return super().load_saved_memory(options)

    def page_history(self):
        self.topbar(
            "번역 기록",
            "중단된 작업은 이어서 하고, 완료된 기록도 필요하면 처음부터 다시 번역할 수 있어요.",
        )
        rows = self.list_history_files()
        if not rows:
            ttk.Label(
                self.container,
                text="아직 저장된 번역 기록이 없어요.",
                style="Subtitle.TLabel",
            ).pack(anchor="center", pady=80)
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
                actions,
                text="번역 현황",
                style="Secondary.TButton",
                command=lambda p=path: self.show_history_status(p),
            ).pack(side="left", padx=(0, 6))
            resume_state = "normal" if metrics["success"] < metrics["total"] else "disabled"
            ttk.Button(
                actions,
                text="번역 다시 재개",
                style="Primary.TButton",
                state=resume_state,
                command=lambda p=path: self.resume_history(p),
            ).pack(side="left", padx=(0, 6))
            ttk.Button(
                actions,
                text="번역 다시하기",
                style="Primary.TButton",
                command=lambda p=path: self.retranslate_history(p),
            ).pack(side="left", padx=(0, 6))
            ttk.Button(
                actions,
                text="기록 열기",
                style="Secondary.TButton",
                command=lambda p=path: self.open_history_detail(p),
            ).pack(side="left")

    def retranslate_history(self, path):
        path = Path(path)
        data = self.load_json(path)
        sig = data.get("signature", {})
        source = sig.get("source_path", "")
        if not source or not Path(source).exists():
            messagebox.showerror(
                "RenPy Tools",
                "기록에 저장된 원본 게임 폴더를 찾지 못했습니다. 게임 위치가 바뀌었다면 새로 선택해주세요.",
            )
            return

        name = Path(source).name or "게임"
        if not messagebox.askyesno(
            "번역 다시하기",
            f"{name} 번역을 처음부터 다시 할까요?\n\n"
            "기존 번역 결과는 재사용하지 않습니다. 현재 기록은 자동으로 백업한 뒤 새 번역 기록으로 갱신합니다.",
        ):
            return

        try:
            backup_dir = self.history_root() / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup = backup_dir / f"{path.stem}_{time.strftime('%Y%m%d_%H%M%S')}.json"
            shutil.copy2(path, backup)
        except Exception as exc:
            messagebox.showerror("RenPy Tools", f"기존 번역 기록 백업에 실패했습니다.\n\n{exc}")
            return

        self._force_retranslate_once = True
        self.resume_history(path)

    def _finish_resume_prepare(self, result, error):
        self._scan_busy = False
        if error:
            messagebox.showerror("RenPy Tools", f"번역 준비 실패\n\n{error}")
            self._force_retranslate_once = False
            return
        self._adopt_prepared_source(result)
        if getattr(self, "_force_retranslate_once", False):
            self.scan.set(self.scan.get() + " · 기존 번역을 사용하지 않고 처음부터 다시 번역합니다.")
        else:
            self.scan.set(self.scan.get() + " · 이전 성공 번역을 불러와 이어서 시작합니다.")
        self.start_quick_translation()


if __name__ == "__main__":
    RenPyToolsV054().mainloop()
