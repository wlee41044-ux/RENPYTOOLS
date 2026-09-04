#!/usr/bin/env python3
import sys

import RenPyToolsApp as ui_module
from RenPyToolsLauncherV050 import RenPyToolsV050
from v051_prepare import install_v051_prepare

install_v051_prepare()
ui_module.UI_VERSION = "0.5.1"


class RenPyToolsV051(RenPyToolsV050):
    """v0.5.1: always prepare/decompile compiled or archived scripts before translation."""

    def __init__(self):
        install_v051_prepare()
        super().__init__()
        ui_module.UI_VERSION = "0.5.1"
        self.title("RenPy Tools 0.5.1")
        self.render()


if __name__ == "__main__":
    RenPyToolsV051().mainloop()
