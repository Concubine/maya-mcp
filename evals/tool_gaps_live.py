"""Live gate for the six tool-gap items (#598), against a real Maya.

Everything new here was built against fakes, and a fake agreeing with its
handler is exactly what has hidden live-only bugs in this repo three times
(#584's isolate, #587's mirror reparenting, uv_atlas's boundingBoxComponent2d).
Four of these items are made ENTIRELY of live-only behaviour:

  * assign_pbr encodes two traps that only Maya enforces (bumpValue is a single
    float; colour rules re-apply sRGB)
  * assemble bakes a flare whose bounds live in the handle's local space
  * setup_lighting now builds an Arnold node this repo has never created
  * render_sheet drives real renders

So each is re-asked of real Maya and reported as a MEASURED number.

Handlers are imported and called INSIDE Maya rather than dispatched over the
wire, because the running plugin registered its command table when it loaded and
does not know about commands added since. Registration is covered headless.

Run:  set MAYA_MCP_PORT=9878 && .venv/Scripts/python.exe evals/tool_gaps_live.py
"""

from __future__ import annotations

import base64
import os
import struct
import sys
import zlib

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from live_call import call, staleness_warning, structured_result  # noqa: E402

CHECKS = []


def check(label, passed, detail=""):
    CHECKS.append((passed, label))
    print("%-5s %-58s %s" % ("PASS" if passed else "FAIL", label, detail))


def ok_resp(resp, what):
    if resp.get("status") != "ok":
        print("FAILED %s: %s" % (what, str(resp.get("error", resp))[:400]))
        sys.exit(1)
    return resp["result"]


def run(code, what, timeout=900.0):
    out = ok_resp(call("execute_python", {"code": code}, timeout), what)
    if out.get("traceback"):
        print("PYTHON FAILED (%s):\n%s" % (what, out["traceback"][:2500]))
        sys.exit(1)
    return structured_result(out, what) if out.get("result_repr") else None


def write_png(path, rgb, size=8):
    """A tiny solid PNG, written without Pillow so this gate has no new dep.

    The maps only have to EXIST and be readable - assign_pbr refuses missing
    files, and what is asserted afterwards is the shading network, not pixels.
    """
    raw = b"".join(
        b"\x00" + bytes(rgb) * size for _ in range(size)
    )

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(
            ">I", zlib.crc32(body) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw))
           + chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(png)
    return path.replace("\\", "/")


# > RELOAD HAZARD, learned here the hard way <
#
# importlib.reload REPLACES a module's globals in place. The running dispatcher
# holds the FUNCTION OBJECT it registered at load time, and that object's body
# executes against those same globals - so reloading a module the dispatcher is
# still dispatching swaps the helpers out from under a live handler. Reloading
# code_exec made every subsequent execute_python return tuples where strings
# were expected, because the old body called the new _cap.
#
# Hence two rules below: modules the dispatcher is NOT running are reloaded
# freely; code_exec is loaded under a separate name instead; and the prelude
# re-binds execute_python to whatever the module currently holds, so the session
# is self-healing rather than needing a Maya restart.
PRELUDE = r'''
import importlib
import maya.cmds as cmds
from maya_plugin import version as _version
from maya_plugin.handlers import (assemble as _assemble, combine as _combine,
                                  lighting as _lighting, material as _material,
                                  modeling as _modeling, pbr as _pbr,
                                  render as _render, uvatlas as _uvatlas,
                                  uvmath as _uvmath)
for _m in (_version, _uvmath, _uvatlas, _combine, _modeling, _material,
           _lighting, _pbr, _assemble, _render):
    importlib.reload(_m)
try:
    from maya_plugin import maya_mcp_plugin as _plugin
    from maya_plugin.handlers import code_exec as _live_code_exec
    _plugin._active_server._dispatcher._handlers["execute_python"] = (
        _live_code_exec.execute_python)
except Exception:
    pass
# maya-mcp #634: "cm" is the authoring convention (1 unit = 1 m in the exported
# file). Displayed measurements are unchanged; what changes is that this eval no
# longer leaves the session in a unit that silently rescales the next build.
# Was "m".
cmds.currentUnit(linear="cm")
'''


