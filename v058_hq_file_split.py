#!/usr/bin/env python3
import json
import time
from pathlib import Path

import RenPyToolsLauncherV048 as launcher048
import v048_master_hq as base

_BASE_PROFILE_FOR = base.profile_for
_INSTALLED = False
_HEADER_RESERVE_BYTES = 4096


def _safe_master_file_bytes(profile):
    """RenPy Tools' own conservative attachment target, not a provider hard limit.

    The selected service/plan/model still controls the token budget.  This adds a
    second, byte-size gate so a context-capable model does not receive one huge TXT
    that is awkward or rejected by a mobile AI app/file picker.
    """
    service = str(profile.get("service", ""))
    plan = str(profile.get("plan", ""))
    model = str(profile.get("model", ""))
    context = profile.get("context_tokens")

    if service == "ChatGPT":
        if plan == "Free":
            target = 32 * 1024
        elif plan == "Go":
            target = 40 * 1024
        elif plan == "Plus":
            target = 48 * 1024
        else:
            target = 64 * 1024
    elif service == "Gemini":
        if "미가입" in plan or (context and context <= 32000):
            target = 24 * 1024
        elif "Plus" in plan or (context and context <= 128000):
            target = 40 * 1024
        elif "Ultra" in plan:
            target = 80 * 1024
        else:
            target = 64 * 1024
    elif service == "Claude":
        if plan == "Free":
            target = 32 * 1024
        elif "Haiku" in model:
            target = 40 * 1024
        elif plan == "Pro":
            target = 56 * 1024
        else:
            target = 64 * 1024
    else:
        target = 32 * 1024

    # Small-context profiles should never get a large attachment merely because
    # the provider's upload UI technically accepts it.
    if context and context <= 32000:
        target = min(target, 24 * 1024)
    elif context and context <= 128000:
        target = min(target, 40 * 1024)
    elif context and context <= 200000:
        target = min(target, 48 * 1024)
    return int(target)


def profile_for_v058(service, plan, model):
    profile = dict(_BASE_PROFILE_FOR(service, plan, model))
    safe_bytes = _safe_master_file_bytes(profile)
    profile["safe_master_file_bytes"] = safe_bytes
    profile["safe_master_file_kib"] = max(1, round(safe_bytes / 1024))
    return profile


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
        f"# renpytools_safe_file_target_kib: {profile['safe_master_file_kib']}",
        "#",
        "# 지시:",
        "# 1) 이 파일의 ID와 원문을 번호 순서대로 번역하세요.",
        "# 2) 한 번의 답변에서 전부 끝내려고 출력 한도까지 밀어붙이지 마세요.",
        "# 3) 대략 recommended_output_tokens 이내에서 완전한 문장까지만 처리하고 멈추세요.",
        "# 4) 채팅 본문/코드블록이 아니라 실제 다운로드 가능한 UTF-8 TXT 파일로 반환하세요.",
        "# 5) 결과 파일 각 줄은 반드시: RT0000001<TAB>\"번역문\" 형식(JSON 문자열)이어야 합니다.",
        "# 6) {...}, [...] 같은 Ren'Py 토큰은 원문 그대로 보존하세요.",
        "# 7) 사용자가 '다음', '0', 또는 '.'을 보내면 직전 결과의 마지막 ID 다음부터 계속하세요.",
        "# 8) 이미 번역한 ID는 다시 출력하지 마세요. 이 파트 마지막 ID까지 끝나면 '이 파트 완료'라고 알려주세요.",
        "#",
        "# SOURCE ROWS",
    ]
    path = Path(path)
    with path.open("w", encoding="utf-8", newline="\n") as fp:
        fp.write("\n".join(header) + "\n")
        for item_id, source in entries:
            fp.write(item_id + "\t" + json.dumps(source, ensure_ascii=False) + "\n")
    return path.stat().st_size


