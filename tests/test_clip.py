"""author_clip / delete_clip (#695) under a FakeCmds.

Real curve evaluation is mayapy's job (tests/test_handlers_mayapy.py); this
file pins validation, the one-clip-at-a-time replace rule, the foreign-curve
refusal, metadata, measured per-key displacement (via the _points seam and a
linear fake), tangent mapping, and delete_clip's teardown.
"""

import json

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import clip


class FakeCmds:
    """A 3-joint chain |root -> |root|mid -> |root|mid|tip, one optional
    bound mesh |body with a blendShape 'body_shapes' carrying alias 'blink'.
    setKeyframe records (node, attr, frame, value) and creates a curve node
    per plug; listConnections answers from that map. currentTime drives the
    fake pose the _points seam reads."""

    def __init__(self, bound=True, rigid_chunks=None):
        self.joints = ["|root", "|root|mid", "|root|mid|tip"]
        self.bound = bound
        # #713/#720: the second legal rig shape - chunks parented under
        # joints with no skinCluster anywhere. joint -> chunk transform.
        self.rigid_chunks = dict(rigid_chunks or {})
        self.curves = {}          # plug -> curve node name
        self.keys = {}            # plug -> {frame: value}
        self.tangents = []        # (node, attr, itt, ott)
        self.attrs = {"|root.translateX": 0.0, "|root.translateY": 1.0,
                      "|root.translateZ": 0.0}
        for j in self.joints:
            self.attrs[j + ".rotate"] = (0.0, 0.0, 0.0)
        self.string_attrs = {}    # node -> {attr: value}
        self.time = 0.0
        self.time_unit = "film"
        self.playback = {}
        self.deleted = []
        self.checkpoints = []
        self.blend_aliases = ["blink"] if bound else []
        self.time_unit_calls = []   # every currentUnit(time=...) issued

    # --- resolution ------------------------------------------------------
    def ls(self, pattern=None, long=False, type=None, **kw):
        if type == "skinCluster":
            return ["body_skin"] if self.bound else []
        if type == "joint":
            return list(self.joints)
        if isinstance(pattern, list):
            if type == "blendShape":
                return [n for n in pattern if n == "body_shapes"]
            return list(pattern)
        if pattern is None:
            return list(self.joints) + (["|body"] if self.bound else [])
        matches = [o for o in self.joints + (["|body"] if self.bound else [])
                   if o == pattern or o.split("|")[-1] == pattern]
        return matches

    def objExists(self, name):
        return bool(self.ls(name)) or name in ("body_shapes", "body_skin")

    def nodeType(self, node):
        if node in self.joints:
            return "joint"
        if node == "body_shapes":
            return "blendShape"
        return "mesh" if node.endswith("Shape") else "transform"

    def listRelatives(self, node, children=False, parent=False, shapes=False,
                      allDescendents=False, type=None, fullPath=False, **kw):
        if children and type == "joint":
            kids = [j for j in self.joints
                    if j.rsplit("|", 1)[0] == node and j != node]
            return kids or None
        if shapes:
            if node == "|body":
                return ["|body|bodyShape"]
            if node in self.rigid_chunks.values():
                return [node + "|" + node.rsplit("|", 1)[-1] + "Shape"]
            return None
        if parent:
            return ["|body"] if node == "|body|bodyShape" else None
        if allDescendents:
            # Real Maya excludes shapes from type="transform"; the chunk
            # transform under this joint is what _bound_meshes is after.
            chunk = self.rigid_chunks.get(node)
            return [chunk] if chunk else None
        return None

    def listHistory(self, node, pruneDagObjects=False, **kw):
        if node == "|body|bodyShape":
            return ["body_shapes", "body_skin"]
        return []

    def listAttr(self, plug, multi=False):
        if plug.startswith("body_shapes"):
            return list(self.blend_aliases) or None
        return None

    def skinCluster(self, name, query=False, influence=False, geometry=False):
        if influence:
            return list(self.joints)
        if geometry:
            return ["|body|bodyShape"]
        return None

    # --- attributes ------------------------------------------------------
    def getAttr(self, key, time=None):
        if key.endswith(".mcp_clip") or key.endswith(".mcp_clip_rest"):
            node, attr = key.rsplit(".", 1)
            return self.string_attrs[node][attr]
        if time is not None:
            return self.evaluate(key, float(time))
        return self.attrs.get(key, 0.0)

    def evaluate(self, plug, t):
        """What a real animCurve would report at time `t`: held at the
        first key's value backwards in time, at the last key's value
        forwards in time, linearly interpolated in between. The exact-key
        lookup the old getAttr(time=...) did could never observe
        contamination BETWEEN keys - which is the entire premise of the
        self-contained-takes rule (#718 review Fix 5)."""
        keys = self.keys.get(plug)
        if not keys:
            return self.attrs.get(plug, 0.0)
        times = sorted(keys)
        if t <= times[0]:
            return keys[times[0]]
        if t >= times[-1]:
            return keys[times[-1]]
        for lo, hi in zip(times, times[1:]):
            if lo <= t <= hi:
                if hi == lo:
                    return keys[lo]
                frac = (t - lo) / (hi - lo)
                return keys[lo] + frac * (keys[hi] - keys[lo])
        return keys[times[-1]]   # unreachable given the bounds above

    def setAttr(self, key, *values, **kw):
        if kw.get("type") == "string":
            node, attr = key.rsplit(".", 1)
            self.string_attrs.setdefault(node, {})[attr] = values[0]
        elif len(values) == 3:
            self.attrs[key] = tuple(values)
        else:
            self.attrs[key] = values[0]

    def addAttr(self, node, longName=None, dataType=None):
        self.string_attrs.setdefault(node, {})[longName] = ""

    def attributeQuery(self, attr, node=None, exists=False):
        return attr in self.string_attrs.get(node, {})

    def deleteAttr(self, plug):
        node, attr = plug.rsplit(".", 1)
        self.string_attrs.get(node, {}).pop(attr, None)

    def xform(self, node, query=False, worldSpace=False, translation=None,
              **kw):
        if query:
            return [self.attrs.get(node + ".translateX", 0.0),
                    self.attrs.get(node + ".translateY", 0.0),
                    self.attrs.get(node + ".translateZ", 0.0)]
        for axis, v in zip("XYZ", translation):
            self.attrs[node + ".translate" + axis] = float(v)

    # --- animation -------------------------------------------------------
    def setKeyframe(self, node, attribute=None, time=None, value=None):
        plug = "%s.%s" % (node, attribute)
        self.curves.setdefault(plug, plug.replace("|", "_") + "_crv")
        self.keys.setdefault(plug, {})[float(time)] = float(value)

    def keyTangent(self, node, attribute=None, edit=False, time=None,
                   inTangentType=None, outTangentType=None):
        self.tangents.append(
            (node, attribute, time, inTangentType, outTangentType))

    def keyframe(self, plug, query=False, **kw):
        return sorted(self.keys.get(plug, {})) or None

    def cutKey(self, plug, time=None, clear=False, **kw):
        keys = self.keys.get(plug)
        if not keys:
            return 0
        lo, hi = time
        doomed = [t for t in keys if lo <= t <= hi]
        for t in doomed:
            del keys[t]
        if not keys:
            curve = self.curves.pop(plug, None)
            if curve:
                self.deleted.append(curve)
            self.keys.pop(plug, None)
        return len(doomed)

    def listConnections(self, plug, source=False, destination=True,
                        type=None):
        curve = self.curves.get(plug)
        return [curve] if curve else None

    def delete(self, *names):
        for n in names:
            self.deleted.append(n)
            for plug, curve in list(self.curves.items()):
                if curve == n:
                    del self.curves[plug]
                    self.keys.pop(plug, None)

    def currentUnit(self, time=None, angle=None, query=False, **kw):
        # units.degrees_to_ui/ui_to_degrees ask for the ANGLE unit; answering
        # "deg" (units.DEGREES_PER_ANGLE_UNIT's identity key - see
        # test_units.py's FakeAngleCmds("deg") and test_rigging.py's
        # angle_unit="deg" default) makes both identity, so keyed values
        # equal their degrees. The brief text said "degree"; that value is
        # not a key of units.DEGREES_PER_ANGLE_UNIT and raises HandlerError -
        # fixed here to match the real module's convention.
        if query and angle:
            return "deg"
        if query:
            return self.time_unit
        if time is not None:
            self.time_unit_calls.append(time)
            self.time_unit = time

    def currentTime(self, value=None, query=False):
        if query:
            return self.time
        self.time = float(value)

    def playbackOptions(self, edit=False, **kw):
        self.playback.update(kw)

    def dagPose(self, *args, **kw):
        return []   # nothing bound via dagPose in the fake: zero-rotation path


