# Delivery Unit Truth — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every mesh deliverable out of this repo contains metre-magnitude vertices and no compensating node scale, proven by a headless check over the committed artifact that runs in the normal test suite.

**Architecture:** The defect is written by the FBX exporter, not present in the Maya scene, so every in-Maya gate is structurally blind to it. The gate therefore parses the exported FBX in pure Python — no Maya — which means it runs in the existing `pytest` suite over the committed `.fbx` files on every run, forever. A shared export preamble replaces the two divergent copies in the generators so there is one place the delivery unit is decided.

**Tech Stack:** Python 3 stdlib only for the checker (`struct`, `zlib`), pytest, Maya `maya.cmds`/`maya.mel` for the generators.

## Global Constraints

- **The checker must not import Maya.** It runs headless in CI against committed artifacts. Anything needing Maya belongs in the generator, not the checker.
- **Delivery invariant, exact:** an exported FBX must have (a) zero non-identity `Lcl Scaling` on any node, (b) every `Lcl Translation` component a multiple of `1.5` (the half-cell of the 3 m lattice) within `1e-3`, (c) largest absolute vertex coordinate under the per-delivery metre ceiling.
- **Metre ceilings, contract-derived — do not invent numbers:**
  - kit: `2.0` m = cell half-face `1.5` + outset allowance `0.5` (`demigol_kit.py` `H`)
  - heroes: `6.5` m = `MAX_RUN` 4 cells × 3 m ÷ 2 + outset `0.5`
- **Do not change `AUTOPROJ_UV_PER_METRE` (`100.0`) or the authoring unit.** Both are load-bearing for UV packing, and through it for the 6 courses/m brick pitch calibrated against Demigol's mipmaps-off import path. Re-opening that number is the outcome this plan exists to avoid.
- **`FBXExportScaleFactor` takes a bare float.** `FBXExportScaleFactor 100` — the `-v` form is a syntax error that fails silently inside the generators' existing `except Exception: pass`.
- Measured baselines the tests pin against (current, broken): kit `41` meshes all at scale `0.01`, largest coord `184.0`; tower `673` meshes, one Null at `0.01`, largest coord `647.0`; stump `174` meshes, largest coord `647.0`.

---

## File Structure

| File | Responsibility |
|---|---|
| `evals/fbx_probe.py` (create) | Pure-Python binary FBX reader. Knows the file format, knows nothing about Demigol. Returns nodes (name, type, translation, scaling) and geometry vertex arrays. |
| `evals/delivery_units.py` (create) | The policy. Given a parsed FBX and a metre ceiling, returns the list of invariant violations. Imports `fbx_probe`, not Maya. |
| `tests/test_delivery_units.py` (create) | Headless gate over the five committed delivery FBXs, plus unit tests for the reader and policy. |
| `evals/maya_export.py` (create) | The single shared Maya-side export preamble both generators call. One place the delivery unit is decided. |
| `evals/demigol_structures.py` (modify) | `EXPORT_CODE` replaced by the shared preamble; bake step added before export. |
| `evals/demigol_kit.py` (modify) | Same. |
| `evals/demigol_structures/manifest.json`, `evals/demigol_kit/manifest.json` (regenerate) | The `units` claim becomes true rather than aspirational. |

**Why the bake and not native metre authoring.** Two mechanisms reach the same artifact. Authoring natively at 1 unit = 1 m is more elegant in the scene but moves every UV, because `polyAutoProjection` output tracks internal size and `AUTOPROJ_UV_PER_METRE` is calibrated to a metre-internal scene — measured, `all_inside` flips between units. That puts the brick pitch and texel density back on the table. Baking the delivery unit into vertices *after* UVs are assigned leaves every calibrated number untouched, because freezing a uniform scale does not alter UVs. The gate in Task 2 makes the mechanism safe either way; this plan picks the one that cannot re-open a contract number.

---

### Task 1: The FBX reader

**Files:**
- Create: `evals/fbx_probe.py`
- Test: `tests/test_delivery_units.py`

