"""Can this command write that plug, and what it says when it cannot.

One guard, asked before the first mutation, wherever a handler makes a STATIC
write to a channel the user is entitled to have locked, constrained, keyed or
wired (#802). `correctives._joint_rotation_writable` was the only site in the
package that asked; five commands did not, and every one of them shipped a
claim it had not delivered.

WHAT MAYA ACTUALLY DOES, measured on 2027 (apiVersion 20270200) by
`evals/static_write_probe_802.py` and `..._802b.py`. The ticket's premise -
"Maya raises 'locked or connected' and the handler lets that RuntimeError out
raw" - turned out to be true of only half the cases, and the other half is
worse:

  * A LOCK, a plain `connectAttr`, or an expression makes `setAttr` RAISE.
    On a compound the message is "A child attribute of 'x.translate' is
    locked or connected", so a compound write is all-or-nothing.
  * A CONSTRAINT, an anim curve, a pairBlend or a set-driven key does NOT.
    `setAttr(joint.rotate, 77, 77, 77)` on an orientConstraint-driven joint
    returns cleanly, reads back 77, and reverts to the constraint's value at
    the next evaluation. The write is FUTILE, not refused.
  * `cmds.xform` NEVER raises. It writes the children it can and silently
    skips the rest - so `xform(t=...)` over a locked translateY moves X and
    Z and leaves Y, with no exception to catch. `cmds.move` and `cmds.hide`
    behave the same way.

So a `try/except` around the write cannot work, in either direction: half the
failures raise nothing at all, and the ones that do raise have already left a
partial write behind. The only correct shape is the one this module
implements - ASK FIRST, refuse before mutating, and where a pass must not
refuse (a render still has to render), name what it could not move.

Both outcomes are one defect from the caller's seat: the handler cannot
deliver the write it was asked for. So this module does not distinguish them
in its verdict, only in its wording.

COMPOUND AND CHILD DO NOT SEE EACH OTHER. `getAttr(".rotate", lock=True)` is
False while rotateX is locked, and `listConnections` on a compound returns
None while all three children are constraint-fed. So every question is asked
of the plug, its children (when it is a compound) and its parent (when it is
a child) - `family()` below - which is what `_joint_rotation_writable`
already did and why it was the model the ticket named. SIBLINGS are
deliberately absent: a locked rotateX does not stop `setAttr(rotateY)`
(measured A05).
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from ..dispatcher import HandlerError

# The compounds a transform write reaches - `shear`'s children are not XYZ,
# which is why this is a table rather than a rule - plus, since #804, the
# colour compounds a shader write reaches. MEASURED (evals/
# look_orphans_probe_804.py): with a file node on kit.emissionColorR alone,
# `setAttr(kit.emissionColor, ...)` raises "A child attribute of
# 'kit.emissionColor' is locked or connected", `listConnections` on the
# compound answers [], and the sibling emissionColorG still takes a write -
# exactly the transform asymmetry, so the same family rule applies.
_CHILDREN: Dict[str, Sequence[str]] = {
    "translate": ("translateX", "translateY", "translateZ"),
    "rotate": ("rotateX", "rotateY", "rotateZ"),
    "scale": ("scaleX", "scaleY", "scaleZ"),
    "jointOrient": ("jointOrientX", "jointOrientY", "jointOrientZ"),
    "preferredAngle": ("preferredAngleX", "preferredAngleY",
                       "preferredAngleZ"),
    "rotateAxis": ("rotateAxisX", "rotateAxisY", "rotateAxisZ"),
    "rotatePivot": ("rotatePivotX", "rotatePivotY", "rotatePivotZ"),
    "scalePivot": ("scalePivotX", "scalePivotY", "scalePivotZ"),
    "shear": ("shearXY", "shearXZ", "shearYZ"),
}
# Shader colour compounds (material.py's _COLOR_ATTRS and the slots pbr maps),
# spelled here rather than imported: material imports this module.
_COLOR_COMPOUNDS = ("baseColor", "color", "emissionColor", "specularColor",
                    "incandescence", "transparency", "transmissionColor",
                    "subsurfaceColor", "coatColor", "sheenColor")
for _attr in _COLOR_COMPOUNDS:
    _CHILDREN[_attr] = tuple("%s%s" % (_attr, c) for c in "RGB")
_CHILDREN["normalCamera"] = ("normalCameraX", "normalCameraY", "normalCameraZ")
COMPOUND_OF: Dict[str, str] = {
    child: parent for parent, kids in _CHILDREN.items() for child in kids}

# `xform -pivots` sets BOTH pivots (modeling.transform's own comment says so),
# so a guard for that flag has to ask about both.
PIVOT_PLUGS = ("rotatePivot", "scalePivot")


class Blocked(object):
    """One reason one plug cannot take the static write it was asked for.

    `plug` is what the handler wanted to write; `at` is where the obstacle
    actually sits, which is a different plug whenever the compound/child
    fold is what makes the write fail. Naming both is the difference
    between "pose_skeleton cannot pose |r|a" and a caller who can go and
    unlock the one axis that is in the way.
    """

    __slots__ = ("plug", "at", "reason", "source", "kind", "joint")

    def __init__(self, plug: str, at: str, reason: str,
                 source: Optional[str] = None,
                 kind: Optional[str] = None,
                 joint: bool = False) -> None:
        self.plug = plug
        self.at = at
        self.reason = reason          # "locked" | "driven"
        self.source = source          # the feeding plug, when driven
        self.kind = kind              # clip.driven_weight_source's verdict
        self.joint = joint            # the owning node is a joint (hint only)

    def __repr__(self) -> str:        # pragma: no cover - debugging aid
        return "Blocked(%r, %r, %r, %r, %r, joint=%r)" % (
            self.plug, self.at, self.reason, self.source, self.kind,
            self.joint)


def family(plug: str) -> List[str]:
    """`plug` plus every plug whose state Maya folds into a write to it.

    The plug itself, its children when it is a compound, its parent when it
    is a child. Never its siblings - see the module docstring.
    """
    node, _, attr = plug.rpartition(".")
    out = [plug]
    out.extend("%s.%s" % (node, child) for child in _CHILDREN.get(attr, ()))
    parent = COMPOUND_OF.get(attr)
    if parent:
        out.append("%s.%s" % (node, parent))
    return out


def _driver(cmds, plug: str):
    # clip imports render, and render imports this module, so the one
    # classifier in the package has to be reached at call time rather than
    # at import time. Deliberately clip's and not a second copy: #771 and
    # #796 both shipped a wrong hint from a second site that classified for
    # itself, which is the whole reason this module exists.
    from . import clip  # noqa: PLC0415 - avoid an import cycle
    return clip.driven_weight_source(cmds, plug)


def blocker(cmds, plug: str) -> List[Blocked]:
    """Everything that stops a static write to `plug`; [] if nothing does.

    The whole family, not the first hit: every caller hands this a COMPOUND,
    so a rigger who locked three axes of one joint is ONE plug here, and
    stopping at rotateX would name one axis, send them to unlock it, and
    refuse again twice more (review catch). A plug is asked about once even
    when the lock and the connection both hold it - the lock is the one a
    single command clears, so it is the one named.
    """
    found = []
    joint = None
    for candidate in family(plug):
        block = None
        if cmds.getAttr(candidate, lock=True):
            block = Blocked(plug, candidate, "locked")
        else:
            source, kind = _driver(cmds, candidate)
            if source is not None:
                block = Blocked(plug, candidate, "driven", source, kind)
        if block is None:
            continue
        if joint is None:
            # Asked once per plug and only on the refusal path: the hint
            # for a curve differs by whether delete_clip can reach it.
            joint = cmds.nodeType(plug.rpartition(".")[0]) == "joint"
        block.joint = joint
        found.append(block)
    return found


def blockers(cmds, plugs: Iterable[str]) -> List[Blocked]:
    """Every obstacle on every plug in `plugs`, in order.

    All of them, not the first: `delete_objects` names every missing object
    in one message rather than sending the caller round the loop once per
    name, and a rigger who locked three axes deserves the same courtesy.
    """
    found = []
    seen = set()
    for plug in plugs:
        if plug in seen:
            continue
        seen.add(plug)
        found.extend(blocker(cmds, plug))
    return found


def because(block: Blocked) -> str:
    """The clause that says what is in the way, from the plug's side.

    Public since #798: clip's lost-write notes carry it inline, so a note
    about a key that vanished names the lock or the connection itself
    instead of pointing at a note that may not exist."""
    if block.reason == "locked":
        return "%s is locked" % block.at
    kind = {"clip": "an animation curve",
            "driven_key": "a set-driven key",
            "corrective": "a corrective (poseInterpolator)",
            "texture": "a texture map"}.get(
                block.kind, "a connection")
    return "%s is driven by %s (%s)" % (block.at, block.source, kind)


def describe(block: Blocked, what: str) -> str:
    """One sentence naming the write that cannot be delivered, and why.

    Used verbatim as a WARNING by the passes that must not refuse, so it
    carries the consequence too - a caller reading a warnings list has no
    exception text to tell them what it cost them.
    """
    if block.reason == "locked":
        return ("%s could not write %s: %s, and Maya refuses that write"
                % (what, block.plug, because(block)))
    return ("%s could not write %s: %s, so a static write here is either "
            "refused or overridden on the next evaluation"
            % (what, block.plug, because(block)))


def _hint(block: Blocked) -> str:
    """The fix, which differs per kind - a wrong one is worse than none.

    Not `clip.refuse_driven_weight`: that speaks about a blendShape weight
    alias, and it lets "other" through with a keying-specific hint because
    a KEY can land through a pairBlend where a STATIC write cannot. Every
    kind is fatal to a static write, so the wording had to be its own.
    """
    if block.reason == "locked":
        return ("unlock the channel (setAttr -lock false %s) and call again"
                % block.at)
    if block.kind == "clip":
        if block.joint:
            return ("delete_clip removes the curves and returns the channel "
                    "to static control; author_clip re-authors the motion "
                    "afterwards")
        # delete_clip takes a skeleton ROOT and nothing else, so sending the
        # owner of a keyed camera or a keyed prop there is the wrong-hint
        # class this module exists to end (review catch).
        return ("delete or disconnect the animation curve %s to return the "
                "channel to static control - delete_clip cannot be aimed at "
                "%s, it takes a skeleton root"
                % (block.source.split(".")[0], block.plug.rpartition(".")[0]))
    if block.kind == "driven_key":
        return ("remove the driven key (delete its curve node) to return "
                "the channel to static control - delete_clip deliberately "
                "leaves those standing, because rig setup is not clip "
                "motion")
    if block.kind == "corrective":
        return ("pose the driver joint instead (that IS the corrective's "
                "control), or delete_objects the interpolator to return the "
                "channel to static control")
    if block.kind == "texture":
        # A mapped slot cannot carry a constant too (#804). The map is the
        # authored look; the constant is the mistake nine times in ten.
        return ("%s is mapped by %s - drop the param and keep the map, or "
                "re-map it (assign_pbr, for a standardSurface slot it knows, "
                "replaces the old map) instead of writing a constant over it"
                % (block.at, block.source.split(".")[0]))
    return ("a constraint, expression or blend node owns %s; disconnect it, "
            "or aim this command at a channel the rig leaves free"
            % block.at)


def refuse(what: str, found: Sequence[Blocked],
           consequence: Optional[str] = None,
           hint_tail: Optional[str] = None) -> None:
    """Raise the refusal for everything `blockers` found. Never returns.

    `hint_tail` is the one thing a caller may add to the advice: what to do
    about a channel this tool cannot write is generic, but what to do
    INSTEAD is command-specific (add_corrective can tell the caller to
    re-author the motion afterwards; transform cannot). The diagnosis stays
    here so it cannot drift; only the epilogue is the caller's.
    """
    if not found:  # pragma: no cover - callers check first
        raise ValueError("refuse() called with nothing to refuse")
    reasons = "; ".join(because(b) for b in found)
    plugs = ", ".join(sorted({b.plug for b in found}))
    tail = consequence or ("nothing was written - this command refuses "
                           "before it mutates rather than leaving the "
                           "scene half-written")
    hints = []
    for block in found:
        text = _hint(block)
        if text not in hints:
            hints.append(text)
    if hint_tail:
        hints.append(hint_tail)
    raise HandlerError(
        "%s cannot write %s: %s. %s" % (what, plugs, reasons, tail),
        hint="; ".join(hints))


def guard(cmds, plugs: Iterable[str], what: str,
          consequence: Optional[str] = None,
          hint_tail: Optional[str] = None) -> None:
    """Refuse `what` unless every plug in `plugs` can take a static write.

    Call it BEFORE the checkpoint and before the first write. That ordering
    is the point: a refusal discovered mid-mutation has already cost the
    caller a half-posed rig, and the restore step then masks the real error
    (the review catch `_joint_rotation_writable` was written for).
    """
    found = blockers(cmds, plugs)
    if found:
        refuse(what, found, consequence, hint_tail)


def transform_plugs(node: str, channels: Iterable[str]) -> List[str]:
    """The compound plugs a transform write touches, for one node.

    `pivots` expands to both pivots because that is what `xform -pivots`
    writes; everything else is the compound of the same name. Compounds and
    not children, deliberately: `xform` skips the child it cannot write and
    keeps the others, so the unit a caller cares about is the whole channel.
    """
    out = []
    for channel in channels:
        if channel == "pivots":
            out.extend("%s.%s" % (node, p) for p in PIVOT_PLUGS)
        else:
            out.append("%s.%s" % (node, channel))
    return out
