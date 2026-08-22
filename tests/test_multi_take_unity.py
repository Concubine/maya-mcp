"""#718 consumer gate: pure tests for evals/multi_take_unity.py's `verify()`.

No Unity, no Maya, no I/O. verify() is the policy that judges the JSON a
real Unity import produces (via UNITY_MEASURE_CS) against what Maya
declared - it is reviewable and testable precisely because it never talks
to a live editor. This is the only place that logic is exercised without a
scratch Unity project; see .superpowers/sdd/t718-13-report.md and
.superpowers/sdd/t718-unity-fix-report.md for what UNITY_MEASURE_CS itself
could NOT be verified by running, and what the first real Unity run
measured.

No prior eval script in this repo has a dedicated pure-logic test file
(evals/*_live.py and evals/multi_take_unity.py's own C#/measurement half
need a live Maya or Unity and are proven by the eval's own printed
checks/report instead) - this file follows tests/test_export_fbx.py's
sys.path convention for reaching into evals/.

Every `measured` fixture below carries an explicit top-level "rest" block
(possibly {}) unless the test is specifically about a MISSING one
(TestRestBlock) - verify() treats an absent "rest" key as its own
violation (see verify()'s docstring, check 0), so any fixture that omits
it unintentionally would fail for the wrong reason.
"""

import os
import sys

_EVALS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "evals")
if _EVALS not in sys.path:
    sys.path.insert(0, _EVALS)

import multi_take_unity as m                        # noqa: E402


def _declared(**overrides):
    record = {"name": "idle", "fps": 30, "start_frame": 0, "end_frame": 60,
              "joints": ["chest", "spine_01"]}
    record.update(overrides)
    return record


def _measured_clip(**overrides):
    clip = {"name": "idle", "length": 2.0, "frameRate": 30.0,
            "curves": [], "samples": {}}
    clip.update(overrides)
    return clip


def _measured(clips, rest=None):
    """Builds the full payload verify() expects: {"rest": ..., "clips":
    ...}. `rest` defaults to {} - fine for any test whose fixtures never
    reach a rest lookup (no samples, or every undeclared joint already
    caught by an earlier check)."""
    return {"rest": {} if rest is None else rest, "clips": clips}


def _still(x=0.0, y=0.0, z=0.0):
    """A joint reading held perfectly constant at (x, y, z) across all
    three samples."""
    return {"start": [x, y, z], "mid": [x, y, z], "end": [x, y, z]}


class TestCleanCase:
    def test_matching_clip_with_no_samples_is_clean(self):
        assert m.verify([_declared()], _measured([_measured_clip()])) == []

    def test_still_undeclared_joint_is_clean(self):
        # "still" is measured to the third decimal here, well inside
        # STILLNESS_EPSILON_DEG (0.01) - this must pass. Rest for L_hip is
        # the assumed-0 case: a joint whose true rest happens to be 0 is
        # not, by itself, evidence the fix is wrong - see
        # TestRestPose for the case that actually distinguishes them.
        clip = _measured_clip(samples={
            "L_hip": {"start": [0.0, 0.001, 0.0],
                      "mid": [0.0, -0.001, 0.0],
                      "end": [0.0, 0.0, 0.0]}})
        measured = _measured([clip], rest={"L_hip": [0.0, 0.0, 0.0]})
        assert m.verify([_declared()], measured) == []

    def test_multiple_declared_clips_all_clean(self):
        # A realistic measured payload: UNITY_MEASURE_CS samples every
        # declared joint (not just the current clip's own) in every clip,
        # so a clean sibling-clip joint must be present here too, held at
        # its own rest - the completeness check (TestCompleteness)
        # requires it.
        at_rest = _still(0, 0, 0)
        declared = [_declared(name="idle"), _declared(name="wave",
                    joints=["R_shoulder"])]
        measured = _measured(
            [_measured_clip(name="idle", samples={"R_shoulder": at_rest}),
             _measured_clip(name="wave", samples={"chest": at_rest,
                                                   "spine_01": at_rest})],
            rest={"R_shoulder": [0, 0, 0], "chest": [0, 0, 0],
                  "spine_01": [0, 0, 0]})
        assert m.verify(declared, measured) == []


