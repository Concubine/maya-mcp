"""maya_array: mirror, radial and linear copies of an existing object.

The source is never moved and never reparented - it is element 0 of the
finished array and stays exactly where the caller put it. Copies are real
duplicates rather than instances: instances share a shape node, which breaks
per-copy booleans, per-copy material assignment, and the move ledger's
per-object identity.

Placement arithmetic lives in arraymath.py, which has no Maya import and is
tested exhaustively headless. This module only drives cmds.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..dispatcher import HandlerError
from . import arraymath, ledger, naming


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _long(cmds, name: str) -> str:
    return (cmds.ls(name, long=True) or [name])[0]


def _short(name: str) -> str:
    return name.split("|")[-1]


def _duplicate(cmds, source: str, prefix: str, index: int) -> str:
    new_name = naming.unique_name(cmds, "%s_%d" % (prefix, index))
    copy = cmds.duplicate(source, name=new_name, returnRootsOnly=True)[0]
    return _long(cmds, copy)


def _radial(cmds, source: str, prefix: str, params: Dict[str, Any]) -> List[str]:
    count = arraymath.resolve_count(params.get("count"))
    axis = params.get("axis", "y")
    idx = arraymath.axis_index(axis)
    center = arraymath.resolve_vec3(params.get("center"), "center", [0.0, 0.0, 0.0])
    angle = params.get("angle", 360.0)
    if isinstance(angle, bool) or not isinstance(angle, (int, float)):
        raise HandlerError(
            "angle must be a number of degrees, got %r" % (angle,),
            hint="angle=360 for a full ring (the default); angle=180 for a half arc",
        )
    names: List[str] = []
    for i, degrees in enumerate(arraymath.radial_angles(count, float(angle)), start=1):
        copy = _duplicate(cmds, source, prefix, i)
        rotation = [0.0, 0.0, 0.0]
        rotation[idx] = degrees
        cmds.rotate(
            rotation[0], rotation[1], rotation[2], copy,
            pivot=tuple(center), relative=True, worldSpace=True,
        )
        names.append(copy)
    return names


def _linear(cmds, source: str, prefix: str, params: Dict[str, Any]) -> List[str]:
    steps = arraymath.linear_steps(
        params.get("count"),
        params.get("offset"),
        params.get("step_rotate"),
        params.get("step_scale"),
    )
    names: List[str] = []
    for i, step in enumerate(steps, start=1):
        copy = _duplicate(cmds, source, prefix, i)
        cmds.xform(copy, relative=True, worldSpace=True, translation=step["translate"])
        if any(step["rotate"]):
            cmds.xform(copy, relative=True, rotation=step["rotate"])
        if any(s != 1.0 for s in step["scale"]):
            cmds.xform(copy, relative=True, scale=step["scale"])
        names.append(copy)
    return names


def array(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    source = naming.require_object(cmds, str(params.get("name") or ""))
    mode = params.get("mode")
    if mode not in arraymath.MODES:
        raise HandlerError(
            "unknown mode %r" % (mode,),
            hint="valid modes: %s" % ", ".join(arraymath.MODES),
        )
    warnings = [w for w in [ledger.check(cmds, source)] if w]

    requested_prefix = params.get("name_prefix")
    if requested_prefix is not None and (
        not isinstance(requested_prefix, str) or not requested_prefix.strip()
    ):
        raise HandlerError(
            "name_prefix must be a non-empty string",
            hint="omit it to name copies after the source, or pass e.g. name_prefix='cog'",
        )
    prefix = (requested_prefix or _short(source)).strip()

    signed: Optional[float] = None
    if mode == "radial":
        names = _radial(cmds, source, prefix, params)
    elif mode == "linear":
        names = _linear(cmds, source, prefix, params)
    else:
        names, signed, mirror_warnings = _mirror(cmds, source, prefix, params)
        warnings.extend(mirror_warnings)

    group_name = params.get("group_name")
    group: Optional[str] = None
    if group_name is not None:
        if not isinstance(group_name, str) or not group_name.strip():
            raise HandlerError(
                "group_name must be a non-empty string",
                hint="omit it to leave the copies unparented, or pass e.g. group_name='gear'",
            )
        # Only the copies. Sweeping the caller's own object into a group we
        # invented would move it in the hierarchy behind their back.
        grp = cmds.group(*names, name=naming.unique_name(cmds, group_name.strip()))
        group = _long(cmds, grp)
        children = cmds.listRelatives(group, children=True, fullPath=True) or []
        if len(children) == len(names):
            names = children

    for name in names:
        ledger.record(cmds, name)

    return {
        "names": names,
        "mode": mode,
        "group": group,
        "signed_volume": signed,
        "warnings": warnings,
    }


def _mirror(cmds, source: str, prefix: str, params: Dict[str, Any]) -> Tuple[List[str], float, List[str]]:
    raise HandlerError(
        "mirror mode is not implemented yet",
        hint="use mode='radial' or mode='linear'",
    )
