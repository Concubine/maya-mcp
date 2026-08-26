"""#714 phase 2 Task 6 live gate: the pixels judged after baking are the
pixels that ship.

Tasks 1-5 proved the bake's BYTES reach the FBX, under mayapy: the PNG
probe, the validation/refusals, the two-phase bake, the MCP surface, and a
real-Maya proof that ONE baked map survives the export that dropped it.
None of that can prove the bake LOOKS like what a builder judged - a bake
that writes a flat grey image passes every byte assertion phase 1/2 write.

This gate renders the scene BEFORE bake_textures runs and AFTER, and the
pair is its real product: two images to look at, alongside the measured
numbers. Both renders come from the SAME live Maya scene through the SAME
render_scene path, so a difference between them is real: bake_textures'
rewire is a PERSISTENT scene edit (procedural network -> file node reading
the baked image), not an export-time trick, so the "after" render is
judging the actual rewired scene, the same one that then gets exported.

The fixture: one cube, uv_atlas box-projected, one standardSurface material
carrying all three of `apply_texture_recipe`'s recipes on the three
DIFFERENT slots `material.SHADER_SLOTS["standardSurface"]` exposes -
color, normal, roughness:

  - ramp_gradient  -> color     (procedural: a `ramp` node)
  - noise_bump     -> normal    (procedural: `noise` through a `bump2d`)
  - file_texture   -> roughness (already file-backed - the survivor;
                                  phase 1 measured this recipe alone never
                                  gets dropped)

Building this exact fixture forced a real product fix (see the module
docstring note below and task-6-report.md): `_ramp_gradient`/
`_file_texture` in texture_recipes.py always wired a node's `.outColor` (a
float3) to the target attribute, which Maya refuses outright for a SCALAR
attribute (`specularRoughness`, the roughness slot's real attr) - "Data
types of source and destination are not compatible", measured live. Fixed
in texture_recipes.py (`_wire_color_output`) to use `.outColorR` for a
scalar destination, the same channel `texbake._bake_source_plug` already
uses for a baked scalar/normal slot.

Usage - this gate has no "verify a prebuilt scene" mode; unlike
drifter_live.py there is nothing worth verifying that was not JUST built by
this exact run, so `--build` is not optional:

    set MAYA_MCP_PORT=9877
    python evals/texbake_live.py --build

MUTATES THE ANSWERING MAYA'S CURRENT SCENE (new_scene, then a cube, a
material, three texture recipes, two renders, two exports, one bake).
Point MAYA_MCP_PORT at a disposable Maya you launched yourself - never the
user's live modelling session (server `maya9879`).

Exit: 0 pass, 1 fail. Writes both renders and both FBXs to
evals/texbake_live/ - report BOTH renders for visual judgment; a bake that
is technically present but visibly wrong (washed out, flat, mis-scaled) is
a FINDING, not a pass, and this script cannot make that call by itself.
"""

from __future__ import annotations

import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_call import call  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "texbake_live")
MESH_NAME = "texbake_cube"
MATERIAL_NAME = "texbake_mat"
SURVIVOR_TEXTURE = os.path.join(OUT_DIR, "texbake_survivor.png")
BEFORE_RENDER = os.path.join(OUT_DIR, "texbake_before.png")
AFTER_RENDER = os.path.join(OUT_DIR, "texbake_after.png")
BEFORE_FBX = os.path.join(OUT_DIR, "texbake_before.fbx")
AFTER_FBX = os.path.join(OUT_DIR, "texbake_after.fbx")

RENDER_PARAMS = {"angles": ["three_quarter"], "renderer": "arnold",
                 "resolution": 512, "samples": 4}


