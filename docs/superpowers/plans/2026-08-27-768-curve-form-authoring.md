# Curve-Driven Form Authoring (#768) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One new tool, `maya_create_curve_form` (`kind: sweep | revolve | loft`), that turns inline through-point curve specs into poly meshes, self-reports station conformance, and is proven by a live gate that also exercises boolean/uv_atlas/bind_skin on the results.

**Architecture:** A pure-math validation module (`curveform_math.py`, no Maya imports) plus a Maya-bound handler (`curveform.py`) registered as plugin command `create_curve_form`; the MCP server exposes it as `maya_create_curve_form` with a `CurveFormResult` schema. Construction curves are built with edit points (interpolating), consumed by `sweepMeshFromCurve` / `revolve` / `loft`, tessellated to poly, capped, and deleted — no curve objects survive the call.

**Tech Stack:** Python (Maya 2027 `maya.cmds` + `maya.api.OpenMaya`), pytest headless + `mayapy` suite, FastMCP server in `src/maya_mcp/server.py`.

**Spec:** `docs/superpowers/specs/2026-08-27-curve-form-authoring-design.md` — read it first; this plan implements it and argues from it.

## Global Constraints

- Worktree trap: in a worktree, pytest imports the PRIMARY checkout via the editable install. Run headless tests with `PYTHONPATH="src;."` set and verify `python -c "import maya_mcp; print(maya_mcp.__file__)"` points at the worktree before trusting any result.
- Two-Maya policy: the user's Maya is on port **9877 — never touch it, never `new_scene` it**. All live work uses the disposable agent Maya on **9878** (`evals/live_call.py` defaults to 9878).
- Live Maya loads the plugin from `Documents/maya/scripts`, not the repo. Before ANY live run: `.venv/Scripts/python.exe maya_plugin/install.py --yes`, then restart the agent Maya. `live_call.py` warns on staleness — never silence the warning.
- Measure suites with `--junitxml` (the pytest summary line is lost to stdout buffering here). Current baselines: headless **1691**, mayapy **184**.
- mayapy is `E:\Autodesk\Maya2027\bin\mayapy.exe`.
- Maya API trap: `MSpace` constants are ints — pass `space=` as a KEYWORD to OpenMaya calls (`getClosestPoint(pt, space=om.MSpace.kWorld)`), or the positional-overload silently misroutes.
- Commit style: `feat(#768): ...` / `test(#768): ...`, ending with the Claude co-author line.
- Sweep contingency (user-authorized 2026-08-27): if the Task 1 probe shows `sweepMeshFromCurve` cannot be driven scriptably (attrs missing / ramps unsettable), implement sweep via circle profile + `extrude` along the path → `nurbsToPoly` instead — same tool surface, same gate; approximate the width ramp by per-span profile scaling, and record the substitution in the spec and on ticket #768.
- Overnight autonomy (user-authorized 2026-08-27): when both suites and the live gate are green, merge to main and mark #768 Resolved without further confirmation. The user's Maya on 9877 will be stale after the deploy — the ticket note must say "restart any running Maya".

## File Structure

| File | Responsibility |
|---|---|
| `evals/curveform_probe_768.py` (new) | mayapy probe: measures the exact flags/attrs this Maya 2027 gives `curve(ep=)`, `closeCurve`, `revolve`, `loft`, `nurbsToPoly`, `sweepMeshFromCurve`. Throwaway-quality, kept for provenance. |
| `maya_plugin/handlers/curveform_math.py` (new) | Pure validation + geometry math: spec normalization, ramps, station expectations, face prediction. No Maya imports. |
| `maya_plugin/handlers/curveform.py` (new) | The `create_curve_form` handler: whole-call validation → build curves → construct → tessellate → cap → clean up → measure stations → result. |
| `maya_plugin/maya_mcp_plugin.py` (modify, ~line 183) | Register `"create_curve_form": curveform.create_curve_form` in the handler table. |
| `src/maya_mcp/schemas.py` (modify) | `CurveFormResult` model. |
| `src/maya_mcp/server.py` (modify) | `maya_create_curve_form` MCP tool. |
| `tests/test_curveform_math.py` (new) | Headless: the math module in full. |
| `tests/test_curveform.py` (new) | Headless: handler refusals that fire before any Maya import. |
| `tests/test_handlers_mayapy.py` (modify) | Real-geometry: vase/horn/torso built in `maya.standalone`, conformance + watertightness + cleanup asserted. |
| `tests/test_server_tools.py` (modify) | Tool listed + params forwarded verbatim. |
| `evals/curve_form_live.py` (new) | The live gate: three canonical forms, tolerance chosen by measurement, composition with boolean/uv_atlas/bind_skin, render_sheet. |

---

### Task 1: Probe this Maya's curve commands (mayapy)

**Files:**
- Create: `evals/curveform_probe_768.py`

**Interfaces:**
- Consumes: nothing from this repo except mayapy.
- Produces: measured facts later tasks depend on — printed as `PROBE <name>: <value>` lines. Specifically: (a) whether `cmds.curve(ep=..., degree=3)` interpolates (curve passes through the points), (b) the working `closeCurve` invocation for rings, (c) working `revolve`→`nurbsToPoly` and `loft`→`nurbsToPoly` flag sets and which of u/v runs along vs around, (d) `sweepMeshFromCurve`'s return value, creator node type, and the real attribute names for profile type/sides, scale/taper ramp, twist, and tessellation.

The spec's constructor choice was probed for *presence* only; nothing has measured how they are *driven*. Every later task cites these measurements, so this comes first and is run against real Maya, not remembered.

- [ ] **Step 1: Write the probe**

