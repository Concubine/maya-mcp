"""Live gate for redmine #638: a boolean rebuilds the mesh, and everything that
is not vertices has to survive the rebuild.

polyCBoolOp builds a brand-new root object. Three things that belonged to input
A were dropped on the way, every one of them silently, on a call that reported
`watertight: true` and `warnings: []`:

  1. the PIVOT - a shoulder rigged at its ball joint came back pivoted at the
     new mesh's bbox centre, which is what #603 exists to prevent;
  2. the PARENT - cutting a slot in a chunk that was a child of the head
     produced a root object, a limb silently falling out of a 29-chunk rig;
  3. the UVs of the newly cut faces - polyCBoolOp keeps EACH OPERAND's own UV
     layout, so an atlas-packed chunk cut with a default-UV cutter comes back
     with the cut face sampling the whole atlas. Nothing looks wrong until the
     material goes on, which is why this is the one that shipped.

A headless test can prove the handler asks Maya for the right things. Only this
can prove Maya did them: the reparent has to happen BEFORE the history delete
(which reaps a parent group whose only child was A), and a parent that carries
a scale hands the result a compensating inverse - the exact node state the
export gate refuses (#629), so it has to be baked rather than carried.

DESTRUCTIVE: calls new_scene. Defaults to port 9878 (the disposable
agent-launched Maya) and refuses 9877 unless MAYA_MCP_ALLOW_USER_SESSION=1.

Run:  .venv/Scripts/python.exe evals/boolean_state_live.py
Exit: 0 pass, 1 fail, 2 no connection.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_call import DEFAULT_PORT, call, structured_result  # noqa: E402

PORT = DEFAULT_PORT
# Patch 0 of a 4x4 atlas with a 2% margin - where the golem run's chunks sat.
PATCH = (0.005, 0.755, 0.245, 0.995)
TOL = 1e-4

failures = []

STATE = """
import maya.cmds as cmds
n = '%s'
shape = cmds.listRelatives(n, shapes=True, fullPath=True, ni=True)[0]
flat = cmds.polyEditUV(shape + '.map[*]', q=True) or []
us = flat[0::2]; vs = flat[1::2]
{'pivot': [round(v, 6) for v in cmds.xform(n, q=True, ws=True, rotatePivot=True)],
 'parent': (cmds.listRelatives(n, parent=True, fullPath=True) or [None])[0],
 'scale': [round(v, 6) for v in cmds.getAttr(n + '.scale')[0]],
 'bbox': [round(v, 4) for v in cmds.exactWorldBoundingBox(n)],
 'uv': None if not flat else [round(min(us), 6), round(min(vs), 6),
                              round(max(us), 6), round(max(vs), 6)]}
