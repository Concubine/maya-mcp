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

from ..dispatcher import HandlerError, refuse_inert, require_known_keys
from . import naming, pngprobe

VALID_ANGLES = ("front", "side", "back", "top", "three_quarter", "current")
VALID_SHADING = ("smoothShaded", "flatShaded", "wireframe", "textured")
VALID_BUFFERS = ("beauty", "ssao")
# displayLights modes we expose. "scene" is the one that makes a lit model
# judgeable; "default" is Maya's headlight (what every capture did before M2).
VALID_LIGHTING = ("default", "scene", "flat")
_LIGHTING_TO_DISPLAY = {"default": "default", "scene": "all", "flat": "flat"}

# The display transform every frame this module grabs is encoded with, and
# the one render_scene delivers (#615) - render.py imports it from here so the
# two eyes cannot drift apart. Measured on Maya 2027 (#837): an offscreen
# playblast takes the PANEL's view transform, which is ACES 1.0 SDR-video on a
# stock install. That curve read a linear-0.5 plane as 165 and a 0.028 plane
# as 17 where Arnold said 188 and 47; an agent judging its materials through
# the viewport darkened them until Arnold showed clay, and then blamed Arnold.
# Un-tone-mapped sRGB reports the asset; a tone-mapped view puts a look on it.
DISPLAY_TRANSFORM = "Un-tone-mapped (sRGB)"


def _apply_display_transform(cmds, panel: str):
    """Make the grab that follows encode like render_scene.

    The view transform is swapped on the GLOBAL colour-management prefs for
    the duration of the grab, and _PanelState puts the user's back with the
    rest of the panel state. Not on the panel: modelEditor has a per-panel
    viewTransformName flag that can be set and read back, and the offscreen
    playblast ignores it - measured, the panel reported Un-tone-mapped and
    drew 165 (ACES); the global swap drew 188. The panel's own cmEnabled is
    forced on because OFF means no transform at all - a raw linear frame,
    127 for a 0.5 albedo.

    Returns (transform_name, note): the name the prefs report AFTER the
    edit, and a note when that is not the one asked for - a Maya that
    refuses the edit draws with whatever it has, and the result must say so
    rather than claim the render's encoding.
    """
    try:
        cmds.modelEditor(panel, edit=True, cmEnabled=True)
        cmds.colorManagementPrefs(edit=True, viewTransformName=DISPLAY_TRANSFORM)
        applied = cmds.colorManagementPrefs(query=True, viewTransformName=True)
    except Exception as exc:  # noqa: BLE001 - reported, never hidden
        return None, (
            "the display transform could not be set on %s (%s: %s): the frames "
            "carry the panel's own view transform, so their tones will not "
            "match maya_render_scene's %s encoding"
            % (panel, type(exc).__name__, str(exc).strip() or "no message",
               DISPLAY_TRANSFORM)
        )
    if applied != DISPLAY_TRANSFORM:
        return applied, (
            "the panel reports view transform %r after asking for %r: the "
            "frames' tones will not match maya_render_scene's encoding"
            % (applied, DISPLAY_TRANSFORM)
        )
    return applied, None
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


def _maya_main_window():
    """Maya's main window as a QWidget, or None when there is no Qt to ask.

    Split out from `ensure_viewport_realized` so the note logic can be tested
    against a window that behaves the way a real one measurably does.
    """
    try:
        from maya.OpenMayaUI import MQtUtil  # noqa: PLC0415 - Maya-only
        from shiboken6 import wrapInstance  # noqa: PLC0415
        from PySide6.QtWidgets import QWidget  # noqa: PLC0415

        pointer = MQtUtil.mainWindow()
        if pointer is None:
            return None
        return wrapInstance(int(pointer), QWidget)
    except Exception:  # noqa: BLE001 - never fail a capture over this
        return None


# What this process has already SAID about the main window. Three facts, each
# worth saying once: we asked for the window, the request did not take, the
# window came up. Per process, because that is the scope of the thing being
# described - one Maya, one window, one screen.
_WINDOW_NOTES = {"asked": False, "said_not_taken": False, "said_up": False}

_ASKED_NOTE = (
    "Maya's main window is not shown, which makes the viewport draw nothing "
    "into a capture (maya-mcp #765), so this call asked Maya to show it. "
    "Whether a window actually appears on your screen cannot be measured "
    "from inside this call - Maya acts on the request on its own next turn, "
    "and reads back as shown either way - so this is a request, not a "
    "report. The next capture says what came of it (maya-mcp #826).")
_NOT_TAKEN_NOTE = (
    "Maya's main window is still not shown, so the earlier request did not "
    "take and nothing has appeared on your screen. Asked again. MEASURED on "
    "agent-launched Mayas: the FIRST show a process is asked for is undone "
    "again before the next command, whenever it comes, and the one after it "
    "sticks - so this is the capture that usually puts the window up "
    "(maya-mcp #826).")
