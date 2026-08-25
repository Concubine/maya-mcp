# #714 — Export texture honesty: detect, report, gate; then bake — Design

Ticket: #714 "FBX export silently drops procedural texture maps — bake to file textures or warn
with numbers". Evidence: `evals/golem_rerun_665/findings_report.md` finding 3 (five procedural
noise+bump networks judged in renders, absent from the delivered FBX, recorded only as a README
note); measured byte-level confirmation in `evals/drifter_live.py::_fbx_texture_facts` (a `file`
node survives as one Texture + one Video record carrying the image basename; procedural node
names occur zero times in the bytes).

This design was produced by a three-way design competition (in-export bake / separate bake tool /
report-first gate) scored by a three-judge panel (honesty, risk/evidence, consumer-ergonomics
lenses). The in-export bake lost decisively on all three lenses — scene mutation inside export,
resting on unmeasured facts, shipping pixels the builder never judged — and is **rejected, not
deferred**. The synthesis: the report-first gate ships unconditionally as **phase 1** (nothing in
it rests on an unmeasured fact), and the persistent bake tool ships as **phase 2**, gated on the
probe measurements phase 1 banks.

## 0. Commitments

| Decision | Commitment |
|---|---|
| Where honesty lives | `export_fbx` detects and reports ALWAYS (no flag arms it); the byte gate proves every file-backed claim survived. |
| Where the cure lives | A new single-responsibility tool `maya_bake_textures` (phase 2) that PERSISTENTLY rewires procedurals to baked file textures — post-bake renders show exactly what ships, and the builder re-judges pixels before export. |
| Never | Baking inside `export_fbx`. Scene mutation inside export, restore-on-failure machinery, and unjudged shipped pixels are a complexity-and-honesty class the export architecture was designed to avoid. |
| Back-compat | Default behavior refuses nothing that passes today. The golem-class drop becomes named `dropped_maps` + warnings instead of a README apology. |
| Evidence discipline | Phase 1 depends on zero unmeasured facts (its one new parse is TDD-pinned against the committed drifter FBX). Everything bake-related is measured by probes BEFORE phase 2 code; a disappointing probe re-scopes phase 2, never phase 1. |

## 1. Phase 1 — the gate (unconditional)

### 1.1 `maya_export_fbx` — one new param

**`require_baked_textures: bool = False`** (validated exactly like `include_skins`).

- `False` (default): procedural texture claims produce **warnings** and a populated
  `dropped_maps` block; the export still writes.
- `True`: refuses **pre-write** (the cost-nothing principle — nothing is written) on any
  procedural claim or any unenumerable material, listing every (material, slot, terminal chain)
  and naming both remedies: `maya_bake_textures` (once phase 2 ships; until then the hint names
  file textures / `assign_pbr` re-authoring).

A bool, not a tri-state enum: the two behaviors are warn and refuse; "drop silently" is not a
mode this project offers. The name states the contract (the caller demands file-backed-only
cargo), sitting beside the `include_skins` declaration precedent without copying its shape —
textures are never optional cargo, so there is no include decision.

### 1.2 `maya_export_fbx` — result additions

`ExportFbxResult` (src/maya_mcp/schemas.py) is `extra="ignore"`, so BOTH fields must be added to
the model or they are silently dropped — the #757 precedent (its branch added warnings
forwarding to two other wrappers; follow that shape, and see §4 sequencing).

- **`warnings: List[str]`** (default empty) — new on this result, generic.
- **`textures: Optional[TextureFacts] = None`** — present when the scene claims any map OR the
  file carries any Texture record; null otherwise (the `shapes` presence rule):

```
TextureFacts:
  texture_records: int           # Texture object records counted in the bytes
  video_records: int             # Video object records
  file_maps: [FileMapFact]       # scene-claimed file-backed maps, byte-verified
  dropped_maps: [DroppedMapFact] # scene-claimed procedural maps, byte-confirmed absent
  unclaimed_records: [str]       # record basenames no walked claim explains
  unavailable_reason: Optional[str]

FileMapFact:
  material: str; attr: str       # real attr, e.g. "baseColor"
  slot: Optional[str]            # semantic slot via pbr.SLOTS / material.SHADER_SLOTS, else null
  file_node: str; basename: str
  on_disk: bool                  # image existed at export time (feeds the §1.5 matrix)
  found_in_file: bool            # the gate result
  semantics_lost: [str]          # "channel swizzle outColorG", "reverse-invert", "Raw colorspace"

DroppedMapFact:
  material: str; attr: str; slot: Optional[str]
  terminal: str; terminal_type: str    # e.g. "mcpTex_noise1", "noise"
  via: [str]                           # intermediates, e.g. ["bump2d"]
  meshes: [str]                        # exported meshes wearing this material
```

