"""#775 task 3: what apply_surface_detail refuses, plans, and applies.

FakeCmds is meshmaps' fake (tests/test_meshmaps.py), copied rather than
imported so this suite does not couple to meshmaps' test internals - the
same call already made for texbake's and meshmaps' own fakes. The
listConnections/connectAttr pair is already generic over any plug
(node.attr), which is what makes it answer `shader.normalCamera` and
`bump2d`/`place2dTexture` connections correctly without any dedicated
bookkeeping: every wire this handler makes is just another entry in the
same `conns` dict.
"""

import os

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import (meshmaps, pngprobe, pngwrite, surfdetail,
                                  surfdetail_math, texture_recipes)


class FakeCmds:
    """|limb (shape |limbShape) wears limbSG -> limb_mat (standardSurface),
    baseColor unconnected (a plain white value)."""

    def __init__(self):
        self.meshes = {"|limb": "|limbShape"}
        self.types = {"limb_mat": "standardSurface"}
        self.shape_sgs = {"|limbShape": ["limbSG"]}
        self.sg_members = {"limbSG": ["|limbShape"]}
        self.conns = {"limbSG.surfaceShader": ["limb_mat.outColor"]}
        self.existing_attrs = {"limb_mat.baseColor"}
        self.attr_values = {"limb_mat.baseColor": [(1.0, 1.0, 1.0)]}
        self.connected = []
        self.deleted = []
        self.created = []
        self.checkpoints = []
        self.selection = ["|limb"]

    def ls(self, *args, **kw):
        if kw.get("selection"):
            return list(self.selection)
        name = args[0] if args else kw.get("name")
        if name in self.meshes:
            return [name]
        return [n for n in self.meshes if n.split("|")[-1] == name] or []

    def objExists(self, name):
        return (name in self.meshes or name in self.types
                or name in self.meshes.values())

    def listRelatives(self, node, shapes=False, fullPath=False, **kw):
        return [self.meshes[node]] if shapes and node in self.meshes else None

    def nodeType(self, node):
        if node in self.meshes.values():
            return "mesh"
        return self.types.get(node, "transform")

    def listSets(self, object=None, type=None):
        return list(self.shape_sgs.get(object, []))

    def sets(self, name, query=False, **kw):
        if query:
            return list(self.sg_members.get(name, []))
        raise NotImplementedError("query only")

    def listConnections(self, plug, source=False, destination=True,
                        plugs=False, **kw):
        node = plug.split(".")[0]
        has_attr = "." in plug
        if source:
            if has_attr:
                srcs = list(self.conns.get(plug) or [])
            else:
                srcs = []
                for dst, srclist in self.conns.items():
                    if dst.split(".")[0] == node:
                        srcs.extend(srclist)
            if not srcs:
                return None
            return srcs if plugs else [s.split(".")[0] for s in srcs]
        dsts = []
        for dst, srclist in self.conns.items():
            for src in srclist:
                matched = (src == plug) if has_attr else (
                    src.split(".")[0] == node)
                if matched:
                    dsts.append(dst)
                    break
        return (dsts if plugs else [d.split(".")[0] for d in dsts]) or None

    def attributeQuery(self, attr, node=None, exists=False):
        return ("%s.%s" % (node, attr)) in self.existing_attrs

    def getAttr(self, plug, **kw):
        return self.attr_values.get(plug, "")

    def shadingNode(self, node_type, name=None, **kw):
        self.types[name] = node_type
        self.created.append(name)
        return name

    def setAttr(self, plug, *values, **kw):
        self.attr_values[plug] = list(values) if len(values) > 1 else (
            values[0] if values else None)

    def connectAttr(self, src, dst, force=False):
        self.connected.append((src, dst))
        self.conns[dst] = [src]

    def delete(self, *nodes):
        for n in nodes:
            self.deleted.append(n)
            self.types.pop(n, None)
            for dst in list(self.conns):
                if dst.split(".")[0] == n:
                    del self.conns[dst]
                    continue
                self.conns[dst] = [s for s in self.conns[dst]
                                   if s.split(".")[0] != n]
                if not self.conns[dst]:
                    del self.conns[dst]

    def select(self, *args, **kw):
        if kw.get("clear"):
            self.selection = []
        elif args:
            arg = args[0]
            self.selection = list(arg) if isinstance(arg, list) else [arg]


