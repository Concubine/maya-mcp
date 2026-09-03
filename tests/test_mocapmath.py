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

    def test_idle_parses_and_maps(self):
        with open(os.path.join(FIXTURES, "cmu_idle.bvh")) as fh:
            r = mm.parse_bvh(fh.read())
        assert r["frames"] > 30
        names = [j["name"] for j in r["joints"]]
        mapped = mm.resolve_hik_map(names, mm.CMU_HIK_MAP)
        assert set(mapped) == set(mm.REQUIRED_HIK_SLOTS)

    def test_walk_root_translates_more_than_idle(self):
        # The fixture-selection sanity check: a walk clip's root should
        # travel far more than an idle/stand clip's root over its run,
        # otherwise the two fixtures do not actually differ the way their
        # names claim.
        def root_travel(path):
            with open(path) as fh:
                r = mm.parse_bvh(fh.read())
            xs = [row[0] for row in r["rows"]]
            zs = [row[2] for row in r["rows"]]
            return max(xs) - min(xs) + max(zs) - min(zs)

        walk_travel = root_travel(os.path.join(FIXTURES, "cmu_walk.bvh"))
        idle_travel = root_travel(os.path.join(FIXTURES, "cmu_idle.bvh"))
        assert walk_travel > 10.0 * max(idle_travel, 1e-6)


class TestFps:
    def test_source_fps_from_frame_time(self):
        assert mm.source_fps(1.0 / 120.0) == pytest.approx(120.0)

    def test_nearest_bake_fps(self):
        assert mm.nearest_bake_fps(120.0, {24, 25, 30, 48, 50, 60}) == 60
        assert mm.nearest_bake_fps(30.0003, {24, 25, 30, 48, 50, 60}) == 30

    def test_nearest_bake_fps_ties_toward_higher(self):
        assert mm.nearest_bake_fps(27.0, {24, 30}) == 30

    def test_frame_time_refused_when_non_positive(self):
        with pytest.raises(HandlerError, match="frame time"):
            mm.source_fps(0.0)
        with pytest.raises(HandlerError, match="frame time"):
            mm.source_fps(-0.01)

    def test_frame_time_refused_when_absurd(self):
        with pytest.raises(HandlerError, match="frame time"):
            mm.source_fps(1.0 / 5000.0)


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


class TestTheWindowThatActuallyFits:
    """#797 rows 24/42: `smooth_track`'s window SHRINKS per sample, so a
    window wider than the track is not an error and not a wider filter -
    it is the same filter as the widest window that fits, silently. The
    number clean_clip needs in order to say so.
    """

    def test_the_widest_window_is_the_track_on_an_odd_length(self):
        assert mm.largest_smoothing_window(31) == 31

    def test_an_even_length_loses_its_last_sample_to_centering(self):
        # a centered odd window cannot span 30 - 29 is the widest that can
        # sit on the middle sample.
        assert mm.largest_smoothing_window(30) == 29

    def test_a_track_too_short_for_any_legal_window_answers_zero(self):
        # smooth_track's own floor is 5; below that no window is legal.
        assert mm.largest_smoothing_window(4) == 0
        assert mm.largest_smoothing_window(1) == 0
        assert mm.largest_smoothing_window(0) == 0

    def test_the_floor_is_smooth_tracks_own(self):
        assert mm.largest_smoothing_window(5) == 5
        assert mm.MIN_SMOOTHING_SAMPLES == 5

    def test_every_window_past_the_fit_is_the_same_filter(self):
        # The measured claim the refusal is built on (#797 row 24): on a
        # 30-sample track, window 31 and window 101 both produce EXACTLY
        # what window 29 produces.
        track = [float(i % 3) for i in range(30)]
        fit = mm.smooth_track(track, window=29)
        assert mm.smooth_track(track, window=31) == pytest.approx(fit)
        assert mm.smooth_track(track, window=101) == pytest.approx(fit)

    def test_a_track_below_the_floor_is_returned_unchanged(self):
        # identity for n <= 4: every shrunk fit spans <= its own order, so
        # the polynomial passes through every sample exactly.
        for n in (1, 2, 3, 4):
            track = [float(i % 3) for i in range(n)]
            assert mm.smooth_track(track, window=5) == pytest.approx(track)
        # and at 5 it finally moves a value
        five = [0.0, 1.0, 0.0, 1.0, 0.0]
        assert mm.smooth_track(five, window=5) != pytest.approx(five)


class TestBlendWeights:
    def test_ramps_zero_to_one_to_zero(self):
        w = mm.blend_weights(10, edge=3)
        assert w[0] == pytest.approx(0.0)
        assert max(w) == pytest.approx(1.0)
        assert w[-1] == pytest.approx(0.0)
        assert w == pytest.approx(list(reversed(w)))
