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
        assert cmds.getAttr(shapes[0] + ".intensity") == pytest.approx(2.0)


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
