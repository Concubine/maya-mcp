"""Persistent viewport/camera discipline (#577 req 4a/4b).

Unlike capture (which restores everything), these handlers make DELIBERATE
persistent changes: the LLM sets up its working view once instead of fighting
drifted panel state every capture. set_viewport doubles as the state query —
call it with no changes to read the current panel configuration.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

from ..dispatcher import HandlerError
from . import naming
from .capture import find_model_panel

DEFAULT_CAMERA = "mcpCam"
_EDITOR_FLAGS = {
    # param name -> modelEditor flag
    "show_grid": "grid",
    "show_light_icons": "lights",
    "show_camera_icons": "cameras",
    "show_locators": "locators",
    "show_manipulators": "manipulators",
    "show_texture_placements": "textures",
    "wireframe_on_shaded": "wireframeOnShaded",
}
_DISPLAY_LIGHTS = ("default", "all", "active", "flat", "none")


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def look_at_rotation(position: List[float], target: List[float]) -> List[float]:
    """Maya xyz euler (deg) for a camera at `position` looking at `target`.

    Convention matches capture.camera_placement: pitch = -elevation,
    yaw = azimuth (0 = +Z), no roll.
    """
    v = [p - t for p, t in zip(position, target)]  # target -> position offset
    length = math.sqrt(sum(c * c for c in v))
    if length <= 1e-9:
        raise HandlerError(
            "camera position and look_at coincide",
            hint="separate them; the camera needs a viewing direction",
        )
    elevation = math.degrees(math.asin(v[1] / length))
    azimuth = math.degrees(math.atan2(v[0], v[2]))
    return [-elevation, azimuth, 0.0]


def set_viewport(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    panel = find_model_panel(cmds)
    edits: Dict[str, Any] = {}
    for param, flag in _EDITOR_FLAGS.items():
        value = params.get(param)
        if value is not None:
            edits[flag] = bool(value)
    display_lights = params.get("display_lights")
    if display_lights is not None:
        if display_lights not in _DISPLAY_LIGHTS:
            raise HandlerError(
                "unknown display_lights %r" % display_lights,
                hint="valid: %s" % ", ".join(_DISPLAY_LIGHTS),
            )
        edits["displayLights"] = display_lights

    # modelPanel -q -camera returns a short name (verified live, Maya 2027);
    # every scene-node name this plugin reports must be canonical long.
    # Resolved BEFORE the edit call below: an ambiguous short name must
    # refuse the whole request, not raise after the panel was already
    # mutated (there would be no way to report the settings actually took).
    cam = cmds.modelPanel(panel, query=True, camera=True)
    camera_long = naming.require_object(cmds, cam) if cam else cam

    if edits:
        cmds.modelEditor(panel, edit=True, **edits)

    state = {"panel": panel}
    for param, flag in _EDITOR_FLAGS.items():
        state[param] = bool(cmds.modelEditor(panel, query=True, **{flag: True}))
    state["display_lights"] = cmds.modelEditor(panel, query=True, displayLights=True)
    state["camera"] = camera_long
    return state


def set_camera(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    name = str(params.get("camera") or DEFAULT_CAMERA)
    warnings: List[str] = []
    if cmds.objExists(name):
        cam = naming.require_object(cmds, name)
        # `name` collided with an existing node that require_object resolves
        # regardless of type. A stray non-camera (or a shapeless transform)
        # under that name would otherwise crash later with a raw IndexError
        # (listRelatives(...)[0]) or a raw Maya exception (setAttr/lookThru)
        # instead of a hinted HandlerError.
        shapes = cmds.listRelatives(cam, shapes=True, fullPath=True) or []
        if not shapes or cmds.nodeType(shapes[0]) != "camera":
            raise HandlerError(
                "%r exists but is not a camera" % name,
                hint="pass a different `camera` name, or rename/delete the conflicting node",
            )
        warnings.append("reused existing camera %s" % cam)
    else:
        # cmds.camera(name=...) does NOT rename the transform (verified live,
        # Maya 2027: camera(name="mcpCam") always yields "mcpCam1", ignoring
        # the requested name entirely) — create unnamed, then rename, same
        # idiom every other creator in this plugin uses for -name-less
        # commands. unique_name is still consulted for the deterministic-
        # suffix contract even though this branch already knows `name` is
        # free, so a concurrent create between the objExists check and here
        # degrades to a suffix instead of a rename collision.
        resolved_name = naming.unique_name(cmds, name)
        cam = cmds.camera()[0]
        cam = cmds.rename(cam, resolved_name)
        cam = naming.require_object(cmds, cam)

    position = params.get("position")
    look_at = params.get("look_at")
    if position is not None:
        if not isinstance(position, (list, tuple)) or len(position) != 3:
            raise HandlerError(
                "position must be [x, y, z]", hint="world-space coordinates"
            )
        cmds.xform(cam, translation=[float(v) for v in position], worldSpace=True)
    if look_at is not None:
        if not isinstance(look_at, (list, tuple)) or len(look_at) != 3:
            raise HandlerError("look_at must be [x, y, z]", hint="world-space point")
        current = cmds.xform(cam, query=True, worldSpace=True, translation=True)
        cmds.xform(
            cam, rotation=look_at_rotation(current, [float(v) for v in look_at]),
            worldSpace=True,
        )
    focal = params.get("focal_length")
    if focal is not None:
        shape = cmds.listRelatives(cam, shapes=True, fullPath=True)[0]
        cmds.setAttr(shape + ".focalLength", float(focal))
    if params.get("set_active", True):
        panel = find_model_panel(cmds)
        cmds.lookThru(panel, cam)
    return {
        "name": cam,
        "position": cmds.xform(cam, query=True, worldSpace=True, translation=True),
        "rotation": cmds.xform(cam, query=True, worldSpace=True, rotation=True),
        "warnings": warnings,
    }
