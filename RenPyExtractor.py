#!/usr/bin/env python3
import os, shutil, zipfile, threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from ui_common import *

APP = "RenPy Extractor"
VERSION = "0.2.0"

try:
    from rpatool import RenPyArchive, decompile_rpyc_file
    HAVE_TOOLKIT = True
except Exception:
    HAVE_TOOLKIT = False

class ExtractorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP} {VERSION}")
        self.geometry("820x650")
        self.minsize(720, 560)
        setup_styles(self)

        self.source = tk.StringVar()
        self.make_original = tk.BooleanVar(value=True)
        self.remove_rpyc = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="게임 폴더를 선택해주세요.")
        self.scan_text = tk.StringVar(value="아직 게임을 선택하지 않았습니다.")
        self.output_zip = None
        self.page = 1

        self.container = ttk.Frame(self, padding=24)
        self.container.pack(fill="both", expand=True)
        self.render()

    def clear(self):
        for w in self.container.winfo_children():
            w.destroy()

    def render_header(self, active):
        ttk.Label(self.container, text="RenPy Extractor", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self.container, text="RPA 추출 및 RPYC 디컴파일", style="Subtitle.TLabel").pack(anchor="w", pady=(2, 16))
        stepper(self.container, active, ["게임 폴더 선택", "옵션 설정", "디컴파일", "완료"])

    def render(self):
        self.clear()
        self.render_header(self.page)
        if self.page == 1: self.page_folder()
        elif self.page == 2: self.page_options()
        elif self.page == 3: self.page_work()
        else: self.page_done()

    def page_folder(self):
        outer, c = card(self.container)
        outer.pack(fill="x")
        ttk.Label(c, text="📁  디컴파일할 게임 폴더 선택", style="Section.TLabel").pack(anchor="w")
        ttk.Label(c, text="Ren'Py 게임의 최상위 폴더를 선택해주세요.", style="Muted.Card.TLabel").pack(anchor="w", pady=(3, 12))

        row = ttk.Frame(c, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self.source).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="찾아보기", style="Secondary.TButton", command=self.pick_folder).pack(side="left", padx=(8,0))

        ttk.Label(c, textvariable=self.scan_text, style="Muted.Card.TLabel").pack(anchor="w", pady=(10,0))

        btns = ttk.Frame(self.container)
        btns.pack(fill="x", pady=(18,0))
        self.next_btn = ttk.Button(btns, text="다음  ›", style="Primary.TButton", command=self.to_options)
        self.next_btn.pack(side="right")

    def pick_folder(self):
        p = filedialog.askdirectory(title="Ren'Py 게임 폴더 선택")
        if not p:
            return
        self.source.set(p)
        root = Path(p)
        rpa = len(list(root.rglob("*.rpa"))) + len(list(root.rglob("*.rpi")))
        rpyc = len(list(root.rglob("*.rpyc")))
        rpymc = len(list(root.rglob("*.rpymc")))
        rpy = len(list(root.rglob("*.rpy")))
        self.scan_text.set(f"게임 인식 완료  ·  RPA/RPI {rpa}개  ·  RPYC {rpyc}개  ·  RPYMC {rpymc}개  ·  RPY {rpy}개")

    def to_options(self):
        if not Path(self.source.get()).is_dir():
            messagebox.showerror(APP, "먼저 올바른 게임 폴더를 선택해주세요.")
            return
        self.page = 2
        self.render()

    def page_options(self):
        outer, c = card(self.container)
        outer.pack(fill="x")

        ttk.Label(c, text="파일 처리 옵션", style="Section.TLabel").pack(anchor="w", pady=(0,12))

        ttk.Checkbutton(
            c, variable=self.make_original,
            text="파일 복제 (기본적으로 켜짐)"
        ).pack(anchor="w")
        ttk.Label(
            c, text="입력 게임을 Original 폴더에 그대로 복사해 안전하게 보관합니다.",
            style="Muted.Card.TLabel"
        ).pack(anchor="w", padx=(24,0), pady=(2,12))

        ttk.Checkbutton(
            c, variable=self.remove_rpyc,
            text="디컴파일 결과에서 RPYC 제거"
        ).pack(anchor="w")
        ttk.Label(
            c, text="디컴파일에 성공한 .rpyc/.rpymc만 Decompiled 폴더에서 제거합니다. Original에는 영향을 주지 않습니다.",
            style="Muted.Card.TLabel"
        ).pack(anchor="w", padx=(24,0), pady=(2,0))

        if not HAVE_TOOLKIT:
            ttk.Label(
                c, text="⚠ rpa-toolkit이 현재 Python 환경에 없습니다. EXE 빌드 시 자동 포함되도록 구성되어 있습니다.",
                style="Muted.Card.TLabel"
            ).pack(anchor="w", pady=(16,0))

        btns = ttk.Frame(self.container)
        btns.pack(fill="x", pady=(18,0))
        ttk.Button(btns, text="‹  이전", style="Secondary.TButton", command=self.back).pack(side="left")
        ttk.Button(btns, text="디컴파일 시작  ›", style="Primary.TButton", command=self.start).pack(side="right")

    def back(self):
        self.page = max(1, self.page-1)
        self.render()

    def start(self):
        if not HAVE_TOOLKIT:
            messagebox.showerror(APP, "rpa-toolkit을 불러오지 못했습니다.\n\n소스 실행이라면 requirements.txt를 설치해주세요.")
            return
        out = filedialog.asksaveasfilename(
            title="결과 ZIP 저장",
            defaultextension=".zip",
            filetypes=[("ZIP 파일", "*.zip")],
            initialfile=Path(self.source.get()).name + "_decompiled.zip"
        )
        if not out:
            return
        self.output_zip = Path(out)
        self.page = 3
        self.render()
        threading.Thread(target=self.worker, daemon=True).start()

    def page_work(self):
        outer, c = card(self.container)
        outer.pack(fill="both", expand=True)
        ttk.Label(c, text="디컴파일 진행 중", style="Section.TLabel").pack(anchor="w")
        ttk.Label(c, textvariable=self.status, style="Muted.Card.TLabel").pack(anchor="w", pady=(3,12))
        self.bar = ttk.Progressbar(c, mode="determinate")
        self.bar.pack(fill="x")
        self.percent = ttk.Label(c, text="0%", style="Muted.Card.TLabel")
        self.percent.pack(anchor="e", pady=(4,10))
        self.details_btn = ttk.Button(c, text="자세히 보기", style="Flat.TButton", command=self.toggle_log)
        self.details_btn.pack(anchor="w")
        self.log = tk.Text(c, height=12, wrap="word", state="disabled", relief="flat", bg="#F8FAFD")
        self.log_visible = False

    def toggle_log(self):
        if self.log_visible:
            self.log.pack_forget()
            self.details_btn.config(text="자세히 보기")
        else:
            self.log.pack(fill="both", expand=True, pady=(8,0))
            self.details_btn.config(text="자세히 숨기기")
        self.log_visible = not self.log_visible

    def add_log(self, text):
        def work():
            if not hasattr(self, "log"): return
            self.log.configure(state="normal")
            self.log.insert("end", text + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        self.after(0, work)

    def set_progress(self, i, total, status=None):
        def work():
            if not hasattr(self, "bar"): return
            total2 = max(total, 1)
            self.bar["maximum"] = total2
            self.bar["value"] = i
            self.percent.config(text=f"{int(i/total2*100)}%")
            if status:
                self.status.set(status)
        self.after(0, work)

    def extract_archives(self, root):
        archives = list(root.rglob("*.rpa")) + list(root.rglob("*.rpi"))
        for idx, archive in enumerate(archives, 1):
            self.status.set(f"RPA 추출 중 · {archive.name}")
            try:
                with RenPyArchive(str(archive)) as rpa:
                    names = rpa.list()
                    for name in names:
                        try:
                            data = rpa.read(name)
                            out = archive.parent / name
                            out.parent.mkdir(parents=True, exist_ok=True)
                            if not out.exists():
                                out.write_bytes(data)
                        except Exception as e:
                            self.add_log(f"[파일 실패] {name}: {e}")
                self.add_log(f"[RPA 완료] {archive.name}")
            except Exception as e:
                self.add_log(f"[RPA 실패] {archive}: {e}")
        return len(archives)

    def worker(self):
        src = Path(self.source.get())
        out_zip = self.output_zip
        workdir = out_zip.parent / (out_zip.stem + "_work")
        try:
            if workdir.exists():
                shutil.rmtree(workdir)
            workdir.mkdir(parents=True)

            original = workdir / "Original"
            decompiled = workdir / "Decompiled"

            self.set_progress(0, 1, "파일 복사 중...")
            if self.make_original.get():
                shutil.copytree(src, original)
                self.add_log("[완료] Original 복사본 생성")

            shutil.copytree(src, decompiled)
            self.add_log("[완료] 작업용 Decompiled 복사본 생성")

            self.set_progress(0, 1, "RPA/RPI 추출 중...")
            archive_count = self.extract_archives(decompiled)

            compiled = list(decompiled.rglob("*.rpyc")) + list(decompiled.rglob("*.rpymc"))
            total = len(compiled)
            ok = fail = 0

            for i, fp in enumerate(compiled, 1):
                out = fp.with_suffix(".rpym" if fp.suffix.lower() == ".rpymc" else ".rpy")
                try:
                    result = decompile_rpyc_file(fp, output_path=out, overwrite=True)
                    if getattr(result, "success", True):
                        ok += 1
                        if self.remove_rpyc.get():
                            fp.unlink(missing_ok=True)
                        self.add_log(f"[완료] {fp.relative_to(decompiled)}")
                    else:
                        fail += 1
                        self.add_log(f"[실패] {fp.relative_to(decompiled)}: {getattr(result,'error','알 수 없는 오류')}")
                except Exception as e:
                    fail += 1
                    self.add_log(f"[실패] {fp.relative_to(decompiled)}: {e}")
                self.set_progress(i, total, f"RPYC 디컴파일 중 · {i}/{total}")

            self.set_progress(1, 1, "ZIP 생성 중...")
            readme = workdir / "README_결과.txt"
            readme.write_text(
                f"{APP} {VERSION}\n"
                f"RPA/RPI 처리: {archive_count}\n"
                f"RPYC/RPYMC: {total}\n성공: {ok}\n실패: {fail}\n"
                f"Original 생성: {'예' if self.make_original.get() else '아니오'}\n"
                f"Decompiled의 RPYC 제거: {'예' if self.remove_rpyc.get() else '아니오'}\n",
                encoding="utf-8"
            )

            with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
                for p in workdir.rglob("*"):
                    if p.is_file():
                        z.write(p, p.relative_to(workdir))

            self.result = (ok, fail)
            self.after(0, self.finish_success)
        except Exception as e:
            self.after(0, lambda: messagebox.showerror(APP, f"작업 중 오류가 발생했습니다.\n\n{e}"))
            self.after(0, lambda: self.status.set("작업 실패"))
        finally:
            try:
                if workdir.exists(): shutil.rmtree(workdir)
            except Exception:
                pass

    def finish_success(self):
        self.page = 4
        self.render()

    def page_done(self):
        ok, fail = getattr(self, "result", (0,0))
        outer, c = card(self.container)
        outer.pack(fill="x")
        ttk.Label(c, text="✓  디컴파일 완료", style="Section.TLabel").pack(anchor="center")
        ttk.Label(c, text=f"성공 {ok}개  ·  실패 {fail}개", style="Muted.Card.TLabel").pack(anchor="center", pady=(5,12))
        ttk.Label(c, text=str(self.output_zip), style="Muted.Card.TLabel").pack(anchor="center")
        row = ttk.Frame(self.container)
        row.pack(fill="x", pady=(18,0))
        ttk.Button(row, text="처음으로", style="Secondary.TButton", command=self.restart).pack(side="left")
        ttk.Button(row, text="결과 위치 열기", style="Primary.TButton", command=self.open_output).pack(side="right")

    def restart(self):
        self.page = 1
        self.render()

    def open_output(self):
        try:
            os.startfile(str(self.output_zip.parent))
        except Exception:
            messagebox.showinfo(APP, f"결과 위치:\n{self.output_zip.parent}")

if __name__ == "__main__":
    ExtractorApp().mainloop()
