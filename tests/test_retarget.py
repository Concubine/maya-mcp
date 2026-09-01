"""retarget_clip refusals that never touch Maya (#774 Task 3), plus the
guards it shares with author_clip (#796).

House pattern proven in #768: these tests RUNNING headless (no `maya.cmds`
importable anywhere in this process) IS the proof that whole-call validation
happens before any Maya import - retarget_clip must refuse a bad call on
params alone, never getting as far as `_cmds()`.

The shared-guard class at the bottom is the exception to "no Maya at all":
`_apply_shared_guards` takes `cmds` as an argument, so it is driven with
test_clip.py's FakeCmds directly - the fake that already models the
`listConnections(type="animCurve")` behaviour under test (a purpose-built
stub here would model the very thing the defect is about).
"""

import pytest

from maya_plugin.dispatcher import HandlerError, require_known_keys
from maya_plugin.handlers import cleanclip, clip, retarget
from tests.test_clip import FakeCmds, _plant_blend_curve, _plant_sdk_curve


def base(**over):
    p = {"file": "evals/mocap_fixtures/cmu_walk.bvh", "root": "|rig|Hips",
         "clip": "walk01"}
    p.update(over)
    return p


def clean_base(**over):
    p = {"root": "|rig|Hips", "clip": "walk01"}
    p.update(over)
    return p


class TestParamGate:
    def test_unknown_key_refused_with_synonym(self):
        # require_known_keys puts the synonym phrase in .hint, not the
        # message (dispatcher.py) - the same adjustment test_curveform.py
        # already made for this exact pattern; pytest.raises(match=...)
        # checks str(exc), which is message-only.
        with pytest.raises(HandlerError) as exc:
            retarget.retarget_clip({**base(), "path": "x.bvh"})
        assert "'path' is called 'file'" in exc.value.hint

    def test_missing_file_param_refused(self):
        p = base()
        del p["file"]
        with pytest.raises(HandlerError, match="file"):
            retarget.retarget_clip(p)

    def test_nonexistent_file_refused_before_maya(self):
        with pytest.raises(HandlerError, match="no such file"):
            retarget.retarget_clip(base(file="evals/mocap_fixtures/nope.bvh"))

    def test_unsupported_extension_refused(self):
        with pytest.raises(HandlerError, match=r"\.bvh or \.fbx"):
            retarget.retarget_clip(base(file="evals/live_call.py"))

    def test_bad_clip_name_refused(self):
        with pytest.raises(HandlerError, match="identifier"):
            retarget.retarget_clip(base(clip="2 bad name"))

    def test_bad_range_refused(self):
        with pytest.raises(HandlerError, match="start"):
            retarget.retarget_clip(base(start=50, end=10))


class TestCleanClipParamGate:
    """clean_clip (#774 Task 5) refusals that never touch Maya: whole-call
    validation happens before `_cmds()`, proven the same way TestParamGate
    proves it for retarget_clip - these run in a process where
    `maya.cmds` is not importable at all."""

    def test_unknown_key_refused_with_name_synonym(self):
        p = clean_base()
        del p["clip"]
        p["name"] = "walk01"
        with pytest.raises(HandlerError) as exc:
            cleanclip.clean_clip(p)
        assert "'name' is called 'clip'" in exc.value.hint

    def test_unknown_key_refused_with_smoothing_synonym(self):
        with pytest.raises(HandlerError) as exc:
            cleanclip.clean_clip({**clean_base(), "smoothing": True})
        assert "'smoothing' is called 'filter'" in exc.value.hint

    def test_filter_must_be_bool_or_window_dict(self):
        with pytest.raises(HandlerError, match="filter"):
            cleanclip.clean_clip({**clean_base(), "filter": "yes"})

    def test_filter_window_must_be_odd_and_at_least_five(self):
        with pytest.raises(HandlerError, match="window"):
            cleanclip.clean_clip({**clean_base(), "filter": {"window": 4}})

    def test_filter_dict_refuses_unknown_key(self):
        with pytest.raises(HandlerError, match="filter"):
            cleanclip.clean_clip({**clean_base(), "filter": {"wrong": 5}})

    def test_lock_contacts_must_be_bool_or_joints_dict(self):
        with pytest.raises(HandlerError, match="lock_contacts"):
            cleanclip.clean_clip({**clean_base(), "lock_contacts": "yes"})

    def test_lock_contacts_joints_must_be_a_non_empty_list(self):
        with pytest.raises(HandlerError, match="joints"):
            cleanclip.clean_clip(
                {**clean_base(), "lock_contacts": {"joints": []}})

    def test_lock_contacts_dict_refuses_unknown_key(self):
        with pytest.raises(HandlerError, match="lock_contacts"):
            cleanclip.clean_clip(
                {**clean_base(), "lock_contacts": {"wrong": ["x"]}})

    def test_both_passes_false_refused(self):
        with pytest.raises(HandlerError, match="nothing"):
            cleanclip.clean_clip(
                {**clean_base(), "filter": False, "lock_contacts": False})

    def test_missing_root_refused_before_maya(self):
        p = clean_base()
        del p["root"]
        with pytest.raises(HandlerError, match="root"):
            cleanclip.clean_clip(p)


