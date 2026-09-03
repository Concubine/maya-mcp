"""retarget_clip: a mocap file in, a normal phase-6 clip out (#774).

The honest split this handler exists to make: motion QUALITY comes from the
capture (a real actor, a real mocap rig), not from anything authored here -
`author_clip`'s hand-keyed poses are a different tool for a different job.
This handler's only responsibility is the mechanical, checkable part: get a
`.bvh`/`.fbx` file's motion onto a `create_skeleton` biped without breaking
it, self-measure the result (`measure_clip`, #773), and leave nothing behind
- no HIK state, no scratch skeleton, no partial scene mutation on a refused
call. Once baked, the clip is indistinguishable from one `author_clip`
produced: `preview_clip`/`measure_clip`/`delete_clip`/multi-take
`export_fbx` all read it unchanged (`clip.register_clip`, extracted for
exactly this reuse).

Retargeting itself is HumanIK's job (Route A), characterized on BOTH ends
from FIXED joint-name tables (`mocapmath.CMU_HIK_MAP`/`SKELETON_HIK_MAP`) and
torn down completely inside this one call - the #768 "construction curves"
discipline applied to rig/plugin STATE instead of scene geometry. A direct
matrix-math fallback (Route B) was pre-authorized in case HIK proved
unscriptable; Task 1's probe (`evals/mocap_probe_774.py`) confirmed Route A
works end to end in mayapy standalone, so Route B is not implemented here -
see the task-3 report for that scope decision.

Measured facts this module's constants and call sequence are built from -
`evals/mocap_probe_774.py`, `.superpowers/sdd/2026-08-27-774-mocap-retarget/
task-1-report.md`:

  - `mayaHIK` ALONE silently fails to lock: `hikCharacterLock` no-ops with no
    exception and `hikIsDefinitionLocked` stays 0, unless `mayaCharacterization`
    is ALSO loaded first (it backs `characterizationToolUICmd`, which the lock
    validation path calls through `hikIsCharacterizationInValidOrWarningState`).
    Both plugins are loaded, always, before any `hikCreateCharacter` call, and
    every lock is VERIFIED via `hikIsDefinitionLocked` - never trusted just
    because `hikCharacterLock` did not raise.
  - `hikBakeCharacter` THROWS in mayapy/standalone (`doBakeSimulationArgList.mel`
    calls `generateAllUvTilePreviews`, sourced only in a full interactive Maya
    UI session). `cmds.bakeResults` on the characterized target joints is the
    measured-equivalent substitute (270 keys/joint on the probe's test range,
    matching the source's own keyed span).
  - Retargeting evaluates the instant `hikSetCharacterInput` runs - no
    `dgdirty`/`refresh`/currentTime nudge needed (measured identical readback
    across all three on the probe).
  - Teardown: `hikDeleteCharacter` per character, called for BOTH characters
    before anything else is torn down, measured 0 leftover HIK-typed nodes.
    This module additionally deletes the source's namespace and then VERIFIES
    no `_HIK_NODE_TYPES` node survives, rather than trusting the two
    `hikDeleteCharacter` calls silently.
"""

from __future__ import annotations

import math
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..dispatcher import HandlerError, refuse_inert, require_known_keys
from . import clip, clipmath, mocapmath, naming, rigging, session, units

RETARGET_CLIP_KEYS = ("file", "root", "clip", "start", "end", "fps")
RETARGET_CLIP_SYNONYMS = {
    "path": "file", "bvh": "file", "name": "clip", "take": "clip",
    "target": "root", "skeleton": "root",
}

# --- Measured by evals/mocap_probe_774.py (#774 Task 1) - ONE place; if a
# future probe run prints different names/ids, fix them HERE. -------------
_HIK_PLUGIN = "mayaHIK"
_HIK_CHARACTERIZATION_PLUGIN = "mayaCharacterization"
# The 15 classic HIK slot ids - measured via hikGetNodeIdFromName, matching
# hikDefinitionOperations.mel's own table exactly (Reference=0 is not a
# required slot and is not needed here).
_HIK_SLOT_IDS = {
    "Hips": 1, "LeftUpLeg": 2, "LeftLeg": 3, "LeftFoot": 4,
    "RightUpLeg": 5, "RightLeg": 6, "RightFoot": 7, "Spine": 8,
    "LeftArm": 9, "LeftForeArm": 10, "LeftHand": 11,
    "RightArm": 12, "RightForeArm": 13, "RightHand": 14, "Head": 15,
}
# Every node TYPE hikCreateCharacter/setCharacterObject/lock/hikSetCharacterInput
# were measured to create, across both characters plus the one shared
# retargeter - the teardown verification sweep below checks for all of them.
# NOTE: the MEL echo during hikDeleteCharacter names the node "HIKproperties1"/
# "2", but that is the auto-generated NODE NAME, not its `cmds.nodeType()` -
# `cmds.ls(type="HIKproperties")` warns "Unknown object type" and silently
# matches nothing (a #764-class quiet-failure trap: the query looks like it
# ran, and never did). Verified live (Task 3 smoke, mayapy): the real type is
# `HIKProperty2State` - `cmds.nodeType("HIKproperties1")` on a freshly
# created character returned that string, so this is what the leftover
# sweep actually queries.
_HIK_NODE_TYPES = ("HIKCharacterNode", "HIKProperty2State", "HIKSolverNode",
                    "HIKState2SK", "HIKRetargeterNode", "HIKState2FK",
                    "HIKCharacterStateClient")
# --------------------------------------------------------------------------

# Maya rotateOrder enum values, by the 3-letter application order (first
# axis listed rotates first) - BVH's CHANNELS line lists rotation channels
# in that same "applied first" order, so the string built from a joint's
# channel list is a direct lookup key here.
_ROTATE_ORDER_ENUM = {"xyz": 0, "yzx": 1, "zxy": 2,
                      "xzy": 3, "yxz": 4, "zyx": 5}

# reverse of clipmath.FPS_UNITS (fps -> Maya time-unit string), for reading
# an imported FBX's fps back OUT of the scene's time unit after import.
_FPS_BY_UNIT = {unit: fps for fps, unit in clipmath.FPS_UNITS.items()}

# A retarget whose derived source-to-target scale sits beyond this ratio
# (either direction) is almost certainly a units mismatch (BVH inches vs
# this repo's metre-authoring convention, or a wildly mis-proportioned mocap
# skeleton) rather than a legitimately tiny/giant character - named in the
# brief as the threshold to warn at, not refuse: the retarget still runs
# either way, since HIK's own retargeting is scale-aware.
SCALE_WARN_RATIO = 10.0


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _mel():
    import maya.mel as mel  # noqa: PLC0415 - only importable inside Maya

    return mel


# ---------------------------------------------------------------------------
# Pure helpers (no Maya) - BVH hierarchy/channel arithmetic
# ---------------------------------------------------------------------------


def _channel_offsets(joints_spec: Sequence[Dict[str, Any]]) -> List[Tuple[int, int]]:
    """(flat-row start index, channel count) per joint, in `joints_spec` order.

    `joints_spec` (mocapmath.parse_bvh's `joints` list) is built in the exact
    depth-first pre-order the file's own MOTION row lists channels in - each
    joint is appended to the list the moment its own CHANNELS line is parsed,
    before its children are - so a running sum of channel counts in this
    order is a correct index into any MOTION row without re-deriving the
    file's layout a second way.
    """
    offsets = []
    idx = 0
    for j in joints_spec:
        offsets.append((idx, len(j["channels"])))
        idx += len(j["channels"])
    return offsets


