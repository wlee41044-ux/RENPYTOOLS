#!/usr/bin/env python3
import sys

from RenPyToolsLauncherV048 import RenPyToolsV048
from v048_master_hq import run_v048_self_test


def run_all_self_tests():
    # v0.4.8 has its own end-to-end master-workflow test. Older-version tests
    # mutate the shared AI profile catalog, so chaining them in the same Python
    # process can create a false failure even though v0.4.7 itself already passed
    # CI. Core RenPy tests are still run separately by the workflow.
    return run_v048_self_test()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_all_self_tests())
    RenPyToolsV048().mainloop()
