# The golem — design of record, v3

Everything from the original DESIGN.md stands unless restated here. The
creature: a colossus of pressed earth and kiln-hardened plates, animated by a
light that is not its own — **heavy at rest, agile the moment it moves**.

## The consumer — what changed in v3

The engine team now **imports baked animation** alongside the physics
assembly. Their contract grows one clause and keeps all the old ones:

- **NEW: the FBX carries named animation takes.** They will play ambient
  animation (idle, the visor scan) as clips, layered UNDER the
  physics-driven motion — physics still owns the jump cycle and every
  reaction to force. Clips are the creature's autonomous life; physics is
  its response to the world.
- Still true: primitive colliders only; breakable in play (pieces rip off
  and keep rendering/colliding); metres, nothing to correct on import, rest
  height ≈ 4.0 m; structure and names pattern-matchable; whatever the FBX
  cannot express ships beside it in a documented file.

How you make the creature animable — what carries the motion, how the
animation data and the rigid-body assembly coexist in one file — is your
call, and it is the hard design problem of this iteration. Whatever you
choose must not break the old contract clauses.

## The animation set

| take | length | what it is |
|---|---|---|
| `idle` | 3–5 s, seamless loop | The resting crouch breathing: a slow mass shift — torso settles a few cm, shoulders roll fractionally, fists drift. Subtle: at thumbnail scale it should read as "alive", not "dancing". First and last frame identical. |
| `visor_scan` | 1–2 s, seamless loop | The tracer eye sweeping the visor slot (the ±0.24 m local-X run from the engine README), bright core leading, tail following. May loop offset from `idle` — the engine plays them independently. |
| optional third | your choice | If one more take would prove the pipeline (a wake-up shudder, a heavy exhale settling dust), add it. Only if the first two are solid. |

Rotation-only is NOT required for takes (that rule binds the five *pose*
targets, which remain deliverable unchanged) — but nothing in a take may
translate a physics chunk's own node except the tracer, which is render-only.
Root motion in takes: none; the engine owns locomotion.

## Rules learned in v2.1 — now design rules

- **The core light reads as cracks, never as panels.** Every `core_*` mesh
  stays ≥ 2 cm inside its segment's plates bounds on every axis (measured,
  not eyeballed). Where a join should glow deliberately, a trim/crown lip on
  the PLATE side frames a narrow crack; the trim belongs to the plates chunk
  itself (combined in), never a free-floating collar.
- Ball-joint spheres stay: sockets read filled at any articulation angle.
- The visor tracer stays a separate render-only mesh under the head — in v3
  it is also the star of `visor_scan`.

## Presentation

As before (visor is the narrative light; warm key, cool rim; check under
AO) — plus: judge every take from captured frames, and check the idle loop
seam explicitly (last frame vs first).
