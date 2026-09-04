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
TEXT_EXTS = {".rpy", ".rpym"}
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
    """True when the game has compiled scripts or archives that may hide scripts."""
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
    """Create a complete translation-only script copy without modifying the game.

    Every RPYC/RPYMC is now actually attempted. If a readable .rpy/.rpym is
    already shipped beside it, a successful decompile refreshes that copy so we
    do not accidentally translate an older source file. If decompilation fails,
    the shipped readable source is kept as a fallback. A compiled-only script
    that cannot be recovered stops translation instead of being silently skipped.
    """
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

    report("기존 스크립트와 컴파일된 스크립트를 모으고 있어요...")
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
        report(f"압축 파일에서 스크립트를 찾고 있어요... {index}/{len(archives)}")
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
    preserved = 0
    refreshed = 0
    unrecovered = []

    for index, path in enumerate(compiled, 1):
        report(f"컴파일된 스크립트를 디컴파일하고 있어요... {index}/{len(compiled)}")
        target = path.with_suffix(".rpym" if path.suffix.lower() == ".rpymc" else ".rpy")
        had_readable = target.is_file()
        temp_target = target.with_name(target.stem + ".renpytools_decompiled" + target.suffix)
        try:
            temp_target.unlink(missing_ok=True)
        except Exception:
            pass

        success = False
        try:
            result = decompile_rpyc_file(path, output_path=temp_target, overwrite=True)
            success = bool(getattr(result, "success", True) and temp_target.is_file())
        except Exception:
            success = False

        if success:
            try:
                os.replace(temp_target, target)
            except Exception:
                shutil.copy2(temp_target, target)
                temp_target.unlink(missing_ok=True)
            ok += 1
            if had_readable:
                refreshed += 1
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass
            continue

        failed += 1
        try:
            temp_target.unlink(missing_ok=True)
        except Exception:
            pass
        if had_readable:
            preserved += 1
            # The translation cache only needs readable scripts. Keeping the
            # failed RPYC around can make later scans think preparation is incomplete.
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass
        else:
            try:
                unrecovered.append(str(path.relative_to(dest_game)))
            except Exception:
                unrecovered.append(path.name)

    if unrecovered:
        sample = ", ".join(unrecovered[:5])
        raise RuntimeError(
            "일부 컴파일 스크립트를 디컴파일하지 못해서 번역을 중단했습니다. "
            f"복구 실패 {len(unrecovered)}개 · 예: {sample}. "
            "이 상태에서 계속하면 대사가 빠진 불완전 패치가 만들어질 수 있습니다."
        )

    text_scripts = _walk_files(dest_game, TEXT_EXTS)
    if not text_scripts:
        raise RuntimeError(
            "자동 디컴파일을 시도했지만 번역 가능한 .rpy/.rpym 파일을 만들지 못했습니다. "
            f"RPYC 성공 {ok}개 / 실패 {failed}개 / RPA 추출 {extracted}개"
        )

    report("디컴파일/스크립트 준비가 끝났어요.")
    return output, {
        "loose": len(loose),
        "archives": len(archives),
        "extracted": extracted,
        "archive_fail": archive_fail,
        "compiled": len(compiled),
        "decompiled": ok,
        "refreshed_text": refreshed,
        "preserved_text": preserved,
        "decompile_fail": failed,
        "unrecovered": 0,
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
