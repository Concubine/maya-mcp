"""Throwaway probe for redmine #836, part b: WHAT makes the kethran body bake
so slow? Part a measured a 256x256 AO bake of that mesh at well past ten
minutes, where #770 measured a 1024 AO bake of a 124.5k-tri assembly at 6.2 s.
So it is not resolution and not triangle count. The candidates, each isolated:

  S1  a polySphere of ~58k tris with its NATIVE UVs at 256 - is it the count?
  S2  the body with polyAutoProjection (non-overlapping shells) at 256 - is it
      the box projection's six overlapping projections?
  S3  the body with its construction history deleted, box UVs, at 256 - is
      it the history (loft + booleans + polySmooth re-evaluated)?
  S4  the body as-is at 128 - does resolution matter at all on this mesh?

Every step has its own budget: a step that exceeds it is recorded and the
series continues with the NEXT candidate on a fresh scene state (the answer
is the pattern across steps, not any one of them). The scene is re-opened
between body steps so S2/S3 do not contaminate each other.

Run:  MAYA_MCP_PORT=9878 MAYA_MCP_EXPECT_PID=<pid> .venv/Scripts/python.exe evals/bake_hang_probe_836b.py

OPENS evals/kethran_run/kethran.ma IN THE ANSWERING MAYA. Refuses 9877.
"""
from __future__ import annotations

import json
import os
import sys
import textwrap
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, _HERE)

from live_call import call, structured_result  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
if PORT == 9877:
    raise SystemExit("refusing 9877 - that is the user's Maya")
OUT = os.path.join(_HERE, "bake_hang_probe_836b")
os.makedirs(OUT, exist_ok=True)
MAPS_DIR = os.path.join(OUT, "maps")
os.makedirs(MAPS_DIR, exist_ok=True)
SCENE = os.path.join(_HERE, "kethran_run", "kethran.ma").replace("\\", "/")
BODY = "|kethran|body"
STEP_BUDGET_S = float(os.environ.get("PROBE_BUDGET_S", "420"))
FINDINGS: dict = {"port": PORT, "steps": []}


def save() -> None:
    with open(os.path.join(OUT, "findings.json"), "w", encoding="utf-8") as fh:
        json.dump(FINDINGS, fh, indent=1, default=str)


def probe(name: str, value) -> None:
    FINDINGS[name] = value
    save()
    print("PROBE %s: %r" % (name, value), flush=True)


def ok(command: str, params: dict, timeout_s: float = 300.0) -> dict:
    frame = call(command, params, timeout_s=timeout_s, port=PORT)
    if frame.get("status") != "ok":
        raise RuntimeError("%s failed: %s"
                           % (command, json.dumps(frame.get("error"), indent=1)))
    return frame.get("result") or {}


def py(code: str, timeout_s: float = 300.0):
    body = textwrap.dedent(code).strip() + "\nr"
    res = ok("execute_python", {"code": body}, timeout_s=timeout_s)
    if res.get("traceback"):
        raise RuntimeError("execute_python raised:\n" + res["traceback"])
    return structured_result(res, "r")


def clean_maps() -> None:
    for name in os.listdir(MAPS_DIR):
        try:
            os.unlink(os.path.join(MAPS_DIR, name))
        except OSError:
            pass


UV_REPORT = """
    import maya.cmds as cmds
    import maya.api.OpenMaya as om
    sel = om.MSelectionList(); sel.add(%r)
    fn = om.MFnMesh(sel.getDagPath(0))
    us, vs = fn.getUVs()
    counts, ids = fn.getAssignedUVs()
    # crude overlap census: rasterise UV face bboxes onto a 64x64 grid and
    # count texels claimed by more than one face
    import collections
    grid = collections.Counter()
    k = 0
    for c in counts:
        face = ids[k:k + c]; k += c
        if not face:
            continue
        xs = [us[i] for i in face]; ys = [vs[i] for i in face]
        x0, x1 = int(min(xs) * 64), int(max(xs) * 64)
        y0, y1 = int(min(ys) * 64), int(max(ys) * 64)
        for x in range(max(x0, 0), min(x1, 63) + 1):
            for y in range(max(y0, 0), min(y1, 63) + 1):
                grid[(x, y)] += 1
    claimed = len(grid)
    multi = sum(1 for v in grid.values() if v > 1)
    r = {"uv_count": len(us), "faces_with_uvs": sum(1 for c in counts if c),
         "u_range": [min(us) if us else None, max(us) if us else None],
         "v_range": [min(vs) if vs else None, max(vs) if vs else None],
         "grid_claimed": claimed, "grid_multi_claimed": multi,
         "mean_claims_per_texel": (sum(grid.values()) / float(claimed)) if claimed else 0,
         "history": cmds.listHistory(%r, pruneDagObjects=True) or []}
"""