def _install(fake, monkeypatch):
    """Wire a FakeCmds into the clip module - the `fake` fixture's body,
    reusable by tests that need a differently-shaped scene (#720)."""
    monkeypatch.setattr(clip, "_cmds", lambda: fake)
    monkeypatch.setattr(clip.session, "auto_checkpoint",
                        lambda label: fake.checkpoints.append(label) or
                        {"checkpoint_id": "cp"})

    def points(mesh):
        # One vertex whose Y is the value of |root.rotateX's curve at the
        # fake's current frame (0 when unkeyed) - the minimal model that
        # makes per-key displacement depend on evaluated curves.
        keys = fake.keys.get("|root.rotateX", {})
        lift = keys.get(fake.time, 0.0)
        return [0.0, lift, 0.0, 1.0, 0.0, 0.0]

    monkeypatch.setattr(clip, "_points", points)
    return fake


@pytest.fixture
def fake(monkeypatch):
    return _install(FakeCmds(), monkeypatch)


def _author(fake, name="idle", fps=30, keys=None, **kw):
    if keys is None:
        keys = [
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"mid": [0, 0, 45]},
             "root_position": [0.0, 1.05, 0.0]},
        ]
    return clip.author_clip(dict({"root": "root", "name": name, "fps": fps,
                                  "keys": keys}, **kw))