_UP_NOTE = (
    "Maya's main window is up on screen now, after a capture asked for it "
    "(maya-mcp #765). That is a visible change to the screen and the only "
    "one a capture makes.")


def reset_window_notes() -> None:
    """Forget what this process has said about the main window (tests, gates)."""
    _WINDOW_NOTES.update(asked=False, said_not_taken=False, said_up=False)


def ensure_viewport_realized() -> Optional[str]:
    """Show Maya's main window if it is not shown, and report what happened.

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

    #826 is what that report may and may not claim. It used to say "this call
    showed it", which is an assertion about the screen that this call cannot
    check. MEASURED (evals/realized_note_probe_826b.py) on a virgin agent
    Maya: `show()` makes `isVisible()` True synchronously and the window is
    hidden again by the next command, with neither `sendPostedEvents` nor
    `processEvents` revealing it - the two worlds are indistinguishable from
    in here.

    What is undone is the process's FIRST show, not "a show during the first
    seconds": the #826 gate reproduced it on a Maya 67 s old, and the next
    show stuck for good. That is also the shape #825 saw from outside - the
    note on captures 1 and 2 and never again.

    So the note reports across calls instead of asserting inside one: this
    call says it ASKED, and the next call - which can see the outcome - says
    the request did not take, or that the window is up. Each of the three is
    said at most once per process; the show() itself is retried every time,
    because that is #765's protection and it costs nothing.

    Returns the note to warn with, or None when there is nothing new to say
    (which includes "this Maya has no Qt to ask" - the blank check downstream
    is the backstop for every cause this cannot see).
    """
    window = _maya_main_window()
    if window is None:
        return None
    try:
        visible = bool(window.isVisible())
        if not visible:
            window.show()
    except Exception:  # noqa: BLE001 - see docstring; never fail a capture
        return None

    if visible:
        # Only ours to report if we are the reason it might be up.
        if _WINDOW_NOTES["asked"] and not _WINDOW_NOTES["said_up"]:
            _WINDOW_NOTES["said_up"] = True
            return _UP_NOTE
        return None
    if not _WINDOW_NOTES["asked"]:
        _WINDOW_NOTES["asked"] = True
        return _ASKED_NOTE
    if not _WINDOW_NOTES["said_not_taken"]:
        _WINDOW_NOTES["said_not_taken"] = True
        return _NOT_TAKEN_NOTE
    return None


# What VP2 draws for a shape whose shading assignment has not bound yet.
# MEASURED exactly (#830): a bad frame is 76-83% this one flat value, where a
# correctly shaded frame spreads across its lighting ramp and tops out at the
# background.
UNASSIGNED_GREEN = [0, 208, 57]
# A quarter of the sampled subject. The measured failure is three times this;
# the margin is for a frame where the subject only partly fills the shot.
_UNASSIGNED_SHARE = 0.25


def unbound_shader_warnings(shot: Dict[str, Any], label: str) -> List[str]:
    """Say it out loud when a frame is mostly Maya's unassigned-shader green.

    The capture flushes a draw before every grab so this should not happen
    (#830) - but that flush is a MITIGATION for one known VP2 path, not a
    proof, and the failure it prevents is a picture that lies with a plain
    success: real geometry, real opaque pixels, the wrong material. #765's
    rule is that such a frame gets named, so this is the backstop for the day
    the flush is not enough.

    Never a refusal, and it says what else it could be: a material really can
    be that exact green, and the caller is the one who knows which.
    """
    dominant = (shot.get("dominant") or {})
    rgb, share = dominant.get("top_rgb"), dominant.get("top_share")
    if rgb != UNASSIGNED_GREEN or not share or share < _UNASSIGNED_SHARE:
        return []
    return ["%s is %.0f%% Maya's unassigned-shader green (RGB %d,%d,%d), "
            "which is what VP2 draws for a shape it rendered before the "
            "shading assignment bound (maya-mcp #830). This capture flushes a "
            "draw to prevent exactly that, so either the flush did not take "
            "here or the material really is that flat green - shooting the "
            "frame again tells the two apart."
            % (label, 100 * share, rgb[0], rgb[1], rgb[2])]


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
        # An isolate frame that came back blank was asked a follow-up
        # question, so answer it instead of listing the possibilities (#825).
        if shot.get("isolate_view_failed") is True:
            return ["%s came back BLANK, but the SAME frame drawn without "
                    "isolate was not. So the scene is not empty and the "
                    "camera is not pointed at nothing: what drew nothing is "
                    "the isolated view. Either everything named in 'isolate' "
                    "is hidden or has no drawable geometry, or the viewport "
                    "failed to draw an isolated view at all (maya-mcp #825, "
                    "measured on some agent-launched Mayas). Do not judge "
                    "anything from this frame. Check the objects are visible, "
                    "then re-take it without 'isolate', or pass 'target' to "
                    "frame the subject while leaving the rest visible."
                    % label]
        if shot.get("isolate_view_failed") is False:
            return ["%s came back BLANK, and so did the same frame drawn "
                    "without isolate: there was nothing to draw. The scene "
                    "is empty, or every subject is outside the frame. Do not "
                    "judge anything from this frame." % label]
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


