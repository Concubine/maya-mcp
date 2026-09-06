# Tool friction — third pass (armour, scars, face)

For the maya-mcp developer. Written 2026-09-06 by the Claude session that did the
armour/scar/face pass on the kethran, as a **user of the tools**, not a reader of the
source. Findings are numbered A-1… to keep them distinct from F-* (report 1) and N-*
(report 2).

Severity: **P1** = cost me the session or destroyed work · **P2** = cost me repeated
round-trips · **P3** = cosmetic or documentation.

| | Finding | Sev |
|---|---|---|
| A-1 | Two concurrent tool calls **killed the Maya process** | **P1** |
| A-2 | `frame_all: false` ignored on `current`, and the error **compounds** every call | **P2** |
| A-3 | Viewport state **leaks between angles and between calls** | **P2** |
| A-4 | `sculpt_ops` cannot author a **stroke** — everything is a radial blob | **P2** |
| A-5 | `bake_mesh_maps` `distinct_values: 2` is still false (actual 256) | **P2** |
| A-6 | `curvature_radius` default is documented for metre scale; this scene is cm | **P2** |
| A-7 | `combine` drops the parent; `boolean_op` carries it | **P2** |
| A-8 | No batch route for a plain material on N meshes | **P3** |
| A-9 | `capture_turntable` renders on **black**; `capture_viewport` on white | **P3** |
| A-10 | `apply_surface_detail` still lists the `p2d` node 18× | **P3** |

---

## A-1 — Two concurrent tool calls killed Maya outright · **P1**

I sent `maya_checkpoint` and `maya_capture_viewport` **in the same message** (the
harness encourages batching independent calls). Both failed:

```
maya_checkpoint:      connection to the Maya plugin failed mid-request
                      ([WinError 10054] An existing connection was forcibly closed…)
maya_capture_viewport: Could not reach the Maya plugin at 127.0.0.1:9879.
```

`netstat` showed nothing on 9879 and `tasklist /FI "PID eq 35716"` returned *No tasks*.
**The Maya process was gone.** I had to relaunch and re-open the scene.

Every call before this was sequential and fine; this was the first parallel pair. I did
not retry the experiment — I could not afford to lose the model twice — so treat this as
strong circumstantial evidence, not a controlled repro.

**Ask:** the plugin should serialise or refuse a second concurrent request, not die. A
`BusyError` would have cost me nothing. As it stands, an agent following the ordinary
"batch independent calls" guidance can destroy a session's unsaved work. If serialising
is hard, please say so in the server description so agents know to keep calls sequential.

## A-2 — `frame_all: false` is ignored on `current`, and the error compounds · **P2**

`maya_set_camera(camera="headCam", position=[-140,172,322], …)` then
`maya_capture_viewport(angles=["current"], frame_all=False)`.

The docstring says `'current' uses the active camera unchanged`. Observed positions of
`|headCam|` across three successive captures, with `frame_all: false` every time and
**no `set_camera` between them**:

| call | angles | reported camera position |
|---|---|---|
| 1 | `["current","side"]` | `[-158, 188, 312]` ✓ preserved |
| 2 | `["current","front"]`, `buffer:"ssao"` | `[-816, 388, 828]` ✗ |
| 3 | `["current"]` | `[-2522, 835, 2568]` ✗ |

The displacement **compounds** — each call pushes the camera ~3× further out. That is
the signature of framing computing a scene bounding box that **includes camera
transforms**: the camera flies out to frame itself, which enlarges the box, which flies
it further out next time. (Memory of #772-era work says lights were excluded from
framing; cameras appear not to be.)

Two separate bugs here: `frame_all: false` not being honoured at all on `current`, and
cameras being inside the framing bbox.

**Workaround I used:** abandoned `current` entirely and framed with
`target: ["|kethran|eyes"]` — real objects near the region I wanted. That worked well
and is arguably the better API anyway.

**Ask:** honour `frame_all: false` on `current`; exclude camera transforms from the
framing bbox.

## A-3 — Viewport state leaks between angles and between calls · **P2**

The docstring promises *"Captures are side-effect-free: all viewport state is
restored."* Measured otherwise.

One call, `angles: ["current","side"]`, `wireframe_overlay: false`:

- the **`current`** frame came back with a **cyan wireframe drawn over everything on a
  black background** — at low zoom this reads as a solid cyan silhouette, which is what
  I first mistook for the known VP2 materials-unbound fault;
- the **`side`** frame in the **same call** was correct: no wireframe, white background.

