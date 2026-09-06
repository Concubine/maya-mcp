"""Live gate for redmine #832: the capture params a real caller found inert.

Two fresh agents reported three parameters that succeed and change nothing
they can see. Measured first (evals/capture_params_probe_832): two were
real, one was not.

  capture_turntable `resolution` - real. The plugin honoured it, the wrapper
  composited the cells and then capped the SHEET at the single-image 768 px,
  so 8 frames came back as 192-px cells at 256, 400, 640 and 1024 alike. The
  sheet now gets the largest frame an LLM reads at full detail, and the text
  says what the cells came out as.
  capture_viewport `buffer: ssao` - real. The switch went on, Maya's own AO
  numbers stayed: a 40/255 darkening in a 16-px band. The frame now carries
  settings that darken a contact by 147/255 and leave open floor alone.
  capture_turntable `lighting` - NOT reproduced: scene vs default read 107
  vs 65 mean luma on the reporter's own scene with the reporter's own calls,
  under today's encoding and under the ACES one their run predated. Pinned
  here on a one-light scene so a regression is caught.

  1  8 frames at 384 -> a 1536x768 sheet of 384-px cells, said in the text
  2  8 frames at 1024 -> a 1568-px sheet of 392-px cells; the note names
     392, 1024 and path=
  3  4 frames at 1024 -> 784-px cells: fewer columns carry bigger cells
  4  the file written at 1024 keeps 1024-px cells (4096x2048), and the note
     names the file instead of path=
  5  capture_viewport at 1024 with no path says to pass path=; with a path
     it says nothing of the kind and the file is 1024 px
  6  buffer='ssao' on a contact scene darkens the contacts against beauty
     (max diff >= 100, more than 3% of pixels by > 24) and leaves the open
     floor alone (< 2 mean)
  7  every VP2 AO setting is back afterwards; the result carries the
     settings and the note names amount 2.0 / radius 32 px
  8  the shading routes the #818 audit lists as probe-only, sent
     functionally: smoothShaded, flatShaded, wireframe and textured each
     draw; wireframe draws fewer opaque pixels than smoothShaded; flatShaded
     bands a sphere into fewer tones than smoothShaded (69 vs 153, measured)
  9  turntable lighting on a one-light scene: default gives four cells
     within 2 luma of each other, scene spreads them by more than 40
 10  capture_viewport lighting=scene differs from default on an isolated
     subject too

Defaults to port 9878 and refuses 9877 unless MAYA_MCP_ALLOW_USER_SESSION=1
(it replaces the scene). The sheet checks go THROUGH THE WRAPPER
(create_server on a real MayaConnection), because that is where the cap
lives.

Run:  .venv/Scripts/python.exe evals/capture_params_live.py
Exit: 0 pass, 1 fail, 2 no connection.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image, ImageChops, ImageStat  # noqa: E402

from live_call import DEFAULT_PORT, call  # noqa: E402

PORT = DEFAULT_PORT
results: list = []


def send(command: str, params: dict, timeout_s: float = 120.0) -> dict:
    try:
        return call(command, params, timeout_s=timeout_s, port=PORT)
    except (ConnectionRefusedError, OSError) as exc:
        print("could not reach a Maya plugin on %s: %s" % (PORT, exc))
        sys.exit(2)


def ok(command: str, params: dict, timeout_s: float = 120.0) -> dict:
    response = send(command, params, timeout_s)
    if response.get("status") != "ok":
        print("FAIL: %s: %s" % (command, json.dumps(response.get("error"))[:400]))
        sys.exit(1)
    return response.get("result") or {}


def py(code: str) -> None:
    result = ok("execute_python", {"code": code})
    if result.get("traceback"):
        print("FAIL: execute_python raised:\n%s" % result["traceback"])
        sys.exit(1)


def check(label: str, passed: bool, detail: str) -> None:
    print("%s %s: %s" % ("PASS" if passed else "FAIL", label, detail))
    results.append((label, passed))


def new_scene() -> None:
    ok("new_scene", {"confirm": True})


def png(b64: str) -> Image.Image:
    img = Image.open(io.BytesIO(base64.b64decode(b64)))
    img.load()
    return img


def luma(img: Image.Image) -> float | None:
    """Mean luma over the opaque pixels - the subject, not the background."""
    rgba = img.convert("RGBA")
    mask = rgba.getchannel("A").point(lambda v: 255 if v > 8 else 0)
    if not mask.histogram()[255]:
        return None
    return round(ImageStat.Stat(rgba.convert("RGB").convert("L"), mask=mask).mean[0], 1)


def opaque_px(img: Image.Image) -> int:
    return img.convert("RGBA").getchannel("A").point(lambda v: 255 if v > 8 else 0).histogram()[255]


def distinct(img: Image.Image) -> int:
    """How many colours the subject is drawn in (opaque pixels only)."""
    rgba = img.convert("RGBA")
    colours = rgba.getcolors(maxcolors=rgba.width * rgba.height) or []
    return len({colour[:3] for _, colour in colours if colour[3] > 8})


def diff(a: Image.Image, b: Image.Image) -> dict:
    d = ImageChops.difference(a.convert("RGB"), b.convert("RGB")).convert("L")
    hist = d.histogram()
    total = d.width * d.height
    w = d.width
    corners = [(0, int(w * 0.85), int(w * 0.15), w), (int(w * 0.85), int(w * 0.85), w, w)]
    return {"max": max(i for i, h in enumerate(hist) if h) if any(hist) else 0,
            "frac_gt24": round(sum(hist[25:]) / total, 4),
            "mean": round(sum(i * h for i, h in enumerate(hist)) / total, 3),
            "open_floor": [round(ImageStat.Stat(d.crop(c)).mean[0], 2) for c in corners]}


# ------------------------------------------------------------ the wrapper

def wrapper():
    from maya_mcp import server as server_mod  # noqa: PLC0415
    from maya_mcp.connection import MayaConnection  # noqa: PLC0415

    return server_mod.create_server(MayaConnection(port=PORT))


def tool(mcp, name: str, args: dict):
    result = asyncio.run(mcp.call_tool(name, args))
    texts = [c.text for c in result.content if getattr(c, "type", None) == "text"]
    if result.is_error:
        print("FAIL: %s: %s" % (name, texts))
        sys.exit(1)
    pictures = [png(c.data) for c in result.content if getattr(c, "type", None) == "image"]
    return pictures, "\n".join(texts)


def cube_scene() -> None:
    new_scene()
    py("import maya.cmds as cmds\n"
       "c = cmds.polyCube(name='g832_cube', w=10, h=10, d=10, ch=False)[0]\n"
       "cmds.xform(c, ws=True, t=(0, 5, 0))\n")


def contact_scene() -> None:
    new_scene()
    py("import maya.cmds as cmds\n"
       "cmds.polyPlane(name='g832_floor', w=60, h=60, sx=1, sy=1, ch=False)\n"
       "c = cmds.polyCube(name='g832_cube', w=10, h=10, d=10, ch=False)[0]\n"
       "cmds.xform(c, ws=True, t=(0, 5, 0))\n"
       "y = cmds.polyCylinder(name='g832_cyl', r=3, h=10, sx=24, ch=False)[0]\n"
       "cmds.xform(y, ws=True, t=(8, 5, 0))\n"
       "s = cmds.polySphere(name='g832_sph', r=4, ch=False)[0]\n"
       "cmds.xform(s, ws=True, t=(-10, 2, 0))\n")


def one_light_scene() -> None:
    new_scene()
    py("import maya.cmds as cmds\n"
       "c = cmds.polyCube(name='g832_cube', w=10, h=10, d=10, ch=False)[0]\n"
       "cmds.xform(c, ws=True, t=(0, 5, 0))\n"
       "l = cmds.directionalLight(name='g832_key', intensity=1.5)\n"
       "lt = cmds.listRelatives(l, parent=True, fullPath=True)[0]\n"
       "cmds.xform(lt, ws=True, ro=(-35, 0, 0))\n")


def vp2_state() -> dict:
    result = ok("execute_python", {"code": (
        "import maya.cmds as cmds\n"
        "{a: cmds.getAttr('hardwareRenderingGlobals.' + a) for a in "
        "('ssaoEnable', 'ssaoAmount', 'ssaoRadius', 'ssaoFilterRadius', 'ssaoSamples')}\n")})
    import ast  # noqa: PLC0415

    return ast.literal_eval(result["result_repr"])


def main() -> None:
    if PORT == 9877 and os.environ.get("MAYA_MCP_ALLOW_USER_SESSION") != "1":
        print("refusing to run on 9877: this eval replaces the scene. "
              "Set MAYA_MCP_ALLOW_USER_SESSION=1 to override.")
        sys.exit(2)
    ok("ping", {})  # the pid pin and the staleness banner, before the wrapper joins
    mcp = wrapper()
    out_dir = tempfile.mkdtemp(prefix="g832_")

    # 1-4: the sheet carries its cells
    cube_scene()
    pictures, text = tool(mcp, "maya_capture_turntable", {"target": "|g832_cube", "n_frames": 8})
    check("1 eight frames at the default 384 come back as 384-px cells",
          pictures[0].size == (1536, 768) and "8 cells of 384 px" in text,
          "sheet %s, text %r" % (pictures[0].size, text[:120]))
    pictures, text = tool(mcp, "maya_capture_turntable",
                          {"target": "|g832_cube", "n_frames": 8, "resolution": 1024})
    check("2 eight frames at 1024 come back capped at 1568 with 392-px cells, and the note says so",
          pictures[0].size == (1568, 784) and "8 cells of 392 px" in text
          and "1024" in text and "1568" in text and "path=" in text,
          "sheet %s, text %r" % (pictures[0].size, text[:300]))
    pictures, text = tool(mcp, "maya_capture_turntable",
                          {"target": "|g832_cube", "n_frames": 4, "resolution": 1024})
    check("3 four frames at 1024 carry 784-px cells",
          pictures[0].size == (1568, 1568) and "4 cells of 784 px" in text,
          "sheet %s" % (pictures[0].size,))
    sheet_path = os.path.join(out_dir, "turn.png").replace("\\", "/")
    pictures, text = tool(mcp, "maya_capture_turntable",
                          {"target": "|g832_cube", "n_frames": 8, "resolution": 1024,
                           "path": sheet_path})
    on_disk = Image.open(sheet_path).size
    check("4 the file keeps the full 1024-px cells and the note names it",
          on_disk == (4096, 2048) and "turn.png" in text and "path=" not in text,
          "file %s, text %r" % (on_disk, text[:300]))

    # 5: the single-image cap says so too
    pictures, text = tool(mcp, "maya_capture_viewport",
                          {"angles": ["front"], "target": ["|g832_cube"], "resolution": 1024})
    no_path = "note: resolution 1024" in text and "path=" in text
    frame_path = os.path.join(out_dir, "front.png").replace("\\", "/")
    pictures, text2 = tool(mcp, "maya_capture_viewport",
                           {"angles": ["front"], "target": ["|g832_cube"], "resolution": 1024,
                            "path": frame_path})
    check("5 a 1024 capture with no path says to pass one; with a path it does not, and the file is 1024",
          no_path and "note: resolution" not in text2 and Image.open(frame_path).size == (1024, 1024),
          "no path: %r / with path: %r" % (text[-160:], text2[-160:]))

    # 6-7: ssao reads as contact
    contact_scene()
    before = vp2_state()
    base = {"angles": ["three_quarter"], "target": ["|g832_cube"], "wireframe_overlay": False,
            "resolution": 768}
    beauty = ok("capture_viewport", dict(base, buffer="beauty"))
    ssao = ok("capture_viewport", dict(base, buffer="ssao"))
    after = vp2_state()
    d = diff(png(beauty["images"][0]["png_b64"]), png(ssao["images"][0]["png_b64"]))
    check("6 ssao darkens the contacts and leaves the open floor alone",
          d["max"] >= 100 and d["frac_gt24"] > 0.03 and max(d["open_floor"]) < 2,
          json.dumps(d))
    note = [w for w in ssao.get("warnings") or [] if "ssao" in w]
    check("7 the AO settings are back, carried in the result, and named once",
          after == before and ssao.get("ssao") == {"ssaoAmount": 2.0, "ssaoRadius": 32,
                                                   "ssaoFilterRadius": 16, "ssaoSamples": 32}
          and len(note) == 1 and "amount 2.0" in note[0] and "radius 32 px" in note[0]
          and beauty.get("ssao") is None,
          "before %s after %s ssao %s note %s" % (json.dumps(before), json.dumps(after),
                                                 json.dumps(ssao.get("ssao")), json.dumps(note)))

    # 8: the shading routes, sent functionally
    frames = {}
    for shading in ("smoothShaded", "flatShaded", "wireframe", "textured"):
        result = ok("capture_viewport", {"angles": ["three_quarter"], "target": ["|g832_sph"],
                                         "shading": shading, "wireframe_overlay": False,
                                         "resolution": 384})
        frames[shading] = (png(result["images"][0]["png_b64"]), result["images"][0].get("blank"))
    drew = all(not blank for _, blank in frames.values())
    wire_px = opaque_px(frames["wireframe"][0])
    smooth_px = opaque_px(frames["smoothShaded"][0])
    # Facets change the gradient WITHIN a face, which is small on a
    # 20-segment sphere (frame-mean diff 0.19, measured) - but flat shading
    # bands the sphere into as many tones as it has visible faces where
    # smooth grades it through hundreds: 69 against 153 (probe4).
    smooth_tones = distinct(frames["smoothShaded"][0])
    flat_tones = distinct(frames["flatShaded"][0])
    check("8 every shading route draws; wireframe is sparser than shaded; flat bands a sphere into fewer tones",
          drew and wire_px < smooth_px * 0.5 and flat_tones < smooth_tones * 0.6,
          "blank %s, wireframe %d px vs shaded %d px, tones flat %d vs smooth %d" % (
              [b for _, b in frames.values()], wire_px, smooth_px, flat_tones, smooth_tones))

    # 9-10: turntable lighting (F-9, pinned)
    one_light_scene()
    cells = {}
    for mode in ("default", "scene"):
        result = ok("capture_turntable", {"target": "|g832_cube", "n_frames": 4,
                                          "lighting": mode, "resolution": 256}, timeout_s=180)
        cells[mode] = [luma(png(s["png_b64"])) for s in result["images"]]
    default_spread = max(cells["default"]) - min(cells["default"])
    scene_spread = max(cells["scene"]) - min(cells["scene"])
    check("9 the turntable's lighting param reaches the frames",
          default_spread <= 2 and scene_spread > 40,
          "default %s scene %s" % (cells["default"], cells["scene"]))
    front = {}
    for mode in ("default", "scene"):
        result = ok("capture_viewport", {"angles": ["front"], "isolate": ["|g832_cube"],
                                         "lighting": mode, "resolution": 256})
        front[mode] = luma(png(result["images"][0]["png_b64"]))
    check("10 scene lighting reaches an isolated subject too",
          abs(front["scene"] - front["default"]) > 20, "front %s" % json.dumps(front))

    new_scene()
    failed = [label for label, passed in results if not passed]
    print("\n%d checks, %d failed%s" % (len(results), len(failed),
                                        (": " + ", ".join(failed)) if failed else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
