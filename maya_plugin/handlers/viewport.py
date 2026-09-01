"""Persistent viewport/camera discipline (#577 req 4a/4b).

Unlike capture (which restores everything), these handlers make DELIBERATE
persistent changes: the LLM sets up its working view once instead of fighting
drifted panel state every capture. set_viewport doubles as the state query —
call it with no changes to read the current panel configuration.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

from ..dispatcher import HandlerError, require_known_keys
from . import naming, plugwrite
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


# Every top-level key set_viewport reads. Anything else is refused rather
# than ignored (#767): an unread key does not fail, it succeeds and does
# something else.
SET_VIEWPORT_KEYS = (
    "show_grid", "show_light_icons", "show_camera_icons", "show_locators",
    "show_manipulators", "show_texture_placements", "wireframe_on_shaded",
    "display_lights",
)
# `lighting` is what the neighbouring capture tools call the very same
# light-display choice, so a caller who has just written a capture call
# carries the word over. The rest are Maya's own modelEditor flag names,
# sitting in _EDITOR_FLAGS as the values these params map onto: anyone who
# knows the underlying command reaches for the flag before the param.
SET_VIEWPORT_SYNONYMS = {
    "lighting": "display_lights",
    "grid": "show_grid",
    "lights": "show_light_icons",
    "cameras": "show_camera_icons",
    "locators": "show_locators",
    "manipulators": "show_manipulators",
    "textures": "show_texture_placements",
}


def set_viewport(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, SET_VIEWPORT_KEYS, "set_viewport",
                       SET_VIEWPORT_SYNONYMS)
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


# Every top-level key set_camera reads. Anything else is refused rather than
# ignored: an unread key does not fail, it succeeds and does something else.
SET_CAMERA_KEYS = ("camera", "position", "look_at", "focal_length",
                   "set_active")
# `name` is what the RESULT calls the camera, and it is also the create-key
# every other node-making tool in this plugin takes, so it is the first word
# reached for. `translate`/`translation` are the xform flag and the transform
# attribute this handler itself drives underneath — the Maya spelling of the
# thing, not the parameter's.
SET_CAMERA_SYNONYMS = {
    "name": "camera",
    "translate": "position",
    "translation": "position",
}


def set_camera(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, SET_CAMERA_KEYS, "set_camera",
                       SET_CAMERA_SYNONYMS)
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
    focal = params.get("focal_length")
    if position is not None and (
            not isinstance(position, (list, tuple)) or len(position) != 3):
        raise HandlerError(
            "position must be [x, y, z]", hint="world-space coordinates"
        )
    if look_at is not None and (
            not isinstance(look_at, (list, tuple)) or len(look_at) != 3):
        raise HandlerError("look_at must be [x, y, z]", hint="world-space point")
    shape = None
    if focal is not None:
        shape = cmds.listRelatives(cam, shapes=True, fullPath=True)[0]

    # `camera` names a node the caller need not have made, and a shot camera
    # riding a vehicle through a parentConstraint - or aimed at a subject, or
    # with a keyed lens - is an ordinary scene, not a broken one. The reuse
    # path above already converts the OTHER kind of collision into a hinted
    # refusal precisely so the caller never meets a raw Maya exception; this
    # is the same collision, and the name resolved to a camera that belongs
    # to something else (#802).
    #
    # ALL THREE writes are asked about together, before the first one lands.
    # They used to be applied in sequence with the check absent, so an
    # aim-constrained camera (translate free, rotate fed) was MOVED and then
    # failed on the rotation: set_camera makes deliberate persistent changes
    # and has no restore, so the caller saw an error and their camera had
    # silently relocated. Measured (#802): the xform would not even have
    # raised - it writes the children it can and skips the rest - so the
    # camera moved, the aim did nothing, and the call REPORTED SUCCESS.
    wanted = []
    if position is not None:
        wanted.append(cam + ".translate")
    if look_at is not None:
        wanted.append(cam + ".rotate")
    if focal is not None:
        wanted.append(shape + ".focalLength")
    plugwrite.guard(
        cmds, wanted, "set_camera",
        consequence="nothing was written - the camera is where it was")

    if position is not None:
        cmds.xform(cam, translation=[float(v) for v in position], worldSpace=True)
    if look_at is not None:
        current = cmds.xform(cam, query=True, worldSpace=True, translation=True)
        cmds.xform(
            cam, rotation=look_at_rotation(current, [float(v) for v in look_at]),
            worldSpace=True,
        )
    if focal is not None:
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
