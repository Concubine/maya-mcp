"""#743 consumer gate: the drifter, re-imported and DEFORMED by a real Unity.

The byte gate (evals/drifter_live.py) proves the FILE declares a skin
cluster, two blend-shape channels and three takes. This proves UNITY
reconstructs them - one SkinnedMeshRenderer, driven by curves on both the
bones and blendShape.<name> - and that the vertices it actually draws match
the vertices Maya computed.

Every comparison is a FRAME-INVARIANT distance (drifter_metrics), never a
coordinate and never a height. #737's check_poses reported 0 violations at
1 mm on a file that was 3.2 m wrong in a consumer, because it re-composed
poses the way OUR reader does. A shared metric cannot drift like that - so
verify() below calls drifter_metrics.compare_samples/seam_violations
directly rather than reimplementing either comparison.

Driven through the unityMCP TOOLS by the agent, in a SCRATCH project. This
script holds the C# to run and the policy to judge its output; it never
talks to Unity itself - a Python process cannot call an MCP tool, only the
agent driving the conversation can.

If the Unity editor is not open, or `claude mcp list` shows unityMCP
unhealthy, report that and STOP. Do NOT fall back to a Unity CLI batchmode
run - CLAUDE.md, "MCP is the PRIMARY tooling path".

DECLARED is derived from evals/drifter_live/baseline.json and never
hand-restated, so the byte gate and this gate cannot silently disagree
about what was declared.

Four things measured about a real Unity import this session, all baked
into UNITY_MEASURE_CS below:

  1. Snippets run as METHOD BODIES under CodeDom, not top-level programs -
     a `using` directive is a syntax error ("Unexpected symbol 'System',
     expecting '('") and every type must be fully qualified
     (UnityEngine.Mesh, System.Collections.Generic.List<>, ...).
  2. The backend is CodeDom, not Roslyn - C# 6 only. No string
     interpolation, no null-conditional (?.), no nameof, no
     expression-bodied members, no LINQ (a `using System.Linq` would
     itself already be refused, but even without it .Select/.Where/OfType
     are unavailable). Every filter below is a plain loop; a lambda
     assigned to a System.Func<> variable (not a LINQ extension) is fine -
     that pattern already ran clean against a real editor in #718's gate.
  3. MEASURED against a real editor 2026-08-23: Unity's ModelImporter does
     NOT preserve a 1:1 vertex index mapping with Maya. The drifter's
     23,922-vertex mesh imports as sharedMesh.vertexCount == 93344 - UV
     and hard-normal seams split each affected vertex into several, with
     weldVertices/optimizeMeshVertices/optimizeMeshPolygons all OFF making
     no difference (measured both ways). Worse, neither Maya's live
     `.vtx[]` world positions NOR the raw FBX "Vertices" control-point
     array (as fbxbytes.read_fbx parses it) locate a matching Unity vertex
     within useful tolerance for any landmark except the apex (a pole
     point where dozens of duplicates coincide) - Maya's `.vtx[]` index
     and the FBX file's control-point index are evidently not the same
     ordering either. A landmark picked by INDEX in Maya cannot be
     re-located by index, or by naive nearest-position search, in Unity.
     The fix: re-derive apex/tip/rim in Unity using the SAME geometric
     definition drifter_live.py's _find_landmarks uses (max/min world Y
     for apex/tip; farthest pair among rim-band candidates for rim),
     applied directly to Unity's own bind-pose sharedMesh.vertices - never
     Maya's indices. See RIM_Y/RIM_RADIUS_MIN below, imported from
     drifter_live rather than restated.
  4. MEASURED: a blend shape's Unity name carries its Maya deformer-node
     prefix, e.g. "drifter_body_shapes.bell_crease" - not the bare alias
     ("bell_crease") baseline.json declares. verify() matches by exact
     name OR by dot-suffix so the two conventions can agree.

Mesh.GetBonesPerVertex() returns a Unity.Collections.NativeArray<byte>
holding NATIVE memory - read with a plain indexed loop and Dispose() it
before it goes out of scope, once, never per-sample.

The measurement itself poses the rig with AnimationClip.SampleAnimation
and reads the ACTUALLY DEFORMED vertices with SkinnedMeshRenderer.BakeMesh
- skinning and blend shapes both applied - which is the entire point: a
byte gate can prove the FBX declares a skin cluster and two blend-shape
channels without ever proving Unity's renderer actually moves a vertex
because of them.

Usage:
    uv run python evals/drifter_unity.py                  # print the steps
    uv run python evals/drifter_unity.py --measurements m.json
Exit: 0 pass, 1 fail.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import drifter_metrics as dm  # noqa: E402
# RIM_Y/RIM_RADIUS_MIN drive the C#'s own landmark re-detection (see the
# module docstring, point 3) - imported, never hand-restated, so a future
# change to drifter_live's rim band moves this gate too.
from drifter_live import RIM_Y as _RIM_Y  # noqa: E402
from drifter_live import RIM_RADIUS_MIN as _RIM_RADIUS_MIN  # noqa: E402
from drifter_live import RIM_BAND_HALF as _RIM_BAND_HALF  # noqa: E402
from drifter_live import TIP_BAND as _TIP_BAND  # noqa: E402
from drifter_live import APEX_BAND as _APEX_BAND  # noqa: E402
from drifter_metrics import POSITION_QUANTUM as _QUANTUM  # noqa: E402

BASELINE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "drifter_live", "baseline.json")


def _load_baseline(path=BASELINE_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


_baseline = _load_baseline()

def _clips_with_duration(clips, fps) -> list:
    """baseline.json's clip records carry start_frame/end_frame/loop/name -
    no duration_s (that field is a live_call/author_clip convention verify()
    happens to expect, not something drifter_live.py itself writes). Derived
    here, once, as (end_frame - start_frame) / fps - never hand-restated as
    a literal, so a future baseline with different frame ranges recomputes
    correctly rather than silently comparing against a stale number."""
    out = []
    for c in clips:
        d = dict(c)
        d["duration_s"] = (c["end_frame"] - c["start_frame"]) / float(fps)
        out.append(d)
    return out


# Never hand-restated: every field below is read straight out of the live
# gate's own baseline.json, so this gate and the byte gate cannot silently
# disagree about what Maya declared.
DECLARED = {
    "joints": _baseline["joints"],
    "blend_targets": _baseline["blend_targets"],
    "looping_clips": _baseline["looping_clips"],
    "tolerances": _baseline["tolerances"],
    "clips": _clips_with_duration(_baseline["clips"], _baseline["fps"]),
    "samples": _baseline["samples"],
}

# Maya's own landmark indices/measurement, kept ONLY for cross-reference in
# the report (e.g. comparing Unity's re-derived rim_diameter_at_pick against
# this one) - MEASURED 2026-08-23: these indices are NOT fed to Unity. See
# the module docstring, point 3: neither Maya's `.vtx[]` index nor the FBX
# file's own control-point index locates the same vertex in Unity's
# imported (vertex-split) mesh, so UNITY_MEASURE_CS re-derives its own
# landmarks geometrically instead of reusing these.
_LANDMARKS = _baseline["landmarks"]
for _name in ("apex", "tip", "rim"):
    _got = _LANDMARKS.get(_name)
    if not isinstance(_got, list) or not _got:
        raise SystemExit(
            "landmarks.%s must be a non-empty LIST of vertex indices, got %r. "
            "A bare int (or a 2-element rim) is the pre-2026-08-24 shape, "
            "where each landmark was a single extremum vertex - that rule was "
            "measured unable to survive re-derivation in Unity. Re-run "
            "evals/drifter_live.py to regenerate baseline.json." % (_name, _got))
MAYA_LANDMARK_SIZES = {n: len(_LANDMARKS[n]) for n in ("apex", "tip", "rim")}
MAYA_RIM_DIAMETER_AT_PICK = float(_LANDMARKS["rim_diameter_at_pick"])

# How much wider than Maya's the C# searches each band before rank-cutting
# to MAYA_LANDMARK_SIZES. 1.5 is a margin, not a tuned value: the measured
# overshoot was 14% at the tip and 1.3% at the rim, so 50% clears both with
# room, and anything the widening lets in is discarded by the cut anyway.
BAND_WIDEN = 1.5

FBX_PATH = _baseline["fbx"]["path"]
ASSET_SUBDIR = "Assets/DrifterGate743"
ASSET_PATH = "%s/%s" % (ASSET_SUBDIR, os.path.basename(FBX_PATH))


def verify(declared: dict, measured: dict) -> dict:
    """Pure policy. No Unity, no filesystem, no network.

    `declared` is DECLARED (or an equivalent dict carrying `joints`,
    `blend_targets`, `looping_clips`, `tolerances`, `clips`, `samples`).
    `measured` is UNITY_MEASURE_CS's written JSON, already parsed:
    {"bones": int, "blend_shapes": [str], "clips": [{"name","length"}],
     "bones_per_vertex_max": int, "samples": [{"clip","frame",
     "rim_diameter","apex_to_tip"}]}.

    Every deformation/seam check is delegated to drifter_metrics
    (compare_samples/seam_violations) rather than reimplemented - the
    whole point per #737: a validator that recomposes a comparison its own
    way instead of calling the shared function can silently disagree with
    what a consumer actually sees.

    bones_per_vertex_max is REPORTED in `detail` but never itself a
    problem: Unity truncating 8-influence binds to 4 is an expected,
    already-understood consequence of the engine's own limit (drifter_live
    bound deliberately above it to construct this exact case), not a
    product defect - the deformation comparison above is what would catch
    the truncation actually MATTERING (a wrong vertex position), if it did.
    """
    problems = []
    tol = declared["tolerances"]

    if int(measured.get("bones", -1)) != int(declared["joints"]):
        problems.append("bone count is %r, declared %r"
                        % (measured.get("bones"), declared["joints"]))

    # MEASURED 2026-08-23 against a real editor: Unity's imported blend
    # shape names carry the Maya deformer node's name as a dot-prefix
    # ("drifter_body_shapes.bell_crease"), not the bare alias baseline.json
    # declares ("bell_crease") - an exact-match check failed on a file that
    # genuinely carries both channels. Accept an exact match OR the
    # declared name as a dot-suffix of a measured one.
    got_shapes = set(measured.get("blend_shapes") or [])
    for want in declared["blend_targets"]:
        if want in got_shapes:
            continue
        suffix = "." + want
        if not any(g == want or g.endswith(suffix) for g in got_shapes):
            problems.append("blend shape %r absent in Unity (got %r)"
                            % (want, sorted(got_shapes)))

    got_clips = {c["name"]: c for c in (measured.get("clips") or [])}
    for want in declared["clips"]:
        got = got_clips.get(want["name"])
        if got is None:
            problems.append("clip %r absent in Unity" % want["name"])
            continue
        delta = abs(float(got["length"]) - float(want["duration_s"]))
        if delta > 1e-3:
            problems.append("clip %r length %r, declared %r (delta %.3g)"
                            % (want["name"], got["length"],
                               want["duration_s"], delta))
        # The loop FLAG, which is a different question from the loop SEAM.
        # seam_violations proves the geometry closes - drift_idle's first
        # and last frame agreed to 0.000000 m on the first live run. It
        # cannot prove Unity will replay the clip, and MEASURED 2026-08-24
        # it would not have: every take imports with isLooping == false,
        # because the FBX importer defaults loopTime off per take. A
        # seamless clip that plays once and stops is still a broken asset.
        if "is_looping" not in got:
            problems.append(
                "clip %r carries no is_looping - the measurement predates "
                "the loop-flag check; re-run UNITY_MEASURE_CS" % want["name"])
        else:
            want_loop = want["name"] in declared["looping_clips"]
            if bool(got["is_looping"]) != want_loop:
                problems.append(
                    "clip %r imported with is_looping=%r, declared %r "
                    "(set Loop Time on the take in the model importer)"
                    % (want["name"], bool(got["is_looping"]), want_loop))

    try:
        bad = dm.compare_samples(declared["samples"],
                                 measured.get("samples") or [],
                                 tol["compare"])
    except ValueError as exc:
        problems.append("incomplete measurement: %s" % exc)
        bad = []
    for b in bad:
        problems.append(
            "%s frame %d: %s declared %.6f, Unity %.6f (delta %.6f)"
            % (b["clip"], b["frame"], b["metric"], b["declared"],
               b["measured"], b["delta"]))

    seams = dm.seam_violations(measured.get("samples") or [],
                               declared["looping_clips"], tol["seam"])
    for s in seams:
        problems.append(
            "loop seam reopened in Unity: %s %s first %.6f last %.6f "
            "(delta %.6f)" % (s["clip"], s["metric"], s["first"],
                              s["last"], s["delta"]))

    return {"ok": not problems, "problems": problems,
            "detail": {"bones_per_vertex_max":
                       measured.get("bones_per_vertex_max"),
                       "deformation_violations": len(bad),
                       "seam_violations": len(seams)}}


# --- C# generation ---------------------------------------------------------

def _cs_string_array(values) -> str:
    return ", ".join(
        '"%s"' % str(v).replace("\\", "\\\\").replace('"', '\\"')
        for v in values)


def _cs_int_array(values) -> str:
    return ", ".join(str(int(v)) for v in values)


def _cs_float_array(values) -> str:
    # "%.17g" round-trips a Python float exactly; the trailing "f" makes
    # each entry a valid C# float literal. Precision lost narrowing to
    # float32 is immaterial here - these are only ever passed to
    # AnimationClip.SampleAnimation's float `time` parameter.
    return ", ".join("%.17gf" % float(v) for v in values)


# One (clip, frame, time_s) triple per declared sample row, in DECLARED's
# own order - never a hardcoded list, so the C# always asks for exactly
# what the live Maya gate actually sampled.
_SAMPLE_CLIPS = [s["clip"] for s in DECLARED["samples"]]
_SAMPLE_FRAMES = [int(s["frame"]) for s in DECLARED["samples"]]
_SAMPLE_TIMES = [float(s["time_s"]) for s in DECLARED["samples"]]

# Plain string substitution, not str.format(): the C# body is full of
# literal '{' '}' braces that .format() would treat as fields. Placeholders
# are deliberately un-brace-shaped so they cannot collide.
#
# Runs as a METHOD BODY under unityMCP's execute_code (CodeDom/C# 6
# backend) - see the module docstring for what that rules out. Every clip
# gets its OWN freshly-instantiated GameObject: a clip only keys the
# channels it declares, so reusing one instance across clips would leave
# an earlier clip's SampleAnimation call's untouched channels stuck at
# whatever they last were, contaminating this clip's deformed shape for
# reasons that have nothing to do with what Unity actually does with THIS
# clip. Static facts (bone count, blend shape names, bones-per-vertex) are
# properties of the shared mesh/skeleton, not of any one clip's pose, so
# they are measured once on their own throwaway instance instead.
_UNITY_MEASURE_TEMPLATE = r"""
// #743 consumer gate measurement. Run via mcp__unityMCP__execute_code
// against the drifter FBX imported at __ASSET_PATH__ (importAnimation must
// already be ON and the asset reimported before this runs).
//
// Writes ONE JSON object to outputPath (below), exactly the shape
// evals/drifter_unity.py's verify() expects:
//   {"bones": int, "blend_shapes": [str, ...],
//    "clips": [{"name": str, "length": float}, ...],
//    "bones_per_vertex_max": int,
//    "samples": [{"clip": str, "frame": int,
//                 "rim_diameter": float, "apex_to_tip": float}, ...]}
//
// rim_diameter/apex_to_tip are read from the SkinnedMeshRenderer's
// ACTUALLY BAKED mesh (BakeMesh, after SampleAnimation posed the rig) at
// four vertex indices found by RE-DERIVING drifter_live's landmark
// definitions directly on Unity's own bind-pose mesh (apex/tip = max/min
// world Y; rim = farthest pair among rim-band candidates) - MEASURED
// 2026-08-23: Unity's FBX import splits the drifter's 23,922 vertices into
// 93,344 (UV/hard-normal seams), and neither Maya's `.vtx[]` index nor the
// raw FBX control-point index locates the same physical vertex in that
// split mesh within useful tolerance, so Maya's landmark INDICES cannot be
// reused here - only the geometric RULE that picked them can.
string modelPath = "__ASSET_PATH__";
string outputPath = System.IO.Path.Combine(
    System.IO.Path.GetDirectoryName(UnityEngine.Application.dataPath),
    "drifter_unity_measurement.json");

