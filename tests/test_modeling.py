"""modeling handler validation tests against a fake cmds — no Maya required."""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import ledger, modeling


class FakeCmds:
    """Records calls; simulates a flat scene namespace."""

    def __init__(self, objects=(), shapes=None):
        self.objects = set(objects)
        self.shapes = shapes or {}  # long transform -> (shape_long, node_type)
        self.calls = []
        self.xf = {}

    def objExists(self, name):
        return any(o == name or o.split("|")[-1] == name for o in self.objects)

    def ls(self, name=None, long=False, **kw):
        assert long
        return [o for o in self.objects if o == name or o.split("|")[-1] == name]

    def listRelatives(self, node, shapes=False, children=False, fullPath=False, noIntermediate=False):
        if shapes:
            assert shapes and fullPath and noIntermediate
            entry = self.shapes.get(node)
            return [entry[0]] if entry else None
        assert children and fullPath
        prefix = node + "|"
        return [
            o for o in self.objects
            if o.startswith(prefix) and "|" not in o[len(prefix):]
        ] or None

    def nodeType(self, node):
        for shape, ntype in self.shapes.values():
            if shape == node:
                return ntype
        raise AssertionError("unexpected nodeType call")

    def polyCube(self, name=None, constructionHistory=False, **kw):
        self.calls.append(("polyCube", name, kw))
        long_name = "|" + name
        self.objects.add(long_name)
        self.xf[long_name] = ((0, 0, 0), (0, 0, 0), (1, 1, 1))
        return [name, name + "Shape"]

    def xform(self, name, **kw):
        if kw.get("query"):
            t, r, s = self.xf.get(name, ((0, 0, 0), (0, 0, 0), (1, 1, 1)))
            if kw.get("translation"):
                return list(t)
            if kw.get("rotation"):
                return list(r)
            return list(s)
        self.calls.append(("xform", name, kw))

    def delete(self, *names):
        self.calls.append(("delete", names))
        for n in names:
            self.objects.discard(n)

    def group(self, *names, name=None):
        self.calls.append(("group", names, name))
        long_name = "|" + name
        self.objects.add(long_name)
        self.xf[long_name] = ((0, 0, 0), (0, 0, 0), (1, 1, 1))
        # Reparent children: update their long names in objects set
        for child in names:
            self.objects.discard(child)
            child_short = child.split("|")[-1]
            new_long = long_name + "|" + child_short
            self.objects.add(new_long)
            if child in self.xf:
                self.xf[new_long] = self.xf[child]
                del self.xf[child]
        return name


@pytest.fixture(autouse=True)
def clean_ledger():
    ledger.clear()
    yield
    ledger.clear()


def test_create_primitive_rejects_unknown_kind():
    with pytest.raises(HandlerError) as exc:
        modeling.create_primitive({"kind": "dodecahedron", "name": "x"})
    assert "cube" in exc.value.hint  # hint lists valid kinds


def test_create_primitive_requires_name():
    with pytest.raises(HandlerError):
        modeling.create_primitive({"kind": "cube"})


def test_create_primitive_collision_gets_suffix(monkeypatch):
    fake = FakeCmds(objects={"|golem_arm"})
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    result = modeling.create_primitive({"kind": "cube", "name": "golem_arm"})
    assert result["name"] == "|golem_arm_001"


def test_transform_missing_object_errors(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    with pytest.raises(HandlerError):
        modeling.transform({"names": ["|nope"], "translate": [1, 0, 0]})


def test_transform_requires_some_component(monkeypatch):
    fake = FakeCmds(objects={"|a"})
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        modeling.transform({"names": ["|a"]})
    assert "translate" in exc.value.hint


def test_transform_reports_user_moved_warning(monkeypatch):
    fake = FakeCmds(objects={"|a"})
    fake.xf["|a"] = ((0, 0, 0), (0, 0, 0), (1, 1, 1))
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    ledger.record(fake, "|a")
    fake.xf["|a"] = ((5, 0, 0), (0, 0, 0), (1, 1, 1))  # user dragged it
    result = modeling.transform({"names": ["|a"], "translate": [1, 0, 0]})
    assert any("outside" in w for w in result["warnings"])


def test_delete_objects_lists_all_missing(monkeypatch):
    fake = FakeCmds(objects={"|a"})
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        modeling.delete_objects({"names": ["|a", "|gone", "|also_gone"]})
    assert "|gone" in str(exc.value) and "|also_gone" in str(exc.value)
    assert not any(c[0] == "delete" for c in fake.calls)  # nothing deleted


def test_group_rekeys_ledger_for_children(monkeypatch):
    """After grouping, children's old ledger entries are gone; new ones exist."""
    fake = FakeCmds(objects={"|a", "|b"})
    fake.xf["|a"] = ((1, 0, 0), (0, 0, 0), (1, 1, 1))
    fake.xf["|b"] = ((2, 0, 0), (0, 0, 0), (1, 1, 1))
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)

    # Record transforms for both objects before grouping
    ledger.record(fake, "|a")
    ledger.record(fake, "|b")

    # Group the children
    result = modeling.group({"names": ["|a", "|b"], "group_name": "parent_grp"})
    group_name = result["name"]

    # Old ledger entries should be gone
    assert ledger.check(fake, "|a") is None
    assert ledger.check(fake, "|b") is None

    # New ledger entries should exist for the reparented children: mutate the
    # post-group transform and confirm a baseline was actually recorded
    # (mirrors test_transform_reports_user_moved_warning; check() returning
    # None can't distinguish "recorded" from "never recorded").
    new_a = group_name + "|a"
    new_b = group_name + "|b"
    fake.xf[new_a] = ((99, 0, 0), (0, 0, 0), (1, 1, 1))
    warning_a = ledger.check(fake, new_a)
    assert warning_a is not None and "outside" in warning_a

    fake.xf[new_b] = ((99, 0, 0), (0, 0, 0), (1, 1, 1))
    warning_b = ledger.check(fake, new_b)
    assert warning_b is not None and "outside" in warning_b


def test_boolean_rejects_unknown_op(monkeypatch):
    fake = FakeCmds(objects={"|a", "|b"})
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        modeling.boolean_op({"a": "|a", "b": "|b", "op": "xor", "new_name": "x"})
    assert "union" in exc.value.hint


def test_boolean_rejects_same_object(monkeypatch):
    fake = FakeCmds(
        objects={"|a"},
        shapes={"|a": ("|a|aShape", "mesh")},
    )
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    with pytest.raises(HandlerError):
        modeling.boolean_op({"a": "|a", "b": "|a", "op": "union", "new_name": "x"})
