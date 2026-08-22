"""Task 12 gate for #718: three named clips on ONE rig's shared timeline,
each keying a DISJOINT channel set, so the feature's own correctness rule
is what is under test - all clips share ONE animation curve per channel,
so a joint any clip does not declare would otherwise hold whatever a
neighbour left on it. author_clip pins every channel at each clip's own
boundary frames to prevent that, in BOTH directions:

    idle  - spine/chest sway only, 2.0 s, loop closing on a NON-rest -3
            degree base pose (not 0) - a rest-valued boundary would make
            "idle's joints sit at rest in a later clip's range" pass
            whether or not the forward pin ran
    wave  - one arm only (R_shoulder/R_elbow), 1.5 s, starting MID-GESTURE
            (not the rest T-pose) - touches NO joint idle or step
            declares, and its non-rest first key is what a missing
            backward pin would visibly leak into idle's range
    step  - hips/legs plus root_position, 1.2 s, loop - root_position is
            the BACKWARDS case: neither idle nor wave ever uses it, so its
            introduction here is what proves the backward pin actually
            runs (a curve holds its first key's value backwards in time,
            so a channel a LATER clip introduces would otherwise rewrite
            an EARLIER, already-judged clip's pose for it)

Measured checks (this script) + judged sheets (the acceptance):

    1  build humanoid + skeleton + bind (clip_live's scene setup, reused
       verbatim) -> author idle, wave, step in that order -> each clip's
       reported range is contiguous with the one-frame gap and
       non-overlapping (check_layout)
    2  forward contamination, both un-authored directions: inside each
       clip's own range, every joint/channel it does NOT declare is
       measured at rest (rest_probe) - the case clip_live's docstring
       calls "a channel this clip never mentions would hold whatever a
       neighbour left on it"
    3  backward contamination: clip idle's per-frame mesh state, measured
       by independently walking its OWN frames (probe_displacement, not
       author_clip's sparse per_key sample) BEFORE step exists and again
       AFTER - idle never used root_position and step is what introduces
       it. Two series are compared: max_displacement (against idle's own
       first frame - a fine liveness check, but a CONSTANT offset cancels
       out of it under linear blend skinning, so it cannot actually catch
       a missing backward pin) and centroid (an ABSOLUTE per-frame
       position - a constant offset does NOT cancel here, which is what
       makes it the actual proof; #718 review Fix 1)
    3b forward contamination's one un-probed direction: step's own last
       key equals its first (loop close) at a NON-rest pose, so its hold
       forward into whatever clip follows it (wave, in the final layout)
       is checked the same way (#718 review Fix 2)
    4  re-authoring the MIDDLE clip (wave) moves it to the tail; idle's
       and step's own keyframe times AND values, read back independently
       (capture_keys), are byte-identical before and after
    5  delete_clip(name="wave") removes exactly one clip and leaves idle
       and step's own keys still byte-identical to the captured state;
       wave is then re-authored to restore all three clips for export
    6  export with include_animation=true: the three declared takes are
       present by name with the right start_s/stop_s, EVERY joint of the
       RIG's channel UNION (clipmath.channel_union - every channel any
       clip touches, not just each take's own declared joints - #718
       review Fix 3) carries a curve record attributed to EVERY take with
       the right key count for that take's OWN span, and an independent
       byte re-read (fbxbytes) agrees with the tool's own report
    7  preview_clip renders each of the three clips - JUDGED (idle's sheet
       must show a still arm and still legs, wave's a still spine and
       still legs, step's a still spine and still arm) AND ASSERTED: every
       rendered frame lies inside that clip's own declared range (#718
       review Fix 4 - on a shared timeline, rendering a NEIGHBOUR's frames
       is exactly the multi-take failure mode)

Rotation literals for the legs/hips/root reuse clip_live.WALK_KEYS'
hip/knee/ankle/root_position table verbatim (arms/shoulders dropped) -
those signs were MEASURED, not derived, in that gate's first run; see its
WALK_KEYS comment for the probe numbers. The wave arm literals are new to
this gate and were checked against the rendered sheet (see the report).

DESTRUCTIVE: calls new_scene. Port 9878, the agent-launched Maya, per the
two-Maya policy - never point this at the user's 9877 (or the second
disposable instance some sessions run on 9879).

Run:  uv run python evals/multi_take_live.py
Exit: 0 pass, 1 fail, 2 no connection.
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys

from PIL import Image

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from humanoid_live import JOINTS, MESH, PARTS  # noqa: E402
from live_call import call, structured_result  # noqa: E402
from maya_plugin.handlers import clipmath, fbxbytes  # noqa: E402
from maya_plugin.handlers.clip import CLIP_ATTR  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
OUT_DIR = os.path.join(_HERE, "multi_take_live")
JOINT_COUNT = len(JOINTS)

# The rig's build-time root position (humanoid_live.JOINTS) - a joint's
# rest pose before any clip poses it. Used as the expected value when a
# probe checks that root_position sits at rest inside a clip that never
# uses it (idle, wave).
PELVIS_REST = next(j["position"] for j in JOINTS if j["name"] == "pelvis")
REST_ROT_TOL = 1e-4   # degrees
REST_POS_TOL = 1e-4   # metres

# Preview framing - inherited from clip_live.py's measured band (same rig,
# same three_point lighting, same 640 px resolution): at 320 px the figure
# was too small to judge motion, and a mean luminance outside 30..240 means
# the render is blown out or black rather than actually judgeable.
PREVIEW_RESOLUTION = 640
IDLE_ZOOM = 2.0
WAVE_ZOOM = 1.8
STEP_ZOOM = 1.5
LIT_THRESHOLD = 18
FIGURE_PIXELS_MIN = 2000
LUMINANCE_BAND = (30.0, 240.0)

IDLE_FPS = 30
WAVE_FPS = 30
STEP_FPS = 30

# idle: spine/chest sway only. Same shape as clip_live.IDLE_KEYS with the
# shoulder/blink channels dropped - this gate needs idle to declare
# NOTHING wave or step also declare, so the sway is spine/chest alone.
#
# MEASURED (this gate's first run): spine_01/chest share the vertical-bone
# convention (humanoid_live.biped_pose's table: local Y ~ world X for
# these joints, same axis family as WALK's hips), so a Y rotation is a
# fore/aft PITCH - visible as a lean from the SIDE, nearly invisible from
# the FRONT (a front camera looks straight down that lean and only sees
# foreshortening). The first run previewed idle from the front at +-3/+-1
# degrees and the rendered sheet showed no visible sway at all despite
# every number being green - a false pass this fix corrects two ways:
# preview_clip's angle is "side" below (not "front"), and the amplitude is
# widened to a clearly-legible lean.
#
# #718 review Fix 2: the loop closes on a -3 degree base pose, NOT on 0.
# A loop only requires first key == last key (clipmath.loop_violations),
# never that either equal rest - and rest (0) is exactly the value the
# forward-contamination pins put on spine_01/chest inside wave's and
# step's ranges. With idle's own boundary AT 0 too, "idle's joints sit at
# rest in a later clip's range" passed whether or not the forward pin ran
# (the curve would hold 0 forward regardless). Shifting the whole cycle by
# a constant -3 degrees keeps every displacement-based assertion below
# unchanged (each key's *relative* motion from the cycle's own base is
# identical to before) while making idle's un-padded hold-forward value
# (-3 degrees) provably different from the rest value (0 degrees) the pin
# is required to write instead.
IDLE_KEYS = [
    {"time_s": 0.0,
     "rotations": {"spine_01": [0, -3, 0], "chest": [0, -3, 0]}},
    {"time_s": 0.5,
     "rotations": {"spine_01": [0, -13, 0], "chest": [0, -13, 0]}},
    {"time_s": 1.0,
     "rotations": {"spine_01": [0, -3, 0], "chest": [0, -3, 0]}},
    {"time_s": 1.2,
     "rotations": {"spine_01": [0, 1, 0], "chest": [0, 1, 0]}},
    {"time_s": 2.0,
     "rotations": {"spine_01": [0, -3, 0], "chest": [0, -3, 0]}},
]

# wave: one arm only. Deliberately touches no joint idle or step declare.
#
# #718 review Fix 2: the FIRST key starts mid-gesture (arm already
# raised), not at the rest T-pose (0,0,0). wave's first key is the value
# the BACKWARD pin must write across idle's whole range when wave
# introduces R_shoulder/R_elbow - with a rest-valued first key, "idle's
# range: wave's joints sit at rest" passed whether or not that pin ran (a
# curve holds its first key backward in time regardless, and that key was
# already rest). A non-rest first key ([0,0,-40]/[0,0,20]) makes the
# un-pinned backward hold (a raised arm) measurably different from the
# rest the pin is required to write instead.
WAVE_KEYS = [
    {"time_s": 0.0,
     "rotations": {"R_shoulder": [0, 0, -40], "R_elbow": [0, 0, 20]}},
    {"time_s": 0.5,
     "rotations": {"R_shoulder": [0, 0, -70], "R_elbow": [0, 0, 35]}},
    {"time_s": 1.0,
     "rotations": {"R_shoulder": [0, 0, -35], "R_elbow": [0, 0, 10]}},
    {"time_s": 1.5,
     "rotations": {"R_shoulder": [0, 0, -70], "R_elbow": [0, 0, 35]}},
]

# step: hips/legs plus root_position. Hip/knee/ankle/root_position
# literals reused verbatim from clip_live.WALK_KEYS (arms/shoulders
# dropped) - contact (L forward) -> passing -> contact (R forward) ->
# passing -> contact (loop close).
STEP_KEYS = [
    {"time_s": 0.0,
     "rotations": {"L_hip": [0, 25, 0], "R_hip": [0, -20, 0],
                   "L_knee": [0, 5, 0], "R_knee": [0, -30, 0],
                   "L_ankle": [0, 0, -5], "R_ankle": [0, 0, 10]},
     "root_position": [0.0, 0.97, 0.0]},
    {"time_s": 0.3,
     "rotations": {"L_hip": [0, 0, 0], "R_hip": [0, 5, 0],
                   "L_knee": [0, -5, 0], "R_knee": [0, -45, 0],
                   "L_ankle": [0, 0, 0], "R_ankle": [0, 0, -15]},
     "root_position": [0.0, 1.01, 0.0]},
    {"time_s": 0.6,
     "rotations": {"L_hip": [0, -20, 0], "R_hip": [0, 25, 0],
                   "L_knee": [0, -30, 0], "R_knee": [0, 5, 0],
                   "L_ankle": [0, 0, 10], "R_ankle": [0, 0, -5]},
     "root_position": [0.0, 0.97, 0.0]},
    {"time_s": 0.9,
     "rotations": {"L_hip": [0, 5, 0], "R_hip": [0, 0, 0],
                   "L_knee": [0, -45, 0], "R_knee": [0, -5, 0],
                   "L_ankle": [0, 0, -15], "R_ankle": [0, 0, 0]},
     "root_position": [0.0, 1.01, 0.0]},
    {"time_s": 1.2,
     "rotations": {"L_hip": [0, 25, 0], "R_hip": [0, -20, 0],
                   "L_knee": [0, 5, 0], "R_knee": [0, -30, 0],
                   "L_ankle": [0, 0, -5], "R_ankle": [0, 0, 10]},
     "root_position": [0.0, 0.97, 0.0]},
]

def _joints_of(keys):
    return sorted({j for k in keys for j in k["rotations"]})


# #718 review Fix 5: derived from the KEYS tables themselves, not
# hand-duplicated - a joint added to one table without updating the
# matching list here would silently go unprobed by rest_probe below.
IDLE_JOINTS = _joints_of(IDLE_KEYS)
WAVE_JOINTS = _joints_of(WAVE_KEYS)
STEP_JOINTS = _joints_of(STEP_KEYS)

# The gate's entire premise: each clip's declared joints are disjoint from
# the other two, so a rest_probe reading joint X inside a clip that never
# declares it is unambiguously testing contamination, not a shared channel.
assert not set(IDLE_JOINTS) & set(WAVE_JOINTS), "idle/wave joints overlap"
assert not set(IDLE_JOINTS) & set(STEP_JOINTS), "idle/step joints overlap"
assert not set(WAVE_JOINTS) & set(STEP_JOINTS), "wave/step joints overlap"

CHECKS = []


def check(label, passed, detail=""):
    CHECKS.append((bool(passed), label))
    print("%s %s%s" % ("PASS" if passed else "FAIL", label,
                       ("  [%s]" % detail) if detail else ""))
    return bool(passed)


def send(command, params, timeout_s=300.0):
    try:
        return call(command, params, timeout_s=timeout_s, port=PORT)
    except (ConnectionRefusedError, OSError) as exc:
        print("could not reach a Maya plugin on %s: %s" % (PORT, exc))
        sys.exit(2)


def ok(command, params, timeout_s=300.0):
    response = send(command, params, timeout_s)
    if response.get("status") != "ok":
        print("FAIL: %s: %s" % (command,
                                json.dumps(response.get("error"))[:600]))
        sys.exit(1)
    return response.get("result") or {}


def py(code, what, timeout_s=300.0):
    return structured_result(ok("execute_python", {"code": code},
                                timeout_s), what)


def out(name):
    return os.path.join(OUT_DIR, name)


def declared_clips(root):
    """The rig's declared clip records, read straight off the mcp_clip
    attribute - the same source export.py's own _scene_clips reads. An
    independent lookup: this script never imports clip.clip_meta."""
    return py(
        "import maya.cmds as cmds\nimport json\n"
        "json.loads(cmds.getAttr(%r))" % ("%s.%s" % (root, CLIP_ATTR)),
        "declared clips")


def check_layout(tag, records, require_exact_gap):
    """Check 1: non-overlapping, always; contiguous-with-a-1-frame-gap
    additionally when `require_exact_gap` (fresh append order only).

    GAP_FRAMES=1 means one unowned frame between a clip's end and the next
    clip's start, so freshly appended clips have consecutive starts at
    exactly end+2. That equality is NOT a general invariant of the
    declared set, though: #718 decision 5 is that a deleted or moved
    clip's vacated range is never re-packed ("a gap costs nothing"), so
    once a clip has been moved to the tail (leaving a hole where it used
    to sit) the remaining clips are no longer wall-to-wall - only
    disjointness still holds, which is checked either way. Passing
    require_exact_gap=True on a post-move layout would be asserting an
    invariant the design explicitly does not make; this gate's first run
    did exactly that and failed on its own wrong assumption, not a product
    defect."""
    ordered = sorted(records, key=lambda r: r["start_frame"])
    disjoint = all(ordered[i]["start_frame"] > ordered[i - 1]["end_frame"]
                  for i in range(1, len(ordered)))
    detail = json.dumps([(r["name"], r["start_frame"], r["end_frame"])
                         for r in ordered])
    if not require_exact_gap:
        check("%s: %d clips do not overlap" % (tag, len(ordered)),
              len(ordered) == 3 and disjoint, detail)
        return
    exact_gap = all(ordered[i]["start_frame"]
                    == ordered[i - 1]["end_frame"] + clipmath.GAP_FRAMES + 1
                    for i in range(1, len(ordered)))
    check("%s: %d clips are contiguous with a 1-frame gap and do not overlap"
          % (tag, len(ordered)), len(ordered) == 3 and exact_gap and disjoint,
          detail)


def capture_keys(tag, joints, meta, root=None):
    """{plug: [(time, value), ...]} read straight from the curves, SCOPED
    to `meta`'s own [start_frame, end_frame] - the ground truth checks 4
    and 5 diff against, independent of anything author_clip/delete_clip
    themselves reported.

    Scoped, not whole-curve, on purpose: every clip's channel lives on ONE
    shared curve (#718), so a neighbour's own boundary can legitimately
    grow or lose a pin key elsewhere on that SAME curve without this
    clip's own declared span changing at all - e.g. re-authoring 'wave'
    re-pins root_position's curve at wave's OWN new tail boundary (root is
    in 'wave doesn't declare it but a kept clip does' territory), which
    changes the root plug's WHOLE-curve key list without moving a single
    key inside 'step's own [start_frame, end_frame]. A whole-curve capture
    would report step's keys as "changed" for a reason that has nothing to
    do with step - measured directly: this gate's first run tripped
    exactly that false positive on both idle and step. Restricting the
    query to this clip's own frame range is what makes "byte-identical"
    mean the clip's OWN motion, not the curve's whole key list."""
    plugs = ["%s.rotate%s" % (j, axis) for j in joints for axis in "XYZ"]
    if root:
        plugs += ["%s.translate%s" % (root, axis) for axis in "XYZ"]
    start, end = int(meta["start_frame"]), int(meta["end_frame"])
    code = (
        "import maya.cmds as cmds\n"
        "_plugs = %(plugs)r\n"
        "_span = (%(start)d, %(end)d)\n"
        "_out = {}\n"
        "for _p in _plugs:\n"
        "    _times = cmds.keyframe(_p, query=True, time=_span) or []\n"
        "    _vals = cmds.keyframe(_p, query=True, time=_span,"
        " valueChange=True) or []\n"
        "    _out[_p] = [(round(t, 6), round(v, 6))"
        " for t, v in zip(_times, _vals)]\n"
        "_out"
    ) % {"plugs": plugs, "start": start, "end": end}
    return py(code, tag)


def probe_displacement(tag, meta, stride=3):
    """Per-frame measurement of MESH across `meta`'s OWN frame range,
    independent of anything author_clip itself computed (a fresh
    currentTime walk, over every sampled frame rather than just the
    authored key times, so a leak that only shows up between keys is not
    invisible to it). Two quantities per frame:

      max_displacement - vertex movement against the range's OWN first
        frame. The same measurement author_clip's per_key makes; a fine
        liveness check, but NOT the backward-contamination proof (see
        centroid below).

      centroid - the mesh's ABSOLUTE average vertex position. #718 review
      Fix 1: under linear blend skinning, P_f - P_0 = sum_i w_i(M_i(f) -
      M_i(0)), so any transform that is CONSTANT across the whole range
      (exactly what a curve holding a neighbour's key backward in time
      produces) contributes zero to that difference - max_displacement
      reads identical whether or not the backward pin ran, at every frame,
      by construction. centroid is an ABSOLUTE quantity: a constant
      offset does NOT cancel out of it, which is what makes comparing
      centroid before/after a later clip is authored an actual proof of
      the backward-pin guard, not a self-consistent-either-way check.
    """
    start, end = int(meta["start_frame"]), int(meta["end_frame"])
    frames = list(range(start, end + 1, stride))
    if frames[-1] != end:
        frames.append(end)
    code = (
        "import maya.cmds as cmds\n"
        "_mesh = %(mesh)r\n"
        "_frames = %(frames)r\n"
        "cmds.currentTime(%(start)d)\n"
        "_base = cmds.xform(_mesh + '.vtx[*]', query=True, worldSpace=True,"
        " translation=True)\n"
        "_out = []\n"
        "for _f in _frames:\n"
        "    cmds.currentTime(_f)\n"
        "    _cur = cmds.xform(_mesh + '.vtx[*]', query=True,"
        " worldSpace=True, translation=True)\n"
        "    _worst = 0.0\n"
        "    _n = len(_cur) // 3\n"
        "    _cx = _cy = _cz = 0.0\n"
        "    for _i in range(0, len(_cur), 3):\n"
        "        _dx = _cur[_i] - _base[_i]\n"
        "        _dy = _cur[_i + 1] - _base[_i + 1]\n"
        "        _dz = _cur[_i + 2] - _base[_i + 2]\n"
        "        _d = (_dx * _dx + _dy * _dy + _dz * _dz) ** 0.5\n"
        "        if _d > _worst:\n"
        "            _worst = _d\n"
        "        _cx += _cur[_i]\n"
        "        _cy += _cur[_i + 1]\n"
        "        _cz += _cur[_i + 2]\n"
        "    _out.append({'frame': _f, 'max_displacement': round(_worst, 6),"
        " 'centroid': [round(_cx / _n, 6), round(_cy / _n, 6),"
        " round(_cz / _n, 6)]})\n"
        "cmds.currentTime(0)\n"
        "_out"
    ) % {"mesh": "|" + MESH, "frames": frames, "start": start}
    return py(code, tag, timeout_s=600.0)


def worst_centroid_delta(before, after):
    return max(abs(a["centroid"][i] - b["centroid"][i])
              for a, b in zip(before, after) for i in range(3))


def rest_probe(tag, meta, samples, rot_joints, root=None):
    """{frame: {joint: [rx, ry, rz], ...}} at `samples` evenly spaced
    frames inside meta's OWN range, for joints THIS clip does not
    declare - a non-zero reading means a neighbour's motion leaked across
    the boundary. `root` (if given) adds '__root__': the root's local
    translate, for probing root_position leakage into a clip that never
    uses it."""
    start, end = int(meta["start_frame"]), int(meta["end_frame"])
    span = end - start
    frames = sorted({int(round(start + span * i / (samples - 1)))
                     for i in range(samples)})
    root_line = (
        "    _row['__root__'] = [round(v, 6) for v in "
        "cmds.getAttr(%r + '.translate')[0]]\n" % root) if root else ""
    code = (
        "import maya.cmds as cmds\n"
        "_frames = %(frames)r\n"
        "_joints = %(joints)r\n"
        "_out = {}\n"
        "for _f in _frames:\n"
        "    cmds.currentTime(_f)\n"
        "    _row = {_j: [round(v, 6) for v in cmds.getAttr(_j + '.rotate')"
        "[0]] for _j in _joints}\n"
        + root_line +
        "    _out[_f] = _row\n"
        "cmds.currentTime(0)\n"
        "_out"
    ) % {"frames": frames, "joints": rot_joints}
    return py(code, tag)


def worst_rotation(rows, joints):
    return max(abs(v) for row in rows.values() for j in joints for v in row[j])


def worst_root_delta(rows):
    return max(abs(a - b) for row in rows.values()
              for a, b in zip(row["__root__"], PELVIS_REST))


def take_named(anim, name):
    if not anim:
        return None
    for take in anim.get("takes", []):
        if take.get("name") == name:
            return take
    return None


def by_take_target(anim):
    """{(take, target, property): row} from every attributed row - an
    independent rebuild of the lookup export.py's anim_violations/
    anim_clip_facts use internally, built here straight from
    fbxbytes.anim_facts's output rather than imported from export.py."""
    out = {}
    for row in anim["targets"]:
        if row.get("take") is None:
            continue
        out.setdefault((row["take"], row["target"], row["property"]), row)
    return out


def lit_stats(png_bytes):
    """(lit pixel count, mean luminance of those pixels), via the
    histogram - same measurement clip_live.py uses."""
    hist = Image.open(io.BytesIO(png_bytes)).convert("L").histogram()
    lit = sum(hist[LIT_THRESHOLD + 1:])
    total = sum(i * hist[i] for i in range(LIT_THRESHOLD + 1, 256))
    return lit, (total / lit if lit else 0.0)


def save_preview(tag, result, meta):
    """`meta` is the clip's own DECLARED record (from declared_clips/
    final_records, independent of this `result`) - #718 review Fix 4: a
    shared timeline means rendering a NEIGHBOUR's frames is exactly the
    multi-take failure mode, so the frames actually rendered are checked
    against that independent ground truth, not merely counted."""
    saved = 0
    counts = []
    means = []
    for image in result.get("images", []):
        png = base64.b64decode(image["png_b64"])
        path = out("%s_%s.png" % (tag, image["label"].replace("=", "")
                                  .replace(".", "_")))
        with open(path, "wb") as fh:
            fh.write(png)
        saved += 1
        lit, mean = lit_stats(png)
        counts.append(lit)
        means.append(mean)
    check("preview %s rendered %d frames" % (tag, saved), saved >= 4,
          "frames=%s" % [f["frame"] for f in result.get("frames", [])])
    frames = [f["frame"] for f in result.get("frames", [])]
    start, end = int(meta["start_frame"]), int(meta["end_frame"])
    check("preview %s: every rendered frame lies inside %r's own declared "
          "range [%d, %d]" % (tag, meta["name"], start, end),
          bool(frames) and all(start <= f <= end for f in frames),
          "frames=%s range=%d..%d" % (frames, start, end))
    lo, hi = LUMINANCE_BAND
    check("preview %s: every cell shows a lit, shaded figure" % tag,
          bool(counts) and min(counts) >= FIGURE_PIXELS_MIN
          and all(lo <= m <= hi for m in means),
          "lit_px %d..%d (min %d), mean luminance %.1f..%.1f (band %.0f..%.0f)"
          % (min(counts or [0]), max(counts or [0]), FIGURE_PIXELS_MIN,
             min(means or [0]), max(means or [0]), lo, hi))


def main():
    if PORT in (9877, 9879):
        print("refusing to run on %d: this eval discards the open scene "
              "(two-Maya policy). Launch a disposable Maya on 9878." % PORT)
        return 2

    os.makedirs(OUT_DIR, exist_ok=True)
    identity = py("import os\n{'pid': os.getpid()}", "identity")
    print("Maya on %d: pid %s, writing to %s\n"
          % (PORT, identity["pid"], OUT_DIR))

    # ---- 1. humanoid + skeleton + bind (clip_live's scene setup, reused)
    ok("new_scene", {"confirm": True})
    for kind, name, divisions, scale, translate, rotate in PARTS:
        params = {"kind": kind, "name": name, "divisions": divisions,
                  "scale": scale, "translate": translate}
        if rotate:
            params["rotate"] = rotate
        ok("create_primitive", params)
    ok("combine", {"names": [p[1] for p in PARTS], "name": MESH})
    py("import maya.cmds as cmds\n"
       "cmds.makeIdentity(%r, apply=True, translate=False, rotate=True, "
       "scale=True, normal=0, preserveNormals=True)\nTrue"
       % ("|" + MESH), "freeze the combined mesh")
    skeleton = ok("create_skeleton", {"joints": JOINTS})
    root = skeleton["root"]
    bind = ok("bind_skin", {"mesh": "|" + MESH, "root": root},
              timeout_s=600.0)
    check("the bind leaves NO vertex unowned",
          bind["unweighted_vertices"] == 0,
          "unweighted=%d" % bind["unweighted_vertices"])
    ok("setup_lighting", {"preset": "three_point"})

    # ---- 2. author idle, wave, step in that order
    idle = ok("author_clip", {"root": root, "name": "idle", "fps": IDLE_FPS,
                              "interpolation": "smooth", "loop": True,
                              "keys": IDLE_KEYS})
    check("idle: duration and frames measured back",
          abs(idle["duration_s"] - 2.0) < 1e-6 and idle["frames"] == 61,
          "duration=%.3f frames=%d" % (idle["duration_s"], idle["frames"]))
    check("idle: only spine/chest keyed, starts at frame 0",
          idle["keyed_joints"] == 2 and idle["start_frame"] == 0,
          "keyed_joints=%d start=%d" % (idle["keyed_joints"],
                                        idle["start_frame"]))
    # IDLE_KEYS' shape is base -> sway -> base -> small sway -> base (loop
    # close on the -3 degree cycle base, not on the skeleton's true rest -
    # #718 review Fix 2): keys 2 and 4 are LEGITIMATELY back at the
    # frame-0 baseline (no blend weight rides along to keep them apart,
    # unlike clip_live's idle), so only keys 1 and 3 are asserted nonzero;
    # 2 and 4 are asserted near-zero on purpose - that near-zero IS the
    # measured return to the cycle's OWN base pose / loop closure (this is
    # a displacement measured relative to key 0, not an absolute value -
    # it reads near-zero however far key 0 itself sits from true rest).
    moved = [k["max_displacement"] for k in idle["per_key"]]
    check("idle: the sway keys measured real motion, the base-pose keys "
          "measured a return to the cycle's own base",
          moved[0] == 0.0 and moved[1] > 0.01 and moved[2] < 1e-3
          and moved[3] > 0.001 and moved[4] < 1e-3,
          json.dumps([round(m, 4) for m in moved]))

    wave = ok("author_clip", {"root": root, "name": "wave", "fps": WAVE_FPS,
                              "interpolation": "smooth", "loop": False,
                              "keys": WAVE_KEYS})
    check("wave appends after idle with the 1-frame gap",
          wave["replaced"] is None and wave["clips"] == ["idle", "wave"]
          and wave["start_frame"] == idle["end_frame"] + clipmath.GAP_FRAMES + 1,
          "start=%d idle_end=%d" % (wave["start_frame"], idle["end_frame"]))
    moved = [k["max_displacement"] for k in wave["per_key"]]
    check("wave: every interior key measured real motion",
          moved[0] == 0.0 and all(m > 0.005 for m in moved[1:]),
          json.dumps([round(m, 4) for m in moved]))

    # BEFORE step exists: idle's own motion, measured independently.
    probe_before = probe_displacement(
        "idle displacement BEFORE step exists", idle)

    step = ok("author_clip", {"root": root, "name": "step", "fps": STEP_FPS,
                              "interpolation": "smooth", "loop": True,
                              "keys": STEP_KEYS})
    check("step appends after wave with the 1-frame gap, root keyed",
          step["replaced"] is None and step["clips"] == ["idle", "wave", "step"]
          and step["start_frame"] == wave["end_frame"] + clipmath.GAP_FRAMES + 1
          and step["root_position_keyed"] is True,
          "start=%d wave_end=%d root_keyed=%s"
          % (step["start_frame"], wave["end_frame"],
             step["root_position_keyed"]))
    moved = [k["max_displacement"] for k in step["per_key"]]
    check("step: every interior key measured real motion",
          all(m > 0.05 for m in moved[1:-1]),
          json.dumps([round(m, 4) for m in moved]))
    check("step: the loop measurably closes (last key ~= first)",
          moved[-1] < 1e-3, "closure=%.5f" % moved[-1])

    # ---- check 1: the three ranges are contiguous-with-a-gap, disjoint
    check_layout("initial authoring order", declared_clips(root),
                require_exact_gap=True)

    # ---- check 3 (backwards half): idle's motion AFTER step introduces
    # root_position, compared to the independent measurement taken above
    # before step existed at all.
    probe_after = probe_displacement(
        "idle displacement AFTER step exists (root_position introduced)",
        idle)
    # Liveness only - see probe_displacement's docstring (#718 review Fix
    # 1): a constant offset (exactly what a missing backward pin would
    # leave across idle's whole range) cancels out of a per-frame
    # difference against idle's OWN first frame, so this check reads
    # identical whether or not the backward pin ran. It still catches a
    # measurement-plumbing regression (e.g. probe_displacement itself
    # breaking), which is why it stays, just not labelled as the
    # contamination proof.
    check("authoring 'step' left idle's relative motion identical "
          "(liveness check, not the contamination proof - see the next "
          "check)",
          len(probe_before) == len(probe_after)
          and all(abs(a["max_displacement"] - b["max_displacement"]) < 1e-6
                  for a, b in zip(probe_before, probe_after)),
          "before=%s after=%s"
          % ([f["max_displacement"] for f in probe_before],
             [f["max_displacement"] for f in probe_after]))
    # THE backward-contamination proof (#718 review Fix 1): centroid is an
    # ABSOLUTE quantity, so a constant offset does not cancel here the way
    # it does above. If the backward pin were skipped or scoped wrong, the
    # pelvis translateY curve would hold step's first key (0.97, vs the
    # 1.00 build-rest PELVIS_REST) backward across idle's whole range - a
    # uniform (0, -0.03, 0) shift on every frame's centroid. See the t718
    # report for the arithmetic proof (against these exact measured
    # centroid values) that this check would fail under that regression,
    # where max_displacement above would not.
    centroid_delta = worst_centroid_delta(probe_before, probe_after)
    check("authoring 'step' left idle's ABSOLUTE mesh position identical "
          "(the backward-contamination guard)",
          len(probe_before) == len(probe_after) and centroid_delta < 1e-6,
          "worst_centroid_delta=%.6g before[0]=%s after[0]=%s"
          % (centroid_delta, probe_before[0]["centroid"],
             probe_after[0]["centroid"]))

    # ---- check 3 (forwards half) + bonus coverage: every OTHER clip's
    # foreign channels sit at rest inside each clip's own range.
    rows = rest_probe("forward: idle's joints during wave's range",
                      wave, 3, IDLE_JOINTS)
    check("wave's range: idle's undeclared joints (spine/chest) sit at rest",
          worst_rotation(rows, IDLE_JOINTS) < REST_ROT_TOL,
          "worst=%.6g" % worst_rotation(rows, IDLE_JOINTS))

    rows = rest_probe("forward: wave/step joints+root during idle's range",
                      idle, 3, WAVE_JOINTS + STEP_JOINTS, root=root)
    check("idle's range: wave's and step's undeclared joints sit at rest, "
          "root_position sits at its build position",
          worst_rotation(rows, WAVE_JOINTS + STEP_JOINTS) < REST_ROT_TOL
          and worst_root_delta(rows) < REST_POS_TOL,
          "worst_rot=%.6g worst_root=%.6g"
          % (worst_rotation(rows, WAVE_JOINTS + STEP_JOINTS),
             worst_root_delta(rows)))

    rows = rest_probe("forward: idle/wave joints during step's range",
                      step, 3, IDLE_JOINTS + WAVE_JOINTS)
    check("step's range: idle's and wave's undeclared joints sit at rest",
          worst_rotation(rows, IDLE_JOINTS + WAVE_JOINTS) < REST_ROT_TOL,
          "worst=%.6g" % worst_rotation(rows, IDLE_JOINTS + WAVE_JOINTS))

    # ---- check 2: re-authoring the MIDDLE clip moves it to the tail and
    # leaves idle's and step's own keys byte-identical, measured by
    # reading key times and values back independently.
    idle_before = capture_keys("idle keys before wave moves", IDLE_JOINTS,
                               idle)
    step_before = capture_keys("step keys before wave moves", STEP_JOINTS,
                               step, root=root)
    wave2 = ok("author_clip", {"root": root, "name": "wave",
                               "fps": WAVE_FPS, "interpolation": "smooth",
                               "loop": False, "keys": WAVE_KEYS})
    check("re-authoring 'wave' moved it to the tail, after 'step'",
          wave2["replaced"] == "wave"
          and wave2["clips"] == ["idle", "step", "wave"]
          and wave2["start_frame"] == step["end_frame"] + clipmath.GAP_FRAMES + 1,
          "start=%d step_end=%d clips=%s"
          % (wave2["start_frame"], step["end_frame"], wave2["clips"]))
    idle_after = capture_keys("idle keys after wave moved", IDLE_JOINTS, idle)
    step_after = capture_keys("step keys after wave moved", STEP_JOINTS,
                              step, root=root)
    check("re-authoring the middle clip left idle's own keys byte-identical",
          idle_before == idle_after,
          "%d plugs compared" % len(idle_before))
    check("re-authoring the middle clip left step's own keys byte-identical",
          step_before == step_after,
          "%d plugs compared" % len(step_before))

    # ---- check 4: delete_clip removes exactly one clip and leaves the
    # others measurable (their own keys still byte-identical).
    #
    # deleted_curves is NOT asserted >0 here: measured directly (see the
    # t718-12 report), wave's own R_shoulder/R_elbow curves also carry
    # BACKWARD rest-pin keys at idle's and step's boundary frames (#718's
    # own backward-contamination guard, working exactly as designed), so
    # cutting wave's own [start_frame, end_frame] range leaves those curve
    # NODES alive with 2 residual keys apiece - deleted_curves counts fully
    #-vanished curve nodes, so it reads 0 on a rig built exactly this way,
    # correctly. What actually proves the deletion is that wave's own
    # range is empty afterwards - checked directly below.
    gone = ok("delete_clip", {"root": root, "name": "wave"})
    wave_range_empty = py(
        "import maya.cmds as cmds\n"
        "_plugs = %r\n"
        "any(cmds.keyframe(_p, query=True, time=(%d, %d)) for _p in _plugs)"
        % (["%s.rotate%s" % (j, axis) for j in WAVE_JOINTS for axis in "XYZ"],
           wave2["start_frame"], wave2["end_frame"]),
        "wave's own range after delete_clip")
    check("delete_clip(name='wave') removes exactly one clip, and wave's "
          "own frame range now carries zero keys",
          gone["clips"] == ["idle", "step"] and wave_range_empty is False,
          "clips=%s deleted_curves=%s wave_range_has_keys=%s"
          % (gone["clips"], gone["deleted_curves"], wave_range_empty))
    idle_deleted = capture_keys("idle keys after delete_clip('wave')",
                                IDLE_JOINTS, idle)
    step_deleted = capture_keys("step keys after delete_clip('wave')",
                                STEP_JOINTS, step, root=root)
    check("delete_clip left idle's and step's own keys byte-identical, "
          "still measurable",
          idle_deleted == idle_after and step_deleted == step_after,
          "idle_match=%s step_match=%s"
          % (idle_deleted == idle_after, step_deleted == step_after))

    # Restore all three clips for the export/preview phase below.
    wave3 = ok("author_clip", {"root": root, "name": "wave",
                               "fps": WAVE_FPS, "interpolation": "smooth",
                               "loop": False, "keys": WAVE_KEYS})
    check("re-authored 'wave' lands back at the same tail position",
          wave3["clips"] == ["idle", "step", "wave"]
          and wave3["start_frame"] == step["end_frame"] + clipmath.GAP_FRAMES + 1,
          "start=%d clips=%s" % (wave3["start_frame"], wave3["clips"]))
    final_records = declared_clips(root)
    records_by_name = {r["name"]: r for r in final_records}
    # Not require_exact_gap: idle and step's own ranges are unchanged, but
    # the space between them where 'wave' used to sit (before check 2
    # moved it to the tail) is a hole, by design (#718 decision 5) - see
    # check_layout's docstring.
    check_layout("final rebuilt layout", final_records,
                require_exact_gap=False)

    # #718 review Fix 2: the one contamination direction never probed
    # numerically before this fix - step's FORWARD hold. step's own last
    # key equals its first (the loop close), which is the hips/legs'
    # active pose, NOT rest - so a curve holding it forward in time past
    # step's own range is a value that visibly differs from rest, unlike
    # the (pre-fix) trivially-rest idle/wave boundaries this same
    # direction would otherwise have exercised. In the final layout 'wave'
    # sits right after 'step', which is what makes this checkable now.
    rows = rest_probe("forward: step's joints+root during wave's range",
                      records_by_name["wave"], 3, STEP_JOINTS, root=root)
    check("wave's range: step's undeclared joints and root_position sit "
          "at rest (step's non-rest loop-close pose does not hold forward)",
          worst_rotation(rows, STEP_JOINTS) < REST_ROT_TOL
          and worst_root_delta(rows) < REST_POS_TOL,
          "worst_rot=%.6g worst_root=%.6g"
          % (worst_rotation(rows, STEP_JOINTS), worst_root_delta(rows)))

    # ---- check 5 (part 1): export, three named takes with the right span
    fbx_path = out("multi_take.fbx")
    if os.path.exists(fbx_path):
        os.unlink(fbx_path)
    result = ok("export_fbx", {"path": fbx_path.replace("\\", "/"),
                               "metres_per_unit": 1.0,
                               "include_skins": True,
                               "include_animation": True}, timeout_s=900.0)
    check("export: skins travel alongside the three takes",
          result["skin"]["deformers"] == 1
          and result["skin"]["clusters"] == JOINT_COUNT,
          json.dumps(result["skin"]))
    anim = result["animation"]
    for name in ("idle", "step", "wave"):
        record = records_by_name[name]
        take = take_named(anim, name)
        fps = float(record["fps"])
        want_start = record["start_frame"] / fps
        want_stop = record["end_frame"] / fps
        # Half a frame, not a whole one - export.py's anim_violations uses
        # the same tolerance for the same reason (see its comment): clears
        # tick/second round-trip noise by ~15 orders of magnitude while
        # still catching a whole-frame boundary slip, which matters here
        # because clips sit only GAP_FRAMES+1 frames apart.
        tol = 0.5 / fps
        check("export: a take named %r spans the right frames" % name,
              take is not None
              and abs(take["start_s"] - want_start) <= tol
              and abs(take["stop_s"] - want_stop) <= tol,
              "take=%s want=%.4f..%.4f" % (take, want_start, want_stop))

    # ---- check 5 (part 2, the added coverage requirement): EVERY channel
    # of EVERY declared take, at the byte level - not a two-channel spot
    # check, and not even a per-take-own-joints check.
    #
    # #718 review Fix 3: the self-contained rule means every take carries
    # EVERY channel the rig touches (author_clip pins each clip's channels
    # it does not declare at its own boundary), so the requirement this
    # gate is meant to corroborate is "every joint of the UNION, in every
    # take" - matching export.py's own internal gate
    # (clipmath.channel_union(...)), not "each take's own declared
    # joints" (which only re-checks the same 11 rows the take-span check
    # above already touched indirectly, and would miss a regression that
    # drops one joint's PINNED rows from a take that never declared that
    # joint itself).
    union = clipmath.channel_union(final_records)
    btt = by_take_target(anim)
    coverage_failures = []
    channels_checked = 0
    for record in final_records:
        expected = record["end_frame"] - record["start_frame"] + 1
        for joint in union["joints"]:
            channels_checked += 1
            entry = btt.get((record["name"], joint, "Lcl Rotation"))
            if entry is None:
                coverage_failures.append(
                    "%s/%s: no rotation curve attributed to this take"
                    % (record["name"], joint))
            elif entry["curves"] != 3 or entry["key_count"] != expected:
                coverage_failures.append(
                    "%s/%s: curves=%s key_count=%s (want 3/%d)"
                    % (record["name"], joint, entry["curves"],
                       entry["key_count"], expected))
        if union["root_position_used"]:
            channels_checked += 1
            entry = btt.get((record["name"], "pelvis", "Lcl Translation"))
            if entry is None:
                coverage_failures.append(
                    "%s/pelvis: no root translation curve attributed to "
                    "this take" % record["name"])
            elif entry["curves"] != 3 or entry["key_count"] != expected:
                coverage_failures.append(
                    "%s/pelvis: curves=%s key_count=%s (want 3/%d)"
                    % (record["name"], entry["curves"], entry["key_count"],
                       expected))
    check("every channel of the RIG (%d joints%s) carries correct curves "
          "in every declared take, at the byte level (%d channels checked "
          "across %d takes)"
          % (len(union["joints"]),
             " + root" if union["root_position_used"] else "",
             channels_checked, len(final_records)),
          channels_checked > 0 and not coverage_failures,
          "; ".join(coverage_failures[:6]) or "all channels agree")

    facts = fbxbytes.read_fbx(fbx_path)
    check("an independent byte read agrees with the tool",
          fbxbytes.anim_facts(facts)
          == {k: v for k, v in anim.items() if k != "clips"})

    # ---- check 5 (part 3): previews, judged
    # "side", not "front": idle's rotation axis is a fore/aft pitch (see
    # IDLE_KEYS' comment) - a front camera looks straight down that axis
    # and shows almost no motion at all.
    preview = ok("preview_clip", {"root": root, "name": "idle",
                                  "angle": "side",
                                  "resolution": PREVIEW_RESOLUTION,
                                  "zoom": IDLE_ZOOM}, timeout_s=900.0)
    save_preview("idle", preview, records_by_name["idle"])
    preview = ok("preview_clip", {"root": root, "name": "wave",
                                  "angle": "front",
                                  "resolution": PREVIEW_RESOLUTION,
                                  "zoom": WAVE_ZOOM}, timeout_s=900.0)
    save_preview("wave", preview, records_by_name["wave"])
    preview = ok("preview_clip", {"root": root, "name": "step",
                                  "angle": "side",
                                  "resolution": PREVIEW_RESOLUTION,
                                  "zoom": STEP_ZOOM}, timeout_s=900.0)
    save_preview("step", preview, records_by_name["step"])

    with open(out("baseline.json"), "w") as fh:
        json.dump({
            "fbx": "multi_take.fbx",
            "clips": [
                {"name": r["name"], "fps": r["fps"],
                 "start_frame": r["start_frame"], "end_frame": r["end_frame"],
                 "joints": r["joints"],
                 "root_position_used": r.get("root_position_used", False)}
                for r in sorted(final_records, key=lambda r: r["start_frame"])
            ],
        }, fh, indent=2, sort_keys=True)
    print("  baseline: %s" % out("baseline.json"))

    print("\n" + "=" * 72)
    print("JUDGE the preview frames in %s:" % OUT_DIR)
    print("  idle_*: spine/chest sway visibly; the arm and legs must NOT")
    print("  move at all across the sheet.")
    print("  wave_*: the R arm visibly raises/waves; the spine and legs")
    print("  must NOT move at all across the sheet.")
    print("  step_*: legs/hips stride and the body bobs; the spine and R")
    print("  arm must NOT move at all across the sheet.")
    print("  A sheet where the 'wrong' body part moves is a contamination")
    print("  FAIL even with every number above green.")
    print("=" * 72 + "\n")

    failed = [label for passed, label in CHECKS if not passed]
    print("\n%d/%d passed" % (len(CHECKS) - len(failed), len(CHECKS)))
    for label in failed:
        print("  FAILED: %s" % label)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
