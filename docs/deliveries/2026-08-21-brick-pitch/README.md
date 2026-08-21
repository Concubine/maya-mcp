# The brick course pitch, judged by looking (Demigol #652, 2026-08-21)

Demigol's phase 2–3 art ask carried this line, sourced from the revision-2 contract notes:

> the brick texture reads roughly 5–6× oversize, and nobody has looked since

**That is two revisions stale, and the current value is wrong in the other direction.** This is
what was measured and rendered before any of it was changed.

## What the shipped atlas actually contains

Measured off `kit_albedo.png` itself — an FFT down the brick patch, not a reading of the
changelog:

```
brick       patch0   FFT dominant k=54 => 54 courses/patch, period 19.0 px
brick_dark  patch1   FFT dominant k=54 => 54 courses/patch, period 19.0 px
            => 6.00 courses/m, 167 mm course, 19.0 px/course
```

So the history runs: revision 1 drew ~7 courses on a 3 m face (**that** was the 5–6× oversize the
contract diagnosed) → revision 2 corrected it to a faithful 13 courses/m → **revision 3
deliberately coarsened it to 6/m**, and 6/m is what ships today.

## Why revision 3 coarsened it, and why that reasoning does not survive a render

Revision 3's stated reason was a prediction: at 113.8 px/m a real brick course is 8.8 px and the
mortar bed (0.16 of a course) is 1.4 px; sub-2px detail cannot read as mortar, and because
Demigol's import path disables mipmaps to protect the atlas patch margin, it would alias at city
distance.

The prediction was never rendered. It is now.

| file | what it shows |
|---|---|
| `brick_detail_close.png` | 1:1 crops, 8 m out, golem eye height — 6 / 9 / 13 courses/m |
| `brick_detail_play.png` | 1:1 crops, 26 m out at 6 m eye — Demigol's own preview camera, 60° vertical FOV |
| `brick_recede_detail.png` | a 78 m brick wall at a grazing angle, the worst case for moiré |
| `brick_control_mip.png` | **the positive control** |
| `brick_pitch_close.png`, `brick_pitch_play.png` | the full frames the crops come from, with a 1.8 m human and a 4.5 m golem in shot for scale |

**The receding wall shows no moiré at 13 courses/m** — anywhere along the sweep, from near-1:1
texel density down to the vanishing point.

**And the control proves the test could have shown it.** A 1-px checker was written into the same
brick patch and rendered from the same camera under the same filtering. Unfiltered it tears into
violent moiré across the whole wall; with Maya's filtering restored it collapses to smooth grey:

```
                near ------------------------------> far
filterOFF  hf:  93.61   74.73   36.29   36.40   49.90   17.00
filterON   hf:  11.15    9.96    3.34    1.19    1.25    1.17
```

The A/B above ran under `filterOFF`. The aliasing condition was genuinely reproduced, and real
brick survived it.

## What 6 courses/m costs

A 167 mm course is twice a real brick. In `brick_detail_close.png` and `brick_detail_play.png`
the shipped wall reads as **large-format blockwork, not brick** — and because the courses stay
individually resolvable much further out, at play distance they read as **horizontal striping**
rather than as material. The finer pitch is the one that stops reading as a pattern and starts
reading as a surface.

## DECIDED: 13 courses/m — real brick

**User's call, 2026-08-21**, shown `the_choice_close.png` / `the_choice_play.png` — the shipped
9 courses/m against the 13 alternative, same camera, one decision.

An intermediate **9** was delivered first and overruled. Its argument was that 9 put the mortar
bed at 2.0 px, exactly on the pinned floor, and so required no assumption about anything
unmeasured. 13 puts the bed at 1.4 px and looks like brick.

**The open risk is not aliasing — that was tested here and survived.** It is that every render
in this folder came from Maya's rasteriser, while Demigol samples the same atlas through Unity
with **BC block compression**, where a 1.4 px dark line is exactly the feature a block codec
smears. That measurement can only be taken on the Unity side and is flagged on #652. If brick
reads mushy in Unity and crisp in these images, that is the first thing to check.

The generator's old `>= 2 px` mortar-bed floor was **retired, not lowered** — see
`tests/test_demigol_generators.py`. Its premise was the claim these renders disproved.

## Method note

Maya's viewport clamps textures to 2048 by default
(`hardwareRenderingGlobals.enableTextureMaxRes`). Every capture here was taken with the clamp
**off**, because judging a 4096 atlas through a 2048 downsample is the same defect Demigol just
fixed in #630 — measuring the instrument instead of the art.
