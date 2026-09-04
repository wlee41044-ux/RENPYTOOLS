#!/usr/bin/env python3
import hashlib
import json
import shutil
import tempfile
import time
from pathlib import Path

import RenPyAIPatcher as core
import v048_master_hq as master
from v044_smart_picker import downloads_root, safe_folder_name

RESULT_FORMAT = "renpytools-result-v2"


def game_name_from_workspace(workspace):
    name = Path(workspace).parent.name
    suffix = " TL.RENPY"
    if name.upper().endswith(suffix):
        name = name[:-len(suffix)]
    return name or "RenPyGame"


def game_name_from_path(game_path):
    root = Path(game_path)
    if root.name.lower() == "game":
        root = root.parent
    return safe_folder_name(root.name or "RenPyGame")


def game_id_from_sources(sources):
    payload = json.dumps(sources or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _replace_instruction(text, old, new):
    return text.replace(old, new) if old in text else text


def build_master_workflow_v050(source_path, output_dir, service, plan, model, target_lang="한국어", status=None):
    """Build v0.4.8 master files, then upgrade them to the manual-merge v0.5.0 contract."""
    manifest = master.build_master_workflow(
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
    (output_dir / master.MASTER_MANIFEST).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    for index, part in enumerate(parts, 1):
        path = output_dir / part["file"]
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        text = _replace_instruction(
            text,
            f"# part: {index}",
            f"# part: {index}/{part_count}\n# final_part: {'true' if index == part_count else 'false'}\n"
            f"# game_name: {game_name}\n# game_id: {game_id}\n# result_prefix: {prefix}",
        )
        text = _replace_instruction(
            text,
            "# 4) 결과는 다운로드 가능한 TXT 파일 하나로 반환하세요.",
            "# 4) 결과는 반드시 실제로 다운로드 가능한 UTF-8 .txt 파일 하나로 생성해서 첨부하세요.\n"
            "#    채팅 본문이나 코드블록에 결과를 붙여넣는 방식은 금지합니다.\n"
            f"#    결과 파일 이름은 {prefix}_001.txt, {prefix}_002.txt ...처럼 {prefix}로 시작하고 매 답변마다 번호를 올리세요.\n"
            f"#    파일 첫 줄에는 '# format: {RESULT_FORMAT}', 다음 줄에는 '# game_id: {game_id}'를 넣으세요.",
        )
        text = _replace_instruction(
            text,
            "# 7) 사용자가 '다음'이라고 하면 직전 결과의 마지막 ID 다음부터 계속하세요.",
            "# 7) 사용자가 '다음', '0', 또는 '.' 하나만 보내면 모두 같은 계속 명령입니다. 직전 결과의 마지막 ID 다음부터 계속하세요.",
        )
        text = _replace_instruction(
            text,
            "# 8) 이미 번역한 ID는 다시 출력하지 마세요. 이 파트 마지막 ID까지 끝나면 '이 파트 완료'라고 짧게 알려주세요.",
            "# 8) 이미 번역한 ID는 다시 출력하지 마세요. 현재 파트가 끝났고 final_part=false면 '이 파트 완료. 다음 작업 파일을 첨부하세요.'라고 말하세요.\n"
            "#    final_part=true의 마지막 ID까지 끝났으면 반드시 '모든 번역이 끝났습니다.'라고 말하세요. 이후 계속 명령을 받아도 번역을 처음부터 반복하지 마세요.",
        )
        path.write_text(text, encoding="utf-8", newline="\n")

    guide = output_dir / "AI_사용법.txt"
    if guide.exists():
        text = guide.read_text(encoding="utf-8", errors="replace")
        text = text.replace("같은 채팅에서 '다음'이라고 보내", "같은 채팅에서 '0', '.', 또는 '다음'을 보내")
        text += (
            f"\n결과 파일 이름은 {prefix}_001.txt, {prefix}_002.txt ... 형식을 사용합니다.\n"
            "모든 결과를 받은 뒤 RenPy Tools 홈의 '조합하기'에서 게임을 고르면 같은 이름의 결과 파일을 자동 검색합니다.\n"
            "자동 조합은 하지 않습니다. 사용자가 일괄 합성 또는 선택 합성을 눌렀을 때만 최종 패치를 만듭니다.\n"
        )
        guide.write_text(text, encoding="utf-8")
    return manifest


def parse_result_v050(path, sources, expected_game_id=None):
    """Parse a TreeTL*.txt result. Metadata is preferred; legacy row-only TXT remains usable."""
    result = {}
    meta = {}
    try:
        with Path(path).open("r", encoding="utf-8", errors="replace") as fp:
            for raw in fp:
                line = raw.rstrip("\r\n")
                if line.startswith("#") and ":" in line:
                    key, value = line[1:].split(":", 1)
                    meta[key.strip().lower()] = value.strip()
                    continue
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
                if not master._token_placeholders(sources[item_id]).issubset(master._token_placeholders(translated)):
                    continue
                result[item_id] = translated
    except Exception:
        return {}, {}, False

    file_game_id = meta.get("game_id")
    verified = bool(expected_game_id and file_game_id == expected_game_id)
    if expected_game_id and file_game_id and file_game_id != expected_game_id:
        return {}, meta, False
    return result, meta, verified


def _candidate_result_files(root, prefix):
    root = Path(root)
    found = []
    if not root.is_dir():
        return found
    try:
        found.extend(root.glob("*.txt"))
        for child in root.iterdir():
            if not child.is_dir() or child.name.lower() in {"android", "renpytools"}:
                continue
            found.extend(child.glob("*.txt"))
    except Exception:
        pass
    prefix_lower = prefix.lower()
    return [p for p in found if p.name.lower().startswith(prefix_lower) and p.suffix.lower() == ".txt"]


def find_latest_workspace(game_path):
    game_name = game_name_from_path(game_path)
    base = downloads_root(game_path) / f"{game_name} TL.RENPY"
    candidates = []
    if base.is_dir():
        try:
            for child in base.iterdir():
                manifest = child / master.MASTER_MANIFEST
                if child.is_dir() and manifest.is_file():
                    candidates.append((manifest.stat().st_mtime, child))
        except Exception:
            pass
    if not candidates:
        return None
    candidates.sort(key=lambda row: row[0], reverse=True)
    return candidates[0][1]


def load_workspace_manifest(workspace):
    path = Path(workspace) / master.MASTER_MANIFEST
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data.get("sources"):
        raise RuntimeError("고품질 번역 작업 정보가 비어 있습니다.")
    data.setdefault("game_name", game_name_from_workspace(workspace))
    data.setdefault("game_id", game_id_from_sources(data.get("sources", {})))
    data.setdefault("result_prefix", f"{data['game_name']}TL")
    return data


def find_matching_results(game_path, workspace, manifest=None):
    manifest = manifest or load_workspace_manifest(workspace)
    prefix = manifest.get("result_prefix") or f"{manifest.get('game_name', game_name_from_path(game_path))}TL"
    expected_game_id = manifest.get("game_id") or game_id_from_sources(manifest.get("sources", {}))
    roots = [downloads_root(game_path), Path(workspace), Path(workspace) / master.TRANSLATED_DIR]
    seen = set()
    rows = []
    for root in roots:
        for path in _candidate_result_files(root, prefix):
            try:
                key = str(path.resolve()).lower()
            except Exception:
                key = str(path).lower()
            if key in seen:
                continue
            seen.add(key)
            parsed, meta, verified = parse_result_v050(path, manifest["sources"], expected_game_id)
            if not parsed:
                continue
            rows.append({
                "path": path,
                "count": len(parsed),
                "verified": verified,
                "game_id_present": bool(meta.get("game_id")),
                "mtime": path.stat().st_mtime if path.exists() else 0,
                "first_id": min(parsed) if parsed else "",
                "last_id": max(parsed) if parsed else "",
            })
    rows.sort(key=lambda row: row["mtime"])
    return rows


def combine_result_files(manifest, files, require_complete=True):
    sources = manifest.get("sources", {})
    expected_game_id = manifest.get("game_id") or game_id_from_sources(sources)
    translations = {}
    used = []
    verified_count = 0
    invalid = []
    files = sorted([Path(p) for p in files], key=lambda p: p.stat().st_mtime if p.exists() else 0)
    for path in files:
        parsed, meta, verified = parse_result_v050(path, sources, expected_game_id)
        if not parsed:
            invalid.append(path.name)
            continue
        translations.update(parsed)  # newest file wins because files are mtime-sorted
        used.append(path)
        if verified:
            verified_count += 1
    if not used:
        raise RuntimeError("선택한 파일에서 이 게임의 번역 결과를 찾지 못했습니다.")
    missing = [item_id for item_id in sources if item_id not in translations]
    if require_complete and missing:
        raise RuntimeError(
            f"아직 번역되지 않은 문장이 {len(missing):,}개 있습니다. "
            f"예: {', '.join(missing[:5])}\n모든 결과 파일을 받은 뒤 다시 합성하세요."
        )
    return {
        "translations": translations,
        "missing": missing,
        "used": used,
        "invalid": invalid,
        "verified_files": verified_count,
    }


def build_patch_tree(manifest, translations, patch_root):
    target_lang = manifest.get("target_lang", "한국어")
    target_dir = core.LANGS.get(target_lang, core.LANGS["한국어"])[0]
    sources = manifest.get("sources", {})
    patch_root = Path(patch_root)
    patch_root.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Generated by RenPy Tools v0.5.0 high-quality merge",
        f"translate {target_dir} strings:",
        "",
    ]
    for item_id, old in sources.items():
        new = translations.get(item_id)
        if not new:
            continue
        lines.extend([
            f'    old "{core.escape_rpy(old)}"',
            f'    new "{core.escape_rpy(new)}"',
            "",
        ])
    output = patch_root / "renpytools_strings.rpy"
    output.write_text("\n".join(lines), encoding="utf-8")
    return target_dir, output


def next_available(path):
    path = Path(path)
    if not path.exists():
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{path.stem}_{int(time.time())}{path.suffix}")


def merge_apply_and_build_exe(app, manifest, files, game_path):
    combined = combine_result_files(manifest, files, require_complete=True)
    game = app.resolve_game_for_apply(game_path, reject_decompiled=False)
    if game is None:
        raise RuntimeError("선택한 폴더에서 game 폴더를 찾지 못했습니다.")
    game_name = manifest.get("game_name") or game_name_from_path(game_path)
    output_dir = downloads_root(game_path)

    with tempfile.TemporaryDirectory() as td:
        patch_root = Path(td) / "patch"
        target_dir, _ = build_patch_tree(manifest, combined["translations"], patch_root)

        # First apply the same payload to the creator's selected game for immediate testing.
        destination, backup = app.apply_patch_to_game(patch_root, game, target_dir)

        # Then turn that exact payload into the one-file distribution patch.
        old_output = getattr(app, "output_zip", None)
        placeholder = output_dir / f"{game_name}TL.zip"
        app.output_zip = placeholder
        try:
            built = Path(app.build_standalone_patch(patch_root, target_dir))
        finally:
            app.output_zip = old_output
        final_exe = next_available(output_dir / f"{game_name}TL.exe")
        if final_exe.exists():
            final_exe.unlink()
        built.replace(final_exe)

    return {
        "exe": final_exe,
        "destination": destination,
        "backup": backup,
        "translations": len(combined["translations"]),
        "files": len(combined["used"]),
        "verified_files": combined["verified_files"],
    }


def scan_master_results_v050(workspace, preferred_path=None, roots=None):
    """Progress watcher only. It never creates a combined file or patch."""
    workspace = Path(workspace)
    manifest = load_workspace_manifest(workspace)
    sources = manifest.get("sources", {})
    expected_game_id = manifest.get("game_id")
    prefix = manifest.get("result_prefix")
    if roots is None:
        roots = [downloads_root(preferred_path), workspace]
    translated_dir = workspace / master.TRANSLATED_DIR
    translated_dir.mkdir(parents=True, exist_ok=True)
    memory_path = translated_dir / "translation_memory.json"
    try:
        memory = json.loads(memory_path.read_text(encoding="utf-8")) if memory_path.exists() else {}
    except Exception:
        memory = {}
    imported = 0
    for root in roots:
        for path in _candidate_result_files(root, prefix):
            parsed, meta, _ = parse_result_v050(path, sources, expected_game_id)
            if expected_game_id and meta.get("game_id") and meta.get("game_id") != expected_game_id:
                continue
            before = len(memory)
            memory.update(parsed)
            imported += max(0, len(memory) - before)
            if parsed:
                try:
                    dest = translated_dir / path.name
                    if path.resolve() != dest.resolve():
                        shutil.copy2(path, dest)
                except Exception:
                    pass
    memory_path.write_text(json.dumps(memory, ensure_ascii=False, indent=2), encoding="utf-8")
    return imported, memory


def run_v050_self_test():
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sources = {
                "RT0000001": "Good morning, {name}.",
                "RT0000002": "Score: [score]",
            }
            manifest = {
                "target_lang": "한국어",
                "game_name": "Tree",
                "game_id": game_id_from_sources(sources),
                "result_prefix": "TreeTL",
                "sources": sources,
            }
            result1 = root / "TreeTL_001.txt"
            result2 = root / "TreeTL_002.txt"
            result1.write_text(
                f"# format: {RESULT_FORMAT}\n# game_id: {manifest['game_id']}\n"
                'RT0000001\t"좋은 아침, {name}."\n', encoding="utf-8"
            )
            result2.write_text(
                f"# format: {RESULT_FORMAT}\n# game_id: {manifest['game_id']}\n"
                'RT0000002\t"점수: [score]"\n', encoding="utf-8"
            )
            merged = combine_result_files(manifest, [result1, result2])
            assert len(merged["translations"]) == 2
            assert merged["verified_files"] == 2
            patch = root / "patch"
            target, file = build_patch_tree(manifest, merged["translations"], patch)
            assert target == "korean" and file.is_file()
            text = file.read_text(encoding="utf-8")
            assert "좋은 아침" in text and "[score]" in text
            bad = root / "TreeTL_bad.txt"
            bad.write_text(
                f"# game_id: {manifest['game_id']}\nRT0000001\t\"토큰 손실\"\n", encoding="utf-8"
            )
            parsed, _, _ = parse_result_v050(bad, sources, manifest["game_id"])
            assert not parsed
        return 0
    except Exception as exc:
        try:
            Path("RenPyTools-v050-selftest-error.txt").write_text(repr(exc), encoding="utf-8")
        except Exception:
            pass
        return 1
