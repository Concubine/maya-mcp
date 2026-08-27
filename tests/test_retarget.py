"""retarget_clip refusals that never touch Maya (#774 Task 3).

House pattern proven in #768: these tests RUNNING headless (no `maya.cmds`
importable anywhere in this process) IS the proof that whole-call validation
happens before any Maya import - retarget_clip must refuse a bad call on
params alone, never getting as far as `_cmds()`.
"""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import retarget


def base(**over):
    p = {"file": "evals/mocap_fixtures/cmu_walk.bvh", "root": "|rig|Hips",
         "clip": "walk01"}
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
