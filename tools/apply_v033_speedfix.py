from pathlib import Path

app = Path("RenPyAIPatcher.py")
text = app.read_text(encoding="utf-8")

replacements = [
    ('VERSION = "0.3.2"', 'VERSION = "0.3.3"'),
    ('data = self._request_json(url, timeout=25)', 'data = self._request_json(url, timeout=8)'),
    ('current = min(max_workers, 3)', 'current = min(max_workers, 2)'),
    ('wave = queue[:max(current, 1) * 2]', 'wave = queue[:max(current, 1)]'),
    ('queue = queue[len(wave):]', 'queue = queue[len(wave):]'),
    ('if attempts[key] < 6:', 'if attempts[key] < 4:'),
    ('wait = min(60.0, 5.0 * (2 ** min(rate_rounds - 1, 4)))', 'wait = min(20.0, 4.0 * (2 ** min(rate_rounds - 1, 3)))'),
    ('self.add_log(f"[429 자동 대기] {int(wait)}초 후 재시도 · 진행상황 저장됨")\n                time.sleep(wait + random.uniform(0.2, 0.8))', 'self.add_log(f"[429 자동 대기] {int(wait)}초 후 재시도 · 진행상황 저장됨")\n                self.progress(len(memory), total, f"무료 번역 서버 제한 · {int(wait)}초 후 자동 재시도")\n                time.sleep(wait + random.uniform(0.2, 0.8))'),
    ('if current < min(max_workers, 3):', 'if current < min(max_workers, 2):'),
    ('if o["provider"] == "무료 Google 번역":\n                self.translate_google_batches', 'if o["provider"] in ("무료 Google 번역", "무료 자동 선택 (추천)"):\n                self.translate_google_batches'),
    ('무료 자동 선택: Google이 제한되면 Lingva로 자동 우회', '무료 자동 선택: Google 배치 번역을 우선 사용하고 제한 시 속도를 자동 조절'),
]

for old, new in replacements:
    if old not in text:
        raise SystemExit(f"Expected source fragment not found: {old[:100]!r}")
    text = text.replace(old, new, 1)

# Avoid request bursts that trigger 429 after dozens of successful batches.
needle = '''            else:\n                rate_rounds = 0\n                if current < min(max_workers, 2):\n                    current += 1\n\n    def translate_other_provider'''
replacement = '''            else:\n                rate_rounds = 0\n                if current < min(max_workers, 2):\n                    current += 1\n                # A tiny pacing delay is much faster than hitting a long 429 cooldown.\n                if queue:\n                    time.sleep(0.35 + random.uniform(0.05, 0.15))\n\n    def translate_other_provider'''
if needle not in text:
    raise SystemExit("Could not locate successful-wave pacing insertion point")
text = text.replace(needle, replacement, 1)

# If the fast Google batch path still leaves a few failures in automatic mode,
# retry only those failed strings through the no-key automatic fallback chain.
needle = '''            if o["provider"] in ("무료 Google 번역", "무료 자동 선택 (추천)"):\n                self.translate_google_batches(translator, pending, o["google_workers"], memory, failures, o, sources, total)\n            else:\n                self.translate_other_provider(translator, pending, memory, failures, o, sources, total)\n\n            final_failed = [src for src in sources if src not in memory]'''
replacement = '''            if o["provider"] in ("무료 Google 번역", "무료 자동 선택 (추천)"):\n                self.translate_google_batches(translator, pending, o["google_workers"], memory, failures, o, sources, total)\n                if o["provider"] == "무료 자동 선택 (추천)":\n                    fallback_pending = [src for src in sources if src not in memory]\n                    if fallback_pending:\n                        self.add_log(f"[무료 자동 우회] Google에서 남은 {len(fallback_pending)}문장만 다른 무료 엔진으로 재시도합니다.")\n                        self.progress(len(memory), total, f"남은 {len(fallback_pending)}문장 무료 엔진 우회 중")\n                        self.translate_other_provider(translator, fallback_pending, memory, failures, o, sources, total)\n            else:\n                self.translate_other_provider(translator, pending, memory, failures, o, sources, total)\n\n            final_failed = [src for src in sources if src not in memory]'''
if needle not in text:
    raise SystemExit("Could not locate worker provider dispatch")
text = text.replace(needle, replacement, 1)

# Keep generated patch metadata aligned with the application version.
text = text.replace("v0.3.2", "v0.3.3")
app.write_text(text, encoding="utf-8")

installer = Path("installer.iss")
iss = installer.read_text(encoding="utf-8")
if '#define MyAppVersion "0.3.2"' not in iss:
    raise SystemExit("installer.iss is not at v0.3.2")
iss = iss.replace('#define MyAppVersion "0.3.2"', '#define MyAppVersion "0.3.3"', 1)
installer.write_text(iss, encoding="utf-8")

print("Applied v0.3.3 speed/stall hotfix")
