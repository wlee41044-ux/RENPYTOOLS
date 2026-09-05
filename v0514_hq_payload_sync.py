#!/usr/bin/env python3
import inspect
import tempfile
from pathlib import Path

import RenPyAIPatcher as core
import RenPyToolsLauncherV0510 as launcher0510
import RenPyToolsLauncherV055 as launcher055
import v050_manual_merge as merge
from v052_render_compat import BUNDLED_FONT_NAME, PATCH_FONT_DIR

_INSTALLED = False


def _finalize_hq_payload(app, patch_root, target_dir, game):
    """Finalize HQ payload before either local apply or standalone packaging.

    v0.5.13 still applied the raw one-file HQ strings patch first, then inherited
    v0.5.5 standalone packaging finalized the temporary payload afterwards. That
    meant the creator's local game received no translated tl template/font/choice
    compatibility files while the later EXE could contain them. Finalize once,
    then use that exact directory for both outputs.
    """
    patch_root = Path(patch_root)
    game = Path(game)

    old_options = getattr(app, "job_options", None)
    options = dict(old_options) if isinstance(old_options, dict) else {}
    options["apply_game_path"] = str(game)
    options["source_path"] = str(game.parent)
    app.job_options = options
    try:
        structure = launcher055.prepare_final_payload(app, patch_root, target_dir)
    finally:
        app.job_options = old_options

    if target_dir == "korean":
        required = [
            patch_root / PATCH_FONT_DIR / BUNDLED_FONT_NAME,
            patch_root / "renpytools_font_compat.rpy",
            patch_root / "renpytools_choice_compat.rpy",
        ]
        missing = [p.name for p in required if not p.is_file()]
        if missing:
            raise RuntimeError(
                "고품질 패치의 한글 호환 파일 생성이 끝나지 않았습니다. "
                "게임에 불완전한 패치를 적용하지 않고 중단합니다. 누락: " + ", ".join(missing)
            )
    return structure


def merge_apply_and_build_exe_v0514(app, manifest, files, game_path):
    combined = merge.combine_result_files(manifest, files, require_complete=True)
    game = app.resolve_game_for_apply(game_path, reject_decompiled=False)
    if game is None:
        raise RuntimeError("선택한 폴더에서 game 폴더를 찾지 못했습니다.")

    game = Path(game)
    game_name = manifest.get("game_name") or merge.game_name_from_path(game_path)
    output_dir = merge.downloads_root(game_path)

    with tempfile.TemporaryDirectory() as td:
        patch_root = Path(td) / "patch"
        target_dir, _ = merge.build_patch_tree(manifest, combined["translations"], patch_root)

        # CRITICAL ORDER: build the real Ren'Py tl structure + bundled Korean
        # font + UI/choice compatibility BEFORE copying anything into the game.
        _finalize_hq_payload(app, patch_root, target_dir, game)

        # The creator's game and the shareable EXE now consume the SAME payload.
        destination, backup = app.apply_patch_to_game(patch_root, game, target_dir)

        old_output = getattr(app, "output_zip", None)
        placeholder = output_dir / f"{game_name}TL.zip"
        app.output_zip = placeholder
        try:
            # Bypass RenPyToolsV055.build_standalone_patch here because that
            # override finalizes again. The payload is already final and must not
            # change after local apply; package it byte-for-byte as it stands.
            built = Path(core.PatcherApp.build_standalone_patch(app, patch_root, target_dir))
        finally:
            app.output_zip = old_output

        final_exe = merge.next_available(output_dir / f"{game_name}TL.exe")
        if final_exe.exists():
            final_exe.unlink()
        built.replace(final_exe)

    return {
        "exe": final_exe,
        "destination": destination,
        "backup": backup,
        "translations": len(combined["translations"]),
        "files": len(combined["used"]),
        "verified_files": combined["verified_files"],
    }


def install_v0514_hq_payload_sync():
    global _INSTALLED
    # RenPyToolsV0510._merge_rows resolves this module global at call time.
    launcher0510.merge_apply_and_build_exe = merge_apply_and_build_exe_v0514
    _INSTALLED = True
    return True


def run_v0514_self_test():
    try:
        install_v0514_hq_payload_sync()
        assert launcher0510.merge_apply_and_build_exe is merge_apply_and_build_exe_v0514

        # Regression guard for the exact v0.5.11/v0.5.13 bug: finalization must
        # occur before local apply, and standalone packaging must use the base
        # packager so it cannot mutate the payload after local installation.
        src = inspect.getsource(merge_apply_and_build_exe_v0514)
        finalize_at = src.index("_finalize_hq_payload")
        apply_at = src.index("app.apply_patch_to_game")
        package_at = src.index("core.PatcherApp.build_standalone_patch")
        assert finalize_at < apply_at < package_at

        with tempfile.TemporaryDirectory() as td:
            patch = Path(td) / "patch"
            (patch / PATCH_FONT_DIR).mkdir(parents=True)
            (patch / PATCH_FONT_DIR / BUNDLED_FONT_NAME).write_bytes(b"font")
            (patch / "renpytools_font_compat.rpy").write_text("ok", encoding="utf-8")
            (patch / "renpytools_choice_compat.rpy").write_text("ok", encoding="utf-8")
            assert all(p.is_file() for p in (
                patch / PATCH_FONT_DIR / BUNDLED_FONT_NAME,
                patch / "renpytools_font_compat.rpy",
                patch / "renpytools_choice_compat.rpy",
            ))
        return 0
    except Exception as exc:
        try:
            Path("RenPyTools-v0514-selftest-error.txt").write_text(repr(exc), encoding="utf-8")
        except Exception:
            pass
        return 1
