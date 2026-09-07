# The Kethran — handoff

> **Moved 2026-09-07 (Redmine #870):** the asset's home is now `D:\develd-assets\kethran\`, including `kethran2/` (the armour + texture pass) which no longer lives here. What stays in this folder stays only because `kethran.ma` is a test fixture for `evals/uv_normalize_live.py` and the two bake-hang probes. Do not add art here.

**Read this before touching the scene.** Written by the Claude session that built it,
2026-09-05, for whoever picks it up next (human or agent).

---

## What this is

A mythical creature built entirely through the `maya-mcp` MCP tools, in a live Maya 2027
session, as an exercise in (a) making something that reads as a real animal and (b)
finding out where the tooling fights you. **The second half is the more valuable output** —
see `TOOL-FRICTION-REPORT.md`, which is written for the MCP developer, not for an artist.

Nothing here belongs in the `maya-mcp` repo. It is a tool repo, not an art repo.

## Files

| File | What it is |
|---|---|
| `kethran.ma` | **The scene.** Final. Maya 2027, linear unit **cm**. |
| `kethran_hero.png` | Hero three-quarter, 1400 px, viewport capture (not Arnold — see below) |
| `kethran_turntable.png` | 8-view contact sheet |
| `kethran_ortho_side.png`, `kethran_ortho_front.png` | Orthographics |
| `gen.py` | Generates the loft cross-section tables. **This is the actual source of the body form.** |
| `body.json`, `head.json` | Output of an earlier two-piece version of `gen.py`. Superseded — kept only as a record. |
| `kethran_recovered.ma` | A checkpoint copy. This is what saved the model when Maya had to be killed. Do not delete until you have your own backup. |
| `kethran_hero_viewport.png` | **Discard.** The rejected too-close frame with the bad lumpy hide. Kept as evidence for the friction report. |
| `maps/` | **Empty.** The texture bake hung and wrote nothing. |
| `checkpoints/` | Auto-checkpoints Maya wrote here after a restore. |

## Scene structure

Everything is under one group, `|kethran`, scaled **0.906** uniformly about the origin
(that is what puts the withers at exactly 200 cm — do not "clean up" that scale without
re-checking the height).

```
|kethran
├── body     57,724 tris   material: hide       <- torso+neck+skull+legs+tail+ears, ONE mesh
├── horns     5,950 tris   material: horn       <- both main horns + both forward tusks
├── crest        84 tris   material: crestKeratin
├── hooves      432 tris   material: claw
├── eyes      1,040 tris   material: eyeball
├── pupils      576 tris   material: pupil
└── ears        252 tris   material: membrane
```

Measured, not intended:

- Shoulder (withers): **199.9 cm**
- Nose to tail-tip: 380 cm; head-body 321 cm (1.6x shoulder — correct bovid proportion)
- Horn tips: 262.8 cm
- Total: 66,058 tris

Lighting is `maya_setup_lighting` `three_point` at intensity **2.2**. That value is tuned
for the **viewport**, not for Arnold. See the render warning below.

## The one decision that mattered

**Rump, torso, neck and skull are a single 16-section loft.** Not three parts joined.

I built the body three times:

1. Separate head mesh -> read as a bulb on a stick.
2. Body+neck merged, head separate -> still a visible collar ring at the jaw.
3. **One surface, rump to nose** -> the neck/shoulder and neck/head joins simply stopped
   existing as problems.

Then the limbs and tail were swept as single tapered forms and **boolean-unioned into that
body**, then smoothed once, so shoulder and hip are fused geometry rather than overlapping
shells. The skull masses (cranium, brow, cheeks, jaw, eye sockets, nostrils) were **grown
out of the existing surface** with `soft_move` / `inflate_region`. I first tried adding
them as spheres and they read unmistakably as balls stuck on — if you extend the head, grow
it, don't bolt it on.

**If you rebuild the body, edit `gen.py`, not the mesh.** The 16-section cap on
`create_curve_form` loft is the binding constraint; that is why the section table is so
tightly budgeted.

## Honest critique — where it stops reading as real

Ranked by how much it costs the illusion:

1. **The hide is plastic.** One flat albedo. No grain, no dirt, no countershading, no pore
   or wrinkle. This is the biggest single failure and it is not for lack of trying — both
   available routes failed (bake chain hung; geometric noise had no usable window). This is
   the first thing to fix.
2. **Muscle reads as soft upholstered pads, not muscle bellies.** `inflate_region` gives a
   radial bump with smooth falloff; real muscle has a belly and a tapered tendon insertion.
   Passes at turntable distance, fails in the hero shot.
3. **Lower legs are too columnar.** They do now have a fetlock, carpus, forearm and hock —
   all placed by measuring the mesh — but the cannon is a smooth tube with no tendon groove
   and no bone/flexor separation.
4. **The head is small for the horns.** The horns won the silhouette argument and the skull
   never caught up.
5. **No mouth.** There is a lip crease and there are nostrils, but no actual mouth opening.
6. **The ears are weak.** Third attempt, still reading as a cone rather than a cupped ear,
   and mostly hidden under the horn boss anyway.

**It reads as real at silhouette and mid distance. It stops reading closer than ~3 metres.**

## What I would do next, in order

1. **Texture, not geometry, for the hide.** Do NOT reach for `displace_noise` — I measured
   its usable window at this density and it is empty (see friction report item F-6). Get
   UVs and a bump/normal map on it instead. The bake tool hung on me; try a much smaller
   resolution and one map at a time before trusting it with a long job.
2. Rework shoulder/hip muscle so each mass has an insertion, not just a belly.
3. Give the head another ~10-15% and cut a mouth.
4. Redo the ears from a cupped form.
5. Only then think about a skeleton / bind.

## Working rules learned the hard way

- **Do not guess sculpt coordinates.** `soft_move` / `inflate_region` refuse when the centre
  is farther than `radius` from the surface. There is no structured tool to find a point on
  the surface, so measure the mesh first (I used `maya_execute_python` with
  `OpenMaya.MFnMesh.getPoints`, banded by y, printing the centroid per band). Guessing cost
  me five refusals; measuring made every subsequent op land first time.
- **Sculpt ops are not undoable** and every call reuses the same auto-checkpoint id, so only
  the most recent is recoverable. **Copy the checkpoint `.ma` to a safe path yourself before
  anything risky.** That is the only reason this model survived a forced Maya restart.
- **Reshoot any capture whose colours look wrong** before believing it. Four frames came back
  flat chroma-green in this session (VP2 materials-unbound). Every one was a
  `lighting: 'scene'` capture, and the other angle in the same call was always fine.
- **The viewport and Arnold disagree on material values here.** The rig intensity of 2.2 in
  this scene is correct for the viewport and roughly 2x too hot for Arnold. If you render
  with Arnold, expect pale washed-out clay and re-tune the lights — do not "fix" it by
  brightening the materials, which is the wrong end of the problem.
- The green frames were accidentally useful: they *are* the pure-silhouette test, and the
  creature reads clearly in flat colour as a heavy-shouldered horned quadruped with a dorsal
  crest. Silhouette is the part of this model that works.

## Environment this was built in

- Maya 2027, launched minimized on port **9879** with cwd `D:\devel\maya-mcp`, i.e. the repo
  plugin. Repo `main` was at **e0d56b1** at session start. I did **not** verify which plugin
  copy actually loaded — if that matters to a bug repro, check it.
- Only `mcp__maya9879__*` tools were used. Never `mcp__maya__*` (that points at a human's
  live session on 9877).
- No repo files were edited, nothing was committed, no test suite was run.

## Note on where this folder lives

It was written to a **session-scoped temp directory**. Move it somewhere durable before you
rely on it. `D:\devel\maya-mcp-art\` is the art territory per the project conventions —
but that path is another agent's working area, so confirm with the owner before writing into
it.
