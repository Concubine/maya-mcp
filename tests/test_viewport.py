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

    #799 hardened three answers-anything fallbacks. `nodeType`/`getAttr`
    returned None and `listRelatives`/`xform` returned empties for a node
    that was never registered, so every query about a vanished node - the
    class that shipped #796's blocking defects - answered plausibly here
    and raises in Maya. Every panel-taking method accepted any string as a
    live panel. And `setAttr`/`xform` wrote to any plug: a camera whose
    translate or rotate is CONNECTION-FED (a keyed shot camera, an
    aim-constrained one) refuses a static write in Maya, and set_camera
    writes to exactly those plugs on a camera the caller may not have made.
    """

    def __init__(self):
        self.calls = []
        self.panel = "modelPanel4"
        self.panel_types = {"modelPanel4": "modelPanel"}
        self.visible_panels = ["modelPanel4"]
        self.focus_panel = "modelPanel4"
        self.deleted = []
        # plug -> the SOURCE PLUG feeding it. setAttr/xform refuse these.
        # A source plug (not a bare node name) because that is what Maya's
        # listConnections(plugs=True) answers, and the shared writability
        # guard classifies the source by asking nodeType about it (#802) -
        # so every entry's node must be registered in `node_type` too.
        self.driven_plugs = {}
        # plugs a rigger locked. Modelled here for the first time in #802:
        # setAttr refuses one, and `xform` does NOT - it writes the children
        # it can and skips the rest, which is why set_camera has to ask
        # before it writes rather than catch afterwards.
        self.locked_plugs = set()
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

    def _require(self, name):
        """Maya's answer for a node that was deleted or never made (#799)."""
        resolved = self._resolve(name)
        if resolved is None:
            raise RuntimeError("No object matches name: %s" % name)
        return resolved

    def _require_panel(self, panel):
        if panel not in self.panel_types:
            raise RuntimeError("Object '%s' not found." % panel)
        return panel

    def _static_write_blocker(self, node, attr):
        """The connection that makes a static write to `node.attr` raise.

        Maya refuses in BOTH compound directions: a compound refuses when a
        CHILD of it is fed - the asymmetry #796 measured on setAttr - and a
        child refuses when the whole compound is. `xform -translation` /
        `-rotation` are static writes to the same plugs.

        `setAttr` and `xform` share this one helper deliberately: round 1
        reported the guard as sitting on both while `setAttr` did a plain
        exact-string lookup, so a test pinning the compound rule through
        setAttr would have passed vacuously (#799 round 2).
        """
        candidates = [
            "%s.%s" % (node, attr),
            *["%s.%s%s" % (node, attr, axis) for axis in "XYZ"],
        ]
        if attr[-1:] in ("X", "Y", "Z"):
            candidates.append("%s.%s" % (node, attr[:-1]))
        for plug in candidates:
            if plug in self.locked_plugs:
                return "%s is locked" % plug
            if plug in self.driven_plugs:
                return "%s feeds it" % self.driven_plugs[plug]
        return None

    def _all_matches(self, name):
        """Every registered node whose long name or short tail equals `name`
        - unlike _resolve (which arbitrarily returns the first hit), this can
        report more than one match so naming.require_object's ambiguity
        branch is reachable through a handler, not just in isolation
        (test_naming.py already covers it directly)."""
        if name in self.node_type:
            return [name]
        short = str(name).lstrip("|")
        return [
            long_name for long_name in self.node_type
            if long_name.rsplit("|", 1)[-1] == short
        ]

    # -- panel discovery (used by find_model_panel, imported from capture) --
    def getPanel(self, **kw):
        # #799: typed, so getPanel does not answer "modelPanel" for whatever
        # happens to have focus. An agent-driven Maya usually has focus in
        # the script editor, and find_model_panel's search branches were
        # unreachable here while this answered a constant.
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
            return self.panel_camera_short
        return None

    def modelEditor(self, panel, **kw):
        self._require_panel(panel)
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
        if kw.get("long"):
            return self._all_matches(args[0])
        resolved = self._resolve(args[0])
        return [] if resolved is None else [args[0]]

    def listRelatives(self, node, **kw):
        resolved = self._require(node)
        shape = self.shape_of.get(resolved)
        return [shape] if shape else []

    def nodeType(self, node):
        return self.node_type[self._require(node)]

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
        resolved = self._require(node)
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
        resolved = self._require(node)
        if kw.get("query"):
            if kw.get("translation"):
                return list(self.translate.get(resolved, [0.0, 0.0, 0.0]))
            if kw.get("rotation"):
                return list(self.rotate.get(resolved, [0.0, 0.0, 0.0]))
            return None
        # #799 contract 2: `xform` is a STATIC write, and a plug a
        # constraint/anim curve/pairBlend feeds refuses one. set_camera
        # aims these at a camera the caller merely NAMED, which may be the
        # scene's own constrained shot camera.
        for flag, attr in (("translation", "translate"), ("rotation", "rotate")):
            if flag in kw:
                blocker = self._static_write_blocker(resolved, attr)
                if blocker:
                    raise RuntimeError(
                        "xform: The attribute '%s.%s' is locked or connected "
                        "and cannot be modified (%s feeds it)"
                        % (resolved, attr, blocker))
        if "translation" in kw:
            self.translate[resolved] = [float(v) for v in kw["translation"]]
        if "rotation" in kw:
            self.rotate[resolved] = [float(v) for v in kw["rotation"]]
        return None

    def delete(self, node):
        """A node really LEAVES the registry, so every later query about it
        takes the _require raise - the #796 class, in this fake's terms."""
        resolved = self._require(node)
        self.deleted.append(resolved)
        shape = self.shape_of.pop(resolved, None)
        self.node_type.pop(resolved, None)
        if shape:
            self.node_type.pop(shape, None)

    def setAttr(self, attr, *values, **kw):
        # *values, because Maya takes one per compound child: the single
        # positional this used to declare turned a compound write into a
        # TypeError instead of the modelled refusal (#799 round 2).
        node, _, name = str(attr).rpartition(".")
        resolved = self._require(node)
        if attr not in self.attrs:
            raise RuntimeError("No object matches name: %s" % attr)
        blocker = self._static_write_blocker(resolved, name)
        if blocker:
            raise RuntimeError(
                "setAttr: The attribute '%s' is locked or connected and "
                "cannot be modified (%s)" % (attr, blocker))
        self.attrs[attr] = values[0] if len(values) == 1 else list(values)

    def getAttr(self, attr, lock=False, **kw):
        node, _, _name = str(attr).rpartition(".")
        self._require(node)
        if kw:
            # #802: an unmodelled flag used to fall into **kw and come back
            # as the VALUE, which is a silent lie about a question the fake
            # was never taught to answer.
            raise TypeError(
                "FakeCmds.getAttr models lock= only (#802), not %r" % sorted(kw))
        if lock:
            # Exact-plug, like Maya: getAttr('.rotate', lock=True) is False
            # while rotateX is locked (measured A01), which is why the guard
            # asks the compound AND its children.
            return attr in self.locked_plugs
        if attr not in self.attrs:
            raise RuntimeError("No object matches name: %s" % attr)
        return self.attrs[attr]

    def listConnections(self, plug, source=False, destination=True,
                        plugs=False, type=None, **kw):
        """Source-side connections of ONE EXACT plug, as Maya answers them.

        Exact, because Maya is: a query on `.rotate` returns None while all
        three of its children are constraint-fed, and a query on `.rotateX`
        does not see a connection made on `.rotate` - MEASURED on 2027 by
        evals/static_write_probe_802.py (B01/B02, C01/C02). That asymmetry
        is the whole reason `plugwrite.family` asks about the compound and
        the children separately, so a fake that folded them together would
        make the guard's central case untestable (#802).
        """
        self._require(str(plug).split(".")[0])
        if not source:
            raise AssertionError(
                "FakeCmds.listConnections models source queries only (#802)")
        src = self.driven_plugs.get(plug)
        if src is None:
            return None
        node = src.split(".")[0]
        if type is not None:
            # Maya's type filter matches DERIVED types, so an animCurveTA
            # answers type="animCurve" (the #796 defect-1 trap).
            actual = self.nodeType(node)
            if not (actual == type
                    or (type == "animCurve" and actual.startswith(type))):
                return None
        return [src] if plugs else [node]

    def lookThru(self, panel, cam):
        self._require_panel(panel)
        self._require(cam)
        self.calls.append(("lookThru", panel, cam))


