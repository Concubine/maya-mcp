# #601 build ledger — one row per build step

`escaped` = this step BUILT something through `execute_python`. Measurement calls
are not escapes and are not listed. Every escape carries a reason.

Design of record: `docs/superpowers/specs/2026-08-15-golem-articulated-design.md`
Plan: `docs/superpowers/plans/2026-08-15-golem-articulated.md`

## Before the build

The toolset gained one capability first, because the audit found it missing before
the run started rather than during it: per-object pivot placement (#603). Placing 29
pivots at their joint sockets had NO tool path — `transform` took no pivot,
`assemble`/`combine` took one global mode for a whole call, and `array`'s pivot was
only the mirror plane. Built as `transform.pivot` and `assemble.pivots`, commits
`6cbe40c..89f64ba`, live-gated at `PASS pivot=[0,10,0] bbox unchanged`.

Two defects were found on the way in and are part of this run's evidence:

- **#604** — the staleness handshake read `CLEAN` against a Maya still running the
  old code, because `version.plugin_info()` re-reads the digest and stamp from disk
  on every ping. Between a deploy and a restart it reports the copy that is not
  live. Caught by wire-probing the dispatcher rather than trusting the check.
- The live gate script itself skipped cleanup on every failure path, and because
  `polyCube` auto-uniquifies, a leftover object would have made the NEXT run
  silently measure stale state. Fixed before it ever ran.
- **The MCP server process was stale too**, one layer above #604. The user restarted
  Maya, which fixed the plugin; the MCP server that exposes the tools is a separate
  process started before the pivot commits, so `maya_assemble` still advertised no
  `pivots` and `maya_transform` no `pivot`. The build could not begin. #604 at least
  has a handshake that could be repaired — nothing checks the MCP server against its
  own source at all. Caught by reading the live tool schema instead of assuming the
  deploy covered it.
- **`assemble` reported the pivot it was ASKED for, not the one Maya has** — found by
  the final whole-branch review. `placed = list(wanted)`, so the response could not
  disagree with the request in any environment. The 29-chunk build's own result was
  therefore worthless as rig verification, and would have read PASS regardless. Fixed
  to query back, plus `evals/assemble_pivots_live.py` covering the three cases
  (explicit / multi-part omitted / single-part omitted).

The pattern in all four: a green signal that was reading something other than the
thing under test. Two were caught only by distrusting the check itself.

## Build steps

| # | Step | Tool | Calls | Escaped | Why |
|---|------|------|-------|---------|-----|
