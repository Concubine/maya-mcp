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

---

## RESULT — 2026-08-12: PASSED

Run on Maya 2027 (Windows), driven end-to-end through the real MCP stdio
server. Snowman with carrot nose + coal eyes built in 7 productive tool calls
(1 scene graph, 3 execute_python, 3 capture rounds), with multiple visible
capture-driven corrections (framing via isolate, silhouette proportions).

Two real capture bugs were found BY the loop and fixed live:
1. Isolate rendered blank/stale: modern Maya implements View Selected via the
   editor mainListConnection + `modelEditor -viewSelected`, not the legacy
   `isolateSelect -state/-loadSelected` (which silently no-ops on 2027).
   Fixed to use Maya's own `enableIsolateSelect` + locked list connection.
2. Selection highlight wireframes polluted captures; now cleared pre-playblast
   and restored after.

Open question #1 (design doc §9) answered for Windows/Maya 2027: playblast
offscreen works reliably; the M3dView fallback never needed to fire.
Viewport hygiene verified: no temp cameras, isolate restored, undo queue free
of capture churn. userSetup.py autoload verified on cold Maya start.

## ADDENDUM — 2026-08-12: isolate fix #1 replaced (redmine #575)

The `enableIsolateSelect` + locked mainListConnection fix above turned out to
break VP2 shading-group resolution for any shape with per-face/groupId
bindings — such shapes rendered flat unassigned-green, isolate-only (found
during the golem run, #574). Replaced with the `isolateSelect
state/addDagObject` API (membership lives in the panel's ViewSelectedSet, so
the pre-playblast select-clear needs no locking), plus a forced refresh before
playblast (a shape's first-ever draw under isolate precedes its shading-group
binding — one transient green frame otherwise).

## Regression checks

After any change to `maya_plugin/handlers/capture.py`, with Maya open and the
plugin listening:

```bash
.venv/Scripts/python.exe evals/isolate_regression.py
```

Builds a temporary per-face-shaded cube (the minimal trigger for both green
modes above), captures it with isolate, and asserts material colors rather
than VP2's unassigned-green. Exit 0 = pass; the cube is deleted either way.
