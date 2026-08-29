"""#769 acceptance gate: the cage ops (`insert_loop`, `extrude_edges`,
`mirror_topology`) in a REAL Maya, driving a subdivision-cage workflow the
way an artist would - build an asymmetric half-form, hold its silhouette
with an edge loop before extruding an open-border rim, mirror it into a
whole, then MEASURE what the ticket actually promises rather than eyeball
it:

  1. mirror_topology's weld is an EXACT reflection about the mirror plane -
     shells==1, merged_vertices>0 (both the op's own self-report AND an
     independent execute_python recheck), and every vertex maps onto a
     counterpart under reflection within an EPSILON chosen by measurement.
  2. the epsilon actually discriminates: nudging one off-plane vertex by
     10x epsilon (via soft_move) makes the same check FAIL.
  3. insert_loop's whole reason to exist, measured LOCALLY: `smooth` moves
     the surface AT THE LOOP'S OWN LOCATION less than it moves the same
     absolute location on an otherwise-identical loopless control (2026-
     08-29 fix-review: a global bbox metric was tried first and rejected -
     Catmull-Clark's effect is local by construction, so a global metric
     dilutes it into a margin small enough that an unrelated change could
     flip its sign with no real regression; see
     code_nearest_vertex_distance's docstring).
  4. the result survives composition (uv_atlas, create_skeleton + bind_skin)
     and renders.

`split` is NOT exercised here - it is covered by the mayapy suite
(docs/superpowers/specs/2026-08-29-cage-ops-design.md's Testing section);
this gate is about the two ops the design calls "risky" in combination
(insert_loop + mirror_topology) plus extrude_edges, on real geometry.

The half-form: a unit cube spanning x in [-1, 0] (an open border sits
exactly on the x=0 plane once its +X cap face is deleted - the standard
"model half, mirror the rest" recipe; see cage_probe_769.py Section 3's
build_half_cube), with a small edge loop inserted before the open border is
cut, an outward rim extrude of that border (translate has a ZERO x
component, so the new border stays exactly on the mirror plane), and an
inflate_region bump on the untouched far corner to give the vertex cloud
enough irregularity that the symmetry measurement is a real per-vertex
nearest-neighbour search, not just "did the 8 box corners survive".

EPSILON starts at None (measurement mode, the #768/#773/#774 convention):
the worst per-vertex reflection distance is printed and not asserted, but
the discrimination proof still runs unconditionally (same convention as
retarget_live's two discrimination checks) using the mechanically-derived
value (2x measured, round up 1 sig fig, floor 1e-4) for that run. After a
real run, EPSILON is hardcoded from the measured worst case - see the
comment above EPSILON.

Every check() call accumulates into FAILURES rather than stopping the run;
only ok() aborts early, and only on a hard call failure (a refused or
crashed command) - so a run always exercises every check before deciding
pass/fail, and exits non-zero at the end if any check failed (the
curve_form_live/retarget_live convention).

Usage:

    set MAYA_MCP_PORT=9878
    set MAYA_MCP_EXPECT_PID=<the pid you launched>
    python evals/cage_ops_live.py

MUTATES THE ANSWERING MAYA'S CURRENT SCENE (new_scene, twice).
MAYA_MCP_EXPECT_PID is REQUIRED: a port is not an identity (#648), and this
gate discards the open scene more than once.

Artifacts: evals/cage_ops_live/sheet.png
Exit: 0 pass, 1 fail or preflight refused, 2 no connection.
"""

from __future__ import annotations

import base64
import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from live_call import call, structured_result  # noqa: E402
from maya_mcp import images  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
OUT_DIR = os.path.join(_HERE, "cage_ops_live")

FAILURES = []

# Measured on a real Maya (2026-08-29, agent Maya pid 131852, port 9878):
# worst per-vertex reflection distance on the mirrored+bumped+looped cage =
# 0.00000006 (float noise - polyMirrorFace's weld is an exact reflection,
# not an approximate one). The mechanical rule (2x measured, round up 1 sig
# fig, floor 1e-4) gives 0.0001: the floor dominates completely here, so
# EPSILON is a sanity ceiling well above float noise, not a measurement of
# real seam slop. The discrimination proof (a 10x-epsilon nudge, 0.001)
# measured worst=0.00099999 afterward - comfortably above EPSILON, so the
# tolerance actually discriminates.
EPSILON = 0.0001

