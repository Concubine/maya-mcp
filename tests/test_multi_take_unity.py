"""#718 consumer gate: pure tests for evals/multi_take_unity.py's `verify()`.

No Unity, no Maya, no I/O. verify() is the policy that judges the JSON a
real Unity import produces (via UNITY_MEASURE_CS) against what Maya
declared - it is reviewable and testable precisely because it never talks
to a live editor. This is the only place that logic is exercised without a
scratch Unity project; see .superpowers/sdd/t718-unity-fix-report.md for
what two real Unity runs measured, and what each round of this gate got
wrong before landing here.

No prior eval script in this repo has a dedicated pure-logic test file
(evals/*_live.py and evals/multi_take_unity.py's own C#/measurement half
need a live Maya or Unity and are proven by the eval's own printed
checks/report instead) - this file follows tests/test_export_fbx.py's
sys.path convention for reaching into evals/.

verify() no longer consults any absolute reference pose (two earlier
attempts - a hardcoded [0,0,0], then the model's export-time default
pose - were both wrong on real Unity data, see the module docstring). It
runs two checks per undeclared joint instead, using the clips as each
other's reference:

  A. MOVEMENT - within one clip, an undeclared joint's start/mid/end
     samples must agree (cyclically) within STILLNESS_EPSILON_DEG.
  B. AGREEMENT - across every clip that leaves a joint undeclared, the
     value it holds must agree (cyclically) within STILLNESS_EPSILON_DEG.
     With fewer than two such clips, B cannot be evaluated, and verify()
     says so explicitly rather than passing silently.

Most fixtures below build on `_clean_measured()` / `_declared()` - the
real #718 rig's three clips (idle declares chest/spine_01, wave declares
R_shoulder, step declares L_hip), each holding the other two clips' joints
at a realistic constant, agreeing across clips - matched to the actual
values measured against a real Unity import, given in the task brief. A
clean 3-clip fixture is the right default because check B needs at least
two non-declaring clips per joint to be evaluable at all; a 1- or 2-clip
`declared` list is deliberately reserved for TestCheckBNotEvaluable, where
that insufficiency is the point.
"""

import os
import sys

_EVALS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "evals")
if _EVALS not in sys.path:
    sys.path.insert(0, _EVALS)

import multi_take_unity as m                        # noqa: E402


def _clip(name, joints, end_frame, fps=30):
    return {"name": name, "fps": fps, "start_frame": 0,
            "end_frame": end_frame, "joints": joints}


def _declared():
    """The real #718 rig's declared clips: idle (2.0s @ 30fps) declares
    chest/spine_01, wave (1.5s) declares R_shoulder, step (1.2s) declares
    L_hip - each joint owned by exactly one clip, so every other joint's
    check B always has exactly two candidate clips to compare in this
    fixture."""
    return [_clip("idle", ["chest", "spine_01"], 60),
            _clip("wave", ["R_shoulder"], 45),
            _clip("step", ["L_hip"], 36)]


def _still(x=0.0, y=0.0, z=0.0):
    """A joint reading held perfectly constant at (x, y, z) across all
    three samples."""
    return {"start": [x, y, z], "mid": [x, y, z], "end": [x, y, z]}


def _measured_clip(name, length, samples, frame_rate=30.0):
    return {"name": name, "length": length, "frameRate": frame_rate,
            "curves": [], "samples": samples}


def _measured(clips, default_pose=None):
    """Builds the full payload verify() expects: {"model_default_pose":
    ..., "clips": ...}. `model_default_pose` is diagnostic-only (see the
    module docstring) - verify() never reads it, so it defaults to {} and
    is irrelevant to every test below except
    TestModelDefaultPoseIsDiagnosticOnly."""
    return {"model_default_pose": {} if default_pose is None else default_pose,
            "clips": clips}


