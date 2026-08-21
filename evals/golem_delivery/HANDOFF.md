# Golem handoff package

Everything needed to bring the demolition golem into Demigol. Assembled 2026-08-16.

**Engine-side ticket: redmine #644** (`demigol` project, localhost:3000). Read it before starting —
it carries the measurements and the one decision that has to be made first.

## Provenance

| | |
|---|---|
| source repo | `D:\devel\maya-mcp` |
| commit | `70a409f675ecccfd1a6fd045885307bb9917f3d2` |
| tree state | clean |
| source path | `evals/golem_delivery/` |
| delivery authored | 2026-08-16 09:44–10:17 |

If you need to re-sync, go back to that path in that repo. This folder is a **copy**, so treat the
commit above as its identity — the project has already been bitten once by a vendored record
disagreeing with the live tree.

## What is in here

### `delivery/` — the contract. All five files matter.

| file | what it is |
|---|---|
| `golem.fbx` | the geometry. Unit-gated: 4.02173 m tall, one root, **zero non-identity node scales** |
| `manifest.json` | orientation, origin, per-chunk colliders, mass shares, materials, emission rule |
| `chunks.json` | per-chunk detail including `break_impulse_mult` |
| `poses.json` | five poses, absolute local euler XYZ for all 33 nodes |
| `README.md` | the modeller's own handoff notes |

### `textures/` — the shared kit atlas

`kit_albedo.png`, `kit_mask.png`, `kit_normal.png` (4096², albedo + mask + normal).

**These are here for completeness only. DO NOT vendor them into Demigol.** They are already in the
game at `unity/Assets/Art/demigol_kit/`, and the golem's ten materials all sample that same atlas by
design — one material, one batch, and a consumer that has the buildings already has the textures.
Bind to the existing kit material.

Related: **redmine #630** — Unity currently imports this 4096 atlas at 2048 because
`ArtImportSettings` never sets `maxTextureSize`. Effective density is 56.9 px/m, not the delivered
113.8. The golem inherits that halving. Worth fixing in the same pass.

### `reference/` — renders, for orientation only

`hero_*.png` and `poses_side.png`. **The hero renders predate the final bake** — same shape,
different number of metres. They are not fresh frames of the delivered file. Do not measure anything
off them.

## Measured facts (verified in Maya against the delivered file, 2026-08-16)

