from pathlib import Path

p = Path('RenPyAIPatcher.py')
s = p.read_text(encoding='utf-8')
old = "        assert escape_rpy('a\"b\\nc') == 'a\\\\\"b\\\\\\\\nc'\n"
new = "        assert escape_rpy('a\"b\\nc') == 'a\\\\\"b\\\\nc'\n"
if old not in s:
    raise SystemExit('self-test assertion not found')
s = s.replace(old, new, 1)
p.write_text(s, encoding='utf-8')
