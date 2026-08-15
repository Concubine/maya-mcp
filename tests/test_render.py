"""render_scene tests: framing math, validation, and restore discipline.

The math is pure and fully tested here. The Maya-touching part is exercised
against a fake cmds - real pixels are the job of evals/render_scene_live.py,
because a green suite here proved nothing while capture_viewport was quietly
returning transparent images (redmine #584).
"""

import math

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import capture, render


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

    def __init__(self, lights=(), geometry=("|ball|ballShape", "|floor|floorShape")):
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
        self.loaded_plugins = []
        self._renderers = ["mayaSoftware", "mayaHardware2", "arnold"]
        # Arnold registers its renderer through a DEFERRED callback, so on a
        # real Maya the renderer list can still omit it right after a
        # successful load. Set this to reproduce that window.
        self.renderer_list_lags = False
        # World rotation reported for a light transform, keyed by name.
        self.light_yaw_query = {}
        self.yaw_history = []
        self._lights = list(lights)
        # Geometry is SHAPES, as cmds.ls(geometry=True) returns them - the
        # distinction that made isolate hide its own subject (redmine #584).
        self._geometry = list(geometry)
        self._transforms = sorted({s.rsplit("|", 1)[0] for s in self._geometry})
        self.visibility = {name: True for name in self._geometry}

    # --- queries
    def ls(self, *args, **kwargs):
        if kwargs.get("lights"):
            return list(self._lights)
        if kwargs.get("type") == "light":
            return list(self._lights)
        if kwargs.get("geometry"):
            # Real cmds.ls returns SHORT names unless long=True is asked for.
            # Reproducing that is the whole point: the live gate found isolate
            # hiding its own subject because "gemShape" never matches "|gem".
            if kwargs.get("long"):
                return list(self._geometry)
            return [name.rsplit("|", 1)[-1] for name in self._geometry]
        if args:
            name = args[0]
            if kwargs.get("long"):
                return [name if name.startswith("|") else "|" + name]
            return [name]
        return []

    def objExists(self, name):
        return name in self._transforms or name in self._geometry or name in self.created

    def exactWorldBoundingBox(self, *targets):
        return [-1.0, -1.0, -1.0, 1.0, 1.0, 1.0]

    def getAttr(self, attr):
        if attr.endswith(".translate") or attr.endswith(".rotate"):
            return [(0.0, 0.0, 0.0)]
        if attr.endswith(".visibility"):
            return self.visibility.get(attr[: -len(".visibility")], True)
        return self.attrs.get(attr, 0)

    def renderer(self, *args, **kwargs):
        return list(self._renderers)

    def loadPlugin(self, name, **kwargs):
        self.loaded_plugins.append(name)
        if name == "mtoa" and not self.renderer_list_lags:
            if "arnold" not in self._renderers:
                self._renderers.append("arnold")
        return [name]

    def pluginInfo(self, name, **kwargs):
        if kwargs.get("loaded"):
            return name in self.loaded_plugins
        return None

    def undoInfo(self, **kwargs):
        return True

    # --- mutations
    def setAttr(self, attr, *values, **kwargs):
        self.attrs[attr] = values[0] if len(values) == 1 else list(values)
        if attr.endswith(".rotateY"):
            self.yaw_history.append(values[0])

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
        if kwargs.get("parent"):
            if "Shape" in name and name.startswith("|"):
                return [name.rsplit("|", 1)[0]]
            return ["mayaMcpTempKey"]
        if kwargs.get("allDescendents"):
            return [s for s in self._geometry if s.startswith(name + "|")]
        return []

    def xform(self, *args, **kwargs):
        if kwargs.get("query") and kwargs.get("rotation"):
            return list(self.light_yaw_query.get(args[0], (0.0, 0.0, 0.0)))
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
        assert "|floor|floorShape" in fake_maya.hidden
        assert all(fake_maya.visibility.values()), "visibility must be restored"

    def test_isolate_leaves_already_hidden_objects_hidden(self, monkeypatch, tmp_path):
        # Restoring visibility on something WE did not hide would show the user
        # an object they deliberately hid - a perception tool editing the scene.
        fake = FakeCmds(lights=["|keyLightShape"])
        fake.visibility["|floor|floorShape"] = False
        monkeypatch.setattr(render, "_cmds", lambda: fake)
        monkeypatch.setattr(render, "_render_frame", _stub_render_frame(tmp_path, fake))
        render.render_scene({"angles": ["front"], "isolate": ["|ball"]})
        assert fake.visibility["|floor|floorShape"] is False
        assert "|floor|floorShape" not in fake.hidden

    def test_isolate_does_not_hide_its_own_subject(self, fake_maya):
        # cmds.ls(geometry=True) returns SHAPES, and a transform name never
        # matches one: the live gate caught this hiding the very gem it was
        # asked to render, and returning a black frame (redmine #584).
        render.render_scene({"angles": ["front"], "isolate": ["|ball"]})
        assert "|ball|ballShape" not in fake_maya.hidden

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
        monkeypatch.setattr(
            fake_maya, "loadPlugin",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("mtoa not installed")),
        )
        with pytest.raises(HandlerError) as excinfo:
            render.render_scene({"angles": ["front"]})
        assert "hw2" in str(excinfo.value.hint or "")

    def test_mtoa_is_loaded_when_arnold_is_not_listed_yet(self, monkeypatch, tmp_path):
        # A cold Maya lists only mayaSoftware and mayaHardware2 until something
        # loads mtoa. Making the caller do that to use the DEFAULT renderer is
        # a tool defect; the live gate hit it on a freshly launched Maya.
        fake = FakeCmds(lights=["|keyLightShape"])
        fake._renderers = ["mayaSoftware", "mayaHardware2"]
        monkeypatch.setattr(render, "_cmds", lambda: fake)
        monkeypatch.setattr(render, "_render_frame", _stub_render_frame(tmp_path, fake))
        out = render.render_scene({"angles": ["front"]})
        assert fake.loaded_plugins == ["mtoa"]
        assert out["renderer"] == "arnold"

    def test_mtoa_is_not_loaded_for_an_hw2_render(self, fake_maya):
        render.render_scene({"angles": ["front"], "renderer": "hw2"})
        assert fake_maya.loaded_plugins == []

    def test_a_loaded_mtoa_counts_even_while_the_renderer_list_lags(
        self, monkeypatch, tmp_path
    ):
        # Arnold registers its renderer through a deferred callback, so for a
        # moment after a SUCCESSFUL load the renderer list still omits it.
        # Trusting that list rejected arnold on a just-started Maya; the
        # authoritative answer is whether the plugin is loaded.
        fake = FakeCmds(lights=["|keyLightShape"])
        fake._renderers = ["mayaSoftware", "mayaHardware2"]
        fake.renderer_list_lags = True
        monkeypatch.setattr(render, "_cmds", lambda: fake)
        monkeypatch.setattr(render, "_render_frame", _stub_render_frame(tmp_path, fake))
        out = render.render_scene({"angles": ["front"]})
        assert fake.loaded_plugins == ["mtoa"]
        assert out["renderer"] == "arnold"

    def test_target_frames_without_hiding_anything(self, fake_maya):
        # The #585 blocker: framing a gem for a close-up must not hide the
        # backdrop it needs behind it to refract.
        render.render_scene({"angles": ["front"], "target": ["|ball"]})
        assert fake_maya.hidden == []

    def test_isolate_still_frames_when_no_target_is_given(self, fake_maya):
        render.render_scene({"angles": ["front"], "isolate": ["|ball"]})
        assert "|floor|floorShape" in fake_maya.hidden

    def test_target_and_isolate_can_disagree(self, fake_maya):
        # Frame the ball, hide only the floor: both questions answered
        # independently, which is the point of the split.
        render.render_scene({
            "angles": ["front"], "target": ["|ball"], "isolate": ["|ball"]})
        assert "|floor|floorShape" in fake_maya.hidden

    def test_target_rejects_a_missing_object(self, fake_maya):
        with pytest.raises(HandlerError):
            render.render_scene({"angles": ["front"], "target": ["|nope"]})

    def test_zoom_moves_the_camera_closer_without_changing_the_angle(self):
        bbox_min, bbox_max = [-1.0, -1.0, -1.0], [1.0, 1.0, 1.0]
        position, _ = capture.camera_placement("front", bbox_min, bbox_max)
        closer = render.zoomed_position(position, bbox_min, bbox_max, 2.0)
        assert closer[2] == pytest.approx(position[2] / 2.0)
        assert closer[0] == pytest.approx(position[0])
        assert closer[1] == pytest.approx(position[1])

    def test_zoom_validation(self):
        assert render.resolve_zoom(None) == 1.0
        for bad in (0.0, 0.1, 20.0, "2x", True):
            with pytest.raises(HandlerError):
                render.resolve_zoom(bad)

    def test_the_rig_follows_the_camera_and_is_put_back(self, monkeypatch, tmp_path):
        # setup_lighting builds a WORLD-locked rig while render_scene orbits, so
        # a side render came back nearly black: key at yaw +30, camera at 90.
        fake = FakeCmds(lights=["|mcpLight_key|mcpLight_keyShape"])
        fake.light_yaw_query["|mcpLight_key"] = (-35.0, 30.0, 0.0)
        monkeypatch.setattr(render, "_cmds", lambda: fake)
        monkeypatch.setattr(render, "_render_frame", _stub_render_frame(tmp_path, fake))
        out = render.render_scene({"angles": ["side"]})
        assert out["relit_lights"] == 1
        # side is azimuth 90: the key swings to 120 for the render...
        assert fake.yaw_history == [120.0, 30.0]
        # ...and 30 is where it ends up, because the rig is the user's scene.
        assert fake.attrs["|mcpLight_key.rotateY"] == 30.0

    def test_a_user_authored_rig_is_never_touched(self, monkeypatch, tmp_path):
        fake = FakeCmds(lights=["|myKeyLight|myKeyLightShape"])
        fake.light_yaw_query["|myKeyLight"] = (-35.0, 30.0, 0.0)
        monkeypatch.setattr(render, "_cmds", lambda: fake)
        monkeypatch.setattr(render, "_render_frame", _stub_render_frame(tmp_path, fake))
        out = render.render_scene({"angles": ["side"]})
        assert out["relit_lights"] == 0
        assert fake.yaw_history == []

    def test_relight_can_be_declined(self, monkeypatch, tmp_path):
        fake = FakeCmds(lights=["|mcpLight_key|mcpLight_keyShape"])
        fake.light_yaw_query["|mcpLight_key"] = (-35.0, 30.0, 0.0)
        monkeypatch.setattr(render, "_cmds", lambda: fake)
        monkeypatch.setattr(render, "_render_frame", _stub_render_frame(tmp_path, fake))
        out = render.render_scene({"angles": ["side"], "relight": False})
        assert out["relit_lights"] == 0
        assert fake.yaw_history == []

    def test_samples_and_resolution_reach_the_render_step(self, fake_maya):
        render.render_scene({"angles": ["front"], "samples": 6, "resolution": 256})
        assert fake_maya.written[0]["samples"] == 6
        assert fake_maya.written[0]["resolution"] == 256

    def test_hw2_maps_through_to_the_maya_renderer_name(self, fake_maya):
        out = render.render_scene({"angles": ["front"], "renderer": "hw2"})
        assert out["renderer"] == "hw2"
        assert fake_maya.written[0]["renderer"] == "mayaHardware2"


