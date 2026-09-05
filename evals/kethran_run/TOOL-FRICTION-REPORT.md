# maya-mcp — tool friction report from one organic-modelling run

**Reporter:** Claude session, 2026-09-05. **Audience:** the maya-mcp developer.
**Task:** build an anatomically plausible 2 m quadruped from scratch, through the MCP tools
only, correcting from viewport captures. Produced `kethran.ma` in this folder.

**Standing:** I am reporting only what the tools told *me*, as a consumer of them. I did not
read maya-mcp source to write this. Where I am inferring a cause I say so; where I only have
an observation I give the observation.

## Environment

- Maya 2027, launched minimized, `MAYA_MCP_PORT=9879`, cwd `D:\devel\maya-mcp`.
- Repo `main` was at **e0d56b1** at session start. **I did not verify which plugin copy
  actually loaded** — if a repro depends on that, establish it first.
- Scene unit **cm**. The subject is ~340 units long, ~200 tall. Several findings below are
  scale-dependent and that scale is the reason.
- Body mesh at the time of the worst findings: **57,724 tris**, one watertight shell,
  produced by loft + 7 boolean unions + one `polySmooth` division.

---

## Severity summary

| ID | Severity | Tool | One line |
|---|---|---|---|
| F-1 | **Blocker** | `bake_mesh_maps` | Hung 40 min, wrote zero files, blocked the whole session; its own timeout hint names a parameter it does not accept |
| F-2 | **High** | `sculpt_ops` | Every call reuses auto-checkpoint id `1000_auto_sculpt`, so consecutive sculpts destroy the only recovery point |
| F-3 | **High** | `render_scene` vs `capture_viewport` | The two disagree on material values by roughly a factor of 2 in light response |
| F-4 | **High** | viewport captures | Materials-unbound (flat chroma-green) frames, 4 occurrences, all on `lighting:'scene'` |
| F-5 | **Medium** | `create_curve_form` (sweep) | `worst_station_deviation` warning's remedy ("raise resolution") did not work; the deviation is large in absolute terms and easy to under-read |
| F-6 | **Medium** | `sculpt_ops displace_noise` | No documented units; no usable amplitude window at this mesh density; tore open a boolean seam |
| F-7 | **Medium** | `sculpt_ops` | No structured way to find a point on the surface, so every sculpt needs an `execute_python` probe first |
| F-8 | **Medium** | `create_curve_form` (loft) | 16-section cap + multi-KB literal point payload; no procedural input |
| F-9 | **Low** | `capture_turntable` | `lighting` parameter appears inert |
| F-10 | **Low** | `array` (linear) | Source is left outside the group it creates; deleting the group orphans it and it then silently claims the next requested name |
| F-11 | **Low** | `inflate_region` / `soft_move` | Cannot dome a loft's flat `cap_ends` end cap |
| F-12 | **Low** | `uv_atlas` | `all_inside:false` for a 4e-4 overshoot on a 1x1 atlas where there is nothing to bleed into |
| F-13 | **Low** | `restore_checkpoint` | Resets the panel's active camera to `|persp` |
| F-14 | **Low** | `assign_material` | One mesh per call; a 22-part model needs 22 calls or a `combine` pass |

---

## F-1 — `bake_mesh_maps` hung for 40 minutes and blocked the session **[BLOCKER]**

The single most expensive event of the run. It cost a Maya restart and about an hour.

**Call:**
```
maya_bake_mesh_maps(
  meshes          = ["|kethran|body"],     # 57,724 tris, one shell, watertight
  out_dir         = "<scratch>/kethran/maps",
  maps            = ["ao", "curvature"],
  curvature_output= "both",
  curvature_radius= 4,
  resolution      = 2048,
  apply_ao        = false,
)
```
UVs had been created immediately before by `uv_atlas(project="box", cols=1, rows=1)`.

**Observed:**
- Returned `TimeoutError: command 'bake_mesh_maps' did not finish within 300.0 s`.
- It kept running. Subsequent calls returned `BusyError` naming it, with elapsed time —
  I watched it go 923 s -> 1992 s -> 2146 s.
- Polled `out_dir` on disk continuously for **~40 minutes total: zero files ever appeared.**
- Recovery required `Stop-Process` on Maya and a relaunch, then restoring a checkpoint.

**Three distinct problems here:**