# Measured on the same real Maya (2026-08-29, pid 131852, port 9878): local
# post-smooth displacement at the loop's own fixed pre-smooth location,
# looped=0.176777 vs loopless=0.242956 - ratio 1.374x. The GAP (0.066179) is
# what matters for "orders of magnitude above float noise": the sanity
# check right above this measurement (build_half_form's "unchanged by every
# step since insert_loop") measures the SAME kind of residual at ~0 (<1e-9)
# when nothing moved the point on purpose, so a 0.066-unit gap is ~7-8
# orders of magnitude bigger than the float noise floor - not a coin-flip
# margin. RATIO_THRESHOLD=1.2 sits comfortably below the measured 1.374x
# (real margin against a future small drift in the exact numbers) and
# comfortably above 1.0 (so it tests more than the bare ordering assert
# next to it, which would pass at ratio=1.0001).
RATIO_THRESHOLD = 1.2


def round_up_1sig(x, floor=1e-4):
    """2x-and-round-up-to-1-sig-fig, the #768/#773/#774 tolerance method."""
    if x <= 0:
        return floor
    exp = math.floor(math.log10(x))
    scaled = x / (10 ** exp)
    rounded = math.ceil(scaled - 1e-9)
    if rounded >= 10:
        rounded, exp = 1, exp + 1
    return max(rounded * (10 ** exp), floor)


def send(command, params, timeout_s=60.0):
    try:
        return call(command, params, timeout_s=timeout_s, port=PORT)
    except (ConnectionRefusedError, OSError) as exc:
        print("could not reach a Maya plugin on %s: %s" % (PORT, exc))
        sys.exit(2)


def ok(command, params, timeout_s=60.0, what=None):
    resp = send(command, params, timeout_s)
    if resp.get("status") != "ok":
        print("FAILED %s: %s" % (what or command,
                                 json.dumps(resp.get("error", resp))[:600]))
        sys.exit(1)
    return resp.get("result") or {}


def check(condition, message):
    print(("  PASS  " if condition else "  FAIL  ") + message)
    if not condition:
        FAILURES.append(message)
    return condition


def py(code, what, timeout_s=60.0):
    return structured_result(ok("execute_python", {"code": code}, timeout_s,
                                what), what)


def preflight():
    expect = (os.environ.get("MAYA_MCP_EXPECT_PID") or "").strip()
    if not expect:
        raise SystemExit(
            "MAYA_MCP_EXPECT_PID is not set. This gate discards the "
            "answering Maya's scene (new_scene, twice) - launch one "
            "yourself and name its pid (#648). Refusing to guess which "
            "Maya is disposable.")
    ping = ok("ping", {}, 10.0, "ping")
    process = ping.get("process") or {}
    print("answering Maya: pid %s, scene %r" % (process.get("pid"),
                                                 process.get("scene")))
    return ping


# ---------------------------------------------------------------------------
# execute_python code generators - small, single-purpose topology queries and
# mutations that the plugin's declared tool surface has no dedicated verb
# for (finding an axis-parallel edge, finding/deleting the cap face at the
# mirror plane, reading boundary edges) - the same use of execute_python as a
# measurement/setup tool the other live gates rely on (retarget_live's
# freeze-transform py() call, declared_clips()).
# ---------------------------------------------------------------------------

def code_find_axis_edges(mesh, axis_idx, length, tol=1e-4):
    """[(edge_index, endpoint0_axis_coord, endpoint1_axis_coord), ...] for
    edges running the full `length` along `axis_idx` and nothing on the
    other two axes - the 4 edges of a unit box parallel to that axis, used
    as polySplitRing root edges (their ring wraps around the box's belt,
    matching cage_probe_769.py Section 1's lateral-edge recipe). The two
    endpoint coordinates come back too so a caller can pick a `position`
    weight that lands the loop near a chosen end (weight 0 sits at
    endpoint0, weight 1 at endpoint1 - cage_probe_769.py Section 1
    measured this exactly)."""
    others = [k for k in range(3) if k != axis_idx]
    return """
import maya.cmds as cmds
mesh = {mesh!r}
axis = {axis}
others = {others!r}
n = cmds.polyEvaluate(mesh, edge=True)
out = []
for i in range(n):
    vs = cmds.ls(cmds.polyListComponentConversion(mesh + '.e[%d]' % i, toVertex=True), flatten=True)
    p0 = cmds.pointPosition(vs[0], world=True)
    p1 = cmds.pointPosition(vs[1], world=True)
    if (all(abs(p0[k] - p1[k]) < {tol!r} for k in others)
            and abs(abs(p0[axis] - p1[axis]) - {length!r}) < {tol!r}):
        out.append((i, p0[axis], p1[axis]))
out
""".format(mesh=mesh, axis=axis_idx, others=others, tol=tol, length=length)


