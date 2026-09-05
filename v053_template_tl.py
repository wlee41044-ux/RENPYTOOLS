#!/usr/bin/env python3
import re
import tempfile
from pathlib import Path

import RenPyAIPatcher as core
from v049_compat import decode_rpy_text

_HEADER_RE = re.compile(
    r"(?m)^translate\s+(?P<lang>[A-Za-z_][A-Za-z0-9_]*)\s+"
    r"(?P<kind>[A-Za-z_][A-Za-z0-9_]*)(?P<rest>[^:\n]*)\s*:\s*$"
)
_FONT_OPEN_RE = re.compile(r"\{font=[^{}]*\}", re.I)
_FONT_CLOSE_RE = re.compile(r"\{/font\}", re.I)

_INSTALLED = False
_PREVIOUS_APPLY = None


def _literal_from_line(line):
    matches = list(core.STRING_RE.finditer(line))
    if not matches:
        return None
    match = matches[-1]
    return decode_rpy_text(match.group("text"), match.group("quote"))


def _replace_last_literal(line, value):
    matches = list(core.STRING_RE.finditer(line))
    if not matches:
        return line
    match = matches[-1]
    replacement = '"' + core.escape_rpy(value) + '"'
    return line[:match.start()] + replacement + line[match.end():]


def _korean_safe_text(value, target_dir):
    """Let the bundled Korean font win over font tags embedded in source text.

    Some games wrap menu/choice strings in {font=...} tags. RenPy Tools preserves
    text tags during translation, but an English/Japanese-only font tag overrides
    our Korean style fallback and renders the translated choice as boxes. Strip
    only font-selection tags from the translated value; all other Ren'Py tags are
    preserved and the source/old value is never modified.
    """
    if target_dir != "korean" or not isinstance(value, str):
        return value
    value = _FONT_OPEN_RE.sub("", value)
    value = _FONT_CLOSE_RE.sub("", value)
    return value


def _read_global_string_patch(patch_root):
    """Read the old v0.3.x/v0.5.x source->translation strings payload."""
    path = Path(patch_root) / "renpytools_strings.rpy"
    if not path.is_file():
        return {}, None
    mapping = {}
    pending = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("old "):
            pending = _literal_from_line(line)
        elif stripped.startswith("new ") and pending is not None:
            translated = _literal_from_line(line)
            if translated is not None:
                mapping[pending] = translated
            pending = None
    return mapping, path


def _translation_blocks(text):
    matches = list(_HEADER_RE.finditer(text))
    blocks = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks.append((match, text[match.start():end]))
    return blocks


def _template_score(path):
    scripts = [
        p for p in Path(path).rglob("*")
        if p.is_file() and p.suffix.lower() in {".rpy", ".rpym"}
    ]
    dialogue = 0
    strings = 0
    for script in scripts:
        try:
            text = script.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for match, _ in _translation_blocks(text):
            kind = match.group("kind").lower()
            rest = match.group("rest").strip()
            if kind == "strings":
                strings += 1
            elif kind not in {"python", "style"} and not rest:
                dialogue += 1
    return dialogue * 1000 + strings * 20 + len(scripts), dialogue, strings, len(scripts)


def find_best_translation_template(game_dir, target_dir="korean"):
    """Prefer an existing full tl/<language> tree, such as the game's Japanese patch."""
    tl = Path(game_dir) / "tl"
    if not tl.is_dir():
        return None
    candidates = []
    try:
        children = list(tl.iterdir())
    except Exception:
        return None
    for child in children:
        if not child.is_dir():
            continue
        if child.name.lower() in {target_dir.lower(), "none"}:
            continue
        score, dialogue, strings, scripts = _template_score(child)
        if score > 0:
            candidates.append((score, dialogue, strings, scripts, child))
    if not candidates:
        return None
    candidates.sort(key=lambda row: (row[0], row[1], row[3]), reverse=True)
    return candidates[0][4]