1. **The timeout hint names a parameter the tool does not have.** The error said
   *"for long operations pass a larger `timeout_s` (up to 1800 s)"*. `bake_mesh_maps` has
   **no `timeout_s` in its schema** (`render_scene` does). So the hint's advice is
   unfollowable. Either add the parameter or change the hint.
2. **No progress signal.** "Slow" and "hung" are indistinguishable from the client side.
   With zero bytes on disk after 40 minutes I could not tell whether waiting another 10
   minutes would help. Some incremental output — per-map completion, or a partial file —
   would have made this a 5-minute decision instead of an hour-long one.
3. **A single tool call can wedge the entire session with no cancel path.** Every other tool
   returned `BusyError` and there was no way to interrupt. Given that sculpt work is not
   undoable (F-2), "kill Maya" is a genuinely destructive last resort.

**Suspected trigger (unverified):** `curvature_output:"both"` at `resolution:2048` on a
58k-tri mesh, and/or `curvature_radius:4`. Note the docstring says the radius default of 0.1
"suits metre-scale assets" — my asset is metre-scale but authored in **cm**, so I set 4.
If radius is used as a ray length in scene units, a 40x default radius on a 58k mesh may be
the cost explosion. Worth testing radius sensitivity in isolation.

**Ask:** a `timeout_s` parameter that actually aborts; a cheap pre-flight cost estimate or a
refusal above some (tris x resolution x maps) budget; progress output.

---

## F-2 — `sculpt_ops` auto-checkpoints collide, destroying the recovery point **[HIGH]**

Every `sculpt_ops` call that contains a vertex-writing op returns the **same**
`checkpoint_id: "1000_auto_sculpt"`. Consecutive calls overwrite the same file.

The tool correctly and repeatedly warns that these ops bypass the undo queue and that the
checkpoint is the only way back. But because the id is reused, **the checkpoint only ever
reverts the single most recent call.** After three sculpt calls in a row there is no path
back to the state before the first one.

This bit me directly: I applied a `displace_noise` pass, then a scar pass. When the noise
turned out to be wrong (F-6), the checkpoint held *post-noise, pre-scar* — exactly the state
I did not want. I only recovered because I had manually copied an earlier checkpoint `.ma`
to my own scratch directory as insurance.

**Ask:** monotonic ids (`NNN_auto_sculpt`) like `combine`/`boolean` appear to use, so a
sculpt session is a stack rather than a single slot.

**Related, positive:** the warning text itself is excellent — it names the exact ops, says
plainly that `maya_undo` will not work, and gives the id to pass to `restore_checkpoint`.
Please keep that wording. The defect is the id, not the message.

---

## F-3 — Arnold and the viewport disagree on material values **[HIGH]**

The same `standardSurface` values render as two different materials depending on path.

| Material | linear `baseColor` | `capture_viewport` (`lighting:'scene'`) | `render_scene` (arnold) |
|---|---|---|---|
| `claw` | `[0.028, 0.026, 0.026]` | near-black — correct | **pale mid-grey** |
| `hide` | `[0.105, 0.083, 0.066]` | dark brown — correct | **pale beige clay** |
| `horn` | `[0.072, 0.059, 0.042]` | dark olive-brown — correct | light taupe |

Lighting in both cases was `setup_lighting(three_point)`.

**What I tried:** halved the rig intensity 2.6 -> 1.25 and darkened the hide. Arnold's
reported `mean_luma` moved 36.9 -> 27.2, but the *relationship between materials* did not
recover — a 0.028 albedo still rendered as light grey, which no amount of exposure change
should produce. `clipped_fraction` was 0.0000, so it is not simple blowout.

**Consequence:** I had to abandon Arnold for the deliverable and shoot the hero shot as a
1400 px viewport capture. That is a real capability loss — no ray-traced shadows, no true
transmission on the ear membrane.

**Also:** the two paths need roughly **2x different rig intensity** for a comparable look
(viewport wanted ~2.2, Arnold ~1.0-1.25). Since `setup_lighting`'s docstring defines
intensity 1.0 as "a surface facing the key reads its OWN albedo", *Arnold* looks like the
one honouring the contract and the viewport looks under-lit — but the viewport is the one
whose output matched the authored colours. I could not reconcile these and I am not certain
which end is wrong.

**Ask:** a stated colour-management contract for each path, and ideally a note in
`setup_lighting` that its intensity calibration is path-specific.

