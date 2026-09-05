#!/usr/bin/env python3
import sys

from RenPyToolsLauncherV0510Stable import run_all_self_tests as run_v0510_tests


def run_all_self_tests():
    code = run_v0510_tests()
    if code:
        return code
    from v0511_merge_speed import run_v0511_self_test
    return run_v0511_self_test()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_all_self_tests())

    from RenPyToolsLauncherV0511 import RenPyToolsV0511
    RenPyToolsV0511().mainloop()
