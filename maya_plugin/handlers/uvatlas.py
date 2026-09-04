"""maya_uv_atlas: pack a mesh's UVs into one patch of a texture atlas.

The reason this exists is a constraint that arrives from the consumer, not
from Maya: an engine batches instanced geometry BY MATERIAL, so a kit of parts
that has to be drawn tens of thousands of times can afford exactly one
material. Every material difference the art still needs - brick against glass
against steel, a dark recess against a lit face - therefore has to live in a
single shared texture, which means every piece must be told which region of
that texture it reads from.

The arithmetic is in uvmath.py and is tested headless. This module drives
cmds and, importantly, MEASURES THE RESULT: it reports the UV bounding box each
mesh actually ended up with, so a caller can see the packing landed rather than
being told the command was issued.

Normalisation is on by default and matters more than it looks. Maya's
primitives do not share a UV convention - a polyCube's default layout does not
span 0..1 - so fitting raw UVs into a patch would scale each primitive kind by
a different factor. Normalising first makes the fit independent of whatever
the incoming layout was.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..dispatcher import HandlerError, refuse_inert, require_known_keys
from . import naming, units, uvmath

PROJECTIONS = ("box", "planar", "keep")

# polyAutoProjection(scaleMode=0) emits UVs proportional to WORLD SIZE rather
# than fitted to the unit square. Measured live on Maya 2027 with the scene in
# metres: a 3.0 m cube projects to a 900-unit UV bbox and a 0.5 m cube to 150 -
# exactly 6:1, i.e. 100 UV units per metre. That constant is what makes a stated
# texel density possible at all, so the live gate asserts it; if a Maya version
# or unit convention ever changes it, the gate fails loudly instead of every
# piece silently drifting to a different density.
#
# It is NOT a constant of Maya, though it was written as one. It sizes UVs from
# Maya's INTERNAL centimetres, so it tracks the scene's linear unit exactly as
# units.export_metres_per_unit does - 100.0 in an "m" scene, 1.0 in a "cm" one.
# Both measured by evals/combine_uv_live.py (maya-mcp #635). Hard-coding the
# "m" value was latent until #634 made new_scene force "cm", at which point
# every default call started producing UVs 100x too small.
AUTOPROJ_UV_PER_METRE = 100.0  # the "m"-scene value; kept for reference only


def autoproj_uv_per_metre(cmds) -> float:
    """The world-proportional UV constant for the scene as it stands now."""
    per_metre = units.units_block(cmds)["export_metres_per_unit"]
    # An unrecognised unit means we cannot know. Fall back to the historical
    # value rather than silently scaling by None - and it is the value that was
    # right for every scene before #634, so it is the safest guess available.
    return AUTOPROJ_UV_PER_METRE if per_metre is None else per_metre


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _short(name: str) -> str:
    return name.split("|")[-1]


def _require_mesh(cmds, transform: str) -> str:
    shapes = cmds.listRelatives(
        transform, shapes=True, fullPath=True, noIntermediate=True
    ) or []
    mesh = next((s for s in shapes if cmds.nodeType(s) == "mesh"), None)
    if mesh is None:
        raise HandlerError(
            "%s is not a polygon mesh" % _short(transform),
            hint="UV packing applies to meshes; curves and groups have no UVs",
        )
    return mesh


def _face_uv_loops(cmds, shape: str) -> List[List[Any]]:
    """One (u, v) polygon per face, in face-vertex order; [] for a face with
    no UVs. The API, not cmds: polyEvaluate has no per-face UV area query and
    a cmds call per face is the whole timeout on a real mesh."""
    import maya.api.OpenMaya as om  # noqa: PLC0415 - only importable inside Maya

    sel = om.MSelectionList()
    sel.add(shape)
    fn = om.MFnMesh(sel.getDagPath(0))
    loops: List[List[Any]] = []
    for face in range(fn.numPolygons):
        try:
            loops.append([fn.getPolygonUV(face, i)
                          for i in range(fn.polygonVertexCount(face))])
        except RuntimeError:
            loops.append([])
    return loops


def _planar_warnings(cmds, shape: str) -> List[str]:
    """What a planar projection did to this shape's faces (#822).

    A projection is along ONE plane, so every face edge-on to it collapses
    to zero UV area and every face on the far side of a solid lands mirrored
    over the near side. Both were silent, reported `inside_patch: true`.
    """
    stats = uvmath.face_uv_stats(_face_uv_loops(cmds, shape))
    out: List[str] = []
    if stats["zero_area"]:
        out.append(
            "%d of %d faces have zero UV area after the planar projection "
            "(they are edge-on to the projection axis); planar suits a flat "
            "sheet - use project=box for a solid"
            % (stats["zero_area"], stats["faces"]))
    if stats["mirrored"]:
        out.append(
            "%d of %d faces are mirrored after the planar projection (the far "
            "side of the mesh is stacked on the near side); use project=box "
            "for a solid" % (stats["mirrored"], stats["faces"]))
    return out


def _uv_bounds(cmds, shape: str) -> List[float]:
    # boundingBox2d, NOT boundingBoxComponent2d. The component form measures a
    # component SELECTION and returns ((0,0),(0,0)) when handed a shape, which
    # reads as "the UVs collapsed to a point" - a plausible-looking failure
    # that cost a live gate here (measured on Maya 2027: boundingBox2d gives
    # ((0,1),(0,1)) on a fresh cube, the component form gives zeros).
    bb = cmds.polyEvaluate(shape, boundingBox2d=True)
    (u0, u1), (v0, v1) = bb[0], bb[1]
    return [float(u0), float(v0), float(u1), float(v1)]


def pack_shape(
    cmds, shape: str, rect, project: str = "box", normalize: bool = True,
    world_scale=None, uv_per_metre=None,
) -> Dict[str, Any]:
    """Project and fit ONE shape's UVs into `rect`; report where they landed.

    Split out of uv_atlas so bulk builders (assemble) pack through exactly this
    code rather than a second copy of it - the world-scale arithmetic and the
    boundingBox2d trap below are the kind of thing that must have one home.
    """
    warnings: List[str] = []
    if world_scale is not None:
        # WORLD-SCALE MODE: texel density is decided by real-world size, so
        # a 3 m slab and a 0.5 m band carry the SAME pixels per metre. The
        # normalising mode below cannot do this - it makes every object fill
        # the patch, so a small band ends up magnified several times over
        # and a wall reads as a model of a wall.
        cmds.polyAutoProjection(shape, ch=False, scaleMode=0)
        # The constant is per METRE OF WORLD SIZE, and polyAutoProjection reads
        # that size in Maya's internal centimetres - so it is a property of the
        # scene's linear unit, not of Maya. Derived rather than assumed since
        # #635; an explicit uv_per_metre still wins, which is what keeps the
        # generators' explicit 1.0 authoritative.
        per_metre = (
            autoproj_uv_per_metre(cmds) if uv_per_metre is None else uv_per_metre
        )
        scale = (rect[2] - rect[0]) / (per_metre * world_scale)
        raw = _uv_bounds(cmds, shape)
        pivot_u, pivot_v, delta_u, delta_v = uvmath.centre_in_rect(raw, rect)
        cmds.polyEditUV(
            shape + ".map[*]",
            scaleU=scale, scaleV=scale, pivotU=pivot_u, pivotV=pivot_v,
        )
        cmds.polyEditUV(shape + ".map[*]", uValue=delta_u, vValue=delta_v)
    else:
        if project == "box":
            cmds.polyAutoProjection(shape, ch=False)
        elif project == "planar":
            # The axis follows the mesh: "z" was WORLD -z whatever the mesh
            # faced (#822, measured: a sheet facing X collapsed 16 of 16 faces
            # to zero UV area, reported inside_patch true), and Maya's own
            # md="b" collapsed the same sheet under a headless Maya.
            axis = uvmath.thinnest_axis(cmds.exactWorldBoundingBox(shape))
            cmds.polyProjection(shape + ".f[*]", type="Planar", ch=False, md=axis)
            warnings.extend(_planar_warnings(cmds, shape))

        if normalize:
            # normalizeType=0 is COLLECTIVE: the whole mesh becomes one 0..1
            # block, which is what a single atlas patch wants. Normalising per
            # shell would give every shell the full patch and destroy the
            # relative scale between a piece's parts.
            cmds.polyNormalizeUV(
                shape + ".map[*]", normalizeType=0, preserveAspectRatio=False,
                ch=False,
            )

        scale_u, scale_v, offset_u, offset_v = uvmath.fit_transform(rect)
        cmds.polyEditUV(
            shape + ".map[*]",
            scaleU=scale_u, scaleV=scale_v, pivotU=0.0, pivotV=0.0,
        )
        cmds.polyEditUV(shape + ".map[*]", uValue=offset_u, vValue=offset_v)

    bounds = _uv_bounds(cmds, shape)
    tol = 1e-4
    inside = (
        bounds[0] >= rect[0] - tol and bounds[1] >= rect[1] - tol
        and bounds[2] <= rect[2] + tol and bounds[3] <= rect[3] + tol
    )
    # A piece that does not fit is REPORTED, never silently clamped: its UVs
    # spill into the neighbouring patch, which reads as another material's
    # pixels on this piece.
    return {"uv_bounds": [round(q, 6) for q in bounds], "inside_patch": bool(inside),
            "warnings": warnings}


# Every top-level key uv_atlas reads. Anything else is refused rather than
# ignored (#767): an unread key does not fail, it succeeds and does something
# else - and a silently ignored packing param leaves UVs sitting in the wrong
# patch, which reads as another material's pixels rather than as an error.
UV_ATLAS_KEYS = ("names", "patch", "cols", "rows", "margin", "project",
                 "normalize", "world_scale", "uv_per_metre")
# `projection` is the unabbreviated English word for `project`, and `mode` is
# the generic word for the same three-way choice; both name PROJECTIONS above.
# `normalized` is the past participle a caller writes when they mean the
# `normalize` flag. `mesh` and `meshes` are what every neighbouring tool calls
# its subject - assign_material takes `mesh`, bake_textures takes `meshes` -
# while this one, which packs several pieces into one patch, calls it `names`.
UV_ATLAS_SYNONYMS = {"projection": "project", "mode": "project",
                     "normalized": "normalize", "meshes": "names",
                     "mesh": "names"}


def uv_atlas(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, UV_ATLAS_KEYS, "uv_atlas", UV_ATLAS_SYNONYMS)
    # Everything down to the refusals below is PURE - no Maya, no scene - and
    # it stays that way deliberately (#797): a param this branch drops must be
    # refused before the first cmds call, not after the UVs have been
    # reprojected. `cmds = _cmds()` is taken further down, right before the
    # first thing that needs it.
    names = params.get("names")
    if not isinstance(names, list) or not names:
        raise HandlerError(
            "names must be a non-empty list of meshes, got %r" % (names,)
        )

    cols = params.get("cols", 4)
    rows = params.get("rows", 4)
    margin = params.get("margin", 0.02)
    col, row = uvmath.resolve_cell(params.get("patch", 0), cols, rows)
    rect = uvmath.patch_rect(cols, rows, col, row, margin=margin)

    # RAW, so the refusal below can tell "the caller asked for keep" from
    # "the wrapper filled the key in": since #797 maya_uv_atlas defaults
    # project to None on every call.
    requested_project = params.get("project")
    project = requested_project or "box"
    if project not in PROJECTIONS:
        raise HandlerError(
            "project must be one of %s, got %r" % (", ".join(PROJECTIONS), project),
            hint="'box' suits primitives and hard-surface parts; 'keep' preserves "
                 "a layout you already authored",
        )
    # None is the wrapper's "not passed", not a value to type-check: reading it
    # with params.get("normalize", True) would leave the default unapplied
    # (None is a PRESENT key) and the isinstance check below would then refuse
    # every call the wrapper makes.
    normalize = params.get("normalize")
    if normalize is None:
        normalize = True
    if not isinstance(normalize, bool):
        raise HandlerError("normalize must be true or false, got %r" % (normalize,))

    world_scale = params.get("world_scale")
    if world_scale is not None:
        if isinstance(world_scale, bool) or not isinstance(world_scale, (int, float)):
            raise HandlerError(
                "world_scale must be a number of metres, got %r" % (world_scale,)
            )
        if float(world_scale) <= 0.0:
            raise HandlerError("world_scale must be positive, got %r" % (world_scale,))
        world_scale = float(world_scale)

    uv_per_metre = params.get("uv_per_metre")
    if uv_per_metre is not None:
        if isinstance(uv_per_metre, bool) or not isinstance(uv_per_metre, (int, float)):
            raise HandlerError(
                "uv_per_metre must be a number, got %r" % (uv_per_metre,)
            )
        if float(uv_per_metre) <= 0.0:
            raise HandlerError(
                "uv_per_metre must be positive, got %r" % (uv_per_metre,))
        uv_per_metre = float(uv_per_metre)

    # --- what this branch will not use (#797) ----------------------------
    if world_scale is not None and requested_project in ("keep", "planar"):
        # Not merely ignored - DESTRUCTIVE. pack_shape's world branch calls
        # polyAutoProjection(scaleMode=0) unconditionally, so an authored
        # layout asked to be kept is box-projected over and the call still
        # reports success.
        refuse_inert(
            "uv_atlas", "project", "with world_scale",
            "world-scale packing box-autoprojects every shape "
            "(polyAutoProjection scaleMode=0) to get UVs proportional to world "
            "size, so %r would be overwritten, not preserved" % requested_project,
            hint="drop world_scale to keep an authored layout, or drop project "
                 "- 'box' is what world mode already does",
        )
    if uv_per_metre is not None and world_scale is None:
        # uv_per_metre is the UV units polyAutoProjection(scaleMode=0) emits
        # per metre of world size, and only the world branch projects that
        # way; the normalising branch fits the mesh to the patch, where no
        # density constant is read at all.
        refuse_inert(
            "uv_atlas", "uv_per_metre", "without world_scale",
            "it scales the world-proportional projection, and without "
            "world_scale the UVs are normalised to fill the patch instead - "
            "the density then follows each mesh's size, not a constant",
            hint="pass world_scale (the metres one patch represents), or drop "
                 "uv_per_metre",
        )

    cmds = _cmds()
    targets = [naming.require_object(cmds, n) for n in names]
    shapes = [_require_mesh(cmds, t) for t in targets]

    out: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for transform, shape in zip(targets, shapes):
        packed = pack_shape(
            cmds, shape, rect, project=project, normalize=normalize,
            world_scale=world_scale, uv_per_metre=uv_per_metre,
        )
        # Per-shape findings (#822: what a planar projection collapsed or
        # mirrored) travel in the result's own warnings, named by mesh.
        warnings.extend("%s: %s" % (transform, w) for w in packed.pop("warnings", []))
        out.append({"name": transform, **packed})

    return {
        "meshes": out,
        "atlas": [cols, rows],
        "patch": [col, row],
        "patch_rect": [round(q, 6) for q in rect],
        "margin": float(margin),
        "projection": "world" if world_scale is not None else project,
        "normalized": bool(normalize) and world_scale is None,
        "world_scale": world_scale,
        # What was APPLIED, not what was asked for (#797): outside world mode
        # nothing reads a density constant, so reporting one was a stated
        # texel density for a pack that gave every mesh a different one.
        "uv_per_metre": (
            None if world_scale is None
            else (autoproj_uv_per_metre(cmds) if uv_per_metre is None
                  else uv_per_metre)
        ),
        "all_inside": all(m["inside_patch"] for m in out),
        # Documented in protocol.md's result row since M2.3 and never
        # actually sent before #797; since #822 it carries what a planar
        # projection did to each mesh's faces.
        "warnings": warnings,
    }
