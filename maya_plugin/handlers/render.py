"""render_scene: pixels that do not need a viewport.

capture_viewport reads the VP2 viewport, which means it needs a mapped window -
an agent-launched Maya returns fully transparent playblasts - and that it
inherits VP2's approximations: transmission draws as plain transparency, so a
diamond and a plastic block look alike. cmds.render goes through the render
pipeline and needs neither. It renders headless, and under Arnold it refracts
for real (redmine #584).

The framing math is capture.py's, reused rather than restated. The one
difference is that capture lets viewFit refine its placement and viewFit needs a
panel, so here the camera's focal length is set to actually BE the field of view
the math assumes. Everything above the handler is pure and tested headless.
"""

from __future__ import annotations

import base64
import math
import os
import uuid
from typing import Any, Dict, List, Optional, Sequence

from ..dispatcher import HandlerError
from . import capture, naming

VALID_RENDERERS = ("arnold", "hw2")
RENDERER_TO_MAYA = {"arnold": "arnold", "hw2": "mayaHardware2"}
DEFAULT_RENDERER = "arnold"

# One angle by default, not capture's three: a rendered frame costs seconds.
# The 4-image ceiling is capture's, and holds for capture's reason - the token
# budget of the images coming back, not the time spent making them.
DEFAULT_ANGLES = ["three_quarter"]
DEFAULT_RESOLUTION = 512
MIN_RESOLUTION, MAX_RESOLUTION = 64, 2048
DEFAULT_SAMPLES, MIN_SAMPLES, MAX_SAMPLES = 3, 1, 8

# Maya's default camera vertical film aperture, in inches.
MAYA_VERTICAL_APERTURE_IN = 0.981


def focal_length_for_fov(
    fov_deg: float, aperture_inches: float = MAYA_VERTICAL_APERTURE_IN
) -> float:
    """Lens (mm) giving `fov_deg` vertical field of view on that film back."""
    half = math.radians(fov_deg) / 2.0
    return (aperture_inches * 25.4 / 2.0) / math.tan(half)


def resolve_angles(angles: Optional[Sequence[str]]) -> List[str]:
    if angles is None or angles == []:
        return list(DEFAULT_ANGLES)
    angles = list(angles)
    if len(angles) > capture.MAX_ANGLES_PER_CALL:
        raise HandlerError(
            "%d angles requested; the cap is %d images per call"
            % (len(angles), capture.MAX_ANGLES_PER_CALL),
            hint="split the render into multiple calls of up to 4 angles",
        )
    for angle in angles:
        if angle not in capture.VALID_ANGLES:
            raise HandlerError(
                "unknown angle %r" % angle,
                hint="valid angles: %s" % ", ".join(capture.VALID_ANGLES),
            )
    return angles


def resolve_renderer(renderer: Optional[str]) -> str:
    if renderer is None:
        return DEFAULT_RENDERER
    if renderer not in VALID_RENDERERS:
        raise HandlerError(
            "unknown renderer %r" % renderer,
            hint="valid renderers: %s ('arnold' refracts transmissive "
            "materials; 'hw2' is faster and does not)" % ", ".join(VALID_RENDERERS),
        )
    return renderer


def clamp_resolution(resolution: Optional[int]) -> int:
    if not isinstance(resolution, int) or isinstance(resolution, bool):
        return DEFAULT_RESOLUTION
    return max(MIN_RESOLUTION, min(MAX_RESOLUTION, resolution))


def resolve_samples(samples: Optional[int]) -> int:
    if samples is None:
        return DEFAULT_SAMPLES
    if (
        not isinstance(samples, int) or isinstance(samples, bool)
        or not (MIN_SAMPLES <= samples <= MAX_SAMPLES)
    ):
        raise HandlerError(
            "samples must be an integer %d..%d" % (MIN_SAMPLES, MAX_SAMPLES),
            hint="Arnold AA samples; 3 is a judgeable frame, 1 is noisy and "
            "fast. Ignored by the hw2 renderer.",
        )
    return samples