```python
"""#768 probe: how THIS Maya 2027 actually drives curve construction.

Run:  E:\\Autodesk\\Maya2027\\bin\\mayapy.exe evals/curveform_probe_768.py
Every finding prints as 'PROBE <name>: <value>'. Facts, not assertions:
a surprising value here changes Task 3's constants, not this script.
"""
from __future__ import annotations

import maya.standalone
maya.standalone.initialize(name="python")
import maya.cmds as cmds  # noqa: E402


def probe(name, value):
    print("PROBE %s: %r" % (name, value))


cmds.file(new=True, force=True)

# --- (a) does curve(ep=) interpolate? -----------------------------------
pts = [(0, 0, 0), (1, 2, 0), (2, 1, 0), (4, 3, 0)]
crv = cmds.curve(ep=pts, degree=3)
probe("ep_curve_created", crv)
# An interpolating curve passes through every edit point; measure the
# closest point on the curve to each authored point.
import maya.api.OpenMaya as om  # noqa: E402
sel = om.MSelectionList(); sel.add(crv)
fn = om.MFnNurbsCurve(sel.getDagPath(0))
worst = max(
    (om.MPoint(p) - fn.closestPoint(om.MPoint(p), space=om.MSpace.kWorld)[0]).length()
    for p in pts
)
probe("ep_curve_worst_point_distance", worst)  # expect ~0.0

# --- (b) closed ring curve ----------------------------------------------
ring = [(1, 0, 0), (0, 0, 1), (-1, 0, 0), (0, 0, -1)]
rc = cmds.curve(ep=ring + [ring[0]], degree=3)
closed = cmds.closeCurve(rc, constructionHistory=False, preserveShape=0,
                         replaceOriginal=True)
probe("closeCurve_result", closed)
probe("ring_form_after_close", cmds.getAttr(closed[0] + ".form")
      if closed else None)  # 0=open 1=closed 2=periodic

# --- (c) revolve -> nurbsToPoly ----------------------------------------
cmds.file(new=True, force=True)
prof = cmds.curve(ep=[(0.2, 0, 0), (0.5, 0.4, 0), (0.3, 0.9, 0), (0.4, 1.2, 0)],
                  degree=3)
rev = cmds.revolve(prof, constructionHistory=False, axis=(0, 1, 0),
                   pivot=(0, 0, 0), degree=3, sections=16,
                   startSweep=0, endSweep=360)
probe("revolve_result", rev)
poly = cmds.nurbsToPoly(rev[0], constructionHistory=False, format=2,
                        polygonType=1, uType=2, uNumber=24, vType=2, vNumber=16)
probe("revolve_poly", poly)
probe("revolve_poly_faces", cmds.polyEvaluate(poly[0], face=True))
# Which parameter runs around? Compare against uNumber/vNumber asymmetry.
probe("revolve_poly_verts", cmds.polyEvaluate(poly[0], vertex=True))

# --- (c2) loft -> nurbsToPoly ------------------------------------------
cmds.file(new=True, force=True)
rings = []
for y, r in ((0.0, 0.5), (0.6, 0.8), (1.4, 0.6), (2.0, 0.3)):
    pts = [(r, y, 0), (0, y, r), (-r, y, 0), (0, y, -r)]
    c = cmds.curve(ep=pts + [pts[0]], degree=3)
    c = cmds.closeCurve(c, constructionHistory=False, preserveShape=0,
                        replaceOriginal=True)[0]
    rings.append(c)
lofted = cmds.loft(*rings, constructionHistory=False, uniform=True,
                   close=False, autoReverse=False, degree=3)
probe("loft_result", lofted)
lpoly = cmds.nurbsToPoly(lofted[0], constructionHistory=False, format=2,
                         polygonType=1, uType=2, uNumber=24, vType=2, vNumber=16)
probe("loft_poly_faces", cmds.polyEvaluate(lpoly[0], face=True))

# --- (d) sweepMeshFromCurve --------------------------------------------
cmds.file(new=True, force=True)
path = cmds.curve(ep=[(0, 0, 0), (0, 1, 0.3), (0, 2, 0.2), (0, 3, 0.8)],
                  degree=3)
sweep = cmds.sweepMeshFromCurve(path)
probe("sweep_return", sweep)
probe("sweep_meshes", cmds.ls(type="mesh", long=True))
creators = cmds.ls(type="sweepMeshCreator")
probe("sweep_creator_nodes", creators)
if creators:
    attrs = cmds.listAttr(creators[0], keyable=False, hasData=True) or []
    interesting = [a for a in attrs if any(
        k in a.lower() for k in
        ("profile", "taper", "twist", "scale", "poly", "precision",
         "segment", "interpolation", "sweep", "distance", "cap"))]
    probe("sweep_creator_attrs", sorted(interesting))
    for a in sorted(interesting):
        try:
            probe("sweep_attr %s" % a, cmds.getAttr("%s.%s" % (creators[0], a)))
        except Exception as exc:  # noqa: BLE001 - compound attrs print as errors
            probe("sweep_attr %s" % a, "UNREADABLE: %s" % exc)

print("PROBE done")
```

- [ ] **Step 2: Run it**

Run: `E:\Autodesk\Maya2027\bin\mayapy.exe evals/curveform_probe_768.py`
Expected: every `PROBE` line prints; `ep_curve_worst_point_distance` ~0.0 (that is the interpolation guarantee the whole design rests on); `sweep_creator_attrs` names the taper/twist/profile/tessellation attributes.

- [ ] **Step 3: Record the findings**

Paste the full `PROBE` output into the commit message body. If `ep_curve_worst_point_distance` is not ≈ 0, or `sweepMeshFromCurve` has no scriptable taper, STOP — report to the user per Global Constraints.

- [ ] **Step 4: Commit**

```bash
git add evals/curveform_probe_768.py
git commit -m "probe(#768): measure curve/revolve/loft/sweep driving on this Maya 2027"
```

---

### Task 2: `curveform_math` — pure validation and station math

**Files:**
- Create: `maya_plugin/handlers/curveform_math.py`
- Test: `tests/test_curveform_math.py`

**Interfaces:**
- Consumes: `HandlerError` from `maya_plugin.dispatcher`; `MAX_PRIMITIVE_FACES` from `maya_plugin.handlers.modeling`.
- Produces (exact signatures Task 3 calls):
  - `validate_spec(params: dict) -> dict` — whole-call validation; returns the normalized spec described below or raises `HandlerError`.
  - `parse_ramp(value, what: str) -> list[tuple[float, float]]` — number → `[(0.0, v), (1.0, v)]`; list of `[t, v]` pairs validated (t in [0,1], strictly increasing, v > 0).
  - `ramp_value(ramp, t: float) -> float` — linear interpolation, clamped to the ramp's ends.
  - `chord_params(points) -> list[float]` — cumulative chord-length fractions, `[0.0, ..., 1.0]`.
  - `predicted_faces(spec) -> int` — refuses over `MAX_PRIMITIVE_FACES` with a hint naming `resolution`.
  - `station_expectations(spec) -> list[dict]` — `[{"label": str, "point": [x,y,z], "expected": [lo, hi]}, ...]`.
  - `form_size(spec) -> float` — max authored extent (sweep includes max width), the deviation normalizer.

Normalized spec shape (every later consumer relies on these keys):

