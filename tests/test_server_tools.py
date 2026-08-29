"""MCP server tool tests: registration, annotations, marshaling, image returns.

Uses the real MCPServer with an injected fake connection — no Maya, no sockets.
"""

import asyncio
import base64
import io
import json

import pytest
from PIL import Image as PILImage

from maya_mcp import refstore, schemas, server as server_mod


def png_b64(width=1024, height=1024, color=(140, 100, 70)):
    img = PILImage.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


class FakeConn:
    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or {}

    def request(self, cmd, params, timeout_s=30.0):
        self.calls.append({"cmd": cmd, "params": params, "timeout_s": timeout_s})
        return self.responses[cmd]


def run(coro):
    return asyncio.run(coro)


class TestRegistration:
    def test_exactly_the_three_m0_tools_registered(self):
        mcp = server_mod.create_server(FakeConn())
        tools = run(mcp.list_tools())
        assert {
            "maya_execute_python",
            "maya_get_scene_graph",
            "maya_capture_viewport",
        }.issubset({t.name for t in tools})
        for tool in tools:
            assert tool.description  # every tool documented

    def test_session_tools_registered(self):
        mcp = server_mod.create_server(FakeConn())
        tools = run(mcp.list_tools())
        assert {t.name for t in tools} == {
            "maya_execute_python",
            "maya_get_scene_graph",
            "maya_get_object_info",
            "maya_capture_viewport",
            "maya_capture_turntable",
            "maya_render_scene",
            "maya_render_sheet",
            "maya_checkpoint",
            "maya_restore_checkpoint",
            "maya_undo",
            "maya_redo",
            "maya_new_scene",
            "maya_open_scene",
            "maya_save_scene",
            "maya_export_fbx",
            "maya_bake_textures",
            "maya_reset_namespace",
            "maya_create_primitive",
            "maya_duplicate",
            "maya_array",
            "maya_transform",
            "maya_group",
            "maya_parent",
            "maya_rename",
            "maya_delete_objects",
            "maya_boolean_op",
            "maya_etch_text",
            "maya_sculpt_ops",
            "maya_deform",
            "maya_combine",
            "maya_assemble",
            "maya_uv_atlas",
            "maya_remesh_retopo",
            "maya_mesh_cleanup",
            "maya_set_viewport",
            "maya_set_camera",
            "maya_load_reference_image",
            "maya_compare_to_reference",
            "maya_setup_lighting",
            "maya_assign_material",
            "maya_assign_pbr",
            "maya_apply_texture_recipe",
            "maya_create_skeleton",
            "maya_bind_skin",
            "maya_pose_skeleton",
            "maya_reset_pose",
            "maya_weight_report",
            "maya_mirror_weights",
            "maya_smooth_weights",
            "maya_set_region_weights",
            "maya_pose_ik",
            "maya_author_physics",
            "maya_create_blendshape",
            "maya_set_blendshape_weights",
            "maya_author_clip",
            "maya_delete_clip",
            "maya_measure_clip",
            "maya_preview_clip",
            "maya_create_curve_form",
            "maya_retarget_clip",
            "maya_clean_clip",
        }

    def test_annotations_declare_read_only_vs_destructive(self):
        mcp = server_mod.create_server(FakeConn())
        by_name = {t.name: t for t in run(mcp.list_tools())}
        # design §5: every tool declares all three hints explicitly
        execute = by_name["maya_execute_python"].annotations
        assert (execute.read_only_hint, execute.destructive_hint,
                execute.idempotent_hint) == (False, True, False)
        scene_graph = by_name["maya_get_scene_graph"].annotations
        assert (scene_graph.read_only_hint, scene_graph.destructive_hint,
                scene_graph.idempotent_hint) == (True, False, True)
        capture = by_name["maya_capture_viewport"].annotations
        assert (capture.read_only_hint, capture.destructive_hint,
                capture.idempotent_hint) == (True, False, True)
        lighting = by_name["maya_setup_lighting"].annotations
        assert (lighting.read_only_hint, lighting.destructive_hint,
                lighting.idempotent_hint) == (False, True, False)


class TestExecutePython:
    def test_marshals_code_and_timeout_and_returns_result(self):
        conn = FakeConn(
            responses={
                "execute_python": {
                    "stdout": "", "stderr": "", "result_repr": "42",
                    "traceback": None, "namespace_keys": ["x"],
                }
            }
        )
        mcp = server_mod.create_server(conn)
        result = run(
            mcp.call_tool("maya_execute_python", {"code": "6*7", "timeout_s": 90})
        )
        assert result.is_error is False
        assert conn.calls[0]["cmd"] == "execute_python"
        assert conn.calls[0]["params"]["code"] == "6*7"
        assert conn.calls[0]["params"]["timeout_s"] == 90
        assert conn.calls[0]["timeout_s"] == 90
        assert result.structured_content["result_repr"] == "42"

    def test_timeout_beyond_300_rejected_by_schema(self):
        conn = FakeConn(responses={"execute_python": {}})
        mcp = server_mod.create_server(conn)
        with pytest.raises(Exception, match="timeout_s"):
            run(mcp.call_tool("maya_execute_python", {"code": "1", "timeout_s": 9999}))
        assert conn.calls == []  # rejected before reaching Maya

    def test_traceback_passed_through_verbatim(self):
        tb = "Traceback (most recent call last):\n  ...\nValueError: golem stumbled"
        conn = FakeConn(
            responses={
                "execute_python": {
                    "stdout": "", "stderr": "", "result_repr": None,
                    "traceback": tb, "namespace_keys": [],
                }
            }
        )
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_execute_python", {"code": "boom()"}))
        assert result.structured_content["traceback"] == tb


class TestSceneGraph:
    def test_marshals_filter_and_pagination(self):
        conn = FakeConn(
            responses={
                "get_scene_graph": {"objects": [], "total": 0, "cursor": None}
            }
        )
        mcp = server_mod.create_server(conn)
        result = run(
            mcp.call_tool(
                "maya_get_scene_graph",
                {"filter": "mesh", "max_objects": 50, "cursor": "10"},
            )
        )
        assert result.is_error is False
        params = conn.calls[0]["params"]
        assert params == {"filter": "mesh", "max_objects": 50, "cursor": "10"}


def lit_png_b64(size=(64, 64)):
    """A frame with a subject in it - pixel_stats must call this non-blank."""
    img = PILImage.new("RGB", size, (0, 0, 0))
    for x in range(8):
        for y in range(8):
            img.putpixel((x, y), (200, 40 + x, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def blank_png_b64(size=(64, 64)):
    """What a render of nothing looks like: valid PNG, no subject."""
    buf = io.BytesIO()
    PILImage.new("RGBA", size, (0, 0, 0, 0)).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


class TestRenderScene:
    def _response(self, png_list):
        return {
            "render_scene": {
                "images": [{"angle": a, "png_b64": p} for a, p in png_list],
                "camera_positions": [],
                "renderer": "arnold",
                "samples": 3,
                "fallback_light": False,
            }
        }

    def test_marshals_params_and_reports_pixel_statistics(self):
        conn = FakeConn(responses=self._response([("front", lit_png_b64())]))
        mcp = server_mod.create_server(conn)
        result = run(
            mcp.call_tool(
                "maya_render_scene",
                {"angles": ["front"], "renderer": "arnold", "resolution": 256,
                 "samples": 5, "isolate": ["|gem"], "fallback_light": False},
            )
        )
        assert result.is_error is False
        assert conn.calls[0]["cmd"] == "render_scene"
        params = conn.calls[0]["params"]
        assert params["renderer"] == "arnold"
        assert params["samples"] == 5
        assert params["isolate"] == ["|gem"]
        assert params["fallback_light"] is False
        assert len([c for c in result.content if c.type == "image"]) == 1
        text = " ".join(c.text for c in result.content if c.type == "text")
        assert "opaque_px" in text and "arnold" in text

    def test_all_blank_frames_raise_instead_of_returning_black_squares(self):
        # The failure this tool exists to make visible: a valid PNG of nothing
        # arriving with a success status.
        conn = FakeConn(responses=self._response([("front", blank_png_b64())]))
        mcp = server_mod.create_server(conn)
        with pytest.raises(Exception, match="blank"):
            run(mcp.call_tool("maya_render_scene", {"angles": ["front"]}))

    def test_one_good_frame_among_blanks_still_returns(self):
        conn = FakeConn(responses=self._response(
            [("front", blank_png_b64()), ("side", lit_png_b64())]
        ))
        mcp = server_mod.create_server(conn)
        result = run(
            mcp.call_tool("maya_render_scene", {"angles": ["front", "side"]})
        )
        assert result.is_error is False
        assert len([c for c in result.content if c.type == "image"]) == 2

    def test_defaults_are_arnold_and_512(self):
        conn = FakeConn(responses=self._response([("three_quarter", lit_png_b64())]))
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool("maya_render_scene", {}))
        params = conn.calls[0]["params"]
        assert params["renderer"] == "arnold"
        assert params["resolution"] == 512
        assert params["samples"] == 3

    def test_rejects_a_fifth_angle_before_reaching_maya(self):
        conn = FakeConn(responses=self._response([]))
        mcp = server_mod.create_server(conn)
        with pytest.raises(Exception):
            run(mcp.call_tool(
                "maya_render_scene",
                {"angles": ["front", "side", "back", "top", "three_quarter"]},
            ))
        assert conn.calls == []

    def test_handler_warnings_are_forwarded_as_notes(self):
        # #757: the #721 IPR-hygiene report arrived at the wire and died in
        # this wrapper - render_sheet forwarded it, render_scene dropped it.
        responses = self._response([("front", lit_png_b64())])
        responses["render_scene"]["warnings"] = [
            "closed the Arnold RenderView window after rendering - an idle "
            "IPR re-renders on every scene mutation (#721)"]
        conn = FakeConn(responses=responses)
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_render_scene", {"angles": ["front"]}))
        text = " ".join(c.text for c in result.content if c.type == "text")
        assert "note: closed the Arnold RenderView window" in text


class TestMeasureClip:
    def test_marshals_params_and_returns_typed_metrics(self):
        conn = FakeConn(responses={"measure_clip": {
            "name": "walk", "fps": 30, "frames_sampled": 31, "loop": True,
            "rig_height": 1.0,
            "thresholds": {"contact_height": 0.02, "contact_speed": 0.35,
                           "slide_warn": 0.02},
            "joints": {"L_foot": {
                "path_length": 2.1, "peak_speed": 3.385,
                "peak_speed_frame": 7, "max_accel": 53.16,
                "max_accel_frame": 8, "height_range": [0.0, 0.11],
                "loop_closure": 0.0002}},
            "contacts": {"L_foot": {"runs": [[15, 30]], "max_slide": 0.0}},
            "symmetry": [{"left": "L_foot", "right": "R_foot",
                          "peak_speed_ratio": 1.0}],
            "warnings": ["R_foot SLIDES 0.0973 through a plant"],
        }})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool(
            "maya_measure_clip", {"root": "|hips", "name": "walk"}))
        assert result.is_error is False
        assert conn.calls[0]["cmd"] == "measure_clip"
        assert conn.calls[0]["params"] == {
            "root": "|hips", "name": "walk", "joints": None,
            "contact_joints": None,
        }
        out = result.structured_content
        assert out["joints"]["L_foot"]["peak_speed_frame"] == 7
        assert out["contacts"]["L_foot"]["runs"] == [[15, 30]]
        # the slide warning REACHES the caller - #757's lesson, again
        assert any("SLIDES" in w for w in out["warnings"])


class TestCaptureViewport:
    def test_returns_downscaled_images_plus_camera_summary(self, monkeypatch):
        monkeypatch.setenv("MAYA_MCP_MAX_IMAGE_PX", "256")
        conn = FakeConn(
            responses={
                "capture_viewport": {
                    "images": [
                        {"angle": "front", "png_b64": png_b64(1024, 1024)},
                        {"angle": "three_quarter", "png_b64": png_b64(1024, 512)},
                    ],
                    "camera_positions": [
                        {"angle": "front", "position": [0, 2, 9], "rotation": [0, 0, 0]},
                        {"angle": "three_quarter", "position": [6, 5, 6],
                         "rotation": [-27.9, 45, 0]},
                    ],
                }
            }
        )
        mcp = server_mod.create_server(conn)
        result = run(
            mcp.call_tool(
                "maya_capture_viewport",
                {"angles": ["front", "three_quarter"], "shading": "smoothShaded"},
            )
        )
        assert result.is_error is False
        image_blocks = [c for c in result.content if c.type == "image"]
        text_blocks = [c for c in result.content if c.type == "text"]
        assert len(image_blocks) == 2
        # downscaled to the configured cap before reaching the LLM
        first = PILImage.open(io.BytesIO(base64.b64decode(image_blocks[0].data)))
        assert max(first.size) == 256
        assert any("front" in t.text and "three_quarter" in t.text for t in text_blocks)

    def test_a_blank_frame_warning_reaches_the_caller(self):
        # #765 on top of #757's lesson: the handler names a blank frame, and
        # a warning this wrapper never reads is a warning nobody sees. The
        # image still comes back - naming it is the point, not refusing it.
        conn = FakeConn(
            responses={
                "capture_viewport": {
                    "images": [{"angle": "front", "png_b64": png_b64(64, 64),
                                "blank": True}],
                    "camera_positions": [{"angle": "front"}],
                    "warnings": ["front came back BLANK - every pixel is "
                                 "transparent, so nothing was drawn."],
                }
            }
        )
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_capture_viewport",
                                   {"angles": ["front"]}))
        assert result.is_error is False
        texts = [c.text for c in result.content if c.type == "text"]
        assert any("BLANK" in t for t in texts), texts
        assert len([c for c in result.content if c.type == "image"]) == 1

    def test_a_turntable_blank_warning_reaches_the_caller(self):
        conn = FakeConn(
            responses={
                "capture_turntable": {
                    "images": [{"index": 0, "azimuth": 0.0,
                                "png_b64": png_b64(64, 64), "blank": True}],
                    "n_frames": 1,
                    "warnings": ["azimuth 0 came back BLANK"],
                }
            }
        )
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_capture_turntable", {"n_frames": 2}))
        assert result.is_error is False
        texts = [c.text for c in result.content if c.type == "text"]
        assert any("BLANK" in t for t in texts), texts

    def test_marshals_all_capture_params(self):
        conn = FakeConn(
            responses={
                "capture_viewport": {"images": [], "camera_positions": []}
            }
        )
        mcp = server_mod.create_server(conn)
        run(
            mcp.call_tool(
                "maya_capture_viewport",
                {
                    "angles": ["top"], "shading": "wireframe",
                    "wireframe_overlay": False, "buffer": "ssao",
                    "isolate": ["|golem"], "frame_all": False, "resolution": 512,
                },
            )
        )
        params = conn.calls[0]["params"]
        assert params["angles"] == ["top"]
        assert params["shading"] == "wireframe"
        assert params["wireframe_overlay"] is False
        assert params["buffer"] == "ssao"
        assert params["isolate"] == ["|golem"]
        assert params["frame_all"] is False
        assert params["resolution"] == 512

    def test_invalid_angle_rejected_by_schema_before_wire(self):
        conn = FakeConn(responses={"capture_viewport": {}})
        mcp = server_mod.create_server(conn)
        with pytest.raises(Exception, match="dutch_tilt"):
            run(mcp.call_tool("maya_capture_viewport", {"angles": ["dutch_tilt"]}))
        assert conn.calls == []  # never reached Maya


