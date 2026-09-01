"""capture_viewport: THE critical tool — the LLM's eyes.

Temporary offscreen camera per angle, viewFit, single-frame playblast
(fallback: M3dView.readColorBuffer), returned as base64 PNG. A perception call
must be side-effect-free: every panel/scene setting touched is snapshotted and
restored, temp cameras deleted, selection restored.

The placement math is pure (tested headless); only _capture_one touches maya.

render.py reuses _FOV_DEG, _scene_bbox and camera_placement so the viewport eye
and the render eye frame a subject identically - keep them in step, and expect
render_scene to move if this framing changes.
"""

from __future__ import annotations

import base64
import math
import os
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from ..dispatcher import HandlerError, require_known_keys
from . import naming, pngprobe

VALID_ANGLES = ("front", "side", "back", "top", "three_quarter", "current")
VALID_SHADING = ("smoothShaded", "flatShaded", "wireframe", "textured")
VALID_BUFFERS = ("beauty", "ssao")
# displayLights modes we expose. "scene" is the one that makes a lit model
# judgeable; "default" is Maya's headlight (what every capture did before M2).
VALID_LIGHTING = ("default", "scene", "flat")
_LIGHTING_TO_DISPLAY = {"default": "default", "scene": "all", "flat": "flat"}
MAX_ANGLES_PER_CALL = 4
DEFAULT_ANGLES = ["front", "side", "three_quarter"]
DEFAULT_RESOLUTION = 768
MIN_RESOLUTION, MAX_RESOLUTION = 64, 2048

# azimuth (deg around Y, 0 = +Z), elevation (deg above horizon)
_ANGLE_DIRECTIONS = {
    "front": (0.0, 0.0),
    "side": (90.0, 0.0),
    "back": (180.0, 0.0),
    "top": (0.0, 90.0),
    "three_quarter": (45.0, 27.938),  # Maya's default persp orientation
}
_FOV_DEG = 40.0
_FIT_MARGIN = 1.15
# Maya's filmFit enum: 0 fill, 1 horizontal, 2 vertical, 3 overscan.
_FILM_FIT_HORIZONTAL = 1
# What cmds.camera() builds here, recorded for the tests and for anyone
# reading the arithmetic - never used as an assumption. apply_framing_fov
# reads the film back off the camera it is given, because the previous
# attempt at this (render.py) hardcoded 0.981 in against a camera that
# measures 0.9449 in, and was wrong in a way nothing could see (#772).
MAYA_HORIZONTAL_APERTURE_IN = 1.4173


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


# ------------------------------------------------------------------ pure math


def resolve_angles(angles: Optional[Sequence[str]]) -> List[str]:
    if angles is None or angles == []:
        return list(DEFAULT_ANGLES)
    angles = list(angles)
    if len(angles) > MAX_ANGLES_PER_CALL:
        raise HandlerError(
            "%d angles requested; the cap is %d images per call"
            % (len(angles), MAX_ANGLES_PER_CALL),
            hint="split the capture into multiple calls of up to 4 angles",
        )
    for angle in angles:
        if angle not in VALID_ANGLES:
            raise HandlerError(
                "unknown angle %r" % angle,
                hint="valid angles: %s" % ", ".join(VALID_ANGLES),
            )
    return angles


def clamp_resolution(resolution: Optional[int]) -> int:
    if not isinstance(resolution, int) or isinstance(resolution, bool):
        return DEFAULT_RESOLUTION
    return max(MIN_RESOLUTION, min(MAX_RESOLUTION, resolution))


def _placement(
    azimuth_deg: float, elevation_deg: float,
    bbox_min: Sequence[float], bbox_max: Sequence[float]
) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    """Camera position and euler rotation (deg, Maya xyz order) for an azimuth/
    elevation pair.

    Points the camera at the bbox center from far enough away that the bounding
    sphere fits inside the field of view; viewFit refines the framing afterwards.
    """
    center = [(lo + hi) / 2.0 for lo, hi in zip(bbox_min, bbox_max)]
    radius = math.dist(bbox_min, bbox_max) / 2.0
    radius = max(radius, 0.5)  # degenerate/empty bbox still gets a sane distance
    distance = _FIT_MARGIN * radius / math.sin(math.radians(_FOV_DEG) / 2.0)

    az = math.radians(azimuth_deg)
    el = math.radians(elevation_deg)
    position = (
        center[0] + distance * math.cos(el) * math.sin(az),
        center[1] + distance * math.sin(el),
        center[2] + distance * math.cos(el) * math.cos(az),
    )
    # Maya convention (matches the default persp camera): pitch = -elevation,
    # yaw = azimuth, no roll, default xyz rotate order.
    rotation = (-elevation_deg, azimuth_deg, 0.0)
    return position, rotation