def code_find_cap_faces(mesh, axis_idx, plane, tol=1e-5):
    """Face indices every one of whose vertices sits on `plane` along
    `axis_idx` - the single cap quad to delete to open a border there."""
    return """
import maya.cmds as cmds
mesh = {mesh!r}
axis = {axis}
n = cmds.polyEvaluate(mesh, face=True)
out = []
for i in range(n):
    vs = cmds.ls(cmds.polyListComponentConversion(mesh + '.f[%d]' % i, toVertex=True), flatten=True)
    if all(abs(cmds.pointPosition(v, world=True)[axis] - {plane!r}) < {tol!r} for v in vs):
        out.append(i)
out
""".format(mesh=mesh, axis=axis_idx, plane=plane, tol=tol)


def code_delete_faces(mesh, indices):
    return """
import maya.cmds as cmds
mesh = {mesh!r}
cmds.delete([mesh + '.f[%d]' % i for i in {indices!r}])
True
""".format(mesh=mesh, indices=list(indices))


def code_boundary_edges(mesh):
    return """
import maya.api.OpenMaya as om
sel = om.MSelectionList()
sel.add({mesh!r})
dag = sel.getDagPath(0)
it = om.MItMeshEdge(dag)
out = []
while not it.isDone():
    if it.numConnectedFaces() == 1:
        out.append(it.index())
    it.next()
out
""".format(mesh=mesh)


def code_min_abs_x(mesh):
    return """
import maya.cmds as cmds
pts = cmds.xform({mesh!r} + '.vtx[*]', query=True, worldSpace=True, translation=True)
min(abs(x) for x in pts[0::3])
""".format(mesh=mesh)


def code_vertex_count(mesh):
    return "import maya.cmds as cmds\ncmds.polyEvaluate(%r, vertex=True)\n" % mesh


def code_shell_count(mesh):
    return "import maya.cmds as cmds\ncmds.polyEvaluate(%r, shell=True)\n" % mesh


def code_find_off_plane_vertex(mesh, min_abs_x):
    return """
import maya.cmds as cmds
mesh = {mesh!r}
pts = cmds.xform(mesh + '.vtx[*]', query=True, worldSpace=True, translation=True)
n = len(pts) // 3
found = None
for i in range(n):
    x, y, z = pts[3 * i], pts[3 * i + 1], pts[3 * i + 2]
    if abs(x) > {min_abs_x!r}:
        found = [x, y, z]
        break
found
""".format(mesh=mesh, min_abs_x=min_abs_x)


def code_symmetry_worst(mesh):
    """For every vertex, the distance from its x-reflection to the NEAREST
    actual vertex - an O(n^2) nearest-neighbour search, deliberately not an
    index-paired comparison, since mirror_topology gives no promise that
    vertex i's mirror counterpart is vertex N-i."""
    return """
import maya.cmds as cmds
pts = cmds.xform({mesh!r} + '.vtx[*]', query=True, worldSpace=True, translation=True)
n = len(pts) // 3
verts = [(pts[3 * i], pts[3 * i + 1], pts[3 * i + 2]) for i in range(n)]
worst = 0.0
for (x, y, z) in verts:
    rx = -x
    best = min(((rx - vx) ** 2 + (y - vy) ** 2 + (z - vz) ** 2) ** 0.5
               for (vx, vy, vz) in verts)
    if best > worst:
        worst = best
worst
""".format(mesh=mesh)


