"""The Demigol asset generators, tested WITHOUT Maya.

Both generators were built live against a Maya session and had no unit tests
at all - every claim about them was verified in-scene, which meant no fast
feedback loop and no way to catch an arithmetic regression before a 20-minute
build. They import cleanly headless (live_call opens no socket at module
scope, and build_atlas_maps imports numpy inside the function), so the pure
authoring surface is testable here: cell claiming, chunk merging, the load
path, the box arithmetic, and the manifest fields a consumer reads.

What is NOT tested here is anything Maya measures - triangle counts, boundary
edges, UV bounds. Those stay in the live gate, which is the only thing that
can measure them.
"""

import os
import sys

import pytest

_EVALS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "evals")
if _EVALS not in sys.path:
    sys.path.insert(0, _EVALS)

import demigol_kit as kit          # noqa: E402
import demigol_structures as st    # noqa: E402


# ============================================================ the outset rule

class TestChunkOutset:
    """#600 item 4: the heroes use up to 0.47 m of outset and declare none.

    The kit has declared its since revision 2; this is the same computation
    generalised from a one-cell piece centred on the origin to a chunk of
    sx x sy x sz cells, whose boxes are authored in its own local space.
    """

    def test_a_body_only_chunk_declares_no_outset(self):
        boxes = [{"pos": [0.0, 0.0, 0.0], "dim": [2.99, 2.99, 2.99]}]
        assert st.chunk_outset(boxes, 1, 1, 1) == 0.0

    def test_a_box_reaching_past_the_cell_block_declares_the_difference(self):
        # half-extent of a 1-cell chunk is 1.5; this reaches 1.57.
        boxes = [{"pos": [0.0, 0.0, 0.0], "dim": [2.99, 2.99, 2.99]},
                 {"pos": [-1.47, 0.0, 0.0], "dim": [0.2, 2.99, 1.64]}]
        assert st.chunk_outset(boxes, 1, 1, 1) == pytest.approx(0.07)

    def test_the_half_extent_scales_with_a_multi_cell_chunk(self):
        # A 4-storey chunk is 6.0 half-high, so a box reaching 5.995 does NOT
        # oversail - the naive one-cell rule would have called this 4.495.
        boxes = [{"pos": [0.0, 0.0, 0.0], "dim": [2.99, 11.99, 2.99]}]
        assert st.chunk_outset(boxes, 1, 4, 1) == 0.0

    def test_the_largest_oversail_on_any_axis_wins(self):
        boxes = [{"pos": [0.0, 0.0, 1.6], "dim": [1.0, 1.0, 1.0]},   # z -> 0.6
                 {"pos": [1.55, 0.0, 0.0], "dim": [1.0, 1.0, 1.0]}]  # x -> 0.55
        assert st.chunk_outset(boxes, 1, 1, 1) == pytest.approx(0.6)

    def test_an_empty_box_list_is_no_outset_rather_than_an_error(self):
        assert st.chunk_outset([], 1, 1, 1) == 0.0


class TestOutsetReachesTheManifest:
    """The value is useless unless a consumer can read it per chunk."""

    def test_as_dict_carries_outset_m(self):
        ch = st.Chunk("steel", 0, 0, 0)
        d = ch.as_dict(outset_m=0.07)
        assert d["outset_m"] == 0.07

    def test_as_dict_defaults_to_zero_so_the_field_is_never_absent(self):
        # JsonUtility has no notion of a missing field; an absent key would
        # deserialize as 0.0 anyway. Emitting it explicitly makes the manifest
        # state the value rather than imply it.
        assert st.Chunk("steel", 0, 0, 0).as_dict()["outset_m"] == 0.0

    def test_outset_m_is_a_field_on_the_chunk_entry_not_a_keyed_map(self):
        # DeliveryManifest is a [Serializable] DTO parsed by plain JsonUtility
        # with no Newtonsoft. JsonUtility cannot deserialize dictionaries, so a
        # name-keyed outset map would parse as nothing and fail silently.
        d = st.Chunk("steel", 0, 0, 0).as_dict(outset_m=0.3)
        assert isinstance(d["outset_m"], float)
        assert not any(isinstance(v, dict) for v in d.values())