@pytest.fixture
def fake(monkeypatch):
    cmds = FakeCmds()
    monkeypatch.setattr(surfdetail, "_cmds", lambda: cmds)
    monkeypatch.setattr(surfdetail.session, "auto_checkpoint",
                        lambda reason: (cmds.checkpoints.append(reason)
                                        or {"checkpoint_id": "cp",
                                            "path": "cp.ma"}))
    return cmds


def _varied_png(path, size=4):
    """A real, non-uniform PNG - what a real curvature/ao bake looks like."""
    pixels = [((x * 37 + y * 11) % 256,) * 3
             for y in range(size) for x in range(size)]
    pngwrite.write_png(str(path), size, size, pixels)
    return str(path)


def _flat_png(path, size=4, value=128):
    pixels = [(value, value, value)] * (size * size)
    pngwrite.write_png(str(path), size, size, pixels)
    return str(path)


def _masks(tmp_path, short="limb", size=4, curvature=True, ao=True):
    if curvature:
        _varied_png(tmp_path / ("%s_curvature.png" % short), size)
    if ao:
        _varied_png(tmp_path / ("%s_ao.png" % short), size)


def _params(tmp_path, mesh="|limb", effects=None, **kw):
    base = {"mesh": mesh, "maps_dir": str(tmp_path),
           "effects": effects if effects is not None else [{"kind": "wear"}]}
    base.update(kw)
    return base


# --------------------------------------------------------------------------
# 1-8: TestValidation
# --------------------------------------------------------------------------


