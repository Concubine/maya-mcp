"""Live-Maya regression check: isolate captures must keep materials (redmine #575).

On Maya 2027, the M0-era isolate implementation (enableIsolateSelect + locked
mainListConnection) rendered any shape with per-face/groupId shading bindings
as flat unassigned-green in VP2 playblasts — isolate-only; the same capture
without isolate was fine. The fix routes isolation through the isolateSelect
state/addDagObject API. This script guards against regressing that.

It drives the live plugin over TCP (Maya must be open, plugin listening on
127.0.0.1:9877, a viewport visible): builds a temporary cube with per-face
red/yellow lambert assignments — the minimal trigger, verified live — captures
it with isolate, and asserts the pixels show the materials rather than the
VP2 unassigned-green. The cube and its shaders are deleted afterwards.

Run:  .venv/Scripts/python.exe evals/isolate_regression.py
Exit: 0 pass, 1 fail, 2 could not run (no Maya connection).

Part of the loop-test protocol (docs/m0-loop-test.md): run this after any
change to maya_plugin/handlers/capture.py.
"""

from __future__ import annotations

import base64
import io
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from maya_plugin import protocol  # noqa: E402

HOST, PORT = "127.0.0.1", 9877
CUBE = "mcpIsoCheck_cube"

SETUP = """
import maya.cmds as cmds
if cmds.objExists("|{cube}"):
    cmds.delete("|{cube}")
cube = cmds.polyCube(name="{cube}", width=3, height=3, depth=3)[0]
cmds.setAttr(cube + ".translate", 0, 500, 0, type="double3")
for name, color, faces in (("{cube}_red", (1, 0.2, 0.2), "f[0:2]"),
                           ("{cube}_yel", (1, 1, 0.2), "f[3:5]")):
    mat = cmds.shadingNode("lambert", asShader=True, name=name)
    cmds.setAttr(mat + ".color", *color, type="double3")
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=name + "SG")
    cmds.connectAttr(mat + ".outColor", sg + ".surfaceShader", force=True)
    cmds.sets("%s.%s" % (cube, faces), edit=True, forceElement=name + "SG")
cmds.select(clear=True)
""".format(cube=CUBE)

TEARDOWN = """
import maya.cmds as cmds
for node in ("|{cube}", "{cube}_red", "{cube}_yel", "{cube}_redSG", "{cube}_yelSG"):
    if cmds.objExists(node):
        cmds.delete(node)
""".format(cube=CUBE)


def call(cmd, params, timeout_s=60.0):
    sock = socket.create_connection((HOST, PORT), timeout=timeout_s + 30)
    try:
        sock.sendall(protocol.encode_frame(protocol.make_request(cmd, params, timeout_s)))
        resp = protocol.read_frame(sock.recv)
    finally:
        sock.close()
    if resp.get("status") != "ok":
        raise RuntimeError("plugin error: %s" % resp.get("error"))
    return resp["result"]


def color_fractions(png_bytes):
    """(green_fraction, red_fraction) over opaque pixels, or (None, None) if
    the capture had no opaque pixels at all (a distinct failure from #575 -
    see the caller).

    VP2's unassigned-material green measured live: (0, 208, 57) — saturated
    green with no red. The cube's lamberts render red- and yellow-dominant.
    """
    from PIL import Image

    image = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    opaque = [(r, g, b) for r, g, b, a in image.getdata() if a > 128]
    if not opaque:
        # A blank/empty capture is a DIFFERENT failure than the #575 shading
        # bug (which produces a fully-opaque, saturated-green image) - do not
        # report it as green-dominant, or a capture pipeline break masquerades
        # as "the isolate bug is back" and burns a debugging session on the
        # wrong problem (as it already did once).
        return None, None
    green = sum(1 for r, g, b in opaque if g > 120 and g > 1.5 * r and g > 1.5 * b)
    red = sum(1 for r, g, b in opaque if r > 120 and r > 1.5 * g and r > 1.5 * b)
    return green / len(opaque), red / len(opaque)


def main() -> int:
    try:
        call("execute_python", {"code": "pass"}, timeout_s=10.0)
    except Exception as exc:
        print("SKIP: no live Maya plugin on %s:%d (%s)" % (HOST, PORT, exc))
        return 2

    call("execute_python", {"code": SETUP})
    try:
        result = call("capture_viewport", {
            "angles": ["three_quarter"],
            "isolate": ["|%s" % CUBE],
            "resolution": 512,
        })
        png = base64.b64decode(result["images"][0]["png_b64"])
        green, red = color_fractions(png)
    finally:
        call("execute_python", {"code": TEARDOWN})

    if green is None:
        print("FAIL: capture was empty - this is not the #575 bug")
        return 1

    print("isolate capture: green-dominant %.2f, red-dominant %.2f of opaque pixels"
          % (green, red))
    if green > 0.5:
        print("FAIL: isolate capture is unassigned-green — the VP2 isolate "
              "shading bug is back (redmine #575)")
        return 1
    if red < 0.2:
        print("FAIL: isolate capture shows no material colors (expected the "
              "per-face red lambert to dominate at least 20%)")
        return 1
    print("PASS: isolate capture keeps per-face materials")
    return 0


if __name__ == "__main__":
    sys.exit(main())
