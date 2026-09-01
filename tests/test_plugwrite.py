"""The shared static-write guard (#802).

Six commands used to answer "can I write this plug" for themselves, or not
ask at all. They ask this module now, so this is where the answer is pinned -
including the two halves of Maya's behaviour that no handler test can
distinguish, because a fake refuses both and Maya refuses only one:

  * a LOCK and a plain wire make setAttr RAISE;
  * a CONSTRAINT or a curve does NOT - the write lands and is discarded at
    the next evaluation.

Both are "this command cannot deliver what it was asked for", which is why
the guard's verdict is the same for both and only its wording differs.
Everything asserted here about Maya was measured by
evals/static_write_probe_802.py and evals/static_write_probe_802b.py; the
label in a comment (A01, B01, ...) is that probe's row.
"""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import plugwrite


class FakeCmds:
    """The two queries the guard makes, answered EXACTLY as Maya answers.

    Exact-plug in both, because the compound/child asymmetry is the guard's
    whole reason for walking a family: `getAttr('.rotate', lock=True)` is
    False while rotateX is locked (A01), and `listConnections('.rotate')` is
    None while all three children are constraint-fed (B01). A fake that
    folded them together would make every interesting case pass vacuously.
    """

    def __init__(self):
        self.locked = set()
        self.driven = {}         # plug -> source plug
        self.types = {}          # source node -> nodeType
        self.nodes = {"|a", "|a|b"}

    def _require(self, plug):
        node = plug.rpartition(".")[0]
        if node not in self.nodes and node not in self.types:
            raise RuntimeError("No object matches name: %s" % plug)

    def getAttr(self, plug, lock=False, **kw):
        self._require(plug)
        if kw:
            raise TypeError("only lock= is modelled (#802): %r" % sorted(kw))
        if lock:
            return plug in self.locked
        raise RuntimeError("the fake serves lock queries only")

    def listConnections(self, plug, source=False, destination=True,
                        plugs=False, type=None, **kw):
        self._require(plug)
        assert source and not destination, "source queries only"
        src = self.driven.get(plug)
        if src is None:
            return None
        return [src] if plugs else [src.split(".")[0]]

    def nodeType(self, node):
        if node in self.nodes:
            # the two registered nodes are joints; anything else a test
            # registers is a plain transform (a camera, a prop)
            return "joint" if node.startswith("|a") else "transform"
        if node not in self.types:
            raise RuntimeError("No object matches name: %s" % node)
        return self.types[node]


@pytest.fixture
def fake():
    return FakeCmds()


class TestFamily:
    """Which plugs Maya folds into a write, and which it does not."""

    def test_a_compound_pulls_in_its_children(self):
        assert plugwrite.family("|a.rotate") == [
            "|a.rotate", "|a.rotateX", "|a.rotateY", "|a.rotateZ"]

    def test_a_child_pulls_in_its_compound(self):
        assert plugwrite.family("|a.rotateY") == ["|a.rotateY", "|a.rotate"]

    def test_a_child_never_pulls_in_a_sibling(self):
        """MEASURED (A05): setAttr('.rotateY') succeeds while rotateX is
        locked. Folding siblings in would refuse a write Maya takes, and a
        guard that over-refuses gets weakened back by the next reader."""
        assert "|a.rotateX" not in plugwrite.family("|a.rotateY")

    def test_a_scalar_plug_stands_alone(self):
        assert plugwrite.family("|a|b.focalLength") == ["|a|b.focalLength"]

    def test_shear_is_a_compound_whose_children_are_not_xyz(self):
        assert plugwrite.family("|a.shear")[1:] == [
            "|a.shearXY", "|a.shearXZ", "|a.shearYZ"]

    def test_pivots_expands_to_both_pivots(self):
        """`xform -pivots` writes rotatePivot AND scalePivot, so a guard
        for that flag has to ask about both or it half-checks the call."""
        assert plugwrite.transform_plugs("|a", ["pivots"]) == [
            "|a.rotatePivot", "|a.scalePivot"]

    def test_other_channels_are_the_compound_of_the_same_name(self):
        assert plugwrite.transform_plugs("|a", ["translate", "rotate"]) == [
            "|a.translate", "|a.rotate"]


