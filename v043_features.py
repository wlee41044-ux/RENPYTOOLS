#!/usr/bin/env python3
import json
import tempfile
import time
from pathlib import Path

import RenPyAIPatcher as core
from fast_scan import collect_rpy_fast

HQ_FORMAT = "renpytools-hq-v1"
GOOGLE_BATCH_ITEMS = 70
GOOGLE_BATCH_CHARS = 3600

# These are RenPy Tools safety profiles, not claims about provider hard limits.
# The app deliberately stays well below theoretical context windows because
# long JSON translation jobs are more likely to omit rows or damage structure.
AI_CATALOG = {
    "ChatGPT": {
        "Free": {
            "기본 (GPT-5.6 Luna)": (150, 6500),
            "Think (GPT-5.6 Luna)": (170, 7500),
        },
        "Go": {
            "기본 (GPT-5.6 Luna)": (180, 8000),
            "Think (GPT-5.6 Luna)": (200, 9000),
        },
        "Plus": {
            "Instant (GPT-5.6 Sol)": (260, 11000),
            "Medium (GPT-5.6 Sol)": (300, 13000),
            "High (GPT-5.6 Sol)": (320, 14000),
        },
        "Pro": {
            "Instant (GPT-5.6 Sol)": (300, 13000),
            "Medium (GPT-5.6 Sol)": (340, 15000),
            "High (GPT-5.6 Sol)": (360, 16000),
            "Extra High (GPT-5.6 Sol)": (380, 17000),
            "Pro (GPT-5.6 Sol Pro)": (420, 18500),
        },
        "Business": {
            "Instant (GPT-5.6 Sol)": (300, 13000),
            "Medium (GPT-5.6 Sol)": (340, 15000),
            "High (GPT-5.6 Sol)": (360, 16000),
            "Extra High (GPT-5.6 Sol)": (380, 17000),
            "Pro (GPT-5.6 Sol Pro)": (420, 18500),
        },
        "Enterprise": {
            "Instant (GPT-5.6 Sol)": (300, 13000),
            "Medium (GPT-5.6 Sol)": (340, 15000),
            "High (GPT-5.6 Sol)": (360, 16000),
            "Extra High (GPT-5.6 Sol)": (380, 17000),
            "Pro (GPT-5.6 Sol Pro)": (420, 18500),
        },
        "잘 모르겠어요": {
            "자동 추천": (140, 6000),
        },
    },
    "Gemini": {
        "무료": {"자동 추천": (180, 8000), "직접 선택": (180, 8000)},
        "유료": {"자동 추천": (300, 13000), "직접 선택": (300, 13000)},
        "잘 모르겠어요": {"자동 추천": (150, 6500)},
    },
    "Claude": {
        "무료": {"자동 추천": (170, 7500), "직접 선택": (170, 7500)},
        "유료": {"자동 추천": (280, 12000), "직접 선택": (280, 12000)},
        "잘 모르겠어요": {"자동 추천": (150, 6500)},
    },
    "기타 AI": {
        "잘 모르겠어요": {"자동 추천": (130, 5500), "직접 설정": (130, 5500)},
    },
}


def plans_for(service):
    return list(AI_CATALOG.get(service, AI_CATALOG["기타 AI"]))


def models_for(service, plan):
    service_map = AI_CATALOG.get(service, AI_CATALOG["기타 AI"])
    if plan not in service_map:
        plan = next(iter(service_map))
    return list(service_map[plan])


def hq_limits_for(service, plan, model):
    service_map = AI_CATALOG.get(service, AI_CATALOG["기타 AI"])
    if plan not in service_map:
        plan = next(iter(service_map))
    model_map = service_map[plan]
    if model not in model_map:
        model = next(iter(model_map))
    max_items, max_chars = model_map[model]
    return {"max_items": max_items, "max_chars": max_chars}


def make_google_batches_v043(texts, max_items=GOOGLE_BATCH_ITEMS, max_chars=GOOGLE_BATCH_CHARS):
    """Use fewer Google requests while keeping room for separators/tokens."""
    batches, current, chars = [], [], 0
    for text in texts:
        cost = len(text) + 32
        if current and (len(current) >= max_items or chars + cost > max_chars):
            batches.append(current)
            current, chars = [], 0
        current.append(text)
        chars += cost
    if current:
        batches.append(current)
    return batches


def iter_extract_strings_stream(path):
    """Line-by-line extractor so one huge .rpy file is never loaded at once."""
    seen = set()
    with Path(path).open("r", encoding="utf-8", errors="replace") as fp:
        for no, line in enumerate(fp, 1):
            for match in core.STRING_RE.finditer(line):
                value = match.group("text")
                if core.looks_translatable(line, value) and value not in seen:
                    seen.add(value)
                    yield no, value


