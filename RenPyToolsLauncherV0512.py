#!/usr/bin/env python3

import RenPyToolsApp as ui_module
from RenPyToolsLauncherV0511 import RenPyToolsV0511
from v0512_hq_speed_prompt import install_v0512_hq_speed_prompt

ui_module.UI_VERSION = "0.5.12"


class RenPyToolsV0512(RenPyToolsV0511):
    """v0.5.12: faster HQ AI work prompt + independent parallel parts."""

    def __init__(self):
        super().__init__()
        # Parent v0.5.9 installs its own HQ builder during init, so install the
        # speed wrapper after all inherited initializers have finished.
        install_v0512_hq_speed_prompt()
        ui_module.UI_VERSION = "0.5.12"
        self.title("RenPy Tools 0.5.12")
        self.render()


if __name__ == "__main__":
    RenPyToolsV0512().mainloop()
