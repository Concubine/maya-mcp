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
| `ping` | `{}` | `{ pong, maya, plugin: {package_dir, digest, stamp}, process: {pid, host, port, started_at, uptime_s, scene} }` |
| `execute_python` | `{ code, timeout_s?, risky? }` | `{ stdout, stderr, result_repr, traceback, namespace_keys, checkpoint? }` |
| `reset_namespace` | `{}` | `{ reset: true }` |
| `get_scene_graph` | `{ filter?, max_objects?, cursor? }` | `{ objects: [...], total, cursor }` |
| `capture_viewport` | `{ angles?, shading?, wireframe_overlay?, buffer?, isolate?, target?, frame_all?, resolution? }` | `{ images: [{angle, png_b64}], camera_positions: [...] }` |

`ping` answers two questions a caller cannot answer for itself: `plugin` says
which *code* is live (feed it to `version.compare`), `process` says which
*process* is answering — a port is not an identity, and a Maya that lost the
bind race is indistinguishable from yours without a pid (#648). A bind failure
raises `PortInUseError` rather than leaving a Maya running with no listener.

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

## Delivery

| cmd | params | result |
|---|---|---|
| `export_fbx` | `{ path, metres_per_unit, nodes? }` | `{ path, bytes, fbx_version, node_count, mesh_count, root_nodes, unit_scale_factor, metres_per_unit, world_bounds_min, world_bounds_max, height_m, bounds_unavailable_reason }` |

Every field of the result is read back **out of the written file**, never from the Maya scene — the unit defect this tool guards (#629) is produced by the exporter and is absent from the scene, so a scene-derived report would be confidently wrong in exactly the case that matters. The file is written to a sibling temp path and only reaches `path` once it passes; a refused export leaves whatever was already there untouched.

`metres_per_unit` is required and only `1.0` exports. There is no default on purpose: a guess about what one unit means is what shipped three deliveries at 100x.

The gate makes **two** assertions. The declaration must say metres (`UnitScaleFactor` 100.0), and no node whose scale reaches a vertex may carry one — that is the node holding the geometry and every ancestor above it. Nodes whose scale cannot touch a vertex are not gated: a whole-scene export writes lights and cameras as `Model` records too, and refusing an export because a light or an annotation locator is scaled would blame vertex magnitude for something that has no vertices (#646). A locator and a group are both `Null` in the file, so the test is structural, not by node kind.

Omitting `nodes` exports the whole scene, including lights and cameras (`FBXExportCameras`/`FBXExportLights`, pinned rather than left to `FBXResetExport`'s defaults). Passing `nodes` exports that selection **plus its ancestor chain** — so a group above the selection carries its scale into the file, and the gate refuses it by name rather than silently shipping a mis-sized asset.

`height_m` and the bounds are null when the reader cannot compose the hierarchy — a non-default `rotateOrder` is the case that happens in practice — and `bounds_unavailable_reason` then says which, distinctly from "the file holds no geometry". The export still succeeds: a measurement the reader cannot make must not fail bytes that already passed the gate.
