"""get_object_info section readers against a fake cmds - no Maya required."""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import objinfo


class FakeCmds:
    """#799: every answer here is MODELLED, and a node this scene does not
    hold raises the way Maya raises.

    Before #799 `nodeType` ended in a bare `return "mesh"`, so it could not
    fail a test whatever it was asked about - including a node that had been
    deleted, which real Maya answers with
    RuntimeError("No object matches name: ..."). That is the exact shape of
    the three blocking defects #796 shipped past a green suite.

    Round 2 removed two methods that were DEAD here rather than guarded:
    `objExists` (naming.require_object resolves through `ls`, and objinfo.py
    never calls objExists - see ls() below) and `polyEvaluate` (mesh stats go
    through meshcheck.mesh_stats, which imports maya.cmds itself and is
    monkeypatched, so this fake's polyEvaluate answered a constant 1 to
    nobody). Deleting either changed no test, which is how they were found.
    Dead surface on a fake is not neutral: it is read as the guarded surface.
    """

    def __init__(self, linear="cm"):
        self.linear = linear
        self.objects = {"|golem|torso"}
        self.shapes = {"|golem|torso": "|golem|torso|torsoShape"}
        # Every DG node this scene holds, and its type. `nodeType` answers
        # from here and from nowhere else; a name that is not in it either
        # was deleted or never existed, and both raise.
        self.node_types = {
            "|golem|torso": "transform",
            "|golem|torso|torsoShape": "mesh",
            "clay_SG": "shadingEngine",
            "clay_mat": "lambert",
            "polySoftEdge1": "polySoftEdge",
        }
        self.deleted = []
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
        self.transforms = {
            "|golem|torso": {"translate": [1.0, 2.0, 3.0],
                             "rotate": [0.0, 90.0, 0.0],
                             "scale": [1.0, 1.0, 1.0]},
        }
        self.uv_sets = {"|golem|torso|torsoShape": ["map1"]}
        self.history = {"|golem|torso|torsoShape":
                        ["|golem|torso|torsoShape", "polySoftEdge1"]}

    # --- existence -------------------------------------------------------
    def _require(self, node):
        """#799 contract point 1: a query about a node the scene does not
        hold raises. Every cmds call below routes through here first, so a
        handler that keeps asking about something it deleted (or never
        resolved) fails here instead of being handed a plausible default.

        Existence is decided by `node_types` ALONE, never by a tombstone
        list. #799 round 2: a permanent tombstone makes a node re-created
        under a previously-deleted name invisible forever, which Maya
        certainly does not do - strict-direction wrongness that produces
        spurious failures the next person "fixes" by weakening the fake."""
        name = str(node).split(".")[0]
        if name not in self.node_types:
            raise RuntimeError("No object matches name: %s" % name)
        return name

    def delete(self, *names):
        """#799 round 2, finding 5: deletion is SHAPE-granular, and a
        transform takes its shape down with it the way Maya's `delete`
        does. Round 1 recorded names against a tombstone list that only
        `_require`'s transform-level check consulted, so after
        `delete("|golem|torso|torsoShape")` the shape was still handed back
        by `listRelatives` and a handler holding it across the delete would
        have been given a live-looking name."""
        for name in names:
            self.deleted.append(name)  # audit log only; nothing resolves against it
            doomed = {name}
            if name in self.shapes:
                doomed.add(self.shapes[name])   # a transform's shape dies with it
            for gone in doomed:
                self.node_types.pop(gone, None)
                self.objects.discard(gone)
                self.transforms.pop(gone, None)
                self.uv_sets.pop(gone, None)
                self.history.pop(gone, None)
                self._shape_sgs.pop(gone, None)
            self.shapes = {t: s for t, s in self.shapes.items()
                           if t not in doomed and s not in doomed}

    def ls(self, name=None, long=False, **kw):
        # `ls` is the non-raising query: an unmatched pattern is an empty
        # result, not an error. That is why require_object can turn a
        # vanished name into a HandlerError instead of a traceback.
        #
        # #799 round 2, finding 4: an `objExists` method used to sit beside
        # this one, and it was DEAD - naming.require_object (naming.py:28)
        # resolves through `cmds.ls(name, long=True)`, and objinfo.py never
        # calls objExists at all. `delattr(FakeCmds, "objExists")` changed
        # no test. Removed rather than kept as decoration a future reader
        # would mistake for the guarded surface; `ls` IS that surface.
        return [o for o in self.objects
                if (o == name or o.split("|")[-1] == name)]

    # --- reads -----------------------------------------------------------
    def listRelatives(self, node, shapes=False, fullPath=False, noIntermediate=False):
        self._require(node)
        assert shapes and fullPath and noIntermediate, (
            "get_object_info resolves shapes one way only")
        return [self.shapes[node]] if node in self.shapes else None

    def nodeType(self, node):
        return self.node_types[self._require(node)]

    def xform(self, name, query=False, worldSpace=False, **kw):
        self._require(name)
        assert query and worldSpace, "get_object_info must only QUERY transforms"
        values = self.transforms[name]
        for flag, channel in (("translation", "translate"),
                              ("rotation", "rotate"), ("scale", "scale")):
            if kw.get(flag):
                return list(values[channel])
        if kw.get("matrix"):
            # #831: the world matrix's translation row is where the ORIGIN
            # is; it differs from `translate` once a pivot sits off it. A
            # test declares it; undeclared, the origin is the translate,
            # which is Maya's answer for a node with its pivot at home.
            origin = values.get("world_position", values["translate"])
            return [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
                    0.0, 0.0, 1.0, 0.0] + list(origin) + [1.0]
        raise AssertionError("unexpected xform query %r" % (kw,))

    def listSets(self, object=None, type=None):
        self._require(object)
        assert type == 1, "shading membership is the render-set query"
        return list(self._shape_sgs.get(object, []))

    def sets(self, sg, query=False, **kw):
        # #799 round 2: `cmds.sets(node, ...)` without `query` is the EDIT
        # form - it adds to / creates a set. _shading_section only ever asks
        # who is in one, so a write reaching here is a defect, not a read to
        # be answered with the membership list.
        self._require(sg)
        assert query and not kw, (
            "shading membership is a QUERY; cmds.sets without it EDITS the set (%r)"
            % (kw,))
        return list(self.set_members.get(sg, []))

    def listConnections(self, node, source=True, destination=False, type=None):
        self._require(node)
        return list(self.connections.get(node, []))

    def polyUVSet(self, name, query=False, allUVSets=False):
        self._require(name)
        assert query and allUVSets
        return list(self.uv_sets.get(name, []))

    def listHistory(self, node):
        self._require(node)
        return list(self.history.get(node, [node]))

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


