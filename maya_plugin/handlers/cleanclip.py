"""clean_clip: deterministic clip improvement with before/after numbers
(#774 Task 5).

#773 gave motion NUMBERS (measure_clip); this is the first tool that ACTS on
them. Two independent, always-numbered passes over an already-authored clip:

* `filter` - a Savitzky-Golay smooth (`mocapmath.smooth_track`) over every
  currently-keyed joint channel, sampled per frame across the clip's own
  range and re-keyed. Removes single-frame jitter (a popped key, mocap
  noise) without rounding off real motion - the same reason #774's own
  retarget bake never hand-rolled a moving average.
* `lock_contacts` - per contact joint, `motionmath.contact_runs` finds the
  SAME inferred plant windows `measure_clip` reports, pins each run to its
  own median world position (a `blend_weights` raised-cosine ease at the
  edges so the pin introduces no new velocity kink), and re-solves the
  2-bone leg chain through `rigging.solve_ik_chain` - the exact analytic
  solve `pose_ik` uses, extracted for this second caller rather than
  re-derived (#774 Task 5 review: extraction with zero behavior change,
  proven against tests/test_rigging.py's existing `TestPoseIk` suite).

Both passes are optional and independently gated (`filter`/`lock_contacts`,
wire-default true); disabling both is refused, not silently a no-op call.
`measure_clip` runs before and after - the same instrument #773 built, so
the "did this help" question always has a number, never a feeling. Any
metric that got WORSE is named in `warnings`, never turned into a failure:
this handler reports, the caller (or the eval gate) judges.
"""

from __future__ import annotations

import statistics
from typing import Any, Dict, List, Optional, Tuple

from ..dispatcher import HandlerError, require_known_keys
from . import clip, mocapmath, motionmath, rigging, session

CLEAN_CLIP_KEYS = ("root", "clip", "filter", "lock_contacts")
CLEAN_CLIP_SYNONYMS = {"name": "clip", "smoothing": "filter"}

# mocapmath.smooth_track's own floor (window must be odd, >= 5) - the
# gentlest legal Savitzky-Golay filter, and a reasonable default for a
# caller that just wants jitter gone without naming a window.
DEFAULT_FILTER_WINDOW = 5
# Swing-phase frames added on each side of a detected contact run for the
# blend_weights raised-cosine ease (see _run_contact_lock_pass) - clamped
# per-run to whatever margin the track actually has on that side, so a run
# flush against the clip's own start/end never asks for frames that do not
# exist.
DEFAULT_EDGE_FRAMES = 3


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


# ---------------------------------------------------------------------------
# Pure param validation - runs before any Maya import (proof: test_retarget.py
# ::TestCleanClipParamGate runs in a process with no `maya.cmds` at all).
# ---------------------------------------------------------------------------


def _validate_filter(value: Any) -> Tuple[bool, int]:
    """(enabled, window). `None`/`True` take the default window; `False`
    disables the pass; a dict overrides the window only."""
    if value is None or value is True:
        return True, DEFAULT_FILTER_WINDOW
    if value is False:
        return False, DEFAULT_FILTER_WINDOW
    if isinstance(value, dict):
        unknown = sorted(set(value) - {"window"})
        if unknown:
            raise HandlerError(
                "filter dict does not take %s"
                % ", ".join(repr(k) for k in unknown),
                hint="filter={'window': <odd int, at least 5>}")
        window = value.get("window", DEFAULT_FILTER_WINDOW)
        if (isinstance(window, bool) or not isinstance(window, int)
                or window < 5 or window % 2 == 0):
            raise HandlerError(
                "filter['window'] must be an odd whole number of at least "
                "5, got %r" % (window,),
                hint="e.g. filter={'window': 5} - mocapmath.smooth_track "
                     "needs a centered odd Savitzky-Golay window")
        return True, window
    raise HandlerError(
        "filter must be true, false, or {'window': <odd int, at least 5>}, "
        "got %r" % (value,),
        hint="true smooths every keyed channel with the default window "
             "(%d); false skips the filter pass" % DEFAULT_FILTER_WINDOW)