**Interfaces:**
- Produces: `read_fbx(path) -> FbxFacts` where `FbxFacts` is a dataclass with fields
  `version: int`, `nodes: list[FbxNode]`, `meshes: list[tuple[float, ...]]` (flat xyz vertex arrays),
  `unit_scale_factor: float | None`.
  `FbxNode` is a dataclass with `name: str`, `kind: str`, `translation: tuple[float, float, float]`,
  `scaling: tuple[float, float, float]`.
- Node names in FBX carry a `\x00\x01` separator (`"tower\x00\x01Model"`); `name` must be the part before it.
- Absent `Lcl Scaling` / `Lcl Translation` records mean identity / origin, not missing data.

- [ ] **Step 1: Write the failing test**

Import style is not a free choice — follow `tests/test_demigol_generators.py:16-27`, which
puts `evals/` on `sys.path` and imports the modules flat. There is **no `evals/__init__.py`**,
so `from evals import ...` fails.

```python
# tests/test_delivery_units.py
import os
import sys
from pathlib import Path

import pytest

_EVALS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "evals")
if _EVALS not in sys.path:
    sys.path.insert(0, _EVALS)

import fbx_probe          # noqa: E402

REPO = Path(__file__).resolve().parents[1]
KIT = REPO / "evals" / "demigol_kit" / "demigol_kit.fbx"
TOWER = REPO / "evals" / "demigol_structures" / "tower.fbx"


def test_reader_finds_every_kit_mesh():
    facts = fbx_probe.read_fbx(KIT)
    assert facts.version == 7700
    assert len(facts.meshes) == 41


def test_reader_strips_the_fbx_name_separator():
    facts = fbx_probe.read_fbx(TOWER)
    names = [n.name for n in facts.nodes]
    assert "tower" in names, names[:5]
    assert not any("\x00" in n for n in names)


def test_reader_defaults_absent_records_to_identity():
    facts = fbx_probe.read_fbx(TOWER)
    # 673 chunks are written without an Lcl Scaling record; only the group Null
    # carries one. Absent must read as identity, never as missing.
    assert all(n.scaling == (1.0, 1.0, 1.0)
               for n in facts.nodes if n.name != "tower")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_delivery_units.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'evals.fbx_probe'`

- [ ] **Step 3: Write the reader**

Binary FBX layout: 27-byte header (`Kaydara FBX Binary`, version at offset 23), then nested node
records. Records use 64-bit offsets when version >= 7500. Each record is
`EndOffset, NumProperties, PropertyListLen` (u32 or u64 each), `NameLen` (u8), name, properties,
optional nested records, terminated by a null record. A zero `EndOffset` is the terminator.

Property typecodes: `C`(bool,1) `B`(u8,1) `Y`(i16,2) `I`(i32,4) `F`(f32,4) `D`(f64,8) `L`(i64,8);
`S`/`R` are u32 length + bytes; `f d l i c b` are arrays of
`ArrayLength(u32), Encoding(u32), CompressedLength(u32)` then payload, zlib-deflated when
`Encoding == 1`.

