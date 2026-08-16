# `maya_export_fbx` — design

Redmine: **#642** (this work), **#629** (the unit defect the gate exists to catch), **#634/#635**
(`export_metres_per_unit` as the assertable number), **#640** (the naming papercuts this must not
add to).

## The problem, in one sentence

The server has forty tools and not one of them writes a file a consumer can open, so the single
decision most likely to ship a broken asset — what one unit means in the written file — is the
one decision the server has no opinion about.

Every delivery so far (demigol kit, heroes, golem) exported through `maya_execute_python` carrying
a hand-maintained MEL preamble, `evals/maya_export.py`. That file exists because the behaviour is
not guessable from the API docs, and the two generators once held **divergent** copies of it whose
divergence was load-bearing.

## Measured facts this design rests on

All established during #629 and re-stated in `evals/maya_export.py`, which is the current single
source.

| fact | consequence |
|---|---|
| Maya's internal linear unit is centimetres whatever `currentUnit` reports, and the exporter writes those internal numbers | a metre-*authored* scene exports at 100x |
| `FBXExportConvertUnitString m` runs without error and does **nothing** — six selector/dynamic-conversion combinations were byte-identical | it is not in the preamble, and must not be added back as decoration |
| `FBXExportScaleFactor` takes a **bare float**; the `-v` form raises (and both generators swallowed that in `except Exception: pass`) | pinned as `'FBXExportScaleFactor %g'` |
| the factor only **multiplies the root node scale the exporter writes** — confirmed by the reciprocal, factor 0.01 wrote 0.0001 | it can never change vertex magnitude, so it cannot rescue a wrong scene |
| Maya writes `UnitScaleFactor 1.0` for a metre-native scene and offers no way to change it — measured across nine combinations | the declaration has to be patched in the bytes afterwards |
| a compensating root scale renders correctly | three revisions shipped at 100x with every in-Maya check green (#596, #600, #629) |

The last two rows are the whole argument for this tool's shape: **the defect is written by the
exporter and is absent from the scene, so no in-Maya check can see it.** The tool must read back
the bytes it just wrote.

## The unit contract

**`metres_per_unit` is required and has no default. Only `1.0` proceeds.**

Not a default, because a default is a guess, and the guess is exactly what shipped three times.
Not a conversion, because the factor cannot convert: the only way to make an oversized scene
export at the right magnitude is the compensating root scale, which is the defect. So any value
other than `1.0` is refused with a hint to bake the scale into the vertices first.

This matches the authoring convention the repo already uses: author under `currentUnit("cm")` so
one unit *means* one metre (`METRE_TRUE_UNIT = "cm"` in `maya_plugin/handlers/units.py`), and the
export scale factor is `1.0`.

Note the deliberate asymmetry with the file: `metres_per_unit` is the parameter, `UnitScaleFactor`
in the FBX is **centimetres**-per-unit, so `metres_per_unit == 1.0` is written as `100.0`
(`fbx_probe.DECLARES_METRES`). The parameter speaks the language of #634/#635
(`export_metres_per_unit`), the file speaks FBX's.

## Shape

### 1. Promote the byte reader

`evals/fbx_probe.py` moves **verbatim** to `maya_plugin/handlers/fbxbytes.py`. It has to live
plugin-side: the FBX is written on the Maya machine's disk and the server cannot assume it shares
that filesystem. It is pure stdlib (`struct`, `zlib`, `math`), so it loads inside Maya's
interpreter with no dependency, and `maya_plugin/install.py` copies the whole package, so it
deploys with no install change.

`evals/fbx_probe.py` becomes a re-export shim so the six existing consumers are untouched:
`evals/delivery_units.py`, `evals/golem_delivery_package.py`, `evals/demigol_kit.py`,
`evals/demigol_structures.py`, `evals/units_live.py`, `tests/test_delivery_units.py`.

The shim must re-export **names**, not values — `tests/test_delivery_units.py` monkeypatches
`fbx_probe.read_fbx` in seven places and `evals/delivery_units.py` resolves it as an attribute at
call time, so the patch and the lookup have to land on the same module object. `from ... import *`
satisfies that; a `read_fbx = _real.read_fbx` alias in a wrapper that then called `_real.read_fbx`
internally would not.

### 2. New handler `maya_plugin/handlers/export.py`

| param | required | meaning |
|---|---|---|
| `path` | yes | absolute, must end `.fbx`; parent directory must exist |
| `metres_per_unit` | **yes, no default** | only `1.0` proceeds |
| `nodes` | no | list of transforms to export; omitted means the whole scene |

Sequence:

1. **Validate** every param before touching Maya. A bad param must cost nothing.
2. `FBXResetExport`, then the pinned preamble moved out of `evals/maya_export.py`:
   file version `FBX202000`, up axis `y`, input connections off, embedded textures off,
   scale factor `1.0`.
3. Export — `-s` (selection) when `nodes` was given, all otherwise.
4. **Patch** `UnitScaleFactor` to `100.0` in place. One IEEE-754 double overwritten with another
   of the same width, so no offset, length or nested record in the file moves.
5. **Re-read the bytes** and run the gate.
6. On any violation: `os.unlink` the file and raise `HandlerError` naming the offending nodes.

**Refuse, don't warn.** There is no `strict=false`. A file that fails the gate is the exact
artifact that shipped three times looking fine; leaving it on disk with a warning in the response
recreates the failure, because the warning is in a transcript and the file is in a delivery.

### 3. The gate

Two assertions, and only two, because they are the two that hold for **every** export this server
can be asked to make:

* **every node scale is identity** (tolerance 1e-3) — a compensating node scale is the mechanism by
  which a wrong vertex magnitude renders correctly
* **the declaration is `100.0`** — metre-magnitude vertices declared as centimetres is the same
  defect inverted, and Demigol measures unit scale on import

Deliberately **not** included, though `evals/delivery_units.py` checks them:

* **one root node.** That is a *rig* rule (`check_rig_delivery`). The demigol kit legitimately
  exports 41 roots and would fail it.
* **the lattice / pitch checks and the ceiling.** Those are contract envelopes belonging to a
  particular delivery, not properties of a correct export. They stay in `evals/`.

The tool asserts what it is responsible for. The delivery gates keep asserting what *they* are
responsible for, against the same bytes.

### 4. The return

Everything composed **from the file**, never from the scene — that is the point of the tool:

`path`, `bytes`, `fbx_version`, `node_count`, `mesh_count`, `root_nodes`, `unit_scale_factor`,
`metres_per_unit`, `world_bounds_min`, `world_bounds_max`, `height_m`.

`height_m` is `world_bounds_max.y - world_bounds_min.y` composed through the parent chain, which
is the number a consumer sees on import and the one that discriminates a 4 m creature from a 4 cm
one when every individual chunk is sub-metre.

### 5. The tool

`maya_export_fbx`, in `src/maya_mcp/server.py` with an `ExportFbxResult` in
`src/maya_mcp/schemas.py`, following the `maya_save_scene` pattern
(`read_only_hint=False, destructive_hint=False, idempotent_hint=True`).

**Named `maya_export_fbx`, not the bare `maya_export` in the ticket title.** #640 is open about
naming papercuts, and `maya_export` promises OBJ and USD the tool does not have. The ticket's own
"(fbx/obj at least)" is the scope the user cut to FBX only; the name should say so.

### 6. One definition, without an art run

The ticket's justification is that the preamble must have exactly one source. Deleting
`EXPORT_PREAMBLE` outright does not achieve that — it breaks it. Three scripts consume it today:

| consumer | use |
|---|---|
| `evals/demigol_kit.py:813` | `EXPORT_CODE = maya_export.EXPORT_PREAMBLE + ...`, 41-root kit delivery |
| `evals/demigol_structures.py:1061` | same, hero structures |
| `evals/units_live.py:103` | the live unit probe |

All three are delivery generators whose export path can only be re-validated by a live Maya run —
i.e. an art run. Migrating them to `maya_export_fbx` is worth doing and is **not** in this ticket.

So instead: the handler holds the MEL statements as a module-level tuple, and
`evals/maya_export.py` **composes `EXPORT_PREAMBLE` from that tuple** rather than restating it.
One definition, three callers unchanged, no art run required, and a later migration deletes the
composition rather than reconciling a second copy. `EXPORT_SCALE_FACTOR` is likewise re-exported
from the handler's constant.

`AUTHORING_UNIT`, `UV_PER_METRE` and `UNITS_GATE` stay where they are: they are generator-side
facts about how a scene is *authored*, not about how it is written.

The import direction is `evals/` → `maya_plugin/`, which is new but sound: `handlers/export.py`'s
module level is pure stdlib (`maya.cmds` is imported inside functions, per the `_cmds()` pattern
every handler uses), so it imports cleanly outside Maya. This is the same reason the byte reader
can move in the other direction.

## Testing

**Headless** (`tests/`): param validation; the gate run over synthetic `FbxFacts` for each
violation class; and the gate run over the committed `evals/golem_delivery/golem.fbx`, which is a
real 33-chunk artifact that must pass.

**Live** (`evals/export_live.py`): export from a real Maya and report measured bytes, node count
and height. Per the standing rule — a headless green means nothing here, because the code path
that matters is the one that runs inside Maya, and the deployed copy under
`<Documents>/maya/scripts` is not the repo. Sync with `install.py` before trusting any live run.

## What this does not do

* No OBJ, no USD. FBX only, per the scope decision.
* No unit conversion. `metres_per_unit != 1.0` is refused, not fixed.
* No animation, no cameras, no lights export flags — the preamble stays exactly what three
  deliveries have measured, and grows only when a delivery needs it.
