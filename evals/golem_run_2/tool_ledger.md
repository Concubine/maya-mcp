# #601 build ledger — one row per build step

`escaped` = this step BUILT something through execute_python. Measurement calls are
not escapes and are not listed.

| # | Step | Tool | Calls | Escaped | Why |
|---|------|------|-------|---------|-----|
| 1 | 18 chunks + 18 pivots | assemble | 1 | no | |
| 2 | taper 4 limb segments | deform (flare) | 4 | no | |
| 3 | hunch the torso | deform (bend) | 2 | no | **produced nothing** — see finding below |
| 4 | hunch, second attempt | sculpt_ops (soft_move) | 2 | no | belly worked (0.089 lean); girdle did not — see finding |
| 5 | pitch the chest plate | transform (rotate) | 1 | no | the hard-surface instrument, after soft_move failed on an 8-vert cube |
| 6 | rubble the 6 gaskets | sculpt_ops (displace_noise) | 6 | no | |
| 7 | harden brow / fists / feet | sculpt_ops (bevel_edges) | 3 | no | |
| 8 | pressed clay on body chunks | sculpt_ops (displace_noise) | 3 | no | |
| 9 | shoulder socket, L | create_primitive + boolean_op | 2 | no | cutter must BREAK the surface or the result is a sealed void |
| 10 | hip sockets, L and R | create_primitive + boolean_op | 4 | no | the pelvis is a centre chunk, so both hips are cut here — the right one cannot come from Task 7's mirror |
| 11 | carve the aleph | etch_text | 1 | no | one call, glyph to recess |
| 12 | re-place 3 pivots after the booleans | transform (pivot) | 3 | no | **required** — see finding below |
| 13 | rename 2 boolean results | rename | 2 | no | **should not have been required** — see finding below |
| 14 | chamfer the chest girdle | sculpt_ops (bevel_edges) | 1 | no | the chunk Task 5's `soft_move` silently missed; caught by capturing, not by a number |
| 15 | drop the aleph, keep the visor | delete_objects + create_primitive + bevel_edges + transform | 4 | no | art direction; the rune is carved INTO the brow, so removing one meant rebuilding the other |
| 16 | mirror the 11 left chunks | array (mirror) | 11 | no | one call per mesh — mirror takes a single polygon mesh, so the shape of the tool sets the count |
| 17 | strip the `_1` the mirror appended | rename | 11 | no | **should not have been required** — see finding below |
| — | place the 11 right pivots | *(none needed)* | 0 | no | the plan budgeted 11 calls here; `array` had already mirrored them — see finding below |
| 18 | parent the 29 into one tree | parent | 28 | no | one child per call, confirmed from the signature before counting |
| 19 | swing the left arm and put it back | transform (rotate) | 2 | no | the rig test — the point of Tasks 1–3 and 8 together |
| 20 | cut the scan slot into the visor | create_primitive + boolean_op | 2 | no | the recess the tracer lives in |
| 21 | put the brow back together afterwards | rename + transform + parent | 3 | no | **should not have been required** — the boolean took three things, see finding |
| 22 | the tracer core and its trail | create_primitive | 4 | no | one core, three fading bars — a smear, not KITT's segments |
| 23 | light the tracer | assign_material | 4 | no | emission 14 / 5.5 / 2.0 / 0.7 down the trail |
| 24 | hang the eye on the head | parent | 4 | no | so it travels with the skull, not the world |
| 25 | atlas all 29 into patch 0 | uv_atlas | 1 | no | **2 calls attempted** — `patch: 0` was refused, see finding |
| 26 | the kit's three maps on all 29 | assign_pbr | 1 | no | claim 2 of #601 — one material, 29 meshes |
| 27 | seam glow on the 6 chunks nearest the eye | assign_pbr | 5 | no | `params` is the only way to keep the maps AND vary emission — see finding |
| 28 | light it | setup_lighting | 4 | no | environment → three_point → environment; three of the four were diagnosis, see finding |
| 29 | prove the dome was dead | create_primitive + assign_material | 2 | no | a 50% grey probe sphere; the call that turned a suspicion into a defect |
| 30 | hero renders | render_scene | 11 | no | **8 of the 11 were diagnosis**, not pictures — see finding |
| 31 | the per-chunk sheet | render_sheet | 2 | no | 29 cells in ONE call against the kit's 41; the second call was the Arnold retry that timed out |

