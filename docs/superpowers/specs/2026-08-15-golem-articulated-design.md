# Golem, articulated — design revision for the #601 re-run

Revises `2026-08-12-golem-benchmark-design.md`. Decided 2026-08-15 with the user,
for ticket #601 ("does the current toolset build it through TOOLS?").

The 2026-08-12 design describes a rooted statue: *"Legs almost absent: pelvis
boulder sinks into a broken-earth base disc."* This revision gives the golem legs
and a physics-ready structure. Everything not restated here — the kiln-plate
material story, the emet rune, the boulder construction grammar — carries over
unchanged.

## What the golem is now

A creature that must read **heavy at rest and agile the moment it moves**, whose
limbs respond to momentum at visibly different speeds. It ships as separate rigid
chunks; a game engine builds the PhysX ragdoll from them. Maya never simulates.

## Where the ragdoll is assembled

**In the game engine.** Maya's deliverable is chunk meshes, a named hierarchy, and
correct pivots. PhysX bodies and joint limits are authored downstream.

This is a deliberate choice, not a limitation worked around silently. The toolset
has no rigging surface at all — no joints, no skinning, no rigid bodies, no
constraints — and for a rigid-chunk creature it needs none. The collider *is* the
chunk. What a solver requires is hierarchy, pivot-at-socket, and mass distribution,
and the first two are expressible through `parent`/`group` and #603. Mass falls out
of the volumes we model. Whether a real rigging surface would add anything beyond
this is parked in #602.

## Proportions

Head height = 1.0 u throughout.

| Landmark | Height |
|---|---|
| Total, in the resting crouch | ~5.0 u |
| Total, if it ever extends | ~5.8 u — the height it does not show you |
| Shoulder line | ~4.0 u |
| Pelvis bottom | ~2.0 u |
| Ankle | ~0.35 u |

Segment lengths: thigh 1.1 u, shin 0.8 u, foot slab 0.35 u tall and broad; upper
arm 1.2 u, forearm 1.35 u, fist 0.65 u.

**Legs** are the in-between of silverback and digitigrade. The knee bends forward,
never straight — ~35–40° flex at rest, so standing still it already looks about to
move. The coil comes from proportion, not from reverse-jointing: the shin is
deliberately *shorter* than the thigh and narrower, and the ankle sits high over a
broad cracked slab foot. Short-shin-over-long-thigh is what reads as coiled; the
high ankle is what reads as ready.

**Arms** stay silverback: hanging fists finish at ~0.8 u, mid-shin. Long enough to
plant with a lean, not full knuckle-drag.

**Torso** is unchanged from #574 — squat pyramid, shoulders 2.2× pelvis width, head
at the shoulder line and forward ~0.3 u, deep brow.

The #574 rule "forearm ≈ torso height" is dropped. It described a body that was
almost entirely torso; once legs exist the torso is 2.0 u and the proportion no
longer holds.

**The broken-earth language moves to the feet.** The base disc is gone, but cracked
slab feet that look torn out of the ground keep the original image alive rather
than discarding it.

## Joint treatment

Deep interpenetration and articulation want the same millimetres. Chunks that
overlap deeply read as pressed earth but have almost no rotation range before the
hidden geometry emerges and visibly intersects. The resolution is a hybrid:

- **Gasket collars everywhere.** Chunks barely touch; a small collar of packed
  rubble at each joint hides the gap. No booleans. Each collar is its own low-mass
  body.
- **Real ball-and-socket at the four big joints** — two shoulders, two hips. The
  proximal end of the upper arm and thigh is modelled as a ball; a concave cup is
  booleaned into the shoulder boulder and pelvis. Rotation stays legible at any
  angle where range matters most.

Four booleans, not ten, which keeps the #579 exposure small.

## Why the limbs respond differently

The differing momentum response is a **consequence of the proportions, not a tuning
pass.** Same solver, same settings, opposite behaviour:

- **Arms** — long, heavy, distally weighted (the fist is the mass), on loose joints.
  High inertia, low damping: they lag and overshoot.
- **Legs** — short, thick, proximally weighted, planted. Low inertia, high damping:
  they snap and hold.
- **Gaskets** — small, low mass, hung off the limb they collar. They settle *after*
  the limb has already stopped.

Three response timescales in one creature, none hand-authored.

## Chunk manifest — 29

| Group | Count | Chunks |
|---|---|---|
| Core | 5 | pelvis, belly, chest girdle, head, brow plate |
| Shoulders | 2 | shoulder ×2 |
| Arms | 6 | upper arm, forearm, fist — ×2 |
| Legs | 6 | thigh, shin, foot — ×2 |
| Gaskets | 10 | neck, waist, elbow ×2, wrist ×2, knee ×2, ankle ×2 |

Socket balls cost no extra chunks — the ball is the proximal end of the upper arm
or thigh. The four cups are boolean cuts into existing chunks.

