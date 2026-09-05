#!/usr/bin/env python3

import RenPyToolsApp as ui_module
from RenPyToolsLauncherV056 import RenPyToolsV056
from v056_global_ui_font import install_v056_global_ui_font
from v057_choice_compat import install_v057_choice_compat

install_v056_global_ui_font()
install_v057_choice_compat()
ui_module.UI_VERSION = "0.5.7"


class RenPyToolsV057(RenPyToolsV056):
    """v0.5.7: language-time choice style compatibility for Korean."""

    def __init__(self):
        install_v056_global_ui_font()
        install_v057_choice_compat()
        super().__init__()
        install_v056_global_ui_font()
        install_v057_choice_compat()
        ui_module.UI_VERSION = "0.5.7"
        self.title("RenPy Tools 0.5.7")
        self.render()


if __name__ == "__main__":
    RenPyToolsV057().mainloop()
