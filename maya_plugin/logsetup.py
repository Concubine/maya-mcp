"""Log files that survive several Mayas at once (maya-mcp #650).

Every plugin process used to log to one shared `~/.maya-mcp/logs/plugin.log`.
Windows cannot rename a file another process holds open, so the moment that
file reached `RotatingFileHandler`'s cap while a second Maya (or the MCP
server) had it open, `doRollover` raised `PermissionError` — and then did so on
every subsequent write. Logging stopped permanently, and the only outward sign
was Python's `--- Logging error ---` block on stdout, which prints the record
being logged and the stack of whoever logged it, so a *handler* failure reads
as though the code being logged about broke.

Measured cost: a 2,000,082-byte frozen log, and three Mayas started afterwards
whose "plugin listening on ..." lines were never recorded. A gap in the backup
numbering (`plugin.log`, `.1`, `.3`, no `.2`) is this bug's fingerprint — the
`.N`→`.N+1` renames succeed, since nobody holds a backup, and only the
`base`→`.1` rename fails.

Two changes here, and the first is the actual fix:

* **The file is process-private:** `plugin-<pid>.log`. Rollover renames a file
  only this process holds, so it cannot contend. It also means a log finally
  says which process wrote it — the identity gap #648 closed for `ping`, closed
  here for the one file you consult when two instances are confusing each other.
* **A rollover that fails anyway degrades instead of going silent.** A tail, an
  editor or a backup agent can hold any file. When rename fails we keep
  appending past the cap and say so once, in the log itself. An oversized log is
  a nuisance; a log that stops is a lie.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from typing import Dict, List, Optional, Tuple

DEFAULT_MAX_BYTES = 2_000_000
DEFAULT_BACKUP_COUNT = 3
# Process-private files accumulate one set per Maya launch, so configure()
# prunes by session. Keep enough that yesterday's confusing pair is still there.
DEFAULT_KEEP_SESSIONS = 8

LINE_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def log_dir() -> str:
    """MAYA_MCP_LOG_DIR, else `~/.maya-mcp/logs`.

    The override exists so tests (and anyone with a small home volume) can point
    logging somewhere else; without it the only way to exercise this module is to
    write into the user's real log directory.
    """
    override = os.environ.get("MAYA_MCP_LOG_DIR", "").strip()
    if override:
        return os.path.expanduser(override)
    return os.path.join(os.path.expanduser("~"), ".maya-mcp", "logs")


def level_from_env() -> int:
    """MAYA_MCP_LOG_LEVEL, falling back to INFO on any unknown value —
    a typo'd level must never take the process down."""
    name = os.environ.get("MAYA_MCP_LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, name, None)
    return level if isinstance(level, int) else logging.INFO


def process_log_path(
    stem: str, directory: Optional[str] = None, pid: Optional[int] = None
) -> str:
    """`<stem>-<pid>.log`. The pid is the point — see the module docstring."""
    base = log_dir() if directory is None else directory
    return os.path.join(base, "%s-%d.log" % (stem, os.getpid() if pid is None else pid))


def _pid_of(name: str, stem: str) -> Optional[int]:
    """The pid in `<stem>-<pid>.log` or one of its `.1`/`.2` backups, else None.

    Returning None for the legacy shared `plugin.log` is deliberate: pruning must
    not delete files written before this fix landed.
    """
    prefix = stem + "-"
    if not name.startswith(prefix) or ".log" not in name:
        return None
    head = name[len(prefix) :].split(".log", 1)[0]
    return int(head) if head.isdigit() else None


def prune(
    stem: str,
    directory: Optional[str] = None,
    keep_sessions: int = DEFAULT_KEEP_SESSIONS,
) -> List[str]:
    """Delete all but the `keep_sessions` newest processes' logs. Returns what went.

    A file another process still holds open cannot be deleted on Windows, and
    that is exactly the behaviour we want: a live session's log becomes
    prunable only once that session is gone. So this needs no liveness check —
    the OS is the interlock.
    """
    base = log_dir() if directory is None else directory
    try:
        names = os.listdir(base)
    except OSError:
        return []

    sessions: Dict[int, List[Tuple[float, str]]] = {}
    for name in names:
        pid = _pid_of(name, stem)
        if pid is None:
            continue
        path = os.path.join(base, name)
        try:
            sessions.setdefault(pid, []).append((os.path.getmtime(path), path))
        except OSError:
            continue  # vanished under us; nothing to prune

    newest_first = sorted(
        sessions.values(), key=lambda files: max(t for t, _ in files), reverse=True
    )
    removed = []
    for files in newest_first[max(0, keep_sessions) :]:
        for _, path in files:
            try:
                os.remove(path)
            except OSError:
                continue  # held by a live process, or already gone
            removed.append(path)
    return removed


class ResilientRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """Rotates when it can, appends when it cannot, and never stops silently.

    `RotatingFileHandler` treats a failed rename as a failed *record*: the
    message is dropped and, because the file stays over the cap, so is every
    message after it. Here a rename failure downgrades the cap instead —
    losing the size bound is strictly better than losing the log.
    """

    def __init__(
        self,
        filename: str,
        maxBytes: int = DEFAULT_MAX_BYTES,
        backupCount: int = DEFAULT_BACKUP_COUNT,
        **kwargs,
    ):
        # delay=True: a process that never logs leaves no empty file behind.
        kwargs.setdefault("delay", True)
        kwargs.setdefault("encoding", "utf-8")
        super().__init__(
            filename, maxBytes=maxBytes, backupCount=backupCount, **kwargs
        )
        self.degraded = False
        self._retry_at_bytes = 0
        self._said_degraded = False
        self._said_error = False

    def doRollover(self) -> None:
        try:
            super().doRollover()
        except OSError as exc:
            self._degrade(exc)
        else:
            self.degraded = False

    def shouldRollover(self, record) -> bool:  # type: ignore[override]
        # While degraded, do not re-attempt the rename for every single record:
        # it cannot succeed while the other holder is still there, and the cost
        # would be a failed syscall per log line. Retry once the file has grown
        # another full cap, so a contender that goes away is picked up again.
        if self.degraded and self._current_size() < self._retry_at_bytes:
            return False
        return bool(super().shouldRollover(record))

    def _current_size(self) -> int:
        try:
            return os.path.getsize(self.baseFilename)
        except OSError:
            return 0

    def _degrade(self, exc: OSError) -> None:
        self.degraded = True
        self._arm_retry()
        if self.stream is None:  # doRollover closed it before the rename failed
            try:
                self.stream = self._open()
            except OSError:
                return  # nothing left to say it with; handleError covers this
        if not self._said_degraded:
            self._said_degraded = True
            self._write_plainly(
                "maya-mcp logging: cannot rotate %s (%s). Appending past the "
                "%d-byte cap rather than dropping records; this log will grow."
                % (self.baseFilename, exc, self.maxBytes)
            )
        # Re-arm AFTER the notice. The notice is itself a few hundred bytes, and
        # measuring the threshold before writing it let our own message push the
        # file over the retry line - so the very next record tried the doomed
        # rename again, which is the behaviour this whole class exists to avoid.
        self._arm_retry()

    def _arm_retry(self) -> None:
        self._retry_at_bytes = self._current_size() + max(1, self.maxBytes)

    def _write_plainly(self, message: str) -> None:
        """Into the log, and onto stderr — whichever survives is the one read."""
        try:
            self.stream.write(message + "\n")
            self.flush()
        except (OSError, ValueError, AttributeError):
            pass
        try:
            sys.stderr.write(message + "\n")
        except Exception:  # a detached stderr must not become a logging failure
            pass

    def handleError(self, record) -> None:
        """One plain sentence, not logging's misleading traceback.

        `logging.raiseExceptions` prints the record and the stack of whoever
        logged it, which reads as though *that* code failed. Say what actually
        failed, once, and never raise into the caller — this runs inside Maya.
        """
        if self._said_error:
            return
        self._said_error = True
        exc = sys.exc_info()[1]
        try:
            sys.stderr.write(
                "maya-mcp logging: %s is no longer being written (%s: %s)\n"
                % (self.baseFilename, type(exc).__name__, exc)
            )
        except Exception:
            pass


def configure(
    logger: logging.Logger,
    stem: str,
    directory: Optional[str] = None,
    keep_sessions: int = DEFAULT_KEEP_SESSIONS,
) -> Optional[ResilientRotatingFileHandler]:
    """Attach one process-private rotating handler to `logger`. Idempotent.

    Returns the handler, or None if the directory could not be made or opened —
    logging must never take the plugin or the server down, so an unwritable log
    directory is a silent no-op here and nowhere else.
    """
    logger.setLevel(level_from_env())
    for existing in logger.handlers:
        if isinstance(existing, ResilientRotatingFileHandler):
            return existing

    base = log_dir() if directory is None else directory
    try:
        os.makedirs(base, exist_ok=True)
        prune(stem, directory=base, keep_sessions=keep_sessions)
        handler = ResilientRotatingFileHandler(process_log_path(stem, directory=base))
    except OSError:
        return None
    handler.setFormatter(logging.Formatter(LINE_FORMAT))
    logger.addHandler(handler)
    return handler
