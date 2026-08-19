# Rigging surface — skeletons, skinning, and the road to animation (#602)

Decided 2026-08-19 with the user. Supersedes `docs/design.md` line 42, which
deferred rigging as a stretch goal: the user has unparked it. The evidence rule
("build when a run fights for it") is superseded by an explicit ambition:
**deforming creatures** — skinned crowds, organic bosses, soft variants — none
of which is currently authorable end-to-end, and a follow-through to
**high-quality motion and animation**.

Companion experiment: #665 rebuilds the golem from #601's own instructions once
this surface exists, to learn whether the chunk-only limitation was itself a
load-bearing framing helper for rigid-body authoring. This spec deliberately
does nothing to bias that run.

## Shape of the milestone

One umbrella design (this document), **six phases, each its own ticket, branch,
and live-gated deliverable**, ordered cheapest-first so every rung is
individually shippable and each builds on the one below. The M2 → M2.1–M2.4
pattern, applied on purpose: if priorities shift after phase 3, phases 1–3 are
merged, gated, and useful on their own.

| phase | capability | gate deliverable |
|---|---|---|
| 1 | joint skeletons, skin bind, pose application | the **serpent** |
| 2 | weights craft (mirror/smooth/region/report) | the **humanoid**, judged |
| 3 | IK posing, baked to FK | humanoid re-posed in a fraction of the calls |
| 4 | physics-body data into manifests | golem manifest regenerated through the tool; feeds #665 |
| 5 | blend shapes | the humanoid gets a face |
| 6 | animation clips + animated export | a walk/idle on the humanoid, curves verified in the bytes |

Two benchmark creatures, chosen with the user:

* **The serpent** (phase 1): a single joint chain through one mesh. The purest
  deformation test — one variable, cheap to judge (silhouette continuity),
  fails legibly (a rigid-chunk serpent reads as a bike chain).
* **The humanoid** (phase 2 acceptance, reused by every later phase): full
  skeleton, the classic hard weights at hips and shoulders, the direct path to
  the "skinned crowds" ambition. Phases 3, 5 and 6 all re-judge on it, so its
  quality bar compounds.

## Conventions inherited, not invented

Every phase obeys the rules the existing 41 tools already paid for:

