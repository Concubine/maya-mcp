# #817 — export_fbx warns when a skin ships more than 4 influences per vertex

Redmine #817. The one durable sentence out of #748 (Closed by the #756
re-scope as consumer-side; not reopened). bind_skin allows 8 influences on
purpose; a consumer that caps at 4 - Unity's default import, MEASURED in
#743/#748 as `bones_per_vertex_max = 4` - keeps the 4 heaviest and
renormalises, and #748 measured the cost on the drifter: 22,716 of 23,922
vertices capped, deformation drift ~3 % of the joint rotation on the deepest
chain, ~0 at rest. Nothing in the export said so.

## What shipped

- `fbxbytes.skin_facts` reads, per vertex, how many clusters carry a NON-ZERO
  weight in the records that ship (a weight the exporter dropped below 1e-3
  is not an influence the consumer sees) and returns `max_influences` and
  `vertices_over_4_influences`; null / 0 when the records are unreadable.
- `export.skin_warnings` says it once, as a WARNING never a violation: the
  count, the file's maximum, the 4-heaviest rule, the measured drift, and the
  two ways out (rebind at 4, or keep it for a consumer that reads 8).
  `export_fbx` carries it in `warnings`; `SkinFacts` gained the two fields.
- protocol.md paragraph after the skin gate rules.

## Gate

`evals/influence_warning_live.py` **9/9** (no captures): a 10-joint chain and
a 16×36 tube bound at 8 export with `max_influences 8`, `592` vertices over
4, one warning naming both; rebound at 4 the same file reports 4 / 0 and no
warning; both files bind the same 10 clusters; the file's maximum equals
`weight_report`'s in both cases. Noted in passing: the 8-bind's
`max_weight_sum_error` is 1.5e-3 in the file - the exporter's sub-1e-3 drop,
inside `WEIGHT_SUM_TOL` = 1e-2, exactly as the tolerance's note predicts.

## Suite

See the ticket's closing note for the junit numbers.
