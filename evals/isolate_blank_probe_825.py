"""Throwaway probe for #825: why does EVERY isolate capture come back blank
in some agent-launched Maya processes while non-isolate captures in the SAME
process draw?

#824 established what it is NOT: not the occlusion code (reproduced with it
monkeypatched out) and not capture.py's isolate logic (reproduced with a
hand-rolled isolateSelect + viewFit + playblast). So this probe asks the
Maya-side question instead - what state does VP2's view-selected render need
that a never-realized window has not got, and what makes it appear?

Ordered so each step is a control for the next:

  A  as-launched state: window, panels, renderer, Maya's own idea of the GUI
  B  non-isolate / isolate / isolate-again, same process, same scene
  C  ogs(reset=True) then isolate      <- candidate root cause: stale VP2
  D  refresh(force=True) then isolate
  E  Qt showNormal - state in the SAME command, then in the NEXT one
     (#825 measured it reading hidden again afterwards; who re-hides it?)
  F  isolate after showNormal, then a non-isolate control at the end

Run:  MAYA_MCP_PORT=9879 python evals/isolate_blank_probe_825.py <tag>
The tag names the output dir, so a minimized launch and a normal one can be
compared side by side.
"""
import base64
import io
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import occlusion_probe_824 as p1  # noqa: E402

TAG = sys.argv[1] if len(sys.argv) > 1 else "run"
OUT = os.path.join(_HERE, "isolate_blank_probe_825", TAG)
os.makedirs(OUT, exist_ok=True)
FINDINGS = {}


def opaque(png_b64, name=None):
    """Opaque pixel count, and the dominant colour when there is one."""
    from PIL import Image
    img = Image.open(io.BytesIO(base64.b64decode(png_b64))).convert("RGBA")
    if name:
        img.save(os.path.join(OUT, name + ".png"))
    px = list(img.getdata())
    op = [p for p in px if p[3] > 0]
    red = sum(1 for p in op if p[0] > 110 and p[0] > p[2] + 40)
    blue = sum(1 for p in op if p[2] > 110 and p[2] > p[0] + 40)
    return {"opaque": len(op), "total": len(px), "red": red, "blue": blue}


def show(label, value):
    FINDINGS[label] = value
    with open(os.path.join(OUT, "findings.json"), "w", encoding="utf-8") as fh:
        json.dump(FINDINGS, fh, indent=1, default=str)
    print("\n--- %s ---" % label)
    print(json.dumps(value, indent=1, sort_keys=True, default=str))


def cap(label, isolate=True, save=True):
    params = {"angles": ["back"], "target": ["|red"], "resolution": 256,
              "shading": "flatShaded"}
    if isolate:
        params["isolate"] = ["|red"]
    res = p1.ok("capture_viewport", params)
    img = res["images"][0]
    out = opaque(img["png_b64"], label if save else None)
    out["blank_flag"] = img.get("blank")
    out["never_shown_note"] = any("main window" in w for w in res.get("warnings") or [])
    return out