class TestSessionTools:
    def test_maya_checkpoint_forwards_label(self):
        conn = FakeConn(
            responses={"checkpoint": {"checkpoint_id": "001_pre_rune", "path": "x.ma"}}
        )
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_checkpoint", {"label": "pre_rune"}))
        assert result.is_error is False
        assert conn.calls[0]["cmd"] == "checkpoint"
        assert conn.calls[0]["params"] == {"label": "pre_rune"}
        assert result.structured_content["checkpoint_id"] == "001_pre_rune"

    def test_maya_new_scene_default_confirm_false_forwards(self):
        # The plugin itself refuses without confirm=true (see test_session.py::
        # test_new_scene_requires_confirm); here we only verify the tool forwards
        # the default confirm=False rather than silently defaulting to True.
        conn = FakeConn(responses={"new_scene": {"new_scene": True}})
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool("maya_new_scene", {}))
        assert conn.calls[0]["cmd"] == "new_scene"
        assert conn.calls[0]["params"] == {"confirm": False, "linear_unit": "cm"}

    def test_maya_export_fbx_forwards_params(self):
        conn = FakeConn(
            responses={"export_fbx": {
                "path": "x.fbx", "bytes": 1234, "fbx_version": 7700,
                "node_count": 3, "mesh_count": 1, "root_nodes": ["|golem_arm"],
                "unit_scale_factor": 100.0, "metres_per_unit": 1.0,
            }}
        )
        mcp = server_mod.create_server(conn)
        result = run(
            mcp.call_tool(
                "maya_export_fbx",
                {
                    "path": "x.fbx",
                    "metres_per_unit": 1.0,
                    "nodes": ["golem_arm"],
                },
            )
        )
        assert result.is_error is False
        assert conn.calls[0]["cmd"] == "export_fbx"
        assert conn.calls[0]["params"] == {
            "path": "x.fbx", "metres_per_unit": 1.0, "nodes": ["golem_arm"],
            "include_skins": False, "include_animation": False,
            "require_baked_textures": False,
        }
        assert result.structured_content["fbx_version"] == 7700
        assert result.structured_content["skin"] is None

    def test_maya_export_fbx_forwards_nodes_omitted_as_none(self):
        conn = FakeConn(
            responses={"export_fbx": {
                "path": "x.fbx", "bytes": 1234, "fbx_version": 7700,
                "node_count": 3, "mesh_count": 1, "root_nodes": ["|golem_arm"],
                "unit_scale_factor": 100.0, "metres_per_unit": 1.0,
            }}
        )
        mcp = server_mod.create_server(conn)
        run(
            mcp.call_tool(
                "maya_export_fbx", {"path": "x.fbx", "metres_per_unit": 1.0}
            )
        )
        assert conn.calls[0]["cmd"] == "export_fbx"
        assert conn.calls[0]["params"] == {
            "path": "x.fbx", "metres_per_unit": 1.0, "nodes": None,
            "include_skins": False, "include_animation": False,
            "require_baked_textures": False,
        }

    def test_maya_export_fbx_forwards_include_skins_and_surfaces_the_block(self):
        conn = FakeConn(
            responses={"export_fbx": {
                "path": "x.fbx", "bytes": 1234, "fbx_version": 7700,
                "node_count": 4, "mesh_count": 1, "root_nodes": ["|tube"],
                "unit_scale_factor": 100.0, "metres_per_unit": 1.0,
                "skin": {"deformers": 1, "clusters": 3,
                         "influenced_models": 3, "bind_pose_present": True,
                         "max_weight_sum_error": 2e-7,
                         "unweighted_file_vertices": 0,
                         "unavailable_reason": None},
            }}
        )
        mcp = server_mod.create_server(conn)
        result = run(
            mcp.call_tool(
                "maya_export_fbx",
                {"path": "x.fbx", "metres_per_unit": 1.0,
                 "nodes": ["tube", "j1"], "include_skins": True},
            )
        )
        assert conn.calls[0]["params"]["include_skins"] is True
        assert result.structured_content["skin"]["clusters"] == 3
        assert result.structured_content["skin"]["bind_pose_present"] is True

    def test_export_fbx_forwards_textures_and_warnings(self):
        """#714: ExportFbxResult is extra='ignore', so a field the model does
        not declare is dropped silently on the way to the caller - exactly
        the #757 defect class."""
        result = _export_result_with(
            textures={
                "texture_records": 1, "video_records": 1,
                "file_maps": [{"material": "m", "attr": "baseColor",
                               "slot": "color", "file_node": "t",
                               "basename": "grain.png", "on_disk": True,
                               "found_in_file": True, "semantics_lost": []}],
                "dropped_maps": [{"material": "m", "attr": "normalCamera",
                                  "slot": "normal",
                                  "terminal": "mcpTex_noise",
                                  "terminal_type": "noise",
                                  "via": ["bump2d"], "meshes": ["|c"]}],
                "unclaimed_records": [], "unavailable_reason": None,
            },
            warnings=["material 'm' slot 'normal' ... silently drops"],
        )
        assert result.textures.dropped_maps[0].terminal == "mcpTex_noise"
        assert result.textures.file_maps[0].found_in_file is True
        assert result.warnings

    def test_export_fbx_passes_require_baked_textures_to_the_wire(self):
        sent = _capture_request(lambda tool: tool(
            path="C:/t/x.fbx", metres_per_unit=1.0, require_baked_textures=True))
        assert sent["params"]["require_baked_textures"] is True


class TestLinearUnitReachesTheToolSurface:
    """maya-mcp #634 - the numbers these tools quote had no unit attached."""

    def test_new_scene_defaults_to_the_metre_true_unit(self):
        conn = FakeConn(responses={"new_scene": {"new_scene": True}})
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool("maya_new_scene", {"confirm": True}))
        assert conn.calls[0]["params"]["linear_unit"] == "cm"

    def test_new_scene_forwards_an_explicit_unit(self):
        conn = FakeConn(responses={"new_scene": {"new_scene": True}})
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool("maya_new_scene", {"confirm": True, "linear_unit": "m"}))
        assert conn.calls[0]["params"]["linear_unit"] == "m"

    def test_new_scene_result_surfaces_the_units_block(self):
        conn = FakeConn(responses={"new_scene": {
            "new_scene": True,
            "units": {"linear_unit": "cm", "export_metres_per_unit": 1.0},
        }})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_new_scene", {"confirm": True}))
        assert result.structured_content["units"]["export_metres_per_unit"] == 1.0

    def test_scene_graph_result_surfaces_the_units_block(self):
        # Without this the bboxes in `objects` are bare numbers, which is how a
        # 100x delivery shipped three times looking fine (#629).
        conn = FakeConn(responses={"get_scene_graph": {
            "objects": [], "total": 0, "cursor": None,
            "units": {"linear_unit": "m", "export_metres_per_unit": 100.0},
        }})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_get_scene_graph", {}))
        assert result.structured_content["units"]["export_metres_per_unit"] == 100.0

    def test_object_info_result_surfaces_the_units_block(self):
        conn = FakeConn(responses={"get_object_info": {
            "name": "|golem|torso",
            "transform": {"translate": [1.0, 2.0, 3.0]},
            "units": {"linear_unit": "cm", "export_metres_per_unit": 1.0},
        }})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_get_object_info", {"name": "|golem|torso"}))
        assert result.structured_content["units"]["linear_unit"] == "cm"


