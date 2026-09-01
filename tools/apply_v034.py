from pathlib import Path

p = Path('RenPyAIPatcher.py')
s = p.read_text(encoding='utf-8')

s = s.replace('VERSION = "0.3.3"', 'VERSION = "0.3.4"', 1)
s = s.replace('data = self._request_json(url, timeout=8)', 'data = self._request_json(url, timeout=5)', 1)

old = '''        self.provider, self.source, self.target = provider, source, target
        self.google_blocked_until = 0.0
        self._state_lock = threading.Lock()
'''
new = '''        self.provider, self.source, self.target = provider, source, target
        self.google_blocked_until = 0.0
        self.lingva_preferred = None
        self._state_lock = threading.Lock()
'''
if old not in s:
    raise SystemExit('init block not found')
s = s.replace(old, new, 1)

old = '''    def lingva_raw(self, text):
        last = None
        encoded = urllib.parse.quote(text, safe="")
        for base in self.LINGVA_INSTANCES:
            try:
                url = f"{base}/api/v1/{self.source}/{self.target}/{encoded}"
                data = self._request_json(url, timeout=5)
                out = data.get("translation", "") if isinstance(data, dict) else ""
                if out:
                    return out
            except Exception as exc:
                last = exc
        raise RuntimeError(f"Lingva 공개 서버에 연결하지 못했습니다: {last}")
'''
new = '''    def lingva_raw(self, text):
        last = None
        encoded = urllib.parse.quote(text, safe="")
        instances = list(self.LINGVA_INSTANCES)
        with self._state_lock:
            preferred = self.lingva_preferred
        if preferred in instances:
            instances.remove(preferred)
            instances.insert(0, preferred)
        for base in instances:
            try:
                url = f"{base}/api/v1/{self.source}/{self.target}/{encoded}"
                data = self._request_json(url, timeout=5)
                out = data.get("translation", "") if isinstance(data, dict) else ""
                if out:
                    with self._state_lock:
                        self.lingva_preferred = base
                    return out
            except Exception as exc:
                last = exc
        raise RuntimeError(f"Lingva 공개 서버에 연결하지 못했습니다: {last}")
'''
if old not in s:
    raise SystemExit('lingva block not found')
s = s.replace(old, new, 1)

s = s.replace(
    '    def translate_google_batches(self, translator, pending, max_workers, memory, failures, options, sources, total):',
    '    def translate_google_batches(self, translator, pending, max_workers, memory, failures, options, sources, total, auto_failover=False):',
    1,
)

