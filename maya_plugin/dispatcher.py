"""Request dispatcher for the Maya plugin.

Maya-free by design: the main-thread executor (maya.utils.executeInMainThreadWithResult
in production) and the undo-chunk hooks (maya.cmds.undoInfo in production) are injected,
so this module is fully testable outside Maya.

Threading model (design doc section 3.3):
- The socket thread calls handle_request() and blocks on a Future with the
  request's timeout.
- A single worker thread pulls jobs off a queue and runs each handler through
  the injected main-thread executor, so handlers always run on Maya's main thread.
- On timeout the caller gets a structured TimeoutError response and the session
  is flagged busy until the straggling handler finishes; its late result is
  dropped, never delivered to a different request id.
"""

from __future__ import annotations

import queue
import threading
import time
import traceback
from concurrent.futures import Future
from concurrent.futures import TimeoutError as _FutureTimeoutError
from typing import Any, Callable, Dict, Optional

from . import protocol

DEFAULT_TIMEOUT_S = 30.0
MAX_TIMEOUT_S = 600.0


class HandlerError(Exception):
    """Controlled handler failure: a clean message plus an actionable hint.

    Raise this for anticipated conditions (unknown object, bad argument) where a
    traceback would be noise. Unexpected exceptions get full tracebacks instead.
    """

    def __init__(self, message: str, hint: Optional[str] = None):
        super().__init__(message)
        self.hint = hint


class Dispatcher:
    def __init__(
        self,
        handlers: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]],
        main_thread_exec: Optional[Callable[[Callable[[], Any]], Any]] = None,
        token: Optional[str] = None,
        default_timeout_s: float = DEFAULT_TIMEOUT_S,
        undo_open: Optional[Callable[[], None]] = None,
        undo_close: Optional[Callable[[], None]] = None,
    ):
        self._handlers = dict(handlers)
        self._main_thread_exec = main_thread_exec or (lambda fn: fn())
        self._token = token
        self._default_timeout_s = default_timeout_s
        self._undo_open = undo_open
        self._undo_close = undo_close

        self._lock = threading.Lock()
        self._straggler: Optional[Future] = None
        self._queue: "queue.Queue[Optional[tuple]]" = queue.Queue()
        self._worker = threading.Thread(
            target=self._worker_loop, name="maya-mcp-dispatch", daemon=True
        )
        self._worker.start()

    # ------------------------------------------------------------------ public

    def handle_request(self, frame: Dict[str, Any]) -> Dict[str, Any]:
        """Process one request frame; always returns a response frame."""
        req_id = str(frame.get("id", ""))

        if frame.get("v") != protocol.PROTOCOL_VERSION:
            return protocol.make_error(
                req_id,
                "ProtocolVersionError",
                "unsupported protocol version %r (plugin speaks v%d)"
                % (frame.get("v"), protocol.PROTOCOL_VERSION),
                hint="upgrade the maya-mcp server or the Maya plugin so both speak v%d"
                % protocol.PROTOCOL_VERSION,
            )

        if not protocol.token_ok(frame, self._token):
            return protocol.make_error(
                req_id,
                "AuthError",
                "missing or invalid token",
                hint="set MAYA_MCP_TOKEN to the same value for the server and the plugin",
            )

        cmd = frame.get("cmd")
        handler = self._handlers.get(cmd)
        if handler is None:
            return protocol.make_error(
                req_id,
                "UnknownCommandError",
                "unknown command %r" % cmd,
                hint="available commands: %s" % ", ".join(sorted(self._handlers)),
            )

        with self._lock:
            if self._straggler is not None:
                return protocol.make_error(
                    req_id,
                    "BusyError",
                    "a previous command is still executing in Maya",
                    hint="the session is busy until the straggling command finishes; "
                    "retry shortly",
                )

        timeout_s = frame.get("timeout_s", self._default_timeout_s)
        if not isinstance(timeout_s, (int, float)) or timeout_s <= 0:
            timeout_s = self._default_timeout_s
        timeout_s = min(float(timeout_s), MAX_TIMEOUT_S)

        params = frame.get("params") or {}
        fut: Future = Future()
        self._queue.put((fut, req_id, handler, params))
        try:
            return fut.result(timeout=timeout_s)
        # concurrent.futures.TimeoutError only became an alias of the builtin in
        # Python 3.11; Maya 2023/2024 embed 3.9/3.10, so catch both explicitly.
        except (_FutureTimeoutError, TimeoutError):
            with self._lock:
                if not fut.done():
                    self._straggler = fut
            return protocol.make_error(
                req_id,
                "TimeoutError",
                "command %r did not finish within %.1f s" % (cmd, timeout_s),
                hint="the command is still running in Maya and the session is busy "
                "until it finishes; for long operations pass a larger timeout_s "
                "or split the work",
            )

    def shutdown(self, join_timeout_s: float = 2.0) -> None:
        self._queue.put(None)
        self._worker.join(timeout=join_timeout_s)

    # ------------------------------------------------------------------ worker

    def _worker_loop(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                return
            fut, req_id, handler, params = job
            response = self._run_job(req_id, handler, params)
            with self._lock:
                fut.set_result(response)
                if self._straggler is fut:
                    # The caller already gave up on this job; drop its result and
                    # unblock the session.
                    self._straggler = None

    def _run_job(
        self, req_id: str, handler: Callable, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        start = time.monotonic()

        def run_on_main() -> Dict[str, Any]:
            if self._undo_open is not None:
                self._undo_open()
            try:
                return handler(params)
            finally:
                if self._undo_close is not None:
                    self._undo_close()

        try:
            result = self._main_thread_exec(run_on_main)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            if not isinstance(result, dict):
                result = {"value": result}
            return protocol.make_ok(req_id, result, elapsed_ms)
        except HandlerError as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return protocol.make_error(
                req_id,
                type(exc).__name__,
                str(exc),
                hint=exc.hint,
                elapsed_ms=elapsed_ms,
            )
        except Exception as exc:  # noqa: BLE001 - never swallow, always report
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return protocol.make_error(
                req_id,
                type(exc).__name__,
                str(exc),
                maya_traceback=traceback.format_exc(),
                elapsed_ms=elapsed_ms,
            )
