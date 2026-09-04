# #824 — capture_viewport says when the target it framed is hidden

Redmine #824, the item #823 noted and did not fix: `capture_viewport` places
its camera from the target's bounding box alone, so an object standing
between them fills the frame and nothing said so. Probes (kept):
`evals/occlusion_probe_824.py` (a–J), `_824b.py` (grouped target, timing,
isolate, miss shape), `_824c/d/e.py` (the isolate-blank investigation that
became #825). Findings under `evals/occlusion_probe_824/`. Maya 2027, agent
9878, repo cwd.

## What was measured

- **K2 again**: `back` + `target=|red` on a red(+Z)/blue(−Z) pair → 65536 /
  65536 blue px, zero red, `blank: false`, `warnings: []`. Nine rays from the
  placed camera to |red's bbox centre and corners all hit |blue first
  (`MFnMesh.closestIntersection`, 0.8 ms). front and side: 0 of 9.
- **Partial cover** tracks the pixels: blue shifted x=0.5 → 5 of 9 blocked,
  7442 red px against 14884 clear; shifted x=0.9 → 0 of 9, 14884.
- **A floor grazes**: a cube standing on a plane has its bottom corners ON the
  plane, so rays to them hit it at param == distance: 4 of 9 blocked from
  three_quarter and 2 from the front with no tolerance, 0 with 1e-4.
- **A grouped target's own members block its far corners**: 4 of 9 from the
  back until the target's shapes were excluded. `listRelatives(
  allDescendents=True, shapes=True)` answered NOTHING for the group;
  `ls(<nodes>, dag=True, shapes=True)` is the form that works.
- `ls(geometry=True, visible=True)` lists a skinned mesh's ShapeOrig next to
  the drawn shape; `.intermediateObject` tells them apart. A hidden object,
  or one under a hidden parent, is not listed.
- `isolate=[red]` + target red from the back drew 14884 red (in the process
  where isolate drew at all, see #825): what isolate hides cannot occlude.
- **Timing**: 9 rays against a 40k-face sphere, 11 ms brute force, 6 ms with
  `autoUniformGridParams` (whose build is the 6 ms). No accelerator used.
  A 500×500 `polySphere` (250k faces) HUNG Maya twice (>600 s) — the
  primitive, not the rays; two agent Mayas killed for it.
- `closestIntersection` returns `None` on a miss, a 6-tuple on a hit.

## What changed

- `maya_plugin/handlers/capture.py`: `bbox_samples`, `occlusion_warning`,
  `occluder_shapes`, `blocked_samples` (the OpenMaya seam, module-level like
  `physics._points_and_triangles`), `target_occlusion` (never raises; the
  unmeasurable form is reported, blank_warnings discipline). `_capture_one`
  asks it after `viewFit`, only for a named target on a placing angle, and
  carries `occlusion` in the shot; `frame_warnings` turns it into text.
  Warning, never a refusal.
- `docs/protocol.md`: the paragraph under "Framing". `src/maya_mcp/server.py`:
  the `target` description.
- Tests: `tests/test_capture.py` (FakeCaptureCmds learned `ls(dag, shapes)`,
  intermediate shapes, a transform's bbox as the union of its shapes, and
  ancestor transforms; 20 new tests, file 125/125),
  `tests/test_handlers_mayapy.py::TestOcclusionRaysInMaya` (4, real MFnMesh:
  9/9 blocked, 0/9 clear, the floor graze, the grouped/skinned exclusions).
- Gate `evals/occlusion_live.py`: 13/13 on a fresh agent 9878. Suite
  3170 / 0 failed / 0 errors / 2 skipped.

## Found on the way, not fixed here → #825

Every ISOLATE capture of two of the three agent Maya processes today came
back blank (0 opaque px) while non-isolate captures drew 65536; the third
process drew 14884 red for the same call. Reproduced with the #824 code
monkeypatched out and with a hand-rolled isolate + playblast. The main
window reads `isHidden()` after `show()`, and `showNormal()` did not change
the isolate result. The blank guard names it; gate check 6b passes a blank
frame by design and names the ticket.
