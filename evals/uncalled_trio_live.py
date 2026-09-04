"""#829 live gate: the three commands nobody had ever sent to Maya.

The #818 coverage audit's last row - `rename`, `reset_namespace` and
`set_viewport` had no live caller at all, so everything believed about them
came from unit tests against fakes. #799 measured what that is worth: 35
hardened fakes turned up 19 handler defects a green suite had been hiding.
The probe (evals/uncalled_trio_probe_829.py) found four more here.

What it measured, and what this gate now holds:

  rename
    - Maya does not REFUSE a name it dislikes, it rewrites it: "my lamp" ->
      "my_lamp", "a|b" -> "a_b", "lamp-01" -> "lamp_01", "2lamp" -> "lamp"
      (leading digits stripped), "ns:lamp" -> "lamp" (namespace prefix
      dropped - asking for a namespace silently gets you none). All of it
      came back as a plain success with `warnings: []`.
    - A taken name was redirected to a _001 suffix, also silently.
    - Renaming a SHAPE raised a raw, hintless "No valid objects supplied to
      'xform' command" - from the ledger write, AFTER the rename had already
      happened. A failure message over a mutation that took.
    - Renaming a PARENT left every descendant's ledger entry keyed to a path
      that no longer existed, which silently retired the "moved outside
      maya-mcp" check for the whole subtree.
    - Good news, pinned here so it stays true: a rename carries the shape
      name with it, and a bound joint / shaded mesh survives one intact.

  reset_namespace
    - Works end to end; its refusal hint ended on "valid params: " and
      stopped, because it has none.

  set_viewport
    - Its icon and grid flags never reach a capture: every capture forces
      grid, lights, cameras, locators, manipulators and textures OFF for its
      own frames and restores the panel afterwards. Measured: a capture with
      the grid on is byte-identical to one with the grid off.

Usage:

    set MAYA_MCP_PORT=9878
    set MAYA_MCP_EXPECT_PID=<the pid you launched>
    python evals/uncalled_trio_live.py

MUTATES THE ANSWERING MAYA'S SCENE. Refuses 9877, the user's session.
Exit: 0 pass, 1 fail.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import textwrap

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_call import call, structured_result  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
if PORT == 9877:
    raise SystemExit("refusing 9877 - that is the user's Maya")

CHECKS: list = []


def check(label: str, passed: bool, detail: object = "") -> bool:
    CHECKS.append((label, bool(passed), detail))
    print("  %s %s%s" % ("PASS" if passed else "FAIL", label,
                         ("  <- " + str(detail)) if detail else ""))
    return bool(passed)


def preflight() -> dict:
    if not (os.environ.get("MAYA_MCP_EXPECT_PID") or "").strip():
        raise SystemExit(
            "MAYA_MCP_EXPECT_PID is not set. This gate discards the answering "
            "Maya's scene, so it will not guess which one is disposable (#648).")
    frame = call("ping", {}, port=PORT)
    if frame.get("status") != "ok":
        raise SystemExit("ping failed: %r" % (frame.get("error"),))
    ping = frame.get("result") or {}
    if (ping.get("plugin") or {}).get("restart_required"):
        raise SystemExit(
            "the answering Maya (pid %s) holds stale modules - restart it "
            "before running this gate"
            % (ping.get("process") or {}).get("pid"))
    return ping


def raw(command: str, params: dict, timeout_s: float = 180.0) -> dict:
    return call(command, params, timeout_s=timeout_s, port=PORT)


def ok(command: str, params: dict, timeout_s: float = 180.0) -> dict:
    frame = raw(command, params, timeout_s)
    if frame.get("status") != "ok":
        raise SystemExit("%s failed: %s"
                         % (command, json.dumps(frame.get("error"), indent=1)))
    return frame.get("result") or {}


def refusal(command: str, params: dict) -> dict:
    """The error frame, for the cases where being refused IS the behaviour."""
    frame = raw(command, params)
    if frame.get("status") == "ok":
        return {}
    return frame.get("error") or {}


def py(code: str, timeout_s: float = 180.0):
    body = textwrap.dedent(code).strip() + "\nr"
    res = ok("execute_python", {"code": body}, timeout_s=timeout_s)
    if res.get("traceback"):
        raise SystemExit("execute_python raised:\n" + res["traceback"])
    return structured_result(res, "r")


def shoot(**params) -> str:
    """md5 of one captured frame - the finest comparison available here."""
    args = {"angles": ["front"], "resolution": 256}
    args.update(params)
    res = ok("capture_viewport", args)
    return hashlib.md5(res["images"][0]["png_b64"].encode("ascii")).hexdigest()


LIB = r'''
import maya.cmds as cmds

DEFAULTS = ("persp", "top", "front", "side")


def clean():
    junk = [n for n in (cmds.ls(assemblies=True) or []) if n not in DEFAULTS]
    if junk:
        cmds.delete(junk)
    return True


def victim(name="victim"):
    clean()
    cmds.polyCube(name=name)
    return (cmds.ls(name, long=True) or [None])[0]


def shape_of(name):
    return [s.split("|")[-1]
            for s in (cmds.listRelatives(name, shapes=True, fullPath=True) or [])]


def move_behind_our_back(name, x):
    """What a human does with the mouse: an edit no tool recorded."""
    cmds.xform(name, worldSpace=True, translation=(x, 0, 0))
    return cmds.xform(name, query=True, worldSpace=True, translation=True)


def skin_bound(mesh):
    return bool(cmds.ls(cmds.listHistory(mesh) or [], type="skinCluster"))


def shading_groups(mesh):
    shapes = cmds.listRelatives(mesh, shapes=True, fullPath=True) or []
    if not shapes:
        return []
    return sorted(set(cmds.listConnections(shapes[0], type="shadingEngine") or []))
'''

# What Maya measurably does to a name it will not take (#829 probe A4).
MANGLED = [("my lamp", "my_lamp"), ("2lamp", "lamp"), ("a|b", "a_b"),
           ("ns:lamp", "lamp"), ("lamp-01", "lamp_01")]


def main() -> int:
    ping = preflight()
    print("answering Maya: pid %s, plugin %s"
          % ((ping.get("process") or {}).get("pid"),
             ((ping.get("plugin") or {}).get("loaded_digest") or "")[:12]))
    ok("new_scene", {"confirm": True})
    py(LIB + "\nr = 1")

    print("\nclaim 1: a clean rename renames, and says nothing")
    py("r = victim('lamp_base')")
    out = ok("rename", {"name": "lamp_base", "new_name": "base"})
    check("the node is under the new long name", out.get("name") == "|base", out)
    check("nothing to warn about, so nothing is said",
          out.get("warnings") == [], out.get("warnings"))
    check("and Maya carried the SHAPE name along with it",
          py("r = shape_of('base')") == ["baseShape"],
          py("r = shape_of('base')"))

    print("\nclaim 2: a name that was taken is REPORTED, not just returned")
    py("r = victim('shade')")
    py("cmds.polyCube(name='arm')\nr = 1")
    out = ok("rename", {"name": "shade", "new_name": "arm"})
    check("the node got the suffixed name", out.get("name") == "|arm_001", out)
    notes = out.get("warnings") or []
    check("exactly one warning, and it names both names",
          len(notes) == 1 and "already taken" in notes[0]
          and "'arm'" in notes[0] and "arm_001" in notes[0], notes)

    print("\nclaim 3: a name MAYA rewrote is reported (it rewrites, never refuses)")
    for requested, expected in MANGLED:
        py("r = victim()")
        out = ok("rename", {"name": "victim", "new_name": requested})
        notes = out.get("warnings") or []
        got = (out.get("name") or "").lstrip("|")
        check("%-9r became %-9r live" % (requested, got), got == expected,
              "expected %r, Maya gave %r" % (expected, got))
        check("   ...and one warning names what was asked and what was got",
              len(notes) == 1 and "does not accept" in notes[0]
              and repr(requested) in notes[0] and repr(got) in notes[0], notes)

    print("\nclaim 4: a name Maya KEEPS is not reported as a rewrite")
    py("r = victim()")
    out = ok("rename", {"name": "victim", "new_name": "lampé"})
    check("an accented name survives and draws no warning",
          out.get("name") == "|lampé" and out.get("warnings") == [], out)

    print("\nclaim 5: renaming a SHAPE works, instead of raising after doing it")
    py("r = victim()")
    shape = py("r = (cmds.listRelatives('victim', shapes=True, fullPath=True) or [''])[0]")
    frame = raw("rename", {"name": shape, "new_name": "victim_geo"})
    check("the call succeeds", frame.get("status") == "ok",
          (frame.get("error") or {}).get("message"))
    check("and the shape really is renamed",
          py("r = shape_of('victim')") == ["victim_geo"],
          py("r = shape_of('victim')"))

    print("\nclaim 6: renaming a PARENT keeps the outside-edit check alive for "
          "its children")
    py("r = clean()")
    ok("create_primitive", {"kind": "cube", "name": "kid"})
    ok("transform", {"names": ["kid"], "translate": [1, 0, 0]})
    grp = ok("group", {"names": ["kid"], "group_name": "rig"})
    renamed = ok("rename", {"name": grp["name"], "new_name": "lamp_rig"})
    check("the group is renamed", renamed.get("name") == "|lamp_rig", renamed)
    py("r = move_behind_our_back('|lamp_rig|kid', 7.0)")
    after = ok("transform", {"names": ["|lamp_rig|kid"], "translate": [1, 0, 0]})
    moved = [w for w in (after.get("warnings") or [])
             if "outside maya-mcp" in w]
    check("a hand-moved child of a renamed group is still noticed",
          len(moved) == 1, after.get("warnings"))

    print("\nclaim 7: a rename does not break a bind or a material")
    py("r = clean()")
    ok("create_primitive", {"kind": "cube", "name": "skin_me",
                            "scale": [1, 4, 1], "subdivisions": [2, 6, 2]})
    ok("create_skeleton", {"joints": [
        {"name": "root_jnt", "position": [0, -2, 0]},
        {"name": "tip_jnt", "position": [0, 2, 0], "parent": "root_jnt"}]})
    ok("bind_skin", {"mesh": "skin_me", "root": "root_jnt"})
    ok("assign_material", {"mesh": "skin_me", "shader": "standardSurface",
                           "name": "lamp_mat"})
    before_sg = py("r = shading_groups('skin_me')")
    ok("rename", {"name": "root_jnt", "new_name": "hip_jnt"})
    ok("rename", {"name": "skin_me", "new_name": "lamp_mesh"})
    check("the skin is still bound after renaming its joint and its mesh",
          py("r = skin_bound('lamp_mesh')") is True)
    check("the material assignment survived",
          py("r = shading_groups('lamp_mesh')") == before_sg, before_sg)
    report = ok("weight_report", {"mesh": "lamp_mesh"})
    check("weight_report reads the renamed rig, under the renamed joint",
          report.get("mesh") == "|lamp_mesh"
          and any("hip_jnt" in j["joint"] for j in report.get("per_joint") or []),
          [j["joint"] for j in report.get("per_joint") or []])

    print("\nclaim 8: reset_namespace really empties the namespace")
    check("a name defined through execute_python is there for the next call",
          py("gate829 = 41 + 1\nr = gate829") == 42)
    check("reset says it reset", ok("reset_namespace", {}).get("reset") is True)
    gone = raw("execute_python", {"code": "r = gate829\nr"})
    tb = ((gone.get("result") or {}).get("traceback") or "")
    check("and the name is really gone from the live process",
          "NameError" in tb and "gate829" in tb, tb.strip().splitlines()[-1:])
    check("while cmds still works, so the namespace was rebuilt not broken",
          py("r = len(cmds.ls(assemblies=True)) > 0") is True)
    # That reset took THIS GATE's helpers with it, which is the command
    # working. Put them back before the claims that use them.
    py(LIB + "\nr = 1")

    print("\nclaim 9: a command that reads NO params says that, rather than "
          "trailing off")
    err = refusal("reset_namespace", {"confirm": True})
    check("it is refused", bool(err), err)
    check("and the hint states the fact instead of naming an empty list",
          "reads no params at all" in (err.get("hint") or ""), err.get("hint"))

    print("\nclaim 10: set_viewport reads the panel back, with a long camera name")
    py("r = clean()")
    ok("create_primitive", {"kind": "cube", "name": "subject"})
    state = ok("set_viewport", {})
    check("a pure query changes nothing and warns about nothing",
          state.get("warnings") == [], state.get("warnings"))
    check("the camera comes back canonical long",
          (state.get("camera") or "").startswith("|"), state.get("camera"))
    check("the panel is named", bool(state.get("panel")), state)

    print("\nclaim 11: the flags a capture overrides are named as such")
    grid_off = ok("set_viewport", {"show_grid": False})
    check("switching one OFF is not worth a word",
          grid_off.get("warnings") == [], grid_off.get("warnings"))
    off_frame = shoot()
    grid_on = ok("set_viewport", {"show_grid": True})
    notes = grid_on.get("warnings") or []
    check("switching the grid ON says the capture will not show it",
          len(notes) == 1 and "grid is now shown" in notes[0]
          and "force it off" in notes[0], notes)
    on_frame = shoot()
    check("and the frames prove it: grid on and grid off are byte-identical",
          on_frame == off_frame, "%s vs %s" % (on_frame[:12], off_frame[:12]))
    check("the flag itself really is on in the panel, for the human",
          ok("set_viewport", {}).get("show_grid") is True)

    print("\nclaim 12: display_lights round-trips, and a bad one is refused")
    for mode in ("default", "all", "active", "flat", "none"):
        got = ok("set_viewport", {"display_lights": mode})
        check("display_lights %-8s round-trips" % mode,
              got.get("display_lights") == mode and got.get("warnings") == [],
              got.get("display_lights"))
    err = refusal("set_viewport", {"display_lights": "nonsense"})
    check("an unknown display_lights is refused, naming the valid ones",
          "unknown display_lights" in (err.get("message") or "")
          and "flat" in (err.get("hint") or ""), err)

    print("\nclaim 13: a capture leaves the persistent settings alone")
    ok("set_viewport", {"display_lights": "default", "show_grid": True})
    before = ok("set_viewport", {})
    ok("capture_viewport", {"angles": ["three_quarter"], "resolution": 192})
    after = ok("set_viewport", {})
    keys = [k for k in before if k not in ("warnings",)]
    check("every panel setting survives a capture unchanged",
          all(before[k] == after[k] for k in keys),
          {k: (before[k], after[k]) for k in keys if before[k] != after[k]})

    failed = [c for c in CHECKS if not c[1]]
    print("\n%d/%d checks passed" % (len(CHECKS) - len(failed), len(CHECKS)))
    for label, _, detail in failed:
        print("  FAILED: %s  <- %s" % (label, detail))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
