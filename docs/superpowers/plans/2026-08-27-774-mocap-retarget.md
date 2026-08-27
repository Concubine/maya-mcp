# Mocap Retargeting (#774) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two new tools — `maya_retarget_clip` (local BVH/FBX mocap file + biped root → baked named clip, HIK state fully internal) and `maya_clean_clip` (deterministic filter + contact-lock passes with before/after numbers) — proven by a live gate whose thresholds are chosen by measurement.

**Architecture:** A pure module `mocapmath.py` (BVH parser, characterization-map validation, filter math — no Maya imports) under two Maya-bound handlers: `retarget.py` (parse → build source skeleton → HIK characterize both ends from fixed tables → retarget → bake → tear down → self-measure) and `cleanclip.py` (filter + contact-locked IK reusing `motionmath.contact_runs`). Baked clips register through the SAME metadata path `author_clip` uses, so preview/measure/delete/export work unchanged.

**Tech Stack:** Python (Maya 2027 `maya.cmds` + MEL HumanIK commands + `maya.api.OpenMaya`), pytest headless + mayapy suite, FastMCP server.

**Spec:** `docs/superpowers/specs/2026-08-27-mocap-retarget-design.md` — read it first.

## Global Constraints

- Worktree trap: in a worktree, pytest imports the PRIMARY checkout via the editable install. Run headless tests with `PYTHONPATH="src;."` and verify `import maya_mcp` resolves to the worktree before trusting results.
- Two-Maya policy: the user's Maya is on **9877 — never touch it**. Live work uses a disposable agent Maya on **9878**; launch (bash): `MAYA_MCP_PORT=9878 "E:/Autodesk/Maya2027/bin/maya.exe" &`, poll the port; kill only a pid PROVEN via `netstat -ano | findstr 9878`.
- Live Maya loads the plugin from Documents/maya/scripts: `.venv/Scripts/python.exe maya_plugin/install.py --yes` (from the worktree) + restart the 9878 Maya before ANY live run. `evals/live_call.py` defaults to 9878 and warns on staleness — never silence it.
- Suites measured with `--junitxml` (stdout buffering eats the summary line). Baselines at plan time: headless **1731 total / 1 skipped**, mayapy **190 total / 1 skipped**. mayapy is `E:\Autodesk\Maya2027\bin\mayapy.exe`.
- MSpace/OpenMaya keyword trap: pass `space=` as a KEYWORD to OpenMaya calls.
- Commit style `feat(#774):` / `test(#774):` / `probe(#774):`, Claude co-author line.
- Overnight authorizations (user, 2026-08-27): subagent-driven execution; merge to main + mark #774 Resolved when both suites AND the live gate are green; **if the probe shows HumanIK cannot be driven scriptably, fall back to DIRECT retargeting** (per-joint rotation mapping through the fixed characterization tables with T-pose offset correction — same tool surface, same gate) and record the substitution in spec + ticket. The user's Maya was CLOSED at plan time; if a 9877 listener appears mid-run, it is the user — leave it alone.
- Spec bounds: humanoid bipeds only; no network in the tool surface (dev-time fixture download is allowed, see Task 2); ML enhancement out of scope.
- Another agent's territory: never touch `evals/golem_rerun_665/out_v4/`.

## File Structure

| File | Responsibility |
|---|---|
| `evals/mocap_probe_774.py` (new) | mayapy probe: HIK scriptability (plugin, MEL commands, characterize→retarget→bake→teardown loop), `clipmath.FPS_UNITS` contents, BVH-source skeleton build. Throwaway-quality, kept for provenance. |
| `evals/mocap_fixtures/` (new) | 1 walk + 1 idle CMU BVH clip + `ATTRIBUTION.md`. Committed test inputs. |
| `maya_plugin/handlers/mocapmath.py` (new) | Pure: BVH parser, characterization tables + validation, filter math, blend windows. No Maya imports. |
| `maya_plugin/handlers/retarget.py` (new) | `retarget_clip` handler: parse/import → source skeleton → characterize → retarget → bake → teardown → register clip → self-measure. |
| `maya_plugin/handlers/cleanclip.py` (new) | `clean_clip` handler: checkpoint → filter pass → contact-lock pass → re-bake → before/after numbers. |
| `maya_plugin/handlers/clip.py` (modify) | Extract the clip-metadata registration into a shared helper both `author_clip` and `retarget_clip` call (ONE copy of the record-writing code). |
| `maya_plugin/maya_mcp_plugin.py` (modify) | Register `"retarget_clip"` and `"clean_clip"` in the handler table. |
| `src/maya_mcp/schemas.py` + `server.py` (modify) | `RetargetClipResult`, `CleanClipResult`; tools `maya_retarget_clip`, `maya_clean_clip`. |
| `tests/test_mocapmath.py` (new) | Headless: parser, maps, filters in full. |
| `tests/test_retarget.py` (new) | Headless: both handlers' Maya-free refusals + wire-shape regression tests. |
| `tests/test_handlers_mayapy.py` (modify) | Real-geometry: retarget the fixture walk, teardown proof, clean_clip before/after. |
| `tests/test_server_tools.py` (modify) | Tool list + forward tests. |
| `evals/retarget_live.py` (new) | The live gate: thresholds by measurement, two discriminations, #718 export composition, preview sheet. |

