# Next session — start here

Written 2026-08-16, at the end of the #601 golem build. Supersedes the previous
transition prompt in this file.

Working directory **must** be `D:\devel\maya-mcp` — running from
`D:\devel\Demigol\maya-mcp` loads the wrong project's memory.

## Where things stand

**#601 is Resolved.** The articulated golem is built. Branch
**`scene-unit-truth`**, **15 commits, unmerged**, tree clean, 833 tests green.

Read this first, before re-planning anything:
**`evals/golem_run_2/tool_gaps_report.md`** — the ranked findings are the run's
actual product. The model is the receipt.

What exists: 29 chunks, 14,066 tris, 5.0272 tall, one tree at `golem_C_pelvis`,
every pivot at its proximal socket, scene at `evals/golem_run_2/golem.mb`, three
hero PNGs beside it. Zero escapes for geometry; one recorded escape for
artifacts.

Fixed in-run, `aa91c0f`: **`setup_lighting`'s dome had never lit anything**. It
used `cmds.createNode`, which builds the node without wiring it into Maya's
lighting network — so it drew as background and illuminated nothing. Since that
preset exists precisely because a three-point rig cannot show a metal, every
metallic material ever judged through `environment` or `hdri` was judged unlit.

Raised: **#638**, **#639**, **#640**. **#636** still open.

## Art direction changed mid-build — do not quote the old story

The user deleted the aleph rune and committed to the visor: *"this guy is
shaping up to be an iron giant which is also good — keep with the place."* The
glow is now a **tracer eye scan**, a recess across the visor with a bright core
and three fading bars, parented under the brow.

Anything that still says "seam glow from distance to the rune" is stale —
including the emet → met kill condition in the motion handoff spec. The rule
survives (detaching the brow still kills the light) but the reason is now
physical rather than symbolic: the brow *carries* the emitters.

## The work, in order

### 1. The delivery package — recommended, ~1 hour

`evals/golem_run_2/` is a benchmark result, not a package. The precedent is
`evals/demigol_structures/`: `.fbx` + `.png` per piece, `manifest.json`,
`README.md`. Missing:

- **FBX export. There is no MCP tool for it at all** — it costs an
  `execute_python` escape, and that absence is itself a finding worth recording.
- **Gate the FBX BYTES, not the scene.** In-scene units pass
  (`export_metres_per_unit` 1.0, height 5.0272) and that proves nothing: #629's
  whole lesson is that the exporter is where units go wrong and every in-scene
  check is blind to it. These chunks carry **non-identity transform scales**
  from `assemble`, which is exactly the case that defect lived in.
- **Settle the scale question first — see below.**
- manifest (chunk list, pivot per socket, tri counts, atlas/material,
  destruction unit) and a README.

Worth doing because export is the last untested surface in this toolset, and a
29-pivot rig with non-identity scales is the case most likely to break it.

### 2. The scale discrepancy — settle BEFORE exporting

The motion handoff pins **1u = 0.8 m → 4.0 m rest**. The built golem measures
**5.0272** and declares **`export_metres_per_unit` = 1.0**, so it would export at
**5.0272 m, ~25% over** the pinned figure. Under the 0.8 convention 5.0272 u *is*
4.02 m — so the geometry is right and only the declaration is in question. Do not
guess; decide it, then gate the written file.

### 3. Merge `scene-unit-truth`

### 4. Optional / parked

- A short frame sequence of the tracer sweeping. A still can only show one sweep
  position, and the user has not said yes or no.
- Two motion questions the user wants to **discuss**, not have answered at them:
  `GrabReach = 4 m` against a real 2.56 m arm, and contact-pair cost at 29
  chunks.
- Lower priority, from `2026-08-15-open-actions.md`: stale triangle count in the
  hero manifest, `endcap` chirality coverage, the brick-pitch/mipmaps-off
  coupling, the revision-4 silhouette lever.

## Three honest negatives — keep them, they are load-bearing

- **The joins FAIL under SSAO.** Gasket collars show almost no contact
  darkening; they read as balls threaded on a limb, which is the exact thing
  #574 asked to be checked. A model note, not a tool note.
- **The body seam glow is invisible.** At 0.013–0.315 emission against a lit
  body the falloff is monotonic, verified, and does nothing. Left at measured
  values deliberately rather than quietly dialled up.
- Two of my predictions were wrong and are recorded as such: the kit's maps
  **do** read on creature shapes, and the black render was **not** metalness
  (it measured 0.0).

## Standing constraints

- Short, precise replies. Measured numbers over assurances.
- When a prior claim turns out wrong, say so plainly rather than moving on.
- **#579 is still open**: `maya_new_scene` after a boolean + isolate capture
  wedges Maya. This scene is full of both. Prefer restarting Maya.
- A green result from a stale deployed copy means nothing — Maya loads from
  `Documents/maya/scripts`, not the repo.
