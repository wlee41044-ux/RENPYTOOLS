#!/usr/bin/env python3
import sys

from RenPyToolsLauncherV056Stable import run_all_self_tests as run_v056_tests


def run_all_self_tests():
    # Run all inherited regression tests before importing v0.5.7.
    # v057_choice_compat imports the v0.5.5 launcher, which installs the strict
    # decompile gate. Loading that too early changes behavior expected by older
    # fallback tests and causes a false CI failure on their synthetic RPYC.
    code = run_v056_tests()
    if code:
        return code

    from v057_choice_compat import run_v057_self_test
    return run_v057_self_test()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_all_self_tests())

    from RenPyToolsLauncherV057 import RenPyToolsV057
    RenPyToolsV057().mainloop()
