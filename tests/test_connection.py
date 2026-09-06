"""Connection tests: framing over real sockets, reconnect, timeout, token.

Runs a fake plugin (real TCP server speaking the wire protocol) in a thread —
no Maya required.
"""

import os
import socket
import threading
import time

import pytest

from maya_plugin import protocol
from maya_mcp.connection import (
    MayaConnection,
    MayaConnectionError,
    MayaError,
    MayaTimeoutError,
)


class FakePlugin:
    """Minimal TCP server speaking the wire protocol; behavior via a responder fn."""

    def __init__(self, responder):
        self.responder = responder
        self.frames = []
        self.connections = 0
        self._srv = socket.create_server(("127.0.0.1", 0))
        self._srv.settimeout(0.2)
        self.port = self._srv.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                return  # a test closed the listener on purpose (#862)
            self.connections += 1
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()
        self._srv.close()

    def _client(self, conn):
        try:
            while True:
                frame = protocol.read_frame(lambda n: conn.recv(n))
                self.frames.append(frame)
                resp = self.responder(frame)
                if resp is None:
                    conn.close()
                    return
                conn.sendall(protocol.encode_frame(resp))
        except (protocol.ProtocolError, OSError):
            pass
        finally:
            conn.close()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=2)


def echo_responder(frame):
    return protocol.make_ok(frame["id"], {"echo": frame["params"]}, elapsed_ms=1)


@pytest.fixture
def plugin():
    servers = []

    def start(responder=echo_responder):
        srv = FakePlugin(responder)
        servers.append(srv)
        return srv

    yield start
    for s in servers:
        s.stop()


class TestRequests:
    def test_request_returns_result_and_sends_wellformed_frame(self, plugin):
        srv = plugin()
        conn = MayaConnection(port=srv.port)
        result = conn.request("ping", {"x": 1}, timeout_s=5)
        assert result == {"echo": {"x": 1}}
        # frames[0] is the identity handshake (#862); the request is next
        assert srv.frames[0]["cmd"] == "ping" and srv.frames[0]["params"] == {}
        frame = srv.frames[1]
        assert frame["v"] == protocol.PROTOCOL_VERSION
        assert frame["cmd"] == "ping"
        assert frame["params"] == {"x": 1}
        assert frame["timeout_s"] == 5
        assert "timeout_adjustable" not in frame
        conn.close()

    def test_request_carries_the_timeout_adjustable_flag(self, plugin):
        # redmine #836: only a tool that exposes timeout_s says so on the wire
        srv = plugin()
        conn = MayaConnection(port=srv.port)
        conn.request("ping", {}, timeout_s=5, timeout_adjustable=True)
        assert srv.frames[1]["timeout_adjustable"] is True  # [0] is the handshake
        conn.close()

    def test_persistent_connection_reused_across_requests(self, plugin):
        srv = plugin()
        conn = MayaConnection(port=srv.port)
        conn.request("a", {}, timeout_s=5)
        conn.request("b", {}, timeout_s=5)
        assert srv.connections == 1
        conn.close()

    def test_token_attached_when_configured(self, plugin):
        srv = plugin()
        conn = MayaConnection(port=srv.port, token="tok123")
        conn.request("ping", {}, timeout_s=5)
        assert srv.frames[0]["token"] == "tok123"
        conn.close()

    def test_error_response_raises_maya_error_with_details(self, plugin):
        def responder(frame):
            return protocol.make_error(
                frame["id"], "RuntimeError", "object not found",
                maya_traceback="Traceback (most recent call last): ...",
                hint="call maya_get_scene_graph",
            )

        srv = plugin(responder)
        conn = MayaConnection(port=srv.port)
        with pytest.raises(MayaError) as exc_info:
            conn.request("ping", {}, timeout_s=5)
        err = exc_info.value
        assert err.error_type == "RuntimeError"
        assert err.hint == "call maya_get_scene_graph"
        assert "Traceback" in err.maya_traceback
        # The formatted message must carry everything the LLM needs to self-correct
        text = str(err)
        assert "object not found" in text
        assert "call maya_get_scene_graph" in text
        assert "Traceback" in text
        conn.close()