class TestEveryHeroChunkDeclaresItsOutset:
    """The end-to-end shape of item 4, on a real building."""

    @pytest.fixture(scope="class")
    @classmethod
    def built(cls):
        b = st.tower()
        chunks = b.chunks()
        occupied = set()
        for c in chunks:
            occupied.update(c.cells_occupied())
        return b, chunks, occupied

    def test_declared_outset_never_exceeds_the_allowance(self, built):
        b, chunks, occupied = built
        for c in chunks:
            boxes = st.chunk_boxes(c, occupied, b.storeys)
            out = st.chunk_outset(boxes, c.sx, c.sy, c.sz)
            assert out <= st.MAX_OUTSET + 1e-9, "%s oversails %.4f" % (c.name, out)

    def test_some_chunk_actually_uses_the_allowance(self, built):
        # Guards against the rule passing trivially because every chunk is a
        # bare box - which is exactly what revision 1 was.
        b, chunks, occupied = built
        worst = max(st.chunk_outset(st.chunk_boxes(c, occupied, b.storeys),
                                    c.sx, c.sy, c.sz)
                    for c in chunks)
        assert worst > 0.0

    def test_declared_outset_agrees_with_the_measured_reach(self, built):
        b, chunks, occupied = built
        for c in chunks[:200]:
            boxes = st.chunk_boxes(c, occupied, b.storeys)
            if not boxes:
                continue
            declared = st.chunk_outset(boxes, c.sx, c.sy, c.sz)
            half = [st.CELL * s / 2.0 for s in (c.sx, c.sy, c.sz)]
            measured = max(abs(bx["pos"][i]) + bx["dim"][i] / 2.0 - half[i]
                           for bx in boxes for i in range(3))
            assert declared == pytest.approx(max(0.0, measured), abs=1e-4)


# ============================================================ the hero material

class TestHeroMaterialBlock:
    """#600 item 5: the README says the heroes sample the kit atlas, and the
    manifest never names it, so an importer cannot wire it without hardcoding
    cross-delivery knowledge."""

    def test_the_block_names_the_delivery_it_borrows_from(self):
        m = st.hero_material_block()
        assert m["shared_with"] == "demigol_kit"

    def test_the_block_names_all_three_maps(self):
        maps = st.hero_material_block()["maps"]
        assert maps["albedo"] == "kit_albedo.png"
        assert maps["normal"] == "kit_normal.png"
        assert maps["mask"] == "kit_mask.png"

    def test_the_block_states_the_atlas_layout_it_samples_at(self):
        m = st.hero_material_block()
        assert m["atlas_px"] == kit.ATLAS_PX
        assert m["atlas_grid"] == [kit.ATLAS_COLS, kit.ATLAS_ROWS]

    def test_the_block_records_that_smoothness_is_in_alpha(self):
        # URP Lit's _MetallicGlossMap reads R = metallic, A = smoothness. The
        # Demigol side named this the single most likely silent regression, so
        # the delivery states the packing rather than leaving it to a README.
        assert "A" in st.hero_material_block()["mask_channels"]["smoothness"]

    def test_the_block_is_json_utility_safe(self):
        # Objects and numeric arrays only - no name-keyed map where the
        # importer expects to iterate.
        m = st.hero_material_block()
        assert isinstance(m["atlas_grid"], list)
        assert all(isinstance(v, (int, float)) for v in m["atlas_grid"])


# ============================================ characterisation: the cell grid

