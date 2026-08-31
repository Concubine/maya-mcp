# maya-mcp wire protocol (v1)

TCP, loopback by default (`127.0.0.1:9877`). One frame = `uint32` big-endian
body length followed by a UTF-8 JSON object. Max frame size: 64 MB.

The single source of truth is [`maya_plugin/protocol.py`](../maya_plugin/protocol.py),
imported by both the MCP server and the Maya plugin.

## Frames

Request (server → plugin):

```jsonc
{ "v": 1, "id": "uuid-hex", "cmd": "capture_viewport", "params": { }, "timeout_s": 30,
  "token": "..." }          // token only when MAYA_MCP_TOKEN is set
```

Success (plugin → server):

```jsonc
{ "v": 1, "id": "uuid-hex", "status": "ok", "result": { }, "elapsed_ms": 412 }
```

Failure — tracebacks are sacred, never truncated:

```jsonc
{ "v": 1, "id": "uuid-hex", "status": "error",
  "error": { "type": "RuntimeError", "message": "...",
             "maya_traceback": "full traceback text",   // unexpected exceptions only
             "hint": "actionable next step when known" } }
```

## Rules

- **One in-flight request at a time.** The client serializes; the plugin's
  dispatcher runs one command at a time on Maya's main thread.
- **Timeouts.** The plugin enforces `timeout_s` per command (max 600 s). On
  timeout it replies with `TimeoutError` and flags the session busy until the
  straggling command finishes; meanwhile new requests get `BusyError`. A late
  result is dropped, never delivered to a different request id.
- **Reconnect.** A client that times out or hits a transport error drops its
  connection and opens a fresh one on the next request.
- **Version.** Requests with `v != 1` are rejected with `ProtocolVersionError`.
- **Auth.** With `MAYA_MCP_TOKEN` set on the plugin, every frame must carry a
  matching `token` (constant-time comparison) or it gets `AuthError` — and the
  connection is closed after the response (no free retry loop for guessing).
  The plugin refuses to bind non-loopback hosts unless `MAYA_MCP_BIND_ANY=1`
  AND a token are set.
- **Inbound cap.** The plugin accepts request frames up to 4 MB (requests never
  carry images; the 64 MB protocol cap applies to responses only). Once a
  frame starts arriving, its remainder must land within 30 s or the connection
  is dropped — idle connections between requests block indefinitely and are fine.
- **Undo.** Every mutating command runs inside one `undoInfo` chunk = one undo
  step. Read-only perception commands (`capture_viewport`) suppress undo
  recording (`stateWithoutFlush`) so their internal churn never lands on the
  undo queue — undo after a capture reverts the last real edit.

## Error types

| type | meaning |
|---|---|
| `ProtocolVersionError` | version mismatch between server and plugin |
| `AuthError` | missing/invalid token |
| `UnknownCommandError` | cmd not registered; hint lists available commands |
| `BusyError` | a straggling command still occupies Maya's main thread |
| `TimeoutError` | command exceeded `timeout_s`; session busy until it finishes |
| `HandlerError` | controlled handler failure with an actionable hint |
| anything else | unexpected exception; `maya_traceback` carries the full story |

## Commands (M0)

| cmd | params | result |
|---|---|---|
| `ping` | `{}` | `{ pong, maya, plugin: {package_dir, digest, stamp, loaded_digest, loaded_stamp, imported_at, restart_required}, process: {pid, host, port, started_at, uptime_s, scene} }` |
| `execute_python` | `{ code, timeout_s?, risky? }` | `{ stdout, stderr, result_repr, traceback, namespace_keys, checkpoint? }` |
| `reset_namespace` | `{}` | `{ reset: true }` |
| `get_scene_graph` | `{ filter?, max_objects?, cursor? }` | `{ objects: [...], total, cursor }` |
| `capture_viewport` | `{ angles?, shading?, wireframe_overlay?, buffer?, isolate?, target?, frame_all?, resolution? }` | `{ images: [{angle, png_b64, blank}], camera_positions: [...], warnings }` |

