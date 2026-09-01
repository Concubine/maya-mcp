"""assign_pbr: the three-map material stack, wired in one call.

The same network was hand-wired twice in one session (the Demigol kit, then the
hero buildings): standardSurface + file nodes + place2dTexture + reverse
(smoothness -> roughness) + bump2d. Every art run from here is PBR, so this was
the highest-frequency boilerplate left on the surface.

Two traps are ENCODED here rather than remembered, because both are live-only -
they cannot be found in a viewport and no mechanical check outside Maya sees
them:

  * bump2d.bumpValue is a SINGLE FLOAT. Connecting file.outColor to it is
    rejected outright. It takes outAlpha, and with bumpInterp = 1 Maya traces
    back through that connection to the file's RGB and reads it as a normal.
  * normal and mask maps are DATA, not colour. Without colorSpace = "Raw" and
    ignoreColorSpaceFileRules, Maya applies an sRGB curve: it bends the normals
    and shifts every roughness value, and the result merely looks a bit off.

The other thing this call knows is that ONE file node can drive several slots -
the kit's metalness and smoothness are two channels of one mask image, so they
must share a node and not read the same file twice.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from ..dispatcher import HandlerError, require_known_keys
from . import material, naming, orphans, plugwrite

SHADER = "standardSurface"

# slot -> (attribute, kind). kind decides how the map is wired, not what it means.
SLOTS: Dict[str, Tuple[str, str]] = {
    "color": ("baseColor", "color"),
    "emission_color": ("emissionColor", "color"),
    "metalness": ("metalness", "scalar"),
    "roughness": ("specularRoughness", "scalar"),
    "normal": ("normalCamera", "normal"),
}

# Which scalar/colour param would fight a map for the same attribute. Setting a
# value on a connected attribute is an error in Maya and a lie in the result.
_PARAM_FOR_SLOT = {
    "color": "baseColor",
    "emission_color": "emissionColor",
    "metalness": "metalness",
    "roughness": "roughness",
}

_CHANNEL_PLUG = {"r": "outColorR", "g": "outColorG", "b": "outColorB", "a": "outAlpha"}

# Data, not colour: these must be read linearly or the render is quietly wrong.
_RAW_BY_DEFAULT = {"metalness", "roughness", "normal"}

# Tokens Maya expands itself; such a path names no single file on disk, so the
# existence check has to stand down rather than reject a legitimate sequence.
_PATTERN_TOKENS = ("<udim>", "<u>", "<v>", "<f>", "<frame0", "<tile>")

# place2dTexture -> file. The full set; a partial hookup produces textures that
# ignore repeat/offset and blur wrongly at glancing angles.
_PLACE2D_LINKS = (
    ("coverage", "coverage"),
    ("translateFrame", "translateFrame"),
    ("rotateFrame", "rotateFrame"),
    ("mirrorU", "mirrorU"),
    ("mirrorV", "mirrorV"),
    ("stagger", "stagger"),
    ("wrapU", "wrapU"),
    ("wrapV", "wrapV"),
    ("repeatUV", "repeatUV"),
    ("offset", "offset"),
    ("rotateUV", "rotateUV"),
    ("noiseUV", "noiseUV"),
    ("vertexUvOne", "vertexUvOne"),
    ("vertexUvTwo", "vertexUvTwo"),
    ("vertexUvThree", "vertexUvThree"),
    ("vertexCameraOne", "vertexCameraOne"),
    ("outUV", "uvCoord"),
    ("outUvFilterSize", "uvFilterSize"),
)


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _mesh_names(params: Dict[str, Any]) -> List[str]:
    raw = params.get("mesh")
    names = [raw] if isinstance(raw, str) else list(raw or [])
    if not names or not all(isinstance(n, str) and n.strip() for n in names):
        raise HandlerError(
            "missing required param 'mesh'",
            hint="pass one mesh name, or a list of them to share one material - "
            "sharing is the point when they read from a common atlas",
        )
    return [n.strip() for n in names]


def validate_maps(maps: Any) -> List[Dict[str, Any]]:
    """Pure pass over the requested maps: every field checked, nothing built.

    Returns one resolved spec per slot, in a stable order. Pure so the whole
    call can be refused before a single node exists - the rule material.py
    already follows for scalar params.
    """
    if not isinstance(maps, dict) or not maps:
        raise HandlerError(
            "assign_pbr needs at least one entry in 'maps'",
            hint="e.g. maps={'color': 'D:/kit_albedo.png', 'normal': "
            "'D:/kit_normal.png'}; for scalars only, use maya_assign_material",
        )
    unknown = set(maps) - set(SLOTS)
    if unknown:
        raise HandlerError(
            "unknown map slots: %s" % ", ".join(sorted(unknown)),
            hint="valid slots: %s" % ", ".join(sorted(SLOTS)),
        )

    resolved = []
    for slot in sorted(maps, key=list(SLOTS).index):
        spec = maps[slot]
        if isinstance(spec, str):
            spec = {"path": spec}
        if not isinstance(spec, dict):
            raise HandlerError(
                "map %r must be a path or an object" % slot,
                hint="e.g. 'D:/mask.png' or {'path': 'D:/mask.png', "
                "'channel': 'g', 'invert': true}",
            )
        attr, kind = SLOTS[slot]
        path = spec.get("path")
        if not isinstance(path, str) or not path.strip():
            raise HandlerError(
                "map %r needs a 'path'" % slot,
                hint="pass the image file to read for this slot",
            )
        path = path.strip()

        channel = spec.get("channel")
        if channel is not None:
            if kind != "scalar":
                raise HandlerError(
                    "map %r takes no 'channel'" % slot,
                    hint="%s reads %s"
                    % (slot, "all three channels"
                       if kind == "color" else "the whole image as a normal"),
                )
            channel = str(channel).lower()
            if channel not in _CHANNEL_PLUG:
                raise HandlerError(
                    "map %r has unknown channel %r" % (slot, spec.get("channel")),
                    hint="channels: %s" % ", ".join(sorted(_CHANNEL_PLUG)),
                )
        elif kind == "scalar":
            channel = "r"

        invert = bool(spec.get("invert", False))
        if invert and kind == "normal":
            raise HandlerError(
                "map 'normal' cannot be inverted",
                hint="a flipped normal map is a texture-authoring fix, not a "
                "shading-network one - re-export the map with the green channel "
                "you want",
            )

        # Overridable, because some pipelines really do ship sRGB masks - but
        # the default per slot is the thing that is right almost every time.
        raw = spec.get("raw")
        raw = (slot in _RAW_BY_DEFAULT) if raw is None else bool(raw)

        resolved.append({
            "slot": slot, "attr": attr, "kind": kind, "path": path,
            "channel": channel, "invert": invert, "raw": raw,
            "mip_filter": bool(spec.get("mip_filter", True)),
        })
    return resolved


def missing_files(specs: List[Dict[str, Any]]) -> List[str]:
    """Absolute, non-pattern paths that do not exist.

    A missing texture is not an error in Maya: the file node renders flat and
    the material merely looks wrong, which is the failure class this project
    keeps paying for. Relative paths (workspace-resolved) and UDIM/frame
    patterns are skipped rather than guessed at.
    """
    absent = []
    for spec in specs:
        path = spec["path"]
        lowered = path.lower()
        if not os.path.isabs(path) or any(t in lowered for t in _PATTERN_TOKENS):
            continue
        if not os.path.isfile(path):
            absent.append(path)
    return absent


def _file_node(cmds, tracker, base: str, spec: Dict[str, Any],
               claims: List[Tuple[str, str]]) -> str:
    """The file node (with its place2dTexture) for one map.

    `claims` collects (node, the name it was meant to have): when this call
    is re-texturing a slot, the OLD network still holds `<mat>_<slot>_tex`
    at creation time and unique_name steps around it. Once the old nodes are
    swept the caller renames the new ones back (#804) - a look-dev loop
    should not leave `kit_color_tex_004` behind after four re-textures.
    """
    wanted = "%s_%s_tex" % (base, spec["slot"])
    node = tracker(cmds.shadingNode(
        "file", asTexture=True, name=naming.unique_name(cmds, wanted),
    ))
    claims.append((node, wanted))
    cmds.setAttr(node + ".fileTextureName", spec["path"], type="string")
    # Explicit either way: inheriting the user's filter preference makes the
    # same call produce different pixels in two sessions. 0 = Off, which is what
    # an atlas wants - mip blur bleeds neighbouring patches across every seam.
    cmds.setAttr(node + ".filterType", 1 if spec["mip_filter"] else 0)
    if spec["raw"]:
        cmds.setAttr(node + ".colorSpace", "Raw", type="string")
        # Without this, Maya's colour-management RULES re-apply sRGB on scene
        # open and quietly undo the line above.
        cmds.setAttr(node + ".ignoreColorSpaceFileRules", True)

    wanted_place = "%s_%s_p2d" % (base, spec["slot"])
    place = tracker(cmds.shadingNode(
        "place2dTexture", asUtility=True,
        name=naming.unique_name(cmds, wanted_place),
    ))
    claims.append((place, wanted_place))
    for src, dst in _PLACE2D_LINKS:
        try:
            cmds.connectAttr("%s.%s" % (place, src), "%s.%s" % (node, dst), force=True)
        except Exception:  # noqa: BLE001 - attribute sets differ across versions
            pass
    return node


def _wire(cmds, tracker, shader: str, base: str, spec: Dict[str, Any],
          node: str, claims: List[Tuple[str, str]]) -> List[str]:
    """Connect `node` into the slot. Returns the nodes the OLD wiring of that
    slot reached (captured before the force-connect replaces the edge), so
    the caller can sweep whatever nothing else uses any more (#804). The
    bump2d / reverse it makes join `claims` like the file nodes do."""
    target = "%s.%s" % (shader, spec["attr"])
    stale = orphans.upstream_network(cmds, target)
    if spec["kind"] == "normal":
        wanted = "%s_bump" % base
        bump = tracker(cmds.shadingNode(
            "bump2d", asUtility=True, name=naming.unique_name(cmds, wanted),
        ))
        claims.append((bump, wanted))
        cmds.setAttr(bump + ".bumpInterp", 1)  # 1 = tangent-space normal map
        # outAlpha, NOT outColor: bumpValue is a single float and refuses RGB.
        # bumpInterp=1 makes Maya follow this connection back to the file's
        # colour, so the alpha plug is how a normal map is delivered.
        cmds.connectAttr(node + ".outAlpha", bump + ".bumpValue", force=True)
        cmds.connectAttr(bump + ".outNormal", target, force=True)
        return stale

    if spec["kind"] == "scalar":
        source = "%s.%s" % (node, _CHANNEL_PLUG[spec["channel"]])
        if spec["invert"]:
            wanted = "%s_%s_inv" % (base, spec["slot"])
            inv = tracker(cmds.shadingNode(
                "reverse", asUtility=True, name=naming.unique_name(cmds, wanted),
            ))
            claims.append((inv, wanted))
            cmds.connectAttr(source, inv + ".inputX", force=True)
            source = inv + ".outputX"
        cmds.connectAttr(source, target, force=True)
        return stale

    source = node + ".outColor"
    if spec["invert"]:
        wanted = "%s_%s_inv" % (base, spec["slot"])
        inv = tracker(cmds.shadingNode(
            "reverse", asUtility=True, name=naming.unique_name(cmds, wanted),
        ))
        claims.append((inv, wanted))
        cmds.connectAttr(source, inv + ".input", force=True)
        source = inv + ".output"
    cmds.connectAttr(source, target, force=True)
    return stale


# Every top-level key assign_pbr reads. Anything else is refused rather than
# ignored (#767): an unread key does not fail, it succeeds and does something
# else.
ASSIGN_PBR_KEYS = ("mesh", "maps", "params", "name")
# `material` is what the RESULT calls the shader this mints, and the tool next
# door was passed it in place of `name` eleven times before anything said so.
# `textures` is the everyday word for the images in `maps`; only the slot table
# above calls them maps.
ASSIGN_PBR_SYNONYMS = {"material": "name", "textures": "maps"}


def assign_pbr(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, ASSIGN_PBR_KEYS, "assign_pbr",
                       ASSIGN_PBR_SYNONYMS)
    cmds = _cmds()
    meshes = _mesh_names(params)
    specs = validate_maps(params.get("maps"))
    values = dict(params.get("params") or {})

    clashes = sorted(
        _PARAM_FOR_SLOT[s["slot"]] for s in specs
        if _PARAM_FOR_SLOT.get(s["slot"]) in values
    )
    if clashes:
        raise HandlerError(
            "these params are also driven by a map: %s" % ", ".join(clashes),
            hint="a mapped attribute cannot carry a constant too - drop the "
            "param, or drop the map for that slot",
        )

    absent = missing_files(specs)
    if absent:
        raise HandlerError(
            "texture file(s) not found: %s" % ", ".join(absent),
            hint="a missing map is not an error in Maya - the file node renders "
            "flat and the material just looks wrong. Paths are resolved on the "
            "MACHINE RUNNING MAYA.",
        )

    # Every mesh resolved BEFORE anything is built: the second mesh used to
    # be resolved inside assign_material after the maps were wired, and a
    # typo there now reaches the failure sweep with the OLD network already
    # swept (review catch) - the one path on which a refused call could
    # leave the material bare.
    for mesh in meshes:
        naming.require_mesh(cmds, mesh)

    requested_name: Optional[str] = params.get("name")
    minted_material = not (requested_name and cmds.objExists(str(requested_name)))

    if not minted_material and values and cmds.nodeType(str(requested_name)) == SHADER:
        # #804: the clash check above sees THIS call's maps only. A material
        # reached by name carries the maps of every call before it, and a
        # scalar aimed at one of those slots would reach assign_material's
        # setAttr on a plug a file node drives - MEASURED: Maya raises
        # "locked or connected", and before this it did so AFTER the mesh had
        # been moved. Ask the scene first, with the package's one guard; a
        # slot this call is about to re-map is refused too (the map wins
        # over a constant either way, and saying so beats a raw raise).
        attr_of = material._ATTR[SHADER]  # noqa: SLF001 - the one table, next door
        # A key the whitelist does not know is assign_material's refusal to
        # make (it names the valid params); only known keys are asked about.
        plugwrite.guard(
            cmds, ["%s.%s" % (requested_name, attr_of[key])
                   for key in values if key in attr_of],
            "assign_pbr",
            consequence="nothing was written and no mesh was moved - a mapped "
                        "attribute cannot carry a constant too")

    first = material.assign_material({
        "mesh": meshes[0], "shader": SHADER, "params": values,
        "name": requested_name,
    })
    mat, sg = first["material"], first["shading_group"]
    warnings: List[str] = list(first["warnings"])

    created: List[str] = []
    claims: List[Tuple[str, str]] = []
    stale_by_slot: Dict[str, List[str]] = {}

    def tracker(node: str) -> str:
        created.append(node)
        return node

    wired: Dict[str, Dict[str, Any]] = {}
    try:
        # One file node per distinct (path, colour space, filtering): the kit's
        # metalness and smoothness are two channels of ONE mask image, and
        # reading it twice would double the texture memory for identical pixels.
        by_source: Dict[Tuple[str, bool, bool], str] = {}
        for spec in specs:
            key = (spec["path"], spec["raw"], spec["mip_filter"])
            node = by_source.get(key)
            if node is None:
                node = _file_node(cmds, tracker, mat, spec, claims)
                by_source[key] = node
            else:
                warnings.append(
                    "%s shares file node %s (same image)" % (spec["slot"], node)
                )
            stale_by_slot[spec["slot"]] = _wire(cmds, tracker, mat, mat, spec,
                                                node, claims)
            wired[spec["slot"]] = {
                "file": node, "attr": spec["attr"], "channel": spec["channel"],
                "inverted": spec["invert"], "raw": spec["raw"],
                "replaced": [],
            }

        # Re-texturing a slot: the old file node, its place2dTexture and any
        # reverse/bump2d in front of it have just lost their only consumer.
        # MEASURED (#804 probe): Maya never reaps them - the old file's one
        # remaining output is defaultTextureList1. Sweep what nothing real
        # uses any more, AFTER every slot is wired (one file node can serve
        # two slots; sweeping per slot could take it from the other), and
        # never anything this call built.
        stale = [n for old in stale_by_slot.values() for n in old
                 if n not in created]
        swept, survivors = orphans.sweep(cmds, stale)
        for slot, old in stale_by_slot.items():
            wired[slot]["replaced"] = [n for n in old if n in swept]
        warnings.extend(orphans.survivor_warnings(
            survivors, "re-texturing %s" % mat))
        # The swept nodes held the names the new ones were meant to have.
        renames: Dict[str, str] = {}
        for node, wanted in claims:
            if node.split("|")[-1] != wanted and not cmds.objExists(wanted):
                renames[node] = cmds.rename(node, wanted)
                # `created` follows each rename at once: a raise on the next
                # one must still let the failure sweep find this node.
                created[:] = [renames[node] if n == node else n for n in created]
        for entry in wired.values():
            entry["file"] = renames.get(entry["file"], entry["file"])

        assigned = [first["mesh"]]
        for extra in meshes[1:]:
            more = material.assign_material({
                "mesh": extra, "shader": SHADER, "params": {}, "name": mat,
            })
            assigned.append(more["mesh"])
    except Exception:
        # Zero orphans: sweep exactly what this call built - including the
        # material, but only when this call is what minted it.
        doomed = list(created)
        if minted_material:
            doomed.extend([sg, mat])
        for node in reversed(doomed):
            if cmds.objExists(node):
                try:
                    cmds.delete(node)
                except Exception:  # noqa: BLE001, S110 - best-effort cleanup
                    pass
        raise

    return {
        "meshes": assigned,
        "material": mat,
        "shading_group": sg,
        "shader": SHADER,
        "maps": wired,
        "nodes": created,
        "warnings": warnings,
    }