# Shading modes VP2 cannot draw a shadow into: a shadow is darkening applied
# to a shaded surface, and neither of these draws one. UNMEASURED - which is
# why the notes below warn rather than refuse (#797 row 38). The frame that
# comes back is still a frame; it just does not carry what was switched on.
_NO_SHADOW_SHADING = ("flatShaded", "wireframe")


def display_warnings(shading: str, shadows: bool,
                     buffer: str = "beauty") -> List[str]:
    """Flags VP2 accepts and then does nothing with.

    Pure - it asks Maya nothing, so it runs before any capture and reports
    once per CALL rather than once per frame. Said out loud for the same
    reason render_scene reports `fallback_light`: a caller who switched
    something on and reads a frame without it concludes the subject has no
    self-shadowing, not that the mode they chose cannot show one.
    """
    out: List[str] = []
    if shadows and shading in _NO_SHADOW_SHADING:
        out.append(
            "shadows=True under shading=%r: a shadow is darkening applied to "
            "a shaded surface and this mode draws none, so the frame comes "
            "back without them. Use shading='smoothShaded' to judge shadows."
            % shading)
    if buffer == "ssao" and shading == "wireframe":
        out.append(
            "buffer='ssao' under shading='wireframe': ambient occlusion "
            "darkens the crevices of a drawn surface and a wireframe draws "
            "none, so the frame is the same wireframe either way.")
    return out


def frame_warnings(shot: Dict[str, Any], label: str,
                   resolution: int) -> List[str]:
    """What this frame did NOT do, taken off the shot dict (#797).

    Three notes, each about a request the frame silently dropped:

      * `target` on a "current" angle framed nothing (row 20). The panel's
        own camera is kept exactly where the user left it, so the subject
        the caller named had no effect on what was photographed. Only ever
        reached on a MIXED angle list - a current-only capture refuses.
      * the playblast failed and the M3dView fallback drew at the PANEL's
        size rather than the resolution asked for (row 36). Nothing said so
        before, and a caller measuring pixels off the image had no way to
        know its scale had changed under them.
      * lighting='scene' in a scene holding no light (row 38): displayLights
        'all' with nothing to light with draws the subject black on black,
        and the blank check cannot catch it because the background still
        renders.
      * the `target` is behind another mesh from this angle (#824): the
        camera is placed from the target's bbox alone, so the frame is full
        of the occluder and the blank check cannot see it either.
    """
    out: List[str] = []
    if shot.get("target_unframed"):
        out.append(
            "%s: 'target' did not frame this angle - 'current' looks through "
            "the panel's own camera and moves nothing. The other angles in "
            "this call were framed on it." % label)
    drawn = shot.get("drawn_size")
    if drawn:
        out.append(
            "%s was drawn at %dx%d, not %dx%d: the playblast failed and the "
            "M3dView fallback reads the viewport's own framebuffer, whatever "
            "size the panel happens to be. Measure pixels off it accordingly."
            % (label, drawn[0], drawn[1], resolution, resolution))
    if shot.get("unlit"):
        out.append(
            "lighting='scene' but this scene has no light: the subject is lit "
            "by nothing and draws dark against the background. Call "
            "maya_setup_lighting first, or use lighting='default' for Maya's "
            "headlight.")
    note = occlusion_warning(label, shot.get("occlusion"))
    if note:
        out.append(note)
    return out


# ------------------------------------------------------- occlusion (#824)

# A ray that reaches its sample point within this fraction of the distance
# is NOT blocked. MEASURED: a cube standing on a plane has its bottom
# corners ON the plane, and the rays to them hit it at param == distance
# (4 of 9 from three_quarter, 2 of 9 from the front); with this tolerance,
# none.
OCCLUSION_TOLERANCE = 1e-4


def bbox_samples(bbox_min: Sequence[float], bbox_max: Sequence[float]
                 ) -> List[Tuple[float, float, float]]:
    """The nine points a target's visibility is asked at: the centre of
    its world bbox and the eight corners, centre first."""
    centre = tuple((float(lo) + float(hi)) / 2.0
                   for lo, hi in zip(bbox_min, bbox_max))
    corners = [
        (float(x), float(y), float(z))
        for x in (bbox_min[0], bbox_max[0])
        for y in (bbox_min[1], bbox_max[1])
        for z in (bbox_min[2], bbox_max[2])
    ]
    return [centre] + corners