float rimY = __RIM_Y__;
float rimRadiusMin = __RIM_RADIUS_MIN__;
float rimBandHalfWidth = __RIM_BAND_HALF__;
float tipBand = __TIP_BAND__;
float apexBand = __APEX_BAND__;
float quantum = __QUANTUM__;
// Bands are searched WIDER here than in Maya, then rank-cut to the counts
// Maya declared. A hard threshold cannot make two engines agree on set
// SIZE across an FBX float32 round-trip - measured 105 vs 120 at the tip,
// 774 vs 784 at the rim - so the producer declares cardinality and this
// side reproduces it. Widening guarantees the cut never comes up short.
float bandWiden = __BAND_WIDEN__;
int apexN = __APEX_N__;
int tipN = __TIP_N__;
int rimN = __RIM_N__;

string[] reqClip = new string[] { __SAMPLE_CLIPS__ };
int[] reqFrame = new int[] { __SAMPLE_FRAMES__ };
float[] reqTime = new float[] { __SAMPLE_TIMES__ };

System.Func<string, string> Esc = s => s.Replace("\\", "\\\\").Replace("\"", "\\\"");
System.Func<float, string> Num = v => v.ToString("R", System.Globalization.CultureInfo.InvariantCulture);

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
    // (named "__preview__<clipname>") - not takes Maya authored.
    if (candidate.name.StartsWith("__preview__")) continue;
    clipList.Add(candidate);
}
UnityEngine.AnimationClip[] clips = clipList.ToArray();

