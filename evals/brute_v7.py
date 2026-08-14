"""The brute, rebuilt with arrays and flare (redmine #587) — the M2.4 after-picture.

`evals/brute_v6.py` is the before-picture, built the day M2.4 was specified. Its
source carried the milestone's whole argument in plain sight: fourteen
hand-typed left/right pairs with nothing checking the negated row matched its
twin, and every limb a constant-diameter tube because taper was inexpressible.

This is the same figure with the same materials, lighting and framing, rebuilt
using what M2.4 added. Nothing about the art direction changed — only the
vocabulary available to describe it.

What changed, concretely:

  - Every left/right pair is now ONE authored row plus a `mirror` call. The
    right side cannot drift from the left, because it is not typed.
  - Four limb segments taper via the `flare` deformer: upper arms and thighs
    heavy at the joint and tapering away, forearms and shins flaring back out
    toward fist and foot. None of this shape existed in v6.
  - The back crystal growth is a `linear` array with compounding `step_scale`,
    so it recedes down the spine geometrically instead of via four hand-tuned
    rows.
  - The heart bolts and the collar vent stacks are `radial` arrays. Both sit on
    the midline, so they need no mirroring — a ring is one call.

Honest limitation, worth stating because it shaped the code: `mirror` requires a
single polygon mesh, so a whole limb GROUP cannot be mirrored in one call yet
(M2.4 added a clear error for that rather than a traceback; per-descendant
normal reversal is a follow-up). So this mirrors chunk by chunk. That is still
one authored row per pair instead of two, and the numbers cannot disagree.

Run:  set MAYA_MCP_PORT=9878 && .venv/Scripts/python.exe evals/brute_v7.py v7
Artifacts: evals/brute_v7/*.png
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

OUT_DIR = os.path.join(_HERE, "brute_v7")

# Materials are v6's, unchanged and deliberately so: holding the look constant
# is what makes the shape difference readable.
MATS = {
    "basalt": dict(baseColor=[0.195, 0.186, 0.200], roughness=0.72, specular=0.50),
    "granite": dict(baseColor=[0.27, 0.250, 0.235], roughness=0.66, specular=0.45),
    "iron": dict(baseColor=[0.38, 0.39, 0.42], metalness=0.68, roughness=0.58),
    "bronze": dict(baseColor=[0.62, 0.42, 0.19], metalness=0.70, roughness=0.38),
    "seam": dict(baseColor=[0.05, 0.03, 0.02], emission=2.6,
                 emissionColor=[1.0, 0.52, 0.08], roughness=0.5),
    "ember": dict(baseColor=[0.05, 0.03, 0.02], emission=6.0,
                  emissionColor=[1.0, 0.66, 0.22], roughness=0.5),
    "ruby": dict(baseColor=[0.35, 0.02, 0.05], transmission=1.0,
                 transmissionColor=[0.92, 0.32, 0.36], ior=1.77, roughness=0.03),
    "citrine": dict(baseColor=[0.45, 0.30, 0.03], transmission=1.0,
                    transmissionColor=[0.95, 0.78, 0.38], ior=1.55, roughness=0.04),
    "amethyst": dict(baseColor=[0.22, 0.08, 0.38], transmission=1.0,
                     transmissionColor=[0.72, 0.52, 0.92], ior=1.54, roughness=0.05),
}

# ------------------------------------------------------------------ midline
# (name, kind, translate, rotate, scale, material, rough)
# Chunks on x=0. They are their own mirror image, so they are authored once and
# left alone.
MIDLINE = [
    ("pelvis",   "cube",        [0.0, 3.85, 0.0],  [0, 16, 0],  [3.1, 1.9, 2.5], "granite", True),
    ("belly",    "cube",        [0.0, 5.35, 0.05], [0, -11, 0], [3.3, 1.9, 2.6], "basalt", True),
    ("chest",    "cube",        [0.0, 7.35, 0.0],  [0, 9, 0],   [4.7, 2.8, 3.1], "basalt", True),
    ("waistSeam", "cylinder",   [0.0, 4.62, 0.05], [0, 0, 0],   [2.55, 0.14, 2.15], "seam", False),
    ("chestSeam", "cylinder",   [0.0, 6.20, 0.05], [0, 0, 0],   [2.85, 0.13, 2.30], "seam", False),
    ("collar",   "cube",        [0.0, 8.80, 0.10], [0, 6, 0],   [4.0, 1.15, 2.6], "iron", True),
    ("heartRim", "torus",       [0.0, 7.45, 1.30], [90, 0, 0],  [2.0, 0.55, 2.0], "bronze", False),
    ("heartCore", "octahedron", [0.0, 7.45, 1.18], [0, 45, 0],  [0.85, 0.95, 0.85], "ember", False),
    ("heart",    "octahedron",  [0.0, 7.45, 1.42], [0, 45, 12], [1.15, 1.45, 1.15], "ruby", False),
    ("neck",     "cylinder",    [0.0, 9.45, -0.05], [0, 0, 0],  [1.35, 1.1, 1.35], "iron", False),
    ("head",     "cube",        [0.0, 10.25, 0.05], [0, 20, 0], [2.0, 1.75, 2.05], "granite", True),
    ("brow",     "cube",        [0.0, 10.70, 0.28], [-12, 0, 0], [2.10, 0.62, 1.35], "iron", True),
    ("jaw",      "prism",       [0.0, 9.72, 0.42],  [180, 0, 0], [1.55, 0.62, 1.25], "basalt", False),
]

# ------------------------------------------------------------- the left side
# Authored ONCE. Every entry below becomes two chunks: itself and its mirror
# across x=0. In v6 each of these was two literal rows with hand-negated
# numbers on the second.
LEFT = [
    ("shoulderL", "icosahedron", [3.15, 8.35, 0.0], [10, 25, 15], [2.8, 2.5, 2.7], "basalt", True),
    ("pauldronL", "icosahedron", [3.30, 9.35, 0.0], [0, 0, -22], [2.85, 1.55, 2.65], "iron", True),
    ("upperArmL", "cylinder",    [3.90, 6.30, 0.0], [0, 0, -9],  [1.75, 3.2, 1.75], "granite", True),
    ("elbowL",   "icosahedron",  [4.22, 4.55, 0.0], [0, 45, 0],  [1.65, 1.55, 1.65], "basalt", True),
    ("armSeamL", "cylinder",     [4.06, 5.42, 0.0], [0, 0, -9],  [1.5, 0.14, 1.5], "seam", False),
    ("forearmL", "cylinder",     [4.50, 2.95, 0.05], [0, 0, -6], [1.95, 2.7, 1.95], "granite", True),
    ("fistL",    "icosahedron",  [4.78, 1.20, 0.15], [15, 20, 0], [2.35, 2.25, 2.35], "basalt", True),
    ("knuckleL", "cube",         [4.78, 1.58, 0.72], [-18, 0, 0], [1.60, 0.48, 0.80], "bronze", False),
    ("thighL",   "cylinder",     [1.45, 2.55, 0.0], [0, 0, 5],   [2.05, 2.4, 2.15], "basalt", True),
    ("kneeL",    "icosahedron",  [1.52, 1.45, 0.12], [0, 30, 0], [1.55, 1.35, 1.55], "iron", False),
    ("shinL",    "cylinder",     [1.58, 0.80, 0.0], [0, 0, 3],   [1.85, 1.45, 1.95], "granite", True),
    ("footL",    "cube",         [1.66, 0.30, 0.70], [0, 7, 0],  [2.70, 0.62, 3.5], "basalt", True),
    ("eyeL",     "octahedron",   [0.48, 10.22, 0.94], [0, 0, 0], [0.44, 0.36, 0.44], "citrine", False),
    ("eyeGlowL", "octahedron",   [0.48, 10.22, 0.86], [0, 0, 0], [0.30, 0.25, 0.30], "ember", False),
]

# ------------------------------------------------------------------- flares
# THE thing v6 could not express. A flare's startFlare* acts at the low (bottom)
# end of the deformer and endFlare* at the high (top) end, so these read as
# "wide where the mass is, narrow where it leaves".
#
# Upper arms and thighs are heavy at the joint and taper away from the body;
# forearms and shins flare back OUT toward fist and foot, which is what makes a
# brute read as top-heavy rather than merely large.
FLARES = {
    "upperArmL": dict(startFlareX=0.78, startFlareZ=0.78, endFlareX=1.30, endFlareZ=1.30),
    "forearmL":  dict(startFlareX=1.28, startFlareZ=1.28, endFlareX=0.84, endFlareZ=0.84),
    "thighL":    dict(startFlareX=0.82, startFlareZ=0.82, endFlareX=1.28, endFlareZ=1.28),
    "shinL":     dict(startFlareX=1.22, startFlareZ=1.22, endFlareX=0.88, endFlareZ=0.88),
}

# ------------------------------------------------------------------- arrays
# All three sit on the midline, so they need no mirroring: a ring or a run is
# one call.
#
# spineA is v6's four hand-tuned pyramid rows replaced by one seed plus a
# compounding linear array. step_scale is a per-copy multiplier, so the growth
# recedes geometrically down the back instead of by hand-picked numbers.
SPINE_SEED = ("spineA", "pyramid", [0.0, 8.70, -1.75], [58, 0, 0],
              [1.15, 1.75, 1.15], "amethyst")
SPINE_ARRAY = dict(mode="linear", count=5, offset=[0.0, -1.18, -0.04],
                   step_scale=[0.86, 0.86, 0.86], name_prefix="spine",
                   group_name="spineGrowth")

# A ring of bolts around the heart bezel, about Z so it lies in the chest face.
# Pass 1 sized these at 0.34 and they vanished into the bezel; they have to sit
# ON the rim to read as fixings rather than as noise.
BOLT_SEED = ("heartBolt", "prism", [0.0, 8.48, 1.34], [90, 0, 0],
             [0.46, 0.34, 0.46], "bronze")
BOLT_ARRAY = dict(mode="radial", count=6, axis="z", center=[0.0, 7.45, 1.34],
                  name_prefix="heartBolt", group_name="heartBolts")

# Exhaust stacks across the BACK of the collar. Pass 1 ran these as a full
# 360 ring around the neck and the front half stood up through the face like
# a cluster of pipes - a full ring is the wrong shape for something that should
# only exist behind the shoulders.
#
# This is an ARC, which is the other half of the radial spacing rule: at 360
# the step is angle/count (no element at the seam, because the seam is where
# the source already sits), but at any other angle it is angle/(count-1) so the
# first and last elements land ON the endpoints. Here that means 5 stacks at
# 45 degrees apart, sweeping from the right shoulder round the back to the
# left - and the endpoints matter, because they are the two that must sit
# symmetrically on the shoulders.
VENT_SEED = ("vent", "cylinder", [1.62, 9.15, -0.35], [0, 0, 0],
             [0.44, 1.05, 0.44], "iron")
VENT_ARRAY = dict(mode="radial", count=5, axis="y", angle=180.0,
                  center=[0.0, 9.15, -0.35],
                  name_prefix="vent", group_name="ventCollar")

# v6 solved "19% of the frame is transparent, which a viewer draws as a
# hard-edged white slab" by adding a sidewall. That fixed the symptom and
# introduced a worse one: a visible corner behind the figure that reads as a
# wall appearing out of nowhere.
#
# The actual problem was a backdrop too small and too close, so a three-quarter
# camera saw past its edge. Far and large has no corner to see: at this
# distance the backdrop subtends roughly four times the frame width, so it
# fills the background from any of the angles rendered here.
# An open box, not a wall. Three iterations of "add one more plane" each fixed
# the angle being looked at and left another one transparent, because a plane
# facing front is EDGE-ON to a side camera. Four walls placed far out is the
# shape that has no bad angle: at 150 units the frame is roughly 110 wide, so
# every corner sits well outside it, and there is no visible seam from any
# horizontal view.
#
# This matters for more than tidiness. The amethyst spine crystals are
# TRANSMISSIVE - they show what is behind them - and against a transparent
# background they rendered as black silhouettes. The same #585 lesson: a gem is
# only as visible as whatever it has to refract.
_WALL = dict(size=[400.0, 1.0, 300.0], y=100.0, grey=[0.33, 0.34, 0.37])
ENVIRONMENT = [
    ("ground", "plane", [0.0, 0.0, 0.0], [0, 0, 0], [400.0, 1.0, 400.0],
     dict(color=[0.20, 0.20, 0.22])),
    ("wallBack", "plane", [0.0, _WALL["y"], -150.0], [90, 0, 0], _WALL["size"],
     dict(color=_WALL["grey"])),
    ("wallFront", "plane", [0.0, _WALL["y"], 150.0], [90, 0, 0], _WALL["size"],
     dict(color=_WALL["grey"])),
    ("wallLeft", "plane", [-150.0, _WALL["y"], 0.0], [90, 0, 90], _WALL["size"],
     dict(color=[0.31, 0.32, 0.35])),
    ("wallRight", "plane", [150.0, _WALL["y"], 0.0], [90, 0, 90], _WALL["size"],
     dict(color=[0.31, 0.32, 0.35])),
]

ROUGH_OPS = [
    {"op": "smooth", "divisions": 1},
    {"op": "displace_noise", "amp": 0.055, "freq": 3.1, "octaves": 2},
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


def make(name, kind, translate, rotate, scale, rough):
    ok(call("create_primitive", {
        "kind": kind, "name": name, "translate": translate,
        "rotate": rotate, "scale": scale}, 60.0), "create %s" % name)
    if rough:
        ok(call("sculpt_ops", {"mesh": "|" + name, "ops": ROUGH_OPS}, 180.0),
           "roughen %s" % name)
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

    stats = dict(authored=0, mirrored=0, flared=0, arrayed=0)

    for name, kind, translate, rotate, scale, mat, rough in MIDLINE:
        material(make(name, kind, translate, rotate, scale, rough), mat)
        stats["authored"] += 1
        _built.append(name)

    # The left side, authored once and reflected. The mirror reports
    # signed_volume: positive means the copy's faces point outward. A negative
    # number here would mean a chunk that renders black, and it would be the
    # tool saying so rather than the render.
    for name, kind, translate, rotate, scale, mat, rough in LEFT:
        mesh = make(name, kind, translate, rotate, scale, rough)
        if name in FLARES:
            ok(call("deform", {
                "mesh": mesh, "deformer": "flare", "params": FLARES[name],
                "delete_history_after": True}, 180.0), "flare %s" % name)
            stats["flared"] += 1
        material(mesh, mat)
        stats["authored"] += 1
        _built.append(name)

        result = ok(call("array", {
            "name": mesh, "mode": "mirror", "axis": "x", "pivot": [0.0, 0.0, 0.0],
            "name_prefix": name[:-1] + "R"}, 180.0), "mirror %s" % name)
        volume = result.get("signed_volume")
        if volume is None or volume <= 0.0:
            print("  WINDING PROBLEM on %s: signed_volume=%s warnings=%s"
                  % (name, volume, result.get("warnings")))
            sys.exit(1)
        for copy in result["names"]:
            material(copy, mat)
            _built.append(copy.split("|")[-1])
        stats["mirrored"] += len(result["names"])

    # The back growth: one seed, one compounding run.
    name, kind, translate, rotate, scale, mat = SPINE_SEED
    seed = make(name, kind, translate, rotate, scale, False)
    material(seed, mat)
    _built.append(name)
    stats["authored"] += 1
    result = ok(call("array", dict(SPINE_ARRAY, name=seed), 180.0), "spine array")
    for copy in result["names"]:
        material(copy, mat)
        _built.append(copy.split("|")[-1])
    stats["arrayed"] += len(result["names"])

    # Two rings.
    for seed_spec, array_spec, label in (
        (BOLT_SEED, BOLT_ARRAY, "heart bolts"),
        (VENT_SEED, VENT_ARRAY, "vent collar"),
    ):
        name, kind, translate, rotate, scale, mat = seed_spec
        seed = make(name, kind, translate, rotate, scale, False)
        material(seed, mat)
        _built.append(name)
        stats["authored"] += 1
        result = ok(call("array", dict(array_spec, name=seed), 180.0), label)
        for copy in result["names"]:
            material(copy, mat)
            _built.append(copy.split("|")[-1])
        stats["arrayed"] += len(result["names"])

    ok(call("setup_lighting", {
        "preset": "three_point", "intensity": 3.0, "replace_existing": True},
        180.0), "setup_lighting")
    return stats


def render(label, angles, zoom=1.35, resolution=768, samples=4):
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
        print("%-30s %s" % (os.path.basename(path),
                            json.dumps(images.pixel_stats(png))))


if __name__ == "__main__":
    label = sys.argv[1] if len(sys.argv) > 1 else "v7"
    angles = sys.argv[2].split(",") if len(sys.argv) > 2 else ["three_quarter"]
    zoom = float(sys.argv[3]) if len(sys.argv) > 3 else 1.35
    stats = build()
    total = len(_built)
    print("built %d chunks: %d authored, %d mirrored, %d arrayed (%d flared)"
          % (total, stats["authored"], stats["mirrored"], stats["arrayed"],
             stats["flared"]))
    print("v6 authored %d rows by hand for the same figure" % 45)
    render(label, angles, zoom)
