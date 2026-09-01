"""Live probe for redmine #802: what Maya ACTUALLY does with a static write
to a locked or connection-fed plug.

Written BEFORE the fix, per the ticket's own instruction and #796's lesson
(three review rounds arguing behaviours one probe settles). It measures, it
does not assert: every question below is one the guard's design turns on, and
every answer here is a fact the fix is allowed to rely on.

DESTRUCTIVE: calls file(new=True, force=True). Runs against the disposable
agent Maya on 9878 and REFUSES 9877.

Run:  MAYA_MCP_PORT=9878 .venv/Scripts/python.exe evals/static_write_probe_802.py
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
    """Run a write and record what Maya did with it."""
    try:
        fn()
        out[label] = {"raised": False}
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

# ---------------------------------------------------------------- A. LOCK
root = cmds.joint(name="lockRoot", position=(0, 0, 0))
kid = cmds.joint(name="lockKid", position=(0, 2, 0))
cmds.setAttr(kid + ".rotateX", lock=True)

ask("A01_compound_lock_query_when_one_child_locked",
    lambda: cmds.getAttr(kid + ".rotate", lock=True))
ask("A02_child_lock_query_locked_child",
    lambda: cmds.getAttr(kid + ".rotateX", lock=True))
ask("A03_child_lock_query_free_sibling",
    lambda: cmds.getAttr(kid + ".rotateY", lock=True))
attempt("A04_setAttr_compound_with_one_child_locked",
        lambda: cmds.setAttr(kid + ".rotate", 0.0, 0.0, 0.0))
attempt("A05_setAttr_free_sibling_child",
        lambda: cmds.setAttr(kid + ".rotateY", 5.0))
attempt("A06_setAttr_locked_child_itself",
        lambda: cmds.setAttr(kid + ".rotateX", 5.0))
attempt("A07_xform_rotation_with_one_child_locked",
        lambda: cmds.xform(kid, rotation=(0.0, 0.0, 0.0)))
ask("A08_rotate_after_all_that", lambda: cmds.getAttr(kid + ".rotate")[0])

# A locked COMPOUND: does the child report locked?
lockc = cmds.spaceLocator(name="lockCompound")[0]
cmds.setAttr(lockc + ".translate", lock=True)
ask("A09_child_lock_query_when_compound_locked",
    lambda: cmds.getAttr(lockc + ".translateX", lock=True))
ask("A10_compound_lock_query_when_compound_locked",
    lambda: cmds.getAttr(lockc + ".translate", lock=True))
attempt("A11_setAttr_child_when_compound_locked",
        lambda: cmds.setAttr(lockc + ".translateX", 3.0))
attempt("A12_xform_translation_when_compound_locked",
        lambda: cmds.xform(lockc, worldSpace=True, translation=(1.0, 2.0, 3.0)))
ask("A13_translate_after", lambda: cmds.getAttr(lockc + ".translate")[0])

# ------------------------------------------------------ B. ORIENT CONSTRAINT
cmds.select(clear=True)
oroot = cmds.joint(name="ocRoot", position=(0, 0, 0))
okid = cmds.joint(name="ocKid", position=(0, 2, 0))
driver = cmds.spaceLocator(name="ocDriver")[0]
cmds.setAttr(driver + ".translateX", 3.0)
oc = cmds.orientConstraint(driver, okid)[0]

ask("B01_listConnections_on_rotate_COMPOUND",
    lambda: cmds.listConnections(okid + ".rotate", source=True,
                                 destination=False, plugs=True))
ask("B02_listConnections_on_rotateX_CHILD",
    lambda: cmds.listConnections(okid + ".rotateX", source=True,
                                 destination=False, plugs=True))
ask("B03_connectionInfo_rotateX",
    lambda: cmds.connectionInfo(okid + ".rotateX", sourceFromDestination=True))
ask("B04_connectionInfo_rotate_compound",
    lambda: cmds.connectionInfo(okid + ".rotate", sourceFromDestination=True))
ask("B05_isDestination_rotate_compound",
    lambda: cmds.connectionInfo(okid + ".rotate", isDestination=True))
ask("B06_isDestination_rotateX",
    lambda: cmds.connectionInfo(okid + ".rotateX", isDestination=True))
ask("B07_lock_query_on_constrained_child",
    lambda: cmds.getAttr(okid + ".rotateX", lock=True))
ask("B08_settable_query_on_constrained_child",
    lambda: cmds.getAttr(okid + ".rotateX", settable=True))
ask("B09_settable_query_on_constrained_compound",
    lambda: cmds.getAttr(okid + ".rotate", settable=True))
ask("B10_settable_query_on_locked_child",
    lambda: cmds.getAttr(kid + ".rotateX", settable=True))
ask("B11_settable_query_on_compound_with_one_locked_child",
    lambda: cmds.getAttr(kid + ".rotate", settable=True))
ask("B12_settable_free_plug",
    lambda: cmds.getAttr(oroot + ".rotate", settable=True))
attempt("B13_setAttr_constrained_rotate_compound",
        lambda: cmds.setAttr(okid + ".rotate", 0.0, 0.0, 10.0))
attempt("B14_setAttr_constrained_rotateX_child",
        lambda: cmds.setAttr(okid + ".rotateX", 10.0))
attempt("B15_xform_rotation_on_constrained_joint",
        lambda: cmds.xform(okid, rotation=(0.0, 0.0, 10.0)))
ask("B16_rotate_after", lambda: cmds.getAttr(okid + ".rotate")[0])

# ------------------------------------------------------ C. PARENT CONSTRAINT
cam = cmds.camera(name="probeCam")
camx = cam[0]
rider = cmds.spaceLocator(name="camDriver")[0]
cmds.setAttr(rider + ".translateY", 4.0)
pc = cmds.parentConstraint(rider, camx)[0]

ask("C01_translate_compound_connections",
    lambda: cmds.listConnections(camx + ".translate", source=True,
                                 destination=False, plugs=True))
ask("C02_translateX_child_connections",
    lambda: cmds.listConnections(camx + ".translateX", source=True,
                                 destination=False, plugs=True))
ask("C03_settable_translate_compound",
    lambda: cmds.getAttr(camx + ".translate", settable=True))
ask("C04_settable_translateX", lambda: cmds.getAttr(camx + ".translateX",
                                                    settable=True))
out["C05_translate_before"] = cmds.xform(camx, query=True, worldSpace=True,
                                         translation=True)
attempt("C06_xform_worldSpace_translation_on_parentConstrained",
        lambda: cmds.xform(camx, worldSpace=True, translation=(1.0, 2.0, 3.0)))
ask("C07_translate_after",
    lambda: cmds.xform(camx, query=True, worldSpace=True, translation=True))
attempt("C08_move_on_parentConstrained",
        lambda: cmds.move(1.0, 2.0, 3.0, camx, worldSpace=True))
ask("C09_translate_after_move",
    lambda: cmds.xform(camx, query=True, worldSpace=True, translation=True))

# ------------------------------------------------------- D. AIM CONSTRAINT
aimcam = cmds.camera(name="aimCam")[0]
aimtgt = cmds.spaceLocator(name="aimTarget")[0]
cmds.setAttr(aimtgt + ".translateZ", -6.0)
ac = cmds.aimConstraint(aimtgt, aimcam)[0]
ask("D01_aim_rotate_children_connected",
    lambda: cmds.listConnections(aimcam + ".rotateX", source=True,
                                 destination=False, plugs=True))
ask("D02_aim_translate_settable",
    lambda: cmds.getAttr(aimcam + ".translateX", settable=True))
ask("D03_aim_rotate_settable",
    lambda: cmds.getAttr(aimcam + ".rotateX", settable=True))
out["D04_translate_before"] = cmds.xform(aimcam, query=True, worldSpace=True,
                                         translation=True)
attempt("D05_xform_translation_on_aim_constrained",
        lambda: cmds.xform(aimcam, worldSpace=True, translation=(2.0, 2.0, 2.0)))
ask("D06_translate_after",
    lambda: cmds.xform(aimcam, query=True, worldSpace=True, translation=True))
attempt("D07_xform_rotation_on_aim_constrained",
        lambda: cmds.xform(aimcam, rotation=(0.0, 45.0, 0.0)))
ask("D08_rotate_after", lambda: cmds.getAttr(aimcam + ".rotate")[0])

# ------------------------------------------------- E. KEYED VISIBILITY / YAW
sph = cmds.polySphere(name="keyedSphere")[0]
shape = cmds.listRelatives(sph, shapes=True, fullPath=True)[0]
cmds.setKeyframe(shape + ".visibility", time=1, value=1)
cmds.setKeyframe(shape + ".visibility", time=10, value=0)
ask("E01_vis_connections",
    lambda: cmds.listConnections(shape + ".visibility", source=True,
                                 destination=False, plugs=True))
ask("E02_vis_settable", lambda: cmds.getAttr(shape + ".visibility",
                                             settable=True))
attempt("E03_setAttr_keyed_visibility",
        lambda: cmds.setAttr(shape + ".visibility", 0))
ask("E04_vis_after", lambda: cmds.getAttr(shape + ".visibility"))
attempt("E05_hide_keyed_shape", lambda: cmds.hide(shape))
ask("E06_vis_after_hide", lambda: cmds.getAttr(shape + ".visibility"))

lite = cmds.directionalLight(name="probeKey")
_par = cmds.listRelatives(lite, parent=True, fullPath=True)
litex = _par[0] if _par else lite
cmds.setKeyframe(litex + ".rotateY", time=1, value=30)
ask("E07_light_yaw_settable", lambda: cmds.getAttr(litex + ".rotateY",
                                                   settable=True))
attempt("E08_setAttr_keyed_light_yaw",
        lambda: cmds.setAttr(litex + ".rotateY", 120.0))
ask("E09_yaw_after", lambda: cmds.getAttr(litex + ".rotateY"))

# ------------------------------------------------------- F. PAIRBLEND / SDK
pbj = cmds.spaceLocator(name="pairBlendNode")[0]
cmds.setKeyframe(pbj + ".rotateY", time=1, value=0)
cmds.orientConstraint(driver, pbj)
ask("F01_pairblend_source",
    lambda: cmds.listConnections(pbj + ".rotateY", source=True,
                                 destination=False, plugs=True))
ask("F02_pairblend_settable",
    lambda: cmds.getAttr(pbj + ".rotateY", settable=True))
attempt("F03_setAttr_through_pairblend",
        lambda: cmds.setAttr(pbj + ".rotateY", 45.0))
ask("F04_after", lambda: cmds.getAttr(pbj + ".rotateY"))

sdk = cmds.spaceLocator(name="sdkNode")[0]
cmds.setDrivenKeyframe(sdk + ".translateY", currentDriver=driver + ".translateX",
                       driverValue=0.0, value=0.0)
cmds.setDrivenKeyframe(sdk + ".translateY", currentDriver=driver + ".translateX",
                       driverValue=5.0, value=5.0)
ask("F05_sdk_settable", lambda: cmds.getAttr(sdk + ".translateY", settable=True))
attempt("F06_xform_on_sdk_driven",
        lambda: cmds.xform(sdk, worldSpace=True, translation=(0.0, 9.0, 0.0)))
ask("F07_sdk_ty_after", lambda: cmds.getAttr(sdk + ".translateY"))

# ------------------------------------- G. focalLength on an animated lens
alens = cmds.camera(name="animLens")
alensShape = alens[1]
cmds.setKeyframe(alensShape + ".focalLength", time=1, value=35)
ask("G01_focal_settable", lambda: cmds.getAttr(alensShape + ".focalLength",
                                               settable=True))
attempt("G02_setAttr_keyed_focal",
        lambda: cmds.setAttr(alensShape + ".focalLength", 50.0))
ask("G03_focal_after", lambda: cmds.getAttr(alensShape + ".focalLength"))

# ------------------------------ H. partial xform: a refused write on rotate
# after a successful sibling write on translate
mix = cmds.spaceLocator(name="mixedLock")[0]
cmds.setAttr(mix + ".rotateY", lock=True)
attempt("H01_xform_translation_free_on_rot_locked_node",
        lambda: cmds.xform(mix, worldSpace=True, translation=(5.0, 0.0, 0.0)))
attempt("H02_xform_rotation_locked",
        lambda: cmds.xform(mix, rotation=(0.0, 30.0, 0.0)))
ask("H03_state", lambda: [cmds.getAttr(mix + ".translate")[0],
                          cmds.getAttr(mix + ".rotate")[0]])
# One xform call carrying BOTH a legal and an illegal write: partial?
mix2 = cmds.spaceLocator(name="mixedLock2")[0]
cmds.setAttr(mix2 + ".rotateY", lock=True)
attempt("H04_xform_translation_and_rotation_one_call",
        lambda: cmds.xform(mix2, worldSpace=True, translation=(7.0, 0.0, 0.0),
                           rotation=(0.0, 30.0, 0.0)))
ask("H05_state", lambda: [cmds.getAttr(mix2 + ".translate")[0],
                          cmds.getAttr(mix2 + ".rotate")[0]])

# ------------------------------ I. does xform(query) still work on locked?
ask("I01_query_on_locked",
    lambda: cmds.xform(lockc, query=True, worldSpace=True, translation=True))

# ------------------------------ J. expression-driven plug
expr_node = cmds.spaceLocator(name="exprNode")[0]
cmds.expression(string="%s.translateY = time;" % expr_node, name="probeExpr")
ask("J01_expr_settable", lambda: cmds.getAttr(expr_node + ".translateY",
                                              settable=True))
ask("J02_expr_source",
    lambda: cmds.listConnections(expr_node + ".translateY", source=True,
                                 destination=False, plugs=True))
attempt("J03_setAttr_expr_driven",
        lambda: cmds.setAttr(expr_node + ".translateY", 7.0))

# ------------------------------ K. a plug that is a SOURCE only
srcnode = cmds.spaceLocator(name="srcNode")[0]
dstnode = cmds.spaceLocator(name="dstNode")[0]
cmds.connectAttr(srcnode + ".translateX", dstnode + ".translateX")
ask("K01_source_side_settable",
    lambda: cmds.getAttr(srcnode + ".translateX", settable=True))
ask("K02_source_side_listConnections_source_only",
    lambda: cmds.listConnections(srcnode + ".translateX", source=True,
                                 destination=False, plugs=True))
attempt("K03_setAttr_on_source_side",
        lambda: cmds.setAttr(srcnode + ".translateX", 4.0))

# ------------------------------ L. the OTHER plugs these handlers write
ask("L01_settable_jointOrient_on_locked_rot_joint",
    lambda: cmds.getAttr(kid + ".jointOrient", settable=True))
ask("L02_settable_scale_on_locked_rot_joint",
    lambda: cmds.getAttr(kid + ".scale", settable=True))
# A referenced-style read-only plug: worldMatrix output
ask("L03_settable_worldMatrix",
    lambda: cmds.getAttr(kid + ".worldMatrix[0]", settable=True))

# ------------------------------ M. settable on a NON-EXISTENT plug and on a
# plug of a node that does not exist: does the guard's own query raise?
ask("M01_settable_missing_attr",
    lambda: cmds.getAttr(kid + ".noSuchAttr", settable=True))
ask("M02_settable_missing_node",
    lambda: cmds.getAttr("|noSuchNodeAnywhere.translateX", settable=True))

json.dumps(out)
'''


def main() -> int:
    resp = call("execute_python", {"code": PROBE}, timeout_s=300)
    if resp.get("status") != "ok":
        print(json.dumps(resp, indent=2)[:6000])
        return 2
    payload = structured_result(resp.get("result") or {}, "probe")
    data = json.loads(payload)
    for key in sorted(data):
        print("%-52s %s" % (key, json.dumps(data[key])[:300]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
