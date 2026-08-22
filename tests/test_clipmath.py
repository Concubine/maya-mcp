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


class TestRecords:
    def _records(self):
        return [
            {"name": "idle", "fps": 30, "start_frame": 0, "end_frame": 60,
             "duration_s": 2.0, "loop": True, "interpolation": "smooth",
             "joints": ["chest"], "weight_channels": ["blink"],
             "root_position_used": False},
            {"name": "walk", "fps": 30, "start_frame": 62, "end_frame": 98,
             "duration_s": 1.2, "loop": True, "interpolation": "linear",
             "joints": ["L_hip"], "weight_channels": [],
             "root_position_used": True},
        ]

    def test_a_bare_object_reads_as_one_record(self):
        """Every scene authored before #718 carries a bare object with no
        frame range: it is clip one, starting at frame 0."""
        out = clipmath.normalized_records(
            {"name": "sway", "fps": 30, "duration_s": 1.5, "loop": False,
             "interpolation": "linear", "joints": ["mid"],
             "weight_channels": [], "root_position_used": False})
        assert len(out) == 1
        assert out[0]["start_frame"] == 0 and out[0]["end_frame"] == 45
        assert out[0]["name"] == "sway"

    def test_a_nameless_value_survives_as_one_record(self):
        """clip_meta reports an unparseable attr as name-only; that must not
        crash the layout math either."""
        out = clipmath.normalized_records({"name": "junk"})
        assert out[0]["name"] == "junk" and out[0]["fps"] == 30
        assert out[0]["start_frame"] == 0 and out[0]["end_frame"] == 0
        assert clipmath.normalized_records(None) == []
        assert clipmath.normalized_records("not json at all") == []

    def test_records_come_back_in_timeline_order(self):
        out = clipmath.normalized_records(list(reversed(self._records())))
        assert [r["name"] for r in out] == ["idle", "walk"]

    def test_next_start_leaves_exactly_one_gap_frame(self):
        assert clipmath.next_start_frame([]) == 0
        # idle ends at 60, frame 61 is the gap, walk starts at 62
        assert clipmath.next_start_frame(self._records()[:1]) == 62
        assert clipmath.next_start_frame(self._records()) == 100

    def test_fps_conflict_names_the_fps_in_use_and_its_clips(self):
        assert clipmath.fps_conflict([], 24) is None
        assert clipmath.fps_conflict(self._records(), 30) is None
        message = clipmath.fps_conflict(self._records(), 24)
        assert "30" in message and "idle" in message and "walk" in message

    def test_channel_union_is_every_channel_any_clip_touches(self):
        union = clipmath.channel_union(self._records())
        assert union["joints"] == ["L_hip", "chest"]
        assert union["weight_channels"] == ["blink"]
        assert union["root_position_used"] is True
        empty = clipmath.channel_union([])
        assert empty == {"joints": [], "weight_channels": [],
                         "root_position_used": False}

    def test_drop_record_returns_the_record_and_the_rest(self):
        dropped, kept = clipmath.drop_record(self._records(), "idle")
        assert dropped["start_frame"] == 0 and dropped["end_frame"] == 60
        assert [r["name"] for r in kept] == ["walk"]
        missing, kept = clipmath.drop_record(self._records(), "nope")
        assert missing is None and len(kept) == 2

    def test_overlaps_and_duplicate_names_are_violations(self):
        assert clipmath.overlap_violations(self._records()) == []
        bad = self._records()
        bad[1]["start_frame"] = 60
        out = clipmath.overlap_violations(bad)
        assert any("overlap" in v and "idle" in v and "walk" in v
                   for v in out)
        dupe = self._records()
        dupe[1]["name"] = "idle"
        assert any("more than one take named 'idle'" in v
                   for v in clipmath.overlap_violations(dupe))

    def test_all_overlapping_pairs_are_reported(self):
        """With three or more records, every overlapping pair must be named,
        not just adjacent ones. A (0-100), B (50-60), C (70-200) overlaps
        both A-B and A-C."""
        records = [
            {"name": "A", "fps": 30, "start_frame": 0, "end_frame": 100,
             "duration_s": 3.33, "loop": False, "interpolation": "linear",
             "joints": [], "weight_channels": [], "root_position_used": False},
            {"name": "B", "fps": 30, "start_frame": 50, "end_frame": 60,
             "duration_s": 0.33, "loop": False, "interpolation": "linear",
             "joints": [], "weight_channels": [], "root_position_used": False},
            {"name": "C", "fps": 30, "start_frame": 70, "end_frame": 200,
             "duration_s": 4.33, "loop": False, "interpolation": "linear",
             "joints": [], "weight_channels": [], "root_position_used": False},
        ]
        out = clipmath.overlap_violations(records)
        # Should report both A-B and A-C overlaps
        ab_overlap = any("takes 'A' (0-100) and 'B' (50-60) overlap" in v
                         for v in out)
        ac_overlap = any("takes 'A' (0-100) and 'C' (70-200) overlap" in v
                         for v in out)
        assert ab_overlap, "A-B overlap not reported"
        assert ac_overlap, "A-C overlap not reported"
        # B-C should not overlap
        bc_overlap = any("'B'" in v and "'C'" in v and "overlap" in v
                         for v in out)
        assert not bc_overlap, "B-C should not overlap"
