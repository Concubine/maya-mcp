# Golem benchmark design — "Riverbed colossus, kiln-fired"

Art direction for the maya-mcp acceptance benchmark (design doc §8.3, Appendix A).
Decided 2026-08-12: **direction A construction + direction C material story**
(stacked-boulder body wearing cracked plates with glowing seams).

## Concept

A golem of Jewish folklore: a heavy earthen humanoid assembled from river
boulders and slabs of pressed clay, kiln-hardened at the surface. The word
*emet* (אמת) embossed on its forehead glows — and the same animating light
leaks faintly through every crack and join in the body, dimming with distance
from the word. The fiction told by materials: the word is the life; the body
is only earth.

## Proportions (head height = 1.0 u; total height ≈ 4 heads)

- Total height ~4.2 u; shoulder line at ~3.2 u.
- Shoulders ~2.2× pelvis width; silhouette is a squat pyramid.
- Hunch: head center sits AT the shoulder line, forward ~0.3 u; deep brow.
- Forearms ≈ torso height; fists ≈ 1.8× head volume; arms hang to the ground.
- Legs almost absent: pelvis boulder sinks into a broken-earth base disc —
  "feet rooted like broken earth" is literal.

## Construction grammar (M1 tools; separable boulders, each watertight)

**Rev 2026-08-12 (#574, user decision):** the body is NOT unioned. Every
chunk (boulder/slab/plate) stays its own closed watertight mesh, deeply
interpenetrating its neighbors so the silhouette reads pressed-together.
Chunks must be able to rip off — this is the export shape Demigol's golem
kit (M2) consumes; a fused hero mesh is presentation-only if made at all.
Verified build: 14 parts (pelvis, belly, chest girdle, 2 shoulders, head,
brow plate, 2×2 arm stones, 2 fists, ground disc).

Part list (all primitives; join work by interpenetration + per-part sculpt):
1. Pelvis boulder (sphere, flattened) sunk into a cracked ground disc.
2. Torso slab (rounded box), narrower than pelvis — mass reads bottom-heavy.
3. Two shoulder boulders (spheres) larger than the head, set high and forward.
4. Head: worn dome (sphere cut by brow plane), no face — brow shadow + rune.
5. Arms: 2–3 stacked stone segments each, ending in slab fists (beveled boxes).

Join treatment is where M1's sculpt tools get exercised honestly: after the
boolean union, `soft_move`/`inflate_region` passes slump the joins so boulders
read as pressed together like wet clay (not floating rocks), and
`crease_edges`/`bevel_edges` harden the plate boundaries where seams will glow.
Bend deformer for the hunch; lattice for global proportion pushes after visual
checks. `remesh_retopo` to ≤50k tris, `mesh_cleanup` last.

## Material story (M2 texture networks)

- Base: matte terracotta/umber clay (standardSurface, roughness ~0.85),
  strata banding by world-Y (ramp), subtle color variation per-boulder (noise).
- Cracks: fractal noise → threshold → bump AND emission mask. Crack density
  highest at joins and extremities.
- Seam glow: crack/seam emission color = warm ember (match rune), intensity
  driven by a ramp keyed to distance from the forehead — brightest at the
  rune, faint at the fists. One `create_texture_network` recipe: noise →
  remapValue → layeredTexture → (bump2d + emission).
- Rune (rev 2026-08-12, #574): a single **inverted + mirrored aleph (א)**
  — not the full word — ETCHED into the flattened brow plate as a carved
  recess (boolean; no applied letter geometry, no recess emission). The
  surrounding crack-glow falloff stays centered at the brow so the carving
  sits inside the brightest ember zone.

## Presentation

Three-point lighting (key warm, rim cool to silhouette the shoulder line),
8-frame turntable contact sheet. SSAO check pass before final — the boulder
joins must read under AO, not just in beauty.

## Rubric mapping

- Silhouette at thumbnail: squat pyramid + arms-to-ground is unmistakable.
- Surface under SSAO: boulder joins + crack relief carry it.
- Presentation coherence: single warm-ember light logic (rune → seams → key).

## Deliberately avoided

Faces, fingers, toes, organic micro-anatomy (documented pipeline ceiling,
§8.4). The Potter's giant (unified hand-pressed clay mass, sculpt-first) is
the post-M3 stretch direction once AI base meshes land; it under-tests less
but risks more today.

## Demigol note

The plate + glowing-seam language doubles as a design study for Demigol's
demolition golem (D:\devel\Demigol): swap ember glow for industrial warning
amber and the same material logic ports.
