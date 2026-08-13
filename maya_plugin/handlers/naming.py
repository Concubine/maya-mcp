"""Name helpers: collision-free naming and object resolution with hints."""

from __future__ import annotations

from typing import Tuple

from ..dispatcher import HandlerError

_MAX_SUFFIX = 999


def unique_name(cmds, requested: str) -> str:
    """The requested name, or the first free deterministic _NNN suffix."""
    if not cmds.objExists(requested):
        return requested
    for i in range(1, _MAX_SUFFIX + 1):
        candidate = "%s_%03d" % (requested, i)
        if not cmds.objExists(candidate):
            return candidate
    raise HandlerError(
        "no free name for %r after %d suffixes" % (requested, _MAX_SUFFIX),
        hint="choose a different base name",
    )


def require_object(cmds, name: str) -> str:
    """Resolve `name` to exactly one canonical long name."""
    matches = cmds.ls(name, long=True) or []
    if not matches:
        raise HandlerError(
            "object %r not found" % name,
            hint="call maya_get_scene_graph to list objects; use canonical long names",
        )
    if len(matches) > 1:
        raise HandlerError(
            "name %r is ambiguous (%d matches)" % (name, len(matches)),
            hint="use the canonical long name, e.g. %s" % matches[0],
        )
    return matches[0]


def require_mesh(cmds, name: str) -> Tuple[str, str]:
    """Resolve to (transform long name, mesh shape long name) or fail with a hint."""
    transform = require_object(cmds, name)
    shapes = (
        cmds.listRelatives(transform, shapes=True, fullPath=True, noIntermediate=True)
        or []
    )
    if not shapes or cmds.nodeType(shapes[0]) != "mesh":
        raise HandlerError(
            "%s is not a polygon mesh" % transform,
            hint="this tool needs a mesh; call maya_get_scene_graph with filter='mesh'",
        )
    return transform, shapes[0]
