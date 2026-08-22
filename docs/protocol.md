# maya-mcp wire protocol (v1)

TCP, loopback by default (`127.0.0.1:9877`). One frame = `uint32` big-endian
body length followed by a UTF-8 JSON object. Max frame size: 64 MB.

The single source of truth is [`maya_plugin/protocol.py`](../maya_plugin/protocol.py),
imported by both the MCP server and the Maya plugin.

## Frames

Request (server → plugin):

```jsonc
{ "v": 1, "id": "uuid-hex", "cmd": "capture_viewport", "params": { }, "timeout_s": 30,
  "token": "..." }          // token only when MAYA_MCP_TOKEN is set
```

Success (plugin → server):

```jsonc
{ "v": 1, "id": "uuid-hex", "status": "ok", "result": { }, "elapsed_ms": 412 }
```

Failure — tracebacks are sacred, never truncated:

```jsonc
{ "v": 1, "id": "uuid-hex", "status": "error",
  "error": { "type": "RuntimeError", "message": "...",
             "maya_traceback": "full traceback text",   // unexpected exceptions only
             "hint": "actionable next step when known" } }
```

## Rules

- **One in-flight request at a time.** The client serializes; the plugin's
  dispatcher runs one command at a time on Maya's main thread.
- **Timeouts.** The plugin enforces `timeout_s` per command (max 600 s). On
  timeout it replies with `TimeoutError` and flags the session busy until the
  straggling command finishes; meanwhile new requests get `BusyError`. A late
  result is dropped, never delivered to a different request id.
- **Reconnect.** A client that times out or hits a transport error drops its
  connection and opens a fresh one on the next request.
- **Version.** Requests with `v != 1` are rejected with `ProtocolVersionError`.
- **Auth.** With `MAYA_MCP_TOKEN` set on the plugin, every frame must carry a
  matching `token` (constant-time comparison) or it gets `AuthError` — and the
  connection is closed after the response (no free retry loop for guessing).
  The plugin refuses to bind non-loopback hosts unless `MAYA_MCP_BIND_ANY=1`
  AND a token are set.
- **Inbound cap.** The plugin accepts request frames up to 4 MB (requests never
  carry images; the 64 MB protocol cap applies to responses only). Once a
  frame starts arriving, its remainder must land within 30 s or the connection
  is dropped — idle connections between requests block indefinitely and are fine.
- **Undo.** Every mutating command runs inside one `undoInfo` chunk = one undo
  step. Read-only perception commands (`capture_viewport`) suppress undo
  recording (`stateWithoutFlush`) so their internal churn never lands on the
  undo queue — undo after a capture reverts the last real edit.

## Error types

| type | meaning |
|---|---|
| `ProtocolVersionError` | version mismatch between server and plugin |
| `AuthError` | missing/invalid token |
| `UnknownCommandError` | cmd not registered; hint lists available commands |
| `BusyError` | a straggling command still occupies Maya's main thread |
| `TimeoutError` | command exceeded `timeout_s`; session busy until it finishes |
| `HandlerError` | controlled handler failure with an actionable hint |
| anything else | unexpected exception; `maya_traceback` carries the full story |

## Commands (M0)

| cmd | params | result |
|---|---|---|
| `ping` | `{}` | `{ pong, maya, plugin: {package_dir, digest, stamp, loaded_digest, loaded_stamp, imported_at, restart_required}, process: {pid, host, port, started_at, uptime_s, scene} }` |
| `execute_python` | `{ code, timeout_s?, risky? }` | `{ stdout, stderr, result_repr, traceback, namespace_keys, checkpoint? }` |
| `reset_namespace` | `{}` | `{ reset: true }` |
| `get_scene_graph` | `{ filter?, max_objects?, cursor? }` | `{ objects: [...], total, cursor }` |
| `capture_viewport` | `{ angles?, shading?, wireframe_overlay?, buffer?, isolate?, target?, frame_all?, resolution? }` | `{ images: [{angle, png_b64}], camera_positions: [...] }` |