DEFAULT_ZOOM = 1.0
MIN_ZOOM, MAX_ZOOM = 0.2, 8.0


def resolve_zoom(zoom: Optional[float]) -> float:
    if zoom is None:
        return DEFAULT_ZOOM
    if (
        not isinstance(zoom, (int, float)) or isinstance(zoom, bool)
        or not (MIN_ZOOM <= float(zoom) <= MAX_ZOOM)
    ):
        raise HandlerError(
            "zoom must be a number %.1f..%.1f" % (MIN_ZOOM, MAX_ZOOM),
            hint="1.0 fits the framed objects; 2.0 is twice as close",
        )
    return float(zoom)


def zoomed_position(position, bbox_min, bbox_max, zoom: float):
    """Move the camera along its own sight line by `zoom`.

    Pure, so the framing maths stays testable without Maya. Dividing the
    centre-to-camera offset keeps the direction and therefore the angle - only
    the distance changes, which is what a zoom is.
    """
    center = [(lo + hi) / 2.0 for lo, hi in zip(bbox_min, bbox_max)]
    return tuple(
        c + (p - c) / zoom for c, p in zip(center, position)
    )


def frame_prefix(call_id: str, index: int, angle: str) -> str:
    """Image name for one frame.

    cmds.render writes into the project images dir and OVERWRITES a fixed path
    every call - both renders in the #584 probe landed on the same untitled.png.
    Every frame therefore gets its own prefix.
    """
    return "mayaMcpRender_%s_%d_%s" % (call_id, index, angle)


# ------------------------------------------------------------- maya internals

_TEMP_CAM = "mayaMcpRenderCam"
_TEMP_LIGHT = "mayaMcpTempKey"


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


class _RenderGlobalsState:
    """Snapshot/restore for the render settings this call has to change.

    Renderer, image format, file prefix, resolution and Arnold's sample count
    are persistent attributes on the USER'S scene, not arguments to the render.
    A perception tool that leaves them changed has edited the file it was asked
    to look at.
    """

    _ATTRS = (
        "defaultRenderGlobals.currentRenderer",
        "defaultRenderGlobals.imageFormat",
        "defaultRenderGlobals.imageFilePrefix",
        "defaultResolution.width",
        "defaultResolution.height",
        "defaultResolution.deviceAspectRatio",
    )

    def __init__(self, cmds):
        self.cmds = cmds
        self.values = {}
        for attr in self._ATTRS:
            try:
                self.values[attr] = cmds.getAttr(attr)
            except Exception:
                pass  # attribute absent in this Maya: nothing to put back
        try:
            self.aa_samples = cmds.getAttr("defaultArnoldRenderOptions.AASamples")
        except Exception:
            self.aa_samples = None  # mtoa not loaded yet

    def restore(self):
        for attr, value in self.values.items():
            try:
                if isinstance(value, str):
                    self.cmds.setAttr(attr, value, type="string")
                else:
                    self.cmds.setAttr(attr, value)
            except Exception:
                pass
        if self.aa_samples is not None:
            try:
                self.cmds.setAttr(
                    "defaultArnoldRenderOptions.AASamples", self.aa_samples
                )
            except Exception:
                pass


