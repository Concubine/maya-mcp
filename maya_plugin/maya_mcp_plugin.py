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

import errno
import logging
import os
import socket
import threading
import time
from typing import Any, Dict, Optional

from . import logsetup, protocol, version
from .dispatcher import Dispatcher
from .handlers import (
    array,
    assemble,
    blendshape,
    capture,
    clip,
    code_exec,
    combine,
    etch,
    export,
    lighting,
    material,
    modeling,
    objinfo,
    pbr,
    physics,
    render,
    rigging,
    scene,
    sculpt,
    session,
    texbake,
    texture_recipes,
    uvatlas,
    viewport,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9877
# Windows reports a taken port as WSAEADDRINUSE, which is not errno.EADDRINUSE
# there - check both rather than let the real message escape as a bare OSError.
WSAEADDRINUSE = 10048

# Inbound requests never legitimately carry images (largest is execute_python
# source); the 64 MB protocol cap is for image-bearing responses only.
INBOUND_MAX_BYTES = 4 * 1024 * 1024
# Once a frame has started arriving, the rest must follow promptly; a half-sent
# frame must not pin a connection thread forever. Idle connections (no bytes at
# all) are healthy and block indefinitely.
DEFAULT_BODY_DEADLINE_S = 30.0

log = logging.getLogger("maya_mcp_plugin")

_active_server: Optional["PluginServer"] = None
_bound_at: Optional[float] = None  # epoch seconds, set when the socket binds


class PortInUseError(OSError):
    """Another process already holds the port this plugin was told to bind.

    An OSError subclass on purpose: this replaces the bare bind OSError with a
    message that says what it means, and callers already catching OSError keep
    working.
    """


def _port_in_use_message(host: str, port: int) -> str:
    """Said in full, because the alternative is worse than a crash.

    A Maya whose bind failed looks completely normal - it just has no plugin,
    while the process that won the port keeps answering calls meant for this
    one. Two Mayas on this machine lost this race silently (#648), so the
    failure says who to ask and what to do about it.
    """
    return (
        "\n" + "!" * 72 + "\n"
        "maya-mcp could NOT bind %s:%d - another process already holds it.\n"
        "This Maya has NO plugin listening. Anything sent to that port is being\n"
        "answered by the other process, not by this one (maya-mcp #648).\n"
        "Find the holder:\n"
        "  Get-NetTCPConnection -State Listen -LocalPort %d | select OwningProcess\n"
        "Then kill it (taskkill /F /T /PID <id>) or start this Maya on another\n"
        "port: MAYA_MCP_PORT=<free port> before launch, or\n"
        "maya_mcp_plugin.start_server(port=<free port>) here.\n" + "!" * 72
    ) % (host, port, port)


def is_maya_available() -> bool:
    try:
        import maya.cmds  # noqa: F401, PLC0415

        return True
    except ImportError:
        return False


def _scene_name() -> Optional[str]:
    """The open scene, or None when Maya cannot answer. Never raises: ping must
    keep working when the thing it is reporting on does not."""
    try:
        import maya.cmds as cmds  # noqa: PLC0415

        return cmds.file(query=True, sceneName=True) or ""
    except Exception:  # noqa: BLE001 - see docstring
        return None


def _process_info() -> Dict[str, Any]:
    """WHICH process is answering - a port is not an identity (maya-mcp #648).

    An agent that launches a Maya and then talks to MAYA_MCP_PORT is only
    assuming the answer comes from the process it started; if another Maya
    already held that port, the launched one comes up with a dead plugin and
    every call lands in the other session, silently. `pid` settles it, and
    `scene` makes it recognisable to a human reading the log.

    started_at is when this plugin BOUND the port, not when Maya started - it
    is what distinguishes a restart, which is what callers actually ask about.
    """
    server = _active_server
    started = _bound_at
    return {
        "pid": os.getpid(),
        "host": server.host if server is not None else None,
        "port": server.port if server is not None else None,
        "started_at": started,
        "uptime_s": round(time.time() - started, 1) if started else None,
        "scene": _scene_name(),
    }


def _ping(params: Dict[str, Any]) -> Dict[str, Any]:
    """Liveness AND identity: which copy of the plugin is running, in which process.

    The live Maya may import <Documents>/maya/scripts/maya_plugin rather than the
    repo, so callers need a way to tell whether a green result describes their
    code. See version.py; clients feed `plugin` to version.compare(). `process`
    answers the other half - whether it describes their Maya (#648).
    """
    return {
        "pong": True,
        "maya": is_maya_available(),
        "plugin": version.plugin_info(),
        "process": _process_info(),
    }


def _build_handlers() -> Dict[str, Any]:
    return {
        "ping": _ping,
        "execute_python": code_exec.execute_python,
        "reset_namespace": code_exec.reset_namespace,
        "get_scene_graph": scene.get_scene_graph,
        "get_object_info": objinfo.get_object_info,
        "capture_viewport": capture.capture_viewport,
        "capture_turntable": capture.capture_turntable,
        "render_scene": render.render_scene,
        "render_sheet": render.render_sheet,
        "checkpoint": session.checkpoint,
        "restore_checkpoint": session.restore_checkpoint,
        "undo": session.undo,
        "redo": session.redo,
        "new_scene": session.new_scene,
        "open_scene": session.open_scene,
        "save_scene": session.save_scene,
        "export_fbx": export.export_fbx,
        "bake_textures": texbake.bake_textures,
        "create_primitive": modeling.create_primitive,
        "duplicate": modeling.duplicate,
        "array": array.array,
        "transform": modeling.transform,
        "group": modeling.group,
        "parent": modeling.parent,
        "rename": modeling.rename,
        "delete_objects": modeling.delete_objects,
        "boolean_op": modeling.boolean_op,
        "combine": combine.combine,
        "assemble": assemble.assemble,
        "uv_atlas": uvatlas.uv_atlas,
        "remesh_retopo": modeling.remesh_retopo,
        "mesh_cleanup": modeling.mesh_cleanup,
        "etch_text": etch.etch_text,
        "sculpt_ops": sculpt.sculpt_ops,
        "deform": sculpt.deform,
        "set_viewport": viewport.set_viewport,
        "set_camera": viewport.set_camera,
        "setup_lighting": lighting.setup_lighting,
        "assign_material": material.assign_material,
        "assign_pbr": pbr.assign_pbr,
        "apply_texture_recipe": texture_recipes.apply_texture_recipe,
        "create_skeleton": rigging.create_skeleton,
        "bind_skin": rigging.bind_skin,
        "pose_skeleton": rigging.pose_skeleton,
        "reset_pose": rigging.reset_pose,
        "weight_report": rigging.weight_report,
        "mirror_weights": rigging.mirror_weights,
        "smooth_weights": rigging.smooth_weights,
        "set_region_weights": rigging.set_region_weights,
        "pose_ik": rigging.pose_ik,
        "author_physics": physics.author_physics,
        "create_blendshape": blendshape.create_blendshape,
        "set_blendshape_weights": blendshape.set_blendshape_weights,
        "author_clip": clip.author_clip,
        "delete_clip": clip.delete_clip,
        "preview_clip": clip.preview_clip,
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


def _setup_logging() -> None:
    """One log file per process: `plugin-<pid>.log`. See logsetup (#650) — a
    single shared file cannot be rotated while another Maya holds it open, and
    the failure is a permanent, silent log outage."""
    logsetup.configure(log, "plugin")


class PluginServer:
    def __init__(
        self,
        host: str,
        port: int,
        token: Optional[str],
        body_deadline_s: float = DEFAULT_BODY_DEADLINE_S,
    ):
        global _bound_at

        # Bind FIRST: if the port is taken, fail before spawning any thread.
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        try:
            self._sock = socket.create_server((host, port), family=family)
        except OSError as exc:
            if exc.errno in (errno.EADDRINUSE, WSAEADDRINUSE):
                raise PortInUseError(_port_in_use_message(host, port)) from exc
            raise
        self._sock.settimeout(0.25)
        self.host = host
        self.port = self._sock.getsockname()[1]
        _bound_at = time.time()
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
        # The pid is here as well as in the filename: it is what someone greps
        # for after `ping` tells them which process they are actually talking to.
        log.info(
            "maya-mcp plugin listening on %s:%d (pid %d)",
            self.host,
            self.port,
            os.getpid(),
        )

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

    try:
        _active_server = PluginServer(host, port, token, body_deadline_s=body_deadline_s)
    except PortInUseError as exc:
        # userSetup starts this through executeDeferred, where a traceback is
        # one more scrolling line in a busy script editor. Say it plainly, and
        # to the log, before letting it raise.
        print(str(exc))
        log.error("%s", exc)
        raise
    return _active_server


def stop_server() -> None:
    global _active_server
    if _active_server is not None:
        _active_server.stop()
        _active_server = None
