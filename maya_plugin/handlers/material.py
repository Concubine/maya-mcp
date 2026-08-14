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

from typing import Any, Dict, List, Optional

from ..dispatcher import HandlerError
from . import meshcheck, naming

SHADERS = ("standardSurface", "lambert", "blinn")

# Whitelisted authoring params per shader, by their REAL attribute names.
PARAM_WHITELIST = {
    "standardSurface": {
        "baseColor", "roughness", "metalness", "emission", "emissionColor",
        "specular", "transmission", "transmissionColor", "transmissionDepth",
        "ior", "coat", "coatRoughness",
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
        "transmission": "transmission", "transmissionColor": "transmissionColor",
        "transmissionDepth": "transmissionDepth",
        "coat": "coat", "coatRoughness": "coatRoughness",
        "ior": "specularIOR",
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
                "incandescence", "transparency", "transmissionColor"}

# Sensible authoring ranges for params where an out-of-range value is a typo,
# not a creative choice - keyed by the whitelist name the caller passes, not
# the real attribute. ior is unbounded in Maya's own node (no hard max), but
# 1.0..3.0 covers every real dielectric a gem run needs (water 1.33, glass
# 1.5, diamond 2.42) and catches "ior=150" before it silently builds a
# black-mirror gem.
_RANGES = {
    "transmission": (0.0, 1.0),
    "ior": (1.0, 3.0),
    # Absorption distance in scene units: how far light travels through the
    # material before transmissionColor has fully tinted it. 0 disables
    # depth-based absorption, which is what makes a saturated transmissionColor
    # behave like paint (redmine #585).
    "transmissionDepth": (0.0, 100.0),
    "coat": (0.0, 1.0),
    "coatRoughness": (0.0, 1.0),
}
_RANGE_HINTS = {
    "transmission": "0 = opaque, 1 = fully transmissive",
    "ior": "water 1.33, glass 1.5, diamond 2.42",
    "transmissionDepth": "scene units light travels before transmissionColor "
    "fully tints it; roughly the object's own size for a gem",
    "coat": "0 = raw surface, 1 = full clear coat (a cut gem's polish)",
    "coatRoughness": "0 = mirror polish, 0.3 = satin",
}


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


def _validate_param_values(shader: str, values: Dict[str, Any]) -> Dict[str, tuple]:
    """Pure type-check pass: every value verified BEFORE anything is built.

    Mirrors lighting.setup_lighting's validate-everything-first shape - the
    scene must never be mutated on a call that is about to be refused.
    Returns {real_attr_name: (setAttr_args_tuple, kwargs)} ready to apply.
    """
    validated: Dict[str, tuple] = {}
    for key, value in values.items():
        attr = _ATTR[shader][key]
        if attr in _COLOR_ATTRS:
            if (
                not isinstance(value, (list, tuple)) or len(value) != 3
                or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                           for v in value)
            ):
                raise HandlerError(
                    "%s must be [r, g, b]" % key,
                    hint="got %r; colour components are 0..1" % (value,),
                )
            validated[attr] = (
                (float(value[0]), float(value[1]), float(value[2])),
                {"type": "double3"},
            )
        else:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise HandlerError(
                    "%s must be a number" % key, hint="got %r" % (value,)
                )
            bounds = _RANGES.get(key)
            if bounds is not None and not (bounds[0] <= value <= bounds[1]):
                raise HandlerError(
                    "%s must be %s..%s" % (key, bounds[0], bounds[1]),
                    hint="got %r; %s" % (value, _RANGE_HINTS[key]),
                )
            validated[attr] = ((float(value),), {})
    return validated


def _shading_group_of(cmds, mat: str) -> Optional[str]:
    """The shading group already wired to `mat`'s outColor, if any."""
    conns = cmds.listConnections(mat + ".outColor", type="shadingEngine") or []
    return conns[0] if conns else None


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

    # A `name` that already names an existing shader of the SAME type is a
    # reuse request (one material shared across meshes), not a collision to
    # uniquify - that reuse is what stops one-material-per-mesh from leaking
    # a shader per call. Existing non-shader nodes, or shaders of a different
    # type, must fail loudly rather than being silently reused as the wrong
    # thing. This is a pure read (objExists/nodeType), so it belongs with the
    # rest of the validation below, before anything is built or touched.
    explicit_name = params.get("name")
    reuse_target: Optional[str] = None
    if explicit_name and cmds.objExists(str(explicit_name)):
        existing_type = cmds.nodeType(str(explicit_name))
        if existing_type != shader:
            if existing_type not in SHADERS:
                raise HandlerError(
                    "%r already exists and is not a shader node (it is a %s)"
                    % (explicit_name, existing_type),
                    hint="pass a different name, or omit name to auto-derive one",
                )
            raise HandlerError(
                "%r is an existing %s shader, not %s"
                % (explicit_name, existing_type, shader),
                hint="use a different name, or set shader=%r to match the "
                "existing material" % existing_type,
            )
        reuse_target = str(explicit_name)

    # Everything above is validation; the type-check pass below is too - only
    # once it succeeds is it safe to create/reuse nodes or touch the mesh's
    # shading.
    validated = _validate_param_values(shader, values)

    warnings: List[str] = []
    if reuse_target is not None:
        mat = reuse_target
        sg = _shading_group_of(cmds, mat)
        if sg is None:
            # A shader that exists but was never wired to a shading group
            # (built outside assign_material) - give it one rather than fail.
            sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                           name=mat + "SG")
            cmds.connectAttr(mat + ".outColor", sg + ".surfaceShader", force=True)
        warnings.append("reused existing material %s" % mat)
    else:
        requested = explicit_name or (mesh_long.split("|")[-1] + "_mat")
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

    for attr, (args, kwargs) in validated.items():
        cmds.setAttr("%s.%s" % (mat, attr), *args, **kwargs)

    shading = meshcheck.ensure_object_shading(cmds, shape, sg)
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
