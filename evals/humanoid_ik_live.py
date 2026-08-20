"""Phase-3 gate for #671: the #668 humanoid re-posed by IK TARGETS.

Phase 2's FK poses required a measured bend-axis study (humanoid_live's
biped_pose docstring: local X is the twist axis on every vertical bone,
legs pitch about local Y, ankles about local Z - learned across two failed
gate runs). This gate re-poses the same humanoid from world-space targets
only, and measures that the knowledge cost is gone:

    1  build + bind + craft the SAME humanoid (constants imported from
       humanoid_live; that file and its 45/45 baseline are untouched)
    2  crouch + extend: FK first (the phase-2 map), then the same pose from
       TARGETS - 1 pose_skeleton (spine/ankle detail) + 4 pose_ik (limbs);
       residual < 5 mm, joints within 1.5 cm of FK, same tearing ceilings
    3  reach: an asymmetric pose NO FK map exists for - 2 pose_ik calls
    4  purity: zero ikHandle/ikEffector/constraint/locator nodes after
       every call; rotations re-applied via pose_skeleton reproduce the
       IK-achieved positions (the bake IS the phase-1 currency)
    5  honesty: an unreachable target reports the geometric miss and warns
    6  judged renders per posed state + baseline.json

DESTRUCTIVE: calls new_scene. Port 9878, the agent-launched Maya, per the
two-Maya policy - never point this at the user's 9877.

Run:  uv run python evals/humanoid_ik_live.py
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

from live_call import call, structured_result  # noqa: E402
from humanoid_live import (  # noqa: E402 - DATA only, that module runs nothing on import
    EDGE_PROBE, EDGE_STRETCH_BACKSTOP, EDGE_STRETCH_MAX, JOINT_COUNT, JOINTS,
    MESH, PARTS, PIECES, TEAR_GROWTH_MIN, biped_pose,
)

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
OUT_DIR = os.path.join(_HERE, "humanoid_ik_live")
POSES_PATH = os.path.join(_HERE, "golem_delivery", "poses.json")

RESIDUAL_MAX = 0.005          # 5 mm on a 2 m figure
FK_MATCH_MAX = 0.015          # per-joint world-position agreement with FK
CURRENCY_MAX = 0.001          # rotations re-applied must land within 1 mm
LIMBS = {                     # joint -> (chain end, pole joint) per limb
    "L_ankle": "L_knee", "R_ankle": "R_knee",
    "L_wrist": "L_elbow", "R_wrist": "R_elbow",
}
# The pole must sit OFF the chain, on the side the joint should fold
# toward; the FK pose's own mid-joint position IS that point.
FK_DETAIL = ("spine_01", "spine_02", "chest", "L_ankle", "R_ankle")

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
        print("FAIL: %s: %s" % (command, json.dumps(response.get("error"))[:600]))
        sys.exit(1)
    return response.get("result") or {}


def py(code, what, timeout_s=300.0):
    return structured_result(ok("execute_python", {"code": code}, timeout_s), what)


def out(name):
    return os.path.join(OUT_DIR, name)


def edge_probe(store, what):
    return py(EDGE_PROBE % {"mesh": "|" + MESH, "store": repr(bool(store)),
                            "grow": TEAR_GROWTH_MIN}, what)


def render(tag):
    params = {"angles": ["front", "side"], "target": ["|" + MESH],
              "resolution": 640, "samples": 3, "renderer": "arnold"}
    response = send("render_scene", params, timeout_s=900.0)
    if response.get("status") != "ok":
        params["renderer"] = "hw2"
        response = send("render_scene", params, timeout_s=900.0)
    if response.get("status") != "ok":
        check("render %s" % tag, False, json.dumps(response.get("error"))[:200])
        return
    for image in response["result"]["images"]:
        with open(out("ik_%s_%s.png" % (tag, image["angle"])), "wb") as fh:
            fh.write(base64.b64decode(image["png_b64"]))
    check("render %s" % tag, True,
          "renderer=%s" % response["result"].get("renderer"))


def no_ik_state(tag):
    left = py(
        "import maya.cmds as cmds\n"
        "{'handles': cmds.ls(type='ikHandle') or [],\n"
        " 'effectors': cmds.ls(type='ikEffector') or [],\n"
        " 'constraints': cmds.ls(type='poleVectorConstraint') or [],\n"
        " 'locators': cmds.ls('*_pole*', type='transform') or []}",
        "%s: IK leftovers" % tag)
    check("%s: no IK state survives" % tag,
          not any(left.values()), json.dumps(left))


def joint_positions(root):
    posed = ok("pose_skeleton", {"root": root, "rotations": {"pelvis": [0, 0, 0]}})
    return {j["name"].split("|")[-1]: j["world_position"]
            for j in posed["joints"]}


def edge_checks(tag, at_bind):
    probe = edge_probe(store=False, what="%s edge probe" % tag)
    check("%s: no visible tear past %.1fx" % (tag, EDGE_STRETCH_MAX),
          probe["max_visible_ratio"] <= EDGE_STRETCH_MAX,
          "visible=%.3f unfiltered=%.3f"
          % (probe["max_visible_ratio"], probe["max_edge_ratio"]))
    check("%s: under the %.1fx backstop" % (tag, EDGE_STRETCH_BACKSTOP),
          probe["max_edge_ratio"] <= EDGE_STRETCH_BACKSTOP)
    check("%s: topology unchanged" % tag,
          probe["shells"] == PIECES and probe["edges"] == at_bind["edges"])
    return probe


def dist(a, b):
    return sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5


def main():
    if PORT == 9877:
        print("refusing to run on 9877: this eval discards the open scene "
              "(two-Maya policy). Launch a disposable Maya on 9878.")
        return 2

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(POSES_PATH) as fh:
        golem_poses = json.load(fh)
    identity = py("import os\n{'pid': os.getpid()}", "identity")
    print("Maya on %d: pid %s, writing to %s\n" % (PORT, identity["pid"], OUT_DIR))

    # ---- 1. the phase-2 humanoid, verbatim ------------------------------
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
       "scale=True, normal=0, preserveNormals=True)\nTrue" % ("|" + MESH),
       "freeze the combined mesh")
    skeleton = ok("create_skeleton", {"joints": JOINTS})
    check("skeleton built all %d joints" % JOINT_COUNT,
          len(skeleton["joints"]) == JOINT_COUNT)
    root = skeleton["root"]
    bind = ok("bind_skin", {"mesh": "|" + MESH, "root": root}, timeout_s=600.0)
    check("bind leaves no vertex unowned", bind["unweighted_vertices"] == 0)
    at_bind = edge_probe(store=True, what="bind edge baseline")

    # the phase-2 craft pass, verbatim (see humanoid_live.py for the
    # measured rationale of every number)
    torso_faces = py(
        "import maya.cmds as cmds\n"
        "_f = cmds.polySelect(%r, extendToShell=0, noSelection=True)\n"
        "{'faces': [int(i) for i in _f]}" % ("|" + MESH), "torso shell faces")
    ok("set_region_weights", {"mesh": "|" + MESH, "joint": "chest",
                              "faces": torso_faces["faces"], "weight": 0.85})
    ok("set_region_weights", {"mesh": "|" + MESH, "joint": "L_shoulder",
                              "within_radius_of": [0.32, 1.50, 0.0],
                              "radius": 0.11, "weight": 0.9,
                              "falloff": "linear"})
    ok("mirror_weights", {"mesh": "|" + MESH, "axis": "x"})
    ok("smooth_weights", {"mesh": "|" + MESH,
                          "joints": ["L_hip", "R_hip", "L_shoulder",
                                     "R_shoulder"], "iterations": 2})
    report = ok("weight_report", {"mesh": "|" + MESH})
    check("crafted weights are clean",
          report["unweighted_vertices"] == 0
          and report["max_influences_exceeded"] == 0)
    ok("setup_lighting", {"preset": "three_point"})

    baseline = {"poses": {}, "purity": {}, "honesty": {}}

    # ---- 2. equivalence: crouch + extend, FK then TARGETS ----------------
    for pose_name in ("crouch", "extend"):
        fk_map = biped_pose(golem_poses[pose_name]["joints_deg"])
        fk = ok("pose_skeleton", {"root": root, "rotations": fk_map})
        fk_joints = {j["name"].split("|")[-1]: j["world_position"]
                     for j in fk["joints"]}
        fk_probe = edge_checks("%s FK" % pose_name, at_bind)
        render("%s_fk" % pose_name)
        ok("reset_pose", {"root": root})

        # target-first: spine/ankle FK detail, then four limbs by TARGET
        detail = {j: fk_map[j] for j in FK_DETAIL if j in fk_map}
        calls = 0
        ok("pose_skeleton", {"root": root, "rotations": detail})
        calls += 1
        merged = dict(detail)
        residuals = {}
        for end_joint, mid_joint in LIMBS.items():
            solved = ok("pose_ik", {
                "root": root, "joint": end_joint,
                "target": fk_joints[end_joint],
                "pole": fk_joints[mid_joint]})
            calls += 1
            residuals[end_joint] = solved["residual"]
            merged.update(solved["rotations"])
            check("%s IK: %s residual < %.0f mm"
                  % (pose_name, end_joint, RESIDUAL_MAX * 1000),
                  solved["residual"] < RESIDUAL_MAX,
                  "residual=%.4f warnings=%s"
                  % (solved["residual"], solved["warnings"]))
        no_ik_state("%s IK" % pose_name)

        ik_joints = joint_positions(root)
        worst = max((dist(ik_joints[j], fk_joints[j]), j) for j in fk_joints)
        check("%s IK: joints match FK within %.1f cm"
              % (pose_name, FK_MATCH_MAX * 100), worst[0] < FK_MATCH_MAX,
              "worst=%.4f at %s" % worst)
        ik_probe = edge_checks("%s IK" % pose_name, at_bind)
        render("%s_ik" % pose_name)
        baseline["poses"][pose_name] = {
            "posing_calls_ik": calls, "residuals": residuals,
            "fk_worst_match": worst[0],
            "fk_max_visible_ratio": fk_probe["max_visible_ratio"],
            "ik_max_visible_ratio": ik_probe["max_visible_ratio"],
            "merged_rotations": merged,
        }
        ok("reset_pose", {"root": root})

    # ---- 3. reach: target-first authoring, no FK map exists --------------
    # R_wrist target corrected from the brief's [0.15, 1.05, 0.35]: measured
    # against this rig, R_shoulder=[-0.22,1.5,0], R_elbow=[-0.45,1.5,0],
    # R_wrist=[-0.68,1.5,0] give a max reach of 0.46 m (upper arm 0.23 +
    # forearm 0.23), but that literal target sits 0.6796 m from R_shoulder -
    # 0.22 m (47%) past the chain's physical reach, which is exactly the
    # 0.2196 residual pose_ik reported (matching the deliberate unreachable-
    # target case in step 5, confirming the handler's math, not this data,
    # was the mismatch). [0.0, 1.20, 0.22] sits 0.4322 m from R_shoulder
    # (within the 0.46 m budget) and measured residual ~2e-9 m - same
    # front-low-across-the-body read, now actually reachable.
    reach_targets = {
        "R_wrist": {"target": [0.0, 1.20, 0.22], "pole": [-0.5, 1.35, 0.25]},
        "L_ankle": {"target": [0.18, 0.30, 0.30], "pole": [0.22, 0.65, 0.55]},
    }
    merged = {}
    residuals = {}
    achieved = {}
    for end_joint, spec in reach_targets.items():
        solved = ok("pose_ik", {"root": root, "joint": end_joint,
                                "target": spec["target"],
                                "pole": spec["pole"]})
        residuals[end_joint] = solved["residual"]
        achieved[end_joint] = solved["achieved_position"]
        merged.update(solved["rotations"])
        check("reach: %s residual < %.0f mm"
              % (end_joint, RESIDUAL_MAX * 1000),
              solved["residual"] < RESIDUAL_MAX,
              "residual=%.4f" % solved["residual"])
    no_ik_state("reach")
    edge_checks("reach", at_bind)
    render("reach")
    baseline["poses"]["reach"] = {"posing_calls_ik": 2,
                                  "residuals": residuals,
                                  "merged_rotations": merged}

    # ---- 4. the bake IS the phase-1 currency ------------------------------
    ok("reset_pose", {"root": root})
    ok("pose_skeleton", {"root": root, "rotations": merged})
    replayed = joint_positions(root)
    for end_joint in reach_targets:
        err = dist(replayed[end_joint], achieved[end_joint])
        check("currency: %s replays within %.0f mm"
              % (end_joint, CURRENCY_MAX * 1000), err < CURRENCY_MAX,
              "err=%.5f" % err)
    baseline["purity"]["currency_max_err"] = max(
        dist(replayed[j], achieved[j]) for j in reach_targets)
    ok("reset_pose", {"root": root})

    # ---- 5. honesty: an unreachable target is a number --------------------
    miss = ok("pose_ik", {"root": root, "joint": "R_wrist",
                          "target": [-3.0, 1.5, 0.0], "pole": [-0.5, 1.2, 0.5]})
    check("honesty: unreachable target reports a residual > 2",
          miss["residual"] > 2.0, "residual=%.3f" % miss["residual"])
    check("honesty: the reach warning fired",
          any("reaches only" in w for w in miss["warnings"]),
          "; ".join(miss["warnings"]))
    baseline["honesty"] = {"residual": miss["residual"],
                           "warnings": miss["warnings"]}
    ok("reset_pose", {"root": root})
    final = edge_probe(store=False, what="final reset probe")
    check("final reset returns the mesh to bind",
          final["max_edge_ratio"] <= 1.0 + 1e-6,
          "max_edge_ratio=%.6f" % final["max_edge_ratio"])

    with open(out("baseline.json"), "w") as fh:
        json.dump(baseline, fh, indent=2, sort_keys=True)

    print("\n" + "=" * 72)
    print("JUDGE: every *_ik render must read as the SAME pose as its *_fk")
    print("twin, and 'reach' as a plausible asymmetric reach - one continuous")
    print("body, no candy-wrapper pinch, no tearing. Renders: %s" % OUT_DIR)
    print("=" * 72 + "\n")

    failed = [label for passed, label in CHECKS if not passed]
    print("%d/%d checks passed" % (len(CHECKS) - len(failed), len(CHECKS)))
    for label in failed:
        print("  FAILED: %s" % label)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
