"""M2.4 acceptance gate: arrays and the completed deformer set, in a real Maya.

Headless tests prove the arithmetic. They cannot prove Maya did what the
arithmetic says - #584 shipped a green suite while every isolated render came
back black. So this builds three things that were impossible before this
milestone, measures each one, and renders them.

The mirror gate additionally settles four assumptions a code review flagged
as things only a live Maya can verify (see the mirror_bbox assertion and the
signed_volume assertions below for which one covers which).

Exits non-zero on the first failure.

Run:  set MAYA_MCP_PORT=9878 && .venv/Scripts/python.exe evals/array_deform_live.py
Artifacts: evals/array_deform_live/*.png
"""

from __future__ import annotations

import base64
import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))
sys.path.insert(0, os.path.dirname(_HERE))

from live_call import call  # noqa: E402
from maya_mcp import images  # noqa: E402
from maya_plugin.handlers import arraymath  # noqa: E402

OUT_DIR = os.path.join(_HERE, "array_deform_live")
FAILURES = []


def ok(resp, what):
    if resp.get("status") != "ok":
        print("FAILED %s: %s" % (what, json.dumps(resp.get("error", resp))[:400]))
        sys.exit(1)
    return resp["result"]


def check(condition, message):
    print(("  PASS  " if condition else "  FAIL  ") + message)
    if not condition:
        FAILURES.append(message)


def scene_graph():
    """The scene graph, fetched once and indexed by name.

    centroid()/span() in the brief's draft each called get_scene_graph
    separately, so the gear check alone cost ~12 round trips. Callers fetch
    once per check and look up names in the returned dict instead.
    """
    result = ok(call("get_scene_graph", {"max_objects": 300}, 60.0), "scene graph")
    return {obj["name"]: obj for obj in result["objects"]}


def centroid_of(objs, name):
    obj = objs.get(name)
    if obj is None:
        raise SystemExit("object %s not in the scene graph" % name)
    lo, hi = obj["bbox_min"], obj["bbox_max"]
    return [(lo[i] + hi[i]) / 2.0 for i in range(3)]


def span_of(objs, name):
    obj = objs.get(name)
    if obj is None:
        raise SystemExit("object %s not in the scene graph" % name)
    lo, hi = obj["bbox_min"], obj["bbox_max"]
    return [hi[i] - lo[i] for i in range(3)]


_TIGHT_BBOX_CODE = """
import json
import maya.api.OpenMaya as om
sel = om.MSelectionList()
sel.add(%r)
dag = sel.getDagPath(0)
dag.extendToShape()
fn = om.MFnMesh(dag)
pts = fn.getPoints(om.MSpace.kWorld)
xs = [p.x for p in pts]
ys = [p.y for p in pts]
zs = [p.z for p in pts]
print(json.dumps({"lo": [min(xs), min(ys), min(zs)], "hi": [max(xs), max(ys), max(zs)]}))
"""


def tight_world_bbox(name):
    """The TIGHT per-vertex world bbox of a mesh, via OpenMaya.

    NOT the same thing as get_scene_graph's bbox_min/bbox_max. Measured live
    (see task-6-report.md): cmds.exactWorldBoundingBox - what get_scene_graph
    reports - is exact for an axis-aligned mesh but LOOSE for a rotated one,
    because it transforms the mesh's cached *local*-space bbox corners by the
    world matrix rather than transforming each vertex. For a triangular prism
    rotated off-axis (exactly this gate's mirror source) that loose box can be
    over half a unit bigger than the true vertex extent on some axes. The
    mirror bbox assertion needs the tight box, or it is comparing a loose
    rotated-AABB prediction against a loose rotated-AABB measurement that
    were never mathematically related to begin with.
    """
    result = ok(call("execute_python", {"code": _TIGHT_BBOX_CODE % name}, 60.0),
                "tight bbox %s" % name)
    data = json.loads(result["stdout"])
    return data["lo"], data["hi"]


def render(label, target, zoom=1.2):
    result = ok(call("render_scene", {
        "angles": ["three_quarter"], "renderer": "arnold", "resolution": 640,
        "samples": 3, "target": target, "zoom": zoom}, 900.0), "render %s" % label)
    os.makedirs(OUT_DIR, exist_ok=True)
    shot = result["images"][0]
    png = base64.b64decode(shot["png_b64"])
    with open(os.path.join(OUT_DIR, "%s.png" % label), "wb") as fh:
        fh.write(png)
    stats = images.pixel_stats(png)
    print("  %s %s" % (label, json.dumps(stats)))
    check(not stats["blank"], "%s rendered a non-blank frame" % label)
    return stats


