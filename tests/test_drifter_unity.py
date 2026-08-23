"""#743 consumer-gate POLICY, exercised without any Unity at all.

#718's consumer gate found three defects and ALL THREE were in the gate,
not the product. A policy that only ever runs against a live editor is a
policy nobody has tested.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "evals"))

import drifter_unity as du  # noqa: E402

DECLARED = {
    "joints": 105,
    "blend_targets": ["bell_crease", "tendril_flare"],
    "looping_clips": ["drift_idle", "pulse_swim"],
    "tolerances": {"seam": 1e-4, "compare": 1e-3},
    "clips": [{"name": "drift_idle", "duration_s": 2.0},
              {"name": "pulse_swim", "duration_s": 1.0},
              {"name": "tendril_reach", "duration_s": 1.2}],
    "samples": [
        {"clip": "pulse_swim", "frame": 0, "rim_diameter": 1.2,
         "apex_to_tip": 3.9},
        {"clip": "pulse_swim", "frame": 30, "rim_diameter": 1.2,
         "apex_to_tip": 3.9},
    ],
}


def _measured(**over):
    base = {
        "bones": 105,
        "blend_shapes": ["bell_crease", "tendril_flare"],
        "clips": [{"name": "drift_idle", "length": 2.0},
                  {"name": "pulse_swim", "length": 1.0},
                  {"name": "tendril_reach", "length": 1.2}],
        "bones_per_vertex_max": 4,
        "samples": [dict(s) for s in DECLARED["samples"]],
    }
    base.update(over)
    return base


def test_a_clean_import_passes():
    assert du.verify(DECLARED, _measured())["ok"] is True


def test_a_missing_clip_fails():
    m = _measured()
    m["clips"] = [c for c in m["clips"] if c["name"] != "pulse_swim"]
    out = du.verify(DECLARED, m)
    assert out["ok"] is False
    assert any("pulse_swim" in p for p in out["problems"])


def test_a_wrong_bone_count_fails():
    out = du.verify(DECLARED, _measured(bones=104))
    assert out["ok"] is False
    assert any("bone" in p.lower() for p in out["problems"])


def test_a_missing_blend_shape_fails():
    out = du.verify(DECLARED, _measured(blend_shapes=["bell_crease"]))
    assert out["ok"] is False
    assert any("tendril_flare" in p for p in out["problems"])


def test_deformation_outside_tolerance_fails():
    m = _measured()
    m["samples"][1]["apex_to_tip"] = 3.5
    out = du.verify(DECLARED, m)
    assert out["ok"] is False
    assert any("apex_to_tip" in p for p in out["problems"])


def test_a_loop_that_reopens_in_unity_fails():
    m = _measured()
    m["samples"][1]["rim_diameter"] = 1.3
    out = du.verify(DECLARED, m)
    assert out["ok"] is False
    assert any("seam" in p.lower() for p in out["problems"])


def test_truncation_is_reported_but_does_not_fail_the_gate():
    """Unity capping at 4 is a MEASUREMENT, not a product defect."""
    out = du.verify(DECLARED, _measured(bones_per_vertex_max=4))
    assert out["ok"] is True
    assert "bones_per_vertex_max" in out["detail"]