class TestBlocker:
    def test_a_free_plug_blocks_nothing(self, fake):
        assert plugwrite.blocker(fake, "|a.translate") == []

    def test_a_locked_child_blocks_the_compound(self, fake):
        # A04: "A child attribute of 'x.rotate' is locked or connected".
        fake.locked = {"|a.rotateX"}
        (block,) = plugwrite.blocker(fake, "|a.rotate")
        assert block.reason == "locked" and block.at == "|a.rotateX"
        assert block.plug == "|a.rotate"

    def test_a_locked_compound_blocks_a_child(self, fake):
        # A09/A11: the child reports locked when the compound is.
        fake.locked = {"|a.translate"}
        (block,) = plugwrite.blocker(fake, "|a.translateY")
        assert block.reason == "locked" and block.at == "|a.translate"

    def test_a_locked_sibling_blocks_nothing(self, fake):
        fake.locked = {"|a.rotateX"}
        assert plugwrite.blocker(fake, "|a.rotateY") == []

    def test_every_obstacle_in_the_family_is_reported(self, fake):
        """Three locked axes of ONE joint are one plug to every caller, so
        stopping at the first would name one axis, send the rigger to
        unlock it, and refuse twice more (review catch)."""
        fake.locked = {"|a.rotateX", "|a.rotateY", "|a.rotateZ"}
        found = plugwrite.blocker(fake, "|a.rotate")
        assert [b.at for b in found] == ["|a.rotateX", "|a.rotateY",
                                         "|a.rotateZ"]

    def test_the_owner_is_classified_as_a_joint_or_not(self, fake):
        """The clip hint names delete_clip only where delete_clip can go."""
        fake.nodes = {"|a", "|cam"}
        fake.driven = {"|a.rotateX": "|crv1.output",
                       "|cam.rotateX": "|crv2.output"}
        fake.types = {"|crv1": "animCurveTA", "|crv2": "animCurveTA"}
        assert plugwrite.blocker(fake, "|a.rotate")[0].joint is True
        assert plugwrite.blocker(fake, "|cam.rotate")[0].joint is False

    def test_a_constrained_child_blocks_the_compound(self, fake):
        # B01/B02: the compound query answers None, the child answers the
        # constraint - so only a family walk finds this.
        fake.driven = {"|a.rotateX": "|oc1.constraintRotateX"}
        fake.types = {"|oc1": "orientConstraint"}
        (block,) = plugwrite.blocker(fake, "|a.rotate")
        assert block.reason == "driven"
        assert block.source == "|oc1.constraintRotateX"
        assert block.kind == "other"

    def test_a_curve_is_classified_as_a_clip(self, fake):
        fake.driven = {"|a.translateY": "|crv1.output"}
        fake.types = {"|crv1": "animCurveTL"}
        assert plugwrite.blocker(fake, "|a.translate")[0].kind == "clip"

    def test_a_driven_key_is_told_apart_from_a_clip(self, fake):
        """A U-typed curve reads a DRIVER attribute; "delete_clip" is a
        wrong diagnosis for it and sends the caller to destroy rig setup."""
        fake.driven = {"|a.translateY": "|sdk1.output"}
        fake.types = {"|sdk1": "animCurveUL"}
        assert plugwrite.blocker(fake, "|a.translate")[0].kind == "driven_key"

    def test_a_corrective_is_told_apart_too(self, fake):
        fake.driven = {"|a.rotateX": "|interp1.output[0]"}
        fake.types = {"|interp1": "poseInterpolator"}
        assert plugwrite.blocker(fake, "|a.rotate")[0].kind == "corrective"

    def test_lock_is_reported_before_a_connection_on_the_same_plug(self, fake):
        """Both are true of a plug Maya refuses; the lock is the one the
        caller can act on with one command, so a plug is asked once."""
        fake.locked = {"|a.rotateX"}
        fake.driven = {"|a.rotateX": "|crv1.output"}
        fake.types = {"|crv1": "animCurveTA"}
        found = plugwrite.blocker(fake, "|a.rotate")
        assert [b.reason for b in found] == ["locked"]

    def test_a_missing_plug_raises_rather_than_answering_free(self, fake):
        """M01/M02: `getAttr` on a plug Maya does not have raises. A guard
        that swallowed that would report every typo as writable."""
        with pytest.raises(RuntimeError, match="No object matches name"):
            plugwrite.blocker(fake, "|ghost.translate")


class TestBlockers:
    def test_every_blocked_plug_is_reported_not_just_the_first(self, fake):
        fake.locked = {"|a.rotateX", "|a|b.translateZ"}
        found = plugwrite.blockers(
            fake, ["|a.rotate", "|a.scale", "|a|b.translate"])
        assert [b.plug for b in found] == ["|a.rotate", "|a|b.translate"]

    def test_a_repeated_plug_is_asked_about_once(self, fake):
        fake.locked = {"|a.rotateX"}
        found = plugwrite.blockers(fake, ["|a.rotate", "|a.rotate"])
        assert len(found) == 1


