#!/usr/bin/env python3
import json
from pathlib import Path

import RenPyToolsLauncherV048 as launcher048
import v048_master_hq as base
import v059_hq_result_discovery as v059

_INSTALLED = False


def _recommended_rows(manifest):
    """Pick a large but conservative rows-per-result target to reduce turn overhead."""
    sources = list((manifest.get("sources") or {}).values())
    profile = manifest.get("profile") or {}
    safe_output = int(profile.get("safe_output_tokens") or 8000)
    if sources:
        sample = sources[: min(len(sources), 500)]
        avg_source = sum(base.estimate_tokens(text) for text in sample) / max(1, len(sample))
    else:
        avg_source = 16.0
    # Korean output plus the result row wrapper. This is deliberately conservative;
    # it is only a target, not a provider limit.
    estimated_row_output = max(14.0, avg_source * 1.35 + 7.0)
    rows = int((safe_output * 0.68) / estimated_row_output)
    return max(80, min(350, rows))


def _speed_block(rows_target, part_count):
    parallel = max(1, min(3, int(part_count or 1)))
    return [
        "#",
        "# FAST TRANSLATION MODE (RenPy Tools v0.5.12)",
        "# - 번역 외 설명, 분석 과정, 요약, 품질평가, 인사말을 출력하지 마세요.",
        "# - 파일 전체를 먼저 장황하게 분석하지 말고 첫 ID부터 바로 번역 결과를 작성하세요.",
        "# - 각 행은 자연스럽고 간결한 한국어로 직접 변환하세요. 같은 뜻을 불필요하게 길게 풀어쓰지 마세요.",
        "# - ID/순서를 건너뛰지 말고, {...}, [...] 토큰은 그대로 유지하세요.",
        "# - 원문 그대로 처리하기 어려운 문장은 노골적인 세부를 피하고 핵심 의미/화자/분위기를 유지한 완곡한 표현으로 번역한 뒤 계속하세요.",
        "# - 한 문장 때문에 전체 작업을 중단하지 마세요. 처리 가능한 다음 ID를 계속 진행하세요.",
        f"# - 한 결과 TXT에서 가능하면 약 {rows_target}문장까지 묶어서 처리하세요. 출력 한도에 가까우면 완전한 행에서 먼저 멈추세요.",
        "# - 결과는 채팅 본문에 재출력하지 말고 실제 다운로드 가능한 TXT 파일만 생성하세요.",
        f"# - 이 part는 다른 part와 독립적입니다. 작업 파일이 여러 개면 최대 {parallel}개를 서로 다른 AI 채팅에서 동시에 처리해도 됩니다.",
    ]


def _rewrite_master_for_speed(path, rows_target, part_count):
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    marker = "# SOURCE ROWS"
    if marker not in text:
        return False
    # Idempotent for rebuilds/tests.
    if "# FAST TRANSLATION MODE (RenPy Tools v0.5.12)" in text:
        return True
    block = "\n".join(_speed_block(rows_target, part_count)) + "\n#\n"
    text = text.replace(marker, block + marker, 1)
    path.write_text(text, encoding="utf-8", newline="\n")
    return True


def build_master_workflow_v0512(source_path, output_dir, service, plan, model, target_lang="한국어", status=None):
    """Keep v0.5.9 result compatibility while making the AI job prompt throughput-oriented."""
    manifest = v059.build_master_workflow_v059(
        source_path, output_dir, service, plan, model, target_lang, status=status
    )
    output_dir = Path(output_dir)
    rows_target = _recommended_rows(manifest)
    parts = manifest.get("parts") or []
    part_count = max(1, len(parts))
    manifest["hq_fast_prompt"] = True
    manifest["recommended_rows_per_result"] = rows_target
    manifest["parallel_parts_supported"] = True
    manifest["recommended_parallel_chats"] = max(1, min(3, part_count))

    for part in parts:
        path = output_dir / part.get("file", "")
        if path.is_file():
            _rewrite_master_for_speed(path, rows_target, part_count)
            part["file_bytes"] = path.stat().st_size

    (output_dir / base.MASTER_MANIFEST).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    guide = output_dir / "AI_사용법.txt"
    if guide.is_file():
        with guide.open("a", encoding="utf-8", newline="\n") as fp:
            fp.write(
                "\n[빠른 고품질 번역]\n"
                f"- 한 결과 파일 목표: 약 {rows_target}문장(문장 길이에 따라 AI가 더 일찍 멈출 수 있음)\n"
                "- AI에게 설명/분석을 시키지 않고 ID 순서대로 바로 번역하도록 작업 파일에 지시가 들어 있습니다.\n"
                "- 번역하기 어려운 문장은 전체 작업을 멈추지 않고 완곡한 표현으로 처리하도록 지시합니다.\n"
            )
            if part_count > 1:
                fp.write(
                    f"- 작업 파일 {part_count}개는 서로 독립적입니다. 속도가 중요하면 최대 {min(3, part_count)}개를 서로 다른 채팅에 각각 첨부해 동시에 번역할 수 있습니다.\n"
                    "- 동시에 번역해도 RT ID가 다르므로 RenPy Tools 조합하기에서 다시 합칠 수 있습니다.\n"
                )
    return manifest


def install_v0512_hq_speed_prompt():
    global _INSTALLED
    launcher048.build_master_workflow = build_master_workflow_v0512
    _INSTALLED = True
    return True


def run_v0512_self_test():
    try:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "SpeedDemo"
            game = root / "game"
            game.mkdir(parents=True)
            lines = ["label start:"]
            for i in range(160):
                lines.append(f'    "This is high quality translation speed test sentence number {i:04d}."')
            (game / "script.rpy").write_text("\n".join(lines) + "\n", encoding="utf-8")
            out = Path(td) / "out"
            manifest = build_master_workflow_v0512(
                root, out, "ChatGPT", "Plus", "Instant (GPT-5.6 Sol)", "한국어"
            )
            assert manifest["hq_fast_prompt"] is True
            assert 80 <= manifest["recommended_rows_per_result"] <= 350
            assert manifest["parallel_parts_supported"] is True
            first = out / manifest["parts"][0]["file"]
            text = first.read_text(encoding="utf-8")
            assert "FAST TRANSLATION MODE" in text
            assert "번역 외 설명" in text
            assert "완곡한 표현" in text
            assert "다운로드 가능한 TXT 파일만" in text
            assert "game_id:" in text
        return 0
    except Exception as exc:
        try:
            Path("RenPyTools-v0512-selftest-error.txt").write_text(repr(exc), encoding="utf-8")
        except Exception:
            pass
        return 1
