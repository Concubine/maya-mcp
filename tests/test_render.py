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


class FakeCmds:
    """Enough maya.cmds to drive render_scene's restore discipline.

    Records every mutation so the tests can assert the scene came back as it
    was - the house rule for perception tools (capture._PanelState).
    """

    def __init__(self, lights=(), geometry=("|ball", "|floor")):
        self.attrs = {
            "defaultRenderGlobals.imageFormat": 7,
            "defaultRenderGlobals.imageFilePrefix": "",
            "defaultRenderGlobals.currentRenderer": "mayaSoftware",
            "defaultResolution.width": 960,
            "defaultResolution.height": 540,
            "defaultResolution.deviceAspectRatio": 1.777,
            "defaultArnoldRenderOptions.AASamples": 1,
        }
        self.created = []
        self.deleted = []
        self.hidden = []
        self.written = []
        self._lights = list(lights)
        self._geometry = list(geometry)
        self.visibility = {name: True for name in self._geometry}

    # --- queries
    def ls(self, *args, **kwargs):
        if kwargs.get("lights"):
            return list(self._lights)
        if kwargs.get("geometry"):
            return list(self._geometry)
        if args:
            return [args[0]]
        return []

    def objExists(self, name):
        return name in self._geometry or name in self.created

    def exactWorldBoundingBox(self, *targets):
        return [-1.0, -1.0, -1.0, 1.0, 1.0, 1.0]

    def getAttr(self, attr):
        if attr.endswith(".translate") or attr.endswith(".rotate"):
            return [(0.0, 0.0, 0.0)]
        return self.attrs.get(attr, 0)

    def renderer(self, *args, **kwargs):
        return ["mayaSoftware", "mayaHardware2", "arnold"]

    def undoInfo(self, **kwargs):
        return True

    # --- mutations
    def setAttr(self, attr, *values, **kwargs):
        self.attrs[attr] = values[0] if len(values) == 1 else list(values)

    def camera(self, *args, **kwargs):
        self.created.append("camera1")
        return ["camera1", "cameraShape1"]

    def rename(self, old, new):
        self.created.append(new)
        return new

    def directionalLight(self, **kwargs):
        name = "mayaMcpTempKeyShape"
        self.created.append(name)
        self._lights.append(name)
        return name

    def listRelatives(self, name, **kwargs):
        return ["mayaMcpTempKey"]

    def xform(self, *args, **kwargs):
        return None

    def hide(self, name):
        self.hidden.append(name)
        self.visibility[name] = False

    def showHidden(self, name):
        self.visibility[name] = True

    def delete(self, name):
        self.deleted.append(name)


def _stub_render_frame(tmp_path, fake):
    """Stand in for cmds.render: writes a small lit PNG, records the call."""
    from PIL import Image as PILImage

    def render_frame(cmds, camera, prefix, renderer, resolution, samples):
        path = tmp_path / (prefix + ".png")
        PILImage.new("RGB", (8, 8), (120, 30, 30)).save(path)
        fake.written.append({"prefix": prefix, "renderer": renderer,
                             "resolution": resolution, "samples": samples})
        return str(path)

    return render_frame


@pytest.fixture
def fake_maya(monkeypatch, tmp_path):
    fake = FakeCmds(lights=["|keyLightShape"])
    monkeypatch.setattr(render, "_cmds", lambda: fake)
    monkeypatch.setattr(render, "_render_frame", _stub_render_frame(tmp_path, fake))
    return fake


class TestRenderScene:
    def test_returns_one_image_per_angle(self, fake_maya):
        out = render.render_scene({"angles": ["front", "side"]})
        assert [i["angle"] for i in out["images"]] == ["front", "side"]
        assert all(i["png_b64"] for i in out["images"])
        assert out["renderer"] == "arnold"
        assert len(out["camera_positions"]) == 2

    def test_every_frame_gets_its_own_prefix(self, fake_maya):
        render.render_scene({"angles": ["front", "front"]})
        prefixes = [w["prefix"] for w in fake_maya.written]
        assert len(set(prefixes)) == 2, "cmds.render overwrites a fixed path"

    def test_render_globals_are_restored(self, fake_maya):
        # Including currentRenderer: the call has to switch the scene's renderer
        # to render at all, and must switch it back.
        before = dict(fake_maya.attrs)
        render.render_scene({"angles": ["front"], "resolution": 256})
        after = {key: fake_maya.attrs[key] for key in before}
        assert after == before

    def test_temp_camera_is_deleted(self, fake_maya):
        render.render_scene({"angles": ["front"]})
        assert any("mayaMcpRenderCam" in name for name in fake_maya.deleted)

    def test_isolate_hides_non_targets_and_restores_them(self, fake_maya):
        render.render_scene({"angles": ["front"], "isolate": ["|ball"]})
        assert "|floor" in fake_maya.hidden
        assert "|ball" not in fake_maya.hidden
        assert all(fake_maya.visibility.values()), "visibility must be restored"

    def test_isolate_rejects_a_missing_object(self, fake_maya):
        with pytest.raises(HandlerError):
            render.render_scene({"angles": ["front"], "isolate": ["|nope"]})

    def test_fallback_light_added_when_dark_and_removed_after(
        self, monkeypatch, tmp_path
    ):
        fake = FakeCmds(lights=[])
        monkeypatch.setattr(render, "_cmds", lambda: fake)
        monkeypatch.setattr(render, "_render_frame", _stub_render_frame(tmp_path, fake))
        out = render.render_scene({"angles": ["front"]})
        assert out["fallback_light"] is True
        assert any("mayaMcpTempKey" in name for name in fake.deleted)

    def test_no_fallback_light_when_the_scene_has_one(self, fake_maya):
        out = render.render_scene({"angles": ["front"]})
        assert out["fallback_light"] is False

    def test_fallback_light_can_be_declined(self, monkeypatch, tmp_path):
        fake = FakeCmds(lights=[])
        monkeypatch.setattr(render, "_cmds", lambda: fake)
        monkeypatch.setattr(render, "_render_frame", _stub_render_frame(tmp_path, fake))
        out = render.render_scene({"angles": ["front"], "fallback_light": False})
        assert out["fallback_light"] is False
        assert not any("mayaMcpTempKey" in name for name in fake.created)

    def test_unknown_renderer_is_rejected_before_touching_the_scene(self, fake_maya):
        with pytest.raises(HandlerError):
            render.render_scene({"renderer": "redshift"})
        assert fake_maya.created == []

    def test_missing_arnold_is_an_error_not_a_silent_substitution(
        self, monkeypatch, fake_maya
    ):
        monkeypatch.setattr(
            fake_maya, "renderer", lambda *a, **k: ["mayaSoftware", "mayaHardware2"]
        )
        with pytest.raises(HandlerError) as excinfo:
            render.render_scene({"angles": ["front"]})
        assert "hw2" in str(excinfo.value.hint or "")

    def test_samples_and_resolution_reach_the_render_step(self, fake_maya):
        render.render_scene({"angles": ["front"], "samples": 6, "resolution": 256})
        assert fake_maya.written[0]["samples"] == 6
        assert fake_maya.written[0]["resolution"] == 256

    def test_hw2_maps_through_to_the_maya_renderer_name(self, fake_maya):
        out = render.render_scene({"angles": ["front"], "renderer": "hw2"})
        assert out["renderer"] == "hw2"
        assert fake_maya.written[0]["renderer"] == "mayaHardware2"
