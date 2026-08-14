# Design Doc: `maya-mcp` — An MCP Server for AI-Driven 3D Modeling in Autodesk Maya

**Status:** Ready for implementation
**Implementer:** Claude Code
**Target stack:** Python 3.10+ · MCP Python SDK (FastMCP) · Maya 2023+ (Python 3 interpreter)
**Benchmark deliverable:** A stylized earth golem (Jewish folklore: clay body, cracked-stone surface, glowing *emet* rune) modeled end-to-end by Claude through this server.

---

## 0. Read these before writing code

1. MCP spec sitemap: `https://modelcontextprotocol.io/sitemap.xml` — fetch relevant pages with `.md` suffix (architecture, stdio transport, tools).
2. Python SDK README: `https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/main/README.md` — use FastMCP with `@mcp.tool` registration and Pydantic v2 models.
3. Maya Python API docs for: `maya.cmds`, `maya.utils.executeInMainThreadWithResult`, `maya.mel.eval`, playblast/`M3dView` viewport capture, `polyRetopo`/`polyRemesh`, soft selection (`softSelect`).

Why Python and not TypeScript (the usual MCP recommendation): the Maya-side plugin **must** be Python (Maya embeds a Python interpreter), and sharing one language across both halves means shared schemas, shared test fixtures, and the ability to unit-test handlers under `mayapy` without a running GUI. Transport is **stdio** (local server); do not build HTTP transport in v1.

---

## 1. Purpose and success definition

Build an MCP server that lets an LLM (Claude Desktop / Claude Code) model, texture, light, and render 3D content in a live Maya session through an **iterative visual feedback loop**.

The design thesis, in priority order:

1. **Perception beats actuation.** The model cannot produce good 3D work blind. Viewport capture returning images to the LLM is the single most important tool; every other tool exists to give the LLM something worth looking at.
2. **One escape hatch + a thin structured layer.** `maya_execute_python` does ~90% of real work. Structured tools exist for reliability, compact returns, safety rails, and destructive-op checkpointing — not for capability.
3. **Compact returns everywhere.** Maya scenes are enormous. Any tool that can return unbounded data must summarize, paginate, or cap. A scene-graph dump of raw vertex data is a session-killing bug, not a feature.

**Success =** a fresh Claude session, given only this server and the prompt in Appendix A, produces a golem that passes the rubric in §8.3 within 120 tool calls.

## 2. Goals and non-goals

**Goals (v1):**
- Full modeling loop: block-out → organic shaping → cleanup → materials → lighting → turntable render.
- Visual feedback: multi-angle viewport capture with wireframe overlay, contact-sheet turntables, reference-image side-by-sides.
- Robust arbitrary code execution with full tracebacks and a persistent namespace.
- Session safety: checkpoints, undo/redo, auto-checkpoint before destructive ops.
- Optional AI mesh generation (Meshy / Hyper3D Rodin / Hunyuan3D adapter) as the organic-base-mesh escape route.

**Non-goals (v1):**
- Rigging, skinning, animation (stretch goal, out of scope).
- ZBrush-grade sculpting fidelity — the loop is low-bandwidth by nature; target is "clean stylized game asset."
- Arnold/offline rendering (viewport 2.0 hardware render only in v1; leave a `renderer` param stubbed).
- Remote/multi-user operation. Localhost only.
- Windows/macOS/Linux installers beyond a simple `install.py` that copies files and prints instructions.

## 3. Architecture

### 3.1 Components

```
┌────────────────┐  MCP (stdio)  ┌──────────────────┐  TCP 127.0.0.1:9877  ┌───────────────────────┐
│ Claude client  │◄─────────────►│ maya-mcp server   │◄────────────────────►│ Maya plugin            │
│ (Desktop/Code) │               │ (FastMCP, Python) │   length-prefixed    │ (socket thread +       │
└────────────────┘               │ - tool schemas    │   JSON frames        │  main-thread dispatch) │
                                 │ - image handling  │                      │ - handlers/* modules   │
                                 │ - AI provider API │                      │ - runs maya.cmds       │
                                 └──────────────────┘                      └───────────────────────┘
```

