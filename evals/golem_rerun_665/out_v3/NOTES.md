# NOTES — golem v3, the golem learns to move

Ticket #713 (lineage #665 → #712 → #713). Delivered into `out_v3/`.
`out/` (the v2 run of record) and `out_v21/` (the polished baseline) were never
written; the first action of the session was a save-as, before any edit.

## Iteration, not rebuild — and why

I opened `out_v21/golem_v21.ma` and built on it. A rebuild would have been vandalism:
v2.1 is polished, its core-containment defect is fixed, and the v3 ask is purely
additive — *make it animable without breaking anything*. The whole risk of this
iteration lives in that word "without", so the first thing I built was not a rig but a
**re-runnable verification sweep** in Maya's persistent namespace, reproducing every
published v2.1 number: 29 meshes, 29/29 watertight, 0 live scales, 11,828 tris,
4.06675 m, every `core_*` ≥ 2 cm inside its plates. I re-ran it after every structural
step and diffed against the baseline.

It earned its keep immediately, by catching a bug of *mine*: my first watertight test
used `polyListComponentConversion(..., border=True)`, which returns every edge of a
whole-mesh conversion rather than the boundary edges, and cheerfully reported 0/29
watertight on a model that is provably 29/29. **A verification sweep that disagrees with
a published number is guilty until proven innocent.**

Final state: the only difference from the v2.1 baseline is **17 added joints**. Nothing
removed, nothing deformed, no skinClusters, geometry identical to three decimal places
on every re-measured mass.

## How I made it animable

The hard design problem, stated by DESIGN_V3: the creature is a rigid chunk hierarchy
with no skeleton, clips key joints only, and whatever I chose could not break the
physics contract (primitive colliders, breakable pieces, pattern-matchable names).

I considered three shapes and rejected two:

1. **Skin the 29 chunks to a skeleton.** Rejected. Rigid kiln plates must not bend,
   `closestDistance` weighting would bleed a thigh's vertices onto the shin joint, and a
   skinned mesh actively fights "pieces rip off and keep colliding".
2. **Constrain the groups to joints.** Rejected — constraint results don't reliably bake
   into takes, and it adds nodes that mean nothing to the consumer.
3. **Joints as rigid parents.** Chosen. 17 joints at the exact measured pivots; each
   `golem_<segment>` group re-parented under its joint, local translate collapsing to
   zero. Rotating a joint moves a whole chunk. No deformers, no weights, no double
   transform, every name preserved.

The satisfying part is that the file now supports **two complete readings of itself**.
A physics consumer can ignore the joints entirely — the chunk list in
`golem_physics.json` is self-contained, exactly as in v2.1. An animation consumer drives
the joints. Same 62 nodes, same 29 meshes, one asset.

One decision inside that is worth defending: **every joint has `jointOrient = (0,0,0)`
and a world-aligned frame.** The rig therefore speaks one language — a joint's local
`rx` is the sagittal hinge, which is what the chunk limits, the pose data, and the v2
sign convention have always meant. It cost me an `execute_python` escape (below), and it
is why the five pose targets transferred to the new rig **with their numbers unchanged**.

## What fought me

### The session-hygiene hang that cost the most time

`maya_author_clip` did not return on a deliberately trivial test — three keys, one
channel, a throwaway two-joint skeleton. It blew past the tool's own 120 s ceiling and
was still spinning **30 minutes** later, one core pegged at 101%, Maya not responding,
every subsequent call `BusyError`. `author_clip` exposes no `timeout_s`, so the advice
its own error prints cannot be followed.

I diagnosed it from outside Maya rather than guessing: port 9879 → PID 7280 (`maya.exe`,
the only editor running); three visible windows, all `enabled=True`, so **no modal
dialog** — the leftover "Warnings and Errors" box from the v2 session was a red herring.
What was *not* a red herring was the **Arnold RenderView left open from the v2 hero
render**. `create_skeleton` (pure DAG work) had returned instantly; the first call that
touched keyframes and the scene time unit wedged — the signature of an IPR render
re-triggering on every scene mutation.

I did not kill the process. `Win32_Process` showed Maya was launched by hand
(`maya.exe`, no args, parent `explorer.exe`), nothing respawns it, and BRIEF_V3 forbids
the one repo that would document how the session is meant to come up — so killing it
risked ending the task rather than unblocking it. I stopped, reported, and wrote the
state to disk. After the user restarted Maya with the RenderView closed, **the identical
call returned instantly.**

The lesson is not about `author_clip`. It is that a long-lived Maya accumulates
invisible state, and an idle IPR view turns every subsequent edit into a render. Close
the RenderView before authoring animation.

### Wall 1 — one FBX is one take

Answered by experiment before I touched the asset, which is why it cost minutes instead
of a rebuild. Two clips on two skeletons coexist happily in the scene; the export then
refuses, verbatim:

```
2 skeletons carry a clip (probeA_root, probeB_root) - one file is one take
```

So **multiple named takes in a single FBX is not expressible through this toolset.**
DESIGN_V3 asked for "the FBX carries named animation takes"; what I can deliver is one
FBX per take. That is a normal game-pipeline shape, so the deviation is mild — but it is
a deviation, it is stated at the top of the engine README, and it has a second-order
consequence I would rather the engine team hear from me than discover: because the scene
can only hold one clip at a time, **the delivered `.ma` cannot contain both takes.** It
ships at rest, and `golem_takes.json` carries both takes' key data so either can be
rebuilt exactly.

