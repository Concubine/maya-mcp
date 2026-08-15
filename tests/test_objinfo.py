"""get_object_info section readers against a fake cmds - no Maya required."""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import objinfo


class FakeCmds:
    def __init__(self, linear="cm"):
        self.linear = linear
        self.objects = {"|golem|torso"}
        self.shapes = {"|golem|torso": "|golem|torso|torsoShape"}
        # Named _shape_sgs (not `sets`) deliberately: an instance attribute
        # named `sets` would shadow the `sets()` method below on this same
        # instance (instance attrs take precedence over class methods in
        # attribute lookup), breaking every cmds.sets(...) call with
        # "'dict' object is not callable".
        self._shape_sgs = {"|golem|torso|torsoShape": ["clay_SG"]}
        self.set_members = {"clay_SG": ["|golem|torso|torsoShape"]}
        # Keyed by the .surfaceShader plug, matching production's
        # cmds.listConnections(sg + ".surfaceShader", ...) - the same idiom
        # scene.py/meshcheck.py use to look up a shading group's material.
        self.connections = {"clay_SG.surfaceShader": ["clay_mat"]}

    def ls(self, name=None, long=False, **kw):
        return [o for o in self.objects if o == name or o.split("|")[-1] == name]

    def listRelatives(self, node, shapes=False, fullPath=False, noIntermediate=False):
        return [self.shapes[node]] if node in self.shapes else None

    def nodeType(self, node):
        return "mesh"

    def xform(self, name, query=False, worldSpace=False, **kw):
        if kw.get("translation"):
            return [1.0, 2.0, 3.0]
        if kw.get("rotation"):
            return [0.0, 90.0, 0.0]
        return [1.0, 1.0, 1.0]

    def listSets(self, object=None, type=None):
        return list(self._shape_sgs.get(object, []))

    def sets(self, sg, query=False):
        return list(self.set_members.get(sg, []))

    def listConnections(self, node, source=True, destination=False, type=None):
        return list(self.connections.get(node, []))

    def polyEvaluate(self, name, uvSetCount=False, **kw):
        return 1

    def polyUVSet(self, name, query=False, allUVSets=False):
        return ["map1"]

    def listHistory(self, node):
        return [node, "polySoftEdge1"]

    def currentUnit(self, query=False, linear=None):
        assert query and linear is True, "get_object_info must only QUERY the unit"
        return self.linear


def test_shading_section_reports_the_assigned_material(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(objinfo, "_cmds", lambda: fake)
    result = objinfo.get_object_info({"name": "|golem|torso", "include": ["shading"]})
    assert result["shading"]["shading_groups"] == ["clay_SG"]
    assert result["shading"]["materials"] == ["clay_mat"]
    assert result["shading"]["per_face"] is False


def test_default_include_is_transform_and_mesh_stats(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(objinfo, "_cmds", lambda: fake)
    monkeypatch.setattr(objinfo, "_mesh_stats", lambda shape: {"tris": 12})
    result = objinfo.get_object_info({"name": "|golem|torso"})
    # `units` is not a section - it is unconditional, because `translate` below
    # is a bare triple without it (maya-mcp #634).
    assert set(result) == {"name", "transform", "mesh_stats", "units"}
    assert result["transform"]["translate"] == [1.0, 2.0, 3.0]


def test_the_transform_it_reports_is_never_unitless(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(objinfo, "_cmds", lambda: fake)
    result = objinfo.get_object_info({"name": "|golem|torso", "include": ["transform"]})
    assert result["units"] == {"linear_unit": "cm", "export_metres_per_unit": 1.0}


def test_a_metre_scene_says_so(monkeypatch):
    fake = FakeCmds(linear="m")
    monkeypatch.setattr(objinfo, "_cmds", lambda: fake)
    result = objinfo.get_object_info({"name": "|golem|torso", "include": ["transform"]})
    assert result["units"]["export_metres_per_unit"] == 100.0


def test_units_reported_even_when_no_geometry_section_was_asked_for(monkeypatch):
    # A caller asking only for shading still gets the unit: it costs one query
    # and removes any path where a response's numbers could be read blind.
    fake = FakeCmds()
    monkeypatch.setattr(objinfo, "_cmds", lambda: fake)
    result = objinfo.get_object_info({"name": "|golem|torso", "include": ["shading"]})
    assert result["units"]["linear_unit"] == "cm"


def test_unknown_section_is_rejected_with_the_valid_list(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(objinfo, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        objinfo.get_object_info({"name": "|golem|torso", "include": ["vertices"]})
    assert "mesh_stats" in exc.value.hint


def test_per_face_membership_is_reported(monkeypatch):
    # M1 established that per-face shading is unreliable; get_object_info must
    # surface it rather than hide it, because a caller seeing one SG would
    # otherwise assume healthy object-level assignment.
    fake = FakeCmds()
    fake.set_members["clay_SG"] = ["|golem|torso|torsoShape.f[0:5]"]
    monkeypatch.setattr(objinfo, "_cmds", lambda: fake)
    result = objinfo.get_object_info({"name": "|golem|torso", "include": ["shading"]})
    assert result["shading"]["per_face"] is True