@pytest.fixture
def fake_cmds(monkeypatch):
    cmds = FakeCmds()
    monkeypatch.setattr(viewport, "_cmds", lambda: cmds)
    return cmds


class TestTheFakeRefusesWhatMayaRefuses:
    """The regression barrier for FakeCmds itself (#799 round 2).

    Round 1 hardened this fake and asserted none of it: reverting every
    behavioural change left the suite green, which is the ticket's own
    complaint - "a green suite proves nothing" - one level up. `deleted` was
    the clearest case, appended to by `delete` and read by nothing.

    Only what this fake models is pinned here. The compound rule is asserted
    on the two plugs set_camera really writes - the transform's translate /
    rotate through `xform`, and the shape's focalLength through `setAttr` -
    plus the shared blocker both of them go through.
    """

    # -- contract 1: existence -------------------------------------------
    def test_every_query_about_a_node_nobody_made_raises(self, fake_cmds):
        ghost = "|nobodyMadeThis"
        for call in (
            lambda: fake_cmds.nodeType(ghost),
            lambda: fake_cmds.getAttr(ghost + ".focalLength"),
            lambda: fake_cmds.setAttr(ghost + ".focalLength", 50.0),
            lambda: fake_cmds.listRelatives(ghost),
            lambda: fake_cmds.xform(ghost, query=True, translation=True),
            lambda: fake_cmds.xform(ghost, translation=(1, 2, 3)),
            lambda: fake_cmds.rename(ghost, "somethingElse"),
            lambda: fake_cmds.delete(ghost),
            lambda: fake_cmds.lookThru(fake_cmds.panel, ghost),
        ):
            with pytest.raises(RuntimeError, match="No object matches name"):
                call()

    def test_a_deleted_camera_is_logged_and_stops_answering(self, fake_cmds):
        """`deleted` existed and was read by nothing (#799 round 2). A
        deleted node is the whole point of contract 1: set_camera names a
        camera the caller last saw some time ago."""
        fake_cmds.delete("|bkCam")
        assert fake_cmds.deleted == ["|bkCam"]
        assert fake_cmds.objExists("bkCam") is False
        for call in (
            lambda: fake_cmds.nodeType("|bkCam"),
            lambda: fake_cmds.listRelatives("|bkCam"),
            lambda: fake_cmds.xform("|bkCam", query=True, translation=True),
        ):
            with pytest.raises(RuntimeError, match="No object matches name"):
                call()
        # The shape goes with it, and so does the plug that hung off it.
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake_cmds.getAttr("|bkCam|bkCamShape.focalLength")

    def test_ls_and_objexists_report_rather_than_raise(self, fake_cmds):
        assert fake_cmds.ls("|nobodyMadeThis", long=True) == []
        assert fake_cmds.objExists("|nobodyMadeThis") is False
        assert fake_cmds.ls("bkCam", long=True) == ["|bkCam"]
        assert fake_cmds.objExists("bkCam") is True

    def test_a_panel_that_is_not_there_raises(self, fake_cmds):
        for call in (
            lambda: fake_cmds.modelPanel("torn_off_and_closed", query=True, camera=True),
            lambda: fake_cmds.modelEditor("torn_off_and_closed", query=True, grid=True),
            lambda: fake_cmds.lookThru("torn_off_and_closed", "|bkCam"),
        ):
            with pytest.raises(RuntimeError, match="not found"):
                call()

    def test_getpanel_is_typed_rather_than_calling_the_focused_one_a_viewport(
        self, fake_cmds
    ):
        # An agent-driven Maya usually has focus in the script editor, and
        # find_model_panel's search branches were unreachable here while
        # this answered "modelPanel" for whatever had focus.
        fake_cmds.panel_types["scriptEditorPanel1"] = "scriptEditor"
        fake_cmds.focus_panel = "scriptEditorPanel1"
        assert fake_cmds.getPanel(withFocus=True) == "scriptEditorPanel1"
        assert fake_cmds.getPanel(typeOf="scriptEditorPanel1") == "scriptEditor"
        assert fake_cmds.getPanel(type="modelPanel") == ["modelPanel4"]

    # -- contract 2: a fed plug refuses a static write --------------------
    def test_setattr_refuses_a_connection_fed_plug(self, fake_cmds):
        # focalLength is the one plug set_camera writes with setAttr, and a
        # keyed zoom feeds exactly it.
        fake_cmds.node_type["focal_anim"] = "animCurveTU"
        fake_cmds.driven_plugs["|bkCam|bkCamShape.focalLength"] = (
            "focal_anim.output")
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake_cmds.setAttr("|bkCam|bkCamShape.focalLength", 50.0)
        assert fake_cmds.attrs["|bkCam|bkCamShape.focalLength"] == 35.0

    def test_a_free_plug_still_takes_its_write(self, fake_cmds):
        fake_cmds.setAttr("|bkCam|bkCamShape.focalLength", 50.0)
        assert fake_cmds.attrs["|bkCam|bkCamShape.focalLength"] == 50.0

    def test_setattr_asks_the_same_blocker_xform_does(self, fake_cmds):
        """Round 1 put the compound rule in `xform` and left `setAttr` on a
        plain exact-string lookup while reporting the guard as living on
        both. The only plug set_camera setAttrs is the scalar focalLength,
        so no compound write through setAttr can catch that divergence -
        what can is that both writers consult ONE rule.
        """
        asked = []
        real = fake_cmds._static_write_blocker
        fake_cmds._static_write_blocker = lambda node, attr: (
            asked.append((node, attr)) or real(node, attr))
        fake_cmds.setAttr("|bkCam|bkCamShape.focalLength", 50.0)
        fake_cmds.xform("|bkCam", translation=(1, 2, 3))
        assert ("|bkCam|bkCamShape", "focalLength") in asked
        assert ("|bkCam", "translate") in asked

    def test_xform_refuses_a_compound_write_when_a_child_is_fed(self, fake_cmds):
        """The direction set_camera meets: it writes the WHOLE translate
        compound through xform, and an aim or point constraint feeds the
        children. Maya refuses the compound write, and round 1 reported this
        guard as living on setAttr as well when it lived only here."""
        fake_cmds.node_type["bkCam_pointConstraint1"] = "pointConstraint"
        fake_cmds.driven_plugs["|bkCam.translateX"] = (
            "bkCam_pointConstraint1.constraintTranslateX")
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake_cmds.xform("|bkCam", translation=(1, 2, 3))
        assert fake_cmds.translate["|bkCam"] == [0.0, 0.0, 5.0]

    def test_xform_refuses_a_write_to_the_fed_compound_itself(self, fake_cmds):
        fake_cmds.node_type["bkCam_aimConstraint1"] = "aimConstraint"
        fake_cmds.driven_plugs["|bkCam.rotate"] = (
            "bkCam_aimConstraint1.constraintRotate")
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake_cmds.xform("|bkCam", rotation=(0, 90, 0))
        assert fake_cmds.rotate["|bkCam"] == [0.0, 0.0, 0.0]

    def test_the_blocker_answers_in_both_compound_directions(self, fake_cmds):
        """setAttr and xform go through this one helper, so the two cannot
        drift apart: a fed CHILD blocks the compound, and a fed COMPOUND
        blocks the child."""
        fake_cmds.node_type["bkCam_pointConstraint1"] = "pointConstraint"
        fake_cmds.driven_plugs["|bkCam.translateX"] = (
            "bkCam_pointConstraint1.constraintTranslateX")
        assert fake_cmds._static_write_blocker("|bkCam", "translate") == (
            "bkCam_pointConstraint1.constraintTranslateX feeds it")
        fake_cmds.node_type["bkCam_aimConstraint1"] = "aimConstraint"
        fake_cmds.driven_plugs["|bkCam.rotate"] = (
            "bkCam_aimConstraint1.constraintRotate")
        assert fake_cmds._static_write_blocker("|bkCam", "rotateY") == (
            "bkCam_aimConstraint1.constraintRotate feeds it")
        assert fake_cmds._static_write_blocker("|bkCam", "visibility") is None

    # -- #802: the two queries the shared writability guard makes ---------
    def test_getattr_lock_is_exact_plug_like_maya(self, fake_cmds):
        """MEASURED (A01): getAttr('.rotate', lock=True) is False while
        rotateX is locked. A fake that folded the family together would
        make the guard's whole reason for walking one untestable."""
        fake_cmds.locked_plugs = {"|bkCam.translateY"}
        assert fake_cmds.getAttr("|bkCam.translateY", lock=True) is True
        assert fake_cmds.getAttr("|bkCam.translate", lock=True) is False
        assert fake_cmds.getAttr("|bkCam.translateX", lock=True) is False

    def test_a_locked_plug_refuses_the_write_the_guard_asks_about(self, fake_cmds):
        fake_cmds.locked_plugs = {"|bkCam.translateY"}
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake_cmds.xform("|bkCam", translation=(1, 2, 3))
        assert fake_cmds.translate["|bkCam"] == [0.0, 0.0, 5.0]

    def test_listconnections_answers_the_exact_plug_only(self, fake_cmds):
        """MEASURED (B01/B02): the compound query answers None while every
        child is constraint-fed, and a child query does not see a
        connection made on the compound."""
        fake_cmds.node_type["bkCam_pointConstraint1"] = "pointConstraint"
        fake_cmds.driven_plugs["|bkCam.translateX"] = (
            "bkCam_pointConstraint1.constraintTranslateX")
        ask = lambda plug: fake_cmds.listConnections(  # noqa: E731
            plug, source=True, destination=False, plugs=True)
        assert ask("|bkCam.translateX") == [
            "bkCam_pointConstraint1.constraintTranslateX"]
        assert ask("|bkCam.translate") is None
        assert ask("|bkCam.translateY") is None
        with pytest.raises(AssertionError, match="source queries only"):
            fake_cmds.listConnections("|bkCam.translateX", destination=True)

    def test_an_unmodelled_getattr_flag_raises_rather_than_lying(self, fake_cmds):
        with pytest.raises(TypeError, match="lock="):
            fake_cmds.getAttr("|bkCam.translate", settable=True)

    def test_an_unfed_camera_still_moves(self, fake_cmds):
        # The refusal must not become the answer to everything.
        fake_cmds.xform("|bkCam", translation=(1, 2, 3))
        assert fake_cmds.translate["|bkCam"] == [1.0, 2.0, 3.0]


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

    def test_ambiguous_camera_short_name_refuses_before_any_edit(self, fake_cmds):
        # A second node sharing the panel camera's short name makes
        # naming.require_object raise "ambiguous". That must happen BEFORE
        # cmds.modelEditor(edit=True, ...) mutates the panel - otherwise the
        # requested settings silently took even though the call raised.
        fake_cmds._register("|other|bkCam", "camera", shape="|other|bkCam|bkCamShape")
        with pytest.raises(HandlerError, match="ambiguous") as exc:
            viewport.set_viewport({"show_grid": False})
        assert exc.value.hint
        assert fake_cmds.calls == []  # no modelEditor call was ever made
        assert fake_cmds.editor_flags["grid"] is True  # untouched


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
        assert first["warnings"] == []  # fresh create: nothing to warn about
        created_after_first = fake_cmds._create_seq
        second = viewport.set_camera(
            {"camera": "reuseCam", "position": [1, 2, 3], "set_active": False}
        )
        assert second["name"] == first["name"] == "|reuseCam"
        assert fake_cmds._create_seq == created_after_first  # no extra create
        assert fake_cmds.translate["|reuseCam"] == [1.0, 2.0, 3.0]
        assert any("reused existing camera |reuseCam" in w for w in second["warnings"])

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

    def test_an_animated_lens_is_refused_before_the_camera_moves(self, fake_cmds):
        """#802: focal_length on a keyed lens is the same collision as a
        constrained transform, and it used to be applied THIRD - after the
        position and the aim had already landed."""
        fake_cmds.node_type["focal_anim"] = "animCurveTU"
        fake_cmds.driven_plugs["|bkCam|bkCamShape.focalLength"] = (
            "focal_anim.output")
        with pytest.raises(HandlerError) as exc:
            viewport.set_camera({"camera": "bkCam", "position": [1, 2, 3],
                                 "focal_length": 50.0, "set_active": False})
        assert "focalLength" in str(exc.value) and exc.value.hint
        assert fake_cmds.translate["|bkCam"] == [0.0, 0.0, 5.0]

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