Two processes, three layers:
- **MCP server** (`src/maya_mcp/`): owns tool definitions, Pydantic validation, image downscaling, token budgets, AI-provider HTTP calls (API keys never enter the Maya process), and the socket client with reconnect logic.
- **Maya plugin** (`maya_plugin/`): a background thread running a TCP socket server inside Maya. It **never** touches the Maya API from the socket thread — every command is marshaled to the main thread via `maya.utils.executeInMainThreadWithResult` and executed there with a watchdog timeout.
- **Wire protocol**: version-tagged, length-prefixed JSON. Images travel as base64 PNG inside result payloads, size-capped before transmission.

### 3.2 Wire protocol

Frame = `uint32 big-endian length` + UTF-8 JSON body.

```jsonc
// request
{ "v": 1, "id": "uuid", "cmd": "capture_viewport", "params": { ... }, "timeout_s": 30 }

// success
{ "v": 1, "id": "uuid", "status": "ok", "result": { ... }, "elapsed_ms": 412 }

// failure — tracebacks are sacred, never truncate them silently
{ "v": 1, "id": "uuid", "status": "error",
  "error": { "type": "RuntimeError", "message": "...", "maya_traceback": "full traceback text",
             "hint": "actionable suggestion when known, e.g. 'object pCube7 not found; call maya_get_scene_graph to list objects'" } }
```

Rules: one in-flight request at a time (the LLM is serial anyway); requests after a timeout get a fresh connection; plugin binds `127.0.0.1` only unless `MAYA_MCP_TOKEN` is set, in which case every frame must carry `"token"`.

### 3.3 Threading and timeouts

- Socket thread receives frames, pushes onto a queue, waits on a `concurrent.futures.Future`.
- Main-thread pump executes handlers via `executeInMainThreadWithResult`; per-command timeout default 30 s (`maya_execute_python` accepts up to 300 s).
- On timeout the server returns a structured timeout error **and** the plugin flags the session as `busy` until the straggler finishes, so a late result can't be mismatched to a new request id.
- All handlers wrap execution in `undoInfo(openChunk)` / `closeChunk` so each tool call is one undo step.

### 3.4 Configuration

Environment variables, all optional: `MAYA_MCP_HOST` (default `127.0.0.1`), `MAYA_MCP_PORT` (default `9877`), `MAYA_MCP_TOKEN`, `MAYA_MCP_LOG_LEVEL`, `MAYA_MCP_MAX_IMAGE_PX` (default `768`), `MESHY_API_KEY` / `RODIN_API_KEY` / `HUNYUAN_API_KEY`.

## 4. Repository layout

```
maya-mcp/
├── pyproject.toml              # deps: mcp, pydantic>=2, pillow, httpx
├── README.md                   # install, config, quickstart, security warning
├── src/maya_mcp/
│   ├── server.py               # FastMCP app; every @mcp.tool defined here, thin
│   ├── connection.py           # socket client, framing, reconnect, token
│   ├── images.py               # b64 decode, downscale, contact-sheet compositor
│   ├── ai_providers/           # meshy.py, rodin.py, hunyuan.py behind one ABC
│   └── schemas.py              # Pydantic models shared conceptually with plugin
├── maya_plugin/
│   ├── maya_mcp_plugin.py      # socket server, dispatcher, main-thread pump
│   ├── handlers/
│   │   ├── scene.py            # scene graph, object info, session ops
│   │   ├── modeling.py         # primitives, booleans, transforms, cleanup
│   │   ├── arraymath.py        # pure array placement math: radial angles, linear
│   │   │                       # steps, point rotation, bbox reflection, signed volume
│   │   ├── array.py            # array command: duplicate, place, mirror-and-fix-
│   │   │                       # winding, group, ledger
│   │   ├── sculpt.py           # sculpt_ops, deformers, soft selection
│   │   ├── materials.py        # shaders, texture networks
│   │   ├── lighting.py         # presets, HDRI
│   │   ├── capture.py          # viewport/turntable/buffer capture
│   │   └── code_exec.py        # execute_python with persistent namespace
│   └── install.py              # copies plugin, appends userSetup.py autoload
├── tests/
│   ├── test_protocol.py        # framing, timeouts, token — no Maya required
│   ├── test_handlers_mayapy.py # runs under `mayapy -m pytest`, standalone mode
│   └── fixtures/
├── evals/
│   ├── golem_benchmark.md      # Appendix A, as a runnable eval doc
│   └── qa_evals.xml            # 10 read-only eval questions (§8.4)
└── docs/
    └── protocol.md             # wire format reference
```

## 5. Tool catalog

