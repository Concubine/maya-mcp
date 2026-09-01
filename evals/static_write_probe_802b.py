"""Live probe round 2 for redmine #802.

Round 1 (evals/static_write_probe_802.py) came back with an answer that
contradicts the ticket's central premise: a setAttr on a CONSTRAINT-driven
rotate did not raise, and an xform onto a LOCKED translate did not raise
either. Both are load-bearing - #802's whole design ("Maya refuses; catch it
first") rests on the first, and three of its eight pinned tests rest on the
second.

Round 1 could not tell two stories apart, so this round separates them:

  * did setAttr WRITE the constrained plug, or did it no-op while the
    constraint kept answering? Round 1's driver had zero rotation and its
    target value was zero on two of three axes, so the read-back was
    consistent with either. Here every value is distinct.
  * is a plain connectAttr destination refused? If it is, constraints and
    anim curves are a special case; if it is not, "connected" simply is not
    the thing setAttr refuses in this Maya.
  * does xform SKIP a locked child, or refuse the whole call? Round 1's
    locked axis already held the value being written.
  * does `getAttr -settable` predict the outcome in every case? Round 1 says
    it does, 9 for 9, which would make it the guard's predicate.

DESTRUCTIVE: file(new=True, force=True). Agent Maya on 9878; refuses 9877.

MEASURED 2026-09-01, Maya 2027 (apiVersion 20270200, evaluation mode
"parallel"), pid 35132. Both rounds' full output is in the ticket; the six
facts the fix is built on:

1. `getAttr(plug, settable=True)` predicted setAttr's outcome in all 14
   wirings measured, and nothing else did. False for a LOCK and for a plain
   `connectAttr`/expression destination; True for a constraint, an anim
   curve, a pairBlend and a set-driven key.

2. So **Maya does NOT refuse a constraint-driven or keyed static write.**
   `setAttr(joint.rotate, 77, 77, 77)` on an orientConstraint-driven joint
   returns cleanly, reads back 77, and reverts to the constraint's value at
   the next evaluation (O4/O5/O6). Same for a keyed plug across a frame
   change (K3/K4/K5) and for `xform` on a parentConstrained node
   (R3/R4/R5). The write is FUTILE, not refused - which is the worse of the
   two, because nothing raises and the handler reports success. #802's
   premise ("Maya raises 'locked or connected'; the handler lets it out
   raw") holds only for a LOCK and for a plain wire.

3. **`cmds.xform` never raises. It silently writes what it can.** Over a
   locked child: the free axes move and the locked one does not (L2/L3,
   L8/L9). Over a plain-connected child: same (P8/P9, X5/X6). `cmds.move`
   too (L4/L5), and `cmds.hide` on an expression-driven visibility returns
   cleanly and leaves the shape visible (W2/W3). Every handler that writes
   through xform is therefore a SILENT partial writer today, and no
   `except` clause can catch what does not raise. The guard has to be a
   pre-check.

4. `setAttr` on a COMPOUND refuses when any child is locked or hard-wired -
   "A child attribute of 'x.translate' is locked or connected" (A04, L6,
   P6, X3) - so a compound write is all-or-nothing where an xform is not.

5. Compound and child queries do not see each other. `getAttr(".rotate",
   lock=True)` is False while rotateX is locked (A01); `listConnections`
   on the compound returns None while every child is constraint-fed (B01,
   C01). A guard must ask about the compound AND each child, which is what
   `correctives._joint_rotation_writable` already does.
   `getAttr(compound, settable=True)` is the exception: it correctly
   answers False for a locked or hard-wired CHILD (B11, X1).

6. `getAttr` with `settable=True` RAISES ValueError on a missing attribute
   or node ("No object matches name"), and answers True for a pure output
   plug like worldMatrix[0] - so it is a predicate about refusal, not about
   meaning, and it cannot be asked blind.
"""

from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, _HERE)

from live_call import call, structured_result  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
if PORT == 9877 and os.environ.get("MAYA_MCP_ALLOW_USER_SESSION") != "1":
    raise SystemExit("refusing to run against 9877 (the user's Maya)")

