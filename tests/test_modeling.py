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

    def listRelatives(self, node, shapes=False, fullPath=False, noIntermediate=False):
        assert shapes and fullPath and noIntermediate
        entry = self.shapes.get(node)
        return [entry[0]] if entry else None

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
