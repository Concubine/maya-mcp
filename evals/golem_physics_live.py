"""Phase-4 gate for #676: the delivered golem re-measured by author_physics.

The delivery under evals/golem_delivery/ was measured by a one-off
execute_python escape that was never committed; author_physics exists to
close exactly that gap. This gate opens the REAL delivered scene
(golem_metre.mb) on the disposable Maya, regenerates every number through
the tool, and diffs field-class by field-class against the committed
ground truth (chunks.json for measurements, manifest.json for design
data), with explicit tolerances and an explained-divergence ledger.

NO RENDERS on purpose: this is a data tool - a picture proves nothing
about a volume, a COM or a cone. The evidence is baseline.json.

DESTRUCTIVE to its Maya's open scene (open_scene). Port 9878, the
agent-launched Maya, per the two-Maya policy - never the user's 9877.
READS the delivery, never writes under it: the delivery is a frozen,
provenance-bearing artifact (a4154f2 lineage).

Run:  uv run python evals/golem_physics_live.py
Exit: 0 pass, 1 fail, 2 no connection.
"""

from __future__ import annotations

import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from live_call import call, structured_result  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
DELIVERY = os.path.join(_HERE, "golem_delivery")
OUT_DIR = os.path.join(_HERE, "golem_physics_live")

# Tolerances, each derived, none guessed:
VOLUME_REL_TOL = 0.01      # chunks.json rounds volume_m3 to 6 dp: up to
VOLUME_ABS_TOL = 1e-6      # ~0.6% on the smallest tracer (8.6e-05)
COM_BBOX_FRACTION = 0.05   # delivered COM method uncommitted (the fist's
                           # equals its bbox centre EXACTLY); ours is the
                           # solid COM the contract asks for
VR_SLACK = 0.05            # "equal" arm of equal-or-better
ESCAPE_SLACK = 0.005
VR_WORST = 2.4             # delivered worst 2.35 (golem_C_waist_gasket)
ESCAPE_RATIO_WORST = 0.10  # delivered worst 0.0913 (golem_L/R_thigh)
MASS_FRACTION_TOL = 1e-4   # manifest rounds mass_fraction to 6 dp
CONE_TOL = 1e-9            # pure arithmetic, no excuse for slack

CHECKS = []


def check(label, passed, detail=""):
    CHECKS.append((bool(passed), label))
    print("%s %s%s" % ("PASS" if passed else "FAIL", label,
                       ("  [%s]" % detail) if detail else ""))
    return bool(passed)


def send(command, params, timeout_s=300.0):
    try:
        return call(command, params, timeout_s=timeout_s, port=PORT)
    except (ConnectionRefusedError, OSError) as exc:
        print("could not reach a Maya plugin on %s: %s" % (PORT, exc))
        sys.exit(2)


def ok(command, params, timeout_s=300.0):
    response = send(command, params, timeout_s)
    if response.get("status") != "ok":
        print("FAIL: %s: %s"
              % (command, json.dumps(response.get("error"))[:600]))
        sys.exit(1)
    return response.get("result") or {}


def py(code, what, timeout_s=300.0):
    return structured_result(
        ok("execute_python", {"code": code}, timeout_s), what)


def short(name):
    return name.split("|")[-1]


