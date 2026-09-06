"""Dispatcher tests: request handling, timeouts, busy flag, undo hooks.

Pure Python — the dispatcher never imports maya; the main-thread executor and
undo hooks are injected (the real plugin injects maya.utils / maya.cmds).
"""

import re
import threading
import time

import pytest

from maya_plugin import protocol
from maya_plugin.dispatcher import Dispatcher, HandlerError, require_known_keys


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


class TestBusyHint:
    """redmine #577 fix: BusyError must be actionable, and the session must
    recover on its own once a straggler genuinely finishes (never before)."""

    def test_hint_names_stuck_command_while_genuinely_still_running(self, dispatcher):
        release = threading.Event()

        def slow(params):
            release.wait(5.0)
            return {}

        d = dispatcher({"slow": slow, "ping": lambda p: {}})
        d.handle_request(req("slow", timeout_s=0.05))
        try:
            # Still running: repeated requests keep refusing, each time
            # naming the stuck command and roughly how long it's been stuck.
            for _ in range(2):
                busy = d.handle_request(req("ping"))
                assert busy["status"] == "error"
                assert busy["error"]["type"] == "BusyError"
                hint = busy["error"]["hint"]
                assert "'slow'" in hint
                assert re.search(r"for \d+s", hint)
                assert "unblock automatically" in hint
                time.sleep(0.05)
        finally:
            release.set()

    def test_hint_flags_abnormally_long_stall_but_still_recovers(self, dispatcher, monkeypatch):
        import maya_plugin.dispatcher as dispatcher_mod

        # Lower the "this looks wedged" threshold so the test doesn't need
        # to actually wait ten-plus minutes to exercise that branch.
        monkeypatch.setattr(dispatcher_mod, "_LIKELY_WEDGED_S", 0.05)
        release = threading.Event()

        def slow(params):
            release.wait(5.0)
            return {"late": True}

        d = dispatcher({"slow": slow, "ping": lambda p: {}})
        d.handle_request(req("slow", timeout_s=0.02))
        time.sleep(0.15)  # now well past the (patched) wedged threshold

        busy = d.handle_request(req("ping"))
        assert busy["error"]["type"] == "BusyError"
        assert "restarting Maya" in busy["error"]["hint"]

        # Even a stall flagged as "likely wedged" still recovers the instant
        # the handler actually returns - the flag is informational only, it
        # never triggers an auto-clear.
        release.set()
        deadline = time.monotonic() + 2.0
        resp = None
        while time.monotonic() < deadline:
            resp = d.handle_request(req("ping"))
            if resp["status"] == "ok":
                break
            time.sleep(0.01)
        assert resp is not None and resp["status"] == "ok"


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


class TestRequireKnownKeys:
    """#764: an unread param does not fail, it succeeds and does something else.

    Measured: eleven tests passed `material=` to a handler whose explicit-name
    param is `name`. Every one created a differently-named material than it
    believed it was creating, and every one PASSED, because they read the name
    back out of the result rather than pinning it.
    """

    def test_it_says_nothing_when_every_key_is_read(self):
        assert require_known_keys(
            {"mesh": "|a", "name": "m"}, ("mesh", "shader", "name"),
            "assign_material") is None

    def test_an_unread_key_is_refused_by_name(self):
        with pytest.raises(HandlerError) as exc:
            require_known_keys({"mesh": "|a", "material": "m"},
                               ("mesh", "shader", "name"), "assign_material")
        assert "assign_material does not take 'material'" in str(exc.value)

    def test_the_hint_names_the_key_that_was_meant(self):
        # The realistic cause is a plausible SYNONYM, not a typo - and a
        # synonym is exactly what re-reading the call site cannot reveal.
        with pytest.raises(HandlerError) as exc:
            require_known_keys({"nam": "m"}, ("mesh", "name"), "assign_material")
        assert "did you mean 'name'?" in exc.value.hint

    def test_a_key_with_no_near_miss_still_lists_what_is_valid(self):
        with pytest.raises(HandlerError) as exc:
            require_known_keys({"colour": "red"}, ("mesh", "name"), "x")
        assert "valid params: mesh, name" in exc.value.hint

    def test_every_unread_key_is_named_not_just_the_first(self):
        with pytest.raises(HandlerError) as exc:
            require_known_keys({"a": 1, "b": 2}, ("mesh",), "x")
        assert "'a'" in str(exc.value) and "'b'" in str(exc.value)

    def test_a_recorded_synonym_is_named_outright(self):
        # The measured #764 case: `material` and `name` share not a single
        # letter in position, so no similarity test finds it. The answer is
        # recorded rather than guessed at.
        with pytest.raises(HandlerError) as exc:
            require_known_keys({"material": "clay"}, ("mesh", "name"),
                               "assign_material", {"material": "name"})
        assert "'material' is called 'name' here" in exc.value.hint



