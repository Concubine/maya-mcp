"""maya_bake_textures: turn procedural texture networks into file textures.

#714 phase 2. Phase 1 made the loss VISIBLE - export_fbx now names every
procedural map Maya's FBX exporter drops. This is the cure: bake those
networks to real images and rewire the scene to use them, so what an agent
judged in a render is what actually ships.

The rewire is PERSISTENT on purpose. A temporary export-time bake would
ship pixels nobody ever looked at; making it a scene edit means the next
render IS the deliverable, and the builder re-judges the real artifact
before exporting. export_fbx never bakes.

Two probe measurements shape the refusals below, and neither is caution:
convertSolidTx does NOT raise on a UV-less mesh - it writes a flat, useless
image - and the FBX export never validates that a texture file exists or is
any good. Nothing downstream catches a bad bake, so this tool checks its
own work (pngprobe) and refuses what it cannot bake honestly.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from ..dispatcher import HandlerError
from . import naming, pbr, texclaim

RESOLUTIONS = (256, 512, 1024, 2048, 4096)
DEFAULT_RESOLUTION = 1024


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def validate(params: Dict[str, Any], cmds) -> Dict[str, Any]:
    """Everything checkable before a single node is touched."""
    raw = params.get("meshes")
    names = [raw] if isinstance(raw, str) else list(raw or [])
    if not names or not all(isinstance(n, str) and n.strip() for n in names):
        raise HandlerError(
            "missing required param 'meshes'",
            hint="pass the mesh(es) whose materials should be baked; "
                 "maya_get_scene_graph lists what the scene contains")

    shapes = []
    for name in names:
        _transform, shape = naming.require_mesh(cmds, name)
        if shape not in shapes:
            shapes.append(shape)

    out_dir = params.get("out_dir")
    if not isinstance(out_dir, str) or not out_dir.strip():
        raise HandlerError(
            "missing required param 'out_dir'",
            hint="an absolute directory the baked images are written to - "
                 "there is no default, because a guessed location is how "
                 "bake files get lost from a delivery")
    if not os.path.isabs(out_dir):
        raise HandlerError(
            "out_dir %r must be absolute" % out_dir,
            hint="a relative path resolves against Maya's working directory, "
                 "which is not where you think it is")
    if not os.path.isdir(out_dir):
        raise HandlerError(
            "out_dir %r does not exist" % out_dir,
            hint="this tool does not make directories it was not asked to "
                 "make (the export_fbx rule)")

    resolution = params.get("resolution", DEFAULT_RESOLUTION)
    if (isinstance(resolution, bool) or not isinstance(resolution, int)
            or resolution not in RESOLUTIONS):
        raise HandlerError(
            "resolution must be one of %s"
            % ", ".join(str(r) for r in RESOLUTIONS),
            hint="a bake is square; these are the sizes this tool writes")

    slots = params.get("slots")
    if slots is not None:
        if (not isinstance(slots, list)
                or not all(isinstance(s, str) for s in slots)):
            raise HandlerError("slots must be a list of slot names",
                               hint="omit it to bake every procedural slot")
        unknown = [s for s in slots if s not in pbr.SLOTS]
        if unknown:
            raise HandlerError(
                "unknown slot(s): %s" % ", ".join(unknown),
                hint="valid slots: %s" % ", ".join(sorted(pbr.SLOTS)))

    return {"meshes": shapes, "out_dir": out_dir, "resolution": resolution,
            "slots": list(slots) if slots is not None else None}


def _uv_count(cmds, shape: str) -> int:
    try:
        return int(cmds.polyEvaluate(shape, uvcoord=True) or 0)
    except Exception:  # noqa: BLE001 - a shape that cannot answer has none
        return 0


def plan_bakes(cmds, shapes: List[str],
               slots: Optional[List[str]]) -> Tuple[List[Dict[str, Any]],
                                                    List[str]]:
    """What this call would bake, and what it is skipping. Pre-mutation.

    One job per (material, attr) - NOT per mesh. MEASURED (probe P2d/P2e):
    convertSolidTx samples through UVs, not world geometry - a transform
    change AND a real vertex deformation both left the bake byte-identical
    - so a material worn by several requested meshes bakes ONCE.

    SCOPE LIMIT on that measurement: it was taken on placement-less `noise`
    networks (the recipes this toolbox authors). A network driven through a
    place2dTexture with non-default placement is NOT covered by it; such a
    job carries a warning rather than a refusal, because the bake is still
    per-material by construction and the warning is what a reviewer needs
    to re-measure if it ever matters.
    """
    for shape in shapes:
        if _uv_count(cmds, shape) == 0:
            raise HandlerError(
                "%s has no UVs - a bake samples through UV space, and Maya "
                "does NOT refuse this: convertSolidTx silently writes a "
                "flat, useless image (MEASURED, #714 probe P2c)" % shape,
                hint="maya_uv_atlas creates UVs (project='box' is enough for "
                     "tiling detail); bake after that")

    claims = texclaim.material_claims(cmds, shapes)
    jobs: List[Dict[str, Any]] = []
    warnings: List[str] = []
    seen = set()
    for claim in claims:
        slot = claim["slot"]
        if slots is not None and slot not in slots:
            continue
        if claim["classification"] == "file":
            warnings.append(
                "%s.%s is already file-backed - nothing to bake"
                % (claim["material"], claim["attr"]))
            continue
        key = (claim["material"], claim["attr"])
        if key in seen:
            continue
        seen.add(key)

        kind = pbr.SLOTS[slot][1] if slot in pbr.SLOTS else "color"
        terminals = claim["terminals"]
        if len(terminals) != 1:
            raise HandlerError(
                "%s.%s is driven by %d terminals (%s) - this tool bakes one "
                "network per slot and will not guess which to keep"
                % (claim["material"], claim["attr"], len(terminals),
                   ", ".join(t["node"] for t in terminals)),
                hint="simplify the network, or bake the slots separately")
        terminal = terminals[0]

        bump_node = None
        if kind == "normal":
            if "bump2d" not in claim["via"]:
                raise HandlerError(
                    "%s.%s is driven procedurally with no bump2d in the "
                    "chain - a tangent-space normal bake is a different "
                    "capability this tool does not have"
                    % (claim["material"], claim["attr"]),
                    hint="author the normal through a bump2d (the noise_bump "
                         "recipe does), or bake the other slots and leave "
                         "this one")
            bump_node = _bump_node_for(cmds, claim)

        if any(t["type"] == "unresolved(depth)" for t in terminals):
            raise HandlerError(
                "%s.%s's network could not be resolved (a cycle, or deeper "
                "than the walk follows) - refusing rather than baking a "
                "guess" % (claim["material"], claim["attr"]),
                hint="simplify the shading network feeding this slot")

        if _has_placement(cmds, terminal["node"]):
            warnings.append(
                "%s.%s samples through a place2dTexture - the bake is still "
                "written once per material, but #714's mesh-independence "
                "measurement covered placement-less networks only; check the "
                "result on each mesh that wears it"
                % (claim["material"], claim["attr"]))

        jobs.append({
            "material": claim["material"], "sg": claim["sg"],
            "attr": claim["attr"], "slot": slot, "kind": kind,
            "terminal_plug": _bake_source_plug(terminal, kind),
            "mesh": claim["mesh"], "meshes": list(claim["meshes"]),
            "via": list(claim["via"]), "bump_node": bump_node,
            "basename": "%s_%s_baked.png" % (claim["material"], slot),
        })
        if len(claim["meshes"]) > 1:
            warnings.append(
                "%s is worn by %d meshes (%s) - baking it changes the look "
                "of every one of them, which is the point, but it is not "
                "reversible without maya_undo"
                % (claim["material"], len(claim["meshes"]),
                   ", ".join(claim["meshes"])))

    if not jobs and not warnings:
        # Truly nothing: no claim at all (not even a file-backed one) on the
        # requested mesh(es). A file-backed-only scene is NOT this case - it
        # exits above with jobs=[] and a "nothing to bake" warning per slot,
        # which is a legitimate no-op, not a refusal.
        raise HandlerError(
            "no procedural texture network to bake on the requested "
            "mesh(es)%s" % (" for slot(s) %s" % ", ".join(slots)
                            if slots else ""),
            hint="maya_export_fbx's textures.dropped_maps names what a "
                 "scene actually carries; a file-backed slot needs no bake")
    return jobs, warnings


def _bake_source_plug(terminal: Dict[str, Any], kind: str) -> str:
    """Which plug convertSolidTx samples.

    MEASURED (probe P3): `noise.outColorR` bakes directly as a usable
    scalar, so a height/scalar bake needs no intermediate node. Colour
    slots bake the terminal's outColor.
    """
    if kind in ("scalar", "normal"):
        return "%s.outColorR" % terminal["node"]
    return "%s.outColor" % terminal["node"]


def _bump_node_for(cmds, claim: Dict[str, Any]) -> Optional[str]:
    """The bump2d between the terminal and the shader, if any. The rewire
    keeps it (bumpDepth is the authored look) and only replaces what feeds
    its bumpValue."""
    sources = cmds.listConnections("%s.%s" % (claim["material"],
                                              claim["attr"]),
                                   source=True, destination=False) or []
    for node in sources:
        try:
            if cmds.nodeType(node) == "bump2d":
                return node
        except Exception:  # noqa: BLE001 - a node that cannot answer is not it
            pass
    return None


def _has_placement(cmds, node: str) -> bool:
    try:
        sources = cmds.listConnections(node, source=True, destination=False) or []
        return any(cmds.nodeType(n) == "place2dTexture" for n in sources)
    except Exception:  # noqa: BLE001 - unknown placement is reported as none
        return False
