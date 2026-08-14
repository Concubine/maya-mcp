"""A rotunda — a clean-slate subject after the brute (redmine #587).

The brute got measurably better and visually worse across five passes. Every
individual fix was correct; the figure still declined, because the fixes were
to things an instrument could see (exposure, opaque pixels, seam placement)
while the actual problems were things it could not: 57 chunks all at the same
dark value, no scale hierarchy, no focal point, a silhouette that got busier
with every pass. More tools produced more parts, not better seeing.

So this starts over with different discipline, on a subject with nothing in
common with a figure:

  FEW elements, LARGE. Twelve authored rows, not fifty-seven.
  VALUE CONTRAST. Pale limestone on a dark base - the brute was one dark mass,
      so its form had nothing to read against.
  ONE focal point. A single lit gem at the centre, and nothing else competing.
  Silhouette first. A dome and a colonnade read at any size; a knuckle stud
      does not.

The M2.4 features are load-bearing here rather than decorative, which is the
honest test of whether they were worth building:

  radial - a colonnade IS a radial array. Ten columns, one authored.
  flare  - column entasis is the textbook use: a classical column is wider at
           the foot and narrows upward along a slight convex curve. `curve`
           gives the swell, start/endFlare the taper. This shape was simply not
           expressible before M2.4.
  linear - the stepped base (a crepidoma) is one step plus a compounding run.

  mirror is NOT used. A rotunda is radially symmetric, so mirroring would be
  the wrong tool, and forcing it in to make the demo look complete would be
  dishonest about what the milestone is for.

Run:  set MAYA_MCP_PORT=9878 && .venv/Scripts/python.exe evals/rotunda.py r1
Artifacts: evals/rotunda/*.png
"""

from __future__ import annotations

import base64
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from live_call import call  # noqa: E402
from maya_mcp import images  # noqa: E402

OUT_DIR = os.path.join(_HERE, "rotunda")

# Limestone is deliberately BRIGHT. The brute's basalt sat at 0.16-0.27 and the
# whole figure read as one silhouette with highlights on it; there was no room
# between the darkest and lightest surface for shading to describe form. Stone
# at 0.70 leaves that room, and the dark base below it is what gives the
# building a base.
MATS = {
    "limestone": dict(baseColor=[0.74, 0.71, 0.64], roughness=0.76, specular=0.30),
    "shadowStone": dict(baseColor=[0.26, 0.25, 0.24], roughness=0.82, specular=0.25),
    "bronze": dict(baseColor=[0.60, 0.41, 0.18], metalness=0.70, roughness=0.34),
    # Transmissive AND self-lit: the facets still refract the colonnade behind
    # them, but the stone does not have to carry the light to it.
    "gemGlow": dict(baseColor=[0.45, 0.30, 0.03], transmission=0.55,
                    transmissionColor=[0.95, 0.78, 0.38], ior=1.55,
                    roughness=0.05, emission=1.5,
                    emissionColor=[1.0, 0.62, 0.18]),
}

# The four-wall surround from brute_v7: far enough out that no corner reaches
# any frame, and closed on every horizontal axis so a transmissive material
# always has something behind it to refract.
# Walls are deliberately much wider than the gap between them: pass 1 sized
# them to 500 across a 380 gap and a sliver of transparent background still
# showed at one corner seam. Overlap is free; a visible seam is not.
ENVIRONMENT = [
    ("ground", "plane", [0.0, 0.0, 0.0], [0, 0, 0], [700.0, 1.0, 700.0],
     dict(color=[0.17, 0.17, 0.19])),
    ("wallBack", "plane", [0.0, 150.0, -190.0], [90, 0, 0], [800.0, 1.0, 460.0],
     dict(color=[0.36, 0.37, 0.40])),
    ("wallFront", "plane", [0.0, 150.0, 190.0], [90, 0, 0], [800.0, 1.0, 460.0],
     dict(color=[0.36, 0.37, 0.40])),
    ("wallLeft", "plane", [-190.0, 150.0, 0.0], [90, 0, 90], [800.0, 1.0, 460.0],
     dict(color=[0.33, 0.34, 0.37])),
    ("wallRight", "plane", [190.0, 150.0, 0.0], [90, 0, 90], [800.0, 1.0, 460.0],
     dict(color=[0.33, 0.34, 0.37])),
]