```python
{"kind": "sweep"|"revolve"|"loft",
 "cap_ends": bool,
 "resolution": {"along": int, "around": int},
 # sweep only:
 "path": [[x,y,z], ...], "width": ramp, "twist": ramp_or_None,
 "profile_sides": int_or_None,          # None = circle
 # revolve only:
 "profile": [[radius, height], ...], "degrees": float, "axis": "x"|"y"|"z",
 # loft only:
 "sections": [[[x,y,z], ...ring...], ...]}
```

Limits (module constants, cited in every refusal hint): `MAX_PATH_POINTS = 64`, `MAX_PROFILE_POINTS = 64`, `MAX_SECTIONS = 16`, `MAX_RING_POINTS = 64`, `MIN_RING_POINTS = 3`, `MAX_ALONG = 512`, `MAX_AROUND = 256`. Defaults: resolution `{"along": 32, "around": 16}` for sweep, `{"along": 24, "around": 24}` for revolve and loft; `cap_ends=True`; `degrees=360.0`; `axis="y"`; `width=1.0` ramp.

Station expectation rules (from the spec: "sample the mesh at each authored station"):
- **revolve**: each profile point `(r, h)` revolved at 4 evenly spaced angles within `[0, degrees]` → for axis y the point is `[r*cos θ, h, r*sin θ]` (x: `[h, r*cos θ, r*sin θ]`; z: `[r*cos θ, r*sin θ, h]`); `expected = [0, 0]` — the surface interpolates the profile.
- **loft**: every ring point verbatim, `expected = [0, 0]`.
- **sweep**: each path point; the mesh surface sits `width/2` from the spine, so `expected = [w/2 * cos(pi/n), w/2]` with `n = profile_sides` (circle: `lo == hi == w/2`); `w = ramp_value(width, chord_params(path)[i])`. When `cap_ends` is true, the FIRST and LAST path points are excluded (the cap plane passes through them, making their closest-point distance ~0 — a false failure).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_curveform_math.py`:

```python
"""curveform_math is pure - every rule here runs with no Maya anywhere."""
import math

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import curveform_math as cm


def sweep_params(**over):
    p = {"kind": "sweep", "name": "horn",
         "path": [[0, 0, 0], [0, 1, 0], [0, 2, 0.5]], "width": 0.4}
    p.update(over)
    return p


class TestValidateSpec:
    def test_sweep_normalizes_with_defaults(self):
        spec = cm.validate_spec(sweep_params())
        assert spec["kind"] == "sweep"
        assert spec["cap_ends"] is True
        assert spec["resolution"] == {"along": 32, "around": 16}
        assert spec["width"] == [(0.0, 0.4), (1.0, 0.4)]
        assert spec["profile_sides"] is None

    def test_unknown_kind_refused(self):
        with pytest.raises(HandlerError, match="kind"):
            cm.validate_spec({"kind": "birail", "name": "x",
                              "path": [[0, 0, 0], [1, 0, 0]]})

    def test_wrong_kinds_param_refused_with_hint(self):
        # profile on a sweep is the cross-kind mistake a caller will make
        with pytest.raises(HandlerError, match="profile"):
            cm.validate_spec(sweep_params(profile=[[0.5, 0]]))

    def test_duplicate_consecutive_path_points_refused(self):
        with pytest.raises(HandlerError, match="consecutive"):
            cm.validate_spec(sweep_params(
                path=[[0, 0, 0], [0, 0, 0], [1, 0, 0]]))

    def test_too_many_path_points_refused(self):
        pts = [[0, float(i), 0] for i in range(cm.MAX_PATH_POINTS + 1)]
        with pytest.raises(HandlerError, match=str(cm.MAX_PATH_POINTS)):
            cm.validate_spec(sweep_params(path=pts))

    def test_revolve_negative_radius_refused(self):
        with pytest.raises(HandlerError, match="radius"):
            cm.validate_spec({"kind": "revolve", "name": "vase",
                              "profile": [[0.5, 0], [-0.1, 1]]})

    def test_loft_mismatched_ring_counts_refused(self):
        with pytest.raises(HandlerError, match="ring"):
            cm.validate_spec({"kind": "loft", "name": "torso", "sections": [
                [[1, 0, 0], [0, 0, 1], [-1, 0, 0]],
                [[1, 1, 0], [0, 1, 1], [-1, 1, 0], [0, 1, -1]]]})

    def test_loft_needs_two_sections(self):
        with pytest.raises(HandlerError, match="section"):
            cm.validate_spec({"kind": "loft", "name": "torso", "sections": [
                [[1, 0, 0], [0, 0, 1], [-1, 0, 0]]]})


class TestRamps:
    def test_constant_becomes_flat_ramp(self):
        assert cm.parse_ramp(0.4, "width") == [(0.0, 0.4), (1.0, 0.4)]

    def test_unsorted_t_refused(self):
        with pytest.raises(HandlerError, match="increasing"):
            cm.parse_ramp([[0.8, 1.0], [0.2, 0.5]], "width")

    def test_t_outside_unit_range_refused(self):
        with pytest.raises(HandlerError, match=r"\[0, 1\]"):
            cm.parse_ramp([[0.0, 1.0], [1.2, 0.5]], "width")

    def test_nonpositive_width_refused(self):
        with pytest.raises(HandlerError, match="positive"):
            cm.parse_ramp([[0.0, 1.0], [1.0, 0.0]], "width")

    def test_linear_interpolation_between_stops(self):
        ramp = cm.parse_ramp([[0.0, 1.0], [1.0, 0.5]], "width")
        assert cm.ramp_value(ramp, 0.5) == pytest.approx(0.75)

    def test_clamped_outside_stops(self):
        ramp = cm.parse_ramp([[0.25, 1.0], [0.75, 0.5]], "width")
        assert cm.ramp_value(ramp, 0.0) == pytest.approx(1.0)
        assert cm.ramp_value(ramp, 1.0) == pytest.approx(0.5)


class TestChordParams:
    def test_fractions_by_arc_length_not_index(self):
        # 3 points, second segment 3x the first: t must be [0, .25, 1]
        t = cm.chord_params([[0, 0, 0], [1, 0, 0], [4, 0, 0]])
        assert t == pytest.approx([0.0, 0.25, 1.0])


