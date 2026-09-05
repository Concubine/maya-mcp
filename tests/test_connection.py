"""Connection tests: framing over real sockets, reconnect, timeout, token.

Runs a fake plugin (real TCP server speaking the wire protocol) in a thread —
no Maya required.
"""

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
        frame = srv.frames[0]
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
        assert srv.frames[0]["timeout_adjustable"] is True
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
        # transparent fresh connection on the next call
        assert conn.request("c", {}, timeout_s=5) == {"echo": {}}
        assert srv.connections == 2
        conn.close()

    def test_response_timeout_raises_and_next_request_gets_fresh_connection(self, plugin):
        stall = {"flag": True}

        def responder(frame):
            if stall["flag"]:
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
