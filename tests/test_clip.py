"""author_clip / delete_clip (#695, #718) under a FakeCmds.

Real curve evaluation is mayapy's job (tests/test_handlers_mayapy.py); this
file pins validation, the #718 self-contained-takes rule (a clip pins every
channel it does not declare at its own boundaries, and back-fills a channel
it introduces across every earlier clip's own boundaries), append/re-author/
delete across MULTIPLE clips sharing one timeline, the foreign-curve
refusal, metadata (both the #718 list shape and the pre-#718 bare-object
shape), measured per-key displacement (via the _points seam and a linear
fake), tangent mapping, and delete_clip's teardown (partial - one clip out
of several - and full).
"""

import json
import re

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
        self.cut_plugs = []       # every plug cutKey was aimed at (#796)
        self.connection_queries = []   # every listConnections plug, in order
        self.checkpoints = []
        self.blend_aliases = ["blink"] if bound else []
        self.time_unit_calls = []   # every currentUnit(time=...) issued
        # #796 review round 3 M2. EMPTY by default: dagPose(query=True,
        # bindPose=True) answering [] is the no-bind-pose teardown path,
        # which is the only one any test before this round exercised - so
        # delete_clip's BOUND branch, the common one in a real scene (any
        # skinCluster gives the rig a bind pose), was never executed here
        # at all. Tests set this to reach it.
        self.bind_poses = []
        self.dag_pose_restores = []      # every dagPose(restore=True) target
        self.dag_pose_restored = []      # joints the restore actually moved
        # Which of #796's two unmeasured outcomes the restore takes when it
        # meets a connection-fed plug: True = (a) it raises, False = (b) it
        # silently skips that joint. delete_clip must be right under both.
        self.dag_pose_restore_raises = False
        # The OTHER unmeasured outcome (#796 review round 4 B): whether a
        # setKeyframe aimed at a plug an INTERMEDIARY feeds (a pairBlend, a
        # unitConversion, an anim-layer blend node) lands on the curve
        # behind that node or is swallowed the way a driven key's is.
        # Default False - the behaviour author_clip had before #796, which
        # a fix must not regress; the tests that care flip it and assert
        # the handler is honest under both.
        self.blend_swallows_keys = False

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
        return (bool(self.ls(name)) or name in ("body_shapes", "body_skin")
                or name in self.rigid_chunks.values())

    def nodeType(self, node):
        # #796 review: real Maya raises "No object matches name" for a node
        # that no longer exists. The fake used to fall through to
        # "transform" for anything unknown, which is precisely why a
        # classify-after-delete regression was invisible here.
        if node in self.deleted:
            raise RuntimeError("No object matches name: %s" % node)
        if node in self.joints:
            return "joint"
        if node == "body_shapes":
            return "blendShape"
        override = getattr(self, "node_types", {}).get(node)
        if override:
            return override
        if node in self.curves.values():
            return "animCurveTU"
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

    def listAttr(self, plug, multi=False, keyable=False):
        if plug.startswith("body_shapes"):
            return list(self.blend_aliases) or None
        if keyable:
            # #796 review round 6 D: what `bakeResults` writes when it is
            # given no `-attribute` flag - every KEYABLE channel, which is
            # wider than the rotate/translate the retarget guard used to
            # ask about. A joint's real answer, plus whatever a rigger
            # added: `keyable_extras` is how a test hands this fake a
            # user-defined keyable attribute.
            if plug not in self.joints:
                return None
            return (["visibility"]
                    + ["translate" + ax for ax in "XYZ"]
                    + ["rotate" + ax for ax in "XYZ"]
                    + ["scale" + ax for ax in "XYZ"]
                    + list(getattr(self, "keyable_extras", {}).get(plug, [])))
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

    def _connected_child(self, plug):
        """The plug a connection feeds that would make `plug` unwritable,
        or None. #796 review: Maya refuses setAttr on a connected plug AND
        on a compound whose child is connected, and the fake never modelled
        that - so a teardown that leaves a curve standing and then writes
        the plug it feeds looked fine here and raises in Maya."""
        fed = set(self.curves) | set(getattr(self, "driven_plugs", {}))
        if plug in fed:
            return plug
        node, _, attr = plug.rpartition(".")
        if attr in ("rotate", "translate"):
            for child in ("%s.%s%s" % (node, attr, ax) for ax in "XYZ"):
                if child in fed:
                    return child
        elif attr[:-1] in ("rotate", "translate") and attr[-1] in "XYZ":
            if "%s.%s" % (node, attr[:-1]) in fed:
                return "%s.%s" % (node, attr[:-1])
        return None

    def setAttr(self, key, *values, **kw):
        if kw.get("type") == "string":
            node, attr = key.rsplit(".", 1)
            self.string_attrs.setdefault(node, {})[attr] = values[0]
            return
        blocker = self._connected_child(key)
        if blocker:
            raise RuntimeError(
                "setAttr: The attribute '%s' is locked or connected and "
                "cannot be modified." % blocker)
        if len(values) == 3:
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

    def _static_write_blocker(self, node):
        """The connection that makes a worldSpace `xform` TRANSLATION write
        on `node` raise, or None.

        A plug's OWN time-based animCurve is NOT one: author_clip keys the
        root on one key and xforms it again on the next, and that is the
        path every root-motion clip in this repo takes today - modelling a
        keyed plug as unwritable here would assert a failure real Maya does
        not have. A pairBlend, an anim layer or a driven key IS one: those
        are exactly the connections `setAttr` refuses above, and an
        `xform -translation` is a static write to the same plugs.
        """
        driven = getattr(self, "driven_plugs", {})
        for plug in ([node + ".translate"]
                     + [node + ".translate" + ax for ax in "XYZ"]):
            if plug in driven:
                return driven[plug]
            curve = self.curves.get(plug)
            if curve and self._recorded_type(curve).startswith("animCurveU"):
                return curve
        return None

    def xform(self, node, query=False, worldSpace=False, translation=None,
              **kw):
        if query:
            return [self.attrs.get(node + ".translateX", 0.0),
                    self.attrs.get(node + ".translateY", 0.0),
                    self.attrs.get(node + ".translateZ", 0.0)]
        # #796 review round 6 A: the refusal `setAttr` has always modelled,
        # on the OTHER static write this module makes. author_clip's
        # root_position path calls xform on the very translate plugs
        # `guard_declared_channels` decided only to WARN about, and the
        # fake answering happily is the only reason a traceback on a
        # keyed-and-constrained root was invisible in this file.
        blocker = self._static_write_blocker(node)
        if blocker:
            raise RuntimeError(
                "xform: The attribute '%s.translate' is locked or connected "
                "and cannot be modified (%s feeds it)" % (node, blocker))
        for axis, v in zip("XYZ", translation):
            self.attrs[node + ".translate" + axis] = float(v)

    # --- animation -------------------------------------------------------
    def _keyframe_blocker(self, plug):
        """The connection that makes setKeyframe on `plug` a SILENT no-op,
        or None.

        MEASURED in #771 (evals/correctives_probe/): setKeyframe on a plug
        a poseInterpolator feeds returns 0 and creates nothing - no curve,
        no key, no error - and a U-typed driven-key curve feeds a plug
        through the same connection shape. The fake did not model that,
        which is exactly why round 3 found author_clip keying straight
        through a set-driven key and still writing mcp_clip declaring that
        joint keyed: the fake could not represent the failure, so no test
        could see it (#796 review round 3 M1).

        A plug's own TIME-based curve is NOT a blocker - re-keying that is
        author_clip's normal append/replace path. A U-typed one is: it is
        a driven key reading a driver attribute.

        An INTERMEDIARY (pairBlend, unitConversion, anim-layer blend node)
        is not a blocker by default: nobody has measured one, Maya inserts
        a pairBlend the moment a plug is both keyed AND constrained, and
        author_clip re-authored exactly that rig normally before #796 - so
        modelling it as a silent no-op made the fake assert an unmeasured
        failure, and a guard built on that assertion refused a rig that
        works (#796 review round 4 B). `blend_swallows_keys` flips the
        fake to the other outcome.
        """
        driven = getattr(self, "driven_plugs", {})
        source = driven.get(plug)
        if source is None:
            node, _, attr = plug.rpartition(".")
            # An anim layer lands on the COMPOUND and reaches all three
            # children - the same asymmetry _connected_child models for
            # setAttr.
            if attr[:-1] in ("rotate", "translate") and attr[-1] in "XYZ":
                source = driven.get("%s.%s" % (node, attr[:-1]))
        if source is None:
            curve = self.curves.get(plug)
            if curve and self._recorded_type(curve).startswith("animCurveU"):
                return curve
            return None
        kind = self._recorded_type(source.split(".")[0])
        if kind.startswith("animCurveU") or kind == "poseInterpolator":
            return source
        return source if self.blend_swallows_keys else None

    def _recorded_type(self, node):
        """`nodeType` without its "was deleted" raise. A cutKey can empty
        and delete a curve, and the next setKeyframe re-creates one under
        the same generated name - which is a NEW node, not a resurrection,
        so asking nodeType here would raise on a perfectly live curve."""
        override = getattr(self, "node_types", {}).get(node)
        if override:
            return override
        return "animCurveTU" if node in self.curves.values() else ""

    def setKeyframe(self, node, attribute=None, time=None, value=None):
        plug = "%s.%s" % (node, attribute)
        if self._keyframe_blocker(plug):
            return 0        # measured: no curve, no key, and no error
        # No dot in the generated name: real Maya node names cannot carry
        # one, and the #771 classifier splits "node.attr" sources on it.
        self.curves.setdefault(
            plug, plug.replace("|", "_").replace(".", "_") + "_crv")
        self.keys.setdefault(plug, {})[float(time)] = float(value)
        return 1

    def keyTangent(self, node, attribute=None, edit=False, time=None,
                   inTangentType=None, outTangentType=None):
        self.tangents.append(
            (node, attribute, time, inTangentType, outTangentType))

    def keyframe(self, plug, query=False, **kw):
        return sorted(self.keys.get(plug, {})) or None

    def cutKey(self, plug, time=None, clear=False, **kw):
        self.cut_plugs.append(plug)
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
                        type=None, plugs=False):
        # Every query, in order. The cycle test asserts on the COUNT per
        # node: a depth bound alone terminates the walk, so only "this node
        # was never queried twice" distinguishes a live cycle guard from a
        # deleted one (#796 review).
        self.connection_queries.append(plug)
        # #796: a node a real scene can hold but not answer for (a broken
        # reference, a node deleted mid-query). A guard must degrade, not
        # crash, on one of these.
        if plug.split(".")[0] in getattr(self, "unqueryable", ()):
            raise RuntimeError("no such node: %s" % plug)
        # #771: a corrective-driven plug - a non-animCurve source that the
        # driven-channel refusal must classify by nodeType.
        driven = getattr(self, "driven_plugs", {})
        if plug in driven:
            if type is None:
                src = driven[plug]
                return [src] if plugs else [src.split(".")[0]]
            return None
        # #796: the upstream side of an intermediary node. A curve reaching
        # a plug THROUGH a pairBlend answers HERE and never from the direct
        # type="animCurve" query on the plug itself - which is the whole
        # defect.
        sources = getattr(self, "node_sources", {})
        if source and plug in sources:
            ups = [u for u in sources[plug]
                   if type is None or self.nodeType(u).startswith(type)]
            return ups or None
        curve = self.curves.get(plug)
        if curve:
            return [curve + ".output"] if plugs else [curve]
        # Maya's compound/child asymmetry, BOTH directions (#796 review
        # defect 4): a query on a CHILD plug does not report a connection
        # made on its PARENT compound - which is where a rotation anim
        # layer lands - while a query on the compound DOES report its
        # children's connections. The fake used to answer nothing in either
        # direction, so a guard blind to compound wiring looked fine here.
        node, _, attr = plug.rpartition(".")
        if source and attr in ("rotate", "translate"):
            found = []
            for child in ("%s.%s%s" % (node, attr, ax) for ax in "XYZ"):
                found.extend(self.listConnections(
                    child, source=source, destination=destination,
                    type=type, plugs=plugs) or [])
            return found or None
        return None

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

    def exactWorldBoundingBox(self, *targets, **kw):
        # A unit-deep box that RIDES the current time along X - the minimal
        # model of a clip with root motion. A caller that claims to frame
        # the whole clip must union this box across frames; framing frame
        # 0's box alone loses the subject (#780).
        return [self.time, 0.0, 0.0, self.time + 1.0, 2.0, 1.0]

    def playbackOptions(self, edit=False, **kw):
        self.playback.update(kw)

    def dagPose(self, *args, **kw):
        """query -> `bind_poses`; restore -> one of #796's two outcomes.

        `dag_pose_restore_raises` picks between them: (a) the restore
        RAISES, or (b) it silently skips the connection-fed joints and
        restores the rest. Nobody has measured which real Maya does, so
        the fake models both and delete_clip has to survive either. In
        (a) nothing is restored - the worst case for a caller, and the
        one that used to kill the teardown after the curves were already
        deleted.
        """
        if kw.get("query"):
            return list(self.bind_poses)
        if kw.get("restore"):
            self.dag_pose_restores.append(args[0] if args else None)
            if self.dag_pose_restore_raises:
                raise RuntimeError(
                    "dagPose: cannot restore - a destination plug is "
                    "locked or connected and cannot be modified")
            for j in self.joints:
                if self._connected_child(j + ".rotate") or \
                        self._connected_child(j + ".translate"):
                    continue    # outcome (b): skipped, silently
                self.attrs[j + ".rotate"] = (0.0, 0.0, 0.0)
                self.dag_pose_restored.append(j)
        return []


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


