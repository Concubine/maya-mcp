"""maya_assemble: build many parts, pack them into an atlas, merge them.

This is the single most hand-rolled loop in the codebase, now written twice:

    for each part:  primitive -> (optional taper) -> move -> uv_atlas -> collect
    then:           unite into one object per chunk

The hero delivery drove about 8,000 boxes through it inside ONE execute_python -
the tool surface was bypassed for the largest authoring job to date, so nothing
about that build was measured by anything but the script itself. That is the
gap: not that the loop is hard, but that a hand-rolled loop is invisible.

The parts list is FLAT and each part names its `chunk`, because that is the
shape a generator emits: 2,034 chunks of four or five boxes each is 8,000 rows,
and demanding a nested structure would only make the caller build one.

Nothing here reimplements the steps. Primitives come from
modeling.build_unit_primitive (one unit-box normalisation), UVs from
uvatlas.pack_shape (one copy of the world-scale arithmetic), merging from
combine.unite (one polyUnite-and-measure). This module is the loop and the
budget, and the value is that both are now on the tool surface.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..dispatcher import HandlerError
from . import combine, ledger, modeling, naming, session, uvatlas, uvmath

# A ceiling on the CALL, not on ambition: one assemble runs on Maya's main
# thread, which means the GUI is frozen for its whole duration. 8,000 boxes was
# a real delivery, so that has to fit; far past it the right answer is several
# calls, each of which can be measured and, if it goes wrong, undone on its own.
MAX_PARTS = 12_000
# Bounds the RESULT the way create_primitive does, not the input count: a
# thousand spheres at divisions=3 is a different machine from a thousand cubes.
MAX_TOTAL_FACES = 4_000_000

_FLARE_PARAMS = ("curve", "startFlareX", "startFlareZ", "endFlareX", "endFlareZ",
                 "lowBound", "highBound")


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _short(name: str) -> str:
    return name.split("|")[-1]


def _vec3(value, what: str, default=None) -> Optional[List[float]]:
    if value is None:
        return default
    if (
        not isinstance(value, (list, tuple)) or len(value) != 3
        or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                   for v in value)
    ):
        raise HandlerError(
            "%s must be a list of 3 numbers, got %r" % (what, value),
            hint="e.g. %s=[0, 1.5, 0]" % what,
        )
    return [float(v) for v in value]


def _taper(value, what: str) -> Optional[Dict[str, float]]:
    """A number is the end flare (1.0 = no change); a dict is flare attributes.

    The bare number exists because "narrower at the top" is what a caller
    actually means nine times out of ten, and spelling it startFlareX /
    startFlareZ / endFlareX / endFlareZ makes the common case look hard.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise HandlerError("%s must be a number or an object, got %r" % (what, value))
    if isinstance(value, (int, float)):
        if value <= 0:
            raise HandlerError(
                "%s must be positive, got %r" % (what, value),
                hint="it is a MULTIPLIER on the far end: 1.0 = no taper, "
                "0.6 = 60%% as wide at the top, 1.4 = flared out",
            )
        return {"endFlareX": float(value), "endFlareZ": float(value)}
    if not isinstance(value, dict):
        raise HandlerError("%s must be a number or an object, got %r" % (what, value))
    unknown = set(value) - set(_FLARE_PARAMS)
    if unknown:
        raise HandlerError(
            "%s has unknown flare params: %s" % (what, ", ".join(sorted(unknown))),
            hint="valid: %s" % ", ".join(_FLARE_PARAMS),
        )
    out = {}
    for key, val in value.items():
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            raise HandlerError("%s.%s must be a number, got %r" % (what, key, val))
        out[key] = float(val)
    return out


