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
- **Static writes ask first (#802).** A command that writes a plug statically
  — `pose_skeleton`, `reset_pose`, `pose_ik`, `set_camera`, `transform`,
  `add_corrective` — asks, before its checkpoint and before its first write,
  whether every plug it will touch is free: not locked, and not fed by a
  constraint, curve, driven key, expression or wire. If any is not, the whole
  call refuses with a `HandlerError` naming the plug, the obstacle and the
  fix, and NOTHING is written — `transform` is all-or-nothing across every
  name in the call, as `delete_objects` is, and `reset_pose` never leaves a
  rig half at its bind pose. The render passes cannot refuse (a render still
  has to render), so `render_scene` and `render_sheet` instead put a warning
  in `warnings` naming each rig light they could not swing and each rival
  shape they could not hide. Measured on Maya 2027, and the reason a
  pre-check is the only shape that works: Maya refuses a locked or hard-wired
  plug, but a constraint- or curve-driven plug TAKES the write and discards
  it at the next evaluation, and `cmds.xform` never raises at all — it writes
  the children it can and silently skips the rest. Neither failure is
  catchable after the fact.
- **Undo.** Every mutating command runs inside one `undoInfo` chunk = one undo
  step. Read-only perception commands (`capture_viewport`) suppress undo
  recording (`stateWithoutFlush`) so their internal churn never lands on the
  undo queue — undo after a capture reverts the last real edit. MEASURED for
  the first time in #820 (Maya 2027): the chunking holds for every mutating
  command tried, the auto-checkpoint adds no step, and a capture adds none —
  but Maya's OWN callbacks push entries that change nothing
  (`selectionMaskResetAll` after any call that touched the selection,
  `hikDefinitionFileNewCallback;` after a new file, and a nameless entry
  `new_scene` leaves at the bottom), and they land AFTER the chunk closes, once
  Maya goes idle between requests. `undo`/`redo` step over those without
  counting them (reported in `skipped`) and stop on the queue-empty query,
  because `cmds.undo()` on an empty queue does not raise — the old handler
  counted attempts, so `undo` after `new_scene` reported one step undone.
  Two more measured facts shape the plugin itself: a deferred callback runs
  inside whatever chunk opens next, so the plugin flushes Maya's idle events
  before every chunk (a query-only call can no longer close a non-empty
  chunk that undo counts as a step); and **a plugin load flushes the undo
  queue** — Maya's deferred autoloads take the loaded count from 16 to 53 in
  the first ~7 s after userSetup, and every chunk recorded before that was
  gone — so `start_server` binds the port only once the plugin count has held
  still for 1.5 s (~20 s after launch on this machine). A listening port now
  means Maya is safe to edit.

### The unknown-key contract

**Every command refuses a top-level `params` key it does not read** (#764,
swept across the whole surface by #767), with a `HandlerError` naming the
offending key and listing the valid ones. The refusal is the first thing each
handler does, before any Maya call, so a typo costs nothing and needs no live
Maya to be reported.

This exists because an unread key is worse than a wrong value. A wrong value
fails; an unread key **succeeds and does something else**. Measured: `assign_material`
reads its explicit-name param as `name`, eleven tests in this repo passed
`material=` instead, and every one of them created a differently-named material
than it believed it was creating — passing, silently, for months.

Where a wrong word is a plausible *synonym* rather than a typo, the error says
which key was meant (`'material' is called 'name' here`). Those are recorded
per command rather than guessed at, because the realistic mistake is reaching
for a neighbouring tool's vocabulary or for a field name out of the *result* —
and no string-similarity test relates `material` to `name`, which share not one
letter in position. Ordinary typos fall back to prefix matching.

Two notes for direct wire callers, who are the ones this protects (the MCP tool
wrappers type their parameters, so an MCP consumer cannot send an unknown key
in the first place):

- `timeout_s` is a **frame-level** field, a sibling of `cmd` and `params` — not
  a param. Putting it inside `params` is ignored by every command except
  `execute_python`, which accepts the key for wrapper compatibility and still
  reads its real timeout from the frame. Measured in this repo's own evals:
  calls that asked for 180 s inside `params` silently got the 60 s default.
- The tables below list the params each command reads. A key absent from a
  table is refused, so a stale table row is a runtime refusal rather than a
  documentation nit — they are checked against the handlers by
  `tests/test_param_contract.py`.

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
| `capture_viewport` | `{ angles?, shading?, wireframe_overlay?, buffer?, lighting?, shadows?, isolate?, target?, frame_all?, resolution? }` | `{ images: [{angle, png_b64, blank}], camera_positions: [...], warnings }` |

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
| `undo` | `{ steps? }` | `{ undone, requested, skipped, queue_empty }` |
| `redo` | `{ steps? }` | `{ redone, requested, skipped, queue_empty }` |
| `new_scene` | `{ confirm, linear_unit? }` | `{ new_scene: true, pre_checkpoint, pre_checkpoint_path, units }` |
| `open_scene` | `{ path, confirm? }` | `{ opened, pre_checkpoint, pre_checkpoint_path }` |
| `save_scene` | `{ path? }` | `{ path }` |

Checkpoints go to `<dir of the open scene>/checkpoints/`, so a `checkpoint_id`
(`NNN_label`) is unique only inside one directory — and `new_scene`,
`open_scene` and `restore_checkpoint` all change which directory that is. Ids
issued during the session are resolved against where they were actually
written, and every id comes back with its `path`; pass `path` instead of
`checkpoint_id` for an id from an earlier session (#649). Passing BOTH is refused unless the id is the path's own stem: `path` overwrote `checkpoint_id` and restored its own file, so two different checkpoints in one call silently became one (#797).

Scene ops:

| cmd | params | result |
|---|---|---|
| `create_primitive` | `{ kind, name, translate?, rotate?, scale?, divisions? \| subdivisions? }` | `{ name, subdivisions, faces, warnings }` |
| `duplicate` | `{ name, new_name, translate?, rotate?, scale? }` | `{ name, warnings }` |
| `transform` | `{ names, translate?, rotate?, scale?, relative?, pivot? }` | `{ objects: [...], warnings }` |
| `group` | `{ names, group_name, pivot? }` | `{ name, pivot, children, warnings }` |
| `parent` | `{ child, parent }` | `{ name, warnings }` |
| `rename` | `{ name, new_name }` | `{ name, warnings }` |
| `delete_objects` | `{ names }` | `{ deleted: [...], warnings }` |
| `combine` | `{ names, name, pivot?, freeze? }` | `{ name, inputs, tris, verts, faces, shells, pivot, pivot_mode, frozen, shading, warnings }` |
| `assemble` | `{ name, parts: [...], atlas?, combine?, pivot?, pivots?, freeze? }` | `{ objects: [...], parts, tris, outside_patch, atlas, warnings }` |

**`group` says where its pivot is** (#823, measured). `cmds.group` builds the new transform at the origin with identity, but puts its **rotate pivot at the members' bounding-box centre** — two cubes at x=2 and x=4 grouped and then rotated 90° about Y orbit (3,0,0), not the origin, and nothing in the old `{name}` result said so. The result now carries `pivot` (queried back from Maya) and `children` (each member's new canonical long name, in the order given), and `pivot: "origin"` moves the pivot to the world origin before reporting — the rig case (#814: parent the roots under a group at the origin and scale that). `warnings` names what Maya did quietly: a `group_name` already held (`|taken` → `|taken_001`, like `boolean_op`), a member renamed because a sibling had its short name (`|p2|part` → `part1`; members are matched by UUID, so the renamed one keeps its drift-ledger record — matching by short name used to lose it), a duplicate entry in `names` (dropped), and a former parent left with no children. A member's world transform is preserved across the reparent; its local one is rewritten.

**`rename` says when the name you got is not the name you asked for** (#829, the first time it was ever sent to a live Maya). Two ways that happens, both silent before — the result carried the new name and an empty `warnings`, so a caller who did not diff the string never learned:

- the name was **taken**, and `naming.unique_name` redirected to a `_001` suffix;
- **Maya rewrote it.** It does not refuse a name it dislikes, it mangles it: `"my lamp"` → `my_lamp`, `"a|b"` → `a_b`, `"lamp-01"` → `lamp_01`, `"2lamp"` → `lamp` (leading digits stripped) and `"ns:lamp"` → `lamp` — **a namespace prefix is dropped**, so asking for a namespace silently gets you none. Non-ASCII letters survive; the rule is word characters, not ASCII.

Two more things measured there and fixed. Renaming a **shape** used to raise a raw, hintless `No valid objects supplied to 'xform' command` — from the drift-ledger write, *after* the rename had already happened, so a failure message stood over a mutation that took. And renaming a **parent** left every descendant's ledger entry keyed to a path that no longer existed, silently retiring the "moved outside maya-mcp" check for the whole subtree; the ledger is now re-keyed along the rename instead of forgotten and re-recorded (a rename writes no transform, so claiming one was wrong too). A rename carries the shape name with it, and a bound joint or a shaded mesh survives one intact — both measured, both pinned by the gate.

**`combine` unites `names` into one mesh called `name`** (#803). `pivot` is `center` (bounding-box centre, the default), `origin`, or `keep`; `freeze` (default true) bakes the transform afterwards, and the reported `pivot` is **queried back from Maya after the freeze**, never the value that was written - a freeze used to be reported as the centre it had just thrown away. `name` may be a consumed input's own name (`combine(names=["|body","|arm"], name="body")` hands back `|body`, not `|body_001`): `polyUnite` consumes every input, so the name is claimed once they are gone, the #640 rule `boolean_op` and `etch_text` already follow. `new_name` is accepted as a synonym. `shells` should equal `inputs` - combine does not weld - and `shading` is the one object-level shading group the result carries, with a warning when the inputs wore more than one.

**`assemble` is the flat build loop on the tool surface.** Each entry of `parts` is `{ kind, pos?, dim?, rotate?, patch?, taper?, chunk?, divisions? | subdivisions?, name? }` - a primitive, placed, optionally tapered and given an atlas cell; parts sharing a `chunk` (default: `name`) are united into one object per chunk when `combine` is true (`merge` is a synonym). `atlas` is `{ cols, rows, margin, world_scale, project, normalize }` or null to leave UVs alone; `pivot` is combine's mode and `pivots` is `{ chunk: [x, y, z] }` for an explicit placement per chunk. Every `objects` entry carries `name, parts, tris, verts, faces, shells, pivot, combined`. The #797 refusals and warnings below say which of these a given build actually reads.

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
| `octahedron`, `icosahedron` | none — `polyPlatonicSolid` has no subdivision flag, so passing **either** `subdivisions` or `divisions` is **refused** rather than ignored (#797) | — |

The reason this exists: `divisions` on a cylinder or cone buys **20 around for every 1 along**. A long thin limb needs rows along its length and almost nothing around it, so the only way to get them was to pay for a circumference no shape needed — measured, 16 rows along a cylinder costs **5122 faces** that way against **194** with a 12-sided tube, and both bend identically (`evals/divisions_live.py`).

**The minimums are enforced, and they are not decoration.** MEASURED on this Maya: given a `subdivisionsAxis` below 3, `polySphere`/`polyCylinder`/`polyCone`/`polyTorus` neither clamp nor raise — they silently substitute their own **default of 20**. A caller asking for a 2-sided tube would get a 20-sided one and be told nothing, so the tool refuses instead.

The result reports **`subdivisions`** (the per-axis counts as built) and **`faces`**, because the multiplier's per-kind meaning is invisible from the call site: `divisions: 4` on a cylinder buys 80 around and 4 along, and nothing else in the result said so.

**`divisions` on a platonic solid is refused too** (#797). It used to be range-checked exactly like a cylinder's and then discarded, because there is no axis to spend it on: the caller asked for a denser icosahedron, got the same 20 faces, and nothing said so. The refusal names the kind — `create_primitive does not use 'divisions' on an icosahedron: polyPlatonicSolid takes radius and axis only …` — and inside `assemble` it is prefixed with the part, so one bad part out of twenty is identified. Refine a platonic solid afterwards with `maya_sculpt_ops` op `smooth` instead.

The face projection those counts are budgeted against was **wrong for cylinder and cone** until #669: it charged a fan of triangles per end cap, where Maya closes each with a single n-gon, so a default cylinder was predicted at 60 faces and builds 22. It survived because the only real-Maya face-count assertions covered the platonic solids, prism and pyramid — the mayapy suite now checks every kind.

`assemble` parts take the same two keys with the same meanings and the same refusals.

**`combine` and `assemble`: `pivot='keep'` on a combined result keeps the ORIGIN, and says so** (#797). MEASURED on a live probe (2026-09-03, pid 33088): a fresh `polyUnite` transform answers `rotatePivot`, `scalePivot` **and** `translate` as `(0, 0, 0)` whatever `ch` is set to, so there is no inherited pivot for `keep` to preserve — it is `origin` under another name. It is not refused, because the value is legal and `assemble`'s single-part branch does keep a pivot a primitive genuinely built; instead `warnings` carries one line saying the unite gave the result the world origin and that `center` is what asks for the bounding-box centre. A caller who asked to keep something and got the origin used to have no way to tell that from a `keep` that worked. `assemble` unites a chunk at a time, so it does **not** carry that line up per chunk — 2,034 identical copies would bury every per-chunk finding beside them; it drops them and states the count once (`pivot='keep' on 12 combined chunk(s) kept …`), and every other warning `combine` raises about a specific chunk is still carried up verbatim.

**`assemble`'s `pivot` is applied by `combine.unite` and by nothing else** (#797), so `origin` and `keep` are REFUSED when nothing in the call is united: with `combine=false`, or when every chunk holds exactly one part. Each part then keeps the pivot its primitive was built with, and `freeze` (on by default) writes over the transform afterwards — the mode was validated and dropped. `center` is the exception the plan measured: a primitive's own pivot already sits at its bounding-box centre, so asking for it is honoured whether or not anything writes it. A MIXED build (at least one multi-part chunk) is not refused — the multi-part chunks really do consume the mode — but `warnings` names how many chunks it reached and which single-part ones it never touched. Use `pivots` (`{chunk: [x, y, z]}`) to place a pivot on a chunk of one; that path reaches loose parts.

**A part's `patch` is a cell of an atlas, so with `atlas: null` it is refused** (#797). With no atlas nothing projects or packs UVs at all, and the cell used to be resolved against a phantom 4×4 grid the caller never asked for — so `patch: 16` came back "outside a 4x4 atlas", a refusal naming a grid that does not exist. The refusal now names the part (`parts[0]`) and the real cause: pass an `atlas` for the patch to address, or drop the patch.

**`atlas.world_scale` box-projects and never normalises** (#797), the same rule `uv_atlas` enforces one level down, because it is literally the same packer: `atlas.project` of `keep` or `planar` is refused with `world_scale` (world mode calls `polyAutoProjection(scaleMode=0)` on every part, so an authored layout is overwritten, not kept), and an explicit `atlas.normalize: true` is refused with it too (normalising makes every part fill its patch, which is the opposite of a fixed texel density; the world branch never calls `polyNormalizeUV`). `project: box` and `normalize: false` are exactly what world mode does and stand. An explicit `null` for `normalize` is read as "not passed" — it takes the default `true` — rather than as `false`, which is what `bool(None)` used to make of it for a raw-TCP caller who meant nothing by it.

**Two things `assemble` cannot refuse, and therefore warns about** (#797). `name` is required by the schema and is read in exactly one place — as the DEFAULT chunk — so a build whose every part names its own chunk never uses it; `warnings` then says the base name went unused, names the chunks the objects are actually called after, and says whether anything in the scene is called that name at all (a part may still ask for the base name as its own). And a part's own `name` survives only as long as the part does: in a chunk that gets united, the transient node is built under that name and then consumed by `polyUnite`, which names the RESULT after the chunk — so `warnings` counts and names the part names that were eaten. Neither is an error; both were silent.

Modeling and sculpting:

| cmd | params | result |
|---|---|---|
| `boolean_op` | `{ a, b, op, new_name }` | `{ name, tris, watertight, parent, pivot, uv_bounds, warnings, carved_text? }` |
| `etch_text` | `{ mesh, text, face, width?, depth?, font?, mirror?, rotate_deg?, new_name? }` | `{ name, tris, watertight, parent, pivot, uv_bounds, warnings, carved_text }` |
| `sculpt_ops` | `{ mesh, ops: [...] }` | `{ applied, ops: [...], tris, warnings, checkpoint_id? }` |
| `deform` | `{ mesh, deformer, params?, delete_history_after? }` | `{ deformer_nodes: [...], baked, warnings, max_displacement }` |
| `remesh_retopo` | `{ mesh, target_polycount, keep_original? }` | `{ name, faces, faces_before, target_polycount, tris, uvs: {before, after, transferred}, method, original, warnings }` |
| `mesh_cleanup` | `{ mesh, merge_verts_threshold?, delete_history?, freeze_transforms?, conform_normals? }` | `{ name, before, after, warnings }` |

**An empty `font` is refused, not silently Arial** (#797), and `width`/`depth` of `0` are refused rather than replaced by the defaults. All three used the `value or DEFAULT` idiom, which cannot tell "not passed" from "passed as zero/blank": a caller who named a font got a carve in Arial, and a caller who asked for `depth=0` got a 0.1 recess. Omit the param for the default; passing it now means it is used.

**Each `sculpt_ops` op declares the keys it reads** (#797). The four cage ops always did; the eight original ops did not, so a key belonging to a neighbouring op went straight through and the op ran on its own defaults — `displace_noise` with `center`/`radius`/`falloff` reads none of the three and displaces the WHOLE mesh, reporting success. Every op now refuses a foreign key (`sculpt_ops op 'displace_noise' does not take 'center', 'radius'`), and the whole check runs before the auto-checkpoint. `soft_move` and `inflate_region` take `vertex_id` **or** `center`, never both: `vertex_id` resolves the region centre to that vertex's own world position and `center` is never read, so passing both is refused rather than silently centring somewhere else.

**`rotate` on a `sculpt` deformer is refused** (#814, the #797 probe finally run). The sculptor `cmds.sculpt` builds is a sphere, and a sphere turned about its own centre pushes the mesh exactly as before — MEASURED: vertex positions identical to five decimals under `rotate=[45,30,0]` and `[0,0,90]`, while moving `translate` by 0.5 displaced them by 3.4, and the handle's rotate attribute read back exactly as written. Shape a sculpt with `params.translate`, `maxDisplacement` and `dropoffDistance`; `rotate` still turns a lattice or a nonLinear handle.

**A lattice bake with no handle move is refused** (#797). `deform` with `deformer="lattice"`, `delete_history_after=true` and no `params.translate`/`params.rotate` built a lattice, deformed nothing with it (a lattice deforms nothing until its points move), deleted it again and returned `{deformer_nodes: [], baked: true, max_displacement: 0.0}` — a success report for a call in which the mesh was never touched. Move the handle before the bake, or drop `delete_history_after` and shape the lattice live. Relatedly, the "a lattice never warns about zero displacement" exemption now applies only while the lattice SURVIVES: once history is deleted there are no points left to move, so a baked lattice that moved nothing warns like any other deformer.

**`create_curve_form`: `resolution.around` is refused on a sweep that gives `profile_sides`** (#797). A sweep's cross-section ring is `profile_sides` when it is given — that is the number that reaches `.profilePolySides`, and `resolution.around` is read on exactly one branch: the one where `profile_sides` is omitted and a round tube is approximated with as many sides as `around` asks for. A caller who passed both got the n-gon and had their `around` dropped silently. Pass `resolution={"along": N}` alongside `profile_sides` — `along` drives `interpolationSteps` and is read on every sweep branch — or drop `profile_sides` for a round tube of `around` sides. The face bill follows the same rule: `predicted_faces` on a sweep is `along * profile_sides` when the n-gon is given, `along * around` when it is not.

`remesh_retopo`'s `method` says which of the three commands actually ran, and it matters: `polyRetopo` takes a `targetFaceCount` and honours `target_polycount`; `polyRemesh` takes no face-count target at all and remeshes to its own uniform edge length, so on that fallback `warnings` says the target could not be honoured and `tris` is the only truth about what was built (#797). MEASURED for the first time in #819 (Maya 2027): `polyRetopo` lands within its own 10 % tolerance of `target_polycount` (183 for 200, 794 for 800, 1903 for 2000), keeps the transform, pivot, shading group and shell count, and **zeroes every UV** the mesh had (439 → 0 on a sphere). So the result now reports `faces` and `faces_before` in the caller's currency, and `uvs` `{before, after, transferred}`: with `keep_original` (the default) the UVs are transferred back from the hidden original by world position and `after` is non-zero; with `keep_original=false` they are gone, `after` is 0, and `warnings` says so and names `maya_uv_atlas`. The hidden original is a real mesh that **travels into `export_fbx`** (measured: two meshes in the file) - `warnings` names it; `maya_delete_objects` it before exporting, or pass `keep_original=false`.

A boolean builds a **new object**, so everything that is not vertices has to be carried across deliberately (#638). `boolean_op` and `etch_text` take three things off `a` before it is consumed and put them back on the result, reporting each one:

* **`parent`** — the result goes back under `a`'s parent, so cutting a socket into a rigged chunk does not drop it out of the hierarchy. The reparent happens *before* construction history is deleted, because that delete garbage-collects the consumed operands and takes an empty parent group with them. If the parent carries a scale or rotation, the result would inherit its inverse as a compensating transform — the node state the export gate refuses (#629) — so that is frozen into the vertices instead, with a warning saying so.
* **`pivot`** — `a`'s world-space pivot, not the new mesh's bounding-box centre. This is what makes `boolean_op` safe to use after `transform`'s `pivot` or `assemble`'s `pivots` (#603).
* **`uv_bounds`** — `[u_min, v_min, u_max, v_max]` of the result. `polyCBoolOp` keeps **each operand's own** UV layout, so the faces the cutter contributes arrive carrying the cutter's UVs: on an atlas-packed chunk cut with a default-UV cutter, the new face samples the whole atlas instead of its own patch, and nothing looks wrong until the material goes on. `b`'s UVs are folded into `a`'s bounds before the boolean runs (folding first, because once merged there is no reliable way to tell the two operands' UVs apart). `uv_bounds` is `null` when the result has no UVs at all.

**`new_name` may be `a`'s or `b`'s own name** (#640). Both operands are consumed, so "cut a socket into X and have the result still be called X" is the natural request — and it used to be inexpressible, returning `X_001`, because the name was reserved while Maya still held it: `polyCBoolOp` leaves both operands as emptied transforms until the construction-history delete reaps them. The result is therefore created under a staged name and claims the requested one immediately after that delete, which is the only moment it is free. A name held by an object this call does **not** consume is never stolen: the staged name stays and `warnings` says which object holds it.

**An empty result is refused, never reported** (#822, measured). `polyCBoolOp` answers a `difference` whose `b` covers `a`, or an `intersection` of volumes that never meet, with a mesh of no faces and no vertices — which `mesh_stats` reads as `watertight: true` — and it has consumed both operands by then. The handler deletes that empty mesh and refuses, naming the auto-checkpoint to restore. For `intersection` the obvious case is caught before anything is spent: two meshes whose world bounding boxes do not overlap (sharing exactly one face counts as not overlapping — that intersection was measured empty too) refuse with nothing changed. A `union` of disjoint meshes is a legitimate two-shell result and is never refused.

`deform`'s `deformer` is one of `bend`, `squash`, `twist`, `flare`, `sine`, `wave` (all `cmds.nonLinear` types), plus `sculpt` and `lattice`. `flare`, `sine` and `wave` are new in M2.4. Each type whitelists its own `params` keys (they land as attributes on the deformer node under exactly those names); `wave` is the one exception with no `lowBound`/`highBound` at all, since it bounds radially via `minRadius`/`maxRadius` instead.

**`sine` and `wave` lengths are scene units** (#822, measured). `cmds.nonLinear` scales its handle to half the mesh's largest extent (a 2-tall cylinder: 1, a 10-tall one: 5, a 4×1×1 slab: 2) and those two deformers read `amplitude`, `wavelength`, `offset` (and wave's `minRadius`/`maxRadius`) in handle units — so `amplitude: 0.2` moved the 2-tall cylinder 0.2 and the 10-tall one 1.0 before the fix. The handler now divides the length params by the handle's scale, so the same number means the same distance on any mesh; `max_displacement` on a 10-tall cylinder with `amplitude: 0.2` reads 0.2. `lowBound`/`highBound` stay handle-local (−1..1 spans the mesh), Maya's own convention, for every nonLinear type.

**Angle params are degrees** (`bend`'s `curvature`, `twist`'s `startAngle`/`endAngle`). Those attributes are angle-typed, and `cmds.setAttr` reads an angle in whatever unit the scene's UI is set to — so `deform` converts from degrees into that unit and the number means the same thing in every scene. `curvature: 0.35` is a third of a degree, which is what made `bend` look inert (#636); a visible hunch is 20–60.

`max_displacement` is how far the furthest vertex actually moved, in scene units, measured from the vertices before and after (not from the bounding box, which over-reports rotated meshes). When it falls below 1% of the mesh's own bounding-box diagonal, `warnings` carries one line naming the measurement and the usual reason that deformer type ends up inert. `lattice` is exempt: a freshly built lattice deforms nothing until its points are moved, so `max_displacement: 0.0` is the correct result there.

Viewport and camera:

| cmd | params | result |
|---|---|---|
| `set_viewport` | `{ show_grid?, show_light_icons?, show_camera_icons?, show_locators?, show_manipulators?, show_texture_placements?, wireframe_on_shaded?, display_lights? }` | `{ panel, show_grid, ..., camera, warnings }` |
| `set_camera` | `{ camera?, position?, look_at?, focal_length?, set_active? }` | `{ name, position, rotation, warnings }` |

**`set_viewport`'s icon and grid flags never reach a capture** (#829, measured). Every `capture_viewport` / `capture_turntable` frame forces `grid`, `lights`, `cameras`, `locators`, `manipulators` and `textures` **off** for its own shot and restores the panel afterwards — a capture taken with the grid on is **byte-identical** to one taken with it off. So switching one on changes what a human sees in Maya and nothing that comes back from a capture, and the result now says so in `warnings` rather than answering a caller who asked for a grid in their shots with a cheerful `show_grid: true`. `wireframe_on_shaded` and `display_lights` are NOT in that list: a capture reads them as its own `wireframe_overlay` and `lighting`. The panel state itself survives a capture unchanged, which the gate checks setting by setting.

`set_camera` aims exactly (#823, measured: the camera's forward axis against the vector to `look_at` reads 1.000000 from every position tried; a capture through it shows what sits in front of it), and `rotation` is Maya's own euler readback, which may be an equivalent triple rather than `[-elevation, azimuth, 0]`. `focal_length` is validated before anything is written: below 0.5 mm (Maya's own floor) or not a number is refused with nothing moved — it used to reach `setAttr`, which raised raw after the position had already landed.

## Commands (M2)

Perception:

| cmd | params | result |
|---|---|---|
| `get_object_info` | `{ name, include? }` | `{ name, transform?, mesh_stats?, uvs?, shading?, history? }` |
| `capture_turntable` | `{ target?, n_frames?, resolution?, shading?, lighting?, shadows? }` | `{ images: [{index, azimuth, png_b64, blank}], n_frames, warnings }` |

An empty `capture_turntable` `target` is REFUSED rather than read as "no target" (#797) — it used to orbit the whole scene under a name the caller thought was honoured.

Lighting and materials:

| cmd | params | result |
|---|---|---|
| `setup_lighting` | `{ preset, intensity?, hdri_path?, replace_existing? }` | `{ preset, lights: [...], removed: [...], checkpoint_id?, warnings }` |
| `assign_material` | `{ mesh, shader?, params?, name? }` | `{ mesh, material, shading_group, shader, warnings }` |
| `assign_pbr` | `{ mesh, maps, params?, name? }` | `{ mesh, material, shading_group, shader, maps, warnings }` |

`hdri_path` is read by the `hdri` preset and by nothing else (#797). Passing it with `three_point`, `single_sun` or `environment` is REFUSED, naming the preset: the directional presets build no dome, and `environment` is the dome that needs no file (a built-in V ramp). A non-existent ABSOLUTE `hdri_path` is refused before the `replace_existing` checkpoint — Maya does not fail on a missing texture, it lights the scene flat grey.

`assign_material` **refuses a top-level param it does not read** (#764), naming the key that was meant: `material` is called `name` here. It is the result field that gets called `material`, which is exactly why callers reached for it as the input key — and it was silently ignored, so the material quietly got the mesh-derived default name instead. Eleven tests in this repo passed `material=`; every one created a differently-named material than it believed it was creating, and every one passed, because they read the name back out of the result rather than pinning it. An unread key does not fail — it succeeds and does something else.

Since #767 this is not a special case: **every command refuses a top-level param it does not read**, and does so before touching Maya at all. See "The unknown-key contract" below.

**What an earlier call built is respected, not trampled (#804).** `assign_pbr` re-texturing a slot deletes the previous file node, its place2dTexture and any reverse/bump2d in front of it — but only what nothing else uses: a file node another slot or material still reads survives, and a warning names what still uses it. The swept names are reported per slot as `maps[slot].replaced`, and the new nodes take back the names the swept ones held. A `params` entry aimed at a plug a map already drives (this call's map or an earlier call's) is **refused before anything is built or moved**, naming the plug and the map — Maya raises "locked or connected" on that write, on a child of a fed compound, and on a compound with one fed child (measured). `assign_material` reusing an existing shader applies the same guard before the mesh is moved into the shading group. `setup_lighting` with `replace_existing` takes the old dome's ramp or hdri file node with the light (Maya never reaps a disconnected shading node), listing them in `removed` beside the transforms; a feed something else still uses is kept and named in `warnings`. `bake_textures` refuses a normal slot whose bump2d does not feed it directly (a reverse in between), before any bake, checkpoint or commit. `apply_texture_recipe` re-applied on a slot (#812) sweeps the network it displaces the same way - an earlier recipe's ramp, noise and bump2d, layeredTexture and mask, or `assign_pbr`'s file node and its place2dTexture - reporting them in `replaced`, keeping and naming anything something else still reads, and giving the new nodes back the base names (`mcpTex_ramp`, not `mcpTex_ramp_001`). Measured: Maya never reaps the node a force-connect displaces; a failed recipe leaves the previous network exactly as it was.
| `apply_texture_recipe` | `{ mesh, recipe, params?, slot? }` | `{ mesh, recipe, slot, nodes: [...], replaced: [...], warnings }` |

**A key INSIDE an `assign_pbr` slot spec is checked like a top-level one** (#797). `maps` is a known top-level key, so until now anything inside one of its per-slot objects went straight through: MEASURED on a probe, a `chanel` typo left the scalar reading the default channel `r` while the result reported success — the #764 failure exactly, an unread key that does not fail but succeeds and does something else. Each spec now takes `path`, `channel`, `invert`, `raw`, `mip_filter` and nothing else, and a foreign key is refused naming the slot (`assign_pbr map 'roughness' does not take 'chanel'`).

**Each `apply_texture_recipe` recipe declares the nested `params` keys it reads** (#797), which is the same gap one level down again. `noise_bump` reads `{scale, depth}` and `file_texture` reads `{file_path}`; anything else inside `params` is refused naming the recipe. `ramp_gradient` and `layered_mask` read **nothing at all** — their builders take the argument and never look at it — so any non-empty `params` is refused for them outright, rather than wiring Maya's default ramp and reporting success to a caller who asked for a scaled one. An empty `params` (or `null`) is "not passed" and is never refused: the MCP wrapper used to send `{}` on every call. A `file_texture` whose `file_path` is an absolute path that does not exist is refused **before any node is created**, by `assign_pbr`'s own rule — Maya does not fail on a missing map, it renders the file node flat and the material merely looks wrong, and paths resolve on the machine running Maya.

## Commands (M2.2)

| cmd | params | result |
|---|---|---|
| `render_scene` | `{ angles?, renderer?, resolution?, isolate?, target?, zoom?, relight?, samples?, fallback_light? }` | `{ images: [{angle, requested_angle?, png_b64}], camera_positions: [{angle, requested_angle?, label, position, rotation, camera, near_clip}], renderer, samples (null under hw2), fallback_light, warnings }` |

### A frame that draws nothing says so (#765)

Every captured frame carries **`blank`**, and a blank one is named in **`warnings`**. The frame is still returned — capturing an empty scene is a legal request — but it is never handed back as a plain success again.

The defect this closes: `capture_viewport` returned frames in which every pixel was transparent. Real RGB, zero alpha, so any viewer composited them to flat white while the tool reported success. A #669 live gate passed with one of those white squares in it, under its own instruction to "now LOOK at this".

**Pixel variety cannot detect it** — the broken frames carried 13 distinct pixel values against 15 for a correct capture of a cube. Opaque coverage can: **0 against 18872**. That is the same measure `render_scene`'s blank guard has always used; `capture_viewport` simply never had one. `blank` is `null` when the frame could not be measured at all, and that is reported too — "I did not check" and "I checked and it is fine" must not look alike.

**The cause, and the other half of the fix.** A Maya whose main window has **never been shown** draws nothing into an offscreen playblast — and every agent-launched Maya starts that way. `offScreen=True` does not save it and neither does the `M3dView.readColorBuffer` fallback. The discriminator is `isVisible()`, not `isMinimized()`: the blind session measured `minimized=False, visible=False`, which is why chasing minimisation led nowhere. One `show()` fixes it permanently for that process, and minimising the window again afterwards does not break it, because the surface stays valid once created.

So `capture_viewport` and `capture_turntable` now show an unrealized window before capturing, and **say so** — making a window appear is a visible side effect, and a capture's contract is that it has none. It only ever fires on a window nobody is looking at: an interactive session has a visible window by definition.

**What that note may claim (#826).** It used to say "this call showed it. That is a visible change to the screen", which is an assertion about the screen that the call making it cannot check. MEASURED on virgin agent Mayas: `show()` sets `isVisible()` True **synchronously**, inside the calling command, and the window can be hidden again by the very next command — with neither `QApplication.sendPostedEvents` nor `processEvents` revealing the difference from in there. The two outcomes are indistinguishable at the moment of speaking, so on those processes the tool announced a window that never appeared, and announced it again on every later capture because visibility never latched.

What is undone is the process's **first** `show()`, not "a show during Maya's first seconds": the #826 gate reproduced it on a Maya 67 s old, and the next `show()` stuck for good. That is the shape #825 saw from outside — the note on captures 1 and 2 and never again.

So the note reports **across calls** rather than asserting inside one, and each of three facts is said at most once per process:

| what the capture found | what it says |
|---|---|
| window hidden, nothing said yet | it **asked** Maya to show it, and that the outcome is not measurable from inside this call |
| still hidden on a later capture | the earlier request **did not take**, nothing appeared, asked again |
| visible on a later capture, after we asked | the window **is up on screen now** — the visible change, reported when it is true |

The `show()` itself is retried on every capture regardless, because that is #765's protection and it costs nothing. A window that was never hidden is neither shown nor mentioned. Gate: `evals/realized_note_live.py` (25/25), which forces both outcomes — the undone one with a one-shot event filter that hides the window one event-loop turn after it is shown.

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
| `render_sheet` | `{ subjects, angle?, renderer?, resolution?, isolate?, samples?, zoom?, relight?, fallback_light? }` | `{ images: [{angle, label, png_b64}], camera_positions: [...], renderer, samples (null under hw2), fallback_light, warnings }` |

`angle='current'` is REFUSED on `render_sheet` and `preview_clip` (#797): each places its own camera per cell / per frame, so there is no viewport camera to keep, and the cells would have been shot as `three_quarter` under the wrong label. `render_scene`'s `angles: ["current"]` still degrades to `three_quarter` offscreen (its schema promises it), but the frame and its `camera_positions` entry are labelled with the angle that was actually SHOT, with `requested_angle: "current"` alongside and one warning. `samples` is `null` under `hw2`, which has no AA sample count; asking for one there is answered with a warning rather than an echo of the number.


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

**`capture_viewport` says when the `target` it framed is hidden behind another mesh** (#824). The camera is placed from the target's bounding box alone, so an object standing between them fills the frame: measured on a red cube at +Z and a blue one at −Z, `back` + `target=|red` came back 65536/65536 blue pixels, zero red, `blank: false`, no warning — the caller asked to see the red cube and got a success holding none of it. The blank guard cannot see this (the frame is full of pixels), so after `viewFit` the handler casts nine rays from the camera to the target's world bbox (centre and eight corners) against every other visible mesh (`MFnMesh.closestIntersection`; 11 ms for nine rays against 40k faces). All nine blocked → a `warnings` entry naming the angle, the target and the occluder, and pointing at `isolate`; some blocked → "partly hidden, N of 9". It is a WARNING, never a refusal: framing a part with its surroundings in shot may be exactly what was asked. What cannot hide the target is excluded by measurement: its own shapes (a grouped target's far corners are reached through its own near member — 4 false blocks of 9 until excluded), a deformer's intermediate `ShapeOrig` (listed as visible geometry, draws nothing), anything `isolate` hides, and a floor the target stands on (rays to the bottom corners hit the plane exactly at the corner, so a hit within 1e-4 of the sample distance is not a block). Only meshes are asked. If the measurement itself fails the frame still comes back and the warning says it could not be measured. `capture_turntable` isolates its target and is unaffected.

`target` is REFUSED by `capture_viewport` when every requested angle is `current` (#797): the current angle keeps the panel's own camera and frames nothing, so the name was read, validated and dropped — and `_scene_bbox`, the only existence check `target` gets, never ran, so a typo came back a success. On a MIXED list `target` is kept (the other angles consume it), the name is existence-checked on the current frame too, and a warning says that frame was not framed on it.

**A frame drawn by the M3dView fallback says what size it really is** (#797). `capture_viewport`, `capture_turntable` and `compare_to_reference` all pass `resolution` to `playblast`, which honours `widthHeight` — but when the playblast fails, the fallback reads the active view's own colour buffer, and that is whatever size the user's panel happens to be. Nothing said so, so a caller measuring pixels off the image had no way to know its scale had changed under them. `warnings` now names the drawn size against the requested one, per frame, and only when the two actually differ.

**Three viewport flags VP2 accepts and then does nothing with are WARNED, not refused** (#797), because the underlying VP2 behaviour is unmeasured and a frame that comes back is still a frame — it just does not carry what was switched on. `lighting='scene'` in a scene holding no light draws the subject dark against a background that still renders, so the blank guard cannot catch it (the question is asked through `lighting.light_shapes`, the one place that knows Arnold's lights are lights, and a scene lit only by a dome does not read as unlit). `shadows=true` under `shading='flatShaded'` or `'wireframe'` comes back without them — a shadow is darkening applied to a shaded surface and neither mode draws one. `buffer='ssao'` under `shading='wireframe'` is the same argument: ambient occlusion darkens the crevices of a drawn surface, and a wireframe draws none, so the frame is identical either way. This is the discipline `render_scene`'s `fallback_light` already followed: a caller who switched something on and reads a frame without it concludes the subject has no self-shadowing, not that the mode they chose cannot show one. MEASURED since (#814, #815): all three warnings are accurate, and under `smoothShaded` the shadow IS drawn - a VP2 depth-map shadow needs a light with `useDepthMapShadows` on (directional, spot or point all cast one) and `lighting='scene'`; a top-ish view shows it, while from `three_quarter` a subject's own body can hide most of its shadow (a unit cube on a small ground changed 2 pixels at 256 px - the scene, not the flag). `buffer='ssao'` under `smoothShaded` changed 1.7 % of pixels; under `wireframe`, none.

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
| `uv_atlas` | `{ names, patch?, cols?, rows?, margin?, project?, normalize?, world_scale?, uv_per_metre? }` | `{ meshes: [{name, uv_bounds, inside_patch}], atlas, patch, patch_rect, margin, projection, normalized, world_scale, uv_per_metre, all_inside, warnings }` |

**`patch` is an integer index or an explicit `[col, row]`** — index 0 is the
top-left patch and the index counts along the row first, the way the atlas image
reads in a viewer. The integer form was documented but *refused* (#640): the MCP
tool typed the parameter as `object`, which constrains nothing and therefore
coerces nothing, so `patch: 0` could arrive as the string `"0"` and the handler
rejected it with an error naming the very form it had just been handed. The schema
now declares a real `int | [int, int]` union, and the handler reads a numeric
string as the integer it is, since the plugin is reachable over raw TCP where
nothing validates at all. Non-numeric text, floats and booleans are still refused.

**`project` of `keep` or `planar` is REFUSED with `world_scale`** (#797), and this one was destructive rather than merely ignored: the world branch calls `polyAutoProjection(scaleMode=0)` on every shape unconditionally, so a layout the caller asked to KEEP was box-projected over and the call still reported success. `box` is what world mode already does and is never refused. Drop `world_scale` to preserve an authored layout, or drop `project`. (`normalize` under `world_scale` is a different case and stands: the result reports `normalized: false`, so nothing is claimed that was not done.)

**`planar` projects along the mesh's best-fit plane and says what it collapsed** (#822, measured). It used to be `polyProjection md="z"`, which is **world** −z whatever the mesh faces: a sheet standing up (facing X or Y) got every one of its 16 faces collapsed to zero UV area, a cube 4 of 6, a sphere its far 200 of 400 faces mirrored over the near ones — all reported `inside_patch: true` with no warning. The projection now runs along the axis the mesh is thinnest on in world space (a cube, being a tie, keeps z — Maya's own `md="b"` "best plane" collapsed the standing sheet under a headless Maya while working in the GUI, so it is not relied on), and the handler measures every face's signed UV area after the projection: `warnings` names, per mesh, how many faces have zero area (edge-on to the plane) and how many are mirrored. A flat sheet warns about nothing; a solid warns on both counts, and the hint is `project: box`.

**`uv_per_metre` is the world branch's density constant, so it is REFUSED without `world_scale`** (#797) — it scales a world-proportional projection, and the normalising branch fits each mesh to the patch instead, where no density constant is read at all. It is a raw-TCP/generator key the MCP wrapper never sends. The result field is now the APPLIED value, never the requested one: `null` outside world mode, and inside it either the caller's number or the constant derived from the scene's linear unit. It used to echo a value back on every call, world mode or not, which stated a texel density for a pack that gave every mesh a different one. `warnings` is real too — protocol.md has listed it in this row since M2.3 and the handler never sent it, so `UvAtlasResult` dropped it on the floor.

## Commands (M2.4)

| cmd | params | result |
|---|---|---|
| `array` | `{ name, mode, count?, axis?, center?, angle?, offset?, step_rotate?, step_scale?, pivot?, name_prefix?, group_name? }` | `{ names: [...], mode, group, signed_volume, warnings }` |

**`name_prefix` is a prefix for `radial` and `linear`, and the NAME for `mirror`** (#640). An array of 12 needs 12 distinct names, so those two append `_1`..`_N`. A mirror makes exactly **one** copy, so numbering it was never collision avoidance — it cost the #601 golem run 11 renames, one per mirrored chunk, and nothing in the scene held any of the un-suffixed names. Pass `name_prefix='golem_R_arm'` to a mirror and the copy is called `golem_R_arm`. If that name really is taken, a suffix is added *and* `warnings` says so, because a silent rename is what made the caller check all eleven by hand. Omitting `name_prefix` still gives `<source>_1`: the fallback stem is the source's own name, which is by definition taken.

**Every placement param belongs to a mode, and the wrong mode refuses it** (#797). `mirror` reads `axis` and `pivot`; `radial` reads `count`, `axis`, `center`, `angle`; `linear` reads `count`, `offset`, `step_rotate`, `step_scale`. `name`, `mode`, `name_prefix` and `group_name` are common to all three. Before this, nothing on the wrong mode was even validated — a probe pushed `center=[1, 2]` (two numbers, not three), `angle=720` and `offset='garbage'` through a mirror call and all three succeeded, because `_mirror` never looks at any of them. `count` on a mirror was the same lie the other way: documented as ignored, so a caller asking for 9 got 1 and was told nothing. A `linear` `offset` of `[0, 0, 0]` with no `step_rotate` and no `step_scale` is refused as well — every copy would land exactly on the source, the same reason `radial` refuses `angle=0`; with a step the copies genuinely differ (nested shells, a turning stack) and the call proceeds.

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

`method` picks the initial weighting. `closestDistance` weights by
straight-line distance, so it reaches across gaps: two legs 4 cm apart, left
hip bent 45°, drags the right leg 18.6 cm (measured, #821). `geodesicVoxel`
measures distance through the mesh's volume and moves the other leg 0.0 mm
on the same rig. Maya's `skinCluster(bindMethod=3)` computes **no weights**
at all (every vertex lands at 1.0 on the last influence, reported as
success); the real bind is the separate `geomBind` command, so the handler
binds `closestDistance` first and then runs geomBind at Maya's UI defaults —
resolution 256 (0.66 s on 400 verts, 1.4 s on 20k), falloff 0.2 — which
leaves a `geomBind` record node on the skinCluster (one undo step removes
both). A geodesic bind whose table still shows the untouched default (every
vertex at 1.0 on one joint) is **refused** and unbound again. Both
`geodesicVoxel` and `heatMap` need a volume: a flat mesh (zero extent along
one local axis) is refused before Maya sees it, because a zero-volume sheet
gets that degenerate table from geomBind silently and hangs Maya under
heatMap (#797, >6 min). `heatMap` on a closed, open-pipe, two-shell or
self-intersecting mesh binds in 2.5–4 s in a GUI Maya. Both geomBind and
heatMap need a GL context: a headless mayapy raises "Unable to create an
offscreen OpenGL buffer", which the handler turns into a refusal that
unbinds the closestDistance skin it was about to refine, so no silent
substitute survives.

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
has no plane of its own, so it folds toward world **+Z** — the ikHandle's
default pole vector, MEASURED on every run of #814's probe, not a guess — and
a warning says so; pass `pole` to choose the side (a given pole put the knee
exactly where it pointed on all four sides tried, over a small pre-bend too) (a straight chain is quietly pre-bent
a few degrees toward the pole so the RP solver can fold at all; the solve
overwrites the nudge). A `pole` that lies ON the start→target line is refused: the pole vector is then parallel to the handle vector, so there is no bend plane — Maya builds a degenerate constraint, the pre-bend is skipped, and the straight-chain warning cannot fire because a pole WAS given (#797). "On the line" is measured against the chain's own reach.

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

**An `exclude` entry that matched no chunk is warned BY NAME** (#797). The filter is a deliberately forgiving substring match — a typo excludes nothing rather than refusing the call — but `maya_author_physics` promises that every exclusion is warned by name, and a dead entry that dropped nothing used to say nothing at all. The warning quotes the entry verbatim (not the lowered form it was matched with), names the root it was matched under, and offers the closest chunk short names as a "did you mean".

**A SKIPPED chunk is not a valid parent** (#797). A chunk whose mesh cannot be read, or which carries no triangles, is skipped with a warning and never becomes a body — but the parent lookup maps were built from the requested chunk list *before* anything had been read, so a skipped chunk still answered as a valid parent on both paths, and a joint was emitted against a body that does not appear in `bodies` at all. Every chunk's geometry is now read FIRST, so the skip set is fully known before any parent resolves against it: an `overrides` entry naming a skipped chunk as its own subject is dropped with a warning saying which chunk was skipped and why; an override naming a skipped chunk as `parent` warns and falls back to the DAG ancestor, exactly as an unnamed parent would resolve; and the DAG walk itself now steps past skipped chunks to the next real body.

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

**A `targets[i]` entry takes `name` and `target_mesh` and nothing else** (#797). `targets` is a known top-level key, so a key inside one entry used to go straight through — the #764 shape one level down, where an unread key does not fail but succeeds and does something else, here by wiring a target the caller believed they had configured. The check is a plain dict-key comparison, so it runs with the rest of the pure validation, before `_cmds()` matters and well before the checkpoint, and the refusal names the index (`create_blendshape targets[1] does not take …`). The MCP schema forbids the same keys at the wire (`BlendshapeTargetSpec` is `extra="forbid"`), so an MCP caller is answered by the schema and a raw-TCP caller by the handler.

`set_blendshape_weights` drives the named weights (0..1, absolute), lands
them sequentially in call order, and measures per step; the returned
`weights` map is every target re-read from the node. All-zero weights IS
the reset — the phase-1 pose-map currency is untouched.

Export: shapes ride along automatically (`FBXExportShapes` pinned on —
there is no parameter). The byte gate refuses an export whose scene
declares a target the file does not carry, and the result's `shapes` block
reports each channel's name and delta payload as read from the bytes.

## Commands (deformation quality / #771)

| cmd | params | result |
|---|---|---|
| `apply_delta_mush` | `{ mesh, smoothing_iterations=10, smoothing_step=0.5, pin_border_vertices=true, distance_weight=1.0 }` | `{ mesh, delta_mush, worst_edge_ratio_before, worst_edge_ratio_after, max_displacement, warnings }` |
| `add_corrective` | `{ mesh, target, joint, rotation: [rx,ry,rz] }` | `{ mesh, blend_shape, target, joint, interpolator, pose_name, pose_index, weight_at_pose, weight_at_rest, corrective_displacement, warnings }` |

`apply_delta_mush` relaxes skinning artifacts with one deltaMush at the
END of the deformation chain (blendShape → skinCluster → deltaMush,
measured). It is exactly identity at the bind pose, so the report's
edge-stretch ratios (current world edge length over the orig shape's bind
length — the humanoid gate's tear currency) are measured **at the current
pose**: pose the rig first, or both ratios read ~1.0 and the result warns.
Refusals: unknown params (#764 synonym map), no skinCluster in history
(nothing to relax — `bind_skin` first), a second deltaMush (stacked
smoothing is unexplainable — `delete_objects` the first).

`distance_weight` defaults to 1.0, NOT Maya's 0.0: uniform smoothing on
this toolbox's primitive meshes (2 mm circumference rings beside 70 mm
length edges, the #669 anisotropy) measurably spikes tiny edges to 8.9x
their bind length — a visible 17 mm tear — while distance-weighted
smoothing removes the spike and still relaxes (measured: humanoid crouch
1.943 → 1.540, extend 2.026 → 1.535).

Order matters, measured: creating a NEW blendShape on a mushed mesh hangs
Maya's deformer reorder 20+ minutes, so `create_blendshape` REFUSES the
node-creation path while a deltaMush is in history (adding targets to an
existing node is instant and stays allowed). Author shapes first, mush
last; re-applying a deleted mush is instant and identical.

`add_corrective` completes the phase-5 story: an EXISTING blendshape
target (authored with `create_blendshape`) fires **at a joint angle**
instead of at a hand-set weight. One poseInterpolator per driver joint
(created on demand with neutral poses recorded at rest, reused by later
correctives on the same joint) drives the weight through `output[pose]`:
measured 0.0 at rest, 0.5 at half the trigger angle, 1.0 at the trigger.
`rotation` is local degrees — the exact `pose_skeleton` currency. The call
verifies its own wire (`weight_at_pose` re-read through the real graph at
the trigger; an inert wire refuses and rolls back) and restores the
joint's rotation. Refusals: unknown params; no blendShape / unknown
target; joint missing or not a joint; all-zero rotation (that IS the
neutral); a target already driven (a clip's curves, a set-driven key,
another corrective, or any other connection - each named as what it
actually is); a driver joint this handler cannot pose (locked or
connection-fed rotation, including animation curves); an unreadable
`mcp_correctives` record (refused rather than silently overwritten -
overwriting would erase every prior pose's memory). A second target at
(nearly) the same rotation - within 1 degree of a pose this tool already
recorded in the interpolator's `mcp_correctives` string attr - REUSES
that pose rather than stacking a near-duplicate that would ill-condition
the interpolation: both weights ride one pose, and the result says so in
`warnings`. The poseInterpolator plugin is loaded on demand and its
absence refuses with a hint.

Removal: `delete_objects` the interpolator's transform — every weight it
drives returns to static control. There is no per-pose removal (v1).

Guard closures that arrive with this surface (one shared classifier,
`clip.driven_weight_source`, so every guard names a weight's owner as
what it actually is — a corrective, a set-driven key, or another
connection — instead of misdiagnosing anim-layer/expression sources):
- `set_blendshape_weights` refuses a REQUESTED weight that a connection
  drives (a hand-set value cannot land on a connected plug — measured);
  a corrective on one target does not lock the others.
- `author_clip` refuses a `blend_weights` channel that a connection
  drives — measured: `setKeyframe` on a connection-fed plug silently
  no-ops (returns 0, creates no curve), so without the refusal the clip
  would ship without a channel it claims to key. Key the JOINT instead;
  the corrective follows it. Boundary pins for OTHER clips' channels
  that became driven out-of-band are skipped with a warning rather than
  claimed as pinned.
- `author_clip` refuses a JOINT channel a **set-driven key or a
  corrective** drives, for the same measured reason and **per channel,
  never per rig** (#796). The channels asked are exactly the ones this call
  DECLARES: every rotate channel of every joint named in
  `keys[].rotations`, plus the root's three translate channels when any key
  carries `root_position`. A driven key anywhere ELSE on the skeleton does
  not block the call — that rig setup is none of this clip's business, and
  blocking on it made a rig carrying a driven key unable to author a first
  clip. The refusal names the channel and its source; for a driven key the
  hint says to pose the DRIVER (`delete_clip` does not remove one — see
  below), not to delete the clip.
- `author_clip` refuses a declared channel a rigger **LOCKED** (#798),
  before the checkpoint, with the same hint every static-write guard gives
  (`setAttr -lock false <plug>`). Measured: `setKeyframe` on a locked plug
  reports 0 and creates nothing (a driven key's tell), and the root's
  `xform` pose write drops a locked child WITHOUT raising — so a locked
  `root.translateY` used to ship a clip declaring `root_position` with one
  of its three channels never written. Declared channels only: a lock
  elsewhere on the rig blocks nothing.
- **Only those kinds refuse.** Any OTHER connection on a declared
  channel — a pairBlend (which Maya inserts the moment a plug is both keyed
  AND constrained), an anim layer, a unitConversion — is keyed exactly as
  it was before #796 and NAMED in `warnings`, with the curve behind the
  intermediary spelled the way `guard_static_pose` spells it (`<curve>
  behind <node>`), so one scene gets one diagnosis. Nothing has measured
  that a key fails to land through such a node, and refusing on that
  guess would stop a keyed-and-constrained rig that authors clips today.
  A connection landing on the `.rotate`/`.translate` COMPOUND (where a
  rotation anim layer lands) covers all three children and is reported
  once, at the compound; the children are asked first, so a driven key on
  one axis is never blamed on a free sibling.
- **Boundary pins are skipped, not refused**, on a JOINT or root-translate
  channel a driven key or a corrective owns, or that is locked (#798) — the
  treatment the weight pins
  have had since #771, extended to the other two pad loops (#796). A pad
  channel belongs to some OTHER clip, so refusing it would block this call
  over rig setup it never asked to touch; instead the pin is skipped, the
  channel is named in `warnings`, and the free channels on the same joint
  are still pinned. A channel whose whole triple is skipped never appears
  in `padded_channels`/`held_channels`.
- A pad channel an INTERMEDIARY feeds is still pinned (same reason as the
  declared case above) and gets **the same note the declared path gives**,
  from the same helper — one scene, one diagnosis, whether or not the clip
  happens to declare the channel. Before this it was pinned, counted, and
  reported “pinned … at rest” with nothing said about the connection.
  A pad channel driven by another clip's own curve — which is every normal
  pad channel — stays silent.
- **The replace-cut is partitioned too.** Re-authoring an existing name
  clears that clip's old frame range across the whole hierarchy, and a
  set-driven key's curve is indexed by DRIVER VALUE: `time=(0, 30)` on one
  is the driver interval 0..30, so the cut would destroy driver keys whose
  NUMBERS fall in the replaced clip's frame range. Those plugs are stepped
  around and named in `warnings`; plugs with a clip curve, and plugs with
  no curve at all, are cut exactly as before. The skip attributes to the
  channel that is actually connected: a driven key behind a pairBlend on
  `tip.rotateX` does not spread the skip — or the warning — onto the free
  `tip.rotateY`/`.rotateZ`, which are still cut. A connection landing on
  the `.rotate` COMPOUND does cover all three, because there it really
  does. `retarget_clip`'s re-retarget of an existing name shares the
  function and the behaviour. Its cost was measured (#798): the blend walk
  adds ~5 connection queries per plug, 2130 vs 360 on a 60-joint rig, for
  48 ms inside a 220 ms re-author — not worth a cache.
- `clean_clip`'s filter pass smooths the CLIP partition only (#798). The
  raw `type="animCurve"` query also returns set-driven-key curves, which
  are indexed by DRIVER VALUE: measured, `getAttr(time=f)` on such a plug
  answers the driver's constant at every frame and the re-key reports 0
  every time, so the pass listed the channel as smoothed having changed
  nothing. It now reads `setKeyframe`'s return too: a channel whose re-keys
  vanished (a plug locked after it was keyed) is named with its cause; one
  whose every re-key vanished is not counted, one that partly landed is
  counted and named. The contact-lock pass reads that return too (#797): a
  run whose keys did not land is named with its cause and never reported
  as locked, and a frame counts as pinned only when the whole solved pose
  landed on it. An explicit `filter['window']` longer than the clip is
  refused — `smooth_track` shrinks its window per sample, so window 31 on
  a 30-frame clip IS window 29 and the warning would still say
  `window=31`. A clip of 4 frames or fewer cannot be smoothed at all (every
  shrunk fit is exact); the pass says so instead of claiming it smoothed
  anything.
- **What the result says is what the writes REPORTED** (#796).
  `cmds.setKeyframe` returns the number of keys it set, and #771 measured 0
  as the tell on a connection-fed plug — no curve, no key, no error. Every
  call site used to discard that number, so the handler guessed which
  writes landed. Now `keyed_joints`, `keyed_weight_channels`,
  `root_position_keyed` and the `mcp_clip` record itself count only
  channels whose key actually exists; a channel whose every write vanished
  is named in `warnings` — the note itself says what swallowed the write
  (a lock, a driven key, a corrective, a blend node), from the one
  classifier every static-write guard in this toolbox asks (#798; it used
  to point at "the note naming what drives it", which did not exist for a
  lock) — and is absent from all of them, and a clip that keyed NOTHING says so in one
  loud warning rather than registering as a normal take. A pin that did not
  land is likewise never counted in `padded_channels`, `held_channels` or
  `back_filled`. `root_position` loses its keys one step earlier than the
  others and reports them the same way: placing the root is a STATIC
  `xform` write, which a connection-fed plug refuses outright, so on a
  keyed-and-constrained root the three translate channels are reported as
  writes that did not land instead of raising a traceback after the
  auto-checkpoint. Every other channel of that same key — the rotations,
  the blend weights — still lands and is still declared. Still a warning and not a refusal: what a key does through
  an intermediary is unmeasured, and the report just has to be true under
  both outcomes.
- **`retarget_clip`'s bake writes six channels, never scale** (#810).
  `bakeResults` with no `-attribute` flag keys every keyable channel of
  the joints it is aimed at - MEASURED: 45 constant-1.0 scale curves per
  retarget on the humanoid, exported as 15 "Lcl Scaling" curve nodes in
  EVERY later take, and invisible to `delete_clip`, which walks rotate +
  translate, reported 90 deleted, left the 45 standing and then refused
  "no clip exists" on a rig still keyed. HIK writes rotation and root
  translation only, so the bake is now aimed with `-attribute` at exactly
  those (`retarget.BAKED_ATTRS`), and `delete_clip` reaps what earlier
  bakes left: a scale curve whose every key is exactly 1.0 is the bake's
  signature and is deleted and counted in `reaped_scale_curves`; a scale
  curve carrying any other value is someone's squash-and-stretch and is
  kept and named; a rig whose only keys are such leftovers no longer
  refuses - it reaps them and says so.
- `retarget_clip`'s `fps` is refused on the .fbx route (#797): the file
  bakes at its own rate, and a different `fps` has not been measured to
  resample correctly. BVH keeps it. Fractional `start`/`end` are rounded to
  whole source rows, with a warning naming the row used.
- The .fbx route reads the FILE, not the scene (#814 - the route had never
  run live, and its first run refuted every assumption it was written on).
  MEASURED on Maya 2027: fbxmaya's default import mode is **merge**, so a
  file whose joint names are already in the scene - a target rig built from
  the same names, the ordinary case - wrote its keys straight onto the
  TARGET RIG and created no joint; the route then refused "imported no
  joints" with the caller's rig already animated. The import now forces
  `add` mode and sets the CURRENT namespace for its duration (the file
  command's `namespace=` flag lands the nodes in `ns1`, outside the reap),
  and restores both. The import does not change the scene's time unit
  (`FBXImportSetMayaFrameRate` changed nothing), so a 60 fps take in a
  24 fps scene sits on fractional frames 0..62.8; the rate is now read from
  the spacing of the take's own keys, the scene is put in that unit, and
  the range is read in the file's frames. The importer's unit conversion
  arrives as a scale on the imported ROOT JOINT (100 for a file declaring
  metres in a centimetre scene); the source-to-target scale factor
  MULTIPLIES it rather than replacing it.
- `retarget_clip` shares the same rules for the channels IT writes (#796):
  the "hand-authored curves" refusal counts clip curves only (a driven key
  on the target no longer masquerades as hand-authored animation and sends
  the caller to a `delete_clip` that refuses the rig), and the HIK slot
  joints it bakes are asked the same per-channel question. **The channels
  asked are the ones `bakeResults` actually writes**: with no `-attribute`
  flag it bakes every KEYABLE channel of each slot joint, so the question
  is asked of the rotate, translate AND scale triples (each with its
  compound, where an anim layer lands) plus every other keyable attribute
  Maya reports for that joint — `visibility`, and any keyable attribute a
  rigger added, a squash-and-stretch driver among them. That list is asked
  of Maya (`listAttr -keyable`), never guessed; a joint that cannot answer
  costs the widening and says so in `warnings`, with the three triples
  still checked. It WARNS where `author_clip` refuses: the measured no-op
  is a `setKeyframe` measurement, and what `bakeResults` does to a
  connection-fed plug is not measured here, so refusing on it would refuse
  on the wrong measurement.
- **A retargeted take is self-contained too** (#798; before it, #796 had
  named the gap and left it). The #718 pass author_clip runs is one
  function now, `clip.make_self_contained`, and `retarget_clip` runs it
  after the bake: a channel some OTHER clip declares and the bake does not
  cover (a blendShape weight, a finger, a jaw) is pinned at rest at this
  take's own boundary frames (`padded_channels`), and the baked joints —
  plus the root's translation when the root is a slot joint — are pinned
  at their STANCE rest across every earlier clip's range (`back_filled`),
  so those clips measure what they measured before. The record declares
  what the bake actually left in the scene: the slot joints whose rotate
  channels carry a clip curve keyed inside the take's range, and
  `root_position_used` when the root's translation got the same (derived
  from the scene, never from the aim list), so a LATER `author_clip` pins
  against this take like any other. Measured before the fix: the walk's
  slot joints held its LAST pose across the whole of the idle take
  authored after it, and idle's back-fill of the head — a slot joint with
  no recorded rest — wrote the walk's FIRST head value over its last
  frame. The rotation rest is captured at the same stance the hips height
  is read at, before the bake; the root's translation rest before the
  replace cut, where a curve-fed root is skipped rather than read at a
  post-cut static value. A slot joint the bake left without a rotation
  curve is named in `warnings` and not declared. The bake's scale curves,
  and its translate curves on slot joints other than the root, stay
  outside the clip model as before — constant when the rig's root IS the
  Hips joint; when the Hips slot sits BELOW the root its baked translation
  carries the root motion and nothing pins it, which `warnings` now says.
  The re-retarget cut clears weight plugs too, since this producer pins
  them.

Export facts (measured, `evals/correctives_probe/`): a live deltaMush is
DROPPED by FBX export with byte-identical output — `export_fbx` warns,
naming the node, and the relaxation exists only in Maya. A driven
corrective weight, by contrast, ships automatically: the animated export's
bake resamples it into real per-frame `DeformPercent` curves in each take
(reimport tracks the driver), with no in-scene baking and no declaration —
the animation gate checks declared clip channels only, and corrective
curves ride as tolerated extras.

## Commands (rigging phase 6 / clips / #695, multi-take #718)

| cmd | params | result |
|---|---|---|
| `author_clip` | `{ root, name, fps=30, keys: [{time_s, rotations?, blend_weights?, root_position?}], interpolation, loop }` | `{ root, clip, fps, duration_s, frames, keyed_joints, keyed_weight_channels, root_position_keyed, interpolation, loop, start_frame, end_frame, clips, padded_channels, held_channels, back_filled, replaced, per_key, warnings }` |
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
| `delete_clip` | `{ root, name? }` | `{ root, clip, clips, deleted_curves, reaped_channels, reaped_scale_curves, max_displacement, warnings }` |

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
  teardown as before #718: every **clip** curve deleted, every keyed weight
  channel zeroed, the bind pose restored. `clips` in the result is then
  always `[]`. When `name` was omitted and several clips existed before the
  call, every one of them was torn down, but `clip` in the result names
  only the FIRST of them (the pre-delete list, index 0) — it does not
  enumerate the delete. Read `clips` (now empty) and `warnings` for the
  full story; treat `clip` here as naming one clip, not the scope of what
  was removed.

**The teardown leaves set-driven keys standing (#796), so "returns the
skeleton to static posing" is CONDITIONAL.** A U-typed animCurve
(`animCurveUU/UL/UA/UT`) reads a driver attribute rather than time: it is
rig setup, not clip motion, and `delete_clip` never removes one — even
though `listConnections(type="animCurve")` returns it alongside the clip
curves, which is how the teardown used to eat it. What follows from that:

* Channels a driven key feeds **stay driven** after a full teardown. A
  `warnings` entry names every curve that was kept and says so; a rig
  carrying nothing but driven keys is refused with `no clip exists` rather
  than torn down.
* A partial delete never `cutKey`s a driven-key plug (that curve is indexed
  by DRIVER VALUE, not time, so a time range means nothing on it), and the
  #730 reap never removes one. `reaped_channels` reports what was actually
  FOUND to delete, not what the doomed record declared — an orphaned
  channel that turns out to be a driven key is absent from it.
* Where a joint short name and a blendShape weight alias collide (a `jaw`
  joint and a `jaw` shape), `reaped_channels` qualifies both — `jaw
  (joint)`, `jaw (blend weight)`. Names that do not collide are unqualified.
* The no-bind-pose fallback (an unbound rig: no skinCluster, so no bind
  pose to restore) zeroes rotations, but `setAttr` on a connection-fed plug
  RAISES — so a rotate channel some connection still feeds is left as it
  is and named in `warnings`, along with why. The free channels on the same
  joint are still zeroed.
* The BOUND branch — any rig with a skinCluster has a bind pose, so this is
  the common one — restores that pose with `dagPose -restore`, which writes
  the same connection-fed plugs. `warnings` names every joint and axis the
  restore could not return to bind, in the same words the fallback above
  uses, and it names TRANSLATE channels too (a `dagPose` restores a whole
  transform, so a connection on `.translateY` defeats it exactly as one on
  `.rotateX` does). If the restore itself raises, the teardown does **not**
  die half-done: the raise is reported in `warnings` and the clip metadata
  is still removed, so the rig never keeps reporting a clip it no longer
  has. That catch is narrow — with nothing driving the skeleton, a failing
  restore has no #796 explanation and still propagates as an error.

Both directions report the measured displacement of the return.

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

**More than 4 influences per vertex is warned, not refused** (#817). The skin
block reports `max_influences` (the most clusters carrying a non-zero weight
for any one vertex, read from the file) and `vertices_over_4_influences`, and
when the latter is non-zero `warnings` carries one line naming both and what a
consumer that caps influences at 4 does - Unity's default import does, MEASURED
in #743/#748 as `bones_per_vertex_max = 4`: it keeps the 4 heaviest and
renormalises, so those vertices deform differently there than in Maya by an
amount that grows with joint rotation on deep chains (#748 measured ~3 % of the
curl on the drifter's tendril, ~0 at rest). `maya_bind_skin` allows 8 on purpose,
and a consumer that reads 8 keeps them all, so the export goes ahead; rebind
with `max_influences=4` for a capping consumer.

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
carry. **`slots: []` is refused naming the slot clause** (#797): an empty
list is a valid list of slot names that selects NO slot, so every
candidate job was filtered out and the refusal blamed the SCENE ("no
procedural texture network to bake") for a fault in the CALL — and it
dropped the "for slot(s) …" clause it prints for every non-empty list,
because an empty list is falsy. An empty selection is malformed whichever
way the scene is shaped, so it is answered before the job list is consulted; omit `slots` to mean "every procedural slot". The rewire is persistent — the next render, and the next
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

**`curvature_radius` and `curvature_output` are refused when `curvature` is not in `maps`** (#797) — the same shape as `apply_ao=true` without `"ao"`, one level down. Both are read by the curvature shader and by nothing else, so on any other map list they were range-checked and then dropped: the caller tuned a radius, got the same AO, and was told nothing. The refusal names the map list that ignores them. Omitting either means "not passed", and the handler applies its own default (`0.1` and `convex`) — the MCP wrapper sends `null` for both on every call rather than a filled-in default, precisely so a value in the params is a value the caller chose.

The bake phase mutates nothing: the map shaders render via
`arnoldRenderToTexture`'s `-shader` flag and are **never assigned** to the
mesh (measured). Each bake runs one mesh into a private empty folder —
Arnold names its own outputs and renames them on short-name collisions, a
rule this tool refuses to model, which is also why two requested meshes
sharing a short name refuse upfront. A UV-less mesh refuses upfront too:
Maya does not — it returns success and writes a corrupt EXR that only
fails at read (measured). UV shells must not OVERLAP: overlapping shells
(box projection on a torus, or on a capped cylinder) rasterize
conflicting surfaces into the same texels, and a buried or down-facing
surface — honestly black — can win every texel it shares (measured: a
collar's whole AO baked uniform black through box-projected UVs and
correctly through its native ones). The tool cannot see the layout, so
this surfaces as a flat-map warning, not a refusal.

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

## Commands (surface detail / #775)

| cmd | params | result |
|---|---|---|
| `apply_surface_detail` | `{ mesh, maps_dir, effects, out_dir?, resolution?, seed? }` | `{ mesh, effects: [{kind, strength, scale, changed_fraction}], color_file, color_basename, height_file, height_basename, file_nodes, checkpoint_id, warnings }` |

`apply_surface_detail` composites directed wear, grime, and grain onto one
mesh's textures, consuming the masks `bake_mesh_maps` bakes from geometry
(`<short>_curvature.png` / `<short>_ao.png` in `maps_dir`, where `<short>`
is the mesh's short name). Direction always comes from a baked mask,
never guesswork: `wear` rides the CURVATURE mask (raised edges wear
first), `grime` rides the AO mask INVERTED (occluded pockets/seams
collect grime), and `grain` blends BOTH masks (curvature un-inverted plus
inverted AO) into a height field wired as a `file -> bump2d(bumpInterp=0)
-> normalCamera` network — grain is a bump network, not a colour
composite like wear/grime.

`effects` is a non-empty list, at most one entry per `kind` (`wear`,
`grime`, `grain`), each `{kind, strength?, scale?, color?}`:

| field | default | range |
|---|---|---|
| `strength` | 2.0 (`grime`: 1.5) | `(0, 4]` |
| `scale` | 1.0 | `(0, 16]` |
| `color` (wear/grime only) | built-in wear/grime colour | 3-list of LINEAR floats in `[0, 1]` |

Colour is always LINEAR — the same convention `assign_material` uses,
never re-derived as sRGB.

The default strengths are the smallest values a live look probe (#775)
measured as legible in a render — a caller who cannot see the result must
get detail that reads. Pass a smaller `strength` for subtlety.

Refusals, all before any file is written or scene node created:
- an unknown top-level or effect-dict key (`maps_dir`/`effects` and
  `kind`/`strength`/`scale`/`color` have a synonym map, same #764
  discipline as `bake_mesh_maps`)
- missing/empty `mesh`, or a `mesh` that does not resolve in the scene
- missing/empty `effects`, a non-object entry, or an unknown `kind`
- the same `kind` repeated across two entries
- `strength` outside `(0, 4]`, `scale` outside `(0, 16]`
- `color` not a 3-list of numbers in `[0, 1]`
- `maps_dir` (required) or `out_dir` (optional) not an absolute, existing
  directory
- `resolution`, when given, not one of the standard bake sizes
- `seed` not an integer
- a needed mask file (`<short>_curvature.png` / `<short>_ao.png`)
  missing, unreadable, **or FLAT** — unlike `bake_mesh_maps`, a flat mask
  REFUSES here instead of warning, because a flat mask has no directional
  signal to drive an effect from
- `grain` requested with curvature/AO masks of disagreeing size and no
  explicit `resolution`
- `grain` requested when the shader already carries a bump/normal network
  on `normalCamera` — this tool will not stack onto an existing one
- `grain` requested with a `color` key — grain writes a HEIGHT map, there
  is no colour to tint; `color` belongs on `wear`/`grime`
- colour effects (`wear`/`grime`) also inherit #770's base-colour refusals
  via `meshmaps.plan_apply`, unchanged here: a procedural colour base
  (hints `maya_bake_textures`), more than one shading group on the mesh, a
  material also worn by a mesh outside the request, a colour slot driven
  by more than one file terminal, or a base file that cannot be read as a
  PNG

The only mutation happens under one `checkpoint_id`; a mid-apply failure
deletes every node this call created and names the checkpoint to restore.
The ORIGINAL input colour map is never overwritten: `wear`/`grime`
composite into a new `<material>_color_detail.png` and rewire the colour
slot to it (any existing colour map is left in place on disk); `grain`
writes a new `<short>_height.png`. Re-applying to the same material,
however, replaces THIS tool's own previous `<material>_color_detail.png`
composite in place rather than starting again from the original base — a
warning is returned (`"<name> is already <material>'s colour base..."`),
and detail compounds if the same effect kind is re-applied on top of its
own prior result. Each `effects[]` result entry reports the
`changed_fraction` of texels the effect actually touched — near-zero
still ships, but with a warning, since a caller asking for detail that
produced almost nothing should know rather than ship a file that quietly
does nothing.
