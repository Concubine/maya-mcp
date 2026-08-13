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

    def test_result_repr_capped_with_marker(self):
        result = code_exec.execute_python({"code": "'B' * 50000"})
        assert len(result["result_repr"]) < 5000
        assert "truncated" in result["result_repr"]


class TestRisky:
    def test_risky_triggers_auto_checkpoint(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            session, "auto_checkpoint",
            lambda reason: calls.append(reason) or "path.ma",
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
