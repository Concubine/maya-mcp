"""Named texture recipes - no Maya required."""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import texture_recipes


class FakeCmds:
    def __init__(self):
        self.objects = {"|torso", "clay_mat"}
        self.shapes = {"|torso": ("|torso|torsoShape", "mesh")}
        self.created = []
        self.connections = []
        self.deleted = []
        self.fail_on = None

    def ls(self, name=None, long=False, **kw):
        return [o for o in self.objects if o == name or o.split("|")[-1] == name]

    def objExists(self, name):
        return name in self.objects

    def listRelatives(self, node, shapes=False, fullPath=False, noIntermediate=False):
        entry = self.shapes.get(node)
        return [entry[0]] if entry else None

    def nodeType(self, node):
        return "mesh" if node.endswith("Shape") else "standardSurface"

    def listConnections(self, node, type=None, **kw):
        if type == "shadingEngine":
            return ["clay_matSG"]
        return ["clay_mat"]

    def listSets(self, object=None, type=None):
        return ["clay_matSG"]

    def shadingNode(self, node_type, name=None, **kw):
        if self.fail_on == node_type:
            raise RuntimeError("forced failure creating %s" % node_type)
        self.created.append(name)
        self.objects.add(name)
        return name

    def connectAttr(self, src, dst, force=False):
        self.connections.append((src, dst))

    def setAttr(self, attr, *value, **kw):
        pass

    def delete(self, *names, **kw):
        for n in names:
            self.deleted.append(n)
            self.objects.discard(n)


def test_noise_bump_builds_and_connects_to_the_normal_slot(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(texture_recipes, "_cmds", lambda: fake)
    result = texture_recipes.apply_texture_recipe(
        {"mesh": "|torso", "recipe": "noise_bump", "params": {"scale": 2.0}}
    )
    assert result["recipe"] == "noise_bump"
    assert result["slot"] == "normal"
    assert len(result["nodes"]) == 2          # noise + bump2d
    assert any(dst.endswith(".normalCamera") for _, dst in fake.connections)


def test_noise_bump_bad_scale_type_raises_hinted_handler_error(monkeypatch):
    # I2: scale/depth used to go straight to float(), so a bad type raised a
    # raw ValueError with no hint - and did so AFTER the noise node was
    # already created. Must now be a HandlerError, and must leave no orphan.
    fake = FakeCmds()
    monkeypatch.setattr(texture_recipes, "_cmds", lambda: fake)
    before = set(fake.objects)
    with pytest.raises(HandlerError) as exc:
        texture_recipes.apply_texture_recipe(
            {"mesh": "|torso", "recipe": "noise_bump",
             "params": {"scale": "big"}}
        )
    assert "scale" in str(exc.value)
    assert fake.objects == before


def test_noise_bump_bad_depth_type_raises_hinted_handler_error(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(texture_recipes, "_cmds", lambda: fake)
    before = set(fake.objects)
    with pytest.raises(HandlerError) as exc:
        texture_recipes.apply_texture_recipe(
            {"mesh": "|torso", "recipe": "noise_bump",
             "params": {"depth": [1, 2]}}
        )
    assert "depth" in str(exc.value)
    assert fake.objects == before


def test_unknown_recipe_lists_the_valid_ones(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(texture_recipes, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        texture_recipes.apply_texture_recipe({"mesh": "|torso", "recipe": "marble"})
    assert "noise_bump" in exc.value.hint


def test_failure_midway_sweeps_every_node_it_created(monkeypatch):
    # The zero-orphan rule, asserted on the path that actually breaks it.
    fake = FakeCmds()
    fake.fail_on = "bump2d"        # noise is created first, then this raises
    monkeypatch.setattr(texture_recipes, "_cmds", lambda: fake)
    with pytest.raises(Exception):
        texture_recipes.apply_texture_recipe(
            {"mesh": "|torso", "recipe": "noise_bump"}
        )
    assert fake.deleted == fake.created, (
        "recipe left orphans: created %s, deleted %s" % (fake.created, fake.deleted)
    )


def test_file_texture_requires_a_path(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(texture_recipes, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        texture_recipes.apply_texture_recipe(
            {"mesh": "|torso", "recipe": "file_texture"}
        )
    assert "file_path" in str(exc.value) or "file_path" in exc.value.hint