---

### Task 1: Probe — can this Maya's HumanIK be driven blind?

**Files:**
- Create: `evals/mocap_probe_774.py`

**Interfaces:**
- Consumes: mayapy; `maya_plugin.handlers.rigging.create_skeleton` (read `evals/humanoid_live.py` first for the exact params that build a biped).
- Produces: `PROBE <name>: <value>` lines that Task 3 turns into constants — the HIK plugin name, the working MEL/cmds invocations for create-character / set-slot / set-source / bake, the node types a characterization creates (for teardown), and `clipmath.FPS_UNITS` membership (does it contain 120? CMU captures at 120 fps).

The spec names this the riskiest unknown: HumanIK's scripting surface is MEL-era and may assume a GUI. #768's probe caught three landmines before they cost anything; same method here.

- [ ] **Step 1: Write the probe.** Structure (follow `evals/curveform_probe_768.py`'s probe()-prints-facts style; every section wrapped so one failure cannot hide another section's facts — catch `Exception`, print it, continue):

```python
"""#774 probe: can HumanIK characterize/retarget/bake be driven from script?

Run:  E:\\Autodesk\\Maya2027\\bin\\mayapy.exe evals/mocap_probe_774.py
(from the worktree root, PYTHONPATH="src;." so repo code imports)
Facts, not assertions: a surprising value changes Task 3's constants.
"""
```

