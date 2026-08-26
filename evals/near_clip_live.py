"""#670 live gate: the render camera's near plane moves with the framing.

The defect, measured in Maya 2027: `render_scene` builds its camera with
`cmds.camera()` and never touches `nearClipPlane`, so the plane sits at Maya's
absolute 0.1 scene units - while the framing distance is
`3.3627 * bounding_sphere_radius`, divided by `zoom`. One number scales with
the subject, the other does not, so a close enough framing walks the subject
through a plane that never moved.

WHICH RENDERER MATTERS, and this cost a wrong reproduction before it was
measured: **hw2 ignores nearClipPlane entirely**. Forced to 0.6 - deeper than
the whole fixture - an hw2 frame came back pixel-identical. **Arnold honours
it**, and Arnold is the default renderer and the one anyone judging a material
is using. So this gate renders with Arnold; an hw2 version of it would pass on
code that renders black.

And black is what it is. Not a cosmetic slice: at zoom 5 on the fixture below,
the old fixed plane cut away the whole of the subject filling the frame - mean
luma 0.6 of 255 - where the same frame with a framing-derived plane comes back
fully lit at 119.7. The residue is measured too: what survives the cut is the
big ball behind, standing in the clipped ball's shadow (isolated and rendered
alone at this framing it reads 123.5, so the darkness is the shadow, and the
missing 119.7 is the subject).

The fixture puts a small ball in front of a big one and frames them together,
so the camera ends up close to the small one while the scene still has
something behind it. Claim 3 renders that framing TWICE: once with
`near_clip_for` temporarily forced back to the old fixed 0.1 inside the
disposable Maya, once with the shipped function. That pair is the gate's real
product - the before frame is what the tool used to return.

Usage:

    set MAYA_MCP_PORT=9877
    python evals/near_clip_live.py

MUTATES THE ANSWERING MAYA'S CURRENT SCENE (new_scene, two spheres, five
Arnold renders, and a temporary monkeypatch of one product function that is
restored before exit). Point MAYA_MCP_PORT at a disposable Maya you launched
yourself - never the user's live modelling session (server `maya9879`).

Exit: 0 pass, 1 fail. Writes every frame to evals/near_clip_live/ - report the
zoom 5 before/after pair for visual judgment.
"""

from __future__ import annotations

import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_call import call  # noqa: E402
from maya_plugin.handlers import pngprobe  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "near_clip_live")
BIG, SMALL = "nearclip_big", "nearclip_small"
# Maya's default on a fresh camera - the plane the tool used to leave in place.
OLD_FIXED_NEAR = 0.1
# A frame this dark is not a picture of anything. The measured before/after
# pair is 0.6 against 119.7, so the threshold is nowhere near either edge.
DARK_LUMA = 10.0

failures: list = []


def fail(message: str) -> None:
    failures.append(message)
    print("FAIL: " + message)


def preflight() -> dict:
    """Refuse to run against a stale or unidentified plugin (#648, #703)."""
    frame = call("ping", {})
    if frame.get("status") != "ok":
        raise SystemExit("ping failed: %r" % (frame.get("error"),))
    ping = frame.get("result") or {}
    if not ping:
        raise SystemExit("no Maya answered - start one, or check "
                         "MAYA_MCP_PORT. Do NOT fall back to batchmode.")
    if (ping.get("plugin") or {}).get("restart_required"):
        raise SystemExit(
            "the answering Maya (pid %s) holds stale modules - restart it "
            "before running this gate"
            % (ping.get("process") or {}).get("pid"))
    return ping


def python(code: str, timeout_s: float = 60.0):
    frame = call("execute_python", {"code": code, "timeout_s": timeout_s},
                 timeout_s=timeout_s + 30)
    if frame.get("status") != "ok":
        raise SystemExit("execute_python failed: %r" % (frame.get("error"),))
    return (frame.get("result") or {}).get("result_repr")


def build_scene() -> None:
    """A small ball parked in front of a big one, framed as one subject.

    The sizes are not arbitrary: they put the small ball well inside the old
    0.1 plane at zoom 5 while leaving something behind it to render, so an
    empty frame means clipping and not an empty scene.
    """
    frame = call("new_scene", {"confirm": True, "linear_unit": "cm"})
    if frame.get("status") != "ok":
        raise SystemExit("new_scene failed: %r" % (frame.get("error"),))
    python(
        "import maya.cmds as cmds\n"
        "cmds.polySphere(r=0.5, sx=32, sy=32, name=%r)\n"
        "small = cmds.polySphere(r=0.08, sx=24, sy=24, name=%r)[0]\n"
        "cmds.xform(small, t=(0, 0, 0.55))\n"
        "cmds.select(clear=True)\n"
        "'built'\n" % (BIG, SMALL)
    )


def force_near(value) -> None:
    """Pin (or release) `near_clip_for` inside the answering Maya.

    The only way to render what the tool USED to return without shipping the
    defect alongside the fix. Confined to the disposable session and always
    released in `main`'s finally.
    """
    if value is None:
        python("from maya_plugin.handlers import render as R\n"
               "if hasattr(R, '_gate_orig_near'):\n"
               "    R.near_clip_for = R._gate_orig_near\n"
               "    del R._gate_orig_near\n"
               "'released'\n")
        return
    python("from maya_plugin.handlers import render as R\n"
           "if not hasattr(R, '_gate_orig_near'):\n"
           "    R._gate_orig_near = R.near_clip_for\n"
           "R.near_clip_for = lambda *a, **k: %r\n"
           "'forced'\n" % float(value))


