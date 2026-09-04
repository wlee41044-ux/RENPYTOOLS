#!/usr/bin/env python3
import tempfile
from pathlib import Path

from auto_decompile import can_auto_decompile, prepare_decompiled_source
from fast_scan import collect_rpy_fast
from RenPyExtractor import resolve_game_folder


def prepare_complete_source(owner, path, status=None):
    """Prepare the complete readable script set before any translation starts.

    If compiled scripts or archives exist, always build a translation-only copy
    first. This prevents both quick and HQ modes from translating only the loose
    .rpy subset while silently skipping RPYC/RPA-contained scripts.
    """
    original = str(Path(path))

    if can_auto_decompile(original):
        if status:
            status("컴파일/압축 스크립트가 있어 먼저 디컴파일하고 있어요...")
        prepared, stats = prepare_decompiled_source(original, status=status)
        root, files = collect_rpy_fast(prepared)
        game = resolve_game_folder(original)
        return {
            "source": str(prepared),
            "root": root,
            "files": files,
            "original": original,
            "apply_game": str(game),
            "decompiled": True,
            "stats": stats,
        }

    root, files = collect_rpy_fast(Path(original))
    game = owner.resolve_game_for_apply(original, reject_decompiled=False)
    return {
        "source": original,
        "root": root,
        "files": files,
        "original": original,
        "apply_game": str(game) if game else "",
        "decompiled": False,
        "stats": {},
    }


def install_v051_prepare():
    import RenPyToolsMain
    RenPyToolsMain.RenPyToolsMain._prepare_source = prepare_complete_source
    return True


def run_v051_prepare_self_test():
    try:
        # Mixed source+compiled case is the regression that used to skip decompile.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "MixedGame"
            game = root / "game"
            game.mkdir(parents=True)
            original_text = 'label start:\n    "This readable source must stay unchanged during preparation."\n'
            (game / "script.rpy").write_text(original_text, encoding="utf-8")
            (game / "script.rpyc").write_bytes(b"fake-rpyc-covered-by-existing-rpy")

            assert can_auto_decompile(root)
            prepared, stats = prepare_decompiled_source(root)
            copied = Path(prepared) / "game" / "script.rpy"
            assert copied.is_file()
            assert copied.read_text(encoding="utf-8") == original_text
            assert stats.get("preserved_text", 0) >= 1
            _, files = collect_rpy_fast(prepared)
            assert files
        return 0
    except Exception as exc:
        try:
            Path("RenPyTools-v051-prepare-error.txt").write_text(repr(exc), encoding="utf-8")
        except Exception:
            pass
        return 1
