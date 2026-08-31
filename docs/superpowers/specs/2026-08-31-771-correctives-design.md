# #771 — deltaMush + pose-space correctives

Two tools that improve how rigs the toolbox already builds hold up at posed
joints, completing the phase-5 blendshape story (#691): a corrective now fires
AT a joint angle instead of at a hand-set weight, and deltaMush relaxes the
skinning artifacts underneath it.

Design date 2026-08-31. Every load-bearing behavior below was MEASURED on this
machine's Maya 2027 (agent Maya, port 9878) via `evals/correctives_probe/`
before this spec was written — none of it is assumed.

## What the evidence says the gate must target

The roadmap conditioned this ticket's promotion on the #665 golem rebuild
showing joint artifacts. **That condition never fired: the rebuild contains
zero skinning** (`evals/golem_rerun_665/findings_report.md` line 49 — rigid
chunk hierarchy by design). The only measured skinning artifact on record is
**edge stretch at hips/shoulders on the phase-2 humanoid**: raw bind 5.31/5.47
worst unfiltered ratio, 2.03 after the weight-craft pass, residual per-pose
`max_edge_ratio` 1.208–2.026 in `evals/humanoid_live/baseline.json`. Elbow
collapse, volume loss, and candy-wrapper twist have zero recorded sightings
(no metric even exists for volume, and no recorded pose twists a joint).

Therefore the gate measures **edge-stretch reduction on the phase-2 humanoid
at its harsh recorded poses** (crouch: knee −104.7°, extend: shoulder 115°)
against the same per-edge machinery humanoid_live already uses — an artifact
that has actually been seen, exactly as the ticket demanded.

## Measured facts the design stands on (probe, 2026-08-31)

1. **poseInterpolator works end to end on this install.** The plugin is loaded
   by default; `cmds.poseInterpolator(joint, name=…)` creates transform+shape
   with `driver[0].driverMatrix ← joint.matrix`; the shipped MEL helper
   `poseInterpolatorAddPose(interp, name)` snapshots the driver's CURRENT
   rotation as a new pose and returns its index. With neutral/neutralSwing/
   neutralTwist recorded at rest and a pose at rotate (0,0,−90):
   `output[pose]` reads 0.0 at rest, 0.5 at 45°, 0.667 at 60°, 1.0 at 90° —
   a clean monotonic ramp (interpolation=0, poseRotationFalloff default 180).
2. **A connected weight follows the driver exactly** (0 / 0.5 / 1.0 through
   the real blendShape alias plug).
3. **`setAttr` on a driven weight raises** ("locked or connected"); worse,
   **`setKeyframe` on a driven weight silently no-ops** (returns 0, no curve,
   connection intact). Both need explicit refusals — a silent no-op inside
   author_clip is a #764-class lie.
4. **`cmds.deltaMush` lands at the end of the chain**: history is
   blendShape → skinCluster → deltaMush, which is the correct order (mush the
   skinned result; the front-of-chain corrective still models the neutral
   surface).
5. **deltaMush is identity at rest** (worst edge ratio exactly 1.0 with mush,
   rig at rest) and **creating it posed vs at rest is byte-identical**
   (max vertex diff 0.0) — it references the orig shape, so no posed-creation
   refusal is needed.
6. **deltaMush measurably relaxes**: cylinder elbow at −110°, worst edge ratio
   1.745 → 1.349 at default iterations 10 / step 0.5.
7. **FBX export silently drops deltaMush**: with-mush and without-mush exports
   of the same rig at bind are byte-identical (47,680 bytes, identical vertex
   floats). export_fbx must WARN — the #714 procedural-texture precedent
   (silent loss the pipeline may accept → warn, never refuse by default).
8. **FBXExportBakeComplexAnimation + Resample bakes a DRIVEN weight into real
   per-frame DeformPercent curves**: a poseInterpolator-driven weight exported
   with a keyed elbow produced a 24-key DeformPercent curve in the take, and
   reimport evaluates 0.0 / 0.432 / 1.0 / 0.5 / 0.0 across the 0→−90→0 arc —
   values track the driver, not a constant. **Correctives ship in clip exports
   automatically**; nothing needs baking in-scene ("export_fbx never bakes"
   stands).

### Amendments from the live gate (2026-08-31, runs 1–2)

The gate's first run against the humanoid caught two facts the cylinder
probe could not see — both are now part of the design:

9. **Maya's default (uniform) deltaMush smoothing SPIKES anisotropic
   meshes.** On the crouched humanoid, default `distanceWeight=0` blew a
   2.16 mm hip-ring edge to **8.9x its bind length** (17 mm — visible by
   the #668 tear currency; iterations 20 → 15.5x/31 mm). The cause is the
   #669 anisotropy: 2 mm circumference rings beside 70 mm length edges, so
   uniform Laplacian smoothing drags tiny-edge vertices toward huge
   neighbours. **`distanceWeight=1.0` removes the spike entirely and beats
   the pre-mush stretch on both currencies** (unfiltered 1.943 → 1.540,
   visible 1.234 → 1.216) — so `distance_weight` is a param and its
   default is 1.0, not Maya's 0.0 (`evals/correctives_probe/
   probe_mush_spike.py`).
10. **Creating a NEW frontOfChain blendShape under a deltaMush hangs
   Maya's deformer reorder 20+ minutes** (8k-vert mesh; measured by
   bisection, `evals/correctives_probe/probe_bs_hang.py`). Every
   neighbouring operation is instant — adding a target to an EXISTING
   node under the same mush measured 0.0 s, and applying a mush over an
   existing blendShape is instant. So `create_blendshape` refuses the
   node-creation path when a deltaMush is in history (author shapes
   first, mush last — real rigging order), and the gate re-applies the
   mush after the corrective section.

## Tool 1: `maya_apply_delta_mush` (wire: `apply_delta_mush`)

Params: `mesh` (required); `smoothing_iterations` int 1–50 (default 10, Maya's
default; 50 mirrors rigmath.MAX_SMOOTH_ITERATIONS); `smoothing_step` float
0.01–1.0 (default 0.5); `pin_border_vertices` bool (default true);
`distance_weight` float 0–1 (default 1.0 — amendment 9).
Synonyms: iterations→smoothing_iterations, step→smoothing_step,
pin_border→pin_border_vertices, object/name→mesh.

Refusals (all before mutation): unknown keys (#764); mesh missing/not a mesh;
**no skinCluster in history** (the tool's claim is relaxing SKINNING — hint:
bind_skin first); **a deltaMush already in history** (stacking makes the
result unexplainable — the bind_skin re-bind precedent; hint: delete_objects
the existing node first).

Behavior: auto_checkpoint → `cmds.deltaMush(mesh, smoothingIterations=…,
smoothingStep=…, pinBorderVertices=…)` → postcondition: exactly one deltaMush
in history, downstream of the skinCluster (raise + rollback otherwise).

Measured report (never echoes inputs): `worst_edge_ratio_before` /
`worst_edge_ratio_after` at the CURRENT pose — current world edge lengths
against the orig (intermediate) shape's edge lengths, so no pose mutation is
needed to know bind lengths — plus `max_displacement` (re-read vertex
positions through the real chain), `delta_mush` (node name), warnings. When
the rig is at rest both ratios read ~1.0 and the report warns that the
measurement was taken at rest (pose the rig to see the relaxation).

## Tool 2: `maya_add_corrective` (wire: `add_corrective`)

Makes an EXISTING phase-5 blendshape target fire at a joint angle: the
complete workflow is create_blendshape (author the shape) → add_corrective
(make it fire).

Params: `mesh` (required); `target` (required — an existing weight alias on
the mesh's blendShape node); `joint` (required — the driver); `rotation`
(required — [rx, ry, rz] LOCAL degrees, the trigger pose, the exact currency
pose_skeleton speaks). Synonyms: angle/pose→rotation, bone→joint,
shape/weight→target.

Refusals (all before mutation): unknown keys; mesh has no blendShape / target
not an alias (reuse blendshape.py's resolution); joint missing or not a
joint; **rotation all zeros within 0.001°** (that is the neutral pose —
ill-defined); **target weight already has ANY incoming connection**
(animCurve → "a clip owns this weight, delete_clip first"; poseInterpolator
output → "already a corrective, driven by <interp>"; other → named
connection); **a pose at (near-)the same rotation already on the joint's
interpolator** (within 1.0° per axis — duplicate poses make interpolation
ill-conditioned); **anim curves driving the joint's rotate**
(clip.guard_static_pose — the handler must temporarily pose the joint).

Behavior (auto_checkpoint; joint.rotate snapshot restored in finally; created
nodes rolled back on failure):
1. Find the joint's poseInterpolator (a scene poseInterpolator shape whose
   `driver[0].driverMatrix` source is this joint) or create one: zero
   joint.rotate, `cmds.poseInterpolator(joint, name=<jointShort>_poseInterp)`,
   add neutral + neutralSwing + neutralTwist poses at rest (the shipped
   `poseInterpolatorAddPose` MEL helper). One interpolator per driver joint;
   a second corrective on the same joint adds a pose to the existing node.
2. Set joint.rotate to `rotation`; `poseInterpolatorAddPose(interp, <target>)`
   (pose named after the alias; suffixed unique within the interp if taken).
3. Snapshot mesh vertices (skin only, at the trigger pose), then
   `connectAttr(interp.output[idx] → blendShapeNode.<alias>)`, re-read
   vertices: `corrective_displacement` = the corrective's own contribution
   through the real deformer chain at the trigger pose.
4. Verify through the real graph (the #764/#775 inert-wire catch, in-handler):
   `weight_at_pose` re-read from the alias plug must exceed 0.5 (measured 1.0)
   or the handler RAISES and rolls back — a wired-but-inert corrective must
   not return ok. Restore rest, read `weight_at_rest` (~0.0; > 0.01 warns).
5. Restore the joint.rotate snapshot.

Returns: mesh, blend_shape, target, joint, interpolator, pose_name,
pose_index, weight_at_pose, weight_at_rest, corrective_displacement, warnings
(corrective_displacement ~0 warns — the target was near-identical to base).

Removal story (v1): delete_objects on the returned interpolator transform
removes every corrective on that joint; the freed weight plugs return to
hand-settable. Documented in protocol.md; a per-pose remove tool is deferred
until an art run asks for it.

## Guard closures (same arc — the holes this feature would otherwise open)

- **set_blendshape_weights** currently dies with a raw Maya error on a driven
  weight (measured). New refusal: any requested alias with a non-animCurve
  incoming connection → "driven by <node>; delete the interpolator to
  hand-set it" (animCurve case keeps the existing clip-owns-it message).
- **author_clip** currently SILENTLY drops keys on driven weights (measured:
  setKeyframe returns 0, no curve). New refusal when any requested
  blend_weights channel has a non-animCurve incoming connection.
- **export_fbx** warns when a live deltaMush sits in an exported mesh's
  history: "deltaMush does not travel in FBX (measured byte-identical
  exports); the relaxation exists only in Maya". Scene-side walk beside
  _scene_shape_aliases. Driven corrective weights need NO export change:
  they bake into per-take DeformPercent curves (measured fact 8), extra
  channels are tolerated by the gate's standing rule, and the live gate
  pins the bake once.

## Live gate: `evals/correctives_live.py` (output: `evals/correctives_live/`)

Fixture: the phase-2 humanoid, rebuilt with the same build/craft/pose
machinery as humanoid_live.py (copied per house style). Runs only against a
disposable Maya (refuses port 9877; surfdetail-era preflight: ping, identity,
restart_required refusal).

1. **Baseline reproduction**: pre-mush per-pose worst edge ratios cross-check
   against `evals/humanoid_live/baseline.json` (crouch 1.943, extend 2.026) —
   the before side of the ticket's before/after pair.
2. **deltaMush reduction**: apply_delta_mush, re-pose, measure. Thresholds are
   pinned from the first measured run with stated margin (house rule — no
   round inventions in advance). The probe's cylinder showed −23% worst ratio.
3. **Judged renders** at extend + crouch, before/after, 1024px (surfdetail's
   render discipline — 640px was barely judgeable).
4. **Corrective fires at the angle**: sculpted shoulder target,
   add_corrective at extend's 115° shoulder pose; weight_at_pose ≈ 1,
   weight_at_rest ≈ 0, half-angle weight in (0.2, 0.8), displacement > 0.
5. **Refusals over the wire**: driven-weight set_blendshape_weights,
   driven-channel author_clip, duplicate pose, zero rotation.
6. **Export honesty**: mush warning present; A/B export byte-identical
   vertices (re-proven on the humanoid once).
7. **Clip bake**: author_clip bends the shoulder through the trigger; export
   include_animation; anim_facts shows a per-frame DeformPercent curve for
   the corrective alias in the NAMED take (multi-take: two clips, curve in
   both); reimport evaluates mid-arc weight in (0,1) tracking the angle.

## Out of scope (deliberate)

Per-vertex deltaMush weight painting; displacement/inward/outward/
distanceWeight knobs; pose falloff/kernel knobs (defaults measured good);
in-between (progressive) poses; mirrorShape; a remove_corrective tool;
driven-channel declarations in the export animation gate (#767 can revisit);
anything simulated (#675 boundary stands).

## Files

The standard #775 registration anatomy: `maya_plugin/handlers/correctives.py`
(new, both handlers), registration in `maya_mcp_plugin.py`, models in
`src/maya_mcp/schemas.py`, tools in `src/maya_mcp/server.py`, guard edits in
`blendshape.py` / `clip.py` / `export.py`, tests in `tests/test_correctives.py`
+ `tests/test_server_tools.py` (registration set-equality!) +
`tests/test_handlers_mayapy.py`, wire docs in `docs/protocol.md`, gate
`evals/correctives_live.py`.
