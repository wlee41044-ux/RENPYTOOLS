#!/usr/bin/env python3
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import RenPyAIPatcher as core
from RenPyAIPatcher import (
    PatcherApp,
    LANGS,
    SOURCE_CODES,
    PROVIDERS,
    collect_rpy,
    extract_strings,
    escape_rpy,
)
from ui_common import card

UI_VERSION = "0.4.0"
HQ_FORMAT = "renpytools-hq-v1"
COMBINED_FORMAT = "renpytools-combined-v1"
HQ_PROFILES = {
    "ChatGPT (안전)": {"max_items": 350, "max_chars": 14000},
    "Gemini (안전)": {"max_items": 450, "max_chars": 18000},
    "Claude (안전)": {"max_items": 400, "max_chars": 16000},
    "기타 AI (매우 안전)": {"max_items": 250, "max_chars": 10000},
}


def _norm(path):
    try:
        return str(Path(path).resolve()).lower()
    except Exception:
        return str(path).lower()


def build_hq_chunks(source_path, output_dir, profile_name, target_lang="한국어"):
    """Prepare conservative JSON chunks for manual high-quality AI translation."""
    source_path = Path(source_path)
    output_dir = Path(output_dir)
    game_root, files = collect_rpy(source_path)
    profile = HQ_PROFILES.get(profile_name, HQ_PROFILES["기타 AI (매우 안전)"])
    max_items = profile["max_items"]
    max_chars = profile["max_chars"]

    rows = []
    file_groups = {}
    seen = {}
    next_id = 1
    for file in files:
        try:
            rel = file.relative_to(game_root).as_posix()
        except Exception:
            rel = file.name
        ids = []
        for line_no, text in extract_strings(file):
            if text not in seen:
                item_id = f"RT{next_id:07d}"
                next_id += 1
                seen[text] = item_id
                rows.append({
                    "id": item_id,
                    "source": text,
                    "file": rel,
                    "line": line_no,
                })
            ids.append(seen[text])
        file_groups[rel] = list(dict.fromkeys(ids))

    if not rows:
        raise RuntimeError("번역할 문장을 찾지 못했습니다.")

    output_dir.mkdir(parents=True, exist_ok=True)
    instruction = (
        "이 파일은 RenPy Tools가 만든 번역 작업 파일입니다. "
        "items의 id와 source는 절대 수정/삭제/재정렬하지 말고 translation 필드만 목표 언어로 번역해 채우세요. "
        "{...}, [...] 같은 Ren'Py 토큰은 원문 그대로 보존하세요. "
        "설명문을 추가하지 말고 유효한 JSON 파일 형식을 그대로 반환하세요."
    )

    chunks = []
    current, chars = [], 0
    for row in rows:
        cost = len(row["source"]) + 64
        if current and (len(current) >= max_items or chars + cost > max_chars):
            chunks.append(current)
            current, chars = [], 0
        current.append(row)
        chars += cost
    if current:
        chunks.append(current)

    manifest_chunks = []
    for index, chunk in enumerate(chunks, 1):
        name = f"chunk_{index:03d}.json"
        payload = {
            "format": HQ_FORMAT,
            "chunk": index,
            "chunk_count": len(chunks),
            "profile": profile_name,
            "target_lang": target_lang,
            "instructions": instruction,
            "items": [
                {
                    "id": row["id"],
                    "source": row["source"],
                    "translation": "",
                    "context": {"file": row["file"], "line": row["line"]},
                }
                for row in chunk
            ],
        }
        (output_dir / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest_chunks.append({"file": name, "ids": [r["id"] for r in chunk]})

    manifest = {
        "format": HQ_FORMAT,
        "created_at": time.time(),
        "source_path": str(source_path.resolve()),
        "game_root": str(game_root.resolve()),
        "target_lang": target_lang,
        "profile": profile_name,
        "total": len(rows),
        "chunks": manifest_chunks,
        "file_groups": file_groups,
        "sources": {r["id"]: r["source"] for r in rows},
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "AI에게_보내는법.txt").write_text(
        "1. chunk_001.json부터 AI 채팅에 하나씩 첨부하세요.\n"
        "2. 파일 안의 instructions를 따르도록 번역시키세요. 별도 프롬프트가 필요하면 '파일 안의 지시대로 번역해줘' 한 줄이면 됩니다.\n"
        "3. AI가 돌려준 JSON 파일을 이 폴더에 저장하세요. 원본 chunk 파일은 백업해두는 것을 권장합니다.\n"
        "4. RenPy Tools의 '조합하기'에서 manifest.json과 번역된 chunk 파일들을 선택하세요.\n",
        encoding="utf-8",
    )
    return manifest


def combine_hq_chunks(manifest_path, translated_files, output_path):
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text("utf-8"))
    if manifest.get("format") != HQ_FORMAT:
        raise RuntimeError("RenPy Tools 고품질 번역 manifest.json이 아닙니다.")

    expected = manifest.get("sources", {})
    translations = {}
    seen_files = 0
    errors = []
    for path in map(Path, translated_files):
        if path.name.lower() == "manifest.json":
            continue
        try:
            data = json.loads(path.read_text("utf-8"))
        except Exception as exc:
            errors.append(f"{path.name}: JSON 읽기 실패 ({exc})")
            continue
        if data.get("format") != HQ_FORMAT or not isinstance(data.get("items"), list):
            continue
        seen_files += 1
        for item in data["items"]:
            item_id = str(item.get("id", ""))
            source = item.get("source", "")
            translated = str(item.get("translation", "") or "").strip()
            if item_id not in expected:
                errors.append(f"{path.name}: 알 수 없는 ID {item_id}")
                continue
            if source != expected[item_id]:
                errors.append(f"{path.name}: {item_id} 원문이 변경됨")
                continue
            if translated:
                translations[item_id] = translated

    missing = [item_id for item_id in expected if item_id not in translations]
    if seen_files == 0:
        raise RuntimeError("번역된 chunk JSON 파일을 찾지 못했습니다.")
    if errors:
        raise RuntimeError("파일 검사 실패:\n" + "\n".join(errors[:12]))
    if missing:
        raise RuntimeError(
            f"아직 번역되지 않은 문장이 {len(missing)}개 있습니다. "
            f"예: {', '.join(missing[:5])}"
        )

    combined = {
        "format": COMBINED_FORMAT,
        "created_at": time.time(),
        "source_path": manifest.get("source_path", ""),
        "target_lang": manifest.get("target_lang", "한국어"),
        "file_groups": manifest.get("file_groups", {}),
        "sources": expected,
        "translations": translations,
    }
    output_path = Path(output_path)
    output_path.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")
    return combined