// --- Static facts: bones, blend shapes, bones-per-vertex - properties of
// the shared mesh/skeleton, measured ONCE on a throwaway instance before
// any clip ever poses it. ---
UnityEngine.GameObject infoInstance = UnityEngine.Object.Instantiate(mainAsset);
UnityEngine.SkinnedMeshRenderer infoSmr = infoInstance.GetComponentInChildren<UnityEngine.SkinnedMeshRenderer>(true);
if (infoSmr == null) {
    UnityEngine.Object.DestroyImmediate(infoInstance);
    return "{\"error\":\"no SkinnedMeshRenderer under " + Esc(modelPath) + "\"}";
}
int bones = infoSmr.bones.Length;
UnityEngine.Mesh sharedMesh = infoSmr.sharedMesh;

// --- Landmarks, re-derived on Unity's OWN bind-pose vertices ------------
// Same rule drifter_metrics.py documents and unit-tests, run here rather
// than trusted to carry an index across the import: band-select a SET,
// dedupe it by quantised position, measure an AGGREGATE.
//
// The first live run of this gate picked apex/tip as the single global
// max/min-Y vertex and rim as the farthest pair in the band. All three are
// extrema, and MEASURED, the drifter's 12 lowest cap vertices span just
// 10.3 mm in distinct positions - so Maya and Unity each landed on a
// different physical point and 26 of 42 deltas came back 0.6-12.1 mm out.
// That was selection noise, not deformation error, and no tolerance could
// have told the difference. Bands plus centroids remove the choice.
//
// The dedupe matters specifically here: Unity splits this mesh's 23,922
// vertices into 93,344 at UV/hard-normal seams, and those duplicates share
// a position exactly. A raw mean would weight a seam vertex 2-4x and drift
// away from Maya's; one index per quantised position weighs them equally.
UnityEngine.Vector3[] bindVerts = sharedMesh.vertices;
float minY = bindVerts[0].y;
float maxY = bindVerts[0].y;
for (int vi = 1; vi < bindVerts.Length; vi++) {
    if (bindVerts[vi].y < minY) minY = bindVerts[vi].y;
    if (bindVerts[vi].y > maxY) maxY = bindVerts[vi].y;
}

