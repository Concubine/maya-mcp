"""A shippable structure library — four buildings, pre-chunked for destruction.

Built to be handed to another project as an asset package rather than admired
in a render. Each structure is a group of SEPARATE CLOSED MESHES, because the
consuming game's building model is "pre-chunked buildings out of structural
pieces" - so the chunks are the destruction units, and they are named for what
they are rather than for the order they were made in.

Four structures, chosen for different silhouettes, footprints and collapse
behaviour rather than for variety's own sake:

  rotunda      round, low and wide. Kill the columns, the dome drops.
  water_tower  tall and thin on splayed legs. Kill a leg, it topples.
  clock_tower  tall and square, tapering. Topples as one piece, or shears at a
               string course.
  gate         wide and spanning. Kill a pier and the arch above it falls -
               the only one whose failure is not straight down.

Each leans on a different tool, which is the honest test of whether the
toolset covers a range rather than one trick:

  rotunda      radial colonnade + flare entasis + linear steps
  water_tower  radial legs + flare tank + linear bands
  clock_tower  flare taper + linear string courses + radial clock faces
  gate         mirror piers + radial voussoir arch (a 180-degree ARC, where
               the spacing rule puts an element on each springing point)

Design discipline, learned the hard way on an earlier subject that got
measurably better and visually worse across five passes: FEW elements and
LARGE, value contrast so form has something to read against, one focal point,
and judge the silhouette before any detail.

Run:  set MAYA_MCP_PORT=9878 && .venv/Scripts/python.exe evals/structures.py
Package: evals/structures/  (fbx + ma + png + manifest.json + README.md)
"""

from __future__ import annotations

import ast
import base64
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from live_call import call  # noqa: E402
from maya_mcp import images  # noqa: E402

OUT_DIR = os.path.join(_HERE, "structures")

# One palette across the library, so four structures read as one set. Values
# are chosen for CONTRAST first: pale stone needs a dark base under it or the
# whole silhouette flattens into a single mass.
MATS = {
    "limestone": dict(baseColor=[0.74, 0.71, 0.64], roughness=0.76, specular=0.30),
    "shadowStone": dict(baseColor=[0.26, 0.25, 0.24], roughness=0.82, specular=0.25),
    "brick": dict(baseColor=[0.42, 0.26, 0.20], roughness=0.85, specular=0.20),
    "iron": dict(baseColor=[0.34, 0.35, 0.38], metalness=0.68, roughness=0.58),
    "bronze": dict(baseColor=[0.60, 0.41, 0.18], metalness=0.70, roughness=0.34),
    "glow": dict(baseColor=[0.45, 0.30, 0.03], transmission=0.55,
                 transmissionColor=[0.95, 0.78, 0.38], ior=1.55, roughness=0.05,
                 emission=1.5, emissionColor=[1.0, 0.62, 0.18]),
}

