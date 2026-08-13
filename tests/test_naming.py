import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import naming


class FakeCmds:
    def __init__(self, objects=None, shapes=None):
        self.objects = set(objects or [])
        self.shapes = shapes or {}  # long transform -> (shape_long, node_type)

    def objExists(self, name):
        return any(o == name or o.split("|")[-1] == name for o in self.objects)

    def ls(self, name, long=False):
        assert long
        return [o for o in self.objects if o == name or o.split("|")[-1] == name]

    def listRelatives(self, node, shapes=False, fullPath=False, noIntermediate=False):
        assert shapes and fullPath and noIntermediate
        entry = self.shapes.get(node)
        return [entry[0]] if entry else None

    def nodeType(self, node):
        for shape, ntype in self.shapes.values():
            if shape == node:
                return ntype
        raise AssertionError("unexpected nodeType call")


def test_unique_name_passthrough_when_free():
    assert naming.unique_name(FakeCmds(), "golem_arm") == "golem_arm"


def test_unique_name_deterministic_suffix():
    fake = FakeCmds(objects={"golem_arm", "golem_arm_001"})
    assert naming.unique_name(fake, "golem_arm") == "golem_arm_002"


def test_require_object_missing_has_hint():
    with pytest.raises(HandlerError) as exc:
        naming.require_object(FakeCmds(), "|nope")
    assert "maya_get_scene_graph" in exc.value.hint


def test_require_object_ambiguous_short_name():
    fake = FakeCmds(objects={"|a|torso", "|b|torso"})
    with pytest.raises(HandlerError) as exc:
        naming.require_object(fake, "torso")
    assert "ambiguous" in str(exc.value)


def test_require_mesh_rejects_non_mesh():
    fake = FakeCmds(
        objects={"|keyLight"},
        shapes={"|keyLight": ("|keyLight|keyLightShape", "pointLight")},
    )
    with pytest.raises(HandlerError) as exc:
        naming.require_mesh(fake, "|keyLight")
    assert "not a polygon mesh" in str(exc.value)


def test_require_mesh_returns_long_names():
    fake = FakeCmds(
        objects={"|golem|torso"},
        shapes={"|golem|torso": ("|golem|torso|torsoShape", "mesh")},
    )
    assert naming.require_mesh(fake, "|golem|torso") == (
        "|golem|torso",
        "|golem|torso|torsoShape",
    )