def focal_length_for_fov(fov_deg: float, aperture_inches: float) -> float:
    """Lens (mm) giving `fov_deg` across a film back `aperture_inches` wide.

    The aperture is required rather than defaulted: which one to pass is a
    consequence of filmFit, and a default is exactly how the wrong one gets
    used silently (#772).
    """
    half = math.radians(fov_deg) / 2.0
    return (aperture_inches * 25.4 / 2.0) / math.tan(half)


def apply_framing_fov(cmds, camera: str, fov_deg: float = _FOV_DEG) -> float:
    """Make `camera` actually have the field of view the placement math solved
    for, and return the focal length set.

    _placement puts the camera at `_FIT_MARGIN * radius / sin(fov/2)`, which
    frames the subject as intended only if the lens agrees. Measured before
    this existed: the placement solved for 40 deg and shot through 54.4 deg,
    so subjects came out at about 72% of their intended linear size (#772).

    Two things have to be pinned, not assumed:

    - **filmFit**, because which aperture governs is a function of it. Every
      image this module produces is square (render.py sets width == height
      and deviceAspectRatio 1.0), so under Horizontal fit the horizontal FOV
      governs both axes and one number describes the frame.
    - **the aperture**, read off this camera. Hardcoding it is what made the
      earlier attempt inert: it assumed 0.981 in against a 0.9449 in back,
      and picked the vertical aperture besides.
    """
    shapes = cmds.listRelatives(camera, shapes=True, fullPath=True) or [camera]
    shape = shapes[0]
    cmds.setAttr(shape + ".filmFit", _FILM_FIT_HORIZONTAL)
    aperture = cmds.getAttr(shape + ".horizontalFilmAperture")
    focal = focal_length_for_fov(fov_deg, aperture)
    cmds.setAttr(shape + ".focalLength", focal)
    return focal


def camera_placement(
    angle: str, bbox_min: Sequence[float], bbox_max: Sequence[float]
) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    """Camera position and euler rotation (deg, Maya xyz order) for a named angle."""
    azimuth_deg, elevation_deg = _ANGLE_DIRECTIONS[angle]
    return _placement(azimuth_deg, elevation_deg, bbox_min, bbox_max)


def camera_placement_azimuth(azimuth_deg: float, bbox_min, bbox_max):
    """Same framing math as camera_placement, at an arbitrary azimuth.

    Elevation is fixed at the three_quarter value so a turntable reads as one
    orbit rather than a wobble.
    """
    return _placement(azimuth_deg, 27.938, bbox_min, bbox_max)


# ------------------------------------------------------------------- handler


def _names(params: Dict[str, Any], key: str, example: str) -> Optional[List[str]]:
    """A list of object names, accepting a bare string for the one-object case."""
    value = params.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list) or not all(isinstance(n, str) for n in value):
        raise HandlerError(
            "%s must be a list of object names" % key,
            hint='e.g. %s=["%s"]; call maya_get_scene_graph for names'
            % (key, example),
        )
    return value or None


