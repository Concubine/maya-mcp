"""End-to-end tests: real plugin socket server <-> real MayaConnection client.

No Maya: the plugin degrades gracefully headless (direct-call executor, no
undo hooks), and execute_python is pure Python — so the full M0 spine
(client -> TCP -> dispatcher -> handler -> response) is exercised for real.
"""

import logging
import os
import socket

import pytest

from maya_mcp.connection import MayaConnection, MayaError
from maya_plugin import logsetup, maya_mcp_plugin
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
        # #604: the wire carries the LOADED identity too - what this session
        # imported, not just what is on disk at ping time. Here nothing was
        # redeployed mid-test, so the two must coincide.
        assert plugin["loaded_digest"] == plugin["digest"]
        assert plugin["restart_required"] is False
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

    def test_bad_log_level_does_not_crash_setup(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MAYA_MCP_LOG_LEVEL", "trace ")
        # MAYA_MCP_LOG_DIR keeps this out of the user's real ~/.maya-mcp/logs,
        # which it used to write a stray pytest-process log into (#650).
        monkeypatch.setenv("MAYA_MCP_LOG_DIR", str(tmp_path))
        maya_mcp_plugin._setup_logging()  # must not raise

        from maya_mcp import server as server_mod

        server_mod._setup_logging()  # must not raise

        # Each process logs to its own file now, so the two never contend.
        pid = os.getpid()
        for handler in (
            maya_mcp_plugin.log.handlers + logging.getLogger("maya_mcp").handlers
        ):
            if isinstance(handler, logsetup.ResilientRotatingFileHandler):
                assert handler.baseFilename.endswith("-%d.log" % pid)
                handler.close()
        maya_mcp_plugin.log.handlers = []
        logging.getLogger("maya_mcp").handlers = []



class TestStartServerWaitsForTheAutoloads:
    """#820: a plugin load flushes Maya's undo queue, and the deferred
    autoloads run for ~7 s after userSetup - so a port that listens before
    they settle accepts edits that cannot be undone. start_server defers the
    bind until two plugin counts AUTOLOAD_SETTLE_S apart agree. Headless
    (_plugin_count() is None) it binds at once, which is what every other
    test in this file relies on."""

    def test_headless_binds_immediately(self):
        srv = maya_mcp_plugin.start_server(port=0)
        try:
            assert srv is not None
        finally:
            maya_mcp_plugin.stop_server()

    def test_a_changing_plugin_count_defers_the_bind(self, monkeypatch):
        counts = iter([16, 41, 53, 53])
        deferred = []
        monkeypatch.setattr(maya_mcp_plugin, "_plugin_count", lambda: next(counts))
        monkeypatch.setattr(maya_mcp_plugin, "_defer",
                            lambda seconds, fn, *args: deferred.append((seconds, fn, args)))
        # 16 vs None: defer, carrying 16
        assert maya_mcp_plugin.start_server(port=0) is None
        assert deferred[-1][0] == maya_mcp_plugin.AUTOLOAD_SETTLE_S
        assert deferred[-1][1] is maya_mcp_plugin.start_server
        assert deferred[-1][2][-1] == 16
        # the deferred call: 41 vs 16, defer again; then 53 vs 41; then 53 == 53 binds
        for expected in (41, 53):
            args = deferred[-1][2]
            assert maya_mcp_plugin.start_server(*args) is None
            assert deferred[-1][2][-1] == expected
        args = deferred[-1][2]
        srv = maya_mcp_plugin.start_server(*args)
        try:
            assert srv is not None and len(deferred) == 3
        finally:
            maya_mcp_plugin.stop_server()

    def test_wait_can_be_switched_off(self, monkeypatch):
        monkeypatch.setattr(maya_mcp_plugin, "_plugin_count", lambda: 16)
        monkeypatch.setattr(maya_mcp_plugin, "_defer",
                            lambda *a: (_ for _ in ()).throw(AssertionError("deferred")))
        srv = maya_mcp_plugin.start_server(port=0, wait_for_autoloads=False)
        try:
            assert srv is not None
        finally:
            maya_mcp_plugin.stop_server()


class TestTheListenerOutlivesAResetClient:
    """#863, the variant measured on 2026-09-06: an agent Maya answered a
    ping and fifteen minutes later refused connections with the process
    still alive. PluginServer._accept_loop broke on ANY non-timeout OSError
    from accept() and closed the listening socket - and Windows raises
    ConnectionResetError from accept() when a client resets the connection
    before the accept completes (a port scanner, a client that connects
    and dies, a health check that hangs up). One stray reset ended the
    listener for the life of the process, silently."""

    def test_a_client_that_resets_before_accept_does_not_kill_the_listener(
            self, plugin_server):
        import struct
        import time

        srv = plugin_server()
        for _ in range(40):
            s = socket.socket()
            # SO_LINGER (on, 0): close() sends RST instead of FIN.
            s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            s.connect(("127.0.0.1", srv.port))
            s.close()
        time.sleep(0.5)
        conn = MayaConnection(port=srv.port, connect_timeout_s=2.0)
        assert conn.request("ping", {}, timeout_s=5)["pong"] is True
        conn.close()

    def test_a_transient_accept_error_is_logged_and_the_loop_goes_on(
            self, plugin_server, caplog):
        import time

        srv = plugin_server()
        real = srv._sock

        class FlakyOnce:
            """The listening socket, with ONE accept() that fails the way a
            reset client makes it fail on Windows."""

            def __init__(self):
                self.failed = False

            def accept(self):
                if not self.failed:
                    self.failed = True
                    raise ConnectionResetError(10054, "forcibly closed by the remote host")
                return real.accept()

            def __getattr__(self, name):
                return getattr(real, name)

        flaky = FlakyOnce()
        with caplog.at_level(logging.WARNING, logger="maya_mcp_plugin"):
            srv._sock = flaky
            deadline = time.monotonic() + 3.0
            while not flaky.failed and time.monotonic() < deadline:
                time.sleep(0.05)
            assert flaky.failed
            conn = MayaConnection(port=srv.port, connect_timeout_s=2.0)
            assert conn.request("ping", {}, timeout_s=5)["pong"] is True
            conn.close()
        srv._sock = real
        assert any("accept" in r.getMessage() and "10054" in r.getMessage()
                   for r in caplog.records), [r.getMessage() for r in caplog.records]

    def test_stop_still_ends_the_loop(self, plugin_server):
        # The fix must not turn stop()'s own close into an endless retry.
        import time

        srv = plugin_server()
        srv.stop()
        deadline = time.monotonic() + 3.0
        while srv._accept_thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not srv._accept_thread.is_alive()


class TestPingSaysWhoAnswered:
    """#862: three maya.exe were up on one machine and one held unsaved work
    from another worktree; the only way to ask 'who are you' was
    execute_python against the very process in doubt. ping's process block
    now carries the working directory and whether the scene is modified,
    so the session_info tool can answer the question without touching the
    scene. Headless: no scene, so modified is None and the cwd is ours."""

    def test_ping_carries_cwd_and_the_modified_flag(self, plugin_server):
        srv = plugin_server()
        conn = MayaConnection(port=srv.port)
        info = conn.request("ping", {}, timeout_s=5)["process"]
        assert info["cwd"] == os.getcwd()
        assert info["scene_modified"] is None  # no Maya to ask
        assert info["pid"] == os.getpid()
        conn.close()


class TestADeadListeningSocketIsRebound:
    """#863: a transient accept() error is ridden out (above); a LISTENING
    socket that is itself dead - EBADF, WSAENOTSOCK - cannot be, so the
    loop binds a fresh one on the same port instead of ending, and says so
    in the log. Only stop() ends the loop."""

    def test_a_not_a_socket_error_rebinds_on_the_same_port(self, plugin_server, caplog):
        import time

        srv = plugin_server()
        port = srv.port
        real = srv._sock

        class DeadOnce:
            def __init__(self):
                self.failed = False

            def accept(self):
                if not self.failed:
                    self.failed = True
                    raise OSError(10038, "An operation was attempted on something that is not a socket")
                return real.accept()

            def __getattr__(self, name):
                return getattr(real, name)

        dead = DeadOnce()
        with caplog.at_level(logging.WARNING, logger="maya_mcp_plugin"):
            srv._sock = dead
            deadline = time.monotonic() + 3.0
            while (not dead.failed or srv._sock is dead) and time.monotonic() < deadline:
                time.sleep(0.05)
            assert srv._sock is not dead  # a fresh socket replaced it
            assert srv.port == port
            conn = MayaConnection(port=port, connect_timeout_s=2.0)
            assert conn.request("ping", {}, timeout_s=5)["pong"] is True
            conn.close()
        assert any("re-bound" in r.getMessage() for r in caplog.records), \
            [r.getMessage() for r in caplog.records]


class TestAColdConnectNamesTheProcessItKnew:
    """#862, the other half: after a drop, the NEXT call's connect is refused
    too - and that message used to be the launch instructions, as if Maya
    had never been started. The handshake ping on every fresh connection
    (below) means the pid is known by then."""

    def test_the_handshake_learns_the_pid_before_any_request(self, plugin_server):
        srv = plugin_server()
        conn = MayaConnection(port=srv.port)
        conn.request("execute_python", {"code": "1"}, timeout_s=10)
        assert conn.last_pid == os.getpid()
        conn.close()

    def test_a_refused_connect_after_a_known_pid_says_whether_it_lives(self, plugin_server):
        srv = plugin_server()
        port = srv.port
        conn = MayaConnection(port=port, connect_timeout_s=0.5)
        conn.request("ping", {}, timeout_s=5)
        assert conn.last_pid == os.getpid()
        srv.stop()
        with pytest.raises(Exception):
            conn.request("ping", {}, timeout_s=5)  # the drop
        with pytest.raises(Exception) as exc_info:
            conn.request("ping", {}, timeout_s=5)  # the cold connect
        msg = str(exc_info.value)
        assert "pid %d" % os.getpid() in msg and "still running" in msg, msg
        assert "start_server" in msg and "Make sure Maya is open" not in msg