Sections, in order:
1. `maya.standalone.initialize`; `cmds.loadPlugin("mayaHIK", quiet=True)` in try/except, then `probe("hik_plugin_loaded", cmds.pluginInfo("mayaHIK", query=True, loaded=True))`. Also try `"mayaHIK.mll"` and probe `[p for p in cmds.pluginInfo(query=True, listPlugins=True) or [] if "hik" in p.lower()]`. Some HIK MEL lives in `"OneClick"` / requires `mel.eval('HIKCharacterControlsTool')` — probe whether that MEL proc exists but do NOT require it (it is UI).
2. MEL existence sweep: `mel.eval('exists "<name>"')` over the candidate list `hikCreateCharacter`, `hikCreateDefinition`, `setCharacterObject`, `hikToggleLockDefinition`, `hikSetCurrentCharacter`, `hikSetCharacterInput`, `mayaHIKsetCharacterInput`, `hikBakeCharacter`, `hikNoneCharacter`, `hikUpdateDefinitionUI` — print each. Also `cmds.ls(nodeTypes=True)`-style check: probe that node types `HIKCharacterNode`, `HIKRetargeterNode`, `HIKSolverNode`, `HIKState2SK` exist via `cmds.nodeType(isTypeName=True, ...)` in try/except.
3. `probe("fps_units", sorted(clipmath.FPS_UNITS))` (import from repo).
4. Build TARGET biped: call `rigging.create_skeleton` with the same params `evals/humanoid_live.py` uses (copy them). Print the joint names returned.
5. Build SOURCE skeleton by hand with `cmds.joint` — a minimal CMU-shaped biped (Hips → Spine → Spine1 → Neck → Head; Hips → L/RHipJoint → L/RUpLeg → L/RLeg → L/RFoot; Spine1 → L/RShoulder → L/RArm → L/RForeArm → L/RHand), ~30cm offsets, and key `Hips.translateX` from 0 to 10 over frames 1-30 plus `LeftUpLeg.rotateZ` 0→40 — enough motion to measure whether retargeting transferred anything.
6. THE CORE LOOP, each sub-step probed: create a character definition for the target (`mel.eval('hikCreateCharacter("probeTarget")')` or whatever step 2 found), assign slots via `setCharacterObject("<joint>", "probeTarget", <slotId>, 0)` for the 15 required slots (Reference=0, Hips=1, LeftUpLeg=2, LeftLeg=3, LeftFoot=4, RightUpLeg=5, RightLeg=6, RightFoot=7, Spine=8, LeftArm=9, LeftForeArm=10, LeftHand=11, RightArm=12, RightForeArm=13, RightHand=14, Head=15 — probe by reading `mel.eval('hikGetNodeCount()')`-style introspection if present, else use these classic ids and MEASURE whether characterization locks), lock the definition, repeat for the source, set source as the target's input, sample frame 15: probe the target Hips' world position BEFORE and AFTER input assignment — a changed position IS retargeting working.
7. Bake: `hikBakeCharacter` (or `cmds.bakeResults` over the target joints for the frame range) — probe that the target joints now carry keyframes (`cmds.keyframe(j, query=True, keyframeCount=True)`).
8. Teardown census: `set(cmds.ls(long=True))` before the whole HIK section vs after deleting the HIK character nodes + source skeleton — probe the leftover node list (this becomes Task 3's teardown checklist).
9. `probe("done", True)`.

- [ ] **Step 2: Run it.** `E:\Autodesk\Maya2027\bin\mayapy.exe evals/mocap_probe_774.py` (worktree root, PYTHONPATH set). Expected: every PROBE line prints. THE decision fact is section 6: did the target move when the source was assigned as input?
- [ ] **Step 3: Decide the route and record it.** If retargeting transferred motion scriptably → HIK route confirmed; paste the full PROBE output into the commit body. If HIK is genuinely unscriptable here (plugin absent, or characterization cannot lock, or input assignment moves nothing) → the DIRECT fallback is pre-authorized: record the measured failure in the commit body and in the ledger, and Task 3 builds the direct retargeter instead (its design is in Task 3, Route B). Either way this task ends with a committed probe and a recorded route decision — not a stall.
- [ ] **Step 4: Commit.** `git add evals/mocap_probe_774.py` ; `git commit -m "probe(#774): HIK scriptability measured - route decided"`.

---

### Task 2: `mocapmath` — BVH parser, characterization tables, filter math

**Files:**
- Create: `maya_plugin/handlers/mocapmath.py`
- Create: `evals/mocap_fixtures/` (2 CMU clips + ATTRIBUTION.md)
- Test: `tests/test_mocapmath.py`

**Interfaces:**
- Consumes: `HandlerError` from `maya_plugin.dispatcher`. Nothing from Task 1.
- Produces (exact signatures Tasks 3/5 call):
  - `parse_bvh(text: str) -> dict` — `{"joints": [{"name", "parent" (index|None), "offset" [x,y,z], "channels" [str,...]}], "frame_time": float, "frames": int, "rows": [[float,...]]}`; raises `HandlerError` naming the line number on malformed input.
  - `fps_from_frame_time(frame_time: float, allowed: set) -> int` — nearest integer fps if within 1% of an allowed unit, else `HandlerError` listing the allowed units.
  - `CMU_HIK_MAP` / `SKELETON_HIK_MAP` — dicts `{hik_slot_name: joint_name}` for the CMU BVH naming and our `create_skeleton` biped naming (#668). The 15 required slot names as keys: `Hips, LeftUpLeg, LeftLeg, LeftFoot, RightUpLeg, RightLeg, RightFoot, Spine, LeftArm, LeftForeArm, LeftHand, RightArm, RightForeArm, RightHand, Head`.
  - `resolve_hik_map(joint_names: list, table: dict) -> dict` — validates every required slot resolves to a present joint; `HandlerError` NAMES the missing slots and the unmatched joints (never guesses).
  - `smooth_track(values: list, window: int, order: int = 2) -> list` — Savitzky–Golay via stdlib-only least squares (precomputed convolution weights for the given window/order), endpoints handled by shrinking the window; refuses even windows and window < 5.
  - `blend_weights(n: int, edge: int) -> list` — 0→1→0 cosine ramp weights for contact-run edge blending.
- The fixture files: exact acquisition procedure in Step 1.

- [ ] **Step 1: Acquire fixtures.** Download TWO small CMU BVH clips from the CMU archive or the cgspeed BVH conversion mirrors (a walk, e.g. subject 07 trial 01; an idle/stand, e.g. subject 02) into `evals/mocap_fixtures/cmu_walk.bvh` and `cmu_idle.bvh`. Verify each parses (after Step 5) and is < 2 MB. Write `evals/mocap_fixtures/ATTRIBUTION.md`: source (CMU Graphics Lab Motion Capture Database, mocap.cs.cmu.edu), the funding acknowledgment the database requests, subject/trial numbers, and the conversion provenance. **If no mirror is reachable, do not stall the task**: write `tests/` against the inline synthetic fixture (Step 2) only, note the gap in your report, and the controller arranges the real clips before Task 7 (the gate needs them; the parser does not).
- [ ] **Step 2: Write the failing tests.** `tests/test_mocapmath.py` — include an INLINE minimal BVH (deterministic, no file dependency) plus file-based tests for the fixtures when present:

```python
"""mocapmath is pure - parser, maps, filters, no Maya anywhere."""
import math
import os

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import mocapmath as mm

TINY_BVH = """HIERARCHY
ROOT Hips
{
    OFFSET 0.0 0.0 0.0
    CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation
    JOINT Spine
    {
        OFFSET 0.0 10.0 0.0
        CHANNELS 3 Zrotation Xrotation Yrotation
        End Site
        {
            OFFSET 0.0 10.0 0.0
        }
    }
}
MOTION
Frames: 2
Frame Time: 0.033333
0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
1.0 2.0 3.0 10.0 20.0 30.0 5.0 0.0 0.0
"""


class TestParseBvh:
    def test_tiny_hierarchy_and_rows(self):
        r = mm.parse_bvh(TINY_BVH)
        assert [j["name"] for j in r["joints"]] == ["Hips", "Spine"]
        assert r["joints"][0]["parent"] is None
        assert r["joints"][1]["parent"] == 0
        assert r["joints"][1]["offset"] == [0.0, 10.0, 0.0]
        assert r["joints"][0]["channels"][:3] == [
            "Xposition", "Yposition", "Zposition"]
        assert r["frames"] == 2 and len(r["rows"]) == 2
        assert r["rows"][1][0] == 1.0 and r["rows"][1][3] == 10.0

    def test_row_arity_must_match_channel_total(self):
        bad = TINY_BVH.replace("1.0 2.0 3.0 10.0 20.0 30.0 5.0 0.0 0.0",
                               "1.0 2.0 3.0")
        with pytest.raises(HandlerError, match="line"):
            mm.parse_bvh(bad)

    def test_missing_motion_section_refused(self):
        with pytest.raises(HandlerError, match="MOTION"):
            mm.parse_bvh(TINY_BVH.split("MOTION")[0])

    def test_frames_count_must_match_rows(self):
        bad = TINY_BVH.replace("Frames: 2", "Frames: 3")
        with pytest.raises(HandlerError, match="Frames"):
            mm.parse_bvh(bad)


FIXTURES = os.path.join(os.path.dirname(__file__), "..", "evals",
                        "mocap_fixtures")


@pytest.mark.skipif(
    not os.path.exists(os.path.join(FIXTURES, "cmu_walk.bvh")),
    reason="CMU fixtures not stocked yet")
class TestCmuFixtures:
    def test_walk_parses_and_maps(self):
        with open(os.path.join(FIXTURES, "cmu_walk.bvh")) as fh:
            r = mm.parse_bvh(fh.read())
        assert r["frames"] > 30
        names = [j["name"] for j in r["joints"]]
        mapped = mm.resolve_hik_map(names, mm.CMU_HIK_MAP)
        assert set(mapped) == set(mm.REQUIRED_HIK_SLOTS)


class TestFps:
    def test_120_and_30_frame_times(self):
        assert mm.fps_from_frame_time(1.0 / 120.0, {30, 60, 120}) == 120
        assert mm.fps_from_frame_time(0.033333, {30, 60}) == 30

    def test_unmatched_frame_time_refused(self):
        with pytest.raises(HandlerError, match="frame time"):
            mm.fps_from_frame_time(0.0417, {30, 60})  # 24 not allowed


class TestHikMap:
    def test_missing_slots_are_named(self):
        with pytest.raises(HandlerError) as exc:
            mm.resolve_hik_map(["Hips", "Spine"], mm.CMU_HIK_MAP)
        assert "LeftFoot" in str(exc.value)

    def test_skeleton_map_covers_required_slots(self):
        assert set(mm.REQUIRED_HIK_SLOTS) <= set(mm.SKELETON_HIK_MAP)
        assert set(mm.REQUIRED_HIK_SLOTS) <= set(mm.CMU_HIK_MAP)


class TestSmoothTrack:
    def test_preserves_linear_signal(self):
        line = [float(i) for i in range(20)]
        assert mm.smooth_track(line, window=5) == pytest.approx(line)

    def test_attenuates_alternating_noise(self):
        noisy = [i + (0.5 if i % 2 else -0.5) for i in range(40)]
        out = mm.smooth_track(noisy, window=7)
        resid = [abs(o - i) for i, o in enumerate(out)][3:-3]
        assert max(resid) < 0.25

    def test_even_or_tiny_window_refused(self):
        with pytest.raises(HandlerError, match="window"):
            mm.smooth_track([1.0] * 10, window=4)
        with pytest.raises(HandlerError, match="window"):
            mm.smooth_track([1.0] * 10, window=3)


class TestBlendWeights:
    def test_ramps_zero_to_one_to_zero(self):
        w = mm.blend_weights(10, edge=3)
        assert w[0] == pytest.approx(0.0)
        assert max(w) == pytest.approx(1.0)
        assert w[-1] == pytest.approx(0.0)
        assert w == pytest.approx(list(reversed(w)))
```

- [ ] **Step 3: RED.** `PYTHONPATH="src;."` + `D:\devel\maya-mcp\.venv\Scripts\python.exe -m pytest tests/test_mocapmath.py -q` → collection error (module absent).
- [ ] **Step 4: Implement `mocapmath.py`.** House style: why-first module docstring citing #774; every refusal names the input and carries a hint with a working example. `REQUIRED_HIK_SLOTS` is the 15-name tuple. `CMU_HIK_MAP` uses the cgspeed/CMU BVH names (`Hips, LeftUpLeg (or LHipJoint→LeftUpLeg chain — map by the names ACTUALLY in the fixture, adjusting the table to what `cmu_walk.bvh` contains and noting any alias entries), ...`); `SKELETON_HIK_MAP` uses the `create_skeleton` biped names (read `evals/humanoid_live.py` / `rigmath.py` for the canonical list). Parser: two-phase (hierarchy stack walk, then MOTION rows), tracking line numbers for every refusal.
- [ ] **Step 5: GREEN** on test_mocapmath.py, then the FULL headless suite once (`-q --junitxml`, read count, delete xml).
- [ ] **Step 6: Commit.** `git add maya_plugin/handlers/mocapmath.py tests/test_mocapmath.py evals/mocap_fixtures/` ; `git commit -m "feat(#774): mocapmath - BVH parser, HIK maps, filter math + CMU fixtures"`.

---

### Task 3: `retarget_clip` handler + shared clip registration

**Files:**
- Create: `maya_plugin/handlers/retarget.py`
- Modify: `maya_plugin/handlers/clip.py` (extract shared registration helper)
- Modify: `maya_plugin/maya_mcp_plugin.py` (register `"retarget_clip"`)
- Test: `tests/test_retarget.py`

**Interfaces:**
- Consumes: `mocapmath.parse_bvh/fps_from_frame_time/resolve_hik_map/CMU_HIK_MAP/SKELETON_HIK_MAP/REQUIRED_HIK_SLOTS`; Task 1's probed HIK invocations (constants at the top of retarget.py, one place, commented "Measured by evals/mocap_probe_774.py"); `clip.py`'s `NAME_RE`, `clipmath.FPS_UNITS`, `clip_meta`, and the newly extracted registration helper; `rigging._require_joint`, `_hierarchy_joints`; `session.auto_checkpoint`, `session.stop_idle_ipr`.
- Produces: `retarget_clip(params) -> dict` with keys `{"clip": str, "root": str, "frames": int, "fps": int, "source_joints": int, "measures": {<measure_clip summary numbers>}, "warnings": [...]}`; plugin command `"retarget_clip"`; shared helper `clip.register_clip(cmds, root_long, name, fps, start, end, loop=False) -> None` (exact record shape = what `author_clip` writes today — extraction, not invention).

- [ ] **Step 1: Extract the registration helper.** Read `author_clip` end-to-end. Move the clip-metadata record-writing block into `register_clip(...)` (module-level in clip.py), call it from `author_clip` unchanged. Run `tests/test_clip.py` + `tests/test_clipmath.py` headless → must stay green (pure refactor, zero behavior change).
- [ ] **Step 2: Write the failing headless tests.** `tests/test_retarget.py` — Maya-free refusals only (the pattern proven in #768: these tests RUNNING headless is the proof validation precedes Maya):

```python
"""retarget_clip refusals that never touch Maya."""
import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import retarget


def base(**over):
    p = {"file": "evals/mocap_fixtures/cmu_walk.bvh", "root": "|rig|Hips",
         "clip": "walk01"}
    p.update(over)
    return p


class TestParamGate:
    def test_unknown_key_refused_with_synonym(self):
        with pytest.raises(HandlerError, match="'path' is called 'file'"):
            retarget.retarget_clip({**base(), "path": "x.bvh"})

    def test_missing_file_param_refused(self):
        p = base(); del p["file"]
        with pytest.raises(HandlerError, match="file"):
            retarget.retarget_clip(p)

    def test_nonexistent_file_refused_before_maya(self):
        with pytest.raises(HandlerError, match="no such file"):
            retarget.retarget_clip(base(file="evals/mocap_fixtures/nope.bvh"))

    def test_unsupported_extension_refused(self):
        with pytest.raises(HandlerError, match=r"\.bvh or \.fbx"):
            retarget.retarget_clip(base(file="evals/live_call.py"))

    def test_bad_clip_name_refused(self):
        with pytest.raises(HandlerError, match="identifier"):
            retarget.retarget_clip(base(clip="2 bad name"))

    def test_bad_range_refused(self):
        with pytest.raises(HandlerError, match="start"):
            retarget.retarget_clip(base(start=50, end=10))
```

(Adjust the file-exists test to a path guaranteed absent; the fixture path itself must NOT be read before cheaper validations — order: keys → clip name → extension → existence.)
- [ ] **Step 3: RED**, then implement `retarget.py`:
  - `RETARGET_CLIP_KEYS = ("file", "root", "clip", "start", "end", "fps")`, synonyms `{"path": "file", "bvh": "file", "name": "clip", "take": "clip", "target": "root", "skeleton": "root"}`. `require_known_keys` on ORIGINAL params.
  - Pure phase (no Maya): validate name via `clip.NAME_RE`, extension, file existence + read + `parse_bvh` for `.bvh` (parse BEFORE any scene touch — a malformed file costs nothing), fps resolution: source fps from `fps_from_frame_time(frame_time, clipmath.FPS_UNITS)`; the `fps` param (default 30, validated against `FPS_UNITS`) is the BAKE rate.
  - Maya phase, inside try/finally over a `temp_nodes` census (the #768 discipline — on ANY exit delete every node the call created except the baked keys): `_require_joint(root)`; `resolve_hik_map` on the target's `_hierarchy_joints` short names with `SKELETON_HIK_MAP` (refusal NAMES missing slots → "target is not a biped this tool can characterize"); guard rails from `author_clip` reused: `stop_idle_ipr`, hand-authored-curve refusal, fps conflict via `clip_meta` + `clipmath.fps_conflict`, one-rig-carries-clips warning; `session.auto_checkpoint("retarget_clip")`.
  - **FBX sources** (the other accepted extension, per the spec): skip the parse phase; import natively (`cmds.file(path, i=True, namespace="mocap_src_<clip>", type="FBX")`) inside the Maya phase, then read the imported joint names and `resolve_hik_map` them — try `CMU_HIK_MAP` first, then `SKELETON_HIK_MAP`; if neither resolves, refuse naming the unmatched joints (never guess). Frame range from the imported keys (`cmds.keyframe(query=True, keyframeCount/timeRange)`); fps from the scene's time unit after import.
  - Build the source skeleton from the parse (BVH route; namespace `mocap_src_<clip>`): `cmds.joint` per parsed joint (offsets), then set keyframes per frame row (channel order as parsed; BVH rotation order comes from the channel triplet — apply via `cmds.setAttr` per frame or `cmds.setKeyframe`; respect `start`/`end` trim). Scale: CMU BVH units are decimetre-ish and vary — measure the source's Hips height, measure the target's Hips height, and uniform-scale the source skeleton group so they match (record the factor in the result's warnings if it exceeds 10x either way).
  - **Route A (HIK, if Task 1 confirmed):** characterize target and source from the probed invocations, set source as input, `bakeResults` the target joints over the mapped frame range at the requested bake fps, then delete: source namespace + every HIK node type the probe's teardown census named.
  - **Route B (direct, pre-authorized fallback):** for each of the 15 mapped slot pairs, per bake frame: source joint world rotation × (source T-pose world rotation)⁻¹ × target T-pose world rotation → target joint; Hips also takes translation scaled by the height factor. Set keys with `cmds.setKeyframe`. Same teardown (source namespace only).
  - Either route ends: `clip.register_clip(cmds, root_long, name, bake_fps, start_frame, end_frame)`; self-measure by calling `clip.measure_clip({"root": root, "name": name})` and folding its summary numbers into `result["measures"]`.
- [ ] **Step 4: GREEN** on tests/test_retarget.py + full headless suite. Register the command in `maya_mcp_plugin.py`.
- [ ] **Step 5: mayapy smoke** (throwaway script in the SDD workspace, NOT committed): retarget `cmu_walk.bvh` onto a `create_skeleton` biped (params from `evals/humanoid_live.py`), print the result dict; verify keys exist, `measures` is populated, and `cmds.ls` shows no `mocap_src_*` or HIK nodes after. Include the output in your report. Iterate here until it works — this loop is where the probe's constants prove out.
- [ ] **Step 6: Commit.** `git commit -m "feat(#774): retarget_clip - mocap file to baked clip, nothing else left behind"`.

---

### Task 4: Real-geometry mayapy tests for retarget

**Files:**
- Modify: `tests/test_handlers_mayapy.py` (append `TestRetargetInMaya`)

**Interfaces:**
- Consumes: Task 3's handler; the fixtures; `create_skeleton` biped params (copy from `evals/humanoid_live.py`).
- Produces: the real-Maya proof Task 7 builds on.

- [ ] **Step 1: Write the tests** (append; skip cleanly when fixtures absent, same guard as test_mocapmath.py):

```python
class TestRetargetInMaya:
    def _biped(self):
        # exact create_skeleton params copied from evals/humanoid_live.py
        ...  # (implementer: paste the literal params, not this ellipsis)

    def test_walk_retargets_and_registers_as_clip(self):
        from maya_plugin.handlers import retarget, clip
        root = self._biped()
        result = retarget.retarget_clip({
            "file": "evals/mocap_fixtures/cmu_walk.bvh",
            "root": root, "clip": "cmuwalk"})
        assert result["frames"] > 30
        assert result["measures"]  # self-measured
        # the clip is a REAL phase-6 clip: metadata visible to clip tools
        import maya.cmds as cmds
        records = clip.clip_meta(cmds, root)
        assert any(r.get("name") == "cmuwalk" for r in records)

    def test_motion_actually_transferred(self):
        import maya.cmds as cmds
        from maya_plugin.handlers import retarget
        root = self._biped()
        retarget.retarget_clip({
            "file": "evals/mocap_fixtures/cmu_walk.bvh",
            "root": root, "clip": "cmuwalk2"})
        hips = cmds.ls(root, long=True)[0]
        p0 = cmds.getAttr(hips + ".translateX", time=1)
        pN = cmds.getAttr(hips + ".translateX", time=40)
        assert abs(pN - p0) > 0.01  # a walk MOVES

    def test_nothing_survives_but_keys(self):
        import maya.cmds as cmds
        from maya_plugin.handlers import retarget
        root = self._biped()
        retarget.retarget_clip({
            "file": "evals/mocap_fixtures/cmu_idle.bvh",
            "root": root, "clip": "cmuidle"})
        assert not cmds.ls("mocap_src_*", long=True)
        assert not [n for n in (cmds.ls(long=True) or [])
                    if "HIK" in (cmds.nodeType(n) or "")]

    def test_non_biped_target_refused_naming_slots(self):
        import maya.cmds as cmds
        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import retarget, rigging
        chain = rigging.create_skeleton({
            "name": "tail", "joints": [
                {"name": "a", "pos": [0, 0, 0]},
                {"name": "b", "pos": [0, 1, 0], "parent": "a"}]})
        with pytest.raises(HandlerError, match="LeftFoot"):
            retarget.retarget_clip({
                "file": "evals/mocap_fixtures/cmu_walk.bvh",
                "root": chain["root"], "clip": "nope"})
```

(The `_biped` helper and the exact `create_skeleton` param shapes are the implementer's to fill from `evals/humanoid_live.py` — the test INTENTS above are the contract; adjust node-type introspection to what the probe's teardown census actually named.)
- [ ] **Step 2: Run the class** under mayapy until green — fixing the HANDLER when a test exposes a real defect. Then the full mayapy suite with `--junitxml`; record the count (expect 190 baseline + new), delete the xml.
- [ ] **Step 3: Commit.** `git commit -m "test(#774): retargeted motion is real, registered, and leaves nothing behind"`.

---

### Task 5: `clean_clip` handler

**Files:**
- Create: `maya_plugin/handlers/cleanclip.py`
- Modify: `maya_plugin/maya_mcp_plugin.py` (register `"clean_clip"`)
- Test: `tests/test_retarget.py` (append headless refusals), `tests/test_handlers_mayapy.py` (append `TestCleanClipInMaya`)

**Interfaces:**
- Consumes: `mocapmath.smooth_track/blend_weights`; `motionmath.contact_runs/max_slide` (read their signatures in `maya_plugin/handlers/motionmath.py:85-133` first); `clip.clip_meta` (find the clip's frame range by name), `clip.measure_clip` (the before/after instrument); `rigging.pose_ik` internals only if IK pinning needs them — prefer direct world-space foot correction: for each contact run, compute the run's anchor position (median of the foot's world positions over the run), then per frame in the run move the foot chain via the same 2-bone analytic solve `pose_ik` uses (import its solver helper rather than duplicating it).
- Produces: `clean_clip(params) -> dict` — `{"clip": str, "root": str, "passes": [...], "before": {...}, "after": {...}, "checkpoint_id": str, "warnings": [...]}` where before/after are `measure_clip` summaries; plugin command `"clean_clip"`.

- [ ] **Step 1: Headless refusal tests** (append to tests/test_retarget.py): unknown key (synonyms `{"name": "clip", "smoothing": "filter"}`), unknown clip name (that check is Maya-side; headless covers key/param-shape refusals: `filter` must be bool or `{window:int}`, `lock_contacts` bool or `{joints:[...]}`; both-false refused with "nothing to do" hint). Write them, RED.
- [ ] **Step 2: Implement.** Flow: validate → `clip_meta` finds the named clip's range (refusal lists the clips that DO exist) → `measure_clip` BEFORE → `session.auto_checkpoint("clean_clip")` (its id goes in the result) → filter pass: for every keyed channel on the hierarchy over the clip range, sample per frame, `smooth_track`, re-key (skip weight/custom channels; rotation channels smoothed per-axis) → contact-lock pass: `contact_runs` on the contact joints (default: the two Foot joints from `SKELETON_HIK_MAP`; overridable), per run pin the foot to the run's median anchor with `blend_weights` easing at run edges → `measure_clip` AFTER → result. Warn (not fail) if any AFTER metric got WORSE than before, naming it — the caller decides; the gate asserts.
- [ ] **Step 3: mayapy tests** (`TestCleanClipInMaya`): author a deliberately dirty clip on a biped with `author_clip` — a two-key walk-ish clip whose foot translates while "planted" (keys chosen so `measure_clip` reports nonzero slide; and add alternating-frame jitter onto one elbow channel via `cmds.setKeyframe` per frame) — then `clean_clip` with both passes and assert: `after` slide < `before` slide; the jittered channel's acceleration metric improved; `checkpoint_id` present; `undo`/restore leaves the original clip measurable again (restore the checkpoint, re-measure, matches `before` within tolerance).
- [ ] **Step 4: GREEN** both layers; full headless + mayapy suites once each. Register the command.
- [ ] **Step 5: Commit.** `git commit -m "feat(#774): clean_clip - filter + contact-lock with before/after numbers"`.

---

### Task 6: MCP server surface

**Files:**
- Modify: `src/maya_mcp/schemas.py`, `src/maya_mcp/server.py`
- Test: `tests/test_server_tools.py` (tool list + forwards), `tests/test_retarget.py` (wire-shape regression)

**Interfaces:**
- Consumes: the two handlers' result keys (Tasks 3/5 Interfaces, exactly).
- Produces: tools `maya_retarget_clip`, `maya_clean_clip`; models `RetargetClipResult`, `CleanClipResult`.

- [ ] **Step 1: Failing tests.** Add both tool names to the expected tool list (~line 61 area, alongside `maya_create_curve_form`). Forward tests in the FakeConn pattern (mirror `TestCurveFormTools`): one per tool asserting cmd name, the FULL param dict with unset optionals as None, and structured_content round-trip. **Wire-shape regression (the #768 lesson, mandatory):** in tests/test_retarget.py, build each tool's request dict EXACTLY as server.py sends it (every key, unset ones None) and drive it through the real handler's pure validation far enough to prove no foreign-key/None-handling refusal fires (for retarget_clip: expect the FILE-existence refusal, not a key refusal — assert the error message mentions the file, proving validation got past the key gate).
- [ ] **Step 2: Implement.** `RetargetClipResult(BaseModel)`: `clip, root, frames, fps, source_joints, measures (dict), warnings`. `CleanClipResult(BaseModel)`: `clip, root, passes (List[str]), before (dict), after (dict), checkpoint_id, warnings`. Field descriptions are LLM-facing docs — state that `measures`/`before`/`after` carry `measure_clip` summary numbers and that thresholds are fractions of rig height (the #773 convention). Tools: `maya_retarget_clip(file, root, clip, start=None, end=None, fps=None)` and `maya_clean_clip(root, clip, filter=True, lock_contacts=True)`, both `BOOL_TIMEOUT_S`... **no — retarget bakes potentially thousands of frames: use `EXPORT_TIMEOUT_S` (300) for retarget_clip, `BOOL_TIMEOUT_S` (120) for clean_clip.** Defaults live handler-side; wire sends None for unset (the #768 ruling — `filter`/`lock_contacts` are the `cap_ends`-style literal-default exceptions, wire-defaulted `True`).
- [ ] **Step 3: GREEN** targeted + full headless suite (`--junitxml`, record, delete).
- [ ] **Step 4: Commit.** `git commit -m "feat(#774): maya_retarget_clip + maya_clean_clip on the MCP surface"`.

---

### Task 7: Deploy + live gate, thresholds by measurement

**Files:**
- Create: `evals/retarget_live.py`
- Modify: thresholds constant(s) in `evals/retarget_live.py` (and nothing else) after measurement

**Interfaces:**
- Consumes: `evals/live_call.py`; plugin commands `create_skeleton`, `retarget_clip`, `clean_clip`, `measure_clip`, `preview_clip`, `export_fbx`, `new_scene`; the committed fixtures (if Task 2's download branch failed, STOP here and report — the controller arranges clips with the user).
- Produces: the #774 acceptance gate, exit non-zero on failure, artifacts in `evals/retarget_live/`.

- [ ] **Step 1: Deploy + launch.** `install.py --yes` from the worktree; launch the 9878 Maya (Global Constraints); ping via live_call — fresh digest, no staleness warning, record the answering pid.
- [ ] **Step 2: Write the gate** (docstring notes the runs-all-checks-then-exits convention, per the #768 review). Steps, each `check()`-ed:
  1. `new_scene`; build the biped (`create_skeleton`, humanoid_live params).
  2. `retarget_clip` the fixture walk → clip `walk`. Print every `measures` number.
  3. `retarget_clip` the fixture idle → clip `idle` (after `delete_clip walk`? NO — one rig, two takes is legal per #718; keep both).
  4. **Discrimination (a):** build a SECOND biped with deliberately different proportions (legs 1.5× longer — adjust the create_skeleton params) → retarget the walk onto it → its pre-clean slide must EXCEED the well-proportioned rig's (print both).
  5. `clean_clip` on the re-proportioned rig's walk → **discrimination (b):** after-slide < before-slide, printed.
  6. THRESHOLDS: start `TOLERANCES = None` (measurement mode: print everything, assert only the two discriminations, exit 0). After the measurement run, set per-metric tolerances = 2× the measured well-proportioned values, rounded up one significant figure (the #773/#768 method), re-run asserting.
  7. Composition: `export_fbx` multi-take with both clips → the #718 byte-gate checks (reuse `evals/multi_take_live.py`'s verification helpers by import or by copying its byte-check invocation — cite which).
  8. `preview_clip` contact sheet for the walk → `evals/retarget_live/walk_sheet.png`; eyeball it (Read the PNG) and SAY what you see in the report.
- [ ] **Step 3: Measure → set tolerances → re-run to exit 0.** Record all numbers in the commit body.
- [ ] **Step 4: Commit.** `git commit -m "test(#774): live gate - retarget measured, cleanup discriminates, tolerance by measurement"`. Leave the 9878 Maya running; report its pid.

---

### Task 8: Suites, final review, merge, ticket

- [ ] **Step 1:** Full headless suite, `--junitxml`, 0 failures (record count vs 1731 baseline).
- [ ] **Step 2:** Full mayapy suite, `--junitxml`, 0 failures (record count vs 190 baseline).
- [ ] **Step 3:** Final whole-branch review per superpowers:requesting-code-review / SDD final review; one fix wave + one scoped re-review if findings.
- [ ] **Step 4:** Merge via superpowers:finishing-a-development-branch (pre-authorized on green); reap the 9878 Maya (proven pid only).
- [ ] **Step 5:** Redmine: one `update_issue` — Resolved, merged hash, both suite counts, all gate numbers + tolerances, route taken (HIK or direct, with the probe evidence), **"restart any running Maya"**.
- [ ] **Step 6:** Memory: update `project-774-mocap-retarget.md` + MEMORY.md line (state, stamp, measured traps); note whether the user still needs to stock more CMU clips for real use.
