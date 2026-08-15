"""MCP server tool tests: registration, annotations, marshaling, image returns.

Uses the real MCPServer with an injected fake connection — no Maya, no sockets.
"""

import asyncio
import base64
import io

import pytest
from PIL import Image as PILImage

from maya_mcp import refstore, server as server_mod


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
        assert conn.calls[0]["params"] == {"confirm": False}


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
            "rotate": None, "scale": None, "divisions": 1,
        }
        assert result.structured_content["name"] == "|golem_arm"

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
