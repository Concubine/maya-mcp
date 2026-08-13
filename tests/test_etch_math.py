import math

from maya_plugin.handlers import etch

BBOX = ([-0.5, -1.0, 0.0], [0.5, 1.0, 0.25])  # raw glyph: 1 wide, 2 tall, 0.25 thick


def test_facing_plus_z_no_rotation():
    result = etch.face_frame_transform(
        face_center=[0, 3.4, 1.3], face_normal=[0, 0, 1],
        glyph_bbox_min=BBOX[0], glyph_bbox_max=BBOX[1],
        width=0.6, depth=0.1,
    )
    assert result["rotate"] == [0.0, 0.0, 0.0]
    sx, sy, sz = result["scale"]
    assert math.isclose(sx, 0.6, rel_tol=1e-6)          # 1.0 wide -> 0.6
    assert math.isclose(sy, 0.6, rel_tol=1e-6)          # uniform in-plane
    assert math.isclose(sz, 0.8, rel_tol=1e-6)          # 0.25 thick -> 2*depth
    assert result["translate"] == [0.0, 3.4, 1.3]


def test_tilted_plate_normal_matches_brow_math():
    # the golem brow plate: rx -18 => n = (0, sin18, cos18)
    n = [0.0, math.sin(math.radians(18)), math.cos(math.radians(18))]
    result = etch.face_frame_transform(
        face_center=[0, 3.46, 1.32], face_normal=n,
        glyph_bbox_min=BBOX[0], glyph_bbox_max=BBOX[1],
        width=1.0, depth=0.1,
    )
    assert math.isclose(result["rotate"][0], -18.0, abs_tol=1e-3)
    assert math.isclose(result["rotate"][1], 0.0, abs_tol=1e-3)


def test_normal_is_normalized_before_use():
    a = etch.face_frame_transform([0, 0, 0], [0, 0, 1], *BBOX, width=1, depth=0.1)
    b = etch.face_frame_transform([0, 0, 0], [0, 0, 7], *BBOX, width=1, depth=0.1)
    assert a == b


def test_degenerate_glyph_bbox_raises():
    import pytest

    from maya_plugin.dispatcher import HandlerError

    with pytest.raises(HandlerError):
        etch.face_frame_transform(
            [0, 0, 0], [0, 0, 1], [0, 0, 0], [0, 0, 0], width=1, depth=0.1
        )