def _clean_measured():
    """The real values measured against a real Unity import (task brief):
    chest/spine_01 (declared by idle) held at [0,0,0] by both wave and
    step; R_shoulder (declared by wave) held at [~0,180,270] by both idle
    and step; L_hip (declared by step) held at [~0,180,~0] by both idle
    and wave. Fully clean - verify() against this and `_declared()` must
    return []."""
    return _measured([
        _measured_clip("idle", 2.0, {
            "R_shoulder": _still(0, 180, 270),
            "L_hip": _still(0, 180, 0),
        }),
        _measured_clip("wave", 1.5, {
            "chest": _still(0, 0, 0),
            "spine_01": _still(0, 0, 0),
            "L_hip": _still(0, 180, 0),
        }),
        _measured_clip("step", 1.2, {
            "chest": _still(0, 0, 0),
            "spine_01": _still(0, 0, 0),
            "R_shoulder": _still(0, 180, 270),
        }),
    ])


def _find_clip(measured, name):
    return next(c for c in measured["clips"] if c["name"] == name)


class TestCleanCase:
    def test_real_data_is_clean(self):
        # The exact values a real Unity import produced (task brief). Both
        # of this gate's earlier reference-pose designs (hardcoded [0,0,0],
        # then the model's export-time default pose) misjudged this data;
        # checks A/B, which consult neither, must call it clean.
        assert m.verify(_declared(), _clean_measured()) == []


class TestExtraContentIsNotAViolation:
    """A clip Unity carries that Maya never declared is not this gate's
    business - the same rule the byte gate applies to an undeclared take
    (#718 design doc). If verify() flagged it, this would fail."""

    def test_undeclared_clip_in_unity_is_ignored(self):
        measured = _clean_measured()
        measured["clips"].append(_measured_clip("Take 001", 6.4, {}))
        assert m.verify(_declared(), measured) == []


class TestMissingClip:
    def test_declared_clip_absent_is_named(self):
        measured = _clean_measured()
        measured["clips"] = [c for c in measured["clips"]
                             if c["name"] != "wave"]
        violations = m.verify(_declared(), measured)
        # Dropping a clip from a 3-clip rig also strips one candidate from
        # every OTHER joint's check B (each joint now has only one
        # remaining non-declaring clip) - that cascade is correct behavior
        # (TestCheckBNotEvaluable covers it directly), so this test only
        # asserts the specific "missing clip" message is among whatever
        # comes back, not that it is the only one.
        assert any(v.startswith("clip 'wave'") and "not found" in v
                   for v in violations)

    def test_only_the_missing_one_is_named_as_not_found(self):
        measured = _clean_measured()
        measured["clips"] = [c for c in measured["clips"]
                             if c["name"] != "step"]
        violations = m.verify(_declared(), measured)
        not_found = [v for v in violations if "not found" in v]
        assert len(not_found) == 1
        assert not_found[0].startswith("clip 'step'")


class TestLengthTolerance:
    """(60 - 0) / 30 == 2.0 exactly for idle. Both sides of LENGTH_TOL_S
    (1e-3) are asserted so a widened or inverted tolerance in a future edit
    cannot pass silently. Length is the only field touched, so - unlike
    the missing-clip/completeness cases - these fixtures never disturb
    check A/B and clean assertions stay exact."""

    def test_just_under_tolerance_passes(self):
        measured = _clean_measured()
        _find_clip(measured, "idle")["length"] = 2.0 + m.LENGTH_TOL_S * 0.5
        assert m.verify(_declared(), measured) == []

    def test_just_over_tolerance_fails(self):
        measured = _clean_measured()
        _find_clip(measured, "idle")["length"] = 2.0 + m.LENGTH_TOL_S * 1.5
        violations = m.verify(_declared(), measured)
        assert len(violations) == 1
        assert "idle" in violations[0] and "length" in violations[0]

    def test_exactly_at_tolerance_passes(self):
        # "more than 1e-3" (brief's own wording) is a strict inequality -
        # exactly at the boundary must not be flagged.
        measured = _clean_measured()
        _find_clip(measured, "idle")["length"] = 2.0 + m.LENGTH_TOL_S
        assert m.verify(_declared(), measured) == []


