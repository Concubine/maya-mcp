# Demigol — four destructible hero buildings (**revision 2**)

**2,034 chunks, 94,344 triangles, one shared material.** Built to
`2026-08-14-structure-model-contract.md` **rev 2**. Regenerate with
`evals/demigol_structures.py` (optionally naming one building, e.g. `… stump`).

| building | archetype | cells | size (m) | chunks | frame | tris | tris/chunk |
|---|---|---|---|---|---|---|---|
| `tower` | Tower | 13 × 13 × 14 | 39.9 × 42.0 × 39.9 | 772 | 492 | 35,040 | 45 |
| `block` | Block | 19 × 19 × 6 | 57.9 × 18.0 × 57.9 | 622 | 482 | 27,576 | 44 |
| `slab` | Slab | 10 × 19 × 8 | 30.9 × 24.0 × 57.9 | 504 | 304 | 24,336 | 48 |
| `stump` | Stump | 10 × 10 × 4 | 30.9 × 12.0 × 30.9 | 136 | 80 | 7,392 | 54 |

## What revision 2 changed

### The budget is now spent — 12 tris/chunk → 44–54

Revision 1 made every chunk a plain box, so all four buildings rendered as the same
graybox cubes the city already draws. They were excellent structurally and
placeholders visually; the contract said so, and it was right.

Detail is placed **only on faces a chunk can actually be seen from**, computed by
probing each chunk's neighbours in the occupied-cell set. Interior and buried frame
chunks stay a single box — they are invisible until the golem opens the building, at
which point what matters is that something came off, not whether it had a cornice.

Per role, on an exposed face: brick gets string courses and sills, `infill` gets
mullion rails, glass gets head and cill trims, and steel/concrete get a flange band
that reads wherever cladding has been torn away. Every exposed chunk on the top
storey gets a **cornice**, and every exposed cladding chunk at ground level gets a
**plinth**.

**This is honest headroom, not a full spend**: 44–54 against 200. A further pass has
room, and the sizes above show why the buildings now measure `39.94` rather than
`39.0` — the ornament oversails by up to 0.47 m against the 0.5 allowance.

### Ornament may leave the cell

The lattice constrains which **cells** a chunk occupies; the render mesh may inset
5 mm where it meets a neighbour and outset up to 0.5 m for ornament. Collision is
generated from the grid and never from this art.

This also retires revision 1's **coplanar-faces** warning: chunks no longer share
exact faces, because every chunk body is inset 5 mm.

### Materials: the same atlas the kit uses

One `standardSurface` per building, sampling the kit's shared 4096 atlas — albedo,
normal, and metallic/smoothness — at the same **113.8 px/m**. That is deliberate: a
hero stands surrounded by kit-dressed neighbours, and if it carried its own materials
the four hand-made buildings would visibly not belong to the same city.

### Watertightness, and the pivot

Both definitions moved and both are now checked correctly:

- **Closed = zero boundary edges and zero non-manifold edges.** Per-chunk
  `V − E + F = 2` is *not* required — a chunk built from several closed boxes fails
  Euler while being perfectly closed.
- **The pivot is the chunk's own centre, not its bounding-box centre.** Those differ
  the moment ornament oversails one face only, so chunks are assembled at the origin
  and moved onto the grid afterwards; the check compares the pivot against the
  position its name declares.

## Verification

Everything the contract's §10 asks, executed rather than asserted:

| check | result |
|---|---|
| load path (§4a) — delete all cladding, flood-fill the frame from storey 0 | **all four stand, 0 stilt columns** |
| zero boundary / non-manifold edges | **0 failures across 2,034 chunks** |
| pivot at chunk centre | **0 failures** |
| occupied cells on the lattice, mesh within +0.5 m | **0 failures**, worst outset 0.47 m |
| triangle budget ≤ 200 × cells | **0 over budget** |
| names parse and agree with measured position | **0 failures** |
| render vacuity (clipped fraction) | 0.0000 on all four |

A build that fails the load-path check **exits non-zero and produces no FBX**.

## Deviations

1. **Corner spandrels** — one cell beside each corner column is concrete rather than
   cladding, or the column would be a stilt by the contract's own definition. The
   zero stilt count is the evidence.
2. **Budget used, not exhausted** — 44–54 of 200, for the reason above.
3. **No curves.** Tapers are available now (a flare on a 1-segment cube is a clean
   frustum at the same 12 triangles, and the kit uses them) but curves need a
   cylinder segment and real triangles. This is now a budget choice, not a
   constraint.

## Settled, no longer open

The origin question from revision 1 is **closed**: min-corner cell centre at local
`y = 0`, floor plane at `y = −1.5`, no offset needed.
