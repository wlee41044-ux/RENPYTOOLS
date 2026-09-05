#!/usr/bin/env python3

import RenPyToolsApp as ui_module
from RenPyToolsLauncherV0513 import RenPyToolsV0513
from v0514_hq_payload_sync import install_v0514_hq_payload_sync

install_v0514_hq_payload_sync()
ui_module.UI_VERSION = "0.5.14"


class RenPyToolsV0514(RenPyToolsV0513):
    """v0.5.14: finalize one HQ payload before local apply and EXE packaging."""

    def __init__(self):
        install_v0514_hq_payload_sync()
        super().__init__()
        install_v0514_hq_payload_sync()
        ui_module.UI_VERSION = "0.5.14"
        self.title("RenPy Tools 0.5.14")
        self.render()


if __name__ == "__main__":
    RenPyToolsV0514().mainloop()
