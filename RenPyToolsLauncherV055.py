#!/usr/bin/env python3

import RenPyToolsApp as ui_module
from RenPyToolsLauncherV054 import RenPyToolsV054
from v055_release_payload import (
    install_v055_strict_prepare,
    prepare_final_payload,
    repack_existing_zip,
)

install_v055_strict_prepare()
ui_module.UI_VERSION = "0.5.5"


class RenPyToolsV055(RenPyToolsV054):
    """v0.5.5: strict decompile gate + finalize one identical patch payload before sharing/apply."""

    def __init__(self):
        install_v055_strict_prepare()
        super().__init__()
        install_v055_strict_prepare()
        ui_module.UI_VERSION = "0.5.5"
        self.title("RenPy Tools 0.5.5")
        self.render()

    def build_standalone_patch(self, patch_root, target_dir):
        # Legacy worker reaches this hook after its first ZIP write but BEFORE
        # standalone packaging and local auto-apply. Finalize the payload here,
        # then rewrite the ZIP so all three outputs use the exact same files.
        structure = prepare_final_payload(self, patch_root, target_dir)
        if structure:
            self.add_log(
                f"[정식 tl 구조 생성] {structure['template_language']} 구조 기준 · "
                f"파일 {structure['files']}개 · 대사 블록 {structure['dialogue_blocks']}개"
            )
        else:
            self.add_log("[tl 구조] 기존 번역 템플릿 없음 · strings 호환 방식 유지")
        repack_existing_zip(self, patch_root)
        return super().build_standalone_patch(patch_root, target_dir)


if __name__ == "__main__":
    RenPyToolsV055().mainloop()
