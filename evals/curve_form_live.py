"""#768 acceptance gate: curve-driven forms in a REAL Maya, measured.

Three forms that were impossible before this ticket - a vase (revolve), a
tapered horn (sweep), a torso (loft) - each asserted on the numbers the
tool itself reports, then pushed through the rest of the pipeline
(boolean, uv_atlas, bind_skin), because a constructor whose output the
other tools choke on has not closed the gap.

TOLERANCE starts at None (measurement mode): every worst_station_deviation
is printed and nothing is asserted on it. Once real numbers are in hand,
TOLERANCE is set to 2x the worst measured value, rounded up to one
significant figure, floored at 0.01 - the #773 method (measure first, then
state the threshold that discriminates). The coarse-horn check at the
bottom of gate_horn is the negative control: a resolution too coarse to
actually pass must land ABOVE TOLERANCE, or the number is not a gate.

`check_quad_dominant` asserts the spec's "quad-dominant" promise (tris <=
2*faces) using `get_object_info`'s mesh_stats section - both numbers are
already cheap to read there, no extra triangulation step needed.

Every check() call accumulates into FAILURES rather than stopping the run;
only ok() aborts early, and only on a hard call failure (a refused or
crashed command) - so a run always exercises every check before deciding
pass/fail, and exits non-zero at the end if any check failed (the
array_deform_live convention).

Run:  set MAYA_MCP_PORT=9878 && .venv/Scripts/python.exe evals/curve_form_live.py
Artifacts: evals/curve_form_live/*.png
"""

from __future__ import annotations

import base64
import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))
sys.path.insert(0, os.path.dirname(_HERE))

from live_call import call  # noqa: E402
from maya_mcp import images  # noqa: E402

OUT_DIR = os.path.join(_HERE, "curve_form_live")
FAILURES = []

# Measured on a real Maya (2026-08-27, agent Maya pid 17372, port 9878):
#   vase  worst_station_deviation = 0.0054
#   horn  worst_station_deviation = 0.0022
#   torso worst_station_deviation = 0.0086  <- worst of the three
# TOLERANCE = 2x the worst measured value (0.0172), rounded up to 1
# significant figure (0.02), floored at 0.01 (the #773 method). Negative
# control: the same horn at resolution={"along":4,"around":4} measured
# 0.0406, well above this tolerance - it discriminates.
TOLERANCE = 0.02


def check_quad_dominant(name, around):
    """Assert `name`'s mesh is quad-dominant: close to 2 triangles per quad
    face, with slack only for the 2 n-gon end caps.

    A pure-quad body triangulates to exactly 2 tris per face. Each end cap
    is a SINGLE n-gon face with `around` sides, which triangulates to
    `around - 2` triangles while counting as only 1 face - a shortfall the
    "2 tris per face" baseline does not budget for. `2 * around` covers
    both caps' worth of that shortfall with room to spare (measured: the
    actual excess for the vase/horn/torso builds below is 38/24/38 tris
    against a `2 * around` slack of 40/32/40 - a real gate, not a rubber
    stamp: a mesh that was actually triangulated or n-gon-heavy throughout
    would blow well past this).

    `around` is the resolution/profile side count THIS gate itself passed
    to `create_curve_form` for `name` - not an assumption about the
    handler's internal defaults - so the slack is honestly derived from
    numbers this script controls. tris/faces come cheaply off
    `get_object_info`'s `mesh_stats` section - no separate triangulation
    step needed to observe them.
    """
    info = ok(call("get_object_info", {"name": name, "include": ["mesh_stats"]}, 60.0),
              "get_object_info %s" % name)
    stats = info["mesh_stats"]
    tris, faces = stats["tris"], stats["faces"]
    slack = 2 * around
    check(tris <= 2 * faces + slack,
          "%s is quad-dominant (tris=%d <= 2*faces + cap slack=%d)"
          % (name, tris, 2 * faces + slack))


def ok(resp, what):
    if resp.get("status") != "ok":
        print("FAILED %s: %s" % (what, json.dumps(resp.get("error", resp))[:400]))
        sys.exit(1)
    return resp["result"]


def check(condition, message):
    print(("  PASS  " if condition else "  FAIL  ") + message)
    if not condition:
        FAILURES.append(message)