class TestACommandThatReadsNothingSaysSo:
    """#829: reset_namespace's refusal ended on the words "valid params: "
    and stopped, because it has none. Measured live - the hint named nothing
    at all, which reads as a bug in the error rather than a fact about the
    command."""

    def test_the_hint_states_the_fact_instead_of_trailing_off(self):
        with pytest.raises(HandlerError) as excinfo:
            require_known_keys({"confirm": True}, (), "reset_namespace")
        assert "reset_namespace does not take 'confirm'" in str(excinfo.value)
        assert "reads no params at all" in excinfo.value.hint
        assert not excinfo.value.hint.rstrip().endswith("valid params:")

    def test_a_command_with_params_still_lists_them(self):
        with pytest.raises(HandlerError) as excinfo:
            require_known_keys({"nope": 1}, ("name", "kind"), "create_primitive")
        assert "valid params: kind, name" in excinfo.value.hint


class TestTimeoutHintNamesOnlyAKnobTheCallerHas:
    """redmine #836: "pass a larger timeout_s (up to 1800 s)" was the hint for
    every command, and the bake tools had no timeout_s to pass - the hint sent
    the kethran run chasing a parameter that did not exist. The frame's
    timeout_adjustable flag says whether the caller had the knob."""

    def _slow_dispatcher(self, dispatcher):
        release = threading.Event()

        def slow(params):
            release.wait(5.0)
            return {}

        return dispatcher({"slow": slow}), release

    def test_a_caller_without_the_knob_is_told_to_split_the_work(self, dispatcher):
        d, release = self._slow_dispatcher(dispatcher)
        try:
            resp = d.handle_request(req("slow", timeout_s=0.05))
            hint = resp["error"]["hint"]
            assert "pass a larger timeout_s" not in hint   # the unfollowable advice
            assert "takes no timeout_s" in hint            # says so instead
            assert "budget" in hint and "split" in hint    # names the budget, offers the way out
        finally:
            release.set()

    def test_a_caller_with_the_knob_is_told_to_raise_it(self, dispatcher):
        d, release = self._slow_dispatcher(dispatcher)
        try:
            resp = d.handle_request(req("slow", timeout_s=0.05, timeout_adjustable=True))
            assert "pass a larger timeout_s" in resp["error"]["hint"]
        finally:
            release.set()


class TestStageInBusyHint:
    """redmine #836: a long handler reports the stage it is in
    (maya_plugin.progress) and the BusyError hint carries it, so a caller
    can tell "map 2 of 3, 380 s into it" from "wedged". The dispatcher
    clears the stage around every job: a stage never outlives the command
    that reported it, and an unmarked command never inherits a stale one."""

    def test_the_hint_carries_the_stage_and_how_long_it_has_stood(self, dispatcher):
        from maya_plugin import progress
        release = threading.Event()
        reported = threading.Event()

        def bake(params):
            progress.report("map 2 of 3: curvature 2048 for body")
            reported.set()
            release.wait(5.0)
            return {}

        d = dispatcher({"bake": bake, "ping": lambda p: {}})
        d.handle_request(req("bake", timeout_s=0.05))
        try:
            assert reported.wait(2.0)
            busy = d.handle_request(req("ping"))
            assert busy["error"]["type"] == "BusyError"
            hint = busy["error"]["hint"]
            assert "'bake'" in hint
            assert "map 2 of 3: curvature 2048 for body" in hint
            assert re.search(r"for \d+s", hint)
        finally:
            release.set()
        # once it finishes, the stage is gone with it
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and progress.current() is not None:
            time.sleep(0.01)
        assert progress.current() is None

    def test_a_stage_never_leaks_into_the_next_command(self, dispatcher):
        from maya_plugin import progress

        def bake(params):
            progress.report("map 1 of 1: ao 256 for body")
            return {}

        release = threading.Event()

        def slow(params):
            release.wait(5.0)
            return {}

        d = dispatcher({"bake": bake, "slow": slow, "ping": lambda p: {}})
        assert d.handle_request(req("bake"))["status"] == "ok"
        assert progress.current() is None
        d.handle_request(req("slow", timeout_s=0.05))
        try:
            busy = d.handle_request(req("ping"))
            assert busy["error"]["type"] == "BusyError"
            assert "map 1 of 1" not in busy["error"]["hint"]
        finally:
            release.set()