def occlusion_warning(label: str, occlusion: Optional[Dict[str, Any]]
                      ) -> Optional[str]:
    """Say when the target the caller asked to see is behind something.

    MEASURED (#823 K2, #824): `back` with `target=|red` on a red(+Z)/blue
    (-Z) pair places the camera from the target's bbox alone, so the blue
    cube sits between them and the frame is 65536/65536 blue px, zero red,
    `blank: false`, no warning. The caller asked for the red cube and got a
    success holding none of it. The blank check cannot see this - the frame
    is full of pixels - so it is asked with rays instead (target_occlusion).

    A WARNING, never a refusal: a caller framing a part with its
    surroundings in shot may want exactly that, and a partial cover is a
    measurement of nine sample points, not a verdict on the picture. The
    unmeasured case is reported too (the blank_warnings discipline).
    """
    if not occlusion:
        return None
    targets = occlusion.get("targets") or []
    names = ", ".join(targets)
    if occlusion.get("unmeasurable") is not None:
        return ("%s: whether target %s is hidden behind another object could "
                "not be measured (%s); the frame may show something else"
                % (label, names, occlusion["unmeasurable"]))
    blocked = int(occlusion.get("blocked") or 0)
    if blocked <= 0:
        return None
    samples = int(occlusion.get("samples") or 0)
    by = ", ".join(occlusion.get("by") or []) or "another mesh"
    isolate = "isolate=[%s]" % ", ".join("'%s'" % t for t in targets)
    if blocked >= samples:
        return ("%s: target %s is hidden behind %s from this angle - all %d "
                "sample points on its bounding box (centre and corners) are "
                "blocked, so the frame shows the occluder, not the target. "
                "Pass %s to photograph it alone, or choose another angle."
                % (label, names, by, samples, isolate))
    return ("%s: target %s is partly hidden behind %s from this angle - %d "
            "of %d sample points on its bounding box are blocked. Pass %s "
            "if the occluder is not wanted in shot."
            % (label, names, by, blocked, samples, isolate))


def occluder_shapes(cmds, framing: Sequence[str],
                    isolate: Optional[Sequence[str]]) -> List[str]:
    """Every visible mesh that could stand between the camera and the
    target: what `ls(geometry=True, visible=True)` draws, minus the
    target's own shapes, minus intermediate shapes, and under `isolate`
    only what is actually shown. Each exclusion is MEASURED (#824):

      * the target's own shapes: rays to a grouped target's far corners
        pass through its near member, and counted as 4 blocks of 9 from
        the back until excluded. `ls(<nodes>, dag=True, shapes=True)` is
        the form that finds them under a group - `listRelatives(
        allDescendents=True, shapes=True)` answered NOTHING for one.
      * a skinned mesh's ShapeOrig is listed as visible geometry next to
        the drawn shape; it draws nothing and would answer rays.
      * only meshes: closestIntersection is an MFnMesh call.
      * isolate=[red] + target red from the back drew 14884 red px: the
        hidden blue cube cannot occlude what it is not drawn in front of.
    """
    own = set(cmds.ls(list(framing), dag=True, shapes=True, long=True,
                      noIntermediate=True) or [])
    shown = None
    if isolate:
        shown = set(cmds.ls(list(isolate), dag=True, shapes=True, long=True,
                            noIntermediate=True) or [])
    out = []
    for shape in cmds.ls(geometry=True, visible=True, long=True) or []:
        if shape in own or cmds.nodeType(shape) != "mesh":
            continue
        if cmds.getAttr(shape + ".intermediateObject"):
            continue
        if shown is not None and shape not in shown:
            continue
        out.append(shape)
    return out