class TestExtraUnityContentIsNotAViolation:
    """A clip Unity carries that Maya never declared is not this gate's
    business - the same rule the byte gate applies to an undeclared take
    (#718 design doc). If verify() flagged it, this would fail."""

    def test_undeclared_clip_in_unity_is_ignored(self):
        measured = _measured([_measured_clip(name="idle"),
                              _measured_clip(name="Take 001", length=6.4)])
        assert m.verify([_declared()], measured) == []

    def test_undeclared_but_present_joint_that_is_declared_by_ANOTHER_clip_here_is_still_checked(self):
        # Sanity: "extra content is fine" must not be confused with "any
        # joint reading is fine" - a joint THIS clip doesn't declare, but
        # which ANOTHER declared clip in the same set legitimately owns
        # (so it is part of the completeness universe too, see
        # TestCompleteness), must still be contamination-checked here.
        # R_shoulder is held at a CONSTANT wrong value (not a sweep back
        # to rest) so only the at-rest check (4b) fires, not the movement
        # check (4a) - keeps this test isolated to the completeness/
        # cross-clip point it is actually about. Distinct from
        # TestContamination.test_undeclared_joint_that_moves_is_flagged,
        # whose offending joint (L_hip) isn't declared by ANY clip in that
        # test's single-clip `declared` list.
        at_rest = _still(0, 0, 0)
        declared = [_declared(name="idle", joints=["chest"]),
                    _declared(name="wave", joints=["R_shoulder"])]
        measured = _measured(
            [_measured_clip(name="idle",
                             samples={"R_shoulder": _still(0, 0, 40)}),
             _measured_clip(name="wave", samples={"chest": at_rest})],
            rest={"R_shoulder": [0, 0, 0], "chest": [0, 0, 0]})
        violations = m.verify(declared, measured)
        assert len(violations) == 1
        assert "idle" in violations[0]
        assert "R_shoulder" in violations[0]


class TestMissingClip:
    def test_declared_clip_absent_from_unity_is_named(self):
        violations = m.verify([_declared(name="idle")], _measured([]))
        assert len(violations) == 1
        assert "idle" in violations[0]
        assert "not found" in violations[0]

    def test_only_the_missing_one_is_named_when_others_are_present(self):
        declared = [_declared(name="idle"), _declared(name="wave")]
        measured = _measured([_measured_clip(name="idle")])
        violations = m.verify(declared, measured)
        assert len(violations) == 1
        assert violations[0].startswith("clip 'wave'")


class TestLengthTolerance:
    """(end_frame - start_frame) / fps == (60 - 0) / 30 == 2.0 exactly.
    Both sides of LENGTH_TOL_S (1e-3) are asserted so a widened or
    inverted tolerance in a future edit cannot pass silently."""

    def test_just_under_tolerance_passes(self):
        clip = _measured_clip(length=2.0 + m.LENGTH_TOL_S * 0.5)
        assert m.verify([_declared()], _measured([clip])) == []

    def test_just_over_tolerance_fails(self):
        clip = _measured_clip(length=2.0 + m.LENGTH_TOL_S * 1.5)
        violations = m.verify([_declared()], _measured([clip]))
        assert len(violations) == 1
        assert "idle" in violations[0]
        assert "length" in violations[0]

    def test_exactly_at_tolerance_passes(self):
        # "more than 1e-3" (brief's own wording) is a strict inequality -
        # exactly at the boundary must not be flagged.
        clip = _measured_clip(length=2.0 + m.LENGTH_TOL_S)
        assert m.verify([_declared()], _measured([clip])) == []


