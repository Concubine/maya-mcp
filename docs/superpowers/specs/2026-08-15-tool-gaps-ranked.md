# maya-mcp — next tools, ranked by price vs benefit

Written 2026-08-15, immediately after the Demigol kit + hero revision-2 runs
(redmine #595). **Every item below is evidence from a real run, not speculation** —
that is this project's rule for what gets built.

Context: those runs produced 41 kit pieces and 4 hero buildings (2,034 chunks,
94,344 tris) and added two tools (`maya_combine`, `maya_uv_atlas` with a
`world_scale` density mode). What follows is what those runs *wished* existed.

---

## Tier 1 — cheap, and pays back immediately

### 1. Deployed-plugin staleness handshake
**Cost: very low.** **Benefit: high.**

The live Maya imports `Documents/maya/scripts/maya_plugin`, not the repo. The M2.4
plan records this costing *hours* when the deployed copy was stale by ~8 tasks. It
bit again this session: the first live gate failed with `ImportError: cannot import
name 'combine'` because two new modules had never been deployed.

Add the repo git hash to `ping`'s response (written at install time), and have
`live_call` / the eval harness warn loudly when it differs from the working tree.
A one-line mismatch warning replaces a class of "green result that means nothing".

### 2. `assign_pbr` — wire a three-map material in one call
**Cost: low.** **Benefit: high.**

Hand-wired the same stack twice this session (kit, then heroes): `standardSurface` +
three `file` nodes + `place2dTexture` + `reverse` (smoothness→roughness) + `bump2d`.
Two live-only traps are now known and should be *encoded rather than remembered*:

- `bump2d.bumpValue` is a **single float** — connecting `file.outColor` is rejected
  outright. It takes `outAlpha`, and with `bumpInterp = 1` Maya traces back through
  that connection for the RGB.
- normal and mask are **data, not colour**: they need `colorSpace = "Raw"` and
  `ignoreColorSpaceFileRules`, or Maya bends the normals and shifts every roughness.

`assign_material` already exists but stops at scalar params. Every art run from here
is PBR, so this is the highest-frequency boilerplate left.

### 3. `execute_python` truncates structured results silently
**Cost: low.** **Benefit: medium-high.** *(A bug, not a tool.)*

A check returning 37 rows came back as a **truncated, unparseable string** — the
failure surfaced as a `SyntaxError` from `ast.literal_eval` on the caller's side,
which is a confusing place to learn about a size cap. Either raise the cap for
structured results, or set an explicit `truncated: true` flag so the caller can act.
Silent truncation of a measurement is the same failure class as a blank render.

---

## Tier 2 — moderate cost, clear payoff

### 4. `maya_assemble` — batch create + UV + combine
**Cost: medium.** **Benefit: high.**

This is the single most hand-rolled loop in the codebase, now written twice:

```
for each part:  polyCube -> (optional flare) -> move -> uv_atlas -> collect
then:           combine into one object, assign material
```

The hero run drove **~8,000 boxes** through it inside one `execute_python`, which
means the *tool surface* was bypassed for the largest authoring job to date. One
call taking a list of `{pos, dim, patch, taper}` would put that work back on tools,
make it measurable, and cut thousands of round-trips.

Note this is exactly how `maya_array` earned its place: N hand-typed rows became one
call.

### 5. Batch render / contact sheet in one call
**Cost: medium.** **Benefit: medium.**

The kit contact sheet is 41 separate `render_scene` round-trips, each isolating one
object, composited client-side with `images.contact_sheet`. `capture_turntable`
already composites server-side, so the pattern exists. Mostly a wall-clock win
(minutes per run), not a capability win — rank accordingly.

### 6. Environment / skydome light
**Cost: low-medium.** **Benefit: medium.**

Carried from the M2.5 seeds and still unbuilt: `metalness = 1.0` renders **black** in
a three-point rig, because a full metal has no diffuse response and there is nothing
to reflect. The kit now ships genuinely metallic steel, so this is no longer
hypothetical — the steel pieces are being judged in a rig that cannot show them
properly.

---

## Tier 3 — expensive; wait for a run that proves the need

### 7. Curve construction (revolve / loft / sweep)
**Cost: high.** **Benefit: currently low.**

Deferred at M2.4 for a good reason that still holds: curves add a **new object type**
that `get_scene_graph`, `get_object_info`, the ledger and mesh cleanup all currently
assume is a mesh. That is a wide blast radius.

And the demand is weaker than it looks. Both revision-2 deliveries list "no curves"
as their remaining gap — but a kit piece is capped at **120 triangles** and the worst
is already 96, so a cylinder segment is barely affordable. Curves are a *hero* and
*character* feature, not a kit one. Build it when a run is actually blocked by it,
not because two READMEs mention it.

---

## Explicitly NOT gaps — do not build these

- **Procedural texture authoring.** The 4096² albedo/normal/mask atlas was generated
  in numpy + PIL and handed to Maya as file paths. That is the right division of
  labour; Maya is a poor place to author procedural textures, and `apply_texture_recipe`
  already covers the in-Maya cases.
- **Measurement / inspection.** `get_object_info` + `meshcheck.mesh_stats` already
  return tris, verts, boundary edges, non-manifold edges and watertightness. The old
  "measure tool" seed is effectively closed.
- **Per-project validation rules.** Both runs validate against the *Demigol* contract
  (cell lattice, outset allowance, name parsing). That belongs in the eval scripts as
  shared helpers, not in the MCP surface.

---

## The lesson worth carrying, independent of any tool

Three gate failures this session were **my own rules going stale**, not code defects:
a tiling check still asserting revision 1's "nothing may leave the cell", a
watertight check using per-chunk Euler on box-built chunks, and a pivot check
comparing against the bounding-box centre (which only coincides with the chunk
centre while nothing oversails).

When a contract changes, **the gates encode the old contract** and will keep passing
or failing for the wrong reason. Re-read the checks before trusting them.

And the recurring one: a fake that agrees with the handler proves nothing. The
`uv_atlas` live gate caught `polyEvaluate(boundingBoxComponent2d)` returning zeros on
a shape — the fake had implemented the same wrong flag. It now lies exactly the way
Maya lies.
