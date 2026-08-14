"""maya_combine: does it merge meshes the way a kit needs, and refuse the rest?

The fake reproduces the two Maya behaviours that have burned this project
before:

  * cmds.polyUnite RENAMES its result on a name collision, so the handler must
    re-resolve by short name rather than trusting the name it asked for
    (modeling.py documents the same trap for grouping).
  * combining meshes that carry different shaders leaves PER-FACE shading
    group membership, which #577 found silently no-ops later per-face work and
    corrupts SGs. The handler collapses to one object-level SG and says so.
"""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import combine


class FakeCmds:
    def __init__(self, objects=("|a", "|b"), shapes=None, unite_name=None):
        self.objects = list(objects)
        self.shapes = (
            dict(shapes)
            if shapes is not None
            else {o: (o + "Shape", "mesh") for o in self.objects}
        )
        self.calls = []
        self.deleted = []
        self.pivots = {}
        self.frozen = []
        # what polyUnite will actually name the result, when Maya disagrees
        self._unite_name = unite_name
        self.sg_members = {}

    # --- names -------------------------------------------------------------
    def ls(self, pattern=None, long=False, **kwargs):
        if pattern is None:
            hits = list(self.objects)
        else:
            hits = [
                n for n in self.objects
                if n == pattern or n.split("|")[-1] == pattern
            ]
        return hits if long else [h.split("|")[-1] for h in hits]

    def objExists(self, name):
        return bool(self.ls(name))

    def listRelatives(self, node, shapes=False, children=False, fullPath=False,
                      noIntermediate=False, **kwargs):
        if shapes:
            entry = self.shapes.get(node)
            return [entry[0]] if entry else None
        return None

    def nodeType(self, node):
        for _transform, (shape, kind) in self.shapes.items():
            if shape == node:
                return kind
        return "transform"

    # --- the operation -----------------------------------------------------
    def polyUnite(self, *args, **kwargs):
        members = list(args[0]) if args and isinstance(args[0], (list, tuple)) else list(args)
        self.calls.append(("polyUnite", tuple(members), kwargs.get("ch")))
        asked = kwargs.get("name") or "polySurface1"
        actual = self._unite_name or asked
        node = "|" + actual
        for m in members:
            if m in self.objects:
                self.objects.remove(m)
            self.shapes.pop(m, None)
        self.objects.append(node)
        self.shapes[node] = (node + "Shape", "mesh")
        return [node, node + "_unite"]

    def polyEvaluate(self, node, **kwargs):
        if kwargs.get("shell"):
            return 2
        if kwargs.get("triangle"):
            return 24
        if kwargs.get("vertex"):
            return 16
        if kwargs.get("face"):
            return 12
        return 0

    def xform(self, node, **kwargs):
        if kwargs.get("query"):
            if kwargs.get("boundingBox"):
                return [-1.5, -1.5, -1.5, 1.5, 1.5, 1.5]
            return [0.0, 0.0, 0.0]
        if "pivots" in kwargs:
            self.pivots[node] = tuple(kwargs["pivots"])
        self.calls.append(("xform", node, None))
        return None

    def exactWorldBoundingBox(self, node):
        return [-1.5, -1.5, -1.5, 1.5, 1.5, 1.5]

    def makeIdentity(self, node, **kwargs):
        self.frozen.append(node)
        self.calls.append(("makeIdentity", node, None))

    def delete(self, node, **kwargs):
        self.deleted.append(node)
        self.calls.append(("delete", node, None))

    def rename(self, node, new):
        self.objects.remove(node)
        renamed = "|" + new
        self.objects.append(renamed)
        self.shapes[renamed] = self.shapes.pop(node, (renamed + "Shape", "mesh"))
        self.calls.append(("rename", node, new))
        return renamed

    # --- shading -----------------------------------------------------------
    def listSets(self, object=None, type=None, **kwargs):
        return self.sg_members.get(object, [])

    def sets(self, *args, **kwargs):
        self.calls.append(("sets", args[0] if args else None, None))
        if kwargs.get("query"):
            return []
        return "|set1"

    def listConnections(self, plug, **kwargs):
        return []


@pytest.fixture(autouse=True)
def _no_checkpoint(monkeypatch):
    from maya_plugin.handlers import session

    monkeypatch.setattr(session, "auto_checkpoint", lambda reason: {"path": "x.ma"})


def _run(fake, **params):
    combine._cmds = lambda: fake  # noqa: SLF001 - the module's only Maya seam
    return combine.combine(params)


class TestCombine:
    def test_merges_two_meshes_into_one(self):
        fake = FakeCmds()
        out = _run(fake, names=["|a", "|b"], name="kit_piece")
        assert out["name"] == "|kit_piece"
        assert ("polyUnite", ("|a", "|b"), False) in [
            (c[0], c[1], c[2]) for c in fake.calls if c[0] == "polyUnite"
        ]

    def test_reports_measured_geometry_not_claims(self):
        out = _run(FakeCmds(), names=["|a", "|b"])
        assert out["tris"] == 24
        assert out["shells"] == 2
        assert out["inputs"] == 2

    def test_re_resolves_when_maya_renames_the_result(self):
        # Maya hands back polySurface7 despite being asked for kit_piece
        fake = FakeCmds(unite_name="polySurface7")
        out = _run(fake, names=["|a", "|b"], name="kit_piece")
        assert out["name"] == "|kit_piece"
        assert ("rename", "|polySurface7", "kit_piece") in fake.calls

    def test_pivot_defaults_to_the_bounding_box_centre(self):
        fake = FakeCmds()
        _run(fake, names=["|a", "|b"], name="p")
        assert fake.pivots  # a pivot was placed, not left where polyUnite put it

    def test_pivot_origin_places_it_at_the_world_origin(self):
        fake = FakeCmds()
        _run(fake, names=["|a", "|b"], name="p", pivot="origin")
        assert list(fake.pivots.values())[0] == (0.0, 0.0, 0.0)

    def test_freeze_is_on_by_default(self):
        fake = FakeCmds()
        _run(fake, names=["|a", "|b"], name="p")
        assert fake.frozen

    def test_freeze_can_be_declined(self):
        fake = FakeCmds()
        _run(fake, names=["|a", "|b"], name="p", freeze=False)
        assert not fake.frozen

    def test_collapses_shading_to_one_object_level_group(self):
        fake = FakeCmds()
        out = _run(fake, names=["|a", "|b"], name="p")
        assert "shading" in out

    def test_rejects_fewer_than_two_inputs(self):
        with pytest.raises(HandlerError):
            _run(FakeCmds(), names=["|a"])

    def test_rejects_a_missing_object(self):
        with pytest.raises(HandlerError):
            _run(FakeCmds(), names=["|a", "|nope"])

    def test_rejects_a_non_mesh_input(self):
        fake = FakeCmds(objects=("|a", "|curve1"),
                        shapes={"|a": ("|aShape", "mesh"),
                                "|curve1": ("|curve1Shape", "nurbsCurve")})
        with pytest.raises(HandlerError) as excinfo:
            _run(fake, names=["|a", "|curve1"])
        assert "mesh" in str(excinfo.value).lower()

    def test_rejects_duplicate_names_in_the_input_list(self):
        with pytest.raises(HandlerError):
            _run(FakeCmds(), names=["|a", "|a"])