class TestBuildingCellClaiming:
    """`put` is the single mutation point, and a double claim is fatal by
    design - that is what makes the manifest an unambiguous statement of what
    each cell is made of."""

    def test_a_second_claim_on_one_cell_is_an_error(self):
        b = st.Building("t", 4, 4, 2)
        b.put("steel", 0, 0, 0)
        with pytest.raises(ValueError, match="claimed twice"):
            b.put("concrete", 0, 0, 0)

    def test_an_unknown_role_is_an_error(self):
        b = st.Building("t", 4, 4, 2)
        with pytest.raises(ValueError, match="unknown role"):
            b.put("timber", 0, 0, 0)

    def test_an_axis_that_is_not_bays_times_three_plus_one_is_rejected(self):
        with pytest.raises(ValueError, match="is not"):
            st.Building("t", 5, 4, 2)

    def test_cladding_never_overwrites_the_frame(self):
        b = st.Building("t", 7, 7, 2)
        b.frame()
        before = dict(b.cells)
        b.clad(lambda y: "brick")
        for key, role in before.items():
            assert b.cells[key] == role

    def test_cladding_is_perimeter_only(self):
        b = st.Building("t", 7, 7, 2)
        b.frame()
        b.clad(lambda y: "brick")
        for (x, y, z), role in b.cells.items():
            if role == "brick":
                assert x in (0, 6) or z in (0, 6)


class TestChunkMerging:
    """`MAX_RUN` is what makes a chunk the unit of destruction: steel merges to
    four storeys so the frame falls in large sections, glass never merges so a
    pane cannot come off in pairs. Confirmed with the Demigol side 2026-08-15
    and deliberately NOT granulated to one cell."""

    def test_steel_merges_vertically(self):
        b = st.Building("t", 7, 7, 4)
        b.frame()
        steel = [c for c in b.chunks() if c.role == "steel"]
        assert any(c.sy > 1 for c in steel)

    def test_steel_never_merges_past_its_run_limit(self):
        b = st.Building("t", 7, 7, 12)
        b.frame()
        for c in b.chunks():
            if c.role == "steel":
                assert c.sy <= st.MAX_RUN["steel"]

    def test_glass_never_merges(self):
        b = st.Building("t", 7, 7, 2)
        b.frame()
        b.clad(lambda y: "glass")
        for c in b.chunks():
            if c.role == "glass":
                assert (c.sx, c.sy, c.sz) == (1, 1, 1)

    def test_every_claimed_cell_lands_in_exactly_one_chunk(self):
        b = st.tower()
        seen = {}
        for c in b.chunks():
            for cell in c.cells_occupied():
                assert cell not in seen, "%s claimed twice" % (cell,)
                seen[cell] = c.role
        assert seen == b.cells

    def test_a_chunk_is_named_for_its_min_corner_cell(self):
        ch = st.Chunk("steel", 3, 1, 7, sx=2, sy=4, sz=1)
        assert ch.name == "steel_x03_y01_z07"


class TestLoadPath:
    """The one-action self-check: discard all cladding, flood-fill the frame
    from storey 0, and refuse to produce an FBX if anything floats."""

    def test_all_four_archetypes_stand(self):
        for _, fn, _ in st.BUILDINGS:
            b = fn()
            report = st.structural_report(b.chunks())
            assert report["standing"], "%s: %s" % (b.label, report)

    def test_all_four_archetypes_have_zero_stilt_columns(self):
        for _, fn, _ in st.BUILDINGS:
            b = fn()
            assert st.structural_report(b.chunks())["stilts"] == []

    def test_a_frame_chunk_with_no_path_to_the_ground_is_caught(self):
        # A lone column segment starting at storey 5. Note the flood fill seeds
        # from ANY structural chunk at y == 0, concrete beams included - so
        # stranding one requires removing the beam grid too, not just the steel
        # below it.
        report = st.structural_report([st.Chunk("steel", 0, 5, 0)])
        assert report["floating"] == ["steel_x00_y05_z00"]
        assert not report["standing"]

    def test_cladding_is_ignored_by_the_load_path(self):
        # Cladding is discarded before the fill, so a building made only of
        # cladding has no frame to float - it is vacuously standing. This pins
        # that the check measures the FRAME, not the building.
        report = st.structural_report([st.Chunk("brick", 0, 4, 0)])
        assert report["frame_chunks"] == 0
        assert report["floating"] == []

    def test_glass_wider_than_two_cells_is_refused(self):
        report = st.structural_report([st.Chunk("glass", 0, 0, 0, sx=3)])
        assert report["wide_glass"]
        assert not report["standing"]


