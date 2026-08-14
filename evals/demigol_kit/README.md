# Demigol — kit of parts

**37 one-cell pieces, 1,956 triangles, ONE material.** Not buildings. The generator
already decides per cell what material sits where and which faces are exposed; this
is the vocabulary it draws with, so it dresses all ~50 buildings and anything
generated later comes dressed for free.

Built to `2026-08-15-kit-of-parts-contract.md`. Regenerate with
`evals/demigol_kit.py`.

| file | what |
|---|---|
| `demigol_kit.fbx` | all 37 pieces, each at the origin with its pivot at the cell centre |
| `kit_atlas.png` | the single 512 px atlas every piece samples |
| `contact_sheet.png` | every piece, individually framed |
| `tiling_proof.png` | a 6 × 5 wall built from the kit |
| `manifest.json` | name, role, context, variant, triangle count, budget |

## The budget decided everything

A hero chunk is drawn once. A kit piece is instanced across ~46,000 standing cells,
so this is the exact inverse problem — and the answer was to build every piece out of
**axis-aligned boxes at 12 triangles each**. That makes the budget *arithmetic
rather than an estimate*: a six-box piece is 72 triangles, checked before anything is
built, and a piece that cannot fit is a design error caught at author time instead of
a render to argue about.

Worst piece is **96 tris against a 120 cap**; interiors are **12 against 20**.

## One material, and how the pieces still look different

Everything samples one 128 px patch of a single 512 px atlas — brick, concrete,
steel, glass, infill, a dark recess, and the industrial warning amber. Verified by
measurement, not assertion: **1 shading group across all 37 pieces**, and every
piece's UV bounding box measured inside `0.0075 … 0.9925` (the 3 % patch margin that
stops bilinear filtering dragging in a neighbouring patch).

This is what makes the kit drawable at city scale. Instancing batches by material; a
kit with eight materials is a kit that cannot be drawn.

## Coverage

| role | context | variants | | worst tris |
|---|---|---|---|---|
| `concrete` | interior | 1 | a | 12 |
| `brick` | interior | 1 | a | 12 |
| `steel` | column | 3 | a, b, c | 60 |
| `steel` | beam | 2 | a, b | 60 |
| `steel` | lobby | 1 | a | 60 |
| `concrete` | beam | 2 | a, b | 36 |
| `concrete` | base | 2 | a, b | 48 |
| `concrete` | roof | 2 | a, b | 48 |
| `concrete` | soffit | 1 | a | 60 |
| `brick` | facade | 3 | a, b, c | 72 |
| `brick` | corner | 2 | a, b | 96 |
| `brick` | roof | 2 | a, b | 48 |
| `brick` | soffit | 1 | a | 60 |
| `brick` | lobby | 1 | a | 36 |
| `infill` | facade | 3 | a, b, c | 72 |
| `infill` | corner | 2 | a, b | 72 |
| `infill` | roof | 1 | a | 24 |
| `infill` | soffit | 1 | a | 60 |
| `glass` | facade | 3 | a, b, c | 96 |
| `glass` | corner | 1 | a | 72 |
| `glass` | roof | 1 | a | 36 |
| `glass` | lobby | 1 | a | 84 |

The workhorse contexts (`facade`) carry three variants each. Single-variant entries
are the ones where a second would be decoration rather than variety — a soffit is
seen from below, briefly.

## It tiles — and that is measured, not claimed

`tiling_proof.png` is a **30-piece, 6 × 5 wall** on the real 3 m lattice, mixing
glass beside infill beside brick beside a steel column, with a brick corner run and
concrete ties. Its measured bounding box is

```
measured  [-1.495, -1.495, -1.495,  16.495, 13.495, 1.495]
expected  [-1.5,   -1.5,   -1.5,    16.5,   13.5,   1.5  ]
```

— exactly the lattice bounds inset by 5 mm on all six faces. Nothing escapes its
cell, nothing overlaps, and the 5 mm inset is the z-fight fix doing its job across
30 adjacent pieces.

## Deliberately outside the rules — with reasons

1. **`kit_interior_a` cannot exist.** The contract's naming rule is
   `kit_<role>_<context>_<variant>`, but its own example `kit_interior_a` is three
   tokens and does not parse. Interiors therefore take a role token —
   `kit_concrete_interior_a`, `kit_brick_interior_a` — which is also more useful,
   since a brick cell's interior can be brick.

2. **`column`, `beam` and `base` are treated as contexts.** The context table lists
   `interior/facade/corner/roof/soffit/lobby`, but the "set that earns its place"
   asks for `steel_column`, `steel_beam`, `concrete_beam`, `concrete_base`. Encoding
   the element as a *fifth* token would break the four-token parse, so it went in the
   context slot. Nine contexts, all parseable.

3. **A piece is several closed boxes, not one closed shell.** Every piece has zero
   boundary edges and zero non-manifold edges, so it is watertight in the sense that
   matters — each box is individually closed, so a chunk reads correctly from every
   angle as it tumbles. But `V−E+F = 2` per *piece* does not hold, and a checker
   written for the hero contract would reject these.

4. **Corners have one chirality.** Rotating the authored `(+Z,+X)` corner by 90°
   steps gives `(+X,−Z)`, `(−Z,−X)`, `(−X,+Z)` — exactly the four corners of a
   rectangular plan walked in order, so one piece serves all four corners of a
   building. **A wall that simply *ends* needs `(+Z,−X)`, which is a mirror and not a
   rotation, and is not in this kit.** If the generator ever produces an open-ended
   wall, that is the piece to add.

5. **No taper, no curve.** Same reason as the hero buildings: the envelope rules
   outrank ornament. Character comes from massing, relief depth and glazing pattern.

## The one thing to decide on the Unity side

The kit ships **textured** — colour identity lives in `kit_atlas.png`. Demigol today
builds every material at runtime from `Shader.Find("Standard")` with a flat colour per
`MaterialId` and no textures at all, so this is a new path.

Two options, and they are not equivalent:

- **Take the atlas.** Pieces keep their internal contrast — a glass pane reads
  differently from its steel frame, brick coursing reads against its own mortar. One
  material, one texture, one batch.
- **Drop the atlas and tint per role at runtime.** Simpler, no new asset path, but
  every piece becomes one flat colour, so the frame around a window vanishes into the
  glass and the coursing vanishes into the brick. The relief still reads in silhouette
  and shadow; the material distinction inside a piece does not.

Worth deciding before the importer binds, because it changes what the importer has to
carry — and remember `Shader.Find` at runtime is what produced the #591 gray screen,
so whichever shader ends up sampling this atlas needs to be in Always Included Shaders.

## Not here

- **No LOD**, per the contract.
- **No second kit family.** The generator is parameterised by patch and box list, so a
  second family — heavier brick, more glass, more decay — is a table edit, not new
  machinery. Four families across the district was the stated ambition; this is one.
