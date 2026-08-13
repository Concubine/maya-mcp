"""capture_viewport: THE critical tool — the LLM's eyes.

Temporary offscreen camera per angle, viewFit, single-frame playblast
(fallback: M3dView.readColorBuffer), returned as base64 PNG. A perception call
must be side-effect-free: every panel/scene setting touched is snapshotted and
restored, temp cameras deleted, selection restored.

The placement math is pure (tested headless); only _capture_one touches maya.
"""

from __future__ import annotations

import base64
import math
import os
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..dispatcher import HandlerError

VALID_ANGLES = ("front", "side", "back", "top", "three_quarter", "current")
VALID_SHADING = ("smoothShaded", "flatShaded", "wireframe", "textured")
VALID_BUFFERS = ("beauty", "ssao")
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


def camera_placement(
    angle: str, bbox_min: Sequence[float], bbox_max: Sequence[float]
) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    """Camera position and euler rotation (deg, Maya xyz order) for an angle.

    Points the camera at the bbox center from far enough away that the bounding
    sphere fits inside the field of view; viewFit refines the framing afterwards.
    """
    azimuth_deg, elevation_deg = _ANGLE_DIRECTIONS[angle]
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


# ------------------------------------------------------------------- handler


def capture_viewport(params: Dict[str, Any]) -> Dict[str, Any]:
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
    wireframe_overlay = bool(params.get("wireframe_overlay", True))
    frame_all = bool(params.get("frame_all", True))
    resolution = clamp_resolution(params.get("resolution"))
    isolate = params.get("isolate")
    if isolate is not None and (
        not isinstance(isolate, list) or not all(isinstance(n, str) for n in isolate)
    ):
        raise HandlerError(
            "isolate must be a list of object names",
            hint='e.g. isolate=["|golem"]; call maya_get_scene_graph for names',
        )

    images = []
    camera_positions = []
    for angle in angles:
        shot = _capture_one(
            angle, shading, wireframe_overlay, buffer, isolate, frame_all, resolution
        )
        images.append({"angle": angle, "png_b64": shot["png_b64"]})
        camera_positions.append(
            {
                "angle": angle,
                "position": shot["camera_position"],
                "rotation": shot["camera_rotation"],
                "camera": shot["camera"],
            }
        )
    return {"images": images, "camera_positions": camera_positions}


# ------------------------------------------------------------- maya internals


def _scene_bbox(cmds, isolate: Optional[List[str]]):
    """World bbox of the isolate set, or of all visible geometry."""
    if isolate:
        missing = [n for n in isolate if not cmds.objExists(n)]
        if missing:
            raise HandlerError(
                "isolate objects not found: %s" % ", ".join(missing),
                hint="call maya_get_scene_graph to list objects",
            )
        targets = isolate
    else:
        targets = cmds.ls(geometry=True, visible=True) or []
    if not targets:
        return [-1.0, -1.0, -1.0], [1.0, 1.0, 1.0]
    bbox = cmds.exactWorldBoundingBox(*targets)
    return list(bbox[:3]), list(bbox[3:])


def _find_model_panel(cmds) -> str:
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
        "no model panel available to capture from",
        hint="open a viewport in Maya (capture does not work in batch/mayapy mode)",
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
    angle: str,
    shading: str,
    wireframe_overlay: bool,
    buffer: str,
    isolate: Optional[List[str]],
    frame_all: bool,
    resolution: int,
) -> Dict[str, Any]:
    cmds = _cmds()
    panel = _find_model_panel(cmds)
    state = _PanelState(cmds, panel)
    temp_camera = None
    # Perception must not pollute the undo queue: suppress undo recording for
    # the whole capture (temp camera, setAttrs, isolate churn) so the
    # dispatcher's chunk closes empty and Maya discards it. stateWithoutFlush
    # keeps the user's existing undo history intact.
    prev_undo = cmds.undoInfo(query=True, state=True)
    cmds.undoInfo(stateWithoutFlush=False)
    try:
        if angle == "current":
            capture_cam = state.camera
        else:
            bbox_min, bbox_max = _scene_bbox(cmds, isolate)
            position, rotation = camera_placement(angle, bbox_min, bbox_max)
            temp_camera = cmds.camera(name="mayaMcpTempCam")[0]
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
            if isolate:
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

        png_bytes = _grab_pixels(cmds, panel, resolution)

        pos = cmds.getAttr(capture_cam + ".translate")[0]
        rot = cmds.getAttr(capture_cam + ".rotate")[0]
        camera_long = (cmds.ls(capture_cam, long=True) or [capture_cam])[0]
        return {
            "png_b64": base64.b64encode(png_bytes).decode("ascii"),
            "camera_position": list(pos),
            "camera_rotation": list(rot),
            "camera": camera_long,
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


def _grab_pixels(cmds, panel: str, resolution: int) -> bytes:
    """Playblast a single frame offscreen; fall back to M3dView.readColorBuffer."""
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
        with open(path, "rb") as fh:
            return fh.read()
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