# Reload code_exec and rebind it in ONE call whose own result is discarded: the
# reload swaps the globals the call's own body is running against, so its result
# packaging may come back malformed. Every later call gets the new handler.
BOOTSTRAP = r'''
import importlib
from maya_plugin import maya_mcp_plugin as _plugin
from maya_plugin.handlers import code_exec as _code_exec
importlib.reload(_code_exec)
_plugin._active_server._dispatcher._handlers["execute_python"] = (
    _code_exec.execute_python)
'''
ok_resp(call("execute_python", {"code": BOOTSTRAP}, 60.0), "bootstrap")


# --------------------------------------------------------------- item 1
print("\n=== item 1: deployed-plugin staleness handshake ===")

warning = staleness_warning()
check("staleness_warning answers without raising", warning is None or bool(warning),
      "silent" if warning is None else "warned")
if warning:
    print(warning)

digest = run(PRELUDE + r'''
info = _version.plugin_info()
{"package_dir": info["package_dir"], "digest": (info["digest"] or "")[:12],
 "stamped": info["stamp"] is not None,
 "commit": ((info["stamp"] or {}).get("commit") or "")[:12]}
''', "plugin_info in the live Maya")
check("the live Maya reports a package digest", bool(digest["digest"]), digest["digest"])
check("the deployed copy carries an install stamp", digest["stamped"],
      digest["commit"])
check("it is the DEPLOYED package, not the repo",
      "Documents" in digest["package_dir"] or "scripts" in digest["package_dir"],
      digest["package_dir"])


# --------------------------------------------------------------- item 3
print("\n=== item 3: execute_python truncation is flagged ===")

# Called in-process rather than over the wire so the numbers are the handler's
# own, not the dispatcher's copy of them - though after BOOTSTRAP above the wire
# would answer the same way.
TRUNCATION = PRELUDE + r'''
from maya_plugin.handlers import code_exec as _code_exec
big = _code_exec.execute_python(
    {"code": "[{'name': 'c%04d' % i, 'tris': 48} for i in range(2034)]"})
huge = _code_exec.execute_python({"code": "'B' * 400000"})
{"big_truncated": big["result_truncated"], "big_bytes": big["result_bytes"],
 "big_parses": len(eval(big["result_repr"])) if not big["result_truncated"] else -1,
 "huge_truncated": huge["result_truncated"], "huge_bytes": huge["result_bytes"],
 "cap": _code_exec.RESULT_REPR_CAP}
'''

t = run(TRUNCATION, "truncation flags")
check("a 2,034-row measurement survives the cap", t["big_truncated"] is False,
      "%d bytes of %d" % (t["big_bytes"], t["cap"]))
check("and it still parses as Python", t["big_parses"] == 2034,
      str(t["big_parses"]))
check("a genuinely oversize result is FLAGGED, not silently cut",
      t["huge_truncated"] is True, "%d bytes" % t["huge_bytes"])


# --------------------------------------------------------------- item 4
print("\n=== item 4: assemble - build, taper, pack, unite ===")

