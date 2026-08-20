# Demigol — kit of parts (family 1, **revision 4**)

**70 one-cell pieces, 5,544 triangles.** Not buildings.
The generator already decides per cell what material sits where and which faces are
exposed; this is the vocabulary it draws with, so it dresses all ~50 buildings and
anything generated later comes dressed for free.

Revision 4 answers Demigol **#654** — the crown the massing has been faking, and the
setback terrace lip — and re-pitches brick against a render rather than a prediction
(**#652**). Revision 3 answered #677: the missing steel pieces, and damage states.
Regenerate with `evals/demigol_kit.py`.

| file | what |
|---|---|
| `demigol_kit.fbx` | all 70 pieces, each at the origin with its pivot at the cell centre |
| `kit_albedo.png` | 4096² albedo atlas, 4 × 4 patches — **brick re-pitched, revision 4** |
| `kit_normal.png` | tangent-space normal, same layout — **brick re-pitched, revision 4** |
| `kit_mask.png` | R = metallic, G = smoothness, **A = smoothness** — unchanged |
| `contact_sheet.png` | every piece, individually framed |
| `tiling_proof.png` | the revision-2 wall, regenerated unchanged, as the baseline |
| `tiling_proof_steel.png` | **new** — a 5 × 5 wall of revision 3's own pieces |
| `tiling_proof_skyline.png` | **new in revision 4** — a 6 × 4 wall, all six new pieces in the top row under open sky |
| `soffit_underside.png` | the deck soffit from the one side it is for |
| `damage_detail.png` | **new** — the six damage states, each beside its `fractured` twin |
| `manifest.json` | per piece: role, context, variant, triangles, budget, **utilisation %**, **measured outset** |

## What revision 4 changed

### 1. `crown` — the cap the massing has been faking

Demigol #654 measured it. The massing gives Towers two setbacks and Slabs one, and caps each
with a perimeter ring of **Infill** — so the top of every building in the city is a curtain
panel one storey taller than the one below it. No coping, no cornice, no change of
silhouette, which is why the roofline reads as *the wall kept going* rather than as a
building ending.

`kit_concrete_roof_b`, `kit_brick_roof_b` and `kit_steel_roof_c` already cap a **deck**, and
none of them is what a wall ring needs: a deck piece spends its cell on the horizontal
surface, and a crown cell has no horizontal surface at all. It is wall, all the way up,
ending in the sky.

Four of them — `kit_infill_crown_a` (plain), `kit_infill_crown_b` (piered), `kit_brick_crown_a`
(dentil course), `kit_concrete_crown_a` (civic, no ornament, one very deep coping). Each reads
the same three moves, because that is what makes a skyline legible from across a district
rather than merely detailed: a cornice with a real shadow under it, a parapet **tonally**
separated from the wall below, and a coping that oversails.

### 2. `terrace` — the setback lip

The other half of #654. A setback leaves the storey below with a deck whose outer edge is
three surfaces at once: the deck you can stand on, the street-facing fascia, and — because
the lip oversails the wall beneath it — an **underside** visible from the pavement. No
delivered piece does all three: a roof piece has no underside, a soffit has no top. The
massing currently dresses the lip with soffit pieces not designed for it.

`kit_concrete_terrace_a` and `kit_steel_terrace_a`. The steel one's underside is corrugation
crossed by a downstand, matching `kit_steel_soffit_a` exactly; the concrete one is coffered,
matching `kit_concrete_soffit_a`. A terrace and a soffit meet at every re-entrant corner,
which is precisely where two undersides get compared.

### 3. Both are CONTEXTS, not variant letters

Same rule that made `endcap` and `damaged` contexts: the shell picks variants from a
coordinate hash, and both of these are chosen by **position**. A hash must never be able to
put a coping halfway up a building.

### 4. Brick re-pitched, 6 → 9 courses/m

Revision 3 coarsened brick to 6/m on a **prediction** that a faithful 13/m course would alias
on Demigol's no-mipmap import path. Revision 4 rendered it: a 78 m brick wall at a grazing
angle, unfiltered, at 6, 9 and 13 courses/m. **13 showed no moiré anywhere along the sweep** —
and a 1-px checker positive control in the same patch, same camera, same filtering, tore into
violent moiré, so the aliasing condition was genuinely reproduced and real brick survived it.

What 6/m cost: a 167 mm course is twice a real brick, so at close and play distance the wall
read as large-format blockwork, and the coarse courses stayed individually resolvable far
enough out to read as horizontal striping rather than as material.

**9 rather than 13** for a reason the render cannot settle: this test is Maya's rasteriser,
Demigol's is Unity with **BC-compressed** textures, and block compression at a 1.4 px mortar
bed is where a thin dark line smears. 9/m puts the bed at **2.0 px — on** the floor the
generator tests pin, not under it. 13 remains available; the evidence is in
`docs/deliveries/2026-08-21-brick-pitch/`.

### 5. The grandfathered taper-trap offender is fixed

Revision 3 found `kit_brick_facade_c`'s tapered string course, measured it, and left it alone
for a stated reason — brick was on that delivery's do-not-touch list, and *"a gate that fails
on a piece you are forbidden to fix is a gate that gets disabled."* Revision 4 reopens brick,
so the reason has expired. The taper is now the same stepped pair the crowns use, and the
gate's known-offender set is **empty**, which is a stronger gate than a populated one.

## What revision 3 changed

**23 new pieces, 41 → 64. No existing piece was touched, no patch colour moved, and no
new atlas.** The three PNGs above are byte-identical to revision 2 — every new mesh
lands on the existing 16 patches, so the standing city is still one draw call and
#653's new-family question is untouched.

There is a **second material**, on six pieces only, and it is not this delivery's: the
`fractured` context binds its broken surfaces to `demigol_shards`' own `shard_fracture`.
See *the two damage sets* below.

### 1. Steel — eleven pieces, 6 → 17

Steel is what the game is about — *"cut the bones, not the skin"*, and steel is the only
role the player aims at — and it had **6 pieces of 41**. Worse, the kit shipped no steel
roof piece at all, so #611's rule S3b dressed every steel deck as a concrete plate:
**13,186 of 45,638 cells, ~28% of all visible surface**, resolving to one concrete family.

| piece | why |
|---|---|
| `kit_steel_roof_a` / `_b` / `_c` | ask #1. **Three, not one** — dressing all 13,186 fallback cells with a single new piece replaces one monotony with another. `_a` ribbed field deck with a drain and a cross seam; `_b` deck + rooftop plant (AHU, vent stack — the only piece in the kit that breaks the cell's top face); `_c` perimeter crown with an oversailing coping. |
| `kit_steel_soffit_a` | deliberately **not** `soffit_coffer`. A coffer is a masonry idea; the underside of a composite steel deck is corrugation crossed by a downstand beam. |
| `kit_steel_facade_a` / `_b` | spandrel + mullions + vision strip; and a shadow-box wall with three projecting vertical fins. Two variants because a curtain wall spans many cells in one glance. |
| `kit_steel_corner_a` + `kit_steel_endcap_a` | four full-height members plus **one** splice collar. The mirror is one line and zero triangles. |
| `kit_steel_column_d` / `_e` / `_f` | the most-repeated piece in the city, differing by **silhouette**: a box/HSS section; a stanchion flaring into its end plates; an I-section wearing a riser and a cable tray. Three I-sections in different trim would still be three I-sections at 30 m. |

**Deck heights follow `kit_concrete_roof_a` exactly** (body to 0.6, cap to 0.9) so a steel
deck and a concrete deck in adjacent cells sit flush.

**The ribs are plain boxes, not tapered.** `taper` flares X and Z together, so a
trapezoidal flute spanning the full cell would pull its own ends away from the neighbour
it has to meet. Standing-seam deck rather than trapezoidal deck — decided by the deformer,
not by taste. See *the taper trap* below.

### 2. Damage states — six, twice over

Sheared plate, exposed rebar, shattered pane, cracked infill. Two each for steel and
concrete, the roles this game looks at most.

**`damaged` is a context, not a variant letter.** The shell picks variants from a
coordinate hash, and damage is a STATE the consumer selects — so it can no more ride in
the variant slot than chirality could, which is exactly why `endcap` exists. A hash must
never be able to decide a cell looks damaged.

**Two of them are authored on +Y, not +Z**, and the manifest says which. A spall modelled
on a vertical face is invisible on a roof deck, and the deck is the surface an airborne
golem spends its time looking at.

**There is no brick damage state.** The generator emits no Brick cells, so it would ship
idle — the one failure mode #677 named outright.

`manifest.json → damage_states.substitutes` is the consumer's table: for a hurt cell whose
*intact* classification is one of the listed `(role, context)` pairs, swap in the named
piece and leave the mesh/scale/collider/material tuple otherwise alone.

#### The two sets — pick one at wiring time

| context | materials | needs |
|---|---|---|
| `damaged` | **one** — everything on the kit atlas | nothing. Drops in against `ChunkDresser` as it stands, which writes a single `sharedMaterial`. |
| `fractured` | **two submeshes** — surviving skin on the kit atlas, broken surfaces on `demigol_shards`' own `shard_fracture` | `ChunkDresser` writing a two-element `sharedMaterials` for these cells. |

**They are geometrically identical.** Both are generated from one authored box list: the
broken boxes carry a `frac` tag, `fractured` honours it and `damaged` strips it. Two
hand-written copies of six pieces would drift, and then a comparison between the sets
would be measuring bookkeeping rather than material. A gate asserts the twins stay equal.

**Why a context and not variant letters.** The shell picks variants from a coordinate
hash, so `_c`/`_d` would let a hash hand a cell a two-material piece the consumer cannot
render. Same reasoning that put chirality in `endcap` and damage in `damaged`.

**Why not the same six names in a second FBX** — which would have been the tidiest swap:
identical node names across two files inside one delivery re-arms the #596 trap exactly.
That is how 626 hero catalog entries came to point at another building's mesh.

**Submesh order is READ, not declared.** The exporter chooses it, so stating it from the
builder would restate an intention. Each piece's `submeshes` array is read back out of
the exported FBX, and the per-polygon material indices are checked against the box list.
Note the unit: kit polygons are **quads**, so a box is 6 polygons and 12 triangles.

**No copies of the fracture maps ship here.** `shard_fracture` is resolved from the
`demigol_shards` delivery — the mirror of what that delivery already does with this
kit's atlas, and for its reasons: a copy is a *second material*, so kit debris would not
batch with the shards it broke out of, ~40 MB would be resident twice, and a shard
re-author would leave the copy silently stale.

**The fracture atlas is projected at 113.8 px/m here — the kit's own, not the shard
library's 269–394.** `demigol_shards` projects broken faces locally about their own small
centres; these are cell-scale boxes, and at a world scale tight enough for 341 px/m a
full-cell slab's box projection spans ~8.5 m of layout against a 3 m patch. It would
spill into the *neighbouring* patch while still measuring inside 0…1, so the UV gate
would pass a piece sampling an unrelated material. Both materials on one mesh now carry
identical pixels per metre, which is what matters where they meet. Colour matches
exactly; feature scale is coarser than a shard's.

**What the second material actually buys, judged from `damage_detail.png`.** The pairs
differ only inside the damage — every exterior face is identical, by design and by gate.
The gain is largest where the break surface is big and directly visible:
`kit_steel_fractured_b`'s peeled flange reads as bright torn metal instead of a slightly
lighter grey, and `kit_concrete_fractured_b` shows real aggregate in the blown corner.
On `steel_a`, `concrete_a` and `glass_a` the difference is subtle at play distance,
because those breaks are small or seen obliquely.

### 3. Continuity with `demigol_shards`, as a measurement

Ask 2 wants these continuous with the shard library's fracture material. The kit's hard
constraint is ONE material, so they cannot *be* that material — which makes the continuity
a number rather than a claim. The pairing is **authored** and only the delta is measured,
against the **delivered** shard manifest:

| kit patch | stands in for | ΔRGB |
|---|---|---|
| `rust` | `rust` | **0, 0, 0** |
| `trim` | `infill_core` | 2, 0, 4 |
| `grime` | `grime` | 4, 4, 3 |
| `concrete_dark` | `concrete_dark` | 4, 5, 5 |
| `glass_bright` | `glass_green` | 6, 0, 19 |
| `steel` | `steel_torn` | **36, 34, 28** |

Exposed core, rebar and soot match within 5 of 255. **Steel is the one real gap**, and it
is one-directional: the fracture atlas's `steel_torn` is deliberately brighter than
anything in the kit (*"a section opened a second ago should be bright bare metal"*).
Rather than fake it, the steel tears read by **geometry and shadow** — a hole, a curled
lip, a flap standing up — and the surviving skin stays on the patch its intact neighbour
wears.

**Pairing by nearest RGB was tried and is the wrong instrument.** It matches `steel` to
`concrete_core` at ΔRGB 24 and reports that as a good result, when the shard library would
never put concrete on a steel tear. It flatters the answer by comparing against whatever
happens to be closest instead of against what the surface actually sits beside.

**This table describes the single-material `damaged` set only.** For `fractured` the
continuity is exact by construction — those surfaces are on the shard library's own
atlas, so there is no delta to measure. Two of its patches are ones the kit does not
have at all: `rebar`, which the kit has to spend `rust` on, and `concrete_core`, a fresh
bright core the kit can only approximate with a weathered dark.

## Utilisation, not a pass mark

| | pieces | triangles | budget | utilisation |
|---|---|---|---|---|
| revision 2 | 41 | 2,364 | 4,720 | 50.1% |
| **revision 3** | **64** | **4,980** | **7,480** | **66.6%** |

All 23 new pieces sit at 9 or 10 boxes — **108–120 of 120, i.e. 90–100%**. Revision 1
passed while spending 6% of its budget, and the pass mark is what hid that.

## Verification

| check | result |
|---|---|
| geometry failures | **0** across 64 pieces |
| shading groups | **2** — `kit_materialSG` on all 64 pieces, `shard_fractureSG` on the 6 `fractured` ones only. The standing city is still one draw call. |
| submesh order | read back from the FBX and matching the manifest on all 64; 58 single-material, 6 with two |
| fracture faces | 144 polygons on the second material, every piece matching its box list |
| skin rule | no box tagged as a break presents more than 0.25 m² of the cell's outer surface (largest actual: 0.042) |
| UV range | 0.0079 … 0.9921, every piece inside its own patch |
| contact-sheet tiles | 64 rendered, **0 blank** |
| damage detail | 12 rendered as 6 pairs, 0 blank |
| soffit underside | 3-cell run, 0 blank |
| damage substitution | 6 states, every skin matched to an intact counterpart |
| units | metre vertices, **zero** non-identity node scales, gated on the FBX **bytes** |
| artifact vs manifest | 64 node names match exactly, triangles agree, declared outset ≥ delivered, no fracture-map copies shipped |

**Tiling proof, revision 3's own pieces** — a 5 × 5 wall of all eleven steel pieces and all
six damage states, roofs on top and soffits directly beneath them (the relationship a deck
and its underside actually have, and the only arrangement the soffit can be judged in),
with both chiralities in one image: the mirrored `endcap` at x = 0 where the wall stops,
the authored `corner` at x = 4.

```
measured  [-1.6,   -1.495, -1.495,  13.6,  13.7, 1.78]
lattice   [-1.5,   -1.5,   -1.5,    13.5,  13.5, 1.5 ]
oversail  [ 0.1,   -0.005, -0.005,   0.1,   0.2, 0.28]   allowance -0.005 .. 0.50
```

The revision-2 wall is regenerated unchanged and its bbox is identical to what revision 2
shipped, so the new pieces did not disturb the old ones.

**The soffit is shot upside down.** A deck's underside is seen from below;
`render_scene`'s angle presets have no bottom, and `current` is documented to fall back to
`three_quarter`, so a custom camera cannot be used either. The run is flipped 180° and shot
from above. **The piece itself is authored the right way up** — the rotation is an
inspection device and nothing in the delivery is upside down.

## Findings, reported not hidden

### `outset_m` is MEASURED now, not derived from the box spec

It used to be computed from the box list, which is the *intent* — a `taper` shrinks a box
after the spec is written. Both concrete bases declared **0.15 m** of oversail while
delivering **0.024**. Every piece now carries the measured figure as `outset_m` and the
spec figure beside it as `outset_from_spec_m`, so the gap is visible instead of implied.
Three pieces differ; all three deliver *less* than they declared.

### The taper trap

A tapered box whose X or Z reach lands on a meeting face (1.495 inset, or the 1.5 cell
face) does **not** meet its neighbour — the flare pulls its far end away and opens a notch
in a run that is meant to be continuous. The generator audits every tapered box and prints
the offenders.

**One offender: `kit_brick_facade_c`'s string course.** It is pre-existing, it is brick,
and brick is on #677's do-not-touch list — so it is reported rather than fixed. It costs
one number whenever brick is next opened. The audit prints instead of failing for the same
reason: a gate that fails on a piece you are forbidden to fix is a gate that gets disabled.

### The defect no gate could see, and the gate that exists now

Both steel damage states were first authored on `steel_dark`, while the intact pieces they
stand in for — `kit_steel_roof_a`'s deck plate and `kit_steel_column_a`'s whole section —
are `steel`. **Every check passed**: the patch exists, the budget holds, the envelope
holds, the tile renders and is not blank. A damaged cell would simply have been a darker
steel sitting beside the cell it replaced — a seam you can only find by rendering the piece
and looking at it next to its neighbour.

`check_damage_substitutions` is that gate now, and it runs before the build. It also
catches an unlisted damage piece, a rule pointing at nothing, and a substitution target no
intact piece provides. `tests/test_demigol_generators.py` carries a positive control that
falsifies the skin and asserts the gate bites.

**It then happened twice more, and the second time it became a second gate.**

`check_skin_rule`: a box that forms part of the cell's **outer surface** is skin and may
never carry a break, because a break puts the shard library's atlas on its faces. Three
`fractured` pieces tagged their whole body slab, so the fractured twin of a concrete deck
came out a mottled boulder beside an intact grey plate — ~6 m² of fracture aggregate on
the outside of the building. Every gate passed: the tag named a real patch, the counts
matched, the submesh order verified, the UVs stayed in range. Found in the paired render.
The limit is 0.25 m² and the largest legitimate contact is 0.042, so the gate is
calibrated rather than nominal, and the suite pins that margin.

### The combine does not carry per-face shading

Assigning a shading group per box *before* `handlers/combine.combine` does not survive
it: **all six two-material pieces came back wholly on one group, and in every case it was
the group its first box carried.** Six for six is first-input-wins, not a coincidence.

The split therefore happens after the combine, by face range — which depends on box order
surviving into the face array. That dependence is **checked, not assumed**: every box was
projected into a known atlas patch, so the patch a face's UVs land in is a fingerprint of
which box it came from, and the run stops if face 6*i* does not belong to box *i*.

Worth someone's attention on the tooling side: this is a real limitation of `combine`, and
nothing in it warns. The handler is untouched here.

### Two more pieces re-authored

Both found in the render and neither visible to any check:

- `kit_steel_corner_a` reused `corner_bands` the way brick does — three bands per cell, so
  nine horizontal lines over three stacked cells and no vertical at all. Right for a brick
  quoin, wrong for what the ask calls *"steel columns full height"*.
- `kit_steel_damaged_a`'s body was `shadow`, which made the tear read and turned the cell's
  four **side** faces black — the same wrong-skin seam, moved to a different face. The
  darkness is now a tray inside the hole and nothing else.

## Not extended, deliberately

All 11 `brick` pieces, non-steel `corner`/`endcap`, non-steel `soffit`, and `concrete_beam`
are exactly as delivered. They are idle for **generator** reasons, not art reasons, and
building more of what is already idle is the one failure mode this delivery was told to
avoid. They unlock when #643's engineering half is decided.

`demigol_shards` was not touched. The "debris looks like flower petals" complaint (#679) is
measured as not an art defect — median flatness 0.689, 6% flat, median volume 0.759 m³
across all 784 shards.

## Still to decide on the Unity side

- Whichever shader samples these maps must be in **Always Included Shaders**;
  `Shader.Find` at runtime is what produced the #591 gray screen.
- Smoothness is in **both** G and A of the mask. A is where Unity reads it; G keeps the map
  readable by eye. Pick one and drop the other if you repack.
- `damaged` is a context no classifier can derive from a cell's six neighbours — it is a
  state the consumer knows and the grid does not. The substitution table is in the manifest;
  wiring it is Demigol-side work.
- **Which damage set to wire.** `damaged` needs nothing and is 36/255 too dark on torn
  steel; `fractured` closes that exactly and needs `ChunkDresser` to write a two-element
  `sharedMaterials`. Both ship, both are verified, and the second costs the project no
  new material — `shard_fracture` is already resident for #663's debris, so the batch
  count stays intact-kit plus everything-broken either way. Wiring `fractured` also means
  the fracture atlas must be resolvable from the `demigol_shards` delivery, since this
  package deliberately ships no copy of it.

## Not here

- **No LOD**, per the contract.
- **One family, not four.** The generator is parameterised by patch table and box list, so a
  second family is a table edit and not new machinery. Parked on #653; the atlas is 16/16
  full, so a new family needs a new atlas.
