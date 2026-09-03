#!/usr/bin/env python3
import ctypes
import json
import os
import re
import tempfile
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk

SCRIPT_OR_ARCHIVE_EXTS = {".rpy", ".rpyc", ".rpym", ".rpymc", ".rpa", ".rpi"}
SKIP_SCAN_DIRS = {
    "android", "dcim", "pictures", "movies", "music", "documents", "obb", "data",
    "windows", "program files", "program files (x86)", "$recycle.bin", "system volume information",
    "renpytools", "renpytools_output", "renpytools_highquality",
}
DOWNLOAD_NAMES = {"download", "downloads"}


def _is_dir(path):
    try:
        return os.path.isdir(str(path))
    except Exception:
        return False


def _norm_key(path):
    try:
        return os.path.normcase(os.path.abspath(str(path)))
    except Exception:
        return str(path).lower()


def _appdata_dir():
    base = os.getenv("APPDATA") or os.getenv("LOCALAPPDATA")
    if base:
        root = Path(base) / "RenPyTools"
    else:
        root = Path.home() / ".renpytools"
    try:
        root.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return root


def _remember_file():
    return _appdata_dir() / "picker_roots.json"


def _download_ancestor(path):
    """Return an existing Download/Downloads ancestor of a selected game."""
    if not path:
        return None
    try:
        current = Path(path)
        if current.name.lower() == "game":
            current = current.parent
        for candidate in (current, *current.parents):
            if candidate.name.lower() in DOWNLOAD_NAMES and _is_dir(candidate):
                return candidate
    except Exception:
        pass
    return None


def remember_game_path(path):
    """Remember the real shared-storage root selected through Wine's file dialog."""
    if not path:
        return
    selected = Path(path)
    root = _download_ancestor(selected)
    if root is None:
        # Even when the game is not inside Downloads, remembering its parent makes
        # the next smart scan useful without walking an entire Android filesystem.
        root = selected.parent if selected.name.lower() == "game" else selected.parent
    if not _is_dir(root):
        return
    rows = []
    try:
        rows = json.loads(_remember_file().read_text("utf-8"))
        if not isinstance(rows, list):
            rows = []
    except Exception:
        rows = []
    value = str(root)
    rows = [x for x in rows if _norm_key(x) != _norm_key(value)]
    rows.insert(0, value)
    rows = rows[:8]
    try:
        _remember_file().write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def remembered_roots():
    try:
        rows = json.loads(_remember_file().read_text("utf-8"))
    except Exception:
        rows = []
    out = []
    if isinstance(rows, list):
        for value in rows:
            path = Path(str(value))
            if _is_dir(path):
                out.append(path)
    return out


def _logical_drives():
    """Enumerate Wine/Windows drive letters without assuming only C: and D:."""
    out = []
    if os.name == "nt":
        try:
            mask = ctypes.windll.kernel32.GetLogicalDrives()
            for index in range(26):
                if mask & (1 << index):
                    out.append(Path(f"{chr(65 + index)}:\\"))
        except Exception:
            pass
    # Wine can occasionally omit a mapped drive from GetLogicalDrives while it
    # is still reachable through the shell. Probe the common shared letters too.
    for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
        candidate = Path(f"{letter}:\\")
        if _is_dir(candidate) and all(_norm_key(candidate) != _norm_key(x) for x in out):
            out.append(candidate)
    return out


def shared_storage_candidates():
    """Possible Android/Winlator shared Download roots, best candidates first."""
    raw = [
        Path(r"D:\Download"),
        Path(r"D:\Downloads"),
        Path(r"Z:\storage\emulated\0\Download"),
        Path(r"Z:\storage\emulated\0\Downloads"),
        Path(r"Z:\storage\self\primary\Download"),
        Path(r"Z:\sdcard\Download"),
        Path(r"Z:\mnt\sdcard\Download"),
    ]

    # Any non-C Wine drive may be mapped directly to Android internal storage,
    # or may contain a Download directory one level below it.
    for drive in _logical_drives():
        if str(drive).upper().startswith("C:"):
            continue
        raw.extend([drive / "Download", drive / "Downloads", drive])

    profile = os.getenv("USERPROFILE")
    raw.extend([Path.home() / "Downloads", Path.home() / "Download"])
    if profile:
        raw.extend([Path(profile) / "Downloads", Path(profile) / "Download"])

    out, seen = [], set()
    for candidate in [*remembered_roots(), *raw]:
        key = _norm_key(candidate)
        if key in seen:
            continue
        seen.add(key)
        if _is_dir(candidate):
            out.append(candidate)
    return out


