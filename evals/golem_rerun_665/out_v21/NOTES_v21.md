# v2.1 polish pass — 2026-08-21 (maya-mcp #712)

Polish on the #665 rebuild, addressing the user-circled defect: the glowing
core boxes read as broad smooth orange panels through every plate gap (inner
arms, chest notches, waist, belt) — and in a few places genuinely crossed the
plate silhouette. `out/` is the frozen #665 run of record; this directory is
the polished delivery.

## What changed, measured

1. **Core containment.** Cores inset on Y (silhouette protrusions: upper arms
   were 10.2 cm below their plates, shins 4.9 cm proud at the knee), then
   shrunk 10–20% on X/Z toward their own centroids so no broad core face sits
   near a gap. Verified: every core's bbox is now ≥ 2 cm inside its plates'
   bbox on every axis (worst: −0.02 m; core_torso −0.195 m).
2. **Trim lips** (the user's clad/crown idea): two beveled strips carrying the
   plate material — `trim_waist` under the mid-torso slab, `trim_belt` as a
   pelvis apron — **combined into `torso_plates` / `pelvis_plates`** (not
   free-floating; the #601 gasket lesson). Chunk count unchanged, shells
   9 / 5, both chunks still watertight.
3. **Core grain.** noise_bump added to all four core-tier materials, so
   glimpsed core reads as ember rock, not smooth plastic. NOTE: procedural —
   does not survive FBX (same as the plates' grain; engine re-authors).
4. **Masses re-measured** after the shrink (`maya_author_physics`):
   `golem_physics.json` here carries the new numbers. The mass story holds,
   stronger: fist+forearm 0.397 vs upper arm 0.300 (distal arms), thigh:shin
   5.3:1 (proximal legs).

## Deliverables

| file | state |
|---|---|
| golem_v21.ma | polished scene |
| golem.fbx | re-exported, byte-gated: 1 root (`golem`), 45 nodes, 29 meshes, 4.06675 m, metres declared. (First whole-scene export attempt swept in the leftover heroCam + light rig — 5 roots; re-exported as `nodes=["|golem"]`.) |
| golem_physics.json | masses updated; colliders/joints unchanged |
| golem_poses.json | unchanged from v2 |
| hero.png, turntable.png | re-rendered; no orange panels from any azimuth |

## Verification sweep (live scene, post-edit)

29 meshes, 29/29 watertight (zero boundary edges), zero live scales anywhere,
11,828 tris (+88 for the trims), height 4.06675 m from the FBX bytes.
