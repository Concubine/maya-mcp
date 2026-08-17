# demigol_shards - the fracture pattern library

Third Demigol art delivery. Contract: `docs/superpowers/specs/2026-08-16-shard-library-contract.md` (revision 1), redmine #664.

**20 patterns, 611 shards, 21600 triangles, 2 materials.** Five roles x four variants; a pattern is one 3 m cell pre-shattered into loose meshes, keyed to material and cell and never to a building, so this one library dresses all 50 city buildings and every one generated later.

## The rule everything rests on

Contract 1b: assembled, a pattern must be indistinguishable from the intact cell it replaces. Here that is **true by construction rather than by measurement** - the shards are the Voronoi cells of a seed set clipped to the 3 m box, and every point of the box is nearest exactly one seed, so they tile it with no gap and no overlap. The measured volumes therefore test the clipper, not the design. Worst error across all 20 patterns: **4.33e-06 m3** against 27 m3.

See `reassembly_*.png`, one per role: **a plain 3 m cube in the same material, the pattern assembled, and the same pattern exploded.** The control cube is there because the claim is a comparison, and because it is what caught the one defect a green gate could not - built through `MFnMesh` every edge comes out SOFT, so each flat outer facet was shaded as a dome and an exact cube rendered as a heap of pillowed stones. Every edge is hard now; a fracture face is a crease by definition.

## How the five roles break

| role | shards/pattern | how it breaks | seeds |
|---|---|---|---|
| `concrete` | 33-36 | blocky lumps, aggregate faces, rebar stubs on 5 shards | jittered 3x3x3 lattice (+/-0.30 m) plus 6 surface-biased seeds in the +Z 0.55 m - fine chips at the face, larger blocks behind |
| `brick` | 33 | along its courses - shards are brick-multiples with flat bed joints | 6 horizontal beds x 5 per bed, running bond (alternate beds offset half a brick), vertical jitter +/-0.02 m so bed joints stay flat |
| `infill` | 20 | plate-like, thin in depth: a curtain panel delaminating | 5 depth layers x 2x2, in-layer depth jitter +/-0.035 m - plate-like fragments 0.6 m thick |
| `glass` | 55-56 | a shower of splinters, radial from the impact point on the pane | polar grid about a jittered impact point on +Z (4 rings, 38 seeds) confined to the front 0.42 m, plus 15 coarse seeds through the body |
| `steel` | 10 | does NOT shatter - few large torn, bent sections | 2x14x2 lattice stretched along Y, gathered into 8 contiguous sections by nearest jittered anchor under an ANISOTROPIC metric (vertical distance weighted 0.40, so a section grows tall rather than cubic), then bent by a smooth warp that vanishes on the cell surface. Sections are UNIONS of ~7 cells, not cells - which is what makes the tear boundary ragged: 37.8 angled facets a section against 15.1 at the old 80-triangle cap. Measured: the anisotropy buys raggedness, not length - height/width stays 1.09-1.23 whatever it is set to, because 8 sections of a 3 m cube are ~1.5 m across by arithmetic |

The differences are entirely in **where the seeds go** - the clipper is the same for all five. That is why the distribution is declared per role in the manifest (contract 2a): it is the dial, and it is meant to be re-runnable. Ask for a different one and it is a parameter change and a re-run, not a re-model.

## Budget utilisation

| role | tris/pattern | cap | max tris/shard | cap | per-shard used |
|---|---|---|---|---|---|
| `concrete` | 984-1116 | 1800 | 76 | 80 | **95%** |
| `brick` | 944-960 | 1800 | 56 | 80 | **70%** |
| `infill` | 556-588 | 1800 | 52 | 80 | **65%** |
| `glass` | 1620-1752 | 1800 | 72 | 80 | **90%** |
| `steel` | 1136-1176 | 1800 | 194 | 200 | **97%** |