def blocked_samples(camera_position: Sequence[float],
                    samples: Sequence[Sequence[float]],
                    shapes: Sequence[str],
                    tolerance: float = OCCLUSION_TOLERANCE
                    ) -> List[Optional[str]]:
    """For each sample point, the shape a ray from the camera hits FIRST
    on its way there, or None when it arrives unblocked.

    OpenMaya, module-level ON PURPOSE (the physics._points_and_triangles
    seam): FakeCmds cannot fake MFnMesh, so the headless tests monkeypatch
    this and the mayapy tests measure it. MEASURED on Maya 2027: nine rays
    against a 40k-face mesh take 11 ms without an accelerator, so none is
    built. closestIntersection answers None on a miss and a (point, param,
    face, triangle, bary1, bary2) tuple on a hit.
    """
    import maya.api.OpenMaya as om  # noqa: PLC0415 - only importable inside Maya

    meshes = []
    for shape in shapes:
        sel = om.MSelectionList()
        sel.add(shape)
        meshes.append((shape, om.MFnMesh(sel.getDagPath(0))))
    source = om.MPoint(*[float(v) for v in camera_position])
    out: List[Optional[str]] = []
    for sample in samples:
        offset = om.MPoint(*[float(v) for v in sample]) - source
        distance = offset.length()
        if distance <= 0.0:
            out.append(None)
            continue
        direction = om.MFloatVector(offset.normal())
        nearest = distance * (1.0 - tolerance)
        hit_by = None
        for shape, mesh in meshes:
            hit = mesh.closestIntersection(
                om.MFloatPoint(source), direction, om.MSpace.kWorld,
                distance, False)
            if hit is not None and hit[2] != -1 and hit[1] < nearest:
                nearest = hit[1]
                hit_by = shape
        out.append(hit_by)
    return out


def _transform_short_name(shape: str) -> str:
    parts = shape.split("|")
    return parts[-2] if len(parts) >= 2 and parts[-2] else parts[-1]


def target_occlusion(cmds, camera: str, framing: Sequence[str],
                     isolate: Optional[Sequence[str]]) -> Dict[str, Any]:
    """Is the framed target visible from where the camera ended up?

    Asked AFTER viewFit, from the camera's final position, at the nine
    bbox_samples of the target against occluder_shapes. Never raises: a
    capture must not fail because this could not be asked, and the
    `unmeasurable` form says so rather than reading as "fine".
    """
    targets = list(framing)
    try:
        position = tuple(cmds.getAttr(camera + ".translate")[0])
        bbox_min, bbox_max = _scene_bbox(cmds, targets, param="target")
        samples = bbox_samples(bbox_min, bbox_max)
        shapes = occluder_shapes(cmds, targets, isolate)
        hits = (blocked_samples(position, samples, shapes) if shapes
                else [None] * len(samples))
    except Exception as exc:  # noqa: BLE001 - see docstring
        return {"targets": targets,
                "unmeasurable": "%s: %s" % (type(exc).__name__, exc)}
    by: List[str] = []
    for hit in hits:
        if hit is None:
            continue
        name = _transform_short_name(hit)
        if name not in by:
            by.append(name)
    return {"targets": targets,
            "blocked": sum(1 for hit in hits if hit is not None),
            "samples": len(samples), "by": by}


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
    # #797 row 20: "current" keeps the panel's own camera exactly where the
    # user left it - _capture_one places no camera and never calls
    # _scene_bbox on that branch, so `target` is read, validated and
    # dropped. It is a REFUSAL rather than a note because _scene_bbox is
    # also the only existence check target ever gets: a typo'd target on a
    # current-only capture came back a success, and the caller believes
    # they photographed the object they named. A MIXED list still consumes
    # target for its other angles, so that one is a per-frame note instead.
    if target and all(a == "current" for a in angles):
        refuse_inert(
            "capture_viewport", "target", "when every angle is 'current'",
            "the current angle looks through the panel's own camera and "
            "frames nothing, so target is never read - not even to check "
            "that the object exists",
            hint="ask for an angle that places a camera (front, side, back, "
                 "top, three_quarter), or drop target to shoot the panel as "
                 "the user left it",
        )

    images = []
    camera_positions = []
    warnings: List[str] = [w for w in [ensure_viewport_realized()] if w]
    warnings.extend(display_warnings(shading, shadows, buffer))
    for angle in angles:
        shot = _capture_one(
            angle, shading, wireframe_overlay, buffer, isolate, frame_all, resolution,
            lighting, shadows, frame_on=target,
        )
        images.append({"angle": angle, "png_b64": shot["png_b64"],
                       "blank": shot.get("blank"),
                       "display_transform": shot.get("display_transform")})
        warnings.extend(blank_warnings(shot, angle))
        warnings.extend(unbound_shader_warnings(shot, angle))
        # Deduped: the unlit note carries no label and is identical on every
        # frame of the call, while the framing and size notes name theirs.
        for note in frame_warnings(shot, angle, resolution):
            if note not in warnings:
                warnings.append(note)
        for note in display_transform_warnings(shot):
            if note not in warnings:
                warnings.append(note)
        camera_positions.append(
            {
                "angle": angle,
                "position": shot["camera_position"],
                "rotation": shot["camera_rotation"],
                "camera": shot["camera"],
            }
        )
    return {"images": images, "camera_positions": camera_positions,
            # One panel per call, so one encoding per call (#837): the name
            # every frame above carries, or None when it could not be set.
            "display_transform": (images[0].get("display_transform")
                                  if images else None),
            "warnings": warnings}


