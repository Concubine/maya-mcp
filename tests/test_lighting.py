"""setup_lighting against a fake cmds - no Maya required."""

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
        return []

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
