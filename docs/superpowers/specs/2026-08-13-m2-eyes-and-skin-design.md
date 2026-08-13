# M2 — eyes & skin

**Status:** approved design, not yet planned
**Ticket:** redmine #581 (project 35, `maya-mcp`)
**Follows:** M1 "hands" (#577), merged as `0165fc0`
**Design doc reference:** `docs/design.md` §5.1, §5.4, §7

---

## 1. What this milestone is for

M1 gave Claude hands: it can build, cut, deform, and clean geometry, and every
result is verifiable by counting things — triangles, boundary edges, orphan
nodes. M2 gives Claude eyes and skin: the ability to make a model *look* like
something, and — more importantly — to see whether it did.

The distinction matters more than it sounds. M1's defects were caught by
numbers. M2 has no numbers. A material is either right or wrong to a human
looking at a picture, and every tool in this milestone is a pixel tool.

### Scope is conceptual, not golem-shaped

maya-mcp is a tool Claude uses to make art for **games in general**. The golem
is one consumer and a benchmark; it is not the target. Every API in this
milestone is designed around its own concept — what a material is, what a light
rig is, what a reference comparison is — and is not shaped to fit golem
look-dev. Where the golem informs a decision, it does so as one worked example
among the possible ones, never as the specification.

### Boundary: viewport judgement only

M2 stops at "it looks right in the Maya viewport."

**Explicitly out of scope**, deferred to a later milestone of its own: UV
layout, texture baking to file, texture export, and game-engine conventions.

This is a deliberate ordering, not an omission. Baking is only worth doing once
the look being baked is known to be good, and knowing that requires the
judgement loop this milestone builds. Building the export path first would mean
shipping a pipeline that faithfully bakes work nobody could evaluate.

---

## 2. Requirement discovered by a real run

On 2026-08-13 a one-pass M1 exercise over the golem surfaced a blocking gap:

> `capture_viewport` cannot render using the scene's own lights. Captures come
> back in default viewport lighting, so a lit model is judged unlit.

The golem scene carries a key/rim/fill rig. Captures of it came back flat grey
and blue, nothing like the ember-lit clay the original run produced. The rig
was there; the capture could not see it.

**This is a hard requirement on M2, not a nicety.** Whatever `setup_lighting`
builds must be visible in captures, or the entire judgement loop is blind and
every other tool here is decorative. Concretely, `capture_viewport` and
`capture_turntable` must be able to render with scene lighting
(`modelEditor -displayLights "all"` and shadow state), and the choice must be
explicit in the API rather than implicit in viewport state — captures have to
be reproducible across sessions.

The same run produced a second, softer observation. Correcting the golem's
faceplate meant guessing a Z offset, re-capturing, overshooting, and guessing
again — a blind loop over a purely visual question. That is precisely the loop
`compare_to_reference` exists to close.

---

## 3. Tools

Seven tools. Four perception, three authoring.

### 3.1 Eyes (perception, `readOnly`)

#### `get_object_info(name, include=[...])`

From §5.1, specified in M0 and never built. Sections: `transform`,
`mesh_stats`, `uvs`, `shading`, `history`. UV and history sections are
summaries — counts and node types — never raw data.

Its `shading` section is how a material assignment is *verified*, which makes it
a prerequisite for testing everything in §3.2 rather than an optional extra.

#### `capture_turntable(target, n_frames=8, resolution=384)`

One contact-sheet image, grid composited server-side in `images.py` (which
already exists and already composites). Eight views for the token cost of one
image. Used for final judgement passes.

#### `load_reference_image(source, ref_id)`

Path or base64. Stored **server-side in the MCP process**, deliberately not in
the Maya scene: reference images then survive `new_scene`, never dirty the
user's file, and cannot be destroyed by a scene operation.

#### `compare_to_reference(ref_id, angle="three_quarter", resolution=640)`

One side-by-side composite: reference on the left, current viewport on the
right. Cheap to build, and it converts "make it look better" into "close this
specific gap."

### 3.2 Skin (authoring)

#### `assign_material(mesh, shader, params)`

`standardSurface` (default), `lambert`, or `blinn`. Whitelisted params —
`baseColor`, `roughness`, `metalness`, `emission`, `emissionColor`, `specular` —
with unknown keys rejected and the valid list returned in the hint, matching the
`deform` whitelist idiom from M1.

**Object-level shading groups only.** One material per mesh. This is not a
simplification for its own sake: M1 established that per-face assignment
silently no-ops and corrupts shading groups on boolean output, which is why
`_do_boolean` collapses everything to a single object-level SG. Honouring that
here keeps one rule in the codebase instead of two contradictory ones.
Multi-material looks come from splitting geometry into separate meshes — which
is what game engines prefer anyway. Per-face assignment stays deferred until
someone solves the underlying Maya behaviour.

Reuses M1's `meshcheck.ensure_object_shading` rather than reimplementing SG
handling.

#### `apply_texture_recipe(mesh, recipe, params)`

**Named recipes, not a general node DAG.** The initial set:

| recipe | builds | typical use |
|---|---|---|
| `noise_bump` | noise → bump2d → shader normal | surface grain, roughened stone/clay |
| `ramp_gradient` | ramp → colour input | gradients, height tinting |
| `layered_mask` | layeredTexture blend of two inputs by a mask | wear, dirt, moss |
| `file_texture` | file node → named shader slot | authored image maps |

The design doc specifies an arbitrary `NodeSpec` graph with cycle checking and
attribute validation. That is deferred. It is the single largest item in the
milestone, it is hard to test meaningfully without real usage telling us which
nodes matter, and a small set of validated recipes covers most genuine need at a
fraction of the surface area. When real runs show the recipes are too rigid,
the general builder lands then — informed by which nodes were actually reached
for.

Each recipe records every node it creates, so a failure sweeps exactly its own
nodes and nothing else — the `etch_text` `finally` pattern from M1, which is the
established way this codebase guarantees zero orphans.

#### `setup_lighting(preset, intensity=1.0, hdri_path=None, replace_existing=True)`

Presets: `three_point`, `single_sun`, `hdri`.

`replace_existing=True` deletes the user's existing lights, which makes this a
destructive operation in exactly the M1 sense — and the only one in this
milestone. It takes an auto-checkpoint first, like `boolean_op`, `etch_text`,
and `remesh_retopo` — and, per M1's own correction, takes it *after* validation
so a refused call never burns one.

What counts as "the prior lights" must be defined precisely, because getting it
wrong deletes user work: only light *transforms and shapes*, never anything
else that happens to be selected or parented nearby. The mechanical gate in
§5.1 asserts this with a full node-count diff.

---

## 4. Safety model

M2 inherits M1's discipline unchanged; three points need stating because look-dev
interacts with it specifically.

**Destructive-op checkpointing, applied narrowly.** Only
`setup_lighting(replace_existing=True)` auto-checkpoints, because it *deletes*
nodes the user authored and may not be able to reconstruct.

`assign_material` and `apply_texture_recipe` deliberately do **not**. Both are
fully covered by the one-call-one-undo-step guarantee, and look-dev is an
iterative loop of many small material tweaks — checkpointing each one would
churn the checkpoint ring (`KEEP_CHECKPOINTS` prunes it) and push genuinely
valuable checkpoints out of it, which is the opposite of the safety the
mechanism exists to provide. Checkpoints are for what undo cannot reach.

**Zero orphans.** Materials, shading groups, texture nodes, and lights are all
scene nodes. Every authoring tool tracks what it created and sweeps exactly that
set on failure. The M1 audit standard applies: after any failed call, the node
counts must be unchanged.

**Reference images are not scene state.** They live in the MCP server process.
This keeps the user's scene clean and makes the reference outlive scene
replacement.

**Undo chunking.** One call, one undo step, unchanged. The four perception tools
are `readOnly` and take no undo chunk — matching the existing `no_undo_chunk`
handling rather than adding a new mechanism.

---

## 5. Verification

The exit test — *"Claude matches a provided reference silhouette within 3
correction rounds"* — is a visual judgement and cannot be fully asserted by a
test suite. Pretending otherwise would produce a green suite that means nothing.
So verification splits in two, and each half is honest about what it covers.

### 5.1 Mechanical gates (deterministic, regressible)

These assert the *plumbing*, which is the part that can be wrong in a way a
human would not notice:

- A material assigned by `assign_material` is readable back through
  `get_object_info(include=["shading"])`, with the params that were set.
- Unknown material params are rejected, and the hint lists the valid set.
- `setup_lighting(replace_existing=True)` removes **exactly** the prior lights
  and no other nodes — asserted by a full node-count diff, not by spot checks.
- `capture_viewport` with scene lighting enabled produces a measurably different
  image than with it disabled (this is the §2 requirement, and it needs a test
  that would fail if lighting silently stopped reaching captures).
- The turntable contact sheet has the expected cell count, grid dimensions, and
  frame order.
- The compare composite has the expected dimensions and panel split.
- Every texture recipe leaves zero orphan nodes — on success **and** on a forced
  mid-recipe failure.

### 5.2 The judged run (the milestone gate)

One live run against a reference image, with the correction rounds and every
capture kept as artifacts under `evals/`. This is the real exit test, it needs
human eyes, and it is recorded rather than asserted.

### 5.3 Method

The two-Maya policy from #577 applies throughout: a disposable agent-launched
Maya on `MAYA_MCP_PORT=9878` takes every call that has never run live before;
the user's Maya on 9877 is used only for pixel proofs. Given M2's tools are
*all* pixel tools, the live loop runs constantly, and the policy is what keeps
that from costing the user their session.

---

## 6. Sequencing

**Build the eyes before the skin.**

You cannot judge a material you cannot see. If `capture_turntable`,
`compare_to_reference`, and lighting-aware capture land first, then every
authoring tool is measurable from its first commit rather than at the end of the
milestone.

M1's lesson was that mechanical tests happily agreed with watertight-but-wrong
geometry for an entire branch. In M2 there is no watertight to fall back on — so
the judging loop is infrastructure, not a final gate, and it goes in first.

Rough order:

1. `get_object_info` — the readback everything else is tested against
2. Lighting-aware capture — the §2 blocking requirement
3. `capture_turntable`
4. `load_reference_image` + `compare_to_reference`
5. `setup_lighting`
6. `assign_material`
7. `apply_texture_recipe`
8. The judged run

---

## 7. Open questions for the plan

- Which shader attribute each texture recipe targets by default, per shader type
  (`standardSurface` vs `lambert` differ in slot names).
- Whether `hdri` preset requires a bundled default HDRI or errors without a
  path.
- Turntable frame count cap, and whether it shares `capture_viewport`'s
  4-images-per-call ceiling (it produces one composite, so probably not).
- Where `evals/` artifacts from the judged run live, and whether they are
  committed.