def display_transform_warnings(shot: Dict[str, Any]) -> List[str]:
    """The #837 note, when the frame is not encoded like the render."""
    note = shot.get("display_transform_note")
    return [note] if note else []


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
    # #797 row 26: `[str(target)] if target else None` reads an EMPTY string
    # as "no target at all", so a call that named nothing quietly orbited
    # the whole scene - sky dome included - and framed the subject as a
    # speck. An empty name is a caller mistake, not a request for
    # everything, and it is the one value that cannot mean what it says.
    if isinstance(target, str) and not target.strip():
        refuse_inert(
            "capture_turntable", "target", "when it is empty",
            "an empty name is falsey, so it was read as 'no target' and the "
            "orbit framed the entire scene instead of an object",
            hint="pass the object to orbit, or omit target entirely to frame "
                 "the whole scene on purpose",
        )
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
    warnings.extend(display_warnings(shading, shadows))
    for i in range(n_frames):
        azimuth = 360.0 * i / n_frames
        shot = _capture_one(
            ("azimuth", azimuth), shading, False, "beauty", isolate, True,
            resolution, lighting, shadows,
        )
        images_out.append(
            {"index": i, "azimuth": azimuth, "png_b64": shot["png_b64"],
             "blank": shot.get("blank"),
             "display_transform": shot.get("display_transform")}
        )
        label = "azimuth %.0f" % azimuth
        warnings.extend(blank_warnings(shot, label))
        warnings.extend(unbound_shader_warnings(shot, label))
        for note in frame_warnings(shot, label, resolution):
            if note not in warnings:
                warnings.append(note)
        for note in display_transform_warnings(shot):
            if note not in warnings:
                warnings.append(note)
    return {"images": images_out, "n_frames": n_frames,
            "display_transform": (images_out[0].get("display_transform")
                                  if images_out else None),
            "warnings": warnings}


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


def _scene_is_unlit(cmds) -> Optional[bool]:
    """Will lighting='scene' light this frame with nothing? (#797 row 38)

    Asked through lighting.light_shapes, which is the one place that knows
    what a light is - Arnold's lights do not answer ls(lights=True), and a
    scene lit entirely by a dome would otherwise read as unlit.

    Never raises and never returns a guess: a capture must not fail because
    the question could not be asked, and `None` says "not measured" rather
    than "fine" (the blank_warnings discipline).
    """
    from . import lighting  # noqa: PLC0415 - lighting imports nothing here

    try:
        return not lighting.light_shapes(cmds)
    except Exception:  # noqa: BLE001 - see docstring; never fail a capture
        return None


def framable_geometry(cmds) -> List[str]:
    """Every visible shape a camera should frame - which excludes the lights."""
    return [
        shape for shape in (cmds.ls(geometry=True, visible=True) or [])
        if not is_light_shape(cmds, shape)
    ]


