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
        monkeypatch.setattr(capture, "_grab_pixels", lambda *a, **k: (b"fakepng", {"blank": False, "unavailable_reason": None}))

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
        return self.shapes[name][0]

    def getClassification(self, node_type, satisfies=None):
        if node_type in self.unknown_classification:
            raise RuntimeError("unknown node type")
        assert satisfies == "light"
        return ["drawdb/light:light"] if node_type in self.LIGHT_TYPES else []

    def objExists(self, name):
        return name in self.shapes

    def exactWorldBoundingBox(self, *names, **kwargs):
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
