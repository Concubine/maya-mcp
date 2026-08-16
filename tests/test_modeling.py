"""modeling handler validation tests against a fake cmds — no Maya required."""

import math

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
        self.pivots = {}
        self.face_count = 1000
        self.reduced_percentage = None
        self.selection = []
        # deform measures vertices before and after; `verts` is what a query
        # returns and `deformed_verts`, when set, is what it returns once a
        # deformer exists - the fake's stand-in for the mesh actually moving.
        self.verts = [0.0, 0.0, 0.0, 1.0, 2.0, 0.5]
        self.deformed_verts = None
        self.angle_unit = "deg"
        self.angle_attrs = {"curvature", "startAngle", "endAngle"}

    def objExists(self, name):
        return any(o == name or o.split("|")[-1] == name for o in self.objects)

    def ls(self, name=None, long=False, selection=False, **kw):
        assert long
        if selection:
            return list(self.selection)
        return [o for o in self.objects if o == name or o.split("|")[-1] == name]

    def select(self, *args, replace=False, clear=False):
        self.calls.append(("select", args, {"replace": replace, "clear": clear}))
        if clear:
            self.selection = []
            return
        flat = []
        for a in args:
            flat.extend(a) if isinstance(a, list) else flat.append(a)
        self.selection = flat

    def polyBridgeEdge(self, constructionHistory=False):
        self.calls.append(("polyBridgeEdge", self.bridge_saw_selection(), {}))

    def bridge_saw_selection(self):
        return list(self.selection)

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

    def getAttr(self, plug, type=False):
        assert type, "the fake only serves type queries"
        return "doubleAngle" if plug.split(".")[-1] in self.angle_attrs else "double"

    def currentUnit(self, query=False, angle=False, **kw):
        assert query and angle
        return self.angle_unit

    def xform(self, name, **kw):
        if kw.get("query"):
            if ".vtx[" in name:
                built = any(c[0] in ("nonLinear", "lattice", "sculpt") for c in self.calls)
                if self.deformed_verts is not None and built:
                    return list(self.deformed_verts)
                return list(self.verts)
            t, r, s = self.xf.get(name, ((0, 0, 0), (0, 0, 0), (1, 1, 1)))
            if kw.get("translation"):
                return list(t)
            if kw.get("rotation"):
                return list(r)
            if kw.get("rotatePivot") or kw.get("pivots"):
                return list(self.pivots.get(name, (0, 0, 0)))
            return list(s)
        if "pivots" in kw:
            self.pivots[name] = tuple(kw["pivots"])
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


def test_bridge_restores_the_users_selection(monkeypatch):
    # polyBridgeEdge reads the active selection, so bridge is the one op that
    # must touch it - but an artist's live selection has to survive the call.
    # It previously ended with select(clear=True), silently discarding it.
    fake = FakeCmds(objects={"|col"}, shapes={"|col": ("|col|colShape", "mesh")})
    monkeypatch.setattr(sculpt, "_cmds", lambda: fake)
    fake.selection = ["|golem|torso", "|golem|head"]

    sculpt.sculpt_ops({
        "mesh": "|col",
        "ops": [{"op": "bridge", "edges_a": "e[0:3]", "edges_b": "e[8:11]"}],
    })

    # the bridge really did run against the edges, not the user's selection
    bridged = [c for c in fake.calls if c[0] == "polyBridgeEdge"]
    assert bridged, fake.calls
    assert bridged[0][1] == ["|col.e[0:3]", "|col.e[8:11]"]
    # ...and the user's selection is back afterwards
    assert fake.selection == ["|golem|torso", "|golem|head"]


def test_bridge_clears_selection_when_there_was_none(monkeypatch):
    fake = FakeCmds(objects={"|col"}, shapes={"|col": ("|col|colShape", "mesh")})
    monkeypatch.setattr(sculpt, "_cmds", lambda: fake)
    fake.selection = []

    sculpt.sculpt_ops({
        "mesh": "|col",
        "ops": [{"op": "bridge", "edges_a": "e[0:3]", "edges_b": "e[8:11]"}],
    })

    assert fake.selection == []


