"""Throwaway probe for #830: does the FIRST frame after a scene edit really
come back with materials unbound (flat green), and what fixes it?

Reported by a fresh agent modelling a prop, not by a gate: twice, the first
frame of the first capture after a scene-modifying call rendered every mesh
carrying its material as flat pure green, while later frames in the SAME call
were correct. No warning of any kind.

capture.py already knows this failure - the comment on its isolate branch
says "a shape never drawn under this isolate renders flat unassigned-green for
one frame (verified live on Maya 2027: first capture green, second correct)"
- and flushes `cmds.refresh(force=True)` for it. But only inside `if isolate:`.

Asked here, in order, and NOTHING is asserted:

  A  does it reproduce at all, with a strongly coloured material?
  B  WHICH edit arms it - assign a material, create a mesh, group+transform,
     setup_lighting - and is it the first FRAME or the first CALL?
  C  what exactly is the green? (the placeholder's RGB, for a detector)
  D  does an explicit refresh(force=True) before the capture kill it?
  E  does the isolate path - the one that already flushes - stay clean?
  F  what does that flush COST? light scene vs ~160k faces. That cost is the
     only reason to keep the flush scoped, so it has to be measured before
     the flush is made unconditional.

Run:  MAYA_MCP_PORT=9878 MAYA_MCP_EXPECT_PID=<pid> python evals/green_first_frame_probe_830.py

MUTATES THE ANSWERING MAYA'S SCENE. Refuses 9877.
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import textwrap

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, _HERE)

from live_call import call, structured_result  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
if PORT == 9877:
    raise SystemExit("refusing 9877 - that is the user's Maya")
OUT = os.path.join(_HERE, "green_first_frame_probe_830")
os.makedirs(OUT, exist_ok=True)
FINDINGS: dict = {}


def ok(command: str, params: dict, timeout_s: float = 300.0) -> dict:
    frame = call(command, params, timeout_s=timeout_s, port=PORT)
    if frame.get("status") != "ok":
        raise SystemExit("%s failed: %s"
                         % (command, json.dumps(frame.get("error"), indent=1)))
    return frame.get("result") or {}


def py(code: str, timeout_s: float = 600.0):
    body = textwrap.dedent(code).strip() + "\nr"
    res = ok("execute_python", {"code": body}, timeout_s=timeout_s)
    if res.get("traceback"):
        raise SystemExit("execute_python raised:\n" + res["traceback"])
    return structured_result(res, "r")


def show(label: str, value) -> None:
    FINDINGS[label] = value
    with open(os.path.join(OUT, "findings.json"), "w", encoding="utf-8") as fh:
        json.dump(FINDINGS, fh, indent=1, default=str)
    print("\n--- %s ---" % label)
    print(json.dumps(value, indent=1, sort_keys=True, default=str))


def colours(png_b64: str, name: str = None) -> dict:
    """Red vs green dominance, and the most common opaque colour."""
    from PIL import Image
    from collections import Counter
    img = Image.open(io.BytesIO(base64.b64decode(png_b64))).convert("RGBA")
    if name:
        img.save(os.path.join(OUT, name + ".png"))
    px = [p for p in img.getdata() if p[3] > 0]
    red = sum(1 for p in px if p[0] > p[1] + 40 and p[0] > p[2] + 40)
    green = sum(1 for p in px if p[1] > p[0] + 40 and p[1] > p[2] + 40)
    common = Counter(px).most_common(3)
    return {"opaque": len(px), "red": red, "green": green,
            "verdict": "GREEN" if green > red else ("red" if red else "neither"),
            "top_colours": [(c, n) for c, n in common]}


def frames(label: str, **params) -> list:
    """One capture call; every frame classified."""
    args = {"angles": ["front", "three_quarter", "side", "back"],
            "resolution": 256, "lighting": "scene"}
    args.update(params)
    res = ok("capture_viewport", args)
    out = []
    for img in res["images"]:
        c = colours(img["png_b64"], "%s_%s" % (label, img["angle"]))
        c["angle"] = img["angle"]
        out.append(c)
    print("  %-28s %s" % (label, " ".join("%s:%s" % (f["angle"][:5], f["verdict"])
                                          for f in out)))
    return out


LIB = r'''
import time
import maya.cmds as cmds

DEFAULTS = ("persp", "top", "front", "side")


def clean():
    junk = [n for n in (cmds.ls(assemblies=True) or []) if n not in DEFAULTS]
    if junk:
        cmds.delete(junk)
    return True


def red_scene(n=3):
    """Three cubes wearing an unmistakable red - so a wrong colour is loud."""
    clean()
    shader = cmds.shadingNode("standardSurface", asShader=True, name="probe_red")
    cmds.setAttr(shader + ".baseColor", 0.9, 0.05, 0.05, type="double3")
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                   name="probe_redSG")
    cmds.connectAttr(shader + ".outColor", sg + ".surfaceShader", force=True)
    made = []
    for i in range(n):
        cube = cmds.polyCube(name="probe_cube%d" % i)[0]
        cmds.setAttr(cube + ".translateX", (i - 1) * 2.5)
        cmds.sets(cube, edit=True, forceElement=sg)
        made.append(cube)
    return made


def reassign():
    """Occurrence 1's edit: put every mesh into the shading group again."""
    meshes = [m for m in cmds.ls(type="mesh", long=True)
              if not cmds.getAttr(m + ".intermediateObject")]
    cmds.sets(meshes, edit=True, forceElement="probe_redSG")
    return len(meshes)


