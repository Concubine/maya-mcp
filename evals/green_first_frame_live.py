"""#830 live gate: a capture never hands back the wrong material silently.

The defect, reported by an agent modelling a prop and reproduced here: the
FIRST frame of a capture call came back flat unassigned-green - real geometry,
fully opaque, plain success, wrong material - while the later frames of the
SAME call were correct. Measured placeholder: exactly RGB (0, 208, 57),
covering 76-83% of the frame where a correctly shaded one spreads across its
lighting ramp.

`capture.py` already knew this failure and flushed a draw for it - but only
inside `if isolate:`, where it was first found. #830 measured the same thing
with no isolate at all, on a 28-mesh scene freshly assigned: 3 reproductions
out of 3 attempts. Two more measurements decided the fix:

  - the same `cmds.refresh(force=True)` issued from an EARLIER command does
    not help (3/3 still green). It has to happen after the capture has
    configured the panel and immediately before the grab.
  - it costs 2-4 ms, measured on a 160k-face scene. There was never a
    trade-off to protect.

So the flush is now unconditional, and because a mitigation is not a proof,
a frame that is still mostly that green is NAMED (#765's rule, one level up
from a blank frame).

Claims, all against a live Maya:

  1  the fixture that reproduced it 3/3 now draws its material, 3/3
  2  a mesh with NO shading group at all - permanently unassigned - is
     reported, and the note names #830 and offers the innocent reading
  3  a correctly shaded scene draws no such note (no false positive)
  4  a LIT green material does not trip it: the threshold discriminates on
     flatness, not on hue
  5  capture_turntable, the other caller, carries the note too

Usage:

    set MAYA_MCP_PORT=9878
    set MAYA_MCP_EXPECT_PID=<the pid you launched>
    python evals/green_first_frame_live.py

MUTATES THE ANSWERING MAYA'S SCENE. Refuses 9877. Exit: 0 pass, 1 fail.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import textwrap
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_call import call, structured_result  # noqa: E402
from maya_plugin.handlers import pngprobe  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
if PORT == 9877:
    raise SystemExit("refusing 9877 - that is the user's Maya")

PLACEHOLDER = [0, 208, 57]
CHECKS: list = []


def check(label: str, passed: bool, detail: object = "") -> bool:
    CHECKS.append((label, bool(passed), detail))
    print("  %s %s%s" % ("PASS" if passed else "FAIL", label,
                         ("  <- " + str(detail)) if detail else ""))
    return bool(passed)


def preflight() -> dict:
    if not (os.environ.get("MAYA_MCP_EXPECT_PID") or "").strip():
        raise SystemExit("MAYA_MCP_EXPECT_PID is not set - this gate discards "
                         "the answering Maya's scene (#648).")
    frame = call("ping", {}, port=PORT)
    ping = frame.get("result") or {}
    if frame.get("status") != "ok" or not ping:
        raise SystemExit("no Maya answered: %r" % (frame.get("error"),))
    if (ping.get("plugin") or {}).get("restart_required"):
        raise SystemExit("the answering Maya holds stale modules - restart it")
    return ping


def ok(command: str, params: dict, timeout_s: float = 300.0) -> dict:
    frame = call(command, params, timeout_s=timeout_s, port=PORT)
    if frame.get("status") != "ok":
        raise SystemExit("%s failed: %s"
                         % (command, json.dumps(frame.get("error"), indent=1)))
    return frame.get("result") or {}


def py(code: str, timeout_s: float = 300.0):
    body = textwrap.dedent(code).strip() + "\nr"
    res = ok("execute_python", {"code": body}, timeout_s=timeout_s)
    if res.get("traceback"):
        raise SystemExit("execute_python raised:\n" + res["traceback"])
    return structured_result(res, "r")


def measure(png_b64: str) -> dict:
    """The frame's dominant colour, measured HERE, not asked of the handler."""
    fd, path = tempfile.mkstemp(suffix=".png", prefix="gate830_")
    os.close(fd)
    try:
        with open(path, "wb") as fh:
            fh.write(base64.b64decode(png_b64))
        return pngprobe.dominant_colour(path)
    finally:
        os.unlink(path)