def build_master_workflow_v058(source_path, output_dir, service, plan, model, target_lang="한국어", status=None):
    source_path = Path(source_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    game_root, files = base.collect_rpy_fast(source_path)
    profile = profile_for_v058(service, plan, model)
    token_budget = max(4000, int(profile["safe_master_tokens"]))
    file_budget = max(16 * 1024, int(profile["safe_master_file_bytes"]))
    payload_byte_budget = max(8 * 1024, file_budget - _HEADER_RESERVE_BYTES)

    seen = {}
    sources = {}
    file_groups = {}
    parts = []
    current = []
    current_tokens = 0
    current_bytes = 0
    next_id = 1

    def report(text):
        if status:
            try:
                status(text)
            except Exception:
                pass

    def flush():
        nonlocal current, current_tokens, current_bytes
        if not current:
            return
        index = len(parts) + 1
        name = f"{base.MASTER_BASENAME}_{index:03d}.txt"
        path = output_dir / name
        actual_bytes = _write_master_part(path, profile, target_lang, index, current)
        parts.append({
            "file": name,
            "first_id": current[0][0],
            "last_id": current[-1][0],
            "items": len(current),
            "estimated_input_tokens": current_tokens,
            "file_bytes": actual_bytes,
            "safe_file_bytes": file_budget,
        })
        current = []
        current_tokens = 0
        current_bytes = 0

    for file_index, file in enumerate(files, 1):
        try:
            rel = file.relative_to(game_root).as_posix()
        except Exception:
            rel = file.name
        ids = []
        report(f"AI 입력 한도에 맞춰 작업 파일을 나누고 있어요... {file_index}/{len(files)} · {rel}")
        for _, text in base.iter_extract_strings_stream(file):
            item_id = seen.get(text)
            if item_id is None:
                item_id = f"RT{next_id:07d}"
                next_id += 1
                seen[text] = item_id
                sources[item_id] = text
                row_tokens = base.estimate_tokens(text) + 8
                row = item_id + "\t" + json.dumps(text, ensure_ascii=False) + "\n"
                row_bytes = len(row.encode("utf-8"))
                would_exceed_tokens = current_tokens + row_tokens > token_budget
                would_exceed_bytes = current_bytes + row_bytes > payload_byte_budget
                if current and (would_exceed_tokens or would_exceed_bytes):
                    flush()
                current.append((item_id, text))
                current_tokens += row_tokens
                current_bytes += row_bytes
            ids.append(item_id)
        file_groups[rel] = list(dict.fromkeys(ids))
    flush()

    if not sources:
        raise RuntimeError("번역할 문장을 찾지 못했습니다.")

    if len(parts) == 1:
        old = output_dir / parts[0]["file"]
        new = output_dir / f"{base.MASTER_BASENAME}.txt"
        if new.exists():
            new.unlink()
        old.rename(new)
        parts[0]["file"] = new.name
        parts[0]["file_bytes"] = new.stat().st_size

    manifest = {
        "format": base.MASTER_FORMAT,
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
    (output_dir / base.MASTER_MANIFEST).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / base.TRANSLATED_DIR).mkdir(parents=True, exist_ok=True)

    guide = (
        "RenPy Tools 고품질 번역 - 입력 한도 자동 분할 방식\n\n"
        f"선택: {service} / {plan} / {model}\n"
        f"전체 문장: {len(sources):,}개\n"
        f"AI에 첨부할 작업 파일: {len(parts)}개\n"
        f"파일당 RenPy Tools 안전 목표: 약 {profile['safe_master_file_kib']}KiB 이하\n"
        f"1회 번역 출력 목표: 약 {profile['safe_output_tokens']:,}토큰 이하\n\n"
        "1. AI_전체번역작업_001.txt부터 AI 채팅에 첨부합니다.\n"
        "2. 같은 파일 안에서는 AI가 멈출 때마다 '0' 또는 '.'을 보내 계속 받습니다.\n"
        "3. 현재 작업 파일의 마지막 ID까지 끝나면 다음 번호 TXT를 첨부합니다.\n"
        "4. 결과 TXT는 휴대폰 Download에 저장합니다.\n"
        "5. 모든 결과를 받은 뒤 RenPy Tools의 조합하기에서 합성/패치합니다.\n"
        "※ 파일 크기 목표는 RenPy Tools가 안정성을 위해 정한 값이며 각 AI 서비스의 공식 업로드 한도와 동일하다는 뜻은 아닙니다.\n"
    )
    (output_dir / "AI_사용법.txt").write_text(guide, encoding="utf-8")
    report(
        f"준비 완료 · {len(sources):,}문장 · 작업 파일 {len(parts)}개 · "
        f"파일당 목표 약 {profile['safe_master_file_kib']}KiB"
    )
    return manifest


def _set_profile_hint_v058(self):
    info = profile_for_v058(self.hq_service.get(), self.hq_plan.get(), self.hq_model.get())
    context = f"{info['context_tokens']:,}" if info["context_tokens"] else "고정값 미확인"
    output = f"{info['max_output_tokens']:,}" if info["max_output_tokens"] else "고정값 미확인"
    self.hq_profile_hint.set(
        f"컨텍스트 참고 {context}토큰 · 최대 출력 참고 {output}토큰 · "
        f"작업 파일당 약 {info['safe_master_file_kib']}KiB 이하로 자동 분할 · "
        f"1회 번역 출력 목표 {info['safe_output_tokens']:,}토큰"
    )


def install_v058_hq_file_split():
    global _INSTALLED
    launcher048.profile_for = profile_for_v058
    launcher048.build_master_workflow = build_master_workflow_v058
    launcher048.RenPyToolsV048._set_profile_hint = _set_profile_hint_v058
    _INSTALLED = True
    return True


def run_v058_self_test():
    try:
        import tempfile
        chatgpt = profile_for_v058("ChatGPT", "Plus", "High (GPT-5.6 Sol)")
        gemini = profile_for_v058("Gemini", "AI 요금제 미가입", "Gemini 3 Flash")
        assert chatgpt["safe_master_file_bytes"] == 48 * 1024
        assert gemini["safe_master_file_bytes"] == 24 * 1024

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "LargeDemo"
            game = root / "game"
            game.mkdir(parents=True)
            lines = ["label start:"]
            for i in range(360):
                lines.append(f'    "This is translation test sentence number {i:04d} with enough text to make the master file larger."')
            (game / "script.rpy").write_text("\n".join(lines) + "\n", encoding="utf-8")
            out = Path(td) / "out"
            manifest = build_master_workflow_v058(
                root, out, "ChatGPT", "Plus", "High (GPT-5.6 Sol)"
            )
            assert len(manifest["parts"]) >= 2
            for part in manifest["parts"]:
                path = out / part["file"]
                assert path.is_file()
                # Header reserve keeps normal multi-row parts under the target.
                assert path.stat().st_size <= chatgpt["safe_master_file_bytes"]
        return 0
    except Exception as exc:
        try:
            Path("RenPyTools-v058-selftest-error.txt").write_text(repr(exc), encoding="utf-8")
        except Exception:
            pass
        return 1