System.Func<UnityEngine.Vector3, string> posKey = delegate(UnityEngine.Vector3 p) {
    long kx = (long)System.Math.Round(p.x / quantum);
    long ky = (long)System.Math.Round(p.y / quantum);
    long kz = (long)System.Math.Round(p.z / quantum);
    return kx.ToString() + "_" + ky.ToString() + "_" + kz.ToString();
};

System.Collections.Generic.List<int> apexSet = new System.Collections.Generic.List<int>();
System.Collections.Generic.List<int> tipSet = new System.Collections.Generic.List<int>();
System.Collections.Generic.List<int> rimSet = new System.Collections.Generic.List<int>();
System.Collections.Generic.HashSet<string> apexSeen = new System.Collections.Generic.HashSet<string>();
System.Collections.Generic.HashSet<string> tipSeen = new System.Collections.Generic.HashSet<string>();
System.Collections.Generic.HashSet<string> rimSeen = new System.Collections.Generic.HashSet<string>();
int apexRaw = 0;
int tipRaw = 0;
int rimRaw = 0;
for (int vi = 0; vi < bindVerts.Length; vi++) {
    UnityEngine.Vector3 p = bindVerts[vi];
    string k = posKey(p);
    if (maxY - p.y <= apexBand * bandWiden) {
        apexRaw++;
        if (apexSeen.Add(k)) apexSet.Add(vi);
    }
    if (p.y - minY <= tipBand * bandWiden) {
        tipRaw++;
        if (tipSeen.Add(k)) tipSet.Add(vi);
    }
    float radius = UnityEngine.Mathf.Sqrt(p.x * p.x + p.z * p.z);
    if (UnityEngine.Mathf.Abs(p.y - rimY) < rimBandHalfWidth * bandWiden && radius > rimRadiusMin) {
        rimRaw++;
        if (rimSeen.Add(k)) rimSet.Add(vi);
    }
}
// Rank-cut to the declared cardinality: tip = lowest y, apex = highest y,
// rim = closest to rimY. Ties break by vertex index in BOTH engines, so
// the cut is deterministic rather than dependent on iteration order.
apexSet.Sort(delegate(int a, int b) {
    int c = bindVerts[b].y.CompareTo(bindVerts[a].y);
    return c != 0 ? c : a.CompareTo(b);
});
tipSet.Sort(delegate(int a, int b) {
    int c = bindVerts[a].y.CompareTo(bindVerts[b].y);
    return c != 0 ? c : a.CompareTo(b);
});
rimSet.Sort(delegate(int a, int b) {
    float da = UnityEngine.Mathf.Abs(bindVerts[a].y - rimY);
    float db = UnityEngine.Mathf.Abs(bindVerts[b].y - rimY);
    int c = da.CompareTo(db);
    return c != 0 ? c : a.CompareTo(b);
});
int apexCut = apexSet.Count < apexN ? apexSet.Count : apexN;
int tipCut = tipSet.Count < tipN ? tipSet.Count : tipN;
int rimCut = rimSet.Count < rimN ? rimSet.Count : rimN;
apexSet = apexSet.GetRange(0, apexCut);
tipSet = tipSet.GetRange(0, tipCut);
rimSet = rimSet.GetRange(0, rimCut);

