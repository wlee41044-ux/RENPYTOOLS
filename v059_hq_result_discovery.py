#!/usr/bin/env python3
import json
import time
from pathlib import Path

import RenPyToolsLauncherV048 as launcher048
import v048_master_hq as master
import v058_hq_file_split as split
from v050_manual_merge import (
    RESULT_FORMAT,
    game_id_from_sources,
    game_name_from_workspace,
    parse_result_v050,
)
from v044_smart_picker import downloads_root

_INSTALLED = False
_SKIP_NAMES = {"ai_사용법.txt"}


def build_master_workflow_v059(source_path, output_dir, service, plan, model, target_lang="한국어", status=None):
    """Keep v0.5.8 byte/token splitting while restoring the v0.5.0 result contract."""
    manifest = split.build_master_workflow_v058(
        source_path, output_dir, service, plan, model, target_lang, status=status
    )
    output_dir = Path(output_dir)
    game_name = game_name_from_workspace(output_dir)
    game_id = game_id_from_sources(manifest.get("sources", {}))
    prefix = f"{game_name}TL"
    parts = manifest.get("parts", [])
    part_count = max(1, len(parts))

    manifest["game_name"] = game_name
    manifest["game_id"] = game_id
    manifest["result_prefix"] = prefix
    manifest["manual_merge"] = True

    for index, part in enumerate(parts, 1):
        path = output_dir / part["file"]
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        header = (
            f"# part: {index}/{part_count}\n"
            f"# final_part: {'true' if index == part_count else 'false'}\n"
            f"# game_name: {game_name}\n"
            f"# game_id: {game_id}\n"
            f"# result_prefix: {prefix}"
        )
        text = text.replace(f"# part: {index}", header, 1)
        old_result_rule = "# 4) 채팅 본문/코드블록이 아니라 실제 다운로드 가능한 UTF-8 TXT 파일로 반환하세요."
        new_result_rule = (
            "# 4) 채팅 본문/코드블록이 아니라 실제 다운로드 가능한 UTF-8 TXT 파일로 반환하세요.\n"
            f"#    가능하면 결과 파일 이름은 {prefix}_001.txt, {prefix}_002.txt ... 형식으로 만드세요.\n"
            "#    파일명이 바뀌어도 RenPy Tools가 내용으로 찾을 수 있지만, 위 이름을 쓰는 것을 권장합니다.\n"
            f"#    파일 첫 줄에는 '# format: {RESULT_FORMAT}', 다음 줄에는 '# game_id: {game_id}'를 반드시 넣으세요."
        )
        text = text.replace(old_result_rule, new_result_rule, 1)
        old_finish = "# 8) 이미 번역한 ID는 다시 출력하지 마세요. 이 파트 마지막 ID까지 끝나면 '이 파트 완료'라고 알려주세요."
        new_finish = (
            "# 8) 이미 번역한 ID는 다시 출력하지 마세요. 현재 파트가 끝났고 final_part=false면 "
            "'이 파트 완료. 다음 작업 파일을 첨부하세요.'라고 알려주세요.\n"
            "#    final_part=true의 마지막 ID까지 끝났으면 '모든 번역이 끝났습니다.'라고 알려주세요."
        )
        text = text.replace(old_finish, new_finish, 1)
        path.write_text(text, encoding="utf-8", newline="\n")
        part["file_bytes"] = path.stat().st_size

    (output_dir / master.MASTER_MANIFEST).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    guide = output_dir / "AI_사용법.txt"
    if guide.is_file():
        with guide.open("a", encoding="utf-8", newline="\n") as fp:
            fp.write(
                f"\n권장 결과 파일명: {prefix}_001.txt, {prefix}_002.txt ...\n"
                f"결과 TXT 안에는 game_id: {game_id}가 있어야 파일명이 달라도 자동으로 찾을 수 있습니다.\n"
                "AI가 파일명을 다르게 만들었으면 조합하기의 '파일 직접 선택'으로 여러 TXT를 직접 고를 수도 있습니다.\n"
            )
    return manifest


def _txt_candidates(root, max_depth=2, max_files=1000):
    root = Path(root)
    if not root.is_dir():
        return []
    found = []
    stack = [(root, 0)]
    skip_dirs = {"android", ".git", "node_modules", "renpytools"}
    while stack and len(found) < max_files:
        folder, depth = stack.pop()
        try:
            children = list(folder.iterdir())
        except Exception:
            continue
        for path in children:
            if len(found) >= max_files:
                break
            try:
                if path.is_file() and path.suffix.lower() == ".txt":
                    found.append(path)
                elif path.is_dir() and depth < max_depth and path.name.lower() not in skip_dirs:
                    stack.append((path, depth + 1))
            except Exception:
                continue
    return found