# (name, kind, translate, rotate, scale, material)
# Everything on the centre axis. Twelve rows total, including the three array
# seeds below.
MASSES = [
    ("stylobate", "cylinder", [0.0, 1.45, 0.0], [0, 0, 0], [21.0, 0.5, 21.0], "limestone"),
    ("innerFloor", "cylinder", [0.0, 1.72, 0.0], [0, 0, 0], [17.5, 0.15, 17.5], "limestone"),
    ("architrave", "cylinder", [0.0, 10.15, 0.0], [0, 0, 0], [19.6, 1.0, 19.6], "limestone"),
    ("cornice",   "cylinder", [0.0, 10.95, 0.0], [0, 0, 0], [20.8, 0.6, 20.8], "limestone"),
    ("ceiling",   "cylinder", [0.0, 10.55, 0.0], [0, 0, 0], [19.4, 0.3, 19.4], "limestone"),
    ("finial",    "octahedron", [0.0, 17.6, 0.0], [0, 0, 0], [2.0, 3.2, 2.0], "bronze"),
    ("altar",     "cylinder", [0.0, 2.15, 0.0],  [0, 0, 0], [4.2, 1.0, 4.2], "shadowStone"),
    # The focal point, and the only saturated thing in the scene. The brute had
    # amber seams, amber eyes, an amber heart, bronze studs and purple crystals
    # all competing; nothing was the subject.
    # The focal point, and the only saturated thing in the scene.
    #
    # Two passes to get this visible, and the second failure is the instructive
    # one. Pass 1 was simply too small. Pass 2 enlarged it and stayed invisible
    # for a different reason: an EMISSIVE core sealed inside a TRANSMISSIVE
    # shell does not get its light out - the emitter has no path to the camera
    # that is not a refraction, and it read as a dark lump under a dome that
    # already shades it. The v6 brute's heart only worked because its ember sat
    # proud of the ruby rather than inside it.
    #
    # So the gem emits. One object, self-lit, no enclosure to escape.
    ("gem", "octahedron", [0.0, 4.6, 0.0], [0, 30, 0], [3.8, 5.2, 3.8], "gemGlow"),
]

# ------------------------------------------------------------------- arrays
# The crepidoma: one step, then a compounding run upward. step_scale < 1 shrinks
# each copy, so the stack narrows as it rises - which is what a stepped plinth
# is. Three steps from one row.
STEP_SEED = ("step", "cylinder", [0.0, 0.2, 0.0], [0, 0, 0],
             [26.0, 0.4, 26.0], "shadowStone")
STEP_ARRAY = dict(mode="linear", count=3, offset=[0.0, 0.4, 0.0],
                  step_scale=[0.93, 1.0, 0.93], name_prefix="step",
                  group_name="crepidoma")

# The colonnade. One column, ten of them. There is no radius parameter - the
# seed's own distance from the centre IS the radius, which is exactly the right
# model here: place one column where a column belongs, then ask for ten.
COLUMN_SEED = ("column", "cylinder", [8.3, 5.9, 0.0], [0, 0, 0],
               [1.85, 8.4, 1.85], "limestone")
COLUMN_FLARE = dict(startFlareX=1.06, startFlareZ=1.06,
                    endFlareX=0.80, endFlareZ=0.80, curve=0.42)
COLUMN_ARRAY = dict(mode="radial", count=10, axis="y", center=[0.0, 0.0, 0.0],
                    name_prefix="column", group_name="colonnade")

_built: list = []


def ok(resp, what):
    if resp.get("status") != "ok":
        print("FAILED %s: %s" % (what, json.dumps(resp.get("error", resp))[:400]))
        sys.exit(1)
    return resp["result"]


def material(mesh, mat):
    ok(call("assign_material", {
        "mesh": mesh, "shader": "standardSurface", "name": mat + "_mat",
        "params": MATS[mat]}, 60.0), "material %s on %s" % (mat, mesh))


def make(name, kind, translate, rotate, scale, divisions=None):
    params = {"kind": kind, "name": name, "translate": translate,
              "rotate": rotate, "scale": scale}
    if divisions is not None:
        params["divisions"] = divisions
    ok(call("create_primitive", params, 60.0), "create %s" % name)
    _built.append(name)
    return "|" + name


