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
# Past this many seconds stuck, the BusyError hint stops sounding like a
# normal "still running" wait and starts telling the caller it may be
# permanently wedged. Comfortably above MAX_TIMEOUT_S so it never fires for
# a legitimately long-running (but eventually finishing) operation that was
# given a large timeout_s.
_LIKELY_WEDGED_S = MAX_TIMEOUT_S * 2


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
        self._inflight: Optional[Future] = None
        self._straggler: Optional[Future] = None
        # What the worker is (or was) actually running, for the BusyError
        # hint below - set right before a handler starts on the main thread,
        # cleared the moment it returns (success, HandlerError, or any other
        # exception all go through the same _run_job return path).
        self._running_cmd: Optional[str] = None
        self._running_since: Optional[float] = None
        self._closed = False
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
        handler = self._handlers.get(cmd) if isinstance(cmd, str) else None
        if handler is None:
            return protocol.make_error(
                req_id,
                "UnknownCommandError",
                "unknown command %r" % (cmd,),
                hint="available commands: %s" % ", ".join(sorted(self._handlers)),
            )

        timeout_s = frame.get("timeout_s", self._default_timeout_s)
        if not isinstance(timeout_s, (int, float)) or isinstance(timeout_s, bool) or timeout_s <= 0:
            timeout_s = self._default_timeout_s
        timeout_s = min(float(timeout_s), MAX_TIMEOUT_S)

        params = frame.get("params") or {}
        fut: Future = Future()
        # Admission and enqueue are one critical section: one in-flight command,
        # period — a second request must never queue silently behind a running job.
        with self._lock:
            if self._closed:
                return protocol.make_error(
                    req_id,
                    "ServerStoppedError",
                    "the plugin server has been stopped",
                    hint="the plugin was stopped or restarted; reconnect to the new server",
                )
            if self._inflight is not None or self._straggler is not None:
                return protocol.make_error(
                    req_id,
                    "BusyError",
                    "a previous command is still executing in Maya",
                    hint=self._busy_hint(),
                )
            self._inflight = fut
            self._queue.put((fut, req_id, cmd, handler, params))
        try:
            return fut.result(timeout=timeout_s)
        # concurrent.futures.TimeoutError only became an alias of the builtin in
        # Python 3.11; Maya 2023/2024 embed 3.9/3.10, so catch both explicitly.
        except (_FutureTimeoutError, TimeoutError):
            with self._lock:
                if fut.cancel():
                    # Still queued, never started: it will never run. Not busy.
                    self._inflight = None
                    return protocol.make_error(
                        req_id,
                        "TimeoutError",
                        "command %r timed out after %.1f s before it started"
                        % (cmd, timeout_s),
                        hint="the command was cancelled and never ran; retry, "
                        "with a larger timeout_s if needed",
                    )
                if not fut.done():
                    # Running on Maya's main thread; keep _inflight set so the
                    # session stays busy until the straggler finishes.
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
        with self._lock:
            self._closed = True
        self._queue.put(None)
        self._worker.join(timeout=join_timeout_s)

    # ---------------------------------------------------------------- busy hint

    def _busy_hint(self) -> str:
        """Build the BusyError hint. Caller must hold self._lock.

        Recovery itself needs nothing extra: _worker_loop already clears
        _inflight/_straggler (and _running_cmd/_running_since, below) the
        instant the stuck handler's call to the main-thread executor
        returns - by success, HandlerError, or any other exception - so a
        genuinely-finished straggler unblocks the session on its own; this
        only makes the error explain what it's waiting for while that
        hasn't happened yet.

        No auto-clear-after-a-timeout and no cancel/reset command: the
        worker is a single thread blocked *synchronously* inside
        executeInMainThreadWithResult, so while a handler is genuinely
        wedged there, nothing this dispatcher does can free that thread to
        pick up a new job - forgetting the straggler would just start
        silently queuing requests behind a job that will never be dequeued,
        which is the exact "queues silently behind a running job" failure
        the one-in-flight design (see module docstring) exists to prevent.
        The only real fix for a truly wedged handler is restarting Maya,
        which is outside what a request over this socket can do, so the
        hint says so once the stall looks abnormal.
        """
        cmd = self._running_cmd or "a command"
        if self._running_since is None:
            return (
                "the session is busy running %r; it will unblock automatically "
                "the instant that command finishes - retry shortly" % cmd
            )
        elapsed_s = time.monotonic() - self._running_since
        hint = (
            "the session is busy: %r has been running for %.0fs; it will "
            "unblock automatically the instant that command finishes - retry "
            "shortly" % (cmd, elapsed_s)
        )
        if elapsed_s > _LIKELY_WEDGED_S:
            hint += (
                ". this is far longer than a Maya command normally takes - "
                "it may be permanently wedged on Maya's main thread (e.g. an "
                "interactive tool call that never returns); if it stays stuck, "
                "the only recovery is restarting Maya"
            )
        return hint

    # ------------------------------------------------------------------ worker

    def _worker_loop(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                return
            fut, req_id, cmd, handler, params = job
            if not fut.set_running_or_notify_cancel():
                # Cancelled by the timeout path before it started; never run it.
                with self._lock:
                    if self._inflight is fut:
                        self._inflight = None
                continue
            with self._lock:
                self._running_cmd = cmd
                self._running_since = time.monotonic()
            response = self._run_job(req_id, handler, params)
            with self._lock:
                fut.set_result(response)
                if self._inflight is fut:
                    self._inflight = None
                if self._straggler is fut:
                    # The caller already gave up on this job; drop its result and
                    # unblock the session.
                    self._straggler = None
                self._running_cmd = None
                self._running_since = None

    def _run_job(
        self, req_id: str, handler: Callable, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        start = time.monotonic()
        use_chunk = not getattr(handler, "no_undo_chunk", False)

        def run_on_main() -> Dict[str, Any]:
            if use_chunk and self._undo_open is not None:
                self._undo_open()
            try:
                return handler(params)
            finally:
                if use_chunk and self._undo_close is not None:
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
