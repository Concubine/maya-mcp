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

from ..dispatcher import HandlerError
from . import naming, uvmath

PROJECTIONS = ("box", "planar", "keep")

# polyAutoProjection(scaleMode=0) emits UVs proportional to WORLD SIZE rather
# than fitted to the unit square. Measured live on Maya 2027 with the scene in
# metres: a 3.0 m cube projects to a 900-unit UV bbox and a 0.5 m cube to 150 -
# exactly 6:1, i.e. 100 UV units per metre. That constant is what makes a stated
# texel density possible at all, so the live gate asserts it; if a Maya version
# or unit convention ever changes it, the gate fails loudly instead of every
# piece silently drifting to a different density.
AUTOPROJ_UV_PER_METRE = 100.0


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


def _uv_bounds(cmds, shape: str) -> List[float]:
    # boundingBox2d, NOT boundingBoxComponent2d. The component form measures a
    # component SELECTION and returns ((0,0),(0,0)) when handed a shape, which
    # reads as "the UVs collapsed to a point" - a plausible-looking failure
    # that cost a live gate here (measured on Maya 2027: boundingBox2d gives
    # ((0,1),(0,1)) on a fresh cube, the component form gives zeros).
    bb = cmds.polyEvaluate(shape, boundingBox2d=True)
    (u0, u1), (v0, v1) = bb[0], bb[1]
    return [float(u0), float(v0), float(u1), float(v1)]


def uv_atlas(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()

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
    scale_u, scale_v, offset_u, offset_v = uvmath.fit_transform(rect)

    project = params.get("project") or "box"
    if project not in PROJECTIONS:
        raise HandlerError(
            "project must be one of %s, got %r" % (", ".join(PROJECTIONS), project),
            hint="'box' suits primitives and hard-surface parts; 'keep' preserves "
                 "a layout you already authored",
        )
    normalize = params.get("normalize", True)
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

    targets = [naming.require_object(cmds, n) for n in names]
    shapes = [_require_mesh(cmds, t) for t in targets]

    out: List[Dict[str, Any]] = []
    for transform, shape in zip(targets, shapes):
        if world_scale is not None:
            # WORLD-SCALE MODE: texel density is decided by real-world size, so
            # a 3 m slab and a 0.5 m band carry the SAME pixels per metre. The
            # normalising mode below cannot do this - it makes every object fill
            # the patch, so a small band ends up magnified several times over
            # and a wall reads as a model of a wall.
            cmds.polyAutoProjection(shape, ch=False, scaleMode=0)
            scale = (rect[2] - rect[0]) / (AUTOPROJ_UV_PER_METRE * world_scale)
            raw = _uv_bounds(cmds, shape)
            fits = uvmath.fits_in_rect(raw, rect, scale)
            pivot_u, pivot_v, delta_u, delta_v = uvmath.centre_in_rect(raw, rect)
            cmds.polyEditUV(
                shape + ".map[*]",
                scaleU=scale, scaleV=scale, pivotU=pivot_u, pivotV=pivot_v,
            )
            cmds.polyEditUV(shape + ".map[*]", uValue=delta_u, vValue=delta_v)
            if not fits:
                # Reported, not silently clamped: the piece is bigger than the
                # density asked of it and its UVs now spill into the neighbouring
                # patch, which reads as another material's pixels on this piece.
                pass
        else:
            if project == "box":
                cmds.polyAutoProjection(shape, ch=False)
            elif project == "planar":
                cmds.polyProjection(shape + ".f[*]", type="Planar", ch=False, md="z")

            if normalize:
                # normalizeType=0 is COLLECTIVE: the whole mesh becomes one 0..1
                # block, which is what a single atlas patch wants. Normalising per
                # shell would give every shell the full patch and destroy the
                # relative scale between a piece's parts.
                cmds.polyNormalizeUV(
                    shape + ".map[*]", normalizeType=0, preserveAspectRatio=False,
                    ch=False,
                )

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
        out.append({
            "name": transform,
            "uv_bounds": [round(q, 6) for q in bounds],
            "inside_patch": bool(inside),
        })

    return {
        "meshes": out,
        "atlas": [cols, rows],
        "patch": [col, row],
        "patch_rect": [round(q, 6) for q in rect],
        "margin": float(margin),
        "projection": "world" if world_scale is not None else project,
        "normalized": bool(normalize) and world_scale is None,
        "world_scale": world_scale,
        "all_inside": all(m["inside_patch"] for m in out),
    }
