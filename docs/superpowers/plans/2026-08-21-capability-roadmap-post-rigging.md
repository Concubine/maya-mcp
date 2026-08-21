# Capability roadmap — after the rigging surface

Drafted 2026-08-21, with the rigging roadmap (phases 1–6, #602/#668/#671/#676/
#691/#695) complete and the #665 golem rebuild in flight. This ranks the Maya
capabilities the 56-tool surface does NOT employ, scored on two axes:

- **Innovation** — how much genuinely new capability it adds to an
  LLM-driven pipeline (not "is it new in Maya").
- **LLM-realism** — how well an LLM generator can actually drive it *blind*:
  deterministic, measurable, gate-able with numbers, no interactive-viewport
  or brush-stroke dependence, no cloud round-trip inside a gate.

The two axes trade off. The most innovative items (Bifrost graphs, mocap
retargeting) are the hardest to gate; the most realistic items (deformers,
baking) are incremental. The roadmap orders by **realism first, innovation
second**, because this project's history says gates are what make any of it
real — a capability that can't report measured numbers ships broken (the
#629/#703 lesson, twice).

Standing rules, unchanged:

1. **Art runs are the requirements engine.** Nothing below gets built until a
   run or a named consumer fights for it. The tiers are a ranking of *what to
   reach for when something fights*, not a build queue.
2. **The engine owns feel** (#675). Simulation stays out; the verdict is
   restated per-item below where it applies.
3. Every new surface arrives with its byte/live gate or it doesn't arrive.

## Tier 0 — recommended now (top priority)

| Capability | Innovation | LLM-realism | Why now |
|---|---|---|---|
| **deltaMush + pose-space correctives** (pose interpolator driving phase-5 blendshapes) | medium | **high** | Directly improves rigs we already build; correctives that fire at a joint angle instead of a hand-set weight complete the phase-5 story. Fully deterministic; gate = measured artifact reduction at posed elbows/shoulders vs the phase-2 humanoid baseline. |
| **Baked AO / curvature / normal into the atlas** (transfer maps, Arnold bake) | medium-high | **high** | Fixes a *measured, shipped* weakness: the delivered golem's joins fail under SSAO and its seam glow is invisible (evals/golem_delivery/README.md). Baking paints the contact shadow into the texture. Outputs are files — byte-checkable, diff-able, gate-native. This is also the LLM-innovative one: procedural look-dev quality without a painter. |

These two are recommendations, not tickets yet. File tickets when picked up;
the #665 findings report may supply the evidence that promotes them (if the
rebuild's skinning shows the same joint artifacts, Tier 0 row 1 stops being
theoretical).

## Tier 1 — realistic, parked on a named trigger

| Capability | Innovation | LLM-realism | Trigger that unparks it |
|---|---|---|---|
| **copySkinWeights / transferAttributes** | medium | high | The first sculpt-high → retopo-low workflow, or any re-mesh of an already-skinned asset. |
| **Unfold3D + automatic seams** (real UV unfolding with stretch metrics) | medium | high | The first asset whose texturing outgrows atlas patches. Stretch/coverage metrics make it gate-able. |
| **HumanIK retargeting** (mocap or foreign-rig animation onto our skeletons) | **high** | medium-high (deterministic once baked; setup is stateful) | A consumer that imports animation. Demigol still forces importAnimation=false — until that flips, authored clips (phase 6) are enough. Biggest single capability jump on this list when it fires. |
| **Time Editor clip blending** (authored transitions) | medium | medium-high | A consumer that wants transitions authored rather than engine-blended. Phase 6 settled on engine-side blending; this reopens only on demand. |

## Tier 2 — innovative, harder to hold to the discipline

| Capability | Innovation | LLM-realism | Notes |
|---|---|---|---|
| **Bifrost procedural graphs, non-sim** (scatter, procedural geometry) | **very high** | medium-low | Graphs are text-representable (compound JSON), which is tantalizing for an LLM author — but the headless authoring API is awkward and outputs are hard to assert. Worth a scoping spike *only* after an art run demands procedural scatter (rubble for the breakable golem is the plausible first ask). |
| **Bullet settle-pose, bake-and-discard** | high | medium | #675's "nearest justified crack": drop chunks, sim N frames, read resting transforms into the phase-1 pose map, delete every sim node. Zero persistent state. Still parked behind a named demand; the boundary otherwise stands. |
| **MASH / XGen** (instancing, grooming, fur) | high | low-medium | Art-run territory; no consumer has asked. Fur in particular is interactive-grooming-shaped — poor blind-driving fit. |

## Tier 3 — watch, do not build

| Capability | Why it stays parked |
|---|---|
| **Flow Retopology** (2027 cloud auto-retopo) | Better than the polyRetopo our remesh_retopo wraps, but cloud round-trip + nondeterministic — cannot sit inside a byte gate. Re-evaluate if Autodesk ships it locally/deterministically. |
| **ML Deformer** | Trained approximation of a deformer stack; nondeterministic training, engine-adjacent purpose. Doesn't fit "measured numbers, reproducible". |
| **Nucleus / MPM / fluids — any live simulation** | The #675 boundary, verbatim: two sources of feel, nondeterminism, and a consumer that executes none of it. Stands. |

## Relation to the current path

This roadmap does **not** supersede the active work. Order of operations:

1. **#665 golem rebuild** (in flight now) — its findings report is itself an
   input to this roadmap and may reorder Tier 0/1.
2. **Small open bugs** as convenient: #669 (cylinder per-axis divisions —
   likely re-confirmed by #665), #670 (render_scene zoom near-plane), #704
   (monitor only).
3. **Tier 0**, when the user green-lights it — ideally with #665's evidence
   in hand.
4. Tiers 1–3 wait for their triggers, per standing rule 1.
