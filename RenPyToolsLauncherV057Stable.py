#!/usr/bin/env python3
import sys

from RenPyToolsLauncherV056Stable import run_all_self_tests as run_v056_tests
from v057_choice_compat import run_v057_self_test


def run_all_self_tests():
    code = run_v056_tests()
    if code:
        return code
    return run_v057_self_test()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_all_self_tests())

    from RenPyToolsLauncherV057 import RenPyToolsV057
    RenPyToolsV057().mainloop()
