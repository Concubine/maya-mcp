"""Probe #824 part 4: WHY are isolate captures blank in this Maya process?

Gate check 6 (isolate=[|red] + target=|red, back) drew 0 red px; probe c
then drew 0 opaque px for five isolate captures in a row, while non-isolate
captures 7 and 8 between them were fine, and the same isolate call in the
previous Maya process drew 14884 red. Ask the process, not the theory:

  1. main window visible / minimized; every model panel's isolate state and
     its ViewSelectedSet members; which panel find_model_panel picks.
  2. an isolate capture with _grab_pixels wrapped to record the panel's
     isolate state and set members at playblast time, plus the panel's
     camera and whether |red is visible in it.
  3. target_occlusion monkeypatched to None (removes the #824 code from the
     path) - does the isolate capture still come back blank?
  4. isolate via the handler's own _apply_isolate by hand, then a plain
     playblast of the panel: opaque px.

Run:  MAYA_MCP_PORT=9878 python evals/occlusion_probe_824d.py
"""
import base64
import io
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import occlusion_probe_824 as p1  # noqa: E402

OUT = p1.OUT


def opaque(png_b64):
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(io.BytesIO(base64.b64decode(png_b64))).convert("RGBA")).astype(int)
    r, g, b, al = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
    return {"opaque": int((al > 0).sum()), "red": int(((r > 120) & (g < 90) & (b < 90)).sum())}


LIB = r'''
import maya.cmds as cmds
from maya_plugin.handlers import capture

def window_state():
    try:
        from maya.OpenMayaUI import MQtUtil
        from shiboken6 import wrapInstance
        from PySide6.QtWidgets import QWidget
        w = wrapInstance(int(MQtUtil.mainWindow()), QWidget)
        return {"visible": w.isVisible(), "minimized": w.isMinimized(), "hidden": w.isHidden()}
    except Exception as e:
        return {"error": repr(e)}

def panel_state():
    out = {}
    for p in cmds.getPanel(type="modelPanel") or []:
        vs = cmds.modelEditor(p, q=True, viewSelected=True)
        so = cmds.modelEditor(p, q=True, viewObjects=True)
        members = cmds.sets(so, q=True) if so else None
        out[p] = {"viewSelected": vs, "set": so, "members": members,
                  "camera": cmds.modelPanel(p, q=True, camera=True),
                  "visible_panel": p in (cmds.getPanel(visiblePanels=True) or [])}
    out["picked"] = capture.find_model_panel(cmds)
    out["focus"] = cmds.getPanel(withFocus=True)
    return out
'''


def main():
    py = p1.py
    py(LIB + "\nr = 1")
    py("r = red_blue_scene()" if False else "import maya.cmds as cmds\nr = 1")
    p1.ok("new_scene", {"confirm": True})
    py(p1.LIB + "\nr = red_blue_scene()")
    py(LIB + "\nr = 1")
    p1.show("D1_before", py("r = {'window': window_state(), 'panels': panel_state()}"))

    # 2. wrap _grab_pixels to record state at playblast time
    py('''
        _orig_grab = capture._grab_pixels
        SEEN = []
        def spy_grab(cmds_, panel, resolution):
            so = cmds.modelEditor(panel, q=True, viewObjects=True)
            SEEN.append({"panel": panel, "viewSelected": cmds.modelEditor(panel, q=True, viewSelected=True),
                         "set": so, "members": cmds.sets(so, q=True) if so else None,
                         "camera": cmds.modelPanel(panel, q=True, camera=True),
                         "red_visible": cmds.getAttr("|red.visibility"),
                         "window": window_state()})
            return _orig_grab(cmds_, panel, resolution)
        capture._grab_pixels = spy_grab
        r = 1
    ''')
    res = p1.ok("capture_viewport", {"angles": ["back"], "target": ["|red"], "isolate": ["|red"], "resolution": 256, "shading": "flatShaded"})
    p1.show("D2_isolate_spied", {"pixels": opaque(res["images"][0]["png_b64"]), "blank": res["images"][0].get("blank"),
                                 "seen": py("r = SEEN"), "after": py("r = panel_state()")})

    # 3. without the #824 code in the path
    py("capture._orig_occ = capture.target_occlusion\ncapture.target_occlusion = lambda *a, **k: None\nr = 1")
    res = p1.ok("capture_viewport", {"angles": ["back"], "target": ["|red"], "isolate": ["|red"], "resolution": 256, "shading": "flatShaded"})
    p1.show("D3_isolate_no_824", {"pixels": opaque(res["images"][0]["png_b64"]), "blank": res["images"][0].get("blank")})
    py("capture.target_occlusion = capture._orig_occ\ncapture._grab_pixels = _orig_grab\nr = 1")

    # non-isolate control in the same state
    res = p1.ok("capture_viewport", {"angles": ["back"], "target": ["|red"], "resolution": 256, "shading": "flatShaded"})
    p1.show("D3b_no_isolate_control", {"pixels": opaque(res["images"][0]["png_b64"]), "blank": res["images"][0].get("blank")})

    # 4. isolate by hand + plain playblast
    p1.show("D4_manual_isolate", py('''
        import os, tempfile
        panel = capture.find_model_panel(cmds)
        capture._apply_isolate(cmds, panel, ["|red"])
        so = cmds.modelEditor(panel, q=True, viewObjects=True)
        members = cmds.sets(so, q=True) if so else None
        cmds.lookThru(panel, "persp")
        cmds.select("|red"); cmds.viewFit("persp"); cmds.select(clear=True)
        path = os.path.join(tempfile.gettempdir(), "d4.png")
        cmds.setFocus(panel)
        cmds.playblast(frame=[1], format="image", compression="png", completeFilename=path, offScreen=True, viewer=False,
                       showOrnaments=False, widthHeight=[256, 256], percent=100, quality=100, forceOverwrite=True)
        import base64
        data = base64.b64encode(open(path, "rb").read()).decode("ascii")
        for m in members or []:
            try: cmds.isolateSelect(panel, removeDagObject=m)
            except Exception: pass
        cmds.isolateSelect(panel, state=0)
        r = {"panel": panel, "set": so, "members": members, "png": data}
    '''))
    d4 = p1.FINDINGS["D4_manual_isolate"]
    p1.show("D4_pixels", opaque(d4.pop("png")))


if __name__ == "__main__":
    main()
