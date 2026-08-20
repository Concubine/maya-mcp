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

    def __init__(self, bound=True):
        self.joints = ["|root", "|root|mid", "|root|mid|tip"]
        self.bound = bound
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
                      type=None, fullPath=False, **kw):
        if children and type == "joint":
            kids = [j for j in self.joints
                    if j.rsplit("|", 1)[0] == node and j != node]
            return kids or None
        if shapes:
            return ["|body|bodyShape"] if node == "|body" else None
        if parent:
            return ["|body"] if node == "|body|bodyShape" else None
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
    def getAttr(self, key):
        if key.endswith(".mcp_clip"):
            node = key.rsplit(".", 1)[0]
            return self.string_attrs[node]["mcp_clip"]
        return self.attrs.get(key, 0.0)

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

    def keyTangent(self, node, attribute=None, edit=False,
                   inTangentType=None, outTangentType=None):
        self.tangents.append((node, attribute, inTangentType, outTangentType))

    def keyframe(self, plug, query=False, **kw):
        return sorted(self.keys.get(plug, {})) or None

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


@pytest.fixture
def fake(monkeypatch):
    fake = FakeCmds()
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
        meta = json.loads(fake.string_attrs["|root"]["mcp_clip"])
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

    def test_replacing_warns_and_deletes_the_old_curves(self, fake):
        _author(fake, name="idle")
        old = set(fake.deleted)
        out = _author(fake, name="walk")
        assert out["replaced"] == "idle"
        assert any("replaced clip 'idle'" in w for w in out["warnings"])
        assert len(fake.deleted) > len(old)

    def test_tangent_mapping(self, fake):
        _author(fake, interpolation="smooth")
        assert fake.tangents and all(t[2] == "auto" and t[3] == "auto"
                                     for t in fake.tangents)
        fake2_keys = fake.tangents[:]
        _author(fake, name="lin", interpolation="linear")
        new = fake.tangents[len(fake2_keys):]
        assert new and all(t[2] == "linear" for t in new)

    def test_fractional_frames_and_unbound_skeleton_warn(self, fake):
        fake.bound = False
        fake.blend_aliases = []
        out = _author(fake, keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 0.333, "rotations": {"mid": [0, 0, 10]}}])
        assert any("between frames" in w for w in out["warnings"])
        assert any("no skinned mesh" in w for w in out["warnings"])


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
        with pytest.raises(HandlerError, match="no skinned mesh"):
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
        with pytest.raises(HandlerError, match="no skinned mesh"):
            clip.preview_clip({"root": "root", "name": "idle"})
        assert fake.time_unit_calls == []
