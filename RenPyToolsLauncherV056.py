#!/usr/bin/env python3

import RenPyToolsApp as ui_module
from RenPyToolsLauncherV055 import RenPyToolsV055
from v056_global_ui_font import install_v056_global_ui_font

install_v056_global_ui_font()
ui_module.UI_VERSION = "0.5.6"


class RenPyToolsV056(RenPyToolsV055):
    """v0.5.6: global Korean font compatibility for choices and in-game settings."""

    def __init__(self):
        install_v056_global_ui_font()
        super().__init__()
        install_v056_global_ui_font()
        ui_module.UI_VERSION = "0.5.6"
        self.title("RenPy Tools 0.5.6")
        self.render()


if __name__ == "__main__":
    RenPyToolsV056().mainloop()
