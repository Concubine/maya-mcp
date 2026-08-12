# M0 manual loop test — the snowman gate

M0's exit test (design doc §7): a fresh Claude session, using ONLY the three
M0 tools, builds **a snowman with a carrot nose**, correcting proportions from
the screenshots it captures. This validates the whole thesis — the
perceive/act loop — before any more tools are built on top of it.

## Prerequisites

- Maya 2023+ installed and open with an empty scene and a visible viewport.
- This repo synced (`uv sync`).

## Steps

1. **Start the plugin** in Maya's Script Editor (Python tab):

   ```python
   import sys; sys.path.insert(0, r"D:/devel/maya-mcp")
   from maya_plugin import maya_mcp_plugin
   maya_mcp_plugin.start_server()
   ```

   Expected: no output, no freeze. `~/.maya-mcp/logs/plugin.log` gains a
   "listening on 127.0.0.1:9877" line.

2. **Register the server** with Claude Code (once):

   ```bash
   claude mcp add maya -- uv --directory D:/devel/maya-mcp run maya-mcp
   ```

3. **Run the eval.** Fresh Claude session, prompt:

   > Using only the maya tools, model a snowman with a carrot nose in the open
   > Maya scene. Work iteratively: capture the viewport after each significant
   > change and correct proportions from what you see before adding detail.

## What to watch (open questions from design doc §9)

- **#1 playblast reliability:** do captures come back at all, and do they show
  the actual scene (not a grey/black frame)? If playblast fails the M3dView
  fallback engages — the log records which path ran.
- **#2 image size:** is 768 px readable in the client? Too big/slow → lower
  `MAYA_MCP_MAX_IMAGE_PX`.
- **Viewport hygiene:** after the session, the original camera, shading mode,
  grid, and selection must be exactly as before the first capture.
- **Undo:** each tool call should be one undo step (Ctrl+Z walks back cleanly).
- **Feel:** does Claude actually *correct* from what it sees? That's the bet.

## Pass criteria

Recognizable snowman (stacked spheres, carrot nose), and at least one visible
correction driven by a capture (e.g. resizing a sphere after seeing bad
proportions). Record tool-call count.

## If it fails

File what broke on redmine #573 (maya-mcp project) — M1 does not start until
this loop is solid.