def nearest_vertex(position) -> float:
    """Distance from `position` to the closest vertex of the whole subject.

    The handler reasons about the bounding BOX, which is a bound and not the
    surface. A gate that re-used the same box would only be checking the
    handler's arithmetic against itself, so this asks Maya for the mesh.
    """
    return float(python(
        "import maya.cmds as cmds, math\n"
        "p = %r\n"
        "best = None\n"
        "for mesh in (%r, %r):\n"
        "    n = cmds.polyEvaluate(mesh, vertex=True)\n"
        "    pts = cmds.xform(mesh + '.vtx[0:%%d]' %% (n - 1), q=True,\n"
        "                     ws=True, t=True)\n"
        "    for i in range(0, len(pts), 3):\n"
        "        d = math.dist(p, pts[i:i + 3])\n"
        "        best = d if best is None else min(best, d)\n"
        "best\n" % (list(position), BIG, SMALL), timeout_s=120.0))


def mean_luma(path: str) -> float:
    png = pngprobe.read_png(path)
    pixels = png["pixels"]
    if not pixels:
        return 0.0
    return sum(sum(p[:3]) / 3.0 for p in pixels) / len(pixels)


def render(zoom: float, out_name: str) -> dict:
    """One Arnold frame, saved. Arnold because hw2 cannot see this defect."""
    frame = call("render_scene", {
        "angles": ["front"], "renderer": "arnold", "resolution": 384,
        "samples": 2, "zoom": zoom,
    }, timeout_s=600.0)
    if frame.get("status") != "ok":
        raise SystemExit("render_scene(zoom=%s) failed: %r"
                         % (zoom, frame.get("error")))
    result = frame.get("result") or {}
    images = result.get("images") or []
    if not images:
        raise SystemExit("render_scene(zoom=%s) returned no images" % zoom)
    path = os.path.join(OUT_DIR, out_name)
    with open(path, "wb") as fh:
        fh.write(base64.b64decode(images[0]["png_b64"]))
    result["_path"] = path
    result["_luma"] = mean_luma(path)
    print("  wrote %s (mean luma %.1f)" % (path, result["_luma"]))
    return result


def shot_of(result: dict) -> dict:
    return (result.get("camera_positions") or [{}])[0]


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    ping = preflight()
    print("answering Maya: pid %s" % (ping.get("process") or {}).get("pid"))
    build_scene()
    try:
        print("claim 1: a comfortable framing keeps the plane it always had")
        result = render(1.0, "near_clip_zoom1.png")
        near1 = shot_of(result).get("near_clip")
        if near1 != OLD_FIXED_NEAR:
            fail("zoom 1.0: near_clip is %r, expected Maya's own %.1f - the "
                 "cap exists so a framing that already worked is untouched"
                 % (near1, OLD_FIXED_NEAR))
        else:
            print("  near_clip=%.4f (unchanged)" % near1)
        # Other warnings (IPR hygiene, sheet nesting) share this list and are
        # not this gate's business; a framing warning here would be a false
        # alarm at a framing 2.5 away from the subject.
        if any("INSIDE the framed bounding box" in w
               for w in (result.get("warnings") or [])):
            fail("zoom 1.0: warned that the camera is inside the subject "
                 "(warnings=%r)" % (result["warnings"],))

        print("claim 2: the control framing, which never clipped")
        result = render(4.0, "near_clip_zoom4.png")
        shot = shot_of(result)
        closest = nearest_vertex(shot["position"])
        print("  near_clip=%.6f nearest_vertex=%.4f"
              % (shot["near_clip"], closest))
        if not OLD_FIXED_NEAR < closest:
            fail("zoom 4.0 is not a control: the old fixed %.1f plane already "
                 "cut the closest vertex at %.4f" % (OLD_FIXED_NEAR, closest))
        if result["_luma"] <= DARK_LUMA:
            fail("zoom 4.0 rendered dark (%.1f) before anything was clipped - "
                 "the fixture or the lighting is wrong, not the near plane"
                 % result["_luma"])

        print("claim 3: the framing the old fixed plane emptied out")
        force_near(OLD_FIXED_NEAR)
        before = render(5.0, "near_clip_zoom5_before.png")
        force_near(None)
        after = render(5.0, "near_clip_zoom5_after.png")
        shot = shot_of(after)
        closest = nearest_vertex(shot["position"])
        print("  near_clip=%.6f nearest_vertex=%.4f"
              % (shot["near_clip"], closest))
        if not shot["near_clip"] < closest:
            fail("zoom 5.0: the plane at %.6f is NOT in front of the closest "
                 "vertex at %.4f" % (shot["near_clip"], closest))
        if before["_luma"] > DARK_LUMA:
            fail("zoom 5.0: forcing the old %.1f plane back did NOT empty the "
                 "frame (mean luma %.1f) - this fixture no longer reproduces "
                 "the defect, so the gate proves nothing"
                 % (OLD_FIXED_NEAR, before["_luma"]))
        if after["_luma"] <= DARK_LUMA:
            fail("zoom 5.0: still dark (mean luma %.1f) with the shipped "
                 "plane - the subject is being clipped away"
                 % after["_luma"])
        print("  before %.1f -> after %.1f mean luma"
              % (before["_luma"], after["_luma"]))

        print("claim 4: a camera inside the framed box says so")
        result = render(8.0, "near_clip_zoom8.png")
        inside = [w for w in (result.get("warnings") or [])
                  if "INSIDE the framed bounding box" in w]
        if not inside:
            fail("zoom 8.0: the camera is inside the subject and nothing said "
                 "so (warnings=%r)" % (result.get("warnings"),))
        else:
            print("  " + inside[0])
    finally:
        force_near(None)

    print()
    if failures:
        print("GATE FAILED (%d)" % len(failures))
        return 1
    print("GATE PASSED - now LOOK at the zoom 5 pair in %s: 'before' is the "
          "frame render_scene used to return, 'after' is the same framing "
          "with the plane derived from it." % OUT_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
