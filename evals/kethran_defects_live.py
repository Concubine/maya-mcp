"""Live gate for the six defects split out of redmine #838 (862-868).

Each was measured before it was touched (evals/capture_state_probe_864,
evals/bake_stats_probe_866, evals/listener_probe_863). What this pins:

  1  session_info (#862): the wrapper's maya_session_info answers the pid
     this run was pinned to, the port, the scene, its modified flag and
     the cwd, without touching the scene
  2  the handshake (#862): a fresh MayaConnection knows the plugin's pid
     before any request of its own
  3  the listener (#863): 100 connect-and-reset clients, garbage, and held
     connections leave the plugin answering
  4  combine (#867): inputs under one group -> the result lives there and
     reports it; inputs from two groups -> names[0]'s, and the other group
     is named; root-level inputs stay at the root without a word; the
     result's world-space vertices are where the inputs' were
  5  bake stats (#866), through the WRAPPER: a curvature map of a torus
     reports an exact distinct_values in the dozens and distinct_values_seen
     of 2; the file agrees with PIL to the pixel
  6  curvature radius (#868): the default on a 380-unit torus is 2% of its
     diagonal and the map carries more values than the old absolute did;
     an explicit 0.1 warns and bakes the flat map it warned about
  7  a capture of a normal scene reports no camera move and no on-screen
     frame (#864 / #865: the guards stay quiet when nothing is wrong)

Defaults to port 9878 and refuses 9877 unless MAYA_MCP_ALLOW_USER_SESSION=1
(it replaces the scene). Run:  .venv/Scripts/python.exe evals/kethran_defects_live.py
Exit: 0 pass, 1 fail, 2 no connection.
"""

from __future__ import annotations

import asyncio
import ast
import json
import os
import socket
import struct
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image  # noqa: E402

from live_call import DEFAULT_PORT, call  # noqa: E402

PORT = DEFAULT_PORT
results: list = []


def send(command: str, params: dict, timeout_s: float = 120.0) -> dict:
    try:
        return call(command, params, timeout_s=timeout_s, port=PORT)
    except (ConnectionRefusedError, OSError) as exc:
        print("could not reach a Maya plugin on %s: %s" % (PORT, exc))
        sys.exit(2)


def ok(command: str, params: dict, timeout_s: float = 120.0) -> dict:
    response = send(command, params, timeout_s)
    if response.get("status") != "ok":
        print("FAIL: %s: %s" % (command, json.dumps(response.get("error"))[:400]))
        sys.exit(1)
    return response.get("result") or {}


def py(code: str):
    result = ok("execute_python", {"code": code})
    if result.get("traceback"):
        print("FAIL: execute_python raised:\n%s" % result["traceback"])
        sys.exit(1)
    rep = result.get("result_repr")
    try:
        return ast.literal_eval(rep) if rep is not None else None
    except Exception:
        return rep


def check(label: str, passed: bool, detail: str) -> None:
    print("%s %s: %s" % ("PASS" if passed else "FAIL", label, detail))
    results.append((label, passed))


def new_scene() -> None:
    ok("new_scene", {"confirm": True})


def wrapper():
    from maya_mcp import server as server_mod  # noqa: PLC0415
    from maya_mcp.connection import MayaConnection  # noqa: PLC0415

    conn = MayaConnection(port=PORT)
    return server_mod.create_server(conn), conn


def tool(mcp, name: str, args: dict):
    result = asyncio.run(mcp.call_tool(name, args))
    texts = [c.text for c in result.content if getattr(c, "type", None) == "text"]
    if result.is_error:
        print("FAIL: %s: %s" % (name, texts))
        sys.exit(1)
    return result.structured_content, "\n".join(texts)


def rst_clients(n: int) -> int:
    sent = 0
    for _ in range(n):
        s = socket.socket()
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            s.connect(("127.0.0.1", PORT))
            s.close()
            sent += 1
        except OSError:
            s.close()
            break
    return sent


