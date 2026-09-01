#!/usr/bin/env python3
from pathlib import Path
import re

p = Path("RenPyAIPatcher.py")
text = p.read_text(encoding="utf-8")


def rep(old, new, count=1):
    global text
    if old not in text:
        raise SystemExit(f"Expected source fragment not found: {old[:120]!r}")
    text = text.replace(old, new, count)


rep('import threading\n', 'import threading\nimport tempfile\n')
rep('VERSION = "0.3.6"', 'VERSION = "0.3.7"')
rep('BATCH_SIZE = 12', 'BATCH_SIZE = 40')
rep('self.google_workers = tk.IntVar(value=2)', 'self.google_workers = tk.IntVar(value=3)')
rep('ttk.Spinbox(left, from_=1, to=8, textvariable=self.google_workers, width=8)', 'ttk.Spinbox(left, from_=1, to=4, textvariable=self.google_workers, width=8)')
rep('기본 2 · 요청당 최대 12문장 · 1~3 권장', '기본 3 · 요청당 최대 40문장 · 속도 우선 · 2~4 권장')
rep('미번역 문장이 남으면 자동 적용하지 않습니다. 기존 같은 언어 패치는 백업 후 갱신합니다.', '일부 미번역은 원문으로 남긴 채 적용합니다. 기존 같은 언어 패치는 백업 후 갱신합니다.')
rep('무료 자동 선택: Google 배치 번역을 우선 사용하고 제한 시 속도를 자동 조절', '무료 자동 선택: Google 대형 배치 고속 번역 · 느린 무료 엔진으로 자동 전환하지 않음')

# Throttle full JSON disk writes. Large games used to rewrite the whole history
# after nearly every network result, which becomes expensive as memory grows.
start = text.index('    def save_state(self, options, sources, memory, failures, total, completed=False):')
end = text.index('    def list_history_files(self):', start)
new_save = '''    def save_state(self, options, sources, memory, failures, total, completed=False, force=False):
        now = time.time()
        data = {
            "version": 6, "signature": self.signature(options), "saved_at": now,
            "total": total, "sources": sources, "translations": memory,
            "failures": failures, "completed": completed,
        }
        # Keep the live history window current even when disk writes are throttled.
        with self.history_lock:
            self.current_history = data
        last = getattr(self, "_last_disk_save", 0.0)
        if not (completed or force or now - last >= 1.5):
            return
        hp = self.history_path(options)
        tmp = hp.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, hp)
        if self.output_zip:
            cp = self.checkpoint_path()
            ctmp = cp.with_suffix(cp.suffix + ".tmp")
            ctmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(ctmp, cp)
        self._last_disk_save = now

'''
text = text[:start] + new_save + text[end:]