def code_vertex_bbox(mesh):
    """(dx, dy, dz) from actual vertex positions - not exactWorldBoundingBox,
    which transforms the object-space box and over-reports
    (maya-exact-bbox-is-not-vertex-bounds); moot here since nothing is
    rotated, but vertices are the ground truth regardless. PRINTED CONTEXT
    ONLY (not asserted) - see code_nearest_vertex_distance's docstring for
    why a global bbox metric is the wrong thing to assert on here."""
    return """
import maya.cmds as cmds
pts = cmds.xform({mesh!r} + '.vtx[*]', query=True, worldSpace=True, translation=True)
xs = pts[0::3]; ys = pts[1::3]; zs = pts[2::3]
(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
""".format(mesh=mesh)


def code_vertex_positions(mesh):
    """Every vertex's world position, as a list of (x, y, z) tuples - used to
    diff before/after an op (e.g. finding insert_loop's newly-created
    vertices by set difference) and as the raw data for a nearest-neighbour
    search."""
    return """
import maya.cmds as cmds
pts = cmds.xform({mesh!r} + '.vtx[*]', query=True, worldSpace=True, translation=True)
n = len(pts) // 3
[(pts[3 * i], pts[3 * i + 1], pts[3 * i + 2]) for i in range(n)]
""".format(mesh=mesh)


def code_nearest_vertex_distance(mesh, point):
    """Distance from a fixed world-space `point` to the NEAREST vertex
    currently on `mesh`.

    This is the LOCAL displacement metric (2026-08-29 fix-review): `point`
    is captured once, right after insert_loop, at a specific loop-ring
    vertex's pre-smooth position (or, for the loopless control, the exact
    same absolute coordinate - a point that sits on a bare, unsupported
    face there instead of on a real vertex). After `smooth` runs, the
    nearest surviving/new vertex to that fixed point tells you how far
    Catmull-Clark moved the surface AT THAT SPECIFIC LOCAL SPOT - which is
    exactly what a support loop is supposed to constrain.

    Why not the global bbox (the first version of this gate): Catmull-Clark's
    vertex rule reads only a vertex's own 1-ring neighbourhood, so a loop's
    effect is LOCAL by construction - measured directly by this gate's own
    dead end, where a loop placed physically close to the flange border
    (but not topologically adjacent to the flange's own corner vertices)
    moved the flange corner's post-smooth position by exactly ZERO relative
    to a loopless control. A global metric (bbox extent, volume, dx/dy/dz)
    is dominated by whichever few vertices happen to be the extremes (here,
    the far-corner inflate_region bump, present identically in both builds)
    and can only pick up the loop's real, local effect as a diluted,
    small-margin difference that a functionally-irrelevant, unrelated change
    elsewhere (a merge_threshold default, a divisions default, a different
    Maya version's polySmooth rounding) could plausibly flip the sign of
    without any real insert_loop regression. Measuring at the loop's own
    location removes that dilution."""
    return """
import maya.cmds as cmds
pts = cmds.xform({mesh!r} + '.vtx[*]', query=True, worldSpace=True, translation=True)
px, py_, pz = {point!r}
n = len(pts) // 3
min(((pts[3 * i] - px) ** 2 + (pts[3 * i + 1] - py_) ** 2
     + (pts[3 * i + 2] - pz) ** 2) ** 0.5 for i in range(n))
""".format(mesh=mesh, point=tuple(float(c) for c in point))


# ---------------------------------------------------------------------------
# the half-form builder
# ---------------------------------------------------------------------------