def downloads_root(preferred_path=None):
    """Choose Android shared Downloads when possible; Windows Downloads is fallback."""
    preferred = _download_ancestor(preferred_path)
    if preferred is not None:
        return preferred

    candidates = shared_storage_candidates()
    # Prefer an actual folder named Download/Downloads outside C:.
    for candidate in candidates:
        drive = str(candidate.drive or "").upper()
        if candidate.name.lower() in DOWNLOAD_NAMES and drive != "C:":
            return candidate
    # A mapped non-C drive can itself be the Android shared Download directory.
    for candidate in candidates:
        drive = str(candidate.drive or "").upper()
        if drive and drive != "C:" and candidate == Path(candidate.anchor):
            return candidate
    for candidate in candidates:
        if candidate.name.lower() in DOWNLOAD_NAMES:
            return candidate

    fallback = Path.home() / "Downloads"
    try:
        fallback.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return fallback


def safe_folder_name(name):
    cleaned = re.sub(r'[<>:"/\\|?*]+', "_", str(name)).strip(" .")
    return cleaned or "RenPyGame"


def hq_workspace_for(game_path, stamp):
    root = Path(game_path)
    game_dir = root if root.name.lower() == "game" else root / "game"
    game_name = game_dir.parent.name if game_dir.name.lower() == "game" else root.name
    # Important for Winlator: use the Download ancestor of the game the user
    # actually selected before trying Windows' C:\Users\...\Downloads.
    base = downloads_root(game_path) / "RenPyTools" / "고품질번역" / safe_folder_name(game_name)
    workspace = base / stamp
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def _game_folder(candidate):
    candidate = Path(candidate)
    if candidate.name.lower() == "game" and _is_dir(candidate):
        return candidate
    game = candidate / "game"
    if _is_dir(game):
        return game
    return None


def _has_renpy_payload(game):
    try:
        with os.scandir(game) as entries:
            for entry in entries:
                if entry.is_file(follow_symlinks=False) and Path(entry.name).suffix.lower() in SCRIPT_OR_ARCHIVE_EXTS:
                    return True
                if entry.is_dir(follow_symlinks=False) and entry.name.lower() in {"tl", "python-packages"}:
                    return True
    except Exception:
        return False

    # Some games keep scripts one level below game/. Keep this bounded.
    try:
        count = 0
        with os.scandir(game) as entries:
            for child in entries:
                if not child.is_dir(follow_symlinks=False):
                    continue
                count += 1
                if count > 160:
                    break
                try:
                    sub_count = 0
                    with os.scandir(child.path) as sub_entries:
                        for sub in sub_entries:
                            sub_count += 1
                            if sub_count > 160:
                                break
                            if sub.is_file(follow_symlinks=False) and Path(sub.name).suffix.lower() in SCRIPT_OR_ARCHIVE_EXTS:
                                return True
                except Exception:
                    continue
    except Exception:
        pass
    return False


def is_renpy_game(candidate):
    game = _game_folder(candidate)
    if game and _has_renpy_payload(game):
        return True
    # Fallback signature for unusual distributions: Ren'Py runtime + game dir.
    try:
        root = Path(candidate)
        game = root / "game"
        renpy = root / "renpy"
        if _is_dir(game) and _is_dir(renpy):
            with os.scandir(root) as entries:
                return any(e.is_file(follow_symlinks=False) and e.name.lower().endswith(".exe") for e in entries)
    except Exception:
        pass
    return False


def _scan_root(root, max_depth=2, max_dirs=4000):
    root = Path(root)
    if not _is_dir(root):
        return []

    results = []
    queue = [(root, 0)]
    visited = 0
    while queue and visited < max_dirs:
        current, depth = queue.pop(0)
        visited += 1
        try:
            game = _game_folder(current)
            if game and ( _has_renpy_payload(game) or is_renpy_game(current) ):
                results.append(game.parent)
                continue
            if depth >= max_depth:
                continue
            with os.scandir(current) as entries:
                for entry in entries:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    if entry.name.lower() in SKIP_SCAN_DIRS:
                        continue
                    queue.append((Path(entry.path), depth + 1))
        except Exception:
            continue
    return results


def discovery_roots():
    out, seen = [], set()
    for root in shared_storage_candidates():
        key = _norm_key(root)
        if key in seen:
            continue
        seen.add(key)
        if _is_dir(root):
            out.append(root)
    return out


def _scan_depth(root):
    name = root.name.lower()
    if name in DOWNLOAD_NAMES:
        return 4
    try:
        if root == Path(root.anchor) and str(root.drive).upper() != "C:":
            return 3
    except Exception:
        pass
    return 2


def find_renpy_games():
    found = []
    seen = set()
    for root in discovery_roots():
        for game_root in _scan_root(root, max_depth=_scan_depth(root)):
            key = _norm_key(game_root)
            if key in seen:
                continue
            seen.add(key)
            found.append(game_root)
    return sorted(found, key=lambda p: p.name.lower())