def _channel_rotate_order(channels: Sequence[str]) -> str:
    """The 3-letter rotateOrder key for one joint's CHANNELS list.

    Refuses (rather than guesses) a joint whose rotation channels are not
    exactly one each of X/Y/Z - a malformed or exotic BVH variant this
    module has never been measured against.
    """
    axes = "".join(c[0].lower() for c in channels if c.endswith("rotation"))
    if sorted(axes) != ["x", "y", "z"]:
        raise HandlerError(
            "a joint's rotation channels are %r - not exactly one each of "
            "Xrotation/Yrotation/Zrotation" % (channels,),
            hint="retarget_clip's BVH source builder needs a full X/Y/Z "
                 "rotation triple per joint to set a matching rotateOrder")
    return axes


def _cumulative_positions(joints_spec: Sequence[Dict[str, Any]]) -> List[List[float]]:
    """World-space rest positions from BVH OFFSETs, in the file's raw units.

    A BVH hierarchy's OFFSETs are defined at the (unrotated) rest pose, so
    they stack by plain vector addition down the parent chain - no rotation
    math needed until the MOTION data is applied. `parent` indices are into
    this same list (mocapmath.parse_bvh guarantees a parent is always
    parsed, hence appended, before its children).
    """
    positions: List[List[float]] = []
    for j in joints_spec:
        offset = j["offset"]
        if j["parent"] is None:
            positions.append(list(offset))
        else:
            parent = positions[j["parent"]]
            positions.append([parent[k] + offset[k] for k in range(3)])
    return positions


def _resample_row(rows: Sequence[Sequence[float]], frac_row: float) -> Sequence[float]:
    """A MOTION row at a possibly-fractional row index, linearly interpolated.

    Needed because the bake fps (`mocapmath.nearest_bake_fps`) is rarely the
    source capture's own rate - CMU's 120fps has no native Maya time unit, so
    a 60fps bake must read every OTHER row, and a non-integer ratio (e.g. a
    50fps bake of a 120fps capture) needs a row that sits between two real
    samples. Linear interpolation of the raw channel values (not spherical
    interpolation of the resulting rotation) is a small approximation right
    at wraparound (-179 to 179 degrees) - acceptable here because this row
    only ever feeds a scaffolding skeleton HIK re-derives orientation from,
    never the delivered clip's own curves.
    """
    lo = max(0, min(int(math.floor(frac_row)), len(rows) - 1))
    hi = min(lo + 1, len(rows) - 1)
    frac = frac_row - lo
    if hi == lo or frac <= 1e-9:
        return rows[lo]
    a, b = rows[lo], rows[hi]
    return [av + (bv - av) * frac for av, bv in zip(a, b)]


def _source_hips_height(bvh: Dict[str, Any], hips_name: str, start_row: int) -> float:
    """The source skeleton's Hips joint height (world Y) at `start_row`.

    Looked up BY NAME (the resolved HIK slot's actual BVH joint name), not by
    assuming the hierarchy's first joint - `resolve_hik_map` already proved
    this name exists in `bvh["joints"]`, but not that it is the root. When
    that joint carries no Yposition channel (only the true root normally
    does), its REST offset height stands in - always available, just not
    animated.
    """
    joints_spec = bvh["joints"]
    offsets = _channel_offsets(joints_spec)
    for i, j in enumerate(joints_spec):
        if j["name"] != hips_name:
            continue
        channels = j["channels"]
        if "Yposition" in channels:
            idx, _count = offsets[i]
            return float(bvh["rows"][start_row][idx + channels.index("Yposition")])
        return _cumulative_positions(joints_spec)[i][1]
    return 0.0  # unreachable: resolve_hik_map already guaranteed this name


# ---------------------------------------------------------------------------
# Maya-phase helpers
# ---------------------------------------------------------------------------


def _create_source_joints(cmds, joints_spec: Sequence[Dict[str, Any]],
                          ns: str, scale_factor: float) -> List[str]:
    """One Maya joint per parsed BVH joint, in a fresh namespace `ns`.

    jointOrient is forced to zero on every joint (BVH channels are ALREADY
    the full local rotation - a create_skeleton-style auto-orient would
    double-apply orientation) and rotateOrder is set to match each joint's
    own CHANNELS order, so a later `cmds.setKeyframe(..., attribute="rotateX"
    ...)` with the raw BVH value is correct without any per-frame matrix work.
    """
    cmds.namespace(add=ns)
    positions = _cumulative_positions(joints_spec)
    created: List[str] = []
    for i, j in enumerate(joints_spec):
        pos = [c * scale_factor for c in positions[i]]
        node_name = "%s:%s" % (ns, j["name"])
        if j["parent"] is None:
            cmds.select(clear=True)
        else:
            cmds.select(created[j["parent"]], replace=True)
        node = cmds.joint(name=node_name, position=pos)
        cmds.setAttr(node + ".jointOrient", 0.0, 0.0, 0.0)
        order = _channel_rotate_order(j["channels"])
        cmds.setAttr(node + ".rotateOrder", _ROTATE_ORDER_ENUM[order])
        created.append(node)
    return created


def _key_source_motion(cmds, joints_spec: Sequence[Dict[str, Any]],
                       joint_nodes: Sequence[str], rows: Sequence[Sequence[float]],
                       start_row: float, target_start_frame: int,
                       num_bake_frames: int, source_fps: float, bake_fps: int,
                       scale_factor: float) -> None:
    """Key every parsed channel of every source joint, one key per BAKE frame.

    Every joint (not just the 15 HIK-mapped ones) is keyed: CMU's hierarchy
    carries stub joints between mapped slots (e.g. LHipJoint before
    LeftUpLeg) that still contribute real rotation to the FK chain, so a
    mapped joint's WORLD orientation - which is what HIK characterizes and
    reads - depends on every ancestor being keyed too, not just the ones
    with a slot of their own.
    """
    offsets = _channel_offsets(joints_spec)
    step = source_fps / float(bake_fps)
    for k in range(num_bake_frames):
        frame = target_start_frame + k
        row = _resample_row(rows, start_row + k * step)
        for i, j in enumerate(joints_spec):
            node = joint_nodes[i]
            idx, count = offsets[i]
            for chan, value in zip(j["channels"], row[idx: idx + count]):
                if chan.endswith("position"):
                    cmds.setKeyframe(node, attribute="translate" + chan[0].upper(),
                                     time=frame, value=value * scale_factor)
                elif chan.endswith("rotation"):
                    cmds.setKeyframe(node, attribute="rotate" + chan[0].upper(),
                                     time=frame,
                                     value=units.degrees_to_ui(cmds, value))


