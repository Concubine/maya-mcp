# Demigol — kit of parts (family 1, **revision 2**)

**41 one-cell pieces, 2,364 triangles, ONE material, three maps.** Not buildings.
The generator already decides per cell what material sits where and which faces are
exposed; this is the vocabulary it draws with, so it dresses all ~50 buildings and
anything generated later comes dressed for free.

Built to `2026-08-15-kit-of-parts-contract.md` **rev 2**. Regenerate with
`evals/demigol_kit.py`.

| file | what |
|---|---|
| `demigol_kit.fbx` | all 41 pieces, each at the origin with its pivot at the cell centre |
| `kit_albedo.png` | 4096² albedo atlas, 4 × 4 patches |
| `kit_normal.png` | tangent-space normal, same layout |
| `kit_mask.png` | R = metallic, G = smoothness, **A = smoothness** |
| `contact_sheet.png` | every piece, individually framed |
| `tiling_proof.png` | a 30-piece 6 × 5 wall |
| `manifest.json` | per piece: role, context, variant, triangles, budget, **declared outset** |

## What revision 2 changed here

### 1. Silhouette — the lattice constrains cells, not meshes

This was the biggest lever, exactly as the contract predicted. Nine pieces now
oversail their cell, up to **0.34 m** against the 0.5 m allowance: string courses,
window sills, a bracketed roof cornice with dentils, corbels under the steel column
caps, and **battered plinths** on the concrete bases.

Tapers cost nothing. Measured live: a flare deformer on a 1-segment cube produces a
clean linear frustum at **12 triangles and 8 vertices** — the same as an untapered
box. So "no taper or curve" was never a triangle problem; it was only ever the
bounds rule.

### 2. Texel density is now a stated, measured number

**113.8 px/m**, uniform across every piece, and it is uniform *because of a tool
change* rather than by luck. Family 1 normalised each box to fill its patch, so a
0.5 m band and a 3 m slab came out roughly 6× different — and, as the contract said,
the manifest gave no way to tell. That unknowability was the real defect.

`uv_atlas` gained a `world_scale` mode: UV scale derives from real-world size, so
pixels per metre is a constant you can compute — `(atlas_px / cols) / world_scale`.

**Why 113.8 and not 170.** A box auto-projection lays a piece's six faces side by
side. Measured live, **a cube's UV bbox spans 2.858 face-widths, not one**, so a
patch covers ~9 m of layout rather than one 3 m face. The contract's ~170 px/m
assumed one patch per face; under box projection reaching it would need a **6144**
atlas. 4096 gives 113.8 px/m — still 2.7× family 1's ~43 — and this is exactly the
"say why" the contract invites for going above 2048.

**Brick is now at real-world scale**: 13 courses/m, so a 3 m face reads **39
courses**. Family 1 drew 8 per patch, putting ~7 on a 3 m face — the 5–6× oversize
the contract diagnosed, confirmed.

### 3. Three maps, still one material

Albedo + normal + metallic/smoothness on one atlas layout under one shader: **1
shading group across all 41 pieces**, zero extra draw calls, zero extra triangles.
Glass, steel and brick no longer reflect light identically — steel is metallic at
0.48–0.62 smoothness, glass is 0.95–0.97, brick is 0.14.

Total map weight is **6.7 MB**. The first attempt was 46 MB: per-pixel grain is a
PNG compressor's worst case, and at 114 px/m it also read as television static
rather than material — the normal map derived from the same height amplified it.
Grain is now generated at ⅛ resolution and box-blurred twice.

### 4. Both corner chiralities

`endcap` is a **tenth context** — `kit_brick_endcap_a/b`, `kit_infill_endcap_a`,
`kit_glass_endcap_a` — carrying the mirrored `(+Z,−X)` corner for a wall that *ends*
rather than turns.

It is a context rather than a variant letter for a mechanical reason: **the shell
picks variants from a coordinate hash**, and chirality is not something that may be
chosen at random. A `corner` and an `endcap` are not interchangeable, so they cannot
share a selection pool.

## Verification

| check | result |
|---|---|
| geometry failures | **0** across 41 pieces |
| shading groups | **1** (`kit_materialSG`) |
| widest extent | 1.840 m — cell face 1.5 + 0.34 outset, inside the 0.5 allowance |
| UV range | 0.0079 … 0.9921, every piece inside its patch |
| triangle budget | worst 96/120; interiors 12/20 |
| contact-sheet tiles | 41 rendered, **0 blank** |

**Tiling proof** — a 30-piece 6 × 5 wall mixing glass, infill, brick, a steel column,
a corner run and concrete ties:

```
measured  [-1.495, -1.5,   -1.524,  16.495, 13.5, 1.84 ]
lattice   [-1.5,   -1.5,   -1.5,    16.5,   13.5, 1.5  ]
oversail  [-0.005,  0.0,    0.024,  -0.005,  0.0, 0.34 ]   allowance -0.005 .. 0.50
```

Note this check *changed* with the contract. Revision 1 asserted the wall matched the
lattice inset by 5 mm on every face; under revision 2 that is the wrong rule, because
ornament is meant to oversail. What is tested now is that every face sits inside the
allowance band.

## Deviations, with reasons

1. **`endcap` is a tenth context** (see above) — chirality cannot ride in the
   hash-selected variant slot.
2. **`column`, `beam`, `base` remain contexts**, as accepted in rev 2 §9.4.
3. **A piece is several closed boxes**, not one closed shell: zero boundary edges and
   zero non-manifold edges, per rev 2 §8.2.
4. **113.8 px/m rather than 170** — measured reason above.
5. **No curved corners.** Tapers are in; true curves would need a cylinder segment
   and cost real triangles against a 120 cap already at 96 on the worst piece. Worth
   revisiting only if the budget rises.

## Still to decide on the Unity side

The kit now *requires* a textured path — three maps, one material. Whichever shader
samples them must be in **Always Included Shaders**; `Shader.Find` at runtime is what
produced the #591 gray screen.

Smoothness is in **both** G and A of the mask: A is where Unity's Standard shader
reads it from, G keeps the map readable by eye. Pick one and drop the other if you
repack.

## Not here

- **No LOD**, per the contract.
- **One family, not four.** The generator is parameterised by patch table and box
  list, so a second family — heavier brick, more glass, more decay — is a table edit,
  not new machinery.