```python
# evals/fbx_probe.py
"""Read what an FBX actually contains, without Maya.

The unit defect this exists to catch is written by the FBX exporter and is not
present in the Maya scene, so no in-Maya check can see it. This reader is pure
stdlib on purpose: the gate has to run in the normal test suite, against the
committed artifact, on every run.
"""
import struct
import zlib
from dataclasses import dataclass, field
from typing import Optional

IDENTITY = (1.0, 1.0, 1.0)
ORIGIN = (0.0, 0.0, 0.0)


@dataclass
class FbxNode:
    name: str
    kind: str
    translation: tuple = ORIGIN
    scaling: tuple = IDENTITY


@dataclass
class FbxFacts:
    version: int
    nodes: list = field(default_factory=list)
    meshes: list = field(default_factory=list)
    unit_scale_factor: Optional[float] = None


def _clean(raw):
    # FBX writes "tower\x00\x01Model"; the object name is the part before it.
    return raw.split("\x00\x01")[0]


def read_fbx(path):
    with open(path, "rb") as fh:
        data = fh.read()
    if not data.startswith(b"Kaydara FBX Binary"):
        raise ValueError("%s is not a binary FBX" % path)

    version = struct.unpack_from("<I", data, 23)[0]
    wide = version >= 7500
    off_fmt = "<QQQ" if wide else "<III"
    off_size = 24 if wide else 12
    facts = FbxFacts(version=version)

    def prop(pos):
        code = data[pos:pos + 1]
        pos += 1
        simple = {b"C": ("<?", 1), b"B": ("<B", 1), b"Y": ("<h", 2), b"I": ("<i", 4),
                  b"F": ("<f", 4), b"D": ("<d", 8), b"L": ("<q", 8)}
        if code in simple:
            fmt, size = simple[code]
            return struct.unpack_from(fmt, data, pos)[0], pos + size
        if code in (b"S", b"R"):
            n = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            raw = data[pos:pos + n]
            val = raw.decode("utf-8", "replace") if code == b"S" else raw
            return val, pos + n
        if code in (b"f", b"d", b"l", b"i", b"c", b"b"):
            length, encoding, comp = struct.unpack_from("<III", data, pos)
            pos += 12
            payload = data[pos:pos + comp]
            pos += comp
            if code == b"d":
                raw = zlib.decompress(payload) if encoding == 1 else payload
                return struct.unpack("<%dd" % length, raw), pos
            return None, pos
        raise ValueError("unknown FBX typecode %r at %d" % (code, pos))

    def walk(pos, end, node):
        while pos < end:
            end_off, nprops, _plen = struct.unpack_from(off_fmt, data, pos)
            if end_off == 0:
                return pos + off_size + 1
            pos += off_size
            nlen = data[pos]
            pos += 1
            name = data[pos:pos + nlen].decode("utf-8", "replace")
            pos += nlen
            values = []
            for _ in range(nprops):
                val, pos = prop(pos)
                values.append(val)

            if name == "Vertices" and values and isinstance(values[0], tuple):
                facts.meshes.append(values[0])
            elif name == "P" and values and isinstance(values[0], str):
                key = values[0]
                if key == "UnitScaleFactor":
                    facts.unit_scale_factor = float(values[-1])
                elif node is not None and key in ("Lcl Scaling", "Lcl Translation"):
                    triple = tuple(float(v) for v in values[-3:])
                    if key == "Lcl Scaling":
                        node.scaling = triple
                    else:
                        node.translation = triple

            child = node
            if name == "Model":
                strs = [v for v in values if isinstance(v, str)]
                child = FbxNode(name=_clean(strs[0]) if strs else "?",
                                kind=strs[1] if len(strs) > 1 else "?")
                facts.nodes.append(child)
            if pos < end_off:
                walk(pos, end_off, child)
            pos = end_off
        return pos

    walk(27, len(data), None)
    return facts
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_delivery_units.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add evals/fbx_probe.py tests/test_delivery_units.py
git commit -m "test(evals): read FBX facts without Maya"
```

---

### Task 2: The invariant, proven red on the shipped files

This is the task the whole plan exists for. The check must be **seen failing against the
five committed FBXs** before anything is fixed. A green-on-arrival check is worth nothing —
that is precisely how this shipped three times.

**Files:**
- Create: `evals/delivery_units.py`
- Modify: `tests/test_delivery_units.py`

**Interfaces:**
- Consumes: `fbx_probe.read_fbx` from Task 1.
- Produces: `check_delivery(path, ceiling_m, lattice_m=1.5) -> list[str]` — human-readable
  violations, empty when the artifact is metre-true. Also `KIT_CEILING_M = 2.0`,
  `HERO_CEILING_M = 6.5`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_delivery_units.py
import delivery_units      # noqa: E402  (evals/ is already on sys.path above)

STRUCTURES = REPO / "evals" / "demigol_structures"
HEROES = ["tower", "block", "slab", "stump"]


