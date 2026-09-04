#!/usr/bin/env python3
import sys

import RenPyToolsApp as ui_module
import RenPyToolsLauncherV048 as v048_launcher
import v048_master_hq as master_hq
from RenPyToolsLauncherV051 import RenPyToolsV051
from v052_render_compat import (
    install_v052_render_compat,
    iter_extract_strings_stream_v052,
)

install_v052_render_compat()
# The inherited HQ builder resolves its extractor through v048_master_hq.
master_hq.iter_extract_strings_stream = iter_extract_strings_stream_v052
ui_module.UI_VERSION = "0.5.2"


class RenPyToolsV052(RenPyToolsV051):
    """v0.5.2: bundled Korean font + short dialogue/menu translation compatibility."""

    def __init__(self):
        install_v052_render_compat()
        master_hq.iter_extract_strings_stream = iter_extract_strings_stream_v052
        super().__init__()
        install_v052_render_compat()
        master_hq.iter_extract_strings_stream = iter_extract_strings_stream_v052
        ui_module.UI_VERSION = "0.5.2"
        self.title("RenPy Tools 0.5.2")
        self.render()


if __name__ == "__main__":
    RenPyToolsV052().mainloop()