Conventions that apply to every tool:
- Names are prefixed `maya_` (discoverability across a multi-server client).
- Inputs validated with Pydantic v2; every field has a description and, where useful, an example. Reject unknown fields.
- Every tool declares MCP annotations: `readOnlyHint`, `destructiveHint`, `idempotentHint`.
- Every response that names scene nodes returns **canonical long names** (`|group1|golem_torso`) so follow-up calls are unambiguous.
- Every error must state what went wrong *and* what to try next (the `hint` field).
- Token budget: default text response ≤ 4 KB; anything bigger paginates (`cursor` param) or summarizes with an explicit `"truncated": true` marker.

### 5.1 Perception (readOnly, the eyes — build these first)

```python
maya_get_scene_graph(filter: str | None = None, max_objects: int = 200, cursor: str | None = None)
  -> { objects: [{ name, type, tris, verts, bbox_min, bbox_max, material, parent, visible }],
       total: int, cursor: str | None }
  # Compact outline of transforms/shapes. NEVER returns component data.
  # `filter` is a case-insensitive substring on name or type ("mesh", "light").

maya_get_object_info(name: str,
                     include: list[Literal["transform","mesh_stats","uvs","shading","history"]] = ["transform","mesh_stats"])
  -> per-section dicts; uv/history sections are summaries (counts, node types), never raw data.

maya_capture_viewport(angles: list[Literal["front","side","back","top","three_quarter","current"]] = ["front","side","three_quarter"],
                      shading: Literal["smoothShaded","flatShaded","wireframe","textured"] = "smoothShaded",
                      wireframe_overlay: bool = True,
                      buffer: Literal["beauty","ssao"] = "beauty",
                      isolate: list[str] | None = None,
                      frame_all: bool = True,
                      resolution: int = 768)
  -> images (one per angle, max 4 per call) + { camera_positions: [...] }
  # THE critical tool. Implementation: temporary offscreen cameras per angle, viewFit,
  # playblast single frame (fallback: M3dView.readColorBuffer), Pillow downscale to
  # MAYA_MCP_MAX_IMAGE_PX, encode PNG. wireframe_overlay lets the LLM judge topology,
  # not just silhouette. `ssao` toggles viewport 2.0 SSAO — surfacing flaws hide in
  # beauty renders and show in AO. Must restore all viewport state afterwards.

maya_capture_turntable(target: str | None = None, n_frames: int = 8, resolution: int = 384)
  -> ONE contact-sheet image (grid composited server-side by images.py)
  # 8 views for the token cost of one image. Used for final judgment passes.

maya_render_scene(angles: list[str] = ["three_quarter"], renderer: "arnold" | "hw2" = "arnold",
                  resolution: int = 512, isolate: list[str] | None = None,
                  samples: int = 3, fallback_light: bool = True)
  -> images + per-frame {opaque_px, total_px, distinct_colors}
  # The second eye (M2.2, redmine #584). capture_viewport reads the VIEWPORT, so it needs
  # a mapped window and inherits VP2's approximations - transmission draws as plain
  # transparency, making gems, glass, ice and water un-judgeable. cmds.render needs
  # neither: it renders from a Maya with no visible window (where every playblast comes
  # back transparent) and under arnold it refracts for real. Isolate HIDES the
  # non-targets here, because panel isolation is invisible to a renderer. Render globals
  # are scene state and are snapshotted/restored around every call.

maya_load_reference_image(source: str, ref_id: str)      # path or base64; stored server-side
maya_compare_to_reference(ref_id: str, angle: str = "three_quarter", resolution: int = 640)
  -> one side-by-side composite image (reference | current viewport)
  # Cheap to build, large quality win: the LLM corrects toward a target instead of a vague ideal.
```

### 5.2 The escape hatch

```python
maya_execute_python(code: str, timeout_s: int = 30, risky: bool = False)
  -> { stdout, stderr, result_repr, traceback: str | None, namespace_keys: [str] }
  # destructiveHint=true. Runs in a PERSISTENT namespace dict (survives across calls;
  # `maya_reset_namespace()` clears it). `maya.cmds`, `maya.mel`, `pymel` (if present)
  # pre-imported. stdout capped at 8 KB with an explicit truncation notice; the
  # traceback is returned complete and verbatim — the LLM debugs itself with it,
  # and silent failure causes hallucinated success. If risky=True, the plugin takes
  # an auto-checkpoint first.
```

### 5.3 Structured modeling (reliability layer over `cmds`)

