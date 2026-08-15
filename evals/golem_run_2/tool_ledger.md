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

**Step 5 — one proportion was wrong and was caught by looking.** The head sat
0.6 of its 1.0 height inside the chest girdle and the figure measured 4.5 against
the design's ~5.0. Corrected with the user (see the plan's Step 3 amendment) and
the call re-run. The `assemble` call itself is counted once: the correction
changed inputs, not the tool path.