def test_resolve_center_rejects_booleans_as_coordinates():
    # bool is a subclass of int, so an isinstance(v, (int, float)) check alone
    # accepts [True, False, True] as a world-space centre. modeling._vec3
    # excludes bools explicitly; this must match. The `center` branch touches
    # neither om nor fn, so it needs no Maya.
    with pytest.raises(HandlerError) as exc:
        sculpt._resolve_center(None, None, {"op": "soft_move", "center": [True, False, True]})
    assert "center" in str(exc.value)


def test_resolve_center_still_accepts_plain_numbers():
    assert sculpt._resolve_center(
        None, None, {"op": "soft_move", "center": [1, 2.5, -3]}
    ) == [1.0, 2.5, -3.0]


def test_projected_faces_matches_the_creator_multipliers():
    # Guards the arithmetic the polycount limit rests on. Measured live in
    # mayapy: polySphere(subdivisionsAxis=400, subdivisionsHeight=400) at
    # divisions=20 really is 160000 faces.
    assert modeling.projected_faces("sphere", 20) == 160_000
    assert modeling.projected_faces("torus", 20) == 160_000
    assert modeling.projected_faces("cube", 20) == 2_400
    assert modeling.projected_faces("plane", 20) == 400
    # divisions is a MULTIPLIER, and the same value costs ~67x more on a
    # sphere than a cube - which is the whole reason a shared divisions bound
    # cannot protect Maya.
    assert modeling.projected_faces("sphere", 200) == 16_000_000


def test_create_primitive_refuses_a_maya_killing_polycount(monkeypatch):
    # divisions=200 is inside the schema's own 1..200 bound, but on a sphere
    # it builds 16M faces and hangs Maya - which is unrecoverable, since a
    # wedged main thread also freezes the GUI and only a kill clears it.
    fake = FakeCmds()
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        modeling.create_primitive({"kind": "sphere", "name": "s", "divisions": 200})
    assert "16000000" in str(exc.value) or "16,000,000" in str(exc.value)
    assert str(modeling.max_divisions_for("sphere")) in exc.value.hint
    # nothing was built
    assert fake.calls == []


def test_primitive_kinds_include_low_poly_faceted_shapes():
    # F2: a cut gem is 8-16 faces; before this, the only faceted primitive
    # was a bevelled cube (36/36 chunks in the real art run).
    assert {"octahedron", "icosahedron", "prism", "pyramid"} <= set(
        modeling.PRIMITIVE_KINDS
    )


def test_projected_faces_platonic_solids_are_fixed_regardless_of_divisions():
    # polyPlatonicSolid has no subdivision flags - divisions cannot change
    # face count, unlike every other kind.
    assert modeling.projected_faces("octahedron", 1) == 8
    assert modeling.projected_faces("octahedron", 50) == 8
    assert modeling.projected_faces("icosahedron", 1) == 20
    assert modeling.projected_faces("icosahedron", 50) == 20


def test_projected_faces_prism_and_pyramid_scale_with_divisions():
    # Measured live in mayapy: polyPrism(numberOfSides=3, subdivisionsCaps=0)
    # is ns*sh+2 faces; polyPyramid(numberOfSides=4, subdivisionsCaps=0) is
    # ns*sh+1 (a single base cap, apex has no cap of its own).
    assert modeling.projected_faces("prism", 1) == 5
    assert modeling.projected_faces("prism", 3) == 11
    assert modeling.projected_faces("pyramid", 1) == 5
    assert modeling.projected_faces("pyramid", 3) == 13


def test_create_primitive_allows_the_largest_safe_divisions(monkeypatch):
    # The limit must not be so blunt that it blocks a legitimately dense mesh:
    # the highest allowed divisions for each kind still goes through.
    for kind in modeling.PRIMITIVE_KINDS:
        allowed = modeling.max_divisions_for(kind)
        assert allowed >= 1, kind
        assert modeling.projected_faces(kind, allowed) <= modeling.MAX_PRIMITIVE_FACES
        if allowed < modeling.MAX_DIVISIONS:
            assert modeling.projected_faces(kind, allowed + 1) > modeling.MAX_PRIMITIVE_FACES


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