if (apexSet.Count == 0 || tipSet.Count == 0 || rimSet.Count == 0) {
    return "LANDMARK BAND EMPTY (apex=" + apexSet.Count + " tip=" + tipSet.Count
        + " rim=" + rimSet.Count + ") - the band constants no longer fit this mesh";
}

// centroid of a set, in WORLD space
System.Func<UnityEngine.Vector3[], UnityEngine.Matrix4x4, System.Collections.Generic.List<int>, UnityEngine.Vector3> centroidOf =
    delegate(UnityEngine.Vector3[] vv, UnityEngine.Matrix4x4 m, System.Collections.Generic.List<int> set) {
        UnityEngine.Vector3 acc = UnityEngine.Vector3.zero;
        for (int si = 0; si < set.Count; si++) { acc += m.MultiplyPoint3x4(vv[set[si]]); }
        return acc / (float)set.Count;
    };

// 2 x mean XZ radius about the ring's OWN XZ centre - centre-relative so
// pulse_swim's 0.7 m of root translation cannot move the number.
System.Func<UnityEngine.Vector3[], UnityEngine.Matrix4x4, System.Collections.Generic.List<int>, float> ringDiameterOf =
    delegate(UnityEngine.Vector3[] vv, UnityEngine.Matrix4x4 m, System.Collections.Generic.List<int> set) {
        float cx = 0f;
        float cz = 0f;
        for (int si = 0; si < set.Count; si++) {
            UnityEngine.Vector3 w = m.MultiplyPoint3x4(vv[set[si]]);
            cx += w.x; cz += w.z;
        }
        cx /= (float)set.Count; cz /= (float)set.Count;
        float total = 0f;
        for (int si = 0; si < set.Count; si++) {
            UnityEngine.Vector3 w = m.MultiplyPoint3x4(vv[set[si]]);
            total += UnityEngine.Mathf.Sqrt((w.x - cx) * (w.x - cx) + (w.z - cz) * (w.z - cz));
        }
        return 2f * total / (float)set.Count;
    };