class TestValidation:
    # 1: unknown top-level / per-effect key
    def test_unknown_top_level_key_refuses_naming_synonym(self, fake, tmp_path):
        params = _params(tmp_path)
        params["masks_dir"] = params.pop("maps_dir")
        with pytest.raises(HandlerError, match="masks_dir") as exc:
            surfdetail.validate(params, fake)
        assert "'maps_dir'" in (exc.value.hint or "")

    def test_unknown_effect_key_refuses_naming_synonym(self, fake, tmp_path):
        params = _params(tmp_path, effects=[
            {"kind": "wear", "colour": [0.5, 0.5, 0.5]}])
        with pytest.raises(HandlerError, match="colour") as exc:
            surfdetail.validate(params, fake)
        assert "'color'" in (exc.value.hint or "")

    # 2: effects missing/empty/non-list, unknown kind, repeated kind
    def test_effects_missing_refuses(self, fake, tmp_path):
        params = _params(tmp_path)
        del params["effects"]
        with pytest.raises(HandlerError, match="effects"):
            surfdetail.validate(params, fake)

    def test_effects_empty_refuses(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="effects"):
            surfdetail.validate(_params(tmp_path, effects=[]), fake)

    def test_effects_non_list_refuses(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="effects"):
            surfdetail.validate(_params(tmp_path, effects="wear"), fake)

    def test_unknown_kind_refuses(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="kind"):
            surfdetail.validate(_params(tmp_path, effects=[{"kind": "rust"}]),
                                fake)

    def test_repeated_kind_refuses(self, fake, tmp_path):
        params = _params(tmp_path, effects=[{"kind": "wear"},
                                            {"kind": "wear"}])
        with pytest.raises(HandlerError, match="repeats"):
            surfdetail.validate(params, fake)

    # 3: strength/scale ranges + defaults
    def test_strength_zero_refuses(self, fake, tmp_path):
        params = _params(tmp_path, effects=[{"kind": "wear", "strength": 0}])
        with pytest.raises(HandlerError, match="strength"):
            surfdetail.validate(params, fake)

    def test_strength_above_max_refuses(self, fake, tmp_path):
        params = _params(tmp_path,
                         effects=[{"kind": "wear", "strength": 4.5}])
        with pytest.raises(HandlerError, match="strength"):
            surfdetail.validate(params, fake)

    def test_strength_non_numeric_refuses(self, fake, tmp_path):
        params = _params(tmp_path,
                         effects=[{"kind": "wear", "strength": "lots"}])
        with pytest.raises(HandlerError, match="strength"):
            surfdetail.validate(params, fake)

    def test_strength_bool_refuses(self, fake, tmp_path):
        params = _params(tmp_path,
                         effects=[{"kind": "wear", "strength": True}])
        with pytest.raises(HandlerError, match="strength"):
            surfdetail.validate(params, fake)

    def test_scale_zero_refuses(self, fake, tmp_path):
        params = _params(tmp_path, effects=[{"kind": "wear", "scale": 0}])
        with pytest.raises(HandlerError, match="scale"):
            surfdetail.validate(params, fake)

    def test_scale_above_max_refuses(self, fake, tmp_path):
        params = _params(tmp_path, effects=[{"kind": "wear", "scale": 17}])
        with pytest.raises(HandlerError, match="scale"):
            surfdetail.validate(params, fake)

    def test_defaults_strength_and_scale(self, fake, tmp_path):
        # 2.0, not the original 0.5: #775 task 6's look probe measured the
        # old defaults as sub-visible in a render (six 8-bit levels across
        # the whole composite), and a caller who cannot see must get detail
        # that reads from the default.
        out = surfdetail.validate(_params(tmp_path, effects=[{"kind": "wear"}]),
                                  fake)
        assert out["effects"][0]["strength"] == 2.0
        assert out["effects"][0]["scale"] == 1.0

    def test_grime_and_grain_defaults(self, fake, tmp_path):
        grime = surfdetail.validate(
            _params(tmp_path, effects=[{"kind": "grime"}]), fake)
        assert grime["effects"][0]["strength"] == 1.5
        grain = surfdetail.validate(
            _params(tmp_path, effects=[{"kind": "grain"}]), fake)
        assert grain["effects"][0]["strength"] == 2.0

    def test_default_seed_is_zero(self, fake, tmp_path):
        out = surfdetail.validate(_params(tmp_path), fake)
        assert out["seed"] == 0

    # 4: color validation
    def test_color_out_of_range_refuses(self, fake, tmp_path):
        params = _params(tmp_path,
                         effects=[{"kind": "wear", "color": [2.0, 0, 0]}])
        with pytest.raises(HandlerError, match="color"):
            surfdetail.validate(params, fake)

    def test_color_wrong_length_refuses(self, fake, tmp_path):
        params = _params(tmp_path,
                         effects=[{"kind": "wear", "color": [0.1, 0.2]}])
        with pytest.raises(HandlerError, match="color"):
            surfdetail.validate(params, fake)

    def test_color_non_numeric_refuses(self, fake, tmp_path):
        params = _params(tmp_path, effects=[
            {"kind": "wear", "color": ["a", "b", "c"]}])
        with pytest.raises(HandlerError, match="color"):
            surfdetail.validate(params, fake)

    def test_color_defaults_to_measured_wear_color(self, fake, tmp_path):
        out = surfdetail.validate(_params(tmp_path, effects=[{"kind": "wear"}]),
                                  fake)
        assert out["effects"][0]["color"] == list(
            surfdetail_math.DEFAULT_WEAR_COLOR)

    def test_color_defaults_to_measured_grime_color(self, fake, tmp_path):
        out = surfdetail.validate(
            _params(tmp_path, effects=[{"kind": "grime"}]), fake)
        assert out["effects"][0]["color"] == list(
            surfdetail_math.DEFAULT_GRIME_COLOR)

    def test_color_is_stored_linear_not_reencoded(self, fake, tmp_path):
        out = surfdetail.validate(_params(tmp_path, effects=[
            {"kind": "wear", "color": [0.2, 0.2, 0.2]}]), fake)
        assert out["effects"][0]["color"] == [0.2, 0.2, 0.2]

    # F1 (#775 fix wave): grain writes a HEIGHT map - a `color` on it was
    # silently accepted and dropped by _validate_color before this fix.
    def test_grain_with_color_refuses(self, fake, tmp_path):
        params = _params(tmp_path, effects=[
            {"kind": "grain", "color": [0.1, 0.1, 0.1]}])
        with pytest.raises(HandlerError, match="grain") as exc:
            surfdetail.validate(params, fake)
        # names the actual problem (no colour to tint) and redirects the
        # caller, rather than a bare "invalid" - this assertion fails if
        # the refusal is ever swapped back for silent acceptance.
        assert "HEIGHT map" in (exc.value.hint or "")
        assert "wear" in (exc.value.hint or "")
        assert "grime" in (exc.value.hint or "")

    # 5: maps_dir / out_dir
    def test_maps_dir_required(self, fake, tmp_path):
        params = _params(tmp_path)
        del params["maps_dir"]
        with pytest.raises(HandlerError, match="maps_dir"):
            surfdetail.validate(params, fake)

    def test_maps_dir_must_be_absolute(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="absolute"):
            surfdetail.validate(_params(tmp_path, maps_dir="rel/dir"), fake)

    def test_maps_dir_must_exist(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="does not exist"):
            surfdetail.validate(
                _params(tmp_path, maps_dir=str(tmp_path / "nope")), fake)

    def test_out_dir_defaults_to_maps_dir(self, fake, tmp_path):
        out = surfdetail.validate(_params(tmp_path), fake)
        assert out["out_dir"] == str(tmp_path)

    def test_out_dir_given_must_be_absolute(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="absolute"):
            surfdetail.validate(_params(tmp_path, out_dir="rel"), fake)

    def test_out_dir_given_must_exist(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="does not exist"):
            surfdetail.validate(
                _params(tmp_path, out_dir=str(tmp_path / "nope")), fake)

    # 6: mask file resolution (missing)
    def test_missing_curvature_mask_refuses_naming_path(self, tmp_path):
        mesh = ("|limb", "|limbShape")
        effects = [{"kind": "wear", "strength": 0.5, "scale": 1.0,
                   "color": [0, 0, 0]}]
        with pytest.raises(HandlerError) as exc:
            surfdetail._resolve_masks(mesh, effects, str(tmp_path), None)
        assert str(tmp_path / "limb_curvature.png") in str(exc.value)
        assert "maya_bake_mesh_maps" in (exc.value.hint or "")

    def test_missing_ao_mask_for_grime_refuses(self, tmp_path):
        mesh = ("|limb", "|limbShape")
        effects = [{"kind": "grime", "strength": 0.5, "scale": 1.0,
                   "color": [0, 0, 0]}]
        with pytest.raises(HandlerError) as exc:
            surfdetail._resolve_masks(mesh, effects, str(tmp_path), None)
        assert str(tmp_path / "limb_ao.png") in str(exc.value)

    def test_grain_needs_both_masks(self, tmp_path):
        _varied_png(tmp_path / "limb_curvature.png")
        mesh = ("|limb", "|limbShape")
        effects = [{"kind": "grain", "strength": 0.3, "scale": 1.0,
                   "color": None}]
        with pytest.raises(HandlerError) as exc:
            surfdetail._resolve_masks(mesh, effects, str(tmp_path), None)
        assert str(tmp_path / "limb_ao.png") in str(exc.value)

    # 7: flat / unmeasurable
    def test_flat_mask_refuses_naming_distinct_values(self, tmp_path):
        _flat_png(tmp_path / "limb_curvature.png")
        mesh = ("|limb", "|limbShape")
        effects = [{"kind": "wear", "strength": 0.5, "scale": 1.0,
                   "color": [0, 0, 0]}]
        with pytest.raises(HandlerError, match="distinct_values") as exc:
            surfdetail._resolve_masks(mesh, effects, str(tmp_path), None)
        assert "flat" in str(exc.value)

    def test_unmeasurable_mask_refuses(self, tmp_path):
        (tmp_path / "limb_curvature.png").write_bytes(b"not a png")
        mesh = ("|limb", "|limbShape")
        effects = [{"kind": "wear", "strength": 0.5, "scale": 1.0,
                   "color": [0, 0, 0]}]
        with pytest.raises(HandlerError, match="could not be measured"):
            surfdetail._resolve_masks(mesh, effects, str(tmp_path), None)

    # 8: resolution
    def test_resolution_must_be_in_texbake_resolutions(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="resolution"):
            surfdetail.validate(_params(tmp_path, resolution=999), fake)

    def test_resolution_defaults_to_mask_width(self, tmp_path):
        _varied_png(tmp_path / "limb_curvature.png", size=4)
        mesh = ("|limb", "|limbShape")
        effects = [{"kind": "wear", "strength": 0.5, "scale": 1.0,
                   "color": [0, 0, 0]}]
        _masks_out, res = surfdetail._resolve_masks(mesh, effects,
                                                     str(tmp_path), None)
        assert res == 4

    def test_grain_masks_disagreeing_size_refuses(self, tmp_path):
        _varied_png(tmp_path / "limb_curvature.png", size=4)
        _varied_png(tmp_path / "limb_ao.png", size=8)
        mesh = ("|limb", "|limbShape")
        effects = [{"kind": "grain", "strength": 0.3, "scale": 1.0,
                   "color": None}]
        with pytest.raises(HandlerError, match="disagree"):
            surfdetail._resolve_masks(mesh, effects, str(tmp_path), None)

    def test_explicit_resolution_skips_the_grain_size_check(self, tmp_path):
        _varied_png(tmp_path / "limb_curvature.png", size=4)
        _varied_png(tmp_path / "limb_ao.png", size=8)
        mesh = ("|limb", "|limbShape")
        effects = [{"kind": "grain", "strength": 0.3, "scale": 1.0,
                   "color": None}]
        _masks_out, res = surfdetail._resolve_masks(mesh, effects,
                                                     str(tmp_path), 1024)
        assert res == 1024