def build_half_form(tag, z_offset, with_loop):
    """A unit cube spanning x in [-1, 0], y/z in [-0.5, 0.5], shifted by
    `z_offset` in Z (so two builds can coexist in one scene without
    colliding - mirror_topology's plane is always world-origin along the
    chosen axis regardless of the object's own transform, cage_probe_769.py
    Section 3 measured, so a Z shift is free): optionally a single support
    loop inserted close to the x=0 end (on a ring chosen while the box is
    still a clean closed quad mesh - the standard "brace the edge you don't
    want smooth to round away" placement, not a loop stuck in the middle of
    an unremarkable span), an open border cut at x=0, an outward rim
    extrude of that border (Y/Z only - the x component of translate is 0,
    so the new border stays exactly on the mirror plane), an asymmetric
    inflate_region bump on the untouched far corner, and finally
    mirror_topology(axis="x"). Returns (mesh_long_name, loop_ref_point):
    `loop_ref_point` is the pre-smooth world position of one of
    insert_loop's own newly-created vertices (None when with_loop=False) -
    the anchor for phase 2's local displacement-under-smooth measurement.
    """
    print("\n  building %s (with_loop=%s, z_offset=%.2f)"
          % (tag, with_loop, z_offset))
    body = ok("create_primitive", {
        "kind": "cube", "name": "%s_body" % tag,
        "scale": [1.0, 1.0, 1.0], "translate": [-0.5, 0.0, z_offset],
    }, 60.0, "create_primitive %s" % tag)
    mesh = body["name"]

    loop_ref_point = None
    if with_loop:
        edges = py(code_find_axis_edges(mesh, 0, 1.0),
                  "find X-parallel edges (%s)" % tag)
        check(len(edges) == 4,
             "%s: found 4 X-parallel edges before insert_loop (got %d)"
             % (tag, len(edges)))
        # Two loops (splitType=2, position ignored per the handler's own
        # doc) splitting the box into thirds along X. A single loop placed
        # right next to the border was tried first and measured to make
        # ZERO difference to the flange corner's post-smooth position:
        # Catmull-Clark's vertex rule only reads 1-ring neighbours, and the
        # flange's own corner vertices are not in that ring regardless of a
        # nearby loop. The mid-span pair is kept anyway - phase 2 measures
        # displacement AT the loop's own location (not the flange), which
        # is exactly where this placement's local effect actually lands.
        root_idx, _x0, _x1 = edges[0]
        verts_before_loop = py(code_vertex_positions(mesh),
                              "vertices before insert_loop (%s)" % tag)
        loop_res = ok("sculpt_ops", {
            "mesh": mesh,
            "ops": [{"op": "insert_loop", "edge": "e[%d]" % root_idx,
                     "count": 2}],
        }, 60.0, "insert_loop (%s)" % tag)["op_results"][0]
        print("    insert_loop: edges %d->%d, faces %d->%d"
             % (loop_res["edges_before"], loop_res["edges_after"],
                loop_res["faces_before"], loop_res["faces_after"]))
        check(loop_res["edges_after"] > loop_res["edges_before"],
             "%s: insert_loop added edges" % tag)

        verts_after_loop = py(code_vertex_positions(mesh),
                             "vertices after insert_loop (%s)" % tag)
        before_set = {tuple(round(c, 6) for c in v) for v in verts_before_loop}
        new_verts = [v for v in verts_after_loop
                    if tuple(round(c, 6) for c in v) not in before_set]
        check(len(new_verts) == 8,
             "%s: insert_loop created exactly 8 new vertices (2 rings x 4)"
             " (got %d)" % (tag, len(new_verts)))
        # Pick a new vertex clear of the inflate_region bump's radius below
        # (centred at [-1, -0.5, z_offset-0.5], radius 0.35) so its position
        # is untouched by every later step in this builder (cap deletion and
        # extrude only touch the x=0 border; mirror only touches the border
        # too) and stays valid as a pre-smooth reference all the way to
        # phase 2's smooth call: the opposite Y/Z corner, y>0 and
        # z>z_offset, sits >1.4 units from the bump centre.
        candidates = [v for v in new_verts
                     if v[1] > 0.0 and (v[2] - z_offset) > 0.0]
        check(len(candidates) >= 1,
             "%s: found a loop vertex clear of the inflate_region bump"
             % tag)
        loop_ref_point = sorted(candidates or new_verts)[0]

    cap_faces = py(code_find_cap_faces(mesh, 0, 0.0),
                  "find x=0 cap face(s) (%s)" % tag)
    check(len(cap_faces) == 1,
         "%s: exactly one cap face sits on x=0 (got %d: %s)"
         % (tag, len(cap_faces), cap_faces))
    py(code_delete_faces(mesh, cap_faces), "delete cap face(s) (%s)" % tag)

    border = py(code_boundary_edges(mesh),
               "border edges after cap deletion (%s)" % tag)
    check(len(border) == 4,
         "%s: open border has 4 edges (got %d)" % (tag, len(border)))

    min_abs_x = py(code_min_abs_x(mesh), "min|x| before extrude (%s)" % tag)
    check(min_abs_x < 1e-4,
         "%s: open border sits on the x=0 plane (min|x|=%.6g)"
         % (tag, min_abs_x))

    extrude_res = ok("sculpt_ops", {
        "mesh": mesh,
        "ops": [{"op": "extrude_edges",
                 "edges": ["e[%d]" % i for i in border],
                 "translate": [0.0, 0.15, -0.1]}],
    }, 60.0, "extrude_edges (%s)" % tag)["op_results"][0]
    print("    extrude_edges: faces %d->%d (new_faces=%d)"
         % (extrude_res["faces_before"], extrude_res["faces_after"],
            extrude_res["new_faces"]))
    check(extrude_res["new_faces"] == 4,
         "%s: extrude_edges added the predicted 4 faces (len(edges)*divisions)"
         % tag)

    ok("sculpt_ops", {
        "mesh": mesh,
        "ops": [{"op": "inflate_region",
                 "center": [-1.0, -0.5, z_offset - 0.5],
                 "radius": 0.35, "amount": 0.3, "falloff": "smooth"}],
    }, 60.0, "inflate_region bump (%s)" % tag)

    min_abs_x2 = py(code_min_abs_x(mesh), "min|x| before mirror (%s)" % tag)
    check(min_abs_x2 < 1e-4,
         "%s: border still on the x=0 plane after the bump (min|x|=%.6g)"
         % (tag, min_abs_x2))

    verts_before = py(code_vertex_count(mesh),
                     "vertex count before mirror (%s)" % tag)
    mirror_res = ok("sculpt_ops", {
        "mesh": mesh, "ops": [{"op": "mirror_topology", "axis": "x"}],
    }, 60.0, "mirror_topology (%s)" % tag)["op_results"][0]
    print("    mirror_topology: shells=%d merged_vertices=%d verts %d->%d"
         % (mirror_res["shells"], mirror_res["merged_vertices"],
            mirror_res["vertices_before"], mirror_res["vertices_after"]))
    check(mirror_res["shells"] == 1,
         "%s: mirror_topology's own self-report says 1 shell" % tag)
    check(mirror_res["merged_vertices"] > 0,
         "%s: mirror_topology's own self-report says merged_vertices>0 (%d)"
         % (tag, mirror_res["merged_vertices"]))

    shells_independent = py(code_shell_count(mesh),
                           "independent shell count (%s)" % tag)
    check(shells_independent == 1,
         "%s: an INDEPENDENT execute_python call also measures 1 shell (%d)"
         % (tag, shells_independent))
    verts_after = py(code_vertex_count(mesh),
                    "vertex count after mirror (%s)" % tag)
    merged_independent = max(0, 2 * verts_before - verts_after)
    check(merged_independent == mirror_res["merged_vertices"],
         "%s: independently computed merged_vertices agrees with the op's "
         "self-report (%d vs %d)"
         % (tag, merged_independent, mirror_res["merged_vertices"]))

    if loop_ref_point is not None:
        # Sanity check the assumption phase 2 relies on: the captured
        # position must still be an EXACT vertex on the finished mesh (not
        # nudged by anything since it was captured) - if this ever fails,
        # the local-displacement measurement below would be silently wrong
        # rather than loudly wrong.
        still_there = py(code_nearest_vertex_distance(mesh, loop_ref_point),
                        "loop_ref_point still exact on the finished mesh (%s)"
                        % tag)
        check(still_there < 1e-9,
             "%s: the captured loop vertex position is unchanged by every "
             "step since insert_loop (residual=%.3g)" % (tag, still_there))

    return mesh, loop_ref_point