Re-issuing the identical call produced two correct frames. So the bad state was left
behind by the *previous* call (an `ssao` capture that had also mis-framed) and consumed
by the first angle of the next one.

**Ask:** restore panel state per *angle*, not per call, and restore it on the error path
— a capture that reframes or fails is exactly the one that leaves state behind.

I also want to flag this against the brief I was working to, which told me to reshoot
any capture whose **colours** look wrong. That advice made me discard a frame that was
not a colour bug at all. A wrong-coloured frame and a wireframe-leaked frame look
identical at thumbnail size; naming the wireframe case in the result would have saved me
two round-trips.

## A-4 — `sculpt_ops` cannot author a stroke · **P2**

This is the single biggest gap for organic detail work.

Every offered op is **radial**: `soft_move` is a weighted blob, `inflate_region` is a
blob, `displace_noise` is global. There is no way to say *"cut a groove along this
path"*. A scar, a wrinkle, a tendon groove, a lip line, a muscle insertion — all of them
are **strokes**, and all of them have to be faked as a chain of overlapping blobs.

Concretely, this pass:

- lip line: 12 ops
- eyelids: 12 ops
- rakes: 15 ops
- flank/muzzle scars: 15 ops
- new haunch scars: 16 ops

…against a **20-op-per-call cap**, so several features had to be split across calls, and
each chain needed a separate `maya_execute_python` round-trip first just to compute
per-point surface normals (see below).

Worse, a chain of blobs does not look like a stroke: it beads. I ended up building the
scars in *texture* space instead, where I could rasterise a real line.

**Ask:** a `stroke` op — `{op:"stroke", path:[[x,y,z]…], radius, depth, profile:"v"|"u"|"round"}`
— that walks the path, projects to the surface and applies a swept falloff. This one op
would replace most of what I did with `execute_python` in this session.

**Related, same root cause:** there is still no structured way to find a point *on* the
surface (F-* in report 1, still true). `soft_move` refuses when the centre is farther
than `radius` from the mesh, so every op needs a prior `execute_python` to fetch
`MFnMesh.getPoints`/`getVertexNormals` and snap. And snapping a guessed 3D polyline is
itself unreliable — my hand-drawn strokes landed **up to 23 cm off the surface**, and
the resulting "line" scattered into unrelated points. What finally worked was walking
vertex-to-vertex along mesh connectivity. That is a general primitive the toolkit could
own.

## A-5 — `bake_mesh_maps` `distinct_values: 2` is still false · **P2**

Reported for `|armor`:

```json
"stats": {"pixel_count":1048576, "distinct_values":2, "non_uniform":true, "blank":false}
```

Measured on the written PNGs with PIL:

| file | reported | actual distinct | min | max | mean |
|---|---|---|---|---|---|
| `armor_ao.png` | 2 | **256** | 0 | 255 | 121.5 |
| `armor_curvature.png` | 2 | **256** | 0 | 255 | 50.7 |

Second independent reproduction (first was in report 2). The statistic is the one number
a caller uses to decide whether a bake is worth keeping, and it is wrong by two orders of
magnitude. It reads like the histogram is being computed on a 1-bit or palettised view of
the image.

**The good news, and please keep it:** the bake itself was **fast** — a couple of seconds
for two 1024 maps, against the 40-minute hang that cost me a session in report 1. And
`timeout_s` is now a real parameter on this tool. Both of those asks landed.

## A-6 — `curvature_radius`'s default is documented for the wrong scale · **P2**

> `Sampling radius in scene units; defaults to 0.1, which suits metre-scale assets.`

This scene is **centimetres** (the toolkit states the scene unit elsewhere, so it knows),
and the creature is 380 units long. The default is a **1 mm** sampling radius on a 3.8 m
animal — it would have produced a near-empty curvature map. I passed `3.0` instead, but
only because I happened to read the sentence.

**Ask:** either scale the default by the scene's linear unit, or warn when
`curvature_radius` is under some fraction of the mesh's bounding box. A silently useless
map is worse than a refusal, because the next tool (`apply_surface_detail`) *refuses on a
flat mask* and the caller then debugs the wrong tool.

## A-7 — `combine` drops the parent; `boolean_op` carries it · **P2**

`maya_boolean_op` documents that it *"Carries a's pivot, a's parent and a's UV bounds
onto the result"*. `maya_combine` does not, and does not say so:

```
maya_combine(names=[12 plates under |kethran], name="armor") -> {"name": "|armor", …}
```

