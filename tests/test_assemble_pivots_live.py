"""evals/assemble_pivots_live.py's cleanup contract: every object the
`assemble` call built must be deleted on every exit path, addressed by the
name Maya actually returned - never the literal chunk name - for the same
reason tests/test_pivot_live.py exists: exactly this class of bug (a missed
delete that then queries the wrong object on the next run) shipped once
already.

Loads the real script by path and monkeypatches its `call` name so main()
runs for real against a stub - no socket, no Maya, and
assemble_pivots_live.py itself is untouched.
"""

import importlib.util
import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_script():
    path = os.path.join(REPO_ROOT, "evals", "assemble_pivots_live.py")
    spec = importlib.util.spec_from_file_location("evals_assemble_pivots_live", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _objects(names, pivots):
    return [
        {"name": name, "parts": 1, "tris": 12, "verts": 8, "faces": 6, "shells": 1,
         "pivot": pivot, "combined": True}
        for name, pivot in zip(names, pivots)
    ]


def _install_stub(monkeypatch, module, *,
                   names=("|assemblePivotGateA", "|assemblePivotGateB",
                          "|assemblePivotGateC"),
                   pivots=([0.0, 9.0, 0.0], [0.0, 0.0, 0.0], None),
                   assemble_result=None, assemble_raises=None,
                   measure_raises_for=None):
    """Fake `call` answering the one `assemble` request and the per-object
    execute_python measurement/delete calls assemble_pivots_live.main()
    makes. Records every delete and every measurement query so tests can pin
    exactly which names were addressed.
    """
    calls = {"delete": [], "measure": []}

    def fake_call(command, params, timeout_s=60.0, port=None):
        if command == "assemble":
            if assemble_raises is not None:
                raise assemble_raises
            if assemble_result is not None:
                return assemble_result
            return {"result": {
                "objects": _objects(names, pivots),
                "parts": len(names), "tris": 12 * len(names), "outside_patch": 0,
                "atlas": None, "warnings": [],
            }}
        if command == "execute_python":
            code = params["code"]
            if "cmds.delete" in code:
                calls["delete"].append(code)
                return {"result": {"result_repr": "'cleaned'", "result_truncated": False}}
            # a measurement query
            calls["measure"].append(code)
            target = next((n for n in names if ("'%s'" % n) in code), None)
            if measure_raises_for is not None and measure_raises_for in code:
                return {"result": {"result_repr": None, "result_truncated": True,
                                    "result_bytes": 999999}}
            idx = names.index(target) if target in names else 0
            measured = pivots[idx] if pivots[idx] is not None else [0.0, 0.0, 0.0]
            return {"result": {"result_repr": repr(measured), "result_truncated": False}}
        raise AssertionError("unexpected command %r" % command)

    monkeypatch.setattr(module, "call", fake_call)
    return calls


class TestAssemblePivotsLiveCleanup:
    def test_cleanup_fires_once_per_built_object_on_the_happy_path(self, monkeypatch):
        module = _load_script()
        calls = _install_stub(monkeypatch, module)
        assert module.main() == 0
        assert len(calls["delete"]) == 3

    def test_an_assemble_error_response_skips_cleanup_since_nothing_was_built(
        self, monkeypatch
    ):
        module = _load_script()
        calls = _install_stub(
            monkeypatch, module,
            assemble_result={"error": "simulated assemble failure"},
        )
        assert module.main() == 1
        assert calls["delete"] == []

    def test_an_exception_in_a_measurement_query_still_cleans_up_every_object(
        self, monkeypatch
    ):
        # A truncated repr on the SECOND object's measurement query must not
        # skip cleanup of the first or third - all three were already built
        # and their names captured before any measurement query ran.
        module = _load_script()
        calls = _install_stub(
            monkeypatch, module, measure_raises_for="assemblePivotGateB",
        )
        with pytest.raises(ValueError, match="truncated"):
            module.main()
        assert len(calls["delete"]) == 3

    def test_cleanup_targets_the_names_maya_actually_returned(self, monkeypatch):
        # A prior run's failed cleanup would leave Maya to uniquify these
        # chunk names on the next build - every query and delete below must
        # address THAT returned name, never the literal 'assemblePivotGateA'.
        module = _load_script()
        renamed = ("|assemblePivotGateA7", "|assemblePivotGateB7",
                   "|assemblePivotGateC7")
        calls = _install_stub(monkeypatch, module, names=renamed)
        assert module.main() == 0

        assert len(calls["delete"]) == 3
        for name, code in zip(renamed, calls["delete"]):
            assert ("'%s'" % name) in code

        assert len(calls["measure"]) == 3
        for name, code in zip(renamed, calls["measure"]):
            assert ("'%s'" % name) in code
            assert "assemblePivotGateA'" not in code or name.endswith("A7")

    def test_a_failed_assemble_call_itself_skips_cleanup_without_a_second_error(
        self, monkeypatch
    ):
        # names stays [] until the assemble call succeeds. If the call
        # itself raises, there is nothing to delete - and the finally block
        # must not manufacture a second error on top of the real one.
        module = _load_script()
        calls = _install_stub(
            monkeypatch, module, assemble_raises=ConnectionError("no socket"),
        )
        with pytest.raises(ConnectionError, match="no socket"):
            module.main()
        assert calls["delete"] == []

    def test_explicit_pivot_mismatch_is_reported_as_failure_not_swallowed(
        self, monkeypatch
    ):
        # If the explicit pivot on chunk A did not land, main() must fail
        # loudly (and still clean up) rather than report PASS.
        module = _load_script()
        calls = _install_stub(
            monkeypatch, module,
            pivots=([1.0, 1.0, 1.0], [0.0, 0.0, 0.0], None),  # wrong for A
        )
        assert module.main() == 1
        assert len(calls["delete"]) == 3