class TestContamination:
    """The exact defect #718's self-contained rule exists to prevent: a
    joint this clip never keys reads a neighbouring clip's pose instead of
    holding still. This is verify()'s whole reason to exist.

    verify() runs TWO checks per undeclared joint - movement (4a) and
    at-rest (4b) - and reports them as distinguishable violations. A joint
    that both moves AND ends up away from its own rest (a sweep starting
    and ending at rest) can trigger both at once; the tests below use a
    CONSTANT-hold shape wherever the point is isolating one check, and a
    sweep shape (asserting both fire) where the point is movement itself.
    """

    def test_undeclared_joint_that_moves_is_flagged(self):
        # idle declares only chest/spine_01. L_hip sweeping from its own
        # rest (0) to 40 degrees and back is exactly "idle held wave's
        # pose for an instant" - both the movement check (4a) and the
        # at-rest check (4b, since mid=40 is far from rest=0) fire.
        clip = _measured_clip(samples={
            "L_hip": {"start": [0, 0, 0], "mid": [0, 0, 40], "end": [0, 0, 0]}})
        measured = _measured([clip], rest={"L_hip": [0, 0, 0]})
        violations = m.verify([_declared()], measured)
        assert len(violations) == 2
        assert all("L_hip" in v and "idle" in v for v in violations)
        assert any("MOVES" in v for v in violations)
        assert any("contamination" in v for v in violations)

    def test_declared_joint_moving_is_never_flagged(self):
        # chest IS declared by idle - it is SUPPOSED to move. A bug that
        # flagged declared joints would fail this.
        clip = _measured_clip(samples={
            "chest": {"start": [0, -3, 0], "mid": [0, -13, 0],
                      "end": [0, -3, 0]}})
        measured = _measured([clip], rest={"chest": [0, 0, 0]})
        assert m.verify([_declared()], measured) == []

    def test_just_under_epsilon_passes(self):
        eps = m.STILLNESS_EPSILON_DEG
        clip = _measured_clip(samples={
            "L_hip": {"start": [0, 0, 0], "mid": [0, 0, eps * 0.9],
                      "end": [0, 0, 0]}})
        measured = _measured([clip], rest={"L_hip": [0, 0, 0]})
        assert m.verify([_declared()], measured) == []

    def test_just_over_epsilon_fails(self):
        # This spike is both a movement over epsilon (4a) and a reading
        # over epsilon away from rest at its midpoint (4b) - both checks
        # are built on the exact same comparison here (rest happens to be
        # 0, and start/end already sit at rest), so both fire together.
        eps = m.STILLNESS_EPSILON_DEG
        clip = _measured_clip(samples={
            "L_hip": {"start": [0, 0, 0], "mid": [0, 0, eps * 1.1],
                      "end": [0, 0, 0]}})
        measured = _measured([clip], rest={"L_hip": [0, 0, 0]})
        violations = m.verify([_declared()], measured)
        assert len(violations) == 2
        assert all("L_hip" in v for v in violations)

    def test_exactly_at_epsilon_passes(self):
        # The source uses a strict `>` (worst > STILLNESS_EPSILON_DEG) -
        # exactly at the boundary must not be flagged, same as
        # TestLengthTolerance.test_exactly_at_tolerance_passes pins for
        # LENGTH_TOL_S.
        eps = m.STILLNESS_EPSILON_DEG
        clip = _measured_clip(samples={
            "L_hip": {"start": [0, 0, 0], "mid": [0, 0, eps],
                      "end": [0, 0, 0]}})
        measured = _measured([clip], rest={"L_hip": [0, 0, 0]})
        assert m.verify([_declared()], measured) == []

    def test_backward_hold_pattern_is_caught(self):
        # The design doc's specific failure shape: a curve holds a LATER
        # clip's first key BACKWARDS across an earlier clip's whole range
        # when the backward pin is missing - start/mid/end all equal to
        # the neighbour's non-rest value, not a smooth sweep. A CONSTANT
        # hold never moves (4a stays silent) - only the at-rest check (4b)
        # can catch this, which is the whole reason 4b exists as an
        # absolute check rather than a variance check.
        clip = _measured_clip(samples={"R_shoulder": _still(0, 0, -40)})
        measured = _measured([clip], rest={"R_shoulder": [0, 0, 0]})
        violations = m.verify([_declared()], measured)
        assert len(violations) == 1
        assert "R_shoulder" in violations[0]
        assert "contamination" in violations[0]

    def test_malformed_samples_entry_is_flagged_not_silently_skipped(self):
        clip = _measured_clip(samples={"L_hip": {"start": [0, 0, 0]}})
        measured = _measured([clip], rest={"L_hip": [0, 0, 0]})
        violations = m.verify([_declared()], measured)
        assert len(violations) == 1
        assert "L_hip" in violations[0]
        assert "malformed" in violations[0]


