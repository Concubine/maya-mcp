# Golem colossus — engine assembly notes (v3, with animation)

Everything from v2.1 still holds. What is new: the asset now arrives **breathing**.

| File | What it is |
|---|---|
| `golem.fbx` | **The asset.** Static. Metres, Y-up, faces +Z, rest height 4.06675 m. 62 nodes, 29 meshes. Nothing to correct on import. |
| `golem_idle.fbx` | Same asset carrying one take, `idle` (4.0 s, seamless) |
| `golem_visor_scan.fbx` | Same asset carrying one take, `visor_scan` (1.6 s, seamless) |
| `golem_v3.ma` | Maya scene, rest pose, no clip |
| `golem_physics.json` | Per-chunk mass/COM, primitive colliders, joint pivots and limits — all re-measured for v3 |
| `golem_takes.json` | Both takes as key data, plus how to rebuild them |
| `golem_poses.json` | The five motion-state pose targets, rotation-only |
| `previews/` | Frames and contact sheets for both takes, plus a crouch spot-check |
| `turntable.png`, `hero.png` | Presentation renders |

## Read this first: one FBX per take

**The FBX format here carries exactly one take per file.** That is not a style choice —
the exporter refuses more than one, verbatim:

```
2 skeletons carry a clip (probeA_root, probeB_root) - one file is one take
```

So `idle` and `visor_scan` ship as separate FBXs, each containing the full asset plus
its own take. This is a normal game-pipeline shape (one animation file per clip), but
it is worth stating plainly because DESIGN_V3 asked for "the FBX carries named animation
takes" and what you get is *files*, plural.

Two consequences for your importer:

1. **Both animation FBXs contain the same 62-node skeleton and the same 29 meshes** as
   `golem.fbx`. Import geometry once from `golem.fbx` and take animation only from the
   other two, or import all three and discard duplicate meshes — your pipeline's call.
2. **Every exported file contains TWO take entries**: the named one and a duplicate
   `Take 001` the exporter always writes. **Select takes by name**, never by index.

## Structure

One transform hierarchy. Rigid chunks, **no skinning anywhere** (`skinClusters: 0`) —
this creature is assembled from rigid bodies, and now those rigid bodies hang off joints.

```
golem
└─ jnt_pelvis                        (root joint, world 0,1.72,0)
   ├─ golem_pelvis                   → pelvis_plates, core_pelvis
   ├─ jnt_torso
   │  ├─ golem_torso                 → torso_plates, core_torso
   │  ├─ jnt_head
   │  │  ├─ golem_head               → head_plates, core_head, head_visor_recess
   │  │  └─ jnt_tracer               → visor_tracer_core        (render-only)
   │  │     └─ jnt_tracer_tail       → visor_tracer_tail        (render-only)
   │  ├─ jnt_upperarm_L → golem_upperarm_L → jnt_forearm_L → … → jnt_fist_L
   │  └─ jnt_upperarm_R → …
   ├─ jnt_thigh_L → golem_thigh_L → jnt_shin_L → … → jnt_foot_L
   └─ jnt_thigh_R → …
```

**What changed from v2.1:** every `golem_<segment>` group is now a *child* of its
`jnt_<segment>` joint, and its local translate is zero. The rule "a node's translate is
its joint's world position" is therefore replaced by:

> **the joint's world position is the joint pivot** (`joint_pivot` in the JSON, and
> `rig.joint_world_positions`).

Every mesh name and every `golem_*` name is unchanged, so name-based pattern matching
from v2.1 still works. Chunks are still `<segment>[_L|_R]_plates`; anything named
`core_*` or `visor_*` / `head_visor_*` is still render-only, gets no collider, and
should be parented to its chunk's rigid body.

### Why joints instead of skinning

A skinned mesh fights everything this creature is for: rigid kiln plates should not
bend, and pieces must rip off and keep colliding. So the joints are **rigid parents**,
not deformers. Rotating a joint moves a whole chunk. You can ignore the joints entirely
and treat the asset exactly as v2.1 (the chunk list in `golem_physics.json` is complete
and self-contained), or drive the joints to play the takes. Both views describe the
same file.

All joints have `jointOrient = (0,0,0)` and world-aligned frames, so **a joint's local
`rx` is the sagittal hinge** — the same convention the chunk data and the pose data use.
One convention across the whole handoff.

## The takes

| take | length | what it does |
|---|---|---|
| `idle` | 4.0 s | Resting breath. Torso settles, head counters, shoulders roll, fists drift. Head travels 4.0 cm, chest 1.8 cm, fists 7.1 cm. **Feet and pelvis travel exactly 0.00 cm** — the creature breathes, it does not hover. |
| `visor_scan` | 1.6 s | The tracer eye sweeping the slot, core leading, tail lagging on a lever so the gap breathes (0.228 m → 0.122 m). |

Both loop seamlessly. That is verified twice over: the authoring tool's own loop
validation accepted them, and independently the **rendered last frame is pixel-identical
to the first** (max channel difference 0 across the whole image) for both takes.

`idle` keys only `jnt_torso`, `jnt_head`, and the six arm joints — **no root motion, and
nothing translates a physics chunk's node**. Confirmed from the exported bytes: every
`Lcl Translation` curve count in `golem_idle.fbx` is 0. In `golem_visor_scan.fbx` the
only translation is on `jnt_tracer`, which is render-only.

Layer these under your physics as planned — they touch none of the channels the jump
cycle needs.

## Breakability, colliders, mass, joints

Unchanged from v2.1, and all re-measured for v3 (they agree to 3 decimals, which is how
we know the rigging did not disturb the model):

- Each `*_plates` chunk is one mesh of **separate closed shells**; 29/29 watertight.
  Split by shell for finer destruction.
- Use `collider_authored`. The tool's auto-fit is also reported as `collider_measured`
  for comparison, but it wastes volume on the limbs (ratio 2.9–3.3 on thigh/shin/forearm
  against ~1.7 for the authored boxes).
- **Arms distal**: fist 0.213 + forearm 0.184 = 0.397 vs upper arm 0.301 (1.32:1) → lag
  and overshoot. **Legs proximal**: thigh 0.353 vs shin 0.067 (5.26:1) → snap and hold.
  If you find yourself tuning per-limb damping for that contrast, check the masses
  imported first.
- All hinges are X in the rest frame. `0°` = rest pose. **The knee's `-38` IS
  anatomically straight** — the rest pose carries the coil. There is no hyperextension
  pose; never let a solver past it.

## Materials

FBX carries base colours only. The kiln-plate grain and the core ember grain are
procedural Maya noise and **do not survive FBX** — re-author in engine: high roughness
(~0.82) terracotta plates, near-black warm-emissive cores per the tier materials
(`golem_core_hot/warm/mid/faint_mat`), warm-white `golem_tracer_mat` (emission 1.0) and
the redder, dimmer `golem_tracer_tail_mat` (emission 0.45). UVs are primitive box
projections — fine for tiling detail, not hand-packed.

The core glow must stay far dimmer than the visor; every `core_*` mesh is ≥ 2 cm inside
its plates' bounds on every axis, so the light reads as cracks and never as panels.
