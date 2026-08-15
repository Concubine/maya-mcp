"""evals/pivot_live.py's cleanup contract: the delete must fire on every
exit path, and it must target the name Maya actually assigned - never the
literal 'pivotGate' - because a missed cleanup that also queries the wrong
object on the next run is what let this class of bug survive undetected
before (see the task-3 review addendum).

Loads the real script by path, exactly as
TestEvalHarnessParsing._live_call() loads evals/live_call.py in
test_code_exec.py, then monkeypatches its `call` name so main() runs for
real against a stub - no socket, no Maya, and pivot_live.py itself is
untouched.
"""

import importlib.util
import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_pivot_live():
    path = os.path.join(REPO_ROOT, "evals", "pivot_live.py")
    spec = importlib.util.spec_from_file_location("evals_pivot_live", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _install_stub(monkeypatch, module, *, build_name="pivotGate7",
                   transform_result=None, build_raises=None, after_truncated=False):
    """Fake `call` answering the three execute_python queries and the one
    transform call pivot_live.main() makes, recording every execute_python
    call whose code deletes something plus every other execute_python code
    string, so tests can pin exactly which object name was addressed.
    """
    build_repr = repr(build_name)
    before_repr = "([2.0, 3.0, 4.0], [1.5, 2.5, 3.5, 2.5, 3.5, 4.5])"
    after_repr = "([0.0, 10.0, 0.0], [2.0, 3.0, 4.0], [1.5, 2.5, 3.5, 2.5, 3.5, 4.5])"
    calls = {"delete": [], "queries": []}

    def fake_call(command, params, timeout_s=60.0, port=None):
        if command == "execute_python":
            code = params["code"]
            if "cmds.delete" in code:
                calls["delete"].append(code)
                return {"result": {"result_repr": "'cleaned'", "result_truncated": False}}
            if "polyCube" in code:
                if build_raises is not None:
                    raise build_raises
                return {"result": {"result_repr": build_repr, "result_truncated": False}}
            calls["queries"].append(code)
            if "rotatePivot" in code:
                if after_truncated:
                    return {"result": {"result_repr": None, "result_truncated": True,
                                        "result_bytes": 999999}}
                return {"result": {"result_repr": after_repr, "result_truncated": False}}
            return {"result": {"result_repr": before_repr, "result_truncated": False}}
        if command == "transform":
            if transform_result is not None:
                return transform_result
            return {"result": {"objects": [{"pivot": [0.0, 10.0, 0.0]}]}}
        raise AssertionError("unexpected command %r" % command)

    monkeypatch.setattr(module, "call", fake_call)
    return calls


class TestPivotLiveCleanup:
    def test_cleanup_fires_exactly_once_on_the_happy_path(self, monkeypatch):
        module = _load_pivot_live()
        calls = _install_stub(monkeypatch, module)
        assert module.main() == 0
        assert len(calls["delete"]) == 1

    def test_transform_error_still_returns_1_and_cleans_up(self, monkeypatch):
        module = _load_pivot_live()
        calls = _install_stub(
            monkeypatch, module,
            transform_result={"error": "simulated transform failure"},
        )
        assert module.main() == 1
        assert len(calls["delete"]) == 1

    def test_an_exception_deep_in_the_body_still_cleans_up_and_is_not_masked(
        self, monkeypatch
    ):
        # The "after" query's structured_result raises ValueError on a
        # truncated repr - an exception that has nothing to do with the
        # transform step succeeding or failing, and the old code had no
        # try/finally at all to catch it.
        module = _load_pivot_live()
        calls = _install_stub(monkeypatch, module, after_truncated=True)
        with pytest.raises(ValueError, match="truncated"):
            module.main()
        assert len(calls["delete"]) == 1

    def test_cleanup_targets_the_name_maya_actually_returned(self, monkeypatch):
        # The assertion that pins the fix: a build step that comes back
        # 'pivotGate7' (Maya's own uniquify suffix from a leftover prior
        # run) must have every later query, and the final delete, address
        # THAT name - not the hardcoded literal 'pivotGate'.
        module = _load_pivot_live()
        calls = _install_stub(monkeypatch, module, build_name="pivotGate7")
        assert module.main() == 0

        assert len(calls["delete"]) == 1
        assert "'pivotGate7'" in calls["delete"][0]
        assert "'pivotGate'" not in calls["delete"][0]

        assert len(calls["queries"]) == 2  # the "before" query and the "after" query
        for code in calls["queries"]:
            assert "'pivotGate7'" in code
            assert "'pivotGate'" not in code

    def test_a_failed_creation_skips_cleanup_without_a_second_error(self, monkeypatch):
        # name stays None until the build call succeeds. If creation itself
        # fails, there is nothing to delete - and the finally block must not
        # manufacture a second error (e.g. an UnboundLocalError, or a delete
        # of the literal 'pivotGate') on top of the real one.
        module = _load_pivot_live()
        calls = _install_stub(
            monkeypatch, module, build_raises=ConnectionError("no socket"),
        )
        with pytest.raises(ConnectionError, match="no socket"):
            module.main()
        assert calls["delete"] == []
