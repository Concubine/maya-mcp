"""#774 acceptance gate: a mocap file's motion, baked through HumanIK onto a
real `create_skeleton` biped, measured - not eyeballed.

Two CMU fixtures (`evals/mocap_fixtures/cmu_walk.bvh`, 317f@120fps;
`cmu_idle.bvh`, 1368f@120fps, trimmed to its first `IDLE_TRIM_END` source
rows to keep bake time down) go onto ONE well-proportioned biped ("rig A",
`humanoid_live.JOINTS` verbatim) as two named takes on the same rig - legal
per #718. That rig, still carrying both clips, is then put through the
composition path (multi-take `export_fbx`, `preview_clip`) BEFORE a second,
deliberately mis-proportioned biped ("rig B", legs `LEG_STRETCH` times
longer - `stretch_legs`) is built in a fresh scene: `new_scene` discards
whatever is open, so rig A's composition/preview steps run first, while it
is still alive, and the docstring order below (composition before
discrimination) reflects that constraint, not the task brief's own listing
order.

The two DISCRIMINATION checks (the brief's steps 4-5) are the actual proof
this gate exists to make, and they are asserted unconditionally, in every
mode:

  (a) retargeting the SAME walk onto the mis-proportioned rig B measures
      MORE independent ankle-contact slide, pre-cleanup, than the
      well-proportioned rig A did.
  (b) `clean_clip`'s `lock_contacts` pass measurably REDUCES rig B's slide
      (its own before/after, both printed).

`CONTACT_JOINTS` (`L_ankle`/`R_ankle`) matches `clean_clip`'s own default
contact-joint resolution (`mocapmath.SKELETON_HIK_MAP`'s two Foot slots), so
every slide number in this gate - rig A's, rig B's before/after, and the
per-metric tolerances below - is the same measurement clean_clip itself
acts on.

TOLERANCES starts at None (measurement mode, the #768/#773 convention):
every number is printed, and the two discriminations above are still
asserted (they are structural correctness, not a threshold chosen by
measurement), but the per-metric slide bounds on rig A are not. After a
real run, TOLERANCES is set from rig A's (and, for walk, rig B's) measured
slide - see the comment above TOLERANCES for the derivation of each of the
two metrics, which are NOT both the same rule: `idle_slide` is the
mechanical "2x measured, round up 1 sig fig, floor 0.01" rule; `walk_slide`
departs from that rule on purpose, because the mechanical value here would
sit ABOVE the mis-proportioned rig B's own bad measurement and so could
not discriminate anything - `walk_slide` is instead set strictly between
rig A's good value and rig B's bad one, making the absolute tolerance
itself a measured discriminator, not just the two unconditional checks
above. The gate is re-run after setting TOLERANCES to confirm it now
asserts everything and still exits 0.

Every check() call accumulates into FAILURES rather than stopping the run;
only ok() aborts early, and only on a hard call failure (a refused or
crashed command) - so a run always exercises every check before deciding
pass/fail, and exits non-zero at the end if any check failed (the
array_deform_live/curve_form_live convention).

The #718 composition byte-gate is reused from `evals/multi_take_live.py`
(Task 12): `declared_clips` (read `mcp_clip` straight off the rig) and the
independent `fbxbytes.read_fbx`/`anim_facts` re-read are copied verbatim in
spirit (adapted here since this rig carries no mesh - retarget_clip needs a
skeleton only, so there is no `combine`/`bind_skin` scene-build phase).
`retarget_clip`'s own registered clip records carry an EMPTY declared
`joints` list (`clip.register_clip`'s documented default for a baked clip -
"the whole rig is baked, not authored key by key"), so multi_take_live's
per-declared-joint channel-union check is vacuous here (the union is
empty). This gate checks the thing that actually matters for a baked clip
instead: every one of the 15 HIK-characterized joints
(`mocapmath.SKELETON_HIK_MAP`'s values) carries a correct 3-curve rotation
record, with the right key count for ITS OWN take, in both takes.

Usage:

    set MAYA_MCP_PORT=9878
    set MAYA_MCP_EXPECT_PID=<the pid you launched>
    python evals/retarget_live.py

MUTATES THE ANSWERING MAYA'S CURRENT SCENE (new_scene, twice).
MAYA_MCP_EXPECT_PID is REQUIRED: a port is not an identity (#648), and this
gate discards the open scene more than once.

Artifacts: evals/retarget_live/walk_sheet.png, retarget_multi_take.fbx
Exit: 0 pass, 1 fail or preflight refused, 2 no connection.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from humanoid_live import JOINTS, MESH, PARTS  # noqa: E402
from live_call import call, structured_result  # noqa: E402
from maya_mcp import images  # noqa: E402
from maya_plugin.handlers import fbxbytes, mocapmath  # noqa: E402
from maya_plugin.handlers.clip import CLIP_ATTR  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
OUT_DIR = os.path.join(_HERE, "retarget_live")
FIXTURES = os.path.join(_HERE, "mocap_fixtures")
WALK_BVH = os.path.join(FIXTURES, "cmu_walk.bvh").replace("\\", "/")
IDLE_BVH = os.path.join(FIXTURES, "cmu_idle.bvh").replace("\\", "/")
WALK_SOURCE_LAST_ROW = 316  # cmu_walk.bvh: 317 rows, 0-indexed
# cmu_idle.bvh is 1368f@120fps - trimmed to its first 300 source rows (2.5s)
# to keep the bake fast; the trim is source ROW indices (retarget_clip's
# start/end), not baked frames.
IDLE_TRIM_END = 300
# MEASURED (this gate's first run, cmu_walk.bvh): source row 0 is a
# calibration/reference pose, not the first frame of the actual capture - a
# per-frame diagnostic showed EVERY joint's peak_speed/max_accel landing on
# the row0->row1 transition (up to ~25 m/s on a walk whose real per-frame
# speeds run 0.1-1 m/s), which disabled measure_clip's own contact
# detection entirely: row 0 becomes the WHOLE clip's floor_y (its own
# trajectory minimum), so `contact_runs`' "near its own floor" window
# (#773) only ever matches the one frame that is ALSO moving fastest - zero
# contact runs on a real, cleanly-planted walk. Retargeting from source row
# 1 instead removes the pop entirely (verified: the same walk then measures
# 33/158 and 20/158 genuinely slow, near-floor L_ankle/R_ankle frames) and
# is exactly what `start` exists for - trimming a known-bad calibration
# frame out of a source capture, not a workaround for anything
# retarget_clip itself gets wrong. Applied to both fixtures as a precaution
# (idle's own row 0 was not separately diagnosed) - see the report for what
# idle actually measured.
SOURCE_ROW_START = 1

LEG_STRETCH = 1.5  # biped B's discrimination proportion (brief step 4)
# clean_clip's own default contact-joint resolution (mocapmath.
# SKELETON_HIK_MAP's two Foot slots) - every slide number in this gate uses
# the SAME two joints clean_clip itself acts on.
CONTACT_JOINTS = ["L_ankle", "R_ankle"]

FAILURES = []

# Measured on a real Maya (2026-08-28, agent Maya pid 86348, port 9878),
# after SOURCE_ROW_START's row-0 fix (see its comment - without it, contact
# detection never fires on either rig and every slide number below reads
# 0.0, discriminating nothing):
#   rig A (good proportions) walk worst ankle slide = 0.05001  (L_ankle 0.04451, R_ankle 0.05001)
#   rig B (legs 1.5x, bad)   walk worst ankle slide  = 0.06854  (pre-clean)
#   rig A idle worst ankle slide = 0.00400  (L_ankle 0.00400, R_ankle 0.00367)
#
# idle_slide: the brief's mechanical "2x measured, round up 1 sig fig,
# floor 0.01" rule applied cleanly (2*0.00400=0.00800, below the floor ->
# 0.01) - idle has no bad-rig counterpart measured here, so this is a
# sanity ceiling, not a discriminator.
#
# walk_slide: the SAME mechanical rule gives 2*0.05001=0.10002 -> 0.2,
# which sits ABOVE rig B's own bad measurement (0.06854) - a value that
# cannot discriminate anything, since a regression proportional across
# both rigs would still clear it. Per controller ruling (supersedes the
# brief's formula here, which decade-rounds past the one number that
# matters): walk_slide is instead set BETWEEN the two measured values -
# strictly below rig B's bad 0.06854, comfortably above rig A's good
# 0.05001 - so the absolute tolerance itself is a measured discriminator,
# not just the two unconditional discrimination checks below:
#   walk_slide = 0.06   (0.05001 <= 0.06  -> rig A PASSES)
#                        (0.06854 >  0.06 -> rig B's bad pre-clean value
#                         would FAIL this same tolerance, printed for
#                         illustration in [7] but never asserted against
#                         rig B - rig B exists to be cleaned up, not to
#                         pass the good-rig ceiling)
TOLERANCES = {
    "walk_slide": 0.06,
    "idle_slide": 0.01,
}


def send(command, params, timeout_s=300.0):
    try:
        return call(command, params, timeout_s=timeout_s, port=PORT)
    except (ConnectionRefusedError, OSError) as exc:
        print("could not reach a Maya plugin on %s: %s" % (PORT, exc))
        sys.exit(2)


def ok(command, params, timeout_s=300.0, what=None):
    resp = send(command, params, timeout_s)
    if resp.get("status") != "ok":
        print("FAILED %s: %s" % (what or command,
                                 json.dumps(resp.get("error", resp))[:600]))
        sys.exit(1)
    return resp.get("result") or {}


def check(condition, message):
    print(("  PASS  " if condition else "  FAIL  ") + message)
    if not condition:
        FAILURES.append(message)
    return condition


def py(code, what, timeout_s=300.0):
    return structured_result(ok("execute_python", {"code": code}, timeout_s,
                                what), what)


def preflight():
    expect = (os.environ.get("MAYA_MCP_EXPECT_PID") or "").strip()
    if not expect:
        raise SystemExit(
            "MAYA_MCP_EXPECT_PID is not set. This gate discards the "
            "answering Maya's scene (new_scene, twice) - launch one "
            "yourself and name its pid (#648). Refusing to guess which "
            "Maya is disposable.")
    ping = ok("ping", {}, 10.0, "ping")
    process = ping.get("process") or {}
    print("answering Maya: pid %s, scene %r" % (process.get("pid"),
                                                 process.get("scene")))
    return ping


def round_up_1sig(x, floor=0.01):
    """2x-and-round-up-to-1-sig-fig, the #768/#773 tolerance method."""
    if x <= 0:
        return floor
    exp = math.floor(math.log10(x))
    scaled = x / (10 ** exp)
    rounded = math.ceil(scaled - 1e-9)
    if rounded >= 10:
        rounded, exp = 1, exp + 1
    return max(rounded * (10 ** exp), floor)


