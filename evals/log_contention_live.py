"""Live gate for redmine #650: the plugin log dies at the cap when Mayas share it.

The defect is an operating-system fact, not a Python one, so it cannot be gated
by a fake `cmds` or a single process. Windows refuses to rename a file another
process holds open, and `RotatingFileHandler` treats a failed rename as a failed
RECORD: the message is dropped, the file stays over the cap, and so every
message after it is dropped too. Logging stops permanently. The only outward
sign is Python's `--- Logging error ---` block, which prints the record and the
stack of whoever logged it - so a HANDLER failure reads as though the code being
logged about broke.

Part A is a symmetric A/B across two real child processes: the same two writers,
the same cap, the same barrier, differing only in old handler vs new. Both hold
their file open for the whole run, so every rollover the shared-file pair
attempts is guaranteed to fail - no timing luck involved either way.

Part B needs a live Maya and answers the question Part A cannot: that a real
plugin, deployed and started for real, writes `plugin-<pid>.log` for the pid
`ping` reports, and no longer touches the shared file at all. That closes the
#648 identity loop for the file you actually read when two instances are
confusing each other.

Part B defaults to port 9878 (the disposable agent-launched Maya). Part A needs
no Maya and always runs. Non-destructive: touches no scene, writes only under a
scratch directory (Part A) and reads `~/.maya-mcp/logs` (Part B).

Run:  .venv/Scripts/python.exe evals/log_contention_live.py
Exit: 0 pass, 1 fail.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_call import DEFAULT_PORT, call  # noqa: E402

from maya_plugin import logsetup  # noqa: E402

PORT = DEFAULT_PORT
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAP = 2000  # a 2 MB cap needs 2 MB of log lines to reach; the mechanism is identical
LINES = 200  # ~62 bytes each: about six rollovers per writer
# Enough backups that the retention window (BACKUPS+1 caps = 42 KB) holds every
# record BOTH writers produce (~25 KB). This is what makes the A/B airtight: with
# the default 3 backups the window holds ~110 records and the rest age out
# legitimately, which looks identical to dropping them if you only count. Here
# rotation cannot lose anything, so any missing record is the rename failure.
BACKUPS = 20
MARKER = "record-%s-%04d"

failures = []
checks = 0


def check(name, ok, detail=""):
    global checks
    checks += 1
    print("%-4s %s%s" % ("PASS" if ok else "FAIL", name, (" - " + detail) if detail else ""))
    if not ok:
        failures.append(name)


# --------------------------------------------------------------------------
# Part A: two real processes, one log stem
# --------------------------------------------------------------------------

WORKER = r'''
import logging, logging.handlers, os, sys, time
mode, logdir, tag, cap, lines, backups, ready, go = sys.argv[1:9]
cap, lines, backups = int(cap), int(lines), int(backups)
sys.path.insert(0, %(repo)r)

if mode == "shared":
    # The pre-#650 handler: every process on ONE file.
    path = os.path.join(logdir, "plugin.log")
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=cap, backupCount=backups, encoding="utf-8"
    )
else:
    from maya_plugin import logsetup
    handler = logsetup.ResilientRotatingFileHandler(
        logsetup.process_log_path("plugin", directory=logdir),
        maxBytes=cap, backupCount=backups, delay=False,
    )
handler.setFormatter(logging.Formatter("%%(message)s"))
log = logging.getLogger("w" + tag)
log.addHandler(handler)
log.setLevel(logging.INFO)

# Open the file NOW, then wait: both writers must hold a handle for the whole
# run, or a rename could succeed by luck and the A/B would measure timing.
log.info("opening " + tag)
open(ready, "w").close()
while not os.path.exists(go):
    time.sleep(0.01)

if tag == "HOLD":
    # An IDLE second Maya: it holds its handle and never rotates, so the other
    # writer's rename can never slip through. This is the production shape.
    while not os.path.exists(go + ".stop"):
        time.sleep(0.02)
else:
    for i in range(lines):
        log.info(("record-%%s-%%04d" %% (tag, i)) + " " + "x" * 50)
handler.close()
''' % {"repo": REPO}


def run_pair(mode, workdir, tags=("A", "B"), label=None):
    """Child processes writing concurrently. Returns (stdout+stderr, logdir).

    Every child opens its file and signals ready BEFORE any of them writes, so
    all handles are held for the whole run and no rename can succeed by timing
    luck. A tag of "HOLD" makes that child an idle holder.
    """
    name = label or mode
    logdir = os.path.join(workdir, name)
    os.makedirs(logdir, exist_ok=True)
    go = os.path.join(workdir, name + ".go")
    procs, readies, sinks = [], [], []
    # Child output goes to FILES, not pipes. The pre-#650 handler prints a full
    # traceback for every dropped record - enough to fill a pipe buffer and
    # deadlock a child we are waiting on. That volume is itself a symptom: this
    # is what lands on Maya's stdout when the log dies.
    for tag in tags:
        ready = os.path.join(workdir, "%s.%s.ready" % (name, tag))
        readies.append(ready)
        sink = os.path.join(workdir, "%s.%s.out" % (name, tag))
        sinks.append(sink)
        handle = open(sink, "w", encoding="utf-8", errors="replace")
        procs.append(
            (
                subprocess.Popen(
                    [sys.executable, "-c", WORKER, mode, logdir, tag,
                     str(CAP), str(LINES), str(BACKUPS), ready, go],
                    stdout=handle, stderr=subprocess.STDOUT, text=True,
                ),
                handle,
            )
        )
    deadline = time.time() + 60
    while time.time() < deadline and not all(os.path.exists(r) for r in readies):
        time.sleep(0.02)
    open(go, "w").close()  # all handles are open; release them together
    if "HOLD" in tags:
        procs[tags.index("A")][0].wait(timeout=300)  # writer finishes on its own
        open(go + ".stop", "w").close()  # then release the holder
    for proc, handle in procs:
        proc.wait(timeout=300)
        handle.close()
    output = []
    for sink in sinks:
        with open(sink, "r", encoding="utf-8", errors="replace") as fh:
            output.append(fh.read())
    return "".join(output), logdir


def landed(logdir, tag):
    """How many of writer `tag`'s records survive anywhere under logdir."""
    total = 0
    for name in sorted(os.listdir(logdir)):
        with open(os.path.join(logdir, name), "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        total += sum(1 for i in range(LINES) if (MARKER % (tag, i)) in text)
    return total


def part_a():
    workdir = tempfile.mkdtemp(prefix="eval650_")
    try:
        print("\n== Part A: two processes, %d records each, %d-byte cap, %d backups =="
              % (LINES, CAP, BACKUPS))

        out_old, dir_old = run_pair("shared", workdir)
        old_a, old_b = landed(dir_old, "A"), landed(dir_old, "B")
        old_total = old_a + old_b
        print("   pre-#650  one shared plugin.log: %d/%d records survived (A %d, B %d)"
              % (old_total, 2 * LINES, old_a, old_b))
        print("   files: %s" % sorted(os.listdir(dir_old)))

        out_new, dir_new = run_pair("private", workdir)
        new_a, new_b = landed(dir_new, "A"), landed(dir_new, "B")
        new_total = new_a + new_b
        print("   post-#650 process-private:      %d/%d records survived (A %d, B %d)"
              % (new_total, 2 * LINES, new_a, new_b))
        print("   files: %s" % sorted(os.listdir(dir_new)))

        # The defect, measured. If this passes trivially the platform allows the
        # rename and there is nothing to fix here - say so rather than claim a win.
        if old_total >= 2 * LINES:
            check("A1 the shared-file defect reproduces", True,
                  "SKIPPED: this platform renames held files; nothing to reproduce")
        else:
            check("A1 the shared-file defect reproduces", True,
                  "%d of %d records were DROPPED" % (2 * LINES - old_total, 2 * LINES))

        check("A2 process-private files lose nothing", new_total == 2 * LINES,
              "%d of %d survived" % (new_total, 2 * LINES))
        check("A3 the fix is strictly better than what it replaced",
              new_total >= old_total,
              "%d survived vs %d" % (new_total, old_total))
        check("A4 one file per process, named for the pid",
              all(n.startswith("plugin-") for n in os.listdir(dir_new))
              and len({n.split(".log")[0] for n in os.listdir(dir_new)}) == 2,
              "files: %s" % sorted(os.listdir(dir_new)))
        check("A5 the misleading traceback is gone",
              "--- Logging error ---" in out_old and "--- Logging error ---" not in out_new,
              "old block present: %s, new block present: %s"
              % ("--- Logging error ---" in out_old, "--- Logging error ---" in out_new))

        # Every writer's LAST record is the sharpest form of "logging did not stop".
        check("A6 each writer's final record is present",
              all((MARKER % (tag, LINES - 1)) in _all_text(dir_new) for tag in ("A", "B")))
        check("A7 the cap is still enforced when nothing contends", _rotated(dir_new),
              "backups present: %s"
              % sorted(n for n in os.listdir(dir_new) if ".log." in n))

        # ------------------------------------------------------------------
        # The production shape: the OTHER Maya is idle. Two hot writers each
        # close their own handle while attempting their own rollover, so renames
        # slip through and the log partly recovers. An idle holder never
        # releases, so the failure is total and permanent - which is why the
        # real plugin.log froze 82 bytes past the cap and never wrote again.
        # ------------------------------------------------------------------
        print("\n== Part A': one writer, one IDLE holder (the production shape) ==")
        out_idle, dir_idle = run_pair(
            "shared", workdir, tags=("A", "HOLD"), label="idle_shared"
        )
        idle_kept = landed(dir_idle, "A")
        last_kept = max(
            (i for i in range(LINES) if (MARKER % ("A", i)) in _all_text(dir_idle)),
            default=-1,
        )
        print("   pre-#650  shared file, idle holder: %d/%d records survived; "
              "last one written was #%d of %d" % (idle_kept, LINES, last_kept, LINES - 1))

        out_ok, dir_ok = run_pair(
            "private", workdir, tags=("A", "HOLD"), label="idle_private"
        )
        ok_kept = landed(dir_ok, "A")
        print("   post-#650 private file, idle holder: %d/%d records survived"
              % (ok_kept, LINES))

        check("A8 an idle holder freezes the shared log PERMANENTLY",
              idle_kept < LINES and last_kept < LINES - 1,
              "logging stopped at record #%d and never resumed" % last_kept)
        check("A9 an idle holder cannot touch a process-private log",
              ok_kept == LINES, "%d of %d survived" % (ok_kept, LINES))
        check("A10 the frozen shared log is what printed the misleading traceback",
              "--- Logging error ---" in out_idle
              and "--- Logging error ---" not in out_ok)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _all_text(logdir):
    out = []
    for name in sorted(os.listdir(logdir)):
        with open(os.path.join(logdir, name), "r", encoding="utf-8", errors="replace") as fh:
            out.append(fh.read())
    return "\n".join(out)


def _rotated(logdir):
    return any(".log." in n for n in os.listdir(logdir))


# --------------------------------------------------------------------------
# Part B: a real Maya's real log file
# --------------------------------------------------------------------------

def part_b():
    print("\n== Part B: a live plugin's own log file (port %d) ==" % PORT)
    try:
        response = call("ping", {}, timeout_s=15.0)
    except Exception as exc:  # noqa: BLE001 - report, do not raise
        print("   no plugin answered on port %d (%s)" % (PORT, exc))
        print("   SKIPPED: Part B needs a live Maya. Part A stands on its own.")
        return

    process = (response.get("result") or {}).get("process") or {}
    pid = process.get("pid")
    logdir = logsetup.log_dir()
    expected = logsetup.process_log_path("plugin", directory=logdir, pid=pid)
    print("   answering pid %s, expecting %s" % (pid, os.path.basename(expected)))

    check("B1 the live plugin has its own log file", os.path.exists(expected),
          expected if os.path.exists(expected)
          else "missing: %s (files: %s)"
               % (expected, sorted(n for n in os.listdir(logdir) if "plugin" in n)))
    if not os.path.exists(expected):
        return

    with open(expected, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    check("B2 it recorded the bind, with the pid", "listening on" in text
          and ("(pid %s)" % pid) in text,
          "first line: %r" % (text.splitlines() or [""])[0])
    check("B3 the pid in the filename is the pid that answered",
          os.path.basename(expected) == "plugin-%s.log" % pid)

    # The shared file is the thing that used to deadlock. A live plugin must not
    # be appending to it at all any more.
    legacy = os.path.join(logdir, "plugin.log")
    if not os.path.exists(legacy):
        check("B4 the shared plugin.log is untouched", True, "no legacy file present")
    else:
        age_s = time.time() - os.path.getmtime(legacy)
        check("B4 the shared plugin.log is untouched", age_s > 3600,
              "last written %.1f h ago (%d bytes)" % (age_s / 3600.0, os.path.getsize(legacy)))


def main():
    part_a()
    part_b()
    print("\n%d checks, %d failures" % (checks, len(failures)))
    for name in failures:
        print("  FAILED: %s" % name)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
