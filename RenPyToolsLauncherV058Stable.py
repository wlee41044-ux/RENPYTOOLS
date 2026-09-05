#!/usr/bin/env python3
import sys

from RenPyToolsLauncherV057Stable import run_all_self_tests as run_v057_tests


def run_all_self_tests():
    # Keep v0.5.8 imports after inherited tests so strict-decompile monkeypatches
    # do not alter older synthetic regression fixtures.
    code = run_v057_tests()
    if code:
        return code
    from v058_hq_file_split import run_v058_self_test
    return run_v058_self_test()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_all_self_tests())

    from RenPyToolsLauncherV058 import RenPyToolsV058
    RenPyToolsV058().mainloop()