def _is_say_like(line):
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or not core.STRING_RE.search(line):
        return False
    lower = stripped.lower()
    blocked = (
        "old ", "new ", "voice ", "play ", "queue ", "scene ", "show ", "hide ",
        "image ", "define ", "default ", "python", "$", "init ", "style ", "transform ",
    )
    if lower.startswith(blocked):
        return False
    first = core.STRING_RE.search(line)
    if first and "=" in line[:first.start()]:
        return False
    return True


def _transform_dialogue_block(block, target_dir, translations):
    lines = block.splitlines()
    if not lines:
        return None, set()
    lines[0] = re.sub(
        r"^(translate\s+)[A-Za-z_][A-Za-z0-9_]*",
        rf"\g<1>{target_dir}",
        lines[0],
        count=1,
    )
    pending_source = None
    transformed = 0
    unsafe = False
    handled_sources = set()
    output = [lines[0]]

    for line in lines[1:]:
        stripped = line.strip()
        if stripped.startswith("#"):
            source = _literal_from_line(stripped[1:].lstrip())
            if source is not None:
                pending_source = source
            output.append(line)
            continue

        if _is_say_like(line):
            if pending_source is None:
                unsafe = True
                break
            translated = _korean_safe_text(translations.get(pending_source, pending_source), target_dir)
            output.append(_replace_last_literal(line, translated))
            handled_sources.add(pending_source)
            pending_source = None
            transformed += 1
            continue

        output.append(line)

    if unsafe or transformed == 0:
        return None, set()
    return "\n".join(output).rstrip() + "\n", handled_sources


def _string_pairs(block):
    pairs = []
    pending = None
    for line in block.splitlines()[1:]:
        stripped = line.strip()
        if stripped.startswith("old "):
            pending = _literal_from_line(line)
        elif stripped.startswith("new ") and pending is not None:
            pairs.append(pending)
            pending = None
    return pairs


def _render_strings_block(target_dir, sources, translations, seen):
    rows = []
    for old in sources:
        if old in seen:
            continue
        seen.add(old)
        new = _korean_safe_text(translations.get(old, old), target_dir)
        rows.extend([
            f'    old "{core.escape_rpy(old)}"',
            f'    new "{core.escape_rpy(new)}"',
            "",
        ])
    if not rows:
        return None
    return "\n".join([f"translate {target_dir} strings:", ""] + rows).rstrip() + "\n"


def augment_patch_from_existing_tl(patch_root, game_dir, target_dir="korean"):
    """Upgrade one global strings file into Ren'Py's normal per-script tl layout."""
    patch_root = Path(patch_root)
    translations, global_patch = _read_global_string_patch(patch_root)
    if not translations or global_patch is None:
        return None

    template = find_best_translation_template(game_dir, target_dir)
    if template is None:
        return None

    seen_strings = set()
    dialogue_sources = set()
    generated_files = 0
    dialogue_blocks = 0
    string_entries = 0

    scripts = sorted(
        p for p in template.rglob("*")
        if p.is_file() and p.suffix.lower() in {".rpy", ".rpym"}
    )
    for source_file in scripts:
        try:
            text = source_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        output_blocks = []
        file_string_sources = []
        for match, block in _translation_blocks(text):
            kind = match.group("kind").lower()
            rest = match.group("rest").strip()
            if kind == "strings":
                file_string_sources.extend(_string_pairs(block))
                continue
            if kind in {"python", "style"} or rest:
                continue
            transformed, handled = _transform_dialogue_block(block, target_dir, translations)
            if transformed:
                output_blocks.append(transformed)
                dialogue_sources.update(handled)
                dialogue_blocks += 1

        strings_block = _render_strings_block(
            target_dir, file_string_sources, translations, seen_strings
        )
        if strings_block:
            output_blocks.append(strings_block)
            string_entries += len([x for x in file_string_sources if x in seen_strings])

        if not output_blocks:
            continue
        rel = source_file.relative_to(template)
        destination = patch_root / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            "# Generated by RenPy Tools v0.5.6\n"
            f"# Translation structure copied from tl/{template.name}; target is {target_dir}.\n\n"
            + "\n".join(output_blocks).rstrip() + "\n",
            encoding="utf-8",
        )
        generated_files += 1

    if generated_files == 0 or dialogue_blocks == 0:
        return None

    extras = [
        old for old in translations
        if old not in seen_strings and old not in dialogue_sources
    ]
    extra_block = _render_strings_block(target_dir, extras, translations, seen_strings)
    if extra_block:
        (patch_root / "renpytools_extra_strings.rpy").write_text(
            "# Generated by RenPy Tools v0.5.6\n" + extra_block,
            encoding="utf-8",
        )

    global_patch.unlink(missing_ok=True)
    return {
        "template": str(template),
        "template_language": template.name,
        "files": generated_files,
        "dialogue_blocks": dialogue_blocks,
        "dialogue_sources": len(dialogue_sources),
        "string_sources": len(seen_strings),
        "extras": len(extras),
    }


