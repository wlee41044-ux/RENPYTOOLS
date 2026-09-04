#!/usr/bin/env python3
import sys

from RenPyToolsLauncherV050Stable import run_all_self_tests as run_v050_tests
from RenPyToolsLauncherV051 import RenPyToolsV051
from v051_prepare import run_v051_prepare_self_test


def run_all_self_tests():
    code = run_v050_tests()
    if code:
        return code
    return run_v051_prepare_self_test()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_all_self_tests())
    RenPyToolsV051().mainloop()
