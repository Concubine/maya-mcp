"""Pure math for #775 - no Maya anywhere."""
import pytest
from maya_plugin.handlers import surfdetail_math as sm


def _flat_png(w, h, value, alpha=255):
    return {"width": w, "height": h,
            "pixels": [(value, value, value, alpha)] * (w * h)}


class TestMask:
    def test_mask_values_scales_red_to_unit(self):
        m = sm.mask_values(_flat_png(2, 2, 128), invert=False)
        assert m["width"] == 2 and m["height"] == 2
        assert all(abs(v - 128 / 255.0) < 1e-9 for v in m["values"])

    def test_invert_flips(self):
        m = sm.mask_values(_flat_png(1, 1, 0), invert=True)
        assert m["values"] == [1.0]

    def test_sample_nearest_across_resolutions(self):
        # 2x2 mask sampled at res 4: each quadrant reads its source texel.
        png = {"width": 2, "height": 2,
               "pixels": [(0, 0, 0, 255), (255, 255, 255, 255),
                          (255, 255, 255, 255), (0, 0, 0, 255)]}
        m = sm.mask_values(png, invert=False)
        assert sm.sample(m, 0, 0, 4) == 0.0      # top-left quadrant
        assert sm.sample(m, 3, 0, 4) == 1.0      # top-right
        assert sm.sample(m, 0, 3, 4) == 1.0
        assert sm.sample(m, 3, 3, 4) == 0.0


class TestPatterns:
    def test_wear_is_sparse_and_bounded(self):
        p = sm.wear_pattern(64, scale=1.0, seed=0)
        vals = p["values"]
        assert len(vals) == 64 * 64
        assert all(0.0 <= v <= 1.0 for v in vals)
        zero = sum(1 for v in vals if v == 0.0)
        assert zero > len(vals) * 0.5  # scratches are sparse, not a wash

    def test_grime_and_height_bounded_and_varied(self):
        for fn in (sm.grime_pattern, sm.height_pattern):
            p = fn(64, scale=1.0, seed=0)
            vals = p["values"]
            assert all(0.0 <= v <= 1.0 for v in vals)
            assert len(set(round(v, 6) for v in vals)) > 10  # not flat

    def test_seed_changes_pattern_deterministically(self):
        a = sm.wear_pattern(32, 1.0, seed=1)["values"]
        b = sm.wear_pattern(32, 1.0, seed=2)["values"]
        c = sm.wear_pattern(32, 1.0, seed=1)["values"]
        assert a == c
        assert a != b


class TestComposite:
    def _mask_half(self):
        # left half 0, right half 1 at 4x4
        vals = [1.0 if x >= 2 else 0.0 for y in range(4) for x in range(4)]
        return {"values": vals, "width": 4, "height": 4}

    def _pattern_all(self):
        return {"values": [1.0] * 16, "width": 4, "height": 4}

    def test_detail_lands_only_where_mask_says(self):
        base = [(0.5, 0.5, 0.5)] * 16
        out = sm.composite_detail(base, [{
            "kind": "grime", "pattern": self._pattern_all(),
            "mask": self._mask_half(), "strength": 1.0,
            "color_linear": (0.0, 0.0, 0.0)}], 4)
        px = out["pixels"]
        left = [px[y * 4 + x] for y in range(4) for x in range(2)]
        right = [px[y * 4 + x] for y in range(4) for x in range(2, 4)]
        assert all(p == left[0] for p in left)
        assert all(r[0] < left[0][0] for r in right)  # darkened only right
        assert 0.49 < out["changed"]["grime"] <= 0.51

    def test_wear_lightens_toward_color(self):
        base = [(0.2, 0.2, 0.2)] * 16
        out = sm.composite_detail(base, [{
            "kind": "wear", "pattern": self._pattern_all(),
            "mask": self._pattern_all(), "strength": 1.0,
            "color_linear": (1.0, 1.0, 1.0)}], 4)
        assert all(p[0] > 100 for p in out["pixels"])  # lifted well above base

    def test_order_is_wear_then_grime_regardless_of_list(self):
        base = [(0.5, 0.5, 0.5)] * 16
        eff_w = {"kind": "wear", "pattern": self._pattern_all(),
                 "mask": self._pattern_all(), "strength": 1.0,
                 "color_linear": (1.0, 1.0, 1.0)}
        eff_g = {"kind": "grime", "pattern": self._pattern_all(),
                 "mask": self._pattern_all(), "strength": 1.0,
                 "color_linear": (0.0, 0.0, 0.0)}
        a = sm.composite_detail(base, [eff_w, eff_g], 4)["pixels"]
        b = sm.composite_detail(base, [eff_g, eff_w], 4)["pixels"]
        assert a == b

    def test_strength_zero_changes_nothing(self):
        base = [(0.5, 0.5, 0.5)] * 16
        out = sm.composite_detail(base, [{
            "kind": "grime", "pattern": self._pattern_all(),
            "mask": self._pattern_all(), "strength": 0.0,
            "color_linear": (0.0, 0.0, 0.0)}], 4)
        assert out["changed"]["grime"] == 0.0
