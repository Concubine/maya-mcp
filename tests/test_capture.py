"""capture_viewport tests: camera placement math, validation, marshaling.

The placement math is pure and fully tested here. The Maya-touching capture
internals are exercised via argument-marshaling with a stubbed capture step
(real pixels are covered by the manual M0 loop test inside Maya).
"""

import math

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import capture


CENTER_BBOX = ([-2.0, 0.0, -1.0], [2.0, 4.0, 1.0])  # center (0, 2, 0)


class TestCameraPlacement:
    def test_front_sits_on_positive_z_looking_straight(self):
        pos, rot = capture.camera_placement("front", *CENTER_BBOX)
        assert pos[0] == pytest.approx(0.0, abs=1e-9)
        assert pos[1] == pytest.approx(2.0, abs=1e-9)
        assert pos[2] > 1.0
        assert rot == pytest.approx((0.0, 0.0, 0.0))

    def test_side_sits_on_positive_x_with_yaw_90(self):
        pos, rot = capture.camera_placement("side", *CENTER_BBOX)
        assert pos[0] > 2.0
        assert pos[2] == pytest.approx(0.0, abs=1e-9)
        assert rot == pytest.approx((0.0, 90.0, 0.0))

    def test_back_sits_on_negative_z_with_yaw_180(self):
        pos, rot = capture.camera_placement("back", *CENTER_BBOX)
        assert pos[2] < -1.0
        assert rot == pytest.approx((0.0, 180.0, 0.0))

    def test_top_sits_above_pitched_straight_down(self):
        pos, rot = capture.camera_placement("top", *CENTER_BBOX)
        assert pos[1] > 4.0
        assert pos[0] == pytest.approx(0.0, abs=1e-6)
        assert rot[0] == pytest.approx(-90.0)

    def test_three_quarter_matches_maya_persp_convention(self):
        # Maya's default persp camera: rotation (-el, 45, 0) at a position whose
        # x == z and whose xz-distance/height ratio follows the elevation angle.
        pos, rot = capture.camera_placement("three_quarter", *CENTER_BBOX)
        assert rot[1] == pytest.approx(45.0)
        assert rot[0] < 0.0  # pitched down
        assert rot[2] == 0.0
        assert pos[0] == pytest.approx(pos[2])
        elevation = -rot[0]
        xz = math.hypot(pos[0], pos[2])
        assert math.degrees(math.atan2(pos[1] - 2.0, xz)) == pytest.approx(elevation)

    def test_distance_scales_with_bbox(self):
        small_pos, _ = capture.camera_placement("front", [-1, -1, -1], [1, 1, 1])
        big_pos, _ = capture.camera_placement("front", [-10, -10, -10], [10, 10, 10])
        assert big_pos[2] > small_pos[2] * 5

    def test_degenerate_bbox_still_finite_distance(self):
        pos, _ = capture.camera_placement("front", [0, 0, 0], [0, 0, 0])
        assert 0.5 < pos[2] < 100.0
        assert all(math.isfinite(c) for c in pos)


class TestValidation:
    def test_default_angles(self):
        assert capture.resolve_angles(None) == ["front", "side", "three_quarter"]

    def test_unknown_angle_is_handler_error_listing_valid_ones(self):
        with pytest.raises(HandlerError, match="dutch_tilt") as exc_info:
            capture.resolve_angles(["front", "dutch_tilt"])
        assert "three_quarter" in exc_info.value.hint

    def test_more_than_four_angles_rejected(self):
        with pytest.raises(HandlerError, match="4"):
            capture.resolve_angles(["front", "side", "back", "top", "three_quarter"])

    def test_current_is_a_valid_angle(self):
        assert capture.resolve_angles(["current"]) == ["current"]

    def test_resolution_clamped_to_sane_range(self):
        assert capture.clamp_resolution(None) == 768
        assert capture.clamp_resolution(32) == 64
        assert capture.clamp_resolution(10000) == 2048
        assert capture.clamp_resolution(512) == 512


class TestMarshaling:
    def test_capture_viewport_marshals_angles_resolution_and_wraps_results(
        self, monkeypatch
    ):
        calls = []

        def fake_capture(angle, shading, wireframe_overlay, buffer, isolate,
                         frame_all, resolution):
            calls.append((angle, shading, wireframe_overlay, buffer, isolate,
                          frame_all, resolution))
            return {"png_b64": "ZmFrZQ==", "camera_position": [0, 0, 10],
                    "camera_rotation": [0, 0, 0]}

        monkeypatch.setattr(capture, "_capture_one", fake_capture)
        result = capture.capture_viewport(
            {"angles": ["front", "top"], "resolution": 4096, "shading": "wireframe",
             "wireframe_overlay": False, "isolate": ["|golem"], "frame_all": False}
        )
        assert [c[0] for c in calls] == ["front", "top"]
        assert all(c[1] == "wireframe" for c in calls)
        assert all(c[2] is False for c in calls)
        assert all(c[4] == ["|golem"] for c in calls)
        assert all(c[5] is False for c in calls)
        assert all(c[6] == 2048 for c in calls)  # clamped
        assert [img["angle"] for img in result["images"]] == ["front", "top"]
        assert all(img["png_b64"] == "ZmFrZQ==" for img in result["images"])
        assert len(result["camera_positions"]) == 2

    def test_invalid_shading_rejected_before_any_capture(self, monkeypatch):
        monkeypatch.setattr(
            capture, "_capture_one",
            lambda *a, **k: pytest.fail("capture ran despite invalid shading"),
        )
        with pytest.raises(HandlerError, match="shading"):
            capture.capture_viewport({"shading": "raytraced"})

    def test_invalid_buffer_rejected(self, monkeypatch):
        monkeypatch.setattr(
            capture, "_capture_one",
            lambda *a, **k: pytest.fail("capture ran despite invalid buffer"),
        )
        with pytest.raises(HandlerError, match="buffer"):
            capture.capture_viewport({"buffer": "zdepth"})
