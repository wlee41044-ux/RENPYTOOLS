#!/usr/bin/env python3
import hashlib
import json
import os
import random
import re
import shutil
import sys
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
VERSION = "0.3.3"
LANGS = {
    "한국어": ("korean", "ko"), "English": ("english", "en"), "日本語": ("japanese", "ja"),
    "简体中文": ("schinese", "zh-CN"), "繁體中文": ("tchinese", "zh-TW"), "Español": ("spanish", "es"),
    "Français": ("french", "fr"), "Deutsch": ("german", "de"),
}
SOURCE_CODES = {"자동 감지": "auto", **{k: v[1] for k, v in LANGS.items()}}
PROVIDERS = [
    "무료 자동 선택 (추천)",
    "무료 Google 번역",
    "Lingva Translate (무료/키 없음)",
    "MyMemory (무료/키 없음)",
    "Ollama (무료/로컬 자동모델)",
    "LM Studio (무료/로컬 자동모델)",
]
STRING_RE = re.compile(r'(?P<quote>["\'])(?P<text>(?:\\.|(?!\1).)*?)(?P=quote)')
SKIP_PREFIXES = (
    "image ", "scene ", "show ", "hide ", "play ", "queue ", "stop ", "voice ", "jump ", "call ",
    "label ", "$", "python:", "init python:", "transform "
)
SCRIPT_EXTS = {".rpy", ".rpym"}
BATCH_SIZE = 12
BATCH_CHAR_LIMIT = 1800
HISTORY_PAGE_SIZE = 200


def looks_translatable(line, text):
    s, value = line.strip(), text.strip()
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
            if not child.is_dir():
                continue
            if child.name.lower() == "game" and child not in candidates:
                candidates.append(child)
            nested = child / "game"
            if nested.is_dir() and nested not in candidates:
                candidates.append(nested)
    except Exception:
        pass
    return candidates


