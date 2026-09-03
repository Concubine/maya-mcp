"""Live gate for redmine #797: a param a branch drops is refused, not kept.

#764 refused an unknown KEY and #767 made every command declare its key set.
This ticket is the level below: a key the handler knows, validates, and then
never consumes on the branch another param's value selects - `divisions` on
an icosahedron (polyPlatonicSolid has no subdivision flag; the caller asked
for a denser solid and got the same 20 faces), `pivot='origin'` with nothing
combined, `project='keep'` under `world_scale` (box-autoprojected over an
authored layout), `target` when every angle is 'current' (nothing framed,
and the only existence check never ran), a `pole` on the start-target line
(no bend plane, and the straight-chain warning silenced by its presence), a
lattice baked before its handle moved (`baked: true` for a mesh never
touched). The headless suite (tests/test_branch_contract.py) proves each
refusal fires before the first Maya import; this gate proves the branch the
refusal names really is the branch Maya takes, and that the sibling branch
that DOES consume the param still builds.

Two things only a live Maya can settle are asserted here too:
  * `samples` under hw2 is reported null (hw2 has no AA count), and under
    arnold on a COLD mtoa (the options node absent until createOptions) the
    requested count still lands and the user's default is restored after.
  * a fresh polyUnite result's pivot sits at the origin, so `pivot='keep'`
    on a combined result is the same thing as 'origin' (measured 2026-09-03).

DESTRUCTIVE: calls new_scene. Runs against the disposable agent Maya on 9879
(or 9878) and REFUSES 9877 (the user's session) unless
MAYA_MCP_ALLOW_USER_SESSION=1. The live Maya must be launched with the repo
as its working directory so it imports THIS working tree's plugin (phase 0
asserts it), and for the cold-arnold check it must be a FRESH session in
which nothing has rendered with arnold yet (phase 0 reports it; the check
degrades to a warm assertion otherwise).

Run:  MAYA_MCP_PORT=9879 MAYA_MCP_EXPECT_PID=<pid> .venv/Scripts/python.exe evals/inert_branches_live.py
Exit: 0 pass, 1 fail, 2 environment (nothing listening / wrong code loaded).
"""

from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, _HERE)

from live_call import call, structured_result  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9879"))
if PORT == 9877 and os.environ.get("MAYA_MCP_ALLOW_USER_SESSION") != "1":
    print("refusing to run against port 9877 (the user's Maya): this gate "
          "calls new_scene. Launch the agent Maya on 9879/9878 with the repo "
          "as its cwd, or set MAYA_MCP_ALLOW_USER_SESSION=1 on purpose.")
    raise SystemExit(2)

CHECKS = []


def check(label, passed, detail=""):
    CHECKS.append((bool(passed), label))
    print("%-4s %s%s" % ("PASS" if passed else "FAIL", label,
                         ("  [%s]" % detail) if detail else ""))
    return bool(passed)


def send(command, params, timeout_s=300.0):
    try:
        return call(command, params, timeout_s=timeout_s, port=PORT)
    except (ConnectionRefusedError, OSError) as exc:
        print("could not reach a Maya plugin on %s: %s" % (PORT, exc))
        sys.exit(2)


def ok(command, params, timeout_s=300.0):
    response = send(command, params, timeout_s)
    if response.get("status") != "ok":
        print("FAIL: %s: %s" % (command, json.dumps(response.get("error"))[:800]))
        sys.exit(1)
    return response.get("result") or {}


def refusal(command, params, timeout_s=300.0):
    response = send(command, params, timeout_s)
    if response.get("status") == "ok":
        return None
    return response.get("error") or {}


def refused_inert(label, command, params, param, *words, timeout_s=300.0):
    """The generic recogniser test_branch_contract.py uses, over the wire."""
    err = refusal(command, params, timeout_s)
    msg = (err or {}).get("message", "")
    passed = err is not None and "does not use" in msg and param in msg and all(
        w in msg for w in words)
    return check(label, passed, msg[:160] if msg else "call succeeded")


def py(code, what, timeout_s=300.0):
    return structured_result(ok("execute_python", {"code": code}, timeout_s),
                             what)


def faces(name):
    return py("import maya.cmds as cmds\ncmds.polyEvaluate(%r, face=True)" % name,
              "faces of %s" % name)


