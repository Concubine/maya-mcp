# Vacuum drifter — a fully deformable fixture, measured in a real Unity

Ticket: [#743](http://localhost:3000/issues/743)
Date: 2026-08-23
Status: design approved, not yet planned

## 1. Why a new fixture

The golem has been this server's only substantial fixture, from #665 through v4
(#728). It is rigid chunks throughout: 33 meshes parented to one another, later
rigid-parented to joints (#713/#720). Everything a rigid hierarchy can teach us,
it has taught — including the expensive lesson of #737, where five delivered
poses turned out to describe an operation no consumer can perform.

That fixture is exhausted, and its exhaustion is structural rather than a matter
of effort. A rigid chunk asset cannot exercise skinning, cannot exercise blend
shapes as anything but decoration, and cannot exercise the import path a real
game character takes.

So this fixture is chosen to be the golem's structural opposite: **a fully soft
body, where nothing is rigid and deformation is the entire asset.**

### 1.1 What it is not

Not an art run. The 2026-08 split stands: this repo builds the MCP, and a
separate agent consumes it for Demigol. The drifter exists to put load on the
tool surface and to produce measurements. It is judged by what it finds, not by
how it looks.

## 2. The subject

A "vacuum drifter" — a medusa-like creature. A soft bell roughly 1.2 m across,
long tendrils trailing beneath it, about 4 m overall, authored metre-true.

The subject was chosen for its mechanics, not its aesthetics. A bell that
contracts is a pure skinning problem with a blend-shape refinement; tendrils are
long thin many-joint chains; nothing about it invites a hard surface.

## 3. The asset

### 3.1 Scale and units

Authored metre-native. `export_metres_per_unit == 1.0` is asserted at export,
never the `linear_unit` string (#634/#635). #647 confirmed against a real Unity
that our unit claim is exact — a 3 m cube arrives 3.000000 per axis with no
import correction — so the unit lane is settled and this fixture inherits it
rather than re-litigating it.

### 3.2 Rig — 105 joints

| Part | Count | Joints each | Total |
|---|---|---|---|
| Root (bell apex) | 1 | 1 | 1 |
| Radial ribs, 45° apart | 8 | 3 | 24 |
| Tendrils, from rib tips | 8 | 10 | 80 |
| | | | **105** |

Tendrils descend from rib **tips**, not from the root. That makes the hierarchy
genuinely deep, so a weight error at the bell margin propagates three metres
down a tendril and is trivially visible in a measurement.

Two properties of this rig are chosen for what they stress:

**Two joints sit on the mirror plane.** Mirroring X→−X pairs 45°↔135° and
225°↔315°, and maps 0°↔180° — but the ribs at 90° and 270° mirror *onto
themselves*. `mirror_weights` pairs positionally and refuses asymmetric
skeletons; it has only ever seen a humanoid, where nothing sits on the symmetry
plane except a spine that is excluded rather than self-paired. A joint that is
its own mirror pair is a case it has never met. Whatever it does is a finding.

**Eight tendrils meet the bell margin.** That crowds the margin with competing
influences, which is the precondition for the truncation question — but see
§4.1: density alone does not create the case, because `bind_skin` caps
influences by parameter. The two work together.

### 3.3 Vertex budget — stated, not discovered

**A ceiling of 15,000 vertices total: ~6k bell, ~1k per tendril.** The gate
asserts the ceiling and reports the actual count; exceeding it fails the gate
rather than being noted in passing.

#669 is what happens when divisions are uniform and unbudgeted: 25.6k of a
33.4k-vertex mesh landed on one head. Nothing in the current authoring path
budgets topology. Stating the number up front forces divisions to be allocated
deliberately, and it keeps the asset inside what a game would accept — which
matters, because the material scope (§6) exists to make the result genuinely
usable.

Tendrils are also #669's own territory: a tendril *is* a long thin limb, and the
divisions coupling that ticket describes applies directly.

## 4. Deformers

### 4.1 Skinning — and the truncation case must be created on purpose

Smooth bind, then `smooth_weights`. Weights are authored as a whole table with
`normalize=False` through the single `MFnSkinCluster` write path.

**Correction to an earlier draft.** I wrote that eight tendrils crowding the
bell margin would make five-or-more influences per vertex emerge on their own.
That is wrong: `bind_skin` takes `max_influences` (1–8, **default 4**, documented
as "4 is the game-engine convention"). Bound at the default, the asset can never
exceed Unity's limit and the truncation question cannot arise at all.

So the fixture **binds at `max_influences=8` deliberately**, to construct the
case rather than hope for it. Geometry crowding still matters — it is what makes
the extra influences meaningful rather than negligible — but the cap is what
allows them to exist.

This also gives the run a second, cheaper question worth recording: whether
`smooth_weights` respects the cap or can push a vertex past it. Nothing states
that it does.

`weight_report` gets a job it has not had before: reading the
**influences-per-vertex distribution before export**. Knowing that distribution
in Maya tells us whether Unity's four-influence truncation will occur *before* we
go looking for its effects in the consumer. If deformation then diverges in
Unity, we already know whether truncation is the cause rather than having to
work it out backwards.

A run that binds at 8 is deliberately *not* shipping best practice. That is the
point of a fixture: the spec's own §12 keeps the fix out of scope, and a second
bind at 4 is available as a control if the measured difference needs isolating.

### 4.2 Blend shapes — two targets, deliberately

| Target | Fires in | Purpose |
|---|---|---|
| `bell_crease` | `pulse_swim` | Rim folding inward at peak contraction — detail skinning cannot produce |
| `tendril_flare` | `tendril_reach` | Flare as the tendril closes |

Front-of-chain, the arrangement proven at a posed elbow in #691.

Two targets rather than one is the point. Each clip must pin the *other* clip's
weight channel to rest — the padding rule at
`maya_plugin/handlers/clip.py:537`, where a channel declared by one clip is held
at rest by the clips that do not declare it, and weights-all-zero *is* the reset
by rule rather than by capture.

Today that rule is only ever checked against itself. With two targets it becomes
consumer-visible: if padding fails, Unity plays `drift_idle` with a crease stuck
on, and the gate sees it. One extra modelled target converts an internal
invariant into a measurable external fact.

## 5. Motion — three takes

`author_clip` keys joint **rotation** only; translation is root-exclusive
(`maya_plugin/handlers/clip.py`, `ROTATE_ATTRS` / `TRANSLATE_ATTRS`). That suits
a drifter, which swims by moving its root while its body curls.

fps is declared explicitly in the gate and restated at export — fbxmaya caches
export fps at plug-in load, so it is never assumed.

| Take | Shape | Contents |
|---|---|---|
| `drift_idle` | loop | Subtle rib sway. Root stationary. Both blend channels pinned at rest. |
| `pulse_swim` | loop | Ribs contract and release; `bell_crease` fires at peak; **root translates forward**. |
| `tendril_reach` | one-shot | One tendril curls to an IK target via `pose_ik`, baked to FK; `tendril_flare` fires as it closes. |

### 5.1 What each take is for

`pulse_swim` carries the only translate channel the tool surface supports, and
in Unity it lands as **root motion** — an integration surface nobody has looked
at.

`tendril_reach` puts `pose_ik` somewhere it has never been. It was gated on a
three-joint humanoid limb where the fold direction falls out of
`preferredAngle`. A ten-joint tendril has no natural fold. If `pose_ik` cannot
hit a target on a chain like that, **this is a finding, not a failure to route
around** — the gate records it and the ticket carries it.

Because rotation is the only joint channel, IK targets must sit inside the
chain's reach: the tendril reaches by curling, not by stretching.

### 5.2 Loop continuity — authoring side is already covered

**Correction to an earlier draft of this spec.** I wrote that our gates are
blind to loop seams. They are not, on the authoring side: `author_clip` takes a
`loop` flag that validates the last key closes onto the first across rotations,
weights *and* root position, and refuses with the measured difference — "a cycle
that does not close pops on repeat in-engine"
(`src/maya_mcp/server.py`, `maya_author_clip`). #718 measured clip lengths and
did not exercise this, but the check exists.

So both looping takes are authored with `loop=True` and the authoring-side
assertion costs nothing.

**What remains genuinely unchecked is the seam as the consumer reconstructs
it.** Maya refusing a clip that does not close says nothing about what Unity
holds after import, resampling and its own tangent handling. The consumer gate
therefore samples the deformation metrics of §8 at the first and last frame of
each looping clip **in Unity** and requires them to agree within 1e-4 (rim
diameter and apex-to-tip, in metres). That tolerance is a named constant written
into `baseline.json`, so both gates judge the seam by the same number.

`tendril_reach` is authored with `loop=False` and is exempt from the seam check
in both places.

## 6. Material — scope deliberately narrow

Enough to answer "does anything arrive", not an art project. No transmission, no
subsurface.

- UV bell and tendrils into one atlas via `uv_atlas`.
- **Generate the base-colour image to disk from the gate itself**, so the fixture
  is deterministic and re-runnable and carries no art dependency.
- Apply it with `apply_texture_recipe`'s `file_texture`.

### 6.1 Why `file_texture` is the only door

Measured while writing this spec: `apply_texture_recipe` offers four recipes and
three of them — `noise_bump`, `ramp_gradient`, `layered_mask` — build
**procedural** nodes (`noise`, `ramp`, `layered`). Only `file_texture` creates a
`file` node carrying a path on disk
(`maya_plugin/handlers/texture_recipes.py:104`).

Procedural nodes are precisely what #714 reports the FBX dropping silently. So
there is exactly one viable route to a textured asset today, and it is not the
expressive one.

### 6.2 The #714 assertion

Also apply a procedural recipe to the shader's normal slot, and assert in the
byte gate what the FBX carries for it.

One extra call and one extra assertion. In exchange, #714 stops being a ticket
description and becomes a measurement: we would know from the bytes whether
procedural maps vanish and file textures survive.

## 7. Gates

Three artefacts, following the pattern #718 established in
`evals/multi_take_unity.py`.

### 7.1 `evals/drifter_live.py` — the live Maya gate

Builds the drifter end to end, measures it, and writes
`evals/drifter_live/baseline.json`:

- joint count and hierarchy
- influences-per-vertex distribution
- blend-shape aliases
- declared clip ranges and fps
- vertex counts against the budget
- texture paths
- the deformation samples of §8

### 7.2 The byte gate — same run

Export via `maya_export_fbx`, then parse the artefact:

- `export_metres_per_unit == 1.0`
- three takes present **by name** (an FBX also carries `Take 001`; look up by
  name, never by position — #695)
- a skin cluster record present
- **both blend-shape channels animated**, not merely declared
- the file texture referenced
- the #714 assertion on the procedural normal slot

The byte gate exists because the scene is blind to what the exporter writes —
#629's whole lesson.

**Contamination caution.** #718 measured a multi-take FBX carrying *three* curve
records per plug (`Take 001` plus one per take), and its first gate collapsed
them on an unstable uid, passing 6 times in 8 on identical exports.
Contamination is a *constant*, so variance and relative-displacement checks are
blind to it. Any per-take assertion here must key on stable identity and compare
against declared absolutes.

### 7.3 `evals/drifter_unity.py` — the consumer gate

Holds the C# to run and the policy to judge its output. It never talks to Unity
itself: a Python process cannot call an MCP tool, only the agent driving the
conversation can.

Everything it asserts is **derived from `baseline.json`**, never hand-restated,
so the byte gate and the consumer gate cannot silently disagree about what was
declared.

## 8. The decisive measurement

#737 turned on comparing a **frame-invariant** quantity — fist-to-fist centroid
distance — because it survives any rigid or mirrored transform and so admits no
coordinate-convention argument. Height, by contrast, was nearly blind: three of
four poses agreed to ~2 µm while the arms were metres out.

The drifter's frame-invariant equivalents:

1. **Bell rim diameter** — max pairwise distance among rim vertices.
2. **Apex-to-tendril-tip distance** — for a named tendril.

Sampled at first frame, last frame, and **five evenly spaced interior frames**,
on every clip — seven samples per metric per clip. The sample frames are written
into `baseline.json` so the consumer gate samples exactly the same times rather
than recomputing them.

In Unity: `AnimationClip.SampleAnimation` to pose the rig, then
`SkinnedMeshRenderer.BakeMesh` to read the **actually deformed** vertices —
skinning and blend shapes both applied, which is the entire point. An in-Maya
gate photographs a shape Maya computed; only the consumer can show the shape the
consumer will draw.

### 8.1 Everything else the consumer gate checks

- bone count matches the declared 105
- blend-shape names and count
- clip names and lengths against declared
- loop-seam continuity as reconstructed in the consumer
- `drift_idle` shows **no** crease it never declared (the padding rule, §4.2)
- what the material carries (§6)
- **Unity's own bones-per-vertex against Maya's distribution** — answering the
  truncation question directly rather than by inference

## 9. The general rule this establishes

#737's finding was not golem-specific: *any* rigid chunk-only posed delivery
this server produces has the same hole, because the defect is in the
pose-as-euler contract rather than in the asset. A consumer whose transform
model has no rotation pivot cannot execute "set each node's local euler to
these values", however accurate the values are.

This fixture settles that **by construction**. The drifter's poses only ever
exist as takes; there is no euler list to be unexecutable, because the exporter
bakes the pivot chain and the consumer plays a clip.

**The rule, stated generally:** *a posed delivery ships poses as animation
takes. It does not ship per-node euler lists.*

That is what #737 asked for, and stating it here makes it a rule rather than a
golem workaround.

## 10. Standing rules that apply

- **MCP is the primary path.** If the Unity editor is not open, or
  `claude mcp list` shows unityMCP unhealthy, report it in one line and **STOP**.
  No CLI batchmode fallback — a silent fallback hides the breakage and bakes in
  the slower path.
- **Scratch Unity project only.** Never point this at Demigol: its importer
  forces `importAnimation=false`, which is exactly why clip probes cannot run
  there. The #718 scratch project was deleted; the build recipe lives in
  `evals/multi_take_unity.py`'s docstring (~5 minutes).
- **Expect gate defects first.** #718's consumer gate found three defects, *all
  of them in the gate*, before it found anything in the product. Early failures
  here should be read as gate bugs until proven otherwise.
- **Verify which Maya answers.** A port is not an identity (#648); match the
  listener's pid. Check `ping`'s `loaded_digest` / `restart_required` before
  trusting any live result — a Maya launched before the last deploy holds stale
  modules.

## 11. Risks and open questions

| Risk | Handling |
|---|---|
| `pose_ik` cannot solve a ten-joint chain | Record the measurement and file it. This is the question, not an obstacle. |
| `mirror_weights` refuses or mishandles self-paired joints | Same — it is a designed-for finding. Fall back to authoring both halves directly if it blocks the build. |
| Blend-shape curves may not survive into Unity at all | This is the headline unknown. The byte gate localises it: if the channel is animated in the bytes and absent in Unity, the defect is the consumer's import, not ours. |
| More than 4 influences per vertex changes deformation in Unity | Measured on both sides before comparison (§4.1, §8.1), so it is diagnosed rather than inferred. |
| Vertex budget forces coarse tendrils that deform badly | The budget is a spec value; if it proves wrong, revise it explicitly in the ticket rather than drifting. |

## 12. Out of scope

- Translucency, subsurface, or any look development.
- LODs, colliders, prefab setup, Animator controller authoring.
- glTF/GLB export (#696 — only if a web consumer appears).
- Fixing #714, #669, #730, #731, #732. This fixture *measures*; fixes are their
  own tickets.
- Any change to the golem delivery. #737's resolution route is a separate
  decision; this spec only supplies the general rule.
