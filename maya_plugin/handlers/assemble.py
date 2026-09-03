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

from ..dispatcher import HandlerError, refuse_inert, require_known_keys
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
    parts: Any, cols: int, rows: int, default_chunk: str, has_atlas: bool = True
) -> List[Dict[str, Any]]:
    """Resolve every part, or refuse the whole call. Pure - no Maya, no scene.

    Whole-call validation matters more here than anywhere else in this codebase:
    a build that dies on part 6,000 leaves six thousand orphans behind, and the
    scene it half-built is worth less than no scene at all.

    `has_atlas` is what says whether `patch` means anything: with no atlas
    nothing projects or packs UVs, so a patch is a cell of a grid that does
    not exist and is refused rather than resolved (#797).
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
                               "chunk", "divisions", "subdivisions", "name"}
        if unknown:
            raise HandlerError(
                "%s has unknown keys: %s" % (where, ", ".join(sorted(unknown))),
                hint="valid: kind, pos, dim, rotate, patch, taper, chunk, "
                "divisions, subdivisions, name",
            )

        kind = part.get("kind", "cube")
        if kind not in modeling.PRIMITIVE_KINDS:
            raise HandlerError(
                "%s has unknown kind %r" % (where, kind),
                hint="valid kinds: %s" % ", ".join(modeling.PRIMITIVE_KINDS),
            )
        # Same resolver as create_primitive, so a part reads the same as a
        # standalone build and neither one can drift from the other (#669).
        axes = modeling.resolve_subdivisions(kind, part, where)
        total_faces += modeling.check_face_budget(kind, axes, where)
        if total_faces > MAX_TOTAL_FACES:
            raise HandlerError(
                "the parts add up to more than %d faces" % MAX_TOTAL_FACES,
                hint="`divisions` is a multiplier and costs far more on some "
                "kinds than others - a sphere multiplies it by 20 on BOTH "
                "axes. Per-axis `subdivisions` spends faces only where the "
                "part needs them.",
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

        # A patch addresses a cell of the atlas this call packs into. With no
        # atlas there is no packing at all - and the cell was still being
        # resolved against the placeholder grid below, so an index this build
        # never had could come back "outside" a grid the caller never asked
        # for (#797).
        cell = (0, 0)
        if has_atlas:
            cell = uvmath.resolve_cell(part.get("patch", 0), cols, rows)
        elif "patch" in part:
            refuse_inert(
                "assemble", "patch", "when atlas is null",
                "%s asks for patch %r, but with atlas null this call leaves "
                "every part's UVs exactly as its primitive was built - "
                "nothing is projected and nothing is packed, so there is no "
                "grid for the cell to name" % (where, part["patch"]),
                hint="pass atlas={'cols': .., 'rows': ..} to pack the parts "
                "into one, or drop the patch",
            )

        resolved.append({
            "index": index,
            "kind": kind,
            "axes": axes,
            "pos": _vec3(part.get("pos"), where + ".pos", default=[0.0, 0.0, 0.0]),
            "dim": dim,
            "rotate": _vec3(part.get("rotate"), where + ".rotate"),
            "taper": _taper(part.get("taper"), where + ".taper"),
            "cell": cell,
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

    # What the world branch of uvatlas.pack_shape does NOT read (#797). The two
    # are keyed differently, because their defaults differ: `project` is keyed
    # on the VALUE - absent reads as None, which is neither of the two modes
    # refused - while `normalize` needs the VALUE to be non-None AND true,
    # because its default is True and a bare truthiness test therefore cannot
    # tell an explicit true from a caller who said nothing - and an explicit
    # null, which a TCP caller may send, IS saying nothing. Either way a
    # caller who said nothing is not a
    # caller who asked for the wrong thing. `project: box` and
    # `normalize: false` are exactly what world mode does, so they are
    # honoured rather than refused.
    if world_scale is not None:
        if atlas.get("project") in ("keep", "planar"):
            refuse_inert(
                "assemble", "project", "in atlas with world_scale",
                "world-scale packing calls polyAutoProjection(scaleMode=0) on "
                "every part to size its UVs by world size, so an authored "
                "%r layout is overwritten rather than kept" % atlas["project"],
                hint="drop atlas.world_scale to keep an authored layout, or "
                "drop atlas.project - 'box' is what world mode already does",
            )
        if atlas.get("normalize") is not None and bool(atlas["normalize"]):
            refuse_inert(
                "assemble", "normalize", "in atlas with world_scale",
                "normalising makes every part fill its patch, which is the "
                "opposite of a fixed texel density - the world branch never "
                "calls polyNormalizeUV, so the flag decides nothing here",
                hint="drop atlas.normalize, or drop atlas.world_scale to pack "
                "by normalising instead",
            )
    return {
        "cols": int(atlas.get("cols", 4)),
        "rows": int(atlas.get("rows", 4)),
        "margin": float(atlas.get("margin", 0.02)),
        "world_scale": world_scale,
        "project": project,
        # None is "not passed", not False. `atlas.get("normalize", True)` sees
        # a PRESENT key when a TCP caller sends an explicit null, so the True
        # default never applied and bool(None) handed pack_shape False - an
        # un-normalised pack, silently, for a caller who said nothing.
        # uvatlas.py reads its own `normalize` the same way.
        "normalize": True if atlas.get("normalize") is None
        else bool(atlas["normalize"]),
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


# Every top-level key assemble reads. Anything else is refused rather than
# ignored (#767): an unread key does not fail, it succeeds and does something
# else.
ASSEMBLE_KEYS = ("name", "parts", "atlas", "combine", "pivot", "pivots",
                 "freeze")
# `merge` is this module's own vocabulary for the flag - the docstring above
# describes the second half of the loop as merging, and the handler's own
# local variable is called `merge` - whereas the key on the wire is named
# after the neighbouring maya_combine tool that actually performs it.
ASSEMBLE_SYNONYMS = {"merge": "combine"}


def assemble(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, ASSEMBLE_KEYS, "assemble", ASSEMBLE_SYNONYMS)
    # EVERYTHING down to the checkpoint below is pure - no Maya, no scene -
    # and `cmds = _cmds()` is taken only once nothing is left to refuse. That
    # was always the intent (a whole-call validation, so a build cannot die on
    # part 6,000 and leave orphans), but the import sat at the top, which put
    # the branch refusals below the checkpoint they exist to precede (#797).
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
    resolved = validate_parts(params.get("parts"), cols, rows, base,
                              has_atlas=atlas is not None)

    merge = params.get("combine", True)
    if not isinstance(merge, bool):
        raise HandlerError("combine must be true or false, got %r" % (merge,))
    # RAW, so the refusal below can tell "the caller asked for origin" from
    # "the wrapper filled the key in": since #797 maya_assemble sends
    # pivot=None on every call it makes.
    requested_pivot = params.get("pivot")
    pivot_mode = requested_pivot or "center"
    if pivot_mode not in combine.PIVOT_MODES:
        raise HandlerError(
            "pivot must be one of %s, got %r"
            % (", ".join(combine.PIVOT_MODES), pivot_mode)
        )

    warnings: List[str] = []
    # The pivot MODE is a property of the unite: combine.unite is the only
    # caller of _place_pivot, so a chunk that never goes through it - because
    # combine is false, or because it holds one part - gets no mode applied at
    # all. `center` is the exception the plan measured: a primitive's own
    # pivot already sits at its bbox centre, so asking for `center` is
    # honoured whether or not anything writes it.
    sizes: Dict[str, int] = {}
    for part in resolved:
        sizes[part["chunk"]] = sizes.get(part["chunk"], 0) + 1
    united = [chunk for chunk, count in sizes.items() if merge and count > 1]
    loose = [chunk for chunk, count in sizes.items() if not (merge and count > 1)]
    # Hoisted, not rebuilt inside the comprehensions below: those run once per
    # part, and the delivery this module was written for is 8,000 parts over
    # 2,034 chunks.
    united_set = set(united)

    if requested_pivot in ("origin", "keep") and not united:
        if not merge:
            refuse_inert(
                "assemble", "pivot", "when combine is false",
                "the mode is applied by the unite, and with combine=false no "
                "chunk is united - every part keeps the pivot its primitive "
                "was built with, then freeze (if on) writes over the transform",
                hint="set combine=true, or name the pivots you want with "
                "`pivots` ({chunk: [x, y, z]}), which reaches loose parts too",
            )
        refuse_inert(
            "assemble", "pivot", "on a single-part chunk",
            "every chunk in this call holds one part, and a chunk of one is "
            "never united - combine.unite is what applies the mode, so the "
            "part keeps the pivot its primitive was built with",
            hint="`pivots` ({chunk: [x, y, z]}) places a pivot on a "
            "single-part chunk; 'center' is where a primitive's pivot "
            "already is",
        )
    if requested_pivot in ("origin", "keep") and loose:
        # Not refused: the multi-part chunks DO consume the mode, so refusing
        # would refuse a working call. Saying which chunks it never reached is
        # the honest half.
        shown = loose[:3]
        warnings.append(
            "pivot=%r reached %d of %d chunks: %s%s hold one part each, and a "
            "chunk of one is never united, so no pivot mode is applied to it"
            % (requested_pivot, len(united), len(sizes), ", ".join(shown),
               " (and %d more)" % (len(loose) - len(shown))
               if len(loose) > len(shown) else "")
        )

    # `name` is required by the schema, so it cannot be refused (#797 tier 2).
    # It is read in exactly one place - as the default chunk - so a build whose
    # every part names its own chunk never uses it.
    if base not in sizes:
        shown = list(sizes)[:3]
        # ...but a PART may still ask for the base name as its own, and an
        # explicitly named part in a chunk nothing unites keeps it (the rename
        # below is skipped for explicit names), so the scene would then hold a
        # node called exactly that. Only a name no surviving part claims is
        # absent from the scene - claiming otherwise would be the same
        # unmeasured-report defect this ticket removes.
        claimed = any(part["name"] == base and part["chunk"] not in united_set
                      for part in resolved)
        warnings.append(
            "no part used the base name %r: 'name' is only the DEFAULT chunk, "
            "and every part here names its own, so the objects are called "
            "after the chunks (%s%s)%s"
            % (base, ", ".join(shown),
               ", and %d more" % (len(sizes) - len(shown))
               if len(sizes) > len(shown) else "",
               "" if claimed else " and nothing is called %r" % base)
        )

    # A part's own `name` survives only as long as the part does. In a chunk
    # that gets united the transient node is built under that name and then
    # consumed by polyUnite, which names the RESULT after the chunk.
    eaten = [part["name"] for part in resolved
             if part["name"] and part["chunk"] in united_set]
    if eaten:
        shown = eaten[:3]
        warnings.append(
            "%d part name(s) are consumed by polyUnite: %s%s name nodes that "
            "exist only until their chunk is united, and the merged object is "
            "named after the chunk instead"
            % (len(eaten), ", ".join(repr(n) for n in shown),
               " (and %d more)" % (len(eaten) - len(shown))
               if len(eaten) > len(shown) else "")
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

    # Nothing above this line has touched Maya, and nothing below it can
    # refuse the call.
    cmds = _cmds()

    # ONE checkpoint for the whole run. Per-object would evict the ring many
    # times over on a real delivery and turn the safety net into a delay.
    session.auto_checkpoint("assemble")

    built: List[Tuple[str, Dict[str, Any], Dict[str, Any]]] = []
    outside_patch = 0
    for part in resolved:
        requested = part["name"] or "%s_p%04d" % (part["chunk"], part["index"])
        name = naming.unique_name(cmds, requested)
        node = modeling.build_unit_primitive(cmds, part["kind"], name,
                                             axes=part["axes"])
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
    kept_origin = 0
    for chunk in chunks:
        nodes = members[chunk]
        wanted = explicit_pivots.get(chunk)
        if merge and len(nodes) > 1:
            result = combine.unite(cmds, nodes, chunk, pivot_mode, freeze)
            if wanted is not None:
                cmds.xform(result["name"], worldSpace=True, pivots=tuple(wanted))
            # Query Maya back rather than trust either combine.unite's
            # report (a post-freeze query since #803, but taken before the
            # explicit write above) or the caller's own input: a chunk
            # always gets SOME pivot treatment here (the global mode, at
            # minimum), so this is never None for a combined object.
            placed = list(cmds.xform(result["name"], query=True,
                                     worldSpace=True, rotatePivot=True))
            objects.append({
                "name": result["name"], "parts": len(nodes),
                "tris": result["tris"], "verts": result["verts"],
                "faces": result["faces"], "shells": result["shells"],
                "pivot": placed, "combined": True,
            })
            # Every other warning combine.unite raises is about THIS chunk
            # (a stolen name, a shading-group collapse) and must be carried up
            # verbatim. The keep note is the one that is identical for every
            # united result, so 2,034 chunks would bury the per-chunk findings
            # under 2,034 copies of it; it is counted here and stated once
            # below. Matched against the constant, not by substring - a
            # substring filter would eat a future warning that happened to
            # mention the word.
            for note in result["warnings"]:
                if note == combine.KEEP_PIVOT_NOTE:
                    kept_origin += 1
                else:
                    warnings.append(note)
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
                # combine.unite is what applies the freeze, so before this a
                # chunk was frozen or not depending on how many parts happened
                # to land in it - and a caller does not choose that, their
                # generator does. A scale left on the transform is the state
                # the FBX export unit gate refuses (#629), so the same call
                # with the same flags runs here, where there is no unite.
                #
                # It precedes the pivot write below so that what is reported
                # is what the freeze left. MEASURED (#803,
                # evals/combine_pivot_probe_803.py): makeIdentity does NOT
                # move the pivot - the earlier "resets pivots to the world
                # origin" was a plan-doc sentence - so the order is a
                # convention now, not a rescue; the query-back below is what
                # keeps the report honest either way.
                if freeze:
                    cmds.makeIdentity(node, apply=True, translate=True,
                                      rotate=True, scale=True)
                placed = None
                if wanted is not None:
                    cmds.xform(node, worldSpace=True, pivots=tuple(wanted))
                if wanted is not None or freeze:
                    # Query back, not the input echoed. The freeze counts as
                    # pivot treatment even with no `wanted`: it is a write to
                    # the transform this call made, so `null` ("left alone")
                    # would be a claim about a node the call has just
                    # touched - reporting the measured pivot is the honest
                    # answer even though the freeze leaves it in place (#803).
                    # None still means untouched, which is what it has
                    # always promised.
                    placed = list(cmds.xform(node, query=True, worldSpace=True,
                                             rotatePivot=True))
                shape = cmds.listRelatives(node, shapes=True, fullPath=True,
                                           noIntermediate=True)[0]
                objects.append({
                    "name": node, "parts": 1,
                    "tris": cmds.polyEvaluate(shape, triangle=True),
                    "verts": cmds.polyEvaluate(shape, vertex=True),
                    "faces": cmds.polyEvaluate(shape, face=True),
                    "shells": cmds.polyEvaluate(shape, shell=True),
                    "pivot": placed,
                    "combined": False,
                })
                ledger.record(cmds, node)

    if kept_origin:
        warnings.append(
            "pivot='keep' on %d combined chunk(s) kept the pivot polyUnite "
            "gives a united result - the world ORIGIN (measured) - which is "
            "the same place pivot='origin' writes. Nothing of the parts' own "
            "pivots survives the unite; use 'center' for each chunk's "
            "bounding-box centre, or name the pivots with `pivots`."
            % kept_origin
        )

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