def _characterize(cmds, mel, name_hint: str, slot_joints: Dict[str, str],
                  created: List[str]) -> str:
    """hikCreateCharacter -> assign every slot -> lock -> VERIFY the lock.

    `hikCharacterLock` not raising is not evidence it worked (#774 Task 1's
    landmine: it silently no-ops without `mayaCharacterization` also
    loaded) - `hikIsDefinitionLocked` is always read back and a false there
    is a refusal, never a warning.

    #774 review CRITICAL 1: a lock failure (or any exception from
    `setCharacterObject`/`hikSetCurrentCharacter` below) used to raise
    BEFORE this function returned the character's name - the caller's own
    `target_char`/`source_char` variable stayed at its pre-call `None`, so
    `_teardown_hik` never saw the name and skipped deleting a character
    `hikCreateCharacter` had already created. `created` is the caller's own
    list; the name is appended the INSTANT `hikCreateCharacter` returns it -
    before any fallible call - so every character this function ever
    creates is reachable by teardown regardless of what fails afterward.
    """
    char = mel.eval('hikCreateCharacter("%s")'
                    % naming.unique_name(cmds, name_hint))
    created.append(char)
    for slot, joint in slot_joints.items():
        mel.eval('setCharacterObject("%s", "%s", %d, 0)'
                 % (joint, char, _HIK_SLOT_IDS[slot]))
    mel.eval('hikSetCurrentCharacter("%s")' % char)
    mel.eval('hikCharacterLock("%s", 1, 1)' % char)
    if not mel.eval('hikIsDefinitionLocked("%s")' % char):
        raise HandlerError(
            "HumanIK refused to lock the %r characterization "
            "(hikIsDefinitionLocked stayed 0 after hikCharacterLock)" % char,
            hint="measured cause (#774 Task 1): mayaHIK alone silently "
                 "fails to lock unless mayaCharacterization is ALSO loaded "
                 "- both are loaded before this call, so a failure here "
                 "means this skeleton's slot joints are not a valid "
                 "characterization (e.g. two slots on the same joint)")
    return char


def _stance_snapshot(cmds, joints: Sequence[str]):
    """Temporarily force every joint's ROTATION to zero - the build stance (#788).

    HumanIK records the pose at characterization time as the character's
    STANCE, and retargeting maps stance-relative rotation. A skeleton whose
    curves pose it mid-motion at characterization time therefore has its
    stance recorded as that motion pose, and every CONSTANT limb offset
    between the true stance and the motion is silently eaten - measured as
    arms retargeting horizontal (T-pose) while legs, straight in both poses,
    came through fine. Zero rotation IS the stance for every skeleton this
    tool builds or characterizes (create_skeleton rigs and BVH-offset
    sources are both authored that way).

    Returns a snapshot for `_stance_restore`: the disconnected anim-curve
    plugs AND the raw values, so the rig leaves exactly as it arrived.
    """
    saved_conn = []
    saved_val = []
    for j in joints:
        for ax in ("X", "Y", "Z"):
            attr = "%s.rotate%s" % (j, ax)
            try:
                for src in (cmds.listConnections(attr, source=True,
                                                 destination=False,
                                                 plugs=True) or []):
                    cmds.disconnectAttr(src, attr)
                    saved_conn.append((src, attr))
                saved_val.append((attr, cmds.getAttr(attr)))
                cmds.setAttr(attr, 0.0)
            except Exception:  # noqa: BLE001 - a locked/missing channel holds
                pass           # no stance error either way; skip, never abort
    return saved_conn, saved_val


def _stance_restore(cmds, snapshot) -> None:
    """Undo `_stance_snapshot`: values first, then the anim-curve plugs."""
    saved_conn, saved_val = snapshot
    for attr, val in saved_val:
        try:
            cmds.setAttr(attr, val)
        except Exception:  # noqa: BLE001 - restore is best-effort per channel
            pass
    for src, attr in saved_conn:
        try:
            cmds.connectAttr(src, attr)
        except Exception:  # noqa: BLE001
            pass


def _characterize_at_stance(cmds, mel, name_hint: str,
                            slot_joints: Dict[str, str],
                            created: List[str],
                            all_joints: Sequence[str]) -> str:
    """`_characterize`, with the skeleton held at its zero-rotation stance
    for exactly the duration of the characterization (#788). The lock
    snapshots the pose into the character definition, so restoring the live
    pose immediately afterwards changes nothing HIK later solves with.
    """
    snapshot = _stance_snapshot(cmds, all_joints)
    try:
        return _characterize(cmds, mel, name_hint, slot_joints, created)
    finally:
        _stance_restore(cmds, snapshot)


def _teardown_hik(cmds, mel, characters: Sequence[Optional[str]], ns: str,
                  warnings: List[str]) -> None:
    """hikDeleteCharacter per character, then the source namespace, then
    VERIFY no HIK-typed node survives - the exact sequence Task 1's probe
    measured to leave 0 leftover nodes. Runs on every exit (success or
    failure) via the caller's try/finally; never raises itself, since a
    teardown failure must not mask the real error already propagating.

    `characters` is the caller's OWN append-as-created list (see
    `_characterize`'s docstring, #774 review CRITICAL 1) - every name a
    `hikCreateCharacter` call actually returned, whether or not that
    character went on to lock successfully. The `if not char: continue`
    below stays as a defensive no-op for a falsy entry, but nothing normal
    should ever produce one now.
    """
    for char in characters:
        if not char:
            continue
        try:
            if cmds.objExists(char):
                mel.eval('hikDeleteCharacter("%s")' % char)
        except Exception as exc:  # noqa: BLE001 - teardown must not throw
            warnings.append("hikDeleteCharacter(%r) raised during teardown: "
                            "%s" % (char, exc))
    try:
        if cmds.namespace(exists=ns):
            cmds.namespace(removeNamespace=ns, deleteNamespaceContent=True)
    except Exception as exc:  # noqa: BLE001
        warnings.append("removing namespace %r raised during teardown: %s"
                        % (ns, exc))
    leftover = sorted({n for t in _HIK_NODE_TYPES
                       for n in (cmds.ls(type=t) or [])})
    if leftover:
        warnings.append(
            "residual HIK node(s) survived teardown: %s - this should "
            "never happen (Task 1's probe measured 0); report it"
            % ", ".join(leftover))


# ---------------------------------------------------------------------------
# Shared refusal-guard reuse (author_clip's own rules, applied here too)
# ---------------------------------------------------------------------------


def _weight_plugs(cmds, target_joints: List[str]) -> List[str]:
    """Every blendShape weight plug on the meshes this rig moves - what
    the replace cut has to clear, now that this producer pins weight
    channels at its boundaries like author_clip does (#798 review 5)."""
    alias_map = clip._weight_alias_map(
        cmds, rigging._bound_meshes(cmds, set(target_joints)))
    return sorted("%s.%s" % (node, alias) for alias, node in alias_map.items()
                  if not isinstance(node, HandlerError))


def _rest_before_cut(cmds, root_long: str,
                     slot_joints: Dict[str, str]) -> Dict[str, float]:
    """The rig's rest map, with the root's TRANSLATION rest captured before
    anything on this call mutates the scene (#798 review 3).

    Translate curves are not disconnected by the stance window, so the
    stance is the wrong moment for them on a RE-retarget: the replace cut
    has just emptied the old bake's root curve and left the plug at a
    meaningless static value, which `_capture_rest` would then record as
    rest with no warning at all. Captured here instead, a curve-fed root
    is skipped - the honest "no rest known" that `_rest_value` later
    infers and WARNS about - and an unkeyed root is read at its bind.
    """
    rest = clip._rest_map(cmds, root_long)
    if root_long in set(slot_joints.values()):
        for attr in clip.TRANSLATE_ATTRS:
            clip._capture_rest(cmds, "%s.%s" % (root_long, attr), rest)
    return rest


