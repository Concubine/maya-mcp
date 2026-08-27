"""#774 probe: can HumanIK characterize/retarget/bake be driven from script?

Run:  E:\\Autodesk\\Maya2027\\bin\\mayapy.exe evals/mocap_probe_774.py
(from the worktree root, PYTHONPATH="src;." so repo code imports)
Facts, not assertions: a surprising value changes Task 3's constants.
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

import maya.standalone  # noqa: E402
maya.standalone.initialize(name="python")
import maya.cmds as cmds  # noqa: E402
import maya.mel as mel  # noqa: E402


def probe(name, value):
    print("PROBE %s: %r" % (name, value))


cmds.file(new=True, force=True)

# --- 1. plugin load ------------------------------------------------------
try:
    cmds.loadPlugin("mayaHIK", quiet=True)
except Exception as exc:  # noqa: BLE001
    probe("hik_plugin_load_error", str(exc))
try:
    probe("hik_plugin_loaded",
          cmds.pluginInfo("mayaHIK", query=True, loaded=True))
except Exception as exc:  # noqa: BLE001
    probe("hik_plugin_loaded_error", str(exc))

try:
    cmds.loadPlugin("mayaHIK.mll", quiet=True)
    probe("hik_plugin_mll_loaded",
          cmds.pluginInfo("mayaHIK.mll", query=True, loaded=True))
except Exception as exc:  # noqa: BLE001
    probe("hik_plugin_mll_load_error", str(exc))

try:
    all_plugins = cmds.pluginInfo(query=True, listPlugins=True) or []
    probe("hik_plugins_listed",
          [p for p in all_plugins if "hik" in p.lower()])
except Exception as exc:  # noqa: BLE001
    probe("hik_plugins_listed_error", str(exc))

try:
    exists_tool = mel.eval('exists "HIKCharacterControlsTool"')
    probe("HIKCharacterControlsTool_exists", exists_tool)
except Exception as exc:  # noqa: BLE001
    probe("HIKCharacterControlsTool_exists_error", str(exc))

# Also: OneClick plugin, sometimes carrying HIK UI/eval support separately.
try:
    cmds.loadPlugin("OneClick", quiet=True)
    probe("oneclick_plugin_loaded",
          cmds.pluginInfo("OneClick", query=True, loaded=True))
except Exception as exc:  # noqa: BLE001
    probe("oneclick_plugin_load_error", str(exc))

# hikDefinitionUtils.mel's canLockCharacterization() gates EVERY lock on
# hikIsCharacterizationToolUICmdPluginLoaded(), which checks THIS plugin -
# not mayaHIK. Miss it and hikCharacterLock silently no-ops (no exception,
# lock just stays 0). Load it explicitly and probe the command it backs.
try:
    cmds.loadPlugin("mayaCharacterization", quiet=True)
    probe("mayacharacterization_plugin_loaded",
          cmds.pluginInfo("mayaCharacterization", query=True, loaded=True))
except Exception as exc:  # noqa: BLE001
    probe("mayacharacterization_plugin_load_error", str(exc))
try:
    probe("characterizationToolUICmd_exists",
          mel.eval('exists "characterizationToolUICmd"'))
except Exception as exc:  # noqa: BLE001
    probe("characterizationToolUICmd_exists_error", str(exc))

# --- 2. MEL existence sweep ------------------------------------------------
CANDIDATES = [
    "hikCreateCharacter", "hikCreateDefinition", "setCharacterObject",
    "hikSetCharacterObject", "hikToggleLockDefinition", "hikCharacterLock",
    "hikSetCurrentCharacter", "hikGetCurrentCharacter", "hikSetCharacterInput",
    "mayaHIKsetCharacterInput", "hikBakeCharacter", "hikNoneCharacter",
    "hikUpdateDefinitionUI", "hikGetNodeCount", "GetHIKNodeName",
    "hikGetNodeIdFromName", "hikIsDefinitionLocked",
]
for name in CANDIDATES:
    try:
        probe("mel_exists_%s" % name, mel.eval('exists "%s"' % name))
    except Exception as exc:  # noqa: BLE001
        probe("mel_exists_%s_error" % name, str(exc))

for node_type in ("HIKCharacterNode", "HIKRetargeterNode", "HIKSolverNode",
                   "HIKState2SK", "HIKState2FK", "HIKCharacterStateClient"):
    try:
        probe("nodetype_exists_%s" % node_type,
              cmds.nodeType(node_type, isTypeName=True))
    except Exception as exc:  # noqa: BLE001
        probe("nodetype_exists_%s_error" % node_type, str(exc))

# Hunt: what HIK-named procs does THIS Maya's script dir actually define?
# (informational - confirms/refutes the brief's guesses against ground truth)
try:
    scripts_dir = os.path.join(
        os.path.dirname(os.path.dirname(cmds.internalVar(userScriptDir=True))),
        "scripts", "others")
except Exception:  # noqa: BLE001
    scripts_dir = None
probe("hik_scripts_dir_hint", scripts_dir)

# --- 3. clipmath.FPS_UNITS -------------------------------------------------
try:
    from maya_plugin.handlers import clipmath
    probe("fps_units", sorted(clipmath.FPS_UNITS))
    probe("fps_units_contains_120", 120 in clipmath.FPS_UNITS)
except Exception as exc:  # noqa: BLE001
    probe("fps_units_error", str(exc))

# --- 4. build TARGET biped via the repo's own create_skeleton handler ------
# Same joints humanoid_live.py builds (JOINT_COUNT = 20), so downstream tasks
# can reuse this exact rig shape.
TARGET_JOINTS = [
    {"name": "pelvis",     "position": [0.0,  1.00, 0.0]},
    {"name": "spine_01",   "position": [0.0,  1.15, 0.0], "parent": "pelvis"},
    {"name": "spine_02",   "position": [0.0,  1.30, 0.0], "parent": "spine_01"},
    {"name": "chest",      "position": [0.0,  1.45, 0.0], "parent": "spine_02"},
    {"name": "neck",       "position": [0.0,  1.60, 0.0], "parent": "chest"},
    {"name": "head",       "position": [0.0,  1.72, 0.0], "parent": "neck"},
    {"name": "L_shoulder", "position": [0.22, 1.50, 0.0], "parent": "chest"},
    {"name": "L_elbow",    "position": [0.45, 1.50, 0.0], "parent": "L_shoulder"},
    {"name": "L_wrist",    "position": [0.68, 1.50, 0.0], "parent": "L_elbow"},
    {"name": "R_shoulder", "position": [-0.22, 1.50, 0.0], "parent": "chest"},
    {"name": "R_elbow",    "position": [-0.45, 1.50, 0.0], "parent": "R_shoulder"},
    {"name": "R_wrist",    "position": [-0.68, 1.50, 0.0], "parent": "R_elbow"},
    {"name": "L_hip",      "position": [0.10, 0.95, 0.0], "parent": "pelvis"},
    {"name": "L_knee",     "position": [0.10, 0.50, 0.0], "parent": "L_hip"},
    {"name": "L_ankle",    "position": [0.10, 0.08, 0.0], "parent": "L_knee"},
    {"name": "L_toe",      "position": [0.10, 0.02, 0.14], "parent": "L_ankle"},
    {"name": "R_hip",      "position": [-0.10, 0.95, 0.0], "parent": "pelvis"},
    {"name": "R_knee",     "position": [-0.10, 0.50, 0.0], "parent": "R_hip"},
    {"name": "R_ankle",    "position": [-0.10, 0.08, 0.0], "parent": "R_knee"},
    {"name": "R_toe",      "position": [-0.10, 0.02, 0.14], "parent": "R_ankle"},
]
target_root = None
target_joint_names = {}
try:
    from maya_plugin.handlers import rigging
    skel = rigging.create_skeleton({"joints": TARGET_JOINTS})
    target_root = skel["root"]
    target_joint_names = {j["name"].split("|")[-1]: j["name"]
                          for j in skel["joints"]}
    probe("target_skeleton_root", target_root)
    probe("target_skeleton_joint_count", len(skel["joints"]))
    probe("target_skeleton_joint_names", sorted(target_joint_names.keys()))
except Exception as exc:  # noqa: BLE001
    probe("target_skeleton_error", str(exc))

# HIK's classic 15-slot map speaks Hips/LeftUpLeg/... names, not this repo's
# pelvis/L_hip/... names. Map target joints onto HIK's vocabulary explicitly.
TARGET_TO_HIK = {
    "pelvis": "Hips", "L_hip": "LeftUpLeg", "L_knee": "LeftLeg",
    "L_ankle": "LeftFoot", "R_hip": "RightUpLeg", "R_knee": "RightLeg",
    "R_ankle": "RightFoot", "spine_01": "Spine", "L_shoulder": "LeftArm",
    "L_elbow": "LeftForeArm", "L_wrist": "LeftHand",
    "R_shoulder": "RightArm", "R_elbow": "RightForeArm",
    "R_wrist": "RightHand", "head": "Head",
}
# Classic HIK slot ids (from the brief; cross-checked against
# hikGetNodeIdFromName below where that command is available).
HIK_SLOT_IDS = {
    "Reference": 0, "Hips": 1, "LeftUpLeg": 2, "LeftLeg": 3, "LeftFoot": 4,
    "RightUpLeg": 5, "RightLeg": 6, "RightFoot": 7, "Spine": 8,
    "LeftArm": 9, "LeftForeArm": 10, "LeftHand": 11,
    "RightArm": 12, "RightForeArm": 13, "RightHand": 14, "Head": 15,
}
for hik_name, expected_id in sorted(HIK_SLOT_IDS.items(),
                                     key=lambda kv: kv[1]):
    try:
        measured = mel.eval('hikGetNodeIdFromName("%s")' % hik_name)
        probe("hik_slot_id_%s" % hik_name,
              {"expected": expected_id, "measured": measured})
    except Exception as exc:  # noqa: BLE001
        probe("hik_slot_id_%s_error" % hik_name, str(exc))

# --- 5. build SOURCE skeleton by hand (a minimal CMU-shaped biped) ---------
SOURCE_JOINTS = [
    ("Hips", None, (0, 1.0, 0)),
    ("Spine", "Hips", (0, 1.3, 0)),
    ("Spine1", "Spine", (0, 1.6, 0)),
    ("Neck", "Spine1", (0, 1.9, 0)),
    ("Head", "Neck", (0, 2.2, 0)),
    ("LHipJoint", "Hips", (0.05, 1.0, 0)),
    ("LeftUpLeg", "LHipJoint", (0.15, 0.9, 0)),
    ("LeftLeg", "LeftUpLeg", (0.15, 0.5, 0)),
    ("LeftFoot", "LeftLeg", (0.15, 0.1, 0)),
    ("RHipJoint", "Hips", (-0.05, 1.0, 0)),
    ("RightUpLeg", "RHipJoint", (-0.15, 0.9, 0)),
    ("RightLeg", "RightUpLeg", (-0.15, 0.5, 0)),
    ("RightFoot", "RightLeg", (-0.15, 0.1, 0)),
    ("LeftShoulder", "Spine1", (0.15, 1.75, 0)),
    ("LeftArm", "LeftShoulder", (0.45, 1.75, 0)),
    ("LeftForeArm", "LeftArm", (0.75, 1.75, 0)),
    ("LeftHand", "LeftForeArm", (1.05, 1.75, 0)),
    ("RightShoulder", "Spine1", (-0.15, 1.75, 0)),
    ("RightArm", "RightShoulder", (-0.45, 1.75, 0)),
    ("RightForeArm", "RightArm", (-0.75, 1.75, 0)),
    ("RightHand", "RightForeArm", (-1.05, 1.75, 0)),
]
source_root = None
try:
    cmds.select(clear=True)
    created = {}
    for name, parent, pos in SOURCE_JOINTS:
        if parent is None:
            cmds.select(clear=True)
        else:
            cmds.select(created[parent], replace=True)
        node = cmds.joint(name=name, position=pos)
        created[name] = node
    source_root = created["Hips"]
    probe("source_skeleton_root", source_root)
    probe("source_skeleton_joint_count", len(created))

    # Animate: Hips.translateX 0->10 over frames 1-30, LeftUpLeg.rotateZ 0->40.
    cmds.setKeyframe(created["Hips"], attribute="translateX", time=1, value=0)
    cmds.setKeyframe(created["Hips"], attribute="translateX", time=30, value=10)
    cmds.setKeyframe(created["LeftUpLeg"], attribute="rotateZ", time=1, value=0)
    cmds.setKeyframe(created["LeftUpLeg"], attribute="rotateZ", time=30, value=40)
    probe("source_skeleton_keyed", True)
except Exception as exc:  # noqa: BLE001
    probe("source_skeleton_error", str(exc))

# Census BEFORE the HIK section starts (per brief step 8: "before the whole
# HIK section vs after deleting the HIK character nodes + source skeleton").
BEFORE_HIK_SECTION = set(cmds.ls(long=True))

# --- 6. THE CORE LOOP: characterize target + source, retarget, measure ----
target_char = None
source_char = None
target_hips_before = None
target_hips_after = None
try:
    if target_root is None:
        raise RuntimeError("no target skeleton; skipping characterization")

    target_char = mel.eval('hikCreateCharacter("probeTarget")')
    probe("target_character_created", target_char)

    assigned = {}
    for target_name, hik_name in TARGET_TO_HIK.items():
        node = target_joint_names.get(target_name)
        slot_id = HIK_SLOT_IDS[hik_name]
        if node is None:
            probe("target_slot_%s_skipped" % hik_name,
                  "no joint named %r on target" % target_name)
            continue
        try:
            mel.eval('setCharacterObject("%s", "%s", %d, 0)'
                      % (node, target_char, slot_id))
            assigned[hik_name] = node
        except Exception as exc:  # noqa: BLE001
            probe("target_slot_%s_error" % hik_name, str(exc))
    probe("target_slots_assigned", sorted(assigned.keys()))

    try:
        mel.eval('hikSetCurrentCharacter("%s")' % target_char)
        probe("target_can_lock_characterization",
              mel.eval('hikIsCharacterizationInValidOrWarningState()'))
        try:
            probe("target_curcharstatus",
                  mel.eval('characterizationToolUICmd -query -curcharstatus'))
        except Exception as exc:  # noqa: BLE001
            probe("target_curcharstatus_error", str(exc))
    except Exception as exc:  # noqa: BLE001
        probe("target_can_lock_error", str(exc))

    try:
        mel.eval('hikCharacterLock("%s", 1, 1)' % target_char)
        locked = mel.eval('hikIsDefinitionLocked("%s")' % target_char)
        probe("target_definition_locked", locked)
    except Exception as exc:  # noqa: BLE001
        probe("target_lock_error", str(exc))

    cmds.currentTime(15, edit=True)
    try:
        target_hips_before = cmds.xform(
            assigned.get("Hips", target_root), query=True,
            worldSpace=True, translation=True)
        probe("target_hips_world_pos_before_input", target_hips_before)
    except Exception as exc:  # noqa: BLE001
        probe("target_hips_before_error", str(exc))

    if source_root is not None:
        source_char = mel.eval('hikCreateCharacter("probeSource")')
        probe("source_character_created", source_char)

        SOURCE_SLOT_NAMES = {
            "Hips": "Hips", "LeftUpLeg": "LeftUpLeg", "LeftLeg": "LeftLeg",
            "LeftFoot": "LeftFoot", "RightUpLeg": "RightUpLeg",
            "RightLeg": "RightLeg", "RightFoot": "RightFoot",
            "Spine": "Spine", "LeftArm": "LeftArm",
            "LeftForeArm": "LeftForeArm", "LeftHand": "LeftHand",
            "RightArm": "RightArm", "RightForeArm": "RightForeArm",
            "RightHand": "RightHand", "Head": "Head",
        }
        src_assigned = {}
        for hik_name, joint_name in SOURCE_SLOT_NAMES.items():
            slot_id = HIK_SLOT_IDS[hik_name]
            try:
                mel.eval('setCharacterObject("%s", "%s", %d, 0)'
                          % (joint_name, source_char, slot_id))
                src_assigned[hik_name] = joint_name
            except Exception as exc:  # noqa: BLE001
                probe("source_slot_%s_error" % hik_name, str(exc))
        probe("source_slots_assigned", sorted(src_assigned.keys()))

        try:
            mel.eval('hikSetCurrentCharacter("%s")' % source_char)
            probe("source_can_lock_characterization",
                  mel.eval('hikIsCharacterizationInValidOrWarningState()'))
        except Exception as exc:  # noqa: BLE001
            probe("source_can_lock_error", str(exc))

        try:
            mel.eval('hikCharacterLock("%s", 1, 1)' % source_char)
            src_locked = mel.eval('hikIsDefinitionLocked("%s")' % source_char)
            probe("source_definition_locked", src_locked)
        except Exception as exc:  # noqa: BLE001
            probe("source_lock_error", str(exc))

        try:
            mel.eval('hikSetCharacterInput("%s", "%s")'
                      % (target_char, source_char))
            probe("hikSetCharacterInput_called", True)
        except Exception as exc:  # noqa: BLE001
            probe("hikSetCharacterInput_error", str(exc))

        # Evaluation nudges (record which one, if any, made it move).
        for nudge in ("none", "dgdirty", "refresh", "currentTime_reassert"):
            try:
                if nudge == "dgdirty":
                    cmds.dgdirty(allPlugs=True)
                elif nudge == "refresh":
                    cmds.refresh(force=True)
                elif nudge == "currentTime_reassert":
                    cmds.currentTime(1, edit=True)
                    cmds.currentTime(15, edit=True, update=True)
                pos = cmds.xform(assigned.get("Hips", target_root),
                                 query=True, worldSpace=True,
                                 translation=True)
                probe("target_hips_world_pos_after_%s" % nudge, pos)
                if target_hips_after is None:
                    target_hips_after = pos
                else:
                    target_hips_after = pos
            except Exception as exc:  # noqa: BLE001
                probe("target_hips_after_%s_error" % nudge, str(exc))

        if target_hips_before is not None and target_hips_after is not None:
            moved = any(abs(a - b) > 1e-4
                        for a, b in zip(target_hips_before, target_hips_after))
            probe("retargeting_moved_target_hips", moved)
        else:
            probe("retargeting_moved_target_hips", "UNKNOWN (missing sample)")
except Exception as exc:  # noqa: BLE001
    probe("core_loop_error", str(exc))

# --- 7. bake ---------------------------------------------------------------
try:
    if target_char is not None:
        try:
            mel.eval('hikBakeCharacter(0)')
            probe("hikBakeCharacter_called", True)
        except Exception as exc:  # noqa: BLE001
            probe("hikBakeCharacter_error", str(exc))
        # Independent of whether the MEL bake ran, also try cmds.bakeResults
        # over the target joints directly - the brief's named fallback.
        try:
            joints_to_bake = list(assigned.values()) if 'assigned' in dir() else []
        except Exception:  # noqa: BLE001
            joints_to_bake = []
        if not joints_to_bake and target_joint_names:
            joints_to_bake = list(target_joint_names.values())
        if joints_to_bake:
            try:
                cmds.bakeResults(joints_to_bake, simulation=True,
                                 time=(1, 30))
                probe("bakeResults_called", True)
            except Exception as exc:  # noqa: BLE001
                probe("bakeResults_error", str(exc))
            counts = {}
            for j in joints_to_bake:
                try:
                    counts[j] = cmds.keyframe(j, query=True,
                                              keyframeCount=True)
                except Exception as exc:  # noqa: BLE001
                    counts[j] = "ERROR: %s" % exc
            probe("target_joint_keyframe_counts", counts)
    else:
        probe("bake_skipped", "no target character")
except Exception as exc:  # noqa: BLE001
    probe("bake_section_error", str(exc))

# --- 8. teardown census -----------------------------------------------------
# Per brief: BEFORE_HIK_SECTION (captured above, right before any HIK
# character existed) vs AFTER explicit deletes. Anything new that SURVIVES
# is Task 3's teardown checklist - hikDeleteCharacter alone may not get it.
try:
    for char in (target_char, source_char):
        if char and cmds.objExists(char):
            try:
                mel.eval('hikDeleteCharacter("%s")' % char)
            except Exception as exc:  # noqa: BLE001
                probe("hikDeleteCharacter_%s_error" % char, str(exc))
                try:
                    cmds.delete(char)
                except Exception:  # noqa: BLE001
                    pass
    if source_root and cmds.objExists(source_root):
        cmds.delete(source_root)
    if target_root and cmds.objExists(target_root):
        cmds.delete(target_root)
    after_teardown = set(cmds.ls(long=True))
    leftover = sorted(after_teardown - BEFORE_HIK_SECTION)
    probe("teardown_leftover_count", len(leftover))
    probe("teardown_leftover_all", leftover)
    leftover_types = {}
    for n in leftover:
        try:
            t = cmds.nodeType(n)
        except Exception:  # noqa: BLE001
            t = "UNKNOWN"
        leftover_types[t] = leftover_types.get(t, 0) + 1
    probe("teardown_leftover_types", leftover_types)
except Exception as exc:  # noqa: BLE001
    probe("teardown_error", str(exc))

probe("done", True)