---

## F-4 — VP2 materials-unbound green frames **[HIGH, known]**

Four occurrences. Flagged to me in advance as a known issue under repair; recording the data
in case the pattern helps.

| Call | Frame that failed | What went green |
|---|---|---|
| `capture_viewport(angles=[side, three_quarter], lighting=scene)` | `side` | whole body; horns correct |
| `capture_viewport(angles=[three_quarter, side], lighting=scene)` | `three_quarter` | horns only; body correct |
| `capture_viewport(angles=[current, side], lighting=scene, buffer=ssao)` | `current` | body; hooves + crest correct |
| `capture_viewport(angles=[side, three_quarter], lighting=scene, buffer=ssao)` | `side` | everything |

**Pattern worth checking: all four were `lighting:'scene'`.** I took many
`lighting:'default'` captures in this session and none of them failed. In every case the
*other* angle in the same call rendered correctly, so it is per-frame, not per-call, and it
affects a different subset of meshes each time. Reshooting always fixed it.

Rough incidence: 4 bad frames out of roughly 20 `lighting:'scene'` frames.

---

## F-5 — sweep `worst_station_deviation`: the hint's remedy did not work **[MEDIUM]**

The warning reads:
> `worst station deviation 0.0537 of form size at sweep path[2] - raise resolution or simplify the curve`

**Raising `resolution` did not reduce it.** Two recorded builds of the same hind leg:

| Build | `resolution` | reported deviation |
|---|---|---|
| B | `{along: 48, around: 20}` | 0.0477 |
| C | `{along: 64, around: 22}` | **0.0537** |

*Caveat, stated honestly:* the path points also changed slightly between B and C, so this is
not a controlled experiment. But raising `along` by 33% certainly did not reduce the
deviation, and the deviation appears to come from the spine curve fit rather than from
tessellation density.

**The second, larger issue is the unit.** "0.0537 of form size" on a 190-unit limb is
**~10 cm of real displacement**, and it does not fall where you expect — it *smooths away a
deliberate zig-zag*. I specified an ungulate limb with a proper elbow-back / carpus-forward
break; the fitted spine rounded it off and put my lower leg roughly **15 cm behind** where I
asked. I read 5% as negligible and moved on. It was not negligible; I only found it later by
dumping vertex positions.

**Ask:** report the deviation in **scene units as well as** the fraction, and name the
station's requested-vs-achieved position. `"path[2]: requested (45,104,-66), achieved
(41,99,-78), off by 13.5 cm"` would have changed my decision immediately.

---

## F-6 — `displace_noise` has no usable window on an organic mesh at this scale **[MEDIUM]**

Purpose per the docstring is to "kill the untouched-primitive look". I could not get it to.

| `amp` | `freq` | mesh | result |
|---|---|---|---|
| 1.5 | 0.05 | 14.8k tris | **invisible** at any distance |
| 3.5 | 0.035 | 14.8k tris | visible **polygonal faceting**, plus it tore open a boolean union seam into a crack |
| 0.9 | 0.07 | 57.7k tris | invisible |
| 1.8 | 0.055 | 57.7k tris | visible, but reads as **crumpled quilting / a deflating balloon**, not hide |

I reverted it entirely and shipped a smooth hide, which is a worse-looking lie but a less
distracting one. `kethran_hero_viewport.png` in this folder is the amp-1.8 result, kept as
evidence.

Three separate asks:

1. **Units are undocumented.** `amp:0.05` and `freq:2.6` defaults imply a unit-scale object.
   There is nothing in the docstring telling a caller how to scale these for a 340-unit
   subject; I found the range by binary search across four attempts.
2. **It displaces vertices, so its finest wavelength is bounded by edge length.** At ~4 cm
   edges it cannot produce skin grain, only lumps. Consider refusing (or warning) when the
   requested wavelength approaches the mesh's mean edge length — that is precisely the regime
   where the output is faceted garbage.
3. **It amplified a boolean seam into a visible crack.** Displacing across a union seam where
   the two surfaces meet at a shallow angle opened it. Worth knowing that "run a boolean
   union then displace" is a trap.

---

## F-7 — No structured way to find a point on the surface **[MEDIUM]**

`soft_move` and `inflate_region` take a world-space `center` and refuse when it is farther
than `radius` from the mesh. On an organic form produced by loft + booleans + sculpt, **I
have no idea where the surface actually is** — it is not where my construction numbers said,
because the sweep fit moved it (F-5) and prior inflates moved it again.