def _plant_sdk_curve(fake, plug="|root|mid|tip.rotateX",
                     curve="tip_rotX_driven", node_type="animCurveUA"):
    """A set-driven key on a joint plug: a curve node of a U-typed type,
    which reads a DRIVER attribute rather than time. listConnections
    type="animCurve" returns it exactly like a clip curve (the filter
    matches DERIVED types), which is the #796 defect-1 trap."""
    fake.curves[plug] = curve
    fake.node_types = dict(getattr(fake, "node_types", {}),
                           **{curve: node_type})
    return curve


def _plant_blend_curve(fake, plug, blend="mid_pairBlend",
                       curve="mid_rotX_crv", blend_type="pairBlend",
                       curve_type="animCurveTA"):
    """A curve that reaches `plug` THROUGH an intermediary node (#796
    defect 2): the plug's DIRECT animCurve query sees nothing at all, its
    only source is the blend node, and the curve hangs off that."""
    fake.driven_plugs = dict(getattr(fake, "driven_plugs", {}),
                             **{plug: blend + ".output"})
    fake.node_types = dict(getattr(fake, "node_types", {}),
                           **{blend: blend_type, curve: curve_type})
    fake.node_sources = dict(getattr(fake, "node_sources", {}),
                             **{blend: [curve]})
    return curve


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

    def test_a_set_driven_key_is_not_a_foreign_clip_curve(self, fake):
        # #796 review defect 3: this refusal counted the U-typed SDK curves
        # as "hand-authored animation this tool did not author" and pointed
        # at delete_clip, which now refuses the same rig with "no clip
        # exists" and a hint saying it never removes them. A rig carrying a
        # driven key and no clip could author no first clip, and each tool
        # named the other as the fix - a closed loop.
        sdk = _plant_sdk_curve(fake)
        out = _author(fake)
        assert out["clip"] == "idle"
        assert sdk in fake.curves.values()   # rig setup untouched

    def test_the_foreign_curve_hint_stays_true_of_delete_clip(self, fake):
        # The hint sends the caller to delete_clip, so the curves it counts
        # have to be curves delete_clip actually removes.
        fake.curves["|root|mid.rotateZ"] = "hand_authored_crv"
        _plant_sdk_curve(fake)
        with pytest.raises(HandlerError) as exc:
            _author(fake)
        assert "1 hand-authored" in str(exc.value)
        assert "tip_rotX_driven" not in str(exc.value)

    def test_a_declared_joint_channel_with_a_driven_key_refuses(self, fake):
        # #796 review round 3 M1. Round 2 narrowed the foreign-curve check
        # to the CLIP partition, which was right - a driven key SOMEWHERE
        # on the rig must not block a first clip - but it left the joint
        # side with no per-channel guard at all, and the weight side is the
        # only one that had one. author_clip then keyed a plug a driven key
        # feeds: the write returns 0 and creates nothing, and the handler
        # still wrote mcp_clip declaring that joint keyed.
        sdk = _plant_sdk_curve(fake, plug="|root|mid.rotateZ",
                               curve="mid_rotZ_driven")
        with pytest.raises(HandlerError) as exc:
            _author(fake)               # the default keys declare 'mid'
        message, hint = str(exc.value), exc.value.hint
        assert "|root|mid.rotateZ" in message      # the CHANNEL, by name
        assert sdk in message                      # and the curve
        assert "set-driven key" in message
        # The hint has to be true of the tools it names: since #796
        # delete_clip explicitly does NOT remove a driven key, so pointing
        # there would be the closed loop round 2 just opened.
        assert "delete_clip does NOT remove a driven key" in hint
        assert "pose the DRIVER attribute" in hint
        assert fake.checkpoints == []              # refused before mutating

    def test_the_clip_never_ships_declaring_a_channel_the_key_missed(
            self, fake):
        # What makes that a refusal rather than a warning, MEASURED in #771
        # and modelled by the fake only as of this round: the write does
        # not land and does not complain.
        _plant_sdk_curve(fake, plug="|root|mid.rotateZ",
                         curve="mid_rotZ_driven")
        with pytest.raises(HandlerError):
            _author(fake)
        assert fake.setKeyframe("|root|mid", attribute="rotateZ",
                                time=0.0, value=45.0) == 0
        assert "|root|mid.rotateZ" not in fake.keys

    def test_a_driven_key_on_an_undeclared_channel_never_blocks(self, fake):
        # The other half: the loop round 2 fixed stays fixed. The refusal
        # is PER CHANNEL, so rig setup on a channel this clip never touches
        # is none of author_clip's business.
        sdk = _plant_sdk_curve(fake)               # |root|mid|tip.rotateX
        out = _author(fake)                        # declares 'mid' only
        assert out["clip"] == "idle"
        assert fake.keys["|root|mid.rotateZ"]      # the declared key landed
        assert sdk in fake.curves.values()         # rig setup untouched

    def test_an_anim_layer_on_the_compound_is_reported_not_refused(
            self, fake):
        # #796 review defect 4's asymmetry, now on the author side: a
        # rotation anim layer lands on `.rotate`, and a query on `.rotateX`
        # reports nothing - so a child-only guard never sees this shape at
        # all. What it DOES about it changed in round 4 (defect B): an
        # anim-layer blend node classifies as "other", nobody has MEASURED
        # that setKeyframe fails to land through one, and before #796
        # author_clip re-authored this rig normally. Refusing it was a
        # regression; the channel is keyed and the layer is NAMED.
        fake.driven_plugs = {"|root|mid.rotate": "layer_blend.output"}
        fake.node_types = {"layer_blend": "animBlendNodeAdditiveRotation"}
        out = _author(fake)
        assert out["clip"] == "idle"
        assert fake.keys["|root|mid.rotateZ"]          # today's behaviour
        notes = [w for w in out["warnings"]
                 if "|root|mid.rotate is driven by layer_blend.output" in w]
        assert len(notes) == 1        # the compound names ONE channel, once

    def test_a_pair_blend_on_a_declared_channel_does_not_refuse(self, fake):
        # #796 review round 4 B. Maya inserts a pairBlend the moment a plug
        # is both keyed AND constrained (this module's own
        # `_curve_behind_a_blend` says so), setKeyframe lands on the
        # animCurve behind it, and author_clip re-authored such a rig
        # normally before this ticket. Refusing it with "disconnect that
        # source" is a REGRESSION, not a fix.
        curve = _plant_blend_curve(fake, "|root|mid.rotateZ",
                                   curve="mid_rotZ_crv")
        out = _author(fake)
        assert out["clip"] == "idle"
        assert fake.keys["|root|mid.rotateZ"]
        assert any("%s behind mid_pairBlend" % curve in w
                   for w in out["warnings"])

    def test_the_blend_diagnosis_is_the_one_guard_static_pose_gives(
            self, fake):
        # ONE scene, ONE diagnosis: author_clip used to name the
        # intermediary and say "disconnect that source" while
        # guard_static_pose walked it and named the CURVE - the
        # wrong-diagnosis class refuse_driven_weight's docstring exists to
        # prevent.
        curve = _plant_blend_curve(fake, "|root|mid.rotateZ",
                                   curve="mid_rotZ_crv")
        notes = _author(fake)["warnings"]
        with pytest.raises(HandlerError) as exc:
            clip.guard_static_pose(fake, "|root", TestGuards.JOINTS,
                                   "pose_skeleton")
        phrase = "%s behind mid_pairBlend" % curve
        assert phrase in str(exc.value)
        assert any(phrase in w for w in notes)

    def test_the_unmeasured_swallowed_key_still_reaches_the_caller(
            self, fake):
        # The other outcome of the live question: IF a key does not land
        # through a pairBlend, the clip ships declaring a channel it never
        # keyed. Not refusing is the choice that cannot regress a working
        # rig - which is exactly why the warning is not optional.
        fake.blend_swallows_keys = True
        _plant_blend_curve(fake, "|root|mid.rotateZ", curve="mid_rotZ_crv")
        out = _author(fake)
        assert "|root|mid.rotateZ" not in fake.keys
        assert any("mid_pairBlend" in w for w in out["warnings"])

    def test_a_sibling_axis_driven_key_is_named_as_itself(self, fake):
        # The compound is asked ONLY when no child answered. Asking it
        # first would report a free axis as blocked and name the wrong
        # channel in the refusal - the compound reports its children's
        # connections too.
        _plant_sdk_curve(fake, plug="|root|mid.rotateZ",
                         curve="mid_rotZ_driven")
        with pytest.raises(HandlerError) as exc:
            _author(fake)
        assert "|root|mid.rotate is" not in str(exc.value)
        assert "|root|mid.rotateZ is" in str(exc.value)

    def test_a_driven_root_translation_refuses_only_when_the_clip_moves_it(
            self, fake):
        # root_position keys the root's TRANSLATE channels, so those are
        # declared channels too - and a clip that leaves the root alone
        # never declares them.
        _plant_sdk_curve(fake, plug="|root.translateY",
                         curve="root_ty_driven")
        with pytest.raises(HandlerError) as exc:
            _author(fake)               # the default keys move the root
        assert "|root.translateY" in str(exc.value)
        out = _author(fake, keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"mid": [0, 0, 45]}}])
        assert out["clip"] == "idle"

    def test_a_joint_that_cannot_answer_refuses_instead_of_keying_blind(
            self, fake):
        # The write-side guards degrade to "assume blocked"; the author
        # side cannot - a plug it fails to classify might be the very
        # connection-fed one whose key silently vanishes. Refusing costs
        # only the call: nothing has been mutated yet.
        fake.unqueryable = {"|root|mid"}
        with pytest.raises(HandlerError, match="cannot tell what drives"):
            _author(fake)
        assert fake.checkpoints == []

    def test_corrective_driven_weight_channel_refuses(self, fake):
        # #771, MEASURED (evals/correctives_probe/): setKeyframe on a
        # connection-fed plug silently no-ops - the refusal is what keeps
        # the clip from shipping without a channel it claims to key.
        fake.driven_plugs = {
            "body_shapes.blink": "mid_poseInterpShape.output[3]"}
        fake.node_types = {"mid_poseInterpShape": "poseInterpolator"}
        with pytest.raises(HandlerError, match="corrective"):
            _author(fake, keys=[
                {"time_s": 0.0, "blend_weights": {"blink": 0.0}},
                {"time_s": 1.0, "blend_weights": {"blink": 1.0}}])
        assert fake.checkpoints == []


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
        fake.string_attrs["|other_root"] = {
            "mcp_clip": json.dumps([{"name": "walk", "fps": 30,
                                     "start_frame": 0, "end_frame": 10}])}
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

    def test_author_clip_stops_an_idle_ipr_and_warns(self, fake, monkeypatch):
        monkeypatch.setattr(clip.session, "stop_idle_ipr",
                            lambda cmds: ["closed the Arnold RenderView"])
        out = _author(fake)
        assert any("closed the Arnold RenderView" in w and "#721" in w
                   for w in out["warnings"])


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

    def test_a_legacy_weight_channel_pins_at_zero_not_its_first_key(
            self, fake):
        """Final review Fix 3: `rest.setdefault(..., 0.0)` used to cover
        only `mine["weight_channels"]` (this clip's own aliases). A weight
        channel declared SOLELY by a pre-#718 clip - no per-channel rest
        record exists for it either, since legacy scenes predate that
        bookkeeping - reached `_rest_value`, which falls back to inferring
        rest from the curve's EARLIEST keyed value. For a legacy clip that
        opens non-zero (blink held at 1.0), that infers the wrong rest
        entirely: the phase-5 rule is that weights-all-zero IS the reset,
        not 'whatever a legacy clip happened to open with'. Constructed by
        hand-writing the legacy bare-object metadata shape (clip_meta's
        other read path) with curves author_clip itself never wrote."""
        fake.string_attrs["|root"] = {"mcp_clip": json.dumps({
            "name": "old", "fps": 30, "start_frame": 0, "end_frame": 30,
            "duration_s": 1.0, "loop": False, "interpolation": "linear",
            "joints": [], "weight_channels": ["blink"],
            "root_position_used": False})}
        fake.curves["body_shapes.blink"] = "legacy_crv"
        fake.keys["body_shapes.blink"] = {0.0: 1.0, 30.0: 1.0}
        out = _author(fake, name="new", keys=self._idle())   # never touches blink
        assert not any("no rest value was recorded" in w and "blink" in w
                       for w in out["warnings"]), out["warnings"]
        keys = fake.keys["body_shapes.blink"]
        start, end = out["start_frame"], out["end_frame"]
        assert keys[float(start)] == pytest.approx(0.0)
        assert keys[float(end)] == pytest.approx(0.0)

    def test_a_posed_rig_warns_that_rest_is_not_the_bind_pose(self, fake):
        """#732: FakeCmds.dagPose returns [] (no bind pose known), so
        _bind_rotations answers {} and every joint falls back to the
        pre-#732 capture-current behavior - summarized, not per-joint."""
        fake.attrs["|root|mid.rotateZ"] = 10.0
        out = _author(fake, name="idle", keys=self._idle())
        assert any("no readable bind pose" in w and "mid" in w
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

    def test_a_clip_introduced_channel_still_pins_its_own_boundaries(
            self, fake):
        """Final review Fix 1: the wave-1 code only padded channels ANY
        OTHER clip on the rig declares (`theirs`) - a channel this clip
        ALONE introduces (`mine \\ theirs`) was left unpinned, on the
        reasoning that "no other clip's keys are on that curve to bleed
        in". That reasoning is false: the BACK-FILL pass (below, in this
        same call) writes rest keys onto exactly that curve, at idle's own
        boundary frames (0 and 30) - two frames short of walk's start
        (32). Evaluating THROUGH those keys (not just checking where keys
        land) is the only way to see the bug: without walk's own boundary
        pins, walk's introduced channel `tip` ramps up from idle's
        back-filled rest keys instead of holding flat at its own
        authored value of 40 degrees."""
        _author(fake, name="idle", keys=self._idle())   # declares 'mid' only
        out = _author(fake, name="walk", keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 0.5, "rotations": {"tip": [0, 0, 40]}},
            {"time_s": 1.0, "rotations": {"mid": [0, 0, 20]}}])
        start, end = out["start_frame"], out["end_frame"]
        assert (start, end) == (32, 62)
        # walk's OWN range must read a flat 40 on tip - not a ramp bled in
        # from idle's back-filled rest keys at frames 0 and 30. Without the
        # fix this reads ~4.71 at frame 32 and ~16.47 at frame 37.
        for frame in (float(start), 37.0, float(end)):
            assert fake.evaluate("|root|mid|tip.rotateZ", frame) == \
                pytest.approx(40.0)
        assert "tip" in out["held_channels"]
        assert "tip" not in out["padded_channels"]

    def test_a_single_clip_rig_is_untouched_by_the_new_pinning(self, fake):
        """The gate on `kept` being non-empty: a rig's FIRST clip has no
        earlier clip to back-fill against, so padding its own channels
        against themselves must add nothing - exactly the two authored
        keys, no new pins, no extra tangent calls."""
        before = list(fake.tangents)
        out = _author(fake, name="idle", keys=self._idle())
        assert out["padded_channels"] == []
        assert out["held_channels"] == []
        assert out["back_filled"] == {"clips": [], "channels": []}
        assert sorted(fake.keys["|root|mid.rotateZ"]) == [0.0, 30.0]
        new_tangents = fake.tangents[len(before):]
        assert all(t[2] == (0, 30) for t in new_tangents)   # main pass only

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

    def test_round_down_reauthor_cut_does_not_leave_a_stray_fractional_key(
            self, fake):
        """Final review Fix 2: the same rounds-down trap, in the CUT
        rather than the pad/tangent passes. `a`'s first version keys `mid`
        at time_s 0.0 and 0.6 (24 fps): frames 0 and 14.4, so end_frame
        rounds DOWN to 14 (#636's int(round(...))). Re-authoring `a` with
        new keys at 0.0 and 1.0 used to cut only (start_frame, end_frame)
        == (0, 14) - the old key at 14.4, holding the FIRST version's
        value (50), sat outside that window and survived, so the
        re-authored curve read the OLD version's pose between frames 14
        and 15 instead of a clean ramp. The fix widens the cut by
        GAP_FRAMES, which costs nothing: no take's range ever includes
        that frame."""
        _author(fake, name="a", fps=24, keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 0.6, "rotations": {"mid": [0, 0, 50]}}])
        out = _author(fake, name="a", fps=24, keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"mid": [0, 0, 10]}}])
        assert out["replaced"] == "a"
        start, end = out["start_frame"], out["end_frame"]
        assert (start, end) == (0, 24)   # only clip on the rig: re-appends at 0
        # the stray key at 14.4 (the OLD version's) must be gone - nothing
        # left on the curve but the two newly-authored keys
        assert sorted(fake.keys["|root|mid.rotateZ"]) == [0.0, 24.0]
        for frame in (7.0, 14.0, 14.4, 15.0, 24.0):
            assert fake.evaluate("|root|mid.rotateZ", frame) == \
                pytest.approx(10.0 * frame / 24.0)

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


