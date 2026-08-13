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


class FakeIsolateCmds:
    """Minimal cmds stub for the isolate path: isolateSelect + view-selected set.

    editor()/selectionConnection() raise — the isolate path must never touch
    the mainListConnection machinery (locking it breaks VP2 shading-group
    resolution for per-face/groupId bindings; redmine #575).
    """

    def __init__(self, set_members=None, view_selected=False):
        self.calls = []
        self.set_members = list(set_members or [])
        self.view_selected = view_selected

    def isolateSelect(self, panel, **kw):
        self.calls.append(("isolateSelect", panel, kw))
        if kw.get("state") is not None:
            self.view_selected = bool(kw["state"])
        if "addDagObject" in kw:
            self.set_members.append(kw["addDagObject"])
        if "removeDagObject" in kw:
            self.set_members.remove(kw["removeDagObject"])

    def modelEditor(self, panel, **kw):
        self.calls.append(("modelEditor", panel, kw))
        if kw.get("query"):
            if kw.get("viewObjects"):
                return "%sViewSelectedSet" % panel
            if kw.get("viewSelected"):
                return self.view_selected
        return None

    def sets(self, name, **kw):
        self.calls.append(("sets", name, kw))
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

        def getAttr(self, attr):
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
                         frame_all, resolution, lighting, shadows):
            calls.append((angle, shading, wireframe_overlay, buffer, isolate,
                          frame_all, resolution, lighting, shadows))
            return {"png_b64": "ZmFrZQ==", "camera_position": [0, 0, 10],
                    "camera_rotation": [0, 0, 0], "camera": "|mayaMcpTempCam"}

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
    monkeypatch.setattr(capture, "_grab_pixels", lambda *a, **k: b"fakepng")

    capture.capture_viewport({
        "angles": ["front"], "lighting": "scene", "shadows": True,
    })

    applied = [c for c in fake.calls if c[0] == "modelEditor" and c[2].get("edit")]
    assert any(c[2].get("displayLights") == "all" for c in applied), applied
    assert any(c[2].get("shadows") is True for c in applied), applied
    # restored to what it was before the capture
    assert fake.editor_state["displayLights"] == "default"
    assert fake.editor_state["shadows"] is False


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
    """

    def __init__(self):
        self.calls = []
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
        }
        self.ssao = False
        self.active_camera = "persp"  # panel's current camera (not cmds.camera(), below)
        self.focus_panel = "modelPanel1"
        self._create_seq = 0
        self.renamed = []
        self.deleted = []
        self.existing_names = set()
        # When set, cmds.ls(<this name>, long=True) reports TWO matches
        # instead of one - reproduces a scene with a stray node sharing the
        # temp camera's short name, without require_object being involved
        # (capture.py's cosmetic `camera` field must never raise on this).
        self.ambiguous_name = None

    def getPanel(self, **kw):
        if kw.get("withFocus"):
            return self.focus_panel
        if kw.get("typeOf") == self.focus_panel:
            return "modelPanel"
        if kw.get("type") == "modelPanel":
            return [self.focus_panel]
        if kw.get("visiblePanels"):
            return [self.focus_panel]
        return None

    def modelPanel(self, panel, **kw):
        if kw.get("query") and kw.get("camera"):
            return self.active_camera
        return None

    def modelEditor(self, panel, **kw):
        self.calls.append(("modelEditor", panel, dict(kw)))
        if kw.get("query"):
            if kw.get("viewSelected"):
                return False
            if kw.get("viewObjects"):
                return ""
            for flag, value in self.editor_state.items():
                if kw.get(flag):
                    return value
            return None
        for flag, value in kw.items():
            if flag in self.editor_state:
                self.editor_state[flag] = value
        return None

    def undoInfo(self, **kw):
        return True if kw.get("query") else None

    def getAttr(self, attr):
        if attr == "hardwareRenderingGlobals.ssaoEnable":
            return self.ssao
        return [(0.0, 0.0, 0.0)]  # .translate / .rotate

    def setAttr(self, attr, *args, **kw):
        if attr == "hardwareRenderingGlobals.ssaoEnable":
            self.ssao = args[0]
        return None

    def ls(self, *args, **kw):
        if args and kw.get("long"):
            name = str(args[0]).lstrip("|")
            if self.ambiguous_name and name == self.ambiguous_name:
                return ["|dupA|%s" % name, "|dupB|%s" % name]
            return ["|%s" % name]
        if kw.get("geometry"):
            return []
        return []

    def select(self, *a, **kw):
        return None

    def lookThru(self, *a, **kw):
        return None

    def setFocus(self, *a, **kw):
        return None

    def objExists(self, name):
        return str(name).lstrip("|") in self.existing_names

    def camera(self, **kw):
        # Deliberately ignores kw["name"] - matches the live Maya quirk
        # set_camera already works around (viewport.py); capture.py's temp
        # camera must use the same create-then-rename idiom.
        self._create_seq += 1
        transform = "camera%d" % self._create_seq
        shape = "camera%dShape" % self._create_seq
        return [transform, shape]

    def rename(self, node, new_name):
        self.renamed.append((node, new_name))
        return new_name

    def viewFit(self, *a, **kw):
        return None

    def delete(self, *a, **kw):
        self.deleted.extend(a)
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
        monkeypatch.setattr(capture, "_grab_pixels", lambda *a, **k: b"fakepng")

        capture._capture_one(
            "current", "smoothShaded", True, "beauty", None, True, 256
        )

        edit_calls = [
            c[2] for c in cmds.calls
            if not c[2].get("query") and "lights" in c[2]
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
        monkeypatch.setattr(capture, "_grab_pixels", lambda *a, **k: b"fakepng")

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
        monkeypatch.setattr(capture, "_grab_pixels", lambda *a, **k: b"fakepng")

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
        monkeypatch.setattr(capture, "_grab_pixels", lambda *a, **k: b"fakepng")

        shot = capture._capture_one(
            "front", "smoothShaded", True, "beauty", None, True, 256
        )

        assert shot["png_b64"]  # the capture succeeded end to end
        assert shot["camera"] == "|dupA|mayaMcpTempCam"  # first match, no raise
