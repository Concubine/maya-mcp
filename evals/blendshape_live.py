"""Phase-5 gate for #691: blend shapes on the #668 humanoid.

The user chose BOTH target kinds (2026-08-20):

    1  brow_raise    - facial expression, judged front-on at 0 / 0.5 / 1
    2  L_elbow_bulge - muscle corrective ON THE FOREARM, judged AT a
       90-degree elbow, with the measured front-of-chain proof: the
       displaced-vertex centroid rides the POSED forearm, not the bind
       location. (A delta centred on the elbow pivot could not tell the
       deformation orders apart, which is why the bulge sits at x=0.55.)

Measured checks (this script) + judged renders (the acceptance):
    build humanoid + skeleton + bind (no craft pass: this gate judges
    SHAPES; #668's gate owns weight craft) -> author two targets with
    duplicate+sculpt -> create_blendshape (consumed, deltas measured) ->
    monotonic displacement sweep 0/0.5/1 -> corrective at the posed elbow
    -> reset both currencies -> export include_skins + shapes, byte-gated.

DESTRUCTIVE: calls new_scene. Port 9878, the agent-launched Maya, per the
two-Maya policy - never point this at the user's 9877.

Run:  uv run python evals/blendshape_live.py
Exit: 0 pass, 1 fail, 2 no connection.
"""

from __future__ import annotations

import base64
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from humanoid_live import JOINTS, MESH, PARTS  # noqa: E402
from live_call import call, structured_result  # noqa: E402
from maya_plugin.handlers import fbxbytes  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
OUT_DIR = os.path.join(_HERE, "blendshape_live")
JOINT_COUNT = 20

# Sculpt literals, derived from the humanoid's authored geometry (the PARTS
# table): the head sphere is centred (0, 1.74, 0) with scale (.20, .26,
# .20), so its brow front sits near (0, 1.80, 0.15); the L arm cylinder
# runs x 0.14..0.70 at y 1.50, so the forearm midpoint is (0.55, 1.50, 0).
# MEASURED divergence from the brief literal (2026-08-20): at the gate's
# fixed full-body 640px framing the head spans ~60px, so the brief's [0, .04,
# .03] delta (a ~6.6px shift) produced a max pixel diff of 39/255 confined to
# a 28x26px patch - real but visually unreadable (see task-7-report.md). Not
# a handler defect: create_blendshape/set_blendshape_weights measured the
# sculpt correctly (deltas/sweep numbers were exactly as authored). Widened
# to make the rise legibly visible against this camera/lighting; still a
# soft-falloff push, still > the 0.01 wiring-delta floor by a wide margin.
BROW_CENTER = [0.0, 1.80, 0.15]
BROW_RADIUS = 0.16
BROW_DELTA = [0.0, 0.065, 0.05]
BULGE_CENTER = [0.55, 1.50, 0.0]
BULGE_RADIUS = 0.12
BULGE_AMOUNT = 0.04

CHECKS = []


def check(label, passed, detail=""):
    CHECKS.append((bool(passed), label))
    print("%s %s%s" % ("PASS" if passed else "FAIL", label,
                       ("  [%s]" % detail) if detail else ""))
    return bool(passed)


def send(command, params, timeout_s=300.0):
    try:
        return call(command, params, timeout_s=timeout_s, port=PORT)
    except (ConnectionRefusedError, OSError) as exc:
        print("could not reach a Maya plugin on %s: %s" % (PORT, exc))
        sys.exit(2)


def ok(command, params, timeout_s=300.0):
    response = send(command, params, timeout_s)
    if response.get("status") != "ok":
        print("FAIL: %s: %s" % (command,
                                json.dumps(response.get("error"))[:600]))
        sys.exit(1)
    return response.get("result") or {}


def py(code, what, timeout_s=300.0):
    return structured_result(ok("execute_python", {"code": code},
                                timeout_s), what)