# Replace the Google queue with a speed-first implementation. 429 is handled by
# reducing concurrency and retrying the SAME large batch; splitting on 429 only
# increases request count and makes rate limits worse.
start = text.index('    def translate_google_batches(')
end = text.index('    def translate_auto_fallback(', start)
new_google = '''    def translate_google_batches(self, translator, pending, max_workers, memory, failures, options, sources, total, auto_failover=False):
        queue = make_batches(pending)
        current = max(1, min(int(max_workers or 1), 4))
        non_rate_attempts = {}
        consecutive_429 = 0
        started = time.monotonic()
        initial_done = len(memory)
        self.add_log(
            f"[고속 배치 번역] {len(pending)}문장 → {len(queue)}개 요청 묶음 · "
            f"묶음당 최대 {BATCH_SIZE}문장 · 동시 요청 {current}개"
        )
        while queue:
            wave = queue[:current]
            queue = queue[len(wave):]
            rate_limited = []
            with ThreadPoolExecutor(max_workers=current, thread_name_prefix="google-fast") as pool:
                futures = {pool.submit(translator.translate_google_batch, batch): batch for batch in wave}
                for future in as_completed(futures):
                    batch = futures[future]
                    key = tuple(batch)
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
                            # Keep the batch intact. More/smaller requests make 429 worse.
                            rate_limited.append(batch)
                        elif len(batch) > 1:
                            mid = max(1, len(batch) // 2)
                            queue[:0] = [batch[:mid], batch[mid:]]
                            self.add_log(f"[HTTP {exc.code} · 배치 축소] {len(batch)} → {len(batch[:mid])}+{len(batch[mid:])}")
                        else:
                            non_rate_attempts[key] = non_rate_attempts.get(key, 0) + 1
                            if non_rate_attempts[key] < 3:
                                queue.insert(0, batch)
                            else:
                                failures[batch[0]] = f"HTTP {exc.code}"
                    except Exception as exc:
                        non_rate_attempts[key] = non_rate_attempts.get(key, 0) + 1
                        if len(batch) > 1:
                            mid = max(1, len(batch) // 2)
                            queue[:0] = [batch[:mid], batch[mid:]]
                            self.add_log(f"[배치 자동 복구] {len(batch)}문장 묶음 → 더 작은 묶음")
                        elif non_rate_attempts[key] < 3:
                            queue.insert(0, batch)
                        else:
                            failures[batch[0]] = str(exc)
                    elapsed = max(time.monotonic() - started, 0.001)
                    translated_now = max(0, len(memory) - initial_done)
                    speed = translated_now / elapsed
                    self.progress(
                        len(memory), total,
                        f"고속 번역 · 성공 {len(memory)}/{total} · 요청 {current}개 동시 · {speed:.1f}문장/초"
                    )

            if rate_limited:
                queue = rate_limited + queue
                consecutive_429 += 1
                new_current = max(1, current - 1)
                if new_current != current:
                    self.add_log(f"[429 감지] 동시 요청 {current} → {new_current}")
                    current = new_current
                wait = min(30.0, float(2 ** min(consecutive_429, 5)))
                self.add_log(f"[429 대기] 큰 묶음은 유지 · {int(wait)}초 후 재시도")
                self.progress(len(memory), total, f"Google 사용 제한 · {int(wait)}초 대기 · 진행 저장됨")
                self.save_state(options, sources, memory, failures, total, force=True)
                if consecutive_429 >= 6:
                    raise RuntimeError(
                        "Google 번역이 계속 429 사용 제한을 반환했습니다. 현재 번역은 저장되어 있습니다. "
                        "잠시 후 같은 설정으로 다시 실행하면 이어서 번역합니다."
                    )
                time.sleep(wait + random.uniform(0.1, 0.4))
            else:
                consecutive_429 = 0
                if current < min(int(max_workers or 1), 4):
                    current += 1
                # No fixed pacing in speed mode. Large batches already reduce request count.
        self.save_state(options, sources, memory, failures, total, force=True)
        return True

'''
text = text[:start] + new_google + text[end:]

# In the recommended mode Google remains the only automatic network engine.
# This restores the pre-fallback behaviour and prevents the whole job from
# falling into very slow/low-quota MyMemory after one Google 429.
old_worker = '''            if translator.source == "auto":
                detected_source = detect_source_code(sources)
                if detected_source:
                    translator.source = detected_source
                    self.add_log(f"[원본 언어 자동 판별] {detected_source} · 무료 우회 엔진에서도 사용합니다.")
            memory, failures = self.load_saved_memory(o)'''
new_worker = '''            # Keep Google source detection as `auto`. v0.3.5 started forcing a
            # guessed language here only to unlock slow fallback providers.
            memory, failures = self.load_saved_memory(o)'''
rep(old_worker, new_worker)

old_dispatch = '''            if o["provider"] in ("무료 Google 번역", "무료 자동 선택 (추천)"):
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
            elif o["provider"] == "MyMemory (무료/키 없음)":'''
