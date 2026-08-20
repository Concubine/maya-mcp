# Rigging Phase 6 — animation clips Implementation Plan (#695)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three commands — `author_clip(root, name, fps, keys, interpolation, loop)` keys the phase-1 pose map over time (plus optional blendshape weights and root position, per-key displacement MEASURED), `preview_clip` renders every-nth frame for a judged contact sheet, `delete_clip` returns the skeleton to static land — plus `include_animation` on export (baked per-frame, take named after the clip, pinned OFF by default) with the byte gate reading AnimationCurve records, key counts and take duration out of the file.

**Architecture:** One new pure module `clipmath.py` (fps→Maya-time-unit map, key-shape validation, loop closure) and one new handler module `clip.py` (all-`cmds` orchestration, `_points` seam, lazy `rigging` import to avoid the guard cycle). While a clip exists, static pose mutators (`pose_skeleton`, `pose_ik`, `reset_pose`, `set_blendshape_weights`) REFUSE — curves own the channels; `delete_clip` is the way back. `render._run_shots` learns per-shot `time` + `reuse_camera` so preview frames render through the existing pipeline with a FIXED camera. `fbxbytes.py` learns AnimationCurve/AnimationCurveNode/Stack/Layer/Takes records and `anim_facts()`; `export.py` gains `include_animation` (both states pinned — False asserts ZERO curve records even when the scene is animated). Spec: `docs/superpowers/specs/2026-08-20-rigging-p6-clips-design.md` (settled decisions binding) on top of the Phase 6 section of `2026-08-19-rigging-surface-design.md`. Ticket #695.

**Tech Stack:** Python (Maya plugin handlers + FastMCP server), pytest three-leg testing (FakeCmds orchestration / synthetic-facts fbxbytes / mayapy real-Maya), live gate over the TCP client extending the #668 humanoid.

## Global Constraints

