# maya-mcp

An MCP server that lets an LLM (Claude Desktop / Claude Code) model, texture, light, and
render 3D content in a live Autodesk Maya session through an iterative visual feedback loop.

**Status: M2** — M1 (perceive/act loop, modeling primitives, `boolean_op`, `etch_text`,
sculpt/deform, remesh/cleanup, session safety, viewport/camera control) plus object readback
(`get_object_info`), turntable capture, reference-image comparison, lighting rigs
(`setup_lighting`), and materials/texturing (`assign_material`, `apply_texture_recipe`).
See [docs/design.md](docs/design.md) for the full design and milestones.

## Security warning

`maya_execute_python` is **arbitrary code execution on your machine**, driven by an LLM.
Only run this server locally, only connect clients you trust, and treat the Maya session as
disposable. The plugin binds `127.0.0.1` only by default; non-loopback binding requires both
`MAYA_MCP_BIND_ANY=1` and `MAYA_MCP_TOKEN` to be set.

## Architecture

```
Claude client ◄─MCP (stdio)─► maya-mcp server ◄─TCP 127.0.0.1:9877─► Maya plugin
                              (this package)     length-prefixed        (socket thread +
                                                 JSON frames             main-thread dispatch)
```

## Install

Requirements: Python 3.10+, [uv](https://docs.astral.sh/uv/), Maya 2023+.

```bash
git clone <this repo> && cd maya-mcp
uv sync
```

### 1. Install the Maya plugin

```bash
uv run python maya_plugin/install.py
```

This copies `maya_plugin/` into your Maya scripts directory and prints the `userSetup.py`
autoload snippet. It prints exactly what it will do and asks before touching anything.

Manual alternative — run inside Maya's Script Editor (Python tab):

```python
import sys; sys.path.insert(0, r"D:/devel/maya-mcp")
from maya_plugin import maya_mcp_plugin
maya_mcp_plugin.start_server()   # listens on 127.0.0.1:9877
```

### 2. Register the MCP server with your client

Claude Code:

```bash
claude mcp add maya -- uv --directory D:/devel/maya-mcp run maya-mcp
```

Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "maya": { "command": "uv", "args": ["--directory", "D:/devel/maya-mcp", "run", "maya-mcp"] }
  }
}
```

### 3. Smoke test

With Maya open and the plugin started, ask Claude: *"Use maya_get_scene_graph to list the scene."*
If the plugin is not running you get an actionable "plugin not connected" error, not a hang.

## Configuration

Environment variables, all optional:

| Variable | Default | Meaning |
|---|---|---|
| `MAYA_MCP_HOST` | `127.0.0.1` | Plugin host the server connects to |
| `MAYA_MCP_PORT` | `9877` | Plugin TCP port |
| `MAYA_MCP_TOKEN` | unset | Shared secret; every frame must carry it when set |
| `MAYA_MCP_LOG_LEVEL` | `INFO` | Rotating file logs in `~/.maya-mcp/logs/` |
| `MAYA_MCP_MAX_IMAGE_PX` | `768` | Longest edge for returned viewport images |

## Tools

`src/maya_mcp/server.py` is the authoritative source — the table below enumerates its
`@mcp.tool` wrappers (33 total: 3 from M0, 23 added in M1, 7 added in M2). Schemas
(`src/maya_mcp/schemas.py`) are the reference for exact fields; each row here is one sentence.

### Perception (M0)

| Tool | Description |
|---|---|
| `maya_execute_python` | Run Python in Maya with a persistent namespace; full tracebacks come back verbatim. |
| `maya_get_scene_graph` | Compact paginated outline of the scene; never returns component data. |
| `maya_capture_viewport` | Offscreen multi-angle viewport captures returned as images; side-effect-free. |

### Session safety

| Tool | Description |
|---|---|
| `maya_checkpoint` | Incremental scene save to the checkpoint directory; keeps the newest 20. |
| `maya_restore_checkpoint` | Replace the current scene with a checkpoint (auto-checkpoints first; discards the undo queue). |
| `maya_undo` | Undo the last N mutating tool calls (one call = one undo step). |
| `maya_redo` | Redo previously undone tool calls. |
| `maya_new_scene` | Start an empty scene; refuses without `confirm=true`. |
| `maya_open_scene` | Open a scene file, replacing the current scene; requires `confirm=true` if the current scene has unsaved changes. |
| `maya_save_scene` | Save the scene (.ma or .mb by extension). |
| `maya_reset_namespace` | Clear the persistent `maya_execute_python` namespace. |

### Scene ops

| Tool | Description |
|---|---|
| `maya_create_primitive` | Create a polygon primitive (cube/sphere/cylinder/plane/torus/cone) at an optional transform. |
| `maya_duplicate` | Duplicate an object by name, optionally offsetting the copy. |
| `maya_array` | Mirror, radial-array, or linear-array an existing object into real duplicates; `count` is the total including the source. |
| `maya_transform` | Move/rotate/scale one or more objects by name. |
| `maya_group` | Create a new group transform and parent named objects under it. |
| `maya_parent` | Reparent one object under another. |
| `maya_rename` | Rename an object by name. |
| `maya_delete_objects` | Delete objects by name; all-or-nothing if any name is missing. |

### Modeling and sculpting

| Tool | Description |
|---|---|
| `maya_boolean_op` | Boolean two meshes (union/difference/intersection); auto-checkpoints, deletes construction history, collapses shading to one material. |
| `maya_etch_text` | Carve text into a mesh face in one call (glyph, size, orient to face normal, depth, boolean, cleanup); reuses `boolean_op`'s core. |
| `maya_sculpt_ops` | Apply a sequence of sculpt ops (`soft_move`, `inflate_region`, `displace_noise`, `smooth`, `extrude_faces`, `bevel_edges`, `crease_edges`, `bridge`) to one mesh. |
| `maya_deform` | Apply a nonlinear/lattice deformer (bend/lattice/squash/twist/sculpt) to a mesh by name. |
| `maya_remesh_retopo` | Retopologize a mesh toward a target polycount (polyRetopo, falling back to polyRemesh, then polyReduce); auto-checkpoints. |
| `maya_mesh_cleanup` | Merge near-duplicate vertices, conform normals, freeze transforms, and delete construction history. |

### Viewport and camera

| Tool | Description |
|---|---|
| `maya_set_viewport` | Persistently configure the working viewport (grid/icon/manipulator visibility, lighting mode). |
| `maya_set_camera` | Create/position a named camera and, by default, make it the active viewport camera. |

### Perception and judgement (M2)

| Tool | Description |
|---|---|
| `maya_get_object_info` | Read one object's transform, mesh stats, UV sets, shading, or history — how you verify a material actually landed. |
| `maya_capture_turntable` | Orbit the subject and return a single contact-sheet image (up to 16 frames for the token cost of one). |
| `maya_load_reference_image` | Store a reference image in the server, by id, for later side-by-side comparison; survives `new_scene`. |
| `maya_compare_to_reference` | One side-by-side image: the reference on the left, your live viewport on the right. |

### Rendering (M2.2)

| Tool | Description |
|---|---|
| `maya_render_scene` | Render frames through the render pipeline instead of the viewport: shows transmission and refraction as they really are, and works on a Maya with no visible window. Reports each frame's opaque pixel count, because a render of nothing is still a valid image. |

**Which eye to use.** `maya_capture_viewport` is fast (milliseconds), needs a
mapped window, and draws transmissive materials as plain transparency — a
diamond and a plastic block look the same. `maya_render_scene` costs seconds a
frame, needs no window at all, and under Arnold refracts for real. Judge shape
and composition with the viewport; judge materials with the renderer.

### Lighting and materials (M2)

| Tool | Description |
|---|---|
| `maya_setup_lighting` | Build a preset lighting rig (three-point/single-sun/HDRI) so the model can actually be judged; the only tool that deletes existing scene lights. |
| `maya_assign_material` | Assign one shader (standardSurface/lambert/blinn) to a whole mesh, object-level only. |
| `maya_apply_texture_recipe` | Build a named texture network (noise bump, ramp gradient, layered mask, file texture) and wire it into a mesh's shader. |

### Checkpoint directory and undo contract

Checkpoints save to `<scene_dir_or_workspace_root>/checkpoints/NNN_label.ma` (numbered,
newest 20 kept). `maya_restore_checkpoint` takes the `checkpoint_id` **stem** returned by
`maya_checkpoint` (e.g. `003_pre_rune`), not a file path.

The plugin dispatcher wraps each mutating tool call in one `undoInfo` chunk, so **one tool
call = one undo step** via `maya_undo`/`maya_redo`. Two exceptions:

- `maya_undo`/`maya_redo`/`maya_new_scene`/`maya_open_scene`/`maya_restore_checkpoint` are
  themselves chunk-exempt (they manipulate the undo queue or reload the scene directly).
- `maya_sculpt_ops`'s vertex ops — `soft_move`, `inflate_region`, `displace_noise` — write
  through `MFnMesh.setPoints`, which bypasses Maya's undo queue entirely; `maya_undo` will
  **not** revert them. When any of the three appear in a `sculpt_ops` call, the call
  auto-checkpoints first and returns a `checkpoint_id` (not a path) — restore that via
  `maya_restore_checkpoint` to recover. This is a different contract from `ExecuteResult.checkpoint`
  (from `maya_execute_python(risky=true)`) and `CheckpointResult.path` (from `maya_checkpoint`),
  which return a file **path**, not an id — don't confuse the two shapes.

## Known ceiling

This loop reliably reaches "clean stylized game asset" quality and does not reach ZBrush-grade
organic sculpting — the perceive/act loop is orders of magnitude lower-bandwidth than an artist
with a tablet. Do not benchmark against faces or animals in v1.

## Tests

```bash
uv run pytest                  # pure-Python: protocol, dispatcher, connection, images
mayapy -m pytest tests/test_handlers_mayapy.py   # optional, needs Maya
```