def _render_frame(cmds, camera, prefix, renderer, resolution, samples) -> str:
    """Render one frame and return the file it landed on.

    Its own function so the restore and marshaling tests can run without a
    renderer; everything Maya-version-specific about rendering lives here.
    """
    # cmds.render renders with whatever the scene's currentRenderer is - the
    # renderer is a scene attribute, not a call argument. _RenderGlobalsState
    # snapshotted it; the handler's finally puts it back.
    cmds.setAttr("defaultRenderGlobals.currentRenderer", renderer, type="string")
    cmds.setAttr("defaultRenderGlobals.imageFormat", 32)  # png
    cmds.setAttr("defaultRenderGlobals.imageFilePrefix", prefix, type="string")
    cmds.setAttr("defaultResolution.width", resolution)
    cmds.setAttr("defaultResolution.height", resolution)
    cmds.setAttr("defaultResolution.deviceAspectRatio", 1.0)
    if renderer == "arnold":
        try:
            cmds.setAttr("defaultArnoldRenderOptions.AASamples", samples)
        except Exception:
            pass  # mtoa exposes this only once its globals node exists
    written = cmds.render(camera, x=resolution, y=resolution)
    # Some Maya versions hand back a list of written files rather than one path;
    # str() of a list is a path that cannot exist, which would surface as a
    # baffling "produced no image file" instead of the real result.
    if isinstance(written, (list, tuple)):
        written = written[0] if written else ""
    return str(written)


def _available_renderers(cmds) -> List[str]:
    try:
        return list(cmds.renderer(query=True, namesOfAvailableRenderers=True) or [])
    except Exception:
        return []


def _ensure_renderer(cmds, maya_renderer: str) -> List[str]:
    """Available renderers, loading mtoa first if arnold is wanted and absent.

    A cold Maya lists only mayaSoftware and mayaHardware2 - mtoa loads lazily,
    so the default renderer is missing until something asks for it. Making the
    caller load a plugin to use the default is a tool defect, not their mistake
    (found by the live gate on a freshly launched Maya, redmine #584).
    """
    available = _available_renderers(cmds)
    if maya_renderer != "arnold" or "arnold" in available:
        return available
    try:
        cmds.loadPlugin("mtoa", quiet=True)
    except Exception:
        return available  # not installed; the caller gets the hint below
    available = _available_renderers(cmds)
    if "arnold" in available:
        return available
    try:
        loaded = bool(cmds.pluginInfo("mtoa", query=True, loaded=True))
    except Exception:
        loaded = False
    if loaded:
        # mtoa registers its renderer through a DEFERRED callback, so the
        # renderer list lags a successful load by a moment - long enough that a
        # render on a just-started Maya was rejected for a renderer that was in
        # fact there. Whether the plugin is loaded is the authoritative answer;
        # the list is a view that catches up.
        return available + ["arnold"]
    return available


def _scene_has_light(cmds) -> bool:
    """Is anything actually lighting this scene?

    Visible, not merely present: a hidden light does not illuminate, so a scene
    whose only light is hidden renders as black - the case fallback_light exists
    to catch.
    """
    return bool(cmds.ls(lights=True, visible=True) or [])


# setup_lighting names everything it builds "mcpLight_*". That prefix is the
# boundary for relighting: OUR rig follows the camera, a rig the user authored
# is theirs and is never touched.
_RIG_PREFIX = "mcpLight"


def _rig_lights(cmds) -> Dict[str, float]:
    """Transforms of the tool's own light rig, mapped to their original yaw."""
    rig = {}
    for light in cmds.ls(lights=True, long=True) or []:
        parents = cmds.listRelatives(light, parent=True, fullPath=True) or []
        transform = parents[0] if parents else light
        leaf = transform.rsplit("|", 1)[-1]
        if _RIG_PREFIX not in leaf and _TEMP_LIGHT not in leaf:
            continue
        try:
            rig[transform] = float(
                cmds.xform(transform, query=True, rotation=True, worldSpace=True)[1]
            )
        except Exception:
            pass
    return rig


def _orient_rig(cmds, rig: Dict[str, float], azimuth_deg: float) -> None:
    """Swing the tool's rig to sit behind the camera at `azimuth_deg`.

    setup_lighting builds a WORLD-locked rig while render_scene orbits the
    subject, so a side or back angle renders nearly black - measured on the
    #585 run: key at yaw +30, camera at yaw 90. Yaw only: the rig's elevation
    is the look, and only its bearing needs to follow the camera.
    """
    for transform, original_yaw in rig.items():
        try:
            cmds.xform(transform, edit=True, rotateAxis=(0, 0, 0))
        except Exception:
            pass
        try:
            cmds.setAttr(transform + ".rotateY", original_yaw + azimuth_deg)
        except Exception:
            pass


