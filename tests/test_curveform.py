"""create_curve_form refusals that never touch Maya.

Whole-call validation runs before any cmds import (assemble-style): a bad
call must leave nothing behind, and these tests prove the refusal path is
Maya-free by running where maya is not importable at all.
"""
import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import curveform


class TestParamGate:
    def test_unknown_key_refused_with_synonym(self):
        # require_known_keys puts the synonym phrase in .hint, not the
        # message (see tests/test_dispatcher.py's own convention) - str(exc)
        # only carries "does not take 'points'".
        with pytest.raises(HandlerError) as exc:
            curveform.create_curve_form({
                "kind": "sweep", "name": "horn",
                "points": [[0, 0, 0], [0, 1, 0]]})
        assert "'points' is called 'path'" in exc.value.hint

    def test_taper_names_width(self):
        with pytest.raises(HandlerError) as exc:
            curveform.create_curve_form({
                "kind": "sweep", "name": "horn",
                "path": [[0, 0, 0], [0, 1, 0]], "taper": 0.5})
        assert "'taper' is called 'width'" in exc.value.hint

    def test_missing_name_refused(self):
        with pytest.raises(HandlerError, match="name"):
            curveform.create_curve_form({
                "kind": "sweep", "path": [[0, 0, 0], [0, 1, 0]]})

    def test_bad_spec_refused_before_any_maya_import(self):
        # This test RUNNING headless is itself the assertion that
        # validation precedes Maya - a cmds import here would blow up.
        with pytest.raises(HandlerError, match="kind"):
            curveform.create_curve_form({"kind": "nope", "name": "x"})

    def test_over_budget_resolution_refused(self):
        # 512x256 (MAX_ALONG x MAX_AROUND) is only 131074 faces - far under
        # MAX_PRIMITIVE_FACES (1,000,000), so predicted_faces can never fire
        # through a validated spec (see curveform_math.predicted_faces's
        # docstring). The real ceiling a caller can actually hit here is the
        # per-axis MAX_ALONG/MAX_AROUND clamp - exceed that instead; the
        # point stands either way: an impossible bill is refused before Maya.
        with pytest.raises(HandlerError, match="resolution.along"):
            curveform.create_curve_form({
                "kind": "revolve", "name": "vase",
                "profile": [[0.5, 0.0], [0.3, 1.0]],
                "resolution": {"along": 513, "around": 256},
                "degrees": 360})