def validate_parts(
    parts: Any, cols: int, rows: int, default_chunk: str
) -> List[Dict[str, Any]]:
    """Resolve every part, or refuse the whole call. Pure - no Maya, no scene.

    Whole-call validation matters more here than anywhere else in this codebase:
    a build that dies on part 6,000 leaves six thousand orphans behind, and the
    scene it half-built is worth less than no scene at all.
    """
    if not isinstance(parts, list) or not parts:
        raise HandlerError(
            "parts must be a non-empty list",
            hint="each part is {pos, dim} plus optional kind, rotate, patch, "
            "taper, chunk",
        )
    if len(parts) > MAX_PARTS:
        raise HandlerError(
            "%d parts is over the %d-part ceiling for one call" % (len(parts), MAX_PARTS),
            hint="split the build - each call is one undo step and one "
            "measurement, so smaller calls also fail smaller",
        )

    resolved: List[Dict[str, Any]] = []
    total_faces = 0
    for index, part in enumerate(parts):
        where = "parts[%d]" % index
        if not isinstance(part, dict):
            raise HandlerError("%s must be an object, got %r" % (where, part))
        unknown = set(part) - {"kind", "pos", "dim", "rotate", "patch", "taper",
                               "chunk", "divisions", "name"}
        if unknown:
            raise HandlerError(
                "%s has unknown keys: %s" % (where, ", ".join(sorted(unknown))),
                hint="valid: kind, pos, dim, rotate, patch, taper, chunk, "
                "divisions, name",
            )

        kind = part.get("kind", "cube")
        if kind not in modeling.PRIMITIVE_KINDS:
            raise HandlerError(
                "%s has unknown kind %r" % (where, kind),
                hint="valid kinds: %s" % ", ".join(modeling.PRIMITIVE_KINDS),
            )
        divisions = part.get("divisions", 1)
        if not isinstance(divisions, int) or isinstance(divisions, bool) or not (
            1 <= divisions <= modeling.MAX_DIVISIONS
        ):
            raise HandlerError(
                "%s divisions must be an integer 1..%d"
                % (where, modeling.MAX_DIVISIONS)
            )
        total_faces += modeling.projected_faces(kind, divisions)
        if total_faces > MAX_TOTAL_FACES:
            raise HandlerError(
                "the parts add up to more than %d faces" % MAX_TOTAL_FACES,
                hint="`divisions` is a multiplier and costs far more on some "
                "kinds than others - a sphere multiplies it by 20 on BOTH axes",
            )

        dim = _vec3(part.get("dim"), where + ".dim")
        if dim is None:
            raise HandlerError(
                "%s needs a 'dim'" % where,
                hint="dim is the part's size in scene units - every primitive "
                "kind is built to fill a 1-unit box, so dim IS the scale",
            )
        if any(d <= 0 for d in dim):
            raise HandlerError(
                "%s.dim must be positive, got %r" % (where, dim),
                hint="a zero or negative dimension collapses or inverts the "
                "part, and an inverted one renders inside out",
            )

        chunk = part.get("chunk", default_chunk)
        if not isinstance(chunk, str) or not chunk.strip():
            raise HandlerError("%s.chunk must be a non-empty string" % where)

        resolved.append({
            "index": index,
            "kind": kind,
            "divisions": divisions,
            "pos": _vec3(part.get("pos"), where + ".pos", default=[0.0, 0.0, 0.0]),
            "dim": dim,
            "rotate": _vec3(part.get("rotate"), where + ".rotate"),
            "taper": _taper(part.get("taper"), where + ".taper"),
            "cell": uvmath.resolve_cell(part.get("patch", 0), cols, rows),
            "chunk": chunk.strip(),
            "name": part.get("name"),
        })
    return resolved


def _atlas_settings(atlas: Any) -> Optional[Dict[str, Any]]:
    """None means "do not touch UVs at all" - not every assembly is atlased."""
    if atlas is None:
        return None
    if not isinstance(atlas, dict):
        raise HandlerError(
            "atlas must be an object or null, got %r" % (atlas,),
            hint="e.g. atlas={'cols': 4, 'rows': 4, 'world_scale': 3.0}; null "
            "leaves UVs alone",
        )
    unknown = set(atlas) - {"cols", "rows", "margin", "world_scale", "project",
                            "normalize"}
    if unknown:
        raise HandlerError(
            "atlas has unknown keys: %s" % ", ".join(sorted(unknown)),
            hint="valid: cols, rows, margin, world_scale, project, normalize",
        )
    project = atlas.get("project", "box")
    if project not in uvatlas.PROJECTIONS:
        raise HandlerError(
            "atlas.project must be one of %s, got %r"
            % (", ".join(uvatlas.PROJECTIONS), project)
        )
    world_scale = atlas.get("world_scale")
    if world_scale is not None:
        if isinstance(world_scale, bool) or not isinstance(world_scale, (int, float)):
            raise HandlerError(
                "atlas.world_scale must be a number of metres, got %r" % (world_scale,)
            )
        if float(world_scale) <= 0.0:
            raise HandlerError("atlas.world_scale must be positive")
        world_scale = float(world_scale)
    return {
        "cols": int(atlas.get("cols", 4)),
        "rows": int(atlas.get("rows", 4)),
        "margin": float(atlas.get("margin", 0.02)),
        "world_scale": world_scale,
        "project": project,
        "normalize": bool(atlas.get("normalize", True)),
    }


