"""retarget_clip refusals that never touch Maya (#774 Task 3).

House pattern proven in #768: these tests RUNNING headless (no `maya.cmds`
importable anywhere in this process) IS the proof that whole-call validation
happens before any Maya import - retarget_clip must refuse a bad call on
params alone, never getting as far as `_cmds()`.
"""

import pytest

from maya_plugin.dispatcher import HandlerError, require_known_keys
from maya_plugin.handlers import cleanclip, retarget


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