def _rest_at_stance(cmds, root_long: str, slot_joints: Dict[str, str],
                    rest: Dict[str, float]) -> Dict[str, float]:
    """Every ROTATION this bake is about to write, captured into `rest`
    NOW - which must be while the rig stands at its stance (#798).

    author_clip captures a channel's rest the moment before it keys it,
    and the #718 pass pins against that record. This tool captured
    nothing, so the author_clip that came next inferred a "rest" for a
    baked joint from its EARLIEST KEY - the walk's first frame - and its
    back-fill wrote that value over the walk's last frame (MEASURED,
    evals/clip_edges_probe_798 section B: head.rotateX at walk01's end
    became its start). Called inside the caller's `_stance_snapshot`
    window: the rotate curves are disconnected there, so `_capture_rest`
    reads the stance pose rather than skipping a plug some other clip
    already drives, and a channel already recorded is left alone as
    always. The root's translation is `_rest_before_cut`'s.
    """
    for j in sorted(set(slot_joints.values())):
        for attr in clip.ROTATE_ATTRS:
            clip._capture_rest(cmds, "%s.%s" % (j, attr), rest)
    return rest


def _finish_take(cmds, root_long: str, target_joints: List[str],
                 slot_joints: Dict[str, str], name: str, bake_fps: int,
                 start_frame: int, end_frame: int,
                 kept: List[Dict[str, Any]], rest: Dict[str, float],
                 warnings: List[str]) -> Dict[str, Any]:
    """After the bake: say what it left, make the take self-contained, and
    register it (#798).

    `mine` is derived from the SCENE - the slot joints whose rotate
    channels carry a clip curve keyed inside this take's range, and the
    root's translation when it is a slot joint and got the same - never
    from the list `bakeResults` was aimed at (#796's observed-writes
    rule, at this producer's one write site). The record used to declare
    `joints: []` for every retargeted take, which is why the author_clip
    that came next pinned nothing against it. Then `clip.make_self_
    contained` runs exactly as it does for author_clip: the neighbours'
    channels this bake does not cover are pinned at rest at this take's
    boundaries, and this take's own joints are pinned at rest across
    every earlier clip's range.
    """
    slots = sorted(set(slot_joints.values()))
    keyed = clip.clip_curve_plugs(
        cmds, clip._anim_curves(cmds, clip._joint_plugs(slots)))
    landed_joints = set()
    root_landed = False
    for plug in keyed:
        times = cmds.keyframe(plug, query=True) or []
        if not any(start_frame <= t <= end_frame for t in times):
            continue
        node, attr = plug.rsplit(".", 1)
        if attr in clip.ROTATE_ATTRS:
            landed_joints.add(clip._short(node))
        elif node == root_long and attr in clip.TRANSLATE_ATTRS:
            root_landed = True
    if root_long not in slots:
        # Review catch 2: the Hips slot's baked TRANSLATION carries this
        # bake's root motion, and the clip model has a channel only for
        # the ROOT's translation. Nothing declares, pads or back-fills it,
        # so it holds across every neighbour and through this take's own
        # boundaries - said here, since the model cannot carry it.
        warnings.append(
            "%s is the Hips slot but not this rig's root, so its baked "
            "translation - the root motion of %r - sits outside the clip "
            "model: no record declares it, nothing pins it at any clip's "
            "boundary, and it holds across the neighbouring takes; make "
            "the Hips joint the root to have it treated as root_position"
            % (slot_joints.get("Hips", "the Hips joint"), name))
    silent = [clip._short(j) for j in slots
              if clip._short(j) not in landed_joints]
    if silent:
        warnings.append(
            "the bake left no rotation curve keyed in frames %d-%d on %s - "
            "those slot joints are not declared by %r, so nothing pins "
            "them at its boundaries; check what drives them"
            % (start_frame, end_frame, ", ".join(silent), name))
    mine = {"joints": sorted(landed_joints), "weight_channels": [],
            "root_position_used": root_landed}
    alias_map = clip._weight_alias_map(
        cmds, rigging._bound_meshes(cmds, set(target_joints)))
    contained = clip.make_self_contained(
        cmds, "retarget_clip", root_long, target_joints, alias_map,
        start_frame, end_frame, float(end_frame), kept, mine, rest,
        warnings)
    clip.register_clip(cmds, root_long, name, bake_fps, start_frame,
                       end_frame, loop=False, joints=mine["joints"],
                       root_position_used=mine["root_position_used"])
    return contained


# The three channel groups with a COMPOUND: a connection can land on
# `.rotate`/`.translate`/`.scale` itself (a rotation anim layer does), where
# it covers all three children and a query on a child reports nothing.
_TRIPLES = ((clip.ROTATE_ATTRS, "rotate"),
            (clip.TRANSLATE_ATTRS, "translate"),
            (clip.SCALE_ATTRS, "scale"))
_TRIPLE_ATTRS = frozenset(
    [a for attrs, _ in _TRIPLES for a in attrs]
    + [compound for _, compound in _TRIPLES])


def _baked_channel_groups(cmds, joints: List[str], warnings: List[str]
                          ) -> List[Tuple[str, Tuple[str, ...],
                                          Optional[str]]]:
    """[(node, attrs, compound)] for every channel `bakeResults` writes on
    `joints` - ASKED, not assumed (#796 review round 6 D).

    With no `-attribute` flag `bakeResults` bakes every KEYABLE channel of
    each node it is aimed at. The guard used to ask about ROTATE and
    TRANSLATE while its own comment claimed that was everything the bake
    writes, so a squash-and-stretch set-driven key on a slot joint's
    `.scaleY` - or on any keyable attribute a rigger added - was baked over
    with nothing named. Maya is asked for the list rather than a hardcoded
    guess, because a guess is exactly how the claim outgrew the guard the
    first time.

    The triples keep their compound fallback; everything else is a scalar
    plug with no parent to ask about, which `_connected_channels` takes as
    `compound=None`. A joint that cannot answer `listAttr` costs the
    WIDENING and says so - the triples are still asked, the way the
    write-side guards degrade rather than crash.
    """
    groups: List[Tuple[str, Tuple[str, ...], Optional[str]]] = []
    for joint in sorted(set(joints)):
        for attrs, compound in _TRIPLES:
            groups.append((joint, attrs, compound))
        try:
            keyable = cmds.listAttr(joint, keyable=True) or []
        except Exception as exc:  # noqa: BLE001 - one joint, not the guard
            warnings.append(
                "cannot list %s's keyable channels (%s) - retarget_clip "
                "checked its rotate, translate and scale channels only, so "
                "a user-defined keyable attribute this bake writes is "
                "unchecked; check it after the call" % (joint, exc))
            continue
        extra = tuple(a for a in keyable if a not in _TRIPLE_ATTRS)
        if extra:
            groups.append((joint, extra, None))
    return groups


