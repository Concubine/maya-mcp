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
_MAYA_RIM = [int(i) for i in _LANDMARKS["rim"]]
if len(_MAYA_RIM) != 2:
    raise SystemExit("landmarks.rim must carry exactly 2 vertex indices "
                     "(the farthest pair), got %d" % len(_MAYA_RIM))
MAYA_RIM_DIAMETER_AT_PICK = float(_LANDMARKS["rim_diameter_at_pick"])

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
float rimBandHalfWidth = 0.06f;   // drifter_live.py's own band tolerance

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

// --- Landmarks, re-derived on Unity's OWN bind-pose vertices - see the
// header comment above this template. apex/tip are the single global
// max/min-Y vertex; rim is the farthest pair among candidates within
// rimBandHalfWidth of rimY and farther than rimRadiusMin from the vertical
// axis - the exact rule drifter_live.py's _find_landmarks uses in Maya,
// just run here instead of trusted to carry an index across the import. ---
UnityEngine.Vector3[] bindVerts = sharedMesh.vertices;
int apexIdx = 0;
int tipIdx = 0;
for (int vi = 1; vi < bindVerts.Length; vi++) {
    if (bindVerts[vi].y > bindVerts[apexIdx].y) apexIdx = vi;
    if (bindVerts[vi].y < bindVerts[tipIdx].y) tipIdx = vi;
}
System.Collections.Generic.List<int> rimCandidates = new System.Collections.Generic.List<int>();
for (int vi = 0; vi < bindVerts.Length; vi++) {
    UnityEngine.Vector3 p = bindVerts[vi];
    float radius = UnityEngine.Mathf.Sqrt(p.x * p.x + p.z * p.z);
    if (UnityEngine.Mathf.Abs(p.y - rimY) < rimBandHalfWidth && radius > rimRadiusMin) {
        rimCandidates.Add(vi);
    }
}
int rim0Idx = rimCandidates.Count > 0 ? rimCandidates[0] : 0;
int rim1Idx = rimCandidates.Count > 1 ? rimCandidates[1] : 0;
float rimDiameterAtPick = 0f;
for (int a = 0; a < rimCandidates.Count; a++) {
    int ia = rimCandidates[a];
    for (int b = a + 1; b < rimCandidates.Count; b++) {
        int ib = rimCandidates[b];
        float d = UnityEngine.Vector3.Distance(bindVerts[ia], bindVerts[ib]);
        if (d > rimDiameterAtPick) { rimDiameterAtPick = d; rim0Idx = ia; rim1Idx = ib; }
    }
}

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
        UnityEngine.Vector3 apexW = l2w.MultiplyPoint3x4(verts[apexIdx]);
        UnityEngine.Vector3 tipW = l2w.MultiplyPoint3x4(verts[tipIdx]);
        UnityEngine.Vector3 rim0W = l2w.MultiplyPoint3x4(verts[rim0Idx]);
        UnityEngine.Vector3 rim1W = l2w.MultiplyPoint3x4(verts[rim1Idx]);
        float apexToTip = UnityEngine.Vector3.Distance(apexW, tipW);
        float rimDiameter = UnityEngine.Vector3.Distance(rim0W, rim1W);

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
    clipsSb.Append("{\"name\":\"" + Esc(clips[ci].name) + "\",\"length\":" + Num(clips[ci].length) + "}");
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
outSb.Append("\"landmark_indices\":{\"apex\":" + apexIdx + ",\"tip\":" + tipIdx
    + ",\"rim0\":" + rim0Idx + ",\"rim1\":" + rim1Idx + "},");
outSb.Append("\"landmark_rim_candidates\":" + rimCandidates.Count + ",");
outSb.Append("\"landmark_rim_diameter_at_pick\":" + Num(rimDiameterAtPick) + ",");
outSb.Append("\"mesh_vertex_count\":" + bindVerts.Length);
outSb.Append("}");

System.IO.File.WriteAllText(outputPath, outSb.ToString());

string summary = "wrote " + reqClip.Length + " sample(s) across " + uniqueClipNames.Length
    + " clip(s) to " + outputPath + " (bones=" + bones + " blend_shapes=" + sharedMesh.blendShapeCount
    + " bones_per_vertex_max=" + bonesPerVertexMax + " rim_candidates=" + rimCandidates.Count + ")";
UnityEngine.Debug.Log(summary);
return summary;
""".strip("\n")

UNITY_MEASURE_CS = (_UNITY_MEASURE_TEMPLATE
                     .replace("__ASSET_PATH__", ASSET_PATH)
                     .replace("__RIM_Y__", "%.17gf" % _RIM_Y)
                     .replace("__RIM_RADIUS_MIN__", "%.17gf" % _RIM_RADIUS_MIN)
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
