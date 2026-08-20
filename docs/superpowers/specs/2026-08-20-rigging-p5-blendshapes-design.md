# Rigging phase 5 — blend shapes (design)

Ticket: #691. Parent spec: `2026-08-19-rigging-surface-design.md`, Phase 5
section — this doc settles the decisions that spec deferred, agreed with the
user 2026-08-20. Currency and boundaries are unchanged: the pose map stays the
phase-1 rotation map, no persistent solver state, engine owns feel.

## Tools

### `create_blendshape(mesh, targets=[{name, target_mesh}])`

Wires a `blendShape` deformer on `mesh` with one target per entry. Targets are
ordinary meshes authored with the existing modeling/sculpt tools — this tool
only wires deltas.

* **Front-of-chain.** The deformer is inserted so it evaluates BEFORE the
  skinCluster (`deformationOrder` front-of-chain). Shapes model the neutral
  surface; the skin then carries the shaped surface to the pose. This is what
  makes a corrective correct at a bent joint.
* **Topology must match.** `target_mesh` vertex count must equal the base's;
  mismatch is a refusal carrying both measured counts. No wrap fallback, no
  silent nearest-point transfer.
* **Targets are consumed.** After wiring, the target meshes are deleted — the
  deltas live in the deformer node, and a stale editable copy invites sculpting
  a mesh that no longer feeds anything. (Same reap logic as boolean operands.)
* **Names are the contract.** Each target's `name` becomes the weight alias and
  the exported Shape record name.
* Returns MEASURED per target: `max_delta` (vertex displacement at weight 1,
  read from the scene by evaluating the target, not echoed from the input) and
  `vertex_count`. Warnings with numbers for zero-delta targets (a target
  identical to the base is almost certainly a mistake).

### `set_blendshape_weights(mesh, weights={name: 0..1})`

* Sets the named weight attributes; unknown names are a refusal listing the
  names that exist.
* Returns MEASURED after the write (#636 rule): `max_displacement` combined and
  `per_target`, re-read from the deformed mesh against the neutral.
* Weights all-0 IS the reset — no new reset tool, and `reset_pose`'s contract
  is untouched (joints only).

## Export

* Shapes ride along automatically whenever a blendShape deformer exists on an
  exported mesh (`FBXExportShapes`). No new caller-facing parameter; existing
  callers see identical behavior on shape-less scenes.
* Byte gate (`fbxbytes.py`): assert one Shape record per declared target name,
  with non-empty delta data. This is where #668 carry-note (f) is due: Shape
  records carry `Indexes` int arrays (sparse vertex indices); the reader
  currently just tolerates them wherever they appear — now it must read them
  and report per-shape counts.

## Gate

`evals/` live gate on the disposable 9879 Maya (pid-verified), extending the
#668 humanoid. The user chose BOTH target kinds:

1. One **facial expression** target — the readable, judge-a-render case.
2. One **muscle corrective** target (e.g. elbow/knee bulge) — judged AT a
   posed joint, which is what actually proves front-of-chain ordering under
   the skinCluster.

Checks: judged renders at weight 0 / 0.5 / 1; measured displacement strictly
monotonic across those weights; skinned+shaped export passes the byte gate
(Shape records per name, skin gates still green); measured numbers recorded in
`baseline.json`. Plan literals derived from measurement, not guessed.

## Out of scope

In-between (progressive) targets, driven keys / set-driven correctives,
editing or extracting targets after wiring, non-matching-topology transfer,
and anything simulated (#675 boundary stands).
