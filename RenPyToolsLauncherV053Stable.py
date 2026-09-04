#!/usr/bin/env python3
import sys

from RenPyToolsLauncherV052Stable import run_all_self_tests as run_v052_tests
from RenPyToolsLauncherV053 import RenPyToolsV053
from v053_template_tl import run_v053_self_test


def run_all_self_tests():
    code = run_v052_tests()
    if code:
        return code
    return run_v053_self_test()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_all_self_tests())
    RenPyToolsV053().mainloop()
