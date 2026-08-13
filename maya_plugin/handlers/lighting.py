"""setup_lighting: preset rigs (design doc 5.4).

"A model can't be judged unlit; M2 blocks on this."

This is the only destructive tool in M2: replace_existing=True deletes
user-authored nodes, so it auto-checkpoints - AFTER validation, so a refused
call never burns one (the correction M1 made to sculpt_ops/remesh).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..dispatcher import HandlerError
from . import naming

PRESETS = ("three_point", "single_sun", "hdri")

# (suffix, intensity multiplier, rotate) - a conventional key/fill/rim rig.
_THREE_POINT = (
    ("key", 1.0, [-35.0, 30.0, 0.0]),
    ("fill", 0.35, [-15.0, -55.0, 0.0]),
    ("rim", 0.7, [-10.0, 165.0, 0.0]),
)
_SINGLE_SUN = (("sun", 1.0, [-45.0, 25.0, 0.0]),)


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _auto_checkpoint(reason: str):
    from . import session  # noqa: PLC0415 - avoid an import cycle

    return session.auto_checkpoint(reason)


def _existing_light_transforms(cmds) -> List[str]:
    """Transforms that own a light shape - and nothing else.

    Deliberately derived from ls(type="light"), not from a selection or a
    naming convention: this list is about to be deleted.
    """
    out: List[str] = []
    for shape in cmds.ls(type="light", long=True) or []:
        parents = cmds.listRelatives(shape, parent=True, fullPath=True) or []
        for parent in parents:
            if parent not in out:
                out.append(parent)
    return out


def _build(cmds, prefix: str, specs, intensity: float) -> List[str]:
    created: List[str] = []
    for suffix, factor, rotate in specs:
        name = naming.unique_name(cmds, "%s_%s" % (prefix, suffix))
        shape = cmds.directionalLight(name=name, intensity=intensity * factor)
        parents = cmds.listRelatives(shape, parent=True, fullPath=True) or []
        transform = parents[0] if parents else shape
        cmds.xform(transform, rotation=rotate, worldSpace=True)
        created.append(transform)
    return created


def setup_lighting(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    preset = params.get("preset")
    if preset not in PRESETS:
        raise HandlerError(
            "unknown lighting preset %r" % preset,
            hint="valid presets: %s" % ", ".join(PRESETS),
        )
    intensity = params.get("intensity", 1.0)
    if (
        not isinstance(intensity, (int, float)) or isinstance(intensity, bool)
        or not (0.0 < intensity <= 20.0)
    ):
        raise HandlerError(
            "intensity must be a number in (0, 20]",
            hint="got %r; 1.0 is the neutral default" % (intensity,),
        )
    hdri_path = params.get("hdri_path")
    if preset == "hdri" and not hdri_path:
        raise HandlerError(
            "the hdri preset requires hdri_path",
            hint="maya-mcp bundles no HDRI (they are large and separately "
            "licensed) - pass an absolute path to your own .hdr/.exr",
        )
    replace_existing = params.get("replace_existing", True) is not False

    # Everything above is validation; only now is it safe to spend a
    # checkpoint or delete anything.
    checkpoint_id: Optional[str] = None
    removed: List[str] = []
    if replace_existing:
        existing = _existing_light_transforms(cmds)
        if existing:
            info = _auto_checkpoint("lighting")
            checkpoint_id = (info or {}).get("checkpoint_id")
            for transform in existing:
                cmds.delete(transform)
                removed.append(transform.split("|")[-1])

    if preset == "three_point":
        lights = _build(cmds, "mcpLight", _THREE_POINT, float(intensity))
    elif preset == "single_sun":
        lights = _build(cmds, "mcpLight", _SINGLE_SUN, float(intensity))
    else:
        lights = _build_hdri(cmds, str(hdri_path), float(intensity))

    return {
        "preset": preset,
        "lights": lights,
        "removed": removed,
        "checkpoint_id": checkpoint_id,
        "warnings": [],
    }


def _build_hdri(cmds, hdri_path: str, intensity: float) -> List[str]:
    """Dome light driven by a file texture.

    aiSkyDomeLight is Arnold-only, so this uses Maya's own light + file node
    to stay renderer-agnostic (compatibility rule, design doc 6).
    """
    name = naming.unique_name(cmds, "mcpLight_dome")
    shape = cmds.directionalLight(name=name, intensity=intensity)
    parents = cmds.listRelatives(shape, parent=True, fullPath=True) or []
    transform = parents[0] if parents else shape
    tex = cmds.shadingNode("file", asTexture=True,
                           name=naming.unique_name(cmds, "mcpLight_domeTex"))
    cmds.setAttr(tex + ".fileTextureName", hdri_path, type="string")
    cmds.connectAttr(tex + ".outColor", shape + ".color", force=True)
    return [transform]
