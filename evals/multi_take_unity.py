"""#718 consumer gate: a multi-take FBX re-imported by a real Unity.

The byte gate (evals/multi_take_live.py's export check + fbxbytes.anim_facts)
proves the FILE declares three takes; this proves UNITY reads three clips,
with the right lengths, and that a joint a clip never keyed does not move
inside that clip. That last one is the contamination check on the consumer's
side - the defect the self-contained rule exists to prevent (see #718's
design doc, "the self-contained takes rule") is invisible in the bytes: a
curve holding a neighbouring clip's pose reads as a perfectly well-formed
take.

Driven through the unityMCP TOOLS by the agent, in a SCRATCH project -
Demigol's importer forces importAnimation=false, which is exactly why this
cannot run there (docs/superpowers/specs/2026-08-22-multi-take-fbx-design.md,
"Unity gate"). This script holds the C# to run and the policy to judge its
output; it never talks to Unity itself - a Python process cannot call an
MCP tool, only the agent driving this conversation can.

If the Unity editor is not open, or `claude mcp list` shows unityMCP
unhealthy, report that and STOP. Do NOT fall back to a Unity CLI batchmode
run - that is this machine's standing rule (see CLAUDE.md, "MCP is the
PRIMARY tooling path"): a silent fallback hides the breakage and bakes in
the slower path as normal.

DECLARED, FBX_PATH and UNITY_MEASURE_CS are all derived from
evals/multi_take_live/baseline.json, the file the live Maya gate
(evals/multi_take_live.py) writes after authoring and exporting the three
clips - never hand-restated here, so the byte gate and this consumer gate
cannot silently disagree about what was declared.

Usage:
    uv run python evals/multi_take_unity.py                 # print the steps
    uv run python evals/multi_take_unity.py --measurements m.json
Exit: 0 pass, 1 fail.

MEASURED: not yet run against a real Unity editor. This script has been
exercised only as pure Python (verify()'s own test suite,
tests/test_multi_take_unity.py) and by reading UNITY_MEASURE_CS as text -
see .superpowers/sdd/t718-13-report.md for exactly what was and was not
checked. The steps below have not executed against a live Unity instance;
whoever runs them next should replace this paragraph with the measured
clip count, per-clip length, and the stillness epsilon actually observed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))

BASELINE_PATH = os.path.join(_HERE, "multi_take_live", "baseline.json")

# A declared clip's Unity `length` (seconds) must match this, computed from
# the same fields fbxbytes/export.anim_violations checks the byte gate
# against (evals/multi_take_live.py's take-span check uses the identical
# formula). 1e-3 s is the brief's own figure; it is far looser than the
# 0.5/fps (~0.017 s at 30 fps) the byte gate uses because Unity's own
# reported clip.length additionally passes through its own fps-quantised
# frame count on import, one more rounding step than the byte gate's direct
# tick read.
LENGTH_TOL_S = 1e-3

# A joint NOT declared by a clip must sit within this many degrees of REST
# (0 on every axis) at every one of its three samples for that clip to
# pass - an absolute distance-from-rest check, not "does it vary between
# the three samples" (see verify()'s docstring for why the latter cannot
# catch the documented failure shape). Justification, not a
# guess: Unity's FBX import converts Maya's per-axis rotation curves into
# its own internal representation (quaternion component curves for a
# Generic-rigged import) and back to Euler angles when `SampleAnimation` is
# read via `localRotation.eulerAngles` - that round trip alone can move a
# truly-constant value by floating-point noise, empirically well under 1e-3
# degrees in Unity's own quaternion math. The smallest REAL motion any of
# the three authored clips contains is idle's spine/chest sway, a 10 degree
# swing (multi_take_live.IDLE_KEYS); wave's arm and step's hips move 30-45
# degrees. 0.01 degrees sits three orders of magnitude below the smallest
# authored motion and roughly two above plausible round-trip noise - the
# same gap multi_take_live.py's own REST_ROT_TOL (1e-4 degrees) exploits on
# the Maya side, widened here because this measurement crosses one more
# lossy conversion (Maya bytes -> Unity's internal quaternion curves ->
# sampled Euler) that the Maya-side probe never goes through.
STILLNESS_EPSILON_DEG = 0.01

# Where the scratch project should receive the exported FBX. A plain
# subfolder under Assets/ - unityMCP has no "upload a local file into the
# project" tool of its own (import_model_file both copies AND imports in
# one step, which the brief's steps do not use - it needs importAnimation
# forced ON before Unity's importer ever runs, and import_model_file's
# animation_type controls RIG type, not the importAnimation flag Demigol's
# project forces off), so the copy itself is a plain filesystem operation
# the agent performs directly, followed by refresh_unity + manage_asset to
# turn animation import on and force a reimport.
ASSET_SUBDIR = "Assets/MultiTakeGate718"


def _load_baseline(path=BASELINE_PATH):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


_baseline = _load_baseline()

# The three clips Task 12 authored, read straight from the live gate's own
# output - never re-typed here. Each record: {name, fps, start_frame,
# end_frame, joints, root_position_used}.
DECLARED = _baseline["clips"]

# Resolved relative to baseline.json's OWN directory (multi_take_live.py's
# convention: its "fbx" field is a bare filename sitting next to the
# baseline it wrote, not a path relative to the repo root or the caller's
# cwd).
FBX_PATH = os.path.normpath(
    os.path.join(os.path.dirname(BASELINE_PATH), _baseline["fbx"]))

ASSET_PATH = "%s/%s" % (ASSET_SUBDIR, os.path.basename(FBX_PATH))

# The union of every joint any declared clip keys - the set UNITY_MEASURE_CS
# samples in every clip, so verify() can check, per clip, that every joint
# NOT in that clip's own `joints` list held still.
ALL_JOINTS = sorted({j for clip in DECLARED for j in clip.get("joints", [])})


def _cs_string_array(names):
    return ", ".join('"%s"' % n.replace("\\", "\\\\").replace('"', '\\"')
                     for n in names)


# Plain string substitution, not str.format(): the C# body below is full of
# literal '{' '}' braces (blocks, dictionaries, string interpolation-free
# concatenation), which .format() would treat as fields and choke on. The
# two placeholders are deliberately un-brace-shaped so they cannot collide.
_UNITY_MEASURE_TEMPLATE = r"""
// #718 consumer gate measurement. Run via mcp__unityMCP__execute_code
// against the multi-take FBX imported at __ASSET_PATH__ (importAnimation
// must already be ON and the asset reimported before this runs).
//
// Prints ONE JSON object, exactly the shape evals/multi_take_unity.py's
// verify() parses:
//   {"clips": [
//     {"name": str, "length": float, "frameRate": float,
//      "curves": [{"path": str, "property": str}, ...],
//      "samples": {"<declared joint>":
//                    {"start": [x,y,z], "mid": [x,y,z], "end": [x,y,z]}}}
//   ]}
//
// "samples" covers every DECLARED joint across ALL three clips (not just
// this clip's own), sampled at this clip's own start/mid/end - that is
// what lets verify() catch a joint a clip did NOT declare holding a
// neighbouring clip's pose through this clip's whole range.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;
using UnityEditor;
using UnityEngine;

