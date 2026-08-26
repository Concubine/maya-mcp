"""motionmath - the pure metrics behind measure_clip (#773). No Maya."""

import math

from maya_plugin.handlers import motionmath


def straight_track(n, step=0.1, y=0.0):
    return [[i * step, y, 0.0] for i in range(n)]


class TestKinematics:
    def test_speeds_are_per_second_not_per_frame(self):
        # 0.1 units per frame at 30 fps is 3 units/second.
        v = motionmath.speeds(straight_track(4), fps=30.0)
        assert all(abs(s - 3.0) < 1e-9 for s in v)
        assert len(v) == 3

    def test_a_pop_lands_in_max_accel_with_its_frame(self):
        # Constant speed, then one frame teleports: the discriminator the
        # #773 probe measured as 111 vs 53 against the clean mirror limb.
        track = straight_track(10)
        track[5][0] += 0.5
        kin = motionmath.joint_kinematics(track, fps=30.0)
        # the spike lands on an interval TOUCHING the popped sample - the
        # acceleration between the approach and the teleport
        assert 4 <= kin["max_accel_frame"] <= 6
        assert kin["peak_speed"] > 10.0

    def test_a_still_joint_reports_zeros_not_noise(self):
        kin = motionmath.joint_kinematics([[1, 2, 3]] * 8, fps=30.0)
        assert kin["path_length"] == 0.0
        assert kin["peak_speed"] == 0.0
        assert kin["max_accel"] == 0.0

    def test_loop_closure_is_the_first_to_last_distance(self):
        track = straight_track(5)
        assert abs(motionmath.loop_closure(track) - 0.4) < 1e-9
        track.append(track[0])
        assert motionmath.loop_closure(track) == 0.0


class TestContact:
    def test_a_plant_is_low_and_slow_and_a_swing_is_neither(self):
        # Half plant (still at ground), half swing (fast and lifted) - the
        # walk-in-place shape the probe used. One run, covering the plant.
        plant = [[0.0, 0.0, 0.0]] * 10
        swing = [[0.0, 0.1 * math.sin(i / 9 * math.pi),
                  0.05 * i] for i in range(10)]
        runs = motionmath.contact_runs(plant + swing, fps=30.0, rig_height=1.0)
        assert len(runs) == 1
        first, last = runs[0]
        assert first == 0
        assert last <= 11  # the swing frames are not contact

    def test_slide_is_the_net_drift_of_one_run_not_jitter(self):
        # Within-tolerance jitter that returns to start is NOT a slide;
        # a net drift is. Both stay low and slow.
        # 13 samples: an odd count so the alternating jitter genuinely ends
        # where it began - with an even count its own endpoints differ.
        jitter = [[0.001 * (-1) ** i, 0.0, 0.0] for i in range(13)]
        drift = [[0.005 * i, 0.0, 0.0] for i in range(12)]
        for track, expected in ((jitter, 0.0), (drift, 0.055)):
            runs = motionmath.contact_runs(track, fps=30.0, rig_height=1.0)
            slide = motionmath.max_slide(track, runs)
            assert abs(slide - expected) < 2e-3, (expected, slide, runs)

    def test_the_probes_measured_case_discriminates(self):
        # The numbers from the live #773 probe: a clean plant slid 0.0, the
        # broken one 0.097 on a 1.0-height rig. The warn threshold (2%) must
        # separate them with a wide margin on both sides.
        assert motionmath.SLIDE_WARN_FRAC * 1.0 > 0.0 + 1e-6
        assert 0.097 > motionmath.SLIDE_WARN_FRAC * 1.0 * 2

    def test_a_degenerate_rig_height_yields_no_runs(self):
        assert motionmath.contact_runs(
            straight_track(5), fps=30.0, rig_height=0.0) == []


class TestSymmetry:
    def test_pairs_by_the_repos_own_naming(self):
        pairs = motionmath.mirror_pairs(
            ["hips", "L_foot", "R_foot", "L_hand", "spine", "R_knee"])
        assert ("L_foot", "R_foot") in pairs
        assert ("L_hand", "R_hand") not in pairs  # no mirror present
        assert all("spine" not in p for p in pairs)

    def test_ratio_reads_one_for_symmetric_and_large_for_popped(self):
        # The probe: 1.0 clean, 2.4 with a popped key on one limb.
        assert motionmath.symmetry_ratio(3.385, 3.385) == 1.0
        assert abs(motionmath.symmetry_ratio(8.05, 3.385) - 2.378) < 1e-2
        assert motionmath.symmetry_ratio(3.385, 8.05) == \
            motionmath.symmetry_ratio(8.05, 3.385)

    def test_still_limbs_are_symmetric_not_a_division_error(self):
        assert motionmath.symmetry_ratio(0.0, 0.0) == 1.0
        assert motionmath.symmetry_ratio(1.0, 0.0) == float("inf")