```python
maya_create_primitive(kind: Literal["cube","sphere","cylinder","plane","torus","cone"],
                      name: str, translate=(0,0,0), rotate=(0,0,0), scale=(1,1,1),
                      divisions: int = 1) -> { name }

maya_duplicate(name, new_name, translate=None, rotate=None, scale=None) -> { name }
maya_array(name: str, mode: Literal["mirror","radial","linear"], count: int = 2,
          axis=None, center=None, angle: float = 360.0, offset=None,
          step_rotate=None, step_scale=None, pivot=None, name_prefix=None,
          group_name=None) -> { names: [str], mode, group, signed_volume, warnings }
  # mirror reflects one copy across a world plane (needs a single polygon mesh);
  # radial rings copies about an axis; linear runs copies along a vector, with
  # step_scale compounding into a geometric taper down the run.
maya_transform(names: list[str], translate=None, rotate=None, scale=None, relative: bool = True)
maya_group(names: list[str], group_name: str) / maya_parent(child, parent) / maya_rename / maya_delete_objects

maya_boolean_op(a: str, b: str, op: Literal["union","difference","intersection"], new_name: str)
  -> { name, tris, watertight: bool, warnings: [str] }
  # destructive. AUTO-CHECKPOINT before executing. Delete construction history after.
  # Validate result is manifold; if not, return ok with a warning + hint to run cleanup.

maya_sculpt_ops(mesh: str, ops: list[SculptOp]) -> { applied: int, tris, warnings }
  # SculptOp is a tagged union — the golem-maker:
  #   {op:"soft_move", center: [x,y,z] | vertex_id, radius: float,
  #    falloff: "smooth"|"linear", delta: [x,y,z]}          # THE organic tool: soft
  #                                                          # selection + move approximates
  #                                                          # broad sculpt strokes
  #   {op:"extrude_faces", faces: "f[120:135]", distance, keep_together: true}
  #   {op:"smooth", divisions: 1}
  #   {op:"inflate_region", center, radius, amount}
  #   {op:"bevel_edges", edges, width, segments}
  #   {op:"crease_edges", edges, amount}                     # stone-plate joints
  #   {op:"bridge", edges_a, edges_b}
  # Applied in order; abort-and-report on first failure, listing which ops landed.

maya_deform(mesh: str, deformer: Literal["bend","flare","lattice","sculpt",
                                          "sine","squash","twist","wave"],
            params: dict, delete_history_after: bool = False)
  # bend for the golem hunch; lattice for global proportion pushes; flare for
  # a limb thick at one end and thin at the other; sine/wave for ripples.

maya_remesh_retopo(mesh: str, target_polycount: int, keep_original: bool = True)
  # destructive → auto-checkpoint. polyRetopo where available, polyRemesh fallback,
  # polyReduce as last resort; report which path ran.

maya_mesh_cleanup(mesh: str, merge_verts_threshold: float = 0.001,
                  delete_history: bool = True, freeze_transforms: bool = True,
                  conform_normals: bool = True) -> { before: stats, after: stats }
```

### 5.4 Surface and look

```python
maya_assign_material(mesh: str, shader: Literal["standardSurface","lambert","blinn"] = "standardSurface",
                     params: dict)   # whitelist: baseColor, roughness, metalness, emission,
                                     # emissionColor, specular; reject others with a hint.

maya_create_texture_network(mesh: str, recipe: list[NodeSpec])
  # NodeSpec: { node: "noise"|"ramp"|"layeredTexture"|"bump2d"|"displacement"|"file"|"remapValue",
  #             name: str, params: dict, connect: [{src_attr, dst_node, dst_attr}] }
  # Validate the DAG (no cycles, attrs exist) BEFORE creating anything; return the created
  # node names. This is how the golem gets cracked-clay noise → bump + displacement.

maya_setup_lighting(preset: Literal["three_point","single_sun","hdri"],
                    intensity: float = 1.0, hdri_path: str | None = None,
                    replace_existing: bool = True)
  # A model can't be judged unlit; M2 blocks on this.
```

### 5.5 AI mesh generation (the ceiling-raiser)

