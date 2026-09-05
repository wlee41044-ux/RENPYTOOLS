#!/usr/bin/env python3

import RenPyToolsApp as ui_module
from RenPyToolsLauncherV0512 import RenPyToolsV0512
from v0513_backup_safety import install_v0513_backup_safety

install_v0513_backup_safety()
ui_module.UI_VERSION = "0.5.13"


class RenPyToolsV0513(RenPyToolsV0512):
    """v0.5.13: keep backup .rpy files outside game/ to prevent duplicate translations."""

    def __init__(self):
        install_v0513_backup_safety()
        super().__init__()
        install_v0513_backup_safety()
        ui_module.UI_VERSION = "0.5.13"
        self.title("RenPy Tools 0.5.13")
        self.render()


if __name__ == "__main__":
    RenPyToolsV0513().mainloop()
