"""Live gate for redmine #802: no command writes a plug the rig owns.

The headless suite proves the guard is CALLED. Only Maya can prove it was
asked the right question, because the whole ticket turns on behaviours a
fake asserts rather than observes - and this ticket's own probe found two
of those assertions to be false (see evals/static_write_probe_802b.py):
Maya does not refuse a constraint-driven setAttr, and `cmds.xform` does not
refuse anything at all. So every check below builds the real wiring, calls
the real command, and then asks Maya what actually happened to the plug.

Each phase pairs a REFUSAL with its negative control. A guard that refuses
everything passes half a gate and breaks every rig it is meant to protect;
#799's lesson is that a check wrong in the strict direction is as expensive
as a permissive one, so the free-channel case is asserted every time.

DESTRUCTIVE: calls maya_new_scene. Runs against the disposable agent Maya on
9878 and REFUSES 9877 (the user's session) unless
MAYA_MCP_ALLOW_USER_SESSION=1.

Launch that Maya with the repo as its working directory, so Maya's
CWD-on-sys.path makes it import THIS tree rather than the deployed copy in
Documents/maya/scripts. Phase 0 asserts exactly that.

Run:  MAYA_MCP_PORT=9878 MAYA_MCP_EXPECT_PID=<pid> \
        .venv/Scripts/python.exe evals/static_write_guard_live.py
Exit: 0 pass, 1 fail, 2 environment.
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, _HERE)

from live_call import call, structured_result  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
if PORT == 9877 and os.environ.get("MAYA_MCP_ALLOW_USER_SESSION") != "1":
    print("refusing to run against port 9877 (the user's Maya): this gate "
          "calls new_scene. Set MAYA_MCP_ALLOW_USER_SESSION=1 to override.",
          file=sys.stderr)
    raise SystemExit(2)

RESULTS = []


def check(label, ok, detail=""):
    RESULTS.append((label, bool(ok), detail))
    print("%-4s %-62s %s" % ("PASS" if ok else "FAIL", label, detail),
          flush=True)


def send(command, params, timeout_s=180.0):
    return call(command, params, timeout_s=timeout_s, port=PORT)


def ok(command, params, timeout_s=180.0):
    response = send(command, params, timeout_s)
    if response.get("status") != "ok":
        raise SystemExit("%s failed: %s" % (command, response.get("error")))
    return response.get("result") or {}


def refusal(command, params, timeout_s=180.0):
    """The error payload of a call that MUST refuse, or None if it did not."""
    response = send(command, params, timeout_s)
    if response.get("status") == "ok":
        return None
    return response.get("error") or {}


def py(code, what, timeout_s=180.0):
    return structured_result(ok("execute_python", {"code": code}, timeout_s),
                             what)


def refused_well(err, *needles):
    """A refusal is only a fix if it is a HandlerError that names the plug."""
    if not err:
        return False, "the call SUCCEEDED"
    if err.get("type") != "HandlerError":
        return False, "raw %s: %s" % (err.get("type"), err.get("message"))
    text = "%s %s" % (err.get("message", ""), err.get("hint") or "")
    missing = [n for n in needles if n not in text]
    if missing:
        return False, "message never names %s: %r" % (missing, text[:200])
    if not err.get("hint"):
        return False, "no hint"
    return True, err.get("message", "")[:110]


# --------------------------------------------------------------- phase 0
print("=== 0. who answered, and whose code is it ===", flush=True)
ident = py(
    "import os, maya_plugin\n"
    "{'file': maya_plugin.__file__, 'cwd': os.getcwd()}", "identity")
loaded = os.path.normcase(os.path.abspath(ident["file"]))
expected = os.path.normcase(os.path.join(REPO, "maya_plugin", "__init__.py"))
if loaded != expected:
    print("WRONG CODE: live Maya imports %s, not %s. Relaunch it with the "
          "repo as its working directory." % (loaded, expected),
          file=sys.stderr)
    raise SystemExit(2)
print("live plugin: %s" % loaded, flush=True)
has_module = py("from maya_plugin.handlers import plugwrite\n"
                "sorted(plugwrite._CHILDREN)", "plugwrite")
check("0. the guard module is loaded in the live Maya",
      "rotate" in has_module and "rotatePivot" in has_module,
      "compounds: %d" % len(has_module))

# --------------------------------------------------------------- phase 1
print("\n=== 1. pose_skeleton / reset_pose / pose_ik ===", flush=True)
ok("new_scene", {"confirm": True})
py("""
import maya.cmds as cmds
cmds.select(clear=True)
cmds.joint(name='root', position=(0, 0, 0))
cmds.joint(name='mid', position=(0, 2, 0))
cmds.joint(name='tip', position=(0, 4, 0))
# A non-zero pose, so a HALF-reset is visible as a plug that moved.
cmds.setAttr('root.rotateZ', 12.0)
cmds.setAttr('mid.rotateZ', 20.0)
drv = cmds.spaceLocator(name='drv')[0]
cmds.setAttr(drv + '.rotateX', 30.0)
cmds.orientConstraint(drv, 'mid', maintainOffset=False)
cmds.setAttr('tip.rotateX', lock=True)
'built'
""", "rig")

# What the CONSTRAINT holds mid at right now. NOT zero: the driver is
# pitched 30 and mid's parent is rolled 12, so the constraint solves a local
# (30, 0, -12) to put mid's world orientation on the driver's. Round 1 of
# this gate compared against zero and failed itself - a gate asserting its
# own arithmetic rather than the handler's behaviour.
driven_before = py("import maya.cmds as cmds\ncmds.getAttr('mid.rotate')[0]",
                   "mid before")
err = refusal("pose_skeleton", {"root": "root", "rotations": {"mid": [0, 0, 45]}})
passed, detail = refused_well(err, "mid", "orientConstraint")
check("1a. pose_skeleton refuses a constraint-driven joint", passed, detail)

after = py("import maya.cmds as cmds\ncmds.getAttr('mid.rotate')[0]", "mid")
drift = max(abs(a - b) for a, b in zip(driven_before, after))
check("1b. ...and the joint still reads what the rig holds it at",
      drift < 1e-6 and abs(after[2] - 45.0) > 1.0,
      "mid.rotate %s -> %s (45 was asked for)" % (driven_before, after))

out = ok("pose_skeleton", {"root": "root", "rotations": {"root": [0, 0, 25]}})
free = py("import maya.cmds as cmds\ncmds.getAttr('root.rotateZ')", "root")
check("1c. NEGATIVE CONTROL: a free joint in the same rig still poses",
      out.get("applied") == 1 and abs(free - 25.0) < 1e-4,
      "root.rotateZ = %.3f, applied=%s" % (free, out.get("applied")))

err = refusal("reset_pose", {"root": "root"})
passed, detail = refused_well(err, "tip", "lock")
check("1d. reset_pose refuses a locked rotate channel", passed, detail)

state = py("import maya.cmds as cmds\n"
           "[cmds.getAttr(j + '.rotateZ') for j in ('root', 'mid', 'tip')]",
           "pose")
check("1e. ...BEFORE it zeroed any joint (the half-reset #802 names)",
      abs(state[0] - 25.0) < 1e-4,
      "root.rotateZ = %.3f (25 = untouched, 0 = half-reset)" % state[0])

err = refusal("pose_ik", {"root": "root", "joint": "tip",
                          "target": [1.0, 3.0, 0.0], "start": "root"})
passed, detail = refused_well(err, "lock")
check("1f. pose_ik refuses the same locked chain", passed, detail)

py("import maya.cmds as cmds\ncmds.setAttr('tip.rotateX', lock=False)\n'ok'",
   "unlock")
err = refusal("pose_ik", {"root": "root", "joint": "tip",
                          "target": [1.0, 3.0, 0.0], "start": "root"})
passed, detail = refused_well(err, "mid", "orientConstraint")
check("1g. pose_ik refuses the constrained chain joint too", passed, detail)

# The branch every BOUND rig takes is `dagPose -restore`, which returns a
# whole transform. Review of the first cut found it guarded .rotate for a
# setAttr that branch never makes and missed the translate it does write.
ok("new_scene", {"confirm": True})
py("""
import maya.cmds as cmds
cmds.select(clear=True)
cmds.joint(name='bRoot', position=(0, 0, 0))
cmds.joint(name='bKid', position=(0, 2, 0))
mesh = cmds.polyCylinder(name='sleeve', r=0.5, h=2)[0]
cmds.select(clear=True)
cmds.skinCluster('bRoot', 'bKid', mesh, toSelectedBones=True)
cmds.setAttr('bKid.rotateZ', 30.0)
cmds.setAttr('bKid.scaleX', lock=True)   # a rigger's routine cleanup
'bound'
""", "bound rig")
poses = py("import maya.cmds as cmds\n"
           "cmds.dagPose('bRoot', query=True, bindPose=True) or []", "poses")
check("1h. the bound rig really has a bind pose (the branch under test)",
      bool(poses), "poses = %s" % (poses,))
out = ok("reset_pose", {"root": "bRoot"})
rz = py("import maya.cmds as cmds\ncmds.getAttr('bKid.rotateZ')", "rz")
check("1i. NEGATIVE CONTROL: a locked SCALE does not stop the bind restore",
      out.get("reset") is True and abs(rz) < 1e-4,
      "reset=%s bKid.rotateZ=%.3f (0 = restored)" % (out.get("reset"), rz))
py("import maya.cmds as cmds\ncmds.setAttr('bKid.rotateZ', 30.0)\n"
   "cmds.setAttr('bKid.translateY', lock=True)\n'locked'", "lock ty")
err = refusal("reset_pose", {"root": "bRoot"})
passed, detail = refused_well(err, "bKid", "translateY", "lock")
check("1j. ...but a locked TRANSLATE refuses it, named", passed, detail)
rz = py("import maya.cmds as cmds\ncmds.getAttr('bKid.rotateZ')", "rz2")
check("1k. ...and the restore was never attempted",
      abs(rz - 30.0) < 1e-4, "bKid.rotateZ = %.3f (30 = untouched)" % rz)

# --------------------------------------------------------------- phase 2
print("\n=== 2. set_camera ===", flush=True)
ok("new_scene", {"confirm": True})
py("""
import maya.cmds as cmds
cam = cmds.camera(name='shot')[0]
cam = cmds.rename(cam, 'shotCam')
cmds.setAttr(cam + '.translate', 0.0, 0.0, 5.0)
rider = cmds.spaceLocator(name='rider')[0]
cmds.setAttr(rider + '.translateY', 9.0)
cmds.parentConstraint(rider, cam, maintainOffset=False)
# A second camera: translate FREE, rotate fed by an aim.
aim = cmds.camera(name='aim')[0]
aim = cmds.rename(aim, 'aimCam')
cmds.setAttr(aim + '.translate', 0.0, 0.0, 7.0)
tgt = cmds.spaceLocator(name='aimTgt')[0]
cmds.setAttr(tgt + '.translateZ', -6.0)
cmds.aimConstraint(tgt, aim)
# A third: transform free, LENS keyed.
lens = cmds.camera(name='lens')[0]
lens = cmds.rename(lens, 'lensCam')
shape = cmds.listRelatives(lens, shapes=True, fullPath=True)[0]
cmds.setKeyframe(shape + '.focalLength', time=1, value=35)
'built'
""", "cameras")

err = refusal("set_camera", {"camera": "shotCam", "position": [1, 2, 3],
                             "set_active": False})
passed, detail = refused_well(err, "shotCam", "translate")
check("2a. set_camera refuses a parent-constrained camera", passed, detail)

before = py("import maya.cmds as cmds\n"
            "cmds.xform('aimCam', query=True, worldSpace=True, "
            "translation=True)", "aim before")
err = refusal("set_camera", {"camera": "aimCam", "position": [1, 2, 3],
                             "look_at": [0, 0, 0], "set_active": False})
passed, detail = refused_well(err, "aimCam", "rotate")
check("2b. set_camera refuses an AIM-constrained camera", passed, detail)

after = py("import maya.cmds as cmds\n"
           "cmds.xform('aimCam', query=True, worldSpace=True, "
           "translation=True)", "aim after")
moved = max(abs(a - b) for a, b in zip(before, after))
check("2c. ...and the free TRANSLATE was not written first (the half-move)",
      moved < 1e-6, "moved by %.4g (%s -> %s)" % (moved, before, after))

err = refusal("set_camera", {"camera": "lensCam", "position": [1, 2, 3],
                             "focal_length": 50.0, "set_active": False})
passed, detail = refused_well(err, "focalLength")
check("2d. set_camera refuses a keyed lens", passed, detail)
hint = (err or {}).get("hint") or ""
check("2d'. ...and does not send a CAMERA to delete_clip (a skeleton tool)",
      "disconnect the animation curve" in hint
      and not hint.startswith("delete_clip"),
      hint[:110])

lens_after = py("import maya.cmds as cmds\n"
                "[cmds.xform('lensCam', query=True, worldSpace=True, "
                "translation=True), cmds.getAttr('lensCamShape.focalLength')]",
                "lens after")
check("2e. ...before writing the free position that preceded it",
      abs(lens_after[0][0]) < 1e-6 and abs(lens_after[1] - 35.0) < 1e-4,
      "translate=%s focal=%.2f" % (lens_after[0], lens_after[1]))

free_cam = ok("set_camera", {"camera": "freeCam", "position": [1, 2, 3],
                             "focal_length": 50.0, "set_active": False})
check("2f. NEGATIVE CONTROL: an unconstrained camera is still placed",
      max(abs(a - b) for a, b in zip(free_cam["position"], [1, 2, 3])) < 1e-4,
      "position = %s" % (free_cam["position"],))

# --------------------------------------------------------------- phase 3
print("\n=== 3. transform, all-or-nothing across names ===", flush=True)
ok("new_scene", {"confirm": True})
py("""
import maya.cmds as cmds
a = cmds.polyCube(name='cubeA')[0]
b = cmds.polyCube(name='cubeB')[0]
cmds.setAttr(b + '.translateY', lock=True)
c = cmds.polyCube(name='cubeC')[0]
drv = cmds.spaceLocator(name='mover')[0]
cmds.setAttr(drv + '.translateX', 4.0)
cmds.parentConstraint(drv, c, maintainOffset=False)
'built'
""", "cubes")

err = refusal("transform", {"names": ["|cubeA", "|cubeB"],
                            "translate": [5.0, 0.0, 0.0]})
passed, detail = refused_well(err, "cubeB", "lock")
check("3a. transform refuses when the SECOND name has a locked plug",
      passed, detail)

pos = py("import maya.cmds as cmds\ncmds.getAttr('cubeA.translate')[0]", "a")
check("3b. ...and the FIRST name never moved (delete_objects' promise)",
      max(abs(v) for v in pos) < 1e-6, "cubeA.translate = %s" % (pos,))

err = refusal("transform", {"names": ["|cubeA", "|cubeC"],
                            "translate": [5.0, 0.0, 0.0]})
passed, detail = refused_well(err, "cubeC", "parentConstraint")
check("3c. transform refuses a constraint-driven object too", passed, detail)

pos = py("import maya.cmds as cmds\ncmds.getAttr('cubeA.translate')[0]", "a2")
check("3d. ...and cubeA is still where it started",
      max(abs(v) for v in pos) < 1e-6, "cubeA.translate = %s" % (pos,))

moved = ok("transform", {"names": ["|cubeA"], "translate": [5.0, 0.0, 0.0]})
check("3e. NEGATIVE CONTROL: a free object still moves",
      abs(moved["objects"][0]["translate"][0] - 5.0) < 1e-4,
      "translate = %s" % (moved["objects"][0]["translate"],))

# --------------------------------------------------------------- phase 4
print("\n=== 4. the render passes name what they could not move ===",
      flush=True)
ok("new_scene", {"confirm": True})
py("""
import maya.cmds as cmds
cmds.polySphere(name='ball')
cmds.setAttr('ball.translateY', 1.0)
floor = cmds.polyCube(name='floor', w=8, h=0.2, d=8)[0]
'built'
""", "subjects")
ok("setup_lighting", {"preset": "three_point"}, timeout_s=240)
rig_light = py("""
import maya.cmds as cmds
rig = [cmds.listRelatives(l, parent=True, fullPath=True)[0]
       for l in cmds.ls(lights=True, long=True)
       if 'mcpLight' in l]