def _validate_lock_contacts(value: Any) -> Tuple[bool, Optional[List[str]]]:
    """(enabled, explicit joint list) - `None` for the list means "use the
    default two ankles" (resolved later, against the real rig)."""
    if value is None or value is True:
        return True, None
    if value is False:
        return False, None
    if isinstance(value, dict):
        unknown = sorted(set(value) - {"joints"})
        if unknown:
            raise HandlerError(
                "lock_contacts dict does not take %s"
                % ", ".join(repr(k) for k in unknown),
                hint="lock_contacts={'joints': ['L_ankle', 'R_ankle']}")
        joints = value.get("joints")
        if (not isinstance(joints, list) or not joints
                or not all(isinstance(j, str) and j.strip() for j in joints)):
            raise HandlerError(
                "lock_contacts['joints'] must be a non-empty list of joint "
                "name strings, got %r" % (joints,),
                hint="e.g. lock_contacts={'joints': ['L_ankle', 'R_ankle']}")
        return True, list(joints)
    raise HandlerError(
        "lock_contacts must be true, false, or {'joints': [...]}, got %r"
        % (value,),
        hint="true locks the default contact joints (this rig's two HIK "
             "Foot slots, mocapmath.SKELETON_HIK_MAP)")


# ---------------------------------------------------------------------------
# Maya-phase helpers
# ---------------------------------------------------------------------------


def _resolve_contact_joints(
    by_short: Dict[str, str], root_short: str, explicit: Optional[List[str]]
) -> Tuple[List[str], List[str]]:
    """(long joint names, warnings). An EXPLICIT list refuses an unknown
    joint (measure_clip's own `resolve` rule); the DEFAULT list skips a
    missing one with a warning instead - a non-biped rig should still get
    its filter pass, not a hard refusal over a pass it never asked to name."""
    warnings: List[str] = []
    if explicit is not None:
        out = []
        for entry in explicit:
            short = clip._short(entry)
            if short not in by_short:
                raise HandlerError(
                    "lock_contacts joint %r is not a joint under %s"
                    % (entry, root_short),
                    hint="joints here: %s" % ", ".join(sorted(by_short)))
            out.append(by_short[short])
        return out, warnings
    defaults = [mocapmath.SKELETON_HIK_MAP["LeftFoot"],
                mocapmath.SKELETON_HIK_MAP["RightFoot"]]
    out = []
    missing = []
    for short in defaults:
        if short in by_short:
            out.append(by_short[short])
        else:
            missing.append(short)
    if missing:
        warnings.append(
            "lock_contacts defaults to %s - %s not a joint under this "
            "root, so only %d of 2 default contact joint(s) could be "
            "resolved" % (" and ".join(repr(d) for d in defaults),
                          "is" if len(missing) == 1 else "are", len(out)))
    return out, warnings


def _keyed_plugs(cmds, joints: List[str]) -> List[str]:
    """Every joint rotate/translate plug a CLIP curve currently drives.
    `clip._joint_plugs` never lists a weight/custom channel, so skipping
    those happens by construction, not a special case here.

    The CLIP partition only (#798): the raw `type="animCurve"` query also
    returns the U-typed set-driven-key nodes, which are indexed by DRIVER
    VALUE rather than time. MEASURED (evals/clip_edges_probe_798): on such
    a plug `getAttr(time=f)` answers the driver's constant at every f, the
    re-key returns 0 every time, and the pass listed the channel as
    smoothed having changed nothing. #796 built the partition for exactly
    this; this was the one site that never asked it."""
    return sorted(clip.clip_curve_plugs(
        cmds, clip._anim_curves(cmds, clip._joint_plugs(joints))))