```python
maya_generate_mesh_ai(prompt: str | None, image_ref: str | None,
                      provider: Literal["meshy","rodin","hunyuan"] = "meshy",
                      target_polys: int = 30000) -> { job_id }
maya_check_ai_job(job_id) -> { status: "pending"|"done"|"failed", eta_s?, error? }
maya_import_ai_result(job_id, name: str) -> { name, tris, materials_imported }
maya_import_mesh(path: str, name: str)    # local OBJ/FBX/GLB
  # Async submit → poll → import. HTTP happens in the MCP server process (httpx),
  # never inside Maya. Providers behind one ABC in ai_providers/; a missing API key
  # returns an actionable error naming the env var. This is the single biggest
  # quality upgrade: generate the organic base, use Maya tools for kitbash/retopo/
  # materials/lighting.
```

### 5.6 Session safety

```python
maya_checkpoint(label: str) -> { checkpoint_id, path }
  # Incremental save to <project>/checkpoints/NNN_label.ma. Auto-invoked by
  # boolean_op, remesh_retopo, execute_python(risky=True). Keep last 20, prune older.
maya_restore_checkpoint(checkpoint_id)
maya_undo(steps: int = 1) / maya_redo(steps: int = 1)
  # Works because every tool call is one undo chunk (§3.3). Undo is cheaper than re-modeling.
maya_new_scene(confirm: bool) / maya_open_scene(path) / maya_save_scene(path: str | None)
  # new_scene REQUIRES confirm=true; refuse otherwise with a hint.
maya_reset_namespace()
```

## 6. Cross-cutting requirements

**Token discipline.** Images: max 4 per tool call, longest edge ≤ `MAYA_MCP_MAX_IMAGE_PX` (default 768; turntable frames 384). Text: ≤ 4 KB per response unless the tool documents pagination. Any truncation is marked explicitly so the LLM knows to ask for more rather than assume completeness.

**Error contract.** Never swallow an exception. Every error carries `type`, `message`, the complete Maya traceback, and a `hint` when the cause is recognizable (unknown node → suggest `maya_get_scene_graph`; component syntax error → show correct `f[a:b]` form; timeout → suggest splitting the operation). Actionable errors are a feature with equal rank to any tool.

**Naming and idempotency.** Requested names that collide get deterministic suffixes (`golem_arm` → `golem_arm_001`) and the canonical assigned name is always returned. Tools address objects only by name, never by selection state — the LLM must never depend on what is selected.

**Viewport hygiene.** Capture tools snapshot and restore every setting they touch (active camera, shading mode, SSAO, isolate state). A perception call must be side-effect-free.

**Logging.** Both processes log to rotating files (`~/.maya-mcp/logs/`); `MAYA_MCP_LOG_LEVEL=DEBUG` logs full frames minus image payloads.

**Security.** `maya_execute_python` is arbitrary code execution on the user's machine — the README must say so plainly. Plugin binds loopback only by default; non-loopback binding requires both an explicit env opt-in and a token. AI-provider keys live only in the MCP server process. `install.py` never modifies files outside Maya's prefs directory without printing exactly what it will do and asking.

**Compatibility.** Maya 2023–2026, Windows + macOS (Linux best-effort). Feature-detect `polyRetopo`; degrade with a reported fallback rather than failing.

## 7. Milestones

| M | Scope | Exit test |
|---|-------|-----------|
| **M0 — the loop** | Protocol, plugin skeleton, `execute_python`, `get_scene_graph`, `capture_viewport` | Claude builds a snowman with carrot nose using only these three tools, correcting proportions from screenshots |
| **M1 — hands** | All §5.3 modeling tools + §5.6 session safety, undo-chunk discipline | Scripted test: boolean a rune cavity into a cube, undo it, restore a checkpoint; zero orphan history nodes |
| **M2 — eyes & skin** | Materials, texture networks, lighting, turntable, reference compare, SSAO buffer | Claude matches a provided reference silhouette within 3 correction rounds; turntable contact sheet renders |
| **M2.1 — gem gaps** | transmission/ior params, faceted primitives, material reuse (from a real art run) | The gem-brute run's tool gaps closed |
| **M2.2 — headless render** | `render_scene`: cmds.render path, arnold by default, blank-frame detection | From an AGENT-launched Maya: a lit scene renders non-blank, and a transmissive gem measurably differs from an identical opaque one (`evals/render_scene_live.py`) |
| **M3 — ceiling raise** | AI provider adapters, async job flow, import + auto-cleanup pipeline | Text prompt → Meshy mesh lands in scene, retopo'd to 30k tris, materialed |
| **M4 — proof** | Golem benchmark run, evals, README, install.py polish | §8.3 rubric passes; MCP Inspector shows all schemas valid |

