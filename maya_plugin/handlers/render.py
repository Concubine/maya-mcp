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
from . import capture, lighting, naming

VALID_RENDERERS = ("arnold", "hw2")
RENDERER_TO_MAYA = {"arnold": "arnold", "hw2": "mayaHardware2"}
DEFAULT_RENDERER = "arnold"

# One angle by default, not capture's three: a rendered frame costs seconds.
# The 4-image ceiling is capture's, and holds for capture's reason - the token
# budget of the images coming back, not the time spent making them.
DEFAULT_ANGLES = ["three_quarter"]
# A sheet returns ONE composited image, so the 4-image ceiling does not apply -
# but a rendered frame costs seconds, and a 64-cell sheet is unreadable at any
# resolution that fits in a message. The kit that motivated this is 41 pieces.
MAX_SHEET_SUBJECTS = 48
DEFAULT_RESOLUTION = 512
MIN_RESOLUTION, MAX_RESOLUTION = 64, 2048
DEFAULT_SAMPLES, MIN_SAMPLES, MAX_SAMPLES = 3, 1, 8

# Maya's default camera vertical film aperture, in inches.
MAYA_VERTICAL_APERTURE_IN = 0.981

# The display transform the delivered frame is encoded with. Un-tone-mapped
# matches URP with post-processing off, which is where the game side is today;
# a tone-mapped view (ACES) would darken a linear-0.5 plane to 165 instead of
# 188 and put a look on an image whose job is to report the asset (#615).
DISPLAY_TRANSFORM = "Un-tone-mapped (sRGB)"


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


class _ArnoldDisplayState:
    """Make Arnold apply a display transform to the frame it writes.

    Arnold hands back RAW LINEAR pixels: a surface of linear albedo 0.5 lit to
    N.L = 1 arrived as 127 where a displayable image wants 188, so every frame
    this tool ever returned was about 2.2 gamma too dark and the art judged
    through it was judged wrong (redmine #615).

    The transform is Arnold's to apply - in float, before the quantise to 8
    bits, so there is no banding, and read from the scene's own colour
    management, so it survives an OCIO change. Use Output Transform rather than
    Use View Transform because the OUTPUT one can be pointed at
    "Un-tone-mapped (sRGB)" for the delivered image while the user's viewport
    keeps whatever view transform they set. Falls back to the view transform
    when no output transform by that name exists in their config.

    None of this reaches cmds.render, which never consults the Arnold driver at
    all - see _render_frame.
    """

    _ATTRS = (
        "defaultArnoldDriver.colorManagement",
        # arnoldRender writes the DRIVER's format, not imageFormat: left alone
        # it writes .exr and the handler reads a file that is not a PNG.
        "defaultArnoldDriver.aiTranslator",
    )

    def __init__(self, cmds):
        self.cmds = cmds
        self.attrs = {}
        self.prefs = {}

    def apply(self) -> bool:
        """Configure the driver; False means this Maya cannot, render as before."""
        try:
            import mtoa.core  # noqa: PLC0415 - only importable with mtoa loaded

            mtoa.core.createOptions()  # defaultArnoldDriver must exist to be set
        except Exception:
            pass  # no mtoa module, or the node already exists: getAttr decides
        try:
            for attr in self._ATTRS:
                self.attrs[attr] = self.cmds.getAttr(attr)
            for pref in ("outputTransformEnabled", "outputTransformName"):
                self.prefs[pref] = self.cmds.colorManagementPrefs(
                    query=True, **{pref: True}
                )
            available = self.cmds.colorManagementPrefs(
                query=True, outputTransformNames=True
            ) or []
            self.cmds.setAttr(
                "defaultArnoldDriver.aiTranslator", "png", type="string"
            )
            if DISPLAY_TRANSFORM in available:
                self.cmds.colorManagementPrefs(
                    edit=True, outputTransformName=DISPLAY_TRANSFORM
                )
                self.cmds.colorManagementPrefs(edit=True, outputTransformEnabled=True)
                self.cmds.setAttr("defaultArnoldDriver.colorManagement", 2)
            else:
                self.cmds.setAttr("defaultArnoldDriver.colorManagement", 1)
            return True
        except Exception:
            self.restore()
            return False

    def restore(self):
        # Order matters: the name has to go back before the enable flag, or a
        # scene that had output transforms off is briefly left pointing
        # somewhere it never pointed.
        if "outputTransformName" in self.prefs:
            self._try(
                lambda: self.cmds.colorManagementPrefs(
                    edit=True, outputTransformName=self.prefs["outputTransformName"]
                )
            )
        if "outputTransformEnabled" in self.prefs:
            self._try(
                lambda: self.cmds.colorManagementPrefs(
                    edit=True,
                    outputTransformEnabled=self.prefs["outputTransformEnabled"],
                )
            )
        for attr, value in self.attrs.items():
            if isinstance(value, str):
                self._try(lambda a=attr, v=value: self.cmds.setAttr(a, v, type="string"))
            else:
                self._try(lambda a=attr, v=value: self.cmds.setAttr(a, v))

    @staticmethod
    def _try(action):
        try:
            action()
        except Exception:
            pass  # a restore that raises hides whatever the render did