@pytest.mark.parametrize("hero", HEROES)
def test_hero_is_metre_true(hero):
    violations = delivery_units.check_delivery(
        STRUCTURES / ("%s.fbx" % hero), delivery_units.HERO_CEILING_M)
    assert violations == [], "\n".join(violations)


def test_kit_is_metre_true():
    violations = delivery_units.check_delivery(
        KIT, delivery_units.KIT_CEILING_M)
    assert violations == [], "\n".join(violations)


def test_check_names_the_node_carrying_a_bad_scale(tmp_path):
    # The message has to identify the offending node, because the two
    # deliveries put the scale in different places: the heroes on one group
    # Null, the kit on all 41 Mesh nodes.
    violations = delivery_units.check_delivery(KIT, delivery_units.KIT_CEILING_M)
    assert any("kit_steel_column_a" in v for v in violations), violations
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_delivery_units.py -v`
Expected: FAIL — 5 of the 6 new tests red. The messages must name real measured numbers,
e.g. `tower: node 'tower' has scale (0.01, 0.01, 0.01), expected identity` and
`tower: largest vertex coordinate 647.0000 m exceeds ceiling 6.5 m — this is a x100 unit error`.
**Record the actual failure output in the commit message.** This is the evidence that the
gate can see the defect.

- [ ] **Step 3: Write the policy**

```python
# evals/delivery_units.py
"""The delivery unit invariant, checked against the artifact.


Three independent assertions, because each catches a different way of being
wrong and the delivery has historically satisfied some while failing others:

  scale     a compensating node scale makes a wrong vertex magnitude render
            correctly, which is how a 100x error shipped three times looking fine
  lattice   chunk translations sit on the 3 m grid, so in metres every component
            is a multiple of 1.5 and in centimetres a multiple of 150 - an exact
            unit test that needs no manifest
  ceiling   no vertex may exceed the contract's own envelope, in metres

Sibling import, not a package import: evals/ has no __init__.py and callers put
it on sys.path (see tests/test_demigol_generators.py).
"""
import fbx_probe

KIT_CEILING_M = 2.0     # cell half-face 1.5 + outset allowance 0.5
HERO_CEILING_M = 6.5    # MAX_RUN 4 cells x 3 m / 2 + outset 0.5
TOL = 1e-3


def check_delivery(path, ceiling_m, lattice_m=1.5):
    facts = fbx_probe.read_fbx(path)
    label = getattr(path, "name", str(path))
    out = []

    for node in facts.nodes:
        if any(abs(s - 1.0) > TOL for s in node.scaling):
            out.append(
                "%s: node %r has scale %s, expected identity - a compensating "
                "node scale hides a wrong vertex magnitude"
                % (label, node.name, tuple(round(s, 6) for s in node.scaling)))

    for node in facts.nodes:
        for axis, value in zip("xyz", node.translation):
            if value and abs(value / lattice_m - round(value / lattice_m)) > TOL:
                out.append(
                    "%s: node %r translation %s=%.4f is not a multiple of the "
                    "%.1f m half-cell - the file is not in metres"
                    % (label, node.name, axis, value, lattice_m))

    biggest = 0.0
    for verts in facts.meshes:
        for v in verts:
            if abs(v) > biggest:
                biggest = abs(v)
    if biggest > ceiling_m:
        out.append(
            "%s: largest vertex coordinate %.4f m exceeds ceiling %.1f m"
            % (label, biggest, ceiling_m)
            + (" - this is a x100 unit error" if biggest > ceiling_m * 50 else ""))

    return out
```

- [ ] **Step 4: Run to confirm it fails for the RIGHT reasons**

Run: `python -m pytest tests/test_delivery_units.py -v`
Expected: still FAIL on the five deliveries — this is correct and stays red until Task 4.
The three reader tests and `test_check_names_the_node_carrying_a_bad_scale` pass.
Confirm each failure message names a measured number, not a generic assertion.

- [ ] **Step 5: Commit the red gate**

```bash
git add evals/delivery_units.py tests/test_delivery_units.py
git commit -m "test(evals): gate delivery unit truth against the artifact

