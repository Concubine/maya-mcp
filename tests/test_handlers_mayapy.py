"""Handler tests that need a real Maya: run under `mayapy -m pytest tests/test_handlers_mayapy.py`.

Skipped automatically when maya is not importable (regular CI / dev machines).
Viewport capture needs a GUI, so only its argument marshaling is asserted here;
real pixels are covered by the manual M0 loop test inside Maya.
"""

import math

import pytest

maya = pytest.importorskip("maya", reason="requires mayapy / Maya's embedded Python")

import maya.standalone  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def maya_session():
    maya.standalone.initialize(name="python")
    yield
    try:
        maya.standalone.uninitialize()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def fresh_scene():
    import maya.cmds as cmds

    cmds.file(new=True, force=True)
    yield


class TestExecutePythonInMaya:
    def test_cmds_is_preimported_and_usable(self):
        from maya_plugin.handlers import code_exec

        code_exec.reset_namespace()
        result = code_exec.execute_python(
            {"code": "name = cmds.polyCube(name='loop_test_cube')[0]\nname"}
        )
        assert result["traceback"] is None
        assert "loop_test_cube" in result["result_repr"]


class TestSceneGraphInMaya:
    def test_real_scene_outline(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import scene

        cmds.polyCube(name="torso")
        cmds.polySphere(name="head")
        result = scene.get_scene_graph({})
        names = {o["name"] for o in result["objects"]}
        assert "|torso" in names and "|head" in names
        torso = next(o for o in result["objects"] if o["name"] == "|torso")
        assert torso["type"] == "mesh"
        assert torso["tris"] == 12
        assert torso["verts"] == 8

    def test_filter_and_pagination_against_real_scene(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import scene

        for i in range(5):
            cmds.polyCube(name="brick_%d" % i)
        page = scene.get_scene_graph({"filter": "brick", "max_objects": 2})
        assert page["total"] == 5
        assert len(page["objects"]) == 2
        assert page["cursor"] is not None


class TestCaptureInMayapy:
    def test_capture_refused_cleanly_without_gui(self):
        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import capture

        with pytest.raises(HandlerError, match="panel|batch"):
            capture.capture_viewport({"angles": ["front"]})


class TestCaptureLightingInMaya:
    def test_scene_lighting_changes_the_pixels(self, tmp_path):
        # Spec 2: a capture must be able to use the scene's own lights.
        # Asserting the modelEditor flag alone would pass even if VP2 ignored
        # it - so compare actual pixels between the two modes.
        import base64
        import maya.cmds as cmds

        from maya_plugin.handlers import capture

        if not cmds.about(query=True, batch=True) is False:
            pytest.skip("viewport capture needs a GUI Maya")

        cmds.file(rename=str(tmp_path / "lighting.ma"))
        cmds.polyCube(name="litcube", w=4, h=4, d=4)
        light = cmds.directionalLight(name="keyish", intensity=3.0)
        cmds.xform(cmds.listRelatives(light, parent=True)[0], rotation=[-35, 25, 0])

        shots = {}
        for mode in ("default", "scene"):
            out = capture.capture_viewport({
                "angles": ["three_quarter"], "lighting": mode,
                "wireframe_overlay": False, "resolution": 256,
                "isolate": ["|litcube"],
            })
            shots[mode] = base64.b64decode(out["images"][0]["png_b64"])

        assert shots["default"] != shots["scene"], (
            "scene lighting produced pixel-identical output to the default "
            "headlight - displayLights is not reaching VP2"
        )


class TestSessionInMaya:
    def test_checkpoint_restore_roundtrip(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import session

        cmds.file(rename=str(tmp_path / "work.ma"))
        cmds.polyCube(name="keeper")
        cp = session.checkpoint({"label": "with_keeper"})
        cmds.polySphere(name="stray")
        result = session.restore_checkpoint({"checkpoint_id": cp["checkpoint_id"]})
        assert result["restored"] == cp["checkpoint_id"]
        assert cmds.objExists("keeper")
        assert not cmds.objExists("stray")

    def test_undo_reverses_a_chunked_change(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import session

        cmds.undoInfo(openChunk=True, chunkName="maya-mcp")
        cmds.polyCube(name="undo_me")
        cmds.undoInfo(closeChunk=True)
        assert cmds.objExists("undo_me")
        result = session.undo({"steps": 1})
        assert result["undone"] == 1
        assert not cmds.objExists("undo_me")


class TestMeshcheckInMaya:
    def test_closed_cube_is_watertight(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import meshcheck

        cube = cmds.polyCube(name="wt_cube")[0]
        stats = meshcheck.mesh_stats(cube)
        assert stats["tris"] == 12
        assert stats["boundary_edges"] == 0
        assert stats["nonmanifold_edges"] == 0
        assert stats["watertight"] is True

    def test_open_plane_is_not_watertight(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import meshcheck

        plane = cmds.polyPlane(name="wt_plane", sx=1, sy=1)[0]
        stats = meshcheck.mesh_stats(plane)
        assert stats["boundary_edges"] == 4
        assert stats["watertight"] is False

    def test_ensure_object_shading_repairs_partial_assignment(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import meshcheck

        cube = cmds.polyCube(name="sg_cube")[0]
        shape = cmds.listRelatives(cube, shapes=True, fullPath=True)[0]
        shader = cmds.shadingNode("lambert", asShader=True, name="sg_red")
        sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                       name="sg_redSG")
        cmds.connectAttr(shader + ".outColor", sg + ".surfaceShader", force=True)
        # per-face assignment on half the cube = partial coverage
        cmds.sets(cube + ".f[0:2]", edit=True, forceElement=sg)
        result = meshcheck.ensure_object_shading(cmds, shape, fallback_sg=sg)
        assert result["repaired"] is True
        assert result["sg"] == sg
        # whole shape is now an object-level member (cmds.sets query returns
        # short names on this Maya version, even when queried/assigned via
        # full path, so compare short names)
        members = cmds.sets(sg, query=True) or []
        assert shape.split("|")[-1] in [m.split("|")[-1] for m in members]

    def test_ensure_object_shading_leaves_healthy_mesh_alone(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import meshcheck

        cube = cmds.polyCube(name="sg_ok_cube")[0]
        shape = cmds.listRelatives(cube, shapes=True, fullPath=True)[0]
        # fresh primitives are object-level members of initialShadingGroup
        result = meshcheck.ensure_object_shading(cmds, shape, fallback_sg=None)
        assert result["repaired"] is False
        assert result["sg"] == "initialShadingGroup"

    def test_ensure_object_shading_ignores_other_shapes_basename_match(self):
        # Regression: two shapes sharing a basename in different groups used
        # to let a healthy OTHER shape's object-level membership mask a
        # partially-assigned shape of the same short name (commit ec0af3f).
        import maya.cmds as cmds

        from maya_plugin.handlers import meshcheck

        shader = cmds.shadingNode("lambert", asShader=True, name="sg_dup_red")
        sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                       name="sg_dupSG")
        cmds.connectAttr(shader + ".outColor", sg + ".surfaceShader", force=True)

        grp_a = cmds.group(cmds.polyCube()[0], name="grpA")
        cmds.rename(cmds.listRelatives(grp_a, children=True)[0], "part")
        grp_b = cmds.group(cmds.polyCube()[0], name="grpB")
        cmds.rename(cmds.listRelatives(grp_b, children=True)[0], "part")

        shape_a = cmds.listRelatives("|grpA|part", shapes=True, fullPath=True)[0]
        shape_b = cmds.listRelatives("|grpB|part", shapes=True, fullPath=True)[0]

        # grpB's shape gets full, healthy object-level membership.
        cmds.sets(shape_b, edit=True, forceElement=sg)
        # grpA's shape only gets partial per-face membership of the same SG -
        # this must NOT be masked as healthy by grpB's basename-matching
        # object-level membership.
        cmds.sets(shape_a + ".f[0:2]", edit=True, forceElement=sg)

        result = meshcheck.ensure_object_shading(cmds, shape_a, fallback_sg=sg)
        assert result["repaired"] is True
        assert result["sg"] == sg

        members = cmds.sets(sg, query=True) or []
        resolved = [
            (cmds.ls(m, long=True) or [m])[0] for m in members if ".f[" not in m
        ]
        assert shape_a in resolved


class TestMeshStatsNonMeshInMaya:
    def test_non_mesh_input_raises_clear_error(self):
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import meshcheck

        cmds.group(empty=True, name="someGroup")
        with pytest.raises(HandlerError, match="not a polygon mesh"):
            meshcheck.mesh_stats("|someGroup")


class TestModelingInMaya:
    def test_create_transform_duplicate_roundtrip(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        created = modeling.create_primitive(
            {"kind": "cube", "name": "mb_cube", "translate": [1, 2, 3]}
        )
        assert created["name"] == "|mb_cube"
        assert cmds.xform("|mb_cube", q=True, ws=True, t=True) == [1.0, 2.0, 3.0]

        copy = modeling.duplicate(
            {"name": "|mb_cube", "new_name": "mb_cube_b", "translate": [2, 0, 0]}
        )
        assert copy["name"] == "|mb_cube_b"
        assert cmds.xform("|mb_cube_b", q=True, ws=True, t=True) == [3.0, 2.0, 3.0]

        moved = modeling.transform(
            {"names": ["|mb_cube"], "translate": [0, 0, 0], "relative": False}
        )
        assert moved["objects"][0]["translate"] == [0.0, 0.0, 0.0]

    def test_group_parent_rename_delete(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        modeling.create_primitive({"kind": "cube", "name": "gp_a"})
        modeling.create_primitive({"kind": "cube", "name": "gp_b"})
        grp = modeling.group({"names": ["|gp_a", "|gp_b"], "group_name": "gp_grp"})
        assert grp["name"] == "|gp_grp"
        modeling.create_primitive({"kind": "cube", "name": "gp_c"})
        parented = modeling.parent({"child": "|gp_c", "parent": "|gp_grp"})
        assert parented["name"] == "|gp_grp|gp_c"
        renamed = modeling.rename({"name": "|gp_grp|gp_c", "new_name": "gp_kid"})
        assert renamed["name"] == "|gp_grp|gp_kid"
        modeling.delete_objects({"names": ["|gp_grp"]})
        assert not cmds.objExists("gp_grp")

    def test_platonic_solid_kinds_build_with_fixed_low_poly_face_counts(self):
        # F2: octahedron/icosahedron have no subdivision flags in Maya - the
        # real face count must match projected_faces regardless of divisions,
        # proving the cap math (max_divisions_for) stays honest for them too.
        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        oct_low = modeling.create_primitive({"kind": "octahedron", "name": "gem_oct_a"})
        oct_high = modeling.create_primitive(
            {"kind": "octahedron", "name": "gem_oct_b", "divisions": 50}
        )
        assert cmds.polyEvaluate(oct_low["name"], face=True) == 8
        assert cmds.polyEvaluate(oct_high["name"], face=True) == 8
        assert modeling.projected_faces("octahedron", 50) == 8

        ico = modeling.create_primitive({"kind": "icosahedron", "name": "gem_ico"})
        assert cmds.polyEvaluate(ico["name"], face=True) == 20
        assert modeling.projected_faces("icosahedron", 1) == 20

    def test_prism_and_pyramid_build_faceted_low_poly_gems(self):
        # A cut gem is 8-16 faces - these two kinds are the tool gap the real
        # art run hit (only bevelled cubes were faceted before F2).
        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        prism = modeling.create_primitive(
            {"kind": "prism", "name": "gem_prism", "divisions": 3}
        )
        assert cmds.polyEvaluate(prism["name"], face=True) == modeling.projected_faces(
            "prism", 3
        )

        pyramid = modeling.create_primitive(
            {"kind": "pyramid", "name": "gem_pyramid", "divisions": 3}
        )
        assert cmds.polyEvaluate(
            pyramid["name"], face=True
        ) == modeling.projected_faces("pyramid", 3)

        # divisions=1 defaults land inside the "cut gem is 8-16 faces" band.
        prism_default = modeling.create_primitive(
            {"kind": "prism", "name": "gem_prism_default"}
        )
        assert 5 <= cmds.polyEvaluate(prism_default["name"], face=True) <= 16


class TestBooleanInMaya:
    def test_difference_carves_and_is_clean(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        cmds.file(rename=str(tmp_path / "bool.ma"))
        cmds.polyCube(name="base", w=2, h=2, d=2)
        cmds.polySphere(name="cutter", r=1.2)
        cmds.xform("cutter", ws=True, t=(1, 1, 1))
        result = modeling.boolean_op(
            {"a": "|base", "b": "|cutter", "op": "difference", "new_name": "carved"}
        )
        assert result["name"] == "|carved"
        assert result["watertight"] is True
        assert result["tris"] > 12
        # inputs consumed, no leftover boolean nodes, no construction history
        assert not cmds.objExists("base") and not cmds.objExists("cutter")
        assert cmds.ls(type="polyCBoolOp") == []
        shape = cmds.listRelatives("|carved", shapes=True, fullPath=True)[0]
        # cmds.listHistory returns short names on this Maya version (same
        # quirk as cmds.sets query, see meshcheck test precedent below), so
        # resolve to canonical long names before comparing.
        history = [(cmds.ls(h, long=True) or [h])[0] for h in cmds.listHistory(shape)]
        assert history == [shape]

    def test_boolean_keeps_object_level_shading(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        cmds.file(rename=str(tmp_path / "boolsg.ma"))
        cmds.polyCube(name="base2", w=2, h=2, d=2)
        shader = cmds.shadingNode("lambert", asShader=True, name="bool_clay")
        sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                       name="bool_claySG")
        cmds.connectAttr(shader + ".outColor", sg + ".surfaceShader", force=True)
        cmds.sets("base2", edit=True, forceElement=sg)
        cmds.polySphere(name="cutter2", r=1.2)
        result = modeling.boolean_op(
            {"a": "|base2", "b": "|cutter2", "op": "difference", "new_name": "carved2"}
        )
        # the run's trap: output must end object-level assigned to A's material
        # (cmds.sets query returns short names on this Maya version even for
        # full-path assignment - see meshcheck's
        # test_ensure_object_shading_repairs_partial_assignment - so compare
        # short names, same as that precedent).
        shape = cmds.listRelatives("|carved2", shapes=True, fullPath=True)[0]
        members = cmds.sets(sg, query=True) or []
        assert shape.split("|")[-1] in [m.split("|")[-1] for m in members]

    def test_boolean_takes_auto_checkpoint(self, tmp_path):
        import os

        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        cmds.file(rename=str(tmp_path / "boolcp.ma"))
        cmds.polyCube(name="base3")
        cmds.polySphere(name="cutter3")
        modeling.boolean_op(
            {"a": "|base3", "b": "|cutter3", "op": "union", "new_name": "fused3"}
        )
        cp_dir = str(tmp_path / "checkpoints")
        assert any("auto_boolean" in f for f in os.listdir(cp_dir))


# The atlas patch every #638 test packs its chunk into: patch 0 of a 4x4 grid
# with a 2% margin, which is where the golem run's chunks actually sat.
PATCH_638 = (0.005, 0.755, 0.245, 0.995)


def _uv_bounds(cmds, node):
    flat = cmds.polyEditUV(node + ".map[*]", query=True) or []
    us, vs = flat[0::2], flat[1::2]
    return (min(us), min(vs), max(us), max(vs))


def _pack_into(cmds, node, rect):
    """Squeeze a default 0..1 layout into `rect`, the way uv_atlas does."""
    cmds.polyEditUV(node + ".map[*]", pu=0, pv=0,
                    su=rect[2] - rect[0], sv=rect[3] - rect[1])
    cmds.polyEditUV(node + ".map[*]", u=rect[0], v=rect[1])


class TestBooleanCanReuseAConsumedName:
    """#640-1: `new_name` collided with an input the call itself consumes.

    `boolean_op(a=shoulder, b=cutter, new_name="shoulder")` returned
    `shoulder_001`, because the name was reserved while Maya still held it -
    polyCBoolOp leaves both operands as emptied transforms until the history
    delete reaps them. So the most natural request there is, cut a socket into X
    and have it still be called X, could not be expressed. It cost the #601 run
    3 renames.

    Only a real Maya can settle this: the whole question is when the operands
    actually stop existing, which is precisely what a fake decides for itself.
    """

    def test_the_result_can_take_a_s_own_name(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        cmds.file(rename=str(tmp_path / "boolname.ma"))
        cmds.polyCube(name="golem_L_shoulder", w=2, h=2, d=2)
        cmds.polyCube(name="socket_cutter", w=1, h=1, d=1)
        cmds.xform("socket_cutter", ws=True, t=(1, 1, 0))

        result = modeling.boolean_op({
            "a": "|golem_L_shoulder", "b": "|socket_cutter",
            "op": "difference", "new_name": "golem_L_shoulder",
        })
        assert result["name"] == "|golem_L_shoulder"
        assert cmds.objExists("|golem_L_shoulder")
        assert not cmds.objExists("golem_L_shoulder_001")
        assert result["warnings"] == []

    def test_the_result_can_take_b_s_own_name(self, tmp_path):
        """b is consumed too, so its name is equally free."""
        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        cmds.file(rename=str(tmp_path / "boolnameb.ma"))
        cmds.polyCube(name="plate", w=4, h=4, d=4)
        cmds.polyCube(name="keeper", w=1, h=1, d=1)
        cmds.xform("keeper", ws=True, t=(2, 2, 0))

        result = modeling.boolean_op({
            "a": "|plate", "b": "|keeper", "op": "difference",
            "new_name": "keeper",
        })
        assert result["name"] == "|keeper"

    def test_a_name_held_by_an_UNCONSUMED_object_is_still_refused(self, tmp_path):
        """The safety half. A name belonging to something this call does not
        consume must not be stolen - and the caller has to be told."""
        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        cmds.file(rename=str(tmp_path / "boolnamebystander.ma"))
        cmds.polyCube(name="host", w=2, h=2, d=2)
        cmds.polyCube(name="cutter2", w=1, h=1, d=1)
        cmds.xform("cutter2", ws=True, t=(1, 1, 0))
        cmds.polyCube(name="bystander", w=1, h=1, d=1)
        cmds.xform("bystander", ws=True, t=(20, 0, 0))

        result = modeling.boolean_op({
            "a": "|host", "b": "|cutter2", "op": "difference",
            "new_name": "bystander",
        })
        assert result["name"] != "|bystander"
        assert cmds.objExists("|bystander")  # untouched
        assert any("bystander" in w for w in result["warnings"]), (
            "silently returning a different name is what cost the run its renames"
        )

    def test_the_claimed_name_keeps_everything_638_carried(self, tmp_path):
        """The rename happens late in the sequence, after the reparent, the
        freeze and the pivot. Claiming the name must not undo any of that."""
        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        cmds.file(rename=str(tmp_path / "boolnamestate.ma"))
        head = cmds.group(empty=True, name="golem_C_head")
        cmds.polyCube(name="brow", w=2, h=2, d=2)
        cmds.parent("brow", head)
        cmds.xform("|golem_C_head|brow", ws=True, pivots=(0, 1, 0))
        cmds.polyCube(name="visor2", w=1, h=1, d=1)
        cmds.xform("visor2", ws=True, t=(1, 1, 0))

        result = modeling.boolean_op({
            "a": "|golem_C_head|brow", "b": "|visor2", "op": "difference",
            "new_name": "brow",
        })
        assert result["name"] == "|golem_C_head|brow"
        assert result["parent"] == "|golem_C_head"
        assert result["pivot"] == pytest.approx([0.0, 1.0, 0.0], abs=1e-4)

    def test_etch_text_can_keep_the_plate_s_name(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import etch

        try:
            cmds.loadPlugin("Type", quiet=True)
        except Exception:
            pytest.skip("Type plugin unavailable in standalone")
        cmds.file(rename=str(tmp_path / "etchname.ma"))
        cmds.polyCube(name="sigil_plate", w=4, h=4, d=4)

        result = etch.etch_text({
            "mesh": "|sigil_plate", "text": "A", "face": 0, "width": 2.0,
            "depth": 0.3, "new_name": "sigil_plate",
        })
        assert result["name"] == "|sigil_plate"


class TestBooleanCarriesAState:
    """#638: a boolean rebuilds the mesh, and everything that is not vertices -
    the pivot, the place in the hierarchy, the atlas patch - was being dropped
    silently. All three were measured lost on one call in the #601 golem run."""

    def test_the_pivot_survives_the_rebuild(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        cmds.file(rename=str(tmp_path / "boolpivot.ma"))
        cmds.polyCube(name="shoulder", w=2, h=2, d=2)
        cmds.xform("shoulder", ws=True, t=(0, 2, 0))
        # the rigged pivot: the ball joint at the bottom of the chunk, NOT the
        # bbox centre the boolean would otherwise invent.
        cmds.xform("shoulder", ws=True, pivots=(0, 1, 0))
        cmds.polyCube(name="socket", w=1, h=1, d=1)
        cmds.xform("socket", ws=True, t=(1, 3, 0))

        result = modeling.boolean_op({
            "a": "|shoulder", "b": "|socket", "op": "difference",
            "new_name": "shoulder_cut",
        })
        pivot = cmds.xform(result["name"], q=True, ws=True, rotatePivot=True)
        assert pivot == pytest.approx([0.0, 1.0, 0.0], abs=1e-4)
        assert result["pivot"] == pytest.approx([0.0, 1.0, 0.0], abs=1e-4)
        assert result["warnings"] == []

    def test_the_result_stays_in_the_hierarchy(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        cmds.file(rename=str(tmp_path / "boolparent.ma"))
        head = cmds.group(empty=True, name="golem_C_head")
        cmds.polyCube(name="brow", w=2, h=2, d=2)
        cmds.parent("brow", head)
        cmds.polyCube(name="visor", w=1, h=1, d=1)
        cmds.xform("visor", ws=True, t=(1, 1, 0))

        result = modeling.boolean_op({
            "a": "|golem_C_head|brow", "b": "|visor", "op": "difference",
            "new_name": "brow_slotted",
        })
        assert result["name"] == "|golem_C_head|brow_slotted"
        assert result["parent"] == "|golem_C_head"
        # and the parent group is not left holding nothing: the result IS in it
        assert cmds.listRelatives(head, children=True, fullPath=True) == [
            "|golem_C_head|brow_slotted"
        ]

    def test_a_parent_whose_only_child_is_a_is_not_reaped(self, tmp_path):
        """delete(constructionHistory=True) garbage-collects the consumed
        operands, and an empty parent group goes with them - measured. The
        result is reparented BEFORE that delete for exactly this reason."""
        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        cmds.file(rename=str(tmp_path / "boolsolo.ma"))
        solo = cmds.group(empty=True, name="soloGRP")
        cmds.polyCube(name="onlyChild", w=2, h=2, d=2)
        cmds.parent("onlyChild", solo)
        cmds.polyCube(name="soloCutter", w=1, h=1, d=1)
        cmds.xform("soloCutter", ws=True, t=(1, 1, 0))

        result = modeling.boolean_op({
            "a": "|soloGRP|onlyChild", "b": "|soloCutter", "op": "difference",
            "new_name": "onlyChild_cut",
        })
        assert cmds.objExists("soloGRP")
        assert result["parent"] == "|soloGRP"
        assert result["warnings"] == []

    def test_a_scaled_parent_does_not_leave_a_compensating_scale(self, tmp_path):
        """Reparenting preserves world position, which hands the result the
        INVERSE of the group's scale - the exact node state the export gate
        refuses (#629). It has to be baked, not carried."""
        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        cmds.file(rename=str(tmp_path / "boolscaled.ma"))
        rig = cmds.group(empty=True, name="scaledGRP")
        for axis in "XYZ":
            cmds.setAttr(rig + ".scale" + axis, 0.8)
        cmds.polyCube(name="chunk", w=2, h=2, d=2)
        cmds.parent("chunk", rig)
        before = cmds.exactWorldBoundingBox("|scaledGRP|chunk")
        cmds.polyCube(name="scaledCutter", w=1, h=1, d=1)
        cmds.xform("scaledCutter", ws=True, t=(1, 1, 0))

        result = modeling.boolean_op({
            "a": "|scaledGRP|chunk", "b": "|scaledCutter", "op": "difference",
            "new_name": "chunk_cut",
        })
        assert cmds.getAttr(result["name"] + ".scale")[0] == pytest.approx(
            (1.0, 1.0, 1.0), abs=1e-6
        )
        # baked, not lost: the geometry has not moved or resized
        after = cmds.exactWorldBoundingBox(result["name"])
        assert after[:3] == pytest.approx(before[:3], abs=1e-4)
        assert any("frozen into the vertices" in w for w in result["warnings"])

    def test_the_cutter_cannot_drag_the_result_out_of_its_atlas_patch(self, tmp_path):
        """The one that would have shipped: polyCBoolOp keeps each operand's
        own UVs, so a default-UV cutter puts the newly cut faces on the whole
        atlas. Nothing looks wrong until the material goes on."""
        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        cmds.file(rename=str(tmp_path / "booluv.ma"))
        cmds.polyCube(name="packed", w=2, h=2, d=2)
        _pack_into(cmds, "packed", PATCH_638)
        assert _uv_bounds(cmds, "packed") == pytest.approx(PATCH_638, abs=1e-4)
        cmds.polyCube(name="rawCutter", w=1, h=1, d=1)
        cmds.xform("rawCutter", ws=True, t=(1, 1, 0))
        assert _uv_bounds(cmds, "rawCutter") == pytest.approx((0, 0, 1, 1), abs=1e-4)

        result = modeling.boolean_op({
            "a": "|packed", "b": "|rawCutter", "op": "difference",
            "new_name": "packed_cut",
        })
        u0, v0, u1, v1 = _uv_bounds(cmds, result["name"])
        assert u0 >= PATCH_638[0] - 1e-4 and v0 >= PATCH_638[1] - 1e-4
        assert u1 <= PATCH_638[2] + 1e-4 and v1 <= PATCH_638[3] + 1e-4
        assert result["uv_bounds"] == pytest.approx(list(PATCH_638), abs=1e-3)
        assert result["warnings"] == []

    def test_a_mesh_with_no_uvs_is_not_a_failure(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        cmds.file(rename=str(tmp_path / "boolnouv.ma"))
        cmds.polyCube(name="bare", w=2, h=2, d=2)
        cmds.polyMapDel("bare.f[*]")
        # the test is only worth anything if the mesh really has none left
        assert not (cmds.polyEditUV("bare.map[*]", query=True) or [])
        cmds.polyCube(name="bareCutter", w=1, h=1, d=1)
        cmds.xform("bareCutter", ws=True, t=(1, 1, 0))

        result = modeling.boolean_op({
            "a": "|bare", "b": "|bareCutter", "op": "difference",
            "new_name": "bare_cut",
        })
        assert result["watertight"] is True
        assert result["warnings"] == []


class TestEtchInMaya:
    def test_etch_carves_recess(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import etch

        # loadPlugin returns falsy both when the plugin is genuinely
        # unavailable AND when it's already loaded (see etch._create_glyph's
        # own comment) - check pluginInfo too so an already-loaded plugin
        # from an earlier test in this session doesn't cause a false skip.
        if not cmds.loadPlugin("Type", quiet=True) and not cmds.pluginInfo(
            "Type", query=True, loaded=True
        ):
            pytest.skip("Type plugin unavailable in standalone")
        cmds.file(rename=str(tmp_path / "etch.ma"))
        cmds.polyCube(name="plate", w=2, h=1, d=0.3)
        before = cmds.polyEvaluate("plate", triangle=True)
        result = etch.etch_text(
            {"mesh": "|plate", "text": "א", "face": 0, "width": 0.8,
             "depth": 0.05, "mirror": True, "rotate_deg": 180.0}
        )
        assert result["tris"] > before
        # zero orphans from the Type network
        assert cmds.ls(type="type") == []
        assert cmds.ls(type="typeExtrude") == []

    def test_face_center_normal_matches_the_face_it_names(self, tmp_path):
        # Regression, found by the live smoke (redmine #577): the old code
        # called it.getNormal(om.MSpace.kWorld) POSITIONALLY, which binds to
        # MItMeshPolygon's getNormal(vertexIndex) overload rather than
        # getNormal(space) - MSpace.kWorld is the int 4. On a cube that
        # returned the NEXT face's normal for every face, so etch_text carved
        # into the wrong plane (an "A" meant for the +Z face landed edge-on).
        #
        # The check is deliberately independent of any normal API: on a cube
        # centred at the origin, the outward normal of each face is its own
        # centre direction, and the centre comes from a different call
        # (it.center) than the normal does.
        import maya.cmds as cmds

        from maya_plugin.handlers import etch

        cmds.file(rename=str(tmp_path / "face_normals.ma"))
        cmds.polyCube(name="normplate", w=2, h=2, d=2)
        for face in range(6):
            center, normal = etch._face_center_normal("|normplate", face)
            length = sum(c * c for c in center) ** 0.5
            expected = [c / length for c in center]
            assert normal == pytest.approx(expected, abs=1e-6), (
                "face %d centre %r but normal %r" % (face, center, normal)
            )

    def test_mirrored_etch_carves_the_host_not_the_cutter(self, tmp_path):
        # Regression, found by the live smoke (redmine #577): mirror=True
        # negates the cutter's X scale, which reverses its face winding.
        # polyBoolOp reads an inside-out operand as its own complement, so
        # "difference" quietly returned the INTERSECTION - the carve volume
        # alone (2 x 2.14 x 0.3) instead of the carved 4x4x4 host. Both
        # results are watertight and have a plausible triangle count, which
        # is why every existing assertion stayed green.
        #
        # The host's bounding box is the discriminator: a difference keeps it,
        # an intersection collapses it to the cutter.
        import maya.cmds as cmds

        from maya_plugin.handlers import etch

        if not cmds.loadPlugin("Type", quiet=True) and not cmds.pluginInfo(
            "Type", query=True, loaded=True
        ):
            pytest.skip("Type plugin unavailable in standalone")
        cmds.file(rename=str(tmp_path / "etch_mirror.ma"))
        cmds.polyCube(name="mirrorplate", w=4, h=4, d=4)
        host_bbox = cmds.exactWorldBoundingBox("|mirrorplate")

        result = etch.etch_text(
            {"mesh": "|mirrorplate", "text": "א", "face": 0, "width": 2.0,
             "depth": 0.3, "mirror": True, "rotate_deg": 180.0}
        )
        assert result["watertight"] is True
        carved_bbox = cmds.exactWorldBoundingBox(result["name"])
        assert carved_bbox == pytest.approx(host_bbox, abs=1e-4), (
            "mirrored etch returned a %r-sized solid; the host is %r - the "
            "cutter's winding was not corrected, so difference became "
            "intersection"
            % ([round(hi - lo, 3) for lo, hi in zip(carved_bbox[:3], carved_bbox[3:])],
               [round(hi - lo, 3) for lo, hi in zip(host_bbox[:3], host_bbox[3:])])
        )
        assert cmds.ls(type="type") == []
        assert cmds.ls(type="typeExtrude") == []

    def test_sweep_runs_when_failure_happens_after_glyph_creation(self, monkeypatch, tmp_path):
        # face_frame_transform runs inside the try, after _create_glyph has
        # already built a real Type network - a failure there must still
        # trigger the finally sweep.
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import etch

        # loadPlugin returns falsy both when the plugin is genuinely
        # unavailable AND when it's already loaded (see etch._create_glyph's
        # own comment) - check pluginInfo too so an already-loaded plugin
        # from an earlier test in this session doesn't cause a false skip.
        if not cmds.loadPlugin("Type", quiet=True) and not cmds.pluginInfo(
            "Type", query=True, loaded=True
        ):
            pytest.skip("Type plugin unavailable in standalone")
        cmds.file(rename=str(tmp_path / "etch_sweep_frame.ma"))
        cmds.polyCube(name="plate", w=2, h=1, d=0.3)

        def _boom(*args, **kwargs):
            raise HandlerError("forced face_frame_transform failure")

        monkeypatch.setattr(etch, "face_frame_transform", _boom)

        # Spy on the real _create_glyph so the test can name the mesh
        # transform it built - I2: the old orphan check only asserted zero
        # Type/typeExtrude *nodes*, which stayed true even when the glyph
        # MESH transform itself (not a Type-network node) was left behind.
        real_create_glyph = etch._create_glyph
        created_names = []

        def _spy_create_glyph(cmds_arg, text, font):
            name = real_create_glyph(cmds_arg, text, font)
            created_names.append(name)
            return name

        monkeypatch.setattr(etch, "_create_glyph", _spy_create_glyph)

        with pytest.raises(HandlerError, match="forced face_frame_transform failure"):
            etch.etch_text({"mesh": "|plate", "text": "א", "face": 0})

        assert cmds.ls(type="type") == []
        assert cmds.ls(type="typeExtrude") == []
        assert created_names, "the real glyph creator should have run"
        assert not cmds.objExists(created_names[0])

    def test_sweep_runs_when_create_glyph_itself_fails_after_type_node_created(
        self, monkeypatch, tmp_path
    ):
        # Reproduces the exact orphan path from the review finding: a real
        # Type network gets created (via CreatePolygonType), then the glyph
        # builder raises before returning - the old code ran _create_glyph
        # BEFORE the try, so this sweep never fired.
        import maya.cmds as cmds
        import maya.mel as mel

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import etch

        # loadPlugin returns falsy both when the plugin is genuinely
        # unavailable AND when it's already loaded (see etch._create_glyph's
        # own comment) - check pluginInfo too so an already-loaded plugin
        # from an earlier test in this session doesn't cause a false skip.
        if not cmds.loadPlugin("Type", quiet=True) and not cmds.pluginInfo(
            "Type", query=True, loaded=True
        ):
            pytest.skip("Type plugin unavailable in standalone")
        cmds.file(rename=str(tmp_path / "etch_sweep_create.ma"))
        cmds.polyCube(name="plate", w=2, h=1, d=0.3)

        created_names = []

        def _fake_create_glyph(cmds_arg, text, font):
            before = set(cmds.ls(type="transform"))
            mel.eval("CreatePolygonType;")
            created_names.extend(set(cmds.ls(type="transform")) - before)
            raise HandlerError("forced create_glyph failure after real node creation")

        monkeypatch.setattr(etch, "_create_glyph", _fake_create_glyph)

        with pytest.raises(HandlerError, match="forced create_glyph failure"):
            etch.etch_text({"mesh": "|plate", "text": "א", "face": 0})

        assert cmds.ls(type="type") == []
        assert cmds.ls(type="typeExtrude") == []
        # I2: CreatePolygonType makes at least the glyph mesh transform (plus
        # a manipulator handle) - neither is a Type/typeExtrude *node*, so
        # the assertions above stayed green with them still in the scene.
        assert created_names, "CreatePolygonType should have created transforms"
        for name in created_names:
            assert not cmds.objExists(name), name


class TestSculptInMaya:
    def test_displace_noise_moves_verts_and_keeps_count(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import sculpt

        cmds.polySphere(name="rock", subdivisionsAxis=12, subdivisionsHeight=12)
        before = cmds.xform("rock.vtx[5]", q=True, ws=True, t=True)
        verts = cmds.polyEvaluate("rock", vertex=True)
        result = sculpt.sculpt_ops(
            {"mesh": "|rock",
             "ops": [{"op": "displace_noise", "amp": 0.08, "freq": 2.6,
                      "octaves": 2, "soften_angle": 55}]}
        )
        assert result["applied"] == 1
        assert cmds.polyEvaluate("rock", vertex=True) == verts
        assert cmds.xform("rock.vtx[5]", q=True, ws=True, t=True) != before

    def test_soft_move_is_local(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import sculpt

        cmds.polyPlane(name="pad", sx=10, sy=10, w=10, h=10)
        far_before = cmds.xform("pad.vtx[0]", q=True, ws=True, t=True)
        sculpt.sculpt_ops(
            {"mesh": "|pad",
             "ops": [{"op": "soft_move", "center": [0, 0, 0], "radius": 2.0,
                      "falloff": "smooth", "delta": [0, 1, 0]}]}
        )
        center_y = cmds.xform("pad.vtx[60]", q=True, ws=True, t=True)[1]
        assert center_y > 0.5  # lifted
        assert cmds.xform("pad.vtx[0]", q=True, ws=True, t=True) == far_before

    def test_abort_and_report_lists_applied(self):
        import pytest as _pytest

        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import sculpt

        cmds.polyCube(name="ar_cube")
        with _pytest.raises(HandlerError) as exc:
            sculpt.sculpt_ops(
                {"mesh": "|ar_cube",
                 "ops": [{"op": "smooth", "divisions": 1},
                         {"op": "extrude_faces", "faces": "NOT_A_COMPONENT",
                          "distance": 1.0}]}
            )
        assert "smooth" in str(exc.value)  # reports what landed

    def test_vertex_op_takes_auto_checkpoint_and_warns(self, tmp_path):
        import os

        import maya.cmds as cmds

        from maya_plugin.handlers import sculpt

        cmds.file(rename=str(tmp_path / "sculptcp.ma"))
        cmds.polySphere(name="rock2", subdivisionsAxis=12, subdivisionsHeight=12)
        result = sculpt.sculpt_ops(
            {"mesh": "|rock2",
             "ops": [{"op": "displace_noise", "amp": 0.08, "freq": 2.6,
                      "octaves": 2}]}
        )
        cp_dir = str(tmp_path / "checkpoints")
        assert any("auto_sculpt" in f for f in os.listdir(cp_dir))
        assert result["checkpoint_id"] is not None
        assert os.path.isfile(os.path.join(cp_dir, result["checkpoint_id"] + ".ma"))
        assert any(
            "displace_noise" in w and "NOT undoable" in w for w in result["warnings"]
        )

    def test_cmds_only_ops_take_no_checkpoint_or_warning(self, tmp_path):
        import os

        import maya.cmds as cmds

        from maya_plugin.handlers import sculpt

        cmds.file(rename=str(tmp_path / "sculptcp2.ma"))
        cmds.polyCube(name="cube_sc2")
        result = sculpt.sculpt_ops(
            {"mesh": "|cube_sc2", "ops": [{"op": "smooth", "divisions": 1}]}
        )
        assert result["checkpoint_id"] is None
        assert result["warnings"] == []
        cp_dir = tmp_path / "checkpoints"
        assert not cp_dir.exists() or not any(
            "auto_sculpt" in f for f in os.listdir(cp_dir)
        )

    def test_unknown_op_in_list_takes_no_checkpoint(self, tmp_path):
        import os

        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import sculpt

        cmds.file(rename=str(tmp_path / "sculptcp3.ma"))
        cmds.polySphere(name="rock3")
        with pytest.raises(HandlerError):
            sculpt.sculpt_ops(
                {"mesh": "|rock3",
                 "ops": [{"op": "displace_noise", "amp": 0.05},
                         {"op": "not_a_real_op"}]}
            )
        cp_dir = tmp_path / "checkpoints"
        assert not cp_dir.exists() or not any(
            "auto_sculpt" in f for f in os.listdir(cp_dir)
        )

    def test_checkpoint_id_restores_and_error_hint_names_it(self, tmp_path):
        import os

        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import session, sculpt

        # happy path: the returned checkpoint_id round-trips through
        # maya_restore_checkpoint (the review finding: the old "checkpoint"
        # field was a path, which restore_checkpoint's checkpoint_id param
        # rejects).
        cmds.file(rename=str(tmp_path / "sculptcp4.ma"))
        cmds.polySphere(name="rock4", subdivisionsAxis=12, subdivisionsHeight=12)
        result = sculpt.sculpt_ops(
            {"mesh": "|rock4",
             "ops": [{"op": "displace_noise", "amp": 0.08, "freq": 2.6, "octaves": 2}]}
        )
        restore = session.restore_checkpoint({"checkpoint_id": result["checkpoint_id"]})
        assert restore["restored"] == result["checkpoint_id"]

        # error path: a valid vertex op lands, then soft_move fails
        # (missing delta) - the checkpoint taken before either op ran must
        # still exist on disk, and the failure hint must point at it.
        cmds.file(new=True, force=True)
        cmds.file(rename=str(tmp_path / "sculptcp5.ma"))
        cmds.polySphere(name="rock5", subdivisionsAxis=12, subdivisionsHeight=12)
        with pytest.raises(HandlerError) as exc:
            sculpt.sculpt_ops(
                {"mesh": "|rock5",
                 "ops": [{"op": "displace_noise", "amp": 0.05},
                         {"op": "soft_move", "center": [0, 0, 0], "radius": 1.0}]}
            )
        assert "restore the auto-checkpoint" in exc.value.hint
        cp_dir = str(tmp_path / "checkpoints")
        matches = [f for f in os.listdir(cp_dir) if "auto_sculpt" in f]
        assert matches
        checkpoint_id = matches[-1][:-len(".ma")]
        assert checkpoint_id in exc.value.hint


class TestViewportInMaya:
    def test_set_camera_creates_and_positions_named_camera(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import viewport

        result = viewport.set_camera(
            {"camera": "mb_test_cam", "position": [0, 5, 10],
             "look_at": [0, 0, 0], "focal_length": 35, "set_active": False}
        )
        assert result["name"] == "|mb_test_cam"
        assert cmds.objExists("|mb_test_cam")
        shape = cmds.listRelatives("|mb_test_cam", shapes=True, fullPath=True)[0]
        assert cmds.getAttr(shape + ".focalLength") == 35.0
        pos = cmds.xform("|mb_test_cam", query=True, worldSpace=True, translation=True)
        assert pos == pytest.approx([0.0, 5.0, 10.0])
        # looking back toward the origin from +Y/+Z: pitched down, no roll
        rot = cmds.xform("|mb_test_cam", query=True, worldSpace=True, rotation=True)
        assert rot[0] < 0.0
        assert rot[2] == pytest.approx(0.0)

    def test_set_camera_reuses_existing_camera_by_name(self):
        # Regression: cmds.camera(name=...) does NOT rename the transform on
        # this Maya version (it always appends "1", ignoring the requested
        # name) - the handler must create unnamed then cmds.rename(), and a
        # second call with the same name must reposition the SAME camera
        # rather than creating a new one each time (idempotent_hint=True).
        import maya.cmds as cmds

        from maya_plugin.handlers import viewport

        first = viewport.set_camera({"camera": "mb_reuse_cam", "set_active": False})
        assert first["name"] == "|mb_reuse_cam"
        second = viewport.set_camera(
            {"camera": "mb_reuse_cam", "position": [1, 2, 3], "set_active": False}
        )
        assert second["name"] == "|mb_reuse_cam"
        assert len(cmds.ls("mb_reuse_cam", long=True)) == 1
        assert cmds.xform(
            "|mb_reuse_cam", query=True, worldSpace=True, translation=True
        ) == pytest.approx([1.0, 2.0, 3.0])

    def test_set_camera_reuse_of_non_camera_name_raises_hinted_error(self):
        # A stray non-camera node with the requested name must not crash with
        # a raw IndexError/Maya exception (listRelatives(...)[0] on a
        # shapeless transform, or setAttr/lookThru on a non-camera shape) -
        # it's a foreseeable name collision and needs a HandlerError + hint.
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import viewport

        cmds.polyCube(name="mb_not_a_camera")
        with pytest.raises(HandlerError, match="camera") as exc:
            viewport.set_camera({"camera": "mb_not_a_camera", "set_active": False})
        assert exc.value.hint

    def test_set_camera_reuse_of_shapeless_transform_raises_hinted_error(self):
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import viewport

        cmds.group(name="mb_empty_grp", empty=True)
        with pytest.raises(HandlerError, match="camera") as exc:
            viewport.set_camera({"camera": "mb_empty_grp", "set_active": False})
        assert exc.value.hint

    def test_set_viewport_and_set_camera_refuse_cleanly_without_gui(self):
        # Same constraint as capture_viewport: no modelPanel exists in
        # mayapy/batch mode, and set_active defaults to True.
        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import viewport

        with pytest.raises(HandlerError, match="panel|batch"):
            viewport.set_viewport({"show_grid": True})
        with pytest.raises(HandlerError, match="panel|batch"):
            viewport.set_camera({"camera": "mb_active_cam"})


class TestObjectInfoInMaya:
    def test_sections_against_a_real_mesh(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import objinfo

        cmds.file(rename=str(tmp_path / "objinfo.ma"))
        cmds.polyCube(name="infocube", w=2, h=2, d=2)
        cmds.xform("|infocube", translation=[1, 2, 3])

        info = objinfo.get_object_info(
            {"name": "|infocube",
             "include": ["transform", "mesh_stats", "uvs", "shading", "history"]}
        )
        assert info["name"] == "|infocube"
        assert info["transform"]["translate"] == pytest.approx([1.0, 2.0, 3.0])
        assert info["mesh_stats"]["watertight"] is True
        assert info["mesh_stats"]["tris"] == 12
        assert info["uvs"]["count"] >= 1
        # a fresh polyCube is in initialShadingGroup at object level
        assert info["shading"]["shading_groups"] == ["initialShadingGroup"]
        assert info["shading"]["per_face"] is False
        assert info["history"]["node_count"] >= 1

    def test_group_without_a_shape_rejects_mesh_sections(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import objinfo

        cmds.file(rename=str(tmp_path / "objinfo_group.ma"))
        cmds.polyCube(name="gchild")
        cmds.group("|gchild", name="ginfo")
        with pytest.raises(HandlerError, match="no shape node"):
            objinfo.get_object_info({"name": "|ginfo", "include": ["mesh_stats"]})


class TestDeformRemeshCleanupInMaya:
    def test_bend_deformer_created_and_baked(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import sculpt

        cmds.polyCylinder(name="col", sx=8, sy=12, height=6)
        result = sculpt.deform(
            {"mesh": "|col", "deformer": "bend", "params": {"curvature": 45}}
        )
        assert result["deformer_nodes"]
        baked = sculpt.deform(
            {"mesh": "|col", "deformer": "bend", "params": {"curvature": -20},
             "delete_history_after": True}
        )
        assert baked["baked"] is True
        shape = cmds.listRelatives("|col", shapes=True, fullPath=True)[0]
        # cmds.listHistory returns short names on this Maya version (same
        # quirk as cmds.sets query / cmds.listHistory in the boolean tests
        # above), so resolve to canonical long names before comparing.
        history = [(cmds.ls(h, long=True) or [h])[0] for h in cmds.listHistory(shape)]
        assert history == [shape]
        # I1: baking must not orphan the handle transform either (bend's is
        # bend1Handle, shape type deformBend) - constructionHistory delete
        # only removes the deformer DG node, not the handle it created.
        assert cmds.ls(type="deformBend") == []

    def test_bend_actually_bends_and_reports_how_far(self):
        # #636: the old test asserted only that nodes existed, so a bend that
        # moved the mesh by 0.1% of its height passed. Assert the geometry.
        import maya.cmds as cmds

        from maya_plugin.handlers import sculpt

        cmds.polyCylinder(name="col", sx=8, sy=20, height=2.0, radius=0.2)
        result = sculpt.deform(
            {"mesh": "|col", "deformer": "bend", "params": {"curvature": 45}}
        )
        # A 45-degree bend on a 2.0-tall cylinder swings its tip a third of a
        # unit sideways. Pre-fix this measured 0.0055 (45 was read as degrees
        # already, so it worked) - the guard that matters is the low end below.
        assert result["max_displacement"] > 0.2, result
        assert result["warnings"] == []

    def test_bend_that_moves_nothing_says_so(self):
        # The exact call from the golem build: curvature 0.35 is a third of a
        # degree, and the tool must report that it did nothing.
        import maya.cmds as cmds

        from maya_plugin.handlers import sculpt

        cmds.polyCylinder(name="inert", sx=8, sy=20, height=2.0, radius=0.2)
        result = sculpt.deform(
            {"mesh": "|inert", "deformer": "bend", "params": {"curvature": 0.35}}
        )
        assert result["max_displacement"] < 0.01, result
        assert len(result["warnings"]) == 1
        assert "DEGREES" in result["warnings"][0]

    def test_bend_means_degrees_in_a_radians_scene(self):
        # setAttr reads angle attributes in the scene's UI unit, so the same
        # curvature must survive a scene whose angles are radians.
        import maya.cmds as cmds

        from maya_plugin.handlers import sculpt

        def tip(mesh):
            flat = cmds.xform(mesh + ".vtx[*]", query=True, worldSpace=True,
                              translation=True)
            return max(abs(flat[i]) for i in range(0, len(flat), 3))

        cmds.polyCylinder(name="deg_col", sx=8, sy=20, height=2.0, radius=0.2)
        in_degrees = sculpt.deform(
            {"mesh": "|deg_col", "deformer": "bend", "params": {"curvature": 45}}
        )
        degrees_tip = tip("|deg_col")
        try:
            cmds.currentUnit(angle="rad")
            cmds.polyCylinder(name="rad_col", sx=8, sy=20, height=2.0, radius=0.2)
            in_radians = sculpt.deform(
                {"mesh": "|rad_col", "deformer": "bend", "params": {"curvature": 45}}
            )
            radians_tip = tip("|rad_col")
        finally:
            cmds.currentUnit(angle="deg")
        assert in_radians["max_displacement"] == pytest.approx(
            in_degrees["max_displacement"], rel=1e-6
        )
        assert radians_tip == pytest.approx(degrees_tip, rel=1e-6)

    def test_soft_move_refuses_a_radius_that_reaches_no_vertex(self):
        # #636's sibling: this reported applied:1 and moved nothing.
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import sculpt

        cmds.polySphere(name="far_ball", radius=1.0)
        cmds.xform("|far_ball", translation=[5, 0, 0])
        before = cmds.xform("|far_ball.vtx[*]", query=True, worldSpace=True,
                            translation=True)
        with pytest.raises(HandlerError) as exc:
            sculpt.sculpt_ops(
                {"mesh": "|far_ball",
                 "ops": [{"op": "soft_move", "center": [0, 0, 0], "radius": 0.9,
                          "delta": [0, 0.5, 0]}]}
            )
        assert "does not reach the mesh" in str(exc.value)
        after = cmds.xform("|far_ball.vtx[*]", query=True, worldSpace=True,
                           translation=True)
        assert after == before  # refused before touching a single vertex

    def test_lattice_deform_baked_leaves_no_handle_transforms(self):
        # I1: cmds.delete(mesh, constructionHistory=True) removes the ffd
        # deformer DG node but NOT the transforms cmds.lattice created
        # (ffd1Lattice, ffd1Base) - both stay in the scene, visible and
        # framed by viewFit, even though the response claims baked=True
        # with deformer_nodes=[] (nothing left to clean up, by its own
        # report). Verify against real Maya that both are actually gone.
        import maya.cmds as cmds

        from maya_plugin.handlers import sculpt

        cmds.polyCube(name="lat_bake_target")
        result = sculpt.deform(
            {"mesh": "|lat_bake_target", "deformer": "lattice",
             "params": {"translate": [1, 0, 0]}, "delete_history_after": True}
        )
        assert result["baked"] is True
        assert result["deformer_nodes"] == []
        assert cmds.ls(type="lattice") == []
        assert cmds.ls(type="baseLattice") == []

    def test_deform_rejects_unknown_param(self):
        import pytest as _pytest

        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import sculpt

        cmds.polyCube(name="dp_cube")
        with _pytest.raises(HandlerError) as exc:
            sculpt.deform(
                {"mesh": "|dp_cube", "deformer": "bend",
                 "params": {"wobble": 3}}
            )
        assert "curvature" in exc.value.hint  # hint lists the whitelist

    def test_remesh_reports_method_and_keeps_original(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        cmds.file(rename=str(tmp_path / "remesh.ma"))
        cmds.polySphere(name="blob", subdivisionsAxis=40, subdivisionsHeight=40)
        result = modeling.remesh_retopo(
            {"mesh": "|blob", "target_polycount": 400, "keep_original": True}
        )
        assert result["method"] in ("polyRetopo", "polyRemesh", "polyReduce")
        assert cmds.objExists("blob_orig")
        assert cmds.getAttr("blob_orig.visibility") is False
        # the hidden duplicate's name must come back so the LLM can find/clean it
        assert result["original"] == "|blob_orig"

    def test_remesh_reports_no_original_when_keep_original_false(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        cmds.file(rename=str(tmp_path / "remesh_no_orig.ma"))
        cmds.polySphere(name="blob_bare", subdivisionsAxis=40, subdivisionsHeight=40)
        result = modeling.remesh_retopo(
            {"mesh": "|blob_bare", "target_polycount": 400, "keep_original": False}
        )
        assert result["original"] is None
        assert not cmds.objExists("blob_bare_orig")

    def test_remesh_polyreduce_percentage_warning_distinguishes_query_failure(
        self, tmp_path, monkeypatch
    ):
        # Minor finding: if polyEvaluate(face=True) ever returns a non-int,
        # the old code silently left percentage at 0 and still claimed
        # "target_polycount %d >= current face count %s" - lying about a
        # query failure as if it were the ordinary "nothing to reduce" case.
        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        def _raise(*args, **kwargs):
            raise RuntimeError("forced fallback for test")

        monkeypatch.setattr(cmds, "polyRetopo", _raise)
        monkeypatch.setattr(cmds, "polyRemesh", _raise)
        real_poly_evaluate = cmds.polyEvaluate

        def _flaky_poly_evaluate(*args, **kwargs):
            if kwargs.get("face"):
                return {"unexpected": "shape"}  # not an int
            return real_poly_evaluate(*args, **kwargs)

        monkeypatch.setattr(cmds, "polyEvaluate", _flaky_poly_evaluate)

        cmds.file(rename=str(tmp_path / "remesh_badeval.ma"))
        cmds.polySphere(name="blob3", subdivisionsAxis=40, subdivisionsHeight=40)
        result = modeling.remesh_retopo(
            {"mesh": "|blob3", "target_polycount": 400, "keep_original": False}
        )
        assert result["method"] == "polyReduce"
        assert any(
            "polyEvaluate" in w and "int" in w for w in result["warnings"]
        ), result["warnings"]
        assert not any("target_polycount" in w for w in result["warnings"])

    def test_cleanup_reports_before_after(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        cmds.polyCube(name="dirty")
        cmds.xform("dirty", t=(3, 1, 0), ro=(10, 20, 30))
        result = modeling.mesh_cleanup({"mesh": "|dirty"})
        assert result["before"]["tris"] == result["after"]["tris"] == 12
        # frozen: transform is identity now
        assert cmds.xform("dirty", q=True, ws=True, t=True) == [0.0, 0.0, 0.0]

    def test_sculpt_deformer_uses_sculpt_command_not_nonlinear(self):
        # Finding 1: Maya's nonLinear command has no "sculpt" type -
        # deformer="sculpt" must route to cmds.sculpt, which does accept
        # maxDisplacement/dropoffDistance. Verify against real Maya that the
        # call succeeds and that the returned handle (nodes[1], the origin
        # locator) actually moves the mesh when translated - confirming it
        # is the correct "movable handle", not a fixed reference node.
        import maya.cmds as cmds

        from maya_plugin.handlers import sculpt

        cmds.polySphere(name="sculpt_target", subdivisionsAxis=20, subdivisionsHeight=20, radius=5)
        result = sculpt.deform(
            {"mesh": "|sculpt_target", "deformer": "sculpt",
             "params": {"maxDisplacement": 1.0, "dropoffDistance": 2.0,
                        "translate": [0, 4, 0]}}
        )
        assert result["baked"] is False
        assert len(result["deformer_nodes"]) == 3  # [deformer, origin, stretchOrigin]
        assert cmds.nodeType(result["deformer_nodes"][0]) == "sculpt"
        # the top-pole vertex (0, 5, 0) sits inside the moved origin's
        # dropoff and must have been displaced by the deform call above.
        n = cmds.polyEvaluate("sculpt_target", vertex=True)
        top = next(
            i for i in range(n)
            if abs(cmds.pointPosition("sculpt_target.vtx[%d]" % i, world=True)[0]) < 0.3
            and abs(cmds.pointPosition("sculpt_target.vtx[%d]" % i, world=True)[2]) < 0.3
            and cmds.pointPosition("sculpt_target.vtx[%d]" % i, world=True)[1] > 0
        )
        moved = cmds.pointPosition("sculpt_target.vtx[%d]" % top, world=True)
        assert moved != [0.0, 5.0, 0.0]

    def test_lattice_deformer_moves_lattice_not_base(self):
        # Finding 2: cmds.lattice returns [ffd, lattice, base]; the FFD
        # deforms via the relative offset between lattice and base, so the
        # handle we translate must be nodes[1] (the lattice), not nodes[-1]
        # (the base, which is a fixed reference and moving it alone is
        # wrong / a no-op relative to the mesh).
        import maya.cmds as cmds

        from maya_plugin.handlers import sculpt

        cmds.polyCube(name="lattice_target")
        before = cmds.pointPosition("lattice_target.vtx[0]", world=True)
        result = sculpt.deform(
            {"mesh": "|lattice_target", "deformer": "lattice",
             "params": {"translate": [1, 0, 0]}}
        )
        assert result["baked"] is False
        deformer_nodes = result["deformer_nodes"]
        assert len(deformer_nodes) == 3  # [ffd, lattice, base]
        assert cmds.nodeType(deformer_nodes[0]) == "ffd"
        after = cmds.pointPosition("lattice_target.vtx[0]", world=True)
        assert after != before  # translating the lattice actually deformed the mesh

    def test_remesh_retopo_polyreduce_fallback_reduces_toward_target(self, tmp_path, monkeypatch):
        # Finding 3: with polyRetopo/polyRemesh forced unavailable, the
        # polyReduce fallback's percentage must be the reduction *amount*
        # (not the keep-fraction) - verified against real Maya by checking
        # the resulting face count actually lands near target_polycount
        # instead of barely reducing at all.
        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        def _raise(*args, **kwargs):
            raise RuntimeError("forced fallback for test")

        monkeypatch.setattr(cmds, "polyRetopo", _raise)
        monkeypatch.setattr(cmds, "polyRemesh", _raise)

        cmds.file(rename=str(tmp_path / "remesh_fallback.ma"))
        cmds.polySphere(name="blob2", subdivisionsAxis=40, subdivisionsHeight=40)
        before_faces = cmds.polyEvaluate("blob2", face=True)
        result = modeling.remesh_retopo(
            {"mesh": "|blob2", "target_polycount": 400, "keep_original": False}
        )
        assert result["method"] == "polyReduce"
        assert any("polyRetopo" in w for w in result["warnings"])
        assert any("polyRemesh" in w for w in result["warnings"])
        after_faces = cmds.polyEvaluate("blob2", face=True)
        assert after_faces < before_faces
        # With the inverted-percentage bug, a 1600->400 target reduces by
        # ~4% (barely moves); the fix lands close to the 400 target.
        assert after_faces <= 500

    def test_flare_sine_wave_and_squash_apply_and_bake(self):
        # Attribute names come from Maya, not from documentation: this test is
        # what makes the whitelist trustworthy. squash is here too - it's one
        # of the pre-existing types (bend/squash/twist) whose param wiring the
        # refactor to a uniform create-then-setAttr path changed, and it was
        # otherwise verified nowhere against real Maya.
        import maya.cmds as cmds

        from maya_plugin.handlers import sculpt

        cases = [
            ("flare", {"curve": 0.4, "startFlareX": 1.4, "endFlareX": 0.4}),
            ("sine", {"amplitude": 0.3, "wavelength": 2.0}),
            ("wave", {"amplitude": 0.2, "wavelength": 1.5, "maxRadius": 3.0}),
            ("squash", {"factor": 0.5}),
        ]
        for kind, params in cases:
            cmds.file(new=True, force=True)
            cmds.polyCylinder(name="stalk", height=6, subdivisionsY=12)
            before = cmds.xform("stalk", query=True, boundingBox=True)
            result = sculpt.deform(
                {"mesh": "|stalk", "deformer": kind, "params": params,
                 "delete_history_after": True}
            )
            after = cmds.xform("stalk", query=True, boundingBox=True)
            assert result["baked"] is True, kind
            assert before != after, "%s deformed nothing" % kind

    def test_flare_actually_tapers(self):
        # The whole reason flare is in this milestone: a limb that is wide at
        # one end and narrow at the other. Asserting "the bbox changed" would
        # pass for any deformer; this asserts the SHAPE.
        import maya.cmds as cmds

        from maya_plugin.handlers import sculpt

        cmds.file(new=True, force=True)
        cmds.polyCylinder(name="limb", height=6, subdivisionsY=16)
        sculpt.deform(
            {"mesh": "|limb", "deformer": "flare",
             "params": {"startFlareX": 1.8, "startFlareZ": 1.8,
                        "endFlareX": 0.4, "endFlareZ": 0.4},
             "delete_history_after": True}
        )
        verts = cmds.xform("limb.vtx[*]", query=True, worldSpace=True, translation=True)
        points = [verts[i:i + 3] for i in range(0, len(verts), 3)]
        low = [p for p in points if p[1] < -2.0]
        high = [p for p in points if p[1] > 2.0]
        assert low and high, (
            "no vertices found beyond y=-2.0/+2.0 - flare's Y range moved, "
            "so the taper comparison below has nothing to measure"
        )
        width_low = max(abs(p[0]) for p in low)
        width_high = max(abs(p[0]) for p in high)
        assert width_low > width_high * 1.5, (
            "flare did not taper: bottom %.3f, top %.3f" % (width_low, width_high)
        )


class TestM1AcceptanceGate:
    def test_boolean_rune_cavity_undo_restore_zero_orphans(self, tmp_path):
        import queue
        import threading
        import time

        import maya.cmds as cmds

        from maya_plugin.dispatcher import Dispatcher
        from maya_plugin.maya_mcp_plugin import _build_handlers, _undo_hooks

        cmds.file(rename=str(tmp_path / "gate.ma"))
        undo_open, undo_close = _undo_hooks()

        # Maya 2027's mayapy standalone mis-parses undoInfo(closeChunk=True)
        # and any query=True command call when it runs on a thread other
        # than the one that called maya.standalone.initialize() (raising a
        # misleading "must be passed a boolean argument" TypeError).
        # Production never hits this: PluginServer wires main_thread_exec to
        # maya.utils.executeInMainThreadWithResult, which marshals every
        # handler call onto Maya's real GUI main thread. That same call
        # hangs forever here (headless mayapy has no Qt event loop to pump
        # it), so it can't be reused verbatim for this gate. Instead the
        # gate supplies its own main_thread_exec: a queue that THIS test
        # method's thread — the pytest/mayapy main thread that initialized
        # standalone (see the session-scoped maya_session fixture) — pumps
        # below, while the actual call(...) sequence runs on a helper
        # thread (handle_request() blocks its caller, so the thread doing
        # the pumping cannot also be the one making the calls). Do not
        # "simplify" this back to a bare Dispatcher(...) with no
        # main_thread_exec (silently runs handlers on the wrong thread and
        # hits the TypeError above) or to executeInMainThreadWithResult
        # (deadlocks headless) — either "simplification" turns this gate
        # into a deadlock or a false pass.
        _SENTINEL = object()
        work_queue: "queue.Queue" = queue.Queue()

        def main_thread_exec(fn):
            result_slot: dict = {}
            done = threading.Event()
            work_queue.put((fn, result_slot, done))
            done.wait()
            if "error" in result_slot:
                raise result_slot["error"]
            return result_slot["value"]

        dispatcher = Dispatcher(
            _build_handlers(),
            main_thread_exec=main_thread_exec,
            undo_open=undo_open,
            undo_close=undo_close,
        )

        def call(cmd, **params):
            frame = {"v": 1, "id": cmd, "cmd": cmd, "params": params}
            response = dispatcher.handle_request(frame)
            assert response["status"] == "ok", response
            return response["result"]

        helper_failure = []

        def run_sequence():
            try:
                call("create_primitive", kind="cube", name="gate_block",
                     scale=[2, 2, 2])
                checkpoint = call("checkpoint", label="pre_cavity")

                # rune cavity: a cutter cube booleaned out of the block
                call("create_primitive", kind="cube", name="gate_cutter",
                     translate=[0, 0, 1.0], scale=[0.6, 1.2, 0.4])
                carved = call("boolean_op", a="|gate_block", b="|gate_cutter",
                              op="difference", new_name="gate_carved")
                assert carved["watertight"] is True
                assert carved["tris"] > 12

                # zero orphan history nodes, ever
                assert cmds.ls(type="polyCBoolOp") == []
                shape = cmds.listRelatives("|gate_carved", shapes=True,
                                           fullPath=True)[0]
                # cmds.listHistory returns short names on this Maya version (same
                # quirk as the boolean/deform tests above), so resolve to
                # canonical long names before comparing. Unrelated to threading:
                # reproduces identically on the true main thread.
                history = [(cmds.ls(h, long=True) or [h])[0]
                           for h in cmds.listHistory(shape)]
                assert history == [shape]

                # undo the boolean: ONE step (the whole tool call was one chunk)
                undone = call("undo", steps=1)
                assert undone["undone"] == 1
                assert cmds.objExists("gate_block") and cmds.objExists("gate_cutter")
                assert not cmds.objExists("gate_carved")

                # restore the pre-cavity checkpoint: block only, no cutter
                restored = call("restore_checkpoint",
                                checkpoint_id=checkpoint["checkpoint_id"])
                assert restored["restored"] == checkpoint["checkpoint_id"]
                assert cmds.objExists("gate_block")
                assert not cmds.objExists("gate_cutter")
                assert not cmds.objExists("gate_carved")

                # scene-wide orphan sweep (I1: lattice/baseLattice/nonlinear
                # handle shape types added so this gate would also catch a
                # regression in sculpt.deform's delete_history_after handle
                # cleanup, not just boolean_op's history discipline)
                for orphan_type in (
                    "polyCBoolOp", "type", "typeExtrude", "groupParts",
                    "lattice", "baseLattice",
                    "deformBend", "deformSquash", "deformTwist",
                ):
                    assert cmds.ls(type=orphan_type) == [], orphan_type
            except BaseException as exc:  # re-raised on the main thread below
                helper_failure.append(exc)
            finally:
                # Always unblock the pump, success or failure, so a mid-sequence
                # assertion failure (or any other exception) can never hang it.
                work_queue.put(_SENTINEL)

        helper = threading.Thread(
            target=run_sequence, name="gate-sequence", daemon=True
        )
        helper.start()

        deadline = time.monotonic() + 30.0
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AssertionError(
                        "gate pump timed out waiting for the helper thread "
                        "(possible deadlock feeding main_thread_exec)"
                    )
                try:
                    item = work_queue.get(timeout=remaining)
                except queue.Empty:
                    raise AssertionError(
                        "gate pump timed out waiting for the helper thread "
                        "(possible deadlock feeding main_thread_exec)"
                    )
                if item is _SENTINEL:
                    break
                fn, result_slot, done = item
                try:
                    result_slot["value"] = fn()
                except BaseException as exc:  # propagate to the dispatcher worker intact
                    result_slot["error"] = exc
                finally:
                    done.set()
        finally:
            helper.join(timeout=5.0)
            dispatcher.shutdown()

        if helper_failure:
            raise helper_failure[0]


class TestLightingInMaya:
    def test_replace_existing_removes_exactly_the_prior_lights(self, tmp_path):
        # A full node-count diff, not a spot check: this tool deletes user
        # work, and "removed one thing too many" is the failure that matters.
        #
        # The fixture also covers I1 (over-deletion, CRITICAL): a light
        # transform that also carries a mesh shape, and a light transform
        # with a child node parented under it. cmds.delete(transform)
        # deletes the whole subtree, so a naive "delete the transform" pass
        # would take the mesh and the child down with the light - that is
        # exactly what the old code did, and why an earlier version of this
        # fixture (light alone, no children, no co-located shapes) missed it.
        import maya.cmds as cmds

        from maya_plugin.handlers import lighting

        cmds.file(new=True, force=True)
        cmds.file(rename=str(tmp_path / "lighting.ma"))
        cmds.polyCube(name="keepme")
        cmds.spaceLocator(name="keepme_loc")
        old_shape = cmds.ls(cmds.directionalLight(name="old_key"), long=True)[0]
        old_transform = cmds.listRelatives(old_shape, parent=True, fullPath=True)[0]

        # A light transform that ALSO holds a mesh shape (two shapes, one
        # transform) - reparent a cube's shape onto the light's transform.
        shared_shape = cmds.ls(cmds.directionalLight(name="old_shared"), long=True)[0]
        shared_transform = cmds.listRelatives(shared_shape, parent=True, fullPath=True)[0]
        cube_tf = cmds.polyCube(name="shared_mesh_src")[0]
        cube_shape = cmds.listRelatives(cube_tf, shapes=True, fullPath=True)[0]
        cmds.parent(cube_shape, shared_transform, relative=True, shape=True)
        cmds.delete(cube_tf)  # now-empty source transform; the shape lives on shared_transform
        mesh_under_shared = [
            s for s in cmds.listRelatives(shared_transform, shapes=True, fullPath=True) or []
            if cmds.nodeType(s) == "mesh"
        ][0]

        # A light transform with a child node (a locator) parented under it.
        child_shape = cmds.ls(cmds.directionalLight(name="old_with_child"), long=True)[0]
        child_transform = cmds.listRelatives(child_shape, parent=True, fullPath=True)[0]
        cmds.spaceLocator(name="old_with_child_loc")
        cmds.parent("old_with_child_loc", child_transform)
        child_loc = child_transform + "|old_with_child_loc"

        before = set(cmds.ls(long=True))

        result = lighting.setup_lighting(
            {"preset": "three_point", "replace_existing": True}
        )

        assert cmds.objExists("|keepme")
        assert cmds.objExists("|keepme_loc")
        # the isolated light: fully removed, transform included
        assert not cmds.objExists(old_transform)
        assert not cmds.objExists(old_shape)
        # the mesh-sharing transform: light shape gone, transform + mesh survive
        assert not cmds.objExists(shared_shape)
        assert cmds.objExists(shared_transform)
        assert cmds.objExists(mesh_under_shared)
        # the transform with a child locator: light shape gone, transform + child survive
        assert not cmds.objExists(child_shape)
        assert cmds.objExists(child_transform)
        assert cmds.objExists(child_loc)

        assert len(result["lights"]) == 3
        assert result["removed"] == ["old_key"]
        assert len(result["warnings"]) == 2, \
            "the two spared transforms (shared mesh, child locator) must be surfaced"

        # every surviving pre-existing node is still there - a full set
        # diff against exactly the nodes that were legitimately deleted
        after = set(cmds.ls(long=True))
        expected_vanished = {old_transform, old_shape, shared_shape, child_shape}
        vanished = before - after
        assert vanished == expected_vanished, (
            "setup_lighting deleted more or less than the light shapes/isolated "
            "transform: extra=%s missing=%s"
            % (vanished - expected_vanished, expected_vanished - vanished)
        )

    def test_build_hdri_sweeps_orphans_on_forced_connect_failure(self, monkeypatch, tmp_path):
        # IMPORTANT (I2): _build_hdri creates a light, then a file texture,
        # then connects them - a failure on the connect must not leave
        # either behind. This runs after the delete step, so a miss here
        # means prior lights are already gone AND stray half-built nodes
        # remain.
        import maya.cmds as cmds

        from maya_plugin.handlers import lighting

        cmds.file(new=True, force=True)
        cmds.file(rename=str(tmp_path / "lighting_hdri_sweep.ma"))
        before = set(cmds.ls(long=True))

        def _boom(*args, **kwargs):
            raise RuntimeError("forced connectAttr failure")

        monkeypatch.setattr(cmds, "connectAttr", _boom)

        with pytest.raises(RuntimeError, match="forced connectAttr failure"):
            lighting.setup_lighting({
                "preset": "hdri",
                "hdri_path": str(tmp_path / "sky.hdr"),
                "replace_existing": False,
            })

        after = set(cmds.ls(long=True))
        assert after == before, (
            "the orphaned light + file texture must be swept: %s" % (after - before)
        )

    def test_build_three_point_sweeps_in_flight_light_on_xform_failure(self, monkeypatch, tmp_path):
        # IMPORTANT: _build must record a created light's transform BEFORE
        # the xform() call that can fail on it, mirroring _build_hdri. If it
        # records only after xform succeeds, a failure on light N leaves
        # lights 1..N-1 swept but light N itself - already created via
        # directionalLight() - never makes it into `created`, so it leaks.
        import maya.cmds as cmds

        from maya_plugin.handlers import lighting

        cmds.file(new=True, force=True)
        cmds.file(rename=str(tmp_path / "lighting_xform_sweep.ma"))
        before = set(cmds.ls(long=True))

        real_xform = cmds.xform
        calls = []

        def _flaky_xform(*args, **kwargs):
            calls.append(args)
            if len(calls) == 2:
                raise RuntimeError("forced xform failure")
            return real_xform(*args, **kwargs)

        monkeypatch.setattr(cmds, "xform", _flaky_xform)

        with pytest.raises(RuntimeError, match="forced xform failure"):
            lighting.setup_lighting({"preset": "three_point", "replace_existing": False})

        after = set(cmds.ls(long=True))
        assert after == before, (
            "the in-flight second light must be swept too, not just the "
            "completed first light: %s" % (after - before)
        )

    def test_lights_actually_light_the_scene(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import lighting

        cmds.file(new=True, force=True)
        cmds.file(rename=str(tmp_path / "lighting_shape.ma"))
        result = lighting.setup_lighting({"preset": "single_sun", "intensity": 2.0})
        shapes = cmds.listRelatives(result["lights"][0], shapes=True, fullPath=True)
        assert cmds.nodeType(shapes[0]) == "directionalLight"
        # #617: `intensity` is a UNIT - 1.0 means a surface facing the key reads
        # its own albedo - and the handler carries the pi, because Arnold's
        # distant light and VP2 both return albedo/pi at raw intensity 1.0. So
        # the raw attribute on the node is 2*pi, and pi is written literally
        # rather than as lighting.FULLY_LIT: a future change to the factor
        # SHOULD fail here and send the reader back to #617, not pass silently.
        assert cmds.getAttr(shapes[0] + ".intensity") == pytest.approx(2.0 * math.pi)


class TestTextureRecipesInMaya:
    def test_recipe_connects_and_rejects_missing_file_path_before_creating_nodes(
        self, tmp_path
    ):
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import material, texture_recipes

        cmds.file(new=True, force=True)
        cmds.file(rename=str(tmp_path / "recipes.ma"))
        cmds.polyCube(name="texcube", w=2, h=2, d=2)
        material.assign_material({"mesh": "|texcube", "name": "clay"})

        before = set(cmds.ls(long=True))
        result = texture_recipes.apply_texture_recipe(
            {"mesh": "|texcube", "recipe": "noise_bump"}
        )
        assert len(result["nodes"]) == 2
        assert cmds.listConnections("clay.normalCamera") != []

        # file_texture's missing-file_path check is its very first line, so
        # this only proves a pre-flight validation failure has no side
        # effects - it never exercises the sweep itself (no node exists to
        # sweep). See test_sweep_removes_real_nodes_after_partial_failure
        # below for that.
        mid = set(cmds.ls(long=True))
        with pytest.raises(HandlerError):
            texture_recipes.apply_texture_recipe(
                {"mesh": "|texcube", "recipe": "file_texture"}  # no file_path
            )
        assert set(cmds.ls(long=True)) == mid

    def test_sweep_removes_real_nodes_after_partial_failure(self, tmp_path, monkeypatch):
        # Review finding: the test above's forced failure (file_texture with
        # no file_path) raises on _file_texture's very first line, before
        # any cmds.shadingNode call - so `created` is always empty and the
        # sweep's cmds.delete() path has never run against a real Maya node.
        # Force the failure AFTER noise_bump has created real noise/bump2d
        # nodes (both shadingNode calls happen before either connectAttr
        # call), by making the first connectAttr raise, and assert the full
        # scene node set - not just the tracked `created` list - returns to
        # exactly its pre-call snapshot.
        import maya.cmds as cmds

        from maya_plugin.handlers import material, texture_recipes

        cmds.file(new=True, force=True)
        cmds.file(rename=str(tmp_path / "recipes_sweep.ma"))
        cmds.polyCube(name="texcube2", w=2, h=2, d=2)
        material.assign_material({"mesh": "|texcube2", "name": "clay2"})

        real_connect_attr = cmds.connectAttr
        calls = []

        def _flaky_connect_attr(*args, **kwargs):
            calls.append(args)
            if len(calls) == 1:
                raise RuntimeError("forced connectAttr failure")
            return real_connect_attr(*args, **kwargs)

        monkeypatch.setattr(cmds, "connectAttr", _flaky_connect_attr)

        before = set(cmds.ls(long=True))
        with pytest.raises(RuntimeError, match="forced connectAttr failure"):
            texture_recipes.apply_texture_recipe(
                {"mesh": "|texcube2", "recipe": "noise_bump"}
            )
        after = set(cmds.ls(long=True))
        assert after == before, (
            "the noise/bump2d nodes created before the forced failure must "
            "be swept: %s" % (after - before)
        )


class TestMaterialInMaya:
    def test_transmission_and_ior_actually_set_on_a_real_standardsurface(self, tmp_path):
        # F1: transmission/ior are the whole optical identity of a gem - this
        # proves the values land on the real node, not just a fake.
        import maya.cmds as cmds

        from maya_plugin.handlers import material

        cmds.file(new=True, force=True)
        cmds.file(rename=str(tmp_path / "gem_material.ma"))
        cmds.polyCube(name="gemcube", w=2, h=2, d=2)

        result = material.assign_material({
            "mesh": "|gemcube", "shader": "standardSurface",
            "params": {
                "transmission": 0.92, "transmissionColor": [0.9, 0.97, 1.0],
                "ior": 1.5, "roughness": 0.05,
            },
            "name": "diamond_mat",
        })
        mat = result["material"]
        assert cmds.getAttr(mat + ".transmission") == pytest.approx(0.92)
        assert cmds.getAttr(mat + ".specularIOR") == pytest.approx(1.5)
        assert cmds.getAttr(mat + ".transmissionColor")[0] == pytest.approx(
            (0.9, 0.97, 1.0)
        )

    def test_same_name_reuses_one_shader_across_two_meshes(self, tmp_path):
        # F4: three iterations of one-material-per-mesh left ~108 dead
        # shaders for eight distinct gems in the real art run. Two calls with
        # the same name for two different meshes must produce ONE shader.
        import maya.cmds as cmds

        from maya_plugin.handlers import material

        cmds.file(new=True, force=True)
        cmds.file(rename=str(tmp_path / "gem_reuse.ma"))
        cmds.polyCube(name="reuse_a")
        cmds.polyCube(name="reuse_b")

        first = material.assign_material({
            "mesh": "|reuse_a", "shader": "standardSurface",
            "params": {"baseColor": [0.2, 0.6, 0.9]}, "name": "shared_gem",
        })
        second = material.assign_material({
            "mesh": "|reuse_b", "shader": "standardSurface",
            "params": {"transmission": 0.8}, "name": "shared_gem",
        })

        assert first["material"] == "shared_gem"
        assert second["material"] == "shared_gem"
        assert cmds.ls("shared_gem*", type="standardSurface") == ["shared_gem"]
        assert cmds.getAttr("shared_gem.transmission") == pytest.approx(0.8)

        shape_a = cmds.listRelatives("|reuse_a", shapes=True, fullPath=True)[0]
        shape_b = cmds.listRelatives("|reuse_b", shapes=True, fullPath=True)[0]
        sg = first["shading_group"]
        members = [m.split("|")[-1] for m in (cmds.sets(sg, query=True) or [])]
        assert shape_a.split("|")[-1] in members
        assert shape_b.split("|")[-1] in members

    def test_assigned_material_reads_back_through_get_object_info(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import material, objinfo

        cmds.file(new=True, force=True)
        cmds.file(rename=str(tmp_path / "material.ma"))
        cmds.polyCube(name="matcube", w=2, h=2, d=2)

        result = material.assign_material({
            "mesh": "|matcube", "shader": "standardSurface",
            "params": {"baseColor": [0.4, 0.3, 0.25], "roughness": 0.8},
            "name": "clay",
        })
        info = objinfo.get_object_info({"name": "|matcube", "include": ["shading"]})
        assert info["shading"]["materials"] == [result["material"]]
        assert info["shading"]["per_face"] is False
        assert cmds.getAttr(result["material"] + ".specularRoughness") == pytest.approx(0.8)

    def test_assign_takes_no_checkpoint(self, tmp_path):
        # Look-dev is a loop of small tweaks; checkpointing each would evict
        # the checkpoints that matter.
        import maya.cmds as cmds

        from maya_plugin.handlers import material, session

        cmds.file(new=True, force=True)
        cmds.file(rename=str(tmp_path / "material_cp.ma"))
        cmds.polyCube(name="cpcube")
        before = len(session._existing(session._checkpoint_dir(cmds)))
        material.assign_material({"mesh": "|cpcube", "params": {"roughness": 0.5}})
        after = len(session._existing(session._checkpoint_dir(cmds)))
        assert after == before

    def test_bad_param_type_leaves_scene_node_set_unchanged(self, tmp_path):
        # I2 (real Maya): the old code built the shader + SG and force-
        # assigned the mesh to it BEFORE type-checking param values, so a
        # bad param (scalar where a colour is required) orphaned both nodes
        # AND left the mesh half-reassigned, losing its prior material. A
        # full scene node-set diff, not just an orphan spot-check, is the
        # milestone rule: "after any failed call, scene node counts are
        # unchanged."
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import material

        cmds.file(new=True, force=True)
        cmds.file(rename=str(tmp_path / "material_orphan.ma"))
        cmds.polyCube(name="orphcube", w=2, h=2, d=2)
        original = material.assign_material(
            {"mesh": "|orphcube", "shader": "lambert",
             "params": {"color": [0.1, 0.2, 0.3]}, "name": "orig_mat"}
        )

        before = set(cmds.ls(long=True))
        with pytest.raises(HandlerError):
            material.assign_material({
                "mesh": "|orphcube", "shader": "standardSurface",
                "params": {"baseColor": 0.5}, "name": "bad_mat",
            })
        after = set(cmds.ls(long=True))
        assert after == before, (
            "assign_material left orphan nodes: %s" % (after - before)
        )

        # the mesh must still be wearing its ORIGINAL material, not
        # half-reassigned onto the refused call's shading group.
        shape = cmds.listRelatives("|orphcube", shapes=True, fullPath=True)[0]
        members = cmds.sets(original["shading_group"], query=True) or []
        assert shape.split("|")[-1] in [m.split("|")[-1] for m in members]


class TestPrimitiveBaseSize:
    """Every kind fills a 1-unit box at scale 1 (redmine #584, gem-brute run).

    Maya's own defaults disagree wildly - measured here: cube 1.0 across,
    sphere/cone/cylinder/octahedron 2.0, icosahedron 1.701, prism 0.866,
    pyramid 1.414, torus 3.0 - so swapping `kind` at a fixed scale silently
    resized the object, and the run built solids at twice the size it asked for.

    The guarantee is the BOX, not the width: a triangular prism spans 1.0 across
    a corner and 0.866 across the flats, so no single kind-independent "width"
    exists. Largest dimension exactly 1, nothing outside the box.
    """

    @pytest.mark.parametrize("kind", [
        "cube", "plane", "sphere", "cone", "cylinder", "torus",
        "octahedron", "icosahedron", "prism", "pyramid",
    ])
    def test_unit_size_at_scale_one(self, kind):
        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        result = modeling.create_primitive({"kind": kind, "name": "sizeCheck"})
        bbox = cmds.exactWorldBoundingBox(result["name"])
        dims = (bbox[3] - bbox[0], bbox[4] - bbox[1], bbox[5] - bbox[2])
        assert max(dims) == pytest.approx(1.0, abs=0.02), (
            "%s measures %s; every kind must fill the same unit box"
            % (kind, tuple(round(d, 3) for d in dims))
        )


class TestFramingExcludesLightsInMaya:
    """#639's load-bearing assumption, pinned against the real Maya: a dome is
    returned by ls(geometry=True), and Maya's own classification calls it a
    light. The headless tests encode these answers; this is what checks them."""

    def test_ls_geometry_really_does_return_a_dome(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import capture, lighting

        cmds.file(rename=str(tmp_path / "framing.ma"))
        cmds.polyCube(name="subject", w=5, h=5, d=5)
        result = lighting.setup_lighting({"preset": "environment"})
        dome = result["lights"][0]
        shape = cmds.listRelatives(dome, shapes=True, fullPath=True)[0]
        if cmds.nodeType(shape) != "aiSkyDomeLight":
            pytest.skip("no Arnold dome in this mayapy: %s" % cmds.nodeType(shape))

        visible = cmds.ls(geometry=True, visible=True) or []
        assert any(v.split("|")[-1] == shape.split("|")[-1] for v in visible), (
            "the premise of the fix: a light shape comes back from ls(geometry=True)"
        )
        assert capture.is_light_shape(cmds, shape) is True
        assert cmds.exactWorldBoundingBox(shape)[3] > 100  # it is enormous

    def test_the_dome_does_not_decide_where_the_camera_goes(self, tmp_path):
        import math

        import maya.cmds as cmds

        from maya_plugin.handlers import capture, lighting

        cmds.file(rename=str(tmp_path / "framing2.ma"))
        cmds.polyCube(name="subject2", w=5, h=5, d=5)
        lighting.setup_lighting({"preset": "environment"})

        bbox_min, bbox_max = capture._scene_bbox(cmds, None)
        assert bbox_max[0] == pytest.approx(2.5, abs=1e-4)
        assert bbox_min[0] == pytest.approx(-2.5, abs=1e-4)
        position, _ = capture.camera_placement("three_quarter", bbox_min, bbox_max)
        assert math.dist([0, 0, 0], position) < 100.0


class TestBboxSeesHiddenChildren:
    """#640-4's load-bearing measurement, pinned against the real Maya.

    The fake cmds in tests/test_render.py encodes these two answers, and the
    sheet's framing fix rests entirely on the second one. If a Maya version ever
    changed either, the headless tests would keep passing while every nested
    sheet cell went back to framing a subtree it had hidden.
    """

    def _nested(self, cmds, tmp_path, name):
        cmds.file(rename=str(tmp_path / name))
        parent = cmds.polyCube(name="pelvisBox", w=1, h=1, d=1)[0]
        child = cmds.polyCube(name="chestBox", w=1, h=1, d=1)[0]
        cmds.xform(child, ws=True, t=(20, 0, 0))
        cmds.parent(child, parent)
        return parent, cmds.listRelatives(child, shapes=True, fullPath=True)[0]

    def test_a_parents_bbox_includes_a_HIDDEN_child(self, tmp_path):
        import maya.cmds as cmds

        parent, child_shape = self._nested(cmds, tmp_path, "bboxhidden.ma")
        cmds.hide(child_shape)
        assert cmds.exactWorldBoundingBox(parent)[3] == pytest.approx(20.5, abs=1e-4), (
            "hiding a child does NOT shrink the parent's box - which is why "
            "hiding the sub-assemblies was not enough to fix the framing"
        )

    def test_ignoreInvisible_is_what_measures_what_will_be_seen(self, tmp_path):
        import maya.cmds as cmds

        parent, child_shape = self._nested(cmds, tmp_path, "bboxignore.ma")
        cmds.hide(child_shape)
        assert cmds.exactWorldBoundingBox(
            parent, ignoreInvisible=True
        )[3] == pytest.approx(0.5, abs=1e-4)

    def test_scene_bbox_passes_the_flag_through(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import capture

        parent, child_shape = self._nested(cmds, tmp_path, "bboxflag.ma")
        cmds.hide(child_shape)
        _, subtree_max = capture._scene_bbox(cmds, [parent])
        _, visible_max = capture._scene_bbox(cmds, [parent], visible_only=True)
        assert subtree_max[0] == pytest.approx(20.5, abs=1e-4)
        assert visible_max[0] == pytest.approx(0.5, abs=1e-4)


def _serpent_cylinder(cmds, name="tube", height=4.0, sections=12):
    """A cylinder standing on Y with enough length subdivisions to bend."""
    node = cmds.polyCylinder(name=name, radius=0.3, height=height,
                             subdivisionsY=sections, ch=False)[0]
    cmds.xform(node, worldSpace=True, translation=[0, height / 2.0, 0])
    return (cmds.ls(node, long=True) or [node])[0]


class TestCreateSkeletonInMaya:
    def test_chain_builds_parented_joints_at_the_positions(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        out = rigging.create_skeleton({
            "chain": [[0, 0, 0], [0, 2, 0], [0, 4, 0]], "chain_prefix": "sp"})
        assert out["root"] == "|sp_01"
        assert cmds.nodeType(out["root"]) == "joint"
        assert [tuple(round(v, 6) for v in j["position"])
                for j in out["joints"]] == [(0, 0, 0), (0, 2, 0), (0, 4, 0)]
        # Parented: moving the root carries the chain.
        cmds.xform("|sp_01", worldSpace=True, translation=[1, 0, 0])
        tip = cmds.xform(out["joints"][2]["name"], query=True,
                         worldSpace=True, translation=True)
        assert tip[0] == pytest.approx(1.0)

    def test_default_orient_aims_x_at_the_child_and_zeroes_the_leaf(self):
        from maya_plugin.handlers import rigging

        out = rigging.create_skeleton({
            "chain": [[0, 0, 0], [0, 2, 0]], "chain_prefix": "o"})
        # A straight +Y chain under xyz/yup: X aims at the child, so the root
        # carries a 90-degree orient about Z, and the leaf carries none.
        assert out["joints"][0]["orient"][2] == pytest.approx(90.0, abs=1e-4)
        assert out["joints"][1]["orient"] == pytest.approx([0.0, 0.0, 0.0])

    def test_explicit_orient_overrides_and_reports_in_degrees(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        cmds.currentUnit(angle="rad")
        try:
            out = rigging.create_skeleton({"joints": [
                {"name": "solo", "position": [0, 0, 0], "orient": [0, 45, 0]}]})
            assert out["joints"][0]["orient"][1] == pytest.approx(45.0, abs=1e-4)
        finally:
            cmds.currentUnit(angle="deg")

    def test_single_joint_skeleton_works(self):
        from maya_plugin.handlers import rigging

        out = rigging.create_skeleton({"joints": [
            {"name": "lone", "position": [1, 2, 3]}]})
        assert out["root"] == "|lone"
        assert out["joints"][0]["position"] == pytest.approx([1.0, 2.0, 3.0])


class TestBindSkinInMaya:
    def _chain(self, rigging, n=4, height=4.0):
        step = height / (n - 1)
        return rigging.create_skeleton({
            "chain": [[0, i * step, 0] for i in range(n)],
            "chain_prefix": "bj"})

    def test_bind_owns_every_vertex(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        mesh = _serpent_cylinder(cmds)
        skel = self._chain(rigging)
        out = rigging.bind_skin({"mesh": mesh, "root": skel["root"]})
        assert out["unweighted_vertices"] == 0
        assert len(out["influences"]) == 4
        assert all(p["vertices"] > 0 for p in out["per_joint"])
        total_verts = cmds.polyEvaluate(mesh, vertex=True)
        assert sum(p["vertices"] for p in out["per_joint"]) >= total_verts

    def test_rebind_is_refused_against_a_real_skincluster(self):
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import rigging

        mesh = _serpent_cylinder(cmds, name="tube2")
        skel = self._chain(rigging)
        rigging.bind_skin({"mesh": mesh, "root": skel["root"]})
        with pytest.raises(HandlerError, match="already bound"):
            rigging.bind_skin({"mesh": mesh, "root": skel["root"]})

    def test_max_influences_is_obeyed_in_the_weights(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        mesh = _serpent_cylinder(cmds, name="tube3")
        skel = self._chain(rigging, n=6)
        out = rigging.bind_skin({"mesh": mesh, "root": skel["root"],
                                 "max_influences": 2})
        assert out["max_influences_exceeded"] == 0

    def test_binding_a_mid_chain_root_warns_about_joints_above_it(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        mesh = _serpent_cylinder(cmds, name="tube4")
        skel = self._chain(rigging, n=4)
        joints = [j["name"] for j in skel["joints"]]
        true_root, mid_root = joints[0], joints[1]

        out = rigging.bind_skin({"mesh": mesh, "root": mid_root})
        assert out["unweighted_vertices"] >= 0  # bind succeeded, not asserting shape
        assert any(
            "OUTSIDE the hierarchy" in w and rigging._short(true_root) in w
            for w in out["warnings"])

    def test_binding_the_true_root_stays_warning_free(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        mesh = _serpent_cylinder(cmds, name="tube5")
        skel = self._chain(rigging, n=4)
        out = rigging.bind_skin({"mesh": mesh, "root": skel["root"]})
        assert not any("OUTSIDE the hierarchy" in w for w in out["warnings"])


class TestPoseSkeletonInMaya:
    def _bound_serpent(self, cmds, rigging, name="ptube", n=4, height=4.0):
        mesh = _serpent_cylinder(cmds, name=name, height=height)
        step = height / (n - 1)
        skel = rigging.create_skeleton({
            "chain": [[0, i * step, 0] for i in range(n)],
            "chain_prefix": name + "_j"})
        rigging.bind_skin({"mesh": mesh, "root": skel["root"]})
        return mesh, skel

    def test_a_bend_actually_moves_the_mesh(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        mesh, skel = self._bound_serpent(cmds, rigging)
        mid = skel["joints"][1]["name"]
        out = rigging.pose_skeleton({"root": skel["root"],
                                     "rotations": {mid: [0, 0, 90]}})
        # Everything above the mid joint (~2/3 of a 4-unit tube) swings a
        # quarter turn; the tip alone travels ~sqrt(2)*2.67/... - pin loosely,
        # the exact arc is the live gate's job.
        assert out["max_displacement"] > 1.0
        assert out["displaced_vertices"] > 0
        assert out["warnings"] == []
        # Joint world positions are reported for every joint, measured.
        tip = out["joints"][-1]["world_position"]
        assert tip[0] != pytest.approx(0.0, abs=1e-3)  # swung off the axis

    def test_rotations_mean_degrees_whatever_the_scene_unit_says(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        mesh, skel = self._bound_serpent(cmds, rigging, name="rtube")
        mid = skel["joints"][1]["name"]
        cmds.currentUnit(angle="rad")
        try:
            out = rigging.pose_skeleton({"root": skel["root"],
                                         "rotations": {mid: [0, 0, 90]}})
        finally:
            cmds.currentUnit(angle="deg")
        rz = cmds.getAttr(mid + ".rotateZ")  # queried in deg now
        assert rz == pytest.approx(90.0, abs=1e-4)
        assert out["max_displacement"] > 1.0

    def test_reset_pose_returns_to_bind_within_tolerance(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging, sculpt

        mesh, skel = self._bound_serpent(cmds, rigging, name="ztube")
        bind_positions = sculpt.vertex_positions(cmds, mesh)
        mid = skel["joints"][1]["name"]
        rigging.pose_skeleton({"root": skel["root"],
                               "rotations": {mid: [0, 0, 90]}})
        out = rigging.reset_pose({"root": skel["root"]})
        assert out["max_displacement"] > 1.0  # it undid a real pose
        from maya_plugin.handlers import sculpt_math
        assert sculpt_math.max_displacement(
            bind_positions, sculpt.vertex_positions(cmds, mesh)) < 1e-4

    def test_a_pose_on_an_empty_joint_warns_of_near_zero_motion(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        # Root joint far below the tube: bind gives it ~nothing.
        mesh = _serpent_cylinder(cmds, name="wtube")
        skel = rigging.create_skeleton({
            "chain": [[0, -50, 0], [0, -49, 0], [0, 2, 0], [0, 4, 0]],
            "chain_prefix": "w_j"})
        rigging.bind_skin({"mesh": mesh, "root": skel["root"]})
        out = rigging.pose_skeleton({
            "root": skel["root"],
            "rotations": {skel["joints"][0]["name"]: [0, 0, 1]}})
        # Whatever it measured is reported; if it moved almost nothing the
        # warning names the cause.
        if out["max_displacement"] < 0.05:
            assert any("near-zero" in w for w in out["warnings"])


class TestExportSkinsInMaya:
    def _bound(self, cmds, rigging, name):
        mesh = _serpent_cylinder(cmds, name=name, height=2.0, sections=6)
        skel = rigging.create_skeleton({
            "chain": [[0, 0, 0], [0, 1, 0], [0, 2, 0]],
            "chain_prefix": name + "_j"})
        rigging.bind_skin({"mesh": mesh, "root": skel["root"]})
        return mesh, skel

    def test_a_skinned_selected_export_carries_the_records(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import export, fbxbytes, rigging

        mesh, skel = self._bound(cmds, rigging, "xtube")
        out = export.export_fbx({
            "path": str(tmp_path / "skinned.fbx").replace("\\", "/"),
            "metres_per_unit": 1.0,
            "nodes": [mesh, skel["root"]],
            "include_skins": True,
        })
        assert out["skin"]["deformers"] == 1
        assert out["skin"]["clusters"] == 3
        assert out["skin"]["bind_pose_present"] is True
        assert out["skin"]["unweighted_file_vertices"] == 0
        assert out["skin"]["max_weight_sum_error"] < 1e-3
        facts = fbxbytes.read_fbx(out["path"])
        assert {n.kind for n in facts.nodes} >= {"Mesh", "LimbNode"}

    def test_default_export_stays_skinless(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import export, fbxbytes, rigging

        mesh, skel = self._bound(cmds, rigging, "ytube")
        out = export.export_fbx({
            "path": str(tmp_path / "plain.fbx").replace("\\", "/"),
            "metres_per_unit": 1.0,
            "nodes": [mesh],
        })
        assert out["skin"] is None
        assert fbxbytes.read_fbx(out["path"]).skins == {}

    def test_include_skins_without_a_bound_mesh_is_refused(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import export

        cube = cmds.polyCube(name="dryCube", ch=False)[0]
        with pytest.raises(HandlerError, match="no skin deformer"):
            export.export_fbx({
                "path": str(tmp_path / "dry.fbx").replace("\\", "/"),
                "metres_per_unit": 1.0,
                "nodes": [cube],
                "include_skins": True,
            })
        assert not (tmp_path / "dry.fbx").exists()

    def test_leaving_the_skeleton_out_of_nodes_is_refused_by_name(self, tmp_path):
        """The measurement behind FBX_SKINS_MEL[True] being skins-only.

        With input connections left off (the preamble's setting), selecting the
        mesh WITHOUT its root writes a deformer record carrying zero clusters.
        Turning FBXExportInputConnections on would make this succeed by
        silently widening the selection; it is refused instead, and the message
        has to name the missing skeleton rather than just the unweighted count.
        """
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import export, rigging

        mesh, _skel = self._bound(cmds, rigging, "ztube")
        with pytest.raises(HandlerError, match="skeleton root") as exc:
            export.export_fbx({
                "path": str(tmp_path / "short.fbx").replace("\\", "/"),
                "metres_per_unit": 1.0,
                "nodes": [mesh],
                "include_skins": True,
            })
        assert "links no joints" in str(exc.value)
        assert not (tmp_path / "short.fbx").exists()

    def test_a_max_influences_bind_survives_the_exporters_weight_pruning(
            self, tmp_path):
        """WEIGHT_SUM_TOL is 1e-2 because of THIS export, measured here.

        Maya's FBX exporter drops every skin weight below 1e-3 and does not
        renormalise, while Maya's own in-scene sums are 1.0 to 2.2e-16. A
        12-joint max_influences=8 bind loses up to three such weights on one
        vertex, so it left the file 1.38e-3 short of 1.0 - and the original
        1e-3 tolerance refused a bind nothing is wrong with.
        """
        import maya.cmds as cmds

        from maya_plugin.handlers import export, rigging

        mesh = _serpent_cylinder(cmds, name="ptube", height=4.0, sections=24)
        skel = rigging.create_skeleton({
            "chain": [[0, i * (4.0 / 11), 0] for i in range(12)],
            "chain_prefix": "p_j"})
        bind = rigging.bind_skin({"mesh": mesh, "root": skel["root"],
                                  "max_influences": 8})
        assert bind["unweighted_vertices"] == 0

        out = export.export_fbx({
            "path": str(tmp_path / "pruned.fbx").replace("\\", "/"),
            "metres_per_unit": 1.0,
            "nodes": [mesh, skel["root"]],
            "include_skins": True,
        })
        err = out["skin"]["max_weight_sum_error"]
        assert out["skin"]["unweighted_file_vertices"] == 0
        assert err < export.WEIGHT_SUM_TOL
        # The pruning is real, not hypothetical: if this ever drops to float
        # noise the exporter changed and the tolerance can be revisited.
        assert err > 1e-9, (
            "the exporter no longer prunes weights - remeasure WEIGHT_SUM_TOL")