def _run_filter_pass(cmds, joints: List[str], start_frame: int,
                     end_frame: int, window: int,
                     warnings: List[str]) -> List[str]:
    """Sample every currently-keyed channel at every integer frame of the
    clip's own [start_frame, end_frame], Savitzky-Golay smooth it, and
    re-key the smoothed values - one animCurve per plug, and NEVER a frame
    outside this range, so a neighbouring clip sharing the same shared
    curve (#718) is untouched.

    Returns the channels whose re-key LANDED (#798, the #796 observed-
    writes rule at this module's own setKeyframe site): a plug locked
    after it was keyed samples fine and re-keys never - setKeyframe
    reports 0 - and counting it would report a smoothing that did not
    happen. A write that vanished is named, with its cause."""
    frames = list(range(start_frame, end_frame + 1))
    filtered: List[str] = []
    for plug in _keyed_plugs(cmds, joints):
        node, attr = plug.rsplit(".", 1)
        values = [float(cmds.getAttr(plug, time=f)) for f in frames]
        smoothed = mocapmath.smooth_track(values, window)
        lost = 0
        for frame, value in zip(frames, smoothed):
            if not clip.key_landed(cmds.setKeyframe(
                    node, attribute=attr, time=frame, value=value)):
                lost += 1
        if lost:
            warnings.append(clip._lost_write_note(
                "clean_clip's filter pass", plug, lost,
                clip.swallowed_by(cmds, plug)))
        if lost < len(frames):
            filtered.append(plug)
    return filtered


def _leg_chain(cmds, joints: List[str], root_long: str, ankle: str) -> List[str]:
    """The 2-bone chain above `ankle` - pose_ik's own "two joints up"
    default-start rule (rigging.pose_ik), so the contact-lock pass folds
    the knee exactly the way an explicit pose_ik call on this same ankle
    would."""
    path = rigging._chain_between(cmds, joints, root_long, ankle)
    if len(path) < 3:
        raise HandlerError(
            "%s hangs directly under the root - lock_contacts needs a "
            "2-bone chain (hip/knee/ankle) above it" % clip._short(ankle),
            hint="pass lock_contacts={'joints': [...]} naming a joint "
                 "deeper in the hierarchy, or disable lock_contacts on "
                 "this rig")
    return rigging._chain_between(cmds, joints, path[-3], ankle)


def _rig_height(cmds, joints: List[str], start_frame: int) -> float:
    """Same definition measure_clip uses: the hierarchy's own Y range at
    the clip's first sampled frame - the one scale every relative
    contact-detection threshold hangs off (motionmath.py's own rule)."""
    prev = cmds.currentTime(query=True)
    try:
        cmds.currentTime(start_frame)
        ys = [float(cmds.xform(j, query=True, worldSpace=True,
                               translation=True)[1]) for j in joints]
    finally:
        cmds.currentTime(prev)
    return max(ys) - min(ys)


def _sample_track(cmds, joint: str, start_frame: int,
                  end_frame: int) -> List[List[float]]:
    prev = cmds.currentTime(query=True)
    track: List[List[float]] = []
    try:
        for frame in range(start_frame, end_frame + 1):
            cmds.currentTime(frame)
            track.append([float(v) for v in cmds.xform(
                joint, query=True, worldSpace=True, translation=True)])
    finally:
        cmds.currentTime(prev)
    return track


