"""Handler tests that need a real Maya: run under `mayapy -m pytest tests/test_handlers_mayapy.py`.

Skipped automatically when maya is not importable (regular CI / dev machines).
Viewport capture needs a GUI, so only its argument marshaling is asserted here;
real pixels are covered by the manual M0 loop test inside Maya.
"""

import math
import os

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

    def test_every_kind_builds_the_face_count_the_budget_predicted(self):
        # #669: the face projection is what the 1M-face ceiling and assemble's
        # 4M-face budget are spent against, and it was WRONG for cylinder and
        # cone for as long as it existed - it charged a fan of triangles for
        # each end cap where Maya closes one with a single n-gon (22 faces
        # predicted as 60). It survived because the only real-Maya face
        # assertions covered the platonic solids, prism and pyramid. This
        # covers every kind, so the next drift fails here instead of quietly
        # inflating a budget.
        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        for kind in modeling.PRIMITIVE_KINDS:
            for divisions in (1, 2, 3):
                built = modeling.create_primitive({
                    "kind": kind, "divisions": divisions,
                    "name": "fc_%s_%d" % (kind, divisions),
                })
                assert cmds.polyEvaluate(built["name"], face=True) == (
                    modeling.projected_faces(kind, divisions)
                ), (kind, divisions)
                # and the result reports what it built, not what was asked for
                assert built["faces"] == modeling.projected_faces(kind, divisions)
                assert built["subdivisions"] == list(
                    modeling.axes_for_divisions(kind, divisions)
                )

    def test_per_axis_subdivisions_reach_maya_as_asked(self):
        # The #669 fix itself: rows ALONG a cylinder without paying for the
        # circumference. Both meshes carry 16 rows; the coupled one costs 26x.
        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        free = modeling.create_primitive({
            "kind": "cylinder", "name": "limb_free", "subdivisions": [12, 16],
        })
        assert cmds.polyEvaluate(free["name"], face=True) == 194
        assert free["subdivisions"] == [12, 16]

        coupled = modeling.create_primitive({
            "kind": "cylinder", "name": "limb_coupled", "divisions": 16,
        })
        assert cmds.polyEvaluate(coupled["name"], face=True) == 5122

        # every other multi-axis kind spends its axes independently too
        for kind, axes, expected in (
            ("cube", [4, 1, 1], 18),
            ("plane", [8, 2], 16),
            ("cone", [12, 6], 73),
            ("torus", [12, 6], 72),
            ("sphere", [12, 6], 72),
            ("prism", [6], 20),
            ("pyramid", [6], 25),
        ):
            built = modeling.create_primitive({
                "kind": kind, "name": "ax_%s" % kind, "subdivisions": axes,
            })
            assert cmds.polyEvaluate(built["name"], face=True) == expected, kind
            assert modeling.faces_for(kind, tuple(axes)) == expected, kind

    def test_maya_silently_substitutes_its_default_below_the_minimum(self):
        # The measurement the minimums rest on, kept live: asking polyCylinder
        # for 2 sides does not clamp to 3 and does not raise - Maya builds its
        # own default of 20. If a future Maya starts refusing (or clamping)
        # instead, this fails and the refusal in resolve_subdivisions can be
        # re-derived rather than trusted.
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import modeling

        raw = cmds.polyCylinder(
            name="silent_default", constructionHistory=False,
            radius=0.5, height=1.0, subdivisionsAxis=2, subdivisionsHeight=1,
        )[0]
        assert cmds.polyEvaluate(raw, face=True) == 22  # 20 sides + 2 caps

        with pytest.raises(HandlerError) as exc:
            modeling.create_primitive({
                "kind": "cylinder", "name": "refused", "subdivisions": [2, 1],
            })
        assert "around" in str(exc.value)
        assert not cmds.objExists("refused")

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


def _build_half_cube_on_plane(cmds, name, border_offset=0.0):
    """Cube of width/height/depth 2 with its +X cap face deleted, leaving an
    open border loop sitting on the mirror plane (x=0) - mirrors
    evals/cage_probe_769.py's build_half_cube exactly (seam_x=0.0 case).
    border_offset shifts the open border's OWN vertices (component-space,
    not the transform) further along +X, simulating a half-shell authored
    slightly off the intended mirror plane."""
    c = cmds.polyCube(name=name, width=2, height=2, depth=2, constructionHistory=False)
    mesh = (cmds.ls(c[0], long=True) or [c[0]])[0]
    cmds.xform(mesh, translation=(-1, 0, 0), worldSpace=True)
    cmds.makeIdentity(mesh, apply=True, translate=True, rotate=True, scale=True)
    nfaces = cmds.polyEvaluate(mesh, face=True)
    target = None
    for i in range(nfaces):
        vs = cmds.ls(
            cmds.polyListComponentConversion(mesh + ".f[%d]" % i, toVertex=True),
            flatten=True,
        )
        if all(abs(cmds.pointPosition(v, world=True)[0]) < 1e-6 for v in vs):
            target = i
            break
    cmds.delete(mesh + ".f[%d]" % target)
    if border_offset:
        for v in cmds.ls(mesh + ".vtx[*]", flatten=True):
            if abs(cmds.pointPosition(v, world=True)[0]) < 1e-6:
                cmds.xform(
                    v, translation=(border_offset, 0, 0), worldSpace=True,
                    relative=True,
                )
    return mesh


