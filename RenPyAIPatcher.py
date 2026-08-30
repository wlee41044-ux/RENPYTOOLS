#!/usr/bin/env python3
import json
import os
import random
import re
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ui_common import *

APP = "RenPy AI Patcher"
VERSION = "0.2.6"

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
    "label ", "$", "python:", "init python:", "transform "
)
SCRIPT_EXTS = {".rpy", ".rpym"}


def looks_translatable(line, text):
    s = line.strip()
    value = text.strip()
    if not value or s.startswith("#") or any(s.lower().startswith(p) for p in SKIP_PREFIXES):
        return False
    if re.search(r"\.(png|jpg|jpeg|webp|gif|ogg|mp3|wav|opus|rpy|rpyc|rpym|rpymc|ttf|otf)$", value, re.I):
        return False
    if re.fullmatch(r"[A-Za-z0-9_./\\:@#%+\-=]+", value) and " " not in value:
        return False
    return True


def mask_tokens(text):
    tokens = []
    def repl(match):
        key = f"__RPTOKEN_{len(tokens)}__"
        tokens.append((key, match.group(0)))
        return key
    return re.sub(r'(\{[^{}]*\}|\[[^\[\]]*\])', repl, text), tokens


def unmask(text, tokens):
    for key, value in tokens:
        text = text.replace(key, value)
    return text


def escape_rpy(text):
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def candidate_script_roots(root):
    root = Path(root)
    candidates = []
    for item in (root / "game", root, root / "Decompiled" / "game", root / "Decompiled"):
        if item.is_dir() and item not in candidates:
            candidates.append(item)
    try:
        for child in root.iterdir():
            if child.is_dir() and child.name.lower() == "game" and child not in candidates:
                candidates.append(child)
            nested = child / "game"
            if nested.is_dir() and nested not in candidates:
                candidates.append(nested)
    except Exception:
        pass
    return candidates


def collect_rpy(root):
    best_root = None
    best_files = []
    for candidate in candidate_script_roots(root):
        files = [
            p for p in candidate.rglob("*")
            if p.is_file()
            and p.suffix.lower() in SCRIPT_EXTS
            and "tl" not in [part.lower() for part in p.relative_to(candidate).parts]
        ]
        if len(files) > len(best_files):
            best_root, best_files = candidate, files
    if not best_root or not best_files:
        raise RuntimeError("번역 가능한 .rpy/.rpym 파일을 찾지 못했습니다. 게임 폴더 또는 Extractor 결과 폴더를 선택하세요.")
    return best_root, best_files