float rimDiameterAtPick = ringDiameterOf(bindVerts, UnityEngine.Matrix4x4.identity, rimSet);

System.Text.StringBuilder blendSb = new System.Text.StringBuilder();
blendSb.Append("[");
for (int bsi = 0; bsi < sharedMesh.blendShapeCount; bsi++) {
    if (bsi > 0) blendSb.Append(",");
    blendSb.Append("\"" + Esc(sharedMesh.GetBlendShapeName(bsi)) + "\"");
}
blendSb.Append("]");

// GetBonesPerVertex() returns a NativeArray<byte> holding NATIVE memory -
// read with a plain indexed loop and Dispose() before it goes out of
// scope, once here, never per-sample.
Unity.Collections.NativeArray<byte> bonesPerVertex = sharedMesh.GetBonesPerVertex();
int bonesPerVertexMax = 0;
for (int bpi = 0; bpi < bonesPerVertex.Length; bpi++) {
    int v = (int)bonesPerVertex[bpi];
    if (v > bonesPerVertexMax) bonesPerVertexMax = v;
}
bonesPerVertex.Dispose();

UnityEngine.Object.DestroyImmediate(infoInstance);

// --- Per-clip deformed measurements, one fresh instance per clip. ---
System.Collections.Generic.List<string> uniqueClipList = new System.Collections.Generic.List<string>();
for (int ri = 0; ri < reqClip.Length; ri++) {
    if (!uniqueClipList.Contains(reqClip[ri])) uniqueClipList.Add(reqClip[ri]);
}
string[] uniqueClipNames = uniqueClipList.ToArray();

System.Text.StringBuilder samplesSb = new System.Text.StringBuilder();
samplesSb.Append("[");
bool firstSample = true;

for (int uci = 0; uci < uniqueClipNames.Length; uci++) {
    string wantClip = uniqueClipNames[uci];
    UnityEngine.AnimationClip clip = null;
    for (int ci = 0; ci < clips.Length; ci++) {
        if (clips[ci].name == wantClip) { clip = clips[ci]; break; }
    }
    if (clip == null) continue;   // absence is verify()'s job to report

    UnityEngine.GameObject instance = UnityEngine.Object.Instantiate(mainAsset);
    UnityEngine.SkinnedMeshRenderer smr = instance.GetComponentInChildren<UnityEngine.SkinnedMeshRenderer>(true);
    UnityEngine.Mesh baked = new UnityEngine.Mesh();

    for (int ri = 0; ri < reqClip.Length; ri++) {
        if (reqClip[ri] != wantClip) continue;

        // Pose the rig, then read what the renderer ACTUALLY DRAWS -
        // skinning and blend shapes both applied. This is the entire
        // point: the byte gate already proved the FBX declares a skin
        // cluster and two blend-shape channels without proving Unity's
        // renderer moves a single vertex because of them.
        clip.SampleAnimation(instance, reqTime[ri]);
        smr.BakeMesh(baked);
        UnityEngine.Vector3[] verts = baked.vertices;
        UnityEngine.Matrix4x4 l2w = smr.transform.localToWorldMatrix;
        UnityEngine.Vector3 apexW = centroidOf(verts, l2w, apexSet);
        UnityEngine.Vector3 tipW = centroidOf(verts, l2w, tipSet);
        float apexToTip = UnityEngine.Vector3.Distance(apexW, tipW);
        float rimDiameter = ringDiameterOf(verts, l2w, rimSet);

        if (!firstSample) samplesSb.Append(",");
        firstSample = false;
        samplesSb.Append("{\"clip\":\"" + Esc(wantClip) + "\",\"frame\":" + reqFrame[ri]
                         + ",\"rim_diameter\":" + Num(rimDiameter)
                         + ",\"apex_to_tip\":" + Num(apexToTip) + "}");
    }

    UnityEngine.Object.DestroyImmediate(instance);
}
samplesSb.Append("]");