### 1.3 `maya_apply_texture_recipe` — authoring-time honesty

The three procedural recipes (`noise_bump`, `ramp_gradient`, `layered_mask`) append one warning:
*"this recipe builds a procedural network that Maya's FBX exporter silently drops — export_fbx
reports it in dropped_maps; use file textures for anything that must survive export."* (Phase 2
extends the text to name `maya_bake_textures` once the tool exists — a phase-1 warning must not
recommend a tool that is not there yet.) The result already declares `warnings`; verify the MCP wrapper forwards it
(the #757 audit rule: a wrapper without the field over a handler that stops being silent must
grow the field). The loss is now announced at authoring, at export, and in the bytes.

### 1.4 The scene-side claim — `maya_plugin/handlers/texclaim.py`

ONE walker for both export and (phase 2) bake — never two. Split the repo's usual way: pure
classification (fake-cmds-testable) + one cmds-touching enumerator,
**`material_claims(cmds, meshes) -> [claim]`**, called in `export_fbx` beside
`_scene_shape_aliases` on the identical node expansion.

- **`AUTHORED_ATTRS`** — DERIVED at import time from `pbr.SLOTS` ∪ `material.SHADER_SLOTS`
  values (never a copied constant, so a new slot cannot silently fall out of the walk).
  Today's union: baseColor, emissionColor, metalness, specularRoughness, normalCamera, color,
  eccentricity.
- **`PASS_THROUGH_TYPES = ("bump2d", "reverse")`** — the only intermediates stepped through
  (bump2d via `.bumpValue`, reverse via `.input*`); `place2dTexture` is placement, ignored.
- Walk: shape → `listSets(type=1)` → every SG (per-face gives several) → `sg.surfaceShader`
  source → shader × `AUTHORED_ATTRS` → upstream `listConnections` through pass-throughs,
  traversing ALL upstream branches, depth cap 8 with cycle guard.
- Classification per slot: **`"file"` only when the entire terminal set is `file` nodes** (± the
  recognized intermediates) — recording basename, source plug (swizzle), reverse-on-path,
  `colorSpace == "Raw"`, and on-disk existence. **Any non-file contributor anywhere upstream =
  `"procedural"`** — a layeredTexture mixing two files is procedural (the MIX is what the
  exporter loses); no whitelist of known procedural types, not-a-file IS the classification.
  Depth-cap/cycle → procedural with `terminal_type: "unresolved(depth)"` — conservative toward
  reporting loss.