class TestRefusal:
    def _err(self, fake, plugs, what="pose_skeleton", **kw):
        with pytest.raises(HandlerError) as exc:
            plugwrite.guard(fake, plugs, what, **kw)
        return exc.value

    def test_a_free_call_is_not_refused(self, fake):
        plugwrite.guard(fake, ["|a.translate", "|a.rotate"], "transform")

    def test_the_refusal_names_the_command_the_plug_and_the_obstacle(self, fake):
        fake.locked = {"|a.rotateX"}
        err = self._err(fake, ["|a.rotate"])
        assert "pose_skeleton" in str(err)
        assert "|a.rotate" in str(err) and "|a.rotateX" in str(err)
        assert "locked" in str(err)

    def test_a_locked_plug_is_told_how_to_unlock_it_by_name(self, fake):
        fake.locked = {"|a.rotateX"}
        assert "|a.rotateX" in self._err(fake, ["|a.rotate"]).hint

    def test_a_clip_curve_on_a_joint_is_sent_to_delete_clip(self, fake):
        fake.driven = {"|a.rotateY": "|crv1.output"}
        fake.types = {"|crv1": "animCurveTA"}
        assert self._err(fake, ["|a.rotate"]).hint.startswith("delete_clip")

    def test_a_clip_curve_on_a_camera_is_NOT_sent_to_delete_clip(self, fake):
        """delete_clip takes a skeleton root and nothing else. A keyed
        camera or prop used to get that hint anyway - the wrong-hint class
        this module exists to end, shipped by the module itself (review
        catch)."""
        fake.nodes = {"|cam"}
        fake.driven = {"|cam.translateX": "|cam_tx.output"}
        fake.types = {"|cam_tx": "animCurveTL"}
        hint = self._err(fake, ["|cam.translate"], what="set_camera").hint
        assert "delete_clip cannot be aimed at |cam" in hint
        assert "disconnect the animation curve |cam_tx" in hint
        assert not hint.startswith("delete_clip")

    def test_a_driven_key_is_NOT_sent_to_delete_clip(self, fake):
        """delete_clip deliberately leaves U-typed curves standing (#796
        defect 1), so naming it here would be a hint that cannot work."""
        fake.driven = {"|a.rotateY": "|sdk1.output"}
        fake.types = {"|sdk1": "animCurveUA"}
        hint = self._err(fake, ["|a.rotate"]).hint
        assert hint.startswith("remove the driven key")
        # delete_clip appears only as the disclaimer that it will NOT do it,
        # which is the wording guard_static_pose settled on for the same
        # curve: a caller who follows "delete_clip" here destroys rig setup,
        # is refused again, and has no curve left to name.
        assert "delete_clip deliberately leaves those standing" in hint

    def test_a_corrective_is_sent_to_its_driver_joint(self, fake):
        fake.driven = {"|a.rotateY": "|interp1.output[0]"}
        fake.types = {"|interp1": "poseInterpolator"}
        assert "driver joint" in self._err(fake, ["|a.rotate"]).hint

    def test_a_constraint_is_named_without_a_curve_diagnosis(self, fake):
        fake.driven = {"|a.rotateY": "|oc1.constraintRotateY"}
        fake.types = {"|oc1": "orientConstraint"}
        err = self._err(fake, ["|a.rotate"])
        assert "|oc1.constraintRotateY" in str(err)
        assert "curve" not in err.hint

    def test_two_different_obstacles_are_both_hinted(self, fake):
        fake.locked = {"|a.rotateX"}
        fake.driven = {"|a|b.translateY": "|crv1.output"}
        fake.types = {"|crv1": "animCurveTL"}
        err = self._err(fake, ["|a.rotate", "|a|b.translate"], what="transform")
        assert "unlock" in err.hint and "delete_clip" in err.hint

    def test_two_locks_name_both_plugs(self, fake):
        fake.locked = {"|a.rotateX", "|a|b.translateY"}
        hint = self._err(fake, ["|a.rotate", "|a|b.translate"]).hint
        # Two locks, two named plugs - a lock's fix names ITS plug.
        assert hint.count("unlock the channel") == 2
        assert "|a.rotateX" in hint and "|a|b.translateY" in hint
        assert "delete_clip" not in hint

    def test_one_piece_of_advice_is_given_once(self, fake):
        """Two curve-driven plugs share one fix; the hint says it once.
        (Review catch: the dedupe's suppressing branch was exercised by no
        test - two LOCKS differ in wording because a lock names its plug.)"""
        fake.driven = {"|a.rotateY": "|crv1.output",
                       "|a|b.rotateZ": "|crv2.output"}
        fake.types = {"|crv1": "animCurveTA", "|crv2": "animCurveTA"}
        hint = self._err(fake, ["|a.rotate", "|a|b.rotate"]).hint
        assert hint.count("delete_clip removes the curves") == 1

    def test_the_consequence_is_the_callers_to_state(self, fake):
        fake.locked = {"|a.rotateX"}
        err = self._err(fake, ["|a.rotate"],
                        consequence="nothing was moved")
        assert "nothing was moved" in str(err)

    def test_a_command_specific_epilogue_lands_last_in_the_hint(self, fake):
        """The diagnosis is shared so it cannot drift; what to do INSTEAD is
        the command's own (add_corrective can say "re-author the motion
        afterwards"; transform cannot)."""
        fake.locked = {"|a.rotateX"}
        err = self._err(fake, ["|a.rotate"], hint_tail="then try again")
        assert err.hint.endswith("then try again")


