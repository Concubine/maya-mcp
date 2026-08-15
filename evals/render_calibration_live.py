"""Live gate: render_scene must return a DISPLAYABLE image (redmine #615).

Arnold hands back raw linear pixels. Written straight into an 8-bit PNG, a
surface of linear albedo 0.5 lit to N.L = 1 arrives as 127 where a displayable
image wants 188 - every frame the tool returned was about 2.2 gamma too dark,
and the whole headless suite was green throughout. So the measurement lives
here, where it is pixels rather than a mock.

The probe is a plane of standardSurface baseColor 0.5 (base 1, specular 0) lit
by a single directional light at intensity pi - pi because Arnold's distant
light is not pi-normalised, so intensity 1.0 would deliver albedo/pi. Every
other light in the scene is parked at 0 for the duration and put back after.
The plane sits far from the origin so it cannot collide with the user's work.

Run:  MAYA_MCP_PORT=9877 uv run python evals/render_calibration_live.py
Exit: 0 pass, 1 fail, 2 could not run (no Maya connection).
"""

from __future__ import annotations

import base64
import io
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from live_call import DEFAULT_PORT, call, structured_result  # noqa: E402

# Linear 0.5 through the sRGB transfer function: 1.055 * 0.5^(1/2.4) - 0.055.
EXPECTED = 188
TOLERANCE = 3

SETUP = """
import maya.cmds as cmds, math
saved = {}
for shape in (cmds.ls(type="light", long=True) or []):
    if "calibLight" in shape:
        continue
    try:
        saved[shape] = cmds.getAttr(shape + ".intensity")
        cmds.setAttr(shape + ".intensity", 0.0)
    except Exception:
        pass
probe = cmds.directionalLight(name="calibLight", intensity=math.pi)
cmds.xform(cmds.listRelatives(probe, parent=True, fullPath=True)[0],
           rotation=(-90, 0, 0), worldSpace=True)
plane = cmds.polyPlane(name="calibPlane", width=20, height=20, sx=1, sy=1)[0]
cmds.xform(plane, translation=(120, 20, 0), worldSpace=True)
mat = cmds.shadingNode("standardSurface", asShader=True, name="calibMat")
cmds.setAttr(mat + ".baseColor", 0.5, 0.5, 0.5, type="double3")
cmds.setAttr(mat + ".base", 1.0)
cmds.setAttr(mat + ".specular", 0.0)
sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=mat + "SG")
cmds.connectAttr(mat + ".outColor", sg + ".surfaceShader", force=True)
cmds.sets(plane, edit=True, forceElement=sg)
{"saved": saved}
"""

TEARDOWN = """
import maya.cmds as cmds
for node in ("calibPlane", "calibLight", "calibMat", "calibMatSG"):
    if cmds.objExists(node):
        cmds.delete(node)
restored = 0
for shape, value in %r.items():
    if cmds.objExists(shape):
        try:
            cmds.setAttr(shape + ".intensity", value)
            restored += 1
        except Exception:
            pass
{"restored": restored}
"""


def send(command, params, timeout_s=300.0):
    response = call(command, params, timeout_s=timeout_s)
    if response.get("status") != "ok":
        raise RuntimeError("%s failed: %s" % (command, response.get("error")))
    return response["result"]


def lit_value(png_bytes) -> int:
    """The red channel of the commonest lit colour in the frame.

    Modal rather than mean: the plane does not fill the frame, and averaging it
    with the black background would report a number that is not the surface's.
    """
    from PIL import Image

    image = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    colors = image.getcolors(maxcolors=image.width * image.height) or []
    lit = sorted((c for c in colors if sum(c[1]) > 12), reverse=True)
    return lit[0][1][0] if lit else -1


def main() -> int:
    try:
        send("execute_python", {"code": "pass"}, timeout_s=10.0)
    except Exception as exc:  # noqa: BLE001 - a gate reports, it does not raise
        print("SKIP: no live Maya plugin on port %d (%s)" % (DEFAULT_PORT, exc))
        return 2

    saved = structured_result(send("execute_python", {"code": SETUP}))["saved"]
    try:
        result = send("render_scene", {
            "isolate": ["calibPlane"],
            "angles": ["top"],
            "relight": False,        # our probe light IS the calibration
            "fallback_light": False,
            "resolution": 256,
            "samples": 3,
        })
        png = base64.b64decode(result["images"][0]["png_b64"])
        measured = lit_value(png)
    finally:
        send("execute_python", {"code": TEARDOWN % saved})

    print("calibration: measured %d  expected %d +/- %d  (%d lights parked and "
          "restored)" % (measured, EXPECTED, TOLERANCE, len(saved)))
    if abs(measured - EXPECTED) > TOLERANCE:
        print("FAIL: a linear-0.5 surface at N.L = 1 must leave as %d. %d is "
              "the RAW LINEAR value - render_scene is returning undisplayable "
              "pixels again (redmine #615)." % (EXPECTED, measured))
        return 1
    print("PASS: render_scene returns a displayable image")
    return 0


if __name__ == "__main__":
    sys.exit(main())
