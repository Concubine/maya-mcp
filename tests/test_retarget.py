"""retarget_clip refusals that never touch Maya (#774 Task 3).

House pattern proven in #768: these tests RUNNING headless (no `maya.cmds`
importable anywhere in this process) IS the proof that whole-call validation
happens before any Maya import - retarget_clip must refuse a bad call on
params alone, never getting as far as `_cmds()`.
"""

import pytest

from maya_plugin.dispatcher import HandlerError
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