class TestDescribe:
    """The sentence the passes that must NOT refuse use instead."""

    def test_a_lock_says_maya_refuses_the_write(self, fake):
        fake.locked = {"|a.rotateY"}
        (block,) = plugwrite.blocker(fake, "|a.rotateY")
        text = plugwrite.describe(block, "render_scene")
        assert "render_scene" in text and "|a.rotateY" in text
        assert "refuses" in text

    def test_a_connection_says_refused_OR_overridden(self, fake):
        """Both halves, because from here the guard cannot tell which: a
        curve takes the write and discards it, a plain wire refuses it, and
        the caller's loss is identical either way."""
        fake.driven = {"|a.rotateY": "|crv1.output"}
        fake.types = {"|crv1": "animCurveTA"}
        (block,) = plugwrite.blocker(fake, "|a.rotateY")
        text = plugwrite.describe(block, "render_scene")
        assert "overridden" in text and "|crv1.output" in text


class TestTheFakeRefusesWhatMayaRefuses:
    """The fake above answers two queries; both must answer like Maya.

    A fake wrong in the STRICT direction is as bad as a permissive one -
    #799's lesson, and the reason `getAttr(lock=)` here is exact-plug
    rather than family-aware.
    """

    def test_a_compound_lock_query_ignores_a_locked_child(self, fake):
        # A01, the measurement the whole family walk exists for.
        fake.locked = {"|a.rotateX"}
        assert fake.getAttr("|a.rotate", lock=True) is False
        assert fake.getAttr("|a.rotateX", lock=True) is True

    def test_a_compound_connection_query_ignores_a_fed_child(self, fake):
        # B01/C01.
        fake.driven = {"|a.rotateX": "|oc1.constraintRotateX"}
        assert fake.listConnections("|a.rotate", source=True,
                                    destination=False, plugs=True) is None
        assert fake.listConnections("|a.rotateX", source=True,
                                    destination=False, plugs=True) == [
            "|oc1.constraintRotateX"]

    def test_a_node_that_does_not_exist_raises_from_either_query(self, fake):
        for call in (lambda: fake.getAttr("|ghost.rotate", lock=True),
                     lambda: fake.listConnections("|ghost.rotate", source=True,
                                                  destination=False)):
            with pytest.raises(RuntimeError, match="No object matches name"):
                call()

    def test_an_unmodelled_getattr_flag_raises_rather_than_lying(self, fake):
        """`settable=True` predicted setAttr's outcome in every wiring the
        probe measured, and this fake does not model it. Answering the
        VALUE for it - which is what a bare **kw does - would be a silent
        lie about the one question that could replace this guard."""
        with pytest.raises(TypeError, match="lock="):
            fake.getAttr("|a.rotate", settable=True)

    def test_a_destination_query_is_refused_as_unmodelled(self, fake):
        with pytest.raises(AssertionError, match="source queries only"):
            fake.listConnections("|a.rotate", source=True, destination=True)

    def test_an_unregistered_source_type_raises(self, fake):
        """The guard classifies by asking nodeType about the source. A fake
        that invented a type there would let a wrong hint ship green."""
        fake.driven = {"|a.rotateX": "|mystery.out"}
        with pytest.raises(RuntimeError, match="No object matches name"):
            plugwrite.blocker(fake, "|a.rotate")