string modelPath = "__ASSET_PATH__";
string[] declaredJoints = new string[] { __JOINTS_CSV__ };

Func<string, string> Esc = s => s.Replace("\\", "\\\\").Replace("\"", "\\\"");
Func<float, string> Num = v => v.ToString("R", CultureInfo.InvariantCulture);
Func<Vector3, string> Vec3 = v => "[" + Num(v.x) + "," + Num(v.y) + "," + Num(v.z) + "]";

GameObject mainAsset = AssetDatabase.LoadMainAssetAtPath(modelPath) as GameObject;
if (mainAsset == null) {
    return "{\"error\":\"no root GameObject at " + Esc(modelPath) + "\"}";
}

UnityEngine.Object[] allAssets = AssetDatabase.LoadAllAssetsAtPath(modelPath);
AnimationClip[] clips = allAssets.OfType<AnimationClip>().ToArray();

GameObject instance = UnityEngine.Object.Instantiate(mainAsset);
Dictionary<string, Transform> jointLookup = new Dictionary<string, Transform>();
foreach (Transform t in instance.GetComponentsInChildren<Transform>(true)) {
    if (!jointLookup.ContainsKey(t.name)) jointLookup[t.name] = t;
}

StringBuilder sb = new StringBuilder();
sb.Append("{\"clips\":[");
for (int ci = 0; ci < clips.Length; ci++) {
    AnimationClip clip = clips[ci];
    if (ci > 0) sb.Append(",");

    UnityEditor.EditorCurveBinding[] bindings = AnimationUtility.GetCurveBindings(clip);

    // One SampleAnimation call per TIME (not per joint), so every joint's
    // reading at a given time comes from the same applied pose.
    float[] times = new float[] { 0f, clip.length * 0.5f, clip.length };
    Dictionary<string, Vector3[]> perJoint = new Dictionary<string, Vector3[]>();
    foreach (string jointName in declaredJoints) {
        if (jointLookup.ContainsKey(jointName)) perJoint[jointName] = new Vector3[3];
    }
    for (int ti = 0; ti < times.Length; ti++) {
        clip.SampleAnimation(instance, times[ti]);
        foreach (KeyValuePair<string, Vector3[]> kv in perJoint) {
            kv.Value[ti] = jointLookup[kv.Key].localRotation.eulerAngles;
        }
    }

    sb.Append("{\"name\":\"" + Esc(clip.name) + "\",");
    sb.Append("\"length\":" + Num(clip.length) + ",");
    sb.Append("\"frameRate\":" + Num(clip.frameRate) + ",");

    sb.Append("\"curves\":[");
    for (int bi = 0; bi < bindings.Length; bi++) {
        if (bi > 0) sb.Append(",");
        sb.Append("{\"path\":\"" + Esc(bindings[bi].path) + "\",\"property\":\""
                  + Esc(bindings[bi].propertyName) + "\"}");
    }
    sb.Append("],");

    sb.Append("\"samples\":{");
    bool firstJoint = true;
    string[] labels = new string[] { "start", "mid", "end" };
    foreach (KeyValuePair<string, Vector3[]> kv in perJoint) {
        if (!firstJoint) sb.Append(",");
        firstJoint = false;
        sb.Append("\"" + Esc(kv.Key) + "\":{");
        for (int i = 0; i < 3; i++) {
            if (i > 0) sb.Append(",");
            sb.Append("\"" + labels[i] + "\":" + Vec3(kv.Value[i]));
        }
        sb.Append("}");
    }
    sb.Append("}}");
}
sb.Append("]}");

