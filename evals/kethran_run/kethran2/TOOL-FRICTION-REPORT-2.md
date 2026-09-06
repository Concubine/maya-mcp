# maya-mcp — friction report 2: texturing the kethran's hide

**Reporter:** the same Claude session that produced `TOOL-FRICTION-REPORT.md` and the model.
**Date:** 2026-09-05. **Audience:** the maya-mcp developer.
**Task (handed over by the tooling session):** texture the hide — item 1 of my own handoff.

I am the only caller who saw the *before*, so the first section is a verdict on the five fixes.
As before: I report what the tools told me, I did not read maya-mcp source, and where I am
inferring rather than observing I say so.

## Environment

- Maya 2027, port **9879**, launched with `-WorkingDirectory D:\devel\maya-mcp` so it imported
  main's plugin. Main at **f3050ed**. (I did not independently verify the loaded plugin's hash —
  same caveat as last time — but every behaviour below is consistent with the fixes being live.)
- Body mesh: 57,724 tris, watertight, one shell, `hide` / `hideSG`.
- **Constraint on this run:** this session is confined to a git worktree, and every write to
  `D:\devel\maya-mcp\...` was refused by the harness — including `maya_open_scene` on the repo
  copy. I did not route around it. I verified my scratchpad `kethran.ma` was **byte-identical**
  to the committed copy (`sha256 5b98f540…`) and worked from mine. **All outputs are therefore in
  my scratchpad, not in `evals\kethran_run\`** — see "Where the files are" at the end.

---

## Part 1 — verdict on the five fixes

| Was | Verdict | Evidence |
|---|---|---|
| F-1 bake hang (40 min, 0 files) | **FIXED — decisively** | The *exact* config that hung — 2048, `ao`+`curvature(both)` — returned in seconds. A 1024 three-map bake also returned promptly. |
| F-2 checkpoint id stuck at `1000` | **FIXED** | Ids ran `001, 006, 007, 008, 009, 010, 011, 012` across the session. Monotonic, no collisions. |
| F-12 `uv_atlas all_inside:false` | **FIXED — and my diagnosis was wrong** | See below. |
| `timeout_s` on the bake tools | **PRESENT** | In the schema, accepted (`600`, `900`). Not exercised — nothing timed out. |
| F-4 VP2 green frames | **No recurrence** | Zero green frames in ~8 `lighting:'scene'` captures plus a turntable. Not proof, but the before/after contrast is stark (4 in ~20 last time). |
| F-3 viewport vs Arnold | **NOT resolved for me** | Still disagree, ~2.5-3x on exposure, and ~5x on bump. Detail below. |

### F-12: I was wrong, and the tool was right

Last time I wrote off `all_inside:false` as *"rounding noise… technically true, needlessly
alarming"* and recommended suppressing it on a 1x1 atlas. **That recommendation was wrong and
should not be implemented.**

Old run: `uv_bounds [0.009787, 0.009786, 0.990356, 0.990175]`, `all_inside:false`.
This run:  `uv_bounds [0.01, 0.01, 0.99, 0.99]`, `all_inside:true`.

Those four-ten-thousandths of overshoot were not rounding — they were the visible tip of the
per-face normalisation (#845) that caused the 40-minute bake. The flag was the **only** signal I
was given that anything was wrong, and I talked myself out of it because the magnitude looked
trivial. Worth remembering as a design point: the flag was correct *and* it was too quiet to
survive a caller's judgement. Something like "UV bounds do not match the patch — this usually
means a stacked layout, which makes bakes pathological" would have saved me an hour.

### F-1: what the fix looks like from outside

```
bake_mesh_maps(meshes=["|kethran|body"], maps=["ao","curvature"],
               curvature_output="both", curvature_radius=3,
               resolution=2048, timeout_s=900)