class TestPanelDiscovery:
    """#799: getPanel used to call whatever had focus a modelPanel, so
    find_model_panel's search branches never ran through these handlers."""

    def test_set_viewport_finds_the_viewport_when_focus_is_elsewhere(
        self, fake_cmds
    ):
        fake_cmds.panel_types["scriptEditorPanel1"] = "scriptEditor"
        fake_cmds.focus_panel = "scriptEditorPanel1"
        assert fake_cmds.panel not in (fake_cmds.focus_panel,)
        assert viewport.set_viewport({})["panel"] == fake_cmds.panel

    def test_set_camera_activates_on_the_viewport_not_the_focused_panel(
        self, fake_cmds
    ):
        fake_cmds.panel_types["scriptEditorPanel1"] = "scriptEditor"
        fake_cmds.focus_panel = "scriptEditorPanel1"
        result = viewport.set_camera({"camera": "mcpCam"})
        assert ("lookThru", fake_cmds.panel, result["name"]) in fake_cmds.calls

    def test_a_deleted_camera_is_recreated_rather_than_queried(self, fake_cmds):
        """`camera` names a node that may have gone away since the caller
        last saw it. objExists has to decide that BEFORE require_object /
        listRelatives get asked, because Maya answers those with a raise
        (#799 contract 1) - the fake used to answer None and [] instead."""
        fake_cmds.delete("|bkCam")
        result = viewport.set_camera({"camera": "bkCam", "set_active": False})
        assert result["name"] == "|bkCam"
        assert result["warnings"] == []   # a fresh create, not a reuse


