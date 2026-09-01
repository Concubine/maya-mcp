"""assign_material and the semantic-slot map - no Maya required."""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import material


def test_resolve_slot_maps_semantic_names_per_shader():
    assert material.resolve_slot("standardSurface", "color") == "baseColor"
    assert material.resolve_slot("lambert", "color") == "color"
    assert material.resolve_slot("standardSurface", "roughness") == "specularRoughness"
    assert material.resolve_slot("standardSurface", "normal") == "normalCamera"
    assert material.resolve_slot("lambert", "normal") == "normalCamera"


def test_resolve_slot_rejects_a_slot_the_shader_lacks():
    # A texture wired to nothing changes no pixels and looks like success.
    # This must be a loud error, never a silent no-op.
    with pytest.raises(HandlerError) as exc:
        material.resolve_slot("lambert", "roughness")
    assert "lambert" in str(exc.value)
    assert "color" in exc.value.hint


def test_unknown_material_param_is_rejected_with_the_whitelist(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(material, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        material.assign_material({
            "mesh": "|torso", "shader": "standardSurface",
            "params": {"subsurface_radius": 3},
        })
    assert "roughness" in exc.value.hint


def test_assign_creates_shader_and_object_level_sg(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(material, "_cmds", lambda: fake)
    result = material.assign_material({
        "mesh": "|torso", "shader": "standardSurface",
        "params": {"baseColor": [0.4, 0.3, 0.25], "roughness": 0.8},
    })
    assert result["shader"] == "standardSurface"
    assert result["shading_group"].endswith("SG")
    assert ("setAttr", "baseColor") in [
        (c[0], c[1].split(".")[-1]) for c in fake.calls if c[0] == "setAttr"
    ]


def test_bad_param_type_leaves_no_orphan_nodes(monkeypatch):
    # I2: a bad param value must be caught before any node is created, sg
    # built, or the mesh's shading is touched - the scene's node set (and
    # shading-group membership) must be byte-for-byte unchanged after a
    # failed call.
    fake = FakeCmds()
    fake.sg_members["initialShadingGroup"] = ["|torso|torsoShape"]
    monkeypatch.setattr(material, "_cmds", lambda: fake)
    objects_before = set(fake.objects)
    sg_before = {k: list(v) for k, v in fake.sg_members.items()}
    with pytest.raises(HandlerError):
        material.assign_material({
            "mesh": "|torso", "shader": "standardSurface",
            "params": {"baseColor": 0.5},
        })
    assert fake.objects == objects_before, (
        "assign_material left orphan nodes: %s"
        % (fake.objects - objects_before)
    )
    assert fake.sg_members == sg_before, "mesh shading assignment was mutated"


def test_standardSurface_whitelist_includes_gem_optics():
    # F1: transmission/ior are the entire optical identity of a gem - without
    # them every gem is an opaque coloured solid, no matter how faceted.
    assert {"transmission", "transmissionColor", "ior"} <= material.PARAM_WHITELIST[
        "standardSurface"
    ]
    assert material._ATTR["standardSurface"]["transmission"] == "transmission"
    assert material._ATTR["standardSurface"]["transmissionColor"] == "transmissionColor"
    assert material._ATTR["standardSurface"]["ior"] == "specularIOR"
    assert "transmissionColor" in material._COLOR_ATTRS


def test_assign_material_sets_transmission_ior_and_transmission_color(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(material, "_cmds", lambda: fake)
    material.assign_material({
        "mesh": "|torso", "shader": "standardSurface",
        "params": {"transmission": 0.9, "transmissionColor": [0.95, 1.0, 0.98],
                   "ior": 1.5},
    })
    set_attrs = {c[1].split(".")[-1]: c[2] for c in fake.calls if c[0] == "setAttr"}
    assert set_attrs["transmission"] == (0.9,)
    assert set_attrs["specularIOR"] == (1.5,)
    assert set_attrs["transmissionColor"] == (0.95, 1.0, 0.98)


def test_transmission_out_of_range_is_rejected_with_hint(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(material, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        material.assign_material({
            "mesh": "|torso", "shader": "standardSurface",
            "params": {"transmission": 1.5},
        })
    assert "0" in exc.value.hint or "0" in str(exc.value)
    assert fake.calls == []  # refused before anything was built


def test_ior_out_of_range_is_rejected_with_hint(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(material, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        material.assign_material({
            "mesh": "|torso", "shader": "standardSurface",
            "params": {"ior": 5.0},
        })
    assert "1" in str(exc.value) and "3" in str(exc.value)
    assert fake.calls == []


def test_ior_rejects_bool_like_the_other_scalars(monkeypatch):
    # bool is a subclass of int - True/False must not silently pass as 1.0/0.0.
    fake = FakeCmds()
    monkeypatch.setattr(material, "_cmds", lambda: fake)
    with pytest.raises(HandlerError):
        material.assign_material({
            "mesh": "|torso", "shader": "standardSurface",
            "params": {"ior": True},
        })


def test_assign_replaces_an_existing_default_shading_assignment(monkeypatch):
    # Every freshly created Maya mesh already belongs to a default SG
    # (initialShadingGroup / openPBR_shaderSG1) with clean object-level
    # membership - that pre-existing single-SG "healthy" state must not be
    # mistaken for "already wearing my new material" and left alone.
    fake = FakeCmds()
    fake.sg_members["initialShadingGroup"] = ["|torso|torsoShape"]
    monkeypatch.setattr(material, "_cmds", lambda: fake)
    result = material.assign_material({
        "mesh": "|torso", "shader": "lambert", "params": {"color": [1, 0, 0]},
    })
    new_sg = result["shading_group"]
    assert new_sg == result["material"] + "SG"
    assert "|torso|torsoShape" in fake.sg_members[new_sg]
    assert "|torso|torsoShape" not in fake.sg_members["initialShadingGroup"]


def test_assign_material_reuses_existing_shader_of_the_same_type(monkeypatch):
    # F4: three iterations of one-material-per-mesh left ~108 dead shaders for
    # eight distinct gems. Passing the same name for a second mesh must reuse
    # the shader, not mint a uniquified variant.
    fake = FakeCmds()
    monkeypatch.setattr(material, "_cmds", lambda: fake)
    first = material.assign_material({
        "mesh": "|torso", "shader": "standardSurface",
        "params": {"baseColor": [0.2, 0.6, 0.9]}, "name": "shared_gem",
    })
    fake.objects.add("|arm")
    fake.shapes["|arm"] = ("|arm|armShape", "mesh")
    second = material.assign_material({
        "mesh": "|arm", "shader": "standardSurface",
        "params": {"transmission": 0.8}, "name": "shared_gem",
    })
    assert first["material"] == "shared_gem"
    assert second["material"] == "shared_gem"
    shader_nodes = [c for c in fake.calls if c[0] == "shadingNode"]
    assert len(shader_nodes) == 1, "a second shader was minted: %s" % shader_nodes
    # both meshes actually wear the one shader's shading group
    sg = first["shading_group"]
    assert "|torso|torsoShape" in fake.sg_members[sg]
    assert "|arm|armShape" in fake.sg_members[sg]


def test_assign_material_reuse_applies_new_params_to_the_existing_shader(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(material, "_cmds", lambda: fake)
    material.assign_material({
        "mesh": "|torso", "shader": "standardSurface",
        "params": {"baseColor": [0.2, 0.6, 0.9]}, "name": "shared_gem",
    })
    fake.objects.add("|arm")
    fake.shapes["|arm"] = ("|arm|armShape", "mesh")
    material.assign_material({
        "mesh": "|arm", "shader": "standardSurface",
        "params": {"transmission": 0.8}, "name": "shared_gem",
    })
    set_attrs = [c for c in fake.calls if c[0] == "setAttr" and c[1] == "shared_gem.transmission"]
    assert set_attrs, "reuse must still apply the caller's params to the shader"


def test_assign_material_refuses_to_reuse_a_non_shader_node(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(material, "_cmds", lambda: fake)
    fake.objects.add("not_a_shader")  # a transform, never typed as a shader
    with pytest.raises(HandlerError) as exc:
        material.assign_material({
            "mesh": "|torso", "shader": "standardSurface",
            "params": {}, "name": "not_a_shader",
        })
    assert "not_a_shader" in str(exc.value)


def test_assign_material_refuses_to_reuse_a_shader_of_a_different_type(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(material, "_cmds", lambda: fake)
    material.assign_material({
        "mesh": "|torso", "shader": "lambert",
        "params": {"color": [0.5, 0.5, 0.5]}, "name": "wrong_type_mat",
    })
    fake.objects.add("|arm")
    fake.shapes["|arm"] = ("|arm|armShape", "mesh")
    with pytest.raises(HandlerError) as exc:
        material.assign_material({
            "mesh": "|arm", "shader": "standardSurface",
            "params": {}, "name": "wrong_type_mat",
        })
    assert "lambert" in str(exc.value) and "standardSurface" in str(exc.value)


class FakeCmds:
    """One mesh transform plus whatever shading network gets built on it.

    #799, the three rules, applied wherever this fake models the call at all:

      1. a query - OR A WRITE - aimed at a node this scene does not hold
         RAISES the way Maya does; `objExists` is the one exception.
         Deletions are tracked so a node that vanished stops answering, and
         a name used again afterwards is a NEW node, not a tombstone.
      2. `setAttr` refuses a plug a connection feeds, and a compound whose
         CHILD is fed refuses too. This is not decoration: assign_material's
         REUSE path writes params straight onto a shader that a texture may
         already drive, which is precisely the plug Maya refuses. The
         refusal CLEARS when the source node is deleted - a fake that
         refuses forever manufactures failures Maya never has.
      3. nothing answers unconditionally. `nodeType` used to hand back "mesh"
         for every node it had never heard of, so require_mesh's shape check
         could not fail here and the reuse-vs-collide branch that reports
         "it is a <type>" reported a type nobody had set.

    `ls` resolves SHAPES as well as transforms, because Maya's does and
    meshcheck.ensure_object_shading compares its answer against a shape long
    name to decide whether the mesh's shading is healthy.
    """

    # A colour/vector compound's children, for the refusal in _blocker.
    _CHILD_SUFFIXES = ("R", "G", "B", "X", "Y", "Z")

    def __init__(self):
        self.objects = {"|torso"}
        self.shapes = {"|torso": ("|torso|torsoShape", "mesh")}
        self.calls = []
        # sg name -> list of member long names; mirrors real Maya's shape-to-SG
        # sets membership, including whatever default SG a mesh starts in.
        self.sg_members = {}
        # node name -> node type, for pre-seeded/created non-mesh nodes (shaders,
        # transforms) so nodeType() can tell a shader from a transform from a
        # shader-of-the-wrong-type - the reuse-vs-collide checks all hinge on it.
        self.node_types = {}
        # shader node -> its shading group, populated by connectAttr(outColor ->
        # surfaceShader) exactly as real Maya wires it; reuse lookup depends on
        # being able to find an existing shader's SG the same way real code does.
        self.shader_to_sg = {}
        self.deleted = []           # every name delete() has taken away
        # destination plug -> source plug, as connectAttr wires it. A plug in
        # here is unwritable (#799 contract point 2).
        self.connections = {}
        self.locked = set()         # plugs locked rather than connected

    # --- resolution ------------------------------------------------------
    def _live(self):
        names = set(self.objects) | {s for s, _ in self.shapes.values()}
        return names - set(self.deleted)

    def _matches(self, name):
        return sorted(n for n in self._live()
                      if n == name or n.split("|")[-1] == name)

    def _require(self, name):
        if not self._matches(name):
            raise RuntimeError("No object matches name: %s" % name)

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

    # --- writes ----------------------------------------------------------
    def _born(self, name):
        """Register a node. A name that was deleted and is now used again is a
        NEW node, not a resurrection - without this the `deleted` list is a
        permanent tombstone and a rebuilt node at the same name is invisible
        for the rest of the run, which is the strict mirror of a fake that
        answers anything (#799 round 2).
        """
        self.objects.add(name)
        self.deleted = [d for d in self.deleted if d != name]

    def shadingNode(self, node_type, asShader=False, name=None, **kw):
        self.calls.append(("shadingNode", node_type, name))
        self._born(name)
        self.node_types[name] = node_type
        return name

    def delete(self, *names, **kw):
        for name in names:
            self._require(name)
            resolved = self._matches(name)[0]
            self.deleted.append(resolved)
            self.objects.discard(resolved)
            # Maya's delete takes the whole subtree: a transform's shape goes
            # with it (#799 round 2, copied from test_naming.py).
            entry = self.shapes.get(resolved)
            if entry:
                self.deleted.append(entry[0])
            # ...and it takes the node's connections with it, both ways. A
            # plug whose source node has died is FREE in Maya; leaving the
            # entry behind made the setAttr refusal below permanent, which
            # manufactures failures instead of modelling the scene.
            for dst, src in list(self.connections.items()):
                if (dst.split(".")[0] == resolved
                        or src.split(".")[0] == resolved):
                    del self.connections[dst]

    def sets(self, *args, **kw):
        if kw.get("renderable"):
            name = kw.get("name")
            self.calls.append(("sets", name))
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
            self.calls.append(("sets", "forceElement", shape, target))
            return []
        # #799 round 2: the trailing `return []` that used to sit here
        # answered ANY other flag combination - `sets(node, edit=True,
        # remove=...)` included - blind, and for a deleted node at that.
        raise AssertionError(
            "unmodelled sets(%r, %r): teach the fake what Maya answers "
            "before a handler relies on it" % (args, sorted(kw)))

    def connectAttr(self, src, dst, force=False):
        # #799 round 2: contract point 1 stopped at the read/write boundary -
        # a connectAttr aimed at a name that stopped answering (a stale
        # pre-rename path, a deleted node) was RECORDED as a success.
        self._require(src.split(".")[0])
        self._require(dst.split(".")[0])
        self.calls.append(("connectAttr", src, dst))
        self.connections[dst] = src
        if dst.endswith(".surfaceShader") and src.endswith(".outColor"):
            self.shader_to_sg[src[: -len(".outColor")]] = dst[: -len(".surfaceShader")]

    def _blocker(self, plug):
        """The connection or lock that makes `plug` unwritable, or None.

        Maya's compound/child asymmetry, both directions: writing baseColor
        is refused when baseColorG alone is driven, and writing baseColorG is
        refused when the whole compound is.
        """
        fed = set(self.connections) | self.locked
        if plug in fed:
            return plug
        node, _, attr = plug.rpartition(".")
        for suffix in self._CHILD_SUFFIXES:
            child = "%s.%s%s" % (node, attr, suffix)
            if child in fed:
                return child
        if attr[-1:] in self._CHILD_SUFFIXES:
            parent = "%s.%s" % (node, attr[:-1])
            if parent in fed:
                return parent
        return None

    def setAttr(self, attr, *value, **kw):
        # #799 round 2: a write to a node the scene does not hold raises "No
        # object matches name" in Maya, exactly as a read does. Recording it
        # as a success is how a handler that skipped a re-resolve after a
        # rename (the #796 shape) stayed invisible here.
        self._require(attr.split(".")[0])
        blocker = self._blocker(attr)
        if blocker:
            raise RuntimeError(
                "setAttr: The attribute '%s' is locked or connected and "
                "cannot be modified." % blocker
            )
        self.calls.append(("setAttr", attr, value))

    def _pairs(self):
        return [(src, dst) for dst, src in self.connections.items()]

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
            # This used to answer [] to every shape however wired - a fake
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


def test_assign_material_refuses_the_material_synonym(monkeypatch):
    # #764. `material` is the name the result reports back, so it reads like
    # the obvious input key - and it was silently ignored, handing back a
    # mesh-derived default name instead. Refusal over guessing: an alias
    # would keep two spellings alive for the same idea.
    fake = FakeCmds()
    monkeypatch.setattr(material, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        material.assign_material({
            "mesh": "|torso", "shader": "lambert", "material": "clay",
        })
    assert "does not take 'material'" in str(exc.value)
    assert "'name'" in exc.value.hint
    # and nothing was built before the refusal
    assert fake.calls == []


def test_assign_material_still_takes_every_key_it_reads(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(material, "_cmds", lambda: fake)
    result = material.assign_material({
        "mesh": "|torso", "shader": "lambert", "name": "clay",
        "params": {"color": [1, 0, 0]},
    })
    assert result["material"] == "clay"


def test_reusing_a_shader_that_was_built_without_an_sg_gives_it_one(monkeypatch):
    # #799 contract point 3, the INVERSE shape: FakeCmds.listConnections used
    # to answer from a map only connectAttr ever filled, so a shader that
    # PREDATES this handler could not exist here and the "reused a shader that
    # was never wired to a shading group" branch had no test at all. A shader
    # built by hand in the Hypershade is exactly that node.
    fake = FakeCmds()
    fake.objects.add("hand_built")
    fake.node_types["hand_built"] = "standardSurface"
    monkeypatch.setattr(material, "_cmds", lambda: fake)
    result = material.assign_material({
        "mesh": "|torso", "shader": "standardSurface",
        "params": {"baseColor": [0.5, 0.5, 0.5]}, "name": "hand_built",
    })
    assert result["material"] == "hand_built"
    assert result["shading_group"] == "hand_built" + "SG"
    assert ("connectAttr", "hand_built.outColor",
            "hand_builtSG.surfaceShader") in fake.calls
    assert "|torso|torsoShape" in fake.sg_members["hand_builtSG"]


def test_reusing_a_mapped_shader_is_refused_before_the_mesh_is_moved(monkeypatch):
    # #804: the reuse path asks plugwrite about every param's plug BEFORE
    # the mesh is moved. MEASURED: Maya refuses the write on the compound,
    # on a child of a fed compound, and on a compound with one fed child.
    fake = FakeCmds()
    monkeypatch.setattr(material, "_cmds", lambda: fake)
    material.assign_material({
        "mesh": "|torso", "shader": "standardSurface", "params": {},
        "name": "kit",
    })
    # What assign_pbr does next: a file texture takes over the base colour.
    fake.objects.add("kit_color_tex")
    fake.node_types["kit_color_tex"] = "file"
    fake.connectAttr("kit_color_tex.outColor", "kit.baseColor", force=True)

    fake.objects.add("|arm")
    fake.shapes["|arm"] = ("|arm|armShape", "mesh")
    sg_before = {k: list(v) for k, v in fake.sg_members.items()}

    # A refusal, in the handler's own validate-before-you-touch-anything
    # style - not a raw RuntimeError out of Maya half way through the call.
    with pytest.raises(HandlerError) as exc:
        material.assign_material({
            "mesh": "|arm", "shader": "standardSurface",
            "params": {"baseColor": [1, 0, 0]}, "name": "kit",
        })
    assert "baseColor" in str(exc.value)
    assert "kit_color_tex" in str(exc.value)
    assert "assign_pbr" in (exc.value.hint or "")
    assert fake.sg_members == sg_before, "the mesh was moved by a failed call"
    assert not any(c[0] == "setAttr" for c in fake.calls[-1:]
                   if c[1] == "kit.baseColor")


def test_reusing_a_shader_mapped_on_one_channel_is_refused_for_the_compound(monkeypatch):
    # MEASURED (#804 probe): a file on kit.emissionColorR alone makes
    # setAttr(kit.emissionColor, ...) raise "A child attribute ... is locked
    # or connected", while listConnections on the compound answers []. The
    # guard walks the family, so the child is found.
    fake = FakeCmds()
    monkeypatch.setattr(material, "_cmds", lambda: fake)
    material.assign_material({"mesh": "|torso", "shader": "standardSurface",
                              "params": {}, "name": "kit"})
    fake.objects.add("kit_mask_tex")
    fake.node_types["kit_mask_tex"] = "file"
    fake.connectAttr("kit_mask_tex.outColorR", "kit.emissionColorR", force=True)
    with pytest.raises(HandlerError) as exc:
        material.assign_material({"mesh": "|torso", "shader": "standardSurface",
                                  "params": {"emissionColor": [1, 1, 1]},
                                  "name": "kit"})
    assert "emissionColorR" in str(exc.value)


def test_reusing_a_mapped_shader_with_params_on_free_plugs_still_lands(monkeypatch):
    # The guard is per plug: a mapped baseColor does not stop a roughness
    # constant on the same shader, and the mesh moves as before.
    fake = FakeCmds()
    monkeypatch.setattr(material, "_cmds", lambda: fake)
    material.assign_material({"mesh": "|torso", "shader": "standardSurface",
                              "params": {}, "name": "kit"})
    fake.objects.add("kit_color_tex")
    fake.node_types["kit_color_tex"] = "file"
    fake.connectAttr("kit_color_tex.outColor", "kit.baseColor", force=True)
    fake.objects.add("|arm")
    fake.shapes["|arm"] = ("|arm|armShape", "mesh")
    out = material.assign_material({"mesh": "|arm", "shader": "standardSurface",
                                    "params": {"roughness": 0.4}, "name": "kit"})
    assert out["material"] == "kit"
    assert ("setAttr", "kit.specularRoughness", (0.4,)) in fake.calls
    assert "|arm|armShape" in fake.sg_members[out["shading_group"]]


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
        fake.shadingNode("standardSurface", asShader=True, name="kit")
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
        fake.shadingNode("lambert", asShader=True, name="kit")
        fake.delete("kit")
        assert fake.objExists("kit") is False
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.nodeType("kit")

    def test_a_write_to_a_node_that_is_gone_raises_too(self):
        # The half contract point 1 was missing: setAttr and connectAttr
        # recorded a success against any name at all, so a handler aiming a
        # write at a stale path looked correct here.
        fake = FakeCmds()
        fake.shadingNode("lambert", asShader=True, name="kit")
        fake.delete("kit")
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.setAttr("kit.color", 1.0, 0.0, 0.0, type="double3")
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.connectAttr("kit.outColor", "ghostSG.surfaceShader")

    def test_deleting_a_transform_takes_its_shape_with_it(self):
        fake = FakeCmds()
        fake.delete("|torso")
        assert fake.objExists("|torso|torsoShape") is False

    def test_a_name_used_again_after_a_delete_is_a_new_node_not_a_ghost(self):
        # Strictness has a failure mode of its own: a permanent tombstone
        # makes a rebuilt node invisible forever, which manufactures failures.
        fake = FakeCmds()
        fake.shadingNode("lambert", asShader=True, name="kit")
        fake.delete("kit")
        fake.shadingNode("lambert", asShader=True, name="kit")
        assert fake.objExists("kit") is True
        assert fake.nodeType("kit") == "lambert"
        fake.setAttr("kit.color", 1.0, 0.0, 0.0, type="double3")

    # -- point 2: a plug something already drives -------------------------
    def test_setAttr_refuses_a_connected_plug(self):
        fake = self._wired()
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake.setAttr("kit.baseColor", 1.0, 0.0, 0.0, type="double3")

    def test_setAttr_refuses_in_both_compound_directions(self):
        # A compound write when a CHILD is fed...
        fake = FakeCmds()
        fake.shadingNode("standardSurface", asShader=True, name="kit")
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
        fake.shadingNode("lambert", asShader=True, name="kit")
        fake.locked.add("kit.color")
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake.setAttr("kit.color", 1.0, 0.0, 0.0, type="double3")

    def test_a_free_plug_still_writes(self):
        fake = self._wired()
        fake.setAttr("kit.metalness", 1.0)
        assert ("setAttr", "kit.metalness", (1.0,)) in fake.calls

    def test_deleting_the_source_frees_the_plug_again(self):
        # The refusal has to CLEAR: in Maya the destination is writable the
        # instant its source node dies. A fake that refuses forever is the
        # mirror image of one that answers anything.
        fake = self._wired()
        fake.delete("kit_color_tex")
        fake.setAttr("kit.baseColor", 1.0, 0.0, 0.0, type="double3")
        assert ("setAttr", "kit.baseColor", (1.0, 0.0, 0.0)) in fake.calls

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

    def test_nodeType_does_not_call_every_stranger_a_mesh(self):
        fake = FakeCmds()
        fake.shadingNode("lambert", asShader=True, name="kit")
        assert fake.nodeType("kit") == "lambert"
        assert fake.nodeType("|torso") == "transform"
        assert fake.nodeType("|torso|torsoShape") == "mesh"
