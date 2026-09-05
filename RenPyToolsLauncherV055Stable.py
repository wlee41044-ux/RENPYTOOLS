#!/usr/bin/env python3
import sys

from RenPyToolsLauncherV054Stable import run_all_self_tests as run_v054_tests
from RenPyToolsLauncherV055 import RenPyToolsV055
from v055_release_payload import run_v055_self_test


def run_all_self_tests():
    code = run_v054_tests()
    if code:
        return code
    return run_v055_self_test()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_all_self_tests())
    RenPyToolsV055().mainloop()