def _scene_bbox(cmds, isolate: Optional[List[str]], visible_only: bool = False,
                param: str = "isolate"):
    """World bbox of the isolate set, or of all visible non-light geometry.

    `param` names the caller's own key in the not-found refusal. This is the
    only existence check either `isolate` or `target` gets, and it used to
    say "isolate objects not found" for a mistyped TARGET - naming a param
    the caller did not pass, which sends them looking in the wrong place
    (#797 row 20's review).

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
                "%s objects not found: %s" % (param, ", ".join(missing)),
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
        # Colour management (#837): the capture swaps the GLOBAL view
        # transform for the grab and forces this panel's cmEnabled on, so
        # both must come back. None when Maya cannot say (an older build
        # without the flags), and then restore leaves that one alone.
        try:
            self.cm_enabled = me(cmEnabled=True)
        except Exception:
            self.cm_enabled = None
        try:
            self.view_transform = cmds.colorManagementPrefs(
                query=True, viewTransformName=True)
        except Exception:
            self.view_transform = None
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
        if self.view_transform is not None:
            try:
                cmds.colorManagementPrefs(edit=True, viewTransformName=self.view_transform)
            except Exception:
                pass
        if self.cm_enabled is not None:
            try:
                cmds.modelEditor(panel, edit=True, cmEnabled=bool(self.cm_enabled))
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
    # Asked HERE, where cmds exists: the handlers above must stay Maya-free
    # until the capture itself, so their param refusals fire headless (#797
    # row 20's contract). Reported once by the caller, not once per frame.
    unlit = _scene_is_unlit(cmds) if lighting == "scene" else False
    target_unframed = False
    panel = find_model_panel(cmds)
    state = _PanelState(cmds, panel)
    temp_camera = None
    # Perception must not pollute the undo queue: suppress undo recording for
    # the whole capture (temp camera, setAttrs, isolate churn) so the
    # dispatcher's chunk closes empty and Maya discards it. stateWithoutFlush
    # keeps the user's existing undo history intact.
    prev_undo = cmds.undoInfo(query=True, state=True)
    cmds.undoInfo(stateWithoutFlush=False)
    # Maya's invisibility evaluator is OFF for the whole frame (redmine #847).
    # MEASURED on Maya 2027 (evals/newscene_spin_probe_847/, three identical
    # native stack samples): a capture changes what is visible - isolate,
    # displayLights, the temp camera and its deletion - which the Evaluation
    # Manager's invisibility evaluator starts monitoring with a delayed
    # notification. A scene replace (file -new / -open) within ~100 ms of the
    # capture, before an idle turn delivered it, tears the evaluator down
    # (AnimUISlice!TinvisibilityEvaluator::endMonitoring) into an access
    # violation, after which Maya's crash handler spins one core forever and
    # only a process kill recovers. Off before the capture and back on after
    # it: 6/6 timed scene replaces returned where the control spun 2/3.
    # Switching it off AFTER the capture trips the same crash (setActive ->
    # endMonitoring), so the bracket is here, and the restore is the LAST
    # thing the finally does. Only ever restored to what it was: a user who
    # keeps it off keeps it off.
    invisibility_was = _invisibility_evaluator_off(cmds)
    try:
        # Framing and visibility are separate questions, exactly as in
        # render_scene: `frame_on` frames, `isolate` hides. With no frame_on,
        # framing falls back to the isolate set - what a caller passing only
        # isolate means.
        framing = frame_on or isolate
        # Which key the caller actually passed, so a not-found refusal names
        # the word they typed rather than the one this function calls it.
        framing_param = "target" if frame_on else "isolate"
        if angle == "current":
            # Nothing is framed here - but the name still has to be REAL.
            # _scene_bbox is the only existence check `target` ever gets, so
            # skipping it let a typo'd target succeed against whatever the
            # panel happened to hold (#797 row 20). The box is discarded;
            # the refusal inside it is the point.
            if framing:
                _scene_bbox(cmds, framing, param=framing_param)
            target_unframed = bool(frame_on)
            capture_cam = state.camera
        else:
            bbox_min, bbox_max = _scene_bbox(cmds, framing, param=framing_param)
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

        # Is the target actually in view from where the camera ended up?
        # Asked here, after viewFit has moved it, and only for a named
        # target on a placing angle: isolate alone leaves nothing else to
        # hide behind, and "current" placed no camera (#824).
        occlusion = None
        if frame_on and angle != "current":
            occlusion = target_occlusion(cmds, capture_cam, frame_on, isolate)

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
        # Encode like the render eye (#837), after the panel is configured
        # and before the flush below, so the draw the playblast grabs is the
        # one made under this transform.
        display_transform, display_transform_note = _apply_display_transform(cmds, panel)

        # VP2 builds a shape's render items lazily, and their first draw can
        # precede the shading-group binding: a shape VP2 has not drawn since
        # the assignment renders flat unassigned-green (measured: exactly RGB
        # 0,208,57) for ONE frame, and the frames after it in the same call
        # are correct. Flush one full draw so the playblast grabs bound
        # materials.
        #
        # This used to be scoped to `if isolate:`, where it was first found.
        # #830 measured the same failure with no isolate at all - a 28-mesh
        # scene, freshly assigned, reproduced it 3 times out of 3 - and the
        # scoping is why an agent building a prop got a capture that lied
        # about its materials with a plain success. It has to sit HERE,
        # after the panel is configured and immediately before the grab: the
        # same refresh issued from an earlier command does not help (measured,
        # 3/3 still green), because the draw that matters is the one this
        # panel state provokes. It costs 2-4 ms, measured on a 160k-face
        # scene, which is the whole reason there is nothing to trade off.
        cmds.refresh(force=True)

        png_bytes, opacity = _grab_pixels(cmds, panel, resolution)
        isolate_view_failed = None
        if isolate and opacity.get("blank") is True:
            isolate_view_failed = _isolate_blank_control(cmds, panel, resolution)

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
            # The colour census, for unbound_shader_warnings (#830). Measured
            # in _grab_pixels and forgotten here in the first cut, which is
            # #757 one layer down: the guard ran on a key nothing set, so a
            # frame that WAS the placeholder green passed in silence and only
            # the live gate noticed.
            "dominant": opacity.get("dominant"),
            # What this frame did NOT do, for frame_warnings above.
            "drawn_size": opacity.get("drawn_size"),
            "unlit": unlit,
            "target_unframed": target_unframed,
            "occlusion": occlusion,
            "isolate_view_failed": isolate_view_failed,
            # The encoding this frame actually carries (#837), and why it is
            # not the render's when it is not.
            "display_transform": display_transform,
            "display_transform_note": display_transform_note,
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
        # Last, after every visibility change above (#847).
        _invisibility_evaluator_restore(cmds, invisibility_was)


INVISIBILITY_EVALUATOR = "invisibility"


def _invisibility_evaluator_off(cmds) -> Optional[bool]:
    """Switch the invisibility evaluator off for a capture; returns what it
    was, or None when it was already off or cannot be asked (an older Maya,
    a headless one), in which case there is nothing to restore."""
    try:
        was = bool(cmds.evaluator(query=True, name=INVISIBILITY_EVALUATOR, enable=True))
        if was:
            cmds.evaluator(name=INVISIBILITY_EVALUATOR, enable=False)
        return was or None
    except Exception:  # noqa: BLE001 - no evaluator to bracket, nothing to undo
        return None


def _invisibility_evaluator_restore(cmds, was: Optional[bool]) -> None:
    if not was:
        return
    try:
        cmds.evaluator(name=INVISIBILITY_EVALUATOR, enable=True)
    except Exception:  # noqa: BLE001 - a restore that fails must not fail the frame
        pass


def _isolate_blank_control(cmds, panel: str, resolution: int) -> Optional[bool]:
    """A blank isolate frame: was it the scene, or the isolate view? (#825)

    Re-shoots the SAME camera with view-selected switched off and nothing
    else touched. If that draws, the scene is not empty and the subject is
    not out of frame, so the isolated view is what failed - which is the
    #825 condition, measured on agent-launched Mayas where every isolate
    capture in a process comes back transparent while non-isolate captures
    in that same process draw fine.

    Costs one extra playblast and only ever runs on a frame that already
    came back blank, which is rare and already worth a warning.

    Membership survives the toggle: `_apply_isolate` keeps its objects in
    the panel's ViewSelectedSet, and `state` only gates whether the panel
    honours it, so flipping it back leaves the isolate exactly as it was.

    Returns True (the isolate view failed), False (the scene really is
    empty), or None when the question could not be answered - which must
    stay distinct, because "I did not check" and "I checked" are different
    answers and the caller is told which one it got.
    """
    try:
        cmds.isolateSelect(panel, state=0)
        try:
            cmds.refresh(force=True)
            _, opacity = _grab_pixels(cmds, panel, resolution)
        finally:
            cmds.isolateSelect(panel, state=1)
    except Exception:  # noqa: BLE001 - a diagnostic must never fail a capture
        return None
    blank = opacity.get("blank")
    return None if blank is None else blank is False


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
    drawn: Optional[Tuple[int, int]] = None
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
            drawn = _read_color_buffer(path)
        if not os.path.exists(path):
            raise HandlerError(
                "viewport capture produced no image (playblast and M3dView both failed)",
                hint="make sure a viewport is visible and not minimized, then retry",
            )
        opacity = dict(pngprobe.opacity(path))
        # Same reason as drawn_size below: a per-frame measurement of this
        # file, taken while the file exists. #830 reads it to tell an
        # unbound-shader frame from a correct one.
        opacity["dominant"] = pngprobe.dominant_colour(path)
        # Carried in the opacity dict rather than as a third return value:
        # it is a per-frame MEASUREMENT of the file, exactly like `blank`,
        # and every stand-in for this function returns the pair. Only set
        # when the fallback actually changed the size - a playblast that
        # honoured widthHeight has nothing to report (#797 row 36).
        if drawn is not None and drawn != (resolution, resolution):
            opacity["drawn_size"] = list(drawn)
        with open(path, "rb") as fh:
            return fh.read(), opacity
    finally:
        if os.path.exists(path):
            os.unlink(path)


def _read_color_buffer(path: str) -> Optional[Tuple[int, int]]:
    """Fallback capture: read the active 3d view's color buffer (GUI only).

    Returns the size it actually DREW at, which is the panel's own, not the
    resolution the caller asked for: playblast honours widthHeight, while
    M3dView reads the framebuffer of a view that is whatever size the
    user's window makes it. So this path silently changes the image's scale,
    and until #797 row 36 no field said so - a caller measuring pixels off
    the frame had no way to know. None when the fallback did not run or the
    size could not be read.
    """
    try:
        import maya.OpenMaya as om  # noqa: PLC0415
        import maya.OpenMayaUI as omui  # noqa: PLC0415

        view = omui.M3dView.active3dView()
        view.refresh(False, True)
        image = om.MImage()
        view.readColorBuffer(image, True)
        image.writeToFile(path, "png")
        return int(view.portWidth()), int(view.portHeight())
    except Exception:
        return None  # caller reports the combined failure with a hint
