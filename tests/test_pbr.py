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
    """Two mesh transforms, plus the whole shading network assign_pbr builds.

    #799, the three rules, applied wherever this fake models the call at all:

      1. a query - OR A WRITE - aimed at a node this scene does not hold
         RAISES the way Maya does; `objExists` is the one exception. This
         file deletes nodes on every orphan-sweep path, so the deleted list
         is what those queries consult, and a name used again afterwards is
         a NEW node rather than a permanent tombstone.
      2. `setAttr` refuses a plug a connection feeds, and a compound whose
         CHILD is fed refuses too. This is the whole point here: assign_pbr
         connects file nodes INTO the shader's own attributes and then hands
         the caller's scalar params to assign_material, which writes them
         straight onto those same attributes.
      3. nothing answers unconditionally. `nodeType` answered "mesh" for
         every node it had never heard of - which is also the answer
         require_mesh is looking for, so its shape check could not fail here
         - and `sets` answered [] to a membership QUERY, which left
         ensure_object_shading's healthy branch dead in this file: every call
         re-forced an assignment it had just made.
    """

    _CHILD_SUFFIXES = ("R", "G", "B", "X", "Y", "Z")

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
        self.locked = set()

    # ---- resolution
    def _live(self):
        names = set(self.objects) | {s for s, _ in self.shapes.values()}
        return names - set(self.deleted)

    def _matches(self, name):
        return sorted(n for n in self._live()
                      if n == name or n.split("|")[-1] == name)

    def _require(self, name):
        if not self._matches(name):
            raise RuntimeError("No object matches name: %s" % name)

    # ---- reads
    def ls(self, name=None, long=False, **kw):
        return self._matches(name)

    def objExists(self, name):
        return bool(self._matches(name))

    def listRelatives(self, node, shapes=False, fullPath=False, noIntermediate=False):
        self._require(node)
        entry = self.shapes.get(node)
        if not entry or entry[0] in self.deleted:
            return None
        return [entry[0]]

    def nodeType(self, node):
        self._require(node)
        recorded = self.node_types.get(node)
        if recorded:
            return recorded
        for shape, ntype in self.shapes.values():
            if shape == node:
                return ntype
        return "transform"

    def _pairs(self):
        return list(self.connections)

    def getAttr(self, attr, lock=False, **kw):
        # plugwrite's lock question (#802/#804). Nothing else is modelled.
        self._require(attr.split(".")[0])
        if lock and not kw:
            return attr in self.locked
        raise AssertionError("unmodelled getAttr(%r, %r)" % (attr, kw))

    def listConnections(self, node, type=None, source=False, destination=True,
                        plugs=False, **kw):
        self._require(node.split(".")[0])
        if type == "shadingEngine" and node.endswith(".outColor"):
            sg = self.shader_to_sg.get(node[: -len(".outColor")])
            return [sg] if sg and sg not in self.deleted else []
        if type == "shadingEngine" and "." not in node:
            # meshcheck.first_sg asks a SHAPE which shading groups it is in.
            # This used to answer [] for every shape however wired - a fake
            # certifying "this mesh has no shading group" unconditionally.
            return [sg for sg, members in self.sg_members.items()
                    if node in members]
        if type is None and source and not destination:
            # #804: what feeds an exact plug, or (bare node) any plug on it -
            # the walk plugwrite.blocker and orphans.upstream_network make.
            # None when nothing does, as Maya answers.
            if "." in node:
                srcs = [s for s, d in self._pairs() if d == node]
            else:
                srcs = [s for s, d in self._pairs()
                        if d.split(".")[0] == node]
            srcs = [s for s in srcs if s.split(".")[0] not in self.deleted]
            return (srcs if plugs else
                    list(dict.fromkeys(s.split(".")[0] for s in srcs))) or None
        if type is None and destination and not source:
            # ...and what a node feeds, downstream: orphans.real_outputs.
            if "." in node:
                dsts = [d for s, d in self._pairs() if s == node]
            else:
                dsts = [d for s, d in self._pairs()
                        if s.split(".")[0] == node]
            return (dsts if plugs else
                    list(dict.fromkeys(d.split(".")[0] for d in dsts))) or None
        raise AssertionError(
            "unmodelled listConnections(%r, type=%r)" % (node, type))

    def listSets(self, object=None, type=None):
        self._require(object)
        return [sg for sg, members in self.sg_members.items() if object in members]

    # ---- writes
    def _born(self, name):
        """Register a node. A name that was deleted and is now used again is
        a NEW node, not a resurrection - so it stops counting as deleted."""
        self.objects.add(name)
        self.deleted = [d for d in self.deleted if d != name]

    def shadingNode(self, node_type, name=None, **kw):
        if self.fail_on == node_type:
            raise RuntimeError("forced failure creating %s" % node_type)
        self.created.append(name)
        self._born(name)
        self.node_types[name] = node_type
        return name

    def sets(self, *args, **kw):
        if kw.get("renderable"):
            name = kw.get("name")
            self._born(name)
            self.node_types[name] = "shadingEngine"
            self.sg_members.setdefault(name, [])
            return name
        if kw.get("query"):
            self._require(args[0])
            return list(self.sg_members.get(args[0], []))
        if kw.get("edit") and kw.get("forceElement"):
            shape, target = args[0], kw["forceElement"]
            self._require(shape)
            self._require(target)
            for members in self.sg_members.values():
                if shape in members:
                    members.remove(shape)
            self.sg_members.setdefault(target, []).append(shape)
            return []
        # #799 round 2: the trailing `return []` that used to sit here
        # answered ANY other flag combination blind - `sets(node, edit=True,
        # remove=...)` on a DELETED node included.
        raise AssertionError(
            "unmodelled sets(%r, %r): teach the fake what Maya answers "
            "before a handler relies on it" % (args, sorted(kw)))

    def connectAttr(self, src, dst, force=False):
        # #799 round 2: contract point 1 stopped at the read/write boundary -
        # a connectAttr aimed at a name that stopped answering was RECORDED
        # as a success. Maya raises "No object matches name" for both ends.
        self._require(src.split(".")[0])
        self._require(dst.split(".")[0])
        # A destination plug takes ONE source: -force replaces whatever was
        # already there rather than stacking a second connection on it, which
        # is how re-texturing a shared material strands the old file node.
        if force:
            self.connections = [(s, d) for s, d in self.connections if d != dst]
        self.connections.append((src, dst))
        if dst.endswith(".surfaceShader") and src.endswith(".outColor"):
            self.shader_to_sg[src[: -len(".outColor")]] = dst[: -len(".surfaceShader")]

    def _blocker(self, plug):
        """The connection or lock that makes `plug` unwritable, or None.

        Maya's compound/child asymmetry, both directions: baseColor refuses
        when baseColorG alone is driven, and baseColorG refuses when the
        whole compound is.
        """
        fed = {dst for _, dst in self.connections} | self.locked
        if plug in fed:
            return plug
        node, _, attr = plug.rpartition(".")
        for suffix in self._CHILD_SUFFIXES:
            if "%s.%s%s" % (node, attr, suffix) in fed:
                return "%s.%s%s" % (node, attr, suffix)
        if attr[-1:] in self._CHILD_SUFFIXES:
            parent = "%s.%s" % (node, attr[:-1])
            if parent in fed:
                return parent
        return None

    def setAttr(self, attr, *value, **kw):
        # #799 round 2: a write to a node the scene does not hold raises "No
        # object matches name" in Maya, exactly as a read does - the half of
        # contract point 1 the first pass left out.
        self._require(attr.split(".")[0])
        blocker = self._blocker(attr)
        if blocker:
            raise RuntimeError(
                "setAttr: The attribute '%s' is locked or connected and "
                "cannot be modified." % blocker
            )
        self.attrs[attr] = value[0] if len(value) == 1 else value

    def rename(self, node, new):
        # Maya suffixes on collision rather than refusing; modelled so the
        # #804 name claim is caught by the name it gets back.
        self._require(node)
        resolved = self._matches(node)[0]
        if new in self.objects and new != resolved:
            new = new + "1"
        self.objects.discard(resolved)
        self._born(new)
        self.node_types[new] = self.node_types.pop(resolved, "transform")
        self.created = [new if c == resolved else c for c in self.created]
        self.connections = [
            (s.replace(resolved + ".", new + ".", 1) if s.split(".")[0] == resolved else s,
             d.replace(resolved + ".", new + ".", 1) if d.split(".")[0] == resolved else d)
            for s, d in self.connections]
        for key in [k for k in self.attrs if k.split(".")[0] == resolved]:
            self.attrs[new + key[len(resolved):]] = self.attrs.pop(key)
        return new

    def delete(self, *names, **kw):
        for n in names:
            self._require(n)
            resolved = self._matches(n)[0]
            self.deleted.append(resolved)
            self.objects.discard(resolved)
            # Maya's delete takes the whole subtree: a transform's shape goes
            # with it (#799 round 2, copied from test_naming.py).
            entry = self.shapes.get(resolved)
            if entry:
                self.deleted.append(entry[0])
            # Deleting a node takes its connections with it, both ways.
            self.connections = [(s, d) for s, d in self.connections
                                if s.split(".")[0] != resolved
                                and d.split(".")[0] != resolved]


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

    def test_a_key_a_map_spec_never_reads_is_refused(self, fake, atlas):
        """#797 row 17: the #767 defect one level down. `maps` is a known
        top-level key, so every key INSIDE a slot's spec used to be
        accepted and dropped - a 'chanel' typo left the scalar reading the
        default channel r, silently, and the result reported success."""
        with pytest.raises(HandlerError) as exc:
            pbr.assign_pbr({"mesh": "|torso",
                            "maps": {"metalness": {"path": atlas["mask"],
                                                   "chanel": "g"}}})
        assert "does not take" in str(exc.value)
        assert "chanel" in str(exc.value)
        assert "metalness" in str(exc.value)
        assert "channel" in (exc.value.hint or "")
        assert fake.created == []

    def test_the_keys_a_map_spec_does_read_still_work(self, fake, atlas):
        specs = pbr.validate_maps(
            {"roughness": {"path": atlas["mask"], "channel": "g",
                           "invert": True, "raw": False,
                           "mip_filter": False}})
        assert specs[0]["channel"] == "g"
        assert specs[0]["invert"] is True
        assert specs[0]["raw"] is False
        assert specs[0]["mip_filter"] is False

    def test_the_nested_refusal_names_the_slot_it_belongs_to(self, fake,
                                                             atlas):
        """Two slots, one bad key: the message must say WHICH."""
        with pytest.raises(HandlerError) as exc:
            pbr.assign_pbr({"mesh": "|torso",
                            "maps": {"color": atlas["albedo"],
                                     "normal": {"path": atlas["normal"],
                                                "flip_green": True}}})
        assert "normal" in str(exc.value)
        assert "flip_green" in str(exc.value)

    def test_every_refusal_fires_before_maya_is_imported(self, tmp_path):
        """#767's proof, without the fake: `_cmds()` used to run before a
        single map was looked at, so a typo was answered only after the
        scene had been reached."""
        with pytest.raises(HandlerError) as exc:
            pbr.assign_pbr({"mesh": "|torso",
                            "maps": {"metalness": {"path": "m.png",
                                                   "chanel": "g"}}})
        assert "does not take" in str(exc.value)
        with pytest.raises(HandlerError, match="not found"):
            pbr.assign_pbr({"mesh": "|torso",
                            "maps": {"color": str(tmp_path / "absent.png")}})

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