class TestModelingTools:
    def test_maya_create_primitive_forwards_params(self):
        conn = FakeConn(
            responses={"create_primitive": {"name": "|golem_arm", "warnings": []}}
        )
        mcp = server_mod.create_server(conn)
        result = run(
            mcp.call_tool(
                "maya_create_primitive",
                {"kind": "cube", "name": "golem_arm", "translate": [1, 2, 3]},
            )
        )
        assert result.is_error is False
        assert conn.calls[0]["cmd"] == "create_primitive"
        assert conn.calls[0]["params"] == {
            "kind": "cube", "name": "golem_arm", "translate": [1, 2, 3],
            "rotate": None, "scale": None, "divisions": None,
            "subdivisions": None,
        }
        assert result.structured_content["name"] == "|golem_arm"

    def test_maya_create_primitive_forwards_per_axis_subdivisions(self):
        # #669: an unset `divisions` must arrive as None rather than 1, or the
        # handler would see both currencies on every call and refuse them all.
        conn = FakeConn(
            responses={"create_primitive": {
                "name": "|limb", "subdivisions": [12, 16], "faces": 194,
                "warnings": [],
            }}
        )
        mcp = server_mod.create_server(conn)
        result = run(
            mcp.call_tool(
                "maya_create_primitive",
                {"kind": "cylinder", "name": "limb", "subdivisions": [12, 16]},
            )
        )
        assert result.is_error is False
        assert conn.calls[0]["params"]["subdivisions"] == [12, 16]
        assert conn.calls[0]["params"]["divisions"] is None
        # and what was built comes back through the wrapper's own model - a
        # result field missing from the model is a field nobody sees (#757).
        assert result.structured_content["subdivisions"] == [12, 16]
        assert result.structured_content["faces"] == 194

    def test_maya_boolean_op_forwards_params(self):
        conn = FakeConn(
            responses={
                "boolean_op": {
                    "name": "|carved", "tris": 24, "watertight": True,
                    "warnings": [],
                }
            }
        )
        mcp = server_mod.create_server(conn)
        result = run(
            mcp.call_tool(
                "maya_boolean_op",
                {"a": "|base", "b": "|cutter", "op": "difference", "new_name": "carved"},
            )
        )
        assert result.is_error is False
        assert conn.calls[0]["cmd"] == "boolean_op"
        assert conn.calls[0]["params"] == {
            "a": "|base", "b": "|cutter", "op": "difference", "new_name": "carved",
        }
        assert conn.calls[0]["timeout_s"] == server_mod.BOOL_TIMEOUT_S
        assert result.structured_content["name"] == "|carved"

    def test_maya_array_forwards_params(self):
        # Pins the full wire contract: a dropped or renamed key here is
        # invisible to both the ArrayResult-only schema tests and the
        # handler's own unit tests, and would only surface live in Maya.
        # `axis` is omitted by the caller on purpose - the tool must forward
        # it as None rather than filling in a default, since radial and
        # mirror need DIFFERENT defaults and only the handler knows which.
        conn = FakeConn(
            responses={
                "array": {
                    "names": ["|tooth_1"], "mode": "radial", "group": None,
                    "signed_volume": None, "warnings": [],
                }
            }
        )
        mcp = server_mod.create_server(conn)
        result = run(
            mcp.call_tool(
                "maya_array",
                {"name": "|tooth", "mode": "radial", "count": 6},
            )
        )
        assert result.is_error is False
        assert conn.calls[0]["cmd"] == "array"
        assert conn.calls[0]["params"] == {
            "name": "|tooth", "mode": "radial", "count": 6, "axis": None,
            "center": None, "angle": 360.0, "offset": None,
            "step_rotate": None, "step_scale": None, "pivot": None,
            "name_prefix": None, "group_name": None,
        }
        assert conn.calls[0]["timeout_s"] == server_mod.BOOL_TIMEOUT_S
        assert result.structured_content["names"] == ["|tooth_1"]

    def test_maya_etch_text_forwards_params(self):
        conn = FakeConn(
            responses={
                "etch_text": {
                    "name": "|plate_etched", "tris": 512, "watertight": True,
                    "warnings": [], "carved_text": "א",
                }
            }
        )
        mcp = server_mod.create_server(conn)
        result = run(
            mcp.call_tool(
                "maya_etch_text",
                {"mesh": "|plate", "text": "א", "face": 0, "width": 0.8,
                 "depth": 0.05, "mirror": True, "rotate_deg": 180.0},
            )
        )
        assert result.is_error is False
        assert conn.calls[0]["cmd"] == "etch_text"
        assert conn.calls[0]["params"] == {
            "mesh": "|plate", "text": "א", "face": 0, "width": 0.8,
            "depth": 0.05, "font": "Arial", "mirror": True, "rotate_deg": 180.0,
            "new_name": None,
        }
        assert conn.calls[0]["timeout_s"] == server_mod.BOOL_TIMEOUT_S
        assert result.structured_content["carved_text"] == "א"

    def test_maya_sculpt_ops_forwards_params(self):
        conn = FakeConn(
            responses={
                "sculpt_ops": {
                    "applied": 1, "ops": ["displace_noise"], "tris": 480,
                    "warnings": [
                        "ops [displace_noise] modify vertices via the Maya API "
                        "and are NOT undoable with maya_undo; to revert this "
                        "call, restore the auto-checkpoint"
                    ],
                    "checkpoint_id": "001_auto_sculpt",
                }
            }
        )
        mcp = server_mod.create_server(conn)
        ops = [{"op": "displace_noise", "amp": 0.06, "freq": 2.6, "octaves": 2}]
        result = run(
            mcp.call_tool(
                "maya_sculpt_ops",
                {"mesh": "|rock", "ops": ops},
            )
        )
        assert result.is_error is False
        assert conn.calls[0]["cmd"] == "sculpt_ops"
        assert conn.calls[0]["params"] == {"mesh": "|rock", "ops": ops}
        assert conn.calls[0]["timeout_s"] == server_mod.BOOL_TIMEOUT_S
        assert result.structured_content["applied"] == 1
        assert result.structured_content["ops"] == ["displace_noise"]
        assert result.structured_content["checkpoint_id"] == "001_auto_sculpt"
        assert "NOT undoable" in result.structured_content["warnings"][0]

    def test_maya_sculpt_ops_checkpoint_defaults_to_none(self):
        conn = FakeConn(
            responses={
                "sculpt_ops": {
                    "applied": 1, "ops": ["smooth"], "tris": 12, "warnings": [],
                }
            }
        )
        mcp = server_mod.create_server(conn)
        result = run(
            mcp.call_tool(
                "maya_sculpt_ops",
                {"mesh": "|cube", "ops": [{"op": "smooth", "divisions": 1}]},
            )
        )
        assert result.is_error is False
        assert result.structured_content["checkpoint_id"] is None

    def test_maya_sculpt_ops_op_results_round_trips(self):
        # #769 fix review: op_results (the cage ops' measured per-op
        # outcomes) must reach real MCP callers, not just direct
        # sculpt.sculpt_ops() callers - SculptResult declares it explicitly
        # so it survives the schema's extra="ignore" for undeclared keys.
        conn = FakeConn(
            responses={
                "sculpt_ops": {
                    "applied": 1, "ops": ["mirror_topology"], "tris": 24,
                    "warnings": [], "checkpoint_id": None,
                    "op_results": [
                        {"op": "mirror_topology", "shells": 1,
                         "merged_vertices": 4, "vertices_before": 8,
                         "vertices_after": 12},
                    ],
                }
            }
        )
        mcp = server_mod.create_server(conn)
        ops = [{"op": "mirror_topology", "axis": "x"}]
        result = run(
            mcp.call_tool(
                "maya_sculpt_ops",
                {"mesh": "|half_cube", "ops": ops},
            )
        )
        assert result.is_error is False
        assert result.structured_content["op_results"] == [
            {"op": "mirror_topology", "shells": 1, "merged_vertices": 4,
             "vertices_before": 8, "vertices_after": 12},
        ]

    def test_maya_sculpt_ops_op_results_defaults_to_none(self):
        # The eight original ops (soft_move, smooth, bridge, ...) never
        # populate op_results - the plugin response omits the key entirely
        # for those calls, and the schema must not invent one.
        conn = FakeConn(
            responses={
                "sculpt_ops": {
                    "applied": 1, "ops": ["smooth"], "tris": 12, "warnings": [],
                }
            }
        )
        mcp = server_mod.create_server(conn)
        result = run(
            mcp.call_tool(
                "maya_sculpt_ops",
                {"mesh": "|cube", "ops": [{"op": "smooth", "divisions": 1}]},
            )
        )
        assert result.is_error is False
        assert result.structured_content["op_results"] is None

    def test_maya_deform_forwards_params(self):
        conn = FakeConn(
            responses={
                "deform": {"deformer_nodes": ["|bend1Handle"], "baked": False, "warnings": []}
            }
        )
        mcp = server_mod.create_server(conn)
        result = run(
            mcp.call_tool(
                "maya_deform",
                {"mesh": "|col", "deformer": "bend", "params": {"curvature": 45}},
            )
        )
        assert result.is_error is False
        assert conn.calls[0]["cmd"] == "deform"
        assert conn.calls[0]["params"] == {
            "mesh": "|col", "deformer": "bend", "params": {"curvature": 45},
            "delete_history_after": False,
        }
        assert conn.calls[0]["timeout_s"] == server_mod.BOOL_TIMEOUT_S
        assert result.structured_content["deformer_nodes"] == ["|bend1Handle"]

    def test_maya_remesh_retopo_forwards_params(self):
        conn = FakeConn(
            responses={
                "remesh_retopo": {
                    "name": "|blob", "tris": 400, "method": "polyRetopo", "warnings": [],
                }
            }
        )
        mcp = server_mod.create_server(conn)
        result = run(
            mcp.call_tool(
                "maya_remesh_retopo",
                {"mesh": "|blob", "target_polycount": 400},
            )
        )
        assert result.is_error is False
        assert conn.calls[0]["cmd"] == "remesh_retopo"
        assert conn.calls[0]["params"] == {
            "mesh": "|blob", "target_polycount": 400, "keep_original": True,
        }
        assert conn.calls[0]["timeout_s"] == server_mod.BOOL_TIMEOUT_S
        assert result.structured_content["method"] == "polyRetopo"

    def test_maya_mesh_cleanup_forwards_defaults(self):
        conn = FakeConn(
            responses={
                "mesh_cleanup": {
                    "name": "|dirty",
                    "before": {"tris": 12, "verts": 8, "faces": 6, "boundary_edges": 0,
                               "nonmanifold_edges": 0, "watertight": True},
                    "after": {"tris": 12, "verts": 8, "faces": 6, "boundary_edges": 0,
                              "nonmanifold_edges": 0, "watertight": True},
                    "warnings": [],
                }
            }
        )
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_mesh_cleanup", {"mesh": "|dirty"}))
        assert result.is_error is False
        assert conn.calls[0]["cmd"] == "mesh_cleanup"
        assert conn.calls[0]["params"] == {
            "mesh": "|dirty", "merge_verts_threshold": 0.001,
            "delete_history": True, "freeze_transforms": True, "conform_normals": True,
        }
        assert conn.calls[0]["timeout_s"] == server_mod.BOOL_TIMEOUT_S
        assert result.structured_content["before"]["tris"] == 12


class TestSetViewport:
    def test_marshals_provided_params_and_returns_full_state(self):
        conn = FakeConn(
            responses={
                "set_viewport": {
                    "panel": "modelPanel4", "show_grid": False,
                    "show_light_icons": False, "show_camera_icons": True,
                    "show_locators": True, "show_manipulators": True,
                    "show_texture_placements": True, "wireframe_on_shaded": False,
                    "display_lights": "default", "camera": "|persp",
                }
            }
        )
        mcp = server_mod.create_server(conn)
        result = run(
            mcp.call_tool(
                "maya_set_viewport", {"show_grid": False, "show_light_icons": False}
            )
        )
        assert result.is_error is False
        assert conn.calls[0]["cmd"] == "set_viewport"
        assert conn.calls[0]["params"]["show_grid"] is False
        assert conn.calls[0]["params"]["show_light_icons"] is False
        # unset params marshal through as None, not omitted - the handler
        # treats None as "leave unchanged"
        assert conn.calls[0]["params"]["show_camera_icons"] is None
        assert conn.calls[0]["params"]["display_lights"] is None
        assert conn.calls[0]["timeout_s"] == server_mod.SCENE_TIMEOUT_S
        assert result.structured_content["panel"] == "modelPanel4"
        assert result.structured_content["camera"] == "|persp"

    def test_bare_call_is_a_state_query_with_all_params_none(self):
        conn = FakeConn(
            responses={
                "set_viewport": {
                    "panel": "modelPanel4", "show_grid": True,
                    "show_light_icons": True, "show_camera_icons": True,
                    "show_locators": True, "show_manipulators": True,
                    "show_texture_placements": True, "wireframe_on_shaded": False,
                    "display_lights": "default", "camera": "|persp",
                }
            }
        )
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool("maya_set_viewport", {}))
        assert all(v is None for v in conn.calls[0]["params"].values())

    def test_invalid_display_lights_rejected_by_schema(self):
        conn = FakeConn(responses={"set_viewport": {}})
        mcp = server_mod.create_server(conn)
        with pytest.raises(Exception, match="display_lights"):
            run(mcp.call_tool("maya_set_viewport", {"display_lights": "supernova"}))
        assert conn.calls == []  # rejected before reaching Maya


class TestSetCamera:
    def test_marshals_all_params_and_returns_camera_result(self):
        conn = FakeConn(
            responses={
                "set_camera": {
                    "name": "|mcpCam", "position": [0.0, 5.0, 10.0],
                    "rotation": [-27.938, 45.0, 0.0], "warnings": [],
                }
            }
        )
        mcp = server_mod.create_server(conn)
        result = run(
            mcp.call_tool(
                "maya_set_camera",
                {
                    "camera": "mcpCam", "position": [0, 5, 10], "look_at": [0, 0, 0],
                    "focal_length": 35, "set_active": False,
                },
            )
        )
        assert result.is_error is False
        assert conn.calls[0]["cmd"] == "set_camera"
        assert conn.calls[0]["params"] == {
            "camera": "mcpCam", "position": [0, 5, 10], "look_at": [0, 0, 0],
            "focal_length": 35, "set_active": False,
        }
        assert conn.calls[0]["timeout_s"] == server_mod.SCENE_TIMEOUT_S
        assert result.structured_content["name"] == "|mcpCam"
        assert result.structured_content["rotation"] == [-27.938, 45.0, 0.0]

    def test_defaults_camera_name_and_set_active_true(self):
        conn = FakeConn(
            responses={
                "set_camera": {
                    "name": "|mcpCam", "position": [0.0, 0.0, 0.0],
                    "rotation": [0.0, 0.0, 0.0], "warnings": [],
                }
            }
        )
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool("maya_set_camera", {}))
        assert conn.calls[0]["params"]["camera"] == "mcpCam"
        assert conn.calls[0]["params"]["set_active"] is True
        assert conn.calls[0]["params"]["position"] is None
        assert conn.calls[0]["params"]["look_at"] is None

    def test_bad_position_length_rejected_by_schema(self):
        conn = FakeConn(responses={"set_camera": {}})
        mcp = server_mod.create_server(conn)
        with pytest.raises(Exception, match="position"):
            run(mcp.call_tool("maya_set_camera", {"position": [1, 2]}))
        assert conn.calls == []  # rejected before reaching Maya


class TestSetupLighting:
    def test_marshals_all_params_and_returns_result(self):
        conn = FakeConn(
            responses={
                "setup_lighting": {
                    "preset": "three_point",
                    "lights": ["|mcpLight_key", "|mcpLight_fill", "|mcpLight_rim"],
                    "removed": ["oldKey"],
                    "checkpoint_id": "007_auto_lighting",
                    "warnings": [],
                }
            }
        )
        mcp = server_mod.create_server(conn)
        result = run(
            mcp.call_tool(
                "maya_setup_lighting",
                {"preset": "three_point", "intensity": 1.5,
                 "replace_existing": True},
            )
        )
        assert result.is_error is False
        assert conn.calls[0]["cmd"] == "setup_lighting"
        assert conn.calls[0]["params"] == {
            "preset": "three_point", "intensity": 1.5,
            "hdri_path": None, "replace_existing": True,
        }
        assert conn.calls[0]["timeout_s"] == server_mod.SCENE_TIMEOUT_S
        assert result.structured_content["removed"] == ["oldKey"]
        assert result.structured_content["checkpoint_id"] == "007_auto_lighting"

    def test_defaults_intensity_and_replace_existing(self):
        conn = FakeConn(
            responses={
                "setup_lighting": {
                    "preset": "single_sun", "lights": ["|mcpLight_sun"],
                    "removed": [], "checkpoint_id": None, "warnings": [],
                }
            }
        )
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool("maya_setup_lighting", {"preset": "single_sun"}))
        assert conn.calls[0]["params"]["intensity"] == 1.0
        assert conn.calls[0]["params"]["replace_existing"] is True
        assert conn.calls[0]["params"]["hdri_path"] is None

    def test_invalid_preset_rejected_by_schema(self):
        conn = FakeConn(responses={"setup_lighting": {}})
        mcp = server_mod.create_server(conn)
        with pytest.raises(Exception, match="preset"):
            run(mcp.call_tool("maya_setup_lighting", {"preset": "cinematic"}))
        assert conn.calls == []  # rejected before reaching Maya


class TestCaptureTurntable:
    def test_forwards_caller_supplied_shading(self):
        conn = FakeConn(
            responses={
                "capture_turntable": {
                    "images": [{"index": 0, "azimuth": 0.0, "png_b64": png_b64(32, 32)}],
                    "n_frames": 1,
                }
            }
        )
        mcp = server_mod.create_server(conn)
        run(
            mcp.call_tool(
                "maya_capture_turntable", {"target": "|golem", "shading": "textured"}
            )
        )
        assert conn.calls[0]["cmd"] == "capture_turntable"
        assert conn.calls[0]["params"]["shading"] == "textured"

    def test_shading_defaults_to_smooth_shaded(self):
        conn = FakeConn(
            responses={
                "capture_turntable": {
                    "images": [{"index": 0, "azimuth": 0.0, "png_b64": png_b64(32, 32)}],
                    "n_frames": 1,
                }
            }
        )
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool("maya_capture_turntable", {}))
        assert conn.calls[0]["params"]["shading"] == "smoothShaded"