## Notes

**Step 1 — the rig arrived in the build call.** All 18 chunks came back
`combined: false`, i.e. every one is single-part. That is precisely the case that
used to get *no* pivot treatment at all: `combine` never runs for a single-part
chunk, so Maya's default pivot stood. Without #603's `pivots` map this body would
have had 18 centroid pivots and no rig. Verified independently with
`execute_python`, not from the response — `golem_L_thigh` at the hip ball
[0.55, 2.15, 0], `golem_L_upperarm` at the shoulder [1.25, 3.95, 0.15].

**Task 5, row 3 — `deform` with `bend` is inert, and it reports success.** Both
calls returned `baked: true` with no warnings and moved nothing: measured
`lean_forward = 0.0` on the belly (382 verts) and the chest girdle (8 verts).

Diagnosed rather than worked around:

- The handle is placed correctly — translate [0, 3.0, 0.05] on a mesh spanning
  Y 2.525–3.475, scale 0.725, bounds ±1, envelope 1. Not a placement bug.
- Toggling `envelope` 0↔1 moves vertices by **0.00145** at curvature 0.35.
- Response is **linear in curvature**, not arc-like: 0.35→0.0015, 1.0→0.0041,
  2.0→0.0083, 4.0→0.0166, 8.0→0.0334. About 0.4% of the mesh's height per unit.
- **Not caused by the non-uniform `scale = dim` that single-part chunks carry.**
  A probe sphere scaled [1.45, 0.95, 1.15] and the same sphere frozen to
  identity both displaced 0.0083 at curvature 2.0.
- **Not the MCP tool.** Calling `cmds.nonLinear(type="bend")` directly, with no
  tool in the path, gives the same result: a 2.0-tall cylinder's tip moves
  0.066 — 3% of its length — at curvature 12.

So `bend` cannot deliver a hunch at any value the parameter accepts. Raised as
maya-mcp #636. The hunch came from `sculpt_ops soft_move` instead, which is a
tool path and not an escape.

**Task 5, row 4 — `soft_move` silently misses a mesh wider than its radius.**
The chest girdle is 2.2 wide; a radius-0.9 sphere centred on its top face
reaches no vertex at all (nearest top corner is 1.23 away). `applied: 1`, no
warning, nothing moved. On an 8-vertex cube there is no radius that catches the
top four and not the bottom four — 1.23 vs 1.60 — so the op is the wrong
instrument for a hard plate regardless. Rotating the chunk about its own pivot
gave the forward pitch and kept the plate hard, which is what the design wants.

**Task 6, row 12 — `boolean_op` does not preserve the pivot.** Measured, not
assumed: `golem_L_shoulder` went in with its pivot at the shoulder ball
[0.9, 3.85, 0.1] and came out with [1.1517, 3.964, 0.1452] — the new mesh's own
bbox centre. Same for the pelvis: [0, 2.45, 0] became [0.0069, 2.4526, 0.0076].
The boolean also freezes `scale` to identity, which is harmless.

This is a genuine gap and it costs exactly what #603 was built to buy. A caller
who rigs first and cuts sockets second loses the rig silently — the tool reports
`watertight: true` and says nothing about the pivot. Either `boolean_op` should
carry `a`'s pivot onto the result, or it should warn. Baseline for all 18 chunks
was captured to `pivots_pre_boolean.json` before the first cut, which is what made
the comparison possible; **Task 8's re-place pass is now confirmed necessary
rather than precautionary.**

**Task 6, row 13 — `new_name` collides with an input that the call itself
consumes.** `boolean_op(a=golem_L_shoulder, b=cutter, new_name="golem_L_shoulder")`
returned `golem_L_shoulder_001`. The name is reserved before the inputs are
deleted, so the most natural request there is — cut a socket into X and have it
still be called X — cannot be expressed. Proven by contrast, not inferred: the
pelvis call named its result `golem_C_pelvis` while the live object was still
called `pelvis_socket_L`, and got the clean name. Two `rename` calls were spent
undoing this.