def _run_contact_lock_pass(cmds, joints: List[str],
                           contact_joints: List[str],
                           chains: Dict[str, List[str]], start_frame: int,
                           end_frame: int, fps: float,
                           warnings: List[str]) -> None:
    """Per contact joint: find its own plant runs with the SAME function
    measure_clip judges by (motionmath.contact_runs), pin each run to the
    run's own median world position, and re-solve the 2-bone leg chain
    (rigging.solve_ik_chain) at every frame so the whole limb honours the
    pin, not just the ankle in isolation.

    `chains` is pre-resolved and pre-validated by the caller, BEFORE the
    checkpoint and the filter pass (#774 Task 5 review: a chain too shallow
    for `_leg_chain` to accept must refuse before anything mutates, not
    from inside this already-mutating pass) - this function only consumes
    it, never calls `_leg_chain` itself.

    The `blend_weights` ease is applied OUTSIDE the detected run, not at
    its own boundary samples: `blend_weights(n, edge)` is 0 exactly at
    index 0 and n-1 by construction (the whole point - a hard step there
    would itself be the discontinuity this pass exists to remove), and
    `measure_clip.max_slide` measures exactly those two endpoints. Easing
    AT the run's own edges would leave the boundary frames at their
    original (drifted) positions and the slide metric unchanged - so the
    locked window is widened by up to `DEFAULT_EDGE_FRAMES` swing-phase
    frames on each side (clamped to the track's own bounds), and the ramp
    spends its 0->1 rise in that margin: every frame of the RUN ITSELF
    then sits in blend_weights' flat, fully-anchored interior.
    """
    rig_height = _rig_height(cmds, joints, start_frame)
    n_track = end_frame - start_frame + 1
    for ankle in contact_joints:
        chain = chains[ankle]
        track = _sample_track(cmds, ankle, start_frame, end_frame)
        runs = motionmath.contact_runs(track, fps, rig_height)
        if not runs:
            warnings.append(
                "%s: no contact run detected - nothing to lock"
                % clip._short(ankle))
            continue
        for first, last in runs:
            anchor = [statistics.median(p[axis] for p in track[first:last + 1])
                     for axis in range(3)]
            edge = max(0, min(DEFAULT_EDGE_FRAMES, first, n_track - 1 - last))
            ext_first, ext_last = first - edge, last + edge
            weights = mocapmath.blend_weights(ext_last - ext_first + 1, edge)
            for idx, frame_local in enumerate(range(ext_first, ext_last + 1)):
                w = weights[idx]
                original = track[frame_local]
                target = [original[axis] * (1.0 - w) + anchor[axis] * w
                         for axis in range(3)]
                frame = start_frame + frame_local
                cmds.currentTime(frame)
                solved = rigging.solve_ik_chain(cmds, chain, target)
                warnings.extend(solved.get("warnings", []))
                for j in chain:
                    for attr in clip.ROTATE_ATTRS:
                        cmds.setKeyframe(j, attribute=attr, time=frame)
            warnings.append(
                "%s: locked contact run frames %d-%d (eased %d frame(s) "
                "each side) to its median plant position"
                % (clip._short(ankle), start_frame + first,
                   start_frame + last, edge))


