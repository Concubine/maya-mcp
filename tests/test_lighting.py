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

    #799. The three rules, wherever this fake models the call at all:

      1. a query - OR A WRITE - aimed at a node this scene does not hold
         RAISES the way Maya does; `objExists` is the one exception.
         replace_existing deletes nodes and _build_dome renames one, so this
         is the file where a call can meet a name that stopped answering.
      2. `setAttr` and `xform` refuse a plug a connection feeds - the dome's
         `.color` is a connected plug the moment its ramp is wired. The
         refusal follows the node through a rename and CLEARS when the
         source is deleted, so a re-light can rebuild at the same path.
      3. nothing answers unconditionally. `nodeType` answered "unknown" for
         every node it had never heard of, and `objExists` compared a name
         against LONG PATHS only - so `mcpLight_domeRamp` never looked taken,
         naming.unique_name handed the same name back every time and the
         fake quietly overwrote one node with the next. `ls` with no type
         flag answered [] to every name, which is an answer no real ls gives.
    """

    _LIGHT_TYPES = {"directionalLight", "pointLight", "spotLight", "areaLight", "light"}

    # Maya hands back the SHAPE from shadingNode(asLight=True) in some
    # versions and the auto-created TRANSFORM in others - _build_dome
    # normalises for both. This fake returned the shape unconditionally, so
    # the transform half of that normalisation was dead code under test.
    shading_node_returns_transform = False

    def __init__(self, existing_lights=()):
        self.deleted = []
        self.created = []
        # destination plug -> source plug, as connectAttr wires it. A plug in
        # here is unwritable by setAttr or xform (#799 contract point 2).
        self.connections = {}
        self.locked = set()
        # Every node built through shadingNode(asLight=True). Tracked separately
        # from `created` because WHICH command built a light is the whole
        # difference between one that lights and one that only draws.
        self.as_light = []
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

    # -- resolution --
    def _matches(self, name):
        """`ls`'s answer for a name: Maya resolves a SHORT name as readily as
        a long path, which is the whole basis of naming.unique_name."""
        return sorted(n for n in self.objects
                      if n == name or n.split("|")[-1] == name)

    def _require(self, name):
        if not self._matches(name):
            raise RuntimeError("No object matches name: %s" % name)

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
        if not args:
            return sorted(self.objects)
        return sorted({m for a in args for m in self._matches(a)})

    # -- mtoa, which is installed-but-unloaded on a cold Maya --
    mtoa_installed = True
    mtoa_loaded = False

    def pluginInfo(self, name, query=False, loaded=False, **kw):
        if loaded:
            return self.mtoa_loaded
        # #799 round 2: the trailing `return None` answered every OTHER query
        # flag - version, path, registered - with "no", which is an answer,
        # not an absence. Refuse what this fake has not been taught.
        raise AssertionError(
            "unmodelled pluginInfo(%r, query=%r, %r)" % (name, query, sorted(kw)))

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
        self._require(node)
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
        return bool(self._matches(name))

    def _delete_recursive(self, path):
        if path not in self.objects:
            return
        for child in list(self.children.get(path, [])):
            self._delete_recursive(child)
        self.deleted.append(path)
        self.objects.discard(path)
        # #799 round 2: a deleted node takes its connections with it, both
        # ways. Leaving them behind made the setAttr refusal PERMANENT - a
        # dome rebuilt at the same path after a re-light was refused a write
        # to `.color` forever, which manufactures a failure Maya never has.
        self.connections = {
            dst: src for dst, src in self.connections.items()
            if dst.split(".")[0] != path and src.split(".")[0] != path
        }
        self.node_type.pop(path, None)
        parent = self.parent.pop(path, None)
        self.children.pop(path, None)
        if parent and parent in self.children:
            self.children[parent] = [c for c in self.children[parent] if c != path]

    def delete(self, *names, **kw):
        for n in names:
            self._require(n)
            self._delete_recursive(self._matches(n)[0])

    def directionalLight(self, name=None, intensity=1.0, **kw):
        tname = name or "dirLight"
        self.created.append(("directionalLight", name, intensity))
        transform = self.add_transform(tname)
        return self.add_shape(transform, tname + "Shape", "directionalLight")

    def shadingNode(self, node_type, asTexture=False, asLight=False, name=None, **kw):
        if asLight:
            # A light is a DAG node: Maya parents the shape under an
            # auto-created transform and hands back the shape, exactly as
            # createNode does. The difference is invisible here and decisive in
            # a render - see test_the_dome_is_created_as_a_light.
            shape_name = name or (node_type + "Shape1")
            transform = self.add_transform(shape_name.replace("Shape", "") + "_xf")
            self.created.append((node_type, name))
            self.as_light.append((node_type, name))
            shape = self.add_shape(transform, shape_name, node_type)
            # Which of the two Maya hands back is a version difference, and
            # _build_dome claims to survive either (#799 point 3).
            return transform if self.shading_node_returns_transform else shape
        tname = name or node_type
        path = "|" + tname
        self.objects.add(path)
        self.node_type[path] = node_type
        self.parent[path] = None
        self.children.setdefault(path, [])
        self.created.append((node_type, name))
        return path

    def listConnections(self, node, source=False, destination=True,
                        plugs=False, type=None, **kw):
        """#804: what feeds a plug (or any plug on a bare node), and what a
        node feeds - the two questions orphans.upstream_network and
        orphans.real_outputs ask. Answered from the same dst -> src map
        connectAttr writes and delete clears; None when nothing, as Maya."""
        self._require(node.split(".")[0])
        assert type is None, "typed listConnections is not modelled here"
        bare = "." not in node
        if source and not destination:
            srcs = [src for dst, src in self.connections.items()
                    if (dst.split(".")[0] == node if bare else dst == node)]
            return (srcs if plugs else
                    list(dict.fromkeys(s.split(".")[0] for s in srcs))) or None
        if destination and not source:
            dsts = [dst for dst, src in self.connections.items()
                    if (src.split(".")[0] == node if bare else src == node)]
            return (dsts if plugs else
                    list(dict.fromkeys(d.split(".")[0] for d in dsts))) or None
        raise AssertionError("unmodelled listConnections direction")

    def nodeType(self, node):
        self._require(node)
        # A node the fixture built without a recorded type is a plain
        # transform, which is what Maya would call it - "unknown" was an
        # answer no scene ever gives.
        return self.node_type.get(node, "transform")

    def connectAttr(self, src, dst, force=False, **kw):
        # #799 round 2: contract point 1 stopped at the read/write boundary -
        # a connectAttr aimed at a stale pre-rename path (the #796 shape, and
        # exactly what _build_dome would leave if its re-resolve went away)
        # was RECORDED as a success. Maya raises for either end.
        self._require(src.split(".")[0])
        self._require(dst.split(".")[0])
        self.attrs.setdefault("__connections__", []).append((src, dst))
        if force:
            self.connections.pop(dst, None)
        self.connections[dst] = src

    def _blocker(self, plug):
        """The connection or lock that makes `plug` unwritable, or None.

        Maya's compound/child asymmetry, both directions: `rotate` refuses
        when only `rotateY` is driven, and `rotateY` refuses when the whole
        compound is.
        """
        fed = set(self.connections) | self.locked
        if plug in fed:
            return plug
        node, _, attr = plug.rpartition(".")
        for suffix in ("R", "G", "B", "X", "Y", "Z"):
            if "%s.%s%s" % (node, attr, suffix) in fed:
                return "%s.%s%s" % (node, attr, suffix)
        if attr[-1:] in ("R", "G", "B", "X", "Y", "Z"):
            parent = "%s.%s" % (node, attr[:-1])
            if parent in fed:
                return parent
        return None

    def xform(self, name, **kw):
        self._require(name)
        if kw.get("query"):
            # #799 round 2: this used to answer [0,0,0] to EVERY query flag -
            # a pivot, a bounding box, a matrix - which is a made-up answer,
            # and lighting.py asks none of them. Refuse until one is taught.
            raise AssertionError(
                "unmodelled xform query(%r, %r)" % (name, sorted(kw)))
        # An xform is a STATIC WRITE to the same plugs setAttr refuses: a
        # light whose rotation an expression or a constraint drives cannot be
        # swung by the rig builder (#799 contract point 2).
        for flag, plug_attr in (("rotation", "rotate"),
                                ("translation", "translate"),
                                ("scale", "scale")):
            if kw.get(flag) is None:
                continue
            blocker = self._blocker("%s.%s" % (name, plug_attr))
            if blocker:
                raise RuntimeError(
                    "xform: The attribute '%s' is locked or connected and "
                    "cannot be modified" % blocker
                )
        self.attrs.setdefault(name, []).append(kw)

    def setAttr(self, attr, *value, **kw):
        # #799 round 2: lighting.py:348 writes the dome's intensity onto a
        # shape it re-resolved two lines earlier. Delete that re-resolve and
        # the write lands on the pre-rename path - which this fake used to
        # RECORD as a success. In Maya it raises "No object matches name".
        self._require(attr.split(".")[0])
        blocker = self._blocker(attr)
        if blocker:
            raise RuntimeError(
                "setAttr: The attribute '%s' is locked or connected and "
                "cannot be modified." % blocker
            )
        self.attrs[attr] = value

    def rename(self, old, new):
        """Really move the node, subtree and all.

        A stub that returned the new name without renaming anything let a
        cleanup path look correct while sweeping a node that no longer answered
        to the name it was tracking - the fake agreeing with the handler instead
        of behaving like Maya.
        """
        # #799: renaming a node that is not there raises in Maya. Handing the
        # new name back regardless is the same answers-anything shape as the
        # stub this docstring already warns about.
        self._require(old)
        old = self._matches(old)[0]
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

        # A rename rewrites every plug name that referenced the node, so a
        # connection recorded against the OLD path has to follow it - or the
        # fake keeps a write-block on a name nothing answers to any more
        # while the live node's plug looks free (#799 round 2).
        def follow(plug):
            node, dot, attr = plug.partition(".")
            if node == old:
                node = new_path
            elif node.startswith(old + "|"):
                node = new_path + node[len(old):]
            return node + dot + attr

        self.connections = {follow(d): follow(s)
                            for d, s in self.connections.items()}
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

    def test_the_dome_is_created_as_a_light_not_a_bare_node(self, monkeypatch):
        """createNode builds the node but never wires it into Maya's lighting
        network, so the dome draws as BACKGROUND and illuminates nothing.

        Measured in a live Maya during the #601 run, and it took a probe to
        believe it: a plain 50%-grey sphere under a createNode dome renders
        PURE BLACK while the dome's own sky blows out behind it, at intensity
        1.0 and at 4.0 alike. The same sphere under a stock
        shadingNode(asLight=True) dome renders correctly. Setting colour,
        intensity, defaultLightSet membership and even the lightList connection
        on the createNode dome afterwards fixes none of it - the node has to be
        BUILT as a light.

        This is the preset the tool's own docs call REQUIRED for metal, so
        every metallic material ever judged through it was judged unlit.
        """
        fake = self._fake(monkeypatch)
        lighting.setup_lighting({"preset": "environment"})
        assert [c for c in fake.as_light if c[0] == "aiSkyDomeLight"], (
            "the dome must be built with shadingNode(asLight=True); createNode "
            "produces a dome that renders as background and lights nothing"
        )

    def test_an_hdri_dome_is_a_light_too(self, monkeypatch):
        """Same defect, same fix: hdri and environment share _build_dome, so an
        HDRI dome was equally inert."""
        fake = self._fake(monkeypatch)
        lighting.setup_lighting({"preset": "hdri", "hdri_path": "D:/studio.hdr"})
        assert [c for c in fake.as_light if c[0] == "aiSkyDomeLight"]

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

    def test_a_maya_that_hands_back_the_transform_gets_the_same_dome(self, monkeypatch):
        """#799 contract point 3. _build_dome normalises both of Maya's
        answers to shadingNode(asLight=True) - the shape in some versions,
        the auto-created transform in others - and this fake returned the
        shape unconditionally, so the transform half of that normalisation
        had no test at all.
        """
        fake = self._fake(monkeypatch, shading_node_returns_transform=True)
        result = lighting.setup_lighting({"preset": "environment",
                                          "intensity": 1.0})
        assert result["lights"] == ["|mcpLight_dome"]
        # the intensity landed on the SHAPE, not on the transform it came in as
        assert fake.attrs["|mcpLight_dome|mcpLight_domeShape.intensity"] == (1.0,)
        assert [c for c in fake.as_light if c[0] == "aiSkyDomeLight"]

    def test_replacing_a_dome_takes_its_ramp_with_it(self, monkeypatch):
        # #804 MEASURED: deleting the dome's shape and transform leaves its
        # ramp with defaultTextureList1 as its one consumer, and Maya never
        # reaps it. replace_existing captures what fed each light's colour
        # before the delete and sweeps it after.
        fake = self._fake(monkeypatch)
        lighting.setup_lighting({"preset": "environment"})
        result = lighting.setup_lighting({"preset": "environment"})
        ramps = sorted(n for n, t in fake.node_type.items() if t == "ramp")
        assert ramps == ["|mcpLight_domeRamp"], ramps
        assert "mcpLight_domeRamp" in result["removed"]
        assert fake.connections.get("|mcpLight_dome|mcpLight_domeShape.color") \
            == "|mcpLight_domeRamp.outColor"

    def test_a_ramp_something_else_still_uses_survives_the_relight(self, monkeypatch):
        # The sweep is about consumers, not authorship: a ramp the user also
        # wired somewhere else is kept, and named.
        fake = self._fake(monkeypatch)
        lighting.setup_lighting({"preset": "environment"})
        keeper = fake.shadingNode("lambert", asShader=True, name="keeper")
        fake.connectAttr("|mcpLight_domeRamp.outColor", keeper + ".color")
        result = lighting.setup_lighting({"preset": "environment"})
        assert "|mcpLight_domeRamp" in fake.objects
        assert "mcpLight_domeRamp" not in result["removed"]
        assert any("mcpLight_domeRamp" in w and "still used" in w
                   for w in result["warnings"])


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



class TestTheFakeRefusesWhatMayaRefuses:
    """#799 round 2: the hardening in FakeCmds has to be ASSERTED somewhere.

    Reverting every behavioural change in the fake left this suite fully
    green, because not one test exercised the new refusals - "a green suite
    proves nothing", one level up. These pin the contract points this fake
    actually models, so loosening it goes red here first.
    """

    def _dome(self):
        """_build_dome's own opening sequence: a light shape under an
        auto-created transform, then the transform renamed."""
        fake = FakeCmds()
        shape = fake.shadingNode("aiSkyDomeLight", asLight=True,
                                 name="mcpLight_domeShape")
        transform = fake.listRelatives(shape, parent=True, fullPath=True)[0]
        fake.rename(transform, "mcpLight_dome")
        return fake, shape

    def _lit_dome(self):
        """...and its ramp wired into the shape's colour."""
        fake, _ = self._dome()
        shape = fake.listRelatives("|mcpLight_dome", shapes=True,
                                   fullPath=True)[0]
        ramp = fake.shadingNode("ramp", asTexture=True, name="mcpLight_domeRamp")
        fake.connectAttr(ramp + ".outColor", shape + ".color", force=True)
        return fake, shape, ramp

    # -- point 1: a name that stopped answering ---------------------------
    def test_every_query_about_a_node_that_never_existed_raises(self):
        fake = FakeCmds()
        fake.add_light("keyShape")
        for call in (lambda: fake.nodeType("|ghost"),
                     lambda: fake.listRelatives("|ghost", parent=True,
                                                fullPath=True),
                     lambda: fake.xform("|ghost", rotation=(0, 0, 0),
                                        worldSpace=True),
                     lambda: fake.rename("|ghost", "haunt"),
                     lambda: fake.delete("|ghost")):
            with pytest.raises(RuntimeError, match="No object matches name"):
                call()
        assert fake.objExists("|ghost") is False  # the question that answers

    def test_a_write_aimed_at_a_stale_pre_rename_path_raises(self):
        # The half of contract point 1 the first pass left out, and the sharp
        # case: this is lighting.py:348's write with the re-resolve at
        # 346-347 removed - the #796 shape, recorded as a success before.
        fake, stale = self._dome()
        assert fake.objExists(stale) is False
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.setAttr(stale + ".intensity", 4.0)
        ramp = fake.shadingNode("ramp", asTexture=True, name="mcpLight_domeRamp")
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.connectAttr(ramp + ".outColor", stale + ".color", force=True)

    def test_the_renamed_node_takes_the_write_instead(self):
        # The other direction: the re-resolved path really is writable, so
        # the refusal above is about the stale name, not about strictness.
        fake, _ = self._dome()
        shape = fake.listRelatives("|mcpLight_dome", shapes=True,
                                   fullPath=True)[0]
        fake.setAttr(shape + ".intensity", 4.0)
        assert fake.attrs[shape + ".intensity"] == (4.0,)

    # -- point 2: a plug something already drives -------------------------
    def test_setAttr_refuses_a_connected_plug(self):
        fake, shape, _ = self._lit_dome()
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake.setAttr(shape + ".color", 1.0, 1.0, 1.0, type="double3")
        fake.setAttr(shape + ".intensity", 2.0)  # a free plug still writes

    def test_setAttr_refuses_a_compound_whose_child_is_driven(self):
        fake = FakeCmds()
        fake.add_light("keyShape")
        ramp = fake.shadingNode("ramp", asTexture=True, name="skyRamp")
        fake.connectAttr(ramp + ".outColorR", "|key|keyShape.colorG")
        with pytest.raises(RuntimeError, match="keyShape.colorG"):
            fake.setAttr("|key|keyShape.color", 1.0, 1.0, 1.0, type="double3")

    def test_setAttr_refuses_a_child_whose_compound_is_driven(self):
        fake, shape, _ = self._lit_dome()
        with pytest.raises(RuntimeError, match="domeShape.color'"):
            fake.setAttr(shape + ".colorG", 0.5)

    def test_setAttr_refuses_a_locked_plug_with_nothing_connected(self):
        fake = FakeCmds()
        fake.add_light("keyShape")
        fake.locked.add("|key|keyShape.intensity")
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake.setAttr("|key|keyShape.intensity", 3.0)

    def test_xform_refuses_a_driven_rotation_and_lets_a_free_one_through(self):
        fake = FakeCmds()
        fake.add_light("keyShape")
        ramp = fake.shadingNode("ramp", asTexture=True, name="driver")
        fake.connectAttr(ramp + ".outColorR", "|key.rotateY")
        with pytest.raises(RuntimeError, match="key.rotateY"):
            fake.xform("|key", rotation=(-35.0, 40.0, 0.0), worldSpace=True)
        fake.xform("|key", translation=(0.0, 1.0, 0.0), worldSpace=True)
        assert {"translation": (0.0, 1.0, 0.0),
                "worldSpace": True} in fake.attrs["|key"]

    def test_deleting_the_source_frees_the_plug_again(self):
        # The refusal has to CLEAR. A re-light deletes the old dome and
        # rebuilds at the same resolved path; a fake that refuses forever
        # manufactures a failure Maya never has.
        fake, shape, _ = self._lit_dome()
        fake.delete("|mcpLight_dome")
        rebuilt_shape = fake.shadingNode("aiSkyDomeLight", asLight=True,
                                         name="mcpLight_domeShape")
        transform = fake.listRelatives(rebuilt_shape, parent=True,
                                       fullPath=True)[0]
        fake.rename(transform, "mcpLight_dome")
        rebuilt = fake.listRelatives("|mcpLight_dome", shapes=True,
                                     fullPath=True)[0]
        assert rebuilt == shape, "the rebuild landed on the same path"
        fake.setAttr(rebuilt + ".color", 1.0, 1.0, 1.0, type="double3")

    def test_a_rename_carries_the_connection_with_it(self):
        # The mirror of the above: the block follows the node, rather than
        # staying pinned to a name nothing answers to any more.
        fake, _, _ = self._lit_dome()
        fake.rename("|mcpLight_dome", "mcpLight_dome_001")
        moved = fake.listRelatives("|mcpLight_dome_001", shapes=True,
                                   fullPath=True)[0]
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake.setAttr(moved + ".color", 1.0, 1.0, 1.0, type="double3")

    # -- point 3: nothing answers unconditionally -------------------------
    def test_ls_with_no_type_flag_resolves_a_name(self):
        # It used to answer [] to every name, which is an answer no real ls
        # gives - and it is what naming.unique_name reads to pick a suffix.
        fake = FakeCmds()
        fake.add_light("keyShape")
        assert fake.ls("key", long=True) == ["|key"]
        assert fake.ls("|key|keyShape", long=True) == ["|key|keyShape"]
        assert fake.ls("nothing_here", long=True) == []

    def test_nodeType_does_not_answer_unknown_for_a_plain_transform(self):
        fake = FakeCmds()
        fake.add_light("keyShape")
        assert fake.nodeType("|key") == "transform"
        assert fake.nodeType("|key|keyShape") == "directionalLight"
        # ...and a node a fixture put in the scene without recording a type
        # is a plain transform. "unknown" is an answer no real scene gives,
        # and _build_dome branches on nodeType == "aiSkyDomeLight".
        fake.objects.add("|handmade")
        assert fake.nodeType("|handmade") == "transform"

    def test_pluginInfo_and_an_xform_query_refuse_what_they_never_modelled(self):
        fake = FakeCmds()
        fake.add_light("keyShape")
        assert fake.pluginInfo("mtoa", query=True, loaded=True) is False
        with pytest.raises(AssertionError, match="unmodelled pluginInfo"):
            fake.pluginInfo("mtoa", query=True, version=True)
        with pytest.raises(AssertionError, match="unmodelled xform query"):
            fake.xform("|key", query=True, translation=True, worldSpace=True)