# --------------------------------------------------------------------------
# 9-10: TestPlanning
# --------------------------------------------------------------------------


class TestPlanning:
    def test_color_effect_routes_through_plan_apply(self, fake, tmp_path,
                                                     monkeypatch):
        _masks(tmp_path)
        calls = []
        real = meshmaps.plan_apply

        def _spy(cmds, meshes):
            calls.append(meshes)
            return real(cmds, meshes)
        monkeypatch.setattr(meshmaps, "plan_apply", _spy)
        surfdetail.apply_surface_detail(_params(tmp_path))
        assert calls == [[("|limb", "|limbShape")]]

    def test_procedural_base_refuses_naming_bake_textures(self, fake,
                                                           tmp_path):
        _masks(tmp_path)
        fake.types["mcpTex_noise"] = "noise"
        fake.conns["limb_mat.baseColor"] = ["mcpTex_noise.outColor"]
        with pytest.raises(HandlerError, match="procedural") as exc:
            surfdetail.apply_surface_detail(_params(tmp_path))
        assert "maya_bake_textures" in (exc.value.hint or "")
        assert fake.checkpoints == []  # refused before any mutation

    def test_a_wearer_outside_the_request_refuses(self, fake, tmp_path):
        _masks(tmp_path)
        fake.meshes["|other"] = "|otherShape"
        fake.sg_members["limbSG"] = ["|limbShape", "|otherShape"]
        with pytest.raises(HandlerError, match="otherShape"):
            surfdetail.apply_surface_detail(_params(tmp_path))
        assert fake.checkpoints == []

    def test_grain_only_skips_plan_apply(self, fake, tmp_path, monkeypatch):
        _masks(tmp_path)

        def _boom(cmds, meshes):
            raise AssertionError("plan_apply must not run for a grain-only call")
        monkeypatch.setattr(meshmaps, "plan_apply", _boom)
        out = surfdetail.apply_surface_detail(
            _params(tmp_path, effects=[{"kind": "grain"}]))
        assert out["color_file"] is None

    def test_grain_refuses_when_shader_already_carries_a_bump_network(
            self, fake, tmp_path):
        _masks(tmp_path)
        fake.conns["limb_mat.normalCamera"] = ["someBump.outNormal"]
        with pytest.raises(HandlerError, match="already carries") as exc:
            surfdetail.apply_surface_detail(
                _params(tmp_path, effects=[{"kind": "wear"},
                                          {"kind": "grain"}]))
        assert "maya_bake_textures" in (exc.value.hint or "")
        assert fake.checkpoints == []  # refused before any mutation

    def test_grain_only_finds_shader_via_shader_of(self, fake, tmp_path):
        _masks(tmp_path)
        fake.conns["limb_mat.normalCamera"] = ["someBump.outNormal"]
        with pytest.raises(HandlerError, match="limb_mat"):
            surfdetail.apply_surface_detail(
                _params(tmp_path, effects=[{"kind": "grain"}]))