def out(name):
    return os.path.join(OUT_DIR, name)


# Stores the current vertices as the NEUTRAL baseline on the first call;
# afterwards reports max displacement vs that baseline and the centroid of
# every vertex that moved more than a millimetre - the front-of-chain
# evidence.
VERT_PROBE = """
import maya.cmds as cmds
_flat = cmds.xform(%(mesh)r + '.vtx[*]', query=True, worldSpace=True,
                   translation=True)
if %(store)s:
    BS_NEUTRAL = list(_flat)
_worst = 0.0
_cx = _cy = _cz = 0.0
_n = 0
for _i in range(0, len(_flat), 3):
    _dx = _flat[_i] - BS_NEUTRAL[_i]
    _dy = _flat[_i + 1] - BS_NEUTRAL[_i + 1]
    _dz = _flat[_i + 2] - BS_NEUTRAL[_i + 2]
    _d = (_dx * _dx + _dy * _dy + _dz * _dz) ** 0.5
    if _d > _worst:
        _worst = _d
    if _d > 1e-3:
        _cx += _flat[_i]; _cy += _flat[_i + 1]; _cz += _flat[_i + 2]
        _n += 1
{'max_disp': round(_worst, 6),
 'moved': _n,
 'centroid': ([round(_cx / _n, 4), round(_cy / _n, 4),
               round(_cz / _n, 4)] if _n else None)}
"""


def probe(store, what):
    return py(VERT_PROBE % {"mesh": "|" + MESH, "store": repr(bool(store))},
              what)


def render(tag, angles=("front",)):
    params = {"angles": list(angles), "target": ["|" + MESH],
              "resolution": 640, "samples": 3, "renderer": "arnold"}
    response = send("render_scene", params, timeout_s=900.0)
    if response.get("status") != "ok":
        params["renderer"] = "hw2"
        response = send("render_scene", params, timeout_s=900.0)
    if response.get("status") != "ok":
        check("render %s" % tag, False,
              json.dumps(response.get("error"))[:200])
        return
    for image in response["result"]["images"]:
        path = out("humanoid_%s_%s.png" % (tag, image["angle"]))
        with open(path, "wb") as fh:
            fh.write(base64.b64decode(image["png_b64"]))
    check("render %s" % tag, True,
          "renderer=%s" % response["result"].get("renderer"))


