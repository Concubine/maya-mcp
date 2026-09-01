"""get_scene_graph handler tests against a fake `cmds` — no Maya required.

The fake implements exactly the cmds surface the handler is allowed to touch;
anything else raises, which keeps the handler honest about its API footprint.
"""

import pytest

from maya_plugin.handlers import scene


class FakeCmds:
    """A tiny Maya scene: a golem group with two meshes, a light, default cameras."""

    def __init__(self, linear="cm"):
        self.linear = linear
        self.heavy_calls = 0  # polyEvaluate + exactWorldBoundingBox invocations
        self.transforms = {
            "|persp": {}, "|top": {}, "|front": {}, "|side": {},  # default cams
            "|golem": {"shape": None, "parent": None, "visible": True},
            "|golem|torso": {
                "shape": ("|golem|torso|torsoShape", "mesh"),
                "parent": "|golem", "visible": True,
                "tris": 500, "verts": 260, "material": "clay_mat",
                "bbox": [-1.0, 0.0, -0.5, 1.0, 2.0, 0.5],
            },
            "|golem|head": {
                "shape": ("|golem|head|headShape", "mesh"),
                "parent": "|golem", "visible": False,
                "tris": 200, "verts": 110, "material": None,
                "bbox": [-0.4, 2.0, -0.4, 0.4, 2.8, 0.4],
            },
            "|keyLight": {
                "shape": ("|keyLight|keyLightShape", "pointLight"),
                "parent": None, "visible": True,
                "bbox": [-0.1, 3.0, -0.1, 0.1, 3.2, 0.1],
            },
        }
        self._shape_owner = {
            v["shape"][0]: k
            for k, v in self.transforms.items()
            if v.get("shape")
        }
        # Every shading group this scene holds, and the material it drives.
        # #799 round 2, finding 5: the `.surfaceShader` branch of
        # listConnections used to DERIVE its answer from the plug string
        # ("|ghostSG.surfaceShader" -> ["ghost"]), so it named a material
        # for a shading group that had never existed - an answers-anything
        # path the round-1 pass did not reach.
        self.shading_groups = {
            "%sSG" % info["material"]: info["material"]
            for info in self.transforms.values() if info.get("material")
        }
        # An audit log of what `delete` took. NOTHING resolves against it:
        # existence is decided by the tables alone, so a name re-created
        # after a delete is visible again, as it is in Maya. A permanent
        # tombstone here would be strict-direction wrongness - the kind
        # that produces spurious failures the next person "fixes" by
        # weakening the fake back.
        self.deleted = []

    # --- existence -------------------------------------------------------
    def _require(self, node, table=None):
        """Maya's answer to a query about a node that was deleted or never
        existed: RuntimeError("No object matches name: ..."). Before #799
        this fake raised KeyError for the same case - close enough to fail a
        test by accident, not close enough to be the failure a handler will
        actually meet, and nothing at all for the DEFAULT branches below,
        which simply answered."""
        table = self.transforms if table is None else table
        if node not in table:
            raise RuntimeError("No object matches name: %s" % node)
        return node

    def delete(self, *names):
        """#799 round 2, finding 5: deletion is SHAPE-granular now.

        Round 1 recorded every deleted name against the `transforms` table,
        so a deleted SHAPE could not be expressed at all: after
        `delete("|golem|head|headShape")`, `nodeType` still answered "mesh"
        and `polyEvaluate` still answered 200. Deleting a transform takes
        its shape with it, the way Maya's `delete` does."""
        for name in names:
            self.deleted.append(name)  # audit log only
            info = self.transforms.pop(name, None)
            if info and info.get("shape"):
                self._shape_owner.pop(info["shape"][0], None)
            # A shape deleted on its own leaves its transform standing, but
            # shapeless - which is exactly how a group behaves.
            #
            # Its `bbox` deliberately STAYS. Dropping it was tried and
            # reverted: get_scene_graph calls exactWorldBoundingBox on every
            # object it pages, so a shapeless transform with no modelled box
            # turned a legitimate handler call into an AssertionError. What
            # Maya really answers for a shapeless transform is unmeasured,
            # and refusing a call the handler is entitled to make is
            # strict-direction wrongness - as bad as a permissive fake, and
            # worse in one way: it produces a spurious failure the next
            # person "fixes" by weakening the fake back.
            owner = self._shape_owner.pop(name, None)
            if owner is not None and owner in self.transforms:
                self.transforms[owner] = dict(self.transforms[owner], shape=None)

    def ls(self, type=None, long=False):
        assert type == "transform" and long
        return list(self.transforms)

    def listRelatives(self, node, shapes=False, parent=False, fullPath=False,
                      noIntermediate=False):
        assert fullPath
        if shapes:
            assert noIntermediate  # never pick *Orig intermediate shapes
        info = self.transforms[self._require(node)]
        if shapes:
            return [info["shape"][0]] if info.get("shape") else None
        if parent:
            return [info["parent"]] if info.get("parent") else None
        raise AssertionError("unexpected listRelatives call")

    def nodeType(self, node):
        # #799: modelled for BOTH kinds of name the handler can hold - a
        # shape (which is what _shape_and_type asks about) and a transform
        # (which nothing asks about today, and which used to KeyError). A
        # name that is neither raises.
        if node in self._shape_owner:
            return self.transforms[self._require_shape(node)]["shape"][1]
        if node in self.transforms:
            return "transform"
        raise RuntimeError("No object matches name: %s" % node)

    def _require_shape(self, shape):
        # #799 round 2, finding 5: existence is decided by _shape_owner,
        # which `delete` now prunes - so a SHAPE deleted on its own stops
        # answering here too, not just a shape whose transform went with it.
        owner = self._shape_owner.get(shape)
        if owner is None or owner not in self.transforms:
            raise RuntimeError("No object matches name: %s" % shape)
        return owner

    def polyEvaluate(self, shape, triangle=False, vertex=False):
        self.heavy_calls += 1
        info = self.transforms[self._require_shape(shape)]
        if triangle:
            return info["tris"]
        if vertex:
            return info["verts"]
        raise AssertionError("unexpected polyEvaluate call")

    def exactWorldBoundingBox(self, node):
        """The union over the transform AND its descendants, hidden ones
        included.

        #799 replaces an unconditional `[0, 0, 0, 0, 0, 0]` fallback, which
        made every group in this scene report a zero-sized box at the origin
        and could never fail. MEASURED in #640 (see
        maya-bbox-and-sheet-framing-traps): the unflagged call includes a
        transform's children REGARDLESS of their visibility - which is why
        `|golem` here has to cover `|golem|head` even though head is hidden.
        The inverted 1e20 sentinel is the `ignoreInvisible=True` answer only,
        and get_scene_graph never passes that flag, so it cannot appear here.
        """
        self._require(node)
        self.heavy_calls += 1
        boxes = [info["bbox"] for name, info in self.transforms.items()
                 if "bbox" in info
                 and (name == node or name.startswith(node + "|"))]
        if not boxes:
            # A group with nothing under it: Maya answers the sentinel here
            # too, but nothing in this scene is empty and inventing the case
            # would be modelling an unmeasured shape.
            raise AssertionError("no modelled bbox anywhere under %r" % node)
        return [min(b[i] for b in boxes) for i in range(3)] + \
               [max(b[i] for b in boxes) for i in range(3, 6)]

    def listConnections(self, node, type=None):
        if type == "shadingEngine":
            mat = self.transforms[self._require_shape(node)].get("material")
            return ["%sSG" % mat] if mat else None
        if node.endswith(".surfaceShader"):
            # #799 round 2, finding 5: this used to DERIVE a material name
            # from the plug string, so `listConnections("|ghostSG.surfaceShader")`
            # confidently answered ["ghost"] for a shading group that had
            # never existed - the last answers-anything path in this fake.
            # Modelled from the scene now: an unknown SG raises the way Maya
            # raises for a plug on a node that is not there.
            sg = node[:-len(".surfaceShader")]
            if sg not in self.shading_groups:
                raise RuntimeError("No object matches name: %s" % sg)
            return [self.shading_groups[sg]]
        raise AssertionError("unexpected listConnections call: %r %r" % (node, type))

    def getAttr(self, attr):
        node, _, plug = attr.rpartition(".")
        assert plug == "visibility", "get_scene_graph reads one attribute"
        return self.transforms[self._require(node)]["visible"]

    def currentUnit(self, query=False, linear=None):
        assert query and linear is True, "get_scene_graph must only QUERY the unit"
        return self.linear


