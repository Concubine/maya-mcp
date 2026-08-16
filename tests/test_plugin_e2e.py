"""End-to-end tests: real plugin socket server <-> real MayaConnection client.

No Maya: the plugin degrades gracefully headless (direct-call executor, no
undo hooks), and execute_python is pure Python — so the full M0 spine
(client -> TCP -> dispatcher -> handler -> response) is exercised for real.
"""

import os
import socket

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

    def test_ping_identifies_which_copy_of_the_plugin_is_running(self, plugin_server):
        """The staleness handshake: a caller must be able to tell whether a green
        result came from its own code or from a deployed copy weeks behind it."""
        from maya_plugin import version

        srv = plugin_server()
        conn = MayaConnection(port=srv.port)
        plugin = conn.request("ping", {}, timeout_s=5)["plugin"]
        assert plugin["package_dir"] == os.path.dirname(os.path.abspath(version.__file__))
        assert version.compare(plugin, plugin["digest"]) is None
        assert version.compare(plugin, "a-different-tree") is not None
        conn.close()

    def test_ping_says_which_process_is_answering(self, plugin_server):
        """maya-mcp #648: a port is not an identity. Two Mayas on one machine
        lost a bind race silently because nothing in the protocol said whose
        process was on the other end."""
        srv = plugin_server()
        conn = MayaConnection(port=srv.port)
        process = conn.request("ping", {}, timeout_s=5)["process"]
        assert process["pid"] == os.getpid()
        assert process["port"] == srv.port
        assert process["host"] == "127.0.0.1"
        assert process["uptime_s"] >= 0.0
        assert process["scene"] is None  # headless: Maya cannot answer
        conn.close()

    def test_a_taken_port_fails_loudly_instead_of_starting_a_deaf_maya(self, plugin_server):
        """The losing Maya used to come up looking normal with no plugin, while
        the winner answered calls meant for it. The failure now says who to ask."""
        srv = plugin_server()
        with pytest.raises(maya_mcp_plugin.PortInUseError) as exc_info:
            maya_mcp_plugin.PluginServer("127.0.0.1", srv.port, None)
        message = str(exc_info.value)
        assert str(srv.port) in message
        assert "OwningProcess" in message  # how to find the process that won

    def test_start_server_prints_the_bind_failure_before_raising(self, capsys):
        # userSetup starts the plugin via executeDeferred, where a bare
        # traceback is easy to miss.
        holder = socket.create_server(("127.0.0.1", 0))
        previous = maya_mcp_plugin._active_server
        maya_mcp_plugin._active_server = None
        try:
            with pytest.raises(maya_mcp_plugin.PortInUseError):
                maya_mcp_plugin.start_server(port=holder.getsockname()[1])
            assert "could NOT bind" in capsys.readouterr().out
        finally:
            maya_mcp_plugin._active_server = previous
            holder.close()

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


class TestHardening:
    def test_stop_while_client_connected_fails_fast_and_restart_recovers(
        self, plugin_server
    ):
        import time

        srv = plugin_server()
        port = srv.port
        conn = MayaConnection(port=port)
        assert conn.request("ping", {}, timeout_s=5)["pong"] is True

        srv.stop()  # client connection still open — must be force-closed
        start = time.monotonic()
        with pytest.raises(Exception):
            conn.request("execute_python", {"code": "1"}, timeout_s=30)
        assert time.monotonic() - start < 2.0  # fail fast, not a 30s stall

        srv2 = maya_mcp_plugin.start_server(port=port)
        try:
            assert conn.request("ping", {}, timeout_s=5)["pong"] is True
        finally:
            srv2.stop()
        conn.close()

    def test_auth_error_closes_the_connection(self, plugin_server):
        srv = plugin_server(token="hunter2")
        bad = MayaConnection(port=srv.port, token="wrong")
        with pytest.raises(MayaError) as exc_info:
            bad.request("ping", {}, timeout_s=5)
        assert exc_info.value.error_type == "AuthError"
        # server must have dropped the connection after answering: the next
        # request on the cached socket dies at transport level, not AuthError
        from maya_mcp.connection import MayaConnectionError

        with pytest.raises(MayaConnectionError):
            bad.request("ping", {}, timeout_s=5)
        bad.close()

    def test_oversized_inbound_frame_closes_connection(self, plugin_server):
        import socket
        import struct

        srv = plugin_server()
        with socket.create_connection(("127.0.0.1", srv.port), timeout=2) as raw:
            raw.sendall(struct.pack(">I", 32 * 1024 * 1024))  # 32MB claim, no body
            raw.settimeout(2.0)
            assert raw.recv(4096) == b""  # closed without buffering the body

    def test_half_sent_frame_hits_body_deadline(self, plugin_server):
        import socket
        import struct
        import time

        srv = plugin_server(body_deadline_s=0.3)
        with socket.create_connection(("127.0.0.1", srv.port), timeout=5) as raw:
            raw.sendall(struct.pack(">I", 100))  # promise 100 bytes...
            raw.sendall(b"only a few")  # ...deliver 10, then stall
            raw.settimeout(5.0)
            start = time.monotonic()
            assert raw.recv(4096) == b""  # server gives up and closes
            assert time.monotonic() - start < 3.0

    def test_failed_bind_leaks_no_dispatcher_thread(self):
        import socket
        import threading

        before = sum(
            1 for t in threading.enumerate() if t.name == "maya-mcp-dispatch"
        )
        blocker = socket.create_server(("127.0.0.1", 0))
        try:
            with pytest.raises(OSError):
                maya_mcp_plugin.start_server(port=blocker.getsockname()[1])
            after = sum(
                1 for t in threading.enumerate() if t.name == "maya-mcp-dispatch"
            )
            assert after == before
        finally:
            blocker.close()

    def test_bad_log_level_does_not_crash_setup(self, monkeypatch):
        monkeypatch.setenv("MAYA_MCP_LOG_LEVEL", "trace ")
        maya_mcp_plugin._setup_logging()  # must not raise

        from maya_mcp import server as server_mod

        server_mod._setup_logging()  # must not raise
