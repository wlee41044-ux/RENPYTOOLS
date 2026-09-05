#!/usr/bin/env python3

import RenPyToolsApp as ui_module
from RenPyToolsLauncherV057 import RenPyToolsV057
from v058_hq_file_split import install_v058_hq_file_split

install_v058_hq_file_split()
ui_module.UI_VERSION = "0.5.8"


class RenPyToolsV058(RenPyToolsV057):
    """v0.5.8: split HQ master TXT by model/profile token and file-size targets."""

    def __init__(self):
        install_v058_hq_file_split()
        super().__init__()
        install_v058_hq_file_split()
        ui_module.UI_VERSION = "0.5.8"
        self.title("RenPy Tools 0.5.8")
        self.render()


if __name__ == "__main__":
    RenPyToolsV058().mainloop()
