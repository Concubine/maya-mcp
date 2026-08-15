# render_scene display transform — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `render_scene` return a *displayable* image instead of raw linear pixels, so an asset's colour and value can be judged from a render.

**Architecture:** The defect and the fix both live in `maya_plugin/handlers/render.py`. A calibration helper renders a surface of known albedo under a known light and asserts the returned 8-bit value, which turns "does the image look right" into a number. Task 1 is a time-boxed spike that establishes *how* to reach Path A, not *whether* to take it. The fix must be **plugin-side**, not MCP-server-side, because the eval scripts talk to the plugin directly over TCP (`evals/live_call.py`) and never pass through the server.

**Path A — having Arnold apply the transform in float — is the committed target, chosen for durability and image quality rather than cost.** Task 2 exists only for the case where Path A proves impossible on this mtoa version, and taking it requires saying so on #615.

**Tech Stack:** Python 3, `maya.cmds`, `maya.api.OpenMaya.MImage`, pytest, `uv`.

Redmine: **#615** (this work), **#600** (the art revision that surfaced it).

## Global Constraints

- Tests run with `uv run python -m pytest`. Plain `python -m pytest` fails with `ModuleNotFoundError: maya_mcp`.
- Baseline to hold: **703 passed, 1 skipped**. No existing test may regress.
- **Pillow is NOT importable inside Maya.** `numpy` is (2.3.5) but must not become a hard dependency of the plugin — Maya versions differ. Any pixel work uses a 256-entry byte LUT via `bytes.translate`, which needs neither.
- The deployed plugin at `Documents/maya/scripts/maya_plugin` goes stale against the repo. Sync before trusting any live check.
- Live gate runs on port **9877** (the user's Maya): `MAYA_MCP_PORT=9877`. 9878 is not listening.
- Leave the user's scene as found: any colour-management or driver attribute the handler changes must be restored in a `finally`, following the existing `_RenderGlobalsState` pattern in `render.py`.
- Do not change `setup_lighting` preset intensities in this plan. The π-normalisation question is real but separate; note it on #615 and leave it.

---

## Measured facts this plan rests on

Established live on 2026-08-15; re-verify only if something contradicts them.

| Fact | Value |
|---|---|
| Calibration: linear-0.5 plane, N·L=1, light intensity 1.0 | renders **~42** (raw linear predicts 41; sRGB predicts 188) |
| Same plane, light intensity π | renders **~128** (raw linear predicts 128) |
| `defaultArnoldDriver.colorManagement` | enum `Raw : Use View Transform : Use Output Transform`, set to **2** |
| `colorManagementPrefs -outputTransformEnabled` | **False** — so mode 2 silently degrades to Raw |
| Render call used | `cmds.render(camera, x, y)` at `render.py:229` — the interactive render-view path |
| Setting `colorManagement` to 1 and re-rendering | **no effect** (`mean_luma` stayed 6.7) |
| `PIL` in Maya | **absent**. `numpy` present, 2.3.5 |
| Scene colour management | `cmEnabled: True`, rendering space ACEScg, view `ACES 1.0 SDR-video (sRGB)` |
| Available view transforms | `ACES 1.0 SDR-video (sRGB)`, `Un-tone-mapped (sRGB)`, `Unity neutral tone-map (sRGB)`, `Log (sRGB)`, `Raw (sRGB)` |

---

## File Structure

- `maya_plugin/handlers/render.py` — where the fix lands. Already owns `_render_frame` and the globals save/restore, so the display transform belongs here rather than in a new module.
- `maya_plugin/handlers/display_transform.py` — **new.** The LUT builder and its application. Pure functions over bytes, no Maya import, so it is unit-testable headlessly. Only created if Task 1 selects Path B.
- `tests/test_display_transform.py` — **new.** Headless unit tests for the LUT.
- `evals/render_calibration_live.py` — **new.** The live gate: builds the calibration plane, renders, asserts the 8-bit value. This is the test that actually proves the fix, per "the live gate IS the gate".

---

### Task 1: Spike — decide the fix path (TIME-BOXED, 30 minutes)

No production code. The question: can Arnold be made to apply the display transform itself, or must the handler post-correct the pixels?

**Files:**
- Scratch only. Nothing committed except the decision, recorded on #615.

- [ ] **Step 1: Establish the calibration harness by hand, live**

Run against port 9877. Build the probe in the live scene:

```python
import maya.cmds as cmds, math
saved = {}
for sh in (cmds.ls(type="directionalLight", long=True) or []):
    saved[sh] = cmds.getAttr(sh + ".intensity")
    cmds.setAttr(sh + ".intensity", 0.0)
probe = cmds.directionalLight(name="calibLight", intensity=math.pi)
lt = cmds.listRelatives(probe, parent=True, fullPath=True)[0]
cmds.xform(lt, rotation=(-90, 0, 0), worldSpace=True)
pl = cmds.polyPlane(name="calibPlane", width=20, height=20, sx=1, sy=1)[0]
cmds.xform(pl, translation=(120, 20, 0), worldSpace=True)
m = cmds.shadingNode("standardSurface", asShader=True, name="calibMat")
cmds.setAttr(m + ".baseColor", 0.5, 0.5, 0.5, type="double3")
cmds.setAttr(m + ".base", 1.0)
cmds.setAttr(m + ".specular", 0.0)
sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=m + "SG")
cmds.connectAttr(m + ".outColor", sg + ".surfaceShader", force=True)
cmds.sets(pl, edit=True, forceElement=sg)
```

Render it with `isolate=["calibPlane"]`, `angles=["top"]`, `relight=False`, `fallback_light=False`.
Expected NOW: **~128**. Target after the fix: **~188**.

- [ ] **Step 2: Probe Path A — make Arnold apply the transform**

Try each, re-rendering the probe after each and recording the value:

```python
import mtoa.core; mtoa.core.createOptions()      # defaultArnoldDriver must exist first
cmds.setAttr("defaultArnoldDriver.colorManagement", 1)   # Use View Transform
cmds.colorManagementPrefs(edit=True, viewTransformName="Un-tone-mapped (sRGB)")
```
then, separately:
```python
cmds.setAttr("defaultArnoldDriver.colorManagement", 2)   # Use Output Transform
cmds.colorManagementPrefs(edit=True, outputTransformEnabled=True,
                          outputTransformName="Un-tone-mapped (sRGB)")
```
then, if both fail, swap the render call for mtoa's own:
```python
cmds.arnoldRender(camera=cam, width=res, height=res, batch=True)
```

**Known already:** `colorManagement=1` alone did NOT work via `cmds.render`. The open question is whether `arnoldRender` honours it. That is the single most valuable thing this spike answers.

- [ ] **Step 3: Decide and record**

**Path A is the committed target. Hours are not the tie-breaker — durability and image quality are (user's call, 2026-08-15).**

- **Path A — Arnold applies the transform.** The conversion happens in float *inside* Arnold, before the result is quantised to 8 bits, so there is no banding. It also reads the scene's colour management, which means it stays correct if the OCIO config or rendering space changes later. This is both the more durable and the better-looking answer.
- **Escalate within Path A rather than falling back.** If the driver attribute alone will not do it, changing the arnold render call from `cmds.render` to `cmds.arnoldRender` is in scope for this plan. Keep `cmds.render` for `hw2` and branch on renderer; the existing comment at `render.py:215` explains why `cmds.render` was chosen, and that reasoning only ever applied to picking up `currentRenderer`, not to colour management.
- **Path B is a documented compromise, not a fallback of convenience.** Take it only if Path A is demonstrably impossible on this mtoa version. It post-corrects data that is *already* 8-bit linear, so shadow detail lost to quantisation cannot be recovered and gradients will band. The manual correction of `stump.png` retained 2,769 distinct colours, which is tolerable but strictly worse. If Path B is taken, say so on #615 and open a follow-up to revisit Path A.

**Rejected as less durable, not more:** rendering to float EXR and applying the transform ourselves. It sounds like the most controllable option, but it adds an EXR decode/encode stage, a per-pixel pass that is either slow in pure Python or dependent on Maya's numpy, and a second place for the transform to be wrong — more machinery for the same visual result Path A gives for free.

Post the outcome and the measured numbers to #615. Then delete the probe and restore the lights.

- [ ] **Step 4: Commit the decision**

```bash
git commit --allow-empty -m "spike(render): decide display-transform path for #615"
```

---

### Task 2 (Path B only): The LUT, headless

Skip entirely if Task 1 selected Path A.

**Files:**
- Create: `maya_plugin/handlers/display_transform.py`
- Test: `tests/test_display_transform.py`

**Interfaces:**
- Produces: `srgb_lut() -> bytes` (256 entries) and `encode_png_bytes(png: bytes) -> bytes`.
- Consumed by: Task 3's `_render_frame`.

- [ ] **Step 1: Write the failing test**

```python
from maya_plugin.handlers import display_transform as dt


class TestSrgbLut:
    def test_it_has_one_entry_per_byte(self):
        assert len(dt.srgb_lut()) == 256

    def test_black_and_white_are_fixed_points(self):
        lut = dt.srgb_lut()
        assert lut[0] == 0
        assert lut[255] == 255

    def test_linear_half_becomes_srgb_half(self):
        # the calibration case: linear 0.5 must leave as 188, not 128
        assert abs(dt.srgb_lut()[128] - 188) <= 1

    def test_it_never_darkens(self):
        lut = dt.srgb_lut()
        assert all(lut[i] >= i for i in range(256))

    def test_it_is_monotonic(self):
        lut = dt.srgb_lut()
        assert all(lut[i] <= lut[i + 1] for i in range(255))
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run python -m pytest tests/test_display_transform.py -v`
Expected: FAIL, `ModuleNotFoundError: maya_plugin.handlers.display_transform`

- [ ] **Step 3: Implement**

```python
"""The sRGB transfer function as a byte LUT (redmine #615).

Arnold hands back RAW LINEAR pixels: a surface of linear albedo 0.5 lit to
N.L = 1 arrives as 128 where a displayable image wants 188. Every render this
tool ever returned was ~2.2 gamma too dark, and the art it was used to judge
was judged wrong.

A 256-entry LUT rather than numpy, because Maya ships no Pillow and its numpy
is not guaranteed across versions - and because the data is already 8-bit, so a
LUT is not an approximation of the per-pixel maths, it IS the per-pixel maths.
"""

from __future__ import annotations

_LUT: bytes | None = None


def srgb_lut() -> bytes:
    """Linear byte -> sRGB-encoded byte, memoised."""
    global _LUT
    if _LUT is None:
        out = bytearray(256)
        for i in range(256):
            c = i / 255.0
            s = c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055
            out[i] = min(255, max(0, round(s * 255.0)))
        _LUT = bytes(out)
    return _LUT
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `uv run python -m pytest tests/test_display_transform.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/display_transform.py tests/test_display_transform.py
git commit -m "feat(render): the sRGB transfer function, as a byte LUT"
```

---

### Task 3: Apply it in the handler

**Files:**
- Modify: `maya_plugin/handlers/render.py` (`_render_frame`, around lines 209–235)
- Test: `tests/test_render_handler.py` (extend the existing file; find it first)

**Interfaces:**
- Consumes: Path A — the driver attribute names confirmed by Task 1. Path B — `display_transform.srgb_lut`.
- Produces: no signature change. `render_scene`'s response shape is untouched, so no caller changes.

- [ ] **Step 1: Write the failing test**

Path A — assert the handler sets and restores the attributes, using the existing fake-`cmds` pattern already in the render tests:

```python
def test_it_sets_the_display_transform_for_the_render(fake_cmds):
    render._render_frame(fake_cmds, "cam", "p", "arnold", 256, 3)
    assert fake_cmds.set_attrs["defaultArnoldDriver.colorManagement"] == 1


def test_it_restores_the_driver_setting_afterwards(fake_cmds):
    fake_cmds.attrs["defaultArnoldDriver.colorManagement"] = 2
    render._render_frame(fake_cmds, "cam", "p", "arnold", 256, 3)
    assert fake_cmds.attrs["defaultArnoldDriver.colorManagement"] == 2
```

Path B — assert the returned bytes are brightened:

```python
def test_it_encodes_the_frame_for_display(tmp_path, fake_cmds):
    raw = _png_of_solid_grey(128)          # helper: write a 1-colour PNG
    ...
    assert _dominant_value(result) == pytest.approx(188, abs=2)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run python -m pytest tests/test_render_handler.py -v -k display`
Expected: FAIL.

- [ ] **Step 3: Implement the selected path**

**Path A** — inside `_render_frame`, guarded to `renderer == "arnold"`, wrapped so a Maya without mtoa degrades rather than raises:

```python
    restore = None
    if renderer == "arnold":
        try:
            import mtoa.core
            mtoa.core.createOptions()
            attr = "defaultArnoldDriver.colorManagement"
            restore = (attr, cmds.getAttr(attr))
            cmds.setAttr(attr, 1)          # Use View Transform
        except Exception:
            restore = None                 # no mtoa: the frame is raw, as before
    try:
        written = cmds.render(camera, x=resolution, y=resolution)
    finally:
        if restore is not None:
            cmds.setAttr(restore[0], restore[1])
```

**Path B** — after the file is read at `render.py:588`, before base64:

```python
    png = _apply_display_transform(png)
```
with `_apply_display_transform` decoding the PNG's IDAT, applying `srgb_lut()` via
`bytes.translate`, and re-encoding. Use `maya.api.OpenMaya.MImage` for the decode/encode
(`MImage.readFromFile` / `.writeToFile(path, "png")`) so no Pillow is needed — operate on
the file in place before reading it, which avoids hand-rolling a PNG codec entirely.

- [ ] **Step 4: Run the tests and watch them pass**

Run: `uv run python -m pytest tests/test_render_handler.py -v`
Expected: PASS.

- [ ] **Step 5: Run the whole suite**

Run: `uv run python -m pytest`
Expected: **704+ passed, 1 skipped**. Any pre-existing failure is a regression — stop and fix.

- [ ] **Step 6: Commit**

```bash
git add maya_plugin/handlers/render.py tests/test_render_handler.py
git commit -m "fix(render): return a displayable image, not raw linear pixels"
```

---

### Task 4: The live gate

Headless tests cannot prove this. The whole defect existed *because* every headless test passed.

**Files:**
- Create: `evals/render_calibration_live.py`

- [ ] **Step 1: Write the gate**

It must: sync-check the deployed plugin, build the calibration probe from Task 1 Step 1, render it, print the measured 8-bit value against the expected, and exit non-zero on failure. Restore the lights and delete the probe in a `finally`. Follow the structure of the existing `evals/isolate_regression.py`.

Assertion: `abs(measured - 188) <= 3`.

- [ ] **Step 2: Deploy the plugin and run it**

```bash
MAYA_MCP_PORT=9877 uv run python evals/render_calibration_live.py
```
Expected: `calibration OK  measured 188  expected 188 +/- 3`

Remember to copy the changed plugin to `Documents/maya/scripts/maya_plugin` first, or the gate tests the old code and passes for the wrong reason.

- [ ] **Step 3: Re-render the hero and confirm by eye**

```bash
MAYA_MCP_PORT=9877 uv run python evals/demigol_structures.py stump
```
Expected: `stump OK 166 chunks (110 frame) 12960 tris`, and `stump.png` now reads as light
grey concrete rather than near-black. Compare against `evals/demigol_structures/stump_srgb.png`,
the manually corrected reference produced while diagnosing this — they should broadly match.

- [ ] **Step 4: Commit**

```bash
git add evals/render_calibration_live.py
git commit -m "test(render): a live gate that measures the display transform"
```

- [ ] **Step 5: Close the ticket**

Update #615 to Resolved with the measured before/after numbers and the path taken. Add a
note to #600 that revision 2's renders were gamma-dark, so its colour findings — item 7
especially — should be re-judged against corrected images.

---

## Explicitly out of scope

- **`setup_lighting` π-normalisation.** Real, measured, noted on #615, but a look change with its own blast radius across every preset. Not here.
- **Which view transform is right for Demigol.** `Un-tone-mapped (sRGB)` matches URP with post-processing off, which is where they are today. `Unity neutral tone-map (sRGB)` exists and would match them if they enable post later. Pick un-tone-mapped now; revisit when their post stack lands.
- **Regenerating the kit and the other three heroes.** That belongs to the revision 3 delivery pass, not to this fix.
- **`capture_viewport`.** Unverified — it may have the same fault. Check it after this lands; do not widen scope now.

## Verification

```bash
uv run python -m pytest
```

```bash
MAYA_MCP_PORT=9877 uv run python evals/render_calibration_live.py
```

The second is the one that matters. A green suite proved nothing here the first time.
