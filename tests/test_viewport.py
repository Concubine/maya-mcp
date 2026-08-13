import math

import pytest

from maya_plugin.dispatcher import HandlerError
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
    with pytest.raises(HandlerError):
        viewport.look_at_rotation([1, 2, 3], [1, 2, 3])


# ------------------------------------------------------- fake-cmds orchestration


class FakeCmds:
    """cmds surface for driving set_viewport/set_camera headless.

    Node registry keyed by canonical long name; `_resolve` matches a bare
    short name against any registered node's tail, same ambiguity-prone shape
    real `cmds.ls`/`cmds.objExists` have. Two deliberate quirks mirror real
    Maya behavior this handler works around (see viewport.py's comments), so
    a regression in either fix makes the corresponding test fail rather than
    silently pass:
      - `modelPanel(camera=True)` returns a bare SHORT name even though the
        camera is registered under a long one.
      - `camera(**kw)` ignores any `name=` kwarg entirely (ships back
        "camera<N>"/"camera<N>Shape"), matching the live-verified Maya quirk
        that `cmds.camera(name=...)` does not rename the transform.
    """

    def __init__(self):
        self.calls = []
        self.panel = "modelPanel4"
        self.node_type = {}
        self.shape_of = {}
        self.translate = {}
        self.rotate = {}
        self.attrs = {}
        self.panel_camera_short = "bkCam"
        self._register("|bkCam", "camera", shape="|bkCam|bkCamShape")
        self.translate["|bkCam"] = [0.0, 0.0, 5.0]
        self.rotate["|bkCam"] = [0.0, 0.0, 0.0]
        self.attrs["|bkCam|bkCamShape.focalLength"] = 35.0
        self.editor_flags = dict.fromkeys(
            ["grid", "lights", "cameras", "locators", "manipulators", "textures",
             "wireframeOnShaded"],
            True,
        )
        self.display_lights = "default"
        self._create_seq = 0

    def _register(self, long_name, node_type, shape=None, shape_type=None):
        self.node_type[long_name] = node_type
        if shape:
            self.node_type[shape] = shape_type or node_type
            self.shape_of[long_name] = shape

    def _resolve(self, name):
        if name in self.node_type:
            return name
        short = str(name).lstrip("|")
        for long_name in self.node_type:
            if long_name.rsplit("|", 1)[-1] == short:
                return long_name
        return None

    # -- panel discovery (used by _find_model_panel, imported from capture) --
    def getPanel(self, **kw):
        if kw.get("withFocus"):
            return self.panel
        if kw.get("typeOf") == self.panel:
            return "modelPanel"
        if kw.get("type") == "modelPanel":
            return [self.panel]
        if kw.get("visiblePanels"):
            return [self.panel]
        return None

    def modelPanel(self, panel, **kw):
        if kw.get("query") and kw.get("camera"):
            return self.panel_camera_short
        return None

    def modelEditor(self, panel, **kw):
        self.calls.append(dict(kw))
        if kw.get("query"):
            if "displayLights" in kw:
                return self.display_lights
            for flag, wanted in kw.items():
                if flag == "query" or not wanted:
                    continue
                return self.editor_flags.get(flag)
            return None
        for flag, value in kw.items():
            if flag == "edit":
                continue
            if flag == "displayLights":
                self.display_lights = value
            else:
                self.editor_flags[flag] = value
        return None

    # -- naming --
    def objExists(self, name):
        return self._resolve(name) is not None

    def ls(self, *args, **kw):
        if not args:
            return []
        resolved = self._resolve(args[0])
        if resolved is None:
            return []
        return [resolved] if kw.get("long") else [args[0]]

    def listRelatives(self, node, **kw):
        resolved = self._resolve(node)
        shape = self.shape_of.get(resolved)
        return [shape] if shape else []

    def nodeType(self, node):
        return self.node_type.get(self._resolve(node))

    def camera(self, **kw):
        # Deliberately ignores kw["name"] - matches the live Maya quirk.
        self._create_seq += 1
        transform, shape = "camera%d" % self._create_seq, "camera%dShape" % self._create_seq
        long_t, long_s = "|%s" % transform, "|%s" % shape
        self._register(long_t, "camera", shape=long_s)
        self.translate[long_t] = [0.0, 0.0, 0.0]
        self.rotate[long_t] = [0.0, 0.0, 0.0]
        self.attrs["%s.focalLength" % long_s] = 35.0
        return [transform, shape]

    def rename(self, node, new_name):
        resolved = self._resolve(node)
        node_type = self.node_type.pop(resolved)
        old_shape = self.shape_of.pop(resolved, None)
        new_long = "|%s" % str(new_name).lstrip("|")
        self.node_type[new_long] = node_type
        if resolved in self.translate:
            self.translate[new_long] = self.translate.pop(resolved)
        if resolved in self.rotate:
            self.rotate[new_long] = self.rotate.pop(resolved)
        if old_shape:
            shape_type = self.node_type.pop(old_shape, node_type)
            new_shape = "%s|%sShape" % (new_long, str(new_name).lstrip("|"))
            self.node_type[new_shape] = shape_type
            for key in list(self.attrs):
                if key.startswith(old_shape + "."):
                    self.attrs[new_shape + key[len(old_shape):]] = self.attrs.pop(key)
            self.shape_of[new_long] = new_shape
        return new_long

    def xform(self, node, **kw):
        resolved = self._resolve(node)
        if kw.get("query"):
            if kw.get("translation"):
                return list(self.translate.get(resolved, [0.0, 0.0, 0.0]))
            if kw.get("rotation"):
                return list(self.rotate.get(resolved, [0.0, 0.0, 0.0]))
            return None
        if "translation" in kw:
            self.translate[resolved] = [float(v) for v in kw["translation"]]
        if "rotation" in kw:
            self.rotate[resolved] = [float(v) for v in kw["rotation"]]
        return None

    def setAttr(self, attr, value, **kw):
        self.attrs[attr] = value

    def getAttr(self, attr):
        return self.attrs.get(attr)

    def lookThru(self, panel, cam):
        self.calls.append(("lookThru", panel, cam))


