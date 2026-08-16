# Next session — start here

Rewritten 2026-08-16 at the end of the delivery session. Supersedes the version
written earlier the same day, which listed the package and the scale question as
open — both are done.

Working directory **must** be `D:\devel\maya-mcp` — running from
`D:\devel\Demigol\maya-mcp` loads the wrong project's memory.

## Where things stand

**Everything golem is on `main`.** `scene-unit-truth` was fast-forwarded in and
is history. 819 passed, 1 skipped, tree clean.

**#601 Resolved** (the build). **#641 Resolved** (the delivery). The package is
`evals/golem_delivery/` — `golem.fbx`, `manifest.json`, `poses.json`,
`chunks.json`, `golem_metre.mb`, `poses_side.png`, three hero renders, and a
README that carries the whole story. Regenerate the manifest with
`python evals/golem_delivery_package.py`; it refuses to write one for a file
that fails the gate.

The run's ranked findings are still `evals/golem_run_2/tool_gaps_report.md`.
That directory is the **benchmark result**, not the delivery — do not ship from
it, and note its `golem.mb` is the pre-bake 5.0272-unit scene.

## What this session settled, so it is not re-litigated

- **Scale: bake the 0.8.** 5.027162 units x 0.8 = **4.02173 m**, metre-native,
  identity scales. Both halves of the motion spec hold at once.
- **The bake was not a freeze** — world translations and pivots x0.8, scales to
  identity, vertices recomputed from the new world matrix. Exact to 1.2e-7.
- **Poses are per-chunk ABSOLUTE local euler**, five of them, rotation-only,
  `rest` == what the FBX already carries.
- **Colliders are fitted, not bbox'd**, in chunk-local space: 13 capsules, 3
  spheres, 17 boxes.
- **The gate reads the BYTES.** `check_rig_delivery` (height, one root, identity
  scales, metre declaration), `check_poses` (every pose re-composed from the FBX),
  `check_colliders` (escape bound + mirrored pairs must agree).

## Open, in the order I would take them

1. ~~**#642 — there is no export tool.**~~ **DONE** — `maya_export_fbx` shipped
   on branch `export-tool`. `metres_per_unit` is required with no default and
   only `1.0` proceeds; the handler patches the unit declaration, **re-reads the
   bytes it just wrote**, and on any violation deletes the file and raises. The
   gate is two assertions — identity node scales and a declaration of 100.0 —
   deliberately *not* the one-root rule (the kit legitimately has 41 roots) or
   the ceiling (a per-delivery envelope, still in `evals/delivery_units.py`).
   Live: 8/8 on 9877, span 3.00000 m for a 3-unit cube, a 0.01 node scale
   refused with the file confirmed gone from disk.

   **Left open on purpose:** `evals/demigol_kit.py`, `evals/demigol_structures.py`
   and `evals/units_live.py` still export through `maya_export.EXPORT_PREAMBLE`.
   That string is now *composed* from the handler's own data, so there is one
   definition and a test pins it byte-for-byte — but migrating those three onto
   the tool would need a live art run to re-validate, so it is its own piece of
   work, not a tail of this one.
2. **#579 — `new_scene` wedges Maya. START HERE.** Re-ranked 2026-08-16 after
   reading the ticket properly; it had been listed third with the note "prefer
   restarting Maya", which undersold it. It is filed **High**, the recovery is
   *killing the process and losing the session*, and it cost two sessions before
   anyone bisected it. The expensive work is already done: the trigger is 3/3
   reproducible — an isolate capture of a **boolean-produced** mesh, then
   `new_scene` — and it reproduces on an **agent-launched Maya on 9878**, so it
   can be attacked without risking the user's session. Wedging is the expected
   outcome of a successful repro, so it must never be run on 9877.

   Cheapest first experiment, from the ticket's own suggested steps: force
   isolate teardown on every panel before `cmds.file(new=True)` and see whether
   it clears a landmine that already reads clean by every check we have
   (`isolateSelect -q -state` false, cameras restored, temp cam deleted, no
   `*ViewSelected*` set). If that fails, bisect what "boolean-produced"
   contributes — deleted history with a prior `polyCBoolOp` vs identical
   topology built without one. That distinction decides whether it is fixable
   plugin-side at all.
3. **#645** the byte reader ignores `RotationOffset`/`PreRotation`/`Geometric*`
   — measured 17% height error on `evals/structures/clock_tower.fbx`. Latent,
   not historic: **every shipped delivery scanned clean**, golem included, so
   the 4.02173 m gate never lied. But #603 gave `transform`/`assemble` a
   `pivot`, and moving a pivot is what makes Maya emit those records — the next
   asset built with pivots gets a wrong `height_m` from `maya_export_fbx`.
   Then **#646** the whole-scene (`ea=True`) export branch has never run live.
4. **#640** naming/parameter papercuts, **#639** no image tool writes to disk,
   **#638** `boolean_op` drops pivot, parent and UVs, **#636** `deform`'s bend
   is inert. Real friction, but none of them is a *wrong answer*.
5. **Not this lane any more.** Per the 2026-08-16 split, this repo builds tools
   and a separate agent consumes them for Demigol. **#647** (nothing this server
   exports has ever been opened by a consumer — validate the unit claim on
   import) is filed High and belongs to the consumer-side agent; the claim is
   ours, the work is theirs. Same for the tracer frame sequence and the two
   motion questions (`GrabReach` 4 m vs a measured 2.5528 m arm; contact-pair
   cost at 29 chunks). Assets built here are test fixtures only — the line is
   destination, not complexity.

## Three honest negatives — keep them, they are load-bearing

- **The 4.64 m reveal is not in this geometry.** Straightening the legs from
  rest buys **0.083 m**, not the 0.64 the spec spends on it. `extend` crowns at
  4.137 m. The 5.063 m bbox figure is the fists overhead.
- **The joins fail under SSAO.** Gasket collars show almost no contact
  darkening; they read as balls threaded on a limb.
- **The body seam glow is invisible** at its measured emission against a lit
  body. Left at measured values deliberately.

Plus the one thing no gate here can cover: **nobody has imported the FBX into
Unity.** The bytes are proven; the importer's behaviour is not.

## Standing constraints

- Short, precise replies. Measured numbers over assurances.
- When a prior claim turns out wrong, say so plainly rather than moving on.
- A green result from a stale deployed copy means nothing — Maya loads from
  `Documents/maya/scripts`, not the repo.
