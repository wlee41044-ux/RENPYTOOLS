#!/usr/bin/env python3
import os
import shutil
import threading
from pathlib import Path, PurePosixPath

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ui_common import *

APP = "RenPy Extractor"
VERSION = "0.2.6"
SCRIPT_EXTS = {".rpy", ".rpyc", ".rpym", ".rpymc"}
COMPILED_EXTS = {".rpyc", ".rpymc"}

try:
    from rpatool import RenPyArchive, decompile_rpyc_file
    HAVE_TOOLKIT = True
except Exception:
    HAVE_TOOLKIT = False


def safe_archive_path(base, name):
    clean = str(name).replace("\\", "/")
    rel = PurePosixPath(clean)
    if rel.is_absolute() or ".." in rel.parts:
        return None
    parts = list(rel.parts)
    if parts and parts[0].lower() == "game":
        parts = parts[1:]
    if not parts:
        return None
    return base.joinpath(*parts)


def resolve_game_folder(root):
    root = Path(root)
    if root.name.lower() == "game" and root.is_dir():
        return root
    if (root / "game").is_dir():
        return root / "game"
    raise RuntimeError("Ren'Py game 폴더를 찾지 못했습니다. 게임 최상위 폴더 또는 game 폴더를 선택하세요.")


class ExtractorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP} {VERSION}")
        self.geometry("820x650")
        self.minsize(720, 560)
        setup_styles(self)

        self.source = tk.StringVar()
        self.make_original = tk.BooleanVar(value=False)
        self.extract_all = tk.BooleanVar(value=False)
        self.remove_rpyc = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="게임 폴더를 선택해주세요.")
        self.scan_text = tk.StringVar(value="아직 게임을 선택하지 않았습니다.")
        self.output_dir = None
        self.job_options = None
        self.page = 1

        self.container = ttk.Frame(self, padding=24)
        self.container.pack(fill="both", expand=True)
        self.render()

    def clear(self):
        for widget in self.container.winfo_children():
            widget.destroy()

    def render_header(self, active):
        ttk.Label(self.container, text=f"RenPy Extractor  v{VERSION}", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            self.container,
            text="RPA 추출 및 RPYC 디컴파일 · 폴더로 바로 출력",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(2, 16))
        stepper(self.container, active, ["게임 폴더 선택", "옵션 설정", "디컴파일", "완료"])

    def render(self):
        self.clear()
        self.render_header(self.page)
        [self.page_folder, self.page_options, self.page_work, self.page_done][self.page - 1]()

    def page_folder(self):
        outer, body = card(self.container)
        outer.pack(fill="x")
        ttk.Label(body, text="📁  디컴파일할 게임 폴더 선택", style="Section.TLabel").pack(anchor="w")
        ttk.Label(
            body,
            text="Ren'Py 게임 최상위 폴더 또는 game 폴더를 선택하세요.",
            style="Muted.Card.TLabel",
        ).pack(anchor="w", pady=(3, 12))

        row = ttk.Frame(body, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self.source).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="찾아보기", style="Secondary.TButton", command=self.pick_folder).pack(side="left", padx=(8, 0))
        ttk.Label(body, textvariable=self.scan_text, style="Muted.Card.TLabel").pack(anchor="w", pady=(10, 0))

        buttons = ttk.Frame(self.container)
        buttons.pack(fill="x", pady=(18, 0))
        ttk.Button(buttons, text="다음  ›", style="Primary.TButton", command=self.to_options).pack(side="right")

    def pick_folder(self):
        selected = filedialog.askdirectory(title="Ren'Py 게임 폴더 선택")
        if not selected:
            return
        self.source.set(selected)
        try:
            game = resolve_game_folder(selected)
            rpa = len(list(game.rglob("*.rpa"))) + len(list(game.rglob("*.rpi")))
            rpyc = len(list(game.rglob("*.rpyc")))
            rpymc = len(list(game.rglob("*.rpymc")))
            rpy = len(list(game.rglob("*.rpy")))
            rpym = len(list(game.rglob("*.rpym")))
            self.scan_text.set(
                f"게임 인식 완료 · RPA/RPI {rpa}개 · RPYC {rpyc}개 · RPYMC {rpymc}개 · RPY/RPYM {rpy + rpym}개"
            )
        except Exception as exc:
            self.scan_text.set(str(exc))

    def to_options(self):
        try:
            resolve_game_folder(self.source.get())
        except Exception as exc:
            messagebox.showerror(APP, str(exc))
            return
        self.page = 2
        self.render()

    def page_options(self):
        outer, body = card(self.container)
        outer.pack(fill="x")
        ttk.Label(body, text="파일 처리 옵션", style="Section.TLabel").pack(anchor="w", pady=(0, 12))

        ttk.Checkbutton(body, variable=self.extract_all, text="RPA의 모든 파일 추출 (느림)").pack(anchor="w")
        ttk.Label(
            body,
            text="끄면 번역에 필요한 .rpy/.rpyc/.rpym/.rpymc만 추출합니다.",
            style="Muted.Card.TLabel",
        ).pack(anchor="w", padx=(24, 0), pady=(2, 12))

        ttk.Checkbutton(body, variable=self.make_original, text="게임 전체 Original 백업 폴더 포함 (매우 느림)").pack(anchor="w")
        ttk.Label(
            body,
            text="ZIP으로 압축하지 않습니다. 켜면 결과 폴더 안 Original에 원본 게임을 복사합니다.",
            style="Muted.Card.TLabel",
        ).pack(anchor="w", padx=(24, 0), pady=(2, 12))

        ttk.Checkbutton(body, variable=self.remove_rpyc, text="성공한 RPYC/RPYMC는 결과에서 제거").pack(anchor="w")

        ttk.Label(
            body,
            text="결과는 항상 게임명_Decompiled/game/... 구조로 만들어 AI Patcher가 바로 인식합니다.",
            style="Muted.Card.TLabel",
        ).pack(anchor="w", pady=(14, 0))

        if not HAVE_TOOLKIT:
            ttk.Label(body, text="⚠ rpa-toolkit을 불러오지 못했습니다.", style="Muted.Card.TLabel").pack(anchor="w", pady=(12, 0))

        buttons = ttk.Frame(self.container)
        buttons.pack(fill="x", pady=(18, 0))
        ttk.Button(buttons, text="‹  이전", style="Secondary.TButton", command=self.back).pack(side="left")
        ttk.Button(buttons, text="디컴파일 시작  ›", style="Primary.TButton", command=self.start).pack(side="right")

    def back(self):
        self.page = max(1, self.page - 1)
        self.render()

    def start(self):
        if not HAVE_TOOLKIT:
            messagebox.showerror(APP, "rpa-toolkit을 불러오지 못했습니다.")
            return

        parent = filedialog.askdirectory(title="디컴파일 결과를 저장할 폴더 선택")
        if not parent:
            return

        src = Path(self.source.get())
        game = resolve_game_folder(src)
        base_name = game.parent.name if game.name.lower() == "game" else src.name
        if not base_name:
            base_name = "RenPyGame"
        self.output_dir = Path(parent) / f"{base_name}_Decompiled"

        if self.output_dir.exists():
            if not messagebox.askyesno(APP, f"기존 결과 폴더가 있습니다. 내용을 새로 만들까요?\n\n{self.output_dir}"):
                return

        self.job_options = {
            "source": self.source.get(),
            "make_original": self.make_original.get(),
            "extract_all": self.extract_all.get(),
            "remove_rpyc": self.remove_rpyc.get(),
        }
        self.page = 3
        self.render()
        threading.Thread(target=self.worker, daemon=True).start()

    def page_work(self):
        outer, body = card(self.container)
        outer.pack(fill="both", expand=True)
        ttk.Label(body, text="디컴파일 진행 중", style="Section.TLabel").pack(anchor="w")
        ttk.Label(body, textvariable=self.status, style="Muted.Card.TLabel").pack(anchor="w", pady=(3, 12))
        self.bar = ttk.Progressbar(body, mode="determinate")
        self.bar.pack(fill="x")
        self.percent = ttk.Label(body, text="0%", style="Muted.Card.TLabel")
        self.percent.pack(anchor="e", pady=(4, 10))
        self.details_btn = ttk.Button(body, text="자세히 보기", style="Flat.TButton", command=self.toggle_log)
        self.details_btn.pack(anchor="w")
        self.log = tk.Text(body, height=12, wrap="word", state="disabled", relief="flat", bg="#F8FAFD")
        self.log_visible = False

    def toggle_log(self):
        if self.log_visible:
            self.log.pack_forget()
            self.details_btn.config(text="자세히 보기")
        else:
            self.log.pack(fill="both", expand=True, pady=(8, 0))
            self.details_btn.config(text="자세히 숨기기")
        self.log_visible = not self.log_visible

    def add_log(self, text):
        def update():
            if not hasattr(self, "log"):
                return
            self.log.configure(state="normal")
            self.log.insert("end", text + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        self.after(0, update)

    def set_progress(self, current, total, status=None):
        def update():
            if not hasattr(self, "bar"):
                return
            safe_total = max(total, 1)
            self.bar["maximum"] = safe_total
            self.bar["value"] = current
            self.percent.config(text=f"{int(current / safe_total * 100)}%")
            if status:
                self.status.set(status)
        self.after(0, update)

    def copy_loose_scripts(self, game_src, dest_game):
        copied = 0
        for path in game_src.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SCRIPT_EXTS:
                continue
            rel = path.relative_to(game_src)
            out = dest_game / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, out)
            copied += 1
        return copied

    def extract_archives(self, game_src, dest_game, extract_all):
        archives = list(game_src.rglob("*.rpa")) + list(game_src.rglob("*.rpi"))
        extracted = 0
        failed = 0

        for index, archive in enumerate(archives, 1):
            self.set_progress(index - 1, len(archives), f"RPA 읽는 중 · {index}/{len(archives)} · {archive.name}")
            try:
                archive_parent = archive.parent.relative_to(game_src)
                with RenPyArchive(str(archive)) as rpa:
                    for name in rpa.list():
                        suffix = Path(str(name)).suffix.lower()
                        if not extract_all and suffix not in SCRIPT_EXTS:
                            continue
                        out = safe_archive_path(dest_game / archive_parent, name)
                        if out is None:
                            failed += 1
                            self.add_log(f"[건너뜀] 안전하지 않은 경로: {name}")
                            continue
                        try:
                            data = rpa.read(name)
                            out.parent.mkdir(parents=True, exist_ok=True)
                            if not out.exists():
                                out.write_bytes(data)
                            extracted += 1
                        except Exception as exc:
                            failed += 1
                            self.add_log(f"[RPA 파일 실패] {archive.name} / {name}: {exc}")
                self.add_log(f"[RPA 완료] {archive.name}")
            except Exception as exc:
                failed += 1
                self.add_log(f"[RPA 실패] {archive}: {exc}")
            self.set_progress(index, len(archives), f"RPA 처리 · {index}/{len(archives)}")

        return len(archives), extracted, failed

    def decompile_scripts(self, dest_game, remove_rpyc):
        compiled = [p for p in dest_game.rglob("*") if p.is_file() and p.suffix.lower() in COMPILED_EXTS]
        ok = 0
        fail = 0
        total = len(compiled)

        for index, path in enumerate(compiled, 1):
            output = path.with_suffix(".rpym" if path.suffix.lower() == ".rpymc" else ".rpy")
            try:
                result = decompile_rpyc_file(path, output_path=output, overwrite=True)
                if getattr(result, "success", True) and output.is_file():
                    ok += 1
                    if remove_rpyc:
                        path.unlink(missing_ok=True)
                    self.add_log(f"[디컴파일 완료] {path.relative_to(dest_game)}")
                else:
                    fail += 1
                    self.add_log(f"[디컴파일 실패] {path.relative_to(dest_game)}: {getattr(result, 'error', '출력 파일 없음')}")
            except Exception as exc:
                fail += 1
                self.add_log(f"[디컴파일 실패] {path.relative_to(dest_game)}: {exc}")
            self.set_progress(index, total, f"RPYC 디컴파일 · {index}/{total}")

        return total, ok, fail

    def worker(self):
        options = self.job_options
        src = Path(options["source"])
        game_src = resolve_game_folder(src)
        output = self.output_dir
        dest_game = output / "game"

        try:
            if output.exists():
                shutil.rmtree(output)
            dest_game.mkdir(parents=True, exist_ok=True)

            self.set_progress(0, 1, "스크립트 찾는 중...")
            loose_count = self.copy_loose_scripts(game_src, dest_game)
            self.add_log(f"[완료] 폴더의 스크립트 {loose_count}개 복사")

            archive_count, extracted_count, archive_fail = self.extract_archives(game_src, dest_game, options["extract_all"])
            total, ok, fail = self.decompile_scripts(dest_game, options["remove_rpyc"])

            if options["make_original"]:
                self.set_progress(0, 1, "Original 백업 복사 중...")
                shutil.copytree(src, output / "Original", dirs_exist_ok=True)

            text_scripts = len(list(dest_game.rglob("*.rpy"))) + len(list(dest_game.rglob("*.rpym")))
            (output / "README_결과.txt").write_text(
                f"{APP} {VERSION}\n"
                f"결과 폴더: {output}\n"
                f"AI Patcher에서는 이 폴더 또는 이 안의 game 폴더를 선택하세요.\n"
                f"RPA/RPI: {archive_count}개\n"
                f"RPA에서 추출: {extracted_count}개\n"
                f"RPA 추출 실패/건너뜀: {archive_fail}개\n"
                f"RPYC/RPYMC: {total}개\n"
                f"디컴파일 성공: {ok}개\n"
                f"디컴파일 실패: {fail}개\n"
                f"읽을 수 있는 RPY/RPYM: {text_scripts}개\n",
                encoding="utf-8",
            )

            self.result = (ok, fail, extracted_count, text_scripts)
            self.set_progress(1, 1, "디컴파일 완료 · 압축 없이 폴더로 저장됨")
            self.after(0, self.finish_success)
        except Exception as exc:
            error_text = str(exc)
            self.after(0, lambda msg=error_text: messagebox.showerror(APP, f"작업 중 오류가 발생했습니다.\n\n{msg}"))
            self.after(0, lambda: self.status.set("작업 실패"))

    def finish_success(self):
        self.page = 4
        self.render()

    def page_done(self):
        ok, fail, extracted, text_scripts = getattr(self, "result", (0, 0, 0, 0))
        outer, body = card(self.container)
        outer.pack(fill="x")
        ttk.Label(body, text="✓  디컴파일 완료", style="Section.TLabel").pack(anchor="center")
        ttk.Label(
            body,
            text=f"성공 {ok}개 · 실패 {fail}개 · RPA 추출 {extracted}개 · RPY/RPYM {text_scripts}개",
            style="Muted.Card.TLabel",
        ).pack(anchor="center", pady=(5, 12))
        ttk.Label(body, text="ZIP이 아니라 아래 폴더에 바로 저장했습니다.", style="Muted.Card.TLabel").pack(anchor="center")
        ttk.Label(body, text=str(self.output_dir), style="Muted.Card.TLabel").pack(anchor="center", pady=(4, 0))

        row = ttk.Frame(self.container)
        row.pack(fill="x", pady=(18, 0))
        ttk.Button(row, text="처음으로", style="Secondary.TButton", command=self.restart).pack(side="left")
        ttk.Button(row, text="결과 폴더 열기", style="Primary.TButton", command=self.open_output).pack(side="right")

    def restart(self):
        self.page = 1
        self.render()

    def open_output(self):
        try:
            os.startfile(str(self.output_dir))
        except Exception:
            messagebox.showinfo(APP, f"결과 위치:\n{self.output_dir}")


if __name__ == "__main__":
    ExtractorApp().mainloop()
