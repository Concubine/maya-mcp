# Redmine actions owed from the #602 phase-1 merge (2026-08-19)

Phase 1 merged to main at 2156008. The redmine MCP was disconnected in the
merging session, so these were drafted for the next session to file verbatim
(project 35). Delete this file (or strike items through) once filed.

## 1. Update #602 — notes + status Resolved

> Phase 1 merged to main at 2156008 (16 commits, fast-forward). Shipped:
> create_skeleton / bind_skin / pose_skeleton / reset_pose (45 tools total),
> rigmath pure-math module, degree<->UI-angle helpers promoted to units,
> fbxbytes skin-record parsing (Deformer/Cluster/BindPose, per-vertex weight
> sums from the bytes), export_fbx include_skins with byte-gated skin
> assertions. Gate: evals/serpent_live.py 25/25 twice on the agent Maya
> (9878, pid-verified) — unweighted_vertices 0, FK tip expectation agreement
> 1e-15 (tolerance 0.065), max_displacement 2.4734 in window [2.1734,
> 3.1393], longest posed edge 1.082x bind (ceiling 1.5x), shells 1, reset
> bit-identical, export skin block deformers=1 clusters=12 bind_pose=true
> weight-sum err 9.658e-4; renders judged a smooth continuous arc (no
> bike-chain read). Suites 1073+1skip headless, 110+1skip mayapy. Measured
> facts recorded in code comments: Maya prunes skin weights <1e-3 without
> renormalising (WEIGHT_SUM_TOL=1e-2); FBXExportSkins alone carries skins
> (input-connections flag irrelevant; a selected export must list the
> skeleton root); allDescendents returns joints leaf-first; a mid-chain bind
> root pulls in the joints above it (warned). Baseline for the consumer
> ticket: evals/serpent_live/baseline.json. Phases 2-6 scoped in
> docs/superpowers/specs/2026-08-19-rigging-surface-design.md.

## 2. Create: consumer-side serpent import (the #647 shape)

Subject: Import the phase-1 serpent somewhere real and measure it
Body: Import `evals/serpent_live/serpent.fbx` (repo maya-mcp, commit
2156008) into a real consumer (Unity, or whatever Demigol uses today).
Measure on import: bone count == 12, bind pose upright (bounds match
baseline world_bounds), deformation at a pose (apply the 11x8.18-degree
local-Z bend from baseline.bend_test.rotations_deg and compare the tip
against baseline.bend_test.expected_tip). Compare everything against
`evals/serpent_live/baseline.json`. Context: the byte reader verifies
well-formedness, not importability (#629/#647 scar tissue) — nothing this
repo exports has ever been opened by a consumer; this closes that loop for
skinned exports. Note for the importer: file-side weight sums err up to
~7e-3 because Maya prunes sub-1e-3 weights without renormalising — an
importer that renormalises will deform imperceptibly differently.

## 3. Create: rigging phase 2 — weights craft + the humanoid

Subject: Rigging phase 2 — mirror/smooth/region weights, weight_report, the judged humanoid
Body: Scope = the Phase 2 section of
docs/superpowers/specs/2026-08-19-rigging-surface-design.md: mirror_weights,
smooth_weights, set_region_weights, weight_report; gate = the ~20-joint
humanoid bound and posed through the golem five-pose set adapted to a biped,
judged renders + measured checks. Open sub-question deferred to this
ticket's plan: create_skeleton preset="biped". Carried from phase 1's
reviews, to address here: (a) per-mesh max_displacement/noop reporting in
pose_skeleton (combined max can hide one inert mesh among several) + a
multi-bindpose warning test; (b) file-wide skin totals in export skin
violations can misdirect on multi-mesh/multi-skin files; the
influenced_models==0 violation limb asserts an unmeasured cause; (c)
serpent_live's tearing detector compares global max edge — the humanoid
needs per-edge comparison; (d) note: an unskinned scene containing a scaled
joint now refuses export (LimbNode joined the identity-scale gate
unconditionally — plan-mandated; revisit against the #646 lights argument if
it ever bites); (e) bind_skin warns (not refuses) on a mid-chain root — the
first phase-2 commit may promote it to refusal if region weights make
sub-joint binds attractive; (f) phase 5 note: blend-shape Shape records
carry "Indexes" too — fbxbytes decodes int arrays wherever that record name
appears, harmless today, revisit then.

## 4. Create: create_primitive divisions spend 20:1 around-vs-along on cylinders

Subject: Long thin limbs cannot resolve their length — cylinder divisions coupling
Body: `create_primitive` spends `divisions` as one multiplier: a cylinder
gets ~20x subdivisions around per 1x along its axis, so a long thin limb
(serpent, arm, femur) cannot buy length rows without an absurd
circumference. The serpent gate paid a 160-side circumference for 16 length
rows (see the DIVISIONS comment in evals/serpent_live.py). Phase 2's
humanoid limbs hit this immediately. Candidate: per-axis divisions
([around, along]) on cylinder/cone, or a dedicated axial_divisions param —
decide with the humanoid build in hand. Raised by the phase-1 final review
(highest-value carry-forward of the branch).

## Relations

- #602 relates to all three new tickets; the phase-2 ticket blocks #665's
  richest form (spec says #665 runs after phase 4 at the earliest).