class TestRenderSheet:
    """One frame per subject in ONE call - the kit contact sheet was 41 of them.

    Everything outside the frame loop is setup: resolving the renderer,
    snapshotting the user's render globals, building a camera, hiding the scene.
    These assert that the setup happens once and the loop is just frames.
    """

    def test_one_frame_per_subject_labelled_by_subject(self, fake_maya):
        out = render.render_sheet({"subjects": ["|ball", "|floor"]})
        assert [i["label"] for i in out["images"]] == ["|ball", "|floor"]
        assert all(i["png_b64"] for i in out["images"])

    def test_the_camera_is_built_once_for_the_whole_sheet(self, fake_maya):
        render.render_sheet({"subjects": ["|ball", "|floor"]})
        cameras = [n for n in fake_maya.created if "RenderCam" in n]
        assert len(cameras) == 1, "a camera per cell is setup, not picture"

    def test_each_cell_is_isolated_to_its_own_subject(self, fake_maya):
        render.render_sheet({"subjects": ["|ball", "|floor"]})
        # Each subject's cell hid the OTHER one; both are visible again at the end.
        assert "|floor|floorShape" in fake_maya.hidden
        assert "|ball|ballShape" in fake_maya.hidden
        assert all(fake_maya.visibility.values()), "visibility must be restored"

    def test_isolation_can_be_declined_for_subjects_that_need_the_room(self, fake_maya):
        """Hiding the surroundings also removes what a transmissive material
        refracts - the #585 lesson, kept reachable here."""
        render.render_sheet({"subjects": ["|ball"], "isolate": False})
        assert fake_maya.hidden == []

    def test_every_cell_gets_its_own_render_prefix(self, fake_maya):
        render.render_sheet({"subjects": ["|ball", "|floor"]})
        prefixes = [w["prefix"] for w in fake_maya.written]
        assert len(set(prefixes)) == 2, "cmds.render overwrites a fixed path"

    def test_render_globals_are_restored_after_a_whole_sheet(self, fake_maya):
        before = dict(fake_maya.attrs)
        render.render_sheet({"subjects": ["|ball", "|floor"], "resolution": 256})
        assert {k: fake_maya.attrs[k] for k in before} == before

    def test_a_bad_name_is_caught_before_any_frame_is_rendered(self, fake_maya):
        """A sheet that dies on cell 30 has spent thirty frames' worth of
        seconds to report a typo."""
        with pytest.raises(HandlerError) as exc:
            render.render_sheet({"subjects": ["|ball", "|nonexistent"]})
        assert "nonexistent" in str(exc.value)
        assert fake_maya.written == []

    def test_empty_subjects_points_at_render_scene(self, fake_maya):
        with pytest.raises(HandlerError) as exc:
            render.render_sheet({"subjects": []})
        assert "render_scene" in exc.value.hint

    def test_too_many_subjects_is_refused(self, fake_maya):
        with pytest.raises(HandlerError) as exc:
            render.render_sheet(
                {"subjects": ["|ball"] * (render.MAX_SHEET_SUBJECTS + 1)}
            )
        assert "cap" in str(exc.value)

    def test_an_unknown_angle_is_refused(self, fake_maya):
        with pytest.raises(HandlerError):
            render.render_sheet({"subjects": ["|ball"], "angle": "diagonal"})

    def test_a_sheet_does_not_pollute_the_undo_queue(self):
        assert render.render_sheet.no_undo_chunk is True