class TestWireShapedParams:
    """The MCP server (src/maya_mcp/server.py) sends EVERY declared param on
    EVERY call, `None` for whichever ones the caller left unset - it never
    conditionally omits a key (the #768 lesson, TestWireShapedParams in
    test_curveform_math.py is the sibling of this class). These build the
    request dict EXACTLY as server.py's maya_retarget_clip/maya_clean_clip
    send it and drive it through the real handler far enough to prove no
    foreign-key or None-handling refusal fires."""

    # server.py's maya_retarget_clip request dict: file/root/clip always a
    # caller-given string, start/end/fps None when left unset.
    _RETARGET_WIRE_KEYS = ("file", "root", "clip", "start", "end", "fps")
    # server.py's maya_clean_clip request dict: filter/lock_contacts are the
    # cap_ends-style literal-default exception (#768 ruling) - wire-defaulted
    # True, never None, even when the caller left them unset.
    _CLEAN_WIRE_KEYS = ("root", "clip", "filter", "lock_contacts")

    def _retarget_wire_dict(self, **over):
        params = {k: None for k in self._RETARGET_WIRE_KEYS}
        params.update({"file": "evals/mocap_fixtures/nope.bvh",
                       "root": "|rig|Hips", "clip": "walk01"})
        params.update(over)
        return params

    def _clean_wire_dict(self, **over):
        params = {k: None for k in self._CLEAN_WIRE_KEYS}
        params["filter"] = True
        params["lock_contacts"] = True
        params.update({"root": "|rig|Hips", "clip": "walk01"})
        params.update(over)
        return params

    def test_retarget_wire_shape_reaches_file_existence_refusal(self):
        # Every key server.py sends is present, start/end/fps None (the
        # unset case). A key-gate or None-handling regression would refuse
        # on 'start'/'end'/'fps' before ever touching the filesystem; the
        # file-existence refusal proves all of them passed clean and
        # validation got past the key gate.
        with pytest.raises(HandlerError, match="no such file"):
            retarget.retarget_clip(self._retarget_wire_dict())

    def test_clean_clip_wire_key_set_accepted_by_key_gate(self):
        # clean_clip's own validation reaches a real `import maya.cmds`
        # partway through any call whose root/clip are otherwise valid, so
        # driving a fully-valid wire dict all the way through is not
        # possible in this headless process. The minimal honest check: the
        # exact wire key set, with filter/lock_contacts's literal True
        # default, is not refused by the key gate itself.
        require_known_keys(self._clean_wire_dict(),
                            cleanclip.CLEAN_CLIP_KEYS, "clean_clip",
                            cleanclip.CLEAN_CLIP_SYNONYMS)

    def test_clean_clip_wire_shape_reaches_root_refusal(self):
        # Every key server.py sends is present, filter/lock_contacts at
        # their wire-default True. A key-gate or None-handling regression
        # on either of those would refuse before root is ever inspected;
        # an empty root instead reaches root's OWN pure refusal, proving
        # filter/lock_contacts (and the both-false check) passed clean.
        with pytest.raises(HandlerError, match="root"):
            cleanclip.clean_clip(self._clean_wire_dict(root=""))


