#!/usr/bin/env python3
import sys

from RenPyToolsLauncherV048 import RenPyToolsV048
from v048_ci_selftest import run_v048_ci_self_test


def run_all_self_tests():
    # Core RenPy tests run separately in CI. This v0.4.8 test exercises the new
    # master-TXT workflow with realistic dialogue fixtures.
    return run_v048_ci_self_test()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_all_self_tests())
    RenPyToolsV048().mainloop()
