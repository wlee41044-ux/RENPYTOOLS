#!/usr/bin/env python3
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

import v043_features as hq
from v044_smart_picker import downloads_root, shared_storage_candidates

TRANSLATED_DIR = "번역완료"
PACKAGE_NAME = "AI_작업패키지.zip"
GUIDE_NAME = "AI_반자동_사용법.txt"
COMBINED_NAME = "RenPyTools_Combined_Translation.json"

# RenPy Tools safety profiles for v0.4.6. These are intentionally below
# theoretical model limits, but much larger than v0.4.3's overly conservative
# 5.5k~18.5k character chunks. Character count is the primary limiter.
V046_AI_CATALOG = {
    "ChatGPT": {
        "Free": {
            "기본 (GPT-5.6 Luna)": (1200, 25000),
            "Think (GPT-5.6 Luna)": (1500, 35000),
        },
        "Go": {
            "기본 (GPT-5.6 Luna)": (1500, 35000),
            "Think (GPT-5.6 Luna)": (1800, 45000),
        },
        "Plus": {
            "Instant (GPT-5.6 Sol)": (2000, 50000),
            "Medium (GPT-5.6 Sol)": (2500, 65000),
            "High (GPT-5.6 Sol)": (3000, 80000),
        },
        "Pro": {
            "Instant (GPT-5.6 Sol)": (2500, 65000),
            "Medium (GPT-5.6 Sol)": (3000, 80000),
            "High (GPT-5.6 Sol)": (3500, 95000),
            "Extra High (GPT-5.6 Sol)": (4000, 110000),
            "Pro (GPT-5.6 Sol Pro)": (4500, 120000),
        },
        "Business": {
            "Instant (GPT-5.6 Sol)": (2500, 65000),
            "Medium (GPT-5.6 Sol)": (3000, 80000),
            "High (GPT-5.6 Sol)": (3500, 95000),
            "Extra High (GPT-5.6 Sol)": (4000, 110000),
            "Pro (GPT-5.6 Sol Pro)": (4500, 120000),
        },
        "Enterprise": {
            "Instant (GPT-5.6 Sol)": (2500, 65000),
            "Medium (GPT-5.6 Sol)": (3000, 80000),
            "High (GPT-5.6 Sol)": (3500, 95000),
            "Extra High (GPT-5.6 Sol)": (4000, 110000),
            "Pro (GPT-5.6 Sol Pro)": (4500, 120000),
        },
        "잘 모르겠어요": {"자동 추천": (1000, 22000)},
    },
    "Gemini": {
        "무료": {"자동 추천": (1400, 32000), "직접 선택": (1400, 32000)},
        "유료": {"자동 추천": (2800, 70000), "직접 선택": (2800, 70000)},
        "잘 모르겠어요": {"자동 추천": (1100, 25000)},
    },
    "Claude": {
        "무료": {"자동 추천": (1300, 30000), "직접 선택": (1300, 30000)},
        "유료": {"자동 추천": (2600, 65000), "직접 선택": (2600, 65000)},
        "잘 모르겠어요": {"자동 추천": (1100, 25000)},
    },
    "기타 AI": {
        "잘 모르겠어요": {"자동 추천": (1000, 22000), "직접 설정": (1000, 22000)},
    },
}


def apply_v046_profiles():
    """Mutate the shared catalog object so existing v0.4.3 UI/functions use v0.4.6 limits."""
    hq.AI_CATALOG.clear()
    hq.AI_CATALOG.update(V046_AI_CATALOG)
    return hq.AI_CATALOG


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _chunk_map(workspace):
    workspace = Path(workspace)
    manifest = _read_json(workspace / "manifest.json")
    return manifest, {int(row["file"].split("_")[1].split(".")[0]): row["file"] for row in manifest.get("chunks", [])}