**Task 6, step 2 — a fully interior cutter yields a sealed void, not a socket.**
The plan's cutter centre (the arm's proximal end, [1.25, 3.95, 0.15]) sits inside
the shoulder ball, and subtracting it would have produced a second shell — a
hollow, not a dish. Measured the shoulder's lowest surface vertex on the arm axis
(Y = 3.3833) and dropped the cutter to Y = 3.55 so its radius-0.35 sphere
protrudes 0.18 through that surface. Result: 1 shell, watertight, 760 → 1158 tris.

**Task 6, step 4 — `etch_text` `depth` is exact, and I twice measured it wrong.**
Recorded because the error is the instructive part. First reading said the brow
recess was 0.2 deep for a requested 0.08 — that was the brow's *rear wall*, since
I minimised over every vertex instead of the recess floor. Second reading, on
scrap cubes, said the tool delivered exactly half (0.03 → 0.015, 0.5 → 0.25) —
that was the glyph's *intermediate ring*, picked by taking the second distinct Z.
The full Z list settles it: `etchres1` carries 1.0, 0.75 **and 0.5**, so a
requested 0.5 cuts 0.5. The brow's floor is 0.08 below its own plate plane, with
0.12 of wall left behind. **No defect.** The lesson is that a min/max over a whole
mesh is not a depth measurement, and two independent wrong numbers agreed with
each other well enough to look like a finding.

**Task 6, row 14 — the silent miss had a visible cost, and only a capture found
it.** Every headless number for the chest girdle was green through Tasks 4–6:
watertight, right dimensions, pivot in place. It was the one chunk carrying no
shaping at all, because Task 5's `soft_move` missed it without saying so, and in
the first Task 6 capture it read as a plank laid across the chest. `bevel_edges`
at width 0.14, 2 segments took it from 8 to 48 verts and gave it chamfers that
hold a highlight; bbox is unchanged at 2.2 x 1.213 x 1.454, so nothing about the
proportions moved. `bevel_edges` is cmds-based and **preserved the pivot**, which
is the contrast that makes the boolean finding above concrete rather than
theoretical: same scene, same chunk, one op keeps the rig and the other does not.

