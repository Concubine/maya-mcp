# #818 — live-gate coverage audit

Redmine #818. #814 found that `retarget_clip`'s .fbx route had tests, shipped,
and had never once run against Maya — and was broken five ways when it did.
This audit asks the same question of every command: which `evals/*_live.py`
gate has ever sent it over the wire, and which value-selected route inside it
no gate has ever sent. Produced by `evals/live_coverage_audit.py` (re-runnable;
raw output `evals/live_coverage_818.json`), ranked by hand.

64 commands, 100 eval scripts, 55 gates. 58 commands have at least one gate.

## Never called over the wire by any eval (6)

| command | what it does | cost of an unmeasured defect |
|---|---|---|
| `remesh_retopo` | rewrites a mesh's topology | HIGH — irreversible mesh mutation, headless-green only |
| `undo` / `redo` | session integrity after any tool call | HIGH — every recovery path leans on them; never measured that a tool call is one undo step |
| `rename` | renames a node | low — thin over `cmds.rename`, but the #640/#803 name-claim class lives next door |
| `reset_namespace` | clears execute_python's namespace | low |
| `set_viewport` | sets the panel's display state | low, but the capture tools depend on the panel state it writes |

## Reached only by refusal sweeps — the functional path never measured (2)

| command | gates that call it | what is unmeasured |
|---|---|---|
| `set_camera` | static_write_guard_live | that a positioned/aimed camera actually frames what it says |
| `group` | param_sweep_live | that a group keeps children's world positions and reports its pivot |

## Routes no gate has ever sent (inside covered commands)

| command | param | never sent | only in a probe or run |
|---|---|---|---|
| `bind_skin` | method | `geodesicVoxel`, `heatMap` | — (heatMap HUNG Maya in #797's probe; geodesicVoxel is fully unmeasured) |
| `boolean_op` | op | `intersection` | |
| `uv_atlas` | project | `planar` | |
| `deform` | deformer | `sine` | `twist` |
| `capture_viewport` | angle | `back` | |
| `create_primitive` | kind | — | `cone`, `pyramid` |
| `sculpt_ops` | op | — | `displace_noise` |
| `capture_viewport` | shading / buffer / lighting | — | all measured in #814/#815 probes, no gate |
| `retarget_clip` | file ext | — | (`.fbx` covered since #814) |
| `export_fbx` | flags | — | |
| array / curve_form / lighting presets / surface_detail / recipes / renderers / pivot modes | | — | |

## Ranked follow-ups (each a probe first, then a gate; none started here)

1. `remesh_retopo` live: never run. Mesh mutation with no measurement.
2. `undo` / `redo` live: one tool call = one undo step, and redo restores it — the
   session contract every recovery path assumes.
3. `bind_skin method=geodesicVoxel`: an offered bind method nobody has bound with.
   `heatMap` on an open mesh hangs Maya (#797) — probe it OUTSIDE the plugin
   executor, or refuse it on non-closed meshes on that evidence.
4. `boolean_op op=intersection`, `uv_atlas project=planar`, `deform sine`: one
   small gate each; `deform twist` and `sculpt displace_noise` have probe evidence only.
5. `set_camera` and `group` functional gates; `capture angle=back`.
6. `rename`, `reset_namespace`, `set_viewport`: cheap, low value; fold into any
   nearby gate.

## Caveats

The caller match is a grep for `("command"` in `evals/*.py`, so a gate that
calls a command through a helper with a different literal is missed; the
route match is a literal-string grep, so a value that also appears as a plain
word elsewhere reads as covered. Both err toward "covered" — the lists above
are lower bounds on what is unmeasured.
