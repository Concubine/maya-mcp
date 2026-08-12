# maya-mcp

An MCP server that lets an LLM (Claude Desktop / Claude Code) model, texture, light, and
render 3D content in a live Autodesk Maya session through an iterative visual feedback loop.

**Status: M0** — the perceive/act loop only: `maya_execute_python`, `maya_get_scene_graph`,
`maya_capture_viewport`. See [docs/design.md](docs/design.md) for the full design and milestones.

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

## Tools (M0)

- `maya_execute_python(code, timeout_s=30, risky=False)` — run Python in Maya with a
  persistent namespace; full tracebacks come back verbatim.
- `maya_get_scene_graph(filter=None, max_objects=200, cursor=None)` — compact paginated
  outline of the scene; never returns component data.
- `maya_capture_viewport(angles=[...], shading=..., wireframe_overlay=True, ...)` — offscreen
  multi-angle viewport captures returned as images.

## Known ceiling

This loop reliably reaches "clean stylized game asset" quality and does not reach ZBrush-grade
organic sculpting — the perceive/act loop is orders of magnitude lower-bandwidth than an artist
with a tablet. Do not benchmark against faces or animals in v1.

## Tests

```bash
uv run pytest                  # pure-Python: protocol, dispatcher, connection, images
mayapy -m pytest tests/test_handlers_mayapy.py   # optional, needs Maya
```
