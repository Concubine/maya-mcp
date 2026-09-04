"""Probe #826 part 2: can ensure_viewport_realized MEASURE its own claim
inside the one command it gets?

Part 1 measured, on a virgin agent Maya (pid 47160):
  - show() at t+0.7 s was undone by the next command; show() at t+3.0 s stuck
    and stayed stuck, and hide() -> show() sticks too.
  => the un-showing is a ONE-TIME boot event, not a permanent property of the
     process, and both branches are reachable on demand.

But in BOTH worlds `isVisible()` reads True synchronously inside the command
that called show(). The truth only appears on the next event-loop turn, and
the handler does not get one - it runs between turns. So it cannot tell what
happened unless it pumps.

This asks, in ONE command inside the boot race, whether a pump is a faithful
discriminator - and which pump:

  1 state as launched
  2 show()                              -> state (expected: visible, always)
  3 sendPostedEvents(w, 0)              -> state (Qt-posted events only)
  4 processEvents()                     -> state (also native messages)
  then, in the NEXT command, the ground truth.

A pump is faithful if its reading equals the next command's reading. Then it
also has to be harmless: after the pump the window must still be REALIZED
(that is what #765's show() is for), so the run ends with two captures.

Must run inside the first ~2 s after the port opens - part 1 measured the
race closing by t+3.0 s. Launch Maya, poll the port, run this immediately.

Run:  MAYA_MCP_PORT=9878 python evals/realized_note_probe_826b.py <tag>
"""
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import occlusion_probe_824 as p1  # noqa: E402
import isolate_blank_probe_825 as p825  # noqa: E402

TAG = sys.argv[1] if len(sys.argv) > 1 else "run"
OUT = os.path.join(_HERE, "realized_note_probe_826", TAG)
os.makedirs(OUT, exist_ok=True)

KEYS = ("visible", "hidden", "minimized", "native_surface")

PUMPS = '''
from maya.OpenMayaUI import MQtUtil
from shiboken6 import wrapInstance
from PySide6.QtWidgets import QWidget, QApplication

def state(w):
    return {"visible": w.isVisible(), "hidden": w.isHidden(),
            "minimized": w.isMinimized(),
            "native_surface": w.windowHandle() is not None}

w = wrapInstance(int(MQtUtil.mainWindow()), QWidget)
r = {"1_as_launched": state(w)}
w.show()
r["2_after_show"] = state(w)
QApplication.sendPostedEvents(w, 0)
r["3_after_sendPostedEvents"] = state(w)
QApplication.processEvents()
r["4_after_processEvents"] = state(w)
'''


def vis():
    s = p1.py('''
        from maya.OpenMayaUI import MQtUtil
        from shiboken6 import wrapInstance
        from PySide6.QtWidgets import QWidget
        w = wrapInstance(int(MQtUtil.mainWindow()), QWidget)
        r = {"visible": w.isVisible(), "hidden": w.isHidden(),
             "minimized": w.isMinimized(),
             "native_surface": w.windowHandle() is not None}
    ''')
    return {k: s.get(k) for k in KEYS}


def main():
    print("### probe 826b, tag=%s, port=%s" % (TAG, os.environ.get("MAYA_MCP_PORT")))
    t0 = time.time()
    out = p1.py(PUMPS)          # FIRST command of the session - stay in the race
    ground_truth = vis()        # the next command: what really happened
    dt = round(time.time() - t0, 2)
    print(json.dumps(out, indent=1, sort_keys=True))
    print("\n--- ground truth, next command (t+%ss) ---" % dt)
    print(json.dumps(ground_truth, sort_keys=True))

    truth = ground_truth.get("visible")
    verdict = {
        "raced": out["2_after_show"]["visible"] is True and truth is False,
        "next_command_visible": truth,
        "show_alone_agrees": out["2_after_show"]["visible"] == truth,
        "sendPostedEvents_agrees": out["3_after_sendPostedEvents"]["visible"] == truth,
        "processEvents_agrees": out["4_after_processEvents"]["visible"] == truth,
        "still_realized_after_pumps": out["4_after_processEvents"]["native_surface"],
    }

    # A pump that tells the truth is only usable if it does not cost the
    # realization the show() was for. Two captures say whether it draws.
    p1.ok("new_scene", {"confirm": True})
    p1.py(p1.LIB + "\nr = red_blue_scene()")
    p1.py(p825.LIB + "\nr = 1")
    cap_iso = p825.cap("B_isolate_after_pump", isolate=True, save=True)
    cap_plain = p825.cap("B_non_isolate_after_pump", isolate=False, save=True)
    verdict["isolate_drew_after_pump"] = cap_iso["opaque"]
    verdict["non_isolate_drew_after_pump"] = cap_plain["opaque"]
    verdict["visible_at_the_end"] = vis().get("visible")

    print("\n--- VERDICT ---")
    print(json.dumps(verdict, indent=1))
    with open(os.path.join(OUT, "pumps.json"), "w", encoding="utf-8") as fh:
        json.dump({"pumps": out, "ground_truth": ground_truth,
                   "verdict": verdict, "isolate": cap_iso,
                   "non_isolate": cap_plain}, fh, indent=1, default=str)


if __name__ == "__main__":
    main()
