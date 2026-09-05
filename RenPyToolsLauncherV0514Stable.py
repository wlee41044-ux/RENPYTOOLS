#!/usr/bin/env python3
import sys

from RenPyToolsLauncherV0513Stable import run_all_self_tests as run_v0513_tests


def run_all_self_tests():
    code = run_v0513_tests()
    if code:
        return code
    from v0514_hq_payload_sync import run_v0514_self_test
    return run_v0514_self_test()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_all_self_tests())

    from RenPyToolsLauncherV0514 import RenPyToolsV0514
    RenPyToolsV0514().mainloop()