def relay_guide_text(manifest):
    service = manifest.get("service", "AI")
    plan = manifest.get("plan", "")
    model = manifest.get("model", "")
    count = len(manifest.get("chunks", []))
    return (
        "RenPy Tools 반자동 고품질 번역\n\n"
        f"선택한 AI: {service} / {plan} / {model}\n"
        f"전체 작업 파일: {count}개\n\n"
        "[처음 한 번만]\n"
        "1. 이 ZIP 파일을 AI 채팅에 첨부하세요.\n"
        "2. 아래 문장을 함께 보내세요.\n\n"
        "이 ZIP은 RenPy Tools 번역 작업입니다. chunk_001.json부터 번호 순서대로 처리하세요. "
        "사용자가 '다음'이라고 할 때마다 아직 처리하지 않은 가장 앞 번호의 chunk 파일 딱 1개만 번역하세요. "
        "각 items의 id/source/context와 JSON 구조는 절대 바꾸지 말고 translation 필드만 목표 언어로 채우세요. "
        "{...}, [...] 같은 Ren'Py 토큰은 그대로 보존하세요. 번역 완료 후 원래 chunk 파일명 그대로 JSON 파일로 반환하세요. "
        "설명문보다 파일 반환을 우선하고, 파일을 준 뒤에는 다음 작업을 위해 '다음이라고 보내주세요'라고 짧게 안내하세요.\n\n"
        "[그 다음부터]\n"
        "3. AI가 준 JSON 파일을 휴대폰 Downloads에 저장하세요.\n"
        "4. RenPy Tools가 자동으로 번역 파일을 감지합니다.\n"
        "5. 감지되면 같은 AI 대화에 '다음'만 보내세요.\n"
        "6. 모든 파일이 끝나면 RenPy Tools가 자동 조합할 수 있습니다.\n"
    )


def create_relay_package(workspace):
    """Create one ZIP that the user uploads to the AI only once."""
    workspace = Path(workspace)
    manifest = _read_json(workspace / "manifest.json")
    guide = relay_guide_text(manifest)
    (workspace / GUIDE_NAME).write_text(guide, encoding="utf-8")
    translated = workspace / TRANSLATED_DIR
    translated.mkdir(parents=True, exist_ok=True)

    package = workspace / PACKAGE_NAME
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(workspace / "manifest.json", "manifest.json")
        zf.write(workspace / GUIDE_NAME, GUIDE_NAME)
        for row in manifest.get("chunks", []):
            path = workspace / row.get("file", "")
            if path.is_file():
                zf.write(path, path.name)
    return package


def _validate_translated_chunk(workspace, candidate):
    workspace = Path(workspace)
    candidate = Path(candidate)
    try:
        data = _read_json(candidate)
    except Exception:
        return None
    if data.get("format") != hq.HQ_FORMAT:
        return None
    try:
        chunk_no = int(data.get("chunk"))
    except Exception:
        return None

    manifest, chunk_files = _chunk_map(workspace)
    source_name = chunk_files.get(chunk_no)
    if not source_name:
        return None
    source_path = workspace / source_name
    try:
        source_data = _read_json(source_path)
    except Exception:
        return None

    source_items = source_data.get("items", [])
    result_items = data.get("items", [])
    if len(source_items) != len(result_items) or not result_items:
        return None
    for src, dst in zip(source_items, result_items):
        if src.get("id") != dst.get("id") or src.get("source") != dst.get("source"):
            return None
        translated = dst.get("translation")
        if not isinstance(translated, str) or not translated.strip():
            return None
    return chunk_no, source_name, data


def _candidate_roots(preferred_path=None):
    roots = []
    try:
        roots.append(downloads_root(preferred_path))
    except Exception:
        pass
    try:
        roots.extend(shared_storage_candidates())
    except Exception:
        pass
    out, seen = [], set()
    for root in roots:
        try:
            key = str(Path(root).resolve()).lower()
        except Exception:
            key = str(root).lower()
        if key in seen or not Path(root).is_dir():
            continue
        seen.add(key)
        out.append(Path(root))
    return out