def measure(path: str) -> dict:
    img = Image.open(path)
    img.load()
    rgb = img.convert("RGB")
    return {"distinct": len(rgb.getcolors(maxcolors=rgb.width * rgb.height) or []),
            "luma": len([1 for h in rgb.convert("L").histogram() if h])}


def main() -> None:
    if PORT == 9877 and os.environ.get("MAYA_MCP_ALLOW_USER_SESSION") != "1":
        print("refusing to run on 9877: this eval replaces the scene. "
              "Set MAYA_MCP_ALLOW_USER_SESSION=1 to override.")
        sys.exit(2)
    ping = ok("ping", {})
    pid = ping["process"]["pid"]
    expected = os.environ.get("MAYA_MCP_EXPECT_PID")
    mcp, conn = wrapper()
    out_dir = tempfile.mkdtemp(prefix="g838_")

    # 1-2: who answers
    new_scene()
    info, _ = tool(mcp, "maya_session_info", {})
    check("1 session_info names the process, the port, the scene and the cwd",
          info["pid"] == pid and (expected is None or info["pid"] == int(expected))
          and info["port"] == PORT and info["scene"] == "" and info["scene_modified"] is False
          and info["cwd"] and os.path.isdir(info["cwd"]),
          json.dumps({k: info[k] for k in ("pid", "port", "scene", "scene_modified", "cwd", "uptime_s")}))
    py("import maya.cmds as cmds\ncmds.polyCube(name='g838_dirty')\n")
    info, _ = tool(mcp, "maya_session_info", {})
    check("1b the modified flag follows the scene", info["scene_modified"] is True,
          "scene_modified %r after a polyCube" % info["scene_modified"])
    check("2 a fresh connection learned the pid from its handshake before any request",
          conn.last_pid == pid, "last_pid %r vs ping pid %r" % (conn.last_pid, pid))

    # 3: the listener
    sent = rst_clients(100)
    s = socket.socket()
    s.connect(("127.0.0.1", PORT))
    s.sendall(b"\xff\xff\xff\xff garbage\n")
    s.close()
    time.sleep(0.5)
    alive = send("ping", {}).get("status") == "ok"
    check("3 the listener outlives 100 reset clients and a garbage frame",
          sent == 100 and alive, "resets %d alive %s" % (sent, alive))

    # 4: combine carries the parent
    new_scene()
    py("import maya.cmds as cmds\n"
       "g = cmds.group(empty=True, name='g838_grp'); cmds.xform(g, ws=True, t=(10, 0, 0), s=(2, 2, 2))\n"
       "h = cmds.group(empty=True, name='g838_other')\n"
       "for i, (name, parent) in enumerate((('g838_a', g), ('g838_b', g), ('g838_c', h), ('g838_r1', None), ('g838_r2', None))):\n"
       "    c = cmds.polyCube(name=name, w=2, h=2, d=2, ch=False)[0]\n"
       "    cmds.xform(c, ws=True, t=(i * 5, 3, 0))\n"
       "    if parent: cmds.parent(c, parent)\n")
    before = py("import maya.cmds as cmds\n"
                "sorted(tuple(round(v, 3) for v in cmds.pointPosition(vtx, world=True)) for n in ('g838_a', 'g838_b') "
                "for vtx in cmds.ls(n + '.vtx[*]', flatten=True))\n")
    out = ok("combine", {"names": ["|g838_grp|g838_a", "|g838_grp|g838_b"], "name": "ab"})
    after = py("import maya.cmds as cmds\n"
               "sorted(tuple(round(v, 3) for v in cmds.pointPosition(vtx, world=True)) for vtx in cmds.ls('ab.vtx[*]', flatten=True))\n")
    check("4a inputs under one group leave the result there, and the world geometry stays put",
          out["name"] == "|g838_grp|ab" and out["parent"] == "|g838_grp" and before == after
          and not [w for w in out["warnings"] if "parent" in w],
          "name %s parent %s verts equal %s warnings %s" % (out["name"], out["parent"], before == after, out["warnings"]))
    out = ok("combine", {"names": ["|g838_other|g838_c", "|g838_r1"], "name": "cr"})
    note = [w for w in out["warnings"] if "parent" in w]
    check("4b inputs from two parents carry names[0]'s and name the other",
          out["parent"] == "|g838_other" and len(note) == 1 and "the root" in note[0],
          "parent %s warnings %s" % (out["parent"], json.dumps(out["warnings"])))
    py("import maya.cmds as cmds\ncmds.polyCube(name='g838_r3', ch=False)\n")
    out = ok("combine", {"names": ["|g838_r2", "|g838_r3"], "name": "rr"})
    check("4c root-level inputs stay at the root without a word",
          out["name"] == "|rr" and out["parent"] is None and not [w for w in out["warnings"] if "parent" in w],
          "name %s parent %r warnings %s" % (out["name"], out["parent"], out["warnings"]))

    # 5-6: bake stats and the curvature radius, through the wrapper
    new_scene()
    py("import maya.cmds as cmds\n"
       "t = cmds.polyTorus(name='g838_torus', r=8, sr=3, sx=32, sy=16, ch=False)[0]\n"
       "cmds.xform(t, ws=True, s=(12, 12, 12)); cmds.makeIdentity(t, apply=True, t=True, r=True, s=True)\n"
       "cmds.polyAutoProjection(t, lm=0, pb=0, ibd=1, cm=0, l=2, sc=1, o=1, p=6, ps=0.2, ws=0)\n"
       "cmds.delete(t, ch=True)\n")
    baked, _ = tool(mcp, "maya_bake_mesh_maps", {"meshes": ["|g838_torus"], "out_dir": out_dir,
                                                  "maps": ["curvature"], "resolution": 512,
                                                  "timeout_s": 600})
    entry = baked["baked"][0]
    stats = entry["stats"]
    on_disk = measure(entry["file"])
    check("5 the wrapper counts the file exactly and keeps the plugin's scan apart",
          stats["distinct_values"] == on_disk["distinct"] and stats["distinct_values"] > 10
          and stats["distinct_values_seen"] == 2 and stats["luma_stddev"] is not None,
          "stats %s | PIL %s" % (json.dumps(stats), json.dumps(on_disk)))
    diag = entry["bbox_diagonal"]
    check("6a the default radius is 2%% of the mesh's diagonal and says so",
          diag and abs(entry["curvature_radius"] - diag * 0.02) < 1e-3
          and str(entry["curvature_radius_source"]).startswith("default: 2%")
          and not [w for w in baked.get("warnings", []) if "curvature_radius" in w],
          "radius %s source %r diagonal %s" % (entry["curvature_radius"], entry["curvature_radius_source"], diag))
    rich = stats["distinct_values"]
    baked, _ = tool(mcp, "maya_bake_mesh_maps", {"meshes": ["|g838_torus"], "out_dir": out_dir,
                                                  "maps": ["curvature"], "resolution": 512,
                                                  "curvature_radius": 0.1, "timeout_s": 600})
    entry = baked["baked"][0]
    note = [w for w in baked.get("warnings", []) if "curvature_radius 0.1" in w]
    check("6b an explicit 0.1 on a 380-unit mesh warns, and the map it bakes is the flat one it warned about",
          len(note) == 1 and "0.03%" in note[0] and entry["curvature_radius"] == 0.1
          and entry["curvature_radius_source"] == "given"
          and entry["stats"]["distinct_values"] < 5 < rich,
          "warnings %s | distinct %s (default gave %s)" % (json.dumps(note)[:200], entry["stats"]["distinct_values"], rich))

    # 7: the guards stay quiet on a normal capture
    cap = ok("capture_viewport", {"angles": ["current", "front"], "target": ["|g838_torus"],
                                  "frame_all": False, "resolution": 256})
    quiet = not any("moved during this frame" in w or "ON-SCREEN" in w for w in cap.get("warnings", []))
    check("7 a normal capture reports no camera move and no on-screen frame", quiet,
          "warnings %s" % json.dumps(cap.get("warnings")))

    new_scene()
    failed = [label for label, passed in results if not passed]
    print("\n%d checks, %d failed%s" % (len(results), len(failed),
                                        (": " + ", ".join(failed)) if failed else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
