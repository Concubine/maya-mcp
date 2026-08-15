# Hero revision 3: silhouette, budget, palette

**Ticket:** Redmine #600 items 2, 6, 7. Items 1, 3, 4, 5 shipped as revision 2.5
(commit `8af990e`).

**Goal:** four hero buildings that read as four archetypes from across the
district, on the same atlas, the same material and the same delivery contract.

## The problem, precisely

`Building` cannot express anything but a rectangular prism. `frame()`, `clad()`
and `roof()` all iterate the full `nx x nz` grid at every storey, so *every*
storey has the same footprint by construction. Four archetypes differ only in
their numbers - 13x13x14, 19x19x6, 10x19x8, 10x10x4 - and a 50-building skyline
built from them is a bar chart.

Two smaller misses ride along. Chunks spend 73-78 triangles of a 200-per-cell
budget, having declined curves on budget grounds while sitting on that headroom
(#600 item 6). And all four heroes draw from the same five patches, so they are
one colourway (#600 item 7) - while the atlas carries `amber`, `rust`, `trim`,
`grime`, `brick_dark`, `glass_bright` and `sky_glass`, which no hero touches.

## Architecture

### 1. Footprint per storey

`Building` gains `tiers`: a list of `(from_storey, (x0, x1, z0, z1))`, inclusive
cell bounds, in ascending storey order. Storeys from `from_storey` up to the
next tier's take that rect. Absent, a single implicit tier spans the whole grid
and every existing building behaves exactly as it does today.

`foot(y)` answers the rect for a storey. `frame()`, `clad()` and `roof()` ask it
instead of assuming the grid. The bay lines a storey uses are computed from its
own rect, offset into the parent's coordinates.

**Three validations, all fatal at construction**, because each one is a load
path that would otherwise fail silently in the game rather than in the script:

- *Column lines must land on column lines.* A tier's own bay lines, mapped to
  global coordinates, must be a subset of the parent's. Otherwise a setback
  puts columns where there are none below, and they stand on cladding.
- *Tiers must nest.* Each rect must be contained in the one below it. A tier
  that grows is a cantilever, and nothing in the contract carries one.
- *Each axis must still be `bays * 3 + 1` and at least 4 cells.* The same rule
  the whole grid obeys, because a tier is a grid.

### 2. The roof follows the footprint

`roof()` stops meaning "cap the top storey" and becomes: **for every storey,
cap the cells it occupies that the storey above does not.**

That is one rule, and it produces both things we want. At the top it covers the
whole footprint, exactly as today. At a setback it lays a *terrace* - a real
deck of real cells at the tier boundary. Several roof decks at several heights,
which is the roof-slam surface item 1 asked for, arriving as a consequence of
the silhouette rather than as a second feature.

Terraces are structurally sound for the same reason the top deck is: a terrace
ring sits on the wider tier's perimeter, which contains bay-line columns, and
the ring is contiguous concrete, so the flood-fill in `structural_report`
reaches all of it from the ground.

`Building` records the cells it roofed. The invariant "no occupied cell has
nothing above it but sky" then becomes checkable against the roof set rather
than against `y == storeys`, which stops being true the moment tiers exist.

### 3. Archetypes

| | footprint by storey | height | reads as |
|---|---|---|---|
| tower | 10x10 to storey 11, 7x7 (offset, not centred) to 21, 4x4 to 27 | 28 storeys, 84 m | a tower: 30 m base, 2.8:1, two shoulders |
| block | 19x19 to storey 4, 13x13 attic | 6 storeys, 18 m | a city block with a stepped crown and a perimeter terrace |
| slab | 10x19 to storey 4, then 10x13 - one END steps back | 8 storeys, 24 m | a slab with an asymmetric shoulder |
| stump | 10x10 for 4 storeys, then a 4x4 bulkhead | 5 storeys, 15 m | a squat industrial mass with a stair headhouse |

The tower's base *shrinks* from 13x13 to 10x10, so it still fits any plot the
old one fitted; the height is unbounded by anything in the contract and the
user's instruction was explicitly that buildings should not be capped in height.
The stump keeps a flat main mass on purpose - a skyline needs plain boxes, and
its bulkhead is what distinguishes it from a graybox.

### 4. Triangles

Detail goes on exposed faces only, as it already does. Added per role: vertical
mullions on glass, a centre joint rib on infill, end pilasters on brick, a
second flange rib on exposed frame chunks. The existing `budget_boxes` guard is
untouched and remains the thing that enforces the cap; the test that measures
the count *after* `split_oversized` is what proves the cap is real.

Target 120-160 triangles per cell against 200. Not a number to hit exactly -
the point is that the headroom argument can no longer be used to decline
geometry, per #600's note that the budget objection does not hold for heroes.

### 5. Palette

A `PALETTE` table per archetype maps role to `(patch, trim_patch)`, defaulting
to the existing `ROLE_PATCH`/`TRIM_PATCH` for anything unstated. No atlas
change, no kit rebuild, one material, one draw call:

- **tower** - cool corporate: `sky_glass` glazing, `trim` spandrels, steel.
- **block** - warm masonry: brick with `amber` string courses, `glass_bright`.
- **slab** - pale industrial: infill and glass with `rust` trim throughout.
- **stump** - grimy: `brick_dark` body, `grime` on every trim.

`chunk_boxes` reads the palette rather than the module-level tables. The
palette travels with the building, so the manifest can state which one a hero
used and an importer or an artist can see it without diffing renders.

## Testing

Headless, in `tests/test_demigol_generators.py`:

- a tier whose bay lines miss the parent's is rejected; a tier that grows is
  rejected; a tier off the `bays * 3 + 1` grid is rejected
- a building with no tiers claims exactly the cells it claims today
  (characterisation - this refactor must not move the existing archetypes'
  behaviour except where a tier says so)
- a setback produces a terrace at the tier boundary, of exactly the cells the
  storey below occupies and the storey above does not
- every archetype still passes `structural_report(...)["standing"]`, terraces
  included
- every (x, z) column tops out in a *roofed* cell
- no box exceeds one cell after splitting; every chunk stays inside the budget
- the four palettes differ from each other, and every patch they name exists in
  `kit.PATCH`

Live, on the user's Maya: the existing `evals/demigol_structures.py` run - four
FBXs, four renders, the geometry check, the manifest. The silhouette claim is
only settled by looking at the renders, so the run must produce a perspective
angle per hero, not just `top`.

## Not doing

- **Curves.** Still deferred, and #600 already says the deferral now stands on
  blast radius across `get_scene_graph`/`get_object_info`/ledger/cleanup, not
  on triangle budget. This spec removes the budget half of that argument by
  spending the headroom on boxes.
- **Courtyards or holes in the footprint.** A rect per storey cannot express a
  donut, and the perimeter logic in `clad()` would need to grow an inner ring.
  Worth it if the dev asks for a courtyard block; not worth inventing now.
- **New atlas patches.** Item 7 is answered by the seven patches already
  shipped and unused.
