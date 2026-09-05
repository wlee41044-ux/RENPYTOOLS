#!/usr/bin/env python3
import sys

from RenPyToolsLauncherV0512Stable import run_all_self_tests as run_v0512_tests


def run_all_self_tests():
    code = run_v0512_tests()
    if code:
        return code
    from v0513_backup_safety import run_v0513_self_test
    return run_v0513_self_test()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_all_self_tests())

    from RenPyToolsLauncherV0513 import RenPyToolsV0513
    RenPyToolsV0513().mainloop()
