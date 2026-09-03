#!/usr/bin/env python3
import json
import math
import re
import shutil
import tempfile
import time
from pathlib import Path

import v043_features as hq
from fast_scan import collect_rpy_fast
from v043_features import iter_extract_strings_stream
from v044_smart_picker import downloads_root, shared_storage_candidates

MASTER_FORMAT = "renpytools-master-v1"
MASTER_MANIFEST = "master_manifest.json"
MASTER_BASENAME = "AI_전체번역작업"
RESULT_PREFIX = "RenPyTools_Result_"
TRANSLATED_DIR = "번역완료"
COMBINED_NAME = "RenPyTools_Combined_Translation.json"

# Context/output numbers below are reference values from current public provider
# documentation where available. safe_master_tokens and safe_output_tokens are
# RenPy Tools' own conservative working targets for a long multi-turn translation
# conversation; they are NOT claims about a user's exact product usage quota.
PROFILE_INFO = {
    "ChatGPT": {
        "Free": {
            "기본 (GPT-5.6 Luna)": (1050000, 128000, 280000, 32000, "Luna 모델 참고치 · Free 사용량 제한은 별도"),
            "Think (GPT-5.6 Luna)": (1050000, 128000, 240000, 28000, "Luna Think · 추론 사용량을 고려해 작업량을 조금 낮춤"),
        },
        "Go": {
            "기본 (GPT-5.6 Luna)": (1050000, 128000, 320000, 36000, "Luna 모델 참고치 · Go 사용량 제한은 별도"),
            "Think (GPT-5.6 Luna)": (1050000, 128000, 280000, 32000, "Luna Think · 장문 작업 안전 목표"),
        },
        "Plus": {
            "Instant (GPT-5.6 Sol)": (1050000, 128000, 360000, 42000, "Sol 모델 참고치 · 긴 대화 여유를 남긴 설정"),
            "Medium (GPT-5.6 Sol)": (1050000, 128000, 340000, 40000, "Sol Medium · 추론 토큰 여유 포함"),
            "High (GPT-5.6 Sol)": (1050000, 128000, 320000, 38000, "Sol High · 품질 우선, 출력 잘림 방지 여유 포함"),
        },
        "Pro": {
            "Instant (GPT-5.6 Sol)": (1050000, 128000, 400000, 48000, "Sol · 높은 사용량 플랜용"),
            "Medium (GPT-5.6 Sol)": (1050000, 128000, 380000, 46000, "Sol Medium"),
            "High (GPT-5.6 Sol)": (1050000, 128000, 360000, 44000, "Sol High"),
            "Extra High (GPT-5.6 Sol)": (1050000, 128000, 330000, 40000, "Sol Extra High · 추론 여유를 더 확보"),
            "Pro (GPT-5.6 Sol Pro)": (1050000, 128000, 320000, 38000, "장시간 워크플로용 Pro · 품질 우선 안전 목표"),
        },
        "Business": {
            "Medium (GPT-5.6 Sol)": (1050000, 128000, 380000, 46000, "Sol Medium"),
            "High (GPT-5.6 Sol)": (1050000, 128000, 360000, 44000, "Sol High"),
            "Extra High (GPT-5.6 Sol)": (1050000, 128000, 330000, 40000, "Sol Extra High"),
            "Pro (GPT-5.6 Sol Pro)": (1050000, 128000, 320000, 38000, "Sol Pro"),
        },
        "Enterprise": {
            "Medium (GPT-5.6 Sol)": (1050000, 128000, 400000, 48000, "Sol Medium"),
            "High (GPT-5.6 Sol)": (1050000, 128000, 380000, 46000, "Sol High"),
            "Extra High (GPT-5.6 Sol)": (1050000, 128000, 350000, 42000, "Sol Extra High"),
            "Pro (GPT-5.6 Sol Pro)": (1050000, 128000, 330000, 40000, "Sol Pro"),
        },
        "잘 모르겠어요": {"자동 추천": (1050000, 128000, 220000, 26000, "안전 우선 자동값")},
    },
    "Gemini": {
        "AI 요금제 미가입": {
            "Gemini 3 Flash-lite": (32000, 64000, 8500, 6000, "Gemini 앱 컨텍스트 32K 기준"),
            "Gemini 3 Flash": (32000, 65536, 8500, 6500, "Gemini 앱 컨텍스트 32K 기준"),
            "Gemini 3 Pro": (32000, 64000, 8000, 6500, "Gemini 앱 컨텍스트 32K 기준"),
        },
        "Google AI Plus": {
            "Gemini 3 Flash-lite": (128000, 64000, 36000, 16000, "Gemini 앱 컨텍스트 128K 기준"),
            "Gemini 3 Flash": (128000, 65536, 36000, 18000, "Gemini 앱 컨텍스트 128K 기준"),
            "Gemini 3 Pro": (128000, 64000, 34000, 18000, "Gemini 앱 컨텍스트 128K 기준"),
        },
        "Google AI Pro": {
            "Gemini 3 Flash-lite": (1000000, 64000, 320000, 36000, "Gemini 앱 컨텍스트 1M 기준"),
            "Gemini 3 Flash": (1000000, 65536, 320000, 40000, "Gemini 앱 컨텍스트 1M 기준"),
            "Gemini 3 Pro": (1000000, 64000, 300000, 40000, "Gemini 앱 컨텍스트 1M 기준"),
        },
        "Google AI Ultra": {
            "Gemini 3 Flash-lite": (1000000, 64000, 360000, 42000, "Gemini 앱 컨텍스트 1M 기준"),
            "Gemini 3 Flash": (1000000, 65536, 360000, 46000, "Gemini 앱 컨텍스트 1M 기준"),
            "Gemini 3 Pro": (1000000, 64000, 340000, 46000, "Gemini 앱 컨텍스트 1M 기준"),
        },
        "잘 모르겠어요": {"자동 추천": (32000, 64000, 7500, 5500, "가장 작은 앱 컨텍스트 기준 안전값")},
    },
    "Claude": {
        "Free": {
            "자동 추천": (None, None, 50000, 12000, "Free의 고정 컨텍스트 수치는 여기서 단정하지 않고 안전값 사용"),
        },
        "Pro": {
            "Claude Sonnet 5": (1000000, 128000, 300000, 38000, "유료 Claude 채팅 1M 컨텍스트 · Sonnet 5 최대 출력 참고 128K"),
            "Claude Opus 5 (사용 가능 시)": (1000000, 128000, 280000, 34000, "유료 Claude 채팅 1M 컨텍스트 · Opus 5"),
            "Claude Fable 5.1 (크레딧)": (1000000, 128000, 280000, 34000, "Pro에서는 사용 크레딧이 필요할 수 있음"),
            "Claude Sonnet 4.6": (500000, 128000, 150000, 26000, "유료 Claude 채팅 500K 컨텍스트"),
            "Claude Haiku 4.5": (200000, 64000, 60000, 18000, "200K 컨텍스트 / 64K 출력 참고"),
        },
        "Max 5x": {
            "Claude Sonnet 5": (1000000, 128000, 340000, 44000, "1M 컨텍스트 · Max 5x 사용량"),
            "Claude Opus 5": (1000000, 128000, 320000, 40000, "1M 컨텍스트 · Max 5x"),
            "Claude Fable 5.1": (1000000, 128000, 300000, 38000, "1M 컨텍스트 · Fable은 주간 사용량을 더 빠르게 쓸 수 있음"),
            "Claude Sonnet 4.6": (500000, 128000, 160000, 28000, "500K 컨텍스트"),
        },
        "Max 20x": {
            "Claude Sonnet 5": (1000000, 128000, 380000, 50000, "1M 컨텍스트 · Max 20x"),
            "Claude Opus 5": (1000000, 128000, 350000, 46000, "1M 컨텍스트 · Max 20x"),
            "Claude Fable 5.1": (1000000, 128000, 330000, 42000, "1M 컨텍스트 · Fable 사용량 특성 고려"),
            "Claude Sonnet 4.6": (500000, 128000, 170000, 30000, "500K 컨텍스트"),
        },
        "Team / Enterprise": {
            "Claude Sonnet 5": (1000000, 128000, 380000, 50000, "1M 컨텍스트 · 워크스페이스 정책에 따라 모델 접근 가능"),
            "Claude Opus 5": (1000000, 128000, 350000, 46000, "1M 컨텍스트"),
            "Claude Fable 5.1": (1000000, 128000, 330000, 42000, "1M 컨텍스트 · 좌석/크레딧 정책에 따라 달라질 수 있음"),
        },
        "잘 모르겠어요": {"자동 추천": (200000, 64000, 50000, 12000, "안전 우선 자동값")},
    },
    "기타 AI": {
        "잘 모르겠어요": {"자동 추천": (None, None, 40000, 10000, "공식 한도를 모를 때 쓰는 안전값")},
    },
}