**Task 7 — `array` mirror DOES carry the pivot, reflected.** The plan asserted the
opposite ("a mirrored chunk's pivot is not automatically the mirror of its source
pivot") and budgeted 11 `transform` calls to fix it. Measured before spending
them: all 11 right chunks already sat at the exact negated-X mirror of their
source, to 1e-3. Eleven calls saved, and the plan's assumption was simply wrong.

Read against the boolean finding above, this is the useful pair. Two ops in the
same scene rebuild a mesh; `array` preserves the rig and `boolean_op` discards it.
So pivot loss is a property of specific ops, not an inevitable consequence of
rebuilding geometry — which means `boolean_op` could carry the pivot and does not.

**Task 7, row 17 — `name_prefix` is a prefix, not a name.** All 11 mirror calls
returned `golem_R_<part>_1`. Nothing else in the scene held those names, so the
suffix is unconditional rather than collision avoidance — `array` numbers copies
because an array of 12 needs 12 distinct names, and mirror inherits that even
though it makes exactly one copy. Cost: 11 `rename` calls to undo, doubling the
task's tool count from 11 to 22. Worth ranking, because `mirror` is the one mode
where the copy count is always exactly one and the caller always knows the name
they want.

**Task 7 — every mirror reported positive `signed_volume` and zero warnings.** The
inverted-normals trap the tool description warns about did not fire on any of the
11. Recorded because a check that never fails still has to be run to know that.

**Task 8 — parenting cost 28 calls and lost nothing.** `maya_parent` takes one
child per call; that was read off the signature before the count was written down,
rather than assumed from the plan. All 29 chunks kept their world pivot AND their
world geometry to 1e-3. One root, 28 descendants.

**Task 8 — the rig works, and here is the number that says so.** Rotating
`golem_L_upperarm` 40° about its shoulder pivot moved every descendant while
preserving each one's distance from that pivot **exactly**: upperarm 0.6,
elbow gasket 1.19236, forearm 1.875, wrist gasket 2.54627, fist 2.875 — all
unchanged to six decimals. The fist travelled 1.9666 and the shoulder ball did not
move at all. That is a rigid rotation about the socket, which is the entire point
of #603, the `pivots` map, and this task taken together. The arm was returned to
rest and the full 29-chunk state re-verified against the pre-parent snapshot.

**Task 8 — a bbox check on a hierarchy is not a geometry check.** The first pass
reported 14 chunks as "moved". Every one of them was a node that had just gained
children, because `exactWorldBoundingBox` on a transform includes its descendants:
the pelvis now measures the whole golem. The 15 leaf nodes were all clean. Measured
again at shape level, nothing had moved. Same error family as the etch depth in
Task 6 — the measurement changed meaning under me while the numbers stayed
plausible.

**Task 9, row 21 — `boolean_op` takes THREE things, not one.** Task 6 found the
pivot loss. Cutting the visor slot on a chunk that was by now *parented and
atlased* exposed two more, and all three arrive silently on a call that reports
`watertight: true`:

1. **Pivot** — `golem_C_brow` went in at [0, 4.5, 0.3] and came out at [0, 4.65,
   0.72], its own bbox centre. Known since Task 6.
2. **Parent** — the result was created as `|golem_C_brow_slotted`, a **root
   object**. The input was a child of `golem_C_head`; the output was not. On a
   29-chunk rig that is a limb silently falling out of the tree.
3. **UVs** — every other chunk sat inside atlas patch 0 (0.005–0.245, 0.755–0.995).
   The boolean result carried fresh UVs spanning the **full 0–1 range**, i.e. it
   would sample all 16 patches of the atlas at once. This is the one that would
   have shipped: nothing in the scene looks wrong until the material goes on.

Undoing it cost `rename` + `transform` + `parent`, and the UVs were only recovered
because Task 9 re-atlased everything anyway. Ranked high for the report: a caller
who booleans **after** rigging, parenting or UVing loses all three without a word.

**Task 9, row 25 — `uv_atlas` refuses the integer `patch` its own docs describe.**
`patch: 0` returned `patch must be an integer index or [col, row], got '0'` — the
value arrived as the *string* `'0'`. The parameter is declared with no type on the
`Field`, so nothing coerces it, and the handler's own error message names the form
it just rejected. `patch: [0, 0]` works. Cheap fix, but it costs a round-trip and
reads as the caller's mistake when it is not.

**Task 9, row 27 — `params` on `assign_pbr` is the only route to per-chunk
emission.** The design wants emission varying per chunk; the atlas wants one shared
material. `maya_assign_material` cannot serve both — it *replaces* the shader, so
using it for emission would strip the three maps off that chunk. `assign_pbr` with
the same `maps` plus a distinct `name` and `params={"emission": …}` keeps both, at
the cost of one shader per distinct emission value. Chunks sharing a value share a
shader: the two shoulders sit at the same 1.5031 m from the eye, so they got one.
Six glowing chunks cost five shaders. Final count: **10 shading groups over 33
objects**, against 1 if emission had been uniform.

**Task 9 — the tracer eye, and the falloff, measured.** Emission down the whole
chain is monotonic non-increasing with no inversion: core 14.0 → trail 5.5 → 2.0 →
0.7 → brow 0.3149 → head 0.0806 → neck 0.0402 → girdle 0.0184 → shoulders 0.0134 →
belly, pelvis, shin, foot all 0.0. Body values are an inverse-square falloff on
measured distance from the slot centre [0, 4.655, 0.82], so the eye is visibly the
source rather than one bright thing among several. The slot is a 0.078 recess in a
0.2755 plate — it breaks the front surface and stops well short of the back, so it
houses the light instead of being a hole. All four bars verified inside the cavity
with 0.005 between neighbours, which is what makes it a smear and not segments.

**Task 9 — the mirror kept its UVs.** Sampled four L/R pairs before re-atlasing:
thigh 120/120, fist 152/152, shoulder 1624/1624, foot 96/96. `array` mirror
preserves UV counts exactly, which extends the Task 7 finding — it carries the
pivot *and* the UVs, where `boolean_op` carries neither.

**Task 9 — `world_scale` silently switches the projection to world space.** The
response reports `"projection": "world"` even though `project` was `box`. So a
chunk's patch region is chosen by **where it stands**, not by its own shape: the
head samples a steel-grey region of the atlas because it is 5 m up, the pelvis a
rust one. UVs are baked per-vertex, so nothing swims when a limb animates — but
L and R mirrors sample different regions, and moving the golem before atlasing
would have recoloured it. Free variety here; a trap for anyone expecting the
`project` they asked for.

**Task 9 — claim 2 of #601, answered: the kit's maps DO read on creature shapes.**
This was the claim most likely to fail, and my own guess before looking was that it
would. It does not. At the city's own density — `world_scale` 9.0, 113.78 px/m,
matching `demigol_structures/manifest.json` exactly — masonry courses read across
the chest girdle and plate banding reads down the limbs. The golem looks built of
the city's material rather than dressed in a picture of it, which is the whole
reason to match density rather than pick a flattering hero number. Recorded because
"maps authored for flat plates, used on a creature" is exactly the kind of thing a
benchmark should test rather than assume.

**Task 10, rows 28–30 — THE DOME LIT NOTHING, and it is the run's most
consequential finding.** `maya_setup_lighting(preset='environment')` built an
`aiSkyDomeLight` that drew as *background* and illuminated nothing at all. Not
dim — a plain 50%-grey `standardSurface` probe sphere rendered **pure black**
while the dome's own sky blew out behind it (`clipped_fraction` 0.45), at
intensity 1.0 and at 4.0 alike, so it was never a scaling problem.

Cause: `_build_dome` used `cmds.createNode("aiSkyDomeLight")`, which builds the
node but never wires it into Maya's lighting network. Fixed at `aa91c0f` by
building it with `cmds.shadingNode(..., asLight=True)`, plus two regression
tests; 833 green, and gated live — the same call that rendered a black golem now
renders brickwork, a horizon and a lit visor.

Four hypotheses died first, and they are recorded so nobody re-derives them: it
is **not** the ramp on `.color`, **not** `defaultLightSet` membership, **not**
the `lightList` connection, and **not** `render_scene`'s `relight`. Each was
applied to a live `createNode` dome and each produced a **byte-identical** frame
(mean_luma 177.9, 2753 distinct colours, five times running). Even renaming the
node out of the `mcpLight` prefix and matching every attribute to a stock dome
left it black. A light has to be *built* as a light.

What makes it matter is what the preset is FOR. Its own docstring says a
three-point rig physically cannot show a metal — metalness 1.0 renders black
there — and that only an environment can fix it. So the tool's answer to its own
measured failure was inert from the day it was written, and **every metallic
material ever judged through `environment` or `hdri` was judged unlit**. That
includes the kit steel this very golem is dressed in.

Honest note on cost: my first guess was the metalness trap, and metalness
measured 0.0. Diagnosis ran to 8 renders and 4 wrong hypotheses. It was worth
it, but the sequence is itself the lesson — the tool reported `warnings: []` at
every step and `fallback_light: false`, i.e. it believed the scene was lit.

**Task 10 — `render_scene` with a dome and no `target` frames the DOME.** The
first hero render put the camera at **5294 units** from a 5 m subject and came
back as a photograph of the sky. The guard that exists for exactly this —
"a render of nothing is a valid image" — did not fire, because it counts
`opaque_px`, and a dome fills the frame with opaque pixels: it reported
409600/409600. Passing `target` fixes it, but nothing warns you, and the failure
looks like a successful render. Worth ranking: the dome preset and the framing
default are individually reasonable and together produce a confident picture of
nothing.

**Task 10, row 31 — `render_sheet`'s `isolate` keeps the subject's DESCENDANTS.**
On a parented rig that is not a kit sheet. 14 of the 29 cells came back as
sub-assemblies rather than chunks — `golem_C_pelvis` rendered the entire golem,
`golem_C_head` rendered head + brow + tracer bars. Only the 15 leaf nodes were
right. The sheet is built for a flat kit, and nothing in it notices that the
subjects form a tree. Either `isolate` should hide descendants that are
themselves subjects, or the tool should warn when a subject contains another.

**Task 10 — `render_sheet` has no `timeout_s`, and its own timeout hint tells
you to pass one.** 29 Arnold cells at 256 px and 1 sample exceeded the 600 s
limit; the error hint reads "pass a larger timeout_s", but the tool's schema
exposes no such parameter, so the advice cannot be followed. Meanwhile the
session stays blocked until the render finishes. The workable answer is
`renderer='hw2'` — which is fast, and which **cannot show a dome at all**, since
image-based lighting is a render feature. So on a dome-lit scene the sheet is a
choice between correct-and-untakeable and fast-and-unlit.

**Task 10 — `capture_viewport` has the same dome-framing failure, and no way
out.** `frame_all` framed the dome, put the camera at **5498 units** from a 5 m
subject, and returned a **blank white image**. Unlike `render_scene` it has no
`target` parameter, so the only way to frame the subject is `isolate` — which is
precisely the code path #618 was about. With `isolate` it framed correctly at 9
units. Two tools, the same defect, and the one with fewer escapes is the one
that returns a plausible-looking blank.

**Task 10 — no image tool can write to disk, and the artifacts are a
deliverable.** `render_scene`, `render_sheet`, `capture_viewport` and
`capture_turntable` all return the image as the call's value and clean up after
themselves; the project's images folder held exactly one stale temp file. So a
run whose plan says "write every image under `evals/golem_run_2/`" **cannot do
it through the tool surface at all**. The three hero stills here were produced by
escaping to `execute_python` and calling the plugin's own `render._render_frame`
— reusing the real pipeline rather than reimplementing it, so the #615 display
transform still applies. **Recorded as an escape.** The contact sheet, turntable
and SSAO frames were NOT written, because writing them means reimplementing each
tool's compositing; they exist only in the run transcript. A `path` parameter on
the four image tools would close this outright, and it is the cheapest high-value
fix on the list.

## Task 10 — the rubric, answered honestly

The design set three questions. Two pass, one fails, and one passes only on the
measurement rather than on the eye.

**1. Does the silhouette read at thumbnail size — squat, crouched, arms to
mid-shin? YES.** At 900 px and again at contact-sheet scale the figure reads
immediately: wide shoulders over a short pelvis, forward hunch, fists ending
level with mid-shin. The head reads as a distinct blue-grey helmet against a rust
body — an accident of world-space projection sampling a different atlas region at
head height, not a decision, but it works and it is what makes the visor the
focal point.

**2. Do the joins carry under SSAO? NO.** The AO capture shows almost no contact
darkening at the gasket collars. They read as separate balls threaded on the
limb rather than as joins that sell a hinge — which is the exact failure the #574
design named and asked to be checked for. The gaskets are doing silhouette work,
not shading work. This is the honest answer and it is a real note against the
model, not against the tool.

**3. Does the glow read as one idea, tracer eye → seams → key? PARTLY.** The eye
reads strongly and unmistakably as the source. The body seam glow does not read
at all: at 0.013–0.315 emission against a dome-lit body it is measurable
(monotonic, verified) and invisible. So the falloff is correct and pointless at
these values. Either the body needs an order of magnitude more emission, or the
scene needs to be darker for it to have anything to be brighter than. Recorded
rather than quietly re-tuned, because "the number is right and the picture does
not show it" is worth more to the report than a dialled-in value.

**Step 5 — one proportion was wrong and was caught by looking.** The head sat
0.6 of its 1.0 height inside the chest girdle and the figure measured 4.5 against
the design's ~5.0. Corrected with the user (see the plan's Step 3 amendment) and
the call re-run. The `assemble` call itself is counted once: the correction
changed inputs, not the tool path.