class TestRenderSheet:
    """41 render_scene round-trips became one call and one image."""

    @staticmethod
    def _subject_png():
        """Two-tone: a FLAT frame is blank by definition (an unlit render, or a
        camera inside an object), so a cell with a subject in it needs two."""
        img = PILImage.new("RGB", (64, 64), (20, 20, 24))
        img.paste(PILImage.new("RGB", (30, 30), (200, 140, 90)), (10, 10))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")

    @classmethod
    def _conn(cls, labels, color=None):
        return FakeConn(responses={"render_sheet": {
            "images": [{"angle": "three_quarter", "label": label,
                        "png_b64": (png_b64(64, 64, color) if color
                                    else cls._subject_png())}
                       for label in labels],
            "camera_positions": [], "renderer": "arnold", "samples": 2,
            "fallback_light": False, "zoom": 1.0, "relit_lights": 0,
        }})

    def test_a_whole_kit_goes_over_the_wire_once(self):
        conn = self._conn(["|kit_a", "|kit_b", "|kit_c"])
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_render_sheet", {
            "subjects": ["|kit_a", "|kit_b", "|kit_c"], "renderer": "hw2",
        }))
        assert len(conn.calls) == 1
        assert conn.calls[0]["cmd"] == "render_sheet"
        assert conn.calls[0]["params"]["subjects"] == ["|kit_a", "|kit_b", "|kit_c"]
        assert result.is_error is False

    def test_returns_one_composited_image_not_n(self):
        mcp = server_mod.create_server(self._conn(["a", "b", "c", "d"]))
        result = run(mcp.call_tool("maya_render_sheet", {
            "subjects": ["a", "b", "c", "d"],
        }))
        pictures = [c for c in result.content if getattr(c, "type", None) == "image"]
        assert len(pictures) == 1, "a sheet is ONE image - that is the token win"

    def test_the_cell_order_is_reported_so_the_grid_can_be_read(self):
        mcp = server_mod.create_server(self._conn(["|kit_a", "|kit_b"]))
        result = run(mcp.call_tool("maya_render_sheet",
                                   {"subjects": ["|kit_a", "|kit_b"]}))
        text = " ".join(c.text for c in result.content
                        if getattr(c, "type", None) == "text")
        assert "row-major" in text
        assert "|kit_a" in text and "|kit_b" in text

    def test_blank_cells_are_named_not_left_to_the_eye(self):
        """A cell of nothing is a valid image. Naming the empty ones is the
        difference between 'that piece looks wrong' and 'it did not render'."""
        mcp = server_mod.create_server(self._conn(["|kit_a"], color=(0, 0, 0)))
        result = run(mcp.call_tool("maya_render_sheet", {"subjects": ["|kit_a"]}))
        text = " ".join(c.text for c in result.content
                        if getattr(c, "type", None) == "text")
        assert "blank cells: [\"|kit_a\"]" in text

    def test_no_blank_cells_says_so_explicitly(self):
        mcp = server_mod.create_server(self._conn(["|kit_a"]))
        result = run(mcp.call_tool("maya_render_sheet", {"subjects": ["|kit_a"]}))
        text = " ".join(c.text for c in result.content
                        if getattr(c, "type", None) == "text")
        assert "blank cells: none" in text

    def test_the_subject_cap_is_enforced_by_the_schema(self):
        conn = self._conn(["a"])
        mcp = server_mod.create_server(conn)
        with pytest.raises(Exception):
            run(mcp.call_tool("maya_render_sheet", {"subjects": ["a"] * 49}))
        assert conn.calls == []  # rejected before reaching Maya


class TestReferenceImages:
    def test_load_reference_image_returns_metadata(self):
        conn = FakeConn()
        mcp = server_mod.create_server(conn)
        result = run(
            mcp.call_tool(
                "maya_load_reference_image",
                {"source": png_b64(40, 30), "ref_id": "hero"},
            )
        )
        assert result.is_error is False
        assert result.structured_content == {
            "ref_id": "hero", "width": 40, "height": 30, "bytes": len(
                base64.b64decode(png_b64(40, 30))
            ),
        }
        assert conn.calls == []  # server-side store, never touches Maya

    def test_compare_to_reference_returns_side_by_side_image_left_reference_right_viewport(self):
        # Reference color: bright red; viewport color: bright blue
        ref_color = (255, 0, 0)
        viewport_color = (0, 0, 255)

        conn = FakeConn(
            responses={
                "capture_viewport": {
                    "images": [{"angle": "three_quarter", "png_b64": png_b64(64, 64, color=viewport_color)}],
                    "camera_positions": [],
                }
            }
        )
        mcp = server_mod.create_server(conn)
        run(
            mcp.call_tool(
                "maya_load_reference_image",
                {"source": png_b64(32, 32, color=ref_color), "ref_id": "hero"},
            )
        )
        result = run(mcp.call_tool("maya_compare_to_reference", {"ref_id": "hero"}))
        assert result.is_error is False
        image_blocks = [c for c in result.content if c.type == "image"]
        text_blocks = [c for c in result.content if c.type == "text"]
        assert len(image_blocks) == 1
        composite = PILImage.open(io.BytesIO(base64.b64decode(image_blocks[0].data)))
        # side-by-side canvas: wider than either source alone, same height
        assert composite.width > 64
        assert composite.height == 64
        assert any("hero" in t.text and "three_quarter" in t.text for t in text_blocks)
        assert conn.calls[0]["cmd"] == "capture_viewport"

        # Verify the image placement: reference on left, viewport on right.
        # The 8px gap separates them; sample well inside each half to avoid edges.
        # Left panel should be at least 32px (the scaled reference width).
        left_sample_x = 15  # well inside the left half
        right_sample_x = composite.width - 15  # well inside the right half
        center_y = composite.height // 2

        left_pixel = composite.getpixel((left_sample_x, center_y))
        right_pixel = composite.getpixel((right_sample_x, center_y))

        # Left side should have reference color (red)
        assert left_pixel == ref_color, f"Left pixel {left_pixel} != reference color {ref_color}"
        # Right side should have viewport color (blue)
        assert right_pixel == viewport_color, f"Right pixel {right_pixel} != viewport color {viewport_color}"

    def test_compare_to_reference_forwards_caller_supplied_shading(self):
        conn = FakeConn(
            responses={
                "capture_viewport": {
                    "images": [{"angle": "three_quarter", "png_b64": png_b64(32, 32)}],
                    "camera_positions": [],
                }
            }
        )
        mcp = server_mod.create_server(conn)
        run(
            mcp.call_tool(
                "maya_load_reference_image",
                {"source": png_b64(16, 16), "ref_id": "hero"},
            )
        )
        run(
            mcp.call_tool(
                "maya_compare_to_reference", {"ref_id": "hero", "shading": "textured"}
            )
        )
        assert conn.calls[0]["cmd"] == "capture_viewport"
        assert conn.calls[0]["params"]["shading"] == "textured"

    def test_compare_to_reference_shading_defaults_to_smooth_shaded(self):
        conn = FakeConn(
            responses={
                "capture_viewport": {
                    "images": [{"angle": "three_quarter", "png_b64": png_b64(32, 32)}],
                    "camera_positions": [],
                }
            }
        )
        mcp = server_mod.create_server(conn)
        run(
            mcp.call_tool(
                "maya_load_reference_image",
                {"source": png_b64(16, 16), "ref_id": "hero"},
            )
        )
        run(mcp.call_tool("maya_compare_to_reference", {"ref_id": "hero"}))
        assert conn.calls[0]["params"]["shading"] == "smoothShaded"

    def test_compare_to_reference_oversized_reference_is_capped(self, monkeypatch):
        # I6: a big reference must not bypass MAYA_MCP_MAX_IMAGE_PX - the
        # composite (reference | viewport) must land within the cap on its
        # longest edge, not balloon to the reference's native size.
        monkeypatch.setenv("MAYA_MCP_MAX_IMAGE_PX", "256")
        conn = FakeConn(
            responses={
                "capture_viewport": {
                    "images": [{"angle": "three_quarter", "png_b64": png_b64(64, 64)}],
                    "camera_positions": [],
                }
            }
        )
        mcp = server_mod.create_server(conn)
        run(
            mcp.call_tool(
                "maya_load_reference_image",
                {"source": png_b64(3000, 3000), "ref_id": "huge"},
            )
        )
        result = run(
            mcp.call_tool("maya_compare_to_reference", {"ref_id": "huge", "resolution": 200})
        )
        image_blocks = [c for c in result.content if c.type == "image"]
        composite = PILImage.open(io.BytesIO(base64.b64decode(image_blocks[0].data)))
        assert max(composite.size) <= 256

    def test_compare_to_reference_unknown_ref_id_errors_naming_loaded_ids(self):
        conn = FakeConn(responses={"capture_viewport": {"images": [], "camera_positions": []}})
        mcp = server_mod.create_server(conn)
        run(
            mcp.call_tool(
                "maya_load_reference_image",
                {"source": png_b64(10, 10), "ref_id": "hero"},
            )
        )
        with pytest.raises(Exception, match="hero"):
            run(mcp.call_tool("maya_compare_to_reference", {"ref_id": "missing"}))
        assert conn.calls == []  # never reached Maya - failed before the capture

    def test_compare_to_reference_errors_clearly_for_an_unknown_ref_id(self):
        # The failure a user will actually hit: comparing before loading.
        store = refstore.ReferenceStore()
        with pytest.raises(KeyError) as exc:
            store.get("never_loaded")
        assert "none" in str(exc.value)


class TestDocsExplainWhichShadingModeRevealsWhat:
    # F5: facets are invisible in smoothShaded, exactly as texture networks
    # are - the run couldn't tell whether a tool had done anything.

    def test_capture_viewport_shading_param_explains_the_modes(self):
        mcp = server_mod.create_server(FakeConn())
        tools = {t.name: t for t in run(mcp.list_tools())}
        desc = tools["maya_capture_viewport"].input_schema["properties"]["shading"][
            "description"
        ]
        assert "textured" in desc and "texture" in desc
        assert "flatShaded" in desc and "facet" in desc
        assert "smoothShaded" in desc and "hid" in desc  # "hides"/"hidden"

    def test_capture_turntable_shading_param_explains_the_modes(self):
        mcp = server_mod.create_server(FakeConn())
        tools = {t.name: t for t in run(mcp.list_tools())}
        desc = tools["maya_capture_turntable"].input_schema["properties"]["shading"][
            "description"
        ]
        assert "textured" in desc and "texture" in desc
        assert "flatShaded" in desc and "facet" in desc
        assert "smoothShaded" in desc and "hid" in desc

    def test_apply_texture_recipe_description_tells_caller_to_capture_textured(self):
        mcp = server_mod.create_server(FakeConn())
        tools = {t.name: t for t in run(mcp.list_tools())}
        desc = tools["maya_apply_texture_recipe"].description
        assert "textured" in desc

    def test_remesh_retopo_description_warns_it_is_wrong_for_faceted_forms(self):
        # F3: polyRetopo produces uniform quads and smooths - the opposite of
        # what a crystalline/faceted gem chunk needs.
        mcp = server_mod.create_server(FakeConn())
        tools = {t.name: t for t in run(mcp.list_tools())}
        desc = tools["maya_remesh_retopo"].description
        assert "quad" in desc
        assert "facet" in desc or "crystalline" in desc

    def test_assign_material_description_explains_reuse_semantics(self):
        # F4: reusing an existing shader of the same type is the intended way
        # to share one material across meshes - the tool description must say so.
        mcp = server_mod.create_server(FakeConn())
        tools = {t.name: t for t in run(mcp.list_tools())}
        desc = tools["maya_assign_material"].description
        assert "reuse" in desc.lower() or "reuses" in desc.lower()

    def test_assemble_forwards_a_whole_parts_list_in_one_request(self):
        conn = FakeConn({"assemble": {
            "objects": [{"name": "|tower_c0000", "parts": 4, "tris": 48,
                         "verts": 32, "faces": 24, "shells": 4,
                         "pivot": [0, 0, 0], "combined": True}],
            "parts": 4, "tris": 48, "outside_patch": 0, "atlas": [4, 4],
            "warnings": [],
        }})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_assemble", {
            "name": "tower",
            "parts": [{"pos": [0, 0, 0], "dim": [3, 3, 3], "chunk": "tower_c0000"}],
            "atlas": {"cols": 4, "rows": 4, "world_scale": 3.0},
        }))
        assert conn.calls[0]["cmd"] == "assemble"
        assert conn.calls[0]["params"]["atlas"]["world_scale"] == 3.0
        # A real delivery is thousands of boxes: the timeout must be the render
        # budget, not the 30 s scene one.
        assert conn.calls[0]["timeout_s"] == server_mod.RENDER_TIMEOUT_S
        assert result.structured_content["objects"][0]["shells"] == 4

    def test_assemble_forwards_the_per_chunk_pivot_map(self):
        conn = FakeConn({"assemble": {
            "objects": [{"name": "|rig_arm", "parts": 1, "tris": 12,
                         "verts": 8, "faces": 6, "shells": 1,
                         "pivot": [1.0, 2.0, 3.0], "combined": True}],
            "parts": 1, "tris": 12, "outside_patch": 0, "atlas": None,
            "warnings": [],
        }})
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool("maya_assemble", {
            "name": "rig",
            "parts": [{"pos": [0, 0, 0], "dim": [1, 1, 1], "chunk": "rig_arm"}],
            "pivots": {"rig_arm": [1.0, 2.0, 3.0]},
        }))
        # If pivots stopped being forwarded, this would silently pass through
        # as None and the plugin would fall back to the global `pivot` mode.
        assert conn.calls[0]["params"]["pivots"] == {"rig_arm": [1.0, 2.0, 3.0]}

    def test_assemble_rejects_a_pivots_entry_with_the_wrong_length_in_schema(self):
        # pivots values reuse Vec3 (min_length=3, max_length=3) so a malformed
        # entry is refused by the MCP schema itself - never forwarded to the
        # plugin, which would otherwise cost a Maya round-trip just to reject
        # what pydantic could catch for free.
        from mcp.server.mcpserver.exceptions import ToolError

        conn = FakeConn()
        mcp = server_mod.create_server(conn)
        with pytest.raises(ToolError):
            run(mcp.call_tool("maya_assemble", {
                "name": "rig",
                "parts": [{"pos": [0, 0, 0], "dim": [1, 1, 1], "chunk": "rig_arm"}],
                "pivots": {"rig_arm": [1.0, 2.0]},
            }))
        assert conn.calls == []

    def test_assign_pbr_forwards_the_whole_map_set_in_one_request(self):
        conn = FakeConn({"assign_pbr": {
            "meshes": ["|kit_a", "|kit_b"], "material": "kit",
            "shading_group": "kitSG", "shader": "standardSurface",
            "maps": {"roughness": {"file": "kit_mask_tex",
                                   "attr": "specularRoughness", "channel": "g",
                                   "inverted": True, "raw": True}},
            "nodes": ["kit_mask_tex"], "warnings": [],
        }})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_assign_pbr", {
            "mesh": ["|kit_a", "|kit_b"],
            "maps": {"roughness": {"path": "D:/kit_mask.png", "channel": "g",
                                   "invert": True}},
        }))
        assert conn.calls[0]["cmd"] == "assign_pbr"
        assert conn.calls[0]["params"]["mesh"] == ["|kit_a", "|kit_b"]
        assert conn.calls[0]["params"]["maps"]["roughness"]["invert"] is True
        assert result.structured_content["maps"]["roughness"]["raw"] is True

    def test_assign_pbr_description_carries_the_traps_that_cost_a_session(self):
        """The tool description is where a caller learns things no viewport can
        show: that a smoothness map needs inverting, that data maps are read
        raw, and that an atlas wants mip filtering off."""
        mcp = server_mod.create_server(FakeConn())
        tools = {t.name: t for t in run(mcp.list_tools())}
        schema = str(tools["maya_assign_pbr"].input_schema)
        assert "SMOOTHNESS" in schema
        assert "sRGB" in schema
        assert "ATLAS" in schema


