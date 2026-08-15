"""The gem brute, rendered (redmine #585).

The art brief that produced #583 and #584: a hulking brute built out of gem
types. The original run came out correct in form and wrong in substance - it
read as painted faceted plastic - and every reason was a tool gap. This run
repeats it with those gaps closed: transmission/ior on standardSurface, faceted
primitives, material reuse (#583), and a render path that can actually SHOW
refraction (#584).

Built through the plugin's own tool commands rather than execute_python, so the
run exercises the API surface it is meant to judge. Primitive `scale` is read as
a size in units, which is only true since #584 normalised every kind to the same
unit box.

Run:  set MAYA_MCP_PORT=9878 && .venv/Scripts/python.exe evals/gem_brute_v5.py
Artifacts: evals/gem_brute_v5/*.png
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

OUT_DIR = os.path.join(_HERE, "gem_brute_v5")

# --------------------------------------------------------------- the materials
# One entry per gem; the same name is passed for every chunk wearing it, which
# #583 made reuse the shader instead of minting a variant per mesh.
# transmissionColor is an ABSORPTION tint, not a paint colour: light that gets
# through is multiplied by it, so a saturated value absorbs nearly everything
# and the gem renders as a dark solid. Study A used saturated tints and every
# coloured gem read as painted plastic - only the near-white diamond looked like
# a gem. These are pale tints with transmission at 1.0, which is what a real
# gem's absorption looks like over a few centimetres of stone.
GEMS = {
    "ruby": dict(baseColor=[0.35, 0.02, 0.05], transmission=1.0,
                 transmissionColor=[0.92, 0.32, 0.36], ior=1.77, roughness=0.03),
    "emerald": dict(baseColor=[0.02, 0.28, 0.14], transmission=1.0,
                    transmissionColor=[0.42, 0.90, 0.60], ior=1.58, roughness=0.04),
    "sapphire": dict(baseColor=[0.02, 0.06, 0.38], transmission=1.0,
                     transmissionColor=[0.42, 0.58, 0.95], ior=1.77, roughness=0.03),
    "amethyst": dict(baseColor=[0.22, 0.08, 0.38], transmission=1.0,
                     transmissionColor=[0.72, 0.52, 0.92], ior=1.54, roughness=0.05),
    "citrine": dict(baseColor=[0.45, 0.30, 0.03], transmission=1.0,
                    transmissionColor=[0.95, 0.78, 0.38], ior=1.55, roughness=0.04),
    "diamond": dict(baseColor=[0.85, 0.88, 0.92], transmission=0.95,
                    transmissionColor=[0.97, 0.98, 1.0], ior=2.42, roughness=0.02),
    # The anchors. A figure of nothing but transmissive gems has no silhouette:
    # every chunk shows what is behind it, so the shape dissolves. Obsidian and
    # pyrite are opaque on purpose - they are what makes the gems read AS gems.
    # 0.02 black reads as a hole rather than a stone once a chunk is only a few
    # dozen pixels across: there is no room for a highlight to describe the
    # form. Dark but not absent, with a hard polish, keeps the facets legible.
    "obsidian": dict(baseColor=[0.07, 0.07, 0.09], transmission=0.0,
                     roughness=0.10, metalness=0.0, specular=1.0),
    "pyrite": dict(baseColor=[0.85, 0.66, 0.22], transmission=0.0,
                   metalness=1.0, roughness=0.18),
}

# ----------------------------------------------------------------- the figure
# (name, kind, translate, rotate, scale, gem). Hulking proportions: wide chest,
# long heavy arms, short thick legs, small head.
CHUNKS = [
    # core column
    ("pelvis",     "octahedron",  [0.0, 4.1, 0.0],   [0, 22, 0],   [2.6, 1.7, 2.0], "obsidian"),
    ("belly",      "icosahedron", [0.0, 5.6, 0.1],   [12, 40, 8],  [2.7, 2.0, 2.2], "amethyst"),
    ("chest",      "octahedron",  [0.0, 7.6, 0.0],   [0, 18, 0],   [4.1, 2.9, 2.7], "obsidian"),
    ("collar",     "prism",       [0.0, 9.0, 0.1],   [0, 30, 0],   [3.6, 1.1, 2.2], "pyrite"),
    ("heart",      "octahedron",  [0.0, 7.5, 1.25],  [0, 45, 20],  [1.5, 1.9, 1.5], "ruby"),
    ("head",       "octahedron",  [0.0, 10.3, 0.05], [0, 35, 0],   [1.6, 1.9, 1.6], "diamond"),
    ("brow",       "pyramid",     [0.0, 10.5, 0.75], [-70, 0, 0],  [1.1, 0.9, 1.1], "citrine"),
    # shoulders and arms
    ("shoulderL",  "icosahedron", [3.0, 8.6, 0.0],   [10, 25, 15], [2.3, 2.1, 2.2], "sapphire"),
    ("shoulderR",  "icosahedron", [-3.0, 8.6, 0.0],  [10, -25, -15], [2.3, 2.1, 2.2], "sapphire"),
    ("upperArmL",  "octahedron",  [3.7, 6.5, 0.0],   [0, 0, -12],  [1.5, 2.8, 1.5], "emerald"),
    ("upperArmR",  "octahedron",  [-3.7, 6.5, 0.0],  [0, 0, 12],   [1.5, 2.8, 1.5], "emerald"),
    ("elbowL",     "octahedron",  [4.1, 4.9, 0.0],   [0, 45, 0],   [1.3, 1.2, 1.3], "pyrite"),
    ("elbowR",     "octahedron",  [-4.1, 4.9, 0.0],  [0, 45, 0],   [1.3, 1.2, 1.3], "pyrite"),
    ("forearmL",   "octahedron",  [4.4, 3.2, 0.1],   [0, 0, -8],   [1.7, 2.6, 1.7], "citrine"),
    ("forearmR",   "octahedron",  [-4.4, 3.2, 0.1],  [0, 0, 8],    [1.7, 2.6, 1.7], "citrine"),
    ("fistL",      "icosahedron", [4.7, 1.5, 0.2],   [15, 20, 0],  [2.0, 1.9, 2.0], "obsidian"),
    ("fistR",      "icosahedron", [-4.7, 1.5, 0.2],  [15, -20, 0], [2.0, 1.9, 2.0], "obsidian"),
    # legs
    ("thighL",     "octahedron",  [1.3, 2.7, 0.0],   [0, 0, 6],    [1.8, 2.3, 1.9], "sapphire"),
    ("thighR",     "octahedron",  [-1.3, 2.7, 0.0],  [0, 0, -6],   [1.8, 2.3, 1.9], "sapphire"),
    ("shinL",      "octahedron",  [1.4, 1.0, 0.0],   [0, 30, 0],   [1.6, 1.8, 1.7], "obsidian"),
    ("shinR",      "octahedron",  [-1.4, 1.0, 0.0],  [0, 30, 0],   [1.6, 1.8, 1.7], "obsidian"),
    ("footL",      "prism",       [1.5, 0.3, 0.45],  [0, 90, 0],   [2.2, 0.7, 1.7], "pyrite"),
    ("footR",      "prism",       [-1.5, 0.3, 0.45], [0, 90, 0],   [2.2, 0.7, 1.7], "pyrite"),
    # back crystal growth - the silhouette read from the side
    ("spineA",     "pyramid",     [0.0, 8.6, -1.5],  [55, 0, 0],   [1.5, 1.9, 1.5], "amethyst"),
    ("spineB",     "pyramid",     [0.9, 7.2, -1.5],  [60, 25, 12], [1.2, 1.6, 1.2], "amethyst"),
    ("spineC",     "pyramid",     [-0.9, 7.2, -1.5], [60, -25, -12], [1.2, 1.6, 1.2], "amethyst"),
    ("spineD",     "pyramid",     [0.0, 6.0, -1.4],  [65, 45, 0],  [1.0, 1.3, 1.0], "ruby"),
]

# Environment. A transmissive material shows what is BEHIND it, so with nothing
# behind it there is nothing to refract and a gem renders as a dark lump.
#
# The sizes here are a WORKAROUND, not a design: render_scene frames every
# visible object, and `isolate` controls framing and visibility together, so
# there is no way to say "frame the figure, keep the room". v5 pass 1 rendered
# the brute at about a tenth of frame height because a 26-unit backdrop
# out-voted it. Keeping the room barely larger than the figure is the only
# lever available - see the #585 findings.
ENVIRONMENT = [
    # Bright, and deliberately so: a transmissive material is only as visible as
    # what is behind it. Against a dark room every gem renders as a black lump
    # whatever its transmissionColor says - v6 proved that as clearly as v5
    # proved the opposite at the over-exposed end.
    ("ground", "plane", [0.0, 0.0, 0.0], [0, 0, 0], [13.0, 1.0, 13.0],
     dict(color=[0.42, 0.43, 0.46])),
    ("backdrop", "plane", [0.0, 6.0, -5.5], [90, 0, 0], [13.0, 1.0, 12.0],
     dict(color=[0.78, 0.79, 0.82])),
]


def ok(resp, what):
    if resp.get("status") != "ok":
        print("FAILED %s: %s" % (what, json.dumps(resp.get("error", resp))[:400]))
        sys.exit(1)
    return resp["result"]


def build():
    ok(call("new_scene", {"confirm": True}, 120.0), "new_scene")

    for name, kind, translate, rotate, scale, color in ENVIRONMENT:
        ok(call("create_primitive", {
            "kind": kind, "name": name, "translate": translate,
            "rotate": rotate, "scale": scale}, 60.0), "create %s" % name)
        ok(call("assign_material", {
            "mesh": "|" + name, "shader": "lambert", "name": name + "_mat",
            "params": color}, 60.0), "material %s" % name)

    for name, kind, translate, rotate, scale, gem in CHUNKS:
        ok(call("create_primitive", {
            "kind": kind, "name": name, "translate": translate,
            "rotate": rotate, "scale": scale}, 60.0), "create %s" % name)
        ok(call("assign_material", {
            "mesh": "|" + name, "shader": "standardSurface", "name": gem + "_mat",
            "params": GEMS[gem]}, 60.0), "material %s on %s" % (gem, name))

    # Pass 1 at 14 blew every surface to flat saturated primaries - the exact
    # "painted plastic" read the original run was criticised for, this time
    # caused by exposure rather than by the material model.
    # 7.0/pi: the pre-#617 number, in the new unit - same pixels as before
    ok(call("setup_lighting", {
        "preset": "three_point", "intensity": 2.2282, "replace_existing": True},
        120.0), "setup_lighting")


def render(label, angles=("three_quarter",), resolution=640, samples=4):
    result = ok(call("render_scene", {
        "angles": list(angles), "renderer": "arnold",
        "resolution": resolution, "samples": samples}, 600.0), "render %s" % label)
    os.makedirs(OUT_DIR, exist_ok=True)
    for shot in result["images"]:
        png = base64.b64decode(shot["png_b64"])
        path = os.path.join(OUT_DIR, "%s_%s.png" % (label, shot["angle"]))
        with open(path, "wb") as fh:
            fh.write(png)
        print("%-28s %s" % (os.path.basename(path), json.dumps(images.pixel_stats(png))))


# ----------------------------------------------------------- material study
# The figure cannot answer "does a gem look like a gem": each chunk is about 40
# pixels across in a full-body frame, and render_scene has no zoom, no framing
# target, and no way to isolate for FRAMING without also hiding the backdrop
# that a transmissive material needs behind it. So the material question gets
# its own scene, at a size where it is actually answerable.
STUDY = [
    ("studyRuby", "octahedron", [-4.5, 3.0, 0.0], [0, 25, 0], [3.4, 4.0, 3.4], "ruby"),
    ("studyEmerald", "prism", [-1.5, 3.0, 0.0], [0, 15, 0], [3.0, 4.2, 3.0], "emerald"),
    ("studyDiamond", "icosahedron", [1.5, 3.0, 0.0], [15, 30, 0], [3.4, 3.4, 3.4], "diamond"),
    ("studySapphire", "octahedron", [4.5, 3.0, 0.0], [0, 45, 20], [3.4, 4.0, 3.4], "sapphire"),
    # An opaque control in the same frame. Without one, "it looks like a gem"
    # has nothing to be true relative to - this is the pair the original run
    # could not tell apart in the viewport.
    ("studyOpaqueRed", "octahedron", [0.0, 7.6, -1.0], [0, 25, 0], [2.6, 3.0, 2.6],
     "painted"),
]

STUDY_ENV = [
    ("studyGround", "plane", [0.0, 0.0, 0.0], [0, 0, 0], [16.0, 1.0, 10.0],
     dict(color=[0.32, 0.33, 0.36])),
    ("studyBackdrop", "plane", [0.0, 5.0, -4.0], [90, 0, 0], [16.0, 1.0, 10.0],
     dict(color=[0.72, 0.73, 0.76])),
    # Something with structure to refract: a flat field bends into a flat field,
    # so a gem in front of plain grey looks like plain grey.
    ("studyBarA", "cube", [-6.0, 4.0, -3.6], [0, 0, 0], [1.2, 8.0, 0.4],
     dict(color=[0.85, 0.25, 0.10])),
    ("studyBarB", "cube", [0.0, 4.0, -3.6], [0, 0, 0], [1.2, 8.0, 0.4],
     dict(color=[0.10, 0.55, 0.85])),
    ("studyBarC", "cube", [6.0, 4.0, -3.6], [0, 0, 0], [1.2, 8.0, 0.4],
     dict(color=[0.95, 0.80, 0.15])),
]


def build_study():
    ok(call("new_scene", {"confirm": True}, 120.0), "new_scene")
    for name, kind, translate, rotate, scale, color in STUDY_ENV:
        ok(call("create_primitive", {
            "kind": kind, "name": name, "translate": translate,
            "rotate": rotate, "scale": scale}, 60.0), "create %s" % name)
        ok(call("assign_material", {
            "mesh": "|" + name, "shader": "lambert", "name": name + "_mat",
            "params": color}, 60.0), "material %s" % name)

    gems = dict(GEMS)
    # The control: the ruby's colour with transmission switched off - i.e.
    # exactly what the whole toolset could produce before #583.
    gems["painted"] = dict(baseColor=[0.42, 0.03, 0.06], transmission=0.0,
                           roughness=0.12, specular=1.0)
    for name, kind, translate, rotate, scale, gem in STUDY:
        ok(call("create_primitive", {
            "kind": kind, "name": name, "translate": translate,
            "rotate": rotate, "scale": scale}, 60.0), "create %s" % name)
        ok(call("assign_material", {
            "mesh": "|" + name, "shader": "standardSurface", "name": gem + "_mat",
            "params": gems[gem]}, 60.0), "material %s on %s" % (gem, name))

    # 4.0/pi: the pre-#617 number, in the new unit - same pixels as before
    ok(call("setup_lighting", {
        "preset": "three_point", "intensity": 1.2732, "replace_existing": True},
        120.0), "setup_lighting")


if __name__ == "__main__":
    label = sys.argv[1] if len(sys.argv) > 1 else "v5"
    angles = sys.argv[2].split(",") if len(sys.argv) > 2 else ["three_quarter"]
    mode = os.environ.get("GEM_BRUTE_MODE", "figure")
    if os.environ.get("GEM_BRUTE_SKIP_BUILD") != "1":
        if mode == "study":
            build_study()
            print("built material study: %d gems + %d environment"
                  % (len(STUDY), len(STUDY_ENV)))
        else:
            build()
            print("built: %d chunks + %d environment"
                  % (len(CHUNKS), len(ENVIRONMENT)))
    render(label, angles)