class TestReplaceCutOnDrivenChannels:
    """#796 review round 5 A: `cut_replaced_range` is the ONE site in this
    module that runs a DESTRUCTIVE time-range `cutKey` over every plug of
    the whole hierarchy, and it was the one site the clip/driven partition
    was never applied to. An SDK curve is indexed by DRIVER VALUE, so a
    time range is a numeric range on the driver: a re-author whose frames
    span 0-30 destroys every driver key between 0 and 30.

    Round 2's own change is what made this reachable: before #796
    author_clip REFUSED a rig carrying a driven key outright, so this cut
    never ran on one. It runs now.
    """

    def _idle(self):
        return [{"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
                {"time_s": 1.0, "rotations": {"mid": [0, 0, 45]}}]

    def _plant(self, fake):
        """The reviewer's reproduction: a set-driven key on the UNDECLARED
        channel |root|mid|tip.rotateX whose driver keys sit at driver
        VALUES 0, 15 and 90 - numbers that look exactly like frames."""
        _plant_sdk_curve(fake)                  # |root|mid|tip.rotateX
        fake.keys["|root|mid|tip.rotateX"] = {0.0: 0.0, 15.0: 3.0,
                                              90.0: 9.0}

    def test_a_re_author_never_cuts_a_driven_key_plug(self, fake):
        _author(fake, name="idle", keys=self._idle())   # frames 0-30
        self._plant(fake)
        _author(fake, name="idle", keys=self._idle())   # re-author: cuts
        assert "|root|mid|tip.rotateX" not in fake.cut_plugs
        assert sorted(fake.keys["|root|mid|tip.rotateX"]) == [0.0, 15.0,
                                                              90.0]

    def test_the_replace_cut_still_clears_every_clip_plug(self, fake):
        # The guard must narrow the cut by exactly one kind and nothing
        # else: a plug with a clip curve, and a plug with no curve at all,
        # are both still cut.
        _author(fake, name="idle", keys=self._idle())
        self._plant(fake)
        _author(fake, name="idle", keys=self._idle())
        assert "|root|mid.rotateZ" in fake.cut_plugs      # clip curve
        assert "|root|mid|tip.rotateY" in fake.cut_plugs  # no curve at all

    def test_a_driven_key_behind_a_blend_node_is_stepped_around_too(
            self, fake):
        # #796 review defect 7's shape, on the destructive side: the direct
        # curve query sees NOTHING when a pairBlend sits in the way, so the
        # partition alone would still aim a time-range cutKey at a curve
        # indexed by driver value. Skipping is right under both unmeasured
        # answers - if cutKey does not follow the connection, the cut it
        # skipped was a no-op anyway.
        _author(fake, name="idle", keys=self._idle())
        _plant_blend_curve(fake, "|root|mid|tip.rotateX",
                           blend="tip_pairBlend", curve="tip_sdk",
                           curve_type="animCurveUL")
        out = _author(fake, name="idle", keys=self._idle())
        assert "|root|mid|tip.rotateX" not in fake.cut_plugs
        assert any("tip_sdk behind tip_pairBlend" in w
                   for w in out["warnings"])

    def test_a_clip_curve_behind_a_blend_node_is_still_cut(self, fake):
        # The narrowing is one KIND wide, not "anything behind a blend
        # node": a time-based curve reached through a pairBlend is this
        # module's own currency and its replaced range must still go.
        _author(fake, name="idle", keys=self._idle())
        _plant_blend_curve(fake, "|root|mid|tip.rotateX",
                           blend="tip_pairBlend", curve="tip_crv")
        _author(fake, name="idle", keys=self._idle())
        assert "|root|mid|tip.rotateX" in fake.cut_plugs

    def test_a_free_sibling_axis_is_still_cut_and_never_named(self, fake):
        # #796 review round 6 C: the indirect check reached the PARENT
        # COMPOUND, and a compound reports any SIBLING's source - so ONE
        # driven key behind a pairBlend on tip.rotateX made the skip
        # contagious across tip.rotateY and tip.rotateZ, and `_skip_cut_note`
        # blamed them BY NAME. Two of those three warnings were about
        # channels with no source and no keys at all, which is exactly what
        # protocol.md promises does not happen ("the children are asked
        # first, so a driven key on one axis is never blamed on a free
        # sibling").
        _author(fake, name="idle", keys=self._idle())
        _plant_blend_curve(fake, "|root|mid|tip.rotateX",
                           blend="tip_pairBlend", curve="tip_sdk",
                           curve_type="animCurveUL")
        out = _author(fake, name="idle", keys=self._idle())
        assert "|root|mid|tip.rotateX" not in fake.cut_plugs     # the real one
        assert "|root|mid|tip.rotateY" in fake.cut_plugs
        assert "|root|mid|tip.rotateZ" in fake.cut_plugs
        assert not any("|root|mid|tip.rotateY" in w
                       or "|root|mid|tip.rotateZ" in w
                       for w in out["warnings"])

    def test_a_compound_borne_driven_key_still_covers_all_three(self, fake):
        # The narrowing is "ask the children first", not "never ask the
        # compound": an anim layer lands on `.rotate` itself, where all
        # three children really are behind it and a cut on any of them
        # would aim a time range at a driver-indexed curve.
        _author(fake, name="idle", keys=self._idle())
        _plant_blend_curve(fake, "|root|mid|tip.rotate",
                           blend="tip_layer", curve="tip_sdk",
                           blend_type="animBlendNodeAdditiveRotation",
                           curve_type="animCurveUL")
        out = _author(fake, name="idle", keys=self._idle())
        for axis in "XYZ":
            assert "|root|mid|tip.rotate%s" % axis not in fake.cut_plugs
        assert len([w for w in out["warnings"]
                    if "did NOT clear" in w]) == 3

    def test_the_skipped_cut_is_named(self, fake):
        # Silently not cutting is the same sin as silently cutting: the
        # caller is told which plug the replace-cut stepped around.
        _author(fake, name="idle", keys=self._idle())
        self._plant(fake)
        out = _author(fake, name="idle", keys=self._idle())
        assert any("|root|mid|tip.rotateX" in w and "tip_rotX_driven" in w
                   for w in out["warnings"])


class TestPadPinsOnDrivenChannels:
    """#796 review round 4 A: the boundary-pin pass calls setKeyframe on
    channels OTHER clips declared, which the per-channel refusal above
    never asks about (it asks only what THIS call declares). The weight pad
    loop has skipped a driven channel since #771; the joint and
    root-translate loops claimed pins that measurably never landed."""

    def _idle(self):
        return [{"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
                {"time_s": 1.0, "rotations": {"mid": [0, 0, 45]}}]

    def _walk(self):
        return [{"time_s": 0.0, "rotations": {"tip": [0, 0, 0]}},
                {"time_s": 1.0, "rotations": {"tip": [0, 0, 20]}}]

    def test_a_pad_joint_channel_driven_out_of_band_is_skipped(self, fake):
        # The reviewer's reproduction: 'wave' declares tip, then out of
        # band tip.rotateX's clip curve is deleted and a set-driven key is
        # wired onto it, then 'idle' declares mid only. The pad pass pinned
        # tip and REPORTED it pinned; the key returned 0 and created
        # nothing.
        _author(fake, name="wave", keys=self._walk())
        fake.keys.pop("|root|mid|tip.rotateX", None)
        _plant_sdk_curve(fake)                      # |root|mid|tip.rotateX
        out = _author(fake, name="idle", keys=self._idle())
        assert any("|root|mid|tip.rotateX" in w and "SKIPPED" in w
                   for w in out["warnings"])
        assert "|root|mid|tip.rotateX" not in fake.keys     # never landed
        # the FREE channels on the same joint are still pinned
        assert fake.keys["|root|mid|tip.rotateY"][
            float(out["start_frame"])] == 0.0

    def test_a_pad_root_translate_driven_out_of_band_is_skipped(self, fake):
        # The same hole on the root_position loop, which has no guard of
        # any kind.
        _author(fake, name="walk")            # default keys move the root
        fake.keys.pop("|root.translateY", None)
        _plant_sdk_curve(fake, plug="|root.translateY",
                         curve="root_ty_driven")
        out = _author(fake, name="idle", keys=self._idle())
        assert any("|root.translateY" in w and "SKIPPED" in w
                   for w in out["warnings"])
        assert "|root.translateY" not in fake.keys
        assert fake.keys["|root.translateX"][float(out["start_frame"])] == 0.0

    def test_a_pad_channel_behind_a_blend_node_is_still_pinned(self, fake):
        # Skipping is limited to the kinds MEASURED to swallow a key. A
        # pairBlend is not one of them, and skipping its pin would lose a
        # boundary that a rig which works today gets - the same
        # over-refusal as defect B, one loop over.
        _author(fake, name="wave", keys=self._walk())
        _plant_blend_curve(fake, "|root|mid|tip.rotateX",
                           blend="tip_pairBlend", curve="tip_rotX_crv")
        out = _author(fake, name="idle", keys=self._idle())
        assert not any("SKIPPED" in w for w in out["warnings"])
        assert fake.keys["|root|mid|tip.rotateX"][
            float(out["start_frame"])] == 0.0

    def test_a_skipped_pad_channel_is_never_counted_as_pinned(self, fake):
        # A joint whose WHOLE rotate triple is driven contributes nothing
        # to padded_channels - the weight loop's precedent exactly.
        _author(fake, name="wave", keys=self._walk())
        for axis in "XYZ":
            plug = "|root|mid|tip.rotate%s" % axis
            fake.keys.pop(plug, None)
            _plant_sdk_curve(fake, plug=plug, curve="tip_rot%s_driven" % axis)
        out = _author(fake, name="idle", keys=self._idle())
        assert "tip" not in out["padded_channels"]
        assert "tip" not in out["held_channels"]
        assert len([w for w in out["warnings"] if "SKIPPED" in w]) == 3


class TestPadNotesMatchTheDeclaredPath:
    """#796 review round 5 B: one scene, one diagnosis - in the PAD loops.

    Round 4 A narrowed the joint and root pad loops to the kinds in
    UNKEYABLE_KINDS and discarded every entry outside them. A pad channel an INTERMEDIARY feeds was then pinned,
    counted, and reported "pinned ... at rest" with no note at all - while
    the IDENTICAL connection on a DECLARED channel produced
    `_driven_channel_note`. That asymmetry is what round 4 B was filed to
    end, one loop over.
    """

    def _idle(self):
        return [{"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
                {"time_s": 1.0, "rotations": {"mid": [0, 0, 45]}}]

    def _wave(self):
        return [{"time_s": 0.0, "rotations": {"tip": [0, 0, 0]}},
                {"time_s": 1.0, "rotations": {"tip": [0, 0, 20]}}]

    def test_a_pad_joint_channel_behind_a_blend_is_named(self, fake):
        _author(fake, name="wave", keys=self._wave())
        _plant_blend_curve(fake, "|root|mid|tip.rotateX",
                           blend="tip_pairBlend", curve="tip_rotX_crv")
        out = _author(fake, name="idle", keys=self._idle())
        assert any("|root|mid|tip.rotateX" in w and "tip_pairBlend" in w
                   and "tip_rotX_crv" in w for w in out["warnings"])
        # still PINNED, and still counted - round 4 B's rule holds here too
        assert "tip" in out["padded_channels"]

    def test_the_pad_note_is_the_one_the_declared_path_gives(self, fake,
                                                             monkeypatch):
        # Two scenes, one connection, one sentence. The declared path's
        # note is built by `_driven_channel_note`; the pad path must reach
        # the SAME helper rather than growing a second wording (or, as it
        # did, none at all).
        declared = _install(FakeCmds(), monkeypatch)
        _plant_blend_curve(declared, "|root|mid|tip.rotateX",
                           blend="tip_pairBlend", curve="tip_rotX_crv")
        spoken = [w for w in _author(declared, name="idle",
                                     keys=self._wave())["warnings"]
                  if "|root|mid|tip.rotateX" in w]
        assert len(spoken) == 1

        _author(fake, name="wave", keys=self._wave())
        _plant_blend_curve(fake, "|root|mid|tip.rotateX",
                           blend="tip_pairBlend", curve="tip_rotX_crv")
        padded = _author(fake, name="idle", keys=self._idle())["warnings"]
        assert spoken[0] in padded

    def test_a_pad_root_translation_behind_a_blend_is_named(self, fake):
        # The root loop has the same shape and the same hole.
        _author(fake, name="walk")            # default keys move the root
        _plant_blend_curve(fake, "|root.translateY", blend="root_pairBlend",
                           curve="root_tY_crv")
        out = _author(fake, name="idle", keys=self._idle())
        assert any("|root.translateY" in w and "root_pairBlend" in w
                   for w in out["warnings"])
        assert fake.keys["|root.translateY"][float(out["start_frame"])] \
            == pytest.approx(1.0)

    def test_a_clip_driven_pad_channel_stays_silent(self, fake):
        # The normal case must not acquire a note: every pad channel is by
        # definition driven by ANOTHER CLIP's curve, and saying so about
        # each one would bury the notes that matter.
        _author(fake, name="wave", keys=self._wave())
        out = _author(fake, name="idle", keys=self._idle())
        assert not any("is driven by" in w for w in out["warnings"])


class TestObservedWrites:
    """#796 review round 5 C: `setKeyframe` returns the NUMBER of keys it
    set, and #771 measured 0 as the tell that the write vanished. Every
    call site discarded it, so the handler GUESSED which writes landed and
    could ship `mcp_clip` declaring a channel it never keyed.

    Both unmeasured outcomes are pinned here: with `blend_swallows_keys`
    False (today's behaviour, which a fix must not regress) the report is
    unchanged; with it True the report follows what actually happened.
    """

    def _mid(self):
        return [{"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
                {"time_s": 1.0, "rotations": {"mid": [0, 0, 45]}}]

    def _swallow_mid(self, fake):
        fake.blend_swallows_keys = True
        return _plant_blend_curve(fake, "|root|mid.rotate",
                                  blend="mid_pairBlend", curve="mid_crv",
                                  blend_type="pairBlend")

    def test_a_swallowed_joint_is_not_counted_or_declared(self, fake):
        self._swallow_mid(fake)
        out = _author(fake, keys=self._mid())
        assert out["keyed_joints"] == 0
        assert clip.clip_meta(fake, "|root")[0]["joints"] == []
        assert any("|root|mid.rotateZ" in w and "did not land" in w.lower()
                   for w in out["warnings"])

    def test_the_same_scene_that_lands_reports_exactly_as_before(self, fake):
        # Outcome (a): the key DOES land through the pairBlend. Nothing
        # about the report may change - this is the rig that works today.
        _plant_blend_curve(fake, "|root|mid.rotate", blend="mid_pairBlend",
                           curve="mid_crv", blend_type="pairBlend")
        out = _author(fake, keys=self._mid())
        assert out["keyed_joints"] == 1
        assert clip.clip_meta(fake, "|root")[0]["joints"] == ["mid"]
        assert not any("did not land" in w.lower() for w in out["warnings"])

    def test_a_partly_swallowed_joint_is_still_declared(self, fake):
        # Only rotateZ is swallowed; the other two axes carry real keys, so
        # the clip really does own this joint. The truth is per CHANNEL.
        fake.blend_swallows_keys = True
        _plant_blend_curve(fake, "|root|mid.rotateZ", blend="mid_pairBlend",
                           curve="mid_rotZ_crv")
        out = _author(fake, keys=self._mid())
        assert out["keyed_joints"] == 1
        assert clip.clip_meta(fake, "|root")[0]["joints"] == ["mid"]
        assert any("|root|mid.rotateZ" in w and "did not land" in w.lower()
                   for w in out["warnings"])

    def test_a_swallowed_root_translation_is_not_declared(self, fake):
        # #796 review round 6 A: on THIS scene the verdict is now reached
        # one write earlier - the pose write in front of the keys refuses
        # on a connection-fed root, so the three translate channels are
        # lost there rather than in setKeyframe. Same fact, same sentence,
        # same absence from the record; see TestRefusedRootPoseWrite.
        fake.blend_swallows_keys = True
        _plant_blend_curve(fake, "|root.translate", blend="root_pairBlend",
                           curve="root_crv")
        out = _author(fake)                   # default keys move the root
        assert out["root_position_keyed"] is False
        assert clip.clip_meta(fake, "|root")[0]["root_position_used"] is False
        assert any("|root.translateY" in w and "did not land" in w.lower()
                   for w in out["warnings"])

    def test_a_clip_that_keyed_nothing_says_so_loudly(self, fake):
        self._swallow_mid(fake)
        out = _author(fake, keys=self._mid())
        assert any("keyed NOTHING" in w for w in out["warnings"])

    def test_a_lost_boundary_pin_is_never_counted_as_pinned(self, fake):
        # `_pin` discarded the same return. A pad channel behind an
        # intermediary is pinned (round 4 B) - but if that pin does not
        # land, `padded_channels` must not claim it did.
        _author(fake, name="wave", keys=[
            {"time_s": 0.0, "rotations": {"tip": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"tip": [0, 0, 20]}}])
        for axis in "XYZ":
            plug = "|root|mid|tip.rotate%s" % axis
            fake.keys.pop(plug, None)
            fake.curves.pop(plug, None)
        fake.blend_swallows_keys = True
        _plant_blend_curve(fake, "|root|mid|tip.rotate",
                           blend="tip_pairBlend", curve="tip_crv",
                           blend_type="pairBlend")
        out = _author(fake, name="idle", keys=self._mid())
        assert "tip" not in out["padded_channels"]
        assert "tip" not in out["held_channels"]
        assert any("|root|mid|tip.rotateX" in w and "did not land" in w.lower()
                   for w in out["warnings"])

    def test_a_back_fill_is_never_claimed_for_a_channel_that_never_keyed(
            self, fake):
        # The back-fill runs over the channels THIS clip introduces. A
        # channel whose every write vanished is not one of them.
        _author(fake, name="wave", keys=self._mid())
        fake.blend_swallows_keys = True
        _plant_blend_curve(fake, "|root|mid|tip.rotate",
                           blend="tip_pairBlend", curve="tip_crv",
                           blend_type="pairBlend")
        out = _author(fake, name="idle", keys=[
            {"time_s": 0.0, "rotations": {"tip": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"tip": [0, 0, 20]}}])
        assert out["back_filled"]["channels"] == []
        assert clip.clip_meta(fake, "|root")[1]["joints"] == []


class TestRefusedRootPoseWrite:
    """#796 review round 6 A: the honest-report path for ROOT TRANSLATION
    was unreachable on a real rig.

    `guard_declared_channels` decides only to WARN about an "other"
    connection on the declared translate channels (round 4 B: a pairBlend
    is what Maya inserts the moment a plug is both keyed AND constrained,
    and such a rig authors clips today). The keying loop then called
    `cmds.xform(root, worldSpace=True, translation=...)` - a STATIC write
    to those very plugs, which a connection-fed plug refuses - so the call
    raised a traceback after `auto_checkpoint` had run and key 0's
    rotations were already in the scene. The round-5 test that pinned the
    report passed only because `FakeCmds.xform` did not model the refusal
    `FakeCmds.setAttr` already modelled.
    """

    def _keys(self):
        return [{"time_s": 0.0, "rotations": {"mid": [0, 0, 0]},
                 "root_position": [0.0, 1.0, 0.0]},
                {"time_s": 1.0, "rotations": {"mid": [0, 0, 45]},
                 "root_position": [0.0, 1.4, 0.0]}]

    def _constrained_root(self, fake):
        # Keyed AND constrained: Maya's pairBlend, per child, on the root's
        # translate compound. NOT `blend_swallows_keys` - the key itself is
        # unmeasured through a blend node and irrelevant here, because the
        # POSE write in front of it is what refuses.
        return _plant_blend_curve(fake, "|root.translate",
                                  blend="root_pairBlend", curve="root_crv")

    def test_a_refused_pose_write_is_reported_not_raised(self, fake):
        self._constrained_root(fake)
        out = _author(fake, keys=self._keys())
        assert out["root_position_keyed"] is False
        assert clip.clip_meta(fake, "|root")[0]["root_position_used"] is False
        for axis in "XYZ":
            assert any("|root.translate%s" % axis in w
                       and "did NOT land" in w for w in out["warnings"])

    def test_the_rotations_of_the_same_call_still_land(self, fake):
        # The clip is not lost, only the channel that could not be written.
        self._constrained_root(fake)
        out = _author(fake, keys=self._keys())
        assert out["keyed_joints"] == 1
        assert clip.clip_meta(fake, "|root")[0]["joints"] == ["mid"]
        assert not any("keyed NOTHING" in w for w in out["warnings"])

    def test_nothing_is_keyed_behind_the_caller_on_the_refused_plugs(
            self, fake):
        # A value keyed from a pose write that never happened would be this
        # clip's own guess at where the root is - the guessing class round
        # 5 C removed, one write earlier.
        self._constrained_root(fake)
        _author(fake, keys=self._keys())
        for axis in "XYZ":
            assert "|root.translate%s" % axis not in fake.keys

    def test_the_other_channels_of_the_same_KEY_still_land(self, fake):
        # The refused pose write costs the root's translate channels and
        # NOTHING else: the blend weight named on the very same key is
        # written after it and has no connection to those plugs.
        self._constrained_root(fake)
        out = _author(fake, keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]},
             "blend_weights": {"blink": 0.0},
             "root_position": [0.0, 1.0, 0.0]},
            {"time_s": 1.0, "rotations": {"mid": [0, 0, 45]},
             "blend_weights": {"blink": 1.0},
             "root_position": [0.0, 1.4, 0.0]}])
        assert out["keyed_weight_channels"] == ["blink"]
        assert fake.keys["body_shapes.blink"][
            float(out["end_frame"])] == 1.0

    def test_a_free_root_still_moves_and_declares_itself(self, fake):
        # The same call on a rig with nothing on the root: unchanged.
        out = _author(fake, keys=self._keys())
        assert out["root_position_keyed"] is True
        assert not any("did NOT land" in w for w in out["warnings"])
        assert fake.keys["|root.translateY"]