new_dispatch = '''            if o["provider"] in ("무료 Google 번역", "무료 자동 선택 (추천)"):
                self.translate_google_batches(
                    translator, pending, o["google_workers"], memory, failures, o, sources, total
                )
            elif o["provider"] == "MyMemory (무료/키 없음)":'''
rep(old_dispatch, new_dispatch)

# Speed-first policy: a few failed lines stay as original text instead of blocking
# the entire usable patch/installer.
old_standalone = '''            self.standalone_path = None
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
                        self.add_log(f"[기존 패치 백업] {self.backup_path}")'''
new_standalone = '''            self.standalone_path = None
            if final_failed:
                self.add_log(f"[속도 우선] 미번역 {len(final_failed)}개는 원문으로 유지합니다.")
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
                self.progress(1, 1, "원본 게임에 패치 자동 적용 중...")
                self.applied_path, self.backup_path = self.apply_patch_to_game(
                    patch_root, o.get("apply_game_path", ""), target_dir
                )
                self.add_log(f"[자동 적용 완료] {self.applied_path}")
                if self.backup_path:
                    self.add_log(f"[기존 패치 백업] {self.backup_path}")'''
rep(old_standalone, new_standalone)

# Ensure error exits persist the latest translations immediately.
rep('self.save_state(o, sources, memory, failures if "failures" in locals() else {}, len(sources))',
    'self.save_state(o, sources, memory, failures if "failures" in locals() else {}, len(sources), force=True)')

# Version strings in generated patch files/loaders/comments.
text = text.replace('v0.3.6', 'v0.3.7')

# Replace self-test with tests for the new core path: large batching, token
# preservation, and actual patch copy/language activation. No internet needed.
start = text.index('def run_self_test():')
end = text.index('\n\nif __name__ == "__main__":', start)
new_test = '''def run_self_test():
    try:
        # Large batches are the main speed lever.
        sample = [f"短い台詞{i}" for i in range(95)]
        rows = make_batches(sample)
        assert rows
        assert sum(len(row) for row in rows) == len(sample)
        assert all(1 <= len(row) <= BATCH_SIZE for row in rows)

        # Google batch separator parsing + Ren'Py token preservation.
        fake = Translator("무료 Google 번역", "auto", "ko")
        fake.google_raw = lambda value: value.replace("你好", "안녕하세요").replace("再见", "잘 가")
        translated = fake.translate_google_batch(["你好 {name}", "再见"])
        assert translated == ["안녕하세요 {name}", "잘 가"]

        # The generated patch must actually be copied into game/tl/<language>
        # and install the language activation loader.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            game = root / "game"
            patch = root / "patch"
            game.mkdir()
            patch.mkdir()
            (patch / "renpytools_strings.rpy").write_text(
                'translate korean strings:\\n    old "你好"\\n    new "안녕하세요"\\n',
                encoding="utf-8",
            )
            destination, backup = PatcherApp.apply_patch_to_game(None, patch, game, "korean")
            assert backup is None
            assert (destination / "renpytools_strings.rpy").is_file()
            loader = (game / "renpytools_language.rpy").read_text(encoding="utf-8")
            assert "config.language = 'korean'" in loader
        return 0
    except Exception as exc:
        try:
            Path("RenPyAIPatcher-selftest-error.txt").write_text(repr(exc), encoding="utf-8")
        except Exception:
            pass
        return 1
'''
text = text[:start] + new_test + text[end:]

p.write_text(text, encoding="utf-8")

iss = Path("installer.iss")
iss_text = iss.read_text(encoding="utf-8")
if '#define MyAppVersion "0.3.6"' not in iss_text:
    raise SystemExit("installer.iss v0.3.6 version not found")
iss.write_text(iss_text.replace('#define MyAppVersion "0.3.6"', '#define MyAppVersion "0.3.7"', 1), encoding="utf-8")

print("Applied v0.3.7 speed-first stabilization patch")
