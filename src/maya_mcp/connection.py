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
# The identity ping on a fresh connection (#862): ping reads nothing and
# answers from the socket thread when Maya is busy, so this is short.
HANDSHAKE_TIMEOUT_S = 5.0

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


def process_alive(pid: int) -> Optional[bool]:
    """Is the process with this pid still running? None when the question
    could not be asked - which must stay distinct from "no" (#862): the
    message built on it says "gone" only when the OS said so.

    Windows has no signal 0; OpenProcess with the query-limited right
    answers for any process the caller may see, and an access-denied
    answer still means the process exists. A handle that opens but reports
    an exit code other than STILL_ACTIVE (259) is a process that has ended
    while something holds its handle.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    if os.name == "nt":
        try:
            import ctypes  # noqa: PLC0415 - only this branch needs it
            from ctypes import wintypes  # noqa: PLC0415

            kernel32 = ctypes.windll.kernel32
            query_limited = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION
            handle = kernel32.OpenProcess(query_limited, False, pid)
            if not handle:
                error = ctypes.get_last_error() or kernel32.GetLastError()
                if error == 5:  # ERROR_ACCESS_DENIED: exists, not ours to open
                    return True
                if error == 87:  # ERROR_INVALID_PARAMETER: no such process
                    return False
                return None
            try:
                code = wintypes.DWORD()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return None
                return code.value == 259  # STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        except Exception:  # noqa: BLE001 - see docstring: unknown, not "no"
            return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None
    return True


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
        # Who answered the last ping that passed through here (#862): the
        # pid lets a mid-request failure say whether the process is gone or
        # only its listener, which is the difference between a relaunch and
        # a retry. None until a ping has been seen.
        self.last_pid: Optional[int] = None
        self.last_scene: Optional[str] = None

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
                raise MayaConnectionError(self._diagnose_drop(exc)) from exc

            if response.get("id") != frame["id"]:
                self._drop()
                raise MayaConnectionError(
                    "response id mismatch (got %r, expected %r); connection reset"
                    % (response.get("id"), frame["id"])
                )
            if response.get("status") == "ok":
                result = response.get("result")
                if cmd == "ping" and isinstance(result, dict):
                    self._note_identity(result)
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

    def _note_identity(self, ping_result: Dict[str, Any]) -> None:
        process = ping_result.get("process") or {}
        pid = process.get("pid")
        if isinstance(pid, int) and not isinstance(pid, bool):
            self.last_pid = pid
        scene = process.get("scene")
        if isinstance(scene, str):
            self.last_scene = scene

    def _listener_answers(self) -> bool:
        """Does anything accept a connection on the port right now?"""
        try:
            probe = socket.create_connection(
                (self.host, self.port), timeout=min(1.0, self.connect_timeout_s)
            )
        except OSError:
            return False
        probe.close()
        return True

    def _diagnose_drop(self, exc: BaseException) -> str:
        """What a mid-request failure means for the caller (#862).

        The old message said "it will be re-established on the next call"
        for every drop - including the two where the Maya process had died,
        nothing listened on the port, and the caller lost time retrying.
        Three different things can be true, and one probe connect plus the
        last ping's pid tell them apart.
        """
        where = "%s:%d" % (self.host, self.port)
        if self._listener_answers():
            return (
                "connection to the Maya plugin failed mid-request (%s). The plugin "
                "at %s still accepts connections, so the next call reconnects - if "
                "this keeps happening, Maya may be dying under load (redmine 863: "
                "check its memory)" % (exc, where)
            )
        pid = self.last_pid
        alive = process_alive(pid) if pid else None
        if pid and alive is True:
            return (
                "connection to the Maya plugin failed mid-request (%s), and nothing "
                "is listening on %s, but Maya pid %d is still running: its plugin "
                "server died (redmine 863). Run start_server() in that Maya's script "
                "editor, or relaunch it; retrying this call will not help"
                % (exc, where, pid)
            )
        if pid and alive is False:
            return (
                "connection to the Maya plugin failed mid-request (%s), and nothing "
                "is listening on %s: Maya pid %d is gone - the process died. "
                "Relaunch Maya and reopen the scene; retrying this call will not help"
                % (exc, where, pid)
            )
        return (
            "connection to the Maya plugin failed mid-request (%s), and nothing is "
            "listening on %s any more: the Maya that was answering is gone or its "
            "plugin server died. Relaunch Maya (or run start_server() in it) and "
            "reopen the scene; retrying this call will not help" % (exc, where)
        )

    def _ensure_connected(self) -> socket.socket:
        if self._sock is not None:
            return self._sock
        try:
            sock = socket.create_connection(
                (self.host, self.port), timeout=self.connect_timeout_s
            )
        except OSError as exc:
            raise MayaConnectionError(self._explain_refusal()) from exc
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = sock
        self._handshake(sock)
        return sock

    def _explain_refusal(self) -> str:
        """A cold connect that nothing accepted: the launch instructions,
        unless a ping on an earlier connection named the process - then
        whether that process is still there is the fact that matters (#862).
        """
        where = "%s:%d" % (self.host, self.port)
        pid = self.last_pid
        alive = process_alive(pid) if pid else None
        if pid and alive is False:
            return (
                "Could not reach the Maya plugin at %s: Maya pid %d, which answered "
                "here before, is gone - the process died. Relaunch Maya and reopen "
                "the scene" % (where, pid)
            )
        if pid and alive is True:
            return (
                "Could not reach the Maya plugin at %s, but Maya pid %d, which "
                "answered here before, is still running: its plugin server died "
                "(redmine 863). Run start_server() in that Maya's script editor, or "
                "relaunch it" % (where, pid)
            )
        return LAUNCH_INSTRUCTIONS.format(host=self.host, port=self.port)

    def _handshake(self, sock: socket.socket) -> None:
        """One ping on every fresh connection, so a later failure can name the
        process it was talking to (#862). A port is not an identity, and the
        wrapper never learned one before: nothing under src/ sent a ping.

        An error frame is raised the way any request raises it - an
        AuthError closes the connection on the plugin's side, and a BusyError
        would meet the next request just the same. A transport failure on
        the handshake leaves the identity unknown and lets the real request
        find out what is wrong.
        """
        frame = protocol.make_request("ping", {}, HANDSHAKE_TIMEOUT_S, token=self.token)
        try:
            sock.settimeout(HANDSHAKE_TIMEOUT_S + self.response_grace_s)
            sock.sendall(protocol.encode_frame(frame))
            response = protocol.read_frame(lambda n: sock.recv(n))
        except (protocol.ProtocolError, OSError):
            return
        if response.get("id") != frame["id"]:
            return
        if response.get("status") == "ok":
            result = response.get("result")
            if isinstance(result, dict):
                self._note_identity(result)
            return
        # The socket stays cached: the plugin closes it after an AuthError,
        # so the next request fails at transport level exactly as it always
        # did (test_auth_error_closes_the_connection), and a BusyError leaves
        # it perfectly usable.
        error = response.get("error") or {}
        raise MayaError(
            error.get("type", "UnknownError"),
            error.get("message", "unknown error"),
            maya_traceback=error.get("maya_traceback"),
            hint=error.get("hint"),
        )

    def _drop(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
