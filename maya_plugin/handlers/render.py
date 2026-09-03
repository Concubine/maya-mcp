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
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..dispatcher import HandlerError, refuse_inert, require_known_keys
from . import capture, lighting, naming, plugwrite, pngprobe, session

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

# The display transform the delivered frame is encoded with. Un-tone-mapped
# matches URP with post-processing off, which is where the game side is today;
# a tone-mapped view (ACES) would darken a linear-0.5 plane to 165 instead of
# 188 and put a look on an image whose job is to report the asset (#615).
DISPLAY_TRANSFORM = "Un-tone-mapped (sRGB)"


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


# Maya's own default on a fresh camera, and the ceiling we keep: at a normal
# framing the plane stays exactly where it has always been.
DEFAULT_NEAR_CLIP = 0.1
# Maya's own floor, MEASURED: setAttr refuses anything below 0.001 with
# "Cannot set the attribute ... below its minimum value of 0.001", and it
# raises rather than clamping - so a near plane computed from a camera sitting
# inside the subject took the whole render down with it (#670 live gate).
MIN_NEAR_CLIP = 0.001


def box_clearance(position, bbox_min, bbox_max) -> float:
    """Distance from `position` to the framed bounding box; 0.0 when inside it.

    The framing maths sizes its distance off the bounding SPHERE, which for
    anything tall or flat sits far outside the geometry - a near plane derived
    from it would be pushed in much harder than the subject needs. The box is
    the tightest bound already in hand.
    """
    gaps = [
        max(lo - p, 0.0, p - hi)
        for p, lo, hi in zip(position, bbox_min, bbox_max)
    ]
    return math.sqrt(sum(g * g for g in gaps))


def near_clip_for(position, bbox_min, bbox_max) -> float:
    """Near clip plane for a camera at `position` framing that box.

    Maya's default 0.1 is an ABSOLUTE distance while the framing distance
    scales with the subject and then divides by zoom, so a close framing walks
    the subject through a plane that never moved. Measured on #670: a ball
    0.044 in front of the camera was cut away entirely and the frame came back
    BLACK (mean luma 0.6 of 255), where the same framing with the plane below
    renders at 119.7.

    Renderer-dependent, and worth knowing before reproducing anything: hw2
    ignores nearClipPlane outright - forced deeper than the whole subject, an
    hw2 frame is pixel-identical - while arnold, the default and the renderer
    anyone judging a material is using, honours it.

    Half the clearance keeps the whole subject in front of the plane with
    margin. Capping at Maya's default means this can only ever un-clip: a
    subject that was already comfortably framed keeps the plane it had.
    """
    center = [(lo + hi) / 2.0 for lo, hi in zip(bbox_min, bbox_max)]
    distance = math.dist(list(position), center)
    clearance = box_clearance(position, bbox_min, bbox_max)
    return min(
        DEFAULT_NEAR_CLIP,
        max(clearance / 2.0, distance / 1000.0, MIN_NEAR_CLIP),
    )


def framing_warning(position, bbox_min, bbox_max, zoom: float, label: str):
    """Say so when the near plane cannot save this framing.

    Two cases, both of which come back as a picture that looks fine:

    - Past a zoom of about 3.4 the sight-line division puts the camera inside
      the subject's own bounds, and what renders is the inside of the surface -
      smooth, lit, entirely plausible, and not the thing anyone asked to see.
    - Closer than Maya's 0.001 minimum there is no plane left to move, so the
      subject is sliced no matter what we set.

    No clamp in either case: the caller asked for that zoom and gets it, but
    not silently.
    """
    clearance = box_clearance(position, bbox_min, bbox_max)
    if clearance <= 0.0:
        return (
            "the camera sits INSIDE the framed bounding box for %s at zoom "
            "%.2f: that frame may be showing the subject's interior, which "
            "renders as a plausible surface. Lower the zoom to put the camera "
            "back outside it." % (label, zoom)
        )
    if clearance <= MIN_NEAR_CLIP:
        return (
            "%s is %.4f from the camera at zoom %.2f, closer than the %.3f "
            "minimum Maya allows for a near clip plane: the front of it is "
            "clipped away and no plane can fix that. Lower the zoom."
            % (label, clearance, zoom, MIN_NEAR_CLIP)
        )
    return None


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