def stretch_legs(joints, factor):
    """`joints`, with each leg's hip->knee->ankle segments stretched by
    `factor` below an UNCHANGED hip position - so the only thing that
    differs from `joints` is leg PROPORTION, not the pelvis height
    retarget_clip's own scale derivation reads (`target_hips_height`, the
    pelvis joint's own world Y) nor anything above the hip. The foot
    (ankle->toe) is carried along by the same absolute offset as the
    original, keeping the foot's own shape intact - only the leg above it
    gets longer.

    Contact detection (`motionmath.contact_runs`) floors against each
    joint's OWN minimum Y across the clip, not an absolute ground plane, so
    the resulting negative ankle/toe Y values (the joint now sits below
    where `joints`' hip was) do not themselves break plant detection.
    """
    orig = {j["name"]: list(j["position"]) for j in joints}
    stretched_y = {}
    for side in ("L", "R"):
        hip_y = orig["%s_hip" % side][1]
        knee_y = orig["%s_knee" % side][1]
        ankle_y = orig["%s_ankle" % side][1]
        toe_y = orig["%s_toe" % side][1]
        new_knee_y = hip_y - (hip_y - knee_y) * factor
        new_ankle_y = new_knee_y - (knee_y - ankle_y) * factor
        new_toe_y = new_ankle_y - (ankle_y - toe_y)
        stretched_y["%s_knee" % side] = new_knee_y
        stretched_y["%s_ankle" % side] = new_ankle_y
        stretched_y["%s_toe" % side] = new_toe_y
    out = []
    for j in joints:
        nj = dict(j)
        pos = list(j["position"])
        if j["name"] in stretched_y:
            pos[1] = stretched_y[j["name"]]
        nj["position"] = pos
        out.append(nj)
    return out


