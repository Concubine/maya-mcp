"""modeling handler validation tests against a fake cmds — no Maya required."""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import ledger, meshcheck, modeling, sculpt, session


class FakeCmds:
    """Records calls; simulates a flat scene namespace."""

    def __init__(self, objects=(), shapes=None):
        self.objects = set(objects)
        self.shapes = shapes or {}  # long transform -> (shape_long, node_type)
        self.calls = []
        self.xf = {}
        self.face_count = 1000
        self.reduced_percentage = None

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

    def delete(self, *names, **kw):
        self.calls.append(("delete", names))
        if not kw.get("constructionHistory"):
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

    def duplicate(self, source, name=None, returnRootsOnly=False):
        self.calls.append(("duplicate", source, name))
        long_name = "|" + name
        self.objects.add(long_name)
        self.xf[long_name] = ((0, 0, 0), (0, 0, 0), (1, 1, 1))
        return [name]

    def setAttr(self, attr, value):
        self.calls.append(("setAttr", attr, value))

    def nonLinear(self, name, type=None, **kw):
        self.calls.append(("nonLinear", name, type, kw))
        deformer_name = type + "1"
        handle_name = type + "Handle1"
        self.objects.add("|" + handle_name)
        return [deformer_name, handle_name]

    def lattice(self, name, divisions=None, objectCentered=None, **kw):
        self.calls.append(("lattice", name, divisions, objectCentered, kw))
        self.objects.add("|ffd1Lattice")
        self.objects.add("|ffd1Base")
        return ["ffd1", "ffd1Lattice", "ffd1Base"]

    def sculpt(self, name, **kw):
        self.calls.append(("sculpt", name, kw))
        self.objects.add("|sculptor1")
        self.objects.add("|sculpt1StretchOrigin")
        return ["sculpt1", "sculptor1", "sculpt1StretchOrigin"]

    def polyEvaluate(self, name, face=False, triangle=False, vertex=False):
        self.calls.append(("polyEvaluate", name, face, triangle, vertex))
        if face:
            return self.face_count
        if triangle:
            return self.face_count
        if vertex:
            return self.face_count
        raise AssertionError("unexpected polyEvaluate call")

    def polyReduce(self, name, percentage=None, constructionHistory=False):
        self.calls.append(("polyReduce", name, percentage))
        self.reduced_percentage = percentage

    def polyMergeVertex(self, name, distance=None):
        self.calls.append(("polyMergeVertex", name, distance))

    def polyNormal(self, name, normalMode=None, constructionHistory=False):
        self.calls.append(("polyNormal", name, normalMode))

    def makeIdentity(self, name, apply=None, translate=None, rotate=None, scale=None):
        self.calls.append(("makeIdentity", name, apply, translate, rotate, scale))


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


def _mesh_fake(name="|blob"):
    return FakeCmds(objects={name}, shapes={name: (name + "|blobShape", "mesh")})


def test_remesh_retopo_rejects_too_low_target_polycount(monkeypatch):
    fake = _mesh_fake()
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        modeling.remesh_retopo({"mesh": "|blob", "target_polycount": 50})
    assert "target_polycount" in str(exc.value)
    # validation happens before the auto-checkpoint (which would need real
    # Maya) - no cmds writes must have happened
    assert fake.calls == []


def test_remesh_retopo_rejects_too_high_target_polycount(monkeypatch):
    fake = _mesh_fake()
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        modeling.remesh_retopo({"mesh": "|blob", "target_polycount": 999999})
    assert "target_polycount" in str(exc.value)


def test_remesh_retopo_rejects_non_int_target_polycount(monkeypatch):
    fake = _mesh_fake()
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    with pytest.raises(HandlerError):
        modeling.remesh_retopo({"mesh": "|blob", "target_polycount": 400.5})