def ensure_viewport_realized() -> Optional[str]:
    """Show Maya's main window if it has never been shown, and say so.

    MEASURED, and it is the cause of #765: a Maya whose main window has not
    been realized draws NOTHING into an offscreen playblast. Every pixel comes
    back transparent - `offScreen=True` does not save it, and neither does the
    M3dView fallback. One `show()` fixes it permanently for that process: the
    same capture that returned 0 opaque pixels returns 9604 immediately after,
    and MINIMISING the window again afterwards does not break it, because the
    surface stays valid once created.

    The discriminator is `isVisible()`, not `isMinimized()` - the blind
    session measured minimized=False, visible=False, which is why chasing
    minimisation first led nowhere.

    This only ever fires on a window nobody is looking at, so it cannot
    disturb an interactive session: a Maya somebody is using has a visible
    window by definition. It is still REPORTED, because making a window
    appear on someone's screen is a side effect and this tool's contract is
    that it has none.

    Returns the note to warn with, or None when nothing needed doing (which
    includes "this Maya has no Qt to ask" - the blank check downstream is the
    backstop for every cause this cannot see).
    """
    try:
        from maya.OpenMayaUI import MQtUtil  # noqa: PLC0415 - Maya-only
        from shiboken6 import wrapInstance  # noqa: PLC0415
        from PySide6.QtWidgets import QWidget  # noqa: PLC0415

        pointer = MQtUtil.mainWindow()
        if pointer is None:
            return None
        window = wrapInstance(int(pointer), QWidget)
        if window.isVisible():
            return None
        window.show()
    except Exception:  # noqa: BLE001 - see docstring; never fail a capture
        return None
    return ("Maya's main window had never been shown, which makes the "
            "viewport draw nothing into a capture (maya-mcp #765), so this "
            "call showed it. That is a visible change to the screen and the "
            "only one a capture makes.")


def blank_warnings(shot: Dict[str, Any], label: str) -> List[str]:
    """Say it out loud when a frame drew nothing (#765).

    NOT a refusal. A capture of an empty scene is a legitimate request and
    measures identically to a broken one - both are zero opaque pixels - so
    the honest move is to name it and let the caller decide, the way
    `render_sheet` names its blank cells. What is NOT acceptable is the old
    behaviour: handing back a picture of nothing with a success status, which
    is how a whole live gate came to pass on a white square.

    A frame that could not be measured is reported too. "I did not check" and
    "I checked and it is fine" are different answers and must not look alike.
    """
    if shot.get("blank") is True:
        return ["%s came back BLANK - every pixel is transparent, so nothing "
                "was drawn. The scene may be empty or the subject outside the "
                "frame; if neither is true, the viewport itself drew nothing "
                "(maya-mcp #765) and an offline `render_scene` will still "
                "work. Do not judge anything from this frame." % label]
    if shot.get("blank") is None:
        return ["%s could not be measured for blankness (%s), so whether it "
                "shows anything is unknown"
                % (label, shot.get("blank_unmeasurable"))]
    return []


# Every top-level key capture_viewport reads. Anything else is refused rather
# than ignored (#767): an unread key does not fail, it succeeds and does
# something else.
CAPTURE_VIEWPORT_KEYS = (
    "angles", "shading", "wireframe_overlay", "buffer", "lighting", "shadows",
    "isolate", "target", "frame_all", "resolution",
)
# `frame_on` is what this module calls the very same thing one layer down -
# _capture_one takes it under that name and render.py's shot dicts spell it
# that way too - so anyone who has read the code reaches for it before
# `target`.
CAPTURE_VIEWPORT_SYNONYMS = {"frame_on": "target"}


def capture_viewport(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, CAPTURE_VIEWPORT_KEYS, "capture_viewport",
                       CAPTURE_VIEWPORT_SYNONYMS)
    angles = resolve_angles(params.get("angles"))
    shading = params.get("shading", "smoothShaded")
    if shading not in VALID_SHADING:
        raise HandlerError(
            "unknown shading mode %r" % shading,
            hint="valid shading modes: %s" % ", ".join(VALID_SHADING),
        )
    buffer = params.get("buffer", "beauty")
    if buffer not in VALID_BUFFERS:
        raise HandlerError(
            "unknown buffer %r" % buffer,
            hint="valid buffers: %s" % ", ".join(VALID_BUFFERS),
        )
    lighting = params.get("lighting", "default")
    if lighting not in VALID_LIGHTING:
        raise HandlerError(
            "unknown lighting mode %r" % lighting,
            hint="valid lighting modes: %s ('scene' lights the model with the "
            "scene's own lights; 'default' is Maya's headlight)"
            % ", ".join(VALID_LIGHTING),
        )
    shadows = bool(params.get("shadows", False))
    wireframe_overlay = bool(params.get("wireframe_overlay", True))
    frame_all = bool(params.get("frame_all", True))
    resolution = clamp_resolution(params.get("resolution"))
    isolate = _names(params, "isolate", "|golem")
    # `target` frames without hiding anything, so a subject can be framed with
    # its surroundings still in shot. Before #639 the only way to frame one
    # object here was `isolate`, which also hides the rest - the very path #618
    # was about - and frame_all with no isolate framed the sky dome.
    target = _names(params, "target", "|golem|chest")

    images = []
    camera_positions = []
    warnings: List[str] = [w for w in [ensure_viewport_realized()] if w]
    for angle in angles:
        shot = _capture_one(
            angle, shading, wireframe_overlay, buffer, isolate, frame_all, resolution,
            lighting, shadows, frame_on=target,
        )
        images.append({"angle": angle, "png_b64": shot["png_b64"],
                       "blank": shot.get("blank")})
        warnings.extend(blank_warnings(shot, angle))
        camera_positions.append(
            {
                "angle": angle,
                "position": shot["camera_position"],
                "rotation": shot["camera_rotation"],
                "camera": shot["camera"],
            }
        )
    return {"images": images, "camera_positions": camera_positions,
            "warnings": warnings}


