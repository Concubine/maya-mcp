"""#770 probe round 4: the live gate's ground (assemble-built plane) baked
ALL-TRANSPARENT AO; every polyPlane bake before it was fine. Which variable
is it - the assemble-built geometry, or GUI-vs-standalone Maya?

Run:  E:\\Autodesk\\Maya2027\\bin\\mayapy.exe evals/meshmaps_probe_770d.py

This reproduces the gate's exact build under standalone. If it reproduces
here, the geometry is the variable and can be dissected cheaply. If it does
not, the difference is the GUI session and the dissection moves there.
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import maya.standalone

maya.standalone.initialize(name="python")
import maya.cmds as cmds  # noqa: E402

from maya_plugin.handlers import assemble, meshmaps, pngprobe  # noqa: E402

OUT = os.path.join(tempfile.gettempdir(), "meshmaps_probe_770d")
os.makedirs(OUT, exist_ok=True)
for f in os.listdir(OUT):
    try:
        os.unlink(os.path.join(OUT, f))
    except OSError:
        pass


def probe(name, value):
    print("PROBE %s: %r" % (name, value), flush=True)


try:
    cmds.file(new=True, force=True)
    result = assemble.assemble({
        "name": "gate",
        "parts": [
            {"kind": "plane", "dim": [6.0, 0.01, 6.0], "pos": [0, 0, 0],
             "chunk": "gate_ground"},
            {"kind": "cylinder", "dim": [0.8, 3.0, 0.8],
             "pos": [0, 1.5, 0], "chunk": "gate_limb",
             "subdivisions": [20, 8]},
            {"kind": "torus", "dim": [1.3, 0.4, 1.3], "pos": [0, 1.5, 0],
             "chunk": "gate_collar"},
        ],
        "combine": True, "freeze": True})
    names = [o.get("name") if isinstance(o, dict) else o
             for o in result.get("objects") or []]
    probe("assemble_objects", names)
    ground = next(n for n in names if "gate_ground" in n)
    shape = cmds.listRelatives(ground, shapes=True, fullPath=True)[0]

    # Evidence about the mesh itself, before any bake:
    probe("ground_uv_count", cmds.polyEvaluate(shape, uvcoord=True))
    probe("ground_uv_sets", cmds.polyUVSet(shape, query=True,
                                           allUVSets=True))
    probe("ground_current_uv_set", cmds.polyUVSet(shape, query=True,
                                                  currentUVSet=True))
    us = cmds.getAttr(shape + ".uvst[0].uvsp[*]") or []
    if us:
        flat_u = [p[0] for p in us]
        flat_v = [p[1] for p in us]
        probe("ground_uv_bbox", (min(flat_u), max(flat_u),
                                 min(flat_v), max(flat_v)))
    probe("ground_face_normal_sample", cmds.polyInfo(shape + ".f[0]",
                                                     faceNormals=True))
    probe("ground_bbox", cmds.exactWorldBoundingBox(ground))

    out = meshmaps.bake_mesh_maps({"meshes": [ground], "out_dir": OUT,
                                   "maps": ["ao"], "resolution": 256})
    entry = out["baked"][0]
    probe("assemble_ground_ao_stats", entry["stats"])
except Exception as exc:  # noqa: BLE001
    probe("assemble_ground_ao", "REFUSED/FAILED: %s" % exc)
    traceback.print_exc()

# control: a plain polyPlane in the SAME scene
try:
    plane = cmds.ls(cmds.polyPlane(name="control_plane", width=6, height=6,
                                   constructionHistory=False)[0],
                    long=True)[0]
    out = meshmaps.bake_mesh_maps({"meshes": [plane], "out_dir": OUT,
                                   "maps": ["ao"], "resolution": 256})
    probe("polyplane_control_ao_stats", out["baked"][0]["stats"])
except Exception as exc:  # noqa: BLE001
    probe("polyplane_control_ao", "REFUSED/FAILED: %s" % exc)
    traceback.print_exc()

print("DONE", flush=True)