# ===================================================================== roofs

class TestRoofFraming:
    """#600 item 1, the top-ranked miss: every render is an open egg-crate.

    The cause was hero-side and total - `_exposure` computed `faces["top"]`
    and the crown band read it, but no box was ever placed on the +Y face
    itself and no cell was ever claimed above the top storey. The building
    simply stopped.

    Per the user's direction the hero FRAMES the roof (beams on the bay lines
    plus a deck substrate, in frame roles, structural, collapses) and the kit
    SHEATHES it (finish, parapet, plant, cladding roles, peels off). This is
    the existing frame/cladding split rotated into the horizontal.
    """

    def test_roof_claims_a_storey_above_the_top_one(self):
        b = st.Building("t", 7, 7, 3)
        b.frame()
        b.roof()
        assert any(y == 3 for (_, y, _) in b.cells)

    def test_the_roof_is_built_from_frame_roles_not_cladding(self):
        b = st.Building("t", 7, 7, 3)
        b.frame()
        b.roof()
        for (_, y, _), role in b.cells.items():
            if y == 3:
                assert role in st.STRUCTURAL, role

    def test_the_roof_covers_the_whole_footprint(self):
        b = st.Building("t", 7, 7, 2)
        b.frame()
        b.roof()
        roofed = {(x, z) for (x, y, z) in b.cells if y == 2}
        assert roofed == {(x, z) for x in range(7) for z in range(7)}

    def test_the_roof_does_not_disturb_the_storeys_below(self):
        b = st.Building("t", 7, 7, 3)
        b.frame()
        before = {k: v for k, v in b.cells.items() if k[1] < 3}
        b.roof()
        assert {k: v for k, v in b.cells.items() if k[1] < 3} == before

    def test_roofing_twice_is_an_error_rather_than_a_silent_overwrite(self):
        b = st.Building("t", 7, 7, 2)
        b.frame()
        b.roof()
        with pytest.raises(ValueError, match="claimed twice"):
            b.roof()

    def test_the_roof_ties_the_columns_it_sits_on(self):
        # Beams land on the bay lines, so every column below has structure
        # directly above it - the roof is the top tie, not a hat.
        b = st.Building("t", 7, 7, 2)
        b.frame()
        b.roof()
        for x in b.bx:
            for z in b.bz:
                assert (x, 2, z) in b.cells