Red against all five shipped FBXs, which is the point: the equivalent
in-Maya assertion passes green on the same files, because the defect is
written by the exporter and is not present in the scene."
```

---

### Task 3: One shared export preamble

**Files:**
- Create: `evals/maya_export.py`
- Modify: `evals/demigol_structures.py:1055-1070`, `evals/demigol_kit.py:807-822`

**Interfaces:**
- Produces: `EXPORT_PREAMBLE` (str) — Maya-side Python, and `BAKE_TO_METRES` (str).
- Consumes: nothing from earlier tasks; the generators embed these strings in their
  `execute_python` payloads exactly as they embed `EXPORT_CODE` today.

The two generators currently hold divergent copies, and the divergence is load-bearing:
the heroes select one group (one Null gets the 0.01) while the kit selects 41 roots
(all 41 Meshes get it). One preamble removes the divergence.

- [ ] **Step 1: Write the module**

```python
# evals/maya_export.py
"""The single place the delivery unit is decided.

Measured facts this encodes, none of them guessable:

* `FBXExportConvertUnitString m` runs without error and does NOTHING. After it,
  the exporter still reports UnitsSelector=Centimeters, DynamicScaleConversion=1.
  Six combinations of selector and dynamic conversion produced byte-identical
  unit behaviour. It is removed rather than kept as decoration.
* `FBXExportScaleFactor` takes a BARE FLOAT. The `-v` form raises, and both
  generators swallowed that inside `except Exception: pass`.
* The factor MULTIPLIES the root node scale the exporter writes. The exporter
  always writes 0.01 there, so 100 cancels it to identity and the record is
  omitted. Confirmed by the reciprocal: factor 0.01 wrote 0.0001.
* Because the factor only cancels the node scale, the VERTICES must already be
  metre-magnitude - hence BAKE_TO_METRES must run first.
"""

# Scale the exported roots to metre magnitude and freeze, so the vertices
# themselves carry metres. Runs AFTER UVs are assigned and after the in-Maya
# checks: freezing a uniform scale does not touch UVs, and the checks are
# written against the metre-authored scene.
BAKE_TO_METRES = r'''
import maya.cmds as cmds
for _root in ROOTS:
    cmds.setAttr(_root + ".scale", 0.01, 0.01, 0.01, type="double3")
    cmds.makeIdentity(_root, apply=True, translate=False, rotate=False, scale=True)
'''

EXPORT_PREAMBLE = r'''
import maya.cmds as cmds
import maya.mel as mel
cmds.loadPlugin("fbxmaya", quiet=True)
mel.eval('FBXResetExport')
mel.eval('FBXExportFileVersion -v FBX202000')
mel.eval('FBXExportUpAxis y')
mel.eval('FBXExportInputConnections -v false')
mel.eval('FBXExportEmbeddedTextures -v false')
mel.eval('FBXExportScaleFactor 100')
'''
```

- [ ] **Step 2: Rewrite `EXPORT_CODE` in `evals/demigol_structures.py`**

Replace lines 1055-1070 with:

```python
EXPORT_CODE = maya_export.BAKE_TO_METRES + maya_export.EXPORT_PREAMBLE + r'''
cmds.select("|" + LABEL, replace=True, hierarchy=True)
cmds.file(FBX, force=True, type="FBX export", pr=True, es=True)
result = FBX
'''
```

Add `from evals import maya_export` to the imports, and ensure the caller passes
`ROOTS = ["|" + label]` into the payload namespace alongside `LABEL` and `FBX`.
Note the bare `except Exception: pass` around the old MEL block is deliberately gone —
it is what hid the `FBXExportScaleFactor` syntax error.

- [ ] **Step 3: Rewrite `EXPORT_CODE` in `evals/demigol_kit.py`**

Replace lines 807-822 with:

```python
EXPORT_CODE = maya_export.BAKE_TO_METRES + maya_export.EXPORT_PREAMBLE + r'''
cmds.select(NAMES, replace=True)
cmds.file(FBX, force=True, type="FBX export", pr=True, es=True)
result = FBX
'''
```

Add `from evals import maya_export`, and pass `ROOTS = NAMES` — the kit's 41 pieces are
each their own export root, which is why all 41 carry the scale today.

- [ ] **Step 4: Make the generator refuse to write a bad delivery**

The pytest gate catches a bad artifact *after* it is committed. The generator must refuse
to produce one at all — this is the "fatal" #629 asks for. In **both** generators, straight
after the export call returns the path:

```python
import delivery_units

