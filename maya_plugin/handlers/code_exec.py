"""execute_python: the escape hatch. Persistent namespace, sacred tracebacks.

The namespace survives across calls (reset via maya_reset_namespace). Maya
modules are pre-imported when available; headless (tests, mayapy without a
scene) the namespace simply lacks them.

A Python exception inside user code is NOT a protocol error: the call succeeds
and the complete verbatim traceback comes back in the result, because the LLM
debugs itself with it and silent failure causes hallucinated success.

Truncation follows the same rule. A capped result is a MEASUREMENT WITH ITS TAIL
CUT OFF, and callers routinely ast.literal_eval result_repr - so a 37-row check
came back as a broken string and surfaced as a SyntaxError inside the caller's
parser, which is a confusing place to learn about a size cap. Every cap now
reports itself as a flag, and the structured-result cap is large enough that a
real measurement fits inside it.
"""

from __future__ import annotations

import ast
import contextlib
import io
import traceback
from typing import Any, Dict, Optional

from ..dispatcher import HandlerError

STDOUT_CAP = 8 * 1024
# A structured result is the whole point of the call, not chatter: 4 KB used to
# cut a 37-row check in half. The wire allows 64 MB, so this is still bounded by
# three orders of magnitude - and anything hitting it is a dump, not a
# measurement, and should be written to a file.
RESULT_REPR_CAP = 256 * 1024
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


def _cap(text: str, limit: int) -> tuple:
    """(text, was_truncated). The notice stays inline for a human reading the
    output; the flag is for a caller that is about to parse it."""
    if len(text) <= limit:
        return text, False
    return text[:limit] + TRUNCATION_NOTICE % limit, True


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
    result_bytes: Optional[int] = None
    result_truncated = False
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
                        full = repr(value)
                        result_bytes = len(full)
                        result_repr, result_truncated = _cap(full, RESULT_REPR_CAP)
        except Exception:
            tb_text = traceback.format_exc()

    stdout_text, stdout_truncated = _cap(stdout_buf.getvalue(), STDOUT_CAP)
    stderr_text, stderr_truncated = _cap(stderr_buf.getvalue(), STDOUT_CAP)
    result: Dict[str, Any] = {
        "stdout": stdout_text,
        "stderr": stderr_text,
        "result_repr": result_repr,
        "traceback": tb_text,
        "namespace_keys": sorted(k for k in ns if not k.startswith("__")),
        # A truncated repr will not parse. Callers literal_eval this routinely,
        # so they must be able to ask rather than discover it as a SyntaxError.
        "result_truncated": result_truncated,
        "result_bytes": result_bytes,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
    }
    if checkpoint_path is not None:
        result["checkpoint"] = checkpoint_path
    return result