def _apply_taper(cmds, node: str, flare: Dict[str, float], part: Dict[str, Any]) -> None:
    """Bake a flare into the geometry, leaving no deformer and no handle.

    The handle is placed and SCALED explicitly rather than trusting whatever
    size Maya gives it: flare's lowBound/highBound are in the handle's local
    space, so a handle of the wrong size tapers part of the part, or none of
    it, and looks like the parameters were ignored. Scaling by half the part's
    height makes the default -1..1 bounds span exactly the part. The flare
    values themselves are multipliers, so a uniform handle scale cancels out.
    """
    nodes = cmds.nonLinear(node, type="flare")
    deformer, handle = nodes[0], nodes[1]
    half_height = max(part["dim"][1] / 2.0, 1e-6)
    cmds.setAttr(handle + ".translateX", part["pos"][0])
    cmds.setAttr(handle + ".translateY", part["pos"][1])
    cmds.setAttr(handle + ".translateZ", part["pos"][2])
    if part["rotate"] is not None:
        for axis, value in zip("XYZ", part["rotate"]):
            cmds.setAttr(handle + ".rotate" + axis, value)
    for axis in "XYZ":
        cmds.setAttr(handle + ".scale" + axis, half_height)
    for attr, value in flare.items():
        cmds.setAttr("%s.%s" % (deformer, attr), value)
    # Bake: deleting history on a deformed mesh keeps the deformed shape. The
    # handle transform survives that and would otherwise litter the scene with
    # one orphan per tapered part.
    cmds.delete(node, constructionHistory=True)
    if cmds.objExists(handle):
        cmds.delete(handle)


