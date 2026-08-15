"""Live gate for maya_combine and maya_uv_atlas against a real Maya.

The headless suites for these two use fakes, and a fake is exactly what hid a
live-only bug twice in this repo (#584's isolate, #587's mirror reparenting).
So every claim the tools make in their descriptions is re-asked here of real
Maya and reported as a MEASURED number.

The handlers are imported and called INSIDE Maya rather than dispatched over
the wire, because the running plugin registered its command table when it
loaded and does not know about commands added since. Registration itself is
covered headless (tests/test_server_tools.py); what cannot be covered headless,
and is the whole point of this file, is whether cmds actually behaves the way
the fakes pretend.

Run:  set MAYA_MCP_PORT=9878 && .venv/Scripts/python.exe evals/combine_uv_live.py
"""

from __future__ import annotations

import ast
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from live_call import call  # noqa: E402

CHECKS = []


def check(label, got, want, ok=None):
    passed = ok(got) if ok else got == want
    CHECKS.append((passed, label, got, want))
    print("%-5s %-52s got %s" % ("PASS" if passed else "FAIL", label, got))


def ok_resp(resp, what):
    if resp.get("status") != "ok":
        print("FAILED %s: %s" % (what, str(resp.get("error", resp))[:400]))
        sys.exit(1)
    return resp["result"]


def run(code, what, timeout=600.0):
    out = ok_resp(call("execute_python", {"code": code}, timeout), what)
    if out.get("traceback"):
        print("PYTHON FAILED (%s):\n%s" % (what, out["traceback"][:2000]))
        sys.exit(1)
    return ast.literal_eval(out["result_repr"]) if out.get("result_repr") else None


PRELUDE = r'''
import importlib
import maya.cmds as cmds
from maya_plugin.handlers import combine as _combine
from maya_plugin.handlers import uvatlas as _uvatlas
from maya_plugin.handlers import uvmath as _uvmath
from maya_plugin.handlers import meshcheck as _meshcheck
importlib.reload(_uvmath)
importlib.reload(_uvatlas)
importlib.reload(_combine)
# maya-mcp #634: "cm" is the authoring convention - the numbers below still
# mean metres, and displayed measurements are identical either way, but the
# session is no longer left in a unit that makes the NEXT thing built in it
# export 100x too large. Was "m".
cmds.currentUnit(linear="cm")
'''


COMBINE_CODE = PRELUDE + r'''
boxes = []
for i in range(3):
    node = cmds.polyCube(w=1, h=1, d=1, name="part%d" % i, ch=False)[0]
    cmds.move(i * 2.0, 0, 0, node, absolute=True)
    boxes.append((cmds.ls(node, long=True) or [node])[0])

out = _combine.combine({"names": boxes, "name": "kit_test_piece",
                        "pivot": "origin", "freeze": True})
shape = cmds.listRelatives(out["name"], shapes=True, fullPath=True)[0]
stats = _meshcheck.mesh_stats(shape)
result = {
    "name": out["name"],
    "shells": out["shells"],
    "tris": out["tris"],
    "inputs": out["inputs"],
    "boundary_edges": stats["boundary_edges"],
    "watertight": stats["watertight"],
    "scale": [round(s, 6) for s in cmds.getAttr(out["name"] + ".scale")[0]],
    "pivot": [round(p, 6) for p in cmds.xform(out["name"], q=True, ws=True, rp=True)],
    # TRANSFORMS only: an unfiltered ls("part*") also matches the shape nodes,
    # which is not what "did the inputs get consumed" means.
    "survivors": len(cmds.ls("part*", long=True, type="transform") or []),
    "sg_count": len(cmds.listSets(object=shape, type=1) or []),
}
result
'''