def test_the_transform_section_says_where_the_origin_is(monkeypatch):
    """#831: `translate` is the channel. On an object scaled or turned about
    a pivot off its origin the origin is somewhere else, and only the world
    matrix knows where - the section carries it as world_position, the
    same field transform's result has."""
    fake = FakeCmds()
    fake.transforms["|golem|torso"]["world_position"] = [36.44, 68.34, 0.0]
    monkeypatch.setattr(objinfo, "_cmds", lambda: fake)
    result = objinfo.get_object_info({"name": "|golem|torso", "include": ["transform"]})
    assert result["transform"]["translate"] == [1.0, 2.0, 3.0]
    assert result["transform"]["world_position"] == [36.44, 68.34, 0.0]


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


def test_history_reports_the_real_node_types(monkeypatch):
    # #799: no test reached _history_section at all while FakeCmds.nodeType
    # ended in an unconditional `return "mesh"` - it could not tell one
    # history node from another, so the de-duplicating loop that section is
    # made of had nothing to de-duplicate and no test to fail.
    fake = FakeCmds()
    monkeypatch.setattr(objinfo, "_cmds", lambda: fake)
    result = objinfo.get_object_info({"name": "|golem|torso", "include": ["history"]})
    assert result["history"]["node_count"] == 2
    assert result["history"]["node_types"] == ["mesh", "polySoftEdge"]


def test_uv_sets_are_reported_by_name_and_count(monkeypatch):
    # The other section #799 found with no test of its own.
    fake = FakeCmds()
    monkeypatch.setattr(objinfo, "_cmds", lambda: fake)
    result = objinfo.get_object_info({"name": "|golem|torso", "include": ["uvs"]})
    assert result["uvs"] == {"uv_sets": ["map1"], "count": 1}