`ping` answers two questions a caller cannot answer for itself: `plugin` says
which *code* is live (feed it to `version.compare`), `process` says which
*process* is answering — a port is not an identity, and a Maya that lost the
bind race is indistinguishable from yours without a pid (#648). A bind failure
raises `PortInUseError` rather than leaving a Maya running with no listener.

**`plugin` carries two identities, and the difference between them is a
finding** (#604). `digest`/`stamp` describe the files **on disk right now**;
`loaded_digest`/`loaded_stamp` describe what this session **imported**, captured
once at plugin load. A running Maya holds the modules it imported at startup —
`install.py` rewrites the disk and reloads nothing — so in the window between a
deploy and a restart the two diverge, and the disk names exactly the code that
is *not* answering. Judging by disk is how the old handshake read CLEAN against
a stale session while a caller measured the old handlers and attributed the
results to the new branch; the same window made two fresh #640 fixes read as
regressions. `version.compare` therefore judges by `loaded_digest` (falling
back to `digest` for pre-#604 plugins) and has a distinct verdict for the
window: *deployed but not restarted*, whose advice is restart — not the
redeploy that has already run and cannot help. `restart_required` is the same
divergence as a bare boolean, for humans reading a raw ping. Gated live by
`evals/staleness_live.py`, which walks the actual window on a real Maya.

## Commands (M1)

Session safety:

| cmd | params | result |
|---|---|---|
| `checkpoint` | `{ label }` | `{ checkpoint_id, path }` |
| `restore_checkpoint` | `{ checkpoint_id \| path }` | `{ restored, path, pre_restore_checkpoint, pre_restore_path }` |
| `undo` | `{ steps? }` | `{ undone, requested }` |
| `redo` | `{ steps? }` | `{ redone, requested }` |
| `new_scene` | `{ confirm, linear_unit? }` | `{ new_scene: true, pre_checkpoint, pre_checkpoint_path, units }` |
| `open_scene` | `{ path, confirm? }` | `{ opened, pre_checkpoint, pre_checkpoint_path }` |
| `save_scene` | `{ path? }` | `{ path }` |

Checkpoints go to `<dir of the open scene>/checkpoints/`, so a `checkpoint_id`
(`NNN_label`) is unique only inside one directory — and `new_scene`,
`open_scene` and `restore_checkpoint` all change which directory that is. Ids
issued during the session are resolved against where they were actually
written, and every id comes back with its `path`; pass `path` instead of
`checkpoint_id` for an id from an earlier session (#649).

Scene ops:

| cmd | params | result |
|---|---|---|
| `create_primitive` | `{ kind, name, translate?, rotate?, scale?, divisions? }` | `{ name, warnings }` |
| `duplicate` | `{ name, new_name, translate?, rotate?, scale? }` | `{ name, warnings }` |
| `transform` | `{ names, translate?, rotate?, scale?, relative? }` | `{ objects: [...], warnings }` |
| `group` | `{ names, group_name }` | `{ name, warnings }` |
| `parent` | `{ child, parent }` | `{ name, warnings }` |
| `rename` | `{ name, new_name }` | `{ name, warnings }` |
| `delete_objects` | `{ names }` | `{ deleted: [...], warnings }` |

Modeling and sculpting:

| cmd | params | result |
|---|---|---|
| `boolean_op` | `{ a, b, op, new_name }` | `{ name, tris, watertight, parent, pivot, uv_bounds, warnings, carved_text? }` |
| `etch_text` | `{ mesh, text, face, width?, depth?, font?, mirror?, rotate_deg?, new_name? }` | `{ name, tris, watertight, parent, pivot, uv_bounds, warnings, carved_text }` |
| `sculpt_ops` | `{ mesh, ops: [...] }` | `{ applied, ops: [...], tris, warnings, checkpoint_id? }` |
| `deform` | `{ mesh, deformer, params?, delete_history_after? }` | `{ deformer_nodes: [...], baked, warnings, max_displacement }` |
| `remesh_retopo` | `{ mesh, target_polycount, keep_original? }` | `{ name, tris, method, warnings }` |
| `mesh_cleanup` | `{ mesh, merge_verts_threshold?, delete_history?, freeze_transforms?, conform_normals? }` | `{ name, before, after, warnings }` |

A boolean builds a **new object**, so everything that is not vertices has to be carried across deliberately (#638). `boolean_op` and `etch_text` take three things off `a` before it is consumed and put them back on the result, reporting each one:

* **`parent`** — the result goes back under `a`'s parent, so cutting a socket into a rigged chunk does not drop it out of the hierarchy. The reparent happens *before* construction history is deleted, because that delete garbage-collects the consumed operands and takes an empty parent group with them. If the parent carries a scale or rotation, the result would inherit its inverse as a compensating transform — the node state the export gate refuses (#629) — so that is frozen into the vertices instead, with a warning saying so.
* **`pivot`** — `a`'s world-space pivot, not the new mesh's bounding-box centre. This is what makes `boolean_op` safe to use after `transform`'s `pivot` or `assemble`'s `pivots` (#603).
* **`uv_bounds`** — `[u_min, v_min, u_max, v_max]` of the result. `polyCBoolOp` keeps **each operand's own** UV layout, so the faces the cutter contributes arrive carrying the cutter's UVs: on an atlas-packed chunk cut with a default-UV cutter, the new face samples the whole atlas instead of its own patch, and nothing looks wrong until the material goes on. `b`'s UVs are folded into `a`'s bounds before the boolean runs (folding first, because once merged there is no reliable way to tell the two operands' UVs apart). `uv_bounds` is `null` when the result has no UVs at all.

**`new_name` may be `a`'s or `b`'s own name** (#640). Both operands are consumed, so "cut a socket into X and have the result still be called X" is the natural request — and it used to be inexpressible, returning `X_001`, because the name was reserved while Maya still held it: `polyCBoolOp` leaves both operands as emptied transforms until the construction-history delete reaps them. The result is therefore created under a staged name and claims the requested one immediately after that delete, which is the only moment it is free. A name held by an object this call does **not** consume is never stolen: the staged name stays and `warnings` says which object holds it.

`deform`'s `deformer` is one of `bend`, `squash`, `twist`, `flare`, `sine`, `wave` (all `cmds.nonLinear` types), plus `sculpt` and `lattice`. `flare`, `sine` and `wave` are new in M2.4. Each type whitelists its own `params` keys (they land as attributes on the deformer node under exactly those names); `wave` is the one exception with no `lowBound`/`highBound` at all, since it bounds radially via `minRadius`/`maxRadius` instead.

**Angle params are degrees** (`bend`'s `curvature`, `twist`'s `startAngle`/`endAngle`). Those attributes are angle-typed, and `cmds.setAttr` reads an angle in whatever unit the scene's UI is set to — so `deform` converts from degrees into that unit and the number means the same thing in every scene. `curvature: 0.35` is a third of a degree, which is what made `bend` look inert (#636); a visible hunch is 20–60.

`max_displacement` is how far the furthest vertex actually moved, in scene units, measured from the vertices before and after (not from the bounding box, which over-reports rotated meshes). When it falls below 1% of the mesh's own bounding-box diagonal, `warnings` carries one line naming the measurement and the usual reason that deformer type ends up inert. `lattice` is exempt: a freshly built lattice deforms nothing until its points are moved, so `max_displacement: 0.0` is the correct result there.

Viewport and camera:

| cmd | params | result |
|---|---|---|
| `set_viewport` | `{ show_grid?, show_light_icons?, show_camera_icons?, show_locators?, show_manipulators?, show_texture_placements?, wireframe_on_shaded?, display_lights? }` | `{ panel, show_grid, ..., camera }` |
| `set_camera` | `{ camera?, position?, look_at?, focal_length?, set_active? }` | `{ name, position, rotation, warnings }` |

## Commands (M2)

Perception:

| cmd | params | result |
|---|---|---|
| `get_object_info` | `{ name, include? }` | `{ name, transform?, mesh_stats?, uvs?, shading?, history? }` |
| `capture_turntable` | `{ target?, n_frames?, resolution?, shading?, lighting?, shadows? }` | `{ images: [{index, azimuth, png_b64}], n_frames }` |

Lighting and materials:

| cmd | params | result |
|---|---|---|
| `setup_lighting` | `{ preset, intensity?, hdri_path?, replace_existing? }` | `{ preset, lights: [...], removed: [...], checkpoint_id?, warnings }` |
| `assign_material` | `{ mesh, shader?, params?, name? }` | `{ mesh, material, shading_group, shader, warnings }` |
| `apply_texture_recipe` | `{ mesh, recipe, params?, slot? }` | `{ mesh, recipe, slot, nodes: [...], warnings }` |

## Commands (M2.2)

| cmd | params | result |
|---|---|---|
| `render_scene` | `{ angles?, renderer?, resolution?, isolate?, target?, zoom?, relight?, samples?, fallback_light? }` | `{ images: [{angle, png_b64}], camera_positions: [...], renderer, samples, fallback_light }` |

`render_scene` is the second eye. `capture_viewport` reads the VP2 viewport, so
it is fast, needs a mapped window, and draws transmission as plain transparency -
a gem and a plastic block look alike. `render_scene` goes through the render
pipeline: seconds per frame, no window required (it works on an agent-launched
Maya, where every playblast comes back fully transparent), and under `arnold` it
refracts for real.

Two details worth knowing before calling it:

- `isolate` here **hides** the non-targets rather than isolating a panel, since
  panel isolation is invisible to a renderer. Visibility is restored afterwards,
  along with the render globals the call had to change.
- The MCP tool wrapping this command reports `opaque_px`, `total_px` and
  `distinct_colors` per frame, and errors when every frame is blank. A render of
  an empty or unlit scene is a valid PNG with a success status, so blankness has
  to be measured rather than assumed away.

| cmd | params | result |
|---|---|---|
| `render_sheet` | `{ subjects, angle?, renderer?, resolution?, isolate?, samples? }` | `{ images: [{angle, label, png_b64}], camera_positions: [...], renderer, samples, fallback_light, warnings }` |

`render_sheet` is one frame per subject sharing one renderer, camera and set of
render globals; the server composites the cells into a single sheet image. It is
`render_scene`'s loop with a different list, so they share the same
implementation.

**Its cells are siblings, and that changes what `isolate` means** (#640).
`render_scene`'s `isolate` keeps the target's whole subtree, which is right when
you isolate an assembly to look at the assembly. In a sheet the other subjects
are *rival cells*, not content — so on a parented rig 14 of 29 cells came back
rendering sub-assemblies, `golem_C_pelvis` rendering the entire golem. Each cell
now hides the descendants that are themselves subjects, while descendants that
are **not** cells of their own (a bolt, a trim strip) stay in frame, and
`warnings` names every subject that contains another. Framing follows the same
rule: `exactWorldBoundingBox` includes hidden children, so a cell framed on its
subject's transform was still framed on the subtree it had just hidden, leaving
the piece a speck. Sheet cells are framed on what they actually show
(`ignoreInvisible`). `isolate: false` restores the whole-subtree behaviour, since
a caller declining isolation wants the surroundings.

**Timeouts.** Every cell is a full render, so a sheet's cost is per-call, not
per-cell: 29 Arnold cells at 256 px exceeded the old 600 s ceiling, which *was*
the old default — so the timeout error's own advice to "pass a larger timeout_s"
could not be followed twice over. Both render tools now take `timeout_s`
(30 s–1800 s), and the dispatcher's `MAX_TIMEOUT_S` was raised to match. A
timeout never stops the command: Maya runs it to completion on the main thread
and the session stays busy either way, so raising the timeout costs nothing and
timing out costs the images. At the ceiling the error stops recommending a larger
value and says to split the work instead.

## Framing, and writing images to disk

**`target` frames; `isolate` hides.** Both `render_scene` and `capture_viewport`
take the pair, and either may be used alone. With neither, the whole scene is
framed — *lights excluded*. That exclusion is the fix for #639: `ls(geometry=True)`
returns light shapes, and a `setup_lighting(preset='environment')` dome measures
±1000 units, so "frame everything" put the camera 5294 units from a 5-unit
subject and returned a photograph of the sky. The blank guard could not catch it
either, because a dome fills the frame with opaque pixels. Lights are identified
by asking Maya (`getClassification(type, satisfies='light')`), not from a list,
so a renderer this code has never heard of is covered too; a caller who names a
light in `target` or `isolate` still gets it framed.

**`path` writes the image.** All four image tools — `maya_capture_viewport`,
`maya_capture_turntable`, `maya_render_scene`, `maya_render_sheet` — take an
optional `path`, and this is a *server-side* parameter: no plugin command sees
it. The rules are `export_fbx`'s, deliberately, so there is one path contract
across the tool surface:

- absolute, ending in `.png`;
- the parent directory must already exist — these tools do not create
  directories they were not asked to create;
- validated **before** Maya is asked for anything, so a typo does not cost a
  render;
- the bytes written are the full-resolution ones the plugin produced, not the
  copy downscaled to what an LLM can read.

A call that makes one image writes exactly the path given. A call that makes
several inserts the label before the extension — `D:/run/hero.png` with angles
`front` and `side` writes `hero_front.png` and `hero_side.png` — and the result
carries a `wrote: [...]` line naming every file, so a manifest can be built from
the call's own report.

**Server-side only, no plugin command:** `maya_load_reference_image` and
`maya_compare_to_reference` (the two remaining M2 tools in `src/maya_mcp/server.py`) never
cross the wire to the plugin. Reference images live in an in-process `ReferenceStore` on the
MCP server itself — held per server run, not per Maya scene, so they survive `new_scene` and
never touch the file on disk. `compare_to_reference` composites its stored reference against a
fresh `capture_viewport` result (a command that IS on the list above) entirely on the server
side. This is why the M2 tool count (7, README's table) and the M2 command count above (5) don't
match — reconcile them by the two lists here, not by assuming a 1:1 tool-to-command mapping.

## Commands (M2.3)

| cmd | params | result |
|---|---|---|
| `uv_atlas` | `{ names, patch?, cols?, rows?, margin?, mode?, projection?, world_scale? }` | `{ meshes: [{name, uv_bounds, inside_patch}], atlas, patch, patch_rect, margin, projection, normalized, world_scale, all_inside, warnings }` |

**`patch` is an integer index or an explicit `[col, row]`** — index 0 is the
top-left patch and the index counts along the row first, the way the atlas image
reads in a viewer. The integer form was documented but *refused* (#640): the MCP
tool typed the parameter as `object`, which constrains nothing and therefore
coerces nothing, so `patch: 0` could arrive as the string `"0"` and the handler
rejected it with an error naming the very form it had just been handed. The schema
now declares a real `int | [int, int]` union, and the handler reads a numeric
string as the integer it is, since the plugin is reachable over raw TCP where
nothing validates at all. Non-numeric text, floats and booleans are still refused.

## Commands (M2.4)

| cmd | params | result |
|---|---|---|
| `array` | `{ name, mode, count?, axis?, center?, angle?, offset?, step_rotate?, step_scale?, pivot?, name_prefix?, group_name? }` | `{ names: [...], mode, group, signed_volume, warnings }` |

**`name_prefix` is a prefix for `radial` and `linear`, and the NAME for `mirror`** (#640). An array of 12 needs 12 distinct names, so those two append `_1`..`_N`. A mirror makes exactly **one** copy, so numbering it was never collision avoidance — it cost the #601 golem run 11 renames, one per mirrored chunk, and nothing in the scene held any of the un-suffixed names. Pass `name_prefix='golem_R_arm'` to a mirror and the copy is called `golem_R_arm`. If that name really is taken, a suffix is added *and* `warnings` says so, because a silent rename is what made the caller check all eleven by hand. Omitting `name_prefix` still gives `<source>_1`: the fallback stem is the source's own name, which is by definition taken.

## Commands (rigging phase 1 / #602)

| cmd | params | result |
|---|---|---|
| `create_skeleton` | `{ joints? \| chain?, chain_prefix?, root_name? }` | `{ root, joints: [{name, position, parent, orient}], warnings }` |
| `bind_skin` | `{ mesh, root, method?, max_influences? }` | `{ mesh, root, skin_cluster, influences, unweighted_vertices, max_influences_exceeded, per_joint, warnings }` |
| `pose_skeleton` | `{ root, rotations, space? }` | `{ applied, joints: [{name, world_position}], max_displacement, displaced_vertices, per_mesh, warnings }` |
| `reset_pose` | `{ root }` | `{ reset, max_displacement, warnings }` |

`create_skeleton` takes either an explicit `joints` hierarchy or the `chain`
shorthand, and validates the whole call before creating anything — a
skeleton that dies half-built is orphan cleanup nobody asked for. Orientation
defaults to Maya's own convention (X aims at the first child, leaves
zeroed); whatever actually landed, default or explicit `orient` override, is
reported per joint in **degrees**, because orientation is where every rig
surprise lives. Joints are created with `segmentScaleCompensate` **off**:
Maya's default exports as FBX `InheritType 2`, which Unity compounds into
100x scale per joint level under the metres declaration (#703), and this
toolset never scales joints, so the flag buys nothing.

`bind_skin`'s `unweighted_vertices` must be `0` for a deliverable bind — a
vertex no joint owns stays behind when the creature moves, and nothing looks
wrong at bind time; `export_fbx(include_skins=true)` gates on the same fact
read back from the file. `per_joint` reports each influence's vertex count
and mean weight, which is how a bind is seen without a viewport. Re-binding
an already-bound mesh is refused — stacked skinClusters make weights
unexplainable — with a hint to unbind via `execute_python` or restore the
pre-bind checkpoint.

`pose_skeleton`'s `rotations` map is per-joint **local euler degrees,
absolute** (not deltas — re-applying a pose is idempotent). This map is the
pose currency phases 3 and 6 reuse: IK bakes into it, a clip keys it.
`max_displacement` is measured from vertices before/after, never bounding
boxes; a near-zero result against the mesh's own size warns, since that
usually means the rotation landed on a joint owning no vertices. Each bound
mesh is also measured alone in `per_mesh` — a combined max can hide one
inert mesh among several.

`reset_pose` restores the skeleton's `dagPose` bind pose. An unbound
skeleton has no bind pose — rotations are zeroed instead (the
`create_skeleton` rest pose) and a warning says so.

## Commands (rigging phase 2 / #668)

| cmd | params | result |
|---|---|---|
| `weight_report` | `{ mesh }` | `{ mesh, skin_cluster, vertices, max_influences, unweighted_vertices, unweighted_sample, max_influences_exceeded, exceeded_sample, max_weight_sum_error, histogram, per_joint, warnings }` |
| `mirror_weights` | `{ mesh, axis?, direction? }` | `{ mesh, skin_cluster, axis, direction, mirrored_vertices, on_plane_vertices, unpaired_vertices, changed_vertices, unweighted_vertices, warnings }` |
| `smooth_weights` | `{ mesh, joints?, iterations? }` | `{ mesh, skin_cluster, iterations, smoothed_vertices, changed_vertices, unweighted_vertices, max_influences_exceeded, warnings }` |
| `set_region_weights` | `{ mesh, joint, faces? \| within_radius_of? + radius?, weight, falloff? }` | `{ mesh, skin_cluster, joint, vertices_in_region, changed_vertices, sole_owner_vertices, unweighted_vertices, max_influences_exceeded, warnings }` |

Binding is one call; *good* weights are the craft, and agents cannot paint —
so the craft is programmatic. All four operate on an existing bind and refuse
an unbound mesh. `weight_report` is the perception tool (a measurement, no
checkpoint): per-joint ownership, offending-vertex samples, the
influence-count histogram, weight-sum drift. The three mutators write the
whole table in one API call, then **re-read it and report from the re-read**:
`changed_vertices` and post-op integrity (`unweighted_vertices`) are
measured, never computed.

`mirror_weights` pairs vertices and influences by reflected position
(`+to-` copies the +axis side onto the −axis side). An asymmetric skeleton —
an off-plane joint with no positional twin — refuses; asymmetric mesh regions
are counted in `unpaired_vertices`, left unchanged, and warned about. Run it
from the bind pose; a posed mesh pairs garbage and warns.

`smooth_weights` is laplacian smoothing over the mesh graph — the fix for
stair-stepped falloff at hips and shoulders. Every smoothed row is pruned
back to the cluster's `max_influences` and renormalized, so smoothing never
breaks the bind's promise to the exporter. `joints` limits smoothing to
vertices those joints hold.

`set_region_weights` blends one joint toward `weight` over a region — face
ids (hard assignment) or a sphere (`within_radius_of` + `radius`, `linear` or
`none` falloff) — while the other influences share the remainder in their
existing proportions. An empty region refuses rather than silently doing
nothing; a vertex the joint solely owns cannot shed weight (nobody to give it
to) and is counted in `sole_owner_vertices`.

## Commands (rigging phase 3 / #671)

| cmd | params | result |
|---|---|---|
| `pose_ik` | `{ root, joint, target, pole?, start?, keep? }` | `{ achieved_position, residual, rotations, chain, pole_used, kept, max_displacement, displaced_vertices, per_mesh, warnings }` |

`pose_ik` solves a joint chain to a world-space `target`, **bakes the result
to plain FK rotations, and deletes the handle** — no persistent IK state
ever exists in the scene. The `rotations` map (per-joint local euler
degrees, long-name keys) is the phase-1 pose currency: feed it straight to
`pose_skeleton`, key it in a phase-6 clip. `residual` is the measured miss
distance — an unreachable target is a number, not a silent stretch, and the
reach shortfall is spelled out in `warnings`.

The chain runs `start..joint`; `start` defaults to two joints above
`joint` — the classic 2-bone limb (hip for an ankle, shoulder for a
wrist). `pole` is a world **position** the knee/elbow should face. When
omitted, a bent chain keeps its own bend plane; a perfectly straight chain
has no plane, so the fold direction is Maya's guess and a warning says so —
pass `pole` to make it deterministic (a straight chain is quietly pre-bent
a few degrees toward the pole so the RP solver can fold at all; the solve
overwrites the nudge).

`keep=false` solves, measures everything, then restores the pose the call
found — a dry-run for "what would this pose take". `achieved_position` and
all displacement numbers are re-read from the scene after the bake, never
taken from the solver's claim.

## Commands (rigging phase 4 / #676)

| cmd | params | result |
|---|---|---|
| `author_physics` | `{ root | chunks, density?, overrides?, exclude? }` | `{ bodies: [{chunk, parent, mass, volume, signed_volume, com, watertight, open_edges, verts, tris, collider, joint}], density, total_volume, warnings }` |

`author_physics` is **read-only** — no checkpoint, nothing in the scene
changes. It MEASURES per-chunk physics-body data: `volume` is the
tetra-summed closed-mesh volume (|signed|; a negative `signed_volume`
means inward winding and warns), `com` is the tetra-weighted SOLID centre
of mass — the sculpt's, never a bbox centre or a vertex average — and
`mass = |volume| × density`, where `density` defaults to 1.0 so mass
numerically equals volume (deliberate: the handoff ships volumes, masses
are abstract, the engine owns the real constant). Non-watertight meshes
are detected by boundary-edge count (`open_edges`) and warned: the volume
reading is then unreliable, and it says so instead of guessing.

`collider` is ONE primitive per body — `box`, `sphere` or `capsule`,
chosen by extent ratios in the mesh's own principal frame (fits are
rotated; `rotation_deg` is the frame's XYZ euler) — with honesty
MEASURED: `volume_ratio` (primitive/|mesh|) and `max_escape` (furthest
vertex outside). Thresholds for the poor-fit warnings are derived from
the delivered golem's own worst fits (2.35 / 9.13% of bbox diagonal). A
bad fit is a warning with numbers, never a second primitive.

`joint` is the motion handoff's swing/twist cone. Limits are DESIGN
INTENT — never scene-measurable — and arrive via
`overrides = {chunk: {hinge_axis, hinge_range_deg, twist_range_deg?,
parent?}}`. Conversion is the knee rule verbatim: axis along the hinge,
`swing2 = 0`, `swing1 = (hi−lo)/2` covering the flex arc, twist locked
near zero (default `[0, 0]`), and `swing_centre_deg = (lo+hi)/2` placing
the arc so a one-sided range puts neutral at the extreme —
no-hyperextension as the range's own asymmetry. A parented chunk without
an override gets an explicit LOCKED joint plus a warning; a parentless
chunk gets `joint: null`. `parent` defaults to the nearest mesh-bearing
ancestor in the chunk set — and in a rigid-parent rig (#713), where each
chunk hangs off its own joint and the parent chunk is a SIBLING branch under
an ancestor joint rather than an ancestor, to the chunk carried by the
nearest ancestor joint above the chunk's own (#722). Chunks sharing one
joint are welded, never each other's parent; if an ancestor joint carries
several, the first by name is taken and the choice is warned. Flat-sibling
destruction rigs still supply `parent` via overrides, because there
parenthood is design intent too. **An override that supplies joint limits
for a chunk that resolves parentless REFUSES** — a limit with no joint to
attach to used to be dropped silently, leaving a manifest that looked
complete with no limits in it (#722).

Validation is ANALYTIC, not simulated (#675): degenerate volumes,
rest-pose-excluding ranges, multiple parentless bodies and every override
problem are warnings or refusals. Collider interpenetration at bind is
deliberately NOT checked — adjacent destruction chunks legitimately
interpenetrate at their shared joint, so that warning would always fire.

## Commands (rigging phase 5 / #691)

| cmd | params | result |
|---|---|---|
| `create_blendshape` | `{ mesh, targets: [{name, target_mesh}] }` | `{ mesh, blend_shape, targets: [{name, max_delta, vertex_count}], warnings }` |
| `set_blendshape_weights` | `{ mesh, weights: {name: 0..1} }` | `{ mesh, blend_shape, weights, max_displacement, per_target, warnings }` |

`create_blendshape` wires ordinary sculpted meshes as morph targets. The
deformer evaluates **front-of-chain** (before any skinCluster): a shape
models the neutral surface and the skin carries the shaped surface to the
pose, which is what makes a muscle corrective correct at a bent joint.
Targets must match the base's topology (refused with both vertex counts —
no wrap fallback) and are **consumed** once wired: the deltas live in the
deformer, and a stale editable copy invites sculpting a mesh that feeds
nothing. Each target's `name` becomes the weight alias, the
`set_blendshape_weights` key, and the exported Shape record's name.
`max_delta` is measured through the real deformer at weight 1; a target
measuring (near-)identical to the base warns. Creating again on the same
mesh ADDS targets to its one blendShape node — stacking a second deformer
is refused by construction.

`set_blendshape_weights` drives the named weights (0..1, absolute), lands
them sequentially in call order, and measures per step; the returned
`weights` map is every target re-read from the node. All-zero weights IS
the reset — the phase-1 pose-map currency is untouched.

Export: shapes ride along automatically (`FBXExportShapes` pinned on —
there is no parameter). The byte gate refuses an export whose scene
declares a target the file does not carry, and the result's `shapes` block
reports each channel's name and delta payload as read from the bytes.

## Commands (rigging phase 6 / clips / #695, multi-take #718)

| cmd | params | result |
|---|---|---|
| `author_clip` | `{ root, name, fps=30, keys: [{time_s, rotations?, blend_weights?, root_position?}], interpolation, loop, timeout_s=120 }` | `{ root, clip, fps, duration_s, frames, keyed_joints, keyed_weight_channels, root_position_keyed, interpolation, loop, start_frame, end_frame, clips, padded_channels, held_channels, back_filled, replaced, per_key, warnings }` |
| `preview_clip` | `{ root, name, angle?, every_nth?, resolution?, renderer?, zoom? }` | `{ clip, fps, start_frame, end_frame, frames, images, ... }` |
| `delete_clip` | `{ root, name? }` | `{ root, clip, clips, deleted_curves, max_displacement, warnings }` |

`author_clip` keys the phase-1 pose map over time. **One rig carries as many
named clips as the asset needs, laid end to end on ONE shared timeline** —
not a clip library with independent timelines, one timeline that every
clip on the rig occupies a range of. A new clip is always **APPENDED**
after the last one already on the rig: its `start_frame` is derived, never
passed, and `end_frame` is MEASURED back from the curves once keying is
done — the caller never computes frames, it reads them off the result.
Between two clips sits **exactly one unowned gap frame** (`GAP_FRAMES = 1`
in `clipmath.py`): if a clip ends at frame `E`, the next one starts at
`E + 2`, and frame `E + 1` belongs to neither — it is where the
interpolation from one clip's last pose to the next clip's first pose would
otherwise live, and leaving it unclaimed keeps every take's range an exact,
non-overlapping frame count. Re-authoring an existing name does not edit it
in place: its old range is cut and it is **re-appended at the tail**, so it
moves in take order but no OTHER clip's motion changes — `replaced` names
it when this happened, and is `None` for a genuinely new name. **One fps
per rig**: every clip shares the fps of the ones already on the rig,
because a take is a frame range on one timeline and one file cannot carry
two frame rates; a clip authored at a different fps is refused, naming the
existing rate.

Keys may also carry blendshape weights (resolved across the meshes bound to
the skeleton) and a world `root_position` for the root joint — the pelvis
bob a walk needs. `loop=true` refuses a clip whose last key does not close
onto its first, with the measured per-channel difference. Every key's
displacement is MEASURED by driving the scene time to that frame;
`duration_s` is re-read from the authored curves. `timeout_s` (default 120,
ceiling `MAX_TIMEOUT_S`) exists because the tool's own timeout advice was
unfollowable (#721): a long clip on a heavy scene outlives the default, and
an open Arnold RenderView (IPR) re-renders on every scene mutation, which
can stall keyframing for minutes.

**The self-contained rule, and its two kinds of pin.** All clips on a rig
share one curve per channel, so a channel a clip never mentions would
silently hold whatever a neighbour left there — the previous clip's last
pose forward, or a later clip's first pose backward. `author_clip` closes
both directions:

* **`padded_channels`** — channels some OTHER clip on the rig touches that
  THIS clip does not key anywhere in its own range. Pinned at their REST
  value (the value recorded the moment the channel first became
  curve-driven, or inferred with a warning for a scene that predates this
  attribute) at this clip's own boundary frames, so the take cannot inherit
  a neighbour's pose — a caller reading only this clip's take sees the rig
  sitting at rest outside the motion it actually authors.
* **`held_channels`** — channels this clip DOES animate, but did not key
  exactly at one of its own boundary frames (a sparse declaration, or a
  fractional-time key that rounds short of the boundary). These are pinned
  at the clip's OWN held value there — what its own range would already
  evaluate to at that frame — never at rest. Pinning rest here would
  invent motion the clip never authored: it would rewrite an authored final
  pose into a rest pose one frame later. `held_channels` is the honest
  sibling of `padded_channels`: same self-contained goal, opposite pin
  value, because one case has real motion to preserve and the other does
  not.

Both directions are also closed **backwards**: a curve holds its first
key's value backward in time, so a channel a NEW clip introduces (one no
earlier clip on the rig ever declared) would rewrite every earlier clip's
pose the moment it gets keys of its own. `back_filled` reports this case —
`{ clips, channels }`, the earlier clips and the channels pinned across
them — pinned at rest across their ranges, which RESTORES what each of
them measured when it was originally authored rather than changing it.
There is no "own held value" to prefer here, because this clip has no keys
of its own inside an earlier clip's range (clips are always appended at the
tail, by construction).

**Displacement is measured against whatever the skeleton MOVES — by
deformation OR by rigid parenting.** A mesh transform parented under a joint
with no skinCluster anywhere (#713's rig) is a legal rig, not an empty one;
it used to report `max_displacement: 0` and `preview_clip` refused it
outright (#720). `preview_clip` now refuses only a skeleton that moves no
mesh by EITHER mechanism, and the refusal names both.

**While any clip exists, static pose mutators refuse** (`pose_skeleton`,
`pose_ik`, `reset_pose`, `set_blendshape_weights`): curves own the
channels, and a static write would be silently overridden on the next frame
change. `delete_clip` takes an optional `name`, and what happens turns on
whether the rig has any clip LEFT afterward, not on whether `name` was
passed:

* **clips remain** — this is the normal named-partial-delete: cuts just
  that clip's range, leaving every other clip on the rig untouched. `clips`
  in the result reports what is left, in timeline order. **Gaps are not
  re-packed**: a take is an explicit frame range, so a hole where a middle
  clip used to be costs nothing and stays a hole — re-packing would move
  keys the caller never touched. `clip` in the result names the one that
  was removed.
* **none remain** — whether `name` was omitted (delete everything) or it
  named the LAST clip still on the rig, the effect is the same full
  teardown as before #718: every curve deleted, every keyed weight channel
  zeroed, the bind pose restored. `clips` in the result is then always
  `[]`. When `name` was omitted and several clips existed before the call,
  every one of them was torn down, but `clip` in the result names only the
  FIRST of them (the pre-delete list, index 0) — it does not enumerate the
  delete. Read `clips` (now empty) and `warnings` for the full story; treat
  `clip` here as naming one clip, not the scope of what was removed.

Both report the measured displacement of the return.

**`deleted_curves` on a NAMED, partial delete is structurally 0 while two or
more clips remain on the rig — this is a measurement, not a bug.** The
self-contained rule (above) keys every channel the rig uses at every clip's
own boundary frames, so cutting one clip's frame range essentially never
empties a curve outright: the curve still carries keys from the clips that
remain, including the pins the deleted clip's neighbours hold at their own
boundaries. `deleted_curves` counts curves that disappear ENTIRELY, and with
other clips still declaring those same channels, that count is honestly
zero. A future reader seeing 0 next to "deleted" should not "fix" this —
the curves that emptied out are exactly the ones a full (unnamed) delete
reports.

The rig's `playbackOptions` range is always set to the **full span** —
frame 0 through the latest `end_frame` across every clip on the rig, not
just the one most recently authored or deleted — so opening the scene and
scrubbing shows every clip, and `delete_clip` re-derives it after cutting a
range too.

`preview_clip` now takes the clip **by name** — a rig carries several, and
there is no more "the live clip" to default to; an unknown name is refused
with the names present. It renders every-nth frame through the render
pipeline into one contact sheet (camera placed at frame 0 of the NAMED
clip and held); `zoom` (default 1.0, mirrors `render_scene`'s) closes the
framing in — the gate measured the default 320px cell unjudgeable and
needed zoom 1.5-1.6 to read a blink. The result's `frames` list is a trap
for the unwary: `frame` is **absolute** (the rig's own timeline position,
`start_frame` plus the offset), but `time_s` is **clip-relative** (seconds
from the clip's own start, matching what `author_clip`'s `keys[].time_s`
meant when it was authored) — the same pair of units the rest of this
section uses throughout, never mixed within one field.

Export: pass `include_animation=true` to `export_fbx` — **every clip on the
rig** bakes to per-frame curves over the whole rig's span
(`FBXExportBakeComplexAnimation`, from frame `0` to `span_frames`, the
highest `end_frame` among the rig's clips), and one
`FBXExportSplitAnimationIntoTakes` call per clip carves that single baked
range into that many named takes.

**MEASURED (#718 Task 10): curve records are segmented PER TAKE, not one
per plug over the whole file.** A two-clip file carries THREE
`AnimationCurveNode` records for a plug any clip touches — one full-span
record under the exporter's own always-present default take ("Take 001",
keyed over the whole `0..span_frames` range), plus one per named take
carrying that take's OWN range. A first-wins collapse across the three
duplicates, keyed only by `(target, property)`, picks among them by an
FBX-internal object UID that is **not stable across otherwise-identical
exports**: 8 back-to-back exports of one correct scene measured 6 passes
and 2 failures — the gate refused a correct file at random. The fix
(#718 Task 10b) attributes each curve record to the take it belongs to:
`fbxbytes.anim_facts`'s `targets` entries carry a `take` field — the name
of the `AnimationStack` whose `AnimationLayer` owns that curve node,
resolved structurally through the `AnimationCurveNode` ->
`AnimationLayer` -> `AnimationStack` connection chain (never guessed from
tick ranges; `None` when the chain is absent). The byte gate now asserts,
per declared clip, against only THAT clip's own take's records: rotation
curves per keyed joint at the take's own `end_frame - start_frame + 1`
keys (not the whole file's span), root translation curves when
`root_position` was used by any clip, DeformPercent curves per keyed
weight channel, and — looked up **by name** among the file's takes —
that take's start/stop against the declared clip's own
`start_frame`/`end_frame` (converted through the rig's fps, half a frame
of tolerance). Records attributed to "Take 001", or to no take at all,
are ignored — not flagged — the same rule that already tolerates extra
undeclared takes. With `include_animation=false` (the default) the gate
asserts the file carries ZERO curve records even when the scene is
animated. The result gains `animation`, whose `clips` field is a per-clip
list — `{ name, start_frame, end_frame, duration_s, curves }` — read back
from the take and curve records the bytes actually carry for THAT clip's
own take, not echoed from the scene.

**MEASURED: the file always carries one MORE take than clips declared.**
`FBXExportSplitAnimationIntoTakes` writes each named take *alongside* the
exporter's own always-present default take (`"Take 001"`), so a correctly
exported N-clip rig legitimately carries **`N + 1`** takes — two for one
clip, as before #718, and one more per additional clip. `anim_violations`
looks each declared clip up **by name** among the file's takes and ignores
the rest — an extra take is not a violation, the same rule
`shape_violations` applies to undeclared shape channels.

**Multi-CLIP is supported; multi-RIG refuses.** One skeleton may carry any
number of clips and they all export into the one file's takes. Two
DIFFERENT skeletons each carrying clips in the same scene refuse the
export outright, naming both roots: a take is a frame range over the WHOLE
file, so a multi-rig file would need a timeline policy of its own that
does not exist yet. `delete_clip` the rig that is not being exported.

## Delivery

| cmd | params | result |
|---|---|---|
| `export_fbx` | `{ path, metres_per_unit, nodes?, include_skins?, include_animation? }` | `{ path, bytes, fbx_version, node_count, mesh_count, root_nodes, unit_scale_factor, metres_per_unit, world_bounds_min, world_bounds_max, height_m, bounds_unavailable_reason, skin, shapes, animation }` |

Every field of the result is read back **out of the written file**, never from the Maya scene — the unit defect this tool guards (#629) is produced by the exporter and is absent from the scene, so a scene-derived report would be confidently wrong in exactly the case that matters. The file is written to a sibling temp path and only reaches `path` once it passes; a refused export leaves whatever was already there untouched.

`metres_per_unit` is required and only `1.0` exports. There is no default on purpose: a guess about what one unit means is what shipped three deliveries at 100x.

The gate makes **two** assertions. The declaration must say metres (`UnitScaleFactor` 100.0), and no node whose scale reaches a vertex may carry one — that is the node holding the geometry and every ancestor above it. Nodes whose scale cannot touch a vertex are not gated: a whole-scene export writes lights and cameras as `Model` records too, and refusing an export because a light or an annotation locator is scaled would blame vertex magnitude for something that has no vertices (#646). A locator and a group are both `Null` in the file, so the test is structural, not by node kind.

Omitting `nodes` exports the whole scene, including lights and cameras (`FBXExportCameras`/`FBXExportLights`, pinned rather than left to `FBXResetExport`'s defaults). Passing `nodes` exports that selection **plus its ancestor chain** — so a group above the selection carries its scale into the file, and the gate refuses it by name rather than silently shipping a mis-sized asset.

`height_m` and the bounds are null when the reader cannot compose the hierarchy — a non-default `rotateOrder` is the case that happens in practice — and `bounds_unavailable_reason` then says which, distinctly from "the file holds no geometry". The export still succeeds: a measurement the reader cannot make must not fail bytes that already passed the gate.

`include_skins` (default `false`) additionally writes the skinCluster
deformers and the BindPose, and gates on the **file's own** skin records,
not the scene: a skin deformer must be present, every cluster must link
joints (a selected export listing the mesh without the skeleton root writes
a deformer with zero clusters — named separately, since "every vertex
unweighted" otherwise reads like a bad bind rather than a short selection),
a BindPose record must exist, and per-vertex weight sums must be within
`WEIGHT_SUM_TOL` = `1e-2` of 1.0. That tolerance is measured, not guessed:
Maya's FBX exporter drops every skin weight strictly below `1e-3` without
renormalising what is left, so a correct `max_influences=8` bind can lose up
to ~7e-3 per vertex on export alone — a `1e-3` tolerance tried first refused
a real, correctly-bound mesh. LimbNodes (skinned joints) gate under the same
identity-scale rule as meshes (#629), since a joint's scale reaches a vertex
without being its ancestor.

LimbNodes additionally must not carry FBX `InheritType 2` — Maya writes it for
a joint whose `segmentScaleCompensate` is on, and Unity (which does not
implement that inheritance) materialises the metres declaration as
localScale 100 on every such joint and compounds it per level, silently
(#703: a 12-joint serpent instantiated at world scale ~10^21 m with a clean
console). `create_skeleton` turns SSC off at joint creation, so this fires
only on skeletons authored outside the tool or predating the fix.
