"""get_scene_graph: compact paginated outline of the scene.

NEVER returns component data (vertices, faces, UVs) — a raw dump of a Maya
scene is a session-killing bug, not a feature. Names are canonical long names
so follow-up calls are unambiguous.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..dispatcher import HandlerError

MAX_OBJECTS_CAP = 500
DEFAULT_MAX_OBJECTS = 200

# Maya's four built-in cameras; permanent clutter, excluded from the outline.
_DEFAULT_CAMERAS = {"|persp", "|top", "|front", "|side"}


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _entry(cmds, transform: str) -> Dict[str, Any]:
    shapes = cmds.listRelatives(transform, shapes=True, fullPath=True) or []
    shape = shapes[0] if shapes else None
    obj_type = cmds.nodeType(shape) if shape else "group"

    tris: Optional[int] = None
    verts: Optional[int] = None
    if obj_type == "mesh":
        try:
            tris = cmds.polyEvaluate(shape, triangle=True)
            verts = cmds.polyEvaluate(shape, vertex=True)
        except Exception:
            pass  # empty/degenerate mesh; stats stay unknown

    material: Optional[str] = None
    if shape is not None:
        engines = cmds.listConnections(shape, type="shadingEngine") or []
        if engines:
            shaders = cmds.listConnections(engines[0] + ".surfaceShader") or []
            material = shaders[0] if shaders else None

    bbox = cmds.exactWorldBoundingBox(transform)
    parents = cmds.listRelatives(transform, parent=True, fullPath=True) or [None]

    return {
        "name": transform,
        "type": obj_type,
        "tris": tris,
        "verts": verts,
        "bbox_min": list(bbox[:3]),
        "bbox_max": list(bbox[3:]),
        "material": material,
        "parent": parents[0],
        "visible": bool(cmds.getAttr(transform + ".visibility")),
    }


def get_scene_graph(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()

    filt = params.get("filter")
    max_objects = params.get("max_objects", DEFAULT_MAX_OBJECTS)
    if not isinstance(max_objects, int) or max_objects < 1:
        max_objects = DEFAULT_MAX_OBJECTS
    max_objects = min(max_objects, MAX_OBJECTS_CAP)

    offset = 0
    cursor = params.get("cursor")
    if cursor is not None:
        try:
            offset = int(cursor)
            if offset < 0:
                raise ValueError
        except (TypeError, ValueError):
            raise HandlerError(
                "invalid cursor %r" % cursor,
                hint="pass the cursor string returned by the previous call, or omit it",
            ) from None

    transforms = sorted(
        t for t in (cmds.ls(type="transform", long=True) or [])
        if t not in _DEFAULT_CAMERAS
    )

    entries: List[Dict[str, Any]] = []
    needle = filt.lower() if isinstance(filt, str) and filt else None
    for transform in transforms:
        entry = _entry(cmds, transform)
        if needle is None or needle in entry["name"].lower() or needle in entry["type"].lower():
            entries.append(entry)

    page = entries[offset : offset + max_objects]
    next_offset = offset + len(page)
    return {
        "objects": page,
        "total": len(entries),
        "cursor": str(next_offset) if next_offset < len(entries) else None,
    }