LIB = r'''
import maya.cmds as cmds

DEFAULTS = ("persp", "top", "front", "side")


def clean():
    junk = [n for n in (cmds.ls(assemblies=True) or []) if n not in DEFAULTS]
    if junk:
        cmds.delete(junk)
    return True


def shader(name, rgb):
    sh = cmds.shadingNode("standardSurface", asShader=True, name=name)
    cmds.setAttr(sh + ".baseColor", rgb[0], rgb[1], rgb[2], type="double3")
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                   name=name + "SG")
    cmds.connectAttr(sh + ".outColor", sg + ".surfaceShader", force=True)
    return sg


def meshes():
    return [m for m in cmds.ls(type="mesh", long=True)
            if not cmds.getAttr(m + ".intermediateObject")]


def prop(n=28, rgb=(0.9, 0.05, 0.05)):
    """The fixture that reproduced #830 3 times out of 3.

    28 meshes matters: the same recipe with 3 meshes never reproduced it.
    """
    clean()
    sg = shader("gate830_mat", rgb)
    for i in range(n):
        cube = cmds.polyCube(name="gate830_%02d" % i)[0]
        cmds.setAttr(cube + ".translateX", (i % 7) * 1.6 - 4.8)
        cmds.setAttr(cube + ".translateY", (i // 7) * 1.6)
        cmds.setAttr(cube + ".scaleZ", 0.6)
    cmds.sets(meshes(), edit=True, forceElement=sg)
    return {"meshes": len(meshes()), "sg": sg}


def strip_shading():
    """Leave every mesh in NO shading group - permanently unassigned."""
    stripped = 0
    for m in meshes():
        for sg in set(cmds.listConnections(m, type="shadingEngine") or []):
            cmds.sets(m, edit=True, remove=sg)
            stripped += 1
    return stripped
'''


def build(rgb=(0.9, 0.05, 0.05), lights=True) -> dict:
    """A scene VP2 has never drawn - the state the defect needs."""
    ok("new_scene", {"confirm": True})
    py(LIB + "\nr = 1")
    built = py("r = prop(rgb=%r)" % (rgb,))
    if lights:
        ok("setup_lighting", {"preset": "three_point"})
    return built


def shoot(angles=("front", "three_quarter"), **kw) -> tuple:
    args = {"angles": list(angles), "resolution": 256, "lighting": "scene"}
    args.update(kw)
    started = time.time()
    res = ok("capture_viewport", args)
    elapsed = time.time() - started
    frames = [measure(img["png_b64"]) for img in res["images"]]
    notes = [w for w in (res.get("warnings") or [])
             if "unassigned-shader green" in w]
    return frames, notes, elapsed


def main() -> int:
    ping = preflight()
    print("answering Maya: pid %s, plugin %s"
          % ((ping.get("process") or {}).get("pid"),
             ((ping.get("plugin") or {}).get("loaded_digest") or "")[:12]))

    print("\nclaim 1: the fixture that reproduced it 3/3 now draws its material")
    for run in range(3):
        build()
        frames, notes, elapsed = shoot()
        first = frames[0]
        print("    run %d: frame1 top=%s share=%.2f  call=%.2fs"
              % (run, first["top_rgb"], first["top_share"] or 0, elapsed))
        check("run %d: the first frame is not the placeholder" % run,
              first["top_rgb"] != PLACEHOLDER, first)
        check("run %d: and nothing warned, because nothing was wrong" % run,
              notes == [], notes)

    print("\nclaim 2: a mesh with NO shading group is reported, not shipped "
          "silently")
    build()
    stripped = py("r = strip_shading()")
    frames, notes, _ = shoot(angles=["front"])
    check("the fixture really is unassigned now", stripped > 0, stripped)
    check("the frame IS the placeholder green, measured here",
          frames[0]["top_rgb"] == PLACEHOLDER, frames[0])
    check("exactly one note, and it names the ticket",
          len(notes) == 1 and "#830" in notes[0], notes)
    if notes:
        check("it says what else it could be, rather than accusing",
              "material really is that flat green" in notes[0], notes[0])
        check("and it reports the share it measured",
              "%" in notes[0], notes[0])

    print("\nclaim 3: a correctly shaded scene draws no such note")
    build()
    frames, notes, _ = shoot()
    check("no false positive on a red prop", notes == [], notes)

    print("\nclaim 4: a LIT GREEN material does not trip it - the test is "
          "flatness, not hue")
    build(rgb=(0.0, 0.82, 0.22))
    frames, notes, _ = shoot()
    print("    green prop: frame1 top=%s share=%.2f"
          % (frames[0]["top_rgb"], frames[0]["top_share"] or 0))
    check("a green model under scene lighting is not accused", notes == [],
          notes)

    print("\nclaim 5: the turntable carries the note too")
    build()
    py("r = strip_shading()")
    turn = ok("capture_turntable", {"n_frames": 2, "resolution": 192})
    turn_notes = [w for w in (turn.get("warnings") or [])
                  if "unassigned-shader green" in w]
    check("both turntable frames are named", len(turn_notes) == 2, turn_notes)

    failed = [c for c in CHECKS if not c[1]]
    print("\n%d/%d checks passed" % (len(CHECKS) - len(failed), len(CHECKS)))
    for label, _, detail in failed:
        print("  FAILED: %s  <- %s" % (label, detail))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
