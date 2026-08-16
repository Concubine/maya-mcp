"""Shared TCP client for eval scripts: one framed request, one response.

Returns the RAW response frame - status, result, error - because eval scripts
report failures rather than raise on them; the point of a live check is the
measurement, including the measurement of a failure.

The port comes from MAYA_MCP_PORT and defaults to 9878, the disposable
agent-launched Maya, so a stray run never lands in the user's session on 9877
(the two-Maya policy from #577).

Before the first call on a port, this pings the plugin and reports two things
about whoever answered, because a green result from the wrong Maya is worse
than no result:

- WHICH CODE: a loud stderr warning if the live copy is not this working tree.
  Set MAYA_MCP_SKIP_STALE_CHECK=1 to silence it (deliberately awkward).
- WHICH PROCESS: the answering pid and scene are printed to stderr, and if
  MAYA_MCP_EXPECT_PID is set and does not match, the run stops. A port is not
  an identity - set it to the pid you launched (#648).
"""

from __future__ import annotations

import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from maya_plugin import protocol, version  # noqa: E402

HOST = "127.0.0.1"
DEFAULT_PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_checked_ports: set[int] = set()


def _send(command: str, params: dict, timeout_s: float, port: int) -> dict:
    sock = socket.create_connection((HOST, port), timeout=timeout_s + 30)
    try:
        sock.sendall(
            protocol.encode_frame(protocol.make_request(command, params, timeout_s))
        )
        return protocol.read_frame(sock.recv)
    finally:
        sock.close()


def _ping_result(port: int) -> dict:
    """The ping payload, or {} if nothing can be told. Never raises: an
    unreachable plugin is the caller's problem to report, and a check that
    breaks the run it protects is worse than no check."""
    try:
        return (_send("ping", {}, 10.0, port).get("result") or {})
    except Exception:  # noqa: BLE001 - see docstring
        return {}


def staleness_warning(port: int | None = None) -> str | None:
    """Ping the live plugin and compare it against this working tree.

    Returns the warning text, or None when they agree / nothing can be told.
    """
    plugin = _ping_result(port or DEFAULT_PORT).get("plugin")
    try:
        return version.compare(
            plugin,
            version.package_digest(os.path.join(REPO_ROOT, "maya_plugin")),
            working_commit=version.git_stamp(REPO_ROOT)["commit"],
        )
    except Exception:  # noqa: BLE001 - see _ping_result
        return None


def _identity_line(process: dict) -> str:
    return "maya on %s:%s: pid %s, scene %r, up %ss" % (
        process.get("host"), process.get("port"), process.get("pid"),
        process.get("scene"), process.get("uptime_s"),
    )


def _handshake(port: int) -> None:
    """Say who answered, and stop if it is not who the caller expected.

    The staleness check answers "which code"; this answers "which process".
    Both are printed before the first real call so that every eval's output
    carries the evidence of what it was actually measured against.
    """
    result = _ping_result(port)
    try:
        warning = version.compare(
            result.get("plugin"),
            version.package_digest(os.path.join(REPO_ROOT, "maya_plugin")),
            working_commit=version.git_stamp(REPO_ROOT)["commit"],
        )
    except Exception:  # noqa: BLE001
        warning = None
    if warning and os.environ.get("MAYA_MCP_SKIP_STALE_CHECK") != "1":
        print(warning, file=sys.stderr, flush=True)

    process = result.get("process")
    if not isinstance(process, dict):
        print("maya on port %d reports no process identity - it predates the "
              "identity handshake, so WHICH Maya answered cannot be told from "
              "here (maya-mcp #648). Restart it against this tree." % port,
              file=sys.stderr, flush=True)
        process = {}
    else:
        print(_identity_line(process), file=sys.stderr, flush=True)

    expected = (os.environ.get("MAYA_MCP_EXPECT_PID") or "").strip()
    if expected and str(process.get("pid")) != expected:
        raise SystemExit(
            "\n%s\nWRONG MAYA: port %d is answered by pid %s, not the expected "
            "pid %s. A port is not an identity - the Maya you launched may have "
            "lost the bind race to another one, which is now taking your calls "
            "(maya-mcp #648). Refusing to run.\n%s"
            % ("!" * 72, port, process.get("pid"), expected, "!" * 72)
        )


def structured_result(execute_result: dict, what: str = "result"):
    """ast.literal_eval an execute_python result_repr, checking the cap first.

    Eval scripts parse result_repr constantly. When the repr is truncated it is
    not valid Python, and a raw literal_eval reports that as a SyntaxError from
    inside the parser - a confusing place to learn that a MEASUREMENT lost its
    tail. Fail here instead, saying what actually happened.
    """
    import ast

    if execute_result.get("result_truncated"):
        raise ValueError(
            "%s was truncated at the result cap (%s bytes of repr): it cannot be "
            "parsed. Have the code return a summary, or write the full data to a "
            "file and return the path."
            % (what, execute_result.get("result_bytes"))
        )
    repr_text = execute_result.get("result_repr")
    if not repr_text:
        raise ValueError(
            "%s returned no value - the code must END in a bare expression for "
            "execute_python to send one back" % what
        )
    return ast.literal_eval(repr_text)


def call(command: str, params: dict, timeout_s: float = 60.0, port: int | None = None) -> dict:
    """Send one command to a live plugin; return the decoded response frame."""
    target = port or DEFAULT_PORT
    if target not in _checked_ports:
        _checked_ports.add(target)  # mark first: check once, even if it fails
        _handshake(target)
    return _send(command, params, timeout_s, target)