TURNTABLE_DEFAULT_FRAMES = 8
TURNTABLE_MAX_FRAMES = 16


# Every top-level key capture_turntable reads. Anything else is refused rather
# than ignored (#767): an unread key does not fail, it succeeds and does
# something else.
CAPTURE_TURNTABLE_KEYS = (
    "n_frames", "target", "shading", "lighting", "resolution", "shadows",
)
# `isolate` is capture_viewport's word for naming the subject, and this tool
# really does isolate the one it is handed, so the neighbouring key comes to
# hand first; `frames` is the bare noun for the thing `n_frames` counts.
CAPTURE_TURNTABLE_SYNONYMS = {"isolate": "target", "frames": "n_frames"}


def capture_turntable(params: Dict[str, Any]) -> Dict[str, Any]:
    """N evenly-spaced azimuths around the subject, for one composite image.

    The frame cap is about grid legibility, not tokens: this returns ONE
    contact sheet regardless of n_frames, so capture_viewport's 4-image
    ceiling does not apply - but a 32-cell sheet is unreadable at any sane
    resolution.
    """
    require_known_keys(params, CAPTURE_TURNTABLE_KEYS, "capture_turntable",
                       CAPTURE_TURNTABLE_SYNONYMS)
    n_frames = params.get("n_frames", TURNTABLE_DEFAULT_FRAMES)
    if (
        not isinstance(n_frames, int) or isinstance(n_frames, bool)
        or not (2 <= n_frames <= TURNTABLE_MAX_FRAMES)
    ):
        raise HandlerError(
            "n_frames must be an integer 2..%d" % TURNTABLE_MAX_FRAMES,
            hint="the cap is grid legibility - the result is one contact sheet",
        )
    target = params.get("target")
    isolate = [str(target)] if target else None
    shading = params.get("shading", "smoothShaded")
    if shading not in VALID_SHADING:
        raise HandlerError(
            "unknown shading mode %r" % shading,
            hint="valid shading modes: %s" % ", ".join(VALID_SHADING),
        )
    lighting = params.get("lighting", "default")
    if lighting not in VALID_LIGHTING:
        raise HandlerError(
            "unknown lighting mode %r" % lighting,
            hint="valid lighting modes: %s" % ", ".join(VALID_LIGHTING),
        )
    resolution = clamp_resolution(params.get("resolution") or 384)
    shadows = bool(params.get("shadows", False))

    images_out = []
    warnings: List[str] = [w for w in [ensure_viewport_realized()] if w]
    for i in range(n_frames):
        azimuth = 360.0 * i / n_frames
        shot = _capture_one(
            ("azimuth", azimuth), shading, False, "beauty", isolate, True,
            resolution, lighting, shadows,
        )
        images_out.append(
            {"index": i, "azimuth": azimuth, "png_b64": shot["png_b64"],
             "blank": shot.get("blank")}
        )
        warnings.extend(blank_warnings(shot, "azimuth %.0f" % azimuth))
    return {"images": images_out, "n_frames": n_frames, "warnings": warnings}


capture_turntable.no_undo_chunk = True


# ------------------------------------------------------------- maya internals