class TestFocalLengthIsCheckedBeforeAnyWrite:
    """#823, measured: focal_length 0 or negative reached setAttr and Maya
    answered "Cannot set the attribute ... below its minimum value of 0.5" -
    a raw error, after the position had already been written."""

    @pytest.mark.parametrize("focal", [0, -5, 0.2, "35", True, None])
    def test_a_bad_focal_length_is_refused_with_nothing_written(self, fake_cmds, focal):
        if focal is None:
            pytest.skip("None means not passed")
        viewport.set_camera({"camera": "focCam", "set_active": False})
        before = list(fake_cmds.translate["|focCam"])
        with pytest.raises(HandlerError, match="focal_length"):
            viewport.set_camera({"camera": "focCam", "position": [1, 2, 3],
                                 "focal_length": focal, "set_active": False})
        assert fake_cmds.translate["|focCam"] == before

    def test_maya_s_minimum_is_still_accepted(self, fake_cmds):
        out = viewport.set_camera({"camera": "focCam", "focal_length": 0.5, "set_active": False})
        assert fake_cmds.attrs["|focCam|focCamShape.focalLength"] == 0.5
        assert out["name"] == "|focCam"


class TestSetCameraMeetsAConnectedPlug:
    """#799 contract 2: `camera` names a node the caller need not have made.

    set_camera's reuse path already refuses one wrong kind of collision with
    a hint - a name that resolves to a mesh, or to a shapeless transform -
    precisely so the caller does not get "a raw IndexError ... or a raw Maya
    exception (setAttr/lookThru)", in the handler's own words. A camera whose
    transform plugs are CONNECTION-FED is the same collision: the name
    resolved to a real camera that belongs to something else. Maya refuses
    the static write; nothing here catches it.

    Both scenarios below are ordinary scenes. An aim-constrained camera is
    the standard way to make one track a subject, and a camera parented into
    a rig through a parentConstraint is how a shot camera rides a vehicle.
    """

    def _constrained(self, fake_cmds, plugs):
        fake_cmds._register("|shotCam", "camera", shape="|shotCam|shotCamShape")
        fake_cmds.translate["|shotCam"] = [0.0, 0.0, 5.0]
        fake_cmds.rotate["|shotCam"] = [0.0, 0.0, 0.0]
        fake_cmds.attrs["|shotCam|shotCamShape.focalLength"] = 35.0
        for plug in plugs:
            fake_cmds.node_type["shotCam_constraint1"] = "parentConstraint"
            fake_cmds.driven_plugs[plug] = (
            "shotCam_constraint1.constraint") +                 plug.rpartition(".")[2].capitalize()
        return fake_cmds

    def test_a_constrained_camera_is_refused_with_a_hint(self, fake_cmds):
        """#802 FIXED. The refusal the neighbouring collision already got.

        #799 pinned this expecting a raw RuntimeError out of cmds.xform.
        The live probe measured otherwise (evals/static_write_probe_802b.py,
        R3/R4/R5): xform does not raise on a parent-constrained camera at
        all - it writes what it can, the constraint reasserts on the next
        evaluation, and set_camera used to report the position it had asked
        for as though it had taken. So the defect was a SILENT wrong answer,
        not an ugly one, and no except clause could ever have caught it.
        """
        self._constrained(fake_cmds, ["|shotCam.translate", "|shotCam.rotate"])
        with pytest.raises(HandlerError) as exc:
            viewport.set_camera(
                {"camera": "shotCam", "position": [1, 2, 3], "set_active": False}
            )
        assert exc.value.hint

    def test_a_refusal_does_not_leave_the_camera_half_moved(self, fake_cmds):
        """#802 FIXED. Position used to be applied before look_at was tried.

        An AIM-constrained camera has translate free and rotate fed, so the
        move landed and the aim did not. set_camera makes deliberate
        persistent changes and has no restore, so the user's camera had
        relocated for nothing. Every plug the call will write is now asked
        about together, before the first one lands.
        """
        self._constrained(fake_cmds, ["|shotCam.rotate"])
        with pytest.raises(Exception):
            viewport.set_camera({
                "camera": "shotCam", "position": [1, 2, 3],
                "look_at": [0, 0, 0], "set_active": False,
            })
        assert fake_cmds.translate["|shotCam"] == [0.0, 0.0, 5.0], (
            "the camera moved even though the call failed"
        )