def test_transform_forwards_pivot_and_reports_it_back():
    conn = FakeConn({"transform": {
        "objects": [{"name": "|pivotGate", "translate": [2.0, 3.0, 4.0],
                     "rotate": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0],
                     "pivot": [0.0, 10.0, 0.0]}],
        "warnings": [],
    }})
    mcp = server_mod.create_server(conn)
    result = run(mcp.call_tool("maya_transform", {
        "names": ["|pivotGate"], "pivot": [0.0, 10.0, 0.0],
    }))
    # If pivot stopped being forwarded, this would silently pass through as
    # None and the plugin would never move the pivot at all.
    assert conn.calls[0]["params"]["pivot"] == [0.0, 10.0, 0.0]
    assert result.structured_content["objects"][0]["pivot"] == [0.0, 10.0, 0.0]


def test_array_result_accepts_a_mirror_response():
    from maya_mcp.schemas import ArrayResult

    result = ArrayResult.model_validate(
        {
            "names": ["|arm_R"],
            "mode": "mirror",
            "group": None,
            "signed_volume": 3.25,
            "warnings": [],
        }
    )
    assert result.names == ["|arm_R"]
    assert result.signed_volume == 3.25


def test_array_result_signed_volume_is_optional():
    from maya_mcp.schemas import ArrayResult

    result = ArrayResult.model_validate(
        {"names": ["|cog_1", "|cog_2"], "mode": "radial", "group": "|gear"}
    )
    assert result.signed_volume is None
    assert result.group == "|gear"
    assert result.warnings == []


class TestApplyTextureRecipeForwardsWarnings:
    """#714/#757: apply_texture_recipe's handler is about to start emitting
    a warning for the procedural recipes. TextureRecipeResult already
    declares `warnings`, but nothing had proven a handler-emitted warning
    actually survives the round trip to the tool's caller."""

    def test_a_handler_warning_reaches_the_caller(self):
        conn = FakeConn(responses={"apply_texture_recipe": {
            "mesh": "|torso", "recipe": "noise_bump", "slot": "normal",
            "nodes": ["mcpTex_noise1", "mcpTex_bump1"],
            "warnings": ["this recipe builds a procedural network that "
                         "Maya's FBX exporter silently drops"],
        }})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_apply_texture_recipe", {
            "mesh": "|torso", "recipe": "noise_bump"}))
        assert result.structured_content["warnings"] == [
            "this recipe builds a procedural network that Maya's FBX "
            "exporter silently drops"]


class TestBakeTextures:
    def test_bake_textures_forwards_the_baked_list(self):
        """#714 phase 2: BakeTexturesResult is extra='ignore', so an undeclared
        field is dropped silently on the way to the caller (the #757 class)."""
        result = _bake_result_with(
            baked=[{"material": "skin_mat", "slot": "color", "attr": "baseColor",
                    "file": "C:/out/skin_mat_color_baked.png",
                    "basename": "skin_mat_color_baked.png", "resolution": 1024,
                    "colorspace": "sRGB", "wired_plug": "outColor",
                    "kept_intermediates": [], "deleted_nodes": ["mcpTex_noise"],
                    "pixel_check": {"pixel_count": 1048576,
                                    "distinct_values": 186,
                                    "non_uniform": True,
                                    "unavailable_reason": None}}],
            warnings=["skin_mat is worn by 2 meshes"])
        assert result.baked[0].basename == "skin_mat_color_baked.png"
        assert result.baked[0].pixel_check.non_uniform is True
        assert result.baked[0].deleted_nodes == ["mcpTex_noise"]
        assert result.checkpoint_id
        assert result.warnings

    def test_bake_textures_passes_its_params_to_the_wire(self):
        sent = _bake_capture_request(lambda tool: tool(
            meshes=["|body"], out_dir="C:/out", resolution=2048,
            slots=["color"]))
        assert sent["params"] == {"meshes": ["|body"], "out_dir": "C:/out",
                                  "resolution": 2048, "slots": ["color"]}

    def test_no_op_checkpoint_id_is_null_and_still_validates(self):
        """Task 3's review round: a scene where every requested slot is
        already file-backed bakes nothing, so the handler returns
        checkpoint_id=None rather than spending a slot in the bounded
        checkpoint ring on a checkpoint of no change. BakeTexturesResult
        must validate that null rather than requiring a str."""
        result = _bake_result_with(
            baked=[], checkpoint_id=None,
            skipped_file_backed=[
                "skin_mat.baseColor is already file-backed - nothing to bake"],
            warnings=[
                "skin_mat.baseColor is already file-backed - nothing to bake"])
        assert result.checkpoint_id is None
        assert result.baked == []

    def test_no_op_result_still_carries_its_explanation(self):
        """A caller must be able to tell 'nothing needed baking' from
        'nothing happened' - skipped_file_backed is what carries that
        distinction across the wire."""
        result = _bake_result_with(
            baked=[], checkpoint_id=None,
            skipped_file_backed=[
                "skin_mat.baseColor is already file-backed - nothing to bake"],
            warnings=[
                "skin_mat.baseColor is already file-backed - nothing to bake"])
        assert result.skipped_file_backed == [
            "skin_mat.baseColor is already file-backed - nothing to bake"]

    def test_annotations(self):
        mcp = server_mod.create_server(FakeConn())
        by_name = {t.name: t for t in run(mcp.list_tools())}
        bake = by_name["maya_bake_textures"].annotations
        assert (bake.read_only_hint, bake.destructive_hint,
                bake.idempotent_hint) == (False, True, False)


class TestLightingPresets:
    def test_environment_preset_is_reachable_and_needs_no_file(self):
        conn = FakeConn(responses={"setup_lighting": {
            "preset": "environment", "lights": ["|mcpLight_dome"],
            "removed": [], "checkpoint_id": None, "warnings": [],
        }})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_setup_lighting",
                                   {"preset": "environment"}))
        assert conn.calls[0]["params"]["hdri_path"] is None
        assert result.structured_content["lights"] == ["|mcpLight_dome"]

    def test_the_preset_docs_say_why_a_metal_needs_the_dome(self):
        """metalness = 1.0 renders black in a three-point rig. A caller reaching
        for lighting has to learn that HERE, not from a black render."""
        mcp = server_mod.create_server(FakeConn())
        tools = {t.name: t for t in run(mcp.list_tools())}
        schema = str(tools["maya_setup_lighting"].input_schema)
        assert "metal" in schema and "BLACK" in schema


class TestImageToolsWriteFiles:
    """#639: `render_scene`, `render_sheet`, `capture_viewport` and
    `capture_turntable` all returned the image as the call's value and cleaned
    up after themselves. After a full art run the project's images folder held
    exactly one stale temp file, so the run's stills had to escape to
    execute_python and call the plugin's own renderer."""

    @staticmethod
    def _subject_png(size=64):
        img = PILImage.new("RGB", (size, size), (20, 20, 24))
        img.paste(PILImage.new("RGB", (size // 2, size // 2), (200, 140, 90)), (4, 4))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")

    def _capture_conn(self, angles):
        return FakeConn(responses={"capture_viewport": {
            "images": [{"angle": a, "png_b64": self._subject_png()} for a in angles],
            "camera_positions": [],
        }})

    def _render_conn(self, angles):
        return FakeConn(responses={"render_scene": {
            "images": [{"angle": a, "label": a, "png_b64": self._subject_png()}
                       for a in angles],
            "camera_positions": [], "renderer": "arnold", "samples": 3,
            "fallback_light": False, "zoom": 1.0, "relit_lights": 0,
        }})

    def test_one_capture_lands_at_exactly_the_path_asked_for(self, tmp_path):
        target = tmp_path / "hero.png"
        mcp = server_mod.create_server(self._capture_conn(["three_quarter"]))
        result = run(mcp.call_tool("maya_capture_viewport", {
            "angles": ["three_quarter"], "path": str(target),
        }))
        assert result.is_error is False
        assert target.exists() and target.stat().st_size > 0

    def test_several_angles_get_one_file_each_named_by_angle(self, tmp_path):
        mcp = server_mod.create_server(self._capture_conn(["front", "side"]))
        result = run(mcp.call_tool("maya_capture_viewport", {
            "angles": ["front", "side"], "path": str(tmp_path / "hero.png"),
        }))
        assert result.is_error is False
        assert (tmp_path / "hero_front.png").exists()
        assert (tmp_path / "hero_side.png").exists()
        assert not (tmp_path / "hero.png").exists()

    def test_the_written_paths_are_reported_so_a_manifest_can_name_them(self, tmp_path):
        mcp = server_mod.create_server(self._capture_conn(["front", "side"]))
        result = run(mcp.call_tool("maya_capture_viewport", {
            "angles": ["front", "side"], "path": str(tmp_path / "hero.png"),
        }))
        text = " ".join(c.text for c in result.content
                        if getattr(c, "type", None) == "text")
        assert "wrote:" in text
        assert "hero_front.png" in text and "hero_side.png" in text

    def test_the_file_keeps_full_resolution_not_the_downscaled_message_copy(
        self, tmp_path
    ):
        """The point of writing to disk is the deliverable. Saving the copy
        that was shrunk to what an LLM can read would make asking Maya for
        2048 pointless."""
        big = 1600
        conn = FakeConn(responses={"capture_viewport": {
            "images": [{"angle": "front", "png_b64": self._subject_png(big)}],
            "camera_positions": [],
        }})
        mcp = server_mod.create_server(conn)
        target = tmp_path / "big.png"
        result = run(mcp.call_tool("maya_capture_viewport", {
            "angles": ["front"], "path": str(target), "resolution": big,
        }))
        on_disk = PILImage.open(target)
        assert on_disk.width == big
        picture = [c for c in result.content if getattr(c, "type", None) == "image"][0]
        in_message = PILImage.open(io.BytesIO(base64.b64decode(picture.data)))
        assert in_message.width < big  # downscaled for the message, not the file

    def test_a_turntable_writes_the_composited_sheet(self, tmp_path):
        conn = FakeConn(responses={"capture_turntable": {
            "images": [{"index": i, "azimuth": 90.0 * i,
                        "png_b64": self._subject_png()} for i in range(4)],
            "n_frames": 4,
        }})
        mcp = server_mod.create_server(conn)
        target = tmp_path / "turn.png"
        run(mcp.call_tool("maya_capture_turntable", {
            "n_frames": 4, "path": str(target),
        }))
        sheet = PILImage.open(target)
        assert sheet.width > 64  # a grid, not one cell

    def test_a_render_writes_its_frames(self, tmp_path):
        mcp = server_mod.create_server(self._render_conn(["front", "side"]))
        run(mcp.call_tool("maya_render_scene", {
            "angles": ["front", "side"], "path": str(tmp_path / "shot.png"),
        }))
        assert (tmp_path / "shot_front.png").exists()
        assert (tmp_path / "shot_side.png").exists()

    def test_a_render_sheet_writes_one_sheet(self, tmp_path):
        conn = FakeConn(responses={"render_sheet": {
            "images": [{"angle": "three_quarter", "label": label,
                        "png_b64": self._subject_png()}
                       for label in ("|kit_a", "|kit_b")],
            "camera_positions": [], "renderer": "hw2", "samples": 2,
            "fallback_light": False, "zoom": 1.0, "relit_lights": 0,
        }})
        mcp = server_mod.create_server(conn)
        target = tmp_path / "kit.png"
        run(mcp.call_tool("maya_render_sheet", {
            "subjects": ["|kit_a", "|kit_b"], "path": str(target),
        }))
        assert target.exists()

    def test_a_bad_path_costs_nothing_because_it_is_caught_first(self, tmp_path):
        """A rendered frame is seconds and a sheet is seconds times the kit.
        Discovering a typo'd path after the pixels exist would throw all of
        that away, so the path is validated before Maya is asked anything."""
        conn = self._capture_conn(["front"])
        mcp = server_mod.create_server(conn)
        with pytest.raises(Exception, match="does not exist"):
            run(mcp.call_tool("maya_capture_viewport", {
                "angles": ["front"], "path": str(tmp_path / "nope" / "hero.png"),
            }))
        assert conn.calls == []  # Maya was never asked to capture
        assert not (tmp_path / "nope").exists()

    def test_no_path_writes_nothing_and_still_returns_the_image(self, tmp_path):
        mcp = server_mod.create_server(self._capture_conn(["front"]))
        result = run(mcp.call_tool("maya_capture_viewport", {"angles": ["front"]}))
        assert result.is_error is False
        assert [c for c in result.content if getattr(c, "type", None) == "image"]
        assert list(tmp_path.iterdir()) == []
        text = " ".join(c.text for c in result.content
                        if getattr(c, "type", None) == "text")
        assert "wrote:" not in text


class TestRenderTimeoutIsReachable:
    """#640-5: 29 Arnold cells exceeded the limit, and the timeout error told the
    caller to pass a larger timeout_s that no schema offered - and that no
    ceiling would have honoured, since the default WAS the dispatcher's maximum.
    """

    @staticmethod
    def _sheet_conn():
        return FakeConn(responses={"render_sheet": {
            "images": [{"angle": "three_quarter", "label": "|kit_a",
                        "png_b64": TestImageToolsWriteFiles._subject_png()}],
            "camera_positions": [], "renderer": "arnold", "samples": 2,
            "fallback_light": False, "zoom": 1.0, "relit_lights": 0,
        }})

    def test_a_sheet_defaults_to_the_render_timeout(self):
        conn = self._sheet_conn()
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool("maya_render_sheet", {"subjects": ["|kit_a"]}))
        assert conn.calls[0]["timeout_s"] == server_mod.RENDER_TIMEOUT_S

    def test_a_sheet_can_be_given_longer(self):
        conn = self._sheet_conn()
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool("maya_render_sheet", {
            "subjects": ["|kit_a"], "timeout_s": 1500.0,
        }))
        assert conn.calls[0]["timeout_s"] == 1500.0

    def test_render_scene_takes_one_too(self):
        conn = FakeConn(responses={"render_scene": {
            "images": [], "camera_positions": [], "renderer": "arnold",
            "samples": 3, "fallback_light": False, "zoom": 1.0, "relit_lights": 0,
        }})
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool("maya_render_scene", {
            "angles": ["front"], "timeout_s": 1200.0,
        }))
        assert conn.calls[0]["timeout_s"] == 1200.0

    def test_the_ceiling_is_the_dispatchers_ceiling(self):
        """Above the dispatcher's MAX_TIMEOUT_S the plugin silently clamps, so a
        schema that accepted more would be promising something it cannot keep."""
        from maya_plugin import dispatcher

        assert server_mod.MAX_RENDER_TIMEOUT_S == dispatcher.MAX_TIMEOUT_S

    def test_asking_past_the_ceiling_is_refused_rather_than_clamped(self):
        conn = self._sheet_conn()
        mcp = server_mod.create_server(conn)
        with pytest.raises(Exception):
            run(mcp.call_tool("maya_render_sheet", {
                "subjects": ["|kit_a"],
                "timeout_s": server_mod.MAX_RENDER_TIMEOUT_S + 1.0,
            }))
        assert conn.calls == []