class TestConnectionFailures:
    def test_nothing_listening_gives_actionable_error(self):
        with socket.socket() as s:  # grab a port that is then closed = nothing listening
            s.bind(("127.0.0.1", 0))
            dead_port = s.getsockname()[1]
        conn = MayaConnection(port=dead_port, connect_timeout_s=0.5)
        with pytest.raises(MayaConnectionError) as exc_info:
            conn.request("ping", {}, timeout_s=1)
        msg = str(exc_info.value)
        assert "Maya" in msg and "start_server" in msg  # launch instructions

    def test_reconnects_after_server_drops_connection(self, plugin):
        drop_next = {"flag": False}

        def responder(frame):
            if drop_next["flag"]:
                drop_next["flag"] = False
                return None  # close connection without replying
            return echo_responder(frame)

        srv = plugin(responder)
        conn = MayaConnection(port=srv.port)
        conn.request("a", {}, timeout_s=5)
        drop_next["flag"] = True
        with pytest.raises(MayaConnectionError):
            conn.request("b", {}, timeout_s=5)
        # transparent fresh connection on the next call. Three connections,
        # not two: the drop's diagnosis (#862) opens one probe connection to
        # learn that the plugin still listens, then the next call reconnects.
        assert conn.request("c", {}, timeout_s=5) == {"echo": {}}
        assert srv.connections == 3
        conn.close()

    def test_response_timeout_raises_and_next_request_gets_fresh_connection(self, plugin):
        stall = {"flag": True}

        def responder(frame):
            # Only the request under test stalls - the identity handshake (#862)
            # goes first on this connection and must not eat the stall.
            if stall["flag"] and frame["cmd"] == "slow":
                stall["flag"] = False
                time.sleep(3.0)  # far beyond the request timeout + grace
            return echo_responder(frame)

        srv = plugin(responder)
        conn = MayaConnection(port=srv.port, response_grace_s=0.1)
        with pytest.raises(MayaTimeoutError):
            conn.request("slow", {}, timeout_s=0.2)
        assert conn.request("fast", {}, timeout_s=5) == {"echo": {}}
        assert srv.connections == 2
        conn.close()

    def test_mismatched_response_id_is_rejected(self, plugin):
        def responder(frame):
            return protocol.make_ok("someone-else", {"stale": True}, elapsed_ms=1)

        srv = plugin(responder)
        conn = MayaConnection(port=srv.port)
        with pytest.raises(MayaConnectionError, match="mismatch"):
            conn.request("ping", {}, timeout_s=5)
        conn.close()