class TestSetViewportSaysWhatACaptureWillIgnore:
    """#829: these flags read like they are about pictures. They are not.

    MEASURED live: every capture forces grid, light/camera icons, locators,
    manipulators and texture placements OFF for its own frames and restores
    the panel afterwards - a grid switched on here changed nothing at all in
    the pixels of the capture that followed. Before this, set_viewport
    answered a caller who asked for a grid in their shots with a cheerful
    show_grid: true and nothing else.
    """

    def test_switching_a_capture_forced_flag_on_says_so(self, fake_cmds):
        out = viewport.set_viewport({"show_grid": True})
        assert out["show_grid"] is True
        assert len(out["warnings"]) == 1
        note = out["warnings"][0].lower()
        assert "the grid is now shown" in note
        assert "captures force it off" in note

    def test_it_names_every_flag_the_call_switched_on(self, fake_cmds):
        out = viewport.set_viewport({"show_grid": True, "show_locators": True})
        assert len(out["warnings"]) == 1
        note = out["warnings"][0].lower()
        assert "locators and the grid are now shown" in note
        assert "captures force them off" in note

    def test_switching_one_OFF_is_not_worth_a_word(self, fake_cmds):
        # Off is what a capture does anyway: nothing to warn about.
        assert viewport.set_viewport({"show_grid": False})["warnings"] == []

    def test_a_flag_captures_do_not_touch_is_not_warned_about(self, fake_cmds):
        # wireframe_on_shaded and display_lights are both READ by a capture
        # (as wireframe_overlay and lighting), so they are not in this list.
        assert viewport.set_viewport({"wireframe_on_shaded": True})["warnings"] == []
        assert viewport.set_viewport({"display_lights": "all"})["warnings"] == []

    def test_a_pure_query_never_warns(self, fake_cmds):
        # Reading the state must not lecture: nothing was changed.
        assert viewport.set_viewport({})["warnings"] == []
