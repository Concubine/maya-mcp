"""Throwaway probe for redmine #836: was the 40-minute bake_mesh_maps a hang or
a cost explosion, and which knob drives the cost?

The kethran run baked its 57,724-tri body at resolution 2048, maps ao +
curvature, curvature_output 'both', curvature_radius 4 (the docstring's 0.1
"suits metre-scale assets", scaled for a cm scene) - and killed Maya after
40 minutes with nothing in out_dir. Nothing in out_dir is by DESIGN (each map
bakes into a private temp folder and is only moved at the very end), so the
only open question is time. This probe measures it on the same mesh.

Matrix, cheapest first, and the series STOPS the moment one call exceeds
BUDGET_S - a wedged Maya on 9878 costs a kill, a wedged series costs an hour:

  tier 256:  ao | curvature r=0.1 convex | curvature r=4 convex | curvature r=4 both
  tier 512:  the same four
  tier 1024: ao | curvature r=4 both

Every timing prints as 'PROBE <name>: <seconds>' and lands in findings.json.
Facts, not assertions.

Run:  MAYA_MCP_PORT=9878 MAYA_MCP_EXPECT_PID=<pid> .venv/Scripts/python.exe evals/bake_hang_probe_836.py

OPENS evals/kethran_run/kethran.ma IN THE ANSWERING MAYA. Refuses 9877.
"""
from __future__ import annotations

import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, _HERE)

from live_call import call  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
if PORT == 9877:
    raise SystemExit("refusing 9877 - that is the user's Maya")
OUT = os.path.join(_HERE, "bake_hang_probe_836")
os.makedirs(OUT, exist_ok=True)
MAPS_DIR = os.path.join(OUT, "maps")
os.makedirs(MAPS_DIR, exist_ok=True)
SCENE = os.path.join(_HERE, "kethran_run", "kethran.ma")
BODY = "|kethran|body"
BUDGET_S = float(os.environ.get("PROBE_BUDGET_S", "600"))
CALL_TIMEOUT_S = 1500.0  # under the dispatcher's 1800 ceiling
FINDINGS: dict = {"port": PORT, "scene": SCENE, "budget_s": BUDGET_S,
                  "calls": []}


def save() -> None:
    with open(os.path.join(OUT, "findings.json"), "w", encoding="utf-8") as fh:
        json.dump(FINDINGS, fh, indent=1, default=str)


def probe(name: str, value) -> None:
    FINDINGS[name] = value
    save()
    print("PROBE %s: %r" % (name, value), flush=True)


def ok(command: str, params: dict, timeout_s: float = 300.0) -> dict:
    frame = call(command, params, timeout_s=timeout_s, port=PORT)
    if frame.get("status") != "ok":
        raise SystemExit("%s failed: %s"
                         % (command, json.dumps(frame.get("error"), indent=1)))
    return frame.get("result") or {}


def clean_maps() -> None:
    for name in os.listdir(MAPS_DIR):
        try:
            os.unlink(os.path.join(MAPS_DIR, name))
        except OSError:
            pass


# ---------------------------------------------------------------- scene

print("opening", SCENE, flush=True)
opened = ok("open_scene", {"path": SCENE.replace("\\", "/"), "confirm": True}, timeout_s=300)
probe("opened", {k: opened.get(k) for k in ("path", "linear_unit", "warnings")
                 if k in opened})

info_frame = call("get_object_info", {"name": BODY}, timeout_s=60, port=PORT)
probe("body", info_frame.get("result") or info_frame.get("error"))

# The run box-projected UVs right before the bake; the saved scene may or may
# not carry them (it was restored from a checkpoint after the kill). Re-do it:
# the bake refuses a UV-less mesh upfront, and that refusal is not the question.
t0 = time.monotonic()
atlas = ok("uv_atlas", {"names": [BODY], "cols": 1, "rows": 1, "patch": 0,
                        "project": "box", "margin": 0.01}, timeout_s=300)
probe("uv_atlas", {"seconds": round(time.monotonic() - t0, 1),
                   "uv_bounds": atlas.get("uv_bounds"),
                   "all_inside": atlas.get("all_inside"),
                   "warnings": atlas.get("warnings")})

# ---------------------------------------------------------------- matrix

MATRIX = [
    # (label, resolution, maps, curvature_radius, curvature_output)
    ("ao@256", 256, ["ao"], None, None),
    ("curv_r0.1_convex@256", 256, ["curvature"], 0.1, "convex"),
    ("curv_r4_convex@256", 256, ["curvature"], 4.0, "convex"),
    ("curv_r4_both@256", 256, ["curvature"], 4.0, "both"),
    ("ao@512", 512, ["ao"], None, None),
    ("curv_r0.1_convex@512", 512, ["curvature"], 0.1, "convex"),
    ("curv_r4_convex@512", 512, ["curvature"], 4.0, "convex"),
    ("curv_r4_both@512", 512, ["curvature"], 4.0, "both"),
    ("ao@1024", 1024, ["ao"], None, None),
    ("curv_r4_both@1024", 1024, ["curvature"], 4.0, "both"),
]

for label, resolution, maps, radius, output in MATRIX:
    clean_maps()
    params = {"meshes": [BODY], "out_dir": MAPS_DIR.replace("\\", "/"),
              "maps": maps, "resolution": resolution, "apply_ao": False}
    if radius is not None:
        params["curvature_radius"] = radius
    if output is not None:
        params["curvature_output"] = output
    print("\n>>> %s" % label, flush=True)
    t0 = time.monotonic()
    frame = call("bake_mesh_maps", params, timeout_s=CALL_TIMEOUT_S, port=PORT)
    seconds = round(time.monotonic() - t0, 1)
    entry = {"label": label, "params": params, "seconds": seconds,
             "status": frame.get("status"),
             "elapsed_ms": frame.get("elapsed_ms")}
    if frame.get("status") == "ok":
        result = frame.get("result") or {}
        entry["baked"] = [{"map": b.get("map"), "basename": b.get("basename"),
                           "stats": b.get("stats")} for b in
                          result.get("baked", [])]
        entry["warnings"] = result.get("warnings")
        entry["files_in_out_dir"] = sorted(os.listdir(MAPS_DIR))
    else:
        entry["error"] = frame.get("error")
    FINDINGS["calls"].append(entry)
    probe(label, seconds)
    save()
    if frame.get("status") != "ok":
        probe("stopped_on_error", label)
        break
    if seconds > BUDGET_S:
        probe("stopped_over_budget", {"label": label, "seconds": seconds})
        break

print("\nfindings ->", os.path.join(OUT, "findings.json"), flush=True)
