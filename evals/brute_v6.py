"""The brute, rebuilt (redmine #587) — the M2.4 baseline.

The #585 gem brute was a figure made entirely of gems, and its verdict was that
the materials passed and the FORM did not: every chunk was a primitive with a
scale and a rotation, so the figure read as a pile of stretched solids however
correct the shading was.

This run answers a narrower question: with everything M2.2/M2.3 added — a real
render path, `target`/`zoom` framing, camera-following relight, measured
exposure — and with gems used as *accents on a stone body* rather than as the
whole figure, how far can the current toolset actually get?

It is deliberately built BEFORE M2.4 (arrays + flare), so the same subject can be
rebuilt afterwards and the difference is the milestone's evidence. What is
missing here is visible in the source: every left/right pair is two hand-typed
rows, and no limb tapers.

What IS new versus v5:
  - stone body / metal plate / gem accent, instead of all-gem
  - emissive seams (kiln glow), which the material whitelist already supported
    and no run had used
  - smooth + displace_noise on the load-bearing stone chunks, which is the one
    lever that exists today against the untouched-primitive read
  - target + zoom framing, so the figure fills the frame instead of a tenth of it

Run:  set MAYA_MCP_PORT=9878 && .venv/Scripts/python.exe evals/brute_v6.py v6
Artifacts: evals/brute_v6/*.png
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

OUT_DIR = os.path.join(_HERE, "brute_v6")

# ------------------------------------------------------------------ materials
# Three families. The stone carries the silhouette, the metal carries the
# highlights, the gems carry the eye — in that order of area. The #585 lesson
# that transmissionColor is an ABSORPTION tint (pale, with transmission at 1.0)
# still applies to the three gems.
MATS = {
    # Pass 1 ran these at 0.085/0.20 and the figure was a black mass with a
    # blown-white room behind it. Stone that dark has no room left for shading
    # to describe form once the exposure is correct.
    "basalt": dict(baseColor=[0.195, 0.186, 0.200], roughness=0.72, specular=0.50),
    "granite": dict(baseColor=[0.27, 0.250, 0.235], roughness=0.66, specular=0.45),
    # FINDING (pass 1): metalness=1.0 renders BLACK in a three-point rig. A
    # full metal has no diffuse response at all - every pixel it shows is a
    # reflection of the environment, and this scene has no environment to
    # reflect, only three point lights that produce a highlight and nothing
    # else. The pauldrons and collar came out as black wedges. Pulling
    # metalness back to ~0.7 restores enough diffuse for the form to read;
    # the real fix is an environment/skydome, which no tool exposes yet.
    # Polished metal facing a key light head-on returns a near-white plate with
    # no gradient across it, so a flat plate of it reads as paper. Rough metal
    # spreads the highlight and the form comes back.
    "iron": dict(baseColor=[0.38, 0.39, 0.42], metalness=0.68, roughness=0.58),
    "bronze": dict(baseColor=[0.62, 0.42, 0.19], metalness=0.70, roughness=0.38),
    # The kiln glow. Industrial warning amber, per the Demigol art direction.
    # emission multiplies emissionColor; pass 1 ran 6/11 and the seams read as
    # flat yellow paint because they were clipped solid across their whole area.
    "seam": dict(baseColor=[0.05, 0.03, 0.02], emission=2.6,
                 emissionColor=[1.0, 0.52, 0.08], roughness=0.5),
    "ember": dict(baseColor=[0.05, 0.03, 0.02], emission=6.0,
                  emissionColor=[1.0, 0.66, 0.22], roughness=0.5),
    # The accents. Three gem types, used on six small chunks out of forty.
    "ruby": dict(baseColor=[0.35, 0.02, 0.05], transmission=1.0,
                 transmissionColor=[0.92, 0.32, 0.36], ior=1.77, roughness=0.03),
    "citrine": dict(baseColor=[0.45, 0.30, 0.03], transmission=1.0,
                    transmissionColor=[0.95, 0.78, 0.38], ior=1.55, roughness=0.04),
    "amethyst": dict(baseColor=[0.22, 0.08, 0.38], transmission=1.0,
                     transmissionColor=[0.72, 0.52, 0.92], ior=1.54, roughness=0.05),
}

# -------------------------------------------------------------------- the figure
# (name, kind, translate, rotate, scale, material, rough)
# `rough` runs smooth+displace_noise: the boulder treatment. It costs triangles,
# so it goes on the chunks that carry the silhouette, not on plates or gems.
#
# EVERY LEFT/RIGHT PAIR BELOW IS TWO HAND-TYPED ROWS. That is the M2.4 exhibit:
# fourteen rows here are a mirror the toolset cannot express, and nothing checks
# that the negated row matches its twin.
CHUNKS = [
    # ---- core column -------------------------------------------------------
    ("pelvis",   "cube",        [0.0, 3.85, 0.0],  [0, 16, 0],  [3.1, 1.9, 2.5], "granite", True),
    ("belly",    "cube",        [0.0, 5.35, 0.05], [0, -11, 0], [3.3, 1.9, 2.6], "basalt", True),
    ("chest",    "cube",        [0.0, 7.35, 0.0],  [0, 9, 0],   [4.7, 2.8, 3.1], "basalt", True),
    # Seams must sit INSIDE the silhouette of the chunks they join. Pass 1 sized
    # them flush with the widest neighbour, so at any rotation offset they poked
    # out and read as flat yellow slabs laid across the body rather than as light
    # escaping from between two stones.
    # Pass 2 sized these against each neighbour's DECLARED width and they still
    # protruded, because `smooth` rounds a cube's corners: a chunk's actual
    # cross-section near its bottom face is far narrower than its declared
    # width, and a seam plate is by definition at exactly that height. Measured,
    # not guessed - the declared-vs-actual probe showed the seam narrower than
    # both neighbours' bounding boxes while visibly sticking out of both.
    # Discs, not plates. A rectangular plate inside a SMOOTHED (therefore
    # rounded) body always pushes its four corners out through the surface -
    # from the front it reads as a clean line and from three-quarter as a
    # yellow chevron laid across the waist. A disc has no corners to escape.
    ("waistSeam", "cylinder",   [0.0, 4.62, 0.05], [0, 0, 0],   [2.55, 0.14, 2.15], "seam", False),
    ("chestSeam", "cylinder",   [0.0, 6.20, 0.05], [0, 0, 0],   [2.85, 0.13, 2.30], "seam", False),
    ("collar",   "cube",        [0.0, 8.80, 0.10], [0, 6, 0],   [4.0, 1.15, 2.6], "iron", True),
    # The heart: a gem lens in a metal bezel over a glowing core. A transmissive
    # gem shows what is behind it, and sunk into a chest there is nothing behind
    # it but stone - pass 1's ruby read as a dark red hole. The ember core IS
    # what it refracts.
    ("heartRim", "torus",       [0.0, 7.45, 1.30], [90, 0, 0],  [2.0, 0.55, 2.0], "bronze", False),
    ("heartCore", "octahedron", [0.0, 7.45, 1.18], [0, 45, 0],  [0.85, 0.95, 0.85], "ember", False),
    ("heart",    "octahedron",  [0.0, 7.45, 1.42], [0, 45, 12], [1.15, 1.45, 1.15], "ruby", False),
    # ---- head --------------------------------------------------------------
    ("neck",     "cylinder",    [0.0, 9.45, -0.05], [0, 0, 0],  [1.35, 1.1, 1.35], "iron", False),
    ("head",     "cube",        [0.0, 10.25, 0.05], [0, 20, 0], [2.0, 1.75, 2.05], "granite", True),
    ("brow",     "cube",        [0.0, 10.70, 0.28], [-12, 0, 0], [2.10, 0.62, 1.35], "iron", True),
    ("jaw",      "prism",       [0.0, 9.72, 0.42],  [180, 0, 0], [1.55, 0.62, 1.25], "basalt", False),
    ("eyeL",     "octahedron",  [0.48, 10.22, 0.94], [0, 0, 0], [0.44, 0.36, 0.44], "citrine", False),
    ("eyeR",     "octahedron",  [-0.48, 10.22, 0.94], [0, 0, 0], [0.44, 0.36, 0.44], "citrine", False),
    ("eyeGlowL", "octahedron",  [0.48, 10.22, 0.86], [0, 0, 0], [0.30, 0.25, 0.30], "ember", False),
    ("eyeGlowR", "octahedron",  [-0.48, 10.22, 0.86], [0, 0, 0], [0.30, 0.25, 0.30], "ember", False),
    # ---- shoulders and arms (long, knuckles near the ground) ---------------
    ("shoulderL", "icosahedron", [3.15, 8.35, 0.0], [10, 25, 15], [2.8, 2.5, 2.7], "basalt", True),
    ("shoulderR", "icosahedron", [-3.15, 8.35, 0.0], [10, -25, -15], [2.8, 2.5, 2.7], "basalt", True),
    # Were flat prisms. A wedge scaled thin is a triangle with no thickness to
    # catch a gradient, so it read as a paper plate taped to the shoulder.
    # Roughened icosahedra are armour boulders instead.
    ("pauldronL", "icosahedron", [3.30, 9.35, 0.0], [0, 0, -22], [2.85, 1.55, 2.65], "iron", True),
    ("pauldronR", "icosahedron", [-3.30, 9.35, 0.0], [0, 0, 22], [2.85, 1.55, 2.65], "iron", True),
    ("upperArmL", "cylinder",    [3.90, 6.30, 0.0], [0, 0, -9],  [1.75, 3.2, 1.75], "granite", True),
    ("upperArmR", "cylinder",    [-3.90, 6.30, 0.0], [0, 0, 9],  [1.75, 3.2, 1.75], "granite", True),
    ("elbowL",   "icosahedron",  [4.22, 4.55, 0.0], [0, 45, 0],  [1.65, 1.55, 1.65], "basalt", True),
    ("elbowR",   "icosahedron",  [-4.22, 4.55, 0.0], [0, 45, 0], [1.65, 1.55, 1.65], "basalt", True),
    ("armSeamL", "cylinder",     [4.06, 5.42, 0.0], [0, 0, -9],  [1.55, 0.14, 1.55], "seam", False),
    ("armSeamR", "cylinder",     [-4.06, 5.42, 0.0], [0, 0, 9],  [1.55, 0.14, 1.55], "seam", False),
    ("forearmL", "cylinder",     [4.50, 2.95, 0.05], [0, 0, -6], [1.95, 2.7, 1.95], "granite", True),
    ("forearmR", "cylinder",     [-4.50, 2.95, 0.05], [0, 0, 6], [1.95, 2.7, 1.95], "granite", True),
    ("fistL",    "icosahedron",  [4.78, 1.20, 0.15], [15, 20, 0], [2.35, 2.25, 2.35], "basalt", True),
    ("fistR",    "icosahedron",  [-4.78, 1.20, 0.15], [15, -20, 0], [2.35, 2.25, 2.35], "basalt", True),
    ("knuckleL", "cube",         [4.80, 1.55, 0.92], [-18, 0, 0], [1.75, 0.55, 0.85], "bronze", False),
    ("knuckleR", "cube",         [-4.80, 1.55, 0.92], [-18, 0, 0], [1.75, 0.55, 0.85], "bronze", False),
    # ---- legs (short, thick) ----------------------------------------------
    ("thighL",   "cylinder",     [1.45, 2.55, 0.0], [0, 0, 5],   [2.05, 2.4, 2.15], "basalt", True),
    ("thighR",   "cylinder",     [-1.45, 2.55, 0.0], [0, 0, -5], [2.05, 2.4, 2.15], "basalt", True),
    ("kneeL",    "icosahedron",  [1.52, 1.45, 0.12], [0, 30, 0], [1.55, 1.35, 1.55], "iron", False),
    ("kneeR",    "icosahedron",  [-1.52, 1.45, 0.12], [0, 30, 0], [1.55, 1.35, 1.55], "iron", False),
    ("shinL",    "cylinder",     [1.58, 0.80, 0.0], [0, 0, 3],   [1.85, 1.45, 1.95], "granite", True),
    ("shinR",    "cylinder",     [-1.58, 0.80, 0.0], [0, 0, -3], [1.85, 1.45, 1.95], "granite", True),
    ("footL",    "cube",         [1.66, 0.30, 0.70], [0, 7, 0],  [2.70, 0.62, 3.5], "basalt", True),
    ("footR",    "cube",         [-1.66, 0.30, 0.70], [0, -7, 0], [2.70, 0.62, 3.5], "basalt", True),
    # ---- back growth: the gem moment, read from the side -------------------
    ("spineA",   "pyramid",      [0.0, 8.70, -1.75], [58, 0, 0],  [1.15, 1.75, 1.15], "amethyst", False),
    ("spineB",   "pyramid",      [0.88, 7.45, -1.80], [62, 25, 10], [0.92, 1.35, 0.92], "amethyst", False),
    ("spineC",   "pyramid",      [-0.88, 7.45, -1.80], [62, -25, -10], [0.92, 1.35, 0.92], "amethyst", False),
    ("spineD",   "pyramid",      [0.0, 6.20, -1.65], [66, 45, 0], [0.78, 1.15, 0.78], "ruby", False),
]

# The room. `target` frames the figure regardless of room size now, so the room
# is sized to keep its own edges out of frame rather than to out-vote the
# subject - pass 1 was small enough that the backdrop's corners were visible
# behind the head. Mid-grey, not white: pass 1's 0.58 backdrop clipped solid.
ENVIRONMENT = [
    ("ground", "plane", [0.0, 0.0, 0.0], [0, 0, 0], [70.0, 1.0, 60.0],
     dict(color=[0.20, 0.20, 0.22])),
    ("backdrop", "plane", [0.0, 18.0, -22.0], [90, 0, 0], [70.0, 1.0, 46.0],
     dict(color=[0.34, 0.35, 0.38])),
    # A three-quarter camera sees past a single back wall. Pass 2 left 19% of
    # the frame transparent, which a viewer renders as a hard-edged white slab -
    # it reads as a bug in the geometry and is not one.
    ("sidewall", "plane", [-26.0, 18.0, 0.0], [90, 0, 90], [70.0, 1.0, 46.0],
     dict(color=[0.30, 0.31, 0.34])),
]

ROUGH_OPS = [
    {"op": "smooth", "divisions": 1},
    {"op": "displace_noise", "amp": 0.055, "freq": 3.1, "octaves": 2},
]


def ok(resp, what):
    if resp.get("status") != "ok":
        print("FAILED %s: %s" % (what, json.dumps(resp.get("error", resp))[:400]))
        sys.exit(1)
    return resp["result"]


def build():
    ok(call("new_scene", {"confirm": True}, 180.0), "new_scene")

    for name, kind, translate, rotate, scale, color in ENVIRONMENT:
        ok(call("create_primitive", {
            "kind": kind, "name": name, "translate": translate,
            "rotate": rotate, "scale": scale}, 60.0), "create %s" % name)
        ok(call("assign_material", {
            "mesh": "|" + name, "shader": "lambert", "name": name + "_mat",
            "params": color}, 60.0), "material %s" % name)

    roughed = 0
    for name, kind, translate, rotate, scale, mat, rough in CHUNKS:
        ok(call("create_primitive", {
            "kind": kind, "name": name, "translate": translate,
            "rotate": rotate, "scale": scale}, 60.0), "create %s" % name)
        if rough:
            ok(call("sculpt_ops", {"mesh": "|" + name, "ops": ROUGH_OPS}, 180.0),
               "roughen %s" % name)
            roughed += 1
        # One shader per material name, reused across every chunk wearing it.
        ok(call("assign_material", {
            "mesh": "|" + name, "shader": "standardSurface", "name": mat + "_mat",
            "params": MATS[mat]}, 60.0), "material %s on %s" % (mat, name))

    # Pass 1 at 6.0 measured clipped_fraction 0.445 - a third of the frame with
    # no detail left in it. The instrument said so before any eye did.
    ok(call("setup_lighting", {
        "preset": "three_point", "intensity": 3.0, "replace_existing": True},
        180.0), "setup_lighting")
    return roughed


def render(label, angles, target=None, zoom=1.0, resolution=768, samples=4):
    params = {"angles": list(angles), "renderer": "arnold",
              "resolution": resolution, "samples": samples, "zoom": zoom}
    if target:
        params["target"] = list(target)
    result = ok(call("render_scene", params, 900.0), "render %s" % label)
    os.makedirs(OUT_DIR, exist_ok=True)
    for shot in result["images"]:
        png = base64.b64decode(shot["png_b64"])
        path = os.path.join(OUT_DIR, "%s_%s.png" % (label, shot["angle"]))
        with open(path, "wb") as fh:
            fh.write(png)
        print("%-30s %s" % (os.path.basename(path),
                            json.dumps(images.pixel_stats(png))))


if __name__ == "__main__":
    label = sys.argv[1] if len(sys.argv) > 1 else "v6"
    angles = sys.argv[2].split(",") if len(sys.argv) > 2 else ["three_quarter"]
    zoom = float(sys.argv[3]) if len(sys.argv) > 3 else 1.35
    if os.environ.get("BRUTE_SKIP_BUILD") != "1":
        roughed = build()
        print("built: %d chunks (%d roughened) + %d environment"
              % (len(CHUNKS), roughed, len(ENVIRONMENT)))
    figure = [c[0] for c in CHUNKS]
    render(label, angles, target=figure, zoom=zoom)
