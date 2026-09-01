"""#767/M5 probe: which live deformers actually survive an FBX export?

export.py warns about a live deltaMush because #771 MEASURED that one being
dropped byte-identically. The warning covers deltaMush ONLY, and nothing has
ever measured the others - so a caller with a live bend, a lattice, or a wrap
gets silence and an export that quietly ships the undeformed mesh.

This settles it by measurement rather than by extending the warning on a
guess: build one mesh per deformer kind, deform it, record the deformed vertex
positions, export, reimport into a fresh scene, and compare. A deformer that
travels reproduces its deformed shape; a dropped one comes back at rest.

DESTRUCTIVE: calls new_scene. Port 9878 (agent Maya) per the two-Maya policy.
Run:  $env:MAYA_MCP_PORT='9878'; python evals/deformer_drop_probe.py --build
"""

from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from live_call import call, structured_result  # noqa: E402

OUT_DIR = os.path.join(_HERE, "deformer_drop_probe")

# One representative per deformer family the toolbox can actually create.
# `deform` authors the nonlinears; the rest are made directly so the probe
# measures Maya's export behaviour, not this repo's coverage.
CASES = [
    # The control comes first and carries NO deformer. Absolute vertex
    # positions cannot answer this question - the export declares metres and
    # the reimport rescales everything - so the metric is the shape's own
    # asphericity, and the control is what "no deformation survived" looks
    # like after that same rescaling.
    ("control_none", None, None),
    ("nonlinear_bend", "cmds.nonLinear(m, type='bend')[0]",
     "cmds.setAttr(d + '.curvature', 60)"),
    ("nonlinear_twist", "cmds.nonLinear(m, type='twist')[0]",
     "cmds.setAttr(d + '.startAngle', 90)"),
    ("lattice_ffd", "cmds.lattice(m, divisions=(3, 3, 3), objectCentered=True)[1]",
     "cmds.move(0.6, 0, 0, d + '.pt[0][2][0:2]', relative=True)"),
    ("wire", None, None),          # built by the bespoke block below
    ("delta_mush", "cmds.deltaMush(m)[0]", "cmds.setAttr(d + '.smoothingIterations', 10)"),
]

# Scale-invariant shape signature: every vertex expressed relative to the
# mesh centroid and divided by the RMS radius, so a uniform rescale (which is
# exactly what the FBX round-trip does) cancels and the SHAPE is what remains.
# The first attempt used vertex radii alone and was blind to a twist, which
# rotates vertices about an axis WITHOUT changing their distance from the
# centroid - it reported cv 0.0000 both before and after and would have been
# read as "dropped" when nothing had been deformed in the first place. The
# `moved` figure is what proves a case deformed at all, and a case that did
# not deform is reported as inconclusive rather than as a verdict.
SIGNATURE = (
    "def _sig(mesh):\n"
    "    _p = cmds.xform(mesh + '.vtx[*]', query=True, worldSpace=True,\n"
    "                    translation=True)\n"
    "    _v = [_p[i:i+3] for i in range(0, len(_p), 3)]\n"
    "    _n = float(len(_v))\n"
    "    _c = [sum(a[i] for a in _v) / _n for i in range(3)]\n"
    "    _d = [[a[i] - _c[i] for i in range(3)] for a in _v]\n"
    "    _rms = (sum(x*x + y*y + z*z for x, y, z in _d) / _n) ** 0.5\n"
    "    if _rms < 1e-9:\n"
    "        return {'norm': [], 'rms': 0.0}\n"
    "    return {'norm': [[round(x/_rms, 5), round(y/_rms, 5),\n"
    "                      round(z/_rms, 5)] for x, y, z in _d],\n"
    "            'rms': round(_rms, 5)}\n"
)


DELTA = (
    "def _delta(a, b):\n"
    "    _pa, _pb = a.get('norm') or [], b.get('norm') or []\n"
    "    if not _pa or len(_pa) != len(_pb):\n"
    "        return None\n"
    "    return round(max(sum((x - y) ** 2 for x, y in zip(u, v)) ** 0.5\n"
    "                     for u, v in zip(_pa, _pb)), 6)\n"
)


def run(code, label, timeout_s=300.0):
    res = call("execute_python", {"code": code}, timeout_s=timeout_s)
    if res.get("status") != "ok":
        print("FATAL %s: %r" % (label, res.get("error")))
        sys.exit(1)
    result = res.get("result") or {}
    # execute_python reports a raise INSIDE the code as a successful call
    # carrying a traceback, so a probe that only checks status is blind to
    # its own broken setup.
    if result.get("traceback"):
        print("FATAL %s raised in Maya:\n%s" % (label, result["traceback"]))
        sys.exit(1)
    return structured_result(result, label)


