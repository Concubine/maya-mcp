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