def gate_gear():
    print("\n[1] radial: a gear from one tooth")
    ok(call("new_scene", {"confirm": True}, 180.0), "new_scene")
    ok(call("create_primitive", {
        "kind": "cube", "name": "tooth", "translate": [4.0, 0.5, 0.0],
        "scale": [1.2, 1.0, 0.8]}, 60.0), "tooth")
    ok(call("create_primitive", {
        "kind": "cylinder", "name": "hub", "translate": [0.0, 0.5, 0.0],
        "scale": [6.4, 0.9, 6.4]}, 60.0), "hub")
    result = ok(call("array", {
        "name": "|tooth", "mode": "radial", "count": 12, "axis": "y",
        "center": [0.0, 0.0, 0.0], "group_name": "gearTeeth"}, 180.0), "radial array")

    check(len(result["names"]) == 11, "11 copies for a 12-tooth gear (got %d)"
          % len(result["names"]))
    check(result["group"] is not None, "copies were grouped")
    check(result["signed_volume"] is None, "signed_volume not reported for radial")

    objs = scene_graph()
    centres = [centroid_of(objs, "|tooth")] + [centroid_of(objs, n) for n in result["names"]]
    radii = [math.hypot(c[0], c[2]) for c in centres]
    spread = max(radii) - min(radii)
    check(spread < 0.02, "all 12 teeth equidistant from the axis (spread %.4f)" % spread)

    angles = sorted((math.degrees(math.atan2(c[2], c[0])) % 360.0) for c in centres)
    gaps = [(angles[(i + 1) % 12] - angles[i]) % 360.0 for i in range(12)]
    check(max(gaps) - min(gaps) < 0.5,
          "teeth evenly spaced (gap range %.3f deg)" % (max(gaps) - min(gaps)))

    ok(call("setup_lighting", {"preset": "three_point", "intensity": 3.0,
                               "replace_existing": True}, 180.0), "lighting")
    render("gear", ["hub", "tooth"] + [n.split("|")[-1] for n in result["names"]])


def gate_spine():
    print("\n[2] linear + flare: a tapered ribbed spine")
    ok(call("new_scene", {"confirm": True}, 180.0), "new_scene")
    ok(call("create_primitive", {
        "kind": "cylinder", "name": "core", "translate": [0.0, 6.0, 0.0],
        "scale": [1.6, 12.0, 1.6], "divisions": 3}, 60.0), "core")
    ok(call("deform", {
        "mesh": "|core", "deformer": "flare",
        "params": {"startFlareX": 1.9, "startFlareZ": 1.9,
                   "endFlareX": 0.45, "endFlareZ": 0.45},
        "delete_history_after": True}, 180.0), "flare the core")

    info = ok(call("get_object_info", {"name": "|core"}, 60.0), "core info")
    check(info["mesh_stats"]["verts"] > 0, "core survived the flare")

    ok(call("create_primitive", {
        "kind": "cube", "name": "rib", "translate": [0.0, 11.0, 0.0],
        "scale": [3.4, 0.5, 1.2]}, 60.0), "rib")
    result = ok(call("array", {
        "name": "|rib", "mode": "linear", "count": 9,
        "offset": [0.0, -1.25, 0.0], "step_scale": [0.88, 1.0, 0.88],
        "group_name": "ribs"}, 180.0), "linear array")

    check(len(result["names"]) == 8, "8 copies for a 9-rib run (got %d)"
          % len(result["names"]))

    objs = scene_graph()
    widths = [span_of(objs, "|rib")[0]] + [span_of(objs, n)[0] for n in result["names"]]
    monotone = all(widths[i] > widths[i + 1] for i in range(len(widths) - 1))
    check(monotone, "rib widths decrease monotonically down the run: %s"
          % [round(w, 3) for w in widths])
    check(widths[-1] < widths[0] * 0.5,
          "the last rib is less than half the first (%.3f vs %.3f)"
          % (widths[-1], widths[0]))

    ok(call("setup_lighting", {"preset": "three_point", "intensity": 3.0,
                               "replace_existing": True}, 180.0), "lighting")
    render("spine", ["core", "rib"] + [n.split("|")[-1] for n in result["names"]])