class TestSerialization:
    def test_concurrent_requests_are_serialized(self, plugin):
        active = {"now": 0, "max": 0}
        lock = threading.Lock()

        def responder(frame):
            with lock:
                active["now"] += 1
                active["max"] = max(active["max"], active["now"])
            time.sleep(0.05)
            with lock:
                active["now"] -= 1
            return echo_responder(frame)

        srv = plugin(responder)
        conn = MayaConnection(port=srv.port)
        threads = [
            threading.Thread(target=conn.request, args=("p", {}, 5)) for _ in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert active["max"] == 1
        conn.close()


class TestAMidRequestFailureSaysWhatHappened:
    """#862: 'it will be re-established on the next call' was said on every
    mid-request failure - including the two where the Maya process had
    died, nothing listened on the port, and the caller lost time retrying.
    After a failure the connection now finds out which of three things
    happened and says so: the listener still answers (retry is right), the
    port refuses and the last pid seen is gone (relaunch), or the port
    refuses while that pid still runs (the plugin server died inside a
    living Maya - start_server() or relaunch)."""

    @staticmethod
    def _drop_once_responder(after=None):
        state = {"drop": False}

        def responder(frame):
            if frame["cmd"] == "ping":
                return protocol.make_ok(frame["id"], {
                    "pong": True, "process": {"pid": state.get("pid"), "port": 0}}, elapsed_ms=1)
            if state["drop"]:
                state["drop"] = False
                if after:
                    after()
                return None
            return echo_responder(frame)

        return responder, state

    def test_a_dropped_socket_with_the_plugin_still_listening_says_retry(self, plugin):
        responder, state = self._drop_once_responder()
        srv = plugin(responder)
        conn = MayaConnection(port=srv.port)
        conn.request("a", {}, timeout_s=5)
        state["drop"] = True
        with pytest.raises(MayaConnectionError) as exc_info:
            conn.request("b", {}, timeout_s=5)
        msg = str(exc_info.value)
        assert "still accepts connections" in msg and "next call" in msg, msg
        assert "relaunch" not in msg.lower()
        assert conn.request("c", {}, timeout_s=5) == {"echo": {}}
        conn.close()

    def test_a_plugin_that_stopped_listening_says_relaunch(self, plugin):
        srv_box = {}
        responder, state = self._drop_once_responder(after=lambda: srv_box["srv"]._srv.close())
        srv = plugin(responder)
        srv_box["srv"] = srv
        conn = MayaConnection(port=srv.port, connect_timeout_s=0.5)
        conn.request("a", {}, timeout_s=5)
        state["drop"] = True
        with pytest.raises(MayaConnectionError) as exc_info:
            conn.request("b", {}, timeout_s=5)
        msg = str(exc_info.value)
        assert "nothing is listening" in msg and "%d" % srv.port in msg, msg
        assert "relaunch" in msg.lower() and "retry" in msg.lower(), msg
        assert "next call" not in msg

    def test_a_known_pid_that_is_alive_says_the_server_died_inside_maya(self, plugin):
        srv_box = {}
        responder, state = self._drop_once_responder(after=lambda: srv_box["srv"]._srv.close())
        state["pid"] = os.getpid()  # a process that is certainly alive: this one
        srv = plugin(responder)
        srv_box["srv"] = srv
        conn = MayaConnection(port=srv.port, connect_timeout_s=0.5)
        conn.request("ping", {}, timeout_s=5)  # the pid is learned from any ping that passes through
        assert conn.last_pid == os.getpid()
        state["drop"] = True
        with pytest.raises(MayaConnectionError) as exc_info:
            conn.request("b", {}, timeout_s=5)
        msg = str(exc_info.value)
        assert "pid %d" % os.getpid() in msg and "still running" in msg, msg
        assert "start_server" in msg and "retry" in msg.lower(), msg

    def test_a_known_pid_that_is_gone_says_the_process_died(self, plugin):
        srv_box = {}
        responder, state = self._drop_once_responder(after=lambda: srv_box["srv"]._srv.close())
        state["pid"] = _finished_pid()
        srv = plugin(responder)
        srv_box["srv"] = srv
        conn = MayaConnection(port=srv.port, connect_timeout_s=0.5)
        conn.request("ping", {}, timeout_s=5)
        state["drop"] = True
        with pytest.raises(MayaConnectionError) as exc_info:
            conn.request("b", {}, timeout_s=5)
        msg = str(exc_info.value)
        assert "pid %d" % state["pid"] in msg and "gone" in msg, msg
        assert "relaunch" in msg.lower() and "reopen" in msg.lower(), msg

    def test_process_alive_answers_for_this_process_and_a_finished_one(self):
        from maya_mcp import connection

        assert connection.process_alive(os.getpid()) is True
        assert connection.process_alive(_finished_pid()) is False


def _finished_pid():
    """The pid of a child that has already exited - a process that is
    certainly gone (pid reuse within the same test is not a real risk)."""
    import subprocess
    import sys

    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid
