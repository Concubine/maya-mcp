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


class FakeCmds:
    def __init__(self):
        self.objects = {"|torso"}
        self.shapes = {"|torso": ("|torso|torsoShape", "mesh")}
        self.calls = []
        # sg name -> list of member long names; mirrors real Maya's shape-to-SG
        # sets membership, including whatever default SG a mesh starts in.
        self.sg_members = {}

    def ls(self, name=None, long=False, **kw):
        return [o for o in self.objects if o == name or o.split("|")[-1] == name]

    def objExists(self, name):
        return name in self.objects

    def listRelatives(self, node, shapes=False, fullPath=False, noIntermediate=False):
        entry = self.shapes.get(node)
        return [entry[0]] if entry else None

    def nodeType(self, node):
        return "mesh"

    def shadingNode(self, node_type, asShader=False, name=None, **kw):
        self.calls.append(("shadingNode", node_type, name))
        self.objects.add(name)
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

    def setAttr(self, attr, *value, **kw):
        self.calls.append(("setAttr", attr, value))

    def listConnections(self, node, type=None, **kw):
        return []

    def listSets(self, object=None, type=None):
        return [sg for sg, members in self.sg_members.items() if object in members]
