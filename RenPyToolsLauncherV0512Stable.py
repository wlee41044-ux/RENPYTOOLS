#!/usr/bin/env python3
import sys

from RenPyToolsLauncherV0511Stable import run_all_self_tests as run_v0511_tests


def run_all_self_tests():
    code = run_v0511_tests()
    if code:
        return code
    from v0512_hq_speed_prompt import run_v0512_self_test
    return run_v0512_self_test()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_all_self_tests())

    from RenPyToolsLauncherV0512 import RenPyToolsV0512
    RenPyToolsV0512().mainloop()