# --------------------------------------------------------------------------
# 11-15: TestApply
# --------------------------------------------------------------------------


class TestApply:
    def test_color_happy_path(self, fake, tmp_path):
        _masks(tmp_path)
        out = surfdetail.apply_surface_detail(_params(tmp_path, effects=[
            {"kind": "wear", "strength": 2.0, "scale": 4.0}]))
        assert fake.checkpoints == ["apply_surface_detail"]
        assert out["checkpoint_id"] == "cp"
        assert out["color_basename"] == "limb_mat_color_detail.png"
        assert out["color_file"] == os.path.join(str(tmp_path),
                                                 "limb_mat_color_detail.png")
        assert os.path.isfile(out["color_file"])
        assert not list(tmp_path.glob("*.part.png"))
        assert out["height_file"] is None
        assert out["height_basename"] is None
        assert any(dst == "limb_mat.baseColor" for _s, dst in fake.connected)
        assert out["mesh"] == "|limb"
        assert out["effects"][0]["kind"] == "wear"

    def test_color_replaces_a_file_base_and_sweeps_the_old_node(
            self, fake, tmp_path):
        _masks(tmp_path)
        base = tmp_path / "albedo.png"
        pngwrite.write_png(str(base), 2, 2, [(200, 100, 50)] * 4)
        fake.types["kit_file"] = "file"
        fake.conns["limb_mat.baseColor"] = ["kit_file.outColor"]
        fake.attr_values["kit_file.fileTextureName"] = str(base)
        fake.attr_values["kit_file.colorSpace"] = "sRGB"
        surfdetail.apply_surface_detail(_params(tmp_path))
        assert "kit_file" in fake.deleted
        assert os.path.isfile(str(base))  # the input atlas is never touched

    # F2 (#775 fix wave): a second apply to the same material resolves its
    # own previous composite as the new base (the first apply's rewire made
    # that the colour slot's current file) and is about to write over that
    # same path - warn rather than silently compound.
    def test_reapply_to_same_material_warns_and_still_succeeds(self, fake,
                                                                tmp_path):
        _masks(tmp_path)
        first = surfdetail.apply_surface_detail(_params(tmp_path))
        assert not any("colour base" in w for w in first["warnings"])

        second = surfdetail.apply_surface_detail(_params(tmp_path))
        assert second["color_file"] == first["color_file"]
        assert any("colour base" in w for w in second["warnings"])
        assert any("limb_mat_color_detail.png" in w
                   for w in second["warnings"])
        assert os.path.isfile(second["color_file"])

    def test_grain_happy_path_wires_bump_network(self, fake, tmp_path):
        _masks(tmp_path)
        out = surfdetail.apply_surface_detail(
            _params(tmp_path, effects=[{"kind": "grain", "strength": 0.7}]))
        assert out["height_basename"] == "limb_height.png"
        assert os.path.isfile(out["height_file"])
        assert out["color_file"] is None

        bump_nodes = [n for n in fake.created if fake.types.get(n) == "bump2d"]
        assert len(bump_nodes) == 1
        bump = bump_nodes[0]
        assert fake.attr_values[bump + ".bumpInterp"] == 0
        assert fake.attr_values[bump + ".bumpDepth"] == 0.7

        file_nodes = [n for n in fake.created if fake.types.get(n) == "file"]
        assert len(file_nodes) == 1
        fnode = file_nodes[0]
        assert (fnode + ".outAlpha", bump + ".bumpValue") in fake.connected
        # Without alphaIsLuminance the whole network is INERT: pngwrite
        # emits RGB with no alpha, so the file node's outAlpha - the plug
        # driving bumpValue on the line above - is a CONSTANT 1.0 and no
        # bumpDepth can make it shade (#775 task 6, measured live).
        assert fake.attr_values[fnode + ".alphaIsLuminance"] is True
        assert (bump + ".outNormal", "limb_mat.normalCamera") in fake.connected

    def test_changed_fraction_below_floor_warns(self, fake, tmp_path,
                                                monkeypatch):
        _masks(tmp_path)
        monkeypatch.setattr(
            surfdetail.surfdetail_math, "composite_detail",
            lambda base, effects, res: {
                "pixels": [(0, 0, 0)] * (res * res),
                "changed": {"wear": 0.001}})
        out = surfdetail.apply_surface_detail(_params(tmp_path))
        assert out["effects"][0]["changed_fraction"] == 0.001
        assert any("almost nothing" in w for w in out["warnings"])

    def test_grain_changed_fraction_below_floor_warns(self, fake, tmp_path,
                                                       monkeypatch):
        _masks(tmp_path)
        monkeypatch.setattr(
            surfdetail, "_grain_pixels",
            lambda grain, res: ([(0, 0, 0)] * (res * res), 0.001))
        out = surfdetail.apply_surface_detail(
            _params(tmp_path, effects=[{"kind": "grain"}]))
        assert out["effects"][0]["changed_fraction"] == 0.001
        assert any("almost nothing" in w for w in out["warnings"])

    def test_postcondition_reads_file_backed_at_the_new_path(self, fake,
                                                              tmp_path):
        _masks(tmp_path)
        out = surfdetail.apply_surface_detail(_params(tmp_path))
        claims = surfdetail.texclaim.material_claims(fake, ["|limbShape"])
        claim = next(c for c in claims if c["material"] == "limb_mat"
                    and c["attr"] == "baseColor")
        assert claim["classification"] == "file"
        assert claim["terminals"][0]["file_path"] == out["color_file"].replace(
            "\\", "/")

    def test_result_shape_exact_keys(self, fake, tmp_path):
        _masks(tmp_path)
        out = surfdetail.apply_surface_detail(_params(tmp_path, effects=[
            {"kind": "wear"}, {"kind": "grain"}]))
        assert set(out) == {"mesh", "effects", "color_file", "color_basename",
                            "height_file", "height_basename", "file_nodes",
                            "checkpoint_id", "warnings"}
        for eff in out["effects"]:
            assert set(eff) == {"kind", "strength", "scale", "changed_fraction"}

    def test_apply_failure_sweeps_created_nodes(self, fake, tmp_path,
                                                monkeypatch):
        _masks(tmp_path)

        # Fail on the bump2d creation, after the file+place2d already exist.
        real_shading_node = fake.shadingNode

        def _flaky(node_type, name=None, **kw):
            if node_type == "bump2d":
                raise RuntimeError("kaboom")
            return real_shading_node(node_type, name=name, **kw)
        monkeypatch.setattr(fake, "shadingNode", _flaky)
        with pytest.raises(HandlerError, match="checkpoint") as exc:
            surfdetail.apply_surface_detail(
                _params(tmp_path, effects=[{"kind": "grain"}]))
        assert "cp" in str(exc.value)
        # the file + place2d created before the failure are gone again
        remaining = [n for n in fake.created if n not in fake.deleted]
        assert not any(fake.types.get(n) in ("file", "place2dTexture")
                       for n in remaining)
        assert all(n in fake.deleted for n in fake.created)
