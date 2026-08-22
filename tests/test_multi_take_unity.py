"""#718 consumer gate: pure tests for evals/multi_take_unity.py's `verify()`.

No Unity, no Maya, no I/O. verify() is the policy that judges the JSON a
real Unity import produces (via UNITY_MEASURE_CS) against what Maya
declared - it is reviewable and testable precisely because it never talks
to a live editor. This is the only place that logic is exercised without a
scratch Unity project; see .superpowers/sdd/t718-13-report.md for what
UNITY_MEASURE_CS itself could NOT be verified by running.

No prior eval script in this repo has a dedicated pure-logic test file
(evals/*_live.py and evals/multi_take_unity.py's own C#/measurement half
need a live Maya or Unity and are proven by the eval's own printed
checks/report instead) - this file follows tests/test_export_fbx.py's
sys.path convention for reaching into evals/.
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


class TestCleanCase:
    def test_matching_clip_with_no_samples_is_clean(self):
        assert m.verify([_declared()], {"clips": [_measured_clip()]}) == []

    def test_still_undeclared_joint_is_clean(self):
        # "still" is measured to the third decimal here, well inside
        # STILLNESS_EPSILON_DEG (0.01) - this must pass.
        clip = _measured_clip(samples={
            "L_hip": {"start": [0.0, 0.001, 0.0],
                      "mid": [0.0, -0.001, 0.0],
                      "end": [0.0, 0.0, 0.0]}})
        assert m.verify([_declared()], {"clips": [clip]}) == []

    def test_multiple_declared_clips_all_clean(self):
        declared = [_declared(name="idle"), _declared(name="wave",
                    joints=["R_shoulder"])]
        measured = {"clips": [_measured_clip(name="idle"),
                              _measured_clip(name="wave")]}
        assert m.verify(declared, measured) == []


class TestExtraUnityContentIsNotAViolation:
    """A clip Unity carries that Maya never declared is not this gate's
    business - the same rule the byte gate applies to an undeclared take
    (#718 design doc). If verify() flagged it, this would fail."""

    def test_undeclared_clip_in_unity_is_ignored(self):
        measured = {"clips": [_measured_clip(name="idle"),
                              _measured_clip(name="Take 001", length=6.4)]}
        assert m.verify([_declared()], measured) == []

    def test_undeclared_but_present_joint_that_is_declared_by_ANOTHER_clip_here_is_still_checked(self):
        # Sanity: "extra content is fine" must not be confused with "any
        # joint reading is fine" - a joint THIS clip doesn't declare must
        # still be checked (see TestContamination below). This test only
        # pins that an extra whole CLIP is what's exempt, not an extra
        # joint reading within a declared clip.
        clip = _measured_clip(samples={
            "R_shoulder": {"start": [0, 0, 0], "mid": [0, 0, 40],
                           "end": [0, 0, 0]}})
        violations = m.verify([_declared()], {"clips": [clip]})
        assert len(violations) == 1
        assert "R_shoulder" in violations[0]


class TestMissingClip:
    def test_declared_clip_absent_from_unity_is_named(self):
        violations = m.verify([_declared(name="idle")], {"clips": []})
        assert len(violations) == 1
        assert "idle" in violations[0]
        assert "not found" in violations[0]

    def test_only_the_missing_one_is_named_when_others_are_present(self):
        declared = [_declared(name="idle"), _declared(name="wave")]
        measured = {"clips": [_measured_clip(name="idle")]}
        violations = m.verify(declared, measured)
        assert len(violations) == 1
        assert violations[0].startswith("clip 'wave'")


class TestLengthTolerance:
    """(end_frame - start_frame) / fps == (60 - 0) / 30 == 2.0 exactly.
    Both sides of LENGTH_TOL_S (1e-3) are asserted so a widened or
    inverted tolerance in a future edit cannot pass silently."""

    def test_just_under_tolerance_passes(self):
        clip = _measured_clip(length=2.0 + m.LENGTH_TOL_S * 0.5)
        assert m.verify([_declared()], {"clips": [clip]}) == []

    def test_just_over_tolerance_fails(self):
        clip = _measured_clip(length=2.0 + m.LENGTH_TOL_S * 1.5)
        violations = m.verify([_declared()], {"clips": [clip]})
        assert len(violations) == 1
        assert "idle" in violations[0]
        assert "length" in violations[0]

    def test_exactly_at_tolerance_passes(self):
        # "more than 1e-3" (brief's own wording) is a strict inequality -
        # exactly at the boundary must not be flagged.
        clip = _measured_clip(length=2.0 + m.LENGTH_TOL_S)
        assert m.verify([_declared()], {"clips": [clip]}) == []


class TestContamination:
    """The exact defect #718's self-contained rule exists to prevent: a
    joint this clip never keys reads a neighbouring clip's pose instead of
    holding still. This is verify()'s whole reason to exist."""

    def test_undeclared_joint_that_moves_is_flagged(self):
        # idle declares only chest/spine_01. L_hip moving 40 degrees across
        # idle's own range is exactly "idle held wave's pose".
        clip = _measured_clip(samples={
            "L_hip": {"start": [0, 0, 0], "mid": [0, 0, 40], "end": [0, 0, 0]}})
        violations = m.verify([_declared()], {"clips": [clip]})
        assert len(violations) == 1
        assert "L_hip" in violations[0]
        assert "idle" in violations[0]

    def test_declared_joint_moving_is_never_flagged(self):
        # chest IS declared by idle - it is SUPPOSED to move. A bug that
        # flagged declared joints would fail this.
        clip = _measured_clip(samples={
            "chest": {"start": [0, -3, 0], "mid": [0, -13, 0],
                      "end": [0, -3, 0]}})
        assert m.verify([_declared()], {"clips": [clip]}) == []

    def test_just_under_epsilon_passes(self):
        eps = m.STILLNESS_EPSILON_DEG
        clip = _measured_clip(samples={
            "L_hip": {"start": [0, 0, 0], "mid": [0, 0, eps * 0.9],
                      "end": [0, 0, 0]}})
        assert m.verify([_declared()], {"clips": [clip]}) == []

    def test_just_over_epsilon_fails(self):
        eps = m.STILLNESS_EPSILON_DEG
        clip = _measured_clip(samples={
            "L_hip": {"start": [0, 0, 0], "mid": [0, 0, eps * 1.1],
                      "end": [0, 0, 0]}})
        violations = m.verify([_declared()], {"clips": [clip]})
        assert len(violations) == 1
        assert "L_hip" in violations[0]

    def test_backward_hold_pattern_is_caught(self):
        # The design doc's specific failure shape: a curve holds a LATER
        # clip's first key BACKWARDS across an earlier clip's whole range
        # when the backward pin is missing - start/mid/end all equal to
        # the neighbour's non-rest value, not a smooth sweep.
        clip = _measured_clip(samples={
            "R_shoulder": {"start": [0, 0, -40], "mid": [0, 0, -40],
                           "end": [0, 0, -40]}})
        violations = m.verify([_declared()], {"clips": [clip]})
        assert len(violations) == 1
        assert "R_shoulder" in violations[0]

    def test_malformed_samples_entry_is_flagged_not_silently_skipped(self):
        clip = _measured_clip(samples={"L_hip": {"start": [0, 0, 0]}})
        violations = m.verify([_declared()], {"clips": [clip]})
        assert len(violations) == 1
        assert "L_hip" in violations[0]
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
        for key in ('\\"clips\\"', '\\"name\\"', '\\"length\\"',
                   '\\"frameRate\\"', '\\"curves\\"', '\\"samples\\"'):
            assert key in m.UNITY_MEASURE_CS


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
