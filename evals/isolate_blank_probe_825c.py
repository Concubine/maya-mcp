"""Probe #825 part 3: WHO un-shows the window?

Part 2 measured, on a virgin agent Maya: w.show() makes isVisible() True
synchronously, in the same command - and the very next command's capture
still reports "never been shown", i.e. it found isVisible() False again.
The plugin never hides anything (only one .show() in the whole plugin, no
hide/showMinimized/setWindowState anywhere), so Maya or Qt is doing it.

Two candidates, and they call for different fixes:

  TIME/EVENTS - Maya's own boot posts a window-state change (the process was
    started with -WindowStyle Minimized, i.e. STARTUPINFO SW_SHOWMINIMIZED)
    that is delivered on a later event-loop turn and undoes our show(). That
    would explain "2 of 3 processes": a race with the end of boot, and it
    predicts the un-showing STOPS once boot has settled.

  THE CAPTURE ITSELF - something in the playblast path (setFocus, offScreen
    playblast) drops the window. That would be ours to fix, and it predicts
    visibility survives idle gaps but dies across a capture.

So: show once, then read the state back over a series of client-side gaps
with NO capture in between, then do one capture and read it again.

Run:  MAYA_MCP_PORT=9879 python evals/isolate_blank_probe_825c.py <tag>
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
OUT = os.path.join(_HERE, "isolate_blank_probe_825", TAG)
os.makedirs(OUT, exist_ok=True)


def vis():
    s = p1.py("r = window_state()")
    return {k: s.get(k) for k in ("visible", "hidden", "minimized", "native_surface")}


def main():
    print("### probe 825c, tag=%s, port=%s" % (TAG, os.environ.get("MAYA_MCP_PORT")))
    t_connect = time.time()
    p1.ok("new_scene", {"confirm": True})
    p1.py(p1.LIB + "\nr = red_blue_scene()")
    p1.py(p825.LIB + "\nr = 1")

    rows = []

    def note(label, state):
        row = {"label": label, "t_since_connect_s": round(time.time() - t_connect, 1), **state}
        rows.append(row)
        print(json.dumps(row, sort_keys=True))

    note("as_launched", vis())

    shown = p1.py('''
        from maya.OpenMayaUI import MQtUtil
        from shiboken6 import wrapInstance
        from PySide6.QtWidgets import QWidget
        w = wrapInstance(int(MQtUtil.mainWindow()), QWidget)
        w.show()
        r = window_state()
    ''')
    note("right_after_show_same_command",
         {k: shown.get(k) for k in ("visible", "hidden", "minimized", "native_surface")})

    # No capture anywhere in here - only idle gaps, so any change is Maya's.
    for gap in (0, 1, 2, 5, 10, 20):
        if gap:
            time.sleep(gap)
        note("idle_gap_%ss" % gap, vis())

    print("\n--- one capture, then read it back ---")
    cap = p825.cap("C_isolate", isolate=True, save=False)
    print(json.dumps(cap, indent=1))
    note("after_one_capture", vis())

    lost = [r["label"] for r in rows if r.get("visible") is False][1:]
    print("\n--- VERDICT ---")
    print(json.dumps({
        "isolate_drew": cap["opaque"] > 0,
        "isolate_red": cap["red"],
        "never_shown_note_on_that_capture": cap["never_shown_note"],
        "points_where_visibility_was_lost_after_show": lost,
        "reading": ("MAYA/BOOT un-shows it (lost during idle gaps)" if lost
                    else "visibility SURVIVED idle; only a capture could drop it"),
    }, indent=1))
    with open(os.path.join(OUT, "decay.json"), "w", encoding="utf-8") as fh:
        json.dump({"rows": rows, "capture": cap}, fh, indent=1, default=str)


if __name__ == "__main__":
    main()
