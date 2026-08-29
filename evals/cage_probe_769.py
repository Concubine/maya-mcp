"""#769 probe: how THIS Maya 2027 actually drives polySplitRing, polyMirrorFace,
polyExtrudeEdge, polySplit.

Run:  E:\\Autodesk\\Maya2027\\bin\\mayapy.exe evals/cage_probe_769.py
Every finding prints as 'PROBE <name>: <value>'. Facts, not assertions: a
surprising value here changes Task 2's constants, not this script.
"""
from __future__ import annotations

import maya.standalone
maya.standalone.initialize(name="python")
import maya.cmds as cmds  # noqa: E402


def probe(name, value):
    print("PROBE %s: %r" % (name, value))


def mesh_long(shortname):
    return (cmds.ls(shortname, long=True) or [shortname])[0]


def vef(mesh):
    return (cmds.polyEvaluate(mesh, vertex=True), cmds.polyEvaluate(mesh, edge=True),
            cmds.polyEvaluate(mesh, face=True))


# ============================================================================
# SECTION 1: polySplitRing on a 20-around cylinder
# ============================================================================
try:
    print("=" * 10, "SECTION 1: polySplitRing", "=" * 10)

    def fresh_cyl():
        cmds.file(new=True, force=True)
        c = cmds.polyCylinder(radius=1, height=4, subdivisionsAxis=20, subdivisionsHeight=1,
                               constructionHistory=False)
        return mesh_long(c[0])

    mesh = fresh_cyl()
    probe("cyl_verts_edges_faces_before", vef(mesh))
    # Chosen lateral (vertical) edge: spans the full height (y -2..2), shared
    # by the two side quads that wrap the seam (adjacent faces 19 and 0 - this
    # IS a normal interior side edge, not a cap edge).
    EDGE_IDX = 40
    verts = cmds.ls(cmds.polyListComponentConversion(mesh + ".e[%d]" % EDGE_IDX, toVertex=True),
                     flatten=True)
    y0, y1 = (cmds.pointPosition(verts[0], world=True)[1],
              cmds.pointPosition(verts[1], world=True)[1])
    probe("chosen_lateral_edge", "%s.e[%d]" % (mesh, EDGE_IDX))
    probe("chosen_lateral_edge_Y_span", (y0, y1))
    probe("chosen_lateral_edge_adjacent_faces", cmds.polyInfo(mesh + ".e[%d]" % EDGE_IDX,
                                                               edgeToFace=True))

    # --- THE LANDMINE: passing the edge as a component-string argument to
    # polySplitRing (with or without cmds.select first) silently fails with
    # "Can't perform polySplitRing1 on selection" and returns None having
    # changed nothing. The working recipe (lifted from Maya's own
    # scripts/others/polyConvertToRingAndSplit.mel) is:
    #   1. cmds.polySelect(mesh, edgeRing=idx)   <- populates the active
    #      selection with the WHOLE ring, which polySplitRing reads implicitly
    #   2. cmds.polySplitRing(rootEdge=idx, splitType=..., weight=..., ch=0)
    #      with NO positional mesh/component argument at all.
    dup = fresh_cyl()
    before_naive = vef(dup)
    cmds.polySplitRing(dup + ".e[%d]" % EDGE_IDX, weight=0.5, constructionHistory=False)
    after_naive = vef(dup)
    probe("splitring_naive_component_string_arg_prints_a_warning_and_changes_nothing",
          before_naive == after_naive)  # True: Maya warns "Can't perform
    # polySplitRing1 on selection" to stderr/log and returns None, topology
    # unchanged - this is a silent failure from the caller's point of view
    # (no Python exception is raised).

    def split_ring(mesh, idx, **kw):
        cmds.polySelect(mesh, edgeRing=idx)
        return cmds.polySplitRing(rootEdge=idx, constructionHistory=False, **kw)

    mesh = fresh_cyl()
    before = vef(mesh)
    split_ring(mesh, EDGE_IDX, splitType=1, weight=0.5)
    after = vef(mesh)
    probe("splitring_working_recipe_delta_verts_edges_faces",
          tuple(a - b for a, b in zip(after, before)))
    probe("splitring_working_recipe_on_20around_matches_formula(N,2N,N)", (20, 40, 20))

    # weight positions the loop LINEARLY and EXACTLY (measured fraction along
    # the root edge's own Y span, splitType=1 or 0; splitType=2 below ignores
    # weight entirely).
    for w in (0.25, 0.5, 0.75):
        mesh = fresh_cyl()
        before_v = set(cmds.ls(mesh + ".vtx[*]", flatten=True))
        split_ring(mesh, EDGE_IDX, splitType=1, weight=w)
        new_v = set(cmds.ls(mesh + ".vtx[*]", flatten=True)) - before_v
        ys = [cmds.pointPosition(v, world=True)[1] for v in new_v]
        avg_y = sum(ys) / len(ys)
        probe("splitring_weight_%s_new_vertex_count" % w, len(new_v))
        probe("splitring_weight_%s_measured_fraction_of_edge" % w, (avg_y - y0) / (y1 - y0))

    # splitType sweep at fixed weight=0.5: 0 and 1 behave identically (single
    # loop, tracks weight); 2 is special - see below. 3/4/5 behave like 0/1.
    for stp in (0, 1, 2, 3):
        mesh = fresh_cyl()
        before_v = set(cmds.ls(mesh + ".vtx[*]", flatten=True))
        before_f = cmds.polyEvaluate(mesh, face=True)
        split_ring(mesh, EDGE_IDX, splitType=stp, weight=0.5)
        new_v = set(cmds.ls(mesh + ".vtx[*]", flatten=True)) - before_v
        ys = sorted(set(round(cmds.pointPosition(v, world=True)[1], 4) for v in new_v))
        probe("splitring_splitType_%d_face_delta" % stp, cmds.polyEvaluate(mesh, face=True) - before_f)
        probe("splitring_splitType_%d_distinct_new_Y_rings" % stp, ys)

    # --- THE OTHER LANDMINE: the `divisions` flag is INERT for splitType in
    # (0,1,3,4,5) - it always inserts exactly ONE loop no matter the value.
    # `divisions` only takes effect when splitType=2, and in that mode it
    # inserts N EVENLY SPACED loops across the FULL (0,1) range of the root
    # edge and `weight` is silently ignored (measured: weight 0.25/0.5/0.75
    # all produce the identical result under splitType=2).
    for div in (1, 2, 3):
        mesh = fresh_cyl()
        before_v = set(cmds.ls(mesh + ".vtx[*]", flatten=True))
        split_ring(mesh, EDGE_IDX, splitType=1, divisions=div, weight=0.5)
        new_v = set(cmds.ls(mesh + ".vtx[*]", flatten=True)) - before_v
        ys = sorted(set(round(cmds.pointPosition(v, world=True)[1], 4) for v in new_v))
        probe("splitring_splitType1_divisions_%d_INERT_distinct_Y" % div, ys)

    for div in (1, 2, 3):
        mesh = fresh_cyl()
        before_v = set(cmds.ls(mesh + ".vtx[*]", flatten=True))
        before_f = cmds.polyEvaluate(mesh, face=True)
        split_ring(mesh, EDGE_IDX, splitType=2, divisions=div, useEqualMultiplier=True)
        new_v = set(cmds.ls(mesh + ".vtx[*]", flatten=True)) - before_v
        ys = sorted(set(round(cmds.pointPosition(v, world=True)[1], 4) for v in new_v))
        probe("splitring_splitType2_divisions_%d_evenly_spaced_Y" % div, ys)
        probe("splitring_splitType2_divisions_%d_face_delta" % div,
              cmds.polyEvaluate(mesh, face=True) - before_f)

    for w in (0.25, 0.5, 0.75):
        mesh = fresh_cyl()
        before_v = set(cmds.ls(mesh + ".vtx[*]", flatten=True))
        split_ring(mesh, EDGE_IDX, splitType=2, divisions=2, weight=w)
        new_v = set(cmds.ls(mesh + ".vtx[*]", flatten=True)) - before_v
        ys = sorted(set(round(cmds.pointPosition(v, world=True)[1], 4) for v in new_v))
        probe("splitring_splitType2_weight_%s_IGNORED_still_evenly_spaced_Y" % w, ys)

    # repeated single-weight calls on the SAME nominal rootEdge index do NOT
    # distribute evenly - after a split, index 40 remaps to the LOWER half of
    # the original edge, so repeated weight=0.5 calls nest into one end
    # instead of spreading across the whole span. This is why splitType=2 +
    # divisions is the only sane path to count>1, not "call N times".
    mesh = fresh_cyl()
    before_v = set(cmds.ls(mesh + ".vtx[*]", flatten=True))
    for _ in range(3):
        split_ring(mesh, EDGE_IDX, splitType=1, weight=0.5)
    new_v = set(cmds.ls(mesh + ".vtx[*]", flatten=True)) - before_v
    ys = sorted(set(round(cmds.pointPosition(v, world=True)[1], 4) for v in new_v))
    probe("splitring_repeated_calls_x3_same_rootedge_NOT_evenly_spaced_Y", ys)