def is_light_shape(cmds, shape: str) -> bool:
    """Is this shape a light? Asked of Maya, not answered from a list.

    `ls(geometry=True)` includes light shapes. Measured on Maya 2027: a scene
    holding one 5-unit cube and one `setup_lighting(preset='environment')` dome
    returns BOTH, and the dome's bbox is +/-1000 - so framing "all visible
    geometry" put the camera 5294 units from a 5-unit subject and returned a
    photograph of the sky (#639). The blank check could not catch it either: a
    dome fills the frame with opaque pixels.

    Maya's own classification answers for every renderer's lights, including
    ones this code has never heard of. Measured: `aiSkyDomeLight`, `aiAreaLight`,
    `directionalLight` and `pointLight` all satisfy 'light'; `mesh`,
    `nurbsSurface`, `camera` and `locator` do not.
    """
    try:
        return bool(cmds.getClassification(cmds.nodeType(shape), satisfies="light"))
    except Exception:
        # An unknown node type is not a reason to drop it from the frame.
        return False


def framable_geometry(cmds) -> List[str]:
    """Every visible shape a camera should frame - which excludes the lights."""
    return [
        shape for shape in (cmds.ls(geometry=True, visible=True) or [])
        if not is_light_shape(cmds, shape)
    ]


def _scene_bbox(cmds, isolate: Optional[List[str]], visible_only: bool = False):
    """World bbox of the isolate set, or of all visible non-light geometry.

    `visible_only` measures what will actually appear rather than what the
    target contains. `exactWorldBoundingBox` includes a transform's children
    regardless of their visibility - measured: a parent whose only distant child
    is hidden still reports the child's corner at 20.5, and `ignoreInvisible=True`
    reports 0.5 - so framing a contact-sheet cell whose sub-assemblies have just
    been hidden would still frame the whole subtree, leaving the piece a speck
    (#640). Off by default: a caller who frames on an object they hid means that
    object's place in the world, not an empty box.
    """
    if isolate:
        missing = [n for n in isolate if not cmds.objExists(n)]
        if missing:
            raise HandlerError(
                "isolate objects not found: %s" % ", ".join(missing),
                hint="call maya_get_scene_graph to list objects",
            )
        # A caller who names the dome means the dome: only the fallback filters.
        targets = isolate
    else:
        targets = framable_geometry(cmds)
    if not targets:
        return [-1.0, -1.0, -1.0], [1.0, 1.0, 1.0]
    if visible_only:
        bbox = cmds.exactWorldBoundingBox(*targets, ignoreInvisible=True)
        # When NOTHING under the targets is visible, Maya answers with an
        # INVERTED sentinel box - measured as [1e20, 1e20, 1e20, -1e20, -1e20,
        # -1e20]. Fed to camera_placement that put a camera 5.8e20 units out, a
        # frame of nothing that reads as a broken renderer rather than a hidden
        # subject. Fall back to where the target actually is.
        if any(lo > hi for lo, hi in zip(bbox[:3], bbox[3:])):
            bbox = cmds.exactWorldBoundingBox(*targets)
    else:
        bbox = cmds.exactWorldBoundingBox(*targets)
    return list(bbox[:3]), list(bbox[3:])


def find_model_panel(cmds) -> str:
    panel = cmds.getPanel(withFocus=True)
    if panel and cmds.getPanel(typeOf=panel) == "modelPanel":
        return panel
    panels = cmds.getPanel(type="modelPanel") or []
    visible = cmds.getPanel(visiblePanels=True) or []
    for candidate in panels:
        if candidate in visible:
            return candidate
    if panels:
        return panels[0]
    raise HandlerError(
        "no model panel available",
        hint=(
            "open a viewport in Maya - capture/viewport/camera tools don't "
            "work in batch/mayapy mode"
        ),
    )


def _isolate_members(cmds, panel: str) -> List[str]:
    """Current members of the panel's view-selected set ([] if never isolated)."""
    try:
        vs_set = cmds.modelEditor(panel, query=True, viewObjects=True)
        if vs_set:
            return cmds.sets(vs_set, query=True) or []
    except Exception:
        pass
    return []