def test_transform_pivot_alone_is_enough(monkeypatch):
    fake = FakeCmds(objects={"|a"})
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    result = modeling.transform({"names": ["|a"], "pivot": [1.0, 2.0, 3.0]})
    assert result["objects"][0]["pivot"] == [1.0, 2.0, 3.0]
    pivot_calls = [c for c in fake.calls if c[0] == "xform" and "pivots" in c[2]]
    assert len(pivot_calls) == 1
    assert pivot_calls[0][2]["pivots"] == (1.0, 2.0, 3.0)
    assert pivot_calls[0][2]["worldSpace"] is True


def test_transform_pivot_applied_before_rotate(monkeypatch):
    fake = FakeCmds(objects={"|a"})
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    modeling.transform({"names": ["|a"], "pivot": [0.0, 5.0, 0.0],
                        "rotate": [0.0, 90.0, 0.0]})
    kinds = [c[2] for c in fake.calls if c[0] == "xform"]
    pivot_at = next(i for i, kw in enumerate(kinds) if "pivots" in kw)
    rotate_at = next(i for i, kw in enumerate(kinds) if "rotation" in kw)
    assert pivot_at < rotate_at, "pivot must be set before the rotation uses it"


def test_transform_pivot_rejects_bad_shape(monkeypatch):
    fake = FakeCmds(objects={"|a"})
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        modeling.transform({"names": ["|a"], "pivot": [1.0, 2.0]})
    assert "pivot" in str(exc.value)


def test_transform_still_refuses_an_empty_call(monkeypatch):
    fake = FakeCmds(objects={"|a"})
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        modeling.transform({"names": ["|a"]})
    assert "pivot" in exc.value.hint


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
    fake.deformed_verts = [0.0, 0.0, 0.0, 1.4, 2.0, 0.5]  # 0.4 of movement
    monkeypatch.setattr(sculpt, "_cmds", lambda: fake)
    result = sculpt.deform(
        {"mesh": "|col", "deformer": "bend", "params": {"curvature": -20},
         "delete_history_after": True}
    )
    assert result == {"deformer_nodes": [], "baked": True, "warnings": [],
                      "max_displacement": pytest.approx(0.4)}
    assert ("delete", ("|col",)) in [(c[0], c[1]) for c in fake.calls if c[0] == "delete"]


# --- #636: bend was inert because curvature is an ANGLE ---------------------


def test_deform_sets_angle_params_in_degrees_whatever_the_scene_unit(monkeypatch):
    # setAttr reads an angle-typed attribute in the scene's UI angle unit. In a
    # radians scene, curvature=45 would otherwise mean 45 RADIANS - seven full
    # turns - so the same call must be converted, not passed through.
    fake = _mesh_fake("|col")
    fake.angle_unit = "rad"
    monkeypatch.setattr(sculpt, "_cmds", lambda: fake)
    sculpt.deform({"mesh": "|col", "deformer": "bend",
                   "params": {"curvature": 45, "lowBound": -1}})
    written = {c[1]: c[2] for c in fake.calls if c[0] == "setAttr"}
    assert written["bend1.curvature"] == pytest.approx(math.radians(45))
    # lowBound is a plain double and must NOT be touched by the conversion
    assert written["bend1.lowBound"] == -1


def test_deform_leaves_angles_alone_in_a_degrees_scene(monkeypatch):
    fake = _mesh_fake("|col")
    monkeypatch.setattr(sculpt, "_cmds", lambda: fake)
    sculpt.deform({"mesh": "|col", "deformer": "twist",
                   "params": {"startAngle": 30, "endAngle": -30}})
    written = {c[1]: c[2] for c in fake.calls if c[0] == "setAttr"}
    assert written == {"twist1.startAngle": 30.0, "twist1.endAngle": -30.0}


