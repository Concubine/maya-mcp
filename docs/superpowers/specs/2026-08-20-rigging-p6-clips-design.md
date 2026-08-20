# Rigging phase 6 — animation clips (design)

Ticket: #695. Parent spec: `2026-08-19-rigging-surface-design.md`, Phase 6
section — this doc settles the decisions that spec deferred, agreed with the
user 2026-08-20. The currency stays the phase-1 pose map, now keyed; the
engine owns feel; no persistent solver state (the pose_ik precedent).

## Decisions settled with the user

1. **One clip at a time.** No in-scene clip library, no stacked timeline.
   `author_clip` keys the joints directly; authoring under a new name
   replaces the previous clip with a warning naming what was replaced.
   Export bakes the current clip as one take — one FBX per clip. Several
   clips = author→export, repeated.
2. **Clips key joints AND (optionally) blendshape weights.** A blink in an
   idle, a bulge synced to a step — the phase-5 payoff rides along.
3. **Optional root position.** Each key may carry `root_position=[x,y,z]`
   (metres, root joint only) — the vertical pelvis bob an honest walk needs,
   and authored root motion when wanted. Non-root joints stay rotation-only.
4. **Loop flag** (field-informed, 2026-08-20 search): cycles that don't
   close pop on repeat in-engine. `loop=True` validates first key == last
   key (rotations, weights, root position) within tolerance — refusal
   carrying the measured per-channel difference, not a silent pop.

## Tools

### `author_clip(root, name, fps=30, keys=[...], interpolation="linear"|"smooth", loop=False)`

Each key: `{time_s, rotations={joint: [rx,ry,rz]}, blend_weights?={alias: 0..1},
root_position?=[x,y,z]}`. Rotations degrees (#636 convention), times seconds.

* **Whole-call validation before any key is set** (the create_skeleton
  shape): ≥2 keys, strictly increasing `time_s`, known joints under `root`,
  known blendshape aliases. Aliases resolve across blendShape nodes on
  meshes skinned to this skeleton; an alias existing on two nodes is a
  refusal, not a guess. `loop=True` closure check happens here too.
* `interpolation`: `linear` → linear tangents; `smooth` → auto tangents.
* Replaces any existing clip (warning names the replaced clip; its keys are
  deleted first — never merged).
* Sets the scene time range to the clip range. Auto-checkpoints once.
* Returns MEASURED: `duration_s`, keyed joint/channel/curve counts, and
  per-key max vertex displacement sampled by evaluating the scene at each
  key time. A clip that doesn't move the mesh warns loudly with numbers.

### `preview_clip(root, name, resolution?, every_nth?)`

Renders every-nth frame through the EXISTING render path into one contact
sheet — motion judged from a sheet of pixels, no playblast dependency.
Refuses if no clip exists or `name` doesn't match the live clip (guards
against judging a stale assumption). Returns the sheet path plus the frame
times actually rendered.

### `delete_clip(root)`

Forced by an interaction the parent spec didn't face: once curves own the
joint channels, a static write (`pose_skeleton`, `pose_ik`,
`set_blendshape_weights`, `reset_pose`) sets values the curves silently
override on the next frame change. Rule: **while a clip exists, static pose
mutators refuse with a hint naming the clip**; `delete_clip` removes the
curves, returns the skeleton to bind pose, and zeroes every weight channel
the clip keyed (weights-all-0 is the reset, the P5 rule) — measured
`max_displacement` reported, like `reset_pose`. One owner at a time, no
silent fights.

## Export

`maya_export_fbx` gains `include_animation=False` (default).

* **True:** bake per-frame over the clip range
  (`FBXExportBakeComplexAnimation` — baked curves are the only form every
  importer agrees on); the take is named after the clip. Refuses if no clip
  exists.
* **False:** animation export is **pinned off even when curves exist**, so
  existing callers and static exports of animated scenes stay byte-identical
  to today — and the byte gate asserts zero curve records in that case (the
  symmetric assertion).

## Byte gate (`fbxbytes.py`)

AnimCurveNode/AnimationCurve records read, not tolerated:

* per-keyed-joint rotation curves; root translation curves when
  `root_position` was used; DeformPercent curves per keyed weight channel;
* baked key count == `round(duration_s * fps) + 1`;
* duration from KeyTime ticks matches the declaration;
* take name == clip name;
* `include_animation=False` → zero curve records.

FBX tick size and the actual record shapes are **measured first in mayapy**
before any literal enters the plan (the P5 `<node>.<alias>` lesson). Where
skinning or format defeats the reader, fields are null with an
`unavailable_reason`, never a plausible guess (#645).

## Gate (`evals/clip_live.py`, disposable Maya, pid-verified)

The #668 humanoid gets two clips, both `loop=True`:

1. **Idle** — subtle sway + a blink (exercises blend-weight keying).
2. **Walk** — full leg/arm stride cycle with pelvis bob via `root_position`.

Checks: judged contact sheets for both (implementer AND controller);
measured per-key displacement; loop closure measured; both clips exported
and byte-gated with skins + shapes still green; measured numbers recorded in
`baseline.json`. Plan literals derived from measurement, not guessed.

## Out of scope

Animation blending/layers, Trax, retargeting, cycle/infinity flags (looping
is a consumer import setting; our `loop` is a validation, not an FBX
feature), keyframe reduction/curve compression (engines re-compress on
import; reduction reintroduces the interpolation ambiguity per-frame baking
exists to kill), ML motion generation, and anything simulated (#675
boundary stands). glTF export is logged as a reference ticket, not built.
