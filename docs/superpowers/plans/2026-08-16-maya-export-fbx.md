# `maya_export_fbx` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the MCP server a first-class FBX export tool that requires the unit decision explicitly, re-reads the bytes it just wrote, and deletes-and-raises rather than leave a wrong asset on disk.

**Architecture:** The FBX byte reader moves from `evals/fbx_probe.py` into the plugin as `maya_plugin/handlers/fbxbytes.py` (the file is written on the Maya machine's disk, so the check has to run there); `evals/fbx_probe.py` becomes a name re-export shim. A new `maya_plugin/handlers/export.py` holds the measured MEL preamble as data, runs validate → export → patch `UnitScaleFactor` → re-read → gate, and unlinks on any violation. `evals/maya_export.py` composes its existing `EXPORT_PREAMBLE` from that same data, so the three delivery generators are untouched and need no art run.

**Tech Stack:** Python 3, pytest, Maya `maya.cmds` / `maya.mel` (plugin side only), FastMCP + Pydantic (server side), pure-stdlib `struct`/`zlib` for the byte reader.

Spec: [`docs/superpowers/specs/2026-08-16-maya-export-fbx-design.md`](../specs/2026-08-16-maya-export-fbx-design.md). Redmine **#642**.

## Global Constraints

- **No new dependencies.** `maya_plugin/handlers/fbxbytes.py` and the module level of `maya_plugin/handlers/export.py` must be pure stdlib.
- **`maya.cmds` / `maya.mel` are imported inside functions, never at module level** — every handler uses the `_cmds()` pattern. `evals/maya_export.py` imports `maya_plugin.handlers.export` outside Maya and this is what makes that legal.
- **`metres_per_unit` is required, has no default, and only `1.0` proceeds.** Anything else raises.
- **Refuse, don't warn.** No `strict=false`, no "exported with warnings". A file that fails the gate is unlinked before the handler raises.
- **The gate is exactly two assertions:** every node scale is identity (tolerance `1e-3`), and `UnitScaleFactor == 100.0`. Do **not** add the one-root rule (the demigol kit legitimately exports 41 roots) or the lattice/ceiling checks (those are per-delivery contract envelopes and stay in `evals/`).
- **FBX only.** No OBJ, no USD.
- **`EXPORT_SCALE_FACTOR = 1.0`** and the five preamble statements are measured facts, not choices. Do not add `FBXExportConvertUnitString` (it runs and does nothing) and do not use the `-v` form of `FBXExportScaleFactor` (it raises).
- **`evals/maya_export.py`'s `EXPORT_PREAMBLE` must stay byte-identical** to what it is today. Task 2 pins this with a test.
- Every new module starts with `from __future__ import annotations`, matching the rest of `maya_plugin/`.

## File Structure

| file | responsibility |
|---|---|
| `maya_plugin/handlers/fbxbytes.py` | **Create** (moved). Pure-stdlib FBX reader/patcher. Unchanged content. |
| `evals/fbx_probe.py` | **Replace** with a name re-export shim. Six consumers depend on it. |
| `maya_plugin/handlers/export.py` | **Create.** Preamble data, `gate_violations`, `_validate`, `export_fbx`. |
| `evals/maya_export.py` | **Modify.** Compose `EXPORT_PREAMBLE`/`EXPORT_SCALE_FACTOR` from the handler. |
| `maya_plugin/maya_mcp_plugin.py` | **Modify.** Import `export`, register `"export_fbx"`. |
| `src/maya_mcp/schemas.py` | **Modify.** Add `ExportFbxResult`. |
| `src/maya_mcp/server.py` | **Modify.** Add `EXPORT_TIMEOUT_S` and the `maya_export_fbx` tool. |
| `tests/test_export_fbx.py` | **Create.** Gate logic, validation, preamble pin, real-artifact check. |
| `evals/export_live.py` | **Create.** The live gate — measured numbers from a real Maya. |

---

### Task 1: Promote the byte reader into the plugin

**Files:**
- Create: `maya_plugin/handlers/fbxbytes.py` (git mv from `evals/fbx_probe.py`)
- Modify: `evals/fbx_probe.py` (becomes a shim)
- Test: `tests/test_export_fbx.py` (created here)

**Interfaces:**
- Consumes: nothing.
- Produces: `maya_plugin.handlers.fbxbytes` exporting `FbxNode`, `FbxFacts`, `read_fbx(path)`, `world_vertex_bounds(facts, rotations=None)`, `set_unit_scale_factor(path, value=DECLARES_METRES)`, `DECLARES_METRES = 100.0`, `IDENTITY`, `ORIGIN`. `evals/fbx_probe.py` re-exports all of them under the same names.

- [ ] **Step 1: Write the failing test**

Create `tests/test_export_fbx.py`:

```python
"""maya-mcp #642: the export tool, and the gate it runs on its own bytes.

Nothing here imports Maya. The handler's Maya calls are faked, because the
point of this suite is the logic that decides whether a written file is
allowed to survive - and that logic must be checkable without a Maya licence.
"""
import os
import sys
from pathlib import Path

import pytest

_EVALS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "evals")
if _EVALS not in sys.path:
    sys.path.insert(0, _EVALS)

import fbx_probe                                    # noqa: E402
from maya_plugin.handlers import fbxbytes           # noqa: E402

REPO = Path(__file__).resolve().parents[1]
GOLEM = REPO / "evals" / "golem_delivery" / "golem.fbx"


def test_the_reader_lives_in_the_plugin_now():
    # It has to: maya_export_fbx reads back a file on the MAYA machine's disk,
    # and the server cannot assume it shares that filesystem.
    facts = fbxbytes.read_fbx(GOLEM)
    assert facts.unit_scale_factor == fbxbytes.DECLARES_METRES


def test_the_eval_shim_is_the_same_names():
    # evals/delivery_units.py resolves fbx_probe.read_fbx as an ATTRIBUTE at
    # call time and tests/test_delivery_units.py monkeypatches it in seven
    # places, so patch and lookup have to land on the same module object.
    for name in ("read_fbx", "world_vertex_bounds", "set_unit_scale_factor",
                 "FbxNode", "FbxFacts", "DECLARES_METRES"):
        assert getattr(fbx_probe, name) is getattr(fbxbytes, name), name


def test_the_shim_stays_patchable(monkeypatch):
    import delivery_units
    sentinel = fbxbytes.FbxFacts(version=7700, nodes=[], meshes=[],
                                 unit_scale_factor=fbxbytes.DECLARES_METRES)
    monkeypatch.setattr(fbx_probe, "read_fbx", lambda _p: sentinel)
    assert delivery_units.check_delivery("ignored.fbx", ceiling_m=2.0) == []
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_export_fbx.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'maya_plugin.handlers.fbxbytes'`.

- [ ] **Step 3: Move the file**

```bash
git mv evals/fbx_probe.py maya_plugin/handlers/fbxbytes.py
```

Do **not** edit its contents. It is already pure stdlib (`math`, `struct`, `zlib`, `dataclasses`, `typing`) and imports nothing from `evals/`.

- [ ] **Step 4: Write the shim**

Create `evals/fbx_probe.py`:

```python
"""Compatibility shim: the FBX byte reader now lives in the plugin.

Moved to maya_plugin/handlers/fbxbytes.py for maya-mcp #642, because
maya_export_fbx has to read back the bytes it just wrote and those bytes are on
the MAYA machine's disk, where only the plugin runs. Nothing about the reader
changed; this module exists so the six callers in evals/ and tests/ did not
have to.

Re-exported by NAME on purpose. evals/delivery_units.py resolves
`fbx_probe.read_fbx` as an attribute at call time and tests/test_delivery_units.py
monkeypatches it, so the patch and the lookup must land on THIS module object.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maya_plugin.handlers.fbxbytes import (  # noqa: E402,F401 - re-export
    DECLARES_METRES,
    IDENTITY,
    ORIGIN,
    FbxFacts,
    FbxNode,
    read_fbx,
    set_unit_scale_factor,
    world_vertex_bounds,
)
```

- [ ] **Step 5: Run the new test and the whole existing suite**

```bash
python -m pytest tests/test_export_fbx.py tests/test_delivery_units.py -v
```

Expected: PASS, including all of `test_delivery_units.py` (its seven monkeypatches are the reason the shim re-exports names).

```bash
python -m pytest -q
```

Expected: the full suite still green — 819 passed, 1 skipped before this change, and no fewer after.

- [ ] **Step 6: Commit**

```bash
git add maya_plugin/handlers/fbxbytes.py evals/fbx_probe.py tests/test_export_fbx.py
git commit -m "refactor(export): move the FBX byte reader into the plugin (#642)"
```

---

### Task 2: The preamble becomes data, with one definition

**Files:**
- Create: `maya_plugin/handlers/export.py`
- Modify: `evals/maya_export.py:50-70`
- Test: `tests/test_export_fbx.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `maya_plugin.handlers.export.FBX_PREAMBLE_MEL` (a `tuple` of five MEL statement strings), `export.EXPORT_SCALE_FACTOR = 1.0`, `export.SCALE_TOL = 1e-3`. `evals/maya_export.py` keeps exporting `EXPORT_PREAMBLE` (str) and `EXPORT_SCALE_FACTOR` (float) with byte-identical values.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_export_fbx.py`:

```python
import maya_export                                  # noqa: E402
from maya_plugin.handlers import export             # noqa: E402

# Copied verbatim from evals/maya_export.py as it stood at commit 7df1863,
# BEFORE this task rewrote it. This literal is the contract: demigol_kit.py,
# demigol_structures.py and units_live.py all ship their deliveries through
# this exact string, and re-validating a change to it would cost a live art
# run. Composing it from the handler is only safe because this assertion
# proves the composition produced the same bytes.
SHIPPED_PREAMBLE = (
    "\n"
    "import maya.cmds as cmds\n"
    "import maya.mel as mel\n"
    'cmds.loadPlugin("fbxmaya", quiet=True)\n'
    "mel.eval('FBXResetExport')\n"
    "mel.eval('FBXExportFileVersion -v FBX202000')\n"
    "mel.eval('FBXExportUpAxis y')\n"
    "mel.eval('FBXExportInputConnections -v false')\n"
    "mel.eval('FBXExportEmbeddedTextures -v false')\n"
    "mel.eval('FBXExportScaleFactor %g' % EXPORT_SCALE_FACTOR)\n"
)


def test_the_composed_preamble_is_byte_identical():
    assert maya_export.EXPORT_PREAMBLE == SHIPPED_PREAMBLE


def test_the_scale_factor_has_one_definition():
    assert maya_export.EXPORT_SCALE_FACTOR is export.EXPORT_SCALE_FACTOR
    assert export.EXPORT_SCALE_FACTOR == 1.0


def test_the_dead_end_is_not_in_the_preamble():
    # FBXExportConvertUnitString runs without error and does NOTHING - six
    # selector/dynamic-conversion combinations were byte-identical. It must not
    # come back as decoration.
    assert not any("ConvertUnit" in s for s in export.FBX_PREAMBLE_MEL)
    # And the -v form of the scale factor RAISES; both generators used to
    # swallow that inside `except Exception: pass`.
    assert not any(s.startswith("FBXExportScaleFactor") for s in export.FBX_PREAMBLE_MEL)


def test_the_handler_module_imports_outside_maya():
    # evals/maya_export.py imports it from a plain interpreter. If anything
    # moves `import maya.cmds` to module level, that breaks all three delivery
    # generators at import time.
    assert export.FBX_PREAMBLE_MEL[0] == "FBXResetExport"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_export_fbx.py -v -k "preamble or scale_factor or dead_end or outside_maya"
```

Expected: FAIL — `ModuleNotFoundError: No module named 'maya_plugin.handlers.export'`.

- [ ] **Step 3: Create the handler module with the preamble data**

Create `maya_plugin/handlers/export.py`:

```python
"""FBX export, gated on the bytes it just wrote (maya-mcp #642).

The unit decision is the one most likely to ship a broken asset and it used to
live outside the server, in a MEL preamble pasted through execute_python. It
lives here now.

Everything this module knows about the FBX exporter was measured, not read in a
manual - see evals/maya_export.py's docstring for what each line cost:

* Maya's internal linear unit is centimetres whatever `currentUnit` reports,
  and the exporter writes those internal numbers.
* `FBXExportScaleFactor` only MULTIPLIES the root node scale the exporter
  writes. It can never change vertex magnitude, so it cannot rescue a scene
  that is the wrong size - it can only add the compensating scale that makes a
  wrong file render correctly. That is the #629 defect, and the gate below
  rejects exactly that.
* Maya writes `UnitScaleFactor 1.0` for a metre-native scene and offers no way
  to change it, so the declaration is patched in the bytes afterwards.

Nothing at module level imports Maya: evals/maya_export.py imports this from a
plain interpreter to compose the preamble its generators still use.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from ..dispatcher import HandlerError
from . import fbxbytes

# The five statements, in order, with FBXResetExport first so no setting from a
# previous export survives. Held as data rather than a code blob so
# evals/maya_export.py can compose its string from this and no second copy
# exists - the divergence between two copies of this preamble was load-bearing
# once already.
FBX_PREAMBLE_MEL: Tuple[str, ...] = (
    "FBXResetExport",
    "FBXExportFileVersion -v FBX202000",
    "FBXExportUpAxis y",
    "FBXExportInputConnections -v false",
    "FBXExportEmbeddedTextures -v false",
)

# Once the scene is metre-native there is no unit conversion left to make, so
# the exporter writes no compensating node and the factor must be 1. Measured
# both ways: at 100 the heroes' group Null came back at scale (100,100,100).
EXPORT_SCALE_FACTOR = 1.0

SCALE_TOL = 1e-3
```

- [ ] **Step 4: Compose the eval preamble from it**

In `evals/maya_export.py`, replace the `EXPORT_PREAMBLE` and `EXPORT_SCALE_FACTOR` definitions (currently lines 50-70) with:

```python
# One definition, composed. The statements and the factor live in
# maya_plugin/handlers/export.py, which is what maya_export_fbx runs - so this
# preamble and the tool cannot drift apart. tests/test_export_fbx.py pins the
# composed string byte-for-byte against what the generators shipped, because
# re-validating a change here would cost a live art run.
#
# The three consumers - evals/demigol_kit.py, evals/demigol_structures.py and
# evals/units_live.py - prepend their own `EXPORT_SCALE_FACTOR = ...` line, so
# the last statement stays a runtime substitution rather than a baked number.
EXPORT_SCALE_FACTOR = _export.EXPORT_SCALE_FACTOR

EXPORT_PREAMBLE = "\n".join(
    ["",
     "import maya.cmds as cmds",
     "import maya.mel as mel",
     'cmds.loadPlugin("fbxmaya", quiet=True)']
    + ["mel.eval(%r)" % statement for statement in _export.FBX_PREAMBLE_MEL]
    + ["mel.eval('FBXExportScaleFactor %g' % EXPORT_SCALE_FACTOR)",
       ""]
)
```

and add the import at the top of `evals/maya_export.py`, immediately after the module docstring:

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from maya_plugin.handlers import export as _export  # noqa: E402
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
python -m pytest tests/test_export_fbx.py -v
```

Expected: PASS, in particular `test_the_composed_preamble_is_byte_identical`.

Then prove the three generators still import and still see the same string:

```bash
python -c "import sys; sys.path.insert(0,'evals'); import maya_export; print(repr(maya_export.EXPORT_PREAMBLE)); print(maya_export.EXPORT_SCALE_FACTOR)"
```

Expected: the repr matches `SHIPPED_PREAMBLE` in the test, and `1.0`.

- [ ] **Step 6: Commit**

```bash
git add maya_plugin/handlers/export.py evals/maya_export.py tests/test_export_fbx.py
git commit -m "refactor(export): the preamble becomes data with one definition (#642)"
```

---

### Task 3: The gate

**Files:**
- Modify: `maya_plugin/handlers/export.py`
- Test: `tests/test_export_fbx.py`

**Interfaces:**
- Consumes: `fbxbytes.FbxFacts`, `fbxbytes.FbxNode`, `fbxbytes.DECLARES_METRES`, `export.SCALE_TOL` (Tasks 1-2).
- Produces: `export.gate_violations(facts) -> List[str]` — empty list means the file may survive.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_export_fbx.py`:

```python
def _facts(nodes=(), unit=None):
    return fbxbytes.FbxFacts(
        version=7700, nodes=list(nodes), meshes=[],
        unit_scale_factor=fbxbytes.DECLARES_METRES if unit is None else unit)


def test_a_clean_file_has_no_violations():
    node = fbxbytes.FbxNode(name="golem_C_pelvis", kind="Mesh", uid=1)
    assert export.gate_violations(_facts([node])) == []


def test_a_compensating_node_scale_is_a_violation():
    # The exact shape of maya-mcp #629: vertices 100x too large, a 0.01 on the
    # root, and the prefab renders correctly while the bare mesh does not.
    node = fbxbytes.FbxNode(name="kit_root", kind="Null", uid=1,
                            scaling=(0.01, 0.01, 0.01))
    violations = export.gate_violations(_facts([node]))
    assert len(violations) == 1
    assert "kit_root" in violations[0]
    assert "identity" in violations[0]


def test_a_wrong_declaration_is_a_violation():
    violations = export.gate_violations(_facts(unit=1.0))
    assert len(violations) == 1
    assert "UnitScaleFactor" in violations[0]


def test_forty_one_roots_is_not_a_violation():
    # The one-root rule belongs to check_rig_delivery. The demigol kit exports
    # 41 roots and is correct; a universal gate that rejected it would be wrong.
    nodes = [fbxbytes.FbxNode(name="kit_piece_%02d" % i, kind="Mesh", uid=i)
             for i in range(41)]
    assert export.gate_violations(_facts(nodes)) == []


def test_a_big_vertex_is_not_this_gates_business():
    # The ceiling is a per-delivery contract envelope and stays in evals/.
    facts = _facts([fbxbytes.FbxNode(name="tower", kind="Mesh", uid=1)])
    facts.meshes = [(0.0, 0.0, 0.0, 900.0, 900.0, 900.0)]
    assert export.gate_violations(facts) == []


def test_the_shipped_golem_passes_the_gate():
    # A real 33-chunk artifact, committed. If this ever fails, either the gate
    # is wrong or a delivery regressed - both worth stopping for.
    assert export.gate_violations(fbxbytes.read_fbx(GOLEM)) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m pytest tests/test_export_fbx.py -v -k "violation or roots or gate or business"
```

Expected: FAIL with `AttributeError: module 'maya_plugin.handlers.export' has no attribute 'gate_violations'`.

- [ ] **Step 3: Implement the gate**

Append to `maya_plugin/handlers/export.py`:

```python
def gate_violations(facts) -> List[str]:
    """Ways the written file breaks the export invariant, as readable strings.

    Two assertions, and only two, because these are the two that hold for EVERY
    export this server can be asked to make:

      scale        a compensating node scale makes a wrong vertex magnitude
                   render correctly, which is how three revisions shipped at
                   100x with every in-Maya check green (#596, #600, #629)
      declaration  metre-magnitude vertices declared as centimetres is the same
                   defect inverted, and a consumer measures unit scale on import

    Deliberately absent, though evals/delivery_units.py checks them: the
    one-root rule (a RIG rule - the demigol kit legitimately exports 41 roots)
    and the lattice/ceiling checks (per-delivery contract envelopes, not
    properties of a correct export). This tool asserts what it is responsible
    for; the delivery gates keep asserting what they are, against the same bytes.
    """
    out: List[str] = []
    for node in facts.nodes:
        if any(abs(s - 1.0) > SCALE_TOL for s in node.scaling):
            out.append(
                "node %r has scale %s, expected identity - a compensating node "
                "scale hides a wrong vertex magnitude"
                % (node.name, tuple(round(s, 6) for s in node.scaling)))
    if facts.unit_scale_factor != fbxbytes.DECLARES_METRES:
        out.append(
            "the file declares UnitScaleFactor %r, expected %g - the vertices "
            "are metres, so the file would contradict itself"
            % (facts.unit_scale_factor, fbxbytes.DECLARES_METRES))
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_export_fbx.py -v
```

Expected: PASS, all of them.

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/export.py tests/test_export_fbx.py
git commit -m "feat(export): the gate - identity scales and an honest declaration (#642)"
```

---

### Task 4: Parameter validation

**Files:**
- Modify: `maya_plugin/handlers/export.py`
- Test: `tests/test_export_fbx.py`

**Interfaces:**
- Consumes: `HandlerError`, `export.SCALE_TOL`.
- Produces: `export._validate(params) -> Tuple[str, Optional[List[str]]]` returning `(normalised_forward_slash_path, nodes_or_None)`. Raises `HandlerError` otherwise.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_export_fbx.py`:

```python
from maya_plugin.dispatcher import HandlerError    # noqa: E402


def _params(tmp_path, **over):
    out = {"path": str(tmp_path / "out.fbx"), "metres_per_unit": 1.0}
    out.update(over)
    return out


def test_a_good_call_normalises_the_path(tmp_path):
    path, nodes = export._validate(_params(tmp_path))
    assert path.endswith("/out.fbx")
    assert "\\" not in path
    assert nodes is None


def test_metres_per_unit_has_no_default(tmp_path):
    params = _params(tmp_path)
    del params["metres_per_unit"]
    with pytest.raises(HandlerError) as exc:
        export._validate(params)
    assert "metres_per_unit" in str(exc.value)
    # The hint must say WHY there is no default, or the next caller invents one.
    assert "629" in (exc.value.hint or "")


def test_a_hundred_metres_per_unit_is_refused_not_converted(tmp_path):
    with pytest.raises(HandlerError) as exc:
        export._validate(_params(tmp_path, metres_per_unit=100.0))
    assert "only 1.0" in str(exc.value)
    # Refused, not fixed: the only way to "convert" is the compensating root
    # scale, which is the defect. The hint has to point at baking instead.
    assert "freeze" in (exc.value.hint or "")


@pytest.mark.parametrize("bad", [None, "1.0", True, [1.0]])
def test_metres_per_unit_must_be_a_number(tmp_path, bad):
    with pytest.raises(HandlerError):
        export._validate(_params(tmp_path, metres_per_unit=bad))


def test_the_path_must_be_an_fbx(tmp_path):
    with pytest.raises(HandlerError) as exc:
        export._validate(_params(tmp_path, path=str(tmp_path / "out.obj")))
    assert ".fbx" in str(exc.value)


def test_the_path_must_be_absolute(tmp_path):
    with pytest.raises(HandlerError) as exc:
        export._validate(_params(tmp_path, path="out.fbx"))
    assert "absolute" in str(exc.value)


def test_a_missing_directory_is_refused(tmp_path):
    with pytest.raises(HandlerError) as exc:
        export._validate(_params(tmp_path, path=str(tmp_path / "nope" / "out.fbx")))
    assert "does not exist" in str(exc.value)


def test_an_empty_node_list_is_refused(tmp_path):
    # [] would silently export nothing; omitting the param means "everything".
    with pytest.raises(HandlerError) as exc:
        export._validate(_params(tmp_path, nodes=[]))
    assert "omit" in (exc.value.hint or "")


def test_a_node_list_survives_validation(tmp_path):
    _path, nodes = export._validate(_params(tmp_path, nodes=["golem_C_pelvis"]))
    assert nodes == ["golem_C_pelvis"]
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m pytest tests/test_export_fbx.py -v -k "validate or metres_per_unit or path_must or directory or node_list"
```

Expected: FAIL with `AttributeError: module 'maya_plugin.handlers.export' has no attribute '_validate'`.

- [ ] **Step 3: Implement validation**

Append to `maya_plugin/handlers/export.py`:

```python
def _validate(params: Dict[str, Any]) -> Tuple[str, Optional[List[str]]]:
    """Check every parameter before touching Maya. A bad call must cost nothing."""
    path = params.get("path")
    if not isinstance(path, str) or not path.strip():
        raise HandlerError(
            "missing required param 'path'",
            hint="pass an absolute path ending in .fbx, e.g. "
                 "path='D:/deliver/golem.fbx'")
    path = path.strip().replace("\\", "/")
    if not path.lower().endswith(".fbx"):
        raise HandlerError(
            "path %r must end in .fbx" % path,
            hint="this tool writes FBX only")
    if not os.path.isabs(path):
        raise HandlerError(
            "path %r must be absolute" % path,
            hint="a relative path resolves against Maya's working directory, "
                 "which is not the directory you ran anything from")
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        raise HandlerError(
            "the directory %r does not exist" % parent,
            hint="create it first - this tool does not make directories it was "
                 "not asked to make")

    if params.get("metres_per_unit") is None:
        raise HandlerError(
            "missing required param 'metres_per_unit'",
            hint="pass metres_per_unit=1.0. It has NO default on purpose: a "
                 "guess about what one unit means is exactly what shipped three "
                 "deliveries at 100x (maya-mcp #629), and no in-Maya check can "
                 "see that defect")
    mpu = params["metres_per_unit"]
    if isinstance(mpu, bool) or not isinstance(mpu, (int, float)):
        raise HandlerError(
            "metres_per_unit must be a number, got %r" % (mpu,),
            hint="pass metres_per_unit=1.0")
    if abs(float(mpu) - 1.0) > SCALE_TOL:
        raise HandlerError(
            "metres_per_unit=%g is refused; only 1.0 exports" % mpu,
            hint="this is not a conversion the exporter can make. "
                 "FBXExportScaleFactor only multiplies the root node scale, so "
                 "the vertices would stay the wrong size and the file would "
                 "carry the compensating scale this tool rejects. Scale the "
                 "geometry and freeze it so one unit means one metre, then "
                 "export with metres_per_unit=1.0")

    nodes = params.get("nodes")
    if nodes is not None:
        if not isinstance(nodes, list) or not all(isinstance(n, str) for n in nodes):
            raise HandlerError(
                "nodes must be a list of object names",
                hint="e.g. nodes=['golem_C_pelvis'], or omit it to export "
                     "the whole scene")
        if not nodes:
            raise HandlerError(
                "nodes is an empty list, which would export nothing",
                hint="omit nodes entirely to export the whole scene")
    return path, nodes
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_export_fbx.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/export.py tests/test_export_fbx.py
git commit -m "feat(export): validation - metres_per_unit is required and 1.0 only (#642)"
```

---

### Task 5: The handler — export, patch, re-read, refuse

**Files:**
- Modify: `maya_plugin/handlers/export.py`
- Modify: `maya_plugin/maya_mcp_plugin.py:25-40` (import) and `:98` (handler map)
- Test: `tests/test_export_fbx.py`

**Interfaces:**
- Consumes: `_validate`, `gate_violations`, `FBX_PREAMBLE_MEL`, `EXPORT_SCALE_FACTOR`, `fbxbytes`.
- Produces: `export.export_fbx(params) -> Dict[str, Any]` with keys `path`, `bytes`, `fbx_version`, `node_count`, `mesh_count`, `root_nodes`, `unit_scale_factor`, `metres_per_unit`, `world_bounds_min`, `world_bounds_max`, `height_m`. Registered as command `"export_fbx"`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_export_fbx.py`:

```python
class FakeCmds:
    """Just enough Maya to drive the handler: record the calls, write a file."""

    def __init__(self, existing=("golem_C_pelvis",)):
        self.existing = set(existing)
        self.calls = []

    def loadPlugin(self, name, quiet=False):
        self.calls.append(("loadPlugin", name))

    def objExists(self, name):
        return name in self.existing

    def select(self, names, replace=False):
        self.calls.append(("select", names))

    def file(self, path, **kw):
        self.calls.append(("file", path, kw))
        with open(path, "wb") as fh:
            fh.write(b"not really an fbx")


class FakeMel:
    def __init__(self):
        self.evaluated = []

    def eval(self, statement):
        self.evaluated.append(statement)


def _install(monkeypatch, cmds, facts, mel=None):
    mel = mel or FakeMel()
    monkeypatch.setattr(export, "_cmds", lambda: cmds)
    monkeypatch.setattr(export, "_mel", lambda: mel)
    monkeypatch.setattr(export.fbxbytes, "set_unit_scale_factor",
                        lambda _p, value=100.0: value)
    monkeypatch.setattr(export.fbxbytes, "read_fbx", lambda _p: facts)
    return mel


def test_a_clean_export_reports_the_file_not_the_scene(monkeypatch, tmp_path):
    node = fbxbytes.FbxNode(name="golem_C_pelvis", kind="Mesh", uid=1, geometry=7)
    facts = _facts([node])
    facts.meshes = [(0.0, 0.0, 0.0, 1.0, 4.02173, 1.0)]
    facts.geometries = {7: facts.meshes[0]}
    cmds = FakeCmds()
    mel = _install(monkeypatch, cmds, facts)

    out = export.export_fbx({"path": str(tmp_path / "golem.fbx"),
                             "metres_per_unit": 1.0})

    assert out["fbx_version"] == 7700
    assert out["node_count"] == 1
    assert out["root_nodes"] == ["golem_C_pelvis"]
    assert out["unit_scale_factor"] == 100.0
    assert out["metres_per_unit"] == 1.0
    assert out["bytes"] == len(b"not really an fbx")
    assert abs(out["height_m"] - 4.02173) < 1e-6
    # The measured preamble ran, in order, with the factor last.
    assert mel.evaluated == list(export.FBX_PREAMBLE_MEL) + ["FBXExportScaleFactor 1"]


def test_a_violating_file_is_deleted_not_returned(monkeypatch, tmp_path):
    bad = fbxbytes.FbxNode(name="kit_root", kind="Null", uid=1,
                           scaling=(0.01, 0.01, 0.01))
    path = tmp_path / "bad.fbx"
    _install(monkeypatch, FakeCmds(), _facts([bad]))

    with pytest.raises(HandlerError) as exc:
        export.export_fbx({"path": str(path), "metres_per_unit": 1.0})

    assert "kit_root" in str(exc.value)
    assert not path.exists(), "a file that fails the gate must not reach a delivery"


def test_exporting_named_nodes_selects_them(monkeypatch, tmp_path):
    cmds = FakeCmds()
    _install(monkeypatch, cmds, _facts([]))
    export.export_fbx({"path": str(tmp_path / "one.fbx"), "metres_per_unit": 1.0,
                       "nodes": ["golem_C_pelvis"]})
    assert ("select", ["golem_C_pelvis"]) in cmds.calls
    kw = [c for c in cmds.calls if c[0] == "file"][0][2]
    assert kw.get("es") is True and "ea" not in kw


def test_exporting_everything_does_not_select(monkeypatch, tmp_path):
    cmds = FakeCmds()
    _install(monkeypatch, cmds, _facts([]))
    export.export_fbx({"path": str(tmp_path / "all.fbx"), "metres_per_unit": 1.0})
    assert not any(c[0] == "select" for c in cmds.calls)
    kw = [c for c in cmds.calls if c[0] == "file"][0][2]
    assert kw.get("ea") is True and "es" not in kw


def test_an_unknown_node_fails_before_writing_anything(monkeypatch, tmp_path):
    cmds = FakeCmds()
    _install(monkeypatch, cmds, _facts([]))
    path = tmp_path / "ghost.fbx"
    with pytest.raises(HandlerError) as exc:
        export.export_fbx({"path": str(path), "metres_per_unit": 1.0,
                           "nodes": ["no_such_thing"]})
    assert "no_such_thing" in str(exc.value)
    assert not path.exists()


def test_the_command_is_registered():
    from maya_plugin import maya_mcp_plugin
    assert maya_mcp_plugin._build_handlers()["export_fbx"] is export.export_fbx
```

`_build_handlers()` is the private factory at `maya_plugin/maya_mcp_plugin.py:81` that returns
the command map. Calling it imports no Maya, so this test runs headless.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m pytest tests/test_export_fbx.py -v -k "clean_export or violating or named_nodes or everything or unknown_node or registered"
```

Expected: FAIL with `AttributeError: module 'maya_plugin.handlers.export' has no attribute '_cmds'`.

- [ ] **Step 3: Implement the handler**

Append to `maya_plugin/handlers/export.py`:

```python
def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _mel():
    import maya.mel as mel  # noqa: PLC0415 - only importable inside Maya

    return mel


def _bounds(facts):
    """World bounds and height from the FILE, or None when it holds no geometry.

    fbxbytes._rotation implements only the default XYZ euler order and raises
    otherwise - deliberately, since a wrong assumption would move geometry
    silently. That must not fail an export whose bytes already passed the gate,
    so a rotation order the reader cannot compose costs the measurement, not
    the file.
    """
    try:
        lo, hi = fbxbytes.world_vertex_bounds(facts)
    except ValueError:
        return None, None, None
    if any(v == float("inf") for v in lo):
        return None, None, None
    return list(lo), list(hi), hi[1] - lo[1]


def export_fbx(params: Dict[str, Any]) -> Dict[str, Any]:
    path, nodes = _validate(params)
    cmds = _cmds()
    mel = _mel()

    if nodes:
        missing = [n for n in nodes if not cmds.objExists(n)]
        if missing:
            raise HandlerError(
                "no such object(s): %s" % ", ".join(missing[:6]),
                hint="names are case-sensitive; maya_get_scene_graph lists what "
                     "the scene actually contains")

    cmds.loadPlugin("fbxmaya", quiet=True)
    for statement in FBX_PREAMBLE_MEL:
        mel.eval(statement)
    # A bare float. The `-v` form raises, and both delivery generators used to
    # swallow that inside `except Exception: pass`.
    mel.eval("FBXExportScaleFactor %g" % EXPORT_SCALE_FACTOR)

    if nodes:
        cmds.select(nodes, replace=True)
        cmds.file(path, force=True, options="v=0", type="FBX export", pr=True,
                  es=True)
    else:
        cmds.file(path, force=True, options="v=0", type="FBX export", pr=True,
                  ea=True)

    # Maya writes UnitScaleFactor 1.0 for a metre-native scene and offers no way
    # to change it, so the declaration is corrected here: one IEEE-754 double
    # overwritten with another of the same width, so nothing in the file moves.
    fbxbytes.set_unit_scale_factor(path)

    # Re-read the BYTES. This is the whole point of the tool: the defect it
    # guards is written by the exporter and is absent from the Maya scene, so
    # every in-Maya check is structurally blind to it.
    facts = fbxbytes.read_fbx(path)
    violations = gate_violations(facts)
    if violations:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise HandlerError(
            "the exported FBX failed the unit gate and was DELETED: %s"
            % "; ".join(violations[:4]),
            hint="the scene is the problem, not the export settings. Freeze "
                 "transforms so no node carries scale, and author so one unit "
                 "means one metre (linear_unit 'cm' in this repo's convention). "
                 "Nothing is written until it passes - a wrong file on disk is "
                 "how maya-mcp #629 reached three deliveries")

    lo, hi, height = _bounds(facts)
    return {
        "path": path,
        "bytes": os.path.getsize(path),
        "fbx_version": facts.version,
        "node_count": len(facts.nodes),
        "mesh_count": len(facts.meshes),
        "root_nodes": [n.name for n in facts.nodes if n.parent is None],
        "unit_scale_factor": facts.unit_scale_factor,
        "metres_per_unit": 1.0,
        "world_bounds_min": lo,
        "world_bounds_max": hi,
        "height_m": height,
    }
```

- [ ] **Step 4: Register the command**

In `maya_plugin/maya_mcp_plugin.py`, add `export` to the handlers import (it sorts between `etch` and `lighting`):

```python
from .handlers import (
    array,
    assemble,
    capture,
    code_exec,
    combine,
    etch,
    export,
    lighting,
```

and add the entry to the command map, immediately after the `"save_scene"` line (currently line 98):

```python
        "save_scene": session.save_scene,
        "export_fbx": export.export_fbx,
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
python -m pytest tests/test_export_fbx.py -v
```

Expected: PASS.

```bash
python -m pytest -q
```

Expected: the full suite green.

- [ ] **Step 6: Commit**

```bash
git add maya_plugin/handlers/export.py maya_plugin/maya_mcp_plugin.py tests/test_export_fbx.py
git commit -m "feat(export): export_fbx handler - gate the bytes, delete on failure (#642)"
```

---

### Task 6: The MCP tool

**Files:**
- Modify: `src/maya_mcp/schemas.py` (append)
- Modify: `src/maya_mcp/server.py:26-58` (import), `:78` (timeout), after `maya_save_scene` at `:758`
- Test: `tests/test_export_fbx.py`

**Interfaces:**
- Consumes: the handler's return dict from Task 5.
- Produces: `ExportFbxResult` (Pydantic) and the tool `maya_export_fbx(path, metres_per_unit, nodes=None)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_export_fbx.py`:

```python
def test_the_result_model_accepts_the_handler_payload():
    from maya_mcp.schemas import ExportFbxResult
    payload = {
        "path": "D:/deliver/golem.fbx", "bytes": 481232, "fbx_version": 7700,
        "node_count": 33, "mesh_count": 33, "root_nodes": ["golem_C_pelvis"],
        "unit_scale_factor": 100.0, "metres_per_unit": 1.0,
        "world_bounds_min": [-0.9, 0.0, -0.5],
        "world_bounds_max": [0.9, 4.02173, 0.5], "height_m": 4.02173,
    }
    result = ExportFbxResult.model_validate(payload)
    assert result.height_m == 4.02173
    assert result.root_nodes == ["golem_C_pelvis"]


def test_the_result_model_tolerates_a_geometryless_export():
    from maya_mcp.schemas import ExportFbxResult
    result = ExportFbxResult.model_validate({
        "path": "D:/deliver/empty.fbx", "bytes": 1024, "fbx_version": 7700,
        "node_count": 0, "mesh_count": 0, "root_nodes": [],
        "unit_scale_factor": 100.0, "metres_per_unit": 1.0,
    })
    assert result.height_m is None


def test_the_tool_is_exposed():
    source = (REPO / "src" / "maya_mcp" / "server.py").read_text(encoding="utf-8")
    assert "def maya_export_fbx(" in source
    # Named for the format it writes. #640 is open about naming papercuts and a
    # bare maya_export would promise OBJ and USD this tool does not have.
    assert "def maya_export(" not in source
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m pytest tests/test_export_fbx.py -v -k "result_model or tool_is_exposed"
```

Expected: FAIL with `ImportError: cannot import name 'ExportFbxResult'`.

- [ ] **Step 3: Add the result model**

Append to `src/maya_mcp/schemas.py`:

```python
class ExportFbxResult(BaseModel):
    """What maya_export_fbx actually wrote, read back out of the file.

    Every field here is composed from the FBX bytes, never from the Maya scene.
    That is the point of the tool: the unit defect it guards is written by the
    exporter and is absent from the scene, so a scene-derived report would be
    confidently wrong in exactly the case that matters.
    """

    model_config = ConfigDict(extra="ignore")

    path: str = Field(description="The file written, with forward slashes.")
    bytes: int = Field(description="Size on disk.")
    fbx_version: int = Field(description="FBX format version, e.g. 7700.")
    node_count: int = Field(description="Model records in the file.")
    mesh_count: int = Field(description="Geometry records in the file.")
    root_nodes: List[str] = Field(
        description=(
            "Nodes with no parent in the file. One for a rig; the demigol kit "
            "legitimately has 41, so this is reported, not policed."
        )
    )
    unit_scale_factor: float = Field(
        description=(
            "The file's own declaration, in centimetres per file unit. Always "
            "100.0 - the export is refused otherwise."
        )
    )
    metres_per_unit: float = Field(
        description="Always 1.0; the export is refused for any other value."
    )
    world_bounds_min: Optional[List[float]] = Field(
        default=None,
        description="XYZ minimum over every vertex, composed through the "
                    "parent chain. Null when the file holds no geometry.",
    )
    world_bounds_max: Optional[List[float]] = Field(
        default=None, description="XYZ maximum, same composition."
    )
    height_m: Optional[float] = Field(
        default=None,
        description=(
            "Y extent in metres - the number a consumer sees on import, and "
            "the one that tells a 4 m creature from a 4 cm one when every "
            "individual chunk is sub-metre."
        ),
    )
```

- [ ] **Step 4: Add the tool**

In `src/maya_mcp/server.py`, add `ExportFbxResult` to the `from .schemas import (...)` block (alphabetically, between `ExecuteResult` and `LightingResult`):

```python
    ExecuteResult,
    ExportFbxResult,
    LightingResult,
```

Add the timeout beside the others, after `BOOL_TIMEOUT_S = 120.0` (line 78):

```python
# A heavy scene takes tens of seconds to write, and the handler then re-reads
# and composes every vertex in the file before it answers.
EXPORT_TIMEOUT_S = 300.0
```

Add the tool immediately after `maya_save_scene` (ends at line 758):

```python
    @mcp.tool(
        title="Export FBX",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=True
        ),
    )
    def maya_export_fbx(
        path: Annotated[str, Field(description=(
            "Absolute path ending in .fbx. The parent directory must exist."
        ))],
        metres_per_unit: Annotated[float, Field(description=(
            "What one scene unit means in metres. REQUIRED, and only 1.0 "
            "exports - there is no default because a guess here is what "
            "shipped three deliveries at 100x. If your scene is not "
            "metre-native, scale and freeze it first: the exporter cannot fix "
            "vertex magnitude, it can only add a compensating node scale, "
            "which this tool rejects."
        ))],
        nodes: Annotated[Optional[List[str]], Field(description=(
            "Objects to export; omit to export the whole scene."
        ))] = None,
    ) -> ExportFbxResult:
        """Export FBX and gate the result on the BYTES it just wrote.

        Refuses and DELETES the file if any node carries a non-identity scale
        or the unit declaration disagrees with the geometry - the two ways a
        wrong-sized asset renders correctly and ships anyway. Everything
        returned is read back out of the file, not queried from the scene."""
        return ExportFbxResult.model_validate(
            maya.request(
                "export_fbx",
                {"path": path, "metres_per_unit": metres_per_unit, "nodes": nodes},
                timeout_s=EXPORT_TIMEOUT_S,
            )
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
python -m pytest tests/test_export_fbx.py -v
```

Expected: PASS.

```bash
python -m pytest -q
```

Expected: full suite green.

- [ ] **Step 6: Commit**

```bash
git add src/maya_mcp/schemas.py src/maya_mcp/server.py tests/test_export_fbx.py
git commit -m "feat(export): expose maya_export_fbx as an MCP tool (#642)"
```

---

### Task 7: The live gate

**Files:**
- Create: `evals/export_live.py`

**Interfaces:**
- Consumes: the deployed `export_fbx` command over TCP; `evals/live_call.py`'s `call` and `structured_result`; `fbx_probe`.
- Produces: a pass/fail report with measured numbers. Nothing imports it.

**Why this task exists:** a headless green means nothing here. The code path that matters runs inside Maya, and Maya loads the plugin from `<Documents>/maya/scripts/maya_plugin`, not from this repo. See the standing rule in project memory: write `evals/<thing>_live.py` and report measured numbers.

- [ ] **Step 1: Write the live gate**

Create `evals/export_live.py`:

```python
"""Live gate for maya-mcp #642: does maya_export_fbx write what it claims?

A headless test of this tool proves the gate logic and nothing else. The
export itself is Maya calling the FBX plugin, and the defect the gate exists
to catch is written at exactly that step - so the only check worth anything
runs against a real Maya and reads the bytes that came out.

Three measurements, one cube:

    a metre-native cube    -> exports, gate passes, span measures CUBE_SIDE
    the same cube, scaled  -> refused, and the FILE IS GONE afterwards
    metres_per_unit=100    -> refused before Maya is touched at all

The second is the important one. A tool that reports a violation but leaves
the file on disk has not solved anything: the transcript scrolls away and the
file ends up in a delivery.

DESTRUCTIVE: builds and deletes a probe cube in the current scene.

Defaults to port 9877, the user's own Maya, for the same reason
evals/units_live.py does - prove it in the session the user is looking at.
Do not "fix" it back to 9878.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fbx_probe  # noqa: E402  - sibling import, see evals/delivery_units.py
from evals.live_call import call, structured_result  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9877"))
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "export_live")
CUBE = "exportGateCube"
CUBE_SIDE = 3.0
TOL = 1e-3

CHECKS = []


def check(label, passed, detail=""):
    CHECKS.append((bool(passed), label))
    print("%s %s%s" % ("PASS" if passed else "FAIL", label,
                       ("  [%s]" % detail) if detail else ""))
    return bool(passed)


def _py(code, what):
    response = call("execute_python", {"code": code}, port=PORT)
    if response.get("error"):
        raise RuntimeError("%s: %s" % (what, response["error"]))
    return structured_result(response["result"], what)


def refresh_live_handlers():
    """Rebind export_fbx from the DEPLOYED source.

    A running Maya holds the modules it imported at startup, so a fresh deploy
    is invisible to it (maya-mcp #604). Without this the gate measures
    yesterday's plugin and reports it as today's.
    """
    return _py(
        "import importlib\n"
        "from maya_plugin import maya_mcp_plugin as _plugin\n"
        "from maya_plugin.handlers import fbxbytes as _fbxbytes\n"
        "from maya_plugin.handlers import export as _export\n"
        "for _m in (_fbxbytes, _export):\n"
        "    importlib.reload(_m)\n"
        "_h = _plugin._active_server._dispatcher._handlers\n"
        "_h['export_fbx'] = _export.export_fbx\n"
        "list(_export.FBX_PREAMBLE_MEL)",
        "rebind export_fbx from the deployed source",
    )


def build_cube(scale=1.0):
    _py("import maya.cmds as cmds\n"
        "if cmds.objExists('%(n)s'):\n"
        "    cmds.delete('%(n)s')\n"
        "cmds.polyCube(w=%(s)g, h=%(s)g, d=%(s)g, name='%(n)s', ch=False)\n"
        "cmds.setAttr('%(n)s.scale', %(k)g, %(k)g, %(k)g)\n"
        "'built'" % {"s": CUBE_SIDE, "n": CUBE, "k": scale},
        "build the probe cube")


def export(path, metres_per_unit=1.0, nodes=None):
    params = {"path": path.replace("\\", "/"), "metres_per_unit": metres_per_unit}
    if nodes is not None:
        params["nodes"] = nodes
    return call("export_fbx", params, port=PORT)


def span_of(facts):
    best = 0.0
    for verts in facts.meshes:
        for v in verts:
            best = max(best, abs(v))
    return best * 2.0


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("port %d, writing to %s\n" % (PORT, OUT_DIR))
    print("preamble live: %s\n" % (refresh_live_handlers(),))

    # 1. the good case
    good = os.path.join(OUT_DIR, "cube_ok.fbx")
    build_cube(scale=1.0)
    response = export(good, nodes=[CUBE])
    if check("a metre-native cube exports", not response.get("error"),
             response.get("error", "")):
        result = structured_result(response["result"], "export the cube")
        facts = fbx_probe.read_fbx(good)
        check("the declaration is metres",
              facts.unit_scale_factor == fbx_probe.DECLARES_METRES,
              "UnitScaleFactor=%r" % facts.unit_scale_factor)
        check("the vertices are metre-magnitude",
              abs(span_of(facts) - CUBE_SIDE) < TOL,
              "span %.5f m, expected %.1f" % (span_of(facts), CUBE_SIDE))
        check("the reported height came from the file",
              abs(result["height_m"] - CUBE_SIDE) < TOL,
              "height_m=%.5f, bytes=%d, nodes=%d"
              % (result["height_m"], result["bytes"], result["node_count"]))

    # 2. the case the whole tool exists for
    bad = os.path.join(OUT_DIR, "cube_scaled.fbx")
    if os.path.exists(bad):
        os.unlink(bad)
    build_cube(scale=0.01)
    response = export(bad, nodes=[CUBE])
    check("a scaled node is refused", bool(response.get("error")),
          str(response.get("error", ""))[:120])
    check("and the refused file is NOT on disk", not os.path.exists(bad),
          "a warning the caller can ignore is not a gate")

    # 3. refused before Maya is touched
    never = os.path.join(OUT_DIR, "never_written.fbx")
    if os.path.exists(never):
        os.unlink(never)
    build_cube(scale=1.0)
    response = export(never, metres_per_unit=100.0, nodes=[CUBE])
    check("metres_per_unit=100 is refused", bool(response.get("error")),
          str(response.get("error", ""))[:120])
    check("and nothing was written", not os.path.exists(never))

    _py("import maya.cmds as cmds\n"
        "cmds.delete('%s') if cmds.objExists('%s') else None\n"
        "'cleaned'" % (CUBE, CUBE), "delete the probe cube")

    failed = [label for ok, label in CHECKS if not ok]
    print("\n%d/%d passed" % (len(CHECKS) - len(failed), len(CHECKS)))
    for label in failed:
        print("  FAILED: %s" % label)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Deploy the plugin to the live Maya**

The live Maya loads from `<Documents>/maya/scripts/maya_plugin`, not this repo. A live run against a stale copy is a green result that means nothing.

```bash
python maya_plugin/install.py --yes
```

Expected: `Copied plugin to ...` and a `Stamped as <commit>` line matching the current HEAD.

- [ ] **Step 3: Run the live gate and report the measured numbers**

```bash
python evals/export_live.py
```

Expected: `8/8 passed`, with `span 3.00000 m` and `UnitScaleFactor=100.0` printed. **Report the actual measured numbers, not "it passed."** If the user's Maya is not running on 9877, say so and stop — do not substitute a headless run.

- [ ] **Step 4: Commit**

```bash
git add evals/export_live.py
git commit -m "test(export): live gate - measured bytes from a real Maya (#642)"
```

---

### Task 8: Close out

**Files:**
- Modify: `docs/superpowers/plans/2026-08-16-next-session.md` (the #642 entry)

- [ ] **Step 1: Run the full suite one last time**

```bash
python -m pytest -q
```

Expected: green, with the new `tests/test_export_fbx.py` cases added to the count.

- [ ] **Step 2: Update the transition doc**

In `docs/superpowers/plans/2026-08-16-next-session.md`, replace the "#642 — there is no export tool" ranked item with a short done-note: the tool that landed, the gate it enforces, and the one thing deliberately left open — migrating `evals/demigol_kit.py`, `evals/demigol_structures.py` and `evals/units_live.py` off `EXPORT_PREAMBLE` and onto `maya_export_fbx`, which needs a live art run to re-validate and so is its own piece of work.

- [ ] **Step 3: Commit and close the ticket**

```bash
git add docs/superpowers/plans/2026-08-16-next-session.md
git commit -m "docs: #642 is done - the export tool gates its own bytes"
```

Then one Redmine `update_issue` on **#642** combining notes and `status_id: 3` (Resolved): what shipped, the measured live numbers from Task 7 Step 3, and the deferred generator migration named as follow-up work.

---

## Self-Review

**Spec coverage:**

| spec section | task |
|---|---|
| 1. Promote the byte reader | Task 1 |
| 2. New handler, params, sequence | Tasks 2-5 |
| 3. The gate (two assertions; not one-root, not ceiling) | Task 3 |
| 4. The return, composed from the file | Task 5 (handler) + Task 6 (model) |
| 5. The tool, named `maya_export_fbx` | Task 6 |
| 6. One definition without an art run | Task 2 |
| Testing — headless | Tasks 1-6 |
| Testing — composed preamble pinned byte-for-byte | Task 2 |
| Testing — live | Task 7 |
| What this does not do | Global Constraints |

**Naming consistency:** `gate_violations`, `_validate`, `export_fbx`, `_bounds`, `_cmds`, `_mel`, `FBX_PREAMBLE_MEL`, `EXPORT_SCALE_FACTOR`, `SCALE_TOL` are used identically in every task. Command string is `"export_fbx"`; tool is `maya_export_fbx`; model is `ExportFbxResult`.

**No open unknowns.** Every file path, line number and symbol in this plan was read from the working tree at commit `7df1863`: the handler map factory is `_build_handlers()` at `maya_plugin/maya_mcp_plugin.py:81`, `"save_scene"` is line 98, `HandlerError(message, hint=None)` is `maya_plugin/dispatcher.py:39`, `maya_save_scene` ends at `src/maya_mcp/server.py:758`, and `BOOL_TIMEOUT_S` is line 78.

**Two things the implementer must not quietly "improve":**

1. The gate stays at two assertions. Adding the one-root rule breaks the demigol kit's 41 roots; adding the ceiling makes a per-delivery envelope into a universal law.
2. `EXPORT_PREAMBLE` stays byte-identical. If `test_the_composed_preamble_is_byte_identical` fails, the composition is wrong — do not update the expected literal to match the composition, because that literal is what three shipped deliveries went through and the only way to re-validate a change to it is a live art run.
