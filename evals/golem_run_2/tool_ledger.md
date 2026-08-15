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

**Step 5 — one proportion was wrong and was caught by looking.** The head sat
0.6 of its 1.0 height inside the chest girdle and the figure measured 4.5 against
the design's ~5.0. Corrected with the user (see the plan's Step 3 amendment) and
the call re-run. The `assemble` call itself is counted once: the correction
changed inputs, not the tool path.