The result landed at the **world root**, outside the group that holds the rest of the
creature. Nothing warned. If I had not checked the scene graph, the deliverable would
have had an armour set that did not move with the animal.

Re-parenting was clean — `maya_parent` correctly compensated with a local scale of
1.1037 to preserve the world position — but it leaves a non-unit scale on the node that
now has to be frozen before export.

**Ask:** carry `names[0]`'s parent onto the combined result, as `boolean_op` does; or at
minimum warn that the result was reparented to the world.

## A-8 — No batch route for a plain material on N meshes · **P3**

`maya_assign_material` takes `mesh: str` (one). `maya_assign_pbr` takes
`mesh: str | list[str]`. So a **textured** material can be shared across many meshes in
one call, but a **plain** one cannot — the asymmetry is backwards from the common case.

I needed one flat keratin shader on 12 plates. That is 12 calls, or one
`execute_python`. I used `execute_python` (`shadingNode` + `sets(forceElement=…)`),
which is exactly the kind of workaround this report exists to record.

**Ask:** let `assign_material` take a list, same as `assign_pbr`.

## A-9 — `capture_turntable` renders on black; `capture_viewport` on white · **P3**

Same scene, same lighting argument, back to back: `capture_viewport` returns frames on a
**white** background, `capture_turntable` on **pure black**. This asset is a dark brown
animal with dark brown horns, so on the black sheet the horns disappear entirely — my
first read of the sheet was that the horns had been deleted.

The cells are also substantially under-filled: at `n_frames: 8` the subject occupies
maybe a third of each cell's width, with the rest black.

**Ask:** match `capture_viewport`'s background, or expose it. A contact sheet is
specifically the "judge the silhouette" tool, and silhouette judgement is where the
background matters most.

## A-10 — `apply_surface_detail` still lists `p2d` 18× · **P3**

```json
"file_nodes": ["plateKeratin_color_detail",
               "plateKeratin_color_detail_p2d", × 18,
               "armor_height_tex","armor_height_p2d","armor_height_bump"]
```

Verified in report 2 as a reporting duplication rather than a node leak. Unchanged.

---

## Not maya-mcp's fault, but worth knowing if a "make a plate" helper is ever built

The armour technique (duplicate a patch of the target's own faces, extrude into a shell)
is the only thing that made the plates sit *in* the hide rather than on it. Two Maya
behaviours cost me three rebuilds getting there:

- `polyExtrudeFacet(offset=…, keepFacesTogether=True)` offsets **each face
  individually** → a honeycomb of separate cells, not a tapered patch.
- `polyBevel3` on the extruded shell **explodes into shards** where the source patch
  spans a fold in the donor surface.

A `grow_plate(mesh, region, thickness, dome)` command would be a genuinely new capability
— it is the parametric-organic equivalent of `create_curve_form`, for armour, scales,
scutes, callus and bark.

## And one that is Maya, but bites every texture iteration

Maya's file node **caches by path**. Overwriting a PNG in place renders bit-identical
frames (this was N-12 in report 2, rediscovered the hard way here). Every iteration of
the hide albedo needed a *new filename*; it reached `hide_albedo_v10.png` and the height
map `body_height_v7.png` purely because of this.

`render_scene`'s frame stats are what makes it detectable, which is a point in their
favour. The standing suggestion from report 2 still applies: warn when consecutive frames
from the same camera come back bit-identical.

## What worked well — please don't regress it

- **`timeout_s` on `bake_mesh_maps`** landed, and the bake is fast now. Both were asks
  from report 1; both are fixed.
- **`target` on `capture_viewport`** — framing on real objects while keeping the
  surroundings in shot is the right API, and it is what I fell back to when `current`
  betrayed me. The **occlusion warnings** (*"partly hidden behind horns — 4 of 9 sample
  points blocked"*) were genuinely useful and told me to switch angle before I wasted a
  render.
- **`isolate`** on capture is how I found that the left horn still had a machined-disc
  tip and that the scars were landing under the armour. Both were invisible in a normal
  full-scene frame.
- **`render_scene`'s per-frame stats** (`opaque_px`, `distinct_colors`, `mean_luma`,
  `clipped_fraction`) — the honest measure of whether a render is worth looking at.
- **`sculpt_ops`'s auto-checkpoint and its blunt warning** that the three vertex ops are
  not undoable. It says the checkpoint id every time. That is the right amount of
  nagging, and it is the reason I still have this model.
- **`maya_parent` compensating the transform** to preserve world position, and reporting
  the resulting scale so I could see what it had done.