Build strictly in order: **M0 is the whole thesis** — if the perceive/act loop isn't solid, nothing downstream matters.

## 8. Testing and evaluation

### 8.1 Unit and integration
- `tests/test_protocol.py`: framing, length prefixes, timeout behavior, token auth, reconnect — pure Python, no Maya, runs in CI.
- `tests/test_handlers_mayapy.py`: handlers imported under `mayapy -m pytest` with `maya.standalone.initialize()`; capture tests skipped headless (playblast needs a GUI) but their argument-marshaling is still asserted.
- MCP Inspector (`npx @modelcontextprotocol/inspector`) against the running server: every tool schema loads, annotations present, a no-Maya state returns clean "plugin not connected" errors with launch instructions.

### 8.2 QA evals (per MCP conventions)
Author `evals/qa_evals.xml` with 10 questions that are independent, **read-only**, multi-step, realistic, and string-verifiable, run against a checked-in fixture scene (`fixtures/eval_scene.ma`). Example shape: *"Which mesh in the scene has the highest triangle count among objects whose material has roughness below 0.3?"* → `golem_torso`.

### 8.3 The Golem Benchmark (acceptance)
Fresh scene; the only instruction is Appendix A. **Hard pass criteria:** ≤ 120 tool calls; one connected watertight body ≤ 50 k tris (no floating/intersecting shells); cracked-earth material with a noise→bump network; emissive rune on the forehead; three-point lighting; final 8-frame turntable contact sheet produced. **Rubric (human-scored 1–5, pass ≥ 3 each):** proportion/silhouette readability at thumbnail size · surface quality under SSAO · presentation (lighting/material coherence). Record tool-call count and wall time per run; keep the transcript as a regression artifact.

### 8.4 Known ceiling (set expectations in README)
This loop reliably reaches "clean stylized game asset," sometimes mid-poly hand-modeled quality, and does not reach ZBrush-grade organic sculpting — the perceive/act loop is orders of magnitude lower-bandwidth than an artist with a tablet. The golem flatters the pipeline (blocky, geometric, procedural-texture-friendly); do not benchmark against faces or animals in v1.

## 9. Open questions (implementer decides, document the choice)

1. `playblast` vs `M3dView.readColorBuffer` reliability for offscreen capture per OS — prototype both in M0, pick per-platform.
2. Whether client image-size limits require dropping default capture resolution below 768 px — test in Claude Desktop early.
3. `polyRetopo` availability across target Maya versions — confirm and encode in the feature-detect.
4. Persistent-namespace scoping for `execute_python`: per-conversation vs per-Maya-session (proposed: per-Maya-session with `maya_reset_namespace`).
5. Whether `sculpt_ops` soft_move should use `cmds.softSelect` + move or OpenMaya weighted vertex offsets (prototype: OpenMaya is likely faster and cleaner to restore).

---

## Appendix A — Golem benchmark prompt

> Model a golem from Jewish folklore in the open Maya scene: a heavy earthen humanoid — squat proportions, oversized forearms and shoulders, small head, hunched stance, feet rooted like broken earth. Give it a cracked dry-clay surface, carve or emboss the Hebrew word *emet* (אמת) on its forehead and make it glow faintly, light it with a three-point setup, and finish with an 8-frame turntable. Work iteratively: check your work visually after each significant change and correct proportions before adding detail.

## Appendix B — Example wire exchange

```jsonc
→ { "v":1, "id":"a1", "cmd":"sculpt_ops", "params":{ "mesh":"|golem|torso",
    "ops":[ {"op":"soft_move","center":[0,14.2,1.1],"radius":4.0,
             "falloff":"smooth","delta":[0,0.8,0.6]} ] }, "timeout_s":30 }
← { "v":1, "id":"a1", "status":"ok",
    "result":{ "applied":1, "tris":18240, "warnings":[] }, "elapsed_ms":95 }

→ { "v":1, "id":"a2", "cmd":"capture_viewport",
    "params":{ "angles":["front","three_quarter"], "wireframe_overlay":true } }
← { "v":1, "id":"a2", "status":"ok",
    "result":{ "images":[ {"angle":"front","png_b64":"..."},
                          {"angle":"three_quarter","png_b64":"..."} ],
               "camera_positions":[...] }, "elapsed_ms":1310 }
```
