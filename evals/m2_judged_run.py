"""M2 exit test: light, material, and judge a model against a reference.

Drives the live plugin over TCP, exactly like evals/isolate_regression.py.
Writes every capture to evals/m2_run/ so the run is reviewable after the fact -
these PNGs are M2's only exit evidence.

`load_reference_image` / `compare_to_reference` are server-side-only MCP tools
(they live in src/maya_mcp/server.py's ReferenceStore, not in the plugin's
_build_handlers()) - a raw TCP driver against the plugin cannot reach them, so
this run does not exercise reference comparison. Judge the pixels by eye.

Run:  .venv/Scripts/python.exe evals/m2_judged_run.py
Exit: 0 completed, 1 a tool failed, 2 could not connect.
"""

from __future__ import annotations

import base64
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from maya_plugin import protocol  # noqa: E402

HOST = os.environ.get("MAYA_MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("MAYA_MCP_PORT", 9877))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "m2_run")


def call(cmd, params, timeout_s=120.0):
    sock = socket.create_connection((HOST, PORT), timeout=timeout_s + 30)
    try:
        sock.sendall(protocol.encode_frame(protocol.make_request(cmd, params, timeout_s)))
        resp = protocol.read_frame(sock.recv)
    finally:
        sock.close()
    if resp.get("status") != "ok":
        raise RuntimeError("%s failed: %s" % (cmd, resp.get("error")))
    return resp["result"]


def save(result, name):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    with open(path, "wb") as fh:
        fh.write(base64.b64decode(result["images"][0]["png_b64"]))
    print("  ->", path)
    return path


def main():
    print("1. building a subject")
    created = call("create_primitive", {"kind": "sphere", "name": "m2_subject",
                                        "divisions": 3})
    subject = created["name"]  # canonical long name - collision-safe on a dirty scene
    print("  subject:", subject)

    print("2. lighting it")
    lit = call("setup_lighting", {"preset": "three_point", "intensity": 1.2})
    print("  lights:", lit["lights"], "removed:", lit["removed"])

    print("3. unlit vs lit - the spec 2 requirement, visible")
    save(call("capture_viewport", {"angles": ["three_quarter"],
                                   "lighting": "default", "resolution": 640}),
         "01_default_lighting.png")
    save(call("capture_viewport", {"angles": ["three_quarter"],
                                   "lighting": "scene", "resolution": 640}),
         "02_scene_lighting.png")

    print("4. material + texture")
    mat = call("assign_material", {
        "mesh": subject, "shader": "standardSurface",
        "params": {"baseColor": [0.45, 0.32, 0.26], "roughness": 0.85},
        "name": "m2_clay"})
    print("  material:", mat["material"], "sg:", mat["shading_group"])
    tex = call("apply_texture_recipe", {"mesh": subject,
                                        "recipe": "noise_bump",
                                        "params": {"scale": 2.0, "depth": 0.5}})
    print("  texture nodes:", tex["nodes"])
    save(call("capture_viewport", {"angles": ["three_quarter"],
                                   "lighting": "scene", "resolution": 640}),
         "03_materialed.png")

    print("5. readback check")
    info = call("get_object_info", {"name": subject, "include": ["shading"]})
    assert info["shading"]["materials"] == [mat["material"]], info
    assert info["shading"]["per_face"] is False, info
    print("  shading reads back:", info["shading"])

    print("6. turntable")
    tt = call("capture_turntable", {"target": subject, "n_frames": 8,
                                    "lighting": "scene"})
    os.makedirs(OUT, exist_ok=True)
    for shot in tt["images"]:
        with open(os.path.join(OUT, "tt_%02d.png" % shot["index"]), "wb") as fh:
            fh.write(base64.b64decode(shot["png_b64"]))
    print("  %d frames written" % tt["n_frames"])

    print("\nJUDGED RUN COMPLETE - review evals/m2_run/ by eye.")
    print("01 vs 02 must differ (scene lighting reaches pixels).")
    print("03 must show surface grain from the noise_bump recipe.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ConnectionRefusedError, OSError) as exc:
        print("could not reach the plugin on %s:%d - is Maya open? (%s)"
              % (HOST, PORT, exc))
        sys.exit(2)
    except Exception as exc:
        print("FAILED:", exc)
        sys.exit(1)
