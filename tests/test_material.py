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

    def ls(self, name=None, long=False, **kw):
        return [o for o in self.objects if o == name or o.split("|")[-1] == name]

    def objExists(self, name):
        return name in self.objects

    def listRelatives(self, node, shapes=False, fullPath=False, noIntermediate=False):
        entry = self.shapes.get(node)
        return [entry[0]] if entry else None

    def nodeType(self, node):
        return self.node_types.get(node, "mesh")

    def shadingNode(self, node_type, asShader=False, name=None, **kw):
        self.calls.append(("shadingNode", node_type, name))
        self.objects.add(name)
        self.node_types[name] = node_type
        return name

    def sets(self, *args, **kw):
        if kw.get("renderable"):
            name = kw.get("name")
            self.calls.append(("sets", name))
            self.objects.add(name)
            self.sg_members.setdefault(name, [])
            return name
        if kw.get("query"):
            return list(self.sg_members.get(args[0], []))
        if kw.get("edit") and kw.get("forceElement"):
            shape, target = args[0], kw["forceElement"]
            for members in self.sg_members.values():
                if shape in members:
                    members.remove(shape)
            self.sg_members.setdefault(target, []).append(shape)
            self.calls.append(("sets", "forceElement", shape, target))
            return []
        return []

    def connectAttr(self, src, dst, force=False):
        self.calls.append(("connectAttr", src, dst))
        if dst.endswith(".surfaceShader") and src.endswith(".outColor"):
            self.shader_to_sg[src[: -len(".outColor")]] = dst[: -len(".surfaceShader")]

    def setAttr(self, attr, *value, **kw):
        self.calls.append(("setAttr", attr, value))

    def listConnections(self, node, type=None, **kw):
        if type == "shadingEngine" and node.endswith(".outColor"):
            sg = self.shader_to_sg.get(node[: -len(".outColor")])
            return [sg] if sg else []
        return []

    def listSets(self, object=None, type=None):
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