def _regression_warnings(before: Dict[str, Any],
                         after: Dict[str, Any]) -> List[str]:
    """Name every metric that got WORSE. Never a failure here (the brief's
    "warn, not fail" rule) - the caller, or the eval gate, judges whether a
    regression matters."""
    out: List[str] = []
    for short, b in before.get("contacts", {}).items():
        a = after.get("contacts", {}).get(short)
        if a is not None and a["max_slide"] > b["max_slide"] + 1e-9:
            out.append(
                "%s's contact slide got WORSE after cleanup: %.6g -> %.6g"
                % (short, b["max_slide"], a["max_slide"]))
    for short, b in before.get("joints", {}).items():
        a = after.get("joints", {}).get(short)
        if a is not None and a["max_accel"] > b["max_accel"] + 1e-9:
            out.append(
                "%s's max acceleration got WORSE after cleanup: %.6g -> %.6g"
                % (short, b["max_accel"], a["max_accel"]))
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def clean_clip(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, CLEAN_CLIP_KEYS, "clean_clip", CLEAN_CLIP_SYNONYMS)
    filter_enabled, filter_window = _validate_filter(params.get("filter"))
    lock_enabled, lock_joints_param = _validate_lock_contacts(
        params.get("lock_contacts"))
    if not filter_enabled and not lock_enabled:
        raise HandlerError(
            "filter and lock_contacts are both false - clean_clip would do "
            "nothing",
            hint="enable at least one pass, or skip calling clean_clip")

    root_param = params.get("root")
    if not isinstance(root_param, str) or not root_param.strip():
        raise HandlerError(
            "missing required param 'root'",
            hint="the rig's root joint, e.g. what create_skeleton returned "
                 "as `root`")
    clip_name_param = params.get("clip")
    if clip_name_param is not None and not isinstance(clip_name_param, str):
        raise HandlerError("clip must be a string naming an existing clip")

    cmds = _cmds()
    root_long = rigging._require_joint(cmds, root_param)
    joints = rigging._hierarchy_joints(cmds, root_long)
    records = clip.clip_meta(cmds, root_long)
    if not records:
        raise HandlerError(
            "no clip exists on %s" % root_long,
            hint="author_clip or retarget_clip creates one; clean_clip "
                 "improves it")
    if clip_name_param is None and len(records) == 1:
        meta = records[0]
    else:
        meta = next((r for r in records if r["name"] == clip_name_param), None)
    if meta is None:
        raise HandlerError(
            "no clip named %r on %s (has: %s)"
            % (clip_name_param, clip._short(root_long),
               ", ".join(repr(r["name"]) for r in records)),
            hint="a rig carries several clips - pass the one to clean")
    name = meta["name"]
    fps = float(meta.get("fps", 30))
    start_frame = int(meta["start_frame"])
    end_frame = int(meta["end_frame"])

    # Resolved regardless of `lock_enabled`: before/after both measure the
    # SAME contact joints either way, so disabling the pass still reports a
    # comparable (unchanged, if genuinely untouched) slide number rather
    # than silently switching the contact set to measure_clip's own
    # leaves-only default.
    by_short = {clip._short(j): j for j in joints}
    warnings: List[str] = []
    contact_joints, resolve_warnings = _resolve_contact_joints(
        by_short, clip._short(root_long), lock_joints_param)
    if lock_enabled:
        warnings.extend(resolve_warnings)
        if not contact_joints:
            warnings.append(
                "lock_contacts requested but no contact joint could be "
                "resolved on this rig - the pass did not run")

    # #774 Task 5 review IMPORTANT: resolved and VALIDATED here, before the
    # checkpoint and before the filter pass mutates anything - a contact
    # joint too shallow for a 2-bone chain must refuse a clean call, not an
    # already-half-mutated one. `_run_contact_lock_pass` only consumes
    # `chains`; it never calls `_leg_chain` itself.
    chains: Dict[str, List[str]] = {}
    if lock_enabled and contact_joints:
        for ankle in contact_joints:
            chains[ankle] = _leg_chain(cmds, joints, root_long, ankle)

    before = clip.measure_clip({"root": root_long, "name": name,
                                "contact_joints": contact_joints or None})

    checkpoint = session.auto_checkpoint("clean_clip")

    passes: List[str] = []
    if filter_enabled:
        filtered = _run_filter_pass(cmds, joints, start_frame, end_frame,
                                    filter_window, warnings)
        passes.append("filter")
        if filtered:
            warnings.append(
                "filter: smoothed %d channel(s) with window=%d over "
                "frames %d-%d"
                % (len(filtered), filter_window, start_frame, end_frame))
        else:
            warnings.append("filter: no keyed channel found on this rig")

    if lock_enabled and contact_joints:
        _run_contact_lock_pass(cmds, joints, contact_joints, chains,
                               start_frame, end_frame, fps, warnings)
        passes.append("lock_contacts")

    cmds.currentTime(0)

    after = clip.measure_clip({"root": root_long, "name": name,
                               "contact_joints": contact_joints or None})
    warnings.extend(_regression_warnings(before, after))

    # De-duplicate while preserving order (clip.author_clip's own pattern) -
    # the contact-lock pass can repeat an identical solve warning once per
    # frame of a run.
    seen = set()
    deduplicated = []
    for w in warnings:
        if w not in seen:
            seen.add(w)
            deduplicated.append(w)

    return {
        "clip": name,
        "root": root_long,
        "passes": passes,
        "before": before,
        "after": after,
        "checkpoint_id": checkpoint["checkpoint_id"],
        "warnings": deduplicated,
    }