def _apply_isolate(cmds, panel: str, targets: Sequence[str]) -> None:
    """Isolate the panel to exactly `targets` via the isolateSelect API.

    The M0-era mechanism (enableIsolateSelect + force-locked mainListConnection)
    breaks VP2 shading-group resolution for shapes with per-face/groupId
    bindings — they render flat unassigned-green, isolate-only (redmine #575,
    verified live on Maya 2027). isolateSelect state/addDagObject keeps shading
    intact, and membership lives in the panel's ViewSelectedSet rather than the
    live selection, so the pre-playblast select(clear) cannot empty the view —
    no locking needed. Enabling state retains stale members from previous
    isolates (like the legacy -loadSelected no-op), so the set is wiped first.
    """
    cmds.isolateSelect(panel, state=1)
    for member in _isolate_members(cmds, panel):
        try:
            cmds.isolateSelect(panel, removeDagObject=member)
        except Exception:
            pass  # ambiguous short name: worst case a stale member stays visible
    for target in targets:
        cmds.isolateSelect(panel, addDagObject=target)


class _PanelState:
    """Snapshot/restore for every viewport setting the capture touches."""

    def __init__(self, cmds, panel: str):
        self.cmds = cmds
        self.panel = panel
        self.camera = cmds.modelPanel(panel, query=True, camera=True)
        me = lambda **kw: cmds.modelEditor(panel, query=True, **kw)  # noqa: E731
        self.display_appearance = me(displayAppearance=True)
        self.wireframe_on_shaded = me(wireframeOnShaded=True)
        self.display_textures = me(displayTextures=True)
        self.grid = me(grid=True)
        # Icon/manipulator visibility (#577 4a): captures force these off so
        # light icons and place3dTexture widgets never render into a
        # playblast; restore puts back whatever the user had.
        self.lights = me(lights=True)
        self.cameras = me(cameras=True)
        self.locators = me(locators=True)
        self.manipulators = me(manipulators=True)
        self.textures = me(textures=True)
        # Scene-lighting state. These are NOT the icon-visibility flags above:
        # displayLights selects which lights actually light the shaded view,
        # and shadows toggles viewport shadow casting. Neither was snapshotted
        # before M2 because nothing set them - capture rendered in Maya's
        # default headlight regardless of the scene's own rig, which is
        # exactly the gap this task closes (spec 2).
        self.display_lights = me(displayLights=True)
        self.shadows = bool(me(shadows=True))
        # Isolate ("View Selected") state. Membership lives in the panel's
        # ViewSelectedSet objectSet (modelEditor -q -viewObjects); it is only
        # meaningful while viewSelected is on. isolate_dirty is flipped by
        # _capture_one when it isolates, so restore leaves the isolate
        # machinery untouched on captures that never used it.
        self.isolate_state = bool(cmds.modelEditor(panel, query=True, viewSelected=True))
        self.isolate_members = _isolate_members(cmds, panel) if self.isolate_state else []
        self.isolate_dirty = False
        self.ssao = cmds.getAttr("hardwareRenderingGlobals.ssaoEnable")
        self.selection = cmds.ls(selection=True, long=True) or []
        try:
            self.focus_panel = cmds.getPanel(withFocus=True)
        except Exception:
            self.focus_panel = None

    def restore(self):
        cmds, panel = self.cmds, self.panel
        try:
            cmds.modelEditor(
                panel,
                edit=True,
                displayAppearance=self.display_appearance,
                wireframeOnShaded=self.wireframe_on_shaded,
                displayTextures=self.display_textures,
                grid=self.grid,
                lights=self.lights,
                cameras=self.cameras,
                locators=self.locators,
                manipulators=self.manipulators,
                textures=self.textures,
                displayLights=self.display_lights,
                shadows=self.shadows,
            )
        except Exception:
            pass
        if self.isolate_dirty:
            try:
                if self.isolate_state:
                    _apply_isolate(cmds, panel, self.isolate_members)
                else:
                    for member in _isolate_members(cmds, panel):
                        try:
                            cmds.isolateSelect(panel, removeDagObject=member)
                        except Exception:
                            pass
                    cmds.isolateSelect(panel, state=0)
            except Exception:
                pass
        try:
            cmds.setAttr("hardwareRenderingGlobals.ssaoEnable", self.ssao)
        except Exception:
            pass
        try:
            cmds.lookThru(panel, self.camera)
        except Exception:
            pass
        try:
            if self.focus_panel:
                cmds.setFocus(self.focus_panel)
        except Exception:
            pass
        # Selection restore stays last so the user's selection always wins.
        try:
            if self.selection:
                cmds.select(self.selection, replace=True)
            else:
                cmds.select(clear=True)
        except Exception:
            pass


