"""setup_lighting against a fake cmds - no Maya required."""

import math
from typing import Optional

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import lighting


class FakeCmds:
    """A tiny in-memory scene graph: enough of cmds to test setup_lighting's
    logic without Maya. Node identifiers are long paths ("|parent|child");
    a "shape" is just a node whose type isn't "transform".
    """

    _LIGHT_TYPES = {"directionalLight", "pointLight", "spotLight", "areaLight", "light"}

    def __init__(self, existing_lights=()):
        self.deleted = []
        self.created = []
        self.attrs = {}
        self.objects = set()      # every node's long path
        self.node_type = {}       # long path -> type string
        self.parent = {}          # long path -> parent long path or None
        self.children = {}        # long path -> list[long path] (all direct children)
        for shape_name in existing_lights:
            self.add_light(shape_name)

    # -- scene construction helpers, used by tests to build fixtures --
    def add_transform(self, name: str, parent: Optional[str] = None) -> str:
        path = (parent + "|" if parent else "|") + name
        self.objects.add(path)
        self.node_type[path] = "transform"
        self.parent[path] = parent
        self.children.setdefault(path, [])
        if parent:
            self.children.setdefault(parent, []).append(path)
        return path

    def add_shape(self, transform_path: str, shape_name: str, node_type: str) -> str:
        path = transform_path + "|" + shape_name
        self.objects.add(path)
        self.node_type[path] = node_type
        self.parent[path] = transform_path
        self.children.setdefault(transform_path, []).append(path)
        self.children.setdefault(path, [])
        return path

    def add_light(self, shape_name: str, transform_name: Optional[str] = None) -> str:
        transform_name = transform_name or shape_name.replace("Shape", "")
        transform = self.add_transform(transform_name)
        self.add_shape(transform, shape_name, "directionalLight")
        return transform

    # -- fake cmds surface --
    def ls(self, *args, long=False, type=None, **kw):
        if type == "light":
            return [n for n, t in self.node_type.items() if t in self._LIGHT_TYPES]
        if type is not None:
            # Arnold's light nodes answer only to their OWN type - the reason
            # light_shapes has to ask for each of them by name.
            if type in lighting.ARNOLD_LIGHT_TYPES and not self.mtoa_loaded:
                raise RuntimeError("Unknown object type: %s" % type)
            return [n for n, t in self.node_type.items() if t == type]
        return []

    # -- mtoa, which is installed-but-unloaded on a cold Maya --
    mtoa_installed = True
    mtoa_loaded = False

    def pluginInfo(self, name, query=False, loaded=False, **kw):
        if loaded:
            return self.mtoa_loaded
        return None

    def loadPlugin(self, name, **kw):
        if not self.mtoa_installed:
            raise RuntimeError("plugin not found: %s" % name)
        self.mtoa_loaded = True
        return [name]

    def createNode(self, node_type, name=None, **kw):
        """Maya parents a new light shape under an auto-created transform and
        hands back the SHAPE - the shape/transform confusion that has bitten
        this codebase before."""
        shape_name = name or (node_type + "Shape1")
        transform = self.add_transform(shape_name.replace("Shape", "") + "_xf")
        self.created.append((node_type, name))
        return self.add_shape(transform, shape_name, node_type)

    def listRelatives(self, node, parent=False, shapes=False, children=False,
                       fullPath=False, type=None, **kw):
        if parent:
            p = self.parent.get(node)
            return [p] if p else None
        kids = list(self.children.get(node, []))
        if shapes:
            kids = [k for k in kids if self.node_type.get(k) != "transform"]
        if type is not None:
            wanted = self._LIGHT_TYPES if type == "light" else {type}
            kids = [k for k in kids if self.node_type.get(k) in wanted]
        return kids or None

    def objExists(self, name):
        return name in self.objects

    def _delete_recursive(self, path):
        if path not in self.objects:
            return
        for child in list(self.children.get(path, [])):
            self._delete_recursive(child)
        self.deleted.append(path)
        self.objects.discard(path)
        self.node_type.pop(path, None)
        parent = self.parent.pop(path, None)
        self.children.pop(path, None)
        if parent and parent in self.children:
            self.children[parent] = [c for c in self.children[parent] if c != path]

    def delete(self, *names, **kw):
        for n in names:
            self._delete_recursive(n)

    def directionalLight(self, name=None, intensity=1.0, **kw):
        tname = name or "dirLight"
        self.created.append(("directionalLight", name, intensity))
        transform = self.add_transform(tname)
        return self.add_shape(transform, tname + "Shape", "directionalLight")

    def shadingNode(self, node_type, asTexture=False, name=None, **kw):
        tname = name or node_type
        path = "|" + tname
        self.objects.add(path)
        self.node_type[path] = node_type
        self.parent[path] = None
        self.children.setdefault(path, [])
        self.created.append((node_type, name))
        return path

    def connectAttr(self, src, dst, force=False, **kw):
        self.attrs.setdefault("__connections__", []).append((src, dst))

    def xform(self, name, **kw):
        if kw.get("query"):
            return [0.0, 0.0, 0.0]
        self.attrs.setdefault(name, []).append(kw)

    def setAttr(self, attr, *value, **kw):
        self.attrs[attr] = value

    def rename(self, old, new):
        """Really move the node, subtree and all.

        A stub that returned the new name without renaming anything let a
        cleanup path look correct while sweeping a node that no longer answered
        to the name it was tracking - the fake agreeing with the handler instead
        of behaving like Maya.
        """
        if old not in self.objects:
            return new
        parent = self.parent.get(old)
        new_path = (parent + "|" if parent else "|") + new

        def move(path, target):
            self.objects.discard(path)
            self.objects.add(target)
            self.node_type[target] = self.node_type.pop(path)
            self.parent.pop(path, None)
            kids = self.children.pop(path, [])
            self.children[target] = []
            for kid in kids:
                kid_target = target + "|" + kid.rsplit("|", 1)[-1]
                self.children[target].append(kid_target)
                move(kid, kid_target)
                self.parent[kid_target] = target

        move(old, new_path)
        self.parent[new_path] = parent
        if parent and parent in self.children:
            self.children[parent] = [
                new_path if c == old else c for c in self.children[parent]
            ]
        return new_path