def _restore_rig(cmds, rig: Dict[str, float]) -> None:
    for transform, original_yaw in rig.items():
        try:
            cmds.setAttr(transform + ".rotateY", original_yaw)
        except Exception:
            pass


def _hide_non_targets(cmds, isolate: List[str]) -> List[str]:
    """Hide every piece of geometry that is not in `isolate`; return what was hidden.

    Panel isolation is a viewport concept and invisible to a render, so
    isolating here means hiding the rest - and putting it back afterwards.

    Everything is compared as LONG names because cmds.ls(geometry=True) returns
    SHAPES under short names: "gemShape" never matches the transform "|gem" the
    caller passed, so the first version of this hid the very object it was asked
    to render and returned a black frame. The live gate caught it; no headless
    test could have, because a fake that returns long names hides the bug
    (redmine #584).
    """
    keep = set()
    for name in isolate:
        for long_name in cmds.ls(name, long=True) or [name]:
            keep.add(long_name)
    hidden = []
    for name in cmds.ls(geometry=True, long=True) or []:
        if name in keep or any(name.startswith(target + "|") for target in keep):
            continue
        try:
            if not cmds.getAttr(name + ".visibility"):
                # Already hidden by the user. Hiding it changes nothing, but
                # RESTORING it would show them an object they deliberately hid.
                continue
            cmds.hide(name)
            hidden.append(name)
        except Exception:
            pass  # unhideable node (referenced, locked): it stays in frame
    return hidden


def _name_list(params: Dict[str, Any], key: str, example: str):
    value = params.get(key)
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(n, str) for n in value):
        raise HandlerError(
            "%s must be a list of object names" % key,
            hint='e.g. %s=["%s"]; call maya_get_scene_graph for names'
            % (key, example),
        )
    return value


