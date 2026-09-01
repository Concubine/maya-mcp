"""#772 probe: what field of view does the capture camera ACTUALLY have, and
how big does a subject end up compared with what _FIT_MARGIN intends?

The ticket says the placement math assumes 40 deg while the built camera is
~55 deg, so subjects sit smaller than intended. That 55 is the film back's
HORIZONTAL field of view, and these captures are square (768x768 by default),
so which axis governs the framing is the whole question - and it decides
whether subjects come out smaller (horizontal governs) or slightly larger
(vertical governs, 37.9 deg, which is very close to the assumed 40).

Rather than reason about Maya's film-fit rules, this measures: put a sphere
of known radius at the origin, capture it with frame_all FALSE so the
placement math stands unrefined by viewFit, and count how much of the frame
the sphere covers. Intended coverage is 1/_FIT_MARGIN of the half-frame.

Also reports the render path for comparison - render.py already forces the
focal length to match _FOV_DEG, so it is the control that shows what a
matched camera looks like.

DESTRUCTIVE: calls new_scene. Port 9878 (agent Maya).
Run:  $env:MAYA_MCP_PORT='9878'; python evals/fov_probe_772.py --build
"""

from __future__ import annotations

import base64
import io
import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from live_call import call, structured_result  # noqa: E402
from maya_plugin.handlers import capture as capture_mod  # noqa: E402

OUT_DIR = os.path.join(_HERE, "fov_probe_772")
RADIUS = 1.0
RES = 768


def run(code, label, timeout_s=300.0):
    res = call("execute_python", {"code": code}, timeout_s=timeout_s)
    if res.get("status") != "ok":
        print("FATAL %s: %r" % (label, res.get("error")))
        sys.exit(1)
    result = res.get("result") or {}
    if result.get("traceback"):
        print("FATAL %s raised:\n%s" % (label, result["traceback"][-700:]))
        sys.exit(1)
    return structured_result(result, label)


def subject_extent(png_b64):
    """(width_frac, height_frac) of the non-background pixels.

    The subject is the only object in an otherwise empty scene, so anything
    that is not the flat viewport background belongs to it.
    """
    from PIL import Image

    img = Image.open(io.BytesIO(base64.b64decode(png_b64))).convert("RGB")
    w, h = img.size
    px = img.load()
    bg = px[2, 2]

    def differs(c):
        return (abs(c[0] - bg[0]) + abs(c[1] - bg[1]) + abs(c[2] - bg[2])) > 24

    xs, ys = [], []
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            if differs(px[x, y]):
                xs.append(x)
                ys.append(y)
    if not xs:
        return None, None, 0
    return ((max(xs) - min(xs) + 1) / float(w),
            (max(ys) - min(ys) + 1) / float(h),
            len(xs))