-> returned promptly, both maps written, no warnings
```
For comparison, the identical shape of call last time ran >2146 s and wrote nothing. My F-1
speculation that `curvature_radius:4` was the cost driver was **wrong** — radius 3 at 2048 is
fine. The UV layout was the whole problem.

### The #837 fallback warning earned its keep — first call

My very first Arnold render came back with:

> `arnold wrote nothing at the path Maya predicted for it, so this frame fell back to the hardware renderer: it is RAW LINEAR, with no display transform (a 0.5 albedo reads 127 where the render eye says 188), no sky-dome light and no transmission. Measured cause: an empty 'images' file rule in the project makes the prediction and Arnold's write disagree - check the project's workspace (#837)`

That is exactly what happened, it named the cause, and it named the ticket. Under the old
behaviour I would have judged a hardware frame as an Arnold frame and drawn false conclusions
about the materials — **which I now suspect is part of what happened in my original F-3.** This
warning is the single most valuable thing added since my last run.

---

## Part 2 — new findings

### N-1 — bake stats report `distinct_values: 2` on maps that are visibly rich **[MEDIUM]**

Every bake, every map, both resolutions:

```
"stats": {"pixel_count": 4194304, "distinct_values": 2, "non_uniform": true, "blank": false}
```

The AO map is a full continuous gradient with hundreds of values (I opened it: legs, mirrored
body halves and the crest plates are all clearly readable, with smooth falloff). A 1024 AO PNG is
**1.09 MB** — a genuinely two-value 1024 image would compress to a few KB.

This matters because `distinct_values` is presented as the evidence that the bake sampled
something, right beside `blank` and `non_uniform`. As shipped it cannot distinguish a good map
from a flat one — the number is 2 either way. I nearly threw away a perfectly good bake on the
strength of it, and only kept it because the file size didn't fit the story.

Either the statistic is miscomputed, or it means something other than its name (a distinct-value
count *of what*?) and needs renaming.

### N-2 — `apply_surface_detail` reports the same node 18 times **[LOW, cosmetic]**

```
"file_nodes": ["hide_color_detail", "hide_color_detail_p2d", "hide_color_detail_p2d",
               ... x18 ..., "body_height_tex", "body_height_p2d", "body_height_bump"]
```

I checked the scene, expecting a node leak: `place2dTexture` count **2**, `file` count **2**,
`bump2d` count **1**. The scene is clean. It is purely a duplicated entry in the result payload —
presumably listed once per connected attribute. Harmless, but it reads as an 18-node leak to a
caller who has been trained by #812 to watch for exactly that.

### N-3 — viewport and Arnold disagree on bump2d magnitude by roughly 5x **[HIGH]**

This is the sharpest form of the surviving F-3, and it is easy to reproduce.

| `bumpDepth` | `capture_viewport(shading='textured')` | `render_scene(arnold)`, same lights, close zoom |
|---|---|---|
| 2.2 | coarse, crusty "popcorn" — clearly too much | (not shot) |
| 0.55 | strong, well-read pebbled hide | **nothing visible at all** |
| 2.6 | over-textured | reads correctly |
| 5.0 | (not shot) | strong, comparable to viewport at ~0.55 |

I found this the expensive way: I judged the grain in the viewport, dialled `strength` from 2.2
down to 0.6 because it looked like popcorn, and then the Arnold render came back completely
smooth. My first reading was "the texture is missing in Arnold". It was not — it was ~5x under
the threshold where Arnold shows it.

Note this interacts with the tool's own documentation. `apply_surface_detail` says its defaults
are *"the smallest values measured to READ in a render"* — so the defaults are calibrated to the
**render** eye. That is a defensible choice, but it means **judging bump in the viewport and
shipping to a render systematically under-shoots**, and the workflow the server's instructions
prescribe ("capture the viewport after each change and correct what you see") walks you straight
into it. A line in `apply_surface_detail`'s docstring saying "strength maps 1:1 to bumpDepth and
is calibrated for `render_scene`; the viewport exaggerates bump — judge grain in a render" would
have saved the whole detour.

For the record, `strength` maps exactly to `bump2d.bumpDepth` (strength 2.2 -> bumpDepth 2.2).

### N-4 — exposure still disagrees, ~2.5-3x; I could not fully isolate it **[HIGH, partly refined]**

Same scene, same lights, same materials:

- `capture_viewport(lighting='scene')` looks correctly exposed at rig intensity **~1.15-1.2**.
- `render_scene(arnold)` looks correctly exposed at rig intensity **~0.4-0.5**.

At intensity 1.15 Arnold rendered the hide as pale clay; at 0.5 it reads as a plausible dark
taupe. The viewport at 0.5 is far too dark to judge.

**I want to be careful here, because I over-claimed last time.** Two confounds I have now
identified and which explain part but not all of it:

1. `render_scene(relight=True)` swings the rig to follow the camera, so the subject faces the key
   directly. `capture_viewport` does not relight. On a three-quarter view that alone is a large
   difference. I re-ran with `relight=False` and the gap narrowed but did not close.
2. `setup_lighting`'s contract is stated per-key ("a surface facing the key reads its OWN
   albedo"), but `three_point` lights the subject with key **plus** fill **plus** rim. A surface
   facing several of them receives more than 1.0x at intensity 1.0. That is arguably correct
   behaviour and not a bug, but it means "intensity 1.0 = albedo" does not hold for the rig as a
   whole, which is how a caller will read it.

Even with `relight=False` at intensity 0.35 I measured body pixels around 120/255 where a ~0.127
linear albedo predicts roughly 69/255. So something around 2x remains unexplained. **I could not
isolate it further** and I am not claiming a colour-management bug this time — only that the two
eyes still need materially different rig intensities, and that a caller cannot tune once and
trust both.

Suggested, cheap: have `setup_lighting` state in its result what total illumination a
camera-facing surface will actually receive, and note that `relight` changes it.

### N-5 — `-proj` with an `images` **folder** is not enough; the file rule must exist **[MEDIUM]**

The handover instructions (and my own reading) said to create the project dir with an `images`
subfolder. I did. The workspace file rule was still empty:

```
images rule BEFORE: ''      # despite agent_project/images existing on disk
```

That empty rule is precisely the #837 measured cause, so the first render silently fell to
hardware (caught only by the new warning). The fix was:

```python
cmds.workspace(fileRule=("images", "images")); cmds.workspace(saveWorkspace=True)
# images rule AFTER: 'images'
```

**Ask:** since the cause is known and named in the warning, either have `render_scene` repair the
rule itself (or refuse before rendering), or have whatever creates/accepts a `-proj` ensure a
minimal `workspace.mel`. Telling the caller to "check the project's workspace" is much better than
silence, but this is a one-line fix the tool could just do.

### N-6 — grain rides AO, so it lands only where the model is already occluded **[MEDIUM]**

`grain` blends curvature and inverted AO into the height map. On this creature that put a strong
pebbled texture on the lower flank, belly and inner legs, and left the **upper back and shoulder
almost smooth** — the large convex areas that a viewer actually reads first.

That is the documented design and it is right for a hard-surface prop (grime and grain collect in
pockets). On an organic hide it is backwards: a real animal's thickest, most textured skin is on
the exposed dorsal surfaces. There is no way to ask for "uniform grain, not mask-driven" — the
direction comes from the masks by definition.

**Ask:** a `uniform` or `mask_influence` control on `grain` (0 = flat noise everywhere, 1 = fully
mask-driven) would make this usable for creature hide without changing the default behaviour.

### N-7 — iterating on grain requires dropping to Python **[MEDIUM]**

`grain` correctly refuses to stack on an existing bump network. But there is no tool to remove
one, so the moment you want to change grain frequency (which is baked into the height image, not a
node attribute) you are stuck. I had to:

```python
for n in ["body_height_bump", "body_height_tex", "body_height_p2d"]: cmds.delete(n)
```

`restore_checkpoint` is the documented alternative, but the open #847 hazard says not to restore
after capturing — and by then I had captured. So Python was the only path.

**Ask:** either `apply_surface_detail(replace=True)` for grain, or a small
`remove_surface_detail(mesh, kinds=[...])`. This is the same shape of complaint as F-7 last time:
the structured tool covers the first application and not the iteration, and iteration is the
whole job.

### N-8 — visible UV seam stitching from box projection + bake padding **[LOW-MEDIUM]**

The AO and curvature maps carry dark dotted borders around every UV island (clearly visible when
you open `body_ao.png`). Those propagate into `hide_color_detail.png` and then read on the model
as fine **stitched seam lines** across the shoulder and along the spine. Going 1024 -> 2048
reduced but did not remove them.

Partly inherent: `uv_atlas` offers only `box`/`planar`/`keep`, and box projection on an organic
mesh makes many small islands, i.e. many seams. Worth knowing that the current UV toolset cannot
produce a seam-clean organic layout, and that bake padding makes each seam visible rather than
merely present.

### N-9 — texture paths are absolute; moving the folder breaks the look **[LOW, but will bite]**

The file nodes point at my scratchpad:

```
hide_color_detail -> …/scratchpad/kethran2/maps/hide_color_detail.png
body_height_tex   -> …/scratchpad/kethran2/maps/body_height.png
```

When this folder is moved into `evals\kethran_run\`, both break silently — Maya renders a missing
map as flat, it does not complain. Remap after moving:

```python
cmds.setAttr("hide_color_detail.fileTextureName",
             "D:/devel/maya-mcp/evals/kethran_run/maps/hide_color_detail.png", type="string")
cmds.setAttr("body_height_tex.fileTextureName",
             "D:/devel/maya-mcp/evals/kethran_run/maps/body_height.png", type="string")
```

(`assign_pbr`'s docstring notes paths resolve on the Maya machine and a missing file is *refused*
rather than rendered flat — that guard does not exist for maps wired by `apply_surface_detail`.)

---

## Part 3 — what worked well

- **The #837 hardware-fallback warning.** Named the symptom, the numeric consequence, the measured
  cause and the ticket. It turned a silent wrong answer into a two-minute fix.
- **`changed_fraction` per effect** on `apply_surface_detail` (grime 0.954, wear 0.263, grain
  0.961). That is the right kind of number: it told me wear had only touched a quarter of the
  surface, which matched the sparse curvature map and stopped me chasing a non-bug.
- **The `grain` refusal on an existing bump network.** Correct, and it prevented me stacking two
  bump networks by accident. The gap is the missing removal path (N-7), not the refusal.
- **Monotonic checkpoint ids.** Twelve distinct restore points across the session instead of one
  slot overwritten twelve times. This is what makes risky iteration safe.
- **`uv_atlas` returning measured `uv_bounds` rather than a success claim** — that is what made
  the before/after on #845 legible to me at all.
- **`render_scene` frame stats** (`opaque_px`, `distinct_colors`, `clipped_fraction`,
  `mean_luma`). `clipped_fraction: 0.0` is what let me rule out simple blowout in N-4 and keep
  digging instead of guessing.

## Part 4 — what I could not verify

Stated plainly, because a report that only lists conclusions is misleading:

- **I never triggered the #847 hazard.** I followed the rule (open the scene first, never
  `open_scene`/`restore_checkpoint` after capturing) and nothing wedged. That is compliance, not
  evidence the hazard is gone or that it is still there.
- **I did not exercise `timeout_s`.** Nothing timed out, so I confirmed only that the parameter
  exists and is accepted — not that it aborts cleanly.
- **F-4 (green frames) — absence of evidence.** Zero recurrences in ~8 `lighting:'scene'` captures
  plus a turntable, against 4-in-~20 last time. Encouraging, not conclusive; the note in #830 says
  it needs ~28 meshes to reproduce and this scene has 7.
- **I could not isolate the residual ~2x in N-4** after accounting for `relight` and three-light
  summation.
- **I did not verify the loaded plugin's hash**, only that Maya was launched with the repo as its
  working directory.
- **I did not touch the horns, hooves, crest or ears** — budget went to the hide and to
  characterising N-3/N-4. They still carry flat materials.

## Part 4b — added after review: the detail pass alone did not change the distant read

The user looked at the delivered Arnold hero and said "it kinda looks the same". They were
right, and my Part 5 claim below ("addressed at mid distance") was overstated when written.
What went wrong is worth recording because it is a workflow trap, not just a mistake:

* `apply_surface_detail` produces **a bump map and a low-contrast colour composite**. Bump only
  reads under raking light at close range. The grime/wear composite measured ~1.0 stop of
  variation end to end — at full-body framing the creature is still one flat value.
* I tuned the grain in the **viewport**, which over-shows bump ~5x (N-3), then delivered a hero
  in **Arnold**, which under-shows it. So I calibrated in the eye that exaggerates and shipped
  through the eye that hides. The viewport capture at the same camera shows obvious texture; the
  Arnold hero shows almost none. Both are "correct" pictures of the same scene.
* The thing that actually changes a distant read is **large-scale albedo variation**, and no
  tool in the set produces it. The handover brief named it ("countershading and a base albedo
  variation are worth a ramp_gradient or file_texture pass") and I skipped it.

**Fix applied:** built a real hide albedo offline with numpy/PIL from the baked masks
(`build_albedo.py`, next to this file) — countershading driven by the **world-normal G channel**
(dorsal dark, ventral pale), fine mottling, a gentle AO seat, and pale keratin on convex ridges.
Result: 8.2x contrast ratio and 1749 distinct colours where the composite was near-flat. Rendered
`distinct_colors` went 5524 -> 6785 and the animal now reads warm brown with a pale underside
instead of uniform taupe. This is `hide_albedo_v2.png`, wired into `hide.baseColor`.

Three findings fell out of doing it:

**N-10 (MEDIUM) — UV-space noise breaks at island borders.** My first albedo used large smooth
noise in UV space. On a box-projected atlas the islands are discontinuous, so every blotch
stopped dead at an island edge and printed as angular patches on the hip and neck. Geometric
masks (AO, world normal) do not have this problem because they are baked from the surface. Rule:
on a `uv_atlas` box layout, keep procedural UV-space variation **fine only** and take all
large-scale variation from baked masks.

**N-11 (MEDIUM) — multiplying the AO map into albedo prints its island steps.** The AO bake has
tonal steps between islands. At `0.62 + 0.38*ao` those became visible angular patches; at
`0.84 + 0.16*ao` they are gone. The map is fine as a *mask*; it is not clean enough to composite
hard into colour.

**N-12 (MEDIUM, Maya behaviour, not a maya-mcp defect, but it cost a render) — overwriting a
texture on disk does not refresh Maya's file node.** I rewrote `hide_albedo.png` in place and
re-rendered: the frame came back **pixel-identical** — same `distinct_colors` (6530/6651), same
`mean_luma` (14.0/16.0). Maya had cached the image. I only caught it because those stats were
byte-identical rather than merely similar. Writing to a new filename and re-pointing
`fileTextureName` fixed it. **This is a strong argument for `render_scene`'s frame stats:** they
are what made a silently-stale render detectable. A caller judging by eye would have concluded
the edit had no effect and started chasing the wrong thing.

## Part 5 — the model

The hide now has real surface: a fine pebbled grain, grime seated in the recesses, and edge wear
on the crest plates and boolean seams. Against my own critique's item 1 ("the hide is plastic"),
that is addressed at mid distance and in the render.

Still open, unchanged from the first report: muscle masses read as upholstered pads; the lower
legs are columnar; the head is small for the horns; there is no mouth; the ears are weak. Those
are geometry and were explicitly out of scope for this pass.

New weakness introduced by this pass: the seam stitching (N-8) and the uneven grain distribution
(N-6) — the upper back is still smooth where it should be the most textured.

## Where the files are

**Not in `evals\kethran_run\`** — this session could not write there (see Environment). Everything
is in:

```
C:\Users\plotk\AppData\Local\Temp\claude\D--devel-maya-mcp--claude-worktrees-suspicious-wozniak-70acec\
  6f865a17-b45c-4278-8bc9-22402aee9ebe\scratchpad\kethran2\
```

| File | What |
|---|---|
| `kethran_textured.ma` | the textured scene (saved with rig intensity **0.5**, the render-correct value) |
| `maps\body_ao.png`, `body_curvature.png`, `body_world_normal.png` | baked masks (2048 ao+curvature, 1024 world_normal) |
| `maps\hide_color_detail.png` | grime+wear composite, wired to `hide.baseColor` |
| `maps\body_height.png` | grain height, wired via `body_height_bump` -> `hide.normalCamera` |
| `kethran_textured_hero_three_quarter.png`, `_side.png` | Arnold, 1200px, samples 4 |
| `kethran_textured_turntable.png` | 8-view sheet (viewport, shot at intensity **1.2**) |
| `TOOL-FRICTION-REPORT-2.md` | this file |

**Two things to do when moving it into the repo:**
1. Copy `maps\` alongside the scene and remap the two file nodes (N-9).
2. The scene is saved at rig intensity 0.5 because Arnold is the truthful eye. A viewport capture
   of it will look dark — raise `setup_lighting` to ~1.2 for viewport work (N-4).
