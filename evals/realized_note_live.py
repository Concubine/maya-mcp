"""#826 live gate: the window note says what actually happened.

`capture_viewport` shows Maya's main window when it is hidden, because a
never-realized window draws NOTHING into an offscreen playblast (#765). It
used to ANNOUNCE that as a fact - "this call showed it. That is a visible
change to the screen" - on every capture of a hidden window.

MEASURED on virgin agent Mayas (evals/realized_note_probe_826.py and _826b):

  - `show()` sets `isVisible()` True SYNCHRONOUSLY, inside the calling
    command, whatever happens next.
  - During Maya's first seconds the window is hidden again by the very next
    command: no window ever appeared, the claim was false, and because
    visibility never latched it fired again on the next capture, and the next.
  - Neither `QApplication.sendPostedEvents(w, 0)` nor `processEvents()`
    revealed the difference from inside that command. The two worlds are
    indistinguishable in there.
  - The NEXT show sticks, permanently, and hide() -> show() sticks after
    that. It is the process's FIRST show that is undone, not "a show during
    the first seconds": this gate reproduced it on a Maya 67 s old. So the
    note's claim was not false - it was unchecked, and true on the second
    capture of most processes.

So the note now reports ACROSS calls: this call says it asked, and the next
call - the first place the outcome is visible - says the request did not take
or that the window is up. Each fact once per process.

This gate drives every state against a live Maya:

  1  a VIRGIN process             -> capture 1 asks; capture 2's note has to
     match what the window actually did, whichever way it went
  2  a show that sticks           -> ask, then "up on screen now", then
     silence for every capture after
  3  a show that is undone        -> ask, "did not take", "up on screen now",
     then silence - forced with a one-shot event filter that hides the window
     one event-loop turn after it is shown, which is what a virgin process
     was measured doing
  4  a window nobody hid          -> never shown, never mentioned
  5  capture_turntable            -> one note for the whole call, not one per
     frame

Claim 1 only measures the undone path on a Maya nobody has captured from yet;
it says so when it lands on a process that has already spent its first show.
Claims 2 and 3 force both paths on demand, so they hold on any run. Every
frame is checked for opaque pixels HERE, because the whole point of the
show() is that the frames draw.

Usage:

    set MAYA_MCP_PORT=9878
    set MAYA_MCP_EXPECT_PID=<the pid you launched>
    python evals/realized_note_live.py

MUTATES THE ANSWERING MAYA'S SCENE (new_scene, one cube) and hides/shows its
main window. Refuses 9877, the user's session.

Exit: 0 pass, 1 fail.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import textwrap

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_call import call, structured_result  # noqa: E402
from maya_plugin.handlers import pngprobe  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
if PORT == 9877:
    raise SystemExit("refusing 9877 - that is the user's Maya")

CHECKS: list = []


def check(label: str, passed: bool, detail: object = "") -> bool:
    CHECKS.append((label, bool(passed), detail))
    print("  %s %s%s" % ("PASS" if passed else "FAIL", label,
                         ("  <- " + str(detail)) if detail else ""))
    return bool(passed)


def preflight() -> dict:
    if not (os.environ.get("MAYA_MCP_EXPECT_PID") or "").strip():
        raise SystemExit(
            "MAYA_MCP_EXPECT_PID is not set. This gate discards the answering "
            "Maya's scene and hides its window, so it will not guess which "
            "one is disposable - launch one yourself and name its pid (#648).")
    frame = call("ping", {}, port=PORT)
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
    frame = call(command, params, timeout_s=timeout_s, port=PORT)
    if frame.get("status") != "ok":
        raise SystemExit("%s failed: %s"
                         % (command, json.dumps(frame.get("error"), indent=1)))
    return frame.get("result") or {}


def py(code: str, timeout_s: float = 180.0):
    """Run code on the answering Maya and bring back whatever it left in `r`."""
    body = textwrap.dedent(code).strip() + "\nr"
    res = ok("execute_python", {"code": body}, timeout_s=timeout_s)
    if res.get("traceback"):
        raise SystemExit("execute_python raised:\n" + res["traceback"])
    return structured_result(res, "r")


def opaque_pixels(png_b64: str) -> int:
    """Count the drawn pixels HERE - a gate does not ask the code under test."""
    fd, path = tempfile.mkstemp(suffix=".png", prefix="gate826_")
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


LIB = r'''
from maya_plugin.handlers import capture as _capture
from maya.OpenMayaUI import MQtUtil
from shiboken6 import wrapInstance
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import QObject, QEvent, QTimer

# PySide6 scopes its enums; the flat spelling still works in some builds.
_SHOW_EVENT = getattr(getattr(QEvent, "Type", QEvent), "Show")


def win():
    return wrapInstance(int(MQtUtil.mainWindow()), QWidget)


def state():
    # NEVER winId() here - it forces native window creation as a side effect.
    w = win()
    return {"visible": w.isVisible(), "hidden": w.isHidden(),
            "minimized": w.isMinimized(),
            "native_surface": w.windowHandle() is not None}


class _Rehider(QObject):
    """Maya's start-up, reproduced: hide the window one turn after it shows.

    MEASURED as the real behaviour (probe 826b) - show() reads back True and
    the window is hidden again by the next command. Fires exactly once, the
    way the boot race does.
    """

    def __init__(self, w):
        super(_Rehider, self).__init__(w)
        self.w = w
        self.armed = True
        self.fired = False

    def eventFilter(self, obj, ev):
        if self.armed and ev.type() == _SHOW_EVENT:
            self.armed = False
            self.fired = True
            QTimer.singleShot(0, self.w.hide)
        return False


_rehider = [None]


def arm_rehider():
    disarm_rehider()
    w = win()
    r = _Rehider(w)
    w.installEventFilter(r)
    _rehider[0] = r
    return True


def disarm_rehider():
    r = _rehider[0]
    if r is not None:
        try:
            win().removeEventFilter(r)
        except Exception:
            pass
        _rehider[0] = None
    return True


def rehider_fired():
    r = _rehider[0]
    return bool(r and r.fired)


def fresh(hidden=True):
    """A process that has said nothing yet, with the window as asked for."""
    disarm_rehider()
    _capture.reset_window_notes()
    w = win()
    if hidden:
        w.hide()
    else:
        w.show()
    return state()


def tidy():
    """Leave the agent Maya as it was launched: realized, off the screen.

    showMinimized keeps isVisible() True - the #765 discriminator - so the
    window stays realized and this handler stays silent afterwards.
    """
    disarm_rehider()
    _capture.reset_window_notes()
    win().showMinimized()
    return state()
'''


def window_notes(result: dict) -> list:
    return [w for w in (result.get("warnings") or []) if "main window" in w]


def shoot(label: str) -> tuple:
    """One capture; its window notes and an independent opaque-pixel count."""
    res = ok("capture_viewport", {"angles": ["front"], "resolution": 256})
    shot = (res.get("images") or [{}])[0]
    drawn = opaque_pixels(shot.get("png_b64", ""))
    notes = window_notes(res)
    print("    %-22s notes=%d drawn=%d%s"
          % (label, len(notes), drawn,
             ("  " + notes[0][:64] + "...") if notes else ""))
    return notes, drawn


def one_note(label: str, notes: list, phrase: str) -> bool:
    if len(notes) != 1:
        return check(label, False, "%d window notes, expected 1: %r"
                     % (len(notes), notes))
    return check(label, phrase in notes[0], "note was: %r" % notes[0])


def main() -> int:
    ping = preflight()
    print("answering Maya: pid %s, plugin %s"
          % ((ping.get("process") or {}).get("pid"),
             (ping.get("plugin") or {}).get("loaded_digest")))
    py(LIB + "\nr = 1")
    ok("new_scene", {"confirm": True})
    ok("create_primitive", {"kind": "cube", "name": "gate826",
                            "scale": [2, 2, 2]})

    print("\nclaim 1: on a VIRGIN process the note tracks what the window "
          "really did - this is the one the ticket was filed about")
    before = py("r = fresh(hidden=True)")
    check("the window really is hidden to start with",
          before.get("visible") is False, before)
    notes, drawn = shoot("capture 1")
    one_note("capture 1 says it asked", notes, "asked Maya to show it")
    if notes:
        check("capture 1 does not assert that it showed it",
              "call showed it" not in notes[0], notes[0])
    check("capture 1 still drew", drawn > 0, "opaque=%d" % drawn)
    outcome = py("r = state()")
    took = outcome.get("visible") is True
    print("    the show %s (this Maya %s spent its first show)"
          % ("STUCK" if took else "was UNDONE",
             "had already" if took else "had not"))
    notes, drawn = shoot("capture 2")
    one_note("capture 2's note matches the window's real state",
             notes, "up on screen now" if took else "did not take")
    if not took:
        check("nobody was told a window appeared when none did",
              all("up on screen" not in n for n in notes), notes)

    print("\nclaim 2: a show that STICKS - ask, then the outcome, then "
          "silence for good")
    # The process has had a successful show by now, so this hide/show sticks
    # (measured: only the first show of a process is undone).
    py("r = fresh(hidden=True)")
    notes, drawn = shoot("capture 1")
    one_note("capture 1 asks", notes, "asked Maya to show it")
    after = py("r = state()")
    if not check("the show stuck this time", after.get("visible") is True,
                 after):
        raise SystemExit("the fixture for claim 2 did not hold - a second "
                         "show should stick; measured %r" % (after,))
    notes, drawn = shoot("capture 2")
    one_note("capture 2 reports the window is up", notes, "up on screen now")
    check("capture 2 still drew", drawn > 0, "opaque=%d" % drawn)
    notes, drawn = shoot("capture 3")
    check("capture 3 says nothing - the defect was a note on every capture",
          notes == [], notes)

    print("\nclaim 3: a request Maya undoes is reported as one, not as a "
          "screen change (forced, so this holds on any run)")
    py("r = fresh(hidden=True)")
    py("r = arm_rehider()")
    notes, drawn = shoot("capture 1 (armed)")
    one_note("capture 1 asks, exactly as before", notes,
             "asked Maya to show it")
    check("capture 1 drew with the window hidden under it",
          drawn > 0, "opaque=%d" % drawn)
    undone = py("r = state()")
    fired = py("r = rehider_fired()")
    check("the show was undone, as Maya's start-up does",
          fired is True and undone.get("visible") is False,
          {"rehider_fired": fired, "state": undone})
    notes, drawn = shoot("capture 2 (undone)")
    one_note("capture 2 says the request did not take", notes, "did not take")
    if notes:
        check("and it does not claim a window appeared",
              "up on screen" not in notes[0], notes[0])
    stuck = py("r = state()")
    check("the retried show stuck, the way a later one does live",
          stuck.get("visible") is True, stuck)
    notes, drawn = shoot("capture 3 (up)")
    one_note("capture 3 reports the window is up", notes, "up on screen now")
    notes, drawn = shoot("capture 4")
    check("capture 4 says nothing: three facts, each said once",
          notes == [], notes)
    check("every frame drew while the window was going up and down",
          drawn > 0, "opaque=%d" % drawn)

    print("\nclaim 4: a window nobody hid is neither shown nor mentioned")
    vis = py("r = fresh(hidden=False)")
    check("the window is up before this claim", vis.get("visible") is True, vis)
    notes, drawn = shoot("capture on a visible window")
    check("no note at all - an interactive session must not hear from this",
          notes == [], notes)
    check("and it drew", drawn > 0, "opaque=%d" % drawn)

    print("\nclaim 5: the turntable, the other caller, carries ONE note - not "
          "one per frame")
    py("r = fresh(hidden=True)")
    turn = ok("capture_turntable", {"n_frames": 3, "resolution": 192},
              timeout_s=300.0)
    notes = window_notes(turn)
    one_note("the turntable asks once for its 3 frames", notes,
             "asked Maya to show it")
    frames = turn.get("images") or []
    drawn = [opaque_pixels(f.get("png_b64", "")) for f in frames]
    check("all 3 turntable frames drew",
          len(drawn) == 3 and all(d > 0 for d in drawn), drawn)

    print("\n(leaving the window minimised, the way the process was launched)")
    print("  " + str(py("r = tidy()")))

    failed = [c for c in CHECKS if not c[1]]
    print("\n%d/%d checks passed" % (len(CHECKS) - len(failed), len(CHECKS)))
    for label, _, detail in failed:
        print("  FAILED: %s  <- %s" % (label, detail))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