class TestAuthorValidation:
    def test_refusals_cost_nothing(self, fake):
        with pytest.raises(HandlerError, match="plain identifier"):
            _author(fake, name="2bad")
        with pytest.raises(HandlerError, match="fps"):
            _author(fake, fps=31)
        with pytest.raises(HandlerError, match="interpolation"):
            _author(fake, interpolation="stepped")
        with pytest.raises(HandlerError, match="not a joint under this root"):
            _author(fake, keys=[
                {"time_s": 0.0, "rotations": {"nope": [0, 0, 0]}},
                {"time_s": 1.0, "rotations": {"nope": [0, 0, 0]}}])
        with pytest.raises(HandlerError, match="not a blendshape target"):
            _author(fake, keys=[
                {"time_s": 0.0, "blend_weights": {"nope": 0.5}},
                {"time_s": 1.0, "blend_weights": {"nope": 0.0}}])
        assert fake.checkpoints == []

    def test_loop_violations_refuse_with_measured_deltas(self, fake):
        with pytest.raises(HandlerError, match="ends 45"):
            _author(fake, loop=True, keys=[
                {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
                {"time_s": 1.0, "rotations": {"mid": [0, 0, 45]}}])

    def test_foreign_curves_refuse(self, fake):
        fake.curves["|root|mid.rotateZ"] = "hand_authored_crv"
        with pytest.raises(HandlerError, match="hand-authored"):
            _author(fake)


class TestAuthor:
    def test_keys_land_measured_and_metadata_written(self, fake):
        out = _author(fake)
        assert out["root"] == "|root"
        assert out["clip"] == "idle"
        assert out["duration_s"] == pytest.approx(1.0)   # re-read, not echoed
        assert out["frames"] == 31
        assert out["keyed_joints"] == 1
        assert out["root_position_keyed"] is True
        assert out["replaced"] is None
        # rotations keyed on all three axes of the named joint
        assert set(p for p in fake.keys if p.startswith("|root|mid.rotate")) \
            == {"|root|mid.rotateX", "|root|mid.rotateY", "|root|mid.rotateZ"}
        # root translate keyed from the world position
        assert fake.keys["|root.translateY"][30.0] == pytest.approx(1.05)
        # time unit follows fps; playback range covers the clip
        assert fake.time_unit == "ntsc"
        assert fake.playback["minTime"] == 0
        assert fake.playback["maxTime"] == 30
        meta = json.loads(fake.string_attrs["|root"]["mcp_clip"])[0]
        assert meta["name"] == "idle" and meta["fps"] == 30
        assert meta["loop"] is False
        assert fake.checkpoints == ["author_clip"]

    def test_per_key_displacement_is_evaluated_not_echoed(self, fake):
        out = _author(fake, keys=[
            {"time_s": 0.0, "rotations": {"root": [0, 0, 0]}},
            {"time_s": 0.5, "rotations": {"root": [0.25, 0, 0]}},
            {"time_s": 1.0, "rotations": {"root": [0, 0, 0]}}])
        disp = [k["max_displacement"] for k in out["per_key"]]
        # the fake's vertex rides |root.rotateX's keyed value
        assert disp[0] == 0.0
        assert disp[1] == pytest.approx(0.25)
        assert disp[2] == pytest.approx(0.0)

    def test_a_second_clip_appends_after_the_first(self, fake):
        first = _author(fake, name="idle")
        assert (first["start_frame"], first["end_frame"]) == (0, 30)
        assert first["clips"] == ["idle"] and first["replaced"] is None
        second = _author(fake, name="walk")
        # frame 31 is the gap; walk owns 32..62
        assert (second["start_frame"], second["end_frame"]) == (32, 62)
        assert second["clips"] == ["idle", "walk"]
        assert second["replaced"] is None
        # idle's keys are untouched
        assert sorted(fake.keys["|root|mid.rotateZ"]) == [0.0, 30.0, 32.0, 62.0]
        # the playback range spans everything
        assert fake.playback["maxTime"] == 62

    def test_re_authoring_a_name_moves_it_to_the_tail(self, fake):
        _author(fake, name="idle")
        _author(fake, name="walk")
        again = _author(fake, name="idle")
        assert again["replaced"] == "idle"
        assert (again["start_frame"], again["end_frame"]) == (64, 94)
        assert again["clips"] == ["walk", "idle"]
        assert any("vacated" in w and "0-30" in w and "64-94" in w
                   for w in again["warnings"]), again["warnings"]
        # the vacated range holds no keys any more, walk's are untouched
        times = sorted(fake.keys["|root|mid.rotateZ"])
        assert 0.0 not in times and 30.0 not in times
        assert 32.0 in times and 62.0 in times

    def test_a_second_fps_refuses_and_names_the_one_in_use(self, fake):
        _author(fake, name="idle", fps=30)
        with pytest.raises(HandlerError, match="one rig is one frame rate"):
            _author(fake, name="walk", fps=24)
        # the refusal cost nothing: no checkpoint beyond the first author
        assert fake.checkpoints == ["author_clip"]

    def test_a_clip_on_another_rig_warns_because_export_will_refuse(self, fake):
        fake.string_attrs["|other_root"] = {"mcp_clip": "[]"}
        fake.joints.append("|other_root")
        out = _author(fake, name="idle")
        assert any("other_root" in w and "export_fbx" in w
                   for w in out["warnings"]), out["warnings"]

    def test_tangent_mapping(self, fake):
        """#718 review Fix 2: every keyTangent call is scoped to a `time`
        (the whole tuple shape changed to carry it), so retangenting one
        clip can never reach another clip's keys on a shared curve. The
        MAIN pass is scoped to the clip's own [start, end] and carries its
        interpolation; any boundary PIN (fired here because the fixture's
        default keys only key root_position on the second key, so the
        first clip's boundary needs padding on the second author) is
        scoped to a single frame and always flat, regardless of
        interpolation."""
        first = _author(fake, interpolation="smooth")
        main = [t for t in fake.tangents
                if t[2] == (first["start_frame"], first["end_frame"])]
        assert main and all(t[3] == "auto" and t[4] == "auto" for t in main)
        assert len(main) == len(fake.tangents)   # idle is the first clip:
        # theirs is empty, so nothing here can be a boundary pin
        before = fake.tangents[:]
        second = _author(fake, name="lin", interpolation="linear")
        new = fake.tangents[len(before):]
        main_new = [t for t in new
                   if t[2] == (second["start_frame"], second["end_frame"])]
        assert main_new and all(t[3] == "linear" for t in main_new)
        pins = [t for t in new if t not in main_new]
        assert pins and all(t[2][0] == t[2][1] for t in pins)   # one frame
        assert all(t[3] == "flat" and t[4] == "flat" for t in pins)

    def test_tangent_pass_widens_to_the_measured_span_for_a_fractional_key(
            self, fake):
        """#718 review wave 2 Fix 3: end_frame is ROUNDED (#636) - a
        fractional last key (0.333s at 30fps = frame 9.99) rounds UP to
        end_frame=10, which sits past the actual key. A main tangent pass
        scoped to (start_frame, end_frame) would then miss the 9.99 key
        entirely and silently leave Maya's default tangent instead of this
        clip's interpolation. The pass must widen to the unrounded
        MEASURED span instead - the lower bound stays start_frame, which
        is exact by construction."""
        out = _author(fake, keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 0.333, "rotations": {"mid": [0, 0, 10]}}])
        assert out["end_frame"] == 10   # rounds up from 9.99
        main = [t for t in fake.tangents if t[0] == "|root|mid"]
        assert main and all(t[2] == pytest.approx((0.0, 9.99)) for t in main)

    def test_fractional_frames_and_unbound_skeleton_warn(self, fake):
        fake.bound = False
        fake.blend_aliases = []
        out = _author(fake, keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 0.333, "rotations": {"mid": [0, 0, 10]}}])
        assert any("between frames" in w for w in out["warnings"])
        assert any("moves no mesh" in w for w in out["warnings"])

    def test_clip_meta_reads_both_stored_shapes(self, fake):
        """#718: the attr is a LIST now, and a bare object (every scene
        authored before this change) reads as one record at frame 0."""
        _author(fake, name="idle")
        records = clip.clip_meta(fake, "|root")
        assert [r["name"] for r in records] == ["idle"]
        assert records[0]["start_frame"] == 0
        assert records[0]["end_frame"] == 30
        # the legacy shape, written by hand the way an old scene holds it
        fake.string_attrs["|root"]["mcp_clip"] = json.dumps(
            {"name": "old", "fps": 30, "duration_s": 1.0, "loop": False,
             "interpolation": "linear", "joints": ["mid"],
             "weight_channels": [], "root_position_used": False})
        records = clip.clip_meta(fake, "|root")
        assert [r["name"] for r in records] == ["old"]
        assert records[0]["start_frame"] == 0 and records[0]["end_frame"] == 30
        # unparseable is still name-only, still never a crash
        fake.string_attrs["|root"]["mcp_clip"] = "{not json"
        assert [r["name"] for r in clip.clip_meta(fake, "|root")] == ["{not json"]
        # no attr at all is an empty list, not None
        fake.string_attrs["|root"].pop("mcp_clip")
        assert clip.clip_meta(fake, "|root") == []


