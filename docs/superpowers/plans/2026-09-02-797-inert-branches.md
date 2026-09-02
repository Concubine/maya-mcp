# #797 — value-level inert params: the branch table

Redmine #797. Successor to #764 (refuse unknown keys) and #767 (every command
declares its key set). This is the level below: a key the handler KNOWS,
accepts, validates, and then never consumes on some branch selected by
another param's value or by scene state.

Derived 2026-09-02 by five read-only first-pass sweeps (one per handler
group) and three adversarial refute passes over their tables, with headless
probes against the repo's own fakes where a claim could be executed. Rows
the refute pass REFUTED are listed at the end so they are not re-found.
Scratch probes (not committed) lived in the session scratchpad as
`probe_797*.py`, `p797_*.py`, `probe_797_rigmod_pass2.py`.

## The rule the fix implements

A param the caller PASSED that has no effect on the branch the call takes
is REFUSED before the checkpoint, with a message naming the param, the
branch, and why (the `subdivisions`-on-a-platonic wording in
`modeling.resolve_subdivisions`). Two exceptions, each a WARNING naming the
param instead: the param is required by the schema (refusing would refuse
the command), or the wrapper cannot stop sending it. Never a silent echo of
an unused value: a result field that reports a requested value the branch
did not apply is a false claim and is either nulled or replaced by the
applied value.

"Passed" means `is not None` (or key present, for nested dicts). Wherever
the MCP wrapper in `src/maya_mcp/server.py` fills a non-None default the
handler already applies, that default becomes `None` so the handler sees
only what the caller said. Wrappers known to do this: `maya_array`
(`count=2`, `angle=360.0`), `maya_transform` (`relative=True`),
`maya_assemble` (`pivot="center"`), `maya_uv_atlas` (`project="box"`,
`normalize=True`), `maya_bake_mesh_maps` (`curvature_radius=0.1`,
`curvature_output="convex"`), `maya_apply_texture_recipe` (`params={}`),
`maya_render_scene`/`maya_render_sheet` (`samples=3`/`2`),
`maya_capture_viewport` (`frame_all=True`, `wireframe_overlay=True`),
`maya_restore_checkpoint` (`""` for the absent one of id/path).

One shared helper carries the wording so the contract test can recognise
it: `dispatcher.refuse_inert(command, param, branch, why, hint)` →
`HandlerError("<command> does not use '<param>' <branch>: <why>", hint)`.

## Tier 1 — REFUSE (the class; caller passed it, branch drops it)

