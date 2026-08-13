"""execute_python: the escape hatch. Persistent namespace, sacred tracebacks.

The namespace survives across calls (reset via maya_reset_namespace). Maya
modules are pre-imported when available; headless (tests, mayapy without a
scene) the namespace simply lacks them.

A Python exception inside user code is NOT a protocol error: the call succeeds
and the complete verbatim traceback comes back in the result, because the LLM
debugs itself with it and silent failure causes hallucinated success.
"""

from __future__ import annotations

import ast
import contextlib
import io
import traceback
from typing import Any, Dict, Optional

from ..dispatcher import HandlerError

STDOUT_CAP = 8 * 1024
RESULT_REPR_CAP = 4 * 1024
TRUNCATION_NOTICE = "\n... [truncated by maya-mcp: output exceeded %d bytes]"

_namespace: Optional[Dict[str, Any]] = None


def _build_namespace() -> Dict[str, Any]:
    ns: Dict[str, Any] = {"__name__": "__maya_mcp__"}
    try:
        import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

        ns["cmds"] = cmds
    except ImportError:
        pass
    try:
        import maya.mel as mel  # noqa: PLC0415

        ns["mel"] = mel
    except ImportError:
        pass
    try:
        import pymel.core as pm  # noqa: PLC0415

        ns["pm"] = pm
    except ImportError:
        pass
    return ns


def get_namespace() -> Dict[str, Any]:
    global _namespace
    if _namespace is None:
        _namespace = _build_namespace()
    return _namespace


def reset_namespace(params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Handler for maya_reset_namespace; also used directly by tests."""
    global _namespace
    _namespace = None
    return {"reset": True}


def _cap(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + TRUNCATION_NOTICE % limit


def execute_python(params: Dict[str, Any]) -> Dict[str, Any]:
    code = params.get("code")
    if not isinstance(code, str) or not code.strip():
        raise HandlerError(
            "missing required param 'code'",
            hint="pass the Python source to run as the 'code' string",
        )

    checkpoint_path: Optional[str] = None
    if params.get("risky"):
        from . import session  # noqa: PLC0415 - avoid cycle at import time

        checkpoint_path = session.auto_checkpoint("risky_exec")["path"]

    ns = get_namespace()
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    result_repr: Optional[str] = None
    tb_text: Optional[str] = None

    try:
        tree = ast.parse(code, filename="<maya-mcp>", mode="exec")
    except SyntaxError:
        tb_text = traceback.format_exc()
        tree = None

    if tree is not None:
        # IPython-style: if the code ends in a bare expression, evaluate it
        # separately so its value comes back as result_repr.
        trailing_expr: Optional[ast.Expression] = None
        if tree.body and isinstance(tree.body[-1], ast.Expr):
            trailing_expr = ast.Expression(tree.body.pop().value)

        try:
            with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                exec(compile(tree, "<maya-mcp>", "exec"), ns)  # noqa: S102 - the whole point
                if trailing_expr is not None:
                    value = eval(compile(trailing_expr, "<maya-mcp>", "eval"), ns)  # noqa: S307
                    if value is not None:
                        result_repr = _cap(repr(value), RESULT_REPR_CAP)
        except Exception:
            tb_text = traceback.format_exc()

    result: Dict[str, Any] = {
        "stdout": _cap(stdout_buf.getvalue(), STDOUT_CAP),
        "stderr": _cap(stderr_buf.getvalue(), STDOUT_CAP),
        "result_repr": result_repr,
        "traceback": tb_text,
        "namespace_keys": sorted(k for k in ns if not k.startswith("__")),
    }
    if checkpoint_path is not None:
        result["checkpoint"] = checkpoint_path
    return result