def _ensure_arnold_samples(cmds, samples: int) -> Tuple[Optional[str], Any]:
    """Write Arnold's AA sample count, building mtoa's globals node if needed.

    MEASURED (#797, cold mtoa load): on a Maya that has only just loaded
    mtoa, `defaultArnoldRenderOptions` does not exist yet - it is built lazily,
    when the Render Settings window (or `mtoa.core.createOptions`) first
    asks for it. The setAttr this code used to make therefore raised on a
    cold load and landed in a bare `except: pass`, so the frame rendered at
    Arnold's own default while the result reported the caller's `samples`
    back to them: a param validated, echoed, and never applied - #797's
    false claim in its purest form.

    Returns `(warning, restore_value)`:

      * `warning` when the count still could not be written, so the caller
        can null the value rather than claim it.
      * `restore_value` is the node's OWN default, read AFTER this call
        built the node and BEFORE our write - and only then. The caller
        hands it to `_RenderGlobalsState`, whose snapshot necessarily read
        nothing, because the node did not exist when it was taken. Without
        it a perception tool leaves the caller's AA count sitting in the
        user's scene for every render they make afterwards.
    """
    restore_value = None
    if not cmds.objExists("defaultArnoldRenderOptions"):
        try:
            from mtoa.core import createOptions  # noqa: PLC0415 - mtoa only

            createOptions()
        except Exception:  # noqa: BLE001 - mtoa build without the helper
            try:
                cmds.createNode("aiOptions", name="defaultArnoldRenderOptions",
                                shared=True, skipSelect=True)
            except Exception:  # noqa: BLE001 - reported by the write below
                pass
        # Asked rather than assumed: whichever route built it, Arnold's own
        # default is whatever the fresh node carries, and hardcoding a
        # number here would put OUR idea of a default into a user's scene.
        try:
            restore_value = cmds.getAttr("defaultArnoldRenderOptions.AASamples")
        except Exception:  # noqa: BLE001 - nothing was built; nothing to restore
            restore_value = None
    try:
        cmds.setAttr("defaultArnoldRenderOptions.AASamples", samples)
    except Exception as exc:  # noqa: BLE001 - any failure is reportable
        return ("arnold's AA sample count could not be set (%s), so this "
                "render used Arnold's own default rather than the samples=%d "
                "that was asked for - the result reports samples: null "
                "rather than a number it did not apply" % (exc, samples),
                restore_value)
    return None, restore_value


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
        # A plain re-assert per frame. _run_shots ensures the options node
        # exists and REPORTS what it could not write, once, before the loop -
        # doing that work again here would build the node under the frame
        # loop (outside the undo suppression the handler sets up) and throw
        # away the warning it produced.
        try:
            cmds.setAttr("defaultArnoldRenderOptions.AASamples", samples)
        except Exception:  # noqa: BLE001 - already reported by _run_shots
            pass
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


def _orient_rig(cmds, rig: Dict[str, float],
                azimuth_deg: float) -> Tuple[List[str], List[str]]:
    """Swing the tool's rig to sit behind the camera at `azimuth_deg`.

    setup_lighting builds a WORLD-locked rig while render_scene orbits the
    subject, so a side or back angle renders nearly black - measured on the
    #585 run: key at yaw +30, camera at yaw 90. Yaw only: the rig's elevation
    is the look, and only its bearing needs to follow the camera.

    Returns (warnings, refused): a warning per light it could NOT swing,
    and those lights' transforms so the caller can count what it DID swing.
    A user may key a rig light or park it on a constraint, and the write
    used to sit in a bare `except Exception: pass` while `relit_lights`
    reported the count of lights DISCOVERED - so the caller was told the
    rig had followed the camera and got the nearly-black side render this
    function exists to prevent (#802). The warning names the pass rather
    than a command, because _run_shots serves render_scene, render_sheet
    and preview_clip alike. The refusal is asked for rather than caught, because
    for a constrained or keyed rotateY there is no exception to catch: the
    setAttr is taken and the constraint or curve reasserts on the next
    evaluation (measured, evals/static_write_probe_802b.py O4/O6, K3/K5).

    A `cmds.xform(transform, edit=True, rotateAxis=(0, 0, 0))` used to sit
    above the yaw write, inside its own copy of the swallow. It is gone
    because it never ran: `cmds.xform` has NO `edit` flag, so that call
    raised "TypeError: Invalid flag 'edit'" on every render this function
    has ever done and the bare except ate it - found the moment #802's live
    gate removed the swallow, and confirmed against Maya 2027 on its own
    (`xform(loc, rotateAxis=...)` succeeds, `edit=True` raises). It is
    DELETED rather than repaired: making a write work for the first time is
    a behaviour change no measurement backs, and `_restore_rig` never put
    rotateAxis back, so a repair would leave a permanent mutation in the
    user's rig where today there is none.
    """
    warnings = []
    refused = []
    for transform, original_yaw in rig.items():
        blocked = plugwrite.blockers(cmds, [transform + ".rotateY"])
        if blocked:
            warnings.append(
                plugwrite.describe(blocked[0], "the relight pass")
                + " - it stays where you put it, so this angle is lit from "
                  "the rig's original bearing")
            refused.append(transform)
            continue
        cmds.setAttr(transform + ".rotateY", original_yaw + azimuth_deg)
    return warnings, refused


