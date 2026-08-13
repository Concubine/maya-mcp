"""assign_material: one material per mesh, object-level (design doc 5.4).

Object-level shading groups ONLY. M1 established that per-face assignment
silently no-ops and corrupts shading groups on boolean output, which is why
modeling._do_boolean collapses to a single object-level SG - honouring that
here keeps one rule in the codebase instead of two contradictory ones.
Multi-material looks come from splitting geometry, which game engines prefer
anyway.

Does NOT auto-checkpoint: assigning a material is fully covered by
one-call-one-undo-step, and look-dev is a loop of many small tweaks -
checkpointing each would evict genuinely valuable checkpoints from the ring.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..dispatcher import HandlerError
from . import meshcheck, naming

SHADERS = ("standardSurface", "lambert", "blinn")

# Whitelisted authoring params per shader, by their REAL attribute names.
PARAM_WHITELIST = {
    "standardSurface": {
        "baseColor", "roughness", "metalness", "emission", "emissionColor",
        "specular",
    },
    "lambert": {"color", "transparency", "incandescence"},
    "blinn": {"color", "transparency", "incandescence", "eccentricity",
              "specularColor"},
}

# Real attribute name for each whitelisted param, per shader.
_ATTR = {
    "standardSurface": {
        "baseColor": "baseColor", "roughness": "specularRoughness",
        "metalness": "metalness", "emission": "emission",
        "emissionColor": "emissionColor", "specular": "specular",
    },
    "lambert": {
        "color": "color", "transparency": "transparency",
        "incandescence": "incandescence",
    },
    "blinn": {
        "color": "color", "transparency": "transparency",
        "incandescence": "incandescence", "eccentricity": "eccentricity",
        "specularColor": "specularColor",
    },
}

# Semantic slots a texture recipe can target (Task 7 consumes this).
SHADER_SLOTS = {
    "standardSurface": {
        "color": "baseColor", "roughness": "specularRoughness",
        "normal": "normalCamera",
    },
    "lambert": {"color": "color", "normal": "normalCamera"},
    "blinn": {"color": "color", "roughness": "eccentricity",
              "normal": "normalCamera"},
}

_COLOR_ATTRS = {"baseColor", "color", "emissionColor", "specularColor",
                "incandescence", "transparency"}


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def resolve_slot(shader_type: str, slot: str) -> str:
    """Semantic slot -> real attribute for this shader type.

    A slot the shader genuinely lacks is an error, never a silent no-op: a
    texture connected to nothing changes no pixels and reads as success.
    """
    slots = SHADER_SLOTS.get(shader_type)
    if slots is None:
        raise HandlerError(
            "unknown shader type %r" % shader_type,
            hint="valid shaders: %s" % ", ".join(SHADERS),
        )
    if slot not in slots:
        raise HandlerError(
            "shader %s has no %r slot" % (shader_type, slot),
            hint="slots available on %s: %s"
            % (shader_type, ", ".join(sorted(slots))),
        )
    return slots[slot]


def assign_material(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    mesh_long, shape = naming.require_mesh(cmds, str(params.get("mesh") or ""))
    shader = params.get("shader", "standardSurface")
    if shader not in SHADERS:
        raise HandlerError(
            "unknown shader %r" % shader,
            hint="valid shaders: %s" % ", ".join(SHADERS),
        )
    values = dict(params.get("params") or {})
    unknown = set(values) - PARAM_WHITELIST[shader]
    if unknown:
        raise HandlerError(
            "unknown params for %s: %s" % (shader, ", ".join(sorted(unknown))),
            hint="valid params: %s" % ", ".join(sorted(PARAM_WHITELIST[shader])),
        )

    requested = params.get("name") or (mesh_long.split("|")[-1] + "_mat")
    mat_name = naming.unique_name(cmds, str(requested))
    mat = cmds.shadingNode(shader, asShader=True, name=mat_name)
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                   name=mat_name + "SG")
    cmds.connectAttr(mat + ".outColor", sg + ".surfaceShader", force=True)
    # Force the assignment now: every mesh already belongs to some default SG
    # (initialShadingGroup / openPBR_shaderSGn) with clean object-level
    # membership, so ensure_object_shading below would read that pre-existing
    # assignment as already "healthy" and leave it alone. Assign first; call
    # ensure_object_shading only as the defensive repair check it's for.
    cmds.sets(shape, edit=True, forceElement=sg)

    for key, value in values.items():
        attr = "%s.%s" % (mat, _ATTR[shader][key])
        if _ATTR[shader][key] in _COLOR_ATTRS:
            if (
                not isinstance(value, (list, tuple)) or len(value) != 3
                or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                           for v in value)
            ):
                raise HandlerError(
                    "%s must be [r, g, b]" % key,
                    hint="got %r; colour components are 0..1" % (value,),
                )
            cmds.setAttr(attr, float(value[0]), float(value[1]), float(value[2]),
                         type="double3")
        else:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise HandlerError(
                    "%s must be a number" % key, hint="got %r" % (value,)
                )
            cmds.setAttr(attr, float(value))

    shading = meshcheck.ensure_object_shading(cmds, shape, sg)
    warnings: List[str] = []
    if shading["sg"] != sg:
        warnings.append(
            "assignment collapsed onto existing shading group %s" % shading["sg"]
        )
    return {
        "mesh": mesh_long,
        "material": mat,
        "shading_group": shading["sg"],
        "shader": shader,
        "warnings": warnings,
    }
