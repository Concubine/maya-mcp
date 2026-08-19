"""Live gate for redmine #604: the handshake must catch a deployed-but-not-
restarted session instead of reading CLEAN against it.

The defect: `plugin_info()` answered from DISK on every ping, and in the window
between install.py and a Maya restart the disk holds exactly the code that is
NOT running. A caller measured the old handlers and attributed the results to
the new branch (#601), and #640's eval reported two fresh fixes as regressions
for the same reason. The fix reports what the session LOADED alongside what is
on disk, and compare() judges by the loaded identity.

This gate walks the actual window on a real Maya, in four phases:

  A. deploy clean, TAMPER the deployed copy, launch Maya -> it loads the
     tampered code, which stands in for "the old build".
  B. ping: plain STALE expected (loaded == disk == tampered, both differ from
     the working tree). The old code also caught this case.
  C. redeploy clean. Disk now == working tree, session still tampered. This IS
     the #604 window: the old, disk-judging handshake read CLEAN here (asserted
     directly against the on-disk digest), the fixed one must say NOT RESTARTED.
  D. restart Maya -> loaded == disk == working tree -> clean.

DESTRUCTIVE, and it owns the whole lifecycle: it launches and kills its own
Maya (only pids it started, via taskkill /T), and it rewrites the DEPLOYED
plugin copy - tampering it mid-run and leaving it freshly installed from this
tree at the end. Refuses port 9877 unless MAYA_MCP_ALLOW_USER_SESSION=1.

Run:  .venv/Scripts/python.exe evals/staleness_live.py
Exit: 0 pass, 1 fail, 2 environment (no maya.exe / port busy).
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maya_mcp.connection import MayaConnection, MayaConnectionError  # noqa: E402
from maya_plugin import version  # noqa: E402


class WrongProcess(Exception):
    """The port answered, but not from the Maya this gate launched."""

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAYA_EXE = os.environ.get("MAYA_EXE", r"E:\Autodesk\Maya2027\bin\maya.exe")
PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
DEPLOYED = os.path.join(
    os.path.expanduser("~"), "Documents", "maya", "scripts", "maya_plugin"
)
# Appended to a deployed source file to stand in for "an older build": it
# changes the content digest without changing any behaviour.
TAMPER_LINE = "\n# staleness_604_tamper - a stand-in for an older build\n"
BOOT_TIMEOUT_S = 240.0

if PORT == 9877 and os.environ.get("MAYA_MCP_ALLOW_USER_SESSION") != "1":
    print("refusing to run against port 9877 (the user's Maya). Set "
          "MAYA_MCP_ALLOW_USER_SESSION=1 to override.")
    raise SystemExit(2)

failures = []
checks = 0


def check(name, ok, detail=""):
    global checks
    checks += 1
    print("%-4s %s%s" % ("PASS" if ok else "FAIL", name,
                         (" - " + str(detail)) if detail else ""))
    if not ok:
        failures.append(name)


def deploy():
    out = subprocess.run(
        [sys.executable, os.path.join(REPO, "maya_plugin", "install.py"), "--yes"],
        capture_output=True, text=True, timeout=120,
    )
    if out.returncode != 0:
        raise RuntimeError("install.py failed: %s%s" % (out.stdout, out.stderr))


def tamper():
    with open(os.path.join(DEPLOYED, "version.py"), "a", encoding="utf-8") as fh:
        fh.write(TAMPER_LINE)


def port_free() -> bool:
    with socket.socket() as probe:
        return probe.connect_ex(("127.0.0.1", PORT)) != 0


def launch_maya() -> subprocess.Popen:
    # cwd MUST NOT be the repo: Maya puts its working directory on sys.path, so
    # a Maya launched from D:/devel/maya-mcp imports the REPO's maya_plugin and
    # never touches the deployed copy - this gate's first run measured exactly
    # that (loaded digest == working tree while the deployed copy sat tampered
    # on disk), and any agent launching Maya from the repo gets the same silent
    # bypass of the deploy mechanism.
    env = dict(os.environ, MAYA_MCP_PORT=str(PORT))
    return subprocess.Popen([MAYA_EXE], env=env, cwd=os.path.expanduser("~"),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_for_ping(expect_pid: int):
    """The answering plugin, pid-verified (#648): a port is not an identity."""
    deadline = time.time() + BOOT_TIMEOUT_S
    while time.time() < deadline:
        try:
            conn = MayaConnection(port=PORT)
            pong = conn.request("ping", {}, timeout_s=10.0)
        except (OSError, MayaConnectionError):
            time.sleep(3.0)  # still booting
            continue
        pid = (pong.get("process") or {}).get("pid")
        if pid != expect_pid:
            raise WrongProcess(
                "port %d answered from pid %s, not the Maya launched here (%d) "
                "- another session holds the port" % (PORT, pid, expect_pid)
            )
        return conn, pong
    raise RuntimeError("no plugin answered on %d within %.0fs" % (PORT, BOOT_TIMEOUT_S))


def _port_owner() -> int | None:
    """The pid LISTENING on PORT, from netstat - the ground truth, independent
    of process genealogy."""
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True)
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0] == "TCP" \
                and parts[1].endswith(":%d" % PORT) and parts[3] == "LISTENING":
            return int(parts[4])
    return None