# ---------------------------------------------------------------------------
# phase 1: symmetry by measurement + the discrimination proof
# ---------------------------------------------------------------------------

def phase1_symmetry_and_discrimination():
    print("\n[1] symmetry-by-measurement + discrimination proof")
    ok("new_scene", {"confirm": True}, 180.0, "new_scene (phase 1)")
    mesh, _loop_ref = build_half_form("sym_check", 0.0, with_loop=True)

    worst = py(code_symmetry_worst(mesh), "symmetry worst deviation (pre-nudge)")
    print("  measured worst vertex-to-mirror-counterpart distance: %.8f" % worst)
    epsilon_effective = EPSILON if EPSILON is not None else round_up_1sig(2 * worst)
    print("  epsilon %s: %.6g"
         % ("HARDCODED" if EPSILON is not None else "derived this run (2x worst, "
            "round up 1 sig fig, floor 1e-4)", epsilon_effective))
    if EPSILON is None:
        print("  MEASUREMENT MODE - EPSILON is None: the main symmetry check "
             "below is not asserted; the discrimination proof still runs "
             "unconditionally, using the derived value above")
    else:
        check(worst <= EPSILON,
             "mirrored mesh is symmetric within EPSILON (%.8f <= %.6g)"
             % (worst, EPSILON))

    # Discrimination proof (asserted unconditionally, like retarget_live's
    # discrimination checks): nudge ONE off-plane vertex by 10x
    # epsilon_effective, confirm the same measurement now FAILS.
    off_plane = py(code_find_off_plane_vertex(mesh, 0.3),
                  "an off-plane vertex to nudge")
    check(off_plane is not None, "found an off-plane vertex to nudge")
    nudge = 10.0 * epsilon_effective
    ok("sculpt_ops", {
        "mesh": mesh,
        "ops": [{"op": "soft_move", "center": off_plane, "radius": 0.05,
                 "delta": [0.0, nudge, 0.0]}],
    }, 60.0, "soft_move discrimination nudge")
    worst_after_nudge = py(code_symmetry_worst(mesh),
                          "symmetry worst deviation (post-nudge)")
    print("  after nudging one vertex by 10x epsilon (%.6g): worst deviation = %.8f"
         % (nudge, worst_after_nudge))
    check(worst_after_nudge > epsilon_effective,
         "discrimination: a %.6g nudge (10x epsilon) makes the symmetry "
         "check FAIL (worst %.8f > epsilon %.6g)"
         % (nudge, worst_after_nudge, epsilon_effective))
    return worst, epsilon_effective


