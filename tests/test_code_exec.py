"""execute_python handler tests: persistent namespace, output capture, tracebacks.

Runs headless — maya imports inside the handler are optional; the namespace
simply lacks `cmds`/`mel` when Maya is absent.
"""

import pytest

from maya_plugin.handlers import code_exec, session


@pytest.fixture(autouse=True)
def fresh_namespace():
    code_exec.reset_namespace()
    yield
    code_exec.reset_namespace()


class TestExecution:
    def test_last_expression_value_is_result_repr(self):
        result = code_exec.execute_python({"code": "1 + 1"})
        assert result["result_repr"] == "2"
        assert result["traceback"] is None

    def test_statements_without_trailing_expression_give_none_repr(self):
        result = code_exec.execute_python({"code": "x = 41"})
        assert result["result_repr"] is None

    def test_stdout_and_stderr_captured(self):
        result = code_exec.execute_python(
            {"code": "import sys\nprint('to out')\nprint('to err', file=sys.stderr)"}
        )
        assert "to out" in result["stdout"]
        assert "to err" in result["stderr"]

    def test_namespace_persists_across_calls(self):
        code_exec.execute_python({"code": "golem_height = 4.5"})
        result = code_exec.execute_python({"code": "golem_height * 2"})
        assert result["result_repr"] == "9.0"
        assert "golem_height" in result["namespace_keys"]

    def test_reset_namespace_clears_user_names(self):
        code_exec.execute_python({"code": "leftover = 1"})
        code_exec.reset_namespace()
        result = code_exec.execute_python({"code": "'leftover' in dir()"})
        assert result["result_repr"] == "False"

    def test_missing_code_param_is_handler_error(self):
        from maya_plugin.dispatcher import HandlerError

        with pytest.raises(HandlerError, match="code"):
            code_exec.execute_python({})


class TestTracebacks:
    def test_runtime_error_returns_complete_verbatim_traceback(self):
        result = code_exec.execute_python(
            {"code": "def inner():\n    raise ValueError('golem stumbled')\ninner()"}
        )
        tb = result["traceback"]
        assert tb is not None
        assert "Traceback (most recent call last)" in tb
        assert "ValueError: golem stumbled" in tb
        assert "inner" in tb  # frames preserved, nothing truncated

    def test_syntax_error_reported_in_traceback_not_raised(self):
        result = code_exec.execute_python({"code": "def broken(:"})
        assert "SyntaxError" in result["traceback"]

    def test_partial_stdout_kept_when_code_fails_midway(self):
        result = code_exec.execute_python(
            {"code": "print('before the fall')\nraise RuntimeError('x')"}
        )
        assert "before the fall" in result["stdout"]
        assert "RuntimeError" in result["traceback"]


class TestOutputCaps:
    def test_stdout_capped_at_8kb_with_explicit_notice(self):
        result = code_exec.execute_python({"code": "print('A' * 20000)"})
        assert len(result["stdout"]) < 10000
        assert "truncated" in result["stdout"]
        assert result["stdout_truncated"] is True

    def test_result_repr_capped_with_marker(self):
        result = code_exec.execute_python(
            {"code": "'B' * %d" % (code_exec.RESULT_REPR_CAP + 5000)}
        )
        assert len(result["result_repr"]) < code_exec.RESULT_REPR_CAP + 1000
        assert "truncated" in result["result_repr"]

    def test_truncation_of_a_structured_result_is_flagged_not_silent(self):
        """The bug: a 37-row check came back as a truncated, unparseable string,
        and the caller learned about it as a SyntaxError from its own
        literal_eval. The cap is fine; discovering it downstream is not."""
        result = code_exec.execute_python(
            {"code": "[{'chunk': 'c%d' % i, 'tris': i} for i in range(200000)]"}
        )
        assert result["result_truncated"] is True
        assert result["result_bytes"] > code_exec.RESULT_REPR_CAP

    def test_an_uncapped_result_says_so_and_reports_its_real_size(self):
        result = code_exec.execute_python({"code": "[{'chunk': 'c', 'tris': 12}]"})
        assert result["result_truncated"] is False
        assert result["result_bytes"] == len(result["result_repr"])
        assert result["stdout_truncated"] is False

    def test_a_real_measurement_now_fits(self):
        """37 rows was the size that broke. The cap has to clear a genuine
        per-chunk report of a whole delivery, not just a toy one."""
        result = code_exec.execute_python({
            "code": "[{'name': 'tower_c%04d' % i, 'tris': 48, 'watertight': True,"
                    " 'outset_m': 0.47} for i in range(2034)]"
        })
        assert result["result_truncated"] is False
        import ast

        assert len(ast.literal_eval(result["result_repr"])) == 2034

    def test_a_result_with_no_value_reports_no_size(self):
        result = code_exec.execute_python({"code": "x = 1"})
        assert result["result_repr"] is None
        assert result["result_bytes"] is None
        assert result["result_truncated"] is False


class TestEvalHarnessParsing:
    """evals/live_call.structured_result - the caller side of the same bug."""

    @staticmethod
    def _live_call():
        import importlib.util
        import os

        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "evals", "live_call.py",
        )
        spec = importlib.util.spec_from_file_location("evals_live_call", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_parses_a_whole_result(self):
        out = code_exec.execute_python({"code": "[{'tris': 12}]"})
        assert self._live_call().structured_result(out) == [{"tris": 12}]

    def test_a_truncated_result_fails_here_not_inside_the_parser(self):
        out = code_exec.execute_python({"code": "'B' * %d" % (256 * 1024 + 10)})
        with pytest.raises(ValueError) as exc:
            self._live_call().structured_result(out, "chunk report")
        assert "truncated" in str(exc.value)
        assert "chunk report" in str(exc.value)

    def test_code_that_returned_nothing_says_why(self):
        out = code_exec.execute_python({"code": "x = 1"})
        with pytest.raises(ValueError) as exc:
            self._live_call().structured_result(out)
        assert "bare expression" in str(exc.value)


class TestRisky:
    def test_risky_triggers_auto_checkpoint(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            session, "auto_checkpoint",
            lambda reason: calls.append(reason)
            or {"checkpoint_id": "001_auto_risky_exec", "path": "path.ma"},
        )
        result = code_exec.execute_python({"code": "1", "risky": True})
        assert calls == ["risky_exec"]
        assert result["checkpoint"] == "path.ma"

    def test_non_risky_takes_no_checkpoint(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            session, "auto_checkpoint", lambda reason: calls.append(reason)
        )
        code_exec.execute_python({"code": "1"})
        assert calls == []
