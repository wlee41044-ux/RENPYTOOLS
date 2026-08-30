#!/usr/bin/env python3
import json
import os
import re
import shutil
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ui_common import *

APP = "RenPy AI Patcher"
VERSION = "0.2.2"

LANGS = {
    "한국어": ("korean", "ko"),
    "English": ("english", "en"),
    "日本語": ("japanese", "ja"),
    "简体中文": ("schinese", "zh-CN"),
    "繁體中文": ("tchinese", "zh-TW"),
    "Español": ("spanish", "es"),
    "Français": ("french", "fr"),
    "Deutsch": ("german", "de"),
}
SOURCE_CODES = {"자동 감지": "auto", **{k: v[1] for k, v in LANGS.items()}}
PROVIDERS = [
    "무료 Google 번역",
    "Ollama (무료/로컬)",
    "LM Studio / OpenAI 호환",
    "OpenAI 호환 API",
]

STRING_RE = re.compile(r'(?P<quote>["\'])(?P<text>(?:\\.|(?!\1).)*?)(?P=quote)')
SKIP_PREFIXES = (
    "image ", "scene ", "show ", "hide ", "play ", "queue ", "stop ",
    "voice ", "jump ", "call ", "label ", "define ", "default ", "$",
    "python:", "init python:", "transform ", "style ", "screen ",
)


def looks_translatable(line, text):
    s = line.strip()
    if not text.strip() or s.startswith("#"):
        return False
    if any(s.lower().startswith(p) for p in SKIP_PREFIXES):
        return False
    if re.fullmatch(r"[\w./\\:@#%+\-=]+", text) and " " not in text:
        return False
    if re.search(r"\.(png|jpg|jpeg|webp|gif|ogg|mp3|wav|opus|rpy|rpyc)$", text, re.I):
        return False
    return True


def mask_tokens(text):
    tokens = []
    pattern = re.compile(r'(\{[^{}]*\}|\[[^\[\]]*\])')

    def repl(match):
        key = f"__RPTOKEN_{len(tokens)}__"
        tokens.append((key, match.group(0)))
        return key

    return pattern.sub(repl, text), tokens


def unmask(text, tokens):
    for key, value in tokens:
        text = text.replace(key, value)
    return text


def escape_rpy(text):
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class Translator:
    def __init__(self, provider, source, target, key="", url="", model=""):
        self.provider = provider
        self.source = source
        self.target = target
        self.key = key.strip()
        self.url = url.strip()
        self.model = model.strip()

    def translate(self, text):
        masked, tokens = mask_tokens(text)
        if self.provider == "무료 Google 번역":
            out = self.google(masked)
        elif self.provider == "Ollama (무료/로컬)":
            out = self.openai(masked, self.url or "http://127.0.0.1:11434/v1/chat/completions", self.model or "qwen2.5:7b", self.key or "ollama")
        elif self.provider == "LM Studio / OpenAI 호환":
            out = self.openai(masked, self.url or "http://127.0.0.1:1234/v1/chat/completions", self.model or "local-model", self.key or "lm-studio")
        else:
            if not self.url or not self.model:
                raise RuntimeError("OpenAI 호환 API는 Base URL과 Model이 필요합니다.")
            out = self.openai(masked, self.url, self.model, self.key)
        return unmask(out.strip(), tokens)

    def google(self, text):
        q = urllib.parse.quote(text)
        url = (
            "https://translate.googleapis.com/translate_a/single?client=gtx"
            f"&sl={urllib.parse.quote(self.source)}"
            f"&tl={urllib.parse.quote(self.target)}&dt=t&q={q}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
        return "".join(x[0] for x in data[0] if x and x[0])

    def openai(self, text, url, model, key):
        payload = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": "Translate visual novel text. Return only translated text. Preserve every __RPTOKEN_n__ placeholder exactly."},
                {"role": "user", "content": f"Translate to {self.target}:\n{text}"},
            ],
            "temperature": 0.2,
        }).encode()
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=120) as response:
            data = json.loads(response.read().decode())
        return data["choices"][0]["message"]["content"]


def collect_rpy(root):
    game = root / "game"
    if root.name.lower() == "game":
        game = root
    if not game.is_dir():
        raise RuntimeError("Ren'Py game 폴더를 찾지 못했습니다.")
    files = [p for p in game.rglob("*.rpy") if "tl" not in p.relative_to(game).parts]
    return game, files


