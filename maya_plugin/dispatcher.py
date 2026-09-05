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
# Raised from 600 for #640. A timeout here does NOT stop the command - Maya runs
# it to completion on the main thread and the session stays busy either way - so
# this ceiling only decides how long the caller waits before being told
# something it cannot act on. A 29-cell Arnold contact sheet needs longer than
# ten minutes, and the timeout hint tells callers to pass a larger timeout_s, so
# a ceiling below what a legitimate render costs made that advice unfollowable.
MAX_TIMEOUT_S = 1800.0
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


def require_known_keys(params, allowed, command: str, synonyms=None) -> None:
    """Refuse a param this command does not read, naming what was meant.

    A key a handler never looks at is worse than a wrong value: a wrong value
    fails, an unread key succeeds and does something else. Measured on #764 -
    `assign_material` reads its explicit-name param as `name`, and eleven
    tests passed `material=` instead. Every one of them created a
    differently-named material than it believed it was creating, and every one
    of them PASSED, because they read the name back out of the result rather
    than pinning it. Nothing anywhere said a word.

    `synonyms` maps a wrong key to the right one for the cases that have
    actually been seen. It exists because the realistic cause is a plausible
    SYNONYM, not a typo, and no string-similarity test finds one: `material`
    and `name` share not a single letter in position. A caller who reaches for
    the wrong word will reach for it again next time, so the answer is
    recorded rather than guessed at. Prefix matching stays as the fallback for
    ordinary typos.
    """
    unknown = sorted(set(params) - set(allowed))
    if not unknown:
        return
    synonyms = synonyms or {}
    hints = []
    for key in unknown:
        if key in synonyms:
            hints.append("%r is called %r here" % (key, synonyms[key]))
            continue
        near = [a for a in sorted(allowed)
                if a.startswith(key[:3]) or key.startswith(a[:3])]
        if near:
            hints.append("%r - did you mean %s?"
                         % (key, " or ".join(repr(n) for n in near)))
    raise HandlerError(
        "%s does not take %s" % (command, ", ".join(repr(k) for k in unknown)),
        hint=("; ".join(hints) + ". " if hints else "")
        # A command that reads nothing used to end its refusal on the words
        # "valid params: " and stop, naming none because there are none
        # (measured on reset_namespace, #829). Say the actual fact instead.
        + ("%s reads no params at all - call it with an empty object" % command
           if not allowed else
           "valid params: %s" % ", ".join(sorted(allowed))),
    )


def refuse_inert(command: str, param: str, branch: str, why: str,
                 hint: Optional[str] = None) -> None:
    """Refuse a param the caller PASSED that this branch of the command drops.

    The level below require_known_keys (#797): a key the handler knows,
    accepts, validates, and then never consumes on the branch another
    param's value selects. #797's confirmed instance is `divisions` on an
    icosahedron - range-checked like every other primitive's, then discarded
    because polyPlatonicSolid has no subdivision flag, so the caller asked
    for a denser solid and got the same 20 faces with no word said.

    The wording is shared so tests/test_branch_contract.py can recognise
    every instance generically: `<command> does not use '<param>' <branch>:
    <why>`. `branch` names the branch in the caller's own terms ("on an
    icosahedron", "in mirror mode", "when atlas is null"); `why` says what
    Maya or the handler actually does there, so the caller can tell a
    refusal of their intent from a refusal of their spelling.
    """
    raise HandlerError(
        "%s does not use '%s' %s: %s" % (command, param, branch, why),
        hint=hint,
    )


class Dispatcher:
    def __init__(
        self,
        handlers: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]],
        main_thread_exec: Optional[Callable[[Callable[[], Any]], Any]] = None,
        token: Optional[str] = None,
        default_timeout_s: float = DEFAULT_TIMEOUT_S,
        undo_open: Optional[Callable[[], None]] = None,
        undo_close: Optional[Callable[[], None]] = None,
        undo_flush: Optional[Callable[[], None]] = None,
    ):
        self._handlers = dict(handlers)
        self._main_thread_exec = main_thread_exec or (lambda fn: fn())
        self._token = token
        self._default_timeout_s = default_timeout_s
        self._undo_open = undo_open
        self._undo_close = undo_close
        self._undo_flush = undo_flush

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
        requested_timeout_s = float(timeout_s)
        timeout_s = min(requested_timeout_s, MAX_TIMEOUT_S)

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
            # Do not advise a larger timeout_s when the caller is already at the
            # ceiling - that advice cannot be followed, and following it is what
            # #640 found impossible.
            if timeout_s >= MAX_TIMEOUT_S:
                hint = (
                    "the command is still running in Maya and the session is busy "
                    "until it finishes. This was already the maximum timeout "
                    "(%.0f s), so waiting longer is not available: split the work "
                    "- fewer subjects per sheet, fewer samples, or a lower "
                    "resolution." % MAX_TIMEOUT_S
                )
            else:
                hint = (
                    "the command is still running in Maya and the session is busy "
                    "until it finishes; for long operations pass a larger "
                    "timeout_s (up to %.0f s) or split the work" % MAX_TIMEOUT_S
                )
            return protocol.make_error(
                req_id,
                "TimeoutError",
                "command %r did not finish within %.1f s" % (cmd, timeout_s),
                hint=hint,
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
            if getattr(handler, "flush_undo_first", False) and self._undo_flush is not None:
                # A handler that replaces the scene (redmine #847). MEASURED on
                # Maya 2027: after an isolate capture, file-new spins forever
                # unless the undo queue was flushed in a SEPARATE request
                # first - the same flush inside the handler, in every order
                # tried, still spins. Separate requests are separate
                # main-thread executions with Maya's event loop running
                # between them, so the flush gets its own hop here, and the
                # handler runs as the next one.
                self._main_thread_exec(self._undo_flush)
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