def build():
    ok(call("new_scene", {"confirm": True}, 180.0), "new_scene")

    for name, kind, translate, rotate, scale, color in ENVIRONMENT:
        ok(call("create_primitive", {
            "kind": kind, "name": name, "translate": translate,
            "rotate": rotate, "scale": scale}, 60.0), "create %s" % name)
        ok(call("assign_material", {
            "mesh": "|" + name, "shader": "lambert", "name": name + "_mat",
            "params": color}, 60.0), "material %s" % name)

    authored = 0
    for name, kind, translate, rotate, scale, mat in MASSES:
        material(make(name, kind, translate, rotate, scale), mat)
        authored += 1

    # The dome. A sphere is a WHOLE sphere, and its lower hemisphere hung down
    # inside the colonnade as a dark blob suspended over the altar. A ceiling
    # disc did not fix it: the ceiling sits at the springing line while the
    # hemisphere hangs well below, so it hid nothing from any view that looks
    # in between the columns. There is no hemisphere primitive, so cut one -
    # difference a cube occupying everything below the springing line.
    make("domeBall", "sphere", [0.0, 10.7, 0.0], [0, 0, 0], [18.0, 13.0, 18.0])
    make("domeCutter", "cube", [0.0, -5.3, 0.0], [0, 0, 0], [44.0, 32.0, 44.0])
    ok(call("boolean_op", {
        "a": "|domeBall", "b": "|domeCutter", "op": "difference",
        "new_name": "dome"}, 300.0), "cut the dome to a hemisphere")
    for consumed in ("domeBall", "domeCutter"):
        if consumed in _built:
            _built.remove(consumed)
    _built.append("dome")
    material("|dome", "limestone")

    # Steps.
    name, kind, translate, rotate, scale, mat = STEP_SEED
    seed = make(name, kind, translate, rotate, scale)
    material(seed, mat)
    authored += 1
    result = ok(call("array", dict(STEP_ARRAY, name=seed), 180.0), "step array")
    for copy in result["names"]:
        material(copy, mat)
        _built.append(copy.split("|")[-1])
    steps = len(result["names"])

    # The colonnade: flare the seed FIRST, then array it, so all ten inherit the
    # entasis from one deformation instead of ten.
    name, kind, translate, rotate, scale, mat = COLUMN_SEED
    seed = make(name, kind, translate, rotate, scale, divisions=2)
    ok(call("deform", {
        "mesh": seed, "deformer": "flare", "params": COLUMN_FLARE,
        "delete_history_after": True}, 180.0), "flare the column")
    material(seed, mat)
    authored += 1
    result = ok(call("array", dict(COLUMN_ARRAY, name=seed), 180.0), "colonnade")
    for copy in result["names"]:
        material(copy, mat)
        _built.append(copy.split("|")[-1])
    columns = len(result["names"])

    # Bright stone needs less light than dark stone did. The brute ran at 3.0
    # against basalt; the same intensity on limestone clips.
    ok(call("setup_lighting", {
        "preset": "three_point", "intensity": 2.1, "replace_existing": True},
        180.0), "setup_lighting")

    return authored, steps, columns


def render(label, angles, zoom=1.25, resolution=768, samples=4):
    result = ok(call("render_scene", {
        "angles": list(angles), "renderer": "arnold", "resolution": resolution,
        "samples": samples, "zoom": zoom, "target": list(_built)}, 900.0),
        "render %s" % label)
    os.makedirs(OUT_DIR, exist_ok=True)
    for shot in result["images"]:
        png = base64.b64decode(shot["png_b64"])
        path = os.path.join(OUT_DIR, "%s_%s.png" % (label, shot["angle"]))
        with open(path, "wb") as fh:
            fh.write(png)
        print("%-28s %s" % (os.path.basename(path),
                            json.dumps(images.pixel_stats(png))))


def organise():
    """Separate the BUILDING from the STUDIO, and say which is which.

    The four backdrop walls and the ground exist only so a render has a
    background and so transmissive materials have something behind them to
    refract. They are lighting equipment, not the model - but until now they
    sat loose in the same namespace as the rotunda, so opening the scene in
    Maya showed a 26-unit building apparently impaled by 800-unit walls with
    nothing to say which was which.

    Anything meant to leave this scene as an asset goes under |rotunda.
    Everything that is scaffolding goes under |studio, so it can be hidden or
    deleted in one action.
    """
    ok(call("group", {"names": ["|" + n for n in _built],
                      "group_name": "rotunda"}, 180.0), "group the building")
    ok(call("group", {"names": ["|" + n for n, _k, _t, _r, _s, _c in ENVIRONMENT],
                      "group_name": "studio"}, 180.0), "group the studio")


def export(fbx_path, scene_path):
    """Write the building alone to FBX, with the studio excluded."""
    ok(call("save_scene", {"path": scene_path}, 300.0), "save scene")
    code = (
        "import maya.cmds as cmds\n"
        "cmds.loadPlugin('fbxmaya', quiet=True)\n"
        "cmds.select('|rotunda', replace=True, hierarchy=True)\n"
        "cmds.file(r'%s', force=True, type='FBX export', pr=True, es=True)\n"
        "result = cmds.polyEvaluate('|rotunda', triangle=True)\n" % fbx_path
    )
    out = ok(call("execute_python", {"code": code}, 300.0), "export fbx")
    if out.get("traceback"):
        print("FBX EXPORT FAILED:\n%s" % out["traceback"][:600])
        sys.exit(1)
    print("exported %s (tris: %s)" % (os.path.basename(fbx_path),
                                      out.get("result_repr")))


if __name__ == "__main__":
    label = sys.argv[1] if len(sys.argv) > 1 else "r1"
    angles = sys.argv[2].split(",") if len(sys.argv) > 2 else ["three_quarter"]
    zoom = float(sys.argv[3]) if len(sys.argv) > 3 else 1.25
    authored, steps, columns = build()
    print("%d objects from %d authored rows (%d step copies, %d column copies)"
          % (len(_built), authored, steps, columns))
    render(label, angles, zoom)
    organise()
    if os.environ.get("ROTUNDA_EXPORT") == "1":
        os.makedirs(OUT_DIR, exist_ok=True)
        export(os.path.join(OUT_DIR, "rotunda.fbx"),
               os.path.join(OUT_DIR, "rotunda.ma"))