def _compat_catalog():
    out = {}
    for service, plans in PROFILE_INFO.items():
        out[service] = {}
        for plan, models in plans.items():
            out[service][plan] = {}
            for model, (_, _, safe_master, _, _) in models.items():
                # Existing UI requires (items, chars). v0.4.8 no longer uses
                # these values to create chunks, but keep the shared API valid.
                out[service][plan][model] = (999999, max(20000, safe_master * 3))
    return out


def apply_v048_profiles():
    hq.AI_CATALOG.clear()
    hq.AI_CATALOG.update(_compat_catalog())
    return hq.AI_CATALOG


def profile_for(service, plan, model):
    plans = PROFILE_INFO.get(service) or PROFILE_INFO["기타 AI"]
    if plan not in plans:
        plan = next(iter(plans))
    models = plans[plan]
    if model not in models:
        model = next(iter(models))
    context, max_output, safe_master, safe_output, note = models[model]
    return {
        "service": service,
        "plan": plan,
        "model": model,
        "context_tokens": context,
        "max_output_tokens": max_output,
        "safe_master_tokens": safe_master,
        "safe_output_tokens": safe_output,
        "note": note,
    }


def plans_for(service):
    return list((PROFILE_INFO.get(service) or PROFILE_INFO["기타 AI"]).keys())


