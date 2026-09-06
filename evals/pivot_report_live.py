"""Live gate for redmine #831: transform says where the object went.

A fresh agent scaled two lamp parts about an external pivot; the geometry
moved, the result's `translate` did not change, and the docstring had said
to trust the result over its own bookkeeping. Measured
(evals/pivot_probe_831): `xform -q -ws -t` answers the translate CHANNEL,
which a rotate or scale about a pivot off the origin leaves alone while the
object moves. The result now carries world_position (the origin, from the
world matrix) and bbox_center, and a warning names the move the channel did
not report. This proves it through the real wire route, on cubes at
(18.22, 34.17, 0) - the reporter's numbers.

  1  pivot (0,0,0) + scale x2: translate unchanged, world_position and
     bbox_center at (36.44, 68.34, 0), a warning naming "scaled about a
     pivot", 38.7 units, and world_position
  2  pivot (0,0,0) + rotate 90 about Z: world_position (-34.17, 18.22, 0)
     and a "rotated about a pivot" warning
  3  scale x2 with no pivot: nothing moves, no warning
  4  pivot (0,0,0) alone: nothing moves, no warning; then scale x2 in a
     LATER call with no pivot param: the object moves and the warning fires
  5  pivot at the cube's own centre + scale x2: no warning
  6  a translate on the already pivot-scaled cube of check 1: no warning,
     world_position moves by exactly the translate
  7  a cube whose vertices sit 5 above its origin, pivot (0,0,0) + scale
     x2 from (50,0,0): world_position (100,0,0), bbox_center (100,10,0)
  8  an empty group, pivot (0,0,0) + scale x2: bbox_center None,
     world_position doubled, the warning says "no geometry"
  9  a cube parented under a group at (10,0,0): world_position
     (36.44, 68.34, 0) after the pivot scale
 10  get_object_info's transform section carries the same world_position
     as transform's result for the cube of check 1

Defaults to port 9878 and refuses 9877 unless MAYA_MCP_ALLOW_USER_SESSION=1
(it creates objects in the open scene; leftovers named g831_* are deleted
first so it can be rerun on one process).

Run:  .venv/Scripts/python.exe evals/pivot_report_live.py
Exit: 0 pass, 1 fail, 2 no connection.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_call import DEFAULT_PORT, call  # noqa: E402

PORT = DEFAULT_PORT
START = [18.22, 34.17, 0.0]
results: list = []


def send(command: str, params: dict, timeout_s: float = 60.0) -> dict:
    try:
        return call(command, params, timeout_s=timeout_s, port=PORT)
    except (ConnectionRefusedError, OSError) as exc:
        print("could not reach a Maya plugin on %s: %s" % (PORT, exc))
        sys.exit(2)


def ok(command: str, params: dict, timeout_s: float = 60.0) -> dict:
    response = send(command, params, timeout_s)
    if response.get("status") != "ok":
        print("FAIL: %s: %s" % (command, json.dumps(response.get("error"))[:400]))
        sys.exit(1)
    return response.get("result") or {}


def py(code: str) -> dict:
    result = ok("execute_python", {"code": code})
    if result.get("traceback"):
        print("FAIL: execute_python raised:\n%s" % result["traceback"])
        sys.exit(1)
    return result


def check(label: str, passed: bool, detail: str) -> None:
    print("%s %s: %s" % ("PASS" if passed else "FAIL", label, detail))
    results.append((label, passed))


def near(a, b, tol: float = 1e-3) -> bool:
    return (a is not None and b is not None and len(a) == len(b)
            and all(abs(float(x) - float(y)) <= tol for x, y in zip(a, b)))


def r3(v):
    return None if v is None else [round(float(x), 3) for x in v]


def cube(name: str, at=START, size: float = 10.0) -> str:
    py("import maya.cmds as cmds\n"
       "n = cmds.polyCube(name=%r, w=%r, h=%r, d=%r, ch=False)[0]\n"
       "cmds.xform(n, ws=True, t=%r)\n" % (name, size, size, size, tuple(at)))
    return "|" + name


def transform(names, **params) -> dict:
    return ok("transform", dict(params, names=names))


def where(obj: dict) -> str:
    return "translate %s world_position %s bbox_center %s" % (
        r3(obj.get("translate")), r3(obj.get("world_position")), r3(obj.get("bbox_center")))


def main() -> None:
    if PORT == 9877 and os.environ.get("MAYA_MCP_ALLOW_USER_SESSION") != "1":
        print("refusing to run on 9877: this eval creates objects in the open scene. "
              "Set MAYA_MCP_ALLOW_USER_SESSION=1 to override.")
        sys.exit(2)
    py("import maya.cmds as cmds\n"
       "old = cmds.ls('g831_*', long=True) or []\n"
       "if old:\n"
       "    cmds.delete(old)\n")

    # 1: the reporter's case
    a = cube("g831_A")
    out = transform([a], pivot=[0, 0, 0], scale=[2, 2, 2])
    obj = out["objects"][0]
    warnings = out.get("warnings") or []
    check("1a translate is the unchanged channel", near(obj["translate"], START),
          "translate %s" % r3(obj["translate"]))
    check("1b world_position is where the origin went",
          near(obj.get("world_position"), [36.44, 68.34, 0]),
          "world_position %s" % r3(obj.get("world_position")))
    check("1c bbox_center is where the geometry went",
          near(obj.get("bbox_center"), [36.44, 68.34, 0]),
          "bbox_center %s" % r3(obj.get("bbox_center")))
    text = warnings[0] if warnings else ""
    check("1d the warning names the move",
          "scaled about a pivot" in text and "38.7" in text
          and "world_position" in text and "36.44, 68.34" in text,
          "warnings %s" % json.dumps(warnings))

    # 2: a rotate about the same pivot
    b = cube("g831_B")
    out = transform([b], pivot=[0, 0, 0], rotate=[0, 0, 90])
    obj = out["objects"][0]
    check("2a a rotate about the pivot moves the origin too",
          near(obj.get("world_position"), [-34.17, 18.22, 0]) and near(obj["translate"], START),
          where(obj))
    check("2b and says so", any("rotated about a pivot" in w for w in out.get("warnings") or []),
          "warnings %s" % json.dumps(out.get("warnings")))

    # 3: control - a scale about the object's own pivot
    d = cube("g831_D")
    out = transform([d], scale=[2, 2, 2])
    obj = out["objects"][0]
    check("3 a scale about the object's own pivot moves nothing and says nothing",
          near(obj.get("world_position"), START) and near(obj.get("bbox_center"), START)
          and (out.get("warnings") or []) == [],
          "%s warnings %s" % (where(obj), json.dumps(out.get("warnings"))))

    # 4: the pivot placed in an earlier call
    f = cube("g831_F")
    first = transform([f], pivot=[0, 0, 0])
    obj = first["objects"][0]
    check("4a a pivot alone moves nothing and says nothing",
          near(obj.get("world_position"), START) and (first.get("warnings") or []) == [],
          "%s warnings %s" % (where(obj), json.dumps(first.get("warnings"))))
    second = transform([f], scale=[2, 2, 2])
    obj = second["objects"][0]
    check("4b a later scale with no pivot param carries the object and says so",
          near(obj.get("world_position"), [36.44, 68.34, 0]) and near(obj["translate"], START)
          and any("scaled about a pivot" in w for w in second.get("warnings") or []),
          "%s warnings %s" % (where(obj), json.dumps(second.get("warnings"))))

    # 5: a pivot param that lands where the pivot already was
    g = cube("g831_G")
    out = transform([g], pivot=START, scale=[2, 2, 2])
    obj = out["objects"][0]
    check("5 a pivot at the object's own origin changes nothing",
          near(obj.get("world_position"), START) and (out.get("warnings") or []) == [],
          "%s warnings %s" % (where(obj), json.dumps(out.get("warnings"))))

    # 6: a translate on the pivot-scaled cube of check 1
    out = transform([a], translate=[1, 0, 0])
    obj = out["objects"][0]
    check("6 a translate is reported by the channel and gets no warning",
          near(obj["translate"], [19.22, 34.17, 0])
          and near(obj.get("world_position"), [37.44, 68.34, 0])
          and (out.get("warnings") or []) == [],
          "%s warnings %s" % (where(obj), json.dumps(out.get("warnings"))))

    # 7: geometry offset from its origin
    py("import maya.cmds as cmds\n"
       "n = cmds.polyCube(name='g831_offset', w=2, h=2, d=2, ch=False)[0]\n"
       "cmds.move(0, 5, 0, n + '.vtx[*]', r=True)\n"
       "cmds.xform(n, ws=True, t=(50, 0, 0))\n")
    out = transform(["|g831_offset"], pivot=[0, 0, 0], scale=[2, 2, 2])
    obj = out["objects"][0]
    check("7 the origin and the geometry are two answers",
          near(obj.get("world_position"), [100, 0, 0]) and near(obj.get("bbox_center"), [100, 10, 0]),
          where(obj))

    # 8: a node with no geometry under it
    py("import maya.cmds as cmds\n"
       "g = cmds.group(empty=True, name='g831_empty')\n"
       "cmds.xform(g, ws=True, t=(5, 6, 7))\n")
    out = transform(["|g831_empty"], pivot=[0, 0, 0], scale=[2, 2, 2])
    obj = out["objects"][0]
    check("8 a node with no geometry has no bbox centre but an origin",
          obj.get("bbox_center") is None and near(obj.get("world_position"), [10, 12, 14])
          and any("no geometry" in w for w in out.get("warnings") or []),
          "%s warnings %s" % (where(obj), json.dumps(out.get("warnings"))))

    # 9: a parented object
    py("import maya.cmds as cmds\n"
       "g = cmds.group(empty=True, name='g831_Egrp')\n"
       "cmds.xform(g, ws=True, t=(10, 0, 0))\n"
       "n = cmds.polyCube(name='g831_E', w=10, h=10, d=10, ch=False)[0]\n"
       "n = cmds.parent(n, g)[0]\n"
       "cmds.xform(n, ws=True, t=(18.22, 34.17, 0))\n")
    out = transform(["|g831_Egrp|g831_E"], pivot=[0, 0, 0], scale=[2, 2, 2])
    obj = out["objects"][0]
    check("9 a parented object reports its world origin",
          near(obj.get("world_position"), [36.44, 68.34, 0]) and near(obj["translate"], START),
          where(obj))

    # 10: the read-side twin agrees
    info = ok("get_object_info", {"name": a, "include": ["transform"]})
    section = info.get("transform") or {}
    check("10 get_object_info's transform section carries the same world_position",
          near(section.get("world_position"), [37.44, 68.34, 0])
          and near(section.get("translate"), [19.22, 34.17, 0]),
          "transform section %s" % json.dumps(section))

    failed = [label for label, passed in results if not passed]
    print("\n%d checks, %d failed%s" % (len(results), len(failed),
                                        (": " + ", ".join(failed)) if failed else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
