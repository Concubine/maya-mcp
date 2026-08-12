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
