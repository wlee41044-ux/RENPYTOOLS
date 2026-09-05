#!/usr/bin/env python3
import sys

CURRENT_VERSION = "0.5.11"


def run_all_self_tests():
    # Import the current stable test chain only when tests are explicitly run.
    # This prevents launcher monkeypatch side effects during CI discovery/imports.
    from RenPyToolsLauncherV0511Stable import run_all_self_tests as run_current_tests
    return run_current_tests()


def launch_app():
    from RenPyToolsLauncherV0511 import RenPyToolsV0511
    RenPyToolsV0511().mainloop()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_all_self_tests())
    launch_app()
