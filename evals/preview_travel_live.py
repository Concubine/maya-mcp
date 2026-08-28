"""#780 regression gate: preview_clip on a clip with ROOT MOTION must show
the subject in EVERY cell, and every cell must be a DIFFERENT image.

The defect this guards against (measured 2026-08-28, #780): preview_clip
framed its held camera on the subject's FRAME-0 bounding box only, so a
clip that travels (the #774 CMU walk covers ~4.8 m) walked its subject out
of the frame mid-clip - every cell after the exit frame was the same
byte-identical, subject-less render, and nothing said so. The sheet
"passed" while silently showing garbage motion for a third of the clip.
Root cause was measured, not guessed: the DG, CPU skin and per-frame bbox
all kept moving at the frozen frames (probes with refresh/EM-off/GPU-off/
cache-off all changed nothing), and the frozen tail's bytes equalled a
render with the mesh HIDDEN - the subject simply was not in the frustum
from frame 105 on.

The fix frames the held camera on the UNION of the subject's bounds across
all sampled frames - the camera still never moves (motion must read
against a fixed frame), it just frames the whole journey. This gate is the
cheap structural check for that promise:

    1  a 3-joint pillar rig, bound, with an author_clip that TRAVELS
       (root_position +Z across ~2.5 body heights) while a mid-joint sways
       (so adjacent samples differ even at a fixed screen position)
    2  preview_clip at DEFAULT zoom, angle=side (travel crosses the view)
    3  every returned cell hashed: ALL DISTINCT (a repeat = a frozen or
       out-of-frame tail, the #780 signature)
    4  every cell carries the subject (pixel_stats: not blank, and a
       minimum opaque coverage so "one sliver pixel" cannot pass)
    5  the call reports no blank-frame warning (none should be needed at
       default zoom now that the framing covers the travel)

MUTATES THE ANSWERING MAYA'S CURRENT SCENE (new_scene).
MAYA_MCP_EXPECT_PID is REQUIRED: a port is not an identity (#648).

Usage:

    set MAYA_MCP_PORT=9878
    set MAYA_MCP_EXPECT_PID=<the pid you launched>
    python evals/preview_travel_live.py

Exit: 0 pass, 1 fail, 2 no connection.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from live_call import call, structured_result  # noqa: E402
from maya_mcp import images  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
OUT_DIR = os.path.join(_HERE, "preview_travel_live")

MESH = "travel_pillar"
TRAVEL_M = 3.0          # ~2.5x the pillar's height - well past frame-0 framing
CLIP_S = 3.0
FPS = 30
# "The subject is in this cell" floor. MEASURED on this fixture's own
# cells (256 px, default zoom, union framing, first green run 2026-08-28):
# the pillar covers a steady 0.30-0.31% of every cell - it is a 0.3 m-wide
# pillar in a ~4 m travel corridor - and an out-of-frame cell covers
# exactly 0.0000. 0.1% sits 3x under every measured cell and infinitely
# above the defect.
MIN_OPAQUE_FRACTION = 0.001

FAILURES = []


def send(command, params, timeout_s=300.0):
    try:
        return call(command, params, timeout_s=timeout_s, port=PORT)
    except (ConnectionRefusedError, OSError) as exc:
        print("could not reach a Maya plugin on %s: %s" % (PORT, exc))
        sys.exit(2)


def ok(command, params, timeout_s=300.0, what=None):
    resp = send(command, params, timeout_s)
    if resp.get("status") != "ok":
        print("FAILED %s: %s" % (what or command,
                                 json.dumps(resp.get("error", resp))[:600]))
        sys.exit(1)
    return resp.get("result") or {}


def check(condition, message):
    print(("  PASS  " if condition else "  FAIL  ") + message)
    if not condition:
        FAILURES.append(message)
    return condition


def main():
    expect = (os.environ.get("MAYA_MCP_EXPECT_PID") or "").strip()
    if not expect:
        raise SystemExit(
            "MAYA_MCP_EXPECT_PID is not set. This gate discards the "
            "answering Maya's scene (new_scene) - launch one yourself and "
            "name its pid (#648). Refusing to guess which Maya is "
            "disposable.")
    os.makedirs(OUT_DIR, exist_ok=True)

    ok("new_scene", {"confirm": True}, 180.0)

    # -- 1. the travelling pillar -------------------------------------
    ok("create_primitive", {"kind": "cylinder", "name": MESH,
                            "divisions": 3, "scale": [0.15, 0.6, 0.15],
                            "translate": [0.0, 0.6, 0.0]}, 60.0)
    skeleton = ok("create_skeleton", {"joints": [
        {"name": "base", "position": [0.0, 0.05, 0.0]},
        {"name": "mid", "position": [0.0, 0.60, 0.0], "parent": "base"},
        {"name": "top", "position": [0.0, 1.15, 0.0], "parent": "mid"},
    ]}, 60.0)
    root = skeleton["root"]
    bind = ok("bind_skin", {"mesh": "|" + MESH, "root": root}, 300.0)
    check(bind.get("unweighted_vertices", 1) == 0,
          "bind_skin leaves no vertex unweighted (unweighted=%s)"
          % bind.get("unweighted_vertices"))

    # -- 2. a clip that TRAVELS while it sways ------------------------
    # Keys every 0.25 s: root_position walks +Z at a steady 1 m/s while
    # the mid joint sways on a non-harmonic sine, so no two sampled cells
    # can legitimately be the same image even ignoring the travel.
    keys = []
    steps = int(CLIP_S / 0.25)
    for i in range(steps + 1):
        t = i * 0.25
        sway = 25.0 * math.sin(2.1 * t)
        keys.append({"time_s": t,
                     "root_position": [0.0, 0.05, TRAVEL_M * t / CLIP_S],
                     "rotations": {"mid": [0.0, sway, sway * 0.5]}})
    clip = ok("author_clip", {"root": root, "name": "travel", "fps": FPS,
                              "keys": keys}, 120.0)
    check(clip.get("root_position_keyed") is True,
          "author_clip keyed the root travel (root_position_keyed=%s)"
          % clip.get("root_position_keyed"))

    # -- 3-5. the sheet: all cells distinct, all cells inhabited ------
    preview = ok("preview_clip", {"root": root, "name": "travel",
                                  "angle": "side", "resolution": 256},
                 300.0, "preview_clip travel")
    frame_imgs = preview.get("images", [])
    check(len(frame_imgs) >= 8,
          "preview returned a dense sheet (%d cells)" % len(frame_imgs))

    pngs = [base64.b64decode(im["png_b64"]) for im in frame_imgs]
    hashes = [hashlib.md5(p).hexdigest() for p in pngs]
    for im, h in zip(frame_imgs, hashes):
        print("    %s %s" % (im.get("label"), h[:8]))
    dupes = {h: [im.get("label") for im, hh in zip(frame_imgs, hashes)
                 if hh == h]
             for h in hashes if hashes.count(h) > 1}
    check(not dupes,
          "every cell is a distinct image (the #780 signature is a "
          "byte-identical run)%s"
          % ("" if not dupes
             else " - duplicates: " + json.dumps(sorted(dupes.values()))))

    empty = []
    for im, png in zip(frame_imgs, pngs):
        stats = images.pixel_stats(png)
        fraction = (stats["opaque_px"] / float(stats["total_px"])
                    if stats["total_px"] else 0.0)
        if stats["blank"] or fraction < MIN_OPAQUE_FRACTION:
            empty.append("%s (opaque %.4f)" % (im.get("label"), fraction))
    check(not empty,
          "every cell carries the subject (>= %.1f%% opaque)%s"
          % (MIN_OPAQUE_FRACTION * 100,
             "" if not empty else " - empty: " + "; ".join(empty)))

    blank_warnings = [w for w in preview.get("warnings", [])
                      if "nothing" in w or "blank" in w]
    check(not blank_warnings,
          "no blank-frame warning at default zoom%s"
          % ("" if not blank_warnings
             else " - got: " + "; ".join(blank_warnings)))

    sheet_path = os.path.join(OUT_DIR, "travel_sheet.png")
    with open(sheet_path, "wb") as fh:
        fh.write(images.contact_sheet(pngs, cols=min(len(pngs), 4)))
    print("  wrote %s" % sheet_path)

    if FAILURES:
        print("\n%d FAILURE(S):" % len(FAILURES))
        for f in FAILURES:
            print("  - " + f)
        sys.exit(1)
    print("\nALL CHECKS PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
