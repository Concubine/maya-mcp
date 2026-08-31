"""#770 live gate: the contact shadow the golem never had, measured.

The delivered golem's joins fail under SSAO - gasket collars show almost no
contact darkening (evals/golem_delivery/README.md). This gate builds that
exact geometry class in a live Maya - a limb standing on the ground with a
collar ringed around it - bakes mesh maps, applies the AO into the colour
maps, and measures three things no headless test can:

  1. The GROUND's baked AO is darker under the limb than in the open
     (map-space measurement through known UVs);
  2. the render AFTER apply_ao is measurably darker than BEFORE, through
     the same render_scene path on the same scene - the shadow is in the
     shipped look, not in a renderer's screen-space pass;
  3. the composite colour maps ride the exported FBX's bytes.

Usage (no "verify a prebuilt scene" mode - everything worth measuring is
built by this run):

    set MAYA_MCP_PORT=9878
    python evals/meshmaps_live.py --build

MUTATES THE ANSWERING MAYA'S CURRENT SCENE (new_scene first). Point
MAYA_MCP_PORT at a disposable Maya you launched yourself - never the
user's session on 9877.

Exit: 0 pass, 1 fail. Writes renders, maps and the FBX to
evals/meshmaps_live/ - report BOTH renders for visual judgment; a
contact shadow that is technically present but visibly wrong is a
FINDING this script cannot call by itself.
"""

from __future__ import annotations

import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live_call import call  # noqa: E402

from maya_plugin.handlers import pngprobe  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "meshmaps_live")
BEFORE_RENDER = os.path.join(OUT_DIR, "meshmaps_before.png")
AFTER_RENDER = os.path.join(OUT_DIR, "meshmaps_after.png")
AFTER_FBX = os.path.join(OUT_DIR, "meshmaps_after.fbx")

RENDER_PARAMS = {"angles": ["three_quarter"], "renderer": "arnold",
                 "resolution": 512, "samples": 4}

# The measured bar for "the map carries a contact shadow": probe S3 put the
# gap at 3.9-under vs 251-away on a raw bake. After compositing into a 0.8
# grey and re-encoding sRGB the gap compresses, so the gate asks for a
# still-unmissable 60/255 in the MAP and a 2/255 mean-luma drop in the
# RENDER (the shadow occupies a small fraction of the frame).
MAP_GAP_MIN = 60
RENDER_LUMA_DROP_MIN = 2.0

failures: list[str] = []
findings: list[str] = []


def check(name: str, ok: bool, detail: str) -> None:
    line = "%s %s: %s" % ("PASS" if ok else "FAIL", name, detail)
    print(line, flush=True)
    findings.append(line)
    if not ok:
        failures.append(line)


def must(frame: dict, what: str) -> dict:
    if frame.get("status") != "ok":
        raise SystemExit("%s failed: %r" % (what, frame.get("error")))
    return frame.get("result") or {}


def preflight() -> dict:
    ping = must(call("ping", {}), "ping")
    plugin = ping.get("plugin") or {}
    process = ping.get("process") or {}
    if plugin.get("restart_required"):
        raise SystemExit(
            "the answering Maya (pid %s) holds stale modules - restart it "
            "before running this gate" % process.get("pid"))
    print("gating against pid %s, scene %r" % (process.get("pid"),
                                               process.get("scene")),
          flush=True)
    return ping


def build_scene() -> dict:
    """The golem-join proxy: a limb cylinder standing on a ground plane,
    with a collar torus ringed around it - the geometry class whose
    delivered version reads as 'balls threaded on a limb'."""
    must(call("new_scene", {"confirm": True}), "new_scene")

    ground = must(call("create_primitive",
                       {"kind": "plane", "name": "gate_ground",
                        "size": {"width": 6.0, "depth": 6.0}}),
                  "create_primitive(plane)").get("name") or "|gate_ground"
    limb = must(call("create_primitive",
                     {"kind": "cylinder", "name": "gate_limb",
                      "size": {"radius": 0.4, "height": 3.0},
                      "position": [0, 1.5, 0]}),
                "create_primitive(cylinder)").get("name") or "|gate_limb"
    collar = must(call("create_primitive",
                       {"kind": "torus", "name": "gate_collar",
                        "size": {"radius": 0.55, "section_radius": 0.18},
                        "position": [0, 1.5, 0]}),
                  "create_primitive(torus)").get("name") or "|gate_collar"

    for mesh in (ground, limb, collar):
        must(call("uv_atlas", {"names": [mesh], "project": "box"}),
             "uv_atlas(%s)" % mesh)
    for mesh, mat in ((ground, "gate_ground_mat"), (limb, "gate_limb_mat"),
                      (collar, "gate_collar_mat")):
        must(call("assign_material",
                  {"mesh": mesh, "shader": "standardSurface", "name": mat,
                   "params": {"base_color": [0.75, 0.75, 0.75],
                              "roughness": 0.6, "metalness": 0.0}}),
             "assign_material(%s)" % mat)

    must(call("setup_lighting", {"preset": "three_point", "intensity": 1.5}),
         "setup_lighting")
    return {"ground": ground, "limb": limb, "collar": collar}


