# Hero revision 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `Building` a per-storey footprint, spend the triangle headroom,
and give each hero its own colourway - #600 items 2, 6 and 7.

**Architecture:** See `docs/superpowers/specs/2026-08-15-hero-silhouette-revision-3-design.md`.
A tier list drives `foot(y)`; `frame`/`clad`/`roof` ask it instead of assuming
the grid. Roofing becomes "cap what the storey above does not cover", which
yields terraces. Palette and detail are table edits on top.

**Tech Stack:** Python 3, pytest, the live Maya plugin on port 9877.

## Global Constraints

- `BAY = 3`; every axis is `bays * 3 + 1` cells and at least 4.
- `CELL = 3.0` m, `MAX_OUTSET = 0.5` m, `TRI_BUDGET_PER_CELL = 200`,
  `TRIS_PER_BOX = 12`.
- Chunk limits unchanged: `MAX_CELLS 48`, `MAX_SPAN 6`, `MAX_STOREYS 4`,
  `MAX_RUN` untouched - the Demigol side rejected granulating chunks.
- Heroes share the kit atlas. No new patches, no kit rebuild.
- Every patch a palette names must exist in `demigol_kit.PATCH`.
- Buildings are not capped in height (user instruction, 2026-08-15).

---

### Task 1: Tiers - the footprint per storey

**Files:**
- Modify: `evals/demigol_structures.py` (`Building.__init__`, new `foot`,
  `_tier_bay_lines`, `_check_tiers`)
- Test: `tests/test_demigol_generators.py`

**Interfaces:**
- Produces: `Building(label, nx, nz, storeys, note="", tiers=None)` where
  `tiers` is `[(from_storey, (x0, x1, z0, z1)), ...]` ascending, inclusive
  bounds. `Building.foot(y) -> (x0, x1, z0, z1)`. `tiers=None` means one
  implicit tier covering the whole grid.

- [ ] **Step 1: Write the failing tests** - a tier whose bay lines are not a
  subset of the parent's raises; a tier that grows raises; a tier off the
  `bays*3+1` grid raises; `foot(y)` returns the whole grid when `tiers=None`;
  `foot(y)` returns the right rect either side of a boundary.
- [ ] **Step 2:** `pytest tests/test_demigol_generators.py -k Tier -v` - FAIL.
- [ ] **Step 3: Implement.** Validation runs in `__init__` so a bad tier can
  never reach the game. Error messages name the tier and the offending axis.
- [ ] **Step 4:** tests PASS.
- [ ] **Step 5: Commit.**

---

### Task 2: frame() and clad() honour the footprint

**Files:**
- Modify: `evals/demigol_structures.py` (`frame`, `_interior`,
  `_corner_spandrels`, `clad`)
- Test: `tests/test_demigol_generators.py`

**Interfaces:**
- Consumes: `foot(y)` from Task 1.
- Produces: same signatures; behaviour identical when no tiers are given.

- [ ] **Step 1: Write the failing tests** - characterisation first: a building
  with no tiers claims *exactly* the same cell dict as before the change (pin
  the count and a sample of roles). Then: with a tier, no cell is claimed
  outside `foot(y)` at that storey; the setback storey's columns sit directly
  above columns of the storey below.
- [ ] **Step 2:** run - FAIL.
- [ ] **Step 3: Implement.** `_interior` and `_corner_spandrels` take a rect.
  Bay lines per storey come from `_tier_bay_lines`.
- [ ] **Step 4:** tests PASS, and the whole file passes - the existing frame
  and cladding tests are the characterisation.
- [ ] **Step 5: Commit.**

---

### Task 3: roof() follows the footprint, and terraces appear

**Files:**
- Modify: `evals/demigol_structures.py` (`roof`, `Building.__init__` gains
  `self.roofed`)
- Test: `tests/test_demigol_generators.py`

**Interfaces:**
- Produces: `Building.roofed` - the set of `(x, y, z)` cells `roof()` claimed.

- [ ] **Step 1: Write the failing tests** - a setback building gets a terrace
  at the tier boundary of exactly `foot(y) - foot(y+1)`; the top deck still
  covers the whole top footprint; every `(x, z)` column tops out in a cell in
  `self.roofed`; roofing twice still raises; a terraced building still passes
  `structural_report(...)["standing"]`.
