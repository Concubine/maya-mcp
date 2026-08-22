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

THE SCRATCH PROJECT ALREADY EXISTS on this machine, at
`D:/devel/unity-mt718-scratch` (Unity 6000.0.47f1, with
`com.coplaydev.unity-mcp` pulled from the same git URL Demigol's manifest
uses). Open it and its MCP bridge connects; there is no need to build a new
one. Creating it from scratch is `Unity.exe -createProject <path> -batchmode
-quit`, then adding that one dependency to `Packages/manifest.json`, then
opening the project so the package resolves. Do NOT point this gate at
Demigol - see above.

MEASURED: run once against a real Unity editor (2026-08-22). Length check:
Unity reported wave 1.500000s, idle 2.000000s, step 1.200000s against
Maya's declared ranges, max delta 4.8e-07s - well inside LENGTH_TOL_S.
`importAnimation` was already ON by default for this FBX, so the
`manage_asset(action="modify")` step in the procedure below was a no-op
(harmless - still worth doing, since Demigol's own project forces it off
and nothing here can assume a scratch project starts the same way). The
model imports as `animationType=Generic` with 4 default clips: the three
named takes plus Maya's own `Take 001`.

The first run's C#, and its contamination check, were both wrong and are
fixed now:

  - UNITY_MEASURE_CS runs as a METHOD BODY under unityMCP's CodeDom/C# 6
    backend, where a `using` directive is a syntax error ("Line 1:
    Unexpected symbol 'System', expecting '('") and LINQ is unavailable
    for the same reason. Every type below is fully qualified instead
    (`System.Func`, `UnityEngine.GameObject`, `UnityEditor.AssetDatabase`,
    ...) and the LINQ `.OfType<AnimationClip>()` filter is a plain loop.
    `LoadAllAssetsAtPath` also returns Unity's own internal preview clips
    (named `__preview__<clipname>`) alongside the real ones - filtered out
    by name prefix, or they would show up as extra, confusing "clips."

  - The contamination check (verify()'s check 4) compared every
    undeclared joint's sampled rotation against a hardcoded rest of
    [0,0,0]. That is wrong: a joint's `localRotation` in Unity carries its
    import-time joint ORIENTATION, which is not zero (measured: L_ankle's
    true rest is [270, 293.1986, 0], not [0,0,0]). The first run's 10
    "violations" were all this - every one of them had identical
    start/mid/end readings (the signature of a joint that never moved at
    all), just compared against the wrong reference. UNITY_MEASURE_CS now
    measures each declared joint's true rest pose once, on the freshly
    instantiated model BEFORE `SampleAnimation` is ever called on it, and
    emits it as a top-level "rest" block; verify() compares every
    undeclared joint's readings against ITS OWN measured rest, cyclically
    (mod 360, shortest signed distance - a 359.999 reading against a rest
    of 0 is 0.001 degrees away, not 359.999), never a hardcoded 0.

A second live run (2026-08-22) proved even that "rest" reference is wrong.
UNITY_MEASURE_CS measured the model's instantiated transform BEFORE
`SampleAnimation` ever ran on it - but that transform is the FBX's node
DEFAULT pose, which is Maya's EXPORT-TIME SCENE POSE, not the rig's rest
pose. Confirmed from both sides: evals/multi_take_live.py deliberately
authors `idle`'s loop with `spine_01`/`chest` NOT at rest (a -3 degree
lean, chosen precisely so the contamination checks would not be vacuous),
while Maya's own rest for those joints is 0. The exported FBX's node
defaults reflect whatever pose the scene held at export time - idle's -3
degree opening pose - which round-trips through Unity's Y-up sign flip to
+3 degrees. Meanwhile `wave` and `step` correctly pin `chest`/`spine_01` to
[0,0,0] (Maya's true rest). The second run flagged that CORRECT pinning as
4 false violations, all on `chest`/`spine_01`, because it compared against
the export-time scene pose instead of the rig's rest.

verify() no longer needs an absolute reference pose at all - Unity's own
clips are each other's reference. Two checks replace the old rest-relative
one, reported as distinguishable messages because they mean different
things:

  A. MOVEMENT - a joint a clip does not declare must not move within that
     clip: its start, mid and end samples must agree (cyclically) within
     STILLNESS_EPSILON_DEG. Catches a joint sweeping through the clip.

  B. AGREEMENT - the value a joint holds while undeclared must agree,
     cyclically, across every clip that does not declare it. Each joint in
     this rig is declared by exactly one clip, so at least two others hold
     it un-animated; if one of them inherited a neighbour's pose, the two
     would disagree. This needs no reference pose at all - the clips are
     each other's reference. With fewer than two non-declaring clips to
     compare, B cannot be evaluated, and verify() says so rather than
     passing silently.

Verified against the real measurements: `chest` (declared by idle) holds
[0,0,0] in both wave and step; `R_shoulder` (declared by wave) holds
[~0,180,270] in both idle and step; `L_hip` (declared by step) holds
[~0,180,~0] in both idle and wave - all three pairs agree, so all three
pass, which is the correct result. R_shoulder's [0,180,270] is exactly the
non-zero value the FIRST run's hardcoded-0 assumption got wrong, and
chest/spine_01's [0,0,0] is exactly what the SECOND run's export-time-pose
assumption got wrong (it expected +3, not 0) - checks A/B get both right
without needing to know either number up front, because they never consult
an assumed or measured "rest" at all.

The C#'s emitted default-pose block is kept - genuinely useful diagnostic
context, what a consumer's prefab shows before any clip plays - but renamed
from "rest" to "model_default_pose", and is printed only as context
alongside a violation, never read by verify() for correctness. Its comment
says explicitly that it is the export-time scene pose and NOT the rig's
rest pose, citing this exact chest/spine_01 case, so nobody wires it back
into a correctness check.
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

# The tolerance, in degrees, for BOTH checks verify() runs on a joint a clip
# does not declare - neither one needs, or consults, any absolute reference
# pose:
#
#   A. MOVEMENT - within one clip, that joint's start/mid/end samples must
#      agree (cyclically) within this many degrees. A larger spread means
#      the joint is sweeping through the clip's range.
#   B. AGREEMENT - across every OTHER clip that also does not declare that
#      joint, the value it holds (compared cyclically) must agree within
#      this many degrees. A larger spread means at least one of those
#      clips inherited a neighbour's pose - the actual contamination
#      defect. This is deliberately a clip-vs-clip comparison, not a
#      clip-vs-rest one: an earlier version of this gate compared every
#      undeclared joint against an assumed or measured "rest" pose, and
#      both attempts were wrong on real Unity data (module docstring's
#      MEASURED paragraphs) - a hardcoded 0 ignores joint orientation, and
#      the model's export-time default pose is the SCENE pose at export,
#      not the rig's rest. Two non-contaminated clips agreeing with each
#      other is proof enough, and needs neither number.
#
# Justification for the tolerance value, not a guess: Unity's FBX import
# converts Maya's per-axis rotation curves into its own internal
# representation (quaternion component curves for a Generic-rigged import)
# and back to Euler angles when `SampleAnimation` is read via
# `localRotation.eulerAngles` - that round trip alone can move a
# truly-constant value by floating-point noise, empirically well under 1e-3
# degrees in Unity's own quaternion math (measured: L_hip/R_hip's x and z
# axes at 7.0e-15 degrees off an exact multiple of 360). The smallest REAL
# motion any of the three authored clips contains is idle's spine/chest
# sway, a 10 degree swing (multi_take_live.IDLE_KEYS); wave's arm and
# step's hips move 30-45 degrees. 0.01 degrees sits three orders of
# magnitude below the smallest authored motion and roughly two above
# plausible round-trip noise - the same gap multi_take_live.py's own
# REST_ROT_TOL (1e-4 degrees) exploits on the Maya side, widened here
# because this measurement crosses one more lossy conversion (Maya bytes ->
# Unity's internal quaternion curves -> sampled Euler) that the Maya-side
# probe never goes through.
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
#
# Runs as a METHOD BODY under unityMCP's execute_code (CodeDom/C# 6
# backend) - a `using` directive there is a syntax error ("Line 1:
# Unexpected symbol 'System', expecting '('", measured on the first live
# run) and LINQ is unavailable for the same reason. Every type below is
# therefore fully qualified, and the one LINQ-shaped filter the first
# draft used (`.OfType<AnimationClip>().ToArray()`) is a plain loop.
_UNITY_MEASURE_TEMPLATE = r"""
// #718 consumer gate measurement. Run via mcp__unityMCP__execute_code
// against the multi-take FBX imported at __ASSET_PATH__ (importAnimation
// must already be ON and the asset reimported before this runs).
//
// Writes ONE JSON object to outputPath (see below), exactly the shape
// evals/multi_take_unity.py's verify() parses:
//   {"model_default_pose": {"<declared joint>": [x,y,z], ...},
//    "clips": [
//     {"name": str, "length": float, "frameRate": float,
//      "curves": [{"path": str, "property": str}, ...],
//      "samples": {"<declared joint>":
//                    {"start": [x,y,z], "mid": [x,y,z], "end": [x,y,z]}}}
//   ]}
//
// "model_default_pose" is measured ONCE, on the freshly instantiated model
// BEFORE SampleAnimation is ever called on it. DIAGNOSTIC ONLY - it is the
// FBX node's default transform, i.e. Maya's EXPORT-TIME SCENE POSE, NOT the
// rig's rest pose (two earlier attempts to use it, or a hardcoded [0,0,0],
// as a correctness reference were both wrong on real Unity data - see the
// module docstring's MEASURED paragraphs: chest/spine_01's true Maya rest
// is 0, but the FBX default carries idle's authored -3-degree opening pose
// instead). verify() never reads this block for correctness - only prints
// it as context alongside a violation.
//
// "samples" covers every DECLARED joint across ALL three clips (not just
// this clip's own), sampled at this clip's own start/mid/end - that is
// what lets verify() catch a joint a clip did NOT declare holding a
// neighbouring clip's pose through this clip's whole range.
//
// The C# returns a short one-line-per-clip summary, not the JSON itself -
// the JSON alone runs to 30KB+ of curve-binding data, and returning that
// through the tool call is worse than writing it to disk (outputPath,
// declared as a variable up front) and reading the file directly.
string modelPath = "__ASSET_PATH__";
string outputPath = System.IO.Path.Combine(
    System.IO.Path.GetDirectoryName(UnityEngine.Application.dataPath),
    "multi_take_unity_measurement.json");
string[] declaredJoints = new string[] { __JOINTS_CSV__ };

System.Func<string, string> Esc = s => s.Replace("\\", "\\\\").Replace("\"", "\\\"");
System.Func<float, string> Num = v => v.ToString("R", System.Globalization.CultureInfo.InvariantCulture);
System.Func<UnityEngine.Vector3, string> Vec3 = v => "[" + Num(v.x) + "," + Num(v.y) + "," + Num(v.z) + "]";

UnityEngine.GameObject mainAsset = UnityEditor.AssetDatabase.LoadMainAssetAtPath(modelPath) as UnityEngine.GameObject;
if (mainAsset == null) {
    return "{\"error\":\"no root GameObject at " + Esc(modelPath) + "\"}";
}

UnityEngine.Object[] allAssets = UnityEditor.AssetDatabase.LoadAllAssetsAtPath(modelPath);
System.Collections.Generic.List<UnityEngine.AnimationClip> clipList = new System.Collections.Generic.List<UnityEngine.AnimationClip>();
for (int ai = 0; ai < allAssets.Length; ai++) {
    UnityEngine.AnimationClip candidate = allAssets[ai] as UnityEngine.AnimationClip;
    if (candidate == null) continue;
    // LoadAllAssetsAtPath also returns Unity's own internal preview clips
    // (named "__preview__<clipname>") - duplicates of the real clips, not
    // takes Maya authored.
    if (candidate.name.StartsWith("__preview__")) continue;
    clipList.Add(candidate);
}
UnityEngine.AnimationClip[] clips = clipList.ToArray();

UnityEngine.GameObject instance = UnityEngine.Object.Instantiate(mainAsset);
System.Collections.Generic.Dictionary<string, UnityEngine.Transform> jointLookup = new System.Collections.Generic.Dictionary<string, UnityEngine.Transform>();
foreach (UnityEngine.Transform t in instance.GetComponentsInChildren<UnityEngine.Transform>(true)) {
    if (!jointLookup.ContainsKey(t.name)) jointLookup[t.name] = t;
}

// The model's default pose, BEFORE SampleAnimation touches this instance
// for the first time - the FBX node defaults (Maya's export-time scene
// pose, NOT the rig's rest - diagnostic only, see the header comment).
System.Text.StringBuilder defaultPoseSb = new System.Text.StringBuilder();
defaultPoseSb.Append("{");
bool firstDefaultJoint = true;
foreach (string jointName in declaredJoints) {
    UnityEngine.Transform defaultJt;
    if (!jointLookup.TryGetValue(jointName, out defaultJt)) continue;
    if (!firstDefaultJoint) defaultPoseSb.Append(",");
    firstDefaultJoint = false;
    defaultPoseSb.Append("\"" + Esc(jointName) + "\":" + Vec3(defaultJt.localRotation.eulerAngles));
}
defaultPoseSb.Append("}");

System.Text.StringBuilder sb = new System.Text.StringBuilder();
sb.Append("{\"model_default_pose\":" + defaultPoseSb.ToString() + ",\"clips\":[");
for (int ci = 0; ci < clips.Length; ci++) {
    UnityEngine.AnimationClip clip = clips[ci];
    if (ci > 0) sb.Append(",");

    UnityEditor.EditorCurveBinding[] bindings = UnityEditor.AnimationUtility.GetCurveBindings(clip);

    // One SampleAnimation call per TIME (not per joint), so every joint's
    // reading at a given time comes from the same applied pose.
    float[] times = new float[] { 0f, clip.length * 0.5f, clip.length };
    System.Collections.Generic.Dictionary<string, UnityEngine.Vector3[]> perJoint = new System.Collections.Generic.Dictionary<string, UnityEngine.Vector3[]>();
    foreach (string jointName in declaredJoints) {
        if (jointLookup.ContainsKey(jointName)) perJoint[jointName] = new UnityEngine.Vector3[3];
    }
    for (int ti = 0; ti < times.Length; ti++) {
        clip.SampleAnimation(instance, times[ti]);
        foreach (System.Collections.Generic.KeyValuePair<string, UnityEngine.Vector3[]> kv in perJoint) {
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
    foreach (System.Collections.Generic.KeyValuePair<string, UnityEngine.Vector3[]> kv in perJoint) {
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

System.IO.File.WriteAllText(outputPath, sb.ToString());

System.Text.StringBuilder summary = new System.Text.StringBuilder();
summary.Append("wrote " + clips.Length + " clip(s) to " + outputPath + ": ");
for (int ci = 0; ci < clips.Length; ci++) {
    if (ci > 0) summary.Append(", ");
    summary.Append(clips[ci].name + "=" + Num(clips[ci].length) + "s");
}
UnityEngine.Debug.Log(summary.ToString());
return summary.ToString();
""".strip("\n")

UNITY_MEASURE_CS = (_UNITY_MEASURE_TEMPLATE
                     .replace("__ASSET_PATH__", ASSET_PATH)
                     .replace("__JOINTS_CSV__", _cs_string_array(ALL_JOINTS)))


def _angle_cyclic_diff(a, b):
    """Shortest signed distance in degrees from angle `b` to angle `a`,
    treating both as points on a 360-degree cycle - so a reading of
    359.999 against a rest of 0.0 is 0.001 degrees away, not 359.999.
    `a - b` alone (what the first draft used) is wrong at that wraparound;
    a plain `% 360` without re-centring into [-180, 180] is ALSO wrong for
    a slightly-negative value (Python's `%` returns a positive remainder,
    so -1e-15 % 360 comes back near +360, not near 0) - exactly the kind
    of float noise Unity's quaternion round trip leaves on a value that
    should read as an exact multiple of 360 (measured: L_hip/R_hip's x and
    z axes at 7.0e-15). Re-centring after the modulo handles both."""
    d = (a - b) % 360.0
    if d > 180.0:
        d -= 360.0
    return d


def _vec3_cyclic_worst(vec, ref):
    """Largest per-component cyclic distance (degrees) between two
    3-vectors of angles."""
    return max(abs(_angle_cyclic_diff(float(v), float(r)))
               for v, r in zip(vec, ref))


def verify(declared, measured):
    """Pure. No Unity, no I/O. `declared` is DECLARED (or an equivalent
    list of {name, fps, start_frame, end_frame, joints} records);
    `measured` is the JSON object UNITY_MEASURE_CS writes to its output
    file, already parsed - {"model_default_pose": {...}, "clips": [...]}.

    Returns a list of violation strings (empty = pass). No absolute
    reference pose is ever consulted - two earlier versions of this gate
    tried that (a hardcoded [0,0,0], then the model's export-time default
    pose from `measured["model_default_pose"]`) and both were wrong on real
    Unity data (module docstring's MEASURED paragraphs: a joint orientation
    is generally non-zero, and the FBX default reflects whatever pose the
    scene held at EXPORT time, not the rig's rest). `model_default_pose` is
    diagnostic only now - never read below, only printed as context by
    main() alongside a violation.

    Checks, per declared clip:

      1. it exists by name in `measured` (a clip present in Unity but NOT
         declared is NOT a violation - same rule the byte gate's
         `anim_violations` applies to an undeclared take, #718 design doc's
         byte-gate section: "A take present in the file but not declared is
         NOT a violation").
      2. its `length` matches (end_frame - start_frame) / fps within
         LENGTH_TOL_S.
      3. every joint any DECLARED clip touches, other than this clip's own,
         actually appears in this clip's `samples` with all three readings
         (start/mid/end) present and numeric - the completeness check.
         Without this, a joint Unity's measurement fails to produce ANY
         reading for (a name mismatch after import, a lookup miss, any
         gap) is simply absent from `samples`; check A below only ever
         walks the joints THAT ARE PRESENT, so a missing joint contributes
         zero violations and the gate reports a false clean PASS on
         exactly the defect it exists to catch. "Every joint that should
         have been sampled" is derived from the `declared` records
         themselves (the union of every clip's `joints`, minus this
         clip's own) - never a hardcoded list, so it tracks whatever the
         live Maya gate actually authored.
      A. MOVEMENT - every joint sampled for that clip that this clip does
         NOT declare must not move within the clip: its start/mid/end
         readings must agree, cyclically, within STILLNESS_EPSILON_DEG.
         Catches a joint sweeping through the clip's own range.

    Then, once per joint rather than per clip:

      B. AGREEMENT - the value an undeclared joint holds (its "mid" sample,
         which check A above already established agrees with start/end to
         within epsilon whenever A did not already fire) must agree,
         cyclically within STILLNESS_EPSILON_DEG, across EVERY clip that
         does not declare that joint. This is the actual contamination
         check, and it needs no reference pose at all - the clips are each
         other's reference. Each joint in this rig is declared by exactly
         one clip, so at least two others hold it un-animated; if one of
         them inherited a neighbour's pose instead of the correct constant,
         the two would disagree, regardless of what that correct constant
         is (proven here by
         TestContamination.test_backward_hold_pattern_is_caught and
         TestNoRestNeeded.test_correct_nonzero_constant_across_all_clips_is_not_flagged
         in tests/test_multi_take_unity.py - the latter is the exact shape
         both of this gate's earlier reference-pose attempts got wrong).
         When fewer than two clips leave a joint undeclared AND measurable,
         B cannot be evaluated - reported as its own message (a check that
         cannot run is not a check that passed), not a silent pass. A
         joint declared by every clip, or missing entirely from every
         other clip's samples (already caught by check 3), naturally lands
         here as "fewer than two."
    """
    violations = []
    measured_by_name = {c["name"]: c for c in measured.get("clips", [])
                        if "name" in c}

    # The completeness universe: every joint ANY declared clip touches.
    # Derived from `declared` itself - never hardcoded - so it always
    # matches what the live Maya gate actually authored.
    all_declared_joints = {j for r in declared for j in r.get("joints", [])}

    # Per-clip bookkeeping check B needs after the per-clip loop below:
    # which joints each clip declares (so B knows which clips to compare),
    # and each found clip's own samples (so B can read the "mid" value
    # without re-deriving it from `measured`).
    clip_declared_joints = {}
    clip_samples = {}
    clip_found = {}

    for record in declared:
        name = record["name"]
        clip_declared_joints[name] = set(record.get("joints", []))
        m = measured_by_name.get(name)
        if m is None:
            violations.append(
                "clip %r is declared but was not found among Unity's "
                "imported clips (found: %s)"
                % (name, sorted(measured_by_name)))
            clip_found[name] = False
            continue
        clip_found[name] = True

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

        declared_joints = clip_declared_joints[name]
        samples = m.get("samples", {})
        clip_samples[name] = samples

        # Check 3: completeness. A joint declared by ANOTHER clip must
        # show up in THIS clip's samples at all - if it is simply absent
        # (not malformed, not still, ABSENT), check A below would never
        # see it and the gap would pass silently.
        for joint in sorted(all_declared_joints - declared_joints):
            if joint not in samples:
                violations.append(
                    "clip %r: joint %r should have been sampled (it is "
                    "declared by another clip) but is missing from "
                    "Unity's measurement entirely - a measurement gap is "
                    "not proof of stillness" % (name, joint))

        # Check A: movement across the three samples, cyclic, for every
        # joint Unity's measurement DID produce a reading for.
        for joint, rows in samples.items():
            if joint in declared_joints:
                continue
            try:
                start = [float(v) for v in rows["start"]]
                mid = [float(v) for v in rows["mid"]]
                end = [float(v) for v in rows["end"]]
            except (KeyError, TypeError, ValueError):
                violations.append(
                    "clip %r: joint %r has a malformed samples entry (%r)"
                    % (name, joint, rows))
                continue

            move_worst = max(_vec3_cyclic_worst(start, mid),
                              _vec3_cyclic_worst(mid, end),
                              _vec3_cyclic_worst(start, end))
            if move_worst > STILLNESS_EPSILON_DEG:
                violations.append(
                    "clip %r: joint %r is NOT declared by this clip but its "
                    "sampled rotation MOVES %.6f degrees within the clip's "
                    "own range (start=%s mid=%s end=%s) > epsilon=%.g "
                    "degrees - it should be perfectly still (check A: "
                    "movement)"
                    % (name, joint, move_worst, start, mid, end,
                       STILLNESS_EPSILON_DEG))

    # Check B: cross-clip agreement, once per joint. Uses each non-
    # declaring clip's "mid" sample as that clip's held value - check A
    # above already confirms start/mid/end agree within epsilon whenever it
    # did not itself fire, so "mid" alone represents the held pose without
    # any circular-averaging pitfalls (a plain arithmetic mean of, say,
    # 359.999 and 0.001 would wrongly land near 180).
    for joint in sorted(all_declared_joints):
        held = {}
        for record in declared:
            name = record["name"]
            if joint in clip_declared_joints[name]:
                continue
            if not clip_found.get(name):
                continue
            rows = clip_samples.get(name, {}).get(joint)
            if not rows:
                continue  # already flagged by check 3
            try:
                held[name] = [float(v) for v in rows["mid"]]
            except (KeyError, TypeError, ValueError):
                continue  # already flagged by check A's malformed-entry case

        if len(held) < 2:
            violations.append(
                "joint %r: only %d clip(s) leave it undeclared and "
                "measurable (%s) - check B (cross-clip agreement) needs at "
                "least two to compare and cannot be evaluated here; a "
                "check that cannot run is not a check that passed"
                % (joint, len(held), sorted(held)))
            continue

        names = sorted(held)
        worst_diff = -1.0
        worst_pair = None
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                d = _vec3_cyclic_worst(held[names[i]], held[names[j]])
                if d > worst_diff:
                    worst_diff = d
                    worst_pair = (names[i], names[j])

        if worst_diff > STILLNESS_EPSILON_DEG:
            detail = ", ".join(
                "%r held %s" % (n, held[n]) for n in names)
            violations.append(
                "joint %r is undeclared by %d clip(s) but they do not hold "
                "the same value: %r vs %r differ by %.6f degrees > "
                "epsilon=%.g degrees (check B: agreement) - one of these "
                "clips inherited a neighbour's pose instead of the joint's "
                "own constant value: %s"
                % (joint, len(names), worst_pair[0], worst_pair[1],
                   worst_diff, STILLNESS_EPSILON_DEG, detail))

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
    Runs the measurement (this module's UNITY_MEASURE_CS constant). It
    WRITES the JSON object described in verify()'s docstring to a file
    (outputPath inside the C#, computed as
    "<project root>/multi_take_unity_measurement.json" - a sibling of the
    project's Assets/ folder) and returns only a short one-line-per-clip
    summary; the full JSON is 30KB+ of curve-binding data and not worth
    returning through the tool call.

 7. Copy that file locally (if the scratch project is remote) and verify
    it:
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
        default_pose = measured.get("model_default_pose")
        if default_pose:
            print()
            print("Diagnostic context (NOT part of the check above - see "
                  "verify()'s docstring): the model's export-time default "
                  "pose per joint, i.e. the pose a consumer's prefab shows "
                  "before any clip plays. This is Maya's SCENE pose at "
                  "export time, not the rig's rest pose (chest/spine_01 "
                  "measured non-zero here even though Maya's true rest for "
                  "both is 0 - see module docstring).")
            for joint in sorted(default_pose):
                print("  model_default_pose[%r] = %s"
                      % (joint, default_pose[joint]))
        return 1

    found = sorted(measured_name for measured_name in
                   (c.get("name") for c in measured.get("clips", []))
                   if measured_name is not None)
    print("PASS: all %d declared clip(s) verified against Unity's import "
          "(Unity reported: %s)" % (len(DECLARED), found))
    return 0


if __name__ == "__main__":
    sys.exit(main())
