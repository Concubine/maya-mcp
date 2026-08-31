# #775 Directed Surface Detail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `maya_apply_surface_detail` — wear on edges (curvature mask), grime in pockets (inverted-AO mask), grain relief (height→bump) — pixels composited into real map files that ship in the FBX.

**Architecture:** New handler pair `surfdetail.py` (Maya-facing) + `surfdetail_math.py` (pure pattern/composite math, headless-testable), reusing #770's `meshmaps` machinery: `plan_apply` for base-colour resolution, sRGB decode/encode, `.part.png` commit, `_rewire_color`, checkpoint + sweep + texclaim postcondition. Height relief wires `file → bump2d(bumpInterp=0) → shader.normalCamera` — pbr.py's measured idiom with the interp that means height.

**Tech Stack:** Python 2/3-compatible plugin code (matches handlers/), pytest headless + mayapy suites, live gate on agent Maya 9878.

**Spec:** `docs/superpowers/specs/2026-08-31-775-directed-detail-design.md`

## Global Constraints

- Two-Maya policy: 9877 is the USER's session — never `new_scene` it. Gates run on a disposable Maya launched on 9878 via `$env:MAYA_MCP_PORT='9878'; Start-Process 'E:\Autodesk\Maya2027\bin\maya.exe' -WindowStyle Minimized -WorkingDirectory 'D:\devel\maya-mcp' -PassThru` — the env var MUST be set before Start-Process in the same invocation, or the plugin defaults to 9877, finds it taken, and binds NOTHING (measured, Task 1: first launch sat listener-less with a PortInUseError only in its own log). Pid-verified with `netstat -ano | findstr 9878`, killed with `taskkill /F /T /PID <pid>`, port release verified.
- Suites measured with `--junitxml` (stdout buffering loses the summary line). Baselines: headless 1838 pass, mayapy 211 pass.
- Never touch `evals/golem_rerun_665/out_v4/` (another agent's in-flight work).
- Every refusal is a `HandlerError` with a `hint`; unknown params refused via `dispatcher.require_known_keys` with a synonym map (#764).
- Input files are never overwritten; new files commit via `.part.png` → `os.replace`.
- Image conversion never touches MImage (GUI Maya zeroes EXR alpha — measured #770). This tool reads/writes PNGs only via `pngprobe`/`pngwrite`, so the trap does not apply, but do not "improve" that.

---

### Task 1: Probes P1 (fbm perf) and P2 (bump-interp-0 export)

**Files:**
- Create: `evals/surfdetail_probe_775.py`

**Interfaces:**
- Consumes: `maya_plugin.handlers.sculpt_math.fbm(x, y, z, octaves)`, `evals/live_call.py`'s `call(command, params, timeout_s=...)`.
- Produces: measured numbers recorded in this plan (edit the Results block below), governing Task 2's pattern-generation strategy and Task 3's bump wiring.

- [ ] **Step 1: Write the probe script**

```python
"""#775 probes. P1 headless: python evals/surfdetail_probe_775.py p1
P2 live (agent Maya on 9878): set MAYA_MCP_PORT=9878 first, then
python evals/surfdetail_probe_775.py p2 -- MUTATES the answering scene."""
from __future__ import annotations
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from maya_plugin.handlers import sculpt_math

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "surfdetail_probe")

def p1():
    """fbm cost at 1024^2 and 256^2 - decides full-res vs upsample."""
    for size in (256, 1024):
        t0 = time.time()
        vals = [sculpt_math.fbm((i % size) / 64.0, (i // size) / 64.0, 0.0)
                for i in range(size * size)]
        dt = time.time() - t0
        print("P1 %dx%d: %.1fs (%d samples, min %.3f max %.3f)"
              % (size, size, dt, len(vals), min(vals), max(vals)), flush=True)

def p2():
    """file->bump2d(interp 0)->standardSurface: does the PNG ride the FBX?"""
    from live_call import call
    os.makedirs(OUT, exist_ok=True)
    height_png = os.path.join(OUT, "p2_height.png")
    from maya_plugin.handlers import pngwrite
    px = [((x * 7 + y * 13) % 256,) * 3 for y in range(64) for x in range(64)]
    pngwrite.write_png(height_png, 64, 64, px)
    fbx = os.path.join(OUT, "p2_bump.fbx").replace("\\", "/")
    r = call("execute_python", {"code": """
import maya.cmds as cmds
cmds.file(new=True, force=True)
t = cmds.polyCube(name='p2_cube', constructionHistory=False)[0]
cmds.makeIdentity(t, apply=True)
sh = cmds.shadingNode('standardSurface', asShader=True, name='p2_mat')
sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name='p2_sg')
cmds.connectAttr(sh + '.outColor', sg + '.surfaceShader')
cmds.sets(t, edit=True, forceElement=sg)
f = cmds.shadingNode('file', asTexture=True, name='p2_heightfile')
cmds.setAttr(f + '.fileTextureName', %r, type='string')
b = cmds.shadingNode('bump2d', asUtility=True, name='p2_bump')
cmds.setAttr(b + '.bumpInterp', 0)
cmds.connectAttr(f + '.outAlpha', b + '.bumpValue', force=True)
cmds.connectAttr(b + '.outNormal', sh + '.normalCamera', force=True)
result = 'wired'
""" % height_png.replace("\\", "/")})
    print("P2 wire:", r.get("status"), r.get("result"), flush=True)
    r = call("export_fbx", {"path": fbx, "metres_per_unit": 1.0,
                            "nodes": ["p2_cube"],
                            "require_baked_textures": True}, timeout_s=300.0)
    print("P2 export:", r.get("status"),
          (r.get("result") or {}).get("textures"), flush=True)
    if r.get("status") == "ok":
        with open(fbx.replace("/", os.sep), "rb") as fh:
            data = fh.read()
        print("P2 basename in FBX bytes:", b"p2_height.png" in data, flush=True)

if __name__ == "__main__":
    {"p1": p1, "p2": p2}.get(sys.argv[1] if len(sys.argv) > 1 else "", 
        lambda: sys.exit(__doc__))()
```

- [ ] **Step 2: Run P1 headless**

Run: `python evals/surfdetail_probe_775.py p1`
Expected: timings printed. Decision rule: 1024² over ~15 s → Task 2 generates patterns at 256² and bilinearly upsamples (the mask stays full-res); under → full-res generation.

- [ ] **Step 3: Launch agent Maya on 9878, run P2**

Launch with the Global Constraints recipe, verify the 9878 listener's pid matches the launched pid (`netstat -ano | findstr 9878`). Run `MAYA_MCP_PORT=9878 python evals/surfdetail_probe_775.py p2` (set the env var PowerShell-style: `$env:MAYA_MCP_PORT='9878'`).
Expected: export `ok`, `dropped_maps` empty, `P2 basename in FBX bytes: True`. If the export REFUSES the bump network or drops the map, STOP — the height output design changes (record what happened, discuss before proceeding).

- [ ] **Step 4: Record results below, commit**

**Results (filled by Task 1):**
- P1 256²: 0.4 s; 1024²: 6.8 s → strategy: full-res generation (1024² well under the ~15s threshold, no upsample needed)
- P2: export status `ok`, dropped_maps `[]` (empty), bytes carry PNG name: `True`. `file_maps` records one entry (`p2_heightfile` → `normalCamera`, `on_disk: True`, `found_in_file: True`) noting `semantics_lost: ["channel swizzle outAlpha"]` — the outAlpha→bumpValue swizzle isn't representable in FBX, informational only, not a refusal.

```bash
git add evals/surfdetail_probe_775.py docs/superpowers/plans/2026-08-31-775-directed-detail.md
git commit -m "probe(#775): fbm perf + bump-interp-0 FBX export measured"
```

---

### Task 2: `surfdetail_math.py` — patterns and composite (pure, TDD)

**Files:**
- Create: `maya_plugin/handlers/surfdetail_math.py`
- Test: `tests/test_surfdetail_math.py`

**Interfaces:**
- Consumes: `sculpt_math.fbm(x, y, z, octaves=2) -> float` (signed), `sculpt_math.vnoise(x, y, z) -> float` in [0,1].
- Produces (exact signatures Task 3 relies on):
  - `mask_values(png: dict, invert: bool) -> dict` — takes `pngprobe.read_png` output, returns `{"values": List[float 0..1], "width": int, "height": int}` (red channel / 255, inverted if asked).
  - `sample(field: dict, x: int, y: int, res: int) -> float` — nearest-neighbour lookup of a `{"values","width","height"}` field at output texel (x, y) of a res×res image.
  - `wear_pattern(res: int, scale: float, seed: int) -> dict` — ridged, thresholded fbm field, values in [0,1], mostly 0 (scratches are sparse).
  - `grime_pattern(res: int, scale: float, seed: int) -> dict` — soft speckle field in [0,1].
  - `height_pattern(res: int, scale: float, seed: int) -> dict` — unthresholded fbm remapped to [0,1].
  - `composite_detail(base_linear: List[tuple], effects: List[dict], res: int) -> dict` — effects are `[{"kind","pattern","mask","strength","color_linear"}]`, applied wear-then-grime regardless of list order; returns `{"pixels": List[(r,g,b) bytes], "changed": {kind: fraction}}`.
  - Pattern constants exposed at module top: `WEAR_THRESHOLD = 0.55`, `WEAR_OCTAVES = 3`, `GRIME_OCTAVES = 2`, `GRAIN_OCTAVES = 3`, `DEFAULT_WEAR_COLOR = (0.85, 0.82, 0.78)`, `DEFAULT_GRIME_COLOR = (0.09, 0.07, 0.05)` — provisional until Task 6's look probe; the gate task may retune them.

- [ ] **Step 1: Write the failing tests**

```python
"""Pure math for #775 - no Maya anywhere."""
import pytest
from maya_plugin.handlers import surfdetail_math as sm


def _flat_png(w, h, value, alpha=255):
    return {"width": w, "height": h,
            "pixels": [(value, value, value, alpha)] * (w * h)}


class TestMask:
    def test_mask_values_scales_red_to_unit(self):
        m = sm.mask_values(_flat_png(2, 2, 128), invert=False)
        assert m["width"] == 2 and m["height"] == 2
        assert all(abs(v - 128 / 255.0) < 1e-9 for v in m["values"])

    def test_invert_flips(self):
        m = sm.mask_values(_flat_png(1, 1, 0), invert=True)
        assert m["values"] == [1.0]

    def test_sample_nearest_across_resolutions(self):
        # 2x2 mask sampled at res 4: each quadrant reads its source texel.
        png = {"width": 2, "height": 2,
               "pixels": [(0, 0, 0, 255), (255, 255, 255, 255),
                          (255, 255, 255, 255), (0, 0, 0, 255)]}
        m = sm.mask_values(png, invert=False)
        assert sm.sample(m, 0, 0, 4) == 0.0      # top-left quadrant
        assert sm.sample(m, 3, 0, 4) == 1.0      # top-right
        assert sm.sample(m, 0, 3, 4) == 1.0
        assert sm.sample(m, 3, 3, 4) == 0.0


class TestPatterns:
    def test_wear_is_sparse_and_bounded(self):
        p = sm.wear_pattern(64, scale=1.0, seed=0)
        vals = p["values"]
        assert len(vals) == 64 * 64
        assert all(0.0 <= v <= 1.0 for v in vals)
        zero = sum(1 for v in vals if v == 0.0)
        assert zero > len(vals) * 0.5  # scratches are sparse, not a wash

    def test_grime_and_height_bounded_and_varied(self):
        for fn in (sm.grime_pattern, sm.height_pattern):
            p = fn(64, scale=1.0, seed=0)
            vals = p["values"]
            assert all(0.0 <= v <= 1.0 for v in vals)
            assert len(set(round(v, 6) for v in vals)) > 10  # not flat

    def test_seed_changes_pattern_deterministically(self):
        a = sm.wear_pattern(32, 1.0, seed=1)["values"]
        b = sm.wear_pattern(32, 1.0, seed=2)["values"]
        c = sm.wear_pattern(32, 1.0, seed=1)["values"]
        assert a == c
        assert a != b


class TestComposite:
    def _mask_half(self):
        # left half 0, right half 1 at 4x4
        vals = [1.0 if x >= 2 else 0.0 for y in range(4) for x in range(4)]
        return {"values": vals, "width": 4, "height": 4}

    def _pattern_all(self):
        return {"values": [1.0] * 16, "width": 4, "height": 4}

    def test_detail_lands_only_where_mask_says(self):
        base = [(0.5, 0.5, 0.5)] * 16
        out = sm.composite_detail(base, [{
            "kind": "grime", "pattern": self._pattern_all(),
            "mask": self._mask_half(), "strength": 1.0,
            "color_linear": (0.0, 0.0, 0.0)}], 4)
        px = out["pixels"]
        left = [px[y * 4 + x] for y in range(4) for x in range(2)]
        right = [px[y * 4 + x] for y in range(4) for x in range(2, 4)]
        assert all(p == left[0] for p in left)
        assert all(r[0] < left[0][0] for r in right)  # darkened only right
        assert 0.49 < out["changed"]["grime"] <= 0.51

    def test_wear_lightens_toward_color(self):
        base = [(0.2, 0.2, 0.2)] * 16
        out = sm.composite_detail(base, [{
            "kind": "wear", "pattern": self._pattern_all(),
            "mask": self._pattern_all(), "strength": 1.0,
            "color_linear": (1.0, 1.0, 1.0)}], 4)
        assert all(p[0] > 100 for p in out["pixels"])  # lifted well above base

    def test_order_is_wear_then_grime_regardless_of_list(self):
        base = [(0.5, 0.5, 0.5)] * 16
        eff_w = {"kind": "wear", "pattern": self._pattern_all(),
                 "mask": self._pattern_all(), "strength": 1.0,
                 "color_linear": (1.0, 1.0, 1.0)}
        eff_g = {"kind": "grime", "pattern": self._pattern_all(),
                 "mask": self._pattern_all(), "strength": 1.0,
                 "color_linear": (0.0, 0.0, 0.0)}
        a = sm.composite_detail(base, [eff_w, eff_g], 4)["pixels"]
        b = sm.composite_detail(base, [eff_g, eff_w], 4)["pixels"]
        assert a == b

    def test_strength_zero_changes_nothing(self):
        base = [(0.5, 0.5, 0.5)] * 16
        out = sm.composite_detail(base, [{
            "kind": "grime", "pattern": self._pattern_all(),
            "mask": self._pattern_all(), "strength": 0.0,
            "color_linear": (0.0, 0.0, 0.0)}], 4)
        assert out["changed"]["grime"] == 0.0
```

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/test_surfdetail_math.py -q`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement `surfdetail_math.py`**

Core shapes (P1 decides whether patterns generate at `min(res, 256)` and upsample — `sample()` already handles any size mismatch, so upsampling is just generating a smaller field):

```python
"""Pure pattern + composite math for #775. No Maya imports."""
from __future__ import annotations
from typing import Any, Dict, List, Tuple
from . import sculpt_math

WEAR_THRESHOLD = 0.55
WEAR_OCTAVES = 3
GRIME_OCTAVES = 2
GRAIN_OCTAVES = 3
DEFAULT_WEAR_COLOR = (0.85, 0.82, 0.78)
DEFAULT_GRIME_COLOR = (0.09, 0.07, 0.05)
_PATTERN_MAX = 256  # generation cap; sample() upsamples (P1: full-res too slow)


def mask_values(png: Dict[str, Any], invert: bool) -> Dict[str, Any]:
    vals = [p[0] / 255.0 for p in png["pixels"]]
    if invert:
        vals = [1.0 - v for v in vals]
    return {"values": vals, "width": png["width"], "height": png["height"]}


def sample(field: Dict[str, Any], x: int, y: int, res: int) -> float:
    fw, fh = field["width"], field["height"]
    sx = min(fw - 1, x * fw // res)
    sy = min(fh - 1, y * fh // res)
    return field["values"][sy * fw + sx]


def _field(res: int, scale: float, seed: int, octaves: int, shaper):
    size = min(res, _PATTERN_MAX)
    freq = 8.0 * scale / size
    z = seed * 17.31 + 0.5
    vals = [shaper(sculpt_math.fbm(x * freq, y * freq, z, octaves))
            for y in range(size) for x in range(size)]
    return {"values": vals, "width": size, "height": size}


def wear_pattern(res: int, scale: float, seed: int) -> Dict[str, Any]:
    def shaper(f):  # ridged + thresholded: sparse scratch streaks
        r = 1.0 - min(1.0, abs(f) * 2.0)      # ridges where fbm crosses 0
        return (r - WEAR_THRESHOLD) / (1.0 - WEAR_THRESHOLD) \
            if r > WEAR_THRESHOLD else 0.0
    return _field(res, scale, seed, WEAR_OCTAVES, shaper)


def grime_pattern(res: int, scale: float, seed: int) -> Dict[str, Any]:
    def shaper(f):  # soft speckle biased dark-heavy
        return max(0.0, min(1.0, f * 0.5 + 0.5)) ** 1.5
    return _field(res, scale, seed, GRIME_OCTAVES, shaper)


def height_pattern(res: int, scale: float, seed: int) -> Dict[str, Any]:
    def shaper(f):
        return max(0.0, min(1.0, f * 0.5 + 0.5))
    return _field(res, scale, seed, GRAIN_OCTAVES, shaper)


_ORDER = ("wear", "grime")


def composite_detail(base_linear: List[Tuple[float, float, float]],
                     effects: List[Dict[str, Any]],
                     res: int) -> Dict[str, Any]:
    """lerp(base, color, w) per texel in LINEAR, w = pattern*mask*strength.
    Wear then grime, whatever order the caller listed. Returns 8-bit sRGB
    pixels via meshmaps' encoder plus per-effect changed-texel fractions."""
    from . import meshmaps  # encoder lives with #770's composite
    n = res * res
    work = [list(p) for p in base_linear]
    changed = {}
    for kind in _ORDER:
        eff = next((e for e in effects if e["kind"] == kind), None)
        if eff is None:
            continue
        touched = 0
        color = eff["color_linear"]
        for i in range(n):
            x, y = i % res, i // res
            w = (sample(eff["pattern"], x, y, res)
                 * sample(eff["mask"], x, y, res) * eff["strength"])
            if w <= 0.0:
                continue
            w = min(1.0, w)
            px = work[i]
            before = tuple(px)
            for c in range(3):
                px[c] = px[c] + (color[c] - px[c]) * w
            if tuple(px) != before:
                touched += 1
        changed[kind] = touched / float(n)
    pixels = [(meshmaps._srgb_encode(p[0]), meshmaps._srgb_encode(p[1]),
               meshmaps._srgb_encode(p[2])) for p in work]
    return {"pixels": pixels, "changed": changed}
```

- [ ] **Step 4: Run, verify pass; adjust shaper constants only if a test exposes a real property violation (bounds, sparsity, determinism) — look-tuning waits for Task 6**

Run: `python -m pytest tests/test_surfdetail_math.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/surfdetail_math.py tests/test_surfdetail_math.py
git commit -m "feat(#775): pattern + composite math, pure and seeded"
```

---

### Task 3: `surfdetail.py` — the handler (TDD against FakeCmds)

**Files:**
- Create: `maya_plugin/handlers/surfdetail.py`
- Modify: `maya_plugin/handlers/meshmaps.py` — `_rewire_color(cmds, job, final_path)` gains a keyword `suffix="color_ao"` used in `base = "%s_%s" % (job["material"], suffix)`; no caller change needed.
- Test: `tests/test_surfdetail.py` (FakeCmds modeled on `tests/test_meshmaps.py`)

**Interfaces:**
- Consumes: `meshmaps.plan_apply(cmds, [(transform, shape)])` (base-colour jobs + refusals), `meshmaps.load_base_pixels(base)`, `meshmaps._rewire_color(cmds, job, path, suffix="color_detail")`, `surfdetail_math.*` (Task 2 signatures), `pngprobe.read_png/uniformity`, `pngwrite.write_png(path, w, h, pixels)`, `naming.require_mesh/unique_name`, `session.auto_checkpoint(label)`, `texbake._sweep_orphans`, `texclaim.material_claims`, `dispatcher.require_known_keys/HandlerError`, `texbake.RESOLUTIONS`, `pbr._PLACE2D_LINKS`.
- Produces: `apply_surface_detail(params) -> dict` with keys
  `{"mesh", "effects": [{"kind","strength","scale","changed_fraction"}], "color_file", "color_basename", "height_file", "height_basename", "file_nodes", "checkpoint_id", "warnings"}` (`color_*` None when no colour effect requested; `height_*` None when no grain). Module constants `EFFECT_KINDS = ("wear", "grime", "grain")`, `APPLY_SURFACE_DETAIL_KEYS`, `SYNONYMS` (top level: `{"meshes": "mesh", "masks_dir": "maps_dir", "dir": "maps_dir", "effect": "effects"}`; per-effect: `{"type": "kind", "intensity": "strength", "amount": "strength", "size": "scale", "colour": "color"}`).

**Behavioral requirements (each is a test):**

1. Unknown top-level or per-effect key → refusal naming the synonym.
2. `effects` missing/empty/non-list, unknown `kind`, repeated `kind` → refusal.
3. `strength` outside (0, 4], `scale` outside (0, 16], non-numeric, bool → refusal; defaults `strength=0.5` (grain: `0.3`), `scale=1.0`, `seed=0`.
4. `color` if given must be a 3-list of numbers in [0,1] → else refusal; stored LINEAR (values are linear floats, same convention as `assign_material` params).
5. `maps_dir` required/absolute/exists (same three refusals as meshmaps' `out_dir`); `out_dir` defaults to `maps_dir`, same checks when given.
6. Mask file resolution: wear needs `<short>_curvature.png`, grime and grain need `<short>_ao.png` (grain needs BOTH) in `maps_dir`, where `<short>` is the transform's short name. Missing → refusal naming the exact path and hinting `maya_bake_mesh_maps`.
7. Flat mask → refusal (distinct_values named); unmeasurable (`non_uniform is None`) → refusal. Uses `pngprobe.uniformity` per mask file.
8. `resolution` given → must be in `texbake.RESOLUTIONS`; defaulted → the curvature/ao mask's width (refuse if the two grain masks disagree in size).
9. Colour effects (wear/grime) route through `meshmaps.plan_apply` for the base — inheriting its refusals (procedural base → `maya_bake_textures` hint, multi-SG, outside wearers, unreadable file, multi-terminal). Grain-only calls skip `plan_apply` entirely.
10. Grain refuses when `shader.normalCamera` already has an incoming connection: "already carries a bump/normal network - this tool will not stack them" (hint: bake or remove it first). The shader is found the same way `plan_apply` finds it; for a grain-only call reuse `texture_recipes._shader_of`.
11. Happy path, colour: composite written to `out_dir/<mat>_color_detail.png` via `.part.png` → `os.replace`, rewired with `_rewire_color(..., suffix="color_detail")`, old file node swept via `texbake._sweep_orphans`, all under one `session.auto_checkpoint("apply_surface_detail")`; failure inside the apply sweeps created nodes and reports the checkpoint id (meshmaps phase-B idiom, including the same "scene has been modified ... checkpoint %s has the pre-apply scene" wrapper).
12. Happy path, grain: height field = `height_pattern * (0.5*curv + 0.5*ao_inv)` sampled per texel, written grayscale `(v,v,v)` to `out_dir/<short>_height.png`, wired `file → place2d links → bump2d(bumpInterp=0, outAlpha→bumpValue, bumpDepth=strength) → shader.normalCamera`.
13. Per-effect `changed_fraction` below 0.005 → warning ("strength/scale produced almost nothing").
14. Postcondition: after apply, `texclaim.material_claims` classifies the colour slot as file-backed pointing at the new PNG (assert in test the same way `test_meshmaps.py`'s apply tests do).
15. Result shape exactly as the Produces block above.

- [ ] **Step 1: Write the failing tests** — one test class per requirement group (`TestValidation` covers 1–8, `TestPlanning` 9–10, `TestApply` 11–15). Copy FakeCmds from `tests/test_meshmaps.py` and extend it with `bump2d`/`normalCamera` connection bookkeeping (`listConnections` on `.normalCamera` must reflect prior `connectAttr` calls). Mask fixtures are real PNGs written with `pngwrite` into `tmp_path` — a 4×4 non-uniform curvature file and a flat one.

- [ ] **Step 2: Run, verify failures** — `python -m pytest tests/test_surfdetail.py -q` → import error first, then per-test failures as the module grows.

- [ ] **Step 3: Implement `surfdetail.py`** — mirror meshmaps' file layout: `validate()`, `_resolve_masks()`, `_plan_color()`, `_plan_grain()`, pure-ish `_build_effects()` assembling Task 2 inputs, `apply_surface_detail()` orchestrating: validate → plan (all refusals fire before any file/scene touch) → generate patterns → composite + write files (`.part.png` commit) → checkpoint → rewire colour + wire bump → sweep old nodes → postcondition → result.

- [ ] **Step 4: Run to green, including the meshmaps suite** — `python -m pytest tests/test_surfdetail.py tests/test_surfdetail_math.py tests/test_meshmaps.py -q` (the `_rewire_color` signature change must not disturb #770's tests).

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/surfdetail.py maya_plugin/handlers/meshmaps.py tests/test_surfdetail.py
git commit -m "feat(#775): apply_surface_detail handler - directed wear/grime/grain"
```

---

### Task 4: Registration — wire table, schema, server tool, protocol doc

**Files:**
- Modify: `maya_plugin/maya_mcp_plugin.py` — add `from .handlers import surfdetail` alongside the meshmaps import and `"apply_surface_detail": surfdetail.apply_surface_detail` after `"bake_mesh_maps"` in the handler table.
- Modify: `src/maya_mcp/schemas.py` — after `BakeMeshMapsResult`:

```python
class AppliedEffect(BaseModel):
    model_config = ConfigDict(extra="ignore")
    kind: str
    strength: float
    scale: float
    changed_fraction: float


class ApplySurfaceDetailResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    mesh: str
    effects: list[AppliedEffect]
    color_file: str | None = None
    color_basename: str | None = None
    height_file: str | None = None
    height_basename: str | None = None
    file_nodes: list[str] = []
    checkpoint_id: str | None = None
    warnings: list[str] = []
```

(Match the exact ConfigDict/typing idiom the file already uses — copy from `BakeMeshMapsResult`.)
- Modify: `src/maya_mcp/server.py` — `maya_apply_surface_detail` tool after `maya_bake_mesh_maps`, annotations `read_only=False, destructive=True, idempotent=False`, timeout `EXPORT_TIMEOUT_S`; params `mesh: str`, `maps_dir: str`, `effects: list[dict]`, `out_dir: str | None = None`, `resolution: int | None = None`, `seed: int = 0`. Docstring must carry: what each kind does and which mask drives it, that colour is linear, that flat masks refuse (unlike #770's warn), and that grain refuses on an existing bump network.
- Modify: `docs/protocol.md` — extend the "Commands (mesh maps / #770)" area with a `## Commands (surface detail / #775)` section: wire table row for `apply_surface_detail`, param table, refusal list, result shape.
- Test: `tests/test_server_tools.py` — add `TestApplySurfaceDetail` (result-stub round-trip through the schema, param forwarding) and add `"maya_apply_surface_detail"` to the exact registered-tools set in `test_session_tools_registered`.

- [ ] **Step 1: Write the failing server tests** (registered-set membership + stub round-trip, modeled on `TestBakeMeshMaps`)
- [ ] **Step 2: Run, verify failure** — `python -m pytest tests/test_server_tools.py -q`
- [ ] **Step 3: Implement the four registrations above**
- [ ] **Step 4: Run to green** — same command; then the full headless suite `python -m pytest tests -q --junitxml=C:\Users\plotk\AppData\Local\Temp\claude\D--devel-maya-mcp\12dee624-30c3-41c4-b3b2-e3be659a2ad8\scratchpad\junit_775_headless.xml` and read counts from the XML.
- [ ] **Step 5: Commit**

```bash
git add maya_plugin/maya_mcp_plugin.py src/maya_mcp/schemas.py src/maya_mcp/server.py docs/protocol.md tests/test_server_tools.py
git commit -m "feat(#775): register maya_apply_surface_detail end to end"
```

---

### Task 5: Real-Maya tests (mayapy suite)

**Files:**
- Modify: `tests/test_handlers_mayapy.py` — append `TestApplySurfaceDetailInMaya`.

**Interfaces:**
- Consumes: the mayapy test scaffolding already in the file (standalone init, mtoa loading pattern from `TestBakeMeshMapsInMaya`), `meshmaps.bake_mesh_maps` to produce real masks.

**Tests (each a method; bake once per class via a cached fixture dir the way `TestBakeMeshMapsInMaya` manages its scene):**

1. Wear on a beveled cube with real baked curvature: composite PNG exists, `changed_fraction > 0`, and detail-mask correlation holds — compute mean |delta| (before vs after colour map, via `pngprobe.read_png`) over top-quartile curvature texels vs bottom-quartile; assert ratio > 2 (the lenient headless bar; the live gate pins the real one).
2. Grime with inverted AO on a two-mesh contact scene: darkening lands in the occluded region.
3. Grain: height PNG written and non-flat; `bump2d` exists with `bumpInterp` 0 and an incoming file connection; shader's `normalCamera` connected.
4. Grain on a shader that already has a bump network → HandlerError (build the network with `apply_texture_recipe`'s `noise_bump` first).
5. Flat mask (bake a lone flat plane's AO — honestly flat) → the wear/grime call refuses naming distinct values.
6. Checkpoint restore: after apply, `restore_checkpoint` returns the colour slot to its pre-apply state (`texclaim` classification back to value/original file).

- [ ] **Step 1: Write the tests, run to watch them fail** — `E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q -k SurfaceDetail --junitxml=<scratchpad>\junit_775_mayapy_red.xml` (expected: failures/errors for the missing behavior, not collection errors)
- [ ] **Step 2: Fix what real Maya disagrees with** (this is where mayapy-only surprises surface; keep fixes in the handler, tests only change if the *expectation* was wrong — record any such change in the commit message)
- [ ] **Step 3: Full mayapy suite green** — `E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q --junitxml=<scratchpad>\junit_775_mayapy.xml` (baseline 211 + new)
- [ ] **Step 4: Commit**

```bash
git add tests/test_handlers_mayapy.py maya_plugin/handlers/surfdetail.py
git commit -m "test(#775): directed detail proven in real Maya - correlation, relief, refusals"
```

---

### Task 6: Live gate + look probe (P3), constants pinned

**Files:**
- Create: `evals/surfdetail_live.py` (output dir `evals/surfdetail_live/`, untracked like the other gate outputs)

**Interfaces:**
- Consumes: `evals/live_call.py`'s `call`, `meshmaps_live.py`'s scene recipe (copy the `build_scene` shape: assemble ground+limb+collar with native UVs, per-object `mesh_cleanup`, `assign_material`, three_point lighting — do NOT import from it, gates stay self-contained), `bake_mesh_maps` to produce masks, then `apply_surface_detail` with all three effects.

**Gate checks (spec section "Gate"):**
1. Masks non-uniform (from bake stats).
2. Correlation from files: for wear on the limb — per-texel |after−before| of the colour map, mean over top-quartile curvature texels ÷ mean over bottom-quartile ≥ BAR (start at 3.0, pin the measured value into the script with a comment, #770's MAP_GAP_MIN idiom). Same for grime vs inverted AO on the ground, and the height map vs its blend mask.
3. Render before/after `apply_surface_detail` differ: relative mean-luma delta AND changed-pixel count (grain makes relief visible without necessarily moving mean luma much — count pixels whose luma moved ≥ 4).
4. Export with `require_baked_textures=True`: `<mat>_color_detail.png` and `<short>_height.png` basenames in the FBX bytes, `dropped_maps` empty.

- [ ] **Step 1: Write the gate script** (docstring carries the 9878-only warning verbatim from `meshmaps_live.py`)
- [ ] **Step 2: Launch agent Maya on 9878 (Global Constraints recipe), run the gate** — `$env:MAYA_MCP_PORT='9878'; python evals/surfdetail_live.py --build`
- [ ] **Step 3: P3 look probe — LOOK at both renders** (`render_scene` PNGs the gate saves). Judge: does wear read as wear on edges, grime as grime in pockets, grain as surface relief — not mould, noise, or dirt-everywhere? Retune `surfdetail_math` constants (threshold, octaves, default colours) and re-run until it reads right. Every retune re-runs Task 2's tests first (`python -m pytest tests/test_surfdetail_math.py -q`).
- [ ] **Step 4: Pin the bars** — replace the provisional correlation/render bars with measured-value-derived ones (comment records the measurement, #770 style). Re-run the gate clean: expected all checks PASS.
- [ ] **Step 5: Kill the agent Maya** (`taskkill /F /T /PID <pid>`, verify 9878 released), commit

```bash
git add evals/surfdetail_live.py maya_plugin/handlers/surfdetail_math.py
git commit -m "test(#775): live gate - correlation measured on real bakes, constants pinned by eye"
```

---

### Task 7: Suites, deploy, ticket, memory

- [ ] **Step 1: Full suites with junitxml** — headless `python -m pytest tests -q --junitxml=<scratchpad>\junit_775_final.xml` (baseline 1838 + new, 0 fail) and mayapy (baseline 211 + new, 0 fail). Read counts from the XML files.
- [ ] **Step 2: Deploy the plugin** — the repo's deploy step (copy to Documents/maya/scripts as done for #770), then `ping` the user's 9877: expect `restart_required=True` with the new digest; tell the user their Maya needs a restart and WAIT for them to confirm before verifying.
- [ ] **Step 3: Ticket** — one `update_issue` on #775: status Resolved, notes carrying commits, measured gate numbers (correlation ratios, render delta), suite counts, the look-probe verdict, and any unfiled follow-up candidates found on the way.
- [ ] **Step 4: Memory** — write `project-775-directed-detail.md` (resolution entry: measured traps, gate numbers, commits, deploy digest), link related memories, update `MEMORY.md` index top entry; fold any new measured trap into its own memory file if one bit hard enough.
- [ ] **Step 5: Final commit** if any doc/plan edits remain

```bash
git add -A -- docs evals/surfdetail_probe_775.py
git commit -m "docs(#775): plan results recorded, gate numbers pinned"
```

---

## Self-review notes

- Spec coverage: mechanism/pixels (T2–T3), height→bump (T3 req 12, P2 gate), tool surface (T3–T4), refusals incl. flat-mask-stricter-than-770 (T3 req 7, mayapy test 5), order-independence (T2 test), 0.5% warning (T3 req 13), gate's four claims (T6), probes P1/P2 (T1) and P3 (T6 step 3), out-of-scope untouched.
- Type consistency: `changed_fraction` (result field) is fed by `composite_detail`'s `changed[kind]`; `suffix` kwarg on `_rewire_color` used with `"color_detail"`; effect dicts in math (`pattern/mask/color_linear`) are built by the handler from wire-level effect dicts (`kind/strength/scale/color`) — two shapes on purpose, named differently.
- The one deliberately-deferred number: correlation and render bars are pinned by measurement in Task 6, recorded in-script — the repo's live-gate idiom, not a placeholder.