class TestBindPoseRest:
    def test_rest_captures_the_bind_rotation_when_known(self, fake, monkeypatch):
        # an "imported rig" whose bind pose carries rotation: current pose
        # EQUALS bind, so no warning, and rest records the bind value.
        monkeypatch.setattr(clip, "_bind_rotations",
                            lambda cmds, root, joints:
                            {"mid": [10.0, 0.0, 0.0]})
        fake.attrs["|root|mid.rotateX"] = 10.0
        out = _author(fake, keys=[
            {"time_s": 0.0, "rotations": {"mid": [10, 0, 0]}},
            {"time_s": 1.0, "rotations": {"mid": [40, 0, 0]}}])
        rest = json.loads(fake.string_attrs["|root"]["mcp_clip_rest"])
        assert rest["mid.rotateX"] == 10.0
        assert not any("posed" in w for w in out["warnings"])

    def test_posed_away_from_a_known_bind_warns_and_pins_at_bind(
            self, fake, monkeypatch):
        monkeypatch.setattr(clip, "_bind_rotations",
                            lambda cmds, root, joints:
                            {"mid": [0.0, 0.0, 0.0]})
        fake.attrs["|root|mid.rotateX"] = 25.0   # posed away from bind
        out = _author(fake, keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"mid": [40, 0, 0]}}])
        rest = json.loads(fake.string_attrs["|root"]["mcp_clip_rest"])
        assert rest["mid.rotateX"] == 0.0        # BIND, not the posed 25
        assert any("posed away from the bind pose" in w
                   for w in out["warnings"])

    def test_unknown_bind_falls_back_to_current_capture(self, fake):
        # FakeCmds.dagPose returns [] -> _bind_rotations returns {} -> the
        # pre-#732 behavior: capture current, warn (summarized) on non-zero.
        fake.attrs["|root|mid.rotateX"] = 25.0
        out = _author(fake, keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"mid": [40, 0, 0]}}])
        rest = json.loads(fake.string_attrs["|root"]["mcp_clip_rest"])
        assert rest["mid.rotateX"] == 25.0
        assert any("no readable bind pose" in w for w in out["warnings"])


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

    def test_a_named_delete_removes_one_clip_and_leaves_the_others(self, fake):
        _author(fake, name="idle")
        # walk uses _author's default keys too, which key the same channels
        # as idle (mid rotations + root.translateY). Deleting idle only cuts
        # idle's own frame range, so walk's keys on those same curves survive
        # - see the deleted_curves == 0 assertion below.
        _author(fake, name="walk")
        out = clip.delete_clip({"root": "root", "name": "idle"})
        assert out["clip"] == "idle" and out["clips"] == ["walk"]
        # Both idle and walk use default keys, which key the same channels
        # (mid rotations + root.translateY). When idle's 0-30 range is cut,
        # walk's 32-62 keys on those same curves survive. Thus no curves are
        # fully emptied: deleted_curves == 0. This is correct behavior - it
        # tests that cutting one clip's range leaves surviving keys intact.
        assert out["deleted_curves"] == 0
        times = sorted(fake.keys["|root|mid.rotateZ"])
        assert 0.0 not in times and 30.0 not in times   # idle's range
        assert 32.0 in times and 62.0 in times          # walk's, untouched
        meta = json.loads(fake.string_attrs["|root"]["mcp_clip"])
        assert [r["name"] for r in meta] == ["walk"]
        # gaps are NOT re-packed: walk keeps the range it was authored at
        assert meta[0]["start_frame"] == 32

    def test_an_unknown_name_refuses_and_lists_what_is_there(self, fake):
        _author(fake, name="idle")
        with pytest.raises(HandlerError, match="no clip named 'nope'"):
            clip.delete_clip({"root": "root", "name": "nope"})
        assert fake.checkpoints == ["author_clip"]

    def test_deleting_the_last_named_clip_completes_the_teardown(self, fake):
        _author(fake, name="idle")
        out = clip.delete_clip({"root": "root", "name": "idle"})
        assert out["clips"] == []
        assert "mcp_clip" not in fake.string_attrs.get("|root", {})
        assert any("last clip" in w for w in out["warnings"])

    def test_deleting_without_a_name_still_removes_everything(self, fake):
        _author(fake, name="idle")
        _author(fake, name="walk")
        out = clip.delete_clip({"root": "root"})
        assert out["clips"] == []
        assert not any(p.startswith("|root|mid.rotate") for p in fake.curves)
        assert "mcp_clip" not in fake.string_attrs.get("|root", {})
        assert "mcp_clip_rest" not in fake.string_attrs.get("|root", {})

    def test_deleting_a_middle_clip_with_rest_pins_preserves_neighbors(
            self, fake):
        """#718 review Fix 5: a middle clip B that carries ONLY rest-pin
        keys on a channel, sandwiched between two clips A and C that key that
        channel for real motion. Deleting B must leave A's and C's evaluated
        motion unchanged - the rest pins are local to B's range and do not
        contaminate the neighbors.

        Regression check: if cutKey were incorrectly scoped (e.g., to the whole
        timeline instead of just B's range), it would remove A's and C's motion
        keys too, and the evaluated poses would differ. This test captures
        evaluated values before and compares after."""
        # Clip A: keys 'mid' with real motion
        rec_a = _author(fake, name="clipA", fps=30, keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"mid": [0, 0, 45]}}])
        # Clip B: keys only 'tip', so 'mid' gets padding (rest pins) at B's
        # boundaries - a rest-pose (0.0) key at B's start_frame and
        # end_frame. Those pins live entirely inside B's own range, so they
        # carry only rest, not A's or C's motion.
        rec_b = _author(fake, name="clipB", fps=30, keys=[
            {"time_s": 0.0, "rotations": {"tip": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"tip": [0, 0, 20]}}])
        # Clip C: keys 'mid' with real motion again (in a different range)
        rec_c = _author(fake, name="clipC", fps=30, keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"mid": [0, 0, 30]}}])

        # Capture A's and C's evaluated poses BEFORE the delete, at their own
        # key frames and a mid-frame. Read the actual ranges back from
        # author_clip's return value rather than hardcoding them - each clip
        # starts GAP_FRAMES+1 past the previous clip's end_frame (clipmath's
        # next_start_frame), so a hand-computed literal drifts the moment
        # that gap changes.
        a_start, a_end = float(rec_a["start_frame"]), float(rec_a["end_frame"])
        c_start, c_end = float(rec_c["start_frame"]), float(rec_c["end_frame"])

        a_poses_before = [
            fake.evaluate("|root|mid.rotateZ", a_start),
            fake.evaluate("|root|mid.rotateZ", (a_start + a_end) / 2.0),
            fake.evaluate("|root|mid.rotateZ", a_end),
        ]
        c_poses_before = [
            fake.evaluate("|root|mid.rotateZ", c_start),
            fake.evaluate("|root|mid.rotateZ", (c_start + c_end) / 2.0),
            fake.evaluate("|root|mid.rotateZ", c_end),
        ]

        # Delete B
        out = clip.delete_clip({"root": "root", "name": "clipB"})
        assert out["clip"] == "clipB"
        assert out["clips"] == ["clipA", "clipC"]

        # Check that A's motion is unchanged
        a_poses_after = [
            fake.evaluate("|root|mid.rotateZ", a_start),
            fake.evaluate("|root|mid.rotateZ", (a_start + a_end) / 2.0),
            fake.evaluate("|root|mid.rotateZ", a_end),
        ]
        assert a_poses_after == pytest.approx(a_poses_before), \
            "Deleting middle clip B should not change A's evaluated motion"

        # Check that C's motion is unchanged
        c_poses_after = [
            fake.evaluate("|root|mid.rotateZ", c_start),
            fake.evaluate("|root|mid.rotateZ", (c_start + c_end) / 2.0),
            fake.evaluate("|root|mid.rotateZ", c_end),
        ]
        assert c_poses_after == pytest.approx(c_poses_before), \
            "Deleting middle clip B should not change C's evaluated motion"

        # Verify B's range carries no keys on mid's channel after delete
        mid_rotZ_keys = fake.keys.get("|root|mid.rotateZ", {})
        b_range = range(rec_b["start_frame"], rec_b["end_frame"] + 1)
        for frame in b_range:
            assert float(frame) not in mid_rotZ_keys, \
                (f"B's padding key at frame {frame} should be deleted")

    def test_a_named_delete_reaps_channels_no_survivor_declares(self, fake):
        # #730: idle keys mid, wave introduces tip, step keys mid again.
        # Deleting wave must remove tip's whole curves - they carry only
        # rest pins inside idle's and step's ranges - without touching a
        # single key of idle's or step's own mid channel.
        _author(fake, name="idle", keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"mid": [0, 0, 30]}}])
        wave_rec = _author(fake, name="wave", keys=[
            {"time_s": 0.0, "rotations": {"tip": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"tip": [0, 0, 45]}}])
        _author(fake, name="step", keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"mid": [0, 0, -30]}}])
        # wave never declares mid, so the pre-existing #718 padding rule
        # also pins mid at rest at WAVE's OWN boundaries (32, 62) - a pin
        # that lives entirely inside wave's own doomed range and is
        # correctly cut away by the existing own-range cutKey step below,
        # unrelated to #730's reap. Exclude it so this checks only the
        # survivors' own authored keys are untouched.
        mid_keys_before = {
            t: v for t, v in fake.keys.get("|root|mid.rotateZ", {}).items()
            if not (wave_rec["start_frame"] <= t <= wave_rec["end_frame"])}

        out = clip.delete_clip({"root": "root", "name": "wave"})

        assert out["clips"] == ["idle", "step"]
        assert out["reaped_channels"] == ["tip"]
        # tip's curves are gone ENTIRELY, not just cut in wave's range
        assert not any(p.startswith("|root|mid|tip.") for p in fake.keys)
        assert out["deleted_curves"] >= 3   # tip's three rotate curves
        # the survivors' own keys are untouched
        assert dict(fake.keys.get("|root|mid.rotateZ", {})) == mid_keys_before
        assert any("no surviving clip declares" in w for w in out["warnings"])

    def test_a_plain_clip_still_tears_down_whole(self, fake):
        # Regression pin for #796: with no driven keys anywhere, the full
        # teardown deletes every clip curve and says nothing about rig setup.
        _author(fake)
        expected = set(fake.curves.values())
        out = clip.delete_clip({"root": "root"})
        assert set(fake.deleted) == expected
        assert out["deleted_curves"] == len(expected)
        assert not any("set-driven" in w for w in out["warnings"])

    def test_the_full_teardown_leaves_set_driven_keys_standing(self, fake):
        # #796 defect 1: _anim_curves' type="animCurve" filter matches the
        # U-typed SDK curves too, so the old teardown deleted the caller's
        # rig setup as a side effect of "remove my clip".
        _author(fake)
        sdk = _plant_sdk_curve(fake)
        clip_curves = {c for c in fake.curves.values() if c != sdk}
        out = clip.delete_clip({"root": "root"})
        assert sdk not in fake.deleted
        assert set(fake.deleted) == clip_curves
        assert out["deleted_curves"] == len(clip_curves)
        assert fake.curves.get("|root|mid|tip.rotateX") == sdk
        assert any(sdk in w and "set-driven" in w for w in out["warnings"])

    def test_the_teardown_leaves_a_driven_rotate_alone_and_says_so(
            self, fake):
        # #796 review defect 2: with a curve left standing, the no-bind-pose
        # fallback's `setAttr(joint + '.rotate', 0, 0, 0)` writes a plug a
        # connection feeds, and Maya raises rather than writing it. The
        # blocked channels must be skipped AND named; the free ones on the
        # same joint still go back to rest.
        _author(fake)
        _plant_sdk_curve(fake)          # |root|mid|tip.rotateX
        out = clip.delete_clip({"root": "root"})
        assert any("left 1 joint rotation(s)" in w and "tip (rotateX)" in w
                   for w in out["warnings"])
        # and the sibling warning stops claiming it zeroed all of them
        assert any("the free rotations were zeroed" in w
                   for w in out["warnings"])
        assert fake.attrs["|root|mid|tip.rotateY"] == 0.0
        assert fake.attrs["|root|mid|tip.rotateZ"] == 0.0
        # a joint nothing feeds is still zeroed as one compound write
        assert fake.attrs["|root|mid.rotate"] == (0.0, 0.0, 0.0)

    def test_a_compound_rotate_connection_blocks_all_three_children(
            self, fake):
        # An anim layer connects animBlendNodeAdditiveRotation.output to the
        # joint's .rotate COMPOUND. Writing any child of a connected
        # compound raises, so all three are off limits, not just one.
        _author(fake)
        fake.driven_plugs = {"|root|mid|tip.rotate": "layer_blend.output"}
        fake.node_types = {"layer_blend": "animBlendNodeAdditiveRotation"}
        out = clip.delete_clip({"root": "root"})
        assert any("tip (rotateX, rotateY, rotateZ)" in w
                   for w in out["warnings"])

    def test_a_joint_that_cannot_answer_is_treated_as_fully_blocked(
            self, fake):
        # A node a broken reference leaves unqueryable must cost a skipped
        # write, never a traceback halfway through a mutation. (delete_clip
        # as a whole still needs a queryable rig - its own up-front
        # _anim_curves sweep asks first; this pins the write-side guard.)
        fake.unqueryable = {"|root|mid|tip"}
        assert clip._blocked_rotate_attrs(fake, "|root|mid|tip") == [
            "rotateX", "rotateY", "rotateZ"]

    def test_a_partial_delete_never_cuts_a_driven_key_plug(self, fake):
        # An SDK curve is indexed by DRIVER VALUE, not time: a time-range
        # cutKey against one is meaningless at best and destroys driver keys
        # that happen to fall in the numeric range at worst.
        _author(fake, name="idle")
        _author(fake, name="walk")
        _plant_sdk_curve(fake)
        out = clip.delete_clip({"root": "root", "name": "idle"})
        assert "|root|mid|tip.rotateX" not in fake.cut_plugs
        assert "|root|mid.rotateZ" in fake.cut_plugs   # the clip plugs still cut
        assert out["clips"] == ["walk"]

    def test_the_orphan_reap_leaves_a_driven_key_curve_standing(self, fake):
        # #730's reap re-queries type="animCurve" on the orphaned channels
        # and deletes the WHOLE curve - the same flaw at a third site.
        _author(fake, name="idle", keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"mid": [0, 0, 30]}}])
        _author(fake, name="wave", keys=[
            {"time_s": 0.0, "rotations": {"tip": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"tip": [0, 0, 45]}}])
        _author(fake, name="step", keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"mid": [0, 0, -30]}}])
        # tip is the orphaned channel; one of its plugs is now owned by a
        # driven key rather than by the clip.
        sdk = _plant_sdk_curve(fake, plug="|root|mid|tip.rotateY",
                               curve="tip_rotY_driven", node_type="animCurveUL")
        out = clip.delete_clip({"root": "root", "name": "wave"})
        assert sdk not in fake.deleted
        assert out["reaped_channels"] == ["tip"]
        assert any("no surviving clip declares" in w for w in out["warnings"])
        assert any(sdk in w and "set-driven" in w for w in out["warnings"])

    def test_a_joint_and_a_weight_alias_of_the_same_name_are_both_reaped(
            self, fake):
        # #796 review defect 5: the reap's plug map went from a flat list to
        # a dict keyed by CHANNEL NAME, and joint short names, blendShape
        # weight aliases and the literal 'root_position' all share that key
        # space. A 'tip' joint and a 'tip' shape overwrote each other, so
        # only one was reaped - and reaped_channels named it once, so
        # nothing in the result revealed the loss.
        fake.blend_aliases = ["blink", "tip"]
        _author(fake, name="idle", keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"mid": [0, 0, 30]}}])
        _author(fake, name="wave", keys=[
            {"time_s": 0.0, "rotations": {"tip": [0, 0, 0]},
             "blend_weights": {"tip": 0.0}},
            {"time_s": 1.0, "rotations": {"tip": [0, 0, 45]},
             "blend_weights": {"tip": 1.0}}])
        _author(fake, name="step", keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"mid": [0, 0, -30]}}])
        out = clip.delete_clip({"root": "root", "name": "wave"})
        assert out["reaped_channels"] == ["tip (joint)", "tip (blend weight)"]
        assert "body_shapes_tip_crv" in fake.deleted        # the shape
        assert "_root_mid_tip_rotateZ_crv" in fake.deleted  # the joint

    def test_an_orphan_channel_that_is_only_a_driven_key_is_not_reaped(
            self, fake):
        # Nothing was removed for that channel, so nothing may claim it was:
        # reaped_channels reports what the reap FOUND, not what the doomed
        # record declared (#796).
        _author(fake, name="idle", keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"mid": [0, 0, 30]}}])
        _author(fake, name="wave", keys=[
            {"time_s": 0.0, "rotations": {"tip": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"tip": [0, 0, 45]}}])
        _author(fake, name="step", keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"mid": [0, 0, -30]}}])
        sdk = [_plant_sdk_curve(fake, plug="|root|mid|tip.rotate" + axis,
                                curve="tip_rot%s_driven" % axis)
               for axis in "XYZ"]
        out = clip.delete_clip({"root": "root", "name": "wave"})
        assert out["reaped_channels"] == []
        assert not any(c in fake.deleted for c in sdk)
        assert not any("no surviving clip declares" in w
                       for w in out["warnings"])

    def test_a_rig_with_only_driven_keys_and_no_clip_refuses(self, fake):
        # Nothing here is clip motion, so there is nothing for this tool to
        # remove - and it must not "fix" that by eating the rig setup.
        sdk = _plant_sdk_curve(fake)
        with pytest.raises(HandlerError, match="no clip") as exc:
            clip.delete_clip({"root": "root"})
        assert sdk in (exc.value.hint or "")
        assert sdk not in fake.deleted

    def test_the_unknown_name_hint_does_not_promise_a_static_skeleton(
            self, fake):
        # The 'omit `name`' hint claims a full delete returns the skeleton
        # to static posing. With driven keys standing that is false.
        _author(fake, name="idle")
        sdk = _plant_sdk_curve(fake)
        with pytest.raises(HandlerError, match="no clip named") as exc:
            clip.delete_clip({"root": "root", "name": "nope"})
        hint = exc.value.hint
        assert sdk in hint
        assert "kept" in hint
        assert "and return the skeleton to static posing" not in hint

    def test_a_named_delete_of_a_declared_shared_channel_reaps_nothing(
            self, fake):
        # mid is declared by the survivor too - nothing may be reaped.
        _author(fake, name="idle", keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"mid": [0, 0, 30]}}])
        _author(fake, name="wave", keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"mid": [0, 0, 45]}}])
        out = clip.delete_clip({"root": "root", "name": "wave"})
        assert out["reaped_channels"] == []
        assert "|root|mid.rotateZ" in fake.keys


