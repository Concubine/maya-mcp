"""Animation clips, phase 6 of #602 (#695): author_clip, preview_clip,
delete_clip.

The currency is the phase-1 pose map, keyed: each key is {time_s, rotations,
blend_weights?, root_position?}. A skeleton carries a LIST of clips laid end
to end on one shared timeline (#718): author_clip APPENDS a new name after
the last clip, with one unowned gap frame between them. Re-authoring an
existing name cuts that clip's old range and re-appends it at the tail - no
other clip's motion moves, only its position in take order. Every clip on a
rig shares one fps; a second rate refuses (one file is one timeline). export
bakes each clip as its own named take, and delete_clip returns the skeleton
to static land. While a clip exists, static pose mutators REFUSE (the guards
below): curves own the channels, and a static write a curve overrides on the
next frame change is the quietest way to lie about a pose.

Every number is MEASURED (#636): duration_s is re-read from the curves after
keying, per-key displacement from vertices with the current time driven to
that key's frame.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from ..dispatcher import HandlerError
from . import capture, clipmath, naming, render, sculpt, sculpt_math, session, units

CLIP_ATTR = "mcp_clip"
REST_ATTR = "mcp_clip_rest"
NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
INTERPOLATIONS = {"linear": "linear", "smooth": "auto"}
ROTATE_ATTRS = ("rotateX", "rotateY", "rotateZ")
TRANSLATE_ATTRS = ("translateX", "translateY", "translateZ")
# Perception caps for preview_clip (Task 4). 16 matches the turntable's
# frame cap: past that a sheet is unreadable at message resolution.
MAX_PREVIEW_FRAMES = 16
DEFAULT_PREVIEW_RESOLUTION = 256


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _short(name: str) -> str:
    return name.split("|")[-1]


def _points(mesh_long: str) -> List[float]:
    """World-space vertex positions. Module-level so tests monkeypatch it
    (the blendshape._points precedent)."""
    return sculpt.vertex_positions(_cmds(), mesh_long)


def clip_meta(cmds, root_long: str) -> List[Dict[str, Any]]:
    """The clips this tool authored on `root_long`, in timeline order.

    An empty list when the rig carries none. Reads BOTH stored shapes: the
    #718 list, and the bare object every scene authored before it (read as
    one record starting at frame 0 - nothing migrates on disk). A value
    that fails to parse is reported as name only rather than crashing a
    guard.
    """
    if not cmds.attributeQuery(CLIP_ATTR, node=root_long, exists=True):
        return []
    raw = cmds.getAttr("%s.%s" % (root_long, CLIP_ATTR))
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return clipmath.normalized_records(
            {"name": str(raw)} if raw else None)
    return clipmath.normalized_records(parsed)


def _anim_curves(cmds, plugs: List[str]) -> Dict[str, List[str]]:
    """plug -> animCurve nodes driving it (source connections only)."""
    out: Dict[str, List[str]] = {}
    for plug in plugs:
        curves = cmds.listConnections(plug, source=True, destination=False,
                                      type="animCurve") or []
        if curves:
            out[plug] = list(curves)
    return out


def _joint_plugs(joints: List[str]) -> List[str]:
    return ["%s.%s" % (j, a) for j in joints
            for a in ROTATE_ATTRS + TRANSLATE_ATTRS]


def guard_static_pose(cmds, root_long: str, joints: List[str],
                      what: str) -> None:
    """Refuse a static pose write while curves drive the skeleton.

    Structural, not metadata: a hand-keyed channel fights a static write the
    same way a clip does. The clip name is named when metadata exists."""
    driven = _anim_curves(cmds, _joint_plugs(joints))
    if not driven:
        return
    records = clip_meta(cmds, root_long)
    label = ((" (clip%s %s)" % ("s" if len(records) > 1 else "",
                                ", ".join(repr(r["name"]) for r in records)))
             if records else "")
    raise HandlerError(
        "%s refuses while animation curves drive this skeleton%s - a static "
        "write here would be overridden on the next frame change"
        % (what, label),
        hint="author_clip re-authors the motion; delete_clip removes the "
             "curves and returns the skeleton to static posing")


def guard_static_weights(cmds, node: str, aliases: List[str],
                         what: str) -> None:
    """The same rule for blendshape weight channels."""
    driven = _anim_curves(cmds, ["%s.%s" % (node, a) for a in aliases])
    if driven:
        raise HandlerError(
            "%s refuses while animation curves drive %d weight channel(s) "
            "of %s (%s)" % (what, len(driven), node,
                            ", ".join(sorted(p.split(".")[-1]
                                             for p in driven))),
            hint="the clip owns these channels; delete_clip returns them to "
                 "static control")


def _weight_alias_map(cmds, meshes: List[str]) -> Dict[str, str]:
    """alias -> blendShape node, across every mesh bound to the skeleton.
    An alias on two nodes is ambiguous and refuses at USE, not here - the
    map records the collision instead of guessing."""
    from . import blendshape  # noqa: PLC0415 - avoid import cycle

    out: Dict[str, Any] = {}
    for mesh in meshes:
        shapes = cmds.listRelatives(mesh, shapes=True, fullPath=True) or []
        for shape in shapes:
            for node in cmds.ls(cmds.listHistory(
                    shape, pruneDagObjects=True) or [],
                    type="blendShape") or []:
                for alias in blendshape._aliases(cmds, node):
                    if alias in out and out[alias] != node:
                        out[alias] = HandlerError(
                            "blendshape target %r exists on both %s and %s"
                            % (alias, out[alias], node),
                            hint="rename one target so the key is "
                                 "unambiguous")
                    elif alias not in out:
                        out[alias] = node
    return out


def _resolve_weight_channels(alias_map: Dict[str, Any],
                             keys: List[Dict[str, Any]]) -> List[str]:
    used: List[str] = []
    for i, key in enumerate(keys):
        for alias in key["blend_weights"]:
            resolved = alias_map.get(alias)
            if resolved is None:
                raise HandlerError(
                    "keys[%d].blend_weights[%r] is not a blendshape target "
                    "on any mesh bound to this skeleton" % (i, alias),
                    hint="targets here: %s"
                         % (", ".join(sorted(alias_map)) or "none"))
            if isinstance(resolved, HandlerError):
                raise resolved
            if alias not in used:
                used.append(alias)
    return used


def _clips_elsewhere(cmds, root_long: str) -> List[str]:
    """Short names of OTHER skeleton roots carrying clips. export_fbx
    refuses such a scene (a take is a frame range over the whole file, so a
    multi-rig file needs a timeline policy of its own) - and that ceiling
    should be discovered while authoring, not at write time (#718)."""
    return [_short(j) for j in cmds.ls(type="joint", long=True) or []
            if j != root_long
            and cmds.attributeQuery(CLIP_ATTR, node=j, exists=True)]


def _rest_key(plug: str) -> str:
    """The rest record's key for a plug: short node name plus attribute.
    Long names carry the DAG path, which a reparent would invalidate."""
    node, attr = plug.rsplit(".", 1)
    return "%s.%s" % (_short(node), attr)


def _rest_map(cmds, root_long: str) -> Dict[str, float]:
    if not cmds.attributeQuery(REST_ATTR, node=root_long, exists=True):
        return {}
    try:
        value = json.loads(cmds.getAttr("%s.%s" % (root_long, REST_ATTR)))
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_rest(cmds, root_long: str, rest: Dict[str, float]) -> None:
    if not cmds.attributeQuery(REST_ATTR, node=root_long, exists=True):
        cmds.addAttr(root_long, longName=REST_ATTR, dataType="string")
    cmds.setAttr("%s.%s" % (root_long, REST_ATTR), json.dumps(rest),
                 type="string")


def _capture_rest(cmds, plug: str, rest: Dict[str, float]) -> None:
    """Record a channel's rest value the moment it becomes curve-driven.

    Read it later and a curve answers instead of the rest pose - which is
    why this is captured here, before the keying, and not derived on
    demand. A channel already driven (and already recorded) is left alone.
    """
    key = _rest_key(plug)
    if key in rest:
        return
    if cmds.listConnections(plug, source=True, destination=False,
                            type="animCurve"):
        return
    rest[key] = float(cmds.getAttr(plug))


def _rest_value(cmds, plug: str, rest: Dict[str, float],
                warnings: List[str]) -> float:
    """The value to pin a channel at outside the clips that declare it.

    Recorded at first touch (above). A scene authored before #718 has no
    record, so the value is inferred from the existing clip's FIRST key -
    for a self-contained clip that key IS its rest pose - and the
    inference is WARNED, never silent.
    """
    key = _rest_key(plug)
    if key in rest:
        return float(rest[key])
    times = cmds.keyframe(plug, query=True) or []
    if times:
        value = float(cmds.getAttr(plug, time=times[0]))
        warnings.append(
            "no rest value was recorded for %s (this scene predates the "
            "multi-clip metadata) - pinned at %g, its earliest keyed value"
            % (key, value))
        rest[key] = value
        return value
    value = float(cmds.getAttr(plug))
    rest[key] = value
    return value


def author_clip(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    from . import rigging  # noqa: PLC0415 - rigging imports clip for guards

    root_long = rigging._require_joint(cmds, params.get("root"))
    joints = rigging._hierarchy_joints(cmds, root_long)

    name = params.get("name")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise HandlerError(
            "name %r must be a plain identifier (letters, digits, "
            "underscore; not starting with a digit)" % (name,),
            hint="the name becomes the exported take name")
    fps = params.get("fps", 30)
    if (isinstance(fps, bool) or not isinstance(fps, int)
            or fps not in clipmath.FPS_UNITS):
        raise HandlerError(
            "fps must be one of %s"
            % ", ".join(str(k) for k in sorted(clipmath.FPS_UNITS)),
            hint="the frame rates Maya has native time units for; the "
                 "scene's time unit is set to match so keys land on frames")
    interpolation = params.get("interpolation", "linear")
    if interpolation not in INTERPOLATIONS:
        raise HandlerError(
            "unknown interpolation %r; one of: %s"
            % (interpolation, ", ".join(sorted(INTERPOLATIONS))),
            hint="'linear' for mechanical reads, 'smooth' (auto tangents) "
                 "for organic motion")
    loop = params.get("loop", False)
    if not isinstance(loop, bool):
        raise HandlerError("loop must be true or false",
                           hint="true validates that the last key closes "
                                "onto the first")

    keys = clipmath.validated_keys(params.get("keys"))

    # Resolve every name BEFORE the checkpoint - a bad call costs nothing.
    resolved_keys: List[Dict[str, Any]] = []
    for key in keys:
        resolved = dict(key)
        if key["rotations"]:
            resolved["rotations"] = rigging._resolve_rotations(
                cmds, joints, key["rotations"])
        resolved_keys.append(resolved)
    meshes = rigging._bound_meshes(cmds, set(joints))
    alias_map = _weight_alias_map(cmds, meshes)
    weight_channels = _resolve_weight_channels(alias_map, resolved_keys)

    if loop:
        violations = clipmath.loop_violations(resolved_keys[0],
                                              resolved_keys[-1])
        if violations:
            raise HandlerError(
                "loop=true but the clip does not close: %s"
                % "; ".join(violations[:4]),
                hint="a cycle whose last key differs from its first pops "
                     "on repeat in-engine; make the end key match the "
                     "start key, or drop loop")

    records = clip_meta(cmds, root_long)
    conflict = clipmath.fps_conflict(records, fps)
    if conflict:
        raise HandlerError(
            conflict,
            hint="delete_clip the clips at the other rate, or author this "
                 "one at theirs")

    weight_plugs = ["%s.%s" % (alias_map[a], a) for a in alias_map
                    if not isinstance(alias_map[a], HandlerError)]
    existing = _anim_curves(cmds, _joint_plugs(joints) + weight_plugs)
    if existing and not records:
        raise HandlerError(
            "this skeleton carries %d hand-authored animation curve "
            "channel(s) this tool did not author (e.g. %s)"
            % (len(existing), sorted(existing)[0]),
            hint="replacing hand-authored animation silently would destroy "
                 "work; delete_clip removes it if that is intended")

    warnings: List[str] = []
    fractional = clipmath.fractional_frame_times(
        [k["time_s"] for k in resolved_keys], fps)
    if fractional:
        warnings.append(
            "key time(s) %s land between frames at %d fps - the baked "
            "export samples integer frames, so these keys are between "
            "samples" % (", ".join("%g" % t for t in fractional), fps))
    if not meshes:
        warnings.append(
            "this skeleton moves no mesh (no skinned bind, no mesh parented "
            "under its joints) - the clip moves bare joints only; the "
            "displacement below is measured against nothing")
    elsewhere = _clips_elsewhere(cmds, root_long)
    if elsewhere:
        warnings.append(
            "another skeleton carries clips (%s) - export_fbx REFUSES a "
            "scene where two rigs carry clips, because a take is a frame "
            "range over the whole file; delete_clip the rig not being "
            "exported" % ", ".join(elsewhere))

    session.auto_checkpoint("author_clip")

    by_short: Dict[str, str] = {}
    for j in joints:
        by_short.setdefault(_short(j), j)

    def _rot_plugs(short: str) -> List[str]:
        long_name = by_short.get(short)
        if long_name is None:
            return []
        return ["%s.%s" % (long_name, a) for a in ROTATE_ATTRS]

    root_translate_plugs = ["%s.%s" % (root_long, a) for a in TRANSLATE_ATTRS]
    mine = {
        "joints": sorted({_short(j) for key in resolved_keys
                          for j in key["rotations"]}),
        "weight_channels": list(weight_channels),
        "root_position_used": any(k["root_position"] is not None
                                  for k in resolved_keys),
    }
    rest = _rest_map(cmds, root_long)
    for short in mine["joints"]:
        for plug in _rot_plugs(short):
            _capture_rest(cmds, plug, rest)
    if mine["root_position_used"]:
        for plug in root_translate_plugs:
            _capture_rest(cmds, plug, rest)
    for alias in mine["weight_channels"]:
        # By rule, not by capture: weights-all-zero IS the reset (phase 5).
        rest.setdefault(_rest_key("%s.%s" % (alias_map[alias], alias)), 0.0)

    # Re-authoring a name RE-APPENDS it at the tail (#718 decision 4): its
    # old range is cut, and no other clip's motion moves. Take ORDER in the
    # file changes; each take is still independently named, which is all a
    # consumer reads.
    replaced, kept = clipmath.drop_record(records, name)
    if replaced is not None:
        for plug in sorted(set(_joint_plugs(joints) + weight_plugs)):
            cmds.cutKey(plug, time=(replaced["start_frame"],
                                    replaced["end_frame"]), clear=True)

    start_frame = clipmath.next_start_frame(kept)

    prev_unit = cmds.currentUnit(query=True, time=True)
    unit = clipmath.FPS_UNITS[fps]
    if prev_unit != unit:
        cmds.currentUnit(time=unit)
        warnings.append("scene time unit changed %r -> %r so a frame is "
                        "1/%d s" % (prev_unit, unit, fps))

    keyed: List[tuple] = []   # (node, attr) pairs, for tangents
    for key in resolved_keys:
        frame = start_frame + key["time_s"] * fps
        for joint, triple in key["rotations"].items():
            for attr, value in zip(ROTATE_ATTRS, triple):
                cmds.setKeyframe(joint, attribute=attr, time=frame,
                                 value=units.degrees_to_ui(cmds, value))
                keyed.append((joint, attr))
        if key["root_position"] is not None:
            cmds.xform(root_long, worldSpace=True,
                       translation=key["root_position"])
            local = [float(v) for v in cmds.xform(
                root_long, query=True, translation=True)]
            for attr, value in zip(TRANSLATE_ATTRS, local):
                cmds.setKeyframe(root_long, attribute=attr, time=frame,
                                 value=value)
                keyed.append((root_long, attr))
        for alias, value in key["blend_weights"].items():
            cmds.setKeyframe(alias_map[alias], attribute=alias, time=frame,
                             value=value)
            keyed.append((alias_map[alias], alias))

    # MEASURED end frame (#636): the latest key at or after this clip's
    # start, re-read from the curves. Nothing above start_frame can belong
    # to another clip - this clip is always appended at the tail, and a
    # re-author cut its old range first.
    end_frame = start_frame
    for node, attr in set(keyed):
        times = cmds.keyframe("%s.%s" % (node, attr), query=True) or []
        later = [t for t in times if t >= start_frame]
        if later:
            end_frame = max(end_frame, max(later))
    end_frame = int(round(end_frame))
    duration_s = (end_frame - start_frame) / float(fps)
    frames = end_frame - start_frame + 1
    if replaced is not None:
        warnings.append(
            "re-authored clip %r: vacated frames %d-%d and re-appended it "
            "at %d-%d - no other clip's motion changed"
            % (name, replaced["start_frame"], replaced["end_frame"],
               start_frame, end_frame))

    tangent = INTERPOLATIONS[interpolation]
    for node, attr in sorted(set(keyed)):
        cmds.keyTangent(node, attribute=attr, edit=True,
                        inTangentType=tangent, outTangentType=tangent)

    # --- the self-contained rule (#718) --------------------------------
    # All clips share ONE curve per channel, so a channel this clip never
    # mentions would hold whatever a neighbour left on it - forwards from
    # the previous clip's last key, and BACKWARDS from a later clip's
    # first key. Both are pinned here, at rest, and both are reported.
    theirs = clipmath.channel_union(kept)
    padded_channels: List[str] = []
    back_filled_channels: List[str] = []

    def _pin(plug: str, frames: List[int]) -> None:
        node, attr = plug.rsplit(".", 1)
        value = _rest_value(cmds, plug, rest, warnings)
        for frame in frames:
            cmds.setKeyframe(node, attribute=attr, time=frame, value=value)
        cmds.keyTangent(node, attribute=attr, edit=True,
                        inTangentType=tangent, outTangentType=tangent)

    mine_frames = [start_frame, end_frame]
    for short in theirs["joints"]:
        if short in mine["joints"]:
            continue
        plugs = _rot_plugs(short)
        if not plugs:
            warnings.append(
                "a clip declares joint %r, which is not under this root any "
                "more - it cannot be pinned at rest, so takes that do not "
                "declare it may inherit a neighbour's value" % short)
            continue
        for plug in plugs:
            _pin(plug, mine_frames)
        padded_channels.append(short)
    for alias in theirs["weight_channels"]:
        if alias in mine["weight_channels"]:
            continue
        node = alias_map.get(alias)
        if node is None or isinstance(node, HandlerError):
            warnings.append(
                "a clip declares weight channel %r, which no mesh bound to "
                "this skeleton carries any more - it cannot be pinned at "
                "rest" % alias)
            continue
        _pin("%s.%s" % (node, alias), mine_frames)
        padded_channels.append(alias)
    if theirs["root_position_used"] and not mine["root_position_used"]:
        for plug in root_translate_plugs:
            _pin(plug, mine_frames)
        padded_channels.append("root_position")

    # BACKWARDS contamination: a curve holds its FIRST key's value
    # backwards in time, so a channel this clip introduces would rewrite
    # every earlier clip's pose for it. Pinning at rest across their
    # ranges RESTORES what each of them measured when it was authored.
    their_frames = [f for r in kept
                    for f in (r["start_frame"], r["end_frame"])]
    if their_frames:
        for short in mine["joints"]:
            if short in theirs["joints"]:
                continue
            for plug in _rot_plugs(short):
                _pin(plug, their_frames)
            back_filled_channels.append(short)
        for alias in mine["weight_channels"]:
            if alias in theirs["weight_channels"]:
                continue
            _pin("%s.%s" % (alias_map[alias], alias), their_frames)
            back_filled_channels.append(alias)
        if mine["root_position_used"] and not theirs["root_position_used"]:
            for plug in root_translate_plugs:
                _pin(plug, their_frames)
            back_filled_channels.append("root_position")
    back_filled = {
        "clips": [r["name"] for r in kept] if back_filled_channels else [],
        "channels": back_filled_channels,
    }
    if back_filled_channels:
        warnings.append(
            "pinned %d channel(s) (%s) at rest across %s so their motion is "
            "unchanged by this clip"
            % (len(back_filled_channels), ", ".join(back_filled_channels),
               ", ".join(back_filled["clips"])))
    _write_rest(cmds, root_long, rest)

    new_record = {
        "name": name, "fps": fps, "start_frame": start_frame,
        "end_frame": end_frame, "duration_s": duration_s, "loop": loop,
        "interpolation": interpolation,
        "joints": sorted({_short(j) for key in resolved_keys
                          for j in key["rotations"]}),
        "weight_channels": weight_channels,
        "root_position_used": any(k["root_position"] is not None
                                  for k in resolved_keys),
    }
    all_records = kept + [new_record]
    span_end = max(r["end_frame"] for r in all_records)
    # The playback range is the FULL span, so opening the .ma and scrubbing
    # shows every clip - not just the one authored last.
    cmds.playbackOptions(edit=True, minTime=0, maxTime=span_end,
                         animationStartTime=0, animationEndTime=span_end)

    # MEASURED per key: drive the time to each key's frame and read the
    # bound meshes against the evaluated FIRST key. Key 0 is 0 by
    # construction; a clip whose every later key is ~0 warns below.
    per_key: List[Dict[str, Any]] = []
    baselines: Dict[str, List[float]] = {}
    worst = 0.0
    cmds.currentTime(start_frame)
    for mesh in meshes:
        baselines[mesh] = _points(mesh)
    for key in resolved_keys:
        cmds.currentTime(start_frame + key["time_s"] * fps)
        disp = 0.0
        for mesh in meshes:
            disp = max(disp, sculpt_math.max_displacement(
                baselines[mesh], _points(mesh)))
        per_key.append({"time_s": key["time_s"], "max_displacement": disp})
        worst = max(worst, disp)
    cmds.currentTime(0)
    if meshes:
        extent = max(sculpt_math.bbox_extent(b) for b in baselines.values())
        if extent > 0 and worst < extent * 1e-2:
            warnings.append(
                "the clip's largest measured displacement is %.4g against "
                "a mesh of size %.4g - near-zero motion usually means the "
                "keys landed on joints that own no vertices"
                % (worst, extent))

    if not cmds.attributeQuery(CLIP_ATTR, node=root_long, exists=True):
        cmds.addAttr(root_long, longName=CLIP_ATTR, dataType="string")
    cmds.setAttr("%s.%s" % (root_long, CLIP_ATTR), json.dumps(all_records),
                 type="string")

    return {
        "root": root_long,
        "clip": name,
        "fps": fps,
        "duration_s": duration_s,
        "frames": frames,
        "keyed_joints": len({j for key in resolved_keys
                             for j in key["rotations"]}),
        "keyed_weight_channels": weight_channels,
        "root_position_keyed": any(k["root_position"] is not None
                                   for k in resolved_keys),
        "interpolation": interpolation,
        "loop": loop,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "clips": [r["name"] for r in all_records],
        "padded_channels": padded_channels,
        "back_filled": back_filled,
        "replaced": name if replaced is not None else None,
        "per_key": per_key,
        "warnings": warnings,
    }


def delete_clip(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    from . import rigging  # noqa: PLC0415

    root_long = rigging._require_joint(cmds, params.get("root"))
    joints = rigging._hierarchy_joints(cmds, root_long)
    records = clip_meta(cmds, root_long)
    meshes = rigging._bound_meshes(cmds, set(joints))
    alias_map = _weight_alias_map(cmds, meshes)
    weight_plugs = ["%s.%s" % (node, a) for a, node in alias_map.items()
                    if not isinstance(node, HandlerError)]
    driven = _anim_curves(cmds, _joint_plugs(joints) + weight_plugs)
    if not driven and not records:
        raise HandlerError(
            "no clip exists on %s" % root_long,
            hint="author_clip creates one; this tool removes it")

    warnings: List[str] = []
    if not records and driven:
        warnings.append(
            "no clip metadata on %s - deleting %d hand-authored curve "
            "channel(s)" % (_short(root_long), len(driven)))

    session.auto_checkpoint("delete_clip")
    before = {m: _points(m) for m in meshes}

    doomed = sorted({c for curves in driven.values() for c in curves})
    if doomed:
        cmds.delete(*doomed)
    # Weights back to 0 (weights-all-0 IS the reset, the P5 rule), then the
    # skeleton back to bind - reset_pose's exact logic inline so this call
    # holds ONE checkpoint.
    for plug in weight_plugs:
        if plug in driven:
            cmds.setAttr(plug, 0.0)
    poses = cmds.dagPose(root_long, query=True, bindPose=True) or []
    if poses:
        cmds.dagPose(poses[0], restore=True, g=True)
        if len(poses) > 1:
            warnings.append("%d bind poses exist; restored %s"
                            % (len(poses), poses[0]))
    else:
        for joint in joints:
            cmds.setAttr(joint + ".rotate", 0.0, 0.0, 0.0)
        warnings.append(
            "no bind pose exists (nothing is bound); rotations zeroed, "
            "which is the create_skeleton rest pose")
    if cmds.attributeQuery(CLIP_ATTR, node=root_long, exists=True):
        cmds.deleteAttr("%s.%s" % (root_long, CLIP_ATTR))

    max_disp = 0.0
    for mesh in meshes:
        max_disp = max(max_disp, sculpt_math.max_displacement(
            before[mesh], _points(mesh)))
    return {
        "root": root_long,
        "clip": records[0]["name"] if records else None,
        "deleted_curves": len(doomed),
        "max_displacement": max_disp,
        "warnings": warnings,
    }


def preview_clip(params: Dict[str, Any]) -> Dict[str, Any]:
    """A contact sheet of the clip's frames - motion judged the way
    everything here is judged, from pixels, with NO playblast dependency.

    The camera is placed once, at frame 0's framing, and HELD: motion must
    read against a fixed frame, and a camera chasing the subject would hide
    root motion entirely. Perception: no checkpoint, current time restored.
    """
    cmds = _cmds()
    from . import rigging  # noqa: PLC0415

    root_long = rigging._require_joint(cmds, params.get("root"))
    records = clip_meta(cmds, root_long)
    if not records or not records[0].get("name"):
        raise HandlerError(
            "no clip exists on %s" % root_long,
            hint="author_clip creates one; preview_clip renders it")
    meta = records[0]
    name = params.get("name")
    if name != meta["name"]:
        raise HandlerError(
            "the live clip is %r, not %r" % (meta["name"], name),
            hint="pass the clip's own name - previewing a stale assumption "
                 "judges the wrong motion")
    fps = int(meta.get("fps", 30))
    duration_frames = int(round(float(meta.get("duration_s", 0.0)) * fps))
    if duration_frames <= 0:
        raise HandlerError("the clip has zero duration",
                           hint="re-author it; this is a broken metadata "
                                "state, not a render problem")

    angle = params.get("angle") or "three_quarter"
    if angle not in capture.VALID_ANGLES:
        raise HandlerError("unknown angle %r" % angle,
                           hint="valid angles: %s"
                                % ", ".join(capture.VALID_ANGLES))
    every_nth = params.get("every_nth")
    if every_nth is None:
        # Simulate the ACTUAL frame list per candidate stride, not just the
        # unpadded range's length - the forced append of the last frame
        # (below) can push a stride that "fits" by the naive formula over
        # the cap when duration_frames isn't a multiple of the stride.
        every_nth = 1
        while True:
            candidate = list(range(0, duration_frames + 1, every_nth))
            if candidate[-1] != duration_frames:
                candidate.append(duration_frames)
            if len(candidate) <= MAX_PREVIEW_FRAMES:
                break
            every_nth += 1
    elif (isinstance(every_nth, bool) or not isinstance(every_nth, int)
            or every_nth < 1):
        raise HandlerError("every_nth must be an integer >= 1",
                           hint="omit it for the densest sheet that fits")
    frames = list(range(0, duration_frames + 1, every_nth))
    if frames[-1] != duration_frames:
        frames.append(duration_frames)   # the last frame always shows
    if len(frames) > MAX_PREVIEW_FRAMES:
        raise HandlerError(
            "every_nth=%d yields %d frames; the cap is %d frames per sheet"
            % (every_nth, len(frames), MAX_PREVIEW_FRAMES),
            hint="raise every_nth, or omit it to auto-fit")

    joints = rigging._hierarchy_joints(cmds, root_long)
    meshes = rigging._bound_meshes(cmds, set(joints))
    if not meshes:
        raise HandlerError(
            "this skeleton moves no mesh - neither a skinned bind nor a "
            "mesh parented under one of its joints; bare joints render "
            "nothing",
            hint="bind_skin for a deforming rig, or parent the chunks under "
                 "their joints for a rigid-body rig; the preview frames "
                 "whatever the skeleton moves")

    # Reassert the CLIP's own time unit (mirrors author_clip): another clip
    # authored since - on this skeleton or any other - may have left the
    # scene-global unit at a different fps, and the frame numbers below only
    # mean what the reported time_s claims if the unit matches this clip.
    # Done last, immediately before the shots that consume it: every check
    # above must pass before this call is allowed to mutate the scene.
    cmds.currentUnit(time=clipmath.FPS_UNITS[fps])

    render_params = {
        "renderer": params.get("renderer", "hw2"),
        "resolution": params.get("resolution",
                                 DEFAULT_PREVIEW_RESOLUTION),
        "samples": params.get("samples", 1),
        "zoom": params.get("zoom", 1.0),
    }
    shots = []
    for i, frame in enumerate(frames):
        shots.append({
            "label": "t=%.2fs" % (frame / float(fps)),
            "angle": angle,
            "isolate": None,
            "frame_on": meshes,
            "time": frame,
            "reuse_camera": i > 0,
        })
    result = render._run_shots(cmds, shots, render_params)
    result["clip"] = meta["name"]
    result["fps"] = fps
    result["frames"] = [{"frame": f, "time_s": f / float(fps)}
                        for f in frames]
    return result


preview_clip.no_undo_chunk = True
