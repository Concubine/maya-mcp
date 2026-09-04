"""Probe #824, part 2: the steps part 1 could not finish.

Part 1 (occlusion_probe_824.py) hung the agent Maya for >12 min in step H
(a 250k-face sphere) and its own-shape exclusion missed the target's shapes
under a group (listRelatives allDescendents+shapes answered nothing). Here:

  F2  own shapes via cmds.ls(dag=True, shapes=True): a grouped target
  H2  the big mesh, one step per call with its own timing: build, MFnMesh,
      one ray, nine rays, with and without MMeshIsectAccelParams; 40k faces
      first, 250k only if 40k is quick
  I   isolate=[red] + target red from the back; a hidden occluder
  J   closestIntersection's miss shape

Run:  MAYA_MCP_PORT=9878 python evals/occlusion_probe_824b.py
"""

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import occlusion_probe_824 as p1  # noqa: E402

OUT = p1.OUT
FINDINGS = {}


def show(label, value):
    FINDINGS[label] = value
    with open(os.path.join(OUT, "findings_b.json"), "w", encoding="utf-8") as fh:
        json.dump(FINDINGS, fh, indent=1, default=str)
    print("\n--- %s ---" % label)
    print(json.dumps(value, indent=1, sort_keys=True, default=str))


LIB2 = p1.LIB + r'''

def shapes_under(transforms):
    return set(cmds.ls(transforms, dag=True, shapes=True, long=True, noIntermediate=True) or [])

def timed_rays(shape, cam_pos, targets, accel):
    sel = om.MSelectionList(); sel.add(shape)
    t0 = time.perf_counter(); fn = om.MFnMesh(sel.getDagPath(0)); t_fn = time.perf_counter() - t0
    params = fn.autoUniformGridParams() if accel else None
    src = om.MPoint(*cam_pos)
    out = {"fn_ms": round(t_fn * 1000, 2)}
    pts = samples_of(targets)
    t0 = time.perf_counter()
    for i, p in enumerate(pts):
        d = om.MPoint(*p) - src; dist = d.length()
        if accel:
            hit = fn.closestIntersection(om.MFloatPoint(src), om.MFloatVector(d.normal()), om.MSpace.kWorld, dist, False, accelParams=params)
        else:
            hit = fn.closestIntersection(om.MFloatPoint(src), om.MFloatVector(d.normal()), om.MSpace.kWorld, dist, False)
        if i == 0:
            out["first_ray_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    out["nine_rays_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    if accel:
        fn.freeCachedIntersectionAccelerator()
    return out
'''


def main():
    py = p1.py
    ok = p1.ok
    py(LIB2 + "\nr = 1")

    # F2: grouped target, own shapes excluded
    ok("new_scene", {"confirm": True}); py(LIB2 + "\nr = 1")
    py('''
        cmds.file(new=True, force=True)
        a = cmds.polyCube(name="a", ch=False)[0]; cmds.xform(a, ws=True, t=[-1, 0, 0]); colour(a, (1, 0, 0), "ra")
        b = cmds.polyCube(name="b", ch=False)[0]; cmds.xform(b, ws=True, t=[1, 0, 0]); colour(b, (1, 0, 0), "rb")
        g = cmds.group(a, b, name="pair")
        w = cmds.polyCube(name="wall", w=4, h=2, d=0.2, ch=False)[0]; cmds.xform(w, ws=True, t=[0, 0, 2]); colour(w, (0, 0, 1), "wall")
        r = 1
    ''')
    setup = py("r = {'occ': occluders_for(['|pair']), 'own': sorted(shapes_under(['|pair'])), 'own_shape_arg': sorted(shapes_under(['|pair|a|aShape']))}")
    for angle in ("front", "back"):
        shot = p1.capture({"angles": [angle], "target": "|pair"}, "F2_%s" % angle)
        show("F2_group_%s" % angle, {"setup": setup, "capture": shot, "rays": p1.rays(shot["camera"], ["|pair"])})

    # H2: timing, one step per call
    ok("new_scene", {"confirm": True}); py(LIB2 + "\nr = 1")
    for sa in (200,):  # 500x500 (250k faces) HUNG polySphere itself twice (>600 s), not the rays
        build = py('''
            cmds.file(new=True, force=True)
            t0 = time.perf_counter()
            s = cmds.polySphere(name="big", sa=%d, sh=%d, r=3, ch=False)[0]
            build_s = time.perf_counter() - t0
            c = cmds.polyCube(name="red", ch=False)[0]; cmds.xform(c, ws=True, t=[0, 0, 5])
            r = {"faces": cmds.polyEvaluate(s, face=True), "build_s": round(build_s, 2)}
        ''' % (sa, sa), timeout_s=600)
        show("H2_build_%d" % sa, build)
        for accel in (False, True):
            timing = py("r = timed_rays('|big|bigShape', [0, 0, -8], ['|red'], %r)" % accel, timeout_s=900)
            show("H2_rays_%d_accel_%s" % (sa, accel), timing)
            timing = py("r = timed_rays('|big|bigShape', [0, 0, -8], ['|red'], %r)" % accel, timeout_s=900)
            show("H2_rays_%d_accel_%s_again" % (sa, accel), timing)

    # I: isolate hides the occluder; a hidden occluder
    ok("new_scene", {"confirm": True}); py(LIB2 + "\nr = 1")
    py("r = red_blue_scene()")
    shot = p1.capture({"angles": ["back"], "target": "|red", "isolate": ["|red"]}, "I_isolate")
    show("I_isolate", {"capture": shot,
                       "rays_all": p1.rays(shot["camera"], ["|red"]),
                       "rays_isolate": p1.rays(shot["camera"], ["|red"], ["|red"])})
    py("cmds.setAttr('|blue.visibility', False); r = 1")
    shot = p1.capture({"angles": ["back"], "target": "|red"}, "I_hidden")
    show("I_hidden_occluder", {"capture": shot, "rays": p1.rays(shot["camera"], ["|red"]),
                               "visible": py("r = [m['shape'] for m in visible_meshes()]")})
    # a hidden PARENT: the shape itself is visible=True but nothing draws
    py("cmds.setAttr('|blue.visibility', True); g = cmds.group('|blue', name='holder'); cmds.setAttr(g + '.visibility', False); r = 1")
    shot = p1.capture({"angles": ["back"], "target": "|red"}, "I_hidden_parent")
    show("I_hidden_parent", {"capture": shot, "rays": p1.rays(shot["camera"], ["|red"]),
                             "visible": py("r = [m['shape'] for m in visible_meshes()]")})

    # J: the miss shape
    show("J_miss_shape", py('''
        sel = om.MSelectionList(); sel.add("|red"); dag = sel.getDagPath(0); dag.extendToShape()
        fn = om.MFnMesh(dag)
        miss = fn.closestIntersection(om.MFloatPoint(0, 50, 0), om.MFloatVector(0, 1, 0), om.MSpace.kWorld, 10.0, False)
        hit = fn.closestIntersection(om.MFloatPoint(0, 0, 10), om.MFloatVector(0, 0, -1), om.MSpace.kWorld, 100.0, False)
        r = {"miss": repr(miss), "hit": repr(hit)}
    '''))
    print("\nfindings ->", os.path.join(OUT, "findings_b.json"))


if __name__ == "__main__":
    main()
