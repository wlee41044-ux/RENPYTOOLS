#!/usr/bin/env python3
import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from RenPyExtractor import (
    HAVE_TOOLKIT,
    RenPyArchive,
    decompile_rpyc_file,
    resolve_game_folder,
    safe_archive_path,
)

SCRIPT_EXTS = {".rpy", ".rpyc", ".rpym", ".rpymc"}
COMPILED_EXTS = {".rpyc", ".rpymc"}
ARCHIVE_EXTS = {".rpa", ".rpi"}
SKIP_DIRS = {"tl", "cache", "saves", "_renpytools_backup", "renpytools_output"}


def _walk_files(root, suffixes):
    root = Path(root)
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS]
        base = Path(dirpath)
        for name in filenames:
            if Path(name).suffix.lower() in suffixes:
                out.append(base / name)
    return out


def can_auto_decompile(source):
    try:
        game = resolve_game_folder(source)
    except Exception:
        return False
    return bool(_walk_files(game, COMPILED_EXTS | ARCHIVE_EXTS))


def decompile_cache_root(source):
    game = resolve_game_folder(source)
    identity = str(game.parent.resolve()).lower().encode("utf-8", errors="replace")
    key = hashlib.sha256(identity).hexdigest()[:16]
    base = Path(os.getenv("APPDATA") or Path.home()) / "RenPyTools" / "decompiled"
    return base / key


def prepare_decompiled_source(source, status=None):
    """Create a translation-only decompiled copy without modifying the game."""
    if not HAVE_TOOLKIT:
        raise RuntimeError("자동 디컴파일에 필요한 rpa-toolkit을 불러오지 못했습니다.")

    game_src = resolve_game_folder(source)
    output = decompile_cache_root(source)
    dest_game = output / "game"

    if output.exists():
        shutil.rmtree(output)
    dest_game.mkdir(parents=True, exist_ok=True)

    def report(text):
        if status:
            try:
                status(text)
            except Exception:
                pass

    report("게임 스크립트를 준비하고 있어요...")
    loose = _walk_files(game_src, SCRIPT_EXTS)
    for path in loose:
        rel = path.relative_to(game_src)
        out = dest_game / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, out)

    archives = _walk_files(game_src, ARCHIVE_EXTS)
    extracted = 0
    archive_fail = 0
    for index, archive in enumerate(archives, 1):
        report(f"압축된 스크립트를 찾는 중... {index}/{len(archives)}")
        try:
            archive_parent = archive.parent.relative_to(game_src)
            with RenPyArchive(str(archive)) as rpa:
                for name in rpa.list():
                    if Path(str(name)).suffix.lower() not in SCRIPT_EXTS:
                        continue
                    out = safe_archive_path(dest_game / archive_parent, name)
                    if out is None:
                        archive_fail += 1
                        continue
                    if out.exists():
                        continue
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(rpa.read(name))
                    extracted += 1
        except Exception:
            archive_fail += 1

    compiled = _walk_files(dest_game, COMPILED_EXTS)
    ok = 0
    failed = 0
    for index, path in enumerate(compiled, 1):
        report(f"파일을 다듬고 있어요... {index}/{len(compiled)}")
        target = path.with_suffix(".rpym" if path.suffix.lower() == ".rpymc" else ".rpy")
        try:
            result = decompile_rpyc_file(path, output_path=target, overwrite=True)
            if getattr(result, "success", True) and target.is_file():
                ok += 1
                path.unlink(missing_ok=True)
            else:
                failed += 1
        except Exception:
            failed += 1

    text_scripts = _walk_files(dest_game, {".rpy", ".rpym"})
    if not text_scripts:
        raise RuntimeError(
            "자동 디컴파일을 시도했지만 번역 가능한 .rpy/.rpym 파일을 만들지 못했습니다. "
            f"RPYC 성공 {ok}개 / 실패 {failed}개 / RPA 추출 {extracted}개"
        )

    report("파일 준비가 끝났어요.")
    return output, {
        "loose": len(loose),
        "archives": len(archives),
        "extracted": extracted,
        "archive_fail": archive_fail,
        "compiled": len(compiled),
        "decompiled": ok,
        "decompile_fail": failed,
        "scripts": len(text_scripts),
        "original_game": str(game_src),
    }


def run_auto_decompile_self_test():
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "Demo"
            game = root / "game"
            game.mkdir(parents=True)
            (game / "script.rpyc").write_bytes(b"not-a-real-rpyc")
            assert can_auto_decompile(root)
            assert decompile_cache_root(root).name
        return 0
    except Exception:
        return 1
