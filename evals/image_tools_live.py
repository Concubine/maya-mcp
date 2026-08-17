"""Live gate for redmine #639: the image tools must write files, and must not
photograph the sky.

Three gaps, all found in Task 10 of the #601 golem run:

  1. None of the four image tools could write a file. A plan whose deliverable
     was "write every image under evals/<run>/" could not be followed through
     the tool surface at all - the run's hero stills had to escape to
     execute_python and call the plugin's own renderer.
  2. `render_scene` with a dome in the scene and no `target` framed the DOME:
     the camera went to 5294 units from a 5-unit subject. The blank guard could
     not catch it, because a dome fills the frame with opaque pixels.
  3. `capture_viewport` did the same at 5498 units and came back blank white,
     and had no `target` at all - the only way to frame one object was
     `isolate`, which also hides everything else.

This runs the REAL MCP server against a live Maya, because that is the only
place both halves exist: the framing fix lives in the plugin and the file
writing lives in the server, and #639 is about what a caller gets from one
tool call.

The pixel A/B at step 3b needs a viewport that is ON SCREEN. It does not need
the user's own Maya - an agent-launched one blasts real pixels once its window
is foregrounded and un-minimized, and returns a fully transparent frame while
it is not. The eval measures which case it is in and skips the A/B loudly
rather than reading a transparent capture as a pass.

DESTRUCTIVE: calls new_scene. Defaults to port 9878 (the disposable
agent-launched Maya) and refuses 9877 unless MAYA_MCP_ALLOW_USER_SESSION=1.

Run:  .venv/Scripts/python.exe evals/image_tools_live.py
Exit: 0 pass, 1 fail, 2 no connection.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image as PILImage  # noqa: E402

from live_call import DEFAULT_PORT, call, structured_result  # noqa: E402
from maya_mcp import server as server_mod  # noqa: E402
from maya_mcp.connection import MayaConnection  # noqa: E402

PORT = DEFAULT_PORT
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "image_tools_live")
# The subject: a 5-unit cube, the size of the golem chunk that got photographed
# from 5294 units away.
SUBJECT_HALF = 2.5

failures = []


def check(label: str, ok: bool, detail: str) -> None:
    print("%s %s: %s" % ("PASS" if ok else "FAIL", label, detail))
    if not ok:
        failures.append(label)


def send(command: str, params: dict, timeout_s: float = 300.0) -> dict:
    try:
        response = call(command, params, timeout_s=timeout_s, port=PORT)
    except (ConnectionRefusedError, OSError) as exc:
        print("could not reach a Maya plugin on %s: %s" % (PORT, exc))
        sys.exit(2)
    if response.get("status") != "ok":
        print("FAIL: %s: %s" % (command, json.dumps(response.get("error"))[:400]))
        sys.exit(1)
    return response.get("result") or {}


def py(code: str):
    return structured_result(send("execute_python", {"code": code}, 180.0))


def run(coro):
    return asyncio.run(coro)


def texts(result) -> str:
    return " ".join(
        c.text for c in result.content if getattr(c, "type", None) == "text"
    )


def pictures(result):
    return [
        PILImage.open(io.BytesIO(base64.b64decode(c.data)))
        for c in result.content if getattr(c, "type", None) == "image"
    ]


def camera_distance(result) -> float:
    """How far the tool put the camera from the origin, read from its own report.

    Read per text BLOCK, never off the joined string: the "wrote:" line lands
    in the same message and would be parsed as trailing JSON.
    """
    positions = []
    for block in result.content:
        text = getattr(block, "text", "") or ""
        if text.startswith("camera_positions: "):
            positions = json.loads(text[len("camera_positions: "):])
    if not positions:
        return float("nan")
    return max(math.dist([0, 0, 0], p["position"]) for p in positions)


def main() -> None:
    if PORT == 9877 and os.environ.get("MAYA_MCP_ALLOW_USER_SESSION") != "1":
        print("refusing to run on 9877: this eval discards the open scene. "
              "Set MAYA_MCP_ALLOW_USER_SESSION=1 to override.")
        sys.exit(2)

    print("Maya on %d: pid %s" % (PORT, py("import os\nos.getpid()")))
    if os.path.isdir(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    os.makedirs(OUT_DIR)

    send("new_scene", {"confirm": True})
    send("create_primitive", {"kind": "cube", "name": "golemChest",
                              "scale": [SUBJECT_HALF * 2] * 3})
    send("create_primitive", {"kind": "sphere", "name": "golemHead",
                              "translate": [0, 4, 0], "scale": [2, 2, 2]})
    dome = send("setup_lighting", {"preset": "environment"})
    span = py("import maya.cmds as cmds\n"
              "[round(v, 3) for v in cmds.exactWorldBoundingBox('|mcpLight_dome_001')]")
    print("dome %s spans %s\n" % (dome["lights"], span))

    mcp = server_mod.create_server(MayaConnection(port=PORT))

    # ---- 1. framing: a dome must not decide where the camera goes ----
    shot = run(mcp.call_tool("maya_capture_viewport", {
        "angles": ["three_quarter"], "resolution": 512,
        "path": os.path.join(OUT_DIR, "framing.png"),
    }))
    distance = camera_distance(shot)
    check("capture_viewport does not frame the sky dome",
          distance < 100.0,
          "camera at %.1f units from a %.0f-unit subject (was 5498 pre-fix)"
          % (distance, SUBJECT_HALF * 2))
    # Whether capture_viewport's PIXELS are evidence at all depends on the
    # window: a playblast of an off-screen viewport is fully transparent and
    # proves nothing. Measured here, acted on at 3b - never assumed.
    frame = pictures(shot)[0]
    opaque = sum(frame.convert("RGBA").getchannel("A").histogram()[9:])
    print("     (viewport pixels: %d of %d opaque)"
          % (opaque, frame.width * frame.height))

    rendered = run(mcp.call_tool("maya_render_scene", {
        "angles": ["three_quarter"], "resolution": 256, "samples": 1,
        "renderer": "hw2", "path": os.path.join(OUT_DIR, "render.png"),
    }))
    check("render_scene does not frame the sky dome either",
          camera_distance(rendered) < 100.0,
          "camera at %.1f units (was 5294 pre-fix)" % camera_distance(rendered))
    # The render path DOES produce real pixels headless, so this is where the
    # subject can be proven to be in shot. Framed from 5294 units a 5-unit cube
    # is sub-pixel; framed properly it fills a real fraction of the frame.
    render_frame = pictures(rendered)[0].convert("RGB")
    total = render_frame.width * render_frame.height
    background = dict(
        (colour, count) for count, colour in
        (render_frame.getcolors(maxcolors=total) or [])
    ).get((0, 0, 0), 0)
    footprint = (total - background) / total
    check("and the subject really is in the rendered frame",
          footprint > 0.02,
          "%.1f%% of the frame is subject rather than background" % (footprint * 100))

    # ---- 2. target frames without hiding ----
    close = run(mcp.call_tool("maya_capture_viewport", {
        "angles": ["front"], "resolution": 512, "target": ["|golemHead"],
        "path": os.path.join(OUT_DIR, "target.png"),
    }))
    head_distance = camera_distance(close)
    check("target closes in on one object",
          head_distance < distance,
          "head-framed %.2f vs scene-framed %.2f units" % (head_distance, distance))
    still_visible = py("import maya.cmds as cmds\n"
                       "cmds.getAttr('|golemChest.visibility')")
    check("and nothing was hidden to achieve it",
          bool(still_visible), "golemChest.visibility=%s" % still_visible)

    # ---- 3. the files ----
    for name in ("framing.png", "render.png", "target.png"):
        path = os.path.join(OUT_DIR, name)
        check("%s was written" % name, os.path.isfile(path),
              "%d bytes" % os.path.getsize(path) if os.path.isfile(path) else "missing")

    check("the written frame keeps its full resolution",
          PILImage.open(os.path.join(OUT_DIR, "framing.png")).width == 512,
          "%dpx on disk, %dpx in the message"
          % (PILImage.open(os.path.join(OUT_DIR, "framing.png")).width, frame.width))

    # ---- 3b. the defect and the fix, in PIXELS ----
    #
    # A playblast needs a viewport that is actually on screen. It does NOT need
    # the user's own Maya: an agent-launched one blasts fine once its window is
    # foregrounded and not minimized, and returns a fully transparent frame
    # while it is not. That is measured either way below, and the A/B is only
    # claimed when there are real pixels to claim it from - a transparent
    # capture must never be read as a passing one.
    if opaque == 0:
        print("\nSKIPPED the pixel A/B: this Maya's viewport is not on screen, "
              "so every playblast is fully transparent (%d of %d opaque). "
              "Foreground and un-minimize the Maya window and re-run to get it. "
              "The framing checks above rest on the camera placement, which is "
              "real either way." % (opaque, frame.width * frame.height))
    else:
        def footprint_of(params):
            shot = run(mcp.call_tool("maya_capture_viewport",
                                     dict(params, resolution=256)))
            image = pictures(shot)[0].convert("RGBA")
            lit = sum(image.getchannel("A").histogram()[9:])
            return lit / (image.width * image.height), camera_distance(shot)

        # Framing ON the dome is what the fallback used to do by accident, so
        # asking for it explicitly reproduces the defect inside the fixed build.
        sky, sky_distance = footprint_of(
            {"angles": ["three_quarter"], "target": [dome["lights"][0]]}
        )
        subject, subject_distance = footprint_of({"angles": ["three_quarter"]})
        head, head_distance = footprint_of(
            {"angles": ["three_quarter"], "target": ["|golemHead"]}
        )
        check("framing the dome really is a photograph of nothing",
              sky == 0.0,
              "%.2f%% of the frame lit from %.0f units - the ticket's blank image"
              % (sky * 100, sky_distance))
        check("and the fixed fallback puts the subject in shot",
              subject > 0.02,
              "%.2f%% lit from %.1f units" % (subject * 100, subject_distance))
        check("target closes in further still, in pixels",
              head > subject,
              "head %.2f%% at %.1f units vs scene %.2f%% at %.1f units"
              % (head * 100, head_distance, subject * 100, subject_distance))

    multi = run(mcp.call_tool("maya_capture_viewport", {
        "angles": ["front", "side"], "resolution": 256,
        "path": os.path.join(OUT_DIR, "hero.png"),
    }))
    check("several angles write one predictable file each",
          os.path.isfile(os.path.join(OUT_DIR, "hero_front.png"))
          and os.path.isfile(os.path.join(OUT_DIR, "hero_side.png"))
          and not os.path.isfile(os.path.join(OUT_DIR, "hero.png")),
          "wrote %s" % sorted(n for n in os.listdir(OUT_DIR) if n.startswith("hero")))
    check("and it says which files it wrote", "hero_front.png" in texts(multi),
          texts(multi).split("wrote: ")[-1][:160])

    sheet = run(mcp.call_tool("maya_capture_turntable", {
        "n_frames": 4, "resolution": 192,
        "path": os.path.join(OUT_DIR, "turntable.png"),
    }))
    turn_path = os.path.join(OUT_DIR, "turntable.png")
    check("a turntable writes the composited sheet, not its cells",
          os.path.isfile(turn_path)
          and PILImage.open(turn_path).width > 192,
          "%dpx wide" % PILImage.open(turn_path).width
          if os.path.isfile(turn_path) else "missing")
    check("the turntable came back as one image", len(pictures(sheet)) == 1,
          "%d images" % len(pictures(sheet)))

    kit = run(mcp.call_tool("maya_render_sheet", {
        "subjects": ["|golemChest", "|golemHead"], "renderer": "hw2",
        "resolution": 192, "samples": 1,
        "path": os.path.join(OUT_DIR, "kit.png"),
    }))
    check("a render sheet writes its sheet",
          os.path.isfile(os.path.join(OUT_DIR, "kit.png")),
          texts(kit).split("wrote: ")[-1][:160])

    # ---- 4. a bad path must cost nothing ----
    before = sorted(os.listdir(OUT_DIR))
    try:
        run(mcp.call_tool("maya_render_scene", {
            "angles": ["front"], "renderer": "hw2", "resolution": 128,
            "path": os.path.join(OUT_DIR, "no_such_dir", "x.png"),
        }))
        refused = False
        message = "the call succeeded"
    except Exception as exc:
        refused = "does not exist" in str(exc)
        message = str(exc)[:160]
    check("a path into a missing directory is refused, not created",
          refused and sorted(os.listdir(OUT_DIR)) == before, message)

    if failures:
        print("\n%d FAILED: %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("\nall checks passed; images in %s" % OUT_DIR)


if __name__ == "__main__":
    main()