def build_hq_chunks_streaming(
    source_path,
    output_dir,
    service,
    plan,
    model,
    target_lang="한국어",
    status=None,
):
    """Create HQ chunks incrementally for large games/phones/Winlator."""
    source_path = Path(source_path)
    output_dir = Path(output_dir)
    game_root, files = collect_rpy_fast(source_path)
    limits = hq_limits_for(service, plan, model)
    max_items = limits["max_items"]
    max_chars = limits["max_chars"]
    output_dir.mkdir(parents=True, exist_ok=True)

    instruction = (
        "이 파일은 RenPy Tools가 만든 번역 작업 파일입니다. "
        "items의 id와 source는 절대 수정/삭제/재정렬하지 말고 translation 필드만 목표 언어로 번역해 채우세요. "
        "{...}, [...] 같은 Ren'Py 토큰은 원문 그대로 보존하세요. "
        "설명문을 추가하지 말고 유효한 JSON 파일 형식을 그대로 반환하세요."
    )

    seen = {}
    sources = {}
    file_groups = {}
    chunk_files = []
    current = []
    current_chars = 0
    next_id = 1

    def report(text):
        if status:
            try:
                status(text)
            except Exception:
                pass

    def flush_chunk():
        nonlocal current, current_chars
        if not current:
            return
        index = len(chunk_files) + 1
        name = f"chunk_{index:03d}.json"
        payload = {
            "format": HQ_FORMAT,
            "chunk": index,
            "chunk_count": 0,
            "service": service,
            "plan": plan,
            "model": model,
            "target_lang": target_lang,
            "profile_limits": limits,
            "instructions": instruction,
            "items": current,
        }
        (output_dir / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        chunk_files.append({"file": name, "ids": [item["id"] for item in current]})
        current = []
        current_chars = 0

    for file_index, file in enumerate(files, 1):
        try:
            rel = file.relative_to(game_root).as_posix()
        except Exception:
            rel = file.name
        ids = []
        report(f"파일을 쪼개고 있어요... {file_index}/{len(files)} · {rel}")
        for line_no, text in iter_extract_strings_stream(file):
            item_id = seen.get(text)
            if item_id is None:
                item_id = f"RT{next_id:07d}"
                next_id += 1
                seen[text] = item_id
                sources[item_id] = text
                cost = len(text) + 64
                if current and (len(current) >= max_items or current_chars + cost > max_chars):
                    flush_chunk()
                current.append({
                    "id": item_id,
                    "source": text,
                    "translation": "",
                    "context": {"file": rel, "line": line_no},
                })
                current_chars += cost
            ids.append(item_id)
        file_groups[rel] = list(dict.fromkeys(ids))

    flush_chunk()
    if not sources:
        raise RuntimeError("번역할 문장을 찾지 못했습니다.")

    chunk_count = len(chunk_files)
    for meta in chunk_files:
        path = output_dir / meta["file"]
        data = json.loads(path.read_text("utf-8"))
        data["chunk_count"] = chunk_count
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest = {
        "format": HQ_FORMAT,
        "created_at": time.time(),
        "source_path": str(source_path.resolve()),
        "game_root": str(game_root.resolve()),
        "target_lang": target_lang,
        "service": service,
        "plan": plan,
        "model": model,
        "profile_limits": limits,
        "total": len(sources),
        "chunks": chunk_files,
        "file_groups": file_groups,
        "sources": sources,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "AI에게_보내는법.txt").write_text(
        f"선택한 AI: {service} / {plan} / {model}\n"
        "1. chunk_001.json부터 AI 채팅에 하나씩 첨부하세요.\n"
        "2. 파일 안의 instructions를 따라 translation 필드만 번역하게 하세요.\n"
        "3. AI가 돌려준 JSON을 저장하세요.\n"
        "4. RenPy Tools의 조합하기에서 manifest.json과 번역된 chunk 파일을 선택하세요.\n",
        encoding="utf-8",
    )
    report(f"파일 준비 완료 · {len(sources)}문장 · {chunk_count}개 파일")
    return manifest


def history_metrics(data):
    total = int(data.get("total", len(data.get("sources", []))) or 0)
    success = len(data.get("translations", {}) if isinstance(data.get("translations"), dict) else {})
    failed = len(data.get("failures", {}) if isinstance(data.get("failures"), dict) else {})
    pending = max(total - success - failed, 0)
    percent = int(success / max(total, 1) * 100)
    return {"total": total, "success": success, "failed": failed, "pending": pending, "percent": percent}


def run_v043_self_test():
    try:
        small = ["x" * 20 for _ in range(140)]
        batches = make_google_batches_v043(small)
        assert len(batches) <= 3
        assert sum(len(x) for x in batches) == 140
        assert hq_limits_for("ChatGPT", "Free", "기본 (GPT-5.6 Luna)")["max_chars"] < hq_limits_for(
            "ChatGPT", "Pro", "Pro (GPT-5.6 Sol Pro)"
        )["max_chars"]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "Demo"
            game = root / "game"
            game.mkdir(parents=True)
            big = game / "script.rpy"
            with big.open("w", encoding="utf-8") as fp:
                fp.write("label start:\n")
                for i in range(900):
                    fp.write(f'    "Large game line {i}"\n')
            out = Path(td) / "hq"
            manifest = build_hq_chunks_streaming(
                root, out, "ChatGPT", "Free", "기본 (GPT-5.6 Luna)", "한국어"
            )
            assert manifest["total"] == 900
            assert len(manifest["chunks"]) > 1
            assert (out / "manifest.json").is_file()
        return 0
    except Exception as exc:
        try:
            Path("RenPyTools-v043-selftest-error.txt").write_text(repr(exc), encoding="utf-8")
        except Exception:
            pass
        return 1
