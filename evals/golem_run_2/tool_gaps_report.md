# #601 — what building an articulated golem found

31 build steps, 29 chunks, **zero escapes for geometry** and one escape for
artifacts. The model is the receipt; the findings are the product.

Full evidence, with the numbers, is in [`tool_ledger.md`](tool_ledger.md). This
file ranks what came out of it.

---

## 1. `setup_lighting`'s dome lit nothing at all — FIXED, `aa91c0f`

The worst defect this run found, and it had been shipping silently.

`_build_dome` used `cmds.createNode("aiSkyDomeLight")`, which builds the node
but never wires it into Maya's lighting network. The dome drew as **background**
and illuminated nothing. A plain 50%-grey probe sphere rendered **pure black**
while the dome's own sky blew out behind it — at intensity 1.0 and at 4.0 alike,
so never a scaling problem.

What makes it severe is what the preset is *for*. Its own docstring says a
three-point rig physically cannot show a metal, that metalness 1.0 renders black
there, and that only an environment can fix it. **So the tool's answer to its own
measured failure was inert from the day it was written, and every metallic
material ever judged through `environment` or `hdri` was judged unlit.**

Fixed by building it with `cmds.shadingNode(..., asLight=True)`, two regression
tests, 833 green, gated live.

Four hypotheses died first and are recorded so nobody repeats them: **not** the
ramp on `.color`, **not** `defaultLightSet`, **not** the `lightList` connection,
**not** `render_scene`'s `relight`. Each produced a byte-identical frame.

## 2. `boolean_op` silently discards pivot, parent AND UVs

Three losses on one call, all under `watertight: true` and `warnings: []`.

| Lost | Measured |
|---|---|
| Pivot | `golem_L_shoulder` in at [0.9, 3.85, 0.1], out at its own bbox centre |
| Parent | result created as a **root object**, out of the 29-chunk tree |
| UVs | fresh **0–1** UVs where every sibling sat inside atlas patch 0 |

The UV loss is the one that would have shipped: nothing looks wrong until the
material goes on, and then one chunk samples all sixteen patches.

`array` mirror, in the same scene, preserves the pivot *and* the UVs, and
`bevel_edges` preserves the pivot. So this is a property of one operation, not an
inevitable consequence of rebuilding a mesh — `boolean_op` **could** carry them.
Either carry them, or say so.

## 3. No image tool can write to disk

`render_scene`, `render_sheet`, `capture_viewport` and `capture_turntable` all
return the image as the call's value and clean up after themselves. A plan whose
deliverable is "write every image under `evals/`" **cannot be followed through
the tool surface**. This run's hero stills required escaping to `execute_python`.

A `path` parameter on the four image tools closes it outright. Cheapest
high-value fix on this list.

## 4. A dome in the scene makes framing lie, in two different tools

- `render_scene` with no `target`: camera to **5294 units** from a 5 m subject, a
  photograph of the sky. The "a render of nothing is a valid image" guard counts
  `opaque_px`, and a dome fills the frame — it reported 409600/409600.
- `capture_viewport` with `frame_all`: camera to **5498 units**, a **blank white
  image**. And it has no `target`, so the only escape is `isolate`.

Both are confident, successful-looking pictures of nothing. Framing should
exclude light shapes, exactly as #618 taught `isolate` to.

## 5. `deform`'s `bend` is inert and reports success — #636, still open

`baked: true`, no warnings, nothing moved. Response is **linear** in curvature,
about 0.4% of mesh height per unit: 0.35→0.0015, 8.0→0.0334. Not placement, not
the non-uniform scale, and **not the MCP tool** — raw `cmds.nonLinear` gives the
same. Cannot deliver a hunch at any value the parameter accepts.

Alongside it: `sculpt_ops soft_move` **silently misses** a mesh wider than its
radius. `applied: 1`, no warning, nothing moved. The chest girdle went through
Tasks 4–6 green on every headless number and was the one chunk carrying no
shaping at all — caught by a *capture*, not by a measurement.

## 6. `render_sheet` doesn't know its subjects form a tree

`isolate` keeps the subject's descendants, so on a parented rig **14 of 29 cells**
came back as sub-assemblies — `golem_C_pelvis` rendered the entire golem. Only
the 15 leaf chunks were right.

Also: 29 Arnold cells at 256 px / 1 sample exceeded the 600 s limit, and the
timeout hint says to pass a `timeout_s` the tool does not accept. The fast
alternative, `hw2`, cannot show a dome at all.

## 7. Naming: two calls that cannot ask for the name they want

- `boolean_op`'s `new_name` **collides with an input the call itself consumes**.
  Asking for `golem_L_shoulder` back returns `golem_L_shoulder_001`, because the
  name is reserved before the inputs are deleted. Proven by contrast: the pelvis
  call asked for a name that was free at reserve time and got it clean.
- `array` mirror's `name_prefix` is a **prefix, not a name**. All 11 mirrors
  returned `golem_R_<part>_1` with nothing to collide with. Cost 11 `rename`
  calls and doubled the task from 11 tool calls to 22. Mirror is the one mode
  where the copy count is always exactly one and the caller always knows the name.

## 8. `uv_atlas` refuses the integer `patch` its own docs describe

`patch: 0` → `patch must be an integer index or [col, row], got '0'`. It arrives
as a *string*; the `Field` carries no type, so nothing coerces it, and the error
names the form it just rejected. `[0, 0]` works.

## 9. Emission per chunk and a shared atlas material pull against each other

`assign_material` *replaces* the shader, so using it for per-chunk emission
strips the maps. `assign_pbr` with the same `maps` plus a distinct `name` and
`params={"emission": …}` serves both, at one shader per distinct value. Six
glowing chunks cost five shaders; final scene is 10 shading groups over 33
objects against 1 if emission were uniform. Works, but it is a workaround the
tool descriptions do not point at.

---

## What worked, stated because a benchmark that only complains is not measuring

- **#603's `pivots` map is the reason this rig exists.** All 18 chunks came back
  `combined: false` — precisely the case that used to get no pivot treatment at
  all. Without it, 18 centroid pivots and no rig.
- **The rig is rigid, measured.** Rotating `golem_L_upperarm` 40° about its
  shoulder pivot preserved every descendant's distance from that pivot to six
  decimals — 0.6, 1.19236, 1.875, 2.54627, 2.875 unchanged; fist travelled
  1.9666; shoulder ball did not move.
- **`array` mirror carries pivots and UVs.** The plan asserted the opposite and
  budgeted 11 calls to fix what was already correct.
- **Claim 2 is answered, against my own prediction: the kit's maps DO read on
  creature shapes.** At the city's own density (`world_scale` 9.0, 113.78 px/m,
  matching `demigol_structures/manifest.json`) masonry courses read across the
  chest and plate banding down the limbs. It looks built of the place.
- **Claim 4 holds.** 29 chunks, one `render_sheet` call, no blank cells, against
  41 round-trips — with the caveats in §6.
- **`etch_text` is exact.** I measured it wrong twice and nearly filed a false
  bug; the ledger records how, because both wrong numbers agreed with each other.

## The lesson that cost the most

Three times this run a plausible number meant something other than it looked
like: a min over a whole mesh is not a depth; `exactWorldBoundingBox` on a
transform includes descendants, so 14 chunks "moved" when none had; and
`opaque_px` is not a subject-present check when a dome is in frame.

And the counterpart: **the chest girdle passed every headless check while reading
as a plank**, and only a capture found it. Numbers and pictures each catch what
the other cannot. Anything gated on one alone is gated on half.
