"""Dispatcher tests: request handling, timeouts, busy flag, undo hooks.

Pure Python — the dispatcher never imports maya; the main-thread executor and
undo hooks are injected (the real plugin injects maya.utils / maya.cmds).
"""

import threading
import time

import pytest

from maya_plugin import protocol
from maya_plugin.dispatcher import Dispatcher, HandlerError


def make_dispatcher(handlers, **kwargs):
    d = Dispatcher(handlers=handlers, **kwargs)
    return d


def req(cmd, params=None, timeout_s=5.0, **extra):
    frame = protocol.make_request(cmd, params if params is not None else {}, timeout_s)
    frame.update(extra)
    return frame


@pytest.fixture
def dispatcher(request):
    created = []

    def factory(handlers, **kwargs):
        d = Dispatcher(handlers=handlers, **kwargs)
        created.append(d)
        return d

    yield factory
    for d in created:
        d.shutdown()


class TestBasicDispatch:
    def test_ok_result_echoes_id_and_wraps_result(self, dispatcher):
        d = dispatcher({"ping": lambda params: {"pong": True}})
        frame = req("ping")
        resp = d.handle_request(frame)
        assert resp["status"] == "ok"
        assert resp["id"] == frame["id"]
        assert resp["result"] == {"pong": True}
        assert isinstance(resp["elapsed_ms"], int)

    def test_params_passed_to_handler(self, dispatcher):
        seen = {}

        def echo(params):
            seen.update(params)
            return {"got": params["x"]}

        d = dispatcher({"echo": echo})
        resp = d.handle_request(req("echo", {"x": 7}))
        assert resp["result"] == {"got": 7}
        assert seen == {"x": 7}

    def test_missing_params_defaults_to_empty_dict(self, dispatcher):
        d = dispatcher({"ping": lambda params: {"params": params}})
        frame = req("ping")
        del frame["params"]
        assert d.handle_request(frame)["result"] == {"params": {}}

    def test_unknown_cmd_errors_with_hint_listing_commands(self, dispatcher):
        d = dispatcher({"ping": lambda p: {}, "capture": lambda p: {}})
        resp = d.handle_request(req("nope"))
        assert resp["status"] == "error"
        assert resp["error"]["type"] == "UnknownCommandError"
        assert "capture" in resp["error"]["hint"] and "ping" in resp["error"]["hint"]

    def test_unsupported_version_rejected(self, dispatcher):
        d = dispatcher({"ping": lambda p: {}})
        resp = d.handle_request(req("ping", v=999))
        assert resp["status"] == "error"
        assert resp["error"]["type"] == "ProtocolVersionError"

    def test_handler_runs_through_injected_main_thread_executor(self, dispatcher):
        calls = []

        def executor(fn):
            calls.append("exec")
            return fn()

        d = dispatcher({"ping": lambda p: {"pong": 1}}, main_thread_exec=executor)
        assert d.handle_request(req("ping"))["status"] == "ok"
        assert calls == ["exec"]


class TestErrors:
    def test_handler_exception_returns_full_traceback(self, dispatcher):
        def boom(params):
            raise RuntimeError("kaboom in handler")

        d = dispatcher({"boom": boom})
        resp = d.handle_request(req("boom"))
        assert resp["status"] == "error"
        assert resp["error"]["type"] == "RuntimeError"
        assert resp["error"]["message"] == "kaboom in handler"
        tb = resp["error"]["maya_traceback"]
        assert "Traceback" in tb and "kaboom in handler" in tb and "boom" in tb

    def test_handler_error_carries_hint_without_traceback(self, dispatcher):
        def missing(params):
            raise HandlerError(
                "object pCube7 not found",
                hint="call maya_get_scene_graph to list objects",
            )

        d = dispatcher({"missing": missing})
        resp = d.handle_request(req("missing"))
        assert resp["error"]["type"] == "HandlerError"
        assert resp["error"]["hint"] == "call maya_get_scene_graph to list objects"
        assert "maya_traceback" not in resp["error"]


class TestToken:
    def test_wrong_or_missing_token_rejected(self, dispatcher):
        d = dispatcher({"ping": lambda p: {}}, token="s3cret")
        assert d.handle_request(req("ping"))["error"]["type"] == "AuthError"
        assert d.handle_request(req("ping", token="nope"))["error"]["type"] == "AuthError"

    def test_correct_token_accepted(self, dispatcher):
        d = dispatcher({"ping": lambda p: {"pong": 1}}, token="s3cret")
        assert d.handle_request(req("ping", token="s3cret"))["status"] == "ok"