class TestRoofedBuildingsStillStand:
    def test_a_roofed_building_passes_the_load_path(self):
        b = st.Building("t", 7, 7, 3)
        b.frame()
        b.roof()
        b.clad(lambda y: "brick")
        assert st.structural_report(b.chunks())["standing"]

    def test_the_roof_merges_into_runs_rather_than_per_cell_confetti(self):
        # A floor that comes down in slabs reads as a floor collapsing; the
        # same floor as 169 tiles reads as confetti. MAX_RUN concrete = 4.
        b = st.Building("t", 13, 13, 2)
        b.frame()
        b.roof()
        roof_chunks = [c for c in b.chunks() if c.y == 2]
        assert roof_chunks
        assert any(c.sx > 1 or c.sz > 1 for c in roof_chunks)
        assert len(roof_chunks) < 169

    def test_only_the_roof_reports_an_exposed_top_face(self):
        # Revision 2 decided `top` by arithmetic on the storey count, which was
        # true only because nothing was ever built above the top storey. Once
        # roof() claims a storey, that test crowns the roof AND the storey
        # under it. Probing +Y is the same question the vertical faces ask.
        b = st.Building("t", 7, 7, 3)
        b.frame()
        b.roof()
        chunks = b.chunks()
        occupied = set()
        for c in chunks:
            occupied.update(c.cells_occupied())
        for c in chunks:
            expo = st._exposure(c, occupied, b.storeys)
            if c.y + c.sy - 1 < 3:
                assert not expo["top"], "%s crowned under a roof" % c.name

    def test_a_buried_chunk_has_no_exposed_face_at_all(self):
        b = st.Building("t", 13, 13, 3)
        b.frame()
        b.roof()
        b.clad(lambda y: "brick")
        chunks = b.chunks()
        occupied = set()
        for c in chunks:
            occupied.update(c.cells_occupied())
        buried = [c for c in chunks
                  if not any(st._exposure(c, occupied, b.storeys)[k]
                             for k in ("nx", "px", "nz", "pz", "top"))]
        assert buried, "nothing is buried - the exposure probe is not working"

    def test_no_occupied_cell_is_left_with_nothing_above_it_but_sky(self):
        # V5 from the revision 3 spec, and the check that would have failed
        # revision 2 outright. Every column of cells must top out in a roof
        # cell rather than in whatever the top storey happened to be.
        b = st.Building("t", 7, 7, 3)
        b.frame()
        b.roof()
        b.clad(lambda y: "brick")
        tops = {}
        for (x, y, z) in b.cells:
            tops[(x, z)] = max(tops.get((x, z), -1), y)
        for (x, z), y in tops.items():
            assert y == 3, "column %s tops out at storey %d" % ((x, z), y)


class TestBoxesFitTheirAtlasPatch:
    """Found by the live gate, not by any test: every hero chunk's UVs spilled
    outside its atlas patch, worst 2.94x, and the worst was a brick WALL - so
    this predates revision 3 and shipped in revision 2.

    Each box is packed into its patch individually, before combine, at a fixed
    `world_scale` so texel density is constant. A box LARGER than that envelope
    cannot fit and bleeds into neighbouring patches. Kit pieces are one cell so
    they always fit; hero boxes span whole chunks, up to 4 cells.

    Splitting at cell boundaries fixes it without touching density, MAX_RUN, or
    the destruction unit - the pieces combine back into one mesh.
    """

    def test_a_box_within_one_cell_is_left_alone(self):
        boxes = [{"pos": [0.0, 0.0, 0.0], "dim": [2.99, 2.99, 2.99], "patch": "brick"}]
        assert st.split_oversized(boxes) == boxes

    def test_a_long_box_is_split_into_cell_sized_pieces(self):
        boxes = [{"pos": [0.0, 0.0, 0.0], "dim": [11.99, 2.99, 2.99], "patch": "concrete"}]
        out = st.split_oversized(boxes)
        assert len(out) == 4
        assert all(b["dim"][0] <= st.CELL + 1e-9 for b in out)

    def test_splitting_preserves_the_occupied_volume(self):
        boxes = [{"pos": [0.0, 0.0, 0.0], "dim": [11.99, 2.99, 2.99], "patch": "concrete"}]
        out = st.split_oversized(boxes)
        lo = min(b["pos"][0] - b["dim"][0] / 2.0 for b in out)
        hi = max(b["pos"][0] + b["dim"][0] / 2.0 for b in out)
        assert lo == pytest.approx(-11.99 / 2.0)
        assert hi == pytest.approx(11.99 / 2.0)

    def test_splitting_keeps_the_patch(self):
        boxes = [{"pos": [0.0, 0.0, 0.0], "dim": [11.99, 2.99, 2.99], "patch": "concrete"}]
        assert all(b["patch"] == "concrete" for b in st.split_oversized(boxes))

    def test_a_box_long_on_two_axes_splits_on_both(self):
        boxes = [{"pos": [0.0, 0.0, 0.0], "dim": [5.99, 2.99, 8.99], "patch": "concrete"}]
        out = st.split_oversized(boxes)
        assert len(out) == 2 * 3

    def test_no_box_in_any_archetype_exceeds_one_cell(self):
        for _, fn, _ in st.BUILDINGS:
            b = fn()
            chunks = b.chunks()
            occupied = set()
            for c in chunks:
                occupied.update(c.cells_occupied())
            for c in chunks:
                for bx in st.chunk_boxes(c, occupied, b.storeys):
                    for i in range(3):
                        assert bx["dim"][i] <= st.CELL + 1e-6, (
                            "%s box %.3f on axis %d" % (c.name, bx["dim"][i], i))

    def test_chunks_stay_within_the_triangle_budget_after_splitting(self):
        for _, fn, _ in st.BUILDINGS:
            b = fn()
            chunks = b.chunks()
            occupied = set()
            for c in chunks:
                occupied.update(c.cells_occupied())
            for c in chunks:
                n = len(st.chunk_boxes(c, occupied, b.storeys))
                budget = c.sx * c.sy * c.sz * st.TRI_BUDGET_PER_CELL
                assert n * st.TRIS_PER_BOX <= budget, c.name