UnityEngine.Object.DestroyImmediate(instance);
Debug.Log(sb.ToString());
return sb.ToString();
""".strip("\n")

UNITY_MEASURE_CS = (_UNITY_MEASURE_TEMPLATE
                     .replace("__ASSET_PATH__", ASSET_PATH)
                     .replace("__JOINTS_CSV__", _cs_string_array(ALL_JOINTS)))


def verify(declared, measured):
    """Pure. No Unity, no I/O. `declared` is DECLARED (or an equivalent
    list of {name, fps, start_frame, end_frame, joints} records);
    `measured` is the JSON object UNITY_MEASURE_CS printed, already parsed.

    Returns a list of violation strings (empty = pass). Checks, per
    declared clip:

      1. it exists by name in `measured` (a clip present in Unity but NOT
         declared is NOT a violation - same rule the byte gate's
         `anim_violations` applies to an undeclared take, #718 design doc's
         byte-gate section: "A take present in the file but not declared is
         NOT a violation").
      2. its `length` matches (end_frame - start_frame) / fps within
         LENGTH_TOL_S.
      3. every joint sampled for that clip that this clip does NOT declare
         sits at REST (0 degrees on every axis, every one of its three
         samples) within STILLNESS_EPSILON_DEG - the consumer-side
         contamination check.

         Deliberately an ABSOLUTE distance-from-rest check, not "does the
         reading vary across the three samples" (a plausible first reading
         of the brief's wording, and this script's own first draft): the
         design doc's failure shape is a curve holding "whatever value its
         last key left on it" - a CONSTANT, not a sweep. A joint on the
         wrong side of a missing backward pin reads the SAME wrong value at
         start, mid and end alike (proven here by
         TestContamination.test_backward_hold_pattern_is_caught in
         tests/test_multi_take_unity.py), so a spread-based check sees zero
         variance and passes the exact defect this gate exists to catch.
         Comparing every sample to the joint's known rest value (0 - the
         same assumption multi_take_live.py's rest_probe/worst_rotation
         make on the Maya side, valid because create_skeleton bakes
         orientation into jointOrient, leaving local rotate at bind = 0)
         catches both shapes: a constant wrong hold (every sample equally
         far from 0) and an actual leaked sweep (at least one sample far
         from 0).
    """
    violations = []
    measured_by_name = {c["name"]: c for c in measured.get("clips", [])
                        if "name" in c}

    for record in declared:
        name = record["name"]
        m = measured_by_name.get(name)
        if m is None:
            violations.append(
                "clip %r is declared but was not found among Unity's "
                "imported clips (found: %s)"
                % (name, sorted(measured_by_name)))
            continue

        fps = float(record["fps"])
        expected_length = (record["end_frame"] - record["start_frame"]) / fps
        actual_length = float(m.get("length", float("nan")))
        diff = abs(actual_length - expected_length)
        if diff > LENGTH_TOL_S:
            violations.append(
                "clip %r: Unity length %.6f s does not match declared "
                "%.6f s (fps=%s frames=%d..%d), diff=%.6f s > tol=%.g s"
                % (name, actual_length, expected_length, record["fps"],
                   record["start_frame"], record["end_frame"], diff,
                   LENGTH_TOL_S))

        declared_joints = set(record.get("joints", []))
        samples = m.get("samples", {})
        for joint, rows in samples.items():
            if joint in declared_joints:
                continue
            try:
                start, mid, end = rows["start"], rows["mid"], rows["end"]
            except (KeyError, TypeError):
                violations.append(
                    "clip %r: joint %r has a malformed samples entry (%r)"
                    % (name, joint, rows))
                continue
            worst = max(abs(v) for vec in (start, mid, end) for v in vec)
            if worst > STILLNESS_EPSILON_DEG:
                violations.append(
                    "clip %r: joint %r is NOT declared by this clip but its "
                    "sampled rotation reaches %.6f degrees away from rest "
                    "(start=%s mid=%s end=%s) > epsilon=%.g degrees - "
                    "contamination from a neighbouring clip"
                    % (name, joint, worst, start, mid, end,
                       STILLNESS_EPSILON_DEG))

    return violations


def _steps_text():
    clip_names = ", ".join(repr(c["name"]) for c in DECLARED)
    return """\