class TestSelfContainedTakes:
    """#718's correctness rule: at its own first and last frame, every clip
    keys EVERY channel any clip on the rig touches, at rest for the ones it
    does not mention. Both contamination directions are under test."""

    def _idle(self):
        return [{"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
                {"time_s": 1.0, "rotations": {"mid": [0, 0, 45]}}]

    def _walk(self):
        return [{"time_s": 0.0, "rotations": {"tip": [0, 0, 0]}},
                {"time_s": 1.0, "rotations": {"tip": [0, 0, 20]}}]

    def test_a_clip_pins_the_channels_it_does_not_mention(self, fake):
        _author(fake, name="idle", keys=self._idle())
        out = _author(fake, name="walk", keys=self._walk())
        assert out["padded_channels"] == ["mid"]
        # mid is keyed at BOTH of walk's boundary frames, at rest (0.0)
        keys = fake.keys["|root|mid.rotateZ"]
        assert keys[32.0] == 0.0 and keys[62.0] == 0.0

    def test_a_new_channel_back_fills_rest_at_every_earlier_boundary(self, fake):
        _author(fake, name="idle", keys=self._idle())
        out = _author(fake, name="walk", keys=self._walk())
        assert out["back_filled"] == {"clips": ["idle"], "channels": ["tip"]}
        # tip is pinned at rest across idle's whole range: idle measures
        # exactly what it measured before walk existed
        keys = fake.keys["|root|mid|tip.rotateZ"]
        assert keys[0.0] == 0.0 and keys[30.0] == 0.0

    def test_weight_channels_pin_at_zero_and_the_root_at_its_rest(self, fake):
        _author(fake, name="blinky", keys=[
            {"time_s": 0.0, "blend_weights": {"blink": 0.0},
             "root_position": [0.0, 1.0, 0.0]},
            {"time_s": 1.0, "blend_weights": {"blink": 1.0},
             "root_position": [0.0, 1.4, 0.0]}])
        _author(fake, name="still", keys=self._idle())
        assert fake.keys["body_shapes.blink"][32.0] == 0.0
        assert fake.keys["body_shapes.blink"][62.0] == 0.0
        # the root's rest translate is the bind position, captured before
        # the first clip keyed it
        assert fake.keys["|root.translateY"][32.0] == pytest.approx(1.0)

    def test_a_clip_that_mentions_a_channel_is_never_padded_over_it(self, fake):
        _author(fake, name="idle", keys=self._idle())
        out = _author(fake, name="more", keys=self._idle())
        assert out["padded_channels"] == []
        assert out["back_filled"] == {"clips": [], "channels": []}
        # the second clip's own motion survives at its own frames
        assert fake.keys["|root|mid.rotateZ"][62.0] == pytest.approx(45.0)

    def test_a_vanished_joint_warns_instead_of_crashing(self, fake):
        _author(fake, name="idle", keys=self._walk())      # keys 'tip'
        fake.joints.remove("|root|mid|tip")
        # renaming/deleting a keyed joint out of tool is not this tool's
        # problem to fix, but it must be SAID
        out = _author(fake, name="walk", keys=self._idle())
        assert any("tip" in w and "not under this root any more" in w
                   for w in out["warnings"]), out["warnings"]
        assert out["padded_channels"] == []

    def test_a_scene_with_no_rest_record_infers_it_and_says_so(self, fake):
        """The compatibility case: a clip authored before #718 left curves
        but no rest record, so the rest value is inferred from the earliest
        keyed value - WARNED, never silent."""
        _author(fake, name="old", keys=self._idle())
        fake.string_attrs["|root"].pop("mcp_clip_rest")
        out = _author(fake, name="new", keys=self._walk())
        assert any("no rest value was recorded" in w and "mid.rotateZ" in w
                   for w in out["warnings"]), out["warnings"]
        assert fake.keys["|root|mid.rotateZ"][32.0] == pytest.approx(0.0)

    def test_a_posed_rig_warns_that_rest_is_not_the_bind_pose(self, fake):
        """#718 review Fix 4: _capture_rest reads the rig's CURRENT pose,
        which is the bind pose only when nobody posed the rig first. A
        create_skeleton rest pose reads zero, so a non-zero capture is the
        measurable signal that this rig was posed (e.g. via pose_skeleton)
        before its first clip - and that has to be said, loudly."""
        fake.attrs["|root|mid.rotateZ"] = 10.0
        out = _author(fake, name="idle", keys=self._idle())
        assert any("CURRENT pose" in w and "mid" in w and "10" in w
                   for w in out["warnings"]), out["warnings"]

    def test_zero_rest_and_root_translation_never_warn(self, fake):
        """The rest pose that create_skeleton actually produces (all
        rotations zero) must not warn, and neither must root translation -
        a rig legitimately sits anywhere - nor a weight channel, which is
        recorded 0.0 by rule, never captured."""
        out = _author(fake, name="blinky", keys=[
            {"time_s": 0.0, "blend_weights": {"blink": 0.0},
             "root_position": [0.0, 1.0, 0.0]},
            {"time_s": 1.0, "blend_weights": {"blink": 1.0},
             "root_position": [0.0, 1.4, 0.0]}])
        assert not [w for w in out["warnings"] if "CURRENT pose" in w]

    def test_two_joints_sharing_a_short_name_warn_instead_of_guessing(
            self, fake):
        """#718 review Fix 3: a collision under `by_short` used to resolve
        to whichever joint happened to be seen first (`setdefault`),
        silently pinning/back-filling the WRONG joint. `idle` is authored
        while there is only one `mid`; a duplicate appears afterwards (an
        artist duplicating a chain, say) - exactly the scenario where
        clip metadata (short-name-keyed) can no longer tell the two
        apart. `walk`, authored after the duplicate exists, must report
        the ambiguity and skip the pin rather than guess."""
        _author(fake, name="idle", keys=self._idle())
        fake.joints.append("|root|mid|tip|mid")
        out = _author(fake, name="walk", keys=self._walk())
        assert "mid" not in out["padded_channels"]
        assert any("mid" in w and "ambiguous" in w for w in out["warnings"]
                  ), out["warnings"]

    # -- #718 review Fix 5: evaluated-pose tests, not key-placement tests --
    # FakeCmds.evaluate (above) models what a real animCurve reports between
    # keys; these tests read THROUGH it, which is the only way to observe
    # contamination rather than just where keys happen to sit.

    def test_forwards_contamination_evaluates_to_rest_across_the_gap(
            self, fake):
        _author(fake, name="idle", keys=self._idle())
        _author(fake, name="walk", keys=self._walk())
        # walk owns frames 32..62; mid is not walk's channel, so at every
        # frame across walk's own range it must read rest (0.0), not
        # idle's ending pose (45 degrees) bleeding forward.
        for frame in (32.0, 47.0, 62.0):
            assert fake.evaluate("|root|mid.rotateZ", frame) == \
                pytest.approx(0.0)

    def test_backwards_contamination_never_moves_an_earlier_clips_pose(
            self, fake):
        _author(fake, name="idle", keys=self._idle())
        before = [fake.evaluate("|root|mid.rotateZ", f)
                  for f in (0.0, 10.0, 20.0, 30.0)]
        _author(fake, name="walk", keys=self._walk())
        after_walk = [fake.evaluate("|root|mid.rotateZ", f)
                     for f in (0.0, 10.0, 20.0, 30.0)]
        assert after_walk == pytest.approx(before)
        # a third clip introducing a brand-new weight channel must not
        # move idle's already-measured pose either.
        _author(fake, name="blinky", keys=[
            {"time_s": 0.0, "blend_weights": {"blink": 0.0}},
            {"time_s": 1.0, "blend_weights": {"blink": 1.0}}])
        after_blinky = [fake.evaluate("|root|mid.rotateZ", f)
                       for f in (0.0, 10.0, 20.0, 30.0)]
        assert after_blinky == pytest.approx(before)

    def test_a_sparse_declared_channel_holds_its_own_value_not_rest(
            self, fake):
        """Fix 1 (wave 2): `walk` keys `mid` ONLY at its middle frame, not
        at either boundary. Wave 1 got the pin CONDITION right - `mid`
        being in walk's `mine["joints"]` does NOT exempt it from padding,
        since neither boundary carries a key. But the pin VALUE must not
        invent motion: `mid`'s only authored value inside walk's range is
        30 degrees, so both missing boundaries pin at 30 (flat across
        walk's whole range), not at rest - rest would rewrite walk's own
        sparse key into a rise-and-fall nobody authored. This was filed as
        RED against the wave-1 code, which pinned rest here."""
        _author(fake, name="idle", keys=self._idle())
        out = _author(fake, name="walk", keys=[
            {"time_s": 0.0, "rotations": {"tip": [0, 0, 0]}},
            {"time_s": 0.5, "rotations": {"mid": [0, 0, 30]}},
            {"time_s": 1.0, "rotations": {"tip": [0, 0, 20]}}])
        start, end = out["start_frame"], out["end_frame"]
        assert fake.evaluate("|root|mid.rotateZ", float(start)) == \
            pytest.approx(30.0)
        assert fake.evaluate("|root|mid.rotateZ", float(end)) == \
            pytest.approx(30.0)
        assert "mid" in out["held_channels"]
        assert "mid" not in out["padded_channels"]

    def test_a_channel_never_mentioned_still_pins_at_rest(self, fake):
        """The isolation case is unchanged by Fix 1: a channel `walk`
        never keys at all (no key anywhere in its own range, as opposed
        to the sparse case above) still pins at rest across walk's own
        range - only a channel walk DOES key somewhere in its range gets
        the own-held-value treatment. Guards against the fix
        over-reaching to channels with no authored value to hold."""
        _author(fake, name="idle", keys=self._idle())
        out = _author(fake, name="walk", keys=self._walk())   # never keys 'mid'
        for frame in (float(out["start_frame"]), float(out["end_frame"])):
            assert fake.evaluate("|root|mid.rotateZ", frame) == \
                pytest.approx(0.0)
        assert "mid" in out["padded_channels"]
        assert "mid" not in out["held_channels"]

    def test_the_fixture_default_keys_hold_their_own_value_not_rest(
            self, fake):
        """The repo's own `_author` default keys carry root_position only
        on the SECOND key, so a second clip authored with those defaults
        has root translate keyed at its own end boundary but not its
        start. Pinning REST there (the pre-fix behaviour) rewrites the
        clip's authored motion into a dip-then-climb; pinning at its own
        held value (1.05, the default key's value) keeps the span flat -
        exactly what a lone clip's curve would already hold there."""
        _author(fake)                      # idle, module defaults
        second = _author(fake, name="second")   # also module defaults
        start, end = second["start_frame"], second["end_frame"]
        mid_frame = (start + end) / 2.0
        for frame in (float(start), mid_frame, float(end)):
            assert fake.evaluate("|root.translateY", frame) == \
                pytest.approx(1.05)
        assert "root_position" in second["held_channels"]
        assert "root_position" not in second["padded_channels"]

    def test_padded_and_held_channels_partition_correctly(self, fake):
        """padded_channels (rest) and held_channels (own value) are
        reported separately, and a channel lands in exactly one: `walk`
        holds `mid` at its own sparse value but pins `root_position` -
        which it never mentions at all - at rest."""
        _author(fake, name="idle", keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]},
             "root_position": [0.0, 1.0, 0.0]},
            {"time_s": 1.0, "rotations": {"mid": [0, 0, 45]},
             "root_position": [0.0, 1.4, 0.0]}])
        out = _author(fake, name="walk", keys=[
            {"time_s": 0.0, "rotations": {"tip": [0, 0, 0]}},
            {"time_s": 0.5, "rotations": {"mid": [0, 0, 30]}},
            {"time_s": 1.0, "rotations": {"tip": [0, 0, 20]}}])
        assert set(out["held_channels"]) == {"mid"}
        assert set(out["padded_channels"]) == {"root_position"}
        assert not (set(out["held_channels"]) & set(out["padded_channels"]))

    # -- #718 review wave 3: end_frame = int(round(measured_end)) rounds
    # DOWN whenever the last key's fractional part is below 0.5, so a key
    # exactly on the clip's own final frame can sit outside the OLD
    # [start_frame, end_frame] window `own` was filtered by. Both tests
    # below key at 24 fps, time_s=0.6 -> frame 14.4 relative to the
    # clip's start - exactly the repro from the review.

    def test_round_down_held_value_is_not_flattened(self, fake):
        """`walk` keys `mid` at time_s 0.0 and 0.6 (24 fps): frames 0 and
        14.4 relative to its own start. end_frame rounds down to 14, short
        of the authored key at 14.4. The old `own` filter excluded 14.4,
        so the pin at end_frame fell back to `own[-1]` == the clip's
        FIRST value (0), flattening the whole take between the two keys -
        the curve read flat at 0 across 0..14 and only ramped up to 50 in
        the sliver between 14 and 14.4, outside the baked integer-frame
        take. `idle` runs first so `mid` is in `theirs` and padding
        actually runs for it (a lone first clip is never padded)."""
        _author(fake, name="idle", fps=24, keys=self._idle())
        out = _author(fake, name="walk", fps=24, keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 0.6, "rotations": {"mid": [0, 0, 50]}}])
        start, end = out["start_frame"], out["end_frame"]
        assert end == start + 14          # the rounds-down frame under test
        # the pinned end_frame must carry walk's own FINAL authored value,
        # not its first
        assert fake.evaluate("|root|mid.rotateZ", float(end)) == \
            pytest.approx(50.0)
        # and the take must not be flat: a middle frame sits strictly
        # between the first and last authored values, not pinned at the
        # first
        mid_val = fake.evaluate("|root|mid.rotateZ", float(start + 7))
        assert 0.0 < mid_val < 50.0
        assert "mid" in out["held_channels"]
        assert "mid" not in out["padded_channels"]

    def test_round_down_sparse_channel_is_held_not_rest(self, fake):
        """Same root cause, sparse variant: `mid` is keyed ONLY at the
        fractional time_s=0.6 (frame 14.4 relative), never at either of
        walk's own boundary frames. Under the old bound, that single key
        sits outside [start_frame, end_frame] entirely, so `own` came
        back empty and `_pad_boundaries` took the rest path - classifying
        a channel this clip genuinely animates as unanimated, and its
        authored value (35) never appears inside the baked take at all.
        `tip` is keyed at both ends so start/end_frame land where the
        repro needs them; it is incidental to what's under test here."""
        _author(fake, name="idle", fps=24, keys=self._idle())
        out = _author(fake, name="walk", fps=24, keys=[
            {"time_s": 0.0, "rotations": {"tip": [0, 0, 0]}},
            {"time_s": 0.6, "rotations": {"mid": [0, 0, 35],
                                          "tip": [0, 0, 20]}}])
        start, end = out["start_frame"], out["end_frame"]
        assert end == start + 14          # the rounds-down frame under test
        assert "mid" in out["held_channels"]
        assert "mid" not in out["padded_channels"]
        assert fake.keys["|root|mid.rotateZ"][float(start)] == \
            pytest.approx(35.0)
        assert fake.keys["|root|mid.rotateZ"][float(end)] == \
            pytest.approx(35.0)

    def test_reauthor_preserves_a_later_clips_evaluated_pose_and_vacates_cleanly(
            self, fake):
        _author(fake, name="idle", keys=self._idle())
        walk = _author(fake, name="walk", keys=self._walk())
        start, end = walk["start_frame"], walk["end_frame"]
        mid_frame = (start + end) / 2.0
        before = {
            plug: [fake.evaluate(plug, f)
                   for f in (float(start), mid_frame, float(end))]
            for plug in ("|root|mid|tip.rotateZ", "|root|mid.rotateZ")
        }
        _author(fake, name="idle", keys=self._idle())   # re-author, no-op for walk
        after = {
            plug: [fake.evaluate(plug, f)
                   for f in (float(start), mid_frame, float(end))]
            for plug in ("|root|mid|tip.rotateZ", "|root|mid.rotateZ")
        }
        assert after == before
        # the vacated range (idle's original 0-30) carries no keys at all,
        # on ANY plug.
        for plug, times in fake.keys.items():
            assert not any(0.0 <= t <= 30.0 for t in times), \
                (plug, times)