# The studio: four walls far enough out that no corner reaches any frame, and
# closed on every horizontal axis so transmissive materials always have
# something behind them. It is lighting equipment, not model, and it is grouped
# separately and excluded from every export.
STUDIO = [
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


def make(name, kind, translate, rotate, scale, mat, divisions=None):
    params = {"kind": kind, "name": name, "translate": translate,
              "rotate": rotate, "scale": scale}
    if divisions is not None:
        params["divisions"] = divisions
    ok(call("create_primitive", params, 60.0), "create %s" % name)
    _built.append(name)
    material("|" + name, mat)
    return "|" + name


def flare(mesh, **params):
    ok(call("deform", {"mesh": mesh, "deformer": "flare", "params": params,
                       "delete_history_after": True}, 180.0), "flare %s" % mesh)
    return mesh


def array(mesh, mat, **spec):
    result = ok(call("array", dict(spec, name=mesh), 240.0),
                "%s array on %s" % (spec.get("mode"), mesh))
    for copy in result["names"]:
        material(copy, mat)
        _built.append(copy.split("|")[-1])
    if spec.get("mode") == "mirror":
        volume = result.get("signed_volume")
        if volume is None or volume <= 0.0:
            print("  WINDING PROBLEM mirroring %s: signed_volume=%s warnings=%s"
                  % (mesh, volume, result.get("warnings")))
            sys.exit(1)
    return result["names"]


# ============================================================== the structures
# Each returns nothing; it appends to _built. Every one is built with its base
# at y=0 and centred on x=z=0, so the group pivot lands where a placement tool
# would want it: the centre of the footprint, on the ground.

def rotunda():
    """Round, low and wide. Kill the columns and the dome drops."""
    make("stylobate", "cylinder", [0.0, 1.45, 0.0], [0, 0, 0], [21.0, 0.5, 21.0], "limestone")
    make("innerFloor", "cylinder", [0.0, 1.72, 0.0], [0, 0, 0], [17.5, 0.15, 17.5], "limestone")
    make("architrave", "cylinder", [0.0, 10.15, 0.0], [0, 0, 0], [19.6, 1.0, 19.6], "limestone")
    make("cornice", "cylinder", [0.0, 10.95, 0.0], [0, 0, 0], [20.8, 0.6, 20.8], "limestone")
    make("finial", "octahedron", [0.0, 17.6, 0.0], [0, 0, 0], [2.0, 3.2, 2.0], "bronze")
    make("altar", "cylinder", [0.0, 2.15, 0.0], [0, 0, 0], [4.2, 1.0, 4.2], "shadowStone")
    make("gem", "octahedron", [0.0, 4.6, 0.0], [0, 30, 0], [3.8, 5.2, 3.8], "glow")

    # A sphere is a whole sphere - its lower hemisphere hangs down inside the
    # colonnade as a dark blob over the altar, and a ceiling disc does not hide
    # it because the ceiling sits at the springing line while the hemisphere
    # hangs well below. Cut a real hemisphere.
    make("domeBall", "sphere", [0.0, 10.7, 0.0], [0, 0, 0], [18.0, 13.0, 18.0], "limestone")
    make("domeCutter", "cube", [0.0, -5.3, 0.0], [0, 0, 0], [44.0, 32.0, 44.0], "limestone")
    ok(call("boolean_op", {"a": "|domeBall", "b": "|domeCutter",
                           "op": "difference", "new_name": "dome"}, 300.0), "cut dome")
    for consumed in ("domeBall", "domeCutter"):
        _built.remove(consumed)
    _built.append("dome")
    material("|dome", "limestone")

    step = make("step_base", "cylinder", [0.0, 0.2, 0.0], [0, 0, 0], [26.0, 0.4, 26.0], "shadowStone")
    array(step, "shadowStone", mode="linear", count=3, offset=[0.0, 0.4, 0.0],
          step_scale=[0.93, 1.0, 0.93], name_prefix="step")

    column = make("column", "cylinder", [8.3, 5.9, 0.0], [0, 0, 0], [1.85, 8.4, 1.85],
                  "limestone", divisions=2)
    flare(column, startFlareX=1.06, startFlareZ=1.06,
          endFlareX=0.80, endFlareZ=0.80, curve=0.42)
    array(column, "limestone", mode="radial", count=10, axis="y",
          center=[0.0, 0.0, 0.0], name_prefix="column")


def water_tower():
    """Tall and thin on splayed legs. Kill a leg and it topples sideways."""
    make("footing", "cylinder", [0.0, 0.35, 0.0], [0, 0, 0], [11.0, 0.7, 11.0], "shadowStone")
    make("platform", "cylinder", [0.0, 12.4, 0.0], [0, 0, 0], [10.4, 0.5, 10.4], "iron")
    make("tankFloor", "cone", [0.0, 13.6, 0.0], [180, 0, 0], [9.0, 2.4, 9.0], "iron")

    # The tank: a cylinder flared WIDER at the top, so the vessel reads as a
    # held volume rather than a pipe. Straight-sided would be a silo.
    tank = make("tank", "cylinder", [0.0, 18.4, 0.0], [0, 0, 0], [9.4, 8.0, 9.4],
                "iron", divisions=2)
    flare(tank, startFlareX=0.90, startFlareZ=0.90,
          endFlareX=1.05, endFlareZ=1.05, curve=0.22)

    make("tankRoof", "cone", [0.0, 24.0, 0.0], [0, 0, 0], [10.2, 3.4, 10.2], "iron")
    make("vent", "cylinder", [0.0, 26.4, 0.0], [0, 0, 0], [1.2, 2.0, 1.2], "bronze")
    make("beacon", "octahedron", [0.0, 28.0, 0.0], [0, 0, 0], [1.5, 2.0, 1.5], "glow")

    # Hoop bands up the tank. step_scale is 1.0 here on purpose: the bands
    # follow a flared wall, so shrinking them would peel them off it.
    band = make("band_base", "torus", [0.0, 15.6, 0.0], [0, 0, 0], [9.9, 0.5, 9.9], "bronze")
    array(band, "bronze", mode="linear", count=4, offset=[0.0, 1.9, 0.0],
          name_prefix="band")

    # Four splayed legs. The lean is authored once on the seed; the radial
    # array carries it round, which is the whole point of rotating the source
    # rather than placing copies on a ring.
    leg = make("leg", "cylinder", [5.6, 6.2, 0.0], [0, 0, 7], [1.5, 12.4, 1.5], "iron")
    array(leg, "iron", mode="radial", count=4, axis="y", center=[0.0, 0.0, 0.0],
          name_prefix="leg")

    brace = make("brace", "torus", [0.0, 6.6, 0.0], [0, 0, 0], [11.6, 0.45, 11.6], "iron")
    del brace


def clock_tower():
    """Tall and square, tapering. Topples whole, or shears at a string course."""
    make("plinth", "cube", [0.0, 1.1, 0.0], [0, 0, 0], [13.0, 2.2, 13.0], "shadowStone")

    # The taper is the silhouette. A straight square shaft reads as a chimney;
    # a tapered one reads as a tower, and taper is the thing that was not
    # expressible before this milestone.
    shaft = make("shaft", "cube", [0.0, 13.0, 0.0], [0, 0, 0], [10.4, 22.0, 10.4],
                 "brick", divisions=4)
    flare(shaft, startFlareX=1.04, startFlareZ=1.04,
          endFlareX=0.80, endFlareZ=0.80, curve=0.18)

    make("belfry", "cube", [0.0, 25.6, 0.0], [0, 0, 0], [11.4, 4.0, 11.4], "limestone")
    make("belfryCap", "cube", [0.0, 27.9, 0.0], [0, 0, 0], [12.6, 0.7, 12.6], "limestone")
    make("roof", "pyramid", [0.0, 31.4, 0.0], [0, 0, 0], [12.0, 6.4, 12.0], "iron")
    make("spike", "octahedron", [0.0, 35.6, 0.0], [0, 0, 0], [1.2, 3.0, 1.2], "bronze")
    make("bell", "cone", [0.0, 25.4, 0.0], [180, 0, 0], [4.0, 3.4, 4.0], "bronze")

    # String courses: bands up a TAPERING shaft, so they compound down slightly
    # to stay flush with the wall they belt. This is the case step_scale exists
    # for - four hand-tuned rows would drift off the taper.
    course = make("course_base", "cube", [0.0, 4.4, 0.0], [0, 0, 0], [11.0, 0.55, 11.0], "limestone")
    array(course, "limestone", mode="linear", count=5, offset=[0.0, 4.5, 0.0],
          step_scale=[0.962, 1.0, 0.962], name_prefix="course")

    # Four clock faces, one authored. A radial array about Y puts one on each
    # elevation and orients each to its own wall.
    face = make("clockFace", "cylinder", [0.0, 24.0, 5.9], [90, 0, 0], [5.6, 0.5, 5.6], "limestone")
    array(face, "limestone", mode="radial", count=4, axis="y",
          center=[0.0, 0.0, 0.0], name_prefix="clockFace")
    dial = make("clockDial", "cylinder", [0.0, 24.0, 6.15], [90, 0, 0], [4.2, 0.3, 4.2], "glow")
    array(dial, "glow", mode="radial", count=4, axis="y",
          center=[0.0, 0.0, 0.0], name_prefix="clockDial")


def gate():
    """Wide and spanning. Kill a pier and the arch above it comes down."""
    make("roadbed", "cube", [0.0, 0.25, 0.0], [0, 0, 0], [30.0, 0.5, 12.0], "shadowStone")

    # One pier, authored on the left, then reflected. Nothing about the right
    # pier is typed, so the two cannot disagree - which for a symmetric
    # structure is a correctness property, not a convenience.
    for name, kind, translate, rotate, scale, mat in (
        ("pierPlinth", "cube", [-9.4, 1.1, 0.0], [0, 0, 0], [7.4, 1.6, 9.4], "shadowStone"),
        ("pier", "cube", [-9.4, 7.4, 0.0], [0, 0, 0], [6.4, 11.2, 8.4], "limestone"),
        ("pierCap", "cube", [-9.4, 13.4, 0.0], [0, 0, 0], [7.6, 1.0, 9.4], "limestone"),
    ):
        mesh = make(name, kind, translate, rotate, scale, mat)
        array(mesh, mat, mode="mirror", axis="x", pivot=[0.0, 0.0, 0.0],
              name_prefix=name + "_R")

    make("entablature", "cube", [0.0, 20.6, 0.0], [0, 0, 0], [26.0, 2.6, 9.8], "limestone")
    make("attic", "cube", [0.0, 22.8, 0.0], [0, 0, 0], [21.0, 2.0, 8.4], "limestone")
    make("inscription", "cube", [0.0, 22.8, 4.3], [0, 0, 0], [13.0, 1.2, 0.4], "bronze")
    make("lamp", "octahedron", [0.0, 25.0, 0.0], [0, 0, 0], [1.8, 2.4, 1.8], "glow")

    # The arch ring, and the clearest case for the ARC half of the radial
    # spacing rule. A 180-degree sweep of 9 voussoirs divides by count-1, so
    # the first and last land exactly on the two springing points where the
    # arch meets its piers - which is where an arch must be closed. A full-ring
    # rule (divide by count) would leave both ends floating.
    voussoir = make("voussoir", "cube", [-7.9, 13.9, 0.0], [0, 0, 0],
                    [3.4, 2.6, 8.6], "limestone")
    array(voussoir, "limestone", mode="radial", count=9, axis="z", angle=-180.0,
          center=[0.0, 13.9, 0.0], name_prefix="voussoir")


STRUCTURES = [
    ("rotunda", rotunda, 1.75),
    ("water_tower", water_tower, 1.5),
    ("clock_tower", clock_tower, 1.5),
    ("gate", gate, 1.6),
]


# =================================================================== packaging

def build_studio():
    for name, kind, translate, rotate, scale, color in STUDIO:
        ok(call("create_primitive", {
            "kind": kind, "name": name, "translate": translate,
            "rotate": rotate, "scale": scale}, 60.0), "create %s" % name)
        ok(call("assign_material", {
            "mesh": "|" + name, "shader": "lambert", "name": name + "_mat",
            "params": color}, 60.0), "material %s" % name)


def render(label, zoom):
    result = ok(call("render_scene", {
        "angles": ["three_quarter"], "renderer": "arnold", "resolution": 768,
        "samples": 4, "zoom": zoom, "target": list(_built)}, 900.0),
        "render %s" % label)
    shot = result["images"][0]
    png = base64.b64decode(shot["png_b64"])
    path = os.path.join(OUT_DIR, "%s.png" % label)
    with open(path, "wb") as fh:
        fh.write(png)
    return images.pixel_stats(png)


def organise_and_export(label):
    """Group subject and studio apart, then export the subject alone.

    The studio walls are 800 units across and the buildings are 15-35; loose in
    one namespace they read, correctly, as a wall driven through the model.
    Anything that ships goes under |<label>; scaffolding goes under |studio.
    """
    ok(call("group", {"names": ["|" + n for n in _built],
                      "group_name": label}, 240.0), "group %s" % label)
    ok(call("group", {"names": ["|" + n for n, _k, _t, _r, _s, _c in STUDIO],
                      "group_name": "studio"}, 240.0), "group studio")

    fbx = os.path.join(OUT_DIR, "%s.fbx" % label).replace("\\", "/")
    scene = os.path.join(OUT_DIR, "%s.ma" % label).replace("\\", "/")
    ok(call("save_scene", {"path": scene}, 300.0), "save %s" % label)

    code = (
        "import maya.cmds as cmds\n"
        "cmds.loadPlugin('fbxmaya', quiet=True)\n"
        "cmds.select('|%s', replace=True, hierarchy=True)\n"
        "cmds.file(r'%s', force=True, type='FBX export', pr=True, es=True)\n"
        "chunks = cmds.listRelatives('|%s', children=True, fullPath=True) or []\n"
        "bb = cmds.exactWorldBoundingBox('|%s')\n"
        # polyEvaluate handed a GROUP returns a status string, not a count -
        # it counts meshes, not hierarchies. Sum over the mesh shapes instead.
        "shapes = cmds.listRelatives('|%s', allDescendents=True, type='mesh',\n"
        "                            fullPath=True) or []\n"
        "info = {'chunks': len(chunks),\n"
        "        'tris': sum(cmds.polyEvaluate(s, triangle=True) for s in shapes),\n"
        "        'bbox_min': [round(v, 3) for v in bb[:3]],\n"
        "        'bbox_max': [round(v, 3) for v in bb[3:]],\n"
        "        'names': sorted(c.split('|')[-1] for c in chunks)}\n"
        # execute_python reports the repr of a trailing EXPRESSION; an
        # assignment is not one, so the dict has to be named again on its own
        # line or result_repr comes back None.
        "info\n"
        % (label, fbx, label, label, label)
    )
    out = ok(call("execute_python", {"code": code}, 300.0), "export %s" % label)
    if out.get("traceback"):
        print("EXPORT FAILED for %s:\n%s" % (label, out["traceback"][:700]))
        sys.exit(1)
    return ast.literal_eval(out["result_repr"])


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    manifest = {"units": "maya default (cm); 1 unit = 1 metre if imported at 100x",
                "convention": "each structure is a group of separate closed "
                              "meshes; origin is the centre of the footprint at "
                              "ground level (y=0); +Y up; no construction history",
                "structures": []}

    for label, builder, zoom in STRUCTURES:
        del _built[:]
        ok(call("new_scene", {"confirm": True}, 180.0), "new_scene")
        build_studio()
        # 2.1/pi: the pre-#617 number, in the new unit - same pixels as before
        builder()
        ok(call("setup_lighting", {"preset": "three_point", "intensity": 0.6685,
                                   "replace_existing": True}, 180.0), "lighting")
        stats = render(label, zoom)
        info = organise_and_export(label)
        size = [round(info["bbox_max"][i] - info["bbox_min"][i], 2) for i in range(3)]
        entry = dict(name=label, chunks=info["chunks"], tris=info["tris"],
                     size_whd=size, bbox_min=info["bbox_min"],
                     bbox_max=info["bbox_max"], chunk_names=info["names"],
                     files=["%s.fbx" % label, "%s.ma" % label, "%s.png" % label])
        manifest["structures"].append(entry)
        print("%-12s %2d chunks  %6d tris  %sm  render %s"
              % (label, info["chunks"], info["tris"], size,
                 json.dumps({k: stats[k] for k in ("opaque_px", "clipped_fraction")})))

    manifest["materials"] = {
        name: dict(baseColor=params.get("baseColor"),
                   roughness=params.get("roughness"),
                   metalness=params.get("metalness", 0.0),
                   emissive=bool(params.get("emission")))
        for name, params in MATS.items()
    }
    with open(os.path.join(OUT_DIR, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)
    print("\nwrote %s" % os.path.join(OUT_DIR, "manifest.json"))


if __name__ == "__main__":
    main()