class TestSharedGuards:
    """#796 review round 4 C: retarget_clip is this repo's SECOND clip
    producer, and `_apply_shared_guards` is where it borrows author_clip's
    rules. It was still calling the RAW `clip._anim_curves`, whose
    type="animCurve" filter matches the U-typed set-driven-key nodes - so a
    rig carrying a driven key was refused as "hand-authored animation this
    tool did not author", the hint sent the caller to delete_clip, and
    delete_clip refuses that rig saying it never removes set-driven keys.
    The exact closed loop round 2 fixed in author_clip, still live one tool
    over.
    """

    JOINTS = ["|root", "|root|mid", "|root|mid|tip"]
    # The HIK slot joints - the ones `bakeResults` is actually aimed at
    # (both routes bake `target_slot_joints.values()`, not the hierarchy).
    SLOTS = {"Hips": "|root", "Spine": "|root|mid"}

    def _guard(self, fake, warnings=None):
        return retarget._apply_shared_guards(
            fake, "|root", self.JOINTS, self.SLOTS, 30,
            [] if warnings is None else warnings)

    def test_a_set_driven_key_is_not_a_foreign_clip_curve(self):
        fake = FakeCmds()
        _plant_sdk_curve(fake)                     # |root|mid|tip.rotateX
        assert self._guard(fake) == []             # no records, no refusal

    def test_a_hand_authored_clip_curve_still_refuses(self):
        # The guard this tool must not lose: real hand-authored animation
        # on the target is still work a bake would destroy.
        fake = FakeCmds()
        fake.curves["|root|mid.rotateZ"] = "hand_authored_crv"
        with pytest.raises(HandlerError) as exc:
            self._guard(fake)
        assert "hand-authored" in str(exc.value)

    def test_the_refusal_counts_only_what_delete_clip_deletes(self):
        # The hint names delete_clip, so the channels it counts have to be
        # channels delete_clip actually removes - author_clip's own rule.
        fake = FakeCmds()
        fake.curves["|root|mid.rotateZ"] = "hand_authored_crv"
        _plant_sdk_curve(fake)
        with pytest.raises(HandlerError) as exc:
            self._guard(fake)
        assert "1 hand-authored" in str(exc.value)
        assert "tip_rotX_driven" not in str(exc.value)

    def test_a_driven_key_on_a_baked_channel_is_named(self):
        # The per-channel treatment, where it applies: `bakeResults` writes
        # every keyable channel of the SLOT joints, so a driven key on one
        # is worth saying. A WARNING, not a refusal - #771 measured
        # setKeyframe, and nothing here has measured what a bake does to a
        # connection-fed plug.
        fake = FakeCmds()
        _plant_sdk_curve(fake, plug="|root|mid.rotateZ",
                         curve="mid_rotZ_driven")
        warnings = []
        self._guard(fake, warnings)
        assert any("|root|mid.rotateZ" in w and "mid_rotZ_driven" in w
                   for w in warnings)

    def test_a_driven_key_off_the_baked_channels_says_nothing(self):
        # Per channel, never per rig: tip is no HIK slot joint here, so
        # nothing this call writes goes near it.
        fake = FakeCmds()
        _plant_sdk_curve(fake)                     # |root|mid|tip.rotateX
        warnings = []
        self._guard(fake, warnings)
        assert warnings == []

    def test_a_driven_scale_on_a_slot_joint_is_named(self):
        # #796 review round 6 D: the guard asked ROTATE and TRANSLATE while
        # its own comment (and protocol.md) claimed that was everything
        # `bakeResults` writes. With no `-attribute` flag a bake writes
        # every KEYABLE channel, so a squash-and-stretch set-driven key on
        # a slot joint's .scaleY was baked over with nothing named.
        fake = FakeCmds()
        _plant_sdk_curve(fake, plug="|root|mid.scaleY",
                         curve="mid_sy_driven")
        warnings = []
        self._guard(fake, warnings)
        assert any("|root|mid.scaleY" in w and "mid_sy_driven" in w
                   for w in warnings)

    def test_a_driven_user_keyable_attribute_is_named(self):
        # ASKED, never guessed: the channel list comes from Maya
        # (`listAttr(keyable=True)`), so an attribute a rigger added -
        # which no hardcoded triple could have anticipated - is asked
        # about like any other baked channel.
        fake = FakeCmds()
        fake.keyable_extras = {"|root|mid": ["stretch"]}
        _plant_sdk_curve(fake, plug="|root|mid.stretch",
                         curve="mid_stretch_driven")
        warnings = []
        self._guard(fake, warnings)
        assert any("|root|mid.stretch" in w and "mid_stretch_driven" in w
                   for w in warnings)

    def test_a_driven_scale_off_the_baked_joints_still_says_nothing(self):
        # Per channel, never per rig - the widening does not widen the
        # NODES asked, only the channels of the ones this bake writes.
        fake = FakeCmds()
        _plant_sdk_curve(fake, plug="|root|mid|tip.scaleY",
                         curve="tip_sy_driven")
        warnings = []
        self._guard(fake, warnings)
        assert warnings == []

    def test_a_joint_that_cannot_list_its_channels_says_so(self):
        # The degrade rule: losing the widening costs a note, not the
        # guard - the rotate and translate triples are still asked.
        fake = FakeCmds()

        def refuse(plug, multi=False, keyable=False):
            if keyable:
                raise RuntimeError("no such node: %s" % plug)
            return FakeCmds.listAttr(fake, plug, multi=multi)

        fake.listAttr = refuse
        _plant_sdk_curve(fake, plug="|root|mid.rotateZ",
                         curve="mid_rotZ_driven")
        warnings = []
        self._guard(fake, warnings)
        assert any("keyable" in w and "|root|mid" in w for w in warnings)
        assert any("|root|mid.rotateZ" in w and "mid_rotZ_driven" in w
                   for w in warnings)

    def test_the_note_is_the_one_author_clip_gives(self):
        # ONE scene, ONE diagnosis - the curve behind the intermediary is
        # named the way guard_static_pose and author_clip name it.
        fake = FakeCmds()
        curve = _plant_blend_curve(fake, "|root|mid.rotateZ",
                                   curve="mid_rotZ_crv")
        warnings = []
        self._guard(fake, warnings)
        assert any("%s behind mid_pairBlend" % curve in w for w in warnings)