ASSEMBLE = PRELUDE + r'''
cmds.file(new=True, force=True)
# AFTER the new scene, not before: file(new=True) resets the linear unit, so a
# unit set in the prelude is silently discarded and the whole gate would measure
# in the user's preference while believing it set its own. This same ordering
# fact is why new_scene sets the unit after file(new=True) - maya-mcp #634.
cmds.currentUnit(linear="cm")
parts = []
for i in range(4):
    parts.append({"pos": [i * 4.0, 1.5, 0.0], "dim": [3.0, 3.0, 3.0],
                  "patch": i, "chunk": "gate_chunk_a" if i < 2 else "gate_chunk_b"})
# one tapered part, 8 m tall, so a wrong-sized flare handle is unmistakable
parts.append({"pos": [20.0, 4.0, 0.0], "dim": [3.0, 8.0, 3.0],
              "taper": 0.4, "patch": 5, "chunk": "gate_taper"})

out = _assemble.assemble({
    "name": "gate", "parts": parts,
    "atlas": {"cols": 4, "rows": 4, "world_scale": 3.0, "margin": 0.01},
})

# What survived the build: deformers and their handles must not have.
leftovers = [n for n in (cmds.ls(type="nonLinear") or [])]
handles = [n for n in (cmds.ls("*flare*", long=True) or [])]

# Did the taper actually change the shape? Compare the top slab's width to the
# bottom's, on the tapered part.
taper_node = [o["name"] for o in out["objects"] if "taper" in o["name"]][0]
verts = cmds.xform(taper_node + ".vtx[*]", query=True, worldSpace=True,
                   translation=True)
pts = [verts[i:i + 3] for i in range(0, len(verts), 3)]
top_y = max(p[1] for p in pts)
bot_y = min(p[1] for p in pts)
top_w = max(p[0] for p in pts if p[1] > top_y - 0.01) - \
        min(p[0] for p in pts if p[1] > top_y - 0.01)
bot_w = max(p[0] for p in pts if p[1] < bot_y + 0.01) - \
        min(p[0] for p in pts if p[1] < bot_y + 0.01)

uvs = {}
for o in out["objects"]:
    shape = cmds.listRelatives(o["name"], shapes=True, fullPath=True)[0]
    bb = cmds.polyEvaluate(shape, boundingBox2d=True)
    uvs[o["name"]] = [round(float(bb[0][0]), 4), round(float(bb[1][0]), 4),
                      round(float(bb[0][1]), 4), round(float(bb[1][1]), 4)]

bb = cmds.exactWorldBoundingBox("gate_chunk_a")
{"unit": cmds.currentUnit(query=True, linear=True),
 "chunk_a_size": [round(bb[i + 3] - bb[i], 4) for i in range(3)],
 "objects": [(o["name"], o["parts"], o["tris"], o["shells"]) for o in out["objects"]],
 "parts": out["parts"], "outside_patch": out["outside_patch"],
 "deformers": leftovers, "handles": handles,
 "top_w": round(top_w, 4), "bot_w": round(bot_w, 4),
 "uv_bounds": uvs, "warnings": out["warnings"]}
'''

a = run(ASSEMBLE, "assemble")
names = [o[0] for o in a["objects"]]
# The size the caller ASKED for, measured in the scene's own unit. A size flag
# is read in the current linear unit and an omitted one is not, so cube and
# plane used to come out 100x small in a metres scene - a defect this gate
# found and no fake could.
check("parts really measure their declared dim",
      abs(a["chunk_a_size"][1] - 3.0) < 0.01 and abs(a["chunk_a_size"][0] - 7.0) < 0.01,
      "%s %s (asked 7 x 3 x 3)" % (a["chunk_a_size"], a["unit"]))
check("one object per chunk, in the caller's order",
      [n.split("|")[-1] for n in names] == ["gate_chunk_a", "gate_chunk_b", "gate_taper"],
      str([n.split("|")[-1] for n in names]))
check("united objects keep one shell per part",
      [o[3] for o in a["objects"]] == [2, 2, 1], str([o[3] for o in a["objects"]]))
check("no deformer survived the bake", a["deformers"] == [], str(a["deformers"]))
check("no flare handle was left in the scene", a["handles"] == [], str(a["handles"]))
check("the taper actually narrowed the top",
      a["top_w"] < a["bot_w"] * 0.6,
      "top %.3f m vs bottom %.3f m (asked 0.4)" % (a["top_w"], a["bot_w"]))
check("every part's UVs landed inside its patch", a["outside_patch"] == 0,
      "%d outside" % a["outside_patch"])
inside = all(0.0 <= v <= 1.0 for b in a["uv_bounds"].values() for v in b)
check("UVs are inside the 0..1 atlas square", inside, str(a["uv_bounds"]))


# --------------------------------------------------------------- item 2
print("\n=== item 2: assign_pbr - the three-map stack ===")

