"""BVH parsing, HIK joint-name maps, and filter math for the retarget
pipeline (#774) - no Maya anywhere.

A mocap clip is a text file and a rig is a name list; every decision the
retargeter makes from them - which BVH joint feeds which HumanIK slot, what
bake rate a 120fps capture should land on, how hard to smooth a jittery
curve - is arithmetic and string matching, checkable without a running Maya.
The handler that drives `maya.cmds` (Task 3) is orchestration only; every
number it gets judged against comes from here, the same split
`curveform_math.py` and `arraymath.py` use for their tools.

`parse_bvh` is a two-phase parser (HIERARCHY stack walk, then MOTION rows)
that tracks a line number for every token it reads, so a malformed file gets
named exactly where it broke rather than a bare traceback. The HIK maps are
data, not logic: `CMU_HIK_MAP` matches the joint names actually present in
the CMU/cgspeed BVH fixtures this repo ships (`evals/mocap_fixtures/`), and
`SKELETON_HIK_MAP` matches the biped joint names `create_skeleton` builds
(#668, see `evals/humanoid_live.py`'s `JOINTS`). `resolve_hik_map` is the
only place either map gets read against a REAL skeleton's joint list, and it
never guesses: a slot that cannot be resolved is named, not silently dropped.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..dispatcher import HandlerError

# The 15 HumanIK slots #774's retarget needs filled before a bake can run.
# Order here is "root out along the spine, then each limb" - purely for
# readable error messages; resolve_hik_map does not depend on it.
REQUIRED_HIK_SLOTS = (
    "Hips",
    "LeftUpLeg", "LeftLeg", "LeftFoot",
    "RightUpLeg", "RightLeg", "RightFoot",
    "Spine",
    "LeftArm", "LeftForeArm", "LeftHand",
    "RightArm", "RightForeArm", "RightHand",
    "Head",
)

# The CMU Graphics Lab's raw BVH export (and the cgspeed conversion this repo's
# fixtures come from, `evals/mocap_fixtures/ATTRIBUTION.md`) already uses these
# exact names for the 15 required slots - measured directly against
# `cmu_walk.bvh`/`cmu_idle.bvh` rather than assumed, because CMU's *full*
# skeleton also carries `LHipJoint`/`RHipJoint` (a fixed pelvis-to-hip stub
# with no motion of its own) and `LowerBack`/`Spine1` alongside `Spine` - none
# of those are required slots, so they are not in this table at all.
CMU_HIK_MAP: Dict[str, str] = {
    "Hips": "Hips",
    "LeftUpLeg": "LeftUpLeg",
    "LeftLeg": "LeftLeg",
    "LeftFoot": "LeftFoot",
    "RightUpLeg": "RightUpLeg",
    "RightLeg": "RightLeg",
    "RightFoot": "RightFoot",
    "Spine": "Spine",
    "LeftArm": "LeftArm",
    "LeftForeArm": "LeftForeArm",
    "LeftHand": "LeftHand",
    "RightArm": "RightArm",
    "RightForeArm": "RightForeArm",
    "RightHand": "RightHand",
    "Head": "Head",
}

# `create_skeleton`'s biped naming (#668), read from `evals/humanoid_live.py`'s
# JOINTS list - the canonical name for each joint this repo's own rigs use.
SKELETON_HIK_MAP: Dict[str, str] = {
    "Hips": "pelvis",
    "LeftUpLeg": "L_hip",
    "LeftLeg": "L_knee",
    "LeftFoot": "L_ankle",
    "RightUpLeg": "R_hip",
    "RightLeg": "R_knee",
    "RightFoot": "R_ankle",
    "Spine": "spine_01",
    "LeftArm": "L_shoulder",
    "LeftForeArm": "L_elbow",
    "LeftHand": "L_wrist",
    "RightArm": "R_shoulder",
    "RightForeArm": "R_elbow",
    "RightHand": "R_wrist",
    "Head": "head",
}

# A source rate above this is never a real mocap capture rate - it is
# frame time expressed in the wrong unit (milliseconds instead of seconds,
# say). Refusing early gives a diagnosable error instead of a downstream
# "why are there a million frames" confusion.
_MAX_SOURCE_FPS = 1000.0


# ---------------------------------------------------------------------------
# BVH parsing
# ---------------------------------------------------------------------------

_ROOT_JOINT_RE = re.compile(r"^(ROOT|JOINT)\s+(\S+)\s*$")
_END_SITE_RE = re.compile(r"^End\s+Site\s*$", re.IGNORECASE)
_OFFSET_RE = re.compile(r"^OFFSET\s+(\S+)\s+(\S+)\s+(\S+)\s*$")
_CHANNELS_RE = re.compile(r"^CHANNELS\s+(\d+)\s+(.+)$")
_FRAMES_RE = re.compile(r"^Frames:\s*(\d+)\s*$", re.IGNORECASE)
_FRAME_TIME_RE = re.compile(r"^Frame Time:\s*([-+0-9.eE]+)\s*$", re.IGNORECASE)


def _numbered_tokens(lines: Sequence[str]) -> List[Tuple[int, str]]:
    """Non-blank lines as `(1-based line number, stripped text)`.

    Blank lines carry no information in a BVH file (indentation is
    whitespace, not syntax), so dropping them here means every other parsing
    function can look at "the next token" without special-casing gaps - and
    every line number reported in an error is the ORIGINAL file's line, not
    an index into this filtered list.
    """
    out = []
    for i, raw in enumerate(lines):
        stripped = raw.strip()
        if stripped:
            out.append((i + 1, stripped))
    return out


def _parse_hierarchy(lines: Sequence[str]) -> List[Dict[str, Any]]:
    tokens = _numbered_tokens(lines)
    if not tokens:
        raise HandlerError(
            "BVH text has no HIERARCHY section",
            hint="a BVH file's first non-blank line must be the literal word HIERARCHY",
        )
    line_no, tok = tokens[0]
    if tok != "HIERARCHY":
        raise HandlerError(
            "line %d: BVH text must begin with HIERARCHY, got %r" % (line_no, tok),
            hint="a BVH file's first non-blank line must be the literal word HIERARCHY",
        )

    joints: List[Dict[str, Any]] = []
    pos = 1

    def peek() -> Tuple[int, str]:
        if pos >= len(tokens):
            raise HandlerError(
                "line %d: hierarchy ends unexpectedly (unbalanced braces?)"
                % tokens[-1][0],
                hint="every '{' needs a matching '}'",
            )
        return tokens[pos]

    def consume_literal(expected: str) -> None:
        nonlocal pos
        ln, tok = peek()
        if tok != expected:
            raise HandlerError(
                "line %d: expected %r, got %r" % (ln, expected, tok),
                hint="check the brace/keyword structure around this line",
            )
        pos += 1

    def parse_end_site() -> None:
        nonlocal pos
        pos += 1  # consume the 'End Site' line itself
        consume_literal("{")
        ln, tok = peek()
        if not _OFFSET_RE.match(tok):
            raise HandlerError(
                "line %d: End Site expected OFFSET x y z, got %r" % (ln, tok),
                hint="e.g. OFFSET 0.0 10.0 0.0",
            )
        pos += 1
        consume_literal("}")

    def parse_block(parent_index: Optional[int], keyword: str) -> int:
        nonlocal pos
        ln, tok = peek()
        m = _ROOT_JOINT_RE.match(tok)
        if not m or m.group(1) != keyword:
            raise HandlerError(
                "line %d: expected %s <name>, got %r" % (ln, keyword, tok),
                hint="e.g. %s Hips" % keyword,
            )
        name = m.group(2)
        pos += 1
        consume_literal("{")

        ln, tok = peek()
        m_off = _OFFSET_RE.match(tok)
        if not m_off:
            raise HandlerError(
                "line %d: expected OFFSET x y z, got %r" % (ln, tok),
                hint="e.g. OFFSET 0.0 10.0 0.0",
            )
        try:
            offset = [float(m_off.group(i)) for i in (1, 2, 3)]
        except ValueError:
            raise HandlerError(
                "line %d: OFFSET values must be numbers, got %r" % (ln, tok),
                hint="e.g. OFFSET 0.0 10.0 0.0",
            )
        pos += 1

        ln, tok = peek()
        m_ch = _CHANNELS_RE.match(tok)
        if not m_ch:
            raise HandlerError(
                "line %d: expected CHANNELS <n> <names...>, got %r" % (ln, tok),
                hint="e.g. CHANNELS 6 Xposition Yposition Zposition "
                "Zrotation Xrotation Yrotation",
            )
        declared = int(m_ch.group(1))
        channel_names = m_ch.group(2).split()
        if len(channel_names) != declared:
            raise HandlerError(
                "line %d: CHANNELS declares %d but lists %d names"
                % (ln, declared, len(channel_names)),
                hint="the count and the space-separated name list must agree",
            )
        pos += 1

        my_index = len(joints)
        joints.append({
            "name": name,
            "parent": parent_index,
            "offset": offset,
            "channels": channel_names,
        })

        while True:
            ln, tok = peek()
            if tok == "}":
                pos += 1
                break
            if _END_SITE_RE.match(tok):
                parse_end_site()
                continue
            m_child = _ROOT_JOINT_RE.match(tok)
            if m_child and m_child.group(1) == "JOINT":
                parse_block(my_index, "JOINT")
                continue
            raise HandlerError(
                "line %d: expected JOINT, End Site, or '}', got %r" % (ln, tok),
                hint="a joint block holds child JOINT blocks, then one End "
                "Site or none, then '}'",
            )
        return my_index

    parse_block(None, "ROOT")
    if pos != len(tokens):
        ln, tok = tokens[pos]
        raise HandlerError(
            "line %d: unexpected content after the hierarchy's closing brace: %r"
            % (ln, tok),
            hint="a BVH file has exactly one ROOT block",
        )
    return joints


def _parse_motion(
    lines: Sequence[str], motion_at: int, joints: Sequence[Dict[str, Any]]
) -> Tuple[float, int, List[List[float]]]:
    total_channels = sum(len(j["channels"]) for j in joints)
    tokens = []
    for i in range(motion_at + 1, len(lines)):
        stripped = lines[i].strip()
        if stripped:
            tokens.append((i + 1, stripped))

    if len(tokens) < 2:
        raise HandlerError(
            "line %d: MOTION section needs 'Frames:' and 'Frame Time:' lines"
            % (motion_at + 1),
            hint="e.g.\nMOTION\nFrames: 2\nFrame Time: 0.033333",
        )

    ln, tok = tokens[0]
    m_frames = _FRAMES_RE.match(tok)
    if not m_frames:
        raise HandlerError(
            "line %d: expected 'Frames: <n>', got %r" % (ln, tok),
            hint="e.g. Frames: 120",
        )
    frames = int(m_frames.group(1))

    ln, tok = tokens[1]
    m_ft = _FRAME_TIME_RE.match(tok)
    if not m_ft:
        raise HandlerError(
            "line %d: expected 'Frame Time: <seconds>', got %r" % (ln, tok),
            hint="e.g. Frame Time: 0.033333",
        )
    try:
        frame_time = float(m_ft.group(1))
    except ValueError:
        raise HandlerError(
            "line %d: Frame Time must be a number, got %r" % (ln, tok),
            hint="e.g. Frame Time: 0.033333",
        )

    rows: List[List[float]] = []
    for ln, tok in tokens[2:]:
        parts = tok.split()
        try:
            values = [float(p) for p in parts]
        except ValueError:
            raise HandlerError(
                "line %d: motion row has a non-numeric value: %r" % (ln, tok),
                hint="every motion row is %d space-separated numbers"
                % total_channels,
            )
        if len(values) != total_channels:
            raise HandlerError(
                "line %d: motion row has %d values, expected %d "
                "(the hierarchy's total channel count)"
                % (ln, len(values), total_channels),
                hint="every motion row needs exactly one value per channel, "
                "across every joint in the hierarchy",
            )
        rows.append(values)

    if len(rows) != frames:
        raise HandlerError(
            "Frames: declared %d but the file has %d motion rows"
            % (frames, len(rows)),
            hint="fix the Frames: count, or check for missing/extra motion rows",
        )
    return frame_time, frames, rows


def parse_bvh(text: str) -> Dict[str, Any]:
    """A BVH file's hierarchy and motion data, or a line-numbered refusal.

    Two phases, in the file's own order: `_parse_hierarchy` walks the
    HIERARCHY block's brace structure with an explicit stack (recursion
    through `parse_block`/`parse_end_site`), then `_parse_motion` reads the
    MOTION block's rows against the channel total the hierarchy just
    produced. Every refusal names the 1-based source line it broke on, so a
    malformed fixture (or a hand-edited one, as this module's own tests do)
    is diagnosable without re-deriving line numbers by hand.
    """
    lines = text.splitlines()
    motion_at = None
    for i, raw in enumerate(lines):
        if raw.strip() == "MOTION":
            motion_at = i
            break
    if motion_at is None:
        raise HandlerError(
            "BVH text has no MOTION section",
            hint="a BVH file needs a HIERARCHY block followed by a literal "
            "'MOTION' line, then 'Frames:'/'Frame Time:', then the motion rows",
        )
    joints = _parse_hierarchy(lines[:motion_at])
    frame_time, frames, rows = _parse_motion(lines, motion_at, joints)
    return {
        "joints": joints,
        "frame_time": frame_time,
        "frames": frames,
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# Frame-rate math
# ---------------------------------------------------------------------------


def source_fps(frame_time: float) -> float:
    """The exact frame rate a BVH's `Frame Time` implies - no rounding.

    A mocap source can be captured at ANY rate (CMU's raw exports run
    120fps, which is not a Maya time unit); resampling to something Maya can
    bake is a separate decision (`nearest_bake_fps`). This function only
    reports what the file actually says, refusing a frame time that could
    not be a real capture interval - non-positive (no such thing as zero or
    negative seconds per frame) or absurdly high (over 1000fps is almost
    certainly the wrong unit, e.g. milliseconds instead of seconds).
    """
    if isinstance(frame_time, bool) or not isinstance(frame_time, (int, float)):
        raise HandlerError(
            "frame time must be a number of seconds, got %r" % (frame_time,),
            hint="e.g. source_fps(1.0 / 120.0) for a 120fps capture",
        )
    if frame_time <= 0.0:
        raise HandlerError(
            "frame time must be positive, got %r" % (frame_time,),
            hint="frame time is SECONDS PER FRAME - it can never be zero or negative",
        )
    fps = 1.0 / float(frame_time)
    if fps > _MAX_SOURCE_FPS:
        raise HandlerError(
            "frame time %r implies %.1f fps, over the %d fps sanity ceiling"
            % (frame_time, fps, _MAX_SOURCE_FPS),
            hint="check the unit - frame time is seconds, not milliseconds",
        )
    return fps


def nearest_bake_fps(source_fps: float, allowed: Any) -> int:
    """The closest of `allowed` to `source_fps`, ties favoring the higher rate.

    A capture at 120fps has no Maya time unit of its own; the retargeter
    bakes onto whichever Maya-native rate is closest, and a tie (equidistant
    between two candidates) resolves upward - a scene's `currentUnit -time`
    can always play a baked-high clip back slower, but the reverse loses
    frames that were never captured.
    """
    if not isinstance(allowed, (set, frozenset)) or not allowed:
        raise HandlerError(
            "allowed must be a non-empty set of fps units, got %r" % (allowed,),
            hint="e.g. {24, 25, 30, 48, 50, 60}",
        )
    if isinstance(source_fps, bool) or not isinstance(source_fps, (int, float)):
        raise HandlerError(
            "source_fps must be a number, got %r" % (source_fps,),
            hint="pass the value returned by mocapmath.source_fps(frame_time)",
        )
    best = None
    best_dist = None
    for unit in sorted(allowed):
        dist = abs(unit - source_fps)
        if best is None or dist < best_dist or (dist == best_dist and unit > best):
            best, best_dist = unit, dist
    return int(best)


# ---------------------------------------------------------------------------
# HIK slot resolution
# ---------------------------------------------------------------------------


def resolve_hik_map(joint_names: Sequence[str], table: Dict[str, str]) -> Dict[str, str]:
    """`{slot: joint_name}` for every required HIK slot, or a named refusal.

    Two distinct ways a mapping can fail, both named rather than merged into
    one vague error: `table` itself might not declare a required slot at
    all (a caller-supplied table missing an entry), or it might declare one
    that points at a joint name the ACTUAL skeleton does not have (the
    common case - a table built for one naming convention handed the joint
    list of another). Guessing a substitute for either is exactly the #764
    mistake this repo already paid for once; naming both kinds of gap is
    what makes the caller's next step obvious.
    """
    names = set(joint_names)
    missing_slots = []
    unmatched = []
    for slot in REQUIRED_HIK_SLOTS:
        if slot not in table:
            missing_slots.append(slot)
            continue
        target = table[slot]
        if target not in names:
            unmatched.append((slot, target))
    if missing_slots or unmatched:
        parts = []
        if missing_slots:
            parts.append("table has no entry for slot(s): %s" % ", ".join(missing_slots))
        if unmatched:
            parts.append(
                "no joint named %s"
                % ", ".join("%r (slot %s)" % (target, slot) for slot, target in unmatched)
            )
        raise HandlerError(
            "; ".join(parts),
            hint="every required HIK slot must map to a joint name present in "
            "this skeleton - check spelling and case in the joint list and the map",
        )
    return {slot: table[slot] for slot in REQUIRED_HIK_SLOTS}


# ---------------------------------------------------------------------------
# Savitzky-Golay smoothing
# ---------------------------------------------------------------------------


def _matmul(a: List[List[float]], b: List[List[float]]) -> List[List[float]]:
    rows_a, inner = len(a), len(a[0])
    cols_b = len(b[0])
    out = [[0.0] * cols_b for _ in range(rows_a)]
    for i in range(rows_a):
        for k in range(inner):
            aik = a[i][k]
            if aik == 0.0:
                continue
            row_b = b[k]
            row_out = out[i]
            for j in range(cols_b):
                row_out[j] += aik * row_b[j]
    return out


def _transpose(a: List[List[float]]) -> List[List[float]]:
    return [list(col) for col in zip(*a)]


def _invert_square(matrix: List[List[float]]) -> List[List[float]]:
    """Gauss-Jordan inverse, stdlib only - these matrices are `(order+1)^2`,
    small enough (order stays under `window`, itself a bounded filter width)
    that a hand-rolled elimination is simpler than adding a numpy dependency
    for one function.
    """
    n = len(matrix)
    aug = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot_row = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot_row][col]) < 1e-12:
            raise HandlerError(
                "smooth_track: window/order combination is numerically singular",
                hint="use a smaller order relative to window, e.g. order=2 with window>=5",
            )
        aug[col], aug[pivot_row] = aug[pivot_row], aug[col]
        pivot = aug[col][col]
        aug[col] = [v / pivot for v in aug[col]]
        for r in range(n):
            if r != col:
                factor = aug[r][col]
                if factor != 0.0:
                    aug[r] = [rv - factor * cv for rv, cv in zip(aug[r], aug[col])]
    return [row[n:] for row in aug]


def _savgol_weights(window: int, order: int) -> List[float]:
    """Convolution weights `w` such that `sum(w[j] * y[j])` is the smoothed
    center-point value: fit a degree-`order` polynomial by least squares to
    `window` points centered on the target, then evaluate it AT the center.

    `w` is the first row of `(A^T A)^-1 A^T`, where `A` is the Vandermonde
    matrix of centered offsets `-half..+half` raised to powers `0..order` -
    the fitted polynomial's constant term IS its value at offset 0, so that
    row is exactly the center-point weight vector.
    """
    half = window // 2
    a = [[float(t) ** p for p in range(order + 1)] for t in range(-half, half + 1)]
    at = _transpose(a)
    ata = _matmul(at, a)
    ata_inv = _invert_square(ata)
    m = _matmul(ata_inv, at)
    return m[0]


# `smooth_track`'s own window floor: below 5 samples every shrunk fit
# spans no more points than its own polynomial order, so the fit passes
# through each sample exactly and the filter is the identity. MEASURED in
# tests/test_mocapmath.py::TestTheWindowThatActuallyFits.
MIN_SMOOTHING_SAMPLES = 5


def largest_smoothing_window(n_samples: int) -> int:
    """The widest window `smooth_track` can actually CENTRE on a track of
    `n_samples` - 0 when the track is too short for any legal window.

    The per-sample shrink below is what makes this the number that
    matters (#797 row 24): a window wider than the track is neither an
    error nor a wider filter, it is the SAME filter as this one, silently.
    A centered odd window cannot span an even length, so a 30-frame clip
    tops out at 29 - window 29, 31 and 101 all produce the same output.
    """
    widest = n_samples if n_samples % 2 else n_samples - 1
    return widest if widest >= MIN_SMOOTHING_SAMPLES else 0


def smooth_track(values: List[float], window: int, order: int = 2) -> List[float]:
    """Savitzky-Golay smoothing: a local polynomial fit re-evaluated at each
    point, which (unlike a plain moving average) preserves a signal that is
    already a degree-`order` polynomial - a smoothed walk cycle should not
    round off the swing it actually measured.

    `window` must be odd (a symmetric window needs an equal count each side
    of center) and at least 5 (below that a degree-2 fit is either
    underdetermined or degenerates to the input unchanged - not what a
    caller asking for smoothing wants). Near the ends, where a full window
    would run off the track, the window SHRINKS symmetrically to whatever
    fits - not zero-padded, which would fabricate motion at a boundary; not
    left unsmoothed, which would leave the noisiest samples (endpoints,
    where a moving fit has the least support) exactly as filtered as before.
    """
    if isinstance(window, bool) or not isinstance(window, int) or window < 5 or window % 2 == 0:
        raise HandlerError(
            "window must be an odd whole number of at least 5, got %r" % (window,),
            hint="e.g. window=5 or window=7 - Savitzky-Golay needs a centered odd window",
        )
    if isinstance(order, bool) or not isinstance(order, int) or order < 1 or order >= window:
        raise HandlerError(
            "order must be a whole number from 1 up to window-1, got %r" % (order,),
            hint="order=2 (the default) fits a local parabola",
        )
    n = len(values)
    if n == 0:
        return []

    half = window // 2
    full_weights = _savgol_weights(window, order) if n >= window else None
    shrunk_cache: Dict[Tuple[int, int], List[float]] = {}
    out = []
    for i in range(n):
        radius = min(half, i, n - 1 - i)
        if radius == half and full_weights is not None:
            weights = full_weights
        else:
            eff_window = 2 * radius + 1
            eff_order = min(order, eff_window - 1)
            key = (eff_window, eff_order)
            if key not in shrunk_cache:
                shrunk_cache[key] = _savgol_weights(eff_window, eff_order)
            weights = shrunk_cache[key]
        lo = i - (len(weights) // 2)
        window_vals = values[lo: lo + len(weights)]
        out.append(sum(w * v for w, v in zip(weights, window_vals)))
    return out


# ---------------------------------------------------------------------------
# Contact-run edge blending
# ---------------------------------------------------------------------------


def blend_weights(n: int, edge: int) -> List[float]:
    """A `0 -> 1 -> 0` raised-cosine ramp, `n` samples long, `edge` samples
    per side.

    Applied at a contact run's boundary (foot-plant start/end), a hard `0/1`
    step would introduce a discontinuous velocity right where a cleanup pass
    is trying to REMOVE a discontinuity (the slide #773 measures). The raised
    cosine has zero slope at both the 0 and 1 ends, so blending against it
    never adds a new kink of its own.
    """
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise HandlerError(
            "n must be a positive whole number, got %r" % (n,),
            hint="n is the number of frames in the contact run being blended",
        )
    if isinstance(edge, bool) or not isinstance(edge, int) or edge < 0:
        raise HandlerError(
            "edge must be a non-negative whole number, got %r" % (edge,),
            hint="edge is how many frames ramp in/out at each end, e.g. edge=3",
        )
    if 2 * edge > n:
        raise HandlerError(
            "edge %d is too large for a %d-frame run - 2*edge must not exceed n"
            % (edge, n),
            hint="use a smaller edge, or a longer contact run",
        )
    weights = [1.0] * n
    for i in range(edge):
        ramp = 0.5 * (1.0 - math.cos(math.pi * i / (edge - 1))) if edge > 1 else 0.0
        weights[i] = ramp
        weights[n - 1 - i] = ramp
    return weights
