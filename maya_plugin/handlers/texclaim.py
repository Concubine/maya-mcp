"""The scene's claim about what texture maps each material carries (#714).

Maya's FBX exporter silently drops procedural texture networks: a `file`
node survives as a Texture+Video record pair carrying the image basename,
and anything else (noise, ramp, layeredTexture) vanishes with no API-visible
signal. MEASURED in evals/drifter_live.py's texture probe: 1 Texture + 1
Video for the file node, zero occurrences of the procedural node names.

The export gate needs to know what the scene THINKS it has before it can
say what the file lost - and nothing records that: no metadata node, and
node naming is inconsistent across the two authoring tools (mcpTex_* in
texture_recipes.py, <material>_<slot>_* in pbr.py). So the only honest
answer is to walk the shading graph. This module is that walk, split the
usual way: pure classification here, one cmds-touching enumerator below.

It is deliberately shared with the phase-2 bake tool: two walkers would be
two things to get wrong.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from . import material, pbr

# Every attribute this toolbox's authoring surface can drive. DERIVED from
# the slot tables rather than copied, so a new slot cannot silently fall out
# of the claim. A hand-wired texture on an attr outside this union is not
# claimed - it surfaces as an "unclaimed record" WARNING at the gate, never
# a violation (refusing a file we failed to enumerate would be worse than
# the gap).
_ATTRS: List[str] = [attr for attr, _kind in pbr.SLOTS.values()]
for _slots in material.SHADER_SLOTS.values():
    _ATTRS.extend(_slots.values())
AUTHORED_ATTRS = tuple(sorted(set(_ATTRS)))

# attr -> the semantic slot name callers know it by. First table wins; the
# two agree wherever they overlap (baseColor is "color" in both).
SLOT_FOR_ATTR: Dict[str, str] = {}
for _slot, (_attr, _kind) in pbr.SLOTS.items():
    SLOT_FOR_ATTR.setdefault(_attr, _slot)
for _slots in material.SHADER_SLOTS.values():
    for _slot, _attr in _slots.items():
        SLOT_FOR_ATTR.setdefault(_attr, _slot)

# The only intermediates the walk steps THROUGH. bump2d carries a map into
# normalCamera (assign_pbr and the noise_bump recipe both use it); reverse
# is assign_pbr's invert. place2dTexture is placement, not content, and is
# never a terminal or a pass-through - it feeds the file node's uv plugs,
# which the walk does not follow.
PASS_THROUGH_TYPES = ("bump2d", "reverse")

# Plugs that select ONE channel of an image. FBX carries the image, never
# the swizzle, so a claim wired this way is reported as semantics_lost.
_SWIZZLE_PLUGS = ("outColorR", "outColorG", "outColorB", "outAlpha")

# A pathological or hand-built graph must not hang the export.
MAX_DEPTH = 8


def classify(terminals: List[Dict[str, Any]]) -> str:
    """"file", "procedural", or "value" for one slot's terminal set.

    A slot is a file claim ONLY when every terminal is a file node. Any
    non-file contributor anywhere upstream makes it procedural - a
    layeredTexture mixing two real files is procedural, because the MIX is
    what the exporter loses, not the images.
    """
    if not terminals:
        return "value"
    return ("file" if all(t["type"] == "file" for t in terminals)
            else "procedural")


def _file_terminal(cmds, node: str) -> Dict[str, Any]:
    """The record for a `file` terminal: where its image is and whether it
    is actually there. `on_disk` matters at the gate - the exporter's
    behaviour for a missing image is UNMEASURED (#714 probe P5), so a
    claim whose image is absent only warns."""
    try:
        path = str(cmds.getAttr(node + ".fileTextureName") or "")
    except Exception:
        path = ""
    try:
        colorspace = str(cmds.getAttr(node + ".colorSpace") or "")
    except Exception:
        colorspace = ""
    return {"node": node, "type": "file", "file_path": path,
            "basename": os.path.basename(path) if path else "",
            "on_disk": bool(path) and os.path.isfile(path),
            "colorspace": colorspace}


def _other_terminal(node: str, node_type: str) -> Dict[str, Any]:
    return {"node": node, "type": node_type, "file_path": None,
            "basename": None, "on_disk": None, "colorspace": None}


def _walk_upstream(cmds, plug: str) -> tuple:
    """(terminals, via, swizzles) reached upstream of `plug`.

    Steps THROUGH PASS_THROUGH_TYPES only; everything else terminates. All
    upstream branches are followed (a layeredTexture is itself a terminal,
    so its inputs are never entered).

    Two DIFFERENT things can make a node reappear, and conflating them was
    a real bug (#714 fix round 1): a legitimate ACYCLIC reconvergence - one
    file feeding two attributes of the same bump2d, or the same file
    reaching the slot by two branches - must resolve to ONE terminal, not a
    false "unresolved(depth)" that turns a clean file claim procedural. A
    genuine CYCLE (a node that is its own ancestor on this walk) must still
    be capped and reported. So two separate guards, checked in this order:

      - `ancestors` (carried per frontier entry) - the pass-through nodes
        currently open on THIS path. A node reached that is already its own
        ancestor is a real cycle -> "unresolved(depth)", checked FIRST,
        because a cyclic node is also always in `resolved` by the time the
        cycle closes and would otherwise be silently swallowed by the next
        check instead of reported.
      - `resolved` - every node already turned into a terminal, or already
        pushed onto the frontier for exploration. Reached again from ANY
        other branch (not an ancestor), it is skipped silently: the file
        (or the pass-through subtree beneath it) was already accounted for.

    The depth cap is a backstop for both: a pathological or hand-built
    graph must not hang the export even without a literal cycle. The
    returned terminal list is deduplicated by node name as a final safety
    net, since two sibling branches can each independently trip the
    cap/cycle check for the same node before either is recorded.
    """
    terminals: List[Dict[str, Any]] = []
    via: List[str] = []
    swizzles: List[str] = []
    resolved = set()
    frontier = [(plug, 0, frozenset())]
    while frontier:
        current, depth, ancestors = frontier.pop(0)
        sources = cmds.listConnections(current, source=True,
                                       destination=False, plugs=True) or []
        for source in sources:
            node = source.split(".")[0]
            attr = source.split(".", 1)[1] if "." in source else ""
            if attr in _SWIZZLE_PLUGS and attr not in swizzles:
                swizzles.append(attr)
            if node in ancestors:
                terminals.append(_other_terminal(node, "unresolved(depth)"))
                continue
            if node in resolved:
                continue
            if depth >= MAX_DEPTH:
                terminals.append(_other_terminal(node, "unresolved(depth)"))
                continue
            resolved.add(node)
            node_type = cmds.nodeType(node)
            if node_type in PASS_THROUGH_TYPES:
                if node_type not in via:
                    via.append(node_type)
                frontier.append((node, depth + 1, ancestors | {node}))
            elif node_type == "file":
                terminals.append(_file_terminal(cmds, node))
            else:
                terminals.append(_other_terminal(node, node_type))

    deduped: List[Dict[str, Any]] = []
    seen_nodes = set()
    for terminal in terminals:
        if terminal["node"] in seen_nodes:
            continue
        seen_nodes.add(terminal["node"])
        deduped.append(terminal)
    return deduped, via, swizzles


def _semantics_lost(swizzles: List[str], via: List[str],
                    terminals: List[Dict[str, Any]]) -> List[str]:
    """What survives as an image but not as a wiring decision.

    FBX carries the image reference. It does not carry which channel was
    selected, an inverting reverse node, or a Raw colorspace declaration -
    all three are consumer-side rewires. Reported, never gated: refusing
    them would refuse assign_pbr's own recommended mask workflow.
    """
    lost: List[str] = []
    for plug in swizzles:
        lost.append("channel swizzle %s" % plug)
    if "reverse" in via:
        lost.append("reverse-invert")
    if any((t.get("colorspace") or "") == "Raw" for t in terminals):
        lost.append("Raw colorspace")
    return lost


def material_claims(cmds, shapes: List[str]) -> List[Dict[str, Any]]:
    """What the materials on `shapes` claim to carry, per slot.

    Scoped to the shapes being exported, the same way shape aliases and
    clips are. Never matches node NAMES (mcpTex_* vs <material>_<slot>_*
    are both real conventions in this toolbox) - only graph topology and
    node types.
    """
    claims: List[Dict[str, Any]] = []
    seen_pairs = set()
    for shape in shapes:
        for sg in cmds.listSets(object=shape, type=1) or []:
            shaders = cmds.listConnections(sg + ".surfaceShader",
                                           source=True) or []
            if not shaders:
                continue
            shader = shaders[0]
            for attr in AUTHORED_ATTRS:
                if not cmds.attributeQuery(attr, node=shader, exists=True):
                    continue
                key = (shader, attr)
                terminals, via, swizzles = _walk_upstream(
                    cmds, "%s.%s" % (shader, attr))
                classification = classify(terminals)
                if classification == "value":
                    continue
                if key in seen_pairs:
                    # One material on several exported shapes: claim it
                    # once, but record every mesh that wears it.
                    for claim in claims:
                        if (claim["material"], claim["attr"]) == key:
                            if shape not in claim["meshes"]:
                                claim["meshes"].append(shape)
                    continue
                seen_pairs.add(key)
                claims.append({
                    "mesh": shape,
                    "meshes": [shape],
                    "material": shader,
                    "sg": sg,
                    "attr": attr,
                    "slot": SLOT_FOR_ATTR.get(attr),
                    "classification": classification,
                    "terminals": terminals,
                    "via": via,
                    "semantics_lost": _semantics_lost(swizzles, via,
                                                      terminals),
                })
    return claims
