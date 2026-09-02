#!/usr/bin/env python3
import os
import tempfile
from pathlib import Path

SCRIPT_EXTS = {".rpy", ".rpym"}
SKIP_DIRS = {"tl", "cache", "saves", "_renpytools_backup", "renpytools_output"}


def _scan_scripts(root):
    """Find script files without stat'ing every asset in a large game folder."""
    root = Path(root)
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS]
        base = Path(dirpath)
        for name in filenames:
            if Path(name).suffix.lower() in SCRIPT_EXTS:
                files.append(base / name)
    return files


def collect_rpy_fast(root):
    """Winlator-friendly replacement for the original recursive scanner.

    A normal Ren'Py install keeps scripts under game/. If that directory exists,
    never recursively scan the whole installation (which may contain thousands
    of images/audio/video files). Only fall back to broader candidates for
    extracted/decompiled layouts.
    """
    root = Path(root)
    if not root.exists():
        raise RuntimeError("선택한 폴더를 찾을 수 없습니다.")

    candidates = []
    if root.name.lower() == "game" and root.is_dir():
        candidates.append(root)
    elif (root / "game").is_dir():
        candidates.append(root / "game")
    elif (root / "Decompiled" / "game").is_dir():
        candidates.append(root / "Decompiled" / "game")
    elif (root / "Decompiled").is_dir():
        candidates.append(root / "Decompiled")
    else:
        candidates.append(root)
        try:
            for child in root.iterdir():
                if child.is_dir() and (child / "game").is_dir():
                    candidates.append(child / "game")
        except Exception:
            pass

    for candidate in candidates:
        files = _scan_scripts(candidate)
        if files:
            return candidate, sorted(files)

    raise RuntimeError(
        "번역 가능한 .rpy/.rpym 파일을 찾지 못했습니다. "
        "게임 폴더 또는 Extractor 결과 폴더를 선택하세요."
    )


def run_fast_scan_self_test():
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            game = root / "game"
            (game / "images").mkdir(parents=True)
            (game / "tl" / "korean").mkdir(parents=True)
            (game / "script.rpy").write_text('label start:\n    "Hello"\n', encoding="utf-8")
            (game / "images" / "huge.bin").write_bytes(b"x" * 1024)
            (game / "tl" / "korean" / "old.rpy").write_text("translate korean strings:\n", encoding="utf-8")
            found_root, files = collect_rpy_fast(root)
            assert found_root == game
            assert [p.name for p in files] == ["script.rpy"]
        return 0
    except Exception:
        return 1