class TestUndoHooks:
    def test_undo_chunk_wraps_handler_and_closes_on_error(self, dispatcher):
        events = []
        d = dispatcher(
            {
                "ok": lambda p: events.append("handler") or {},
                "bad": lambda p: (_ for _ in ()).throw(ValueError("x")),
            },
            undo_open=lambda: events.append("open"),
            undo_close=lambda: events.append("close"),
        )
        d.handle_request(req("ok"))
        assert events == ["open", "handler", "close"]
        events.clear()
        resp = d.handle_request(req("bad"))
        assert resp["status"] == "error"
        assert events == ["open", "close"]


class TestTimeoutAndBusy:
    def test_timeout_returns_structured_error_then_busy_then_recovers(self, dispatcher):
        release = threading.Event()

        def slow(params):
            release.wait(5.0)
            return {"late": True}

        d = dispatcher({"slow": slow, "ping": lambda p: {"pong": 1}})

        resp = d.handle_request(req("slow", timeout_s=0.05))
        assert resp["status"] == "error"
        assert resp["error"]["type"] == "TimeoutError"
        assert "still" in resp["error"]["hint"] or "busy" in resp["error"]["hint"]

        # While the straggler runs, new requests are refused as busy
        busy = d.handle_request(req("ping"))
        assert busy["status"] == "error"
        assert busy["error"]["type"] == "BusyError"

        # Once the straggler finishes, the session recovers
        release.set()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            resp = d.handle_request(req("ping"))
            if resp["status"] == "ok":
                break
            time.sleep(0.01)
        assert resp["status"] == "ok"
        assert resp["result"] == {"pong": 1}

    def test_late_result_never_mismatched_to_new_request(self, dispatcher):
        release = threading.Event()

        def slow(params):
            release.wait(5.0)
            return {"who": "slow"}

        d = dispatcher({"slow": slow, "fast": lambda p: {"who": "fast"}})
        d.handle_request(req("slow", timeout_s=0.05))
        release.set()
        time.sleep(0.2)  # let the straggler finish and its result be dropped
        resp = d.handle_request(req("fast"))
        assert resp["status"] == "ok"
        assert resp["result"] == {"who": "fast"}


class TestOneInFlight:
    def test_second_request_during_execution_is_busy_not_queued(self, dispatcher):
        started = threading.Event()
        release = threading.Event()
        ran = []

        def slow(params):
            started.set()
            release.wait(5.0)
            return {"who": "slow"}

        def tracked(params):
            ran.append("tracked")
            return {}

        d = dispatcher({"slow": slow, "tracked": tracked})
        result = {}
        t = threading.Thread(
            target=lambda: result.update(d.handle_request(req("slow", timeout_s=5.0)))
        )
        t.start()
        assert started.wait(2.0)

        # slow is executing (not timed out): a concurrent request must be
        # rejected as busy, not silently queued behind it
        busy = d.handle_request(req("tracked"))
        assert busy["status"] == "error"
        assert busy["error"]["type"] == "BusyError"

        release.set()
        t.join(timeout=2.0)
        assert result["status"] == "ok"
        assert ran == []  # the rejected request never executed

        # session recovered
        assert d.handle_request(req("tracked"))["status"] == "ok"
        assert ran == ["tracked"]

    def test_non_string_cmd_is_unknown_command_not_crash(self, dispatcher):
        d = dispatcher({"ping": lambda p: {}})
        resp = d.handle_request(req("x", v=1) | {"cmd": ["ping"]})
        assert resp["status"] == "error"
        assert resp["error"]["type"] == "UnknownCommandError"

    def test_shutdown_rejects_new_requests_immediately(self, dispatcher):
        d = dispatcher({"ping": lambda p: {"pong": 1}})
        assert d.handle_request(req("ping"))["status"] == "ok"
        d.shutdown()
        start = time.monotonic()
        resp = d.handle_request(req("ping", timeout_s=30.0))
        elapsed = time.monotonic() - start
        assert elapsed < 1.0  # immediate, not a 30s stall against a dead worker
        assert resp["status"] == "error"
        assert resp["error"]["type"] == "ServerStoppedError"


def test_no_undo_chunk_handler_skips_hooks():
    calls = []

    def normal(params):
        return {"ok": 1}

    def exempt(params):
        return {"ok": 2}

    exempt.no_undo_chunk = True

    d = Dispatcher(
        {"normal": normal, "exempt": exempt},
        undo_open=lambda: calls.append("open"),
        undo_close=lambda: calls.append("close"),
    )
    try:
        d.handle_request({"v": 1, "id": "a", "cmd": "normal", "params": {}})
        assert calls == ["open", "close"]
        d.handle_request({"v": 1, "id": "b", "cmd": "exempt", "params": {}})
        assert calls == ["open", "close"]  # unchanged: hooks skipped
    finally:
        d.shutdown()