System.Text.StringBuilder clipsSb = new System.Text.StringBuilder();
clipsSb.Append("[");
for (int ci = 0; ci < clips.Length; ci++) {
    if (ci > 0) clipsSb.Append(",");
    clipsSb.Append("{\"name\":\"" + Esc(clips[ci].name) + "\",\"length\":" + Num(clips[ci].length)
    + ",\"is_looping\":" + (clips[ci].isLooping ? "true" : "false") + "}");
}
clipsSb.Append("]");

System.Text.StringBuilder outSb = new System.Text.StringBuilder();
outSb.Append("{");
outSb.Append("\"bones\":" + bones + ",");
outSb.Append("\"blend_shapes\":" + blendSb.ToString() + ",");
outSb.Append("\"clips\":" + clipsSb.ToString() + ",");
outSb.Append("\"bones_per_vertex_max\":" + bonesPerVertexMax + ",");
outSb.Append("\"samples\":" + samplesSb.ToString() + ",");
// Diagnostics only - verify() does not read these. rim_candidates/
// rim_diameter_at_pick let the report compare Unity's independently
// re-derived rim pick against Maya's own (baseline.json's landmarks).
outSb.Append("\"landmark_sizes\":{\"apex\":" + apexSet.Count + ",\"tip\":" + tipSet.Count
    + ",\"rim\":" + rimSet.Count + "},");
outSb.Append("\"landmark_sizes_before_dedupe\":{\"apex\":" + apexRaw + ",\"tip\":" + tipRaw
    + ",\"rim\":" + rimRaw + "},");
outSb.Append("\"landmark_rim_candidates\":" + rimSet.Count + ",");
outSb.Append("\"landmark_rim_diameter_at_pick\":" + Num(rimDiameterAtPick) + ",");
outSb.Append("\"mesh_vertex_count\":" + bindVerts.Length);
outSb.Append("}");

System.IO.File.WriteAllText(outputPath, outSb.ToString());

string summary = "wrote " + reqClip.Length + " sample(s) across " + uniqueClipNames.Length
    + " clip(s) to " + outputPath + " (bones=" + bones + " blend_shapes=" + sharedMesh.blendShapeCount
    + " bones_per_vertex_max=" + bonesPerVertexMax + " rim_candidates=" + rimSet.Count + ")";
UnityEngine.Debug.Log(summary);
return summary;
""".strip("\n")

# --- Importer configuration, driven by the producer's own declaration ----
#
# MEASURED 2026-08-24: every take imports with AnimationClip.isLooping ==
# false. That is NOT a product defect and no change to the FBX can fix it -
# the format has no per-take loop flag, so "this clip loops" cannot travel
# in the bytes at all. It is a CONSUMER configuration step, and the point
# of running it here is that the configuration is derived from
# baseline.json's own `looping_clips` rather than hand-set in the editor:
# if a clip were renamed, or the producer's loop declaration drifted, the
# importer config would silently fail to match and the measurement step
# would then catch it.
#
# Read defaultClipAnimations, mutate, assign back: clipAnimations starts
# EMPTY on a fresh importer and assigning an empty array wipes the takes.
_UNITY_CONFIGURE_TEMPLATE = r"""
string modelPath = "__ASSET_PATH__";
string[] loopNames = new string[] { __LOOPING_CLIPS__ };
UnityEditor.ModelImporter mi = (UnityEditor.ModelImporter)UnityEditor.AssetImporter.GetAtPath(modelPath);
if (mi == null) { return "NO IMPORTER at " + modelPath; }
mi.importAnimation = true;
UnityEditor.ModelImporterClipAnimation[] clips = mi.defaultClipAnimations;
if (clips == null || clips.Length == 0) { return "NO TAKES on " + modelPath; }
System.Text.StringBuilder sb = new System.Text.StringBuilder();
for (int i = 0; i < clips.Length; i++) {
    bool want = false;
    for (int j = 0; j < loopNames.Length; j++) {
        if (clips[i].name == loopNames[j]) { want = true; break; }
    }
    clips[i].loopTime = want;
    sb.Append(clips[i].name + "=" + (want ? "loop" : "once") + " ");
}
mi.clipAnimations = clips;
UnityEditor.EditorUtility.SetDirty(mi);
mi.SaveAndReimport();
return "configured " + clips.Length + " takes: " + sb.ToString();
"""

UNITY_CONFIGURE_CS = (_UNITY_CONFIGURE_TEMPLATE
                      .replace("__ASSET_PATH__", ASSET_PATH)
                      .replace("__LOOPING_CLIPS__",
                               ", ".join('"%s"' % c
                                         for c in DECLARED["looping_clips"])))


UNITY_MEASURE_CS = (_UNITY_MEASURE_TEMPLATE
                     .replace("__ASSET_PATH__", ASSET_PATH)
                     .replace("__RIM_Y__", "%.17gf" % _RIM_Y)
                     .replace("__RIM_RADIUS_MIN__", "%.17gf" % _RIM_RADIUS_MIN)
                     .replace("__RIM_BAND_HALF__", "%.17gf" % _RIM_BAND_HALF)
                     .replace("__TIP_BAND__", "%.17gf" % _TIP_BAND)
                     .replace("__APEX_BAND__", "%.17gf" % _APEX_BAND)
                     .replace("__QUANTUM__", "%.17gf" % _QUANTUM)
                     .replace("__BAND_WIDEN__", "%.17gf" % BAND_WIDEN)
                     .replace("__APEX_N__", str(MAYA_LANDMARK_SIZES["apex"]))
                     .replace("__TIP_N__", str(MAYA_LANDMARK_SIZES["tip"]))
                     .replace("__RIM_N__", str(MAYA_LANDMARK_SIZES["rim"]))
                     .replace("__SAMPLE_CLIPS__", _cs_string_array(_SAMPLE_CLIPS))
                     .replace("__SAMPLE_FRAMES__", _cs_int_array(_SAMPLE_FRAMES))
                     .replace("__SAMPLE_TIMES__", _cs_float_array(_SAMPLE_TIMES)))


def _steps_text() -> str:
    clip_names = ", ".join(repr(c["name"]) for c in DECLARED["clips"])
    return """\