maps_dir = os.path.join(_HERE, "_tool_gaps_maps")
os.makedirs(maps_dir, exist_ok=True)
albedo = write_png(os.path.join(maps_dir, "albedo.png"), (180, 120, 90))
normal = write_png(os.path.join(maps_dir, "normal.png"), (128, 128, 255))
mask = write_png(os.path.join(maps_dir, "mask.png"), (255, 60, 0))

PBR = PRELUDE + r'''
out = _pbr.assign_pbr({
    "mesh": MESHES, "name": "gate_kit_mat",
    "maps": {"color": ALBEDO,
             "normal": NORMAL,
             "metalness": {"path": MASK, "channel": "r"},
             "roughness": {"path": MASK, "channel": "g", "invert": True}},
    "params": {"base": 1.0},
})
mat = out["material"]
def src(plug):
    conns = cmds.listConnections(plug, source=True, plugs=True) or []
    return conns[0] if conns else None

bump = src(mat + ".normalCamera")
into_bump = src(bump.split(".")[0] + ".bumpValue") if bump else None
nrm_node = out["maps"]["normal"]["file"]
msk_node = out["maps"]["metalness"]["file"]

{"material": mat,
 "baseColor_from": src(mat + ".baseColor"),
 "metalness_from": src(mat + ".metalness"),
 "roughness_from": src(mat + ".specularRoughness"),
 "normal_from": bump,
 "into_bumpValue": into_bump,
 "bumpInterp": cmds.getAttr(bump.split(".")[0] + ".bumpInterp") if bump else None,
 "normal_colorspace": cmds.getAttr(nrm_node + ".colorSpace"),
 "normal_ignores_rules": cmds.getAttr(nrm_node + ".ignoreColorSpaceFileRules"),
 "mask_colorspace": cmds.getAttr(msk_node + ".colorSpace"),
 "albedo_colorspace": cmds.getAttr(out["maps"]["color"]["file"] + ".colorSpace"),
 "shared_mask": out["maps"]["metalness"]["file"] == out["maps"]["roughness"]["file"],
 "file_nodes": len([n for n in (cmds.ls(type="file") or []) if "gate_kit_mat" in n]),
 # Membership lives on the SHAPE, never the transform - asking the transform
 # returns None and reads as "no material", which is how this check first
 # failed against a perfectly correct assignment.
 "shading_groups": sorted(set(
     sg for m in MESHES
     for shp in (cmds.listRelatives(m, shapes=True, fullPath=True) or [])
     for sg in (cmds.listSets(object=shp, type=1) or []))),
 "base": cmds.getAttr(mat + ".base"),
 "warnings": out["warnings"]}
'''.replace("MESHES", repr(names[:2])).replace("ALBEDO", repr(albedo)) \
   .replace("NORMAL", repr(normal)).replace("MASK", repr(mask))

p = run(PBR, "assign_pbr")
check("albedo drives baseColor", (p["baseColor_from"] or "").endswith(".outColor"),
      str(p["baseColor_from"]))
check("metalness reads one CHANNEL of the mask",
      (p["metalness_from"] or "").endswith(".outColorR"), str(p["metalness_from"]))
check("smoothness is inverted into roughness",
      (p["roughness_from"] or "").endswith(".outputX"), str(p["roughness_from"]))
check("TRAP 1: bumpValue is fed outAlpha, not outColor",
      (p["into_bumpValue"] or "").endswith(".outAlpha"), str(p["into_bumpValue"]))
check("bumpInterp = 1 (tangent-space normal map)", p["bumpInterp"] == 1,
      str(p["bumpInterp"]))
check("TRAP 2: normal map is read Raw", p["normal_colorspace"] == "Raw",
      str(p["normal_colorspace"]))
check("TRAP 2: and pinned against colour rules",
      p["normal_ignores_rules"] is True, str(p["normal_ignores_rules"]))
check("mask is read Raw too", p["mask_colorspace"] == "Raw", str(p["mask_colorspace"]))
check("albedo is left as colour", p["albedo_colorspace"] != "Raw",
      str(p["albedo_colorspace"]))