class TestBoundTeardown:
    """delete_clip's BIND-POSE branch (#796 review round 3 M2).

    Nothing exercised it before this round: FakeCmds.dagPose answered []
    unconditionally, so every teardown test above took the unbound
    zero-rotation fallback - while in a real scene any rig with a
    skinCluster has a bind pose and takes THIS branch. Which is where
    `dagPose -restore` meets the rotate and translate plugs a surviving
    set-driven key feeds, and nobody has measured what it does about them:
    both outcomes are modelled here.
    """

    def test_a_bound_rig_gets_exactly_the_restore_it_always_got(self, fake):
        fake.bind_poses = ["bindPose1"]
        _author(fake)
        out = clip.delete_clip({"root": "root"})
        assert fake.dag_pose_restores == ["bindPose1"]
        assert fake.dag_pose_restored == fake.joints
        assert not any("as they are" in w for w in out["warnings"])
        assert not fake.attributeQuery("mcp_clip", node="|root", exists=True)

    def test_outcome_b_reports_what_the_restore_silently_skipped(self, fake):
        # (b) dagPose skips the connection-fed channels: no crash, but a
        # result claiming "bind pose restored" while part of the skeleton
        # never moved is exactly the reporting dishonesty #796 is about.
        fake.bind_poses = ["bindPose1"]
        _author(fake)
        _plant_sdk_curve(fake)                     # |root|mid|tip.rotateX
        out = clip.delete_clip({"root": "root"})
        assert any("tip (rotateX)" in w and "still driven" in w
                   for w in out["warnings"])
        assert "|root|mid|tip" not in fake.dag_pose_restored
        assert not fake.attributeQuery("mcp_clip", node="|root", exists=True)

    def test_outcome_a_never_kills_a_teardown_mid_mutation(self, fake):
        # (a) dagPose raises. The clip curves are already deleted by then,
        # so a traceback here leaves a rig that still REPORTS clips it no
        # longer has - the metadata attrs are removed after the restore.
        fake.bind_poses = ["bindPose1"]
        _author(fake)
        _plant_sdk_curve(fake)
        fake.dag_pose_restore_raises = True
        out = clip.delete_clip({"root": "root"})
        assert any("bind-pose restore RAISED" in w for w in out["warnings"])
        assert any("tip (rotateX)" in w for w in out["warnings"])
        assert out["clips"] == []
        assert not fake.attributeQuery("mcp_clip", node="|root", exists=True)
        assert not fake.attributeQuery("mcp_clip_rest", node="|root",
                                       exists=True)
        assert clip.clip_meta(fake, "|root") == []

    def test_an_unexplained_restore_failure_still_propagates(self, fake):
        # The catch is not a blanket one. With nothing driving the rig
        # there is no #796 story to tell, so a failing restore is a real
        # failure and stays one - today's behaviour, unchanged.
        fake.bind_poses = ["bindPose1"]
        _author(fake)
        fake.dag_pose_restore_raises = True
        with pytest.raises(RuntimeError, match="cannot restore"):
            clip.delete_clip({"root": "root"})

    def test_a_driven_root_translation_is_stuck_here_too(self, fake):
        # dagPose restores a whole TRANSFORM, so a connection on
        # `.translateY` defeats it exactly the way one on `.rotateX` does.
        # (The no-bind-pose fallback stays rotate-only: zeroing rotations
        # is all it ever writes.)
        fake.bind_poses = ["bindPose1"]
        _author(fake)
        _plant_sdk_curve(fake, plug="|root.translateY",
                         curve="root_ty_driven")
        out = clip.delete_clip({"root": "root"})
        assert any("root (translateY)" in w for w in out["warnings"])
        assert "|root" not in fake.dag_pose_restored

    def test_both_branches_name_a_stuck_channel_the_same_way(self,
                                                             monkeypatch):
        # One vocabulary for one fact: the bound restore and the unbound
        # zeroing report the same channels with the same words, differing
        # only in HOW the return failed.
        def _teardown(bind):
            f = _install(FakeCmds(), monkeypatch)
            f.bind_poses = bind
            _author(f)
            _plant_sdk_curve(f)
            return clip.delete_clip({"root": "root"})["warnings"]

        bound = _teardown(["bindPose1"])
        unbound = _teardown([])
        shared = ("as they are - tip (rotateX): a connection still feeds "
                  "those channels (a surviving set-driven key, an anim "
                  "layer, a constraint),")
        assert any(shared in w for w in bound)
        assert any(shared in w for w in unbound)


