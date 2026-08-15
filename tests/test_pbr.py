"""assign_pbr - the three-map stack, and the two live-only traps it encodes.

No Maya. The traps (bumpValue is a float; normal/mask are Raw) cannot be caught
by a viewport or by any check outside Maya, which is exactly why they are
asserted HERE as properties of the network this handler builds.
"""

import os

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import material, pbr


class FakeCmds:
    def __init__(self):
        self.objects = {"|torso", "|arm"}
        self.shapes = {"|torso": ("|torso|torsoShape", "mesh"),
                       "|arm": ("|arm|armShape", "mesh")}
        self.node_types = {}
        self.connections = []
        self.attrs = {}
        self.created = []
        self.deleted = []
        self.sg_members = {}
        self.shader_to_sg = {}
        self.fail_on = None

    # ---- reads
    def ls(self, name=None, long=False, **kw):
        return [o for o in self.objects if o == name or o.split("|")[-1] == name]

    def objExists(self, name):
        return name in self.objects

    def listRelatives(self, node, shapes=False, fullPath=False, noIntermediate=False):
        entry = self.shapes.get(node)
        return [entry[0]] if entry else None

    def nodeType(self, node):
        return self.node_types.get(node, "mesh")

    def listConnections(self, node, type=None, **kw):
        if type == "shadingEngine" and node.endswith(".outColor"):
            sg = self.shader_to_sg.get(node[: -len(".outColor")])
            return [sg] if sg else []
        return []

    def listSets(self, object=None, type=None):
        return [sg for sg, members in self.sg_members.items() if object in members]

    # ---- writes
    def shadingNode(self, node_type, name=None, **kw):
        if self.fail_on == node_type:
            raise RuntimeError("forced failure creating %s" % node_type)
        self.created.append(name)
        self.objects.add(name)
        self.node_types[name] = node_type
        return name

    def sets(self, *args, **kw):
        if kw.get("renderable"):
            name = kw.get("name")
            self.objects.add(name)
            self.node_types[name] = "shadingEngine"
            self.sg_members.setdefault(name, [])
            return name
        if kw.get("edit") and kw.get("forceElement"):
            shape, target = args[0], kw["forceElement"]
            for members in self.sg_members.values():
                if shape in members:
                    members.remove(shape)
            self.sg_members.setdefault(target, []).append(shape)
            return []
        return []

    def connectAttr(self, src, dst, force=False):
        self.connections.append((src, dst))
        if dst.endswith(".surfaceShader") and src.endswith(".outColor"):
            self.shader_to_sg[src[: -len(".outColor")]] = dst[: -len(".surfaceShader")]

    def setAttr(self, attr, *value, **kw):
        self.attrs[attr] = value[0] if len(value) == 1 else value

    def delete(self, *names, **kw):
        for n in names:
            self.deleted.append(n)
            self.objects.discard(n)


@pytest.fixture
def fake(monkeypatch, tmp_path):
    fake = FakeCmds()
    monkeypatch.setattr(pbr, "_cmds", lambda: fake)
    monkeypatch.setattr(material, "_cmds", lambda: fake)
    return fake


@pytest.fixture
def atlas(tmp_path):
    """Real files on disk - assign_pbr refuses paths that do not exist."""
    paths = {}
    for name in ("albedo", "normal", "mask"):
        path = tmp_path / ("kit_%s.png" % name)
        path.write_bytes(b"not really a png")
        paths[name] = str(path)
    return paths


def _three_map(atlas):
    """The exact stack both revision-2 art runs hand-wired."""
    return {
        "color": atlas["albedo"],
        "normal": atlas["normal"],
        "metalness": {"path": atlas["mask"], "channel": "r"},
        "roughness": {"path": atlas["mask"], "channel": "g", "invert": True},
    }


def _dst(fake, plug):
    return [src for src, dst in fake.connections if dst.endswith(plug)]


