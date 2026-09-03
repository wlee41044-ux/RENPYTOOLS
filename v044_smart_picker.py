#!/usr/bin/env python3
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


def downloads_root():
    """Return the most useful Downloads folder for Winlator first, Windows second."""
    candidates = [
        Path("D:/Download"),
        Path("D:/Downloads"),
        Path.home() / "Downloads",
        Path.home() / "Download",
    ]
    profile = os.getenv("USERPROFILE")
    if profile:
        candidates.extend([Path(profile) / "Downloads", Path(profile) / "Download"])

    seen = set()
    for candidate in candidates:
        key = str(candidate).lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            if candidate.is_dir():
                return candidate
        except Exception:
            pass

    fallback = Path.home() / "Downloads"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def safe_folder_name(name):
    cleaned = re.sub(r'[<>:"/\\|?*]+', "_", str(name)).strip(" .")
    return cleaned or "RenPyGame"


def hq_workspace_for(game_path, stamp):
    root = Path(game_path)
    game_dir = root if root.name.lower() == "game" else root / "game"
    game_name = game_dir.parent.name if game_dir.name.lower() == "game" else root.name
    base = downloads_root() / "RenPyTools" / "고품질번역" / safe_folder_name(game_name)
    workspace = base / stamp
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def _game_folder(candidate):
    candidate = Path(candidate)
    if candidate.name.lower() == "game" and candidate.is_dir():
        return candidate
    game = candidate / "game"
    if game.is_dir():
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
        for child in list(Path(game).iterdir())[:120]:
            if not child.is_dir():
                continue
            try:
                for sub in list(child.iterdir())[:120]:
                    if sub.is_file() and sub.suffix.lower() in SCRIPT_OR_ARCHIVE_EXTS:
                        return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def is_renpy_game(candidate):
    game = _game_folder(candidate)
    return bool(game and _has_renpy_payload(game))


def _scan_root(root, max_depth=2, max_dirs=2500):
    root = Path(root)
    if not root.is_dir():
        return []

    results = []
    queue = [(root, 0)]
    visited = 0
    while queue and visited < max_dirs:
        current, depth = queue.pop(0)
        visited += 1
        try:
            game = _game_folder(current)
            if game and _has_renpy_payload(game):
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
    roots = [downloads_root(), Path("D:/Download"), Path("D:/Downloads")]
    # Add home only shallowly as a Windows fallback, without walking whole drives.
    roots.append(Path.home())
    out, seen = [], set()
    for root in roots:
        try:
            key = str(root.resolve()).lower()
        except Exception:
            key = str(root).lower()
        if key in seen:
            continue
        seen.add(key)
        if root.is_dir():
            out.append(root)
    return out


def find_renpy_games():
    found = []
    seen = set()
    for root in discovery_roots():
        depth = 3 if root == downloads_root() else 1
        for game_root in _scan_root(root, max_depth=depth):
            try:
                key = str(game_root.resolve()).lower()
            except Exception:
                key = str(game_root).lower()
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
        text="Downloads 주변을 빠르게 확인해서 Ren'Py 게임만 보여줘요. 목록에 없으면 직접 찾을 수 있어요.",
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
        path = filedialog.askdirectory(title="Ren'Py 게임 폴더 직접 선택", parent=win)
        if path:
            close_with(path)

    def apply_results(games):
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
            status.set("자동으로 찾은 게임이 없어요. '직접 찾아보기'를 사용할 수 있어요.")

    def scan():
        status.set("Ren'Py 게임을 찾고 있어요...")
        def job():
            games = find_renpy_games()
            try:
                parent.after(0, lambda g=games: apply_results(g))
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
            demo = root / "DemoGame"
            game = demo / "game"
            game.mkdir(parents=True)
            (game / "archive.rpa").write_bytes(b"demo")
            assert is_renpy_game(demo)
            assert not is_renpy_game(root / "Missing")
            name = safe_folder_name('A:B?C*')
            assert ":" not in name and "?" not in name and "*" not in name
        return 0
    except Exception:
        return 1
