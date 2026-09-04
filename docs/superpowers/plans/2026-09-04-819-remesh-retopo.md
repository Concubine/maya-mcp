# #819 — remesh_retopo, run against a real Maya for the first time

Redmine #819, first item of the #818 audit. The command had headless tests and
had never been sent to Maya. Probe `evals/remesh_probe_819.py` (findings in
`evals/remesh_probe_819/`), Maya 2027, agent 9878, repo cwd.

## What the probe measured

`polyRetopo`, `polyRemesh` and `polyReduce` all exist; `polyRetopo` is the route
taken every time (plugins `modelingToolkit`, `flowRetopology`). On every mesh
tried it ran in under a second and:

| mesh | target | faces after | notes |
|---|---|---|---|
| sphere 20×20 (400 f) | 200 | 183 | within the node's `targetFaceCountTolerance` of 10 |
| sphere | 800 | 794 | |
| sphere | 2000 | 1903 | a target ABOVE the current count upsamples; no warning needed |
| cube (6 f) | 400 | 348 | a box becomes a 348-face box; bbox unchanged |
| open plane 10×10 (100 f) | 100 | 100 | |
| two-cube combine (2 shells) | 300 | 296 | shells stay 2 |
| transformed, pivoted, shaded sphere | 200 | 183 | translate, rotate, scale, pivot and the shading group all survive; history gone; bbox within 2 % |

Raw `cmds.polyRetopo` keeps the same shape node and leaves a `polyRetopo1`
history node with `targetFaceCount`, `targetFaceCountTolerance=10`,
`preprocessMesh=True`, `preserveHardEdges=False`, `topologyRegularity=0.5`,
`faceUniformity=0`, `anisotropy=0.5`.

**Two silent defects:**

1. **Every UV is destroyed.** 439 → 0 on the sphere, 121 → 0 on the plane,
   14 → 0 on the cube, 28 → 0 on the combine. The result said nothing. A
   retopologised mesh could not be textured or baked afterwards.
2. **Only `tris` was reported** for a caller who asked for a FACE count:
   200 asked, 366 answered, nothing to compare.

And a trap: the kept hidden original is a real mesh, and `export_fbx` ships
hidden meshes — MEASURED in the gate, the file holds two meshes.

## What shipped

`modeling.remesh_retopo`: measures `faces_before` / `uvs_before` first; after
the remesh, if the UVs are gone and the original was kept, transfers them back
by world position (`transferAttributes transferUVs=2 sampleSpace=0
searchMethod=3`) BEFORE the history delete; reports `faces`, `faces_before`,
`target_polycount`, `uvs {before, after, transferred}`; warns when the UVs are
gone with no original (naming `maya_uv_atlas` and `keep_original=true`), and
always names the hidden original as something an export ships. `RemeshResult`
gained the fields; protocol.md row + prose. Fake: `polyEvaluate(uvcoord=)`,
`transferAttributes`. Five tests in `TestRemeshReportsAndRepairsWhatRetopoDestroys`.

## Gate

`evals/remesh_retopo_live.py` **12/12** (no captures): sphere → 183 faces with
UVs back (439 → 199 transferred), transform/pivot/SG/shell intact, history
gone, hidden-original warning present and its claim measured (export writes 2
meshes); `keep_original=false` → UVs 0, warning names uv_atlas, no original
warning; the two-shell combine keeps 2 shells at 296 faces with UVs transferred.

Note on the transferred UVs: 199 UVs on 185 vertices — a per-vertex
projection of the old layout onto the new topology, enough to texture and
bake, not a seam-faithful copy. The number is reported, not hidden.