class TestTheTwoLiveOnlyTraps:
    def test_normal_map_reaches_bump2d_through_outAlpha_not_outColor(self, fake, atlas):
        """bumpValue is a single float: file.outColor is rejected outright. With
        bumpInterp = 1 Maya follows the alpha connection back to the RGB."""
        pbr.assign_pbr({"mesh": "|torso", "maps": {"normal": atlas["normal"]},
                        "name": "kit"})
        into_bump = _dst(fake, ".bumpValue")
        assert into_bump and all(s.endswith(".outAlpha") for s in into_bump), into_bump
        assert not any(s.endswith(".outColor") for s in into_bump)
        assert fake.attrs["kit_bump.bumpInterp"] == 1
        assert _dst(fake, ".normalCamera") == ["kit_bump.outNormal"]

    def test_data_maps_are_read_raw_and_pinned_against_colour_rules(self, fake, atlas):
        """sRGB on a normal map bends the normals; on a mask it shifts every
        roughness value. ignoreColorSpaceFileRules is what keeps it that way
        after the scene is reopened."""
        pbr.assign_pbr({"mesh": "|torso", "maps": _three_map(atlas), "name": "kit"})
        for node in ("kit_normal_tex", "kit_metalness_tex"):
            assert fake.attrs["%s.colorSpace" % node] == "Raw"
            assert fake.attrs["%s.ignoreColorSpaceFileRules" % node] is True

    def test_the_albedo_is_left_as_colour(self, fake, atlas):
        pbr.assign_pbr({"mesh": "|torso", "maps": {"color": atlas["albedo"]},
                        "name": "kit"})
        assert "kit_color_tex.colorSpace" not in fake.attrs


class TestTheThreeMapStack:
    def test_builds_the_whole_network_in_one_call(self, fake, atlas):
        result = pbr.assign_pbr({"mesh": "|torso", "maps": _three_map(atlas),
                                 "name": "kit"})
        assert result["material"] == "kit"
        assert set(result["maps"]) == {"color", "normal", "metalness", "roughness"}
        assert _dst(fake, ".baseColor") == ["kit_color_tex.outColor"]
        assert _dst(fake, ".metalness") == ["kit_metalness_tex.outColorR"]

    def test_smoothness_becomes_roughness_through_a_reverse_node(self, fake, atlas):
        pbr.assign_pbr({"mesh": "|torso", "maps": _three_map(atlas), "name": "kit"})
        inv = "kit_roughness_inv"
        assert fake.node_types[inv] == "reverse"
        assert (("kit_metalness_tex.outColorG", inv + ".inputX")) in fake.connections
        assert _dst(fake, ".specularRoughness") == [inv + ".outputX"]

    def test_two_slots_on_one_image_share_a_single_file_node(self, fake, atlas):
        """Metalness and smoothness are two channels of ONE mask; reading the
        image twice doubles the texture memory for identical pixels."""
        result = pbr.assign_pbr({"mesh": "|torso", "maps": _three_map(atlas),
                                 "name": "kit"})
        assert result["maps"]["metalness"]["file"] == result["maps"]["roughness"]["file"]
        files = [n for n in fake.created if fake.node_types.get(n) == "file"]
        assert len(files) == 3  # albedo, normal, mask - not four
        assert any("shares file node" in w for w in result["warnings"])

    def test_the_same_image_at_two_colour_spaces_gets_two_nodes(self, fake, atlas):
        """One file node cannot be Raw and sRGB at once - that would silently
        give one of the two slots the wrong curve."""
        result = pbr.assign_pbr({
            "mesh": "|torso", "name": "kit",
            "maps": {"color": {"path": atlas["mask"]},
                     "metalness": {"path": atlas["mask"], "channel": "r"}},
        })
        assert result["maps"]["color"]["file"] != result["maps"]["metalness"]["file"]

    def test_texture_placement_is_wired_not_left_to_defaults(self, fake, atlas):
        pbr.assign_pbr({"mesh": "|torso", "maps": {"color": atlas["albedo"]},
                        "name": "kit"})
        assert ("kit_color_p2d.outUV", "kit_color_tex.uvCoord") in fake.connections
        assert ("kit_color_p2d.outUvFilterSize",
                "kit_color_tex.uvFilterSize") in fake.connections

    def test_mip_filtering_is_explicit_so_two_sessions_agree(self, fake, atlas):
        pbr.assign_pbr({"mesh": "|torso", "name": "kit",
                        "maps": {"color": {"path": atlas["albedo"],
                                           "mip_filter": False}}})
        assert fake.attrs["kit_color_tex.filterType"] == 0

    def test_scalar_params_ride_along_with_the_maps(self, fake, atlas):
        pbr.assign_pbr({"mesh": "|torso", "name": "kit",
                        "maps": {"color": atlas["albedo"]},
                        "params": {"base": 1.0, "specular": 0.5}})
        assert fake.attrs["kit.base"] == 1.0
        assert fake.attrs["kit.specular"] == 0.5


