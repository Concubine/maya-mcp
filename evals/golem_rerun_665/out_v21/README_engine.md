# Golem colossus — engine assembly notes

Deliverables in this directory:

| File | What it is |
|---|---|
| `golem.ma` | Maya scene, rest pose, metre-native |
| `golem.fbx` | The asset. Metres, Y-up, faces +Z, rest height ≈ 4.0 m. Nothing to correct on import. |
| `golem_physics.json` | Per-chunk mass/COM, primitive colliders, joint pivots and limits |
| `golem_poses.json` | The five motion-state poses, rotation-only |
| `poses/*.png` | Reference stills of each pose (front / side / three-quarter) |
| `turntable.png`, `hero.png` | Presentation renders |

## Structure — how to read the file

One transform hierarchy, one rigid mesh chunk per body segment. **No skeleton,
no skinning** — this creature is assembled from rigid bodies, which is what a
physics-driven, breakable colossus wants.

```
golem                          (root, origin at ground between the feet)
└─ golem_pelvis                (node origin = creature root pivot, 0,1.72,0)
   ├─ pelvis_plates            ← RIGID CHUNK (the physics body)
   ├─ core_pelvis              ← render-only (see below)
   ├─ golem_torso              (origin = waist joint)
   │  ├─ torso_plates … core_torso
   │  ├─ golem_head            (origin = neck)   → head_plates, core_head,
   │  │                          head_visor_recess, visor_tracer_core/tail
   │  ├─ golem_upperarm_L      (origin = shoulder_L)
   │  │  └─ golem_forearm_L    (origin = elbow_L)
   │  │     └─ golem_fist_L    (origin = wrist_L)
   │  └─ golem_upperarm_R …
   ├─ golem_thigh_L            (origin = hip_L)
   │  └─ golem_shin_L          (origin = knee_L)
   │     └─ golem_foot_L       (origin = ankle_L)
   └─ golem_thigh_R …
```

Pattern-match rule: every articulation node is named `golem_<segment>[_L|_R]`
and its **transform translation is the joint's world position** (also listed
as `joint_pivot` in the JSON). Every physics chunk is named
`<segment>[_L|_R]_plates`. Everything named `core_*` or `visor_*`/
`head_visor_*` is render-only — parent it to its chunk's rigid body and give
it no collider.

## Breakability

Each `*_plates` chunk is one mesh made of **separate closed shells** (each
kiln plate is its own shell). Detach a whole chunk (arm rips off at the
shoulder: take `golem_upperarm_L` and its subtree) and it keeps rendering and
colliding with its authored collider. For finer destruction, split a chunk
mesh by shells — every shell is watertight and can carry a fitted box of its
own. The `core_*` mesh under a segment is the glowing earth interior the
break exposes: keep it with whichever fragment carries the segment node.

## Colliders

`golem_physics.json` carries one authored primitive (box, in the chunk's rest
frame) per chunk — use these. A tool-measured reference set exists in the
scene's history; the authored set is tighter on thighs/shins/forearms.

## Mass and the momentum story

Masses are solid volumes (density 1.0 — you own the constant). The design's
"limbs respond at visibly different speeds" is in the numbers, not a tuning
request:

- **Arms**: fist 0.213 + forearm 0.218 ≥ upper arm 0.365 → distally weighted,
  high swing inertia. They should lag and overshoot under the same solver.
- **Legs**: thigh 0.407 vs shin 0.088 (4.6:1) → proximally weighted, low
  swing inertia. They snap and hold.

If you find yourselves tuning per-limb damping to get that contrast, check
the masses imported correctly first.

## Joints

All hinges are X-axis in the rest frame (the creature is sagittally
articulated); twist ranges where non-zero are in the JSON. 0° = rest pose.
The knee's `-38` limit IS anatomically straight — the rest pose carries the
coil. Never let a solver push past it; there is no hyperextension pose.

## The visor light

`visor_tracer_core` (bright, warm-white emissive) and `visor_tracer_tail`
(dimmer, redder) sit inside the brow slot on `golem_head`. The scan effect is
yours: translate both along local X within ±0.24 m and the tail follows the
core. The body's crack-glow (`core_*` emission) is graded head→feet
(hot→dead) and must stay far dimmer than the tracer.

## Materials

FBX carries base colours only. The kiln-plate surface grain in the renders is
a procedural bump (Maya noise) that does not survive FBX — re-author in
engine: high roughness (~0.82) terracotta plates, near-black warm-emissive
cores per the tier colours in the scene (`golem_core_hot/warm/mid/faint_mat`).
UVs are primitive box projections, serviceable for tiling detail but not
hand-packed.