| # | command | param | branch | notes for the fix |
|---|---|---|---|---|
| 1 | create_primitive, assemble parts[] | `divisions` | kind octahedron/icosahedron | `resolve_subdivisions`: refuse when `divisions is not None` and `not axes_spec`; mirror the `subdivisions` refusal wording. Wrapper already sends None. |
| 2 | array | `count`, `center`, `angle`, `offset`, `step_rotate`, `step_scale` | mode=mirror | Nothing on the wrong mode is even validated (probe: `center=[1,2]`, `angle=720`, `offset="garbage"` all pass). Wrapper `count`/`angle` defaults → None; `_radial` keeps its own 360 default; `resolve_count(None)` refuses "missing". `tests/test_array.py:477-483 test_count_is_ignored` flips to a refusal test. |
| 3 | array | `pivot`, `offset`, `step_rotate`, `step_scale` | mode=radial | same |
| 4 | array | `axis`, `center`, `angle`, `pivot` | mode=linear | same |
| 5 | array | `offset=[0,0,0]` | mode=linear | value-level: every copy lands on the source; radial already refuses `angle=0` (`arraymath.py:93-97`). |
| 6 | assemble | `pivot` in {origin, keep} | combine=false, or a single-part chunk | `center` is observably honoured (bbox centre of a translated primitive), so only origin/keep refuse. Wrapper `pivot` → None; key on presence. Schema text at server.py:1737-1746 already says single-part gets no mode. |
| 7 | assemble | `parts[i].patch` | atlas=null | today validated against a phantom 4x4 grid (`assemble.py:291-292`), so `patch: 16` is refused naming a grid that does not exist. |
| 8 | assemble, uv_atlas | `project` in {keep, planar} | `world_scale` set | DESTRUCTIVE today: `uvatlas.py:108` box-autoprojects an authored layout. `box` is what world mode does — never refuse it. Wrapper `project` → None. uv_atlas's result keeps `projection` (the applied value); add the `warnings` field `UvAtlasResult` lacks (protocol.md:420 promises it). |
| 9 | assemble | `atlas.normalize` explicit `true` | `world_scale` set | key on key presence (`assemble.py:231` fills True). uv_atlas's own `normalize` is REFUTED (result reports `normalized: False`, schema says ignored) — only the wrapper default → None there. |
| 10 | uv_atlas | `uv_per_metre` | `world_scale` None | TCP/generator-only key (wrapper never sends it); result echoes it unused (`uvatlas.py:245-247`). Refuse; stop echoing. |
| 11 | bake_mesh_maps | `curvature_radius`, `curvature_output` | "curvature" not in maps | template `meshmaps.py:181-185` (`apply_ao` without "ao"). Wrapper defaults → None; `tests/test_meshmaps.py:451` pins the fill and changes. |
| 12 | apply_texture_recipe | `params` non-empty | recipe ramp_gradient / layered_mask | builders never read it; schema says "take no params yet". Wrapper sends `{}` always → key on non-empty. |
| 13 | apply_texture_recipe | nested unknown keys | noise_bump reads {scale, depth}; file_texture {file_path} | per-recipe `_KEYS` + `require_known_keys` (#767-class nested gap). Also refuse a nonexistent `file_path` the way `pbr.py:183-199` does. |
| 14 | create_curve_form | `resolution.around` | kind=sweep AND `profile_sides` given | refuse in `_validate_sweep` BEFORE `_validate_resolution` fills it (`curveform_math.py:427`, `:136-175`); `predicted_faces` (`:540-541`) must bill `sides`, and `tests/test_curveform_math.py:187-195` changes with it. |
| 15 | sculpt_ops | `center` | `vertex_id` given (soft_move, inflate_region) | `sculpt.py:56-64` returns before `center` is read; schema documents either/or. |
| 16 | sculpt_ops | unknown/foreign keys on the 8 pre-cage ops | per op | per-op `_KEYS` like the four cage ops (`:288,:368,:494,:556`). Read sets: soft_move {vertex_id\|center, radius, falloff, delta}; inflate_region same with `amount`; displace_noise {amp, freq, octaves, soften_angle}; smooth {divisions}; extrude_faces {faces, distance, keep_together}; bevel_edges {edges, segments, width}; crease_edges {edges, amount}; bridge {edges_a, edges_b}. Worst today: displace_noise with center/radius/falloff displaces the WHOLE mesh. |
| 17 | assign_pbr | per-slot map keys outside {path, channel, invert, raw, mip_filter} | any slot | nested `require_known_keys` (probe: `"chanel"` typo → channel r). |
| 18 | setup_lighting | `hdri_path` | preset three_point / single_sun | wrapper default None already. Also refuse a nonexistent file BEFORE the `replace_existing` checkpoint (`lighting.py:191-196`; today no `exists` check anywhere). |
| 19 | setup_lighting | `hdri_path` | preset=environment | contract decision: the schema promises a dome "needing no file" but `lighting.py:203-206` builds an HDRI dome from it. Refuse ("environment takes no hdri_path; use preset hdri"). |
| 20 | capture_viewport | `target` | every angle is "current" | `capture.py:661-662` bypasses `_scene_bbox`, the only existence check, so a typo target succeeds. Refuse when ALL angles are current; on a mixed list `target` IS consumed for the others, so existence-check on every branch and add a per-frame note for the current frame. |
| 21 | render_sheet, preview_clip | `angle="current"` | any | remapped to three_quarter under the original label; no schema promise for these two (render_scene's schema DOES promise the degrade — see Tier 2). preview places its own camera, so current is structurally inapplicable. |
| 22 | pose_ik | `pole` on the start→target line | any chain | the tool's prebend is skipped and the straight-chain warning (`rigging.py:1031-1035`) is SILENCED by the pole's presence; Maya still builds a degenerate constraint. Refuse in `pose_ik` before the checkpoint (`:1189`/`:1237`), NOT in `solve_ik_plan` (cleanclip calls it without a pole). |
| 23 | restore_checkpoint | `checkpoint_id` | `path` also given and id != stem(path) | `session.py:151-159` overwrites the id; wrapper sends `""` for the absent one, so key on both non-empty. |
| 24 | clean_clip | explicit `filter.window` > clip length | scene state | `smooth_track` shrinks the window per sample (`mocapmath.py:570-584`): window 31 ≡ 101 ≡ 29 on a 30-frame clip, identity for n ≤ 4, and the warning still says `window=W`. Refuse an explicit window larger than the clip; the DEFAULT window on n ≤ 4 WARNS "too short to smooth" instead of "smoothed". |
| 25 | retarget_clip | `fps` != the file's rate | .fbx route | keyed range read in the file's unit (`retarget.py:1086-1109`) and `_set_bake_unit` runs after (`:1129`); route never run live (every eval feeds BVH). Refuse until measured; wrapper default None. `start`/`end` fractional → `int(round())` silently: note or integer type. |
| 26 | capture_turntable | `target=""` | value | `capture.py:373-374` treats it as "no target"; wrapper has no `min_length`. Refuse + `min_length=1`. |
| 27 | deform | `delete_history_after=true` with no `translate`/`rotate` | deformer=lattice | result is `{deformer_nodes: [], baked: true, warnings: [], max_displacement: 0.0}` — nothing happened. Refuse that combination; fix the lattice exemption in `_inert_warnings` (`sculpt.py:896`) to apply only while the lattice survives. lattice+xform+bake stays legal. |
| 28 | etch_text | `font=""` | value | `etch.py:240 or DEFAULT` → "Arial" silently; MCP-reachable (server.py:1863 has no min_length). Drop the `or DEFAULT` idiom at `:236-240` and add `min_length=1`. |

## Tier 2 — WARN or REPORT (required param, wrapper always sends, or documented)

| # | command | param | branch | treatment |
|---|---|---|---|---|
| 29 | render_scene, render_sheet, preview_clip | `samples` | renderer=hw2 | result echoes the requested value (`render.py:1070`) — a false claim. `samples: null` under hw2 (`RenderResult.samples` → Optional) + one warning; the wrapper always sends it. `preview_clip` accepts `samples` that its wrapper never sends and its protocol row omits: drop it from `PREVIEW_CLIP_KEYS`. |
| 30 | render_scene | `angles` containing "current" | always | schema PROMISES the degrade (server.py:487-488): label images and `camera_positions` with the resolved angle (or add `resolved_angle`) + warning. |
| 31 | remesh_retopo | `target_polycount` | polyRetopo unavailable → polyRemesh | param is required; warn naming it like the polyReduce branch (`modeling.py:1066-1069`). |
| 32 | author_physics | `exclude[i]` matching no chunk | root mode | substring filter is deliberately forgiving; warn naming the entry (server.py:2570 promises "every exclusion is warned by name"). |
| 33 | author_physics | `overrides[X].*`, and any body whose parent is X | chunk X SKIPPED (unreadable / zero tris) | `chunk_set`/`by_short` are built pre-skip (`physics.py:306-307`), so a skipped chunk is a valid parent on both the override and DAG paths and a joint is emitted against a body that does not exist. Warn naming the override; exclude skipped chunks from parent resolution. Read-only command, no checkpoint. |
| 34 | assemble | `name` | every part sets `chunk` | required by schema; warn "no part used the base name". |
| 35 | assemble | `parts[i].name` | combine=true, chunk with >1 part | consumed transiently, eaten by polyUnite; warn. |
| 36 | capture_viewport, capture_turntable, compare_to_reference | `resolution` | playblast failed → M3dView fallback | `capture.py:808-835` draws at panel size, no field says so; warn naming the drawn size. |
| 37 | render_scene, render_sheet, preview_clip | `isolate` partial | a shape `hide` refuses for a cause plugwrite cannot classify | `render.py:706-709` continues with nothing appended; warn. |
| 38 | capture_viewport, capture_turntable | `lighting=scene` with no lights; `shadows` under default/flat/wireframe; `buffer=ssao` under wireframe | scene state / shading | warn (VP2 behaviour unmeasured; render_scene already reports `fallback_light`). |
| 39 | clean_clip | `lock_contacts` | a chain plug driven/locked | `cleanclip.py:316` discards setKeyframe's return and `:317-321` claims "locked" unconditionally; read the return like the filter pass (`:203-209`). (Was already in the unticketed backlog.) |
| 40 | create_blendshape | `targets[i]` extra keys | TCP route | handler-level `require_known_keys` on the entry + `extra="forbid"` on `BlendshapeTargetSpec` (schemas.py:705-714). |
| 41 | bake_textures | `slots=[]` | value | refusal exists but omits the slot clause (`texbake.py:294-299`); name it. |
| 42 | clean_clip | default `filter.window` | clip of ≤ 4 frames | see row 24: warn "too short", never "smoothed". |

## Tier 3 — leave, documented or not the class

- transform `relative` with pivot only: pivot is documented as a world-space point; wrapper sends `relative=True` always; pivot-only is a live-used shape (`evals/pivot_live.py:41`, `tests/test_modeling.py:685`).
- execute_python `timeout_s`: the wrapper sends the same value at frame level, which the dispatcher enforces; protocol.md:100-104 tells wire callers. Optionally remove from both `EXECUTE_PYTHON_KEYS` and the wrapper dict together.
- uv_atlas `normalize` under `world_scale`: result reports `normalized: False`, schema says ignored, `tests/test_uvatlas.py:334-338` pins it.
- capture_viewport `wireframe_overlay` under shading=wireframe: the frame IS a wireframe; nothing asked for is missing.
- smooth_weights `joints` naming influences with no held vertex: `smoothed_vertices: 0` reveals it.
- add_corrective reuse branch: the warning names pose, rotation and target. (Adjacent: the record stores the requested rotation, not the reused pose's.)
- pose_skeleton `space`: only "local" is legal; inert by construction.
- apply_delta_mush `pin_border_vertices` on a closed mesh: Maya-inert, not the handler's.
- Wire-only coercions the MCP schema already refuses (render/capture `resolution` non-int or out of range → default/clamp with no result field; get_scene_graph `filter` non-str, `max_objects` out of range; render_sheet `isolate` list; etch `width`/`depth` = 0): worth a handler-side type refusal in the same pass if cheap, but not #797's class.

## Needs a live probe before its row is decided

- combine/assemble `pivot="keep"`: where a fresh `polyUnite` transform's pivot sits (likely origin, making keep ≡ origin). No test or eval exercises `keep`.
- bind_skin `method=heatMap` on an open/non-manifold mesh: does Maya fall back silently (bindMethod is create-only, cannot be queried back)? Diff weight tables vs closestDistance.
- pose_ik degenerate pole: fold sign with vs without the pole on a straight chain (the refusal in row 22 is justified by the silenced warning regardless).
- deform `params.rotate` on sculpt: rotating the sculptor sphere about its centre should be inert; A/B live.
- retarget .fbx `fps`: export a BVH retarget to FBX, re-import at another fps, compare `frames`/`measures` to the source duration (row 25 stays a refusal until this is measured).
- render `samples` under arnold on a cold mtoa load (`defaultArnoldRenderOptions` absent when `render.py:427` writes; created at `:326`): does the write land?
- VP2 shadows / ssao / no-light fallback under the branches in row 38 (warnings are honest without it).

## Refuted by the second pass (do not re-find)

uv_atlas `normalize` under world_scale; capture_viewport `wireframe_overlay` under wireframe; execute_python `timeout_s`; add_corrective reuse branch; transform `relative` with pivot only (documented); smooth_weights zero-row case (result reveals it).

## The contract test

`tests/test_branch_contract.py`, the sibling of `test_param_contract.py`.
A table `BRANCHES = [(command, params_that_select_the_branch_and_pass_the_param, dropped_param, branch_words)]` for every Tier-1 row whose refusal is PURE (fires before `_cmds()`): the test calls the handler headless and asserts a `HandlerError` whose message contains `"does not use"`, the param name, and the branch words — and, as in #767, a handler that reaches Maya before refusing fails the test with an ImportError, which is the proof the refusal runs first. Rows that need the scene (24, 25, 27's lattice, 33) are tested with their module's fakes in their own test files and listed in the table with `scene=True` so the count of covered rows is still asserted. The wrapper-default rows get a second assertion: the wrapper's default for that param is `None` (parsed from server.py's AST the way `_wrapper_sent_keys` does).

## Order of work

1. `dispatcher.refuse_inert` + `tests/test_branch_contract.py` skeleton with rows 1-28 (RED).
2. Wrapper defaults → None (one commit; the wrapper drift test keeps the key sets honest).
3. Handlers, one file at a time, each with its TDD tests; docs/protocol.md rows as they change.
4. Tier 2 warnings/result fields; schemas (`RenderResult.samples` Optional, `UvAtlasResult.warnings`).
5. Live probes on a repo-cwd 9878 (the list above), then the gate `evals/inert_branches_live.py`: at minimum rows 1, 8, 20, 22, 27 over the wire, the arnold/hw2 `samples` truth, and whatever the probes settle.
6. Adversarial review of the diff; suite; deploy; ticket.
