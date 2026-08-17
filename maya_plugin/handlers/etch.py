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
# vectorAdjust/shellDeformer no longer appear here: _create_glyph never wires
# them in (see its docstring) - they only existed to drive interactive
# per-glyph manipulator dragging, which this tool never does.
_TYPE_NODE_TYPES = ("type", "typeExtrude")


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
    # NOT it.getNormal(om.MSpace.kWorld): MItMeshPolygon.getNormal is overloaded
    # as getNormal(space) AND getNormal(vertexIndex[, space]), and a POSITIONAL
    # int binds to the vertex overload - MSpace.kWorld is 4, so that call
    # silently returns "the normal at face-local vertex 4" instead of the face
    # normal. On a cube it yields the NEXT face's normal for every face
    # (verified live on Maya 2027, api 20270200: face 0, center (0,0,0.5),
    # returned (0,1,0) instead of (0,0,1)), so etch_text carved every glyph into
    # the wrong plane. it.getNormal(space=...) is correct, but MFnMesh's
    # getPolygonNormal has no overload to fall into at all - prefer it.
    normal = om.MFnMesh(dag).getPolygonNormal(face, om.MSpace.kWorld)
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
    # ------------------------------------------------------------------
    # Why this doesn't call CreatePolygonType / typeCreateText anymore:
    #
    # mel.eval("CreatePolygonType;") (old code) resolves - via
    # defaultRunTimeCommands.mel - to the MEL proc typeCreateText, which
    # calls Python's maya.app.type.typeToolSetup.createTypeTool(). In a GUI
    # Maya that establishes the interactive Type tool context (a manipulator
    # + tool state machine waiting for viewport/UI interaction) rather than
    # just creating nodes, and never returns - it hung a live GUI session
    # indefinitely. Because the handler runs on Maya's main thread via
    # executeInMainThreadWithResult, that hang froze Dispatcher's single
    # worker thread forever, which set dispatcher._straggler and made every
    # later request fail BusyError until Maya was killed (redmine #577).
    # mayapy standalone never showed this because standalone has no tool
    # context/manipulator system to enter, so the interactive path silently
    # behaves like a plain node-creation call there - mayapy green was not
    # sufficient evidence the interactive path was safe.
    #
    # Investigated on this install (Maya 2027) by reading
    # E:/Autodesk/Maya2027/Python/Lib/site-packages/maya/app/type/typeToolSetup.py
    # (createTypeTool/createTypeToolWithNode - the actual implementation
    # CreatePolygonType/typeCreateText delegates to) plus the MEL call chain
    # (defaultRunTimeCommands.mel -> typeCreateText.mel -> typeInitPlugin.mel,
    # which only sources Attribute Editor templates and registers UI
    # callbacks - irrelevant to node evaluation). There is no `cmds.type`
    # command (cmds.help("type") -> "no command named type"); the Type
    # plugin's public surface is entirely through cmds.createNode. The
    # reference implementation itself proves the whole glyph mesh is buildable
    # with plain createNode/connectAttr/setAttr - the interactive entry point
    # was never required to get geometry, only to let a user drag it in the
    # viewport.
    #
    # So: build the minimal subgraph directly, matching what
    # createTypeToolWithNode wires for the mesh-producing chain
    # (type.outputMesh -> typeExtrude.inputMesh -> mesh.inMesh), and stop
    # there. We deliberately skip createTypeToolWithNode/createTypeTool
    # themselves too, not just CreatePolygonType, because outside batch mode
    # they end with cmds.evalDeferred(...showEditorExact...) - popping the
    # interactive Type Editor panel as a side effect of a headless call - and
    # they also wire vectorAdjust/shellDeformer "adjust" deformers, which
    # exist solely to support per-glyph interactive manipulator dragging
    # (their inputs are literally named manipulatorTransforms). We never
    # need per-glyph manipulation: etch_text immediately bakes the whole
    # glyph transform with a uniform scale/rotate/translate and then calls
    # `cmds.delete(glyph_tf, constructionHistory=True)` to freeze it before
    # handing it to the boolean, so that machinery would be built only to be
    # discarded. Remesh/UV/shader nodes are skipped for the same reason -
    # none of them affect the frozen mesh a boolean difference consumes.
    #
    # DO NOT restore mel.eval("CreatePolygonType;") or call
    # maya.app.type.typeToolSetup.createTypeTool()/createTypeToolWithNode() -
    # see the paragraphs above.
    type_node = cmds.createNode("type", name="type#", skipSelect=True)
    type_extrude = cmds.createNode("typeExtrude", name="typeExtrude#", skipSelect=True)
    glyph_tf = cmds.createNode("transform", name="typeMesh#", skipSelect=True)
    glyph_mesh = cmds.createNode(
        "mesh", name="typeMeshShape#", parent=glyph_tf, skipSelect=True
    )
    cmds.connectAttr(type_node + ".vertsPerChar", type_extrude + ".vertsPerChar")
    cmds.connectAttr(type_node + ".outputMesh", type_extrude + ".inputMesh")
    cmds.connectAttr(type_extrude + ".outputMesh", glyph_mesh + ".inMesh")

    hex_codes = " ".join("%X" % ord(ch) for ch in text)
    cmds.setAttr(type_node + ".textInput", hex_codes, type="string")
    cmds.setAttr(type_node + ".currentFont", font, type="string")
    cmds.setAttr(type_node + ".alignmentMode", 2)  # center
    try:
        cmds.setAttr(type_extrude + ".extrudeDistance", 0.1)
    except Exception:
        pass  # depth is forced via scale anyway
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
    transforms_before = set(cmds.ls(type="transform") or [])
    glyph_tf = None
    # Any transform newly created by _create_glyph (the glyph mesh itself,
    # plus a manipulator handle on any failure path that raises before
    # _create_glyph reaches its own extras cleanup) - captured immediately
    # after that call returns or raises, before _do_boolean creates the
    # (legitimate, wanted) output transform. The _TYPE_NODE_TYPES sweep below
    # only ever caught the Type/history *nodes*, never the mesh transform
    # CreatePolygonType built - that is what actually orphaned it.
    created_transforms: set = set()
    try:
        try:
            glyph_tf = _create_glyph(cmds, text, font)
        finally:
            created_transforms = set(cmds.ls(type="transform") or []) - transforms_before
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
        if mirror:
            # A negative scale factor mirrors the mesh, which reverses its face
            # winding: the cutter ends up inside-out, and polyBoolOp reads an
            # inside-out operand as its own complement - so "difference"
            # silently returned the INTERSECTION (the carve volume alone,
            # 2 x 2.14 x 0.3) instead of the carved host. Reverse the winding
            # back before the boolean. Done before the constructionHistory
            # delete below so that delete bakes it out too - no history node
            # survives (zero-orphan discipline).
            cmds.polyNormal(glyph_tf, normalMode=0, userNormalMode=0)
        cmds.delete(glyph_tf, constructionHistory=True)  # freeze type network out

        # Raw, not uniquified: etching into X and keeping the result called X is
        # the natural request, and X is consumed by this boolean (#640).
        result = modeling._do_boolean(
            cmds, mesh_long, glyph_tf, "difference",
            str(params.get("new_name") or "").strip()
            or mesh_long.split("|")[-1] + "_etched",
        )
    finally:
        # zero orphan history nodes: sweep anything the Type network left behind
        for node_type, before in node_snapshot.items():
            for node in _ls_safe(node_type) - before:
                try:
                    cmds.delete(node)
                except Exception:
                    pass
        # zero orphan glyph mesh: on success _do_boolean consumes glyph_tf
        # (it stops existing), so this is a no-op there. On any failure
        # between glyph creation and a successful boolean, it - and any
        # manipulator handle a failure-before-cleanup path left alongside
        # it - is still sitting at the face center, inside the target's
        # bbox, waiting to be swallowed by a later boolean call by accident.
        for node in created_transforms:
            if cmds.objExists(node):
                try:
                    cmds.delete(node)
                except Exception:
                    pass
    result["carved_text"] = text
    return result