* **Angles are degrees** (#636). Joint orients, pose rotations, joint limits —
  all of them, converted at the boundary exactly as `deform` does.
* **Geometry numbers follow the metre-authoring convention** (#629/#634/#635):
  cm scene, numbers mean metres at export, `export_metres_per_unit == 1.0` is
  the assertion. Joint positions are ordinary geometry numbers.
* **Results carry measured numbers.** A pose reports the joint world positions
  it *achieved* and the mesh's max vertex displacement — the #636 lesson: a
  shaping op that did nothing and said it succeeded is the worst defect class
  this project knows. A bind reports the unweighted-vertex count. An IK solve
  reports its residual.
* **Silence is never an answer** (#638/#640): dropped state, renamed nodes,
  unreachable targets all go to `warnings`.
* **Mutating commands auto-checkpoint**; measurement commands stay off the undo
  queue.
* **The byte-gate never reports a number it cannot verify** (#645): where
  skinning defeats the reader, the field is null with an `unavailable_reason`,
  never a plausible guess.
* **The live gate is the gate** (#601's rule) — but with a twist in this
  milestone's favour: **deformation is fully measurable in headless mayapy**
  (`skinCluster`, `joint`, `ikHandle` all work standalone), unlike anything the
  render tools ever gated. So the mayapy leg carries most of the correctness
  burden, and live gates are reserved for what genuinely needs them: export
  bytes and judged renders.

## Phase 1 — core: skeleton, bind, pose

The foundation everything above sits on. Four commands.

### `create_skeleton`

Assemble's shape, deliberately: a flat validated parts list, whole-call
validation before any node is created, one checkpoint.

```
create_skeleton(
  joints=[{name, position, parent?, orient?}],   # explicit form
  chain=[[x,y,z], ...],                          # OR the serpent shorthand:
  chain_prefix="spine",                          #   positions -> parented chain
  root_name?)
-> { root, joints: [{name, position, parent}], warnings }
```

* Validation up front: duplicate names, unknown parents, cycles — refused
  before the first `cmds.joint` runs (a skeleton that dies halfway is orphan
  cleanup nobody asked for).
* Joint orientation defaults to aiming at the first child (Maya's own
  convention) with `orient` as the explicit override; whatever is chosen is
  REPORTED per joint, because orientation is where every rig surprise lives.
* Returns canonical long names, same as every modeling tool.

### `bind_skin`

```
bind_skin(mesh, root, max_influences=4, method="closestDistance"|"heatMap"|"geodesicVoxel")
-> { mesh, root, influences, unweighted_vertices, max_influences_exceeded,
     per_joint: [{joint, vertices, mean_weight}], warnings }
```

* `unweighted_vertices` **must be 0** for a gate to pass — a vertex no joint
  owns stays behind when the creature moves, and nothing looks wrong at bind
  time. This is the bind-time equivalent of the blank-render check.
* `per_joint` stats exist so an agent can *see* a bind without a viewport: a
  joint owning zero vertices, or one joint owning everything, is a legible
  failure in numbers.
* Re-binding an already-bound mesh is refused with a hint (delete history or
  `unbind` first — decided in the plan), not silently stacked; stacked
  skinClusters are Maya's quietest way to make weights unexplainable.

### `pose_skeleton` / `reset_pose`

```
pose_skeleton(root, rotations={joint: [rx,ry,rz]}, space="local")
-> { applied, joints: [{name, world_position}], max_displacement,
     displaced_vertices, warnings }
reset_pose(root) -> { reset: true, max_displacement }   # back to bind pose
```

* The same pose currency as the golem handoff: per-joint local euler rotations,
  degrees. A phase-6 clip is keys of exactly this map, so nothing is redesigned
  later.
* `max_displacement` is measured from vertices before/after (the `deform`
  precedent), not from bounding boxes (#640's bbox lesson). A pose whose
  displacement is ~0 warns loudly.
* `reset_pose` exists because every measurement and every export must happen
  from a KNOWN pose; "whatever the last test left behind" is not a bind pose.

### Phase 1 gate — the serpent (`evals/serpent_live.py` + mayapy leg)

1. Build a serpent mesh (existing tools), a 12-joint chain through it, bind.
2. `unweighted_vertices == 0`; every joint owns vertices.
3. Bend 90° distributed along the chain: `max_displacement` within a computed
   arc-length window — not just "nonzero"; the tip must travel roughly the arc
   the chain geometry implies.
4. Silhouette continuity, measured: posed mesh remains one shell, no edge
   longer than N× its bind length (tearing detector), plus a judged render —
   the bike-chain read is a pixel judgement.
5. Export with skins; byte assertions below; re-import baseline recorded for
   the consumer ticket.

## Phase 2 — weights craft, and the humanoid

Binding is one call; *good* weights are the craft. Agents cannot paint, so the
craft tools are programmatic:

* `mirror_weights(mesh, axis="x")` — author one side, mirror (the `array`
  mirror precedent: bilateral creatures are the common case).
* `smooth_weights(mesh, joints?, iterations)` — the fix for stair-stepped
  falloff at hips/shoulders.
* `set_region_weights(mesh, joint, faces|within_radius_of, weight, falloff?)` —
  explicit assignment where the bind guessed wrong.
* `weight_report(mesh)` — per-joint ownership map, influence-count violations,
  weight-sum errors, unweighted vertices. The perception tool: an agent judges
  weights from this + a posed render, the way `get_object_info` serves
  modeling.

Gate: the **humanoid** — full skeleton (~20 joints), bound and posed through
the golem's five-pose set adapted to a biped (rest/crouch/extend/air/absorb
exercise exactly the joints that are hard: hips, shoulders, spine). Judged
renders per pose plus the measured checks; acceptance is the judged one.

Open sub-question, deliberately deferred to this phase's plan: whether
`create_skeleton` grows a `preset="biped"` (a parameterised skeleton from
height + proportions). Decide with the humanoid build in hand, not before —
the run will show whether hand-listing ~20 joints is a papercut or fine.

## Phase 3 — IK posing

One command, and a deliberately narrow contract:

```
pose_ik(root, joint, target, pole?=None, keep=True)
-> { achieved_position, residual, rotations: {joint: [rx,ry,rz]}, warnings }
```

Solve chain-to-target, **bake the result to plain FK joint rotations, delete
the handle**. No persistent IK state ever exists in the scene: the stored pose
stays the same rotation map phase 1 defined, so export, clips, and the pose
contract are untouched. `residual` is the measured miss distance — an
unreachable target is a number, not a silent stretch. IK here is an *authoring
convenience*, not a rig feature; that is what keeps it one command instead of a
solver surface.

## Phase 4 — physics-body data

The golem handoff contract's manifest block, generated by a tool instead of a
packaging script:

```
author_physics(roots|chunks, density=1.0, overrides?)
-> { bodies: [{chunk, mass, volume, com, collider: {kind, params},
               joint: {axis, swing_axis, swing1, swing2, twist_lo, twist_hi}}],
     warnings }
```

* Mass = **measured** closed-mesh volume × one density constant (the motion
  handoff's rule: author volumes, let the engine rescale; masses are abstract).
* COM from vertices, not bbox centre (#640's bbox lesson again).
* Collider fit: best primitive (box/sphere/capsule) by extent ratios —
  primitives only, the consumer's stated position ("not one MeshCollider in
  the project").
* Joint limits in the handoff's swing/twist cone shape, neutral-at-extreme
  supported (the knee rule).

Gate: regenerate the delivered golem's manifest through the tool and diff
against `evals/golem_delivery/` — equal or better, with every divergence
explained. This phase is what #665's rebuild then exercises under a fresh
build.

## Phase 5 — blend shapes

* `create_blendshape(mesh, targets=[{name, target_mesh}])` — targets are
  ordinary meshes authored with the EXISTING sculpt/modeling tools, so the
  authoring loop is already judged; this tool only wires deltas.
* `set_blendshape_weights(mesh, weights={name: 0..1})` — returns
  `max_displacement` like every deformation op.
* Export: morph targets ride along (`FBXExportShapes`); byte gate asserts Shape
  records per target name.

Gate: the humanoid gets an expression (or a muscle corrective — decided in the
phase plan); judged render at weight 0/0.5/1, measured monotonic displacement.

## Phase 6 — animation clips

The follow-through. The currency stays the phase-1 pose map, now keyed:

```
author_clip(root, name, fps=30, keys=[{time_s, rotations}, ...],
            interpolation="linear"|"smooth")
-> { name, duration_s, keyed_joints, keys, warnings }
preview_clip(root, name, resolution?, every_nth?)   # contact sheet of frames
export gains include_animation=True                  # bake + write curves
```

* `preview_clip` renders every-nth-frame through the EXISTING render path into
  the contact-sheet form — motion is judged the way everything here is judged,
  from a sheet of pixels, no viewport playblast dependency.
* Export bakes to per-frame keys (`FBXExportBakeComplexAnimation`), because
  baked curves are the only form every importer agrees on.
* Byte gate: AnimationCurve/AnimCurveNode records present, per-joint curve
  count, key count == baked frame count, duration matches the declaration.

Consumer honesty, restated: Demigol currently has **no animation system**
(`importAnimation=false`; poses settled with their agent). Phase 6 builds
engine-general capability with no consumer wired today — accepted knowingly by
the user as the follow-through target, and the consumer ticket below is how it
stops being theoretical.

## Export and the consumer, across all phases

`maya_export_fbx` grows per phase: `include_skins` (P1), shapes (P5),
`include_animation` (P6) — defaults chosen so existing callers are untouched.
The byte reader (`fbxbytes.py`) grows the matching assertions the same phase:

* P1: Deformer/SkinCluster/Cluster records present; per-vertex weight sums
  ≈ 1.0 read from the bytes; joints are Model records and pass the existing
  identity-scale gate; a BindPose record exists.
* P5: Shape records per declared target.
* P6: curve records, counts, duration.

The reader **verifies well-formedness, not importability** — that distinction
is this project's scar tissue (#629: every in-Maya gate was blind; #647:
nothing we export has ever been opened by a consumer). Therefore: **the day
phase 1 merges, a consumer-side ticket is filed** (the #647 shape: import the
serpent somewhere real, measure bind pose, bone count, deformation at a pose)
rather than after six phases of unconsumed exports. Skinned-bounds composition
is explicitly out: the reader reports bind-pose bounds and sets the posed
question to `unavailable_reason` (#645 rule).

## Out of scope, permanently-for-now

Cloth/nucleus simulation, muscle systems, auto-rigging, retargeting, animation
layers, and any in-Maya physics *simulation* — the engine owns feel; that
boundary was settled in the motion handoff and stays. Per-face anything (the
M1 shading-group scar). A general deformer-graph surface (named recipes won
that argument in M2; the same logic holds here).

## Ticketing

#602 carries this design and phase 1. Phases 2–6 are filed as their own
tickets when the preceding phase merges (their scope lines are this document's
sections, refined by what the preceding phase learned). #665 runs after phase
4 at the earliest — it needs physics-body data to compare manifests, and gains
the most if it also has phases 1–3 available to tempt the builder. The
consumer-side import ticket is filed at phase 1 merge.
