"""Throwaway probe for #826: is the note's claim ever true, and can BOTH
branches be reached on demand?

`capture.ensure_viewport_realized` calls `w.show()` on Maya's main window
when `isVisible()` is False and then ASSERTS "this call showed it". Probe
825c measured, on a virgin agent Maya, that the window reads hidden again by
the very next command and stays hidden across idle gaps of 0-20 s and across
a capture - so the claim was false there, and repeated on every capture
because visibility never latched.

825c called show() ONCE, at t+0.5 s, and then only re-read the state. So it
did not separate two very different worlds:

  ONE-TIME  Maya's boot posts a hide/window-state event that lands after our
            show() and undoes it. Then a LATER show() sticks, the current
            code converges by itself, and the honest note is "showed it" on
            whichever capture finally made it stick.
  PERMANENT Something keeps the main window hidden for the life of the
            process. Then no show() ever sticks and the note is simply false
            in this class of process.

This asks that directly: show(), read back in the same command AND in the
next one, repeated at t = 0, 2, 5, 10, 20, 40 s. Then, if any show sticks,
hide() -> show() to see whether the "it stuck" branch is reachable on demand
for a live gate. A capture at the end says whether #765's blank state is
even present in this process (the show() is there to protect against it).

Run:  MAYA_MCP_PORT=9878 python evals/realized_note_probe_826.py <tag>
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

SHOW = '''
from maya.OpenMayaUI import MQtUtil
from shiboken6 import wrapInstance
from PySide6.QtWidgets import QWidget
w = wrapInstance(int(MQtUtil.mainWindow()), QWidget)
before = window_state()
w.%s()
r = {"before": before, "after_same_command": window_state()}
'''


def vis():
    s = p1.py("r = window_state()")
    return {k: s.get(k) for k in KEYS}


def trim(state):
    return {k: state.get(k) for k in KEYS}


def main():
    print("### probe 826, tag=%s, port=%s" % (TAG, os.environ.get("MAYA_MCP_PORT")))
    t0 = time.time()
    p1.ok("new_scene", {"confirm": True})
    p1.py(p1.LIB + "\nr = red_blue_scene()")
    p1.py(p825.LIB + "\nr = 1")

    rows = []

    def attempt(label, method="show"):
        out = p1.py(SHOW % method)
        row = {
            "label": label,
            "t_s": round(time.time() - t0, 1),
            "before": trim(out["before"]),
            "same_command": trim(out["after_same_command"]),
            "next_command": vis(),
        }
        rows.append(row)
        print(json.dumps(row, sort_keys=True))
        return row

    print("\n--- as launched ---")
    print(json.dumps(vis(), sort_keys=True))

    # Q1: does a LATER show() stick, or does nothing ever stick?
    stuck = []
    for gap in (0, 2, 5, 10, 20, 40):
        if gap:
            time.sleep(gap)
        row = attempt("show_at_t%s" % gap)
        if row["next_command"].get("visible") is True:
            stuck.append(row["label"])
            break

    # Q2: with the window genuinely up, is hide() -> show() a way for a gate
    # to reach the "it stuck" branch on demand?
    hide_show = None
    if stuck:
        attempt("hide_after_it_stuck", method="hide")
        hide_show = attempt("show_again_after_hide")

    # Q3: is #765's blank state present here at all? (the show() protects it)
    cap_isolate = p825.cap("A_isolate", isolate=True, save=True)
    cap_plain = p825.cap("B_non_isolate", isolate=False, save=True)
    print("\n--- captures ---")
    print(json.dumps({"isolate": cap_isolate, "non_isolate": cap_plain}, indent=1))
    after_capture = vis()

    verdict = {
        "any_show_stuck_to_the_next_command": bool(stuck),
        "first_show_that_stuck": stuck[0] if stuck else None,
        "reading": ("ONE-TIME: a later show() sticks, the note can become true"
                    if stuck else
                    "PERMANENT: no show() stuck in %d attempts across %s s"
                    % (len(rows), rows[-1]["t_s"] if rows else 0)),
        "hide_then_show_reaches_the_stuck_branch":
            (hide_show["next_command"].get("visible") is True) if hide_show else None,
        "note_fired_on_capture": cap_isolate["never_shown_note"],
        "window_visible_after_all_that": after_capture.get("visible"),
        "isolate_drew": cap_isolate["opaque"],
        "non_isolate_drew": cap_plain["opaque"],
    }
    print("\n--- VERDICT ---")
    print(json.dumps(verdict, indent=1))
    with open(os.path.join(OUT, "shows.json"), "w", encoding="utf-8") as fh:
        json.dump({"rows": rows, "verdict": verdict, "isolate": cap_isolate,
                   "non_isolate": cap_plain, "after_capture": after_capture},
                  fh, indent=1, default=str)


if __name__ == "__main__":
    main()