class TestRestPose:
    """The regression the real Unity run exposed: a joint's rest is NOT
    [0,0,0] in Unity (it carries the import-time joint orientation), and
    verify() must compare against the joint's OWN measured rest, not an
    assumed zero. These are the false-positive shape from the first live
    run: L_ankle held CONSTANT at [270, 293.1986, 0] across all three
    samples of a clip that never declares it - a joint that is not moving
    at all, wrongly flagged only because the reference value was wrong."""

    def test_still_at_own_non_zero_rest_is_not_flagged(self):
        # If verify() still assumed rest=[0,0,0] (the bug), this would be
        # flagged as ~293 degrees of contamination. It must not be.
        clip = _measured_clip(
            samples={"L_ankle": _still(270, 293.1986, 0)})
        measured = _measured([clip], rest={"L_ankle": [270, 293.1986, 0]})
        assert m.verify([_declared()], measured) == []

    def test_constant_reading_at_a_DIFFERENT_non_zero_pose_is_flagged(self):
        # L_ankle's true rest is [270, 293.1986, 0] (measured on the real
        # rig) but it is held CONSTANT at R_shoulder's rest
        # [0, 180, 270] instead - the documented contamination shape,
        # exercised with realistic non-zero values on both sides so a fix
        # that merely swapped "compare to 0" for "compare to some fixed
        # non-zero constant" (rather than each joint's OWN rest) would
        # fail to catch this.
        clip = _measured_clip(
            samples={"L_ankle": _still(0, 180, 270)})
        measured = _measured([clip], rest={"L_ankle": [270, 293.1986, 0]})
        violations = m.verify([_declared()], measured)
        assert len(violations) == 1
        assert "L_ankle" in violations[0]
        assert "contamination" in violations[0]

    def test_realistic_multi_joint_rest_block_all_clean(self):
        # The clean case carrying a full realistic rest block (the actual
        # values measured on the real rig for #718's first Unity run,
        # given in the ticket) - every undeclared joint held constant at
        # its own rest must produce zero violations.
        rest = {
            "L_ankle": [270, 293.1986, 0], "L_hip": [0.0, 180, 0.0],
            "R_ankle": [270, 293.1986, 0], "R_hip": [0.0, 180, 0.0],
            "R_shoulder": [0.0, 180, 270], "L_knee": [0, 0, 0],
            "R_knee": [0, 0, 0], "R_elbow": [0, 0, 0],
        }
        clip = _measured_clip(samples={
            joint: _still(*value) for joint, value in rest.items()})
        measured = _measured([clip], rest=rest)
        assert m.verify([_declared()], measured) == []


class TestRestBlock:
    """A `measured` payload with no top-level "rest" key at all - the
    structural gap check 0 exists to catch, distinct from a per-joint gap
    in TestCompleteness."""

    def test_missing_rest_block_is_its_own_violation(self):
        clip = _measured_clip(samples={"L_hip": _still(0, 0, 0)})
        violations = m.verify([_declared()], {"clips": [clip]})
        assert len(violations) == 1
        assert "rest" in violations[0]

    def test_joint_absent_from_a_present_rest_block_is_flagged(self):
        # "rest" IS present, but this particular joint has no entry in
        # it - distinct from the block being missing entirely (which
        # would already have been reported by check 0 and this per-joint
        # message is suppressed to avoid restating the same gap once per
        # joint).
        clip = _measured_clip(samples={"L_hip": _still(0, 0, 0)})
        measured = _measured([clip], rest={})
        violations = m.verify([_declared()], measured)
        assert len(violations) == 1
        assert "L_hip" in violations[0]
        assert "no rest measurement" in violations[0]


