#!/usr/bin/env python3

import RenPyToolsApp as ui_module
from RenPyToolsLauncherV0510 import RenPyToolsV0510
from v0511_merge_speed import install_v0511_merge_speedfix

install_v0511_merge_speedfix()
ui_module.UI_VERSION = "0.5.11"


class RenPyToolsV0511(RenPyToolsV0510):
    """v0.5.11: avoid scanning the shared Temp directory during HQ merge."""

    def __init__(self):
        install_v0511_merge_speedfix()
        super().__init__()
        install_v0511_merge_speedfix()
        ui_module.UI_VERSION = "0.5.11"
        self.title("RenPy Tools 0.5.11")
        self.render()


if __name__ == "__main__":
    RenPyToolsV0511().mainloop()
