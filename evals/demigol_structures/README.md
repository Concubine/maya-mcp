# Demigol structure package — 4 buildings

Built against the **STRUCTURE MODEL CONTRACT**. Every building is authored *as* a
set of chunk meshes on a 3 m lattice — nothing is welded and cut up afterwards.

Generator: `evals/demigol_structures.py` in the `maya-mcp` repo. Regenerating is
one command; the design lives in ~120 lines of cell arithmetic, so footprints,
storey counts and role distribution are cheap to change.

| building | footprint (cells) | size (m) | storeys | chunks | tris | tris/chunk |
|---|---|---|---|---|---|---|
| `campanile` | 4 × 4 | 12 × 42 × 12 | 14 | 154 | 1 848 | 12 |
| `framed_tower` | 10 × 10 | 30 × 36 × 30 | 12 | 384 | 4 608 | 12 |
| `warehouse` | 19 × 10 | 57 × 15 × 30 | 5 | 286 | 3 432 | 12 |
| `gatehouse` | 19 × 7 | 57 × 15 × 21 | 5 | 216 | 2 592 | 12 |

1 040 chunks, 12 480 triangles total. Budget is ≤200 tris per 1-cell chunk; every
chunk is a box at 12.

## Conformance

- **Units** — metres, Y-up. The scene is switched to `linear='m'` before anything
  is created, and FBX export is pinned to metres and Y-up explicitly.
- **Lattice** — cell = 3 m. Chunks are positioned from *cell indices only*;
  metres are derived at the very end. Straddling a boundary is not expressible
  in the generator rather than merely avoided.
- **Footprints** — every horizontal axis is (bays × 3 + 1) cells. Bay pitch 9 m.
- **Chunks** — every chunk is a `polyCube`: closed, watertight, 12 triangles.
- **Pivots** — cubes are built centred on the origin and then *moved*, never
  scaled. Each transform's pivot is already the chunk's own centre, scale stays
  `(1,1,1)` and rotation stays zero, so there is nothing left to freeze.
- **History** — created with `ch=False`; none exists.
- **Limits** — 48 cells / 6 span / 4 storeys asserted per chunk at emit time.
  This is not decorative: it rejected a 3 × 7 lintel during authoring, which was
  then split into two beams that each fall as their own body.
- **Names** — `<role>_x##_y##_z##`, generated from the same cell indices that
  place the geometry, so a name cannot drift from its position.
- **Materials** — five flat lambert colours named exactly for the roles. No
  textures, no authored materials, nothing to flag.

### Self-check

After building, every chunk is re-measured **in the scene** and asserted against
the contract — not against the intent that produced it:

closed (V−E+F = 2) · bounds on 3 m boundaries · pivot at chunk centre ·
scale `(1,1,1)` and rotation zero · name parses **and agrees with measured
position** · within 48 cells / 6 span / 4 storeys.

All four report clean. The check runs on every regeneration, so it is a gate
rather than a one-off.

## Two readings I had to choose — please confirm

Both are flagged in `manifest.json` under `deviations`.

1. **Multi-cell chunk naming.** A chunk spanning several cells is named for its
   **min-corner** cell. The contract defines x/z as "cell coords from the min
   corner", which is unambiguous for a 1-cell chunk and needs a choice once a
   chunk spans cells. If you want centre-naming, it is a one-line change and the
   self-check will enforce it.
2. **Vertical sense of the origin.** I placed the min-corner cell **centre** at
   local `y = 0`, so the floor plane sits at `y = −1.5`. The other reading puts
   the floor at `y = 0` and the origin 1.5 m above it. If that is the one you
   meant, every building needs a single **+1.5 m Y offset** — no regeneration.

## Known issue: coplanar faces will z-fight

Adjacent chunks share exact faces, because bounds must land on cell boundaries.
In the preview renders this shows as speckling across the elevations, and it will
flicker in Unity the same way.

Contract point 4 says chunks *may interpenetrate deeply — encouraged*, which is
the intended escape, but it sits in tension with "bounds must land ON cell
boundaries". I kept the bounds exact, because that is the rule the placement and
flood-fill logic depends on. Options on your side, cheapest first:

- shrink the **render** mesh a few mm inside the collision/lattice bounds;
- overlap adjacent chunks by a whole cell where the design allows;
- accept it for interior faces that are never both visible.

Worth a decision before more buildings are made, since it affects authoring.

## What is deliberately *not* here

- **No taper or curve anywhere.** A tapered chunk cannot have bounds on cell
  boundaries, so lattice conformance won it. Character comes from massing and
  role distribution instead. If you want curved or tapered chunks, the rule that
  needs relaxing is "bounds on cell boundaries" — say so and it is available.
- **No LOD.** Contract says one for now.
- **No interior detail.** Floors are slabs; there are no stairs, cores or
  partitions. Say if interiors matter once the golem can enter.

## The four, and how each fails

- **`campanile`** — 12 × 12 m, 42 m tall, brick. Slenderness ~3.5:1, so it goes
  over as one piece. Top two storeys swap brick for steel corners and glass
  infill, which puts a readable shear line under the belfry.
- **`framed_tower`** — the canonical framed block. Steel on 9 m bay lines,
  concrete floors, curtain infill hung between, glazed band every third storey.
  Cut a column line and everything the frame was carrying drops.
- **`warehouse`** — long and low, brick on a steel frame, with a sawtooth roof of
  single-cell ridges above the roof slab that shed individually.
- **`gatehouse`** — a 3-cell void driven through the centre bay at ground level,
  spanned by two concrete lintels at storey 1. The only one whose failure is not
  straight down: take a flanking pier and the span over the void comes with it.
