"""Shared TCP client for eval scripts: one framed request, one response.

Returns the RAW response frame - status, result, error - because eval scripts
report failures rather than raise on them; the point of a live check is the
measurement, including the measurement of a failure.

The port comes from MAYA_MCP_PORT and defaults to 9878, the disposable
agent-launched Maya, so a stray run never lands in the user's session on 9877
(the two-Maya policy from #577).
"""

from __future__ import annotations

import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from maya_plugin import protocol  # noqa: E402

HOST = "127.0.0.1"
DEFAULT_PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))


def call(command: str, params: dict, timeout_s: float = 60.0, port: int | None = None) -> dict:
    """Send one command to a live plugin; return the decoded response frame."""
    sock = socket.create_connection((HOST, port or DEFAULT_PORT), timeout=timeout_s + 30)
    try:
        sock.sendall(
            protocol.encode_frame(protocol.make_request(command, params, timeout_s))
        )
        return protocol.read_frame(sock.recv)
    finally:
        sock.close()