UV_CODE = PRELUDE + r'''
# A cube and a platonic solid do NOT share a UV convention. If normalisation
# works, both land in the SAME patch rectangle regardless.
cube = (cmds.ls(cmds.polyCube(w=1, h=1, d=1, name="uv_cube", ch=False)[0],
                long=True) or [""])[0]
ico = (cmds.ls(cmds.polyPlatonicSolid(r=1, st=1, name="uv_ico", ch=False)[0],
               long=True) or [""])[0]

packed = _uvatlas.uv_atlas({"names": [cube, ico], "cols": 4, "rows": 4,
                            "patch": 6, "margin": 0.0})
rect = _uvmath.patch_rect(4, 4, 2, 1, margin=0.0)

# Packing again must be stable, not drift - the second call re-normalises the
# already-packed layout, so a caller can re-run a build step safely.
again = _uvatlas.uv_atlas({"names": [cube], "cols": 4, "rows": 4,
                           "patch": 6, "margin": 0.0, "project": "keep"})

margined = _uvatlas.uv_atlas({"names": [ico], "cols": 4, "rows": 4,
                              "patch": 6, "margin": 0.1})
bare = _uvmath.patch_rect(4, 4, 2, 1, margin=0.0)

# --- fixed texel density -------------------------------------------------
# The constant AUTOPROJ_UV_PER_METRE is the whole basis of a STATED density,
# so it is asserted here against real Maya rather than trusted.
probe = cmds.polyCube(w=1, h=1, d=1, name="uv_metre", ch=False)[0]
probe = (cmds.ls(probe, long=True) or [probe])[0]
pshape = cmds.listRelatives(probe, shapes=True, fullPath=True)[0]
cmds.polyAutoProjection(pshape, ch=False, scaleMode=0)
pbb = cmds.polyEvaluate(pshape, boundingBox2d=True)

big = cmds.polyCube(w=3, h=3, d=3, name="dens_big", ch=False)[0]
big = (cmds.ls(big, long=True) or [big])[0]
small = cmds.polyCube(w=0.5, h=0.5, d=0.5, name="dens_small", ch=False)[0]
small = (cmds.ls(small, long=True) or [small])[0]
d_big = _uvatlas.uv_atlas({"names": [big], "cols": 4, "rows": 4, "patch": 0,
                           "margin": 0.0, "world_scale": 3.0})
d_small = _uvatlas.uv_atlas({"names": [small], "cols": 4, "rows": 4, "patch": 0,
                             "margin": 0.0, "world_scale": 3.0})
bb_big = d_big["meshes"][0]["uv_bounds"]
bb_small = d_small["meshes"][0]["uv_bounds"]

result = {
    "rect": [round(q, 6) for q in rect],
    "cube_bounds": packed["meshes"][0]["uv_bounds"],
    "ico_bounds": packed["meshes"][1]["uv_bounds"],
    "all_inside": packed["all_inside"],
    "repack_bounds": again["meshes"][0]["uv_bounds"],
    "margined": margined["meshes"][0]["uv_bounds"],
    "bare_rect": [round(q, 6) for q in bare],
    # The DERIVED constant, not the module's historical literal: since
    # maya-mcp #635 it follows the scene's linear unit, because
    # polyAutoProjection sizes UVs from Maya's internal centimetres. Reading
    # the literal here is what let this eval pass for a metre scene and fail
    # for a centimetre one while the projection itself was fine.
    "uv_per_metre_constant": _uvatlas.autoproj_uv_per_metre(cmds),
    "scene_linear_unit": cmds.currentUnit(q=True, linear=True),
    "metre_cube_uv_extent": round(max(pbb[0][1] - pbb[0][0],
                                      pbb[1][1] - pbb[1][0]), 4),
    "density_big": round((bb_big[2] - bb_big[0]) / 3.0, 6),
    "density_small": round((bb_small[2] - bb_small[0]) / 0.5, 6),
    "big_fills_patch": round(bb_big[2] - bb_big[0], 6),
    "patch_width": round(_uvmath.patch_rect(4, 4, 0, 0, margin=0.0)[2], 6),
}
result
'''


def main():
    print("port %s" % os.environ.get("MAYA_MCP_PORT", "9878"))
    ok_resp(call("new_scene", {"confirm": True}, 300.0), "new_scene")

    c = run(COMBINE_CODE, "combine")
    print("\n-- combine ------------------------------------------------")
    check("three boxes become one object", c["survivors"], 0)
    check("each input survives as its own shell", c["shells"], 3)
    check("triangles are the sum of the inputs", c["tris"], 36)
    check("inputs reported", c["inputs"], 3)
    check("result is watertight", c["watertight"], True)
    check("no boundary edges", c["boundary_edges"], 0)
    check("scale frozen to 1,1,1", c["scale"], [1.0, 1.0, 1.0])
    check("pivot='origin' lands at the origin", c["pivot"], [0.0, 0.0, 0.0])
    check("exactly one shading group", c["sg_count"], 1)

    ok_resp(call("new_scene", {"confirm": True}, 300.0), "new_scene 2")
    u = run(UV_CODE, "uv_atlas")
    print("\n-- uv_atlas -----------------------------------------------")
    tol = 1e-4

    def near(a, b):
        return all(abs(x - y) <= tol for x, y in zip(a, b))

    check("cube lands exactly on the patch", u["cube_bounds"], u["rect"],
          ok=lambda g: near(g, u["rect"]))
    check("icosahedron lands on the SAME patch", u["ico_bounds"], u["rect"],
          ok=lambda g: near(g, u["rect"]))
    check("all_inside reported true", u["all_inside"], True)
    check("re-packing is stable", u["repack_bounds"], u["rect"],
          ok=lambda g: near(g, u["rect"]))
    check("margin insets off the patch edge", u["margined"], "inside bare rect",
          ok=lambda g: (g[0] > u["bare_rect"][0] + tol
                        and g[1] > u["bare_rect"][1] + tol
                        and g[2] < u["bare_rect"][2] - tol
                        and g[3] < u["bare_rect"][3] - tol))

    print("\n-- fixed texel density ------------------------------------")
    # A 1 m cube's auto-projected UV extent spans 3 face-widths across, so the
    # per-metre constant is that extent / 3.
    check("the projected UV extent matches the constant the tool derives "
          "for a %r scene" % u["scene_linear_unit"],
          round(u["metre_cube_uv_extent"] / 3.0, 3),
          u["uv_per_metre_constant"],
          ok=lambda g: abs(g - u["uv_per_metre_constant"])
          < max(1.0, u["uv_per_metre_constant"] * 0.01))
    # A box auto-projection lays six faces side by side, so a cube's UV bbox is
    # about THREE face-widths across, not one. That factor is the difference
    # between "512 px per patch" and "512 px across a 3 m face", so it is
    # measured and stated rather than assumed - assuming it is what made the
    # first family's texel density unknowable.
    factor = u["big_fills_patch"] / u["patch_width"]
    check("a cube's UV layout spans ~3 face-widths", round(factor, 3), "2.5-3.5",
          ok=lambda g: 2.5 <= g <= 3.5)
    check("0.5 m piece carries the SAME px/m as a 3 m piece",
          u["density_small"], u["density_big"],
          ok=lambda g: abs(g - u["density_big"]) <= 1e-4)

    passed = sum(1 for p, *_ in CHECKS if p)
    print("\n%d/%d checks green" % (passed, len(CHECKS)))
    sys.exit(0 if passed == len(CHECKS) else 1)


if __name__ == "__main__":
    main()
