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
    return str(cmds.render(camera, x=resolution, y=resolution))


def _available_renderers(cmds) -> List[str]:
    try:
        return list(cmds.renderer(query=True, namesOfAvailableRenderers=True) or [])
    except Exception:
        return []


def _scene_has_light(cmds) -> bool:
    return bool(cmds.ls(lights=True) or [])


def _hide_non_targets(cmds, isolate: List[str]) -> List[str]:
    """Hide every piece of geometry that is not in `isolate`; return what was hidden.

    Panel isolation is a viewport concept and invisible to a render, so
    isolating here means hiding the rest - and putting it back afterwards.
    """
    hidden = []
    for name in cmds.ls(geometry=True) or []:
        if name in isolate or any(name.startswith(t + "|") for t in isolate):
            continue
        try:
            cmds.hide(name)
            hidden.append(name)
        except Exception:
            pass  # unhideable node (referenced, locked): it stays in frame
    return hidden


def render_scene(params: Dict[str, Any]) -> Dict[str, Any]:
    """Render named angles through the render pipeline; no viewport involved."""
    angles = resolve_angles(params.get("angles"))
    renderer = resolve_renderer(params.get("renderer"))
    resolution = clamp_resolution(params.get("resolution"))
    samples = resolve_samples(params.get("samples"))
    fallback_light = bool(params.get("fallback_light", True))
    isolate = params.get("isolate")
    if isolate is not None and (
        not isinstance(isolate, list) or not all(isinstance(n, str) for n in isolate)
    ):
        raise HandlerError(
            "isolate must be a list of object names",
            hint='e.g. isolate=["|golem"]; call maya_get_scene_graph for names',
        )

    cmds = _cmds()
    maya_renderer = RENDERER_TO_MAYA[renderer]
    available = _available_renderers(cmds)
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
    temp_camera = None
    temp_light = None
    prev_undo = cmds.undoInfo(query=True, state=True)
    cmds.undoInfo(stateWithoutFlush=False)
    try:
        if isolate:
            missing = [n for n in isolate if not cmds.objExists(n)]
            if missing:
                raise HandlerError(
                    "isolate objects not found: %s" % ", ".join(missing),
                    hint="call maya_get_scene_graph to list objects",
                )
            hidden = _hide_non_targets(cmds, isolate)

        if fallback_light and not _scene_has_light(cmds):
            # Arnold renders an unlit scene as pure black, indistinguishable
            # from a broken render - and the blank check downstream would then
            # reject a perfectly good scene.
            light_shape = cmds.directionalLight(intensity=2.0)
            parent = (cmds.listRelatives(light_shape, parent=True) or [light_shape])[0]
            temp_light = cmds.rename(parent, naming.unique_name(cmds, _TEMP_LIGHT))
            cmds.xform(temp_light, rotation=[-35, 25, 0])

        bbox_min, bbox_max = capture._scene_bbox(cmds, isolate)
        images_out = []
        positions = []
        for index, angle in enumerate(angles):
            # "current" has no meaning without a panel to read a camera from;
            # it degrades to the default judging angle rather than failing a
            # render the caller could not have known was panel-dependent.
            position, rotation = capture.camera_placement(
                "three_quarter" if angle == "current" else angle, bbox_min, bbox_max
            )
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
        }
    finally:
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
