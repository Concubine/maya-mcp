"""Generate evals/rigging_fixtures/skinned_cylinder.fbx - run ONCE under
mayapy, commit the artifact. The headless fbxbytes tests pin their numbers
against this file the way test_fbxbytes.py pins the clock tower.

    E:\\Autodesk\\Maya2027\\bin\\mayapy.exe evals/make_skin_fixture.py

3-joint chain through a 2-unit cylinder, closestDistance bind, exported with
skins through the SAME handler the tool uses - so the fixture is the tool's
own output, not a hand-made file.
"""
import os
import sys

import maya.standalone

maya.standalone.initialize(name="python")
import maya.cmds as cmds  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from maya_plugin.handlers import export, rigging  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "rigging_fixtures")
os.makedirs(OUT_DIR, exist_ok=True)

cmds.file(new=True, force=True)
mesh = cmds.polyCylinder(name="fixture_tube", radius=0.3, height=2.0,
                         subdivisionsY=6, ch=False)[0]
cmds.xform(mesh, worldSpace=True, translation=[0, 1.0, 0])
skel = rigging.create_skeleton({
    "chain": [[0, 0, 0], [0, 1, 0], [0, 2, 0]], "chain_prefix": "fix"})
bind = rigging.bind_skin({"mesh": "|fixture_tube", "root": skel["root"]})
assert bind["unweighted_vertices"] == 0, bind

result = export.export_fbx({
    "path": os.path.join(OUT_DIR, "skinned_cylinder.fbx").replace("\\", "/"),
    "metres_per_unit": 1.0,
    "include_skins": True,
})
print("wrote", result["path"], result["bytes"], "bytes")
print("skin block:", result["skin"])
maya.standalone.uninitialize()