class RenPyToolsApp(PatcherApp):
    def __init__(self):
        self.route = "home"
        self.flow_step = 0
        self._history_file_groups = {}
        self._selected_history_path = None
        self.hq_profile = tk.StringVar(value="ChatGPT (안전)")
        self.hq_workspace = None
        self.hq_manifest = None
        super().__init__()
        self.title(f"RenPy Tools {UI_VERSION}")
        self.geometry("1180x760")
        self.minsize(900, 620)
        self._extend_styles()
        self.render()

    def _extend_styles(self):
        style = ttk.Style(self)
        style.configure("HomeTitle.TLabel", font=("Segoe UI Semibold", 26), foreground="#10213F")
        style.configure("HeroTitle.TLabel", font=("Segoe UI Semibold", 18), foreground="#10213F")
        style.configure("HeroSub.TLabel", font=("Segoe UI", 10), foreground="#66738A")
        style.configure("Blue.TLabel", font=("Segoe UI Semibold", 10), foreground="#2869F0")
        style.configure("Big.TButton", font=("Segoe UI Semibold", 12), padding=(18, 14))
        style.configure("Danger.TButton", font=("Segoe UI Semibold", 10), padding=(14, 10))

    def clear(self):
        for w in self.container.winfo_children():
            w.destroy()

    def render(self):
        self.clear()
        route = getattr(self, "route", "home")
        routes = {
            "home": self.page_home,
            "quick_select": self.page_quick_select,
            "quick_progress": self.page_quick_progress,
            "quick_done": self.page_quick_done,
            "hq_select": self.page_hq_select,
            "hq_ready": self.page_hq_ready,
            "update_select": self.page_update_select,
            "update_confirm": self.page_update_confirm,
            "history": self.page_history,
            "history_detail": self.page_history_detail,
            "combine": self.page_combine,
            "patch": self.page_patch,
            "settings": self.page_settings,
            "photo": self.page_photo,
        }
        routes.get(route, self.page_home)()

    def nav_home(self):
        self.route = "home"
        self.render()

    def topbar(self, title=None, subtitle=None, back=True):
        top = ttk.Frame(self.container)
        top.pack(fill="x", pady=(0, 16))
        if back:
            ttk.Button(top, text="‹  홈", style="Secondary.TButton", command=self.nav_home).pack(side="left")
        ttk.Label(top, text="RenPy Tools", style="Title.TLabel").pack(side="left", padx=(12 if back else 0, 0))
        ttk.Label(top, text=f"v{UI_VERSION}", style="Subtitle.TLabel").pack(side="left", padx=(8, 0), pady=(5, 0))
        if title:
            ttk.Label(self.container, text=title, style="HomeTitle.TLabel").pack(anchor="w")
        if subtitle:
            ttk.Label(self.container, text=subtitle, style="Subtitle.TLabel").pack(anchor="w", pady=(4, 16))

    def flow_header(self, active):
        self.topbar(back=True)
        labels = ["게임 찾기", "파일 준비", "번역 진행", "번역 상세", "완료"]
        wrap = ttk.Frame(self.container)
        wrap.pack(fill="x", pady=(0, 18))
        for i, label in enumerate(labels, 1):
            cell = ttk.Frame(wrap)
            cell.grid(row=0, column=i-1, sticky="ew")
            wrap.columnconfigure(i-1, weight=1)
            circle = tk.Label(
                cell, text=str(i), width=2, height=1,
                bg=("#2F7AF8" if i == active else "#EEF3FA"),
                fg=("white" if i == active else "#778399"),
                font=("Segoe UI Semibold", 10),
            )
            circle.pack()
            ttk.Label(cell, text=label, style=("Blue.TLabel" if i == active else "Step.TLabel")).pack(pady=(4, 0))

    def _menu_card(self, parent, title, desc, command, accent="#EAF2FF", badge=None):
        outer = tk.Frame(parent, bg="#DCE5F2")
        body = tk.Frame(outer, bg="white", padx=20, pady=18)
        body.pack(fill="both", expand=True, padx=1, pady=1)
        head = tk.Frame(body, bg="white")
        head.pack(fill="x")
        tk.Label(head, text=title, bg="white", fg="#10213F",
                 font=("Segoe UI Semibold", 15)).pack(side="left")
        if badge:
            tk.Label(head, text=badge, bg=accent, fg="#2869F0",
                     font=("Segoe UI Semibold", 9), padx=8, pady=3).pack(side="left", padx=(8, 0))
        tk.Label(body, text=desc, bg="white", fg="#66738A",
                 font=("Segoe UI", 9), justify="left", wraplength=420).pack(anchor="w", pady=(7, 12))
        ttk.Button(body, text="열기  ›", style="Secondary.TButton", command=command).pack(anchor="e")
        return outer

    def page_home(self):
        self.topbar(back=False)
        ttk.Label(self.container, text="무엇을 할까요?", style="HomeTitle.TLabel").pack(anchor="w")
        ttk.Label(
            self.container,
            text="빠르게 시작하거나, 원하는 AI로 더 정교하게 번역할 수 있어요.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(4, 18))

        hero = ttk.Frame(self.container)
        hero.pack(fill="x")
        c1 = self._menu_card(hero, "간편 번역", "게임을 선택하면 기본 설정으로 번역부터 패치까지 자동으로 끝냅니다.",
                             lambda: self._go("quick_select"), "#EAF2FF", "가장 추천")
        c1.pack(side="left", fill="both", expand=True, padx=(0, 8))
        c2 = self._menu_card(hero, "고품질 번역", "게임 파일을 AI에 보내기 좋은 크기로 나눠줍니다. 번역본은 다시 조합해 패치할 수 있어요.",
                             lambda: self._go("hq_select"), "#F1ECFF", "원하는 AI 사용")
        c2.pack(side="left", fill="both", expand=True, padx=(8, 0))

        grid = ttk.Frame(self.container)
        grid.pack(fill="both", expand=True, pady=(16, 0))
        items = [
            ("번역 업데이트", "게임이 업데이트됐거나 기존 번역이 구버전일 때 새 문장만 이어서 번역합니다.", "update_select"),
            ("번역 기록", "게임별 번역 기록을 열고 문장을 수정하거나 패치 파일로 배포합니다.", "history"),
            ("조합하기", "고품질 번역에서 AI가 번역한 조각 파일을 검사하고 하나로 합칩니다.", "combine"),
            ("패치 적용", "완성된 번역 파일을 선택한 Ren'Py 게임에 자동으로 적용합니다.", "patch"),
            ("사진 번역", "게임 로고·배경 이미지의 글자를 번역하는 기능입니다.", "photo"),
            ("세부 설정", "기존 번역 엔진, 언어, 동시 처리 수 등 간편 모드 기본 설정을 조정합니다.", "settings"),
        ]
        for idx, (title, desc, route) in enumerate(items):
            row, col = divmod(idx, 3)
            grid.rowconfigure(row, weight=1)
            grid.columnconfigure(col, weight=1)
            item = self._menu_card(
                grid, title, desc, lambda r=route: self._go(r),
                badge=("개발 중" if route == "photo" else None),
            )
            item.grid(row=row, column=col, sticky="nsew", padx=6, pady=6)

    def _go(self, route):
        self.route = route
        self.render()

    def _select_game_folder(self, next_route=None):
        path = filedialog.askdirectory(title="Ren'Py 게임 폴더 선택")
        if not path:
            return False
        try:
            root, files = collect_rpy(Path(path))
            count = sum(len(extract_strings(x)) for x in files)
        except Exception as exc:
            messagebox.showerror("RenPy Tools", str(exc))
            return False
        self.source_path.set(path)
        self.scan.set(f"번역 준비 완료 · RPY/RPYM {len(files)}개 · 번역 후보 {count}개")
        self._build_file_groups(Path(path))
        if next_route:
            self.route = next_route
            self.render()
        return True

    def _build_file_groups(self, path):
        groups = {}
        try:
            root, files = collect_rpy(path)
            for file in files:
                rel = file.relative_to(root).as_posix()
                groups[rel] = [text for _, text in extract_strings(file)]
        except Exception:
            groups = {}
        self._history_file_groups = groups
        return groups

    def page_quick_select(self):
        self.flow_header(1)
        ttk.Label(self.container, text="간편 번역", style="HomeTitle.TLabel").pack(anchor="center")
        ttk.Label(self.container, text="게임만 선택하면 나머지는 기본 설정으로 자동 처리해요.", style="Subtitle.TLabel").pack(anchor="center", pady=(4, 20))
        outer, body = card(self.container, padding=26)
        outer.pack(fill="x", padx=80)
        ttk.Label(body, text="번역할 Ren'Py 게임을 선택하세요", style="Section.TLabel").pack(anchor="center")
        ttk.Label(body, text="game 폴더가 있는 게임 최상위 폴더를 선택하면 가장 안정적이에요.", style="Muted.Card.TLabel").pack(anchor="center", pady=(5, 16))
        ttk.Button(body, text="게임 선택", style="Big.TButton", command=self.start_quick_from_picker).pack()
        ttk.Label(body, textvariable=self.scan, style="Muted.Card.TLabel").pack(anchor="center", pady=(14, 0))

    def start_quick_from_picker(self):
        if not self._select_game_folder():
            return
        self.start_quick_translation()

    def _automatic_output(self, source_path, suffix="patch"):
        root = Path(source_path)
        game = self.resolve_game_for_apply(root, reject_decompiled=False)
        base = game.parent if game else root
        out_dir = base / "RenPyTools_Output"
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir / f"RenPy_korean_{suffix}.zip"

    def start_quick_translation(self):
        source = self.source_path.get()
        try:
            collect_rpy(Path(source))
        except Exception as exc:
            messagebox.showerror("RenPy Tools", str(exc))
            return
        apply_game = self.resolve_game_for_apply(source, reject_decompiled=False)
        if apply_game is None:
            messagebox.showerror("RenPy Tools", "선택한 폴더에서 원본 game 폴더를 찾지 못했습니다.")
            return

        self.source_lang.set("자동 감지")
        self.target_lang.set("한국어")
        if not self.provider.get():
            self.provider.set("무료 자동 선택 (추천)")
        workers = max(1, min(4, int(self.google_workers.get() or 3)))
        self.output_zip = self._automatic_output(source)
        self.job_options = {
            "source_path": source,
            "source_lang": self.source_lang.get(),
            "target_lang": self.target_lang.get(),
            "provider": self.provider.get(),
            "google_workers": workers,
            "base_url": "",
            "model": "",
            "auto_apply": True,
            "apply_game_path": str(apply_game),
        }
        self.route = "quick_progress"
        self.page = 3
        self.render()
        threading.Thread(target=self.worker, daemon=True).start()

    def page_quick_progress(self):
        self.flow_header(3)
        ttk.Label(self.container, text="번역 진행 중", style="HomeTitle.TLabel").pack(anchor="center")
        ttk.Label(self.container, textvariable=self.status, style="Subtitle.TLabel").pack(anchor="center", pady=(4, 16))
        outer, body = card(self.container, padding=28)
        outer.pack(fill="x", padx=60)
        ttk.Label(body, text="번역 진행도", style="Section.TLabel").pack(anchor="w")
        self.bar = ttk.Progressbar(body, mode="determinate")
        self.bar.pack(fill="x", pady=(14, 4))
        self.percent = ttk.Label(body, text="0%", style="Blue.TLabel")
        self.percent.pack(anchor="e")
        actions = ttk.Frame(body, style="Card.TFrame")
        actions.pack(fill="x", pady=(14, 0))
        self.details = ttk.Button(actions, text="번역 자세히 보기", style="Secondary.TButton", command=self.toggle_log)
        self.details.pack(side="left")
        ttk.Button(actions, text="번역 기록", style="Secondary.TButton", command=lambda: self._go("history")).pack(side="left", padx=(8, 0))
        self.log = tk.Text(body, height=13, wrap="word", state="disabled", relief="flat", bg="#F8FAFD")
        self.log_visible = False
        placeholder, pbody = card(self.container, padding=18)
        placeholder.pack(fill="x", padx=60, pady=(16, 0))
        ttk.Label(pbody, text="기다리는 동안 할 수 있는 게임", style="Section.TLabel").pack(anchor="w")
        ttk.Label(pbody, text="번역 중 기다리는 시간에 할 수 있는 작은 게임을 추후 추가할 예정이에요.", style="Muted.Card.TLabel").pack(anchor="w", pady=(4, 0))

    def finish(self):
        self.route = "quick_done"
        self.page = 4
        self.render()

    def page_quick_done(self):
        self.flow_header(5)
        ttk.Label(self.container, text="번역이 끝났어요!", style="HomeTitle.TLabel").pack(anchor="center")
        outer, body = card(self.container, padding=28)
        outer.pack(fill="x", padx=100, pady=(18, 0))
        ttk.Label(body, text="✓ 한글패치 적용 완료", style="Section.TLabel").pack(anchor="center")
        ttk.Label(body, text=f"처리한 번역 후보 {getattr(self, 'result', 0)}개", style="Muted.Card.TLabel").pack(anchor="center", pady=(6, 0))
        if getattr(self, "applied_path", None):
            ttk.Label(body, text=str(self.applied_path), style="Muted.Card.TLabel").pack(anchor="center", pady=(8, 0))
        ttk.Button(body, text="홈으로", style="Big.TButton", command=self.nav_home).pack(pady=(18, 0))

    def page_hq_select(self):
        self.flow_header(1)
        ttk.Label(self.container, text="고품질 번역", style="HomeTitle.TLabel").pack(anchor="center")
        ttk.Label(self.container, text="게임을 준비한 뒤 원하는 AI에 맞춰 안전한 크기로 나눠드려요.", style="Subtitle.TLabel").pack(anchor="center", pady=(4, 18))
        outer, body = card(self.container, padding=24)
        outer.pack(fill="x", padx=100)
        ttk.Label(body, text="사용할 AI", style="Section.TLabel").pack(anchor="w")
        ttk.Combobox(body, textvariable=self.hq_profile, values=list(HQ_PROFILES), state="readonly").pack(fill="x", pady=(8, 14))
        ttk.Button(body, text="게임 선택하고 파일 준비하기", style="Big.TButton", command=self.prepare_hq_from_picker).pack(anchor="center")
        ttk.Label(body, text="파일 분할은 모델 한도보다 보수적으로 잡습니다.", style="Muted.Card.TLabel").pack(anchor="center", pady=(10, 0))

    def prepare_hq_from_picker(self):
        if not self._select_game_folder():
            return
        path = Path(self.source_path.get())
        game = self.resolve_game_for_apply(path, reject_decompiled=False)
        base = game.parent if game else path
        root = base / "RenPyTools_HighQuality"
        stamp = time.strftime("%Y%m%d_%H%M%S")
        workspace = root / stamp
        try:
            self.hq_manifest = build_hq_chunks(path, workspace, self.hq_profile.get(), self.target_lang.get())
        except Exception as exc:
            messagebox.showerror("RenPy Tools", f"고품질 번역 파일 준비 실패\n\n{exc}")
            return
        self.hq_workspace = workspace
        self.route = "hq_ready"
        self.render()

    def page_hq_ready(self):
        self.flow_header(2)
        ttk.Label(self.container, text="파일 준비가 끝났어요", style="HomeTitle.TLabel").pack(anchor="center")
        ttk.Label(self.container, text="이제 AI에 조각 파일을 하나씩 보내 번역받으면 돼요.", style="Subtitle.TLabel").pack(anchor="center", pady=(4, 16))
        outer, body = card(self.container, padding=24)
        outer.pack(fill="both", expand=True, padx=70)
        steps = [
            "1. 폴더의 chunk_001.json부터 AI 채팅에 첨부하세요.",
            "2. 파일 자체에 번역 지시문이 들어 있어요. 필요하면 '파일 안의 지시대로 번역해줘'라고만 보내세요.",
            "3. 번역된 JSON을 저장하세요. 모든 조각을 번역할 때까지 반복하세요.",
            "4. 메인 화면의 '조합하기'에서 manifest.json과 번역된 조각 파일을 불러오세요.",
        ]
        for text in steps:
            ttk.Label(body, text=text, style="Card.TLabel").pack(anchor="w", pady=8)
        if self.hq_workspace:
            ttk.Label(body, text=f"작업 폴더: {self.hq_workspace}", style="Muted.Card.TLabel").pack(anchor="w", pady=(14, 8))
        row = ttk.Frame(body, style="Card.TFrame")
        row.pack(fill="x", pady=(10, 0))
        ttk.Button(row, text="작업 폴더 열기", style="Primary.TButton", command=self.open_hq_workspace).pack(side="left")
        ttk.Button(row, text="조합하기로 이동", style="Secondary.TButton", command=lambda: self._go("combine")).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="홈으로", style="Secondary.TButton", command=self.nav_home).pack(side="right")

    def open_hq_workspace(self):
        if not self.hq_workspace:
            return
        try:
            os.startfile(str(self.hq_workspace))
        except Exception:
            messagebox.showinfo("RenPy Tools", str(self.hq_workspace))

    def page_combine(self):
        self.topbar("조합하기", "AI가 번역한 조각들을 검사하고 하나의 완성된 번역 파일로 합칩니다.")
        outer, body = card(self.container, padding=24)
        outer.pack(fill="x", padx=80)
        ttk.Label(body, text="1. 원본 manifest.json을 선택하세요", style="Section.TLabel").pack(anchor="w")
        ttk.Label(body, text="2. AI가 번역한 chunk JSON 파일들을 모두 선택하세요", style="Card.TLabel").pack(anchor="w", pady=(12, 4))
        ttk.Button(body, text="번역 파일 조합하기", style="Big.TButton", command=self.combine_picker).pack(anchor="center", pady=(18, 0))

    def combine_picker(self):
        manifest = filedialog.askopenfilename(title="manifest.json 선택", filetypes=[("JSON", "*.json")])
        if not manifest:
            return
        chunks = filedialog.askopenfilenames(title="번역된 chunk JSON 파일 선택", filetypes=[("JSON", "*.json")])
        if not chunks:
            return
        output = filedialog.asksaveasfilename(
            title="완성 번역 파일 저장",
            defaultextension=".json",
            initialfile="RenPyTools_Combined_Translation.json",
            filetypes=[("JSON", "*.json")],
        )
        if not output:
            return
        try:
            combined = combine_hq_chunks(manifest, chunks, output)
        except Exception as exc:
            messagebox.showerror("RenPy Tools", str(exc))
            return
        messagebox.showinfo("RenPy Tools", f"조합 완료!\n번역 문장 {len(combined['translations'])}개\n\n{output}")

    def page_patch(self):
        self.topbar("패치 적용", "완성된 번역 파일을 선택한 Ren'Py 게임에 적용합니다.")
        outer, body = card(self.container, padding=24)
        outer.pack(fill="x", padx=80)
        ttk.Label(body, text="완성 번역 JSON 또는 RenPy Tools 패치 ZIP을 사용할 수 있어요.", style="Section.TLabel").pack(anchor="w")
        ttk.Label(body, text="원본 게임은 자동으로 백업한 뒤 패치를 적용합니다.", style="Muted.Card.TLabel").pack(anchor="w", pady=(5, 18))
        ttk.Button(body, text="번역 파일 선택하고 패치하기", style="Big.TButton", command=self.patch_picker).pack(anchor="center")

    def patch_picker(self):
        source = filedialog.askopenfilename(
            title="완성 번역 파일 선택",
            filetypes=[("RenPy Tools 번역", "*.json *.zip"), ("JSON", "*.json"), ("ZIP", "*.zip")],
        )
        if not source:
            return
        game_root = filedialog.askdirectory(title="패치할 Ren'Py 게임 폴더 선택")
        if not game_root:
            return
        game = self.resolve_game_for_apply(game_root, reject_decompiled=False)
        if game is None:
            messagebox.showerror("RenPy Tools", "선택한 폴더에서 game 폴더를 찾지 못했습니다.")
            return
        try:
            if str(source).lower().endswith(".json"):
                self.apply_combined_json(Path(source), game)
            else:
                self.apply_patch_zip(Path(source), game)
        except Exception as exc:
            messagebox.showerror("RenPy Tools", f"패치 실패\n\n{exc}")
            return
        messagebox.showinfo("RenPy Tools", "패치가 적용됐어요!")

    def apply_combined_json(self, source, game):
        data = json.loads(Path(source).read_text("utf-8"))
        if data.get("format") != COMBINED_FORMAT:
            raise RuntimeError("RenPy Tools에서 조합한 번역 JSON이 아닙니다.")
        target_lang = data.get("target_lang", "한국어")
        target_dir = LANGS.get(target_lang, LANGS["한국어"])[0]
        sources = data.get("sources", {})
        translations = data.get("translations", {})
        with tempfile.TemporaryDirectory() as td:
            patch_root = Path(td) / target_dir
            patch_root.mkdir(parents=True)
            lines = [
                "# Generated by RenPy Tools high-quality mode",
                f"translate {target_dir} strings:",
                "",
            ]
            for item_id, old in sources.items():
                new = translations.get(item_id, old)
                lines.extend([f'    old "{escape_rpy(old)}"', f'    new "{escape_rpy(new)}"', ""])
            (patch_root / "renpytools_strings.rpy").write_text("\n".join(lines), encoding="utf-8")
            self.apply_patch_to_game(patch_root, game, target_dir)

    def apply_patch_zip(self, source, game):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with zipfile.ZipFile(source, "r") as zf:
                zf.extractall(root)
            candidates = list(root.glob("game/tl/*"))
            if not candidates:
                raise RuntimeError("ZIP 안에서 game/tl/<언어> 패치를 찾지 못했습니다.")
            patch_root = candidates[0]
            target_dir = patch_root.name
            self.apply_patch_to_game(patch_root, game, target_dir)

    def page_update_select(self):
        self.topbar("번역 업데이트", "게임 업데이트 후 새로 생긴 문장만 이어서 번역하고 자동 패치합니다.")
        outer, body = card(self.container, padding=24)
        outer.pack(fill="x", padx=80)
        ttk.Button(body, text="업데이트할 게임 선택", style="Big.TButton", command=self.find_update_history).pack(anchor="center")

    def find_update_history(self):
        if not self._select_game_folder():
            return
        selected = _norm(self.source_path.get())
        matches = []
        for path, data in self.list_history_files():
            sig = data.get("signature", {})
            if _norm(sig.get("source_path", "")) == selected:
                matches.append((path, data))
        if not matches:
            messagebox.showinfo("RenPy Tools", "이 게임의 이전 번역 기록을 찾지 못했어요.")
            return
        self._selected_history_path, self._selected_history = matches[0]
        self.route = "update_confirm"
        self.render()

    def page_update_confirm(self):
        self.topbar("구버전 번역 기록을 찾았어요", "기존 번역은 재사용하고 새 문장만 번역합니다.")
        data = getattr(self, "_selected_history", {})
        outer, body = card(self.container, padding=24)
        outer.pack(fill="x", padx=80)
        ttk.Label(body, text=f"기존 번역: {len(data.get('translations', {}))}문장", style="Section.TLabel").pack(anchor="w")
        ttk.Label(body, text="완료 후 원본 게임에 자동으로 패치합니다.", style="Muted.Card.TLabel").pack(anchor="w", pady=(5, 18))
        ttk.Button(body, text="업데이트 시작", style="Big.TButton", command=self.start_update_translation).pack(anchor="center")

    def start_update_translation(self):
        data = getattr(self, "_selected_history", {})
        sig = data.get("signature", {})
        if sig.get("source_lang") in SOURCE_CODES:
            self.source_lang.set(sig["source_lang"])
        if sig.get("target_lang") in LANGS:
            self.target_lang.set(sig["target_lang"])
        if sig.get("provider") in PROVIDERS:
            self.provider.set(sig["provider"])
        self.start_quick_translation()

    def save_state(self, options, sources, memory, failures, total, completed=False, force=False):
        super().save_state(options, sources, memory, failures, total, completed=completed, force=force)
        if completed and self._history_file_groups:
            try:
                hp = self.history_path(options)
                data = self.load_json(hp)
                data["file_groups"] = self._history_file_groups
                tmp = hp.with_suffix(".tmp")
                tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                os.replace(tmp, hp)
            except Exception:
                pass

    def page_history(self):
        self.topbar("번역 기록", "게임별 기록을 열어 번역문을 수정하거나 배포할 수 있어요.")
        rows = self.list_history_files()
        if not rows:
            ttk.Label(self.container, text="아직 저장된 번역 기록이 없어요.", style="Subtitle.TLabel").pack(anchor="center", pady=80)
            return
        holder = ttk.Frame(self.container)
        holder.pack(fill="both", expand=True)
        for path, data in rows[:12]:
            sig = data.get("signature", {})
            name = Path(sig.get("source_path", "게임")).name or "게임"
            outer, body = card(holder, padding=14)
            outer.pack(fill="x", pady=5)
            ttk.Label(body, text=name, style="Section.TLabel").pack(side="left")
            ttk.Label(body, text=f"번역 {len(data.get('translations', {}))}/{data.get('total', 0)}", style="Muted.Card.TLabel").pack(side="left", padx=(12, 0))
            ttk.Button(body, text="열기", style="Secondary.TButton",
                       command=lambda p=path: self.open_history_detail(p)).pack(side="right")

    def open_history_detail(self, path):
        self._selected_history_path = Path(path)
        self.route = "history_detail"
        self.render()

    def page_history_detail(self):
        path = self._selected_history_path
        data = self.load_json(path) if path else {}
        sig = data.get("signature", {})
        self.topbar(Path(sig.get("source_path", "번역 기록")).name, "파일별 번역을 확인하고 번역문을 직접 수정할 수 있어요.")
        top = ttk.Frame(self.container)
        top.pack(fill="x", pady=(0, 10))
        file_groups = data.get("file_groups", {})
        files = ["전체"] + sorted(file_groups)
        selected_file = tk.StringVar(value="전체")
        combo = ttk.Combobox(top, textvariable=selected_file, values=files, state="readonly", width=50)
        combo.pack(side="left")
        ttk.Button(top, text="파일 배포하기", style="Primary.TButton",
                   command=lambda: self.export_history_patch(path)).pack(side="right")

        columns = ("source", "translation")
        tree = ttk.Treeview(self.container, columns=columns, show="headings")
        tree.heading("source", text="원문")
        tree.heading("translation", text="번역문")
        tree.column("source", width=500)
        tree.column("translation", width=500)
        tree.pack(fill="both", expand=True)

        def refresh(*_):
            for row in tree.get_children():
                tree.delete(row)
            sources = data.get("sources", [])
            if selected_file.get() != "전체":
                allowed = set(file_groups.get(selected_file.get(), []))
                sources = [s for s in sources if s in allowed]
            translations = data.get("translations", {})
            for src in sources:
                tree.insert("", "end", values=(src, translations.get(src, "")))
        combo.bind("<<ComboboxSelected>>", refresh)

        def edit(_event=None):
            item = tree.focus()
            if not item:
                return
            src, old = tree.item(item, "values")
            new = simpledialog.askstring("번역 수정", f"원문:\n{src}\n\n번역문:", initialvalue=old, parent=self)
            if new is None:
                return
            data.setdefault("translations", {})[src] = new
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tree.item(item, values=(src, new))
        tree.bind("<Double-1>", edit)
        ttk.Label(self.container, text="번역문을 더블클릭하면 수정할 수 있어요.", style="Subtitle.TLabel").pack(anchor="w", pady=(8, 0))
        refresh()

    def export_history_patch(self, history_path):
        data = self.load_json(Path(history_path))
        sig = data.get("signature", {})
        target_lang = sig.get("target_lang", "한국어")
        target_dir = LANGS.get(target_lang, LANGS["한국어"])[0]
        output = filedialog.asksaveasfilename(
            title="패치 ZIP 배포",
            defaultextension=".zip",
            initialfile=f"RenPy_{target_dir}_patch.zip",
            filetypes=[("ZIP", "*.zip")],
        )
        if not output:
            return
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            patch = root / "game" / "tl" / target_dir
            patch.mkdir(parents=True)
            lines = ["# Exported by RenPy Tools", f"translate {target_dir} strings:", ""]
            translations = data.get("translations", {})
            for old in data.get("sources", []):
                new = translations.get(old, old)
                lines.extend([f'    old "{escape_rpy(old)}"', f'    new "{escape_rpy(new)}"', ""])
            (patch / "renpytools_strings.rpy").write_text("\n".join(lines), encoding="utf-8")
            (root / "game" / "renpytools_language.rpy").write_text(
                "init 999 python:\n"
                f"    config.language = {target_dir!r}\n",
                encoding="utf-8",
            )
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
                for file in root.rglob("*"):
                    if file.is_file():
                        zf.write(file, file.relative_to(root))
        messagebox.showinfo("RenPy Tools", f"배포용 패치를 만들었어요.\n\n{output}")

    def page_settings(self):
        self.topbar("세부 설정", "간편 번역의 기본 설정입니다. 건드리지 않아도 기본값으로 잘 작동해요.")
        wrap = ttk.Frame(self.container)
        wrap.pack(fill="x")
        lo, left = card(wrap)
        lo.pack(side="left", fill="both", expand=True, padx=(0, 8))
        ro, right = card(wrap)
        ro.pack(side="left", fill="both", expand=True, padx=(8, 0))
        ttk.Label(left, text="번역 옵션", style="Section.TLabel").pack(anchor="w", pady=(0, 10))
        self.combo_row(left, "원본 언어", self.source_lang, list(SOURCE_CODES))
        self.combo_row(left, "번역 언어", self.target_lang, list(LANGS))
        self.combo_row(left, "번역 방식", self.provider, PROVIDERS)
        ttk.Label(left, text="Google 동시 요청 수", style="Card.TLabel").pack(anchor="w", pady=(9, 3))
        ttk.Spinbox(left, from_=1, to=4, textvariable=self.google_workers, width=8).pack(anchor="w")
        ttk.Checkbutton(left, variable=self.auto_apply, text="번역 완료 후 자동 패치 적용").pack(anchor="w", pady=(12, 0))
        ttk.Label(right, text="기존 설정 유지", style="Section.TLabel").pack(anchor="w")
        ttk.Label(right, text="v0.3.7에서 사용하던 무료 번역 엔진과 설정을 그대로 사용합니다.", style="Muted.Card.TLabel").pack(anchor="w", pady=(8, 0))
        ttk.Label(right, text="간편 번역은 이 화면을 열지 않아도 현재 기본값으로 바로 시작합니다.", style="Muted.Card.TLabel").pack(anchor="w", pady=(8, 0))
        ttk.Button(self.container, text="설정 저장하고 홈으로", style="Primary.TButton", command=self.nav_home).pack(anchor="e", pady=(18, 0))

    def page_photo(self):
        self.topbar("사진 번역", "게임 로고와 배경 이미지까지 번역하는 기능을 준비하고 있어요.")
        outer, body = card(self.container, padding=36)
        outer.pack(fill="x", padx=100)
        ttk.Label(body, text="현재 개발 중", style="HeroTitle.TLabel").pack(anchor="center")
        ttk.Label(body, text="OCR → 원문 제거 → 배경 복원 → 번역문 배치 흐름으로 추가할 예정이에요.", style="Muted.Card.TLabel").pack(anchor="center", pady=(8, 0))


def run_ui_self_test():
    try:
        assert core.run_self_test() == 0
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            game_root = root / "Demo"
            game = game_root / "game"
            game.mkdir(parents=True)
            (game / "script.rpy").write_text(
                'label start:\n    "Hello [name]"\n    "Good morning"\n',
                encoding="utf-8",
            )
            workspace = root / "hq"
            manifest = build_hq_chunks(game_root, workspace, "기타 AI (매우 안전)")
            assert manifest["total"] == 2
            translated_files = []
            for chunk_meta in manifest["chunks"]:
                p = workspace / chunk_meta["file"]
                data = json.loads(p.read_text("utf-8"))
                for item in data["items"]:
                    item["translation"] = "번역:" + item["source"]
                out = workspace / ("translated_" + p.name)
                out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                translated_files.append(out)
            combined_path = root / "combined.json"
            combined = combine_hq_chunks(workspace / "manifest.json", translated_files, combined_path)
            assert len(combined["translations"]) == 2
        return 0
    except Exception as exc:
        try:
            Path("RenPyToolsUI-selftest-error.txt").write_text(repr(exc), encoding="utf-8")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_ui_self_test())
    RenPyToolsApp().mainloop()