def _capture_one(
    angle: Union[str, Tuple[str, float]],
    shading: str,
    wireframe_overlay: bool,
    buffer: str,
    isolate: Optional[List[str]],
    frame_all: bool,
    resolution: int,
    lighting: str = "default",
    shadows: bool = False,
    frame_on: Optional[List[str]] = None,
) -> Dict[str, Any]:
    cmds = _cmds()
    panel = find_model_panel(cmds)
    state = _PanelState(cmds, panel)
    temp_camera = None
    # Perception must not pollute the undo queue: suppress undo recording for
    # the whole capture (temp camera, setAttrs, isolate churn) so the
    # dispatcher's chunk closes empty and Maya discards it. stateWithoutFlush
    # keeps the user's existing undo history intact.
    prev_undo = cmds.undoInfo(query=True, state=True)
    cmds.undoInfo(stateWithoutFlush=False)
    try:
        # Framing and visibility are separate questions, exactly as in
        # render_scene: `frame_on` frames, `isolate` hides. With no frame_on,
        # framing falls back to the isolate set - what a caller passing only
        # isolate means.
        framing = frame_on or isolate
        if angle == "current":
            capture_cam = state.camera
        else:
            bbox_min, bbox_max = _scene_bbox(cmds, framing)
            if isinstance(angle, (tuple, list)) and angle[0] == "azimuth":
                position, rotation = camera_placement_azimuth(
                    float(angle[1]), bbox_min, bbox_max
                )
            else:
                position, rotation = camera_placement(angle, bbox_min, bbox_max)
            # cmds.camera(name=...) does NOT rename the transform on this
            # Maya (verified live: it always yields "camera1"/"camera2", the
            # same broken idiom set_camera works around) - create unnamed,
            # then rename deterministically via unique_name. Without this the
            # temp camera really is "cameraN", a name a user scene plausibly
            # already contains, which is exactly what made the cosmetic
            # `camera` field below able to collide and (pre-fix) fail the
            # whole capture on an ambiguous short name.
            temp_name = naming.unique_name(cmds, "mayaMcpTempCam")
            created_cam = cmds.camera()[0]
            temp_camera = cmds.rename(created_cam, temp_name)
            # The lens has to match the FOV the placement above solved for.
            # viewFit refines the distance afterwards when frame_all is on,
            # which is what hid this for so long - but frame_all=False shoots
            # the placement straight, and then a mismatched lens IS the
            # framing (#772).
            apply_framing_fov(cmds, temp_camera)
            cmds.setAttr(temp_camera + ".translate", *position, type="double3")
            cmds.setAttr(temp_camera + ".rotate", *rotation, type="double3")
            cmds.setAttr(temp_camera + ".visibility", False)
            capture_cam = temp_camera
        cmds.lookThru(panel, capture_cam)

        if isolate:
            cmds.select(isolate, replace=True)  # viewFit below frames the selection
            _apply_isolate(cmds, panel, isolate)
            state.isolate_dirty = True

        if frame_all and angle != "current":
            # NEVER viewFit allObjects: it refits to every object in the scene,
            # dome included, which is the second half of #639 - the placement
            # math above can exclude the lights and viewFit would put them
            # straight back, at 5498 units and a blank white frame. Frame an
            # explicit selection instead, and only fall back to allObjects when
            # there is genuinely nothing to select.
            fit_set = framing or [
                shape for shape in framable_geometry(cmds)
                if cmds.objExists(shape)
            ]
            if fit_set:
                cmds.select(fit_set, replace=True)
                cmds.viewFit(capture_cam, fitFactor=0.85)  # fits current selection
            else:
                cmds.viewFit(capture_cam, allObjects=True, fitFactor=0.85)

        # Deselect before grabbing pixels: selection highlight (green/white
        # wireframes) otherwise pollutes the capture. Must happen AFTER viewFit,
        # which frames the current selection; _PanelState restores the user's
        # selection afterwards.
        cmds.select(clear=True)

        editor_kwargs = {
            "displayAppearance": "wireframe" if shading == "wireframe" else (
                "flatShaded" if shading == "flatShaded" else "smoothShaded"
            ),
            "wireframeOnShaded": wireframe_overlay and shading != "wireframe",
            "displayTextures": shading == "textured",
            "grid": False,
            "lights": False,
            "cameras": False,
            "locators": False,
            "manipulators": False,
            "textures": False,
            "displayLights": _LIGHTING_TO_DISPLAY[lighting],
            "shadows": shadows,
        }
        cmds.modelEditor(panel, edit=True, **editor_kwargs)
        cmds.setAttr("hardwareRenderingGlobals.ssaoEnable", buffer == "ssao")

        if isolate:
            # VP2 builds a shape's isolate-mode render items lazily, and their
            # first draw can precede the shading-group binding — a shape never
            # drawn under this isolate renders flat unassigned-green for one
            # frame (verified live on Maya 2027: first capture green, second
            # correct). Flush one full draw so the playblast grabs bound
            # materials.
            cmds.refresh(force=True)

        png_bytes, opacity = _grab_pixels(cmds, panel, resolution)

        pos = cmds.getAttr(capture_cam + ".translate")[0]
        rot = cmds.getAttr(capture_cam + ".rotate")[0]
        # Cosmetic field only - a display name must never fail a capture.
        # naming.require_object raises on an ambiguous short name, which
        # would fail the whole call after the pixels were already grabbed;
        # fall back to the bare name rather than resolve-or-raise.
        camera_long = (cmds.ls(capture_cam, long=True) or [capture_cam])[0]
        return {
            "png_b64": base64.b64encode(png_bytes).decode("ascii"),
            "camera_position": list(pos),
            "camera_rotation": list(rot),
            "camera": camera_long,
            "blank": opacity.get("blank"),
            "blank_unmeasurable": opacity.get("unavailable_reason"),
        }
    finally:
        state.restore()
        if temp_camera is not None:
            try:
                cmds.delete(temp_camera)
            except Exception:
                pass
        try:
            cmds.undoInfo(stateWithoutFlush=prev_undo)
        except Exception:
            pass


