"""create_curve_form refusals that never touch Maya.

Whole-call validation runs before any cmds import (assemble-style): a bad
call must leave nothing behind, and these tests prove the refusal path is
Maya-free by running where maya is not importable at all.
"""
import importlib.util
import os

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import curveform

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_live_gate():
    """Load evals/curve_form_live.py by path (house convention - see
    tests/test_assemble_pivots_live.py). Its network calls all sit behind
    `if __name__ == "__main__"`, so importing it as a module only runs the
    sys.path setup and defines its functions/constants - no socket, no Maya.
    """
    path = os.path.join(REPO_ROOT, "evals", "curve_form_live.py")
    spec = importlib.util.spec_from_file_location("evals_curve_form_live", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_deviation_warn_matches_live_gate_tolerance():
    # #768 review RIDER: curveform.DEVIATION_WARN (the self-report threshold
    # returned in every create_curve_form result's `warnings`) and
    # evals/curve_form_live.py's TOLERANCE (the live gate's pass/fail bar)
    # are two independently-written 0.02 literals that share ONE measurement
    # provenance (both cite the same 2026-08-27 vase/horn/torso run in their
    # own comments) - nothing enforces they stay equal if either is edited.
    live_gate = _load_live_gate()
    assert curveform.DEVIATION_WARN == live_gate.TOLERANCE


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