def render_scene(params: Dict[str, Any]) -> Dict[str, Any]:
    """Render named angles through the render pipeline; no viewport involved."""
    angles = resolve_angles(params.get("angles"))
    renderer = resolve_renderer(params.get("renderer"))
    resolution = clamp_resolution(params.get("resolution"))
    samples = resolve_samples(params.get("samples"))
    zoom = resolve_zoom(params.get("zoom"))
    fallback_light = bool(params.get("fallback_light", True))
    relight = bool(params.get("relight", True))
    isolate = _name_list(params, "isolate", "|golem")
    # Framing and visibility are separate questions. Welding them meant a
    # close-up of a gem also hid the backdrop it needed to refract, so the
    # material could not be judged at the only size where it is visible
    # (redmine #585). `target` frames; `isolate` hides; either may be used
    # alone. With no target, framing falls back to the isolate set, which is
    # what a caller passing only isolate means.
    target = _name_list(params, "target", "|golem|chest")
    frame_on = target or isolate

    cmds = _cmds()
    maya_renderer = RENDERER_TO_MAYA[renderer]
    available = _ensure_renderer(cmds, maya_renderer)
    if available and maya_renderer not in available:
        raise HandlerError(
            "renderer %r is not available in this Maya (have: %s)"
            % (renderer, ", ".join(available)),
            hint="load the mtoa plugin for arnold, or pass renderer='hw2' - "
            "hw2 renders headless too, it just cannot show refraction",
        )

    call_id = uuid.uuid4().hex[:8]
    state = _RenderGlobalsState(cmds)
    hidden: List[str] = []
    rig: Dict[str, float] = {}
    temp_camera = None
    temp_light = None
    prev_undo = cmds.undoInfo(query=True, state=True)
    cmds.undoInfo(stateWithoutFlush=False)
    try:
        for key, names in (("isolate", isolate), ("target", target)):
            missing = [n for n in (names or []) if not cmds.objExists(n)]
            if missing:
                raise HandlerError(
                    "%s objects not found: %s" % (key, ", ".join(missing)),
                    hint="call maya_get_scene_graph to list objects",
                )
        if isolate:
            hidden = _hide_non_targets(cmds, isolate)

        if fallback_light and not _scene_has_light(cmds):
            # Arnold renders an unlit scene as pure black, indistinguishable
            # from a broken render - and the blank check downstream would then
            # reject a perfectly good scene.
            light_shape = cmds.directionalLight(intensity=2.0)
            parent = (cmds.listRelatives(light_shape, parent=True) or [light_shape])[0]
            temp_light = cmds.rename(parent, naming.unique_name(cmds, _TEMP_LIGHT))
            cmds.xform(temp_light, rotation=[-35, 25, 0])

        # Snapshot the rig AFTER any fallback key exists, so the fallback swings
        # with the camera too - it is our light, and an unlit back view is the
        # exact failure it was added to prevent.
        rig = _rig_lights(cmds) if relight else {}

        bbox_min, bbox_max = capture._scene_bbox(cmds, frame_on)
        images_out = []
        positions = []
        for index, angle in enumerate(angles):
            # "current" has no meaning without a panel to read a camera from;
            # it degrades to the default judging angle rather than failing a
            # render the caller could not have known was panel-dependent.
            resolved_angle = "three_quarter" if angle == "current" else angle
            position, rotation = capture.camera_placement(
                resolved_angle, bbox_min, bbox_max
            )
            if zoom != 1.0:
                position = zoomed_position(position, bbox_min, bbox_max, zoom)
            if relight:
                _orient_rig(cmds, rig, capture._ANGLE_DIRECTIONS[resolved_angle][0])
            if temp_camera is None:
                created = cmds.camera()[0]
                temp_camera = cmds.rename(created, naming.unique_name(cmds, _TEMP_CAM))
                # No panel means no viewFit to refine the framing, so the camera
                # must really have the field of view the placement math assumes.
                cmds.setAttr(
                    temp_camera + ".focalLength",
                    focal_length_for_fov(capture._FOV_DEG),
                )
            cmds.setAttr(temp_camera + ".translate", *position, type="double3")
            cmds.setAttr(temp_camera + ".rotate", *rotation, type="double3")

            path = _render_frame(
                cmds, temp_camera, frame_prefix(call_id, index, angle),
                maya_renderer, resolution, samples,
            )
            if not path or not os.path.exists(path):
                raise HandlerError(
                    "renderer %r produced no image file (reported %r)"
                    % (renderer, path),
                    hint="check Maya's script editor output; for arnold, "
                    "confirm the mtoa plugin is loaded",
                )
            try:
                with open(path, "rb") as fh:
                    png = fh.read()
            finally:
                try:
                    os.unlink(path)  # the render lands in the project images dir
                except OSError:
                    pass
            images_out.append(
                {"angle": angle, "png_b64": base64.b64encode(png).decode("ascii")}
            )
            pos = cmds.getAttr(temp_camera + ".translate")[0]
            rot = cmds.getAttr(temp_camera + ".rotate")[0]
            positions.append(
                {"angle": angle, "position": list(pos), "rotation": list(rot),
                 "camera": temp_camera}
            )

        return {
            "images": images_out,
            "camera_positions": positions,
            "renderer": renderer,
            "samples": samples,
            "fallback_light": temp_light is not None,
            "zoom": zoom,
            "relit_lights": len(rig),
        }
    finally:
        _restore_rig(cmds, rig)
        for name in hidden:
            try:
                cmds.showHidden(name)
            except Exception:
                pass
        for temp in (temp_camera, temp_light):
            if temp is not None:
                try:
                    cmds.delete(temp)
                except Exception:
                    pass
        state.restore()
        try:
            cmds.undoInfo(stateWithoutFlush=prev_undo)
        except Exception:
            pass


# Perception must not pollute the user's undo queue.
render_scene.no_undo_chunk = True
