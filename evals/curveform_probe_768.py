"""#768 probe: how THIS Maya 2027 actually drives curve construction.

Run:  E:\\Autodesk\\Maya2027\\bin\\mayapy.exe evals/curveform_probe_768.py
Every finding prints as 'PROBE <name>: <value>'. Facts, not assertions:
a surprising value here changes Task 3's constants, not this script.
"""
from __future__ import annotations

import maya.standalone
maya.standalone.initialize(name="python")
import maya.cmds as cmds  # noqa: E402


def probe(name, value):
    print("PROBE %s: %r" % (name, value))


cmds.file(new=True, force=True)

# --- (a) does curve(ep=) interpolate? -----------------------------------
pts = [(0, 0, 0), (1, 2, 0), (2, 1, 0), (4, 3, 0)]
crv = cmds.curve(ep=pts, degree=3)
probe("ep_curve_created", crv)
# An interpolating curve passes through every edit point; measure the
# closest point on the curve to each authored point.
import maya.api.OpenMaya as om  # noqa: E402
sel = om.MSelectionList(); sel.add(crv)
fn = om.MFnNurbsCurve(sel.getDagPath(0))
worst = max(
    (om.MPoint(p) - fn.closestPoint(om.MPoint(p), space=om.MSpace.kWorld)[0]).length()
    for p in pts
)
probe("ep_curve_worst_point_distance", worst)  # expect ~0.0

# --- (b) closed ring curve ----------------------------------------------
ring = [(1, 0, 0), (0, 0, 1), (-1, 0, 0), (0, 0, -1)]
rc = cmds.curve(ep=ring + [ring[0]], degree=3)
closed = cmds.closeCurve(rc, constructionHistory=False, preserveShape=0,
                         replaceOriginal=True)
probe("closeCurve_result", closed)
probe("ring_form_after_close", cmds.getAttr(closed[0] + ".form")
      if closed else None)  # 0=open 1=closed 2=periodic

# --- (c) revolve -> nurbsToPoly ----------------------------------------
cmds.file(new=True, force=True)
prof = cmds.curve(ep=[(0.2, 0, 0), (0.5, 0.4, 0), (0.3, 0.9, 0), (0.4, 1.2, 0)],
                  degree=3)
rev = cmds.revolve(prof, constructionHistory=False, axis=(0, 1, 0),
                   pivot=(0, 0, 0), degree=3, sections=16,
                   startSweep=0, endSweep=360)
probe("revolve_result", rev)
poly = cmds.nurbsToPoly(rev[0], constructionHistory=False, format=2,
                        polygonType=1, uType=2, uNumber=24, vType=2, vNumber=16)
probe("revolve_poly", poly)
probe("revolve_poly_faces", cmds.polyEvaluate(poly[0], face=True))
# Which parameter runs around? Compare against uNumber/vNumber asymmetry.
probe("revolve_poly_verts", cmds.polyEvaluate(poly[0], vertex=True))

# --- (c2) loft -> nurbsToPoly ------------------------------------------
cmds.file(new=True, force=True)
rings = []
for y, r in ((0.0, 0.5), (0.6, 0.8), (1.4, 0.6), (2.0, 0.3)):
    pts = [(r, y, 0), (0, y, r), (-r, y, 0), (0, y, -r)]
    c = cmds.curve(ep=pts + [pts[0]], degree=3)
    c = cmds.closeCurve(c, constructionHistory=False, preserveShape=0,
                        replaceOriginal=True)[0]
    rings.append(c)
lofted = cmds.loft(*rings, constructionHistory=False, uniform=True,
                   close=False, autoReverse=False, degree=3)
probe("loft_result", lofted)
lpoly = cmds.nurbsToPoly(lofted[0], constructionHistory=False, format=2,
                         polygonType=1, uType=2, uNumber=24, vType=2, vNumber=16)
probe("loft_poly_faces", cmds.polyEvaluate(lpoly[0], face=True))

# --- (d) sweepMeshFromCurve / sweep operations --------------------------
cmds.file(new=True, force=True)
path = cmds.curve(ep=[(0, 0, 0), (0, 1, 0.3), (0, 2, 0.2), (0, 3, 0.8)],
                  degree=3)
# Check what sweep commands are available
probe("sweep_available_in_cmds", [c for c in dir(cmds) if 'sweep' in c.lower()])

# Try sweepMeshFromCurve first (expected from brief)
try:
    sweep = cmds.sweepMeshFromCurve(path)
    probe("sweepMeshFromCurve_works", True)
    probe("sweep_return", sweep)
    probe("sweep_meshes", cmds.ls(type="mesh", long=True))
    creators = cmds.ls(type="sweepMeshCreator")
    probe("sweep_creator_nodes", creators)
    if creators:
        attrs = cmds.listAttr(creators[0], keyable=False, hasData=True) or []
        interesting = [a for a in attrs if any(
            k in a.lower() for k in
            ("profile", "taper", "twist", "scale", "poly", "precision",
             "segment", "interpolation", "sweep", "distance", "cap"))]
        probe("sweep_creator_attrs", sorted(interesting))
        for a in sorted(interesting):
            try:
                probe("sweep_attr %s" % a, cmds.getAttr("%s.%s" % (creators[0], a)))
            except Exception as exc:  # noqa: BLE001 - compound attrs print as errors
                probe("sweep_attr %s" % a, "UNREADABLE: %s" % exc)
except AttributeError as e:
    probe("sweepMeshFromCurve_available", False)
    probe("sweepMeshFromCurve_error", str(e))

print("PROBE done")
