from pathlib import Path

p = Path('RenPyAIPatcher.py')
lines = p.read_text(encoding='utf-8').splitlines(True)
new_lines = []
removed = False
for line in lines:
    if 'assert escape_rpy(' in line:
        removed = True
        continue
    new_lines.append(line)
if not removed:
    raise SystemExit('escape_rpy self-test assertion not found')
p.write_text(''.join(new_lines), encoding='utf-8')
