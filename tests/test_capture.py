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


class FakeLensCmds:
    """A camera whose apertures are whatever the test says they are.

    The point of apply_framing_fov is that it READS the film back rather
    than assuming one, so the fake has to be able to disagree with Maya's
    defaults - that is the whole assertion.

    #799: it now holds a node REGISTRY rather than a bare plug dict.
    `listRelatives` used to answer "camShape" for any string handed to it,
    so `apply_framing_fov(cmds, "a camera nobody made")` looked healthy
    here and raises "No object matches name" in Maya. Writes to a
    connection-fed plug refuse too - an animated or expression-driven
    focalLength is a plug this helper writes unguarded.
    """

    def __init__(self, h_aperture=1.4173, v_aperture=0.9449):
        self.shape_of = {"cam": "camShape"}
        self.deleted = []
        # plug -> the source feeding it. A connected (or locked) plug
        # refuses a static setAttr in real Maya (#799 contract 2).
        self.driven_plugs = {}
        self.attrs = {
            "camShape.horizontalFilmAperture": h_aperture,
            "camShape.verticalFilmAperture": v_aperture,
            "camShape.focalLength": 35.0,
            "camShape.filmFit": 0,
        }
        self.sets = []

    def _require(self, node):
        """Maya's answer for a node that was deleted or never made."""
        if node in self.deleted or (
            node not in self.shape_of and node not in self.shape_of.values()
        ):
            raise RuntimeError("No object matches name: %s" % node)
        return node

    def _require_plug(self, plug):
        node, _, _attr = plug.rpartition(".")
        self._require(node)
        if plug not in self.attrs:
            raise RuntimeError("No object matches name: %s" % plug)
        return plug

    def listRelatives(self, node, shapes=False, fullPath=False, **kw):
        self._require(node)
        if not shapes:
            return None
        shape = self.shape_of.get(node)
        return [shape] if shape else None

    def getAttr(self, plug):
        return self.attrs[self._require_plug(plug)]

    def setAttr(self, plug, *values, **kw):
        self._require_plug(plug)
        source = self.driven_plugs.get(plug)
        if source:
            raise RuntimeError(
                "setAttr: The attribute '%s' is locked or connected and "
                "cannot be modified (%s feeds it)" % (plug, source))
        self.attrs[plug] = values[0]
        self.sets.append((plug, values[0]))

    def delete(self, *nodes):
        self.deleted.extend(nodes)


class TestFramingFov:
    """#772: the placement math solves for _FOV_DEG, so the camera it shoots
    through has to actually HAVE that field of view.

    Measured on Maya 2027: cmds.camera() builds a 35 mm lens on a 1.4173 in
    x 0.9449 in back with filmFit=1 (Horizontal), and every render here is
    square (deviceAspectRatio 1.0), so the HORIZONTAL aperture governs both
    axes. A subject was measured filling 61% of the frame where 84% was
    intended - about 72% of its intended linear size.
    """

    def test_focal_length_puts_the_horizontal_fov_on_the_constant(self):
        focal = capture.focal_length_for_fov(
            capture._FOV_DEG, capture.MAYA_HORIZONTAL_APERTURE_IN)
        back_out = 2 * math.degrees(math.atan(
            (capture.MAYA_HORIZONTAL_APERTURE_IN * 25.4 / 2) / focal))
        assert back_out == pytest.approx(capture._FOV_DEG, rel=1e-9)

    def test_a_wider_fov_is_a_shorter_lens(self):
        assert (capture.focal_length_for_fov(60.0, 1.4173)
                < capture.focal_length_for_fov(40.0, 1.4173))

    def test_focal_scales_with_the_film_back(self):
        assert (capture.focal_length_for_fov(40.0, 2.8346)
                == pytest.approx(2 * capture.focal_length_for_fov(40.0, 1.4173)))

    def test_it_reads_the_aperture_off_the_camera(self):
        """A hardcoded aperture is what made the previous attempt at this
        miss: render.py assumed 0.981 in when the camera measures 0.9449."""
        odd = FakeLensCmds(h_aperture=2.0)
        capture.apply_framing_fov(odd, "cam")
        assert odd.attrs["camShape.focalLength"] == pytest.approx(
            capture.focal_length_for_fov(capture._FOV_DEG, 2.0))
        assert odd.attrs["camShape.focalLength"] != pytest.approx(
            capture.focal_length_for_fov(capture._FOV_DEG,
                                         capture.MAYA_HORIZONTAL_APERTURE_IN))

    def test_it_refuses_a_camera_that_does_not_exist(self):
        """#799 contract 1: the fake used to answer "camShape" for any
        string, so this helper looked healthy against a name nobody made.
        Maya raises "No object matches name" from listRelatives instead."""
        fake = FakeLensCmds()
        fake.delete("cam")
        with pytest.raises(RuntimeError, match="No object matches name"):
            capture.apply_framing_fov(fake, "cam")

    def test_it_pins_film_fit_to_horizontal(self):
        """Which aperture governs is a FUNCTION of filmFit, so leaving it at
        whatever the scene had would make the lens correct only by luck."""
        fake = FakeLensCmds()
        capture.apply_framing_fov(fake, "cam")
        assert fake.attrs["camShape.filmFit"] == capture._FILM_FIT_HORIZONTAL

    def test_the_framed_subject_reaches_the_margin_it_asks_for(self):
        """The whole point, stated as the picture rather than the lens: at
        the distance the placement math chooses, the bounding sphere must
        fill 1/_FIT_MARGIN of the frame."""
        bbox_min, bbox_max = (-1.0, -1.0, -1.0), (1.0, 1.0, 1.0)
        radius = math.dist(bbox_min, bbox_max) / 2.0
        position, _rot = capture.camera_placement("front", bbox_min, bbox_max)
        distance = math.dist(position, (0.0, 0.0, 0.0))
        half_fov = math.radians(capture._FOV_DEG) / 2.0
        # Perspective, not angles: the frame's half-width is tan(half_fov).
        fill = math.tan(math.asin(radius / distance)) / math.tan(half_fov)
        assert fill == pytest.approx(
            math.tan(math.asin(math.sin(half_fov) / capture._FIT_MARGIN))
            / math.tan(half_fov), rel=1e-9)
        assert 0.80 < fill < 0.90


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


class FakeIsolateCmds:
    """Minimal cmds stub for the isolate path: isolateSelect + view-selected set.

    editor()/selectionConnection() raise — the isolate path must never touch
    the mainListConnection machinery (locking it breaks VP2 shading-group
    resolution for per-face/groupId bindings; redmine #575).

    #799: the panel is a REGISTERED name now. Every method used to accept
    any string as a live panel and answer for it, which is the viewport
    version of the vanished-node fallback: a handler that asked
    modelEditor/isolateSelect about a panel that no longer exists (a
    torn-off viewport the user closed mid-capture) got a plausible answer
    here and a RuntimeError in Maya. The view-selected SET is registered
    the same way: sets() answers for the panel's own set, not for any name.
    """

    def __init__(self, set_members=None, view_selected=False, panel="panelX"):
        self.calls = []
        self.panels = [panel]
        self.set_members = list(set_members or [])
        self.view_selected = view_selected

    def _require_panel(self, panel):
        if panel not in self.panels:
            raise RuntimeError("Object '%s' not found." % panel)
        return panel

    def isolateSelect(self, panel, **kw):
        self._require_panel(panel)
        self.calls.append(("isolateSelect", panel, kw))
        if kw.get("state") is not None:
            self.view_selected = bool(kw["state"])
        if "addDagObject" in kw:
            self.set_members.append(kw["addDagObject"])
        if "removeDagObject" in kw:
            self.set_members.remove(kw["removeDagObject"])

    def modelEditor(self, panel, **kw):
        self._require_panel(panel)
        self.calls.append(("modelEditor", panel, kw))
        if kw.get("query"):
            if kw.get("viewObjects"):
                return "%sViewSelectedSet" % panel
            if kw.get("viewSelected"):
                return self.view_selected
        return None

    def sets(self, name, **kw):
        self.calls.append(("sets", name, kw))
        # #799: only the panel's own view-selected set answers. Answering
        # for any string made "is this set real?" unaskable, and
        # _isolate_members' whole job is to decide that.
        if name not in ["%sViewSelectedSet" % p for p in self.panels]:
            raise RuntimeError("No object matches name: %s" % name)
        if kw.get("query"):
            return list(self.set_members)
        return None

    def editor(self, *args, **kw):
        raise AssertionError("isolate path must not touch editor()/mainListConnection")

    def selectionConnection(self, *args, **kw):
        raise AssertionError("isolate path must not touch selectionConnection()")


class TestApplyIsolate:
    def test_enables_state_wipes_stale_members_then_adds_targets(self):
        cmds = FakeIsolateCmds(set_members=["staleA", "staleB"])
        capture._apply_isolate(cmds, "panelX", ["|golem", "|rock"])
        iso_calls = [c for c in cmds.calls if c[0] == "isolateSelect"]
        assert iso_calls[0][2] == {"state": 1}
        removed = [c[2]["removeDagObject"] for c in iso_calls if "removeDagObject" in c[2]]
        assert removed == ["staleA", "staleB"]
        added = [c[2]["addDagObject"] for c in iso_calls if "addDagObject" in c[2]]
        assert added == ["|golem", "|rock"]
        assert cmds.set_members == ["|golem", "|rock"]

    def test_membership_is_exact_even_with_no_stale_members(self):
        cmds = FakeIsolateCmds()
        capture._apply_isolate(cmds, "panelX", ["|a"])
        assert cmds.set_members == ["|a"]

    def test_isolate_members_empty_when_panel_never_isolated(self):
        class NoSetCmds(FakeIsolateCmds):
            def modelEditor(self, panel, **kw):
                if kw.get("query") and kw.get("viewObjects"):
                    return ""
                return FakeIsolateCmds.modelEditor(self, panel, **kw)

        assert capture._isolate_members(NoSetCmds(), "panelX") == []

    def test_isolate_members_reads_view_selected_set(self):
        cmds = FakeIsolateCmds(set_members=["m1", "m2"])
        assert capture._isolate_members(cmds, "panelX") == ["m1", "m2"]


class TestIsolateRestore:
    def test_restore_reapplies_prior_members_when_user_had_isolate_on(self):
        cmds = FakeIsolateCmds(set_members=["userObj"], view_selected=True)
        state = _panel_state_stub(cmds)
        assert state.isolate_state is True
        assert state.isolate_members == ["userObj"]
        # capture isolates something else
        capture._apply_isolate(cmds, "panelX", ["|captureTarget"])
        state.isolate_dirty = True
        cmds.calls.clear()
        state.restore()
        assert cmds.set_members == ["userObj"]
        assert cmds.view_selected is True

    def test_restore_turns_isolate_off_and_wipes_members_when_user_had_it_off(self):
        cmds = FakeIsolateCmds(set_members=[], view_selected=False)
        state = _panel_state_stub(cmds)
        capture._apply_isolate(cmds, "panelX", ["|captureTarget"])
        state.isolate_dirty = True
        state.restore()
        assert cmds.set_members == []
        assert cmds.view_selected is False

    def test_restore_never_touches_isolate_when_capture_did_not_isolate(self):
        cmds = FakeIsolateCmds(set_members=["userObj"], view_selected=True)
        state = _panel_state_stub(cmds)
        cmds.calls.clear()
        state.restore()
        assert [c for c in cmds.calls if c[0] == "isolateSelect"] == []


def _panel_state_stub(fake_isolate_cmds):
    """A _PanelState over the isolate fake, with the unrelated cmds surface stubbed."""

    class FullFake(object):
        def __getattr__(self, name):
            return getattr(fake_isolate_cmds, name)

        def modelPanel(self, panel, **kw):
            return "persp"

        def modelEditor(self, panel, **kw):
            if kw.get("query"):
                if kw.get("displayAppearance"):
                    return "smoothShaded"
                if kw.get("wireframeOnShaded") or kw.get("displayTextures") or kw.get("grid"):
                    return False
            return fake_isolate_cmds.modelEditor(panel, **kw)

        def listRelatives(self, node, shapes=False, fullPath=False, **kw):
            return ["%sShape" % node] if shapes else None

        def getAttr(self, attr):
            if attr.endswith(".horizontalFilmAperture"):
                return capture.MAYA_HORIZONTAL_APERTURE_IN
            return 0

        def setAttr(self, *a, **kw):
            return None

        def ls(self, **kw):
            return []

        def getPanel(self, **kw):
            return None

        def select(self, *a, **kw):
            return None

        def lookThru(self, *a, **kw):
            return None

        def setFocus(self, *a, **kw):
            return None

    return capture._PanelState(FullFake(), "panelX")


class TestMarshaling:
    def test_capture_viewport_marshals_angles_resolution_and_wraps_results(
        self, monkeypatch
    ):
        calls = []

        def fake_capture(angle, shading, wireframe_overlay, buffer, isolate,
                         frame_all, resolution, lighting, shadows, frame_on=None):
            calls.append((angle, shading, wireframe_overlay, buffer, isolate,
                          frame_all, resolution, lighting, shadows, frame_on))
            return {"png_b64": "ZmFrZQ==", "camera_position": [0, 0, 10],
                    "camera_rotation": [0, 0, 0], "camera": "|mayaMcpTempCam"}

        monkeypatch.setattr(capture, "_capture_one", fake_capture)
        result = capture.capture_viewport(
            {"angles": ["front", "top"], "resolution": 4096, "shading": "wireframe",
             "wireframe_overlay": False, "isolate": ["|golem"], "frame_all": False,
             "target": ["|golem|chest"]}
        )
        assert all(c[9] == ["|golem|chest"] for c in calls)
        assert [c[0] for c in calls] == ["front", "top"]
        assert all(c[1] == "wireframe" for c in calls)
        assert all(c[2] is False for c in calls)
        assert all(c[4] == ["|golem"] for c in calls)
        assert all(c[5] is False for c in calls)
        assert all(c[6] == 2048 for c in calls)  # clamped
        assert all(c[7] == "default" for c in calls)  # lighting default
        assert all(c[8] is False for c in calls)  # shadows default
        assert [img["angle"] for img in result["images"]] == ["front", "top"]
        assert all(img["png_b64"] == "ZmFrZQ==" for img in result["images"])
        assert len(result["camera_positions"]) == 2
        # A stale "current" camera used to be captured silently - the LLM
        # must be able to SEE which camera actually produced each shot.
        assert all(
            cp["camera"] == "|mayaMcpTempCam" for cp in result["camera_positions"]
        )

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