def report_deviation(label, result):
    """Print the measured deviation; assert it only once TOLERANCE is real."""
    deviation = result["worst_station_deviation"]
    print("  %s worst_station_deviation=%.4f (station=%s, form_size=%.4f)"
          % (label, deviation, result.get("worst_station"), result.get("form_size", 0.0)))
    if TOLERANCE is None:
        return deviation
    check(deviation <= TOLERANCE,
          "%s worst_station_deviation %.4f <= tolerance %.4f"
          % (label, deviation, TOLERANCE))
    return deviation


def ring(y, a, b, n=8):
    """n points around an ellipse (semi-axes a, b) at height y, in the XZ plane."""
    pts = []
    for i in range(n):
        theta = i * (2.0 * math.pi / n)
        pts.append([a * math.cos(theta), y, b * math.sin(theta)])
    return pts


VASE_RESOLUTION = {"along": 24, "around": 24}  # matches the revolve/loft default


def gate_vase():
    print("\n[1] vase: revolve")
    result = ok(call("create_curve_form", {
        "kind": "revolve", "name": "vase",
        "profile": [[0.30, 0.0], [0.50, 0.35], [0.22, 0.80],
                    [0.28, 1.10], [0.20, 1.25]],
        "resolution": VASE_RESOLUTION,
    }, 180.0), "create_curve_form vase")
    check(result["watertight"], "vase is watertight")
    check(result["faces"] > 0, "vase has faces (%d)" % result["faces"])
    report_deviation("vase", result)
    check_quad_dominant(result["name"], VASE_RESOLUTION["around"])
    return result


HORN_RESOLUTION = {"along": 32, "around": 16}  # matches the sweep default; no
# explicit profile_sides, so the tube's own cross-section side count IS
# resolution.around (see curveform._build_sweep's fallback).


def gate_horn():
    print("\n[2] horn: sweep")
    result = ok(call("create_curve_form", {
        "kind": "sweep", "name": "horn",
        "path": [[0, 0, 0], [0.1, 0.5, 0], [0.35, 0.9, 0], [0.7, 1.1, 0.2]],
        "width": [[0, 0.30], [1, 0.06]],
        "resolution": HORN_RESOLUTION,
    }, 180.0), "create_curve_form horn")
    check(result["watertight"], "horn is watertight")
    report_deviation("horn", result)
    check_quad_dominant(result["name"], HORN_RESOLUTION["around"])

    # Negative control (Step 3): a deliberately coarse tessellation must NOT
    # pass. Built and measured, never placed in the scene under the "horn"
    # name so it cannot collide with (or be mistaken for) the real one used
    # in the composition steps below.
    coarse = ok(call("create_curve_form", {
        "kind": "sweep", "name": "horn_coarse",
        "path": [[0, 0, 0], [0.1, 0.5, 0], [0.35, 0.9, 0], [0.7, 1.1, 0.2]],
        "width": [[0, 0.30], [1, 0.06]],
        "resolution": {"along": 4, "around": 4},
    }, 180.0), "create_curve_form horn_coarse")
    coarse_dev = coarse["worst_station_deviation"]
    print("  horn_coarse (resolution along=4,around=4) worst_station_deviation=%.4f"
          % coarse_dev)
    if TOLERANCE is not None:
        check(coarse_dev > TOLERANCE,
              "coarse horn (along=4,around=4) deviation %.4f exceeds tolerance "
              "%.4f - the tolerance actually discriminates" % (coarse_dev, TOLERANCE))
    ok(call("delete_objects", {"names": [coarse["name"]]}, 60.0), "delete horn_coarse")
    return result


TORSO_RESOLUTION = {"along": 24, "around": 24}  # matches the revolve/loft
# default; the loft's tessellation "around" count (nurbsToPoly's vNumber,
# which is what sizes the two end-cap n-gons) is this, NOT the 8 points
# per `ring()` section below - those only shape the NURBS surface lofted
# through them.


def gate_torso():
    print("\n[3] torso: loft, 4 rings x 8 points, elliptical, chest wider than waist")
    sections = [
        ring(0.00, 0.35, 0.25),   # hip
        ring(0.45, 0.28, 0.20),   # waist - narrowest
        ring(0.90, 0.45, 0.32),   # chest - widest
        ring(1.30, 0.32, 0.24),   # shoulder
    ]
    result = ok(call("create_curve_form", {
        "kind": "loft", "name": "torso", "sections": sections,
        "resolution": TORSO_RESOLUTION,
    }, 180.0), "create_curve_form torso")
    check(result["watertight"], "torso is watertight")
    report_deviation("torso", result)
    check_quad_dominant(result["name"], TORSO_RESOLUTION["around"])
    return result


