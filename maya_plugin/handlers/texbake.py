"""maya_bake_textures: turn procedural texture networks into file textures.

#714 phase 2. Phase 1 made the loss VISIBLE - export_fbx now names every
procedural map Maya's FBX exporter drops. This is the cure: bake those
networks to real images and rewire the scene to use them, so what an agent
judged in a render is what actually ships.

The rewire is PERSISTENT on purpose. A temporary export-time bake would
ship pixels nobody ever looked at; making it a scene edit means the next
render IS the deliverable, and the builder re-judges the real artifact
before exporting. export_fbx never bakes.

Two probe measurements shape the refusals below, and neither is caution:
convertSolidTx does NOT raise on a UV-less mesh - it writes a flat, useless
image - and the FBX export never validates that a texture file exists or is
any good. Nothing downstream catches a bad bake, so this tool checks its
own work (pngprobe) and refuses what it cannot bake honestly.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from ..dispatcher import HandlerError
from . import naming, pbr, pngprobe, session, texclaim

RESOLUTIONS = (256, 512, 1024, 2048, 4096)
DEFAULT_RESOLUTION = 1024


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def validate(params: Dict[str, Any], cmds) -> Dict[str, Any]:
    """Everything checkable before a single node is touched."""
    raw = params.get("meshes")
    _meshes_hint = ("pass the mesh(es) whose materials should be baked; "
                    "maya_get_scene_graph lists what the scene contains")
    if isinstance(raw, str):
        names = [raw]
    elif raw is None:
        names = []
    elif isinstance(raw, (list, tuple)):
        names = list(raw)
    else:
        # A truthy non-iterable (meshes=5, meshes=True) must not reach
        # list(raw or []) below - that raises a bare TypeError instead of
        # this tool's own HandlerError.
        raise HandlerError("missing required param 'meshes'",
                           hint=_meshes_hint)
    if not names or not all(isinstance(n, str) and n.strip() for n in names):
        raise HandlerError("missing required param 'meshes'",
                           hint=_meshes_hint)

    shapes = []
    for name in names:
        _transform, shape = naming.require_mesh(cmds, name)
        if shape not in shapes:
            shapes.append(shape)

    out_dir = params.get("out_dir")
    if not isinstance(out_dir, str) or not out_dir.strip():
        raise HandlerError(
            "missing required param 'out_dir'",
            hint="an absolute directory the baked images are written to - "
                 "there is no default, because a guessed location is how "
                 "bake files get lost from a delivery")
    if not os.path.isabs(out_dir):
        raise HandlerError(
            "out_dir %r must be absolute" % out_dir,
            hint="a relative path resolves against Maya's working directory, "
                 "which is not where you think it is")
    if not os.path.isdir(out_dir):
        raise HandlerError(
            "out_dir %r does not exist" % out_dir,
            hint="this tool does not make directories it was not asked to "
                 "make (the export_fbx rule)")

    resolution = params.get("resolution", DEFAULT_RESOLUTION)
    if (isinstance(resolution, bool) or not isinstance(resolution, int)
            or resolution not in RESOLUTIONS):
        raise HandlerError(
            "resolution must be one of %s"
            % ", ".join(str(r) for r in RESOLUTIONS),
            hint="a bake is square; these are the sizes this tool writes")

    slots = params.get("slots")
    if slots is not None:
        if (not isinstance(slots, list)
                or not all(isinstance(s, str) for s in slots)):
            raise HandlerError("slots must be a list of slot names",
                               hint="omit it to bake every procedural slot")
        unknown = [s for s in slots if s not in pbr.SLOTS]
        if unknown:
            raise HandlerError(
                "unknown slot(s): %s" % ", ".join(unknown),
                hint="valid slots: %s" % ", ".join(sorted(pbr.SLOTS)))

    return {"meshes": shapes, "out_dir": out_dir, "resolution": resolution,
            "slots": list(slots) if slots is not None else None}


def _uv_count(cmds, shape: str) -> int:
    """Number of UV coordinates on `shape`.

    A mesh with genuinely no UV set answers 0 here with no exception -
    that is the legitimate "no UVs" case the caller turns into a refusal.
    A `polyEvaluate` call that RAISES is a different problem (a corrupt
    mesh, a stale reference) and must not be laundered into that same "no
    UVs" diagnosis - this tool must not claim a diagnosis it did not make.
    """
    try:
        return int(cmds.polyEvaluate(shape, uvcoord=True) or 0)
    except Exception as exc:  # noqa: BLE001 - re-raised below with its own message
        raise HandlerError(
            "could not determine the UV count for %s: %s" % (shape, exc),
            hint="this is not the no-UVs refusal - polyEvaluate itself "
                 "failed; inspect %s in Maya directly" % shape)


def plan_bakes(cmds, shapes: List[str],
               slots: Optional[List[str]]) -> Tuple[List[Dict[str, Any]],
                                                    List[str]]:
    """What this call would bake, and what it is skipping. Pre-mutation.

    One job per (material, attr) - NOT per mesh. MEASURED (probe P2d/P2e):
    convertSolidTx samples through UVs, not world geometry - a transform
    change AND a real vertex deformation both left the bake byte-identical
    - so a material worn by several requested meshes bakes ONCE.

    SCOPE LIMIT on that measurement: it was taken on placement-less `noise`
    networks (the recipes this toolbox authors). A network driven through a
    place2dTexture with non-default placement is NOT covered by it; such a
    job carries a warning rather than a refusal, because the bake is still
    per-material by construction and the warning is what a reviewer needs
    to re-measure if it ever matters.
    """
    for shape in shapes:
        if _uv_count(cmds, shape) == 0:
            raise HandlerError(
                "%s has no UVs - a bake samples through UV space, and Maya "
                "does NOT refuse this: convertSolidTx silently writes a "
                "flat, useless image (MEASURED, #714 probe P2c)" % shape,
                hint="maya_uv_atlas creates UVs (project='box' is enough for "
                     "tiling detail); bake after that")

    claims = texclaim.material_claims(cmds, shapes)
    jobs: List[Dict[str, Any]] = []
    warnings: List[str] = []
    # The ONE legitimate reason plan_bakes can end with an empty `jobs` and
    # still not refuse: every claim it looked at was already file-backed.
    # Tracked as its own flag rather than inferred from `warnings` being
    # non-empty - `warnings` is a generic bag that OTHER paths (placement,
    # shared-mesh) also write into, always alongside a job. Gating the
    # final refusal on that bag instead of this flag would mean a future
    # skip-with-warning path added without updating this flag gets silently
    # treated as "something happened, don't refuse" even though nothing was
    # planned. See _refuse_if_nothing_to_bake and its direct unit tests.
    skipped_file_backed = False
    seen = set()
    for claim in claims:
        slot = claim["slot"]
        if slots is not None and slot not in slots:
            continue
        if claim["classification"] == "file":
            warnings.append(
                "%s.%s is already file-backed - nothing to bake"
                % (claim["material"], claim["attr"]))
            skipped_file_backed = True
            continue
        key = (claim["material"], claim["attr"])
        if key in seen:
            continue
        seen.add(key)

        if slot not in pbr.SLOTS:
            # No real texclaim walk produces this today (SLOT_FOR_ATTR is
            # derived from the same tables as pbr.SLOTS), but a future
            # material.SHADER_SLOTS entry could. Refusing here rather than
            # defaulting to "color" matters: a scalar/normal network baked
            # as a "color" kind samples outColor where _bake_source_plug
            # needs outColorR, which is a wrong bake with no refusal at all.
            raise HandlerError(
                "%s.%s claims slot %r, which this tool has no measured "
                "wiring shape for" % (claim["material"], claim["attr"], slot),
                hint="pbr.SLOTS names every slot this tool knows how to "
                     "bake; extend it before baking a new one")
        kind = pbr.SLOTS[slot][1]
        terminals = claim["terminals"]
        if len(terminals) != 1:
            raise HandlerError(
                "%s.%s is driven by %d terminals (%s) - this tool bakes one "
                "network per slot and will not guess which to keep"
                % (claim["material"], claim["attr"], len(terminals),
                   ", ".join(t["node"] for t in terminals)),
                hint="simplify the network, or bake the slots separately")
        terminal = terminals[0]

        bump_node = None
        if kind == "normal":
            if "bump2d" not in claim["via"]:
                raise HandlerError(
                    "%s.%s is driven procedurally with no bump2d in the "
                    "chain - a tangent-space normal bake is a different "
                    "capability this tool does not have"
                    % (claim["material"], claim["attr"]),
                    hint="author the normal through a bump2d (the noise_bump "
                         "recipe does), or bake the other slots and leave "
                         "this one")
            bump_node = _bump_node_for(cmds, claim)

        if any(t["type"] == "unresolved(depth)" for t in terminals):
            raise HandlerError(
                "%s.%s's network could not be resolved (a cycle, or deeper "
                "than the walk follows) - refusing rather than baking a "
                "guess" % (claim["material"], claim["attr"]),
                hint="simplify the shading network feeding this slot")

        if _has_placement(cmds, terminal["node"]):
            warnings.append(
                "%s.%s samples through a place2dTexture - the bake is still "
                "written once per material, but #714's mesh-independence "
                "measurement covered placement-less networks only; check the "
                "result on each mesh that wears it"
                % (claim["material"], claim["attr"]))

        jobs.append({
            "material": claim["material"], "sg": claim["sg"],
            "attr": claim["attr"], "slot": slot, "kind": kind,
            "terminal_plug": _bake_source_plug(terminal, kind),
            "mesh": claim["mesh"], "meshes": list(claim["meshes"]),
            "via": list(claim["via"]), "bump_node": bump_node,
            "basename": "%s_%s_baked.png" % (claim["material"], slot),
        })
        if len(claim["meshes"]) > 1:
            warnings.append(
                "%s is worn by %d meshes (%s) - baking it changes the look "
                "of every one of them, which is the point, but it is not "
                "reversible without maya_undo"
                % (claim["material"], len(claim["meshes"]),
                   ", ".join(claim["meshes"])))

    _refuse_if_nothing_to_bake(jobs, skipped_file_backed, slots)
    return jobs, warnings


def _refuse_if_nothing_to_bake(jobs: List[Dict[str, Any]],
                               skipped_file_backed: bool,
                               slots: Optional[List[str]]) -> None:
    """The final refusal, isolated so its condition is a fact about `jobs`
    and `skipped_file_backed` ONLY - never about the shape of `warnings`,
    which other call sites are free to extend for unrelated reasons.

    A file-backed-only scene is NOT "nothing to bake": that already exits
    plan_bakes's loop with jobs=[] and skipped_file_backed=True, which is a
    legitimate no-op. Refuse only when neither fired at all.
    """
    if jobs or skipped_file_backed:
        return
    raise HandlerError(
        "no procedural texture network to bake on the requested "
        "mesh(es)%s" % (" for slot(s) %s" % ", ".join(slots)
                        if slots else ""),
        hint="maya_export_fbx's textures.dropped_maps names what a "
             "scene actually carries; a file-backed slot needs no bake")


def _bake_source_plug(terminal: Dict[str, Any], kind: str) -> str:
    """Which plug convertSolidTx samples.

    MEASURED (probe P3): `noise.outColorR` bakes directly as a usable
    scalar, so a height/scalar bake needs no intermediate node. Colour
    slots bake the terminal's outColor.
    """
    if kind in ("scalar", "normal"):
        return "%s.outColorR" % terminal["node"]
    return "%s.outColor" % terminal["node"]


def _bump_node_for(cmds, claim: Dict[str, Any]) -> Optional[str]:
    """The bump2d between the terminal and the shader, if any. The rewire
    keeps it (bumpDepth is the authored look) and only replaces what feeds
    its bumpValue."""
    sources = cmds.listConnections("%s.%s" % (claim["material"],
                                              claim["attr"]),
                                   source=True, destination=False) or []
    for node in sources:
        try:
            if cmds.nodeType(node) == "bump2d":
                return node
        except Exception:  # noqa: BLE001 - a node that cannot answer is not it
            pass
    return None


def _has_placement(cmds, node: str) -> bool:
    try:
        sources = cmds.listConnections(node, source=True, destination=False) or []
        return any(cmds.nodeType(n) == "place2dTexture" for n in sources)
    except Exception:  # noqa: BLE001 - unknown placement is reported as none
        return False


def _convert_solid_tx(cmds, source_plug: str, target: str, path: str,
                      resolution: int) -> None:
    """The bake itself, isolated so tests can drive the surrounding
    machinery without Maya.

    The delete-first/assert-after discipline is the probe's: convertSolidTx
    can return normally WITHOUT writing a file, and a fixed output name
    would then read back a previous run's image as if it were this one.
    """
    if os.path.exists(path):
        os.remove(path)
    cmds.convertSolidTx(source_plug, target, resolutionX=resolution,
                        resolutionY=resolution, fileImageName=path,
                        fileFormat="png", alpha=False)


def _verify_bake(path: str, job: Dict[str, Any]) -> Dict[str, Any]:
    """Did this bake actually sample anything? Refuses on the two measured
    ways a bake can be worthless: no file at all, and a flat image."""
    if not os.path.isfile(path):
        raise HandlerError(
            "the bake of %s.%s produced no file - convertSolidTx returned "
            "without writing %s" % (job["material"], job["attr"], path),
            hint="nothing in the scene was changed; check that the mesh has "
                 "UVs and that the texture network evaluates")
    check = pngprobe.uniformity(path)
    if check["non_uniform"] is None:
        raise HandlerError(
            "the bake of %s.%s could not be measured (%s) - refusing to "
            "rewire the scene to an image this tool cannot verify"
            % (job["material"], job["attr"], check["unavailable_reason"]),
            hint="nothing was changed; the file is at %s if you want to "
                 "look at it yourself" % path)
    if not check["non_uniform"]:
        raise HandlerError(
            "the bake of %s.%s is flat - every one of its %d pixels is the "
            "same value, which means the network sampled nothing"
            % (job["material"], job["attr"], check["pixel_count"]),
            hint="the usual cause is UV space: maya_uv_atlas gives the mesh "
                 "a layout the bake can sample through. Nothing in the scene "
                 "was changed")
    return check


def _rewire(cmds, job: Dict[str, Any], final_path: str) -> Dict[str, Any]:
    """Replace the procedural chain with a file node reading the bake.

    Per-slot shapes are the ones MEASURED to survive an FBX export:
    a colour slot takes file.outColor; a scalar takes file.outColorR with
    Raw colour space (assign_pbr's data-not-colour trap); a normal keeps
    its bump2d - bumpDepth is the authored look - and only its bumpValue
    source is replaced (probe P4 measured that path surviving export).
    """
    base = "%s_%s_baked" % (job["material"], job["slot"])
    node = cmds.shadingNode("file", asTexture=True,
                            name=naming.unique_name(cmds, base))
    cmds.setAttr(node + ".fileTextureName", final_path, type="string")
    raw = job["kind"] in ("scalar", "normal")
    if raw:
        cmds.setAttr(node + ".colorSpace", "Raw", type="string")
        # Without this, Maya's colour-management rules re-apply sRGB on
        # scene open and quietly undo the line above (the pbr precedent).
        cmds.setAttr(node + ".ignoreColorSpaceFileRules", True)

    place = cmds.shadingNode("place2dTexture", asUtility=True,
                             name=naming.unique_name(cmds, base + "_p2d"))
    for src, dst in pbr._PLACE2D_LINKS:
        try:
            cmds.connectAttr("%s.%s" % (place, src), "%s.%s" % (node, dst),
                             force=True)
        except Exception:  # noqa: BLE001 - attribute sets differ by version
            pass

    if job["kind"] == "normal" and job["bump_node"]:
        cmds.connectAttr(node + ".outAlpha",
                         job["bump_node"] + ".bumpValue", force=True)
        wired_plug = "outAlpha"
        kept = [job["bump_node"]]
    elif job["kind"] == "scalar":
        cmds.connectAttr(node + ".outColorR",
                         "%s.%s" % (job["material"], job["attr"]), force=True)
        wired_plug = "outColorR"
        kept = []
    else:
        cmds.connectAttr(node + ".outColor",
                         "%s.%s" % (job["material"], job["attr"]), force=True)
        wired_plug = "outColor"
        kept = []
    return {"file_node": node, "place": place, "wired_plug": wired_plug,
            "kept_intermediates": kept,
            "colorspace": "Raw" if raw else "sRGB"}


def _doomed_nodes(cmds, job: Dict[str, Any]) -> List[str]:
    """The replaced network's nodes, minus anything still feeding something
    else. apply_texture_recipe's zero-orphans value, inverted: delete what
    this call orphaned, never what somebody else is using."""
    terminal = job["terminal_plug"].split(".")[0]
    doomed = []
    for node in [terminal]:
        outputs = cmds.listConnections(node, source=False,
                                       destination=True) or []
        others = [o for o in outputs
                  if o != job["material"] and o not in job["via"]
                  and o != job["bump_node"]]
        if others:
            continue
        doomed.append(node)
    return doomed


def bake_textures(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    settings = validate(params, cmds)
    jobs, warnings = plan_bakes(cmds, settings["meshes"], settings["slots"])

    # --- phase A: bake and verify, mutating NOTHING -------------------
    staged: List[Dict[str, Any]] = []
    try:
        for job in jobs:
            part = os.path.join(settings["out_dir"],
                                job["basename"] + ".part.png")
            _convert_solid_tx(cmds, job["terminal_plug"], job["mesh"], part,
                              settings["resolution"])
            check = _verify_bake(part, job)
            staged.append({"job": job, "part": part, "check": check})
    except Exception:
        for entry in staged:
            try:
                os.unlink(entry["part"])
            except OSError:
                pass
        # the failing job's own part file, if it got that far
        for job in jobs:
            part = os.path.join(settings["out_dir"],
                                job["basename"] + ".part.png")
            if os.path.exists(part) and not any(e["part"] == part
                                                for e in staged):
                try:
                    os.unlink(part)
                except OSError:
                    pass
        raise

    # --- phase B: every bake verified, so commit ----------------------
    checkpoint = session.auto_checkpoint("bake_textures")
    baked = []
    for entry in staged:
        job, part = entry["job"], entry["part"]
        final_path = os.path.join(settings["out_dir"], job["basename"])
        os.replace(part, final_path)
        doomed = _doomed_nodes(cmds, job)
        wiring = _rewire(cmds, job, final_path.replace("\\", "/"))
        if doomed:
            cmds.delete(*doomed)
        baked.append({
            "material": job["material"], "slot": job["slot"],
            "attr": job["attr"], "file": final_path,
            "basename": job["basename"], "resolution": settings["resolution"],
            "colorspace": wiring["colorspace"],
            "wired_plug": wiring["wired_plug"],
            "kept_intermediates": wiring["kept_intermediates"],
            "deleted_nodes": doomed, "pixel_check": entry["check"],
        })

    # Postcondition: the slot must no longer read as procedural. A bake
    # that "succeeded" while leaving the claim procedural is a bug in this
    # tool, not a caller error - so it raises rather than warning.
    remaining = texclaim.material_claims(cmds, settings["meshes"])
    still = [c for c in remaining
             if c["classification"] == "procedural"
             and any(b["material"] == c["material"] and b["attr"] == c["attr"]
                     for b in baked)]
    if still:
        raise HandlerError(
            "POSTCONDITION FAILED: %s still reads as procedural after "
            "baking - the scene has been modified and a checkpoint (%s) "
            "was taken before the change"
            % (", ".join("%s.%s" % (c["material"], c["attr"]) for c in still),
               checkpoint["checkpoint_id"]),
            hint="maya_restore_checkpoint returns the scene; this is a bug "
                 "in maya_bake_textures, please report the network shape")

    return {
        "meshes": settings["meshes"], "out_dir": settings["out_dir"],
        "resolution": settings["resolution"], "baked": baked,
        "skipped_file_backed": [w for w in warnings
                                if "already file-backed" in w],
        "checkpoint_id": checkpoint["checkpoint_id"],
        "warnings": warnings,
    }
