# The modelling vocabulary gap — why everything comes out of a box

Written 2026-08-26 from a direct observation by the user: *"things you make seem
to only revolve around cubes or basic trigonometric shapes."* That is accurate,
and this document measures why, then ranks what would change it.

It extends `2026-08-21-capability-roadmap-post-rigging.md` rather than replacing
it: that roadmap ranks capabilities for **rigging and look-dev**. This one is
about **form** — the shapes the toolbox can author at all.

## What the toolbox can say today, measured

Every command that makes or changes geometry, read off
`maya_plugin/maya_mcp_plugin.py` and the handlers:

| surface | vocabulary |
|---|---|
| `create_primitive` | 10 kinds: cube, sphere, cylinder, plane, torus, cone, octahedron, icosahedron, prism, pyramid |
| `assemble` | many primitives at once, with per-part `taper` |
| `array` | duplicate along a line/radial/grid, and mirror (object-level) |
| `boolean_op`, `combine`, `etch_text` | union/difference/intersection, merge, engraved text |
| `deform` | 8 whole-object deformers: bend, squash, twist, flare, sine, wave, sculpt, lattice |
| `sculpt_ops` | 8 ops: soft_move, inflate_region, displace_noise, smooth, extrude_faces, bevel_edges, crease_edges, bridge |
| `remesh_retopo`, `mesh_cleanup` | decimate/retopologise, weld and tidy |

**The whole vocabulary starts from a primitive and pushes it around.** There is
no way to *describe a silhouette* and have Maya build a surface through it.
Grepped and confirmed: no `curve`, `revolve`, `loft`, `extrude`-along-path,
`sweepMeshFromCurve`, `polySplitRing`, `polyMirrorFace`, `wire` or `softMod`
appears anywhere in the handlers.

That ceiling is exactly what the output shows. Assembled, faceted, rocky,
mechanical and architectural forms come out well — the golem runs prove it.
A head that is not a box does not, and no amount of pushing a sphere gets there.

## Why this bites an LLM harder than it bites a human

A human modeller closes the loop with their eyes hundreds of times a minute.
This toolbox authors **by coordinate, with no feedback until a render**. That
makes two things true at once:

* Brush-style sculpting is a poor fit — it is stroke-based, cumulative, and
  unmeasurable halfway through.
* **Curve-driven construction is an unusually good fit** — a curve is a short
  list of numbers, which is the one thing an LLM can author precisely and a
  gate can assert exactly. Maya then turns those numbers into a flowing surface
  deterministically.

The gap is not that the toolbox lacks sculpting. It is that it lacks the
*parametric* half of modelling, which is the half best suited to being driven
blind.

## What this Maya actually offers — probed, not remembered

Run against Maya 2027 via mayapy (`cmds` unless noted):

| command | present | what it buys |
|---|---|---|
| `curve` | **yes** | author a profile or path from CVs — pure numbers |
| `revolve` | **yes** | spin a profile around an axis: heads, vases, domes, limbs of varying radius |
| `loft` | **yes** | a surface through a series of cross-sections: torso, tail, horn |
| `extrude` | **yes** | sweep a profile along a path curve |
| `sweepMeshFromCurve` | **yes** | curve → **poly** directly, with taper/twist/scale ramps along the length |
| `nurbsToPoly` | **yes** | convert a NURBS result to quads with tessellation control |
| `planarSrf` | **yes** | cap a closed curve (`planar` is not the python name) |
| `polySplitRing` | **yes** | insert edge loops — the most-used shaping op in poly modelling |
| `polyExtrudeEdge` | **yes** | extrude edges (only *faces* are extrudable today) |
| `polyMirrorFace` | **yes** | topological mirror with seam merge — build half, get a whole |
| `polySplit` | **yes** | cut new topology into a mesh |
| `wire` | **yes** (node) | curve-driven silhouette deformer: draw the profile, mesh follows |
| `softMod` | **yes** (node) | falloff push/pull with a handle |
| `deltaMush` | **yes** (node) | relax skinning artifacts |
| `shrinkWrap`, `wrap` | **yes** (node) | project one mesh onto another |
| `transferAttributes` | **yes** | move UVs/weights between meshes |
| `polyAverageVertex`, `polyReduce`, `polyRetopo` | **yes** | relax, decimate, auto-retopo |
| `sculptTarget` | **yes** | sculpt a blendshape target |
| `birail1`, `curveWarp`, `polyChamferVertex` | **no** | not present in this install — do not plan around them |

## Ranked, for this project

### 1. Curve-driven construction — the one that changes what can be made

`curve` + `sweepMeshFromCurve` / `revolve` / `loft` / `extrude`, with
`nurbsToPoly` where the result is NURBS.

This is the direct answer to "a head that is not a cube": a head is a revolve of
one profile, or a loft through four or five cross-sections. A horn, a claw, a
tail, a pipe, a strap, a vine, a muscle belly are all one swept profile with a
taper ramp. The inputs are small lists of numbers; the output is a mesh whose
silhouette can be measured against the curve that produced it, so it is
gate-native in this repo's sense.

`sweepMeshFromCurve` deserves first place inside this group: it emits **poly**
directly (no NURBS conversion step), and its taper/twist/scale ramps are exactly
the parameters that make one curve produce a family of organic forms.

### 2. The subdivision-cage vocabulary — the one that changes quality of what is made

`polySplitRing` (edge loops), `polyExtrudeEdge`, `polyMirrorFace` (topological
mirror with merge), `polySplit`.

Real modelling is: build a coarse cage, control it with loops and creases, then
smooth. This repo already has the *last* two steps — `smooth` and
`crease_edges` — and none of the middle. Adding loops, edge extrusion and a
topological mirror turns the existing `extrude_faces`/`bevel`/`crease`/`smooth`
set into an actual workflow instead of four isolated verbs.

`polyMirrorFace` is worth calling out separately: characters are symmetric,
building half and mirroring halves the authoring cost *and* guarantees the
symmetry that hand-placed coordinates never quite achieve.

### 3. Curve and falloff deformers — cheap shaping on top of both

`wire` (a curve drives the silhouette) and `softMod` (a handle with falloff).
`wire` in particular is the deformer that most resembles how a sculptor thinks,
while staying entirely numeric.

### 4. Already on the other roadmap, still right

`deltaMush` + pose-space correctives, and baked AO/curvature/normal into the
atlas. Neither changes what can be *authored*; both change how what is authored
holds up. The baked-AO one fixes a measured, shipped weakness.

## What not to build

* **Artisan sculpt brushes** (`sculptMeshCacheTool`) — stroke-based and
  interactive. Bad fit for blind authoring, and unassertable mid-stroke.
* **Quad Draw / interactive retopo** — same reason.
* **`birail1`, `curveWarp`, `polyChamferVertex`** — measured absent here.
* Anything already parked in the other roadmap's Tier 2/3 (Bifrost, MASH,
  XGen, live simulation). Nothing in this document changes those verdicts.

## Suggested order

1. **Curve-driven construction** — biggest change in what is possible, and the
   best fit for authoring without eyes. Wants a brainstorm before a plan: the
   design space (which of sweep/revolve/loft to expose, how a curve is
   specified, what the gate measures) is wide enough that writing a ticket cold
   would guess at it.
2. **Subdivision-cage vocabulary** — mostly mechanical, each verb small, and it
   completes a set that is already half-built.
3. The two roadmap Tier-0 items, on their own merits.