class TestUvAtlasPatchAcceptsAnInteger:
    """#640-3: `patch: 0` was refused by the handler with an error naming the
    integer form it had just been handed - the schema typed it as `object`, which
    constrains nothing and coerces nothing."""

    @staticmethod
    def _conn():
        return FakeConn(responses={"uv_atlas": {
            "meshes": [], "atlas": [4, 4], "patch": [0, 0],
            "patch_rect": [0.0, 0.75, 0.25, 1.0], "margin": 0.02,
            "projection": "auto", "normalized": True, "all_inside": True,
        }})

    def test_a_bare_integer_index_reaches_maya(self):
        conn = self._conn()
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool("maya_uv_atlas", {"names": ["|chunk"], "patch": 0}))
        assert conn.calls[0]["params"]["patch"] == 0

    def test_a_col_row_pair_still_works(self):
        conn = self._conn()
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool("maya_uv_atlas", {"names": ["|chunk"], "patch": [2, 1]}))
        assert conn.calls[0]["params"]["patch"] == [2, 1]

    def test_a_numeric_string_is_coerced_to_the_integer_it_is(self):
        """The exact failure: the number arrived as text. A typed union coerces
        it; `object` passed it straight through to a handler that refused it."""
        conn = self._conn()
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool("maya_uv_atlas", {"names": ["|chunk"], "patch": "0"}))
        assert conn.calls[0]["params"]["patch"] == 0

    def test_the_schema_declares_a_type_at_all(self):
        """`object` is why nothing coerced. If this reverts, the tool goes back
        to accepting anything and failing deep in the handler."""
        mcp = server_mod.create_server(self._conn())
        tool = next(t for t in run(mcp.list_tools()) if t.name == "maya_uv_atlas")
        schema = tool.input_schema["properties"]["patch"]
        assert schema != {}, "patch has no type constraint at all"
        declared = json.dumps(schema)
        assert "integer" in declared


class TestCaptureViewportTargetReachesMaya:
    def test_target_is_forwarded(self):
        conn = FakeConn(responses={
            "capture_viewport": {"images": [], "camera_positions": []}
        })
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool("maya_capture_viewport", {
            "angles": ["front"], "target": ["|golem|chest"],
        }))
        assert conn.calls[0]["params"]["target"] == ["|golem|chest"]
        assert conn.calls[0]["params"]["isolate"] is None


class TestRiggingTools:
    def test_create_skeleton_marshals_the_chain_form(self):
        conn = FakeConn(responses={"create_skeleton": {
            "root": "|s_01",
            "joints": [{"name": "|s_01", "position": [0, 0, 0],
                        "parent": None, "orient": [0, 0, 0]}],
            "warnings": []}})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_create_skeleton", {
            "chain": [[0, 0, 0], [0, 1, 0]], "chain_prefix": "s"}))
        assert conn.calls[0]["cmd"] == "create_skeleton"
        assert conn.calls[0]["params"]["chain"] == [[0, 0, 0], [0, 1, 0]]

    def test_bind_skin_defaults_travel(self):
        conn = FakeConn(responses={"bind_skin": {
            "mesh": "|m", "root": "|r", "skin_cluster": "mSkin",
            "influences": ["|r"], "unweighted_vertices": 0,
            "max_influences_exceeded": 0,
            "per_joint": [{"joint": "|r", "vertices": 8, "mean_weight": 1.0}],
            "warnings": []}})
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool("maya_bind_skin", {"mesh": "m", "root": "r"}))
        params = conn.calls[0]["params"]
        assert params["max_influences"] == 4
        assert params["method"] == "closestDistance"

    def test_pose_and_reset_round_trip(self):
        conn = FakeConn(responses={
            "pose_skeleton": {"applied": 1, "joints": [],
                              "max_displacement": 0.5,
                              "displaced_vertices": 12, "warnings": []},
            "reset_pose": {"reset": True, "max_displacement": 0.5,
                           "warnings": []}})
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool("maya_pose_skeleton", {
            "root": "r", "rotations": {"a": [0, 0, 10]}}))
        run(mcp.call_tool("maya_reset_pose", {"root": "r"}))
        assert [c["cmd"] for c in conn.calls] == ["pose_skeleton", "reset_pose"]

    def test_weight_report_marshals_and_validates(self):
        conn = FakeConn(responses={"weight_report": {
            "mesh": "|h", "skin_cluster": "hSkin", "vertices": 8,
            "max_influences": 4, "unweighted_vertices": 0,
            "unweighted_sample": [], "max_influences_exceeded": 0,
            "exceeded_sample": [], "max_weight_sum_error": 0.0,
            "histogram": [{"influences": 2, "vertices": 8}],
            "per_joint": [{"joint": "|r|a", "vertices": 8, "mean_weight": 0.5}],
            "warnings": []}})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_weight_report", {"mesh": "|h"}))
        assert conn.calls[0]["cmd"] == "weight_report"
        assert conn.calls[0]["params"] == {"mesh": "|h"}
        assert result.structured_content["vertices"] == 8

    def test_mirror_weights_marshals_and_validates(self):
        conn = FakeConn(responses={"mirror_weights": {
            "mesh": "|h", "skin_cluster": "hSkin", "axis": "x",
            "direction": "+to-", "mirrored_vertices": 4, "on_plane_vertices": 2,
            "unpaired_vertices": 0, "changed_vertices": 3,
            "unweighted_vertices": 0, "warnings": []}})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_mirror_weights", {"mesh": "|h"}))
        assert conn.calls[0]["cmd"] == "mirror_weights"
        assert conn.calls[0]["params"] == {
            "mesh": "|h", "axis": "x", "direction": "+to-"}
        assert result.structured_content["mirrored_vertices"] == 4

    def test_smooth_weights_omits_joints_when_unset(self):
        conn = FakeConn(responses={"smooth_weights": {
            "mesh": "|h", "skin_cluster": "hSkin", "iterations": 1,
            "smoothed_vertices": 8, "changed_vertices": 5,
            "unweighted_vertices": 0, "max_influences_exceeded": 0,
            "warnings": []}})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_smooth_weights", {"mesh": "|h"}))
        assert conn.calls[0]["cmd"] == "smooth_weights"
        assert conn.calls[0]["params"] == {"mesh": "|h", "iterations": 1}
        assert result.structured_content["smoothed_vertices"] == 8

    def test_smooth_weights_forwards_joints_verbatim_when_given(self):
        conn = FakeConn(responses={"smooth_weights": {
            "mesh": "|h", "skin_cluster": "hSkin", "iterations": 2,
            "smoothed_vertices": 3, "changed_vertices": 2,
            "unweighted_vertices": 0, "max_influences_exceeded": 0,
            "warnings": []}})
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool(
            "maya_smooth_weights",
            {"mesh": "|h", "joints": ["|r|hip"], "iterations": 2}))
        assert conn.calls[0]["cmd"] == "smooth_weights"
        assert conn.calls[0]["params"] == {
            "mesh": "|h", "iterations": 2, "joints": ["|r|hip"]}

    def test_set_region_weights_marshals_radius_mode_params(self):
        conn = FakeConn(responses={"set_region_weights": {
            "mesh": "|h", "skin_cluster": "hSkin", "joint": "|r|a",
            "vertices_in_region": 5, "changed_vertices": 5,
            "sole_owner_vertices": 0, "unweighted_vertices": 0,
            "max_influences_exceeded": 0,
            "warnings": []}})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_set_region_weights", {
            "mesh": "|h", "joint": "a", "weight": 1.0,
            "within_radius_of": [0, 4, 0], "radius": 1.0,
            "falloff": "none"}))
        assert conn.calls[0]["cmd"] == "set_region_weights"
        assert conn.calls[0]["params"] == {
            "mesh": "|h", "joint": "a", "weight": 1.0,
            "within_radius_of": [0, 4, 0], "radius": 1.0, "falloff": "none"}
        assert result.structured_content["vertices_in_region"] == 5

    def test_set_region_weights_omits_optional_params_when_unset(self):
        conn = FakeConn(responses={"set_region_weights": {
            "mesh": "|h", "skin_cluster": "hSkin", "joint": "|r|b",
            "vertices_in_region": 2, "changed_vertices": 2,
            "sole_owner_vertices": 0, "unweighted_vertices": 0,
            "max_influences_exceeded": 0,
            "warnings": []}})
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool("maya_set_region_weights", {
            "mesh": "|h", "joint": "b", "weight": 1.0, "faces": [0, 1]}))
        assert conn.calls[0]["cmd"] == "set_region_weights"
        assert conn.calls[0]["params"] == {
            "mesh": "|h", "joint": "b", "weight": 1.0, "faces": [0, 1]}

    def test_pose_ik_marshals_and_omits_optionals(self):
        conn = FakeConn(responses={"pose_ik": {
            "achieved_position": [0.1, 0.6, 0.2], "residual": 0.0004,
            "rotations": {"|p|h": [0.0, 41.0, 0.0]},
            "chain": ["|p|h", "|p|h|k", "|p|h|k|a"],
            "pole_used": [0.1, 0.5, 0.5], "kept": True,
            "max_displacement": 0.31, "displaced_vertices": 140,
            "per_mesh": [{"mesh": "|m", "max_displacement": 0.31,
                          "displaced_vertices": 140}],
            "warnings": []}})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_pose_ik", {
            "root": "p", "joint": "a", "target": [0.1, 0.6, 0.2]}))
        assert conn.calls[0]["cmd"] == "pose_ik"
        assert conn.calls[0]["params"] == {
            "root": "p", "joint": "a", "target": [0.1, 0.6, 0.2],
            "keep": True}
        assert result.structured_content["residual"] == 0.0004

    def test_pose_ik_forwards_pole_start_keep(self):
        conn = FakeConn(responses={"pose_ik": {
            "achieved_position": [0, 0, 0], "residual": 0.9,
            "rotations": {}, "chain": [], "pole_used": None, "kept": False,
            "max_displacement": 0.0, "displaced_vertices": 0,
            "per_mesh": [], "warnings": ["keep=false: restored"]}})
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool("maya_pose_ik", {
            "root": "p", "joint": "a", "target": [0, 0, 0],
            "pole": [0, 0, 1], "start": "hip", "keep": False}))
        params = conn.calls[0]["params"]
        assert params["pole"] == [0, 0, 1]
        assert params["start"] == "hip"
        assert params["keep"] is False

    def test_author_physics_marshals_and_omits_optionals(self):
        conn = FakeConn(responses={"author_physics": {
            "bodies": [{
                "chunk": "|golem|pelvis", "parent": None,
                "mass": 0.372, "volume": 0.372, "signed_volume": 0.372,
                "com": [0.0, 1.86, 0.03],
                "watertight": True, "open_edges": 0,
                "verts": 382, "tris": 760,
                "collider": {"kind": "capsule", "centre": [0.0, 1.86, 0.0],
                             "rotation_deg": [-26.3, 0.0, 180.0],
                             "size": None, "radius": 0.47, "height": 1.16,
                             "axis": [0.0, 1.0, 0.0],
                             "volume_ratio": 1.72, "max_escape": 0.02},
                "joint": None}],
            "density": 1.0, "total_volume": 0.372, "warnings": []}})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_author_physics",
                                   {"root": "golem"}))
        assert conn.calls[0]["cmd"] == "author_physics"
        assert conn.calls[0]["params"] == {"root": "golem", "density": 1.0}
        body = result.structured_content["bodies"][0]
        assert body["collider"]["kind"] == "capsule"
        assert body["joint"] is None

    def test_author_physics_forwards_chunks_overrides_exclude(self):
        conn = FakeConn(responses={"author_physics": {
            "bodies": [], "density": 2.0, "total_volume": 0.0,
            "warnings": ["w"]}})
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool("maya_author_physics", {
            "chunks": ["a", "b"], "density": 2.0,
            "exclude": ["tracer"],
            "overrides": {"b": {"parent": "a",
                                "hinge_axis": [1, 0, 0],
                                "hinge_range_deg": [0, 110]}}}))
        params = conn.calls[0]["params"]
        assert params["chunks"] == ["a", "b"]
        assert params["density"] == 2.0
        assert params["exclude"] == ["tracer"]
        # PhysicsOverride round-trips with the None fields dropped
        assert params["overrides"] == {"b": {
            "parent": "a", "hinge_axis": [1.0, 0.0, 0.0],
            "hinge_range_deg": [0.0, 110.0]}}