Every chunk stays a closed watertight mesh that can rip off, per the #574 rev.

## The rig

**Hierarchy** is the ragdoll tree. Pelvis is root:

```
pelvis
├─ belly ─ chest girdle ─┬─ shoulder ─ upper arm ─ forearm ─ fist   (×2)
│                        └─ head ─ brow plate
└─ thigh ─ shin ─ foot                                              (×2)
```

Gaskets parent to the **proximal** member of their joint.

**Pivots.** Every chunk's pivot sits at its proximal joint centre — upper arm at the
shoulder ball, shin at the knee, foot at the ankle. Gaskets pivot at their own joint
centre. This is the whole rig and the part the engine reads. `center` is wrong for
every limb chunk: a centroid is the middle of the bone, not the joint.

**Names** carry side and part — `golem_L_upperarm`, `golem_C_pelvis`,
`golem_L_gasket_elbow` — so the engine builds bodies by pattern-match.

## Materials

Carried from #574 in kind: cracked kiln plates over matte terracotta, `uv_atlas`
across the chunks, `assign_pbr` with a real three-map atlas, and the inverted
mirrored aleph etched into the brow plate by boolean.

**Seam glow is baked per chunk, not driven by a world-space network.** A ramp keyed
to world distance from the brow would change an arm's glow the instant the arm
moves. One emission value per chunk, computed from its rest distance to the rune,
makes the falloff travel with the body. This is both correct for a ragdoll and
fully tool-expressible — 29 material calls, no shading network.

Legs help the story: they put real distance between the rune and the extremities,
so the falloff finally has range to show. The feet read nearly dead.

## Presentation

`setup_lighting` with the `environment` preset plus a warm key; a per-chunk contact
sheet through `render_sheet`; a hero turntable.

## Tooling

Audited against the handlers before designing, rather than discovered mid-build.

**Works already:** `assemble` (flat parts list with chunk labels, plus `taper`,
`patch`, `rotate` per part), `deform` (all six nonLinear types plus lattice),
`sculpt_ops` (`soft_move`, `inflate_region`, `displace_noise`, `smooth`,
`bevel_edges`, `crease_edges`, `bridge`), `boolean_op`, `etch_text`, `uv_atlas`,
`assign_pbr`, `parent`/`group`, `setup_lighting` preset `environment`.
`render_sheet` caps at 48 subjects, so 29 chunks is one call.

**Hole — per-object pivot placement (#603).** No tool path exists. `transform` has
no pivot parameter; `assemble`/`combine` take one global mode for the whole call;
`array`'s pivot is only the mirror plane. **Built first**, before the run.

**Hole — physics metadata (#602).** Nothing carries mass, centre of mass, collider
shape, or joint limits. Parked; arguably outside a modeling MCP's job.

**Partial — mirror is per-mesh.** `array` mode=mirror rejects anything but a single
polygon mesh. A limb is 6 chunks, so mirroring a limb pair is ~12 calls plus
grouping. Left unpatched, and measured by the run.

Everything except #603 stays unpatched so the run can still surprise us.

## Benchmark method

Build order:

1. Build and deploy #603; restart Maya; confirm the staleness handshake reads clean.
2. `checkpoint`.
3. `assemble` the centre and left-side chunks from one flat parts list.
4. Shaping passes — `deform` for the hunch and limb curvature, `sculpt_ops` for
   pressed-clay joins and hardened plate edges.
5. Four socket booleans, `checkpoint` before each.
6. `etch_text` the aleph into the brow.
7. Mirror left chunks to right; group.
8. Place 29 pivots.
9. Build the hierarchy with `parent`/`group`.
10. `uv_atlas`, then `assign_pbr` with per-chunk emission.
11. `setup_lighting`, then `render_sheet` and the turntable.
12. Measure and close the ledger.

**Instrumentation.** One ledger row per build step: step, tool used, call count,
whether it escaped to `execute_python`, and why. That ledger is the report's
evidence base. `execute_python` is permitted for measurement without penalty; every
use of it to *build* something is a finding.

## Hazards

- **#579 is open.** `maya_new_scene` wedges Maya after an isolate capture of a
  boolean-produced mesh. This golem has four booleans and will be isolate-captured.
  Checkpoint before each boolean; if Maya wedges, restart it rather than calling
  `new_scene`.
- **Two-Maya policy (#577).** The user's session is 9877; eval scripts default to
  9878 and need `MAYA_MCP_PORT=9877`.
- **The live gate is the gate.** A green result from a stale deployed copy means
  nothing. Report measured numbers.

## Deliverables

- Renders kept as artifacts under `evals/golem_run_2/`.
- A ranked price-vs-benefit list of every place the toolset fought this brief, in
  the format of `2026-08-15-tool-gaps-ranked.md`, sourced only from this run.
- Tool-surface utilisation: build steps through tools vs `execute_python`, with a
  reason for each escape.