def group_and_move():
    """Occurrence 2's edit: group the cubes and move the group."""
    cubes = [c for c in (cmds.ls(assemblies=True) or []) if c.startswith("probe_cube")]
    grp = cmds.group(cubes, name="probe_grp")
    cmds.setAttr(grp + ".translateY", 0.5)
    return grp


def add_mesh():
    cube = cmds.polyCube(name="probe_new")[0]
    cmds.setAttr(cube + ".translateZ", 2.0)
    cmds.sets(cube, edit=True, forceElement="probe_redSG")
    return cube


def flush():
    t = time.time()
    cmds.refresh(force=True)
    return round(time.time() - t, 3)


def heavy(subdiv=400):
    """~160k faces, built from a plane - polySphere 500x500 HANGS Maya."""
    p = cmds.polyPlane(name="probe_heavy", subdivisionsX=subdiv,
                       subdivisionsY=subdiv, width=10, height=10)[0]
    cmds.sets(p, edit=True, forceElement="probe_redSG")
    return {"mesh": p, "faces": cmds.polyEvaluate(p, face=True)}
'''


def main():
    print("### probe 830 on port %s" % PORT)
    ping = ok("ping", {})
    print("answering Maya: pid %s" % (ping.get("process") or {}).get("pid"))
    ok("new_scene", {"confirm": True})
    py(LIB + "\nr = 1")

    print("\nA. does it reproduce: red material, then capture straight away")
    py("r = red_scene()")
    ok("setup_lighting", {"preset": "three_point"})
    first = frames("A1_first_call_after_edits")
    second = frames("A2_second_call_no_edit")
    show("A does it reproduce", {
        "first_call_after_the_edits": first,
        "second_call_no_edit_between": second,
        "reproduced": any(f["verdict"] == "GREEN" for f in first),
        "only_the_first_frame": (first[0]["verdict"] == "GREEN"
                                 and all(f["verdict"] != "GREEN" for f in first[1:]))
        if first else None,
    })

    print("\nB. which edit arms it")
    per_edit = {}
    for label, code in (("reassign_material", "r = reassign()"),
                        ("group_and_move", "r = group_and_move()"),
                        ("add_a_new_mesh", "r = add_mesh()"),
                        ("setup_lighting", None)):
        if code:
            py(code)
        else:
            ok("setup_lighting", {"preset": "three_point"})
        per_edit[label] = frames("B_" + label)
    show("B which edit arms it", {
        k: {"verdicts": [f["verdict"] for f in v],
            "green_first_frame": v[0]["verdict"] == "GREEN"}
        for k, v in per_edit.items()})

    print("\nC. what IS the green (for a detector)")
    green_frames = [f for v in [first] + list(per_edit.values()) for f in v
                    if f["verdict"] == "GREEN"]
    show("C the placeholder colour", {
        "green_frames_seen": len(green_frames),
        "top_colours_of_each": [f["top_colours"] for f in green_frames[:4]],
    })

    print("\nD. does an explicit flush before the capture kill it")
    py("r = add_mesh()")
    cost = py("r = flush()")
    after_flush = frames("D_after_explicit_flush")
    show("D flush before the capture", {
        "flush_seconds_light_scene": cost,
        "frames": [f["verdict"] for f in after_flush],
        "still_green": any(f["verdict"] == "GREEN" for f in after_flush),
    })

    print("\nE. the isolate path, which already flushes")
    py("r = add_mesh()")
    iso = frames("E_isolate", angles=["front"], isolate=["probe_cube0"])
    show("E isolate path", {"frames": [f["verdict"] for f in iso]})

    print("\nF. what the flush costs on a heavy scene")
    heavy = py("r = heavy()", timeout_s=900.0)
    costs = [py("r = flush()", timeout_s=900.0) for _ in range(3)]
    show("F flush cost", {"scene": heavy, "flush_seconds": costs})

    print("\nfindings -> %s" % os.path.join(OUT, "findings.json"))


if __name__ == "__main__":
    main()
