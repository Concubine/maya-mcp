# #601 build ledger — one row per build step

`escaped` = this step BUILT something through execute_python. Measurement calls are
not escapes and are not listed.

| # | Step | Tool | Calls | Escaped | Why |
|---|------|------|-------|---------|-----|
| 1 | 18 chunks + 18 pivots | assemble | 1 | no | |

## Notes

**Step 1 — the rig arrived in the build call.** All 18 chunks came back
`combined: false`, i.e. every one is single-part. That is precisely the case that
used to get *no* pivot treatment at all: `combine` never runs for a single-part
chunk, so Maya's default pivot stood. Without #603's `pivots` map this body would
have had 18 centroid pivots and no rig. Verified independently with
`execute_python`, not from the response — `golem_L_thigh` at the hip ball
[0.55, 2.15, 0], `golem_L_upperarm` at the shoulder [1.25, 3.95, 0.15].

**Step 5 — one proportion was wrong and was caught by looking.** The head sat
0.6 of its 1.0 height inside the chest girdle and the figure measured 4.5 against
the design's ~5.0. Corrected with the user (see the plan's Step 3 amendment) and
the call re-run. The `assemble` call itself is counted once: the correction
changed inputs, not the tool path.

