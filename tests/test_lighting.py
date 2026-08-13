"""setup_lighting against a fake cmds - no Maya required."""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import lighting


class FakeCmds:
    def __init__(self, existing_lights=()):
        self.lights = list(existing_lights)     # shape names
        self.deleted = []
        self.created = []
        self.attrs = {}
        self.objects = set()

    def ls(self, *args, long=False, type=None, **kw):
        if type == "light":
            return list(self.lights)
        return []

    def listRelatives(self, node, parent=False, fullPath=False, **kw):
        return [node.replace("Shape", "")] if parent else None

    def objExists(self, name):
        return name in self.objects

    def delete(self, *names, **kw):
        for n in names:
            self.deleted.append(n)
            self.objects.discard(n)

    def directionalLight(self, name=None, intensity=1.0, **kw):
        shape = (name or "dirLight") + "Shape"
        self.created.append(("directionalLight", name, intensity))
        self.objects.add("|" + (name or "dirLight"))
        return shape

    def xform(self, name, **kw):
        if kw.get("query"):
            return [0.0, 0.0, 0.0]
        self.attrs.setdefault(name, []).append(kw)

    def setAttr(self, attr, *value, **kw):
        self.attrs[attr] = value

    def rename(self, old, new):
        return new


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