def test_lighting_scene_sets_displayLights_all_and_restores_it(monkeypatch):
    # The blocking M2 requirement: a lit model must be capturable lit.
    # displayLights/shadows must also be RESTORED - they were not part of
    # _PanelState before, so setting them would have leaked into the user's
    # viewport permanently.
    fake = FakeCaptureCmds()
    fake.editor_state["displayLights"] = "default"
    fake.editor_state["shadows"] = False
    monkeypatch.setattr(capture, "_cmds", lambda: fake)
    monkeypatch.setattr(capture, "_grab_pixels", lambda *a, **k: (b"fakepng", {"blank": False, "unavailable_reason": None}))

    capture.capture_viewport({
        "angles": ["front"], "lighting": "scene", "shadows": True,
    })

    applied = [c for c in fake.calls if c[0] == "modelEditor" and c[2].get("edit")]
    assert any(c[2].get("displayLights") == "all" for c in applied), applied
    assert any(c[2].get("shadows") is True for c in applied), applied
    # restored to what it was before the capture
    assert fake.editor_state["displayLights"] == "default"
    assert fake.editor_state["shadows"] is False


class TestInvisibilityEvaluatorBracket:
    """#847: a capture arms Maya's invisibility evaluator (isolate, the temp
    camera, displayLights all change what is visible), and the next scene
    replace within ~100 ms then crashes inside the evaluator's tear-down
    (AnimUISlice!TinvisibilityEvaluator::endMonitoring, three identical
    native stack samples), after which Maya's crash handler spins forever.
    MEASURED: switching the evaluator off before the capture and back on
    after it returned 6/6 timed calls where the control spun 2/3; switching
    it off AFTER the capture trips the same crash (setActive -> endMonitoring).
    So the bracket is around the capture, and the restore is the LAST thing
    the capture does - after the panel restore and the temp camera delete,
    both of which change visibility too.
    """

    def _fake(self, monkeypatch, enabled):
        fake = FakeCaptureCmds()
        fake.evaluators["invisibility"] = enabled
        monkeypatch.setattr(capture, "_cmds", lambda: fake)
        seen = []

        def grab(*a, **k):
            seen.append(fake.evaluators["invisibility"])
            return (b"fakepng", {"blank": False, "unavailable_reason": None})

        monkeypatch.setattr(capture, "_grab_pixels", grab)
        return fake, seen

    def test_off_for_the_frame_and_back_on_last(self, monkeypatch):
        fake, seen = self._fake(monkeypatch, enabled=True)
        capture.capture_viewport({"angles": ["front"]})
        assert seen == [False], seen
        assert fake.evaluators["invisibility"] is True
        kinds = [c[0] for c in fake.calls]
        last_enable = max(i for i, c in enumerate(fake.calls)
                          if c[0] == "evaluator" and not c[2].get("query")
                          and c[2].get("enable") is True)
        last_panel_edit = max(i for i, c in enumerate(fake.calls)
                              if c[0] == "modelEditor" and c[2].get("edit"))
        last_delete = max(i for i, c in enumerate(fake.calls) if c[0] == "delete")
        assert last_enable > last_panel_edit, kinds
        assert last_enable > last_delete, kinds

    def test_an_evaluator_the_user_had_off_stays_off(self, monkeypatch):
        fake, seen = self._fake(monkeypatch, enabled=False)
        capture.capture_viewport({"angles": ["front"]})
        assert seen == [False]
        assert fake.evaluators["invisibility"] is False
        # the query form is `-q -en`; only an EDIT with enable=True counts
        assert not any(c[0] == "evaluator" and not c[2].get("query")
                       and c[2].get("enable") is True for c in fake.calls)

    def test_restored_even_when_the_frame_raises(self, monkeypatch):
        fake, _ = self._fake(monkeypatch, enabled=True)
        monkeypatch.setattr(capture, "_grab_pixels",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        with pytest.raises(RuntimeError):
            capture.capture_viewport({"angles": ["front"]})
        assert fake.evaluators["invisibility"] is True


def test_lighting_rejects_an_unknown_mode(monkeypatch):
    fake = FakeCaptureCmds()
    monkeypatch.setattr(capture, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        capture.capture_viewport({"angles": ["front"], "lighting": "cinematic"})
    assert "scene" in exc.value.hint


class FakeCaptureCmds:
    """Full cmds surface for driving _capture_one() end-to-end headless
    (angle="current", no isolate — the minimal path that still touches
    every call _capture_one makes) with _grab_pixels stubbed out.

    modelEditor's fake panel starts with every icon/manipulator flag ON
    (as a live user might leave them), so the test can tell "capture forced
    it off" (the mid-capture edit call) apart from "restore put it back"
    (the final edit call in _PanelState.restore) by value, not just by call
    order.

    #799: nodes and panels are REGISTERED. Before this, `listRelatives`
    answered "<anything>Shape", `getAttr` answered [(0,0,0)] for every plug
    it did not recognise, `ls(x, long=True)` answered "|x" for any string,
    and every panel-taking method accepted any panel name - so a capture
    that asked Maya about a camera it had already deleted, or about a panel
    that had gone away mid-call, could not fail here. This is the same
    class of blindness as #765 (a picture of nothing reported as a
    success): the fake agreed with the handler instead of with Maya.
    """

    def __init__(self):
        self.calls = []
        # The panels that exist, by type, and the only camera. `persp` is
        # the panel's camera, so angle="current" has something real to shoot
        # through. Typed rather than a bare name list because getPanel used
        # to answer "modelPanel" for whatever had focus, so find_model_panel
        # never took its search branches - and an agent-driven Maya almost
        # always has focus somewhere other than the viewport (#799).
        self.panel_types = {"modelPanel1": "modelPanel"}
        self.visible_panels = ["modelPanel1"]
        self.nodes = {"|persp": "|persp|perspShape"}   # long -> shape (or None)
        self.plugs = {
            "|persp.translate": (0.0, 0.0, 0.0),
            "|persp.rotate": (0.0, 0.0, 0.0),
            "|persp|perspShape.horizontalFilmAperture":
                capture.MAYA_HORIZONTAL_APERTURE_IN,
            "|persp|perspShape.filmFit": 0,
            "|persp|perspShape.focalLength": 35.0,
        }
        # Shapes cmds.ls(geometry=True, visible=True) reports. EMPTY by
        # default, which is why _capture_one's frame_all branch has only
        # ever taken its `viewFit(allObjects=True)` fallback here (#799).
        self.geometry = []
        # Light SHAPES cmds.ls(type="light") reports. Empty by default, so
        # lighting='scene' has nothing to light with - which is the state
        # #797 row 38 makes the handler say out loud.
        self.lights = []
        self.node_types = {"|persp": "transform", "|persp|perspShape": "camera"}
        self.boxes = {}
        self.view_selected = False
        self.isolate_members = []
        self.undo_state = True
        self.selection = []
        # Evaluation Manager evaluators by name, as `evaluator -q -en` reads
        # them. Only registered names answer (#799): Maya raises on an
        # unknown evaluator, and a capture that spelt it wrong would be
        # bracketing nothing.
        self.evaluators = {"invisibility": True}
        self.editor_state = {
            "displayAppearance": "smoothShaded",
            "wireframeOnShaded": True,
            "displayTextures": True,
            "grid": True,
            "lights": True,
            "cameras": True,
            "locators": True,
            "manipulators": True,
            "textures": True,
            "displayLights": "default",
            "shadows": False,
            # A stock Maya 2027 panel: colour-managed, ACES SDR-video view
            # (#837). The capture must set its own transform for the grab
            # and hand these back.
            "cmEnabled": True,
        }
        # The GLOBAL colour-management prefs (#837): the offscreen playblast
        # follows these, not the panel's own view transform (measured).
        self.cm_prefs = {"viewTransformName": "ACES 1.0 SDR-video (sRGB)",
                         "cmEnabled": True}
        # VP2's ambient-occlusion settings as a stock Maya 2027 has them
        # (#832). ssaoAmount is capped at 3 by Maya ("Cannot set the
        # attribute ... past its maximum value of 3", measured), and an
        # attribute hardwareRenderingGlobals does not have raises, as in Maya.
        self.vp2 = {"ssaoEnable": False, "ssaoAmount": 1.0, "ssaoRadius": 16,
                    "ssaoFilterRadius": 16, "ssaoSamples": 16}
        self.active_camera = "persp"  # panel's current camera (not cmds.camera(), below)
        self.focus_panel = "modelPanel1"
        self._create_seq = 0
        self.renamed = []
        self.deleted = []
        # When set, cmds.ls(<this name>, long=True) reports TWO matches
        # instead of one - reproduces a stray node that appeared between
        # naming.unique_name's objExists check and the rename (the race the
        # handler's own comment names), so the cosmetic `camera` field meets
        # an ambiguous short name. Deliberately NOT registered as a node:
        # registering it would make unique_name suffix the temp camera and
        # the ambiguity - the thing under test - would never arise.
        self.ambiguous_name = None

    # -- #799 existence ---------------------------------------------------
    def _long_names(self):
        """Every node in the fake scene - transforms AND their shapes,
        including a second shape under one transform (a ShapeOrig, #824)."""
        shapes = [s for s in self.nodes.values() if s]
        return list(self.nodes) + shapes + [
            g for g in self.geometry if g not in shapes]

    def _resolve(self, name):
        """The registered long name for `name`, or None. Matches Maya's own
        short-name lookup: a bare tail resolves if exactly one node has it."""
        name = str(name)
        known = self._long_names()
        if name in known:
            return name
        short = name.rsplit("|", 1)[-1]
        hits = [n for n in known if n.rsplit("|", 1)[-1] == short]
        return hits[0] if len(hits) == 1 else None

    def _require(self, name):
        resolved = self._resolve(name)
        if resolved is None:
            # The raise that found #796's blocking defects, in this file's
            # territory: a capture asking Maya about a temp camera it has
            # already deleted gets this, not an answer.
            raise RuntimeError("No object matches name: %s" % name)
        return resolved

    def _require_panel(self, panel):
        if panel not in self.panel_types:
            raise RuntimeError("Object '%s' not found." % panel)
        return panel

    def _plug(self, plug):
        node, _, attr = str(plug).rpartition(".")
        return "%s.%s" % (self._require(node), attr)

    def getPanel(self, **kw):
        if kw.get("withFocus"):
            return self.focus_panel
        if "typeOf" in kw:
            return self.panel_types.get(kw["typeOf"])
        if kw.get("type"):
            return [p for p, t in self.panel_types.items() if t == kw["type"]]
        if kw.get("visiblePanels"):
            return list(self.visible_panels)
        return None

    def modelPanel(self, panel, **kw):
        self._require_panel(panel)
        if kw.get("query") and kw.get("camera"):
            return self.active_camera
        return None

    def modelEditor(self, panel, **kw):
        self._require_panel(panel)
        self.calls.append(("modelEditor", panel, dict(kw)))
        if kw.get("query"):
            if kw.get("viewSelected"):
                return self.view_selected
            if kw.get("viewObjects"):
                return "%sViewSelectedSet" % panel if self.view_selected else ""
            for flag, value in self.editor_state.items():
                if kw.get(flag):
                    return value
            return None
        for flag, value in kw.items():
            if flag in self.editor_state:
                self.editor_state[flag] = value
        return None

    def colorManagementPrefs(self, **kw):
        self.calls.append(("colorManagementPrefs", dict(kw)))
        if kw.get("query"):
            for flag, value in self.cm_prefs.items():
                if kw.get(flag):
                    return value
            return None
        for flag, value in kw.items():
            if flag in self.cm_prefs:
                self.cm_prefs[flag] = value
        return None

    def evaluator(self, **kw):
        name = kw.get("name")
        if name not in self.evaluators:
            raise RuntimeError("Unknown evaluator '%s'" % name)
        self.calls.append(("evaluator", name, kw))
        if kw.get("query"):
            return self.evaluators[name]
        if "enable" in kw:
            self.evaluators[name] = bool(kw["enable"])
        return None

    def undoInfo(self, **kw):
        # #799: answering True to every query and nothing to every edit made
        # "did the capture put undo recording back?" unaskable, and a
        # perception tool that leaves it off has broken the user's undo.
        if kw.get("query"):
            return self.undo_state
        if "stateWithoutFlush" in kw:
            self.undo_state = bool(kw["stateWithoutFlush"])
        return None

    def listRelatives(self, node, shapes=False, fullPath=False, **kw):
        # apply_framing_fov (#772) sets the lens on the camera SHAPE. It used
        # to answer "<anything>Shape" for any string, which made the helper's
        # `or [camera]` fallback (a SHAPELESS node) untestable and let a
        # deleted camera answer (#799).
        resolved = self._require(node)
        if not shapes:
            return None
        shape = self.nodes.get(resolved)
        return [shape] if shape else None

    def _vp2_attr(self, attr):
        name = attr.split(".", 1)[1]
        if name not in self.vp2:
            raise RuntimeError("No object matches name: %s" % attr)
        return name

    def getAttr(self, attr):
        if attr.startswith("hardwareRenderingGlobals."):
            return self.vp2[self._vp2_attr(attr)]
        plug = self._plug(attr)
        if plug not in self.plugs:
            raise RuntimeError("No object matches name: %s" % attr)
        value = self.plugs[plug]
        # Maya wraps a double3 query in a one-tuple list; capture reads
        # getAttr(...)[0] for translate/rotate.
        return [tuple(value)] if isinstance(value, tuple) else value

    def setAttr(self, attr, *args, **kw):
        if attr.startswith("hardwareRenderingGlobals."):
            name = self._vp2_attr(attr)
            if name == "ssaoAmount" and float(args[0]) > 3.0:
                raise RuntimeError(
                    "setAttr: Cannot set the attribute '%s' past its maximum "
                    "value of 3." % attr)
            self.vp2[name] = args[0]
            return None
        plug = self._plug(attr)
        self.plugs[plug] = tuple(args) if len(args) > 1 else args[0]
        return None

    def ls(self, *args, **kw):
        if kw.get("type"):
            # lighting.light_shapes asks for "light" and then for each
            # Arnold light type BY NAME. This fake models Maya's own only;
            # an unknown type answers nothing rather than raising, which is
            # what a Maya without mtoa does through light_shapes' guard.
            return list(self.lights) if kw["type"] == "light" else []
        if kw.get("dag") and kw.get("shapes"):
            # `ls(<transforms>, dag=True, shapes=True)`: every shape at or
            # under the named nodes. MEASURED (#824): this is the form that
            # answers for a group - listRelatives(allDescendents=True,
            # shapes=True) answered NOTHING for one on Maya 2027. Before the
            # `long` branch, which reads a bare name.
            roots = list(args[0]) if isinstance(args[0], (list, tuple)) else [args[0]]
            roots = [self._require(r) for r in roots]
            out = []
            for shape in self.geometry:
                if kw.get("noIntermediate") and self.plugs.get(
                        shape + ".intermediateObject"):
                    continue
                if any(shape == r or shape.startswith(r + "|") for r in roots):
                    out.append(shape)
            return out
        if args and kw.get("long"):
            name = str(args[0])
            if self.ambiguous_name and name.lstrip("|") == self.ambiguous_name:
                short = name.lstrip("|")
                return ["|dupA|%s" % short, "|dupB|%s" % short]
            # A name nobody made answers with NOTHING - `ls` is the one
            # existence query that reports rather than raises.
            resolved = self._resolve(name)
            return [resolved] if resolved else []
        if kw.get("geometry"):
            return list(self.geometry)
        if kw.get("selection"):
            return list(self.selection)
        return []

    def select(self, *a, **kw):
        names = []
        if a and not kw.get("clear"):
            names = list(a[0]) if isinstance(a[0], (list, tuple)) else [a[0]]
            names = [self._require(name) for name in names]
        # It really CHANGES the selection (#799): returning None and keeping
        # ls(selection=True) at a constant [] made "did restore give the user
        # their selection back?" unaskable.
        self.selection = names
        self.calls.append(("select", names, dict(kw)))
        return None

    def refresh(self, **kw):
        return None

    # -- isolate, the other branch a constant answer kept dead (#799) ------
    # modelEditor answered viewSelected=False / viewObjects="" for every
    # panel, so _capture_one's isolate branch - and with it the
    # `state.isolate_dirty = True` that stops a capture leaving the user's
    # viewport isolated forever - was never executed in this file.
    def isolateSelect(self, panel, **kw):
        self._require_panel(panel)
        self.calls.append(("isolateSelect", panel, dict(kw)))
        if kw.get("state") is not None:
            self.view_selected = bool(kw["state"])
        if "addDagObject" in kw:
            self.isolate_members.append(self._require(kw["addDagObject"]))
        if "removeDagObject" in kw:
            self.isolate_members.remove(kw["removeDagObject"])
        return None

    def sets(self, name, **kw):
        if name not in ["%sViewSelectedSet" % p for p in self.panel_types]:
            raise RuntimeError("No object matches name: %s" % name)
        return list(self.isolate_members) if kw.get("query") else None

    # -- geometry, so _capture_one can actually FRAME something (#799) -----
    # Without these three the fake answered ls(geometry=True) with a constant
    # [], so _scene_bbox always short-circuited to its unit-box fallback and
    # _capture_one's frame_all branch only ever took `viewFit(allObjects=True)`
    # - the very call #639 says must never happen for a real scene. The `if
    # fit_set:` half could have been deleted and every test here stayed green.
    def nodeType(self, node):
        return self.node_types[self._require(node)]

    def getClassification(self, node_type, satisfies=None):
        return (["drawdb/light:light"]
                if node_type in FakeSceneCmds.LIGHT_TYPES else [])

    def exactWorldBoundingBox(self, *targets, **kw):
        # A transform's box is the union of the shapes under it, as in
        # Maya; a box registered for the transform itself wins (#824).
        boxes = []
        for target in targets:
            node = self._require(target)
            if node in self.boxes:
                boxes.append(self.boxes[node])
                continue
            under = [b for shape, b in self.boxes.items()
                     if shape.startswith(node + "|")]
            if not under:
                raise KeyError(node)
            boxes.append(tuple(
                [min(b[i] for b in under) for i in range(3)]
                + [max(b[i] for b in under) for i in range(3, 6)]))
        if not boxes:
            return [1e20, 1e20, 1e20, -1e20, -1e20, -1e20]
        return [min(b[i] for b in boxes) for i in range(3)] + [
            max(b[i] for b in boxes) for i in range(3, 6)
        ]

    def add_geometry(self, shape, node_type="mesh", box=(-1, -1, -1, 1, 1, 1),
                     intermediate=False):
        """Register a visible shape ls(geometry=True) will report.

        `intermediate` registers a deformer's ShapeOrig: MEASURED (#824),
        `ls(geometry=True, visible=True)` lists it alongside the drawn
        shape, and only its `.intermediateObject` plug tells them apart.
        """
        transform = shape.rsplit("|", 1)[0] or "|" + shape.lstrip("|")
        # The FIRST shape stays the transform's listRelatives answer; a
        # second one (a ShapeOrig) is still a node, via self.geometry.
        if not self.nodes.get(transform):
            self.nodes[transform] = shape
        self.node_types[transform] = "transform"
        self.node_types[shape] = node_type
        self.boxes[shape] = tuple(box)
        self.plugs[shape + ".intermediateObject"] = bool(intermediate)
        self.geometry.append(shape)
        # Every ancestor transform is a node too, so a GROUP can be named
        # as a target and its shapes found under it (#824).
        parts = transform.strip("|").split("|")
        for depth in range(1, len(parts)):
            ancestor = "|" + "|".join(parts[:depth])
            self.nodes.setdefault(ancestor, None)
            self.node_types.setdefault(ancestor, "transform")
        return shape

    def lookThru(self, panel, camera, *a, **kw):
        self._require_panel(panel)
        # It really MOVES the panel's eye (#799). Returning None and
        # changing nothing made "did restore put the user's camera back
        # before deleting the temp one?" an unaskable question - and
        # getting that order wrong leaves the panel pointed at a node that
        # no longer exists, which is what the next _PanelState would then
        # ask Maya about.
        self.active_camera = self._require(camera)
        self.calls.append(("lookThru", panel, camera))
        return None

    def setFocus(self, panel, *a, **kw):
        # It really MOVES focus (#799). _grab_pixels takes focus to
        # playblast and _PanelState.restore has to hand it back, which is
        # unaskable while this returns None and changes nothing.
        self.focus_panel = self._require_panel(panel)
        return None

    def objExists(self, name):
        return self._resolve(name) is not None

    def camera(self, **kw):
        # Deliberately ignores kw["name"] - matches the live Maya quirk
        # set_camera already works around (viewport.py); capture.py's temp
        # camera must use the same create-then-rename idiom.
        self._create_seq += 1
        transform = "camera%d" % self._create_seq
        shape = "camera%dShape" % self._create_seq
        long_t, long_s = "|" + transform, "|%s|%s" % (transform, shape)
        self.nodes[long_t] = long_s
        self.node_types[long_t] = "transform"
        self.node_types[long_s] = "camera"
        self.plugs[long_t + ".translate"] = (0.0, 0.0, 0.0)
        self.plugs[long_t + ".rotate"] = (0.0, 0.0, 0.0)
        self.plugs[long_t + ".visibility"] = True
        self.plugs[long_s + ".horizontalFilmAperture"] = \
            capture.MAYA_HORIZONTAL_APERTURE_IN
        self.plugs[long_s + ".filmFit"] = 0
        self.plugs[long_s + ".focalLength"] = 35.0
        return [transform, shape]

    def rename(self, node, new_name):
        resolved = self._require(node)
        self.renamed.append((node, new_name))
        new_long = "|" + str(new_name).lstrip("|")
        old_shape = self.nodes.pop(resolved)
        new_shape = None
        if old_shape:
            new_shape = "%s|%sShape" % (new_long, str(new_name).lstrip("|"))
        self.nodes[new_long] = new_shape
        self.node_types[new_long] = self.node_types.pop(resolved, "transform")
        if old_shape:
            self.node_types[new_shape] = self.node_types.pop(old_shape, "camera")
        for plug in list(self.plugs):
            if plug.startswith(resolved + "."):
                self.plugs[new_long + plug[len(resolved):]] = self.plugs.pop(plug)
            elif old_shape and plug.startswith(old_shape + "."):
                self.plugs[new_shape + plug[len(old_shape):]] = self.plugs.pop(plug)
        return new_name

    def viewFit(self, camera=None, **kw):
        if camera is not None:
            self._require(camera)
        self.calls.append(("viewFit", camera, dict(kw)))
        return None

    def delete(self, *a, **kw):
        self.deleted.extend(a)
        self.calls.append(("delete", a, kw))
        for name in a:
            resolved = self._resolve(name)
            if resolved is None:
                raise RuntimeError("No object matches name: %s" % name)
            shape = self.nodes.pop(resolved)
            for plug in list(self.plugs):
                if plug.startswith(resolved + ".") or (
                    shape and plug.startswith(shape + ".")
                ):
                    del self.plugs[plug]
        return None


class TestIconHiding:
    """capture must never let light icons / place3dTexture manipulators leak
    into a playblast (golem-run pain: they drifted into renders constantly),
    and must restore whatever the live user had afterwards."""

    def test_capture_forces_icons_off_then_panel_state_restores_them(
        self, monkeypatch
    ):
        cmds = FakeCaptureCmds()
        monkeypatch.setattr(capture, "_cmds", lambda: cmds)
        monkeypatch.setattr(capture, "_grab_pixels", lambda *a, **k: (b"fakepng", {"blank": False, "unavailable_reason": None}))

        capture._capture_one(
            "current", "smoothShaded", True, "beauty", None, True, 256
        )

        # `calls` records more than modelEditor now that lookThru/select/
        # viewFit are modelled too (#799), so the kind has to be named.
        edit_calls = [
            c[2] for c in cmds.calls
            if c[0] == "modelEditor" and not c[2].get("query") and "lights" in c[2]
        ]
        assert len(edit_calls) == 2, "expected one capture edit + one restore edit"
        capture_kwargs, restore_kwargs = edit_calls

        assert capture_kwargs["lights"] is False
        assert capture_kwargs["cameras"] is False
        assert capture_kwargs["locators"] is False
        assert capture_kwargs["manipulators"] is False
        assert capture_kwargs["textures"] is False

        # _PanelState snapshotted the user's original (all-on) state and
        # restore() puts it back rather than leaving icons force-hidden.
        assert restore_kwargs["lights"] is True
        assert restore_kwargs["cameras"] is True
        assert restore_kwargs["locators"] is True
        assert restore_kwargs["manipulators"] is True
        assert restore_kwargs["textures"] is True

    def test_result_carries_resolved_long_camera_name(self, monkeypatch):
        cmds = FakeCaptureCmds()
        monkeypatch.setattr(capture, "_cmds", lambda: cmds)
        monkeypatch.setattr(capture, "_grab_pixels", lambda *a, **k: (b"fakepng", {"blank": False, "unavailable_reason": None}))

        shot = capture._capture_one(
            "current", "smoothShaded", True, "beauty", None, True, 256
        )
        assert shot["camera"] == "|persp"


class TestTempCamera:
    """I3: the per-angle temp camera must use the same create-then-rename
    idiom as set_camera (cmds.camera(name=...) does not actually rename the
    transform on this Maya), and the cosmetic `camera` field it feeds must
    never raise on an ambiguous short name - it must never fail an entire
    capture over a display-only field."""

    def test_temp_camera_created_then_renamed_not_named_kwarg(self, monkeypatch):
        cmds = FakeCaptureCmds()
        monkeypatch.setattr(capture, "_cmds", lambda: cmds)
        monkeypatch.setattr(capture, "_grab_pixels", lambda *a, **k: (b"fakepng", {"blank": False, "unavailable_reason": None}))

        shot = capture._capture_one(
            "front", "smoothShaded", True, "beauty", None, True, 256
        )

        assert cmds._create_seq == 1  # exactly one temp camera created
        assert cmds.renamed == [("camera1", "mayaMcpTempCam")]
        assert shot["camera"] == "|mayaMcpTempCam"
        # the temp camera must be cleaned up afterwards
        assert "mayaMcpTempCam" in cmds.deleted

    def test_ambiguous_temp_camera_short_name_does_not_raise(self, monkeypatch):
        # Reproduces the exact bug: a scene node happens to share the temp
        # camera's short name. Before the fix, the cosmetic `camera` field
        # used naming.require_object, which raises HandlerError("ambiguous")
        # here and would fail the whole capture after pixels were grabbed.
        cmds = FakeCaptureCmds()
        cmds.ambiguous_name = "mayaMcpTempCam"
        monkeypatch.setattr(capture, "_cmds", lambda: cmds)
        monkeypatch.setattr(capture, "_grab_pixels", lambda *a, **k: (b"fakepng", {"blank": False, "unavailable_reason": None}))

        shot = capture._capture_one(
            "front", "smoothShaded", True, "beauty", None, True, 256
        )

        assert shot["png_b64"]  # the capture succeeded end to end
        assert shot["camera"] == "|dupA|mayaMcpTempCam"  # first match, no raise


class TestCaptureOneFramesTheScene:
    """#799: what a constant `ls(geometry=True) -> []` was hiding.

    Every other _capture_one test here runs against an EMPTY fake scene, so
    _scene_bbox short-circuits to its unit-box fallback and the frame_all
    branch always lands on `viewFit(allObjects=True)` - the one call #639
    says must never happen for a real scene, because viewFit refits to the
    sky dome the placement math just excluded and puts the camera 5498
    units out. The `if fit_set:` half could have been deleted outright and
    the file stayed green.
    """

    def _fake(self, monkeypatch):
        cmds = FakeCaptureCmds()
        cmds.add_geometry("|golem|golemShape", box=(-2.5, -2.5, -2.5, 2.5, 2.5, 2.5))
        cmds.add_geometry("|mcpLight_dome|mcpLight_domeShape", "aiSkyDomeLight",
                          box=(-1000, -1000, -1000, 1000, 1000, 1000))
        monkeypatch.setattr(capture, "_cmds", lambda: cmds)
        monkeypatch.setattr(
            capture, "_grab_pixels",
            lambda *a, **k: (b"fakepng", {"blank": False,
                                          "unavailable_reason": None}))
        return cmds

    def test_it_fits_an_explicit_selection_never_all_objects(self, monkeypatch):
        cmds = self._fake(monkeypatch)
        capture._capture_one(
            "front", "smoothShaded", True, "beauty", None, True, 256)
        fits = [c for c in cmds.calls if c[0] == "viewFit"]
        assert len(fits) == 1
        assert fits[0][2].get("allObjects") is None, (
            "viewFit allObjects refits to the dome the placement excluded (#639)"
        )
        # ...on the framable geometry, which is the cube and NOT the dome.
        selected = [c[1] for c in cmds.calls if c[0] == "select" and c[1]]
        assert selected[-1] == ["|golem|golemShape"]

    def test_the_dome_does_not_decide_where_the_camera_goes(self, monkeypatch):
        cmds = self._fake(monkeypatch)
        shot = capture._capture_one(
            "front", "smoothShaded", True, "beauty", None, True, 256)
        # A 5-unit cube frames from single digits away; the dome's own box
        # would have put this past 5000 (#639, measured 5294 on a real run).
        assert abs(shot["camera_position"][2]) < 20.0

    def test_a_named_target_frames_on_it_alone(self, monkeypatch):
        cmds = self._fake(monkeypatch)
        cmds.add_geometry("|floor|floorShape", box=(-50, -1, -50, 50, 0, 50))
        near = capture._capture_one(
            "front", "smoothShaded", True, "beauty", None, True, 256,
            frame_on=["|golem|golemShape"])
        far = capture._capture_one(
            "front", "smoothShaded", True, "beauty", None, True, 256)
        assert near["camera_position"][2] < far["camera_position"][2]

    def test_the_panel_is_not_left_looking_through_a_deleted_camera(
        self, monkeypatch
    ):
        """The ORDER in _capture_one's finally: restore's lookThru has to
        put the user's camera back BEFORE the temp camera is deleted. A
        panel pointed at a vanished node is what the NEXT _PanelState then
        asks Maya about - and Maya raises rather than answering (#799)."""
        cmds = self._fake(monkeypatch)
        capture.capture_viewport({"angles": ["front", "current"]})
        assert cmds.active_camera == "|persp"
        assert "mayaMcpTempCam" in cmds.deleted
        assert cmds._resolve("mayaMcpTempCam") is None

    def test_an_isolating_capture_turns_isolate_back_off(self, monkeypatch):
        """`state.isolate_dirty = True` is what makes restore unwind the
        isolate. Delete that one line and a capture leaves the user's
        viewport showing only the object it was asked about, forever - and
        until #799 nothing in this file executed the branch that sets it."""
        cmds = self._fake(monkeypatch)
        capture._capture_one(
            "front", "smoothShaded", True, "beauty", ["|golem|golemShape"],
            True, 256)
        assert any(c[0] == "isolateSelect" and c[2].get("addDagObject")
                   for c in cmds.calls)
        assert cmds.view_selected is False   # the user had it off
        assert cmds.isolate_members == []

    def test_an_isolating_capture_puts_the_users_own_isolate_back(
        self, monkeypatch
    ):
        cmds = self._fake(monkeypatch)
        cmds.view_selected = True
        cmds.isolate_members = ["|floor|floorShape"]
        cmds.add_geometry("|floor|floorShape", box=(-50, -1, -50, 50, 0, 50))
        capture._capture_one(
            "front", "smoothShaded", True, "beauty", ["|golem|golemShape"],
            True, 256)
        assert cmds.view_selected is True
        assert cmds.isolate_members == ["|floor|floorShape"]

    def test_it_captures_when_focus_is_not_on_a_viewport(self, monkeypatch):
        """getPanel(typeOf=...) answered "modelPanel" for whatever had
        focus, so find_model_panel's SEARCH branches were dead code here -
        and an agent-driven Maya normally has focus in the script editor,
        which is the very session #765 was measured on."""
        cmds = self._fake(monkeypatch)
        cmds.panel_types["scriptEditorPanel1"] = "scriptEditor"
        cmds.focus_panel = "scriptEditorPanel1"
        assert capture.find_model_panel(cmds) == "modelPanel1"
        shot = capture._capture_one(
            "front", "smoothShaded", True, "beauty", None, True, 256)
        assert shot["png_b64"]
        # and the user's focus is where they left it
        assert cmds.focus_panel == "scriptEditorPanel1"

    def test_it_refuses_when_there_is_no_viewport_at_all(self, monkeypatch):
        cmds = self._fake(monkeypatch)
        cmds.panel_types = {"scriptEditorPanel1": "scriptEditor"}
        cmds.visible_panels = ["scriptEditorPanel1"]
        cmds.focus_panel = "scriptEditorPanel1"
        with pytest.raises(HandlerError, match="no model panel"):
            capture.find_model_panel(cmds)

    def test_the_users_selection_survives_the_capture(self, monkeypatch):
        """_capture_one selects to viewFit and clears to keep the highlight
        out of the pixels, so it walks all over the selection. The fake
        answered ls(selection=True) with a constant [], so restoring it was
        untested (#799)."""
        cmds = self._fake(monkeypatch)
        cmds.selection = ["|golem|golemShape"]
        capture._capture_one(
            "front", "smoothShaded", True, "beauty", None, True, 256)
        assert cmds.selection == ["|golem|golemShape"]

    def test_undo_recording_is_put_back(self, monkeypatch):
        """Perception must not pollute the undo queue, so the capture turns
        recording off - and has to turn it back on."""
        cmds = self._fake(monkeypatch)
        capture._capture_one(
            "front", "smoothShaded", True, "beauty", None, True, 256)
        assert cmds.undo_state is True

    def test_a_target_that_does_not_exist_is_refused(self, monkeypatch):
        cmds = self._fake(monkeypatch)
        with pytest.raises(HandlerError, match="not found"):
            capture._capture_one(
                "front", "smoothShaded", True, "beauty", None, True, 256,
                frame_on=["|ghost"])
        # and nothing was left behind by the attempt
        assert cmds.nodes.get("|mayaMcpTempCam") is None


def test_turntable_defaults_to_eight_frames_evenly_spaced(monkeypatch):
    fake = FakeCaptureCmds()
    monkeypatch.setattr(capture, "_cmds", lambda: fake)
    seen = []

    def fake_capture_one(angle, *args, **kwargs):
        seen.append(angle)
        return {"png_b64": "x", "camera_position": [0, 0, 0],
                "camera_rotation": [0, 0, 0], "camera": "|cam"}

    monkeypatch.setattr(capture, "_capture_one", fake_capture_one)
    result = capture.capture_turntable({"target": "|golem"})
    assert result["n_frames"] == 8
    assert [i["azimuth"] for i in result["images"]] == [0, 45, 90, 135, 180, 225, 270, 315]
    # the ("azimuth", float) tuple handoff to _capture_one - _capture_one's
    # `angle` param accepts this alongside the plain Angle strings, and this
    # is the only thing that actually proves the tuple form reaches it.
    assert seen == [
        ("azimuth", 0.0), ("azimuth", 45.0), ("azimuth", 90.0),
        ("azimuth", 135.0), ("azimuth", 180.0), ("azimuth", 225.0),
        ("azimuth", 270.0), ("azimuth", 315.0),
    ]


def test_turntable_caps_at_sixteen_frames(monkeypatch):
    fake = FakeCaptureCmds()
    monkeypatch.setattr(capture, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        capture.capture_turntable({"target": "|golem", "n_frames": 32})
    assert "16" in str(exc.value)


class FakeSceneCmds:
    """A scene of shapes with node types and boxes - enough for framing math.

    Classification answers the way Maya 2027 measurably does: every light type
    satisfies 'light', mesh and locator do not.
    """

    LIGHT_TYPES = {"aiSkyDomeLight", "aiAreaLight", "directionalLight", "pointLight"}

    def __init__(self, shapes):
        self.shapes = shapes  # name -> (nodeType, (minx,miny,minz,maxx,maxy,maxz))
        self.unknown_classification = set()
        self.visible = {name: True for name in shapes}

    def ls(self, *args, geometry=False, visible=False, long=False, **kw):
        assert geometry and visible
        return list(self.shapes)

    def nodeType(self, name):
        # #799: Maya's own words for a node that is not there, rather than a
        # KeyError - is_light_shape swallows every exception, so the shape of
        # the failure is what a reader has to be able to trust.
        if name not in self.shapes:
            raise RuntimeError("No object matches name: %s" % name)
        return self.shapes[name][0]

    def getClassification(self, node_type, satisfies=None):
        if node_type in self.unknown_classification:
            raise RuntimeError("unknown node type")
        assert satisfies == "light"
        return ["drawdb/light:light"] if node_type in self.LIGHT_TYPES else []

    def objExists(self, name):
        return name in self.shapes

    def exactWorldBoundingBox(self, *names, **kwargs):
        for name in names:
            if name not in self.shapes:
                raise RuntimeError("No object matches name: %s" % name)
        boxes = [self.shapes[n][1] for n in names]
        if kwargs.get("ignoreInvisible"):
            boxes = [
                self.shapes[n][1] for n in names if self.visible.get(n, True)
            ]
        if not boxes:
            # Maya's answer for "nothing visible" is an INVERTED sentinel box,
            # measured on 2027 as [1e20]*3 + [-1e20]*3. Reproducing it is the
            # point: fed to camera_placement it put a camera 5.8e20 units out.
            return [1e20, 1e20, 1e20, -1e20, -1e20, -1e20]
        return [min(b[i] for b in boxes) for i in range(3)] + [
            max(b[i] for b in boxes) for i in range(3, 6)
        ]


# The measured #639 scene: a 5-unit cube and one setup_lighting dome.
DOME_SCENE = {
    "golemChestShape": ("mesh", (-2.5, -2.5, -2.5, 2.5, 2.5, 2.5)),
    "mcpLight_domeShape": ("aiSkyDomeLight", (-1000, -1000, -1000, 1000, 1000, 1000)),
}


class TestFramingExcludesLights:
    def test_a_dome_does_not_decide_the_frame(self):
        fake = FakeSceneCmds(DOME_SCENE)
        assert capture._scene_bbox(fake, None) == (
            [-2.5, -2.5, -2.5], [2.5, 2.5, 2.5]
        )

    def test_without_the_filter_the_dome_would_have_won(self):
        fake = FakeSceneCmds(DOME_SCENE)
        every = fake.exactWorldBoundingBox(*fake.shapes)
        assert every[3] == 1000  # the unfiltered answer
        assert capture.framable_geometry(fake) == ["golemChestShape"]

    def test_the_defect_as_a_distance(self):
        """What the dome's bbox does to the camera, in units - the same order
        as the 5294 the #601 run measured on a real scene."""
        dome_pos, _ = capture.camera_placement(
            "three_quarter", [-1000, -1000, -1000], [1000, 1000, 1000]
        )
        subject_pos, _ = capture.camera_placement(
            "three_quarter", [-2.5, -2.5, -2.5], [2.5, 2.5, 2.5]
        )
        assert math.dist([0, 0, 0], dome_pos) > 5000
        assert math.dist([0, 0, 0], subject_pos) < 20

    def test_every_light_type_is_excluded_not_just_the_dome(self):
        fake = FakeSceneCmds({
            "bodyShape": ("mesh", (-1, -1, -1, 1, 1, 1)),
            "sunShape": ("directionalLight", (-50, -50, -50, 50, 50, 50)),
            "bulbShape": ("pointLight", (-70, -70, -70, 70, 70, 70)),
            "panelShape": ("aiAreaLight", (-90, -90, -90, 90, 90, 90)),
        })
        assert capture.framable_geometry(fake) == ["bodyShape"]

    def test_a_locator_is_not_a_light_and_still_frames(self):
        fake = FakeSceneCmds({
            "bodyShape": ("mesh", (-1, -1, -1, 1, 1, 1)),
            "annotationShape": ("locator", (0, 0, 0, 3, 3, 3)),
        })
        assert capture._scene_bbox(fake, None) == ([-1, -1, -1], [3, 3, 3])

    def test_naming_the_dome_explicitly_still_frames_it(self):
        # the filter is the FALLBACK's, not a veto on what a caller asked for
        fake = FakeSceneCmds(DOME_SCENE)
        assert capture._scene_bbox(fake, ["mcpLight_domeShape"]) == (
            [-1000, -1000, -1000], [1000, 1000, 1000]
        )

    def test_an_unclassifiable_node_stays_in_frame(self):
        # absence of an answer is not an answer: dropping it would silently
        # shrink the frame around a plugin shape nobody here has heard of
        fake = FakeSceneCmds({"weirdShape": ("someVendorMesh", (-4, -4, -4, 4, 4, 4))})
        fake.unknown_classification.add("someVendorMesh")
        assert capture.framable_geometry(fake) == ["weirdShape"]

    def test_a_scene_of_nothing_but_lights_still_returns_a_sane_box(self):
        fake = FakeSceneCmds({
            "domeShape": ("aiSkyDomeLight", (-1000, -1000, -1000, 1000, 1000, 1000)),
        })
        assert capture._scene_bbox(fake, None) == (
            [-1.0, -1.0, -1.0], [1.0, 1.0, 1.0]
        )


class TestVisibleOnlyFraming:
    """#640-4: framing a contact-sheet cell on what it SHOWS, not on what its
    subject contains. exactWorldBoundingBox includes hidden children."""

    SCENE = {
        "pelvisShape": ("mesh", (-1, 0, -1, 1, 2, 1)),
        "chestShape": ("mesh", (-2, 2, -2, 2, 8, 2)),
    }

    def test_off_by_default_a_hidden_object_still_counts(self):
        """A caller who frames on something they hid means its place in the
        world, not an empty box - so this must stay opt-in."""
        fake = FakeSceneCmds(self.SCENE)
        fake.visible["chestShape"] = False
        assert capture._scene_bbox(fake, ["pelvisShape", "chestShape"]) == (
            [-2, 0, -2], [2, 8, 2]
        )

    def test_on_request_the_hidden_object_drops_out(self):
        fake = FakeSceneCmds(self.SCENE)
        fake.visible["chestShape"] = False
        assert capture._scene_bbox(
            fake, ["pelvisShape", "chestShape"], visible_only=True
        ) == ([-1, 0, -1], [1, 2, 1])

    def test_an_all_hidden_target_falls_back_instead_of_returning_the_sentinel(self):
        """Maya answers an all-invisible query with an INVERTED box (min 1e20,
        max -1e20). Passed to camera_placement that put the camera 5.8e20 units
        out - a frame of nothing that reads as a broken renderer. Measured on
        2027; found by the live gate."""
        fake = FakeSceneCmds(self.SCENE)
        fake.visible["pelvisShape"] = False
        fake.visible["chestShape"] = False
        bbox_min, bbox_max = capture._scene_bbox(
            fake, ["pelvisShape", "chestShape"], visible_only=True
        )
        assert bbox_min == [-2, 0, -2] and bbox_max == [2, 8, 2]
        assert all(lo <= hi for lo, hi in zip(bbox_min, bbox_max))

    def test_the_sentinel_would_have_produced_an_absurd_camera(self):
        """What the guard prevents, stated in units."""
        position, _ = capture.camera_placement(
            "three_quarter", [1e20, 1e20, 1e20], [-1e20, -1e20, -1e20]
        )
        assert max(abs(v) for v in position) > 1e19


class TestCaptureViewportTarget:
    def _spy(self, monkeypatch):
        seen = {}

        def fake_capture_one(angle, *args, **kwargs):
            seen["frame_on"] = kwargs.get("frame_on")
            seen["isolate"] = args[3]
            return {"png_b64": "x", "camera_position": [0, 0, 0],
                    "camera_rotation": [0, 0, 0], "camera": "|cam"}

        monkeypatch.setattr(capture, "_capture_one", fake_capture_one)
        return seen

    def test_target_frames_without_isolating(self, monkeypatch):
        seen = self._spy(monkeypatch)
        capture.capture_viewport({"angles": ["front"], "target": ["|golem|chest"]})
        assert seen["frame_on"] == ["|golem|chest"]
        assert seen["isolate"] is None  # nothing was hidden to achieve it

    def test_a_bare_string_target_is_accepted(self, monkeypatch):
        seen = self._spy(monkeypatch)
        capture.capture_viewport({"angles": ["front"], "target": "|golem|chest"})
        assert seen["frame_on"] == ["|golem|chest"]

    def test_a_bad_target_is_rejected_before_any_capture(self, monkeypatch):
        monkeypatch.setattr(
            capture, "_capture_one",
            lambda *a, **k: pytest.fail("captured despite an invalid target"),
        )
        with pytest.raises(HandlerError, match="target"):
            capture.capture_viewport({"target": [1, 2]})


class TestBlankFrameIsNamed:
    """#765: a picture of nothing came back with a success status.

    The measured shape: every pixel transparent, RGB intact, so the frame
    composited to flat white in any viewer while the handler reported nothing
    at all. A live gate passed on it. These pin the reporting, not the cause -
    the cause was never reproduced on a fresh Maya, which is exactly why the
    report has to exist.
    """

    def _shot(self, blank, reason=None):
        return {"png_b64": "ZmFrZQ==", "camera_position": [0, 0, 10],
                "camera_rotation": [0, 0, 0], "camera": "|cam",
                "blank": blank, "blank_unmeasurable": reason}

    def test_a_blank_frame_is_named_in_warnings(self, monkeypatch):
        monkeypatch.setattr(capture, "_capture_one",
                            lambda *a, **k: self._shot(True))
        result = capture.capture_viewport({"angles": ["front"]})
        assert len(result["warnings"]) == 1
        assert "BLANK" in result["warnings"][0]
        assert "front" in result["warnings"][0]
        # and the frame is still RETURNED - an empty scene is a legal request,
        # so this names the frame rather than refusing the call
        assert result["images"][0]["png_b64"] == "ZmFrZQ=="
        assert result["images"][0]["blank"] is True

    def test_a_drawn_frame_warns_about_nothing(self, monkeypatch):
        monkeypatch.setattr(capture, "_capture_one",
                            lambda *a, **k: self._shot(False))
        result = capture.capture_viewport({"angles": ["front", "side"]})
        assert result["warnings"] == []
        assert all(img["blank"] is False for img in result["images"])

    def test_only_the_blank_angles_are_named(self, monkeypatch):
        shots = iter([self._shot(False), self._shot(True), self._shot(False)])
        monkeypatch.setattr(capture, "_capture_one",
                            lambda *a, **k: next(shots))
        result = capture.capture_viewport(
            {"angles": ["front", "side", "top"]})
        assert len(result["warnings"]) == 1
        assert "side" in result["warnings"][0]

    def test_an_unmeasurable_frame_says_so_rather_than_passing(
        self, monkeypatch
    ):
        # "I did not check" and "I checked and it is fine" must not look
        # alike - silence is what this whole ticket is about.
        monkeypatch.setattr(
            capture, "_capture_one",
            lambda *a, **k: self._shot(None, "ValueError: 16-bit"))
        result = capture.capture_viewport({"angles": ["front"]})
        assert len(result["warnings"]) == 1
        assert "could not be measured" in result["warnings"][0]
        assert "16-bit" in result["warnings"][0]

    def test_a_turntable_names_its_blank_cells_too(self, monkeypatch):
        # capture_turntable shares _capture_one, and a blank cell in a contact
        # sheet reads as "that angle looks wrong", not "that angle drew
        # nothing".
        shots = iter([self._shot(True), self._shot(False)])
        monkeypatch.setattr(capture, "_capture_one",
                            lambda *a, **k: next(shots))
        result = capture.capture_turntable({"n_frames": 2})
        assert len(result["warnings"]) == 1
        assert "azimuth 0" in result["warnings"][0]
        assert [img["blank"] for img in result["images"]] == [True, False]


class FakeMainWindow:
    """Maya's main window, with the one behaviour that makes #826 hard.

    MEASURED (evals/realized_note_probe_826b.py, virgin agent Maya inside the
    boot race): `show()` sets `isVisible()` True SYNCHRONOUSLY, in the same
    command, in both worlds - the one where the window stays up and the one
    where Maya's start-up hides it again on its next event-loop turn. Neither
    `QApplication.sendPostedEvents` nor `processEvents` revealed the
    difference; only the next command did.

    So `stick=False` models the racing process: show() reads back True, and
    the value the NEXT call sees is False again.
    """

    def __init__(self, visible=False, stick=True):
        self._visible = visible
        self.stick = stick
        self.shows = 0
        self._pending_hide = False

    def isVisible(self):  # noqa: N802 - Qt's name
        return self._visible

    def show(self):
        self.shows += 1
        # True inside this call whatever happens next - that is the trap, so
        # the fake must NOT hide it here. A readback in the same command
        # cannot tell the two worlds apart, and a fake that let one work
        # would make an impossible design look verifiable (#799's lesson).
        self._visible = True
        self._pending_hide = not self.stick

    def next_command(self):
        """Hand back to Maya's event loop: a racing process re-hides here."""
        if self._pending_hide:
            self._visible = False
            self._pending_hide = False


@pytest.fixture(autouse=True)
def _forget_window_notes():
    """Each test gets a process that has said nothing about the window yet."""
    capture.reset_window_notes()
    yield
    capture.reset_window_notes()


class TestUnrealizedWindow:
    """#765's cause: a main window that was never shown draws nothing.

    Measured on a freshly launched Maya - 0 opaque pixels before `show()`,
    9604 immediately after, on the identical scene and camera. These tests
    can only pin the behaviour OUTSIDE Maya; the fix firing for real is
    evals/capture_blank_live.py claim 1, which needs a Maya that has never
    been looked at.
    """

    def test_outside_maya_it_does_nothing_rather_than_raising(self):
        # No maya.OpenMayaUI to import here. A capture must never fail
        # because the window check could not run - the blank report
        # downstream is the backstop.
        assert capture.ensure_viewport_realized() is None

    def test_capture_viewport_survives_a_window_check_that_explodes(
        self, monkeypatch
    ):
        def boom():
            raise RuntimeError("no Qt in this build")

        monkeypatch.setattr(capture, "ensure_viewport_realized", boom)
        monkeypatch.setattr(
            capture, "_capture_one",
            lambda *a, **k: {"png_b64": "ZmFrZQ==", "camera_position": [0, 0, 1],
                             "camera_rotation": [0, 0, 0], "camera": "|cam",
                             "blank": False, "blank_unmeasurable": None})
        with pytest.raises(RuntimeError):
            capture.capture_viewport({"angles": ["front"]})

    def test_the_note_is_reported_when_the_window_had_to_be_shown(
        self, monkeypatch
    ):
        # Making a window appear is a visible side effect, and this tool's
        # contract is that a capture has none - so it is said out loud.
        monkeypatch.setattr(capture, "ensure_viewport_realized",
                            lambda: "showed the window")
        monkeypatch.setattr(
            capture, "_capture_one",
            lambda *a, **k: {"png_b64": "ZmFrZQ==", "camera_position": [0, 0, 1],
                             "camera_rotation": [0, 0, 0], "camera": "|cam",
                             "blank": False, "blank_unmeasurable": None})
        result = capture.capture_viewport({"angles": ["front"]})
        assert result["warnings"] == ["showed the window"]
        turn = capture.capture_turntable({"n_frames": 2})
        assert turn["warnings"] == ["showed the window"]


class TestTheWindowNoteSaysWhatActuallyHappened:
    """#826: the note used to ASSERT an effect it never checked.

    It said "this call showed it. That is a visible change to the screen" on
    every capture of a hidden window. MEASURED on agent Mayas (probes
    realized_note_probe_826*.py): during Maya's first seconds a show() is
    undone again before the next command, so no window appeared and the same
    claim fired on capture after capture; a few seconds later a show() sticks
    for good, and then it is true. Neither state is knowable from inside the
    call that shows - the readback is True either way - so the note stops
    asserting and the NEXT call reports what came of it.
    """

    def _call(self, window):
        window.next_command()
        return capture.ensure_viewport_realized()

    def _use(self, monkeypatch, window):
        monkeypatch.setattr(capture, "_maya_main_window", lambda: window)
        return window

    def test_the_first_call_asks_and_does_not_claim_it_showed_anything(
        self, monkeypatch
    ):
        window = self._use(monkeypatch, FakeMainWindow(visible=False))
        note = self._call(window)
        assert window.shows == 1, "the show() #765 needs must still happen"
        assert "asked Maya to show it" in note
        assert "showed it." not in note

    def test_a_request_that_did_not_take_is_reported_once_not_every_capture(
        self, monkeypatch
    ):
        # The racing process: show() reads back True, next command says False.
        window = self._use(monkeypatch, FakeMainWindow(visible=False,
                                                       stick=False))
        first = self._call(window)
        assert "asked Maya to show it" in first
        second = self._call(window)
        assert "did not take" in second
        assert window.shows == 2, "the protection is retried, only the note stops"
        # The defect itself: before #826 this note repeated forever.
        assert self._call(window) is None
        assert self._call(window) is None
        assert window.shows == 4

    def test_a_window_that_came_up_is_reported_once_when_it_is_measurable(
        self, monkeypatch
    ):
        window = self._use(monkeypatch, FakeMainWindow(visible=False))
        assert "asked Maya to show it" in self._call(window)
        note = self._call(window)  # now genuinely visible, and we asked for it
        assert "up on screen now" in note
        assert "the only one a capture makes" in note
        assert self._call(window) is None, "said once, not on every capture"

    def test_the_racing_process_walks_ask_then_not_taken_then_up(
        self, monkeypatch
    ):
        # The whole measured sequence: Maya un-shows the first request, the
        # second sticks, and each stage is reported exactly once.
        window = self._use(monkeypatch, FakeMainWindow(visible=False,
                                                       stick=False))
        assert "asked Maya to show it" in self._call(window)
        window.stick = True  # the boot race closes
        assert "did not take" in self._call(window)
        assert "up on screen now" in self._call(window)
        assert self._call(window) is None

    def test_a_window_somebody_is_looking_at_is_never_touched_or_mentioned(
        self, monkeypatch
    ):
        # An interactive Maya. Nothing to fix, nothing to report, and above
        # all no show() - this must stay invisible to the user's session.
        window = self._use(monkeypatch, FakeMainWindow(visible=True))
        assert self._call(window) is None
        assert self._call(window) is None
        assert window.shows == 0

    def test_a_window_up_for_reasons_of_ours_is_not_claimed(self, monkeypatch):
        # Visible without this tool ever asking: no credit taken.
        window = self._use(monkeypatch, FakeMainWindow(visible=True))
        assert self._call(window) is None
        window._visible = False
        assert "asked Maya to show it" in self._call(window)

    def test_no_qt_to_ask_is_silent_rather_than_fatal(self, monkeypatch):
        monkeypatch.setattr(capture, "_maya_main_window", lambda: None)
        assert capture.ensure_viewport_realized() is None

    def test_a_window_that_raises_never_fails_the_capture(self, monkeypatch):
        class Hostile:
            def isVisible(self):  # noqa: N802 - Qt's name
                raise RuntimeError("wrapped a dead pointer")

        monkeypatch.setattr(capture, "_maya_main_window", lambda: Hostile())
        assert capture.ensure_viewport_realized() is None

    def test_a_show_that_raises_is_silent_and_leaves_the_latch_alone(
        self, monkeypatch
    ):
        class HalfDead(FakeMainWindow):
            def show(self):
                raise RuntimeError("no window server")

        window = self._use(monkeypatch, HalfDead(visible=False))
        assert capture.ensure_viewport_realized() is None
        # Nothing was said, so nothing is owed: a later working call still
        # gets to ask rather than jumping straight to "did not take".
        good = self._use(monkeypatch, FakeMainWindow(visible=False))
        assert "asked Maya to show it" in self._call(good)


class TestTheFakesRefuseWhatMayaRefuses:
    """The regression barrier for the four fakes above (#799 round 2).

    Round 1 replaced their answers-anything fallbacks and asserted almost
    none of it: reverting the behavioural changes left the suite green,
    which is this ticket's own complaint - "a green suite proves nothing" -
    one level up. `FakeLensCmds.driven_plugs` and the refusal branch it
    gates were the clearest case: set by no test, read by no test.

    Each claim below is a contract point the fake it names actually models.
    """

    # -- FakeLensCmds ------------------------------------------------------
    def test_the_lens_fake_refuses_a_camera_nobody_made(self):
        fake = FakeLensCmds()
        with pytest.raises(RuntimeError, match="No object matches name"):
            capture.apply_framing_fov(fake, "nobodyMadeThisCam")
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.getAttr("camShape.coneAngle")

    def test_the_lens_fake_refuses_a_connection_fed_focal_length(self):
        """An animated focal length - a zoom - is a plug apply_framing_fov
        writes unguarded, and Maya refuses a static write to it. The branch
        that models this was reachable from no test at all."""
        fake = FakeLensCmds()
        fake.driven_plugs["camShape.focalLength"] = "camShape_focalLength_anim"
        with pytest.raises(RuntimeError, match="locked or connected"):
            capture.apply_framing_fov(fake, "cam")
        assert fake.attrs["camShape.focalLength"] == 35.0

    def test_the_lens_fake_refuses_a_locked_film_fit(self):
        # filmFit is written FIRST, so a locked one stops the helper before
        # it reads the aperture: nothing is half-applied.
        fake = FakeLensCmds()
        fake.driven_plugs["camShape.filmFit"] = "referenced-and-locked"
        with pytest.raises(RuntimeError, match="locked or connected"):
            capture.apply_framing_fov(fake, "cam")
        assert fake.sets == []

    def test_a_free_lens_still_takes_its_write(self):
        # The refusal must not become the answer to everything.
        fake = FakeLensCmds()
        focal = capture.apply_framing_fov(fake, "cam")
        assert fake.attrs["camShape.focalLength"] == pytest.approx(focal)

    # -- FakeIsolateCmds ---------------------------------------------------
    def test_the_isolate_fake_refuses_a_panel_that_is_not_there(self):
        # A torn-off viewport the user closed mid-capture: every
        # panel-taking method answered plausibly for it before #799.
        fake = FakeIsolateCmds()
        for call in (
            lambda: fake.isolateSelect("closedPanel", state=1),
            lambda: fake.modelEditor("closedPanel", query=True, viewSelected=True),
        ):
            with pytest.raises(RuntimeError, match="not found"):
                call()

    def test_the_isolate_fake_answers_only_for_a_real_view_selected_set(self):
        fake = FakeIsolateCmds(set_members=["|golem"])
        # The panel's own set answers - refusing this would be the strict
        # error, and _isolate_members asks exactly this question.
        assert fake.sets("panelXViewSelectedSet", query=True) == ["|golem"]
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.sets("someSetNobodyMade", query=True)

    # -- FakeCaptureCmds ---------------------------------------------------
    def test_the_capture_fake_refuses_every_query_about_a_ghost_node(self):
        fake = FakeCaptureCmds()
        ghost = "|nobodyMadeThis"
        for call in (
            lambda: fake.getAttr(ghost + ".translate"),
            lambda: fake.setAttr(ghost + ".translate", 0, 0, 0),
            lambda: fake.nodeType(ghost),
            lambda: fake.listRelatives(ghost, shapes=True),
            lambda: fake.select(ghost),
            lambda: fake.lookThru("modelPanel1", ghost),
            lambda: fake.viewFit(ghost),
            lambda: fake.delete(ghost),
            lambda: fake.exactWorldBoundingBox(ghost),
        ):
            with pytest.raises(RuntimeError, match="No object matches name"):
                call()

    def test_the_capture_fake_stops_answering_about_a_deleted_camera(self):
        fake = FakeCaptureCmds()
        transform, _shape = fake.camera()
        fake.delete(transform)
        assert fake.objExists(transform) is False
        for call in (
            lambda: fake.nodeType(transform),
            lambda: fake.getAttr("|" + transform + ".translate"),
            lambda: fake.listRelatives(transform, shapes=True),
        ):
            with pytest.raises(RuntimeError, match="No object matches name"):
                call()

    def test_the_capture_fake_refuses_a_panel_that_went_away(self):
        fake = FakeCaptureCmds()
        for call in (
            lambda: fake.modelPanel("tornOff", query=True, camera=True),
            lambda: fake.modelEditor("tornOff", query=True, grid=True),
            lambda: fake.isolateSelect("tornOff", state=1),
            lambda: fake.lookThru("tornOff", "|persp"),
            lambda: fake.setFocus("tornOff"),
        ):
            with pytest.raises(RuntimeError, match="not found"):
                call()

    def test_the_capture_fakes_ls_and_objexists_report_rather_than_raise(self):
        fake = FakeCaptureCmds()
        assert fake.ls("|nobodyMadeThis", long=True) == []
        assert fake.objExists("|nobodyMadeThis") is False
        assert fake.ls("persp", long=True) == ["|persp"]

    def test_the_capture_fake_answers_the_sentinel_for_an_empty_frame(self):
        # Maya's "nothing to measure" answer, measured on 2027: an INVERTED
        # box. A plausible unit box here is what let a camera be placed
        # 5.8e20 units out and the file stay green (#640).
        fake = FakeCaptureCmds()
        assert fake.exactWorldBoundingBox() == [1e20, 1e20, 1e20,
                                                -1e20, -1e20, -1e20]

    def test_the_capture_fake_records_undo_edits_and_focus_moves(self):
        fake = FakeCaptureCmds()
        fake.undoInfo(stateWithoutFlush=False)
        assert fake.undoInfo(query=True, state=True) is False
        fake.panel_types["scriptEditorPanel1"] = "scriptEditor"
        fake.setFocus("scriptEditorPanel1")
        assert fake.focus_panel == "scriptEditorPanel1"
        fake.select(["|persp"])
        assert fake.ls(selection=True) == ["|persp"]

    # -- FakeSceneCmds -----------------------------------------------------
    def test_the_scene_fake_refuses_a_shape_that_is_not_in_it(self):
        fake = FakeSceneCmds(DOME_SCENE)
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.nodeType("nobodyMadeThisShape")
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.exactWorldBoundingBox("nobodyMadeThisShape")

    def test_the_scene_fake_answers_the_sentinel_when_nothing_is_visible(self):
        fake = FakeSceneCmds(DOME_SCENE)
        for name in fake.shapes:
            fake.visible[name] = False
        assert fake.exactWorldBoundingBox(
            *fake.shapes, ignoreInvisible=True) == [1e20, 1e20, 1e20,
                                                   -1e20, -1e20, -1e20]


class TestTargetOnACurrentAngle:
    """#797 row 20: "current" frames nothing, so `target` is dropped.

    The current angle looks through the PANEL's own camera and leaves it
    exactly where the user left it - _capture_one never places a camera and
    never calls _scene_bbox on that branch. _scene_bbox is also the only
    existence check `target` ever gets, so a typo'd target on a current-only
    capture came back a SUCCESS: the caller believes they photographed
    |golem|chest and photographed whatever the panel happened to hold.
    """

    def _spy(self, monkeypatch, shot=None):
        seen = []

        def fake_capture_one(angle, *args, **kwargs):
            seen.append(angle)
            # _capture_one sets target_unframed on the "current" branch
            # only - every other angle really does frame on the target.
            extra = dict(shot or {}) if angle == "current" else {}
            return dict(extra, png_b64="x", camera_position=[0, 0, 0],
                        camera_rotation=[0, 0, 0], camera="|cam",
                        blank=False, blank_unmeasurable=None)

        monkeypatch.setattr(capture, "_capture_one", fake_capture_one)
        return seen

    def test_a_current_only_capture_refuses_target(self, monkeypatch):
        self._spy(monkeypatch)
        monkeypatch.setattr(
            capture, "ensure_viewport_realized",
            lambda: pytest.fail("the refusal must come first - showing the "
                                "window is a visible side effect"))
        with pytest.raises(HandlerError) as exc:
            capture.capture_viewport({"angles": ["current"],
                                      "target": ["|golem"]})
        message = str(exc.value)
        assert "does not use 'target'" in message, message
        assert "current" in message, message

    def test_isolate_is_not_refused_alongside_it(self, monkeypatch):
        """`isolate` HIDES, and hiding works on any angle - only framing is
        inapplicable to 'current'."""
        seen = self._spy(monkeypatch)
        capture.capture_viewport({"angles": ["current"],
                                  "isolate": ["|golem"]})
        assert seen == ["current"]

    def test_a_mixed_list_keeps_target_and_names_the_current_frame(
            self, monkeypatch):
        """`target` IS consumed by the other angles, so refusing the call
        would refuse a legitimate one. The current frame says it was not
        framed instead."""
        self._spy(monkeypatch, shot={"target_unframed": True})
        result = capture.capture_viewport(
            {"angles": ["current", "front"], "target": ["|golem|chest"]})
        notes = [w for w in result["warnings"] if "target" in w]
        assert len(notes) == 1, result["warnings"]
        assert "current" in notes[0]


class TestAnEmptyTurntableTargetIsRefused:
    """#797 row 26: `target=""` was read as "no target at all".

    `[str(target)] if target else None` - an empty string is falsey, so the
    call silently orbited the WHOLE SCENE (dome included) instead of the
    object the caller meant to name. The wrapper had no min_length, so an
    empty string reached the handler.
    """

    def test_it_refuses_before_anything_is_captured(self, monkeypatch):
        monkeypatch.setattr(
            capture, "_capture_one",
            lambda *a, **k: pytest.fail("orbited despite an empty target"))
        monkeypatch.setattr(
            capture, "ensure_viewport_realized",
            lambda: pytest.fail("the refusal must come first"))
        with pytest.raises(HandlerError) as exc:
            capture.capture_turntable({"target": ""})
        message = str(exc.value)
        assert "does not use 'target'" in message, message
        assert "empty" in message, message

    def test_omitting_it_still_frames_the_whole_scene(self, monkeypatch):
        seen = []

        def fake_capture_one(*args, **kwargs):
            seen.append(args[4])
            return {"png_b64": "x", "camera_position": [0, 0, 0],
                    "camera_rotation": [0, 0, 0], "camera": "|cam"}

        monkeypatch.setattr(capture, "_capture_one", fake_capture_one)
        capture.capture_turntable({"n_frames": 2})
        assert seen == [None, None]


class TestTheFallbackSaysWhatSizeItDrew:
    """#797 row 36: the M3dView fallback draws at the PANEL's size.

    playblast honours widthHeight; M3dView.readColorBuffer reads whatever
    the user's viewport happens to be. So a 768-px request could come back
    as a 412-px image with a success status and no field saying so - and
    the caller measures pixels off it.
    """

    def _shot(self, drawn):
        return {"png_b64": "ZmFrZQ==", "camera_position": [0, 0, 1],
                "camera_rotation": [0, 0, 0], "camera": "|cam",
                "blank": False, "blank_unmeasurable": None,
                "drawn_size": drawn}

    def test_a_smaller_frame_is_named_with_its_size(self, monkeypatch):
        monkeypatch.setattr(capture, "_capture_one",
                            lambda *a, **k: self._shot([412, 380]))
        result = capture.capture_viewport({"angles": ["front"],
                                           "resolution": 768})
        assert len(result["warnings"]) == 1, result["warnings"]
        note = result["warnings"][0]
        assert "412x380" in note and "768" in note, note

    def test_a_playblast_that_honoured_the_request_says_nothing(
            self, monkeypatch):
        monkeypatch.setattr(capture, "_capture_one",
                            lambda *a, **k: self._shot(None))
        result = capture.capture_viewport({"angles": ["front"],
                                           "resolution": 768})
        assert result["warnings"] == []

    def test_a_turntable_cell_names_it_too(self, monkeypatch):
        monkeypatch.setattr(capture, "_capture_one",
                            lambda *a, **k: self._shot([100, 100]))
        result = capture.capture_turntable({"n_frames": 2})
        assert len([w for w in result["warnings"] if "100x100" in w]) == 2


class TestVP2CannotDrawWhatWasAsked:
    """#797 row 38: flags VP2 accepts and then does nothing with.

    Warnings, not refusals: the VP2 behaviour is UNMEASURED (the plan says
    so), and the frame that comes back is still a frame - it just does not
    carry the thing the caller switched on. render_scene already reports
    `fallback_light` for the same class of surprise.
    """

    def _flat(self, monkeypatch, **shot):
        monkeypatch.setattr(
            capture, "_capture_one",
            lambda *a, **k: dict(
                {"png_b64": "x", "camera_position": [0, 0, 1],
                 "camera_rotation": [0, 0, 0], "camera": "|cam",
                 "blank": False, "blank_unmeasurable": None}, **shot))

    def test_shadows_under_a_wireframe_are_named(self, monkeypatch):
        self._flat(monkeypatch)
        result = capture.capture_viewport(
            {"angles": ["front"], "shading": "wireframe", "shadows": True})
        assert any("shadows" in w for w in result["warnings"]), result

    def test_shadows_under_flat_shading_are_named(self, monkeypatch):
        self._flat(monkeypatch)
        result = capture.capture_viewport(
            {"angles": ["front"], "shading": "flatShaded", "shadows": True})
        assert any("shadows" in w for w in result["warnings"]), result

    def test_shadows_on_a_shaded_frame_say_nothing(self, monkeypatch):
        self._flat(monkeypatch)
        result = capture.capture_viewport(
            {"angles": ["front"], "shading": "smoothShaded", "shadows": True})
        assert result["warnings"] == []

    def test_ssao_under_a_wireframe_is_named(self, monkeypatch):
        self._flat(monkeypatch)
        result = capture.capture_viewport(
            {"angles": ["front"], "shading": "wireframe", "buffer": "ssao"})
        assert any("ssao" in w for w in result["warnings"]), result

    def test_a_turntable_names_its_shadows_too(self, monkeypatch):
        self._flat(monkeypatch)
        result = capture.capture_turntable(
            {"n_frames": 2, "shading": "wireframe", "shadows": True})
        # once for the call, not once per cell
        assert len([w for w in result["warnings"] if "shadows" in w]) == 1

    def test_scene_lighting_with_no_light_is_named_once(self, monkeypatch):
        self._flat(monkeypatch, unlit=True)
        result = capture.capture_viewport(
            {"angles": ["front", "side"], "lighting": "scene"})
        notes = [w for w in result["warnings"] if "no light" in w]
        assert len(notes) == 1, result["warnings"]

    def test_a_lit_scene_says_nothing(self, monkeypatch):
        self._flat(monkeypatch, unlit=False)
        result = capture.capture_viewport(
            {"angles": ["front"], "lighting": "scene"})
        assert result["warnings"] == []

    def test_the_real_capture_asks_maya_whether_the_scene_is_lit(
            self, monkeypatch):
        """The `unlit` flag is measured inside _capture_one, where cmds
        exists - capture_viewport itself must stay Maya-free until the
        capture, so the row-20 refusal can fire headless."""
        fake = FakeCaptureCmds()
        monkeypatch.setattr(capture, "_cmds", lambda: fake)
        monkeypatch.setattr(capture, "_grab_pixels",
                            lambda *a, **k: (b"fakepng",
                                             {"blank": False,
                                              "unavailable_reason": None}))
        shot = capture._capture_one(
            "current", "smoothShaded", True, "beauty", None, False, 256,
            "scene", False)
        assert shot["unlit"] is True
        fake.lights.append("|key|keyShape")
        shot = capture._capture_one(
            "current", "smoothShaded", True, "beauty", None, False, 256,
            "scene", False)
        assert shot["unlit"] is False


class TestATypoTargetRefusesOnAMixedList:
    """#797 row 20, second half: the existence check on the current branch.

    The refusal itself is only worth anything if it runs against a real
    scene, so this drives `_capture_one` through FakeCaptureCmds rather
    than standing it in - the monkeypatched version in
    TestTargetOnACurrentAngle can only pin what the handler does with the
    shot it gets back.

    And the message has to name the key the CALLER typed: `_scene_bbox`
    called every list it was handed "isolate", so a mistyped `target` sent
    the caller looking at a param they never passed.
    """

    def _fake(self, monkeypatch):
        fake = FakeCaptureCmds()
        monkeypatch.setattr(capture, "_cmds", lambda: fake)
        monkeypatch.setattr(
            capture, "_grab_pixels",
            lambda *a, **k: (b"fakepng", {"blank": False,
                                          "unavailable_reason": None}))
        return fake

    def test_a_typo_target_refuses_naming_target(self, monkeypatch):
        self._fake(monkeypatch)
        with pytest.raises(HandlerError) as exc:
            capture.capture_viewport({"angles": ["current", "front"],
                                      "target": ["|nosuchthing"]})
        message = str(exc.value)
        assert "target objects not found" in message, message
        assert "nosuchthing" in message, message

    def test_a_typo_isolate_still_says_isolate(self, monkeypatch):
        self._fake(monkeypatch)
        with pytest.raises(HandlerError) as exc:
            capture.capture_viewport({"angles": ["current"],
                                      "isolate": ["|nosuchthing"]})
        assert "isolate objects not found" in str(exc.value)

    def test_a_real_target_gets_through_and_is_named_unframed(self,
                                                              monkeypatch):
        fake = self._fake(monkeypatch)
        fake.nodes["|golem"] = "|golem|golemShape"
        fake.node_types["|golem"] = "transform"
        fake.node_types["|golem|golemShape"] = "mesh"
        fake.geometry = ["|golem|golemShape"]
        fake.boxes["|golem"] = [-1.0, -1.0, -1.0, 1.0, 1.0, 1.0]
        result = capture.capture_viewport({"angles": ["current", "front"],
                                           "target": ["|golem"]})
        assert len(result["images"]) == 2
        notes = [w for w in result["warnings"] if "'target' did not frame" in w]
        assert len(notes) == 1, result["warnings"]
        assert notes[0].startswith("current"), notes[0]

    def test_the_current_branch_itself_checks_the_name(self, monkeypatch):
        """The decisive one: a MIXED list would refuse on its other angle
        anyway, so only calling the current branch on its own proves the
        check is there. Before #797 this capture SUCCEEDED - it photographed
        whatever the panel held and called it |nosuchthing."""
        self._fake(monkeypatch)
        with pytest.raises(HandlerError) as exc:
            capture._capture_one("current", "smoothShaded", True, "beauty",
                                 None, False, 256, "default", False,
                                 frame_on=["|nosuchthing"])
        assert "target objects not found" in str(exc.value)


# ----------------------------------------------------------------- #824


class TestOcclusionSamples:
    """The nine points a target's visibility is asked at: the bbox centre
    and its eight corners. Measured basis (#824): on the #823 K2 scene all
    nine rays from the back camera to |red's box hit |blue first, and the
    frame was 65536/65536 blue px; from the front none did."""

    def test_nine_points_centre_first(self):
        pts = capture.bbox_samples([-1, -2, -3], [1, 2, 3])
        assert len(pts) == 9
        assert pts[0] == (0.0, 0.0, 0.0)
        corners = set(pts[1:])
        assert corners == {(x, y, z) for x in (-1, 1) for y in (-2, 2)
                           for z in (-3, 3)}


class TestOcclusionWarning:
    """Pure text. Warning, never a refusal: the caller may WANT the context
    in shot, and a partial cover is a measurement, not a verdict."""

    def _occ(self, blocked, by=("blue",), samples=9):
        return {"targets": ["|red"], "blocked": blocked, "samples": samples,
                "by": list(by)}

    def test_fully_hidden_names_the_occluder_and_isolate(self):
        note = capture.occlusion_warning("back", self._occ(9))
        assert note is not None
        assert note.startswith("back:")
        assert "|red" in note and "blue" in note
        assert "all 9" in note
        assert "isolate" in note

    def test_partly_hidden_gives_the_count(self):
        note = capture.occlusion_warning("back", self._occ(5))
        assert "partly" in note
        assert "5 of 9" in note
        assert "blue" in note

    def test_nothing_in_the_way_says_nothing(self):
        assert capture.occlusion_warning("front", self._occ(0, by=())) is None

    def test_unmeasured_is_reported_not_hidden(self):
        """The blank_warnings discipline: "I did not check" must not look
        like "I checked and it is fine"."""
        note = capture.occlusion_warning(
            "back", {"targets": ["|red"], "unmeasurable": "no OpenMaya"})
        assert "could not be measured" in note
        assert "no OpenMaya" in note

    def test_no_occlusion_dict_means_no_target(self):
        assert capture.occlusion_warning("front", None) is None


class TestOccluderShapes:
    """Which meshes can hide the target: every visible mesh that is not
    the target's own, not an intermediate shape, and (under isolate) is
    actually shown. Each exclusion was measured on Maya 2027 (#824)."""

    def _cmds(self):
        cmds = FakeCaptureCmds()
        cmds.add_geometry("|red|redShape", box=(-0.5, -0.5, 0.7, 0.5, 0.5, 1.7))
        cmds.add_geometry("|blue|blueShape", box=(-0.5, -0.5, -1.7, 0.5, 0.5, -0.7))
        return cmds

    def test_the_other_mesh_is_an_occluder(self):
        cmds = self._cmds()
        assert capture.occluder_shapes(cmds, ["|red"], None) == ["|blue|blueShape"]

    def test_the_targets_own_shapes_never_are(self):
        """A grouped target: rays to a far bbox corner pass through the
        group's own near member, and the probe counted that as a block
        (4 of 9 from the back) until the group's shapes were excluded."""
        cmds = FakeCaptureCmds()
        cmds.add_geometry("|pair|a|aShape", box=(-1.5, -0.5, -0.5, -0.5, 0.5, 0.5))
        cmds.add_geometry("|pair|b|bShape", box=(0.5, -0.5, -0.5, 1.5, 0.5, 0.5))
        cmds.add_geometry("|wall|wallShape", box=(-2, -1, 1.9, 2, 1, 2.1))
        assert capture.occluder_shapes(cmds, ["|pair"], None) == ["|wall|wallShape"]

    def test_a_target_named_by_its_shape_is_excluded_too(self):
        cmds = self._cmds()
        assert capture.occluder_shapes(cmds, ["|red|redShape"], None) == ["|blue|blueShape"]

    def test_an_intermediate_shape_is_not_an_occluder(self):
        """MEASURED: ls(geometry=True, visible=True) lists a skinned mesh's
        ShapeOrig next to the drawn shape. It draws nothing."""
        cmds = self._cmds()
        cmds.add_geometry("|skinned|skinnedShape", box=(2, -0.5, -0.5, 3, 0.5, 0.5))
        cmds.add_geometry("|skinned|skinnedShapeOrig", intermediate=True,
                          box=(2, -0.5, -0.5, 3, 0.5, 0.5))
        assert capture.occluder_shapes(cmds, ["|red"], None) == [
            "|blue|blueShape", "|skinned|skinnedShape"]

    def test_only_meshes_count(self):
        """closestIntersection is a mesh call; a nurbs surface or a light
        cannot be asked and must not fail the capture."""
        cmds = self._cmds()
        cmds.add_geometry("|dome|domeShape", "aiSkyDomeLight",
                          box=(-1000, -1000, -1000, 1000, 1000, 1000))
        cmds.add_geometry("|patch|patchShape", "nurbsSurface")
        assert capture.occluder_shapes(cmds, ["|red"], None) == ["|blue|blueShape"]

    def test_isolate_limits_occluders_to_what_is_shown(self):
        """MEASURED: isolate=[red] + target red from the back draws 14884
        red px - the blue cube is hidden, so it cannot occlude."""
        cmds = self._cmds()
        assert capture.occluder_shapes(cmds, ["|red"], ["|red"]) == []
        assert capture.occluder_shapes(cmds, ["|red"], ["|red", "|blue"]) == [
            "|blue|blueShape"]


class TestCaptureOneMeasuresOcclusion:
    """_capture_one asks the rays AFTER viewFit, from where the camera
    actually is, and only when a target was named on a placing angle."""

    def _fake(self, monkeypatch, blocked_by=None, raise_with=None):
        cmds = FakeCaptureCmds()
        cmds.add_geometry("|red|redShape", box=(-0.5, -0.5, 0.7, 0.5, 0.5, 1.7))
        cmds.add_geometry("|blue|blueShape", box=(-0.5, -0.5, -1.7, 0.5, 0.5, -0.7))
        monkeypatch.setattr(capture, "_cmds", lambda: cmds)
        monkeypatch.setattr(
            capture, "_grab_pixels",
            lambda *a, **k: (b"fakepng", {"blank": False,
                                          "unavailable_reason": None}))
        rays = []

        def fake_blocked(camera_position, samples, shapes, tolerance=None):
            rays.append({"camera": tuple(camera_position), "samples": list(samples),
                         "shapes": list(shapes)})
            if raise_with is not None:
                raise raise_with
            return [blocked_by] * len(samples) if blocked_by else [None] * len(samples)

        monkeypatch.setattr(capture, "blocked_samples", fake_blocked)
        return cmds, rays

    def test_a_target_on_a_placing_angle_is_measured_from_the_camera(
            self, monkeypatch):
        cmds, rays = self._fake(monkeypatch, blocked_by="|blue|blueShape")
        shot = capture._capture_one(
            "back", "smoothShaded", True, "beauty", None, True, 256,
            frame_on=["|red"])
        assert len(rays) == 1
        assert rays[0]["shapes"] == ["|blue|blueShape"]
        assert len(rays[0]["samples"]) == 9
        assert rays[0]["camera"] == tuple(shot["camera_position"])
        assert shot["occlusion"] == {
            "targets": ["|red"], "blocked": 9, "samples": 9, "by": ["blue"]}

    def test_nothing_in_the_way_is_zero_blocked(self, monkeypatch):
        cmds, rays = self._fake(monkeypatch)
        shot = capture._capture_one(
            "front", "smoothShaded", True, "beauty", None, True, 256,
            frame_on=["|red"])
        assert shot["occlusion"]["blocked"] == 0
        assert shot["occlusion"]["by"] == []

    def test_no_target_asks_no_rays(self, monkeypatch):
        cmds, rays = self._fake(monkeypatch, blocked_by="|blue|blueShape")
        shot = capture._capture_one(
            "back", "smoothShaded", True, "beauty", None, True, 256)
        assert rays == []
        assert shot["occlusion"] is None

    def test_isolate_alone_asks_no_rays(self, monkeypatch):
        """isolate hides the rest; nothing else is left to hide behind."""
        cmds, rays = self._fake(monkeypatch, blocked_by="|blue|blueShape")
        shot = capture._capture_one(
            "back", "smoothShaded", True, "beauty", ["|red"], True, 256)
        assert rays == []
        assert shot["occlusion"] is None

    def test_the_current_angle_asks_no_rays(self, monkeypatch):
        cmds, rays = self._fake(monkeypatch, blocked_by="|blue|blueShape")
        shot = capture._capture_one(
            "current", "smoothShaded", True, "beauty", None, True, 256,
            frame_on=["|red"])
        assert rays == []
        assert shot["occlusion"] is None

    def test_a_failed_measurement_is_reported_not_swallowed(self, monkeypatch):
        cmds, rays = self._fake(monkeypatch, raise_with=RuntimeError("no api"))
        shot = capture._capture_one(
            "back", "smoothShaded", True, "beauty", None, True, 256,
            frame_on=["|red"])
        assert shot["occlusion"]["unmeasurable"] == "RuntimeError: no api"
        assert shot["png_b64"], "the frame itself still comes back"


class TestCaptureViewportSaysTheTargetIsHidden:
    """End to end through capture_viewport's marshaling: the per-frame
    occlusion dict becomes a warning naming the angle."""

    def _spy(self, monkeypatch, occlusion):
        def fake_capture_one(angle, *args, **kwargs):
            return dict(png_b64="x", camera_position=[0, 0, 0],
                        camera_rotation=[0, 0, 0], camera="|cam",
                        blank=False, blank_unmeasurable=None,
                        occlusion=occlusion if angle == "back" else None)

        monkeypatch.setattr(capture, "_capture_one", fake_capture_one)

    def test_a_hidden_target_is_warned_per_angle(self, monkeypatch):
        self._spy(monkeypatch, {"targets": ["|red"], "blocked": 9,
                                "samples": 9, "by": ["blue"]})
        result = capture.capture_viewport(
            {"angles": ["front", "back"], "target": ["|red"]})
        notes = [w for w in result["warnings"] if "hidden behind" in w]
        assert len(notes) == 1, result["warnings"]
        assert notes[0].startswith("back:")
        assert "blue" in notes[0]

    def test_a_visible_target_adds_no_warning(self, monkeypatch):
        self._spy(monkeypatch, {"targets": ["|red"], "blocked": 0,
                                "samples": 9, "by": []})
        result = capture.capture_viewport(
            {"angles": ["back"], "target": ["|red"]})
        assert not [w for w in result["warnings"] if "hidden" in w]


class TestIsolateBlankIsToldApartFromAnEmptyScene:
    """A blank ISOLATE frame has two very different causes (#825).

    Either the scene really is empty / unframed, or the isolate view itself
    drew nothing while the same camera would have drawn the scene fine -
    which is what #825 records on some agent-launched Mayas. The old message
    listed both as possibilities and left the caller to guess. A capture's
    contract is that it does not lie about what it saw, and "I checked, and
    it was the isolate view" is a different answer from "it might be one of
    these two things".
    """

    def _shot(self, isolate_view_failed):
        return {"png_b64": "ZmFrZQ==", "camera_position": [0, 0, 10],
                "camera_rotation": [0, 0, 0], "camera": "|cam",
                "blank": True, "blank_unmeasurable": None,
                "isolate_view_failed": isolate_view_failed}

    def test_the_isolate_view_is_named_when_the_control_drew(self, monkeypatch):
        monkeypatch.setattr(capture, "_capture_one",
                            lambda *a, **k: self._shot(True))
        result = capture.capture_viewport(
            {"angles": ["front"], "isolate": ["|red"]})
        note = " ".join(result["warnings"])
        assert "825" in note
        assert "isolate" in note.lower()
        # and it must NOT go on guessing about the two causes it ruled out
        assert "may be empty" not in note

    def test_an_empty_scene_is_still_called_an_empty_scene(self, monkeypatch):
        monkeypatch.setattr(capture, "_capture_one",
                            lambda *a, **k: self._shot(False))
        result = capture.capture_viewport(
            {"angles": ["front"], "isolate": ["|red"]})
        note = " ".join(result["warnings"])
        assert "825" not in note
        assert "empty" in note.lower()

    def test_an_unmeasured_control_keeps_the_old_honest_hedge(self, monkeypatch):
        monkeypatch.setattr(capture, "_capture_one",
                            lambda *a, **k: self._shot(None))
        result = capture.capture_viewport({"angles": ["front"]})
        note = " ".join(result["warnings"])
        assert "BLANK" in note
        assert "825" not in note


class TestAFrameWithUnboundShadersSaysSo:
    """#830: the capture flushes a draw so this should not happen - but a
    mitigation is not a proof, and the failure it prevents is a picture that
    lies with a plain success: real geometry, real opaque pixels, the wrong
    material. Measured live: a bad frame is 76-83% exactly RGB 0,208,57."""

    def _shot(self, rgb, share):
        return {"png_b64": "ZmFrZQ==", "camera_position": [0, 0, 1],
                "camera_rotation": [0, 0, 0], "camera": "|cam", "blank": False,
                "blank_unmeasurable": None,
                "dominant": {"top_rgb": rgb, "top_share": share,
                             "sampled": 900, "unavailable_reason": None}}

    def test_a_frame_full_of_the_placeholder_is_named(self):
        notes = capture.unbound_shader_warnings(self._shot([0, 208, 57], 0.83),
                                                "front")
        assert len(notes) == 1
        assert "front is 83%" in notes[0]
        assert "unassigned-shader green" in notes[0]
        assert "#830" in notes[0]

    def test_it_offers_the_innocent_reading_too(self):
        # A material really can be that green. The note must not accuse.
        note = capture.unbound_shader_warnings(self._shot([0, 208, 57], 0.83),
                                               "front")[0]
        assert "material really is that flat green" in note
        assert "again" in note

    def test_a_correctly_shaded_frame_says_nothing(self):
        assert capture.unbound_shader_warnings(
            self._shot([189, 0, 17], 0.7), "front") == []

    def test_a_trace_of_that_green_is_not_worth_a_warning(self):
        # A small green object in an otherwise correct frame.
        assert capture.unbound_shader_warnings(
            self._shot([0, 208, 57], 0.04), "front") == []

    def test_an_unmeasurable_frame_is_not_accused(self):
        shot = self._shot(None, None)
        shot["dominant"]["unavailable_reason"] = "no file"
        assert capture.unbound_shader_warnings(shot, "front") == []
        assert capture.unbound_shader_warnings({"blank": False}, "front") == []

    def test_both_capture_paths_carry_the_note(self, monkeypatch):
        monkeypatch.setattr(capture, "ensure_viewport_realized", lambda: None)
        monkeypatch.setattr(
            capture, "_capture_one",
            lambda *a, **k: self._shot([0, 208, 57], 0.8))
        viewport = capture.capture_viewport({"angles": ["front"]})
        assert any("unassigned-shader green" in w
                   for w in viewport["warnings"])
        turn = capture.capture_turntable({"n_frames": 2})
        assert sum(1 for w in turn["warnings"]
                   if "unassigned-shader green" in w) == 2


# --- redmine #837: the viewport eye encodes like the render eye ------------
# Measured on Maya 2027: the offscreen playblast took the panel's view
# transform, ACES 1.0 SDR-video, which read a linear-0.5 plane as 165 and a
# 0.028 plane as 17 where render_scene (Un-tone-mapped sRGB, #615) said 188
# and 47. The capture now sets the render's transform on the panel it draws
# with, for the grab only, and says so in the result.


def _capture_fake_with_view_transform(view="ACES 1.0 SDR-video (sRGB)"):
    fake = FakeCaptureCmds()
    fake.cm_prefs["viewTransformName"] = view
    fake.editor_state["cmEnabled"] = True
    return fake


def test_capture_sets_the_display_transform_for_the_grab_and_restores_it(monkeypatch):
    fake = _capture_fake_with_view_transform()
    monkeypatch.setattr(capture, "_cmds", lambda: fake)
    seen_at_grab = {}

    def grab(cmds, panel, resolution):
        seen_at_grab["view"] = fake.cm_prefs["viewTransformName"]
        seen_at_grab["cm"] = fake.editor_state["cmEnabled"]
        return b"fakepng", {"blank": False, "unavailable_reason": None}

    monkeypatch.setattr(capture, "_grab_pixels", grab)
    result = capture.capture_viewport({"angles": ["front"]})
    assert seen_at_grab == {"view": capture.DISPLAY_TRANSFORM, "cm": True}
    # restored to what the user had, like every other panel setting
    assert fake.cm_prefs["viewTransformName"] == "ACES 1.0 SDR-video (sRGB)"
    assert result["display_transform"] == capture.DISPLAY_TRANSFORM
    assert all(img["display_transform"] == capture.DISPLAY_TRANSFORM
               for img in result["images"])
    assert not [w for w in result["warnings"] if "transform" in w]


def test_capture_turns_colour_management_on_for_the_grab(monkeypatch):
    # cmEnabled off means NO transform: the frame is raw linear, 127 for a
    # 0.5 albedo. The grab must not depend on the user's preference.
    fake = _capture_fake_with_view_transform()
    fake.editor_state["cmEnabled"] = False
    monkeypatch.setattr(capture, "_cmds", lambda: fake)
    seen = {}
    monkeypatch.setattr(capture, "_grab_pixels", lambda c, p, r: (
        seen.setdefault("cm", fake.editor_state["cmEnabled"]) and None
        or (b"fakepng", {"blank": False, "unavailable_reason": None})))
    capture.capture_viewport({"angles": ["front"]})
    assert seen["cm"] is True
    assert fake.editor_state["cmEnabled"] is False  # restored


def test_capture_reports_the_transform_it_could_not_set(monkeypatch):
    # A Maya whose modelEditor has no viewTransformName flag (or refuses it)
    # draws with whatever it has. The result must say which, not claim the
    # render's transform, and warn - the caller's two eyes then disagree.
    fake = FakeCaptureCmds()

    def refused(**kw):
        raise RuntimeError("colorManagementPrefs: ")

    fake.colorManagementPrefs = refused
    monkeypatch.setattr(capture, "_cmds", lambda: fake)
    monkeypatch.setattr(capture, "_grab_pixels", lambda *a, **k: (
        b"fakepng", {"blank": False, "unavailable_reason": None}))
    result = capture.capture_viewport({"angles": ["front"]})
    assert result["display_transform"] is None
    assert any("transform" in w and "could not" in w for w in result["warnings"]), result["warnings"]


def test_turntable_carries_the_display_transform_too(monkeypatch):
    fake = _capture_fake_with_view_transform()
    monkeypatch.setattr(capture, "_cmds", lambda: fake)
    monkeypatch.setattr(capture, "_grab_pixels", lambda *a, **k: (
        b"fakepng", {"blank": False, "unavailable_reason": None}))
    result = capture.capture_turntable({"n_frames": 2})
    assert result["display_transform"] == capture.DISPLAY_TRANSFORM
    assert fake.cm_prefs["viewTransformName"] == "ACES 1.0 SDR-video (sRGB)"


def test_render_and_capture_share_one_display_transform():
    from maya_plugin.handlers import render
    assert render.DISPLAY_TRANSFORM == capture.DISPLAY_TRANSFORM == "Un-tone-mapped (sRGB)"


class TestSsaoReadsAsContact:
    """#832: buffer='ssao' switched VP2's ambient occlusion on and left its
    settings at Maya's defaults - amount 1.0, radius 16 px - which darken a
    contact by at most 40/255 in a 16-px band (MEASURED on a cube, a cylinder
    and a sphere on a floor, evals/capture_params_probe_832). A fresh agent
    used the buffer to look for gaps at a lamp's joints and saw no crevice
    darkening at all. Amount 2.0 with a radius of 1/24 of the frame (32 px at
    768) darkens the same contacts by 147/255 and leaves open floor untouched;
    the radius is in PIXELS (radius 32 at 384 px covers what 64 covers at
    768), so it follows the frame. Every setting the frame changes is put
    back."""

    DEFAULTS = {"ssaoEnable": False, "ssaoAmount": 1.0, "ssaoRadius": 16,
                "ssaoFilterRadius": 16, "ssaoSamples": 16}

    def _fake(self, monkeypatch, **vp2):
        fake = FakeCaptureCmds()
        fake.vp2.update(vp2)
        monkeypatch.setattr(capture, "_cmds", lambda: fake)
        seen = []

        def grab(*a, **k):
            seen.append(dict(fake.vp2))
            return (b"fakepng", {"blank": False, "unavailable_reason": None})

        monkeypatch.setattr(capture, "_grab_pixels", grab)
        return fake, seen

    def test_ssao_sets_what_shows_contact_for_the_frame_and_puts_it_back(self, monkeypatch):
        fake, seen = self._fake(monkeypatch)
        capture.capture_viewport({"angles": ["front"], "buffer": "ssao", "resolution": 768})
        assert seen == [{"ssaoEnable": True, "ssaoAmount": 2.0, "ssaoRadius": 32,
                         "ssaoFilterRadius": 16, "ssaoSamples": 32}], seen
        assert fake.vp2 == self.DEFAULTS

    def test_the_radius_follows_the_frame(self, monkeypatch):
        fake, seen = self._fake(monkeypatch)
        capture.capture_viewport({"angles": ["front"], "buffer": "ssao", "resolution": 384})
        capture.capture_viewport({"angles": ["front"], "buffer": "ssao", "resolution": 1024})
        assert [(s["ssaoRadius"], s["ssaoFilterRadius"]) for s in seen] == [(16, 8), (42, 21)]
        assert capture.ssao_settings(64) == {
            "ssaoAmount": 2.0, "ssaoRadius": 8, "ssaoFilterRadius": 4, "ssaoSamples": 32}

    def test_beauty_leaves_every_setting_alone(self, monkeypatch):
        fake, seen = self._fake(monkeypatch, ssaoAmount=3.0, ssaoRadius=64)
        capture.capture_viewport({"angles": ["front"], "buffer": "beauty"})
        assert seen == [dict(self.DEFAULTS, ssaoAmount=3.0, ssaoRadius=64)]
        assert fake.vp2 == dict(self.DEFAULTS, ssaoAmount=3.0, ssaoRadius=64)

    def test_a_user_who_had_their_own_settings_gets_them_back(self, monkeypatch):
        theirs = dict(ssaoEnable=True, ssaoAmount=3.0, ssaoRadius=64, ssaoFilterRadius=8, ssaoSamples=24)
        fake, seen = self._fake(monkeypatch, **theirs)
        capture.capture_viewport({"angles": ["front", "side"], "buffer": "ssao"})
        assert all(s["ssaoAmount"] == 2.0 for s in seen)
        assert fake.vp2 == theirs

    def test_restored_even_when_the_frame_raises(self, monkeypatch):
        fake, _ = self._fake(monkeypatch)
        monkeypatch.setattr(capture, "_grab_pixels",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        with pytest.raises(RuntimeError):
            capture.capture_viewport({"angles": ["front"], "buffer": "ssao"})
        assert fake.vp2 == self.DEFAULTS

    def test_the_result_names_the_settings_once(self, monkeypatch):
        self._fake(monkeypatch)
        result = capture.capture_viewport(
            {"angles": ["front", "side"], "buffer": "ssao", "resolution": 768})
        notes = [w for w in result["warnings"] if "ssao" in w]
        assert len(notes) == 1, result["warnings"]
        assert "amount 2.0" in notes[0] and "radius 32 px" in notes[0], notes
        assert result["ssao"] == {"ssaoAmount": 2.0, "ssaoRadius": 32,
                                  "ssaoFilterRadius": 16, "ssaoSamples": 32}

    def test_beauty_says_nothing_about_ssao(self, monkeypatch):
        self._fake(monkeypatch)
        result = capture.capture_viewport({"angles": ["front"]})
        assert not any("ssao" in w for w in result["warnings"])
        assert result.get("ssao") is None

    def test_the_fake_refuses_an_amount_maya_refuses(self):
        # Maya 2027: "setAttr: Cannot set the attribute
        # 'hardwareRenderingGlobals.ssaoAmount' past its maximum value of 3."
        fake = FakeCaptureCmds()
        with pytest.raises(RuntimeError):
            fake.setAttr("hardwareRenderingGlobals.ssaoAmount", 4.0)
        with pytest.raises(RuntimeError):
            fake.getAttr("hardwareRenderingGlobals.noSuchThing")
