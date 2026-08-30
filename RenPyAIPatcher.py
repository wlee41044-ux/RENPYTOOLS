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
VERSION = "0.2.4"

LANGS = {
    "한국어": ("korean", "ko"), "English": ("english", "en"), "日本語": ("japanese", "ja"),
    "简体中文": ("schinese", "zh-CN"), "繁體中文": ("tchinese", "zh-TW"), "Español": ("spanish", "es"),
    "Français": ("french", "fr"), "Deutsch": ("german", "de"),
}
SOURCE_CODES = {"자동 감지": "auto", **{k: v[1] for k, v in LANGS.items()}}
PROVIDERS = ["무료 Google 번역", "Ollama (무료/로컬)", "LM Studio / OpenAI 호환", "OpenAI 호환 API"]
STRING_RE = re.compile(r'(?P<quote>["\'])(?P<text>(?:\\.|(?!\1).)*?)(?P=quote)')
SKIP_PREFIXES = (
    "image ", "scene ", "show ", "hide ", "play ", "queue ", "stop ", "voice ", "jump ", "call ",
    "label ", "define ", "default ", "$", "python:", "init python:", "transform ", "style ", "screen "
)

def looks_translatable(line, text):
    s = line.strip()
    if not text.strip() or s.startswith("#") or any(s.lower().startswith(p) for p in SKIP_PREFIXES):
        return False
    if re.fullmatch(r"[\w./\\:@#%+\-=]+", text) and " " not in text:
        return False
    if re.search(r"\.(png|jpg|jpeg|webp|gif|ogg|mp3|wav|opus|rpy|rpyc)$", text, re.I):
        return False
    return True

def mask_tokens(text):
    tokens = []
    def repl(m):
        key = f"__RPTOKEN_{len(tokens)}__"
        tokens.append((key, m.group(0)))
        return key
    return re.sub(r'(\{[^{}]*\}|\[[^\[\]]*\])', repl, text), tokens

def unmask(text, tokens):
    for key, value in tokens:
        text = text.replace(key, value)
    return text

def escape_rpy(text):
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

class Translator:
    def __init__(self, provider, source, target, key="", url="", model=""):
        self.provider, self.source, self.target = provider, source, target
        self.key, self.url, self.model = key.strip(), url.strip(), model.strip()

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
            f"&sl={urllib.parse.quote(self.source)}&tl={urllib.parse.quote(self.target)}&dt=t&q={q}"
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
    game = root if root.name.lower() == "game" else root / "game"
    if not game.is_dir():
        raise RuntimeError("Ren'Py game 폴더를 찾지 못했습니다.")
    return game, [p for p in game.rglob("*.rpy") if "tl" not in p.relative_to(game).parts]