def _restore_rig(cmds, rig: Dict[str, float]) -> None:
    for transform, original_yaw in rig.items():
        # A light _orient_rig refused to swing was never moved, so putting
        # it back is a no-op that would refuse in its own right. The whole
        # body stays inside the swallow, guard included: this runs in a
        # `finally`, and a restore that raises - even from the guard's own
        # query, on a light something else deleted - would mask the error
        # that got us here.
        try:
            if plugwrite.blockers(cmds, [transform + ".rotateY"]):
                continue
            cmds.setAttr(transform + ".rotateY", original_yaw)
        except Exception:
            pass


def _under_any(name: str, roots: set) -> bool:
    return any(name.startswith(root + "|") for root in roots)


def _hide_non_targets(
    cmds, isolate: List[str], exclude: Optional[List[str]] = None,
    warnings: Optional[List[str]] = None,
) -> List[str]:
    """Hide every piece of geometry that is not in `isolate`; return what was hidden.

    A shape it could NOT hide is appended to `warnings` by name. A keyed or
    expression-driven `.visibility` is ordinary on a rig, and the refusal
    used to sit in the bare `except: pass` below with nothing said - so a
    rival subject stayed in the cell and the sheet reported no warnings at
    all, which is the #640 defect this function exists to prevent (#802).
    Measured: `cmds.hide` on such a shape does not even raise, it returns
    cleanly and leaves the shape visible, so the refusal has to be asked
    for rather than caught.

    `exclude` overrides the descendant rule below. Keeping a target's whole
    subtree is right for render_scene - isolate an assembly and you want to see
    the assembly - but a contact sheet's cells are siblings in one list, and on a
    parented rig one subject contains another: 14 of 29 cells came back as
    sub-assemblies, `golem_C_pelvis` rendering the entire golem (#640). The other
    subjects go in `exclude`, so each cell shows its own piece while descendants
    that are NOT cells of their own (a bolt, a trim strip) stay in frame.

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
    # Only excluded names UNDER a kept target matter: exclude exists purely to
    # override the descendant rule. An excluded ANCESTOR is already hidden by the
    # ordinary rule, and treating it as banished hid the kept target's own shape -
    # measured, the chest cell came back empty and its camera was placed 5.8e20
    # units out, because a subject nested between two other subjects has one of
    # them above it (#640).
    banished = set()
    for name in exclude or []:
        for long_name in cmds.ls(name, long=True) or [name]:
            if long_name not in keep and _under_any(long_name, keep):
                banished.add(long_name)
    # An aiSkyDomeLight answers ls(geometry=True). Hiding it turned every
    # isolated render under the environment/hdri presets into a pure black
    # frame - and those are the only presets in which a metal can be judged at
    # all, so the tool and the rig that need each other most could not be used
    # together (redmine #618). lighting.light_shapes is the one place that
    # knows what a light is; a second answer here would be a second thing to
    # get wrong.
    lights = set(lighting.light_shapes(cmds))
    hidden = []
    for name in cmds.ls(geometry=True, long=True) or []:
        if name in lights:
            continue
        if name in keep:
            continue
        if _under_any(name, keep) and not (
            name in banished or _under_any(name, banished)
        ):
            continue
        try:
            visible = cmds.getAttr(name + ".visibility")
        except Exception:  # noqa: BLE001 - a node that cannot even be asked
            continue       # stays in frame; nothing here can improve on that
        if not visible:
            # Already hidden by the user. Hiding it changes nothing, but
            # RESTORING it would show them an object they deliberately hid.
            continue
        # OUTSIDE the swallow, deliberately. Round 1 of this fix put the
        # guard inside it, and a guard that cannot answer then failed
        # silently into the very `except: pass` it was added to replace -
        # the same shape of defect, one layer up.
        blocked = plugwrite.blockers(cmds, [name + ".visibility"])
        if blocked:
            if warnings is not None:
                note = (plugwrite.describe(blocked[0], "the isolate pass")
                        + " - it stays in frame alongside the subject")
                # Deduped like the relight notes: a contact sheet
                # re-runs this pass once per cell, and the same rival
                # fails identically in every one of them.
                if note not in warnings:
                    warnings.append(note)
            continue
        try:
            cmds.hide(name)
        except Exception as exc:  # noqa: BLE001 - see the docstring
            # Unhideable for a reason plugwrite could not classify. It used
            # to `continue` with nothing said, which is the #640 defect this
            # function exists to prevent wearing a different coat: the rival
            # stays in the cell and the sheet reports no warnings at all
            # (#797 row 37). Deduped like the guarded note above - a sheet
            # re-runs this pass once per cell.
            if warnings is not None:
                note = ("could not hide %s for the isolate pass (%s) - it "
                        "stays in frame alongside the subject"
                        % (name.split("|")[-1], exc))
                if note not in warnings:
                    warnings.append(note)
            continue
        hidden.append(name)
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


# Every top-level key render_scene reads, the last six of them inside
# _run_shots rather than here. Anything else is refused rather than ignored
# (#767): an unread key does not fail, it succeeds and does something else.
RENDER_SCENE_KEYS = (
    "angles", "isolate", "target", "renderer", "resolution", "samples",
    "zoom", "relight", "fallback_light",
)
# `frame_on` is the name this handler itself gives `target` in the shot dicts
# below, so a caller who has read the code reaches for it; `subjects` is
# render_sheet's word for the objects to render, one tool over in this module.
RENDER_SCENE_SYNONYMS = {"frame_on": "target", "subjects": "isolate"}


def render_scene(params: Dict[str, Any]) -> Dict[str, Any]:
    """Render named angles through the render pipeline; no viewport involved."""
    require_known_keys(params, RENDER_SCENE_KEYS, "render_scene",
                       RENDER_SCENE_SYNONYMS)
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


# Every top-level key render_sheet reads, the last six of them inside
# _run_shots rather than here. Anything else is refused rather than ignored
# (#767): an unread key does not fail, it succeeds and does something else.
RENDER_SHEET_KEYS = (
    "subjects", "angle", "isolate", "renderer", "resolution", "samples",
    "zoom", "relight", "fallback_light",
)
# `target` is what render_scene and capture_viewport call the object to frame,
# and a sheet cell is that same object one per frame, so the singular and its
# plural both arrive here meaning `subjects`.
RENDER_SHEET_SYNONYMS = {"target": "subjects", "targets": "subjects"}


def render_sheet(params: Dict[str, Any]) -> Dict[str, Any]:
    """One frame per subject, each isolated and framed on itself, in ONE call.

    A kit contact sheet was 41 separate render_scene round-trips. Every one of
    them re-resolved the renderer, snapshotted and restored the render globals,
    built and deleted a camera, and re-hid the scene - all of which is setup,
    not picture. Here it happens once and the loop is just frames.

    The images come back as a list; the MCP server composites them, exactly as
    it already does for capture_turntable.
    """
    require_known_keys(params, RENDER_SHEET_KEYS, "render_sheet",
                       RENDER_SHEET_SYNONYMS)
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
    # #797 row 21: a sheet builds its OWN offscreen camera per cell, so
    # there is no panel camera for "current" to mean. _run_shots degrades it
    # to three_quarter and every cell came back labelled "current" - a label
    # naming an angle that was not shot. render_scene's schema promises that
    # degrade and this one does not, so here it is a refusal rather than a
    # relabel.
    if angle == "current":
        refuse_inert(
            "render_sheet", "angle", "when it is 'current'",
            "a sheet renders offscreen with a camera it places per cell - "
            "there is no viewport camera to keep, so 'current' would be "
            "shot as three_quarter under the wrong label",
            hint="name the angle you want (front, side, back, top, "
                 "three_quarter); to shoot the panel as it stands use "
                 "maya_capture_viewport",
        )
    # Isolating is the POINT of a sheet: each cell must show one piece, not one
    # piece in front of forty others. Opting out is allowed for a subject that
    # needs its surroundings (a transmissive material refracts them).
    isolate_each = bool(params.get("isolate", True))
    # The other subjects are this cell's rivals, not its content: on a parented
    # rig one subject contains another, and keeping the subtree made 14 of 29
    # cells render sub-assemblies (#640). Each cell frames what it still shows.
    shots = [
        {"label": subject, "angle": angle,
         "isolate": [subject] if isolate_each else None,
         "exclude": [s for s in subjects if s != subject] if isolate_each else None,
         "frame_on": [subject],
         "frame_visible_only": isolate_each}
        for subject in subjects
    ]
    result = _run_shots(_cmds(), shots, params)
    result["warnings"] = _nesting_warnings(_cmds(), subjects) + result.get(
        "warnings", []
    )
    return result


def _nesting_warnings(cmds, subjects: List[str]) -> List[str]:
    """Say which subjects contain which others - the cells whose content changed.

    The nesting is hidden in the hierarchy, and a caller reading a sheet cannot
    tell "this piece looks like the whole rig" from "this piece IS the whole
    rig". Naming it is cheap and turns a surprise into a stated decision.
    """
    resolved = {}
    for subject in subjects:
        matches = cmds.ls(subject, long=True) or []
        if len(matches) == 1:
            resolved[subject] = matches[0]
    warnings = []
    for subject, long_name in resolved.items():
        contained = sorted(
            other for other, other_long in resolved.items()
            if other != subject and other_long.startswith(long_name + "|")
        )
        if contained:
            warnings.append(
                "%s contains %d other subject(s) (%s): their geometry was hidden "
                "in %s's cell, which shows only its own pieces"
                % (subject, len(contained), ", ".join(contained[:4])
                   + (", ..." if len(contained) > 4 else ""), subject)
            )
    return warnings


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

    # #797 row 29: hw2 has no AA sample count - it draws the viewport's own
    # image and _render_frame never even looks at `samples` there - so the
    # value is validated and dropped. Echoing it back in the result was a
    # false claim the caller had no way to check: they read samples: 6 and
    # believe the frame was sampled six times. The result carries null
    # instead, and says so ONCE when the caller actually asked for a count
    # (the wrapper now defaults it to None, so "asked" is knowable).
    reports_samples = renderer != "hw2"
    setup_warnings: List[str] = []
    if not reports_samples and params.get("samples") is not None:
        setup_warnings.append(
            "renderer 'hw2' has no AA sample count - it draws the viewport's "
            "own image - so samples=%d was dropped and the result reports "
            "samples: null. Use renderer='arnold' to control sampling."
            % samples)

    maya_renderer = RENDERER_TO_MAYA[renderer]
    available = _ensure_renderer(cmds, maya_renderer)
    if available and maya_renderer not in available:
        # This refusal raises before the try/finally below, so #721 hygiene
        # deliberately does NOT run here: an ARV can only be leaked by a
        # PRIOR render (whose own finally already cleaned it up) or by
        # something else opening it by hand (author_clip's/preview_clip's
        # own guard covers that case before any keyframe work touches it) -
        # this call never got far enough to open or touch one itself.
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
    hygiene: List[str] = []
    prev_undo = cmds.undoInfo(query=True, state=True)
    cmds.undoInfo(stateWithoutFlush=False)
    prev_time = (cmds.currentTime(query=True)
                 if any(s.get("time") is not None for s in shots) else None)
    try:
        # AFTER the snapshot, so the restore puts the user's own count back;
        # after the undo suppression, because on a cold mtoa this BUILDS a
        # node and render_scene/render_sheet are no_undo_chunk - a
        # perception tool's createNode landing loose in the user's undo
        # queue is exactly the pollution that suppression prevents; and
        # inside the try, so a failure here still unwinds through the
        # finally rather than leaving undo recording off.
        if renderer == "arnold":
            note, aa_restore = _ensure_arnold_samples(cmds, samples)
            if aa_restore is not None:
                # The snapshot above read nothing - the node did not exist
                # yet - so hand it the fresh node's own default, or the
                # caller's AA count outlives this render in their scene.
                state.aa_samples = aa_restore
            if note is not None:
                setup_warnings.append(note)
                reports_samples = False  # never claim a count not applied

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
        framing_warnings: List[str] = list(setup_warnings)
        # Rig lights the relight pass could not swing, across every shot.
        # `relit_lights` used to be len(rig) - lights DISCOVERED - so a rig
        # whose every write was refused still reported that it had followed
        # the camera (#802). The count is what was actually moved now, and
        # the warnings name the rest; the two cannot disagree.
        unswung: set = set()
        # (isolate, exclude) - the pair that decides what is visible.
        current_isolate: Optional[tuple] = None
        for index, shot in enumerate(shots):
            if shot.get("time") is not None:
                cmds.currentTime(shot["time"])
            angle = shot["angle"]
            # "current" has no meaning without a panel to read a camera
            # from; it degrades to the default judging angle rather than
            # failing a render the caller could not have known was
            # panel-dependent - render_scene's schema PROMISES that. What it
            # must not do is keep the old label: every frame came back
            # named "current" while three_quarter was what was shot, and
            # both the image and its camera_positions entry said so (#797
            # row 30). The resolved name travels with the frame instead,
            # and `requested_angle` records what was asked for.
            resolved_angle = "three_quarter" if angle == "current" else angle
            if angle != resolved_angle:
                note = ("angle 'current' has no meaning offscreen - there is "
                        "no panel camera to read - so this render used "
                        "'%s', the default judging angle. The frames and "
                        "camera_positions below are labelled with what was "
                        "actually shot." % resolved_angle)
                if note not in framing_warnings:
                    framing_warnings.append(note)
            # Re-hide only when the visible set actually changes: render_scene
            # holds one isolate set across all its angles, and re-walking every
            # shape in a 45,000-renderer city per frame would cost more than the
            # renders.
            # The exclude set differs per sheet cell even when isolate does not,
            # so both have to be part of "did the visible set change".
            visible_key = (shot["isolate"], shot.get("exclude"))
            if visible_key != current_isolate:
                for name in hidden:
                    try:
                        cmds.showHidden(name)
                    except Exception:
                        pass
                hidden = (
                    _hide_non_targets(cmds, shot["isolate"],
                                      shot.get("exclude"), framing_warnings)
                    if shot["isolate"] else []
                )
                current_isolate = visible_key

            if not (shot.get("reuse_camera") and temp_camera is not None):
                # A shot may carry its own framing box: a HELD camera is only
                # honest if its frame contains the subject at every time it
                # will be shot at, and only the caller knows those times -
                # preview_clip passes the union of the subject's bounds
                # across all its sampled frames (#780: a walking clip left
                # its frame-0 framing at frame 105 and every later cell was
                # the same subject-less render).
                if shot.get("bbox") is not None:
                    bbox_min, bbox_max = shot["bbox"]
                else:
                    bbox_min, bbox_max = capture._scene_bbox(
                        cmds, shot["frame_on"],
                        visible_only=bool(shot.get("frame_visible_only"))
                    )
                position, rotation = capture.camera_placement(
                    resolved_angle, bbox_min, bbox_max
                )
                if zoom != 1.0:
                    position = zoomed_position(position, bbox_min, bbox_max, zoom)
                if relight:
                    # Deduped: _orient_rig runs once per shot and a light the
                    # rig cannot swing fails identically on every one of
                    # them, so an 8-angle turntable would otherwise say the
                    # same sentence eight times.
                    notes, refused = _orient_rig(
                        cmds, rig,
                        capture._ANGLE_DIRECTIONS[resolved_angle][0])
                    for note in notes:
                        if note not in framing_warnings:
                            framing_warnings.append(note)
                    unswung.update(refused)
                if temp_camera is None:
                    created = cmds.camera()[0]
                    temp_camera = cmds.rename(created, naming.unique_name(cmds, _TEMP_CAM))
                    # No panel means no viewFit to refine the framing, so the
                    # camera must really have the field of view the placement
                    # math assumes. This used to compute the lens from a
                    # hardcoded VERTICAL aperture of 0.981 in, against a
                    # camera that measures 0.9449 in and fits horizontally -
                    # so it was wrong twice over and nothing could see it
                    # (#772). apply_framing_fov reads the film back instead.
                    capture.apply_framing_fov(cmds, temp_camera)
                cmds.setAttr(temp_camera + ".translate", *position, type="double3")
                cmds.setAttr(temp_camera + ".rotate", *rotation, type="double3")
                # The plane has to move with the framing, not stay at the
                # absolute 0.1 a fresh camera is born with (#670).
                cmds.setAttr(
                    temp_camera + ".nearClipPlane",
                    near_clip_for(position, bbox_min, bbox_max),
                )
                unfixable = framing_warning(
                    position, bbox_min, bbox_max, zoom, shot["label"]
                )
                if unfixable is not None:
                    framing_warnings.append(unfixable)

            path = _render_frame(
                cmds, temp_camera, frame_prefix(call_id, index, resolved_angle),
                maya_renderer, resolution, samples,
            )
            if not path or not os.path.exists(path):
                raise HandlerError(
                    "renderer %r produced no image file (reported %r)"
                    % (renderer, path),
                    hint="check Maya's script editor output; for arnold, "
                    "confirm the mtoa plugin is loaded",
                )
            # The #765 lesson applied to the render path: a valid PNG of
            # nothing is a success code wearing a failure. Probed while the
            # file still exists (opacity reads from disk), reported as a
            # warning rather than a refusal because "nothing here" is a
            # legitimate render of an empty view - the caller just must be
            # TOLD, not left to eyeball 16 identical background cells (#780).
            probe = pngprobe.opacity(path)
            if probe.get("blank"):
                framing_warnings.append(
                    "%s drew nothing - zero opaque pixels; the subject is "
                    "outside this frame (or nothing is lit)" % shot["label"])
            try:
                with open(path, "rb") as fh:
                    png = fh.read()
            finally:
                try:
                    os.unlink(path)  # the render lands in the project images dir
                except OSError:
                    pass
            image = {
                "angle": resolved_angle, "label": shot["label"],
                "png_b64": base64.b64encode(png).decode("ascii"),
            }
            pos = cmds.getAttr(temp_camera + ".translate")[0]
            rot = cmds.getAttr(temp_camera + ".rotate")[0]
            position_entry = {
                "angle": resolved_angle, "label": shot["label"],
                "position": list(pos), "rotation": list(rot),
                "camera": temp_camera,
                "near_clip": cmds.getAttr(temp_camera + ".nearClipPlane"),
            }
            if angle != resolved_angle:
                # Only when they differ: an extra key on every ordinary
                # frame is noise, and its absence is the honest signal that
                # what was asked for is what was shot.
                image["requested_angle"] = angle
                position_entry["requested_angle"] = angle
            images_out.append(image)
            positions.append(position_entry)

        out = {
            "images": images_out,
            "camera_positions": positions,
            "renderer": renderer,
            "samples": samples if reports_samples else None,
            "fallback_light": temp_light is not None,
            "zoom": zoom,
            "relit_lights": len(rig) - len(unswung),
            "warnings": framing_warnings,
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
        if prev_time is not None:
            try:
                cmds.currentTime(prev_time)
            except Exception:
                pass
        state.restore()
        try:
            cmds.undoInfo(stateWithoutFlush=prev_undo)
        except Exception:
            pass
        hygiene = session.stop_idle_ipr(cmds)

    out.setdefault("warnings", []).extend(
        a + " after rendering - an idle IPR re-renders on every scene "
        "mutation and can wedge later keyframe work (#721)"
        for a in hygiene)
    return out


# Perception must not pollute the user's undo queue.
render_scene.no_undo_chunk = True
render_sheet.no_undo_chunk = True