def test_three_point_builds_three_lights(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(lighting, "_cmds", lambda: fake)
    monkeypatch.setattr(lighting, "_auto_checkpoint", lambda reason: None)
    result = lighting.setup_lighting({"preset": "three_point", "replace_existing": False})
    assert result["preset"] == "three_point"
    assert len(result["lights"]) == 3
    assert result["removed"] == []


def test_replace_existing_removes_only_light_transforms(monkeypatch):
    # The dangerous path: this deletes user-authored nodes. It must touch
    # lights and nothing else - not a selection, not a sibling in the group.
    fake = FakeCmds(existing_lights=["oldKeyShape", "oldFillShape"])
    fake.objects.update({"|oldKey", "|oldFill", "|golem", "|camera1"})
    monkeypatch.setattr(lighting, "_cmds", lambda: fake)
    monkeypatch.setattr(lighting, "_auto_checkpoint",
                        lambda reason: {"checkpoint_id": "007_auto_lighting"})
    result = lighting.setup_lighting({"preset": "single_sun", "replace_existing": True})
    assert sorted(result["removed"]) == ["oldFill", "oldKey"]
    assert "|golem" not in fake.deleted
    assert "|camera1" not in fake.deleted
    assert result["checkpoint_id"] == "007_auto_lighting"


def test_replace_existing_spares_a_transform_that_also_holds_a_mesh(monkeypatch):
    # CRITICAL (I1): cmds.delete(transform) deletes the whole subtree. A
    # transform carrying both a light shape and a mesh shape must lose only
    # the light - deleting the transform would take the mesh down with it.
    fake = FakeCmds()
    light_transform = fake.add_transform("oldKey")
    light_shape = fake.add_shape(light_transform, "oldKeyShape", "directionalLight")
    mesh_shape = fake.add_shape(light_transform, "oldKeyMeshShape", "mesh")
    monkeypatch.setattr(lighting, "_cmds", lambda: fake)
    monkeypatch.setattr(lighting, "_auto_checkpoint",
                        lambda reason: {"checkpoint_id": "007_auto_lighting"})

    result = lighting.setup_lighting({"preset": "single_sun", "replace_existing": True})

    assert fake.objExists(light_transform), "the shared transform must survive"
    assert fake.objExists(mesh_shape), "the co-located mesh must survive"
    assert not fake.objExists(light_shape), "the light shape itself must still go"
    assert result["removed"] == [], "the transform was spared, so it is not 'removed'"
    assert any("oldKey" in w for w in result["warnings"]), \
        "a caller who asked to replace lighting deserves to know a node survived"


def test_replace_existing_spares_a_transform_with_a_child_node(monkeypatch):
    # CRITICAL (I1): a transform with a locator (or anything else) parented
    # under it must not lose that child when its light is replaced.
    fake = FakeCmds()
    light_transform = fake.add_transform("oldKey")
    light_shape = fake.add_shape(light_transform, "oldKeyShape", "directionalLight")
    child = fake.add_transform("oldKey_loc", parent=light_transform)
    fake.add_shape(child, "oldKey_locShape", "locator")
    monkeypatch.setattr(lighting, "_cmds", lambda: fake)
    monkeypatch.setattr(lighting, "_auto_checkpoint",
                        lambda reason: {"checkpoint_id": "007_auto_lighting"})

    result = lighting.setup_lighting({"preset": "single_sun", "replace_existing": True})

    assert fake.objExists(light_transform), "the parent transform must survive"
    assert fake.objExists(child), "the child node must survive"
    assert not fake.objExists(light_shape), "the light shape itself must still go"
    assert result["removed"] == []
    assert any("oldKey" in w for w in result["warnings"])


def test_replace_existing_false_takes_no_checkpoint(monkeypatch):
    # Checkpoints are for what undo cannot reach. Additive lighting is
    # ordinary undoable work and must not burn one.
    fake = FakeCmds(existing_lights=["oldKeyShape"])
    monkeypatch.setattr(lighting, "_cmds", lambda: fake)
    calls = []
    monkeypatch.setattr(lighting, "_auto_checkpoint",
                        lambda reason: calls.append(reason))
    lighting.setup_lighting({"preset": "single_sun", "replace_existing": False})
    assert calls == []


def test_hdri_without_a_path_is_rejected(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(lighting, "_cmds", lambda: fake)
    monkeypatch.setattr(lighting, "_auto_checkpoint", lambda reason: None)
    with pytest.raises(HandlerError) as exc:
        lighting.setup_lighting({"preset": "hdri"})
    assert "hdri_path" in str(exc.value) or "hdri_path" in exc.value.hint


def test_unknown_preset_lists_the_valid_ones(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(lighting, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        lighting.setup_lighting({"preset": "cinematic"})
    assert "three_point" in exc.value.hint


def test_invalid_preset_burns_no_checkpoint(monkeypatch):
    # Same discipline M1 established for sculpt_ops/remesh: validate fully
    # before spending a checkpoint.
    fake = FakeCmds(existing_lights=["oldKeyShape"])
    monkeypatch.setattr(lighting, "_cmds", lambda: fake)
    calls = []
    monkeypatch.setattr(lighting, "_auto_checkpoint",
                        lambda reason: calls.append(reason))
    with pytest.raises(HandlerError):
        lighting.setup_lighting({"preset": "nope", "replace_existing": True})
    assert calls == []
    assert fake.deleted == []


def test_build_three_point_sweeps_in_flight_light_on_xform_failure(monkeypatch):
    # IMPORTANT: _build must record a created light's transform BEFORE the
    # xform() call that can fail on it, mirroring _build_hdri. If it records
    # only after xform succeeds, a failure on light N leaves lights 1..N-1
    # swept but light N itself - already created via directionalLight() -
    # never makes it into `created`, so it leaks as an orphan.
    fake = FakeCmds()
    monkeypatch.setattr(lighting, "_cmds", lambda: fake)
    monkeypatch.setattr(lighting, "_auto_checkpoint", lambda reason: None)
    before = set(fake.objects)

    real_xform = fake.xform
    calls = []

    def _flaky_xform(name, **kw):
        calls.append(name)
        if len(calls) == 2:
            raise RuntimeError("forced xform failure")
        return real_xform(name, **kw)

    monkeypatch.setattr(fake, "xform", _flaky_xform)

    with pytest.raises(RuntimeError, match="forced xform failure"):
        lighting.setup_lighting({"preset": "three_point", "replace_existing": False})

    assert fake.objects == before, \
        "the in-flight second light must be swept too, not just the completed first light"


def test_build_hdri_sweeps_orphans_on_forced_connect_failure(monkeypatch, tmp_path):
    # IMPORTANT (I2): _build_hdri creates a light, then a file texture, then
    # connects them - a failure on the connect must not leave either behind.
    fake = FakeCmds()
    monkeypatch.setattr(lighting, "_cmds", lambda: fake)

    def _boom(*args, **kw):
        raise RuntimeError("forced connectAttr failure")

    monkeypatch.setattr(fake, "connectAttr", _boom)
    before = set(fake.objects)

    with pytest.raises(RuntimeError, match="forced connectAttr failure"):
        lighting.setup_lighting({
            "preset": "hdri",
            "hdri_path": str(tmp_path / "sky.hdr"),
            "replace_existing": False,
        })

    assert fake.objects == before, \
        "the orphaned light + file texture must be swept on failure"


class TestEnvironmentDome:
    """metalness = 1.0 renders BLACK in a three-point rig.

    A full metal has no diffuse response and three directional lights give it
    nothing to reflect, so the kit's steel was being judged in a rig that
    physically cannot show it. No intensity fixes that; only an environment can.
    """

    @staticmethod
    def _fake(monkeypatch, **kwargs):
        fake = FakeCmds()
        for key, value in kwargs.items():
            setattr(fake, key, value)
        monkeypatch.setattr(lighting, "_cmds", lambda: fake)
        monkeypatch.setattr(lighting, "_auto_checkpoint", lambda reason: None)
        return fake

    def test_environment_builds_a_real_arnold_dome(self, monkeypatch):
        fake = self._fake(monkeypatch)
        result = lighting.setup_lighting({"preset": "environment"})
        assert result["warnings"] == []
        assert [c for c in fake.created if c[0] == "aiSkyDomeLight"]
        assert len(result["lights"]) == 1

    def test_it_loads_mtoa_rather_than_making_the_caller_do_it(self, monkeypatch):
        """A cold Maya has mtoa installed and unloaded. Making the caller load a
        plugin to use the tool's own preset is a defect, not their mistake."""
        fake = self._fake(monkeypatch)
        assert fake.mtoa_loaded is False
        lighting.setup_lighting({"preset": "environment"})
        assert fake.mtoa_loaded is True

    def test_a_bare_dome_gets_a_horizon_not_flat_grey(self, monkeypatch):
        """A FLAT grey dome lights a metal evenly and it still reads as grey
        paint. The horizon line is what makes a mirror legible as a mirror."""
        fake = self._fake(monkeypatch)
        lighting.setup_lighting({"preset": "environment"})
        assert [c for c in fake.created if c[0] == "ramp"]
        ramp = "|mcpLight_domeRamp"
        assert fake.attrs[ramp + ".type"] == (0,)  # V ramp
        assert fake.attrs[ramp + ".colorEntryList[0].color"] == lighting.DEFAULT_GROUND
        assert fake.attrs[ramp + ".colorEntryList[3].color"] == lighting.DEFAULT_SKY

    def test_an_hdri_is_read_raw_and_mapped_latlong(self, monkeypatch):
        """An HDRI is lighting DATA: an sRGB curve on it changes every
        reflection and every bounce. And the dome's default projection is not
        the one every HDRI a caller owns is authored in."""
        fake = self._fake(monkeypatch)
        lighting.setup_lighting({"preset": "hdri", "hdri_path": "D:/studio.hdr"})
        tex = "|mcpLight_domeTex"
        assert fake.attrs[tex + ".colorSpace"] == ("Raw",)
        assert fake.attrs[tex + ".ignoreColorSpaceFileRules"] == (True,)
        dome = [n for n, t in fake.node_type.items() if t == "aiSkyDomeLight"][0]
        assert fake.attrs[dome + ".format"] == (2,)  # latlong

    def test_without_arnold_it_says_the_metal_will_still_be_wrong(self, monkeypatch):
        """The old hdri preset was a directional light with a texture on its
        colour - a coloured lamp, not image-based lighting. It survives only as
        a fallback, and it no longer pretends."""
        fake = self._fake(monkeypatch, mtoa_installed=False)
        result = lighting.setup_lighting({"preset": "environment"})
        assert len(result["lights"]) == 1
        assert not [c for c in fake.created if c[0] == "aiSkyDomeLight"]
        assert any("metallic material will still render black" in w
                   for w in result["warnings"])

    def test_hdri_without_a_path_points_at_the_no_file_preset(self, monkeypatch):
        self._fake(monkeypatch)
        with pytest.raises(HandlerError) as exc:
            lighting.setup_lighting({"preset": "hdri"})
        assert "environment" in exc.value.hint

    def test_replace_existing_removes_a_previous_dome(self, monkeypatch):
        """A dome that survives replace_existing quietly doubles the lighting of
        every rig built after it - and ls(type='light') cannot see one."""
        fake = self._fake(monkeypatch)
        lighting.setup_lighting({"preset": "environment"})
        domes_before = [n for n, t in fake.node_type.items()
                        if t == "aiSkyDomeLight"]
        assert len(domes_before) == 1
        result = lighting.setup_lighting({"preset": "three_point"})
        assert result["removed"], "the old dome was left behind"
        assert not [n for n, t in fake.node_type.items() if t == "aiSkyDomeLight"]

    def test_light_shapes_survives_a_maya_without_mtoa(self, monkeypatch):
        fake = self._fake(monkeypatch, mtoa_installed=False)
        fake.add_light("keyShape")
        assert lighting.light_shapes(fake) == ["|key|keyShape"]


class TestFullyLitUnit:
    """#617: intensity 1.0 must mean a surface facing the key reads its own
    albedo. Arnold's distant light returns albedo/pi at 1.0, and VP2 does the
    same (both measured live), so the tool carries the pi and the caller states
    a picture instead of guessing a number.
    """

    @staticmethod
    def _fake(monkeypatch, **kwargs):
        fake = FakeCmds()
        for key, value in kwargs.items():
            setattr(fake, key, value)
        monkeypatch.setattr(lighting, "_cmds", lambda: fake)
        monkeypatch.setattr(lighting, "_auto_checkpoint", lambda reason: None)
        return fake

    @staticmethod
    def _built(fake):
        """(name, intensity) per directional light created.

        FakeCmds.directionalLight records ("directionalLight", name, intensity);
        createNode records a 2-tuple, hence the star-unpack.
        """
        return [(name, rest[0]) for kind, name, *rest in fake.created
                if kind == "directionalLight"]

    def test_a_single_sun_at_one_is_a_fully_lit_surface(self, monkeypatch):
        fake = self._fake(monkeypatch)
        lighting.setup_lighting({"preset": "single_sun", "intensity": 1.0,
                                 "replace_existing": False})
        assert self._built(fake)[0][1] == pytest.approx(math.pi)

    def test_the_key_carries_the_factor_and_the_ratios_are_unchanged(self, monkeypatch):
        fake = self._fake(monkeypatch)
        lighting.setup_lighting({"preset": "three_point", "intensity": 2.0,
                                 "replace_existing": False})
        built = [i for _, i in self._built(fake)]
        assert built[0] == pytest.approx(2.0 * math.pi)
        # only the UNIT moves: key/fill/rim keep the rig's shape
        assert built[1] / built[0] == pytest.approx(0.35)
        assert built[2] / built[0] == pytest.approx(0.7)

    def test_the_dome_does_not_get_the_factor(self, monkeypatch):
        # A hemisphere of uniform luminance already integrates to albedo * L.
        # Measured: environment at 1.0 lights the plane to ~122, where a
        # pi-divided dome would be ~88.
        fake = self._fake(monkeypatch)
        result = lighting.setup_lighting({"preset": "environment", "intensity": 1.0,
                                          "replace_existing": False})
        dome = result["lights"][0]
        intensity = [v for a, v in fake.attrs.items()
                     if a.startswith(dome) and a.endswith(".intensity")]
        assert intensity and intensity[0] == (1.0,)

    def test_the_no_arnold_fallback_matches_the_dome_it_stands_in_for(self, monkeypatch):
        # Without the factor a Maya lacking mtoa renders three times darker than
        # one that has it, for the same call - a silent difference.
        fake = self._fake(monkeypatch, mtoa_installed=False)
        lighting.setup_lighting({"preset": "environment", "intensity": 1.0,
                                 "replace_existing": False})
        assert self._built(fake)[0][1] == pytest.approx(math.pi)