def assemble(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    base = params.get("name")
    if not isinstance(base, str) or not base.strip():
        raise HandlerError(
            "missing required param 'name'",
            hint="the name for the assembled object, and the prefix for its "
            "parts; parts that set their own 'chunk' are named after that",
        )
    base = base.strip()

    atlas = _atlas_settings(params.get("atlas"))
    cols = atlas["cols"] if atlas else 4
    rows = atlas["rows"] if atlas else 4
    resolved = validate_parts(params.get("parts"), cols, rows, base)

    merge = params.get("combine", True)
    if not isinstance(merge, bool):
        raise HandlerError("combine must be true or false, got %r" % (merge,))
    pivot_mode = params.get("pivot") or "center"
    if pivot_mode not in combine.PIVOT_MODES:
        raise HandlerError(
            "pivot must be one of %s, got %r"
            % (", ".join(combine.PIVOT_MODES), pivot_mode)
        )

    explicit_pivots: Dict[str, List[float]] = {}
    raw_pivots = params.get("pivots")
    if raw_pivots is not None:
        if not isinstance(raw_pivots, dict):
            raise HandlerError(
                "pivots must be a map of chunk name to [x, y, z]",
                hint='e.g. pivots={"golem_L_upperarm": [1.25, 3.95, 0.15]}',
            )
        known = {part["chunk"] for part in resolved}
        for chunk_name, value in raw_pivots.items():
            if chunk_name not in known:
                raise HandlerError(
                    "pivots names chunk %r, which no part builds" % chunk_name,
                    hint="chunks in this call: %s" % ", ".join(sorted(known)),
                )
            # _vec3 returns None for an absent value; an explicit map has no
            # "absent" - naming a chunk and giving it nothing is a mistake.
            if value is None:
                raise HandlerError(
                    "pivots[%r] is null; a pivot is a world-space point" % chunk_name,
                    hint="e.g. [1.25, 3.95, 0.15], or drop the key to keep the "
                    "global pivot mode",
                )
            explicit_pivots[chunk_name] = _vec3(value, "pivots[%r]" % chunk_name)

    freeze = params.get("freeze", True)
    if not isinstance(freeze, bool):
        raise HandlerError("freeze must be true or false, got %r" % (freeze,))

    # ONE checkpoint for the whole run. Per-object would evict the ring many
    # times over on a real delivery and turn the safety net into a delay.
    session.auto_checkpoint("assemble")

    built: List[Tuple[str, Dict[str, Any], Dict[str, Any]]] = []
    warnings: List[str] = []
    outside_patch = 0
    for part in resolved:
        requested = part["name"] or "%s_p%04d" % (part["chunk"], part["index"])
        name = naming.unique_name(cmds, requested)
        node = modeling.build_unit_primitive(cmds, part["kind"], name,
                                             part["divisions"])
        node = (cmds.ls(node, long=True) or [node])[0]
        cmds.xform(node, scale=part["dim"])
        if part["rotate"] is not None:
            cmds.xform(node, worldSpace=True, absolute=True, rotation=part["rotate"])
        cmds.xform(node, worldSpace=True, absolute=True, translation=part["pos"])

        if part["taper"] is not None:
            _apply_taper(cmds, node, part["taper"], part)

        packed: Dict[str, Any] = {}
        if atlas is not None:
            shape = cmds.listRelatives(node, shapes=True, fullPath=True,
                                       noIntermediate=True)[0]
            col, row = part["cell"]
            rect = uvmath.patch_rect(cols, rows, col, row, margin=atlas["margin"])
            packed = uvatlas.pack_shape(
                cmds, shape, rect, project=atlas["project"],
                normalize=atlas["normalize"], world_scale=atlas["world_scale"],
            )
            if not packed["inside_patch"]:
                outside_patch += 1
        built.append((node, part, packed))

    # Group by chunk, first-seen order: the caller's ordering is meaningful
    # (a generator emits a building storey by storey) and a dict would lose it.
    chunks: List[str] = []
    members: Dict[str, List[str]] = {}
    explicit: Dict[str, bool] = {}
    for node, part, _packed in built:
        if part["chunk"] not in members:
            chunks.append(part["chunk"])
            members[part["chunk"]] = []
            explicit[part["chunk"]] = False
        members[part["chunk"]].append(node)
        explicit[part["chunk"]] |= bool(part["name"])

    objects: List[Dict[str, Any]] = []
    for chunk in chunks:
        nodes = members[chunk]
        wanted = explicit_pivots.get(chunk)
        if merge and len(nodes) > 1:
            result = combine.unite(cmds, nodes, chunk, pivot_mode, freeze)
            placed = result["pivot"]
            if wanted is not None:
                cmds.xform(result["name"], worldSpace=True, pivots=tuple(wanted))
                placed = list(wanted)
            objects.append({
                "name": result["name"], "parts": len(nodes),
                "tris": result["tris"], "verts": result["verts"],
                "faces": result["faces"], "shells": result["shells"],
                "pivot": placed, "combined": True,
            })
            warnings.extend(result["warnings"])
            ledger.record(cmds, result["name"])
        else:
            # A chunk of one is still that chunk: a caller who labelled it
            # expects an object under that name whether it took five boxes or
            # one. An explicitly named part keeps its own name - that is the
            # caller being specific, not defaulting.
            if len(nodes) == 1 and not explicit[chunk] and _short(nodes[0]) != chunk:
                nodes = [(cmds.ls(cmds.rename(nodes[0],
                                              naming.unique_name(cmds, chunk)),
                                  long=True) or [nodes[0]])[0]]
            for node in nodes:
                if wanted is not None:
                    cmds.xform(node, worldSpace=True, pivots=tuple(wanted))
                shape = cmds.listRelatives(node, shapes=True, fullPath=True,
                                           noIntermediate=True)[0]
                objects.append({
                    "name": node, "parts": 1,
                    "tris": cmds.polyEvaluate(shape, triangle=True),
                    "verts": cmds.polyEvaluate(shape, vertex=True),
                    "faces": cmds.polyEvaluate(shape, face=True),
                    "shells": cmds.polyEvaluate(shape, shell=True),
                    "pivot": list(wanted) if wanted is not None else None,
                    "combined": False,
                })
                ledger.record(cmds, node)

    if outside_patch:
        warnings.append(
            "%d of %d parts have UVs outside their patch - those pieces read "
            "the neighbouring patch's pixels, which is another material's "
            "texture. Lower world_scale, or give them a larger patch."
            % (outside_patch, len(resolved))
        )

    return {
        "objects": objects,
        "parts": len(resolved),
        "tris": sum(o["tris"] for o in objects),
        "outside_patch": outside_patch,
        "atlas": [cols, rows] if atlas else None,
        "warnings": warnings,
    }