def _arnold_render(cmds, camera, resolution) -> str:
    """Render through mtoa's own command; return the file, or "" if it could not.

    arnoldRender reports nothing about where it wrote, but renderSettings
    predicts the name from the same globals the render uses - measured exact on
    a live Maya, so this is a lookup rather than a guess.
    """
    try:
        predicted = cmds.renderSettings(
            firstImageName=True, fullPath=True, camera=camera
        )
    except Exception:
        return ""
    if isinstance(predicted, (list, tuple)):
        predicted = predicted[0] if predicted else ""
    try:
        cmds.arnoldRender(
            camera=camera, width=resolution, height=resolution, batch=True
        )
    except Exception:
        return ""
    return str(predicted) if predicted and os.path.exists(str(predicted)) else ""


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
        # The display transform only reaches the file through mtoa's own render
        # command; cmds.render ignores the driver entirely (#615).
        display = _ArnoldDisplayState(cmds)
        if display.apply():
            try:
                written = _arnold_render(cmds, camera, resolution)
            finally:
                display.restore()
            if written:
                return written
        # arnoldRender could not run or wrote nothing: a dark frame beats no
        # frame, so fall through to the interactive path as before.
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


def _visible(cmds, shape: str) -> bool:
    try:
        return bool(cmds.getAttr(shape + ".visibility"))
    except Exception:
        return True


def _scene_has_light(cmds) -> bool:
    """Is anything actually lighting this scene?

    Visible, not merely present: a hidden light does not illuminate, so a scene
    whose only light is hidden renders as black - the case fallback_light exists
    to catch.

    Arnold's lights are asked for BY TYPE (lighting.light_shapes), because they
    do not reliably answer cmds.ls(lights=True) - and a scene lit entirely by a
    dome that reads as unlit would get a fallback key thrown on top of it,
    doubling the exposure of every judged frame.
    """
    if any(_visible(cmds, s) for s in lighting.light_shapes(cmds)):
        return True
    return bool(cmds.ls(lights=True, visible=True) or [])


# setup_lighting names everything it builds "mcpLight_*". That prefix is the
# boundary for relighting: OUR rig follows the camera, a rig the user authored
# is theirs and is never touched.
_RIG_PREFIX = "mcpLight"


def _rig_lights(cmds) -> Dict[str, float]:
    """Transforms of the tool's own light rig, mapped to their original yaw.

    A DOME is deliberately excluded even though setup_lighting built it: an
    environment is the world, not a lamp, and swinging it per angle would
    rotate every reflection shot to shot - the opposite of what it is for.
    """
    rig = {}
    for light in cmds.ls(lights=True, long=True) or []:
        try:
            if cmds.nodeType(light) in lighting.OMNIDIRECTIONAL_LIGHT_TYPES:
                continue
        except Exception:
            pass
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
    isolate = _name_list(params, "isolate", "|golem")
    # Framing and visibility are separate questions. Welding them meant a
    # close-up of a gem also hid the backdrop it needed to refract, so the
    # material could not be judged at the only size where it is visible
    # (redmine #585). `target` frames; `isolate` hides; either may be used
    # alone. With no target, framing falls back to the isolate set, which is
    # what a caller passing only isolate means.
    target = _name_list(params, "target", "|golem|chest")
    shots = [
        {"label": angle, "angle": angle, "isolate": isolate,
         "frame_on": target or isolate}
        for angle in angles
    ]
    return _run_shots(_cmds(), shots, params)


