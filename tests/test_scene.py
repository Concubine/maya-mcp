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
            },
        }
        self._shape_owner = {
            v["shape"][0]: k
            for k, v in self.transforms.items()
            if v.get("shape")
        }

    def ls(self, type=None, long=False):
        assert type == "transform" and long
        return list(self.transforms)

    def listRelatives(self, node, shapes=False, parent=False, fullPath=False,
                      noIntermediate=False):
        assert fullPath
        if shapes:
            assert noIntermediate  # never pick *Orig intermediate shapes
        info = self.transforms[node]
        if shapes:
            return [info["shape"][0]] if info.get("shape") else None
        if parent:
            return [info["parent"]] if info.get("parent") else None
        raise AssertionError("unexpected listRelatives call")

    def nodeType(self, node):
        owner = self._shape_owner[node]
        return self.transforms[owner]["shape"][1]

    def polyEvaluate(self, shape, triangle=False, vertex=False):
        self.heavy_calls += 1
        info = self.transforms[self._shape_owner[shape]]
        if triangle:
            return info["tris"]
        if vertex:
            return info["verts"]
        raise AssertionError("unexpected polyEvaluate call")

    def exactWorldBoundingBox(self, node):
        self.heavy_calls += 1
        return self.transforms[node].get("bbox", [0, 0, 0, 0, 0, 0])

    def listConnections(self, node, type=None):
        if type == "shadingEngine":
            mat = self.transforms[self._shape_owner[node]].get("material")
            return ["%sSG" % mat] if mat else None
        if node.endswith(".surfaceShader"):
            return [node.split("|")[-1].replace("SG.surfaceShader", "")]
        raise AssertionError("unexpected listConnections call: %r %r" % (node, type))

    def getAttr(self, attr):
        node = attr.rsplit(".", 1)[0]
        return self.transforms[node]["visible"]

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
