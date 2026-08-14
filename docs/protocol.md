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
| `ping` | `{}` | `{ pong: true, maya: bool }` |
| `execute_python` | `{ code, timeout_s?, risky? }` | `{ stdout, stderr, result_repr, traceback, namespace_keys, checkpoint? }` |
| `reset_namespace` | `{}` | `{ reset: true }` |
| `get_scene_graph` | `{ filter?, max_objects?, cursor? }` | `{ objects: [...], total, cursor }` |
| `capture_viewport` | `{ angles?, shading?, wireframe_overlay?, buffer?, isolate?, frame_all?, resolution? }` | `{ images: [{angle, png_b64}], camera_positions: [...] }` |

## Commands (M1)

Session safety:

| cmd | params | result |
|---|---|---|
| `checkpoint` | `{ label }` | `{ checkpoint_id, path }` |
| `restore_checkpoint` | `{ checkpoint_id }` | `{ restored, pre_restore_checkpoint }` |
| `undo` | `{ steps? }` | `{ undone, requested }` |
| `redo` | `{ steps? }` | `{ redone, requested }` |
| `new_scene` | `{ confirm }` | `{ new_scene: true }` |
| `open_scene` | `{ path, confirm? }` | `{ opened }` |
| `save_scene` | `{ path? }` | `{ path }` |

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
| `boolean_op` | `{ a, b, op, new_name }` | `{ name, tris, watertight, warnings, carved_text? }` |
| `etch_text` | `{ mesh, text, face, width?, depth?, font?, mirror?, rotate_deg?, new_name? }` | `{ name, tris, watertight, warnings, carved_text }` |
| `sculpt_ops` | `{ mesh, ops: [...] }` | `{ applied, ops: [...], tris, warnings, checkpoint_id? }` |
| `deform` | `{ mesh, deformer, params?, delete_history_after? }` | `{ deformer_nodes: [...], baked, warnings }` |
| `remesh_retopo` | `{ mesh, target_polycount, keep_original? }` | `{ name, tris, method, warnings }` |
| `mesh_cleanup` | `{ mesh, merge_verts_threshold?, delete_history?, freeze_transforms?, conform_normals? }` | `{ name, before, after, warnings }` |

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

**Server-side only, no plugin command:** `maya_load_reference_image` and
`maya_compare_to_reference` (the two remaining M2 tools in `src/maya_mcp/server.py`) never
cross the wire to the plugin. Reference images live in an in-process `ReferenceStore` on the
MCP server itself — held per server run, not per Maya scene, so they survive `new_scene` and
never touch the file on disk. `compare_to_reference` composites its stored reference against a
fresh `capture_viewport` result (a command that IS on the list above) entirely on the server
side. This is why the M2 tool count (7, README's table) and the M2 command count above (5) don't
match — reconcile them by the two lists here, not by assuming a 1:1 tool-to-command mapping.
