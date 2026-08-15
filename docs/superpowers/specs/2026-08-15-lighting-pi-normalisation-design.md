# setup_lighting π-normalisation — design

Redmine: **#617** (this work), **#615** (the display transform that exposed it), **#600** (the
art revision whose colour findings depend on both).

## The problem, in one number

The revision-3 hero's roof deck has an albedo of (158,156,148). With #615 landed — so the gamma
is now right — it renders at **102**.

Arnold's distant light is not π-normalised. A lambert surface facing the key at `intensity 1.0`
returns `albedo / π`, not `albedo`. The tool's neutral default therefore delivers about **32%**
of a fully-lit surface, and "1.0" names nothing: it is a number you turn until the picture looks
right.

Every caller has been doing exactly that. The intensities across the eval scripts read 1.2, 1.5,
2.1, 3.0, 3.2, 4.0, 16.0 — each dialled in by eye, and dialled in against images that were *also*
2.2 gamma too dark. They are correcting two faults at once, which is why no two of them agree.

## Measured facts this design rests on

Established live on 9877, 2026-08-15, with the #615 calibration plane (`standardSurface`,
`baseColor` linear 0.5, `base` 1.0, `specular` 0.0, N·L = 1, every other light parked at 0).

| path | intensity 1/π | intensity 1.0 | intensity π |
|---|---|---|---|
| Arnold, via `render_scene` | — | — | **188** — fully lit |
| VP2, via `capture_viewport` with `lighting="scene"` | 32 | 83 | **165** — fully lit, ACES-encoded |

**Both paths divide by π.** One factor fixes both; no renderer branching.

| other measurement | value |
|---|---|
| `environment` dome at intensity 1.0, same plane | ~(122,110,107) — a π-divided dome would be ~88 |
| `capture_viewport` default `lighting` | `"default"` (Maya's headlight) — scene lights do nothing until `lighting="scene"` |
| VP2's encoding | the scene's **view** transform (ACES), where `render_scene` now uses the **output** transform (un-tone-mapped) |

The dome measurement is the one that bounds the change: hemisphere integration already carries
the π, so a dome needs no correction and must not receive one.

## The unit

**`intensity = 1.0` means a surface facing the key reads its own albedo.**

0.5 is visibly dim, 2.0 is deliberately hot, and the number is a statement about the picture
rather than about Arnold's internals. Relative key/fill/rim ratios are unchanged — only the unit
moves. The `(0, 20]` range stays; 20 now means twenty times fully lit, which is still a sane
ceiling for a deliberate blow-out.

## What changes

### 1. The factor, in `maya_plugin/handlers/lighting.py`

A module constant, applied where directional lights are created:

- `_build` (line 118) — serves `three_point` and `single_sun`
- `_build_dome`'s **no-Arnold fallback** (line 270) — that directional light stands in for a
  dome, so it must match the dome's exposure or a Maya without mtoa silently renders three times
  darker than one with it

The real `aiSkyDomeLight` (line 298) is **not** touched.

### 2. The tool description, in `src/maya_mcp/server.py`

`intensity`'s description is `"Overall rig intensity; 1.0 is neutral."` — which was never true and
is now wrong in a checkable way. It states the unit instead. Without this line the change is
invisible to every caller that reads the tool surface rather than the source.

### 3. The callers, split by kind

**Gate scripts get a mechanical `/π`.** `array_deform_live`, `lookdev_controls_live`, `brute_v6`,
`brute_v7`, `gem_brute_v5`, `rotunda`, `structures`, `m2_judged_run`. Dividing by π reproduces
today's pixels exactly, so no gate's assertion changes meaning and no gate needs re-judging. This
is a rename, not a re-tune.

**The two demigol art scripts get re-judged, not divided.** `demigol_kit.py` (3.2) and
`demigol_structures.py` (1.5) are the delivery, and their numbers were compensating for the gamma
bug as well. They move to a key of about 1.0 and are confirmed by eye during the revision-3
regeneration pass — which has to re-render them anyway.

## Verification

**Headless** (`tests/test_lighting.py`): `_build` passes `intensity × factor × π` to
`directionalLight`; the key/fill/rim *ratios* are unchanged; the dome's own intensity is passed
through untouched; the no-Arnold fallback gets the factor.

**Live** (`evals/render_calibration_live.py`, extended): a second measurement that goes *through*
`setup_lighting(preset="single_sun", intensity=1.0)` rather than through a hand-built light, with
the calibration plane rotated to face the sun so N·L = 1, asserting **188 ± 3**.

That second check is the whole claim in one number, and it is the only one that could catch the
factor being applied in the wrong place — a headless test proves the multiplication happened, not
that the picture came out right. The existing 188 check stays as it is: it uses its own light at
intensity π and is unaffected by this change, which makes it a useful control.

## Out of scope

- **#618 — isolate hides the sky dome.** Found while measuring for this. `cmds.ls(geometry=True)`
  reports `aiSkyDomeLight` shapes as geometry, so `render_scene(isolate=[...])` under a dome
  returns a pure black frame. Adjacent and cheap, but a different defect in a different handler.
- **The VP2/render tone mismatch.** Viewport captures encode through the scene's ACES view
  transform (0.5 → 165) while renders now use un-tone-mapped (0.5 → 188), so the same asset
  reads differently in the two tools. Real, worth a ticket, not worth folding in here.
- **Any scene or script outside this repo** that passes an intensity. Nothing is versioned or
  shimmed: the unit changes, the tool description says so, and callers adjust.
- **The delivery itself.** Lights never leave our Maya scene. The game side receives geometry,
  albedo/mask/normal and a manifest, with no baked lighting of any kind. This changes what our
  images say, not what ships — it reaches them only upstream, in that colour authored against a
  wrongly-exposed image bakes the compensation into the atlas, and *that* does ship.
