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


class TestPatchArrivesAsText:
    """#640-3: `patch: 0` was refused with an error naming the form it was given.

    The MCP schema typed it as `object`, which constrains nothing and coerces
    nothing, so a client sending 0 could deliver the string "0" - and the plugin
    is reachable over raw TCP besides, where nothing validates at all. A digit
    string is an integer index that arrived as text; anything else still fails.
    """

    def test_a_digit_string_is_the_index_it_looks_like(self):
        assert uvmath.resolve_cell("0", 4, 4) == (0, 0)
        assert uvmath.resolve_cell("5", 4, 4) == (1, 1)

    def test_surrounding_whitespace_does_not_change_the_answer(self):
        assert uvmath.resolve_cell(" 3 ", 4, 4) == (3, 0)

    def test_a_pair_of_digit_strings_works_too(self):
        assert uvmath.resolve_cell(["2", "1"], 4, 4) == (2, 1)

    def test_a_text_index_past_the_end_is_still_refused(self):
        with pytest.raises(HandlerError) as exc:
            uvmath.resolve_cell("16", 4, 4)
        assert "outside" in str(exc.value)

    def test_a_word_is_still_not_an_index(self):
        for bad in ("middle", "", "1.5", "0x3", "--2"):
            with pytest.raises(HandlerError):
                uvmath.resolve_cell(bad, 4, 4)

    def test_a_float_is_still_not_an_index(self):
        # 2.5 is not a patch, and neither is True. Coercion is for TEXT that is
        # already an integer, not for widening what counts as one.
        for bad in (2.5, True, None):
            with pytest.raises(HandlerError):
                uvmath.resolve_cell(bad, 4, 4)


def _apply_fold(fold, u, v):
    """What Maya does with the six numbers: scale about the pivot, then move."""
    pivot_u, pivot_v, scale_u, scale_v, delta_u, delta_v = fold
    return (
        pivot_u + (u - pivot_u) * scale_u + delta_u,
        pivot_v + (v - pivot_v) * scale_v + delta_v,
    )


class TestFoldTransform:
    def test_folding_a_box_onto_itself_is_the_identity(self):
        box = (0.2, 0.3, 0.6, 0.9)
        fold = uvmath.fold_transform(box, box)
        assert uvmath.is_identity_fold(fold)
        assert _apply_fold(fold, 0.4, 0.5) == pytest.approx((0.4, 0.5))

    def test_the_unit_square_lands_exactly_on_an_atlas_patch(self):
        # the #638 case: a default-UV cutter folded into a chunk's patch
        rect = uvmath.patch_rect(4, 4, 0, 0, margin=0.02)
        fold = uvmath.fold_transform((0.0, 0.0, 1.0, 1.0), rect)
        assert _apply_fold(fold, 0.0, 0.0) == pytest.approx(rect[:2])
        assert _apply_fold(fold, 1.0, 1.0) == pytest.approx(rect[2:])
        assert not uvmath.is_identity_fold(fold)

    def test_an_off_square_source_still_lands_on_the_corners(self):
        src, dst = (0.5, 0.25, 0.75, 1.0), (0.005, 0.755, 0.245, 0.995)
        fold = uvmath.fold_transform(src, dst)
        assert _apply_fold(fold, src[0], src[1]) == pytest.approx(dst[:2])
        assert _apply_fold(fold, src[2], src[3]) == pytest.approx(dst[2:])
        mid = _apply_fold(fold, (src[0] + src[2]) / 2, (src[1] + src[3]) / 2)
        assert mid == pytest.approx(((dst[0] + dst[2]) / 2, (dst[1] + dst[3]) / 2))

    def test_a_degenerate_source_axis_is_centred_not_collapsed_to_a_corner(self):
        # every UV on one vertical line: there is no width to scale, so the
        # only defensible answer is the middle of the destination.
        fold = uvmath.fold_transform((0.5, 0.0, 0.5, 1.0), (0.0, 0.0, 0.25, 1.0))
        u, v = _apply_fold(fold, 0.5, 0.5)
        assert u == pytest.approx(0.125)
        assert v == pytest.approx(0.5)

    def test_a_degenerate_destination_collapses_the_source_onto_it(self):
        fold = uvmath.fold_transform((0.0, 0.0, 1.0, 1.0), (0.4, 0.4, 0.4, 0.9))
        for u in (0.0, 0.5, 1.0):
            assert _apply_fold(fold, u, 0.5)[0] == pytest.approx(0.4)

    def test_is_identity_fold_sees_a_small_but_real_move(self):
        fold = uvmath.fold_transform((0.0, 0.0, 1.0, 1.0), (0.0, 0.0, 1.0, 0.999))
        assert not uvmath.is_identity_fold(fold)