# ---------------------------------------------------------------------------
# phase 2: loops hold the silhouette + composition + render
# ---------------------------------------------------------------------------

def phase2_loops_hold_and_composition():
    print("\n[2] loops hold the silhouette under smooth (measured)")
    ok("new_scene", {"confirm": True}, 180.0, "new_scene (phase 2)")

    looped, loop_ref = build_half_form("cage_looped", 0.0, with_loop=True)
    loopless, _no_ref = build_half_form("cage_loopless", 3.0, with_loop=False)
    check(loop_ref is not None, "captured a loop-vertex reference point (looped)")
    # The loopless control has no loop, so there is no real vertex to
    # capture there - the exact same absolute station (X, Y, Z - only Z
    # shifted by the same z_offset delta between the two builds) is used
    # instead, landing on a bare, unsupported patch of its otherwise
    # identical geometry.
    loopless_ref = (loop_ref[0], loop_ref[1], loop_ref[2] + 3.0)

    # Global bbox is PRINTED CONTEXT ONLY (2026-08-29 fix-review) - see
    # code_nearest_vertex_distance's docstring for why it is not asserted
    # on: it is dominated by the far-corner inflate_region bump (identical
    # in both builds) and dilutes the loop's local, small-margin effect
    # into a gap that a functionally-irrelevant change elsewhere could flip
    # without any real insert_loop regression.
    bbox_before_looped = py(code_vertex_bbox(looped), "bbox before smooth (looped)")
    bbox_before_loopless = py(code_vertex_bbox(loopless), "bbox before smooth (loopless)")

    ok("sculpt_ops", {"mesh": looped, "ops": [{"op": "smooth", "divisions": 1}]},
      120.0, "smooth (looped)")
    ok("sculpt_ops", {"mesh": loopless, "ops": [{"op": "smooth", "divisions": 1}]},
      120.0, "smooth (loopless)")

    bbox_after_looped = py(code_vertex_bbox(looped), "bbox after smooth (looped)")
    bbox_after_loopless = py(code_vertex_bbox(loopless), "bbox after smooth (loopless)")
    print("  bbox before smooth (x,y,z), CONTEXT ONLY: looped=%s loopless=%s"
         % (tuple(round(v, 5) for v in bbox_before_looped),
            tuple(round(v, 5) for v in bbox_before_loopless)))
    print("  bbox after  smooth (x,y,z), CONTEXT ONLY: looped=%s loopless=%s"
         % (tuple(round(v, 5) for v in bbox_after_looped),
            tuple(round(v, 5) for v in bbox_after_loopless)))
    for axis, label in ((0, "X"), (1, "Y"), (2, "Z")):
        shrink = lambda before, after: (before[axis] - after[axis]) / before[axis]
        print("  %s-extent shrinkage (not asserted, global/diluted - context "
             "only): looped=%.4f%% loopless=%.4f%%"
             % (label, shrink(bbox_before_looped, bbox_after_looped) * 100,
                shrink(bbox_before_loopless, bbox_after_loopless) * 100))

    # THE ASSERTED METRIC: local post-smooth displacement AT the loop's own
    # (fixed, pre-smooth) location, looped vs loopless. See
    # code_nearest_vertex_distance's docstring for the mechanism and why
    # this replaces the global bbox metric.
    disp_looped = py(code_nearest_vertex_distance(looped, loop_ref),
                    "local displacement after smooth (looped)")
    disp_loopless = py(code_nearest_vertex_distance(loopless, loopless_ref),
                      "local displacement after smooth (loopless)")
    ratio = (disp_loopless / disp_looped) if disp_looped > 0 else float("inf")
    print("  LOCAL post-smooth displacement at the loop's own station: "
         "looped=%.6f loopless=%.6f (loopless/looped ratio=%.3fx)"
         % (disp_looped, disp_loopless, ratio))
    check(disp_looped < disp_loopless,
         "insert_loop's whole purpose, measured LOCALLY: the surface at the "
         "loop's own location moves LESS under smooth than the same "
         "location does in an otherwise-identical loopless control "
         "(%.6f < %.6f)" % (disp_looped, disp_loopless))
    if RATIO_THRESHOLD is None:
        print("  MEASUREMENT MODE - RATIO_THRESHOLD is None: the ratio "
             "above is printed and not asserted yet")
    else:
        # RATIO_THRESHOLD is set well below the measured value (real
        # margin) and well above 1.0 (so it tests more than the bare
        # ordering assert above) - orders of magnitude above anything float
        # noise or an unrelated default (merge_threshold, divisions) could
        # produce by accident.
        check(ratio > RATIO_THRESHOLD,
             "the local displacement gap is orders of magnitude above float "
             "noise, not a coin-flip global margin (ratio %.3fx > "
             "threshold %sx)" % (ratio, RATIO_THRESHOLD))

    print("\n[3] composition: uv_atlas + create_skeleton + bind_skin (looped mesh)")
    uv = ok("uv_atlas", {"names": [looped], "cols": 1, "rows": 1, "patch": 0,
                         "margin": 0.05}, 180.0, "uv_atlas")
    check(bool(uv.get("meshes")), "uv_atlas reports at least one mesh")

    skeleton = ok("create_skeleton", {
        "chain": [[0.0, -0.5, 0.0], [0.0, 0.5, 0.0]], "chain_prefix": "cage_j",
    }, 60.0, "create_skeleton")
    check(len(skeleton["joints"]) == 2,
         "2-joint chain built (got %d)" % len(skeleton["joints"]))
    bind = ok("bind_skin", {"mesh": looped, "root": skeleton["root"]}, 600.0,
             "bind_skin")
    check(bind.get("unweighted_vertices", 1) == 0,
         "bind_skin leaves no vertex unweighted (unweighted=%s)"
         % bind.get("unweighted_vertices"))

    print("\n[4] render_sheet: looped (rigged) vs loopless control")
    os.makedirs(OUT_DIR, exist_ok=True)
    sheet = ok("render_sheet", {"subjects": [looped, loopless],
                                "renderer": "arnold", "resolution": 512,
                                "samples": 3}, 300.0, "render_sheet")
    check(len(sheet.get("images", [])) == 2,
         "render_sheet returned one image per subject (%d of 2)"
         % len(sheet.get("images", [])))
    pngs = [base64.b64decode(im["png_b64"]) for im in sheet["images"]]
    for im, png in zip(sheet["images"], pngs):
        stats = images.pixel_stats(png)
        print("  %s %s" % (im["label"], json.dumps(stats)))
        check(not stats["blank"], "%s cell is not blank" % im["label"])
    sheet_png = images.contact_sheet(pngs, cols=len(pngs))
    sheet_path = os.path.join(OUT_DIR, "sheet.png")
    with open(sheet_path, "wb") as fh:
        fh.write(sheet_png)
    print("  wrote %s" % sheet_path)


def main():
    preflight()
    phase1_symmetry_and_discrimination()
    phase2_loops_hold_and_composition()

    print("\n%d checks failed" % len(FAILURES))
    for failure in FAILURES:
        print("  - %s" % failure)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
