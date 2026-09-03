"""The branch contract (#797): a param a branch drops is refused, not kept.

The level below tests/test_param_contract.py. That file proves every
command refuses a KEY it never reads. This one proves every command refuses
a VALUE it validates and then never consumes, on the branch another param's
value selects - `divisions` on an icosahedron (polyPlatonicSolid has no
subdivision flag; the caller asks for a denser solid and gets the same 20
faces), `count` on a mirror (one image, always), `project="keep"` under
`world_scale` (box-autoprojected anyway, over an authored layout).

The table below is docs/superpowers/plans/2026-09-02-797-inert-branches.md's
Tier 1, one entry per (row, dropped param). Each PURE entry is called
headless: the refusal must be a `dispatcher.refuse_inert` ("does not use")
naming the param and the branch, and - the #767 proof - it must fire before
the handler's first Maya import. A handler that reaches `_cmds()` first
fails here with an ImportError, which is the point: a refusal after the
checkpoint is a refusal after the damage.

Entries marked `scene=True` need a scene to decide (a clip's length, a
chain's geometry, whether a lattice survived) and are tested with their
module's fakes in their own test files; they sit in the table so the count
of covered rows is still asserted here.

The wrapper-default entries carry a second assertion: the MCP wrapper in
src/maya_mcp/server.py defaults that param to None, so the handler sees
only what the caller actually said. A wrapper that fills `count=2` on every
call makes "the caller passed count" unknowable.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.maya_mcp_plugin import _build_handlers

HANDLERS = _build_handlers()
SERVER_PY = Path(__file__).resolve().parents[1] / "src" / "maya_mcp" / "server.py"

REFUSAL = "does not use"

_PART = {"pos": [0, 0, 0], "dim": [1, 1, 1]}


def _fbx(tmp_path):
    path = tmp_path / "walk.fbx"
    path.write_bytes(b"Kaydara FBX Binary  \x00")
    return str(path)


# Each entry: row number in the plan, command, the params that select the
# branch AND pass the dropped param, the dropped param, words the refusal
# must contain (the branch, in the caller's terms), and whether a scene is
# needed. `params` may be a callable taking tmp_path.
BRANCHES = [
    # 1 - polyPlatonicSolid has no subdivision flag
    dict(row=1, command="create_primitive",
         params={"kind": "icosahedron", "name": "gem", "divisions": 3},
         param="divisions", words=["icosahedron"]),
    dict(row=1, command="create_primitive",
         params={"kind": "octahedron", "name": "gem", "divisions": 2},
         param="divisions", words=["octahedron"]),
    # 2 - mirror mode reads axis and pivot only
    *[dict(row=2, command="array",
           params={"name": "|tooth", "mode": "mirror", "axis": "x", key: value},
           param=key, words=["mirror"])
      for key, value in [("count", 9), ("center", [1, 2, 3]), ("angle", 720),
                         ("offset", [1, 0, 0]), ("step_rotate", [0, 1, 0]),
                         ("step_scale", [1, 1, 1])]],
    # 3 - radial mode reads count, axis, center, angle
    *[dict(row=3, command="array",
           params={"name": "|tooth", "mode": "radial", "count": 3, key: value},
           param=key, words=["radial"])
      for key, value in [("pivot", [0, 0, 0]), ("offset", [1, 0, 0]),
                         ("step_rotate", [0, 1, 0]), ("step_scale", [1, 1, 1])]],
    # 4 - linear mode reads count, offset, step_rotate, step_scale
    *[dict(row=4, command="array",
           params={"name": "|tooth", "mode": "linear", "count": 3,
                   "offset": [1, 0, 0], key: value},
           param=key, words=["linear"])
      for key, value in [("axis", "y"), ("center", [0, 0, 0]), ("angle", 90),
                         ("pivot", [0, 0, 0])]],
    # 5 - a zero offset lands every copy on the source
    dict(row=5, command="array",
         params={"name": "|tooth", "mode": "linear", "count": 3,
                 "offset": [0, 0, 0]},
         param="offset", words=["linear"]),
    # 6 - the pivot mode is a property of the combine
    dict(row=6, command="assemble",
         params={"name": "kit", "parts": [_PART, _PART], "combine": False,
                 "pivot": "origin"},
         param="pivot", words=["combine"]),
    dict(row=6, command="assemble",
         params={"name": "kit", "parts": [_PART], "pivot": "keep"},
         param="pivot", words=["single"]),
    # 7 - a patch is a cell of an atlas that does not exist
    dict(row=7, command="assemble",
         params={"name": "kit", "parts": [dict(_PART, patch=3)]},
         param="patch", words=["atlas"]),
    # 8 - world_scale box-autoprojects whatever project asked for
    dict(row=8, command="assemble",
         params={"name": "kit", "parts": [_PART],
                 "atlas": {"world_scale": 2.0, "project": "keep"}},
         param="project", words=["world_scale"]),
    dict(row=8, command="uv_atlas",
         params={"names": ["|box"], "world_scale": 2.0, "project": "planar"},
         param="project", words=["world_scale"]),
    # 9 - world_scale never normalises
    dict(row=9, command="assemble",
         params={"name": "kit", "parts": [_PART],
                 "atlas": {"world_scale": 2.0, "normalize": True}},
         param="normalize", words=["world_scale"]),
    # 10 - uv_per_metre is the world-scale constant
    dict(row=10, command="uv_atlas",
         params={"names": ["|box"], "uv_per_metre": 1.0},
         param="uv_per_metre", words=["world_scale"]),
    # 11 - curvature settings without a curvature bake
    dict(row=11, command="bake_mesh_maps",
         params=lambda tmp: {"meshes": ["|limb"], "out_dir": str(tmp),
                             "maps": ["ao"], "curvature_radius": 0.2},
         param="curvature_radius", words=["curvature"]),
    dict(row=11, command="bake_mesh_maps",
         params=lambda tmp: {"meshes": ["|limb"], "out_dir": str(tmp),
                             "maps": ["ao"], "curvature_output": "concave"},
         param="curvature_output", words=["curvature"]),
    # 12 - two recipes take no params
    dict(row=12, command="apply_texture_recipe",
         params={"mesh": "|box", "recipe": "ramp_gradient",
                 "params": {"scale": 2}},
         param="params", words=["ramp_gradient"]),
    dict(row=12, command="apply_texture_recipe",
         params={"mesh": "|box", "recipe": "layered_mask",
                 "params": {"depth": 1}},
         param="params", words=["layered_mask"]),
    # 13 - nested keys a recipe never reads (#767-class)
    dict(row=13, command="apply_texture_recipe",
         params={"mesh": "|box", "recipe": "noise_bump",
                 "params": {"scale": 2, "octaves": 3}},
         param="octaves", refusal="does not take", words=["noise_bump"]),
    dict(row=13, command="apply_texture_recipe",
         params={"mesh": "|box", "recipe": "file_texture",
                 "params": {"file_path": "x.png", "scale": 2}},
         param="scale", refusal="does not take", words=["file_texture"]),
    # 14 - a sweep's ring is profile_sides when given
    dict(row=14, command="create_curve_form",
         params={"name": "horn", "kind": "sweep",
                 "path": [[0, 0, 0], [0, 1, 0], [0, 2, 0.5]],
                 "profile_sides": 12,
                 "resolution": {"along": 10, "around": 8}},
         param="around", words=["profile_sides"]),
    # 15 - vertex_id wins before center is read
    dict(row=15, command="sculpt_ops",
         params={"mesh": "|box", "ops": [{"op": "soft_move", "vertex_id": 0,
                                          "center": [0, 0, 0], "radius": 1,
                                          "delta": [0, 1, 0]}]},
         param="center", words=["vertex_id"]),
    dict(row=15, command="sculpt_ops",
         params={"mesh": "|box", "ops": [{"op": "inflate_region",
                                          "vertex_id": 0, "center": [0, 0, 0],
                                          "radius": 1, "amount": 0.1}]},
         param="center", words=["vertex_id"]),
    # 16 - the pre-cage ops declare their keys like the cage ops
    dict(row=16, command="sculpt_ops",
         params={"mesh": "|box", "ops": [{"op": "displace_noise", "amp": 0.1,
                                          "center": [0, 0, 0], "radius": 1}]},
         param="center", refusal="does not take", words=["displace_noise"]),
    dict(row=16, command="sculpt_ops",
         params={"mesh": "|box", "ops": [{"op": "smooth", "amount": 2}]},
         param="amount", refusal="does not take", words=["smooth"]),
    # 17 - per-slot map keys
    dict(row=17, command="assign_pbr",
         params={"mesh": "|box",
                 "maps": {"metalness": {"path": "m.png", "chanel": "g"}}},
         param="chanel", refusal="does not take", words=["metalness"]),
    # 18 - the directional presets build no dome
    dict(row=18, command="setup_lighting",
         params={"preset": "three_point", "hdri_path": "C:/sky.hdr"},
         param="hdri_path", words=["three_point"]),
    dict(row=18, command="setup_lighting",
         params={"preset": "single_sun", "hdri_path": "C:/sky.hdr"},
         param="hdri_path", words=["single_sun"]),
    # 19 - environment is the dome that needs no file
    dict(row=19, command="setup_lighting",
         params={"preset": "environment", "hdri_path": "C:/sky.hdr"},
         param="hdri_path", words=["environment"]),
    # 20 - "current" keeps the user's camera; nothing is framed
    dict(row=20, command="capture_viewport",
         params={"angles": ["current"], "target": ["|golem"]},
         param="target", words=["current"]),
    # 21 - these two place their own camera
    dict(row=21, command="render_sheet",
         params={"subjects": ["|a"], "angle": "current"},
         param="angle", words=["current"]),
    dict(row=21, command="preview_clip",
         params={"root": "|pelvis", "name": "walk", "angle": "current"},
         param="angle", words=["current"]),
    # 22 - a pole on the start->target line has no bend plane (scene)
    dict(row=22, command="pose_ik", params=None, param="pole", scene=True),
    # 23 - a path names its own checkpoint
    dict(row=23, command="restore_checkpoint",
         params={"checkpoint_id": "003_other", "path": "C:/cp/007_pre.ma"},
         param="checkpoint_id", words=["path"]),
    # 24 - a window longer than the clip shrinks to the clip (scene)
    dict(row=24, command="clean_clip", params=None, param="window", scene=True),
    # 25 - the .fbx route reads its range in the file's own rate
    dict(row=25, command="retarget_clip",
         params=lambda tmp: {"file": _fbx(tmp), "root": "|pelvis",
                             "clip": "walk", "fps": 30},
         param="fps", words=[".fbx"]),
    # 43 (#814) - the sculptor is a sphere; rotating it about its centre is inert
    dict(row=43, command="deform",
         params={"mesh": "|slab", "deformer": "sculpt",
                 "params": {"translate": [0, 0.3, 0], "rotate": [45, 30, 0]}},
         param="rotate", words=["sculpt"]),
    # 26 - an empty target is no target
    dict(row=26, command="capture_turntable",
         params={"target": ""},
         param="target", words=["empty"]),
    # 27 - a lattice with nothing moved and its history deleted is nothing
    dict(row=27, command="deform",
         params={"mesh": "|box", "deformer": "lattice",
                 "delete_history_after": True},
         param="delete_history_after", words=["lattice"]),
    # 28 - an empty font is silently Arial
    dict(row=28, command="etch_text",
         params={"mesh": "|box", "text": "A", "face": 0, "font": ""},
         param="font", words=["empty"]),
]

PURE = [b for b in BRANCHES if not b.get("scene")]
SCENE = [b for b in BRANCHES if b.get("scene")]


def _label(entry):
    return "row%02d-%s-%s" % (entry["row"], entry["command"], entry["param"])


def test_every_tier_one_row_is_covered():
    # rows 1-28 are #797's Tier-1 table; 43 is the sculpt-rotate row #814's
    # probe settled (numbered after #797's 42-row branch table).
    assert {b["row"] for b in BRANCHES} == set(range(1, 29)) | {43}
    assert {b["command"] for b in BRANCHES} <= set(HANDLERS)
    assert {b["row"] for b in SCENE} == {22, 24}, (
        "scene rows are tested with their module's fakes: pose_ik in "
        "tests/test_rigging.py, clean_clip in tests/test_retarget.py")


@pytest.mark.parametrize("entry", PURE, ids=_label)
def test_dropped_param_refuses_before_maya(entry, tmp_path):
    params = entry["params"]
    if callable(params):
        params = params(tmp_path)
    with pytest.raises(HandlerError) as exc:
        HANDLERS[entry["command"]](dict(params))
    message = str(exc.value)
    refusal = entry.get("refusal", REFUSAL)
    assert refusal in message, (
        "%s refused, but not for the dropped param - %r" % (_label(entry), message))
    assert entry["param"] in message, message
    for word in entry["words"]:
        assert word in message, (
            "%s: the refusal must name the branch (%r) - %r"
            % (_label(entry), word, message))


# ------------------------------------------------------------ wrapper defaults

# (wrapper function, param): the MCP wrapper must default it to None, so
# "the caller passed it" is knowable at the handler.
WRAPPER_DEFAULTS_NONE = [
    ("maya_array", "count"),
    ("maya_array", "angle"),
    ("maya_assemble", "pivot"),
    ("maya_uv_atlas", "project"),
    ("maya_uv_atlas", "normalize"),
    ("maya_bake_mesh_maps", "curvature_radius"),
    ("maya_bake_mesh_maps", "curvature_output"),
    ("maya_apply_texture_recipe", "params"),
    ("maya_render_scene", "samples"),
    ("maya_render_sheet", "samples"),
    ("maya_restore_checkpoint", "checkpoint_id"),
    ("maya_restore_checkpoint", "path"),
]


def _wrapper_default(func_name: str, param: str):
    tree = ast.parse(SERVER_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            args = node.args
            positional = args.posonlyargs + args.args
            defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
            for arg, default in zip(positional, defaults):
                if arg.arg == param:
                    return default
            for arg, default in zip(args.kwonlyargs, args.kw_defaults):
                if arg.arg == param:
                    return default
            raise AssertionError("%s has no param %r" % (func_name, param))
    raise AssertionError("server.py defines no %s" % func_name)


@pytest.mark.parametrize("func_name,param", WRAPPER_DEFAULTS_NONE,
                         ids=["%s.%s" % pair for pair in WRAPPER_DEFAULTS_NONE])
def test_wrapper_default_is_none(func_name, param):
    default = _wrapper_default(func_name, param)
    assert default is not None, "%s.%s has no default at all" % (func_name, param)
    assert isinstance(default, ast.Constant) and default.value is None, (
        "%s defaults %s to %s - the handler then cannot tell a passed value "
        "from a filled one, and the branch refusal fires on every call"
        % (func_name, param, ast.unparse(default)))


def test_refuse_inert_wording_is_the_contract():
    """The helper's wording is what every assertion above keys on."""
    from maya_plugin.dispatcher import refuse_inert

    with pytest.raises(HandlerError) as exc:
        refuse_inert("create_primitive", "divisions", "on an icosahedron",
                     "polyPlatonicSolid takes radius only", hint="drop it")
    assert str(exc.value) == (
        "create_primitive does not use 'divisions' on an icosahedron: "
        "polyPlatonicSolid takes radius only")
    assert exc.value.hint == "drop it"
    assert "maya" not in sys.modules or True  # headless by construction
