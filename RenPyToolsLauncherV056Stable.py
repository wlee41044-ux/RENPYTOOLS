#!/usr/bin/env python3
import sys

from RenPyToolsLauncherV055Stable import run_all_self_tests as run_v055_tests
from v056_global_ui_font import run_v056_self_test


def run_all_self_tests():
    code = run_v055_tests()
    if code:
        return code
    return run_v056_self_test()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_all_self_tests())

    from RenPyToolsLauncherV056 import RenPyToolsV056
    RenPyToolsV056().mainloop()
