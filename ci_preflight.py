#!/usr/bin/env python3
"""Fast CI gate that must pass before the Windows installer workflow starts."""
import ast
import compileall
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ERROR_GLOBS = (
    "RenPyTools*-error.txt",
    "RenPyAIPatcher*-error.txt",
)


def fail(message):
    print(f"PRECHECK FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def print_error_files():
    seen = set()
    for pattern in ERROR_GLOBS:
        for path in ROOT.glob(pattern):
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            try:
                print(f"\n--- {path.name} ---\n{path.read_text(encoding='utf-8', errors='replace')}")
            except Exception:
                pass


def run_isolated(*args):
    print("+", sys.executable, *args)
    proc = subprocess.run([sys.executable, *args], cwd=ROOT)
    if proc.returncode:
        print_error_files()
        fail(f"command failed with exit code {proc.returncode}: {' '.join(args)}")


def check_version_sync():
    from RenPyToolsCurrent import CURRENT_VERSION
    installer = (ROOT / "installer.iss").read_text(encoding="utf-8", errors="replace")
    match = re.search(r'^#define\s+MyAppVersion\s+"([^"]+)"', installer, re.M)
    if not match:
        fail("installer.iss has no MyAppVersion")
    if match.group(1) != CURRENT_VERSION:
        fail(f"version mismatch: current={CURRENT_VERSION}, installer={match.group(1)}")
    print(f"Version sync OK: {CURRENT_VERSION}")


def check_frozen_safe_tests():
    """Reject real inspect.getsource calls in app/test modules without false positives from comments/strings."""
    bad = []
    for path in ROOT.glob("*.py"):
        # ci_preflight.py is a CI-only script and is never frozen into RenPyAIPatcher.exe.
        if path.resolve() == Path(__file__).resolve():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(text, filename=str(path))
        except Exception:
            continue

        imported_getsource_names = set()
        inspect_aliases = {"inspect"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "inspect":
                        inspect_aliases.add(alias.asname or alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module == "inspect":
                for alias in node.names:
                    if alias.name == "getsource":
                        imported_getsource_names.add(alias.asname or alias.name)

        unsafe = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "getsource"
                and isinstance(func.value, ast.Name)
                and func.value.id in inspect_aliases
            ):
                unsafe = True
                break
            if isinstance(func, ast.Name) and func.id in imported_getsource_names:
                unsafe = True
                break
        if unsafe:
            bad.append(path.name)

    if bad:
        fail(
            "frozen-unsafe source introspection found: " + ", ".join(sorted(bad))
            + ". Use behavior-based self-tests instead."
        )
    print("Frozen-EXE self-test safety OK")


def main():
    # Syntax errors are caught before any test module can mutate global state.
    if not compileall.compile_dir(str(ROOT), quiet=1, maxlevels=1):
        fail("Python syntax/compile check failed")
    check_version_sync()
    check_frozen_safe_tests()

    # Each major suite gets a fresh interpreter. This is deliberate: many legacy
    # compatibility layers monkeypatch launchers at import time, so sharing one
    # interpreter made unrelated old fixtures fail whenever a new version imported
    # a strict patch earlier than before.
    run_isolated("RenPyAIPatcher.py", "--self-test")
    run_isolated("RenPyToolsCurrent.py", "--self-test")
    print("PRECHECK PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