I hit five refusals in a row guessing. I then wrote this, and every subsequent op landed
first time:

```python
import maya.api.OpenMaya as om
s = om.MSelectionList(); s.add("|body")
pts = om.MFnMesh(s.getDagPath(0)).getPoints(om.MSpace.kWorld)
# band by y, print min/max/centroid of z and x per band
```

**This is the clearest case in the run of a structured tool making the ordinary case
expensive.** The ordinary case is "put a muscle bulge on the outside of the shoulder", and it
currently requires dropping to the API to find out where the shoulder is.

**Ask:** something like `maya_get_surface_point(mesh, near=[x,y,z])` returning the closest
surface point, its normal and its vertex id — or let `center` accept a ray/direction and snap.
`vertex_id` exists as an alternative but is unusable without a way to *find* the vertex id.

**Strongly positive, and worth preserving:** the refusal message is the best in the toolset —
> `radius 17 does not reach the mesh: the nearest vertex is 17.3565 from the center, so every vertex weighs 0`

It gives the exact distance, so the fix is arithmetic rather than another guess. It also
reports which ops already applied before the failure, which made partial failures safe. Please
do not regress this.

---

## F-8 — loft: 16-section cap and a multi-KB literal payload **[MEDIUM]**

`create_curve_form(kind="loft")` takes `sections` as literal 3D points, max 16 sections,
3-64 points per ring.

- I wrote an **external Python generator** (`gen.py` in this folder) purely to emit the JSON,
  then pasted ~7 KB of literal floats into each call. Three body rebuilds = three such
  payloads.
- **The 16-section cap directly shaped the model.** I wanted separate torso, neck and head
  lofts; the seams looked like a toy, so I merged all three into one surface — which needed
  16 sections exactly, with the head getting five and the neck three. That merge turned out
  to be the right artistic call, but it was forced by the cap, not chosen.

**Ask:** either raise the cap, or accept a section *function*/parameterisation, or accept a
file path to a JSON section table. Any of the three removes the paste step.

**Positive:** `worst_station_deviation` on the *loft* was consistently ~0.004 — the surface
really does pass through the numbers, and being able to trust that without rendering is what
made the parametric approach viable at all.

---

## F-9 — `capture_turntable`'s `lighting` parameter appears inert **[LOW]**

Two consecutive calls, identical but for `lighting`:

```
capture_turntable(target="|kethran", n_frames=8, lighting="scene",   resolution=640)
capture_turntable(target="|kethran", n_frames=8, lighting="default", resolution=640)
```

The two contact sheets were **visually indistinguishable** — same exposure, same shading,
same dark falloff on the away-facing frames. The same `lighting` parameter on
`capture_viewport` produces an obvious difference. Either the parameter is not reaching the
turntable render, or the sheet always uses scene lights.

Separately: at `lighting:'scene'` the away-facing frames are very dark, because (unlike
`render_scene`) the turntable does not appear to relight per frame. A `relight` option
matching `render_scene`'s would make the sheet far more useful for judging form.

---

## F-10 — `array` linear leaves the source outside its own group **[LOW]**

```
maya_array(name="|crestA", mode="linear", count=4, group_name="crestGrpA", ...)
-> group "|crestGrpA" contains crestA_1..3;  "|crestA" stays at the scene root
```

This is documented ("The source is never reparented"), but the consequence is not obvious:
`delete_objects(["|crestGrpA"])` looks like "remove that array" and instead leaves an orphan
sitting in the scene. My next `create_primitive(name="crestA")` then silently became
**`crestA_001`**, colliding with the leftover.

It did report the assigned canonical name in the result, so nothing was actually hidden —
this is a papercut, not a defect. But "delete the array I just made" being a two-call
operation is a sharp edge worth smoothing (e.g. optionally parent the source into the group,
or return the source name in the result so it is obvious it survived).

---

## F-11 — `inflate_region` / `soft_move` cannot dome a loft's flat end cap **[LOW]**

A loft built with `cap_ends:true` closes its ends with a flat n-gon. On the muzzle this read
as a machined flat disc and was very visible in front captures.