- **Decisions settled with the user 2026-08-20** (design doc — do not relitigate): ONE clip at a time (replace with warning, no library, no stacked timeline); keys carry rotations + optional `blend_weights` + optional `root_position` (root joint only); `loop=True` validates first==last key within tolerance (refusal with measured per-channel difference); static mutators refuse while a clip exists; export bakes per-frame with the take named after the clip; `include_animation=False` pins animation export OFF and the byte gate asserts zero curve records; one FBX per clip.
- **Report measured, never echoed** (#636): `duration_s` re-read from the curves after keying, per-key `max_displacement` from vertex reads at each key time, `delete_clip`'s displacement from before/after reads. Angles are degrees at the boundary, times are seconds, distances scene units.
- **Silence is never an answer** (#638/#640): replaced clips, fractional-frame keys, time-unit changes, no-bound-mesh clips, noop clips — warnings with numbers/names.
- **Mutators auto-checkpoint** after validation passes (a bad call must cost nothing). `preview_clip` is perception: `no_undo_chunk = True`, no checkpoint, current time restored.
- **No persistent solver state beyond the clip itself**: the clip IS curves on the joints plus one `mcp_clip` string attr on the root recording {name, fps, duration_s, loop, joints, weight_channels, root_position_used, interpolation}. `delete_clip` removes all of it.
- Two-Maya policy: live gate on the disposable agent-launched Maya, port **9878** (`MAYA_MCP_PORT` overrides), **neutral cwd** (#604), pid verified (#648). Never `new_scene` on the user's 9877.
- Suites at branch base (`rigging-p6-clips`, on main 05870dc): `uv run pytest -q` = **1244 passed + 1 skipped**, `E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q` = **142 passed + 1 skipped**. Both stay green; counts only grow. **Measure with `--junitxml`** — the pytest summary line is lost to stdout buffering on this machine; never trust `tail`.
- 53 tools currently; this phase makes **56**.
- **Plan literals are measured, not guessed.** Budgeted measurements (Task 6): the FBX tick constant (46186158000/s), the OP-connection property strings (`Lcl Rotation`/`Lcl Translation`/`DeformPercent`), the take name `FBXExportSplitAnimationIntoTakes` actually writes, the baked key count (expected `round(duration*fps)+1`), whether weight-channel curves are baked or carried as authored, and that `FBXProperty "Export|IncludeGrp|Animation" -v false` yields ZERO curve records. If a measurement contradicts a literal below, fix the reader/violation there, record the measured value in the test comment, and carry the change forward — do not force the literal.
- `evals/golem_delivery/`, `evals/humanoid_live/`, `evals/blendshape_live/` baselines stay frozen; the new gate writes its own `evals/clip_live/` directory.

## File structure

| file | responsibility |
|---|---|
| `maya_plugin/handlers/clipmath.py` (create) | Pure: `FPS_UNITS`, key-shape validation, fractional-frame detection, loop closure. |
| `maya_plugin/handlers/clip.py` (create) | `author_clip`, `preview_clip`, `delete_clip`; `CLIP_ATTR`; guards `guard_static_pose` / `guard_static_weights`; seam `_points`. |
| `maya_plugin/handlers/rigging.py` (modify) | `pose_skeleton` / `pose_ik` / `reset_pose` call `clip.guard_static_pose`. |
| `maya_plugin/handlers/blendshape.py` (modify) | `set_blendshape_weights` calls `clip.guard_static_weights`. |
| `maya_plugin/handlers/render.py` (modify) | `_run_shots`: per-shot `time`, `reuse_camera`, current-time snapshot/restore. |
| `maya_plugin/handlers/fbxbytes.py` (modify) | AnimationCurve/CurveNode/Stack/Layer/Takes records; `KTIME_PER_SECOND`; `anim_facts()`. |
| `maya_plugin/handlers/export.py` (modify) | `include_animation`; `FBX_ANIM_MEL`; `_scene_clip`; `anim_violations`; bake range + take-naming MEL; `animation` result block. |
| `maya_plugin/maya_mcp_plugin.py` (modify) | Register `author_clip`, `preview_clip`, `delete_clip`. |
| `src/maya_mcp/schemas.py` (modify) | `ClipKeySpec`, `ClipKeyMeasure`, `AuthorClipResult`, `DeleteClipResult`, `AnimCurveTarget`, `TakeRecord`, `AnimFacts`, `ExportFbxResult.animation`. |
| `src/maya_mcp/server.py` (modify) | `maya_author_clip`, `maya_delete_clip`, `maya_preview_clip` (sheet composited like `maya_render_sheet`); `maya_export_fbx` gains `include_animation`. |
| `docs/protocol.md` (modify) | Phase-6 command section; Delivery table row gains `animation`. |
| `evals/clip_live.py` (create) | The live gate: humanoid + blink target, looping idle + walk, judged preview sheets, both clips exported and byte-gated, `evals/clip_live/baseline.json`. |
| `tests/test_clipmath.py`, `tests/test_clip.py` (create); `tests/test_rigging.py`, `tests/test_blendshape.py`, `tests/test_fbxbytes.py`, `tests/test_export_fbx.py`, `tests/test_server_tools.py`, `tests/test_handlers_mayapy.py` (modify) | Coverage per leg. |

### Contract decisions locked here (plan-level refinements of the spec)

1. **fps is one of {24, 25, 30, 48, 50, 60}** — the frame rates Maya has native time units for (`film`/`pal`/`ntsc`/`show`/`palf`/`ntscf`). `author_clip` sets the scene time unit to match (warning when that changes it) so a frame IS a key-time unit and the bake range is exact. An arbitrary-fps knob would put keys between frames silently.
2. **`keys[0].time_s` must be 0.0** (refusal): the clip's timeline starts at zero, the bake range is `0..duration`, and a clip that starts at 0.4 s would bake 12 frames of unstated pose. A key whose `time_s * fps` is not an integer WARNS (the key sits between baked frames).
3. **Every key names at least one channel** (refusal otherwise). Channel sets MAY differ between keys (a blink keyed only mid-clip is legitimate — Maya interpolates each curve between its own keys) but `loop=True` requires the FIRST and LAST keys to name the SAME channel set, values within `LOOP_TOL_DEG = 1e-3` degrees / `LOOP_TOL = 1e-4` (weights, metres) — a channel absent from either end cannot prove closure.
4. **Foreign animation refuses `author_clip`.** Curves on the skeleton WITHOUT an `mcp_clip` attr are someone's hand-authored animation; replacing them silently would destroy work this tool never made. Refusal with hint: `delete_clip` clears them if that is intended (it works with or without metadata, warning when without).
5. **`blend_weights` aliases resolve across the blendShape nodes of meshes SKINNED to this skeleton** (`_bound_meshes`); an alias found on two nodes is a refusal, not a guess. `root_position` is a WORLD position applied via `xform -ws` then keyed as the root's local translate (identical for an unparented root; the xform makes a parented root correct too).
6. **The guard is structural, not metadata**: static mutators refuse when an `animCurve` drives any relevant channel (rotate/translate on hierarchy joints; weight aliases on the blendShape node), naming the clip when `mcp_clip` exists. This catches hand-keyed channels too — writing a value a curve overrides on the next frame change is the silent fight the rule exists to prevent, whoever keyed it.
7. **`per_key[i].max_displacement` is measured against the evaluated FIRST key** (current time driven to each key's frame, vertices re-read, compared to frame 0). Key 0 is 0 by construction; a clip whose every later key measures ~0 against a mesh of extent E warns via the `NOOP_POSE_RATIO` rule. `duration_s` is re-read from `cmds.keyframe(query=True)` after keying, never echoed.
8. **`preview_clip` gains an optional `angle`** (default `three_quarter`, validated against `capture.VALID_ANGLES`) — a spec-signature refinement: a walk is judged from the side, an expression from the front. The camera is placed ONCE at frame 0's framing and held (`reuse_camera`) — motion must read against a fixed frame, and a camera chasing the bbox per frame would hide root motion entirely. Cap `MAX_PREVIEW_FRAMES = 16` (the turntable's cap); default `every_nth` is the smallest stride that fits.
9. **Export**: `include_animation=True` refuses when no clip exists, and refuses when MORE than one root carries `mcp_clip` (one clip at a time is per-skeleton; one FILE is one take). Bake: `FBXExportBakeComplexAnimation -v true`, start 0, end `round(duration_s*fps)`, step 1; take naming via `FBXExportSplitAnimationIntoTakes` (Task 6 measures what Maya actually writes). `False` pins `FBXProperty "Export|IncludeGrp|Animation" -v false` AND `FBXExportBakeComplexAnimation -v false`; the byte gate then asserts zero curve records — the symmetric assertion.
10. **Weight-channel curves are asserted PRESENT, not key-counted.** Whether Maya's baker resamples `DeformPercent` curves or carries them as authored is a Task 6 measurement; the violation gates presence + ≥2 keys, and the measured count goes in the mayapy pin and the gate baseline. Joint rotation and root translation curves gate the full `round(duration*fps)+1` count.
11. **`delete_clip`** deletes every animCurve on the hierarchy's rotate/translate channels and on the clip's weight aliases, zeroes those weight channels (weights-all-0 is the reset, the P5 rule), restores the bind pose (dagPose when one exists, zeroed rotations otherwise — `reset_pose`'s exact logic inline, NOT a nested call, so there is one checkpoint), removes `mcp_clip`, and reports measured `max_displacement`.
12. **Extra animation targets in the file are not violations** (a hand-keyed channel outside the clip's declaration still deserves to export — the shape_violations precedent); MISSING declared targets are.

---

### Task 1: clipmath — the pure leg

**Files:**
- Create: `maya_plugin/handlers/clipmath.py`
- Test: `tests/test_clipmath.py`

**Interfaces:**
- Consumes: nothing (pure stdlib).
- Produces (Task 2 calls these by name): `FPS_UNITS`, `MAX_KEYS`, `LOOP_TOL_DEG`, `LOOP_TOL`, `validated_keys(keys) -> List[dict]`, `fractional_frame_times(times, fps) -> List[float]`, `loop_violations(first, last) -> List[str]`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_clipmath.py`:

```python
"""Pure clip math (#695): key-shape validation, frame alignment, loop closure.

Everything scene-dependent (joint resolution, alias resolution, actual keying)
is clip.py's job under FakeCmds; this file pins the parts that need no scene.
"""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import clipmath


def _key(t, rot=None, bw=None, rp=None):
    out = {"time_s": t}
    if rot is not None:
        out["rotations"] = rot
    if bw is not None:
        out["blend_weights"] = bw
    if rp is not None:
        out["root_position"] = rp
    return out


class TestValidatedKeys:
    def test_a_healthy_key_list_normalizes(self):
        keys = clipmath.validated_keys([
            _key(0.0, rot={"L_hip": [0, -20, 0]}, rp=[0, 1.0, 0]),
            _key(0.5, rot={"L_hip": [0, 20, 0]}, bw={"blink": 1.0}),
        ])
        assert keys[0]["time_s"] == 0.0
        assert keys[0]["rotations"] == {"L_hip": [0.0, -20.0, 0.0]}
        assert keys[0]["blend_weights"] == {}
        assert keys[0]["root_position"] == [0.0, 1.0, 0.0]
        assert keys[1]["blend_weights"] == {"blink": 1.0}
        assert keys[1]["root_position"] is None

    def test_refusals(self):
        good = [_key(0.0, rot={"j": [0, 0, 0]}),
                _key(1.0, rot={"j": [0, 0, 0]})]
        with pytest.raises(HandlerError, match="2..%d" % clipmath.MAX_KEYS):
            clipmath.validated_keys(None)
        with pytest.raises(HandlerError, match="2..%d" % clipmath.MAX_KEYS):
            clipmath.validated_keys(good[:1])
        with pytest.raises(HandlerError, match="must start at time_s 0"):
            clipmath.validated_keys([_key(0.1, rot={"j": [0, 0, 0]}),
                                    _key(1.0, rot={"j": [0, 0, 0]})])
        with pytest.raises(HandlerError, match="strictly increasing"):
            clipmath.validated_keys([good[0], _key(0.0, rot={"j": [0, 0, 0]})])
        with pytest.raises(HandlerError, match="names no channel"):
            clipmath.validated_keys([good[0], _key(1.0)])
        with pytest.raises(HandlerError, match="keys\\[1\\].time_s"):
            clipmath.validated_keys([good[0], _key("x", rot={"j": [0, 0, 0]})])
        with pytest.raises(HandlerError, match="0..1"):
            clipmath.validated_keys([good[0], _key(1.0, bw={"blink": 1.5})])
        with pytest.raises(HandlerError, match="0..1"):
            clipmath.validated_keys([good[0], _key(1.0, bw={"blink": True})])
        with pytest.raises(HandlerError, match="root_position"):
            clipmath.validated_keys([good[0], _key(1.0, rp=[1, 2])])
        with pytest.raises(HandlerError, match="rotations\\[.j.\\]"):
            clipmath.validated_keys([good[0], _key(1.0, rot={"j": [1, 2]})])

    def test_fps_units_cover_the_native_rates(self):
        assert clipmath.FPS_UNITS == {24: "film", 25: "pal", 30: "ntsc",
                                      48: "show", 50: "palf", 60: "ntscf"}


class TestFrameAlignment:
    def test_aligned_times_pass_quietly(self):
        assert clipmath.fractional_frame_times([0.0, 0.3, 0.6], 30) == []

    def test_misaligned_times_are_named(self):
        assert clipmath.fractional_frame_times([0.0, 0.33], 30) == [0.33]


class TestLoopViolations:
    def _first(self):
        return {"time_s": 0.0, "rotations": {"L_hip": [0.0, -20.0, 0.0]},
                "blend_weights": {"blink": 0.0},
                "root_position": [0.0, 1.0, 0.0]}

    def test_a_closed_loop_is_clean(self):
        last = dict(self._first(), time_s=1.2)
        assert clipmath.loop_violations(self._first(), last) == []

    def test_tolerance_is_real_but_tight(self):
        last = dict(self._first(), time_s=1.2,
                    rotations={"L_hip": [0.0, -20.0 + 5e-4, 0.0]})
        assert clipmath.loop_violations(self._first(), last) == []
        last["rotations"] = {"L_hip": [0.0, -19.9, 0.0]}
        out = clipmath.loop_violations(self._first(), last)
        assert len(out) == 1 and "L_hip" in out[0] and "0.1" in out[0]

    def test_channel_set_mismatch_is_a_violation(self):
        last = dict(self._first(), time_s=1.2, blend_weights={})
        out = clipmath.loop_violations(self._first(), last)
        assert any("blink" in v and "last key" in v for v in out)
        first = dict(self._first(), root_position=None)
        out = clipmath.loop_violations(first, dict(self._first(), time_s=1.2))
        assert any("root_position" in v for v in out)

    def test_weight_and_root_deltas_are_measured_in_the_message(self):
        last = dict(self._first(), time_s=1.2,
                    blend_weights={"blink": 0.4},
                    root_position=[0.0, 1.05, 0.0])
        out = clipmath.loop_violations(self._first(), last)
        assert any("blink" in v and "0.4" in v for v in out)
        assert any("root_position" in v and "0.05" in v for v in out)
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_clipmath.py -q --junitxml=$env:TEMP/p6t1.xml`. Expected: FAIL (`ImportError` on `clipmath`).

- [ ] **Step 3: Implement** — create `maya_plugin/handlers/clipmath.py`:

```python
"""Pure clip math for #695: no Maya, no scene - the testable half of clip.py.

Times are seconds, rotations degrees (#636), root positions metres. The
scene-facing half (name resolution, keying, measurement) lives in clip.py.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..dispatcher import HandlerError

# The frame rates Maya has NATIVE time units for. author_clip sets the scene
# unit to match, so a frame IS one key-time unit and the bake range is exact -
# an arbitrary-fps knob would put keys between frames silently.
FPS_UNITS = {24: "film", 25: "pal", 30: "ntsc",
             48: "show", 50: "palf", 60: "ntscf"}
MAX_KEYS = 64
# Loop closure tolerances: float noise passes, an authoring mistake does not.
# A 0.001-degree joint step or a 0.1 mm root step is invisible at any frame
# rate; a real pop is orders of magnitude above both.
LOOP_TOL_DEG = 1e-3
LOOP_TOL = 1e-4


def _vec3(value, what: str) -> Optional[List[float]]:
    if value is None:
        return None
    if (not isinstance(value, (list, tuple)) or len(value) != 3
            or any(isinstance(v, bool) or not isinstance(v, (int, float))
                   for v in value)):
        raise HandlerError("%s must be [x, y, z] numbers" % what)
    return [float(v) for v in value]


def validated_keys(keys) -> List[Dict[str, Any]]:
    """Normalized key dicts, or a refusal. Structure only - names that need a
    scene (joints, aliases) are clip.py's to resolve."""
    if (not isinstance(keys, list) or not 2 <= len(keys) <= MAX_KEYS):
        raise HandlerError(
            "keys must be a list of 2..%d {time_s, rotations?, blend_weights?,"
            " root_position?} entries" % MAX_KEYS,
            hint="a clip is at least a start and an end key")
    out: List[Dict[str, Any]] = []
    for i, entry in enumerate(keys):
        if not isinstance(entry, dict):
            raise HandlerError("keys[%d] must be a dict" % i)
        t = entry.get("time_s")
        if isinstance(t, bool) or not isinstance(t, (int, float)) or t < 0:
            raise HandlerError("keys[%d].time_s must be a number >= 0" % i,
                               hint="seconds from the clip start")
        rotations = entry.get("rotations")
        if rotations is None:
            rotations = {}
        if not isinstance(rotations, dict):
            raise HandlerError("keys[%d].rotations must be a map of joint "
                               "name to [rx, ry, rz] degrees" % i)
        rot_out = {}
        for name, triple in rotations.items():
            v = _vec3(triple, "keys[%d].rotations[%r]" % (i, name))
            if v is None:
                raise HandlerError(
                    "keys[%d].rotations[%r] must be [rx, ry, rz]" % (i, name))
            rot_out[name] = v
        weights = entry.get("blend_weights")
        if weights is None:
            weights = {}
        if not isinstance(weights, dict):
            raise HandlerError("keys[%d].blend_weights must be a map of "
                               "target name to 0..1" % i)
        for name, value in weights.items():
            if (isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not 0.0 <= float(value) <= 1.0):
                raise HandlerError(
                    "keys[%d].blend_weights[%r] must be a number in 0..1, "
                    "got %r" % (i, name, value))
        weights = {k: float(v) for k, v in weights.items()}
        root_position = _vec3(entry.get("root_position"),
                              "keys[%d].root_position" % i)
        if not rot_out and not weights and root_position is None:
            raise HandlerError(
                "keys[%d] names no channel" % i,
                hint="every key carries at least one of rotations, "
                     "blend_weights, root_position")
        out.append({"time_s": float(t), "rotations": rot_out,
                    "blend_weights": weights, "root_position": root_position})
    if out[0]["time_s"] != 0.0:
        raise HandlerError(
            "keys must start at time_s 0.0 (got %g)" % out[0]["time_s"],
            hint="the bake range is 0..duration; a later first key would "
                 "bake frames of unstated pose")
    for i in range(1, len(out)):
        if out[i]["time_s"] <= out[i - 1]["time_s"]:
            raise HandlerError(
                "key times must be strictly increasing (keys[%d] at %g after "
                "%g)" % (i, out[i]["time_s"], out[i - 1]["time_s"]))
    return out


def fractional_frame_times(times: List[float], fps: int) -> List[float]:
    """Key times that do not land on an integer frame at this fps - the baked
    export samples integer frames, so these keys are between samples."""
    out = []
    for t in times:
        frame = t * fps
        if abs(frame - round(frame)) > 1e-6:
            out.append(t)
    return out


def loop_violations(first: Dict[str, Any], last: Dict[str, Any]) -> List[str]:
    """Ways the last key fails to close onto the first, with measured deltas.

    Channel-set equality is required: a channel absent from either end cannot
    prove closure, and Maya would hold/interpolate it into a pop on repeat.
    """
    out: List[str] = []
    f_rot, l_rot = first["rotations"], last["rotations"]
    for name in sorted(set(f_rot) | set(l_rot)):
        if name not in l_rot:
            out.append("loop: joint %r is keyed on the first key but not the "
                       "last key" % name)
        elif name not in f_rot:
            out.append("loop: joint %r is keyed on the last key but not the "
                       "first key" % name)
        else:
            worst = max(abs(a - b) for a, b in zip(f_rot[name], l_rot[name]))
            if worst > LOOP_TOL_DEG:
                out.append(
                    "loop: joint %r ends %.4g degrees away from where it "
                    "starts (first %s, last %s)"
                    % (name, worst, f_rot[name], l_rot[name]))
    f_w, l_w = first["blend_weights"], last["blend_weights"]
    for name in sorted(set(f_w) | set(l_w)):
        if name not in l_w:
            out.append("loop: weight %r is keyed on the first key but not "
                       "the last key" % name)
        elif name not in f_w:
            out.append("loop: weight %r is keyed on the last key but not "
                       "the first key" % name)
        elif abs(f_w[name] - l_w[name]) > LOOP_TOL:
            out.append("loop: weight %r ends at %g, starts at %g"
                       % (name, l_w[name], f_w[name]))
    f_rp, l_rp = first["root_position"], last["root_position"]
    if (f_rp is None) != (l_rp is None):
        out.append("loop: root_position is keyed on only one end of the clip")
    elif f_rp is not None:
        worst = max(abs(a - b) for a, b in zip(f_rp, l_rp))
        if worst > LOOP_TOL:
            out.append("loop: the root ends %.4g away from where it starts "
                       "(first %s, last %s)" % (worst, f_rp, l_rp))
    return out
```

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_clipmath.py -q --junitxml=$env:TEMP/p6t1.xml`. Expected: PASS (read the XML, not the tail).

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/clipmath.py tests/test_clipmath.py
git commit -m "feat(#695): clipmath - fps units, key validation, loop closure (pure)"
```

---

### Task 2: author_clip / delete_clip under FakeCmds

**Files:**
- Create: `maya_plugin/handlers/clip.py`
- Modify: `maya_plugin/maya_mcp_plugin.py` (handlers import list + three `_build_handlers` entries after `"set_blendshape_weights"` — `preview_clip` registers now but its handler body lands in Task 4; register `author_clip` and `delete_clip` in this task, `preview_clip` in Task 4)
- Test: `tests/test_clip.py`

**Interfaces:**
- Consumes: `clipmath` (Task 1), `rigging._require_joint` / `_hierarchy_joints` / `_resolve_rotations` / `_bound_meshes` (all take `cmds` as a parameter — no monkeypatching of rigging needed), `blendshape._aliases`, `naming`, `sculpt`, `sculpt_math`, `session`, `units.degrees_to_ui` / `ui_to_degrees`.
- Produces (Tasks 3/5/7/9 read these by name):
  - `clip.CLIP_ATTR = "mcp_clip"`, `clip.NAME_RE`
  - `clip.author_clip(params) -> {root, clip, fps, duration_s, frames, keyed_joints, keyed_weight_channels, root_position_keyed, interpolation, loop, replaced, per_key: [{time_s, max_displacement}], warnings}`
  - `clip.delete_clip(params) -> {root, clip, deleted_curves, max_displacement, warnings}`
  - `clip.clip_meta(cmds, root_long) -> Optional[dict]` (export's Task 5 seam)
  - `clip.guard_static_pose(cmds, root_long, joints, what)`, `clip.guard_static_weights(cmds, node, aliases, what)` (Task 3 wires them)
  - Module-level `_points(mesh_long)` — the seam tests monkeypatch.

- [ ] **Step 1: Write the failing tests** — create `tests/test_clip.py`:

```python
"""author_clip / delete_clip (#695) under a FakeCmds.

Real curve evaluation is mayapy's job (tests/test_handlers_mayapy.py); this
file pins validation, the one-clip-at-a-time replace rule, the foreign-curve
refusal, metadata, measured per-key displacement (via the _points seam and a
linear fake), tangent mapping, and delete_clip's teardown.
"""

import json

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import clip


class FakeCmds:
    """A 3-joint chain |root -> |root|mid -> |root|mid|tip, one optional
    bound mesh |body with a blendShape 'body_shapes' carrying alias 'blink'.
    setKeyframe records (node, attr, frame, value) and creates a curve node
    per plug; listConnections answers from that map. currentTime drives the
    fake pose the _points seam reads."""

    def __init__(self, bound=True):
        self.joints = ["|root", "|root|mid", "|root|mid|tip"]
        self.bound = bound
        self.curves = {}          # plug -> curve node name
        self.keys = {}            # plug -> {frame: value}
        self.tangents = []        # (node, attr, itt, ott)
        self.attrs = {"|root.translateX": 0.0, "|root.translateY": 1.0,
                      "|root.translateZ": 0.0}
        for j in self.joints:
            self.attrs[j + ".rotate"] = (0.0, 0.0, 0.0)
        self.string_attrs = {}    # node -> {attr: value}
        self.time = 0.0
        self.time_unit = "film"
        self.playback = {}
        self.deleted = []
        self.checkpoints = []
        self.blend_aliases = ["blink"] if bound else []

    # --- resolution ------------------------------------------------------
    def ls(self, pattern=None, long=False, type=None, **kw):
        if type == "skinCluster":
            return ["body_skin"] if self.bound else []
        if type == "joint":
            return list(self.joints)
        if isinstance(pattern, list):
            if type == "blendShape":
                return [n for n in pattern if n == "body_shapes"]
            return list(pattern)
        if pattern is None:
            return list(self.joints) + (["|body"] if self.bound else [])
        matches = [o for o in self.joints + (["|body"] if self.bound else [])
                   if o == pattern or o.split("|")[-1] == pattern]
        return matches

    def objExists(self, name):
        return bool(self.ls(name)) or name in ("body_shapes", "body_skin")

    def nodeType(self, node):
        if node in self.joints:
            return "joint"
        if node == "body_shapes":
            return "blendShape"
        return "mesh" if node.endswith("Shape") else "transform"

    def listRelatives(self, node, children=False, parent=False, shapes=False,
                      type=None, fullPath=False, **kw):
        if children and type == "joint":
            kids = [j for j in self.joints
                    if j.rsplit("|", 1)[0] == node and j != node]
            return kids or None
        if shapes:
            return ["|body|bodyShape"] if node == "|body" else None
        if parent:
            return ["|body"] if node == "|body|bodyShape" else None
        return None

    def listHistory(self, node, pruneDagObjects=False, **kw):
        if node == "|body|bodyShape":
            return ["body_shapes", "body_skin"]
        return []

    def listAttr(self, plug, multi=False):
        if plug.startswith("body_shapes"):
            return list(self.blend_aliases) or None
        return None

    def skinCluster(self, name, query=False, influence=False, geometry=False):
        if influence:
            return list(self.joints)
        if geometry:
            return ["|body|bodyShape"]
        return None

    # --- attributes ------------------------------------------------------
    def getAttr(self, key):
        if key.endswith(".mcp_clip"):
            node = key.rsplit(".", 1)[0]
            return self.string_attrs[node]["mcp_clip"]
        return self.attrs.get(key, 0.0)

    def setAttr(self, key, *values, **kw):
        if kw.get("type") == "string":
            node, attr = key.rsplit(".", 1)
            self.string_attrs.setdefault(node, {})[attr] = values[0]
        elif len(values) == 3:
            self.attrs[key] = tuple(values)
        else:
            self.attrs[key] = values[0]

    def addAttr(self, node, longName=None, dataType=None):
        self.string_attrs.setdefault(node, {})[longName] = ""

    def attributeQuery(self, attr, node=None, exists=False):
        return attr in self.string_attrs.get(node, {})

    def deleteAttr(self, plug):
        node, attr = plug.rsplit(".", 1)
        self.string_attrs.get(node, {}).pop(attr, None)

    def xform(self, node, query=False, worldSpace=False, translation=None,
              **kw):
        if query:
            return [self.attrs.get(node + ".translateX", 0.0),
                    self.attrs.get(node + ".translateY", 0.0),
                    self.attrs.get(node + ".translateZ", 0.0)]
        for axis, v in zip("XYZ", translation):
            self.attrs[node + ".translate" + axis] = float(v)

    # --- animation -------------------------------------------------------
    def setKeyframe(self, node, attribute=None, time=None, value=None):
        plug = "%s.%s" % (node, attribute)
        self.curves.setdefault(plug, plug.replace("|", "_") + "_crv")
        self.keys.setdefault(plug, {})[float(time)] = float(value)

    def keyTangent(self, node, attribute=None, edit=False,
                   inTangentType=None, outTangentType=None):
        self.tangents.append((node, attribute, inTangentType, outTangentType))

    def keyframe(self, plug, query=False, **kw):
        return sorted(self.keys.get(plug, {})) or None

    def listConnections(self, plug, source=False, destination=True,
                        type=None):
        curve = self.curves.get(plug)
        return [curve] if curve else None

    def delete(self, *names):
        for n in names:
            self.deleted.append(n)
            for plug, curve in list(self.curves.items()):
                if curve == n:
                    del self.curves[plug]
                    self.keys.pop(plug, None)

    def currentUnit(self, time=None, angle=None, query=False, **kw):
        # units.degrees_to_ui/ui_to_degrees ask for the ANGLE unit; answering
        # "degree" makes both identity, so keyed values equal their degrees.
        if query and angle:
            return "degree"
        if query:
            return self.time_unit
        if time is not None:
            self.time_unit = time

    def currentTime(self, value=None, query=False):
        if query:
            return self.time
        self.time = float(value)

    def playbackOptions(self, edit=False, **kw):
        self.playback.update(kw)

    def dagPose(self, *args, **kw):
        return []   # nothing bound via dagPose in the fake: zero-rotation path


@pytest.fixture
def fake(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(clip, "_cmds", lambda: fake)
    monkeypatch.setattr(clip.session, "auto_checkpoint",
                        lambda label: fake.checkpoints.append(label) or
                        {"checkpoint_id": "cp"})

    def points(mesh):
        # One vertex whose Y is the value of |root.rotateX's curve at the
        # fake's current frame (0 when unkeyed) - the minimal model that
        # makes per-key displacement depend on evaluated curves.
        keys = fake.keys.get("|root.rotateX", {})
        lift = keys.get(fake.time, 0.0)
        return [0.0, lift, 0.0, 1.0, 0.0, 0.0]

    monkeypatch.setattr(clip, "_points", points)
    return fake


def _author(fake, name="idle", fps=30, keys=None, **kw):
    if keys is None:
        keys = [
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"mid": [0, 0, 45]},
             "root_position": [0.0, 1.05, 0.0]},
        ]
    return clip.author_clip(dict({"root": "root", "name": name, "fps": fps,
                                  "keys": keys}, **kw))


class TestAuthorValidation:
    def test_refusals_cost_nothing(self, fake):
        with pytest.raises(HandlerError, match="plain identifier"):
            _author(fake, name="2bad")
        with pytest.raises(HandlerError, match="fps"):
            _author(fake, fps=31)
        with pytest.raises(HandlerError, match="interpolation"):
            _author(fake, interpolation="stepped")
        with pytest.raises(HandlerError, match="not a joint under this root"):
            _author(fake, keys=[
                {"time_s": 0.0, "rotations": {"nope": [0, 0, 0]}},
                {"time_s": 1.0, "rotations": {"nope": [0, 0, 0]}}])
        with pytest.raises(HandlerError, match="not a blendshape target"):
            _author(fake, keys=[
                {"time_s": 0.0, "blend_weights": {"nope": 0.5}},
                {"time_s": 1.0, "blend_weights": {"nope": 0.0}}])
        assert fake.checkpoints == []

    def test_loop_violations_refuse_with_measured_deltas(self, fake):
        with pytest.raises(HandlerError, match="ends 45"):
            _author(fake, loop=True, keys=[
                {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
                {"time_s": 1.0, "rotations": {"mid": [0, 0, 45]}}])

    def test_foreign_curves_refuse(self, fake):
        fake.curves["|root|mid.rotateZ"] = "hand_authored_crv"
        with pytest.raises(HandlerError, match="hand-authored"):
            _author(fake)


class TestAuthor:
    def test_keys_land_measured_and_metadata_written(self, fake):
        out = _author(fake)
        assert out["root"] == "|root"
        assert out["clip"] == "idle"
        assert out["duration_s"] == pytest.approx(1.0)   # re-read, not echoed
        assert out["frames"] == 31
        assert out["keyed_joints"] == 1
        assert out["root_position_keyed"] is True
        assert out["replaced"] is None
        # rotations keyed on all three axes of the named joint
        assert set(p for p in fake.keys if p.startswith("|root|mid.rotate")) \
            == {"|root|mid.rotateX", "|root|mid.rotateY", "|root|mid.rotateZ"}
        # root translate keyed from the world position
        assert fake.keys["|root.translateY"][30.0] == pytest.approx(1.05)
        # time unit follows fps; playback range covers the clip
        assert fake.time_unit == "ntsc"
        assert fake.playback["minTime"] == 0
        assert fake.playback["maxTime"] == 30
        meta = json.loads(fake.string_attrs["|root"]["mcp_clip"])
        assert meta["name"] == "idle" and meta["fps"] == 30
        assert meta["loop"] is False
        assert fake.checkpoints == ["author_clip"]

    def test_per_key_displacement_is_evaluated_not_echoed(self, fake):
        out = _author(fake, keys=[
            {"time_s": 0.0, "rotations": {"root": [0, 0, 0]}},
            {"time_s": 0.5, "rotations": {"root": [0.25, 0, 0]}},
            {"time_s": 1.0, "rotations": {"root": [0, 0, 0]}}])
        disp = [k["max_displacement"] for k in out["per_key"]]
        # the fake's vertex rides |root.rotateX's keyed value
        assert disp[0] == 0.0
        assert disp[1] == pytest.approx(0.25)
        assert disp[2] == pytest.approx(0.0)

    def test_replacing_warns_and_deletes_the_old_curves(self, fake):
        _author(fake, name="idle")
        old = set(fake.deleted)
        out = _author(fake, name="walk")
        assert out["replaced"] == "idle"
        assert any("replaced clip 'idle'" in w for w in out["warnings"])
        assert len(fake.deleted) > len(old)

    def test_tangent_mapping(self, fake):
        _author(fake, interpolation="smooth")
        assert fake.tangents and all(t[2] == "auto" and t[3] == "auto"
                                     for t in fake.tangents)
        fake2_keys = fake.tangents[:]
        _author(fake, name="lin", interpolation="linear")
        new = fake.tangents[len(fake2_keys):]
        assert new and all(t[2] == "linear" for t in new)

    def test_fractional_frames_and_unbound_skeleton_warn(self, fake):
        fake.bound = False
        fake.blend_aliases = []
        out = _author(fake, keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 0.333, "rotations": {"mid": [0, 0, 10]}}])
        assert any("between frames" in w for w in out["warnings"])
        assert any("no skinned mesh" in w for w in out["warnings"])


class TestDelete:
    def test_no_clip_refuses(self, fake):
        with pytest.raises(HandlerError, match="no clip"):
            clip.delete_clip({"root": "root"})

    def test_deletes_curves_metadata_and_measures(self, fake):
        _author(fake)
        out = clip.delete_clip({"root": "root"})
        assert out["clip"] == "idle"
        assert out["deleted_curves"] > 0
        assert not any(p.startswith("|root|mid.rotate") for p in fake.curves)
        assert "mcp_clip" not in fake.string_attrs.get("|root", {})
        assert fake.checkpoints == ["author_clip", "delete_clip"]

    def test_hand_authored_curves_delete_with_a_warning(self, fake):
        fake.curves["|root|mid.rotateZ"] = "hand_crv"
        fake.keys["|root|mid.rotateZ"] = {0.0: 1.0}
        out = clip.delete_clip({"root": "root"})
        assert out["clip"] is None
        assert any("no clip metadata" in w for w in out["warnings"])


class TestGuards:
    def test_static_pose_guard_names_the_clip(self, fake):
        _author(fake)
        with pytest.raises(HandlerError, match="clip 'idle'"):
            clip.guard_static_pose(fake, "|root",
                                   ["|root", "|root|mid", "|root|mid|tip"],
                                   "pose_skeleton")

    def test_static_weight_guard(self, fake):
        _author(fake, keys=[
            {"time_s": 0.0, "blend_weights": {"blink": 0.0}},
            {"time_s": 1.0, "blend_weights": {"blink": 0.0}}])
        with pytest.raises(HandlerError, match="animation curves"):
            clip.guard_static_weights(fake, "body_shapes", ["blink"],
                                      "set_blendshape_weights")

    def test_clean_scene_passes_both_guards(self, fake):
        clip.guard_static_pose(fake, "|root", ["|root"], "pose_skeleton")
        clip.guard_static_weights(fake, "body_shapes", ["blink"], "x")
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_clip.py -q --junitxml=$env:TEMP/p6t2.xml`. Expected: FAIL (`ImportError` on `clip`).

- [ ] **Step 3: Implement** — create `maya_plugin/handlers/clip.py`:

```python
"""Animation clips, phase 6 of #602 (#695): author_clip, preview_clip,
delete_clip.

The currency is the phase-1 pose map, keyed: each key is {time_s, rotations,
blend_weights?, root_position?}. ONE clip exists per skeleton at a time -
authoring under a new name replaces the old one (with a warning), export
bakes the current clip as one take, and delete_clip returns the skeleton to
static land. While a clip exists, static pose mutators REFUSE (the guards
below): curves own the channels, and a static write a curve overrides on the
next frame change is the quietest way to lie about a pose.

Every number is MEASURED (#636): duration_s is re-read from the curves after
keying, per-key displacement from vertices with the current time driven to
that key's frame.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from ..dispatcher import HandlerError
from . import clipmath, naming, sculpt, sculpt_math, session, units

CLIP_ATTR = "mcp_clip"
NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
INTERPOLATIONS = {"linear": "linear", "smooth": "auto"}
ROTATE_ATTRS = ("rotateX", "rotateY", "rotateZ")
TRANSLATE_ATTRS = ("translateX", "translateY", "translateZ")
# Perception caps for preview_clip (Task 4). 16 matches the turntable's
# frame cap: past that a sheet is unreadable at message resolution.
MAX_PREVIEW_FRAMES = 16
DEFAULT_PREVIEW_RESOLUTION = 256


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _short(name: str) -> str:
    return name.split("|")[-1]


def _points(mesh_long: str) -> List[float]:
    """World-space vertex positions. Module-level so tests monkeypatch it
    (the blendshape._points precedent)."""
    return sculpt.vertex_positions(_cmds(), mesh_long)


def clip_meta(cmds, root_long: str) -> Optional[Dict[str, Any]]:
    """The clip this tool authored on `root_long`, or None. Read from the
    mcp_clip string attr; a value that fails to parse is reported as name
    only rather than crashing a guard."""
    if not cmds.attributeQuery(CLIP_ATTR, node=root_long, exists=True):
        return None
    raw = cmds.getAttr("%s.%s" % (root_long, CLIP_ATTR))
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {"name": str(raw) if raw else None}


def _anim_curves(cmds, plugs: List[str]) -> Dict[str, List[str]]:
    """plug -> animCurve nodes driving it (source connections only)."""
    out: Dict[str, List[str]] = {}
    for plug in plugs:
        curves = cmds.listConnections(plug, source=True, destination=False,
                                      type="animCurve") or []
        if curves:
            out[plug] = list(curves)
    return out


def _joint_plugs(joints: List[str]) -> List[str]:
    return ["%s.%s" % (j, a) for j in joints
            for a in ROTATE_ATTRS + TRANSLATE_ATTRS]


def guard_static_pose(cmds, root_long: str, joints: List[str],
                      what: str) -> None:
    """Refuse a static pose write while curves drive the skeleton.

    Structural, not metadata: a hand-keyed channel fights a static write the
    same way a clip does. The clip name is named when metadata exists."""
    driven = _anim_curves(cmds, _joint_plugs(joints))
    if not driven:
        return
    meta = clip_meta(cmds, root_long) or {}
    label = (" (clip %r)" % meta["name"]) if meta.get("name") else ""
    raise HandlerError(
        "%s refuses while animation curves drive this skeleton%s - a static "
        "write here would be overridden on the next frame change"
        % (what, label),
        hint="author_clip re-authors the motion; delete_clip removes the "
             "curves and returns the skeleton to static posing")


def guard_static_weights(cmds, node: str, aliases: List[str],
                         what: str) -> None:
    """The same rule for blendshape weight channels."""
    driven = _anim_curves(cmds, ["%s.%s" % (node, a) for a in aliases])
    if driven:
        raise HandlerError(
            "%s refuses while animation curves drive %d weight channel(s) "
            "of %s (%s)" % (what, len(driven), node,
                            ", ".join(sorted(p.split(".")[-1]
                                             for p in driven))),
            hint="the clip owns these channels; delete_clip returns them to "
                 "static control")


def _weight_alias_map(cmds, meshes: List[str]) -> Dict[str, str]:
    """alias -> blendShape node, across every mesh bound to the skeleton.
    An alias on two nodes is ambiguous and refuses at USE, not here - the
    map records the collision instead of guessing."""
    from . import blendshape  # noqa: PLC0415 - avoid import cycle

    out: Dict[str, Any] = {}
    for mesh in meshes:
        shapes = cmds.listRelatives(mesh, shapes=True, fullPath=True) or []
        for shape in shapes:
            for node in cmds.ls(cmds.listHistory(
                    shape, pruneDagObjects=True) or [],
                    type="blendShape") or []:
                for alias in blendshape._aliases(cmds, node):
                    if alias in out and out[alias] != node:
                        out[alias] = HandlerError(
                            "blendshape target %r exists on both %s and %s"
                            % (alias, out[alias], node),
                            hint="rename one target so the key is "
                                 "unambiguous")
                    elif alias not in out:
                        out[alias] = node
    return out


def _resolve_weight_channels(alias_map: Dict[str, Any],
                             keys: List[Dict[str, Any]]) -> List[str]:
    used: List[str] = []
    for i, key in enumerate(keys):
        for alias in key["blend_weights"]:
            resolved = alias_map.get(alias)
            if resolved is None:
                raise HandlerError(
                    "keys[%d].blend_weights[%r] is not a blendshape target "
                    "on any mesh bound to this skeleton" % (i, alias),
                    hint="targets here: %s"
                         % (", ".join(sorted(alias_map)) or "none"))
            if isinstance(resolved, HandlerError):
                raise resolved
            if alias not in used:
                used.append(alias)
    return used


def author_clip(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    from . import rigging  # noqa: PLC0415 - rigging imports clip for guards

    root_long = rigging._require_joint(cmds, params.get("root"))
    joints = rigging._hierarchy_joints(cmds, root_long)

    name = params.get("name")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise HandlerError(
            "name %r must be a plain identifier (letters, digits, "
            "underscore; not starting with a digit)" % (name,),
            hint="the name becomes the exported take name")
    fps = params.get("fps", 30)
    if (isinstance(fps, bool) or not isinstance(fps, int)
            or fps not in clipmath.FPS_UNITS):
        raise HandlerError(
            "fps must be one of %s"
            % ", ".join(str(k) for k in sorted(clipmath.FPS_UNITS)),
            hint="the frame rates Maya has native time units for; the "
                 "scene's time unit is set to match so keys land on frames")
    interpolation = params.get("interpolation", "linear")
    if interpolation not in INTERPOLATIONS:
        raise HandlerError(
            "unknown interpolation %r; one of: %s"
            % (interpolation, ", ".join(sorted(INTERPOLATIONS))),
            hint="'linear' for mechanical reads, 'smooth' (auto tangents) "
                 "for organic motion")
    loop = params.get("loop", False)
    if not isinstance(loop, bool):
        raise HandlerError("loop must be true or false",
                           hint="true validates that the last key closes "
                                "onto the first")

    keys = clipmath.validated_keys(params.get("keys"))

    # Resolve every name BEFORE the checkpoint - a bad call costs nothing.
    resolved_keys: List[Dict[str, Any]] = []
    for key in keys:
        resolved = dict(key)
        if key["rotations"]:
            resolved["rotations"] = rigging._resolve_rotations(
                cmds, joints, key["rotations"])
        resolved_keys.append(resolved)
    meshes = rigging._bound_meshes(cmds, set(joints))
    alias_map = _weight_alias_map(cmds, meshes)
    weight_channels = _resolve_weight_channels(alias_map, resolved_keys)

    if loop:
        violations = clipmath.loop_violations(resolved_keys[0],
                                              resolved_keys[-1])
        if violations:
            raise HandlerError(
                "loop=true but the clip does not close: %s"
                % "; ".join(violations[:4]),
                hint="a cycle whose last key differs from its first pops "
                     "on repeat in-engine; make the end key match the "
                     "start key, or drop loop")

    meta = clip_meta(cmds, root_long)
    weight_plugs = ["%s.%s" % (alias_map[a], a) for a in alias_map
                    if not isinstance(alias_map[a], HandlerError)]
    existing = _anim_curves(cmds, _joint_plugs(joints) + weight_plugs)
    if existing and meta is None:
        raise HandlerError(
            "this skeleton carries animation curves this tool did not "
            "author (%d driven channel(s), e.g. %s)"
            % (len(existing), sorted(existing)[0]),
            hint="replacing hand-authored animation silently would destroy "
                 "work; delete_clip removes it if that is intended")
    replaced = meta.get("name") if meta else None

    warnings: List[str] = []
    fractional = clipmath.fractional_frame_times(
        [k["time_s"] for k in resolved_keys], fps)
    if fractional:
        warnings.append(
            "key time(s) %s land between frames at %d fps - the baked "
            "export samples integer frames, so these keys are between "
            "samples" % (", ".join("%g" % t for t in fractional), fps))
    if not meshes:
        warnings.append(
            "no skinned mesh is bound to this skeleton - the clip moves "
            "bare joints only; bind_skin first if deformation was the point")

    session.auto_checkpoint("author_clip")

    if existing:
        doomed = sorted({c for curves in existing.values() for c in curves})
        cmds.delete(*doomed)
        if replaced:
            warnings.append("replaced clip %r (%d curves deleted)"
                            % (replaced, len(doomed)))

    prev_unit = cmds.currentUnit(query=True, time=True)
    unit = clipmath.FPS_UNITS[fps]
    if prev_unit != unit:
        cmds.currentUnit(time=unit)
        warnings.append("scene time unit changed %r -> %r so a frame is "
                        "1/%d s" % (prev_unit, unit, fps))

    keyed: List[tuple] = []   # (node, attr) pairs, for tangents
    for key in resolved_keys:
        frame = key["time_s"] * fps
        for joint, triple in key["rotations"].items():
            for attr, value in zip(ROTATE_ATTRS, triple):
                cmds.setKeyframe(joint, attribute=attr, time=frame,
                                 value=units.degrees_to_ui(cmds, value))
                keyed.append((joint, attr))
        if key["root_position"] is not None:
            cmds.xform(root_long, worldSpace=True,
                       translation=key["root_position"])
            local = [float(v) for v in cmds.xform(
                root_long, query=True, translation=True)]
            for attr, value in zip(TRANSLATE_ATTRS, local):
                cmds.setKeyframe(root_long, attribute=attr, time=frame,
                                 value=value)
                keyed.append((root_long, attr))
        for alias, value in key["blend_weights"].items():
            cmds.setKeyframe(alias_map[alias], attribute=alias, time=frame,
                             value=value)
            keyed.append((alias_map[alias], alias))

    tangent = INTERPOLATIONS[interpolation]
    for node, attr in sorted(set(keyed)):
        cmds.keyTangent(node, attribute=attr, edit=True,
                        inTangentType=tangent, outTangentType=tangent)

    # MEASURED duration (#636): the latest key on any authored plug, re-read
    # from the curves, never echoed from the input.
    last_frame = 0.0
    for node, attr in set(keyed):
        times = cmds.keyframe("%s.%s" % (node, attr), query=True) or []
        if times:
            last_frame = max(last_frame, max(times))
    duration_s = last_frame / fps
    frames = int(round(last_frame)) + 1
    cmds.playbackOptions(edit=True, minTime=0, maxTime=last_frame,
                         animationStartTime=0, animationEndTime=last_frame)

    # MEASURED per key: drive the time to each key's frame and read the
    # bound meshes against the evaluated FIRST key. Key 0 is 0 by
    # construction; a clip whose every later key is ~0 warns below.
    per_key: List[Dict[str, Any]] = []
    baselines: Dict[str, List[float]] = {}
    worst = 0.0
    cmds.currentTime(0)
    for mesh in meshes:
        baselines[mesh] = _points(mesh)
    for key in resolved_keys:
        cmds.currentTime(key["time_s"] * fps)
        disp = 0.0
        for mesh in meshes:
            disp = max(disp, sculpt_math.max_displacement(
                baselines[mesh], _points(mesh)))
        per_key.append({"time_s": key["time_s"], "max_displacement": disp})
        worst = max(worst, disp)
    cmds.currentTime(0)
    if meshes:
        extent = max(sculpt_math.bbox_extent(b) for b in baselines.values())
        if extent > 0 and worst < extent * 1e-2:
            warnings.append(
                "the clip's largest measured displacement is %.4g against "
                "a mesh of size %.4g - near-zero motion usually means the "
                "keys landed on joints that own no vertices"
                % (worst, extent))

    if not cmds.attributeQuery(CLIP_ATTR, node=root_long, exists=True):
        cmds.addAttr(root_long, longName=CLIP_ATTR, dataType="string")
    cmds.setAttr("%s.%s" % (root_long, CLIP_ATTR), json.dumps({
        "name": name, "fps": fps, "duration_s": duration_s, "loop": loop,
        "interpolation": interpolation,
        "joints": sorted({_short(j) for key in resolved_keys
                          for j in key["rotations"]}),
        "weight_channels": weight_channels,
        "root_position_used": any(k["root_position"] is not None
                                  for k in resolved_keys),
    }), type="string")

    return {
        "root": root_long,
        "clip": name,
        "fps": fps,
        "duration_s": duration_s,
        "frames": frames,
        "keyed_joints": len({j for key in resolved_keys
                             for j in key["rotations"]}),
        "keyed_weight_channels": weight_channels,
        "root_position_keyed": any(k["root_position"] is not None
                                   for k in resolved_keys),
        "interpolation": interpolation,
        "loop": loop,
        "replaced": replaced,
        "per_key": per_key,
        "warnings": warnings,
    }


def delete_clip(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    from . import rigging  # noqa: PLC0415

    root_long = rigging._require_joint(cmds, params.get("root"))
    joints = rigging._hierarchy_joints(cmds, root_long)
    meta = clip_meta(cmds, root_long)
    meshes = rigging._bound_meshes(cmds, set(joints))
    alias_map = _weight_alias_map(cmds, meshes)
    weight_plugs = ["%s.%s" % (node, a) for a, node in alias_map.items()
                    if not isinstance(node, HandlerError)]
    driven = _anim_curves(cmds, _joint_plugs(joints) + weight_plugs)
    if not driven and meta is None:
        raise HandlerError(
            "no clip exists on %s" % root_long,
            hint="author_clip creates one; this tool removes it")

    warnings: List[str] = []
    if meta is None and driven:
        warnings.append(
            "no clip metadata on %s - deleting %d hand-authored curve "
            "channel(s)" % (_short(root_long), len(driven)))

    session.auto_checkpoint("delete_clip")
    before = {m: _points(m) for m in meshes}

    doomed = sorted({c for curves in driven.values() for c in curves})
    if doomed:
        cmds.delete(*doomed)
    # Weights back to 0 (weights-all-0 IS the reset, the P5 rule), then the
    # skeleton back to bind - reset_pose's exact logic inline so this call
    # holds ONE checkpoint.
    for plug in weight_plugs:
        if plug in driven:
            cmds.setAttr(plug, 0.0)
    poses = cmds.dagPose(root_long, query=True, bindPose=True) or []
    if poses:
        cmds.dagPose(poses[0], restore=True, g=True)
        if len(poses) > 1:
            warnings.append("%d bind poses exist; restored %s"
                            % (len(poses), poses[0]))
    else:
        for joint in joints:
            cmds.setAttr(joint + ".rotate", 0.0, 0.0, 0.0)
        warnings.append(
            "no bind pose exists (nothing is bound); rotations zeroed, "
            "which is the create_skeleton rest pose")
    if cmds.attributeQuery(CLIP_ATTR, node=root_long, exists=True):
        cmds.deleteAttr("%s.%s" % (root_long, CLIP_ATTR))

    max_disp = 0.0
    for mesh in meshes:
        max_disp = max(max_disp, sculpt_math.max_displacement(
            before[mesh], _points(mesh)))
    return {
        "root": root_long,
        "clip": meta.get("name") if meta else None,
        "deleted_curves": len(doomed),
        "max_displacement": max_disp,
        "warnings": warnings,
    }
```

(`preview_clip` is Task 4 — do not stub it here; `naming` is imported for Task 4's use and flake will not complain because `clip_meta` uses none of it — if the linter flags the unused import, add it in Task 4 instead.)

- [ ] **Step 4: Register** — in `maya_plugin/maya_mcp_plugin.py`, add `clip` to the `from .handlers import (...)` list (alphabetical: after `capture`, before `code_exec` — match the file's ordering), and in `_build_handlers` after `"set_blendshape_weights"`:

```python
        "author_clip": clip.author_clip,
        "delete_clip": clip.delete_clip,
```

- [ ] **Step 5: Run to verify pass** — `uv run pytest tests/test_clip.py tests/test_clipmath.py -q --junitxml=$env:TEMP/p6t2.xml`, then the whole suite `uv run pytest -q --junitxml=$env:TEMP/p6full.xml`. Expected: PASS; count grows from 1244.

- [ ] **Step 6: Commit**

```bash
git add maya_plugin/handlers/clip.py maya_plugin/maya_mcp_plugin.py tests/test_clip.py
git commit -m "feat(#695): author_clip / delete_clip - one clip at a time, loop closure, measured per-key displacement"
```

---

### Task 3: Static mutators refuse while a clip exists

**Files:**
- Modify: `maya_plugin/handlers/rigging.py` (`pose_skeleton`, `pose_ik`, `reset_pose`), `maya_plugin/handlers/blendshape.py` (`set_blendshape_weights`)
- Test: `tests/test_rigging.py`, `tests/test_blendshape.py` (add a class each)

**Interfaces:**
- Consumes: Task 2's `clip.guard_static_pose` / `clip.guard_static_weights`.
- Produces: the ownership rule the design doc states. `create_blendshape` and the weight-craft tools are deliberately NOT guarded: they write skin weights or new unkeyed channels, which no curve owns.

- [ ] **Step 1: Write the failing tests.** In `tests/test_rigging.py`, find the existing FakeCmds used by the pose tests and add (adapting the fixture/scene helpers to that file's own idiom — its FakeCmds already models a joint hierarchy; add a `listConnections` that answers from a `curve_plugs` set attribute, defaulting to empty so every existing test still passes):

```python
class TestClipGuard:
    """#695: while animation curves drive the skeleton, static pose writes
    refuse - a value a curve overrides on the next frame change is the
    quietest way to lie about a pose."""

    def test_pose_skeleton_refuses_on_a_driven_skeleton(self, ...):
        # build the file's usual 2..3-joint scene, then:
        fake.curve_plugs = {"<root>|<child>.rotateZ"}
        with pytest.raises(HandlerError, match="animation curves"):
            rigging.pose_skeleton({"root": "<root>",
                                   "rotations": {"<child>": [0, 0, 10]}})

    def test_reset_pose_refuses_on_a_driven_skeleton(self, ...):
        fake.curve_plugs = {"<root>.rotateX"}
        with pytest.raises(HandlerError, match="delete_clip"):
            rigging.reset_pose({"root": "<root>"})

    def test_pose_ik_refuses_on_a_driven_skeleton(self, ...):
        fake.curve_plugs = {"<mid>.rotateY"}
        with pytest.raises(HandlerError, match="animation curves"):
            rigging.pose_ik({"root": "<root>", "joint": "<tip>",
                             "target": [1.0, 0.0, 0.0]})

    def test_an_undriven_skeleton_poses_exactly_as_before(self, ...):
        # no curve_plugs: the ordinary happy-path pose test body, unchanged
```

In `tests/test_blendshape.py`, extend its FakeCmds with the same defaulting `listConnections` and add:

```python
class TestClipGuard:
    def test_set_weights_refuses_on_a_keyed_channel(self, fake):
        _scene(fake)
        fake.deltas = {"blink": 0.2}
        node = _create(fake, [{"name": "blink",
                               "target_mesh": "brow"}])["blend_shape"]
        fake.curve_plugs = {"%s.blink" % node}
        with pytest.raises(HandlerError, match="animation curves"):
            blendshape.set_blendshape_weights(
                {"mesh": "humanoid", "weights": {"blink": 0.5}})

    def test_unkeyed_channels_still_write(self, fake):
        _scene(fake)
        fake.deltas = {"blink": 0.2}
        _create(fake, [{"name": "blink", "target_mesh": "brow"}])
        out = blendshape.set_blendshape_weights(
            {"mesh": "humanoid", "weights": {"blink": 0.5}})
        assert out["weights"]["blink"] == 0.5
```

The `listConnections` both fakes gain (identical in each):

```python
    def listConnections(self, plug, source=False, destination=True,
                        type=None):
        if plug in getattr(self, "curve_plugs", ()):
            return [plug.replace("|", "_").replace(".", "_") + "_crv"]
        return None
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_rigging.py tests/test_blendshape.py -q --junitxml=$env:TEMP/p6t3.xml`. Expected: the new tests FAIL (`AttributeError`/no refusal); every pre-existing test PASSES (the default-empty `curve_plugs` guarantees it).

- [ ] **Step 3: Implement.** In `rigging.py`, add `clip` to the module's `from . import ...` line (safe: `clip` imports `rigging` only lazily inside functions), then insert the guard immediately after joint resolution and BEFORE the checkpoint in all three mutators:

In `pose_skeleton`, after `joints = _hierarchy_joints(cmds, root_long)`:

```python
    clip.guard_static_pose(cmds, root_long, joints, "pose_skeleton")
```

In `pose_ik`, after `joints = _hierarchy_joints(cmds, root_long)`:

```python
    clip.guard_static_pose(cmds, root_long, joints, "pose_ik")
```

In `reset_pose`, after `joints = _hierarchy_joints(cmds, root_long)`:

```python
    clip.guard_static_pose(cmds, root_long, joints, "reset_pose")
```

In `blendshape.py`, add `clip` to the `from . import ...` line, and in `set_blendshape_weights` after `aliases = _aliases(cmds, node)`:

```python
    clip.guard_static_weights(cmds, node, aliases, "set_blendshape_weights")
```

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_rigging.py tests/test_blendshape.py tests/test_clip.py -q --junitxml=$env:TEMP/p6t3.xml`. Expected: PASS, including every pre-existing pose/weights test.

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/rigging.py maya_plugin/handlers/blendshape.py tests/test_rigging.py tests/test_blendshape.py
git commit -m "feat(#695): static pose/weight mutators refuse while a clip owns the channels"
```

---

### Task 4: preview_clip — frames through the existing render path

**Files:**
- Modify: `maya_plugin/handlers/render.py` (`_run_shots` learns `time` + `reuse_camera`), `maya_plugin/handlers/clip.py` (add `preview_clip`), `maya_plugin/maya_mcp_plugin.py` (register `"preview_clip"`)
- Test: `tests/test_clip.py` (add a class), `tests/test_render.py` (only if that file unit-tests `_run_shots` shot dicts — check; if not, the clip-side tests cover the seam)

**Interfaces:**
- Consumes: `render._run_shots`, `capture.VALID_ANGLES`, Task 2's `clip_meta`.
- Produces: `clip.preview_clip(params) -> {clip, fps, frames: [{frame, time_s}], images: [{label, angle, png_b64}], renderer, samples, ...}` (the `_run_shots` result plus `clip`/`fps`/`frames`). Task 7's server tool composites `images` into ONE contact sheet.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_clip.py`:

```python
class TestPreviewClip:
    """preview_clip picks frames and delegates to render._run_shots; the
    render loop itself is render.py's tested code. The seam is monkeypatched
    and its SHOTS are asserted - fixed camera, every-nth frames, first and
    last always included."""

    def _wire(self, fake, monkeypatch, duration_s=2.0, fps=30):
        _author(fake, name="idle", fps=fps, keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": duration_s, "rotations": {"mid": [0, 0, 0]}}])
        calls = {}

        def run_shots(cmds, shots, params):
            calls["shots"] = shots
            calls["params"] = params
            return {"images": [{"label": s["label"], "angle": s["angle"],
                                "png_b64": "x"} for s in shots],
                    "renderer": "hw2", "samples": 1, "fallback_light": False,
                    "zoom": 1.0, "relit_lights": 0}

        monkeypatch.setattr(clip.render, "_run_shots", run_shots)
        return calls

    def test_refusals(self, fake, monkeypatch):
        with pytest.raises(HandlerError, match="no clip"):
            clip.preview_clip({"root": "root", "name": "idle"})
        self._wire(fake, monkeypatch)
        with pytest.raises(HandlerError, match="live clip is 'idle'"):
            clip.preview_clip({"root": "root", "name": "walk"})
        with pytest.raises(HandlerError, match="unknown angle"):
            clip.preview_clip({"root": "root", "name": "idle",
                               "angle": "dutch"})
        with pytest.raises(HandlerError, match="every_nth"):
            clip.preview_clip({"root": "root", "name": "idle",
                               "every_nth": 0})

    def test_default_stride_fits_the_cap_and_keeps_the_ends(self, fake,
                                                            monkeypatch):
        calls = self._wire(fake, monkeypatch, duration_s=2.0, fps=30)
        out = clip.preview_clip({"root": "root", "name": "idle"})
        frames = [f["frame"] for f in out["frames"]]
        assert frames[0] == 0 and frames[-1] == 60
        assert len(frames) <= clip.MAX_PREVIEW_FRAMES
        shots = calls["shots"]
        assert shots[0]["time"] == 0 and shots[-1]["time"] == 60
        assert not shots[0].get("reuse_camera")
        assert all(s.get("reuse_camera") for s in shots[1:])
        assert all(s["frame_on"] == ["|body"] for s in shots)

    def test_explicit_stride_that_overflows_refuses(self, fake, monkeypatch):
        self._wire(fake, monkeypatch, duration_s=2.0, fps=30)
        with pytest.raises(HandlerError, match="%d frame"
                           % clip.MAX_PREVIEW_FRAMES):
            clip.preview_clip({"root": "root", "name": "idle",
                               "every_nth": 1})

    def test_current_time_is_restored(self, fake, monkeypatch):
        self._wire(fake, monkeypatch)
        fake.time = 7.0
        clip.preview_clip({"root": "root", "name": "idle"})
        assert fake.time == 7.0

    def test_unbound_skeleton_refuses(self, fake, monkeypatch):
        self._wire(fake, monkeypatch)
        fake.bound = False
        with pytest.raises(HandlerError, match="no skinned mesh"):
            clip.preview_clip({"root": "root", "name": "idle"})
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_clip.py -q --junitxml=$env:TEMP/p6t4.xml`. Expected: new tests FAIL (`preview_clip` missing).

- [ ] **Step 3: Implement the `_run_shots` extension** — in `render.py`, inside `_run_shots`:

**(a)** After `prev_undo = cmds.undoInfo(query=True, state=True)`, snapshot the time (only when any shot travels):

```python
    prev_time = (cmds.currentTime(query=True)
                 if any(s.get("time") is not None for s in shots) else None)
```

**(b)** At the top of the per-shot loop body (before the visibility block):

```python
            if shot.get("time") is not None:
                cmds.currentTime(shot["time"])
```

**(c)** Guard the camera-placement block: a preview judges MOTION, so the camera must hold still while the subject moves — a camera chasing the per-frame bbox would hide root motion entirely. Wrap the placement (`bbox_min.. = capture._scene_bbox` through both `cmds.setAttr(temp_camera + ".translate"/".rotate", ...)` lines, and the `_orient_rig` call) in:

```python
            if not (shot.get("reuse_camera") and temp_camera is not None):
                ...existing placement block, unchanged, indented...
```

(The `temp_camera is None` creation branch stays inside the guarded block — the first shot always places.)

**(d)** In the `finally`, before `state.restore()`:

```python
        if prev_time is not None:
            try:
                cmds.currentTime(prev_time)
            except Exception:
                pass
```

- [ ] **Step 4: Implement `preview_clip`** — append to `clip.py` (and add `capture`, `render` to its `from . import ...` line — both are import-safe headless):

```python
def preview_clip(params: Dict[str, Any]) -> Dict[str, Any]:
    """A contact sheet of the clip's frames - motion judged the way
    everything here is judged, from pixels, with NO playblast dependency.

    The camera is placed once, at frame 0's framing, and HELD: motion must
    read against a fixed frame, and a camera chasing the subject would hide
    root motion entirely. Perception: no checkpoint, current time restored.
    """
    cmds = _cmds()
    from . import rigging  # noqa: PLC0415

    root_long = rigging._require_joint(cmds, params.get("root"))
    meta = clip_meta(cmds, root_long)
    if meta is None or not meta.get("name"):
        raise HandlerError(
            "no clip exists on %s" % root_long,
            hint="author_clip creates one; preview_clip renders it")
    name = params.get("name")
    if name != meta["name"]:
        raise HandlerError(
            "the live clip is %r, not %r" % (meta["name"], name),
            hint="pass the clip's own name - previewing a stale assumption "
                 "judges the wrong motion")
    fps = int(meta.get("fps", 30))
    duration_frames = int(round(float(meta.get("duration_s", 0.0)) * fps))
    if duration_frames <= 0:
        raise HandlerError("the clip has zero duration",
                           hint="re-author it; this is a broken metadata "
                                "state, not a render problem")

    angle = params.get("angle") or "three_quarter"
    if angle not in capture.VALID_ANGLES:
        raise HandlerError("unknown angle %r" % angle,
                           hint="valid angles: %s"
                                % ", ".join(capture.VALID_ANGLES))
    every_nth = params.get("every_nth")
    if every_nth is None:
        every_nth = 1
        while duration_frames // every_nth + 1 > MAX_PREVIEW_FRAMES:
            every_nth += 1
    elif (isinstance(every_nth, bool) or not isinstance(every_nth, int)
            or every_nth < 1):
        raise HandlerError("every_nth must be an integer >= 1",
                           hint="omit it for the densest sheet that fits")
    frames = list(range(0, duration_frames + 1, every_nth))
    if frames[-1] != duration_frames:
        frames.append(duration_frames)   # the last frame always shows
    if len(frames) > MAX_PREVIEW_FRAMES:
        raise HandlerError(
            "every_nth=%d yields %d frames; the cap is %d frames per sheet"
            % (every_nth, len(frames), MAX_PREVIEW_FRAMES),
            hint="raise every_nth, or omit it to auto-fit")

    joints = rigging._hierarchy_joints(cmds, root_long)
    meshes = rigging._bound_meshes(cmds, set(joints))
    if not meshes:
        raise HandlerError(
            "no skinned mesh is bound to this skeleton - bare joints "
            "render nothing",
            hint="bind_skin first; the preview frames the bound meshes")

    render_params = {
        "renderer": params.get("renderer", "hw2"),
        "resolution": params.get("resolution",
                                 DEFAULT_PREVIEW_RESOLUTION),
        "samples": params.get("samples", 1),
        "zoom": params.get("zoom", 1.0),
    }
    shots = []
    for i, frame in enumerate(frames):
        shots.append({
            "label": "t=%.2fs" % (frame / float(fps)),
            "angle": angle,
            "isolate": None,
            "frame_on": meshes,
            "time": frame,
            "reuse_camera": i > 0,
        })
    result = render._run_shots(cmds, shots, render_params)
    result["clip"] = meta["name"]
    result["fps"] = fps
    result["frames"] = [{"frame": f, "time_s": f / float(fps)}
                        for f in frames]
    return result


preview_clip.no_undo_chunk = True
```

- [ ] **Step 5: Register** — in `maya_mcp_plugin.py` `_build_handlers`, after `"delete_clip"`:

```python
        "preview_clip": clip.preview_clip,
```

- [ ] **Step 6: Run to verify pass** — `uv run pytest tests/test_clip.py -q --junitxml=$env:TEMP/p6t4.xml`, then `uv run pytest -q --junitxml=$env:TEMP/p6full.xml` (render.py's existing tests must be untouched by the `_run_shots` edit — no shot in any existing caller carries `time`/`reuse_camera`, so behavior is identical).

- [ ] **Step 7: Commit**

```bash
git add maya_plugin/handlers/clip.py maya_plugin/handlers/render.py maya_plugin/maya_mcp_plugin.py tests/test_clip.py
git commit -m "feat(#695): preview_clip - fixed-camera frame sheet through the existing render path"
```

---

### Task 5: fbxbytes reads animation records

**Files:**
- Modify: `maya_plugin/handlers/fbxbytes.py`
- Test: `tests/test_fbxbytes.py` (add a class)

**Interfaces:**
- Consumes: nothing new.
- Produces: `FbxFacts.anim_curves` (`{uid: {"key_count", "first_tick", "last_tick"}}`), `FbxFacts.anim_nodes` (`{uid: {"name", "target", "target_kind", "property", "curves"}}`), `FbxFacts.anim_stacks` (int), `FbxFacts.anim_layers` (set of uids), `FbxFacts.takes` (`[{"name", "start_tick", "stop_tick"}]`), `KTIME_PER_SECOND`, and `fbxbytes.anim_facts(facts) -> {"stacks", "layers", "curves", "curve_nodes", "takes": [{"name", "duration_s"}], "targets": [{"target", "property", "curves", "key_count", "duration_s"}], "unavailable_reason"}` (Task 6 gates on it, Task 7's schema mirrors it).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_fbxbytes.py`:

```python
class TestAnimFacts:
    """Animation records (#695). Synthetic facts here; that these shapes
    match what Maya WRITES - tick size, property strings, take naming - is
    pinned under mayapy (TestClipExportInMaya)."""

    def _facts(self):
        facts = FbxFacts(version=7500)
        facts.nodes.append(FbxNode(name="L_hip", kind="LimbNode", uid=1))
        tick = fbxbytes.KTIME_PER_SECOND
        facts.anim_curves[10] = {"key_count": 31, "first_tick": 0,
                                 "last_tick": tick}
        facts.anim_curves[11] = {"key_count": 31, "first_tick": 0,
                                 "last_tick": tick}
        facts.anim_curves[12] = {"key_count": 31, "first_tick": 0,
                                 "last_tick": tick}
        facts.anim_nodes[20] = {"name": "R", "target": 1,
                                "target_kind": "model",
                                "property": "Lcl Rotation",
                                "curves": [10, 11, 12]}
        facts.anim_stacks = 1
        facts.anim_layers = {30}
        facts.takes = [{"name": "walk", "start_tick": 0, "stop_tick": tick}]
        return facts

    def test_a_healthy_file_reads_clean(self):
        out = fbxbytes.anim_facts(self._facts())
        assert out["stacks"] == 1 and out["layers"] == 1
        assert out["curves"] == 3 and out["curve_nodes"] == 1
        assert out["takes"] == [{"name": "walk", "duration_s": 1.0}]
        assert out["targets"] == [{"target": "L_hip",
                                   "property": "Lcl Rotation", "curves": 3,
                                   "key_count": 31, "duration_s": 1.0}]
        assert out["unavailable_reason"] is None

    def test_a_channel_target_reads_by_alias(self):
        facts = self._facts()
        facts.blend_channels[40] = {"name": "shapes.blink", "shape": None,
                                    "deformer": None}
        facts.anim_curves[13] = {"key_count": 5, "first_tick": 0,
                                 "last_tick": fbxbytes.KTIME_PER_SECOND}
        facts.anim_nodes[21] = {"name": "DeformPercent", "target": 40,
                                "target_kind": "channel",
                                "property": "DeformPercent",
                                "curves": [13]}
        out = fbxbytes.anim_facts(facts)
        by = {(t["target"], t["property"]): t for t in out["targets"]}
        assert by[("blink", "DeformPercent")]["key_count"] == 5

    def test_orphans_and_mismatches_are_reasons_never_guesses(self):
        facts = self._facts()
        facts.anim_nodes[21] = {"name": "T", "target": None,
                                "target_kind": None, "property": None,
                                "curves": []}
        facts.anim_curves[11]["key_count"] = 30
        out = fbxbytes.anim_facts(facts)
        assert "drives nothing" in out["unavailable_reason"]
        assert "disagree on key count" in out["unavailable_reason"]
        by = {t["target"]: t for t in out["targets"] if t["target"]}
        assert by["L_hip"]["key_count"] is None

    def test_an_animation_less_facts_reads_empty(self):
        out = fbxbytes.anim_facts(FbxFacts(version=7500))
        assert out == {"stacks": 0, "layers": 0, "curves": 0,
                       "curve_nodes": 0, "takes": [], "targets": [],
                       "unavailable_reason": None}
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_fbxbytes.py -q --junitxml=$env:TEMP/p6t5.xml`. Expected: FAIL (unknown fields / `anim_facts` missing).

- [ ] **Step 3: Implement.** Edits inside `fbxbytes.py`:

**(a)** `FbxFacts` gains, after `blend_deformers`:

```python
    # Animation (#602 phase 6 / #695). anim_curves: AnimationCurve uid ->
    # {"key_count", "first_tick", "last_tick"} - counts and endpoints only,
    # never the arrays (a 61-frame bake x 60+ curves of floats is memory
    # nothing asks about). anim_nodes: AnimationCurveNode uid -> {"name",
    # "target" uid, "target_kind" "model"|"channel"|None, "property" (the
    # OP-connection property string, e.g. "Lcl Rotation"), "curves": [uid]}.
    # takes come from the Takes section: name + LocalTime endpoint ticks.
    anim_curves: dict = field(default_factory=dict)
    anim_nodes: dict = field(default_factory=dict)
    anim_stacks: int = 0
    anim_layers: set = field(default_factory=set)
    takes: list = field(default_factory=list)
```

**(b)** After the `DECLARES_METRES` constant (or near the top with the other constants):

```python
# FBX KTime: ticks per second. The SDK constant; PINNED against a real Maya
# export of a clip with a measured duration (TestClipExportInMaya) rather
# than trusted from documentation.
KTIME_PER_SECOND = 46186158000
```

**(c)** In `read_fbx`, the property decode grows two gated wants. Change the `prop` signature and array branch:

```python
    def prop(pos, want_ints=False, want_longs=False, want_floats=False):
        ...
        if code in _ARRAYS:
            length, encoding, comp = struct.unpack_from("<III", data, pos)
            pos += 12
            payload = data[pos:pos + comp]
            pos += comp
            fmt = None
            if code == b"d":
                fmt = "<%dd"
            elif want_ints and code == b"i":
                fmt = "<%di"
            elif want_longs and code == b"l":
                fmt = "<%dq"
            elif want_floats and code == b"f":
                fmt = "<%df"
            if fmt is not None:
                raw = zlib.decompress(payload) if encoding == 1 else payload
                return struct.unpack(fmt % length, raw), pos
            return None, pos
```

and the call site becomes:

```python
                val, pos = prop(pos, want_ints=(name == "Indexes"),
                                want_longs=(name == "KeyTime"),
                                want_floats=False)
```

(`KeyValueFloat` stays undecoded on purpose — nothing reads baked values from the bytes, only counts and times; decoding them would be memory for numbers nothing asks about. If Task 6's measurement ever needs a value, gate it then.)

**(d)** In `walk`, new record arms in the `Model`/`Geometry`/`Deformer` elif chain:

```python
            elif name == "AnimationCurve":
                uid = values[0] if values and isinstance(values[0], int) else None
                if uid is not None:
                    facts.anim_curves[uid] = {"key_count": 0,
                                              "first_tick": None,
                                              "last_tick": None}
                    child = ("acurve", uid)
            elif name == "AnimationCurveNode":
                uid = values[0] if values and isinstance(values[0], int) else None
                strs = [v for v in values if isinstance(v, str)]
                if uid is not None:
                    facts.anim_nodes[uid] = {
                        "name": _clean(strs[0]) if strs else "?",
                        "target": None, "target_kind": None,
                        "property": None, "curves": []}
                    child = ("anode", uid)
            elif name == "AnimationStack":
                facts.anim_stacks += 1
            elif name == "AnimationLayer":
                uid = values[0] if values and isinstance(values[0], int) else None
                if uid is not None:
                    facts.anim_layers.add(uid)
            elif name == "Take":
                strs = [v for v in values if isinstance(v, str)]
                facts.takes.append({"name": _clean(strs[0]) if strs else "?",
                                    "start_tick": None, "stop_tick": None})
                child = ("take", len(facts.takes) - 1)
```

data arms alongside the cluster/shape `Indexes` arms:

```python
            elif (name == "KeyTime" and isinstance(node, tuple)
                    and node[0] == "acurve" and values
                    and isinstance(values[0], tuple)):
                ticks = values[0]
                rec = facts.anim_curves[node[1]]
                rec["key_count"] = len(ticks)
                rec["first_tick"] = ticks[0] if ticks else None
                rec["last_tick"] = ticks[-1] if ticks else None
            elif (name == "LocalTime" and isinstance(node, tuple)
                    and node[0] == "take" and len(values) >= 2
                    and all(isinstance(v, int) for v in values[:2])):
                facts.takes[node[1]]["start_tick"] = values[0]
                facts.takes[node[1]]["stop_tick"] = values[1]
```

**(e)** Connections carry the OP property string now. The `C` arm becomes:

```python
            elif name == "C" and len(values) >= 3:
                _connections.append(
                    (values[1], values[2],
                     values[3] if len(values) > 3
                     and isinstance(values[3], str) else None))
```

the loop header becomes `for child, parent, link_prop in _connections:` (every existing arm ignores `link_prop`), and three arms join the END of the chain:

```python
        elif child in facts.anim_curves and parent in facts.anim_nodes:
            facts.anim_nodes[parent]["curves"].append(child)
        elif child in facts.anim_nodes and parent in by_uid:
            facts.anim_nodes[child]["target"] = parent
            facts.anim_nodes[child]["target_kind"] = "model"
            facts.anim_nodes[child]["property"] = link_prop
        elif child in facts.anim_nodes and parent in facts.blend_channels:
            facts.anim_nodes[child]["target"] = parent
            facts.anim_nodes[child]["target_kind"] = "channel"
            facts.anim_nodes[child]["property"] = link_prop
```

(AnimationCurveNode→AnimationLayer and Layer→Stack connections fall through every arm and are dropped — the layer/stack COUNTS are the facts; membership adds nothing a violation would read.)

**(f)** New function after `shape_facts`:

```python
def anim_facts(facts):
    """What the file's animation records hold. Reading, not policy (#645).

    Per curve node: the Model (joint) or BlendShapeChannel it drives, the
    OP-connection property that says WHICH plug ("Lcl Rotation",
    "Lcl Translation", "DeformPercent" - measured under mayapy,
    TestClipExportInMaya), the curve count and their agreed key count.
    Structural failures - an orphan curve node, curves that disagree on key
    count - are reasons, never guesses; POLICY (expected counts, take
    naming, zero-when-off) lives in export.anim_violations.
    """
    reasons = []
    targets = []
    by_uid = {n.uid: n for n in facts.nodes if n.uid is not None}
    for uid, node in sorted(facts.anim_nodes.items()):
        entry = {"target": None,
                 "property": (node["property"] or node["name"]),
                 "curves": len(node["curves"]),
                 "key_count": None, "duration_s": None}
        if node["target_kind"] == "model" and node["target"] in by_uid:
            entry["target"] = by_uid[node["target"]].name
        elif (node["target_kind"] == "channel"
                and node["target"] in facts.blend_channels):
            entry["target"] = (facts.blend_channels[node["target"]]["name"]
                               .split(".")[-1])
        else:
            reasons.append("curve node %r drives nothing this reader holds"
                           % node["name"])
        counts = set()
        first = []
        last = []
        for cuid in node["curves"]:
            curve = facts.anim_curves.get(cuid)
            if curve is None:
                continue
            counts.add(curve["key_count"])
            if curve["first_tick"] is not None:
                first.append(curve["first_tick"])
            if curve["last_tick"] is not None:
                last.append(curve["last_tick"])
        if len(counts) == 1:
            entry["key_count"] = counts.pop()
            if first and last:
                entry["duration_s"] = ((max(last) - min(first))
                                       / float(KTIME_PER_SECOND))
        elif counts:
            reasons.append(
                "curve node %r's curves disagree on key count (%s)"
                % (node["name"],
                   ", ".join(str(c) for c in sorted(counts))))
        targets.append(entry)
    takes = []
    for take in facts.takes:
        duration = None
        if (take["start_tick"] is not None
                and take["stop_tick"] is not None):
            duration = ((take["stop_tick"] - take["start_tick"])
                        / float(KTIME_PER_SECOND))
        takes.append({"name": take["name"], "duration_s": duration})
    return {
        "stacks": facts.anim_stacks,
        "layers": len(facts.anim_layers),
        "curves": len(facts.anim_curves),
        "curve_nodes": len(facts.anim_nodes),
        "takes": takes,
        "targets": sorted(targets,
                          key=lambda e: (e["target"] or "", e["property"])),
        "unavailable_reason": "; ".join(reasons) or None,
    }
```

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_fbxbytes.py tests/test_export_fbx.py -q --junitxml=$env:TEMP/p6t5.xml`. Expected: PASS including every pre-existing test (the committed-artifact fixtures carry no animation records, so every new field stays empty on them — that IS the regression assertion).

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/fbxbytes.py tests/test_fbxbytes.py
git commit -m "feat(#695): fbxbytes reads AnimationCurve/CurveNode/Takes records - counts and ticks, never the arrays"
```

---

### Task 6: Export — include_animation, both states pinned, byte-gated

**Files:**
- Modify: `maya_plugin/handlers/export.py`
- Test: `tests/test_export_fbx.py` (add a class)

**Interfaces:**
- Consumes: Task 5's `anim_facts`, Task 2's `clip.clip_meta` / `clip.CLIP_ATTR`.
- Produces: `export.FBX_ANIM_MEL`, `export._scene_clip(cmds) -> Optional[dict]`, `export.anim_violations(afacts, declared) -> List[str]` (declared=None means include_animation was False); `export_fbx`'s result gains `"animation"` (the `anim_facts` dict when `include_animation=True`, else `None`). Task 7's `AnimFacts` schema mirrors the dict exactly.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_export_fbx.py`:

```python
class TestAnimViolations:
    """#695: the include_animation contract, judged from the BYTES against
    what the SCENE's clip metadata declared."""

    def _declared(self):
        return {"name": "walk", "fps": 30, "duration_s": 1.0,
                "root": "pelvis", "joints": ["L_hip"],
                "weight_channels": ["blink"], "root_position_used": True}

    def _clean(self):
        return {"stacks": 1, "layers": 1, "curves": 7, "curve_nodes": 3,
                "takes": [{"name": "walk", "duration_s": 1.0}],
                "targets": [
                    {"target": "L_hip", "property": "Lcl Rotation",
                     "curves": 3, "key_count": 31, "duration_s": 1.0},
                    {"target": "pelvis", "property": "Lcl Translation",
                     "curves": 3, "key_count": 31, "duration_s": 1.0},
                    {"target": "blink", "property": "DeformPercent",
                     "curves": 1, "key_count": 5, "duration_s": 1.0},
                ],
                "unavailable_reason": None}

    def test_a_matching_file_passes(self):
        assert export.anim_violations(self._clean(), self._declared()) == []

    def test_include_animation_false_asserts_zero_curves(self):
        empty = {"stacks": 0, "layers": 0, "curves": 0, "curve_nodes": 0,
                 "takes": [], "targets": [], "unavailable_reason": None}
        assert export.anim_violations(empty, None) == []
        out = export.anim_violations(self._clean(), None)
        assert any("include_animation" in v for v in out)

    def test_take_name_and_duration_gate(self):
        afacts = self._clean()
        afacts["takes"] = [{"name": "Take 001", "duration_s": 1.0}]
        out = export.anim_violations(afacts, self._declared())
        assert any("Take 001" in v and "'walk'" in v for v in out)
        afacts = self._clean()
        afacts["takes"][0]["duration_s"] = 0.5
        out = export.anim_violations(afacts, self._declared())
        assert any("duration" in v for v in out)
        afacts = self._clean()
        afacts["takes"] = []
        out = export.anim_violations(afacts, self._declared())
        assert any("0 takes" in v for v in out)

    def test_missing_and_miscounted_joint_curves_fail(self):
        afacts = self._clean()
        afacts["targets"] = [t for t in afacts["targets"]
                             if t["target"] != "L_hip"]
        out = export.anim_violations(afacts, self._declared())
        assert any("L_hip" in v and "no rotation curves" in v for v in out)
        afacts = self._clean()
        afacts["targets"][0]["key_count"] = 30
        out = export.anim_violations(afacts, self._declared())
        assert any("L_hip" in v and "31" in v and "30" in v for v in out)
        afacts = self._clean()
        afacts["targets"][0]["curves"] = 2
        out = export.anim_violations(afacts, self._declared())
        assert any("L_hip" in v and "2 curve" in v for v in out)

    def test_root_translation_gates_only_when_used(self):
        afacts = self._clean()
        afacts["targets"] = [t for t in afacts["targets"]
                             if t["property"] != "Lcl Translation"]
        out = export.anim_violations(afacts, self._declared())
        assert any("root" in v and "translation" in v for v in out)
        declared = dict(self._declared(), root_position_used=False)
        assert export.anim_violations(afacts, declared) == []

    def test_weight_channels_gate_presence_not_count(self):
        # Whether Maya bakes DeformPercent curves or carries them as
        # authored is a mayapy measurement (contract decision 10) - so the
        # gate is presence + >=2 keys, never a full frame count.
        afacts = self._clean()
        afacts["targets"] = [t for t in afacts["targets"]
                             if t["property"] != "DeformPercent"]
        out = export.anim_violations(afacts, self._declared())
        assert any("blink" in v for v in out)
        afacts = self._clean()
        afacts["targets"][2]["key_count"] = 1
        out = export.anim_violations(afacts, self._declared())
        assert any("blink" in v and "1 key" in v for v in out)

    def test_extra_targets_are_not_violations(self):
        afacts = self._clean()
        afacts["targets"].append(
            {"target": "hand_keyed", "property": "Lcl Rotation",
             "curves": 3, "key_count": 31, "duration_s": 1.0})
        assert export.anim_violations(afacts, self._declared()) == []

    def test_unreadable_records_fail(self):
        afacts = self._clean()
        afacts["unavailable_reason"] = "curve node 'T' drives nothing"
        out = export.anim_violations(afacts, self._declared())
        assert any("unreadable" in v for v in out)

    def test_the_anim_preamble_is_pinned_both_ways(self):
        assert export.FBX_ANIM_MEL[False] == (
            'FBXProperty "Export|IncludeGrp|Animation" -v false',
            "FBXExportBakeComplexAnimation -v false",
        )
        assert export.FBX_ANIM_MEL[True] == (
            'FBXProperty "Export|IncludeGrp|Animation" -v true',
            "FBXExportBakeComplexAnimation -v true",
            "FBXExportBakeComplexStep -v 1",
        )
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_export_fbx.py -q --junitxml=$env:TEMP/p6t6.xml`. Expected: FAIL (`anim_violations` missing).

- [ ] **Step 3: Implement.** In `export.py`:

**(a)** Module imports gain `import json` and `from . import clip as clip_mod` (clip.py is headless-importable — its Maya import is lazy).

**(b)** After `FBX_SHAPES_MEL`:

```python
# Animation export, both states explicit so FBXResetExport's defaults never
# decide it. OFF is pinned as hard as ON (#695 design decision): a scene
# CARRYING curves exported with include_animation=false must be
# byte-equivalent to a static export - the byte gate asserts zero curve
# records in that case, the symmetric assertion. The bake range (start/end)
# and take naming are per-call values, composed in export_fbx.
FBX_ANIM_MEL = {
    True: ('FBXProperty "Export|IncludeGrp|Animation" -v true',
           "FBXExportBakeComplexAnimation -v true",
           "FBXExportBakeComplexStep -v 1"),
    False: ('FBXProperty "Export|IncludeGrp|Animation" -v false',
            "FBXExportBakeComplexAnimation -v false"),
}
```

**(c)** `_validate` gains, after the `include_skins` block (and its return becomes a 4-tuple; update the unpack in `export_fbx`):

```python
    include_animation = params.get("include_animation", False)
    if not isinstance(include_animation, bool):
        raise HandlerError(
            "include_animation must be true or false, got %r"
            % (include_animation,),
            hint="true bakes the authored clip to per-frame curves and "
                 "names the take after it")
```

**(d)** New helpers after `shape_violations`:

```python
def _scene_clip(cmds):
    """The clip metadata maya_author_clip stamped, or None. More than one
    clip-carrying root refuses: one clip at a time is per-skeleton, and one
    FILE is one take - exporting two at once has no honest take name."""
    roots = [j for j in cmds.ls(type="joint", long=True) or []
             if cmds.attributeQuery(clip_mod.CLIP_ATTR, node=j, exists=True)]
    if not roots:
        return None
    if len(roots) > 1:
        raise HandlerError(
            "%d skeletons carry a clip (%s) - one file is one take"
            % (len(roots), ", ".join(r.split("|")[-1] for r in roots)),
            hint="delete_clip the skeletons not being exported")
    meta = clip_mod.clip_meta(cmds, roots[0]) or {}
    meta["root"] = roots[0].split("|")[-1]
    return meta


def anim_violations(afacts, declared) -> List[str]:
    """Ways the animation records break the include_animation contract.

    declared=None means include_animation was FALSE: the file must carry
    ZERO curve records even when the scene is animated - the symmetric
    assertion that keeps static exports of animated scenes byte-honest.
    Extra targets are NOT violations (the shape_violations precedent);
    missing declared ones are.
    """
    out: List[str] = []
    if declared is None:
        if afacts["curves"] or afacts["curve_nodes"]:
            out.append(
                "the file carries %d animation curves without "
                "include_animation - the animation pin failed"
                % afacts["curves"])
        return out
    if afacts["unavailable_reason"]:
        out.append("animation records unreadable: %s"
                   % afacts["unavailable_reason"])
    if len(afacts["takes"]) != 1:
        out.append("the file carries %d takes, expected exactly 1"
                   % len(afacts["takes"]))
    else:
        take = afacts["takes"][0]
        if take["name"] != declared["name"]:
            out.append("the take is named %r, the clip is %r"
                       % (take["name"], declared["name"]))
        tol = 1.0 / declared["fps"]
        if (take["duration_s"] is None
                or abs(take["duration_s"] - declared["duration_s"]) > tol):
            out.append(
                "the take's duration is %s s, the clip declares %g s"
                % (take["duration_s"], declared["duration_s"]))
    expected = int(round(declared["duration_s"] * declared["fps"])) + 1
    by = {}
    for t in afacts["targets"]:
        by.setdefault((t["target"], t["property"]), t)
    for joint in declared["joints"]:
        t = by.get((joint, "Lcl Rotation"))
        if t is None:
            out.append("joint %r has no rotation curves in the file" % joint)
            continue
        if t["curves"] != 3:
            out.append("joint %r carries %d curve(s), expected 3 (X, Y, Z)"
                       % (joint, t["curves"]))
        if t["key_count"] != expected:
            out.append("joint %r bakes %s keys, expected %d"
                       % (joint, t["key_count"], expected))
    if declared.get("root_position_used"):
        t = by.get((declared["root"], "Lcl Translation"))
        if t is None:
            out.append("the clip keys the root's position but the file "
                       "carries no root translation curves")
        elif t["key_count"] != expected:
            out.append("root translation bakes %s keys, expected %d"
                       % (t["key_count"], expected))
    for alias in declared.get("weight_channels", []):
        t = by.get((alias, "DeformPercent"))
        if t is None:
            out.append("weight channel %r has no curves in the file" % alias)
        elif (t["key_count"] or 0) < 2:
            out.append("weight channel %r carries %s key(s), expected at "
                       "least 2" % (alias, t["key_count"]))
    return out
```

**(e)** Wire into `export_fbx`. After `declared_shapes = _scene_shape_aliases(cmds, nodes)`:

```python
    declared_clip = _scene_clip(cmds) if include_animation else None
    if include_animation and declared_clip is None:
        raise HandlerError(
            "include_animation=true but no clip exists",
            hint="author_clip keys the motion first; a static export needs "
                 "no flag at all")
```

The preamble loop gains the animation tuple and, when exporting animation, the per-call bake range and take naming (after the loop, before `FBXExportScaleFactor`):

```python
    for statement in (FBX_PREAMBLE_MEL + FBX_SCENE_CONTENT_MEL
                      + FBX_SHAPES_MEL + FBX_SKINS_MEL[include_skins]
                      + FBX_ANIM_MEL[include_animation]):
        mel.eval(statement)
    if include_animation:
        end_frame = int(round(declared_clip["duration_s"]
                              * declared_clip["fps"]))
        mel.eval("FBXExportBakeComplexStart -v 0")
        mel.eval("FBXExportBakeComplexEnd -v %d" % end_frame)
        # The take is NAMED AFTER THE CLIP. Maya's default take name is its
        # own; SplitAnimationIntoTakes overrides it - MEASURED under mayapy
        # (TestClipExportInMaya). If that measurement finds a different
        # mechanism, fix it there and record the measured behavior.
        mel.eval("FBXExportSplitAnimationIntoTakes -clear")
        mel.eval('FBXExportSplitAnimationIntoTakes -v "%s" 0 %d'
                 % (declared_clip["name"], end_frame))
```

After the shapes block (`violations += shape_bad`):

```python
    anim_block = fbxbytes.anim_facts(facts)
    anim_bad = anim_violations(anim_block,
                               declared_clip if include_animation else None)
    violations += anim_bad
    anim_hint = (
        " For animation violations: the clip must exist (maya_author_clip) "
        "and a selected export ('nodes') must include the skeleton root - "
        "curves travel with their joints." if anim_bad else "")
```

Append `+ anim_hint` at both raise sites (alongside `skin_hint + shape_hint`). In the returned dict, after `"shapes": ...`:

```python
        "animation": anim_block if include_animation else None,
```

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_export_fbx.py tests/test_fbxbytes.py -q --junitxml=$env:TEMP/p6t6.xml`. Expected: PASS including every pre-existing export test (static exports: `include_animation` defaults False, `_scene_clip` never runs, `anim_violations` sees empty facts and returns `[]`, `animation` is `None`).

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/export.py tests/test_export_fbx.py
git commit -m "feat(#695): include_animation - baked take named after the clip, zero-curves asserted when off"
```

---

### Task 7: The real-Maya leg (mayapy) — behavior and THE MEASUREMENTS

**Files:**
- Test: `tests/test_handlers_mayapy.py` (add two classes at the end)
- Possibly modify (only if a measurement forces it): `maya_plugin/handlers/fbxbytes.py`, `maya_plugin/handlers/export.py`

**Interfaces:**
- Consumes: Tasks 1–6.
- Produces: the MEASURED pins this phase's byte gate rests on: (1) the tick constant, (2) the OP property strings, (3) the take name `FBXExportSplitAnimationIntoTakes` writes, (4) the baked key count, (5) whether DeformPercent curves are baked or as-authored, (6) `Animation -v false` ⇒ zero curve records. Any failure here is fixed in the READER/VIOLATION with the measured value recorded in the test comment — never by loosening the live gate later.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_handlers_mayapy.py`:

```python
class TestClipInMaya:
    # The mayapy session is ONE persistent Maya scene across tests: reused
    # joint names would collide with unique_name and make short-name
    # resolution ambiguous, so every test builds under its OWN prefix (the
    # bs_base/bs_base8 precedent in the blendshape classes above).
    def _rig(self, cmds, prefix, bound=True):
        from maya_plugin.handlers import rigging

        base = cmds.ls(cmds.polyCube(name=prefix + "_base", height=2,
                                     subdivisionsHeight=4)[0], long=True)[0]
        skeleton = rigging.create_skeleton({"joints": [
            {"name": prefix + "_root", "position": [0.0, -1.0, 0.0]},
            {"name": prefix + "_mid", "position": [0.0, 0.0, 0.0],
             "parent": prefix + "_root"},
            {"name": prefix + "_tip", "position": [0.0, 1.0, 0.0],
             "parent": prefix + "_mid"}]})
        if bound:
            rigging.bind_skin({"mesh": base, "root": skeleton["root"]})
        return base, skeleton["root"]

    def test_author_measures_real_evaluated_motion(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import clip

        base, root = self._rig(cmds, "ca")
        out = clip.author_clip({
            "root": root, "name": "bend", "fps": 30,
            "keys": [
                {"time_s": 0.0, "rotations": {"ca_mid": [0, 0, 0]}},
                {"time_s": 1.0, "rotations": {"ca_mid": [0, 0, 90]}},
            ]})
        assert out["duration_s"] == pytest.approx(1.0)
        assert out["frames"] == 31
        # per-key displacement is EVALUATED: at key 1 the tip half of a
        # 2-unit cube swings 90 degrees about the mid joint
        assert out["per_key"][0]["max_displacement"] == 0.0
        assert out["per_key"][1]["max_displacement"] > 0.5
        # the curves really hold degrees: evaluate mid-clip
        cmds.currentTime(15)
        rz = cmds.getAttr(root + "|ca_mid.rotateZ")
        assert 30.0 < rz < 60.0     # linear tangents, halfway-ish
        cmds.currentTime(0)
        # teardown: the mayapy scene persists, and a leftover clip would
        # trip the export leg's one-clip-per-file scan
        clip.delete_clip({"root": root})

    def test_static_mutators_refuse_then_delete_clip_restores(self):
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import clip, rigging, sculpt

        base, root = self._rig(cmds, "cb")
        rest = sculpt.vertex_positions(cmds, base)
        clip.author_clip({
            "root": root, "name": "bend", "fps": 30,
            "keys": [
                {"time_s": 0.0, "rotations": {"cb_mid": [0, 0, 0]}},
                {"time_s": 0.5, "rotations": {"cb_mid": [0, 0, 45]}},
            ]})
        with pytest.raises(HandlerError, match="clip 'bend'"):
            rigging.pose_skeleton({"root": root,
                                   "rotations": {"cb_mid": [0, 0, 10]}})
        with pytest.raises(HandlerError, match="animation curves"):
            rigging.reset_pose({"root": root})
        out = clip.delete_clip({"root": root})
        assert out["clip"] == "bend" and out["deleted_curves"] >= 3
        # static posing works again, and the mesh is back at bind
        now = sculpt.vertex_positions(cmds, base)
        worst = max(abs(a - b) for a, b in zip(rest, now))
        assert worst < 1e-4
        rigging.pose_skeleton({"root": root,
                               "rotations": {"cb_mid": [0, 0, 10]}})

    def test_loop_refusal_and_replace_are_real(self):
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import clip

        base, root = self._rig(cmds, "cc", bound=False)
        with pytest.raises(HandlerError, match="does not close"):
            clip.author_clip({
                "root": root, "name": "bad", "fps": 30, "loop": True,
                "keys": [
                    {"time_s": 0.0, "rotations": {"cc_mid": [0, 0, 0]}},
                    {"time_s": 1.0, "rotations": {"cc_mid": [0, 0, 45]}},
                ]})
        clip.author_clip({
            "root": root, "name": "first", "fps": 30,
            "keys": [
                {"time_s": 0.0, "rotations": {"cc_mid": [0, 0, 0]}},
                {"time_s": 1.0, "rotations": {"cc_mid": [0, 0, 45]}},
            ]})
        out = clip.author_clip({
            "root": root, "name": "second", "fps": 30,
            "keys": [
                {"time_s": 0.0, "rotations": {"cc_tip": [0, 0, 0]}},
                {"time_s": 1.0, "rotations": {"cc_tip": [0, 0, 20]}},
            ]})
        assert out["replaced"] == "first"
        # the first clip's curves are GONE, not merged
        assert not (cmds.listConnections(
            root + "|cc_mid.rotateZ",
            source=True, destination=False, type="animCurve") or [])
        clip.delete_clip({"root": root})   # scene-persistence teardown


class TestClipExportInMaya:
    # Same persistent-scene rule as TestClipInMaya: one prefix per test.
    def _clipped_scene(self, cmds, prefix, with_blink=True):
        from maya_plugin.handlers import blendshape, clip, rigging

        base = cmds.ls(cmds.polyCube(name=prefix + "_base", height=2,
                                     subdivisionsHeight=4)[0], long=True)[0]
        skeleton = rigging.create_skeleton({"joints": [
            {"name": prefix + "_root", "position": [0.0, -1.0, 0.0]},
            {"name": prefix + "_mid", "position": [0.0, 0.0, 0.0],
             "parent": prefix + "_root"}]})
        rigging.bind_skin({"mesh": base, "root": skeleton["root"]})
        weights = {}
        if with_blink:
            target = cmds.ls(cmds.duplicate(base, name=prefix + "_t")[0],
                             long=True)[0]
            cmds.move(0, 0, 0.2, target + ".vtx[0]", relative=True)
            blendshape.create_blendshape({
                "mesh": base,
                "targets": [{"name": prefix + "_blink",
                             "target_mesh": target}]})
            weights = {prefix + "_blink": 0.0}
        keys = [
            {"time_s": 0.0, "rotations": {prefix + "_mid": [0, 0, 0]},
             "root_position": [0.0, -1.0, 0.0], "blend_weights": weights},
            {"time_s": 0.5, "rotations": {prefix + "_mid": [0, 0, 30]},
             "root_position": [0.0, -0.95, 0.0],
             "blend_weights": ({prefix + "_blink": 1.0} if with_blink
                               else {})},
            {"time_s": 1.0, "rotations": {prefix + "_mid": [0, 0, 0]},
             "root_position": [0.0, -1.0, 0.0], "blend_weights": weights},
        ]
        if not with_blink:
            for k in keys:
                k.pop("blend_weights")
        clip.author_clip({"root": skeleton["root"], "name": "sway",
                          "fps": 30, "loop": True, "keys": keys})
        return base, skeleton["root"]

    def test_the_measurements(self, tmp_path):
        """THE MEASUREMENT BATTERY (#695 plan constraint). Every assertion
        here pins a literal the byte gate rests on. On failure, read the
        raw facts (facts.anim_nodes / facts.takes), fix the READER or the
        VIOLATION to the measured truth, and record the measured value in
        a comment here - never force the literal.
        """
        import maya.cmds as cmds

        from maya_plugin.handlers import clip, export, fbxbytes

        base, root = self._clipped_scene(cmds, "cd")
        path = str(tmp_path / "sway.fbx").replace("\\", "/")
        # SELECTED export (mesh + root): the persistent mayapy scene holds
        # other tests' meshes, and a selected export keeps this file about
        # this rig - same shape the skin-export contract documents.
        result = export.export_fbx({"path": path, "metres_per_unit": 1.0,
                                    "nodes": [base, root],
                                    "include_skins": True,
                                    "include_animation": True})
        anim = result["animation"]
        assert anim is not None
        # (3) the take is named after the clip
        assert [t["name"] for t in anim["takes"]] == ["sway"]
        # (1) tick constant: a 1.0 s clip must measure 1.0 s in ticks
        assert anim["takes"][0]["duration_s"] == pytest.approx(1.0, abs=0.04)
        by = {(t["target"], t["property"]): t for t in anim["targets"]}
        # (2) property strings + (4) baked key count
        mid = by[("cd_mid", "Lcl Rotation")]
        assert mid["curves"] == 3
        assert mid["key_count"] == 31          # round(1.0 * 30) + 1
        root_t = by[("cd_root", "Lcl Translation")]
        assert root_t["key_count"] == 31
        # (5) DeformPercent: presence gated; RECORD the measured count here
        blink = by[("cd_blink", "DeformPercent")]
        assert blink["key_count"] >= 2
        # an independent read of the bytes agrees with the tool
        assert fbxbytes.anim_facts(fbxbytes.read_fbx(path)) == anim
        # skins and shapes still green alongside animation
        assert result["skin"]["deformers"] == 1
        assert result["shapes"]["shapes"][0]["name"] == "cd_blink"
        clip.delete_clip({"root": root})   # scene-persistence teardown

    def test_animation_off_writes_zero_curves(self, tmp_path):
        """(6) the symmetric assertion: an ANIMATED scene exported without
        include_animation carries not one curve record."""
        import maya.cmds as cmds

        from maya_plugin.handlers import clip, export, fbxbytes

        base, root = self._clipped_scene(cmds, "cf", with_blink=False)
        path = str(tmp_path / "static.fbx").replace("\\", "/")
        result = export.export_fbx({"path": path, "metres_per_unit": 1.0,
                                    "nodes": [base, root],
                                    "include_skins": True})
        assert result["animation"] is None
        facts = fbxbytes.read_fbx(path)
        assert len(facts.anim_curves) == 0
        assert len(facts.anim_nodes) == 0
        clip.delete_clip({"root": root})   # scene-persistence teardown

    def test_include_animation_without_a_clip_refuses(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import export

        cmds.polyCube(name="ce_plain")
        path = str(tmp_path / "none.fbx").replace("\\", "/")
        with pytest.raises(HandlerError, match="no clip exists"):
            export.export_fbx({"path": path, "metres_per_unit": 1.0,
                               "include_animation": True})
```

- [ ] **Step 2: Run and MEASURE** — `E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q --junitxml=$env:TEMP/p6t7.xml`. Expected: the new tests PASS alongside all 142+1. The budgeted contingencies, in likelihood order: the take name (if `FBXExportSplitAnimationIntoTakes` writes something else or errors, probe the raw `facts.takes` and adjust the MEL in export.py or the assertion to the measured mechanism, recording it); the OP property strings (fix `anim_facts`/`anim_violations` matching); the DeformPercent count; the baked count off-by-one. Fix at the measured truth, record the raw string in a comment, re-run.

- [ ] **Step 3: Commit**

```bash
git add tests/test_handlers_mayapy.py maya_plugin/handlers/fbxbytes.py maya_plugin/handlers/export.py
git commit -m "test(#695): clips measured against a real Maya - tick constant, take naming, property strings, bake counts, zero-when-off"
```

(Include the handler files only if a measurement forced a fix.)

---

### Task 8: Schemas, the three MCP tools (56), export flag, protocol docs

**Files:**
- Modify: `src/maya_mcp/schemas.py`, `src/maya_mcp/server.py`, `docs/protocol.md`
- Test: `tests/test_server_tools.py`

**Interfaces:**
- Consumes: Task 2/4's result dicts, Task 6's `animation` block.
- Produces: `maya_author_clip`, `maya_delete_clip`, `maya_preview_clip` (returns a composited contact sheet, the `maya_render_sheet` pattern); `maya_export_fbx` gains `include_animation`.

- [ ] **Step 1: Write the failing tests** — in `tests/test_server_tools.py`, add `"maya_author_clip"`, `"maya_delete_clip"`, `"maya_preview_clip"` to the registered-tools set (now **56**), and append (matching the file's `FakeConn`/`run` idiom — the `maya_author_physics` tests are the closest model):

```python
class TestClipTools:
    def _author_result(self):
        return {"root": "|pelvis", "clip": "walk", "fps": 30,
                "duration_s": 1.2, "frames": 37, "keyed_joints": 8,
                "keyed_weight_channels": ["blink"],
                "root_position_keyed": True, "interpolation": "smooth",
                "loop": True, "replaced": "idle",
                "per_key": [{"time_s": 0.0, "max_displacement": 0.0},
                            {"time_s": 1.2, "max_displacement": 0.31}],
                "warnings": []}

    def test_author_marshals_keys_and_returns_measured(self):
        conn = FakeConn(responses={"author_clip": self._author_result()})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_author_clip", {
            "root": "|pelvis", "name": "walk", "fps": 30, "loop": True,
            "interpolation": "smooth",
            "keys": [
                {"time_s": 0.0, "rotations": {"L_hip": [0, -25, 0]},
                 "root_position": [0, 0.97, 0],
                 "blend_weights": {"blink": 0.0}},
                {"time_s": 1.2, "rotations": {"L_hip": [0, -25, 0]},
                 "root_position": [0, 0.97, 0],
                 "blend_weights": {"blink": 0.0}},
            ]}))
        params = conn.calls[0]["params"]
        assert conn.calls[0]["cmd"] == "author_clip"
        assert params["keys"][0]["rotations"] == {"L_hip": [0, -25, 0]}
        assert params["keys"][0]["root_position"] == [0, 0.97, 0]
        assert result[1]["per_key"][1]["max_displacement"] == 0.31

    def test_delete_marshals(self):
        conn = FakeConn(responses={"delete_clip": {
            "root": "|pelvis", "clip": "walk", "deleted_curves": 27,
            "max_displacement": 0.31, "warnings": []}})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_delete_clip", {"root": "|pelvis"}))
        assert conn.calls[0]["cmd"] == "delete_clip"
        assert result[1]["deleted_curves"] == 27

    def test_preview_composites_one_sheet(self):
        png = _tiny_png_b64()   # reuse/mirror the helper the capture or
        # render-sheet tests in this file already use for a 1x1 png payload
        conn = FakeConn(responses={"preview_clip": {
            "clip": "walk", "fps": 30,
            "frames": [{"frame": 0, "time_s": 0.0},
                       {"frame": 36, "time_s": 1.2}],
            "images": [{"label": "t=0.00s", "angle": "side", "png_b64": png},
                       {"label": "t=1.20s", "angle": "side",
                        "png_b64": png}],
            "renderer": "hw2", "samples": 1, "fallback_light": False,
            "zoom": 1.0, "relit_lights": 0}})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_preview_clip", {
            "root": "|pelvis", "name": "walk", "angle": "side"}))
        assert conn.calls[0]["params"]["name"] == "walk"
        # first content item is ONE image (the sheet), then the frame times
        assert result[0][0].__class__.__name__ == "Image"
        assert any("t=1.20s" in str(c) for c in result[0])

    def test_export_gains_include_animation(self):
        conn = FakeConn(responses={"export_fbx": _export_result_stub()})
        # extend the stub this file already uses for export tests with
        # "animation": None; assert the marshaled param:
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool("maya_export_fbx", {
            "path": "D:/x/clip.fbx", "metres_per_unit": 1.0,
            "include_animation": True}))
        assert conn.calls[0]["params"]["include_animation"] is True

    def test_annotations(self):
        mcp = server_mod.create_server(FakeConn())
        by_name = {t.name: t for t in run(mcp.list_tools())}
        author = by_name["maya_author_clip"].annotations
        assert (author.read_only_hint, author.destructive_hint,
                author.idempotent_hint) == (False, True, False)
        delete = by_name["maya_delete_clip"].annotations
        assert (delete.read_only_hint, delete.destructive_hint,
                delete.idempotent_hint) == (False, True, True)
        preview = by_name["maya_preview_clip"].annotations
        assert (preview.read_only_hint, preview.destructive_hint,
                preview.idempotent_hint) == (True, False, True)
```

(Adapt helper names to what the file actually provides — it has an export-result stub and an image payload helper near its capture tests; mirror, don't invent.)

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_server_tools.py -q --junitxml=$env:TEMP/p6t8.xml`. Expected: FAIL (registration set mismatch).

- [ ] **Step 3: Implement schemas** — in `src/maya_mcp/schemas.py`, next to the blendshape models:

```python
class ClipKeySpec(BaseModel):
    """One key of a clip: the phase-1 pose map at a moment in time."""

    time_s: float = Field(description=(
        "Seconds from the clip start. The first key must be at 0.0; times "
        "must be strictly increasing and should land on frames at the "
        "clip's fps."))
    rotations: Optional[Dict[str, List[float]]] = Field(
        default=None, description=(
            "Joint name -> [rx, ry, rz] DEGREES, local - exactly "
            "pose_skeleton's currency."))
    blend_weights: Optional[Dict[str, float]] = Field(
        default=None, description=(
            "Blendshape target name -> 0..1 - a blink in an idle, a bulge "
            "synced to a step."))
    root_position: Optional[List[float]] = Field(
        default=None, description=(
            "World position for the ROOT joint - the pelvis bob an honest "
            "walk needs, or authored root motion. Root only; bones do not "
            "translate."))


class ClipKeyMeasure(BaseModel):
    model_config = ConfigDict(extra="ignore")

    time_s: float
    max_displacement: float = Field(description=(
        "MEASURED at this key's frame against the evaluated first key - "
        "the scene's time was driven there and the vertices re-read."))


class AuthorClipResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    root: str
    clip: str
    fps: int
    duration_s: float = Field(description=(
        "Re-read from the authored curves, never echoed."))
    frames: int = Field(description="Baked frame count: round(d*fps)+1.")
    keyed_joints: int
    keyed_weight_channels: List[str]
    root_position_keyed: bool
    interpolation: str
    loop: bool
    replaced: Optional[str] = Field(
        default=None, description=(
            "The clip this call replaced - ONE clip exists at a time."))
    per_key: List[ClipKeyMeasure]
    warnings: List[str] = Field(default_factory=list)


class DeleteClipResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    root: str
    clip: Optional[str] = None
    deleted_curves: int
    max_displacement: float
    warnings: List[str] = Field(default_factory=list)


class TakeRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    duration_s: Optional[float] = None


class AnimCurveTarget(BaseModel):
    model_config = ConfigDict(extra="ignore")

    target: Optional[str] = Field(description=(
        "The joint (Model) or blendshape channel the curves drive."))
    property: str
    curves: int
    key_count: Optional[int] = None
    duration_s: Optional[float] = None


class AnimFacts(BaseModel):
    """Animation records read back OUT OF THE FILE, never from the scene."""

    model_config = ConfigDict(extra="ignore")

    stacks: int
    layers: int
    curves: int
    curve_nodes: int
    takes: List[TakeRecord]
    targets: List[AnimCurveTarget]
    unavailable_reason: Optional[str] = None
```

and on `ExportFbxResult`, after `shapes`:

```python
    animation: Optional[AnimFacts] = Field(
        default=None,
        description=(
            "Animation facts when include_animation=true; null otherwise. "
            "When false, the byte gate has asserted the file carries ZERO "
            "curve records even if the scene is animated."))
```

- [ ] **Step 4: Implement the tools** — in `src/maya_mcp/server.py`, import the new schema names, add to `maya_export_fbx`'s signature (after `include_skins`):

```python
        include_animation: Annotated[bool, Field(description=(
            "Bake the authored clip to per-frame curves and write it as one "
            "take named after the clip. Refuses when no clip exists. False "
            "(the default) pins animation export OFF - a static export of "
            "an animated scene is byte-identical to an unanimated one, "
            "asserted from the bytes."
        ))] = False,
```

(and pass it through in the request params dict), then after `maya_set_blendshape_weights`:

```python
    @mcp.tool(
        title="Author animation clip",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
    )
    def maya_author_clip(
        root: Annotated[str, Field(description="Skeleton root joint.")],
        name: Annotated[str, Field(description=(
            "Clip name - becomes the exported take name. Plain identifier."
        ))],
        keys: Annotated[List[ClipKeySpec], Field(min_length=2, description=(
            "The keys, in time order from 0.0. Each carries any of "
            "rotations / blend_weights / root_position; a channel keyed in "
            "some keys only interpolates between its own keys."
        ))],
        fps: Annotated[int, Field(description=(
            "One of 24, 25, 30, 48, 50, 60 - the scene's time unit is set "
            "to match so keys land on frames."
        ))] = 30,
        interpolation: Annotated[Literal["linear", "smooth"], Field(
            description="linear tangents, or Maya auto tangents.")] = "linear",
        loop: Annotated[bool, Field(description=(
            "Validate that the last key closes onto the first (rotations, "
            "weights, root position) - a cycle that does not close pops on "
            "repeat in-engine. Refusal carries the measured difference."
        ))] = False,
    ) -> AuthorClipResult:
        """Key the pose map over time - ONE clip per skeleton, replacing any
        previous clip with a warning.

        The currency is exactly pose_skeleton's rotation map, plus optional
        blendshape weights and a root position per key. While the clip
        exists, static pose tools refuse (curves own the channels);
        maya_delete_clip returns the skeleton to static posing. Every key's
        displacement is MEASURED by evaluating the scene at that frame.
        Export it with maya_export_fbx include_animation=true."""
        return AuthorClipResult.model_validate(
            maya.request(
                "author_clip",
                {"root": root, "name": name, "fps": fps,
                 "keys": [k.model_dump(exclude_none=True) for k in keys],
                 "interpolation": interpolation, "loop": loop},
                timeout_s=BOOL_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Delete animation clip",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=True
        ),
    )
    def maya_delete_clip(
        root: Annotated[str, Field(description="Skeleton root joint.")],
    ) -> DeleteClipResult:
        """Remove the clip's curves, zero its weight channels, restore the
        bind pose - the skeleton returns to static posing. Reports the
        measured displacement of the return."""
        return DeleteClipResult.model_validate(
            maya.request("delete_clip", {"root": root},
                         timeout_s=BOOL_TIMEOUT_S)
        )

    @mcp.tool(
        title="Preview clip frames",
        annotations=ToolAnnotations(
            read_only_hint=True, destructive_hint=False, idempotent_hint=True
        ),
    )
    def maya_preview_clip(
        root: Annotated[str, Field(description="Skeleton root joint.")],
        name: Annotated[str, Field(description=(
            "The clip's name - refused if it is not the live clip, so a "
            "stale assumption is never judged."
        ))],
        angle: Annotated[Angle, Field(description=(
            "One angle for every frame. 'side' reads a walk; 'front' reads "
            "a face. The camera is placed at frame 0 and HELD - motion is "
            "judged against a fixed frame."
        ))] = "three_quarter",
        every_nth: Annotated[Optional[int], Field(ge=1, description=(
            "Render every nth frame (first and last always included). Omit "
            "for the densest sheet that fits 16 cells."
        ))] = None,
        resolution: Annotated[int, Field(ge=64, le=1024, description=(
            "Per-cell resolution, before the sheet is downscaled."
        ))] = 256,
        renderer: Annotated[Literal["arnold", "hw2"], Field(description=(
            "'hw2' (default here) - a preview is many frames and motion "
            "does not need refraction."
        ))] = "hw2",
        timeout_s: Annotated[float, Field(ge=30.0, le=MAX_RENDER_TIMEOUT_S,
                                          description=(
            "Seconds for ALL frames; a timeout does not stop the render."
        ))] = RENDER_TIMEOUT_S,
    ) -> list:
        """A contact sheet of the clip's frames - judge motion from pixels.

        Row-major, first frame top-left, times labeled per cell."""
        result = maya.request(
            "preview_clip",
            {"root": root, "name": name, "angle": angle,
             "every_nth": every_nth, "resolution": resolution,
             "renderer": renderer},
            timeout_s=timeout_s,
        )
        shots = result.get("images", [])
        cells = [images.decode_and_downscale(s["png_b64"],
                                             max_px=resolution)
                 for s in shots]
        sheet = images.contact_sheet(cells)
        return [
            Image(data=images.decode_and_downscale(
                base64.b64encode(sheet).decode("ascii")), format="png"),
            "clip %r at %d fps - cells (row-major): %s" % (
                result.get("clip"), result.get("fps", 0),
                json.dumps([s["label"] for s in shots])),
            "frames: " + json.dumps(result.get("frames", [])),
        ]
```

- [ ] **Step 5: Protocol docs** — in `docs/protocol.md`, after the blendshape section, matching the file's table+prose format:

```markdown
| `author_clip` | `{ root, name, fps=30, keys: [{time_s, rotations?, blend_weights?, root_position?}], interpolation, loop }` | `{ root, clip, fps, duration_s, frames, keyed_joints, keyed_weight_channels, root_position_keyed, interpolation, loop, replaced, per_key, warnings }` |
| `preview_clip` | `{ root, name, angle?, every_nth?, resolution?, renderer? }` | `{ clip, fps, frames, images, ... }` |
| `delete_clip` | `{ root }` | `{ root, clip, deleted_curves, max_displacement, warnings }` |

`author_clip` keys the phase-1 pose map over time. **One clip exists per
skeleton at a time**: authoring under a new name replaces the previous clip
(warning naming it); there is no clip library and no persistent solver
state beyond the curves themselves plus one metadata attr on the root. Keys
may also carry blendshape weights (resolved across the meshes bound to the
skeleton) and a world `root_position` for the root joint - the pelvis bob a
walk needs. `loop=true` refuses a clip whose last key does not close onto
its first, with the measured per-channel difference. Every key's
displacement is MEASURED by driving the scene time to that frame;
`duration_s` is re-read from the curves.

**While a clip exists, static pose mutators refuse** (`pose_skeleton`,
`pose_ik`, `reset_pose`, `set_blendshape_weights`): curves own the
channels, and a static write would be silently overridden on the next frame
change. `delete_clip` removes the curves, zeroes keyed weight channels,
restores the bind pose, and reports the measured displacement.

`preview_clip` renders every-nth frame through the render pipeline into one
contact sheet (camera placed at frame 0 and held). Export: pass
`include_animation=true` to `export_fbx` - the clip bakes to per-frame
curves (`FBXExportBakeComplexAnimation`) in one take named after the clip,
and the byte gate asserts rotation curves per keyed joint at
`round(duration*fps)+1` keys, root translation curves when root_position
was used, DeformPercent curves per keyed weight channel, and the take's
name and duration. With `include_animation=false` (the default) the gate
asserts the file carries ZERO curve records even when the scene is
animated. The result gains `animation`.
```

Also add the `animation` column note to the Delivery table row (the same place `shapes` was added in P5).

- [ ] **Step 6: Run to verify pass** — `uv run pytest tests/test_server_tools.py -q --junitxml=$env:TEMP/p6t8.xml`, then the whole suite `uv run pytest -q --junitxml=$env:TEMP/p6full.xml`. Expected: PASS, 56 tools.

- [ ] **Step 7: Commit**

```bash
git add src/maya_mcp/schemas.py src/maya_mcp/server.py docs/protocol.md tests/test_server_tools.py
git commit -m "feat(#695): maya_author_clip / maya_preview_clip / maya_delete_clip MCP tools - 56 tools"
```

---

### Task 9: The live gate — looping idle + walk on the humanoid, judged and byte-gated

**Files:**
- Create: `evals/clip_live.py`
- Create (generated by the run, then committed): `evals/clip_live/baseline.json`, preview frames, `idle.fbx`, `walk.fbx`

**Interfaces:**
- Consumes: everything above, deployed; `evals/humanoid_live.py`'s `PARTS`, `JOINTS`, `MESH` constants (importable — `main()` is `__main__`-guarded). The measured bend-axis table from its `biped_pose` docstring is the AUTHORITY for every rotation literal below: legs pitch forward as local `Y=-t` (X is the twist axis down the bone), ankles as local `Z=-t`, both shoulders raise as the SAME local `+Z` (no per-side flip), spine/chest as local `Y=-t`.

**Deploy first (the #604 trap):**

- [ ] **Step 1: Deploy and restart the disposable Maya**

```bash
uv run python maya_plugin/install.py --yes
```

Then start (or restart) the agent-launched Maya with a NEUTRAL cwd (never the repo — Maya puts its cwd on `sys.path`), `MAYA_MCP_PORT=9878`. Ping through the TCP client: `restart_required` false, stamp == `git rev-parse --short=12 HEAD`, listener pid matched to the launched process (#648; `taskkill /F /T` a stale holder and verify the port released).

- [ ] **Step 2: Write the gate** — create `evals/clip_live.py`:

```python
"""Phase-6 gate for #695: animation clips on the #668 humanoid.

Two clips, both loop=True (the field-informed check this phase added):

    1  idle - 2.0 s breathing sway with a BLINK keyed mid-clip
       (exercises blend-weight keying), judged front-on
    2  walk - 1.2 s stride cycle with pelvis bob via root_position
       (exercises root translation), judged from the side; REPLACES the
       idle (the one-clip-at-a-time contract, asserted)

Rotation literals derive from humanoid_live.biped_pose's MEASURED axis
table: create_skeleton aims local X down the bone, so vertical chains
pitch forward as local Y=-t, ankles as local Z=-t, and both shoulders
raise as the same local +Z. Pixels outrank derivations - if a sheet reads
wrong, fix the literals from what the render shows and re-run.

Measured checks (this script) + judged sheets (the acceptance):
    build humanoid + skeleton + bind + blink target -> author idle
    (loop) -> preview sheet -> export include_animation, byte-gated ->
    author walk (replaces, warning asserted) -> preview sheet -> export ->
    static-mutator refusal probed live -> delete_clip -> static export
    carries ZERO curves -> baseline.json.

DESTRUCTIVE: calls new_scene. Port 9878, the agent-launched Maya, per the
two-Maya policy - never point this at the user's 9877.

Run:  uv run python evals/clip_live.py
Exit: 0 pass, 1 fail, 2 no connection.
"""

from __future__ import annotations

import base64
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from humanoid_live import JOINTS, MESH, PARTS  # noqa: E402
from live_call import call, structured_result  # noqa: E402
from maya_plugin.handlers import fbxbytes  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
OUT_DIR = os.path.join(_HERE, "clip_live")
JOINT_COUNT = 20

# Blink target sculpt: a soft brow-drop on the head sphere (front of the
# head sits near (0, 1.80, 0.15) per the PARTS table). It only has to be
# VISIBLE at 256 px - the P5 gate measured that too-subtle sculpts render
# invisibly, so this uses the widened-literal lesson from day one.
BLINK_CENTER = [0.0, 1.80, 0.15]
BLINK_RADIUS = 0.16
BLINK_DELTA = [0.0, -0.06, 0.02]

IDLE_KEYS = [
    {"time_s": 0.0,
     "rotations": {"spine_01": [0, 0, 0], "chest": [0, 0, 0],
                   "L_shoulder": [0, 0, 0], "R_shoulder": [0, 0, 0]},
     "blend_weights": {"blink": 0.0}},
    {"time_s": 0.5,
     "rotations": {"spine_01": [0, -3, 0], "chest": [0, -3, 0],
                   "L_shoulder": [0, 0, 4], "R_shoulder": [0, 0, 4]},
     "blend_weights": {"blink": 0.0}},
    {"time_s": 1.0,
     "rotations": {"spine_01": [0, 0, 0], "chest": [0, 0, 0],
                   "L_shoulder": [0, 0, 0], "R_shoulder": [0, 0, 0]},
     "blend_weights": {"blink": 1.0}},
    {"time_s": 1.2,
     "rotations": {"spine_01": [0, 1, 0], "chest": [0, 1, 0],
                   "L_shoulder": [0, 0, 1], "R_shoulder": [0, 0, 1]},
     "blend_weights": {"blink": 0.0}},
    {"time_s": 2.0,
     "rotations": {"spine_01": [0, 0, 0], "chest": [0, 0, 0],
                   "L_shoulder": [0, 0, 0], "R_shoulder": [0, 0, 0]},
     "blend_weights": {"blink": 0.0}},
]

# The walk: contact (L forward) -> passing -> contact (R forward) ->
# passing -> contact (L forward, == first key: loop). Forward leg swing is
# local -Y on hips (the measured table); the LEGS alternate via OPPOSITE
# L/R signs (vertical bones share the local-Y-is-world-X frame). The ARMS
# counter-swing via the SAME local-Y sign on both shoulders: the horizontal
# bones point opposite ways (+X / -X), so one world rotation about Y moves
# them fore/aft oppositely - hand-mirroring the signs would swing them IN
# PHASE, the same trap humanoid_live's docstring records for the golem
# poses. Ankles are local Z; pelvis bob rides the root.
WALK_FPS = 30
WALK_KEYS = [
    {"time_s": 0.0,
     "rotations": {"L_hip": [0, -25, 0], "R_hip": [0, 20, 0],
                   "L_knee": [0, 5, 0], "R_knee": [0, -30, 0],
                   "L_ankle": [0, 0, -5], "R_ankle": [0, 0, 10],
                   "L_shoulder": [0, 15, 0], "R_shoulder": [0, 15, 0],
                   "L_elbow": [0, 0, 10], "R_elbow": [0, 0, 25]},
     "root_position": [0.0, 0.97, 0.0]},
    {"time_s": 0.3,
     "rotations": {"L_hip": [0, 0, 0], "R_hip": [0, -5, 0],
                   "L_knee": [0, -5, 0], "R_knee": [0, -45, 0],
                   "L_ankle": [0, 0, 0], "R_ankle": [0, 0, -15],
                   "L_shoulder": [0, 0, 0], "R_shoulder": [0, 0, 0],
                   "L_elbow": [0, 0, 15], "R_elbow": [0, 0, 15]},
     "root_position": [0.0, 1.01, 0.0]},
    {"time_s": 0.6,
     "rotations": {"L_hip": [0, 20, 0], "R_hip": [0, -25, 0],
                   "L_knee": [0, -30, 0], "R_knee": [0, 5, 0],
                   "L_ankle": [0, 0, 10], "R_ankle": [0, 0, -5],
                   "L_shoulder": [0, -15, 0], "R_shoulder": [0, -15, 0],
                   "L_elbow": [0, 0, 25], "R_elbow": [0, 0, 10]},
     "root_position": [0.0, 0.97, 0.0]},
    {"time_s": 0.9,
     "rotations": {"L_hip": [0, -5, 0], "R_hip": [0, 0, 0],
                   "L_knee": [0, -45, 0], "R_knee": [0, -5, 0],
                   "L_ankle": [0, 0, -15], "R_ankle": [0, 0, 0],
                   "L_shoulder": [0, 0, 0], "R_shoulder": [0, 0, 0],
                   "L_elbow": [0, 0, 15], "R_elbow": [0, 0, 15]},
     "root_position": [0.0, 1.01, 0.0]},
    {"time_s": 1.2,
     "rotations": {"L_hip": [0, -25, 0], "R_hip": [0, 20, 0],
                   "L_knee": [0, 5, 0], "R_knee": [0, -30, 0],
                   "L_ankle": [0, 0, -5], "R_ankle": [0, 0, 10],
                   "L_shoulder": [0, 15, 0], "R_shoulder": [0, 15, 0],
                   "L_elbow": [0, 0, 10], "R_elbow": [0, 0, 25]},
     "root_position": [0.0, 0.97, 0.0]},
]

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
        print("FAIL: %s: %s" % (command,
                                json.dumps(response.get("error"))[:600]))
        sys.exit(1)
    return response.get("result") or {}


def expect_refusal(command, params, needle, label):
    response = send(command, params)
    refused = (response.get("status") != "ok"
               and needle in json.dumps(response.get("error")))
    check(label, refused, json.dumps(response.get("error"))[:160])


def py(code, what, timeout_s=300.0):
    return structured_result(ok("execute_python", {"code": code},
                                timeout_s), what)


def out(name):
    return os.path.join(OUT_DIR, name)


def save_preview(tag, result):
    saved = 0
    for image in result.get("images", []):
        path = out("%s_%s.png" % (tag, image["label"].replace("=", "")
                                  .replace(".", "_")))
        with open(path, "wb") as fh:
            fh.write(base64.b64decode(image["png_b64"]))
        saved += 1
    check("preview %s rendered %d frames" % (tag, saved), saved >= 4,
          "frames=%s" % [f["frame"] for f in result.get("frames", [])])


def main():
    if PORT == 9877:
        print("refusing to run on 9877: this eval discards the open scene "
              "(two-Maya policy). Launch a disposable Maya on 9878.")
        return 2

    os.makedirs(OUT_DIR, exist_ok=True)
    identity = py("import os\n{'pid': os.getpid()}", "identity")
    print("Maya on %d: pid %s, writing to %s\n"
          % (PORT, identity["pid"], OUT_DIR))

    # ---- 1. humanoid + skeleton + bind + blink target
    ok("new_scene", {"confirm": True})
    for kind, name, divisions, scale, translate, rotate in PARTS:
        params = {"kind": kind, "name": name, "divisions": divisions,
                  "scale": scale, "translate": translate}
        if rotate:
            params["rotate"] = rotate
        ok("create_primitive", params)
    ok("combine", {"names": [p[1] for p in PARTS], "name": MESH})
    py("import maya.cmds as cmds\n"
       "cmds.makeIdentity(%r, apply=True, translate=False, rotate=True, "
       "scale=True, normal=0, preserveNormals=True)\nTrue"
       % ("|" + MESH), "freeze the combined mesh")
    skeleton = ok("create_skeleton", {"joints": JOINTS})
    root = skeleton["root"]
    bind = ok("bind_skin", {"mesh": "|" + MESH, "root": root},
              timeout_s=600.0)
    check("the bind leaves NO vertex unowned",
          bind["unweighted_vertices"] == 0,
          "unweighted=%d" % bind["unweighted_vertices"])
    ok("duplicate", {"name": "|" + MESH, "new_name": "humanoid_blink"})
    ok("sculpt_ops", {"mesh": "|humanoid_blink", "ops": [
        {"op": "soft_move", "center": BLINK_CENTER, "radius": BLINK_RADIUS,
         "delta": BLINK_DELTA, "falloff": "smooth"}]})
    wired = ok("create_blendshape", {"mesh": "|" + MESH, "targets": [
        {"name": "blink", "target_mesh": "|humanoid_blink"}]})
    check("the blink target wired with a real delta",
          wired["targets"][0]["max_delta"] > 0.01,
          "max_delta=%.4f" % wired["targets"][0]["max_delta"])
    ok("setup_lighting", {"preset": "three_point"})

    # ---- 2. loop contract probed live: an open cycle must refuse
    bad = [dict(IDLE_KEYS[0]), dict(IDLE_KEYS[1])]
    bad[1] = dict(bad[1], time_s=2.0)
    expect_refusal("author_clip",
                   {"root": root, "name": "open", "fps": 30, "loop": True,
                    "keys": bad},
                   "does not close",
                   "loop=true refuses an open cycle with the measured delta")

    # ---- 3. the idle: authored, measured, previewed, exported
    idle = ok("author_clip", {"root": root, "name": "idle", "fps": 30,
                              "interpolation": "smooth", "loop": True,
                              "keys": IDLE_KEYS})
    check("idle: duration and frames measured back",
          abs(idle["duration_s"] - 2.0) < 1e-6 and idle["frames"] == 61,
          "duration=%.3f frames=%d" % (idle["duration_s"], idle["frames"]))
    moved = [k["max_displacement"] for k in idle["per_key"]]
    # the LAST key equals the first (loop), so its displacement vs frame 0
    # is ~0 BY CONSTRUCTION - that near-zero IS the measured loop closure.
    check("idle: every interior key measured real motion",
          moved[0] == 0.0 and all(m > 0.005 for m in moved[1:-1]),
          json.dumps([round(m, 4) for m in moved]))
    check("idle: the loop measurably closes (last key ~= first)",
          moved[-1] < 1e-3, "closure=%.5f" % moved[-1])
    check("idle: the blink channel is keyed",
          idle["keyed_weight_channels"] == ["blink"])
    preview = ok("preview_clip", {"root": root, "name": "idle",
                                  "angle": "front", "resolution": 320},
                 timeout_s=900.0)
    save_preview("idle", preview)

    # ---- 4. static mutators refuse while the clip exists
    expect_refusal("pose_skeleton",
                   {"root": root, "rotations": {"chest": [0, 0, 10]}},
                   "clip", "pose_skeleton refuses while the clip owns the "
                   "channels")
    expect_refusal("set_blendshape_weights",
                   {"mesh": "|" + MESH, "weights": {"blink": 0.5}},
                   "animation curves",
                   "set_blendshape_weights refuses on the keyed channel")

    # ---- 5. export the idle, byte-gated
    idle_fbx = out("idle.fbx")
    if os.path.exists(idle_fbx):
        os.unlink(idle_fbx)
    result = ok("export_fbx", {"path": idle_fbx.replace("\\", "/"),
                               "metres_per_unit": 1.0,
                               "include_skins": True,
                               "include_animation": True}, timeout_s=900.0)
    anim = result["animation"]
    print("  idle animation: %s" % json.dumps(anim)[:400])
    check("idle: one take, named after the clip",
          anim is not None and [t["name"] for t in anim["takes"]] == ["idle"],
          json.dumps(anim["takes"] if anim else None))
    check("idle: take duration matches within a frame",
          abs(anim["takes"][0]["duration_s"] - 2.0) <= 1.0 / 30)
    by = {(t["target"], t["property"]): t for t in anim["targets"]}
    idle_joints = ("spine_01", "chest", "L_shoulder", "R_shoulder")
    check("idle: every keyed joint bakes 61-key rotation curves",
          all(by.get((j, "Lcl Rotation"), {}).get("key_count") == 61
              and by.get((j, "Lcl Rotation"), {}).get("curves") == 3
              for j in idle_joints),
          json.dumps({j: by.get((j, "Lcl Rotation"), {}).get("key_count")
                      for j in idle_joints}))
    check("idle: the blink channel carries DeformPercent curves",
          ("blink", "DeformPercent") in by,
          json.dumps(sorted(str(k) for k in by)[:8]))
    check("idle: skins and shapes still green alongside animation",
          result["skin"]["deformers"] == 1
          and result["skin"]["clusters"] == JOINT_COUNT
          and result["shapes"]["shapes"][0]["name"] == "blink",
          json.dumps(result["skin"]))
    facts = fbxbytes.read_fbx(idle_fbx)
    check("idle: an independent byte read agrees with the tool",
          fbxbytes.anim_facts(facts) == anim)

    # ---- 6. the walk REPLACES the idle; previewed from the side; exported
    walk = ok("author_clip", {"root": root, "name": "walk",
                              "fps": WALK_FPS, "interpolation": "smooth",
                              "loop": True, "keys": WALK_KEYS})
    check("walk: replacing the idle is stated",
          walk["replaced"] == "idle"
          and any("replaced clip 'idle'" in w for w in walk["warnings"]))
    check("walk: root bob keyed", walk["root_position_keyed"] is True)
    moved = [k["max_displacement"] for k in walk["per_key"]]
    check("walk: every interior stride key measured real motion",
          all(m > 0.05 for m in moved[1:-1]),
          json.dumps([round(m, 4) for m in moved]))
    check("walk: the loop measurably closes (last key ~= first)",
          moved[-1] < 1e-3, "closure=%.5f" % moved[-1])
    preview = ok("preview_clip", {"root": root, "name": "walk",
                                  "angle": "side", "resolution": 320},
                 timeout_s=900.0)
    save_preview("walk", preview)
    # the pelvis bob, measured off the evaluated scene at contact/passing
    bob = py(
        "import maya.cmds as cmds\n"
        "cmds.currentTime(0)\n"
        "_lo = cmds.xform(%(r)r, query=True, worldSpace=True,\n"
        "                 translation=True)[1]\n"
        "cmds.currentTime(9)\n"
        "_hi = cmds.xform(%(r)r, query=True, worldSpace=True,\n"
        "                 translation=True)[1]\n"
        "cmds.currentTime(0)\n"
        "{'contact_y': round(_lo, 4), 'passing_y': round(_hi, 4)}"
        % {"r": root}, "pelvis bob")
    check("walk: the pelvis bobs (contact %.3f -> passing %.3f)"
          % (bob["contact_y"], bob["passing_y"]),
          bob["passing_y"] - bob["contact_y"] > 0.02)

    walk_fbx = out("walk.fbx")
    if os.path.exists(walk_fbx):
        os.unlink(walk_fbx)
    result = ok("export_fbx", {"path": walk_fbx.replace("\\", "/"),
                               "metres_per_unit": 1.0,
                               "include_skins": True,
                               "include_animation": True}, timeout_s=900.0)
    anim_w = result["animation"]
    by_w = {(t["target"], t["property"]): t for t in anim_w["targets"]}
    check("walk: one take named 'walk', 37-key joint curves",
          [t["name"] for t in anim_w["takes"]] == ["walk"]
          and by_w.get(("L_hip", "Lcl Rotation"), {}).get("key_count") == 37,
          json.dumps(anim_w["takes"]))
    check("walk: root translation curves present at 37 keys",
          by_w.get(("pelvis", "Lcl Translation"), {}).get("key_count") == 37,
          json.dumps({str(k): v.get("key_count")
                      for k, v in by_w.items()
                      if k[1] == "Lcl Translation"}))

    # ---- 7. delete_clip returns the skeleton to static land
    gone = ok("delete_clip", {"root": root})
    check("delete_clip removed the walk and measured the return",
          gone["clip"] == "walk" and gone["deleted_curves"] > 0)
    reposed = ok("pose_skeleton", {"root": root,
                                   "rotations": {"chest": [0, -10, 0]}})
    check("static posing works again after delete_clip",
          reposed["max_displacement"] > 0.01)
    ok("reset_pose", {"root": root})
    static_fbx = out("static.fbx")
    if os.path.exists(static_fbx):
        os.unlink(static_fbx)
    result = ok("export_fbx", {"path": static_fbx.replace("\\", "/"),
                               "metres_per_unit": 1.0,
                               "include_skins": True}, timeout_s=600.0)
    facts = fbxbytes.read_fbx(static_fbx)
    check("a static export after delete_clip carries ZERO curve records",
          len(facts.anim_curves) == 0 and result["animation"] is None,
          "curves=%d" % len(facts.anim_curves))
    os.unlink(static_fbx)   # evidence is the check; the file is not a
    # deliverable of this gate

    with open(out("baseline.json"), "w") as fh:
        json.dump({
            "idle": {"fbx": "idle.fbx", "keys": len(IDLE_KEYS),
                     "duration_s": idle["duration_s"],
                     "frames": idle["frames"],
                     "per_key": idle["per_key"],
                     "animation": anim},
            "walk": {"fbx": "walk.fbx", "keys": len(WALK_KEYS),
                     "duration_s": walk["duration_s"],
                     "frames": walk["frames"],
                     "per_key": walk["per_key"],
                     "pelvis_bob": bob,
                     "animation": anim_w},
        }, fh, indent=2, sort_keys=True)
    print("  baseline: %s" % out("baseline.json"))

    print("\n" + "=" * 72)
    print("JUDGE the preview frames in %s:" % OUT_DIR)
    print("  idle_*: the figure must visibly sway and settle; the blink")
    print("  must read on the face mid-sheet and be gone by the last cell.")
    print("  A frozen sheet with green numbers is a FAIL.")
    print("  walk_*: read the cells as a flipbook - legs must alternate,")
    print("  arms must counter-swing, the body must ride slightly lower at")
    print("  contact than at passing. Legs twisting in place instead of")
    print("  swinging is the wrong-axis failure the measured table exists")
    print("  to prevent. First and last cells must match (the loop).")
    print("=" * 72 + "\n")

    failed = [label for passed, label in CHECKS if not passed]
    print("\n%d/%d passed" % (len(CHECKS) - len(failed), len(CHECKS)))
    for label in failed:
        print("  FAILED: %s" % label)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Run the gate** — `uv run python evals/clip_live.py` against the deployed disposable Maya. Every numbered check must PASS. Then JUDGE the sheets — implementer AND controller (the P2..P5 precedent): the idle must breathe and blink, the walk must read as a stride flipbook with visible bob and a closed loop. If a rotation literal produces the wrong motion (a twist instead of a swing, arms into the torso), fix it from what the pixels show — the measured axis table is the first suspect to re-check — and re-run. Pixels outrank derivations.

- [ ] **Step 4: Re-run both suites on the branch**

```bash
uv run pytest -q --junitxml=$env:TEMP/p6final.xml
E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q --junitxml=$env:TEMP/p6finalmaya.xml
```

Expected: all green (read the XML), counts strictly above 1244/142.

- [ ] **Step 5: Commit the gate and its evidence**

```bash
git add evals/clip_live.py evals/clip_live/
git commit -m "feat(#695): clip live gate - looping idle + walk, judged flipbook sheets, animated exports byte-gated"
```

- [ ] **Step 6: Ticket checkpoint** — update #695 (one `update_issue`): measured gate numbers (durations, key counts, bob, take names), suite counts from the XML, sheets judged by both, any literal adjusted from pixels and why; leave In Progress until merge, then Resolved with the final commit hash per the finishing flow.

---

## Self-review notes (already applied)

- Spec coverage: one-clip-at-a-time + replace warning (Tasks 2, 7, 9), keys with rotations/blend_weights/root_position (1, 2, 7, 9), loop flag with measured refusal (1, 2, 7, 9), static-mutator refusal + delete_clip (2, 3, 7, 9), preview via existing render path with fixed camera (4, 9), interpolation mapping (2), bake + take naming + include_animation both states pinned (6, 7, 9), byte gate on curves/counts/take/duration + zero-when-off (5, 6, 7, 9), measured-first literals (7's measurement battery), gate = looping idle + walk on the humanoid judged from sheets (9).
- Type consistency: `per_key[].{time_s, max_displacement}`; clip metadata `{name, fps, duration_s, loop, interpolation, joints, weight_channels, root_position_used}` written in Task 2, read by Task 6's `_scene_clip` (which adds `root`) and consumed by `anim_violations` under exactly those keys; `anim_facts` dict `{stacks, layers, curves, curve_nodes, takes[], targets[], unavailable_reason}` identical in fbxbytes, export, schemas (`AnimFacts`), and the gate.
- Known measurement points budgeted: Task 7's six-item battery (tick, property strings, take naming, bake count, DeformPercent behavior, zero-when-off); Task 9's rotation literals (pixels outrank the derivation, with the humanoid's measured axis table as the stated authority).
- Deliberately absent, with reasons in place: clip libraries/stacked timelines (design decision 1), arbitrary fps (contract decision 1), keyframe reduction (out of scope — engines re-compress), guarding `create_blendshape`/weight-craft tools (they touch nothing a curve owns).
