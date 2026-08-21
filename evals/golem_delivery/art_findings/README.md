# Golem surfacing — the evidence

Four frames, **identical camera, lighting and shading**; only the materials change. Produced
2026-08-16 from `../delivery/golem.fbx` imported into an empty Maya scene. Redmine **#656**
(surfacing) and **#644** (consumer) both cite these.

Camera: `golemCam` at (640, 300, 720) cm looking at (0, 195, 0), 50 mm. Lighting: three-point rig at
intensity 1.0. Viewport, textured, no wireframe.

| file | body | glow | what it shows |
|---|---|---|---|
| `1_delivered_brick_cyan` | city brick atlas | cyan `(0.45, 0.80, 1.00)` | **as delivered.** The visor pops — it is the only cool note on a warm body |
| `2_brick_amber` | city brick atlas | amber `(1.00, 0.62, 0.15)` | **the recorded direction, applied naively.** The visor *vanishes* into the brown |
| `3_stone_amber` | stone `(0.34, 0.33, 0.31)` | amber | **the recommendation.** The visor pops and the golem reads as a machine, not masonry |
| `4_stone_amber_boosted_12x` | stone | amber at 12× emission | **why "turn it up in Unity" fails.** Lamps, not seams |

## What each frame settles

**1 vs 2 — the glow colour cannot be chosen alone.** Amber is the recorded direction
(CLAUDE.md, from maya-mcp #574: *industrial warning amber*), and applied to the delivered body it is
strictly worse than the cyan that shipped. Amber sits in the same hue family as the brick, so the
visor loses all contrast. The direction is not wrong — it assumes the grey stone body the direction
*also* specifies, and the delivery substituted the city's brick atlas.

**2 vs 3 — the body is the actual variable.** Same amber, different body, opposite result. Whoever
decides this must decide body *and* glow as one pair.

**3 — the recommendation.** Stone body, amber glow. The golem separates from the city it is
destroying, the fiction reads (a demolition machine, not curtain-wall brick), and the decided glow
colour finally works. See #656 for the argument that a single hero character can afford its own
material even though 46,000 instanced city cells cannot.

**4 — the seam glow cannot be recovered engine-side.** #644 records the seam glow as "invisible at
its measured emission (0.013–0.315)", which reads as a value that wants turning up. It is not.
Measured: the five glow materials are assigned to **whole chunks** — brow, head, neck gasket, chest
girdle, both shoulders — with emission colour *and* weight as **flat scalars, no texture driving
either**. There is no crack mask, no seam mask, no falloff. At 12× the head becomes a uniform
luminous blob that swallows the visor detail and the shoulders become flat plates. With no mask to
localise the light, a bigger number has nothing to reveal.

The direction called for *crack mask × steep radial falloff from the brow rune, seam glow at chunk
join boundaries so damage reads for free.* That mechanism is absent from the asset, and it is the
single highest-value ask on #656 — it sits exactly where chunks detach, so it is the difference
between chunk loss having a visual language and having none.

## One frame that is deliberately not here

An AO pass. Strip the texture and the model is spheres, cylinders, boxes and a slab with almost no
contact darkening at the joins — gasket collars read as balls threaded on a limb, and every bit of
detail in the four frames above is albedo doing the work. It is ranked third on #656 because it is
survivable at play distance, and it will surface the moment #619 puts real lighting on the golem.

## Reproducing

Nothing here was saved into the delivery. The four states are pure material edits on a throwaway
import; `../delivery/` is untouched and remains the source of truth.