def models_for(service, plan):
    plans = PROFILE_INFO.get(service) or PROFILE_INFO["기타 AI"]
    if plan not in plans:
        plan = next(iter(plans))
    return list(plans[plan].keys())


def estimate_tokens(text):
    """Conservative mixed-language estimate; not a provider tokenizer."""
    text = str(text)
    ascii_count = sum(1 for c in text if ord(c) < 128)
    non_ascii = len(text) - ascii_count
    return max(1, math.ceil(ascii_count / 3.6 + non_ascii / 1.35 + 4))


def _token_placeholders(text):
    return set(re.findall(r"\{[^{}]+\}|\[[^\[\]]+\]", str(text)))


def _write_master_part(path, profile, target_lang, part_index, entries):
    first_id = entries[0][0]
    last_id = entries[-1][0]
    header = [
        "# RenPy Tools 전체 번역 작업",
        f"# service: {profile['service']}",
        f"# plan: {profile['plan']}",
        f"# model: {profile['model']}",
        f"# target_lang: {target_lang}",
        f"# part: {part_index}",
        f"# id_range: {first_id} ~ {last_id}",
        f"# recommended_output_tokens: {profile['safe_output_tokens']}",
        "#",
        "# 지시:",
        "# 1) 이 파일의 ID와 원문을 번호 순서대로 번역하세요.",
        "# 2) 한 번의 답변에서 전부 끝내려고 출력 한도까지 밀어붙이지 마세요.",
        "# 3) 대략 recommended_output_tokens 이내에서 완전한 문장까지만 처리하고 멈추세요.",
        "# 4) 결과는 다운로드 가능한 TXT 파일 하나로 반환하세요.",
        "# 5) 결과 파일 각 줄은 반드시: RT0000001<TAB>\"번역문\" 형식(JSON 문자열)이어야 합니다.",
        "# 6) {...}, [...] 같은 Ren'Py 토큰은 원문 그대로 보존하세요.",
        "# 7) 사용자가 '다음'이라고 하면 직전 결과의 마지막 ID 다음부터 계속하세요.",
        "# 8) 이미 번역한 ID는 다시 출력하지 마세요. 이 파트 마지막 ID까지 끝나면 '이 파트 완료'라고 짧게 알려주세요.",
        "#",
        "# SOURCE ROWS",
    ]
    with Path(path).open("w", encoding="utf-8", newline="\n") as fp:
        fp.write("\n".join(header) + "\n")
        for item_id, source in entries:
            fp.write(item_id + "\t" + json.dumps(source, ensure_ascii=False) + "\n")


