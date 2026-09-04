#!/usr/bin/env python3
import sys

from RenPyToolsLauncherV051Stable import run_all_self_tests as run_v051_tests
from RenPyToolsLauncherV052 import RenPyToolsV052
from v052_render_compat import run_v052_self_test


def run_all_self_tests():
    code = run_v051_tests()
    if code:
        return code
    return run_v052_self_test()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_all_self_tests())
    RenPyToolsV052().mainloop()