def build_rig(joints, tag):
    skeleton = ok("create_skeleton", {"joints": joints}, 60.0,
                 "create_skeleton %s" % tag)
    check(len(skeleton["joints"]) == len(joints),
         "%s: skeleton built all %d joints" % (tag, len(joints)))
    return skeleton["root"]


def build_mesh():
    """`humanoid_live.PARTS`, combined and frozen - reused verbatim (the
    same body `humanoid_live.py`/`multi_take_live.py` build) so rig A has
    something for `preview_clip` to render: a bare skeleton moves nothing
    ("this skeleton moves no mesh... bare joints render nothing", measured
    directly - see the report), and this gate wants to SEE the retargeted
    walk, not just measure it. Rig B (discrimination only, never previewed)
    skips this entirely to keep its build fast."""
    for kind, name, divisions, scale, translate, rotate in PARTS:
        params = {"kind": kind, "name": name, "divisions": divisions,
                 "scale": scale, "translate": translate}
        if rotate:
            params["rotate"] = rotate
        ok("create_primitive", params, 60.0, "create_primitive %s" % name)
    ok("combine", {"names": [p[1] for p in PARTS], "name": MESH}, 60.0,
      "combine humanoid parts")
    py("import maya.cmds as cmds\n"
      "cmds.makeIdentity(%r, apply=True, translate=False, rotate=True, "
      "scale=True, normal=0, preserveNormals=True)\nTrue" % ("|" + MESH),
      "freeze the combined mesh")


