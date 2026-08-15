# setup_lighting π-normalisation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `setup_lighting`'s `intensity` a unit — `1.0` means a surface facing the key reads its own albedo — instead of an arbitrary dial that every caller has been guessing at.

**Architecture:** One factor (π) applied where directional lights are created in `maya_plugin/handlers/lighting.py`, and nowhere else. Arnold's distant light returns `albedo / π` at intensity 1.0; VP2 does the same, measured; a sky dome does not, because hemisphere integration already carries the π. The callers then split in two: gate scripts get a mechanical `/π` that reproduces today's pixels exactly, and the two demigol art scripts get re-judged by eye, because their numbers were compensating for the #615 gamma bug as well as for this.

**Tech Stack:** Python 3, `maya.cmds`, pytest, `uv`.

Spec: `docs/superpowers/specs/2026-08-15-lighting-pi-normalisation-design.md`.
Redmine: **#617** (this work), **#615** (the display transform that exposed it), **#600** (the art revision).

## Global Constraints

- Tests run with `uv run python -m pytest`. Plain `python -m pytest` fails with `ModuleNotFoundError: maya_mcp`.
- Baseline to hold: **713 passed, 1 skipped**. No existing test may regress.
- Live gate runs on port **9877** (the user's Maya): `MAYA_MCP_PORT=9877`. 9878 is not listening.
- **Deploy before any live check:** `uv run python maya_plugin/install.py --yes`, then hot-patch the running plugin (Task 3 Step 3 gives the exact code). Live Maya loads from `Documents/maya/scripts`, so an un-deployed edit tests the OLD code and passes for the wrong reason.
- Leave the user's scene as found. Every light intensity parked, every node created, must be restored or deleted in a `finally`.
- `setup_lighting` calls in eval scripts must pass `replace_existing=False` when the script did not already pass `True` — `True` deletes user-authored lights and burns a checkpoint.
- The real `aiSkyDomeLight` must NOT receive the factor. Only directional lights.

---

## Measured facts this plan rests on

Established live on 9877, 2026-08-15, with the #615 calibration plane (`standardSurface`, `baseColor` linear 0.5, `base` 1.0, `specular` 0.0, N·L = 1, all other lights parked at 0). Re-verify only if something contradicts them.

| Fact | Value |
|---|---|
| Arnold, `render_scene`, hand-built light at intensity π | **188** — fully lit |
| VP2, `capture_viewport` with `lighting="scene"`, intensity 1/π / 1.0 / π | 32 / 83 / **165** |
| `capture_viewport` default `lighting` | `"default"` (headlight) — scene lights do nothing without `lighting="scene"` |
| `environment` dome at intensity 1.0 | ~(122,110,107); a π-divided dome would be ~88 |
| `_THREE_POINT` factors | key 1.0, fill 0.35, rim 0.7 |
| `_SINGLE_SUN` | one light, factor 1.0, rotation `[-45, 25, 0]` |

---

## File Structure

- `maya_plugin/handlers/lighting.py` — **modify.** The factor lands here, at the two places a directional light is created (`_build` line 118, `_build_dome`'s no-Arnold fallback line 270). The dome's own `setAttr` at line 298 is left alone.
- `src/maya_mcp/server.py` — **modify.** Line 1566-1568: `intensity`'s description currently reads `"Overall rig intensity; 1.0 is neutral."`, which was never true. It states the unit instead.
- `tests/test_lighting.py` — **modify.** Headless proof that the multiplication happens where it should and nowhere else.
- Eight eval scripts — **modify.** Mechanical `/π`, listed with exact line numbers in Task 2.
- `evals/render_calibration_live.py` — **modify.** A second measurement, through `setup_lighting` rather than a hand-built light. This is the only check that can catch the factor being applied in the wrong place.
- `evals/demigol_kit.py`, `evals/demigol_structures.py` — **modify.** Re-judged, not divided (Task 4).

---

### Task 1: The factor, and the unit it creates

**Files:**
- Modify: `maya_plugin/handlers/lighting.py` (add a constant near line 48; `_build` line 118; `_build_dome` line 270)
- Modify: `src/maya_mcp/server.py:1566-1568`
- Test: `tests/test_lighting.py` (append to the existing file)

**Interfaces:**
- Produces: `lighting.FULLY_LIT` — the float multiplier applied to every directional light's intensity. Task 3's live gate refers to the behaviour, not the constant.
- No signature change. `setup_lighting`'s params and response shape are untouched.

- [x] **Step 1: Write the failing tests**

Append to `tests/test_lighting.py`. The existing `FakeCmds.directionalLight` records `("directionalLight", name, intensity)` in `fake.created`, and `setAttr` stores its value as a tuple in `fake.attrs` — both are used below.

```python
class TestFullyLitUnit:
    """#617: intensity 1.0 must mean a surface facing the key reads its own
    albedo. Arnold's distant light returns albedo/pi at 1.0, and VP2 does the
    same (both measured live), so the tool carries the pi and the caller states
    a picture instead of guessing a number.
    """

    def _built(self, fake):
        """(name, intensity) for every directional light the call created.

        FakeCmds.directionalLight records ("directionalLight", name, intensity);
        createNode records a 2-tuple, hence the star-unpack.
        """
        return [(name, rest[0]) for kind, name, *rest in fake.created
                if kind == "directionalLight"]

    def test_a_single_sun_at_one_is_a_fully_lit_surface(self, monkeypatch):
        fake = FakeCmds()
        monkeypatch.setattr(lighting, "_cmds", lambda: fake)
        monkeypatch.setattr(lighting, "_auto_checkpoint", lambda reason: None)
        lighting.setup_lighting({"preset": "single_sun", "intensity": 1.0,
                                 "replace_existing": False})
        assert self._built(fake)[0][1] == pytest.approx(math.pi)

    def test_the_key_carries_the_factor_and_the_ratios_are_unchanged(self, monkeypatch):
        fake = FakeCmds()
        monkeypatch.setattr(lighting, "_cmds", lambda: fake)
        monkeypatch.setattr(lighting, "_auto_checkpoint", lambda reason: None)
        lighting.setup_lighting({"preset": "three_point", "intensity": 2.0,
                                 "replace_existing": False})
        built = [i for _, i in self._built(fake)]
        assert built[0] == pytest.approx(2.0 * math.pi)
        # only the UNIT moves: key/fill/rim keep the rig's shape
        assert built[1] / built[0] == pytest.approx(0.35)
        assert built[2] / built[0] == pytest.approx(0.7)

    def test_the_dome_does_not_get_the_factor(self, monkeypatch):
        # A hemisphere of uniform luminance already integrates to albedo * L.
        # Measured: environment at 1.0 lights the plane to ~122, where a
        # pi-divided dome would be ~88.
        fake = FakeCmds()
        monkeypatch.setattr(lighting, "_cmds", lambda: fake)
        monkeypatch.setattr(lighting, "_auto_checkpoint", lambda reason: None)
        monkeypatch.setattr(lighting, "_arnold_available", lambda cmds: True)
        result = lighting.setup_lighting({"preset": "environment", "intensity": 1.0,
                                          "replace_existing": False})
        dome = result["lights"][0]
        intensity = [v for a, v in fake.attrs.items()
                     if a.startswith(dome) and a.endswith(".intensity")]
        assert intensity and intensity[0] == (1.0,)

    def test_the_no_arnold_fallback_matches_the_dome_it_stands_in_for(self, monkeypatch):
        # Without the factor a Maya lacking mtoa renders three times darker
        # than one that has it, for the same call - a silent difference.
        fake = FakeCmds()
        monkeypatch.setattr(lighting, "_cmds", lambda: fake)
        monkeypatch.setattr(lighting, "_auto_checkpoint", lambda reason: None)
        monkeypatch.setattr(lighting, "_arnold_available", lambda cmds: False)
        lighting.setup_lighting({"preset": "environment", "intensity": 1.0,
                                 "replace_existing": False})
        assert self._built(fake)[0][1] == pytest.approx(math.pi)
```

Add `import math` to the top of `tests/test_lighting.py` if it is not already there.

- [x] **Step 2: Run them and watch them fail**

Run: `uv run python -m pytest tests/test_lighting.py -v -k FullyLit`
Expected: FAIL — three of the four assert π and get 1.0. `test_the_dome_does_not_get_the_factor` passes already; that is correct, it is the guard that the factor stays out of the dome.

- [x] **Step 3: Add the constant**

In `maya_plugin/handlers/lighting.py`, after the `_SINGLE_SUN` definition (line 48), add:

```python
# Arnold's distant light spreads its energy over the hemisphere the surface can
# see, so a lambert facing it at intensity 1.0 returns albedo/pi, not albedo.
# VP2 does the same - both measured on a linear-0.5 plane at N.L = 1, which
# reads its own albedo only at intensity pi (redmine #617).
#
# Carrying the factor here makes `intensity` a UNIT: 1.0 is a fully-lit
# surface, 0.5 is visibly dim, 2.0 is deliberately hot. Before this, "1.0"
# delivered 32% of a lit surface and named nothing, so every caller dialled in
# its own number by eye - 1.2, 1.5, 2.1, 3.0, 3.2, 4.0, 16.0 across the evals,
# no two agreeing, each also compensating for the #615 gamma bug.
#
# A sky dome does NOT get this: a hemisphere of uniform luminance already
# integrates to albedo * L. Measured, environment at 1.0 lights the plane to
# ~122 where a pi-divided dome would be ~88.
FULLY_LIT = math.pi
```

Add `import math` to the imports at the top of the file (after `from __future__ import annotations`, with the other stdlib imports).

- [x] **Step 4: Apply it in `_build`**

`maya_plugin/handlers/lighting.py` line 118, inside `_build`:

```python
            shape = cmds.directionalLight(
                name=name, intensity=intensity * factor * FULLY_LIT)
```

- [x] **Step 5: Apply it to the no-Arnold dome fallback**

`maya_plugin/handlers/lighting.py` line 270, inside `_build_dome`:

```python
            shape = cmds.directionalLight(
                name=name, intensity=intensity * FULLY_LIT)
```

Leave line 298 — `cmds.setAttr(shape + ".intensity", intensity)` on the real `aiSkyDomeLight` — exactly as it is.

- [x] **Step 6: Run the tests and watch them pass**

Run: `uv run python -m pytest tests/test_lighting.py -v`
Expected: PASS, including the four new ones.

- [x] **Step 7: State the unit on the tool surface**

`src/maya_mcp/server.py` lines 1566-1568. Replace:

```python
        intensity: Annotated[float, Field(gt=0, le=20, description=(
            "Overall rig intensity; 1.0 is neutral."
        ))] = 1.0,
```

with:

```python
        intensity: Annotated[float, Field(gt=0, le=20, description=(
            "Rig intensity, in fully-lit surfaces. 1.0 means a surface facing "
            "the key reads its OWN albedo - a light grey wall renders light "
            "grey. 0.5 is visibly dim, 2.0 deliberately hot. The key/fill/rim "
            "ratio is fixed; this scales the whole rig."
        ))] = 1.0,
```

- [x] **Step 8: Run the whole suite**

Run: `uv run python -m pytest`
Expected: **717 passed, 1 skipped**. Any other failure is a regression — stop and fix.

- [x] **Step 9: Commit**

```bash
git add maya_plugin/handlers/lighting.py src/maya_mcp/server.py tests/test_lighting.py
git commit -m "feat(lighting): intensity 1.0 now means a fully-lit surface"
```

---

### Task 2: The gates, divided

Mechanical `/π` for every script whose intensity was tuned for a look that must not change. Dividing reproduces today's pixels exactly, so no gate's assertion changes meaning. This is a rename, not a re-tune.

**Files:**
- Modify: `evals/array_deform_live.py:259, 313, 409` — `3.0` → `0.9549`
- Modify: `evals/brute_v6.py:224` — `3.0` → `0.9549`
- Modify: `evals/brute_v7.py:305` — `3.0` → `0.9549`
- Modify: `evals/gem_brute_v5.py:157` — `7.0` → `2.2282`
- Modify: `evals/gem_brute_v5.py:232` — `4.0` → `1.2732`
- Modify: `evals/lookdev_controls_live.py:78` — `4.0` → `1.2732`
- Modify: `evals/lookdev_controls_live.py:139` — `16.0` → `5.0930`
- Modify: `evals/m2_judged_run.py:71` — `1.2` → `0.3820`
- Modify: `evals/rotunda.py:226` — `2.1` → `0.6685`
- Modify: `evals/structures.py:365` — `2.1` → `0.6685`

**Interfaces:**
- Consumes: Task 1's `FULLY_LIT`, indirectly — these numbers are only correct once the handler carries the factor.
- Produces: nothing. No other task depends on these files.

- [x] **Step 1: Change every number**

Each is a literal in a `setup_lighting` params dict of the form `"intensity": 3.0,`. Change only the number. Do not touch `preset` or `replace_existing`.

The divisions, for checking: `1.2/π = 0.3820`, `2.1/π = 0.6685`, `3.0/π = 0.9549`, `4.0/π = 1.2732`, `7.0/π = 2.2282`, `16.0/π = 5.0930`.

- [x] **Step 2: Add the one-line reason where the number now looks odd**

A bare `0.9549` invites someone to "tidy" it back to 1.0. Above each changed call, add:

```python
    # 3.0/pi: the pre-#617 number, in the new unit - same pixels as before
```

with that script's own old value.

- [x] **Step 3: Verify nothing else moved**

Run: `git diff --stat evals/`
Expected: ten files, and every changed line is either an intensity literal or the comment above it. No logic, no assertions.

- [x] **Step 4: Run the headless suite**

Run: `uv run python -m pytest`
Expected: **717 passed, 1 skipped**. These are eval scripts, not tests, so the count should not move — this step is confirming you did not edit a file that pytest imports.

- [x] **Step 5: Commit**

```bash
git add evals/
git commit -m "test(evals): the gates' intensities, restated in the new unit"
```

---

### Task 3: The live gate

Headless tests prove the multiplication happened. They cannot prove it happened in the right place, or that the resulting picture is correct — the whole of #615 existed while the suite was green.

**Files:**
- Modify: `evals/render_calibration_live.py`

**Interfaces:**
- Consumes: Task 1's behaviour, through `setup_lighting`.
- Produces: a second exit-code check in the same script.

- [x] **Step 1: Add the second measurement**

The existing check builds its own light at intensity π and asserts 188. Keep it exactly as it is — it does not go through `setup_lighting`, so it is unaffected by this change and makes a useful control.

Add a second check that goes *through* the preset. Insert after the existing measurement, inside the same `try`:

```python
PRESET_SETUP = """
import maya.cmds as cmds
# The hand-built control light, off. Derived rather than spelled
# "calibLightShape": cmds.directionalLight names the TRANSFORM, and the shape
# suffix is Maya's to choose.
for shape in (cmds.listRelatives("calibLight", shapes=True, fullPath=True) or []):
    cmds.setAttr(shape + ".intensity", 0.0)
"""

PRESET_AIM = """
import maya.cmds as cmds
# Aim the preset's sun straight down at the plane so N.L = 1. Its ROTATION is
# not what #617 changed - its intensity is - so pointing it is fair, and it is
# the only way to compare against a known analytic value.
cmds.xform(%r, rotation=(-90, 0, 0), worldSpace=True)
"""
```

and in `main()`, after the first `measured = lit_value(png)`:

```python
        send("execute_python", {"code": PRESET_SETUP})
        rig = send("setup_lighting", {"preset": "single_sun", "intensity": 1.0,
                                      "replace_existing": False})
        created = rig["lights"]
        send("execute_python", {"code": PRESET_AIM % created[0]})
        result = send("render_scene", {
            "isolate": ["calibPlane"], "angles": ["top"], "relight": False,
            "fallback_light": False, "resolution": 256, "samples": 3,
        })
        preset_measured = lit_value(base64.b64decode(result["images"][0]["png_b64"]))
```

`created` must be deleted in the existing `finally`, before the lights are restored:

```python
        send("execute_python", {"code":
             "import maya.cmds as cmds\n"
             "for node in %r:\n"
             "    if cmds.objExists(node):\n"
             "        cmds.delete(node)\n" % (created,)})
```

Initialise `created = []` before the `try` so the `finally` cannot raise on a failure that happened earlier.

- [x] **Step 2: Report and gate on it**

Replace the single print/return block at the end of `main()` with both numbers:

```python
    print("calibration: hand-built light at pi -> %d, setup_lighting(single_sun, "
          "1.0) -> %d, expected %d +/- %d  (%d lights parked and restored)"
          % (measured, preset_measured, EXPECTED, TOLERANCE, len(saved)))
    if abs(measured - EXPECTED) > TOLERANCE:
        print("FAIL: a linear-0.5 surface at N.L = 1 must leave as %d. %d is "
              "the RAW LINEAR value - render_scene is returning undisplayable "
              "pixels again (redmine #615)." % (EXPECTED, measured))
        return 1
    if abs(preset_measured - EXPECTED) > TOLERANCE:
        print("FAIL: setup_lighting(intensity=1.0) must light a surface to its "
              "OWN albedo, which is %d here. %d means the pi is missing, in the "
              "wrong place, or applied twice (redmine #617)." 
              % (EXPECTED, preset_measured))
        return 1
    print("PASS: displayable pixels, and intensity 1.0 is a fully-lit surface")
    return 0
```

- [x] **Step 3: Deploy and hot-patch the live plugin**

```bash
uv run python maya_plugin/install.py --yes
```

Then reload the running plugin — the deployed copy is what Maya imports, and a reload of the module alone does not rebuild the dispatcher's handler table:

```python
import importlib
import maya_plugin.handlers.lighting as L
importlib.reload(L)
import maya_mcp_plugin as P
P._active_server._dispatcher._handlers = P._build_handlers()
```

Send that through `execute_python` on port 9877, then confirm the live module has the new code:

```python
import maya_plugin.handlers.lighting as L
getattr(L, "FULLY_LIT", None)
```

Expected: `3.141592653589793`.

- [x] **Step 4: Run the gate**

```bash
MAYA_MCP_PORT=9877 uv run python evals/render_calibration_live.py
```

Expected: `calibration: hand-built light at pi -> 187, setup_lighting(single_sun, 1.0) -> 187, expected 188 +/- 3` then `PASS`.

If the second number comes back near **60**, the factor was applied to the dome path or divided rather than multiplied. If it comes back near **255**, it was applied twice.

- [x] **Step 5: Commit**

```bash
git add evals/render_calibration_live.py
git commit -m "test(render): the live gate measures the unit, not just the gamma"
```

---

### Task 4: The two art scripts, re-judged

`demigol_kit.py` (3.2) and `demigol_structures.py` (1.5) are the delivery. Their numbers were dialled in against images suffering BOTH faults, so dividing by π would preserve a look that was never judged honestly. They get a number chosen in the new unit and confirmed by eye.

**Files:**
- Modify: `evals/demigol_structures.py:893`
- Modify: `evals/demigol_kit.py:936`

**Interfaces:**
- Consumes: Task 1's unit, Task 3's confirmation that the unit is real.
- Produces: the renders the revision-3 regeneration pass will judge.

- [x] **Step 1: Set both to the new unit**

`evals/demigol_structures.py:893` and `evals/demigol_kit.py:936`: `"intensity": 1.0`.

Above each, replace any existing tuning comment with:

```python
    # 1.0 = a surface facing the key reads its own albedo (#617). The old 1.5
    # was dialled in against images that were also 2.2 gamma too dark (#615),
    # so it is not a number worth converting - only re-judging.
```

using that script's own old value.

- [x] **Step 2: Re-render the hero and read the number**

```bash
MAYA_MCP_PORT=9877 uv run python evals/demigol_structures.py stump
```

Expected: `stump OK 166 chunks (110 frame) 12960 tris`, and the roof deck's modal lit value now near its albedo of (158,156,148) rather than the 102 it reads today. Measure it rather than eyeballing:

```python
from PIL import Image
im = Image.open("evals/demigol_structures/stump.png").convert("RGB")
sorted((c for c in im.getcolors(maxcolors=im.width*im.height) if sum(c[1]) > 30),
       reverse=True)[:3]
```

- [x] **Step 3: Judge it by eye**

Open `evals/demigol_structures/stump.png`. The deck should read as light grey concrete. If it is now blown out — large flat areas at 250+ — the key is too hot for a scene with three lights adding up; drop to 0.7 and re-render. Record whichever number you land on and why, in the comment from Step 1.

- [x] **Step 4: Commit**

```bash
git add evals/demigol_kit.py evals/demigol_structures.py evals/demigol_structures/
git commit -m "feat(assets): light the delivery in the new unit, and mean it"
```

- [x] **Step 5: Close the ticket**

Update #617 to Resolved with the before/after numbers from Task 3 Step 4 and Task 4 Step 2, and the intensity each art script landed on.

---

## Explicitly out of scope

- **#618 — isolate hides the sky dome.** `cmds.ls(geometry=True)` reports `aiSkyDomeLight` shapes as geometry, so `render_scene(isolate=[...])` under a dome returns a black frame. Found while measuring for this; a different defect in a different handler. It is cheap and it is on the path to judging item 7's metals, so it is a reasonable thing to bundle into the same live session — but it is not this plan.
- **The VP2/render tone mismatch.** Captures encode through the scene's ACES view transform (0.5 → 165), renders through un-tone-mapped (0.5 → 188). Same asset, two looks. Worth a ticket.
- **Regenerating the kit and the other three heroes.** That is the revision-3 delivery pass. Task 4 re-renders `stump` only, as the judgement sample.

## Verification

```bash
uv run python -m pytest
```

```bash
MAYA_MCP_PORT=9877 uv run python evals/render_calibration_live.py
```

The second is the one that matters. A green suite proved nothing about #615, and it proves nothing about the unit either — only a rendered surface reading its own albedo does.