def preflight() -> dict:
    """Refuse to run against a stale or unidentified plugin (#648, #703)."""
    ping_frame = call("ping", {})
    if ping_frame.get("status") != "ok":
        raise SystemExit("ping failed: %r" % (ping_frame.get("error"),))
    ping = ping_frame.get("result") or {}
    if not ping:
        raise SystemExit("no Maya answered - start one, or check "
                         "MAYA_MCP_PORT. Do NOT fall back to batchmode.")
    plugin = ping.get("plugin") or {}
    process = ping.get("process") or {}
    if plugin.get("restart_required"):
        raise SystemExit(
            "the answering Maya (pid %s) holds stale modules - restart it "
            "before running this gate" % process.get("pid"))
    return ping


def _write_survivor_texture(path: str) -> None:
    """A deterministic PNG for the file_texture recipe - no art dependency.

    Same generator shape as drifter_live.py's `_write_texture`, distinct
    colours so it is visually obvious this is a DIFFERENT image.
    """
    import struct
    import zlib
    size = 256
    rows = bytearray()
    for y in range(size):
        rows.append(0)
        for x in range(size):
            v = (x ^ y) & 0xFF
            rows += bytes((30 + v // 4, 160 - v // 3, 90 + v // 5))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
           + chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(png)


def build_scene() -> dict:
    """A fresh, UV-atlased cube carrying all three recipes on three
    different slots of ONE standardSurface material. See the module
    docstring for why roughness (not emission, which this shader's
    `material.SHADER_SLOTS` does not expose to texture recipes at all) is
    the third slot, and the product fix that made wiring it possible.
    """
    new_scene = call("new_scene", {"confirm": True})
    if new_scene.get("status") != "ok":
        raise SystemExit("new_scene failed: %r" % (new_scene.get("error"),))

    # No `scale` here: create_primitive's `scale` is a TRANSFORM scale, and
    # export_fbx's unit gate refuses any node carrying non-identity scale
    # (a compensating node scale would hide a wrong vertex magnitude,
    # #629) - MEASURED live, first run of this gate. A plain 1 m cube is
    # framed fine by render_scene's own bbox-based camera.
    cube_frame = call("create_primitive", {"kind": "cube", "name": MESH_NAME})
    if cube_frame.get("status") != "ok":
        raise SystemExit("create_primitive(cube) failed: %r"
                         % (cube_frame.get("error"),))
    mesh = (cube_frame.get("result") or {}).get("name") or MESH_NAME

    uv_frame = call("uv_atlas", {"names": [mesh], "project": "box"})
    if uv_frame.get("status") != "ok":
        raise SystemExit("uv_atlas failed: %r" % (uv_frame.get("error"),))

    mat_frame = call("assign_material",
                     {"mesh": mesh, "shader": "standardSurface",
                      "name": MATERIAL_NAME,
                      "params": {"metalness": 0.0, "roughness": 0.5}})
    if mat_frame.get("status") != "ok":
        raise SystemExit("assign_material failed: %r"
                         % (mat_frame.get("error"),))

    light_frame = call("setup_lighting",
                       {"preset": "three_point", "intensity": 1.5})
    if light_frame.get("status") != "ok":
        raise SystemExit("setup_lighting failed: %r"
                         % (light_frame.get("error"),))

    os.makedirs(OUT_DIR, exist_ok=True)
    _write_survivor_texture(SURVIVOR_TEXTURE)

    ramp_frame = call("apply_texture_recipe",
                      {"mesh": mesh, "recipe": "ramp_gradient",
                       "slot": "color"})
    if ramp_frame.get("status") != "ok":
        raise SystemExit("apply_texture_recipe(ramp_gradient, color) "
                         "failed: %r" % (ramp_frame.get("error"),))
    ramp = ramp_frame.get("result") or {}

    noise_frame = call("apply_texture_recipe",
                       {"mesh": mesh, "recipe": "noise_bump",
                        "slot": "normal"})
    if noise_frame.get("status") != "ok":
        raise SystemExit("apply_texture_recipe(noise_bump, normal) "
                         "failed: %r" % (noise_frame.get("error"),))
    noise = noise_frame.get("result") or {}

    filed_frame = call("apply_texture_recipe",
                       {"mesh": mesh, "recipe": "file_texture",
                        "slot": "roughness",
                        "params": {"file_path": SURVIVOR_TEXTURE}})
    if filed_frame.get("status") != "ok":
        raise SystemExit("apply_texture_recipe(file_texture, roughness) "
                         "failed: %r" % (filed_frame.get("error"),))
    filed = filed_frame.get("result") or {}

    return {"mesh": mesh, "material": MATERIAL_NAME,
            "procedural_nodes": list(ramp.get("nodes") or [])
                                + list(noise.get("nodes") or []),
            "survivor_nodes": list(filed.get("nodes") or []),
            "recipe_warnings": {"ramp_gradient": ramp.get("warnings"),
                                "noise_bump": noise.get("warnings"),
                                "file_texture": filed.get("warnings")}}


def render_and_save(label: str, path: str) -> dict:
    resp = call("render_scene", dict(RENDER_PARAMS), timeout_s=600.0)
    if resp.get("status") != "ok":
        raise SystemExit("render_scene(%s) failed: %r"
                         % (label, resp.get("error"),))
    images = (resp.get("result") or {}).get("images") or []
    if not images:
        raise SystemExit("render_scene(%s) returned no images" % label)
    png = base64.b64decode(images[0]["png_b64"])
    with open(path, "wb") as fh:
        fh.write(png)
    return {"label": label, "path": path, "bytes": len(png)}


def export_and_record(path: str, mesh: str, require_baked: bool) -> dict:
    return call("export_fbx",
               {"path": path, "metres_per_unit": 1.0, "nodes": [mesh],
                "include_skins": False, "include_animation": False,
                "require_baked_textures": require_baked}, timeout_s=180.0)


def _basename_in_bytes(path: str, basename: str) -> bool:
    """Independent of the product's own textures/file_maps report - open
    the exported FBX and look for the literal basename in the raw bytes."""
    with open(path, "rb") as fh:
        raw = fh.read()
    return basename.encode("utf-8", "ignore") in raw


def main() -> int:
    ping = preflight()
    process = ping.get("process") or {}
    plugin = ping.get("plugin") or {}

    problems = []

    scene = build_scene()
    mesh = scene["mesh"]

    before_render = render_and_save("before", BEFORE_RENDER)

    before_export = export_and_record(BEFORE_FBX, mesh, require_baked=False)
    if before_export.get("status") != "ok":
        raise SystemExit("export_fbx(before) failed: %r"
                         % (before_export.get("error"),))
    before_result = before_export.get("result") or {}
    before_textures = before_result.get("textures") or {}
    dropped_before = before_textures.get("dropped_maps") or []
    file_maps_before = before_textures.get("file_maps") or []
    if len(dropped_before) != 2:
        problems.append(
            "export BEFORE bake: expected exactly 2 dropped procedural "
            "maps (ramp_gradient/color, noise_bump/normal), got %d: %r"
            % (len(dropped_before), dropped_before))
    if not any((m.get("slot") == "roughness" and m.get("found_in_file"))
              for m in file_maps_before):
        problems.append(
            "export BEFORE bake: the file_texture survivor (roughness "
            "slot) is not reported found_in_file in file_maps: %r"
            % (file_maps_before,))

    bake_frame = call("bake_textures",
                     {"meshes": [mesh], "out_dir": OUT_DIR,
                      "resolution": 1024}, timeout_s=300.0)
    if bake_frame.get("status") != "ok":
        raise SystemExit("bake_textures failed: %r"
                         % (bake_frame.get("error"),))
    bake_result = bake_frame.get("result") or {}
    baked = bake_result.get("baked") or []
    if len(baked) != 2:
        problems.append(
            "bake_textures: expected 2 baked entries (color, normal), "
            "got %d: %r" % (len(baked), [b.get("slot") for b in baked]))
    for entry in baked:
        file_path = entry.get("file") or ""
        size = os.path.getsize(file_path) if os.path.isfile(file_path) else 0
        entry["_measured_bytes_on_disk"] = size
        if size == 0:
            problems.append("baked file %r is missing or empty on disk"
                            % file_path)
        check = entry.get("pixel_check") or {}
        if not check.get("non_uniform"):
            problems.append(
                "baked %s.%s (%s) pixel_check reports non_uniform=%r "
                "(distinct_values=%r) - a flat image is not a real bake"
                % (entry.get("material"), entry.get("attr"),
                   entry.get("slot"), check.get("non_uniform"),
                   check.get("distinct_values")))

    after_render = render_and_save("after", AFTER_RENDER)

    after_export = export_and_record(AFTER_FBX, mesh, require_baked=True)
    if after_export.get("status") != "ok":
        problems.append(
            "export_fbx AFTER bake with require_baked_textures=True FAILED "
            "(the strict delivery gate is still refusing this scene): %r"
            % (after_export.get("error"),))
        after_textures: dict = {}
    else:
        after_result = after_export.get("result") or {}
        after_textures = after_result.get("textures") or {}

    dropped_after = after_textures.get("dropped_maps") or []
    if dropped_after:
        problems.append("export AFTER bake: dropped_maps is not empty: %r"
                        % (dropped_after,))

    file_maps_after = after_textures.get("file_maps") or []
    if len(file_maps_after) != 3:
        problems.append(
            "export AFTER bake: expected exactly 3 file_maps entries (2 "
            "baked + 1 original survivor), got %d: %r"
            % (len(file_maps_after), file_maps_after))
    not_found = [m for m in file_maps_after if not m.get("found_in_file")]
    if not_found:
        problems.append("export AFTER bake: %d file_maps entr(y/ies) report "
                        "found_in_file=False: %r"
                        % (len(not_found), not_found))

    bytes_present = {}
    if os.path.isfile(AFTER_FBX):
        for entry in baked:
            basename = entry.get("basename") or os.path.basename(
                entry.get("file") or "")
            present = bool(basename) and _basename_in_bytes(AFTER_FBX, basename)
            bytes_present[basename] = present
            if not present:
                problems.append(
                    "independent byte check: baked basename %r is NOT "
                    "present in the raw bytes of %s" % (basename, AFTER_FBX))
    else:
        problems.append("AFTER fbx %r does not exist to byte-check"
                        % AFTER_FBX)

    for p in problems:
        print("FAIL: %s" % p)

    print("maya pid=%s plugin_digest=%s scene=%r"
         % (process.get("pid"), plugin.get("loaded_digest"),
            process.get("scene")))
    print("mesh=%r material=%r procedural_nodes=%r survivor_nodes=%r"
         % (mesh, scene["material"], scene["procedural_nodes"],
            scene["survivor_nodes"]))
    print("before render: %s (%d bytes)"
         % (before_render["path"], before_render["bytes"]))
    print("after render:  %s (%d bytes)"
         % (after_render["path"], after_render["bytes"]))
    print("baked entries: %r"
         % ([{"material": b.get("material"), "slot": b.get("slot"),
               "basename": b.get("basename"),
               "bytes_on_disk": b.get("_measured_bytes_on_disk"),
               "distinct_values": (b.get("pixel_check") or {}).get(
                   "distinct_values")}
              for b in baked],))
    print("independent byte-presence in AFTER fbx: %r" % (bytes_present,))
    print("#714 task 6 verdict: dropped_before=%d baked=%d "
         "distinct_pixels_per_bake=%r dropped_after=%d "
         "require_baked_textures=%s before_render=%r after_render=%r"
         % (len(dropped_before), len(baked),
            [(b.get("slot"), (b.get("pixel_check") or {}).get(
                "distinct_values")) for b in baked],
            len(dropped_after),
            "PASS" if after_export.get("status") == "ok" else "FAIL",
            BEFORE_RENDER, AFTER_RENDER))
    return 1 if problems else 0


if __name__ == "__main__":
    if "--build" not in sys.argv:
        print("this gate has no prebuilt-scene mode - pass --build (see "
             "the module docstring). Nothing was run.")
        sys.exit(2)
    sys.exit(main())
