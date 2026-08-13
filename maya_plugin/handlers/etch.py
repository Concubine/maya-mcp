"""etch_text: carve text/glyphs into a mesh face in one call (#577 req 2).

Golem-run lessons baked in: the Type node's extrude attrs are unreliable
(measure the raw bbox and force depth via scale); placement is computed in
the target face's actual normal frame from mesh data (plane math breaks on
polySmooth-bowed faces); boolean output needs the Task-6 SG cleanup; every
Type-network node this tool creates is deleted afterwards - zero orphans.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

from ..dispatcher import HandlerError
from . import naming

DEFAULT_WIDTH = 0.6
DEFAULT_DEPTH = 0.1
DEFAULT_FONT = "Arial"
_TYPE_NODE_TYPES = ("type", "typeExtrude", "vectorAdjust", "shellDeformer")


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


# ------------------------------------------------------------------ pure math


def face_frame_transform(
    face_center: List[float],
    face_normal: List[float],
    glyph_bbox_min: List[float],
    glyph_bbox_max: List[float],
    width: float,
    depth: float,
) -> Dict[str, List[float]]:
    """Scale/rotate/translate placing a raw +Z-facing glyph onto a face.

    Cutter thickness is forced to 2*depth and its center sits ON the face, so
    the boolean difference carves exactly `depth` into the surface regardless
    of what the Type node's extrude attrs actually produced.
    """
    size = [hi - lo for lo, hi in zip(glyph_bbox_min, glyph_bbox_max)]
    if min(size) <= 1e-9:
        raise HandlerError(
            "glyph bounding box is degenerate (%r)" % (size,),
            hint="the Type node produced no geometry; check the text/font",
        )
    length = math.sqrt(sum(n * n for n in face_normal))
    if length <= 1e-9:
        raise HandlerError("face normal is zero", hint="pick a non-degenerate face")
    nx, ny, nz = (n / length for n in face_normal)

    in_plane = width / size[0]
    scale = [in_plane, in_plane, (2.0 * depth) / size[2]]
    # Same convention as capture.camera_placement: pitch = -elevation,
    # yaw = azimuth (0 = +Z), no roll, Maya xyz rotate order.
    elevation = math.degrees(math.asin(max(-1.0, min(1.0, ny))))
    azimuth = math.degrees(math.atan2(nx, nz))
    rotate = [-elevation, azimuth, 0.0]
    return {"scale": scale, "rotate": rotate, "translate": list(face_center)}


# ------------------------------------------------------------------- handler


def _face_center_normal(mesh_long: str, face: int):
    import maya.api.OpenMaya as om  # noqa: PLC0415

    sel = om.MSelectionList()
    sel.add(mesh_long)
    dag = sel.getDagPath(0)
    it = om.MItMeshPolygon(dag)
    if face < 0 or face >= it.count():
        raise HandlerError(
            "face %d out of range (mesh has %d faces)" % (face, it.count()),
            hint="faces are 0-indexed; capture with wireframe_overlay to pick one",
        )
    it.setIndex(face)
    center = it.center(om.MSpace.kWorld)
    normal = it.getNormal(om.MSpace.kWorld)
    return [center.x, center.y, center.z], [normal.x, normal.y, normal.z]


def _create_glyph(cmds, text: str, font: str) -> str:
    # cmds.loadPlugin returns the list of newly-loaded plugin names, which is
    # empty/falsy when the plugin is ALREADY loaded (not just when it's
    # unavailable) - and RuntimeErrors instead of returning falsy when the
    # plugin genuinely can't be found. Confirmed live on Maya 2027 standalone:
    # a second loadPlugin("Type") call returns None even though isPluginLoaded
    # is True. So: try the load, then fall back to an explicit loaded check
    # (case-correct - Maya registers it as "Type", not "type") before giving up.
    try:
        newly_loaded = cmds.loadPlugin("Type", quiet=True)
    except RuntimeError:
        newly_loaded = None
    if not newly_loaded:
        try:
            loaded = cmds.pluginInfo("Type", query=True, loaded=True)
        except Exception:
            # pluginInfo itself raises for a plugin Maya has never registered,
            # rather than returning a falsy value - treat that the same as
            # "not loaded" so we still surface the intended HandlerError.
            loaded = False
        if not loaded:
            raise HandlerError(
                "the Type plugin is not available in this Maya",
                hint="etch needs Maya's Type tool; carve with maya_boolean_op "
                "and a custom cutter mesh instead",
            )
    import maya.mel as mel  # noqa: PLC0415

    before = set(cmds.ls(type="transform"))
    mel.eval("CreatePolygonType;")
    created = [t for t in cmds.ls(type="transform") if t not in before]
    if not created:
        raise HandlerError(
            "CreatePolygonType produced no transform",
            hint="the Type plugin misbehaved; retry or carve with maya_boolean_op",
        )
    # CreatePolygonType creates TWO new transforms: the typeMesh transform
    # (mesh shape, what we want) and a handle/manipulator transform (a
    # displayPoints locator) used for interactive dragging - not creation
    # order guaranteed, so pick by shape type rather than created[0].
    # Confirmed live on Maya 2027 standalone: ls(type="transform") right
    # after CreatePolygonType returns the manipulator transform FIRST.
    mesh_created = [
        t for t in created
        if any(
            cmds.nodeType(s) == "mesh"
            for s in (cmds.listRelatives(t, shapes=True, fullPath=True) or [])
        )
    ]
    if not mesh_created:
        raise HandlerError(
            "CreatePolygonType produced no mesh transform",
            hint="the Type plugin misbehaved; retry or carve with maya_boolean_op",
        )
    glyph_tf = mesh_created[0]
    extras = [t for t in created if t != glyph_tf]
    if extras:
        cmds.delete(extras)  # the manipulator handle is not needed headless
    type_node = (cmds.ls(type="type") or [])[-1]
    hex_codes = " ".join("%X" % ord(ch) for ch in text)
    cmds.setAttr(type_node + ".textInput", hex_codes, type="string")
    cmds.setAttr(type_node + ".currentFont", font, type="string")
    cmds.setAttr(type_node + ".alignmentMode", 2)  # center
    try:
        cmds.setAttr(type_node + ".extrudeEnable", 1)
        cmds.setAttr(type_node + ".extrudeDistance", 0.1)
    except Exception:
        pass  # depth is forced via scale anyway
    cmds.refresh()
    return glyph_tf


def etch_text(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    from . import modeling, session  # noqa: PLC0415

    mesh_long, _ = naming.require_mesh(cmds, str(params.get("mesh") or ""))
    text = params.get("text")
    if not isinstance(text, str) or not text.strip():
        raise HandlerError(
            "missing required param 'text'",
            hint="pass the characters to carve, e.g. text='\\u05d0' for an aleph",
        )
    face = params.get("face")
    if not isinstance(face, int) or isinstance(face, bool):
        raise HandlerError(
            "missing required param 'face' (int face id)",
            hint="pick the face to carve into; capture with wireframe_overlay "
            "to identify face ids",
        )
    width = float(params.get("width") or DEFAULT_WIDTH)
    depth = float(params.get("depth") or DEFAULT_DEPTH)
    if width <= 0 or depth <= 0:
        raise HandlerError("width and depth must be positive", hint="sizes are in scene units")
    font = str(params.get("font") or DEFAULT_FONT)
    mirror = bool(params.get("mirror", False))
    rotate_deg = float(params.get("rotate_deg") or 0.0)

    center, normal = _face_center_normal(mesh_long, face)
    session.auto_checkpoint("etch")

    def _ls_safe(node_type: str) -> set:
        # unknown node types raise until the Type plugin has been loaded once
        try:
            return set(cmds.ls(type=node_type) or [])
        except Exception:
            return set()

    node_snapshot = {t: _ls_safe(t) for t in _TYPE_NODE_TYPES}
    glyph_tf = None
    try:
        glyph_tf = _create_glyph(cmds, text, font)
        bbox = cmds.exactWorldBoundingBox(glyph_tf)
        placement = face_frame_transform(center, normal, bbox[:3], bbox[3:], width, depth)
        scale = placement["scale"]
        if mirror:
            scale = [-scale[0], scale[1], scale[2]]
        cmds.xform(glyph_tf, scale=scale)
        cmds.xform(glyph_tf, rotation=placement["rotate"], worldSpace=True)
        if rotate_deg:
            cmds.rotate(rotate_deg, glyph_tf, z=True, objectSpace=True, relative=True)
        # after scaling, recenter the glyph bbox onto the face center
        bbox = cmds.exactWorldBoundingBox(glyph_tf)
        current = [(lo + hi) / 2.0 for lo, hi in zip(bbox[:3], bbox[3:])]
        offset = [t - c for t, c in zip(placement["translate"], current)]
        cmds.xform(glyph_tf, translation=offset, relative=True, worldSpace=True)
        cmds.delete(glyph_tf, constructionHistory=True)  # freeze type network out

        result = modeling._do_boolean(
            cmds, mesh_long, glyph_tf, "difference",
            naming.unique_name(cmds, str(params.get("new_name") or "") or
                               mesh_long.split("|")[-1] + "_etched"),
        )
    finally:
        # zero orphan history nodes: sweep anything the Type network left behind
        for node_type, before in node_snapshot.items():
            for node in _ls_safe(node_type) - before:
                try:
                    cmds.delete(node)
                except Exception:
                    pass
    result["carved_text"] = text
    return result