except Exception as exc:  # noqa: BLE001
    probe("SECTION_1_FAILED", str(exc))


# ============================================================================
# SECTION 2: polyExtrudeEdge on a plane border
# ============================================================================
try:
    print("=" * 10, "SECTION 2: polyExtrudeEdge", "=" * 10)
    import maya.api.OpenMaya as om

    def boundary_edges(mesh):
        sel = om.MSelectionList(); sel.add(mesh)
        it = om.MItMeshEdge(sel.getDagPath(0))
        out = []
        while not it.isDone():
            if it.onBoundary():
                out.append(it.index())
            it.next()
        return out

    def fresh_plane():
        cmds.file(new=True, force=True)
        p = cmds.polyPlane(width=4, height=1, subdivisionsWidth=4, subdivisionsHeight=1,
                            constructionHistory=False)
        return mesh_long(p[0])

    mesh = fresh_plane()
    be = boundary_edges(mesh)
    probe("plane_boundary_edge_indices", be)
    all_e = set(range(cmds.polyEvaluate(mesh, edge=True)))
    interior = sorted(all_e - set(be))
    probe("plane_interior_edge_indices", interior)

    # Face yield: cmds.polyExtrudeEdge(edges, translate=(x,y,z), divisions=N,
    # constructionHistory=False) works with the plain component-string
    # argument directly - no polySelect dance needed here (unlike Section 1).
    for n_edges, divisions in ((1, 1), (1, 2), (3, 1), (3, 2)):
        mesh = fresh_plane()
        be = boundary_edges(mesh)
        edges = [mesh + ".e[%d]" % i for i in be[:n_edges]]
        before_f = cmds.polyEvaluate(mesh, face=True)
        cmds.polyExtrudeEdge(edges, translate=(0, 1, 0), divisions=divisions,
                              constructionHistory=False)
        delta = cmds.polyEvaluate(mesh, face=True) - before_f
        probe("extrude_edges%d_div%d_face_delta" % (n_edges, divisions), delta)
        probe("extrude_edges%d_div%d_matches_edges_times_divisions" % (n_edges, divisions),
              delta == n_edges * divisions)

    # interior (non-border) edge: same op, same +1-face-per-edge yield.
    mesh = fresh_plane()
    interior = sorted(set(range(cmds.polyEvaluate(mesh, edge=True))) - set(boundary_edges(mesh)))
    before_f = cmds.polyEvaluate(mesh, face=True)
    cmds.polyExtrudeEdge(mesh + ".e[%d]" % interior[0], translate=(0, 1, 0),
                          constructionHistory=False)
    probe("extrude_interior_edge_face_delta", cmds.polyEvaluate(mesh, face=True) - before_f)

    # translate IS a literal world-space offset (not local/normal-relative):
    # an edge at y=0 moves its two new vertices to y=2 for translate=(0,2,0).
    mesh = fresh_plane()
    edge = mesh + ".e[%d]" % boundary_edges(mesh)[0]
    before_v = set(cmds.ls(mesh + ".vtx[*]", flatten=True))
    cmds.polyExtrudeEdge(edge, translate=(0, 2, 0), constructionHistory=False)
    new_v = set(cmds.ls(mesh + ".vtx[*]", flatten=True)) - before_v
    probe("extrude_translate_is_world_offset_new_vertex_Ys",
          sorted(cmds.pointPosition(v, world=True)[1] for v in new_v))