def render_to(path: str, label: str) -> float:
    result = must(call("render_scene", dict(RENDER_PARAMS), timeout_s=600.0),
                  "render_scene(%s)" % label)
    images = result.get("images") or []
    if not images:
        raise SystemExit("render_scene(%s) returned no images" % label)
    png = base64.b64decode(images[0]["png_b64"])
    with open(path, "wb") as fh:
        fh.write(png)
    data = pngprobe.read_png(path)
    total = sum(p[0] + p[1] + p[2] for p in data["pixels"])
    return total / (3.0 * len(data["pixels"]))


def region_mean(path: str, u0: float, u1: float, v0: float, v1: float) -> float:
    png = pngprobe.read_png(path)
    w, h, px = png["width"], png["height"], png["pixels"]
    vals = [px[y * w + x][0]
            for y in range(h) for x in range(w)
            if u0 <= (x + 0.5) / w <= u1
            and v0 <= 1.0 - (y + 0.5) / h <= v1]
    return sum(vals) / max(len(vals), 1)


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    preflight()
    scene = build_scene()

    before_luma = render_to(BEFORE_RENDER, "before")
    print("before render mean luma: %.2f" % before_luma, flush=True)

    bake = must(call("bake_mesh_maps",
                     {"meshes": [scene["ground"], scene["limb"],
                                 scene["collar"]],
                      "out_dir": OUT_DIR, "resolution": 512,
                      "apply_ao": True}, timeout_s=900.0),
                "bake_mesh_maps")

    baked = bake.get("baked") or []
    check("nine_maps_baked", len(baked) == 9,
          "%d maps (3 meshes x ao/curvature/world_normal)" % len(baked))
    for entry in baked:
        stats = entry.get("stats") or {}
        check("map_not_blank:%s" % entry["basename"],
              stats.get("blank") is False,
              "blank=%r distinct=%r" % (stats.get("blank"),
                                        stats.get("distinct_values")))
    ao_maps = {e["mesh"]: e for e in baked if e["map"] == "ao"}
    for mesh_key in ("ground", "limb", "collar"):
        entry = ao_maps.get(scene[mesh_key])
        check("ao_non_uniform:%s" % mesh_key,
              bool(entry and entry["stats"]["non_uniform"]),
              "stats=%r" % ((entry or {}).get("stats"),))

    # 1. map-space: the ground is darker under the limb than in the open.
    ground_ao = ao_maps.get(scene["ground"])
    if ground_ao:
        under = region_mean(ground_ao["file"], 0.42, 0.58, 0.42, 0.58)
        away = region_mean(ground_ao["file"], 0.02, 0.14, 0.02, 0.14)
        check("ground_ao_contact_gap", under < away - MAP_GAP_MIN,
              "under=%.1f away=%.1f gap=%.1f (min %d)"
              % (under, away, away - under, MAP_GAP_MIN))

    applied = bake.get("applied") or []
    check("three_materials_applied", len(applied) == 3,
          "%d applied, checkpoint=%r" % (len(applied),
                                         bake.get("checkpoint_id")))

    # 2. render-space: the shadow is in the shipped look now.
    after_luma = render_to(AFTER_RENDER, "after")
    drop = before_luma - after_luma
    check("render_darkened_by_applied_ao", drop >= RENDER_LUMA_DROP_MIN,
          "before=%.2f after=%.2f drop=%.2f (min %.1f)"
          % (before_luma, after_luma, drop, RENDER_LUMA_DROP_MIN))

    # 3. the composites ride the export's bytes.
    export = must(call("export_fbx",
                       {"path": AFTER_FBX.replace("\\", "/"),
                        "metres_per_unit": 1.0,
                        "nodes": [scene["ground"], scene["limb"],
                                  scene["collar"]],
                        "require_baked_textures": True}, timeout_s=300.0),
                  "export_fbx")
    with open(AFTER_FBX, "rb") as fh:
        fbx_bytes = fh.read()
    for entry in applied:
        check("composite_in_fbx_bytes:%s" % entry["basename"],
              entry["basename"].encode() in fbx_bytes,
              "%d byte file" % len(fbx_bytes))
    check("export_dropped_nothing",
          not (export.get("textures") or {}).get("dropped_maps"),
          "dropped=%r" % ((export.get("textures") or {}).get("dropped_maps"),))

    for warning in bake.get("warnings") or []:
        print("WARNING from bake_mesh_maps: %s" % warning, flush=True)

    print("\n%s - %d checks, %d failed. Renders: %s / %s"
          % ("GATE FAILED" if failures else "GATE PASSED",
             len(findings), len(failures), BEFORE_RENDER, AFTER_RENDER),
          flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    if "--build" not in sys.argv:
        raise SystemExit(__doc__)
    raise SystemExit(main())