LIB = r'''
import maya.cmds as cmds

def window_state():
    try:
        from maya.OpenMayaUI import MQtUtil
        from shiboken6 import wrapInstance
        from PySide6.QtWidgets import QWidget
        p = MQtUtil.mainWindow()
        if p is None:
            return {"mainWindow": None}
        w = wrapInstance(int(p), QWidget)
        # NB: never call w.winId() here - it FORCES native window creation as
        # a side effect, which is one of the things this probe is testing. It
        # gets its own labelled step (G) at the end.
        return {"visible": w.isVisible(), "minimized": w.isMinimized(),
                "hidden": w.isHidden(), "size": [w.width(), w.height()],
                # windowHandle() is None until a native surface exists, and
                # unlike winId() it does NOT create one.
                "native_surface": w.windowHandle() is not None,
                "class": w.metaObject().className()}
    except Exception as e:
        return {"error": repr(e)}

def panel_state():
    out = {}
    for p in cmds.getPanel(type="modelPanel") or []:
        so = cmds.modelEditor(p, q=True, viewObjects=True)
        out[p] = {"viewSelected": cmds.modelEditor(p, q=True, viewSelected=True),
                  "set": so,
                  "members": cmds.sets(so, q=True) if so else None,
                  "camera": cmds.modelPanel(p, q=True, camera=True),
                  "renderer": cmds.modelEditor(p, q=True, rendererName=True),
                  "visible_panel": p in (cmds.getPanel(visiblePanels=True) or [])}
    out["focus"] = cmds.getPanel(withFocus=True)
    return out

def env_state():
    import maya.mel as mel
    d = {"batch": cmds.about(batch=True), "version": cmds.about(version=True)}
    try:
        d["ogs_paused"] = cmds.ogs(query=True, pause=True)
    except Exception as e:
        d["ogs_paused"] = repr(e)
    for attr in ("renderMode", "multiSampleEnable", "lineAAEnable"):
        try:
            d[attr] = cmds.getAttr("hardwareRenderingGlobals." + attr)
        except Exception as e:
            d[attr] = repr(e)
    try:
        d["displayAppearance"] = mel.eval('getAttr "defaultRenderGlobals.currentRenderer"')
    except Exception as e:
        d["displayAppearance"] = repr(e)
    return d
'''


def main():
    print("### probe 825, tag=%s, port=%s" % (TAG, os.environ.get("MAYA_MCP_PORT")))
    p1.ok("new_scene", {"confirm": True})
    p1.py(p1.LIB + "\nr = red_blue_scene()")
    p1.py(LIB + "\nr = 1")

    show("A_as_launched", p1.py(
        "r = {'window': window_state(), 'panels': panel_state(), 'env': env_state()}"))

    show("B1_non_isolate", cap("B1_non_isolate", isolate=False))
    show("B2_isolate_first", cap("B2_isolate_first"))
    show("B3_isolate_again", cap("B3_isolate_again"))
    show("B4_window_after", p1.py("r = {'window': window_state(), 'panels': panel_state()}"))

    show("C1_ogs_reset", p1.py("cmds.ogs(reset=True)\nr = window_state()"))
    show("C2_isolate_after_ogs_reset", cap("C2_isolate_after_ogs_reset"))

    show("D1_refresh_force", p1.py("cmds.refresh(force=True)\nr = 1"))
    show("D2_isolate_after_refresh", cap("D2_isolate_after_refresh"))

    show("E1_showNormal_same_command", p1.py('''
        from maya.OpenMayaUI import MQtUtil
        from shiboken6 import wrapInstance
        from PySide6.QtWidgets import QWidget
        w = wrapInstance(int(MQtUtil.mainWindow()), QWidget)
        before = window_state()
        w.showNormal()
        r = {"before": before, "after_showNormal": window_state()}
    '''))
    show("E2_next_command", p1.py("r = window_state()"))
    show("E3_isolate_after_showNormal", cap("E3_isolate_after_showNormal"))

    show("F1_non_isolate_control", cap("F1_non_isolate_control", isolate=False))

    # G: force a NATIVE surface without putting the window on anyone's screen.
    # If this is what isolate needs, it is a better fix than show(): #765's
    # ensure_viewport_realized has to warn that it made a window appear,
    # because a capture's contract is that it has no visible side effect.
    show("G1_winId_forces_native", p1.py('''
        from maya.OpenMayaUI import MQtUtil
        from shiboken6 import wrapInstance
        from PySide6.QtWidgets import QWidget
        from PySide6.QtWidgets import QApplication
        w = wrapInstance(int(MQtUtil.mainWindow()), QWidget)
        before = window_state()
        wid = int(w.winId())
        QApplication.processEvents()
        r = {"before": before, "winId": wid, "after": window_state()}
    '''))
    show("G2_isolate_after_winId", cap("G2_isolate_after_winId"))
    show("G3_window_final", p1.py("r = {'window': window_state(), 'panels': panel_state()}"))
    print("\nWrote %s" % os.path.join(OUT, "findings.json"))


if __name__ == "__main__":
    main()