old = '''            if rate_hits:
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
'''
new = '''            if rate_hits:
                rate_rounds += 1
                if auto_failover:
                    # A 429 means this IP is currently rate-limited. Do not keep
                    # hammering the same endpoint in automatic mode. Preserve the
                    # completed memory and immediately switch to a different free engine.
                    with translator._state_lock:
                        translator.google_blocked_until = max(translator.google_blocked_until, time.time() + 600.0)
                    self.add_log("[429 자동 우회] Google 요청을 중단하고 다른 무료 엔진으로 전환합니다.")
                    self.progress(len(memory), total, "Google 사용 제한 감지 · 다른 무료 엔진 확인 중")
                    self.save_state(options, sources, memory, failures, total)
                    return False
                new_current = max(1, current - 1)
                if new_current != current:
                    self.add_log(f"[429 감지] 동시 요청 {current} → {new_current}")
                    current = new_current
                wait = min(20.0, 4.0 * (2 ** min(rate_rounds - 1, 3)))
                self.add_log(f"[429 자동 대기] {int(wait)}초 후 재시도 · 진행상황 저장됨")
                self.progress(len(memory), total, f"Google 사용 제한 · {int(wait)}초 후 자동 재시도")
                time.sleep(wait + random.uniform(0.2, 0.8))
            else:
                rate_rounds = 0
                if current < min(max_workers, 2):
                    current += 1
                # A tiny pacing delay is much faster than hitting a long 429 cooldown.
                if queue:
                    time.sleep(0.35 + random.uniform(0.05, 0.15))
        return True

    def translate_auto_fallback(self, translator, pending, memory, failures, options, sources, total):
        if not pending:
            return
        candidates = ["Lingva Translate (무료/키 없음)"]
        if translator.source != "auto":
            candidates.append("MyMemory (무료/키 없음)")

        probe = pending[0]
        selected = None
        selected_name = None
        for name in candidates:
            self.add_log(f"[무료 엔진 확인] {name}")
            self.progress(len(memory), total, f"{name} 연결 확인 중")
            candidate = Translator(name, translator.source, translator.target)
            try:
                translated = candidate.translate_one(probe)
                if not translated:
                    raise RuntimeError("빈 번역 결과")
                memory[probe] = translated
                failures.pop(probe, None)
                selected = candidate
                selected_name = name
                self.save_state(options, sources, memory, failures, total)
                break
            except Exception as exc:
                self.add_log(f"[무료 엔진 사용 불가] {name} · {exc}")

        if selected is None:
            self.save_state(options, sources, memory, failures, total)
            raise RuntimeError(
                "Google 번역이 사용 제한(429)에 걸렸고 다른 무료 번역 서버에도 연결하지 못했습니다. "
                "현재까지 성공한 번역은 저장되어 있으니 잠시 후 다시 실행하세요."
            )

        remaining = [src for src in pending if src not in memory]
        self.add_log(f"[무료 자동 전환 완료] {selected_name} · 남은 {len(remaining)}문장")
        self.progress(len(memory), total, f"{selected_name}로 계속 번역 중")
        if remaining:
            self.translate_other_provider(selected, remaining, memory, failures, options, sources, total)

    def translate_other_provider(self, translator, pending, memory, failures, options, sources, total):
'''
if old not in s:
    raise SystemExit('google/fallback insertion point not found')
s = s.replace(old, new, 1)

old = '''            if o["provider"] in ("무료 Google 번역", "무료 자동 선택 (추천)"):
                self.translate_google_batches(translator, pending, o["google_workers"], memory, failures, o, sources, total)
                if o["provider"] == "무료 자동 선택 (추천)":
                    fallback_pending = [src for src in sources if src not in memory]
                    if fallback_pending:
                        self.add_log(f"[무료 자동 우회] Google에서 남은 {len(fallback_pending)}문장만 다른 무료 엔진으로 재시도합니다.")
                        self.progress(len(memory), total, f"남은 {len(fallback_pending)}문장 무료 엔진 우회 중")
                        self.translate_other_provider(translator, fallback_pending, memory, failures, o, sources, total)
            else:
'''
new = '''            if o["provider"] in ("무료 Google 번역", "무료 자동 선택 (추천)"):
                auto_mode = o["provider"] == "무료 자동 선택 (추천)"
                self.translate_google_batches(
                    translator, pending, o["google_workers"], memory, failures, o, sources, total,
                    auto_failover=auto_mode,
                )
                if auto_mode:
                    fallback_pending = [src for src in sources if src not in memory]
                    if fallback_pending:
                        self.add_log(f"[무료 자동 우회] Google에서 남은 {len(fallback_pending)}문장을 다른 무료 엔진으로 넘깁니다.")
                        self.translate_auto_fallback(translator, fallback_pending, memory, failures, o, sources, total)
            else:
'''
if old not in s:
    raise SystemExit('worker provider block not found')
s = s.replace(old, new, 1)

s = s.replace('Generated by RenPy Tools v0.3.3', 'Generated by RenPy Tools v0.3.4')
s = s.replace('v0.3.3 writes exactly one translation block', 'v0.3.4 writes exactly one translation block')
s = s.replace('Generated by RenPy AI Patcher v0.3.3', 'Generated by RenPy AI Patcher v0.3.4')

p.write_text(s, encoding='utf-8')

iss = Path('installer.iss')
i = iss.read_text(encoding='utf-8')
i = i.replace('#define MyAppVersion "0.3.3"', '#define MyAppVersion "0.3.4"', 1)
iss.write_text(i, encoding='utf-8')
