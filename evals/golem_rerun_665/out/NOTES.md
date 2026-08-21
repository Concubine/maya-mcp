# NOTES — golem colossus build

## What I built, how I chose to realize it, and why

One articulated golem colossus, ≈4.07 m at rest, delivered as a **rigid chunk
hierarchy** — 13 articulated segments (pelvis, torso, head, and per side
upper arm / forearm / fist, thigh / shin / foot), each segment one combined
mesh of kiln-fired plates over a separate glowing earth-core mesh. No
skeleton, no skinning.

That was the central judgment call. The consumer drives the body with
physics on primitive colliders and needs pieces to rip off. A smooth-skinned
mesh fights all three of those; rigid bodies with joint pivots ARE the
engine's native vocabulary. So the Maya transform hierarchy is the physics
assembly: every articulation node's translation is exactly its joint's world
position, every chunk is a watertight named mesh, and `golem_physics.json`
carries mass/COM/collider/limit data measured from the scene by
`maya_author_physics` (with hand-authored tighter colliders where the
auto-fit was loose).

Design decisions worth defending:

- **Ball-joint spheres** at shoulder, hip, elbow, wrist, ankle, waist, neck,
  belonging to the child chunk and centred exactly on the joint pivot. A
  sphere centred on the rotation axis is rotation-invariant — the socket
  stays visually filled at ANY angle. That is the whole answer to the
  design's "no hollow gaps, no hidden geometry pushing through" requirement,
  and it doubles as the visible articulation the "legible joints" clause
  asks for.
- **The visor is composed, not carved**: brow slab above, jaw below, pillars
  at the ends, a near-black recess plate behind, and the tracer (bright
  core + dimmer tail) floating inside as separate meshes. Composition
  guaranteed the recess reads and keeps the tracer a separate object the
  engine can slide along the slot.
- **The crouch is geometry, not pose**: rest pose has all rotations at zero;
  the 38° knee coil, short-shin-over-long-thigh, high ankle, and silverback
  arm hang are authored into the meshes. The knee's `-38°` limit is
  anatomically straight, so "0° is the range's own edge" fell out for free.
- **Mass distribution is authored**: measured fist+forearm (0.43) outweighs
  the upper arm (0.37); thigh outweighs shin 4.6:1. The engine gets lag-and-
  overshoot arms and snap-and-hold legs from the same solver settings.
- **Glow tiers**: four core materials (hot head, warm torso, mid
  pelvis/upper limbs, faint lower limbs; feet/fists have no core at all) so
  the life-light dies toward the extremities, and the first render taught me
  to keep all of it far below the visor.

## What fought me

- **World-vs-local rotation semantics.** `maya_transform(relative=false)`
  sets WORLD-space orientation, not local. My first crouch pass silently
  produced a knee bent 110° local. Caught it because the tool reports
  achieved positions and the knee's world position matched world-space math
  exactly. Re-authored every pose as world orientations applied
  parent-before-child; the pose JSON carries both world and derived local
  values.
- **The hero render.** `maya_render_scene` has no camera parameter and its
  `current` angle does not use the active viewport camera (verified: the
  returned camera position was the canned three-quarter). I escaped to
  Python for a worm's-eye camera and spent four renders fighting light aim
  and exposure by hand — the tool's relight/exposure calibration turned out
  to be worth more than camera freedom. Final hero went back through
  `render_scene` (front, level camera, zoom 1.45) after rebuilding the
  calibrated rig and re-tinting colours only.
- **The FBX unit gate** refused my first export: ten core meshes still
  carried live node scale (mirror-baking had cleaned only the R side).
  Right refusal, clean fix (`mesh_cleanup` freeze), second export passed
  and was verified from the file's own bytes.
- **Mirror + absolute scale.** `maya_array(mirror)` bakes transforms, so a
  later absolute-scale on a mirrored copy double-scales. Cost one shrunken
  upper arm and a numeric compensation early on.

## What I wanted and could not get

- **A camera parameter on `maya_render_scene`** (or a `current` angle that
  honours `maya_set_camera`). The one deliberate low-angle hero shot the
  brief invited is not expressible through the render tool; my Python
  fallback lost the rig calibration and lost the trade.
- **Per-light colour on `maya_setup_lighting`.** DESIGN.md names the exact
  look — warm key, cool rim — and the preset can't say it. Tinting via
  `execute_python` was a two-line escape, but it is the one part of the
  presentation the toolset could not express.
- **Animated tracer scan.** With no skeleton there is no
  `maya_author_clip` (it keys joints only), so the tracer scan and the five
  poses ship as data (`golem_poses.json`) rather than FBX takes. For a
  physics-assembled creature I think that is the honest form anyway — the
  engine was never going to play clips.
- **Emissive bloom in pose stills**: pose captures are viewport rasters, so
  the tracer reads as a bright bar without halo there; the Arnold hero and
  the first material renders show the true glow.

## Surprises

- `maya_author_physics` converts one-sided hinge ranges into swing cones
  with the neutral at the extreme — the knee rule is genuinely built in,
  and its warnings caught my sloppy auto-fit colliders with numbers
  (volume_ratio) rather than vibes.
- The transform tool's "modified outside maya-mcp" warnings, which I first
  read as noise, are actually a world-space state ledger — they are what
  let me diagnose the world-vs-local rotation semantics without a single
  extra measurement call.
- `maya_combine` collapsing per-face shading to one material per object is
  documented, but its consequence shaped the whole asset: two meshes per
  segment (plates + core) is the design that materialized the
  glow-through-cracks brief.
- The checkpoint that saved the weathering experiment restored the scene
  but KEPT unrelated edits made in the same batch before the sculpt ran —
  ordering favored me, but I stopped batching risky ops with cheap ones
  after that.

## Honest self-assessment

The silhouette, proportions, articulation legibility, mass story, and the
visor read all land, and every number in the handoff was either measured by
a tool or comes from authored dimensions. The weakest points: the kiln-plate
surface detail relies on a procedural bump that does not survive FBX (engine
re-authors it; base colours do survive), and the hero render is a solid
front-on portrait rather than the low-angle monument shot I wanted — the
toolset's render path could not express that camera, and I chose its
calibrated exposure over my uncalibrated worm's-eye.