def _apply_shared_guards(cmds, root_long: str, target_joints: List[str],
                         slot_joints: Dict[str, str], bake_fps: int,
                         warnings: List[str]) -> List[Dict[str, Any]]:
    """The author_clip guard rails a second clip-producer must not skip:
    one-fps-per-rig, refuse clobbering hand-authored curves, name the
    channels this bake writes that something already drives, warn about
    another rig on the same scene carrying clips. Returns the rig's
    existing clip records (needed by the caller for next_start_frame).

    What is deliberately NOT here (#796 review round 4 C):
    `refuse_driven_weight` and the boundary-pin skip, because this tool
    declares no `blend_weights` channel and pins no boundaries - it bakes
    the HIK slot joints and nothing else; and `guard_static_pose`, which
    is the guard for tools that write a STATIC pose, the opposite of this
    one. Everything author_clip refuses about the channels it is about to
    write, this now asks too.
    """
    records = clip.clip_meta(cmds, root_long)
    conflict = clipmath.fps_conflict(records, bake_fps)
    if conflict:
        raise HandlerError(
            conflict,
            hint="delete_clip the clips at the other rate, or retarget this "
                 "one at theirs")

    # #796 review round 4 C: the CLIP partition, exactly as author_clip
    # counts it. The raw query's type="animCurve" filter matches the
    # DERIVED U-typed set-driven-key nodes, so a rig carrying rig setup was
    # refused here as "hand-authored animation", the hint sent the caller
    # to delete_clip, and delete_clip refuses that rig with "no clip
    # exists" and a note that it never removes set-driven keys: a closed
    # loop, and a target rig carrying a driven key could never be
    # retargeted onto. The hint stays true because what it counts is
    # exactly what delete_clip deletes.
    existing = clip.clip_curve_plugs(
        cmds, clip._anim_curves(cmds, clip._joint_plugs(target_joints)))
    if existing and not records:
        raise HandlerError(
            "this skeleton carries %d hand-authored animation curve "
            "channel(s) this tool did not author (e.g. %s)"
            % (len(existing), sorted(existing)[0]),
            hint="replacing hand-authored animation silently would destroy "
                 "work; delete_clip removes it if that is intended")

    # author_clip's per-channel treatment, on the channels this tool
    # actually writes: `bakeResults` is aimed at the HIK SLOT joints (both
    # routes bake `target_slot_joints.values()`), and with no `-at` flag it
    # writes every KEYABLE channel of each - which is what
    # `_baked_channel_groups` asks Maya for, rather than the rotate and
    # translate this comment used to claim was all of it (#796 review round
    # 6 D). A driven key elsewhere on the rig is rig setup and none of this
    # call's business, exactly as on the author side.
    #
    # WARNED, never refused, and that is the one deliberate difference from
    # author_clip: #771's "the write returns 0 and creates nothing" is a
    # `setKeyframe` measurement, and nothing in this repo has measured what
    # `bakeResults` does to a connection-fed plug (it may bake through it,
    # replace the connection, or skip it). Refusing on a measurement about
    # a different mechanism would stop a rig that retargets today - the
    # round-4 defect B mistake, one tool over. The live gate settles it.
    warnings.extend(clip.guard_declared_channels(
        cmds, "retarget_clip",
        _baked_channel_groups(cmds, list(slot_joints.values()), warnings),
        refuse_unkeyable=False))

    elsewhere = clip._clips_elsewhere(cmds, root_long)
    if elsewhere:
        warnings.append(
            "another skeleton carries clips (%s) - export_fbx REFUSES a "
            "scene where two rigs carry clips, because a take is a frame "
            "range over the whole file; delete_clip the rig not being "
            "exported" % ", ".join(elsewhere))
    return records


def _resolve_target(cmds, root_param: Any) -> Tuple[str, List[str], Dict[str, str]]:
    root_long = rigging._require_joint(cmds, root_param)
    target_joints = rigging._hierarchy_joints(cmds, root_long)
    target_by_short = {clip._short(j): j for j in target_joints}
    try:
        slot_map = mocapmath.resolve_hik_map(
            [clip._short(j) for j in target_joints], mocapmath.SKELETON_HIK_MAP)
    except HandlerError as exc:
        raise HandlerError(
            "target is not a biped this tool can characterize: %s" % exc,
            hint=exc.hint) from exc
    slot_joints = {slot: target_by_short[short] for slot, short in slot_map.items()}
    return root_long, target_joints, slot_joints


def _set_bake_unit(cmds, bake_fps: int, warnings: List[str]) -> None:
    prev_unit = cmds.currentUnit(query=True, time=True)
    unit = clipmath.FPS_UNITS[bake_fps]
    if prev_unit != unit:
        cmds.currentUnit(time=unit)
        warnings.append("scene time unit changed %r -> %r so a frame is "
                        "1/%d s" % (prev_unit, unit, bake_fps))


def _fold_measures(cmds, root_long: str, name: str,
                   warnings: List[str]) -> Dict[str, Any]:
    measures = clip.measure_clip({"root": root_long, "name": name})
    warnings.extend(measures.get("warnings", []))
    return measures


# ---------------------------------------------------------------------------
# Pure param validation
# ---------------------------------------------------------------------------


def _validate_common(params: Dict[str, Any]) -> Tuple[str, str, str, Optional[float], Optional[float], Optional[int]]:
    """keys -> clip name -> extension -> existence -> root -> range -> fps.

    Everything here is pure (no Maya, no filesystem beyond one `isfile`/
    `splitext`) so a malformed call is refused before a scene is ever
    touched - the #768 proof pattern: these checks running headless IS the
    proof they run before Maya.
    """
    require_known_keys(params, RETARGET_CLIP_KEYS, "retarget_clip",
                       RETARGET_CLIP_SYNONYMS)

    name = params.get("clip")
    if not isinstance(name, str) or not clip.NAME_RE.fullmatch(name):
        raise HandlerError(
            "clip %r must be a plain identifier (letters, digits, "
            "underscore; not starting with a digit)" % (name,),
            hint="the name becomes the exported take name, same as "
                 "author_clip's `name`")

    file_param = params.get("file")
    if not isinstance(file_param, str) or not file_param.strip():
        raise HandlerError(
            "missing required param 'file'",
            hint="a local .bvh or .fbx path - BVH is parsed internally, "
                 "FBX imports via Maya's native FBX path")
    path = file_param.strip()
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".bvh", ".fbx"):
        raise HandlerError(
            "unsupported file extension %r - retarget_clip reads .bvh or "
            ".fbx" % ext,
            hint="pass a local mocap file with one of those extensions")

    if not os.path.isfile(path):
        raise HandlerError(
            "no such file: %r" % path,
            hint="pass a local, readable .bvh or .fbx path")

    root_param = params.get("root")
    if not isinstance(root_param, str) or not root_param.strip():
        raise HandlerError(
            "missing required param 'root'",
            hint="the target rig's root joint, e.g. what create_skeleton "
                 "returned as `root`")

    start = params.get("start")
    end = params.get("end")
    for label, value in (("start", start), ("end", end)):
        if value is not None and (isinstance(value, bool)
                                  or not isinstance(value, (int, float))
                                  or value < 0):
            raise HandlerError(
                "%s must be a non-negative number of source frames" % label,
                hint="start/end trim the SOURCE file's frame range (row "
                     "indices), before any bake-rate resampling")
    if start is not None and end is not None and end <= start:
        raise HandlerError(
            "start must be < end (got start=%r, end=%r)" % (start, end),
            hint="start/end trim the SOURCE frame range - end must come "
                 "after start")

    fps = params.get("fps")
    if fps is not None and (isinstance(fps, bool) or not isinstance(fps, int)
                            or fps not in clipmath.FPS_UNITS):
        raise HandlerError(
            "fps must be one of %s"
            % ", ".join(str(k) for k in sorted(clipmath.FPS_UNITS)),
            hint="the frame rates Maya has native time units for; omit fps "
                 "to bake at whichever of those is nearest the source's own "
                 "capture rate")

    # #797 row 25: on the .fbx route fps selects a bake rate that nothing
    # resamples TO. The FBX's own rate is only knowable from the SCENE's
    # time unit after the import; the keyed range is then read in that
    # unit (`cmds.keyframe`), start/end are clamped against it, and
    # `_set_bake_unit` changes the unit only afterwards - so the range and
    # the bake speak different rates whenever fps differs from the file's.
    # The BVH route has no such gap (its rate comes from the file header,
    # before anything is imported) and keeps fps. This route has never run
    # live either - every eval in this repo feeds it BVH - so the claim
    # "fps resamples an FBX correctly" is not measured, and #797's rule is
    # that an unmeasured effect is refused, not shipped.
    if ext == ".fbx" and fps is not None:
        refuse_inert(
            "retarget_clip", "fps", "on the .fbx route",
            "the keyed range is read in the file's own time unit and the "
            "bake unit is set after it, so a different fps has not been "
            "measured to resample correctly",
            hint="omit fps for an FBX source - it bakes at the file's own "
                 "rate - or convert the clip to BVH, whose route reads its "
                 "rate from the file header and does resample")

    return path, ext, name, start, end, fps