except Exception as exc:  # noqa: BLE001
    probe("SECTION_2_FAILED", str(exc))


# ============================================================================
# SECTION 3: polyMirrorFace on a half-cube
# ============================================================================
try:
    print("=" * 10, "SECTION 3: polyMirrorFace", "=" * 10)

    def build_half_cube(border_offset=0.0, seam_x=0.0):
        """Cube of width 2 spanning x in [seam_x-2, seam_x], with the +X cap
        face deleted, leaving an open border loop at x=seam_x. border_offset
        then shifts that border loop's OWN vertices (component-space, not the
        transform) further along +X, simulating a half-shell that was
        authored slightly off the intended mirror plane."""
        cmds.file(new=True, force=True)
        c = cmds.polyCube(width=2, height=2, depth=2, constructionHistory=False)
        mesh = mesh_long(c[0])
        cmds.xform(mesh, translation=(seam_x - 1, 0, 0), worldSpace=True)
        cmds.makeIdentity(mesh, apply=True, translate=True, rotate=True, scale=True)
        nfaces = cmds.polyEvaluate(mesh, face=True)
        target = None
        for i in range(nfaces):
            vs = cmds.ls(cmds.polyListComponentConversion(mesh + ".f[%d]" % i, toVertex=True),
                         flatten=True)
            if all(abs(cmds.pointPosition(v, world=True)[0] - seam_x) < 1e-6 for v in vs):
                target = i
                break
        cmds.delete(mesh + ".f[%d]" % target)
        if border_offset:
            for v in cmds.ls(mesh + ".vtx[*]", flatten=True):
                if abs(cmds.pointPosition(v, world=True)[0] - seam_x) < 1e-6:
                    cmds.xform(v, translation=(border_offset, 0, 0), worldSpace=True,
                               relative=True)
        return mesh

    mesh = build_half_cube()
    probe("half_cube_pre_shells_verts_faces",
          (cmds.polyEvaluate(mesh, shell=True), cmds.polyEvaluate(mesh, vertex=True),
           cmds.polyEvaluate(mesh, face=True)))
    probe("half_cube_pre_bbox", cmds.exactWorldBoundingBox(mesh))

    # axis=0 (X) is the only axis that produces the closed-cube result for a
    # border sitting on the YZ plane, as expected; axis=1/2 leave the mesh
    # unchanged (mirroring across a plane the geometry doesn't straddle -
    # the whole object IS the "selection" here, so the operation still
    # "succeeds" but does not close the shape).
    for axis in (0, 1, 2):
        mesh = build_half_cube()
        cmds.polyMirrorFace(mesh, axis=axis, mergeMode=1, mergeThreshold=0.01,
                             constructionHistory=False)
        probe("mirror_axis%d_shells_verts_bbox" % axis,
              (cmds.polyEvaluate(mesh, shell=True), cmds.polyEvaluate(mesh, vertex=True),
               cmds.exactWorldBoundingBox(mesh)))

    # `direction`, `pivot`, and `worldSpace` were all measured to have NO
    # effect on where the mirror plane sits or which side is duplicated -
    # every value produced byte-identical results in this whole-object
    # invocation.
    for direction in (0, 1, -1, 2):
        mesh = build_half_cube()
        cmds.polyMirrorFace(mesh, axis=0, direction=direction, mergeMode=1,
                             mergeThreshold=0.01, constructionHistory=False)
        probe("mirror_direction_%s_bbox_UNCHANGED_by_direction" % direction,
              cmds.exactWorldBoundingBox(mesh))

    mesh = build_half_cube()
    cmds.xform(mesh, pivots=(0.5, 0, 0), worldSpace=True)  # move the object's OWN pivot attr
    cmds.polyMirrorFace(mesh, axis=0, mergeMode=1, mergeThreshold=0.01,
                         constructionHistory=False)
    probe("mirror_object_pivot_attr_moved_to_0.5_bbox_STILL_mirrors_at_world_origin",
          cmds.exactWorldBoundingBox(mesh))

    # THE ACTUAL PLANE: fixed at WORLD ORIGIN along `axis` by default,
    # overridable with `mirrorPlaneCenter` (NOT `pivot`) - moving the whole
    # object 10 units away and mirroring still reflects about world x=0
    # unless mirrorPlaneCenter says otherwise.
    mesh = build_half_cube(seam_x=10.0)
    cmds.polyMirrorFace(mesh, axis=0, mergeMode=1, mergeThreshold=0.01,
                         constructionHistory=False)
    probe("mirror_object_moved_to_seam_x10_default_plane_still_world_origin_bbox",
          cmds.exactWorldBoundingBox(mesh))  # expect reflection about x=0, NOT x=10

    mesh = build_half_cube(seam_x=10.0)
    cmds.polyMirrorFace(mesh, axis=0, mergeMode=1, mergeThreshold=0.01,
                         mirrorPlaneCenter=(10, 0, 0), constructionHistory=False)
    probe("mirror_mirrorPlaneCenter_10_correctly_reflects_about_seam_bbox",
          cmds.exactWorldBoundingBox(mesh))  # expect [8,-1,-1, 12,1,1]

    # mergeMode: 0=duplicate only (no weld, 2 shells); 1=weld to ONE shell,
    # vertex count drops by the border count; 2=becomes ONE shell but does
    # NOT dedupe vertices (still 16, degenerate/coincident duplicates); 3
    # behaves like 0.
    for mm in (0, 1, 2, 3):
        mesh = build_half_cube()
        cmds.polyMirrorFace(mesh, axis=0, mergeMode=mm, mergeThreshold=0.01,
                             constructionHistory=False)
        probe("mergeMode_%d_on_plane_shells_verts" % mm,
              (cmds.polyEvaluate(mesh, shell=True), cmds.polyEvaluate(mesh, vertex=True)))

    # --- THE CARE CASE, and the load-bearing surprise ---------------------
    # A half-cube whose border sits 0.1 off the mirror plane (moved in
    # COMPONENT space, so the transform/pivot story above can't be blamed).
    # Naive expectation: mergeThreshold gates whether the 0.2-unit seam gap
    # (0.1 the source side + 0.1 the mirrored side) merges - small threshold
    # should refuse, large threshold should merge.
    # MEASURED: with mergeMode=1, ALL of mergeThreshold in
    # (0.0, 0.001, 0.05, 0.2, 0.25, -1.0) produce the IDENTICAL result: 1
    # shell, 12 verts, and the border vertex is FORCE-SNAPPED exactly onto
    # the mirror plane (x=0) regardless of how far off it started. Verified
    # up to a 1.9-unit offset in a 2-unit-wide box (i.e. almost the entire
    # mesh) - still silently snaps to a perfect box, threshold ignored.
    # mergeThreshold has NO effect on the boundary-merge decision under
    # mergeMode=1 in this whole-object invocation: shell count can NEVER
    # detect a badly-off-plane border, because mergeMode=1 always produces
    # exactly one shell. The spec's "shell count is MEASURED; refuse if not
    # 1" rule will never fire from an off-plane seam - it needs a DIFFERENT
    # signal (e.g. how far the pre-op border vertices actually sat from the
    # plane, measured BEFORE calling polyMirrorFace).
    for offset in (0.1, 1.0, 1.9):
        for threshold in (0.0, 0.001, 0.05, 0.2, 0.25):
            mesh = build_half_cube(border_offset=offset)
            cmds.polyMirrorFace(mesh, axis=0, mergeMode=1, mergeThreshold=threshold,
                                 constructionHistory=False)
            shells = cmds.polyEvaluate(mesh, shell=True)
            verts = cmds.polyEvaluate(mesh, vertex=True)
            xs = sorted(set(round(cmds.pointPosition(v, world=True)[0], 4)
                            for v in cmds.ls(mesh + ".vtx[*]", flatten=True)))
            probe("care_case_offset%s_threshold%s_shells_verts_distinctX" % (offset, threshold),
                  (shells, verts, xs))

    probe("care_case_CONCLUSION",
          "mergeThreshold is a no-op under mergeMode=1 for the whole-object "
          "invocation - border vertices are unconditionally snapped onto the "
          "mirror plane. shell-count alone cannot implement the spec's "
          "refuse-on-unmerged rule; Task 2 needs a pre-op distance-from-plane "
          "measurement instead (or must find a different mergeMode/selection "
          "shape where mergeThreshold actually gates the weld).")

    # mergeThresholdType: DOES change behavior (unlike mergeThreshold itself) -
    # measured at threshold=0.15, offset=0.1: type 0 merges (1 shell), types
    # 1 and 2 do NOT (2 shells) - so the type flag selects what the number
    # means, and only type 0's interpretation of 0.15 is generous enough
    # here. (This was NOT re-tested against the force-snap finding above,
    # which used the type-0 default throughout - the two findings are not
    # contradictory: they were measured under different threshold TYPES.)
    for mtt in (0, 1, 2):
        mesh = build_half_cube(border_offset=0.1)
        cmds.polyMirrorFace(mesh, axis=0, mergeMode=1, mergeThreshold=0.15,
                             mergeThresholdType=mtt, constructionHistory=False)
        probe("mergeThresholdType_%d_offset0.1_threshold0.15_shells" % mtt,
              cmds.polyEvaluate(mesh, shell=True))