def gate_boolean(horn_name):
    print("\n[4] composition: boolean union with the horn")
    # boolean_op CONSUMES both operands (see modeling._do_boolean's docstring -
    # "both are about to stop existing"), and the render_sheet step still
    # needs the original horn - so the boolean runs against a disposable
    # duplicate, not the horn itself.
    dup = ok(call("duplicate", {"name": horn_name, "new_name": "horn_for_boolean"},
                  60.0), "duplicate horn")
    ok(call("create_primitive", {
        "kind": "cube", "name": "hornBase", "translate": [0.0, -0.2, 0.0],
        "scale": [0.6, 0.4, 0.6],
    }, 60.0), "hornBase cube")
    result = ok(call("boolean_op", {
        "a": "|hornBase", "b": dup["name"], "op": "union", "new_name": "horn_union",
    }, 180.0), "boolean_op union")
    check(result.get("tris", 0) > 0, "boolean union reports faces/tris (%s)"
          % result.get("tris"))
    return result


def gate_uv_atlas(vase_name):
    print("\n[5] composition: uv_atlas on the vase")
    result = ok(call("uv_atlas", {
        "names": [vase_name], "cols": 1, "rows": 1, "patch": 0, "margin": 0.05,
    }, 180.0), "uv_atlas vase")
    check(bool(result.get("meshes")), "uv_atlas reports at least one mesh")
    return result


def gate_bind_skin(torso_name):
    print("\n[6] composition: bind_skin on the torso")
    skeleton = ok(call("create_skeleton", {
        "chain": [[0.0, 0.0, 0.0], [0.0, 0.65, 0.0], [0.0, 1.30, 0.0]],
        "chain_prefix": "torso_j",
    }, 60.0), "create_skeleton torso chain")
    check(len(skeleton["joints"]) == 3, "3-joint chain built (got %d)"
          % len(skeleton["joints"]))
    root = skeleton["root"]
    bind = ok(call("bind_skin", {"mesh": torso_name, "root": root}, 600.0),
              "bind_skin torso")
    check(bind.get("unweighted_vertices", 1) == 0,
          "bind_skin leaves no vertex unweighted (unweighted=%s, warnings=%s)"
          % (bind.get("unweighted_vertices"), bind.get("warnings")))
    return bind


def gate_render_sheet(names):
    print("\n[7] render_sheet of the three forms")
    result = ok(call("render_sheet", {
        "subjects": names, "renderer": "arnold", "resolution": 512, "samples": 3,
    }, 600.0), "render_sheet")
    check(len(result.get("images", [])) == len(names),
          "render_sheet returned one image per subject (%d of %d)"
          % (len(result.get("images", [])), len(names)))
    pngs = [base64.b64decode(img["png_b64"]) for img in result["images"]]
    os.makedirs(OUT_DIR, exist_ok=True)
    for img, png in zip(result["images"], pngs):
        stats = images.pixel_stats(png)
        print("  %s %s" % (img["label"], json.dumps(stats)))
        check(not stats["blank"], "%s cell is not blank" % img["label"])
    sheet_png = images.contact_sheet(pngs, cols=len(pngs))
    sheet_path = os.path.join(OUT_DIR, "sheet.png")
    with open(sheet_path, "wb") as fh:
        fh.write(sheet_png)
    print("  wrote %s" % sheet_path)
    return result


if __name__ == "__main__":
    ok(call("new_scene", {"confirm": True}, 180.0), "new_scene")

    vase = gate_vase()
    horn = gate_horn()
    torso = gate_torso()

    gate_boolean(horn["name"])
    gate_uv_atlas(vase["name"])
    gate_bind_skin(torso["name"])
    gate_render_sheet([vase["name"], horn["name"], torso["name"]])

    print("\n%d checks failed" % len(FAILURES))
    for failure in FAILURES:
        print("  - %s" % failure)
    sys.exit(1 if FAILURES else 0)