class TestRectContains:
    def test_a_box_contains_itself(self):
        box = (0.005, 0.755, 0.245, 0.995)
        assert uvmath.rect_contains(box, box)

    def test_a_cutters_full_range_does_not_fit_an_atlas_patch(self):
        assert not uvmath.rect_contains(
            (0.0, 0.0, 1.0, 1.0), (0.005, 0.755, 0.245, 0.995)
        )

    def test_escaping_on_one_side_alone_is_enough_to_fail(self):
        patch = (0.005, 0.755, 0.245, 0.995)
        assert not uvmath.rect_contains((0.005, 0.755, 0.3, 0.995), patch)
        assert not uvmath.rect_contains((0.005, 0.6, 0.245, 0.995), patch)

    def test_float_noise_within_tolerance_still_counts_as_inside(self):
        patch = (0.005, 0.755, 0.245, 0.995)
        assert uvmath.rect_contains(
            (0.005 - 1e-9, 0.755, 0.245 + 1e-9, 0.995), patch
        )


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


class TestFaceUvStats:
    """#822: a planar projection along the wrong axis collapses every face
    edge-on to it to zero UV area, and stacks the far side of a solid on the
    near side with mirrored winding. Both were silent."""

    SQUARE = [(0, 0), (1, 0), (1, 1), (0, 1)]           # counter-clockwise
    MIRRORED = [(0, 0), (0, 1), (1, 1), (1, 0)]         # clockwise
    LINE = [(0, 0), (0.5, 0), (1, 0), (0.5, 0)]         # collinear

    def test_a_healthy_face_counts_as_neither(self):
        assert uvmath.face_uv_stats([self.SQUARE]) == {"faces": 1, "zero_area": 0, "mirrored": 0}

    def test_collinear_uvs_are_zero_area(self):
        assert uvmath.face_uv_stats([self.LINE, self.SQUARE])["zero_area"] == 1

    def test_clockwise_uvs_are_mirrored(self):
        assert uvmath.face_uv_stats([self.MIRRORED, self.SQUARE])["mirrored"] == 1

    def test_a_face_with_no_uvs_is_zero_area(self):
        assert uvmath.face_uv_stats([[], self.SQUARE])["zero_area"] == 1

    def test_no_faces(self):
        assert uvmath.face_uv_stats([]) == {"faces": 0, "zero_area": 0, "mirrored": 0}


class TestThinnestAxis:
    """#822: a planar projection has to run along the axis the sheet is thin
    on. Maya's md="b" ("best plane") collapsed an X-facing sheet under a
    headless Maya while working in the GUI, so the axis is chosen here from
    the world bbox ([xmin, ymin, zmin, xmax, ymax, zmax]) instead."""

    def test_a_flat_y_sheet_projects_along_y(self):
        assert uvmath.thinnest_axis([-1, 0, -1, 1, 0, 1]) == "y"

    def test_a_sheet_standing_on_x_projects_along_x(self):
        assert uvmath.thinnest_axis([0, -1, -1, 0, 1, 1]) == "x"

    def test_a_thin_slab_counts_as_a_sheet(self):
        assert uvmath.thinnest_axis([-1, -1, -0.01, 1, 1, 0.01]) == "z"

    def test_a_cube_falls_back_to_z(self):
        assert uvmath.thinnest_axis([-0.5, -0.5, -0.5, 0.5, 0.5, 0.5]) == "z"

    def test_a_uniformly_flipped_sheet_is_not_mirrored(self):
        # measured (#822): a sheet projected from its back side has EVERY
        # face wound clockwise - a whole-mesh flip, nothing stacked on
        # anything. Mirrored means the minority winding: the far side of a
        # solid landing on the near side.
        assert uvmath.face_uv_stats([TestFaceUvStats.MIRRORED] * 16)["mirrored"] == 0

    def test_the_minority_winding_is_the_mirrored_one(self):
        assert uvmath.face_uv_stats([TestFaceUvStats.MIRRORED] * 5 + [TestFaceUvStats.SQUARE] * 2)["mirrored"] == 2