def build_master_workflow(source_path, output_dir, service, plan, model, target_lang="한국어", status=None):
    source_path = Path(source_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    game_root, files = collect_rpy_fast(source_path)
    profile = profile_for(service, plan, model)
    budget = max(4000, int(profile["safe_master_tokens"]))

    seen = {}
    sources = {}
    file_groups = {}
    parts = []
    current = []
    current_tokens = 0
    next_id = 1

    def report(text):
        if status:
            try:
                status(text)
            except Exception:
                pass

    def flush():
        nonlocal current, current_tokens
        if not current:
            return
        index = len(parts) + 1
        # Temporary numbered name; renamed to unnumbered if there is only one part.
        name = f"{MASTER_BASENAME}_{index:03d}.txt"
        path = output_dir / name
        _write_master_part(path, profile, target_lang, index, current)
        parts.append({
            "file": name,
            "first_id": current[0][0],
            "last_id": current[-1][0],
            "items": len(current),
            "estimated_input_tokens": current_tokens,
        })
        current = []
        current_tokens = 0

    for file_index, file in enumerate(files, 1):
        try:
            rel = file.relative_to(game_root).as_posix()
        except Exception:
            rel = file.name
        ids = []
        report(f"전체 번역 파일을 만들고 있어요... {file_index}/{len(files)} · {rel}")
        for _, text in iter_extract_strings_stream(file):
            item_id = seen.get(text)
            if item_id is None:
                item_id = f"RT{next_id:07d}"
                next_id += 1
                seen[text] = item_id
                sources[item_id] = text
                row_tokens = estimate_tokens(text) + 8
                if current and current_tokens + row_tokens > budget:
                    flush()
                current.append((item_id, text))
                current_tokens += row_tokens
            ids.append(item_id)
        file_groups[rel] = list(dict.fromkeys(ids))
    flush()

    if not sources:
        raise RuntimeError("번역할 문장을 찾지 못했습니다.")

    if len(parts) == 1:
        old = output_dir / parts[0]["file"]
        new = output_dir / f"{MASTER_BASENAME}.txt"
        if new.exists():
            new.unlink()
        old.rename(new)
        parts[0]["file"] = new.name

    manifest = {
        "format": MASTER_FORMAT,
        "created_at": time.time(),
        "source_path": str(source_path.resolve()),
        "game_root": str(game_root.resolve()),
        "target_lang": target_lang,
        "service": service,
        "plan": plan,
        "model": model,
        "profile": profile,
        "total": len(sources),
        "parts": parts,
        "sources": sources,
        "file_groups": file_groups,
    }
    (output_dir / MASTER_MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / TRANSLATED_DIR).mkdir(parents=True, exist_ok=True)

    guide = (
        "RenPy Tools 고품질 번역 - 전체 파일 방식\n\n"
        f"선택: {service} / {plan} / {model}\n"
        f"전체 문장: {len(sources):,}개\n"
        f"전체 작업 파일: {len(parts)}개\n"
        f"RenPy Tools 권장 1회 출력 목표: 약 {profile['safe_output_tokens']:,}토큰 이하\n\n"
        "1. 첫 AI_전체번역작업 파일을 AI 채팅에 한 번 첨부합니다.\n"
        "2. 파일 안의 지시대로 번역 파일을 받습니다.\n"
        "3. 결과 TXT를 Downloads에 저장합니다.\n"
        "4. 같은 채팅에서 '다음'이라고 보내 계속 받습니다.\n"
        "5. 현재 전체작업 파일이 끝나면 다음 전체작업 파일이 있을 때만 그것을 한 번 더 첨부합니다.\n"
        "6. RenPy Tools가 결과 TXT를 자동 감지하고 모두 끝나면 자동 조합합니다.\n"
    )
    (output_dir / "AI_사용법.txt").write_text(guide, encoding="utf-8")
    report(f"준비 완료 · {len(sources):,}문장 · 전체작업 파일 {len(parts)}개")
    return manifest


def _read_manifest(workspace):
    return json.loads((Path(workspace) / MASTER_MANIFEST).read_text(encoding="utf-8"))


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
        root = Path(root)
        try:
            key = str(root.resolve()).lower()
        except Exception:
            key = str(root).lower()
        if key in seen or not root.is_dir():
            continue
        seen.add(key)
        out.append(root)
    return out


def parse_result_file(path, sources):
    result = {}
    try:
        with Path(path).open("r", encoding="utf-8", errors="replace") as fp:
            for raw in fp:
                line = raw.rstrip("\r\n")
                if not line.startswith("RT") or "\t" not in line:
                    continue
                item_id, encoded = line.split("\t", 1)
                if item_id not in sources:
                    continue
                try:
                    translated = json.loads(encoded)
                except Exception:
                    continue
                if not isinstance(translated, str) or not translated.strip():
                    continue
                if not _token_placeholders(sources[item_id]).issubset(_token_placeholders(translated)):
                    continue
                result[item_id] = translated
    except Exception:
        return {}
    return result


def scan_master_results(workspace, preferred_path=None, roots=None):
    workspace = Path(workspace)
    manifest = _read_manifest(workspace)
    sources = manifest.get("sources", {})
    roots = list(roots) if roots is not None else _candidate_roots(preferred_path)
    translated_dir = workspace / TRANSLATED_DIR
    translated_dir.mkdir(parents=True, exist_ok=True)
    memory_path = translated_dir / "translation_memory.json"
    try:
        memory = json.loads(memory_path.read_text(encoding="utf-8")) if memory_path.exists() else {}
    except Exception:
        memory = {}

    candidates = []
    for root in roots:
        root = Path(root)
        try:
            candidates.extend(root.glob("*.txt"))
            for child in root.iterdir():
                if child.is_dir() and child.name.lower() not in {"android", "renpytools"}:
                    candidates.extend(child.glob("*.txt"))
        except Exception:
            continue

    imported = 0
    for path in sorted(set(candidates), key=lambda p: p.stat().st_mtime if p.exists() else 0):
        name = path.name
        if name.startswith(MASTER_BASENAME) or name in {"AI_사용법.txt"}:
            continue
        parsed = parse_result_file(path, sources)
        if not parsed:
            continue
        before = len(memory)
        memory.update(parsed)
        imported += max(0, len(memory) - before)
        try:
            dest = translated_dir / name
            if not dest.exists() or dest.stat().st_mtime < path.stat().st_mtime:
                shutil.copy2(path, dest)
        except Exception:
            pass

    memory_path.write_text(json.dumps(memory, ensure_ascii=False, indent=2), encoding="utf-8")
    return imported, memory


def master_status(workspace):
    workspace = Path(workspace)
    manifest = _read_manifest(workspace)
    sources = manifest.get("sources", {})
    parts = manifest.get("parts", [])
    memory_path = workspace / TRANSLATED_DIR / "translation_memory.json"
    try:
        memory = json.loads(memory_path.read_text(encoding="utf-8")) if memory_path.exists() else {}
    except Exception:
        memory = {}
    completed_ids = {x for x in memory if x in sources and str(memory[x]).strip()}
    total = len(sources)
    completed = len(completed_ids)
    next_id = None
    for item_id in sources:
        if item_id not in completed_ids:
            next_id = item_id
            break
    current_part = None
    for index, part in enumerate(parts, 1):
        if next_id is None or part["first_id"] <= next_id <= part["last_id"]:
            current_part = index
            break
    if current_part is None and parts:
        current_part = len(parts)
    return {
        "total": total,
        "completed": completed,
        "percent": int(completed / max(total, 1) * 100),
        "next_id": next_id,
        "done": total > 0 and completed == total,
        "part_count": len(parts),
        "current_part": current_part or 0,
        "current_file": parts[(current_part or 1) - 1]["file"] if parts else None,
        "translations": memory,
        "manifest": manifest,
    }


def write_combined_if_done(workspace):
    state = master_status(workspace)
    if not state["done"]:
        return None
    manifest = state["manifest"]
    output = Path(workspace) / COMBINED_NAME
    payload = {
        "format": "renpytools-combined-v1",
        "created_at": time.time(),
        "target_lang": manifest.get("target_lang", "한국어"),
        "source_path": manifest.get("source_path", ""),
        "sources": manifest.get("sources", {}),
        "translations": state["translations"],
        "file_groups": manifest.get("file_groups", {}),
        "service": manifest.get("service", ""),
        "plan": manifest.get("plan", ""),
        "model": manifest.get("model", ""),
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def run_v048_self_test():
    try:
        apply_v048_profiles()
        assert profile_for("Gemini", "Google AI Pro", "Gemini 3 Pro")["context_tokens"] == 1000000
        assert profile_for("Claude", "Pro", "Claude Sonnet 5")["max_output_tokens"] == 128000
        assert profile_for("ChatGPT", "Plus", "High (GPT-5.6 Sol)")["safe_master_tokens"] >= 300000
        assert estimate_tokens("Hello world") < estimate_tokens("안녕하세요 세계") * 2
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "Demo"
            game = root / "game"
            game.mkdir(parents=True)
            (game / "script.rpy").write_text('label start:\n    "Hello"\n    "World"\n', encoding="utf-8")
            out = Path(td) / "out"
            manifest = build_master_workflow(root, out, "ChatGPT", "Plus", "High (GPT-5.6 Sol)")
            assert manifest["total"] == 2
            assert len(manifest["parts"]) == 1
            assert (out / f"{MASTER_BASENAME}.txt").is_file()
            downloads = Path(td) / "Download"
            downloads.mkdir()
            (downloads / "RenPyTools_Result_test.txt").write_text(
                'RT0000001\t"안녕"\nRT0000002\t"세계"\n', encoding="utf-8"
            )
            imported, memory = scan_master_results(out, roots=[downloads])
            assert imported == 2 and len(memory) == 2
            assert master_status(out)["done"]
            assert write_combined_if_done(out).is_file()
        return 0
    except Exception as exc:
        try:
            Path("RenPyTools-v048-selftest-error.txt").write_text(repr(exc), encoding="utf-8")
        except Exception:
            pass
        return 1
