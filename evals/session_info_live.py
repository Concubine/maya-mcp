"""Live gate for redmine #921: maya_session_info must ANSWER against a real,
installed plugin - the one call whose whole job is to say which Maya you are
talking to.

The defect: a stamp is the install record `version.read_stamp` parsed - a
dict, {"commit", "dirty", "installed_at"} - and the wrapper handed that dict
straight to SessionInfo.plugin_stamp, an Optional[str]. Pydantic refused the
model, so the tool returned a validation error and NOTHING else: no pid, no
port, no scene. The advice every agent is given - "three Mayas on one machine,
call maya_session_info first (#862)" - failed on the session it mattered for.

Why the suite was green through all of it, and why this gate must run LIVE:

  - the unit fake sent `"stamp": "813895d58b50"`, a bare string the plugin has
    never produced (#799 all over again - a fake that accepts what the real
    thing refuses, in reverse);
  - a Maya launched from the repo imports the REPO plugin copy, which install.py
    never stamped. read_stamp returns None there, None validates fine, and every
    agent Maya - 9878, 9879, 9880 - is exactly that case. Only a session running
    an INSTALLED copy carries a stamp, which in practice means the user's own.

So this gate refuses to claim anything from an unstamped session: that is the
configuration that cannot reproduce the defect, and a pass from it would be the
same vacuous green that hid this for as long as it hid.

READ-ONLY: one ping, no scene touched, nothing written. Port 9877 is allowed
deliberately - the user's Maya is normally the only stamped session on the
machine, and a ping costs it nothing.

Run:  .venv/Scripts/python.exe evals/session_info_live.py
      MAYA_MCP_PORT=9877 .venv/Scripts/python.exe evals/session_info_live.py
Exit: 0 pass, 1 fail, 2 environment (no plugin answered / unstamped session).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from live_call import DEFAULT_PORT, call  # noqa: E402

PORT = DEFAULT_PORT
results: list = []


def check(label: str, passed: bool, detail: str = "") -> bool:
    results.append((label, passed))
    print("%s %s%s" % ("PASS" if passed else "FAIL", label,
                       ("  [%s]" % detail) if detail else ""))
    return passed


def ping() -> dict:
    try:
        response = call("ping", {}, timeout_s=10.0, port=PORT)
    except (ConnectionRefusedError, OSError) as exc:
        print("could not reach a Maya plugin on %s: %s" % (PORT, exc))
        sys.exit(2)
    if response.get("status") != "ok":
        print("ping failed: %s" % json.dumps(response)[:400])
        sys.exit(2)
    return response.get("result") or {}


def session_info() -> tuple[bool, str]:
    """(is_error, text) from the real wrapper over a real connection - the
    layer the defect lived in. Anything short of call_tool would skip the
    model validation that was the failure."""
    from maya_mcp import server as server_mod  # noqa: PLC0415
    from maya_mcp.connection import MayaConnection  # noqa: PLC0415

    mcp = server_mod.create_server(MayaConnection(port=PORT))
    result = asyncio.run(mcp.call_tool("maya_session_info", {}))
    texts = [c.text for c in result.content if getattr(c, "type", None) == "text"]
    return bool(result.is_error), "\n".join(texts)


def main() -> None:
    raw = ping()
    plugin = raw.get("plugin") or {}
    process = raw.get("process") or {}

    loaded = plugin.get("loaded_stamp") if plugin.get("loaded_digest") else None
    stamp = loaded or plugin.get("stamp")
    print("port %s  pid %s  package_dir %s" % (PORT, process.get("pid"),
                                               plugin.get("package_dir")))
    print("stamp on the wire: %s" % json.dumps(stamp))

    if not isinstance(stamp, dict) or not stamp.get("commit"):
        print("\nUNSTAMPED session: this plugin copy carries no install record, "
              "which is the one configuration that CANNOT reproduce #921. Point "
              "MAYA_MCP_PORT at a Maya running an installed copy (install.py "
              "--yes, then restart it) and run again.")
        sys.exit(2)

    expected = "%s%s" % (str(stamp["commit"])[:12],
                         "+dirty" if stamp.get("dirty") else "")

    is_error, text = session_info()
    check("1 the tool answers at all against a stamped plugin", not is_error,
          text[:200] if is_error else "")
    if is_error:
        print("\n1 check, 1 failed: 1")
        sys.exit(1)

    info = json.loads(text)
    print("session_info: %s" % json.dumps(
        {k: info.get(k) for k in ("pid", "port", "cwd", "plugin_stamp",
                                  "plugin_restart_required")}))

    check("2 plugin_stamp is a string, not the raw install record",
          isinstance(info.get("plugin_stamp"), str),
          "type %s" % type(info.get("plugin_stamp")).__name__)
    check("3 it names the commit the RUNNING copy was stamped with",
          info.get("plugin_stamp") == expected,
          "%s vs %s" % (info.get("plugin_stamp"), expected))
    check("4 the identity the caller actually asked for survived",
          info.get("pid") == process.get("pid") and info.get("port") == PORT,
          "pid %s port %s" % (info.get("pid"), info.get("port")))
    check("5 the scene answer matches the process the ping described",
          info.get("scene") == process.get("scene"),
          "%r vs %r" % (info.get("scene"), process.get("scene")))

    failed = [label.split()[0] for label, passed in results if not passed]
    print("\n%d checks, %d failed%s" % (len(results), len(failed),
                                        (": " + ", ".join(failed)) if failed else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
