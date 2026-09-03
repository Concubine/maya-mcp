"""Named texture recipes (design doc 5.4, narrowed).

The doc specifies an arbitrary NodeSpec DAG. That is deferred: it is the
largest single item in M2 and hard to test meaningfully without real usage
showing which nodes matter. A small set of validated recipes covers most
genuine need at a fraction of the surface area; the general builder lands
later, informed by which recipes people actually reach for.

Every node a recipe creates is tracked, so any failure sweeps exactly those
nodes and nothing else - the etch_text finally pattern from M1.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple

from ..dispatcher import HandlerError, refuse_inert, require_known_keys
from . import material, naming, orphans, pbr

RECIPES = ("noise_bump", "ramp_gradient", "layered_mask", "file_texture")
# Which semantic slot each recipe drives.
RECIPE_SLOT = {
    "noise_bump": "normal",
    "ramp_gradient": "color",
    "layered_mask": "color",
    "file_texture": "color",
}

# Which nested `params` keys each recipe's builder actually READS - #797
# rows 12-13. `params` is a known TOP-level key, so require_known_keys let
# every nested key through: the #767 defect one level down, where the value
# is validated by nobody and dropped by the builder. Two of the four
# recipes read nothing at all (`_ramp_gradient` and `_layered_mask` take
# the argument and never look at it), so for them any non-empty dict is
# inert - the caller asks for a scaled ramp, gets Maya's default one, and
# is told nothing.
RECIPE_PARAM_KEYS: Dict[str, tuple] = {
    "noise_bump": ("scale", "depth"),
    "ramp_gradient": (),
    "layered_mask": (),
    "file_texture": ("file_path",),
}
# What the two param-less recipes build instead, said in the caller's terms.
_PARAMLESS_WHY = {
    "ramp_gradient": "the builder wires a ramp with Maya's own defaults and "
                     "reads nothing from params",
    "layered_mask": "the builder wires a layeredTexture fed by a noise mask "
                    "and reads nothing from params",
}


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _shader_of(cmds, shape: str):
    """The shader node feeding this shape, and its type."""
    sgs = cmds.listSets(object=shape, type=1) or []
    if not sgs:
        raise HandlerError(
            "%s has no shading group" % shape,
            hint="call maya_assign_material first - a texture needs a shader "
            "to connect to",
        )
    # Query the .surfaceShader plug specifically (same idiom as
    # objinfo.py/scene.py's material lookup) rather than an unfiltered
    # cmds.listConnections(sgs[0], type=None): passing an explicit type=None
    # to real Maya's listConnections raises "RuntimeError: -t expects type
    # STRING" (verified live, Maya 2027) even though fake-cmds tolerates it.
    shaders = cmds.listConnections(sgs[0] + ".surfaceShader", source=True) or []
    if not shaders:
        raise HandlerError(
            "shading group %s has no shader" % sgs[0],
            hint="call maya_assign_material first",
        )
    shader = shaders[0]
    return shader, cmds.nodeType(shader)


def _validate_number(name: str, value: Any) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise HandlerError(
            "%s must be a number" % name, hint="got %r" % (value,)
        )
    return float(value)


def _node(cmds, tracker, node_type: str, base: str, **flags) -> str:
    """Mint a recipe node under `base`, or the first free _NNN suffix. The
    tracker records the node AND the name it wanted: after the previous
    network on the slot is swept (#812) the base name is usually free
    again, and the new node takes it back."""
    return tracker(cmds.shadingNode(
        node_type, name=naming.unique_name(cmds, base), **flags), base)


def _noise_bump(cmds, tracker, shader, attr, params) -> None:
    scale = _validate_number("scale", params.get("scale", 1.0))
    depth = _validate_number("depth", params.get("depth", 0.4))
    noise = _node(cmds, tracker, "noise", "mcpTex_noise", asTexture=True)
    bump = _node(cmds, tracker, "bump2d", "mcpTex_bump", asUtility=True)
    cmds.setAttr(noise + ".frequency", 8.0 * scale)
    cmds.setAttr(bump + ".bumpDepth", depth)
    cmds.connectAttr(noise + ".outColorR", bump + ".bumpValue", force=True)
    cmds.connectAttr(bump + ".outNormal", "%s.%s" % (shader, attr), force=True)


def _wire_color_output(cmds, node: str, shader: str, attr: str) -> None:
    """Connect `node.outColor` to `shader.attr`, using the red channel when
    `attr` is a scalar.

    A texture node's colour output is a float3 (`outColor`). Connecting
    that directly to a SCALAR attribute - `standardSurface.specularRoughness`
    is the one this toolbox's own slot table (`material.SHADER_SLOTS`)
    exposes - is refused outright by Maya: "Data types of source and
    destination are not compatible" (MEASURED live, #714 Task 6, building
    the texbake_live gate's three-different-slots fixture: ramp_gradient on
    "roughness" is exactly this case). `outColorR` is a scalar and connects
    cleanly - the same channel `texbake._bake_source_plug` already uses for
    a baked scalar/normal slot, so a baked and an unbaked scalar map read
    the same channel of their source node.
    """
    compound = bool(cmds.attributeQuery(attr, node=shader,
                                        numberOfChildren=True))
    source = node + (".outColor" if compound else ".outColorR")
    cmds.connectAttr(source, "%s.%s" % (shader, attr), force=True)


def _ramp_gradient(cmds, tracker, shader, attr, params) -> None:
    ramp = _node(cmds, tracker, "ramp", "mcpTex_ramp", asTexture=True)
    _wire_color_output(cmds, ramp, shader, attr)


def _layered_mask(cmds, tracker, shader, attr, params) -> None:
    layered = _node(cmds, tracker, "layeredTexture", "mcpTex_layered",
                    asTexture=True)
    mask = _node(cmds, tracker, "noise", "mcpTex_mask", asTexture=True)
    cmds.connectAttr(mask + ".outAlpha", layered + ".inputs[0].alpha", force=True)
    cmds.connectAttr(layered + ".outColor", "%s.%s" % (shader, attr), force=True)


def _file_texture(cmds, tracker, shader, attr, params) -> None:
    path = params.get("file_path")
    if not path:
        raise HandlerError(
            "the file_texture recipe requires file_path",
            hint="pass an absolute path to an image file",
        )
    node = _node(cmds, tracker, "file", "mcpTex_file", asTexture=True)
    cmds.setAttr(node + ".fileTextureName", str(path), type="string")
    _wire_color_output(cmds, node, shader, attr)


_BUILDERS: Dict[str, Callable] = {
    "noise_bump": _noise_bump,
    "ramp_gradient": _ramp_gradient,
    "layered_mask": _layered_mask,
    "file_texture": _file_texture,
}


# Every top-level key apply_texture_recipe reads. Anything else is refused
# rather than ignored (#767): an unread key does not fail, it succeeds and does
# something else.
APPLY_TEXTURE_RECIPE_KEYS = ("mesh", "recipe", "params", "slot")


def validate_recipe_params(recipe: str, nested: Any) -> Dict[str, Any]:
    """The nested `params` dict, checked against the recipe that will read
    it - pure, so the whole call is refused before a node exists (#797).

    None and {} are "not passed": the MCP wrapper used to send `params={}`
    on every call, so refusing an empty dict would refuse the command.
    """
    if nested is None:
        nested = {}
    if not isinstance(nested, dict):
        raise HandlerError(
            "params must be an object of recipe settings",
            hint="e.g. params={'scale': 2.0} for noise_bump; got %r"
                 % (nested,))
    if not nested:
        return {}

    allowed = RECIPE_PARAM_KEYS[recipe]
    if not allowed:
        refuse_inert(
            "apply_texture_recipe", "params",
            "for the %s recipe" % recipe, _PARAMLESS_WHY[recipe],
            hint="drop params; maya_assign_pbr wires an authored image, and "
                 "maya_bake_textures flattens what a recipe builds")
    require_known_keys(nested, allowed,
                       "apply_texture_recipe params for %s" % recipe)

    # pbr.missing_files's rule, reused rather than re-derived: absolute,
    # non-pattern paths only. A missing map is not an error in Maya - the
    # file node renders flat and the material merely looks wrong, which is
    # the failure class this project keeps paying for.
    path = nested.get("file_path")
    if isinstance(path, str) and path.strip():
        absent = pbr.missing_files([{"path": path.strip()}])
        if absent:
            raise HandlerError(
                "texture file not found: %s" % absent[0],
                hint="Maya renders a missing file as flat colour and reports "
                     "nothing. Paths are resolved on the MACHINE RUNNING "
                     "MAYA.")
    return dict(nested)


def apply_texture_recipe(params: Dict[str, Any]) -> Dict[str, Any]:
    # Ahead of _cmds(): an unknown key (#767) and a key this recipe's
    # builder never reads (#797) both need Maya for nothing, and a refusal
    # after the scene is touched is a refusal after the damage.
    require_known_keys(params, APPLY_TEXTURE_RECIPE_KEYS,
                       "apply_texture_recipe")
    recipe = params.get("recipe")
    if recipe not in RECIPES:
        raise HandlerError(
            "unknown recipe %r" % recipe,
            hint="valid recipes: %s" % ", ".join(RECIPES),
        )
    recipe_params = validate_recipe_params(recipe, params.get("params"))

    cmds = _cmds()
    mesh_long, shape = naming.require_mesh(cmds, str(params.get("mesh") or ""))
    shader, shader_type = _shader_of(cmds, shape)
    slot = params.get("slot") or RECIPE_SLOT[recipe]
    attr = material.resolve_slot(shader_type, slot)

    created: List[str] = []
    claims: List[Tuple[str, str]] = []

    def tracker(node: str, wanted: str) -> str:
        created.append(node)
        claims.append((node, wanted))
        return node

    # What the slot wears NOW - an earlier recipe's ramp / noise+bump2d /
    # layered+mask, or assign_pbr's file node and its place2dTexture two
    # hops up. Captured before the builder's force-connect replaces the
    # edge this walk follows. MEASURED (evals/recipe_orphans_probe.py, Maya
    # 2027, #812): Maya never reaps what that connection displaces - the
    # old node stays, wired only to defaultTextureList1 or
    # defaultRenderUtilityList1, and the new one is minted as
    # mcpTex_ramp_001. assign_pbr over a recipe slot already sweeps (#804);
    # this is the other direction.
    target = "%s.%s" % (shader, attr)
    stale = orphans.upstream_network(cmds, target)

    warnings: List[str] = []
    try:
        _BUILDERS[recipe](cmds, tracker, shader, attr, recipe_params)
        # Sweep what nothing real uses any more - never anything this call
        # built, and never a node something else still reads (a ramp the
        # user wired into a second shader survives, and is named).
        swept, survivors = orphans.sweep(
            cmds, [n for n in stale if n not in created])
        warnings.extend(orphans.survivor_warnings(
            survivors, "re-applying %s on %s" % (recipe, target)))
        # The swept nodes held the names the new ones were meant to have.
        for node, wanted in claims:
            if node != wanted and not cmds.objExists(wanted):
                renamed = cmds.rename(node, wanted)
                # `created` follows the rename at once: a raise on the next
                # one must still let the failure sweep find this node.
                created[:] = [renamed if n == node else n for n in created]
    except Exception:
        # zero orphans: sweep exactly what this call built, nothing else -
        # the old network is untouched by a failure, whether or not the
        # builder got as far as displacing it
        for node in reversed(created):
            if cmds.objExists(node):
                try:
                    cmds.delete(node)
                except Exception:
                    pass
        raise

    if recipe != "file_texture":
        warnings.append(
            "this recipe builds a procedural network that Maya's FBX "
            "exporter silently drops - maya_export_fbx reports it in "
            "textures.dropped_maps; maya_bake_textures converts it to a "
            "file texture that does survive")
        # The recipe's own nodes already exist by this point - a polyEvaluate
        # that RAISES (a corrupt mesh, a stale reference) is a different
        # problem from "no UVs" (texbake._uv_count draws the same
        # distinction) and must not crash a call that already succeeded.
        # Skip the warning, not the result; maya_bake_textures will still
        # refuse accurately later if UVs really are missing.
        try:
            has_uvs = bool(cmds.polyEvaluate(shape, uvcoord=True) or 0)
        except Exception:
            has_uvs = True
        if not has_uvs:
            warnings.append(
                "this mesh has no UVs, so maya_bake_textures will refuse it "
                "- maya_uv_atlas creates a layout (project='box' is enough "
                "for tiling detail)")

    return {
        "mesh": mesh_long,
        "recipe": recipe,
        "slot": slot,
        "nodes": created,
        "replaced": swept,
        "warnings": warnings,
    }