class TestDelete:
    def test_no_clip_refuses(self, fake):
        with pytest.raises(HandlerError, match="no clip"):
            clip.delete_clip({"root": "root"})

    def test_deletes_curves_metadata_and_measures(self, fake):
        _author(fake)
        out = clip.delete_clip({"root": "root"})
        assert out["clip"] == "idle"
        assert out["deleted_curves"] > 0
        assert not any(p.startswith("|root|mid.rotate") for p in fake.curves)
        assert "mcp_clip" not in fake.string_attrs.get("|root", {})
        assert fake.checkpoints == ["author_clip", "delete_clip"]

    def test_hand_authored_curves_delete_with_a_warning(self, fake):
        fake.curves["|root|mid.rotateZ"] = "hand_crv"
        fake.keys["|root|mid.rotateZ"] = {0.0: 1.0}
        out = clip.delete_clip({"root": "root"})
        assert out["clip"] is None
        assert any("no clip metadata" in w for w in out["warnings"])


class TestGuards:
    def test_static_pose_guard_names_the_clip(self, fake):
        _author(fake)
        with pytest.raises(HandlerError, match="clip 'idle'"):
            clip.guard_static_pose(fake, "|root",
                                   ["|root", "|root|mid", "|root|mid|tip"],
                                   "pose_skeleton")

    def test_static_weight_guard(self, fake):
        _author(fake, keys=[
            {"time_s": 0.0, "blend_weights": {"blink": 0.0}},
            {"time_s": 1.0, "blend_weights": {"blink": 0.0}}])
        with pytest.raises(HandlerError, match="animation curves"):
            clip.guard_static_weights(fake, "body_shapes", ["blink"],
                                      "set_blendshape_weights")

    def test_clean_scene_passes_both_guards(self, fake):
        clip.guard_static_pose(fake, "|root", ["|root"], "pose_skeleton")
        clip.guard_static_weights(fake, "body_shapes", ["blink"], "x")