class FakeArnoldCmds(FakeCmds):
    """FakeCmds plus the mtoa-side surface _render_frame touches.

    Seeded with the scene as found on 9877: the driver on Use Output Transform
    with output transforms DISABLED, which is the configuration in which mode 2
    silently degrades to Raw (redmine #615).
    """

    def __init__(self, tmp_path, output_transforms=None, arnold_render_raises=False):
        super().__init__(lights=["|keyLightShape"])
        self.tmp_path = tmp_path
        self.attrs["defaultArnoldDriver.colorManagement"] = 0
        self.attrs["defaultArnoldDriver.aiTranslator"] = "exr"
        self.output_transforms = (
            ["Un-tone-mapped (sRGB)", "ACES 1.0 SDR-video (sRGB)"]
            if output_transforms is None
            else list(output_transforms)
        )
        self.cm_prefs = {
            "outputTransformEnabled": False,
            "outputTransformName": "ACES 1.0 SDR-video (sRGB)",
            "viewTransformName": "ACES 1.0 SDR-video (sRGB)",
        }
        self.arnold_render_raises = arnold_render_raises
        self.arnold_renders = []
        self.legacy_renders = []
        self.during = []  # colour-management state at the moment of rendering

    def colorManagementPrefs(self, *args, **kwargs):
        if kwargs.get("query"):
            if kwargs.get("outputTransformNames"):
                return list(self.output_transforms)
            for key in ("outputTransformEnabled", "outputTransformName",
                        "viewTransformName"):
                if kwargs.get(key):
                    return self.cm_prefs[key]
            return None
        for key in ("outputTransformEnabled", "outputTransformName",
                    "viewTransformName"):
            if key in kwargs:
                self.cm_prefs[key] = kwargs[key]
        return None

    def renderSettings(self, **kwargs):
        prefix = self.attrs["defaultRenderGlobals.imageFilePrefix"]
        return [str(self.tmp_path / (prefix + ".png"))]

    def _snapshot(self):
        return {
            "colorManagement": self.attrs["defaultArnoldDriver.colorManagement"],
            "aiTranslator": self.attrs["defaultArnoldDriver.aiTranslator"],
            "outputTransformEnabled": self.cm_prefs["outputTransformEnabled"],
            "outputTransformName": self.cm_prefs["outputTransformName"],
        }

    def arnoldRender(self, **kwargs):
        self.during.append(self._snapshot())
        if self.arnold_render_raises:
            raise RuntimeError("arnoldRender exploded")
        self.arnold_renders.append(kwargs)
        self._write_image(self.renderSettings()[0])

    def render(self, camera, **kwargs):
        self.during.append(self._snapshot())
        self.legacy_renders.append({"camera": camera, **kwargs})
        prefix = self.attrs["defaultRenderGlobals.imageFilePrefix"]
        path = str(self.tmp_path / (prefix + "_legacy.png"))
        self._write_image(path)
        return path

    @staticmethod
    def _write_image(path):
        from PIL import Image as PILImage

        PILImage.new("RGB", (8, 8), (188, 188, 188)).save(path)