The per-shard cap is **per role**: 80 everywhere, 200 for `steel`, raised by the contract owner on #664. The next section is why.

### Steel, re-run at the raised cap

The first delivery of this library reported steel as its weak spot and asked for exactly this: its *pattern* budget sat at 27% while every section was pinned at 95% of the 80-triangle *per-shard* cap, so the binding constraint was the one that had nothing to do with cost - and it is what made steel read diced rather than torn. It now sits at **1176 of 1800 pattern triangles (65%)** with sections at **97% of the 200 cap**.

**The re-run does not spend the new cap the way the ask assumed, and that is the one thing to read here.** The ask was phrased as *~4.5 Voronoi cells per section, ~192 triangles*, carrying forward the first delivery's own counterfactual. But cells-per-section is a proxy. What the eye reads is how many angled planes the torn boundary turns through, so the re-run measured **tear facets** directly:

| lattice | cells/section | mean tear facets | max tris/shard | section volumes |
|---|---|---|---|---|
| `2x5x2` (shipped before) | 2.5 | 15.1 | 76 | 2.34-4.34 m3 |
| `3x4x3` (the ask, converted) | 4.5 | 27.2 | 194 | 1.51-6.57 m3 |
| **`2x14x2` (ships now)** | **7.0** | **37.8** | **194** | **2.40-4.72 m3** |
| `2x16x2` | 8.0 | 40.3 | 230 | over cap |

A Y-dense lattice is far more triangle-efficient, because cells stacked along one axis merge into a section that gains volume without gaining many outward walls. Same triangle price as the converted ask, **39% more tear**, and the sections stay comparable in size - `3x4x3` came out lopsided at 1.5 to 6.6 m3, which reads as a broken block rather than as eight severed sections.

The cap and the lattice are therefore **one decision**: 200 buys 7 cells a section and nothing more, since the next step measured 230. Moving either without re-measuring the other is a bug.

What is NOT available at any budget, and is worth saying so it is not re-litigated: **long** members. Eight sections dividing a 3 m cube are about 1.5 m across whatever the metric does - measured height/width stayed 1.09-1.23 across every setting tried, including a strongly anisotropic gather. Torn is reachable; long is not, at 8 pieces. The contract owner has accepted this and ruled long members out of this library.

There is a second, structural limit on the same role. **1b requires the assembled pattern to be an exact cube**, so every shard's outer face is flat and axis-aligned by definition. A torn read can therefore only live on the fracture walls - which is why the bend deforms the interior and vanishes at the cell surface. 1b and the steel row of 2 pull against each other, and 1b wins because it is the one that is rejected rather than flagged.

## The two materials

1. **`shard_building`** - the kit's atlas, unchanged. A surviving outer face must line up with the intact cells beside it, so it uses the same atlas, the same patch and the same 113.8 px/m.

   **This delivery ships no copy of it.** The manifest declares `shared_with: demigol_kit` and the three `kit_*.png` byte copies earlier revisions carried are gone. Resolve the material from the kit delivery. Copies gave the shards their own material, which means shard debris would *not batch with the kit wall it broke out of*, ~40 MB of texture would be resident twice, and a kit re-author would leave the copies silently stale with nothing failing.

2. **`shard_fracture`** - new, 4096 px, 16 of 16 patches used. The freshly-broken faces are the majority of every shard's surface and the kit atlas is 16/16 full. Albedo, normal and metallic/smoothness on one layout, so it costs one extra draw call for the whole city and not one more.

Assignment is **per face**, not per object, and UVs are per face-vertex: a shard corner belongs to an outer face and a broken face at once, and those read from different atlases.

### Submesh order is DECLARED, not derivable

Every shard carries a `submeshes` array in the manifest, in FBX submesh order. **Bind materials by index from that array.** Do not assume index 0 is the building atlas:

| shards | submeshes | index 0 is |
|---|---|---|
| 576 | `["shard_building", "shard_fracture"]` | `shard_building` |
| 35 | `["shard_fracture"]` | `shard_fracture` |