Neither of these fixed it:
```
soft_move     (center=[0,136,215], radius=20, delta=[0,0,8])
inflate_region(center=[0,136,216], radius=24, amount=7)
```
The cap stayed flat. I assume the single large n-gon has too few vertices to deform, and its
own vertices sit on the rim, not the interior.

**Workaround that did work:** boolean-union a sphere onto the end. That is a heavyweight fix
for "round off the end of my tube".

**Ask:** either triangulate/subdivide caps so they are deformable, or offer a `cap_style`
of `"dome"` on `create_curve_form`.

---

## F-12 — `uv_atlas` `all_inside:false` on a harmless overshoot **[LOW]**

```
uv_atlas(names=["|kethran|body"], cols=1, rows=1, patch=0, project="box", margin=0.01)
-> uv_bounds [0.009787, 0.009786, 0.990356, 0.990175]
   patch_rect [0.01, 0.01, 0.99, 0.99]
   all_inside: false
```

The overshoot is 2e-4 to 4e-4 UV units — rounding noise — and this is a **1x1 atlas**, so
there is no neighbouring patch to bleed into. The flag is literally true and the tool is
being honest, which I appreciate given what the flag is for. But on a single-patch layout it
reads as a failure when nothing is wrong. Consider suppressing it (or wording it differently)
when `cols*rows == 1`, or tolerancing it against the margin.

---

## F-13 — `restore_checkpoint` resets the panel's active camera **[LOW]**

After a restore, `capture_viewport(angles=["current"])` was looking through `|persp`, not the
camera I had made active with `set_camera` before the checkpoint. The named cameras did
survive inside the restored file — only the panel's *choice* was reset. Minor, but it silently
invalidates `angles:["current"]` after any restore.

---

## F-14 — `assign_material` is one mesh per call **[LOW]**

A 22-part model needs 22 calls, or a `combine` pass first to collapse same-material parts. I
did the latter (7 combines, then 7 assigns).

The shader-reuse behaviour — same `name` + same shader type reuses the existing shader and
applies the params to it — is what made iterating on colours cheap, and is a genuinely good
design. An optional `meshes: [...]` list would remove the remaining friction.

---

## Things that worked well — please don't regress these

Reporting these because a friction log that only lists complaints is misleading about where
the tooling is strong.

- **`inflate_region`'s out-of-reach refusal** (F-7) — gives the exact distance, names which
  ops already applied, and names the checkpoint to restore. This is the model the rest of the
  error surface should follow.
- **`BusyError` names the running command and its elapsed seconds.** During the F-1 hang this
  was the only thing telling me the difference between "wedged" and "working". Extremely
  valuable.
- **`boolean_op` reports `watertight` and carries `a`'s pivot, parent and UV bounds onto the
  result, and says so.** I ran 8 unions in sequence on a growing organic mesh and every one
  came back watertight. That is the single most reliable tool in the set.
- **`combine`'s shading-group warning** — *"inputs carried 2 different shading groups; the
  result is one object-level assignment to hornSG"* — told me exactly what Maya had done
  quietly. That was the behaviour I wanted, and I only knew it landed because it said so.
- **`capture_viewport`'s occlusion note** — *"target |body is partly hidden behind legFR,
  legHR ... 2 of 9 sample points on its bounding box are blocked"* — correctly identified
  that my close-ups were being blocked, and told me the fix (`isolate`).
- **`capture_viewport`'s `target`-vs-`current` note** — it told me plainly that `target` did
  not frame the `current` angle rather than silently ignoring it.
- **`create_curve_form`'s `worst_station_deviation`** as a concept: being able to trust that
  the surface passes through my numbers without rendering is what made parametric body-building
  work. The problem in F-5 is the *unit* and the *hint*, not the measurement.
- **`new_scene` stating the linear unit** rather than inheriting it. I never once had to wonder
  what my numbers meant.

## Suggested priority

1. **F-1** — a hang with no cancel path and an unfollowable hint is the only thing here that
   cost an hour and a process kill.
2. **F-2** — silent loss of the only recovery path for non-undoable operations.
3. **F-7** — this one shapes the whole authoring loop for organic work; fixing it would remove
   most of my `execute_python` usage.
4. **F-3 / F-4** — a render path that disagrees with the viewport, plus intermittent unbound
   materials, means captures cannot be fully trusted, which undermines the "correct what you
   see" workflow the server's own instructions prescribe.
5. **F-5, F-6, F-8** — the organic-modelling ergonomics cluster.