- Node names are never matched (naming is inconsistent: `mcpTex_*` vs `<material>_<slot>_*`);
  only topology and nodeType. Dedupe one claim per (shader, attr); a file node shared across
  slots (assign_pbr's dedupe) claims per-slot at zero cost since the byte check is by basename.
- Claims scope to exported meshes only, like shapes and clips.

### 1.5 The byte gate

**fbxbytes.py** gains Texture and Video record parsing: uid → `{name (via _clean), filename
(FileName/RelativeFilename child records, both kept raw)}`, plus **`texture_facts(facts)`**
mirroring `skin_facts`/`shape_facts`/`anim_facts` with the same `unavailable_reason` discipline.
No connection resolution and no Material record parsing — the comparison needs names and
basenames only (attribution to materials comes from the scene claim, which the report already
carries). The parser is written TDD-first against the **committed drifter FBX** (1 Texture /
1 Video, known basename), converting the record-layout unknown into a measurement before any
product code trusts it.

**`export.texture_violations(tfacts, claims, require_baked) -> (violations, warnings)`** — pure,
table-testable, composed beside the other violation lists. Comparison: **case-insensitive image
basename** (Windows), claim basename vs `os.path.basename` of each record filename — never node
names, never exact counts (dedupe and extras make counts model-dependent; the extras-tolerated
precedent holds). The matrix:

| Condition | default | `require_baked_textures=true` |
|---|---|---|
| File claim (`on_disk=true`) absent from the file's Texture AND Video records | **VIOLATION** | **VIOLATION** |
| File claim with `on_disk=false` absent from the records | warning ("image missing on disk at export time; survival unmeasured — probe P5") | warning |
| Procedural claim exists | warning + `dropped_maps` entry | **pre-write refusal** (§1.1) |
| File claim survives but `semantics_lost` non-empty | warning | warning |
| Record no walked claim explains (`unclaimed_records`) | warning | warning |
| A procedural terminal's node name appears among record names | warning ("the drop model is stale — re-measure #714") | warning |
| Pattern-token path claim (`<udim>` etc.) with no prefix-matching record | warning | warning |

Rationale for the asymmetry: a missing on-disk **file** claim is a loss class never observed
(measured: file-backed always survives), so refusing catches an exporter regression loudly and
breaks no one. A **procedural** claim is the known, documented behavior golem-class consumers
rely on — warn by default, refuse only on demand. `semantics_lost` never refuses even under
strict (the image ships; the consumer rewires channels — refusing would block assign_pbr's own
mask workflow). The missing-on-disk and UDIM rows stay warnings until their probes measure the
exporter's actual behavior; tighten in a follow-up only on evidence.

Violations feed the existing refusal flow untouched: temp `.part.fbx` unlinked, `path` never
written, hint gains a composed `texture_hint`.

### 1.6 Phase-1 tests and gate

- **Headless:** texclaim classification over fake-cmds graphs (file direct, file→bump2d,
  file→reverse, noise→bump2d, ramp, layeredTexture-with-inner-file → procedural, shared file
  node, per-face multi-SG, depth-cap cycle); `texture_violations` table-driven over every matrix
  row in both flag states (including the file-claim-absent row real exports cannot produce —
  exactly why it must be unit-tested); fbxbytes Texture/Video parsing pinned against the
  committed drifter FBX; schema/wrapper red-green tests for `textures` + `warnings` (#757
  pattern).
- **mayapy** (export-then-read-bytes pattern): assign_pbr scene with hand-rolled deterministic
  PNGs → all `found_in_file` true, swizzle/invert/Raw variants populate `semantics_lost`, run as
  BOTH selected and whole-scene exports (whole-scene material carriage gets its own measurement,
  not an assumption); noise_bump scene → default passes with named `dropped_maps`,
  `require_baked_textures=true` refuses pre-write with `path` untouched; hand-wired file texture
  on a non-authored attr → `unclaimed_records` warning, no violation; UDIM path → measure and
  pin.
- **Live gate:** extend `evals/drifter_live.py`'s texture-facts section from "finding, not
  gated" to asserting the product's `textures` block agrees with the eval's own independent
  generic-records walker (the #718 cross-check shape), and that the noise_bump drop is named in
  `dropped_maps`. Report measured record counts, basename hits, dropped names.

## 2. The probes (run under phase 1; they gate phase 2)

Committed as `evals/bake_probe_714.py`, standalone, NOT part of any suite; verdicts recorded on
the ticket and in memory. No probe outcome can sink phase 1.

| # | Question | Decides |
|---|---|---|
| P1 | Does `convertSolidTx` produce a file under maya.standalone? | Where phase-2 bake-correctness tests live (mayapy vs live-only). The tool ships either way — production runs in real Maya. |
| P2 | Bake a recipe `noise` (created with NO place2dTexture) through (a) clean 0..1 UVs, (b) primitive box-projection UVs (golem-class), (c) a UV-less mesh; A/B the bake against a `render_scene` render. | **The phase-2 GO/NO-GO** (usable bakes on golem-class UVs), the no-UV refusal's measured error text, and whether shared materials bake mesh-independently (2D sampling) or per-mesh (3D) — which picks §3.4's shared-material rule. |
| P3 | What PNG does convertSolidTx write (bit depth, color type)? And: bake the pre-bump scalar as a height map — usable? | Whether the `uniform_image` pixel check ships (minimal single-format reader) or stays null; the bump-as-height story. |
| P4 | Export a `file → bump2d(bumpInterp=0) → normalCamera` material; does the HEIGHT path survive like assign_pbr's measured normal (bumpInterp=1) path? | Whether baked bump slots survive; if not, the bake tool refuses `normal` slots ("bake cannot make this survive") and the byte gate would refuse the missing basename anyway — no silent regression possible. |
| P5 | What does the exporter write for a file node whose image is missing on disk? | Tightening (or keeping) the §1.5 missing-on-disk warning row. |

**GO/NO-GO:** phase 2 proceeds iff P2 yields usable bakes on box-projection UVs. On NO-GO, #714
closes on phase 1 + banked probe verdicts, and a new ticket carries the measurements to Tier-0.

## 3. Phase 2 — `maya_bake_textures` (evidence-gated)

Baking is a scene edit, not an export option. New tool, handler
`maya_plugin/handlers/texbake.py`, sharing `texclaim.py`. The persistent rewire means post-bake
viewport and renders ARE the shipped pixels; the builder re-judges the actual artifact before
export — the only shape that closes the judged-render-vs-shipped-file divergence instead of
managing it.

### 3.1 Params

- `meshes: List[str]` — required, non-empty; missing names refuse with the scene-graph hint.
- `out_dir: str` — required, absolute, must already exist (export_fbx's "does not make
  directories" stance). No default: a guessed location is how bake files get lost from
  deliveries.
- `resolution: int = 1024` — one of {256, 512, 1024, 2048, 4096}.
- `slots: Optional[List[str]] = None` — assign_pbr slot vocabulary filter; `None` = every
  procedural-carrying slot. Unknown slot refuses.

No `dry_run` (export's default mode is the detector), no `overwrite` flag (part-then-replace
makes overwrite safe).

### 3.2 Mechanics

- Engine: `convertSolidTx(<terminal plug>, <mesh>, antiAlias=True, resolutionX/Y=R,
  fileFormat="png", fileImageName=<part path>)`, sampling the mesh's current UV set.
- Per-slot wiring (the measured-surviving shapes): color-class → RGB PNG, `file.outColor →
  attr`, sRGB; scalar → `file.outColorR → attr`, Raw + ignoreColorSpaceFileRules (assign_pbr's
  data-not-colour trap); normal-via-bump2d → bake the bump INPUT as height, KEEP the original
  bump2d (bumpDepth preserved, bumpInterp=0), rewire only `.bumpValue` to `file.outAlpha`, Raw —
  contingent on P4. Every new file node gets a place2dTexture via the existing pbr helper,
  named `<material>_<slot>_baked` (assign_pbr's convention).
- Files: `<out_dir>/<material>_<slot>_baked.png`, uniquified on collision; written `.part.png`
  first, verified (exists, size floor, non-uniform pixels per P3), `os.replace` at commit.
- **Two-phase all-or-nothing:** phase A bakes every requested slot to `.part` files and verifies
  — ZERO scene mutation; phase B (only if all verified) performs all rewires, replaces all
  files, deletes replaced chains. Phase-A failure sweeps `.part` files and raises naming the
  failed slot; the scene is in exactly one of two states. `session.auto_checkpoint
  ("bake_textures")` runs before phase B (the repo's destructive-op convention), and a phase-B
  failure's hint names the checkpoint and `maya_undo`.
- Deletion policy: delete only nodes whose every downstream connection leads into the replaced
  plug (computed pre-bake); anything feeding elsewhere survives with a warning
  (apply_texture_recipe's zero-orphans value, inverted).
- **Judgment affordance:** the result carries `capture_before`/`capture_after` viewport-capture
  paths (skipped null in batch mode) so an unjudged bake is a named gap, not a silent one. The
  real quality gate is the builder re-judging renders — the live gate encodes it (§3.5).
- Postcondition: re-run the texclaim walk on touched materials; any baked slot still classifying
  procedural RAISES (a postcondition bug, never a warning).

### 3.3 Refusals (pre-mutation) and warnings

Refuse: mesh with zero UV coordinates (hint: `maya_uv_atlas` creates UVs — and phase 2 adds the
authoring-time warning in `apply_texture_recipe` when the target mesh has no UVs); `normalCamera`
driven procedurally WITHOUT a bump2d intermediate (a tangent-space normal bake is Tier-0's
sibling); unrecognized terminal chains (refusal over guessing); UDIM/sequence paths.

Warn (proceed): material also worn by meshes outside the request (the persistent rewire changes
their look too — visible in the next render, which is the point); UV bbox outside [0,1]±ε;
uniform-image bake.

### 3.4 Shared materials — decided by P2

If P2 measures mesh-independent sampling (2D): a material shared by several requested meshes
bakes ONCE, warning names every wearer. If P2 measures mesh-dependent sampling (3D/projection):
refuse shared materials within the request (ambiguity is not guessed away; hint: bake per mesh
or duplicate the material). The spec deliberately encodes both arms; the probe picks.

### 3.5 Phase-2 tests and gate

Headless: texbake validation/refusal paths, all-or-nothing sweep on forced mid-batch failure,
`BakeTexturesResult` schema red-green. mayapy (conditional on P1; else live): per-recipe cube →
bake → export → bytes carry every baked basename and zero pre-bake procedural names;
`require_baked_textures=true` passes post-bake. Live gate `evals/texbake_live.py`: a mesh
carrying all three procedural recipes + one file texture; render BEFORE; bake; render AFTER and
judge both (implementer AND controller — the humanoid_live dual-judgment precedent); export;
independent byte walk agrees with the `textures` block; measured numbers throughout. Plus a
drifter_live re-run for regression. Deploy stamp + restart-required note, as every plugin change.

## 4. Sequencing and cross-cutting

1. **#757 first.** Its branch touched `src/maya_mcp/schemas.py`/`server.py` — the same files
   §1.2 must edit. RESOLVED at spec time: 7dff350 was merged to main on 2026-08-25 (it is this
   spec commit's parent), so #714 implementation builds directly on its warnings-forwarding
   pattern.
2. Phase 1 lands as one branch (walker → fbxbytes → violations → result/schema → tests → live
   gate), probes run alongside; ticket gets the probe verdict table; GO/NO-GO decision recorded
   on the ticket before phase 2 starts.
3. `docs/protocol.md` updated with each phase (export_fbx param/result; the bake tool's
   contract).
4. The roadmap's Tier-0 "bake AO/curvature into the atlas" item is a SIBLING: texclaim, the
   part-file discipline, and the Texture/Video byte gate are all reusable by it; nothing here
   assumes the only bake source is a shading network.

## 5. Non-goals

- No baking inside `export_fbx`, ever; no auto-bake under `require_baked_textures`.
- No flip of `FBXExportEmbeddedTextures` or `FBXExportInputConnections` (pinned false on
  measured grounds); no copying of images next to the FBX (delivery packaging reads
  `textures.file_maps` and does its own copying).
- No preservation of FBX-inexpressible semantics (swizzle/Raw/invert) — reported, never gated,
  never "fixed"; no re-baking of already-file-backed slots.
- No Material-record parsing or connection resolution in fbxbytes (basenames are the measured
  invariant); no standalone material-report tool; no UV authoring or overlap detection inside
  the bake tool (uv_atlas owns UVs; the after-render judgment owns quality).
- No tangent-space normal / AO / curvature baking (Tier-0's sibling); no UDIM bake support.
- No retroactive re-gating or strictness flip of shipped deliveries; `evals/golem_rerun_665/`
  artifacts are never regenerated by this ticket (`out_v4/` is another agent's, untouchable).

## 6. Unmeasured-fact register (consolidated)

| Fact | Used by | Fallback if it disappoints |
|---|---|---|
| Texture/Video record layout | §1.5 parser | TDD-pinned against the committed drifter FBX first; layout variance → `unavailable_reason` + warning, never a silent pass or bogus refusal |
| Whole-scene material carriage | §1.6 mayapy | its own measurement; the claim walk already scopes per-branch, the test pins whichever truth emerges |
| UDIM tokens in record filenames | §1.5 matrix row | warn-only until measured; tighten later |
| Missing-on-disk image behavior (P5) | §1.5 matrix row | warn-only until measured |
| convertSolidTx under standalone (P1) | test placement only | bake tests move to the live gate |
| Noise/UV bake fidelity (P2) | phase-2 GO/NO-GO, §3.4 | NO-GO → phase 1 ships alone, new ticket carries the measurements |
| Baked PNG format (P3) | `uniform_image` check | field stays null; size floor + render judgment carry it |
| Height-path bump survival (P4) | §3.2 normal wiring | bake refuses `normal` slots; byte gate refuses the missing basename anyway |
