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
to static land - except for set-driven keys, which are rig setup rather than
clip motion, so they are left standing and reported (#796). The other side
of that: author_clip refuses a channel IT DECLARES that a set-driven key
or a corrective feeds (setKeyframe on one returns 0 and creates nothing -
MEASURED - so the clip would ship declaring a channel it never keyed), and
ignores one it does not declare. Any OTHER connection (a pairBlend, an
anim layer) is named in `warnings` and keyed anyway: nothing has measured
that a key fails to land through one, and refusing there would stop a
keyed-and-constrained rig that authors clips today (#796). What such a
write DID is then observed rather than assumed - setKeyframe returns the
number of keys it set, so a channel whose key never appeared is named,
uncounted, and absent from `mcp_clip` (#796 round 5).
While a clip exists, static pose mutators REFUSE (the guards
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

from ..dispatcher import HandlerError, refuse_inert, require_known_keys
from . import (capture, clipmath, naming, render, rigmath, sculpt,
              sculpt_math, session, units)

CLIP_ATTR = "mcp_clip"
REST_ATTR = "mcp_clip_rest"
NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
INTERPOLATIONS = {"linear": "linear", "smooth": "auto"}
ROTATE_ATTRS = ("rotateX", "rotateY", "rotateZ")
# How the #730 reap names a channel whose name belongs to two kinds at once
# (a 'jaw' joint and a 'jaw' blendShape alias) - see the reap in delete_clip.
_KIND_LABEL = {"joint": "joint", "weight": "blend weight",
               "root": "root translation"}
TRANSLATE_ATTRS = ("translateX", "translateY", "translateZ")
# #796 review round 6 D: `bakeResults` with no `-attribute` flag writes
# every KEYABLE channel of the nodes it is aimed at, scale among them - so
# retarget_clip's guard has to be able to ask about the scale triple the
# same way it asks about the other two, compound included: whatever the
# rotate triple's parent arm is worth, the scale triple's is worth the
# same (see _connected_channels on what #796's live gate measured there).
# Nothing on the author side writes scale, and this widens nothing
# author_clip asks.
SCALE_ATTRS = ("scaleX", "scaleY", "scaleZ")
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


# Driven-key curves: input is a DRIVER attribute, not time. They feed a plug
# through a connection exactly like a poseInterpolator does, and setKeyframe
# on such a plug silently no-ops the same way (#771 measured the
# poseInterpolator case; the U-typed curves share the connection shape), so
# the classifier below must NOT lump them in with time-based clip curves.
_DRIVEN_KEY_TYPES = ("animCurveUU", "animCurveUL", "animCurveUA",
                     "animCurveUT")


def partition_driven_keys(cmds, curves) -> Tuple[List[str], List[str]]:
    """(clip curves, set-driven-key curves), deduplicated and sorted.

    Takes either a flat iterable of curve nodes or the plug -> curves map
    _anim_curves returns.

    listConnections(type="animCurve") matches DERIVED types, so the U-typed
    driven-key nodes come back from that query alongside the time-based clip
    curves - which is how delete_clip's teardown came to delete the caller's
    rig setup as a side effect of "remove my clip" (#796). Every site that
    acts on that query's result has to split it again, and three sites
    splitting independently is how the wrong one ships (#771 review), so
    they all split HERE.
    """
    flat = ([c for cs in curves.values() for c in cs]
            if isinstance(curves, dict) else list(curves))
    clip_curves, sdk_curves = set(), set()
    for curve in flat:
        bucket = (sdk_curves if cmds.nodeType(curve) in _DRIVEN_KEY_TYPES
                  else clip_curves)
        bucket.add(curve)
    return sorted(clip_curves), sorted(sdk_curves)


def stale_scale_curves(cmds, joints: List[str]
                       ) -> Tuple[List[str], List[str]]:
    """(identity scale curves to reap, scale plugs left standing).

    #810: retarget_clip's bake used to key SCALE on every slot joint
    (`bakeResults` with no `-attribute` flag writes every keyable channel)
    - 45 constant-1.0 curves per retarget on the humanoid, MEASURED - and
    no clip tool walks scale, so delete_clip left them and then refused
    "no clip exists" on a rig still keyed, while every later clip's export
    carried them as 15 "Lcl Scaling" nodes per take. The bake is aimed
    now; this reaps what earlier bakes left.

    Reaped ONLY when every key is exactly 1.0: that is the bake's
    signature, and deleting it changes nothing a viewer could see. A scale
    curve carrying any other value is someone's squash-and-stretch and is
    named, never touched; a driven key (U-typed) is rig setup and is
    excluded before the values are even read.
    """
    driven = clip_curve_plugs(cmds, _anim_curves(
        cmds, ["%s.%s" % (j, a) for j in joints for a in SCALE_ATTRS]))
    identity: List[str] = []
    kept: List[str] = []
    for plug, curves in sorted(driven.items()):
        values = cmds.keyframe(plug, query=True, valueChange=True) or []
        if values and all(abs(float(v) - 1.0) < 1e-9 for v in values):
            identity.extend(curves)
        else:
            kept.append(plug)
    return sorted(set(identity)), kept


def clip_curve_plugs(cmds, driven: Dict[str, List[str]]
                     ) -> Dict[str, List[str]]:
    """`driven` (an _anim_curves map) with the driven-key curves filtered
    out and the plugs left with nothing dropped.

    The plug-level face of partition_driven_keys, for the sites that act on
    a PLUG rather than on a curve node: an SDK curve is indexed by DRIVER
    VALUE, not time, so a time-range cutKey against one is meaningless at
    best and silently destroys driver keys that fall in the numeric range at
    worst, and a setAttr on such a plug raises (it is connection-fed).
    """
    out: Dict[str, List[str]] = {}
    for plug, curves in driven.items():
        kept, _ = partition_driven_keys(cmds, curves)
        if kept:
            out[plug] = kept
    return out


def driven_weight_source(cmds, plug: str):
    """(source plug, kind) for the connection feeding `plug`, or (None, None).

    kind: "clip" (a time-based animCurve - this module's own currency),
    "driven_key" (a U-typed curve reading a driver attribute), "corrective"
    (a poseInterpolator output, #771), or "other" (anim layers' blend
    nodes, pairBlend, unitConversion, expressions...). One classifier for
    every guard that must answer "who owns this weight" - three sites
    classifying independently is how the wrong hint ships (#771 review).
    """
    from . import orphans  # noqa: PLC0415 - keep this module's import list flat
    srcs = cmds.listConnections(plug, source=True, destination=False,
                                plugs=True) or []
    if not srcs:
        return None, None
    src = srcs[0]
    src_type = cmds.nodeType(src.split(".")[0])
    if src_type in _DRIVEN_KEY_TYPES:
        return src, "driven_key"
    if src_type.startswith("animCurve"):
        return src, "clip"
    if src_type == "poseInterpolator":
        return src, "corrective"
    if src_type in orphans.TEXTURE_TYPES:
        # #804: a file/ramp/noise/bump2d feeding a shader slot. The one
        # classifier grows a kind rather than material.py telling the
        # caller a texture is "a constraint, expression or blend node".
        return src, "texture"
    if src_type in orphans.SWEEPABLE_TYPES:
        # A reverse (or a place2dTexture) is a texture's front end ONLY when
        # it feeds a shader: the same node type drives joint channels in an
        # IK/FK switch, and that rig must keep the generic diagnosis (review
        # catch - the wrong-hint class this classifier exists to end).
        from . import material  # noqa: PLC0415 - material imports plugwrite imports clip
        try:
            if cmds.nodeType(plug.split(".")[0]) in material.SHADERS:
                return src, "texture"
        except Exception:  # noqa: BLE001 - an owner that cannot answer is not a shader
            pass
    return src, "other"


def refuse_driven_weight(what: str, alias: str, src: str, kind: str) -> None:
    """The kind-specific refusal for a weight some connection owns.

    A wrong diagnosis is worse than a refusal: telling a caller to
    delete_objects an interpolator that does not exist (because the real
    source was a unitConversion or an anim-layer blend node) sends them
    to delete the wrong node or loop on a dead-end hint.
    """
    if kind == "corrective":
        raise HandlerError(
            "weight %r is a corrective, driven by %s - %s cannot write a "
            "connected plug (measured: setKeyframe on one returns 0 and "
            "creates no curve; setAttr raises)" % (alias, src, what),
            hint="pose the driver joint instead (that IS the corrective's "
                 "control), or delete_objects the interpolator to return "
                 "the weight to static control")
    if kind == "driven_key":
        raise HandlerError(
            "weight %r is driven by a set-driven key (%s) - %s cannot "
            "write a connection-fed plug" % (alias, src, what),
            hint="remove the driven key (delete its curve node) to return "
                 "the weight to static control")
    raise HandlerError(
        "weight %r is driven by %s - %s cannot write a connection-fed "
        "plug" % (alias, src, what),
        hint="disconnect that source to return the weight to static "
             "control; this tool refuses rather than silently writing a "
             "value the connection would immediately override")


# The connection kinds a key MEASURABLY cannot land on: #771 measured the
# poseInterpolator case (setKeyframe returns 0 and creates no curve) and the
# U-typed driven-key curves feed a plug through the same connection shape.
#
# "other" is deliberately NOT here (#796 review round 4 B). A pairBlend is
# what Maya inserts the moment a plug is both keyed AND constrained - this
# module's own `_curve_behind_a_blend` documents that - and setKeyframe then
# lands on the animCurve behind it, which is how author_clip re-authored
# such a rig before #796. Refusing "other" turned a working keyed+
# constrained rig into one that can author no clip at all: a REGRESSION
# dressed as a fix. Whether the key really lands through a pairBlend is a
# live question; until it is measured, the choice that cannot break a
# working rig is to key it and NAME what sits in the way.
UNKEYABLE_KINDS = ("driven_key", "corrective")


def refuse_driven_channel(what: str, plug: str, src: str, kind: str) -> None:
    """The kind-specific refusal for a JOINT channel some connection owns.

    The skeleton-side face of `refuse_driven_weight`, sharing its one
    classifier (`driven_weight_source`) and differing only in what it can
    truthfully say: a weight's fix is "delete_objects the interpolator",
    while a joint channel's is "pose the driver" - and, since #796,
    delete_clip explicitly does NOT remove a driven key, so a hint that
    named it would send the caller to a tool that refuses them with "no
    clip exists".

    Only the kinds in UNKEYABLE_KINDS refuse. Any other kind RETURNS
    without raising, so every caller can hand this function whatever it
    classified and no second site can quietly widen the refusal - see that
    constant for why "other" must not.
    """
    if kind == "driven_key":
        raise HandlerError(
            "joint channel %s is driven by a set-driven key (%s) - %s "
            "cannot key a connection-fed plug (measured: setKeyframe on "
            "one returns 0 and creates no curve), so the clip would ship "
            "declaring a channel it never keyed" % (plug, src, what),
            hint="delete_clip does NOT remove a driven key (#796: it is "
                 "rig setup, not clip motion) - pose the DRIVER attribute "
                 "instead, which is what actually controls this channel, "
                 "or delete that curve node deliberately if the channel "
                 "must carry clip motion; a driven key on a channel this "
                 "clip does not declare does not block anything")
    if kind == "corrective":
        raise HandlerError(
            "joint channel %s is driven by a corrective interpolator (%s) "
            "- %s cannot key a connection-fed plug (measured: setKeyframe "
            "on one returns 0 and creates no curve)" % (plug, src, what),
            hint="delete_objects the interpolator to return this channel "
                 "to keyable control, or key a channel it does not drive")
    # Every other kind: no refusal, deliberately (UNKEYABLE_KINDS). The
    # caller warns instead, through `_driven_channel_note`.


def _joint_plugs(joints: List[str]) -> List[str]:
    return ["%s.%s" % (j, a) for j in joints
            for a in ROTATE_ATTRS + TRANSLATE_ATTRS]


# rotateX -> rotate, translateY -> translate. A connection made on the
# COMPOUND is invisible to a query on its child: listConnections('j.rotateX')
# reports nothing when the source landed on 'j.rotate'. Maya's rotation anim
# layers connect exactly that way (animBlendNodeAdditiveRotation.output ->
# .rotate), while pairBlend connects per-child - so any code that asks "who
# owns this child plug" has to ask about the parent too (#796 review
# defect 4).
_COMPOUND_OF = dict([(a, "rotate") for a in ROTATE_ATTRS]
                    + [(a, "translate") for a in TRANSLATE_ATTRS]
                    + [(a, "scale") for a in SCALE_ATTRS])


def _parent_plug(plug: str) -> Optional[str]:
    node, _, attr = plug.rpartition(".")
    parent = _COMPOUND_OF.get(attr)
    return "%s.%s" % (node, parent) if parent else None


def _connected_channels(cmds, node: str, attrs: Tuple[str, ...],
                        compound: Optional[str]
                        ) -> List[Tuple[str, str, str, str]]:
    """[(attr, plug, source, kind)] for the channels of `node` a
    connection feeds. `attr` is the channel that cannot be written; `plug`
    is where the connection actually LANDS - the child itself, or the
    compound when that is what carries it.

    Child-first, always. Maya reports a child's connection at the compound
    too, so asking the compound first would blame a sibling's driven key
    for a channel that is perfectly free. The compound is asked SECOND, and
    only when no child answered - a defensive arm, not a described
    mechanism: #796's live gate measured a rotation anim layer on Maya 2027
    connecting the CHILD (`<layer>.outputY` -> `.rotateY`) with the
    `.rotate` compound query returning nothing, so the layered case this
    arm was added for (#796 review defect 4) did not reproduce here. It
    stays because a compound-borne connection costs one query to rule out
    and is invisible to a child-only walk if some rig or Maya version does
    make one. ONE primitive for both faces of the question - author_clip's
    per-channel refusal and delete_clip's write guard - because two copies
    of this rule is how the wrong one ships (#771 review).

    `compound` may be None, for a group of channels that HAS no compound:
    a joint's user-defined keyable attributes, which `bakeResults` writes
    alongside the triples (#796 review round 6 D). Each is then asked on
    its own and no parent is asked about, which is the whole truth for a
    scalar plug.
    """
    found: List[Tuple[str, str, str, str]] = []
    for attr in attrs:
        plug = "%s.%s" % (node, attr)
        src, kind = driven_weight_source(cmds, plug)
        if kind is not None:
            found.append((attr, plug, src, kind))
    if found or compound is None:
        return found
    plug = "%s.%s" % (node, compound)
    src, kind = driven_weight_source(cmds, plug)
    if kind is None:
        return []
    return [(a, plug, src, kind) for a in attrs]


# Nodes a curve can hide behind. pairBlend is what Maya inserts the moment a
# plug is both keyed and constrained; animBlendNodeBase is ABSTRACT, so
# nodeType reports a derived name (animBlendNodeAdditiveDL, ...) and the
# match below has to be a prefix one.
_INTERMEDIARY_TYPES = ("pairBlend", "blendWeighted", "unitConversion")
_INTERMEDIARY_PREFIX = "animBlendNode"
# A depth of 4 covers a stacked anim-layer chain with a unitConversion at
# each end; past that this is not a shape a static-pose guard can diagnose.
_BLEND_WALK_DEPTH = 4


def _is_intermediary(node_type: str) -> bool:
    return (node_type in _INTERMEDIARY_TYPES
            or node_type.startswith(_INTERMEDIARY_PREFIX))


def _curve_behind_a_blend(cmds, plug: str) -> Tuple[Optional[str],
                                                    Optional[str]]:
    """(animCurve, the node it hides behind) for a curve that reaches `plug`
    THROUGH an intermediary node, or (None, None).

    Maya inserts a pairBlend when a plug is both keyed and constrained, and
    anim layers insert an animBlendNode*; the curve then reaches the plug
    through that node and _anim_curves' direct query returns NOTHING. The
    guard passes, the static write lands, and the curve overrides it on the
    next evaluation - precisely the silent wrongness the guard exists to
    prevent (#796 defect 2).

    The PARENT COMPOUND is asked when the child plug has no source of its
    own (#796 review defect 4). Both wirings this walk knows about were
    MEASURED on Maya 2027 by #796's live gate, and both start from the
    child: a pairBlend connects per child (outRotateX -> rotateX), and so
    does a rotation anim layer (`<layer>.outputY` -> `.rotateY`, with the
    `.rotate` compound query answering nothing). The compound arm was
    written for a layered wiring that did not reproduce, and is kept as
    cheap insurance rather than as a claim: a query on a child plug does
    not report a connection made on its parent, so if any rig does carry
    one, a child-only walk would never start.

    Deliberately NOT folded into _anim_curves: that query is the TEARDOWN's
    blast radius. If it started returning curves reached through a blend
    node, delete_clip would delete a curve feeding a node it does not
    understand and leave that node behind. Teardown stays direct-only; only
    the guard looks wider.

    Bounded, cycle-guarded, and a node that cannot answer degrades to "no
    curve found" rather than crashing a guard (the _outside_wearers idiom).
    """
    curve, via, had_source = _walk_to_a_curve(cmds, plug)
    if curve is not None or had_source:
        # The child's own source is the story, curve or no curve. Maya
        # reports a child's connection at the compound as well, so retrying
        # the parent here would only re-walk the same subgraph.
        return curve, via
    parent = _parent_plug(plug)
    if parent is None:
        return None, None
    # The compound is asked ONLY when the connection really lands on it -
    # `_connected_channels` is the one place that rule lives, and asking it
    # here is what keeps this function from spreading a SIBLING's source
    # onto a free axis (#796 review round 6 C). A compound reports its
    # children's connections too, so a pairBlend on tip.rotateX made this
    # walk answer "driven" for tip.rotateY and tip.rotateZ as well: the
    # replace-cut then stepped around two channels with no source and no
    # keys at all, and `_skip_cut_note` blamed them by name - the exact
    # wrong-channel report protocol.md promises cannot happen.
    node, _, attr = plug.rpartition(".")
    group = [a for a, c in _COMPOUND_OF.items() if c == _COMPOUND_OF[attr]]
    try:
        landing = _connected_channels(cmds, node, tuple(sorted(group)),
                                      _COMPOUND_OF[attr])
    except Exception:  # noqa: BLE001 - cannot tell: nothing found
        return None, None
    if not any(at == parent for _a, at, _s, _k in landing):
        return None, None
    curve, via, _ = _walk_to_a_curve(cmds, parent)
    return curve, via


def _walk_to_a_curve(cmds, plug: str) -> Tuple[Optional[str],
                                               Optional[str], bool]:
    """_curve_behind_a_blend for ONE plug, child or compound.

    Third element: whether `plug` had a source at all - which is what tells
    the caller there is nothing to gain by asking the parent compound.
    """
    try:
        src, kind = driven_weight_source(cmds, plug)
        if not src:
            return None, None, False
        if kind != "other":
            return None, None, True
        entry = src.split(".")[0]
        # The cycle guard, not the depth bound, is what keeps this from
        # re-walking a loop: the bound alone terminates, so only "never
        # queried twice" tells the two apart (#796 review defect 6).
        seen: set = set()
        frontier = [entry]
        for _ in range(_BLEND_WALK_DEPTH):
            nxt: List[str] = []
            for node in frontier:
                if node in seen:
                    continue
                seen.add(node)
                if not _is_intermediary(cmds.nodeType(node)):
                    continue
                for up in cmds.listConnections(node, source=True,
                                               destination=False) or []:
                    if cmds.nodeType(up).startswith("animCurve"):
                        return up, entry, True
                    nxt.append(up)
            frontier = nxt
        return None, None, True
    except Exception:  # noqa: BLE001 - a node that cannot answer finds nothing
        return None, None, False


def pad_pin_verdicts(cmds, what: str, node: str, attrs: Tuple[str, ...],
                     compound: str, label: str
                     ) -> Tuple[List[str], List[str]]:
    """(the plugs a padding pass may pin, the notes it must report).

    What the PADDING passes ask, where `guard_declared_channels` is the
    wrong tool: a pad channel belongs to another clip, not to this call's
    request, so a driven one is skipped and reported rather than refused
    (#796 review round 4 A - refusing a pad would resurrect the closed
    loop round 2 opened, where a rig carrying rig setup could author no
    clip at all).

    Three verdicts, and the middle one is what round 5 B added:

    * a "clip" kind, or no connection at all, pins silently - EVERY pad
      channel is by definition some other clip's curve, so a note about
      each would bury the notes that matter;
    * an UNKEYABLE_KINDS channel is SKIPPED and named (`_skip_pin_note`) -
      a key on one measurably does not land, so pinning it and counting
      the pin would be false-green;
    * any OTHER connection - a pairBlend, an anim layer, a unitConversion
      - is pinned (round 4 B: skipping it would lose a boundary a rig that
      works today gets) and named with `_driven_channel_note`, the SAME
      sentence the DECLARED path gives for the identical connection.

    That last one is the round 4 B asymmetry, one loop over: round 4 A
    narrowed these loops to the unkeyable kinds and then discarded every
    other entry, so an intermediary-fed pad channel was pinned, counted,
    and reported "pinned ... at rest" with no note at all - one scene, two
    diagnoses, depending only on whether the clip happened to declare the
    channel (#796 review round 5 B).
    """
    landing = {attr: (plug, src, kind) for attr, plug, src, kind
               in _connected_channels(cmds, node, attrs, compound)}
    free: List[str] = []
    notes: List[str] = []
    for attr in attrs:
        plug = "%s.%s" % (node, attr)
        # #798: a LOCK is the third thing a key measurably cannot land
        # on (setKeyframe returns 0, nothing created - the same tell as
        # a driven key), and it is not a connection, so the landing map
        # above cannot see it. Skipped and said, exactly like the
        # unkeyable kinds: a pad belongs to another clip, never refused.
        if is_locked(cmds, plug):
            notes.append(_skip_pin_note("%s %s" % (label, plug),
                                        "is locked"))
            continue
        entry = landing.get(attr)
        if entry is None or entry[2] == "clip":
            free.append(plug)
            continue
        at, src, kind = entry
        if kind in UNKEYABLE_KINDS:
            notes.append(_skip_pin_note("%s %s" % (label, plug),
                                        "is driven by %s" % src))
            continue
        free.append(plug)
        # `at`, not `plug`: the note names where the connection LANDS (the
        # child, or the compound that carries it), exactly as the declared
        # path does - a compound-borne anim layer is ONE fact about one
        # plug, and author_clip's final de-duplication collapses the three
        # identical notes into it.
        notes.append(_driven_channel_note(cmds, what, at, src, kind))
    return free, notes


def _driven_channel_note(cmds, what: str, plug: str, src: str,
                         kind: str) -> str:
    """The ONE sentence this module uses for a channel a clip producer is
    about to write that something other than a clip curve already feeds,
    when it does NOT refuse.

    Where a curve hides behind an intermediary the note names it the way
    `guard_static_pose` does - "<curve> behind <node>" - because a caller
    who meets both must not be told they are looking at two different
    problems. author_clip naming the intermediary while guard_static_pose
    named the curve behind it was the wrong-diagnosis class
    `refuse_driven_weight`'s docstring exists to prevent (#796 review
    round 4 B).
    """
    curve, via = _curve_behind_a_blend(cmds, plug)
    behind = " (%s behind %s)" % (curve, via) if curve else ""
    measured = (" - a key on a connection-fed plug measurably does not "
                "land (#771)" if kind in UNKEYABLE_KINDS else "")
    return ("%s is driven by %s%s%s - %s writes that channel anyway; what "
            "the take holds there is the connection's output rather than "
            "this clip's value, and whether the write lands at all through "
            "this shape is NOT measured (#796)"
            % (plug, src, behind, measured, what))


def guard_declared_channels(cmds, what: str,
                            groups: List[Tuple[str, Tuple[str, ...], str]],
                            refuse_unkeyable: bool = True) -> List[str]:
    """Classify every channel `what` is about to write; refuse the ones a
    key measurably cannot land on, and return the warnings for the rest.

    `groups` is [(node, attrs, compound)] - exactly the channels the call
    DECLARES, never the whole rig: a driven key elsewhere is rig setup and
    none of this clip's business (#796 review defect 3).

    ONE implementation for both of this repo's clip producers, because two
    sites classifying independently is how the wrong one ships (#771
    review). They differ in one thing, and it is the flag: author_clip
    writes with `setKeyframe`, which #771 MEASURED to return 0 and create
    nothing on a plug a driven key or a corrective feeds, so it refuses
    those rather than shipping metadata declaring a channel it never
    keyed. retarget_clip writes with `bakeResults` - a different mechanism
    nobody here has measured against a connection-fed plug - so it passes
    False and warns: refusing there would refuse on a measurement that is
    not about it, and would stop a rig that retargets today (#796 review
    round 4 C).

    Kinds outside UNKEYABLE_KINDS never refuse for EITHER caller; see that
    constant.
    """
    notes: List[str] = []
    for node, attrs, compound in groups:
        # A compound-less group (round 6 D) has no one word for what it
        # asked about, so it says what it IS: keyable channels.
        label = compound or "keyable"
        try:
            connected = _connected_channels(cmds, node, attrs, compound)
        except Exception as exc:   # noqa: BLE001
            # The write-side guards degrade to "assume blocked" (see
            # _blocked_rotate_attrs); a REFUSING caller cannot, because the
            # alternative is keying a plug it cannot classify - and if that
            # plug turns out to be connection-fed the key does not land and
            # says nothing. Nothing has been mutated yet, so the refusal
            # costs the caller only the call. A warning-only caller says so
            # and carries on: it has no refusal to fall back on.
            if not refuse_unkeyable:
                notes.append(
                    "cannot tell what drives %s's %s channels (%s) - %s "
                    "writes them blind; check them after the call"
                    % (_short(node), label, exc, what))
                continue
            raise HandlerError(
                "cannot tell what drives %s's %s channels (%s)"
                % (_short(node), label, exc),
                hint="a node that cannot answer a connection query is "
                     "usually a broken reference; repair or remove it, or "
                     "author this clip without that joint - %s refuses "
                     "rather than keying a plug it cannot classify"
                     % what) from exc
        for _, plug, src, kind in connected:
            if kind == "clip":
                continue
            if refuse_unkeyable:
                # Raises for UNKEYABLE_KINDS; returns for every other kind,
                # which is warned about below rather than refused.
                refuse_driven_channel(what, plug, src, kind)
            notes.append(_driven_channel_note(cmds, what, plug, src, kind))
    # A connection on the COMPOUND is reported once per child, and it is
    # ONE fact about one plug: three copies of it read as three problems.
    return list(dict.fromkeys(notes))


def _skip_pin_note(what: str, because: str) -> str:
    """The ONE way the padding pass says a boundary pin was skipped.

    #771 gave the weight loop this sentence; #796 review round 4 A gave
    the joint and root-translation loops the same guard, and a second
    wording for one fact is how a reader concludes they are two different
    problems (the `_stuck_note` rule, one pass over). `because` is the
    clause - "is driven by <src>", or since #798 "is locked" - so a lock
    and a driven key read as the same fact with a different cause.
    """
    return ("%s %s - its boundary pin was SKIPPED (a key on a locked or "
            "connection-fed plug silently no-ops); the clip declaring it "
            "can no longer export that channel" % (what, because))


def is_locked(cmds, plug: str) -> bool:
    """Whether `plug` itself is locked (#798). Per CHILD, never folded from
    the compound: MEASURED, `getAttr('.translate', lock=True)` is False
    while translateY is locked. A plug that cannot answer is not locked -
    the write-side guards then report what the write itself says."""
    try:
        return bool(cmds.getAttr(plug, lock=True))
    except Exception:  # noqa: BLE001 - cannot tell: the write will tell
        return False


def swallowed_by(cmds, plug: str) -> str:
    """The clause naming what made a write to `plug` vanish (#798).

    ONE classifier - `plugwrite.blocker`, the same one every static-write
    guard in this repo asks - so a lock, a driven key, a corrective and a
    blend node are all named the way the rest of the toolbox names them.
    `_lost_write_note` used to end "see the note naming what drives it",
    which pointed at nothing whenever the cause was not a connection: a
    lock is not a connection and nothing asked about locks.
    """
    from . import plugwrite  # noqa: PLC0415 - plugwrite imports clip lazily
    try:
        found = plugwrite.blocker(cmds, plug)
    except Exception:  # noqa: BLE001 - a plug that cannot answer
        found = []
    # A plug's OWN clip curve is where the key was meant to land, never
    # what swallowed it - `blocker` lists it because a STATIC write cannot
    # go through one, which is not this question. And a lock outranks any
    # connection: it is the one thing a single command clears (review).
    found = [b for b in found
             if not (b.reason == "driven" and b.kind == "clip")]
    found.sort(key=lambda b: b.reason != "locked")
    if found:
        return plugwrite.because(found[0])
    return ("nothing on %s answers to a lock or connection query, so this "
            "tool cannot name the cause" % plug)


def key_landed(result: Any) -> bool:
    """Whether a `cmds.setKeyframe` call actually created what it was asked
    for.

    `setKeyframe` returns the NUMBER of keys it set, and #771 MEASURED 0 as
    the tell on a connection-fed plug: no curve, no key, and no error.
    Every call site in this module discarded that number, so the handler
    GUESSED which writes landed and could ship `mcp_clip` declaring a
    channel it never keyed - the whole guessing class, turned into an
    observation (#796 review round 5 C).

    A NON-numeric return is treated as landed. A Maya build (or a seam)
    that answers None tells us nothing, and assuming failure there would
    strip a perfectly keyed channel out of the clip's own metadata - the
    expensive direction of this mistake.
    """
    if isinstance(result, (int, float)) and not isinstance(result, bool):
        return result != 0
    return True


def _lost_write_note(what: str, plug: str, frames: int,
                     because: str) -> str:
    """The ONE way this module says a key it ASKED for was not created.

    Distinct from `_skip_pin_note` on purpose: that one is a write this
    module DECIDED not to attempt, and this one is a write it attempted and
    did not get. Collapsing the two would tell a caller their rig refused a
    channel the tool never even tried (#796 review round 5 C).

    TWO mechanisms lose a write, and this sentence covers both because the
    caller's fix is the same for either and a second wording for one fact
    is how a reader concludes they are two problems (`_stuck_note`'s rule).
    A `setKeyframe` that reports 0 keys is one; the other, on ROOT
    TRANSLATION only, is the `xform` pose write that has to land first
    being refused outright by the same connection - a connection-fed plug
    takes no static write (#796 review round 6 A).

    `because` names the cause INLINE (#798, from `swallowed_by`): the
    sentence used to end by pointing at "the note naming what drives it",
    and on a LOCKED plug no such note existed.
    """
    return ("%s's key on %s did NOT land at %d frame(s) (setKeyframe "
            "reported 0 keys, or - on root translation - the pose write it "
            "depends on was refused): %s, so this clip neither counts nor "
            "declares that channel" % (what, plug, frames, because))


def _lost_pin_note(plug: str, frames: List[float], because: str) -> str:
    """The same fact about a BOUNDARY PIN rather than an authored key."""
    return ("the boundary pin on %s did NOT land at frame(s) %s "
            "(setKeyframe reported 0 keys): %s, so a take that does not "
            "declare that channel may inherit a neighbour's value there "
            "(#796)" % (plug, ", ".join("%g" % f for f in frames), because))


def _blocked_rotate_attrs(cmds, joint: str) -> List[str]:
    """Which of `joint`'s rotate children a connection still feeds.

    setAttr on a connection-fed plug raises ("locked or connected and
    cannot be modified"), and connecting the COMPOUND blocks all three
    children - so a source on `.rotate` blocks the lot (#796 review defect
    2). The child-first order and the compound fallback both live in
    `_connected_channels`, which author_clip's per-channel refusal asks the
    same question of. A node that cannot answer is reported as fully
    blocked: skipping a write and saying so beats crashing a teardown
    mid-mutation.
    """
    try:
        return [a for a, _, _, _ in
                _connected_channels(cmds, joint, ROTATE_ATTRS, "rotate")]
    except Exception:  # noqa: BLE001 - cannot tell: do not risk the write
        return list(ROTATE_ATTRS)


def _blocked_transform_attrs(cmds, joint: str) -> List[str]:
    """`_blocked_rotate_attrs` widened to TRANSLATE, for the bind-pose
    restore.

    `dagPose -restore` returns a whole transform, so a connection on
    `.translateY` defeats it exactly the way one on `.rotateX` does - and
    delete_clip's own sweep already covers translate plugs, so a surviving
    driven key there is a shape this rig can really carry. The no-bind-pose
    fallback stays rotate-only because zeroing rotations is all it ever
    writes. Same degrade rule: a joint that cannot answer is reported as
    fully stuck rather than crashing a teardown mid-mutation.
    """
    try:
        return [a for a, _, _, _ in
                (_connected_channels(cmds, joint, ROTATE_ATTRS, "rotate")
                 + _connected_channels(cmds, joint, TRANSLATE_ATTRS,
                                       "translate"))]
    except Exception:  # noqa: BLE001 - cannot tell: report it as stuck
        return list(ROTATE_ATTRS + TRANSLATE_ATTRS)


def _stuck_note(stuck: List[Tuple[str, List[str]]], noun: str,
                tail: str) -> str:
    """The ONE way this module names channels a teardown could not return
    to rest. `stuck` is [(joint short name, blocked attrs)].

    Both of delete_clip's teardown branches - the bind-pose restore and the
    no-bind-pose zeroing - report the same fact about the same channels and
    differ only in HOW the return failed, so they say it the same way and
    differ only in `tail`. Two vocabularies for one fact is how a reader
    concludes they are two different problems (#796 review round 3 M2).

    The count is the number of CHANNELS the list names, not the number of
    joints it groups them under: "left 2 joint channel(s) as they are -
    root (translateZ); tip (rotateX, rotateY)" was MEASURED, and 2 is the
    joint count while three channels are stuck (#796 review round 4 D).
    Both call sites now count exactly what they list.
    """
    total = sum(len(attrs) for _, attrs in stuck)
    named = "; ".join("%s (%s)" % (short, ", ".join(attrs))
                      for short, attrs in stuck)
    return ("left %d joint %s as they are - %s: a connection still feeds "
            "those channels (a surviving set-driven key, an anim layer, a "
            "constraint), %s" % (total, noun, named, tail))


def guard_static_pose(cmds, root_long: str, joints: List[str],
                      what: str) -> None:
    """Refuse a static pose write while curves drive the skeleton.

    Structural, not metadata: a hand-keyed channel fights a static write the
    same way a clip does. The clip name is named when metadata exists.

    FOUR kinds of curve reach these plugs and each needs its own exit,
    because each has a different fix. A time-based curve is this module's
    currency, so delete_clip is a real fix; a driven-key (U-typed) curve is
    a connection reading a DRIVER attribute, and "the clip owns these
    channels; delete_clip" is a wrong diagnosis for it (#767 M2 - the same
    reason guard_static_weights leaves those curves to the
    driven_weight_source classifier); a curve reaching a plug THROUGH a
    pairBlend or an anim-layer blend node is invisible to delete_clip's
    direct query, so naming delete_clip for THAT one is a dead-end hint of
    a third kind (#796 defect 2); and a driven key reached through such a
    node is a fourth, because deleting its curve leaves the blend node
    owning the plug and the guard refusing with nothing left to name (#796
    review defect 7).

    delete_clip now leaves the driven-key curves standing and reports them
    (#796 defect 1), so when both drive the skeleton the caller is told
    about both and told plainly that the clip fix will not cost them their
    rig setup - and will not silently return those channels to static
    either. This paragraph used to say the opposite, correctly, back when
    the teardown reaped whatever _anim_curves returned."""
    plugs = _joint_plugs(joints)
    driven = _anim_curves(cmds, plugs)
    clip_curves, sdk_curves = partition_driven_keys(cmds, driven)
    # Ordered by first sighting so the message reads the way the rig does.
    hidden: Dict[Tuple[str, str], None] = {}
    # #796 review defect 7: an INDIRECT driven key is kept apart from the
    # direct ones rather than merged into them. "Remove the driven key
    # (delete its curve node)" is false of one behind a blend node and
    # never names the intermediary, so a caller who follows it destroys rig
    # setup, is refused again, and now has no curve left to name.
    hidden_sdk: Dict[Tuple[str, str], None] = {}
    for plug in plugs:
        if plug in driven:
            continue
        curve, via = _curve_behind_a_blend(cmds, plug)
        if curve is None:
            continue
        _, indirect_sdk = partition_driven_keys(cmds, [curve])
        bucket = hidden_sdk if indirect_sdk else hidden
        bucket.setdefault((curve, via), None)
    if not (clip_curves or sdk_curves or hidden or hidden_sdk):
        return
    sdk_named = ", ".join(sdk_curves)
    sdk_hint = ("remove the driven key (delete its curve node) to return "
                "those channels to static posing")
    hidden_named = ", ".join("%s behind %s" % pair for pair in hidden)
    hidden_hint = ("delete_clip's teardown queries DIRECT curve connections "
                   "only, so it will NOT remove a curve hiding behind a "
                   "blend node; delete or disconnect %s, then the curve "
                   "behind it, to return those channels to static posing"
                   % ", ".join(sorted({via for _, via in hidden})))
    hidden_sdk_named = ", ".join("%s behind %s" % pair for pair in hidden_sdk)
    hidden_sdk_hint = ("a driven-key curve reached THROUGH a blend node is "
                       "not freed by deleting the curve alone - %s still "
                       "owns the plug and this guard would refuse again; "
                       "delete or disconnect that node as well to return "
                       "those channels to static posing"
                       % ", ".join(sorted({via for _, via in hidden_sdk})))
    rig_setup_named = "; ".join(x for x in (sdk_named, hidden_sdk_named) if x)
    rig_setup_hint = "; ".join(
        h for h, present in ((sdk_hint, sdk_curves),
                             (hidden_sdk_hint, hidden_sdk)) if present)
    if not clip_curves and not hidden:
        raise HandlerError(
            "%s refuses while set-driven keys drive this skeleton (%s) - a "
            "static write here would be overridden the next time the driver "
            "attribute moves" % (what, rig_setup_named),
            hint=rig_setup_hint)
    if clip_curves:
        records = clip_meta(cmds, root_long)
        label = ((" (clip%s %s)"
                  % ("s" if len(records) > 1 else "",
                     ", ".join(repr(r["name"]) for r in records)))
                 if records else "")
        message = ("%s refuses while animation curves drive this skeleton%s "
                   "- a static write here would be overridden on the next "
                   "frame change" % (what, label))
        hint = ("author_clip re-authors the motion; delete_clip removes the "
                "curves and returns the skeleton to static posing")
    else:
        message = ("%s refuses while an animation curve drives this skeleton "
                   "through a blend node (%s) - a static write here would be "
                   "overridden on the next frame change"
                   % (what, hidden_named))
        hint = hidden_hint
    if sdk_curves or hidden_sdk:
        message += ("; set-driven keys drive it as well (%s), which is rig "
                    "setup rather than clip motion" % rig_setup_named)
        hint += ("; delete_clip leaves those driven-key curves standing (rig "
                 "setup is not clip motion), so %s if those channels must be "
                 "static too" % rig_setup_hint)
    if clip_curves and hidden:
        message += ("; an animation curve also reaches it through a blend "
                    "node (%s), which delete_clip's direct query cannot see"
                    % hidden_named)
        hint += "; " + hidden_hint
    raise HandlerError(message, hint=hint)


def guard_static_weights(cmds, node: str, aliases: List[str],
                         what: str) -> None:
    """The same rule for blendshape weight channels.

    Driven-key (U-typed) curves are deliberately NOT this guard's business:
    they are connections reading a driver, not clip channels, and "the clip
    owns these channels; delete_clip" would be a wrong diagnosis with a
    dead-end hint. They fall through to the per-request
    driven_weight_source classifier, which names them (#771)."""
    driven = clip_curve_plugs(
        cmds, _anim_curves(cmds, ["%s.%s" % (node, a) for a in aliases]))
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


def _skip_cut_note(plug: str, curves: List[str],
                   via: Optional[str] = None) -> str:
    """The ONE way this module says a destructive range-cut stepped around
    a plug (#796 review round 5 A).

    Not cutting silently is the same sin as cutting silently: the caller
    has to know which channel kept its keys, or a stale value it never sees
    named becomes "the tool is flaky". `via` names the intermediary when
    the curve reaches the plug through one, spelled the way
    `guard_static_pose` spells it - one scene, one diagnosis."""
    named = ", ".join(curves)
    return ("did NOT clear the replaced clip's frame range on %s: %s is a "
            "set-driven key, indexed by DRIVER VALUE rather than by time, "
            "so that frame range is a numeric range on the driver and a "
            "cutKey against it would destroy rig setup (#796) - the "
            "channel keeps every key it had"
            % (plug, "%s behind %s" % (named, via) if via else named))


def cut_replaced_range(cmds, joints: List[str], replaced: Dict[str, Any],
                       weight_plugs: Optional[List[str]] = None) -> List[str]:
    """Clear a REPLACED clip's old keys on every channel it might have used.

    Returns the notes naming any plug it stepped around; every caller
    appends them to its own `warnings`.

    Widened past `end_frame` by GAP_FRAMES (#718 final review Fix 2):
    `end_frame` is `int(round(measured_end))` (#636), which rounds DOWN
    whenever the last key's fractional part is below 0.5 - a key at
    end_frame+0.4 (e.g. measured_end=14.4, end_frame=14) then sits outside
    (start_frame, end_frame) and would survive an unwidened cut, holding
    the REPLACED version's value and polluting whatever gets keyed into
    the same range next. Widening is free: no take's range ever includes
    the unowned gap frame (clipmath.GAP_FRAMES), so nothing legitimate
    lives there either.

    Extracted from author_clip's re-author path (#774 Task 3 review,
    the way register_clip was) so retarget_clip's own replace-same-name
    path cuts identically rather than re-deriving the same shape - a
    second, slightly-different cut here would be exactly the kind of
    almost-matching duplicate this codebase measures its way out of.
    `joints` is the FULL hierarchy the caller keys against (author_clip's
    `_hierarchy_joints(root_long)`, retarget_clip's `target_joints`), not
    just the channels the replaced record happened to declare - the same
    over-inclusive plug set author_clip has always cut against.

    PARTITIONED, and this is the only site in this module that mutates a
    time RANGE over that over-inclusive plug set (#796 review round 5 A).
    `clip_curve_plugs`' docstring names this exact hazard: a set-driven
    key's curve is indexed by DRIVER VALUE, so `time=(0, 30)` here is the
    driver interval 0..30 and a `cutKey` silently destroys every driver key
    whose NUMBER falls in the replaced clip's frame range. The four
    read-only sites had the partition; the one destructive site did not.
    Round 2 is what made it reachable: before #796 author_clip refused a
    rig carrying a driven key outright, so this cut never ran on one.

    Narrowed by exactly ONE kind and nothing else - a plug with a clip
    curve is cut, and so is a plug with no curve at all (cutKey on it is a
    no-op, and skipping those would be a second, silent behaviour change).
    """
    notes: List[str] = []
    for plug in sorted(set(_joint_plugs(joints) + list(weight_plugs or []))):
        # Per plug, not one sweep: a node that cannot answer (a broken
        # reference) must cost one skipped cut, never a traceback halfway
        # through a mutation the caller has already checkpointed - the
        # `_blocked_rotate_attrs` degrade rule, on the side where "cannot
        # tell" means "do not destroy".
        via: Optional[str] = None
        try:
            driven = _anim_curves(cmds, [plug])
            sdk: List[str] = []
            if plug in driven:
                if plug not in clip_curve_plugs(cmds, driven):
                    sdk = driven[plug]
            else:
                # #796 review defect 7's shape, on the destructive side: a
                # driven key can reach a plug THROUGH a pairBlend or an
                # anim layer, where the direct query above sees NOTHING.
                # Whether `cutKey` follows a connection to the curve behind
                # it is not measured here - and skipping is right under
                # both answers, because if it does not follow, the cut it
                # skipped was a no-op anyway. A CLIP curve behind a blend
                # node is still cut, exactly as before.
                curve, via = _curve_behind_a_blend(cmds, plug)
                if curve is not None:
                    _, sdk = partition_driven_keys(cmds, [curve])
        except Exception as exc:  # noqa: BLE001 - cannot tell: do not cut
            notes.append(
                "did NOT clear the replaced clip's frame range on %s: "
                "nothing could tell what drives it (%s), and a time-range "
                "cutKey on a set-driven key destroys rig setup - the "
                "channel keeps every key it had" % (plug, exc))
            continue
        if sdk:
            notes.append(_skip_cut_note(plug, sdk, via))
            continue
        cmds.cutKey(plug, time=(replaced["start_frame"],
                               replaced["end_frame"] + clipmath.GAP_FRAMES),
                    clear=True)
    return notes


def register_clip(cmds, root_long: str, name: str, fps: int, start: int,
                  end: int, loop: bool = False, interpolation: str = "linear",
                  joints: Optional[List[str]] = None,
                  weight_channels: Optional[List[str]] = None,
                  root_position_used: bool = False) -> None:
    """Append (or replace-and-re-append, #718 decision 4) one clip's metadata
    record on `root_long`, then widen the rig's playback range to the new
    span so scrubbing the open scene shows every clip, not just the one just
    written.

    Extracted from author_clip (#774 Task 3) so a second producer of clips
    (retarget_clip, which bakes motion rather than keying named channels)
    writes the exact same record shape instead of a hand-rolled
    approximation - this is the ONE place `mcp_clip` gets written. Every
    caller does its OWN drop_record/next_start_frame bookkeeping before
    calling this (start/end/loop are already decided by the time this
    runs); this function only re-derives `kept` from the rig's current
    metadata to build the new full record list - cheap, and always
    consistent with whatever the caller already used to pick `start`,
    because nothing mutates `root_long`'s CLIP_ATTR between that decision
    and this call.

    `joints`/`weight_channels`/`root_position_used`/`interpolation` default
    to what a baked clip actually has: no per-key channel declarations of
    its own (the whole rig is baked, not authored key by key via `keys=`)
    and linear tangents (one key per frame from a bake makes tangent TYPE
    invisible). author_clip passes its own computed values for all four, so
    adding these defaults changes nothing about its existing behavior.

    Curve-cutting a REPLACED clip's old range is the CALLER's job, not
    this function's - that has to happen before the new keys are set,
    which is earlier than this call ever runs.
    """
    records = clip_meta(cmds, root_long)
    _replaced, kept = clipmath.drop_record(records, name)
    new_record = {
        "name": name, "fps": fps, "start_frame": start, "end_frame": end,
        "duration_s": (end - start) / float(fps), "loop": loop,
        "interpolation": interpolation,
        "joints": sorted(joints) if joints else [],
        "weight_channels": list(weight_channels) if weight_channels else [],
        "root_position_used": bool(root_position_used),
    }
    all_records = kept + [new_record]
    span_end = max(r["end_frame"] for r in all_records)
    # The playback range is the FULL span, so opening the .ma and scrubbing
    # shows every clip - not just the one authored last.
    cmds.playbackOptions(edit=True, minTime=0, maxTime=span_end,
                         animationStartTime=0, animationEndTime=span_end)
    if not cmds.attributeQuery(CLIP_ATTR, node=root_long, exists=True):
        cmds.addAttr(root_long, longName=CLIP_ATTR, dataType="string")
    cmds.setAttr("%s.%s" % (root_long, CLIP_ATTR), json.dumps(all_records),
                 type="string")


def make_self_contained(cmds, what: str, root_long: str, joints: List[str],
                        alias_map: Dict[str, Any], start_frame: int,
                        end_frame: int, measured_end: float,
                        kept: List[Dict[str, Any]], mine: Dict[str, Any],
                        rest: Dict[str, float],
                        warnings: List[str]) -> Dict[str, Any]:
    """The #718 self-contained rule, for ANY producer of a clip (#798).

    All clips share ONE curve per channel, so a channel this clip never
    mentions would hold whatever a neighbour left on it - forwards from
    the previous clip's last key, and BACKWARDS from a later clip's first
    key. Both are pinned here, and both are reported:

    * every channel any clip on the rig declares (`theirs`, unioned with
      `mine` once an earlier clip exists) is pinned at this clip's own
      boundary frames - at rest when this clip never keys it, at its own
      held value when it does (`_pad_boundaries`);
    * every channel THIS clip introduces is pinned at rest across every
      earlier clip's boundaries (`_back_fill`), which RESTORES what each
      of them measured when it was authored.

    `mine` is what this clip actually GOT - derived by the caller from the
    writes' own returns (author_clip) or from what the bake left in the
    scene (retarget_clip), never from the request (#796 review round 5 C).
    `rest` is the rig's rest map with this clip's own channels already
    captured BEFORE its keys were written; it is completed here (the
    legacy inference in `_rest_value`) and written back. `measured_end` is
    the unrounded keyed maximum, see `_pad_boundaries`.

    Lived as closures inside author_clip until #798, which is exactly why
    retarget_clip ran no such pass: a retargeted take registered `joints:
    []`, so the author_clip that came next pinned nothing against it and
    the slot joints held the walk's last pose across the whole idle take
    (MEASURED, evals/clip_edges_probe_798 section B). Returns
    `padded_channels`, `held_channels` and `back_filled`, the three
    result fields both producers now report.
    """
    by_short: Dict[str, List[str]] = {}
    for j in joints:
        by_short.setdefault(_short(j), []).append(j)
    root_translate_plugs = ["%s.%s" % (root_long, a) for a in TRANSLATE_ATTRS]

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

    def _pin(plug: str, frames: List[int], value: float) -> List[int]:
        """Pin `plug` at `value` on each of `frames`. Returns the frames
        whose write did NOT land (#796 review round 5 C) - the same
        observation the authored keys make, at the fourth setKeyframe call
        site. The tangent edit is skipped for a frame that has no key:
        there is nothing there to tangent."""
        node, attr = plug.rsplit(".", 1)
        lost: List[int] = []
        for frame in frames:
            if not key_landed(cmds.setKeyframe(node, attribute=attr,
                                               time=frame, value=value)):
                lost.append(frame)
                continue
            # #718 review Fix 2: a pinned key is scoped to its own frame,
            # and FLAT - not the clip's interpolation. A pin is not
            # authored motion; flat is the honest type, and it keeps a
            # pinned span genuinely flat regardless of what interpolation
            # this clip was authored with.
            cmds.keyTangent(node, attribute=attr, time=(frame, frame),
                            edit=True, inTangentType="flat",
                            outTangentType="flat")
        return lost

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
            lost = _pin(plug, missing, _rest_value(cmds, plug, rest,
                                                   warnings))
        else:
            lost = []
            for frame in missing:
                source = own[0] if frame == start_frame else own[-1]
                lost += _pin(plug, [frame],
                             float(cmds.getAttr(plug, time=source)))
        # #796 review round 5 C: a pin that did not land is not a pin. The
        # caller counts this verdict into `padded_channels`/
        # `held_channels`, so returning one for a plug where nothing was
        # written is exactly the false-green round 4 A closed on the
        # SKIPPED channels - the same hole, one step further in.
        if lost:
            warnings.append(_lost_pin_note(plug, lost,
                                           swallowed_by(cmds, plug)))
        if len(lost) == len(missing):
            return ""
        return "rest" if not own else "held"

    def _back_fill(plugs: List[str], frames: List[int]) -> bool:
        """Pin every plug of one channel at rest across `frames`. True when
        at least one of those writes landed - which is the only thing that
        makes `back_filled_channels` true (#796 review round 5 C)."""
        landed = False
        for plug in plugs:
            lost = _pin(plug, frames, _rest_value(cmds, plug, rest,
                                                  warnings))
            if lost:
                warnings.append(_lost_pin_note(plug, lost,
                                               swallowed_by(cmds, plug)))
            landed = landed or len(lost) < len(frames)
        return landed

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
        # #796 review round 4 A: the treatment the weight loop below has
        # had since #771, which this loop never got. The per-channel
        # refusal above asks only about the channels THIS call declares -
        # precisely the ones a pad is NOT: `pad_joints` is other clips'
        # channels unioned with this call's. Another clip's channel can
        # have become driven out of band, `_pin`'s setKeyframe silently
        # no-ops on it (measured), and reporting it "pinned" below would
        # be false-green. A pad is not the caller's request, so it is
        # SKIPPED and said - never refused, which would resurrect the
        # closed loop round 2 opened. Only UNKEYABLE_KINDS skip: a
        # pairBlend still gets its pin, for defect B's reason - and, since
        # round 5 B, the same NOTE the declared path gives it.
        free, notes = pad_pin_verdicts(
            cmds, what, plugs[0].rsplit(".", 1)[0], ROTATE_ATTRS,
            "rotate", "joint channel")
        warnings.extend(notes)
        if not free:
            continue
        kinds = {kind for kind in (_pad_boundaries(p) for p in free) if kind}
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
        # #771: another clip's declared channel can have become driven
        # out-of-band (its curve deleted, then a corrective wired). _pin's
        # setKeyframe would silently no-op on it (measured), so claiming
        # "pinned" below would be false-green - skip and say so instead.
        # ANY non-clip kind skips here, which is one kind wider than the
        # joint loop above: this side's own refusal (refuse_driven_weight,
        # #771) refuses every non-clip kind for a DECLARED weight, so the
        # pad matches the refusal on its own side of the rig rather than
        # the other side's.
        if is_locked(cmds, "%s.%s" % (node, alias)):
            warnings.append(_skip_pin_note("weight channel %r" % alias,
                                           "is locked"))
            continue
        src, drive_kind = driven_weight_source(cmds, "%s.%s" % (node, alias))
        if drive_kind is not None and drive_kind != "clip":
            warnings.append(_skip_pin_note("weight channel %r" % alias,
                                           "is driven by %s" % src))
            continue
        kind = _pad_boundaries("%s.%s" % (node, alias))
        if kind == "held":
            held_channels.append(alias)
        elif kind == "rest":
            padded_channels.append(alias)
    if pad_root_position:
        # Same #796 round 4 A treatment as the joint loop (and round 5 B's
        # note with it): this loop had no guard of any kind, and a root
        # another clip moves can have become driven out of band exactly
        # like a joint channel.
        free, notes = pad_pin_verdicts(
            cmds, what, root_long, TRANSLATE_ATTRS, "translate",
            "root translation channel")
        warnings.extend(notes)
        kinds = {kind for kind in (_pad_boundaries(p) for p in free) if kind}
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
            if _back_fill(plugs, their_frames):
                back_filled_channels.append(short)
        for alias in mine["weight_channels"]:
            if alias in theirs["weight_channels"]:
                continue
            if _back_fill(["%s.%s" % (alias_map[alias], alias)],
                          their_frames):
                back_filled_channels.append(alias)
        if mine["root_position_used"] and not theirs["root_position_used"]:
            if _back_fill(root_translate_plugs, their_frames):
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
    return {
        "padded_channels": padded_channels,
        "held_channels": held_channels,
        "back_filled": back_filled,
    }


# Every top-level key author_clip reads. Anything else is refused rather
# than ignored (#767): an unread key does not fail, it succeeds and does
# something else.
AUTHOR_CLIP_KEYS = ("root", "name", "fps", "interpolation", "loop", "keys")
# `clip` is what the RESULT calls the thing just authored, and it is the
# real input key on clean_clip next door - this repo's own vocabulary
# pulling a caller toward the wrong word. `frame_rate` is the unabbreviated
# spelling of fps, which a caller writes out when unsure of the short form.
AUTHOR_CLIP_SYNONYMS = {"clip": "name", "frame_rate": "fps"}


def author_clip(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, AUTHOR_CLIP_KEYS, "author_clip",
                       AUTHOR_CLIP_SYNONYMS)
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

    # #771: a connection-fed weight cannot be keyed - MEASURED
    # (evals/correctives_probe/): setKeyframe on such a plug returns 0 and
    # creates NOTHING, so without this refusal the clip would silently ship
    # without a channel it claims to key. Time-based animCurves ("clip"
    # kind) pass through - re-authoring over this tool's own curves is the
    # normal append/replace path, and foreign hand-keyed curves are the
    # older refusal's job below.
    for alias in weight_channels:
        src, kind = driven_weight_source(
            cmds, "%s.%s" % (alias_map[alias], alias))
        if kind is not None and kind != "clip":
            refuse_driven_weight("author_clip", alias, src, kind)

    # #796 review round 3 M1: the SAME refusal on the joint side, and for
    # the same measured reason - the two loops read alike deliberately.
    # The foreign-curve check below counts the CLIP partition only (a
    # driven key elsewhere on the rig must not block a first clip, #796
    # review defect 3), which left the joints with no per-channel guard at
    # all: setKeyframe on the connection-fed plug returns 0, creates
    # nothing, and the handler still wrote mcp_clip declaring that joint
    # keyed. PER CHANNEL, never per rig: only the channels THIS clip
    # declares are asked, so a driven key on any other channel stays out
    # of the way.
    #
    # `warnings` starts HERE rather than below, because that guard also
    # NAMES the channels it does not refuse (#796 review round 4 B): a
    # pairBlend or an anim layer on a declared channel is keyed as it
    # always was, and reported.
    declared_groups = [(j, ROTATE_ATTRS, "rotate") for j in
                       sorted({j for key in resolved_keys
                               for j in key["rotations"]})]
    if any(k["root_position"] is not None for k in resolved_keys):
        declared_groups.append((root_long, TRANSLATE_ATTRS, "translate"))
    warnings: List[str] = guard_declared_channels(
        cmds, "author_clip", declared_groups)
    # #798: the third refusal, for a LOCK. MEASURED: setKeyframe on a
    # locked plug returns 0 and creates nothing (a driven key's tell), and
    # the root's `xform` pose write drops a locked child WITHOUT raising -
    # so a locked root.translateY shipped a clip declaring root_position
    # with one of its three channels never written. A lock is a static,
    # rigger-set refusal of the very write this clip needs, so it is
    # refused before the checkpoint (#802's rule) with plugwrite's own
    # hint; every other kind of obstacle stays with the guard above.
    # Declared channels only, like everything else here: a lock elsewhere
    # on the rig blocks nothing.
    from . import plugwrite  # noqa: PLC0415 - plugwrite imports clip lazily
    # Weight channels too (review catch): the weight guard above asks
    # about CONNECTIONS, and a locked, unconnected weight answered it
    # with nothing - then checkpointed and shipped without the channel.
    locked = [b for b in plugwrite.blockers(
        cmds, ["%s.%s" % (node, a) for node, attrs, _ in declared_groups
               for a in attrs]
        + ["%s.%s" % (alias_map[a], a) for a in weight_channels])
        if b.reason == "locked"]
    if locked:
        plugwrite.refuse(
            "author_clip", locked,
            consequence="a key on a locked plug measurably does not land "
                        "(setKeyframe reports 0), so the clip would ship "
                        "declaring a channel it never keyed; nothing was "
                        "written",
            hint_tail="or leave that channel out of this clip's keys - a "
                      "lock on a channel the clip does not declare blocks "
                      "nothing")

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
    # #796 review defect 3: the CLIP partition only. A U-typed set-driven
    # key is rig setup, not hand-authored clip motion, and this refusal's
    # hint names delete_clip - which no longer removes those curves and
    # refuses the same rig with "no clip exists". Counting them here made a
    # rig carrying a driven key and no clip unable to author a first clip,
    # with each tool naming the other as the fix. The hint stays true
    # because what it counts is exactly what delete_clip deletes.
    existing = clip_curve_plugs(
        cmds, _anim_curves(cmds, _joint_plugs(joints) + weight_plugs))
    if existing and not records:
        raise HandlerError(
            "this skeleton carries %d hand-authored animation curve "
            "channel(s) this tool did not author (e.g. %s)"
            % (len(existing), sorted(existing)[0]),
            hint="replacing hand-authored animation silently would destroy "
                 "work; delete_clip removes it if that is intended")

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

    root_translate_plugs = ["%s.%s" % (root_long, a) for a in TRANSLATE_ATTRS]
    # What this call ASKED for. `mine` - what it actually GOT - is derived
    # from the writes' own return values after the keying loop below (#796
    # review round 5 C), and the two differ only when a write vanishes.
    # Rest capture runs off the DECLARED set deliberately: it happens
    # before any key is written, and recording a rest value for a channel
    # that then fails to key costs nothing (nobody pins it either way).
    declared = {
        "joints": sorted({_short(j) for key in resolved_keys
                          for j in key["rotations"]}),
        "weight_channels": list(weight_channels),
        "root_position_used": any(k["root_position"] is not None
                                  for k in resolved_keys),
    }
    rest = _rest_map(cmds, root_long)
    rest_before = set(rest)
    bind = _bind_rotations(cmds, root_long, joints)
    for short in declared["joints"]:
        triple = bind.get(short)
        for plug, bind_v in zip(_rot_plugs(short),
                                triple if triple is not None
                                else (None, None, None)):
            _capture_rest(cmds, plug, rest, value=bind_v)
    if declared["root_position_used"]:
        for plug in root_translate_plugs:
            _capture_rest(cmds, plug, rest)
    for alias in declared["weight_channels"]:
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
        # #796 review round 5 A: the cut steps around a driven-key plug and
        # SAYS which one - a stale range nobody was told about reads as a
        # flaky tool.
        warnings.extend(cut_replaced_range(cmds, joints, replaced,
                                           weight_plugs))

    start_frame = clipmath.next_start_frame(kept)

    prev_unit = cmds.currentUnit(query=True, time=True)
    unit = clipmath.FPS_UNITS[fps]
    if prev_unit != unit:
        cmds.currentUnit(time=unit)
        warnings.append("scene time unit changed %r -> %r so a frame is "
                        "1/%d s" % (prev_unit, unit, fps))

    keyed: List[tuple] = []   # (node, attr) pairs that LANDED, for tangents
    # #796 review round 5 C: OBSERVED, never assumed. Everything this call
    # counts, records in `mcp_clip` and reports is derived from these three
    # sets, which only a write that actually created a key adds to.
    landed_joints: set = set()
    landed_weights: set = set()
    landed_root = False
    lost_writes: Dict[str, int] = {}

    def _key(node: str, attr: str, frame: float, value: float) -> bool:
        """setKeyframe, with its return read. True when the key exists."""
        if key_landed(cmds.setKeyframe(node, attribute=attr, time=frame,
                                       value=value)):
            keyed.append((node, attr))
            return True
        plug = "%s.%s" % (node, attr)
        lost_writes[plug] = lost_writes.get(plug, 0) + 1
        return False

    def _place_root(position: List[float]) -> bool:
        """Move the root to one key's world position. False when that write
        was refused - counted and reported exactly as a swallowed
        `setKeyframe` is (`key_landed`'s verdict, reached the other way),
        because the three translate keys that depend on it cannot be
        written either. NOT keyed at a guessed value: a key written from a
        pose write that never happened would be this handler's own guess at
        where the root is, which is the class round 5 C removed."""
        try:
            cmds.xform(root_long, worldSpace=True, translation=position)
        except Exception:  # noqa: BLE001 - a refusal is data, not a crash
            for attr in TRANSLATE_ATTRS:
                plug = "%s.%s" % (root_long, attr)
                lost_writes[plug] = lost_writes.get(plug, 0) + 1
            return False
        return True

    for key in resolved_keys:
        frame = start_frame + key["time_s"] * fps
        for joint, triple in key["rotations"].items():
            for attr, value in zip(ROTATE_ATTRS, triple):
                if _key(joint, attr, frame, units.degrees_to_ui(cmds, value)):
                    landed_joints.add(joint)
        if key["root_position"] is not None:
            # #796 review round 6 A: this xform is a STATIC write to the
            # very translate plugs `guard_declared_channels` may have
            # decided only to WARN about - a pairBlend is what Maya inserts
            # the moment a plug is both keyed AND constrained, and round 4
            # B deliberately does not refuse that rig because it authors
            # clips today. A connection-fed plug refuses a static write, so
            # on such a root this RAISED: a traceback after
            # auto_checkpoint, with key 0's rotations already in the scene.
            # A write that cannot land is REPORTED the way every other lost
            # write is, and the rest of the clip still ships.
            # Nested, never `continue`: this key's BLEND WEIGHTS are
            # written below and have nothing to do with the root's
            # translate plugs - skipping the rest of the key would lose a
            # channel that can be written perfectly well.
            if _place_root(key["root_position"]):
                local = [float(v) for v in cmds.xform(
                    root_long, query=True, translation=True)]
                for attr, value in zip(TRANSLATE_ATTRS, local):
                    if _key(root_long, attr, frame, value):
                        landed_root = True
        for alias, value in key["blend_weights"].items():
            if _key(alias_map[alias], alias, frame, value):
                landed_weights.add(alias)

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

    # #796 review round 5 C: what this clip actually GOT. Every channel
    # below - padded, back-filled, recorded in `mcp_clip`, counted in the
    # result - comes from here rather than from `declared`, so a write that
    # vanished can no longer ship as a channel the take declares and has no
    # curve for. When every write lands (the measured-today case, and the
    # only one before a pairBlend is in the way) this is `declared`
    # verbatim. NOT a refusal: what a key does through an intermediary is
    # unmeasured, and refusing there would stop a keyed-and-constrained rig
    # that authors clips today (round 4 B) - the report just has to be true
    # under both outcomes.
    for plug in sorted(lost_writes):
        warnings.append(_lost_write_note("author_clip", plug,
                                         lost_writes[plug],
                                         swallowed_by(cmds, plug)))
    mine = {
        "joints": sorted({_short(j) for j in landed_joints}),
        "weight_channels": [a for a in weight_channels
                            if a in landed_weights],
        "root_position_used": landed_root,
    }
    if lost_writes and not (landed_joints or landed_weights or landed_root):
        warnings.append(
            "this clip keyed NOTHING: every one of the %d write(s) it "
            "asked for was swallowed by something on the plug, so %r is "
            "registered as an empty take that declares no channel at all - "
            "check the connections named above before exporting it"
            % (sum(lost_writes.values()), name))

    # --- the self-contained rule (#718) --------------------------------
    # Extracted to `make_self_contained` (#798) so retarget_clip, the
    # repo's second clip producer, runs the identical pass: the closures
    # that used to live here were the reason a retargeted take pinned
    # nothing and was pinned against by nobody.
    contained = make_self_contained(
        cmds, "author_clip", root_long, joints, alias_map, start_frame,
        end_frame, measured_end, kept, mine, rest, warnings)
    padded_channels = contained["padded_channels"]
    held_channels = contained["held_channels"]
    back_filled = contained["back_filled"]

    # #796 review round 5 C: `mine` - what LANDED - not the declared set.
    # A record naming a channel with no curve is what every downstream
    # reader trusts: export bakes a take declaring it, the pad passes of
    # the NEXT clip pin against it, and delete_clip's reap goes looking for
    # a curve that was never created.
    register_clip(
        cmds, root_long, name, fps, start_frame, end_frame, loop=loop,
        interpolation=interpolation, joints=mine["joints"],
        weight_channels=mine["weight_channels"],
        root_position_used=mine["root_position_used"])

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
        # #796 review round 5 C: all three are what the writes REPORTED,
        # not what the call asked for. "keyed" is a claim about the scene,
        # and it used to be a re-read of the request.
        "keyed_joints": len(landed_joints),
        "keyed_weight_channels": mine["weight_channels"],
        "root_position_keyed": mine["root_position_used"],
        "interpolation": interpolation,
        "loop": loop,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "clips": [r["name"] for r in clip_meta(cmds, root_long)],
        "padded_channels": padded_channels,
        "held_channels": held_channels,
        "back_filled": back_filled,
        "replaced": name if replaced is not None else None,
        "per_key": per_key,
        "warnings": warnings,
    }


# Every top-level key delete_clip reads; anything else is refused rather
# than ignored.
DELETE_CLIP_KEYS = ("root", "name")
# `clip` is what this handler's own result calls the deleted clip, and what
# clean_clip takes as its input key - the word is already in circulation
# here for exactly this thing, so a caller reaches for it first.
DELETE_CLIP_SYNONYMS = {"clip": "name"}


def delete_clip(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, DELETE_CLIP_KEYS, "delete_clip",
                       DELETE_CLIP_SYNONYMS)
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
    # #796: listConnections(type="animCurve") matches the U-typed
    # set-driven-key nodes too. They are rig setup, not clip motion - this
    # tool leaves them standing and reports them, so everything below acts
    # on the clip partition ONLY.
    #
    # Classified ONCE, here, while every one of these nodes still exists.
    # A partition taken after the cut would ask nodeType about names this
    # call has already deleted, and real Maya raises "No object matches
    # name" for those - which is a traceback mid-mutation, after the range
    # is cut but before the surviving metadata is written (#796 review
    # defect 1). Names are the currency below; the scene is asked nothing.
    clip_driven = clip_curve_plugs(cmds, driven)
    before_curves, sdk_curves = partition_driven_keys(cmds, driven)
    sdk_named = ", ".join(sdk_curves)
    # #810: what an earlier bake left on the scale channels. Classified
    # here, with everything else, while every node still exists.
    stale_scale, kept_scale = stale_scale_curves(cmds, joints)
    if not clip_driven and not records and not stale_scale:
        raise HandlerError(
            "no clip exists on %s" % root_long,
            hint="author_clip creates one; this tool removes it"
                 + ("; the set-driven keys on this rig (%s) are rig setup "
                    "rather than clip motion, and this tool never removes "
                    "them" % sdk_named if sdk_curves else ""))

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
                # #796: "returns the skeleton to static posing" is only true
                # while no set-driven key stands. Promising it to a caller
                # whose rig has one would be a lie they act on.
                hint="omit `name` to delete every clip"
                     + ("; the set-driven keys on this rig (%s) are kept "
                        "either way - they are rig setup rather than clip "
                        "motion, so those channels stay driven" % sdk_named
                        if sdk_curves
                        else " and return the skeleton to static posing"))

    warnings: List[str] = []
    if not records and clip_driven:
        warnings.append(
            "no clip metadata on %s - deleting %d hand-authored curve "
            "channel(s)" % (_short(root_long), len(clip_driven)))
    if stale_scale:
        warnings.append(
            "reaped %d constant (every key 1.0) scale curve(s) an earlier "
            "retarget bake left on this rig - they animated nothing, and "
            "every later take exported them (#810)" % len(stale_scale))
    if kept_scale:
        warnings.append(
            "kept %d scale curve(s) that are not the bake's constant 1.0 "
            "(%s) - a scale curve carrying real values is not clip motion "
            "and this tool never deletes it" % (len(kept_scale),
                                                 ", ".join(kept_scale[:4])))

    session.auto_checkpoint("delete_clip")
    if stale_scale:
        cmds.delete(*stale_scale)
    before = {m: _points(m) for m in meshes}

    deleted_curves = 0
    reaped_channels: List[str] = []
    if kept:
        # ONE clip out of several: cut its range only. Gaps are NOT
        # re-packed (#718 decision 5) - a take is an explicit range, so a
        # gap costs nothing, and re-packing would move keys the caller did
        # not touch.
        for plug in sorted(clip_driven):
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
        # Keyed by (KIND, name), never by name alone: joint short names,
        # blendShape weight aliases and the literal 'root_position' all
        # share one name space, so a 'jaw' joint and a 'jaw' shape used to
        # overwrite each other here - only one got reaped, and
        # reaped_channels named it once, so nothing in the result revealed
        # the loss (#796 review defect 5).
        orphan_plugs: Dict[Tuple[str, str], List[str]] = {}
        for short in doomed_record.get("joints", []):
            if short in survivors["joints"]:
                continue
            matches = by_short.get(short) or []
            if len(matches) != 1:
                continue  # vanished or ambiguous: never guess (_rot_plugs rule)
            orphan_plugs[("joint", short)] = ["%s.%s" % (matches[0], a)
                                              for a in ROTATE_ATTRS]
        for alias in doomed_record.get("weight_channels", []):
            if alias in survivors["weight_channels"]:
                continue
            node = alias_map.get(alias)
            if node is None or isinstance(node, HandlerError):
                continue
            orphan_plugs[("weight", alias)] = ["%s.%s" % (node, alias)]
        if (doomed_record.get("root_position_used")
                and not survivors["root_position_used"]):
            orphan_plugs[("root", "root_position")] = [
                "%s.%s" % (root_long, a) for a in TRANSLATE_ATTRS]
        # Same #796 split as the two sites above: an orphaned channel whose
        # curve is a set-driven key is rig setup that outlives every clip on
        # the rig, so it is neither reaped nor reported as reaped -
        # reaped_channels is derived from what was actually FOUND to delete,
        # never from what the doomed record declared.
        #
        # Invariant this gate relies on: under #718's self-contained rule,
        # every channel a clip declares stays curve-driven outside the
        # doomed range too (a neighbour's rest pin keeps it keyed there), so
        # an orphaned channel normally has a curve to find here.
        found: set = set()
        reaped: List[Tuple[str, str]] = []
        for (kind, channel), plugs in orphan_plugs.items():
            curves, _ = partition_driven_keys(cmds, {
                plug: cmds.listConnections(plug, source=True,
                                           destination=False,
                                           type="animCurve") or []
                for plug in plugs})
            if curves:
                reaped.append((kind, channel))
                found.update(curves)
        # Qualify ONLY the names that actually collide: the single-kind
        # case - every case before this ticket - reads exactly as it always
        # has, and a collision can no longer hide behind one bare name.
        names = [c for _, c in reaped]
        reaped_channels = [
            c if names.count(c) == 1 else "%s (%s)" % (c, _KIND_LABEL[kind])
            for kind, c in reaped]
        orphan_curves = sorted(found)
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
        # Only the SURVIVORS are re-classified: every node this query can
        # return is still in the scene. `before_curves` was classified up
        # top, before the cut - see the note there (#796 review defect 1).
        remaining, _ = partition_driven_keys(cmds, _anim_curves(
            cmds, _joint_plugs(joints) + weight_plugs))
        deleted_curves = len(set(before_curves) - set(remaining))
        cmds.setAttr("%s.%s" % (root_long, CLIP_ATTR), json.dumps(kept),
                     type="string")
        span_end = max(r["end_frame"] for r in kept)
        cmds.playbackOptions(edit=True, minTime=0, maxTime=span_end,
                             animationStartTime=0, animationEndTime=span_end)
    else:
        if name is not None:
            # The STEPS the teardown is about to take, not a claim that
            # each one landed: what the bind-pose restore could not return
            # (and whether it raised at all) is only knowable after the
            # curves are gone, and is appended below in the same list
            # (#796 review round 3 M2).
            warnings.append(
                "%r was the last clip on this rig - the full teardown ran: "
                "weight channels zeroed, bind pose restored%s"
                % (name, " (set-driven keys still drive some channels)"
                   if sdk_curves else ""))
        doomed = before_curves      # classified up top, pre-deletion
        if doomed:
            cmds.delete(*doomed)
        deleted_curves = len(doomed)
        # Weights back to 0 (weights-all-0 IS the reset, the P5 rule), then
        # the skeleton back to bind - reset_pose's exact logic inline so
        # this call holds ONE checkpoint.
        for plug in weight_plugs:
            if plug in clip_driven:
                cmds.setAttr(plug, 0.0)
        poses = cmds.dagPose(root_long, query=True, bindPose=True) or []
        if poses:
            # #796 review round 3 M2, and this is the COMMON path: any rig
            # with a skinCluster has a bind pose, so the branch below - the
            # only one the driven-key guard reached - is the exception, not
            # the rule. `dagPose -restore` writes the very rotate and
            # translate plugs a surviving set-driven key now feeds, and
            # nothing in this repo has MEASURED what it does about that
            # (see the ticket's live gate). It is written to be right
            # either way: the channels it cannot return to bind are named
            # BEFORE the call, a raise is caught rather than killing a
            # teardown that has already deleted the curves and not yet
            # removed the metadata, and a silent skip reports the same
            # fact through the same words.
            stuck: List[Tuple[str, List[str]]] = []
            for joint in joints:
                blocked = _blocked_transform_attrs(cmds, joint)
                if blocked:
                    stuck.append((_short(joint), blocked))
            restored = False
            try:
                cmds.dagPose(poses[0], restore=True, g=True)
                restored = True
            except Exception as exc:   # noqa: BLE001
                if not stuck:
                    # Nothing here explains it, so this is not #796's
                    # failure and swallowing it would hide a real one.
                    # A rig with no driven keys gets exactly the restore
                    # it got before this ticket, this raise included.
                    raise
                warnings.append(
                    "the bind-pose restore RAISED (%s) - the clip curves "
                    "are already deleted and the clip metadata is removed "
                    "below, so this rig carries no clip, but the skeleton "
                    "may be only partly back at its bind pose; check it "
                    "before exporting" % exc)
            # #796 review round 4 E: only when the restore actually
            # happened. Appended unconditionally, this claimed "restored
            # bindPose1" in the same warnings list as "the bind-pose
            # restore RAISED", about the call that restored nothing.
            if restored and len(poses) > 1:
                warnings.append("%d bind poses exist; restored %s"
                                % (len(poses), poses[0]))
            if stuck:
                # Unlike the fallback below, this branch names TRANSLATE
                # channels too: dagPose restores a whole transform, so a
                # connection on `.translateY` defeats it exactly the way
                # one on `.rotateX` does.
                warnings.append(_stuck_note(
                    stuck, "channel(s)",
                    "and a bind-pose restore cannot return a "
                    "connection-fed plug to bind either - those channels "
                    "are still driven, whatever the rest of the skeleton "
                    "did"))
        else:
            # #796 review defect 2: before this ticket every curve was
            # deleted first, so every rotate plug was free by the time this
            # ran. A surviving set-driven key still feeds one, and setAttr
            # on a connection-fed plug RAISES - the same reasoning the
            # weight loop above already applies, carried to the joints.
            stuck = []
            for joint in joints:
                blocked = _blocked_rotate_attrs(cmds, joint)
                if not blocked:
                    cmds.setAttr(joint + ".rotate", 0.0, 0.0, 0.0)
                    continue
                stuck.append((_short(joint), blocked))
                for attr in ROTATE_ATTRS:
                    if attr not in blocked:
                        cmds.setAttr("%s.%s" % (joint, attr), 0.0)
            warnings.append(
                "no bind pose exists (nothing is bound); %s zeroed, which "
                "is the create_skeleton rest pose"
                % ("the free rotations were" if stuck else "rotations"))
            if stuck:
                warnings.append(_stuck_note(
                    stuck, "rotation(s)",
                    "and a static write to a connection-fed plug raises "
                    "rather than landing; the free channels on those "
                    "joints were zeroed"))
        for attr in (CLIP_ATTR, REST_ATTR):
            if cmds.attributeQuery(attr, node=root_long, exists=True):
                cmds.deleteAttr("%s.%s" % (root_long, attr))

    if sdk_curves:
        # #796: a caller who asked for a clean static rig has to learn WHY
        # the skeleton is still driven - silence here reads as a teardown
        # that failed rather than as one that refused to eat rig setup.
        warnings.append(
            "kept %d set-driven-key curve(s) (%s): they read a driver "
            "attribute rather than time, so they are rig setup rather than "
            "clip motion and this tool leaves them standing - those channels "
            "stay driven" % (len(sdk_curves), sdk_named))

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
        "reaped_scale_curves": len(stale_scale),
        "max_displacement": max_disp,
        "warnings": warnings,
    }


# Every top-level key preview_clip reads; anything else is refused rather
# than ignored.
# `samples` is gone (#797 row 29): the wrapper never sent it, protocol.md
# never listed it, and under the default hw2 renderer Arnold's AA count is
# read by nothing - so the only caller who could pass it was one guessing
# at the API, and the guess did nothing.
PREVIEW_CLIP_KEYS = ("root", "name", "angle", "every_nth", "renderer",
                     "resolution", "zoom")
# `clip` is the word the result uses for the thing being previewed and the
# input key clean_clip takes, so it is the first one a caller tries.
# `stride` is the generic term for sampling every nth frame, which reads
# more naturally than the explicit `every_nth` this tool settled on.
PREVIEW_CLIP_SYNONYMS = {"clip": "name", "stride": "every_nth"}


def preview_clip(params: Dict[str, Any]) -> Dict[str, Any]:
    """A contact sheet of the clip's frames - motion judged the way
    everything here is judged, from pixels, with NO playblast dependency.

    The camera is placed once, at frame 0's framing, and HELD: motion must
    read against a fixed frame, and a camera chasing the subject would hide
    root motion entirely. Perception: no checkpoint, current time restored.
    """
    require_known_keys(params, PREVIEW_CLIP_KEYS, "preview_clip",
                       PREVIEW_CLIP_SYNONYMS)
    # The angle is decided before Maya is touched at all: it needs no scene
    # to judge, and #797's contract is that a param this tool cannot use is
    # named before the call reaches the rig (the #767 pattern).
    angle = params.get("angle") or "three_quarter"
    if angle not in capture.VALID_ANGLES:
        raise HandlerError("unknown angle %r" % angle,
                           hint="valid angles: %s"
                                % ", ".join(capture.VALID_ANGLES))
    # #797 row 21: this tool places its OWN camera - one, held across every
    # frame, because motion must read against a fixed frame - so there is
    # no panel camera for "current" to mean. _run_shots degraded it to
    # three_quarter and labelled every cell "current" anyway.
    if angle == "current":
        refuse_inert(
            "preview_clip", "angle", "when it is 'current'",
            "a preview places its own held camera and renders offscreen, so "
            "there is no viewport camera to keep - 'current' would be shot "
            "as three_quarter under the wrong label",
            hint="name the angle that reads the motion: 'side' for a walk, "
                 "'front' for a face",
        )
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

    renderer = params.get("renderer", "hw2")
    render_params = {
        "renderer": renderer,
        "resolution": params.get("resolution",
                                 DEFAULT_PREVIEW_RESOLUTION),
        # One sample: a preview is many frames and motion does not need
        # refraction. Handed over only on the renderer that READS it - hw2
        # draws the viewport's own image, and _run_shots reports `samples:
        # null` there and warns about any count it was asked for. Asking on
        # a caller's behalf, when the caller cannot ask at all, would put
        # that warning on every default preview (#797 row 29).
        "samples": 1 if renderer == "arnold" else None,
        "zoom": params.get("zoom", 1.0),
    }
    # The held camera's framing box is the UNION of the meshes' bounds
    # across every sampled frame, measured frame by frame - NOT frame 0's
    # box. A held camera is the right call (motion must read against a
    # fixed frame), but holding a frame the subject leaves is not: the
    # #774 CMU walk covers ~4.8 m of root motion, walked out of its
    # frame-0 framing at frame 105, and every later cell was the same
    # byte-identical subject-less render while nothing said so (#780).
    # Framing the whole journey keeps the promise a contact sheet makes.
    previous_time = cmds.currentTime(query=True)
    union_min = [float("inf")] * 3
    union_max = [float("-inf")] * 3
    try:
        for offset in frames:
            cmds.currentTime(start_frame + offset)
            bbox_min, bbox_max = capture._scene_bbox(cmds, meshes)
            union_min = [min(a, b) for a, b in zip(union_min, bbox_min)]
            union_max = [max(a, b) for a, b in zip(union_max, bbox_max)]
    finally:
        cmds.currentTime(previous_time)
    shots = []
    for i, offset in enumerate(frames):
        shots.append({
            "label": "t=%.2fs" % (offset / float(fps)),
            "angle": angle,
            "isolate": None,
            "frame_on": meshes,
            "bbox": (union_min, union_max),
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


# Every top-level key measure_clip reads; anything else is refused (#764).
MEASURE_CLIP_KEYS = ("root", "name", "joints", "contact_joints")
# The clip is named by `name` here, while clean_clip and retarget_clip spell
# the same thing `clip` - so the word a caller carries between them is the
# one that reaches nothing, and `cli` finds no key by prefix (#767).
MEASURE_CLIP_SYNONYMS = {"clip": "name"}


def measure_clip(params: Dict[str, Any]) -> Dict[str, Any]:
    """Motion metrics for one clip - the numbers behind the pictures (#773).

    preview_clip is the eye; this is the ruler. It samples every requested
    joint's world position at every frame of the clip and reports what the
    #773 probe proved DISCRIMINATES between a good clip and a broken one:
    per-joint kinematics, inferred contact runs and their slide, left/right
    peak-speed symmetry, and loop closure. What it deliberately does NOT do
    is score the clip: a foot sliding through its plant is unambiguous and
    is warned about; whether a peak speed is "too fast" is a judgement the
    caller owns, so those come back as raw numbers with worst-frame indices.

    Perception: no checkpoint, current time restored, nothing mutated.
    """
    from ..dispatcher import require_known_keys  # noqa: PLC0415
    from . import motionmath, rigging  # noqa: PLC0415

    require_known_keys(params, MEASURE_CLIP_KEYS, "measure_clip",
                       MEASURE_CLIP_SYNONYMS)
    cmds = _cmds()
    root_long = rigging._require_joint(cmds, params.get("root"))
    records = clip_meta(cmds, root_long)
    if not records:
        raise HandlerError(
            "no clip exists on %s" % root_long,
            hint="author_clip creates one; measure_clip measures it")
    name = params.get("name")
    if name is None and len(records) == 1:
        meta = records[0]
    else:
        meta = next((r for r in records if r["name"] == name), None)
    if meta is None:
        raise HandlerError(
            "no clip named %r on %s (has: %s)"
            % (name, _short(root_long),
               ", ".join(repr(r["name"]) for r in records)),
            hint="a rig carries several clips - pass the one to measure")

    fps = float(meta.get("fps", 30))
    start_frame = int(meta["start_frame"])
    end_frame = int(meta["end_frame"])
    if end_frame <= start_frame:
        raise HandlerError("the clip has zero duration",
                           hint="re-author it; this is broken metadata, "
                                "not a measurement problem")

    hierarchy = rigging._hierarchy_joints(cmds, root_long)
    by_short = {_short(j): j for j in hierarchy}

    def resolve(key: str, default: List[str]) -> List[str]:
        wanted = params.get(key)
        if wanted is None:
            return default
        if (not isinstance(wanted, list) or not wanted
                or not all(isinstance(n, str) for n in wanted)):
            raise HandlerError("%s must be a non-empty list of joint names"
                               % key)
        out = []
        for entry in wanted:
            short = _short(entry)
            if short not in by_short:
                raise HandlerError(
                    "%s: %r is not a joint under %s"
                    % (key, entry, _short(root_long)),
                    hint="joints here: %s" % ", ".join(sorted(by_short)))
            out.append(by_short[short])
        return out

    joints = resolve("joints", hierarchy)
    # Contact defaults to the LEAF joints - the ends of chains are what
    # touches the ground; a hip in contact would mean a very different clip.
    children_of = {j: cmds.listRelatives(j, children=True, type="joint",
                                         fullPath=True) or []
                   for j in hierarchy}
    leaves = [j for j in hierarchy if not children_of[j]]
    contact_joints = resolve("contact_joints", leaves)

    sample_set = sorted(set(joints) | set(contact_joints))
    previous_time = cmds.currentTime(query=True)
    tracks: Dict[str, List[List[float]]] = {j: [] for j in sample_set}
    try:
        for frame in range(start_frame, end_frame + 1):
            cmds.currentTime(frame)
            for j in sample_set:
                tracks[j].append([float(v) for v in cmds.xform(
                    j, query=True, worldSpace=True, translation=True)])
    finally:
        cmds.currentTime(previous_time)

    # Rig height from the first sampled frame: the scale every relative
    # threshold hangs off, reported so the numbers can be re-derived.
    first = [tracks[j][0] for j in sample_set]
    rig_height = max(p[1] for p in first) - min(p[1] for p in first)

    warnings: List[str] = []
    joints_out: Dict[str, Any] = {}
    for j in joints:
        kin = motionmath.joint_kinematics(tracks[j], fps)
        kin["loop_closure"] = motionmath.loop_closure(tracks[j])
        joints_out[_short(j)] = kin

    contacts_out: Dict[str, Any] = {}
    slide_warn_at = motionmath.SLIDE_WARN_FRAC * rig_height
    for j in contact_joints:
        runs = motionmath.contact_runs(tracks[j], fps, rig_height)
        slide = motionmath.max_slide(tracks[j], runs)
        contacts_out[_short(j)] = {
            "runs": [[start_frame + a, start_frame + b] for a, b in runs],
            "max_slide": slide,
        }
        if runs and rig_height > 0 and slide > slide_warn_at:
            warnings.append(
                "%s SLIDES %.4f through a plant (%.1f%% of the rig's %.3f "
                "height) - a planted foot holds its ground position, and "
                "this one wanders. The runs are in the result; re-key the "
                "plant to hold." % (_short(j), slide,
                                    100.0 * slide / rig_height, rig_height))

    symmetry = []
    pairs = motionmath.mirror_pairs([_short(j) for j in joints])
    for left, right in pairs:
        ratio = motionmath.symmetry_ratio(
            joints_out[left]["peak_speed"], joints_out[right]["peak_speed"])
        symmetry.append({"left": left, "right": right,
                         "peak_speed_ratio": ratio})

    return {
        "name": meta["name"],
        "fps": int(fps),
        "frames_sampled": end_frame - start_frame + 1,
        "loop": bool(meta.get("loop")),
        "rig_height": rig_height,
        "thresholds": {
            "contact_height": motionmath.CONTACT_HEIGHT_FRAC * rig_height,
            "contact_speed": motionmath.CONTACT_SPEED_FRAC * rig_height,
            "slide_warn": slide_warn_at,
        },
        "joints": joints_out,
        "contacts": contacts_out,
        "symmetry": symmetry,
        "warnings": warnings,
    }


measure_clip.no_undo_chunk = True
