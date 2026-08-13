"""Structured modeling (§5.3): reliability layer over maya.cmds.

Tools address objects by name only, never selection. Requested names that
collide get deterministic _NNN suffixes; canonical long names come back.
Transform-writing handlers record to the ledger and surface live-user edits
as warnings (#577 req 4c).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..dispatcher import HandlerError
from . import ledger, naming

PRIMITIVE_KINDS = ("cube", "sphere", "cylinder", "plane", "torus", "cone")
MAX_DIVISIONS = 200


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _vec3(params: Dict[str, Any], key: str) -> Optional[List[float]]:
    value = params.get(key)
    if value is None:
        return None
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 3
        or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)
    ):
        raise HandlerError(
            "%s must be a list of 3 numbers, got %r" % (key, value),
            hint="e.g. %s=[0, 1.5, 0]" % key,
        )
    return [float(v) for v in value]


def _apply_xform(cmds, name: str, translate, rotate, scale, relative: bool) -> None:
    kwargs: Dict[str, Any] = {"relative": True} if relative else {"worldSpace": True, "absolute": True}
    if translate is not None:
        cmds.xform(name, translation=translate, **kwargs)
    if rotate is not None:
        cmds.xform(name, rotation=rotate, **kwargs)
    if scale is not None:
        if relative:
            cmds.xform(name, scale=scale, relative=True)
        else:
            cmds.xform(name, scale=scale)


def _long(cmds, name: str) -> str:
    matches = cmds.ls(name, long=True) or [name]
    return matches[0]


def create_primitive(params: Dict[str, Any]) -> Dict[str, Any]:
    kind = params.get("kind")
    if kind not in PRIMITIVE_KINDS:
        raise HandlerError(
            "unknown primitive kind %r" % kind,
            hint="valid kinds: %s" % ", ".join(PRIMITIVE_KINDS),
        )
    requested = params.get("name")
    if not isinstance(requested, str) or not requested.strip():
        raise HandlerError(
            "missing required param 'name'",
            hint="pass the object name to create, e.g. name='golem_torso'",
        )
    divisions = params.get("divisions", 1)
    if not isinstance(divisions, int) or not (1 <= divisions <= MAX_DIVISIONS):
        raise HandlerError(
            "divisions must be an integer 1..%d" % MAX_DIVISIONS,
            hint="1 = Maya defaults; higher multiplies subdivision counts",
        )
    cmds = _cmds()
    name = naming.unique_name(cmds, requested)

    creators = {
        "cube": lambda: cmds.polyCube(
            name=name, constructionHistory=False,
            subdivisionsWidth=divisions, subdivisionsHeight=divisions,
            subdivisionsDepth=divisions,
        ),
        "plane": lambda: cmds.polyPlane(
            name=name, constructionHistory=False,
            subdivisionsWidth=divisions, subdivisionsHeight=divisions,
        ),
        "sphere": lambda: cmds.polySphere(
            name=name, constructionHistory=False,
            subdivisionsAxis=20 * divisions, subdivisionsHeight=20 * divisions,
        ),
        "cylinder": lambda: cmds.polyCylinder(
            name=name, constructionHistory=False,
            subdivisionsAxis=20 * divisions, subdivisionsHeight=divisions,
        ),
        "cone": lambda: cmds.polyCone(
            name=name, constructionHistory=False,
            subdivisionsAxis=20 * divisions, subdivisionsHeight=divisions,
        ),
        "torus": lambda: cmds.polyTorus(
            name=name, constructionHistory=False,
            subdivisionsAxis=20 * divisions, subdivisionsHeight=20 * divisions,
        ),
    }
    created = creators[kind]()[0]
    long_name = _long(cmds, created)
    _apply_xform(
        cmds, long_name,
        _vec3(params, "translate"), _vec3(params, "rotate"), _vec3(params, "scale"),
        relative=False,
    )
    ledger.record(cmds, long_name)
    return {"name": long_name, "warnings": []}


def duplicate(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    source = naming.require_object(cmds, str(params.get("name") or ""))
    requested = params.get("new_name")
    if not isinstance(requested, str) or not requested.strip():
        raise HandlerError(
            "missing required param 'new_name'",
            hint="pass the name for the copy, e.g. new_name='golem_arm_L'",
        )
    warnings = [w for w in [ledger.check(cmds, source)] if w]
    new_name = naming.unique_name(cmds, requested)
    copy = cmds.duplicate(source, name=new_name, returnRootsOnly=True)[0]
    long_name = _long(cmds, copy)
    _apply_xform(
        cmds, long_name,
        _vec3(params, "translate"), _vec3(params, "rotate"), _vec3(params, "scale"),
        relative=True,
    )
    ledger.record(cmds, long_name)
    return {"name": long_name, "warnings": warnings}


def transform(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    names = params.get("names")
    if not isinstance(names, list) or not names:
        raise HandlerError(
            "names must be a non-empty list of object names",
            hint='e.g. names=["|golem|torso"]',
        )
    translate = _vec3(params, "translate")
    rotate = _vec3(params, "rotate")
    scale = _vec3(params, "scale")
    if translate is None and rotate is None and scale is None:
        raise HandlerError(
            "nothing to do",
            hint="pass at least one of translate, rotate, scale",
        )
    relative = params.get("relative", True) is not False
    resolved = [naming.require_object(cmds, str(n)) for n in names]

    warnings: List[str] = []
    objects: List[Dict[str, Any]] = []
    for name in resolved:
        moved = ledger.check(cmds, name)
        if moved:
            warnings.append(moved)
        _apply_xform(cmds, name, translate, rotate, scale, relative)
        ledger.record(cmds, name)
        objects.append(
            {
                "name": name,
                "translate": cmds.xform(name, query=True, worldSpace=True, translation=True),
                "rotate": cmds.xform(name, query=True, worldSpace=True, rotation=True),
                "scale": cmds.xform(name, query=True, worldSpace=True, scale=True),
            }
        )
    return {"objects": objects, "warnings": warnings}


def group(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    names = params.get("names")
    if not isinstance(names, list) or not names:
        raise HandlerError(
            "names must be a non-empty list", hint='e.g. names=["|a", "|b"]'
        )
    resolved = [naming.require_object(cmds, str(n)) for n in names]
    requested = params.get("group_name")
    if not isinstance(requested, str) or not requested.strip():
        raise HandlerError(
            "missing required param 'group_name'", hint="e.g. group_name='golem'"
        )
    grp = cmds.group(*resolved, name=naming.unique_name(cmds, requested))
    return {"name": _long(cmds, grp), "warnings": []}


def parent(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    child = naming.require_object(cmds, str(params.get("child") or ""))
    target = naming.require_object(cmds, str(params.get("parent") or ""))
    moved = cmds.parent(child, target)
    long_name = _long(cmds, moved[0])
    ledger.forget(child)  # its long name just changed
    ledger.record(cmds, long_name)
    return {"name": long_name, "warnings": []}


def rename(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    old = naming.require_object(cmds, str(params.get("name") or ""))
    requested = params.get("new_name")
    if not isinstance(requested, str) or not requested.strip():
        raise HandlerError(
            "missing required param 'new_name'", hint="pass the new object name"
        )
    new = cmds.rename(old, naming.unique_name(cmds, requested))
    ledger.forget(old)
    long_name = _long(cmds, new)
    ledger.record(cmds, long_name)
    return {"name": long_name, "warnings": []}


def delete_objects(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    names = params.get("names")
    if not isinstance(names, list) or not names:
        raise HandlerError(
            "names must be a non-empty list", hint='e.g. names=["|scrap"]'
        )
    missing = [str(n) for n in names if not cmds.objExists(str(n))]
    if missing:
        raise HandlerError(
            "objects not found: %s (nothing was deleted)" % ", ".join(missing),
            hint="call maya_get_scene_graph to list objects; the delete is "
            "all-or-nothing",
        )
    resolved = [naming.require_object(cmds, str(n)) for n in names]
    cmds.delete(*resolved)
    for name in resolved:
        ledger.forget(name)
    return {"deleted": resolved, "warnings": []}
