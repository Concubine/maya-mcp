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
            "maya_capture_viewport",
            "maya_checkpoint",
            "maya_restore_checkpoint",
            "maya_undo",
            "maya_redo",
            "maya_new_scene",
            "maya_open_scene",
            "maya_save_scene",
            "maya_reset_namespace",
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
