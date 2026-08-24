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
        # is_looping mirrors DECLARED["looping_clips"] - the C# emits the
        # field for every clip, so a fixture without it models a template
        # that no longer exists.
        "clips": [{"name": "drift_idle", "length": 2.0, "is_looping": True},
                  {"name": "pulse_swim", "length": 1.0, "is_looping": True},
                  {"name": "tendril_reach", "length": 1.2,
                   "is_looping": False}],
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


# --- Loop flag: measured 2026-08-24, and no gate had ever looked ----------
#
# The seam check proves the GEOMETRY closes - drift_idle's first and last
# frame agreed to 0.000000 m. It says nothing about whether Unity will
# actually replay the clip. MEASURED on the real import: all four clips
# arrive with AnimationClip.isLooping == false, because the FBX importer
# defaults every take's loopTime off. Dropped into a game as-is, a
# perfectly seamless drift_idle plays once and stops.


def test_a_declared_looping_clip_must_import_as_looping():
    m = _measured(clips=[{"name": "drift_idle", "length": 2.0,
                          "is_looping": False},
                         {"name": "pulse_swim", "length": 1.0,
                          "is_looping": True},
                         {"name": "tendril_reach", "length": 1.2,
                          "is_looping": False}])
    got = du.verify(DECLARED, m)
    assert got["ok"] is False
    assert any("drift_idle" in p and "loop" in p.lower()
               for p in got["problems"]), got["problems"]


def test_loop_flags_correct_on_every_clip_passes():
    m = _measured(clips=[{"name": "drift_idle", "length": 2.0,
                          "is_looping": True},
                         {"name": "pulse_swim", "length": 1.0,
                          "is_looping": True},
                         {"name": "tendril_reach", "length": 1.2,
                          "is_looping": False}])
    assert du.verify(DECLARED, m)["ok"] is True


def test_a_one_shot_clip_that_imports_looping_is_also_a_problem():
    m = _measured(clips=[{"name": "drift_idle", "length": 2.0,
                          "is_looping": True},
                         {"name": "pulse_swim", "length": 1.0,
                          "is_looping": True},
                         {"name": "tendril_reach", "length": 1.2,
                          "is_looping": True}])
    got = du.verify(DECLARED, m)
    assert got["ok"] is False
    assert any("tendril_reach" in p and "loop" in p.lower()
               for p in got["problems"]), got["problems"]


def test_a_measurement_without_loop_flags_is_refused_not_ignored():
    # An older C# template that never emitted the field must FAIL loudly
    # rather than silently skipping the check - the #718 rule.
    stripped = _measured()
    for c in stripped["clips"]:
        c.pop("is_looping", None)
    got = du.verify(DECLARED, stripped)
    assert got["ok"] is False
    assert any("is_looping" in p for p in got["problems"]), got["problems"]