def apply_patch_v053(self, patch_root, game_dir, target_dir):
    augment_patch_from_existing_tl(patch_root, game_dir, target_dir)
    return _PREVIOUS_APPLY(self, patch_root, game_dir, target_dir)


def install_v053_template_tl():
    global _INSTALLED, _PREVIOUS_APPLY
    if not _INSTALLED:
        _PREVIOUS_APPLY = core.PatcherApp.apply_patch_to_game
        core.PatcherApp.apply_patch_to_game = apply_patch_v053
        _INSTALLED = True
    return True


def run_v053_self_test():
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            game = root / "game"
            japanese = game / "tl" / "japanese"
            japanese.mkdir(parents=True)
            (japanese / "script.rpy").write_text(
                '# game/script.rpy:10\n'
                'translate japanese start_abcd1234:\n\n'
                '    # e "Hello, are you coming with me today?"\n'
                '    e "今日は一緒に来る？"\n\n'
                'translate japanese strings:\n\n'
                '    old "Yes"\n'
                '    new "はい"\n\n'
                '    old "No"\n'
                '    new "いいえ"\n',
                encoding="utf-8",
            )
            (japanese / "screens.rpy").write_text(
                'translate japanese strings:\n\n'
                '    old "Save"\n'
                '    new "保存"\n',
                encoding="utf-8",
            )

            patch = root / "patch"
            patch.mkdir()
            (patch / "renpytools_strings.rpy").write_text(
                'translate korean strings:\n\n'
                '    old "Hello, are you coming with me today?"\n'
                '    new "안녕, 오늘 나랑 같이 갈래?"\n\n'
                '    old "Yes"\n'
                '    new "{font=EnglishOnly.ttf}예{/font}"\n\n'
                '    old "No"\n'
                '    new "아니오"\n\n'
                '    old "Save"\n'
                '    new "저장"\n\n'
                '    old "Extra custom text"\n'
                '    new "추가 사용자 문구"\n',
                encoding="utf-8",
            )

            result = augment_patch_from_existing_tl(patch, game, "korean")
            assert result and result["template_language"] == "japanese"
            script = (patch / "script.rpy").read_text(encoding="utf-8")
            screens = (patch / "screens.rpy").read_text(encoding="utf-8")
            assert "translate korean start_abcd1234:" in script
            assert 'e "안녕, 오늘 나랑 같이 갈래?"' in script
            assert 'new "예"' in script and 'new "아니오"' in script
            assert "EnglishOnly.ttf" not in script
            assert 'new "저장"' in screens
            assert "今日は一緒に来る？" not in script
            assert not (patch / "renpytools_strings.rpy").exists()
            extra = (patch / "renpytools_extra_strings.rpy").read_text(encoding="utf-8")
            assert 'new "추가 사용자 문구"' in extra
        return 0
    except Exception as exc:
        try:
            Path("RenPyTools-v053-selftest-error.txt").write_text(repr(exc), encoding="utf-8")
        except Exception:
            pass
        return 1