class TestSharingOneMaterial:
    def test_a_list_of_meshes_shares_exactly_one_material(self, fake, atlas):
        """The whole reason the kit atlases: one material, one draw call, N
        pieces. A shader per mesh would defeat the UV work that fed it."""
        result = pbr.assign_pbr({"mesh": ["|torso", "|arm"], "name": "kit",
                                 "maps": {"color": atlas["albedo"]}})
        assert result["meshes"] == ["|torso", "|arm"]
        shaders = [n for n in fake.objects
                   if fake.node_types.get(n) == "standardSurface"]
        assert shaders == ["kit"]
        sg = result["shading_group"]
        assert set(fake.sg_members[sg]) == {"|torso|torsoShape", "|arm|armShape"}

    def test_naming_an_existing_material_reuses_it(self, fake, atlas):
        first = pbr.assign_pbr({"mesh": "|torso", "name": "kit",
                                "maps": {"color": atlas["albedo"]}})
        second = pbr.assign_pbr({"mesh": "|arm", "name": "kit",
                                 "maps": {"color": atlas["albedo"]}})
        assert second["material"] == first["material"] == "kit"


class TestRefusals:
    def test_a_missing_texture_is_refused_not_silently_flat(self, fake, tmp_path):
        """Maya renders a missing file as flat colour and reports nothing - the
        material simply looks wrong, which is this project's recurring failure."""
        with pytest.raises(HandlerError) as exc:
            pbr.assign_pbr({"mesh": "|torso",
                            "maps": {"color": str(tmp_path / "never_baked.png")}})
        assert "never_baked.png" in str(exc.value)
        assert fake.created == []

    def test_relative_and_udim_paths_are_not_second_guessed(self, fake):
        specs = pbr.validate_maps({
            "color": "sourceimages/kit.png",
            "roughness": {"path": "D:/kit/atlas.<UDIM>.png"},
        })
        assert pbr.missing_files(specs) == []

    def test_unknown_slot_lists_the_real_ones(self, fake, atlas):
        with pytest.raises(HandlerError) as exc:
            pbr.assign_pbr({"mesh": "|torso", "maps": {"bumpiness": atlas["normal"]}})
        assert "roughness" in exc.value.hint

    def test_a_channel_on_a_colour_slot_is_refused(self, fake, atlas):
        with pytest.raises(HandlerError) as exc:
            pbr.assign_pbr({"mesh": "|torso",
                            "maps": {"color": {"path": atlas["albedo"],
                                               "channel": "r"}}})
        assert "channel" in str(exc.value)

    def test_an_unknown_channel_is_refused(self, fake, atlas):
        with pytest.raises(HandlerError) as exc:
            pbr.assign_pbr({"mesh": "|torso",
                            "maps": {"metalness": {"path": atlas["mask"],
                                                   "channel": "z"}}})
        assert "channels" in exc.value.hint

    def test_inverting_a_normal_map_is_refused_with_the_real_fix(self, fake, atlas):
        with pytest.raises(HandlerError) as exc:
            pbr.assign_pbr({"mesh": "|torso",
                            "maps": {"normal": {"path": atlas["normal"],
                                                "invert": True}}})
        assert "green channel" in exc.value.hint

    def test_a_param_that_fights_a_map_is_refused(self, fake, atlas):
        """setAttr on a connected attribute fails in Maya, and a result that
        reported both would be a lie about what the material does."""
        with pytest.raises(HandlerError) as exc:
            pbr.assign_pbr({"mesh": "|torso", "maps": _three_map(atlas),
                            "params": {"roughness": 0.4}})
        assert "roughness" in str(exc.value)

    def test_no_maps_at_all_points_at_assign_material(self, fake):
        with pytest.raises(HandlerError) as exc:
            pbr.assign_pbr({"mesh": "|torso", "maps": {}})
        assert "assign_material" in exc.value.hint

    def test_every_refusal_happens_before_a_single_node_is_built(self, fake, atlas):
        before = set(fake.objects)
        for bad in (
            {"mesh": "|torso", "maps": {"color": {"path": atlas["albedo"],
                                                  "channel": "r"}}},
            {"mesh": "|torso", "maps": {"nope": atlas["albedo"]}},
            {"mesh": "|torso", "maps": _three_map(atlas),
             "params": {"metalness": 1.0}},
            {"mesh": [], "maps": {"color": atlas["albedo"]}},
        ):
            with pytest.raises(HandlerError):
                pbr.assign_pbr(bad)
        assert fake.objects == before
        assert fake.created == []