key = sorted(rig)[0]
cmds.setKeyframe(key + '.rotateY', time=1, value=cmds.getAttr(key + '.rotateY'))
[key, cmds.getAttr(key + '.rotateY')]
""", "rig light")
key_name, key_yaw = rig_light[0], rig_light[1]
print("keyed rig light: %s at yaw %.3f" % (key_name, key_yaw), flush=True)

rig_size = py("""
import maya.cmds as cmds
len([l for l in cmds.ls(lights=True, long=True) if 'mcpLight' in l
     and cmds.nodeType(l) != 'aiSkyDomeLight'])
""", "rig size")
out = ok("render_scene", {"angles": ["side"], "renderer": "hw2",
                          "resolution": 256}, timeout_s=600)
named = [w for w in out.get("warnings", []) if "mcpLight" in w]
check("4a. render_scene NAMES the rig light it could not swing",
      bool(named), (named[0][:110] if named else
                    "warnings = %s" % (out.get("warnings"),)))
# The discriminator: the old code reported len(rig) whatever it managed to
# move. With one of the rig's lights keyed, the count is one short now.
check("4a'. ...and relit_lights counts what it SWUNG, not what it found",
      out.get("relit_lights") == rig_size - 1,
      "relit_lights=%s of a %d-light rig" % (out.get("relit_lights"),
                                              rig_size))

yaw_now = py("import maya.cmds as cmds\ncmds.getAttr(%r + '.rotateY')"
             % key_name, "yaw")
# A damage assertion, not a discriminator: the old code's restore put the
# yaw back too (and the curve would have reasserted it regardless). Kept
# because it pins the one thing a caller sees afterwards.
check("4b. the user's keyed light sits where they keyed it afterwards",
      abs(yaw_now - key_yaw) < 1e-4,
      "yaw %.3f -> %.3f" % (key_yaw, yaw_now))

py("""
import maya.cmds as cmds
shape = cmds.listRelatives('floor', shapes=True, fullPath=True)[0]
cmds.setKeyframe(shape + '.visibility', time=1, value=1)
'keyed'
""", "floor vis")
sheet = ok("render_sheet", {"subjects": ["|ball", "|floor"],
                            "renderer": "hw2", "resolution": 256},
           timeout_s=900)
named = [w for w in sheet.get("warnings", []) if "floor" in w]
check("4c. render_sheet NAMES the rival it could not hide",
      bool(named), (named[0][:110] if named else
                    "warnings = %s" % (sheet.get("warnings"),)))

vis = py("""
import maya.cmds as cmds
shape = cmds.listRelatives('floor', shapes=True, fullPath=True)[0]
cmds.getAttr(shape + '.visibility')
""", "floor visible")
# Damage assertion, like 4b: the old path's showHidden restored this too.
# It pins the hide/restore bookkeeping, not the fix.
check("4d. ...and the sheet left the user's keyed visibility alone",
      vis is True, "floorShape.visibility = %s" % vis)

# --------------------------------------------------------------- phase 5
print("\n=== 5. add_corrective still refuses after the refactor ===",
      flush=True)
ok("new_scene", {"confirm": True})
py("""
import maya.cmds as cmds
cmds.select(clear=True)
cmds.joint(name='armA', position=(0, 0, 0))
cmds.joint(name='armB', position=(0, 2, 0))
cmds.setAttr('armB.rotateY', lock=True)
arm = cmds.polySphere(name='arm')[0]
# add_corrective refuses a mesh with no blendShape long before it looks at
# the driver joint, so the shape has to be real for the guard to be reached.
bulge = cmds.duplicate(arm, name='bulge')[0]
cmds.move(0.4, 0, 0, bulge + '.vtx[0:20]', relative=True)
cmds.blendShape(bulge, arm, name='arm_shapes')
cmds.delete(bulge)
'built'
""", "corrective rig")
err = refusal("add_corrective", {"mesh": "arm", "target": "bulge",
                                 "joint": "armB", "rotation": [0, 0, -80]})
passed, _ = refused_well(err, "lock") if err else (False, "")
check("5a. add_corrective refuses a locked driver joint through the "
      "shared guard", passed,
      (err or {}).get("message", "")[:110])

# ------------------------------------------------------------------ report
print("\n=== summary ===", flush=True)
failed = [r for r in RESULTS if not r[1]]
print("%d/%d checks passed" % (len(RESULTS) - len(failed), len(RESULTS)))
for label, _ok, detail in failed:
    print("  FAILED %s - %s" % (label, detail))
raise SystemExit(1 if failed else 0)