def test_remesh_retopo_rejects_missing_mesh(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    with pytest.raises(HandlerError):
        modeling.remesh_retopo({"mesh": "|nope", "target_polycount": 400})


def test_mesh_cleanup_rejects_zero_threshold(monkeypatch):
    fake = _mesh_fake("|dirty")
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        modeling.mesh_cleanup({"mesh": "|dirty", "merge_verts_threshold": 0})
    assert "merge_verts_threshold" in str(exc.value)
    assert fake.calls == []


def test_mesh_cleanup_rejects_threshold_above_one(monkeypatch):
    fake = _mesh_fake("|dirty")
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    with pytest.raises(HandlerError):
        modeling.mesh_cleanup({"mesh": "|dirty", "merge_verts_threshold": 1.5})


def test_mesh_cleanup_rejects_missing_mesh(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    with pytest.raises(HandlerError):
        modeling.mesh_cleanup({"mesh": "|nope"})


def test_deform_rejects_unknown_deformer(monkeypatch):
    fake = _mesh_fake("|col")
    monkeypatch.setattr(sculpt, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        sculpt.deform({"mesh": "|col", "deformer": "melt", "params": {}})
    assert "bend" in exc.value.hint


def test_deform_rejects_unknown_param_for_type(monkeypatch):
    fake = _mesh_fake("|col")
    monkeypatch.setattr(sculpt, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        sculpt.deform({"mesh": "|col", "deformer": "twist", "params": {"wobble": 1}})
    assert "startAngle" in exc.value.hint


def test_deform_does_not_mutate_caller_params_dict(monkeypatch):
    # Ambiguity #1 fix: dparams must be a copy, not the caller's dict popped
    # in place.
    fake = _mesh_fake("|col")
    monkeypatch.setattr(sculpt, "_cmds", lambda: fake)
    caller_params = {"curvature": 45, "translate": [0, 1, 0]}
    result = sculpt.deform({"mesh": "|col", "deformer": "bend", "params": caller_params})
    assert caller_params == {"curvature": 45, "translate": [0, 1, 0]}
    assert result["deformer_nodes"] == ["bend1", "|bendHandle1"]


def test_deform_bakes_and_deletes_history(monkeypatch):
    fake = _mesh_fake("|col")
    monkeypatch.setattr(sculpt, "_cmds", lambda: fake)
    result = sculpt.deform(
        {"mesh": "|col", "deformer": "bend", "params": {"curvature": -20},
         "delete_history_after": True}
    )
    assert result == {"deformer_nodes": [], "baked": True, "warnings": []}
    assert ("delete", ("|col",)) in [(c[0], c[1]) for c in fake.calls if c[0] == "delete"]


def test_deform_lattice_translates_lattice_handle_not_base(monkeypatch):
    # Finding 2: cmds.lattice returns [ffd, lattice, base]; the base is a
    # fixed reference frame, so translating it (nodes[-1], the old bug)
    # instead of the lattice (nodes[1]) is wrong. Use the FakeCmds.lattice
    # scaffolding (previously dead) to assert the xform lands on the right
    # node.
    fake = _mesh_fake("|col")
    monkeypatch.setattr(sculpt, "_cmds", lambda: fake)
    result = sculpt.deform(
        {"mesh": "|col", "deformer": "lattice",
         "params": {"translate": [1, 2, 3]}}
    )
    assert result["deformer_nodes"] == ["ffd1", "|ffd1Lattice", "|ffd1Base"]
    xform_calls = [c for c in fake.calls if c[0] == "xform"]
    assert len(xform_calls) == 1
    # handle is the raw node cmds.lattice returned (nodes[1] = the lattice,
    # not the base at nodes[2]) - matches the pre-existing convention where
    # cmds.xform receives the raw handle name, not the resolved long name.
    assert xform_calls[0][1] == "ffd1Lattice"
    assert xform_calls[0][2]["translation"] == [1, 2, 3]


def test_deform_sculpt_calls_sculpt_command_with_whitelisted_params(monkeypatch):
    # Finding 1: deformer="sculpt" must route to cmds.sculpt (which accepts
    # maxDisplacement/dropoffDistance), not cmds.nonLinear (which does not
    # support a "sculpt" type at all).
    fake = _mesh_fake("|col")
    monkeypatch.setattr(sculpt, "_cmds", lambda: fake)
    result = sculpt.deform(
        {"mesh": "|col", "deformer": "sculpt",
         "params": {"maxDisplacement": 1.0, "dropoffDistance": 2.0}}
    )
    sculpt_calls = [c for c in fake.calls if c[0] == "sculpt"]
    assert len(sculpt_calls) == 1
    assert sculpt_calls[0][1] == "|col"
    assert sculpt_calls[0][2] == {"maxDisplacement": 1.0, "dropoffDistance": 2.0}
    assert not any(c[0] == "nonLinear" for c in fake.calls)
    assert result["deformer_nodes"] == ["sculpt1", "|sculptor1", "|sculpt1StretchOrigin"]


def _patch_auto_checkpoint(monkeypatch):
    monkeypatch.setattr(
        session, "auto_checkpoint",
        lambda reason: {"checkpoint_id": "auto_" + reason, "path": "fake.ma"},
    )


def test_remesh_retopo_keep_original_false_skips_duplicate(monkeypatch):
    fake = _mesh_fake("|blob")
    fake.face_count = 1600
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    _patch_auto_checkpoint(monkeypatch)
    result = modeling.remesh_retopo(
        {"mesh": "|blob", "target_polycount": 400, "keep_original": False}
    )
    assert not any(c[0] == "duplicate" for c in fake.calls)
    assert result["method"] == "polyReduce"  # FakeCmds has no polyRetopo/polyRemesh


def test_remesh_retopo_polyreduce_percentage_is_reduction_amount_not_keep_fraction(monkeypatch):
    # Finding 3: percentage passed to polyReduce must be the amount of
    # reduction to *perform* (1 - keep_fraction) * 100, not the keep
    # fraction itself.
    fake = _mesh_fake("|blob")
    fake.face_count = 1600  # target 400 -> keep 25%, so reduce by 75%
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    _patch_auto_checkpoint(monkeypatch)
    result = modeling.remesh_retopo(
        {"mesh": "|blob", "target_polycount": 400, "keep_original": False}
    )
    assert result["method"] == "polyReduce"
    assert fake.reduced_percentage == pytest.approx(75.0)


def test_remesh_retopo_target_at_or_above_current_skips_polyreduce_call(monkeypatch):
    fake = _mesh_fake("|blob")
    fake.face_count = 200  # target 400 >= current 200: nothing to reduce
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    _patch_auto_checkpoint(monkeypatch)
    result = modeling.remesh_retopo(
        {"mesh": "|blob", "target_polycount": 400, "keep_original": False}
    )
    assert result["method"] == "polyReduce"
    assert not any(c[0] == "polyReduce" for c in fake.calls)
    assert any("nothing to reduce" in w for w in result["warnings"])


def _fake_mesh_stats(counter):
    def _stats(name):
        counter.append(name)
        return {
            "tris": 12, "verts": 8, "faces": 6,
            "boundary_edges": 0, "nonmanifold_edges": 0, "watertight": True,
        }
    return _stats


def test_mesh_cleanup_conform_normals_false_skips_polyNormal(monkeypatch):
    fake = _mesh_fake("|dirty")
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    monkeypatch.setattr(meshcheck, "mesh_stats", _fake_mesh_stats([]))
    modeling.mesh_cleanup({"mesh": "|dirty", "conform_normals": False})
    assert not any(c[0] == "polyNormal" for c in fake.calls)
    assert any(c[0] == "polyMergeVertex" for c in fake.calls)  # unaffected


def test_mesh_cleanup_freeze_transforms_false_skips_makeIdentity(monkeypatch):
    fake = _mesh_fake("|dirty")
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    monkeypatch.setattr(meshcheck, "mesh_stats", _fake_mesh_stats([]))
    modeling.mesh_cleanup({"mesh": "|dirty", "freeze_transforms": False})
    assert not any(c[0] == "makeIdentity" for c in fake.calls)


def test_mesh_cleanup_delete_history_false_skips_delete(monkeypatch):
    fake = _mesh_fake("|dirty")
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    monkeypatch.setattr(meshcheck, "mesh_stats", _fake_mesh_stats([]))
    modeling.mesh_cleanup({"mesh": "|dirty", "delete_history": False})
    assert not any(c[0] == "delete" for c in fake.calls)