def test_deform_rejects_an_angle_unit_it_cannot_convert(monkeypatch):
    fake = _mesh_fake("|col")
    fake.angle_unit = "gradians"
    monkeypatch.setattr(sculpt, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        sculpt.deform({"mesh": "|col", "deformer": "bend", "params": {"curvature": 45}})
    assert "gradians" in str(exc.value)


def test_deform_warns_when_the_mesh_did_not_move(monkeypatch):
    # The #636 shape exactly: a bend that reports success and moves the mesh by
    # a fraction of a percent of its own size.
    fake = _mesh_fake("|col")
    fake.deformed_verts = [0.0, 0.0, 0.0, 1.0015, 2.0, 0.5]
    monkeypatch.setattr(sculpt, "_cmds", lambda: fake)
    result = sculpt.deform({"mesh": "|col", "deformer": "bend",
                            "params": {"curvature": 0.35}})
    assert result["max_displacement"] == pytest.approx(0.0015)
    assert len(result["warnings"]) == 1
    assert "DEGREES" in result["warnings"][0]


def test_deform_is_silent_when_the_mesh_actually_moved(monkeypatch):
    fake = _mesh_fake("|col")
    fake.deformed_verts = [0.0, 0.0, 0.0, 1.3, 2.0, 0.5]
    monkeypatch.setattr(sculpt, "_cmds", lambda: fake)
    result = sculpt.deform({"mesh": "|col", "deformer": "bend",
                            "params": {"curvature": 45}})
    assert result["warnings"] == []
    assert result["max_displacement"] == pytest.approx(0.3)


def test_deform_does_not_warn_for_a_freshly_built_lattice(monkeypatch):
    # A lattice deforms nothing until its points are moved, so zero
    # displacement is the correct outcome and must not read as a defect.
    fake = _mesh_fake("|col")
    monkeypatch.setattr(sculpt, "_cmds", lambda: fake)
    result = sculpt.deform({"mesh": "|col", "deformer": "lattice", "params": {}})
    assert result["max_displacement"] == 0.0
    assert result["warnings"] == []


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


def test_deform_accepts_the_three_new_nonlinear_types():
    for kind in ("flare", "sine", "wave"):
        assert kind in sculpt.DEFORMER_WHITELIST


def test_flare_whitelists_the_taper_params():
    assert {"curve", "startFlareX", "startFlareZ", "endFlareX", "endFlareZ"} <= (
        sculpt.DEFORMER_WHITELIST["flare"]
    )


def test_wave_has_radial_bounds_and_not_axial_ones():
    # wave is bounded radially in the XZ plane, not along an axis. Copying
    # sine's whitelist wholesale would accept lowBound/highBound and set
    # attributes that do not exist on the node.
    assert {"minRadius", "maxRadius"} <= sculpt.DEFORMER_WHITELIST["wave"]
    assert "lowBound" not in sculpt.DEFORMER_WHITELIST["wave"]
    assert "highBound" in sculpt.DEFORMER_WHITELIST["sine"]


def test_deform_rejects_a_sine_param_on_flare(monkeypatch):
    fake = _mesh_fake("|blob")
    monkeypatch.setattr(sculpt, "_cmds", lambda: fake)
    with pytest.raises(HandlerError):
        sculpt.deform({"mesh": "|blob", "deformer": "flare",
                       "params": {"wavelength": 2.0}})


def test_nonlinear_params_are_set_as_attributes_not_creation_flags(monkeypatch):
    # One uniform path for all six nonLinear types removes the "is this name a
    # command flag or an attribute?" question entirely - the question that made
    # adding three types risky in the first place.
    fake = _mesh_fake("|blob")
    monkeypatch.setattr(sculpt, "_cmds", lambda: fake)
    sculpt.deform({"mesh": "|blob", "deformer": "flare",
                   "params": {"curve": 0.5, "endFlareX": 0.3}})
    nonlinear_calls = [c for c in fake.calls if c[0] == "nonLinear"]
    assert len(nonlinear_calls) == 1
    assert nonlinear_calls[0][2] == "flare"  # type
    assert nonlinear_calls[0][3] == {}  # no other creation kwargs
    set_attrs = {c[1]: c[2] for c in fake.calls if c[0] == "setAttr"}
    assert set_attrs["flare1.curve"] == 0.5
    assert set_attrs["flare1.endFlareX"] == 0.3


def test_squash_params_are_set_as_attributes_not_creation_flags(monkeypatch):
    # squash is one of the three PRE-EXISTING types (bend/squash/twist) whose
    # param wiring the refactor changed - flare/sine/wave are new types with
    # no prior behaviour to regress. Mirrors the flare test above so squash
    # gets the same headless proof that its params land as setAttr calls.
    fake = _mesh_fake("|blob")
    monkeypatch.setattr(sculpt, "_cmds", lambda: fake)
    sculpt.deform({"mesh": "|blob", "deformer": "squash",
                   "params": {"factor": 0.5}})
    nonlinear_calls = [c for c in fake.calls if c[0] == "nonLinear"]
    assert len(nonlinear_calls) == 1
    assert nonlinear_calls[0][2] == "squash"  # type
    assert nonlinear_calls[0][3] == {}  # no other creation kwargs
    set_attrs = {c[1]: c[2] for c in fake.calls if c[0] == "setAttr"}
    assert set_attrs["squash1.factor"] == 0.5


def test_handle_transform_params_are_not_set_as_attributes(monkeypatch):
    fake = _mesh_fake("|blob")
    monkeypatch.setattr(sculpt, "_cmds", lambda: fake)
    sculpt.deform({"mesh": "|blob", "deformer": "twist",
                   "params": {"startAngle": 40.0, "translate": [0, 2, 0]}})
    set_attrs = {c[1]: c[2] for c in fake.calls if c[0] == "setAttr"}
    assert not any(".translate" in plug for plug in set_attrs)
    assert set_attrs["twist1.startAngle"] == 40.0


def test_deform_raises_for_whitelisted_type_missing_from_nonlinear_types(monkeypatch):
    # Finding 2: NONLINEAR_TYPES must be a real gate, not dead code - if a
    # type is ever added to DEFORMER_WHITELIST without also adding it to
    # NONLINEAR_TYPES (and wiring a dispatch branch), deform() must fail
    # loudly instead of silently falling into the nonLinear path with a
    # bogus type name.
    fake = _mesh_fake("|blob")
    monkeypatch.setattr(sculpt, "_cmds", lambda: fake)
    monkeypatch.setitem(sculpt.DEFORMER_WHITELIST, "wobble", {"amount"})
    with pytest.raises(HandlerError) as exc:
        sculpt.deform({"mesh": "|blob", "deformer": "wobble", "params": {"amount": 1}})
    assert "wobble" in str(exc.value)
    assert "sculpt" in exc.value.hint and "lattice" in exc.value.hint
    assert not any(c[0] == "nonLinear" for c in fake.calls)


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


def test_every_primitive_size_is_passed_explicitly_never_defaulted(monkeypatch):
    """A size FLAG is read in the scene's current linear unit; an OMITTED one
    falls back to Maya's internal unit. Measured live with the scene in metres:
    polyCube() builds a 0.01 m cube and polyCube(w=1,h=1,d=1) a 1 m one - so a
    cube came out ONE HUNDRED TIMES smaller than a sphere at the same scale,
    silently breaking the unit-box promise create_primitive is built on.

    Asserted as kwargs because that is the shape of the bug: not a wrong number,
    an ABSENT one.
    """
    recorded = {}

    class SizeSpy:
        def objExists(self, name):
            return False

        def ls(self, name, **kw):
            return ["|" + name]

        def xform(self, *a, **kw):
            return [0.0, 0.0, 0.0]

        def __getattr__(self, creator):
            def call(name=None, **kw):
                recorded[creator] = kw
                return [name, name + "Shape"]
            return call

    spy = SizeSpy()
    monkeypatch.setattr(modeling, "_cmds", lambda: spy)
    monkeypatch.setattr(modeling.ledger, "record", lambda cmds, name: None)

    size_flags = {"width", "height", "depth", "radius", "sectionRadius",
                  "sideLength", "length"}
    for kind in modeling.PRIMITIVE_KINDS:
        recorded.clear()
        modeling.create_primitive({"kind": kind, "name": "probe_" + kind})
        kwargs = list(recorded.values())[0]
        assert size_flags & set(kwargs), (
            "%s relies on Maya's default size, which is in the INTERNAL unit" % kind
        )
