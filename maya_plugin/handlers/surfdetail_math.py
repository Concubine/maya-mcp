"""Pure pattern + composite math for #775. No Maya imports."""
from __future__ import annotations
from typing import Any, Dict, List, Tuple
from . import sculpt_math

WEAR_THRESHOLD = 0.55
WEAR_OCTAVES = 3
GRIME_OCTAVES = 2
GRAIN_OCTAVES = 3
DEFAULT_WEAR_COLOR = (0.85, 0.82, 0.78)
DEFAULT_GRIME_COLOR = (0.09, 0.07, 0.05)


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


def _field(res: int, scale: float, seed: int, octaves: int, shaper):
    size = res
    freq = 8.0 * scale / size
    z = seed * 17.31 + 0.5
    vals = [shaper(sculpt_math.fbm(x * freq, y * freq, z, octaves))
            for y in range(size) for x in range(size)]
    return {"values": vals, "width": size, "height": size}


def wear_pattern(res: int, scale: float, seed: int) -> Dict[str, Any]:
    def shaper(f):  # ridged + thresholded: sparse scratch streaks
        r = 1.0 - min(1.0, abs(f) * 2.0)      # ridges where fbm crosses 0
        return (r - WEAR_THRESHOLD) / (1.0 - WEAR_THRESHOLD) \
            if r > WEAR_THRESHOLD else 0.0
    return _field(res, scale, seed, WEAR_OCTAVES, shaper)


def grime_pattern(res: int, scale: float, seed: int) -> Dict[str, Any]:
    def shaper(f):  # soft speckle biased dark-heavy
        return max(0.0, min(1.0, f * 0.5 + 0.5)) ** 1.5
    return _field(res, scale, seed, GRIME_OCTAVES, shaper)


def height_pattern(res: int, scale: float, seed: int) -> Dict[str, Any]:
    def shaper(f):
        return max(0.0, min(1.0, f * 0.5 + 0.5))
    return _field(res, scale, seed, GRAIN_OCTAVES, shaper)


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
