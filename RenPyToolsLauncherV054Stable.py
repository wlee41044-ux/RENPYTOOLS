#!/usr/bin/env python3
import sys

from RenPyToolsLauncherV053Stable import run_all_self_tests as run_v053_tests
from RenPyToolsLauncherV054 import RenPyToolsV054


def run_all_self_tests():
    return run_v053_tests()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_all_self_tests())
    RenPyToolsV054().mainloop()
