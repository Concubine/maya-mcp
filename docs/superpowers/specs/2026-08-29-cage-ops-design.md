# Subdivision-cage vocabulary — design (#769)

Date: 2026-08-29. Short brainstorm (the ticket pre-answered most of it);
design approved in chat. Sibling of #768: that ticket added what can be
authored, this one raises the quality of what is authored. Analysis:
`docs/superpowers/plans/2026-08-26-modelling-vocabulary-gap.md` §2.

## Decision: four ops INSIDE `maya_sculpt_ops`

No new tool. `sculpt.py`'s `_OPS` registry gains four entries, batched per
call like the existing eight, same mesh/result conventions:

1. **`insert_loop`** — wraps `polySplitRing`. Params: `edge` (ONE component
   in the `"e[12]"` syntax `bevel_edges`/`crease_edges` already take — reuse
   that resolver, never invent a second), `count` (int ≥1, default 1),
   `position` (0–1 across the ring, default 0.5; `count`>1 distributes
   evenly across (0,1)). Result reports edges/faces before → after.
2. **`extrude_edges`** — wraps `polyExtrudeEdge`. Params: `edges` (list,
   same syntax), `translate` ([x,y,z] world offset, required — an extrude
   that moves nothing is a no-op nobody wants silently), `divisions`
   (default 1). Result verifies the measured new-face count matches
   `len(edges) * divisions` and reports it.
3. **`mirror_topology`** — wraps `polyMirrorFace`. Params: `axis`
   ("x"|"y"|"z"), `direction` ("+"|"-", default "+" meaning the geometry is
   duplicated toward positive axis — stated, probe-verified), and
   `merge_threshold` (scene units, default stated in the tool docs — the
   value is chosen during implementation by probing what merges a
   coincident seam without eating nearby detail; NOT silently Maya's).
   **The care-point rule:** after the op, shell count is MEASURED; if the
   result is not one shell, the op FAILS with the measured minimum seam gap
   in the message (hint: raise `merge_threshold` or move the open border to
   the mirror plane) — unless `allow_unmerged=true` was passed. Result
   reports `merged_vertices` and `shells`.

   > **2026-08-29 fix-review amendment:** `direction` is NOT exposed on the
   > op after all. `evals/cage_probe_769.py` measured `direction` in
   > `{0, 1, -1, 2}` to produce byte-identical results in every
   > whole-object invocation tested — genuinely inert on this Maya, not
   > merely undocumented. Per #764 doctrine (a measured-inert param is
   > refused, not kept on speculation), Task 2 dropped it from
   > `MIRROR_TOPOLOGY_KEYS` entirely; passing it is refused by
   > `require_known_keys` like any other unread key. The op's surface is
   > **axis-only** about the world-origin plane. The side that actually
   > gets duplicated is whatever the probe recorded: for `axis="x"` on a
   > half-cube spanning x in `[-2, 0]` with an open border at x=0, the
   > duplicate lands on the **positive** side, producing a closed box
   > spanning `[-2, 2]` — there is no caller-facing control over this, only
   > the fact of it.
4. **`split`** — wraps `polySplit`. Params: `points` — a list of
   `[edge, t]` pairs (`"e[12]"` syntax + parameter 0–1 along that edge),
   ≥2 entries. Result reports edges/faces before → after.

All four validate through the existing per-op param validation pattern in
`sculpt.py` (unknown op-level keys refused the way existing ops refuse).

> **2026-08-29 fix-review amendment:** the `"e[12]"` resolver
> `bevel_edges`/`crease_edges` use (`_components` in `sculpt.py`) could NOT
> be literally reused for `insert_loop`/`extrude_edges`/`split` as this
> spec originally implied. `_components` returns a component STRING
> (`"mesh.e[3:7]"`) and accepts ranges — exactly what `bevel_edges`/
> `crease_edges` want, since `polyBevel3`/`polyCrease` take component
> strings directly. But `evals/cage_probe_769.py` measured that
> `polySplitRing` (rootEdge=), `polyExtrudeEdge`'s per-edge counting, and
> `polySplit` (insertpoint=(idx, t)) all need a **raw single integer
> index**, not a string, and must REFUSE a range/list rather than silently
> taking one element from it (a range like `"e[0:3]"` would otherwise pass
> and undercount `len(edges)` by a factor of the range size in
> `extrude_edges`/`split`'s new-face verification). Task 2 therefore added
> a second, distinct helper, `_single_component_index`, rather than
> stretching `_components` to cover both shapes.

## Probe-first (the two risky commands)

`polySplitRing`'s ring addressing/flags and `polyMirrorFace`'s
axis/direction/merge semantics get a mayapy probe before implementation —
both are flag-rich commands of the kind that has repeatedly diverged from
documentation on this Maya (#764/#768/#774 precedents). `polyExtrudeEdge`
and `polySplit` are probed in the same script since it costs one section
each.

## Testing

- **Headless**: param validation refusals per op (bad component syntax,
  count/position/threshold shapes, empty lists) — the existing sculpt
  validation test pattern.
- **mayapy** (real geometry, counted): insert_loop on a cylinder adds
  exactly one ring of edges/faces at the stated position; extrude_edges on
  a plane border adds the predicted faces; mirror_topology on a half-cube
  yields ONE shell with the predicted vertex merge count, and the
  refuse-on-unmerged path fires with a measured gap when the mesh sits off
  the plane; split adds the predicted topology.
- **Live gate** (`evals/cage_ops_live.py`, disposable 9878 Maya): build a
  deliberately asymmetric HALF form (primitives + existing sculpt verbs) →
  insert loops → extrude an edge border → `mirror_topology` → measure the
  ticket's promise directly: **every vertex maps onto a counterpart under
  reflection about the mirror plane within an epsilon chosen by
  measurement**; shells == 1; then `smooth` (the workflow's last step)
  survives with the loops holding the silhouette (bbox comparison
  smoothed-with-loops vs smoothed-without — the loop's whole purpose,
  measured); composition: `uv_atlas` + `bind_skin` work on the result; one
  render sheet for eyes.

  > **2026-08-29 fix-review amendment:** the gate does NOT assert a global
  > bbox comparison as this spec said above — it measures LOCAL
  > displacement instead. A global bbox (whole-mesh extent) dilutes a
  > strictly local Catmull-Clark effect: `polySmooth` only pulls a vertex
  > toward the average of its own 1-ring neighbourhood, so a support loop's
  > whole job — holding one specific span of silhouette still — can move
  > the mesh's overall bounding box by nothing at all when that span sits
  > away from whichever axis extreme the bbox tracks (measured: a
  > border-adjacent loop produced ZERO global bbox effect in the probed
  > half-form). The shipped gate instead captures the post-`insert_loop`
  > world position of one of the loop's own new vertices, then compares
  > post-smooth displacement AT THAT SAME LOCATION between a looped build
  > and an otherwise-identical loopless control: looped displacement
  > 0.176777 vs loopless 0.242956 — ratio 1.374x. `RATIO_THRESHOLD = 1.2`
  > sits comfortably below the measured 1.374x while still failing a loop
  > that did nothing (ratio ~1.0).

## Out of scope

- No new tool surface; no changes to existing eight ops beyond registry
  adjacency.
- `polyChamferVertex`/`birail`/`curveWarp` — measured absent on this Maya.
- Cage *presets* (e.g. "loop-cut a limb") — YAGNI until a consumer asks.