def main():
    if "--build" not in sys.argv:
        print(__doc__)
        return 1
    os.makedirs(OUT_DIR, exist_ok=True)
    fbx = os.path.join(OUT_DIR, "deformers.fbx").replace("\\", "/")

    call("new_scene", {"confirm": True}, timeout_s=180.0)

    # Build every case, deform it, and record the deformed positions. A
    # sphere per case, spaced apart so one export carries them all.
    setup = ["import maya.cmds as cmds", SIGNATURE, DELTA,
             "out = {}", "_rest = {}", "_shapes = {}"]
    for i, (name, make, tweak) in enumerate(CASES):
        # Every case starts from the SAME primitive and records its rest
        # shape first, so "this deformer moved nothing" is a measurement
        # rather than an assumption. A deltaMush needs something rough to
        # relax, so its case gets a displaced cube instead of a sphere -
        # mush on an already-smooth sphere is a no-op and would look
        # exactly like a dropped deformer.
        if name == "delta_mush":
            setup += [
                "m = cmds.polyCube(name='delta_mush_case', w=2, h=2, d=2, "
                "sx=6, sy=6, sz=6)[0]",
                "cmds.move(%d, 0, 0, m)" % (i * 3),
                # Maya component ranges take no step (vtx[0:40:3] raises), so
                # the roughness is applied vertex by vertex - and it must BE
                # rough: a deltaMush has nothing to relax on a smooth surface
                # and would read as a dropped deformer.
                "for _i in range(0, 200, 3):\n"
                "    try:\n"
                "        cmds.move(0.12 * ((_i % 2) * 2 - 1), 0.09, 0,\n"
                "                  m + '.vtx[%d]' % _i, relative=True)\n"
                "    except Exception:\n"
                "        break",
            ]
        else:
            setup += [
                "m = cmds.polySphere(name='%s_case', radius=1, sx=16, sy=16)[0]"
                % name,
                "cmds.move(%d, 0, 0, m)" % (i * 3),
            ]
        setup += ["cmds.refresh()", "_rest['%s'] = _sig(m)" % name]

        if name == "control_none":
            setup += ["d = None"]
        elif name == "wire":
            setup += [
                "_crv = cmds.curve(p=[(%d,-1,0),(%d,0,0),(%d,1,0)], degree=2)"
                % (i * 3, i * 3, i * 3),
                "d = cmds.wire(m, wire=_crv, dropoffDistance=(0, 20))[0]",
                "cmds.move(0.8, 0, 0, _crv + '.cv[1]', relative=True)",
            ]
        else:
            setup += ["d = %s" % make, tweak]
        # The normalised shapes stay in Maya's persistent namespace and only
        # scalars cross the wire: shipping ~500 vertices x 6 cases overflows
        # execute_python's result channel and comes back truncated.
        setup += [
            "cmds.refresh()",
            "_shapes['%s'] = _sig(m)" % name,
            "out['%s'] = {'mesh': m, 'deformer': str(d), "
            "'deformed_by': _delta(_rest['%s'], _shapes['%s'])}"
            % (name, name, name),
        ]
    setup.append("out")
    built = run("\n".join(setup), "build deformed cases")

    print("\nbuilt %d cases" % len(built))

    # Export everything, then reimport into a fresh scene and re-measure.
    exp = call("export_fbx", {
        "path": fbx,
        "nodes": [built[n]["mesh"] for n in built],
        "metres_per_unit": 1.0,
    }, timeout_s=600.0)
    print("export status:", exp.get("status"))
    if exp.get("status") != "ok":
        print("export error:", json.dumps(exp.get("error"), indent=1)[:900])
        return 1
    warnings = (exp.get("result") or {}).get("warnings") or []
    print("export warnings (%d):" % len(warnings))
    for w in warnings:
        print("  -", w)

    call("new_scene", {"confirm": True}, timeout_s=180.0)
    # The comparison runs in Maya against the shapes still held in the
    # persistent namespace, so only one float per case crosses the wire.
    after = run(
        "import maya.cmds as cmds\n"
        "cmds.file(%r, i=True, type='FBX', ignoreVersion=True,\n"
        "          mergeNamespacesOnClash=True, namespace=':')\n"
        "out = {}\n"
        "for _m in cmds.ls(type='transform'):\n"
        "    _s = _m.split('|')[-1].split(':')[-1]\n"
        "    if _s.endswith('_case'):\n"
        "        _key = _s[:-5]\n"
        "        if _key in _shapes:\n"
        "            out[_key] = _delta(_shapes[_key], _sig(_m))\n"
        "out" % fbx, "reimport", timeout_s=600.0)

    # The control fixes the noise floor: whatever the round-trip does to an
    # UNDEFORMED mesh is what "unchanged" costs in this metric.
    control_floor = after.get("control_none")
    print("\ncontrol (no deformer) round-trip shape delta: %s" % control_floor)
    floor = max((control_floor or 0.0) * 4.0, 1e-3)

    print("\n%-18s %-13s %-12s %s"
          % ("case", "verdict", "deformed by", "shape delta over round-trip"))
    report = {"control_round_trip_delta": control_floor, "floor": floor}
    for name in built:
        if name == "control_none":
            continue
        deformed = built[name].get("deformed_by")
        roundtrip = after.get(name)
        if roundtrip is None:
            print("%-18s %-13s %-12s %s"
                  % (name, "MISSING", "-", list(after)[:5]))
            report[name] = {"verdict": "missing"}
            continue
        if deformed is None or deformed <= floor:
            # Nothing was deformed, so nothing can be concluded about whether
            # the deformation survives. Saying "DROPPED" here would be the
            # blind-measurement trap this probe exists to avoid.
            verdict = "INCONCLUSIVE"
        elif roundtrip <= floor:
            verdict = "TRAVELS"
        else:
            verdict = "DROPPED"
        print("%-18s %-13s %-12.5f %.5f"
              % (name, verdict, deformed, roundtrip))
        report[name] = {"verdict": verdict, "deformed_by": deformed,
                        "roundtrip_delta": roundtrip}

    with open(os.path.join(OUT_DIR, "report.json"), "w") as handle:
        json.dump({"cases": report, "export_warnings": warnings}, handle, indent=1)
    print("\nwrote %s" % os.path.join(OUT_DIR, "report.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
