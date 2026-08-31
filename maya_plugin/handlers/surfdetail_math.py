"""Pure pattern + composite math for #775. No Maya imports."""
from __future__ import annotations
from typing import Any, Dict, List, Tuple
from . import sculpt_math

# Pinned by the #775 look probe (evals/surfdetail_live.py, task 6) against
# REAL Arnold bakes of the gate's limb/collar/ground, not by eye on paper.
#
# WEAR_THRESHOLD 0.55 -> 0.62: at 0.55 the ridge pattern's zero fraction was
# 0.5061 at seed 0 (64px, scale 1) - a hair over the "scratches are sparse,
# not a wash" bar the pure test asserts, and it LOOKED like a wash. 0.62
# measures 0.5701 there (0.633-0.724 at seeds 1-3) and reads as separated
# streaks. Raising it costs coverage, not peak intensity: the shaper is
# (r-T)/(1-T), so a ridge crest still reaches 1.0.
#
# DEFAULT_WEAR_COLOR (0.85,0.82,0.78) -> (0.97,0.95,0.91): the old value was
# the probe's clearest finding. Wear is a lerp TARGET, and a target only 0.10
# linear above a typical 0.75 base cannot be seen at ANY strength - measured
# on the real limb-curvature bake, the whole composite spanned 225..231 of
# 255, i.e. six levels, with 41% of texels "changed". With this target the
# same bake spans 225..252 (27 levels) and the scuffs are legible in a
# render. Still warm-biased (R>G>B) - exposed/polished material, not chalk.
#
# DEFAULT_GRIME_COLOR is unchanged: probed and already strong enough (a dark
# target 0.66 linear BELOW the base). Grime's weakness was never its colour,
# it was weight - see the task-6 report's strength finding.
WEAR_THRESHOLD = 0.62
WEAR_OCTAVES = 3
GRIME_OCTAVES = 2
GRAIN_OCTAVES = 3
DEFAULT_WEAR_COLOR = (0.97, 0.95, 0.91)
DEFAULT_GRIME_COLOR = (0.09, 0.07, 0.05)

# Base pattern frequency in feature cycles across the whole UV tile, BEFORE
# the caller's `scale` multiplier (whose documented meaning - "a pattern-
# frequency multiplier" - is unchanged; it now multiplies a per-effect base
# instead of one shared 8.0).
#
# One shared 8.0 served all three, and the look probe measured that as the
# worst-looking thing about this module: eight cycles across a tile is a
# blob field. Measured on the gate's real limb bakes at 512, against the
# same masks the tool would use:
#
#   grain, mean |neighbour delta| in the written height PNG - which is
#   exactly the gradient bump2d has to shade with:
#       8.0 -> 0.56    32.0 -> 1.77    64.0 -> 3.29    96.0 -> 4.67
#   At 8.0 the "grain" render was an unmarked cylinder at 3x magnification.
#
#   wear: the correlation barely moves (top-quartile delta 2.735 at 8.0 vs
#   2.793 at 32.0) because DIRECTION is the mask's job - the frequency is
#   the LOOK, and by eye 8.0 is a handful of long soft smudges while 32.0
#   is the broken fine scuffs along an edge the ticket asks for.
#
#   grime keeps 8.0: soft patches are what it should be, and it is the one
#   effect the old shared value actually suited.
#
# 96.0 was rejected for grain despite the larger gradient: at 3 octaves its
# top octave lands under two texels per cycle at 512, i.e. sampling noise
# rather than relief.
WEAR_FREQ = 32.0
GRIME_FREQ = 8.0
GRAIN_FREQ = 64.0


def mask_values(png: Dict[str, Any], invert: bool) -> Dict[str, Any]:
    vals = [p[0] / 255.0 for p in png["pixels"]]
    if invert:
        vals = [1.0 - v for v in vals]
    return {"values": vals, "width": png["width"], "height": png["height"]}


def sample(field: Dict[str, Any], x: int, y: int, res: int) -> float:
    fw, fh = field["width"], field["height"]
    sx = min(fw - 1, x * fw // res)
    sy = min(fh - 1, y * fh // res)
    return field["values"][sy * fw + sx]


def _field(res: int, scale: float, seed: int, octaves: int, shaper,
           base_freq: float = 8.0):
    size = res
    freq = base_freq * scale / size
    z = seed * 17.31 + 0.5
    vals = [shaper(sculpt_math.fbm(x * freq, y * freq, z, octaves))
            for y in range(size) for x in range(size)]
    return {"values": vals, "width": size, "height": size}


def wear_pattern(res: int, scale: float, seed: int) -> Dict[str, Any]:
    def shaper(f):  # ridged + thresholded: sparse scratch streaks
        r = 1.0 - min(1.0, abs(f) * 2.0)      # ridges where fbm crosses 0
        return (r - WEAR_THRESHOLD) / (1.0 - WEAR_THRESHOLD) \
            if r > WEAR_THRESHOLD else 0.0
    return _field(res, scale, seed, WEAR_OCTAVES, shaper, WEAR_FREQ)


def grime_pattern(res: int, scale: float, seed: int) -> Dict[str, Any]:
    def shaper(f):  # soft speckle biased dark-heavy
        return max(0.0, min(1.0, f * 0.5 + 0.5)) ** 1.5
    return _field(res, scale, seed, GRIME_OCTAVES, shaper, GRIME_FREQ)


def height_pattern(res: int, scale: float, seed: int) -> Dict[str, Any]:
    def shaper(f):
        return max(0.0, min(1.0, f * 0.5 + 0.5))
    return _field(res, scale, seed, GRAIN_OCTAVES, shaper, GRAIN_FREQ)


_ORDER = ("wear", "grime")


def composite_detail(base_linear: List[Tuple[float, float, float]],
                     effects: List[Dict[str, Any]],
                     res: int) -> Dict[str, Any]:
    """lerp(base, color, w) per texel in LINEAR, w = pattern*mask*strength.
    Wear then grime, whatever order the caller listed. Returns 8-bit sRGB
    pixels via meshmaps' encoder plus per-effect changed-texel fractions."""
    from . import meshmaps  # encoder lives with #770's composite
    n = res * res
    work = [list(p) for p in base_linear]
    changed = {}
    for kind in _ORDER:
        eff = next((e for e in effects if e["kind"] == kind), None)
        if eff is None:
            continue
        touched = 0
        color = eff["color_linear"]
        for i in range(n):
            x, y = i % res, i // res
            w = (sample(eff["pattern"], x, y, res)
                 * sample(eff["mask"], x, y, res) * eff["strength"])
            if w <= 0.0:
                continue
            w = min(1.0, w)
            px = work[i]
            before = tuple(px)
            for c in range(3):
                px[c] = px[c] + (color[c] - px[c]) * w
            if tuple(px) != before:
                touched += 1
        changed[kind] = touched / float(n)
    pixels = [(meshmaps._srgb_encode(p[0]), meshmaps._srgb_encode(p[1]),
               meshmaps._srgb_encode(p[2])) for p in work]
    return {"pixels": pixels, "changed": changed}