class TestBlendshapeTools:
    def test_create_marshals_targets_and_returns_measured(self):
        conn = FakeConn(responses={"create_blendshape": {
            "mesh": "|humanoid", "blend_shape": "humanoid_shapes",
            "targets": [{"name": "brow_raise", "max_delta": 0.05,
                         "vertex_count": 33414}],
            "warnings": []}})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_create_blendshape", {
            "mesh": "|humanoid",
            "targets": [{"name": "brow_raise",
                         "target_mesh": "|humanoid_brow"}]}))
        params = conn.calls[0]["params"]
        assert conn.calls[0]["cmd"] == "create_blendshape"
        assert params["targets"] == [{"name": "brow_raise",
                                      "target_mesh": "|humanoid_brow"}]
        payload = result.structured_content
        assert payload["targets"][0]["max_delta"] == 0.05

    def test_set_weights_marshals_and_returns_measured(self):
        conn = FakeConn(responses={"set_blendshape_weights": {
            "mesh": "|humanoid", "blend_shape": "humanoid_shapes",
            "weights": {"brow_raise": 0.5},
            "max_displacement": 0.024,
            "per_target": [{"name": "brow_raise", "weight": 0.5,
                            "max_displacement": 0.024}],
            "warnings": []}})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_set_blendshape_weights", {
            "mesh": "|humanoid", "weights": {"brow_raise": 0.5}}))
        assert conn.calls[0]["params"] == {"mesh": "|humanoid",
                                           "weights": {"brow_raise": 0.5}}
        assert result.structured_content["max_displacement"] == 0.024

    def test_annotations(self):
        mcp = server_mod.create_server(FakeConn())
        by_name = {t.name: t for t in run(mcp.list_tools())}
        create = by_name["maya_create_blendshape"].annotations
        assert (create.read_only_hint, create.destructive_hint,
                create.idempotent_hint) == (False, True, False)
        weigh = by_name["maya_set_blendshape_weights"].annotations
        assert (weigh.read_only_hint, weigh.destructive_hint,
                weigh.idempotent_hint) == (False, True, True)


def _export_result_stub():
    return {
        "path": "x.fbx", "bytes": 1234, "fbx_version": 7700,
        "node_count": 3, "mesh_count": 1, "root_nodes": ["|golem_arm"],
        "unit_scale_factor": 100.0, "metres_per_unit": 1.0,
    }


def _export_result_with(**overrides):
    """Push a handler response through the real maya_export_fbx tool and
    back into ExportFbxResult - proving a field the wire carries survives
    the round trip rather than vanishing at the extra='ignore' boundary
    (#757)."""
    conn = FakeConn(
        responses={"export_fbx": dict(_export_result_stub(), **overrides)}
    )
    mcp = server_mod.create_server(conn)
    result = run(
        mcp.call_tool("maya_export_fbx", {"path": "x.fbx", "metres_per_unit": 1.0})
    )
    return schemas.ExportFbxResult(**result.structured_content)


def _capture_request(fn):
    """Call fn(tool), where tool(**kwargs) invokes maya_export_fbx through
    the real server, and return the params FakeConn recorded."""
    conn = FakeConn(responses={"export_fbx": _export_result_stub()})
    mcp = server_mod.create_server(conn)
    fn(lambda **kwargs: run(mcp.call_tool("maya_export_fbx", kwargs)))
    return conn.calls[0]


def _bake_result_stub():
    return {
        "meshes": ["|body"], "out_dir": "C:/out", "resolution": 1024,
        "baked": [], "skipped_file_backed": [],
        "checkpoint_id": "001_auto_bake_textures", "warnings": [],
    }


def _bake_result_with(**overrides):
    """Push a handler response through the real maya_bake_textures tool and
    back into BakeTexturesResult - proving a field the wire carries survives
    the round trip rather than vanishing at the extra='ignore' boundary
    (#757)."""
    conn = FakeConn(
        responses={"bake_textures": dict(_bake_result_stub(), **overrides)}
    )
    mcp = server_mod.create_server(conn)
    result = run(
        mcp.call_tool("maya_bake_textures",
                      {"meshes": ["|body"], "out_dir": "C:/out"})
    )
    return schemas.BakeTexturesResult(**result.structured_content)


def _bake_capture_request(fn):
    """Call fn(tool), where tool(**kwargs) invokes maya_bake_textures through
    the real server, and return the params FakeConn recorded."""
    conn = FakeConn(responses={"bake_textures": _bake_result_stub()})
    mcp = server_mod.create_server(conn)
    fn(lambda **kwargs: run(mcp.call_tool("maya_bake_textures", kwargs)))
    return conn.calls[0]


class TestClipTools:
    def _author_result(self):
        return {"root": "|pelvis", "clip": "walk", "fps": 30,
                "duration_s": 1.2, "frames": 37, "keyed_joints": 8,
                "keyed_weight_channels": ["blink"],
                "root_position_keyed": True, "interpolation": "smooth",
                "loop": True, "start_frame": 39, "end_frame": 75,
                "clips": ["idle", "walk"], "padded_channels": [],
                "held_channels": [],
                "back_filled": {"clips": [], "channels": []},
                "replaced": "idle",
                "per_key": [{"time_s": 0.0, "max_displacement": 0.0},
                            {"time_s": 1.2, "max_displacement": 0.31}],
                "warnings": []}

    def test_author_marshals_keys_and_returns_measured(self):
        conn = FakeConn(responses={"author_clip": self._author_result()})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_author_clip", {
            "root": "|pelvis", "name": "walk", "fps": 30, "loop": True,
            "interpolation": "smooth",
            "keys": [
                {"time_s": 0.0, "rotations": {"L_hip": [0, -25, 0]},
                 "root_position": [0, 0.97, 0],
                 "blend_weights": {"blink": 0.0}},
                {"time_s": 1.2, "rotations": {"L_hip": [0, -25, 0]},
                 "root_position": [0, 0.97, 0],
                 "blend_weights": {"blink": 0.0}},
            ]}))
        params = conn.calls[0]["params"]
        assert conn.calls[0]["cmd"] == "author_clip"
        assert params["keys"][0]["rotations"] == {"L_hip": [0, -25, 0]}
        assert params["keys"][0]["root_position"] == [0, 0.97, 0]
        assert result.structured_content["per_key"][1]["max_displacement"] == 0.31

    def test_delete_marshals(self):
        conn = FakeConn(responses={"delete_clip": {
            "root": "|pelvis", "clip": "walk", "clips": [],
            "deleted_curves": 27,
            "max_displacement": 0.31, "warnings": []}})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_delete_clip", {"root": "|pelvis"}))
        assert conn.calls[0]["cmd"] == "delete_clip"
        assert conn.calls[0]["params"]["name"] is None
        assert result.structured_content["deleted_curves"] == 27

    def test_delete_marshals_a_name(self):
        conn = FakeConn(responses={"delete_clip": {
            "root": "|pelvis", "clip": "idle", "clips": ["walk"],
            "deleted_curves": 0,
            "max_displacement": 0.0, "warnings": []}})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_delete_clip", {
            "root": "|pelvis", "name": "idle"}))
        assert conn.calls[0]["params"]["name"] == "idle"
        assert result.structured_content["clips"] == ["walk"]

    def test_preview_composites_one_sheet(self):
        png = png_b64(32, 32)
        conn = FakeConn(responses={"preview_clip": {
            "clip": "walk", "fps": 30,
            "frames": [{"frame": 0, "time_s": 0.0},
                       {"frame": 36, "time_s": 1.2}],
            "images": [{"label": "t=0.00s", "angle": "side", "png_b64": png},
                       {"label": "t=1.20s", "angle": "side",
                        "png_b64": png}],
            "renderer": "hw2", "samples": 1, "fallback_light": False,
            "zoom": 1.0, "relit_lights": 0}})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_preview_clip", {
            "root": "|pelvis", "name": "walk", "angle": "side"}))
        assert conn.calls[0]["params"]["name"] == "walk"
        # first content item is ONE image (the sheet), then the frame times
        assert len([c for c in result.content if c.type == "image"]) == 1
        text = " ".join(c.text for c in result.content if c.type == "text")
        assert "t=1.20s" in text

    def test_preview_forwards_zoom(self):
        # #695 fix wave: 320px default framing was unjudgeable in the gate;
        # zoom mirrors render_scene's and must reach the handler.
        png = png_b64(32, 32)
        conn = FakeConn(responses={"preview_clip": {
            "clip": "walk", "fps": 30,
            "frames": [{"frame": 0, "time_s": 0.0}],
            "images": [{"label": "t=0.00s", "angle": "side", "png_b64": png}],
            "renderer": "hw2", "samples": 1, "fallback_light": False,
            "zoom": 1.6, "relit_lights": 0}})
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool("maya_preview_clip", {
            "root": "|pelvis", "name": "walk", "angle": "side", "zoom": 1.6}))
        assert conn.calls[0]["params"]["zoom"] == 1.6

    def test_preview_forwards_handler_warnings(self):
        # #757: same gap as render_scene - the #721 hygiene warning existed
        # at the dispatcher layer and never reached the tool's content.
        png = png_b64(32, 32)
        conn = FakeConn(responses={"preview_clip": {
            "clip": "walk", "fps": 30,
            "frames": [{"frame": 0, "time_s": 0.0}],
            "images": [{"label": "t=0.00s", "angle": "side", "png_b64": png}],
            "renderer": "hw2", "samples": 1, "fallback_light": False,
            "zoom": 1.0, "relit_lights": 0,
            "warnings": ["closed the Arnold RenderView window after "
                         "rendering (#721)"]}})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_preview_clip", {
            "root": "|pelvis", "name": "walk"}))
        text = " ".join(c.text for c in result.content if c.type == "text")
        assert "note: closed the Arnold RenderView window" in text

    def test_export_gains_include_animation(self):
        conn = FakeConn(responses={"export_fbx": dict(
            _export_result_stub(), animation=None)})
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool("maya_export_fbx", {
            "path": "D:/x/clip.fbx", "metres_per_unit": 1.0,
            "include_animation": True}))
        assert conn.calls[0]["params"]["include_animation"] is True

    def test_annotations(self):
        mcp = server_mod.create_server(FakeConn())
        by_name = {t.name: t for t in run(mcp.list_tools())}
        author = by_name["maya_author_clip"].annotations
        assert (author.read_only_hint, author.destructive_hint,
                author.idempotent_hint) == (False, True, False)
        delete = by_name["maya_delete_clip"].annotations
        assert (delete.read_only_hint, delete.destructive_hint,
                delete.idempotent_hint) == (False, True, True)
        preview = by_name["maya_preview_clip"].annotations
        assert (preview.read_only_hint, preview.destructive_hint,
                preview.idempotent_hint) == (True, False, True)