def test_a_group_refuses_the_sections_that_need_a_shape(monkeypatch):
    # A shape-less transform reaches listRelatives and gets None back; every
    # section after that would have been handed `shape=None`. #799: with the
    # fake raising on anything it does not model, this branch is the only
    # thing standing between a group and a cmds call on None.
    fake = FakeCmds()
    fake.node_types["|golem"] = "transform"
    fake.objects.add("|golem")
    fake.transforms["|golem"] = {"translate": [0.0, 0.0, 0.0],
                                 "rotate": [0.0, 0.0, 0.0],
                                 "scale": [1.0, 1.0, 1.0]}
    monkeypatch.setattr(objinfo, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        objinfo.get_object_info({"name": "|golem", "include": ["shading"]})
    assert "no shape node" in str(exc.value)
    # and the transform section alone is still legal on the same object
    assert objinfo.get_object_info(
        {"name": "|golem", "include": ["transform"]})["name"] == "|golem"


def test_a_deleted_object_is_refused_before_anything_is_queried(monkeypatch):
    # #799 contract point 1. require_object resolves through `ls`, which
    # answers an empty list rather than raising, so the caller gets a
    # HandlerError with a hint - NOT the RuntimeError every other query on
    # this fake now raises. That ordering is the whole reason a vanished
    # node is safe here, and nothing pinned it before.
    fake = FakeCmds()
    fake.transforms["|golem"] = {"translate": [0.0, 0.0, 0.0],
                                 "rotate": [0.0, 0.0, 0.0],
                                 "scale": [1.0, 1.0, 1.0]}
    fake.node_types["|golem"] = "transform"
    fake.objects.add("|golem")
    monkeypatch.setattr(objinfo, "_cmds", lambda: fake)
    fake.delete("|golem")
    with pytest.raises(HandlerError) as exc:
        objinfo.get_object_info({"name": "|golem", "include": ["transform"]})
    assert "not found" in str(exc.value)


def test_per_face_membership_is_reported(monkeypatch):
    # M1 established that per-face shading is unreliable; get_object_info must
    # surface it rather than hide it, because a caller seeing one SG would
    # otherwise assume healthy object-level assignment.
    fake = FakeCmds()
    fake.set_members["clay_SG"] = ["|golem|torso|torsoShape.f[0:5]"]
    monkeypatch.setattr(objinfo, "_cmds", lambda: fake)
    result = objinfo.get_object_info({"name": "|golem|torso", "include": ["shading"]})
    assert result["shading"]["per_face"] is True


class TestTheFakeRefusesWhatMayaRefuses:
    """#799 round 2: the round-1 hardening had no test of its own, so
    reverting it left the suite green - "a green suite proves nothing", one
    level up. These assert the contract points THIS fake models.

    objinfo.py holds no plug write: its whole surface is listRelatives,
    three `xform` QUERIES, listSets, sets, listConnections, polyUVSet,
    listHistory and nodeType (grep over the handler confirms - the only
    xform calls are the query=True, worldSpace=True reads at objinfo.py:
    41-43). So there is no connection-fed or locked plug and no
    setKeyframe to model here; those barriers belong to the fakes that own
    those calls. What this fake CAN be asked wrongly is a node that is
    gone, a shape that is gone, and a query flag turned into an edit.
    """

    def _fake(self):
        fake = FakeCmds()
        fake.node_types["|golem"] = "transform"
        fake.objects.add("|golem")
        return fake

    # --- contract point 1: a node the scene does not hold ----------------
    def test_a_query_about_a_node_that_never_existed_raises(self):
        # nodeType's round-1 fix. Before it, this method ended in a bare
        # `return "mesh"` and could not fail whatever it was asked about.
        with pytest.raises(RuntimeError, match="No object matches name"):
            self._fake().nodeType("|never|existed")

    def test_a_query_about_a_deleted_node_raises(self):
        fake = self._fake()
        fake.delete("|golem|torso")
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.nodeType("|golem|torso")

    def test_every_read_routes_through_the_existence_check(self):
        # Not just nodeType: each modelled read must refuse the ghost, or
        # the guard is one method wide.
        fake = self._fake()
        ghost = "|golem|ghost"
        for call in (
            lambda: fake.listRelatives(ghost, shapes=True, fullPath=True,
                                       noIntermediate=True),
            lambda: fake.xform(ghost, query=True, worldSpace=True, translation=True),
            lambda: fake.listSets(object=ghost, type=1),
            lambda: fake.sets(ghost, query=True),
            lambda: fake.listConnections(ghost + ".surfaceShader", source=True),
            lambda: fake.polyUVSet(ghost, query=True, allUVSets=True),
            lambda: fake.listHistory(ghost),
        ):
            with pytest.raises(RuntimeError, match="No object matches name"):
                call()

    # --- contract point 1, finding 5: deletion is SHAPE-granular ---------
    def test_a_deleted_shape_is_not_still_handed_back_by_listrelatives(self):
        # Round 1 recorded deletions against the TRANSFORM table only, so
        # after this delete the shape name was still returned here and
        # still answered `nodeType` with "mesh". A handler that resolved a
        # shape and kept it across a delete was handed a live-looking name.
        fake = self._fake()
        fake.delete("|golem|torso|torsoShape")
        assert fake.listRelatives("|golem|torso", shapes=True, fullPath=True,
                                  noIntermediate=True) is None
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.nodeType("|golem|torso|torsoShape")

    def test_deleting_a_transform_takes_its_shape_with_it(self):
        # Maya's `delete` on a transform deletes the shape beneath it.
        fake = self._fake()
        fake.delete("|golem|torso")
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.nodeType("|golem|torso|torsoShape")

    def test_a_deleted_transform_is_gone_from_ls_too(self):
        # `ls` is the non-raising query, so it must ANSWER - with nothing.
        fake = self._fake()
        fake.delete("|golem|torso")
        assert fake.ls("|golem|torso", long=True) == []

    def test_deleting_a_name_does_not_tombstone_it_forever(self):
        # Strict-direction wrongness is as bad as permissive: Maya lets a
        # name be reused after a delete, and a fake that remembered the
        # deletion forever would refuse a node standing right there.
        fake = self._fake()
        fake.delete("|golem|torso")
        fake.node_types["|golem|torso"] = "transform"
        fake.objects.add("|golem|torso")
        assert fake.nodeType("|golem|torso") == "transform"
        assert fake.ls("|golem|torso", long=True) == ["|golem|torso"]

    # --- contract point 2: a query flag that is really an edit -----------
    def test_a_set_EDIT_is_refused_rather_than_answered_as_a_read(self):
        # cmds.sets(sg) without query is the edit form - it would add to
        # the shading group. _shading_section only ever asks who is in one.
        fake = self._fake()
        with pytest.raises(AssertionError, match="QUERY"):
            fake.sets("clay_SG")
        with pytest.raises(AssertionError, match="QUERY"):
            fake.sets("clay_SG", add="|golem|torso|torsoShape")

    def test_the_read_the_handler_really_makes_still_answers(self):
        # The counterpart, so nobody tightens the guard into refusing the
        # live call - a fake wrong in the strict direction produces
        # spurious failures that get "fixed" by weakening it back.
        assert self._fake().sets("clay_SG", query=True) == [
            "|golem|torso|torsoShape"]

    def test_a_transform_write_is_refused_not_answered_with_a_stale_read(self):
        fake = self._fake()
        with pytest.raises(AssertionError, match="only QUERY"):
            fake.xform("|golem|torso", worldSpace=True, translation=(9, 9, 9))
        assert fake.transforms["|golem|torso"]["translate"] == [1.0, 2.0, 3.0]

    def test_an_object_space_transform_read_is_refused(self):
        fake = self._fake()
        with pytest.raises(AssertionError, match="only QUERY"):
            fake.xform("|golem|torso", query=True, translation=True)

    # --- contract point 3: no answers-anything fallback ------------------
    def test_shapes_are_resolved_one_way_only(self):
        # Dropping fullPath returns short names (ambiguous across a scene)
        # and dropping noIntermediate picks up *Orig shapes; both are
        # refused rather than answered with the one shape this fake holds.
        fake = self._fake()
        with pytest.raises(AssertionError, match="one way only"):
            fake.listRelatives("|golem|torso", shapes=True, noIntermediate=True)
        with pytest.raises(AssertionError, match="one way only"):
            fake.listRelatives("|golem|torso", shapes=True, fullPath=True)

    def test_the_unit_query_refuses_anything_but_the_linear_unit(self):
        with pytest.raises(AssertionError, match="only QUERY the unit"):
            self._fake().currentUnit(query=False, linear="m")

    def test_shading_membership_is_the_render_set_query_only(self):
        fake = self._fake()
        with pytest.raises(AssertionError, match="render-set query"):
            fake.listSets(object="|golem|torso|torsoShape", type=2)
