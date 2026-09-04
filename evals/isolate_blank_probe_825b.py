"""Probe #825 part 2: does ensure_viewport_realized's window.show() actually
realize the window, or only queue the request?

Measured in part 1, on two separate virgin agent Mayas: the "never been shown"
note fires on capture 1 AND on capture 2, then stops. So after the first
show() the window is STILL not visible on the next call - it only latches
later. #825's failing processes are the case where it never latches at all,
and every isolate capture in them draws nothing.

show() is documented to be asynchronous: it posts a show event, and the widget
is not realized until Qt delivers it. The plugin runs commands on Maya's main
thread between event-loop turns, so nothing delivers that event inside the
capture that asked for it.

This asks the question in ONE command on a virgin process, so there is no
event-loop turn between the steps to muddy it:

  1. state as launched
  2. show()            -> state immediately after, same command
  3. processEvents()   -> state immediately after, same command

If step 2 is still not visible and step 3 is, show() alone is the defect.

Run:  MAYA_MCP_PORT=9879 python evals/isolate_blank_probe_825b.py <tag>
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import occlusion_probe_824 as p1  # noqa: E402
import isolate_blank_probe_825 as p825  # noqa: E402

TAG = sys.argv[1] if len(sys.argv) > 1 else "run"


def main():
    print("### probe 825b, tag=%s, port=%s" % (TAG, os.environ.get("MAYA_MCP_PORT")))
    p1.ok("new_scene", {"confirm": True})
    p1.py(p1.LIB + "\nr = red_blue_scene()")
    p1.py(p825.LIB + "\nr = 1")

    out = p1.py('''
        from maya.OpenMayaUI import MQtUtil
        from shiboken6 import wrapInstance
        from PySide6.QtWidgets import QWidget, QApplication
        w = wrapInstance(int(MQtUtil.mainWindow()), QWidget)
        a = window_state()
        w.show()
        b = window_state()
        QApplication.processEvents()
        c = window_state()
        r = {"1_as_launched": a, "2_after_show": b, "3_after_processEvents": c}
    ''')
    print(json.dumps(out, indent=1, sort_keys=True))

    verdict = {
        "show_alone_realized": out["2_after_show"].get("visible"),
        "processEvents_realized": out["3_after_processEvents"].get("visible"),
    }
    verdict["show_is_async_defect"] = (
        out["1_as_launched"].get("visible") is False
        and out["2_after_show"].get("visible") is False
        and out["3_after_processEvents"].get("visible") is True
    )
    print("\n--- VERDICT ---")
    print(json.dumps(verdict, indent=1))

    # And the thing that matters: does the isolate view draw on the very
    # first capture of this process, now that the window is genuinely up?
    print("\n--- first isolate capture after a REALIZED window ---")
    print(json.dumps(p825.cap("B_isolate_after_realized", isolate=True), indent=1))


if __name__ == "__main__":
    main()