class TestReuseMeetsTheNetworkItAlreadyBuilt:
    """#799. Every refusal in TestRefusals is derived from THIS call's maps.
    A material reached by `name` carries the maps of every call before it, and
    nothing here looks at them - which the fake could not show while its
    setAttr accepted a connected plug and its connectAttr stacked sources.
    """

    def test_a_param_fighting_a_map_from_an_earlier_call_is_refused(self, fake, atlas):
        # #804: the clash guard sees this call's maps; the scene is asked
        # about the rest, before anything is built or moved. MEASURED: Maya
        # raises "locked or connected" for the write this used to make.
        pbr.assign_pbr({"mesh": "|torso", "name": "kit",
                        "maps": {"color": atlas["albedo"]}})
        objects_before = set(fake._live())
        sg_before = {k: list(v) for k, v in fake.sg_members.items()}
        with pytest.raises(HandlerError) as exc:
            pbr.assign_pbr({"mesh": "|arm", "name": "kit",
                            "maps": {"normal": atlas["normal"]},
                            "params": {"baseColor": [1.0, 0.0, 0.0]}})
        assert "baseColor" in str(exc.value)
        assert "kit_color_tex" in str(exc.value)
        assert "assign_pbr" in (exc.value.hint or "")
        assert set(fake._live()) == objects_before, "a refused call built nodes"
        assert fake.sg_members == sg_before, "a refused call moved the mesh"

    def test_an_unknown_param_on_a_shared_material_is_still_the_whitelist_refusal(self, fake, atlas):
        # Review catch: the early guard indexed the attr table before the
        # whitelist check and turned a typo into a KeyError.
        pbr.assign_pbr({"mesh": "|torso", "name": "kit",
                        "maps": {"color": atlas["albedo"]}})
        with pytest.raises(HandlerError) as exc:
            pbr.assign_pbr({"mesh": "|arm", "name": "kit",
                            "maps": {"normal": atlas["normal"]},
                            "params": {"rougness": 0.4}})
        assert "rougness" in str(exc.value)

    def test_a_bad_second_mesh_is_refused_before_the_old_map_is_swept(self, fake, atlas):
        # Review catch: the stale sweep ran before the extra meshes were
        # resolved, so a typo in mesh two deleted the OLD map and then the
        # failure sweep deleted the new one - a bare material from a
        # refused call.
        pbr.assign_pbr({"mesh": "|torso", "name": "kit",
                        "maps": {"color": atlas["albedo"]}})
        with pytest.raises(HandlerError):
            pbr.assign_pbr({"mesh": ["|torso", "|nosuch"], "name": "kit",
                            "maps": {"color": atlas["mask"]}})
        assert ("kit_color_tex.outColor", "kit.baseColor") in fake.connections
        assert fake.attrs["kit_color_tex.fileTextureName"] == atlas["albedo"]

    def test_re_texturing_a_normal_slot_reclaims_the_bump_name(self, fake, atlas):
        # Review catch: only file/p2d names were claimed; a bump2d or reverse
        # kept its suffix and accumulated across the look-dev loop.
        pbr.assign_pbr({"mesh": "|torso", "name": "kit",
                        "maps": {"normal": atlas["normal"],
                                 "roughness": {"path": atlas["mask"], "channel": "g",
                                               "invert": True}}})
        pbr.assign_pbr({"mesh": "|torso", "name": "kit",
                        "maps": {"normal": atlas["albedo"],
                                 "roughness": {"path": atlas["mask"], "channel": "r",
                                               "invert": True}}})
        assert sorted(n for n in fake.objects if fake.node_types.get(n) == "bump2d") == ["kit_bump"]
        assert sorted(n for n in fake.objects if fake.node_types.get(n) == "reverse") == ["kit_roughness_inv"]

    def test_a_scalar_on_an_unmapped_slot_of_a_shared_material_still_lands(self, fake, atlas):
        # The guard asks about the params' own plugs, not the material: an
        # earlier colour map does not stop a later metalness constant.
        pbr.assign_pbr({"mesh": "|torso", "name": "kit",
                        "maps": {"color": atlas["albedo"]}})
        out = pbr.assign_pbr({"mesh": "|arm", "name": "kit",
                              "maps": {"normal": atlas["normal"]},
                              "params": {"metalness": 1.0}})
        assert out["material"] == "kit"
        assert fake.attrs["kit.metalness"] == 1.0

    def test_re_texturing_a_slot_does_not_strand_the_old_file_node(self, fake, atlas):
        # #804 MEASURED: after the force-connect the old file node's only
        # output is defaultTextureList1 and Maya never reaps it. The sweep
        # takes it and its place2dTexture, and the new nodes take back the
        # names the old ones held.
        pbr.assign_pbr({"mesh": "|torso", "name": "kit",
                        "maps": {"color": atlas["albedo"]}})
        out = pbr.assign_pbr({"mesh": "|torso", "name": "kit",
                              "maps": {"color": atlas["mask"]}})
        files = sorted(n for n in fake.objects
                       if fake.node_types.get(n) in ("file", "place2dTexture"))
        assert files == ["kit_color_p2d", "kit_color_tex"], files
        assert fake.attrs["kit_color_tex.fileTextureName"] == atlas["mask"]
        assert ("kit_color_tex.outColor", "kit.baseColor") in fake.connections
        assert out["maps"]["color"]["file"] == "kit_color_tex"
        assert out["maps"]["color"]["replaced"] == ["kit_color_tex", "kit_color_p2d"]
        assert "kit_color_tex" in out["nodes"] and "kit_color_p2d" in out["nodes"]

    def test_a_file_node_another_slot_still_uses_survives_a_re_texture(self, fake, atlas):
        # The sweep deletes what nothing REAL uses. One mask image driving
        # metalness and roughness (both raw, so ONE file node) keeps that
        # node when only metalness is re-mapped, and the caller is told
        # what still uses it.
        first = pbr.assign_pbr({"mesh": "|torso", "name": "kit",
                                "maps": {"metalness": {"path": atlas["mask"], "channel": "r"},
                                         "roughness": {"path": atlas["mask"], "channel": "g"}}})
        shared = first["maps"]["metalness"]["file"]
        assert first["maps"]["roughness"]["file"] == shared
        out = pbr.assign_pbr({"mesh": "|torso", "name": "kit",
                              "maps": {"metalness": {"path": atlas["albedo"], "channel": "r"}}})
        files = sorted(n for n in fake.objects if fake.node_types.get(n) == "file")
        assert shared in files and len(files) == 2, files
        assert out["maps"]["metalness"]["replaced"] == []
        assert any(shared in w and "still used by" in w for w in out["warnings"])
        assert ("%s.outColorG" % shared, "kit.specularRoughness") in fake.connections

    def test_the_first_texture_of_a_slot_replaces_nothing(self, fake, atlas):
        out = pbr.assign_pbr({"mesh": "|torso", "name": "kit",
                              "maps": {"color": atlas["albedo"]}})
        assert out["maps"]["color"]["replaced"] == []
        assert not any("still used" in w for w in out["warnings"])