def dist(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def bbox_diag(entry):
    lo, hi = entry["bbox_min_m"], entry["bbox_max_m"]
    return math.sqrt(sum((hi[i] - lo[i]) ** 2 for i in range(3)))


def unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return [c / n for c in v]


def main():
    if PORT == 9877:
        print("refusing to run on 9877: this eval discards the open scene "
              "(two-Maya policy). Launch a disposable Maya on 9878.")
        return 2

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(DELIVERY, "chunks.json")) as fh:
        chunks_data = json.load(fh)
    with open(os.path.join(DELIVERY, "manifest.json")) as fh:
        manifest = json.load(fh)
    detail = {e["name"]: e for e in manifest["chunks_detail"]}
    names = sorted(chunks_data)
    check("delivery ground truth loaded: 33 chunks",
          len(names) == 33 and set(detail) == set(names))

    identity = py("import os\n{'pid': os.getpid()}", "identity")
    print("Maya on %d: pid %s, writing to %s\n"
          % (PORT, identity["pid"], OUT_DIR))

    scene = os.path.join(DELIVERY, "golem_metre.mb")
    ok("open_scene", {"path": scene, "confirm": True}, timeout_s=600.0)

    # ---- known-unknown 1: is the delivered DAG nested or flat? ----------
    probe = py(
        "import maya.cmds as cmds\n"
        "chunks = %r\n"
        "out = {}\n"
        "for name in chunks:\n"
        "    longs = cmds.ls(name, long=True) or []\n"
        "    if len(longs) != 1:\n"
        "        out[name] = {'resolved': longs}\n"
        "        continue\n"
        "    node, parent = longs[0], None\n"
        "    walk = node\n"
        "    while True:\n"
        "        ups = cmds.listRelatives(walk, parent=True, fullPath=True)\n"
        "        if not ups:\n"
        "            break\n"
        "        walk = ups[0]\n"
        "        if walk.split('|')[-1] in chunks:\n"
        "            parent = walk.split('|')[-1]\n"
        "            break\n"
        "    out[name] = {'long': node, 'dag_parent': parent}\n"
        "out" % names, "chunk resolution + DAG shape")
    unresolved = [n for n in names if "long" not in probe.get(n, {})]
    check("all 33 chunk names resolve uniquely in the scene",
          not unresolved, ", ".join(unresolved[:6]))
    if unresolved:
        return 1
    dag_nested = any(probe[n]["dag_parent"] for n in names)
    print("DAG shape measured: %s\n"
          % ("nested" if dag_nested else "flat siblings"))

    # ---- overrides FROM the manifest: design data round-trips -----------
    overrides = {}
    for name in names:
        entry = detail[name]
        o = {}
        if entry.get("parent"):
            o["parent"] = entry["parent"]
        joint = entry.get("joint")
        if joint:
            o["hinge_axis"] = joint["hinge_axis_local"]
            o["hinge_range_deg"] = joint["hinge_range_deg"]
        if o:
            overrides[name] = o

    before = py("import maya.cmds as cmds\n"
                "{'nodes': len(cmds.ls(long=True))}", "node count before")
    result = ok("author_physics",
                {"chunks": names, "density": 1.0, "overrides": overrides},
                timeout_s=600.0)
    after = py("import maya.cmds as cmds\n"
               "{'nodes': len(cmds.ls(long=True))}", "node count after")
    check("read-only: scene node count unchanged",
          before["nodes"] == after["nodes"],
          "%d -> %d" % (before["nodes"], after["nodes"]))

    bodies = {short(b["chunk"]): b for b in result["bodies"]}
    check("all 33 chunks measured", set(bodies) == set(names))
    check("no missing-override warnings (all design data supplied)",
          not any("LOCKED joint" in w for w in result["warnings"]),
          "; ".join(result["warnings"][:4]))

    baseline = {"dag_nested": dag_nested,
                "tool_warnings": result["warnings"],
                "per_chunk": {}, "worst": {}, "kinds": {},
                "divergences": {}}

    # ---- Part A: the numbers vs chunks.json -----------------------------
    worst_vol_rel = worst_com = 0.0
    for name in names:
        d = chunks_data[name]
        b = bodies[name]
        diag = bbox_diag(d)
        vol_abs = abs(b["volume"] - d["volume_m3"])
        vol_rel = vol_abs / max(d["volume_m3"], 1e-12)
        worst_vol_rel = max(worst_vol_rel, vol_rel)
        check("%s volume %.6g vs %.6g" % (name, b["volume"], d["volume_m3"]),
              vol_rel <= VOLUME_REL_TOL or vol_abs <= VOLUME_ABS_TOL,
              "rel=%.4g" % vol_rel)
        check("%s verts/tris identical" % name,
              b["verts"] == d["verts"] and b["tris"] == d["tris"],
              "%d/%d vs %d/%d" % (b["verts"], b["tris"],
                                  d["verts"], d["tris"]))
        com_err = dist(b["com"], d["centre_of_mass_m"])
        worst_com = max(worst_com, com_err / diag)
        check("%s com within %.0f%% of bbox diag" % (name,
                                                     COM_BBOX_FRACTION * 100),
              com_err <= COM_BBOX_FRACTION * diag,
              "err=%.4g diag=%.4g" % (com_err, diag))
        baseline["per_chunk"][name] = {
            "volume": b["volume"], "volume_rel_diff": vol_rel,
            "com_err": com_err, "watertight": b["watertight"],
            "kind": b["collider"]["kind"], "kind_delivered":
                d["collider"]["type"],
            "volume_ratio": b["collider"]["volume_ratio"],
            "volume_ratio_delivered": d["collider"]["volume_ratio"],
            "max_escape": b["collider"]["max_escape"],
            "max_escape_delivered": d["collider"]["max_escape_m"],
        }

    # ---- Part B: colliders - equal or better, defined ------------------
    kind_matches = 0
    worst_vr = 0.0
    worst_escape_ratio = 0.0
    for name in names:
        d = chunks_data[name]
        b = bodies[name]
        col = b["collider"]
        diag = bbox_diag(d)
        vr = col["volume_ratio"] if col["volume_ratio"] is not None else 1e9
        worst_vr = max(worst_vr, vr)
        worst_escape_ratio = max(worst_escape_ratio,
                                 col["max_escape"] / diag)
        same_kind = col["kind"] == d["collider"]["type"]
        kind_matches += int(same_kind)
        better = (vr <= d["collider"]["volume_ratio"] + VR_SLACK
                  or col["max_escape"] <= d["collider"]["max_escape_m"]
                  + ESCAPE_SLACK)
        check("%s collider equal-or-better (%s vs %s)"
              % (name, col["kind"], d["collider"]["type"]),
              same_kind or better,
              "vr %.3g vs %.3g, escape %.4g vs %.4g"
              % (vr, d["collider"]["volume_ratio"],
                 col["max_escape"], d["collider"]["max_escape_m"]))
        # sanity: the primitive centre sits inside the chunk's own bbox
        inside = all(d["bbox_min_m"][k] - 0.05 * diag <= col["centre"][k]
                     <= d["bbox_max_m"][k] + 0.05 * diag for k in range(3))
        check("%s collider centre inside the chunk bbox" % name, inside,
              json.dumps(col["centre"]))
    check("global: worst volume_ratio <= %.2f (delivered worst 2.35)"
          % VR_WORST, worst_vr <= VR_WORST, "worst=%.3f" % worst_vr)
    check("global: worst escape ratio <= %.0f%% (delivered worst 9.13%%)"
          % (ESCAPE_RATIO_WORST * 100),
          worst_escape_ratio <= ESCAPE_RATIO_WORST,
          "worst=%.4f" % worst_escape_ratio)
    baseline["kinds"] = {"matches": kind_matches, "total": len(names)}
    print("collider kind agreement: %d/%d (mismatches allowed only when "
          "measurably equal-or-better)\n" % (kind_matches, len(names)))

    # ---- Part C: design data round-trips --------------------------------
    for name in names:
        entry = detail[name]
        b = bodies[name]
        want_parent = entry.get("parent")
        got_parent = short(b["parent"]) if b["parent"] else None
        check("%s parent == manifest's (%s)" % (name, want_parent),
              got_parent == want_parent, "got %s" % got_parent)
        # golem_C_pelvis is the one chunk where the manifest ships a
        # "joint" block on a chunk with parent=None (note: "root - the
        # controller moves this; it has no parent joint to limit") - a
        # documentation placeholder, not a constraint. author_physics
        # (physics.py: "if parent is not None: joint = ...") can never
        # emit a joint without a parent to hang it from, so a root is
        # "no joint" regardless of whether the manifest's joint key is
        # present - measured live 2026-08-20, task-6 report.
        joint = entry.get("joint") if entry.get("parent") else None
        if not joint:
            check("%s has no joint (root body)" % name, b["joint"] is None)
            continue
        lo, hi = joint["hinge_range_deg"]
        cone = b["joint"]
        check("%s cone: swing1=(hi-lo)/2, swing2=0, centre=(lo+hi)/2"
              % name,
              cone is not None
              and abs(cone["swing1"] - (hi - lo) / 2.0) < CONE_TOL
              and cone["swing2"] == 0.0
              and abs(cone["swing_centre_deg"] - (lo + hi) / 2.0) < CONE_TOL
              and cone["source"] == "override",
              json.dumps({k: cone[k] for k in
                          ("swing1", "swing2", "swing_centre_deg")})
              if cone else "no joint")
        axis = unit(joint["hinge_axis_local"])
        check("%s cone axis == normalized hinge_axis_local" % name,
              cone is not None and dist(cone["axis"], axis) < 1e-9)
    shin = bodies["golem_L_shin"]["joint"]
    check("the knee rule on golem_L_shin: neutral at the cone extreme",
          abs(shin["swing_centre_deg"] - shin["swing1"]) < CONE_TOL
          and shin["swing2"] == 0.0,
          "centre=%.4g swing1=%.4g" % (shin["swing_centre_deg"],
                                       shin["swing1"]))

    total = result["total_volume"]
    worst_mf = 0.0
    for name in names:
        mf = bodies[name]["volume"] / total
        err = abs(mf - detail[name]["mass_fraction"])
        worst_mf = max(worst_mf, err)
    check("mass_fraction cross-check over all 33 (abs <= %.0e)"
          % MASS_FRACTION_TOL, worst_mf <= MASS_FRACTION_TOL,
          "worst=%.2e" % worst_mf)
    check("total volume vs manifest mass_model",
          abs(total - manifest["mass_model"]["total_volume_m3"])
          <= 33 * VOLUME_ABS_TOL + 0.01 * total,
          "%.6f vs %.6f" % (total,
                            manifest["mass_model"]["total_volume_m3"]))
    check("handoff mass ordering: fist > forearm (measured)",
          bodies["golem_L_fist"]["volume"]
          > bodies["golem_L_forearm"]["volume"])
    check("handoff mass ordering: thigh > shin (measured)",
          bodies["golem_L_thigh"]["volume"]
          > bodies["golem_L_shin"]["volume"])

    # ---- Part D: purity and determinism ---------------------------------
    again = ok("author_physics",
               {"chunks": names, "density": 1.0, "overrides": overrides},
               timeout_s=600.0)
    check("determinism: a second call returns identical bodies",
          json.dumps(again["bodies"], sort_keys=True)
          == json.dumps(result["bodies"], sort_keys=True))

    # root-mode probe: reported, not asserted equal (the scene may hold
    # lights or helpers the walk legitimately sees)
    top = py(
        "import maya.cmds as cmds\n"
        "node = cmds.ls(%r, long=True)[0]\n"
        "while True:\n"
        "    ups = cmds.listRelatives(node, parent=True, fullPath=True)\n"
        "    if not ups:\n"
        "        break\n"
        "    node = ups[0]\n"
        "{'top': node}" % names[0], "top ancestor")["top"]
    walked = ok("author_physics", {"root": top}, timeout_s=600.0)
    walked_names = {short(b["chunk"]) for b in walked["bodies"]}
    check("root-mode walk from %s finds every chunk" % top,
          set(names) <= walked_names,
          "missing: %s" % ", ".join(sorted(set(names) - walked_names)[:6]))
    baseline["root_walk"] = {"root": top,
                             "extras": sorted(walked_names - set(names))}

    # ---- Part E: the divergence ledger ----------------------------------
    baseline["worst"] = {"volume_rel": worst_vol_rel,
                         "com_over_diag": worst_com,
                         "volume_ratio": worst_vr,
                         "escape_ratio": worst_escape_ratio,
                         "mass_fraction_abs": worst_mf}
    baseline["divergences"] = {
        "joint_shape": "manifest ships hinge currency (hinge_axis_local + "
            "hinge_range_deg + free-text twist); the tool ships the "
            "handoff swing/twist cone - the spec's shape. Conversion "
            "asserted 1:1 from the same design data (Part C).",
        "com_method": "delivered centre_of_mass_m method uncommitted (the "
            "fist's equals its bbox centre exactly); ours is the "
            "tetra-weighted solid COM the contract asks for.",
        "collider_centre": "delivered centre_local_m semantics are "
            "inconsistent between chunks; ours is WORLD - sanity-checked "
            "against each chunk's bbox instead of diffed.",
        "kinds": "mismatches allowed only when measurably equal-or-better "
            "(the delivered kinds are themselves inconsistent: elbow "
            "gasket capsule vs knee gasket box for the same ring shape).",
        "not_emitted": "breakable, break_impulse_mult, break_note, role, "
            "mass_fraction (composer aggregation), materials, pivot "
            "(scene data - get_object_info's job), rest_deg.",
        "added": "mass, signed_volume, watertight, open_edges, "
            "swing_centre_deg, joint.source, rotation_deg (frame euler; "
            "delivered rotation_local_deg convention uncommitted).",
    }
    with open(os.path.join(OUT_DIR, "baseline.json"), "w") as fh:
        json.dump(baseline, fh, indent=2, sort_keys=True)

    print("\n" + "=" * 72)
    print("DIVERGENCE LEDGER (every structural difference, explained):")
    for key, why in baseline["divergences"].items():
        print("  %s: %s" % (key, why))
    print("=" * 72 + "\n")

    failed = [label for passed, label in CHECKS if not passed]
    print("%d/%d checks passed" % (len(CHECKS) - len(failed), len(CHECKS)))
    for label in failed:
        print("  FAILED: %s" % label)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
