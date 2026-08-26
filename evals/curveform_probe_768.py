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
import os
import maya.mel as mel  # noqa: E402

cmds.file(new=True, force=True)
path = cmds.curve(ep=[(0, 0, 0), (0, 1, 0.3), (0, 2, 0.2), (0, 3, 0.8)],
                  degree=3)

# Check what sweep commands are available before loading
probe("sweep_available_in_cmds_before_load", [c for c in dir(cmds) if 'sweep' in c.lower()])

# Check plugin paths for sweep plugins
plugin_paths = cmds.pluginInfo(query=True, listPluginsPath=True) or []
sweep_plugin_candidates = [p for p in plugin_paths if "sweep" in p.lower()]
probe("sweep_plugin_paths_count", len(plugin_paths))
probe("sweep_plugin_candidates_from_path", sweep_plugin_candidates)

# List sweep plugins in the plugin directories
sweep_plugins_in_dirs = []
for ppath in plugin_paths:
    if os.path.isdir(ppath):
        try:
            files = os.listdir(ppath)
            sweep_files = [f for f in files if "sweep" in f.lower()]
            if sweep_files:
                sweep_plugins_in_dirs.extend(sweep_files)
        except:
            pass
probe("sweep_plugins_in_plugin_dirs", sweep_plugins_in_dirs)

# Try to load sweep plugin
plugin_loaded = False
loaded_plugin_name = None
for plugin_attempt in ("sweep", "sweep.mll", "sweepMesh", "sweepMesh.mll"):
    try:
        cmds.loadPlugin(plugin_attempt, quiet=True)
        plugin_loaded = True
        loaded_plugin_name = plugin_attempt
        probe("sweep_plugin_loaded", plugin_attempt)
        break
    except Exception as e:
        pass

if not plugin_loaded:
    probe("sweep_plugin_load_status", "failed to load any sweep plugin variant")

# Check if sweepMeshFromCurve is now available via cmds
probe("sweepMeshFromCurve_in_cmds_after_load", hasattr(cmds, "sweepMeshFromCurve"))

# Check via mel
try:
    mel_exists = mel.eval('exists "sweepMeshFromCurve"')
    probe("sweepMeshFromCurve_in_mel", mel_exists)
except Exception as e:
    probe("sweepMeshFromCurve_mel_check_error", str(e))

# Try sweepMeshFromCurve via cmds (may be loaded now)
try:
    sweep = cmds.sweepMeshFromCurve(path)
    probe("sweepMeshFromCurve_works", True)
    probe("sweep_requires_plugin", loaded_plugin_name)
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
    probe("sweepMeshFromCurve_available_after_load", False)
    probe("sweepMeshFromCurve_error_after_load", str(e))
    # Try via mel.eval if cmds still doesn't have it
    try:
        sweep_mel_result = mel.eval('sweepMeshFromCurve %s' % path)
        probe("sweepMeshFromCurve_via_mel_works", True)
        probe("sweep_requires_plugin", loaded_plugin_name)
        probe("sweep_mel_result", sweep_mel_result)
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
    except Exception as mel_e:
        probe("sweepMeshFromCurve_unavailable_cmds_and_mel", "both failed")
        probe("sweepMeshFromCurve_mel_error", str(mel_e))

print("PROBE done")
