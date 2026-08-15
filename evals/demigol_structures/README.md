# Demigol — four destructible hero buildings (**revision 3**)

**2,025 chunks, 264,000 triangles, one shared material.** Built to
`2026-08-14-structure-model-contract.md` **rev 2**, answering the notes in
Redmine #600. Regenerate with `evals/demigol_structures.py` (optionally naming
one building, e.g. `… stump` — but see the warning under *Regenerating*).

| building | footprint by storey | size (m) | storeys | chunks | frame | tris | palette |
|---|---|---|---|---|---|---|---|
| `tower` | 10×10 → 7×7 → 4×4 | 30.9 × 87.0 × 30.9 | 28 | 673 | 393 | 91,248 | cool |
| `block` | 19×19, 13×13 attic | 57.9 × 21.0 × 57.9 | 6 | 669 | 545 | 85,512 | warm |
| `slab` | 10×19 → 10×13, one end | 30.9 × 27.0 × 57.9 | 8 | 509 | 329 | 63,696 | industrial |
| `stump` | 10×10, 4×4 bulkhead | 30.9 × 18.0 × 30.9 | 5 | 174 | 116 | grimy |

**No base footprint grew.** The tower's *shrank*, from 13×13 cells to 10×10, so
every hero still drops into any plot the revision-2 one fitted and nothing in
the city layout has to move.

## What revision 3 changed

### A storey has a footprint of its own

Revision 2's four archetypes were one silhouette family, and the cause was
structural rather than artistic: `frame`, `clad` and `roof` all iterated the
whole cell grid at every storey, so a flat-topped rectangular prism was the only
shape the generator could express. A **tier** now gives a storey its own rect,
and each hero steps to a different rhythm — the tower twice and off-centre, so
its shaft gains a shoulder; the slab on one end only, because a slab that steps
both ends is just a smaller slab; the block into a set-back attic; the stump not
at all, save a stair bulkhead, because a skyline needs plain boxes or the
stepped ones stop reading as stepped.

Three rules are enforced when a building is constructed, and each one is a load
path rather than tidiness:

- a tier's column lines must land on the lines below, or its columns stand on
  cladding;
- a tier must nest inside the one below, because nothing here carries a
  cantilever;
- each tier axis is still `bays × 3 + 1` cells and at least 4.

A building that breaks one raises and produces no FBX.

### Terraces, from one roofing rule

`roof()` no longer means "cap the top storey". It means **cap every cell a
storey occupies that the storey above does not** — which at the top is the whole
footprint, exactly as before, and at a setback is a terrace. Every deck is real
cells claimed on the lattice, not ornament: collision is generated from the grid
and never from the art, so a deck modelled as decoration would be visible and
not there.

The heroes now carry roof decks at these heights, all of them standable:

- `tower` 37.5 m, 67.5 m, 85.5 m
- `block` 16.5 m, 19.5 m
- `slab` 16.5 m, 25.5 m
- `stump` 13.5 m, 16.5 m

(Deck *surface* heights in local space, where the floor plane is `y = −1.5`.)

### 44–54 triangles per chunk → 125–136

Detail still goes **only on faces a chunk can be seen from**, probed against the
occupied-cell set. What is new is vertical: mullions on glass, a panel joint on
infill, pilasters at each end of a brick face, and flanges either side of the
exposed frame's web so a stripped column reads as an I-section. A facade of
horizontal bands alone reads as a stack of shelves; it is the vertical rhythm
that makes a curtain wall look like one from 30 m.

Exposed chunks now carry **67–76 triangles per cell against a cap of 200**, up
from 38–42. It stops there deliberately. Past that point relief stops reading
and starts aliasing, which is the same failure #600 item 3 raised about brick
arriving by another road. What the headroom retires is the *argument*: curves
were declined on triangle budget while the heroes sat at a quarter of it, and at
35% that objection is dead. Curves remain deferred on blast radius alone.

### Four colourways, no new textures

All four heroes drew from the same five atlas patches, so all four were the same
blue-glass/grey/rust. The atlas has carried `amber`, `rust`, `trim`, `grime`,
`brick_dark`, `glass_bright` and `sky_glass` since revision 2 and no hero ever
sampled one. A palette table per archetype fixes it at **zero cost downstream**:
same atlas, same material, same draw call, no kit rebuild.

The manifest names each hero's palette and the patch indices it actually uses,
so the colourway is readable without diffing renders.

### Ornament may still leave the cell

Unchanged from revision 2, and stated because it is the rule the importer
warns on: the lattice constrains which **cells** a chunk occupies; the render
mesh insets 5 mm where it meets a neighbour and may outset up to 0.5 m for
ornament. Every chunk declares its own `outset_m` in the manifest.

## Verification

Everything the contract's §10 asks, executed rather than asserted:

| check | result |
|---|---|
| load path (§4a) — delete all cladding, flood-fill the frame from storey 0 | **all four stand, 0 stilt columns** |
| zero boundary / non-manifold edges | **0 failures across 2,025 chunks** |
| pivot at chunk centre | **0 failures** |
| occupied cells on the lattice, mesh within +0.5 m | **0 failures** |
| triangle budget ≤ 200 × cells | **0 over budget** |
| every column of cells tops out in a roofed cell | **0 failures** |
| names parse and agree with measured position | **0 failures** |
| render vacuity (clipped fraction) | ≤ 0.0001 on all four |

A build that fails the load-path check **exits non-zero and produces no FBX**.

## Regenerating

Run the script with **no arguments**. Naming individual buildings rebuilds only
those, and the manifest is written from the buildings that run produced — so a
partial run leaves a manifest describing three heroes beside four FBX files,
while still printing that the geometry check passed.

## Renders

The four `.png` files are lit at `intensity 1.0`, which since 2026-08-15 means
*a surface facing the key reads its own albedo*, and carry a display transform.
**Every image delivered before that date was both ~2.2 gamma too dark and ~3×
under-exposed** — if you are comparing against a revision-1 or revision-2
screenshot, the difference you see is mostly that, not an art change.

## Deviations

1. **Corner spandrels** — one cell beside each corner column is concrete rather
   than cladding, or the column would be a stilt by the contract's own
   definition. The zero stilt count is the evidence.
2. **Budget used, not exhausted** — 35% of cap, for the aliasing reason above.
3. **No curves**, deferred on tooling blast radius rather than on budget.
4. **No courtyards.** A rect per storey cannot express a hole in the plan. Say
   the word if a courtyard block is wanted and the tier becomes a list of rects.

## Settled, no longer open

The origin question from revision 1 is **closed**: min-corner cell centre at
local `y = 0`, floor plane at `y = −1.5`, no offset needed.