def extract_strings(path):
    out, seen = [], set()
    for no, line in enumerate(path.read_text("utf-8", errors="replace").splitlines(), 1):
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
        self.geometry("860x720")
        self.minsize(740, 620)
        setup_styles(self)

        self.source_path = tk.StringVar()
        self.source_lang = tk.StringVar(value="자동 감지")
        self.target_lang = tk.StringVar(value="한국어")
        self.provider = tk.StringVar(value="무료 Google 번역")
        self.google_workers = tk.IntVar(value=20)
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
        for w in self.container.winfo_children():
            w.destroy()

    def header(self, active):
        ttk.Label(self.container, text=f"AI Patcher  v{VERSION}", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self.container, text="Ren'Py AI 한글패치 제작 · 고속 병렬 번역 · 자동 이어하기", style="Subtitle.TLabel").pack(anchor="w", pady=(2, 16))
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
        buttons = ttk.Frame(self.container)
        buttons.pack(fill="x", pady=(18, 0))
        ttk.Button(buttons, text="다음  ›", style="Primary.TButton", command=self.next_options).pack(side="right")

    def pick(self):
        path = filedialog.askdirectory(title="번역할 Ren'Py 게임 폴더 선택")
        if not path:
            return
        self.source_path.set(path)
        try:
            _, files = collect_rpy(Path(path))
            count = sum(len(extract_strings(x)) for x in files)
            self.scan.set(f"게임 인식 완료  ·  RPY {len(files)}개  ·  번역 후보 {count}개")
        except Exception as exc:
            self.scan.set(str(exc))

    def next_options(self):
        try:
            collect_rpy(Path(self.source_path.get()))
        except Exception as exc:
            messagebox.showerror(APP, str(exc))
            return
        self.page = 2
        self.render()

    def combo_row(self, parent, label, var, values):
        ttk.Label(parent, text=label, style="Card.TLabel").pack(anchor="w", pady=(7, 3))
        ttk.Combobox(parent, textvariable=var, values=values, state="readonly").pack(fill="x")

    def entry_row(self, parent, label, var, show=None):
        ttk.Label(parent, text=label, style="Card.TLabel").pack(anchor="w", pady=(7, 3))
        ttk.Entry(parent, textvariable=var, show=show).pack(fill="x")

    def page_options(self):
        wrap = ttk.Frame(self.container)
        wrap.pack(fill="x")
        lo, left = card(wrap)
        lo.pack(side="left", fill="both", expand=True, padx=(0, 8))
        ro, right = card(wrap)
        ro.pack(side="left", fill="both", expand=True, padx=(8, 0))

        ttk.Label(left, text="번역 옵션", style="Section.TLabel").pack(anchor="w", pady=(0, 10))
        self.combo_row(left, "원본 언어", self.source_lang, list(SOURCE_CODES))
        self.combo_row(left, "번역 언어", self.target_lang, list(LANGS))
        self.combo_row(left, "번역 방식", self.provider, PROVIDERS)
        ttk.Label(left, text="Google 동시 번역 수", style="Card.TLabel").pack(anchor="w", pady=(9, 3))
        ttk.Spinbox(left, from_=1, to=64, textvariable=self.google_workers, width=8).pack(anchor="w")
        ttk.Label(left, text="무료 Google 번역 선택 시 적용 · 기본 20 · 권장 8~30", style="Muted.Card.TLabel").pack(anchor="w", pady=(4, 0))
        ttk.Label(left, text="진행 상황은 자동 저장되며 같은 ZIP 이름을 선택하면 이어서 진행합니다.", style="Muted.Card.TLabel").pack(anchor="w", pady=(8, 0))

        ttk.Label(right, text="고급 연결 설정", style="Section.TLabel").pack(anchor="w", pady=(0, 10))
        ttk.Label(right, text="무료 번역은 아래 항목을 비워도 됩니다.", style="Muted.Card.TLabel").pack(anchor="w", pady=(0, 10))
        self.entry_row(right, "API Key", self.api_key, show="•")
        self.entry_row(right, "Model", self.model)
        self.entry_row(right, "Base URL", self.base_url)

        buttons = ttk.Frame(self.container)
        buttons.pack(fill="x", pady=(18, 0))
        ttk.Button(buttons, text="‹  이전", style="Secondary.TButton", command=self.back).pack(side="left")
        ttk.Button(buttons, text="한글패치 만들기  ›", style="Primary.TButton", command=self.start).pack(side="right")

    def back(self):
        self.page = max(1, self.page - 1)
        self.render()

    def start(self):
        try:
            workers = max(1, min(64, int(self.google_workers.get())))
        except Exception:
            messagebox.showerror(APP, "Google 동시 번역 수는 1~64 사이 숫자로 입력하세요.")
            return
        out = filedialog.asksaveasfilename(
            title="패치 ZIP 저장",
            defaultextension=".zip",
            filetypes=[("ZIP 파일", "*.zip")],
            initialfile=f"RenPy_{LANGS[self.target_lang.get()][0]}_patch.zip",
        )
        if not out:
            return
        self.job_options = {
            "source_path": self.source_path.get(),
            "source_lang": self.source_lang.get(),
            "target_lang": self.target_lang.get(),
            "provider": self.provider.get(),
            "google_workers": workers,
            "api_key": self.api_key.get(),
            "base_url": self.base_url.get(),
            "model": self.model.get(),
        }
        self.output_zip = Path(out)
        self.page = 3
        self.render()
        threading.Thread(target=self.worker, daemon=True).start()

    def page_work(self):
        outer, body = card(self.container)
        outer.pack(fill="both", expand=True)
        ttk.Label(body, text="번역 및 패치 생성 중", style="Section.TLabel").pack(anchor="w")
        ttk.Label(body, textvariable=self.status, style="Muted.Card.TLabel").pack(anchor="w", pady=(3, 12))
        self.bar = ttk.Progressbar(body, mode="determinate")
        self.bar.pack(fill="x")
        self.percent = ttk.Label(body, text="0%", style="Muted.Card.TLabel")
        self.percent.pack(anchor="e", pady=(4, 8))
        self.details = ttk.Button(body, text="자세히 보기", style="Flat.TButton", command=self.toggle_log)
        self.details.pack(anchor="w")
        self.log = tk.Text(body, height=12, wrap="word", state="disabled", relief="flat", bg="#F8FAFD")
        self.log_visible = False

    def toggle_log(self):
        if self.log_visible:
            self.log.pack_forget()
            self.details.config(text="자세히 보기")
        else:
            self.log.pack(fill="both", expand=True, pady=(8, 0))
            self.details.config(text="자세히 숨기기")
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

    def progress(self, index, total, status):
        def update():
            if not hasattr(self, "bar"):
                return
            safe = max(total, 1)
            self.bar["maximum"] = safe
            self.bar["value"] = index
            self.percent.config(text=f"{int(index / safe * 100)}%")
            self.status.set(status)
        self.after(0, update)

    @staticmethod
    def translate_with_retry(translator, text):
        last = None
        for attempt in range(3):
            try:
                return translator.translate(text), None
            except Exception as exc:
                last = exc
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
        return text, last

    def checkpoint_path(self):
        return self.output_zip.with_suffix(self.output_zip.suffix + ".progress.json")

    def checkpoint_signature(self, options):
        return {
            "source_path": str(Path(options["source_path"]).resolve()),
            "source_lang": options["source_lang"],
            "target_lang": options["target_lang"],
            "provider": options["provider"],
            "base_url": options["base_url"],
            "model": options["model"],
        }

    def load_checkpoint(self, options):
        path = self.checkpoint_path()
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text("utf-8"))
            if data.get("signature") != self.checkpoint_signature(options):
                self.add_log("[이어하기] 기존 진행 파일의 게임/번역 설정이 달라 새로 시작합니다.")
                return {}
            translations = data.get("translations", {})
            if isinstance(translations, dict):
                self.add_log(f"[이어하기] 저장된 번역 {len(translations)}개를 불러왔습니다.")
                return translations
        except Exception as exc:
            self.add_log(f"[이어하기] 진행 파일을 읽지 못했습니다: {exc}")
        return {}

    def save_checkpoint(self, options, memory):
        path = self.checkpoint_path()
        tmp = path.with_suffix(path.suffix + ".tmp")
        data = {
            "version": 1,
            "signature": self.checkpoint_signature(options),
            "saved_at": time.time(),
            "translations": memory,
        }
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

    def worker(self):
        temp = self.output_zip.parent / (self.output_zip.stem + "_work")
        checkpoint = self.checkpoint_path()
        try:
            o = self.job_options
            game, files = collect_rpy(Path(o["source_path"]))
            items = []
            for f in files:
                for no, text in extract_strings(f):
                    items.append((f, no, text))
            if not items:
                raise RuntimeError("번역 가능한 .rpy 문자열을 찾지 못했습니다.")

            target_dir, target_code = LANGS[o["target_lang"]]
            translator = Translator(o["provider"], SOURCE_CODES[o["source_lang"]], target_code, o["api_key"], o["base_url"], o["model"])
            if temp.exists():
                shutil.rmtree(temp)
            patch_root = temp / "game" / "tl" / target_dir
            patch_root.mkdir(parents=True)

            unique = list(dict.fromkeys(text for _, _, text in items))
            workers = o["google_workers"] if o["provider"] == "무료 Google 번역" else 4
            memory = self.load_checkpoint(o)
            unique_set = set(unique)
            memory = {k: v for k, v in memory.items() if k in unique_set}
            pending = [text for text in unique if text not in memory]
            failed = 0
            completed = len(memory)
            total = len(unique)
            last_save = time.monotonic()

            self.add_log(f"[고속 번역] 전체 {len(items)}개 · 중복 제거 {total}개 · 동시 작업 {workers}개")
            if completed:
                self.progress(completed, total, f"이어하기 · {completed}/{total} 완료 · 남은 {len(pending)}개")

            if pending:
                with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="translate") as pool:
                    futures = {pool.submit(self.translate_with_retry, translator, text): text for text in pending}
                    since_save = 0
                    for future in as_completed(futures):
                        src = futures[future]
                        translated, error = future.result()
                        memory[src] = translated
                        completed += 1
                        since_save += 1
                        if error is not None:
                            failed += 1
                            self.add_log(f"[번역 실패] {src[:60]} · {error}")

                        now = time.monotonic()
                        if since_save >= 10 or now - last_save >= 2.0 or completed == total:
                            self.save_checkpoint(o, memory)
                            since_save = 0
                            last_save = now
                        self.progress(completed, total, f"고속 번역 중 · {completed}/{total} · {workers}개 동시 · 자동 저장")

            self.save_checkpoint(o, memory)

            grouped = {}
            for f, no, src in items:
                grouped.setdefault(f, []).append((no, src, memory.get(src, src)))

            for f, entries in grouped.items():
                rel = f.relative_to(game)
                dest = patch_root / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                lines = ["# Generated by RenPy AI Patcher", f"translate {target_dir} strings:", ""]
                for no, old, new in entries:
                    lines.extend([f"    # {rel.as_posix()}:{no}", f'    old "{escape_rpy(old)}"', f'    new "{escape_rpy(new)}"', ""])
                dest.write_text("\n".join(lines), encoding="utf-8")

            (temp / "패치_설명.txt").write_text(
                "이 ZIP의 game 폴더를 원본 게임 최상위 폴더에 합치세요.\n"
                f"번역 파일은 game/tl/{target_dir}/ 아래에 추가됩니다.\n"
                f"고속 병렬 번역: {workers}개 동시 처리 / 이번 실행 번역 실패: {failed}개\n"
                "진행 상황은 작업 중 자동 저장되며, 미완료 시 같은 ZIP 이름으로 다시 시작하면 이어집니다.\n"
                "원본 게임 전체를 재배포하지 말고, 배포 권리가 있는 패치만 공유하세요.\n",
                encoding="utf-8",
            )

            self.progress(1, 1, "패치 ZIP 생성 중...")
            with zipfile.ZipFile(self.output_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
                for path in temp.rglob("*"):
                    if path.is_file():
                        archive.write(path, path.relative_to(temp))

            try:
                checkpoint.unlink(missing_ok=True)
            except Exception:
                pass

            self.result = len(items)
            self.after(0, self.finish)
        except Exception as exc:
            try:
                if 'o' in locals() and 'memory' in locals():
                    self.save_checkpoint(o, memory)
            except Exception:
                pass
            msg = str(exc)
            self.after(0, lambda m=msg: messagebox.showerror(APP, f"작업 중 오류가 발생했습니다.\n\n{m}"))
            self.after(0, lambda: self.status.set("작업 실패 · 진행 상황은 저장됨"))
        finally:
            try:
                if temp.exists():
                    shutil.rmtree(temp)
            except Exception:
                pass

    def finish(self):
        self.page = 4
        self.render()

    def page_done(self):
        outer, body = card(self.container)
        outer.pack(fill="x")
        ttk.Label(body, text="✓  한글패치 생성 완료", style="Section.TLabel").pack(anchor="center")
        ttk.Label(body, text=f"처리한 번역 후보 {getattr(self, 'result', 0)}개", style="Muted.Card.TLabel").pack(anchor="center", pady=(5, 12))
        ttk.Label(body, text=str(self.output_zip), style="Muted.Card.TLabel").pack(anchor="center")
        buttons = ttk.Frame(self.container)
        buttons.pack(fill="x", pady=(18, 0))
        ttk.Button(buttons, text="처음으로", style="Secondary.TButton", command=self.restart).pack(side="left")
        ttk.Button(buttons, text="결과 위치 열기", style="Primary.TButton", command=self.open_output).pack(side="right")

    def restart(self):
        self.page = 1
        self.render()

    def open_output(self):
        try:
            os.startfile(str(self.output_zip.parent))
        except Exception:
            messagebox.showinfo(APP, f"결과 위치:\n{self.output_zip.parent}")

if __name__ == "__main__":
    PatcherApp().mainloop()