def independent_measure(root, clip_name, contact_joints=None, what=""):
    """A measure_clip call this gate makes itself, separate from whatever
    the producing tool (retarget_clip/clean_clip) already self-reported -
    the brief's "assert on an INDEPENDENT measure_clip call, not only the
    self-report" requirement."""
    params = {"root": root, "name": clip_name}
    if contact_joints is not None:
        params["contact_joints"] = contact_joints
    return ok("measure_clip", params, 60.0,
             "measure_clip %s (%s)" % (clip_name, what))


def ankle_slide(measured):
    contacts = measured.get("contacts", {})
    return {j: contacts[j]["max_slide"] for j in CONTACT_JOINTS
           if j in contacts}


def worst(slide_by_joint):
    return max(slide_by_joint.values()) if slide_by_joint else 0.0


def declared_clips(root):
    """The rig's declared clip records, read straight off the mcp_clip
    attribute - the same source export.py's own `_scene_clips` reads.
    Reused from evals/multi_take_live.py's `declared_clips` (#718 Task 12),
    called here via `py()` directly since this rig carries no mesh to route
    an execute_python call through anything else."""
    return py(
        "import maya.cmds as cmds\nimport json\n"
        "json.loads(cmds.getAttr(%r))" % ("%s.%s" % (root, CLIP_ATTR)),
        "declared clips")