@pytest.fixture
def fake_cmds(monkeypatch):
    cmds = FakeCmds()
    monkeypatch.setattr(viewport, "_cmds", lambda: cmds)
    return cmds


class TestSetViewport:
    def test_editor_flags_edited_and_full_state_reflects_them(self, fake_cmds):
        result = viewport.set_viewport(
            {"show_grid": False, "show_light_icons": False, "wireframe_on_shaded": True}
        )
        assert fake_cmds.editor_flags["grid"] is False
        assert fake_cmds.editor_flags["lights"] is False
        assert fake_cmds.editor_flags["wireframeOnShaded"] is True
        assert result["show_grid"] is False
        assert result["show_light_icons"] is False
        assert result["wireframe_on_shaded"] is True
        assert result["panel"] == fake_cmds.panel

    def test_no_params_is_a_pure_state_query_with_no_edit_call(self, fake_cmds):
        viewport.set_viewport({})
        assert all(kw.get("query") for kw in fake_cmds.calls)

    def test_display_lights_valid_value_applied_and_returned(self, fake_cmds):
        result = viewport.set_viewport({"display_lights": "none"})
        assert fake_cmds.display_lights == "none"
        assert result["display_lights"] == "none"

    def test_display_lights_unknown_value_rejected_before_any_edit(self, fake_cmds):
        with pytest.raises(HandlerError, match="display_lights") as exc:
            viewport.set_viewport({"display_lights": "supernova"})
        assert exc.value.hint
        assert fake_cmds.calls == []

    def test_camera_resolved_to_canonical_long_name_even_though_panel_reports_short(
        self, fake_cmds
    ):
        # Regression guard: modelPanel -q -camera returns "bkCam" (short);
        # this would fail if the handler returned that short name verbatim
        # instead of resolving it.
        result = viewport.set_viewport({})
        assert result["camera"] == "|bkCam"