@pytest.fixture
def arnold_cmds(tmp_path):
    return FakeArnoldCmds(tmp_path)


def _frame(fake, renderer="arnold"):
    return render._render_frame(fake, "|cam|camShape", "shot0", renderer, 256, 3)


class TestDisplayTransform:
    """#615: every frame this tool returned was raw linear, ~2.2 gamma dark.

    cmds.render never consults the Arnold driver, so no colour-management
    setting could reach it. cmds.arnoldRender does - measured live, a linear-0.5
    plane goes 127 -> 188 - which is why the arnold branch changes render call.
    """

    def test_arnold_frames_go_through_arnold_render(self, arnold_cmds):
        _frame(arnold_cmds)
        assert len(arnold_cmds.arnold_renders) == 1
        assert arnold_cmds.legacy_renders == []

    def test_the_frame_is_rendered_with_the_output_transform_applied(self, arnold_cmds):
        _frame(arnold_cmds)
        during = arnold_cmds.during[0]
        assert during["colorManagement"] == 2  # Use Output Transform
        assert during["outputTransformEnabled"] is True
        assert during["outputTransformName"] == render.DISPLAY_TRANSFORM

    def test_it_writes_png_rather_than_the_drivers_exr(self, arnold_cmds):
        # arnoldRender obeys the DRIVER's translator, not imageFormat: left
        # alone it writes .exr and the handler reads a file that is not a PNG.
        _frame(arnold_cmds)
        assert arnold_cmds.during[0]["aiTranslator"] == "png"

    def test_it_returns_the_file_arnold_actually_wrote(self, arnold_cmds, tmp_path):
        assert _frame(arnold_cmds) == str(tmp_path / "shot0.png")

    def test_it_restores_the_driver_afterwards(self, arnold_cmds):
        _frame(arnold_cmds)
        assert arnold_cmds.attrs["defaultArnoldDriver.colorManagement"] == 0
        assert arnold_cmds.attrs["defaultArnoldDriver.aiTranslator"] == "exr"

    def test_it_restores_the_colour_management_prefs_afterwards(self, arnold_cmds):
        _frame(arnold_cmds)
        assert arnold_cmds.cm_prefs["outputTransformEnabled"] is False
        assert arnold_cmds.cm_prefs["outputTransformName"] == "ACES 1.0 SDR-video (sRGB)"

    def test_it_restores_them_even_when_the_render_fails(self, tmp_path):
        fake = FakeArnoldCmds(tmp_path, arnold_render_raises=True)
        _frame(fake)
        assert fake.attrs["defaultArnoldDriver.colorManagement"] == 0
        assert fake.cm_prefs["outputTransformEnabled"] is False

    def test_a_failed_arnold_render_falls_back_to_cmds_render(self, tmp_path):
        # A dark frame beats no frame: the caller asked to see something.
        fake = FakeArnoldCmds(tmp_path, arnold_render_raises=True)
        assert _frame(fake).endswith("_legacy.png")

    def test_it_uses_the_view_transform_when_no_output_one_is_available(self, tmp_path):
        # Another OCIO config need not carry that name. Mode 1 reads the
        # scene's VIEW transform, which is still a display transform.
        fake = FakeArnoldCmds(tmp_path, output_transforms=["Rec.709"])
        _frame(fake)
        assert fake.during[0]["colorManagement"] == 1

    def test_hw2_still_goes_through_cmds_render(self, arnold_cmds):
        _frame(arnold_cmds, renderer="mayaHardware2")
        assert arnold_cmds.arnold_renders == []
        assert len(arnold_cmds.legacy_renders) == 1