class TestStuckChannelReporting:
    """#796 review round 4 D and E: two warnings that contradict what they
    sit next to."""

    _NOTE = re.compile(r"left (\d+) joint \S+ as they are - (.*?): a "
                       r"connection")

    def _counted_and_listed(self, warnings):
        notes = [w for w in warnings if "as they are" in w]
        assert len(notes) == 1, notes
        found = self._NOTE.match(notes[0])
        assert found, notes[0]
        listed = sum(len(group.split("(")[1].rstrip(")").split(", "))
                     for group in found.group(2).split("; "))
        return int(found.group(1)), listed

    def _teardown(self, monkeypatch, bind_poses):
        f = _install(FakeCmds(), monkeypatch)
        f.bind_poses = list(bind_poses)
        _author(f)
        _plant_sdk_curve(f)                            # tip.rotateX
        _plant_sdk_curve(f, plug="|root|mid|tip.rotateY",
                         curve="tip_rotY_driven")
        _plant_sdk_curve(f, plug="|root.translateZ",
                         curve="root_tz_driven")
        return clip.delete_clip({"root": "root"})["warnings"]

    def test_the_bound_count_agrees_with_the_list(self, monkeypatch):
        # MEASURED before the fix: "left 2 joint channel(s) as they are -
        # root (translateZ); tip (rotateX, rotateY)" - 2 is the JOINT
        # count and the list names 3 channels.
        count, listed = self._counted_and_listed(
            self._teardown(monkeypatch, ["bindPose1"]))
        assert count == listed

    def test_the_unbound_count_agrees_with_the_list(self, monkeypatch):
        # The fallback branch names rotations only, and counted joints too:
        # one joint, two stuck rotations.
        count, listed = self._counted_and_listed(
            self._teardown(monkeypatch, []))
        assert count == listed

    def test_no_bind_pose_restore_is_claimed_when_it_raised(self, fake):
        # #796 review round 4 E: the "N bind poses exist; restored X" line
        # was appended unconditionally, including on the path where dagPose
        # had just RAISED and restored nothing at all.
        fake.bind_poses = ["bindPose1", "bindPose2"]
        _author(fake)
        _plant_sdk_curve(fake)
        fake.dag_pose_restore_raises = True
        out = clip.delete_clip({"root": "root"})
        assert any("bind-pose restore RAISED" in w for w in out["warnings"])
        assert not any("restored bindPose1" in w for w in out["warnings"])

    def test_the_extra_bind_pose_is_still_named_when_the_restore_lands(
            self, fake):
        # The other half: when the restore really happens, the caller still
        # learns which of the several bind poses was used.
        fake.bind_poses = ["bindPose1", "bindPose2"]
        _author(fake)
        out = clip.delete_clip({"root": "root"})
        assert any("2 bind poses exist; restored bindPose1" in w
                   for w in out["warnings"])