# ================================================================ the kit side

class TestKitPieces:
    def test_every_piece_name_parses(self):
        for name in kit.PIECES():
            assert kit.parse_name(name) is not None, name

    def test_every_referenced_patch_exists(self):
        for name, boxes in kit.PIECES().items():
            for bx in boxes:
                assert bx["patch"] in kit.PATCH, "%s -> %s" % (name, bx["patch"])

    def test_every_piece_is_within_its_triangle_budget(self):
        for name, boxes in kit.PIECES().items():
            role, context, _ = kit.parse_name(name)
            budget = kit.TRI_BUDGET.get(
                context, kit.TRI_BUDGET.get(role, kit.TRI_BUDGET_DEFAULT))
            assert len(boxes) * kit.TRIS_PER_BOX <= budget, name

    def test_no_piece_leaves_the_outset_allowance(self):
        for name, boxes in kit.PIECES().items():
            reach = max(abs(bx["pos"][i]) + bx["dim"][i] / 2.0
                        for bx in boxes for i in range(3))
            assert reach <= kit.OUT + 1e-6, "%s reaches %.4f" % (name, reach)

    def test_the_atlas_grid_is_exactly_filled(self):
        assert len(kit.PATCH) == kit.ATLAS_COLS * kit.ATLAS_ROWS
        assert sorted(v[0] for v in kit.PATCH.values()) == list(range(len(kit.PATCH)))


class TestKitAtlasArithmetic:
    """These numbers are quoted in the contract and the README, so a change
    that moves them silently is a documentation bug as well as an art one."""

    def test_pixels_per_metre_derives_from_the_patch_and_world_scale(self):
        assert kit.PX_PER_METRE == pytest.approx(
            (kit.ATLAS_PX / kit.ATLAS_COLS) / kit.WORLD_SCALE)

    def test_courses_per_patch_derives_from_courses_per_metre(self):
        assert kit.COURSES_PER_PATCH == pytest.approx(
            kit.COURSES_PER_METRE * kit.WORLD_SCALE)

    def test_a_brick_course_is_thick_enough_to_survive_a_mortar_bed(self):
        # The bed is 0.16 of a course. Below ~2 px it stops reading as mortar
        # and becomes the corduroy #600 item 3 complains about.
        course_px = (kit.ATLAS_PX // kit.ATLAS_COLS) / kit.COURSES_PER_PATCH
        assert course_px * 0.16 >= 2.0, (
            "mortar bed is %.2f px at %.1f courses/m"
            % (course_px * 0.16, kit.COURSES_PER_METRE))