class TestCheckAMovement:
    """Check A: an undeclared joint must not move within a clip's own
    range, regardless of what any other clip holds."""

    def test_undeclared_joint_that_moves_is_flagged(self):
        # idle does not declare L_hip (step does). Sweeping it from its
        # otherwise-agreed value (0,180,0) to 40 on z and back is exactly
        # "idle held a moment of a neighbour's motion."
        measured = _clean_measured()
        _find_clip(measured, "idle")["samples"]["L_hip"] = {
            "start": [0, 180, 0], "mid": [0, 180, 40], "end": [0, 180, 0]}
        violations = m.verify(_declared(), measured)
        assert any("L_hip" in v and "idle" in v and "MOVES" in v
                  and "check A" in v for v in violations)

    def test_declared_joint_moving_is_never_flagged(self):
        # chest IS declared by idle - it is SUPPOSED to move. A bug that
        # flagged a clip's own declared joints would fail this.
        measured = _clean_measured()
        _find_clip(measured, "idle")["samples"]["chest"] = {
            "start": [0, -3, 0], "mid": [0, -13, 0], "end": [0, -3, 0]}
        violations = m.verify(_declared(), measured)
        assert not any("chest" in v for v in violations)

    def test_just_under_epsilon_passes(self):
        eps = m.STILLNESS_EPSILON_DEG
        measured = _clean_measured()
        _find_clip(measured, "idle")["samples"]["L_hip"] = {
            "start": [0, 180, 0], "mid": [0, 180, eps * 0.9],
            "end": [0, 180, 0]}
        assert m.verify(_declared(), measured) == []

    def test_just_over_epsilon_fails(self):
        eps = m.STILLNESS_EPSILON_DEG
        measured = _clean_measured()
        _find_clip(measured, "idle")["samples"]["L_hip"] = {
            "start": [0, 180, 0], "mid": [0, 180, eps * 1.1],
            "end": [0, 180, 0]}
        violations = m.verify(_declared(), measured)
        assert any("L_hip" in v and "check A" in v for v in violations)

    def test_exactly_at_epsilon_passes(self):
        # The source uses a strict `>` (worst > STILLNESS_EPSILON_DEG) -
        # exactly at the boundary must not be flagged.
        eps = m.STILLNESS_EPSILON_DEG
        measured = _clean_measured()
        _find_clip(measured, "idle")["samples"]["L_hip"] = {
            "start": [0, 180, 0], "mid": [0, 180, eps], "end": [0, 180, 0]}
        assert m.verify(_declared(), measured) == []

    def test_malformed_samples_entry_is_flagged_not_silently_skipped(self):
        measured = _clean_measured()
        _find_clip(measured, "idle")["samples"]["L_hip"] = {"start": [0, 0, 0]}
        violations = m.verify(_declared(), measured)
        assert any("L_hip" in v and "malformed" in v for v in violations)


