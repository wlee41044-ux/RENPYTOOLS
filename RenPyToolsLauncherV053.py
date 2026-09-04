#!/usr/bin/env python3

import RenPyToolsApp as ui_module
from RenPyToolsLauncherV052 import RenPyToolsV052
from v053_template_tl import install_v053_template_tl

install_v053_template_tl()
ui_module.UI_VERSION = "0.5.3"


class RenPyToolsV053(RenPyToolsV052):
    """v0.5.3: reuse existing tl language files as exact Ren'Py dialogue-ID templates."""

    def __init__(self):
        install_v053_template_tl()
        super().__init__()
        install_v053_template_tl()
        ui_module.UI_VERSION = "0.5.3"
        self.title("RenPy Tools 0.5.3")
        self.render()


if __name__ == "__main__":
    RenPyToolsV053().mainloop()