class TestSetCamera:
    def test_create_path_uses_camera_then_rename_not_named_kwarg(self, fake_cmds):
        # Regression guard: FakeCmds.camera() ignores name= entirely (matches
        # the live Maya quirk); if the handler passed name="mcpCam" to
        # cmds.camera() expecting it to take, the created node would be
        # "camera1", not "mcpCam", and this assertion would fail.
        result = viewport.set_camera({"camera": "mcpCam", "set_active": False})
        assert result["name"] == "|mcpCam"
        assert fake_cmds.objExists("mcpCam")

    def test_reuse_path_repositions_same_camera_without_creating_a_second_one(
        self, fake_cmds
    ):
        first = viewport.set_camera({"camera": "reuseCam", "set_active": False})
        created_after_first = fake_cmds._create_seq
        second = viewport.set_camera(
            {"camera": "reuseCam", "position": [1, 2, 3], "set_active": False}
        )
        assert second["name"] == first["name"] == "|reuseCam"
        assert fake_cmds._create_seq == created_after_first  # no extra create
        assert fake_cmds.translate["|reuseCam"] == [1.0, 2.0, 3.0]

    def test_reuse_path_resolves_nested_short_name_to_canonical_long(self, fake_cmds):
        fake_cmds._register("|grp|camB", "camera", shape="|grp|camB|camBShape")
        fake_cmds.translate["|grp|camB"] = [0.0, 0.0, 0.0]
        fake_cmds.rotate["|grp|camB"] = [0.0, 0.0, 0.0]
        result = viewport.set_camera({"camera": "camB", "set_active": False})
        assert result["name"] == "|grp|camB"

    def test_reuse_of_non_camera_shape_raises_hinted_error(self, fake_cmds):
        fake_cmds._register(
            "|existingMesh", "transform", shape="|existingMesh|existingMeshShape",
            shape_type="mesh",
        )
        with pytest.raises(HandlerError, match="camera") as exc:
            viewport.set_camera({"camera": "existingMesh", "set_active": False})
        assert exc.value.hint

    def test_reuse_of_shapeless_transform_raises_hinted_error(self, fake_cmds):
        fake_cmds.node_type["|emptyGrp"] = "transform"  # no shape registered
        with pytest.raises(HandlerError, match="camera") as exc:
            viewport.set_camera({"camera": "emptyGrp", "set_active": False})
        assert exc.value.hint

    def test_malformed_position_rejected(self, fake_cmds):
        with pytest.raises(HandlerError, match="position") as exc:
            viewport.set_camera(
                {"camera": "mcpCam", "position": [1, 2], "set_active": False}
            )
        assert exc.value.hint

    def test_malformed_look_at_rejected(self, fake_cmds):
        with pytest.raises(HandlerError, match="look_at") as exc:
            viewport.set_camera(
                {"camera": "mcpCam", "look_at": "nope", "set_active": False}
            )
        assert exc.value.hint

    def test_focal_length_sets_shape_attr(self, fake_cmds):
        result = viewport.set_camera(
            {"camera": "mcpCam", "focal_length": 50.0, "set_active": False}
        )
        shape = fake_cmds.shape_of["|" + result["name"].lstrip("|")]
        assert fake_cmds.attrs[shape + ".focalLength"] == 50.0

    def test_set_active_true_calls_lookthru_with_resolved_camera(self, fake_cmds):
        result = viewport.set_camera({"camera": "mcpCam"})  # default set_active=True
        assert ("lookThru", fake_cmds.panel, result["name"]) in fake_cmds.calls

    def test_set_active_false_never_calls_lookthru(self, fake_cmds):
        viewport.set_camera({"camera": "mcpCam", "set_active": False})
        assert not any(
            isinstance(c, tuple) and c[0] == "lookThru" for c in fake_cmds.calls
        )
