"""#818: which commands, and which value-selected routes inside them, has NO
live gate ever sent to a real Maya. Read-only - greps evals/*.py against the
plugin's command registry and the handlers' route enumerations. Re-run after
adding a gate; the table in docs/superpowers/plans/2026-09-04-818-live-
coverage-audit.md is this script's output, ranked by hand.

Run:  python evals/live_coverage_audit.py
"""
from __future__ import annotations

import glob
import json
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
SWEEP_GATES = {"param_sweep_live.py", "inert_branches_live.py", "static_write_guard_live.py"}


def commands():
    reg = open(os.path.join(REPO, "maya_plugin", "maya_mcp_plugin.py"), encoding="utf-8").read()
    body = reg[reg.index("def _build_handlers"):]
    body = body[:body.index("\n    }\n")]
    return re.findall(r'^\s+"([a-z_]+)":', body, re.M)


def eval_texts():
    files = [f for f in glob.glob(os.path.join(_HERE, "*.py"))
             if not f.endswith(("live_call.py", "live_coverage_audit.py"))]
    return {os.path.basename(f): open(f, encoding="utf-8", errors="replace").read() for f in files}


def const(mod, name):
    """The string values of a module-level tuple/dict/set constant."""
    src = open(os.path.join(REPO, "maya_plugin", "handlers", mod + ".py"), encoding="utf-8").read()
    m = re.search(r"^%s\s*=\s*(\(|\{|\[)" % name, src, re.M)
    start = m.end() - 1
    depth = 0
    for i in range(start, len(src)):
        if src[i] in "([{":
            depth += 1
        elif src[i] in ")]}":
            depth -= 1
            if depth == 0:
                return sorted(set(re.findall(r'"([A-Za-z_]+)"', src[start:i + 1])))
    raise ValueError(name)


ROUTES = [
    ("create_primitive", "kind", lambda: const("modeling", "PRIMITIVE_KINDS")),
    ("boolean_op", "op", lambda: const("modeling", "BOOLEAN_OPS")),
    ("array", "mode", lambda: const("arraymath", "MODES")),
    ("create_curve_form", "kind", lambda: const("curveform_math", "KINDS")),
    ("setup_lighting", "preset", lambda: const("lighting", "PRESETS")),
    ("bind_skin", "method", lambda: const("rigging", "BIND_METHODS")),
    ("deform", "deformer", lambda: [k for k in const("sculpt", "DEFORMER_WHITELIST")
                                    if k in ("bend", "squash", "twist", "flare", "sine", "wave", "sculpt", "lattice")]),
    ("sculpt_ops", "op", lambda: const("sculpt", "VERTEX_OPS")),
    ("apply_surface_detail", "effect", lambda: const("surfdetail", "EFFECT_KINDS")),
    ("apply_texture_recipe", "recipe", lambda: const("texture_recipes", "RECIPES")),
    ("uv_atlas", "project", lambda: const("uvatlas", "PROJECTIONS")),
    ("render_scene", "renderer", lambda: const("render", "VALID_RENDERERS")),
    ("capture_viewport", "shading", lambda: const("capture", "VALID_SHADING")),
    ("capture_viewport", "buffer", lambda: const("capture", "VALID_BUFFERS")),
    ("capture_viewport", "lighting", lambda: const("capture", "VALID_LIGHTING")),
    ("capture_viewport", "angle", lambda: const("capture", "VALID_ANGLES")),
    ("combine/assemble", "pivot", lambda: const("combine", "PIVOT_MODES")),
    ("retarget_clip", "file ext", lambda: [".bvh", ".fbx"]),
    ("export_fbx", "flag", lambda: ["include_skins", "include_animation", "require_baked_textures", "nodes"]),
]


def main():
    texts = eval_texts()
    gates = {n: t for n, t in texts.items() if n.endswith("_live.py")}
    cmds = commands()
    coverage = {}
    for c in cmds:
        pat = re.compile(r'\(\s*["\']%s["\']' % re.escape(c))
        callers = sorted(n for n, t in texts.items() if pat.search(t))
        coverage[c] = {"gates": [n for n in callers if n in gates],
                       "probes": [n for n in callers if n not in gates and "probe" in n],
                       "other": [n for n in callers if n not in gates and "probe" not in n]}
    print("%d commands, %d eval scripts (%d gates)\n" % (len(cmds), len(texts), len(gates)))
    never = [c for c, d in coverage.items() if not (d["gates"] or d["probes"] or d["other"])]
    sweep_only = [c for c, d in coverage.items() if d["gates"] and set(d["gates"]) <= SWEEP_GATES]
    print("NO live caller at all (%d): %s" % (len(never), ", ".join(never)))
    print("only reached by refusal sweeps, never functionally (%d): %s\n" % (len(sweep_only), ", ".join(sweep_only)))
    print("%-22s %-9s %-40s %s" % ("command", "param", "never sent by a gate", "probe/run only"))
    routes = {}
    for cmd, param, values in ROUTES:
        missing, probe_only = [], []
        for v in values():
            pat = (re.compile(re.escape(v)) if v.startswith(".")
                   else re.compile(r'["\']%s["\']' % re.escape(v)))
            in_gate = any(pat.search(t) for t in gates.values())
            in_any = any(pat.search(t) for t in texts.values())
            if not in_gate:
                (probe_only if in_any else missing).append(v)
        routes["%s.%s" % (cmd, param)] = {"never": missing, "probe_only": probe_only}
        print("%-22s %-9s %-40s %s" % (cmd, param, ", ".join(missing) or "-", ", ".join(probe_only)))
    with open(os.path.join(_HERE, "live_coverage_818.json"), "w", encoding="utf-8") as fh:
        json.dump({"commands": coverage, "routes": routes, "never_called": never,
                   "sweep_only": sweep_only}, fh, indent=1)


if __name__ == "__main__":
    main()
