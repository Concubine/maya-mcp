# Demigol — kit of parts (family 1, **revision 3**)

**58 one-cell pieces, 4,236 triangles, ONE material, three maps.** Not buildings.
The generator already decides per cell what material sits where and which faces are
exposed; this is the vocabulary it draws with, so it dresses all ~50 buildings and
anything generated later comes dressed for free.

Revision 3 answers Demigol **#677**: the missing steel pieces, and damage states.
Regenerate with `evals/demigol_kit.py`.

| file | what |
|---|---|
| `demigol_kit.fbx` | all 58 pieces, each at the origin with its pivot at the cell centre |
| `kit_albedo.png` | 4096² albedo atlas, 4 × 4 patches — **byte-identical to revision 2** |
| `kit_normal.png` | tangent-space normal, same layout — **byte-identical** |
| `kit_mask.png` | R = metallic, G = smoothness, **A = smoothness** — **byte-identical** |
| `contact_sheet.png` | every piece, individually framed |
| `tiling_proof.png` | the revision-2 wall, regenerated unchanged, as the baseline |
| `tiling_proof_steel.png` | **new** — a 5 × 5 wall of revision 3's own pieces |
| `soffit_underside.png` | **new** — the deck soffit from the one side it is for |
| `damage_detail.png` | **new** — the six damage states, close |
| `manifest.json` | per piece: role, context, variant, triangles, budget, **utilisation %**, **measured outset** |

## What revision 3 changed

**17 new pieces, 41 → 58. No existing piece was touched, no patch colour moved, no new
material, no new atlas.** The three PNGs above are byte-identical to revision 2 — every
new mesh lands on the existing 16 patches, so the whole city is still one draw call and
#653's new-family question is untouched.

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

### 2. Damage states — six, in a `damaged` context

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

**The option not taken**, recorded so it is a decision and not an omission: give the damage
pieces a second submesh bound to `shard_fracture`. That is **zero new materials for the
project** — #663 already ships it, so the batch count stays intact-kit plus
everything-broken — and it would close the steel and glass gaps outright. It needs one
consumer change: `ChunkDresser` writing a two-element `sharedMaterials` for `damaged` cells
where it writes a single `sharedMaterial` today. Not taken here because a piece that
arrives unusable until someone changes the consumer is worse than a piece that drops in and
is 36/255 too dark on one surface. **Say the word and it is a re-run, not a re-model.**

## Utilisation, not a pass mark

| | pieces | triangles | budget | utilisation |
|---|---|---|---|---|
| revision 2 | 41 | 2,364 | 4,720 | 50.1% |
| **revision 3** | **58** | **4,236** | **6,760** | **62.7%** |

All 17 new pieces sit at 9 or 10 boxes — **108–120 of 120, i.e. 90–100%**. Revision 1
passed while spending 6% of its budget, and the pass mark is what hid that.

## Verification

| check | result |
|---|---|
| geometry failures | **0** across 58 pieces |
| shading groups | **1** (`kit_materialSG`) |
| UV range | 0.0079 … 0.9921, every piece inside its own patch |
| contact-sheet tiles | 58 rendered, **0 blank** |
| damage detail | 6 rendered, 0 blank |
| soffit underside | 3-cell run, 0 blank |
| damage substitution | 6 states, every skin matched to an intact counterpart |
| units | metre vertices, **zero** non-identity node scales, gated on the FBX **bytes** |
| artifact vs manifest | 58 node names match exactly, triangles agree, declared outset ≥ delivered |

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

Two more pieces were re-authored for the same class of reason, both found in the render and
neither visible to any check:

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
- The `shard_fracture` submesh option above, if the steel gap matters more than the drop-in.

## Not here

- **No LOD**, per the contract.
- **One family, not four.** The generator is parameterised by patch table and box list, so a
  second family is a table edit and not new machinery. Parked on #653; the atlas is 16/16
  full, so a new family needs a new atlas.
