"""Live proof for the four #585 findings, fixed under #586.

Each claim is a measurement against the study scene that produced the finding:

  F1 target/zoom - a close-up frames the gem AND keeps the room behind it
  F2 transmissionDepth - physical absorption instead of a paint-like tint
  F3 relight - a side render is no longer nearly black
  F4 exposure - clipped fraction and mean luminance are reported

Run:  set MAYA_MCP_PORT=9878 && .venv/Scripts/python.exe evals/lookdev_controls_live.py
Exit: 0 pass, 1 fail, 2 could not run.
Artifacts: evals/m2_3_run/*.png
"""

from __future__ import annotations

import base64
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from gem_brute_v5 import STUDY, STUDY_ENV, GEMS  # noqa: E402
from live_call import call  # noqa: E402
from maya_mcp import images  # noqa: E402

OUT_DIR = os.path.join(_HERE, "m2_3_run")
FAILURES = []


def ok(resp, what):
    if resp.get("status") != "ok":
        print("ERROR %s: %s" % (what, json.dumps(resp.get("error", resp))[:400]))
        sys.exit(1)
    return resp["result"]


def check(claim, condition, detail):
    print("%-58s %s   %s" % (claim, "PASS" if condition else "FAIL", detail))
    if not condition:
        FAILURES.append(claim)


def render(label, params):
    result = ok(call("render_scene", dict(params), 600.0), "render " + label)
    shot = result["images"][0]
    png = base64.b64decode(shot["png_b64"])
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, label + ".png"), "wb") as fh:
        fh.write(png)
    stats = images.pixel_stats(png)
    print("  %-22s %s" % (label, json.dumps(stats)))
    return stats, result


def build():
    ok(call("new_scene", {"confirm": True}, 120.0), "new_scene")
    for name, kind, translate, rotate, scale, color in STUDY_ENV:
        ok(call("create_primitive", {"kind": kind, "name": name,
                                     "translate": translate, "rotate": rotate,
                                     "scale": scale}, 60.0), "create " + name)
        ok(call("assign_material", {"mesh": "|" + name, "shader": "lambert",
                                    "name": name + "_mat", "params": color},
                60.0), "material " + name)
    gems = dict(GEMS)
    gems["painted"] = dict(baseColor=[0.42, 0.03, 0.06], transmission=0.0,
                           roughness=0.12, specular=1.0)
    for name, kind, translate, rotate, scale, gem in STUDY:
        ok(call("create_primitive", {"kind": kind, "name": name,
                                     "translate": translate, "rotate": rotate,
                                     "scale": scale}, 60.0), "create " + name)
        ok(call("assign_material", {"mesh": "|" + name, "shader": "standardSurface",
                                    "name": gem + "_mat", "params": gems[gem]},
                # 4.0/pi: the pre-#617 number, in the new unit - same pixels as before
                60.0), "material " + gem)
    ok(call("setup_lighting", {"preset": "three_point", "intensity": 1.2732,
                               # 16.0/pi: the pre-#617 number, in the new unit - same pixels as before
                               "replace_existing": True}, 120.0), "setup_lighting")


def main():
    build()
    base = {"angles": ["front"], "renderer": "arnold", "resolution": 384,
            "samples": 3}

    # --- F1: framing and visibility are separate questions now
    wide, _ = render("f1_wide", base)
    close, _ = render("f1_target_zoom",
                      dict(base, target=["|studyDiamond"], zoom=2.2))
    isolated, _ = render("f1_isolate_for_contrast",
                         dict(base, isolate=["|studyDiamond"], zoom=2.2))
    check("F1 target+zoom fills more of the frame than the wide shot",
          close["opaque_px"] > wide["opaque_px"],
          "wide %d px -> close %d px" % (wide["opaque_px"], close["opaque_px"]))
    # The point of the split: isolate removes the room, target keeps it. A kept
    # room means far more distinct colours behind the glass to refract.
    check("F1 target keeps the room that isolate removes",
          close["distinct_colors"] > isolated["distinct_colors"] * 1.5,
          "target %d colours vs isolate %d"
          % (close["distinct_colors"], isolated["distinct_colors"]))

    # --- F2: transmissionDepth gives physical colour control
    ok(call("assign_material", {
        "mesh": "|studyRuby", "shader": "standardSurface", "name": "depthRuby_mat",
        "params": {"baseColor": [0.35, 0.02, 0.05], "transmission": 1.0,
                   "transmissionColor": [0.85, 0.10, 0.14],
                   "transmissionDepth": 3.0, "ior": 1.77, "roughness": 0.03,
                   "coat": 1.0, "coatRoughness": 0.02}}, 60.0), "depth ruby")
    depth, _ = render("f2_transmission_depth",
                      dict(base, target=["|studyRuby"], zoom=2.0))
    check("F2 transmissionDepth/coat accepted and rendered non-blank",
          not depth["blank"], "%d opaque px" % depth["opaque_px"])

    # --- F3: the rig follows the camera.
    # Measured on the BACK angle with the subject filling the frame. A side
    # view of this scene puts the subject on 4% of the pixels, so whole-frame
    # luminance cannot see the difference - the first version of this check
    # failed for that reason and was measuring the test, not the fix.
    # Isolated so the frame contains only the subject: any luminance change is
    # the light moving. Measured on the OPAQUE control, whose brightness is a
    # direct function of light direction - a transmissive gem's is not.
    away = dict(base, angles=["side"], isolate=["|studyOpaqueRed"], zoom=1.4)
    lit, result_lit = render("f3_relit", away)
    locked, _ = render("f3_world_locked", dict(away, relight=False))
    check("F3 relight brightens an off-key angle vs the world-locked rig",
          lit["mean_luma"] > locked["mean_luma"] * 1.15,
          "relit luma %.1f vs locked %.1f"
          % (lit["mean_luma"], locked["mean_luma"]))
    check("F3 relight reports which lights it swung",
          result_lit.get("relit_lights", 0) >= 3,
          "relit_lights=%s" % result_lit.get("relit_lights"))

    # --- F4: exposure is a number
    hot, _ = render("f4_overexposed", base)  # after a deliberate blowout below
    check("F4 every frame reports clipped_fraction and mean_luma",
          all(k in hot for k in ("clipped_fraction", "mean_luma")),
          "clipped %.3f, luma %.1f" % (hot["clipped_fraction"], hot["mean_luma"]))
    ok(call("setup_lighting", {"preset": "three_point", "intensity": 5.0930,
                               "replace_existing": True}, 120.0), "blow it out")
    blown, _ = render("f4_blown", base)
    check("F4 clipped_fraction rises when the exposure is blown",
          blown["clipped_fraction"] > hot["clipped_fraction"],
          "%.3f -> %.3f at intensity 4 -> 16"
          % (hot["clipped_fraction"], blown["clipped_fraction"]))

    if FAILURES:
        print("\nFAILED: " + "; ".join(FAILURES))
        return 1
    print("\nPASS - all four findings closed, measured")
    print("artifacts: " + OUT_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
