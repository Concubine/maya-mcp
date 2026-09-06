# The Kethran — armour, scars and face pass

Written by the Claude session that did it, 2026-09-06. Read `README-HANDOFF.md`
(in the parent folder) first for the base model; this covers only what this pass added.

Scene: **`kethran_armored.ma`**. Opened from `kethran_textured.ma`, so everything in the
previous handoff still applies.

---

## What was added

| | |
|---|---|
| **Dermal armour** | 12 grown keratin plates, merged into one mesh `\|kethran\|armor` (20,880 faces, 12 shells): shoulder ×2, hip ×2, jaw ×2, flank scutes ×6 |
| **Scars** | 6 strokes — 3 rakes across the left haunch, 1 across the left shoulder, 1 on the left neck, 1 right haunch, plus a muzzle scar. Cut as geometry AND painted into the albedo and height maps |
| **Broken horns** | Right horn snapped with an oblique laminated fracture + a standing shard; left horn worn to a blunt irregular stub |
| **Face** | Eyelids (upper hooding, lower rising), brow ridges, orbital creases, a lip line the full length of both jaws, nostril pits with raised rims, masseter/jaw mass, a chin. Eyes retracted 7% into the skull |

New material `plateKeratin`; new maps `armor_ao/curvature/height`, `plateKeratin_color_detail`,
`hide_albedo_v10.png`, `body_height_v7.png`.

## The one technique worth keeping: plates grown from the body's own faces

Don't model a plate and lay it on the hide — the contact will always read as two
objects. Instead:

1. Select a patch of the **body's own faces** by an ellipse in (y, z) plus an
   outward-normal test.
2. **Clean the selection topologically** (`clean_region`): a normal test punches
   pinholes wherever the sculpted hide wobbles, and those became actual holes in the
   plate. Morphological closing on the face-adjacency graph, then drop stragglers,
   then keep the largest connected component.
3. `cmds.duplicate` the body, delete every face outside the patch.
4. `polyExtrudeFacet` with `keepFacesTogether=True` and **`localTranslateZ` only**.
5. Relax the rim ring (`relax_rim`) — the ellipse cuts the quad grid into a staircase
   and, once the rim is hard, that staircase shows as sawteeth.
6. Crease the rim, one `polySmooth` division, then dome the outer face.

The plate's inner surface **is** the hide, so there is no gap, no float and no
interpenetration to hide.

**Three things that did NOT work, so you don't retry them:**

- `polyExtrudeFacet(offset=...)` with `keepFacesTogether=True` offsets **every face
  individually** → a honeycomb lattice of separate cells, not a tapered plate.
- `polyBevel3` on the extruded patch → exploding shards, because the rim
  self-intersects where the source patch spans a fold in the body.
- A `polySmooth` without creasing the rim melts the plate into a soft pillow. The
  hard rim is the entire difference between "armour" and "swollen muscle".

## The material lesson

The first material — near-black, glossy, `coat 0.22` — read as **plastic pads bolted
on**. Real dermal armour sits in the *same colour family* as the surrounding hide; the
difference the eye reads is **roughness and grain**, not albedo. Final: `base` 0.42
over the wear composite, roughness 0.50, specular 0.45, **coat 0**.

Then the reverse failure: with `wear` composited in, the plates went *too pale* and
read as bald/mangy patches. `base` is the dial that fixed it.

## Scars: how they were registered, and why the first three attempts failed

Registration is exact and needs no bake:

1. Walk the stroke **along the mesh** (`walk()` — step vertex-to-vertex toward a
   direction using connectivity). Every point is on the surface by construction.
   *Snapping a hand-drawn 3D polyline to the nearest vertex does not work* — my
   guessed points landed up to 23 cm off the surface and the "line" scattered.
2. BFS out from the chain (3 hops) for a weighted band.
3. Export each affected vertex's **UVs** to `maps/scar_uv.json`.
4. `build_scars.py` splats those UVs into (a) pale scar tissue in the albedo and
   (b) a **flattened height map** — healed tissue has no grain, so a scar reads as a
   slick channel through rough hide. **The flattening is the stronger of the two cues.**

Three failures on the way, all diagnosed by making a debug texture rather than guessing:

- **Attempt 1** invisible. Painted a pure-red mask into the albedo → proved the UV
  flip (`v → 1-v`) and the registration were *correct*, so the cause was elsewhere.
- **Attempt 2** invisible. Measured the written capture with numpy: the scars were
  there (2615 px at 1.6× the body's median luma) but ~0.5% of body pixels — too thin
  to survive downscaling to preview size. **A scar has to be wide to read.**
- **Attempt 3** invisible. A green-marked debug texture showed the strokes were landing
  **underneath the armour** — I had cut the rakes across exactly the band where I'd
  built the scute row. Moved them to the haunch, which is uncovered and lit.

If you add more scars: check they are on hide that is both **uncovered and lit**. On
this creature that means the haunch, the neck forward of the shoulder plate, the lower
foreleg and the muzzle. The upper flank is all armour now.

## Honest critique — what is weak

1. **The scars are still marginal at full-body distance.** They read in the Arnold
   heroes and on the haunch in the turntable, but they are a subtle effect, not the
   war-record the brief implies. They read best as *smooth channels*, less as pale
   lines; the albedo contrast is still doing less work than the height flattening.
2. **The plates are all the same shape.** Every one is a domed ellipse. Real dermal
   armour varies — keeled, ridged, polygonal, overlapping. These read as a family of
   the same object at different sizes, which is a giveaway at the shoulder/hip pair.
3. **The shoulder plate carries a crack** inherited from a fold in the body surface
   under it. It happens to read as battle damage, and I kept it — but it was an
   artefact, not a decision, and it is not mirrored by anything on the other side.
4. **The left horn's tip still has a flat worn face** visible from directly behind.
   Its cap had only 25 vertices — too coarse to fracture convincingly — so it was
   domed into a worn stub instead. It is honest for an old animal but it is a
   resolution dodge.
5. **The face is better but not characterful.** It now has lids, brow, lip line,
   nostrils and a chin, and the eye no longer reads as a marble pressed into clay.
   But there is still no mouth *opening*, no ear detail worth the name, and no
   asymmetry in the face at all.
6. **The jaw plates read as lumps on the cheek** from some angles. They were moved off
   the eye (where the first attempt put them, which looked like a lesion) but they are
   the least convincing of the twelve.

## Traps for the next session

- **Never send two `mcp__maya9879__*` calls in one message.** Two concurrent calls
  killed the Maya process outright — connection reset, PID gone, scene lost if unsaved.
  One call per message.
- **`\|kethran\|armor` carries a local scale of 1.1037** (= 1/0.906), which
  `maya_parent` added to preserve world position when the combined mesh was moved back
  under the group. Freeze it before any export, and re-check the silhouette after.
- **Maya caches a texture by path.** Overwriting a PNG in place renders bit-identical
  frames. Every texture iteration here needed a new filename — the albedo reached
  `hide_albedo_v10.png` for this reason alone.
- **The viewport and Arnold still disagree on bump by roughly 5×.** The hide bump is
  set to **9.0**, calibrated in *Arnold* because that is what the heroes ship through.
  It looks overdone in the viewport. Do not "fix" that.
- Sculpt ops through `maya_execute_python` (the horn fractures) **do not
  auto-checkpoint** the way `maya_sculpt_ops` does. Save first.