def collect_rpy(root):
    best_root, best_files = None, []
    for candidate in candidate_script_roots(root):
        files = [
            p for p in candidate.rglob("*")
            if p.is_file() and p.suffix.lower() in SCRIPT_EXTS
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


def make_batches(texts, max_items=BATCH_SIZE, max_chars=BATCH_CHAR_LIMIT):
    batches, current, chars = [], [], 0
    for text in texts:
        cost = len(text) + 32
        if current and (len(current) >= max_items or chars + cost > max_chars):
            batches.append(current)
            current, chars = [], 0
        current.append(text)
        chars += cost
    if current:
        batches.append(current)
    return batches


class Translator:
    LINGVA_INSTANCES = [
        "https://lingva.ml",
        "https://translate.plausibility.cloud",
        "https://translate.projectsegfau.lt",
    ]

    def __init__(self, provider, source, target):
        self.provider, self.source, self.target = provider, source, target
        self.google_blocked_until = 0.0
        self._state_lock = threading.Lock()

    def _request_json(self, url, data=None, headers=None, timeout=30):
        req = urllib.request.Request(url, data=data, headers=headers or {"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def google_raw(self, text):
        params = urllib.parse.urlencode({"client": "gtx", "sl": self.source, "tl": self.target, "dt": "t", "q": text})
        req = urllib.request.Request(
            "https://translate.googleapis.com/translate_a/single?" + params,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json,text/plain,*/*", "Connection": "close"},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                with self._state_lock:
                    self.google_blocked_until = max(self.google_blocked_until, time.time() + 90.0)
            raise
        return "".join(x[0] for x in data[0] if x and x[0])

    def lingva_raw(self, text):
        last = None
        encoded = urllib.parse.quote(text, safe="")
        for base in self.LINGVA_INSTANCES:
            try:
                url = f"{base}/api/v1/{self.source}/{self.target}/{encoded}"
                data = self._request_json(url, timeout=8)
                out = data.get("translation", "") if isinstance(data, dict) else ""
                if out:
                    return out
            except Exception as exc:
                last = exc
        raise RuntimeError(f"Lingva 공개 서버에 연결하지 못했습니다: {last}")

    def mymemory_raw(self, text):
        if self.source == "auto":
            raise RuntimeError("MyMemory는 원본 언어 자동 감지를 지원하지 않습니다. 원본 언어를 직접 선택하세요.")
        params = urllib.parse.urlencode({"q": text, "langpair": f"{self.source}|{self.target}", "mt": "1"})
        data = self._request_json("https://api.mymemory.translated.net/get?" + params, timeout=25)
        response = data.get("responseData", {}) if isinstance(data, dict) else {}
        out = response.get("translatedText", "") if isinstance(response, dict) else ""
        if not out:
            raise RuntimeError("MyMemory가 번역 결과를 반환하지 않았습니다.")
        return out

    def _local_prompt(self, text):
        return (
            "Translate this visual novel text to " + self.target + ". "
            "Return only the translated text. Preserve every __RPTOKEN_n__ placeholder exactly.\n" + text
        )

    def ollama_raw(self, text):
        tags = self._request_json("http://127.0.0.1:11434/api/tags", timeout=8)
        models = tags.get("models", []) if isinstance(tags, dict) else []
        names = [m.get("name", "") for m in models if isinstance(m, dict) and m.get("name")]
        if not names:
            raise RuntimeError("Ollama에서 설치된 로컬 모델을 찾지 못했습니다.")
        preferred = next((n for n in names if "qwen" in n.lower()), names[0])
        payload = json.dumps({
            "model": preferred,
            "messages": [{"role": "user", "content": self._local_prompt(text)}],
            "stream": False,
        }).encode("utf-8")
        data = self._request_json(
            "http://127.0.0.1:11434/api/chat", data=payload,
            headers={"Content-Type": "application/json"}, timeout=120,
        )
        message = data.get("message", {}) if isinstance(data, dict) else {}
        out = message.get("content", "") if isinstance(message, dict) else ""
        if not out:
            raise RuntimeError("Ollama가 번역 결과를 반환하지 않았습니다.")
        return out

    def lmstudio_raw(self, text):
        models = self._request_json("http://127.0.0.1:1234/v1/models", timeout=8)
        rows = models.get("data", []) if isinstance(models, dict) else []
        model = next((x.get("id") for x in rows if isinstance(x, dict) and x.get("id")), None)
        if not model:
            raise RuntimeError("LM Studio에서 로드된 로컬 모델을 찾지 못했습니다.")
        payload = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": self._local_prompt(text)}],
            "temperature": 0.2,
        }).encode("utf-8")
        data = self._request_json(
            "http://127.0.0.1:1234/v1/chat/completions", data=payload,
            headers={"Content-Type": "application/json"}, timeout=120,
        )
        choices = data.get("choices", []) if isinstance(data, dict) else []
        if not choices:
            raise RuntimeError("LM Studio가 번역 결과를 반환하지 않았습니다.")
        return choices[0].get("message", {}).get("content", "")

    def auto_raw(self, text):
        errors = []
        with self._state_lock:
            google_ready = time.time() >= self.google_blocked_until
        if google_ready:
            try:
                return self.google_raw(text)
            except Exception as exc:
                errors.append("Google: " + str(exc))
        else:
            errors.append("Google: 429 대기 중")
        try:
            return self.lingva_raw(text)
        except Exception as exc:
            errors.append("Lingva: " + str(exc))
        if self.source != "auto":
            try:
                return self.mymemory_raw(text)
            except Exception as exc:
                errors.append("MyMemory: " + str(exc))
        raise RuntimeError("무료 자동 번역 실패 · " + " / ".join(errors))

    def translate_one(self, text):
        masked, tokens = mask_tokens(text)
        if self.provider == "무료 자동 선택 (추천)":
            out = self.auto_raw(masked)
        elif self.provider == "무료 Google 번역":
            out = self.google_raw(masked)
        elif self.provider == "Lingva Translate (무료/키 없음)":
            out = self.lingva_raw(masked)
        elif self.provider == "MyMemory (무료/키 없음)":
            out = self.mymemory_raw(masked)
        elif self.provider == "Ollama (무료/로컬 자동모델)":
            out = self.ollama_raw(masked)
        elif self.provider == "LM Studio (무료/로컬 자동모델)":
            out = self.lmstudio_raw(masked)
        else:
            raise RuntimeError("지원하지 않는 무료 번역 엔진입니다.")
        return unmask(out.strip(), tokens)

    def translate_google_batch(self, texts):
        masked_rows, token_rows, markers = [], [], []
        for i, text in enumerate(texts):
            masked, tokens = mask_tokens(text)
            marker = f"ZXQRPSEP{i:04d}ZXQ"
            markers.append(marker)
            masked_rows.append(marker + "\n" + masked)
            token_rows.append(tokens)
        translated = self.google_raw("\n".join(masked_rows))
        positions = []
        for marker in markers:
            pos = translated.find(marker)
            if pos < 0:
                raise RuntimeError("배치 구분자가 번역 중 변경되었습니다.")
            positions.append(pos)
        out = []
        for i, marker in enumerate(markers):
            start = positions[i] + len(marker)
            end = positions[i + 1] if i + 1 < len(markers) else len(translated)
            out.append(unmask(translated[start:end].strip(" \r\n"), token_rows[i]).strip())
        return out


class PatcherApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP} {VERSION}")
        self.geometry("900x760")
        self.minsize(760, 640)
        setup_styles(self)
        self.source_path = tk.StringVar()
        self.source_lang = tk.StringVar(value="자동 감지")
        self.target_lang = tk.StringVar(value="한국어")
        self.provider = tk.StringVar(value="무료 자동 선택 (추천)")
        self.google_workers = tk.IntVar(value=2)
        self.auto_apply = tk.BooleanVar(value=True)
        self.scan = tk.StringVar(value="아직 게임을 선택하지 않았습니다.")
        self.status = tk.StringVar(value="")
        self.page = 1
        self.output_zip = None
        self.job_options = None
        self.current_history = None
        self.history_lock = threading.Lock()
        self.applied_path = None
        self.backup_path = None
        self.standalone_path = None
        self.container = ttk.Frame(self, padding=24)
        self.container.pack(fill="both", expand=True)
        self.render()

    def clear(self):
        for w in self.container.winfo_children():
            w.destroy()

    def header(self, active):
        ttk.Label(self.container, text=f"AI Patcher  v{VERSION}", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self.container, text="Ren'Py AI 한글패치 제작 · 무료 번역 엔진 · 언어 자동 활성화 · 자동 패치", style="Subtitle.TLabel").pack(anchor="w", pady=(2, 16))
        stepper(self.container, active, ["게임 폴더 선택", "옵션 설정", "번역 및 패치", "완료"])

    def render(self):
        self.clear()
        self.header(self.page)
        [self.page_folder, self.page_options, self.page_work, self.page_done][self.page - 1]()

    def page_folder(self):
        outer, body = card(self.container)
        outer.pack(fill="x")
        ttk.Label(body, text="📁  번역할 게임/Decompiled 폴더 선택", style="Section.TLabel").pack(anchor="w")
        ttk.Label(body, text="게임 최상위, game 폴더, Extractor 결과 폴더를 자동 판별합니다.", style="Muted.Card.TLabel").pack(anchor="w", pady=(3, 12))
        row = ttk.Frame(body, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self.source_path).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="찾아보기", style="Secondary.TButton", command=self.pick).pack(side="left", padx=(8, 0))
        ttk.Label(body, textvariable=self.scan, style="Muted.Card.TLabel").pack(anchor="w", pady=(10, 0))
        buttons = ttk.Frame(self.container)
        buttons.pack(fill="x", pady=(18, 0))
        ttk.Button(buttons, text="번역 기록 보기", style="Secondary.TButton", command=self.open_history_browser).pack(side="left")
        ttk.Button(buttons, text="다음  ›", style="Primary.TButton", command=self.next_options).pack(side="right")

    def pick(self):
        path = filedialog.askdirectory(title="번역할 Ren'Py 폴더 선택")
        if not path:
            return
        self.source_path.set(path)
        try:
            root, files = collect_rpy(Path(path))
            count = sum(len(extract_strings(x)) for x in files)
            self.scan.set(f"인식 완료 · {root.name} · RPY/RPYM {len(files)}개 · 번역 후보 {count}개")
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
        ttk.Label(left, text="Google 동시 요청 수", style="Card.TLabel").pack(anchor="w", pady=(9, 3))
        ttk.Spinbox(left, from_=1, to=8, textvariable=self.google_workers, width=8).pack(anchor="w")
        ttk.Label(left, text="기본 2 · 요청당 최대 12문장 · 1~3 권장", style="Muted.Card.TLabel").pack(anchor="w", pady=(4, 0))
        ttk.Label(left, text="번역 성공/실패/대기 목록은 앱을 껐다 켜도 기록됩니다.", style="Muted.Card.TLabel").pack(anchor="w", pady=(8, 0))
        ttk.Checkbutton(left, variable=self.auto_apply, text="번역 완료 후 원본 게임에 자동 패치 적용").pack(anchor="w", pady=(12, 0))
        ttk.Label(left, text="미번역 문장이 남으면 자동 적용하지 않습니다. 기존 같은 언어 패치는 백업 후 갱신합니다.", style="Muted.Card.TLabel").pack(anchor="w", padx=(24, 0), pady=(3, 0))
        ttk.Label(right, text="무료 엔진 안내", style="Section.TLabel").pack(anchor="w", pady=(0, 10))
        ttk.Label(right, text="API Key가 필요한 번역 방식은 v0.3.1에서 제거했습니다.", style="Muted.Card.TLabel").pack(anchor="w", pady=(0, 8))
        ttk.Label(right, text="무료 자동 선택: Google 배치 번역을 우선 사용하고 제한 시 속도를 자동 조절", style="Card.TLabel").pack(anchor="w", pady=(3, 0))
        ttk.Label(right, text="MyMemory: 키 없이 사용 가능하지만 원본 언어 지정 필요 · 사용량 제한 있음", style="Muted.Card.TLabel").pack(anchor="w", pady=(3, 0))
        ttk.Label(right, text="Ollama / LM Studio: PC에 설치·로드된 로컬 모델을 자동 선택", style="Muted.Card.TLabel").pack(anchor="w", pady=(3, 0))
        ttk.Label(right, text="무료 서버는 외부 서비스 제한에 따라 일시적으로 느리거나 막힐 수 있습니다.", style="Muted.Card.TLabel").pack(anchor="w", pady=(12, 0))
        buttons = ttk.Frame(self.container)
        buttons.pack(fill="x", pady=(18, 0))
        ttk.Button(buttons, text="‹  이전", style="Secondary.TButton", command=self.back).pack(side="left")
        ttk.Button(buttons, text="기록 보기", style="Secondary.TButton", command=self.open_history_browser).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="한글패치 만들기  ›", style="Primary.TButton", command=self.start).pack(side="right")

    def back(self):
        self.page = max(1, self.page - 1)
        self.render()

    @staticmethod
    def resolve_game_for_apply(root, reject_decompiled=True):
        root = Path(root)
        if reject_decompiled and any(part.lower() == "decompiled" or part.lower().endswith("_decompiled") for part in root.parts):
            return None
        if root.name.lower() == "game" and root.is_dir():
            return root
        if (root / "game").is_dir():
            return root / "game"
        return None

    def start(self):
        try:
            workers = max(1, min(8, int(self.google_workers.get())))
        except Exception:
            messagebox.showerror(APP, "Google 동시 요청 수는 1~8 사이 숫자로 입력하세요.")
            return

        apply_game_path = ""
        if self.auto_apply.get():
            apply_game = self.resolve_game_for_apply(self.source_path.get(), reject_decompiled=True)
            if apply_game is None:
                chosen = filedialog.askdirectory(title="자동 패치를 적용할 원본 Ren'Py 게임 폴더 선택")
                if not chosen:
                    messagebox.showinfo(APP, "자동 적용을 사용하려면 원본 게임 폴더를 선택해야 합니다.")
                    return
                apply_game = self.resolve_game_for_apply(chosen, reject_decompiled=False)
                if apply_game is None:
                    messagebox.showerror(APP, "선택한 폴더에서 game 폴더를 찾지 못했습니다.")
                    return
            apply_game_path = str(apply_game)
        out = filedialog.asksaveasfilename(
            title="패치 ZIP 저장", defaultextension=".zip",
            filetypes=[("ZIP 파일", "*.zip")],
            initialfile=f"RenPy_{LANGS[self.target_lang.get()][0]}_patch.zip",
        )
        if not out:
            return
        self.job_options = {
            "source_path": self.source_path.get(), "source_lang": self.source_lang.get(),
            "target_lang": self.target_lang.get(), "provider": self.provider.get(),
            "google_workers": workers, "base_url": "", "model": "",
            "auto_apply": self.auto_apply.get(), "apply_game_path": apply_game_path,
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
        actions = ttk.Frame(body, style="Card.TFrame")
        actions.pack(fill="x")
        self.details = ttk.Button(actions, text="자세히 보기", style="Flat.TButton", command=self.toggle_log)
        self.details.pack(side="left")
        ttk.Button(actions, text="번역 목록 보기", style="Secondary.TButton", command=self.open_history_browser).pack(side="left", padx=(8, 0))
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

    def signature(self, options):
        return {
            "source_path": str(Path(options["source_path"]).resolve()),
            "source_lang": options["source_lang"], "target_lang": options["target_lang"],
            "provider": options["provider"], "base_url": options["base_url"], "model": options["model"],
        }

    def history_root(self):
        base = Path(os.getenv("APPDATA") or Path.home())
        path = base / "RenPyTools" / "history"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def history_path(self, options):
        raw = json.dumps(self.signature(options), ensure_ascii=False, sort_keys=True).encode("utf-8")
        return self.history_root() / (hashlib.sha256(raw).hexdigest()[:20] + ".json")

    def checkpoint_path(self):
        return self.output_zip.with_suffix(self.output_zip.suffix + ".progress.json")

    def load_json(self, path):
        try:
            return json.loads(path.read_text("utf-8")) if path.is_file() else {}
        except Exception:
            return {}

    def load_saved_memory(self, options):
        memory, failures = {}, {}
        hp = self.history_path(options)
        history = self.load_json(hp)
        if history.get("signature") == self.signature(options):
            memory.update(history.get("translations", {}) if isinstance(history.get("translations"), dict) else {})
            failures.update(history.get("failures", {}) if isinstance(history.get("failures"), dict) else {})
            if memory:
                self.add_log(f"[기록 복원] 이전 성공 번역 {len(memory)}개를 불러왔습니다.")
        cp = self.checkpoint_path()
        checkpoint = self.load_json(cp)
        if checkpoint.get("signature") == self.signature(options):
            translations = checkpoint.get("translations", {})
            if isinstance(translations, dict):
                memory.update(translations)
        return memory, failures

    def save_state(self, options, sources, memory, failures, total, completed=False):
        now = time.time()
        data = {
            "version": 5, "signature": self.signature(options), "saved_at": now,
            "total": total, "sources": sources, "translations": memory,
            "failures": failures, "completed": completed,
        }
        hp = self.history_path(options)
        tmp = hp.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, hp)
        if self.output_zip:
            cp = self.checkpoint_path()
            ctmp = cp.with_suffix(cp.suffix + ".tmp")
            ctmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(ctmp, cp)
        with self.history_lock:
            self.current_history = data

    def list_history_files(self):
        rows = []
        for path in self.history_root().glob("*.json"):
            data = self.load_json(path)
            sig = data.get("signature", {})
            if not sig:
                continue
            rows.append((path, data))
        rows.sort(key=lambda item: item[1].get("saved_at", 0), reverse=True)
        return rows

    def open_history_browser(self):
        win = tk.Toplevel(self)
        win.title("번역 기록")
        win.geometry("900x620")
        top = ttk.Frame(win, padding=12)
        top.pack(fill="x")
        ttk.Label(top, text="번역 기록 / 진행 상황", style="Section.TLabel").pack(side="left")
        summary = ttk.Label(top, text="")
        summary.pack(side="right")

        select_row = ttk.Frame(win, padding=(12, 0, 12, 8))
        select_row.pack(fill="x")
        histories = self.list_history_files()
        labels = []
        mapping = {}
        for path, data in histories:
            sig = data.get("signature", {})
            label = f"{Path(sig.get('source_path','')).name} · {sig.get('target_lang','')} · {int(data.get('total',0))}문장"
            if label in mapping:
                label += f" · {path.stem[:6]}"
            labels.append(label)
            mapping[label] = data
        selected = tk.StringVar(value=labels[0] if labels else "")
        combo = ttk.Combobox(select_row, textvariable=selected, values=labels, state="readonly")
        combo.pack(side="left", fill="x", expand=True)

        search_var = tk.StringVar()
        ttk.Entry(select_row, textvariable=search_var, width=28).pack(side="left", padx=(8, 0))

        table_frame = ttk.Frame(win, padding=(12, 0, 12, 0))
        table_frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(table_frame, columns=("status", "src", "dst"), show="headings")
        tree.heading("status", text="상태")
        tree.heading("src", text="원문")
        tree.heading("dst", text="번역문")
        tree.column("status", width=70, stretch=False)
        tree.column("src", width=360)
        tree.column("dst", width=360)
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        nav = ttk.Frame(win, padding=12)
        nav.pack(fill="x")
        page_var = tk.IntVar(value=0)
        page_label = ttk.Label(nav, text="")
        page_label.pack(side="left", padx=10)

        def current_data():
            with self.history_lock:
                live = self.current_history
                if live and selected.get() and mapping.get(selected.get(), {}).get("signature") == live.get("signature"):
                    return dict(live)
            return mapping.get(selected.get(), {})

        def refresh(reset=False):
            if reset:
                page_var.set(0)
            data = current_data()
            sources = list(data.get("sources", []))
            translations = data.get("translations", {})
            failures = data.get("failures", {})
            q = search_var.get().strip().lower()
            if q:
                sources = [s for s in sources if q in s.lower() or q in str(translations.get(s, "")).lower()]
            total_rows = len(sources)
            max_page = max(0, (total_rows - 1) // HISTORY_PAGE_SIZE)
            page_var.set(min(max(page_var.get(), 0), max_page))
            start = page_var.get() * HISTORY_PAGE_SIZE
            rows = sources[start:start + HISTORY_PAGE_SIZE]
            for item in tree.get_children():
                tree.delete(item)
            for src in rows:
                if src in translations:
                    state, dst = "성공", translations[src]
                elif src in failures:
                    state, dst = "실패", failures[src]
                else:
                    state, dst = "대기", ""
                tree.insert("", "end", values=(state, src, dst))
            success = len(translations)
            failed = len(failures)
            total = int(data.get("total", len(data.get("sources", []))))
            summary.config(text=f"성공 {success} · 실패 {failed} · 대기 {max(total-success-failed,0)} / 전체 {total}")
            page_label.config(text=f"{page_var.get()+1} / {max_page+1}")

        def prev_page():
            page_var.set(max(0, page_var.get() - 1))
            refresh()

        def next_page():
            page_var.set(page_var.get() + 1)
            refresh()

        ttk.Button(nav, text="‹ 이전", command=prev_page).pack(side="left")
        ttk.Button(nav, text="다음 ›", command=next_page).pack(side="left")
        ttk.Button(nav, text="새로고침", command=refresh).pack(side="right")
        combo.bind("<<ComboboxSelected>>", lambda e: refresh(True))
        search_var.trace_add("write", lambda *_: refresh(True))
        refresh(True)

        def auto_refresh():
            if win.winfo_exists():
                refresh()
                win.after(2000, auto_refresh)
        win.after(2000, auto_refresh)

    def translate_google_batches(self, translator, pending, max_workers, memory, failures, options, sources, total):
        queue = make_batches(pending)
        current = min(max_workers, 2)
        attempts = {}
        rate_rounds = 0
        started = time.monotonic()
        self.add_log(f"[배치 번역] {len(pending)}문장 → {len(queue)}개 요청 묶음 · 묶음당 최대 {BATCH_SIZE}문장")
        while queue:
            wave = queue[:max(current, 1)]
            queue = queue[len(wave):]
            with ThreadPoolExecutor(max_workers=current, thread_name_prefix="google-batch") as pool:
                futures = {pool.submit(translator.translate_google_batch, batch): batch for batch in wave}
                rate_hits = 0
                for future in as_completed(futures):
                    batch = futures[future]
                    key = tuple(batch)
                    attempts[key] = attempts.get(key, 0) + 1
                    try:
                        translated = future.result()
                        if len(translated) != len(batch):
                            raise RuntimeError("배치 결과 개수 불일치")
                        for src, dst in zip(batch, translated):
                            if dst:
                                memory[src] = dst
                                failures.pop(src, None)
                        self.save_state(options, sources, memory, failures, total)
                    except urllib.error.HTTPError as exc:
                        if exc.code == 429:
                            rate_hits += 1
                        if attempts[key] < 4:
                            if len(batch) > 1 and attempts[key] >= 2:
                                mid = max(1, len(batch) // 2)
                                queue.extend([batch[:mid], batch[mid:]])
                                self.add_log(f"[배치 축소] {len(batch)}문장 → {len(batch[:mid])}+{len(batch[mid:])}")
                            else:
                                queue.append(batch)
                        else:
                            for src in batch:
                                failures[src] = f"HTTP {exc.code}"
                            self.save_state(options, sources, memory, failures, total)
                    except Exception as exc:
                        if len(batch) > 1:
                            mid = max(1, len(batch) // 2)
                            queue.extend([batch[:mid], batch[mid:]])
                            self.add_log(f"[구분 실패/축소] {len(batch)}문장 묶음 → 더 작은 묶음")
                        elif attempts[key] < 4:
                            queue.append(batch)
                        else:
                            failures[batch[0]] = str(exc)
                            self.save_state(options, sources, memory, failures, total)
                    elapsed = max(time.monotonic() - started, 0.001)
                    done = len(memory)
                    self.progress(done, total, f"배치 번역 · 성공 {done}/{total} · 요청 {current}개 동시 · {done/elapsed:.1f}문장/초")
            if rate_hits:
                rate_rounds += 1
                new_current = max(1, current - 1)
                if new_current != current:
                    self.add_log(f"[429 감지] 동시 요청 {current} → {new_current}")
                    current = new_current
                wait = min(20.0, 4.0 * (2 ** min(rate_rounds - 1, 3)))
                self.add_log(f"[429 자동 대기] {int(wait)}초 후 재시도 · 진행상황 저장됨")
                self.progress(len(memory), total, f"무료 번역 서버 제한 · {int(wait)}초 후 자동 재시도")
                time.sleep(wait + random.uniform(0.2, 0.8))
            else:
                rate_rounds = 0
                if current < min(max_workers, 2):
                    current += 1
                # A tiny pacing delay is much faster than hitting a long 429 cooldown.
                if queue:
                    time.sleep(0.35 + random.uniform(0.05, 0.15))

    def translate_other_provider(self, translator, pending, memory, failures, options, sources, total):
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="translate") as pool:
            futures = {pool.submit(translator.translate_one, text): text for text in pending}
            for i, future in enumerate(as_completed(futures), 1):
                src = futures[future]
                try:
                    memory[src] = future.result()
                    failures.pop(src, None)
                except Exception as exc:
                    failures[src] = str(exc)
                if i % 10 == 0 or i == len(futures):
                    self.save_state(options, sources, memory, failures, total)
                self.progress(len(memory), total, f"번역 중 · 성공 {len(memory)}/{total}")

    def apply_patch_to_game(self, patch_root, game_dir, target_dir):
        game_dir = Path(game_dir)
        if game_dir.name.lower() != "game" or not game_dir.is_dir():
            raise RuntimeError("자동 적용 대상 game 폴더를 찾지 못했습니다.")
        destination = game_dir / "tl" / target_dir
        backup = None
        stamp = time.strftime("%Y%m%d_%H%M%S")
        backup_base = game_dir / "_RenPyTools_Backup"
        if destination.exists() and any(destination.rglob("*")):
            backup = backup_base / f"{target_dir}_{stamp}"
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(destination, backup)
            # Older RenPy Tools versions generated many per-file translation files.
            # Remove them after backup so stale duplicate `old` strings cannot remain.
            shutil.rmtree(destination)
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copytree(patch_root, destination, dirs_exist_ok=True)

        # Ren'Py keeps the original game language as `None` when a game has no
        # language selector. In that state tl/<language> string translations are
        # present on disk but are not active. Install a tiny root-level loader so
        # the generated translation is actually selected at game startup.
        language_loader = game_dir / "renpytools_language.rpy"
        if language_loader.exists():
            backup_base.mkdir(parents=True, exist_ok=True)
            loader_backup = backup_base / f"renpytools_language_{stamp}.rpy"
            shutil.copy2(language_loader, loader_backup)
        language_loader.write_text(
            "# Generated by RenPy Tools v0.3.3\n"
            "# Activates the language installed by RenPy Tools.\n"
            "init 999 python:\n"
            f"    config.language = {target_dir!r}\n",
            encoding="utf-8",
        )
        return destination, backup

    def build_standalone_patch(self, patch_root, target_dir):
        """Create one shareable EXE containing the patch payload."""
        candidates = [
            Path(sys.executable).resolve().with_name("RenPyPatchInstallerStub.exe"),
            Path(__file__).resolve().with_name("RenPyPatchInstallerStub.exe"),
        ]
        stub = next((p for p in candidates if p.is_file()), None)
        if stub is None:
            raise RuntimeError("독립 패치 설치기 파일(RenPyPatchInstallerStub.exe)을 찾지 못했습니다.")

        files = sorted(p for p in Path(patch_root).rglob("*") if p.is_file())
        if not files:
            raise RuntimeError("독립 패치에 넣을 번역 파일이 없습니다.")

        archive = bytearray(b"RPTPKG01")
        archive += len(files).to_bytes(4, "little")
        lang = target_dir.encode("utf-8")
        archive += len(lang).to_bytes(2, "little")
        archive += lang

        for file in files:
            rel = file.relative_to(patch_root).as_posix().encode("utf-8")
            data = file.read_bytes()
            archive += len(rel).to_bytes(4, "little")
            archive += len(data).to_bytes(8, "little")
            archive += rel
            archive += data

        output = self.output_zip.with_name(self.output_zip.stem + "_Standalone.exe")
        shutil.copy2(stub, output)
        with output.open("ab") as fp:
            fp.write(archive)
            fp.write(len(archive).to_bytes(8, "little"))
            fp.write(b"RPTEND01")
        return output

    def worker(self):
        temp = self.output_zip.parent / (self.output_zip.stem + "_work")
        try:
            o = self.job_options
            game, files = collect_rpy(Path(o["source_path"]))
            items = [(f, no, text) for f in files for no, text in extract_strings(f)]
            if not items:
                raise RuntimeError("번역 가능한 문자열을 찾지 못했습니다.")
            target_dir, target_code = LANGS[o["target_lang"]]
            translator = Translator(o["provider"], SOURCE_CODES[o["source_lang"]], target_code)
            if temp.exists():
                shutil.rmtree(temp)
            patch_root = temp / "game" / "tl" / target_dir
            patch_root.mkdir(parents=True)
            sources = list(dict.fromkeys(text for _, _, text in items))
            total = len(sources)
            memory, failures = self.load_saved_memory(o)
            source_set = set(sources)
            memory = {k: v for k, v in memory.items() if k in source_set}
            failures = {k: v for k, v in failures.items() if k in source_set and k not in memory}
            pending = [text for text in sources if text not in memory]
            self.save_state(o, sources, memory, failures, total)
            self.add_log(f"[번역 시작] 전체 {len(items)}개 · 중복 제거 {total}개 · 복원 {len(memory)}개 · 남은 {len(pending)}개")
            self.progress(len(memory), total, f"번역 시작 · 저장 {len(memory)}/{total}")
            if o["provider"] in ("무료 Google 번역", "무료 자동 선택 (추천)"):
                self.translate_google_batches(translator, pending, o["google_workers"], memory, failures, o, sources, total)
                if o["provider"] == "무료 자동 선택 (추천)":
                    fallback_pending = [src for src in sources if src not in memory]
                    if fallback_pending:
                        self.add_log(f"[무료 자동 우회] Google에서 남은 {len(fallback_pending)}문장만 다른 무료 엔진으로 재시도합니다.")
                        self.progress(len(memory), total, f"남은 {len(fallback_pending)}문장 무료 엔진 우회 중")
                        self.translate_other_provider(translator, fallback_pending, memory, failures, o, sources, total)
            else:
                self.translate_other_provider(translator, pending, memory, failures, o, sources, total)

            final_failed = [src for src in sources if src not in memory]
            # Ren'Py rejects the same `old` value if it is registered in multiple
            # translate-strings blocks. `sources` is game-wide deduplicated, so
            # v0.3.3 writes exactly one translation block and one entry per old text.
            dest = patch_root / "renpytools_strings.rpy"
            lines = [
                "# Generated by RenPy AI Patcher v0.3.3",
                "# Game-wide unique strings; duplicate old values are removed.",
                f"translate {target_dir} strings:",
                "",
            ]
            for old in sources:
                new = memory.get(old, old)
                lines.extend([f'    old "{escape_rpy(old)}"', f'    new "{escape_rpy(new)}"', ""])
            dest.write_text("\n".join(lines), encoding="utf-8")

            # This file lives directly under game/, not tl/. It forces the target
            # language on games that do not expose a language selector themselves.
            language_loader = temp / "game" / "renpytools_language.rpy"
            language_loader.write_text(
                "# Generated by RenPy Tools v0.3.3\n"
                "# Activates the language installed by RenPy Tools.\n"
                "init 999 python:\n"
                f"    config.language = {target_dir!r}\n",
                encoding="utf-8",
            )

            (temp / "패치_설명.txt").write_text(
                f"번역 파일: game/tl/{target_dir}/\n언어 활성화: game/renpytools_language.rpy\n최종 미번역: {len(final_failed)}개\n"
                f"Google 번역은 요청당 최대 {BATCH_SIZE}문장을 묶어 처리합니다.\n"
                "번역 기록은 RenPyTools/history에 유지되어 앱을 다시 실행해도 볼 수 있습니다.\n",
                encoding="utf-8",
            )
            self.progress(1, 1, "패치 ZIP 생성 중...")
            with zipfile.ZipFile(self.output_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
                for path in temp.rglob("*"):
                    if path.is_file():
                        archive.write(path, path.relative_to(temp))

            self.standalone_path = None
            if final_failed:
                self.add_log(f"[독립 EXE 보류] 미번역 {len(final_failed)}개가 남아 설치 EXE를 만들지 않았습니다.")
            else:
                try:
                    self.progress(1, 1, "공유용 독립 패치 EXE 생성 중...")
                    self.standalone_path = self.build_standalone_patch(patch_root, target_dir)
                    self.add_log(f"[독립 EXE 생성] {self.standalone_path}")
                except Exception as exc:
                    # Keep the ZIP/auto-apply result even if only EXE packaging fails.
                    self.add_log(f"[독립 EXE 생성 실패] {exc}")

            self.applied_path = None
            self.backup_path = None
            if o.get("auto_apply"):
                if final_failed:
                    self.add_log(f"[자동 적용 보류] 미번역 {len(final_failed)}개가 남아 원본 게임은 변경하지 않았습니다.")
                else:
                    self.progress(1, 1, "원본 게임에 패치 자동 적용 중...")
                    self.applied_path, self.backup_path = self.apply_patch_to_game(
                        patch_root, o.get("apply_game_path", ""), target_dir
                    )
                    self.add_log(f"[자동 적용 완료] {self.applied_path}")
                    if self.backup_path:
                        self.add_log(f"[기존 패치 백업] {self.backup_path}")

            self.save_state(o, sources, memory, failures, total, completed=True)
            try:
                self.checkpoint_path().unlink(missing_ok=True)
            except Exception:
                pass
            self.result = len(items)
            self.after(0, self.finish)
        except Exception as exc:
            try:
                if "o" in locals() and "sources" in locals() and "memory" in locals():
                    self.save_state(o, sources, memory, failures if "failures" in locals() else {}, len(sources))
            except Exception:
                pass
            msg = str(exc)
            self.after(0, lambda m=msg: messagebox.showerror(APP, f"작업 중 오류가 발생했습니다.\n\n{m}"))
            self.after(0, lambda: self.status.set("작업 실패 · 번역 기록은 저장됨"))
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
        if self.standalone_path:
            ttk.Label(body, text="✓ 공유용 단일 패치 EXE 생성 완료", style="Muted.Card.TLabel").pack(anchor="center", pady=(8, 0))
            ttk.Label(body, text=str(self.standalone_path), style="Muted.Card.TLabel").pack(anchor="center", pady=(2, 0))
        if self.applied_path:
            ttk.Label(body, text="✓ 원본 게임에 자동 패치 적용 완료", style="Muted.Card.TLabel").pack(anchor="center", pady=(8, 0))
            ttk.Label(body, text=str(self.applied_path), style="Muted.Card.TLabel").pack(anchor="center", pady=(2, 0))
            if self.backup_path:
                ttk.Label(body, text=f"기존 패치 백업: {self.backup_path}", style="Muted.Card.TLabel").pack(anchor="center", pady=(2, 0))
        buttons = ttk.Frame(self.container)
        buttons.pack(fill="x", pady=(18, 0))
        ttk.Button(buttons, text="처음으로", style="Secondary.TButton", command=self.restart).pack(side="left")
        ttk.Button(buttons, text="번역 기록 보기", style="Secondary.TButton", command=self.open_history_browser).pack(side="left", padx=(8, 0))
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