def main():
    preflight()
    os.makedirs(OUT_DIR, exist_ok=True)

    # ---- 1. rig A (well-proportioned): retarget the walk -----------------
    ok("new_scene", {"confirm": True}, 180.0, "new_scene (rig A)")
    build_mesh()
    root_a = build_rig(JOINTS, "rig A")
    bind = ok("bind_skin", {"mesh": "|" + MESH, "root": root_a}, 600.0,
             "bind_skin rig A")
    check(bind.get("unweighted_vertices", 1) == 0,
         "rig A: bind_skin leaves no vertex unweighted (unweighted=%s)"
         % bind.get("unweighted_vertices"))
    ok("setup_lighting", {"preset": "three_point"}, 60.0,
      "setup_lighting rig A")

    print("\n[1] retarget_clip: cmu_walk.bvh[%d:%d] -> rig A, clip 'walk'"
         % (SOURCE_ROW_START, WALK_SOURCE_LAST_ROW))
    walk = ok("retarget_clip", {"file": WALK_BVH, "root": root_a,
                                "clip": "walk", "start": SOURCE_ROW_START,
                                "end": WALK_SOURCE_LAST_ROW}, 300.0,
             "retarget_clip walk (rig A)")
    print("  self-report: frames=%d fps=%d source_joints=%d"
         % (walk["frames"], walk["fps"], walk["source_joints"]))
    for k, v in sorted(walk["measures"].items()):
        if k in ("joints", "contacts"):
            print("  self-report measures.%s: %s" % (k, json.dumps(v)))
        else:
            print("  self-report measures.%s = %r" % (k, v))
    for w in walk.get("warnings", []):
        print("  warning: %s" % w)

    # Independent re-measurement with the SAME params retarget_clip used
    # internally (no contact_joints override) - "may check they agree".
    walk_agree = independent_measure(root_a, "walk", what="agreement check")
    agree_keys = ("frames_sampled", "rig_height", "fps", "loop")
    check(all(walk_agree.get(k) == walk["measures"].get(k)
             for k in agree_keys),
         "walk: an independent measure_clip call agrees with retarget's "
         "self-report on %s (independent=%s, self-report=%s)"
         % (agree_keys, {k: walk_agree.get(k) for k in agree_keys},
            {k: walk["measures"].get(k) for k in agree_keys}))

    # The ankle-scoped measurement used for tolerances/discrimination below.
    walk_a_ankles = independent_measure(root_a, "walk", CONTACT_JOINTS,
                                        "ankle slide, rig A")
    slide_a_walk = ankle_slide(walk_a_ankles)
    print("  rig A walk independent ankle slide: %s (worst=%.5f) contacts=%s"
         % ({k: round(v, 5) for k, v in slide_a_walk.items()},
            worst(slide_a_walk), json.dumps(walk_a_ankles.get("contacts"))))

    # ---- 2. rig A: a second take (idle, trimmed), same rig (#718 legal) --
    print("\n[2] retarget_clip: cmu_idle.bvh[%d:%d] -> rig A, clip 'idle' "
         "(second take, same rig)" % (SOURCE_ROW_START, IDLE_TRIM_END))
    idle = ok("retarget_clip", {"file": IDLE_BVH, "root": root_a,
                                "clip": "idle", "start": SOURCE_ROW_START,
                                "end": IDLE_TRIM_END}, 300.0,
             "retarget_clip idle (rig A)")
    print("  self-report: frames=%d fps=%d source_joints=%d"
         % (idle["frames"], idle["fps"], idle["source_joints"]))
    for w in idle.get("warnings", []):
        print("  warning: %s" % w)
    check(idle["fps"] == walk["fps"],
         "walk and idle baked at the same fps on one rig (%d vs %d)"
         % (walk["fps"], idle["fps"]))

    idle_a_ankles = independent_measure(root_a, "idle", CONTACT_JOINTS,
                                        "ankle slide, rig A idle")
    slide_a_idle = ankle_slide(idle_a_ankles)
    print("  rig A idle independent ankle slide: %s (worst=%.5f) contacts=%s"
         % ({k: round(v, 5) for k, v in slide_a_idle.items()},
            worst(slide_a_idle), json.dumps(idle_a_ankles.get("contacts"))))

    # #780's data-level check: baking take 2 must not TOUCH take 1. Before
    # preserveOutsideKeys, bakeResults' default replaced each plug's whole
    # curve with keys for only the idle range - the walk still LOOKED
    # registered (mcp_clip metadata survived) while its frames evaluated to
    # a pre-infinity constant, the export resampled that constant with a
    # correct key COUNT, and only the pixels could have told anyone. The
    # walk's own kinematics re-measured after the idle bake must equal the
    # measurement taken before it.
    walk_after_idle = independent_measure(root_a, "walk",
                                          what="walk re-measure after idle")
    pelvis_before = (walk_agree.get("joints") or {}).get("pelvis") or {}
    pelvis_after = (walk_after_idle.get("joints") or {}).get("pelvis") or {}
    check(pelvis_before.get("path_length") == pelvis_after.get("path_length")
          and pelvis_before.get("path_length", 0) > 1.0,
         "walk motion unchanged by the idle bake (#780): pelvis path_length "
         "%s before, %s after"
         % (pelvis_before.get("path_length"), pelvis_after.get("path_length")))

    # ---- 3. composition: multi-take export_fbx, both clips, from rig A ---
    print("\n[3] composition: export_fbx multi-take (walk + idle) from rig A")
    records = declared_clips(root_a)
    check(sorted(r["name"] for r in records) == ["idle", "walk"],
         "rig A carries exactly the two declared clips: %s"
         % [r["name"] for r in records])

    fbx_path = os.path.join(OUT_DIR, "retarget_multi_take.fbx")
    if os.path.exists(fbx_path):
        os.unlink(fbx_path)
    export = ok("export_fbx", {"path": fbx_path.replace("\\", "/"),
                               "metres_per_unit": 1.0,
                               "include_animation": True}, 300.0,
               "export_fbx multi-take")
    anim = export.get("animation") or {}
    by_take_name = {t["name"]: t for t in anim.get("takes", [])}
    for record in records:
        fps = float(record["fps"])
        want_start = record["start_frame"] / fps
        want_stop = record["end_frame"] / fps
        tol = 0.5 / fps
        take = by_take_name.get(record["name"])
        check(take is not None
             and abs(take["start_s"] - want_start) <= tol
             and abs(take["stop_s"] - want_stop) <= tol,
             "export: a take named %r spans the declared frames %d-%d "
             "(take=%s, want %.4f..%.4f s)"
             % (record["name"], record["start_frame"], record["end_frame"],
                take, want_start, want_stop))

    # #718 byte-gate reuse (evals/multi_take_live.py's Task 12 pattern): an
    # INDEPENDENT re-read of the exported bytes must agree with the tool's
    # own reported "animation" block (excluding "clips", which is composed
    # from the scene's declared records, not the bytes alone - see
    # export.py's own comment on this exact exclusion).
    facts = fbxbytes.read_fbx(fbx_path)
    bytes_anim = fbxbytes.anim_facts(facts)
    check(bytes_anim == {k: v for k, v in anim.items() if k != "clips"},
         "export: an independent byte read agrees with the tool's own "
         "animation report")

    # retarget_clip's own registered clips carry an EMPTY declared `joints`
    # list (see module docstring), so the multi_take_live per-declared-
    # joint check is vacuous here. Checked directly instead: every one of
    # the 15 HIK-characterized joints this handler actually bakes carries a
    # correct 3-curve rotation record with the right key count for ITS OWN
    # take, in both takes; the pelvis (Hips) also carries root translation,
    # since a walk without root motion would not be a walk.
    baked_joints = sorted(set(mocapmath.SKELETON_HIK_MAP.values()))
    by_take_target = {}
    for row in anim.get("targets", []):
        if row.get("take") is None:
            continue
        by_take_target.setdefault(
            (row["take"], row["target"], row["property"]), row)
    coverage_failures = []
    for record in records:
        expected = record["end_frame"] - record["start_frame"] + 1
        for joint in baked_joints:
            entry = by_take_target.get((record["name"], joint, "Lcl Rotation"))
            if (entry is None or entry["curves"] != 3
                    or entry["key_count"] != expected):
                coverage_failures.append(
                    "%s/%s: %r (want curves=3 key_count=%d)"
                    % (record["name"], joint, entry, expected))
        pelvis_entry = by_take_target.get(
            (record["name"], "pelvis", "Lcl Translation"))
        if (pelvis_entry is None or pelvis_entry["curves"] != 3
                or pelvis_entry["key_count"] != expected):
            coverage_failures.append(
                "%s/pelvis root translation: %r (want curves=3 key_count=%d)"
                % (record["name"], pelvis_entry, expected))
    check(not coverage_failures,
         "export: all %d baked HIK joints (+ pelvis root translation) "
         "carry correct curves in both takes%s"
         % (len(baked_joints),
            "" if not coverage_failures
            else " - failures: " + "; ".join(coverage_failures[:6])))

    # ---- 4. preview_clip contact sheet: walk, rig A (still in-scene) -----
    print("\n[4] preview_clip contact sheet: walk, rig A")
    # DEFAULT zoom, on purpose (#780). The first run of this gate zoomed to
    # 2.5 because zoom=1.0 rendered a speck - but the framing box that made
    # the speck was frame 0's alone (inflated by the hidden bind-pose Orig
    # shape), and 2.5 cropped a frame the walk then LEFT at frame 105:
    # every later cell was the same byte-identical, subject-less render.
    # preview_clip now frames its held camera on the union of the subject's
    # bounds across all sampled frames, so the default framing both fits
    # the whole journey and keeps the figure readable.
    preview = ok("preview_clip", {"root": root_a, "name": "walk",
                                  "angle": "side", "resolution": 512},
                 120.0, "preview_clip walk")
    frame_imgs = preview.get("images", [])
    check(len(frame_imgs) > 0,
         "preview_clip returned at least one frame (%d)" % len(frame_imgs))
    pngs = [base64.b64decode(im["png_b64"]) for im in frame_imgs]
    for im, png in zip(frame_imgs, pngs):
        stats = images.pixel_stats(png)
        check(not stats.get("blank"), "%s cell is not blank" % im.get("label"))
    # #780's structural check: a moving clip's cells must ALL be distinct
    # images - a byte-identical run is a frozen or subject-less tail, and
    # measure_clip already proved this walk moves at every sampled frame.
    frame_hashes = [hashlib.md5(p).hexdigest() for p in pngs]
    dupe_labels = sorted({im.get("label")
                          for im, h in zip(frame_imgs, frame_hashes)
                          if frame_hashes.count(h) > 1})
    check(not dupe_labels,
         "all %d preview cells are distinct images (#780)%s"
         % (len(frame_hashes),
            "" if not dupe_labels else " - duplicates: %s" % dupe_labels))
    check(not [w for w in preview.get("warnings", []) if "drew nothing" in w],
         "no cell warned 'drew nothing' (#780 defense-in-depth warning)")
    if pngs:
        sheet_png = images.contact_sheet(pngs, cols=min(len(pngs), 4))
        sheet_path = os.path.join(OUT_DIR, "walk_sheet.png")
        with open(sheet_path, "wb") as fh:
            fh.write(sheet_png)
        print("  wrote %s (%d frames, labels=%s)"
             % (sheet_path, len(frame_imgs),
                [im.get("label") for im in frame_imgs]))

    # ---- 5. discrimination (a): a mis-proportioned rig slides MORE -------
    print("\n[5] discrimination (a): rig B (legs %.1fx longer) retargeted "
         "with the SAME walk - pre-clean slide must EXCEED rig A's"
         % LEG_STRETCH)
    ok("new_scene", {"confirm": True}, 180.0, "new_scene (rig B)")
    joints_b = stretch_legs(JOINTS, LEG_STRETCH)
    root_b = build_rig(joints_b, "rig B")

    walk_b = ok("retarget_clip", {"file": WALK_BVH, "root": root_b,
                                  "clip": "walk", "start": SOURCE_ROW_START,
                                  "end": WALK_SOURCE_LAST_ROW}, 300.0,
               "retarget_clip walk (rig B)")
    for w in walk_b.get("warnings", []):
        print("  warning: %s" % w)
    walk_b_before = independent_measure(root_b, "walk", CONTACT_JOINTS,
                                        "ankle slide, rig B pre-clean")
    slide_b_before = ankle_slide(walk_b_before)
    print("  rig B PRE-clean independent ankle slide: %s (worst=%.5f) "
         "contacts=%s"
         % ({k: round(v, 5) for k, v in slide_b_before.items()},
            worst(slide_b_before), json.dumps(walk_b_before.get("contacts"))))
    print("  rig A ankle slide (reference): worst=%.5f" % worst(slide_a_walk))
    check(worst(slide_b_before) > worst(slide_a_walk),
         "discrimination (a): mis-proportioned rig B's pre-clean slide "
         "(%.5f) exceeds well-proportioned rig A's (%.5f)"
         % (worst(slide_b_before), worst(slide_a_walk)))

    # ---- 6. discrimination (b): clean_clip measurably reduces it ---------
    print("\n[6] discrimination (b): clean_clip on rig B's walk - "
         "after-slide must be LESS than before-slide")
    cleaned = ok("clean_clip", {"root": root_b, "clip": "walk"}, 240.0,
                "clean_clip rig B walk")
    for w in cleaned.get("warnings", []):
        print("  warning: %s" % w)
    slide_b_before_report = ankle_slide(cleaned["before"])
    slide_b_after_report = ankle_slide(cleaned["after"])
    print("  clean_clip's own before/after ankle slide: before=%s after=%s"
         % ({k: round(v, 5) for k, v in slide_b_before_report.items()},
            {k: round(v, 5) for k, v in slide_b_after_report.items()}))
    check(worst(slide_b_after_report) < worst(slide_b_before_report),
         "discrimination (b): clean_clip's after-slide (%.5f) is less than "
         "its before-slide (%.5f)"
         % (worst(slide_b_after_report), worst(slide_b_before_report)))
    check(abs(worst(slide_b_before_report) - worst(slide_b_before)) < 1e-6,
         "clean_clip's own 'before' slide agrees with this gate's earlier "
         "independent pre-clean measurement (%.5f vs %.5f)"
         % (worst(slide_b_before_report), worst(slide_b_before)))

    # ---- 7. tolerances: rig A's own slide, measured then asserted --------
    # Two different jobs, not one: walk_slide is itself a measured
    # discriminator (good rig A passes it, bad rig B's pre-clean value
    # would fail it - see the TOLERANCES comment for the derivation);
    # idle_slide is a sanity ceiling (idle has no bad-rig counterpart
    # measured here). Neither IS the regression net for RELATIVE quality -
    # that is what the two unconditional discrimination checks in [5]/[6]
    # are for, asserted regardless of TOLERANCES.
    print("\n[7] tolerances (rig A, the well-proportioned reference)")
    print("  measured: walk worst ankle slide=%.5f, idle worst ankle "
         "slide=%.5f" % (worst(slide_a_walk), worst(slide_a_idle)))
    print("  mechanical 2x-rounded-up-1sig (floor 0.01) would give: "
         "walk=%.4f idle=%.4f - walk_slide is set BELOW that (see the "
         "TOLERANCES comment): the mechanical value (0.2) sits above rig "
         "B's own bad pre-clean measurement (%.5f) and could not "
         "discriminate a regression proportional across both rigs"
         % (round_up_1sig(2 * worst(slide_a_walk)),
            round_up_1sig(2 * worst(slide_a_idle)), worst(slide_b_before)))
    if TOLERANCES is None:
        print("  MEASUREMENT MODE - TOLERANCES is None: no threshold "
             "asserted on the slide numbers above (the two discriminations "
             "above were still asserted, unconditionally)")
    else:
        check(worst(slide_a_walk) <= TOLERANCES["walk_slide"],
             "rig A walk ankle slide %.5f <= tolerance %.5f"
             % (worst(slide_a_walk), TOLERANCES["walk_slide"]))
        check(worst(slide_a_idle) <= TOLERANCES["idle_slide"],
             "rig A idle ankle slide %.5f <= tolerance %.5f"
             % (worst(slide_a_idle), TOLERANCES["idle_slide"]))
        # Illustration only, never asserted: rig B exists to be CLEANED
        # UP, not to pass the good-rig ceiling, so its pre-clean value is
        # printed against walk_slide but not gated on it.
        print("  illustration (not asserted): rig B's bad pre-clean slide "
             "%.5f %s walk_slide tolerance %.5f - the tolerance itself "
             "discriminates"
             % (worst(slide_b_before),
                ">" if worst(slide_b_before) > TOLERANCES["walk_slide"]
                else "<=",
                TOLERANCES["walk_slide"]))

    print("\n%d checks failed" % len(FAILURES))
    for failure in FAILURES:
        print("  - %s" % failure)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