def gate_mirror():
    print("\n[3] mirror: a rotated asymmetric chunk, off-origin pivot")
    ok(call("new_scene", {"confirm": True}, 180.0), "new_scene")
    # ROTATED on purpose. An unrotated source cannot tell the correct
    # implementation apart from the naive negate-the-object-scale one: they
    # agree exactly when the rotation commutes with the mirror.
    ok(call("create_primitive", {
        "kind": "prism", "name": "arm", "translate": [3.0, 4.0, 1.0],
        "rotate": [18.0, 34.0, 27.0], "scale": [2.0, 5.0, 1.4]}, 60.0), "arm")

    # OFF-ORIGIN pivot on purpose too (amendment to the brief's draft, which
    # used pivot=[0,0,0]): at the origin a wrong pivot is indistinguishable
    # from a right one, since resolve_vec3's default and an explicit
    # pivot=[0,0,0] produce identical geometry either way. This is the
    # single most valuable change to the draft's mirror gate.
    pivot = [2.5, 0.0, 0.0]

    # tight_world_bbox, NOT get_scene_graph's bbox_min/bbox_max: the source
    # is rotated, and get_scene_graph's bbox is measurably loose for a
    # rotated mesh (see tight_world_bbox's docstring). Confirmed live before
    # writing this: get_scene_graph reported max_x=4.977 / min_z=-0.838 for
    # this exact arm, while the true vertex extent is max_x=4.547 /
    # min_z=-0.286 - a 0.55-unit gap on one axis, which is exactly the size
    # of the spurious failure this produced on the first run of this gate.
    before_lo, before_hi = tight_world_bbox("|arm")

    result = ok(call("array", {
        "name": "|arm", "mode": "mirror", "axis": "x",
        "pivot": pivot, "name_prefix": "armMirror"}, 180.0), "mirror")

    check(len(result["names"]) == 1, "mirror made exactly one copy")
    check(result["group"] is None, "no leftover mirror group in the result")

    graph = ok(call("get_scene_graph", {"max_objects": 100}, 60.0), "graph")
    names = [o["name"] for o in graph["objects"]]
    check(not any("mirrorGrp" in n for n in names),
          "the temporary mirror group was deleted from the scene")

    copy = result["names"][0]
    if not any(o["name"] == copy for o in graph["objects"]):
        raise SystemExit("mirrored copy %s not found" % copy)
    got_lo, got_hi = tight_world_bbox(copy)

    # Assumption 1 (makeIdentity really bakes the reflection into the child's
    # geometry, not just the group transform) AND assumption 2 (the reflection
    # composes correctly with a rotated source, M*T*R*S rather than T*R*S*M)
    # are BOTH settled by this one assertion: the source is rotated, the
    # pivot is off-origin, and the prediction is a pure-math bbox with no
    # Maya involved. A wrong bake or a wrong composition order both show up
    # as a bbox that does not match arraymath.mirror_bbox's prediction.
    want_lo, want_hi = arraymath.mirror_bbox(before_lo, before_hi, "x", pivot)
    worst = max(
        max(abs(got_lo[i] - want_lo[i]) for i in range(3)),
        max(abs(got_hi[i] - want_hi[i]) for i in range(3)),
    )
    check(worst < 0.01,
          "mirrored bbox (off-origin pivot) matches the pure prediction "
          "(worst axis error %.5f)" % worst)

    check(result["signed_volume"] is not None,
          "signed_volume was measured on the mirrored copy")
    # Assumption 3 (MFnMesh.getTriangles()'s indices pair correctly with
    # getPoints(kWorld)) and assumption 4 (polyNormal(normalMode=0) really is
    # "reverse") are both settled by this assertion: a wrong triangle/point
    # pairing produces a near-random signed volume (as likely negative as
    # positive, and not reliably matching the pixel cross-check below); a
    # normalMode that doesn't reverse leaves the mirrored copy's inverted
    # winding uncorrected, which is negative by construction.
    check((result["signed_volume"] or 0.0) > 0.0,
          "mirrored copy has OUTWARD winding (signed_volume %s)"
          % result["signed_volume"])
    check(not result["warnings"], "mirror reported no warnings: %s" % result["warnings"])

    ok(call("setup_lighting", {"preset": "three_point", "intensity": 3.0,
                               "replace_existing": True}, 180.0), "lighting")
    stats = render("mirror", ["arm", copy.split("|")[-1]])
    # An inward-facing mesh renders black or hollow: with both halves lit and
    # only one of them inside out, the frame loses colour variety. This is the
    # pixel-side cross-check on the signed-volume number.
    check(stats["distinct_colors"] > 200,
          "the mirrored pair renders as lit solids (%d distinct colours)"
          % stats["distinct_colors"])


if __name__ == "__main__":
    gate_gear()
    gate_spine()
    gate_mirror()
    print("\n%d checks failed" % len(FAILURES))
    for failure in FAILURES:
        print("  - %s" % failure)
    sys.exit(1 if FAILURES else 0)
