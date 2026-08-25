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
from typing import Any, Dict, List, Optional, Tuple

from ..dispatcher import HandlerError
from . import (capture, clipmath, naming, render, rigmath, sculpt,
              sculpt_math, session, units)

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
    should be discovered while authoring, not at write time (#718).

    Keyed on clip_meta parsing to a non-empty record list, NOT on the
    attribute existing (#731): an empty or hollow mcp_clip attr carries no
    clips and must not warn."""
    return [_short(j) for j in cmds.ls(type="joint", long=True) or []
            if j != root_long and clip_meta(cmds, j)]


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


def _bind_rotations(cmds, root_long: str,
                    joints: List[str]) -> Dict[str, Optional[List[float]]]:
    """short joint name -> the BIND pose's `.rotate` triple (UI angle
    units), or None when it cannot be determined for that joint. {} when
    nothing is bound (no dagPose). Reads the SAME pose node delete_clip
    restores (#732)."""
    poses = cmds.dagPose(root_long, query=True, bindPose=True) or []
    if not poses:
        return {}
    pose = poses[0]
    out: Dict[str, Optional[List[float]]] = {}
    for j in joints:
        out[_short(j)] = None
        try:
            plugs = cmds.listConnections(j + ".message", source=False,
                                         destination=True, plugs=True,
                                         type="dagPose") or []
            idx = None
            for p in plugs:
                node, attr = p.split(".", 1)
                if node == pose and attr.startswith("members["):
                    idx = int(attr[len("members["):-1])
                    break
            if idx is None:
                continue
            xform = list(cmds.getAttr("%s.xformMatrix[%d]" % (pose, idx)))
            orient = [units.ui_to_degrees(cmds, v)
                      for v in cmds.getAttr(j + ".jointOrient")[0]]
            axis = [units.ui_to_degrees(cmds, v)
                    for v in cmds.getAttr(j + ".rotateAxis")[0]]
            deg = rigmath.bind_rotation_deg(
                xform, orient, axis, int(cmds.getAttr(j + ".rotateOrder")))
            if deg is not None:
                out[_short(j)] = [units.degrees_to_ui(cmds, v) for v in deg]
        except Exception:
            pass  # unreadable entry -> current-pose fallback for this joint
    return out


def _capture_rest(cmds, plug: str, rest: Dict[str, float],
                  value: Optional[float] = None) -> None:
    """Record a channel's rest value the moment it becomes curve-driven.

    Read it later and a curve answers instead of the rest pose - which is
    why this is captured here, before the keying, and not derived on
    demand. A channel already driven (and already recorded) is left alone.

    `value` overrides the current-pose read: the BIND rotation when the
    dagPose decomposition knows it (#732).
    """
    key = _rest_key(plug)
    if key in rest:
        return
    if cmds.listConnections(plug, source=True, destination=False,
                            type="animCurve"):
        return
    rest[key] = float(cmds.getAttr(plug)) if value is None else float(value)


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
    for action in session.stop_idle_ipr(cmds):
        warnings.append(
            action + " before keyframe work - an idle IPR re-renders on "
            "every scene mutation and can wedge a keyframe call for "
            "minutes (#721)")
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

    # #718 review Fix 3: a short name can name TWO joints under one root
    # (clip metadata is short-name-keyed by long-standing convention, so
    # that ambiguity has to be caught here, not avoided by changing the
    # metadata shape). by_short collects every match; a single match
    # resolves normally, and 0 or 2+ matches are both "cannot resolve" -
    # the difference is only in what the warning says.
    by_short: Dict[str, List[str]] = {}
    for j in joints:
        by_short.setdefault(_short(j), []).append(j)

    def _rot_plugs(short: str) -> List[str]:
        """Rotate plugs for a short joint name, or [] when it does not
        resolve to exactly one joint under this root right now - vanished,
        or ambiguous between two same-named joints. Never guesses."""
        matches = by_short.get(short) or []
        if len(matches) != 1:
            return []
        return ["%s.%s" % (matches[0], a) for a in ROTATE_ATTRS]

    def _pin_plugs(short: str) -> Tuple[List[str], str]:
        """The same resolution as `_rot_plugs`, but paired with the
        warning naming WHY a channel could not be pinned - used by the
        padding/back-fill passes below, which must say so. (The
        rest-capture pass above just skips silently: there is nothing yet
        to warn about - a channel that never gets pinned by anyone never
        needed a rest value.)"""
        matches = by_short.get(short) or []
        if not matches:
            return [], (
                "a clip declares joint %r, which is not under this root "
                "any more - it cannot be pinned at rest, so takes that do "
                "not declare it may inherit a neighbour's value" % short)
        if len(matches) > 1:
            return [], (
                "joint short name %r is ambiguous under this root (%s) - "
                "it cannot be pinned at rest, so takes that do not declare "
                "it may inherit a neighbour's value"
                % (short, ", ".join(sorted(matches))))
        return ["%s.%s" % (matches[0], a) for a in ROTATE_ATTRS], ""

    root_translate_plugs = ["%s.%s" % (root_long, a) for a in TRANSLATE_ATTRS]
    mine = {
        "joints": sorted({_short(j) for key in resolved_keys
                          for j in key["rotations"]}),
        "weight_channels": list(weight_channels),
        "root_position_used": any(k["root_position"] is not None
                                  for k in resolved_keys),
    }
    rest = _rest_map(cmds, root_long)
    rest_before = set(rest)
    bind = _bind_rotations(cmds, root_long, joints)
    for short in mine["joints"]:
        triple = bind.get(short)
        for plug, bind_v in zip(_rot_plugs(short),
                                triple if triple is not None
                                else (None, None, None)):
            _capture_rest(cmds, plug, rest, value=bind_v)
    if mine["root_position_used"]:
        for plug in root_translate_plugs:
            _capture_rest(cmds, plug, rest)
    for alias in mine["weight_channels"]:
        # By rule, not by capture: weights-all-zero IS the reset (phase 5).
        rest.setdefault(_rest_key("%s.%s" % (alias_map[alias], alias)), 0.0)

    # #732: rest is the BIND pose where the dagPose can be decomposed
    # (rigmath.bind_rotation_deg strips jointOrient/rotateAxis). The
    # warning now fires only when the rig is measurably POSED AWAY from
    # that bind pose at first capture - an imported rig whose bind pose
    # legitimately carries rotation stays silent. Joints with no readable
    # bind entry keep the pre-#732 behavior (capture current, warn on
    # non-zero, since a create_skeleton rig reads zero at rest) - both
    # warnings are summarized, never one line per joint. Root translation
    # is excluded (a rig legitimately sits anywhere) and weight channels
    # are excluded (recorded 0.0 by rule, never captured).
    newly_captured = {k: v for k, v in rest.items() if k not in rest_before}
    posed_away: List[str] = []
    unknown_bind: List[str] = []
    for short in sorted({k.rsplit(".", 1)[0] for k in newly_captured
                         if k.rsplit(".", 1)[1] in ROTATE_ATTRS}):
        plugs = _rot_plugs(short)
        if not plugs:
            continue
        triple = bind.get(short)
        if triple is not None:
            current = [float(cmds.getAttr(p)) for p in plugs]
            if any(abs(c - b) > 1e-4 for c, b in zip(current, triple)):
                posed_away.append(short)
        elif any(abs(newly_captured.get("%s.%s" % (short, a), 0.0)) > 1e-9
                 for a in ROTATE_ATTRS):
            unknown_bind.append(short)
    if posed_away:
        warnings.append(
            "%d joint(s) are posed away from the bind pose (e.g. %s) - "
            "rest pins use the BIND pose, so boundary frames will not hold "
            "the current pose" % (len(posed_away),
                                  ", ".join(posed_away[:3])))
    if unknown_bind:
        warnings.append(
            "rest was captured from this rig's CURRENT pose for %d "
            "joint(s) with no readable bind pose (e.g. %s) - a non-zero "
            "value here usually means the rig was posed, e.g. via "
            "pose_skeleton, before its first clip"
            % (len(unknown_bind), ", ".join(unknown_bind[:3])))

    # Re-authoring a name RE-APPENDS it at the tail (#718 decision 4): its
    # old range is cut, and no other clip's motion moves. Take ORDER in the
    # file changes; each take is still independently named, which is all a
    # consumer reads.
    replaced, kept = clipmath.drop_record(records, name)
    if replaced is not None:
        for plug in sorted(set(_joint_plugs(joints) + weight_plugs)):
            # #718 final review Fix 2: widened past `end_frame` by
            # GAP_FRAMES. `end_frame` is `int(round(measured_end))`
            # (#636), which rounds DOWN whenever the last key's fractional
            # part is below 0.5 - a key at end_frame+0.4 (e.g.
            # measured_end=14.4, end_frame=14) then sits outside
            # (start_frame, end_frame) and survives this cut, holding the
            # REPLACED version's value and polluting the re-authored take
            # between end_frame and that stray key. Widening is free: no
            # take's range ever includes the unowned gap frame
            # (clipmath.GAP_FRAMES), so nothing legitimate lives there
            # either.
            cmds.cutKey(plug, time=(replaced["start_frame"],
                                    replaced["end_frame"]
                                    + clipmath.GAP_FRAMES), clear=True)

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
    measured_end = start_frame
    for node, attr in set(keyed):
        times = cmds.keyframe("%s.%s" % (node, attr), query=True) or []
        later = [t for t in times if t >= start_frame]
        if later:
            measured_end = max(measured_end, max(later))
    end_frame = int(round(measured_end))
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
        # #718 review Fix 2: scoped to this clip's OWN frames. Clips share
        # a curve now, so an unscoped keyTangent would retangent every key
        # on the curve, including an earlier clip's - silently changing
        # its motion between its own keys, which this feature must never
        # do.
        # #718 review wave 2 Fix 3: the upper bound is `measured_end`, the
        # UNROUNDED keyed maximum, not the rounded `end_frame`. A
        # fractional last key (e.g. 42.01 with end_frame=42) sits outside
        # (start_frame, end_frame) and would silently keep Maya's default
        # tangent instead of this clip's interpolation. The lower bound
        # stays start_frame, which is exact by construction (frames are
        # integers and every clip starts on one).
        cmds.keyTangent(node, attribute=attr,
                        time=(start_frame, measured_end),
                        edit=True, inTangentType=tangent,
                        outTangentType=tangent)

    # --- the self-contained rule (#718) --------------------------------
    # All clips share ONE curve per channel, so a channel this clip never
    # mentions would hold whatever a neighbour left on it - forwards from
    # the previous clip's last key, and BACKWARDS from a later clip's
    # first key. Both are pinned here, and both are reported.
    theirs = clipmath.channel_union(kept)
    # #718 final review Fix 3: `mine`'s setdefault (above) only covers
    # weight channels THIS clip declares. A weight channel declared solely
    # by an earlier (possibly pre-#718 legacy) clip needs the same
    # by-rule 0.0 - without it, a legacy clip's weight channel falls
    # through to `_rest_value`'s curve-inference fallback and gets pinned
    # at whatever that legacy clip happened to key FIRST (e.g. a blink
    # held open at 1.0), which is a visibly wrong pose in the exported
    # take. Weights-all-zero IS the reset (phase 5), for a legacy channel
    # exactly as much as for one this clip itself introduces.
    for alias in theirs["weight_channels"]:
        node = alias_map.get(alias)
        if node is not None and not isinstance(node, HandlerError):
            rest.setdefault(_rest_key("%s.%s" % (node, alias)), 0.0)
    # #718 final review Fix 1: pad over `theirs` UNION `mine`, not
    # `theirs` alone, whenever an earlier clip exists on this rig. The
    # excuse the wave-1 comment gave for skipping `mine \ theirs` - "a
    # channel only this clip touches has no other clip's keys on its
    # curve to bleed in" - is FALSE: the BACK-FILL pass below writes rest
    # keys onto exactly that curve, at every earlier clip's own boundary
    # frames, and the nearest of those can sit as little as GAP_FRAMES+1
    # frames before this clip's start. So a channel this clip introduces
    # still needs its own boundary pins - not because a neighbour
    # declares it, but because THIS call's own back-fill puts foreign
    # keys on that curve outside this clip's range. Gated on `kept` being
    # non-empty: a rig's first clip has no earlier clip to back-fill
    # against, so its own channels are left exactly as authored - no new
    # keys, no auto-tangent perturbation.
    pad_joints = theirs["joints"]
    pad_weight_channels = theirs["weight_channels"]
    pad_root_position = theirs["root_position_used"]
    if kept:
        pad_joints = sorted(set(pad_joints) | set(mine["joints"]))
        pad_weight_channels = sorted(
            set(pad_weight_channels) | set(mine["weight_channels"]))
        pad_root_position = pad_root_position or mine["root_position_used"]
    padded_channels: List[str] = []
    held_channels: List[str] = []
    back_filled_channels: List[str] = []

    def _pin(plug: str, frames: List[int], value: float) -> None:
        node, attr = plug.rsplit(".", 1)
        for frame in frames:
            cmds.setKeyframe(node, attribute=attr, time=frame, value=value)
            # #718 review Fix 2: a pinned key is scoped to its own frame,
            # and FLAT - not the clip's interpolation. A pin is not
            # authored motion; flat is the honest type, and it keeps a
            # pinned span genuinely flat regardless of what interpolation
            # this clip was authored with.
            cmds.keyTangent(node, attribute=attr, time=(frame, frame),
                            edit=True, inTangentType="flat",
                            outTangentType="flat")

    # #718 review wave 2 Fix 1+2 (one helper, not three copies): the pin
    # VALUE, not just the condition. A missing boundary is pinned at rest
    # ONLY when this clip never keyed the plug at all anywhere in its own
    # [start_frame, end_frame] - the isolation case. When it DID key the
    # plug somewhere in its own range (a sparse declared channel, or a
    # fractional-time key that rounds short of the boundary), pinning rest
    # there would invent motion the clip never authored: rewrite a flat
    # hold into a rise-and-fall, or rewrite an authored final pose into a
    # rest pose 0.01 frames later. So the missing start pins at the value
    # the plug held at its OWN earliest key (min(own)), and the missing
    # end pins at the value it held at its OWN latest key (max(own)) -
    # exactly what a lone clip's curve would already hold there, read the
    # same way `_rest_value` reads any evaluated value: `getAttr(time=t)`.
    # #718 review wave 3 Fix: `own`'s upper bound is `measured_end` (the
    # UNROUNDED keyed maximum), not `end_frame`. `end_frame` is
    # int(round(measured_end)), which rounds DOWN whenever the last key's
    # fractional part is below 0.5 - a key at frame 14.4 with end_frame 14
    # would sit outside [start_frame, end_frame] and get filtered out of
    # `own` entirely. That silently swaps this clip's OWN final value for
    # whichever earlier value happened to survive the filter (its first
    # key, if the channel has no other keys in range), flattening the
    # authored motion; or, if the fractional key was the plug's ONLY key
    # in range, empties `own` altogether and misclassifies a channel this
    # clip genuinely animates as "rest". `measured_end` is already this
    # clip's true keyed span (computed above, per #636) - reuse it rather
    # than re-deriving the same quantity.
    def _pad_boundaries(plug: str) -> str:
        """Pin `plug`'s missing boundary frame(s) of THIS clip's own
        [start_frame, end_frame]. Returns "held", "rest", or "" (nothing
        was missing)."""
        times = set(cmds.keyframe(plug, query=True) or [])
        missing = [f for f in (start_frame, end_frame)
                  if float(f) not in times]
        if not missing:
            return ""
        own = sorted(t for t in times
                     if start_frame <= t <= max(end_frame, measured_end))
        if not own:
            _pin(plug, missing, _rest_value(cmds, plug, rest, warnings))
            return "rest"
        for frame in missing:
            source = own[0] if frame == start_frame else own[-1]
            _pin(plug, [frame], float(cmds.getAttr(plug, time=source)))
        return "held"

    # #718 review Fix 1 (wave 1): pad by BOUNDARY-KEY PRESENCE, not by
    # mention. A clip may declare a channel in `mine` (it names it on SOME
    # key) while never keying it at its OWN first/last frame - `mine`
    # alone can't tell whether the boundary is actually covered, so
    # skipping a channel just because it's in `mine` let a neighbour's
    # pose bleed across the boundary the clip never keyed.
    #
    # The set iterated is `pad_joints`/`pad_weight_channels`/
    # `pad_root_position` (computed above, final review Fix 1) - `theirs`
    # union `mine` when an earlier clip exists, `theirs` alone otherwise -
    # not `theirs` by itself: see that block for why a channel this clip
    # alone introduces still needs its own pins.
    for short in pad_joints:
        plugs, warning = _pin_plugs(short)
        if not plugs:
            warnings.append(warning)
            continue
        kinds = {kind for kind in (_pad_boundaries(p) for p in plugs) if kind}
        if "held" in kinds:
            held_channels.append(short)
        elif "rest" in kinds:
            padded_channels.append(short)
    for alias in pad_weight_channels:
        node = alias_map.get(alias)
        if node is None or isinstance(node, HandlerError):
            warnings.append(
                "a clip declares weight channel %r, which no mesh bound to "
                "this skeleton carries any more - it cannot be pinned at "
                "rest" % alias)
            continue
        kind = _pad_boundaries("%s.%s" % (node, alias))
        if kind == "held":
            held_channels.append(alias)
        elif kind == "rest":
            padded_channels.append(alias)
    if pad_root_position:
        kinds = {kind for kind in (_pad_boundaries(p)
                                   for p in root_translate_plugs) if kind}
        if "held" in kinds:
            held_channels.append("root_position")
        elif "rest" in kinds:
            padded_channels.append("root_position")
    if padded_channels:
        warnings.append(
            "pinned %d channel(s) (%s) at rest at this clip's own boundary "
            "frame(s) - it never keys them anywhere in its own range"
            % (len(padded_channels), ", ".join(padded_channels)))
    if held_channels:
        warnings.append(
            "pinned %d channel(s) (%s) at this clip's OWN held value at "
            "its boundary frame(s) - it keys them elsewhere in its own "
            "range, so the boundary is pinned at what that range would "
            "hold there anyway, not at rest"
            % (len(held_channels), ", ".join(held_channels)))

    # BACKWARDS contamination: a curve holds its FIRST key's value
    # backwards in time, so a channel this clip introduces would rewrite
    # every earlier clip's pose for it. Pinning at rest across their
    # ranges RESTORES what each of them measured when it was authored -
    # this clip has no keys of its own inside an EARLIER clip's range (by
    # construction: clips are always appended at the tail), so there is no
    # "own held value" to prefer here - rest is always right.
    their_frames = [f for r in kept
                    for f in (r["start_frame"], r["end_frame"])]
    if their_frames:
        for short in mine["joints"]:
            if short in theirs["joints"]:
                continue
            # Fix 3's guard applies here too: mine["joints"] normally can't
            # be ambiguous (name resolution already refused it), but a key
            # naming a joint by its FULL long name bypasses that check, so
            # an ambiguous short name can still reach here.
            plugs, warning = _pin_plugs(short)
            if not plugs:
                warnings.append(warning)
                continue
            for plug in plugs:
                _pin(plug, their_frames, _rest_value(cmds, plug, rest,
                                                      warnings))
            back_filled_channels.append(short)
        for alias in mine["weight_channels"]:
            if alias in theirs["weight_channels"]:
                continue
            plug = "%s.%s" % (alias_map[alias], alias)
            _pin(plug, their_frames, _rest_value(cmds, plug, rest, warnings))
            back_filled_channels.append(alias)
        if mine["root_position_used"] and not theirs["root_position_used"]:
            for plug in root_translate_plugs:
                _pin(plug, their_frames, _rest_value(cmds, plug, rest,
                                                      warnings))
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

    # De-duplicate warnings while preserving order and distinctness.
    seen = set()
    deduplicated = []
    for w in warnings:
        if w not in seen:
            seen.add(w)
            deduplicated.append(w)
    warnings = deduplicated

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
        "held_channels": held_channels,
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

    name = params.get("name")
    if name is not None and not isinstance(name, str):
        raise HandlerError("name must be a string, or omitted to delete "
                           "every clip on this rig")
    doomed_record = None
    kept: List[Dict[str, Any]] = []
    if name is not None:
        doomed_record, kept = clipmath.drop_record(records, name)
        if doomed_record is None:
            raise HandlerError(
                "no clip named %r on %s (has: %s)"
                % (name, _short(root_long),
                   ", ".join(repr(r["name"]) for r in records) or "none"),
                hint="omit `name` to delete every clip and return the "
                     "skeleton to static posing")

    warnings: List[str] = []
    if not records and driven:
        warnings.append(
            "no clip metadata on %s - deleting %d hand-authored curve "
            "channel(s)" % (_short(root_long), len(driven)))

    session.auto_checkpoint("delete_clip")
    before = {m: _points(m) for m in meshes}

    deleted_curves = 0
    reaped_channels: List[str] = []
    if kept:
        # ONE clip out of several: cut its range only. Gaps are NOT
        # re-packed (#718 decision 5) - a take is an explicit range, so a
        # gap costs nothing, and re-packing would move keys the caller did
        # not touch.
        for plug in sorted(driven):
            # #718 final review Fix 2 (consistency, not a defect here): the
            # same widening as author_clip's re-author cut. A fractional
            # straggler past `end_frame` already lands in unowned gap
            # space after a delete - no clip claims it either way - so
            # this is hygiene: keeping delete_clip's cut shape identical
            # to author_clip's rather than leaving a stray orphaned key
            # nobody can see.
            cmds.cutKey(plug, time=(doomed_record["start_frame"],
                                    doomed_record["end_frame"]
                                    + clipmath.GAP_FRAMES), clear=True)
        # #730: the doomed clip's back-fill wrote rest pins for its own
        # channels into the SURVIVING clips' ranges. A channel no survivor
        # declares now carries only those pins - dead weight every take
        # would bake. Reap the WHOLE curve, but only for channels the
        # doomed record itself declared and no survivor does; a channel a
        # survivor still uses is never touched, range or no range.
        survivors = clipmath.channel_union(kept)
        by_short: Dict[str, List[str]] = {}
        for j in joints:
            by_short.setdefault(_short(j), []).append(j)
        orphan_plugs: List[str] = []
        for short in doomed_record.get("joints", []):
            if short in survivors["joints"]:
                continue
            matches = by_short.get(short) or []
            if len(matches) != 1:
                continue  # vanished or ambiguous: never guess (_rot_plugs rule)
            orphan_plugs.extend("%s.%s" % (matches[0], a)
                                for a in ROTATE_ATTRS)
            reaped_channels.append(short)
        for alias in doomed_record.get("weight_channels", []):
            if alias in survivors["weight_channels"]:
                continue
            node = alias_map.get(alias)
            if node is None or isinstance(node, HandlerError):
                continue
            orphan_plugs.append("%s.%s" % (node, alias))
            reaped_channels.append(alias)
        if (doomed_record.get("root_position_used")
                and not survivors["root_position_used"]):
            orphan_plugs.extend("%s.%s" % (root_long, a)
                                for a in TRANSLATE_ATTRS)
            reaped_channels.append("root_position")
        orphan_curves = sorted({
            c for plug in orphan_plugs
            for c in cmds.listConnections(plug, source=True,
                                          destination=False,
                                          type="animCurve") or []})
        # Invariant this gate relies on: under #718's self-contained rule,
        # every channel a clip declares stays curve-driven outside the
        # doomed range too (a neighbour's rest pin keeps it keyed there), so
        # an orphaned channel always has a curve to find here. If that ever
        # breaks, reaped_channels could fill while orphan_curves stays empty
        # and this warning silently never fires.
        if orphan_curves:
            # mcp_clip_rest entries for these channels are NOT pruned here -
            # they deliberately survive the reap. Re-introducing the channel
            # in a later clip reuses the recorded rest value; do not "fix"
            # this by deleting the rest record too.
            cmds.delete(*orphan_curves)
            warnings.append(
                "removed the whole curve(s) of %d channel(s) (%s) no "
                "surviving clip declares - they carried only rest pins "
                "inside the surviving clips' ranges (#730)"
                % (len(reaped_channels), ", ".join(reaped_channels)))
        remaining = _anim_curves(cmds, _joint_plugs(joints) + weight_plugs)
        deleted_curves = len({c for curves in driven.values() for c in curves}
                             - {c for curves in remaining.values()
                                for c in curves})
        cmds.setAttr("%s.%s" % (root_long, CLIP_ATTR), json.dumps(kept),
                     type="string")
        span_end = max(r["end_frame"] for r in kept)
        cmds.playbackOptions(edit=True, minTime=0, maxTime=span_end,
                             animationStartTime=0, animationEndTime=span_end)
    else:
        if name is not None:
            warnings.append(
                "%r was the last clip on this rig - the full teardown ran: "
                "weight channels zeroed, bind pose restored" % name)
        doomed = sorted({c for curves in driven.values() for c in curves})
        if doomed:
            cmds.delete(*doomed)
        deleted_curves = len(doomed)
        # Weights back to 0 (weights-all-0 IS the reset, the P5 rule), then
        # the skeleton back to bind - reset_pose's exact logic inline so
        # this call holds ONE checkpoint.
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
        for attr in (CLIP_ATTR, REST_ATTR):
            if cmds.attributeQuery(attr, node=root_long, exists=True):
                cmds.deleteAttr("%s.%s" % (root_long, attr))

    max_disp = 0.0
    for mesh in meshes:
        max_disp = max(max_disp, sculpt_math.max_displacement(
            before[mesh], _points(mesh)))
    return {
        "root": root_long,
        "clip": (doomed_record["name"] if doomed_record
                 else (records[0]["name"] if records else None)),
        "clips": [r["name"] for r in kept],
        "deleted_curves": deleted_curves,
        "reaped_channels": reaped_channels,
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
    if not records:
        raise HandlerError(
            "no clip exists on %s" % root_long,
            hint="author_clip creates one; preview_clip renders it")
    name = params.get("name")
    meta = next((r for r in records if r["name"] == name), None)
    if meta is None:
        raise HandlerError(
            "no clip named %r on %s (has: %s)"
            % (name, _short(root_long),
               ", ".join(repr(r["name"]) for r in records)),
            hint="a rig carries several clips now - pass the one to judge")

    fps = int(meta.get("fps", 30))
    start_frame = int(meta["start_frame"])
    duration_frames = int(meta["end_frame"]) - start_frame
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

    # Hygiene only after every refusal above: a refused preview_clip must
    # mutate nothing (matches author_clip's discipline).
    warnings: List[str] = []
    for action in session.stop_idle_ipr(cmds):
        warnings.append(
            action + " before rendering clip frames - an idle IPR "
            "re-renders on every scene change and can wedge the render "
            "and time scrubbing (#721)")

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
    for i, offset in enumerate(frames):
        shots.append({
            "label": "t=%.2fs" % (offset / float(fps)),
            "angle": angle,
            "isolate": None,
            "frame_on": meshes,
            "time": start_frame + offset,
            "reuse_camera": i > 0,
        })
    result = render._run_shots(cmds, shots, render_params)
    result["warnings"] = warnings + result.get("warnings", [])
    result["clip"] = meta["name"]
    result["fps"] = fps
    result["start_frame"] = start_frame
    result["end_frame"] = start_frame + duration_frames
    result["frames"] = [{"frame": start_frame + f, "time_s": f / float(fps)}
                        for f in frames]
    return result


preview_clip.no_undo_chunk = True