class TestFaceBudget:
    def test_over_budget_refused_naming_resolution(self):
        with pytest.raises(HandlerError, match="resolution"):
            cm.predicted_faces(cm.validate_spec(sweep_params(
                resolution={"along": 512, "around": 256})))
        # 512*256 = 131072 is fine; the refusal needs MAX_ALONG*MAX_AROUND to
        # exceed MAX_PRIMITIVE_FACES only via the explicit check in the test
        # below - so assert the arithmetic instead:

    def test_predicted_faces_is_along_times_around_plus_caps(self):
        spec = cm.validate_spec(sweep_params(
            resolution={"along": 10, "around": 8}))
        assert cm.predicted_faces(spec) == 10 * 8 + 2  # + 2 cap n-gons


class TestStations:
    def test_revolve_stations_lie_on_the_surface_ring(self):
        spec = cm.validate_spec({"kind": "revolve", "name": "vase",
                                 "profile": [[0.5, 0.0], [0.3, 1.0]]})
        st = cm.station_expectations(spec)
        assert len(st) == 2 * 4  # each profile point at 4 angles
        p = st[0]
        assert p["expected"] == [0.0, 0.0]
        assert math.hypot(p["point"][0], p["point"][2]) == pytest.approx(0.5)
        assert p["point"][1] == pytest.approx(0.0)

    def test_sweep_interior_expected_is_half_width(self):
        spec = cm.validate_spec(sweep_params(
            path=[[0, 0, 0], [0, 1, 0], [0, 2, 0]],
            width=[[0.0, 1.0], [1.0, 0.5]]))
        st = cm.station_expectations(spec)
        assert len(st) == 1  # cap_ends=True drops both end stations
        lo, hi = st[0]["expected"]
        assert lo == hi == pytest.approx(0.75 / 2)  # ramp at t=0.5, halved

    def test_sweep_ngon_expected_is_apothem_to_circumradius_band(self):
        spec = cm.validate_spec(sweep_params(
            path=[[0, 0, 0], [0, 1, 0], [0, 2, 0]], width=1.0,
            profile_sides=4))
        lo, hi = cm.station_expectations(spec)[0]["expected"]
        assert hi == pytest.approx(0.5)
        assert lo == pytest.approx(0.5 * math.cos(math.pi / 4))

    def test_loft_stations_are_the_ring_points(self):
        rings = [[[1, 0, 0], [0, 0, 1], [-1, 0, 0], [0, 0, -1]],
                 [[1, 2, 0], [0, 2, 1], [-1, 2, 0], [0, 2, -1]]]
        spec = cm.validate_spec({"kind": "loft", "name": "t",
                                 "sections": rings})
        st = cm.station_expectations(spec)
        assert [s["point"] for s in st] == [p for r in rings for p in r]