#743 Unity consumer gate - steps to run (unityMCP tools, in order)

If the Unity editor is not open, or `claude mcp list` shows unityMCP
unhealthy: STOP here and report that. Do not fall back to a CLI batchmode
run (CLAUDE.md, "MCP is the PRIMARY tooling path").

Target a SCRATCH Unity project, never Demigol's.

Declared clips (from %s): %s
FBX to import: %s
Destination in the scratch project: %s

 1. mcp__unityMCP__set_active_instance
    Pin the scratch project's instance BEFORE any other call - several
    Unity instances may be connected at once, and an unpinned call with
    more than one connected errors rather than guessing. List candidates
    via the mcpforunity://instances resource; pass its Name@hash (or a
    hash/port prefix) as `instance`.

 2. mcp__unityMCP__manage_editor(action="telemetry_ping")
    Confirms the pinned editor actually answers before anything else
    touches its project - if this fails or times out, STOP and report it.

 3. Copy %s into <scratch project>/%s
    Plain filesystem copy, done directly by the agent - no unityMCP tool
    uploads a local file into a project without also importing it in the
    same step.

 4. mcp__unityMCP__refresh_unity(scope="assets", compile="none")
    Makes Unity notice the new file under Assets/.

 5. mcp__unityMCP__manage_asset(action="modify", path=%r,
        properties={"importAnimation": true})
    then mcp__unityMCP__manage_asset(action="import", path=%r)
    Turns animation import ON and forces a reimport under the new
    setting - harmless if it was already on, but nothing here can assume
    a scratch project starts the same way a consuming project's importer
    is configured.

 6. mcp__unityMCP__execute_code(action="execute", code=UNITY_MEASURE_CS)
    Runs the measurement (this module's UNITY_MEASURE_CS constant). It
    WRITES the JSON object described in verify()'s docstring to a file
    (outputPath inside the C#, computed as
    "<project root>/drifter_unity_measurement.json", a sibling of the
    project's Assets/ folder) and returns only a short one-line summary -
    the full JSON is not worth returning through the tool call.

    execute_code reports which backend it compiled with - confirm it says
    CodeDom (not Roslyn) before trusting a failure as a real defect rather
    than a C# 6 syntax mismatch.

 7. Copy that file locally (if the scratch project is remote) and verify
    it:
    uv run python evals/drifter_unity.py --measurements <path to the JSON>
""" % (os.path.basename(BASELINE_PATH), clip_names, FBX_PATH, ASSET_PATH,
       FBX_PATH, ASSET_PATH, ASSET_PATH, ASSET_PATH)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="#743 consumer gate: verify a real Unity's deformed "
                    "read of the drifter FBX against Maya's declared "
                    "baseline.")
    parser.add_argument(
        "--measurements", metavar="PATH",
        help="JSON file holding UNITY_MEASURE_CS's written measurement. "
            "When given, verify it and exit 0/1. When omitted, print the "
            "unityMCP steps to run and exit 0.")
    args = parser.parse_args(argv)

    if args.measurements is None:
        print(_steps_text())
        return 0

    with open(args.measurements, "r", encoding="utf-8") as fh:
        measured = json.load(fh)

    out = verify(DECLARED, measured)
    if not out["ok"]:
        print("FAIL: %d problem(s):" % len(out["problems"]))
        for p in out["problems"]:
            print("  - %s" % p)
        print()
        print("detail: %s" % json.dumps(out["detail"], indent=2))
        return 1

    print("PASS: Unity's import matches the declared baseline.")
    print("detail: %s" % json.dumps(out["detail"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
