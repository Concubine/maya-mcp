"""get_object_info: structured readback of one object (design doc 5.1).

Sections are summaries, never raw component data - uvs and history report
counts and node types so a large mesh cannot blow the response budget.
The shading section is how every M2 authoring tool is verified.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..dispatcher import HandlerError
from . import naming

SECTIONS = ("transform", "mesh_stats", "uvs", "shading", "history")
DEFAULT_SECTIONS = ["transform", "mesh_stats"]


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _mesh_stats(shape: str) -> Dict[str, Any]:
    from . import meshcheck  # noqa: PLC0415 - keep import cheap headless

    return meshcheck.mesh_stats(shape)


def _shape_of(cmds, transform: str):
    shapes = (
        cmds.listRelatives(transform, shapes=True, fullPath=True, noIntermediate=True)
        or []
    )
    return shapes[0] if shapes else None


def _transform_section(cmds, name: str) -> Dict[str, Any]:
    return {
        "translate": cmds.xform(name, query=True, worldSpace=True, translation=True),
        "rotate": cmds.xform(name, query=True, worldSpace=True, rotation=True),
        "scale": cmds.xform(name, query=True, worldSpace=True, scale=True),
    }


def _shading_section(cmds, shape: str) -> Dict[str, Any]:
    sgs = cmds.listSets(object=shape, type=1) or []
    materials: List[str] = []
    per_face = False
    for sg in sgs:
        for member in cmds.sets(sg, query=True) or []:
            if ".f[" in member:
                per_face = True
        # Query the .surfaceShader plug specifically (same idiom as
        # scene.py/meshcheck.py's material lookup) rather than an unfiltered
        # cmds.listConnections(sg, source=True, type=None): passing an
        # explicit type=None to real Maya's listConnections raises
        # "RuntimeError: -t expects type STRING" (verified live, Maya 2027),
        # and an unfiltered query on the SG node itself pulls in unrelated
        # connected nodes (partitions, render utility lists, ...), not just
        # the assigned shader.
        for mat in cmds.listConnections(sg + ".surfaceShader", source=True) or []:
            if mat not in materials:
                materials.append(mat)
    return {"shading_groups": list(sgs), "materials": materials, "per_face": per_face}


def _uvs_section(cmds, shape: str) -> Dict[str, Any]:
    sets = cmds.polyUVSet(shape, query=True, allUVSets=True) or []
    return {"uv_sets": list(sets), "count": len(sets)}


def _history_section(cmds, shape: str) -> Dict[str, Any]:
    nodes = cmds.listHistory(shape) or []
    types = []
    for node in nodes:
        t = cmds.nodeType(node)
        if t not in types:
            types.append(t)
    return {"node_count": len(nodes), "node_types": types}


def get_object_info(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    name = naming.require_object(cmds, str(params.get("name") or ""))
    include = params.get("include") or DEFAULT_SECTIONS
    if not isinstance(include, list) or not include:
        raise HandlerError(
            "include must be a non-empty list of section names",
            hint="valid sections: %s" % ", ".join(SECTIONS),
        )
    unknown = [s for s in include if s not in SECTIONS]
    if unknown:
        raise HandlerError(
            "unknown section(s): %s" % ", ".join(str(u) for u in unknown),
            hint="valid sections: %s" % ", ".join(SECTIONS),
        )

    out: Dict[str, Any] = {"name": name}
    shape = _shape_of(cmds, name)
    needs_shape = {"mesh_stats", "uvs", "shading", "history"}
    if shape is None and needs_shape.intersection(include):
        raise HandlerError(
            "%s has no shape node" % name,
            hint="mesh_stats/uvs/shading/history need a shape; groups support "
            "only the transform section",
        )

    if "transform" in include:
        out["transform"] = _transform_section(cmds, name)
    if "mesh_stats" in include:
        out["mesh_stats"] = _mesh_stats(shape)
    if "uvs" in include:
        out["uvs"] = _uvs_section(cmds, shape)
    if "shading" in include:
        out["shading"] = _shading_section(cmds, shape)
    if "history" in include:
        out["history"] = _history_section(cmds, shape)
    return out


get_object_info.no_undo_chunk = True
