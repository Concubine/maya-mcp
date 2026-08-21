# The golem — design of record

A colossus of pressed earth and kiln-hardened plates, animated by a light that
is not its own. It must read **heavy at rest and agile the moment it moves** —
standing still it already looks about to move, and when it does, its limbs
respond to momentum at visibly different speeds.

## The consumer

A game engine team receives your delivery and builds the creature's motion
with **physics** — the engine drives the body, it does not play hand-animated
clips. What they have told us:

- Their physics uses **primitive colliders only** (boxes, spheres, capsules) —
  there is not one mesh collider in the project, and they will not add one.
- The creature is **breakable**: in play, pieces of the golem must be able to
  rip off. A detached piece keeps rendering and keeps colliding.
- Motion "feel" is tuned engine-side. Your delivery carries the *data* feel is
  built from: the body's structure, how mass is distributed, where things
  articulate and how far, and the key poses below.
- The delivery measures in **metres** in the engine, with nothing to correct
  on import. Rest height ≈ **4.0 m**.
- They assemble the creature from your file by reading its structure and
  names — so name things like someone else has to pattern-match them.

How you carry all of that in a Maya scene and an FBX is your call. Whatever
data the engine needs that the FBX itself cannot express, put beside it in a
file with a README — invent the format, keep it honest.

## Proportions

Head height = 1.0 u throughout. Total height in the resting crouch ~5.0 u
(≈ 4.0 m delivered; so 1 u ≈ 0.8 m).

| Landmark | Height |
|---|---|
| Total, in the resting crouch | ~5.0 u |
| Total, if it ever fully extends | ~5.8 u — height it does not show you |
| Shoulder line | ~4.0 u |
| Pelvis bottom | ~2.0 u |
| Ankle | ~0.35 u |

Segment lengths: thigh 1.1 u, shin 0.8 u, foot slab 0.35 u tall and broad;
upper arm 1.2 u, forearm 1.35 u, fist 0.65 u.

**Legs** are the in-between of silverback and digitigrade. The knee bends
forward, never straight — ~35–40° flex at rest, so standing still it already
looks about to move. The coil comes from proportion, not reverse-jointing:
the shin is deliberately *shorter* than the thigh and narrower, and the ankle
sits high over a broad cracked slab foot. Short-shin-over-long-thigh reads as
coiled; the high ankle reads as ready.

**Arms** are silverback: hanging fists finish at ~0.8 u, mid-shin. Long
enough to plant with a lean, not full knuckle-drag. The fist is the mass of
the arm — distally weighted.

**Torso**: squat pyramid. Shoulders 2.2× pelvis width; the head sits AT the
shoulder line, forward ~0.3 u, under a deep brow. No neck to speak of.

**Feet** carry the broken-earth image: cracked slabs that look torn out of
the ground.

## The head and the light

No face. The brow is deep and heavy, and set into it is a **visor**: a
recessed horizontal slot. Inside the slot runs a **tracer eye** — a scanning
light with a bright core and a short fading tail, the one light on the body
that unmistakably reads. The visor light is the creature's life: whatever
carries it should go wherever the brow goes.

The body's surface: cracked, kiln-fired plates over matte earth. Through the
cracks and joins, a **faint** warm glow — brightest near the head, dying out
toward the extremities; the feet read nearly dead. The story the materials
tell: the light lives in the visor; the body is only earth it leaks through.
Keep the body glow subtle — it must never compete with the visor.

## Why the limbs respond differently

The differing momentum response should be a **consequence of the build, not a
tuning pass**. Same physics, opposite behaviour:

- **Arms** — long, heavy, distally weighted, on loose joints. High inertia:
  they lag and overshoot.
- **Legs** — short, thick, proximally weighted, planted. Low inertia: they
  snap and hold.

If the proportions and mass distribution are right, the engine gets this for
free. If they have to fake it with tuning, the build failed at its one job.

## Articulation

Where the body articulates: shoulders, elbows, wrists, hips, knees, ankles,
waist, neck. The four big joints — shoulders and hips — carry the largest
ranges and must stay **visually legible** at any angle that matters: no
angle in normal motion may open a visible hollow gap or push hidden geometry
through the surface. The body must keep reading as pressed-together mass, not
as parts floating near each other. How you achieve that is a design problem
for you to solve in the build.

The knee never hyperextends — 0° is the range's own edge, not a special case.

## The five motion states

The engine drives one core behaviour: a massive standing jump. Five states,
each a pose your delivery must carry:

| pose | fires on | what it is |
|---|---|---|
| `rest` | idle | the resting crouch — exactly what the delivered file carries untouched |
| `crouch` | jump wind-up (~1.1 s) | torso pitched forward and down, deep knee bend, arms swept back behind the body |
| `extend` | release | legs driven straight (to the knee's 0° limit), arms thrown overhead |
| `air` | airborne | gathered, knees up |
| `absorb` | landing, depth scaled by speed | deepest compression, arms forward for balance |

The wind-up is the pose the whole jump is paid for by. The shoulder swing
between `crouch` (arms back) and `extend` (arms overhead) is the widest range
on the body — design the shoulder for it.

Poses are **rotation-only**: nothing translates, articulation does all of it.

## Presentation

Lighting with one logic: the visor is the light source that matters
narratively; a warm key and a cool rim to silhouette the shoulder line.
Check the build under ambient occlusion, not only in beauty renders — the
joins and plate boundaries must read under AO.

## Deliberately avoided

Faces, fingers, toes, organic micro-anatomy. The golem's hands are fused
slab fists; its feet are slabs. Detail lives in plates, cracks, and mass —
not anatomy.