violations = delivery_units.check_delivery(fbx_path, delivery_units.HERO_CEILING_M)
if violations:
    print("DELIVERY IS NOT METRE-TRUE - refusing to ship %s:" % fbx_path)
    for v in violations:
        print("    " + v)
    sys.exit(1)
```

Use `KIT_CEILING_M` in `demigol_kit.py`. Place it inside the per-building loop in
`main()` (`evals/demigol_structures.py:1157-1170`) so a partial run cannot pass either.

- [ ] **Step 5: Verify the fatal path actually fires**

Temporarily change `FBXExportScaleFactor 100` to `FBXExportScaleFactor 1` in
`evals/maya_export.py`, regenerate one hero, and confirm the generator exits non-zero
with the violation printed. Then change it back.
A guard never seen firing is a guard nobody knows works — that is the whole lesson of #629.

- [ ] **Step 6: Commit**

```bash
git add evals/maya_export.py evals/demigol_structures.py evals/demigol_kit.py
git commit -m "refactor(evals): one export preamble decides the delivery unit

The generator now refuses to write a delivery that is not metre-true,
verified by forcing the failure once."
```

---

### Task 4: Regenerate, and watch the gate go green

**Files:**
- Modify: `evals/demigol_structures/*.fbx`, `evals/demigol_kit/demigol_kit.fbx`, both `manifest.json`

Requires the user's live Maya. Per the repo's standing rule, the live run is the gate —
report measured numbers, never "should work".

- [ ] **Step 1: Regenerate the kit**

```bash
python evals/demigol_kit.py
```

Do **not** call `maya_new_scene` — `|stump|` is the user's own build and `|golemFeel|`
(29 chunks, at x = -20) must survive. Checkpoint `1000_pre_golem_feel` exists if recovery
is needed.

- [ ] **Step 2: Run the gate on the regenerated kit**

Run: `python -m pytest tests/test_delivery_units.py::test_kit_is_metre_true -v`
Expected: PASS. If it fails, read the message — it names the node and the measured number.

- [ ] **Step 3: Regenerate all four heroes in ONE invocation**

```bash
python evals/demigol_structures.py
```

No arguments — `main()` reads `sys.argv[1:]` as a filter (`evals/demigol_structures.py:1155`),
and naming a subset silently writes a manifest describing only the heroes that ran while
the other `.fbx` files sit stale beside it, still printing a clean check. Recorded as a
known trap at #600 note 1292.

- [ ] **Step 4: Run the full gate**

Run: `python -m pytest tests/test_delivery_units.py -v`
Expected: all pass, including the four heroes.

- [ ] **Step 5: Confirm the UVs did not move**

The whole reason for the bake-not-reauthor choice. Compare the regenerated kit's
`uv_min`/`uv_max` aggregates from `CHECK_CODE` against the pre-change values, and confirm
the contact sheet still reads as brick at 6 courses/m.
Expected: identical UV aggregates. Any drift means the bake ran before UV assignment.

- [ ] **Step 6: Make the manifest claim true, and gate it**

Both manifests state `units: "metres, Y-up, 1 unit = 1 m, cell = 3 m"`. Each hero entry
also carries `size_m` (`evals/demigol_structures.py:1166`). The artifact can now be
measured against the manifest's own claim, which is the direct closure of the
manifest-contradicts-artifact class Demigol #606 exists for. Add to
`tests/test_delivery_units.py`:

```python
import json

def test_hero_matches_the_size_its_manifest_declares():
    manifest = json.loads((STRUCTURES / "manifest.json").read_text())
    for entry in manifest["structures"]:
        facts = fbx_probe.read_fbx(STRUCTURES / ("%s.fbx" % entry["name"]))
        lo = [float("inf")] * 3
        hi = [float("-inf")] * 3
        for node, verts in zip(facts.nodes, facts.meshes):
            for i in range(0, len(verts), 3):
                for a in range(3):
                    v = verts[i + a] + node.translation[a]
                    lo[a] = min(lo[a], v)
                    hi[a] = max(hi[a], v)
        measured = [hi[a] - lo[a] for a in range(3)]
        declared = entry["size_m"]
        assert all(abs(m - d) < 0.05 for m, d in zip(measured, declared)), (
            "%s: manifest declares %s m, artifact measures %s m"
            % (entry["name"], declared, [round(m, 3) for m in measured]))
```

Note `zip(facts.nodes, facts.meshes)` assumes Model records and Geometry records appear in
the same order. **Verify that assumption holds** on one hero before trusting the test — if
it does not, key the pairing off the FBX `Connections` section instead. A test that pairs
the wrong mesh to the wrong translation would pass or fail for the wrong reason.

Confirm `geometry_self_check` in the manifest names the artifact-level check, so a reader
can tell the units claim is gated rather than asserted.

- [ ] **Step 7: Run the whole suite**

Run: `python -m pytest -q`
Expected: 752 passed / 1 skipped, plus the new tests. No regressions.

- [ ] **Step 8: Commit**

```bash
git add evals/demigol_structures evals/demigol_kit
git commit -m "fix(assets): the deliveries are metre-true in the vertices"
```

---

### Task 5: Verify the golem precedent, or retire it

Both the open-actions plan and maya-mcp #629 cite the golem blockout as the working
precedent for metre-true geometry. That claim rests on an **in-Maya** measurement — the
exact kind this plan proves blind — and there is no golem `.fbx` in the repo to check.
It is unverified, and an unverified precedent is how a standard drifts.

**Files:**
- Create: `evals/golem_run_2/golem_feel.fbx` (artifact)

- [ ] **Step 1: Export `|golemFeel|` through the new preamble**

Use `maya_export.BAKE_TO_METRES` + `EXPORT_PREAMBLE` with `ROOTS = ["|golemFeel|"]`.
Do not modify the live golem otherwise; it sits at x = -20 and the user's `|stump|` must
not be touched.

- [ ] **Step 2: Measure it**

```bash
python -m pytest tests/test_delivery_units.py -v -k golem
```

Add a test asserting the golem is metre-true against a ceiling of `4.5` m (the design's
4.0 m total height plus headroom), and asserting its measured height is `4.0 ± 0.05` m —
the number the design and #601 both depend on.

- [ ] **Step 3: Report the result honestly**

If it passes, the precedent is real and can be cited. If it fails, say so plainly and
correct #629 and the open-actions plan — the golem is the input to the whole motion
handoff, and a 100x error there would surface as physics that cannot be tuned.

- [ ] **Step 4: Commit**

```bash
git add evals/golem_run_2 tests/test_delivery_units.py
git commit -m "test(golem): measure the metre-true claim instead of citing it"
```

---

### Task 6: Write the coupling down

**Files:**
- Modify: `docs/superpowers/plans/2026-08-15-open-actions.md`

- [ ] **Step 1: Correct the record in the open-actions plan**

Section 1 prescribes an in-Maya `geometry_self_check` assertion as "the point". That is
now known to be insufficient — measured: the scene reads 3.0 m at scale [1,1,1] frozen and
exports as 300.0. Replace it with the artifact-level gate, and note that the existing
`scale == (1,1,1)` check at `demigol_structures.py:1009` already passed green on all three
broken ships.

- [ ] **Step 2: Record the FBX exporter facts**

`FBXExportConvertUnitString` is inert; `FBXExportScaleFactor` takes a bare float and
multiplies the root node scale. Both cost real measurement to establish and neither is
discoverable from the API docs.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/plans/2026-08-15-open-actions.md
git commit -m "docs: the unit gate has to read the artifact, not the scene"
```
