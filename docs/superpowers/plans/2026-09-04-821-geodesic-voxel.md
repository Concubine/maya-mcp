# #821 — bind_skin geodesicVoxel, measured for the first time

Redmine #821, third item of the #818 audit. `bind_skin method=geodesicVoxel`
had never been sent to a Maya; `heatMap` had hung one (#797) and was
undecided. Probes (kept): `evals/geovoxel_probe_821.py` (A), `_821b.py` (B),
`_821c.py` (C); findings under `evals/geovoxel_probe_821/`. Maya 2027, agent
9878, repo cwd.

## What the probe found — the route never did a geodesic bind

`cmds.skinCluster(bindMethod=3)` computes **no weights**. It leaves Maya's
untouched default table — every vertex at 1.0 on the last influence — and
returns success. On the fixture tube all 140 vertices sat on the tip joint;
on a two-leg mesh every vertex was 0.5/0.5 on the two ankle joints. The
handler reported `unweighted_vertices: 0` and a "joints own no vertices"
warning. A caller reading only the gate number shipped it.

The geodesic voxel bind is the separate `geomBind` command, run on an
existing skinCluster. Maya's own `createSkinCluster.mel` binds with
`bindMethod 0`, then `geomBind -bm 3 -gvp <res> <check> -fo <falloff> -mi <n>`.
skinCluster has no `geodesicVoxelParams` flag (its flags: bindMethod,
heatmapFalloff, smoothWeights, smoothWeightsMaxIterations).

## Why it matters — the consumer-side number

Two legs, radius 12 cm, 4 cm apart, one mesh, each with its own 3-joint chain
under a pelvis. Left hip bent 45°:

| bind | left-leg verts carrying right-leg weight | right leg dragged |
|---|---|---|
| closestDistance | 159 / 208, max 0.26, mean 0.06 | 18.6 cm, 207/208 verts > 1 mm |
| `skinCluster(bindMethod=3)` alone (the old route) | 208 / 208 at 0.5 | 25.4 cm — worse |
| closestDistance + geomBind 256 | 0 | 0.0 mm |

At a 20 cm gap closestDistance still moves the other leg 1.85 cm on 158
vertices. Straight-line distance reaches across any gap; geodesic distance
runs through the volume and stops at the skin.

## geomBind, measured

- Resolution (416 verts): 64 → 0.14 s, 128 → 0.17 s, **256 → 0.66 s**
  (UI default), 512 → 2.45 s, 1024 → 28.5 s. Bleed 0 at every resolution.
  19 802-vert sphere 1.4 s at 256.
- Falloff: omitting it is 0.2 (the UI default). 0.0 spreads to 4
  influences on 286 verts; 1.0 narrows to 2 on 305. Blend sharpness.
- `maxInfluences` 1/4/8 honoured; the method itself lands ≤3 here.
- Identical table whether the skinCluster was bound bm 0 or bm 3 first.
- Handles an open pipe (caps deleted, 40 boundary edges), two shells, and
  two self-intersecting united cubes (1.6 s).
- Leaves a `geomBind1` node (falloff, maxInfluences, gvResolution,
  gvPostVoxelCheck) wired to `skin.geomBind` and the bindPose; in the skin's
  history, not the mesh's; deleting it does not touch weights; export_fbx is
  unaffected; one undo removes it with the skin.
- **Silent failure:** a flat polyPlane gets the degenerate table from
  geomBind with no error, no stderr, and the node returned. Boundary edges
  are not the discriminator (the open pipe binds); zero volume is.
- **Needs a GL context:** a headless mayapy raises "Unable to create an
  offscreen OpenGL buffer. Failed computing weights." from geomBind. Found
  by the mayapy test, not the probe.

## heatMap, decided

mayapy refuses it outright (same GL error). In the GUI Maya it works on the
closed tube (2.5 s), two closed shells (3.5 s), self-intersecting shells
(3.2 s), the 19.8k sphere (3.9 s) and the open pipe (2.65 s). #797's >6 min
hang was the flat polyPlane — the same zero-volume class that degenerates
geodesic. Kept, with the flat-mesh refusal. A chain's leaf joint owns 0
vertices under heatMap (no bone segment) — the existing warning names it.

## What changed

- `maya_plugin/handlers/rigging.py`: geodesicVoxel = closestDistance bind,
  then `geomBind(bindMethod=3, geodesicVoxelParams=(256, True), falloff=0.2,
  maxInfluences=max_influences)`. Constants `GEODESIC_RESOLUTION`,
  `GEODESIC_FALLOFF`, `VOLUME_METHODS`. Pre-check: a mesh flat along a local
  axis refuses heatMap and geodesicVoxel before the checkpoint. Post-check:
  a geodesic table matching the degenerate signature is refused and unbound
  (skin + geomBind node deleted). A geomBind exception unbinds and refuses
  with Maya's text.
- `maya_plugin/handlers/rigmath.py`: `sole_owner` (the signature; a single
  influence owning everything is legitimate) and `flat_axis` (extent ≤ 1e-6
  of the largest; 1 mm on 2 m is a shell).
- `tests/test_rigging.py` FakeCmds: `geomBind`, `polyEvaluate(boundingBox)`,
  `skinCluster(edit, unbind)`; `TestBindSkinMethods` (7 tests).
  `tests/test_rigmath.py`: `TestSoleOwner`, `TestFlatAxis`.
  `tests/test_handlers_mayapy.py`: geodesic under mayapy asserts the GL
  refusal leaves nothing bound; flat sheet refused for both methods.
- `docs/protocol.md` bind_skin prose; `src/maya_mcp/server.py` method
  description.
- Gate `evals/geodesic_voxel_live.py`: 15/15 on agent 9878 (fresh launch
  after the edit). Suite 3112 / 0 / 0. mayapy BindSkinInMaya 8/8.
- `evals/live_coverage_audit.py` re-run: bind_skin's method row is covered.

## Left open

- Resolution and falloff are fixed at Maya's UI defaults by decision
  (2026-09-04); a param would need protocol rows and the #767 contract.
- The flat pre-check reads the local-space bbox: a sheet built diagonally in
  its own space passes it and is caught only by the geodesic post-check
  (heatMap has no post-check — it would hang). Not measured.
- `smoothWeights` on skinCluster and `heatmapFalloff` are untouched.