* **33 mesh nodes** = 29 chunks + 4 tracer emitters. **14,130 triangles.**
* **4.02173 m** tall × 2.72834 wide × 1.2423 deep.
* **Metre-native with identity scales.** The 0.8 conversion is baked into the vertices, verified to
  1.2e-7. Nothing carries a scale factor. This is *unlike* the kit and hero deliveries, where unit
  scale had to be adjudicated as a two-path answer (#628) — here there is nowhere for a unit error
  to hide.
* **+Z forward, Y-up.** Measured, not assumed.
* Origin between the feet, floor at y = 0. One tree, root `golem_C_pelvis`, translate+rotate only,
  six levels deep at the deepest.
* **Pivots are proximal joint centres**, not min-corner cell centres. This differs deliberately from
  the kit and hero conventions. Do not infer it from those.
* **Colliders are limb-shaped**: 13 capsules, 3 spheres, 17 boxes, each declared in its own chunk's
  local space with centre, rotation and dimensions, so it stays correct when the chunk turns.
  `max_escape_m` 0.096–0.132 on the limb capsules, published rather than hidden.
* **Mass ships as volume and share**, not kilograms — total 5.265664 m³ plus a per-chunk
  `mass_fraction`. This engine's mass unit is abstract (a 3 m steel cell = 4.0).
* **Five poses**, each already mapped to game state that exists: `crouch` on `ChargeFraction` 0→1
  over the 1.1 s wind-up, `rest` idle, `extend` on release, `air` airborne, `absorb` on
  `OnLanded(speed)` scaled by speed. Every pose is rotation-only; no chunk's translate moves.
  Set the values, do not add them.
* **Arm reach: 2.5528 m** shoulder pivot to furthest fist vertex, against `GolemTuning.GrabReach = 4`.
  Grab currently extends ~1.4 m past the arm and will look like telekinesis without a lunge or step.

## Decide this before writing code

**Is the golem an articulated PHYSICS rig, or a posed VISUAL over the existing capsule controller?**

The delivery assumes the former in places — it specifies joint limits and an asymmetric
`ConfigurableJoint` for the shoulder, because release swings it 210° in one beat. The game assumes
the latter: a capsule controller whose feel has been tuned across four milestones.

These are very different tickets. The answer also decides whether golem locomotion stays
deterministic and server-runnable, which the asymmetric-hunt arc requires (soldiers are a future
*player* kit and the golem is the other half of that matchup).

Brainstorm it. Do not pick by default.

## Things that will move, and should be budgeted rather than discovered

* **The golem gets 1.68× taller** — 2.4 m capsule → 4.02 m body. Camera (`CamDistance 8`,
  `CamHeight 1.5`), `HandoffClearance` (derived from `BodyRadius`), `ShockwaveCrushRadius 4.5` /
  `ShockwaveShoveRadius 9`, and the whole momentum/jump feel were all tuned against 2.4 m. **Expect
  a feel re-tune, and expect it to be the real cost of this work.**
* **Near-field pile interaction** is a function of the golem's capsule keeping its own rubble awake
  (the M5 seed). A different body shape changes it.
* The art import pipeline (`Assets/Editor/ArtPipeline/`) knows two delivery **kinds**, `Hero` and
  `Kit`. A rig is neither. It will need a third.
* `BuildingView.cs:99` hard-codes `mf.sharedMesh = Graybox.CubeMesh` on detach, deliberately,
  because that reassignment clears the static-batch record. If golem chunks detach, check whether
  that mechanism applies here at all.

## Known limits, stated by the delivery about itself

* **The 4.64 m reveal is not in this geometry.** Straightening the legs from rest buys 0.083 m, not
  0.64; `extend` reaches 4.137 m at the crown. The 5.063 m bbox figure is the fists overhead, and
  calling that the golem's height would be a lie. A real 4.64 m needs a deeper modelled crouch —
  a model change, not a pose.
* **The joins fail under SSAO.** Gasket collars show almost no contact darkening and read as balls
  threaded on a limb. Confirmed by inspection. Relevant once the presentation layer (#619) lands.
* **The body seam glow is invisible** at its measured emission (0.013–0.315) against a lit body. It
  was left at measured values rather than quietly dialled up. Only the visor tracer reads.
  Note this is the design's best damage-communication idea — seam glow sits at chunk join
  boundaries, exactly where detachment happens — and it currently shows nothing.
* **The glow is cold cyan** `(0.45, 0.80, 1.00)` on all five glow materials, against a recorded art
  direction of industrial warning amber. See the art status below — do not bind emission colours
  until it is settled.

## ART STATUS, 2026-08-16 — read before binding any material

The geometry is production-ready. The **surfacing is not**, in three specific ways. All three were
established by experiment against this exact file, not by reading the manifest.

**Tracked as redmine #656** (High). **See `art_findings/` in this package** — four frames, identical
camera and lighting, materials the only variable, with `art_findings/README.md` explaining what each
one settles.

### 1. There is no seam glow, and Unity cannot recover it

The decided art direction calls for *crack mask × steep radial falloff from the brow rune, with seam
glow at chunk join boundaries so damage reads for free.* **None of that mechanism is in the asset.**

Measured: the five glow materials are assigned to **whole chunks** — brow, head, neck gasket, chest
girdle, both shoulders — and both emission colour and emission weight are **flat scalar values with
no texture driving either**. There is no crack mask, no seam mask, no falloff.

Raising the emission was tested at 12×. It produces **glowing lamps, not seams**: the head becomes a
uniform luminous blob that swallows the visor detail, and the shoulders become flat plates. With no
mask to localise the light there is nothing for a higher number to reveal.

**Consequence for the engine:** treat golem emission as a per-chunk uniform tint for now. Do not
build a damage-reads-through-seam-glow feature against this asset — it cannot support one. Recovering
it requires a mask channel from the modeller, not a shader change.

### 2. The glow colour is unresolved, and it is coupled to the body colour

Rendered three ways from the same camera and lighting:

| body | glow | result |
|---|---|---|
| brick (as delivered) | cyan (as delivered) | visor **pops** — the only cool note on a warm body |
| brick (as delivered) | amber (per direction) | visor **vanishes** into the brown |
| grey stone | amber | visor **pops** — reads as a hot machine |

So the recorded direction is not simply "wrong": amber assumes the grey stone body the direction also
specifies, and this delivery is clad in the **city's** warm brick atlas instead. Pick the pair, not
the glow alone.

### 3. Under AO there is no surface

Strip the texture and the model is spheres, cylinders, boxes and a slab, with almost no contact
darkening at the joins — gasket collars read as balls threaded on a limb. Every bit of detail in the
beauty renders is the albedo doing the work. That is survivable at distance and will show up the
moment the presentation layer (#619) puts real lighting on it.

### What this means for scheduling

Nothing here blocks importing the FBX, wiring colliders, masses, poses or the controller — that work
can start now against production-quality geometry. It blocks **finalising materials**. Keep emission
colour as a single named constant so the decision costs one edit later.

## Geometry independently re-verified, 2026-08-16 — it is exact

`golem.fbx` was imported into an empty Maya scene and measured **per vertex, in world space, across
all 33 meshes**:

| | measured | manifest / gate |
|---|---|---|
| lowest vertex | −0.006729 m | −0.0067 m |
| highest vertex | +4.015001 m | — |
| **height** | **4.021730 m** | **4.02173 m** |

Delta: **0.000000 m**. Both feet are symmetric at −0.00673 m. 33 mesh nodes, 14,130 triangles, one
root, zero non-identity scales. The delivery's unit gate is correct and the FBX is trustworthy.

**A warning for whoever measures this next.** Maya's bounding-box queries give three different and
all-wrong answers on these meshes:

| method | left foot min y |
|---|---|
| vertex scan (`xform -q -ws -t`) | **−0.00673 m** ← truth |
| `exactWorldBoundingBox` | −0.07752 m |
| `polyEvaluate(b=True)` | −0.07752 m |
| cached `.boundingBoxMin` | −0.01738 m |

An earlier pass of this document reported a 7.5 cm left-foot sink as a real defect on the strength of
`exactWorldBoundingBox`. It was a stale cached bbox, not geometry. **Measure vertices.** The
delivery's own gate reads the FBX bytes with no Maya in the loop, which is why it was right and the
convenient in-Maya query was wrong.
