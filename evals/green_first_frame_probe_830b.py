"""Probe #830 part 2: the first attempt did NOT reproduce the green frame.

Part 1, on a fresh agent Maya: three cubes wearing a loud red shader, then a
capture straight after each of the four edits the reporter named (re-assign
the shading group, group+move, add a mesh, setup_lighting). Every frame came
back red. 16 frames, 0 green.

So whatever arms it is not "a shape that has never been drawn" on its own.
This part moves the fixture towards the session that DID see it - a modelling
agent's, at the point it happened:

  G  28 meshes and 3 shaders, not 3 meshes and 1 - more render items, and the
     reporter's scene had exactly that
  H  the shading groups assigned in BULK through one execute_python
     (cmds.sets(meshes, forceElement=...)), which is what the reporter did
     because assign_material is one mesh per call
  I  a brand-new shader created and assigned immediately before the capture -
     an uncompiled shader rather than an unassigned shape
  J  the same, through the assign_material HANDLER rather than raw cmds
  K  a capture on a virgin process's very first call (part 1 spent several
     captures warming VP2 before its first edit)

Each variant captures 4 angles in ONE call and every frame is classified, so
a green first frame with red followers - the reported signature - is visible
without interpretation.

Run:  MAYA_MCP_PORT=9878 MAYA_MCP_EXPECT_PID=<pid> python evals/green_first_frame_probe_830b.py

MUTATES THE ANSWERING MAYA'S SCENE. Refuses 9877.
"""
from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import green_first_frame_probe_830 as p1  # noqa: E402

LIB2 = r'''
import maya.cmds as cmds


def shader(name, rgb):
    sh = cmds.shadingNode("standardSurface", asShader=True, name=name)
    cmds.setAttr(sh + ".baseColor", rgb[0], rgb[1], rgb[2], type="double3")
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                   name=name + "SG")
    cmds.connectAttr(sh + ".outColor", sg + ".surfaceShader", force=True)
    return sg


def prop(n=28):
    """A prop-sized scene: n meshes, 3 shaders, like the session that saw it."""
    clean()
    sgs = [shader("probe_red2", (0.9, 0.05, 0.05)),
           shader("probe_dark2", (0.08, 0.08, 0.09)),
           shader("probe_cream2", (0.85, 0.8, 0.7))]
    made = []
    for i in range(n):
        cube = cmds.polyCube(name="prop_%02d" % i)[0]
        cmds.setAttr(cube + ".translateX", (i % 7) * 1.6 - 4.8)
        cmds.setAttr(cube + ".translateY", (i // 7) * 1.6)
        cmds.setAttr(cube + ".scaleZ", 0.6)
        made.append(cube)
    return {"meshes": len(made), "sgs": sgs}


def bulk_assign(sg="probe_red2SG"):
    """One call, every mesh - what an agent does when the tool is per-mesh."""
    meshes = [m for m in cmds.ls(type="mesh", long=True)
              if not cmds.getAttr(m + ".intermediateObject")]
    cmds.sets(meshes, edit=True, forceElement=sg)
    return len(meshes)


def fresh_shader_assign():
    """A shader that has never been compiled, assigned right before a capture."""
    import random
    name = "probe_fresh_%d" % random.randint(1000, 9999)
    sg = shader(name, (0.05, 0.05, 0.9))
    meshes = [m for m in cmds.ls(type="mesh", long=True)
              if not cmds.getAttr(m + ".intermediateObject")]
    cmds.sets(meshes, edit=True, forceElement=sg)
    return {"shader": name, "meshes": len(meshes)}
'''


def main():
    print("### probe 830b on port %s" % p1.PORT)
    ping = p1.ok("ping", {})
    print("answering Maya: pid %s" % (ping.get("process") or {}).get("pid"))
    p1.ok("new_scene", {"confirm": True})
    p1.py(p1.LIB + "\n" + LIB2 + "\nr = 1")

    print("\nG/H. 28 meshes, 3 shaders, bulk-assigned in one call")
    built = p1.py("r = prop()")
    assigned = p1.py("r = bulk_assign()")
    p1.ok("setup_lighting", {"preset": "three_point"})
    g = p1.frames("G_first_after_bulk_assign")
    p1.show("G bulk assign then capture", {
        "scene": built, "meshes_assigned": assigned,
        "verdicts": [f["verdict"] for f in g],
        "green_first_frame": g[0]["verdict"] == "GREEN"})

    print("\nI. a brand-new shader assigned immediately before the capture")
    fresh = p1.py("r = fresh_shader_assign()")
    i = p1.frames("I_fresh_shader")
    p1.show("I fresh shader", {
        "shader": fresh,
        "verdicts": [f["verdict"] for f in i],
        "any_green": any(f["verdict"] == "GREEN" for f in i),
        # the fresh shader is BLUE: a frame that is neither red nor green here
        # is the new material actually landing, which is its own answer
        "top_colours_frame1": i[0]["top_colours"]})

    print("\nJ. through the assign_material handler, then capture")
    p1.ok("assign_material", {"mesh": "prop_00", "shader": "standardSurface",
                              "name": "probe_handler_mat"})
    j = p1.frames("J_after_assign_material_handler")
    p1.show("J assign_material handler", {
        "verdicts": [f["verdict"] for f in j],
        "any_green": any(f["verdict"] == "GREEN" for f in j)})

    print("\nK. the whole thing again on a scene VP2 has never drawn")
    p1.ok("new_scene", {"confirm": True})
    p1.py(p1.LIB + "\n" + LIB2 + "\nr = 1")
    p1.py("r = prop()")
    p1.py("r = bulk_assign()")
    k = p1.frames("K_virgin_scene_first_capture")
    p1.show("K first capture of a scene never drawn", {
        "verdicts": [f["verdict"] for f in k],
        "green_first_frame": k[0]["verdict"] == "GREEN",
        "top_colours_frame1": k[0]["top_colours"]})


    total_green = sum(1 for fr in (g + i + j + k) if fr["verdict"] == "GREEN")
    p1.show("VERDICT", {
        "frames_measured_here": len(g) + len(i) + len(j) + len(k),
        "green_frames": total_green,
        "reproduced": total_green > 0})
    print("\nfindings -> %s" % os.path.join(p1.OUT, "findings.json"))


if __name__ == "__main__":
    main()