def main():
    if PORT == 9877:
        print("refusing to run on 9877: this eval discards the open scene "
              "(two-Maya policy). Launch a disposable Maya on 9878.")
        return 2

    os.makedirs(OUT_DIR, exist_ok=True)
    identity = py("import os\n{'pid': os.getpid()}", "identity")
    print("Maya on %d: pid %s, writing to %s\n"
          % (PORT, identity["pid"], OUT_DIR))

    # ---- 1. the humanoid, bound (no craft pass: #668's gate owns craft)
    ok("new_scene", {"confirm": True})
    for kind, name, divisions, scale, translate, rotate in PARTS:
        params = {"kind": kind, "name": name, "divisions": divisions,
                  "scale": scale, "translate": translate}
        if rotate:
            params["rotate"] = rotate
        ok("create_primitive", params)
    ok("combine", {"names": [p[1] for p in PARTS], "name": MESH})
    py("import maya.cmds as cmds\n"
       "cmds.makeIdentity(%r, apply=True, translate=False, rotate=True, "
       "scale=True, normal=0, preserveNormals=True)\nTrue"
       % ("|" + MESH), "freeze the combined mesh")
    skeleton = ok("create_skeleton", {"joints": JOINTS})
    root = skeleton["root"]
    bind = ok("bind_skin", {"mesh": "|" + MESH, "root": root},
              timeout_s=600.0)
    check("the bind leaves NO vertex unowned",
          bind["unweighted_vertices"] == 0,
          "unweighted=%d" % bind["unweighted_vertices"])

    # ---- 2. author the two targets: duplicate + sculpt, the ordinary loop
    ok("duplicate", {"name": "|" + MESH, "new_name": "humanoid_brow"})
    ok("sculpt_ops", {"mesh": "|humanoid_brow", "ops": [
        {"op": "soft_move", "center": BROW_CENTER, "radius": BROW_RADIUS,
         "delta": BROW_DELTA, "falloff": "smooth"}]})
    ok("duplicate", {"name": "|" + MESH, "new_name": "humanoid_elbow"})
    ok("sculpt_ops", {"mesh": "|humanoid_elbow", "ops": [
        {"op": "inflate_region", "center": BULGE_CENTER,
         "radius": BULGE_RADIUS, "amount": BULGE_AMOUNT,
         "falloff": "smooth"}]})

    wired = ok("create_blendshape", {"mesh": "|" + MESH, "targets": [
        {"name": "brow_raise", "target_mesh": "|humanoid_brow"},
        {"name": "L_elbow_bulge", "target_mesh": "|humanoid_elbow"}]})
    deltas = {t["name"]: t["max_delta"] for t in wired["targets"]}
    check("both targets wired with real measured deltas",
          deltas.get("brow_raise", 0) > 0.01
          and deltas.get("L_elbow_bulge", 0) > 0.01,
          json.dumps(deltas))
    consumed = py(
        "import maya.cmds as cmds\n"
        "{'brow': cmds.objExists('humanoid_brow'),"
        " 'elbow': cmds.objExists('humanoid_elbow')}", "consumption")
    check("the target meshes were consumed",
          not consumed["brow"] and not consumed["elbow"],
          json.dumps(consumed))

    # ---- 3. expression sweep 0 / 0.5 / 1: monotonic, rendered, judged
    ok("setup_lighting", {"preset": "three_point"})
    probe(store=True, what="neutral baseline")
    render("brow_0")
    sweep = {}
    for weight in (0.5, 1.0):
        ok("set_blendshape_weights",
           {"mesh": "|" + MESH, "weights": {"brow_raise": weight}})
        measured = probe(store=False, what="brow at %.1f" % weight)
        sweep[weight] = measured["max_disp"]
        render("brow_%s" % str(weight).replace(".", "_"))
    check("displacement is strictly monotonic across 0 / 0.5 / 1",
          0.0 < sweep[0.5] < sweep[1.0],
          "0.5 -> %.4f, 1.0 -> %.4f" % (sweep[0.5], sweep[1.0]))
    check("weight 1 reproduces the wiring-time delta",
          abs(sweep[1.0] - deltas["brow_raise"]) < 1e-3,
          "sweep=%.4f wired=%.4f" % (sweep[1.0], deltas["brow_raise"]))
    ok("set_blendshape_weights",
       {"mesh": "|" + MESH, "weights": {"brow_raise": 0.0}})
    back = probe(store=False, what="after weight reset")
    check("all-zero weights IS the reset",
          back["max_disp"] < 1e-6, "residual=%.3g" % back["max_disp"])

    # ---- 4. the corrective AT a posed elbow: front-of-chain, seen and measured
    posed = ok("pose_skeleton", {"root": root,
                                 "rotations": {"L_elbow": [0, 0, 90]}})
    joints_now = {j["name"].split("|")[-1]: j["world_position"]
                  for j in posed["joints"]}
    forearm_mid = [(a + b) / 2.0 for a, b in
                   zip(joints_now["L_elbow"], joints_now["L_wrist"])]
    probe(store=True, what="posed-elbow baseline")
    render("elbow_posed_w0")
    ok("set_blendshape_weights",
       {"mesh": "|" + MESH, "weights": {"L_elbow_bulge": 1.0}})
    at_pose = probe(store=False, what="corrective at the posed elbow")
    render("elbow_posed_w1")
    check("the corrective moves the mesh at the pose",
          at_pose["max_disp"] > 0.01, "max_disp=%.4f" % at_pose["max_disp"])

    def dist(a, b):
        return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5

    centroid = at_pose["centroid"]
    if centroid is None:
        check("front-of-chain: the bulge rides the POSED forearm", False,
              "centroid=None")
    else:
        bind_site = dist(centroid, BULGE_CENTER)
        posed_site = dist(centroid, forearm_mid)
        check("front-of-chain: the bulge rides the POSED forearm",
              posed_site < bind_site,
              "centroid=%s d(posed)=%.3f d(bind)=%.3f"
              % (centroid, posed_site, bind_site))

    # ---- 5. reset BOTH currencies, then export skins + shapes together
    ok("set_blendshape_weights",
       {"mesh": "|" + MESH, "weights": {"L_elbow_bulge": 0.0}})
    ok("reset_pose", {"root": root})

    fbx = out("humanoid_shaped.fbx")
    if os.path.exists(fbx):
        os.unlink(fbx)
    result = ok("export_fbx", {"path": fbx.replace("\\", "/"),
                               "metres_per_unit": 1.0,
                               "include_skins": True}, timeout_s=600.0)
    shapes = result["shapes"]
    print("  shapes: %s" % json.dumps(shapes))
    check("the file carries both channels by their authored names",
          shapes is not None
          and [s["name"] for s in shapes["shapes"]]
          == ["L_elbow_bulge", "brow_raise"],
          json.dumps(shapes))
    check("every shape carries a self-consistent, non-empty delta payload",
          all(s["points"] > 0 and s["indexes"] == s["points"]
              for s in shapes["shapes"]))
    check("skins survived alongside shapes",
          result["skin"]["deformers"] == 1
          and result["skin"]["clusters"] == JOINT_COUNT
          and result["skin"]["unweighted_file_vertices"] == 0,
          json.dumps(result["skin"]))
    facts = fbxbytes.read_fbx(fbx)
    check("an independent byte read agrees with the tool",
          fbxbytes.shape_facts(facts) == shapes)
    check("shape geometries do not inflate mesh facts",
          result["mesh_count"] == 1, "mesh_count=%d" % result["mesh_count"])
    limbs = [n for n in facts.nodes if n.kind == "LimbNode"]
    check("the bytes still carry %d LimbNode joints" % JOINT_COUNT,
          len(limbs) == JOINT_COUNT, "LimbNodes=%d" % len(limbs))
    check("the file declares metres",
          facts.unit_scale_factor == fbxbytes.DECLARES_METRES)

    with open(out("baseline.json"), "w") as fh:
        json.dump({
            "fbx": "humanoid_shaped.fbx",
            "bytes": result["bytes"],
            "targets": deltas,
            "sweep": {str(k): v for k, v in sweep.items()},
            "corrective_at_pose": {
                "max_disp": at_pose["max_disp"],
                "centroid": at_pose["centroid"],
                "forearm_mid": [round(v, 4) for v in forearm_mid]},
            "shapes": shapes,
            "skin": result["skin"],
        }, fh, indent=2, sort_keys=True)
    print("  baseline: %s" % out("baseline.json"))

    print("\n" + "=" * 72)
    print("JUDGE the renders in %s:" % OUT_DIR)
    print("  brow_0 / brow_0_5 / brow_1: the brow must visibly, smoothly")
    print("  rise - a dent, a spike, or no visible change at 1.0 is a FAIL")
    print("  even with every number green.")
    print("  elbow_posed_w0 vs elbow_posed_w1: the bulge must appear ON the")
    print("  BENT forearm, oriented with it - a bulge floating at the bind")
    print("  position is the deformation-order failure this gate exists")
    print("  to catch.")
    print("=" * 72 + "\n")

    failed = [label for passed, label in CHECKS if not passed]
    print("\n%d/%d passed" % (len(CHECKS) - len(failed), len(CHECKS)))
    for label in failed:
        print("  FAILED: %s" % label)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
