#!/usr/bin/env python3
import sys

from RenPyToolsLauncherV058Stable import run_all_self_tests as run_v058_tests


def run_all_self_tests():
    # Keep v0.5.9 imports after inherited regression tests so its runtime
    # monkeypatches cannot change older fixtures in the same interpreter.
    code = run_v058_tests()
    if code:
        return code
    from v059_hq_result_discovery import run_v059_self_test
    return run_v059_self_test()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_all_self_tests())

    from RenPyToolsLauncherV059 import RenPyToolsV059
    RenPyToolsV059().mainloop()