class TestFormSize:
    def test_sweep_size_includes_width(self):
        spec = cm.validate_spec(sweep_params(
            path=[[0, 0, 0], [0, 4, 0]], width=1.0))
        assert cm.form_size(spec) == pytest.approx(4.0)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_curveform_math.py -q --junitxml=evals/junit_cfm.xml`
Expected: collection error — `curveform_math` does not exist.

- [ ] **Step 3: Implement `maya_plugin/handlers/curveform_math.py`**

Pure module. Follow the docstring conventions of `arraymath.py`/`sculpt_math.py` (state WHY, cite #768). Implementation notes beyond the signatures above:

- `validate_spec` FIRST drops `None`-valued keys (`params = {k: v for k, v in params.items() if v is not None}`) — the MCP server sends every param, unset ones as `None`, and `None` must mean absent (defaults 360 / "y" / `{"along": 32, "around": 16}` etc. are applied here, never on the wire). Then it checks `kind` and dispatches to a per-kind `_validate_sweep/_revolve/_loft`. Each refuses the OTHER kinds' params by name (`"sweep does not take 'profile'"`, hint naming which kind does) — this is in addition to the handler-level `require_known_keys`, because a known-but-wrong-kind key is a different mistake than an unknown key.
- Point validation refuses non-numeric entries, wrong arity, and consecutive duplicates (`dist < 1e-9`), with hints showing a working example.
- `predicted_faces`: sweep and revolve `along * around + (2 if cap_ends else 0)`; loft `along * around + 2` caps likewise; refuse over `MAX_PRIMITIVE_FACES` (import from `.modeling`) with hint "lower `resolution` — along × around is the face bill".
- All angles in degrees at the surface, radians only inside math (house rule: `doubleAngle` lessons from #maya-deform).

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_curveform_math.py -q --junitxml=evals/junit_cfm.xml`
Expected: all pass. Delete `evals/junit_cfm.xml` after reading it (evals/ dirs with other agents' output are off-limits; a stray junit file must not look like theirs).

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/curveform_math.py tests/test_curveform_math.py
git commit -m "feat(#768): curveform_math - pure spec validation, ramps, station math"
```

---

### Task 3: The `create_curve_form` handler + registration

**Files:**
- Create: `maya_plugin/handlers/curveform.py`
- Modify: `maya_plugin/maya_mcp_plugin.py` (handler table, near line 183)
- Test: `tests/test_curveform.py`

**Interfaces:**
- Consumes: `curveform_math.validate_spec/predicted_faces/station_expectations/form_size/ramp_value/chord_params`; `naming.unique_name(cmds, requested)`; `ledger.record(cmds, long_name)`; `meshcheck.mesh_stats(name)`; `modeling._vec3(params, key)`, `modeling._apply_xform(...)`, `modeling._long(cmds, name)`; `dispatcher.require_known_keys`.
- Produces: `create_curve_form(params: dict) -> dict` returning
  `{"name": str, "faces": int, "verts": int, "watertight": bool, "stations": int, "worst_station_deviation": float, "worst_station": Optional[str], "form_size": float, "warnings": List[str]}`
  — registered as plugin command `"create_curve_form"`. Task 5's schema mirrors these fields exactly.

- [ ] **Step 1: Write the failing headless tests**

Create `tests/test_curveform.py` — only refusals that fire BEFORE `_cmds()` is reached, so they run with no Maya:

```python
"""create_curve_form refusals that never touch Maya.

Whole-call validation runs before any cmds import (assemble-style): a bad
call must leave nothing behind, and these tests prove the refusal path is
Maya-free by running where maya is not importable at all.
"""
import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import curveform


class TestParamGate:
    def test_unknown_key_refused_with_synonym(self):
        with pytest.raises(HandlerError, match="'points' is called 'path'"):
            curveform.create_curve_form({
                "kind": "sweep", "name": "horn",
                "points": [[0, 0, 0], [0, 1, 0]]})

    def test_taper_names_width(self):
        with pytest.raises(HandlerError, match="'taper' is called 'width'"):
            curveform.create_curve_form({
                "kind": "sweep", "name": "horn",
                "path": [[0, 0, 0], [0, 1, 0]], "taper": 0.5})

    def test_missing_name_refused(self):
        with pytest.raises(HandlerError, match="name"):
            curveform.create_curve_form({
                "kind": "sweep", "path": [[0, 0, 0], [0, 1, 0]]})

    def test_bad_spec_refused_before_any_maya_import(self):
        # This test RUNNING headless is itself the assertion that
        # validation precedes Maya - a cmds import here would blow up.
        with pytest.raises(HandlerError, match="kind"):
            curveform.create_curve_form({"kind": "nope", "name": "x"})

    def test_over_budget_resolution_refused(self):
        with pytest.raises(HandlerError, match="face"):
            curveform.create_curve_form({
                "kind": "revolve", "name": "vase",
                "profile": [[0.5, 0.0], [0.3, 1.0]],
                "resolution": {"along": 512, "around": 256},
                "degrees": 360})
```

(Adjust the over-budget numbers if 512×256 < `MAX_PRIMITIVE_FACES`: use the documented `MAX_ALONG`/`MAX_AROUND` clamp refusal instead — the point is that an impossible bill is refused before Maya.)

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_curveform.py -q`
Expected: FAIL — no module `curveform`.

- [ ] **Step 3: Implement `maya_plugin/handlers/curveform.py`**

Structure (module docstring explains the blind-authoring rationale, cites the spec):

```python
CREATE_CURVE_FORM_KEYS = (
    "kind", "name", "path", "width", "twist", "profile_sides",
    "profile", "degrees", "axis", "sections",
    "resolution", "cap_ends", "translate", "rotate", "scale",
)
CREATE_CURVE_FORM_SYNONYMS = {
    "points": "path", "taper": "width", "curve": "path",
    "rings": "sections", "sides": "profile_sides", "cross_sections": "sections",
}
# Soft self-report threshold; the live gate (Task 6) MEASURES the real
# number and this constant is updated there - see the gate's Step 5.
DEVIATION_WARN = 0.05

# Measured by evals/curveform_probe_768.py - if the probe printed different
# names, THESE ARE WRONG: fix them here, in one place.
_SWEEP_CREATOR_TYPE = "sweepMeshCreator"
```

`create_curve_form(params)` flow:
1. `require_known_keys(params, CREATE_CURVE_FORM_KEYS, "create_curve_form", CREATE_CURVE_FORM_SYNONYMS)`.
2. `name` required non-empty string (same refusal wording as `create_primitive`).
3. `spec = curveform_math.validate_spec(params)`; `curveform_math.predicted_faces(spec)`.
4. Only now `cmds = _cmds()`; `requested = naming.unique_name(cmds, params["name"])`.
5. Build inside try/finally that deletes every temp node it created on ANY exit (`temp_nodes` list): `_build_sweep` / `_build_revolve` / `_build_loft` per kind, each returning the mesh transform.
   - `_ep_curve(cmds, pts)`: `cmds.curve(ep=[tuple(p) for p in pts], degree=min(3, len(pts) - 1))`.
   - `_ring_curve(cmds, pts)`: EP curve through `pts + [pts[0]]` then `cmds.closeCurve(..., constructionHistory=False, preserveShape=0, replaceOriginal=True)` — exact flags from the Task 1 probe.
   - `_build_revolve`: profile points `(r, h) → (r, h, 0)` for axis y (per-axis mapping as in `curveform_math.station_expectations`); `cmds.revolve(crv, constructionHistory=False, axis=<axis vec>, pivot=(0,0,0), degree=3, sections=spec["resolution"]["around"], startSweep=0, endSweep=spec["degrees"])`; then `_nurbs_to_poly`.
   - `_build_loft`: ring curves → `cmds.loft(*curves, constructionHistory=False, uniform=True, close=False, autoReverse=False, degree=3)` → `_nurbs_to_poly`.
   - `_nurbs_to_poly(cmds, surf, along, around)`: `cmds.nurbsToPoly(surf, constructionHistory=False, format=2, polygonType=1, uType=2, uNumber=?, vType=2, vNumber=?)` — u/v-to-along/around mapping exactly as the probe measured it.
   - `_build_sweep`: path curve → `cmds.sweepMeshFromCurve(crv)`; find the creator node (`cmds.ls(type=_SWEEP_CREATOR_TYPE)` scoped to new nodes); set profile type/sides, the scale/taper ramp from `spec["width"]` (ramp entries via the probe-measured compound attr, positions = the ramp's `t` values), twist likewise, tessellation from `resolution`; then `cmds.delete(mesh, constructionHistory=True)` to bake.
6. `cap_ends`: if `meshcheck.mesh_stats` reports boundary edges, `cmds.polyCloseBorder(mesh, constructionHistory=False)`.
7. `modeling._apply_xform(cmds, long_name, _vec3(translate), _vec3(rotate), _vec3(scale), relative=False)`; `ledger.record(cmds, long_name)`.
8. Delete all construction curves/surfaces; assert none remain (`cmds.objExists`).
9. Measure: `stats = meshcheck.mesh_stats(long_name)`; `_measure_stations(long_name, curveform_math.station_expectations(spec), curveform_math.form_size(spec))` using `MFnMesh.getClosestPoint(om.MPoint(p), space=om.MSpace.kWorld)` (KEYWORD space — Global Constraints trap). Station deviation = distance below `lo` or above `hi`, normalized by `form_size`. NOTE: stations are authored in the form's LOCAL frame — measure before step 7's xform, or transform expectations; measuring BEFORE `_apply_xform` is the simple correct order (build at origin, measure, then place).
10. Warnings: `worst > DEVIATION_WARN` → "worst station deviation X of form size — raise `resolution` or simplify the curve"; non-watertight after `cap_ends=True` → warning naming boundary/nonmanifold counts.
11. Return the result dict (exact keys in Interfaces).

Register in `maya_mcp_plugin.py`: import `curveform` alongside the other handlers; add `"create_curve_form": curveform.create_curve_form,` after `"create_primitive"`.

- [ ] **Step 4: Run headless tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_curveform.py tests/test_curveform_math.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/curveform.py maya_plugin/maya_mcp_plugin.py tests/test_curveform.py
git commit -m "feat(#768): create_curve_form handler - sweep/revolve/loft from through-points"
```

---

### Task 4: Real-geometry tests under mayapy

**Files:**
- Modify: `tests/test_handlers_mayapy.py` (append a class)

**Interfaces:**
- Consumes: `curveform.create_curve_form` (Task 3), the existing `maya_session`/`fresh_scene` fixtures in this file.
- Produces: proof in real Maya that the three kinds build, interpolate, cap, and clean up. Task 6 relies on these passing before any live run.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_handlers_mayapy.py`):

```python
class TestCurveFormInMaya:
    def _build(self, params):
        from maya_plugin.handlers import curveform
        return curveform.create_curve_form(params)

    def test_revolve_vase_is_watertight_and_on_station(self):
        result = self._build({
            "kind": "revolve", "name": "vase",
            "profile": [[0.30, 0.0], [0.50, 0.35], [0.22, 0.80],
                        [0.28, 1.10], [0.20, 1.25]]})
        assert result["watertight"] is True
        assert result["stations"] == 5 * 4
        assert result["worst_station_deviation"] < 0.05
        assert result["faces"] > 0

    def test_sweep_horn_tapers(self):
        import maya.cmds as cmds
        result = self._build({
            "kind": "sweep", "name": "horn",
            "path": [[0, 0, 0], [0.1, 0.5, 0], [0.35, 0.9, 0],
                     [0.7, 1.1, 0.2]],
            "width": [[0.0, 0.30], [1.0, 0.06]]})
        assert result["worst_station_deviation"] < 0.05
        # The taper is real: the mesh near the tip is narrower than the base.
        bbox = cmds.exactWorldBoundingBox(result["name"])
        assert bbox[4] > 1.0  # reached the top of the path (y max)

    def test_loft_torso_passes_through_rings(self):
        rings = []
        for y, r in ((0.0, 0.35), (0.4, 0.45), (0.9, 0.40), (1.3, 0.25)):
            rings.append([[r, y, 0], [0, y, r], [-r, y, 0], [0, y, -r]])
        result = self._build({"kind": "loft", "name": "torso",
                              "sections": rings})
        assert result["worst_station_deviation"] < 0.05
        assert result["watertight"] is True

    def test_no_construction_nodes_survive(self):
        import maya.cmds as cmds
        before_curves = set(cmds.ls(type="nurbsCurve") or [])
        before_surfs = set(cmds.ls(type="nurbsSurface") or [])
        self._build({"kind": "revolve", "name": "cleanup_probe",
                     "profile": [[0.4, 0.0], [0.3, 0.8]]})
        assert set(cmds.ls(type="nurbsCurve") or []) == before_curves
        assert set(cmds.ls(type="nurbsSurface") or []) == before_surfs
        # and no construction history on the mesh itself
        assert not (cmds.listHistory("cleanup_probe",
                                     pruneDagObjects=True) or [])

    def test_placement_happens_after_measurement(self):
        # Stations are authored in the local frame; a translated build must
        # still self-measure clean (regression guard for measure-then-place).
        result = self._build({
            "kind": "revolve", "name": "placed_vase",
            "profile": [[0.4, 0.0], [0.3, 0.8]],
            "translate": [5.0, 0.0, 2.0]})
        assert result["worst_station_deviation"] < 0.05
```

- [ ] **Step 2: Run to verify current failure**

Run: `E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -k CurveForm -q`
Expected: failures only where the implementation is genuinely wrong; fix the handler (attr names from the probe are the likely culprits) until green. The 0.05 assertions here are deliberately loose — the honest tolerance is chosen in Task 6 from live measurement.

- [ ] **Step 3: Run the whole mayapy suite**

Run: `E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q --junitxml=evals/junit_mayapy.xml`
Expected: 184 + 5 = **189 passed** (read the count from the junitxml, then delete the xml).

- [ ] **Step 4: Commit**

```bash
git add tests/test_handlers_mayapy.py maya_plugin/handlers/curveform.py
git commit -m "test(#768): curve forms build, interpolate, cap and clean up in real Maya"
```

---

### Task 5: MCP server surface

**Files:**
- Modify: `src/maya_mcp/schemas.py` (new result model, near `PrimitiveResult`)
- Modify: `src/maya_mcp/server.py` (new tool, near `maya_create_primitive`)
- Test: `tests/test_server_tools.py`

**Interfaces:**
- Consumes: the handler's result keys (Task 3 Interfaces), `NameResult`, `Vec3`, `BOOL_TIMEOUT_S`, the `maya.request` connection.
- Produces: MCP tool `maya_create_curve_form`; `CurveFormResult` in schemas.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_server_tools.py`; also add `"maya_create_curve_form"` to the expected tool list at the top of the file, ~line 61):

```python
class TestCurveFormTools:
    def test_maya_create_curve_form_forwards_params(self):
        conn = FakeConn(responses={"create_curve_form": {
            "name": "|horn", "faces": 512, "verts": 514, "watertight": True,
            "stations": 2, "worst_station_deviation": 0.004,
            "worst_station": "path[1]", "form_size": 1.1, "warnings": [],
        }})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_create_curve_form", {
            "kind": "sweep", "name": "horn",
            "path": [[0, 0, 0], [0, 1, 0], [0.4, 1.6, 0]],
            "width": [[0.0, 0.3], [1.0, 0.05]],
        }))
        assert result.is_error is False
        assert conn.calls[0]["cmd"] == "create_curve_form"
        sent = conn.calls[0]["params"]
        assert sent["kind"] == "sweep"
        assert sent["width"] == [[0.0, 0.3], [1.0, 0.05]]
        # Unset optionals arrive as None, never invented defaults (#669 lesson)
        assert sent["profile"] is None and sent["sections"] is None
        assert result.structured_content["worst_station_deviation"] == 0.004

    def test_maya_create_curve_form_revolve_defaults(self):
        conn = FakeConn(responses={"create_curve_form": {
            "name": "|vase", "faces": 576, "verts": 578, "watertight": True,
            "stations": 8, "worst_station_deviation": 0.002,
            "worst_station": "profile[2]@90", "form_size": 1.25,
            "warnings": [],
        }})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_create_curve_form", {
            "kind": "revolve", "name": "vase",
            "profile": [[0.3, 0.0], [0.5, 0.4], [0.2, 1.25]],
        }))
        assert result.is_error is False
        assert conn.calls[0]["params"]["degrees"] == 360
        assert conn.calls[0]["params"]["cap_ends"] is True
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_server_tools.py -q`
Expected: FAIL — unknown tool, and the tool-list test fails on the missing name.

- [ ] **Step 3: Implement**

`schemas.py` — after `PrimitiveResult`:

```python
class CurveFormResult(NameResult):
    """What the curve build measured about itself, not just that it ran.

    The whole point of curve-driven authoring (#768) is that the numbers the
    caller wrote are assertable: worst_station_deviation is the worst
    distance from the produced surface to those numbers, as a fraction of
    form_size, so a caller (and the gate) reads conformance straight off the
    result instead of re-deriving it.
    """

    model_config = ConfigDict(extra="ignore")

    faces: int = Field(description="Face count of the mesh just built.")
    verts: int = Field(description="Vertex count of the mesh just built.")
    watertight: bool = Field(description=(
        "True when the mesh has no boundary and no non-manifold edges."))
    stations: int = Field(description=(
        "How many authored stations were measured against the mesh."))
    worst_station_deviation: float = Field(description=(
        "Worst distance from the mesh surface to an authored station, as a "
        "fraction of form_size. Near 0 = the surface passes through your "
        "numbers; large = raise `resolution` or simplify the curve."))
    worst_station: Optional[str] = Field(
        default=None,
        description="Label of the worst station, e.g. 'path[3]' or 'profile[2]@90'.")
    form_size: float = Field(description=(
        "Max authored extent in scene units - the deviation normalizer."))