35 of 611 shards are fully interior - they have no face that was ever part of the wall's outer surface - so they carry ONE submesh and index 0 means the fracture atlas on them. A consumer that derives the order from `surface`, or assumes two submeshes everywhere, puts the fracture texture on the outside of those 35 shards and nothing fails. That is the shape of the two defects this project has already paid for: #596's 626 catalog entries bound to another building's mesh, and #630's 4096 atlas importing at 2048 - individually valid data, one wrong global assumption, no error.

The claim is checked against the **exported FBX bytes**, not against the builder that wrote them: material connection order per model, and the per-polygon material indices underneath it. `611/611` models matched.

Interior texel density, per role, derived from the widest broken face each role actually makes:

| role | m of layout per patch | px/m | 20 mm feature |
|---|---|---|---|
| `concrete` | 2.7 | 379 | 7.6 px |
| `brick` | 3.6 | 284 | 5.7 px |
| `infill` | 3.8 | 269 | 5.4 px |
| `glass` | 3.3 | 310 | 6.2 px |
| `steel` | 3.0 | 341 | 6.8 px |

## The outset (contract 1c)

Sized against the kit rather than against the allowance. **Measured in `demigol_kit/manifest.json`: only 9 of the 41 kit pieces oversail at all, and the largest is 0.34 m** - brick facades 0.14-0.22, brick and concrete roofs 0.30-0.34, a concrete base 0.15, a glass sill 0.16, a steel column 0.24, and infill never. A uniform 0.5 m lip would be wrong against 32 of 41 neighbours.

So the band is per role (concrete 0.20 m, brick 0.22 m, infill 0.00 m, glass 0.16 m, steel 0.24 m) and it is delivered as **its own shards** rather than welded onto the cell shards behind it. That keeps every band piece convex, keeps the cell's union at exactly 27 m3, and lets a cornice break off independently the way a cornice does.

## The bite proof

`contact_sheet.png` does not show intact cells - it shows every pattern **after a strike**, because a sheet of intact cells would prove the fill and hide the point. One 1.15 m strike at the +Z face, removing the shards whose delivered `seed` falls inside it, which is the same test the shell will run:

| pattern | shards | removed |
|---|---|---|
| `concrete_a` | 36 | 5 (14%) |
| `concrete_b` | 33 | 5 (15%) |
| `concrete_c` | 33 | 7 (21%) |
| `concrete_d` | 35 | 5 (14%) |
| `brick_a` | 33 | 1 (3%) |
| `brick_b` | 33 | 2 (6%) |
| `brick_c` | 33 | 3 (9%) |
| `brick_d` | 33 | 1 (3%) |
| `infill_a` | 20 | 1 (5%) |
| `infill_b` | 20 | 3 (15%) |
| `infill_c` | 20 | 2 (10%) |
| `infill_d` | 20 | 2 (10%) |
| `glass_a` | 56 | 24 (43%) |
| `glass_b` | 55 | 24 (44%) |
| `glass_c` | 56 | 22 (39%) |
| `glass_d` | 55 | 20 (36%) |
| `steel_a` | 10 | 0 (0%) |
| `steel_b` | 10 | 0 (0%) |
| `steel_c` | 10 | 1 (10%) |
| `steel_d` | 10 | 1 (10%) |

### The spread is mostly the RULE, not the material

Last round this delivery reported the spread above - 36-44%% of a glass pattern against 3-9%% of a brick one - as *erosion per hit is a property of the material*, and handed it over as a decision. That was half right, and the half that was wrong matters more. Scoring the same strike three ways:

