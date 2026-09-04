"""#765 live gate: a picture of nothing says so.

The defect, measured on Maya 2027: `capture_viewport` returned a frame in
which EVERY pixel was transparent - real RGB, zero alpha - so any viewer
composited it to flat white while the tool reported plain success. A whole
#669 live gate passed with that white square in it, and the gate's own
"now LOOK at this" line was pointing at nothing.

What separates a good frame from that one is NOT pixel variety: the broken
frames carried 13 distinct pixel values and a correct capture of a cube
carried 15. It is opaque coverage - 0 against 18872 - which is the same
measure `render_scene`'s own blank guard has always used and the one
`capture_viewport` never had.

The cause, found by measuring rather than reasoning: a Maya whose main window
has NEVER BEEN SHOWN draws nothing into an offscreen playblast. Every
agent-launched Maya starts that way. `offScreen=True` does not save it and
neither does the M3dView fallback; one `show()` fixes it permanently for the
process, and minimising the window again afterwards does not break it. The
discriminator is isVisible(), not isMinimized() - the blind session measured
minimized=False, visible=False, which is why chasing minimisation led nowhere.

So there are two changes and this gate covers both: capture_viewport now SHOWS
an unrealized window (and says it did), and it NAMES any frame that still
comes back empty. The report is the backstop - it catches every other cause of
a blank frame, including the ones nobody has met yet.

This gate proves, against a live Maya:

1. The FIRST capture on a freshly launched Maya draws something - the fix:
   an unrealized main window draws nothing, and this shows it.
2. An EMPTY scene captures blank, is named as blank, and is still returned -
   an empty scene is a legal request, so this names frames, it does not refuse
   calls.
3. A scene with a subject captures non-blank and warns about nothing.
4. The turntable, which shares the same capture path, carries the verdict too.
5. The warning survives the MCP wrapper. #757 was exactly this - a handler
   warning the wrapper never read - so the last claim drives the real tool
   surface, not the TCP layer underneath it.

Every verdict is checked against an INDEPENDENT count of the returned PNG's
opaque pixels, made here. A gate that asks the code under test whether it is
right is not a gate.

Usage:

    set MAYA_MCP_PORT=9878
    set MAYA_MCP_EXPECT_PID=<the pid you launched>
    python evals/capture_blank_live.py

MUTATES THE ANSWERING MAYA'S CURRENT SCENE (new_scene, one cube).
MAYA_MCP_EXPECT_PID is REQUIRED: this discards the open scene, so it refuses
to guess which Maya is disposable. A port is not an identity (#648).

Exit: 0 pass, 1 fail.
"""

from __future__ import annotations

import asyncio
import base64
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_call import call  # noqa: E402
from maya_plugin.handlers import pngprobe  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
failures: list = []


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


def ok(command: str, params: dict, timeout_s: float = 180.0) -> dict:
    frame = call(command, params, timeout_s=timeout_s)
    if frame.get("status") != "ok":
        raise SystemExit("%s failed: %r" % (command, frame.get("error")))
    return frame.get("result") or {}


def opaque_pixels(png_b64: str) -> int:
    """Count the drawn pixels HERE, rather than believe the handler's verdict."""
    fd, path = tempfile.mkstemp(suffix=".png", prefix="gate765_")
    os.close(fd)
    try:
        with open(path, "wb") as fh:
            fh.write(base64.b64decode(png_b64))
        png = pngprobe.read_png(path)
    finally:
        os.unlink(path)
    pixels = png["pixels"]
    stride = len(pixels[0]) if pixels else 0
    if stride == 4:
        return sum(1 for p in pixels if p[3] > 8)
    return sum(1 for p in pixels if any(p[:3]))


def blank_notes(result: dict) -> list:
    return [w for w in (result.get("warnings") or []) if "BLANK" in w]


