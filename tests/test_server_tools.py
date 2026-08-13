"""MCP server tool tests: registration, annotations, marshaling, image returns.

Uses the real MCPServer with an injected fake connection — no Maya, no sockets.
"""

import asyncio
import base64
import io

import pytest
from PIL import Image as PILImage

from maya_mcp import server as server_mod


def png_b64(width=1024, height=1024):
    img = PILImage.new("RGB", (width, height), (140, 100, 70))
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
            "maya_transform",
            "maya_group",
            "maya_parent",
            "maya_rename",
            "maya_delete_objects",
            "maya_boolean_op",
            "maya_etch_text",
            "maya_sculpt_ops",
            "maya_deform",
            "maya_remesh_retopo",
            "maya_mesh_cleanup",
            "maya_set_viewport",
            "maya_set_camera",
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