PROBE = r'''
import json
import maya.cmds as cmds

out = {}

def attempt(label, fn):
    try:
        out[label] = {"raised": False, "returned": fn()}
    except Exception as exc:
        out[label] = {"raised": True, "type": type(exc).__name__,
                      "message": str(exc).strip()}

def ask(label, fn):
    try:
        out[label] = fn()
    except Exception as exc:
        out[label] = {"query_raised": True, "type": type(exc).__name__,
                      "message": str(exc).strip()}

cmds.file(new=True, force=True)

out["Z00_maya_version"] = cmds.about(apiVersion=True)
ask("Z01_evaluation_mode", lambda: cmds.evaluationManager(query=True,
                                                          mode=True))

# ============================================================ 1. PLAIN WIRE
# The plainest possible connection: no constraint, no curve, no blend.
src = cmds.spaceLocator(name="plainSrc")[0]
dst = cmds.spaceLocator(name="plainDst")[0]
cmds.connectAttr(src + ".translateX", dst + ".translateX")
cmds.setAttr(src + ".translateX", 2.0)

ask("P1_dst_settable", lambda: cmds.getAttr(dst + ".translateX",
                                            settable=True))
ask("P2_dst_compound_settable", lambda: cmds.getAttr(dst + ".translate",
                                                     settable=True))
ask("P3_dst_before", lambda: cmds.getAttr(dst + ".translateX"))
attempt("P4_setAttr_plain_connected_child",
        lambda: cmds.setAttr(dst + ".translateX", 9.0))
ask("P5_dst_after", lambda: cmds.getAttr(dst + ".translateX"))
attempt("P6_setAttr_plain_connected_compound",
        lambda: cmds.setAttr(dst + ".translate", 9.0, 9.0, 9.0))
ask("P7_dst_compound_after", lambda: cmds.getAttr(dst + ".translate")[0])
attempt("P8_xform_on_plain_connected",
        lambda: cmds.xform(dst, worldSpace=True, translation=(4.0, 4.0, 4.0)))
ask("P9_dst_after_xform", lambda: cmds.getAttr(dst + ".translate")[0])

# ==================================================== 2. ORIENT CONSTRAINT,
# with every number distinct so the read-back cannot be ambiguous.
cmds.select(clear=True)
oroot = cmds.joint(name="c2Root", position=(0, 0, 0))
okid = cmds.joint(name="c2Kid", position=(0, 2, 0))
drv = cmds.spaceLocator(name="c2Driver")[0]
cmds.setAttr(drv + ".rotateX", 11.0)
cmds.setAttr(drv + ".rotateY", 22.0)
cmds.setAttr(drv + ".rotateZ", 33.0)
cmds.orientConstraint(drv, okid, maintainOffset=False)

ask("O1_children_connected", lambda: [
    cmds.listConnections(okid + "." + a, source=True, destination=False,
                         plugs=True)
    for a in ("rotateX", "rotateY", "rotateZ")])
ask("O2_rotate_driven_value", lambda: cmds.getAttr(okid + ".rotate")[0])
ask("O3_settable_children", lambda: [
    cmds.getAttr(okid + "." + a, settable=True)
    for a in ("rotateX", "rotateY", "rotateZ")])
attempt("O4_setAttr_compound_77",
        lambda: cmds.setAttr(okid + ".rotate", 77.0, 77.0, 77.0))
ask("O5_rotate_right_after", lambda: cmds.getAttr(okid + ".rotate")[0])
cmds.dgdirty(okid)
ask("O6_rotate_after_dgdirty", lambda: cmds.getAttr(okid + ".rotate")[0])
cmds.currentTime(cmds.currentTime(query=True) + 1)
ask("O7_rotate_after_time_change", lambda: cmds.getAttr(okid + ".rotate")[0])
attempt("O8_setAttr_child_88", lambda: cmds.setAttr(okid + ".rotateY", 88.0))
ask("O9_rotateY_after", lambda: cmds.getAttr(okid + ".rotateY"))

# ==================================================== 3. PARENT CONSTRAINT
sub = cmds.polySphere(name="c3Sub")[0]
rider = cmds.spaceLocator(name="c3Rider")[0]
cmds.setAttr(rider + ".translateX", 5.0)
cmds.setAttr(rider + ".translateY", 6.0)
cmds.setAttr(rider + ".translateZ", 7.0)
cmds.parentConstraint(rider, sub, maintainOffset=False)
ask("R1_driven_translate", lambda: cmds.getAttr(sub + ".translate")[0])
ask("R2_settable_translateX", lambda: cmds.getAttr(sub + ".translateX",
                                                   settable=True))
attempt("R3_xform_ws_translation",
        lambda: cmds.xform(sub, worldSpace=True, translation=(1.0, 2.0, 3.0)))
ask("R4_translate_right_after", lambda: cmds.getAttr(sub + ".translate")[0])
cmds.dgdirty(sub)
ask("R5_translate_after_dgdirty", lambda: cmds.getAttr(sub + ".translate")[0])
ask("R6_ws_after", lambda: cmds.xform(sub, query=True, worldSpace=True,
                                      translation=True))

# ============================================ 4. LOCK vs xform: SKIP or FAIL
lk = cmds.spaceLocator(name="lockSkip")[0]
cmds.setAttr(lk + ".translateY", 3.0)
cmds.setAttr(lk + ".translateY", lock=True)
ask("L1_before", lambda: cmds.getAttr(lk + ".translate")[0])
attempt("L2_xform_ws_translation_over_locked_child",
        lambda: cmds.xform(lk, worldSpace=True, translation=(1.0, 1.0, 1.0)))
ask("L3_after", lambda: cmds.getAttr(lk + ".translate")[0])
attempt("L4_move_over_locked_child",
        lambda: cmds.move(2.0, 2.0, 2.0, lk, worldSpace=True))
ask("L5_after_move", lambda: cmds.getAttr(lk + ".translate")[0])
attempt("L6_setAttr_compound_over_locked_child",
        lambda: cmds.setAttr(lk + ".translate", 5.0, 5.0, 5.0))
ask("L7_after_setAttr", lambda: cmds.getAttr(lk + ".translate")[0])

# a locked ROTATE child, xform rotation with a distinct value
lr = cmds.spaceLocator(name="lockRot")[0]
cmds.setAttr(lr + ".rotateX", 12.0)
cmds.setAttr(lr + ".rotateX", lock=True)
attempt("L8_xform_rotation_over_locked_child",
        lambda: cmds.xform(lr, rotation=(0.0, 40.0, 0.0)))
ask("L9_rotate_after", lambda: cmds.getAttr(lr + ".rotate")[0])

# ================================== 5. xform PIVOT on a constrained/locked
pv = cmds.spaceLocator(name="pivotNode")[0]
cmds.setAttr(pv + ".translateX", lock=True)
attempt("V1_xform_pivot_when_translate_child_locked",
        lambda: cmds.xform(pv, worldSpace=True, pivots=(0.0, 5.0, 0.0)))
ask("V2_pivot_after", lambda: cmds.xform(pv, query=True, worldSpace=True,
                                         rotatePivot=True))
ask("V3_rotatePivot_settable",
    lambda: cmds.getAttr(pv + ".rotatePivotX", settable=True))

# ============================== 6. scale/visibility settable on shape nodes
sh = cmds.listRelatives(cmds.polyCube(name="visCube")[0], shapes=True,
                        fullPath=True)[0]
cmds.expression(string="%s.visibility = 1;" % sh, name="visExpr")
ask("W1_expr_vis_settable", lambda: cmds.getAttr(sh + ".visibility",
                                                 settable=True))
attempt("W2_hide_expr_driven_shape", lambda: cmds.hide(sh))
ask("W3_vis_after", lambda: cmds.getAttr(sh + ".visibility"))
attempt("W4_setAttr_expr_driven_vis",
        lambda: cmds.setAttr(sh + ".visibility", 0))

# ============================== 7. referenced-ish: a locked NODE (lockNode)
ln = cmds.spaceLocator(name="lockedNode")[0]
cmds.lockNode(ln, lock=True)
ask("N1_settable_on_locked_node", lambda: cmds.getAttr(ln + ".translateX",
                                                       settable=True))
attempt("N2_setAttr_on_locked_node",
        lambda: cmds.setAttr(ln + ".translateX", 3.0))
attempt("N3_xform_on_locked_node",
        lambda: cmds.xform(ln, worldSpace=True, translation=(3.0, 0.0, 0.0)))
ask("N4_after", lambda: cmds.getAttr(ln + ".translate")[0])
cmds.lockNode(ln, lock=False)

# ============================== 8. settable on a plug of a SHAPE vs XFORM,
# and on a compound whose child is CONNECTED (not locked)
cn = cmds.spaceLocator(name="childConn")[0]
feed = cmds.spaceLocator(name="childFeed")[0]
cmds.connectAttr(feed + ".rotateY", cn + ".rotateY")
ask("X1_compound_settable_child_connected",
    lambda: cmds.getAttr(cn + ".rotate", settable=True))
ask("X2_child_settable_connected", lambda: cmds.getAttr(cn + ".rotateY",
                                                        settable=True))
attempt("X3_setAttr_compound_child_connected",
        lambda: cmds.setAttr(cn + ".rotate", 15.0, 15.0, 15.0))
ask("X4_rotate_after", lambda: cmds.getAttr(cn + ".rotate")[0])
attempt("X5_xform_rotation_child_connected",
        lambda: cmds.xform(cn, rotation=(25.0, 25.0, 25.0)))
ask("X6_rotate_after_xform", lambda: cmds.getAttr(cn + ".rotate")[0])

# ============================== 9. animCurve: does the value SURVIVE a
# frame change, and does setKeyframe-less setAttr really stick?
ak = cmds.spaceLocator(name="keyedNode")[0]
cmds.setKeyframe(ak + ".translateY", time=1, value=0.0)
cmds.setKeyframe(ak + ".translateY", time=10, value=10.0)
cmds.currentTime(5)
ask("K1_value_at_5", lambda: cmds.getAttr(ak + ".translateY"))
ask("K2_settable", lambda: cmds.getAttr(ak + ".translateY", settable=True))
attempt("K3_setAttr_99", lambda: cmds.setAttr(ak + ".translateY", 99.0))
ask("K4_right_after", lambda: cmds.getAttr(ak + ".translateY"))
cmds.currentTime(6)
ask("K5_after_frame_change", lambda: cmds.getAttr(ak + ".translateY"))
attempt("K6_xform_on_keyed",
        lambda: cmds.xform(ak, worldSpace=True, translation=(0.0, 55.0, 0.0)))
ask("K7_after_xform", lambda: cmds.getAttr(ak + ".translateY"))

json.dumps(out)
'''


def main() -> int:
    resp = call("execute_python", {"code": PROBE}, timeout_s=300)
    if resp.get("status") != "ok":
        print(json.dumps(resp, indent=2)[:6000])
        return 2
    data = json.loads(structured_result(resp.get("result") or {}, "probe"))
    for key in sorted(data):
        print("%-46s %s" % (key, json.dumps(data[key])[:300]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