def kill_maya(proc: subprocess.Popen, known_pid: int | None = None):
    """taskkill /T on every pid we know, then VERIFY the port is released.

    One run of this gate left a live Maya behind because the kill trusted the
    Popen pid alone and never checked the outcome - the next run then refused
    to start against the port it had itself leaked. Silence after a kill is a
    claim, and claims get verified: if something still listens, kill the
    netstat owner, and if even that fails, say so instead of returning.
    """
    pids = {proc.pid}
    if known_pid:
        pids.add(known_pid)
    for pid in pids:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True, text=True)
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        pass
    deadline = time.time() + 30
    while not port_free() and time.time() < deadline:
        time.sleep(1.0)
    if not port_free():
        owner = _port_owner()
        if owner:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(owner)],
                           capture_output=True, text=True)
            time.sleep(2.0)
    if not port_free():
        raise RuntimeError(
            "port %d is still held after the kill (owner pid %s) - a Maya "
            "leaked; kill it by hand before the next run" % (PORT, _port_owner())
        )


def main() -> int:
    if not os.path.isfile(MAYA_EXE):
        print("maya.exe not found at %s (set MAYA_EXE)" % MAYA_EXE)
        return 2
    if not port_free():
        print("port %d is already taken; this gate owns its own Maya. "
              "Stop the listener or choose another MAYA_MCP_PORT." % PORT)
        return 2

    working = version.package_digest(os.path.join(REPO, "maya_plugin"))
    working_commit = version.git_stamp(REPO)["commit"]

    # ---- A: a session running "the old build" ------------------------------
    print("phase A: deploy, tamper the deployed copy, launch")
    deploy()
    tamper()
    maya = launch_maya()
    live_pid = None
    try:
        conn, pong = wait_for_ping(maya.pid)
        live_pid = (pong.get("process") or {}).get("pid")
        plugin = pong.get("plugin") or {}
        print("  maya pid %d, loaded %s" % (maya.pid, str(plugin.get("loaded_digest"))[:12]))

        # ---- B: plain stale, as before -------------------------------------
        check("B0 the session imported the DEPLOYED copy, not the repo",
              os.path.normcase(os.path.normpath(plugin.get("package_dir") or ""))
              == os.path.normcase(os.path.normpath(DEPLOYED)),
              "loaded from %s - a repo-cwd launch bypasses the deploy entirely"
              % plugin.get("package_dir"))
        check("B1 ping reports the LOADED identity",
              bool(plugin.get("loaded_digest")), sorted(plugin))
        check("B2 loaded == disk before the redeploy",
              plugin.get("loaded_digest") == plugin.get("digest")
              and plugin.get("restart_required") is False)
        warning = version.compare(plugin, working, working_commit=working_commit)
        check("B3 a tampered deploy is STALE against the tree",
              warning is not None and "NOT running this working tree" in (warning or ""),
              (warning or "silence").splitlines()[2] if warning else "CLEAN")

        # ---- C: the #604 window --------------------------------------------
        print("phase C: redeploy clean, session NOT restarted")
        deploy()
        pong = conn.request("ping", {}, timeout_s=10.0)
        plugin = pong.get("plugin") or {}

        check("C1 the old disk-judging handshake WOULD have read clean here",
              plugin.get("digest") == working,
              "disk %s vs working %s" % (str(plugin.get("digest"))[:12], str(working)[:12]))
        check("C2 the session still answers with the tampered code",
              plugin.get("loaded_digest") != working)
        check("C3 ping itself flags the restart",
              plugin.get("restart_required") is True)
        warning = version.compare(plugin, working, working_commit=working_commit)
        check("C4 compare says NOT RESTARTED instead of clean",
              warning is not None and "NOT restarted" in (warning or ""),
              (warning or "CLEAN - the #604 bug").splitlines()[2] if warning else "CLEAN - the #604 bug")
        check("C5 and the advice is restart, not another redeploy",
              warning is not None and "RESTART" in warning and "redeploy" not in warning)
    finally:
        kill_maya(maya, live_pid)

    # ---- D: restart clears it ----------------------------------------------
    print("phase D: restart against the clean deploy")
    maya = launch_maya()
    live_pid = None
    try:
        conn, pong = wait_for_ping(maya.pid)
        live_pid = (pong.get("process") or {}).get("pid")
        plugin = pong.get("plugin") or {}
        check("D1 after the restart the session runs the tree",
              plugin.get("loaded_digest") == working
              and plugin.get("restart_required") is False)
        check("D2 compare is silent",
              version.compare(plugin, working, working_commit=working_commit) is None)
    finally:
        kill_maya(maya, live_pid)

    print("\n%d checks, %d failures" % (checks, len(failures)))
    for name in failures:
        print("  FAILED: %s" % name)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
