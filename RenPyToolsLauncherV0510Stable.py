#!/usr/bin/env python3
import sys

from RenPyToolsLauncherV059Stable import run_all_self_tests as run_v059_tests


def run_all_self_tests():
    code = run_v059_tests()
    if code:
        return code
    from v0510_async_merge import run_v0510_self_test
    return run_v0510_self_test()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_all_self_tests())

    from RenPyToolsLauncherV0510 import RenPyToolsV0510
    RenPyToolsV0510().mainloop()
