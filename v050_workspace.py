#!/usr/bin/env python3
import tempfile
from pathlib import Path

from v044_smart_picker import downloads_root, safe_folder_name


def hq_workspace_for_v050(game_path, stamp):
    """Create an easy-to-find HQ translation workspace directly in Downloads.

    Example:
        Download/AfterClass TL.RENPY/20260903_231500/

    Keeping the timestamp one level below the game-named folder avoids overwriting
    older work while making the folder immediately recognizable on Android.
    """
    root = Path(game_path)
    game_dir = root if root.name.lower() == "game" else root / "game"
    game_name = game_dir.parent.name if game_dir.name.lower() == "game" else root.name
    folder_name = f"{safe_folder_name(game_name)} TL.RENPY"
    workspace = downloads_root(game_path) / folder_name / str(stamp)
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def run_v050_workspace_self_test():
    try:
        with tempfile.TemporaryDirectory() as td:
            download = Path(td) / "Download"
            game_root = download / "Demo Game"
            (game_root / "game").mkdir(parents=True)
            workspace = hq_workspace_for_v050(game_root, "20260903_230000")
            assert workspace.parent.name == "Demo Game TL.RENPY"
            assert workspace.name == "20260903_230000"
            assert workspace.parent.parent == download
        return 0
    except Exception:
        return 1