| role | `seed` | `seed + bound` | `solid` | shards | `seed` finds |
|---|---|---|---|---|---|
| `concrete` | 22 | 79 | 60 | 125 | **37%** |
| `brick` | 7 | 95 | 47 | 120 | **15%** |
| `infill` | 8 | 58 | 41 | 80 | **20%** |
| `glass` | 90 | 186 | 136 | 210 | **66%** |
| `steel` | 2 | 29 | 16 | 32 | **12%** |

- `seed` - the point test, `|seed - strike| <= radius`. What the shell does today and what the contact sheet shows.
- `seed + bound` - `<= radius + bound_radius_m`, the sphere-sphere form. A superset of `solid` by construction, so it never misses a shard the strike reaches; it over-includes instead, most on the shards whose bounding sphere fits them worst.
- `solid` - ground truth, measured against the real surface: point-to-triangle distance over every face, plus an inside test.

**One point cannot stand for a shard of up to 4.7 m3.** The point test under-removes everywhere, and it under-removes worst on the biggest shards - so a role's apparent erosion rate is largely a sampling artifact of its shard SIZE rather than a property of the material. Glass looks like it shatters partly because its splinters are small enough for a point to represent them; steel looks immovable partly because a 4 m3 section is one point.

Nothing here is a change to the geometry, and no rule is imposed: `bound_radius_m` and `aabb` now ship per shard so the shell can pick its rule with the numbers in front of it. The per-role multiplier the consumer planned is still the right lever for taste - this just means it starts from a corrected baseline rather than compensating for a measurement error.

`rebar_detail.png` is six of the 20 stub-carrying shards at close range. It doubles as the proof of the two-material split at the scale that matters: smooth kit concrete on the outer faces, exposed aggregate on the broken ones, on the same mesh.

## Deviations, with reasons

- **8.3 - every shard convex** (`steel`): the 8 steel sections are unions of ~7 Voronoi cells and are not convex; they are also bent by a smooth warp
  contract 2 requires steel to read as torn plate with ragged tear edges and explicitly NOT to shatter, and a convex lump is the one shape a torn section cannot be. The two rules cannot both hold for this role, so the artistic requirement wins. Every other role is convex by construction and checked. A convex-hull collider on a steel section is a close fit - the sections are large and slab-like, not concave shells.

- **8.3 - every shard convex** (`concrete`): 5 shards per concrete pattern carry a rebar stub as a second shell, which makes those meshes non-convex
  contract 2 asks for rebar stubs protruding from a few shards. The stub grows out of a BROKEN face into the neighbouring shard, where it is fully enclosed until that neighbour is removed - which is exactly when a bar should appear. It cannot open a gap and cannot be seen early. The alternative, taking the bar out through the cell face, is a bar sticking into the street: a different and much rarer read.

- **1b - no overlaps** (`concrete`): a rebar stub interpenetrates the shard it points into, by about 0.0005 m3
  1b exists so that an assembled pattern looks like an intact cell. A stub sealed inside a neighbour cannot affect the union or the silhouette. The fill volume is measured on the Voronoi bodies alone, so the overlap cannot flatter the number either.

- **the kit's 5 mm inset** (`all`): shards reach the cell face exactly, where kit pieces stop 5 mm short
  1b requires the union to fill the cell, and an inset would fail it. The consequence is that a pattern sits 5 mm PROUD of its neighbours rather than coplanar with them, which avoids z-fighting instead of causing it. Worth knowing on the game side; it is not something to correct here.

## Regenerating

```
MAYA_MCP_PORT=9878 "E:/Autodesk/Maya2027/bin/maya.exe" &
set MAYA_MCP_PORT=9878 && .venv/Scripts/python.exe evals/demigol_shards.py
```
**9878, not 9877.** This generator opens with `new_scene`, and 9877 is the user's own Maya session under the two-Maya policy - a `new_scene` there discards whatever is open, unsaved.

The geometry is in `evals/shard_fracture.py` and has no Maya in it: `python evals/shard_fracture.py` prints the full fill/convexity/budget audit for all 20 patterns in about a second, with no scene open.
