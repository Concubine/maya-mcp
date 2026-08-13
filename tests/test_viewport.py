import math

from maya_plugin.handlers import viewport


def test_look_at_straight_down_z():
    # camera at +Z looking back at origin: no rotation
    assert viewport.look_at_rotation([0, 0, 10], [0, 0, 0]) == [0.0, 0.0, 0.0]


def test_look_at_from_above():
    rx, ry, rz = viewport.look_at_rotation([0, 10, 0], [0, 0, 0])
    assert math.isclose(rx, -90.0, abs_tol=1e-6)
    assert rz == 0.0


def test_look_at_three_quarter_matches_capture_convention():
    # 45 deg azimuth, ~28 elevation — the default persp orientation
    el, az = math.radians(27.938), math.radians(45.0)
    pos = [10 * math.cos(el) * math.sin(az), 10 * math.sin(el),
           10 * math.cos(el) * math.cos(az)]
    rx, ry, rz = viewport.look_at_rotation(pos, [0, 0, 0])
    assert math.isclose(rx, -27.938, abs_tol=1e-3)
    assert math.isclose(ry, 45.0, abs_tol=1e-3)


def test_look_at_degenerate_distance_raises():
    import pytest

    from maya_plugin.dispatcher import HandlerError

    with pytest.raises(HandlerError):
        viewport.look_at_rotation([1, 2, 3], [1, 2, 3])