def extract_strings(path):
    out, seen = [], set()
    for no, line in enumerate(path.read_text("utf-8", errors="replace").splitlines(), 1):
        for match in STRING_RE.finditer(line):
            value = match.group("text")
            if looks_translatable(line, value) and value not in seen:
                seen.add(value)
                out.append((no, value))
    return out


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
        params = urllib.parse.urlencode({"client": "gtx", "sl": self.source, "tl": self.target, "dt": "t", "q": text})
        req = urllib.request.Request(
            "https://translate.googleapis.com/translate_a/single?" + params,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json,text/plain,*/*", "Connection": "close"},
        )
        with urllib.request.urlopen(req, timeout=15) as response:
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
        ttk.Label(self.container, text="Ren'Py AI 한글패치 제작 · 429 자동 속도조절 · 자동 이어하기", style="Subtitle.TLabel").pack(anchor="w", pady=(2, 16))
        stepper(self.container, active, ["게임 폴더 선택", "옵션 설정", "번역 및 패치", "완료"])

    def render(self):
        self.clear(); self.header(self.page)
        [self.page_folder, self.page_options, self.page_work, self.page_done][self.page - 1]()

    def page_folder(self):
        outer, body = card(self.container); outer.pack(fill="x")
        ttk.Label(body, text="📁  번역할 게임/Decompiled 폴더 선택", style="Section.TLabel").pack(anchor="w")
        ttk.Label(body, text="게임 최상위, game 폴더, Extractor 결과 폴더를 자동 판별합니다.", style="Muted.Card.TLabel").pack(anchor="w", pady=(3, 12))
        row = ttk.Frame(body, style="Card.TFrame"); row.pack(fill="x")
        ttk.Entry(row, textvariable=self.source_path).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="찾아보기", style="Secondary.TButton", command=self.pick).pack(side="left", padx=(8, 0))
        ttk.Label(body, textvariable=self.scan, style="Muted.Card.TLabel").pack(anchor="w", pady=(10, 0))
        buttons = ttk.Frame(self.container); buttons.pack(fill="x", pady=(18, 0))
        ttk.Button(buttons, text="다음  ›", style="Primary.TButton", command=self.next_options).pack(side="right")

    def pick(self):
        path = filedialog.askdirectory(title="번역할 Ren'Py 폴더 선택")
        if not path: return
        self.source_path.set(path)
        try:
            root, files = collect_rpy(Path(path))
            count = sum(len(extract_strings(x)) for x in files)
            self.scan.set(f"인식 완료 · {root.name} · RPY/RPYM {len(files)}개 · 번역 후보 {count}개")
        except Exception as exc:
            self.scan.set(str(exc))

    def next_options(self):
        try: collect_rpy(Path(self.source_path.get()))
        except Exception as exc:
            messagebox.showerror(APP, str(exc)); return
        self.page = 2; self.render()

    def combo_row(self, parent, label, var, values):
        ttk.Label(parent, text=label, style="Card.TLabel").pack(anchor="w", pady=(7, 3))
        ttk.Combobox(parent, textvariable=var, values=values, state="readonly").pack(fill="x")

    def entry_row(self, parent, label, var, show=None):
        ttk.Label(parent, text=label, style="Card.TLabel").pack(anchor="w", pady=(7, 3))
        ttk.Entry(parent, textvariable=var, show=show).pack(fill="x")

    def page_options(self):
        wrap = ttk.Frame(self.container); wrap.pack(fill="x")
        lo, left = card(wrap); lo.pack(side="left", fill="both", expand=True, padx=(0, 8))
        ro, right = card(wrap); ro.pack(side="left", fill="both", expand=True, padx=(8, 0))
        ttk.Label(left, text="번역 옵션", style="Section.TLabel").pack(anchor="w", pady=(0, 10))
        self.combo_row(left, "원본 언어", self.source_lang, list(SOURCE_CODES))
        self.combo_row(left, "번역 언어", self.target_lang, list(LANGS))
        self.combo_row(left, "번역 방식", self.provider, PROVIDERS)
        ttk.Label(left, text="Google 최대 동시 번역 수", style="Card.TLabel").pack(anchor="w", pady=(9, 3))
        ttk.Spinbox(left, from_=1, to=64, textvariable=self.google_workers, width=8).pack(anchor="w")
        ttk.Label(left, text="429가 발생하면 자동으로 낮추고 안정되면 다시 올립니다.", style="Muted.Card.TLabel").pack(anchor="w", pady=(4, 0))
        ttk.Label(left, text="성공한 번역은 자동 저장하고 실패 항목만 뒤에서 다시 시도합니다.", style="Muted.Card.TLabel").pack(anchor="w", pady=(8, 0))
        ttk.Label(right, text="고급 연결 설정", style="Section.TLabel").pack(anchor="w", pady=(0, 10))
        ttk.Label(right, text="무료 Google 번역은 아래 항목을 비워도 됩니다.", style="Muted.Card.TLabel").pack(anchor="w", pady=(0, 10))
        self.entry_row(right, "API Key", self.api_key, show="•"); self.entry_row(right, "Model", self.model); self.entry_row(right, "Base URL", self.base_url)
        buttons = ttk.Frame(self.container); buttons.pack(fill="x", pady=(18, 0))
        ttk.Button(buttons, text="‹  이전", style="Secondary.TButton", command=self.back).pack(side="left")
        ttk.Button(buttons, text="한글패치 만들기  ›", style="Primary.TButton", command=self.start).pack(side="right")

    def back(self): self.page = max(1, self.page - 1); self.render()

    def start(self):
        try: workers = max(1, min(64, int(self.google_workers.get())))
        except Exception:
            messagebox.showerror(APP, "Google 동시 번역 수는 1~64 사이 숫자로 입력하세요."); return
        out = filedialog.asksaveasfilename(title="패치 ZIP 저장", defaultextension=".zip", filetypes=[("ZIP 파일", "*.zip")], initialfile=f"RenPy_{LANGS[self.target_lang.get()][0]}_patch.zip")
        if not out: return
        self.job_options = {"source_path": self.source_path.get(), "source_lang": self.source_lang.get(), "target_lang": self.target_lang.get(), "provider": self.provider.get(), "google_workers": workers, "api_key": self.api_key.get(), "base_url": self.base_url.get(), "model": self.model.get()}
        self.output_zip = Path(out); self.page = 3; self.render()
        threading.Thread(target=self.worker, daemon=True).start()

    def page_work(self):
        outer, body = card(self.container); outer.pack(fill="both", expand=True)
        ttk.Label(body, text="번역 및 패치 생성 중", style="Section.TLabel").pack(anchor="w")
        ttk.Label(body, textvariable=self.status, style="Muted.Card.TLabel").pack(anchor="w", pady=(3, 12))
        self.bar = ttk.Progressbar(body, mode="determinate"); self.bar.pack(fill="x")
        self.percent = ttk.Label(body, text="0%", style="Muted.Card.TLabel"); self.percent.pack(anchor="e", pady=(4, 8))
        self.details = ttk.Button(body, text="자세히 보기", style="Flat.TButton", command=self.toggle_log); self.details.pack(anchor="w")
        self.log = tk.Text(body, height=12, wrap="word", state="disabled", relief="flat", bg="#F8FAFD"); self.log_visible = False

    def toggle_log(self):
        if self.log_visible: self.log.pack_forget(); self.details.config(text="자세히 보기")
        else: self.log.pack(fill="both", expand=True, pady=(8, 0)); self.details.config(text="자세히 숨기기")
        self.log_visible = not self.log_visible

    def add_log(self, text):
        def update():
            if not hasattr(self, "log"): return
            self.log.configure(state="normal"); self.log.insert("end", text + "\n"); self.log.see("end"); self.log.configure(state="disabled")
        self.after(0, update)

    def progress(self, index, total, status):
        def update():
            if not hasattr(self, "bar"): return
            safe = max(total, 1); self.bar["maximum"] = safe; self.bar["value"] = index
            self.percent.config(text=f"{int(index / safe * 100)}%"); self.status.set(status)
        self.after(0, update)

    @staticmethod
    def translate_once(translator, text):
        try: return translator.translate(text), None, False
        except urllib.error.HTTPError as exc: return None, exc, exc.code == 429
        except Exception as exc: return None, exc, False

    def checkpoint_path(self): return self.output_zip.with_suffix(self.output_zip.suffix + ".progress.json")

    def checkpoint_signature(self, options):
        return {"source_path": str(Path(options["source_path"]).resolve()), "source_lang": options["source_lang"], "target_lang": options["target_lang"], "provider": options["provider"], "base_url": options["base_url"], "model": options["model"]}

    def load_checkpoint(self, options):
        path = self.checkpoint_path()
        if not path.is_file(): return {}
        try:
            data = json.loads(path.read_text("utf-8"))
            if data.get("signature") != self.checkpoint_signature(options): return {}
            translations = data.get("translations", {})
            if isinstance(translations, dict):
                self.add_log(f"[이어하기] 저장된 번역 {len(translations)}개를 불러왔습니다."); return translations
        except Exception as exc: self.add_log(f"[이어하기] 진행 파일 읽기 실패: {exc}")
        return {}

    def save_checkpoint(self, options, memory):
        path = self.checkpoint_path(); tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps({"version": 3, "signature": self.checkpoint_signature(options), "saved_at": time.time(), "translations": memory}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

    def adaptive_translate(self, translator, pending, max_workers, memory, options, total, already_done):
        queue = list(pending); attempts = {text: 0 for text in queue}; current = max_workers
        min_workers = 1; success_streak = 0; started = time.monotonic(); processed = 0
        while queue:
            wave_size = min(len(queue), max(current * 2, current))
            wave, queue = queue[:wave_size], queue[wave_size:]
            results = []
            with ThreadPoolExecutor(max_workers=current, thread_name_prefix="translate") as pool:
                futures = {pool.submit(self.translate_once, translator, text): text for text in wave}
                for future in as_completed(futures):
                    text = futures[future]
                    translated, error, rate_limited = future.result()
                    results.append((text, translated, error, rate_limited))
            rate_hits = 0; wave_success = 0
            for text, translated, error, rate_limited in results:
                attempts[text] += 1; processed += 1
                if translated is not None and error is None:
                    memory[text] = translated; wave_success += 1; success_streak += 1
                else:
                    if rate_limited: rate_hits += 1
                    success_streak = 0
                    if attempts[text] < 7:
                        queue.append(text)
                    else:
                        self.add_log(f"[최종 실패] {text[:60]} · {error}")
                if processed % 10 == 0:
                    self.save_checkpoint(options, memory)
                elapsed = max(time.monotonic() - started, 0.001)
                speed = wave_success / max(elapsed, 0.001)
                done_now = already_done + len(memory)
                self.progress(min(done_now, total), total, f"번역 중 · 성공 {len(memory)}/{total} · 현재 {current}/{max_workers}개 동시 · 429 자동조절")
            if rate_hits:
                new_current = max(min_workers, current // 2)
                if new_current < current:
                    self.add_log(f"[429 감지] {rate_hits}개 제한 · 병렬 {current} → {new_current}")
                    current = new_current
                wait_sec = min(8.0, 1.5 + rate_hits * 0.15) + random.uniform(0.1, 0.6)
                time.sleep(wait_sec)
            elif wave_success == len(results) and success_streak >= max(8, current * 2) and current < max_workers:
                current = min(max_workers, current + max(1, current // 4))
                success_streak = 0
                self.add_log(f"[안정 회복] 병렬 수를 {current}개로 올립니다.")
            elif not wave_success:
                time.sleep(1.0)
        self.save_checkpoint(options, memory)

    def worker(self):
        temp = self.output_zip.parent / (self.output_zip.stem + "_work"); checkpoint = self.checkpoint_path()
        try:
            o = self.job_options; game, files = collect_rpy(Path(o["source_path"]))
            items = [(f, no, text) for f in files for no, text in extract_strings(f)]
            if not items: raise RuntimeError("번역 가능한 문자열을 찾지 못했습니다.")
            target_dir, target_code = LANGS[o["target_lang"]]
            translator = Translator(o["provider"], SOURCE_CODES[o["source_lang"]], target_code, o["api_key"], o["base_url"], o["model"])
            if temp.exists(): shutil.rmtree(temp)
            patch_root = temp / "game" / "tl" / target_dir; patch_root.mkdir(parents=True)
            unique = list(dict.fromkeys(text for _, _, text in items)); total = len(unique)
            max_workers = o["google_workers"] if o["provider"] == "무료 Google 번역" else 4
            memory = self.load_checkpoint(o); unique_set = set(unique); memory = {k: v for k, v in memory.items() if k in unique_set}
            pending = [text for text in unique if text not in memory]
            self.add_log(f"[번역 시작] 전체 {len(items)}개 · 중복 제거 {total}개 · 최대 동시 {max_workers}개")
            self.progress(len(memory), total, f"번역 시작 · 저장 {len(memory)}/{total}")
            self.adaptive_translate(translator, pending, max_workers, memory, o, total, 0)
            final_failed = [src for src in unique if src not in memory]
            grouped = {}
            for f, no, src in items: grouped.setdefault(f, []).append((no, src, memory.get(src, src)))
            for f, entries in grouped.items():
                rel = f.relative_to(game); dest = patch_root / rel; dest.parent.mkdir(parents=True, exist_ok=True)
                lines = ["# Generated by RenPy AI Patcher", f"translate {target_dir} strings:", ""]
                for no, old, new in entries: lines.extend([f"    # {rel.as_posix()}:{no}", f'    old "{escape_rpy(old)}"', f'    new "{escape_rpy(new)}"', ""])
                dest.write_text("\n".join(lines), encoding="utf-8")
            (temp / "패치_설명.txt").write_text(f"번역 파일: game/tl/{target_dir}/\n최종 미번역: {len(final_failed)}개\n429 발생 시 병렬 수를 자동 조절합니다.\n", encoding="utf-8")
            self.progress(1, 1, "패치 ZIP 생성 중...")
            with zipfile.ZipFile(self.output_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
                for path in temp.rglob("*"):
                    if path.is_file(): archive.write(path, path.relative_to(temp))
            checkpoint.unlink(missing_ok=True); self.result = len(items); self.after(0, self.finish)
        except Exception as exc:
            try:
                if 'o' in locals() and 'memory' in locals(): self.save_checkpoint(o, memory)
            except Exception: pass
            msg = str(exc); self.after(0, lambda m=msg: messagebox.showerror(APP, f"작업 중 오류가 발생했습니다.\n\n{m}")); self.after(0, lambda: self.status.set("작업 실패 · 진행 상황은 저장됨"))
        finally:
            try:
                if temp.exists(): shutil.rmtree(temp)
            except Exception: pass

    def finish(self): self.page = 4; self.render()

    def page_done(self):
        outer, body = card(self.container); outer.pack(fill="x")
        ttk.Label(body, text="✓  한글패치 생성 완료", style="Section.TLabel").pack(anchor="center")
        ttk.Label(body, text=f"처리한 번역 후보 {getattr(self, 'result', 0)}개", style="Muted.Card.TLabel").pack(anchor="center", pady=(5, 12))
        ttk.Label(body, text=str(self.output_zip), style="Muted.Card.TLabel").pack(anchor="center")
        buttons = ttk.Frame(self.container); buttons.pack(fill="x", pady=(18, 0))
        ttk.Button(buttons, text="처음으로", style="Secondary.TButton", command=self.restart).pack(side="left")
        ttk.Button(buttons, text="결과 위치 열기", style="Primary.TButton", command=self.open_output).pack(side="right")

    def restart(self): self.page = 1; self.render()

    def open_output(self):
        try: os.startfile(str(self.output_zip.parent))
        except Exception: messagebox.showinfo(APP, f"결과 위치:\n{self.output_zip.parent}")


if __name__ == "__main__":
    PatcherApp().mainloop()