def main():
    # ---- 0. who answered, and WHOSE code is it -------------------------
    ident = py("import os, maya_plugin, maya.cmds as cmds\n"
               "{'pid': os.getpid(), 'plugin': maya_plugin.__file__,\n"
               " 'arnold_cold': not cmds.objExists('defaultArnoldRenderOptions')}",
               "identity")
    print("maya on %d: pid %s\nplugin: %s\narnold cold: %s\n"
          % (PORT, ident["pid"], ident["plugin"], ident["arnold_cold"]))
    if os.path.normcase(REPO) not in os.path.normcase(ident["plugin"]):
        print("the live Maya is running the plugin at %s, NOT this working "
              "tree (%s). Relaunch Maya with the repo as its working "
              "directory." % (ident["plugin"], REPO))
        sys.exit(2)
    ok("new_scene", {"confirm": True})

    # ==================================================================
    # Row 1: divisions on a platonic solid
    # ==================================================================
    refused_inert("row 1: divisions on an icosahedron is refused",
                  "create_primitive",
                  {"kind": "icosahedron", "name": "gem", "divisions": 3},
                  "divisions", "icosahedron")
    check("row 1: ... and nothing named gem was built",
          not py("import maya.cmds as cmds\ncmds.objExists('gem')", "gem exists"))
    gem = ok("create_primitive", {"kind": "icosahedron", "name": "gem"})
    check("row 1: an icosahedron without divisions builds its 20 faces",
          faces(gem["name"]) == 20 and gem.get("faces") == 20,
          "faces %s reported %s" % (faces(gem["name"]), gem.get("faces")))
    cube = ok("create_primitive", {"kind": "cube", "name": "blk", "divisions": 3})
    check("row 1: divisions still bills on a kind that spends it (cube 3 -> 54)",
          faces(cube["name"]) == 54, "faces %s" % faces(cube["name"]))

    # ==================================================================
    # Rows 8 + 10: project/uv_per_metre under world_scale, and the pivot
    # ==================================================================
    refused_inert("row 8: uv_atlas project=keep with world_scale is refused",
                  "uv_atlas", {"names": [cube["name"]], "world_scale": 2.0,
                               "project": "keep"}, "project", "world_scale")
    refused_inert("row 10: uv_atlas uv_per_metre without world_scale is refused",
                  "uv_atlas", {"names": [cube["name"]], "uv_per_metre": 1.0},
                  "uv_per_metre", "world_scale")
    atlas = ok("uv_atlas", {"names": [cube["name"]], "world_scale": 2.0,
                            "project": "box"})
    check("row 8: box + world_scale still packs, reports projection 'world' "
          "and the APPLIED constant",
          atlas.get("projection") == "world"
          and isinstance(atlas.get("uv_per_metre"), (int, float))
          and isinstance(atlas.get("warnings"), list),
          json.dumps({k: atlas.get(k) for k in ("projection", "uv_per_metre",
                                                 "normalized", "warnings")}))
    plain = ok("uv_atlas", {"names": [cube["name"]], "patch": 1})
    check("row 10: without world_scale the result claims no uv_per_metre",
          plain.get("uv_per_metre") is None, "uv_per_metre %r" % plain.get("uv_per_metre"))

    part = {"pos": [0, 0.5, 0], "dim": [1, 1, 1]}
    refused_inert("row 6: assemble pivot=origin with combine=false is refused",
                  "assemble", {"name": "kit", "parts": [part, part],
                               "combine": False, "pivot": "origin"},
                  "pivot", "combine")
    refused_inert("row 8: assemble atlas project=keep with world_scale is refused",
                  "assemble", {"name": "kit", "parts": [part],
                               "atlas": {"world_scale": 2.0, "project": "keep"}},
                  "project", "world_scale")
    refused_inert("row 7: a part's patch with atlas=null is refused",
                  "assemble", {"name": "kit", "parts": [dict(part, patch=3)]},
                  "patch", "atlas")
    pivot = py(
        "import maya.cmds as cmds\n"
        "a = cmds.polyCube(name='pa')[0]; cmds.xform(a, ws=True, t=(1, 2, 3))\n"
        "b = cmds.polyCube(name='pb')[0]; cmds.xform(b, ws=True, t=(3, 4, 5))\n"
        "u = cmds.polyUnite([a, b], ch=False, name='pu')[0]\n"
        "bb = cmds.exactWorldBoundingBox(u)\n"
        "{'rp': [round(v, 6) for v in cmds.xform(u, q=True, ws=True, rotatePivot=True)],\n"
        " 'centre': [round((bb[i] + bb[i + 3]) / 2.0, 6) for i in range(3)]}",
        "polyUnite pivot")
    check("probe: a fresh polyUnite result's pivot is the ORIGIN, not its "
          "centre - so pivot='keep' on a combine result keeps nothing",
          pivot["rp"] == [0.0, 0.0, 0.0] and pivot["centre"] != [0.0, 0.0, 0.0],
          json.dumps(pivot))
    ka = ok("create_primitive", {"kind": "cube", "name": "ka", "translate": [1, 2, 3]})
    kb = ok("create_primitive", {"kind": "cube", "name": "kb", "translate": [3, 4, 5]})
    kept = ok("combine", {"names": [ka["name"], kb["name"]], "name": "kept",
                          "pivot": "keep"}, timeout_s=120.0)
    kept_pivot = kept.get("pivot")
    check("combine pivot='keep' on a united result reports the origin AND warns "
          "that keep is origin here",
          kept_pivot == [0.0, 0.0, 0.0]
          and any("origin" in w for w in kept.get("warnings", [])),
          "pivot %r warnings %s" % (kept_pivot, json.dumps(kept.get("warnings", []))[:200]))

    # ==================================================================
    # Rows 18/19: hdri_path on the presets that build no file-driven dome
    # ==================================================================
    ok("setup_lighting", {"preset": "three_point"})
    lights_before = py("import maya.cmds as cmds\nlen(cmds.ls(lights=True))",
                       "light count")
    refused_inert("row 18: hdri_path on three_point is refused", "setup_lighting",
                  {"preset": "three_point", "hdri_path": "C:/nowhere/sky.hdr"},
                  "hdri_path", "three_point")
    refused_inert("row 19: hdri_path on environment is refused", "setup_lighting",
                  {"preset": "environment", "hdri_path": "C:/nowhere/sky.hdr"},
                  "hdri_path", "environment")
    missing = refusal("setup_lighting", {"preset": "hdri",
                                         "hdri_path": "C:/nowhere/sky.hdr"})
    lights_after = py("import maya.cmds as cmds\nlen(cmds.ls(lights=True))",
                      "light count")
    check("row 18: a nonexistent hdri file is refused BEFORE the rig is replaced",
          missing is not None and lights_after == lights_before,
          "lights %s -> %s; %s" % (lights_before, lights_after,
                                   (missing or {}).get("message", "")[:120]))

    # ==================================================================
    # Row 20/26: target under 'current'; empty turntable target
    # ==================================================================
    refused_inert("row 20: capture_viewport target with angles=['current'] is refused",
                  "capture_viewport", {"angles": ["current"], "target": [cube["name"]]},
                  "target", "current")
    typo = refusal("capture_viewport", {"angles": ["current", "front"],
                                        "target": ["|no_such_thing"],
                                        "resolution": 128})
    check("row 20: a typo target on a MIXED list is refused, naming target",
          typo is not None and "target" in (typo.get("message", "")),
          (typo or {}).get("message", "call succeeded")[:160])
    mixed = ok("capture_viewport", {"angles": ["current", "front"],
                                    "target": [cube["name"]], "resolution": 128})
    check("row 20: a real target on a mixed list captures both frames and the "
          "current frame says it was not framed on it",
          len(mixed.get("images", [])) == 2
          and any("current" in w and "target" in w for w in mixed.get("warnings", [])),
          json.dumps(mixed.get("warnings", []))[:300])
    refused_inert("row 26: capture_turntable target='' is refused",
                  "capture_turntable", {"target": "", "n_frames": 2},
                  "target", "empty")

    # ==================================================================
    # Row 21 + 29: render_sheet current; samples under hw2 / cold arnold
    # ==================================================================
    refused_inert("row 21: render_sheet angle='current' is refused", "render_sheet",
                  {"subjects": [cube["name"]], "angle": "current"}, "angle", "current")
    hw2 = ok("render_scene", {"angles": ["front"], "renderer": "hw2",
                              "resolution": 128, "samples": 4})
    check("row 29: samples under hw2 is reported null and warned",
          hw2.get("samples") is None
          and any("samples" in w for w in hw2.get("warnings", [])),
          "samples %r warnings %s" % (hw2.get("samples"),
                                       json.dumps(hw2.get("warnings", []))[:200]))
    cur = ok("render_scene", {"angles": ["current"], "renderer": "hw2",
                              "resolution": 128})
    frame = (cur.get("images") or [{}])[0]
    check("row 30: render_scene 'current' is labelled with the angle SHOT and "
          "carries requested_angle",
          frame.get("angle") == "three_quarter" and frame.get("requested_angle") == "current",
          json.dumps({k: frame.get(k) for k in ("angle", "requested_angle")}))
    cold = ident["arnold_cold"]
    arn = ok("render_scene", {"angles": ["front"], "renderer": "arnold",
                              "resolution": 96, "samples": 5}, timeout_s=600.0)
    after = py("import maya.cmds as cmds\n"
               "{'exists': cmds.objExists('defaultArnoldRenderOptions'),\n"
               " 'aa': cmds.getAttr('defaultArnoldRenderOptions.AASamples')}",
               "arnold options after render")
    check("row 29 (%s arnold): the requested samples land - no 'samples' "
          "warning, result reports 5" % ("COLD" if cold else "warm"),
          arn.get("samples") == 5
          and not any("samples" in w for w in arn.get("warnings", [])),
          "samples %r warnings %s" % (arn.get("samples"),
                                       json.dumps(arn.get("warnings", []))[:200]))
    check("row 29: after the render the options node exists and the user's AA "
          "count is restored (not left at 5)",
          after["exists"] and after["aa"] != 5, json.dumps(after))

    # ==================================================================
    # Row 22: a pole on the start-target line
    # ==================================================================
    skel = ok("create_skeleton", {"chain": [[0, 0, 0], [0, 1, 0], [0, 2, 0]],
                                  "chain_prefix": "s"})
    names = [j["name"] for j in skel["joints"]]
    root, end = names[0], names[-1]
    refused_inert("row 22: pose_ik with a pole ON the start-target line is refused",
                  "pose_ik", {"root": root, "joint": end, "start": root,
                              "target": [0, 1.5, 0], "pole": [0, 5, 0]},
                  "pole", "line")
    solved = ok("pose_ik", {"root": root, "joint": end, "start": root,
                            "target": [0, 1.5, 0], "pole": [3, 1, 0]})
    check("row 22: a pole OFF the line solves and folds toward it",
          solved.get("residual", 1.0) < 0.05 and solved.get("pole_used") == [3, 1, 0],
          "residual %r pole_used %r" % (solved.get("residual"), solved.get("pole_used")))

    # ==================================================================
    # Row 27: a lattice baked before its handle moved
    # ==================================================================
    col = ok("create_primitive", {"kind": "cylinder", "name": "col",
                                  "subdivisions": [12, 8], "scale": [0.3, 2.0, 0.3]})
    refused_inert("row 27: deform lattice + delete_history_after with no move is refused",
                  "deform", {"mesh": col["name"], "deformer": "lattice",
                             "delete_history_after": True},
                  "delete_history_after", "lattice")
    baked = ok("deform", {"mesh": col["name"], "deformer": "lattice",
                          "params": {"divisions": [2, 5, 2], "translate": [0.4, 0, 0]},
                          "delete_history_after": True})
    check("row 27: lattice + translate + bake stays legal and MOVES the mesh",
          baked.get("baked") is True and baked.get("max_displacement", 0.0) > 0.05,
          "max_displacement %r warnings %s" % (baked.get("max_displacement"),
                                                json.dumps(baked.get("warnings", []))[:200]))

    # ==================================================================
    # Row 23 + 24: restore both-given; clean_clip window past the clip
    # ==================================================================
    cp = ok("checkpoint", {"label": "gate"})
    refused_inert("row 23: restore_checkpoint with a path AND a different id is refused",
                  "restore_checkpoint", {"checkpoint_id": "000_other", "path": cp["path"]},
                  "checkpoint_id", "path")
    keys = [{"time_s": 0.0, "rotations": {names[1]: [0, 0, 0]}},
            {"time_s": 0.3, "rotations": {names[1]: [0, 0, 20]}}]
    clip = ok("author_clip", {"root": root, "name": "nod", "fps": 30,
                              "interpolation": "smooth", "keys": keys})
    n_frames = int(clip.get("frames") or (clip["end_frame"] - clip["start_frame"] + 1))
    refused_inert("row 24: clean_clip filter window %d on a %d-frame clip is refused"
                  % (n_frames + 20, n_frames),
                  "clean_clip", {"root": root, "clip": "nod",
                                 "filter": {"window": n_frames + 20 | 1},
                                 "lock_contacts": False},
                  "window", "clip")
    cleaned = ok("clean_clip", {"root": root, "clip": "nod", "filter": {"window": 5},
                                "lock_contacts": False})
    check("row 24: a window that fits still smooths", isinstance(cleaned, dict)
          and not any("does not use" in w for w in cleaned.get("warnings", [])),
          json.dumps(cleaned.get("warnings", []))[:200])

    # ---- summary ----------------------------------------------------
    failed = [label for passed, label in CHECKS if not passed]
    print("\n%d checks, %d failed" % (len(CHECKS), len(failed)))
    for label in failed:
        print("  FAIL " + label)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
