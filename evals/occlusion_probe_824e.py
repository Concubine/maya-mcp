"""Probe #824 part 5: does the isolate view draw once the main window is
actually SHOWN (showNormal), and does it keep drawing after re-minimising?

Two of three agent Maya processes today drew 0 opaque px for every isolate
capture while non-isolate captures drew fine; the third drew 14884 red for
the same call. ensure_viewport_realized's window.show() leaves
isVisible()=False / isHidden()=True on these (probe d).

Run:  MAYA_MCP_PORT=9878 python evals/occlusion_probe_824e.py
"""
import base64
import io
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import occlusion_probe_824 as p1  # noqa: E402
import occlusion_probe_824d as p4  # noqa: E402


def iso_capture(label):
    res = p1.ok("capture_viewport", {"angles": ["back"], "target": ["|red"], "isolate": ["|red"],
                                     "resolution": 256, "shading": "flatShaded"})
    return {"pixels": p4.opaque(res["images"][0]["png_b64"]), "blank": res["images"][0].get("blank"),
            "window": p1.py("r = window_state()"),
            "never_shown_note": any("never been shown" in w for w in res["warnings"])}


def main():
    p1.ok("new_scene", {"confirm": True})
    p1.py(p1.LIB + "\nr = red_blue_scene()")
    p1.py(p4.LIB + "\nr = 1")
    p1.show("E1_isolate_as_launched", iso_capture("E1"))
    p1.show("E2_after_showNormal", dict(
        shown=p1.py('''
            from maya.OpenMayaUI import MQtUtil
            from shiboken6 import wrapInstance
            from PySide6.QtWidgets import QWidget
            w = wrapInstance(int(MQtUtil.mainWindow()), QWidget)
            w.showNormal()
            r = window_state()
        '''), **iso_capture("E2")))
    p1.show("E3_after_showMinimized", dict(
        shown=p1.py('''
            w.showMinimized()
            r = window_state()
        '''), **iso_capture("E3")))
    res = p1.ok("capture_viewport", {"angles": ["back"], "target": ["|red"], "resolution": 256, "shading": "flatShaded"})
    p1.show("E4_non_isolate_control", {"pixels": p4.opaque(res["images"][0]["png_b64"])})


if __name__ == "__main__":
    main()
