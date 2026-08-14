"""Atlas patch arithmetic: where in UV space does patch N live?

Pure numbers, no Maya. The handler (tests/test_uvatlas.py) only has to drive
cmds correctly; every rectangle it uses is decided here.

The convention under test, because it is the one a caller can get wrong: patch
indices run ROW-MAJOR FROM THE TOP-LEFT, the way you read the atlas PNG in an
image viewer. UV space has v increasing upward, so index 0 is the patch with
the HIGHEST v - not the lowest.
"""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import uvmath


class TestPatchRect:
    def test_single_patch_atlas_is_the_whole_uv_square(self):
        assert uvmath.patch_rect(1, 1, 0, 0) == (0.0, 0.0, 1.0, 1.0)

    def test_quadrants_of_a_two_by_two(self):
        # (col, row) with row 0 at the TOP, so row 0 occupies v 0.5..1.0
        assert uvmath.patch_rect(2, 2, 0, 0) == (0.0, 0.5, 0.5, 1.0)
        assert uvmath.patch_rect(2, 2, 1, 0) == (0.5, 0.5, 1.0, 1.0)
        assert uvmath.patch_rect(2, 2, 0, 1) == (0.0, 0.0, 0.5, 0.5)
        assert uvmath.patch_rect(2, 2, 1, 1) == (0.5, 0.0, 1.0, 0.5)

    def test_patches_tile_the_square_exactly(self):
        cols, rows = 8, 8
        area = 0.0
        for row in range(rows):
            for col in range(cols):
                u0, v0, u1, v1 = uvmath.patch_rect(cols, rows, col, row)
                area += (u1 - u0) * (v1 - v0)
        assert area == pytest.approx(1.0)

    def test_margin_insets_all_four_sides(self):
        u0, v0, u1, v1 = uvmath.patch_rect(2, 2, 0, 0, margin=0.1)
        # patch is 0.5 wide; a 0.1 margin takes 10% of 0.5 = 0.05 off each side
        assert (u0, v0, u1, v1) == pytest.approx((0.05, 0.55, 0.45, 0.95))

    def test_margin_keeps_the_rect_non_degenerate(self):
        u0, v0, u1, v1 = uvmath.patch_rect(4, 4, 3, 3, margin=0.49)
        assert u1 > u0 and v1 > v0

    @pytest.mark.parametrize("cols,rows", [(0, 4), (4, 0), (-1, 4)])
    def test_rejects_empty_grids(self, cols, rows):
        with pytest.raises(HandlerError):
            uvmath.patch_rect(cols, rows, 0, 0)

    @pytest.mark.parametrize("col,row", [(4, 0), (0, 4), (-1, 0), (0, -1)])
    def test_rejects_cells_outside_the_grid(self, col, row):
        with pytest.raises(HandlerError):
            uvmath.patch_rect(4, 4, col, row)

    @pytest.mark.parametrize("margin", [-0.01, 0.5, 1.0])
    def test_rejects_margins_that_would_invert_or_erase_the_patch(self, margin):
        with pytest.raises(HandlerError):
            uvmath.patch_rect(4, 4, 0, 0, margin=margin)


class TestResolveCell:
    def test_index_zero_is_top_left(self):
        assert uvmath.resolve_cell(0, 4, 4) == (0, 0)

    def test_index_runs_along_the_row_first(self):
        assert uvmath.resolve_cell(3, 4, 4) == (3, 0)
        assert uvmath.resolve_cell(4, 4, 4) == (0, 1)
        assert uvmath.resolve_cell(15, 4, 4) == (3, 3)

    def test_explicit_pair_passes_through(self):
        assert uvmath.resolve_cell([2, 1], 4, 4) == (2, 1)

    def test_rejects_index_past_the_end(self):
        with pytest.raises(HandlerError):
            uvmath.resolve_cell(16, 4, 4)

    def test_rejects_a_pair_of_the_wrong_length(self):
        with pytest.raises(HandlerError):
            uvmath.resolve_cell([1, 2, 3], 4, 4)

    def test_rejects_a_non_integer_index(self):
        with pytest.raises(HandlerError):
            uvmath.resolve_cell("middle", 4, 4)


class TestFitTransform:
    def test_unit_rect_is_the_identity(self):
        assert uvmath.fit_transform((0.0, 0.0, 1.0, 1.0)) == (1.0, 1.0, 0.0, 0.0)

    def test_scale_is_the_rect_size_and_offset_its_min_corner(self):
        su, sv, ou, ov = uvmath.fit_transform((0.25, 0.5, 0.5, 1.0))
        assert (su, sv, ou, ov) == pytest.approx((0.25, 0.5, 0.25, 0.5))

    def test_applying_it_maps_the_unit_square_onto_the_rect(self):
        rect = uvmath.patch_rect(8, 8, 5, 2, margin=0.05)
        su, sv, ou, ov = uvmath.fit_transform(rect)
        for u, v in ((0.0, 0.0), (1.0, 1.0), (0.5, 0.25)):
            mapped = (u * su + ou, v * sv + ov)
            assert rect[0] - 1e-9 <= mapped[0] <= rect[2] + 1e-9
            assert rect[1] - 1e-9 <= mapped[1] <= rect[3] + 1e-9
        # and the corners land exactly on the rect, not merely inside it
        assert (0.0 * su + ou, 0.0 * sv + ov) == pytest.approx(rect[:2])
        assert (1.0 * su + ou, 1.0 * sv + ov) == pytest.approx(rect[2:])
