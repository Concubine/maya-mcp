"""Blend shapes, phase 5 of #602 (#691): create_blendshape,
set_blendshape_weights.

Targets are ordinary meshes authored with the existing modeling/sculpt tools;
this module only wires deltas and measures what they do. The deformer goes
FRONT-OF-CHAIN (before any skinCluster): a shape models the neutral surface
and the skin carries the shaped surface to the pose, which is what makes an
elbow corrective correct at a bent elbow. Every number is a distance in scene
units MEASURED from vertices after the write (#636), never echoed - the
target's own vertices are not trusted even for max_delta, because what
matters is what the DEFORMER does to the base, not what the sculpt looked
like.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from ..dispatcher import HandlerError, require_known_keys
from . import clip, naming, sculpt, sculpt_math, session

MAX_TARGETS = 20
# Below this fraction of the base's bbox diagonal, a target's measured delta
# is float noise, not a shape: the target is (near-)identical to the base -
# almost always a duplicate that was never sculpted. Deliberately FAR below
# the 1e-2 noop ratio the pose/sculpt ops use: a 1 mm blink on a 2 m figure
# is a legitimate 5e-4 shape and must not warn.
ZERO_DELTA_RATIO = 1e-7


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _short(name: str) -> str:
    return name.split("|")[-1]


def _points(mesh_long: str) -> List[float]:
    """World-space vertex positions. Module-level so tests monkeypatch it:
    FakeCmds cannot deform, and the measurement is the part only a real Maya
    can supply (the rigging._set_skin_weights precedent)."""
    return sculpt.vertex_positions(_cmds(), mesh_long)


def _blend_node_for(cmds, mesh_shape: str,
                    warnings: List[str]) -> Optional[str]:
    """The mesh's ONE blendShape node, or None. One is all there can be:
    create_blendshape ADDS targets to an existing node instead of stacking a
    second deformer - stacked blendShapes are stacked skinClusters'
    weights-unexplainable failure with a different node type. If the mesh
    already carries more than one (hand-stacked outside this tool), silence
    is never an answer: name every ignored node in `warnings` rather than
    quietly picking one."""
    nodes = cmds.ls(cmds.listHistory(mesh_shape, pruneDagObjects=True) or [],
                    type="blendShape") or []
    if len(nodes) > 1:
        warnings.append(
            "%s carries %d blendShape nodes (%s) - only one is expected; "
            "using %r and ignoring %s" % (
                mesh_shape, len(nodes), ", ".join(nodes), nodes[0],
                ", ".join(nodes[1:])))
    return nodes[0] if nodes else None


def _aliases(cmds, node: str) -> List[str]:
    """Weight alias names in index order - the target-name contract."""
    return cmds.listAttr(node + ".w", multi=True) or []


def _validated_targets(cmds, mesh_long: str, targets,
                       existing: List[str]) -> List[Tuple[str, str]]:
    """[(name, target long name)] or a refusal. Runs BEFORE the checkpoint."""
    if (not isinstance(targets, list) or not targets
            or len(targets) > MAX_TARGETS):
        raise HandlerError(
            "targets must be a list of 1..%d {name, target_mesh} entries"
            % MAX_TARGETS,
            hint='e.g. targets=[{"name": "brow_raise", '
                 '"target_mesh": "humanoid_brow"}]')
    seen_names = set(existing)
    seen_meshes: Dict[str, str] = {}
    out: List[Tuple[str, str]] = []
    for i, entry in enumerate(targets):
        if not isinstance(entry, dict):
            raise HandlerError("targets[%d] must be {name, target_mesh}" % i)
        name = entry.get("name")
        if (not isinstance(name, str) or not name
                or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)):
            raise HandlerError(
                "targets[%d].name %r must be a plain identifier (letters, "
                "digits, underscore; not starting with a digit)" % (i, name),
                hint="the name becomes the weight attribute, the "
                     "set_blendshape_weights key, and the exported Shape "
                     "record name")
        if name in existing:
            raise HandlerError(
                "target name %r already exists on this mesh's blendShape"
                % name,
                hint="existing targets: %s" % ", ".join(existing))
        if name in seen_names:
            raise HandlerError("target name %r appears twice in this call"
                               % name)
        seen_names.add(name)
        t_long, _shape = naming.require_mesh(
            cmds, str(entry.get("target_mesh") or ""))
        if t_long == mesh_long:
            raise HandlerError(
                "targets[%d]: the base mesh cannot be its own target" % i)
        if t_long in seen_meshes:
            raise HandlerError(
                "targets[%d] reuses %s, already consumed by target %r"
                % (i, t_long, seen_meshes[t_long]),
                hint="each target mesh is deleted after wiring, so one mesh "
                     "can carry only one target")
        seen_meshes[t_long] = name
        out.append((name, t_long))
    return out


# Every top-level key create_blendshape reads. Anything else is refused
# rather than ignored (#767). Both synonyms are result-field names: the
# result calls the node `blend_shape` and each target entry names its mesh
# `target_mesh`, so a caller who read one result reaches for those as
# inputs - the exact #764 shape, and neither shares a 3-char prefix with
# `mesh`, so require_known_keys' fallback could never suggest it.
CREATE_BLENDSHAPE_KEYS = ("mesh", "targets")
CREATE_BLENDSHAPE_SYNONYMS = {"base_mesh": "mesh", "blend_shape": "mesh",
                              "object": "mesh", "shape": "targets",
                              "shapes": "targets", "morphs": "targets"}


def create_blendshape(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, CREATE_BLENDSHAPE_KEYS, "create_blendshape",
                       CREATE_BLENDSHAPE_SYNONYMS)
    cmds = _cmds()
    mesh_long, mesh_shape = naming.require_mesh(
        cmds, str(params.get("mesh") or ""))
    warnings: List[str] = []
    node = _blend_node_for(cmds, mesh_shape, warnings)
    existing = _aliases(cmds, node) if node else []
    resolved = _validated_targets(cmds, mesh_long, params.get("targets"),
                                  existing)

    base_count = cmds.polyEvaluate(mesh_long, vertex=True)
    for name, t_long in resolved:
        t_count = cmds.polyEvaluate(t_long, vertex=True)
        if t_count != base_count:
            raise HandlerError(
                "target %r topology does not match: %s has %d vertices, %s "
                "has %d" % (name, _short(mesh_long), base_count,
                            _short(t_long), t_count),
                hint="a target must be a same-topology copy of the base "
                     "(maya_duplicate, then sculpt) - there is no wrap "
                     "fallback")

    # #771, MEASURED (evals/correctives_probe/probe_bs_hang.py): creating a
    # NEW blendShape with frontOfChain=True while a deltaMush sits in the
    # history hangs Maya's deformer-reorder for 20+ minutes on an 8k-vert
    # mesh. Every neighbouring operation is instant - adding a target to an
    # EXISTING node under the same mush measured 0.0 s - so only the
    # node-creation path refuses. Checked AFTER the topology gate so the
    # caller learns about a bad target before being told to tear down the
    # mush. The hint reads the live settings off the node - the re-apply it
    # prescribes must be able to reproduce them, and nothing else records
    # them.
    if node is None:
        mushes = cmds.ls(cmds.listHistory(mesh_shape, pruneDagObjects=True)
                         or [], type="deltaMush") or []
        if mushes:
            mush = mushes[0]
            try:
                settings = (
                    "smoothing_iterations=%d, smoothing_step=%g, "
                    "pin_border_vertices=%s, distance_weight=%g" % (
                        cmds.getAttr(mush + ".smoothingIterations"),
                        cmds.getAttr(mush + ".smoothingStep"),
                        bool(cmds.getAttr(mush + ".pinBorderVertices")),
                        cmds.getAttr(mush + ".distanceWeight")))
            except Exception:  # noqa: BLE001 - the hint must not fail the refusal
                settings = "its settings were unreadable - note them by hand"
            raise HandlerError(
                "%s carries a deltaMush (%s) and no blendShape yet - "
                "creating the blendShape under it would hang Maya's "
                "deformer reorder (measured: 20+ minutes on an 8k-vertex "
                "mesh)" % (mesh_long, mush),
                hint="author blend shapes BEFORE the mush - or "
                     "delete_objects the mush, wire the targets, and "
                     "apply_delta_mush again with the SAME settings (%s)"
                     % settings)

    session.auto_checkpoint("create_blendshape")

    if node is None:
        node = cmds.blendShape(
            *[t for _, t in resolved], mesh_long,
            frontOfChain=True,
            name=naming.unique_name(cmds, _short(mesh_long) + "_shapes"))[0]
        new_indices = list(range(len(resolved)))
    else:
        # NOT len(existing): the alias list is dense, but the node's weight
        # multi need not be - a target removed outside this tool (Shape
        # Editor, blendShape -e -rm) leaves a hole, and len(existing) then
        # names an OCCUPIED index. Landing the edit there doesn't error -
        # aliasAttr just silently renames whatever alias already sat on it.
        occupied = cmds.getAttr(node + ".w", multiIndices=True) or []
        start = max(occupied) + 1 if occupied else 0
        new_indices = []
        for offset, (_name, t_long) in enumerate(resolved):
            cmds.blendShape(node, edit=True,
                            target=(mesh_long, start + offset, t_long, 1.0))
            new_indices.append(start + offset)
    for idx, (name, _t) in zip(new_indices, resolved):
        cmds.aliasAttr(name, "%s.w[%d]" % (node, idx))

    # MEASURED per target (#636): drive each new weight to 1 alone and
    # re-read the BASE mesh through the real deformer. Pre-existing targets
    # keep whatever weights they held - constant on both sides of the
    # comparison, so they cancel.
    baseline = _points(mesh_long)
    extent = sculpt_math.bbox_extent(baseline)
    targets_out: List[Dict[str, Any]] = []
    for idx, (name, _t_long) in zip(new_indices, resolved):
        plug = "%s.w[%d]" % (node, idx)
        cmds.setAttr(plug, 1.0)
        max_delta = sculpt_math.max_displacement(baseline, _points(mesh_long))
        cmds.setAttr(plug, 0.0)
        if max_delta < max(extent, 1.0) * ZERO_DELTA_RATIO:
            warnings.append(
                "target %r measured max_delta %.3g against a %.3g-wide "
                "mesh - the target is (near-)identical to the base. It was "
                "wired anyway, but a duplicate that was never sculpted is "
                "the usual cause" % (name, max_delta, extent))
        targets_out.append({"name": name, "max_delta": max_delta,
                            "vertex_count": base_count})

    # Consume the targets: the deltas live in the deformer now, and a stale
    # editable copy invites sculpting a mesh that no longer feeds anything
    # (the boolean-operand reap logic).
    doomed = [t for _n, t in resolved if cmds.objExists(t)]
    if doomed:
        cmds.delete(*doomed)

    return {"mesh": mesh_long, "blend_shape": node,
            "targets": targets_out, "warnings": warnings}


# Every top-level key set_blendshape_weights reads (#767). `blend_shape` is
# what the result calls the node this command operates on, so addressing it
# by that name is the plausible miss; it shares no prefix with `mesh`.
SET_BLENDSHAPE_WEIGHTS_KEYS = ("mesh", "weights")
# `targets`/`target` are what the weights dict is KEYED BY, so a caller
# naturally names the payload after its keys rather than its values.
SET_BLENDSHAPE_WEIGHTS_SYNONYMS = {"blend_shape": "mesh", "object": "mesh",
                                   "targets": "weights", "target": "weights",
                                   "values": "weights"}


def set_blendshape_weights(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, SET_BLENDSHAPE_WEIGHTS_KEYS,
                       "set_blendshape_weights",
                       SET_BLENDSHAPE_WEIGHTS_SYNONYMS)
    cmds = _cmds()
    mesh_long, mesh_shape = naming.require_mesh(
        cmds, str(params.get("mesh") or ""))
    warnings: List[str] = []
    node = _blend_node_for(cmds, mesh_shape, warnings)
    if node is None:
        raise HandlerError(
            "%s has no blendShape" % mesh_long,
            hint="create_blendshape wires targets first")
    aliases = _aliases(cmds, node)
    clip.guard_static_weights(cmds, node, aliases, "set_blendshape_weights")
    weights = params.get("weights")
    if not isinstance(weights, dict) or not weights:
        raise HandlerError(
            "weights must be a non-empty map of target name to 0..1",
            hint='e.g. weights={"brow_raise": 0.5}; 0 for every target is '
                 'the reset')
    for name, value in weights.items():
        if name not in aliases:
            raise HandlerError(
                "%r is not a target of %s" % (name, node),
                hint="targets here: %s" % ", ".join(aliases))
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not 0.0 <= float(value) <= 1.0):
            raise HandlerError(
                "weights[%r] must be a number in 0..1, got %r"
                % (name, value))
        # #771: only the REQUESTED weights are checked - a corrective on
        # one target must not lock every other target's hand control.
        # (Time-based animCurve sources are the clip guard's job, above,
        # and that one deliberately covers ALL aliases.)
        src, kind = clip.driven_weight_source(cmds, "%s.%s" % (node, name))
        if kind is not None and kind != "clip":
            clip.refuse_driven_weight("set_blendshape_weights", name, src,
                                      kind)

    session.auto_checkpoint("set_blendshape_weights")

    # Sequential on purpose: each weight lands and is measured against the
    # state the previous ones left, in call order - so per_target reports
    # what each shape actually contributed, and the total is the honest
    # before/after (which can be SMALLER than a step when shapes oppose).
    before = _points(mesh_long)
    prev = before
    per_target: List[Dict[str, Any]] = []
    changed = False
    for name, value in weights.items():
        attr = "%s.%s" % (node, name)
        old = float(cmds.getAttr(attr))
        cmds.setAttr(attr, float(value))
        now = _points(mesh_long)
        achieved = float(cmds.getAttr(attr))
        per_target.append({
            "name": name,
            "weight": achieved,
            "max_displacement": sculpt_math.max_displacement(prev, now)})
        prev = now
        if abs(achieved - old) > 1e-9:
            changed = True

    if not changed:
        warnings.append(
            "every requested weight already held its value - nothing moved")
    out_weights = {a: float(cmds.getAttr("%s.%s" % (node, a)))
                   for a in aliases}
    return {"mesh": mesh_long, "blend_shape": node,
            "weights": out_weights,
            "max_displacement": sculpt_math.max_displacement(before, prev),
            "per_target": per_target, "warnings": warnings}
