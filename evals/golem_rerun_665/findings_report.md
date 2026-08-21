# #665 — Golem rebuild with rigging available: findings report

> **Relocated 2026-08-21.** The run was built in `D:\devel\golem-rerun\` and now
> lives here, next to this report: `out/`, `out_v21/`, `out_v3/` and the briefs.
> The absolute paths below and in the BRIEF/DESIGN files are left as written —
> they are what the builder was actually told, and rewriting them would edit the
> record. Auto-checkpoints stayed behind the gitignore, as with every other run.

Run date 2026-08-21. Clean-room build by a fresh agent in `D:\devel\golem-rerun\`
(brief + creature spec only, no access to this repo or the #601 delivery),
against the post-SSC-fix plugin (f32c49ec1e49) on a disposable Maya (pid 7280,
port 9879). Build artifacts: `D:\devel\golem-rerun\out\` (scene, FBX, physics +
pose JSON, engine README, renders, NOTES.md, LEDGER.md). Comparison baseline:
`evals/golem_delivery/`.

## The question, answered

**Was chunk-only tooling a load-bearing constraint? No — the consumer contract
is the load-bearing part.** Given the full 56-tool surface with skeletons,
skinning, IK, blend shapes, and clips available and *no instruction about
whether to use them*, the builder chose a rigid chunk hierarchy — "no skeleton,
no skinning" — and defended it from the contract: primitive colliders only,
breakable in play, physics-driven motion. Their words (NOTES.md): "rigid bodies
with joint pivots ARE the engine's native vocabulary."

The rigging surface was used *selectively, where it paid*: `maya_author_physics`
generated the manifest (then the builder hand-tightened loose auto-fit
colliders); `create_skeleton` / `bind_skin` / `pose_ik` / `author_clip` were
correctly judged irrelevant to a rigid-body creature and never called.

**Consequence for the tool surface:** the discipline does not need a
"rigid_body authoring mode" or constraint restated in tool descriptions. It
needs the *engine facts stated in the brief/contract* (collider policy,
breakability, who drives motion). A builder who knows those facts rederives the
decomposition; the #601 spec's chunk prescription was documentation of a
consequence, not a necessary guardrail.

## Measured comparison (byte reader on both FBXs, same code path)

| Measurable | #601 baseline | #665 rebuild |
|---|---|---|
| Rig gate (`check_rig_delivery`) | pass | pass |
| Height (composed from bytes) | 4.02173 m | 4.06675 m (target ≈4.0) |
| Nodes | 33 (all meshes; mesh transforms ARE the joints) | 45 = **16 null articulation nodes + 29 meshes** |
| Hierarchy depth | 6 | 6 |
| Physics bodies | 29 chunks (incl. 10 gasket collars) | **13 segments** + ball spheres & cores as render-only children |
| Non-identity scales in file | 0 | 0 |
| InheritType | all 1 | all 1 (post-#703 authoring verified end-to-end) |
| Skins / clusters / blendshapes | 0 | 0 |
| Stray takes | 1 ("Take 001", empty) | **0** |
| Triangles | 14,130 | 11,740 (verified live; ledger's ~11.5k honest) |
| Watertight | yes (gated) | yes — 29/29 zero boundary edges, verified live |
| Pivot discipline | pivot = proximal socket, on mesh transforms | joint position = **null node translation** (`golem_<segment>` = joint); pivots exact by construction |
| Pose data | 5 poses, absolute locals for all 33 nodes | 5 poses, symmetric per-segment locals + engine root motion |
| Tool calls / escapes | (see `evals/golem_run_2/tool_gaps_report.md`) zero geometry escapes, 1 artifact escape | **~327 calls, zero geometry escapes, 2 presentation escapes** (light tint, hero camera), export via `maya_export_fbx` (refused once, rightly — live scale — fixed and passed) |

Side-by-side render: `side_by_side_hero.png`. The user's verdict on sight:
"formidable, where the others felt meh."

## Ranked findings

**1. The structure diverged — in the better direction.** The rebuild separates
articulation from geometry (null joint nodes carrying render/physics meshes as
children) where the baseline overloaded mesh transforms as joints. It also
replaced the baseline's 10 gasket collars with **ball-joint spheres centred on
each pivot** — rotation-invariant, so sockets stay filled at any angle. That
structurally solves the baseline's worst *measured* criticism ("joins fail
under SSAO; gaskets read as balls threaded on a limb") — the rebuild's AO check
passed on first look (ledger step 12). Freedom produced a cleaner engine
contract, not a sloppier one.

**2. `maya_render_scene` cannot express an authored camera — the biggest tool
fight of the run** (~12 calls + 6 python escapes on the hero shot). `current`
does not use the active viewport camera (verified by the returned camera
position), and there is no camera parameter. The builder's chosen low-angle
monument shot was unexpressible; they fell back to python, lost the tool's
exposure calibration, produced four bad renders, and surrendered to a canned
front angle. Extends #670. **Ticket candidate: camera param (or honest
`current`) on render_scene.**

**3. Procedural texture maps silently die at export.** The kiln-plate grain is
`apply_texture_recipe` noise_bump; FBX cannot carry procedural networks, so the
exporter dropped `mcpTex_noise` with only a GUI warning. The byte gate is
structurally blind to it (file internally consistent — the #703 defect class).
The delivered FBX renders flatter than every judged render of the run. **Ticket
candidate: export bakes procedurals to file textures (`convertSolidTx`) or
warns with numbers; gate asserts the material's maps survived.** This also
promotes the roadmap's Tier-0 "bake to atlas" item from look-dev to export
honesty.

**4. `maya_transform(relative=false)` sets WORLD orientation — a semantics
trap that cost a full pose re-authoring pass.** The builder's first crouch
silently bent a knee 110° local; caught only because the tool reports achieved
world positions. Discoverability fix (docstring wording), not a behaviour
change — but it will bite every pose author.

**5. `setup_lighting` has no per-light colour.** The design named the exact
look (warm key, cool rim); the preset cannot say it; two-line escape. Cheap
ticket candidate.

**6. `author_physics` auto-fit is loose on limb chunks** — volume_ratio up to
3.3 on thigh/shin/forearm; the builder hand-authored tighter boxes and shipped
those, keeping the tool's set as reference. The knee neutral-at-extreme rule
worked as designed and its warnings ("numbers rather than vibes") were praised.
Partial win: the measurement machinery is right, the fitter needs work on
elongated multi-shell chunks.

**7. Clips cannot exist without joints.** `author_clip` keys joints only, so a
chunk creature cannot carry its tracer-scan animation as an FBX take; it
shipped as prose ("translate ±0.24 m along local X"). For physics-assembled
creatures the builder judged data the honest form anyway — but the gap is now
measured: **the animation surface and the rigid-body surface do not compose.**

**8. Smaller traps, recorded:** `array(mirror)` bakes transforms so a later
absolute scale double-scales (one shrunken upper arm); checkpoint restore kept
unrelated edits batched before the risky op (ordering favored the builder this
time); `maya_group` leaves the pivot at bbox centre so hierarchy building costs
an explicit pivot call per node (14×); `combine`'s one-material-per-object rule
shaped the two-meshes-per-segment design (plates + core) — a constraint that
*produced* the glow-through-cracks look, worth knowing as a feature.

**9. #669 (cylinder axial divisions) did not bite** — this builder built from
boxes and plates throughout. The serpent/humanoid evidence stands; this run
adds nothing to it.

## Model notes (not tool findings)

- The core meshes protrude past the plate silhouette in places (user-observed;
  visible at pelvis/waist in the hero). A containment margin between render
  core and plate shell was never asserted. If a fix pass happens: inset the
  cores, and/or a thin trim/crown ring on plate edges at joints — an *authoring*
  fix, measurable in Maya (max core-outside-plates distance), not an engine
  masking job.
- Rest height 4.067 m vs the spec's ≈4.0 — within "≈", stated in the delivery.

## Verdict for the roadmap

The constraint was not doing the design work; the contract was. Keep stating
engine facts in briefs and delivery contracts. The run's real product is
findings 2, 3, 6: render camera, export map honesty, collider fit — all three
now have two-run evidence trails.
