#!/usr/bin/env python3
import tempfile
import zipfile
from pathlib import Path

import RenPyToolsLauncherV055 as launcher055

_INSTALLED = False


def repack_existing_zip_safe(owner, patch_root):
    """Repack only the legacy <work>/game/tl/<lang> layout.

    HQ manual merge builds its payload in a temporary folder such as
    <temp>/tmpXXXX/patch.  The old v0.5.5 helper blindly used parents[2] as the
    ZIP root, which turns that path into the shared system Temp directory and
    recursively scans/compresses unrelated temporary files. Under Winlator that
    can take minutes even for a few hundred translated lines.
    """
    output = getattr(owner, "output_zip", None)
    if not output:
        return None

    patch_root = Path(patch_root)
    # Expected legacy layout: <work>/game/tl/<language>
    if patch_root.parent.name.lower() != "tl":
        return None
    game_dir = patch_root.parent.parent
    if game_dir.name.lower() != "game":
        return None
    temp_root = game_dir.parent
    if not temp_root.is_dir():
        return None

    # Defensive check: the derived work root must actually contain the supplied
    # patch directory in the exact legacy location before recursive packaging.
    try:
        expected = (temp_root / "game" / "tl" / patch_root.name).resolve()
        if expected != patch_root.resolve():
            return None
    except Exception:
        return None

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for path in temp_root.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(temp_root))
    return output


def install_v0511_merge_speedfix():
    global _INSTALLED
    # RenPyToolsV055.build_standalone_patch resolves this name in the
    # RenPyToolsLauncherV055 module at runtime.
    launcher055.repack_existing_zip = repack_existing_zip_safe
    _INSTALLED = True
    return True


def run_v0511_self_test():
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            class Dummy:
                output_zip = None

            owner = Dummy()

            # HQ merge layout must be skipped immediately. In v0.5.10 this was
            # the path that accidentally caused a scan of the shared Temp folder.
            hq_patch = root / "shared_temp" / "tmp123" / "patch"
            hq_patch.mkdir(parents=True)
            (hq_patch / "renpytools_strings.rpy").write_text("test", encoding="utf-8")
            owner.output_zip = root / "hq_should_not_exist.zip"
            assert repack_existing_zip_safe(owner, hq_patch) is None
            assert not owner.output_zip.exists()

            # Legacy quick-translation layout still repacks normally.
            legacy_patch = root / "work" / "game" / "tl" / "korean"
            legacy_patch.mkdir(parents=True)
            (legacy_patch / "script.rpy").write_text("translate korean strings:\n", encoding="utf-8")
            owner.output_zip = root / "legacy.zip"
            result = repack_existing_zip_safe(owner, legacy_patch)
            assert result == owner.output_zip and owner.output_zip.is_file()
            with zipfile.ZipFile(owner.output_zip, "r") as zf:
                assert "game/tl/korean/script.rpy" in zf.namelist()

            install_v0511_merge_speedfix()
            assert launcher055.repack_existing_zip is repack_existing_zip_safe
        return 0
    except Exception as exc:
        try:
            Path("RenPyTools-v0511-selftest-error.txt").write_text(repr(exc), encoding="utf-8")
        except Exception:
            pass
        return 1
