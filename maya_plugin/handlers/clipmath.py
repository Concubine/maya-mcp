"""Pure clip math for #695: no Maya, no scene - the testable half of clip.py.

Times are seconds, rotations degrees (#636), root positions metres. The
scene-facing half (name resolution, keying, measurement) lives in clip.py.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..dispatcher import HandlerError

# The frame rates Maya has NATIVE time units for. author_clip sets the scene
# unit to match, so a frame IS one key-time unit and the bake range is exact -
# an arbitrary-fps knob would put keys between frames silently.
FPS_UNITS = {24: "film", 25: "pal", 30: "ntsc",
             48: "show", 50: "palf", 60: "ntscf"}
MAX_KEYS = 64
# Loop closure tolerances: float noise passes, an authoring mistake does not.
# A 0.001-degree joint step or a 0.1 mm root step is invisible at any frame
# rate; a real pop is orders of magnitude above both.
LOOP_TOL_DEG = 1e-3
LOOP_TOL = 1e-4


def _vec3(value, what: str) -> Optional[List[float]]:
    if value is None:
        return None
    if (not isinstance(value, (list, tuple)) or len(value) != 3
            or any(isinstance(v, bool) or not isinstance(v, (int, float))
                   for v in value)):
        raise HandlerError("%s must be [x, y, z] numbers" % what)
    return [float(v) for v in value]


def validated_keys(keys) -> List[Dict[str, Any]]:
    """Normalized key dicts, or a refusal. Structure only - names that need a
    scene (joints, aliases) are clip.py's to resolve."""
    if (not isinstance(keys, list) or not 2 <= len(keys) <= MAX_KEYS):
        raise HandlerError(
            "keys must be a list of 2..%d {time_s, rotations?, blend_weights?,"
            " root_position?} entries" % MAX_KEYS,
            hint="a clip is at least a start and an end key")
    out: List[Dict[str, Any]] = []
    for i, entry in enumerate(keys):
        if not isinstance(entry, dict):
            raise HandlerError("keys[%d] must be a dict" % i)
        t = entry.get("time_s")
        if isinstance(t, bool) or not isinstance(t, (int, float)) or t < 0:
            raise HandlerError("keys[%d].time_s must be a number >= 0" % i,
                               hint="seconds from the clip start")
        rotations = entry.get("rotations")
        if rotations is None:
            rotations = {}
        if not isinstance(rotations, dict):
            raise HandlerError("keys[%d].rotations must be a map of joint "
                               "name to [rx, ry, rz] degrees" % i)
        rot_out = {}
        for name, triple in rotations.items():
            v = _vec3(triple, "keys[%d].rotations[%r]" % (i, name))
            if v is None:
                raise HandlerError(
                    "keys[%d].rotations[%r] must be [rx, ry, rz]" % (i, name))
            rot_out[name] = v
        weights = entry.get("blend_weights")
        if weights is None:
            weights = {}
        if not isinstance(weights, dict):
            raise HandlerError("keys[%d].blend_weights must be a map of "
                               "target name to 0..1" % i)
        for name, value in weights.items():
            if (isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not 0.0 <= float(value) <= 1.0):
                raise HandlerError(
                    "keys[%d].blend_weights[%r] must be a number in 0..1, "
                    "got %r" % (i, name, value))
        weights = {k: float(v) for k, v in weights.items()}
        root_position = _vec3(entry.get("root_position"),
                              "keys[%d].root_position" % i)
        if not rot_out and not weights and root_position is None:
            raise HandlerError(
                "keys[%d] names no channel" % i,
                hint="every key carries at least one of rotations, "
                     "blend_weights, root_position")
        out.append({"time_s": float(t), "rotations": rot_out,
                    "blend_weights": weights, "root_position": root_position})
    if out[0]["time_s"] != 0.0:
        raise HandlerError(
            "keys must start at time_s 0.0 (got %g)" % out[0]["time_s"],
            hint="the bake range is 0..duration; a later first key would "
                 "bake frames of unstated pose")
    for i in range(1, len(out)):
        if out[i]["time_s"] <= out[i - 1]["time_s"]:
            raise HandlerError(
                "key times must be strictly increasing (keys[%d] at %g after "
                "%g)" % (i, out[i]["time_s"], out[i - 1]["time_s"]))
    return out


def fractional_frame_times(times: List[float], fps: int) -> List[float]:
    """Key times that do not land on an integer frame at this fps - the baked
    export samples integer frames, so these keys are between samples."""
    out = []
    for t in times:
        frame = t * fps
        if abs(frame - round(frame)) > 1e-6:
            out.append(t)
    return out


def loop_violations(first: Dict[str, Any], last: Dict[str, Any]) -> List[str]:
    """Ways the last key fails to close onto the first, with measured deltas.

    Channel-set equality is required: a channel absent from either end cannot
    prove closure, and Maya would hold/interpolate it into a pop on repeat.
    """
    out: List[str] = []
    f_rot, l_rot = first["rotations"], last["rotations"]
    for name in sorted(set(f_rot) | set(l_rot)):
        if name not in l_rot:
            out.append("loop: joint %r is keyed on the first key but not the "
                       "last key" % name)
        elif name not in f_rot:
            out.append("loop: joint %r is keyed on the last key but not the "
                       "first key" % name)
        else:
            worst = max(abs(a - b) for a, b in zip(f_rot[name], l_rot[name]))
            if worst > LOOP_TOL_DEG:
                out.append(
                    "loop: joint %r ends %.4g degrees away from where it "
                    "starts (first %s, last %s)"
                    % (name, worst, f_rot[name], l_rot[name]))
    f_w, l_w = first["blend_weights"], last["blend_weights"]
    for name in sorted(set(f_w) | set(l_w)):
        if name not in l_w:
            out.append("loop: weight %r is keyed on the first key but not "
                       "the last key" % name)
        elif name not in f_w:
            out.append("loop: weight %r is keyed on the last key but not "
                       "the first key" % name)
        elif abs(f_w[name] - l_w[name]) > LOOP_TOL:
            out.append("loop: weight %r ends at %g, starts at %g"
                       % (name, l_w[name], f_w[name]))
    f_rp, l_rp = first["root_position"], last["root_position"]
    if (f_rp is None) != (l_rp is None):
        out.append("loop: root_position is keyed on only one end of the clip")
    elif f_rp is not None:
        worst = max(abs(a - b) for a, b in zip(f_rp, l_rp))
        if worst > LOOP_TOL:
            out.append("loop: root_position ends %.4g away from where it starts "
                       "(first %s, last %s)" % (worst, f_rp, l_rp))
    return out
