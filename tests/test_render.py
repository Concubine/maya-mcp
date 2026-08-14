"""render_scene tests: framing math, validation, and restore discipline.

The math is pure and fully tested here. The Maya-touching part is exercised
against a fake cmds - real pixels are the job of evals/render_scene_live.py,
because a green suite here proved nothing while capture_viewport was quietly
returning transparent images (redmine #584).
"""

import math

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import render


class TestFocalLength:
    def test_forty_degrees_on_mayas_default_aperture(self):
        # capture.py's placement math assumes a 40 deg vertical FOV and lets
        # viewFit correct any mismatch. There is no panel to fit here, so the
        # camera has to actually have that FOV: half-aperture / tan(fov/2).
        focal = render.focal_length_for_fov(40.0)
        assert focal == pytest.approx(12.4587 / math.tan(math.radians(20.0)), rel=1e-4)
        assert 34.0 < focal < 34.5

    def test_wider_fov_is_a_shorter_lens(self):
        assert render.focal_length_for_fov(60.0) < render.focal_length_for_fov(40.0)

    def test_scales_with_aperture(self):
        big = render.focal_length_for_fov(40.0, aperture_inches=1.962)
        assert big == pytest.approx(2 * render.focal_length_for_fov(40.0))


class TestValidation:
    def test_default_angle_is_a_single_three_quarter(self):
        assert render.resolve_angles(None) == ["three_quarter"]

    def test_rejects_unknown_angle(self):
        with pytest.raises(HandlerError):
            render.resolve_angles(["diagonal"])

    def test_rejects_more_than_four_angles(self):
        with pytest.raises(HandlerError):
            render.resolve_angles(["front", "side", "back", "top", "three_quarter"])

    def test_default_renderer_is_arnold(self):
        assert render.resolve_renderer(None) == "arnold"

    def test_hw2_maps_to_maya_hardware_2(self):
        assert render.RENDERER_TO_MAYA[render.resolve_renderer("hw2")] == "mayaHardware2"

    def test_rejects_unknown_renderer(self):
        with pytest.raises(HandlerError):
            render.resolve_renderer("redshift")

    def test_resolution_defaults_to_512_and_clamps(self):
        assert render.clamp_resolution(None) == 512
        assert render.clamp_resolution(4) == 64
        assert render.clamp_resolution(9000) == 2048
        assert render.clamp_resolution(True) == 512  # bool is not a resolution

    def test_samples_default_and_range(self):
        assert render.resolve_samples(None) == 3
        assert render.resolve_samples(6) == 6
        for bad in (0, 9, 2.5, True):
            with pytest.raises(HandlerError):
                render.resolve_samples(bad)


class TestFramePrefix:
    def test_prefix_is_unique_per_index(self):
        a = render.frame_prefix("abc123", 0, "front")
        b = render.frame_prefix("abc123", 1, "front")
        assert a != b
        assert "front" in a and a.startswith("mayaMcpRender_")

    def test_prefix_has_no_path_separators(self):
        prefix = render.frame_prefix("abc123", 0, "three_quarter")
        assert "/" not in prefix and "\\" not in prefix