- [ ] **Step 2:** run - FAIL.
- [ ] **Step 3: Implement** the single rule: for `y` in `0..storeys`, claim
  concrete at `(x, y+1, z)` for every cell in `foot(y)` not in `foot(y+1)`,
  where `foot(storeys)` is empty.
- [ ] **Step 4:** tests PASS. Update
  `test_no_occupied_cell_is_left_with_nothing_above_it_but_sky` to assert
  against `roofed` rather than `y == storeys`, which tiers make false.
- [ ] **Step 5: Commit.**

---

### Task 4: The four archetypes

**Files:**
- Modify: `evals/demigol_structures.py` (`tower`, `block`, `slab`, `stump`)
- Test: `tests/test_demigol_generators.py`

- [ ] **Step 1: Write the failing test** - each archetype has a distinct
  footprint *profile* (the sequence of `foot(y)` widths); no two archetypes
  share one; every archetype still stands; the tower is at least twice as tall
  as it is wide.
- [ ] **Step 2:** run - FAIL.
- [ ] **Step 3: Implement** the table from the spec: tower 10x10/7x7/4x4 over
  28 storeys, block 19x19 with a 13x13 attic, slab 10x19 stepping to 10x13 on
  one end, stump 10x10 with a 4x4 bulkhead.
- [ ] **Step 4:** tests PASS; the budget and outset tests still pass on the new
  shapes.
- [ ] **Step 5: Commit.**

---

### Task 5: Palette per archetype

**Files:**
- Modify: `evals/demigol_structures.py` (`PALETTES`, `Building.palette`,
  `chunk_boxes`, `_face_boxes`, the manifest writer)
- Test: `tests/test_demigol_generators.py`

**Interfaces:**
- Produces: `PALETTES: dict[str, dict[str, tuple[str, str]]]` - archetype ->
  role -> `(patch, trim_patch)`. `Building.palette_name`, and
  `chunk_boxes(ch, occupied, storeys, palette=None)`.

- [ ] **Step 1: Write the failing tests** - every patch every palette names
  exists in `kit.PATCH`; no two archetypes produce the same set of patches; a
  palette omitting a role falls back to `ROLE_PATCH`/`TRIM_PATCH`; the manifest
  states the palette name.
- [ ] **Step 2:** run - FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** tests PASS.
- [ ] **Step 5: Commit.**

---

### Task 6: Spend the triangle headroom

**Files:**
- Modify: `evals/demigol_structures.py` (`_face_boxes`)
- Test: `tests/test_demigol_generators.py`

- [ ] **Step 1: Write the failing test** - the mean triangles per cell across
  every archetype's exposed chunks is at least 110 (it is 73-78 today), while
  every chunk stays inside its 200-per-cell budget after `split_oversized`.
- [ ] **Step 2:** run - FAIL on the floor, PASS on the cap.
- [ ] **Step 3: Implement** mullions on glass, a centre rib on infill, end
  pilasters on brick, a flange rib on exposed frame.
- [ ] **Step 4:** tests PASS. Re-check the outset tests - new relief must stay
  inside `MAX_OUTSET`.
- [ ] **Step 5: Commit.**

---

### Task 7: The live run

**Files:**
- Modify: `evals/demigol_structures.py` (render angles, if `top` is the only
  one - a silhouette claim cannot be judged from above)
- Produces: `evals/demigol_structures/*.fbx`, `*.png`, `manifest.json`

- [ ] **Step 1:** Full headless suite green first.
  Run: `uv run pytest -q`
- [ ] **Step 2:** Sync the deployed plugin if it is stale.
  Run: `uv run python maya_plugin/install.py --yes`
- [ ] **Step 3:** Build all four, in one invocation - a partial run writes a
  partial manifest (the trap found on 2026-08-15).
  Run: `MAYA_MCP_PORT=9877 uv run python evals/demigol_structures.py`
  Expected: four FBXs, `geometry check: all four clean`, manifest listing all
  four with a `material` block and a palette name.
- [ ] **Step 4:** Look at the renders. The four must be distinguishable in
  silhouette *and* in colour at a glance. If they are not, this plan failed
  regardless of what the tests say.
- [ ] **Step 5:** Report measured numbers on #600: triangles per cell, chunk
  counts, heights, and what each hero now reads as. Commit.
