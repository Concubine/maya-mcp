"""End-to-end tests: real plugin socket server <-> real MayaConnection client.

No Maya: the plugin degrades gracefully headless (direct-call executor, no
undo hooks), and execute_python is pure Python — so the full M0 spine
(client -> TCP -> dispatcher -> handler -> response) is exercised for real.
"""

import pytest

from maya_mcp.connection import MayaConnection, MayaError
from maya_plugin import maya_mcp_plugin
from maya_plugin.handlers import code_exec


@pytest.fixture
def plugin_server():
    servers = []

    def start(**kwargs):
        srv = maya_mcp_plugin.start_server(port=0, **kwargs)
        servers.append(srv)
        return srv

    yield start
    for srv in servers:
        srv.stop()
    code_exec.reset_namespace()


class TestLoop:
    def test_execute_python_round_trip(self, plugin_server):
        srv = plugin_server()
        conn = MayaConnection(port=srv.port)
        result = conn.request("execute_python", {"code": "6 * 7"}, timeout_s=10)
        assert result["result_repr"] == "42"
        conn.close()

    def test_namespace_persists_across_wire_calls(self, plugin_server):
        srv = plugin_server()
        conn = MayaConnection(port=srv.port)
        conn.request("execute_python", {"code": "snowman_parts = 3"}, timeout_s=10)
        result = conn.request("execute_python", {"code": "snowman_parts + 1"}, timeout_s=10)
        assert result["result_repr"] == "4"
        conn.close()

    def test_ping_reports_maya_availability(self, plugin_server):
        srv = plugin_server()
        conn = MayaConnection(port=srv.port)
        result = conn.request("ping", {}, timeout_s=5)
        assert result["pong"] is True
        assert result["maya"] is False  # headless test environment
        conn.close()

    def test_handler_needing_maya_returns_traceback_error(self, plugin_server):
        srv = plugin_server()
        conn = MayaConnection(port=srv.port)
        with pytest.raises(MayaError) as exc_info:
            conn.request("get_scene_graph", {}, timeout_s=10)
        assert exc_info.value.error_type == "ModuleNotFoundError"
        assert "maya" in str(exc_info.value)
        conn.close()

    def test_unknown_command_error_lists_available(self, plugin_server):
        srv = plugin_server()
        conn = MayaConnection(port=srv.port)
        with pytest.raises(MayaError) as exc_info:
            conn.request("sculpt_dragon", {}, timeout_s=5)
        assert exc_info.value.error_type == "UnknownCommandError"
        assert "execute_python" in exc_info.value.hint
        conn.close()


class TestTokenOverWire:
    def test_token_mismatch_rejected_match_accepted(self, plugin_server):
        srv = plugin_server(token="hunter2")
        bad = MayaConnection(port=srv.port, token="wrong")
        with pytest.raises(MayaError) as exc_info:
            bad.request("ping", {}, timeout_s=5)
        assert exc_info.value.error_type == "AuthError"
        bad.close()

        good = MayaConnection(port=srv.port, token="hunter2")
        assert good.request("ping", {}, timeout_s=5)["pong"] is True
        good.close()


class TestLifecycle:
    def test_stop_then_restart_on_same_port(self, plugin_server):
        srv = plugin_server()
        port = srv.port
        conn = MayaConnection(port=port)
        assert conn.request("ping", {}, timeout_s=5)["pong"] is True
        conn.close()
        srv.stop()

        srv2 = maya_mcp_plugin.start_server(port=port)
        try:
            conn2 = MayaConnection(port=port)
            assert conn2.request("ping", {}, timeout_s=5)["pong"] is True
            conn2.close()
        finally:
            srv2.stop()

    def test_multiple_sequential_client_connections(self, plugin_server):
        srv = plugin_server()
        for _ in range(3):
            conn = MayaConnection(port=srv.port)
            assert conn.request("ping", {}, timeout_s=5)["pong"] is True
            conn.close()

    def test_non_loopback_bind_without_token_refused(self):
        with pytest.raises(ValueError, match="token"):
            maya_mcp_plugin.start_server(host="0.0.0.0", port=0)