#718 Unity consumer gate - steps to run (unityMCP tools, in order)

If the Unity editor is not open, or `claude mcp list` shows unityMCP
unhealthy: STOP here and report that. Do not fall back to a CLI batchmode
run.

Target a SCRATCH Unity project - never Demigol's (D:/devel/Demigol/unity):
its importer forces importAnimation=false, which is the exact reason this
gate cannot run there.

Declared clips (from %s): %s
FBX to import: %s
Destination in the scratch project: %s

 1. mcp__unityMCP__set_active_instance
    Pin the scratch project's instance BEFORE any other call - several
    Unity instances may be connected at once, and an unpinned call with
    more than one connected errors rather than guessing. List candidates
    first via the mcpforunity://instances resource; pass its Name@hash (or
    a hash/port prefix) as `instance`.

 2. mcp__unityMCP__manage_editor(action="telemetry_ping")
    Confirms the pinned editor actually answers before anything else
    touches its project - if this fails or times out, STOP and report it
    rather than proceeding on a guess that the editor is up.

 3. Copy %s into <scratch project>/%s
    Plain filesystem copy, done directly by the agent (no unityMCP tool
    uploads a local file into a project - import_model_file both copies
    AND imports in one step, which skips the "importAnimation forced ON
    before Unity's importer first runs" requirement below).

 4. mcp__unityMCP__refresh_unity(scope="assets", compile="none")
    Makes Unity notice the new file under Assets/.

 5. mcp__unityMCP__manage_asset(action="modify", path=%r,
        properties={"importAnimation": true})
    then mcp__unityMCP__manage_asset(action="import", path=%r)
    Turns animation import ON (Demigol's project forces it off) and forces
    a reimport under the new setting. If "modify" cannot reach the model
    importer's importAnimation field this way, get_info on the same path
    first to find the property's exact reflected name before retrying.

 6. mcp__unityMCP__execute_code(action="execute", code=UNITY_MEASURE_CS)
    Runs the measurement (this module's UNITY_MEASURE_CS constant). Its
    return value is the JSON object described in verify()'s docstring.

 7. Save that JSON to a file, then verify it:
    uv run python evals/multi_take_unity.py --measurements <path to the JSON>
""" % (os.path.basename(BASELINE_PATH), clip_names, FBX_PATH, ASSET_PATH,
       FBX_PATH, ASSET_PATH, ASSET_PATH, ASSET_PATH)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="#718 consumer gate: verify a real Unity's read of the "
                    "multi-take FBX against what Maya declared.")
    parser.add_argument(
        "--measurements", metavar="PATH",
        help="JSON file holding UNITY_MEASURE_CS's return value. When "
            "given, verify it and exit 0/1. When omitted, print the "
            "unityMCP steps to run and exit 0.")
    args = parser.parse_args(argv)

    if args.measurements is None:
        print(_steps_text())
        return 0

    with open(args.measurements, "r", encoding="utf-8") as fh:
        measured = json.load(fh)

    violations = verify(DECLARED, measured)
    if violations:
        print("FAIL: %d violation(s):" % len(violations))
        for v in violations:
            print("  - %s" % v)
        return 1

    found = sorted(measured_name for measured_name in
                   (c.get("name") for c in measured.get("clips", []))
                   if measured_name is not None)
    print("PASS: all %d declared clip(s) verified against Unity's import "
          "(Unity reported: %s)" % (len(DECLARED), found))
    return 0


if __name__ == "__main__":
    sys.exit(main())