"""


def send(command: str, params: dict, timeout_s: float = 180.0) -> dict:
    try:
        response = call(command, params, timeout_s=timeout_s, port=PORT)
    except (ConnectionRefusedError, OSError) as exc:
        print("could not reach a Maya plugin on %s: %s" % (PORT, exc))
        sys.exit(2)
    if response.get("status") != "ok":
        print("FAIL: %s: %s" % (command, json.dumps(response.get("error"))[:400]))
        sys.exit(1)
    return response.get("result") or {}


def py(code: str):
    return structured_result(send("execute_python", {"code": code}, 120.0))


def check(label: str, ok: bool, detail: str) -> None:
    print("%s %s: %s" % ("PASS" if ok else "FAIL", label, detail))
    if not ok:
        failures.append(label)


def state(name: str) -> dict:
    return py(STATE % name)


def inside(bounds, rect=PATCH) -> bool:
    if bounds is None:
        return False
    return (bounds[0] >= rect[0] - TOL and bounds[1] >= rect[1] - TOL
            and bounds[2] <= rect[2] + TOL and bounds[3] <= rect[3] + TOL)


PACK = """
import maya.cmds as cmds
n = '%s'
cmds.polyEditUV(n + '.map[*]', pu=0, pv=0, su=%f, sv=%f)
cmds.polyEditUV(n + '.map[*]', u=%f, v=%f)
'packed'
"""


def pack(name: str) -> None:
    py(PACK % (name, PATCH[2] - PATCH[0], PATCH[3] - PATCH[1], PATCH[0], PATCH[1]))


def main() -> None:
    if PORT == 9877 and os.environ.get("MAYA_MCP_ALLOW_USER_SESSION") != "1":
        print("refusing to run on 9877: this eval discards the open scene. "
              "Set MAYA_MCP_ALLOW_USER_SESSION=1 to override.")
        sys.exit(2)

    print("Maya on %d: pid %s\n" % (PORT, py("import os\nos.getpid()")))
    send("new_scene", {"confirm": True})

    # ---- 1. the golem case, whole: rigged pivot + parent + atlas patch ----
    py("import maya.cmds as cmds\n"
       "head = cmds.group(empty=True, name='golem_C_head')\n"
       "a = cmds.polyCube(w=2, h=2, d=2, name='brow')[0]\n"
       "cmds.xform(a, ws=True, translation=(0, 3, 0))\n"
       "a = cmds.parent(a, head)[0]\n"
       "cmds.xform(a, ws=True, pivots=(0, 2, 0))\n"
       "'built'")
    pack("|golem_C_head|brow")
    send("create_primitive", {"kind": "cube", "name": "visor",
                              "translate": [1, 4, 0], "scale": [1, 1, 1]})
    before = state("|golem_C_head|brow")

    result = send("boolean_op", {"a": "|golem_C_head|brow", "b": "|visor",
                                 "op": "difference", "new_name": "brow_slotted"})
    after = state(result["name"])

    check("the rigged pivot survives the cut",
          after["pivot"] == [0.0, 2.0, 0.0],
          "%s -> %s (the bbox centre would be %s)"
          % (before["pivot"], after["pivot"],
             [round((before["bbox"][i] + before["bbox"][i + 3]) / 2, 4) for i in range(3)]))
    check("and the call reports it",
          result.get("pivot") == after["pivot"], repr(result.get("pivot")))
    check("the chunk is still a child of the head",
          after["parent"] == "|golem_C_head" and result.get("parent") == "|golem_C_head",
          "parent=%s, reported=%s, name=%s"
          % (after["parent"], result.get("parent"), result["name"]))
    check("the cut faces stay inside the chunk's atlas patch",
          inside(after["uv"]),
          "a was %s, result is %s, patch is %s"
          % (before["uv"], after["uv"], list(PATCH)))
    check("and the call reports the UV bounds",
          result.get("uv_bounds") == after["uv"], repr(result.get("uv_bounds")))
    check("a clean cut still raises no warnings",
          result.get("warnings") == [], repr(result.get("warnings")))

    # ---- 2. the parent group whose ONLY child is the chunk ----
    py("import maya.cmds as cmds\n"
       "g = cmds.group(empty=True, name='soloGRP')\n"
       "a = cmds.polyCube(w=2, h=2, d=2, name='solo')[0]\n"
       "cmds.xform(a, ws=True, translation=(6, 1, 0))\n"
       "cmds.parent(a, g)\n'built'")
    send("create_primitive", {"kind": "cube", "name": "soloCut",
                              "translate": [7, 2, 0]})
    solo = send("boolean_op", {"a": "|soloGRP|solo", "b": "|soloCut",
                               "op": "difference", "new_name": "solo_cut"})
    alive = py("import maya.cmds as cmds\ncmds.objExists('soloGRP')")
    check("an only-child's parent group is not garbage-collected",
          bool(alive) and solo.get("parent") == "|soloGRP",
          "soloGRP alive=%s, result parent=%s" % (alive, solo.get("parent")))

    # ---- 3. a scaled parent must not leave a compensating scale ----
    py("import maya.cmds as cmds\n"
       "g = cmds.group(empty=True, name='scaledGRP')\n"
       "[cmds.setAttr(g + '.scale' + ax, 0.8) for ax in 'XYZ']\n"
       "a = cmds.polyCube(w=2, h=2, d=2, name='scaled')[0]\n"
       "cmds.xform(a, ws=True, translation=(-6, 1, 0))\n"
       "cmds.parent(a, g)\n'built'")
    scaled_before = state("|scaledGRP|scaled")
    send("create_primitive", {"kind": "cube", "name": "scaledCut",
                              "translate": [-5.4, 1.6, 0]})
    scaled = send("boolean_op", {"a": "|scaledGRP|scaled", "b": "|scaledCut",
                                 "op": "difference", "new_name": "scaled_cut"})
    scaled_after = state(scaled["name"])
    check("a scaled parent leaves no compensating node scale",
          scaled_after["scale"] == [1.0, 1.0, 1.0],
          "scale=%s, warnings=%s" % (scaled_after["scale"], scaled["warnings"]))
    check("and the geometry did not move when it was baked",
          max(abs(a - b) for a, b in
              zip(scaled_after["bbox"][:3], scaled_before["bbox"][:3])) < 1e-3,
          "%s -> %s" % (scaled_before["bbox"][:3], scaled_after["bbox"][:3]))
    check("the bake is reported, not silent",
          any("frozen into the vertices" in w for w in scaled.get("warnings") or []),
          repr(scaled.get("warnings")))

    # ---- 4. etch_text shares the same core, so it inherits the carry ----
    py("import maya.cmds as cmds\n"
       "g = cmds.group(empty=True, name='plaqueGRP')\n"
       "a = cmds.polyCube(w=4, h=4, d=1, name='plaque')[0]\n"
       "cmds.xform(a, ws=True, translation=(0, 10, 0))\n"
       "a = cmds.parent(a, g)[0]\n"
       "cmds.xform(a, ws=True, pivots=(0, 8, 0))\n'built'")
    pack("|plaqueGRP|plaque")
    # face 0 of a fresh polyCube is the +Z face, which is the plaque's front.
    etched = send("etch_text", {
        "mesh": "|plaqueGRP|plaque", "text": "MEM", "face": 0,
        "width": 2.0, "depth": 0.2, "new_name": "plaque_etched",
    }, 300.0)
    etched_state = state(etched["name"])
    check("etch_text carries the same state (it shares the boolean core)",
          etched_state["parent"] == "|plaqueGRP"
          and etched_state["pivot"] == [0.0, 8.0, 0.0]
          and inside(etched_state["uv"]),
          "parent=%s pivot=%s uv=%s"
          % (etched_state["parent"], etched_state["pivot"], etched_state["uv"]))

    if failures:
        print("\n%d FAILED: %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("\nall checks passed")


if __name__ == "__main__":
    main()
