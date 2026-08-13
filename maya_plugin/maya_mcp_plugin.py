"""maya-mcp plugin entry point: TCP socket server inside Maya.

Run inside Maya's Script Editor (or via userSetup.py):

    from maya_plugin import maya_mcp_plugin
    maya_mcp_plugin.start_server()      # 127.0.0.1:9877

The socket thread NEVER touches the Maya API: every command is marshaled to
the main thread via maya.utils.executeInMainThreadWithResult by the dispatcher.
Headless (tests, mayapy) the plugin still runs; handlers that need Maya report
clean errors instead.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import socket
import threading
from typing import Any, Dict, Optional

from . import protocol
from .dispatcher import Dispatcher
from .handlers import capture, code_exec, modeling, scene, session

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9877

# Inbound requests never legitimately carry images (largest is execute_python
# source); the 64 MB protocol cap is for image-bearing responses only.
INBOUND_MAX_BYTES = 4 * 1024 * 1024
# Once a frame has started arriving, the rest must follow promptly; a half-sent
# frame must not pin a connection thread forever. Idle connections (no bytes at
# all) are healthy and block indefinitely.
DEFAULT_BODY_DEADLINE_S = 30.0

log = logging.getLogger("maya_mcp_plugin")

_active_server: Optional["PluginServer"] = None


def is_maya_available() -> bool:
    try:
        import maya.cmds  # noqa: F401, PLC0415

        return True
    except ImportError:
        return False


def _build_handlers() -> Dict[str, Any]:
    return {
        "ping": lambda params: {"pong": True, "maya": is_maya_available()},
        "execute_python": code_exec.execute_python,
        "reset_namespace": code_exec.reset_namespace,
        "get_scene_graph": scene.get_scene_graph,
        "capture_viewport": capture.capture_viewport,
        "checkpoint": session.checkpoint,
        "restore_checkpoint": session.restore_checkpoint,
        "undo": session.undo,
        "redo": session.redo,
        "new_scene": session.new_scene,
        "open_scene": session.open_scene,
        "save_scene": session.save_scene,
        "create_primitive": modeling.create_primitive,
        "duplicate": modeling.duplicate,
        "transform": modeling.transform,
        "group": modeling.group,
        "parent": modeling.parent,
        "rename": modeling.rename,
        "delete_objects": modeling.delete_objects,
    }


def _main_thread_executor():
    """maya.utils.executeInMainThreadWithResult, or None (direct call) headless."""
    try:
        import maya.utils  # noqa: PLC0415

        return maya.utils.executeInMainThreadWithResult
    except ImportError:
        return None


def _undo_hooks():
    """Per-request undo chunk hooks; each tool call is one undo step."""
    try:
        import maya.cmds as cmds  # noqa: PLC0415

        return (
            lambda: cmds.undoInfo(openChunk=True, chunkName="maya-mcp"),
            lambda: cmds.undoInfo(closeChunk=True),
        )
    except ImportError:
        return None, None


def _log_level_from_env() -> int:
    """MAYA_MCP_LOG_LEVEL, falling back to INFO on any unknown value —
    a typo'd level must never take the process down."""
    name = os.environ.get("MAYA_MCP_LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, name, None)
    return level if isinstance(level, int) else logging.INFO


def _setup_logging() -> None:
    log.setLevel(_log_level_from_env())
    if any(isinstance(h, logging.handlers.RotatingFileHandler) for h in log.handlers):
        return
    log_dir = os.path.join(os.path.expanduser("~"), ".maya-mcp", "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            os.path.join(log_dir, "plugin.log"), maxBytes=2_000_000, backupCount=3
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        log.addHandler(handler)
    except OSError:
        pass  # logging must never take the plugin down


class PluginServer:
    def __init__(
        self,
        host: str,
        port: int,
        token: Optional[str],
        body_deadline_s: float = DEFAULT_BODY_DEADLINE_S,
    ):
        # Bind FIRST: if the port is taken, fail before spawning any thread.
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        self._sock = socket.create_server((host, port), family=family)
        self._sock.settimeout(0.25)
        self.host = host
        self.port = self._sock.getsockname()[1]
        self._body_deadline_s = body_deadline_s

        undo_open, undo_close = _undo_hooks()
        self._dispatcher = Dispatcher(
            handlers=_build_handlers(),
            main_thread_exec=_main_thread_executor(),
            token=token,
            undo_open=undo_open,
            undo_close=undo_close,
        )
        self._conns: set = set()
        self._conns_lock = threading.Lock()
        self._stop = threading.Event()
        self._accept_thread = threading.Thread(
            target=self._accept_loop, name="maya-mcp-accept", daemon=True
        )
        self._accept_thread.start()
        log.info("maya-mcp plugin listening on %s:%d", self.host, self.port)

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            log.info("client connected from %s:%d", *addr[:2])
            with self._conns_lock:
                self._conns.add(conn)
            threading.Thread(
                target=self._serve_connection,
                args=(conn,),
                name="maya-mcp-conn",
                daemon=True,
            ).start()
        try:
            self._sock.close()
        except OSError:
            pass

    def _read_request(self, conn: socket.socket):
        """Read one request frame: block indefinitely while idle, but once the
        first bytes arrive the rest of the frame must land within the body
        deadline, so a half-sent frame cannot pin this thread forever."""
        started = [False]

        def recv(n: int) -> bytes:
            data = conn.recv(n)
            if not started[0] and data:
                started[0] = True
                conn.settimeout(self._body_deadline_s)
            return data

        conn.settimeout(None)
        try:
            return protocol.read_frame(recv, max_bytes=INBOUND_MAX_BYTES)
        finally:
            try:
                conn.settimeout(None)
            except OSError:
                pass

    def _serve_connection(self, conn: socket.socket) -> None:
        try:
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            while not self._stop.is_set():
                try:
                    frame = self._read_request(conn)
                except protocol.ConnectionClosedError:
                    log.info("client disconnected")
                    return
                except protocol.ProtocolError as exc:
                    log.warning("protocol error, closing connection: %s", exc)
                    return
                except OSError:
                    return
                log.debug("request cmd=%s id=%s", frame.get("cmd"), frame.get("id"))
                # Never let a dispatch/encode bug kill the connection silently:
                # the contract is one response frame per request, always.
                try:
                    response = self._dispatcher.handle_request(frame)
                    payload = protocol.encode_frame(response)
                except Exception:
                    log.exception("dispatch failed for id=%s", frame.get("id"))
                    import traceback as _tb

                    try:
                        response = protocol.make_error(
                            str(frame.get("id", "")),
                            "InternalError",
                            "internal plugin error while dispatching",
                            maya_traceback=_tb.format_exc(),
                        )
                        payload = protocol.encode_frame(response)
                    except Exception:
                        return
                try:
                    conn.sendall(payload)
                except OSError:
                    log.warning(
                        "client vanished before response for id=%s", frame.get("id")
                    )
                    return
                # An unauthenticated peer gets exactly one answer per connection:
                # no free retry loop for token guessing.
                error = response.get("error") if isinstance(response, dict) else None
                if error and error.get("type") == "AuthError":
                    log.warning("closing connection after AuthError")
                    return
        finally:
            with self._conns_lock:
                self._conns.discard(conn)
            try:
                conn.close()
            except OSError:
                pass

    def stop(self) -> None:
        self._stop.set()
        # Force-close established connections so threads blocked in recv() exit
        # now, clients fail fast instead of stalling a full timeout against a
        # dead dispatcher, and the port is actually free for a rebind.
        with self._conns_lock:
            conns = list(self._conns)
        for conn in conns:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                conn.close()
            except OSError:
                pass
        self._accept_thread.join(timeout=2.0)
        self._dispatcher.shutdown()
        log.info("maya-mcp plugin stopped")


def start_server(
    host: Optional[str] = None,
    port: Optional[int] = None,
    token: Optional[str] = None,
    body_deadline_s: float = DEFAULT_BODY_DEADLINE_S,
) -> PluginServer:
    """Start the plugin server; returns the running server (also kept globally)."""
    global _active_server
    _setup_logging()
    host = host or os.environ.get("MAYA_MCP_HOST", DEFAULT_HOST)
    port = int(port if port is not None else os.environ.get("MAYA_MCP_PORT", DEFAULT_PORT))
    token = token if token is not None else os.environ.get("MAYA_MCP_TOKEN") or None

    loopback = host in ("127.0.0.1", "localhost", "::1")
    if not loopback and (not token or os.environ.get("MAYA_MCP_BIND_ANY") != "1"):
        raise ValueError(
            "refusing to bind non-loopback host %r: set both MAYA_MCP_BIND_ANY=1 "
            "and a MAYA_MCP_TOKEN token to opt in" % host
        )

    if _active_server is not None:
        log.info("stopping previous plugin server before restart")
        _active_server.stop()
        _active_server = None

    _active_server = PluginServer(host, port, token, body_deadline_s=body_deadline_s)
    return _active_server


def stop_server() -> None:
    global _active_server
    if _active_server is not None:
        _active_server.stop()
        _active_server = None