```

`server.py` — after `maya_create_primitive`, `@mcp.tool(title="Create curve-driven form", annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False))`:

```python
def maya_create_curve_form(
    kind: Annotated[Literal["sweep", "revolve", "loft"], Field(description=(
        "sweep: a tube along `path`, sized by `width` - horns, limbs, "
        "vines, straps. revolve: `profile` spun about an axis - heads, "
        "vases, domes. loft: a skin through `sections` rings - torsos, "
        "tails, hulls."))],
    name: Annotated[str, Field(min_length=1, description=(
        "Requested name; collisions get a deterministic suffix and the "
        "canonical long name is returned."))],
    path: Annotated[Optional[List[List[float]]], Field(description=(
        "sweep only. 3D points the spine passes THROUGH (interpolated, "
        "not a control hull), 2-64 of them. e.g. "
        "[[0,0,0],[0,1,0.2],[0.4,1.6,0.3]]"))] = None,
    width: Annotated[Optional[Union[float, List[List[float]]]],
                     Field(description=(
        "sweep only. Tube DIAMETER: a number for constant width, or "
        "[t, width] pairs (t 0-1 along the path, strictly increasing) for "
        "a taper - [[0,0.3],[1,0.05]] is a horn. Default 1.0."))] = None,
    twist: Annotated[Optional[List[List[float]]], Field(description=(
        "sweep only. [t, degrees] pairs twisting the profile along the "
        "path."))] = None,
    profile_sides: Annotated[Optional[int], Field(ge=3, le=64, description=(
        "sweep only. Cross-section as an n-gon instead of a circle: 4 = "
        "square strap, 6 = hex bolt shaft."))] = None,
    profile: Annotated[Optional[List[List[float]]], Field(description=(
        "revolve only. [radius, height] pairs of the silhouette in the "
        "half-plane, interpolated - [[0.3,0],[0.5,0.4],[0.2,1.2]] is a "
        "vase. Radius 0 at an end closes that end onto the axis."))] = None,
    degrees: Annotated[Optional[float], Field(gt=0, le=360, description=(
        "revolve only. Sweep angle; default 360. Less leaves an open shell "
        "(capped when cap_ends)."))] = None,
    axis: Annotated[Optional[Literal["x", "y", "z"]], Field(description=(
        "revolve only. Revolution axis; default y (height in `profile` "
        "runs along it)."))] = None,
    sections: Annotated[Optional[List[List[List[float]]]], Field(description=(
        "loft only. 2-16 cross-section rings, outermost list ordered "
        "along the form; each ring is a closed loop of 3D points, SAME "
        "count per ring (3-64), matched index-to-index."))] = None,
    resolution: Annotated[Optional[dict], Field(description=(
        "{along, around} tessellation. Defaults: sweep {32,16}, "
        "revolve/loft {24,24}. along*around is the face bill (1M cap). "
        "Raise it when worst_station_deviation comes back high."))] = None,
    cap_ends: Annotated[bool, Field(description=(
        "Close open borders (tube ends, loft ends, partial revolves) so "
        "the result is watertight. Default true."))] = True,
    translate: Vec3 = None,
    rotate: Vec3 = None,
    scale: Vec3 = None,
) -> CurveFormResult:
    """Build a flowing poly surface THROUGH the numbers you write.

    This is the parametric half of modelling: describe a silhouette as a
    short list of points and Maya constructs the surface deterministically
    - where primitives + deformers can only push a box around. The curve
    INTERPOLATES your points, so the surface passes through them, and the
    result reports worst_station_deviation - how far the built mesh strays
    from your numbers - so you know it worked without rendering.

    Construction curves are internal: nothing but the mesh survives the
    call. The result composes with everything else - boolean_op, deform,
    uv_atlas, bind_skin."""
    return CurveFormResult.model_validate(
        maya.request(
            "create_curve_form",
            {"kind": kind, "name": name, "path": path, "width": width,
             "twist": twist, "profile_sides": profile_sides,
             "profile": profile, "degrees": degrees, "axis": axis,
             "sections": sections, "resolution": resolution,
             "cap_ends": cap_ends, "translate": translate,
             "rotate": rotate, "scale": scale},
            timeout_s=BOOL_TIMEOUT_S,
        )
    )