class TestTheFakeRefusesWhatMayaRefuses:
    """#799 round 2: the hardening in FakeCmds has to be ASSERTED somewhere.

    Reverting every behavioural change in the fake left this suite fully
    green, because not one test exercised the new refusals - "a green suite
    proves nothing", one level up. These pin the contract points this fake
    actually models, so loosening it goes red here first.
    """

    def _wired(self):
        """A shader with a file texture driving its base colour, the way
        assign_pbr leaves one."""
        fake = FakeCmds()
        fake.shadingNode("standardSurface", name="kit")
        fake.shadingNode("file", name="kit_color_tex")
        fake.connectAttr("kit_color_tex.outColor", "kit.baseColor", force=True)
        return fake

    # -- point 1: a name that stopped answering ---------------------------
    def test_every_query_about_a_node_that_never_existed_raises(self):
        fake = FakeCmds()
        for call in (lambda: fake.nodeType("ghost"),
                     lambda: fake.listRelatives("ghost", shapes=True,
                                                fullPath=True,
                                                noIntermediate=True),
                     lambda: fake.listConnections("ghost.outColor",
                                                  type="shadingEngine"),
                     lambda: fake.listSets(object="ghost", type="shadingEngine"),
                     lambda: fake.sets("ghost", query=True),
                     lambda: fake.delete("ghost")):
            with pytest.raises(RuntimeError, match="No object matches name"):
                call()
        assert fake.objExists("ghost") is False  # the one question that answers

    def test_a_query_about_a_deleted_node_raises(self):
        fake = FakeCmds()
        fake.shadingNode("file", name="kit_color_tex")
        fake.delete("kit_color_tex")
        assert fake.objExists("kit_color_tex") is False
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.nodeType("kit_color_tex")

    def test_a_write_to_a_node_that_is_gone_raises_too(self):
        # The half contract point 1 was missing: setAttr and connectAttr
        # recorded a success against any name at all - including the orphan
        # file node the sweep has just deleted.
        fake = self._wired()
        fake.delete("kit_color_tex")
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.setAttr("kit_color_tex.fileTextureName", "x.png", type="string")
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.connectAttr("kit_color_tex.outColor", "kit.baseColor",
                             force=True)

    def test_deleting_a_transform_takes_its_shape_with_it(self):
        fake = FakeCmds()
        fake.delete("|torso")
        assert fake.objExists("|torso|torsoShape") is False

    def test_a_name_used_again_after_a_delete_is_a_new_node_not_a_ghost(self):
        # Strictness has a failure mode of its own: a permanent tombstone
        # makes a rebuilt node invisible forever, which manufactures failures.
        fake = FakeCmds()
        fake.shadingNode("file", name="kit_color_tex")
        fake.delete("kit_color_tex")
        fake.shadingNode("file", name="kit_color_tex")
        assert fake.objExists("kit_color_tex") is True
        fake.setAttr("kit_color_tex.fileTextureName", "x.png", type="string")

    # -- point 2: a plug something already drives -------------------------
    def test_setAttr_refuses_a_connected_plug(self):
        fake = self._wired()
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake.setAttr("kit.baseColor", 1.0, 0.0, 0.0, type="double3")

    def test_setAttr_refuses_in_both_compound_directions(self):
        # A compound write when a CHILD is fed...
        fake = FakeCmds()
        fake.shadingNode("standardSurface", name="kit")
        fake.shadingNode("file", name="tex")
        fake.connectAttr("tex.outAlpha", "kit.baseColorG")
        with pytest.raises(RuntimeError, match="kit.baseColorG"):
            fake.setAttr("kit.baseColor", 1.0, 0.0, 0.0, type="double3")
        # ...and a CHILD write when the compound is fed.
        other = self._wired()
        with pytest.raises(RuntimeError, match="kit.baseColor'"):
            other.setAttr("kit.baseColorG", 0.5)

    def test_setAttr_refuses_a_locked_plug_with_nothing_connected(self):
        fake = FakeCmds()
        fake.shadingNode("standardSurface", name="kit")
        fake.locked.add("kit.metalness")
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake.setAttr("kit.metalness", 1.0)

    def test_a_free_plug_still_writes(self):
        fake = self._wired()
        fake.setAttr("kit.metalness", 1.0)
        assert fake.attrs["kit.metalness"] == 1.0

    def test_deleting_the_source_frees_the_plug_again(self):
        # The refusal has to CLEAR: in Maya the destination is writable the
        # instant its source node dies.
        fake = self._wired()
        fake.delete("kit_color_tex")
        fake.setAttr("kit.baseColor", 1.0, 0.0, 0.0, type="double3")
        assert fake.attrs["kit.baseColor"] == (1.0, 0.0, 0.0)

    def test_force_replaces_a_connection_instead_of_stacking_one(self):
        fake = self._wired()
        fake.shadingNode("file", name="second_tex")
        fake.connectAttr("second_tex.outColor", "kit.baseColor", force=True)
        assert [s for s, d in fake.connections
                if d == "kit.baseColor"] == ["second_tex.outColor"]

    # -- point 3: nothing answers unconditionally -------------------------
    def test_sets_refuses_a_flag_combination_it_does_not_model(self):
        fake = FakeCmds()
        with pytest.raises(AssertionError, match="unmodelled sets"):
            fake.sets("|torso|torsoShape", edit=True, remove="someSG")

    def test_listConnections_reports_a_shapes_real_shading_groups(self):
        # It used to answer [] for every shape however wired - the exact call
        # meshcheck.first_sg makes, certifying "no shading group" blind.
        fake = FakeCmds()
        fake.sets(renderable=True, noSurfaceShader=True, empty=True, name="kitSG")
        fake.sets("|torso|torsoShape", edit=True, forceElement="kitSG")
        assert fake.listConnections("|torso|torsoShape",
                                    type="shadingEngine") == ["kitSG"]
        with pytest.raises(AssertionError, match="unmodelled listConnections"):
            fake.listConnections("|torso|torsoShape", type="displayLayer")

    def test_sets_query_answers_the_membership_it_was_given(self):
        # The other blind answer: a membership query used to return [], so
        # ensure_object_shading's healthy branch was dead in this file.
        fake = FakeCmds()
        fake.sets(renderable=True, noSurfaceShader=True, empty=True, name="kitSG")
        fake.sets("|torso|torsoShape", edit=True, forceElement="kitSG")
        assert fake.sets("kitSG", query=True) == ["|torso|torsoShape"]

    def test_nodeType_does_not_call_every_stranger_a_mesh(self):
        fake = FakeCmds()
        fake.shadingNode("file", name="kit_color_tex")
        assert fake.nodeType("kit_color_tex") == "file"
        assert fake.nodeType("|torso") == "transform"
        assert fake.nodeType("|torso|torsoShape") == "mesh"