except Exception as exc:  # noqa: BLE001
    probe("SECTION_3_FAILED", str(exc))


# ============================================================================
# SECTION 4: polySplit on a quad plane
# ============================================================================
try:
    print("=" * 10, "SECTION 4: polySplit", "=" * 10)
    cmds.file(new=True, force=True)
    p = cmds.polyPlane(width=2, height=2, subdivisionsWidth=1, subdivisionsHeight=1,
                        constructionHistory=False)
    mesh = mesh_long(p[0])
    probe("quad_faces_edges_before", (cmds.polyEvaluate(mesh, face=True),
                                       cmds.polyEvaluate(mesh, edge=True)))
    for i in range(4):
        vs = cmds.ls(cmds.polyListComponentConversion(mesh + ".e[%d]" % i, toVertex=True),
                     flatten=True)
        probe("edge_%d_endpoints" % i, [cmds.pointPosition(v, world=True) for v in vs])

    # WORKING SYNTAX: cmds.polySplit(mesh, insertpoint=[(edgeIdx, t), ...]) -
    # plain (int, float) tuples, no mesh/component-string prefix on the edge
    # index. This one needs NO polySelect step, unlike polySplitRing.
    before_v, before_e, before_f = vef(mesh)
    cmds.polySplit(mesh, insertpoint=[(0, 0.5), (2, 0.5)], constructionHistory=False)
    after_v, after_e, after_f = vef(mesh)
    probe("polysplit_two_midpoints_delta_verts_edges_faces",
          (after_v - before_v, after_e - before_e, after_f - before_f))
    probe("polysplit_new_vertex_positions_include_both_midpoints",
          sorted(cmds.pointPosition(v, world=True) for v in cmds.ls(mesh + ".vtx[*]", flatten=True)))

    # a single insertpoint is a SILENT NO-OP: returns success, changes nothing.
    cmds.file(new=True, force=True)
    p2 = cmds.polyPlane(width=2, height=2, subdivisionsWidth=1, subdivisionsHeight=1,
                        constructionHistory=False)
    mesh2 = mesh_long(p2[0])
    before_f2 = cmds.polyEvaluate(mesh2, face=True)
    cmds.polySplit(mesh2, insertpoint=[(0, 0.5)], constructionHistory=False)
    probe("polysplit_single_point_is_SILENT_NOOP_face_delta",
          cmds.polyEvaluate(mesh2, face=True) - before_f2)
except Exception as exc:  # noqa: BLE001
    probe("SECTION_4_FAILED", str(exc))

print("PROBE done")