def main():
    if "--build" not in sys.argv:
        print(__doc__)
        return 1
    os.makedirs(OUT_DIR, exist_ok=True)

    call("new_scene", {"confirm": True}, timeout_s=180.0)
    call("create_primitive", {"kind": "sphere", "name": "fov_ball",
                              "scale": [RADIUS, RADIUS, RADIUS]},
         timeout_s=180.0)

    # What the placement math intends, computed from the shipped constants.
    bmin, bmax = (-RADIUS,) * 3, (RADIUS,) * 3
    pos, _rot = capture_mod.camera_placement("front", bmin, bmax)
    sphere_r = math.dist(bmin, bmax) / 2.0
    distance = math.dist(pos, (0.0, 0.0, 0.0))
    print("placement: distance %.4f for bounding-sphere radius %.4f "
          "(= %.3f r, from the assumed %.1f deg)"
          % (distance, sphere_r, distance / sphere_r, capture_mod._FOV_DEG))
    intended = 1.0 / capture_mod._FIT_MARGIN
    print("intended coverage of the frame's half-angle: %.1f%%\n"
          % (100 * intended))

    # --- capture path: camera left at Maya's default lens -----------------
    res = call("capture_viewport", {"angles": ["front"], "frame_all": False,
                                    "resolution": RES}, timeout_s=300.0)
    if res.get("status") != "ok":
        print("capture failed: %r" % res.get("error"))
        return 1
    img = ((res.get("result") or {}).get("images") or [{}])[0]
    cw, ch, npx = subject_extent(img.get("png_b64") or "")
    with open(os.path.join(OUT_DIR, "capture_front.png"), "wb") as fh:
        fh.write(base64.b64decode(img["png_b64"]))
    print("CAPTURE (frame_all=False, default lens):")
    print("  subject spans %.1f%% of frame width, %.1f%% of height (%d px sampled)"
          % (100 * cw, 100 * ch, npx))

    # --- what the camera actually is --------------------------------------
    cam = run("""
import maya.cmds as cmds
_c = cmds.camera()[0]
_s = cmds.listRelatives(_c, shapes=True, fullPath=True)[0]
import math as _m
_f = cmds.getAttr(_s + '.focalLength')
_h = cmds.getAttr(_s + '.horizontalFilmAperture')
_v = cmds.getAttr(_s + '.verticalFilmAperture')
out = {'focal_mm': round(_f, 4),
       'h_aperture_in': round(_h, 4), 'v_aperture_in': round(_v, 4),
       'fov_h_deg': round(2*_m.degrees(_m.atan((_h*25.4/2)/_f)), 3),
       'fov_v_deg': round(2*_m.degrees(_m.atan((_v*25.4/2)/_f)), 3),
       'film_fit': cmds.getAttr(_s + '.filmFit')}
cmds.delete(_c)
out
""", "default camera")
    print("\nDEFAULT cmds.camera(): focal %(focal_mm)s mm, apertures "
          "h=%(h_aperture_in)s\" v=%(v_aperture_in)s\", filmFit=%(film_fit)s"
          % cam)
    print("  -> horizontal FOV %(fov_h_deg)s deg, vertical FOV %(fov_v_deg)s deg"
          % cam)

    # Which axis the measured coverage implies, read back from the picture.
    for axis, frac in (("width", cw), ("height", ch)):
        if not frac:
            continue
        half = math.degrees(math.asin(min(1.0, sphere_r / distance)))
        implied = 2 * half / frac
        print("  measured %s implies an effective FOV of %.2f deg"
              % (axis, implied))

    # --- render path: the control, focal length forced to match -----------
    rres = call("render_scene", {"angles": ["front"], "renderer": "hw2",
                                 "resolution": RES}, timeout_s=900.0)
    rendered = None
    if rres.get("status") == "ok":
        rimg = ((rres.get("result") or {}).get("images") or [{}])[0]
        if rimg.get("png_b64"):
            rw, rh, rn = subject_extent(rimg["png_b64"])
            rendered = {"width_frac": rw, "height_frac": rh, "px": rn}
            with open(os.path.join(OUT_DIR, "render_front.png"), "wb") as fh:
                fh.write(base64.b64decode(rimg["png_b64"]))
            print("\nRENDER (focal forced to _FOV_DEG - the control):")
            print("  subject spans %.1f%% of frame width, %.1f%% of height"
                  % (100 * rw, 100 * rh))
    else:
        print("\nrender skipped: %r" % (rres.get("error") or {}).get("message"))

    report = {"assumed_fov_deg": capture_mod._FOV_DEG,
              "fit_margin": capture_mod._FIT_MARGIN,
              "distance_over_radius": distance / sphere_r,
              "intended_coverage": intended,
              "capture": {"width_frac": cw, "height_frac": ch},
              "camera": cam, "render": rendered}
    with open(os.path.join(OUT_DIR, "report.json"), "w") as fh:
        json.dump(report, fh, indent=1)
    print("\nwrote %s" % os.path.join(OUT_DIR, "report.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
