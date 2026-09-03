#!/usr/bin/env python3
import json
import tempfile
from pathlib import Path

from v048_master_hq import (
    MASTER_BASENAME,
    build_master_workflow,
    estimate_tokens,
    master_status,
    profile_for,
    scan_master_results,
    write_combined_if_done,
)


def run_v048_ci_self_test():
    try:
        assert profile_for("Gemini", "Google AI Pro", "Gemini 3 Pro")["context_tokens"] == 1000000
        assert profile_for("Claude", "Pro", "Claude Sonnet 5")["max_output_tokens"] == 128000
        assert profile_for("ChatGPT", "Plus", "High (GPT-5.6 Sol)")["safe_master_tokens"] >= 300000
        assert estimate_tokens("Hello world") < estimate_tokens("안녕하세요 세계") * 2

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "Demo"
            game = root / "game"
            game.mkdir(parents=True)
            # Use realistic dialogue. The production scanner intentionally ignores
            # some tiny/generic strings, so "Hello"/"World" were a bad self-test.
            (game / "script.rpy").write_text(
                'label start:\n'
                '    "Hello there, this is a RenPy Tools translation test line."\n'
                '    "Where are you going today? I was looking for you."\n',
                encoding="utf-8",
            )

            out = Path(td) / "out"
            manifest = build_master_workflow(
                root, out, "ChatGPT", "Plus", "High (GPT-5.6 Sol)"
            )
            assert manifest["total"] == 2
            assert len(manifest["parts"]) == 1
            assert (out / f"{MASTER_BASENAME}.txt").is_file()

            ids = list(manifest["sources"])
            downloads = Path(td) / "Download"
            downloads.mkdir()
            (downloads / "RenPyTools_Result_test.txt").write_text(
                f'{ids[0]}\t"안녕하세요, 이것은 렌파이 툴 번역 테스트 문장입니다."\n'
                f'{ids[1]}\t"오늘 어디 가세요? 찾고 있었어요."\n',
                encoding="utf-8",
            )
            imported, memory = scan_master_results(out, roots=[downloads])
            assert imported == 2 and len(memory) == 2
            assert master_status(out)["done"]
            combined = write_combined_if_done(out)
            assert combined is not None and combined.is_file()
        return 0
    except Exception as exc:
        try:
            Path("RenPyTools-v048-selftest-error.txt").write_text(repr(exc), encoding="utf-8")
        except Exception:
            pass
        return 1