def _grab_pixels(cmds, panel: str, resolution: int):
    """Playblast a single frame offscreen; fall back to M3dView.readColorBuffer.

    Returns the PNG bytes AND what `pngprobe.opacity` makes of them. The
    measurement happens here because it is the only place the frame exists as
    a file, and it happens at ALL because a playblast can succeed, write a
    valid PNG, and still have drawn nothing (#765): the guard below only
    catches the case where no file appears, which is the failure that never
    actually happened.
    """
    fd, path = tempfile.mkstemp(suffix=".png", prefix="maya_mcp_")
    os.close(fd)
    os.unlink(path)  # playblast wants to create the file itself
    try:
        cmds.setFocus(panel)
        try:
            result = cmds.playblast(
                frame=[cmds.currentTime(query=True)],
                format="image",
                compression="png",
                completeFilename=path,
                offScreen=True,
                viewer=False,
                showOrnaments=False,
                widthHeight=[resolution, resolution],
                percent=100,
                quality=100,
                forceOverwrite=True,
            )
        except Exception:
            result = None
        if not result or not os.path.exists(path):
            _read_color_buffer(path)
        if not os.path.exists(path):
            raise HandlerError(
                "viewport capture produced no image (playblast and M3dView both failed)",
                hint="make sure a viewport is visible and not minimized, then retry",
            )
        opacity = pngprobe.opacity(path)
        with open(path, "rb") as fh:
            return fh.read(), opacity
    finally:
        if os.path.exists(path):
            os.unlink(path)


def _read_color_buffer(path: str) -> None:
    """Fallback capture: read the active 3d view's color buffer (GUI only)."""
    try:
        import maya.OpenMaya as om  # noqa: PLC0415
        import maya.OpenMayaUI as omui  # noqa: PLC0415

        view = omui.M3dView.active3dView()
        view.refresh(False, True)
        image = om.MImage()
        view.readColorBuffer(image, True)
        image.writeToFile(path, "png")
    except Exception:
        pass  # caller reports the combined failure with a hint