class TestPreviewClip:
    """preview_clip picks frames and delegates to render._run_shots; the
    render loop itself is render.py's tested code. The seam is monkeypatched
    and its SHOTS are asserted - fixed camera, every-nth frames, first and
    last always included."""

    def _wire(self, fake, monkeypatch, duration_s=2.0, fps=30):
        _author(fake, name="idle", fps=fps, keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": duration_s, "rotations": {"mid": [0, 0, 0]}}])
        calls = {}

        def run_shots(cmds, shots, params):
            calls["shots"] = shots
            calls["params"] = params
            return {"images": [{"label": s["label"], "angle": s["angle"],
                                "png_b64": "x"} for s in shots],
                    "renderer": "hw2", "samples": 1, "fallback_light": False,
                    "zoom": 1.0, "relit_lights": 0}

        monkeypatch.setattr(clip.render, "_run_shots", run_shots)
        return calls

    def test_refusals(self, fake, monkeypatch):
        with pytest.raises(HandlerError, match="no clip"):
            clip.preview_clip({"root": "root", "name": "idle"})
        self._wire(fake, monkeypatch)
        with pytest.raises(HandlerError, match="live clip is 'idle'"):
            clip.preview_clip({"root": "root", "name": "walk"})
        with pytest.raises(HandlerError, match="unknown angle"):
            clip.preview_clip({"root": "root", "name": "idle",
                               "angle": "dutch"})
        with pytest.raises(HandlerError, match="every_nth"):
            clip.preview_clip({"root": "root", "name": "idle",
                               "every_nth": 0})

    def test_default_stride_fits_the_cap_and_keeps_the_ends(self, fake,
                                                            monkeypatch):
        calls = self._wire(fake, monkeypatch, duration_s=2.0, fps=30)
        out = clip.preview_clip({"root": "root", "name": "idle"})
        frames = [f["frame"] for f in out["frames"]]
        assert frames[0] == 0 and frames[-1] == 60
        assert len(frames) <= clip.MAX_PREVIEW_FRAMES
        shots = calls["shots"]
        assert shots[0]["time"] == 0 and shots[-1]["time"] == 60
        assert not shots[0].get("reuse_camera")
        assert all(s.get("reuse_camera") for s in shots[1:])
        assert all(s["frame_on"] == ["|body"] for s in shots)

    def test_explicit_stride_that_overflows_refuses(self, fake, monkeypatch):
        self._wire(fake, monkeypatch, duration_s=2.0, fps=30)
        with pytest.raises(HandlerError, match="%d frame"
                           % clip.MAX_PREVIEW_FRAMES):
            clip.preview_clip({"root": "root", "name": "idle",
                               "every_nth": 1})

    def test_current_time_is_restored(self, fake, monkeypatch):
        self._wire(fake, monkeypatch)
        fake.time = 7.0
        clip.preview_clip({"root": "root", "name": "idle"})
        assert fake.time == 7.0

    def test_unbound_skeleton_refuses(self, fake, monkeypatch):
        self._wire(fake, monkeypatch)
        fake.bound = False
        with pytest.raises(HandlerError, match="moves no mesh"):
            clip.preview_clip({"root": "root", "name": "idle"})

    def test_default_stride_never_self_refuses_on_the_forced_last_frame(
            self, fake, monkeypatch):
        """Finding 1 (#695 review): the old auto search sized itself with
        duration_frames // every_nth + 1, which is the length of the
        unpadded stride - it never accounted for the unconditional append
        of the last frame when the stride doesn't land on it exactly. That
        undercount let the search accept a stride whose PADDED list still
        overflows the cap, so a default (no every_nth) call could self-
        refuse with a confusing "every_nth=N yields 17 frames" error.
        duration_frames=31 (fps=30, duration_s=31/30) reproduces it: the
        old search accepted every_nth=2 (31//2+1 == 16), but
        range(0, 32, 2) ends at 30, forcing an append to 31 and landing at
        17 frames - one over the cap."""
        calls = self._wire(fake, monkeypatch, duration_s=31.0 / 30.0,
                           fps=30)
        out = clip.preview_clip({"root": "root", "name": "idle"})
        frames = [f["frame"] for f in out["frames"]]
        assert len(frames) <= clip.MAX_PREVIEW_FRAMES
        assert frames[0] == 0
        assert frames[-1] == 31
        assert calls["shots"][-1]["time"] == 31

    def test_explicit_stride_still_refuses_with_the_measured_count(
            self, fake, monkeypatch):
        """An explicitly-passed every_nth that overflows once the forced
        last frame is counted must still refuse, carrying the MEASURED
        frame count (17, not the old formula's 16)."""
        self._wire(fake, monkeypatch, duration_s=31.0 / 30.0, fps=30)
        with pytest.raises(HandlerError, match="every_nth=2 yields 17 "
                           "frames"):
            clip.preview_clip({"root": "root", "name": "idle",
                               "every_nth": 2})

    def test_reasserts_the_clips_own_time_unit(self, fake, monkeypatch):
        """Finding 2 (#695 review): a different clip authored since (or a
        scene opened after this clip's metadata was written) can leave the
        scene-global time unit stale relative to THIS clip's fps. The
        reported time_s values only mean what they claim if the unit
        matches the clip's own fps at render time."""
        self._wire(fake, monkeypatch, duration_s=2.0, fps=30)
        fake.time_unit = "film"   # stale - as if a 24fps clip ran since
        fake.time_unit_calls = []
        clip.preview_clip({"root": "root", "name": "idle"})
        assert fake.time_unit_calls == ["ntsc"]
        assert fake.time_unit == "ntsc"

    def test_a_refused_call_never_reasserts_the_time_unit(self, fake,
                                                           monkeypatch):
        """#695: the currentUnit(time=...) call moved to run only after
        every validation passes, so a refused call must not have touched
        the scene-global time unit at all - covers a validation refusal
        (bad angle), a cap refusal (every_nth over the limit), and the
        unbound-skeleton refusal, which is the check immediately before
        the (moved) currentUnit call."""
        self._wire(fake, monkeypatch, duration_s=2.0, fps=30)
        fake.time_unit_calls = []
        with pytest.raises(HandlerError, match="unknown angle"):
            clip.preview_clip({"root": "root", "name": "idle",
                               "angle": "dutch"})
        assert fake.time_unit_calls == []
        with pytest.raises(HandlerError, match="every_nth"):
            clip.preview_clip({"root": "root", "name": "idle",
                               "every_nth": 1})
        assert fake.time_unit_calls == []
        fake.bound = False
        with pytest.raises(HandlerError, match="moves no mesh"):
            clip.preview_clip({"root": "root", "name": "idle"})
        assert fake.time_unit_calls == []


class TestRigidParentRig:
    """#720: a rig whose chunks are parented under joints with NO skinCluster
    (#713's golem) is a legal rig, not an empty one. It used to report
    max_displacement 0 - an echo (#636) - and preview_clip refused it
    outright.
    """

    def _rigid(self, monkeypatch):
        return _install(
            FakeCmds(bound=False, rigid_chunks={"|root|mid": "|root|mid|chunk"}),
            monkeypatch)

    def test_author_measures_the_chunk_it_moves(self, monkeypatch):
        fake = self._rigid(monkeypatch)
        # The fixture's _points seam moves its vertex with |root.rotateX, so
        # keying the root is what makes a measurable displacement exist at
        # all; a zero here means the chunk was never found (#636).
        out = _author(fake, keys=[
            {"time_s": 0.0, "rotations": {"root": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"root": [30, 0, 0]}}])
        assert max(k["max_displacement"] for k in out["per_key"]) > 0.0
        assert not [w for w in out["warnings"] if "mesh" in w]

    def test_preview_renders_it(self, monkeypatch):
        fake = self._rigid(monkeypatch)
        _author(fake, keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"mid": [0, 0, 45]}}])
        calls = {}

        def run_shots(cmds, shots, params):
            calls["shots"] = shots
            return {"images": [{"label": s["label"], "angle": s["angle"],
                                "png_b64": "x"} for s in shots],
                    "renderer": "hw2", "samples": 1, "fallback_light": False,
                    "zoom": 1.0, "relit_lights": 0}

        monkeypatch.setattr(clip.render, "_run_shots", run_shots)
        out = clip.preview_clip({"root": "root", "name": "idle"})
        assert out["clip"] == "idle"
        assert all(s["frame_on"] == ["|root|mid|chunk"] for s in calls["shots"])

    def test_a_skeleton_that_moves_nothing_still_refuses_naming_both_shapes(
            self, monkeypatch):
        """The refusal survives - it just has to be true. Bare joints render
        nothing whether or not a skinCluster was the missing piece."""
        fake = _install(FakeCmds(bound=False), monkeypatch)
        _author(fake, keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"mid": [0, 0, 45]}}])
        with pytest.raises(HandlerError, match="moves no mesh") as excinfo:
            clip.preview_clip({"root": "root", "name": "idle"})
        assert "parented" in str(excinfo.value)

    def test_author_warns_only_when_nothing_moves(self, monkeypatch):
        fake = _install(FakeCmds(bound=False), monkeypatch)
        out = _author(fake, keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"mid": [0, 0, 45]}}])
        assert [w for w in out["warnings"] if "moves no mesh" in w]