class TestAuthorClipTimeoutIsReachable:
    """#721: author_clip's own timeout error tells the caller to pass a larger
    timeout_s, and no schema offered one. The #640-5 fix applied to the clip
    tools - keying a long clip on a heavy scene, or keying at all while an
    Arnold RenderView (IPR) re-renders on every scene mutation, outlives 120 s.
    """

    def _conn(self):
        return FakeConn(responses={"author_clip": {
            "root": "|pelvis", "clip": "idle", "fps": 30,
            "duration_s": 1.0, "frames": 31, "keyed_joints": 3,
            "keyed_weight_channels": [], "root_position_keyed": False,
            "interpolation": "linear", "loop": False,
            "start_frame": 0, "end_frame": 30, "clips": ["idle"],
            "padded_channels": [], "held_channels": [],
            "back_filled": {"clips": [], "channels": []},
            "replaced": None,
            "per_key": [{"time_s": 0.0, "max_displacement": 0.0},
                        {"time_s": 1.0, "max_displacement": 0.12}],
            "warnings": []}})

    @staticmethod
    def _keys():
        return [{"time_s": 0.0, "rotations": {"jnt_a": [0, 0, 0]}},
                {"time_s": 1.0, "rotations": {"jnt_a": [0, 30, 0]}}]

    def test_the_schema_offers_one(self):
        mcp = server_mod.create_server(self._conn())
        tool = next(t for t in run(mcp.list_tools())
                    if t.name == "maya_author_clip")
        props = tool.input_schema["properties"]
        assert "timeout_s" in props, sorted(props)
        assert props["timeout_s"]["default"] == 120

    def test_it_defaults_to_the_bool_timeout(self):
        conn = self._conn()
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool("maya_author_clip", {
            "root": "|pelvis", "name": "idle", "keys": self._keys()}))
        assert conn.calls[0]["timeout_s"] == server_mod.BOOL_TIMEOUT_S

    def test_it_can_be_given_longer(self):
        conn = self._conn()
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool("maya_author_clip", {
            "root": "|pelvis", "name": "idle", "keys": self._keys(),
            "timeout_s": 900.0}))
        assert conn.calls[0]["timeout_s"] == 900.0

    def test_asking_past_the_dispatchers_ceiling_is_refused(self):
        conn = self._conn()
        mcp = server_mod.create_server(conn)
        with pytest.raises(Exception):
            run(mcp.call_tool("maya_author_clip", {
                "root": "|pelvis", "name": "idle", "keys": self._keys(),
                "timeout_s": server_mod.MAX_RENDER_TIMEOUT_S + 1.0}))
        assert conn.calls == []


class TestMultiTakeSurface:
    """#718: one rig carries N clips, and the surface has to say so."""

    def test_delete_clip_takes_an_optional_name(self):
        mcp = server_mod.create_server(FakeConn())
        tools = {t.name: t for t in run(mcp.list_tools())}
        schema = tools["maya_delete_clip"].input_schema
        assert "name" in schema["properties"]
        assert "name" not in schema.get("required", [])
        assert "every clip" in schema["properties"]["name"]["description"]

    def test_author_clip_says_clips_no_longer_replace_each_other(self):
        mcp = server_mod.create_server(FakeConn())
        tools = {t.name: t for t in run(mcp.list_tools())}
        desc = tools["maya_author_clip"].description
        assert "APPENDED" in desc or "appended" in desc
        assert "ONE file" in desc or "one file" in desc

    def test_author_clip_result_reports_the_range_it_took(self):
        from maya_mcp.schemas import AuthorClipResult

        fields = AuthorClipResult.model_fields
        for name in ("start_frame", "end_frame", "clips", "padded_channels",
                     "back_filled"):
            assert name in fields, sorted(fields)

    def test_take_records_carry_their_place_on_the_timeline(self):
        from maya_mcp.schemas import AnimFacts, DeleteClipResult, TakeRecord

        assert "start_s" in TakeRecord.model_fields
        assert "stop_s" in TakeRecord.model_fields
        assert "clips" in AnimFacts.model_fields
        assert "clips" in DeleteClipResult.model_fields

    def test_export_result_clips_survive_the_round_trip(self):
        # AnimFacts declares model_config = ConfigDict(extra="ignore"), which
        # is exactly why "clips" had to be a DECLARED field on it: without
        # the declaration, pydantic silently strips the per-clip block the
        # export handler composes and no caller ever sees it. A bare
        # `"clips" in AnimFacts.model_fields` check cannot catch that
        # regression if the handler and the schema drift apart under a
        # renamed key - this test pushes a realistic payload through the
        # real maya_export_fbx tool (FakeConn -> call_tool ->
        # ExportFbxResult.model_validate, the same path a real call takes)
        # and asserts the two clips come out with every field intact.
        conn = FakeConn(responses={"export_fbx": {
            "path": "x.fbx", "bytes": 4321, "fbx_version": 7700,
            "node_count": 5, "mesh_count": 1, "root_nodes": ["|pelvis"],
            "unit_scale_factor": 100.0, "metres_per_unit": 1.0,
            "animation": {
                "stacks": 1, "layers": 1, "curves": 14, "curve_nodes": 14,
                "takes": [], "targets": [],
                "clips": [
                    {"name": "idle", "start_frame": 0, "end_frame": 30,
                     "duration_s": 1.0, "curves": 6},
                    {"name": "walk", "start_frame": 31, "end_frame": 91,
                     "duration_s": 2.0, "curves": 8},
                ],
            },
        }})
        mcp = server_mod.create_server(conn)
        result = run(
            mcp.call_tool(
                "maya_export_fbx",
                {"path": "x.fbx", "metres_per_unit": 1.0,
                 "include_animation": True},
            )
        )
        clips = result.structured_content["animation"]["clips"]
        assert len(clips) == 2
        idle, walk = clips
        assert idle["name"] == "idle"
        assert idle["start_frame"] == 0
        assert idle["end_frame"] == 30
        assert idle["duration_s"] == 1.0
        assert idle["curves"] == 6
        assert walk["name"] == "walk"
        assert walk["start_frame"] == 31
        assert walk["end_frame"] == 91
        assert walk["duration_s"] == 2.0
        assert walk["curves"] == 8

    def test_target_take_survives_the_round_trip(self):
        # #718 Task 10b: AnimCurveTarget gained "take" - the name of the
        # AnimationStack a curve record is attributed to. AnimCurveTarget
        # declares model_config = ConfigDict(extra="ignore") (same as
        # AnimFacts above), which is exactly why "take" had to be a
        # DECLARED field: without it, pydantic would silently strip the
        # attribution export_fbx's byte gate now depends on before any
        # caller ever saw it (the same sibling-field trap "clips" hit).
        # Pushed through the real maya_export_fbx tool end to end, the same
        # path a real call takes, with one target attributed to a named
        # take and one carrying no attribution at all.
        conn = FakeConn(responses={"export_fbx": {
            "path": "x.fbx", "bytes": 4321, "fbx_version": 7700,
            "node_count": 5, "mesh_count": 1, "root_nodes": ["|pelvis"],
            "unit_scale_factor": 100.0, "metres_per_unit": 1.0,
            "animation": {
                "stacks": 1, "layers": 1, "curves": 3, "curve_nodes": 2,
                "takes": [], "clips": [],
                "targets": [
                    {"target": "L_hip", "property": "Lcl Rotation",
                     "curves": 3, "key_count": 31, "duration_s": 1.0,
                     "take": "idle"},
                    {"target": "orphan", "property": "Lcl Rotation",
                     "curves": 3, "key_count": None, "duration_s": None,
                     "take": None},
                ],
            },
        }})
        mcp = server_mod.create_server(conn)
        result = run(
            mcp.call_tool(
                "maya_export_fbx",
                {"path": "x.fbx", "metres_per_unit": 1.0,
                 "include_animation": True},
            )
        )
        targets = result.structured_content["animation"]["targets"]
        assert len(targets) == 2
        attributed, orphan = targets
        assert attributed["target"] == "L_hip"
        assert attributed["take"] == "idle"
        assert orphan["target"] == "orphan"
        assert orphan["take"] is None


class TestCurveFormTools:
    def test_maya_create_curve_form_forwards_params(self):
        conn = FakeConn(responses={"create_curve_form": {
            "name": "|horn", "faces": 512, "verts": 514, "watertight": True,
            "stations": 2, "worst_station_deviation": 0.004,
            "worst_station": "path[1]", "form_size": 1.1, "warnings": [],
        }})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_create_curve_form", {
            "kind": "sweep", "name": "horn",
            "path": [[0, 0, 0], [0, 1, 0], [0.4, 1.6, 0]],
            "width": [[0.0, 0.3], [1.0, 0.05]],
        }))
        assert result.is_error is False
        assert conn.calls[0]["cmd"] == "create_curve_form"
        sent = conn.calls[0]["params"]
        assert sent["kind"] == "sweep"
        assert sent["width"] == [[0.0, 0.3], [1.0, 0.05]]
        # Unset optionals arrive as None, never invented defaults (#669 lesson)
        assert sent["profile"] is None and sent["sections"] is None
        assert sent["twist"] is None
        assert sent["degrees"] is None and sent["axis"] is None
        assert result.structured_content["worst_station_deviation"] == 0.004

    def test_maya_create_curve_form_revolve_defaults(self):
        conn = FakeConn(responses={"create_curve_form": {
            "name": "|vase", "faces": 576, "verts": 578, "watertight": True,
            "stations": 8, "worst_station_deviation": 0.002,
            "worst_station": "profile[2]@90", "form_size": 1.25,
            "warnings": [],
        }})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_create_curve_form", {
            "kind": "revolve", "name": "vase",
            "profile": [[0.3, 0.0], [0.5, 0.4], [0.2, 1.25]],
        }))
        assert result.is_error is False
        # Handler-side validate_spec applies the 360/"y" defaults; the wire
        # carries None when the caller left them unset (#669 lesson).
        assert conn.calls[0]["params"]["degrees"] is None
        assert conn.calls[0]["params"]["axis"] is None
        assert conn.calls[0]["params"]["cap_ends"] is True


class TestRetargetTools:
    def test_maya_retarget_clip_forwards_params(self):
        conn = FakeConn(responses={"retarget_clip": {
            "clip": "walk01", "root": "|rig|Hips", "frames": 121, "fps": 30,
            "source_joints": 31,
            "measures": {"name": "walk01", "fps": 30, "frames_sampled": 121,
                         "loop": False, "rig_height": 1.7,
                         "thresholds": {}, "joints": {}, "contacts": {},
                         "symmetry": [], "warnings": []},
            "warnings": [],
        }})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_retarget_clip", {
            "file": "evals/mocap_fixtures/cmu_walk.bvh",
            "root": "|rig|Hips", "clip": "walk01",
        }))
        assert result.is_error is False
        assert conn.calls[0]["cmd"] == "retarget_clip"
        sent = conn.calls[0]["params"]
        assert sent == {
            "file": "evals/mocap_fixtures/cmu_walk.bvh",
            "root": "|rig|Hips", "clip": "walk01",
            "start": None, "end": None, "fps": None,
        }
        assert conn.calls[0]["timeout_s"] == server_mod.EXPORT_TIMEOUT_S
        assert result.structured_content["frames"] == 121
        assert result.structured_content["measures"]["rig_height"] == 1.7

    def test_maya_retarget_clip_forwards_start_end_fps_when_set(self):
        conn = FakeConn(responses={"retarget_clip": {
            "clip": "walk01", "root": "|rig|Hips", "frames": 61, "fps": 24,
            "source_joints": 31, "measures": {}, "warnings": [],
        }})
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool("maya_retarget_clip", {
            "file": "evals/mocap_fixtures/cmu_walk.bvh",
            "root": "|rig|Hips", "clip": "walk01",
            "start": 10, "end": 70, "fps": 24,
        }))
        sent = conn.calls[0]["params"]
        assert sent["start"] == 10 and sent["end"] == 70 and sent["fps"] == 24

    def test_maya_clean_clip_forwards_params(self):
        conn = FakeConn(responses={"clean_clip": {
            "clip": "walk01", "root": "|rig|Hips",
            "passes": ["filter", "lock_contacts"],
            "before": {"rig_height": 1.7}, "after": {"rig_height": 1.7},
            "checkpoint_id": "007_clean_clip", "warnings": [],
        }})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_clean_clip", {
            "root": "|rig|Hips", "clip": "walk01",
        }))
        assert result.is_error is False
        assert conn.calls[0]["cmd"] == "clean_clip"
        sent = conn.calls[0]["params"]
        # filter/lock_contacts are the cap_ends-style literal-default
        # exceptions (#768 ruling) - wire-defaulted True, never None.
        assert sent == {
            "root": "|rig|Hips", "clip": "walk01",
            "filter": True, "lock_contacts": True,
        }
        assert conn.calls[0]["timeout_s"] == server_mod.EXPORT_TIMEOUT_S
        assert result.structured_content["checkpoint_id"] == "007_clean_clip"

    def test_maya_clean_clip_forwards_explicit_filter_and_lock_contacts(self):
        conn = FakeConn(responses={"clean_clip": {
            "clip": "walk01", "root": "|rig|Hips", "passes": ["filter"],
            "before": {}, "after": {}, "checkpoint_id": "008_clean_clip",
            "warnings": [],
        }})
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool("maya_clean_clip", {
            "root": "|rig|Hips", "clip": "walk01",
            "filter": {"window": 7}, "lock_contacts": False,
        }))
        sent = conn.calls[0]["params"]
        assert sent["filter"] == {"window": 7}
        assert sent["lock_contacts"] is False