check("one file node serves both mask channels", p["shared_mask"] is True)
check("three file nodes for four maps", p["file_nodes"] == 3,
      "%d nodes" % p["file_nodes"])
check("both meshes share ONE shading group", len(p["shading_groups"]) == 1,
      str(p["shading_groups"]))
check("scalar params still land", abs(p["base"] - 1.0) < 1e-6, str(p["base"]))


# --------------------------------------------------------------- item 6
print("\n=== item 6: environment dome, so a metal is not black ===")

DOME = PRELUDE + r'''
out = _lighting.setup_lighting({"preset": "environment", "intensity": 1.0})
domes = cmds.ls(type="aiSkyDomeLight", long=True) or []
shape = domes[0] if domes else None
lit = _lighting.light_shapes(cmds)
{"lights": out["lights"], "warnings": out["warnings"],
 "dome_shapes": domes,
 "format": cmds.getAttr(shape + ".format") if shape else None,
 "colour_from": (cmds.listConnections(shape + ".color", source=True) or [None])[0]
                if shape else None,
 "light_shapes_sees_it": bool(shape and shape in lit),
 "render_sees_a_lit_scene": _render._scene_has_light(cmds),
 "relight_set": sorted(_render._rig_lights(cmds).keys())}
'''

d = run(DOME, "environment dome")
check("an aiSkyDomeLight really exists", bool(d["dome_shapes"]),
      str(d["dome_shapes"]))
check("no fallback warning (Arnold was available)", d["warnings"] == [],
      str(d["warnings"]))
check("dome is mapped latlong", d["format"] == 2, str(d["format"]))
check("its colour is driven by the horizon ramp",
      "Ramp" in str(d["colour_from"]) or "ramp" in str(d["colour_from"]),
      str(d["colour_from"]))
check("light_shapes() finds an Arnold light", d["light_shapes_sees_it"] is True)
check("a dome-lit scene does NOT read as unlit",
      d["render_sees_a_lit_scene"] is True,
      "otherwise render_scene throws a fallback key on top of it")
check("the dome is excluded from camera relighting", d["relight_set"] == [],
      str(d["relight_set"]))


# --------------------------------------------------------------- item 5
print("\n=== item 5: render_sheet - one call, N cells ===")

SHEET = PRELUDE + r'''
subjects = SUBJECTS
before = set(cmds.ls(long=True) or [])
out = _render.render_sheet({"subjects": subjects, "renderer": "hw2",
                            "resolution": 128, "samples": 1})
after = set(cmds.ls(long=True) or [])
{"labels": [i["label"] for i in out["images"]],
 "png_b64": [i["png_b64"] for i in out["images"]],
 "leaked_nodes": sorted(n for n in (after - before)),
 "visible_after": all(
     cmds.getAttr(s + ".visibility") for s in (cmds.ls(geometry=True, long=True) or [])),
 "renderer_restored": cmds.getAttr("defaultRenderGlobals.currentRenderer")}
'''.replace("SUBJECTS", repr(names))

s = run(SHEET, "render_sheet", timeout=900.0)
check("one cell per subject, labelled", s["labels"] == names, str(s["labels"]))
# A cell of nothing is a valid PNG, so byte count proves nothing: measure the
# pixels, exactly as the MCP tool does before it composites them.
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))
from maya_mcp import images as _images  # noqa: E402

stats = [_images.pixel_stats(base64.b64decode(b64)) for b64 in s["png_b64"]]
check("every cell has a subject in it (not a blank render)",
      all(not st["blank"] for st in stats),
      str([st["opaque_px"] for st in stats]))
check("the sheet left no nodes behind", s["leaked_nodes"] == [],
      str(s["leaked_nodes"]))
check("every object is visible again", s["visible_after"] is True)
check("the user's renderer setting was restored",
      s["renderer_restored"] not in (None, ""), str(s["renderer_restored"]))


# --------------------------------------------------------------- verdict
failed = [label for passed, label in CHECKS if not passed]
print("\n%d checks, %d failed" % (len(CHECKS), len(failed)))
for label in failed:
    print("  FAILED: %s" % label)
sys.exit(1 if failed else 0)