def _source_row(label: str, value: float, notes: List[str]) -> int:
    """A SOURCE ROW INDEX from the caller's `start`/`end` number.

    Both routes have always taken `int(round())` here and said nothing, so
    `start=10.6` trimmed at row 11 and reported 10.6 back to nobody -
    #797's "never a silent echo of an unused value" at its smallest. The
    schema types these `Optional[float]` (server.py), so a refusal would
    refuse a call the wrapper is entitled to send; #797's schema exception
    is a WARNING naming the value actually APPLIED instead.
    """
    row = int(round(value))
    if row != value:
        notes.append(
            "%s=%r is not a whole source row - the trim used row %d. "
            "start/end are row INDICES into the source file, so the "
            "fractional part selects nothing" % (label, value, row))
    return row


# ---------------------------------------------------------------------------
# BVH route
# ---------------------------------------------------------------------------


def _retarget_bvh(path: str, root_param: str, name: str,
                  start_param: Optional[float], end_param: Optional[float],
                  fps_param: Optional[int]) -> Dict[str, Any]:
    try:
        with open(path, "r") as f:
            text = f.read()
    except OSError as exc:
        raise HandlerError("could not read %r: %s" % (path, exc),
                           hint="check the file's permissions/encoding")
    bvh = mocapmath.parse_bvh(text)
    for j in bvh["joints"]:
        _channel_rotate_order(j["channels"])  # validated for its own sake

    frames = bvh["frames"]
    # `warnings` does not exist until the Maya phase below, so the rounding
    # notes are collected here and folded into it there.
    range_notes: List[str] = []
    start_row = (_source_row("start", start_param, range_notes)
                 if start_param is not None else 0)
    end_row = (_source_row("end", end_param, range_notes)
               if end_param is not None else frames - 1)
    for label, row in (("start", start_row), ("end", end_row)):
        if not 0 <= row < frames:
            raise HandlerError(
                "%s=%d is outside %r's %d frames" % (label, row, path, frames),
                hint="row indices run 0..%d for this file" % (frames - 1))
    if end_row <= start_row:
        raise HandlerError(
            "start must be < end (got start=%d, end=%d) within %r's frame "
            "range" % (start_row, end_row, path))

    source_fps = mocapmath.source_fps(bvh["frame_time"])
    bake_fps = (fps_param if fps_param is not None
               else mocapmath.nearest_bake_fps(source_fps,
                                              set(clipmath.FPS_UNITS)))

    source_names = [j["name"] for j in bvh["joints"]]
    try:
        source_slot_map = mocapmath.resolve_hik_map(
            source_names, mocapmath.CMU_HIK_MAP)
    except HandlerError as exc:
        raise HandlerError(
            "%r is not a mocap skeleton this tool recognizes: %s"
            % (path, exc),
            hint=exc.hint) from exc

    cmds = _cmds()
    mel = _mel()
    root_long, target_joints, target_slot_joints = _resolve_target(cmds, root_param)

    warnings: List[str] = list(range_notes)
    for action in session.stop_idle_ipr(cmds):
        warnings.append(
            action + " before keyframe/bake work - an idle IPR re-renders "
            "on every scene mutation and can wedge a keyframe call for "
            "minutes (#721)")

    records = _apply_shared_guards(cmds, root_long, target_joints,
                                   target_slot_joints, bake_fps, warnings)
    # #774 review IMPORTANT 3: re-retargeting an EXISTING clip name must cut
    # its old range first, mirroring author_clip's own re-author path
    # (clip.cut_replaced_range, extracted from there) - otherwise the old
    # bake's keys never go away and the new bake's keys land ALONGSIDE them,
    # accumulating one extra copy per re-retarget. `kept` (not `records`)
    # is what the new bake gets appended after, same as author_clip: the
    # freed range is not reused, the new bake goes to the tail of every
    # OTHER clip.
    replaced, kept = clipmath.drop_record(records, name)
    # #798: the root's translation rest, read before the cut below can
    # disturb it (see _rest_before_cut); the rotations follow at stance.
    rest = _rest_before_cut(cmds, root_long, target_slot_joints)

    session.auto_checkpoint("retarget_clip")
    _set_bake_unit(cmds, bake_fps, warnings)
    if replaced is not None:
        # #796 review round 5 A: the cut is partitioned now (a driven-key
        # curve is indexed by driver VALUE, so a frame range would eat rig
        # setup) and NAMES every plug it stepped around. Weight plugs too
        # (#798): this producer pins them at its boundaries now.
        warnings.extend(clip.cut_replaced_range(
            cmds, target_joints, replaced, _weight_plugs(cmds, target_joints)))
        warnings.append(
            "re-retargeted clip %r: cleared its old frames %d-%d before "
            "baking the new range - no other clip's motion changed"
            % (name, replaced["start_frame"], replaced["end_frame"]))

    # #788 (third symptom): the target's hips height must be read at STANCE, not at whatever
    # pose the rig's existing clip curves hold at currentTime — a posed read (crouched, mid-hit,
    # airborne) scales the whole retarget wrong, and the error ships silently as a subject who
    # stands taller or shorter than the rig (measured: an idle baked from a mid-clip read came
    # out 15% tall, floating feet and all).
    stance_snapshot = _stance_snapshot(cmds, target_joints)
    try:
        target_hips_height = float(cmds.xform(
            target_slot_joints["Hips"], query=True, worldSpace=True,
            translation=True)[1])
        # #798: the rotation rest this take's channels will be pinned
        # at, read at the same stance the hips height is - before the
        # bake writes over them.
        _rest_at_stance(cmds, root_long, target_slot_joints, rest)
    finally:
        _stance_restore(cmds, stance_snapshot)
    source_hips_height = _source_hips_height(
        bvh, source_slot_map["Hips"], start_row)
    if abs(source_hips_height) > 1e-9:
        scale_factor = target_hips_height / source_hips_height
    else:
        scale_factor = 1.0
        warnings.append(
            "the source's Hips joint measures ~zero height (%.6g) at the "
            "trim start - no scale could be derived, so the source "
            "skeleton was left at the file's raw scale"
            % source_hips_height)
    if scale_factor > SCALE_WARN_RATIO or scale_factor < 1.0 / SCALE_WARN_RATIO:
        warnings.append(
            "source-to-target scale factor is %.4g - the mocap file's "
            "units and this rig's scale differ by more than %gx"
            % (scale_factor, SCALE_WARN_RATIO))

    duration_s = (end_row - start_row) * bvh["frame_time"]
    num_bake_frames = int(round(duration_s * bake_fps)) + 1
    target_start_frame = clipmath.next_start_frame(kept)
    bake_end_frame = target_start_frame + num_bake_frames - 1

    ns = "mocap_src_%s" % name
    characters: List[str] = []
    try:
        joint_nodes = _create_source_joints(cmds, bvh["joints"], ns,
                                            scale_factor)
        source_slot_joints = {slot: "%s:%s" % (ns, jname)
                              for slot, jname in source_slot_map.items()}

        cmds.loadPlugin(_HIK_PLUGIN, quiet=True)
        cmds.loadPlugin(_HIK_CHARACTERIZATION_PLUGIN, quiet=True)

        # #788: characterize BOTH skeletons at their zero-rotation stance,
        # BEFORE any motion drives them. The source is trivially at stance
        # here - its joints were just created at the BVH's OFFSET rest pose
        # and carry no curves yet, which is exactly why it is characterized
        # before _key_source_motion. The target may already carry other
        # clips' curves (the multi-take workflow), so it gets the explicit
        # stance guard. Characterizing after keying was the measured cause
        # of arms retargeting horizontal: HIK recorded a mid-walk pose as
        # the stance and ate the constant stance-to-hanging arm rotation.
        source_char = _characterize(cmds, mel, "retarget_source",
                                    source_slot_joints, characters)
        target_char = _characterize_at_stance(cmds, mel, "retarget_target",
                                              target_slot_joints, characters,
                                              target_joints)

        _key_source_motion(cmds, bvh["joints"], joint_nodes, bvh["rows"],
                           start_row, target_start_frame, num_bake_frames,
                           source_fps, bake_fps, scale_factor)
        mel.eval('hikSetCharacterInput("%s", "%s")' % (target_char, source_char))

        # preserveOutsideKeys, or this bake DESTROYS every other take on the
        # rig: bakeResults' default replaces the whole curve with keys for
        # only the baked range, so baking take 2 (frames 159-308) left take
        # 1's frames 0-157 evaluating to a pre-infinity constant - a frozen
        # figure in every preview cell, and an export whose first take
        # resamples that constant with a perfectly correct key COUNT (#780,
        # measured: pelvis_translateZ1 held 150 keys spanning 159-308 and
        # nothing else after the second retarget).
        cmds.bakeResults(list(target_slot_joints.values()),
                         time=(target_start_frame, bake_end_frame),
                         sampleBy=1, simulation=True,
                         preserveOutsideKeys=True)
    except HandlerError:
        raise
    except Exception as exc:  # noqa: BLE001 - see module docstring / #774
        # review CRITICAL 1 follow-up (Task 4): a mid-characterize HIK/mel
        # failure (e.g. an unresolvable slot id) used to escape as a raw
        # RuntimeError from `mel.eval` - every OTHER refusal in this module
        # is a HandlerError, and a caller catching HandlerError (the
        # documented contract) would not catch this. The `finally` below
        # still tears down exactly as it does for any other exception.
        raise HandlerError(
            "retargeting failed while characterizing/baking against "
            "HumanIK: %s" % exc,
            hint="this usually means one of the two skeletons' 15 required "
                 "HIK slots could not be assigned - check both joint sets "
                 "for duplicate or missing slot targets") from exc
    finally:
        _teardown_hik(cmds, mel, characters, ns, warnings)

    contained = _finish_take(cmds, root_long, target_joints,
                             target_slot_joints, name, bake_fps,
                             target_start_frame, bake_end_frame, kept, rest,
                             warnings)
    measures = _fold_measures(cmds, root_long, name, warnings)

    return {
        "clip": name,
        "root": root_long,
        "frames": num_bake_frames,
        "fps": bake_fps,
        "source_joints": len(bvh["joints"]),
        "measures": measures,
        "padded_channels": contained["padded_channels"],
        "held_channels": contained["held_channels"],
        "back_filled": contained["back_filled"],
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# FBX route
# ---------------------------------------------------------------------------


def _retarget_fbx(path: str, root_param: str, name: str,
                  start_param: Optional[float],
                  end_param: Optional[float]) -> Dict[str, Any]:
    """The other accepted extension, per the spec - imported via Maya's
    native FBX path rather than parsed by hand.

    Takes no fps: `_validate_common` refuses one on this route (#797 row
    25), so the bake rate here is ALWAYS the file's own, read back from
    the scene's time unit after the import. The BVH route still takes one
    - it knows the source rate from the file header, before importing
    anything, and can resample against it.

    UNTESTED beyond headless param validation: no FBX mocap fixture ships
    with this repo (only the CMU .bvh fixtures, #774 Task 2), so this route
    has never run against a real file, in mayapy or otherwise. It follows
    the same characterize/retarget/bake/teardown shape the BVH route was
    measured against Route A's confirmed HIK invocations, but the joint-name
    resolution and frame-range reading below are reasoned from the FBX
    import API's documented behavior, not measured. Verify against a real
    humanoid FBX mocap file before relying on this path.
    """
    cmds = _cmds()
    mel = _mel()
    root_long, target_joints, target_slot_joints = _resolve_target(cmds, root_param)

    warnings: List[str] = []
    for action in session.stop_idle_ipr(cmds):
        warnings.append(
            action + " before keyframe/bake work - an idle IPR re-renders "
            "on every scene mutation and can wedge a keyframe call for "
            "minutes (#721)")

    ns = "mocap_src_%s" % name
    characters: List[str] = []
    imported_joints: List[str] = []
    try:
        before = set(cmds.ls(long=True))
        cmds.namespace(add=ns)
        cmds.file(path, i=True, namespace=ns, type="FBX",
                 ignoreVersion=True, preserveReferences=False)
        after = set(cmds.ls(long=True))
        imported_joints = sorted(n for n in (after - before)
                                 if cmds.nodeType(n) == "joint")
        if not imported_joints:
            raise HandlerError(
                "%r imported no joints" % path,
                hint="retarget_clip needs a skeletal FBX - this file's "
                     "import produced none")
        # #774 review IMPORTANT 2: an FBX import under `namespace=ns` names
        # every joint "ns:Hips", not "Hips" - `clip._short()` only strips
        # the DAG PIPE ("|a|b|c" -> "c"), never a namespace colon, so
        # matching those names against CMU_HIK_MAP/SKELETON_HIK_MAP (which
        # carry bare names) could never succeed and this route always fell
        # into the "not a known mocap convention" refusal below, regardless
        # of the file. Strip the namespace here (last ":"-segment) for the
        # MAP LOOKUP only; `by_bare_imported` keeps the mapping back to the
        # real, still-namespaced node name characterization needs.
        by_bare_imported = {clip._short(j).rsplit(":", 1)[-1]: j
                            for j in imported_joints}
        imported_bare = list(by_bare_imported.keys())

        source_slot_map = None
        source_slot_error: Optional[HandlerError] = None
        for table in (mocapmath.CMU_HIK_MAP, mocapmath.SKELETON_HIK_MAP):
            try:
                source_slot_map = mocapmath.resolve_hik_map(
                    imported_bare, table)
                break
            except HandlerError as exc:
                source_slot_error = exc
        if source_slot_map is None:
            raise HandlerError(
                "%r's joint names do not match a known mocap convention "
                "(tried the CMU names and this repo's create_skeleton "
                "names): %s" % (path, source_slot_error),
                hint="rename the FBX's joints to a recognized convention, "
                     "or use a BVH source instead")
        source_slot_joints = {slot: by_bare_imported[bare]
                              for slot, bare in source_slot_map.items()}

        times = cmds.keyframe(imported_joints, query=True) or []
        if not times:
            raise HandlerError(
                "%r's joints carry no keyframes" % path,
                hint="this FBX has no baked animation to retarget")
        src_start, src_end = min(times), max(times)
        time_unit = cmds.currentUnit(query=True, time=True)
        source_fps = _FPS_BY_UNIT.get(time_unit)
        if source_fps is None:
            raise HandlerError(
                "the scene's time unit %r after importing %r is not one "
                "this tool recognizes" % (time_unit, path),
                hint="one of: %s"
                     % ", ".join(str(f) for f in sorted(clipmath.FPS_UNITS)))
        # The file's own rate, always: a caller-given fps cannot reach
        # here (#797 row 25 refuses it in _validate_common), and a branch
        # that can only take one side is a claim the code does not make.
        bake_fps = source_fps

        row_start = (_source_row("start", start_param, warnings)
                     if start_param is not None else int(round(src_start)))
        row_end = (_source_row("end", end_param, warnings)
                   if end_param is not None else int(round(src_end)))
        if row_start < src_start or row_end > src_end or row_end <= row_start:
            raise HandlerError(
                "start/end (%r/%r) is outside %r's keyed range (%g-%g)"
                % (start_param, end_param, path, src_start, src_end))

        # Deliberately AFTER the import (unlike the BVH route, which knows
        # its bake fps from the file header alone): an FBX's own fps is only
        # readable from the SCENE's time unit once the file is actually
        # imported, so the fps_conflict guard - and the checkpoint after it
        # - cannot run any earlier here. The `finally` below still reaps the
        # whole `ns` namespace on any refusal from this point, so a refused
        # call still leaves nothing behind.
        records = _apply_shared_guards(cmds, root_long, target_joints,
                                       target_slot_joints, bake_fps,
                                       warnings)
        # #774 review IMPORTANT 3: same replace-cut author_clip does on a
        # re-authored name (clip.cut_replaced_range) - see the BVH route's
        # identical block for the full rationale. `kept` (not `records`)
        # is what the new bake's start frame is computed from below.
        replaced, kept = clipmath.drop_record(records, name)
        rest = _rest_before_cut(cmds, root_long, target_slot_joints)

        session.auto_checkpoint("retarget_clip")
        _set_bake_unit(cmds, bake_fps, warnings)
        if replaced is not None:
            # #796 review round 5 A: same partitioned cut as the BVH route
            # above - see that block.
            warnings.extend(clip.cut_replaced_range(
                cmds, target_joints, replaced,
                _weight_plugs(cmds, target_joints)))
            warnings.append(
                "re-retargeted clip %r: cleared its old frames %d-%d before "
                "baking the new range - no other clip's motion changed"
                % (name, replaced["start_frame"], replaced["end_frame"]))

        # #788 third symptom — stance-read the target's hips, see the BVH route's identical block.
        stance_snapshot = _stance_snapshot(cmds, target_joints)
        try:
            target_hips_height = float(cmds.xform(
                target_slot_joints["Hips"], query=True, worldSpace=True,
                translation=True)[1])
            # #798: same as the BVH route - the rotation rest is read at
            # stance, before the bake writes over these channels.
            _rest_at_stance(cmds, root_long, target_slot_joints, rest)
        finally:
            _stance_restore(cmds, stance_snapshot)
        prev_time = cmds.currentTime(query=True)
        cmds.currentTime(row_start)
        source_hips_height = float(cmds.xform(
            source_slot_joints["Hips"], query=True, worldSpace=True,
            translation=True)[1])
        cmds.currentTime(prev_time)
        if abs(source_hips_height) > 1e-9:
            scale_factor = target_hips_height / source_hips_height
        else:
            scale_factor = 1.0
            warnings.append(
                "the source's Hips joint measures ~zero height at the trim "
                "start - no scale could be derived, so the imported "
                "skeleton was left at its native scale")
        if scale_factor > SCALE_WARN_RATIO or scale_factor < 1.0 / SCALE_WARN_RATIO:
            warnings.append(
                "source-to-target scale factor is %.4g - the mocap file's "
                "scale and this rig's scale differ by more than %gx"
                % (scale_factor, SCALE_WARN_RATIO))
        if abs(scale_factor - 1.0) > 1e-9:
            parents = cmds.listRelatives(imported_joints[0], parent=True,
                                         fullPath=True) or []
            scale_node = parents[0] if parents else imported_joints[0]
            cmds.setAttr(scale_node + ".scale", scale_factor, scale_factor,
                        scale_factor)

        target_start_frame = clipmath.next_start_frame(kept)
        num_bake_frames = row_end - row_start + 1
        bake_end_frame = target_start_frame + num_bake_frames - 1
        shift = target_start_frame - row_start
        if shift:
            cmds.keyframe(imported_joints, edit=True, relative=True,
                         timeChange=shift)

        cmds.loadPlugin(_HIK_PLUGIN, quiet=True)
        cmds.loadPlugin(_HIK_CHARACTERIZATION_PLUGIN, quiet=True)
        # #788: both skeletons characterized at their zero-rotation stance -
        # see the BVH route's identical block. On this route the SOURCE also
        # arrives pre-keyed (the FBX import), so it needs the stance guard
        # too; the assumption that zero rotation IS its stance holds for any
        # skeleton authored at rest, and a source it does not hold for was
        # ALREADY mis-characterized by the old code (at an arbitrary motion
        # frame), so this is strictly no worse there.
        target_char = _characterize_at_stance(cmds, mel, "retarget_target",
                                              target_slot_joints, characters,
                                              target_joints)
        source_char = _characterize_at_stance(cmds, mel, "retarget_source",
                                              source_slot_joints, characters,
                                              imported_joints)
        mel.eval('hikSetCharacterInput("%s", "%s")' % (target_char, source_char))

        # preserveOutsideKeys for the same reason as the BVH route above:
        # without it this bake erases every OTHER take's keys (#780).
        cmds.bakeResults(list(target_slot_joints.values()),
                         time=(target_start_frame, bake_end_frame),
                         sampleBy=1, simulation=True,
                         preserveOutsideKeys=True)
    except HandlerError:
        raise
    except Exception as exc:  # noqa: BLE001 - see the BVH route's identical
        # handler (#774 Task 4 fix) for the full rationale: a mid-
        # characterize HIK/mel failure must surface as a HandlerError like
        # every other refusal in this module, not escape as a raw
        # RuntimeError. The `finally` below still tears down regardless.
        raise HandlerError(
            "retargeting failed while characterizing/baking against "
            "HumanIK: %s" % exc,
            hint="this usually means one of the two skeletons' 15 required "
                 "HIK slots could not be assigned - check both joint sets "
                 "for duplicate or missing slot targets") from exc
    finally:
        _teardown_hik(cmds, mel, characters, ns, warnings)

    contained = _finish_take(cmds, root_long, target_joints,
                             target_slot_joints, name, bake_fps,
                             target_start_frame, bake_end_frame, kept, rest,
                             warnings)
    measures = _fold_measures(cmds, root_long, name, warnings)

    return {
        "clip": name,
        "root": root_long,
        "frames": num_bake_frames,
        "fps": bake_fps,
        "source_joints": len(imported_joints),
        "measures": measures,
        "padded_channels": contained["padded_channels"],
        "held_channels": contained["held_channels"],
        "back_filled": contained["back_filled"],
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def retarget_clip(params: Dict[str, Any]) -> Dict[str, Any]:
    path, ext, name, start, end, fps = _validate_common(params)
    root_param = params.get("root")
    if ext == ".bvh":
        return _retarget_bvh(path, root_param, name, start, end, fps)
    # fps is not passed on: _validate_common has already refused one for
    # this route, so the only value it could carry is None (#797 row 25).
    return _retarget_fbx(path, root_param, name, start, end)
