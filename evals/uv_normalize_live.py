"""Live gate for redmine #845 (and the pre-flight half of #836): uv_atlas
normalises COLLECTIVELY, its result says when faces are stacked, and the bake
tools refuse a stacked layout instead of running for an hour.

Measured on Maya 2027: polyNormalizeUV normalizeType=0 scales EVERY FACE to
the full square on its own (a projected cube's faces went from 0.056-0.167 of
the square to 1.000 each); normalizeType=1 is the collective mode. The tool
sent 0 for its whole life. Baking AO through such a layout on a 58k-tri mesh
ran past 16 minutes at 256x256; the same mesh laid out bakes in under a
second.

  1  uv_atlas on a cube: no face spans the patch; face_census says so
  2  the same cube, per-face-normalised by hand (normalizeType=0):
     bake_mesh_maps refuses, names #845, and comes back in well under a
     minute - without baking
  3  the kethran body (evals/kethran_run/kethran.ma) through uv_atlas box:
     no face spans the patch, and a 256 AO bake completes in under 60 s
     (0.6 s measured with a clean layout, 16+ minutes with the old one)

DESTRUCTIVE: calls new_scene and opens a scene. Defaults to port 9878 and
refuses 9877 unless MAYA_MCP_ALLOW_USER_SESSION=1.

Run:  .venv/Scripts/python.exe evals/uv_normalize_live.py
Exit: 0 pass, 1 fail, 2 no connection.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import textwrap
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_call import DEFAULT_PORT, call, structured_result  # noqa: E402

PORT = DEFAULT_PORT
HERE = os.path.dirname(os.path.abspath(__file__))
SCENE = os.path.join(HERE, "kethran_run", "kethran.ma").replace("\\", "/")
BODY = "|kethran|body"
BAKE_BUDGET_S = 60.0

failures = []

CENSUS = """
import maya.api.OpenMaya as om
sel = om.MSelectionList(); sel.add(%r)
fn = om.MFnMesh(sel.getDagPath(0))
us, vs = fn.getUVs()
counts, ids = fn.getAssignedUVs()
k = 0; areas = []
for c in counts:
    face = ids[k:k + c]; k += c
    if not face:
        continue
    xs = [us[i] for i in face]; ys = [vs[i] for i in face]
    areas.append((max(xs) - min(xs)) * (max(ys) - min(ys)))
census = {'faces': len(areas), 'largest': round(max(areas), 4) if areas else None,
          'spanning': sum(1 for a in areas if a >= 0.5)}
"""


def send(command: str, params: dict, timeout_s: float = 120.0):
    try:
        response = call(command, params, timeout_s=timeout_s, port=PORT)
    except (ConnectionRefusedError, OSError) as exc:
        print("could not reach a Maya plugin on %s: %s" % (PORT, exc))
        sys.exit(2)
    return response


def ok(command: str, params: dict, timeout_s: float = 120.0) -> dict:
    response = send(command, params, timeout_s)
    if response.get("status") != "ok":
        print("FAIL: %s: %s" % (command, json.dumps(response.get("error"))[:500]))
        sys.exit(1)
    return response.get("result") or {}


def py(code: str, timeout_s: float = 120.0):
    """Runs `code`, which must assign `census`, and returns it."""
    res = ok("execute_python", {"code": textwrap.dedent(code).strip() + "\ncensus"},
             timeout_s)
    if res.get("traceback"):
        print("FAIL: execute_python raised:\n" + res["traceback"])
        sys.exit(1)
    return structured_result(res, "census")


def check(label: str, passed: bool, detail: str) -> None:
    print("%s %s: %s" % ("PASS" if passed else "FAIL", label, detail))
    if not passed:
        failures.append(label)


def main() -> None:
    if PORT == 9877 and os.environ.get("MAYA_MCP_ALLOW_USER_SESSION") != "1":
        print("refusing to run on 9877: this eval discards the open scene. "
              "Set MAYA_MCP_ALLOW_USER_SESSION=1 to override.")
        sys.exit(2)
    out_dir = tempfile.mkdtemp(prefix="mcp845_")
    try:
        # 1. a cube through uv_atlas
        ok("new_scene", {"confirm": True})
        ok("create_primitive", {"kind": "cube", "name": "cube845", "scale": [2, 1, 3]})
        atlas = ok("uv_atlas", {"names": ["|cube845"], "cols": 1, "rows": 1, "patch": 0,
                                "project": "box", "margin": 0.01})
        mesh = (atlas.get("meshes") or [{}])[0]
        census = mesh.get("face_census") or {}
        check("uv_atlas reports a face census",
              bool(census) and census.get("faces") == 6, json.dumps(census))
        check("no cube face spans the patch",
              census.get("faces_spanning_patch") == 0
              and (census.get("largest_face_fraction") or 1.0) < 0.5,
              json.dumps(census))
        check("no #845 warning on a good layout",
              not any("845" in w for w in atlas.get("warnings", [])),
              json.dumps(atlas.get("warnings")))
        measured = py(CENSUS % "|cube845")
        check("Maya's own UVs agree (largest face well under half the square)",
              measured["spanning"] == 0 and measured["largest"] < 0.5,
              json.dumps(measured))

        # 2. the old layout, made by hand: the bake must refuse, fast
        py("""
            import maya.cmds as cmds
            cmds.polyNormalizeUV("|cube845.map[*]", normalizeType=0,
                                 preserveAspectRatio=False, ch=False)
            census = 1
        """)
        stacked = py(CENSUS % "|cube845")
        check("normalizeType=0 really stacks every face (the measured trap)",
              stacked["spanning"] == 6, json.dumps(stacked))
        t0 = time.monotonic()
        refused = send("bake_mesh_maps", {"meshes": ["|cube845"], "out_dir": out_dir,
                                          "maps": ["ao"], "resolution": 256},
                       timeout_s=300)
        took = time.monotonic() - t0
        err = (refused.get("error") or {})
        check("bake_mesh_maps refuses a stacked layout naming #845",
              refused.get("status") != "ok" and "845" in (err.get("message") or ""),
              (err.get("message") or "no error")[:200])
        check("and refuses before baking (under 10 s)", took < 10.0, "%.1f s" % took)
        check("with the fix in its hint",
              "uv_atlas" in (err.get("hint") or ""), (err.get("hint") or "")[:160])

        # 3. the mesh that cost the kethran run an hour
        ok("open_scene", {"path": SCENE, "confirm": True}, timeout_s=300)
        atlas = ok("uv_atlas", {"names": [BODY], "cols": 1, "rows": 1, "patch": 0,
                                "project": "box", "margin": 0.01}, timeout_s=300)
        census = (atlas.get("meshes") or [{}])[0].get("face_census") or {}
        check("the kethran body's faces do not span the patch",
              census.get("faces") == 28862 and census.get("faces_spanning_patch") == 0,
              json.dumps(census))
        t0 = time.monotonic()
        baked = send("bake_mesh_maps", {"meshes": [BODY], "out_dir": out_dir,
                                        "maps": ["ao"], "resolution": 256},
                     timeout_s=600)
        took = time.monotonic() - t0
        check("a 256 AO bake of the body completes",
              baked.get("status") == "ok",
              json.dumps((baked.get("error") or {}).get("message"))[:200])
        check("in under %d s (was 16+ minutes)" % BAKE_BUDGET_S, took < BAKE_BUDGET_S,
              "%.1f s" % took)
    finally:
        send("new_scene", {"confirm": True})

    if failures:
        print("\n%d FAILED: %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("\nall checks passed")


if __name__ == "__main__":
    main()