class TestGuards:
    JOINTS = ["|root", "|root|mid", "|root|mid|tip"]

    def _plant_sdk_curve(self, fake, **kw):
        return _plant_sdk_curve(fake, **kw)

    def test_static_pose_guard_names_the_clip(self, fake):
        _author(fake)
        with pytest.raises(HandlerError, match="clip 'idle'"):
            clip.guard_static_pose(fake, "|root", self.JOINTS,
                                   "pose_skeleton")

    def test_static_pose_guard_clip_curves_keep_todays_wording(self, fake):
        # The clip wording is load-bearing: the live gate and the tests above
        # assert on it, so the driven-key split must leave it byte-identical.
        _author(fake)
        with pytest.raises(HandlerError) as exc:
            clip.guard_static_pose(fake, "|root", self.JOINTS,
                                   "pose_skeleton")
        assert str(exc.value) == (
            "pose_skeleton refuses while animation curves drive this "
            "skeleton (clip 'idle') - a static write here would be "
            "overridden on the next frame change")
        assert exc.value.hint == (
            "author_clip re-authors the motion; delete_clip removes the "
            "curves and returns the skeleton to static posing")

    def test_static_pose_guard_sends_a_driven_key_to_its_own_fix(self, fake):
        # #767 M2: an SDK curve is a connection reading a driver, not a clip
        # channel. delete_clip would never remove it, so naming delete_clip
        # here sends the caller to a dead end.
        self._plant_sdk_curve(fake)
        with pytest.raises(HandlerError) as exc:
            clip.guard_static_pose(fake, "|root", self.JOINTS,
                                   "pose_skeleton")
        assert "set-driven key" in str(exc.value)
        assert "tip_rotX_driven" in str(exc.value)
        assert "remove the driven key" in exc.value.hint
        assert "delete_clip" not in str(exc.value) + (exc.value.hint or "")
        assert "author_clip" not in str(exc.value) + (exc.value.hint or "")

    def test_static_pose_guard_names_both_kinds_when_both_drive(self, fake):
        # Authoring first keeps author_clip's foreign-curve refusal out of
        # this: the SDK curve is planted onto a channel the clip never keys.
        _author(fake)
        self._plant_sdk_curve(fake)
        with pytest.raises(HandlerError) as exc:
            clip.guard_static_pose(fake, "|root", self.JOINTS,
                                   "pose_skeleton")
        message, hint = str(exc.value), exc.value.hint
        assert "animation curves drive this skeleton (clip 'idle')" in message
        assert "set-driven key" in message and "tip_rotX_driven" in message
        assert "delete_clip removes the curves" in hint
        assert "remove the driven key" in hint

    def test_the_mixed_hint_says_delete_clip_keeps_the_driven_keys(self, fake):
        """#796 defect 1 inverted this paragraph.

        delete_clip's teardown used to reap whatever _anim_curves returned,
        U-typed nodes included, so the hint had to warn that the clip fix
        would cost the caller their rig setup. It no longer does: the SDK
        curves are left standing and reported, so a hint that still promised
        their destruction would be the wrong diagnosis in the other
        direction.
        """
        _author(fake)
        self._plant_sdk_curve(fake)
        with pytest.raises(HandlerError) as exc:
            clip.guard_static_pose(fake, "|root", self.JOINTS,
                                   "pose_skeleton")
        hint = exc.value.hint
        assert "delete_clip's teardown would delete those" not in hint
        assert "leaves those driven-key curves standing" in hint

    def test_static_pose_guard_sees_a_curve_behind_a_pair_blend(self, fake):
        # #796 defect 2: Maya inserts a pairBlend the moment a plug is both
        # keyed and constrained. The direct query sees nothing, the guard
        # used to pass, and the curve overrode the static write on the next
        # evaluation - the exact wrongness this guard exists to prevent.
        curve = _plant_blend_curve(fake, "|root|mid.rotateX")
        with pytest.raises(HandlerError) as exc:
            clip.guard_static_pose(fake, "|root", self.JOINTS,
                                   "pose_skeleton")
        message, hint = str(exc.value), exc.value.hint
        assert curve in message
        assert "mid_pairBlend" in message      # the caller can act on it
        # delete_clip's own query is direct-only, so it cannot be the fix
        assert "delete_clip removes the curves" not in message + hint
        assert "mid_pairBlend" in hint

    def test_the_blend_walk_reaches_through_an_anim_layer_node(self, fake):
        # #796 review defect 4. Maya's ROTATION anim layers insert an
        # animBlendNodeAdditiveRotation whose `output` compound connects to
        # the joint's `.rotate` COMPOUND - and listConnections on a child
        # plug does not report a connection made on its parent. The walk
        # starts from the per-axis plugs _joint_plugs builds, so unless it
        # also asks the parent compound it never starts at all: the guard
        # passes and the layered curve overrides the static write. The
        # earlier version of this test planted a per-axis source the fake
        # was free to invent, so it proved the prefix match and nothing
        # about reachability. (animBlendNodeBase is abstract - nodeType
        # reports the derived name, so the match is still a prefix one.)
        curve = _plant_blend_curve(
            fake, "|root|mid.rotate", blend="layer_blend",
            curve="layered_crv",
            blend_type="animBlendNodeAdditiveRotation")
        assert fake.listConnections("|root|mid.rotateX", source=True,
                                    destination=False, plugs=True) is None
        with pytest.raises(HandlerError) as exc:
            clip.guard_static_pose(fake, "|root", self.JOINTS,
                                   "pose_skeleton")
        assert curve in str(exc.value) and "layer_blend" in str(exc.value)

    def test_a_layered_translate_compound_is_seen_too(self, fake):
        # The same asymmetry on the other compound _joint_plugs walks.
        curve = _plant_blend_curve(
            fake, "|root.translate", blend="root_layer_blend",
            curve="root_layered_crv",
            blend_type="animBlendNodeAdditiveDL")
        with pytest.raises(HandlerError) as exc:
            clip.guard_static_pose(fake, "|root", self.JOINTS,
                                   "pose_skeleton")
        assert curve in str(exc.value)

    def test_a_clip_and_a_hidden_curve_are_both_named(self, fake):
        # delete_clip is a real fix for the clip curves and NOT a fix for
        # the one behind the blend node - the hint has to say both.
        _author(fake)
        curve = _plant_blend_curve(fake, "|root|mid|tip.rotateX",
                                   blend="tip_pairBlend", curve="tip_crv")
        with pytest.raises(HandlerError) as exc:
            clip.guard_static_pose(fake, "|root", self.JOINTS,
                                   "pose_skeleton")
        message, hint = str(exc.value), exc.value.hint
        assert "clip 'idle'" in message
        assert "%s behind tip_pairBlend" % curve in message
        assert "delete_clip removes the curves" in hint
        assert "will NOT remove a curve hiding behind" in hint

    def test_an_indirect_driven_key_names_the_intermediary(self, fake):
        # #796 review defect 7: an indirect U-typed curve was merged into
        # sdk_curves and handed the DIRECT driven-key exit, whose hint is
        # "remove the driven key (delete its curve node)". That is false of
        # an indirect one and never names the intermediary: following it
        # destroys rig setup AND the guard still refuses, now with no curve
        # left to name. This is the dead-end hint refuse_driven_weight's
        # own docstring exists to prevent.
        _plant_blend_curve(fake, "|root|mid.rotateX", curve="mid_sdk",
                           curve_type="animCurveUL")
        with pytest.raises(HandlerError) as exc:
            clip.guard_static_pose(fake, "|root", self.JOINTS,
                                   "pose_skeleton")
        message, hint = str(exc.value), exc.value.hint
        assert "set-driven key" in message
        assert "mid_sdk behind mid_pairBlend" in message
        assert "mid_pairBlend" in hint

    def test_a_direct_and_an_indirect_driven_key_get_their_own_hints(
            self, fake):
        # Two different fixes, so two different hints - the direct one is
        # "delete the curve", the indirect one cannot be.
        _plant_sdk_curve(fake)                       # tip.rotateX, direct
        _plant_blend_curve(fake, "|root|mid.rotateX", curve="mid_sdk",
                           curve_type="animCurveUL")
        with pytest.raises(HandlerError) as exc:
            clip.guard_static_pose(fake, "|root", self.JOINTS,
                                   "pose_skeleton")
        message, hint = str(exc.value), exc.value.hint
        assert "tip_rotX_driven" in message and "mid_sdk" in message
        assert "remove the driven key" in hint      # for the direct one
        assert "mid_pairBlend" in hint              # for the indirect one

    def test_a_source_that_is_not_an_intermediary_stays_out_of_this(
            self, fake):
        # A constraint or an expression owning the plug is not a curve, and
        # this guard has never claimed those. The walk must not invent one.
        fake.driven_plugs = {"|root|mid.rotateX": "mid_expr.output"}
        fake.node_types = {"mid_expr": "expression"}
        clip.guard_static_pose(fake, "|root", self.JOINTS, "pose_skeleton")

    def test_the_blend_walk_never_revisits_a_node_in_a_cycle(self, fake):
        # #796 review defect 6: "it returned" proves nothing here - the
        # depth bound alone terminates the walk, so the old version of this
        # test passed with the cycle guard entirely deleted. Counting the
        # queries per node is what distinguishes them: blendA -> blendB ->
        # blendA revisits on the third hop unless the seen set stops it.
        # Asked of ONE plug, because the guard walks every plug on the
        # skeleton and a whole-guard count would not isolate the loop.
        _plant_blend_curve(fake, "|root|mid.rotateX", blend="blendA",
                           curve="blendB", curve_type="blendWeighted")
        fake.node_sources["blendB"] = ["blendA"]
        fake.connection_queries.clear()
        assert clip._curve_behind_a_blend(
            fake, "|root|mid.rotateX") == (None, None)
        assert fake.connection_queries.count("blendA") == 1
        assert fake.connection_queries.count("blendB") == 1
        # and the guard as a whole still comes back rather than hanging
        clip.guard_static_pose(fake, "|root", self.JOINTS, "pose_skeleton")

    def test_a_node_that_cannot_answer_degrades_instead_of_crashing(
            self, fake):
        # The _outside_wearers idiom: a query that raises must not take a
        # guard down with it.
        _plant_blend_curve(fake, "|root|mid.rotateX")
        fake.unqueryable = {"mid_pairBlend"}
        clip.guard_static_pose(fake, "|root", self.JOINTS, "pose_skeleton")

    def test_the_declared_channel_guard_has_two_faces(self, fake):
        # #796 review round 4 C: ONE implementation for both clip
        # producers, differing in the flag. author_clip REFUSES a joint it
        # cannot classify - it would otherwise key a plug that might
        # swallow the key silently, and nothing is mutated yet.
        # retarget_clip has no refusal of its own to fall back on there
        # (it writes with bakeResults, which #771 never measured), so it
        # says so and carries on.
        fake.unqueryable = {"|root|mid"}
        group = [("|root|mid", clip.ROTATE_ATTRS, "rotate")]
        notes = clip.guard_declared_channels(fake, "retarget_clip", group,
                                             refuse_unkeyable=False)
        assert len(notes) == 1
        assert "cannot tell what drives mid's rotate channels" in notes[0]
        assert "retarget_clip writes them blind" in notes[0]
        with pytest.raises(HandlerError, match="cannot tell what drives"):
            clip.guard_declared_channels(fake, "author_clip", group)

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
        with pytest.raises(HandlerError, match="no clip named 'walk'"):
            clip.preview_clip({"root": "root", "name": "walk"})
        with pytest.raises(HandlerError, match="unknown angle"):
            clip.preview_clip({"root": "root", "name": "idle",
                               "angle": "dutch"})
        with pytest.raises(HandlerError, match="every_nth"):
            clip.preview_clip({"root": "root", "name": "idle",
                               "every_nth": 0})

    def test_a_later_clip_renders_its_own_absolute_frames(self, fake,
                                                          monkeypatch):
        calls = self._wire(fake, monkeypatch)      # authors 'idle', 0..60
        _author(fake, name="walk", fps=30, keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"mid": [0, 0, 20]}}])
        out = clip.preview_clip({"root": "root", "name": "walk"})
        assert (out["start_frame"], out["end_frame"]) == (62, 92)
        # absolute frames drive the scene...
        assert [s["time"] for s in calls["shots"]][0] == 62
        assert [s["time"] for s in calls["shots"]][-1] == 92
        # ...clip-relative seconds are what the caller reads
        assert out["frames"][0] == {"frame": 62, "time_s": 0.0}
        assert out["frames"][-1]["time_s"] == pytest.approx(1.0)
        assert calls["shots"][0]["label"] == "t=0.00s"
        assert out["clip"] == "walk"

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

    def test_held_camera_frames_the_whole_journey(self, fake, monkeypatch):
        """#780: the held camera's framing box must be the UNION of the
        subject's bounds across every sampled frame, not frame 0's box -
        the fake's bbox rides the current time along X, so the union's X
        extent must span first sampled frame .. last sampled frame + 1."""
        calls = self._wire(fake, monkeypatch, duration_s=2.0, fps=30)
        out = clip.preview_clip({"root": "root", "name": "idle"})
        frames = [f["frame"] for f in out["frames"]]
        want = ([float(frames[0]), 0.0, 0.0],
                [float(frames[-1]) + 1.0, 2.0, 1.0])
        assert calls["shots"][0]["bbox"] == want
        # every shot carries the same held box - only shot 0 places the
        # camera today, but the framing promise is per-sheet, not per-shot
        assert all(s["bbox"] == want for s in calls["shots"])

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

    def test_preview_clip_stops_an_idle_ipr_and_warns(self, fake,
                                                       monkeypatch):
        self._wire(fake, monkeypatch)
        monkeypatch.setattr(clip.session, "stop_idle_ipr",
                            lambda cmds: ["closed the Arnold RenderView"])
        out = clip.preview_clip({"root": "root", "name": "idle"})
        assert any("closed the Arnold RenderView" in w and "#721" in w
                   for w in out["warnings"])


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


class TestClipsElsewherePredicate:
    def test_an_empty_clip_attr_on_another_root_is_not_a_clip(self, monkeypatch):
        # #731: a joint carrying mcp_clip that parses to [] must not trip the
        # "another skeleton carries clips" warning.
        fake = FakeCmds()
        fake.joints.append("|other")
        fake.string_attrs["|other"] = {"mcp_clip": "[]"}
        _install(fake, monkeypatch)
        out = _author(fake)
        assert not any("another skeleton carries clips" in w
                       for w in out["warnings"])

    def test_a_real_clip_on_another_root_still_warns(self, monkeypatch):
        fake = FakeCmds()
        fake.joints.append("|other")
        fake.string_attrs["|other"] = {
            "mcp_clip": json.dumps([{"name": "walk", "fps": 30,
                                     "start_frame": 0, "end_frame": 10}])}
        _install(fake, monkeypatch)
        out = _author(fake)
        assert any("another skeleton carries clips" in w
                   for w in out["warnings"])