class TestCageOpsInMaya:
    """The four ops built for #769's subdivision-cage authoring: real-Maya
    topology counted against evals/cage_probe_769.py's measured arithmetic
    (task-1-report.md), never only the handler's own self-report - every
    test re-queries cmds independently of op_results."""

    def test_insert_loop_adds_one_ring_at_position(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import sculpt

        # Matches the probe's fresh_cyl(): radius=1, height=4,
        # subdivisionsAxis=20, subdivisionsHeight=1 - edge 40 is a lateral
        # edge spanning the full Y range [-2, 2].
        cmds.polyCylinder(
            name="loop_cyl", radius=1, height=4, subdivisionsAxis=20,
            subdivisionsHeight=1, constructionHistory=False,
        )
        mesh = "|loop_cyl"
        edges_before = cmds.polyEvaluate(mesh, edge=True)
        faces_before = cmds.polyEvaluate(mesh, face=True)
        verts_before = set(cmds.ls(mesh + ".vtx[*]", flatten=True))

        result = sculpt.sculpt_ops(
            {"mesh": mesh,
             "ops": [{"op": "insert_loop", "edge": "e[40]", "position": 0.25}]}
        )
        op_result = result["op_results"][0]
        assert op_result["op"] == "insert_loop"
        assert op_result["loops_inserted"] == 1
        # probe: N_AROUND=20 -> +N verts (not itself in op_results), +2N
        # edges, +N faces per loop.
        assert op_result["edges_after"] - op_result["edges_before"] == 40
        assert op_result["faces_after"] - op_result["faces_before"] == 20

        # independent cmds re-query, not just the self-report
        assert cmds.polyEvaluate(mesh, edge=True) - edges_before == 40
        assert cmds.polyEvaluate(mesh, face=True) - faces_before == 20
        new_verts = set(cmds.ls(mesh + ".vtx[*]", flatten=True)) - verts_before
        assert len(new_verts) == 20
        # position=0.25 along the edge's own Y span [-2, 2] -> Y = -1.0
        # (probe: splitring_weight_0.25_measured_fraction_of_edge: 0.25)
        ys = {round(cmds.pointPosition(v, world=True)[1], 4) for v in new_verts}
        assert ys == {-1.0}

    def test_extrude_edges_yields_predicted_faces(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import sculpt

        # Matches the probe's fresh_plane(): width=4, height=1,
        # subdivisionsWidth=4, subdivisionsHeight=1 - edges 0,1,2 are
        # boundary edges (probe: plane_boundary_edge_indices includes 0,1,2).
        cmds.polyPlane(
            name="extrude_plane", width=4, height=1, subdivisionsWidth=4,
            subdivisionsHeight=1, constructionHistory=False,
        )
        mesh = "|extrude_plane"
        faces_before = cmds.polyEvaluate(mesh, face=True)
        verts_before = set(cmds.ls(mesh + ".vtx[*]", flatten=True))

        result = sculpt.sculpt_ops(
            {"mesh": mesh,
             "ops": [{"op": "extrude_edges", "edges": ["e[0]", "e[1]", "e[2]"],
                      "translate": [0, 2, 0], "divisions": 2}]}
        )
        op_result = result["op_results"][0]
        # probe: extrude_edges3_div2_face_delta == 6 (== 3 edges * 2 divisions)
        assert op_result["new_faces"] == 6
        assert op_result["faces_after"] - op_result["faces_before"] == 6

        # independent cmds re-query
        assert cmds.polyEvaluate(mesh, face=True) - faces_before == 6
        new_verts = set(cmds.ls(mesh + ".vtx[*]", flatten=True)) - verts_before
        ys = [cmds.pointPosition(v, world=True)[1] for v in new_verts]
        # translate is a literal world-space offset (probe:
        # extrude_translate_is_world_offset_new_vertex_Ys == [2.0, 2.0]) - the
        # farthest new border reaches the full requested offset.
        assert max(ys) == pytest.approx(2.0)

    def test_mirror_topology_merges_to_one_shell(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import sculpt

        mesh = _build_half_cube_on_plane(cmds, "mc_merge")
        verts_before = cmds.polyEvaluate(mesh, vertex=True)
        assert verts_before == 8  # probe: half_cube_pre_shells_verts_faces

        result = sculpt.sculpt_ops(
            {"mesh": mesh, "ops": [{"op": "mirror_topology", "axis": "x"}]}
        )
        op_result = result["op_results"][0]
        assert op_result["shells"] == 1
        # probe: mergeMode_1_on_plane_shells_verts == (1, 12) from 8 verts ->
        # 4 border verts merge (2*8-12=4).
        assert op_result["merged_vertices"] == 4

        # independent cmds re-query
        assert cmds.polyEvaluate(mesh, shell=True) == 1
        verts_after = cmds.polyEvaluate(mesh, vertex=True)
        assert verts_after == 12
        assert verts_after == 2 * verts_before - 4
        bbox = cmds.exactWorldBoundingBox(mesh)
        # probe: mirror_axis0_shells_verts_bbox closes the box to [-2,2] on X
        assert bbox[0] == pytest.approx(-2.0)
        assert bbox[3] == pytest.approx(2.0)

    def test_mirror_off_plane_refuses_with_measured_gap(self):
        import re

        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import sculpt

        # Default merge_threshold (0.001) can never bridge a deliberate
        # 0.1-unit gap (probe's mtt1_offset0.1_threshold0.001 cell: 2 shells,
        # unmerged) - refuses instead of silently leaving two shells.
        mesh = _build_half_cube_on_plane(cmds, "mc_refuse", border_offset=0.1)
        with pytest.raises(HandlerError) as exc:
            sculpt.sculpt_ops(
                {"mesh": mesh, "ops": [{"op": "mirror_topology", "axis": "x"}]}
            )
        # Pin the specific measured-gap number in _op_mirror_topology's own
        # message ("...gap before the op: %.6g, merge_threshold was..."),
        # not just any number in the (wrapped) exception text - a bare
        # any(n >= 0.09 for n in numbers) over every number in the string
        # would also pass on the unrelated shell count (2 >= 0.09) even if a
        # future edit dropped pre_gap from the message entirely.
        m = re.search(r"gap before the op: ([\d.eE+-]+)", str(exc.value))
        assert m is not None, str(exc.value)
        assert float(m.group(1)) == pytest.approx(0.1, abs=0.01)
        # the mesh must be untouched by the refused op path's own claim - Maya
        # actually already applied polyMirrorFace before the shell check, so
        # this asserts the refusal fires on the same live result, not a stale
        # pre-op state.
        assert cmds.polyEvaluate(mesh, shell=True) == 2

        # allow_unmerged=True keeps the unmerged result instead of refusing.
        mesh2 = _build_half_cube_on_plane(cmds, "mc_allow", border_offset=0.1)
        result = sculpt.sculpt_ops(
            {"mesh": mesh2,
             "ops": [{"op": "mirror_topology", "axis": "x",
                      "allow_unmerged": True}]}
        )
        op_result = result["op_results"][0]
        assert op_result["shells"] == 2
        assert cmds.polyEvaluate(mesh2, shell=True) == 2

    def test_split_cuts_predicted_topology(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import sculpt

        # Matches the probe's quad plane: width=2, height=2,
        # subdivisionsWidth=1, subdivisionsHeight=1.
        cmds.polyPlane(
            name="split_quad", width=2, height=2, subdivisionsWidth=1,
            subdivisionsHeight=1, constructionHistory=False,
        )
        mesh = "|split_quad"
        faces_before = cmds.polyEvaluate(mesh, face=True)
        edges_before = cmds.polyEvaluate(mesh, edge=True)
        verts_before = cmds.polyEvaluate(mesh, vertex=True)

        result = sculpt.sculpt_ops(
            {"mesh": mesh,
             "ops": [{"op": "split",
                      "points": [["e[0]", 0.5], ["e[2]", 0.5]]}]}
        )
        op_result = result["op_results"][0]
        # probe: polysplit_two_midpoints_delta_verts_edges_faces == (2, 3, 1)
        assert op_result["faces_after"] - op_result["faces_before"] == 1
        assert op_result["edges_after"] - op_result["edges_before"] == 3

        # independent cmds re-query
        assert cmds.polyEvaluate(mesh, face=True) - faces_before == 1
        assert cmds.polyEvaluate(mesh, edge=True) - edges_before == 3
        assert cmds.polyEvaluate(mesh, vertex=True) - verts_before == 2


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

    def test_joints_are_created_without_segment_scale_compensate(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        # Maya's default (on) exports as FBX InheritType 2, which Unity turns
        # into 100x scale compounding per joint level under the metres
        # declaration (#703). This toolset never scales joints - the export
        # gate refuses scaled joints unconditionally - so SSC buys nothing in
        # Maya, and off at creation means the scene matches the artifact.
        out = rigging.create_skeleton({
            "chain": [[0, 0, 0], [0, 2, 0], [0, 4, 0]], "chain_prefix": "ssc"})
        for j in out["joints"]:
            assert not cmds.getAttr(
                j["name"] + ".segmentScaleCompensate"), j["name"]


class TestCreateSkeletonPositionsInMaya:
    """#719: the #713 golem asked for jnt_torso at (0, 2.05, 0) with
    orient [0,0,0] and measured (0.33, 1.72, 0) - Maya lays a child's
    translate in its PARENT's frame, so overwriting the parent's jointOrient
    swings the child through world space. Silent wrong-position is the bug;
    the requested world positions are the contract.
    """

    def test_explicit_orient_keeps_the_requested_positions(self):
        from maya_plugin.handlers import rigging

        out = rigging.create_skeleton({"joints": [
            {"name": "jnt_root", "position": [0, 0, 0], "orient": [0, 0, 0]},
            {"name": "jnt_torso", "position": [0, 2.05, 0],
             "parent": "jnt_root", "orient": [0, 0, 0]},
            {"name": "jnt_head", "position": [0, 3.4, 0],
             "parent": "jnt_torso", "orient": [0, 0, 0]},
        ]})
        by_name = {j["name"].rsplit("|", 1)[-1]: j for j in out["joints"]}
        assert by_name["jnt_torso"]["position"] == pytest.approx(
            [0, 2.05, 0], abs=1e-6)
        assert by_name["jnt_head"]["position"] == pytest.approx(
            [0, 3.4, 0], abs=1e-6)
        assert by_name["jnt_torso"]["orient"] == pytest.approx(
            [0, 0, 0], abs=1e-6)

    def test_world_aligned_joints_share_the_world_axes(self):
        """The point of orient [0,0,0] on every joint: local X means the same
        axis on every bone, which is what an all-hinges-X rig wants."""
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        out = rigging.create_skeleton({"joints": [
            {"name": "w_root", "position": [0, 0, 0], "orient": [0, 0, 0]},
            {"name": "w_a", "position": [0.4, 1.0, 0], "parent": "w_root",
             "orient": [0, 0, 0]},
            {"name": "w_b", "position": [0.9, 1.8, 0], "parent": "w_a",
             "orient": [0, 0, 0]},
        ]})
        for j in out["joints"]:
            m = cmds.xform(j["name"], query=True, worldSpace=True, matrix=True)
            assert m[:3] == pytest.approx([1, 0, 0], abs=1e-6), j["name"]
            assert m[4:7] == pytest.approx([0, 1, 0], abs=1e-6), j["name"]

    def test_auto_orient_still_places_and_orients_as_before(self):
        """The re-assertion must not disturb the deforming-rig default."""
        from maya_plugin.handlers import rigging

        out = rigging.create_skeleton({
            "chain": [[0, 0, 0], [0, 2, 0], [0, 4, 0]], "chain_prefix": "ar"})
        assert [tuple(round(v, 6) for v in j["position"])
                for j in out["joints"]] == [(0, 0, 0), (0, 2, 0), (0, 4, 0)]
        assert out["joints"][0]["orient"][2] == pytest.approx(90.0, abs=1e-4)
        assert out["joints"][2]["orient"] == pytest.approx([0.0, 0.0, 0.0])


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

    def test_per_mesh_reports_each_bound_mesh_alone(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        mesh, skel = self._bound_serpent(cmds, rigging, name="pm_tube")
        mid = skel["joints"][1]["name"]
        out = rigging.pose_skeleton({"root": skel["root"],
                                     "rotations": {mid: [0, 0, 45]}})
        assert len(out["per_mesh"]) == 1
        assert out["per_mesh"][0]["mesh"] == mesh
        assert out["per_mesh"][0]["max_displacement"] == pytest.approx(
            out["max_displacement"])


class TestWeightReportInMaya:
    def test_report_agrees_with_bind_and_is_read_only(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        mesh = _serpent_cylinder(cmds, name="wr_tube")
        skel = rigging.create_skeleton({
            "chain": [[0, 0, 0], [0, 2, 0], [0, 4, 0]], "chain_prefix": "wr_j"})
        bind = rigging.bind_skin({"mesh": mesh, "root": skel["root"]})
        out = rigging.weight_report({"mesh": mesh})
        assert out["skin_cluster"] == bind["skin_cluster"]
        assert out["unweighted_vertices"] == 0
        assert out["max_influences"] == 4
        assert out["max_weight_sum_error"] < 1e-6   # in-scene sums are exact
        assert sum(b["vertices"] for b in out["histogram"]) == out["vertices"]
        assert [p["joint"] for p in out["per_joint"]] == bind["influences"]

    def test_report_on_an_unbound_mesh_refuses(self):
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import rigging

        mesh = _serpent_cylinder(cmds, name="wr_bare")
        with pytest.raises(HandlerError, match="not bound"):
            rigging.weight_report({"mesh": mesh})


class TestMirrorWeightsInMaya:
    def _bilateral(self, cmds, rigging):
        """A cube spanning x in [-1, 1] bound to a 3-joint T: center root,
        one joint per side."""
        mesh = cmds.polyCube(width=2, height=1, depth=1,
                             subdivisionsX=8, name="mir_box")[0]
        mesh = cmds.ls(mesh, long=True)[0]
        skel = rigging.create_skeleton({"joints": [
            {"name": "mir_root", "position": [0, 0.5, 0]},
            {"name": "mir_L", "position": [0.7, 0.5, 0], "parent": "mir_root"},
            {"name": "mir_R", "position": [-0.7, 0.5, 0], "parent": "mir_root"},
        ]})
        rigging.bind_skin({"mesh": mesh, "root": skel["root"]})
        return mesh, skel

    def test_hand_authored_left_weights_arrive_on_the_right(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        mesh, skel = self._bilateral(cmds, rigging)
        # Deliberately skew ONE +X vertex fully to the LEFT joint.
        sc = rigging.weight_report({"mesh": mesh})["skin_cluster"]
        shape = cmds.listRelatives(mesh, shapes=True, fullPath=True)[0]
        target = None
        for i in range(cmds.polyEvaluate(mesh, vertex=True)):
            pos = cmds.xform("%s.vtx[%d]" % (mesh, i), query=True,
                             worldSpace=True, translation=True)
            if pos[0] > 0.9:
                target = i
                break
        cmds.skinPercent(sc, "%s.vtx[%d]" % (mesh, target),
                         transformValue=[("mir_L", 1.0)])
        out = rigging.mirror_weights({"mesh": mesh, "axis": "x"})
        assert out["mirrored_vertices"] > 0
        assert out["changed_vertices"] > 0
        assert out["unweighted_vertices"] == 0
        # The mirrored twin of `target` is fully owned by mir_R now.
        pos = cmds.xform("%s.vtx[%d]" % (mesh, target), query=True,
                         worldSpace=True, translation=True)
        for i in range(cmds.polyEvaluate(mesh, vertex=True)):
            q = cmds.xform("%s.vtx[%d]" % (mesh, i), query=True,
                           worldSpace=True, translation=True)
            if (abs(q[0] + pos[0]) < 1e-3 and abs(q[1] - pos[1]) < 1e-3
                    and abs(q[2] - pos[2]) < 1e-3):
                w = cmds.skinPercent(sc, "%s.vtx[%d]" % (mesh, i),
                                     query=True, value=True)
                assert max(w) == pytest.approx(1.0, abs=1e-6)
                infs = cmds.skinCluster(sc, query=True, influence=True)
                assert infs[w.index(max(w))].split("|")[-1] == "mir_R"
                break
        else:
            pytest.fail("no mirrored twin found for the authored vertex")

    def test_mirror_is_idempotent(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        mesh, skel = self._bilateral(cmds, rigging)
        rigging.mirror_weights({"mesh": mesh})
        out = rigging.mirror_weights({"mesh": mesh})
        assert out["changed_vertices"] == 0


class TestSmoothWeightsInMaya:
    def test_smoothing_a_hard_edge_reduces_the_step(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        mesh = _serpent_cylinder(cmds, name="sm_tube")
        skel = rigging.create_skeleton({
            "chain": [[0, 0, 0], [0, 2, 0], [0, 4, 0]], "chain_prefix": "sm_j"})
        bind = rigging.bind_skin({"mesh": mesh, "root": skel["root"]})
        sc = bind["skin_cluster"]
        # Manufacture a stair-step: every vertex below y=2 fully to joint 1,
        # above fully to joint 2.
        n = cmds.polyEvaluate(mesh, vertex=True)
        for i in range(n):
            y = cmds.xform("%s.vtx[%d]" % (mesh, i), query=True,
                           worldSpace=True, translation=True)[1]
            owner = "sm_j_01" if y < 2.0 else "sm_j_02"
            cmds.skinPercent(sc, "%s.vtx[%d]" % (mesh, i),
                             transformValue=[(owner, 1.0)])
        out = rigging.smooth_weights({"mesh": mesh, "iterations": 2})
        assert out["changed_vertices"] > 0
        assert out["unweighted_vertices"] == 0
        assert out["max_influences_exceeded"] == 0
        # Some vertex near the seam is now genuinely shared.
        report = rigging.weight_report({"mesh": mesh})
        shared = [b for b in report["histogram"] if b["influences"] >= 2]
        assert shared and sum(b["vertices"] for b in shared) > 0

    def test_joint_filter_leaves_the_far_end_alone(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging, sculpt

        mesh = _serpent_cylinder(cmds, name="sm_tube2")
        skel = rigging.create_skeleton({
            "chain": [[0, 0, 0], [0, 2, 0], [0, 4, 0]], "chain_prefix": "sn_j"})
        rigging.bind_skin({"mesh": mesh, "root": skel["root"]})
        before = rigging.weight_report({"mesh": mesh})
        out = rigging.smooth_weights({"mesh": mesh, "joints": ["sn_j_03"],
                                      "iterations": 1})
        assert out["smoothed_vertices"] < before["vertices"]


class TestSetRegionWeightsInMaya:
    def test_radius_region_hands_vertices_to_the_joint(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        mesh = _serpent_cylinder(cmds, name="rg_tube")
        skel = rigging.create_skeleton({
            "chain": [[0, 0, 0], [0, 2, 0], [0, 4, 0]], "chain_prefix": "rg_j"})
        rigging.bind_skin({"mesh": mesh, "root": skel["root"]})
        out = rigging.set_region_weights({
            "mesh": mesh, "joint": "rg_j_03", "within_radius_of": [0, 4, 0],
            "radius": 1.0, "weight": 1.0, "falloff": "none"})
        assert out["vertices_in_region"] > 0
        assert out["changed_vertices"] > 0
        assert out["unweighted_vertices"] == 0
        sc = out["skin_cluster"]
        # The vertex nearest the tip is fully the NAMED tip joint's now -
        # not just some influence.
        n = cmds.polyEvaluate(mesh, vertex=True)
        best, best_d = None, 1e9
        for i in range(n):
            p = cmds.xform("%s.vtx[%d]" % (mesh, i), query=True,
                           worldSpace=True, translation=True)
            d = (p[0] ** 2 + (p[1] - 4.0) ** 2 + p[2] ** 2) ** 0.5
            if d < best_d:
                best, best_d = i, d
        w = cmds.skinPercent(sc, "%s.vtx[%d]" % (mesh, best),
                             query=True, transform="rg_j_03")
        assert w == pytest.approx(1.0, abs=1e-6)

    def test_faces_region_converts_to_vertices(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        mesh = _serpent_cylinder(cmds, name="rg_tube2")
        skel = rigging.create_skeleton({
            "chain": [[0, 0, 0], [0, 2, 0], [0, 4, 0]], "chain_prefix": "rf_j"})
        rigging.bind_skin({"mesh": mesh, "root": skel["root"]})
        out = rigging.set_region_weights({
            "mesh": mesh, "joint": "rf_j_01", "faces": [0, 1], "weight": 1.0})
        assert out["vertices_in_region"] >= 4
        # A vertex the face->vertex conversion actually picked up is now
        # fully the named joint's - not just "some int came back" (a freshly
        # bound cylinder base may already fully own those verts, so this does
        # NOT assert changed_vertices > 0, which would flake).
        sc = out["skin_cluster"]
        verts = cmds.ls(cmds.polyListComponentConversion(
            "%s.f[0]" % mesh, fromFace=True, toVertex=True), flatten=True)
        vtx = verts[0]
        w = cmds.skinPercent(sc, vtx, query=True, transform="rf_j_01")
        assert w == pytest.approx(1.0, abs=1e-6)


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


class TestPoseIkInMaya:
    LEG = [
        {"name": "ik_pelvis", "position": [0.0, 1.00, 0.0]},
        {"name": "ik_hip", "position": [0.10, 0.95, 0.0], "parent": "ik_pelvis"},
        {"name": "ik_knee", "position": [0.10, 0.50, 0.0], "parent": "ik_hip"},
        {"name": "ik_ankle", "position": [0.10, 0.08, 0.0], "parent": "ik_knee"},
    ]
    TARGET = [0.10, 0.60, 0.20]       # forward+up, well inside the 0.87 reach
    POLE = [0.10, 0.50, 0.50]         # knee faces world +Z

    def _skeleton(self):
        from maya_plugin.handlers import rigging

        return rigging.create_skeleton({"joints": self.LEG})["root"]

    def test_straight_leg_reaches_the_target_with_a_pole(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        root = self._skeleton()
        # regression: capture preferredAngle before IK solve to verify restore
        interior_joint = "|ik_pelvis|ik_hip|ik_knee"
        before_pa = cmds.getAttr(interior_joint + ".preferredAngle")[0]

        out = rigging.pose_ik({"root": root, "joint": "ik_ankle",
                               "target": self.TARGET, "pole": self.POLE})
        # the bind-pose leg is perfectly straight - this asserts the
        # pre-bend actually unlocked the RP solver
        assert out["residual"] < 1e-3, out
        for axis in range(3):
            assert abs(out["achieved_position"][axis]
                       - self.TARGET[axis]) < 2e-3
        # the knee folded toward the pole, not away from it
        knee = cmds.xform(out["chain"][1], query=True, worldSpace=True,
                          translation=True)
        assert knee[2] > 0.01, "knee went to z=%.4f, away from the pole" % knee[2]
        # no persistent IK state, the spec's core promise
        assert not cmds.ls(type="ikHandle")
        assert not cmds.ls(type="ikEffector")
        assert not cmds.ls(type="poleVectorConstraint")
        assert not cmds.ls("*_pole", type="transform")
        # regression: preferredAngle must restore - no persistent IK state includes it
        after_pa = cmds.getAttr(interior_joint + ".preferredAngle")[0]
        for axis in range(3):
            assert abs(after_pa[axis] - before_pa[axis]) < 1e-9, (
                "preferredAngle did not restore: before %r, after %r"
                % (before_pa, after_pa))

    def test_bake_is_the_phase1_pose_currency(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        root = self._skeleton()
        out = rigging.pose_ik({"root": root, "joint": "ik_ankle",
                               "target": self.TARGET, "pole": self.POLE})
        rigging.reset_pose({"root": root})
        # re-apply the returned rotations as plain FK: same achieved position
        rigging.pose_skeleton({"root": root, "rotations": out["rotations"]})
        again = cmds.xform("|ik_pelvis|ik_hip|ik_knee|ik_ankle", query=True,
                           worldSpace=True, translation=True)
        for axis in range(3):
            assert abs(again[axis] - out["achieved_position"][axis]) < 1e-4

    def test_unreachable_target_reports_the_geometric_miss(self):
        from maya_plugin.handlers import rigmath, rigging

        root = self._skeleton()
        target = [0.10, 0.95 - 2.0, 0.0]   # 2.0 below the hip, reach is 0.87
        out = rigging.pose_ik({"root": root, "joint": "ik_ankle",
                               "target": target, "pole": self.POLE})
        expected_miss = 2.0 - rigmath.chain_reach(
            [[0.10, 0.95, 0.0], [0.10, 0.50, 0.0], [0.10, 0.08, 0.0]])
        assert abs(out["residual"] - expected_miss) < 0.05
        assert any("reaches only" in w for w in out["warnings"])

    def test_keep_false_measures_then_restores(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        root = self._skeleton()
        ankle = "|ik_pelvis|ik_hip|ik_knee|ik_ankle"
        before = cmds.xform(ankle, query=True, worldSpace=True,
                            translation=True)
        out = rigging.pose_ik({"root": root, "joint": "ik_ankle",
                               "target": self.TARGET, "pole": self.POLE,
                               "keep": False})
        assert out["kept"] is False
        assert out["residual"] < 1e-3          # the solve itself was measured
        after = cmds.xform(ankle, query=True, worldSpace=True,
                           translation=True)
        for axis in range(3):
            assert abs(after[axis] - before[axis]) < 1e-6

    def test_deforms_a_bound_mesh_and_measures_it(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        root = self._skeleton()
        cmds.polyCylinder(name="ik_leg_mesh", radius=0.06, height=0.9,
                          subdivisionsHeight=8)
        cmds.setAttr("|ik_leg_mesh.translate", 0.10, 0.5, 0.0)
        cmds.makeIdentity("|ik_leg_mesh", apply=True, translate=True)
        rigging.bind_skin({"mesh": "|ik_leg_mesh", "root": root})
        out = rigging.pose_ik({"root": root, "joint": "ik_ankle",
                               "target": self.TARGET, "pole": self.POLE})
        assert out["max_displacement"] > 0.05
        assert out["per_mesh"] and out["per_mesh"][0]["displaced_vertices"] > 0

    # regression (#671 final review): every other test in this class solves a
    # 3-joint chain (one interior joint). `start` exists precisely so a
    # caller can reach past the default two-joints-up and solve a longer
    # run - a serpent spine segment - so one test has to actually build a
    # chain with more than one interior joint and pass `start` explicitly.
    SPINE = [
        {"name": "sp_root", "position": [0.10, 0.95, 0.0]},
        {"name": "sp_1", "position": [0.10, 0.80, 0.0], "parent": "sp_root"},
        {"name": "sp_2", "position": [0.10, 0.65, 0.0], "parent": "sp_1"},
        {"name": "sp_3", "position": [0.10, 0.50, 0.0], "parent": "sp_2"},
        {"name": "sp_4", "position": [0.10, 0.35, 0.0], "parent": "sp_3"},
        {"name": "sp_5", "position": [0.10, 0.20, 0.0], "parent": "sp_4"},
    ]
    SPINE_TARGET = [0.10, 0.50, 0.35]   # reachable: 0.461 of a 0.60 reach
    SPINE_POLE = [0.10, 0.50, 1.0]      # spine folds toward world +Z

    def test_long_chain_with_explicit_start_solves_past_two_joints_up(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        spine_root = rigging.create_skeleton({"joints": self.SPINE})["root"]
        out = rigging.pose_ik({"root": spine_root, "start": "sp_1",
                               "joint": "sp_5", "target": self.SPINE_TARGET,
                               "pole": self.SPINE_POLE})
        assert out["chain"] == [
            "|sp_root|sp_1", "|sp_root|sp_1|sp_2", "|sp_root|sp_1|sp_2|sp_3",
            "|sp_root|sp_1|sp_2|sp_3|sp_4",
            "|sp_root|sp_1|sp_2|sp_3|sp_4|sp_5"], out["chain"]
        assert out["residual"] < 1e-3, out
        for axis in range(3):
            assert abs(out["achieved_position"][axis]
                       - self.SPINE_TARGET[axis]) < 2e-3
        # no persistent IK state, same purity bar as the short-chain solve
        assert not cmds.ls(type="ikHandle")
        assert not cmds.ls(type="ikEffector")
        assert not cmds.ls(type="poleVectorConstraint")
        assert not cmds.ls("*_pole", type="transform")


class TestAuthorPhysicsInMaya:
    def _cube(self, name, size=1.0, translate=(0.0, 0.0, 0.0)):
        import maya.cmds as cmds

        node = cmds.polyCube(name=name, width=size, height=size,
                             depth=size)[0]
        cmds.xform(node, worldSpace=True, translation=list(translate))
        return cmds.ls(node, long=True)[0]

    def test_cube_volume_com_mass_measured(self):
        from maya_plugin.handlers import physics

        self._cube("phys_core", translate=(0.0, 1.0, 0.0))
        out = physics.author_physics({"chunks": ["phys_core"]})
        body = out["bodies"][0]
        assert body["volume"] == pytest.approx(1.0, rel=1e-6)
        assert body["mass"] == pytest.approx(1.0, rel=1e-6)
        assert body["com"] == pytest.approx([0.0, 1.0, 0.0], abs=1e-6)
        assert body["watertight"] is True
        assert body["collider"]["kind"] == "box"
        assert sorted(body["collider"]["size"]) == pytest.approx(
            [1.0, 1.0, 1.0], abs=1e-6)
        assert body["collider"]["max_escape"] == pytest.approx(0.0, abs=1e-9)
        assert body["collider"]["volume_ratio"] == pytest.approx(1.0, rel=1e-6)

    def test_volume_matches_the_array_reader(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import array, physics

        cmds.polyCylinder(name="phys_xcheck", radius=0.3, height=2.0,
                          subdivisionsAxis=20)
        out = physics.author_physics({"chunks": ["phys_xcheck"]})
        signed = array._mesh_signed_volume(cmds, "|phys_xcheck")
        assert out["bodies"][0]["signed_volume"] == pytest.approx(
            signed, rel=1e-9)

    def test_sphere_is_a_sphere(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import physics

        cmds.polySphere(name="phys_ball", radius=0.5,
                        subdivisionsX=12, subdivisionsY=12)
        out = physics.author_physics({"chunks": ["phys_ball"]})
        col = out["bodies"][0]["collider"]
        assert col["kind"] == "sphere", col
        # poles sit at exactly the nominal radius
        assert col["radius"] == pytest.approx(0.5, abs=1e-6)
        assert col["max_escape"] == pytest.approx(0.0, abs=1e-9)
        # the mesh is inscribed in the sphere: ratio slightly above 1
        assert 1.0 < col["volume_ratio"] < 1.2

    def test_cylinder_is_a_capsule_with_measured_escape(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import physics

        cmds.polyCylinder(name="phys_limb", radius=0.3, height=2.0,
                          subdivisionsAxis=20)
        out = physics.author_physics({"chunks": ["phys_limb"]})
        col = out["bodies"][0]["collider"]
        assert col["kind"] == "capsule", col
        assert col["radius"] == pytest.approx(0.3, abs=1e-6)
        assert col["height"] == pytest.approx(1.4, abs=0.01)
        assert abs(col["axis"][1]) == pytest.approx(1.0, abs=1e-6)
        # rim corners poke past the caps: sqrt(r^2+r^2) - r = 0.124
        assert 0.05 < col["max_escape"] < 0.2

    def test_rotated_cylinder_recovers_its_frame(self):
        import math

        import maya.cmds as cmds

        from maya_plugin.handlers import physics

        node = cmds.polyCylinder(name="phys_tilt", radius=0.3, height=2.0,
                                 subdivisionsAxis=20)[0]
        cmds.setAttr(node + ".rotateZ", 30)
        out = physics.author_physics({"chunks": ["phys_tilt"]})
        col = out["bodies"][0]["collider"]
        assert col["kind"] == "capsule"
        # +Y rotated 30 deg about Z lands on (-sin30, cos30, 0)
        expected = [-math.sin(math.radians(30)),
                    math.cos(math.radians(30)), 0.0]
        dot = sum(a * b for a, b in zip(col["axis"], expected))
        assert abs(dot) == pytest.approx(1.0, abs=1e-6)

    def test_open_plane_warns_and_reports_boundary_edges(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import physics

        cmds.polyPlane(name="phys_sheet", width=1, height=1,
                       subdivisionsX=2, subdivisionsY=2)
        out = physics.author_physics({"chunks": ["phys_sheet"]})
        body = out["bodies"][0]
        assert body["watertight"] is False
        assert body["open_edges"] > 0
        assert any("boundary edge" in w for w in out["warnings"])
        assert any("near-zero volume" in w for w in out["warnings"])

    def test_dag_parents_and_default_joints_on_a_real_hierarchy(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import physics

        root = self._cube("phys_pelvis", translate=(0.0, 1.0, 0.0))
        child = self._cube("phys_thigh", size=0.5,
                           translate=(0.3, 0.2, 0.0))
        child = cmds.parent(child, root)[0]
        out = physics.author_physics({"root": "phys_pelvis"})
        by = {b["chunk"].split("|")[-1]: b for b in out["bodies"]}
        assert by["phys_thigh"]["parent"] == "|phys_pelvis"
        assert by["phys_pelvis"]["parent"] is None
        assert by["phys_pelvis"]["joint"] is None
        assert by["phys_thigh"]["joint"]["source"] == "default_locked"
        assert any("LOCKED joint" in w for w in out["warnings"])
        # the child's volume is measured in WORLD space under the parent
        assert by["phys_thigh"]["volume"] == pytest.approx(0.125, rel=1e-6)


class TestBlendshapeInMaya:
    def _base_and_target(self, cmds, bump=0.3, axis=(0.0, 1.0, 0.0)):
        base = cmds.polyCube(name="bs_base", width=1, height=1, depth=1)[0]
        target = cmds.duplicate(base, name="bs_target")[0]
        cmds.move(bump * axis[0], bump * axis[1], bump * axis[2],
                  target + ".vtx[0]", relative=True)
        base_long = cmds.ls(base, long=True)[0]
        target_long = cmds.ls(target, long=True)[0]
        return base_long, target_long

    def test_create_measures_the_real_delta_and_consumes(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import blendshape

        base, target = self._base_and_target(cmds, bump=0.3)
        out = blendshape.create_blendshape({
            "mesh": base,
            "targets": [{"name": "puff", "target_mesh": target}]})
        assert out["targets"][0]["max_delta"] == pytest.approx(0.3, abs=1e-6)
        assert out["targets"][0]["vertex_count"] == 8
        assert not cmds.objExists(target)          # consumed
        # deltas survive the consumption: weight 1 still moves the vertex
        weighted = blendshape.set_blendshape_weights(
            {"mesh": base, "weights": {"puff": 1.0}})
        assert weighted["max_displacement"] == pytest.approx(0.3, abs=1e-6)
        assert weighted["weights"] == {"puff": 1.0}

    def test_half_weight_is_half_the_delta(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import blendshape

        base, target = self._base_and_target(cmds, bump=0.4)
        blendshape.create_blendshape({
            "mesh": base,
            "targets": [{"name": "puff", "target_mesh": target}]})
        out = blendshape.set_blendshape_weights(
            {"mesh": base, "weights": {"puff": 0.5}})
        assert out["max_displacement"] == pytest.approx(0.2, abs=1e-6)

    def test_a_translated_duplicate_contributes_no_false_delta(self):
        # Deltas are object-space in the node: a copy moved aside for
        # sculpting clarity is byte-identical as a target (design decision:
        # measured here, relied on by the gate's authoring flow).
        import maya.cmds as cmds

        from maya_plugin.handlers import blendshape

        base, target = self._base_and_target(cmds, bump=0.3)
        cmds.setAttr(target + ".translateX", 5.0)
        out = blendshape.create_blendshape({
            "mesh": base,
            "targets": [{"name": "puff", "target_mesh": target}]})
        assert out["targets"][0]["max_delta"] == pytest.approx(0.3, abs=1e-6)

    def test_topology_mismatch_refused(self):
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import blendshape

        base = cmds.ls(cmds.polyCube(name="bs_base8")[0], long=True)[0]
        ball = cmds.ls(cmds.polySphere(name="bs_ball")[0], long=True)[0]
        with pytest.raises(HandlerError, match="topology does not match"):
            blendshape.create_blendshape({
                "mesh": base,
                "targets": [{"name": "bad", "target_mesh": ball}]})

    def test_front_of_chain_under_a_skin(self):
        """The phase's load-bearing ordering claim, measured two ways.

        The cube is bound, the root rotated 90 about Z, THEN the shape is
        wired (the risky order - frontOfChain has to reach past the
        existing skinCluster). The target's delta is +X in object space;
        front-of-chain means the skin ROTATES it, so at the posed joint the
        vertex must move +Y in world. Wrong order would move it +X.
        """
        import maya.cmds as cmds

        from maya_plugin.handlers import blendshape, rigging, sculpt

        base, target = self._base_and_target(cmds, bump=0.3,
                                             axis=(1.0, 0.0, 0.0))
        # Test-authoring fix (not a Maya divergence): the brief's literal
        # omitted "parent" on the second joint, which resolve_joints
        # correctly refuses as two roots ("a skeleton has exactly one
        # root"). Added parent="bs_j1" to make this the intended 2-joint
        # chain - measured under mayapy.
        skeleton = rigging.create_skeleton({"joints": [
            {"name": "bs_j1", "position": [0.0, 0.0, 0.0]},
            {"name": "bs_j2", "position": [1.0, 0.0, 0.0],
             "parent": "bs_j1"}]})
        rigging.bind_skin({"mesh": base, "root": skeleton["root"]})
        rigging.pose_skeleton({"root": skeleton["root"],
                               "rotations": {"bs_j1": [0, 0, 90]}})

        out = blendshape.create_blendshape({
            "mesh": base,
            "targets": [{"name": "fix", "target_mesh": target}]})
        assert out["targets"][0]["max_delta"] == pytest.approx(0.3, abs=1e-4)

        # structural: the blendShape sits UPSTREAM of the skinCluster
        shape = cmds.listRelatives(base, shapes=True, fullPath=True,
                                   noIntermediate=True)[0]
        history = cmds.listHistory(shape, pruneDagObjects=True)
        sc = cmds.ls(history, type="skinCluster")[0]
        bs = cmds.ls(history, type="blendShape")[0]
        assert history.index(sc) < history.index(bs)

        # behavioral: the object-space +X delta lands as world +Y
        before = sculpt.vertex_positions(cmds, base)
        blendshape.set_blendshape_weights({"mesh": base,
                                           "weights": {"fix": 1.0}})
        after = sculpt.vertex_positions(cmds, base)
        moved = max(range(len(before) // 3),
                    key=lambda i: sum((after[3 * i + k] - before[3 * i + k]) ** 2
                                      for k in range(3)))
        delta = [after[3 * moved + k] - before[3 * moved + k]
                 for k in range(3)]
        assert delta[1] == pytest.approx(0.3, abs=1e-4)   # +Y, rotated
        assert abs(delta[0]) < 1e-4                        # not +X

    def test_additive_create_and_alias_collision(self):
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import blendshape

        base, t1 = self._base_and_target(cmds, bump=0.2)
        first = blendshape.create_blendshape({
            "mesh": base, "targets": [{"name": "a", "target_mesh": t1}]})
        t2 = cmds.ls(cmds.duplicate(base, name="bs_t2")[0], long=True)[0]
        cmds.move(0, 0, 0.1, t2 + ".vtx[1]", relative=True)
        second = blendshape.create_blendshape({
            "mesh": base, "targets": [{"name": "b", "target_mesh": t2}]})
        assert second["blend_shape"] == first["blend_shape"]
        weighted = blendshape.set_blendshape_weights(
            {"mesh": base, "weights": {"a": 1.0, "b": 1.0}})
        assert set(weighted["weights"]) == {"a", "b"}
        t3 = cmds.ls(cmds.duplicate(base, name="bs_t3")[0], long=True)[0]
        with pytest.raises(HandlerError, match="already exists"):
            blendshape.create_blendshape({
                "mesh": base, "targets": [{"name": "a", "target_mesh": t3}]})

    def test_additive_create_after_a_sparse_removal_does_not_clobber(self):
        """A target removed outside this tool (Shape Editor / `blendShape
        -e -rm`) leaves a HOLE in the node's weight multi, not a shrink from
        the end. MEASURED: `cmds.blendShape(edit=True, remove=True,
        target=(...))` refuses once the tool has consumed the original
        target mesh ('Found 0 matches') - the practical removal path here is
        the attribute-level one Shape Editor itself uses,
        `cmds.removeMultiInstance` on both `.w[i]` and
        `.inputTarget[0].inputTargetGroup[i]`. Before the fix, additive
        create used len(existing) (=1, since only "b" is aliased) as the
        next index, landed on b's OCCUPIED index 1, and aliasAttr silently
        renamed "b" to "c" in place - this test measured that clobber live
        (final indices=[1], aliases=["c"], "b" gone) before asserting the
        fixed behavior below."""
        import maya.cmds as cmds

        from maya_plugin.handlers import blendshape

        base, t1 = self._base_and_target(cmds, bump=0.1)
        t2 = cmds.ls(cmds.duplicate(base, name="bs_sparse_t2")[0],
                    long=True)[0]
        cmds.move(0, 0.2, 0, t2 + ".vtx[0]", relative=True)
        first = blendshape.create_blendshape({
            "mesh": base, "targets": [{"name": "a", "target_mesh": t1},
                                      {"name": "b", "target_mesh": t2}]})
        node = first["blend_shape"]
        assert cmds.getAttr(node + ".w", multiIndices=True) == [0, 1]

        # Remove index 0's target at the attribute level (both the weight
        # multi and its inputTarget group), leaving a hole at 0 with "b"
        # still occupying 1 - the sparse state a live artist leaves behind.
        cmds.removeMultiInstance(node + ".w[0]", b=True)
        cmds.removeMultiInstance(node + ".inputTarget[0].inputTargetGroup[0]",
                                 b=True)
        assert cmds.getAttr(node + ".w", multiIndices=True) == [1]
        assert cmds.listAttr(node + ".w", multi=True) == ["b"]

        t3 = cmds.ls(cmds.duplicate(base, name="bs_sparse_t3")[0],
                    long=True)[0]
        cmds.move(0, 0.3, 0, t3 + ".vtx[0]", relative=True)
        second = blendshape.create_blendshape({
            "mesh": base, "targets": [{"name": "c", "target_mesh": t3}]})
        assert second["blend_shape"] == node
        # "b" must survive untouched, at its original index, with its
        # original weight - not clobbered by "c" landing on it.
        assert cmds.listAttr(node + ".w", multi=True) == ["b", "c"]
        assert cmds.getAttr(node + ".w", multiIndices=True) == [1, 2]
        assert cmds.getAttr(node + ".b") == pytest.approx(0.0)
        assert second["targets"][0]["max_delta"] == pytest.approx(
            0.3, abs=1e-6)


class TestBlendshapeExportInMaya:
    def test_shapes_ride_along_and_the_bytes_name_them(self, tmp_path):
        """THE NAMING MEASUREMENT (#691 plan constraint): whatever Maya
        writes as the channel name, shape_facts must clean it to the
        authored alias. If this assertion fails, the fix belongs in
        fbxbytes.shape_facts's name cleaning - record the measured raw
        string in a comment here when adjusting."""
        import maya.cmds as cmds

        from maya_plugin.handlers import blendshape, export, fbxbytes

        base = cmds.ls(cmds.polyCube(name="bs_exp")[0], long=True)[0]
        target = cmds.ls(cmds.duplicate(base, name="bs_exp_t")[0],
                         long=True)[0]
        cmds.move(0, 0.3, 0, target + ".vtx[0]", relative=True)
        blendshape.create_blendshape({
            "mesh": base,
            "targets": [{"name": "puff", "target_mesh": target}]})

        path = str(tmp_path / "shaped.fbx").replace("\\", "/")
        result = export.export_fbx({"path": path, "metres_per_unit": 1.0})
        shapes = result["shapes"]
        # MEASURED: Maya writes the BlendShapeChannel's raw name as
        # "bs_exp_shapes.puff" (blendShape node name + "." + the authored
        # alias) - the deformer-qualified form fbxbytes.shape_facts's
        # docstring already anticipated. No cleaning-logic change was needed;
        # this run is what PROVES the existing .split(".")[-1] handles it.
        assert shapes is not None and shapes["channels"] == 1
        assert shapes["shapes"][0]["name"] == "puff"
        assert shapes["shapes"][0]["points"] > 0
        assert shapes["shapes"][0]["indexes"] == shapes["shapes"][0]["points"]
        # Shape geometries must not inflate mesh facts
        assert result["mesh_count"] == 1
        # an independent read of the bytes agrees with the tool
        assert fbxbytes.shape_facts(fbxbytes.read_fbx(path)) == shapes

    def test_a_shapeless_scene_reports_no_shapes_block(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import export

        cmds.polyCube(name="bs_plain")
        path = str(tmp_path / "plain.fbx").replace("\\", "/")
        result = export.export_fbx({"path": path, "metres_per_unit": 1.0})
        assert result["shapes"] is None
        assert result["mesh_count"] == 1

    def test_skins_and_shapes_coexist_in_one_file(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import blendshape, export, rigging

        base = cmds.ls(cmds.polyCube(name="bs_both")[0], long=True)[0]
        target = cmds.ls(cmds.duplicate(base, name="bs_both_t")[0],
                         long=True)[0]
        cmds.move(0, 0.2, 0, target + ".vtx[0]", relative=True)
        # Same test-authoring fix as test_front_of_chain_under_a_skin above:
        # parent="bb_j1" added so this is one 2-joint skeleton, not two roots.
        skeleton = rigging.create_skeleton({"joints": [
            {"name": "bb_j1", "position": [0.0, 0.0, 0.0]},
            {"name": "bb_j2", "position": [1.0, 0.0, 0.0],
             "parent": "bb_j1"}]})
        rigging.bind_skin({"mesh": base, "root": skeleton["root"]})
        blendshape.create_blendshape({
            "mesh": base,
            "targets": [{"name": "fix", "target_mesh": target}]})
        path = str(tmp_path / "both.fbx").replace("\\", "/")
        result = export.export_fbx({"path": path, "metres_per_unit": 1.0,
                                    "include_skins": True})
        assert result["skin"]["deformers"] == 1
        assert result["skin"]["clusters"] == 2
        assert result["shapes"]["channels"] == 1
        assert result["shapes"]["shapes"][0]["name"] == "fix"


class TestClipInMaya:
    # The scene is reset per test, but PROCESS state (loaded plugins, the
    # fbxmaya fps cache) persists - prefixes/teardowns guard against
    # cross-test process residue, following the bs_base/bs_base8 precedent
    # in the blendshape classes above.
    def _rig(self, cmds, prefix, bound=True):
        from maya_plugin.handlers import rigging

        base = cmds.ls(cmds.polyCube(name=prefix + "_base", height=2,
                                     subdivisionsHeight=4)[0], long=True)[0]
        skeleton = rigging.create_skeleton({"joints": [
            {"name": prefix + "_root", "position": [0.0, -1.0, 0.0]},
            {"name": prefix + "_mid", "position": [0.0, 0.0, 0.0],
             "parent": prefix + "_root"},
            {"name": prefix + "_tip", "position": [0.0, 1.0, 0.0],
             "parent": prefix + "_mid"}]})
        if bound:
            rigging.bind_skin({"mesh": base, "root": skeleton["root"]})
        return base, skeleton["root"]

    def test_author_measures_real_evaluated_motion(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import clip

        base, root = self._rig(cmds, "ca")
        out = clip.author_clip({
            "root": root, "name": "bend", "fps": 30,
            "keys": [
                {"time_s": 0.0, "rotations": {"ca_mid": [0, 0, 0]}},
                {"time_s": 1.0, "rotations": {"ca_mid": [0, 0, 90]}},
            ]})
        assert out["duration_s"] == pytest.approx(1.0)
        assert out["frames"] == 31
        # per-key displacement is EVALUATED: at key 1 the tip half of a
        # 2-unit cube swings 90 degrees about the mid joint
        assert out["per_key"][0]["max_displacement"] == 0.0
        assert out["per_key"][1]["max_displacement"] > 0.5
        # the curves really hold degrees: evaluate mid-clip
        cmds.currentTime(15)
        rz = cmds.getAttr(root + "|ca_mid.rotateZ")
        assert 30.0 < rz < 60.0     # linear tangents, halfway-ish
        cmds.currentTime(0)
        # teardown: the scene is reset per test, but PROCESS state (loaded
        # plugins, the fbxmaya fps cache) persists - this guards against
        # cross-test process residue tripping the export leg's
        # one-clip-per-file scan
        clip.delete_clip({"root": root})

    def test_static_mutators_refuse_then_delete_clip_restores(self):
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import clip, rigging, sculpt

        base, root = self._rig(cmds, "cb")
        rest = sculpt.vertex_positions(cmds, base)
        clip.author_clip({
            "root": root, "name": "bend", "fps": 30,
            "keys": [
                {"time_s": 0.0, "rotations": {"cb_mid": [0, 0, 0]}},
                {"time_s": 0.5, "rotations": {"cb_mid": [0, 0, 45]}},
            ]})
        with pytest.raises(HandlerError, match="clip 'bend'"):
            rigging.pose_skeleton({"root": root,
                                   "rotations": {"cb_mid": [0, 0, 10]}})
        with pytest.raises(HandlerError, match="animation curves"):
            rigging.reset_pose({"root": root})
        out = clip.delete_clip({"root": root})
        assert out["clip"] == "bend" and out["deleted_curves"] >= 3
        # static posing works again, and the mesh is back at bind
        now = sculpt.vertex_positions(cmds, base)
        worst = max(abs(a - b) for a, b in zip(rest, now))
        assert worst < 1e-4
        rigging.pose_skeleton({"root": root,
                               "rotations": {"cb_mid": [0, 0, 10]}})

    def test_loop_refusal_and_replace_are_real(self):
        """PRE-EXISTING TEST, CORRECTED FOR #718 (found failing by Task
        10's whole-file run - not a Task 8 blind edit, but written at #695
        before #718 gave a rig multiple simultaneous clips). Its old
        assertions encoded #695's single-clip-per-rig behaviour: any
        second author_clip call, regardless of name, replaced the rig's
        one clip outright. #718 replaced that with "same name re-appends
        at the tail; a different name is a SECOND clip that coexists" (see
        clip.py's module docstring, decision 4) - so authoring "second"
        after "first" must NOT report replaced="first", and "first"'s
        curve must still be on the rig afterward (padded by the
        self-contained rule, not deleted). MEASURED: re-authoring the SAME
        name is what still reports `replaced` and cuts the old curve range
        - checked below on "first" itself.
        """
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import clip

        base, root = self._rig(cmds, "cc", bound=False)
        with pytest.raises(HandlerError, match="does not close"):
            clip.author_clip({
                "root": root, "name": "bad", "fps": 30, "loop": True,
                "keys": [
                    {"time_s": 0.0, "rotations": {"cc_mid": [0, 0, 0]}},
                    {"time_s": 1.0, "rotations": {"cc_mid": [0, 0, 45]}},
                ]})
        clip.author_clip({
            "root": root, "name": "first", "fps": 30,
            "keys": [
                {"time_s": 0.0, "rotations": {"cc_mid": [0, 0, 0]}},
                {"time_s": 1.0, "rotations": {"cc_mid": [0, 0, 45]}},
            ]})
        out = clip.author_clip({
            "root": root, "name": "second", "fps": 30,
            "keys": [
                {"time_s": 0.0, "rotations": {"cc_tip": [0, 0, 0]}},
                {"time_s": 1.0, "rotations": {"cc_tip": [0, 0, 20]}},
            ]})
        # MEASURED: a NEW name is a second, coexisting clip - nothing is
        # replaced, and "first"'s clip and curves survive.
        assert out["replaced"] is None
        assert out["clips"] == ["first", "second"]
        assert (cmds.listConnections(
            root + "|cc_mid.rotateZ",
            source=True, destination=False, type="animCurve") or [])
        # re-authoring the SAME name ("first") is what replaces: its old
        # range is cut and it is re-appended at the tail.
        redo = clip.author_clip({
            "root": root, "name": "first", "fps": 30,
            "keys": [
                {"time_s": 0.0, "rotations": {"cc_mid": [0, 0, 60]}},
                {"time_s": 1.0, "rotations": {"cc_mid": [0, 0, 0]}},
            ]})
        assert redo["replaced"] == "first"
        assert redo["clips"] == ["second", "first"]
        clip.delete_clip({"root": root})   # scene-persistence teardown


class TestClipExportInMaya:
    # Same reset-per-test-scene, persistent-process rule as TestClipInMaya:
    # one prefix per test.
    def _clipped_scene(self, cmds, prefix, with_blink=True):
        from maya_plugin.handlers import blendshape, clip, rigging

        base = cmds.ls(cmds.polyCube(name=prefix + "_base", height=2,
                                     subdivisionsHeight=4)[0], long=True)[0]
        skeleton = rigging.create_skeleton({"joints": [
            {"name": prefix + "_root", "position": [0.0, -1.0, 0.0]},
            {"name": prefix + "_mid", "position": [0.0, 0.0, 0.0],
             "parent": prefix + "_root"}]})
        rigging.bind_skin({"mesh": base, "root": skeleton["root"]})
        weights = {}
        if with_blink:
            target = cmds.ls(cmds.duplicate(base, name=prefix + "_t")[0],
                             long=True)[0]
            cmds.move(0, 0, 0.2, target + ".vtx[0]", relative=True)
            blendshape.create_blendshape({
                "mesh": base,
                "targets": [{"name": prefix + "_blink",
                             "target_mesh": target}]})
            weights = {prefix + "_blink": 0.0}
        keys = [
            {"time_s": 0.0, "rotations": {prefix + "_mid": [0, 0, 0]},
             "root_position": [0.0, -1.0, 0.0], "blend_weights": weights},
            {"time_s": 0.5, "rotations": {prefix + "_mid": [0, 0, 30]},
             "root_position": [0.0, -0.95, 0.0],
             "blend_weights": ({prefix + "_blink": 1.0} if with_blink
                               else {})},
            {"time_s": 1.0, "rotations": {prefix + "_mid": [0, 0, 0]},
             "root_position": [0.0, -1.0, 0.0], "blend_weights": weights},
        ]
        if not with_blink:
            for k in keys:
                k.pop("blend_weights")
        clip.author_clip({"root": skeleton["root"], "name": "sway",
                          "fps": 30, "loop": True, "keys": keys})
        return base, skeleton["root"]

    def test_the_measurements(self, tmp_path):
        """THE MEASUREMENT BATTERY (#695 plan constraint). Every assertion
        here pins a literal the byte gate rests on. On failure, read the
        raw facts (facts.anim_nodes / facts.takes), fix the READER or the
        VIOLATION to the measured truth, and record the measured value in
        a comment here - never force the literal.
        """
        import maya.cmds as cmds

        from maya_plugin.handlers import clip, export, fbxbytes

        base, root = self._clipped_scene(cmds, "cd")
        path = str(tmp_path / "sway.fbx").replace("\\", "/")
        # SELECTED export (mesh + root): the scene resets per test, but
        # earlier prefixed meshes can still be present within a run, and a
        # selected export keeps this file about this rig - same shape the
        # skin-export contract documents.
        result = export.export_fbx({"path": path, "metres_per_unit": 1.0,
                                    "nodes": [base, root],
                                    "include_skins": True,
                                    "include_animation": True})
        anim = result["animation"]
        assert anim is not None
        # (3) the take is named after the clip - MEASURED: Maya's exporter
        # ALSO always writes its own default take ("Take 001", full bake
        # range) alongside the one FBXExportSplitAnimationIntoTakes adds, so
        # the file carries 2 takes, not 1 (see export.py's FBX_ANIM_MEL and
        # anim_violations comments for what was tried and rejected). The
        # clip-named take must be present; the extra one is not a defect.
        assert [t["name"] for t in anim["takes"]] == ["Take 001", "sway"]
        sway_take = next(t for t in anim["takes"] if t["name"] == "sway")
        # (1) tick constant: a 1.0 s clip must measure 1.0 s in ticks
        assert sway_take["duration_s"] == pytest.approx(1.0, abs=0.04)
        by = {(t["target"], t["property"]): t for t in anim["targets"]}
        # (2) property strings + (4) baked key count
        mid = by[("cd_mid", "Lcl Rotation")]
        assert mid["curves"] == 3
        assert mid["key_count"] == 31          # round(1.0 * 30) + 1
        root_t = by[("cd_root", "Lcl Translation")]
        assert root_t["key_count"] == 31
        # (5) DeformPercent - MEASURED key_count 31: weight curves resample
        # with everything else once Resample All is on. The contract
        # deliberately keeps >=2 (channels may be sparse), so the assertion
        # stays loose.
        blink = by[("cd_blink", "DeformPercent")]
        assert blink["key_count"] >= 2
        # an independent read of the bytes agrees with the tool, on the
        # keys a bare re-read can produce. "clips" is excluded: it is
        # composed by export_fbx from anim_facts's own output PLUS the
        # scene's declared clip names/joints/channels (anim_clip_facts),
        # so it is not something fbxbytes.anim_facts() on its own ever
        # returns - comparing it here would fail on a key mismatch that
        # has nothing to do with byte-honesty.
        assert (fbxbytes.anim_facts(fbxbytes.read_fbx(path))
                == {k: v for k, v in anim.items() if k != "clips"})
        # skins and shapes still green alongside animation
        assert result["skin"]["deformers"] == 1
        assert result["shapes"]["shapes"][0]["name"] == "cd_blink"
        clip.delete_clip({"root": root})   # scene-persistence teardown

    def test_animation_off_writes_zero_curves(self, tmp_path):
        """(6) the symmetric assertion: an ANIMATED scene exported without
        include_animation carries not one curve record."""
        import maya.cmds as cmds

        from maya_plugin.handlers import clip, export, fbxbytes

        base, root = self._clipped_scene(cmds, "cf", with_blink=False)
        path = str(tmp_path / "static.fbx").replace("\\", "/")
        result = export.export_fbx({"path": path, "metres_per_unit": 1.0,
                                    "nodes": [base, root],
                                    "include_skins": True})
        assert result["animation"] is None
        facts = fbxbytes.read_fbx(path)
        assert len(facts.anim_curves) == 0
        assert len(facts.anim_nodes) == 0
        clip.delete_clip({"root": root})   # scene-persistence teardown

    def test_include_animation_without_a_clip_refuses(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import export

        cmds.polyCube(name="ce_plain")
        path = str(tmp_path / "none.fbx").replace("\\", "/")
        with pytest.raises(HandlerError, match="no clip exists"):
            export.export_fbx({"path": path, "metres_per_unit": 1.0,
                               "include_animation": True})

    def test_two_clip_carrying_roots_refuse_naming_the_take(self, tmp_path):
        """CONTROLLER-ADDED SCOPE (Task 6 review gap; message updated #718):
        export._scene_clips refuses to pick a take name when more than one
        skeleton root in the exported selection carries an authored clip -
        multi-CLIP is supported (N takes on one timeline), but two roots
        still have no honest single-file timeline. Untested anywhere before
        this."""
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import clip, export, rigging

        def _clipped_rig(prefix):
            base = cmds.ls(cmds.polyCube(name=prefix + "_base", height=2,
                                         subdivisionsHeight=4)[0],
                          long=True)[0]
            skeleton = rigging.create_skeleton({"joints": [
                {"name": prefix + "_root", "position": [0.0, -1.0, 0.0]},
                {"name": prefix + "_mid", "position": [0.0, 0.0, 0.0],
                 "parent": prefix + "_root"}]})
            rigging.bind_skin({"mesh": base, "root": skeleton["root"]})
            clip.author_clip({
                "root": skeleton["root"], "name": "move", "fps": 30,
                "keys": [
                    {"time_s": 0.0,
                     "rotations": {prefix + "_mid": [0, 0, 0]}},
                    {"time_s": 1.0,
                     "rotations": {prefix + "_mid": [0, 0, 30]}},
                ]})
            return base, skeleton["root"]

        base_a, root_a = _clipped_rig("cga")
        base_b, root_b = _clipped_rig("cgb")
        path = str(tmp_path / "two_roots.fbx").replace("\\", "/")
        try:
            with pytest.raises(HandlerError,
                                match=r"2 skeletons carry clips") as excinfo:
                export.export_fbx({
                    "path": path, "metres_per_unit": 1.0,
                    "nodes": [base_a, root_a, base_b, root_b],
                    "include_animation": True})
            assert "cga_root" in str(excinfo.value)
            assert "cgb_root" in str(excinfo.value)
        finally:
            clip.delete_clip({"root": root_a})
            clip.delete_clip({"root": root_b})


class TestBindPoseRestInMaya:
    """#732 against real dagPose data. create_skeleton auto-orients local
    X down the bone, so jointOrient is NON-zero and rotate is zero at
    bind - decomposition must recover ~0. A hand-built rig with non-zero
    rotate at bind is the imported-rig case the warning used to spam."""

    def test_a_posed_create_skeleton_rig_pins_at_bind_and_warns(self, tmp_path):
        import json
        import maya.cmds as cmds
        from maya_plugin.handlers import clip, rigging

        base = cmds.ls(cmds.polyCube(name="bp_base", height=2,
                                     subdivisionsHeight=4)[0], long=True)[0]
        skel = rigging.create_skeleton({"joints": [
            {"name": "bp_root", "position": [0.0, -1.0, 0.0]},
            {"name": "bp_mid", "position": [0.0, 0.0, 0.0],
             "parent": "bp_root"},
            {"name": "bp_tip", "position": [0.0, 1.0, 0.0],
             "parent": "bp_mid"}]})
        rigging.bind_skin({"mesh": base, "root": skel["root"]})
        rigging.pose_skeleton({"root": skel["root"],
                               "rotations": {"bp_mid": [25, 0, 0]}})
        out = clip.author_clip({
            "root": skel["root"], "name": "idle", "fps": 30,
            "keys": [
                {"time_s": 0.0, "rotations": {"bp_mid": [0, 0, 0]}},
                {"time_s": 1.0, "rotations": {"bp_mid": [0, 0, 30]}}]})
        rest = json.loads(cmds.getAttr(skel["root"] + ".mcp_clip_rest"))
        assert abs(rest["bp_mid.rotateX"]) < 1e-3   # BIND, not 25
        assert any("posed away from the bind pose" in w
                   for w in out["warnings"])
        clip.delete_clip({"root": skel["root"]})

    def test_a_bind_pose_with_rotation_does_not_warn(self, tmp_path):
        import json
        import maya.cmds as cmds
        from maya_plugin.handlers import clip, rigging

        cmds.select(clear=True)
        r = cmds.joint(name="ir_root", position=[0, -1, 0])
        m = cmds.joint(name="ir_mid", position=[0, 0, 0])
        cmds.joint(name="ir_tip", position=[0, 1, 0])
        cmds.setAttr(m + ".rotateX", 15.0)   # bind pose WITH rotation
        base = cmds.ls(cmds.polyCube(name="ir_base", height=2,
                                     subdivisionsHeight=4)[0], long=True)[0]
        root_long = cmds.ls(r, long=True)[0]
        rigging.bind_skin({"mesh": base, "root": root_long})
        out = clip.author_clip({
            "root": root_long, "name": "idle", "fps": 30,
            "keys": [
                {"time_s": 0.0, "rotations": {"ir_mid": [15, 0, 0]}},
                {"time_s": 1.0, "rotations": {"ir_mid": [45, 0, 0]}}]})
        rest = json.loads(cmds.getAttr(root_long + ".mcp_clip_rest"))
        assert abs(rest["ir_mid.rotateX"] - 15.0) < 1e-3
        assert not any("posed" in w for w in out["warnings"])
        clip.delete_clip({"root": root_long})


class TestMultiTakeExportInMaya:
    """#718's measurement battery. Same reset-per-test-scene,
    persistent-process rule as TestClipExportInMaya: one prefix per test.

    Every assertion here pins a literal the byte gate rests on. On failure,
    read the raw facts (facts.takes / facts.anim_nodes), fix the READER or
    the VIOLATION to the measured truth, and record the measured value in
    a comment here - never force the literal.

    MEASURED (this battery, mayapy, 2026-08-22): all five plan questions
    answered by a real two-clip export.
      1. a two-clip file carries 3 takes: the exporter's own always-present
         default ("Take 001") plus the two named ones ("idle", "walk") -
         same "+1" shape TestClipExportInMaya measured for a single clip.
      2. each named take's start_s/stop_s matches its OWN declared frame
         range converted at the clip's fps (idle 0..1.0s, walk
         32/30..62/30s) - NOT the whole bake span.
      3. STOP-WORTHY, MEASURED, CONTRADICTS THE DESIGN ASSUMPTION: curve
         records ARE segmented per take, not one-per-plug over the whole
         bake range. A rotation plug that any clip touches (directly or
         through the self-contained rule's padding) carries THREE separate
         AnimationCurveNode records in the file, not one: one spanning the
         WHOLE bake range (ticks matching "Take 001", key_count
         span_frames+1 = 63) and one PER NAMED TAKE, each spanning only
         that take's own tick range with that take's own key_count (31 for
         both idle 0-30 and walk 32-62 here, since both happen to be the
         same length). Confirmed directly off facts.anim_nodes (raw
         AnimationCurveNode records, not the aggregated `targets` view) -
         see test_curve_records_are_segmented_per_take, which reads the
         bytes through a gate-BYPASSING export helper because going
         through the real export.export_fbx() gate is what exposed this:
         its `by.setdefault((target, property), t)` first-wins map picks
         WHICHEVER of the three duplicate records the FBX file happens to
         list first, ordered by an FBX-internal object UID that is NOT
         stable run-to-run for the identical scene (measured: 8 back-to-back
         exports of the byte-identical scene in one process split 6 pass /
         2 fail; a single export re-run immediately after this file's
         probe script alone flipped from pass to fail). export_fbx()
         therefore currently PASSES OR FAILS ITS OWN GATE NON-DETERMINISTICALLY
         on a genuinely correct multi-take export, roughly as often as it
         picks the "Take 001" duplicate (63 keys, matches `expected`) as it
         picks a per-take duplicate (31 keys, "bakes 31 keys, expected 63"
         violation). Per this task's explicit instruction, this is NOT
         fixed here: making anim_violations correct requires attributing
         each curve record to the take that actually owns it, which needs
         `fbxbytes.anim_facts`'s `targets` to carry take identity - a
         reader SHAPE change, and a design decision on what "correct" even
         means here (does the policy validate every duplicate, just the
         default take's, or something else) that is above this task's pay
         grade. Filed as a follow-up; see the task report.

         FOLLOW-UP DONE (#718 Task 10b, t718-10b-report.md):
         fbxbytes.anim_facts's targets now carry "take" - the owning
         AnimationStack's name, resolved structurally through the
         AnimationCurveNode -> AnimationLayer -> AnimationStack connection
         chain read_fbx keeps. anim_violations/anim_clip_facts check each
         declared clip against only ITS OWN take's records, at that take's
         own span, ignoring records attributed to "Take 001" or to no
         take. See test_the_real_gate_passes_a_two_clip_export below,
         which calls the real gate (no bypass) and passes.
      4. "Take 001" (the exporter's default) spans the WHOLE bake range,
         0..62/30 s - it is not scoped to any one clip.
      5. mt_mid (keyed only in idle) reads back its rest value (0.0) at
         EVERY integer frame of walk's own range (32..62 inclusive), not
         merely at the two boundary keys the self-contained rule pins -
         see test_every_frame_of_a_padded_range_holds_rest.
    """

    def _two_clip_scene(self, cmds, prefix):
        from maya_plugin.handlers import clip, rigging

        base = cmds.ls(cmds.polyCube(name=prefix + "_base", height=2,
                                     subdivisionsHeight=4)[0], long=True)[0]
        skeleton = rigging.create_skeleton({"joints": [
            {"name": prefix + "_root", "position": [0.0, -1.0, 0.0]},
            {"name": prefix + "_mid", "position": [0.0, 0.0, 0.0],
             "parent": prefix + "_root"},
            {"name": prefix + "_tip", "position": [0.0, 1.0, 0.0],
             "parent": prefix + "_mid"}]})
        rigging.bind_skin({"mesh": base, "root": skeleton["root"]})
        idle = clip.author_clip({
            "root": skeleton["root"], "name": "idle", "fps": 30,
            "keys": [
                {"time_s": 0.0, "rotations": {prefix + "_mid": [0, 0, 0]}},
                {"time_s": 0.5, "rotations": {prefix + "_mid": [0, 0, 30]}},
                {"time_s": 1.0, "rotations": {prefix + "_mid": [0, 0, 0]}}]})
        walk = clip.author_clip({
            "root": skeleton["root"], "name": "walk", "fps": 30,
            "keys": [
                {"time_s": 0.0, "rotations": {prefix + "_tip": [0, 0, 0]}},
                {"time_s": 0.5, "rotations": {prefix + "_tip": [0, 0, 25]}},
                {"time_s": 1.0, "rotations": {prefix + "_tip": [0, 0, 0]}}]})
        return base, skeleton["root"], idle, walk

    def test_the_layout_is_what_the_tool_reported(self):
        import maya.cmds as cmds

        base, root, idle, walk = self._two_clip_scene(cmds, "mt")
        assert (idle["start_frame"], idle["end_frame"]) == (0, 30)
        assert (walk["start_frame"], walk["end_frame"]) == (32, 62)
        assert walk["clips"] == ["idle", "walk"]
        # MEASURED: walk never mentions mt_mid on any key, so it is a pure
        # rest pin (padded_channels) - not "held", which is reserved for a
        # channel a clip DOES key somewhere in its own range but misses at
        # one of its own boundary frames (walk keys no channel that way in
        # this scene, so held_channels is exercised only by mt_tip's
        # back-fill, a different list).
        assert walk["padded_channels"] == ["mt_mid"]
        assert walk["back_filled"]["channels"] == ["mt_tip"]
        assert cmds.playbackOptions(query=True, maxTime=True) == 62

    def test_a_padded_channel_holds_rest_through_the_other_clip(self):
        """THE contamination check, in the scene: mt_mid is keyed in idle
        and never mentioned in walk, so without the pad it would hold
        idle's last value through every frame of walk."""
        import maya.cmds as cmds

        base, root, idle, walk = self._two_clip_scene(cmds, "mu")
        mid = cmds.ls("mu_mid", long=True)[0]
        for frame in (32, 47, 62):
            cmds.currentTime(frame)
            assert abs(cmds.getAttr(mid + ".rotateZ")) < 1e-4, frame
        # ...and mu_tip (which only walk keys) still back-fills to rest
        # through idle's own range - the pad runs in both directions, not
        # just forward from idle into walk.
        tip = cmds.ls("mu_tip", long=True)[0]
        for frame in (0, 15, 30):
            cmds.currentTime(frame)
            assert abs(cmds.getAttr(tip + ".rotateZ")) < 1e-4, frame
        # ...and idle's OWN keyed motion on mu_mid survived walk being
        # authored afterward - this reaches the 30 degree peak idle itself
        # keyed at frame 15 (0.5s), not a rest/back-fill value.
        cmds.currentTime(15)
        assert abs(cmds.getAttr(mid + ".rotateZ") - 30.0) < 1e-3

    def test_every_frame_of_a_padded_range_holds_rest(self):
        """Extends the brief's boundary-sample check (item 2 of the four
        measurements this task owes): the headless fake interpolates
        linearly between keys and cannot model real tangent shape, so it
        can only prove the two ENDPOINTS of a pinned span are flat. Real
        tangents could still bow between them. This samples every integer
        frame in walk's own range under a real evaluated curve.

        MEASURED: mt_mid's rotateX/Y/Z hold exactly 0.0 (< 1e-4) at every
        one of the 31 integer frames 32..62 inclusive - the flat in/out
        tangents _pin sets on the two boundary keys (32, 62) hold the
        whole span between them flat too, not just the sampled ends.
        """
        import maya.cmds as cmds

        base, root, idle, walk = self._two_clip_scene(cmds, "mv2")
        mid = cmds.ls("mv2_mid", long=True)[0]
        for frame in range(32, 63):
            cmds.currentTime(frame)
            for attr in ("rotateX", "rotateY", "rotateZ"):
                assert abs(cmds.getAttr(mid + "." + attr)) < 1e-4, \
                    (frame, attr)

    def _export_bypassing_the_gate(self, cmds, mel, path, nodes, declared):
        """Writes the FBX the way export_fbx does - same MEL, same preamble
        constants, same bake-range/split-into-takes calls, reusing
        export.py's own exposed constants (FBX_PREAMBLE_MEL etc. - the
        same ones evals/maya_export.py composes from, per export.py's
        module docstring) rather than re-deriving the MEL, so those parts
        cannot silently drift from what export_fbx actually sends the
        exporter - but WITHOUT export_fbx's anim_violations gate on top,
        and without its forced fbxmaya unloadPlugin/loadPlugin reload
        (export.py: the bundled FBX plugin caches the scene's frame rate at
        LOAD time, so the reload exists to make it re-read a possibly-
        changed fps before every animated export). Omitting the reload is
        acceptable ONLY because every caller in this class shares one
        session-scoped mayapy process (module docstring) in which a real,
        reload-triggering export_fbx call has already run at 30 fps before
        any of these bypass exports - TestClipExportInMaya::
        test_the_measurements, earlier in this file, is that call - so the
        plugin's cached fps already matches this class's own 30 fps
        scenes. A bypass call run first, in a fresh process, or against a
        scene at a different fps would bake at the wrong rate silently.

        Exists because export.anim_violations is what this class's item 3
        originally measured as non-deterministic before #718 Task 10b's
        take-attribution fix (see the class docstring): a test that needs
        to inspect the RAW per-take curve records - the exact ambiguity
        the gate now resolves - cannot go through the gate itself without
        either depending on that fix already being correct or spending one
        of the shared process's scarce reload-cycle budget (see
        test_the_real_gate_passes_a_two_clip_export's docstring) on a call
        whose gate outcome isn't what the test is checking.
        """
        from maya_plugin.handlers import export as export_mod, fbxbytes

        cmds.loadPlugin("fbxmaya", quiet=True)
        for statement in (export_mod.FBX_PREAMBLE_MEL
                          + export_mod.FBX_SCENE_CONTENT_MEL
                          + export_mod.FBX_SHAPES_MEL
                          + export_mod.FBX_SKINS_MEL[True]
                          + export_mod.FBX_ANIM_MEL[True]):
            mel.eval(statement)
        span = int(declared["span_frames"])
        mel.eval("FBXExportBakeComplexStart -v 0")
        mel.eval("FBXExportBakeComplexEnd -v %d" % span)
        mel.eval("FBXExportSplitAnimationIntoTakes -clear")
        for record in declared["clips"]:
            mel.eval('FBXExportSplitAnimationIntoTakes -v "%s" %d %d'
                     % (record["name"], record["start_frame"],
                        record["end_frame"]))
        mel.eval("FBXExportScaleFactor %g" % export_mod.EXPORT_SCALE_FACTOR)
        cmds.select(nodes, replace=True)
        cmds.file(path, force=True, options="v=0", type="FBX export",
                  pr=True, es=True)
        fbxbytes.set_unit_scale_factor(path)
        return fbxbytes.read_fbx(path)

    def test_the_measurements(self, tmp_path):
        """Items 1, 2 and 4 go through fbxbytes.anim_facts on a real
        export - reliable, since none of them depend on which of a
        segmented plug's duplicate curve records a first-wins lookup
        happens to land on. Item 3 is measured RAW (see the class
        docstring for the full finding and why): counting
        AnimationCurveNode records per (target, property) pair directly,
        never through the gate.
        """
        import maya.cmds as cmds
        import maya.mel as mel

        from maya_plugin.handlers import clip, export, fbxbytes

        base, root, idle, walk = self._two_clip_scene(cmds, "mv")
        path = str(tmp_path / "two.fbx").replace("\\", "/")
        declared = export._scene_clips(cmds)
        facts = self._export_bypassing_the_gate(cmds, mel, path,
                                                [base, root], declared)
        anim = fbxbytes.anim_facts(facts)
        names = [t["name"] for t in anim["takes"]]
        # (1) MEASURED: the exporter's own default take rides along with
        # the two named ones.
        assert "idle" in names and "walk" in names
        assert len(names) == 3, names
        by = {t["name"]: t for t in anim["takes"]}
        # (2) MEASURED: each split take carries its OWN LocalTime range.
        assert abs(by["idle"]["start_s"] - 0.0) < 1e-3
        assert abs(by["idle"]["stop_s"] - 1.0) < 1e-3
        assert abs(by["walk"]["start_s"] - 32 / 30.0) < 1e-3
        assert abs(by["walk"]["stop_s"] - 62 / 30.0) < 1e-3
        # (4) MEASURED: Take 001 spans the whole bake range.
        assert abs(by["Take 001"]["stop_s"] - 62 / 30.0) < 1e-3
        # (3) MEASURED, RAW, off facts.anim_nodes directly (see the class
        # docstring for the full finding): each rotation plug carries
        # THREE AnimationCurveNode records, not one - segmented per take,
        # contradicting the "one curve per plug over the whole span"
        # design assumption export.anim_violations and the docstrings
        # above it were written against.
        by_uid = {n.uid: n for n in facts.nodes if n.uid is not None}
        counts = {}
        for node in facts.anim_nodes.values():
            if node["target_kind"] != "model" or node["target"] not in by_uid:
                continue
            key = (by_uid[node["target"]].name, node["property"])
            counts[key] = counts.get(key, 0) + 1
        for joint in ("mv_mid", "mv_tip"):
            assert counts[(joint, "Lcl Rotation")] == 3, counts
        clip.delete_clip({"root": root})   # scene-persistence teardown

    def test_curve_records_are_segmented_per_take(self, tmp_path):
        """Item 1 of the four owed measurements, gone one level deeper
        than the count in test_the_measurements: this pins the exact tick
        range and key_count of EACH of the three duplicate records per
        plug, proving they are not just three copies of the same thing
        but three DIFFERENT segments - one matching the whole bake range
        ("Take 001"'s own ticks, 63 keys) and one matching each named
        take's own ticks (31 keys each, since idle and walk are both 1s
        clips here).

        STOP: this is exactly the segmentation the task brief said to
        stop on rather than reshape the reader for - see the class
        docstring for the full finding, why export.export_fbx()'s gate is
        measured non-deterministic as a direct consequence, and why that
        is not fixed in this task.
        """
        import maya.cmds as cmds
        import maya.mel as mel

        from maya_plugin.handlers import clip, export, fbxbytes

        base, root, idle, walk = self._two_clip_scene(cmds, "mv3")
        path = str(tmp_path / "raw.fbx").replace("\\", "/")
        declared = export._scene_clips(cmds)
        facts = self._export_bypassing_the_gate(cmds, mel, path,
                                                [base, root], declared)
        by_uid = {n.uid: n for n in facts.nodes if n.uid is not None}
        span_ticks = int(round(62 / 30.0 * fbxbytes.KTIME_PER_SECOND))
        idle_ticks = (0, int(round(30 / 30.0 * fbxbytes.KTIME_PER_SECOND)))
        walk_ticks = (int(round(32 / 30.0 * fbxbytes.KTIME_PER_SECOND)),
                     int(round(62 / 30.0 * fbxbytes.KTIME_PER_SECOND)))
        for joint in ("mv3_mid", "mv3_tip"):
            ranges = []
            for node in facts.anim_nodes.values():
                if (node["target_kind"] != "model"
                        or by_uid.get(node["target"], None) is None
                        or by_uid[node["target"]].name != joint
                        or node["property"] != "Lcl Rotation"):
                    continue
                curve = facts.anim_curves[node["curves"][0]]
                ranges.append((curve["first_tick"], curve["last_tick"],
                              curve["key_count"]))
            ranges.sort()
            # MEASURED (tolerant to a few ticks of rounding): one record
            # spans the WHOLE bake range with 63 keys, one spans idle's
            # own range with 31, one spans walk's own range with 31.
            assert len(ranges) == 3, (joint, ranges)
            (first, first_last, first_n) = ranges[0]
            assert first == 0
            assert abs(first_last - idle_ticks[1]) < 1000
            assert first_n == 31
            (second, second_last, second_n) = ranges[1]
            assert second == 0
            assert abs(second_last - span_ticks) < 1000
            assert second_n == 63
            (third, third_last, third_n) = ranges[2]
            assert abs(third - walk_ticks[0]) < 1000
            assert abs(third_last - walk_ticks[1]) < 1000
            assert third_n == 31
        clip.delete_clip({"root": root})   # scene-persistence teardown

    def test_the_real_gate_passes_a_two_clip_export(self, tmp_path):
        """#718 Task 10b: the fix. Task 10 measured export.export_fbx()'s
        own byte gate failing a genuinely correct two-clip export at
        random - 6 passes and 2 failures over 8 back-to-back exports of
        one scene in one process (t718-10-report.md finding #3), because
        the gate used to collapse a segmented plug's three duplicate curve
        records first-wins on an FBX-internal UID that is not stable run
        to run. With curve records attributed to their take
        (fbxbytes.anim_facts's "take" field, resolved structurally through
        the AnimationCurveNode -> AnimationLayer -> AnimationStack chain)
        and anim_violations/anim_clip_facts checking each declared clip
        against its OWN take's records at its OWN span, the ambiguity is
        gone: this calls the REAL export.export_fbx() - no bypass helper -
        on a correct two-clip scene and it must pass.

        WHY THIS TEST IS A SINGLE CALL, NOT A 6x LOOP: MEASURED (a new
        finding of this task, not in Task 10's report) that export_fbx's
        forced fbxmaya unloadPlugin/loadPlugin cycle (#695 - required so
        the plugin re-reads the scene's fps before every animated export)
        corrupts THIS PROCESS's heap when repeated too many times in one
        mayapy process. This file's persistent, session-scoped mayapy
        process (module docstring) already carries ONE such reload cycle
        from TestClipExportInMaya::test_the_measurements before reaching
        this class, and the RUNNING TOTAL across the WHOLE process - not
        just one test's own count - is what matters: a running total of 3
        reload cycles (that pre-existing one plus 2 more, whether from one
        tight Python loop in a single test or spread across separate
        parametrized test items - both were tried and both crashed
        identically, reproduced 3/3) reliably crashes
        `maya.standalone.uninitialize()` at session end (Windows
        STATUS_HEAP_CORRUPTION, 0xc0000374); a running total of 2 (the
        pre-existing one plus this test's single call) was reproduced
        clean. This is an environmental fragility in the #695 reload
        workaround under heavy repetition on this machine's
        mayapy/fbxmaya build - orthogonal to this task's fix and out of
        its scope to change - not a #718 defect: a standalone,
        single-purpose mayapy process (no other test's accumulated plugin
        churn) called this SAME real gate, with no bypass, on this SAME
        scene 30 times in a row with zero failures and no crash, which is
        the authoritative "at least 6 consecutive in one process" proof
        this task's brief asks for (see the task report for that run's
        full output, and for why a 6x loop cannot also live safely inside
        this shared-process suite). This in-suite test is a standing
        regression guard at the budget the shared process can carry
        safely.

        PRE-#729 HISTORY - the budget above no longer constrains this test:
        #729 replaced the unconditional per-export unload/reload with a
        guard that only pays the reload cost when the scene's time unit
        actually changed (export._fbx_reload_needed); a same-fps export no
        longer spends a reload cycle at all (see
        TestMultiTakeExportInMaya.test_repeated_same_fps_exports_neither_
        reload_nor_crash, which runs six real animated exports in this
        same process and measures zero reload cycles). This test stays a
        single call because a single call is still all it needs to prove,
        not because the process cannot afford more.
        """
        import maya.cmds as cmds

        from maya_plugin.handlers import clip, export

        base, root, idle, walk = self._two_clip_scene(cmds, "mx")
        path = str(tmp_path / "deterministic.fbx").replace("\\", "/")
        result = export.export_fbx({
            "path": path, "metres_per_unit": 1.0,
            "nodes": [base, root], "include_animation": True})
        anim = result["animation"]
        assert anim is not None
        assert sorted(c["name"] for c in anim["clips"]) == ["idle", "walk"]
        clip.delete_clip({"root": root})   # scene-persistence teardown

    def test_a_named_delete_leaves_the_other_take_exportable(self, tmp_path):
        """Stays on the bypass helper, but NOT because the gate is broken:
        #718 Task 10b fixed export.anim_violations's non-deterministic
        first-wins collapse in this same commit (see
        test_the_real_gate_passes_a_two_clip_export, which calls the real
        gate on a two-clip scene and passes). The reason left is budget,
        not correctness: this shared mayapy process (module docstring)
        only has room for ONE more `export_fbx` call whose
        include_animation=True forces fbxmaya's unloadPlugin/loadPlugin
        reload cycle (#695) before the running total of such cycles across
        the whole process crashes `maya.standalone.uninitialize()` at
        session end (see that same test's docstring for the measured
        running-total budget: 2 clean, 3 crashes, reproduced 3/3). That one
        remaining call is already spent by
        test_the_real_gate_passes_a_two_clip_export earlier in this class,
        so this test verifies what it is actually FOR - that a named
        delete leaves the surviving clip's take in the file and the
        deleted one's name gone - on the bypass helper instead of spending
        a reload cycle the process does not have.

        PRE-#729 HISTORY - the reload-cycle budget above no longer applies:
        #729 replaced the unconditional per-export unload/reload with a
        guard that only reloads on an actual frame-rate change
        (export._fbx_reload_needed), so a same-fps `export_fbx` call here
        would cost zero reload cycles, not one. This test stays on the
        bypass helper regardless, because `_export_bypassing_the_gate`
        reads the RAW per-take curve records (facts.anim_nodes) that the
        real gate's anim_facts/anim_violations path does not expose - not
        because the process cannot afford the call.
        """
        import maya.cmds as cmds
        import maya.mel as mel

        from maya_plugin.handlers import clip, export, fbxbytes

        base, root, idle, walk = self._two_clip_scene(cmds, "mw")
        out = clip.delete_clip({"root": root, "name": "idle"})
        assert out["clips"] == ["walk"]
        path = str(tmp_path / "one.fbx").replace("\\", "/")
        declared = export._scene_clips(cmds)
        assert [r["name"] for r in declared["clips"]] == ["walk"]
        facts = self._export_bypassing_the_gate(cmds, mel, path,
                                                [base, root], declared)
        anim = fbxbytes.anim_facts(facts)
        names = [t["name"] for t in anim["takes"]]
        assert "walk" in names and "idle" not in names

    def test_named_delete_measures_real_curve_removal(self):
        """Item 3 of the four owed measurements: delete_clip's
        `deleted_curves` depends on real Maya actually removing a curve
        node once cutKey(..., clear=True) empties it of every key, or #730's
        reap explicitly deletes it - only the headless test fake asserts
        this behaviour today. This measures it against a real Maya, and
        against the raw curve state before and after, rather than trusting
        the reported number alone.

        MEASURED: in this two-clip scene, deleting "idle" reports
        deleted_curves >= 1 and reaped_channels == ["my_mid"] (#730).
        my_mid is a channel idle declared and no surviving clip (walk)
        declares - it carries only walk's own rest-pin keys at frames
        32/62 (outside idle's cut range 0-30), so #730 reaps its whole
        curve rather than leaving those pins as dead weight. my_tip is
        untouched: walk still declares it, so the reap never considers it,
        and idle's own cutKey range (0-30) only strips the back-filled
        rest pins walk put at idle's boundaries, leaving walk's own
        32/47/62 keys exactly as they were.

        Pre-#730 history: this same delete used to report deleted_curves
        == 0 and leave my_mid's curve node in place, just missing idle's
        own keys - "deleted_curves == 0 is structural" was the measured
        truth THEN, before a channel no survivor declared was reaped.
        """
        import maya.cmds as cmds

        from maya_plugin.handlers import clip

        prefix = "my"
        base, root, idle, walk = self._two_clip_scene(cmds, prefix)
        mid = cmds.ls(prefix + "_mid", long=True)[0]
        tip = cmds.ls(prefix + "_tip", long=True)[0]
        # walk back-filled my_tip onto IDLE's own boundaries (0, 30) when
        # walk introduced it (idle didn't declare it yet) - those two pins
        # live inside idle's own doomed range and are correctly cut away
        # by the existing per-range cutKey step below, unrelated to #730's
        # reap. Exclude them so this checks only walk's own keys.
        tip_keys_before = [t for t in cmds.keyframe(tip + ".rotateZ",
                                                     query=True)
                           if not (idle["start_frame"] <= t
                                   <= idle["end_frame"])]

        out = clip.delete_clip({"root": root, "name": "idle"})
        # #730: my_mid is declared by no survivor - its whole curves go.
        assert out["reaped_channels"] == [prefix + "_mid"]
        assert out["deleted_curves"] >= 1
        assert not (cmds.listConnections(
            mid + ".rotateZ", source=True, destination=False,
            type="animCurve") or [])
        # walk's own channel is untouched: same key times as before.
        assert cmds.keyframe(tip + ".rotateZ", query=True) == tip_keys_before
        # walk's own motion is untouched by deleting idle
        cmds.currentTime(47)
        assert abs(cmds.getAttr(tip + ".rotateZ") - 25.0) < 1e-3
        # MEASURED: the full-teardown path (name omitted, last clip) DOES
        # delete every curve - there is nothing left to hold them open.
        final = clip.delete_clip({"root": root})
        assert final["deleted_curves"] > 0
        assert not cmds.listConnections(mid + ".rotateX", source=True,
                                        destination=False, type="animCurve")
        assert not cmds.listConnections(tip + ".rotateX", source=True,
                                        destination=False, type="animCurve")

    def test_repeated_same_fps_exports_neither_reload_nor_crash(self, tmp_path):
        """#729: six real animated exports at ONE fps in this shared
        process. Before the guard this was the measured teardown killer
        (running total of 3 fbxmaya reload cycles crashed
        maya.standalone.uninitialize(), 3/3); with the guard the six
        exports below cost ZERO additional reload cycles, measured by
        counting unloadPlugin calls. The suite finishing cleanly IS the
        teardown proof."""
        import maya.cmds as cmds
        from maya_plugin.handlers import clip, export

        base, root, idle, walk = self._two_clip_scene(cmds, "rp")
        unloads = []
        real_unload = cmds.unloadPlugin

        def counting_unload(*a, **kw):
            unloads.append(a)
            return real_unload(*a, **kw)

        cmds.unloadPlugin = counting_unload
        try:
            for i in range(6):
                path = str(tmp_path / ("r%d.fbx" % i)).replace("\\", "/")
                result = export.export_fbx({
                    "path": path, "metres_per_unit": 1.0,
                    "nodes": [base, root], "include_animation": True})
                assert result["animation"] is not None
        finally:
            cmds.unloadPlugin = real_unload
            clip.delete_clip({"root": root})
        # at most one reload (only if this process's tracker was stale
        # when the loop started); never one per export.
        assert len(unloads) <= 1


class TestTextureHonestyInMaya:
    """#714 against a real exporter. The whole ticket rests on one measured
    claim - file textures survive as Texture+Video records, procedural
    networks vanish entirely - so it is measured here, not assumed."""

    def _png(self, path):
        """A 2x2 PNG with no dependencies (the tool_gaps_live precedent)."""
        import struct
        import zlib

        raw = b"".join(b"\x00" + bytes([255, 0, 0, 0, 255, 0])
                       for _ in range(2))

        def chunk(kind, payload):
            body = kind + payload
            return (struct.pack(">I", len(payload)) + body
                    + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

        png = (b"\x89PNG\r\n\x1a\n"
               + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(raw))
               + chunk(b"IEND", b""))
        with open(path, "wb") as fh:
            fh.write(png)
        return path

    def test_a_file_texture_survives_and_is_reported_found(self, tmp_path):
        """MEASURED under mayapy (Maya 2027): a single `file` node driving
        standardSurface.baseColor exported as exactly 1 Texture record + 1
        Video record (texture_records=1, video_records=1) in a 33024-byte
        selected-export file; file_maps names basename "grain.png" with
        found_in_file=True and dropped_maps=[]. Confirms the module
        docstring's claim on real bytes, not just the headless fake.

        found_in_file is the handler's OWN report - proving the ticket's
        claim needs the independent raw-bytes check below too: the
        basename's literal bytes ("grain.png") are read back out of the
        written file directly, the same rigor the procedural test applies
        to prove absence. A found_in_file that were ever computed from
        something other than a real post-export byte scan would still
        pass the structured assertions above; it cannot survive this one."""
        import maya.cmds as cmds

        from maya_plugin.handlers import export, material, texture_recipes

        image = self._png(str(tmp_path / "grain.png").replace("\\", "/"))
        mesh = cmds.ls(cmds.polyCube(name="tex_cube")[0], long=True)[0]
        material.assign_material({"mesh": mesh, "name": "tex_mat",
                                  "shader": "standardSurface"})
        texture_recipes.apply_texture_recipe({
            "mesh": mesh, "recipe": "file_texture",
            "params": {"file_path": image}})
        path = str(tmp_path / "textured.fbx").replace("\\", "/")
        out = export.export_fbx({"path": path, "metres_per_unit": 1.0,
                                 "nodes": [mesh]})
        block = out["textures"]
        assert block is not None
        assert block["texture_records"] == 1
        maps = [m for m in block["file_maps"] if m["basename"] == "grain.png"]
        assert maps and maps[0]["found_in_file"] is True
        assert block["dropped_maps"] == []
        with open(path, "rb") as fh:
            assert b"grain.png" in fh.read()

    def test_a_procedural_network_is_named_dropped_and_absent_from_bytes(
            self, tmp_path):
        """MEASURED under mayapy (Maya 2027): a noise ("mcpTex_noise") ->
        bump2d -> normalCamera network exports with texture_records=0,
        video_records=0 (28384-byte file), and dropped_maps names exactly
        one entry: terminal="mcpTex_noise", via=["bump2d"] - proof that
        _walk_upstream's bare-node listConnections(bump2d) query aggregates
        the noise source correctly for this single-input case (the #714
        Task 4/5 carried-forward risk #1 - CONFIRMED against real Maya).
        The noise node's own name never appears anywhere in the exported
        bytes (measured: noise.encode() not in the file's raw bytes)."""
        import maya.cmds as cmds

        from maya_plugin.handlers import export, material, texture_recipes

        mesh = cmds.ls(cmds.polyCube(name="proc_cube")[0], long=True)[0]
        material.assign_material({"mesh": mesh, "name": "proc_mat",
                                  "shader": "standardSurface"})
        recipe = texture_recipes.apply_texture_recipe({
            "mesh": mesh, "recipe": "noise_bump"})
        noise = [n for n in recipe["nodes"] if "noise" in n][0]
        path = str(tmp_path / "procedural.fbx").replace("\\", "/")
        out = export.export_fbx({"path": path, "metres_per_unit": 1.0,
                                 "nodes": [mesh]})
        dropped = out["textures"]["dropped_maps"]
        assert [d["terminal"] for d in dropped] == [noise]
        assert dropped[0]["slot"] == "normal"
        # Risk #1 (bare-node listConnections aggregation): the walk steps
        # THROUGH bump2d and queries the bare node name, not a plug - this
        # only reaches the noise terminal at all if real Maya's
        # listConnections(bareNodeName) aggregates every source connection
        # of that node, as the headless fake was built to model. via names
        # exactly the pass-through the walk stepped through to get there.
        assert dropped[0]["via"] == ["bump2d"]
        assert any("silently drops" in w for w in out["warnings"])
        with open(path, "rb") as fh:
            assert noise.encode() not in fh.read()

    def test_require_baked_textures_refuses_and_writes_nothing(self, tmp_path):
        """MEASURED under mayapy (Maya 2027): a ramp_gradient recipe under
        require_baked_textures=true raises HandlerError with message
        "require_baked_textures=true but 1 material slot(s) are driven by
        procedural networks: strict_cube_mat.baseColor (mcpTex_ramp)" -
        refused PRE-WRITE, so neither the final path nor the .part.fbx
        sibling exists afterwards (both measured False)."""
        import os

        import maya.cmds as cmds
        import pytest as _pytest

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import export, material, texture_recipes

        mesh = cmds.ls(cmds.polyCube(name="strict_cube")[0], long=True)[0]
        material.assign_material({"mesh": mesh, "name": "strict_mat",
                                  "shader": "standardSurface"})
        texture_recipes.apply_texture_recipe({"mesh": mesh,
                                              "recipe": "ramp_gradient"})
        path = str(tmp_path / "strict.fbx").replace("\\", "/")
        with _pytest.raises(HandlerError, match="procedural"):
            export.export_fbx({"path": path, "metres_per_unit": 1.0,
                               "nodes": [mesh],
                               "require_baked_textures": True})
        assert not os.path.exists(path)
        assert not os.path.exists(path + ".part.fbx")

    def test_a_whole_scene_export_claims_the_same_maps(self, tmp_path):
        """Whole-scene material carriage is its own measurement, not an
        assumption: the drifter probe measured a SELECTED export only.
        MEASURED under mayapy (Maya 2027): an unselected (whole-scene)
        export of the same file_texture setup carries texture_records=1
        and reports basename "whole.png" with found_in_file=True - the
        same shape as the selected-export case, confirming the claim is
        not selection-mode-dependent. As with the selected-export test,
        found_in_file is checked against an independent raw-bytes read
        too, not just the handler's own report."""
        import maya.cmds as cmds

        from maya_plugin.handlers import export, material, texture_recipes

        image = self._png(str(tmp_path / "whole.png").replace("\\", "/"))
        mesh = cmds.ls(cmds.polyCube(name="whole_cube")[0], long=True)[0]
        material.assign_material({"mesh": mesh, "name": "whole_mat",
                                  "shader": "standardSurface"})
        texture_recipes.apply_texture_recipe({
            "mesh": mesh, "recipe": "file_texture",
            "params": {"file_path": image}})
        path = str(tmp_path / "whole.fbx").replace("\\", "/")
        out = export.export_fbx({"path": path, "metres_per_unit": 1.0})
        found = [m for m in out["textures"]["file_maps"]
                 if m["basename"] == "whole.png"]
        assert found and found[0]["found_in_file"] is True
        with open(path, "rb") as fh:
            assert b"whole.png" in fh.read()

    def test_texclaim_walk_on_awkward_but_legal_shading_does_not_raise(self):
        """Risk probe (#714 Task 5, carried-forward risk #2): texclaim's
        walk is unguarded outside _file_terminal's two getAttr reads, and
        nobody had measured what real Maya raises (if anything) from a
        disconnected shading group or a shape with no shading group at
        all - both awkward but legal scene states. MEASURED under mayapy
        (Maya 2027): the walk RETURNS CLEANLY, raising nothing, and
        reports claims=[] for both nodes - listSets(object=shape, type=1)
        returns an empty list rather than raising when a shape belongs to
        no shading group at all, and a shading group whose surfaceShader
        is disconnected yields `shaders = []` inside material_claims,
        which `continue`s past that shape with no claim (correct: an
        unconnected surfaceShader means the shape has no readable material,
        not that the walk is broken). The #714 Task 4/5 carried-forward
        risk #2 is CONFIRMED harmless for these two shapes; Task 4's
        try/except around the walk therefore never fires here, but stays
        in place as a backstop for scene shapes this probe did not cover."""
        import maya.cmds as cmds

        from maya_plugin.handlers import texclaim

        # A shading group whose surfaceShader is disconnected - legal to
        # build (sets(noSurfaceShader=True) is exactly this), just unusual.
        disconnected = cmds.ls(
            cmds.polyCube(name="disconnected_cube")[0], long=True)[0]
        sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                       name="disconnectedSG")
        cmds.sets(disconnected, edit=True, forceElement=sg)

        # A mesh with no shading group at all - remove it from every set
        # membership Maya gave it by default.
        bare = cmds.ls(cmds.polyCube(name="bare_cube")[0], long=True)[0]
        for s in cmds.listSets(object=bare, type=1) or []:
            cmds.sets(bare, edit=True, remove=s)
        assert not (cmds.listSets(object=bare, type=1) or [])

        claims = texclaim.material_claims(cmds, [disconnected, bare])
        assert claims == []

    def test_bump2d_aggregates_every_source_not_just_the_recipes_own(
            self, tmp_path):
        """Risk #1, actually proven (#714 Task 5 fix round 1): via==
        ["bump2d"] on the noise_bump recipe's ONE-input bump2d cannot
        distinguish "listConnections on the bare node aggregates EVERY
        source" from "there happened to be exactly one source to find".
        This builds a genuinely two-input bump2d and asserts the claim
        names BOTH upstream nodes.

        MEASURED under mayapy (Maya 2027): bump2d exposes a real, unused
        float input - bumpFilterOffset - that a real Maya bump2d node
        accepts a second texture connection into without complaint
        (bumpDepth, also probed, is equally connectable; bumpFilterOffset
        was picked because the recipe never touches it). After wiring a
        second noise's outColorR into mcpTex_bump.bumpFilterOffset
        alongside the recipe's own noise->bumpValue connection,
        cmds.listConnections("mcpTex_bump", source=True, destination=
        False, plugs=True) - the exact bare-node call _walk_upstream
        makes - returned BOTH source plugs
        ["mcpTex_noise.outColorR", "probe_noise2.outColorR"], and
        texclaim.material_claims's terminals for the normalCamera claim
        were exactly ["mcpTex_noise", "probe_noise2"] with via==
        ["bump2d"], classification "procedural". The aggregation
        assumption the whole walker rests on past a pass-through is
        CONFIRMED, not merely consistent with a single-input case."""
        import maya.cmds as cmds

        from maya_plugin.handlers import export, material, texture_recipes

        mesh = cmds.ls(cmds.polyCube(name="two_in_cube")[0], long=True)[0]
        material.assign_material({"mesh": mesh, "name": "two_in_mat",
                                  "shader": "standardSurface"})
        recipe = texture_recipes.apply_texture_recipe({
            "mesh": mesh, "recipe": "noise_bump"})
        noise1 = [n for n in recipe["nodes"] if "noise" in n][0]
        bump = [n for n in recipe["nodes"] if "bump" in n][0]
        noise2 = cmds.shadingNode("noise", asTexture=True,
                                  name="probe_noise2")
        # An unused float input on the SAME bump2d - not bumpValue, which
        # the recipe already drives. Wiring here (rather than a second
        # slot) is what makes this a two-SOURCE, one-NODE fixture: the
        # walk reaches both through the identical bare-node
        # listConnections("bump2d", ...) call, which is exactly the
        # behaviour risk #1 is about.
        cmds.connectAttr(noise2 + ".outColorR", bump + ".bumpFilterOffset",
                         force=True)

        path = str(tmp_path / "two_input.fbx").replace("\\", "/")
        out = export.export_fbx({"path": path, "metres_per_unit": 1.0,
                                 "nodes": [mesh]})
        dropped = out["textures"]["dropped_maps"]
        terminals = sorted(d["terminal"] for d in dropped)
        assert terminals == sorted([noise1, noise2])
        assert all(d["via"] == ["bump2d"] for d in dropped)


class TestBakeTexturesInMaya:
    """#714 phase 2 against a real exporter. The claim under test is the
    whole point of the ticket: a procedural look that CANNOT survive an
    FBX export does survive once baked."""

    def test_a_baked_noise_survives_the_export_that_dropped_it(self, tmp_path):
        import os

        import maya.cmds as cmds

        from maya_plugin.handlers import (export, material, texbake,
                                          texture_recipes, uvatlas)

        mesh = cmds.ls(cmds.polyCube(name="bake_cube")[0], long=True)[0]
        uvatlas.uv_atlas({"names": [mesh], "project": "box"})
        material.assign_material({"mesh": mesh, "name": "bake_mat",
                                  "shader": "standardSurface"})
        recipe = texture_recipes.apply_texture_recipe({
            "mesh": mesh, "recipe": "ramp_gradient"})
        ramp = [n for n in recipe["nodes"] if "ramp" in n][0]

        # BEFORE: the export drops it and says so (phase 1's report).
        before_path = str(tmp_path / "before.fbx").replace("\\", "/")
        before = export.export_fbx({"path": before_path,
                                    "metres_per_unit": 1.0, "nodes": [mesh]})
        assert [d["terminal"] for d in before["textures"]["dropped_maps"]] \
            == [ramp]

        out_dir = str(tmp_path).replace("\\", "/")
        baked = texbake.bake_textures({"meshes": [mesh], "out_dir": out_dir})
        assert len(baked["baked"]) == 1
        entry = baked["baked"][0]
        assert entry["pixel_check"]["non_uniform"] is True
        assert os.path.isfile(entry["file"])

        # AFTER: nothing is dropped, and the image is IN the bytes.
        after_path = str(tmp_path / "after.fbx").replace("\\", "/")
        after = export.export_fbx({"path": after_path,
                                   "metres_per_unit": 1.0, "nodes": [mesh]})
        assert after["textures"]["dropped_maps"] == []
        names = [m["basename"] for m in after["textures"]["file_maps"]]
        assert entry["basename"] in names
        assert all(m["found_in_file"] for m in after["textures"]["file_maps"])
        with open(after_path, "rb") as fh:
            assert entry["basename"].encode() in fh.read()

    def test_a_baked_scene_passes_require_baked_textures(self, tmp_path):
        """The contract phase 1 gave a delivery gate now has a way to be
        satisfied rather than only refused."""
        import maya.cmds as cmds

        from maya_plugin.handlers import (export, material, texbake,
                                          texture_recipes, uvatlas)

        mesh = cmds.ls(cmds.polyCube(name="strict_bake")[0], long=True)[0]
        uvatlas.uv_atlas({"names": [mesh], "project": "box"})
        material.assign_material({"mesh": mesh, "name": "strict_bake_mat",
                                  "shader": "standardSurface"})
        texture_recipes.apply_texture_recipe({"mesh": mesh,
                                              "recipe": "noise_bump"})
        texbake.bake_textures({"meshes": [mesh],
                               "out_dir": str(tmp_path).replace("\\", "/")})
        path = str(tmp_path / "strict.fbx").replace("\\", "/")
        out = export.export_fbx({"path": path, "metres_per_unit": 1.0,
                                 "nodes": [mesh],
                                 "require_baked_textures": True})
        assert out["textures"]["dropped_maps"] == []

    def test_a_uvless_mesh_is_refused_and_nothing_is_written(self, tmp_path):
        """MEASURED (probe P2c): convertSolidTx does NOT raise here - it
        writes a flat image. The refusal is ours, and it must fire before
        any file appears."""
        import os

        import maya.cmds as cmds
        import pytest as _pytest

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import (material, texbake, texture_recipes)

        mesh = cmds.ls(cmds.polyCube(name="nouv_cube")[0], long=True)[0]
        shape = cmds.listRelatives(mesh, shapes=True, fullPath=True)[0]
        cmds.polyMapDel(shape + ".map[*]")
        material.assign_material({"mesh": mesh, "name": "nouv_mat",
                                  "shader": "standardSurface"})
        texture_recipes.apply_texture_recipe({"mesh": mesh,
                                              "recipe": "ramp_gradient"})
        out_dir = str(tmp_path).replace("\\", "/")
        with _pytest.raises(HandlerError, match="no UVs"):
            texbake.bake_textures({"meshes": [mesh], "out_dir": out_dir})
        assert os.listdir(out_dir) == []

    def test_a_shared_material_bakes_once_for_both_meshes(self, tmp_path):
        """MEASURED (probe P2d/P2e): sampling is mesh-independent, so one
        image serves every wearer - and both meshes must end up reading it."""
        import maya.cmds as cmds

        from maya_plugin.handlers import (material, texbake, texclaim,
                                          texture_recipes, uvatlas)

        a = cmds.ls(cmds.polyCube(name="share_a")[0], long=True)[0]
        b = cmds.ls(cmds.polyCube(name="share_b")[0], long=True)[0]
        for mesh in (a, b):
            uvatlas.uv_atlas({"names": [mesh], "project": "box"})
        material.assign_material({"mesh": a, "name": "shared_mat",
                                  "shader": "standardSurface"})
        material.assign_material({"mesh": b, "name": "shared_mat",
                                  "shader": "standardSurface"})
        texture_recipes.apply_texture_recipe({"mesh": a,
                                              "recipe": "ramp_gradient"})
        out = texbake.bake_textures({"meshes": [a, b],
                                     "out_dir": str(tmp_path).replace("\\", "/")})
        assert len(out["baked"]) == 1
        shapes = [cmds.listRelatives(m, shapes=True, fullPath=True)[0]
                  for m in (a, b)]
        claims = texclaim.material_claims(cmds, shapes)
        assert claims and all(c["classification"] == "file" for c in claims)

    def test_a_shared_terminal_survives_baking_only_one_of_its_two_slots(
            self, tmp_path):
        """Task 3's fix round found this defect by READING the plan's code,
        not by running it: a terminal driving TWO attributes of the SAME
        material (one ramp feeding both baseColor and metalness) looked
        orphaned to the original `_doomed_nodes` because it compared
        destination NODE names, not plugs - baking only the color slot
        would have deleted the ramp and silently broken the un-baked
        metalness wiring. The fix (`_orphan_candidates` + `_sweep_orphans`,
        rewire-then-check-remaining-outputs, fixpoint-iterated) had never
        run against real Maya until this test.

        Builds exactly that shape by hand: ramp_gradient wires
        ramp.outColor -> baseColor as usual, then this test additionally
        wires ramp.outColorR -> metalness (a second, independent
        connection off the SAME node). Baking with slots=["color"] only
        must leave the ramp alive and the metalness connection untouched.

        REAL-MAYA FINDING (a genuine product defect, fixed by this task,
        not merely observed): MEASURED under mayapy (Maya 2027), a freshly
        created `ramp` node with ZERO other wiring already answers
        cmds.listConnections(ramp, destination=True) == ['defaultTextureList1']
        - Maya wires every asTexture=True/asUtility=True node into its own
        bookkeeping list (defaultTextureList1 for textures,
        defaultRenderUtilityList1 for utilities/place2dTexture) at creation
        time, before this tool connects it to anything. `_sweep_orphans`'s
        original "any outgoing connection at all -> survives" check could
        therefore NEVER see an empty list for ANY candidate node type this
        tool ever produces - nothing baked would ever actually be deleted,
        contradicting texbake's own module docstring ("delete the replaced
        chains") on every single bake, not just this shared-terminal case.
        Fixed in texbake.py: `_real_outputs`/`_MAYA_BOOKKEEPING_LIST_TYPES`
        now filter out defaultTextureList/defaultRenderUtilityList
        destinations before deciding survival. The warning text this test
        asserts on ("still used by survive_mat") is the POST-FIX text -
        pre-fix it read "still used by defaultTextureList1, survive_mat"
        for this test AND would have read "still used by defaultTextureList1"
        (with deleted_nodes==[]) even for the ordinary, nothing-else-uses-it
        case the sibling deletion test below now proves actually deletes."""
        import maya.cmds as cmds

        from maya_plugin.handlers import (material, texbake, texclaim,
                                          texture_recipes, uvatlas)

        mesh = cmds.ls(cmds.polyCube(name="survive_cube")[0], long=True)[0]
        uvatlas.uv_atlas({"names": [mesh], "project": "box"})
        # assign_material's explicit-name param is "name". It used to accept
        # (and silently ignore) "material", which is what the rest of this
        # file passed - every one of those tests created a differently-named
        # material than it believed it was creating, and passed anyway
        # because they read the name back out of the result. #764 turned that
        # into a refusal and repointed them all at "name".
        material.assign_material({"mesh": mesh, "name": "survive_mat",
                                  "shader": "standardSurface"})
        recipe = texture_recipes.apply_texture_recipe({
            "mesh": mesh, "recipe": "ramp_gradient"})
        ramp = [n for n in recipe["nodes"] if "ramp" in n][0]
        # The second attribute this same ramp now drives - independent of
        # the recipe's own baseColor wiring, off the same source node.
        cmds.connectAttr(ramp + ".outColorR", "survive_mat.metalness",
                         force=True)

        out_dir = str(tmp_path).replace("\\", "/")
        out = texbake.bake_textures({"meshes": [mesh], "out_dir": out_dir,
                                     "slots": ["color"]})
        assert len(out["baked"]) == 1
        entry = out["baked"][0]
        assert entry["slot"] == "color"

        # The ramp must survive: it still feeds the un-baked metalness slot.
        # MEASURED: the warning names exactly "survive_mat" as the survivor
        # - defaultTextureList1 is filtered out by the bookkeeping-list fix
        # above, so this text proves the ramp is being kept for the REAL
        # reason (metalness), not merely because Maya's own list is still
        # attached to it (which is true of every texture node, always).
        assert cmds.objExists(ramp)
        assert entry["deleted_nodes"] == []
        assert ("%s was not deleted after baking survive_mat.baseColor - "
               "still used by survive_mat" % ramp) in out["warnings"]

        # metalness's wiring is untouched - still reading the same ramp.
        metalness_src = cmds.listConnections(
            "survive_mat.metalness", source=True, destination=False,
            plugs=True) or []
        assert metalness_src == [ramp + ".outColorR"]

        # baseColor, meanwhile, now reads the baked file - not the ramp.
        color_src = cmds.listConnections(
            "survive_mat.baseColor", source=True, destination=False) or []
        assert color_src and color_src[0] != ramp
        assert cmds.nodeType(color_src[0]) == "file"

        # And the postcondition the tool itself enforces agrees: baseColor
        # now claims as file-backed, metalness still claims procedural.
        shape = cmds.listRelatives(mesh, shapes=True, fullPath=True)[0]
        claims = {c["attr"]: c["classification"]
                 for c in texclaim.material_claims(cmds, [shape])}
        assert claims["baseColor"] == "file"
        assert claims["metalness"] == "procedural"

    def test_an_unshared_terminal_is_actually_deleted_after_baking(
            self, tmp_path):
        """The other half of the same real-Maya finding: it is not enough
        for the shared-terminal case to WARN and keep the ramp - the
        ordinary, nothing-else-uses-it case must actually delete it, or
        the bookkeeping-list fix above would just be trading one silent
        wrong answer (never deletes) for a different one (never warns but
        still never deletes). No FakeCmds test can prove this: the fake
        never modelled defaultTextureList1's automatic wiring in the first
        place, so a fake-cmds `_sweep_orphans` unit test cannot tell "the
        real Maya list was correctly filtered out" apart from "there was
        never anything to filter". Only real Maya can show the node is
        actually gone afterwards.

        MEASURED under mayapy (Maya 2027): pre-fix, this exact scenario
        (a lone ramp driving only baseColor, nothing else connected to it
        at all besides Maya's own defaultTextureList1) left the ramp alive
        with deleted_nodes==[] and a spurious "still used by
        defaultTextureList1" warning - the ramp was NEVER actually an
        orphan candidate that could be swept, for any bake, ever. Post-fix:
        deleted_nodes==[ramp], objExists(ramp) is False, and warnings
        carries no "was not deleted" entry for it."""
        import maya.cmds as cmds

        from maya_plugin.handlers import (material, texbake,
                                          texture_recipes, uvatlas)

        mesh = cmds.ls(cmds.polyCube(name="delete_cube")[0], long=True)[0]
        uvatlas.uv_atlas({"names": [mesh], "project": "box"})
        material.assign_material({"mesh": mesh, "name": "delete_mat",
                                  "shader": "standardSurface"})
        recipe = texture_recipes.apply_texture_recipe({
            "mesh": mesh, "recipe": "ramp_gradient"})
        ramp = [n for n in recipe["nodes"] if "ramp" in n][0]

        out = texbake.bake_textures({"meshes": [mesh],
                                     "out_dir": str(tmp_path).replace("\\", "/")})
        assert len(out["baked"]) == 1
        entry = out["baked"][0]
        assert entry["deleted_nodes"] == [ramp]
        assert not cmds.objExists(ramp)
        assert not any(ramp in w for w in out["warnings"])


class TestMeasureClipInMaya:
    """measure_clip (#773): the metrics discriminate on a REAL rig.

    The fixture reproduces the #773 probe: a two-leg walk-in-place clip and
    the same clip with a drifting plant and a popped key. The probe measured
    slide 0.0 vs 0.097 and peak speed 3.39 vs 8.05 on this exact shape.
    NOTE the bend axis: create_skeleton auto-orients local X down the bone,
    so legs swing on rotateY - [rx,0,0] keys would silently twist instead
    (the probe's own first fixture made that mistake).
    """

    JOINTS = [
        {"name": "hips", "position": [0, 1.0, 0]},
        {"name": "L_thigh", "parent": "hips", "position": [0.12, 0.95, 0]},
        {"name": "L_shin", "parent": "L_thigh", "position": [0.12, 0.5, 0]},
        {"name": "L_foot", "parent": "L_shin", "position": [0.12, 0.08, 0.05]},
        {"name": "R_thigh", "parent": "hips", "position": [-0.12, 0.95, 0]},
        {"name": "R_shin", "parent": "R_thigh", "position": [-0.12, 0.5, 0]},
        {"name": "R_foot", "parent": "R_shin", "position": [-0.12, 0.08, 0.05]},
    ]

    @staticmethod
    def _keys(broken):
        import math as m
        out = []
        for i in range(11):
            t = i / 10.0

            def leg(sw_start):
                ph = (t - sw_start) % 1.0
                if ph < 0.5:
                    s = m.sin(ph / 0.5 * m.pi)
                    return (-25.0 * s, 35.0 * s)
                return (0.0, 0.0)

            lt, ls = leg(0.0)
            rt, rs = leg(0.5)
            if broken and t < 0.5:
                rt = 8.0 * (t / 0.5)  # the plant drifts instead of holding
            out.append({"time_s": t, "rotations": {
                "L_thigh": [0, lt, 0], "L_shin": [0, ls, 0],
                "R_thigh": [0, rt, 0], "R_shin": [0, rs, 0]}})
        if broken:
            out[3]["rotations"]["L_thigh"][1] += 40.0  # the pop
        return out

    def _rig_with(self, name, broken):
        import maya.cmds as cmds

        from maya_plugin.handlers import clip, rigging

        cmds.file(new=True, force=True)
        root = rigging.create_skeleton({"joints": self.JOINTS})["root"]
        clip.author_clip({"root": root, "name": name, "fps": 30,
                          "interpolation": "smooth", "loop": True,
                          "keys": self._keys(broken)})
        return root

    def test_a_clean_walk_measures_clean(self):
        from maya_plugin.handlers import clip

        root = self._rig_with("walk", broken=False)
        out = clip.measure_clip({"root": root})  # single clip: name optional
        assert out["name"] == "walk"
        assert out["frames_sampled"] == 31
        assert out["warnings"] == []
        # both feet planted half the cycle, sliding nowhere
        for foot in ("L_foot", "R_foot"):
            assert out["contacts"][foot]["runs"], foot
            assert out["contacts"][foot]["max_slide"] < 1e-4, foot
        # symmetric effort, and the pairing found both mirrored chains
        pairs = {(s["left"], s["right"]) for s in out["symmetry"]}
        assert ("L_foot", "R_foot") in pairs
        assert all(s["peak_speed_ratio"] < 1.05 for s in out["symmetry"])
        # a looping clip closes
        assert out["loop"] is True
        assert out["joints"]["L_foot"]["loop_closure"] < 1e-3

    def test_the_broken_walk_is_named_and_numbered(self):
        from maya_plugin.handlers import clip

        root = self._rig_with("walk", broken=True)
        out = clip.measure_clip({"root": root, "name": "walk"})
        # the drifting plant is WARNED about by joint name
        assert any("R_foot" in w and "SLIDES" in w for w in out["warnings"]), \
            out["warnings"]
        assert out["contacts"]["R_foot"]["max_slide"] > \
            out["thresholds"]["slide_warn"]
        # the pop shows as asymmetry between the mirrored feet
        feet = next(s for s in out["symmetry"]
                    if (s["left"], s["right"]) == ("L_foot", "R_foot"))
        assert feet["peak_speed_ratio"] > 1.5
        # and as a worst-frame the caller can go look at
        popped = out["joints"]["L_foot"]
        clean = clip.measure_clip({"root": self._rig_with("walk", False)})
        assert popped["peak_speed"] > 1.5 * clean["joints"]["L_foot"]["peak_speed"]

    def test_an_unread_param_is_refused(self):
        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import clip

        root = self._rig_with("walk", broken=False)
        with pytest.raises(HandlerError) as exc:
            clip.measure_clip({"root": root, "clip": "walk"})
        assert "does not take 'clip'" in str(exc.value)

    def test_perception_leaves_the_time_where_it_was(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import clip

        root = self._rig_with("walk", broken=False)
        cmds.currentTime(7)
        clip.measure_clip({"root": root})
        assert cmds.currentTime(query=True) == 7


class TestCurveFormInMaya:
    def _build(self, params):
        from maya_plugin.handlers import curveform
        return curveform.create_curve_form(params)

    def test_revolve_vase_is_watertight_and_on_station(self):
        result = self._build({
            "kind": "revolve", "name": "vase",
            "profile": [[0.30, 0.0], [0.50, 0.35], [0.22, 0.80],
                        [0.28, 1.10], [0.20, 1.25]]})
        assert result["watertight"] is True
        assert result["stations"] == 5 * 4
        assert result["worst_station_deviation"] < 0.05
        assert result["faces"] > 0

    def test_sweep_horn_tapers(self):
        import maya.cmds as cmds
        result = self._build({
            "kind": "sweep", "name": "horn",
            "path": [[0, 0, 0], [0.1, 0.5, 0], [0.35, 0.9, 0],
                     [0.7, 1.1, 0.2]],
            "width": [[0.0, 0.30], [1.0, 0.06]]})
        assert result["worst_station_deviation"] < 0.05
        # The taper is real: the mesh near the tip is narrower than the base.
        bbox = cmds.exactWorldBoundingBox(result["name"])
        assert bbox[4] > 1.0  # reached the top of the path (y max)

    def test_loft_torso_passes_through_rings(self):
        rings = []
        for y, r in ((0.0, 0.35), (0.4, 0.45), (0.9, 0.40), (1.3, 0.25)):
            rings.append([[r, y, 0], [0, y, r], [-r, y, 0], [0, y, -r]])
        result = self._build({"kind": "loft", "name": "torso",
                              "sections": rings})
        assert result["worst_station_deviation"] < 0.05
        assert result["watertight"] is True

    def test_no_construction_nodes_survive(self):
        import maya.cmds as cmds
        before_curves = set(cmds.ls(type="nurbsCurve") or [])
        before_surfs = set(cmds.ls(type="nurbsSurface") or [])
        self._build({"kind": "revolve", "name": "cleanup_probe",
                     "profile": [[0.4, 0.0], [0.3, 0.8]]})
        assert set(cmds.ls(type="nurbsCurve") or []) == before_curves
        assert set(cmds.ls(type="nurbsSurface") or []) == before_surfs
        # and no construction history on the mesh itself
        assert not (cmds.listHistory("cleanup_probe",
                                     pruneDagObjects=True) or [])

    def test_placement_happens_after_measurement(self):
        # Stations are authored in the local frame; a translated build must
        # still self-measure clean (regression guard for measure-then-place).
        result = self._build({
            "kind": "revolve", "name": "placed_vase",
            "profile": [[0.4, 0.0], [0.3, 0.8]],
            "translate": [5.0, 0.0, 2.0]})
        assert result["worst_station_deviation"] < 0.05

    def test_twist_has_geometric_effect_and_is_degrees(self):
        # #768 review IMPORTANT 2: `twist` had zero geometric evidence - the
        # inert-param failure class this repo has hit twice (#764 was the
        # first). Build the same square-profile sweep twice on a straight
        # 3-point path up Y, twist=0 vs twist=90, and prove: (1) it is not
        # inert - vertices genuinely move; (2) the ramp is 0 at the path's
        # start and (3) the far end rotates by an amount consistent with
        # DEGREES (~90), not radians, turns, or some other unit.
        #
        # Vertices are compared BY INDEX, not by searching for "whichever
        # vertex is nearest angle X" - a 4-sided profile is symmetric under
        # a 90-degree rotation, so an angle-search marker would find some
        # vertex near the target angle regardless of whether twist did
        # anything at all (measured while designing this test - a
        # nearest-angle search is a false-negative trap here). Index
        # correspondence is guaranteed because twist never changes mesh
        # topology, only vertex positions (see `_apply_twist`).
        import math

        import maya.cmds as cmds

        path = [[0, 0, 0], [0, 1, 0], [0, 2, 0]]
        untwisted = self._build({
            "kind": "sweep", "name": "twist_probe_0",
            "path": path, "width": 1.0, "profile_sides": 4, "twist": 0})
        twisted = self._build({
            "kind": "sweep", "name": "twist_probe_90",
            "path": path, "width": 1.0, "profile_sides": 4, "twist": 90})

        def verts(name):
            flat = cmds.xform(
                name + ".vtx[*]", query=True, translation=True,
                worldSpace=True)
            return [flat[i:i + 3] for i in range(0, len(flat), 3)]

        verts0 = verts(untwisted["name"])
        verts90 = verts(twisted["name"])
        assert len(verts0) == len(verts90)

        # (1) Not inert: some vertex must have moved by more than a tiny
        # epsilon between the twist=0 and twist=90 builds.
        max_displacement = max(
            math.dist(a, b) for a, b in zip(verts0, verts90)
        )
        assert max_displacement > 0.05, (
            "twist=90 produced no meaningful geometric change "
            "(max displacement %.6f) - twist is inert" % max_displacement
        )

        # (2) The ramp starts at 0 degrees: vertices near the path's start
        # (y~=0) must nearly coincide between the two builds.
        near_start = [i for i, v in enumerate(verts0) if v[1] < 0.1]
        assert near_start
        start_disp = max(math.dist(verts0[i], verts90[i]) for i in near_start)
        assert start_disp < 0.05, (
            "twist ramp should be ~0 degrees at the path's start, but a "
            "near-start vertex moved %.6f" % start_disp
        )

        # (3) The far end (y~=2, the top of the path) rotated rigidly by an
        # amount consistent with 90 degrees - not 0 (inert), not some wild
        # multiple (wrong unit, e.g. radians-as-degrees or turns).
        far_end = [i for i, v in enumerate(verts0) if v[1] > 1.9]
        assert far_end

        def angle_about_y(p):
            return math.degrees(math.atan2(p[2], p[0]))

        rotations = []
        for i in far_end:
            a0 = angle_about_y(verts0[i])
            a1 = angle_about_y(verts90[i])
            rotations.append((a1 - a0 + 180.0) % 360.0 - 180.0)  # shortest signed diff
        # Every far-end vertex is part of one rigid ring, so they should all
        # report the same rotation.
        assert max(rotations) - min(rotations) < 5.0, (
            "far-end ring did not rotate rigidly: %r" % rotations
        )
        magnitude = abs(rotations[0])
        assert 60.0 < magnitude < 120.0, (
            "far-end rotation magnitude %.2f degrees is not near 90 for a "
            "twist=90 request - twist does not read as degrees" % magnitude
        )


class TestRetargetFbxNamespaceInMaya:
    """#774 Task 3 review IMPORTANT 2: an FBX imported under `namespace=ns`
    (retarget.py's `_retarget_fbx`) names every joint "ns:Hips", not "Hips" -
    `clip._short()` only strips a DAG PIPE ("|a|b|c" -> "c"), never a
    namespace colon, so matching those names against
    CMU_HIK_MAP/SKELETON_HIK_MAP (bare names) could never succeed before the
    fix: EVERY namespaced FBX import fell into the "not a known mocap
    convention" refusal, regardless of the file's actual joint names.

    No FBX mocap fixture ships with this repo (only the CMU .bvh fixtures,
    Task 2), so this builds a real, tiny, CMU-named source skeleton by hand,
    exports it to a real FBX via Maya's own exporter, and re-imports it
    through the full public `retarget_clip` FBX route - proving the
    namespace-strip fix end to end rather than unit-testing a private
    helper in isolation.
    """

    SOURCE_JOINTS = [
        ("Hips", None, (0.0, 1.0, 0.0)),
        ("Spine", "Hips", (0.0, 1.2, 0.0)),
        ("LeftArm", "Spine", (0.2, 1.4, 0.0)),
        ("LeftForeArm", "LeftArm", (0.5, 1.4, 0.0)),
        ("LeftHand", "LeftForeArm", (0.8, 1.4, 0.0)),
        ("RightArm", "Spine", (-0.2, 1.4, 0.0)),
        ("RightForeArm", "RightArm", (-0.5, 1.4, 0.0)),
        ("RightHand", "RightForeArm", (-0.8, 1.4, 0.0)),
        ("Head", "Spine", (0.0, 1.6, 0.0)),
        ("LeftUpLeg", "Hips", (0.15, 0.9, 0.0)),
        ("LeftLeg", "LeftUpLeg", (0.15, 0.5, 0.0)),
        ("LeftFoot", "LeftLeg", (0.15, 0.1, 0.0)),
        ("RightUpLeg", "Hips", (-0.15, 0.9, 0.0)),
        ("RightLeg", "RightUpLeg", (-0.15, 0.5, 0.0)),
        ("RightFoot", "RightLeg", (-0.15, 0.1, 0.0)),
    ]
    # A minimal target biped naming exactly SKELETON_HIK_MAP's 15 required
    # slots (create_skeleton's own naming convention, #668).
    TARGET_JOINTS = [
        {"name": "pelvis", "position": [0.0, 1.0, 0.0]},
        {"name": "spine_01", "position": [0.0, 1.2, 0.0], "parent": "pelvis"},
        {"name": "L_shoulder", "position": [0.2, 1.4, 0.0], "parent": "spine_01"},
        {"name": "L_elbow", "position": [0.5, 1.4, 0.0], "parent": "L_shoulder"},
        {"name": "L_wrist", "position": [0.8, 1.4, 0.0], "parent": "L_elbow"},
        {"name": "R_shoulder", "position": [-0.2, 1.4, 0.0], "parent": "spine_01"},
        {"name": "R_elbow", "position": [-0.5, 1.4, 0.0], "parent": "R_shoulder"},
        {"name": "R_wrist", "position": [-0.8, 1.4, 0.0], "parent": "R_elbow"},
        {"name": "head", "position": [0.0, 1.6, 0.0], "parent": "spine_01"},
        {"name": "L_hip", "position": [0.15, 0.9, 0.0], "parent": "pelvis"},
        {"name": "L_knee", "position": [0.15, 0.5, 0.0], "parent": "L_hip"},
        {"name": "L_ankle", "position": [0.15, 0.1, 0.0], "parent": "L_knee"},
        {"name": "R_hip", "position": [-0.15, 0.9, 0.0], "parent": "pelvis"},
        {"name": "R_knee", "position": [-0.15, 0.5, 0.0], "parent": "R_hip"},
        {"name": "R_ankle", "position": [-0.15, 0.1, 0.0], "parent": "R_knee"},
    ]

    def _export_cmu_like_fbx(self, tmp_path):
        import maya.cmds as cmds
        import maya.mel as mel

        from maya_plugin.handlers import export as export_mod

        created = {}
        for jname, parent, pos in self.SOURCE_JOINTS:
            if parent is None:
                cmds.select(clear=True)
            else:
                cmds.select(created[parent], replace=True)
            created[jname] = cmds.joint(name=jname, position=pos)
        # Two keys on two different channels so the exported FBX carries
        # real, non-degenerate animation curves.
        cmds.setKeyframe(created["Hips"], attribute="translateX", time=1, value=0)
        cmds.setKeyframe(created["Hips"], attribute="translateX", time=10, value=1)
        cmds.setKeyframe(created["LeftUpLeg"], attribute="rotateX", time=1, value=0)
        cmds.setKeyframe(created["LeftUpLeg"], attribute="rotateX", time=10, value=20)

        cmds.loadPlugin("fbxmaya", quiet=True)
        # fbxmaya's export options are PROCESS-GLOBAL, not reset by
        # cmds.file(new=True) - an earlier test elsewhere in this shared
        # mayapy session (export.py's own FBX_ANIM_MEL[False] path, a
        # static/no-animation export) can leave animation baking turned
        # OFF, which silently drops every keyframe from THIS export with
        # no error at all - measured directly: a bare `cmds.file(...,
        # type="FBX export")` call after such a test produced a valid FBX
        # with zero keyframes, and only this explicit reset fixed it.
        # `FBX_PREAMBLE_MEL` starts with `FBXResetExport`; `FBX_ANIM_MEL[True]`
        # is export.py's own animation-on incantation (and the specific
        # `FBXExportBakeResampleAnimation` requirement export.py's own
        # comment documents measuring) - reused rather than re-derived.
        for statement in export_mod.FBX_PREAMBLE_MEL + export_mod.FBX_ANIM_MEL[True]:
            mel.eval(statement)
        cmds.select(list(created.values()), replace=True)
        path = str(tmp_path / "cmu_like_source.fbx").replace("\\", "/")
        cmds.file(path, force=True, options="v=0", type="FBX export",
                 pr=True, es=True)
        return path

    def test_namespaced_import_resolves_past_the_convention_refusal(
            self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import retarget, rigging

        fbx_path = self._export_cmu_like_fbx(tmp_path)
        assert (tmp_path / "cmu_like_source.fbx").exists()

        # A fresh scene for the actual retarget - the skeleton above only
        # existed to produce the FBX file.
        cmds.file(new=True, force=True)
        skel = rigging.create_skeleton({"joints": self.TARGET_JOINTS})

        try:
            result = retarget.retarget_clip(
                {"file": fbx_path, "root": skel["root"], "clip": "fbxtest"})
        except HandlerError as exc:
            # The bug this test targets made EVERY namespaced FBX import
            # fail with exactly this refusal, regardless of the file's
            # actual joint names - so this is the one failure the fix must
            # rule out. A later failure for some OTHER stated reason would
            # still be a regression in the fix, so nothing further is
            # asserted here (see the "full success" branch below - this
            # skeleton is well-formed, so no such later failure exists).
            assert "not a known mocap convention" not in str(exc), (
                "the namespace-stripping fix regressed: FBX import is "
                "still being refused as an unrecognized convention: %s"
                % exc)
            raise
        # This skeleton is a complete, valid 15-slot CMU-named biped with
        # real keyframes, so the fix should carry it all the way through:
        # full success, not just "got past the first refusal".
        assert result["clip"] == "fbxtest"
        assert result["source_joints"] == len(self.SOURCE_JOINTS)
        assert result["frames"] > 0

        # Teardown discipline applies here too - nothing HIK-typed, no
        # mocap_src_* leftovers, same as the BVH route.
        leftover_hik = sorted({
            n for t in ("HIKCharacterNode", "HIKProperty2State",
                       "HIKSolverNode", "HIKState2SK", "HIKRetargeterNode",
                       "HIKState2FK", "HIKCharacterStateClient")
            for n in (cmds.ls(type=t) or [])})
        assert not leftover_hik, leftover_hik
        assert not [n for n in (cmds.ls(long=True) or []) if "mocap_src_" in n]


_MOCAP_FIXTURES = os.path.join(
    os.path.dirname(__file__), "..", "evals", "mocap_fixtures")


@pytest.mark.skipif(
    not os.path.exists(os.path.join(_MOCAP_FIXTURES, "cmu_walk.bvh")),
    reason="CMU fixtures not stocked yet")
class TestRetargetInMaya:
    """#774 Task 4: retarget_clip against REAL Maya, a real biped, and the
    real CMU BVH fixtures (#774 Task 2) - the proof Task 7 builds on.

    Same skip guard as `TestCmuFixtures` in test_mocapmath.py: these fixtures
    ship with the repo (evals/mocap_fixtures/), so the guard is defensive,
    not expected to actually skip in this checkout.
    """

    # create_skeleton's biped params, copied VERBATIM from evals/
    # humanoid_live.py's JOINTS (#668) - the same 20-joint naming
    # mocapmath.SKELETON_HIK_MAP's targets are drawn from.
    JOINTS = [
        {"name": "pelvis",     "position": [0.0,  1.00, 0.0]},
        {"name": "spine_01",   "position": [0.0,  1.15, 0.0], "parent": "pelvis"},
        {"name": "spine_02",   "position": [0.0,  1.30, 0.0], "parent": "spine_01"},
        {"name": "chest",      "position": [0.0,  1.45, 0.0], "parent": "spine_02"},
        {"name": "neck",       "position": [0.0,  1.60, 0.0], "parent": "chest"},
        {"name": "head",       "position": [0.0,  1.72, 0.0], "parent": "neck"},
        {"name": "L_shoulder", "position": [0.22, 1.50, 0.0], "parent": "chest"},
        {"name": "L_elbow",    "position": [0.45, 1.50, 0.0], "parent": "L_shoulder"},
        {"name": "L_wrist",    "position": [0.68, 1.50, 0.0], "parent": "L_elbow"},
        {"name": "R_shoulder", "position": [-0.22, 1.50, 0.0], "parent": "chest"},
        {"name": "R_elbow",    "position": [-0.45, 1.50, 0.0], "parent": "R_shoulder"},
        {"name": "R_wrist",    "position": [-0.68, 1.50, 0.0], "parent": "R_elbow"},
        {"name": "L_hip",      "position": [0.10, 0.95, 0.0], "parent": "pelvis"},
        {"name": "L_knee",     "position": [0.10, 0.50, 0.0], "parent": "L_hip"},
        {"name": "L_ankle",    "position": [0.10, 0.08, 0.0], "parent": "L_knee"},
        {"name": "L_toe",      "position": [0.10, 0.02, 0.14], "parent": "L_ankle"},
        {"name": "R_hip",      "position": [-0.10, 0.95, 0.0], "parent": "pelvis"},
        {"name": "R_knee",     "position": [-0.10, 0.50, 0.0], "parent": "R_hip"},
        {"name": "R_ankle",    "position": [-0.10, 0.08, 0.0], "parent": "R_knee"},
        {"name": "R_toe",      "position": [-0.10, 0.02, 0.14], "parent": "R_ankle"},
    ]

    def _biped(self):
        from maya_plugin.handlers import rigging

        return rigging.create_skeleton({"joints": self.JOINTS})["root"]

    def test_walk_retargets_and_registers_as_clip(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import clip, retarget

        root = self._biped()
        result = retarget.retarget_clip({
            "file": "evals/mocap_fixtures/cmu_walk.bvh",
            "root": root, "clip": "cmuwalk"})
        assert result["frames"] > 30
        assert result["measures"]  # self-measured

        # the clip is a REAL phase-6 clip: metadata visible to clip tools
        records = clip.clip_meta(cmds, result["root"])
        assert any(r.get("name") == "cmuwalk" for r in records)

    def test_motion_actually_transferred(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import retarget

        root = self._biped()
        result = retarget.retarget_clip({
            "file": "evals/mocap_fixtures/cmu_walk.bvh",
            "root": root, "clip": "cmuwalk2"})
        hips = result["root"]
        p0 = cmds.getAttr(hips + ".translateX", time=1)
        pN = cmds.getAttr(hips + ".translateX", time=40)
        assert abs(pN - p0) > 0.01  # a walk MOVES

    def test_nothing_survives_but_keys(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import retarget

        root = self._biped()
        retarget.retarget_clip({
            "file": "evals/mocap_fixtures/cmu_idle.bvh",
            "root": root, "clip": "cmuidle"})
        assert not cmds.ls("mocap_src_*", long=True)
        assert not [n for n in (cmds.ls(long=True) or [])
                    if cmds.nodeType(n) in retarget._HIK_NODE_TYPES]

    def test_non_biped_target_refused_naming_slots(self):
        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import retarget, rigging

        chain = rigging.create_skeleton({
            "joints": [
                {"name": "a", "position": [0, 0, 0]},
                {"name": "b", "position": [0, 1, 0], "parent": "a"}]})
        with pytest.raises(HandlerError, match="LeftFoot"):
            retarget.retarget_clip({
                "file": "evals/mocap_fixtures/cmu_walk.bvh",
                "root": chain["root"], "clip": "nope"})

    def test_characterize_failure_leaves_nothing_behind(self, monkeypatch):
        """The fix round's throwaway smoke-script proof
        (task-3-report.md's "Review-fix pass", CRITICAL 1), committed as a
        real regression test: force a mid-characterize failure through the
        PUBLIC `retarget_clip()` entry point by monkeypatching an invalid
        HumanIK slot id into `retarget._HIK_SLOT_IDS` for one slot -
        `setCharacterObject` fails on that slot, strictly AFTER
        `hikCreateCharacter` already built real nodes, exactly the window
        #774 review CRITICAL 1 found leaking. A refusal here must still
        leave the scene exactly as clean as a successful call's teardown
        does - no source namespace, no HIK-typed node of any kind, and (the
        `_HIK_NODE_TYPES` sweep alone cannot see this) no stray keys landed
        on the target rig's own joints either.
        """
        import maya.cmds as cmds

        from maya_plugin.handlers import retarget

        root = self._biped()
        monkeypatch.setitem(retarget._HIK_SLOT_IDS, "Head", 9999)

        target_joints = cmds.ls(
            cmds.listRelatives(root, allDescendents=True, type="joint",
                              fullPath=True) or [], long=True) + [root]
        before_keys = {j: cmds.keyframe(j, query=True) for j in target_joints}

        with pytest.raises(retarget.HandlerError):
            retarget.retarget_clip({
                "file": "evals/mocap_fixtures/cmu_walk.bvh",
                "root": root, "clip": "cmufail"})

        assert not cmds.ls("mocap_src_*", long=True)
        assert not [n for n in (cmds.ls(long=True) or [])
                    if cmds.nodeType(n) in retarget._HIK_NODE_TYPES]
        after_keys = {j: cmds.keyframe(j, query=True) for j in target_joints}
        assert after_keys == before_keys


class TestCleanClipInMaya:
    """clean_clip (#774 Task 5): filter + contact-lock, proven against a
    REAL biped carrying a DELIBERATELY dirty clip - one foot that drifts
    during its own plant (a measurable SLIDE, #773's own metric) and one
    elbow channel jittering on alternating frames (a popped-key stand-in,
    the #773 probe's own defect shape). Both defects are numbers before
    this call and smaller numbers after it - the whole point of #774's
    "motion has numbers now" arc (see MEMORY.md).
    """

    # create_skeleton's biped params, copied VERBATIM from evals/
    # humanoid_live.py's JOINTS (#668) - the same 20-joint naming
    # mocapmath.SKELETON_HIK_MAP's targets are drawn from, and the exact
    # shape TestRetargetInMaya already proved against a real HumanIK bake.
    JOINTS = [
        {"name": "pelvis",     "position": [0.0,  1.00, 0.0]},
        {"name": "spine_01",   "position": [0.0,  1.15, 0.0], "parent": "pelvis"},
        {"name": "spine_02",   "position": [0.0,  1.30, 0.0], "parent": "spine_01"},
        {"name": "chest",      "position": [0.0,  1.45, 0.0], "parent": "spine_02"},
        {"name": "neck",       "position": [0.0,  1.60, 0.0], "parent": "chest"},
        {"name": "head",       "position": [0.0,  1.72, 0.0], "parent": "neck"},
        {"name": "L_shoulder", "position": [0.22, 1.50, 0.0], "parent": "chest"},
        {"name": "L_elbow",    "position": [0.45, 1.50, 0.0], "parent": "L_shoulder"},
        {"name": "L_wrist",    "position": [0.68, 1.50, 0.0], "parent": "L_elbow"},
        {"name": "R_shoulder", "position": [-0.22, 1.50, 0.0], "parent": "chest"},
        {"name": "R_elbow",    "position": [-0.45, 1.50, 0.0], "parent": "R_shoulder"},
        {"name": "R_wrist",    "position": [-0.68, 1.50, 0.0], "parent": "R_elbow"},
        {"name": "L_hip",      "position": [0.10, 0.95, 0.0], "parent": "pelvis"},
        {"name": "L_knee",     "position": [0.10, 0.50, 0.0], "parent": "L_hip"},
        {"name": "L_ankle",    "position": [0.10, 0.08, 0.0], "parent": "L_knee"},
        {"name": "L_toe",      "position": [0.10, 0.02, 0.14], "parent": "L_ankle"},
        {"name": "R_hip",      "position": [-0.10, 0.95, 0.0], "parent": "pelvis"},
        {"name": "R_knee",     "position": [-0.10, 0.50, 0.0], "parent": "R_hip"},
        {"name": "R_ankle",    "position": [-0.10, 0.08, 0.0], "parent": "R_knee"},
        {"name": "R_toe",      "position": [-0.10, 0.02, 0.14], "parent": "R_ankle"},
    ]

    @staticmethod
    def _keys():
        # Same walk-in-place shape TestMeasureClipInMaya's fixture proved
        # (#773): each leg swings hip+knee on rotateY (create_skeleton
        # auto-orients local X down the bone, so [rx,0,0] would silently
        # twist instead - the probe's own first-fixture mistake), half a
        # cycle out of phase, planted the other half. R's plant is
        # deliberately broken: instead of holding rt=0, it ramps 0->8
        # degrees - a straight ~0.87m hip-to-ankle chain swept 8 degrees
        # moves the ankle ~12cm sideways, at a speed still well under the
        # contact-speed threshold (0.35 * rig_height), so it still reads
        # as "planted" - just planted somewhere that keeps moving.
        import math as m
        out = []
        for i in range(11):
            t = i / 10.0

            def leg(sw_start):
                ph = (t - sw_start) % 1.0
                if ph < 0.5:
                    s = m.sin(ph / 0.5 * m.pi)
                    return (-25.0 * s, 35.0 * s)
                return (0.0, 0.0)

            lt, ls = leg(0.0)
            rt, rs = leg(0.5)
            if t < 0.5:
                rt = 8.0 * (t / 0.5)  # the plant drifts instead of holding
            # A genuine, smooth arm swing for L_elbow - the jitter added on
            # top of THIS in _dirty_rig (not onto a flat zero) is what makes
            # "acceleration improved" a meaningful check: a real signal's
            # own frame-to-frame speed already varies, so measuring "did
            # noise get removed" needs noise riding on real motion, not a
            # bare square wave (whose own discrete accel is exactly 0 - a
            # perfectly periodic same-magnitude alternation has CONSTANT
            # frame-to-frame speed by construction, found while designing
            # this fixture: max_accel measured 0.0 on a bare +12/-12
            # alternation with no base signal underneath it).
            elbow = 15.0 * m.sin(2.0 * m.pi * t)
            out.append({"time_s": t, "rotations": {
                "L_hip": [0, lt, 0], "L_knee": [0, ls, 0],
                "R_hip": [0, rt, 0], "R_knee": [0, rs, 0],
                "L_elbow": [0, elbow, 0]}})
        return out

    def _ankle_names(self, cmds, root):
        joints = cmds.ls(cmds.listRelatives(
            root, allDescendents=True, type="joint", fullPath=True) or [],
            long=True) + [root]
        by_short = {j.rsplit("|", 1)[-1]: j for j in joints}
        return [by_short["L_ankle"], by_short["R_ankle"]]

    def _dirty_rig(self, tmp_path, name="walk"):
        import maya.cmds as cmds

        from maya_plugin.handlers import clip, rigging

        cmds.file(new=True, force=True)
        # A real path (unsaved is fine - session.auto_checkpoint only
        # needs a directory to resolve against, matching the existing
        # checkpoint-round-trip precedent at
        # TestSessionInMaya.test_checkpoint_id_restores_and_error_hint_names_it).
        cmds.file(rename=str(tmp_path / "cleanclipcp.ma"))
        root = rigging.create_skeleton({"joints": self.JOINTS})["root"]
        authored = clip.author_clip({
            "root": root, "name": name, "fps": 30,
            "interpolation": "smooth", "keys": self._keys()})
        start, end = authored["start_frame"], authored["end_frame"]
        elbow = [j for j in cmds.ls(type="joint", long=True)
                 if j.endswith("|L_elbow")][0]
        # Alternating-frame jitter ON TOP of the smooth swing author_clip
        # just keyed - a popped key on every other frame, the #773 probe's
        # own defect shape - never authored via author_clip itself (which
        # would try to pin/back-fill it), directly via setKeyframe the way
        # a bad mocap import or a hand-editing mistake would leave it.
        # Left off the outermost 2 frames each side: mocapmath.smooth_track
        # shrinks its window at the very ends of the track down to a
        # 1-point (then a 3-point, exactly-determined) fit, which cannot
        # reduce noise AT those exact samples - jitter placed there would
        # measure "improved" against a boundary artifact instead of the
        # filter's real effect on the interior.
        base_values = {f: cmds.getAttr(elbow + ".rotateY", time=f)
                      for f in range(start, end + 1)}
        for frame in range(start + 2, end - 1):
            jitter = 12.0 if frame % 2 == 0 else -12.0
            cmds.setKeyframe(elbow, attribute="rotateY", time=frame,
                             value=base_values[frame] + jitter)
        return root

    def test_filter_and_lock_contacts_both_improve_measured_numbers(
            self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import cleanclip

        root = self._dirty_rig(tmp_path)
        ankles = self._ankle_names(cmds, root)
        result = cleanclip.clean_clip({"root": root, "clip": "walk"})

        assert result["clip"] == "walk"
        assert result["root"] == root
        assert set(result["passes"]) == {"filter", "lock_contacts"}
        assert result["checkpoint_id"]

        before, after = result["before"], result["after"]
        # the deliberately-drifted plant slides less after locking - #773's
        # own metric, on the exact joint the fixture broke.
        assert before["contacts"]["R_ankle"]["max_slide"] > 0.02
        assert (after["contacts"]["R_ankle"]["max_slide"]
                < before["contacts"]["R_ankle"]["max_slide"])
        # the jittered elbow channel's effect shows up in its CHILD's
        # world kinematics (a joint's own rotation never moves its own
        # pivot, only what hangs below it) - measured on L_wrist. A
        # Savitzky-Golay smooth cannot remove a real signal's own
        # acceleration, only alternating-frame noise on top of it.
        assert before["joints"]["L_wrist"]["max_accel"] > 0
        assert (after["joints"]["L_wrist"]["max_accel"]
                < before["joints"]["L_wrist"]["max_accel"])
        # the OTHER foot was never broken - locking must not make it worse.
        assert (after["contacts"]["L_ankle"]["max_slide"]
                <= before["contacts"]["L_ankle"]["max_slide"] + 1e-6)
        assert ankles == sorted(ankles)  # sanity: both feet were resolved

    def test_checkpoint_id_restores_to_the_measured_before_state(
            self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import cleanclip, clip, session

        root = self._dirty_rig(tmp_path)
        ankles = self._ankle_names(cmds, root)
        result = cleanclip.clean_clip({"root": root, "clip": "walk"})
        before = result["before"]

        session.restore_checkpoint({"checkpoint_id": result["checkpoint_id"]})
        restored = clip.measure_clip({"root": root, "name": "walk",
                                      "contact_joints": ankles})

        assert abs(restored["contacts"]["R_ankle"]["max_slide"]
                  - before["contacts"]["R_ankle"]["max_slide"]) < 1e-4
        assert abs(restored["joints"]["L_wrist"]["max_accel"]
                  - before["joints"]["L_wrist"]["max_accel"]) < 1e-3

    def test_filter_only_leaves_contacts_untouched_by_the_lock_pass(
            self, tmp_path):
        # passes reports only what actually ran - lock_contacts=false means
        # no IK solve touches the legs at all, so the (still broken) slide
        # is unchanged, not improved.
        import maya.cmds as cmds

        from maya_plugin.handlers import cleanclip

        root = self._dirty_rig(tmp_path)
        ankles = self._ankle_names(cmds, root)
        result = cleanclip.clean_clip(
            {"root": root, "clip": "walk", "lock_contacts": False})

        assert result["passes"] == ["filter"]
        before, after = result["before"], result["after"]
        # the drift is NOT locked - it may shift a little from the filter
        # pass smoothing R_hip/R_knee's own curves, but it stays broken,
        # nowhere near the ~10x reduction the full (filter + lock) call
        # measures in the sibling test above.
        assert before["contacts"]["R_ankle"]["max_slide"] > 0.05
        assert after["contacts"]["R_ankle"]["max_slide"] > 0.05
        assert (after["joints"]["L_wrist"]["max_accel"]
                < before["joints"]["L_wrist"]["max_accel"])

    def test_shallow_contact_joint_refuses_before_any_mutation(
            self, tmp_path):
        # #774 Task 5 review IMPORTANT: a contact joint too shallow for a
        # 2-bone chain must be caught BEFORE the checkpoint and BEFORE the
        # filter pass mutates anything - not from inside the already-
        # mutating contact-lock pass, which would leave a refused call with
        # no checkpoint_id to recover through AND a half-filtered scene.
        # L_hip hangs directly under this rig's root (pelvis) - only one
        # joint up, not the two a 2-bone hip/knee/ankle chain needs (the
        # same shape pose_ik itself refuses on a 2-joint chain).
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import cleanclip, clip, session

        root = self._dirty_rig(tmp_path)
        ankles = self._ankle_names(cmds, root)
        all_joints = cmds.ls(type="joint", long=True)
        before_measure = clip.measure_clip(
            {"root": root, "name": "walk", "contact_joints": ankles})
        before_keys = {j: cmds.keyframe(j, query=True) for j in all_joints}
        cp_dir = session._checkpoint_dir(cmds)
        before_checkpoints = session._existing(cp_dir)

        with pytest.raises(HandlerError, match="hangs directly under the root"):
            cleanclip.clean_clip({
                "root": root, "clip": "walk",
                "lock_contacts": {"joints": ["L_hip"]}})

        # no checkpoint was created ...
        assert session._existing(cp_dir) == before_checkpoints
        # ... no key on any joint changed ...
        after_keys = {j: cmds.keyframe(j, query=True) for j in all_joints}
        assert after_keys == before_keys
        # ... and re-measuring the clip matches the pre-call measurement
        # exactly (nothing moved, so nothing should even be a float away).
        after_measure = clip.measure_clip(
            {"root": root, "name": "walk", "contact_joints": ankles})
        assert after_measure == before_measure


class TestBakeMeshMapsInMaya:
    """#770 against real Arnold. The claim under test is the ticket's own:
    the bake captures what only GEOMETRY knows - a box resting on a plane
    darkens the plane's AO exactly under itself (probe S3 measured 3.9
    under vs 251.1 away), and the composite carries that into the colour
    map the export ships."""

    def _plane_under_box(self):
        import maya.cmds as cmds

        plane = cmds.ls(cmds.polyPlane(name="ground", width=10, height=10,
                                       constructionHistory=False)[0],
                        long=True)[0]
        box = cmds.polyCube(name="crate", width=2, height=2, depth=2,
                            constructionHistory=False)[0]
        cmds.setAttr(box + ".translateY", 1.0)
        return plane

    def _region_mean(self, path, u0, u1, v0, v1):
        from maya_plugin.handlers import pngprobe

        png = pngprobe.read_png(path)
        w, h, px = png["width"], png["height"], png["pixels"]
        vals = [px[y * w + x][0]
                for y in range(h) for x in range(w)
                if u0 <= (x + 0.5) / w <= u1
                and v0 <= 1.0 - (y + 0.5) / h <= v1]
        return sum(vals) / max(len(vals), 1)

    def test_ao_darkens_under_a_resting_box(self, tmp_path):
        from maya_plugin.handlers import meshmaps

        plane = self._plane_under_box()
        out = meshmaps.bake_mesh_maps({
            "meshes": [plane], "out_dir": str(tmp_path), "maps": ["ao"],
            "resolution": 256})
        entry = out["baked"][0]
        assert entry["stats"]["non_uniform"] is True
        assert entry["stats"]["blank"] is False
        under = self._region_mean(entry["file"], 0.4, 0.6, 0.4, 0.6)
        away = self._region_mean(entry["file"], 0.0, 0.15, 0.0, 0.15)
        assert under < away - 100, (under, away)

    def test_curvature_and_normal_are_non_flat_on_shaped_geometry(
            self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import meshmaps, uvatlas

        cube = cmds.ls(cmds.polyCube(name="edgy", width=2, height=2,
                                     depth=2,
                                     constructionHistory=False)[0],
                       long=True)[0]
        cmds.polyBevel3(cube, offset=0.15, segments=2,
                        constructionHistory=False)
        uvatlas.uv_atlas({"names": [cube], "project": "box"})
        out = meshmaps.bake_mesh_maps({
            "meshes": [cube], "out_dir": str(tmp_path),
            "maps": ["curvature", "world_normal"], "resolution": 256})
        by_map = {b["map"]: b for b in out["baked"]}
        assert by_map["curvature"]["stats"]["non_uniform"] is True
        assert by_map["world_normal"]["stats"]["non_uniform"] is True

    def test_no_temp_shader_survives_a_bake(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import meshmaps

        plane = self._plane_under_box()
        before = set(cmds.ls(type=("aiAmbientOcclusion", "aiCurvature",
                                   "aiUtility")) or [])
        meshmaps.bake_mesh_maps({
            "meshes": [plane], "out_dir": str(tmp_path),
            "resolution": 256})
        after = set(cmds.ls(type=("aiAmbientOcclusion", "aiCurvature",
                                  "aiUtility")) or [])
        assert after == before

    def test_a_uv_less_mesh_refuses_upfront(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import meshmaps

        cube = cmds.ls(cmds.polyCube(name="naked",
                                     constructionHistory=False)[0],
                       long=True)[0]
        shape = cmds.listRelatives(cube, shapes=True, fullPath=True)[0]
        cmds.polyMapDel(shape + ".map[*]")
        with pytest.raises(HandlerError, match="no UVs"):
            meshmaps.bake_mesh_maps({"meshes": [cube],
                                     "out_dir": str(tmp_path),
                                     "maps": ["ao"]})
        assert not [f for f in os.listdir(str(tmp_path))]

    def test_apply_ao_rewires_a_plain_colour_to_a_darkened_file(
            self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import material, meshmaps, texclaim

        plane = self._plane_under_box()
        material.assign_material({"mesh": plane, "name": "ground_mat",
                                  "shader": "standardSurface"})
        cmds.setAttr("ground_mat.baseColor", 0.8, 0.8, 0.8,
                     type="double3")
        out = meshmaps.bake_mesh_maps({
            "meshes": [plane], "out_dir": str(tmp_path), "maps": ["ao"],
            "resolution": 256, "apply_ao": True})
        assert out["checkpoint_id"]
        applied = out["applied"][0]
        assert applied["material"] == "ground_mat"
        assert os.path.isfile(applied["file"])

        # the slot really reads the composite now
        shape = cmds.listRelatives(plane, shapes=True, fullPath=True)[0]
        claims = texclaim.material_claims(cmds, [shape])
        claim = next(c for c in claims
                     if c["material"] == "ground_mat"
                     and c["attr"] == "baseColor")
        assert claim["classification"] == "file"
        assert claim["terminals"][0]["file_path"].replace("\\", "/") \
            == applied["file"].replace("\\", "/")

        # and the composite is DARKER under the box than away from it -
        # the contact shadow is in the colour map itself
        under = self._region_mean(applied["file"], 0.4, 0.6, 0.4, 0.6)
        away = self._region_mean(applied["file"], 0.0, 0.15, 0.0, 0.15)
        assert under < away - 100, (under, away)

    def test_apply_ao_composites_onto_a_file_base_without_touching_it(
            self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import material, meshmaps, pngwrite

        plane = self._plane_under_box()
        material.assign_material({"mesh": plane, "name": "kit_mat",
                                  "shader": "standardSurface"})
        base_path = str(tmp_path / "kit_albedo.png")
        pngwrite.write_png(base_path, 4, 4, [(200, 100, 50)] * 16)
        base_bytes = open(base_path, "rb").read()
        file_node = cmds.shadingNode("file", asTexture=True,
                                     name="kit_albedo_file")
        cmds.setAttr(file_node + ".fileTextureName", base_path,
                     type="string")
        cmds.connectAttr(file_node + ".outColor", "kit_mat.baseColor",
                         force=True)

        out = meshmaps.bake_mesh_maps({
            "meshes": [plane], "out_dir": str(tmp_path), "maps": ["ao"],
            "resolution": 256, "apply_ao": True})
        applied = out["applied"][0]
        assert applied["replaced_file"].replace("\\", "/") \
            == base_path.replace("\\", "/")
        # the input atlas is byte-identical - never overwritten
        assert open(base_path, "rb").read() == base_bytes
        # the old file node was orphaned by the rewire and swept
        assert not cmds.objExists(file_node)
        # away from the box, the composite keeps the base hue (scaled by
        # open-sky AO ~1.0): red channel stays dominant
        away = self._region_mean(applied["file"], 0.0, 0.1, 0.0, 0.1)
        assert away > 150


class TestApplySurfaceDetailInMaya:
    """#775 task 5 against real Arnold bakes. wear/grime ride the SAME
    curvature/ao masks meshmaps.bake_mesh_maps produces from real geometry
    (#770); grain wires a real bump2d height network. The claim under
    test is directional: colour change concentrates where the geometry
    signal says it should, not merely "some pixels changed"."""

    def _beveled_cube(self, name):
        import maya.cmds as cmds

        from maya_plugin.handlers import uvatlas

        cube = cmds.ls(cmds.polyCube(name=name, width=2, height=2, depth=2,
                                     constructionHistory=False)[0],
                       long=True)[0]
        cmds.polyBevel3(cube, offset=0.15, segments=2,
                        constructionHistory=False)
        # cols=1, rows=1: the mesh fills the WHOLE UV tile rather than the
        # default's one-of-16 patch - a bake's unmapped canvas gets a
        # dilated background fill (meshmaps extend_edges) that dilutes a
        # per-texel mask correlation if most of the canvas is background,
        # not geometry (measured while tuning this test's ratio bar).
        uvatlas.uv_atlas({"names": [cube], "project": "box", "cols": 1,
                          "rows": 1})
        return cube

    def _plane_under_box(self, plane_name="ground", box_name="crate"):
        import maya.cmds as cmds

        plane = cmds.ls(cmds.polyPlane(name=plane_name, width=10, height=10,
                                       constructionHistory=False)[0],
                        long=True)[0]
        box = cmds.polyCube(name=box_name, width=2, height=2, depth=2,
                            constructionHistory=False)[0]
        cmds.setAttr(box + ".translateY", 1.0)
        return plane

    def _beveled_box_on_plane(self, plane_name="ground", box_name="crate"):
        """A beveled box resting on a plane: the box carries both a real
        curvature signal (the bevel) and a real AO signal (occluded near
        its base, from the plane it touches) - the one scene both wear
        and grime/grain masks can be baked from."""
        import maya.cmds as cmds

        from maya_plugin.handlers import uvatlas

        plane = cmds.ls(cmds.polyPlane(name=plane_name, width=10, height=10,
                                       constructionHistory=False)[0],
                        long=True)[0]
        box = cmds.ls(cmds.polyCube(name=box_name, width=2, height=2,
                                    depth=2,
                                    constructionHistory=False)[0],
                      long=True)[0]
        cmds.setAttr(box + ".translateY", 1.0)
        cmds.polyBevel3(box, offset=0.15, segments=2,
                        constructionHistory=False)
        uvatlas.uv_atlas({"names": [box], "project": "box", "cols": 1,
                          "rows": 1})
        return plane, box

    def _flat_material(self, mesh, name, rgb=(0.6, 0.6, 0.6)):
        import maya.cmds as cmds

        from maya_plugin.handlers import material

        material.assign_material({"mesh": mesh, "name": name,
                                  "shader": "standardSurface"})
        cmds.setAttr(name + ".baseColor", *rgb, type="double3")
        return name

    def _delta_quartiles(self, mask_path, after_path, before_srgb,
                         channel=0):
        """Sort texel indices by the RAW mask pixel value (ascending);
        mean |after-before| colour delta over the bottom and the top
        quartile. The caller decides which end is the "high driving
        signal" one for its effect kind (curvature un-inverted for wear,
        AO inverted for grime - so grime's high signal is the mask's LOW
        raw quartile)."""
        from maya_plugin.handlers import pngprobe

        mask = pngprobe.read_png(mask_path)
        after = pngprobe.read_png(after_path)
        n = len(mask["pixels"])
        assert len(after["pixels"]) == n, (n, len(after["pixels"]))
        order = sorted(range(n), key=lambda i: mask["pixels"][i][0])
        q = max(1, n // 4)

        def mean_delta(idx):
            return sum(abs(after["pixels"][i][channel] - before_srgb)
                      for i in idx) / float(len(idx))

        return mean_delta(order[:q]), mean_delta(order[-q:])

    def test_wear_correlates_with_baked_curvature(self, tmp_path):
        import os

        from maya_plugin.handlers import meshmaps, surfdetail

        cube = self._beveled_cube("worn")
        base_rgb = (0.6, 0.6, 0.6)
        self._flat_material(cube, "worn_mat", base_rgb)
        before_srgb = meshmaps._srgb_encode(base_rgb[0])

        meshmaps.bake_mesh_maps({"meshes": [cube], "out_dir": str(tmp_path),
                                 "maps": ["curvature"], "resolution": 256})

        result = surfdetail.apply_surface_detail({
            "mesh": cube, "maps_dir": str(tmp_path), "out_dir": str(tmp_path),
            "resolution": 256,
            "effects": [{"kind": "wear", "strength": 2.0, "scale": 1.0}],
        })
        wear = next(e for e in result["effects"] if e["kind"] == "wear")
        assert wear["changed_fraction"] > 0
        assert os.path.isfile(result["color_file"])

        curv_path = os.path.join(str(tmp_path), "worn_curvature.png")
        bottom_mean, top_mean = self._delta_quartiles(
            curv_path, result["color_file"], before_srgb)
        # high curvature (top quartile) is wear's driving mask - it must
        # be worn measurably more than the flattest quartile.
        ratio = top_mean / max(bottom_mean, 1e-6)
        assert ratio > 2, (bottom_mean, top_mean, ratio)

    def test_grime_correlates_with_inverted_baked_ao(self, tmp_path):
        import os

        from maya_plugin.handlers import meshmaps, surfdetail

        plane = self._plane_under_box(plane_name="grimyground",
                                      box_name="grimycrate")
        base_rgb = (0.6, 0.6, 0.6)
        self._flat_material(plane, "grime_mat", base_rgb)
        before_srgb = meshmaps._srgb_encode(base_rgb[0])

        meshmaps.bake_mesh_maps({"meshes": [plane], "out_dir": str(tmp_path),
                                 "maps": ["ao"], "resolution": 256})

        result = surfdetail.apply_surface_detail({
            "mesh": plane, "maps_dir": str(tmp_path), "out_dir": str(tmp_path),
            "resolution": 256,
            "effects": [{"kind": "grime", "strength": 2.0, "scale": 1.0}],
        })
        grime = next(e for e in result["effects"] if e["kind"] == "grime")
        assert grime["changed_fraction"] > 0
        assert os.path.isfile(result["color_file"])

        ao_path = os.path.join(str(tmp_path), "grimyground_ao.png")
        bottom_mean, top_mean = self._delta_quartiles(
            ao_path, result["color_file"], before_srgb)
        # grime's mask is AO INVERTED - the driving signal is highest
        # where the raw AO bake is DARKEST (occluded), i.e. the bottom
        # quartile of raw AO values.
        ratio = bottom_mean / max(top_mean, 1e-6)
        assert ratio > 2, (bottom_mean, top_mean, ratio)

    def test_grain_writes_a_height_map_and_wires_a_bump_network(
            self, tmp_path):
        import os

        import maya.cmds as cmds

        from maya_plugin.handlers import meshmaps, pngprobe, surfdetail

        plane, box = self._beveled_box_on_plane(plane_name="grainground",
                                                box_name="graincrate")
        self._flat_material(box, "grain_mat")

        meshmaps.bake_mesh_maps({"meshes": [box], "out_dir": str(tmp_path),
                                 "maps": ["curvature", "ao"],
                                 "resolution": 256})

        result = surfdetail.apply_surface_detail({
            "mesh": box, "maps_dir": str(tmp_path), "out_dir": str(tmp_path),
            "resolution": 256,
            "effects": [{"kind": "grain", "strength": 0.4, "scale": 1.0}],
        })
        assert result["height_file"] is not None
        assert os.path.isfile(result["height_file"])
        uni = pngprobe.uniformity(result["height_file"])
        assert uni["non_uniform"] is True

        bumps = [n for n in result["file_nodes"]
                if cmds.nodeType(n) == "bump2d"]
        assert len(bumps) == 1, result["file_nodes"]
        bump = bumps[0]
        assert cmds.getAttr(bump + ".bumpInterp") == 0

        value_src = cmds.listConnections(bump + ".bumpValue", source=True,
                                         plugs=True, destination=False)
        assert value_src, "bumpValue has no incoming connection"
        assert value_src[0].endswith(".outAlpha")
        assert cmds.nodeType(value_src[0].split(".")[0]) == "file"

        normal_src = cmds.listConnections("grain_mat.normalCamera",
                                          source=True, destination=False)
        assert normal_src and bump in normal_src

    def test_grain_refuses_a_shader_that_already_has_a_bump_network(
            self, tmp_path):
        from maya_plugin.handlers import (meshmaps, surfdetail,
                                          texture_recipes)
        from maya_plugin.dispatcher import HandlerError

        plane, box = self._beveled_box_on_plane(plane_name="stackedground",
                                                box_name="stackedcrate")
        self._flat_material(box, "stacked_mat")
        texture_recipes.apply_texture_recipe({"mesh": box,
                                              "recipe": "noise_bump"})

        meshmaps.bake_mesh_maps({"meshes": [box], "out_dir": str(tmp_path),
                                 "maps": ["curvature", "ao"],
                                 "resolution": 256})

        with pytest.raises(HandlerError, match="bump/normal network"):
            surfdetail.apply_surface_detail({
                "mesh": box, "maps_dir": str(tmp_path),
                "out_dir": str(tmp_path), "resolution": 256,
                "effects": [{"kind": "grain", "strength": 0.4,
                            "scale": 1.0}],
            })

    def test_a_flat_mask_refuses_naming_distinct_values(self, tmp_path):
        """MEASURED (this task): a lone flat plane's real Arnold bake is
        NOT honestly flat. aiAmbientOcclusion/aiCurvature at the
        aa_samples=3 `_arnold_bake` uses carry Monte-Carlo sampling noise
        even over unoccluded, uncurved geometry - a diagnostic bake of
        this exact scene (curvature and ao, 256 res) came back with 125
        and 665 distinct byte values respectively, ~18%/~38% of texels
        off the dominant value, not the single-value bake the #775 plan
        assumed. So this test proves the refusal against a literally
        flat mask FILE (the real geometry-derived filename convention
        and the real `_load_mask`/`pngprobe.uniformity` code path
        `apply_surface_detail` reads through) rather than against a
        bake, which cannot produce one at this sample count."""
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import pngwrite, surfdetail

        plane = cmds.ls(cmds.polyPlane(name="lonely", width=10, height=10,
                                       constructionHistory=False)[0],
                        long=True)[0]
        self._flat_material(plane, "lonely_mat")

        flat_path = str(tmp_path / "lonely_curvature.png")
        pngwrite.write_png(flat_path, 256, 256, [(0, 0, 0)] * (256 * 256))

        with pytest.raises(HandlerError, match="distinct_values"):
            surfdetail.apply_surface_detail({
                "mesh": plane, "maps_dir": str(tmp_path),
                "out_dir": str(tmp_path), "resolution": 256,
                "effects": [{"kind": "wear", "strength": 0.5,
                            "scale": 1.0}],
            })

    def test_checkpoint_restore_reverts_the_colour_slot(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import (meshmaps, session, surfdetail,
                                          texclaim)

        cmds.file(rename=str(tmp_path / "work.ma"))
        cube = self._beveled_cube("checkpointed")
        base_rgb = (0.6, 0.6, 0.6)
        self._flat_material(cube, "cp_mat", base_rgb)

        shape = cmds.listRelatives(cube, shapes=True, fullPath=True)[0]
        # texclaim.material_claims only reports slots worth an export
        # warning (file/procedural) - a plain flat value is classified
        # "value" internally but never appears in the list at all
        # (texclaim.py: `if classification == "value": continue`), so
        # "before" is the ABSENCE of a cp_mat/baseColor claim, not a
        # claim carrying classification "value".
        before_claims = texclaim.material_claims(cmds, [shape])
        assert not any(c["material"] == "cp_mat" and c["attr"] == "baseColor"
                      for c in before_claims)

        meshmaps.bake_mesh_maps({"meshes": [cube], "out_dir": str(tmp_path),
                                 "maps": ["curvature"], "resolution": 256})

        result = surfdetail.apply_surface_detail({
            "mesh": cube, "maps_dir": str(tmp_path), "out_dir": str(tmp_path),
            "resolution": 256,
            "effects": [{"kind": "wear", "strength": 2.0, "scale": 1.0}],
        })

        after_claims = texclaim.material_claims(cmds, [shape])
        after_claim = next(c for c in after_claims
                           if c["material"] == "cp_mat"
                           and c["attr"] == "baseColor")
        assert after_claim["classification"] == "file"

        session.restore_checkpoint({"checkpoint_id": result["checkpoint_id"]})

        restored_claims = texclaim.material_claims(cmds, [shape])
        assert not any(
            c["material"] == "cp_mat" and c["attr"] == "baseColor"
            for c in restored_claims), (
            "restore_checkpoint left the slot classified as file/"
            "procedural - the pre-apply flat value did not come back")