def uv_report(mesh: str) -> dict:
    try:
        return py(UV_REPORT % (mesh, mesh))
    except Exception as exc:  # noqa: BLE001 - a census, not a gate
        return {"error": str(exc)[:300]}


def bake(label: str, mesh: str, resolution: int, budget_s: float) -> dict:
    clean_maps()
    params = {"meshes": [mesh], "out_dir": MAPS_DIR.replace("\\", "/"),
              "maps": ["ao"], "resolution": resolution, "apply_ao": False}
    print("\n>>> %s" % label, flush=True)
    t0 = time.monotonic()
    frame = call("bake_mesh_maps", params, timeout_s=budget_s, port=PORT)
    seconds = round(time.monotonic() - t0, 1)
    entry = {"label": label, "mesh": mesh, "resolution": resolution,
             "seconds": seconds, "status": frame.get("status"),
             "elapsed_ms": frame.get("elapsed_ms")}
    if frame.get("status") == "ok":
        result = frame.get("result") or {}
        entry["baked"] = [{"map": b.get("map"), "stats": b.get("stats")}
                          for b in result.get("baked", [])]
        entry["warnings"] = result.get("warnings")
    else:
        entry["error"] = frame.get("error")
    FINDINGS["steps"].append(entry)
    probe(label, "%ss %s" % (seconds, frame.get("status")))
    return entry


def wait_until_free(max_wait_s: float) -> bool:
    """A step that blew its budget leaves Maya busy; wait for it to finish
    before the next step, up to max_wait_s."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < max_wait_s:
        frame = call("ping", {}, timeout_s=10, port=PORT)
        if frame.get("status") == "ok":
            return True
        time.sleep(15)
    return False


# ------------------------------------------------------------- S1: count

ok("new_scene", {"confirm": True})
sphere = py("""
    import maya.cmds as cmds
    t = cmds.polySphere(name="probeSphere", radius=100, sx=240, sy=120)[0]
    r = {"transform": t, "tris": cmds.polyEvaluate(t, triangle=True)}
""")
probe("S1_sphere", sphere)
probe("S1_sphere_uvs", uv_report("|probeSphere"))
s1 = bake("S1_sphere_native_uv@256", "|probeSphere", 256, STEP_BUDGET_S)
if s1["status"] != "ok" and not wait_until_free(900):
    probe("aborted", "Maya still busy after S1")
    raise SystemExit(1)

# ---------------------------------------------- S2: non-overlapping UVs

ok("open_scene", {"path": SCENE, "confirm": True}, timeout_s=300)
probe("S2_body_uvs_as_saved", uv_report(BODY))
auto = py("""
    import maya.cmds as cmds
    cmds.polyAutoProjection(%r, layoutMethod=0, insertBeforeDeformers=True,
                            scaleMode=1, percentageSpace=0.2, planes=6)
    r = {"done": True}
""" % BODY)
probe("S2_body_uvs_auto", uv_report(BODY))
s2 = bake("S2_body_autoprojection@256", BODY, 256, STEP_BUDGET_S)
if s2["status"] != "ok" and not wait_until_free(900):
    probe("aborted", "Maya still busy after S2")
    raise SystemExit(1)

# ------------------------------------------------- S3: history deleted

ok("open_scene", {"path": SCENE, "confirm": True}, timeout_s=300)
hist = py("""
    import maya.cmds as cmds
    before = len(cmds.listHistory(%r, pruneDagObjects=True) or [])
    cmds.delete(%r, constructionHistory=True)
    after = len(cmds.listHistory(%r, pruneDagObjects=True) or [])
    r = {"history_before": before, "history_after": after}
""" % (BODY, BODY, BODY))
probe("S3_history", hist)
atlas = ok("uv_atlas", {"names": [BODY], "cols": 1, "rows": 1, "patch": 0,
                        "project": "box", "margin": 0.01}, timeout_s=300)
probe("S3_body_uvs_box_nohistory", uv_report(BODY))
s3 = bake("S3_body_box_nohistory@256", BODY, 256, STEP_BUDGET_S)
if s3["status"] != "ok" and not wait_until_free(900):
    probe("aborted", "Maya still busy after S3")
    raise SystemExit(1)

# ------------------------------------------------------ S4: resolution

ok("open_scene", {"path": SCENE, "confirm": True}, timeout_s=300)
ok("uv_atlas", {"names": [BODY], "cols": 1, "rows": 1, "patch": 0,
                "project": "box", "margin": 0.01}, timeout_s=300)
s4 = bake("S4_body_box_asis@128", BODY, 128, STEP_BUDGET_S)

print("\nfindings ->", os.path.join(OUT, "findings.json"), flush=True)
