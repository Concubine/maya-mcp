# The Golem Benchmark (acceptance eval — runs at M4)

Fresh Maya scene; the only instruction given to a fresh Claude session is the
prompt below.

## Prompt

> Model a golem from Jewish folklore in the open Maya scene: a heavy earthen
> humanoid — squat proportions, oversized forearms and shoulders, small head,
> hunched stance, feet rooted like broken earth. Give it a cracked dry-clay
> surface, carve or emboss the Hebrew word *emet* (אמת) on its forehead and
> make it glow faintly, light it with a three-point setup, and finish with an
> 8-frame turntable. Work iteratively: check your work visually after each
> significant change and correct proportions before adding detail.

## Hard pass criteria

- ≤ 120 tool calls
- One connected watertight body ≤ 50k tris (no floating/intersecting shells)
- Cracked-earth material with a noise→bump network
- Emissive rune on the forehead
- Three-point lighting
- Final 8-frame turntable contact sheet produced

## Rubric (human-scored 1–5, pass ≥ 3 each)

1. Proportion / silhouette readability at thumbnail size
2. Surface quality under SSAO
3. Presentation (lighting / material coherence)

Record tool-call count and wall time per run; keep the transcript as a
regression artifact.

## M0 interim eval — the snowman loop test

Until M1+ tools exist, the milestone gate is (design doc §7): using ONLY
`maya_execute_python`, `maya_get_scene_graph`, and `maya_capture_viewport`,
a fresh Claude session builds **a snowman with a carrot nose**, correcting
proportions from the screenshots it captures. Pass = recognizable snowman,
visibly iterated (at least one correction driven by a capture).