class TestReplaceCut:
    """#796 review round 5 A: both retarget routes call
    `clip.cut_replaced_range` to vacate a re-retargeted clip's old frames,
    which is a DESTRUCTIVE time-range `cutKey` over every plug of
    `target_joints`. A driven-key curve on one of those joints is indexed
    by DRIVER VALUE, so that range is a numeric range on the driver -
    exactly the hazard `clip_curve_plugs`' docstring names, at the one site
    that was never given the partition.
    """

    JOINTS = TestSharedGuards.JOINTS
    REPLACED = {"name": "walk01", "start_frame": 0, "end_frame": 30}

    def test_the_vacating_cut_never_touches_a_driven_key_plug(self):
        fake = FakeCmds()
        _plant_sdk_curve(fake)                  # |root|mid|tip.rotateX
        fake.keys["|root|mid|tip.rotateX"] = {0.0: 0.0, 15.0: 3.0,
                                              90.0: 9.0}
        clip.cut_replaced_range(fake, self.JOINTS, self.REPLACED)
        assert "|root|mid|tip.rotateX" not in fake.cut_plugs
        assert sorted(fake.keys["|root|mid|tip.rotateX"]) == [0.0, 15.0,
                                                              90.0]

    def test_the_vacating_cut_still_clears_the_clip_plugs(self):
        fake = FakeCmds()
        fake.curves["|root|mid.rotateZ"] = "walk01_crv"
        fake.keys["|root|mid.rotateZ"] = {0.0: 0.0, 20.0: 45.0}
        clip.cut_replaced_range(fake, self.JOINTS, self.REPLACED)
        assert "|root|mid.rotateZ" in fake.cut_plugs
        assert fake.keys.get("|root|mid.rotateZ") in (None, {})

    def test_the_skipped_plug_is_reported_to_the_caller(self):
        # The retarget routes append what this returns to their own
        # `warnings`, so a plug the cut stepped around is not silent.
        fake = FakeCmds()
        _plant_sdk_curve(fake)
        notes = clip.cut_replaced_range(fake, self.JOINTS, self.REPLACED)
        assert any("|root|mid|tip.rotateX" in n and "tip_rotX_driven" in n
                   for n in notes)


class TestNotSelfContainedNote:
    """#796 review round 5, the round-4 leftover ASSESSED: `retarget_clip`
    runs no #718 self-contained pad/back-fill pass. It bakes the 15 HIK slot
    joints over its own frames and registers a record declaring no channel
    at all, so a channel another clip declares and this bake does not cover
    holds that neighbour's value across the retargeted take - and the NEXT
    author_clip does not pin against this one either.

    The fix is author_clip's whole padding pass, whose pieces are closures
    inside it; too large to lift on a round that ends at a live gate. The
    take is named instead of silently wrong.
    """

    def test_the_retarget_first_ordering_is_told_too(self):
        # #796 review round 6 B: the note fired ONLY where neighbours
        # already existed - and the ordering that actually needs it is the
        # normal mocap workflow, which retargets FIRST. That record
        # declares `joints: []`, so the author_clip that comes next pins
        # nothing against this take and its neighbour's pose bleeds
        # straight into the retargeted range. The mitigation covered the
        # one ordering it was not filed for.
        note = retarget.not_self_contained_note([])
        assert note is not None
        assert "NOT self-contained" in note
        assert "declares no channel" in note

    def test_a_rig_with_neighbours_is_told_and_they_are_named(self):
        note = retarget.not_self_contained_note(
            [{"name": "idle"}, {"name": "wave"}])
        assert note is not None
        assert "NOT self-contained" in note
        assert "'idle', 'wave'" in note
        assert "declares no channel" in note