`ping` answers two questions a caller cannot answer for itself: `plugin` says
which *code* is live (feed it to `version.compare`), `process` says which
*process* is answering — a port is not an identity, and a Maya that lost the
bind race is indistinguishable from yours without a pid (#648). A bind failure
raises `PortInUseError` rather than leaving a Maya running with no listener.

**`plugin` carries two identities, and the difference between them is a
finding** (#604). `digest`/`stamp` describe the files **on disk right now**;
`loaded_digest`/`loaded_stamp` describe what this session **imported**, captured
once at plugin load. A running Maya holds the modules it imported at startup —
`install.py` rewrites the disk and reloads nothing — so in the window between a
deploy and a restart the two diverge, and the disk names exactly the code that
is *not* answering. Judging by disk is how the old handshake read CLEAN against
a stale session while a caller measured the old handlers and attributed the
results to the new branch; the same window made two fresh #640 fixes read as
regressions. `version.compare` therefore judges by `loaded_digest` (falling
back to `digest` for pre-#604 plugins) and has a distinct verdict for the
window: *deployed but not restarted*, whose advice is restart — not the
redeploy that has already run and cannot help. `restart_required` is the same
divergence as a bare boolean, for humans reading a raw ping. Gated live by
`evals/staleness_live.py`, which walks the actual window on a real Maya.

## Commands (M1)

Session safety:

| cmd | params | result |
|---|---|---|
| `checkpoint` | `{ label }` | `{ checkpoint_id, path }` |
| `restore_checkpoint` | `{ checkpoint_id \| path }` | `{ restored, path, pre_restore_checkpoint, pre_restore_path }` |
| `undo` | `{ steps? }` | `{ undone, requested }` |
| `redo` | `{ steps? }` | `{ redone, requested }` |
| `new_scene` | `{ confirm, linear_unit? }` | `{ new_scene: true, pre_checkpoint, pre_checkpoint_path, units }` |
| `open_scene` | `{ path, confirm? }` | `{ opened, pre_checkpoint, pre_checkpoint_path }` |
| `save_scene` | `{ path? }` | `{ path }` |

Checkpoints go to `<dir of the open scene>/checkpoints/`, so a `checkpoint_id`
(`NNN_label`) is unique only inside one directory — and `new_scene`,
`open_scene` and `restore_checkpoint` all change which directory that is. Ids
issued during the session are resolved against where they were actually
written, and every id comes back with its `path`; pass `path` instead of
`checkpoint_id` for an id from an earlier session (#649).

Scene ops:

| cmd | params | result |
|---|---|---|
| `create_primitive` | `{ kind, name, translate?, rotate?, scale?, divisions? \| subdivisions? }` | `{ name, subdivisions, faces, warnings }` |
| `duplicate` | `{ name, new_name, translate?, rotate?, scale? }` | `{ name, warnings }` |
| `transform` | `{ names, translate?, rotate?, scale?, relative? }` | `{ objects: [...], warnings }` |
| `group` | `{ names, group_name }` | `{ name, warnings }` |
| `parent` | `{ child, parent }` | `{ name, warnings }` |
| `rename` | `{ name, new_name }` | `{ name, warnings }` |
| `delete_objects` | `{ names }` | `{ deleted: [...], warnings }` |

### Resolution: `divisions` is a multiplier, `subdivisions` is a count (#669)

`create_primitive` takes **either** of two ways to say how dense the mesh should be, never both — they are different currencies and ranking one over the other silently is the substitution this whole area is about.

* **`divisions`** — the uniform MULTIPLIER on Maya's own defaults. Unchanged, and still the right answer for anything roughly isotropic. Its cost differs wildly per kind: a cube spends it linearly per axis, a sphere or torus multiplies it by 20 on BOTH axes.
* **`subdivisions`** — the LITERAL count per axis, one integer per axis of the kind in hand, in this order:

| kind | axes | minimums |
|---|---|---|
| `cube` | `[width, height, depth]` | 1, 1, 1 |
| `plane` | `[width, depth]` (Maya's "height" flag subdivides Z) | 1, 1 |
| `sphere` | `[around, along]` | 3, 3 |
| `cylinder`, `cone` | `[around, along]` | 3, 1 |
| `torus` | `[ring, tube]` | 3, 3 |
| `prism`, `pyramid` | `[along]` | 1 |
| `octahedron`, `icosahedron` | none — `polyPlatonicSolid` has no subdivision flag, so passing `subdivisions` is **refused** rather than ignored | — |

The reason this exists: `divisions` on a cylinder or cone buys **20 around for every 1 along**. A long thin limb needs rows along its length and almost nothing around it, so the only way to get them was to pay for a circumference no shape needed — measured, 16 rows along a cylinder costs **5122 faces** that way against **194** with a 12-sided tube, and both bend identically (`evals/divisions_live.py`).

**The minimums are enforced, and they are not decoration.** MEASURED on this Maya: given a `subdivisionsAxis` below 3, `polySphere`/`polyCylinder`/`polyCone`/`polyTorus` neither clamp nor raise — they silently substitute their own **default of 20**. A caller asking for a 2-sided tube would get a 20-sided one and be told nothing, so the tool refuses instead.

The result reports **`subdivisions`** (the per-axis counts as built) and **`faces`**, because the multiplier's per-kind meaning is invisible from the call site: `divisions: 4` on a cylinder buys 80 around and 4 along, and nothing else in the result said so.

The face projection those counts are budgeted against was **wrong for cylinder and cone** until #669: it charged a fan of triangles per end cap, where Maya closes each with a single n-gon, so a default cylinder was predicted at 60 faces and builds 22. It survived because the only real-Maya face-count assertions covered the platonic solids, prism and pyramid — the mayapy suite now checks every kind.

`assemble` parts take the same two keys with the same meanings and the same refusals.

Modeling and sculpting:

| cmd | params | result |
|---|---|---|
| `boolean_op` | `{ a, b, op, new_name }` | `{ name, tris, watertight, parent, pivot, uv_bounds, warnings, carved_text? }` |
| `etch_text` | `{ mesh, text, face, width?, depth?, font?, mirror?, rotate_deg?, new_name? }` | `{ name, tris, watertight, parent, pivot, uv_bounds, warnings, carved_text }` |
| `sculpt_ops` | `{ mesh, ops: [...] }` | `{ applied, ops: [...], tris, warnings, checkpoint_id? }` |
| `deform` | `{ mesh, deformer, params?, delete_history_after? }` | `{ deformer_nodes: [...], baked, warnings, max_displacement }` |
| `remesh_retopo` | `{ mesh, target_polycount, keep_original? }` | `{ name, tris, method, warnings }` |
| `mesh_cleanup` | `{ mesh, merge_verts_threshold?, delete_history?, freeze_transforms?, conform_normals? }` | `{ name, before, after, warnings }` |

A boolean builds a **new object**, so everything that is not vertices has to be carried across deliberately (#638). `boolean_op` and `etch_text` take three things off `a` before it is consumed and put them back on the result, reporting each one:

* **`parent`** — the result goes back under `a`'s parent, so cutting a socket into a rigged chunk does not drop it out of the hierarchy. The reparent happens *before* construction history is deleted, because that delete garbage-collects the consumed operands and takes an empty parent group with them. If the parent carries a scale or rotation, the result would inherit its inverse as a compensating transform — the node state the export gate refuses (#629) — so that is frozen into the vertices instead, with a warning saying so.
* **`pivot`** — `a`'s world-space pivot, not the new mesh's bounding-box centre. This is what makes `boolean_op` safe to use after `transform`'s `pivot` or `assemble`'s `pivots` (#603).
* **`uv_bounds`** — `[u_min, v_min, u_max, v_max]` of the result. `polyCBoolOp` keeps **each operand's own** UV layout, so the faces the cutter contributes arrive carrying the cutter's UVs: on an atlas-packed chunk cut with a default-UV cutter, the new face samples the whole atlas instead of its own patch, and nothing looks wrong until the material goes on. `b`'s UVs are folded into `a`'s bounds before the boolean runs (folding first, because once merged there is no reliable way to tell the two operands' UVs apart). `uv_bounds` is `null` when the result has no UVs at all.

**`new_name` may be `a`'s or `b`'s own name** (#640). Both operands are consumed, so "cut a socket into X and have the result still be called X" is the natural request — and it used to be inexpressible, returning `X_001`, because the name was reserved while Maya still held it: `polyCBoolOp` leaves both operands as emptied transforms until the construction-history delete reaps them. The result is therefore created under a staged name and claims the requested one immediately after that delete, which is the only moment it is free. A name held by an object this call does **not** consume is never stolen: the staged name stays and `warnings` says which object holds it.

`deform`'s `deformer` is one of `bend`, `squash`, `twist`, `flare`, `sine`, `wave` (all `cmds.nonLinear` types), plus `sculpt` and `lattice`. `flare`, `sine` and `wave` are new in M2.4. Each type whitelists its own `params` keys (they land as attributes on the deformer node under exactly those names); `wave` is the one exception with no `lowBound`/`highBound` at all, since it bounds radially via `minRadius`/`maxRadius` instead.

**Angle params are degrees** (`bend`'s `curvature`, `twist`'s `startAngle`/`endAngle`). Those attributes are angle-typed, and `cmds.setAttr` reads an angle in whatever unit the scene's UI is set to — so `deform` converts from degrees into that unit and the number means the same thing in every scene. `curvature: 0.35` is a third of a degree, which is what made `bend` look inert (#636); a visible hunch is 20–60.

`max_displacement` is how far the furthest vertex actually moved, in scene units, measured from the vertices before and after (not from the bounding box, which over-reports rotated meshes). When it falls below 1% of the mesh's own bounding-box diagonal, `warnings` carries one line naming the measurement and the usual reason that deformer type ends up inert. `lattice` is exempt: a freshly built lattice deforms nothing until its points are moved, so `max_displacement: 0.0` is the correct result there.

Viewport and camera:

| cmd | params | result |
|---|---|---|
| `set_viewport` | `{ show_grid?, show_light_icons?, show_camera_icons?, show_locators?, show_manipulators?, show_texture_placements?, wireframe_on_shaded?, display_lights? }` | `{ panel, show_grid, ..., camera }` |
| `set_camera` | `{ camera?, position?, look_at?, focal_length?, set_active? }` | `{ name, position, rotation, warnings }` |

## Commands (M2)

Perception:

| cmd | params | result |
|---|---|---|
| `get_object_info` | `{ name, include? }` | `{ name, transform?, mesh_stats?, uvs?, shading?, history? }` |
| `capture_turntable` | `{ target?, n_frames?, resolution?, shading?, lighting?, shadows? }` | `{ images: [{index, azimuth, png_b64, blank}], n_frames, warnings }` |

Lighting and materials:

| cmd | params | result |
|---|---|---|
| `setup_lighting` | `{ preset, intensity?, hdri_path?, replace_existing? }` | `{ preset, lights: [...], removed: [...], checkpoint_id?, warnings }` |
| `assign_material` | `{ mesh, shader?, params?, name? }` | `{ mesh, material, shading_group, shader, warnings }` |

`assign_material` **refuses a top-level param it does not read** (#764), naming the key that was meant: `material` is called `name` here. It is the result field that gets called `material`, which is exactly why callers reached for it as the input key — and it was silently ignored, so the material quietly got the mesh-derived default name instead. Eleven tests in this repo passed `material=`; every one created a differently-named material than it believed it was creating, and every one passed, because they read the name back out of the result rather than pinning it. An unread key does not fail — it succeeds and does something else.

Note that this is currently the **only** command that checks its top-level keys; the MCP tool wrappers type their parameters, so an MCP consumer cannot send an unknown one, but a direct TCP caller (an eval, an art script) can. See the follow-up ticket for the general sweep.
| `apply_texture_recipe` | `{ mesh, recipe, params?, slot? }` | `{ mesh, recipe, slot, nodes: [...], warnings }` |

## Commands (M2.2)

| cmd | params | result |
|---|---|---|
| `render_scene` | `{ angles?, renderer?, resolution?, isolate?, target?, zoom?, relight?, samples?, fallback_light? }` | `{ images: [{angle, png_b64}], camera_positions: [{angle, label, position, rotation, camera, near_clip}], renderer, samples, fallback_light, warnings }` |

### A frame that draws nothing says so (#765)

Every captured frame carries **`blank`**, and a blank one is named in **`warnings`**. The frame is still returned — capturing an empty scene is a legal request — but it is never handed back as a plain success again.

The defect this closes: `capture_viewport` returned frames in which every pixel was transparent. Real RGB, zero alpha, so any viewer composited them to flat white while the tool reported success. A #669 live gate passed with one of those white squares in it, under its own instruction to "now LOOK at this".

**Pixel variety cannot detect it** — the broken frames carried 13 distinct pixel values against 15 for a correct capture of a cube. Opaque coverage can: **0 against 18872**. That is the same measure `render_scene`'s blank guard has always used; `capture_viewport` simply never had one. `blank` is `null` when the frame could not be measured at all, and that is reported too — "I did not check" and "I checked and it is fine" must not look alike.

**The cause, and the other half of the fix.** A Maya whose main window has **never been shown** draws nothing into an offscreen playblast — and every agent-launched Maya starts that way. `offScreen=True` does not save it and neither does the `M3dView.readColorBuffer` fallback. The discriminator is `isVisible()`, not `isMinimized()`: the blind session measured `minimized=False, visible=False`, which is why chasing minimisation led nowhere. One `show()` fixes it permanently for that process, and minimising the window again afterwards does not break it, because the surface stays valid once created.

So `capture_viewport` and `capture_turntable` now show an unrealized window before capturing, and **say that they did** — making a window appear is a visible side effect, and a capture's contract is that it has none. It only ever fires on a window nobody is looking at: an interactive session has a visible window by definition.

The blank report remains the backstop for every other cause, including ones nobody has met yet.

`render_scene` is the second eye. `capture_viewport` reads the VP2 viewport, so
it is fast, needs a mapped window, and draws transmission as plain transparency -
a gem and a plastic block look alike. `render_scene` goes through the render
pipeline: seconds per frame, no window required (it works on an agent-launched
Maya, where every playblast comes back fully transparent), and under `arnold` it
refracts for real.

Two details worth knowing before calling it:

- `isolate` here **hides** the non-targets rather than isolating a panel, since
  panel isolation is invisible to a renderer. Visibility is restored afterwards,
  along with the render globals the call had to change.
- The MCP tool wrapping this command reports `opaque_px`, `total_px` and
  `distinct_colors` per frame, and errors when every frame is blank. A render of
  an empty or unlit scene is a valid PNG with a success status, so blankness has
  to be measured rather than assumed away.

| cmd | params | result |
|---|---|---|
| `render_sheet` | `{ subjects, angle?, renderer?, resolution?, isolate?, samples? }` | `{ images: [{angle, label, png_b64}], camera_positions: [...], renderer, samples, fallback_light, warnings }` |

`render_sheet` is one frame per subject sharing one renderer, camera and set of
render globals; the server composites the cells into a single sheet image. It is
`render_scene`'s loop with a different list, so they share the same
implementation.

**Its cells are siblings, and that changes what `isolate` means** (#640).
`render_scene`'s `isolate` keeps the target's whole subtree, which is right when
you isolate an assembly to look at the assembly. In a sheet the other subjects
are *rival cells*, not content — so on a parented rig 14 of 29 cells came back
rendering sub-assemblies, `golem_C_pelvis` rendering the entire golem. Each cell
now hides the descendants that are themselves subjects, while descendants that
are **not** cells of their own (a bolt, a trim strip) stay in frame, and
`warnings` names every subject that contains another. Framing follows the same
rule: `exactWorldBoundingBox` includes hidden children, so a cell framed on its
subject's transform was still framed on the subtree it had just hidden, leaving
the piece a speck. Sheet cells are framed on what they actually show
(`ignoreInvisible`). `isolate: false` restores the whole-subtree behaviour, since
a caller declining isolation wants the surroundings.

**Timeouts.** Every cell is a full render, so a sheet's cost is per-call, not
per-cell: 29 Arnold cells at 256 px exceeded the old 600 s ceiling, which *was*
the old default — so the timeout error's own advice to "pass a larger timeout_s"
could not be followed twice over. Both render tools now take `timeout_s`
(30 s–1800 s), and the dispatcher's `MAX_TIMEOUT_S` was raised to match. A
timeout never stops the command: Maya runs it to completion on the main thread
and the session stays busy either way, so raising the timeout costs nothing and
timing out costs the images. At the ceiling the error stops recommending a larger
value and says to split the work instead.

**IPR hygiene (#721).** Both `render_scene` and `render_sheet` call
`session.stop_idle_ipr` once the render loop finishes (success or error - it
runs in the `finally`), best-effort and silent when there was nothing to
clean up. An Arnold RenderView (IPR) left open re-renders on every scene
mutation, and a caller renders through `cmds.arnoldRender`/`cmds.render`
directly rather than the IPR view - so any ARV window still open is a leak
from something else, not from this call. What it did, if anything, is
appended to `warnings` (e.g. `"closed the Arnold RenderView window after
rendering - ..."`).

**The near clip plane moves with the framing (#670).** The camera is built by
`cmds.camera()`, whose `nearClipPlane` is an absolute 0.1 scene units — while
the framing distance is `3.3627 × bounding-sphere radius` divided by `zoom`.
One scales with the subject and the other does not, so a close enough framing
walks the subject through a plane that never moved: measured, a zoom of 5 on a
small subject returned a **black frame** (mean luma 0.6 of 255) because the
whole thing sat inside the plane. `render.near_clip_for` therefore derives the
plane from the camera's actual clearance to the framed *box* (half of it,
capped at Maya's own 0.1, floored at the 0.001 `setAttr` refuses to go below —
it raises rather than clamping, which took a whole render down). The cap is
what keeps every framing that already worked byte-identical. The value used is
reported per shot in `camera_positions[].near_clip`.

Two cases no plane can fix are named in `warnings` instead of silently
clamping the caller's `zoom`: the camera landing *inside* the framed box (past
a zoom of about 3.4 the sight-line division puts it there, and what renders is
the inside of the surface — smooth, lit and entirely plausible), and a subject
closer than the 0.001 minimum.

Note that **`hw2` ignores `nearClipPlane` altogether** — forced to a value
deeper than the whole subject, an hw2 frame comes back pixel-identical, so it
cannot see this defect or the fix. `arnold` honours it. Gate this with Arnold
(`evals/near_clip_live.py`).

## Framing, and writing images to disk

**`target` frames; `isolate` hides.** Both `render_scene` and `capture_viewport`
take the pair, and either may be used alone. With neither, the whole scene is
framed — *lights excluded*. That exclusion is the fix for #639: `ls(geometry=True)`
returns light shapes, and a `setup_lighting(preset='environment')` dome measures
±1000 units, so "frame everything" put the camera 5294 units from a 5-unit
subject and returned a photograph of the sky. The blank guard could not catch it
either, because a dome fills the frame with opaque pixels. Lights are identified
by asking Maya (`getClassification(type, satisfies='light')`), not from a list,
so a renderer this code has never heard of is covered too; a caller who names a
light in `target` or `isolate` still gets it framed.

**`path` writes the image.** All four image tools — `maya_capture_viewport`,
`maya_capture_turntable`, `maya_render_scene`, `maya_render_sheet` — take an
optional `path`, and this is a *server-side* parameter: no plugin command sees
it. The rules are `export_fbx`'s, deliberately, so there is one path contract
across the tool surface:

- absolute, ending in `.png`;
- the parent directory must already exist — these tools do not create
  directories they were not asked to create;
- validated **before** Maya is asked for anything, so a typo does not cost a
  render;
- the bytes written are the full-resolution ones the plugin produced, not the
  copy downscaled to what an LLM can read.

A call that makes one image writes exactly the path given. A call that makes
several inserts the label before the extension — `D:/run/hero.png` with angles
`front` and `side` writes `hero_front.png` and `hero_side.png` — and the result
carries a `wrote: [...]` line naming every file, so a manifest can be built from
the call's own report.

**Server-side only, no plugin command:** `maya_load_reference_image` and
`maya_compare_to_reference` (the two remaining M2 tools in `src/maya_mcp/server.py`) never
cross the wire to the plugin. Reference images live in an in-process `ReferenceStore` on the
MCP server itself — held per server run, not per Maya scene, so they survive `new_scene` and
never touch the file on disk. `compare_to_reference` composites its stored reference against a
fresh `capture_viewport` result (a command that IS on the list above) entirely on the server
side. This is why the M2 tool count (7, README's table) and the M2 command count above (5) don't
match — reconcile them by the two lists here, not by assuming a 1:1 tool-to-command mapping.

## Commands (M2.3)

| cmd | params | result |
|---|---|---|
| `uv_atlas` | `{ names, patch?, cols?, rows?, margin?, mode?, projection?, world_scale? }` | `{ meshes: [{name, uv_bounds, inside_patch}], atlas, patch, patch_rect, margin, projection, normalized, world_scale, all_inside, warnings }` |

**`patch` is an integer index or an explicit `[col, row]`** — index 0 is the
top-left patch and the index counts along the row first, the way the atlas image
reads in a viewer. The integer form was documented but *refused* (#640): the MCP
tool typed the parameter as `object`, which constrains nothing and therefore
coerces nothing, so `patch: 0` could arrive as the string `"0"` and the handler
rejected it with an error naming the very form it had just been handed. The schema
now declares a real `int | [int, int]` union, and the handler reads a numeric
string as the integer it is, since the plugin is reachable over raw TCP where
nothing validates at all. Non-numeric text, floats and booleans are still refused.

## Commands (M2.4)

| cmd | params | result |
|---|---|---|
| `array` | `{ name, mode, count?, axis?, center?, angle?, offset?, step_rotate?, step_scale?, pivot?, name_prefix?, group_name? }` | `{ names: [...], mode, group, signed_volume, warnings }` |

**`name_prefix` is a prefix for `radial` and `linear`, and the NAME for `mirror`** (#640). An array of 12 needs 12 distinct names, so those two append `_1`..`_N`. A mirror makes exactly **one** copy, so numbering it was never collision avoidance — it cost the #601 golem run 11 renames, one per mirrored chunk, and nothing in the scene held any of the un-suffixed names. Pass `name_prefix='golem_R_arm'` to a mirror and the copy is called `golem_R_arm`. If that name really is taken, a suffix is added *and* `warnings` says so, because a silent rename is what made the caller check all eleven by hand. Omitting `name_prefix` still gives `<source>_1`: the fallback stem is the source's own name, which is by definition taken.

## Commands (rigging phase 1 / #602)

| cmd | params | result |
|---|---|---|
| `create_skeleton` | `{ joints? \| chain?, chain_prefix?, root_name? }` | `{ root, joints: [{name, position, parent, orient}], warnings }` |
| `bind_skin` | `{ mesh, root, method?, max_influences? }` | `{ mesh, root, skin_cluster, influences, unweighted_vertices, max_influences_exceeded, per_joint, warnings }` |
| `pose_skeleton` | `{ root, rotations, space? }` | `{ applied, joints: [{name, world_position}], max_displacement, displaced_vertices, per_mesh, warnings }` |
| `reset_pose` | `{ root }` | `{ reset, max_displacement, warnings }` |

`create_skeleton` takes either an explicit `joints` hierarchy or the `chain`
shorthand, and validates the whole call before creating anything — a
skeleton that dies half-built is orphan cleanup nobody asked for. Orientation
defaults to Maya's own convention (X aims at the first child, leaves
zeroed); whatever actually landed, default or explicit `orient` override, is
reported per joint in **degrees**, because orientation is where every rig
surprise lives. Joints are created with `segmentScaleCompensate` **off**:
Maya's default exports as FBX `InheritType 2`, which Unity compounds into
100x scale per joint level under the metres declaration (#703), and this
toolset never scales joints, so the flag buys nothing.

`bind_skin`'s `unweighted_vertices` must be `0` for a deliverable bind — a
vertex no joint owns stays behind when the creature moves, and nothing looks
wrong at bind time; `export_fbx(include_skins=true)` gates on the same fact
read back from the file. `per_joint` reports each influence's vertex count
and mean weight, which is how a bind is seen without a viewport. Re-binding
an already-bound mesh is refused — stacked skinClusters make weights
unexplainable — with a hint to unbind via `execute_python` or restore the
pre-bind checkpoint.

`pose_skeleton`'s `rotations` map is per-joint **local euler degrees,
absolute** (not deltas — re-applying a pose is idempotent). This map is the
pose currency phases 3 and 6 reuse: IK bakes into it, a clip keys it.
`max_displacement` is measured from vertices before/after, never bounding
boxes; a near-zero result against the mesh's own size warns, since that
usually means the rotation landed on a joint owning no vertices. Each bound
mesh is also measured alone in `per_mesh` — a combined max can hide one
inert mesh among several.

`reset_pose` restores the skeleton's `dagPose` bind pose. An unbound
skeleton has no bind pose — rotations are zeroed instead (the
`create_skeleton` rest pose) and a warning says so.

## Commands (rigging phase 2 / #668)

| cmd | params | result |
|---|---|---|
| `weight_report` | `{ mesh }` | `{ mesh, skin_cluster, vertices, max_influences, unweighted_vertices, unweighted_sample, max_influences_exceeded, exceeded_sample, max_weight_sum_error, histogram, per_joint, warnings }` |
| `mirror_weights` | `{ mesh, axis?, direction? }` | `{ mesh, skin_cluster, axis, direction, mirrored_vertices, on_plane_vertices, unpaired_vertices, changed_vertices, unweighted_vertices, warnings }` |
| `smooth_weights` | `{ mesh, joints?, iterations? }` | `{ mesh, skin_cluster, iterations, smoothed_vertices, changed_vertices, unweighted_vertices, max_influences_exceeded, warnings }` |
| `set_region_weights` | `{ mesh, joint, faces? \| within_radius_of? + radius?, weight, falloff? }` | `{ mesh, skin_cluster, joint, vertices_in_region, changed_vertices, sole_owner_vertices, unweighted_vertices, max_influences_exceeded, warnings }` |

Binding is one call; *good* weights are the craft, and agents cannot paint —
so the craft is programmatic. All four operate on an existing bind and refuse
an unbound mesh. `weight_report` is the perception tool (a measurement, no
checkpoint): per-joint ownership, offending-vertex samples, the
influence-count histogram, weight-sum drift. The three mutators write the
whole table in one API call, then **re-read it and report from the re-read**:
`changed_vertices` and post-op integrity (`unweighted_vertices`) are
measured, never computed.

`mirror_weights` pairs vertices and influences by reflected position
(`+to-` copies the +axis side onto the −axis side). An asymmetric skeleton —
an off-plane joint with no positional twin — refuses; asymmetric mesh regions
are counted in `unpaired_vertices`, left unchanged, and warned about. Run it
from the bind pose; a posed mesh pairs garbage and warns.

`smooth_weights` is laplacian smoothing over the mesh graph — the fix for
stair-stepped falloff at hips and shoulders. Every smoothed row is pruned
back to the cluster's `max_influences` and renormalized, so smoothing never
breaks the bind's promise to the exporter. `joints` limits smoothing to
vertices those joints hold.

`set_region_weights` blends one joint toward `weight` over a region — face
ids (hard assignment) or a sphere (`within_radius_of` + `radius`, `linear` or
`none` falloff) — while the other influences share the remainder in their
existing proportions. An empty region refuses rather than silently doing
nothing; a vertex the joint solely owns cannot shed weight (nobody to give it
to) and is counted in `sole_owner_vertices`.

## Commands (rigging phase 3 / #671)

| cmd | params | result |
|---|---|---|
| `pose_ik` | `{ root, joint, target, pole?, start?, keep? }` | `{ achieved_position, residual, rotations, chain, pole_used, kept, max_displacement, displaced_vertices, per_mesh, warnings }` |

`pose_ik` solves a joint chain to a world-space `target`, **bakes the result
to plain FK rotations, and deletes the handle** — no persistent IK state
ever exists in the scene. The `rotations` map (per-joint local euler
degrees, long-name keys) is the phase-1 pose currency: feed it straight to
`pose_skeleton`, key it in a phase-6 clip. `residual` is the measured miss
distance — an unreachable target is a number, not a silent stretch, and the
reach shortfall is spelled out in `warnings`.

The chain runs `start..joint`; `start` defaults to two joints above
`joint` — the classic 2-bone limb (hip for an ankle, shoulder for a
wrist). `pole` is a world **position** the knee/elbow should face. When
omitted, a bent chain keeps its own bend plane; a perfectly straight chain
has no plane, so the fold direction is Maya's guess and a warning says so —
pass `pole` to make it deterministic (a straight chain is quietly pre-bent
a few degrees toward the pole so the RP solver can fold at all; the solve
overwrites the nudge).

`keep=false` solves, measures everything, then restores the pose the call
found — a dry-run for "what would this pose take". `achieved_position` and
all displacement numbers are re-read from the scene after the bake, never
taken from the solver's claim.

## Commands (rigging phase 4 / #676)

| cmd | params | result |
|---|---|---|
| `author_physics` | `{ root | chunks, density?, overrides?, exclude? }` | `{ bodies: [{chunk, parent, mass, volume, signed_volume, com, watertight, open_edges, verts, tris, collider, joint}], density, total_volume, warnings }` |

`author_physics` is **read-only** — no checkpoint, nothing in the scene
changes. It MEASURES per-chunk physics-body data: `volume` is the
tetra-summed closed-mesh volume (|signed|; a negative `signed_volume`
means inward winding and warns), `com` is the tetra-weighted SOLID centre
of mass — the sculpt's, never a bbox centre or a vertex average — and
`mass = |volume| × density`, where `density` defaults to 1.0 so mass
numerically equals volume (deliberate: the handoff ships volumes, masses
are abstract, the engine owns the real constant). Non-watertight meshes
are detected by boundary-edge count (`open_edges`) and warned: the volume
reading is then unreliable, and it says so instead of guessing.

`collider` is ONE primitive per body — `box`, `sphere` or `capsule`,
chosen by extent ratios in the mesh's own principal frame (fits are
rotated; `rotation_deg` is the frame's XYZ euler) — with honesty
MEASURED: `volume_ratio` (primitive/|mesh|) and `max_escape` (furthest
vertex outside). Thresholds for the poor-fit warnings are derived from
the delivered golem's own worst fits (2.35 / 9.13% of bbox diagonal). A
bad fit is a warning with numbers, never a second primitive.

`joint` is the motion handoff's swing/twist cone. Limits are DESIGN
INTENT — never scene-measurable — and arrive via
`overrides = {chunk: {hinge_axis, hinge_range_deg, twist_range_deg?,
parent?}}`. Conversion is the knee rule verbatim: axis along the hinge,
`swing2 = 0`, `swing1 = (hi−lo)/2` covering the flex arc, twist locked
near zero (default `[0, 0]`), and `swing_centre_deg = (lo+hi)/2` placing
the arc so a one-sided range puts neutral at the extreme —
no-hyperextension as the range's own asymmetry. A parented chunk without
an override gets an explicit LOCKED joint plus a warning; a parentless
chunk gets `joint: null`. `parent` defaults to the nearest mesh-bearing
ancestor in the chunk set — and in a rigid-parent rig (#713), where each
chunk hangs off its own joint and the parent chunk is a SIBLING branch under
an ancestor joint rather than an ancestor, to the chunk carried by the
nearest ancestor joint above the chunk's own (#722). Chunks sharing one
joint are welded, never each other's parent; if an ancestor joint carries
several, the first by name is taken and the choice is warned. Flat-sibling
destruction rigs still supply `parent` via overrides, because there
parenthood is design intent too. **An override that supplies joint limits
for a chunk that resolves parentless REFUSES** — a limit with no joint to
attach to used to be dropped silently, leaving a manifest that looked
complete with no limits in it (#722).

Validation is ANALYTIC, not simulated (#675): degenerate volumes,
rest-pose-excluding ranges, multiple parentless bodies and every override
problem are warnings or refusals. Collider interpenetration at bind is
deliberately NOT checked — adjacent destruction chunks legitimately
interpenetrate at their shared joint, so that warning would always fire.

## Commands (rigging phase 5 / #691)

| cmd | params | result |
|---|---|---|
| `create_blendshape` | `{ mesh, targets: [{name, target_mesh}] }` | `{ mesh, blend_shape, targets: [{name, max_delta, vertex_count}], warnings }` |
| `set_blendshape_weights` | `{ mesh, weights: {name: 0..1} }` | `{ mesh, blend_shape, weights, max_displacement, per_target, warnings }` |

`create_blendshape` wires ordinary sculpted meshes as morph targets. The
deformer evaluates **front-of-chain** (before any skinCluster): a shape
models the neutral surface and the skin carries the shaped surface to the
pose, which is what makes a muscle corrective correct at a bent joint.
Targets must match the base's topology (refused with both vertex counts —
no wrap fallback) and are **consumed** once wired: the deltas live in the
deformer, and a stale editable copy invites sculpting a mesh that feeds
nothing. Each target's `name` becomes the weight alias, the
`set_blendshape_weights` key, and the exported Shape record's name.
`max_delta` is measured through the real deformer at weight 1; a target
measuring (near-)identical to the base warns. Creating again on the same
mesh ADDS targets to its one blendShape node — stacking a second deformer
is refused by construction.

`set_blendshape_weights` drives the named weights (0..1, absolute), lands
them sequentially in call order, and measures per step; the returned
`weights` map is every target re-read from the node. All-zero weights IS
the reset — the phase-1 pose-map currency is untouched.

Export: shapes ride along automatically (`FBXExportShapes` pinned on —
there is no parameter). The byte gate refuses an export whose scene
declares a target the file does not carry, and the result's `shapes` block
reports each channel's name and delta payload as read from the bytes.

## Commands (rigging phase 6 / clips / #695, multi-take #718)

| cmd | params | result |
|---|---|---|
| `author_clip` | `{ root, name, fps=30, keys: [{time_s, rotations?, blend_weights?, root_position?}], interpolation, loop, timeout_s=120 }` | `{ root, clip, fps, duration_s, frames, keyed_joints, keyed_weight_channels, root_position_keyed, interpolation, loop, start_frame, end_frame, clips, padded_channels, held_channels, back_filled, replaced, per_key, warnings }` |
| `preview_clip` | `{ root, name, angle?, every_nth?, resolution?, renderer?, zoom? }` | `{ clip, fps, start_frame, end_frame, frames, images, warnings, ... }` |
| `measure_clip` | `{ root, name?, joints?, contact_joints? }` | `{ name, fps, frames_sampled, loop, rig_height, thresholds, joints: {kinematics...}, contacts: {runs, max_slide}, symmetry, warnings }` |

### Motion has numbers now (#773)

`preview_clip` is the eye; `measure_clip` is the ruler. It samples every joint's world position at every frame of one clip and reports what a measured probe proved **discriminates** between a good clip and a deliberately broken one (a drifting plant + a popped key, on a real rig):

* **Per-joint kinematics** — path length, peak speed and max |accel| with **worst-frame indices**, height range, loop closure. The probe's popped limb read 8.05 peak against its clean mirror's 3.39.
* **Contact and slide** — plant runs are *inferred* (near the joint's own lowest point AND slower than 35% of rig height per second; the clip format declares no plants), and each run's **net ground-plane drift** is measured. The broken plant slid 0.097 on a 1.0-height rig; the clean one exactly 0.0. A slide past 2% of rig height is named in `warnings` — the one verdict unambiguous enough to be the tool's rather than the caller's.
* **Left/right symmetry** — peak-speed ratio per `L_`/`R_` joint pair: 1.0 clean, 2.4 with the popped key. This is the pop detector, and it exists because the obvious alternative measurably failed: an accel-spike-to-median ratio scored the GOOD clip *higher* (20.0 vs 10.3), since a clip with a rest phase has a near-zero median. Raw numbers plus the mirror comparison discriminate; self-normalised ratios do not.

Thresholds are all **relative to `rig_height`** and reported back in `thresholds`, so every verdict can be re-derived. The contact speed limit is deliberately never a fraction of the joint's own peak: a foot that does nothing but drift has a peak that IS the drift, and a self-relative threshold would grant it zero contact frames and hide the exact defect this exists to catch.

`name` may be omitted when the rig carries exactly one clip. `contact_joints` defaults to the **leaf** joints — the ends of chains are what touches the ground. Perception only: no checkpoint, current time restored.

What this deliberately is not: a score. Whether a peak speed is *too fast* is the caller's judgement; the tool's job is that nothing about the motion is invisible any more.
| `delete_clip` | `{ root, name? }` | `{ root, clip, clips, deleted_curves, reaped_channels, max_displacement, warnings }` |

`author_clip` keys the phase-1 pose map over time. **One rig carries as many
named clips as the asset needs, laid end to end on ONE shared timeline** —
not a clip library with independent timelines, one timeline that every
clip on the rig occupies a range of. A new clip is always **APPENDED**
after the last one already on the rig: its `start_frame` is derived, never
passed, and `end_frame` is MEASURED back from the curves once keying is
done — the caller never computes frames, it reads them off the result.
Between two clips sits **exactly one unowned gap frame** (`GAP_FRAMES = 1`
in `clipmath.py`): if a clip ends at frame `E`, the next one starts at
`E + 2`, and frame `E + 1` belongs to neither — it is where the
interpolation from one clip's last pose to the next clip's first pose would
otherwise live, and leaving it unclaimed keeps every take's range an exact,
non-overlapping frame count. Re-authoring an existing name does not edit it
in place: its old range is cut and it is **re-appended at the tail**, so it
moves in take order but no OTHER clip's motion changes — `replaced` names
it when this happened, and is `None` for a genuinely new name. **One fps
per rig**: every clip shares the fps of the ones already on the rig,
because a take is a frame range on one timeline and one file cannot carry
two frame rates; a clip authored at a different fps is refused, naming the
existing rate.

Keys may also carry blendshape weights (resolved across the meshes bound to
the skeleton) and a world `root_position` for the root joint — the pelvis
bob a walk needs. `loop=true` refuses a clip whose last key does not close
onto its first, with the measured per-channel difference. Every key's
displacement is MEASURED by driving the scene time to that frame;
`duration_s` is re-read from the authored curves. `timeout_s` (default 120,
ceiling `MAX_TIMEOUT_S`) exists because the tool's own timeout advice was
unfollowable (#721): a long clip on a heavy scene outlives the default, and
an open Arnold RenderView (IPR) re-renders on every scene mutation, which
can stall keyframing for minutes. `author_clip` and `preview_clip` now also
call `session.stop_idle_ipr` proactively - `author_clip` right before any
key is written, `preview_clip` right after resolving which clip it is
about to render - so an ARV left open from an earlier render no longer gets
the chance to wedge what comes next: keyframing for `author_clip`,
rendering and time-scrubbing for `preview_clip` (it writes no keys of its
own). Whatever it did lands in `warnings` with an `(#721)` tag.

**The self-contained rule, and its two kinds of pin.** All clips on a rig
share one curve per channel, so a channel a clip never mentions would
silently hold whatever a neighbour left there — the previous clip's last
pose forward, or a later clip's first pose backward. `author_clip` closes
both directions:

* **`padded_channels`** — channels some OTHER clip on the rig touches that
  THIS clip does not key anywhere in its own range. Pinned at their REST
  value, recorded the moment the channel first becomes curve-driven, at
  this clip's own boundary frames, so the take cannot inherit a neighbour's
  pose — a caller reading only this clip's take sees the rig sitting at
  rest outside the motion it actually authors. **Rest is the BIND pose**
  (#732) wherever the joint's dagPose bind matrix can be decomposed — the
  default XYZ rotate order, with `jointOrient`/`rotateAxis` stripped out —
  which is the common case for an imported rig whose bind pose legitimately
  carries rotation; a warning fires only when the rig is measurably POSED
  AWAY from that bind pose at the moment of first capture. A joint with no
  readable bind entry (no dagPose, or a non-default rotate order) falls
  back to the pre-#732 behavior — the rig's CURRENT pose at first capture —
  with its own summarized warning when that capture is non-zero. A scene
  authored before `mcp_clip_rest` existed at all still infers rest with a
  warning, from the existing clip's first key.
* **`held_channels`** — channels this clip DOES animate, but did not key
  exactly at one of its own boundary frames (a sparse declaration, or a
  fractional-time key that rounds short of the boundary). These are pinned
  at the clip's OWN held value there — what its own range would already
  evaluate to at that frame — never at rest. Pinning rest here would
  invent motion the clip never authored: it would rewrite an authored final
  pose into a rest pose one frame later. `held_channels` is the honest
  sibling of `padded_channels`: same self-contained goal, opposite pin
  value, because one case has real motion to preserve and the other does
  not.

Both directions are also closed **backwards**: a curve holds its first
key's value backward in time, so a channel a NEW clip introduces (one no
earlier clip on the rig ever declared) would rewrite every earlier clip's
pose the moment it gets keys of its own. `back_filled` reports this case —
`{ clips, channels }`, the earlier clips and the channels pinned across
them — pinned at rest across their ranges, which RESTORES what each of
them measured when it was originally authored rather than changing it.
There is no "own held value" to prefer here, because this clip has no keys
of its own inside an earlier clip's range (clips are always appended at the
tail, by construction).

**Displacement is measured against whatever the skeleton MOVES — by
deformation OR by rigid parenting.** A mesh transform parented under a joint
with no skinCluster anywhere (#713's rig) is a legal rig, not an empty one;
it used to report `max_displacement: 0` and `preview_clip` refused it
outright (#720). `preview_clip` now refuses only a skeleton that moves no
mesh by EITHER mechanism, and the refusal names both.

**While any clip exists, static pose mutators refuse** (`pose_skeleton`,
`pose_ik`, `reset_pose`, `set_blendshape_weights`): curves own the
channels, and a static write would be silently overridden on the next frame
change. `delete_clip` takes an optional `name`, and what happens turns on
whether the rig has any clip LEFT afterward, not on whether `name` was
passed:

* **clips remain** — this is the normal named-partial-delete: cuts just
  that clip's range, leaving every other clip on the rig untouched. `clips`
  in the result reports what is left, in timeline order. **Gaps are not
  re-packed**: a take is an explicit frame range, so a hole where a middle
  clip used to be costs nothing and stays a hole — re-packing would move
  keys the caller never touched. `clip` in the result names the one that
  was removed.
* **none remain** — whether `name` was omitted (delete everything) or it
  named the LAST clip still on the rig, the effect is the same full
  teardown as before #718: every curve deleted, every keyed weight channel
  zeroed, the bind pose restored. `clips` in the result is then always
  `[]`. When `name` was omitted and several clips existed before the call,
  every one of them was torn down, but `clip` in the result names only the
  FIRST of them (the pre-delete list, index 0) — it does not enumerate the
  delete. Read `clips` (now empty) and `warnings` for the full story; treat
  `clip` here as naming one clip, not the scope of what was removed.

Both report the measured displacement of the return.

**`deleted_curves` on a NAMED, partial delete counts two things.** Cutting
the doomed clip's own frame range essentially never empties a shared curve
(the surviving clips' keys and pins remain), BUT a channel that only the
deleted clip declared is reaped whole (#730): the rest pins the deleted
clip back-filled into the surviving clips' ranges are dead weight no take
declares, so its curves are removed entirely and reported in
`reaped_channels`. A partial delete of a clip whose channels are all
shared with survivors still honestly reports `deleted_curves: 0` and
`reaped_channels: []`.

The rig's `playbackOptions` range is always set to the **full span** —
frame 0 through the latest `end_frame` across every clip on the rig, not
just the one most recently authored or deleted — so opening the scene and
scrubbing shows every clip, and `delete_clip` re-derives it after cutting a
range too.

`preview_clip` now takes the clip **by name** — a rig carries several, and
there is no more "the live clip" to default to; an unknown name is refused
with the names present. It renders every-nth frame through the render
pipeline into one contact sheet (camera placed at frame 0 of the NAMED
clip and held); `zoom` (default 1.0, mirrors `render_scene`'s) closes the
framing in — the gate measured the default 320px cell unjudgeable and
needed zoom 1.5-1.6 to read a blink. The result's `frames` list is a trap
for the unwary: `frame` is **absolute** (the rig's own timeline position,
`start_frame` plus the offset), but `time_s` is **clip-relative** (seconds
from the clip's own start, matching what `author_clip`'s `keys[].time_s`
meant when it was authored) — the same pair of units the rest of this
section uses throughout, never mixed within one field.

Export: pass `include_animation=true` to `export_fbx` — **every clip on the
rig** bakes to per-frame curves over the whole rig's span
(`FBXExportBakeComplexAnimation`, from frame `0` to `span_frames`, the
highest `end_frame` among the rig's clips), and one
`FBXExportSplitAnimationIntoTakes` call per clip carves that single baked
range into that many named takes.

**MEASURED (#718 Task 10): curve records are segmented PER TAKE, not one
per plug over the whole file.** A two-clip file carries THREE
`AnimationCurveNode` records for a plug any clip touches — one full-span
record under the exporter's own always-present default take ("Take 001",
keyed over the whole `0..span_frames` range), plus one per named take
carrying that take's OWN range. A first-wins collapse across the three
duplicates, keyed only by `(target, property)`, picks among them by an
FBX-internal object UID that is **not stable across otherwise-identical
exports**: 8 back-to-back exports of one correct scene measured 6 passes
and 2 failures — the gate refused a correct file at random. The fix
(#718 Task 10b) attributes each curve record to the take it belongs to:
`fbxbytes.anim_facts`'s `targets` entries carry a `take` field — the name
of the `AnimationStack` whose `AnimationLayer` owns that curve node,
resolved structurally through the `AnimationCurveNode` ->
`AnimationLayer` -> `AnimationStack` connection chain (never guessed from
tick ranges; `None` when the chain is absent). The byte gate now asserts,
per declared clip, against only THAT clip's own take's records: rotation
curves per keyed joint at the take's own `end_frame - start_frame + 1`
keys (not the whole file's span), root translation curves when
`root_position` was used by any clip, DeformPercent curves per keyed
weight channel, and — looked up **by name** among the file's takes —
that take's start/stop against the declared clip's own
`start_frame`/`end_frame` (converted through the rig's fps, half a frame
of tolerance). Records attributed to "Take 001", or to no take at all,
are ignored — not flagged — the same rule that already tolerates extra
undeclared takes. With `include_animation=false` (the default) the gate
asserts the file carries ZERO curve records even when the scene is
animated. The result gains `animation`, whose `clips` field is a per-clip
list — `{ name, start_frame, end_frame, duration_s, curves }` — read back
from the take and curve records the bytes actually carry for THAT clip's
own take, not echoed from the scene.

**MEASURED: the file always carries one MORE take than clips declared.**
`FBXExportSplitAnimationIntoTakes` writes each named take *alongside* the
exporter's own always-present default take (`"Take 001"`), so a correctly
exported N-clip rig legitimately carries **`N + 1`** takes — two for one
clip, as before #718, and one more per additional clip. `anim_violations`
looks each declared clip up **by name** among the file's takes and ignores
the rest — an extra take is not a violation, the same rule
`shape_violations` applies to undeclared shape channels.

**Multi-CLIP is supported; multi-RIG refuses.** One skeleton may carry any
number of clips and they all export into the one file's takes. Two
DIFFERENT skeletons each carrying clips in the same scene refuse the
export outright, naming both roots: a take is a frame range over the WHOLE
file, so a multi-rig file would need a timeline policy of its own that
does not exist yet. `delete_clip` the rig that is not being exported.

## Delivery

| cmd | params | result |
|---|---|---|
| `export_fbx` | `{ path, metres_per_unit, nodes?, include_skins?, include_animation?, require_baked_textures? }` | `{ path, bytes, fbx_version, node_count, mesh_count, root_nodes, unit_scale_factor, metres_per_unit, world_bounds_min, world_bounds_max, height_m, bounds_unavailable_reason, skin, shapes, animation, textures, warnings }` |
| `bake_textures` | `{ meshes, out_dir, resolution?, slots? }` | `{ meshes, out_dir, resolution, baked: [...], skipped_file_backed, checkpoint_id, warnings }` |

Every field of the result is read back **out of the written file**, never from the Maya scene — the unit defect this tool guards (#629) is produced by the exporter and is absent from the scene, so a scene-derived report would be confidently wrong in exactly the case that matters. The file is written to a sibling temp path and only reaches `path` once it passes; a refused export leaves whatever was already there untouched.

`metres_per_unit` is required and only `1.0` exports. There is no default on purpose: a guess about what one unit means is what shipped three deliveries at 100x.

The gate makes **two** assertions. The declaration must say metres (`UnitScaleFactor` 100.0), and no node whose scale reaches a vertex may carry one — that is the node holding the geometry and every ancestor above it. Nodes whose scale cannot touch a vertex are not gated: a whole-scene export writes lights and cameras as `Model` records too, and refusing an export because a light or an annotation locator is scaled would blame vertex magnitude for something that has no vertices (#646). A locator and a group are both `Null` in the file, so the test is structural, not by node kind.

Omitting `nodes` exports the whole scene, including lights and cameras (`FBXExportCameras`/`FBXExportLights`, pinned rather than left to `FBXResetExport`'s defaults). Passing `nodes` exports that selection **plus its ancestor chain** — so a group above the selection carries its scale into the file, and the gate refuses it by name rather than silently shipping a mis-sized asset.

`height_m` and the bounds are null when the reader cannot compose the hierarchy — a non-default `rotateOrder` is the case that happens in practice — and `bounds_unavailable_reason` then says which, distinctly from "the file holds no geometry". The export still succeeds: a measurement the reader cannot make must not fail bytes that already passed the gate.

`include_skins` (default `false`) additionally writes the skinCluster
deformers and the BindPose, and gates on the **file's own** skin records,
not the scene: a skin deformer must be present, every cluster must link
joints (a selected export listing the mesh without the skeleton root writes
a deformer with zero clusters — named separately, since "every vertex
unweighted" otherwise reads like a bad bind rather than a short selection),
a BindPose record must exist, and per-vertex weight sums must be within
`WEIGHT_SUM_TOL` = `1e-2` of 1.0. That tolerance is measured, not guessed:
Maya's FBX exporter drops every skin weight strictly below `1e-3` without
renormalising what is left, so a correct `max_influences=8` bind can lose up
to ~7e-3 per vertex on export alone — a `1e-3` tolerance tried first refused
a real, correctly-bound mesh. LimbNodes (skinned joints) gate under the same
identity-scale rule as meshes (#629), since a joint's scale reaches a vertex
without being its ancestor.

LimbNodes additionally must not carry FBX `InheritType 2` — Maya writes it for
a joint whose `segmentScaleCompensate` is on, and Unity (which does not
implement that inheritance) materialises the metres declaration as
localScale 100 on every such joint and compounds it per level, silently
(#703: a 12-joint serpent instantiated at world scale ~10^21 m with a clean
console). `create_skeleton` turns SSC off at joint creation, so this fires
only on skeletons authored outside the tool or predating the fix.

`export_fbx` also reports what the scene's materials CLAIM to carry against
what the bytes actually hold (#714). Procedural texture networks (noise,
ramp, layeredTexture, ...) have no FBX representation at all — Maya's
exporter silently drops them — and each dropped slot is reported per
material/slot in `textures.dropped_maps`, with a matching entry in
`warnings`. `maya_bake_textures` is the remedy: it turns exactly the
networks `dropped_maps` names into file textures the exporter does carry
(below). File-backed maps are byte-verified against the file's own
Texture/Video records by image basename; a claimed file missing from the
bytes REFUSES the export (that loss class has never been observed, so its
absence means the exporter regressed). A Texture/Video record whose own
filename this reader could not parse reports an empty basename instead of
being dropped, and if any such records exist a `warnings` entry names the
count — so a refusal naming a missing record can be told apart from a
genuine parser gap rather than being read as an exporter regression.
`require_baked_textures=true`
(default `false`) turns any procedural claim into a pre-write refusal —
before anything is exported, naming the offending material/slot/node —
for callers who need every map to travel. Channel swizzle (picking one of
R/G/B/A off a map), a `reverse` invert, and a `Raw` colorspace declaration
are reported in each file map's `semantics_lost` and never gated: the
image itself survives in FBX, only the wiring decision does not, and
refusing it would refuse `assign_pbr`'s own mask workflow.

The claim walk itself can fail (an unreadable shading graph) without
failing the export — it costs the measurement, not the export, the same
rule `_bounds` follows for a rotation order it cannot compose. When it
does, `require_baked_textures=true` refuses pre-write on that too: a
strict caller demanded proof that only file-backed maps are present, and
with no claim there is no proof. Either way the failure lands in
`textures.unavailable_reason` (the scene's claim could not be read, the
file's texture records could not be parsed, or both, joined with `"; "`)
and the same string is echoed into `warnings`. A set `unavailable_reason`
means texture verification did **not** happen for this export — a
successful export carrying one has reported strictly less than a clean
one.

`textures` itself is `null` when the export touches no material claims, no
Texture/Video records, and the claim walk did not fail — an untextured
export reports nothing here rather than an empty block. When present, it
carries six fields: `texture_records`/`video_records` (raw counts read back
from the file), `file_maps`/`dropped_maps` (the per-claim detail behind the
paragraph above), `unclaimed_records` (image basenames present in the
file's own Texture/Video records that no scene claim maps to — a file node
the exported selection never reached), and `unavailable_reason`.

When the scene's claim walk itself failed, every basename in the file
would otherwise be reported as unexplained by "no walked material claim
explains" — a wording that has nothing to do with why the walk found
nothing. That warning is suppressed in this case (`unavailable_reason`
already names the real cause); the `unclaimed_records` field itself is
unaffected and still lists those basenames as data.

`apply_texture_recipe` warns at authoring time, not only at export: any
recipe other than `file_texture` returns a `warnings` entry naming
`maya_bake_textures` as the fix — the network it just built has no FBX
representation, and the bake tool converts it to a file texture that does
survive. When the mesh has no UVs, a second warning fires alongside it:
`maya_bake_textures` refuses a UV-less mesh outright (below), so the
recipe says so up front rather than leaving it to be discovered cold at
bake time — `maya_uv_atlas` is named as the fix for that one.

`maya_bake_textures` (`{ meshes, out_dir, resolution?, slots? }`) turns
exactly the procedural networks `dropped_maps` names into file textures
and **rewires the scene** to use them. `out_dir` must be an absolute path
that already exists — this tool does not create directories, the same
rule `export_fbx` follows: a guessed or auto-made location is how bake
files get lost from a delivery. `resolution` is one of `256`, `512`,
`1024`, `2048`, `4096` (default `1024`); `slots` restricts the bake to
the named PBR slots and defaults to every procedural one the mesh(es)
carry. The rewire is persistent — the next render, and the next
`maya_export_fbx`, show exactly what the bake produced, so re-judge the
render before exporting rather than trusting the bake blind.

The bake is two-phase. Phase A bakes and pixel-verifies every job against
a `.part.png` file with nothing in the scene touched yet; only once every
job in the batch clears that check does phase B run. A phase A failure
leaves the scene completely untouched (its `.part.png` files are removed)
and takes no checkpoint — there is nothing yet to roll back. Phase B takes
the checkpoint first, then commits each rewire and sweeps newly orphaned
nodes; if phase B itself fails partway, the scene is left only partially
rewired and the raised error **names the checkpoint id in its own
message**, since `maya_restore_checkpoint` is the only way back at that
point.

A mesh with no UVs is refused outright: a bake
samples through UV space, and Maya's own `convertSolidTx` does not error
on a UV-less mesh — it silently writes a flat, useless image — so this
tool refuses rather than shipping that quietly wrong. A material worn by
several of the requested meshes bakes **once**: the bake samples through
UV space, not world geometry (measured), so a shared material's image is
identical regardless of which mesh triggered it — but that measurement
was taken on placement-less networks only. A network driven through a
place2dTexture with non-default placement is not covered by it; such a
job carries a warning rather than a refusal, since the bake is still
written once per material by construction and the warning is what a
reviewer needs to re-measure if it ever matters. When every requested
slot is already file-backed, nothing is baked and `checkpoint_id` is
`null` rather than a spent checkpoint-ring slot for no change;
`skipped_file_backed` names what needed no work, so a caller can tell
"nothing needed baking" from "nothing happened."

The rewire is material-level, so it can reach further than the meshes
named in the call: if the same shading group is also assigned to a mesh
the caller never listed, that mesh's look changes too. `plan_bakes` queries
the shading group's **actual** membership (`cmds.sets(sg, query=True)`),
not just the requested-shape claim, and warns naming the outside wearer(s)
specifically when it finds one — this is separate from, and does not
replace, the "worn by several requested meshes" warning above. A shading
group that cannot answer the membership query degrades to no warning
rather than failing the bake.

## Commands (mesh maps / #770)

| Command | Params | Result |
|---|---|---|
| `bake_mesh_maps` | `{ meshes, out_dir, maps?, resolution?, apply_ao?, curvature_radius?, curvature_output? }` | `{ meshes, out_dir, resolution, maps, baked: [...], applied: [...], checkpoint_id, warnings }` |

`bake_mesh_maps` bakes **geometry-derived** maps — `ao`, `curvature`,
`world_normal` (default: all three) — per mesh, through each mesh's UVs,
with Arnold's render-to-texture. This is the other half of `bake_textures`:
that tool flattens procedural *shader networks*; this one bakes what only
the *geometry* knows — where parts meet (AO sees **other meshes** as
occluders, measured), where edges are (curvature), which way surfaces face
(world normal; its G channel is an up-facing dust mask).

The bake phase mutates nothing: the map shaders render via
`arnoldRenderToTexture`'s `-shader` flag and are **never assigned** to the
mesh (measured). Each bake runs one mesh into a private empty folder —
Arnold names its own outputs and renames them on short-name collisions, a
rule this tool refuses to model, which is also why two requested meshes
sharing a short name refuse upfront. A UV-less mesh refuses upfront too:
Maya does not — it returns success and writes a corrupt EXR that only
fails at read (measured).

Every map is converted EXR→PNG (a **linear** conversion, measured: AO 0.5
lands on 127/128) and verified: missing/unreadable/drew-nothing refuse;
**flat only warns**, because flat can be honest here — a lone convex
mesh's AO is all-white, and concave curvature on convex-only geometry is
all-black (both measured). `stats` carries the numbers per map.

`apply_ao=true` is the one scene edit, checkpointed: the AO is multiplied
into each material's colour slot **sRGB-correctly** (decode base → linear
multiply → re-encode; the AO png is linear data) and the slot is rewired
to the new composite file — a plain file→slot wiring `export_fbx`
carries. The input colour map is never overwritten. Refusals fire before
any bake runs: a procedural colour slot (bake_textures flattens it
first), a non-PNG base, a material worn by a mesh outside the request, or
per-face assignment. A material shared by several *requested* meshes
composites the union of their AO bakes, masked by each bake's alpha —
those bakes run **unpadded**, because `extend_edges` floods alpha to 1.0
over the whole image (measured); texels claimed twice are reported as
`overlap_fraction` and warned above 1%.
