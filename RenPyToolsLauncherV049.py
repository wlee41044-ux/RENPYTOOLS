#!/usr/bin/env python3
import sys

import RenPyToolsApp as ui_module
import RenPyToolsLauncherV048 as v048_launcher
import v048_master_hq as master_hq
from RenPyToolsLauncherV048 import RenPyToolsV048
from v048_master_hq import run_v048_self_test
from v049_compat import (
    install_v049_compat,
    iter_extract_strings_stream_compat,
    run_v049_self_test,
)
from v050_workspace import hq_workspace_for_v050, run_v050_workspace_self_test

# Patch both the quick translator and v0.4.8's master-HQ extractor before UI use.
install_v049_compat()
master_hq.iter_extract_strings_stream = iter_extract_strings_stream_compat
# Inherited HQ preparation looks up hq_workspace_for in the v0.4.8 module.
# Replace it so Android/Winlator users get Download/<Game> TL.RENPY/<timestamp>/.
v048_launcher.hq_workspace_for = hq_workspace_for_v050
ui_module.UI_VERSION = "0.4.9"


class RenPyToolsV049(RenPyToolsV048):
    """v0.4.9: cross-game translation key + language/font compatibility hotfix."""

    def __init__(self):
        super().__init__()
        install_v049_compat()
        master_hq.iter_extract_strings_stream = iter_extract_strings_stream_compat
        v048_launcher.hq_workspace_for = hq_workspace_for_v050
        ui_module.UI_VERSION = "0.4.9"
        self.title("RenPy Tools 0.4.9")
        self.render()


def run_all_self_tests():
    code = run_v048_self_test()
    if code:
        return code
    code = run_v049_self_test()
    if code:
        return code
    return run_v050_workspace_self_test()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_all_self_tests())
    RenPyToolsV049().mainloop()
