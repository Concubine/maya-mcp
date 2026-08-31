"""#770 probe round 5: does a prior render_scene() poison the bake?

The live gate's only untested-anywhere sequence was: render_scene(arnold)
FIRST, arnoldRenderToTexture SECOND. Round 4 proved the geometry innocent.
Run:  E:\Autodesk\Maya2027\bin\mayapy.exe evals/meshmaps_probe_770e.py
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

from maya_plugin.handlers import assemble, lighting, material, meshmaps, render  # noqa: E402

OUT = os.path.join(tempfile.gettempdir(), "meshmaps_probe_770e")
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
        ],
        "combine": True, "freeze": True})
    names = [o.get("name") for o in result["objects"]]
    ground = next(n for n in names if "gate_ground" in n)
    material.assign_material({"mesh": ground, "name": "gate_ground_mat",
                              "shader": "standardSurface"})
    lighting.setup_lighting({"preset": "three_point", "intensity": 1.5})

    # bake BEFORE any render - the control
    out = meshmaps.bake_mesh_maps({"meshes": [ground], "out_dir": OUT,
                                   "maps": ["ao"], "resolution": 256})
    probe("bake_before_render_stats", out["baked"][0]["stats"])

    # now render the scene the way the gate does
    r = render.render_scene({"angles": ["three_quarter"],
                             "renderer": "arnold", "resolution": 256,
                             "samples": 2})
    probe("render_ran", bool(r.get("images")))

    # and bake AGAIN, after the render
    out2 = meshmaps.bake_mesh_maps({"meshes": [ground], "out_dir": OUT,
                                    "maps": ["ao"], "resolution": 256})
    probe("bake_after_render_stats", out2["baked"][0]["stats"])
except Exception as exc:  # noqa: BLE001
    probe("sequence", "REFUSED/FAILED: %s" % exc)
    traceback.print_exc()

print("DONE", flush=True)
