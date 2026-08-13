"""Handler tests that need a real Maya: run under `mayapy -m pytest tests/test_handlers_mayapy.py`.

Skipped automatically when maya is not importable (regular CI / dev machines).
Viewport capture needs a GUI, so only its argument marshaling is asserted here;
real pixels are covered by the manual M0 loop test inside Maya.
"""

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