class TestCyclicAngles:
    """Angles wrap at 360 degrees - a reading near 360 is close to a rest
    near 0, not far from it, and small float noise that happens to land
    just under 0 (so `% 360` alone reports it near +360) must not be
    mistaken for a huge excursion."""

    def test_reading_just_under_360_against_rest_of_zero_is_not_flagged(self):
        # 359.999 vs 0 is 0.001 degrees away (< epsilon), not 359.999
        # (> epsilon). A naive `abs(a - b)` comparison would flag this.
        clip = _measured_clip(
            samples={"L_hip": _still(0, 0, 359.999)})
        measured = _measured([clip], rest={"L_hip": [0, 0, 0]})
        assert m.verify([_declared()], measured) == []

    def test_negative_float_noise_against_rest_of_zero_is_not_flagged(self):
        # Real measured noise on this rig (L_hip/R_hip's x and z axes) is
        # ~7e-15 degrees off an exact multiple of 360 - here deliberately
        # NEGATIVE, since Python's `%` operator always returns a
        # non-negative remainder: (-7e-15) % 360 lands near +360, not near
        # 0, unless the shortest-path re-centring (subtract 360 when the
        # raw modulo result is > 180) actually happens. A cyclic diff
        # implementation missing that re-centring step would report this
        # as ~360 degrees of contamination instead of ~7e-15.
        noise = -7.01670955e-15
        clip = _measured_clip(
            samples={"L_hip": _still(noise, 180, noise)})
        measured = _measured([clip], rest={"L_hip": [0, 180, 0]})
        assert m.verify([_declared()], measured) == []


class TestCompleteness:
    """A joint that SHOULD have been sampled - declared by ANOTHER clip in
    the same DECLARED set, so UNITY_MEASURE_CS's declaredJoints includes it
    - must actually show up in THIS clip's `samples`. The contamination
    checks above only ever iterate over what IS present in `samples`: if
    Unity's measurement produces no reading at all for a joint (a name
    mismatch after import, a lookup miss, any gap), that joint is simply
    absent, those checks never see it, contribute zero violations, and the
    gate reports a clean PASS on exactly the defect it exists to catch.
    This is the Important finding from wave 1 review."""

    def test_joint_missing_entirely_from_samples_is_a_violation(self):
        # idle declares chest only; wave declares R_shoulder. idle's own
        # measured samples say NOTHING about R_shoulder - not "still",
        # ABSENT. Today (pre-fix) this is invisible: verify() only walks
        # samples.items(), and R_shoulder is not a key.
        at_rest = _still(0, 0, 0)
        declared = [_declared(name="idle", joints=["chest"]),
                    _declared(name="wave", joints=["R_shoulder"])]
        measured = _measured(
            [_measured_clip(name="idle", samples={}),
             _measured_clip(name="wave", samples={
                 "R_shoulder": {"start": [0, 0, 0], "mid": [0, 0, 30],
                                "end": [0, 0, 0]},
                 "chest": at_rest})],
            rest={"chest": [0, 0, 0]})
        violations = m.verify(declared, measured)
        assert len(violations) == 1
        assert "idle" in violations[0]
        assert "R_shoulder" in violations[0]
        assert "missing" in violations[0]

    def test_a_clips_own_declared_joints_are_exempt_from_completeness(self):
        # chest is idle's OWN joint - it is supposed to move and is not
        # what the completeness check is about, so its absence from
        # `samples` here must not be flagged.
        declared = [_declared(name="idle", joints=["chest"])]
        measured = _measured([_measured_clip(name="idle", samples={})])
        assert m.verify(declared, measured) == []

    def test_non_numeric_reading_is_flagged_not_a_crash(self):
        # A malformed-but-present reading must produce a violation, not an
        # uncaught TypeError/ValueError from float() on a non-numeric
        # value.
        at_rest = _still(0, 0, 0)
        declared = [_declared(name="idle", joints=["chest"]),
                    _declared(name="wave", joints=["R_shoulder"])]
        measured = _measured(
            [_measured_clip(name="idle", samples={
                "R_shoulder": {"start": ["oops", 0, 0], "mid": [0, 0, 0],
                               "end": [0, 0, 0]}}),
             _measured_clip(name="wave", samples={"chest": at_rest})],
            rest={"chest": [0, 0, 0]})
        violations = m.verify(declared, measured)
        assert len(violations) == 1
        assert "R_shoulder" in violations[0]
        assert "malformed" in violations[0]


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
        for key in ('\\"rest\\"', '\\"clips\\"', '\\"name\\"',
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