def render_sheet(params: Dict[str, Any]) -> Dict[str, Any]:
    """One frame per subject, each isolated and framed on itself, in ONE call.

    A kit contact sheet was 41 separate render_scene round-trips. Every one of
    them re-resolved the renderer, snapshotted and restored the render globals,
    built and deleted a camera, and re-hid the scene - all of which is setup,
    not picture. Here it happens once and the loop is just frames.

    The images come back as a list; the MCP server composites them, exactly as
    it already does for capture_turntable.
    """
    subjects = _name_list(params, "subjects", "|kit_wall_a")
    if not subjects:
        raise HandlerError(
            "subjects must be a non-empty list of objects to render",
            hint='one frame per subject, e.g. subjects=["|kit_a", "|kit_b"]; '
            "for several angles of ONE subject use maya_render_scene",
        )
    if len(subjects) > MAX_SHEET_SUBJECTS:
        raise HandlerError(
            "%d subjects requested; the cap is %d per call"
            % (len(subjects), MAX_SHEET_SUBJECTS),
            hint="a sheet past that is unreadable at any sane resolution, and "
            "a rendered frame costs seconds - split it",
        )
    angle = params.get("angle") or "three_quarter"
    if angle not in capture.VALID_ANGLES:
        raise HandlerError(
            "unknown angle %r" % angle,
            hint="valid angles: %s" % ", ".join(capture.VALID_ANGLES),
        )
    # Isolating is the POINT of a sheet: each cell must show one piece, not one
    # piece in front of forty others. Opting out is allowed for a subject that
    # needs its surroundings (a transmissive material refracts them).
    isolate_each = bool(params.get("isolate", True))
    shots = [
        {"label": subject, "angle": angle,
         "isolate": [subject] if isolate_each else None,
         "frame_on": [subject]}
        for subject in subjects
    ]
    return _run_shots(_cmds(), shots, params)


def _run_shots(cmds, shots: List[Dict[str, Any]], params: Dict[str, Any]) -> Dict[str, Any]:
    """Render a list of shots sharing one renderer, camera, rig and globals.

    Everything outside the frame loop is SETUP - loading mtoa, snapshotting the
    user's render globals, building a camera, hiding the scene - and it is what
    makes a per-frame round-trip expensive. Both render_scene (many angles of
    one subject) and render_sheet (one angle of many subjects) are the same
    loop with a different list, so they share it.
    """
    renderer = resolve_renderer(params.get("renderer"))
    resolution = clamp_resolution(params.get("resolution"))
    samples = resolve_samples(params.get("samples"))
    zoom = resolve_zoom(params.get("zoom"))
    fallback_light = bool(params.get("fallback_light", True))
    relight = bool(params.get("relight", True))

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
        # Every name in every shot, checked before a single frame is rendered:
        # a sheet that dies on cell 30 has spent thirty frames' worth of seconds
        # to report a typo.
        for shot in shots:
            for key in ("isolate", "frame_on"):
                missing = [n for n in (shot[key] or []) if not cmds.objExists(n)]
                if missing:
                    raise HandlerError(
                        "%s objects not found: %s" % (key, ", ".join(missing)),
                        hint="call maya_get_scene_graph to list objects",
                    )

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

        images_out = []
        positions = []
        current_isolate: Optional[List[str]] = None
        for index, shot in enumerate(shots):
            angle = shot["angle"]
            # Re-hide only when the visible set actually changes: render_scene
            # holds one isolate set across all its angles, and re-walking every
            # shape in a 45,000-renderer city per frame would cost more than the
            # renders.
            if shot["isolate"] != current_isolate:
                for name in hidden:
                    try:
                        cmds.showHidden(name)
                    except Exception:
                        pass
                hidden = (
                    _hide_non_targets(cmds, shot["isolate"]) if shot["isolate"] else []
                )
                current_isolate = shot["isolate"]

            bbox_min, bbox_max = capture._scene_bbox(cmds, shot["frame_on"])
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
            images_out.append({
                "angle": angle, "label": shot["label"],
                "png_b64": base64.b64encode(png).decode("ascii"),
            })
            pos = cmds.getAttr(temp_camera + ".translate")[0]
            rot = cmds.getAttr(temp_camera + ".rotate")[0]
            positions.append(
                {"angle": angle, "label": shot["label"], "position": list(pos),
                 "rotation": list(rot), "camera": temp_camera}
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
render_sheet.no_undo_chunk = True