class TestCheckBAgreement:
    """Check B: the value an undeclared joint holds must agree across
    every clip that leaves it undeclared - the actual contamination check,
    and the reason this gate exists (#718's self-contained takes rule)."""

    def test_two_non_declaring_clips_disagree_names_both(self):
        # chest is declared by idle. wave holds it at the agreed [0,0,0];
        # step holds it at [5,0,0] instead - a constant WRONG value, not a
        # sweep, so check A stays silent and only B can catch it (the
        # design doc's actual failure shape: a curve holding "whatever
        # value its last key left on it").
        measured = _clean_measured()
        _find_clip(measured, "step")["samples"]["chest"] = _still(5, 0, 0)
        violations = m.verify(_declared(), measured)
        matches = [v for v in violations if "chest" in v and "check B" in v]
        assert len(matches) == 1
        msg = matches[0]
        assert "'wave'" in msg and "'step'" in msg
        assert "0.0, 0.0, 0.0" in msg
        assert "5.0, 0.0, 0.0" in msg

    def test_correct_nonzero_constant_across_all_clips_is_not_flagged(self):
        # The exact case that motivated this whole fix: an undeclared
        # joint sitting at a constant NON-ZERO value that is identical
        # across every clip that doesn't declare it - R_shoulder at
        # [0,180,270]. A hardcoded-0 reference (the first design this gate
        # shipped with) would have flagged ~270 degrees of "contamination"
        # here; the model's export-time default pose (the second design)
        # is a different, unrelated value and would have been wrong for a
        # different reason (see module docstring - it is right for some
        # joints and wrong for others, e.g. chest/spine_01, entirely by
        # accident of what pose the scene held at export). Check B needs
        # neither number: idle and step simply agree with each other.
        declared = [_clip("idle", [], 60), _clip("wave", ["R_shoulder"], 45),
                    _clip("step", [], 36)]
        measured = _measured([
            _measured_clip("idle", 2.0, {"R_shoulder": _still(0, 180, 270)}),
            _measured_clip("wave", 1.5, {}),
            _measured_clip("step", 1.2, {"R_shoulder": _still(0, 180, 270)}),
        ])
        assert m.verify(declared, measured) == []


class TestCheckBNotEvaluable:
    """Fewer than two clips leave a joint undeclared and measurable - B
    cannot run, and must say so rather than passing silently (a check that
    cannot run is not a check that passed)."""

    def test_only_one_non_declaring_clip(self):
        declared = [_clip("idle", ["chest"], 60), _clip("wave", [], 45)]
        measured = _measured([
            _measured_clip("idle", 2.0, {}),
            _measured_clip("wave", 1.5, {"chest": _still(0, 0, 0)}),
        ])
        violations = m.verify(declared, measured)
        assert len(violations) == 1
        assert "chest" in violations[0]
        assert "cannot be evaluated" in violations[0]
        assert "1 clip(s)" in violations[0]

    def test_joint_declared_by_every_clip(self):
        # chest is declared by BOTH clips here - there is no clip left
        # where it is ever undeclared, so B has zero candidates, not a
        # crash.
        declared = [_clip("idle", ["chest"], 60), _clip("wave", ["chest"], 45)]
        measured = _measured([
            _measured_clip("idle", 2.0, {}),
            _measured_clip("wave", 1.5, {}),
        ])
        violations = m.verify(declared, measured)
        assert len(violations) == 1
        assert "chest" in violations[0]
        assert "cannot be evaluated" in violations[0]
        assert "0 clip(s)" in violations[0]

    def test_no_declared_clips_at_all_does_not_crash(self):
        assert m.verify([], _measured([])) == []


class TestCyclicAngles:
    """Angles wrap at 360 degrees - a reading near 360 is close to a
    reading near 0, not far from it, and small float noise that happens to
    land just under 0 must not be mistaken for a huge disagreement. Both
    checks (A within a clip, B across clips) go through the same cyclic
    comparison; these exercise it through B, the check most exposed to two
    independently-noisy readings."""

    def test_reading_just_under_360_agrees_with_reading_just_over_zero(self):
        # 359.999 vs 0.001 is 0.002 degrees apart (< epsilon), not ~359.998
        # (> epsilon). A naive `abs(a - b)` comparison would flag this.
        declared = [_clip("idle", [], 60), _clip("wave", ["R_shoulder"], 45),
                    _clip("step", [], 36)]
        measured = _measured([
            _measured_clip("idle", 2.0, {"R_shoulder": _still(0, 0, 359.999)}),
            _measured_clip("wave", 1.5, {}),
            _measured_clip("step", 1.2, {"R_shoulder": _still(0, 0, 0.001)}),
        ])
        assert m.verify(declared, measured) == []

    def test_opposite_sign_float_noise_agrees(self):
        # Real measured noise on this rig (L_hip/R_hip's x and z axes) is
        # ~7e-15 degrees off an exact multiple of 360. Two clips reading
        # opposite-sign noise around 0 must still agree: Python's `%`
        # operator always returns a non-negative remainder, so a cyclic
        # diff implementation missing the [-180, 180] re-centring step
        # would report this pair as ~360 degrees apart instead of ~1.4e-14.
        noise = 7.01670955e-15
        declared = [_clip("idle", [], 60), _clip("wave", ["R_shoulder"], 45),
                    _clip("step", [], 36)]
        measured = _measured([
            _measured_clip("idle", 2.0,
                           {"R_shoulder": _still(noise, 180, noise)}),
            _measured_clip("wave", 1.5, {}),
            _measured_clip("step", 1.2,
                           {"R_shoulder": _still(-noise, 180, -noise)}),
        ])
        assert m.verify(declared, measured) == []


