"""Socket client for the Maya plugin: framing, reconnect, token, serialization.

One in-flight request at a time (the LLM is serial anyway); a request that
times out abandons its connection and the next request opens a fresh one, so a
late response can never be mismatched to a new request id.
"""

from __future__ import annotations

import os
import socket
import threading
from typing import Any, Dict, Optional

from maya_plugin import protocol

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9877

LAUNCH_INSTRUCTIONS = (
    "Could not reach the Maya plugin at {host}:{port}. Make sure Maya is open and the "
    "plugin is running - in Maya's Script Editor (Python tab):\n"
    '    import sys; sys.path.insert(0, r"<path to maya-mcp repo>")\n'
    "    from maya_plugin import maya_mcp_plugin\n"
    "    maya_mcp_plugin.start_server()\n"
    "or set MAYA_MCP_HOST / MAYA_MCP_PORT if the plugin listens elsewhere."
)


class MayaConnectionError(Exception):
    """Transport-level failure: plugin unreachable, dropped, or protocol breach."""


class MayaTimeoutError(MayaConnectionError):
    """No response within the request timeout (plus grace)."""


class MayaError(Exception):
    """The plugin executed the command and reported an error.

    Carries the structured fields from the wire so tools can surface the full
    story - type, message, complete Maya traceback, and an actionable hint.
    """

    def __init__(
        self,
        error_type: str,
        message: str,
        maya_traceback: Optional[str] = None,
        hint: Optional[str] = None,
    ):
        self.error_type = error_type
        self.message = message
        self.maya_traceback = maya_traceback
        self.hint = hint
        parts = ["%s: %s" % (error_type, message)]
        if hint:
            parts.append("hint: %s" % hint)
        if maya_traceback:
            parts.append(maya_traceback.rstrip())
        super().__init__("\n".join(parts))


class MayaConnection:
    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        token: Optional[str] = None,
        connect_timeout_s: float = 3.0,
        response_grace_s: float = 5.0,
    ):
        self.host = host or os.environ.get("MAYA_MCP_HOST", DEFAULT_HOST)
        self.port = int(port or os.environ.get("MAYA_MCP_PORT", DEFAULT_PORT))
        self.token = token if token is not None else os.environ.get("MAYA_MCP_TOKEN")
        self.connect_timeout_s = connect_timeout_s
        # The plugin enforces the command timeout itself and answers with a
        # structured error; the grace covers transport latency on top of it.
        self.response_grace_s = response_grace_s
        self._sock: Optional[socket.socket] = None
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- public

    def request(
        self, cmd: str, params: Dict[str, Any], timeout_s: float = 30.0,
        timeout_adjustable: bool = False,
    ) -> Dict[str, Any]:
        """Send one command and return its `result` dict.

        Raises MayaError on a structured error response, MayaTimeoutError when
        the plugin does not answer in time, MayaConnectionError on transport
        problems.
        """
        with self._lock:
            frame = protocol.make_request(cmd, params, timeout_s, token=self.token,
                                          timeout_adjustable=timeout_adjustable)
            sock = self._ensure_connected()
            try:
                sock.settimeout(timeout_s + self.response_grace_s)
                sock.sendall(protocol.encode_frame(frame))
                response = protocol.read_frame(lambda n: sock.recv(n))
            except socket.timeout:
                self._drop()
                raise MayaTimeoutError(
                    "no response from the Maya plugin within %.1f s for command %r; "
                    "the connection was reset - Maya may still be executing it"
                    % (timeout_s + self.response_grace_s, cmd)
                ) from None
            except (protocol.ProtocolError, OSError) as exc:
                self._drop()
                raise MayaConnectionError(
                    "connection to the Maya plugin failed mid-request (%s); "
                    "it will be re-established on the next call" % exc
                ) from exc

            if response.get("id") != frame["id"]:
                self._drop()
                raise MayaConnectionError(
                    "response id mismatch (got %r, expected %r); connection reset"
                    % (response.get("id"), frame["id"])
                )
            if response.get("status") == "ok":
                result = response.get("result")
                return result if isinstance(result, dict) else {"value": result}
            error = response.get("error") or {}
            raise MayaError(
                error.get("type", "UnknownError"),
                error.get("message", "unknown error"),
                maya_traceback=error.get("maya_traceback"),
                hint=error.get("hint"),
            )

    def close(self) -> None:
        with self._lock:
            self._drop()

    # --------------------------------------------------------------- internal

    def _ensure_connected(self) -> socket.socket:
        if self._sock is not None:
            return self._sock
        try:
            sock = socket.create_connection(
                (self.host, self.port), timeout=self.connect_timeout_s
            )
        except OSError as exc:
            raise MayaConnectionError(
                LAUNCH_INSTRUCTIONS.format(host=self.host, port=self.port)
            ) from exc
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = sock
        return sock

    def _drop(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