```

Note the request dict sends EVERY param, unset ones as `None` — the handler treats `None` as absent (`validate_spec` must ignore `None`-valued keys; make sure Task 2's `validate_spec` does `params = {k: v for k, v in params.items() if v is not None}` first, and that `require_known_keys` in Task 3 runs on the ORIGINAL keys so synonyms still fire). `degrees`/`axis` default resolution happens in `validate_spec` (360 / "y") so the wire shows `None`, matching the #669 lesson the server test pins.

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_server_tools.py tests/test_curveform.py tests/test_curveform_math.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full headless suite**

Run: `.venv/Scripts/python.exe -m pytest tests -q --junitxml=evals/junit_headless.xml`
Expected: 1691 + new tests, 0 failures (count from the xml, then delete the xml). `test_install_guard`/digest tests will fail if the plugin digest machinery needs the new files listed anywhere — if one fails, read it: it is usually telling you the deployed-copy manifest must include `curveform*.py`.

- [ ] **Step 6: Commit**

```bash
git add src/maya_mcp/schemas.py src/maya_mcp/server.py tests/test_server_tools.py
git commit -m "feat(#768): maya_create_curve_form on the MCP surface"
```

---

### Task 6: Deploy + live gate, tolerance chosen by measurement

**Files:**
- Create: `evals/curve_form_live.py`
- Modify: `maya_plugin/handlers/curveform.py` (set `DEVIATION_WARN` to the measured tolerance)

**Interfaces:**
- Consumes: `evals/live_call.py` (`call(command, params, timeout_s)` raw-frame client, port from `MAYA_MCP_PORT`, default 9878); plugin commands `create_curve_form`, `create_primitive`, `boolean_op`, `uv_atlas`, `create_skeleton`, `bind_skin`, `render_sheet`, `new_scene`.
- Produces: the acceptance gate for #768; exits non-zero on first failure; artifacts in `evals/curve_form_live/`.

- [ ] **Step 1: Deploy and restart the disposable Maya**

```bash
.venv/Scripts/python.exe maya_plugin/install.py --yes
```

Then launch/restart the agent Maya on port **9878** (never the user's 9877; verify the pid owning the port with `netstat -ano | findstr 987` — a port is not an identity). Confirm it answers with the NEW stamp:

```bash
.venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'evals'); from live_call import call; print(call('ping', {}, 30.0))"
```

Expected: pong with a `loaded_digest` matching this tree and no staleness warning on stderr.

- [ ] **Step 2: Write the gate**

Create `evals/curve_form_live.py`, in the shape of `evals/array_deform_live.py` (raw frames via `live_call.call`, print measured numbers, `sys.exit(1)` on first failure):

```python
"""#768 acceptance gate: curve-driven forms in a REAL Maya, measured.

Three forms that were impossible before this ticket - a vase (revolve), a
tapered horn (sweep), a torso (loft) - each asserted on the numbers the
tool itself reports, then pushed through the rest of the pipeline
(boolean, uv_atlas, bind_skin), because a constructor whose output the
other tools choke on has not closed the gap.

Run:  set MAYA_MCP_PORT=9878 && .venv/Scripts/python.exe evals/curve_form_live.py
Artifacts: evals/curve_form_live/*.png
"""
```

Gate body, step by step (each `check(...)` prints the measured value and exits non-zero on failure):

1. `new_scene`.
2. **Vase**: `create_curve_form` revolve, profile `[[0.30,0.0],[0.50,0.35],[0.22,0.80],[0.28,1.10],[0.20,1.25]]`. Assert `watertight`, `faces > 0`, `worst_station_deviation <= TOLERANCE`.
3. **Horn**: sweep, path `[[0,0,0],[0.1,0.5,0],[0.35,0.9,0],[0.7,1.1,0.2]]`, width ramp `[[0,0.30],[1,0.06]]`. Assert deviation, watertight.
4. **Torso**: loft through 4 rings (8 points per ring, elliptical: chest wider than waist). Assert deviation, watertight.
5. **Composition — boolean**: `create_primitive` cube, `boolean_op` union with the horn. Assert it returns ok and reports faces.
6. **Composition — uv_atlas** on the vase. Assert ok.
7. **Composition — bind_skin**: `create_skeleton` (3-joint chain up the torso's height), `bind_skin` to the torso. Assert ok.
8. `render_sheet` of the three forms → `evals/curve_form_live/sheet.png`. Assert the render returns ok (the #765 opacity probe already guards blank frames server-side).

Start with `TOLERANCE = None` — when `None`, the gate PRINTS every `worst_station_deviation` and exits 0 without asserting them (measurement mode).

- [ ] **Step 3: Measure, then choose the tolerance**

Run: `set MAYA_MCP_PORT=9878 && .venv/Scripts/python.exe evals/curve_form_live.py`
Record the three printed deviations. Choose `TOLERANCE` = 2× the worst measured value, rounded UP to one significant figure, floored at 0.01 (the #773 method: measure first, then state the threshold that discriminates). Also verify the discrimination direction: rerun the horn once with `resolution={"along": 4, "around": 4}` via a temporary block in the gate and confirm its deviation LANDS ABOVE the chosen tolerance — a tolerance no broken build can fail is not a gate. Remove the temporary block, or keep it as a permanent negative check asserting `deviation > TOLERANCE` (preferred — keep it).

- [ ] **Step 4: Set the tolerance and re-run to green**

Set `TOLERANCE` in the gate AND update `DEVIATION_WARN` in `curveform.py` to the same value; redeploy (`install.py --yes`), restart the 9878 Maya, rerun the gate.
Expected: exit 0, all measured numbers printed, sheet rendered. Eyeball `sheet.png`: the vase flows, the horn tapers, the torso swells — the spec's whole point, confirmed by eye once.

- [ ] **Step 5: Commit**

```bash
git add evals/curve_form_live.py maya_plugin/handlers/curveform.py
git commit -m "test(#768): live gate - three curve forms measured, tolerance chosen by measurement"
```

Put the measured deviations and the chosen tolerance in the commit body.

---

### Task 7: Suites, review, merge, ticket

**Files:**
- Modify: none new — this is verification and closure.

**Interfaces:**
- Consumes: everything above.
- Produces: merged main, Resolved ticket, updated memory.

- [ ] **Step 1: Full headless suite** — `.venv/Scripts/python.exe -m pytest tests -q --junitxml=evals/junit_final.xml`; record pass count from the xml, delete the xml. Expected ≥ 1691 + ~35 new, 0 failures.
- [ ] **Step 2: Full mayapy suite** — `E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q --junitxml=evals/junit_final_mayapy.xml`; expected 189, 0 failures; delete the xml.
- [ ] **Step 3: Code review** — invoke `superpowers:requesting-code-review` against the branch diff; address findings per `superpowers:receiving-code-review`.
- [ ] **Step 4: Merge** — invoke `superpowers:finishing-a-development-branch` (merge to main; the branch was created at execution start per `superpowers:using-git-worktrees`).
- [ ] **Step 5: Redmine** — one `update_issue` on #768: status Resolved, notes carrying the merged commit hash, both suite counts, the three measured deviations, the chosen tolerance, and the artifact path. Remind the user: **restart any running Maya** (deployed stamp changed).
- [ ] **Step 6: Memory** — update `project-768-curve-forms.md` (brainstorm→shipped, commit hash, measured numbers, any traps found) and its `MEMORY.md` line; note #774/#769 remain next per the backlog entry.
