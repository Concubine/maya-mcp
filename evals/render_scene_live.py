"""The #584 acceptance gate: render_scene against an AGENT-LAUNCHED Maya.

Two claims, both measured in pixels rather than asserted:

  1. a lit scene renders NON-BLANK from a Maya with no mapped window - the
     configuration in which every playblast comes back fully transparent;
  2. a transmissive gem renders MEASURABLY DIFFERENT from an otherwise
     identical opaque one, which VP2 cannot show at all.

Run:  set MAYA_MCP_PORT=9878 && .venv/Scripts/python.exe evals/render_scene_live.py
Exit: 0 pass, 1 fail, 2 could not run (no Maya connection).
Artifacts: evals/m2_2_run/*.png
"""

from __future__ import annotations

import base64
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from live_call import call  # noqa: E402
from maya_mcp import images  # noqa: E402

OUT_DIR = os.path.join(_HERE, "m2_2_run")

SCENE = r"""
import json
import maya.cmds as cmds

cmds.file(new=True, force=True)
cmds.polySphere(name="litBall", radius=3)
# Arnold at a viewport-plausible intensity renders almost black - the probe in
# #584 said as much. A rig that looks sane in VP2 is NOT a rig that renders,
# so the gate lights for the renderer it is actually using.
key = cmds.directionalLight(name="gateKey", intensity=12.0)
cmds.xform(cmds.listRelatives(key, parent=True)[0], rotation=[-35, 25, 0])
fill = cmds.directionalLight(name="gateFill", intensity=5.0)
cmds.xform(cmds.listRelatives(fill, parent=True)[0], rotation=[-15, -110, 0])

# A backdrop, so refraction has something to bend. Without one a transmissive
# gem and an opaque gem can both render as "dark thing on black".
wall = cmds.polyPlane(name="backdrop", width=60, height=60, subdivisionsX=1,
                      subdivisionsY=1)[0]
cmds.setAttr(wall + ".rotateX", 90)
cmds.setAttr(wall + ".translate", 0, 6, -14, type="double3")
wall_mat = cmds.shadingNode("lambert", asShader=True, name="backdrop_mat")
cmds.setAttr(wall_mat + ".color", 0.75, 0.75, 0.8, type="double3")
wall_sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                    name="backdrop_SG")
cmds.connectAttr(wall_mat + ".outColor", wall_sg + ".surfaceShader", force=True)
cmds.sets(wall, edit=True, forceElement=wall_sg)

# Two identical gems, one transmissive - the pair VP2 draws as near-identical.
for name, x, transmission in (("opaqueGem", -4.0, 0.0), ("glassGem", 4.0, 1.0)):
    gem = cmds.polyPlatonicSolid(name=name, solidType=2)[0]
    cmds.setAttr(gem + ".scale", 3.0, 3.0, 3.0, type="double3")
    cmds.setAttr(gem + ".translate", x, 6.0, 0.0, type="double3")
    mat = cmds.shadingNode("standardSurface", asShader=True, name=name + "_mat")
    cmds.setAttr(mat + ".baseColor", 0.7, 0.05, 0.1, type="double3")
    cmds.setAttr(mat + ".transmission", transmission)
    cmds.setAttr(mat + ".transmissionColor", 0.8, 0.05, 0.1, type="double3")
    cmds.setAttr(mat + ".specularIOR", 2.42)
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                   name=name + "_SG")
    cmds.connectAttr(mat + ".outColor", sg + ".surfaceShader", force=True)
    cmds.sets(gem, edit=True, forceElement=sg)

print(json.dumps({
    "window_visible": cmds.window("MayaWindow", query=True, visible=True),
    "visible_panels": cmds.getPanel(visiblePanels=True) or [],
    "renderers": cmds.renderer(query=True, namesOfAvailableRenderers=True),
}))
"""


def fail(msg):
    print("FAIL: " + msg)
    sys.exit(1)


def render(label, params):
    resp = call("render_scene", params, 600.0)
    if resp.get("status") != "ok":
        fail("render_scene(%s) errored: %s" % (label, json.dumps(resp)[:600]))
    shot = resp["result"]["images"][0]
    png = base64.b64decode(shot["png_b64"])
    with open(os.path.join(OUT_DIR, "%s.png" % label), "wb") as fh:
        fh.write(png)
    stats = images.pixel_stats(png)
    print("%-8s %s" % (label, json.dumps(stats)))
    return stats


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    setup = call("execute_python", {"code": SCENE}, 180.0)
    if setup.get("status") != "ok":
        print("could not reach Maya: " + json.dumps(setup)[:400])
        return 2
    print("environment: " + setup["result"]["stdout"].strip())

    base = {"angles": ["front"], "renderer": "arnold", "resolution": 256,
            "samples": 3}
    scene = render("scene", dict(base))
    opaque = render("opaque", dict(base, isolate=["|opaqueGem"]))
    glass = render("glass", dict(base, isolate=["|glassGem"]))

    if scene["blank"]:
        fail("a lit scene rendered blank from an agent-launched Maya - claim 1 "
             "is the whole ticket")
    if opaque["blank"] or glass["blank"]:
        fail("a gem rendered blank; transmission cannot be compared")
    # Refraction changes what reaches the camera, so the transmissive gem's
    # colour count and coverage both move. Identical numbers would mean the
    # renderer ignored transmission - the VP2 behaviour this ticket escapes.
    if (opaque["distinct_colors"] == glass["distinct_colors"]
            and opaque["opaque_px"] == glass["opaque_px"]):
        fail("the transmissive gem is pixel-identical to the opaque one - "
             "transmission did not render")

    print("PASS - headless render works and transmission is visible")
    print("artifacts: " + OUT_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