def scan_downloaded_translations(workspace, preferred_path=None, roots=None):
    """Find completed chunk JSONs in Downloads and copy validated files into the workspace."""
    workspace = Path(workspace)
    translated_dir = workspace / TRANSLATED_DIR
    translated_dir.mkdir(parents=True, exist_ok=True)
    roots = list(roots) if roots is not None else _candidate_roots(preferred_path)
    imported = []

    try:
        workspace_key = str(workspace.resolve()).lower()
    except Exception:
        workspace_key = str(workspace).lower()

    candidates = []
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        try:
            # Phone browsers normally save directly in Download. Also inspect one
            # child level for browsers that create their own download directory.
            candidates.extend(root.glob("*.json"))
            for child in root.iterdir():
                if child.is_dir() and child.name.lower() not in {"renpytools", "android"}:
                    candidates.extend(child.glob("*.json"))
        except Exception:
            continue

    # Newest first so a re-downloaded corrected file wins.
    def mtime(path):
        try:
            return path.stat().st_mtime
        except Exception:
            return 0

    for candidate in sorted(set(candidates), key=mtime, reverse=True):
        try:
            candidate_key = str(candidate.resolve()).lower()
        except Exception:
            candidate_key = str(candidate).lower()
        if candidate_key.startswith(workspace_key):
            continue
        valid = _validate_translated_chunk(workspace, candidate)
        if not valid:
            continue
        chunk_no, source_name, _ = valid
        dest = translated_dir / source_name
        try:
            if dest.exists() and dest.stat().st_mtime >= candidate.stat().st_mtime:
                continue
        except Exception:
            pass
        shutil.copy2(candidate, dest)
        imported.append((chunk_no, dest))
    return sorted(imported)


def relay_status(workspace):
    workspace = Path(workspace)
    manifest, chunk_files = _chunk_map(workspace)
    translated_dir = workspace / TRANSLATED_DIR
    translated_dir.mkdir(parents=True, exist_ok=True)
    completed = []
    for chunk_no, filename in sorted(chunk_files.items()):
        path = translated_dir / filename
        if path.is_file() and _validate_translated_chunk(workspace, path):
            completed.append(chunk_no)
    total = len(chunk_files)
    missing = [n for n in sorted(chunk_files) if n not in set(completed)]
    next_no = missing[0] if missing else None
    percent = int(len(completed) / max(total, 1) * 100)
    return {
        "total": total,
        "completed": len(completed),
        "percent": percent,
        "next": next_no,
        "next_file": chunk_files.get(next_no) if next_no else None,
        "done": total > 0 and len(completed) == total,
        "translated_files": [str(translated_dir / chunk_files[n]) for n in completed],
    }


def run_v046_self_test():
    try:
        apply_v046_profiles()
        assert hq.hq_limits_for("ChatGPT", "Plus", "High (GPT-5.6 Sol)")["max_chars"] >= 80000
        assert hq.hq_limits_for("ChatGPT", "Free", "기본 (GPT-5.6 Luna)")["max_chars"] >= 25000

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = root / "workspace"
            workspace.mkdir()
            items1 = [{"id": "RT0000001", "source": "Hello", "translation": "", "context": {}}]
            items2 = [{"id": "RT0000002", "source": "World", "translation": "", "context": {}}]
            for index, items in [(1, items1), (2, items2)]:
                (workspace / f"chunk_{index:03d}.json").write_text(json.dumps({
                    "format": hq.HQ_FORMAT, "chunk": index, "chunk_count": 2, "items": items,
                }, ensure_ascii=False), encoding="utf-8")
            manifest = {
                "format": hq.HQ_FORMAT,
                "service": "ChatGPT", "plan": "Plus", "model": "High (GPT-5.6 Sol)",
                "chunks": [
                    {"file": "chunk_001.json", "ids": ["RT0000001"]},
                    {"file": "chunk_002.json", "ids": ["RT0000002"]},
                ],
            }
            (workspace / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            package = create_relay_package(workspace)
            assert package.is_file()
            with zipfile.ZipFile(package) as zf:
                assert "chunk_001.json" in zf.namelist() and GUIDE_NAME in zf.namelist()

            downloads = root / "Download"
            downloads.mkdir()
            translated = {
                "format": hq.HQ_FORMAT,
                "chunk": 1,
                "chunk_count": 2,
                "items": [{"id": "RT0000001", "source": "Hello", "translation": "안녕", "context": {}}],
            }
            (downloads / "chunk_001.json").write_text(json.dumps(translated, ensure_ascii=False), encoding="utf-8")
            imported = scan_downloaded_translations(workspace, roots=[downloads])
            assert len(imported) == 1
            state = relay_status(workspace)
            assert state["completed"] == 1 and state["next"] == 2 and not state["done"]
        return 0
    except Exception as exc:
        try:
            Path("RenPyTools-v046-selftest-error.txt").write_text(repr(exc), encoding="utf-8")
        except Exception:
            pass
        return 1
