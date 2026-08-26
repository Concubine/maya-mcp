"""#773 live gate: a broken clip is caught by numbers, over the wire.

measure_clip exists because motion had no numbers: author_clip could set any
keyframes and nothing anywhere could say whether the result was broken. This
gate authors the SAME walk twice on a real rig - once clean, once with a
drifting plant and a popped key - and proves the shipped metrics separate
them. Both clips render identically on a contact sheet at a glance; the
whole point is that the numbers do not need the glance.

The discrimination thresholds asserted here are not invented: the #773 probe
measured slide 0.0 vs 0.097 (a 1.0-height rig) and mirror-limb peak-speed
ratio 1.0 vs 2.4 on exactly this fixture, before the tool was written.

FIXTURE NOTE, learned the hard way: create_skeleton auto-orients local X down
the bone, so legs swing on rotateY. Keys of [rx, 0, 0] silently TWIST the
limb instead - the probe's first fixture made that mistake and measured a
walk whose feet barely moved.

Usage:

    set MAYA_MCP_PORT=9878
    set MAYA_MCP_EXPECT_PID=<the pid you launched>
    python evals/motion_qc_live.py

MUTATES THE ANSWERING MAYA'S CURRENT SCENE (new_scene per clip).
MAYA_MCP_EXPECT_PID is REQUIRED: this discards the open scene, so it refuses
to guess which Maya is disposable. A port is not an identity (#648).

Exit: 0 pass, 1 fail.
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_call import call  # noqa: E402

failures: list = []

JOINTS = [
    {"name": "hips", "position": [0, 1.0, 0]},
    {"name": "L_thigh", "parent": "hips", "position": [0.12, 0.95, 0]},
    {"name": "L_shin", "parent": "L_thigh", "position": [0.12, 0.5, 0]},
    {"name": "L_foot", "parent": "L_shin", "position": [0.12, 0.08, 0.05]},
    {"name": "R_thigh", "parent": "hips", "position": [-0.12, 0.95, 0]},
    {"name": "R_shin", "parent": "R_thigh", "position": [-0.12, 0.5, 0]},
    {"name": "R_foot", "parent": "R_shin", "position": [-0.12, 0.08, 0.05]},
]


def fail(message: str) -> None:
    failures.append(message)
    print("FAIL: " + message)


def preflight() -> dict:
    if not (os.environ.get("MAYA_MCP_EXPECT_PID") or "").strip():
        raise SystemExit(
            "MAYA_MCP_EXPECT_PID is not set. This gate discards the answering "
            "Maya's scene, so it will not guess which one is disposable - "
            "launch one yourself and name its pid (#648).")
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


def ok(command: str, params: dict, timeout_s: float = 240.0) -> dict:
    frame = call(command, params, timeout_s=timeout_s)
    if frame.get("status") != "ok":
        raise SystemExit("%s failed: %r" % (command, frame.get("error")))
    return frame.get("result") or {}


def walk_keys(broken: bool) -> list:
    out = []
    for i in range(11):
        t = i / 10.0

        def leg(sw_start):
            ph = (t - sw_start) % 1.0
            if ph < 0.5:
                s = math.sin(ph / 0.5 * math.pi)
                return (-25.0 * s, 35.0 * s)
            return (0.0, 0.0)

        lt, ls = leg(0.0)
        rt, rs = leg(0.5)
        if broken and t < 0.5:
            rt = 8.0 * (t / 0.5)  # the plant drifts instead of holding
        out.append({"time_s": t, "rotations": {
            "L_thigh": [0, lt, 0], "L_shin": [0, ls, 0],
            "R_thigh": [0, rt, 0], "R_shin": [0, rs, 0]}})
    if broken:
        out[3]["rotations"]["L_thigh"][1] += 40.0  # the pop
    return out


def measure(broken: bool) -> dict:
    ok("new_scene", {"confirm": True})
    root = ok("create_skeleton", {"joints": JOINTS})["root"]
    ok("author_clip", {"root": root, "name": "walk", "fps": 30,
                       "interpolation": "smooth", "loop": True,
                       "keys": walk_keys(broken)})
    return ok("measure_clip", {"root": root})


def feet_ratio(result: dict) -> float:
    for pair in result.get("symmetry") or []:
        if (pair["left"], pair["right"]) == ("L_foot", "R_foot"):
            return pair["peak_speed_ratio"]
    fail("no L_foot/R_foot symmetry pair in the result")
    return 0.0


def main() -> int:
    ping = preflight()
    print("answering Maya: pid %s" % (ping.get("process") or {}).get("pid"))

    print("claim 1: the clean walk measures clean")
    clean = measure(broken=False)
    slides = {j: c["max_slide"] for j, c in clean["contacts"].items()}
    print("  slides=%s ratio=%.2f warnings=%d"
          % ({j: round(v, 5) for j, v in slides.items()},
             feet_ratio(clean), len(clean["warnings"])))
    if clean["warnings"]:
        fail("a clean clip was warned about: %r" % (clean["warnings"],))
    if any(v > 1e-3 for v in slides.values()):
        fail("a clean plant slid: %r" % (slides,))
    if not (0.95 <= feet_ratio(clean) <= 1.05):
        fail("clean mirrored feet are asymmetric: %.3f" % feet_ratio(clean))
    for foot in ("L_foot", "R_foot"):
        if not clean["contacts"][foot]["runs"]:
            fail("%s never read as planted in a walk that plants each foot "
                 "half its cycle" % foot)
    if clean["joints"]["L_foot"]["loop_closure"] > 1e-3:
        fail("a looping clip does not close: %.5f"
             % clean["joints"]["L_foot"]["loop_closure"])

    print("claim 2: the broken walk is caught, by name and by number")
    broken = measure(broken=True)
    slide = broken["contacts"]["R_foot"]["max_slide"]
    ratio = feet_ratio(broken)
    named = [w for w in broken["warnings"] if "R_foot" in w and "SLIDES" in w]
    print("  R_foot slide=%.4f (warn at %.4f), L/R ratio=%.2f, warning=%s"
          % (slide, broken["thresholds"]["slide_warn"], ratio, bool(named)))
    if not named:
        fail("the drifting plant was not named: %r" % (broken["warnings"],))
    if slide <= broken["thresholds"]["slide_warn"]:
        fail("the drift (%.4f) did not clear the warn threshold (%.4f) - "
             "this fixture no longer reproduces the defect"
             % (slide, broken["thresholds"]["slide_warn"]))
    if ratio < 1.5:
        fail("the popped key did not show as mirror asymmetry: %.2f" % ratio)

    print("claim 3: the same numbers, separated wide enough to be a verdict")
    margin = slide / max(max(slides.values()), 1e-9)
    print("  slide separation: broken %.4f vs clean %.5f; "
          "ratio separation: %.2f vs %.2f"
          % (slide, max(slides.values()), ratio, feet_ratio(clean)))
    if margin < 10:
        fail("slide separates good from broken by only %.1fx - too narrow "
             "to act on" % margin)

    print()
    if failures:
        print("GATE FAILED (%d)" % len(failures))
        return 1
    print("GATE PASSED - a broken clip is now a measured fact, not a "
          "judgement call about a contact sheet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