def choose_renpy_game(parent, title="Ren'Py 게임 선택"):
    """Modal smart picker. Returns a game root path or None."""
    win = tk.Toplevel(parent)
    win.title(title)
    win.geometry("920x560")
    win.minsize(760, 460)
    win.transient(parent)
    win.grab_set()

    selected = {"path": None}
    status = tk.StringVar(value="Ren'Py 게임을 찾고 있어요...")

    wrap = ttk.Frame(win, padding=18)
    wrap.pack(fill="both", expand=True)
    ttk.Label(wrap, text="찾은 Ren'Py 게임", style="Title.TLabel").pack(anchor="w")
    ttk.Label(
        wrap,
        text="Winlator 공유 저장소와 Downloads 주변을 확인해서 Ren'Py 게임만 보여줘요.",
        style="Subtitle.TLabel",
    ).pack(anchor="w", pady=(3, 12))

    tree = ttk.Treeview(wrap, columns=("name", "path"), show="headings", height=14)
    tree.heading("name", text="게임")
    tree.heading("path", text="위치")
    tree.column("name", width=250, anchor="w")
    tree.column("path", width=610, anchor="w")
    tree.pack(fill="both", expand=True)

    ttk.Label(wrap, textvariable=status, style="Subtitle.TLabel").pack(anchor="w", pady=(8, 0))
    buttons = ttk.Frame(wrap)
    buttons.pack(fill="x", pady=(12, 0))

    def close_with(path):
        if path:
            remember_game_path(path)
            selected["path"] = str(path)
        try:
            win.grab_release()
        except Exception:
            pass
        win.destroy()

    def choose_selected(*_):
        focus = tree.focus()
        if not focus:
            return
        values = tree.item(focus, "values")
        if len(values) >= 2:
            close_with(values[1])

    def browse():
        initial = None
        roots = discovery_roots()
        if roots:
            initial = str(roots[0])
        kwargs = {"title": "Ren'Py 게임 폴더 직접 선택", "parent": win}
        if initial:
            kwargs["initialdir"] = initial
        path = filedialog.askdirectory(**kwargs)
        if path:
            close_with(path)

    def apply_results(games, roots):
        if not win.winfo_exists():
            return
        for item in tree.get_children():
            tree.delete(item)
        for path in games:
            tree.insert("", "end", values=(path.name or "RenPy Game", str(path)))
        if games:
            first = tree.get_children()[0]
            tree.selection_set(first)
            tree.focus(first)
            status.set(f"Ren'Py 게임 {len(games)}개를 찾았어요.")
        else:
            shown = ", ".join(str(x) for x in roots[:3])
            if shown:
                status.set(f"게임을 못 찾았어요 · 확인 위치: {shown}")
            else:
                status.set("공유 저장소를 찾지 못했어요. '직접 찾아보기'로 한 번 선택하면 다음부터 기억해요.")

    def scan():
        status.set("Winlator 공유 저장소에서 Ren'Py 게임을 찾고 있어요...")
        def job():
            roots = discovery_roots()
            games = find_renpy_games()
            try:
                parent.after(0, lambda g=games, r=roots: apply_results(g, r))
            except Exception:
                pass
        threading.Thread(target=job, daemon=True, name="renpy-smart-picker").start()

    ttk.Button(buttons, text="다시 찾기", command=scan).pack(side="left")
    ttk.Button(buttons, text="직접 찾아보기", command=browse).pack(side="left", padx=(8, 0))
    ttk.Button(buttons, text="취소", command=lambda: close_with(None)).pack(side="right")
    ttk.Button(buttons, text="이 게임 선택", style="Primary.TButton", command=choose_selected).pack(side="right", padx=(0, 8))

    tree.bind("<Double-1>", choose_selected)
    win.protocol("WM_DELETE_WINDOW", lambda: close_with(None))
    scan()
    parent.wait_window(win)
    return selected["path"]


def run_v044_picker_self_test():
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            download = root / "Download"
            demo = download / "DemoGame"
            game = demo / "game"
            game.mkdir(parents=True)
            (game / "archive.rpa").write_bytes(b"demo")
            assert is_renpy_game(demo)
            assert not is_renpy_game(root / "Missing")
            assert _download_ancestor(demo) == download
            workspace = hq_workspace_for(demo, "test")
            # On the test runner the selected game's Download ancestor must win
            # over C:\Users\...\Downloads exactly like it should in Winlator.
            assert _norm_key(download) in _norm_key(workspace)
            name = safe_folder_name('A:B?C*')
            assert ":" not in name and "?" not in name and "*" not in name
        return 0
    except Exception:
        return 1