def _skip_candidate(path):
    name = Path(path).name.lower()
    if name in _SKIP_NAMES:
        return True
    if name.startswith(master.MASTER_BASENAME.lower()):
        return True
    if name.startswith("renpytools-") and "error" in name:
        return True
    return False


def result_row_for_path(path, manifest, *, prefix=None, manual=False, workspace=None):
    path = Path(path)
    if not path.is_file() or _skip_candidate(path):
        return None
    sources = manifest.get("sources", {})
    expected_game_id = manifest.get("game_id") or game_id_from_sources(sources)
    parsed, meta, verified = parse_result_v050(path, sources, expected_game_id)
    if not parsed:
        return None

    prefix = prefix or manifest.get("result_prefix") or ""
    name_match = bool(prefix and path.name.lower().startswith(prefix.lower()))
    in_workspace = False
    if workspace:
        try:
            path.resolve().relative_to(Path(workspace).resolve())
            in_workspace = True
        except Exception:
            pass
    return {
        "path": path,
        "count": len(parsed),
        "verified": verified,
        "game_id_present": bool(meta.get("game_id")),
        "name_match": name_match,
        "manual": bool(manual),
        "in_workspace": in_workspace,
        "mtime": path.stat().st_mtime if path.exists() else 0,
        "first_id": min(parsed) if parsed else "",
        "last_id": max(parsed) if parsed else "",
    }


def find_matching_results_v059(game_path, workspace, manifest=None, roots=None):
    """Find valid result TXT by metadata/content, not only by filename prefix."""
    from v050_manual_merge import load_workspace_manifest

    workspace = Path(workspace)
    manifest = manifest or load_workspace_manifest(workspace)
    prefix = manifest.get("result_prefix") or ""
    created_at = float(manifest.get("created_at") or 0)
    if roots is None:
        roots = [downloads_root(game_path), workspace, workspace / master.TRANSLATED_DIR]

    seen = set()
    rows = []
    for root in roots:
        for path in _txt_candidates(root):
            try:
                key = str(path.resolve()).lower()
            except Exception:
                key = str(path).lower()
            if key in seen:
                continue
            seen.add(key)
            row = result_row_for_path(path, manifest, prefix=prefix, workspace=workspace)
            if row is None:
                continue

            # Strong matches are always shown. A row-only file with no metadata/name
            # is also shown when it was created around/after this HQ job, but marked
            # as needing confirmation in the UI. This catches AI-renamed downloads.
            strong = row["verified"] or row["name_match"] or row["in_workspace"]
            recent = not created_at or row["mtime"] >= created_at - 300
            if strong or (recent and row["count"] >= min(2, max(1, len(manifest.get("sources", {}))))):
                row["needs_confirmation"] = not strong
                rows.append(row)

    rows.sort(key=lambda row: row["mtime"])
    return rows


def install_v059_hq_contract():
    global _INSTALLED
    launcher048.build_master_workflow = build_master_workflow_v059
    _INSTALLED = True
    return True


def run_v059_self_test():
    try:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "Tree"
            game = root / "game"
            game.mkdir(parents=True)
            (game / "script.rpy").write_text(
                'label start:\n'
                '    "Good morning, this is a file discovery test sentence."\n'
                '    "Please keep this second translation test sentence too."\n',
                encoding="utf-8",
            )
            workspace = Path(td) / "Download" / "Tree TL.RENPY" / "20260905_160000"
            workspace.mkdir(parents=True)
            manifest = build_master_workflow_v059(
                root, workspace, "ChatGPT", "Plus", "High (GPT-5.6 Sol)", "한국어"
            )
            assert manifest["result_prefix"] == "TreeTL"
            assert manifest["game_id"]
            first_master = workspace / manifest["parts"][0]["file"]
            text = first_master.read_text(encoding="utf-8")
            assert "TreeTL_001.txt" in text
            assert f"# game_id: {manifest['game_id']}" in text

            arbitrary = Path(td) / "Download" / "translated_output.txt"
            arbitrary.write_text(
                f"# format: {RESULT_FORMAT}\n# game_id: {manifest['game_id']}\n"
                'RT0000001\t"첫 번째 번역"\n'
                'RT0000002\t"두 번째 번역"\n',
                encoding="utf-8",
            )
            rows = find_matching_results_v059(root, workspace, manifest, roots=[arbitrary.parent])
            assert any(row["path"].name == "translated_output.txt" and row["verified"] for row in rows)

            manual = Path(td) / "whatever_name.txt"
            manual.write_text('RT0000001\t"직접 선택 번역"\n', encoding="utf-8")
            row = result_row_for_path(manual, manifest, manual=True, workspace=workspace)
            assert row and row["manual"] and row["count"] == 1
        return 0
    except Exception as exc:
        try:
            Path("RenPyTools-v059-selftest-error.txt").write_text(repr(exc), encoding="utf-8")
        except Exception:
            pass
        return 1
