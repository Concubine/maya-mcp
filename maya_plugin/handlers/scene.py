"""get_scene_graph: compact paginated outline of the scene.

NEVER returns component data (vertices, faces, UVs) — a raw dump of a Maya
scene is a session-killing bug, not a feature. Names are canonical long names
so follow-up calls are unambiguous.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..dispatcher import HandlerError, require_known_keys
from . import units

MAX_OBJECTS_CAP = 500
DEFAULT_MAX_OBJECTS = 200

# Maya's four built-in cameras; permanent clutter, excluded from the outline.
_DEFAULT_CAMERAS = {"|persp", "|top", "|front", "|side"}


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _shape_and_type(cmds, transform: str):
    """Cheap resolve: first non-intermediate shape and its type ('group' if none)."""
    shapes = (
        cmds.listRelatives(transform, shapes=True, fullPath=True, noIntermediate=True)
        or []
    )
    shape = shapes[0] if shapes else None
    return shape, (cmds.nodeType(shape) if shape else "group")


def _entry(cmds, transform: str, shape: Optional[str], obj_type: str) -> Dict[str, Any]:
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


# Every top-level key get_scene_graph reads. Anything else is refused rather
# than ignored (#767): an unread key does not fail, it succeeds and does
# something else.
GET_SCENE_GRAPH_KEYS = ("filter", "max_objects", "cursor")
# `name` and `type` are what every returned object calls its own fields, so a
# caller narrowing the outline reaches for the word the result taught it -
# and `filter` is the one key that matches against both. `limit` is the
# ordinary English word for a page size. `offset` is the integer this handler
# decodes the cursor into; it is named in no result field, which is exactly
# why a caller resuming a page would invent it.
GET_SCENE_GRAPH_SYNONYMS = {
    "limit": "max_objects", "type": "filter", "name": "filter",
    "offset": "cursor",
}


def get_scene_graph(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, GET_SCENE_GRAPH_KEYS, "get_scene_graph",
                       GET_SCENE_GRAPH_SYNONYMS)
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

    # Cheap pass first: pagination must bound WORK, not just response bytes.
    # Names (and, only when a filter needs it, shape types) decide membership;
    # the expensive per-object stats run solely for the page being returned.
    needle = filt.lower() if isinstance(filt, str) and filt else None
    matches: List[tuple] = []  # (transform, resolved (shape, type) or None)
    for transform in transforms:
        if needle is None or needle in transform.lower():
            matches.append((transform, None))
            continue
        shape, obj_type = _shape_and_type(cmds, transform)
        if needle in obj_type.lower():
            matches.append((transform, (shape, obj_type)))

    page_items = matches[offset : offset + max_objects]
    objects: List[Dict[str, Any]] = []
    for transform, resolved in page_items:
        shape, obj_type = resolved or _shape_and_type(cmds, transform)
        objects.append(_entry(cmds, transform, shape, obj_type))

    next_offset = offset + len(page_items)
    return {
        "objects": objects,
        "total": len(matches),
        "cursor": str(next_offset) if next_offset < len(matches) else None,
        # Every bbox above is a bare number until this says what it means
        # (maya-mcp #634). On EVERY page, and on an empty result too - a caller
        # asserting the unit must not have to fetch objects to learn it.
        "units": units.units_block(cmds),
    }