class TestZeroOrphans:
    def test_a_failure_midway_sweeps_the_material_it_minted(self, fake, atlas):
        fake.fail_on = "bump2d"  # albedo + normal file nodes exist by then
        with pytest.raises(RuntimeError):
            pbr.assign_pbr({"mesh": "|torso", "name": "kit",
                            "maps": _three_map(atlas)})
        leftover = [n for n in fake.objects if n.startswith("kit")]
        assert leftover == [], "assign_pbr left orphans: %s" % leftover

    def test_a_failure_keeps_a_material_it_did_not_create(self, fake, atlas):
        """Reuse means the material predates this call; sweeping it would
        destroy every other mesh's shading over an unrelated failure.

        The second mesh IS left wearing the material - a failed call is one
        undo step by the dispatcher's contract, so a partial assignment is
        recoverable. Deleting a shared material never is.
        """
        pbr.assign_pbr({"mesh": "|torso", "name": "kit",
                        "maps": {"color": atlas["albedo"]}})
        before = list(fake.created)
        fake.fail_on = "bump2d"
        with pytest.raises(RuntimeError):
            pbr.assign_pbr({"mesh": "|arm", "name": "kit",
                            "maps": {"normal": atlas["normal"]}})
        assert "kit" in fake.objects
        assert "|torso|torsoShape" in fake.sg_members["kitSG"]
        assert [n for n in fake.created if n not in before
                and n in fake.objects] == [], "the failed call left orphan nodes"


class TestMaterialWhitelist:
    def test_base_is_authorable(self):
        """Both art runs set base explicitly rather than inherit a default that
        moved between Maya versions."""
        assert "base" in material.PARAM_WHITELIST["standardSurface"]
        assert material._ATTR["standardSurface"]["base"] == "base"

    def test_slots_cover_every_map_this_handler_wires(self):
        assert set(pbr.SLOTS) >= {"color", "roughness", "metalness", "normal"}
        for slot, (attr, _kind) in pbr.SLOTS.items():
            assert attr, slot


def test_the_handler_never_touches_the_filesystem_for_relative_paths():
    """missing_files is pure enough to run outside Maya - the eval scripts use
    it to check a manifest before shipping the call."""
    assert pbr.missing_files([{"path": "kit.png"}]) == []
    assert pbr.missing_files(
        [{"path": os.path.join(os.sep, "definitely", "absent.png")}]
    ) != []
