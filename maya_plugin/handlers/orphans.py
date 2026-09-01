"""What a look handler leaves behind when it replaces a network - and how to
find it, and how to delete only the part nothing else uses (#804).

Three commands are correct about the network THEY build and wrong about the
one that was already there: assign_pbr force-replaces a slot's connection
(the old file node and its place2dTexture stay), setup_lighting's
replace_existing deletes light transforms (the ramp or hdri file feeding the
old dome's colour stays), and bake_textures already had its own sweep for the
network a bake replaces. MEASURED (evals/look_orphans_probe_804.py, Maya
2027): Maya never reaps a disconnected shading node - after
`connectAttr(new.outColor, mat.baseColor, force=True)` the old file node's
only remaining output is `defaultTextureList1`, its place2dTexture's only
output is `defaultRenderUtilityList1`, and deleting a dome's shape AND
transform leaves its ramp with `defaultTextureList1` as its one consumer.

Two measured facts shape the helpers here:

  * A file node's INPUTS include `defaultColorMgtGlobals` (four connections),
    so an upstream walk cannot take "everything reachable" - it takes only
    node TYPES this package itself builds on a slot (`SWEEPABLE_TYPES`). A
    hand-built layeredTexture the user wired in survives a re-texture; the
    tool cleans up the kinds of network it makes, and reports what it kept.
  * Maya auto-wires every node created with asTexture=True or asUtility=True
    into one of two bookkeeping singletons at creation. `real_outputs`
    excludes exactly those, by NAME (texbake's measured constant, kept in one
    place now) - "still used by something" must not count Maya's own list.

`sweep` deletes to a fixpoint: removing a `reverse` can newly orphan the
file that fed it, and the file's removal newly orphans its place2dTexture.
"""
from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

# Maya auto-wires EVERY asTexture=True / asUtility=True node into one of these
# at creation, before this tool connects it to anything - MEASURED under
# mayapy (Maya 2027, texbake Task 3) and again by the #804 probe. Matched by
# NAME on purpose: a type match would widen a destructive check to nodes
# nobody has measured (texbake's own history is a false-orphan bug from
# comparing at the wrong granularity).
BOOKKEEPING_NODES = ("defaultTextureList1", "defaultRenderUtilityList1")

# Never a candidate, whatever feeds what: the colour-management singleton
# feeds every file node (measured: four connections per file node).
NEVER_SWEEP = ("defaultColorMgtGlobals",)

# The node types this package builds on a shader slot or a light colour, and
# therefore the only types an orphan walk follows and a sweep may delete.
# pbr: file, place2dTexture, bump2d, reverse. lighting: ramp, file.
# texture_recipes: noise, ramp, bump2d, layeredTexture, file. surfdetail /
# meshmaps: file, place2dTexture, bump2d.
SWEEPABLE_TYPES = frozenset({
    "file", "place2dTexture", "bump2d", "reverse", "ramp", "noise",
    "layeredTexture",
})

# The subset that IS a texture wherever it feeds. A `reverse` is not: the
# classic IK/FK switch drives joint channels through one, and calling that
# "a texture map" with an assign_pbr hint is the wrong-hint class the single
# classifier exists to end (review catch). A reverse counts as a texture's
# front end only when what it feeds is a shader (clip.driven_weight_source).
TEXTURE_TYPES = frozenset({"file", "ramp", "noise", "layeredTexture", "bump2d"})

MAX_DEPTH = 8


def real_outputs(cmds, node: str) -> List[str]:
    """`node`'s outgoing connections with Maya's bookkeeping singletons
    excluded. Empty means nothing but Maya's own lists uses it any more."""
    outputs = cmds.listConnections(node, source=False, destination=True) or []
    return [out for out in outputs if out not in BOOKKEEPING_NODES]


def upstream_network(cmds, start: str,
                     types: Iterable[str] = SWEEPABLE_TYPES) -> List[str]:
    """Every node of a sweepable type reachable UPSTREAM of `start` (a plug
    such as `kit.baseColor`, or a node), in discovery order, de-duplicated.

    Captured BEFORE the connection at `start` is replaced or its owner
    deleted - afterwards the edge this walk follows is gone. A node of any
    other type ends the walk on that branch: the tool does not reach
    through what it did not build.
    """
    wanted = set(types)
    found: List[str] = []
    frontier = [(start, 0)]
    seen = {start.split(".")[0]}   # a cycle back to the start is not a candidate
    while frontier:
        current, depth = frontier.pop(0)
        if depth > MAX_DEPTH:
            continue
        sources = cmds.listConnections(current, source=True,
                                       destination=False) or []
        for node in sources:
            node = node.split(".")[0]
            if node in seen or node in NEVER_SWEEP:
                continue
            seen.add(node)
            try:
                node_type = cmds.nodeType(node)
            except Exception:  # noqa: BLE001 - a node that cannot answer is not ours
                continue
            if node_type not in wanted:
                continue
            found.append(node)
            frontier.append((node, depth + 1))
    return found


def sweep(cmds, candidates: Iterable[str]) -> Tuple[List[str], List[Tuple[str, List[str]]]]:
    """Delete whichever of `candidates` has no REAL output left, to a
    fixpoint. Returns (deleted, survivors) where each survivor is
    (node, [what still uses it]) - the caller turns those into warnings,
    because a silent keep hides exactly the shared-network case a sweep
    must not destroy."""
    remaining = [n for n in dict.fromkeys(candidates) if n not in NEVER_SWEEP]
    deleted: List[str] = []
    survivors: List[Tuple[str, List[str]]] = []
    changed = True
    while changed and remaining:
        changed = False
        survivors = []
        for node in remaining:
            if not cmds.objExists(node):
                continue
            outputs = real_outputs(cmds, node)
            if outputs:
                survivors.append((node, outputs))
                continue
            cmds.delete(node)
            deleted.append(node)
            changed = True
        remaining = [n for n, _ in survivors]
    return deleted, survivors


def survivor_warnings(survivors: Sequence[Tuple[str, List[str]]],
                      what: str) -> List[str]:
    """One warning per node a sweep kept, naming what still uses it."""
    return ["%s was not deleted after %s - still used by %s"
            % (node, what, ", ".join(sorted(set(outs))))
            for node, outs in survivors]
