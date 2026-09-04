#!/usr/bin/env python3
import sys
import tempfile
from pathlib import Path

from RenPyToolsLauncherV050 import RenPyToolsV050
from v049_compat import run_v049_self_test
from v050_workspace import run_v050_workspace_self_test
from v050_manual_merge import build_master_workflow_v050, run_v050_self_test


def run_master_contract_test():
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "Tree"
            game = root / "game"
            game.mkdir(parents=True)
            (game / "script.rpy").write_text(
                'label start:\n'
                '    "Good morning. I was waiting for you at the school gate."\n'
                '    "Please remember to bring your notebook after class today."\n',
                encoding="utf-8",
            )
            workspace = Path(td) / "Download" / "Tree TL.RENPY" / "20260904_170000"
            manifest = build_master_workflow_v050(
                root, workspace, "ChatGPT", "Plus", "High (GPT-5.6 Sol)", "한국어"
            )
            assert manifest["game_name"] == "Tree"
            assert manifest["result_prefix"] == "TreeTL"
            assert manifest["game_id"]
            master_file = workspace / "AI_전체번역작업.txt"
            assert master_file.is_file()
            text = master_file.read_text(encoding="utf-8")
            assert "TreeTL_001.txt" in text
            assert "'다음', '0', 또는 '.'" in text
            assert "모든 번역이 끝났습니다." in text
            assert "코드블록에 결과를 붙여넣는 방식은 금지" in text
        return 0
    except Exception as exc:
        try:
            Path("RenPyTools-v050-contract-error.txt").write_text(repr(exc), encoding="utf-8")
        except Exception:
            pass
        return 1


def run_all_self_tests():
    # Do not call the legacy v0.4.8 Hello/World fixture: those strings are
    # intentionally filtered by the real extractor and make that old fixture invalid.
    for test in (
        run_v049_self_test,
        run_v050_workspace_self_test,
        run_master_contract_test,
        run_v050_self_test,
    ):
        code = test()
        if code:
            return code
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_all_self_tests())
    RenPyToolsV050().mainloop()