@pytest.fixture
def fake_cmds(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(scene, "_cmds", lambda: fake)
    return fake


class TestSceneGraph:
    def test_lists_objects_with_canonical_long_names_and_stats(self, fake_cmds):
        result = scene.get_scene_graph({})
        names = {o["name"] for o in result["objects"]}
        assert "|golem|torso" in names and "|golem" in names
        torso = next(o for o in result["objects"] if o["name"] == "|golem|torso")
        assert torso["type"] == "mesh"
        assert torso["tris"] == 500 and torso["verts"] == 260
        assert torso["bbox_min"] == [-1.0, 0.0, -0.5]
        assert torso["bbox_max"] == [1.0, 2.0, 0.5]
        assert torso["material"] == "clay_mat"
        assert torso["parent"] == "|golem"
        assert torso["visible"] is True

    def test_default_cameras_excluded(self, fake_cmds):
        names = {o["name"] for o in scene.get_scene_graph({})["objects"]}
        assert names.isdisjoint({"|persp", "|top", "|front", "|side"})

    def test_group_without_shape_is_typed_group(self, fake_cmds):
        golem = next(
            o for o in scene.get_scene_graph({})["objects"] if o["name"] == "|golem"
        )
        assert golem["type"] == "group"
        assert golem["tris"] is None

    def test_filter_matches_type_case_insensitive(self, fake_cmds):
        result = scene.get_scene_graph({"filter": "MESH"})
        assert {o["name"] for o in result["objects"]} == {"|golem|torso", "|golem|head"}
        assert result["total"] == 2

    def test_filter_matches_name_substring(self, fake_cmds):
        result = scene.get_scene_graph({"filter": "head"})
        assert [o["name"] for o in result["objects"]] == ["|golem|head"]

    def test_light_type_comes_from_shape(self, fake_cmds):
        light = next(
            o for o in scene.get_scene_graph({})["objects"] if o["name"] == "|keyLight"
        )
        assert light["type"] == "pointLight"

    def test_invisible_object_reported_not_hidden(self, fake_cmds):
        head = next(
            o for o in scene.get_scene_graph({})["objects"] if o["name"] == "|golem|head"
        )
        assert head["visible"] is False

    def test_a_groups_box_spans_its_hidden_child(self, fake_cmds):
        # #799: the fake used to answer every group with a zero-sized box at
        # the origin, so no test could see what the box actually contains.
        # #640 MEASURED that the unflagged exactWorldBoundingBox includes
        # children whatever their visibility, and |golem|head is hidden - so
        # the group's reported box reaches up to the head, not just the
        # torso. A caller framing on this number is framing on geometry it
        # cannot see; the per-object `visible` flag is the only thing that
        # says so.
        golem = next(
            o for o in scene.get_scene_graph({})["objects"] if o["name"] == "|golem"
        )
        assert golem["bbox_max"] == [1.0, 2.8, 0.5]   # 2.8 is the HIDDEN head
        assert golem["bbox_min"] == [-1.0, 0.0, -0.5]

    def test_a_deleted_object_is_never_queried(self, fake_cmds):
        # #799 contract point 1: get_scene_graph is safe against a vanished
        # node only because `ls` is the sole source of names and every query
        # after it is about something ls just returned. With the fake now
        # raising on a deleted node, a handler that cached names across the
        # cheap and expensive passes would fail here.
        fake_cmds.delete("|golem|head")
        names = {o["name"] for o in scene.get_scene_graph({})["objects"]}
        assert names == {"|golem", "|golem|torso", "|keyLight"}

    def test_no_component_data_ever(self, fake_cmds):
        for obj in scene.get_scene_graph({})["objects"]:
            assert set(obj) == {
                "name", "type", "tris", "verts", "bbox_min", "bbox_max",
                "material", "parent", "visible",
            }


class TestPagination:
    def test_pagination_pages_through_deterministically(self, fake_cmds):
        page1 = scene.get_scene_graph({"max_objects": 2})
        assert len(page1["objects"]) == 2
        assert page1["total"] == 4
        assert page1["cursor"] is not None

        page2 = scene.get_scene_graph({"max_objects": 2, "cursor": page1["cursor"]})
        assert len(page2["objects"]) == 2
        assert page2["cursor"] is None
        all_names = [o["name"] for o in page1["objects"] + page2["objects"]]
        assert len(set(all_names)) == 4

    def test_bad_cursor_is_handler_error_with_hint(self, fake_cmds):
        from maya_plugin.dispatcher import HandlerError

        with pytest.raises(HandlerError, match="cursor"):
            scene.get_scene_graph({"cursor": "garbage"})

    def test_heavy_stats_only_computed_for_page_items(self, fake_cmds):
        # Pagination must bound WORK, not just bytes: polyEvaluate and
        # exactWorldBoundingBox run only for the page being returned.
        # Page 1 of size 2 (sorted): |golem (group) + |golem|head (mesh)
        # => 1 bbox per page item (2) + tri/vert polyEvaluate for the one mesh (2).
        result = scene.get_scene_graph({"max_objects": 2})
        assert [o["name"] for o in result["objects"]] == ["|golem", "|golem|head"]
        assert fake_cmds.heavy_calls == 4

    def test_filtered_page_does_not_stat_offpage_matches(self, fake_cmds):
        result = scene.get_scene_graph({"filter": "mesh", "max_objects": 1})
        assert result["total"] == 2
        assert len(result["objects"]) == 1
        # bbox+tris+verts for the single page item only
        assert fake_cmds.heavy_calls == 3


class TestSceneGraphReportsItsUnit:
    """maya-mcp #634 - the bboxes above are unitless without this."""

    def test_every_response_carries_the_scenes_unit(self, fake_cmds):
        result = scene.get_scene_graph({})
        assert result["units"] == {"linear_unit": "cm", "export_metres_per_unit": 1.0}

    def test_a_metre_scene_is_reported_as_a_hundred_metres_per_unit(self, monkeypatch):
        # The same bbox numbers, a delivery 100x too large. Only this field
        # tells them apart - no in-Maya measurement can (see #629).
        fake = FakeCmds(linear="m")
        monkeypatch.setattr(scene, "_cmds", lambda: fake)
        result = scene.get_scene_graph({})
        assert result["units"]["export_metres_per_unit"] == 100.0

    def test_the_unit_is_reported_on_every_page_not_just_the_first(self, fake_cmds):
        page1 = scene.get_scene_graph({"max_objects": 2})
        page2 = scene.get_scene_graph({"max_objects": 2, "cursor": page1["cursor"]})
        assert page2["units"] == page1["units"]

    def test_an_empty_result_still_reports_the_unit(self, fake_cmds):
        result = scene.get_scene_graph({"filter": "nothing_matches_this"})
        assert result["objects"] == [] and result["total"] == 0
        assert result["units"]["linear_unit"] == "cm"


class TestTheFakeRefusesWhatMayaRefuses:
    """#799 round 2: nothing asserted the round-1 hardening, so reverting
    every behavioural change in this fake left the suite fully green - "a
    green suite proves nothing", moved up one level into the harness. If
    someone loosens this fake later, these go red.

    Only what THIS fake models. scene.py's Maya surface is `ls`,
    listRelatives, nodeType, polyEvaluate, exactWorldBoundingBox,
    listConnections, getAttr and currentUnit - all reads. There is no
    setAttr, no xform, no connectAttr and no setKeyframe anywhere in it, so
    there is no connection-fed or locked plug to refuse in either compound
    direction and no driven-key source to classify; those barriers belong
    to the fakes that own those calls.
    """

    # --- contract point 1: a node the scene does not hold ----------------
    def test_a_query_about_a_node_that_never_existed_raises(self, fake_cmds):
        for call in (
            lambda: fake_cmds.listRelatives("|nope", shapes=True, fullPath=True,
                                            noIntermediate=True),
            lambda: fake_cmds.nodeType("|nope"),
            lambda: fake_cmds.polyEvaluate("|nope|nopeShape", triangle=True),
            lambda: fake_cmds.exactWorldBoundingBox("|nope"),
            lambda: fake_cmds.getAttr("|nope.visibility"),
            lambda: fake_cmds.listConnections("|nope|nopeShape",
                                              type="shadingEngine"),
        ):
            with pytest.raises(RuntimeError, match="No object matches name"):
                call()

    def test_a_query_about_a_deleted_transform_raises(self, fake_cmds):
        fake_cmds.delete("|golem|torso")
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake_cmds.exactWorldBoundingBox("|golem|torso")
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake_cmds.getAttr("|golem|torso.visibility")

    # --- finding 5: deletion is SHAPE-granular ---------------------------
    def test_a_deleted_shape_stops_answering_too(self, fake_cmds):
        # Round 1 recorded deletions against the `transforms` table only, so
        # a deleted SHAPE could not be expressed: nodeType still answered
        # "mesh" and polyEvaluate still answered 200 triangles for geometry
        # that was gone.
        fake_cmds.delete("|golem|head|headShape")
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake_cmds.nodeType("|golem|head|headShape")
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake_cmds.polyEvaluate("|golem|head|headShape", triangle=True)

    def test_the_transform_survives_its_shape_and_reports_as_a_group(self, fake_cmds):
        # Maya-true, and the counterpart that keeps the fix off the strict
        # side: deleting a shape does NOT delete its transform.
        fake_cmds.delete("|golem|head|headShape")
        head = next(o for o in scene.get_scene_graph({})["objects"]
                    if o["name"] == "|golem|head")
        assert head["type"] == "group" and head["tris"] is None

    def test_deleting_a_transform_takes_its_shape_with_it(self, fake_cmds):
        fake_cmds.delete("|golem|head")
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake_cmds.nodeType("|golem|head|headShape")

    def test_deleting_a_name_does_not_tombstone_it_forever(self, fake_cmds):
        # Strict-direction wrongness is as bad as permissive. Maya lets a
        # name be reused after a delete; a fake that remembered the deletion
        # forever would refuse a node standing right there.
        fake_cmds.delete("|keyLight")
        fake_cmds.transforms["|keyLight"] = {
            "shape": ("|keyLight|keyLightShape", "pointLight"),
            "parent": None, "visible": True,
            "bbox": [-0.1, 3.0, -0.1, 0.1, 3.2, 0.1],
        }
        fake_cmds._shape_owner["|keyLight|keyLightShape"] = "|keyLight"
        assert fake_cmds.nodeType("|keyLight|keyLightShape") == "pointLight"
        assert "|keyLight" in fake_cmds.ls(type="transform", long=True)

    # --- contract point 3: no answers-anything fallback ------------------
    def test_a_shading_group_that_never_existed_is_not_given_a_material(self, fake_cmds):
        # This branch used to DERIVE its answer from the plug string, so it
        # named "ghost" as the material of "|ghostSG" - a shading group
        # nothing in the scene holds.
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake_cmds.listConnections("|ghostSG.surfaceShader")
        # and the real one still answers, so the guard is not strict-side
        assert fake_cmds.listConnections("clay_matSG.surfaceShader") == ["clay_mat"]

    def test_a_group_no_longer_reports_a_zero_box_at_the_origin(self, fake_cmds):
        # The round-1 fix that a test now stands behind: an unconditional
        # `[0, 0, 0, 0, 0, 0]` fallback made every group in this scene
        # report a zero-sized box at the origin and could never fail.
        assert fake_cmds.exactWorldBoundingBox("|golem") == [
            -1.0, 0.0, -0.5, 1.0, 2.8, 0.5]
        with pytest.raises(AssertionError, match="no modelled bbox"):
            fake_cmds.exactWorldBoundingBox("|persp")

    def test_ls_answers_one_question_only(self, fake_cmds):
        # get_scene_graph asks for long-named transforms and nothing else;
        # a shape or short-name walk would be a different handler.
        with pytest.raises(AssertionError):
            fake_cmds.ls(type="mesh", long=True)
        with pytest.raises(AssertionError):
            fake_cmds.ls(type="transform")

    def test_short_named_relatives_are_refused(self, fake_cmds):
        with pytest.raises(AssertionError):
            fake_cmds.listRelatives("|golem|torso", shapes=True,
                                    noIntermediate=True)

    def test_intermediate_shapes_must_be_excluded(self, fake_cmds):
        # An *Orig shape under a skinned mesh would be picked up otherwise.
        with pytest.raises(AssertionError):
            fake_cmds.listRelatives("|golem|torso", shapes=True, fullPath=True)

    def test_only_the_visibility_attribute_is_readable(self, fake_cmds):
        with pytest.raises(AssertionError, match="one attribute"):
            fake_cmds.getAttr("|golem|torso.translateX")

    def test_the_unit_query_refuses_anything_but_the_linear_unit(self, fake_cmds):
        with pytest.raises(AssertionError, match="only QUERY the unit"):
            fake_cmds.currentUnit(query=False, linear="m")

    def test_an_untyped_listconnections_is_refused(self, fake_cmds):
        with pytest.raises(AssertionError, match="unexpected listConnections"):
            fake_cmds.listConnections("|golem|torso|torsoShape")
