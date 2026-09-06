"""The stage a long-running handler is in, for the BusyError hint (#836).

A handler runs on Maya's main thread and, while it does, every other
request is refused with a BusyError built on the socket thread. The
kethran run's 40-minute bake answered those with nothing but the elapsed
seconds; "map 2 of 3: curvature 2048 for body, 380 s into it" is the half
that lets a caller tell slow from wedged. A handler reports here before
each long step; the dispatcher reads it while building the hint and clears
it around every job, so a stage never outlives the command that set it.

Maya-free, one process-wide slot: there is exactly one job in flight by
design (dispatcher module docstring), so one slot is the whole state.
"""

from __future__ import annotations

import threading
import time
from typing import Optional, Tuple

_lock = threading.Lock()
_stage: Optional[str] = None
_since: float = 0.0


def report(stage: str) -> None:
    """Record the stage the running handler has just entered. An empty
    stage clears."""
    global _stage, _since
    with _lock:
        _stage = stage or None
        _since = time.monotonic()


def clear() -> None:
    report("")


def current() -> Optional[Tuple[str, float]]:
    """(stage, seconds it has stood), or None when nothing is reported."""
    with _lock:
        if _stage is None:
            return None
        return _stage, time.monotonic() - _since
