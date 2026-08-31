from pathlib import Path

p = Path('RenPyAIPatcher.py')
s = p.read_text(encoding='utf-8')


def rep(old, new, label):
    global s
    if old not in s:
        raise SystemExit(f'Missing patch target: {label}')
    s = s.replace(old, new, 1)


rep('VERSION = "0.3.0"', 'VERSION = "0.3.1"', 'version')
rep('PROVIDERS = ["무료 Google 번역", "Ollama (무료/로컬)", "LM Studio / OpenAI 호환", "OpenAI 호환 API"]', '''PROVIDERS = [
    "무료 자동 선택 (추천)",
    "무료 Google 번역",
    "Lingva Translate (무료/키 없음)",
    "MyMemory (무료/키 없음)",
    "Ollama (무료/로컬 자동모델)",
    "LM Studio (무료/로컬 자동모델)",
]''', 'providers')

start = s.index('class Translator:')
end = s.index('\n\nclass PatcherApp', start)
new_translator = r'''class Translator:
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
                data = self._request_json(url, timeout=25)
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
'''
s = s[:start] + new_translator + s[end:]

rep('self.provider = tk.StringVar(value="무료 Google 번역")', 'self.provider = tk.StringVar(value="무료 자동 선택 (추천)")', 'default provider')
rep('''        self.api_key = tk.StringVar()\n        self.base_url = tk.StringVar()\n        self.model = tk.StringVar()\n''', '', 'remove api vars')
rep('Ren\'Py AI 한글패치 제작 · 중복 안전 패치 · 독립 실행 EXE · 자동 적용', 'Ren\'Py AI 한글패치 제작 · 무료 번역 엔진 · 429 자동 우회 · 자동 패치', 'subtitle')

old_right = '''        ttk.Label(right, text="고급 연결 설정", style="Section.TLabel").pack(anchor="w", pady=(0, 10))\n        ttk.Label(right, text="무료 Google 번역은 아래 항목을 비워도 됩니다.", style="Muted.Card.TLabel").pack(anchor="w", pady=(0, 10))\n        self.entry_row(right, "API Key", self.api_key, show="•")\n        self.entry_row(right, "Model", self.model)\n        self.entry_row(right, "Base URL", self.base_url)\n'''
new_right = '''        ttk.Label(right, text="무료 엔진 안내", style="Section.TLabel").pack(anchor="w", pady=(0, 10))\n        ttk.Label(right, text="API Key가 필요한 번역 방식은 v0.3.1에서 제거했습니다.", style="Muted.Card.TLabel").pack(anchor="w", pady=(0, 8))\n        ttk.Label(right, text="무료 자동 선택: Google이 제한되면 Lingva로 자동 우회", style="Card.TLabel").pack(anchor="w", pady=(3, 0))\n        ttk.Label(right, text="MyMemory: 키 없이 사용 가능하지만 원본 언어 지정 필요 · 사용량 제한 있음", style="Muted.Card.TLabel").pack(anchor="w", pady=(3, 0))\n        ttk.Label(right, text="Ollama / LM Studio: PC에 설치·로드된 로컬 모델을 자동 선택", style="Muted.Card.TLabel").pack(anchor="w", pady=(3, 0))\n        ttk.Label(right, text="무료 서버는 외부 서비스 제한에 따라 일시적으로 느리거나 막힐 수 있습니다.", style="Muted.Card.TLabel").pack(anchor="w", pady=(12, 0))\n'''
rep(old_right, new_right, 'free info card')

rep('''            "target_lang": self.target_lang.get(), "provider": self.provider.get(),\n            "google_workers": workers, "api_key": self.api_key.get(),\n            "base_url": self.base_url.get(), "model": self.model.get(),\n            "auto_apply": self.auto_apply.get(), "apply_game_path": apply_game_path,\n''', '''            "target_lang": self.target_lang.get(), "provider": self.provider.get(),\n            "google_workers": workers, "base_url": "", "model": "",\n            "auto_apply": self.auto_apply.get(), "apply_game_path": apply_game_path,\n''', 'job options')

rep('translator = Translator(o["provider"], SOURCE_CODES[o["source_lang"]], target_code, o["api_key"], o["base_url"], o["model"])', 'translator = Translator(o["provider"], SOURCE_CODES[o["source_lang"]], target_code)', 'translator init')
rep('''            if o["provider"] == "무료 Google 번역":\n                self.translate_google_batches(translator, pending, o["google_workers"], memory, failures, o, sources, total)\n            else:\n                self.translate_other_provider(translator, pending, memory, failures, o, sources, total)\n''', '''            if o["provider"] == "무료 Google 번역":\n                self.translate_google_batches(translator, pending, o["google_workers"], memory, failures, o, sources, total)\n            else:\n                self.translate_other_provider(translator, pending, memory, failures, o, sources, total)\n''', 'translation dispatch')

rep('with ThreadPoolExecutor(max_workers=4, thread_name_prefix="translate") as pool:', 'with ThreadPoolExecutor(max_workers=2, thread_name_prefix="translate") as pool:', 'free provider concurrency')

rep('''        queue = make_batches(pending)\n        current = min(max_workers, 3)\n        attempts = {}\n        started = time.monotonic()\n''', '''        queue = make_batches(pending)\n        current = min(max_workers, 3)\n        attempts = {}\n        rate_rounds = 0\n        started = time.monotonic()\n''', 'rate rounds')
rep('''            if rate_hits:\n                new_current = max(1, current - 1)\n                if new_current != current:\n                    self.add_log(f"[429 감지] 동시 요청 {current} → {new_current}")\n                    current = new_current\n                time.sleep(min(12.0, 2.5 + rate_hits * 0.8) + random.uniform(0.2, 0.8))\n            elif current < min(max_workers, 3):\n                current += 1\n''', '''            if rate_hits:\n                rate_rounds += 1\n                new_current = max(1, current - 1)\n                if new_current != current:\n                    self.add_log(f"[429 감지] 동시 요청 {current} → {new_current}")\n                    current = new_current\n                wait = min(60.0, 5.0 * (2 ** min(rate_rounds - 1, 4)))\n                self.add_log(f"[429 자동 대기] {int(wait)}초 후 재시도 · 진행상황 저장됨")\n                time.sleep(wait + random.uniform(0.2, 0.8))\n            else:\n                rate_rounds = 0\n                if current < min(max_workers, 3):\n                    current += 1\n''', 'google backoff')

p.write_text(s, encoding='utf-8')
print('RenPyAIPatcher.py upgraded to v0.3.1')