### Wall 2 — a take *can* carry translation

The happier answer. `root_position` keys `Lcl Translation` on the clip's root joint, and
it survives into the file: verified from the exported bytes, 3 curves, 31 keys. Better,
**a non-root joint is accepted as a clip root**, which is what made the visor scan
expressible at all — `jnt_tracer` sits deep in the body hierarchy and still takes
translation keys while the head stays put.

### Wall 3 — the previewer cannot see this rig

`maya_preview_clip` refuses outright: *"no skinned mesh is bound to this skeleton — bare
joints render nothing"*, hint *"bind_skin first"*. The tool models animation as
deformation; my chunks move by rigid parenting, so they render and move perfectly while
the previewer declines to look. Binding a mesh purely to satisfy the previewer would
deform rigid plates and contaminate the asset, so I declined and built previews by hand
with a held camera.

The same assumption shows up as a **measurement blind spot**: `pose_skeleton` and
`author_clip` both report `max_displacement: 0` for this rig, every time, because they
measure skinned deformation only. A zero there does not mean the pose did nothing — I
verified motion by measuring mesh bounding boxes instead.

### The rig-frame trap

`maya_create_skeleton` cannot produce world-aligned joints at given positions. Passing
`orient: [0,0,0]` makes it **ignore `position`** and lay each bone at bone-*length* along
+X — `jnt_torso` landed at (0.33, 1.72, 0) when I asked for (0, 2.05, 0). Omitting
`orient` gives exact positions but auto-orients X at the first child
(`jnt_thigh_L` → `[71.8, −21.9, −173.0]`), under which local `rx` means a different axis
on every bone and the "all hinges are X" contract quietly dies. Neither is what a
sagittal creature wants, so I zeroed the orients and recomputed local translates in
python. Verified: max position error 0.0, max world-axes error 0.0.

### The physics manifest broke silently

Re-running `author_physics` after rigging returned **all 15 bodies with `parent: null`** —
chunk ancestry now passes through joints, which its DAG walk doesn't read as parenthood.
Because a parentless body has no joint, **every hinge override I passed was silently
dropped**. The tool did warn ("15 parentless bodies… parenthood is design intent then"),
and re-running with explicit `parent` per chunk fixed it. Worth flagging loudly: the
failure mode is a manifest that looks complete and has no joint limits in it.

## What I wanted and could not get

- **Multiple takes in one file.** Wall 1. The single most-wanted capability of this
  iteration.
- **A camera parameter on `maya_render_scene`.** Unchanged from v2 and still the thing I
  most want. `three_quarter` puts the camera at y 5.0 looking *down* 28°, which
  diminishes a colossus; `front` is level but frontal. The low-angle monument shot this
  creature deserves is still not expressible, so the hero is again a level portrait.
- **A previewer that renders rigidly-parented rigs**, or a `frame` parameter on
  `capture_viewport`. Between them these cost ~30 calls of hand-rolled preview
  production for what `preview_clip` does in one.
- **A tail that swaps sides.** For "core leading, tail following" to hold on *both*
  strokes, the tail must cross the core — about 0.35 m of extra travel that the 0.72 m
  recess cannot hold alongside the sweep. My lever makes the gap breathe (0.228 m
  stretched, 0.122 m compressed), which reads as inertia, but on the return stroke the
  tail leads. Fixing it properly is an art change, not an animation one: a symmetric
  tracer, or two tails that cross-fade. Documented in `golem_takes.json` rather than
  hidden.

## Surprises

- **Two clips coexist in the scene; only the export refuses.** I expected the ceiling at
  authoring time and found it at write time. That ordering matters: you can build a whole
  multi-take scene and only discover the limit when you ship.
- **Every exported animated FBX contains two takes** — the named one plus a duplicate
  `Take 001`. Any importer selecting by index gets the wrong one half the time.
- **Measurement beat looking, twice.** Both idle defects — sliding feet and 14 cm fist
  swings — were invisible in a still frame and obvious in centimetres of travel. For
  motion this subtle, "capture and look" is not enough; the honest test was a
  frame-by-frame landmark sweep, and then a **pixel difference** of first-vs-last frame
  to prove the seam.
- **The loop seams came out exact, not approximate.** 0.000 microns of joint travel, and
  max channel difference 0 across a full render. I expected to be arguing about
  tolerance and instead got equality.
- The v2.1 masses reproduced to three decimals after all the re-parenting — which is
  the most reassuring number in the whole run, because it is the one that proves the
  rig didn't touch the art.

## Honest self-assessment

The animation contract is met in the only shape the toolset allows, and every claim in
the handoff is measured: takes verified from exported bytes (including the proof that no
physics chunk node translates), loops verified to pixel identity, masses and colliders
re-measured rather than inherited, invariants re-checked after every structural step.

The weak points, plainly: **`idle` is conservative.** At 4 cm of head travel it reads as
alive at full size, and at thumbnail scale it reads as almost nothing — I chose the side
of "not dancing", and a reviewer who wanted more life would be right to push back; the
amplitudes are one number each in `golem_takes.json`. The **tail leads on the return
stroke**, and I could not fix that within the existing visor geometry. The **hero is
still a level front portrait** rather than the low-angle shot the creature wants, for the
same reason as v2. And the **procedural plate grain still does not survive FBX** — the
engine re-authors it, as before.