class TestCompleteness:
    """A joint that SHOULD have been sampled - declared by ANOTHER clip in
    the same DECLARED set - must actually show up in THIS clip's
    `samples`. Check A only ever walks what IS present: if Unity's
    measurement produces no reading at all for a joint, check A never sees
    it and contributes zero violations on its own - this is the gap that
    would let the gate report a false clean PASS on exactly the defect it
    exists to catch."""

    def test_joint_missing_entirely_from_samples_is_flagged(self):
        # idle's samples say NOTHING about R_shoulder - not "still",
        # ABSENT. Removing it from a 3-clip rig also drops R_shoulder's
        # check B down to one remaining candidate clip (step), so a
        # "cannot be evaluated" message rides along too (TestCheckBNotEvaluable
        # covers that mechanism directly) - this test only asserts the
        # completeness message itself is present.
        measured = _clean_measured()
        del _find_clip(measured, "idle")["samples"]["R_shoulder"]
        violations = m.verify(_declared(), measured)
        assert any("idle" in v and "R_shoulder" in v and "missing" in v
                  for v in violations)

    def test_a_clips_own_declared_joints_are_exempt_from_completeness(self):
        # chest/spine_01 are idle's OWN joints - the clean fixture never
        # puts them in idle's own `samples` at all, and that must not be
        # flagged.
        measured = _clean_measured()
        assert "chest" not in _find_clip(measured, "idle")["samples"]
        violations = m.verify(_declared(), measured)
        assert not any("chest" in v or "spine_01" in v for v in violations)

    def test_non_numeric_reading_is_flagged_not_a_crash(self):
        # A malformed-but-present reading must produce a violation, not an
        # uncaught TypeError/ValueError from float() on a non-numeric
        # value.
        measured = _clean_measured()
        _find_clip(measured, "idle")["samples"]["R_shoulder"] = {
            "start": ["oops", 0, 0], "mid": [0, 0, 0], "end": [0, 0, 0]}
        violations = m.verify(_declared(), measured)
        assert any("R_shoulder" in v and "malformed" in v for v in violations)


class TestModelDefaultPoseIsDiagnosticOnly:
    """The renamed pose block (was "rest") is context for a human reading
    a FAIL report - never a correctness reference. If verify() read it for
    anything, a wrong or absent value here would change its answer; it
    must not."""

    def test_missing_model_default_pose_block_is_not_a_violation(self):
        clip = _measured_clip("idle", 2.0,
                              {"R_shoulder": _still(0, 180, 270),
                               "L_hip": _still(0, 180, 0)})
        wave = _measured_clip("wave", 1.5, {"chest": _still(0, 0, 0),
                                            "spine_01": _still(0, 0, 0),
                                            "L_hip": _still(0, 180, 0)})
        step = _measured_clip("step", 1.2, {"chest": _still(0, 0, 0),
                                            "spine_01": _still(0, 0, 0),
                                            "R_shoulder": _still(0, 180, 270)})
        measured = {"clips": [clip, wave, step]}  # no "model_default_pose" key at all
        assert m.verify(_declared(), measured) == []

    def test_wildly_wrong_model_default_pose_does_not_change_the_verdict(self):
        # A default-pose block that disagrees with every joint's actual
        # held value (the exact shape that broke this gate's second
        # design) must have zero effect now.
        measured = _clean_measured()
        measured["model_default_pose"] = {"R_shoulder": [999, 999, 999],
                                          "L_hip": [999, 999, 999],
                                          "chest": [999, 999, 999]}
        assert m.verify(_declared(), measured) == []