def extract_strings(path):
    text = path.read_text("utf-8", errors="replace")
    out = []
    seen = set()
    for no, line in enumerate(text.splitlines(), 1):
        for match in STRING_RE.finditer(line):
            value = match.group("text")
            if looks_translatable(line, value) and value not in seen:
                seen.add(value)
                out.append((no, value))
    return out


class PatcherApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP} {VERSION}")
        self.geometry("860x690")
        self.minsize(740, 590)
        setup_styles(self)
        self.source_path = tk.StringVar()
        self.source_lang = tk.StringVar(value="자동 감지")
        self.target_lang = tk.StringVar(value="한국어")
        self.provider = tk.StringVar(value="무료 Google 번역")
        self.api_key = tk.StringVar()
        self.base_url = tk.StringVar()
        self.model = tk.StringVar()
        self.scan = tk.StringVar(value="아직 게임을 선택하지 않았습니다.")
        self.status = tk.StringVar(value="")
        self.page = 1
        self.output_zip = None
        self.job_options = None
        self.container = ttk.Frame(self, padding=24)
        self.container.pack(fill="both", expand=True)
        self.render()

    def clear(self):
        for widget in self.container.winfo_children():
            widget.destroy()

    def header(self, active):
        ttk.Label(self.container, text=f"AI Patcher  v{VERSION}", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self.container, text="Ren'Py AI 한글패치 제작 · 고속 병렬 번역", style="Subtitle.TLabel").pack(anchor="w", pady=(2, 16))
        stepper(self.container, active, ["게임 폴더 선택", "옵션 설정", "번역 및 패치", "완료"])

    def render(self):
        self.clear()
        self.header(self.page)
        [self.page_folder, self.page_options, self.page_work, self.page_done][self.page - 1]()

    def page_folder(self):
        outer, body = card(self.container)
        outer.pack(fill="x")
        ttk.Label(body, text="📁  번역할 게임 폴더 선택", style="Section.TLabel").pack(anchor="w")
        ttk.Label(body, text="Extractor에서 만든 Decompiled 폴더도 바로 선택할 수 있습니다.", style="Muted.Card.TLabel").pack(anchor="w", pady=(3, 12))
        row = ttk.Frame(body, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self.source_path).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="찾아보기", style="Secondary.TButton", command=self.pick).pack(side="left", padx=(8, 0))
        ttk.Label(body, textvariable=self.scan, style="Muted.Card.TLabel").pack(anchor="w", pady=(10, 0))
        buttons = ttk.Frame(self.container); buttons.pack(fill="x", pady=(18, 0))
        ttk.Button(buttons, text="다음  ›", style="Primary.TButton", command=self.next_options).pack(side="right")

    def pick(self):
        path = filedialog.askdirectory(title="번역할 Ren'Py 게임 폴더 선택")
        if not path: return
        self.source_path.set(path)
        try:
            _, files = collect_rpy(Path(path))
            count = sum(len(extract_strings(x)) for x in files)
            self.scan.set(f"게임 인식 완료  ·  RPY {len(files)}개  ·  번역 후보 {count}개")
        except Exception as exc:
            self.scan.set(str(exc))

    def next_options(self):
        try: collect_rpy(Path(self.source_path.get()))
        except Exception as exc:
            messagebox.showerror(APP, str(exc)); return
        self.page = 2; self.render()

    def page_options(self):
        wrap = ttk.Frame(self.container); wrap.pack(fill="x")
        lo, left = card(wrap); lo.pack(side="left", fill="both", expand=True, padx=(0, 8))
        ro, right = card(wrap); ro.pack(side="left", fill="both", expand=True, padx=(8, 0))
        ttk.Label(left, text="번역 옵션", style="Section.TLabel").pack(anchor="w", pady=(0, 10))
        self.combo_row(left, "원본 언어", self.source_lang, list(SOURCE_CODES))
        self.combo_row(left, "번역 언어", self.target_lang, list(LANGS))
        self.combo_row(left, "번역 방식", self.provider, PROVIDERS)
        ttk.Label(left, text="무료 Google 번역은 최대 8개 문장을 동시에 처리합니다.", style="Muted.Card.TLabel").pack(anchor="w", pady=(10, 0))
        ttk.Label(right, text="고급 연결 설정", style="Section.TLabel").pack(anchor="w", pady=(0, 10))
        ttk.Label(right, text="무료 번역은 아래 항목을 비워도 됩니다.", style="Muted.Card.TLabel").pack(anchor="w", pady=(0, 10))
        self.entry_row(right, "API Key", self.api_key, show="•")
        self.entry_row(right, "Model", self.model)
        self.entry_row(right, "Base URL", self.base_url)
        buttons = ttk.Frame(self.container); buttons.pack(fill="x", pady=(18, 0))
        ttk.Button(buttons, text="‹  이전", style="Secondary.TButton", command=self.back).pack(side="left")
        ttk.Button(buttons, text="한글패치 만들기  ›", style="Primary.TButton", command=self.start).pack(side="right")

    def combo_row(self, parent, label, var, values):
        ttk.Label(parent, text=label, style="Card.TLabel").pack(anchor="w", pady=(7, 3))
        ttk.Combobox(parent, textvariable=var, values=values, state="readonly").pack(fill="x")

    def entry_row(self, parent, label, var, show=None):
        ttk.Label(parent, text=label, style="Card.TLabel").pack(anchor="w", pady=(7, 3))
        ttk.Entry(parent, textvariable=var, show=show).pack(fill="x")

    def back(self):
        self.page = max(1, self.page - 1); self.render()

    def start(self):
        out = filedialog.asksaveasfilename(title="패치 ZIP 저장", defaultextension=".zip", filetypes=[("ZIP 파일", "*.zip")], initialfile=f"RenPy_{LANGS[self.target_lang.get()][0]}_patch.zip")
        if not out: return
        self.job_options = {
            "source_path": self.source_path.get(), "source_lang": self.source_lang.get(),
            "target_lang": self.target_lang.get(), "provider": self.provider.get(),
            "api_key": self.api_key.get(), "base_url": self.base_url.get(), "model": self.model.get(),
        }
        self.output_zip = Path(out); self.page = 3; self.render()
        threading.Thread(target=self.worker, daemon=True).start()

    def page_work(self):
        outer, body = card(self.container); outer.pack(fill="both", expand=True)
        ttk.Label(body, text="번역 및 패치 생성 중", style="Section.TLabel").pack(anchor="w")
        ttk.Label(body, textvariable=self.status, style="Muted.Card.TLabel").pack(anchor="w", pady=(3, 12))
        self.bar = ttk.Progressbar(body, mode="determinate"); self.bar.pack(fill="x")
        self.percent = ttk.Label(body, text="0%", style="Muted.Card.TLabel"); self.percent.pack(anchor="e", pady=(4, 8))
        self.details = ttk.Button(body, text="자세히 보기", style="Flat.TButton", command=self.toggle_log); self.details.pack(anchor="w")
        self.log = tk.Text(body, height=12, wrap="word", state="disabled", relief="flat", bg="#F8FAFD")
        self.log_visible = False

    def toggle_log(self):
        if self.log_visible:
            self.log.pack_forget(); self.details.config(text="자세히 보기")
        else:
            self.log.pack(fill="both", expand=True, pady=(8, 0)); self.details.config(text="자세히 숨기기")
        self.log_visible = not self.log_visible

    def add_log(self, text):
        def update():
            if not hasattr(self, "log"): return
            self.log.configure(state="normal"); self.log.insert("end", text + "\n"); self.log.see("end"); self.log.configure(state="disabled")
        self.after(0, update)

    def progress(self, index, total, status):
        def update():
            if not hasattr(self, "bar"): return
            safe_total = max(total, 1)
            self.bar["maximum"] = safe_total; self.bar["value"] = index
            self.percent.config(text=f"{int(index / safe_total * 100)}%")
            self.status.set(status)
        self.after(0, update)

    @staticmethod
    def translate_with_retry(translator, text):
        last_error = None
        for attempt in range(3):
            try:
                return translator.translate(text), None
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
        return text, last_error

    def worker(self):
        temp = self.output_zip.parent / (self.output_zip.stem + "_work")
        try:
            options = self.job_options
            game, files = collect_rpy(Path(options["source_path"]))
            items = []
            for file_path in files:
                for no, source_text in extract_strings(file_path):
                    items.append((file_path, no, source_text))
            if not items:
                raise RuntimeError("번역 가능한 .rpy 문자열을 찾지 못했습니다.")

            target_dir, target_code = LANGS[options["target_lang"]]
            translator = Translator(options["provider"], SOURCE_CODES[options["source_lang"]], target_code, options["api_key"], options["base_url"], options["model"])
            if temp.exists(): shutil.rmtree(temp)
            patch_root = temp / "game" / "tl" / target_dir; patch_root.mkdir(parents=True)

            unique_texts = list(dict.fromkeys(source_text for _, _, source_text in items))
            total_unique = len(unique_texts)
            workers = 8 if options["provider"] == "무료 Google 번역" else 4
            memory = {}
            failed = 0
            self.add_log(f"[고속 번역] 전체 {len(items)}개 · 중복 제거 {total_unique}개 · 동시 작업 {workers}개")

            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="translate") as pool:
                futures = {pool.submit(self.translate_with_retry, translator, text): text for text in unique_texts}
                for done, future in enumerate(as_completed(futures), 1):
                    source_text = futures[future]
                    translated, error = future.result()
                    memory[source_text] = translated
                    if error is not None:
                        failed += 1
                        self.add_log(f"[번역 실패] {source_text[:60]} · {error}")
                    self.progress(done, total_unique, f"고속 번역 중 · {done}/{total_unique} · {workers}개 동시")

            grouped = {}
            for file_path, no, source_text in items:
                grouped.setdefault(file_path, []).append((no, source_text, memory.get(source_text, source_text)))

            for file_path, entries in grouped.items():
                rel = file_path.relative_to(game)
                dest = patch_root / rel; dest.parent.mkdir(parents=True, exist_ok=True)
                lines = ["# Generated by RenPy AI Patcher", f"translate {target_dir} strings:", ""]
                for no, old, new in entries:
                    lines.extend([f"    # {rel.as_posix()}:{no}", f'    old "{escape_rpy(old)}"', f'    new "{escape_rpy(new)}"', ""])
                dest.write_text("\n".join(lines), encoding="utf-8")

            (temp / "패치_설명.txt").write_text(
                "이 ZIP의 game 폴더를 원본 게임 최상위 폴더에 합치세요.\n"
                f"번역 파일은 game/tl/{target_dir}/ 아래에 추가됩니다.\n"
                f"고속 병렬 번역: {workers}개 동시 처리 / 번역 실패: {failed}개\n"
                "원본 게임 전체를 재배포하지 말고, 배포 권리가 있는 패치만 공유하세요.\n", encoding="utf-8")

            self.progress(1, 1, "패치 ZIP 생성 중...")
            with zipfile.ZipFile(self.output_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
                for path in temp.rglob("*"):
                    if path.is_file(): archive.write(path, path.relative_to(temp))
            self.result = len(items)
            self.after(0, self.finish)
        except Exception as exc:
            error_text = str(exc)
            self.after(0, lambda msg=error_text: messagebox.showerror(APP, f"작업 중 오류가 발생했습니다.\n\n{msg}"))
            self.after(0, lambda: self.status.set("작업 실패"))
        finally:
            try:
                if temp.exists(): shutil.rmtree(temp)
            except Exception: pass

    def finish(self):
        self.page = 4; self.render()

    def page_done(self):
        outer, body = card(self.container); outer.pack(fill="x")
        ttk.Label(body, text="✓  한글패치 생성 완료", style="Section.TLabel").pack(anchor="center")
        ttk.Label(body, text=f"처리한 번역 후보 {getattr(self, 'result', 0)}개", style="Muted.Card.TLabel").pack(anchor="center", pady=(5, 12))
        ttk.Label(body, text=str(self.output_zip), style="Muted.Card.TLabel").pack(anchor="center")
        buttons = ttk.Frame(self.container); buttons.pack(fill="x", pady=(18, 0))
        ttk.Button(buttons, text="처음으로", style="Secondary.TButton", command=self.restart).pack(side="left")
        ttk.Button(buttons, text="결과 위치 열기", style="Primary.TButton", command=self.open_output).pack(side="right")

    def restart(self):
        self.page = 1; self.render()

    def open_output(self):
        try: os.startfile(str(self.output_zip.parent))
        except Exception: messagebox.showinfo(APP, f"결과 위치:\n{self.output_zip.parent}")


if __name__ == "__main__":
    PatcherApp().mainloop()
