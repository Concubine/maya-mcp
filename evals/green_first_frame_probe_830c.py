"""Probe #830 part 3: does a flush fix it, and is the green detectable?

Part 2 reproduced the report on a 28-mesh scene (part 1's 3-cube fixture never
did): the FIRST frame of a capture call comes back flat green, the later
frames of the SAME call are correct. Measured placeholder colour: exactly
**RGB (0, 208, 57)**, 11040 pixels of one flat value against a lit material's
spread of several.

Two questions left before designing anything:

  L  does `cmds.refresh(force=True)` before the capture actually kill it, and
     RELIABLY - three fresh scenes each way, because a one-shot pass proves
     nothing about a race
  M  is (0, 208, 57) stable enough to DETECT? A flush is a mitigation; #765's
     rule is that a frame which lies gets NAMED, so the fallback has to be
     measurable. Recorded per frame: how much of it is exactly that value, and
     how flat the frame is compared with a correctly shaded one.

Run:  MAYA_MCP_PORT=9878 MAYA_MCP_EXPECT_PID=<pid> python evals/green_first_frame_probe_830c.py

MUTATES THE ANSWERING MAYA'S SCENE. Refuses 9877.
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import green_first_frame_probe_830 as p1  # noqa: E402
import green_first_frame_probe_830b as p2  # noqa: E402

PLACEHOLDER = (0, 208, 57)


def placeholder_share(png_b64: str) -> dict:
    """How much of the frame is EXACTLY the unassigned-green, and how flat."""
    from PIL import Image
    from collections import Counter
    img = Image.open(io.BytesIO(base64.b64decode(png_b64))).convert("RGBA")
    px = [p for p in img.getdata() if p[3] > 0]
    if not px:
        return {"opaque": 0}
    counts = Counter(px)
    exact = sum(n for c, n in counts.items() if c[:3] == PLACEHOLDER)
    top_colour, top_n = counts.most_common(1)[0]
    return {"opaque": len(px),
            "placeholder_px": exact,
            "placeholder_share": round(exact / len(px), 3),
            "distinct": len(counts),
            "top_colour": list(top_colour[:3]),
            "top_share": round(top_n / len(px), 3)}


def build_and_shoot(tag: str, flush: bool) -> dict:
    """A fresh 28-mesh scene VP2 has never drawn, then one 2-angle capture."""
    p1.ok("new_scene", {"confirm": True})
    p1.py(p1.LIB + "\n" + p2.LIB2 + "\nr = 1")
    p1.py("r = prop()")
    p1.py("r = bulk_assign()")
    if flush:
        p1.py("r = flush()")
    res = p1.ok("capture_viewport", {"angles": ["front", "three_quarter"],
                                     "resolution": 256, "lighting": "scene"})
    out = [placeholder_share(img["png_b64"]) for img in res["images"]]
    for i, img in enumerate(res["images"]):
        p1.colours(img["png_b64"], "%s_%d_%s" % (tag, i, img["angle"]))
    print("  %-22s frame1 placeholder=%.0f%% distinct=%d | frame2 placeholder=%.0f%%"
          % (tag, 100 * out[0]["placeholder_share"], out[0]["distinct"],
             100 * out[1]["placeholder_share"]))
    return {"frames": out,
            "frame1_is_placeholder": out[0]["placeholder_share"] > 0.25}


def main():
    print("### probe 830c on port %s" % p1.PORT)
    print("answering Maya: pid %s"
          % (p1.ok("ping", {}).get("process") or {}).get("pid"))

    print("\nL. control - no flush, three fresh scenes")
    control = [build_and_shoot("L_control_%d" % i, flush=False) for i in range(3)]

    print("\nL. with cmds.refresh(force=True) before the capture, three more")
    flushed = [build_and_shoot("L_flushed_%d" % i, flush=True) for i in range(3)]

    p1.show("L does a flush fix it", {
        "control_green_first_frames": sum(1 for r in control
                                          if r["frame1_is_placeholder"]),
        "flushed_green_first_frames": sum(1 for r in flushed
                                          if r["frame1_is_placeholder"]),
        "control_shares": [r["frames"][0]["placeholder_share"] for r in control],
        "flushed_shares": [r["frames"][0]["placeholder_share"] for r in flushed],
    })

    bad = [r["frames"][0] for r in control if r["frame1_is_placeholder"]]
    good = [r["frames"][1] for r in control] + [f for r in flushed
                                                for f in r["frames"]]
    p1.show("M is the placeholder detectable", {
        "placeholder_rgb": list(PLACEHOLDER),
        "bad_frames": {"n": len(bad),
                       "share_range": [min(f["placeholder_share"] for f in bad),
                                       max(f["placeholder_share"] for f in bad)]
                       if bad else None,
                       "distinct_range": [min(f["distinct"] for f in bad),
                                          max(f["distinct"] for f in bad)]
                       if bad else None},
        "good_frames": {"n": len(good),
                        "max_placeholder_share": max(f["placeholder_share"]
                                                     for f in good),
                        "distinct_range": [min(f["distinct"] for f in good),
                                           max(f["distinct"] for f in good)]},
    })
    print("\nfindings -> %s" % os.path.join(p1.OUT, "findings.json"))


if __name__ == "__main__":
    main()