def main() -> int:
    ping = preflight()
    print("answering Maya: pid %s" % (ping.get("process") or {}).get("pid"))

    print("claim 1: the FIRST capture on a never-shown Maya still draws")
    # This is the fix itself. A Maya launched by an agent comes up with its
    # main window never realized, and an unrealized window draws NOTHING into
    # an offscreen playblast - measured 0 opaque pixels against 9604 the
    # instant the window is shown. Run this gate against a FRESH Maya or it
    # proves nothing: once shown, a process stays sighted.
    ok("new_scene", {"confirm": True})
    ok("create_primitive", {"kind": "cube", "name": "gate765_first",
                            "scale": [2, 2, 2]})
    first = ok("capture_viewport", {"angles": ["front"], "resolution": 256})
    shot = (first.get("images") or [{}])[0]
    drawn = opaque_pixels(shot.get("png_b64", ""))
    shown = [w for w in (first.get("warnings") or []) if "main window" in w]
    print("  blank=%r opaque(measured here)=%d window-was-shown=%s"
          % (shot.get("blank"), drawn, bool(shown)))
    if drawn == 0:
        fail("the first capture drew nothing even with a cube in frame - the "
             "window fix did not take, and this is the #765 symptom itself")
    if shot.get("blank") is not False:
        fail("the first capture reported blank=%r while carrying %d opaque "
             "pixels" % (shot.get("blank"), drawn))
    if not shown:
        print("  (no window note - this Maya had already been shown, so claim "
              "1 did not exercise the fix)")

    print("claim 2: an empty scene captures blank, and is TOLD as blank")
    ok("new_scene", {"confirm": True})
    empty = ok("capture_viewport", {"angles": ["front"], "resolution": 256})
    shot = (empty.get("images") or [{}])[0]
    drawn = opaque_pixels(shot.get("png_b64", ""))
    print("  blank=%r opaque(measured here)=%d blank-warnings=%d"
          % (shot.get("blank"), drawn, len(blank_notes(empty))))
    if drawn != 0:
        fail("an empty scene drew %d opaque pixels - this fixture is not "
             "empty, so it proves nothing about blankness" % drawn)
    if shot.get("blank") is not True:
        fail("an empty scene reported blank=%r; before #765 this was the "
             "frame that came back as a plain success" % shot.get("blank"))
    if not blank_notes(empty):
        fail("nothing in warnings named the blank frame: %r"
             % (empty.get("warnings"),))
    else:
        print("  " + blank_notes(empty)[0].split(".")[0])
    if not shot.get("png_b64"):
        fail("the blank frame was withheld - an empty scene is a legal "
             "request and the frame must still come back, named")

    print("claim 3: a scene with a subject is not blank and warns about nothing")
    ok("create_primitive", {"kind": "cube", "name": "gate765_cube",
                            "scale": [2, 2, 2]})
    lit = ok("capture_viewport", {"angles": ["front", "three_quarter"],
                                  "resolution": 256})
    for shot in lit.get("images") or []:
        drawn = opaque_pixels(shot["png_b64"])
        print("  %-14s blank=%r opaque(measured here)=%d"
              % (shot["angle"], shot.get("blank"), drawn))
        if drawn == 0:
            fail("%s drew nothing even with a cube in frame - the viewport "
                 "in this session is blind (the #765 symptom itself)"
                 % shot["angle"])
        if shot.get("blank") is not False:
            fail("%s reported blank=%r while carrying %d opaque pixels"
                 % (shot["angle"], shot.get("blank"), drawn))
    if blank_notes(lit):
        fail("a drawn frame was named blank: %r" % (lit["warnings"],))

    print("claim 4: the turntable carries the same verdict")
    turn = ok("capture_turntable", {"n_frames": 2, "resolution": 256},
              timeout_s=300.0)
    for shot in turn.get("images") or []:
        drawn = opaque_pixels(shot["png_b64"])
        if shot.get("blank") is None:
            fail("turntable cell %s carries no blankness verdict at all"
                 % shot.get("index"))
        elif shot.get("blank") != (drawn == 0):
            fail("turntable cell %s says blank=%r with %d opaque pixels"
                 % (shot.get("index"), shot.get("blank"), drawn))
    print("  cells: %r" % [s.get("blank") for s in turn.get("images") or []])

    print("claim 5: and the warning survives the MCP wrapper (#757's lesson)")
    from maya_mcp import server as server_mod          # noqa: PLC0415
    from maya_mcp.connection import MayaConnection     # noqa: PLC0415

    ok("new_scene", {"confirm": True})
    mcp = server_mod.create_server(MayaConnection(port=PORT))
    out = asyncio.run(
        mcp.call_tool("maya_capture_viewport",
                      {"angles": ["front"], "resolution": 256}))
    texts = [c.text for c in out.content if c.type == "text"]
    if not any("BLANK" in t for t in texts):
        fail("the MCP tool returned no blank note for an empty scene: %r"
             % (texts,))
    else:
        print("  wrapper said: "
              + [t for t in texts if "BLANK" in t][0][:90])
    if not [c for c in out.content if c.type == "image"]:
        fail("the MCP tool withheld the image; it must return the frame AND "
             "name it")

    print()
    if failures:
        print("GATE FAILED (%d)" % len(failures))
        return 1
    print("GATE PASSED - a frame that draws nothing now says so, at the "
          "protocol layer and at the tool surface.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