class TestUnityMeasureCsIsWellFormed:
    """Not compiled (no C# toolchain here) - basic textual sanity so a
    template-substitution bug (a stray brace, a placeholder left
    unreplaced) is caught without a live Unity."""

    def test_placeholders_were_substituted(self):
        assert "__ASSET_PATH__" not in m.UNITY_MEASURE_CS
        assert "__JOINTS_CSV__" not in m.UNITY_MEASURE_CS

    def test_asset_path_is_embedded(self):
        assert m.ASSET_PATH in m.UNITY_MEASURE_CS

    def test_every_declared_joint_is_embedded(self):
        for joint in m.ALL_JOINTS:
            assert ('"%s"' % joint) in m.UNITY_MEASURE_CS

    def test_braces_balance(self):
        assert m.UNITY_MEASURE_CS.count("{") == m.UNITY_MEASURE_CS.count("}")

    def test_json_shape_keys_appear_literally(self):
        for key in ('\\"model_default_pose\\"', '\\"clips\\"', '\\"name\\"',
                   '\\"length\\"', '\\"frameRate\\"', '\\"curves\\"',
                   '\\"samples\\"'):
            assert key in m.UNITY_MEASURE_CS

    def test_no_using_directives(self):
        # execute_code runs the snippet as a METHOD BODY (CodeDom/C# 6
        # backend) - a `using` directive there is a syntax error, measured
        # on the first live run ("Line 1: Unexpected symbol 'System',
        # expecting '('"). Every line starting a `using` statement must be
        # gone.
        for line in m.UNITY_MEASURE_CS.splitlines():
            assert not line.strip().startswith("using "), line

    def test_no_linq(self):
        # LINQ is unavailable for the same reason as `using` - the first
        # draft's `.OfType<AnimationClip>()` filter must be gone.
        assert "OfType<" not in m.UNITY_MEASURE_CS
        assert ".Linq" not in m.UNITY_MEASURE_CS

    def test_preview_clips_are_filtered(self):
        assert "__preview__" in m.UNITY_MEASURE_CS

    def test_output_path_is_a_variable_up_front(self):
        assert "string outputPath" in m.UNITY_MEASURE_CS

    def test_writes_file_and_returns_a_short_summary_not_the_json(self):
        assert "File.WriteAllText" in m.UNITY_MEASURE_CS
        # The full JSON StringBuilder ("sb") must not itself be what gets
        # returned - a separate, shorter summary is built and returned.
        assert "return summary.ToString();" in m.UNITY_MEASURE_CS
        assert "return sb.ToString();" not in m.UNITY_MEASURE_CS


class TestDeclaredMatchesBaseline:
    """DECLARED must come from evals/multi_take_live/baseline.json, not be
    hand-restated - the two gates cannot be allowed to silently disagree
    about what was declared."""

    def test_declared_is_the_baseline_file_s_clips(self):
        import json
        with open(m.BASELINE_PATH) as fh:
            baseline = json.load(fh)
        assert m.DECLARED == baseline["clips"]

    def test_fbx_path_resolves_next_to_the_baseline_file(self):
        assert os.path.dirname(m.FBX_PATH) == os.path.dirname(m.BASELINE_PATH)
