# #714 Phase 2 — `maya_bake_textures` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the toolbox a cure for the loss phase 1 exposed — a `maya_bake_textures` tool that converts a material's procedural texture networks into real file textures and rewires the scene to use them, so the look an agent judged in renders is the look that actually ships in the FBX.

**Architecture:** Baking is a scene EDIT, not an export option — the rewire is persistent, so post-bake renders *are* the shipped pixels and the builder re-judges the real artifact before exporting. A new handler `texbake.py` reuses phase 1's `texclaim.py` walker (never a second walker) and runs two phases: phase A bakes every requested slot to `.part.png` files and verifies them with ZERO scene mutation; phase B (only if every bake verified) checkpoints, rewires, commits the files and deletes the replaced chains. `export_fbx` never bakes.

**Tech Stack:** Python (Maya plugin + FastMCP server), `cmds.convertSolidTx` as the bake engine, pytest headless, the mayapy suite, and a live gate in `evals/`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-25-714-export-texture-honesty-design.md` §3 (committed `d44f1aa`). Where this plan and the spec disagree, the spec governs — report the conflict rather than silently diverging.
- Branch: `feat-714-bake-textures` off `main` (phase 1 merged as `e14697d`). Commits: `feat(#714): …` / `fix(#714): …` / `test(#714): …` / `docs(#714): …`.
- **Never touch `evals/golem_rerun_665/out_v4/`** (another agent's untracked work).
- Measure suites with `--junitxml=$env:TEMP\<name>.xml` and read counts from the XML — the pytest summary line is lost to stdout buffering on this machine. Report MEASURED numbers, never "tests pass".
- mayapy: `E:\Autodesk\Maya2027\bin\mayapy.exe`. The mayapy suite is ONE persistent process; each test gets a fresh scene from the autouse `fresh_scene` fixture.
- **Live Maya rule:** MCP server `maya` reaches `127.0.0.1:9877`; server `maya9879` is the USER'S art session — **never call any `mcp__maya9879__*` tool**. Launch your own: `$env:MAYA_MCP_PORT='9877'; Start-Process 'E:\Autodesk\Maya2027\bin\maya.exe' -WorkingDirectory 'D:\devel\maya-mcp'`, poll `Test-NetConnection 127.0.0.1 -Port 9877 -InformationLevel Quiet`, then VERIFY the listener's pid matches the process you started AND that `maya_plugin.__file__` is under `D:\devel\maya-mcp` (otherwise the deployed main-branch plugin is serving and your gate tests the wrong code). Kill only your own pid with `taskkill /F /T /PID <pid>`; verify the port released. If the MCP tools are unreachable: STOP and report, no fallbacks.
- Windows shell is PowerShell; `&&` is unavailable — chain with `;`.
- `docs/protocol.md` is the tool contract: the new tool's entry lands there in the task that ships it.
- Baseline at branch time: headless 1581 pass + 1 skip; mayapy 171 tests (170 pass + 1 skip).

## Measured facts this plan is built on (probe evidence, `evals/bake_probe_714.py`)

These are MEASURED, not assumed. Do not re-litigate them; do not build around a different assumption without a new measurement.

| Fact | Consequence for this plan |
|---|---|
| `convertSolidTx` RUNS under `maya.standalone` and writes a PNG | Bake tests can live in the mayapy suite, not live-only |
| A `noise` bakes usably through primitive **box-projection UVs** (186 distinct values / 1024 px) | The GO. Golem-class UVs are good enough; no UV-quality gate needed |
| A **UV-less mesh silently bakes a FLAT image and does NOT raise** | The tool MUST detect the no-UV condition itself and refuse — Maya will not do it for us (Task 2) |
| Sampling is **mesh-INDEPENDENT** (transform AND verified vertex deformation both leave the bake byte-identical) | A shared material bakes ONCE; no per-mesh refusal (§3.4's permissive arm). **Scope limit: proven for placement-less `noise` networks only** — a `place2dTexture`-driven network is unproven, see Task 2's warning |
| The written PNG is **8-bit RGB (colour type 2), no interlace** | The uniformity check ships; a minimal hand-rolled reader suffices |
| `noise.outColorR` bakes directly as a usable scalar | Bump-as-height needs no intermediate node |
| `file → bump2d(bumpInterp=0) → normalCamera` SURVIVES export | The normal-slot rewire shape is safe |
| **Export never validates that a texture file exists on disk** (a missing image still writes full Texture/Video records) | The tool must verify its OWN bake output; a downstream export will not catch a bad bake |

## File Structure

| File | Responsibility |
|---|---|
| `maya_plugin/handlers/texbake.py` (create) | The bake tool: validation, refusals, two-phase bake/commit, the result. Consumes `texclaim`; owns no walking of its own. |
| `maya_plugin/handlers/pngprobe.py` (create) | A tiny PNG reader — dimensions + distinct-pixel count — so "is this bake degenerate?" is answerable with no dependency. Pure, headless-testable. |
| `maya_plugin/dispatcher.py` / plugin command table (modify) | Register `bake_textures`. |
| `src/maya_mcp/schemas.py`, `src/maya_mcp/server.py` (modify) | `BakeTexturesResult` + the `maya_bake_textures` tool. |
| `maya_plugin/handlers/texture_recipes.py` (modify) | Extend the authoring warning to name the bake tool now that it exists; add the no-UV early warning. |
| `tests/test_pngprobe.py`, `tests/test_texbake.py` (create) | Pure + fake-cmds coverage. |
| `tests/test_handlers_mayapy.py`, `tests/test_server_tools.py` (modify) | Real-Maya bake→export proof; wrapper forwarding. |
| `evals/texbake_live.py` (create) | The live gate: render BEFORE, bake, render AFTER, export, cross-check. |

---

### Task 1: `pngprobe.py` — is this bake degenerate?

**Files:**
- Create: `maya_plugin/handlers/pngprobe.py`
- Create: `tests/test_pngprobe.py`

**Interfaces:**
- Produces: `pngprobe.read_png(path) -> {"width": int, "height": int, "bit_depth": int, "colour_type": int, "pixels": [tuple]}` and `pngprobe.uniformity(path) -> {"pixel_count": int, "distinct_values": int, "non_uniform": bool, "unavailable_reason": Optional[str]}`. `uniformity` NEVER raises — an unreadable or unsupported PNG returns `non_uniform=None` with `unavailable_reason` set.

Why this exists: the probes measured that `convertSolidTx` silently writes a FLAT image for a UV-less mesh and that a downstream export will not notice a bad texture. The tool must therefore inspect its own output. The repo has no image dependency and does not want one (the eval scripts hand-roll PNG I/O with `struct`+`zlib`); this is that technique, promoted to production with an honest "could not read it" path.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pngprobe.py`:

```python
"""#714 phase 2: the bake tool inspects its own output.

MEASURED (evals/bake_probe_714.py, P3): convertSolidTx writes 8-bit RGB
(colour type 2), no interlace - so that is the shape this reader must
handle. Anything else it cannot read is reported, never guessed at.
"""

import struct
import zlib

import pytest

from maya_plugin.handlers import pngprobe


def _png(path, rows, bit_depth=8, colour_type=2):
    """A real PNG built the way evals/tool_gaps_live.py's write_png does -
    no Pillow anywhere in this repo. `rows` is a list of lists of
    per-pixel tuples."""
    raw = bytearray()
    for row in rows:
        raw.append(0)                      # filter type 0 (None)
        for px in row:
            raw.extend(px)

    def chunk(tag, payload):
        body = tag + payload
        return (struct.pack(">I", len(payload)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    width, height = len(rows[0]), len(rows)
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, bit_depth,
                                        colour_type, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(raw)))
           + chunk(b"IEND", b""))
    path.write_bytes(png)
    return str(path)


class TestReadPng:
    def test_it_reads_dimensions_and_pixels(self, tmp_path):
        path = _png(tmp_path / "two.png",
                    [[(255, 0, 0), (0, 255, 0)],
                     [(0, 0, 255), (9, 9, 9)]])
        out = pngprobe.read_png(path)
        assert out["width"] == 2 and out["height"] == 2
        assert out["bit_depth"] == 8 and out["colour_type"] == 2
        assert (255, 0, 0) in out["pixels"] and (9, 9, 9) in out["pixels"]

    def test_a_non_png_raises(self, tmp_path):
        bad = tmp_path / "not.png"
        bad.write_bytes(b"nope")
        with pytest.raises(ValueError, match="PNG"):
            pngprobe.read_png(str(bad))


class TestUniformity:
    def test_a_varied_image_is_non_uniform(self, tmp_path):
        path = _png(tmp_path / "varied.png",
                    [[(1, 1, 1), (2, 2, 2)], [(3, 3, 3), (4, 4, 4)]])
        out = pngprobe.uniformity(path)
        assert out["pixel_count"] == 4
        assert out["distinct_values"] == 4
        assert out["non_uniform"] is True
        assert out["unavailable_reason"] is None

    def test_a_flat_image_is_uniform(self, tmp_path):
        # The MEASURED failure mode: a UV-less mesh bakes exactly this.
        path = _png(tmp_path / "flat.png",
                    [[(7, 7, 7), (7, 7, 7)], [(7, 7, 7), (7, 7, 7)]])
        out = pngprobe.uniformity(path)
        assert out["distinct_values"] == 1
        assert out["non_uniform"] is False

    def test_an_unreadable_file_reports_rather_than_raising(self, tmp_path):
        bad = tmp_path / "broken.png"
        bad.write_bytes(b"\x89PNG\r\n\x1a\n" + b"garbage")
        out = pngprobe.uniformity(str(bad))
        assert out["non_uniform"] is None
        assert out["unavailable_reason"]
        assert out["distinct_values"] == 0

    def test_a_missing_file_reports_rather_than_raising(self, tmp_path):
        out = pngprobe.uniformity(str(tmp_path / "nope.png"))
        assert out["non_uniform"] is None
        assert "nope.png" in out["unavailable_reason"]
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_pngprobe.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'maya_plugin.handlers.pngprobe'`.

- [ ] **Step 3: Implement**

Create `maya_plugin/handlers/pngprobe.py`:

```python
"""A minimal PNG reader, so a bake can be checked for being degenerate.

#714 phase 2. Two measurements make this necessary rather than nice:
convertSolidTx writes a FLAT image (and raises nothing) when the mesh has
no UVs, and the FBX export never validates that a texture file exists or
is any good - so nothing downstream would catch a bad bake. The bake tool
has to inspect its own output.

Deliberately not a general PNG library: it reads 8-bit non-interlaced
images, which is what Maya's own bake was MEASURED to write (P3: bit
depth 8, colour type 2), and reports anything else as unreadable rather
than guessing. `uniformity` never raises - a bake that cannot be measured
is reported as unmeasured, never silently passed.
"""

from __future__ import annotations

import os
import struct
import zlib
from typing import Any, Dict

_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# colour type -> samples per pixel
_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def _unfilter(raw: bytes, width: int, height: int, stride: int) -> list:
    """Undo PNG's per-row filters. The five filter types are the format's
    own; a row's predictor reads the RECONSTRUCTED previous row, which is
    why `prev` is only replaced once a row is finished."""
    out = []
    prev = bytearray(width * stride)
    pos = 0
    for _ in range(height):
        ftype = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + width * stride])
        pos += width * stride
        for i in range(len(line)):
            left = line[i - stride] if i >= stride else 0
            up = prev[i]
            upleft = prev[i - stride] if i >= stride else 0
            if ftype == 1:
                line[i] = (line[i] + left) & 0xFF
            elif ftype == 2:
                line[i] = (line[i] + up) & 0xFF
            elif ftype == 3:
                line[i] = (line[i] + ((left + up) >> 1)) & 0xFF
            elif ftype == 4:
                p = left + up - upleft
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - upleft)
                pred = left if (pa <= pb and pa <= pc) else (
                    up if pb <= pc else upleft)
                line[i] = (line[i] + pred) & 0xFF
            elif ftype != 0:
                raise ValueError("unknown PNG filter type %d" % ftype)
        out.append(bytes(line))
        prev = line
    return out


def read_png(path) -> Dict[str, Any]:
    """Dimensions, header fields and the flat pixel list. Raises ValueError
    on anything this reader does not handle - callers that must not fail
    use `uniformity` instead."""
    path = str(path)
    with open(path, "rb") as fh:
        data = fh.read()
    if not data.startswith(_SIGNATURE):
        raise ValueError("%s is not a PNG" % path)
    pos = len(_SIGNATURE)
    header = None
    idat = bytearray()
    while pos + 8 <= len(data):
        length = struct.unpack_from(">I", data, pos)[0]
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        if tag == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif tag == b"IDAT":
            idat.extend(body)
        elif tag == b"IEND":
            break
        pos += 12 + length
    if header is None:
        raise ValueError("%s carries no IHDR" % path)
    width, height, bit_depth, colour_type, _comp, _filt, interlace = header
    if bit_depth != 8:
        raise ValueError("%s is %d-bit; this reader handles 8-bit only"
                         % (path, bit_depth))
    if interlace:
        raise ValueError("%s is interlaced; this reader handles "
                         "non-interlaced only" % path)
    stride = _CHANNELS.get(colour_type)
    if stride is None:
        raise ValueError("%s has unknown colour type %d"
                         % (path, colour_type))
    rows = _unfilter(zlib.decompress(bytes(idat)), width, height, stride)
    pixels = []
    for row in rows:
        for x in range(width):
            pixels.append(tuple(row[x * stride:(x + 1) * stride]))
    return {"width": width, "height": height, "bit_depth": bit_depth,
            "colour_type": colour_type, "pixels": pixels}


def uniformity(path) -> Dict[str, Any]:
    """How many distinct pixel values the image carries - the honest test
    for "did this bake actually sample anything?".

    Never raises. A file that cannot be read reports non_uniform=None with
    a reason, so a caller says "could not measure this bake" instead of
    either crashing or claiming the bake is fine.
    """
    path = str(path)
    if not os.path.isfile(path):
        return {"pixel_count": 0, "distinct_values": 0, "non_uniform": None,
                "unavailable_reason": "no file at %s" % path}
    try:
        png = read_png(path)
    except Exception as exc:  # noqa: BLE001 - any read failure is reportable
        return {"pixel_count": 0, "distinct_values": 0, "non_uniform": None,
                "unavailable_reason": "%s: %s" % (type(exc).__name__, exc)}
    distinct = len(set(png["pixels"]))
    return {"pixel_count": len(png["pixels"]), "distinct_values": distinct,
            "non_uniform": distinct > 1, "unavailable_reason": None}
```

- [ ] **Step 4: Run to verify pass**

```bash
python -m pytest tests/test_pngprobe.py -q
```

Expected: PASS, 7 tests, pristine output.

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/pngprobe.py tests/test_pngprobe.py
git commit -m "feat(#714): pngprobe - measure whether a bake actually sampled anything"
```

---

### Task 2: `texbake.py` — validation and refusals (no baking yet)

**Files:**
- Create: `maya_plugin/handlers/texbake.py`
- Create: `tests/test_texbake.py`

**Interfaces:**
- Consumes: `texclaim.material_claims(cmds, shapes)` (claim dicts: `mesh`, `meshes`, `material`, `sg`, `attr`, `slot`, `classification`, `terminals` [each `{node, type, file_path, basename, on_disk, colorspace}`], `via`, `semantics_lost`); `naming.require_mesh(cmds, name) -> (transform_long, shape)`; `pbr.SLOTS` (`{slot: (attr, kind)}`).
- Produces: `texbake.validate(params, cmds) -> {"meshes": [shape_long], "out_dir": str, "resolution": int, "slots": Optional[List[str]]}` and `texbake.plan_bakes(cmds, shapes, slots) -> (jobs, warnings)` where a job is `{"material", "sg", "attr", "slot", "kind", "terminal_plug", "mesh", "meshes", "via", "bump_node" (or None), "basename"}`. Both are pre-mutation and raise `HandlerError` for every refusal.

- [ ] **Step 1: Write the failing validation tests**

Create `tests/test_texbake.py` with a fake-cmds scene (mirror `tests/test_texclaim.py`'s fake shape; read it first and reuse its idiom rather than inventing a second one):

```python
"""#714 phase 2: what maya_bake_textures refuses, before it touches anything.

Every refusal here is grounded in a MEASURED probe finding, not caution:
convertSolidTx does not raise on a UV-less mesh (it writes a flat, useless
image), so the tool must catch that itself; and a normal slot with no
bump2d in the chain has no measured surviving wiring shape.
"""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import texbake


class FakeCmds:
    """|body (shape |bodyShape) wears bodySG -> skin_mat; a noise drives
    baseColor. UV count and shading graph are per-test knobs."""

    def __init__(self, uv_count=64):
        self.uv_count = uv_count
        self.meshes = {"|body": "|bodyShape"}
        self.types = {"skin_mat": "standardSurface", "mcpTex_noise": "noise"}
        self.sets = {"|bodyShape": ["bodySG"]}
        self.conns = {"bodySG.surfaceShader": ["skin_mat.outColor"],
                      "skin_mat.baseColor": ["mcpTex_noise.outColor"]}
        self.existing_attrs = {"skin_mat.baseColor"}

    # resolution ------------------------------------------------------
    def ls(self, name=None, long=False, **kw):
        if name in self.meshes:
            return [name]
        return [n for n in self.meshes if n.split("|")[-1] == name] or []

    def objExists(self, name):
        return name in self.meshes or name in self.types

    def listRelatives(self, node, shapes=False, fullPath=False, **kw):
        return [self.meshes[node]] if shapes and node in self.meshes else None

    def nodeType(self, node):
        if node in self.meshes.values():
            return "mesh"
        return self.types.get(node, "transform")

    def polyEvaluate(self, node, uvcoord=False, **kw):
        return self.uv_count if uvcoord else 0

    # graph -----------------------------------------------------------
    def listSets(self, object=None, type=None):
        return list(self.sets.get(object, []))

    def listConnections(self, plug, source=False, destination=True,
                        plugs=False, **kw):
        srcs = self.conns.get(plug) or []
        if not srcs:
            return None
        return list(srcs) if plugs else [s.split(".")[0] for s in srcs]

    def attributeQuery(self, attr, node=None, exists=False):
        return ("%s.%s" % (node, attr)) in self.existing_attrs

    def getAttr(self, plug):
        return ""


@pytest.fixture
def fake(monkeypatch):
    cmds = FakeCmds()
    monkeypatch.setattr(texbake, "_cmds", lambda: cmds)
    return cmds


def _params(tmp_path, **kw):
    base = {"meshes": ["|body"], "out_dir": str(tmp_path)}
    base.update(kw)
    return base


class TestValidation:
    def test_meshes_is_required(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="meshes"):
            texbake.validate({"out_dir": str(tmp_path)}, fake)

    def test_out_dir_must_exist(self, fake, tmp_path):
        params = _params(tmp_path, out_dir=str(tmp_path / "nope"))
        with pytest.raises(HandlerError, match="does not exist"):
            texbake.validate(params, fake)

    def test_out_dir_must_be_absolute(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="absolute"):
            texbake.validate(_params(tmp_path, out_dir="relative/dir"), fake)

    def test_resolution_must_be_a_supported_power_of_two(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="resolution"):
            texbake.validate(_params(tmp_path, resolution=1000), fake)

    def test_an_unknown_slot_refuses(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="slot"):
            texbake.validate(_params(tmp_path, slots=["shininess"]), fake)

    def test_defaults_are_1024_and_every_slot(self, fake, tmp_path):
        out = texbake.validate(_params(tmp_path), fake)
        assert out["resolution"] == 1024
        assert out["slots"] is None
        assert out["meshes"] == ["|bodyShape"]


class TestRefusals:
    def test_a_mesh_with_no_uvs_refuses_naming_uv_atlas(self, fake, tmp_path):
        # MEASURED: convertSolidTx does NOT raise here - it writes a flat,
        # useless image. Maya will not catch this for us.
        fake.uv_count = 0
        params = texbake.validate(_params(tmp_path), fake)
        with pytest.raises(HandlerError, match="no UVs"):
            texbake.plan_bakes(fake, params["meshes"], params["slots"])

    def test_the_no_uv_refusal_hint_names_the_fix(self, fake, tmp_path):
        fake.uv_count = 0
        params = texbake.validate(_params(tmp_path), fake)
        try:
            texbake.plan_bakes(fake, params["meshes"], params["slots"])
        except HandlerError as exc:
            assert "maya_uv_atlas" in (exc.hint or "")
        else:
            pytest.fail("expected a refusal")

    def test_a_procedural_normal_without_a_bump2d_refuses(self, fake, tmp_path):
        fake.existing_attrs = {"skin_mat.normalCamera"}
        fake.conns = {"bodySG.surfaceShader": ["skin_mat.outColor"],
                      "skin_mat.normalCamera": ["mcpTex_noise.outColor"]}
        params = texbake.validate(_params(tmp_path), fake)
        with pytest.raises(HandlerError, match="bump2d"):
            texbake.plan_bakes(fake, params["meshes"], params["slots"])

    def test_a_file_backed_slot_is_skipped_not_baked(self, fake, tmp_path):
        fake.types["mcpTex_file"] = "file"
        fake.conns["skin_mat.baseColor"] = ["mcpTex_file.outColor"]
        params = texbake.validate(_params(tmp_path), fake)
        jobs, warnings = texbake.plan_bakes(fake, params["meshes"],
                                            params["slots"])
        assert jobs == []
        assert any("already file-backed" in w for w in warnings)

    def test_nothing_to_bake_refuses_rather_than_no_opping(self, fake,
                                                           tmp_path):
        fake.conns.pop("skin_mat.baseColor")
        params = texbake.validate(_params(tmp_path), fake)
        with pytest.raises(HandlerError, match="no procedural"):
            texbake.plan_bakes(fake, params["meshes"], params["slots"])


class TestPlan:
    def test_a_procedural_colour_slot_becomes_one_job(self, fake, tmp_path):
        params = texbake.validate(_params(tmp_path), fake)
        jobs, _warnings = texbake.plan_bakes(fake, params["meshes"],
                                             params["slots"])
        assert len(jobs) == 1
        job = jobs[0]
        assert job["material"] == "skin_mat"
        assert job["slot"] == "color"
        assert job["attr"] == "baseColor"
        assert job["kind"] == "color"
        assert job["terminal_plug"] == "mcpTex_noise.outColor"
        assert job["bump_node"] is None
        assert job["basename"] == "skin_mat_color_baked.png"

    def test_the_slots_filter_narrows_the_jobs(self, fake, tmp_path):
        params = texbake.validate(_params(tmp_path, slots=["roughness"]), fake)
        with pytest.raises(HandlerError, match="no procedural"):
            texbake.plan_bakes(fake, params["meshes"], params["slots"])
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_texbake.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'maya_plugin.handlers.texbake'`.

- [ ] **Step 3: Implement validation and planning**

Create `maya_plugin/handlers/texbake.py` (this task ships only `validate` + `plan_bakes` and the module's docstring; Task 3 adds the bake itself):

```python
"""maya_bake_textures: turn procedural texture networks into file textures.

#714 phase 2. Phase 1 made the loss VISIBLE - export_fbx now names every
procedural map Maya's FBX exporter drops. This is the cure: bake those
networks to real images and rewire the scene to use them, so what an agent
judged in a render is what actually ships.

The rewire is PERSISTENT on purpose. A temporary export-time bake would
ship pixels nobody ever looked at; making it a scene edit means the next
render IS the deliverable, and the builder re-judges the real artifact
before exporting. export_fbx never bakes.

Two probe measurements shape the refusals below, and neither is caution:
convertSolidTx does NOT raise on a UV-less mesh - it writes a flat, useless
image - and the FBX export never validates that a texture file exists or is
any good. Nothing downstream catches a bad bake, so this tool checks its
own work (pngprobe) and refuses what it cannot bake honestly.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from ..dispatcher import HandlerError
from . import naming, pbr, texclaim

RESOLUTIONS = (256, 512, 1024, 2048, 4096)
DEFAULT_RESOLUTION = 1024


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def validate(params: Dict[str, Any], cmds) -> Dict[str, Any]:
    """Everything checkable before a single node is touched."""
    raw = params.get("meshes")
    names = [raw] if isinstance(raw, str) else list(raw or [])
    if not names or not all(isinstance(n, str) and n.strip() for n in names):
        raise HandlerError(
            "missing required param 'meshes'",
            hint="pass the mesh(es) whose materials should be baked; "
                 "maya_get_scene_graph lists what the scene contains")

    shapes = []
    for name in names:
        _transform, shape = naming.require_mesh(cmds, name)
        if shape not in shapes:
            shapes.append(shape)

    out_dir = params.get("out_dir")
    if not isinstance(out_dir, str) or not out_dir.strip():
        raise HandlerError(
            "missing required param 'out_dir'",
            hint="an absolute directory the baked images are written to - "
                 "there is no default, because a guessed location is how "
                 "bake files get lost from a delivery")
    if not os.path.isabs(out_dir):
        raise HandlerError(
            "out_dir %r must be absolute" % out_dir,
            hint="a relative path resolves against Maya's working directory, "
                 "which is not where you think it is")
    if not os.path.isdir(out_dir):
        raise HandlerError(
            "out_dir %r does not exist" % out_dir,
            hint="this tool does not make directories it was not asked to "
                 "make (the export_fbx rule)")

    resolution = params.get("resolution", DEFAULT_RESOLUTION)
    if (isinstance(resolution, bool) or not isinstance(resolution, int)
            or resolution not in RESOLUTIONS):
        raise HandlerError(
            "resolution must be one of %s"
            % ", ".join(str(r) for r in RESOLUTIONS),
            hint="a bake is square; these are the sizes this tool writes")

    slots = params.get("slots")
    if slots is not None:
        if (not isinstance(slots, list)
                or not all(isinstance(s, str) for s in slots)):
            raise HandlerError("slots must be a list of slot names",
                               hint="omit it to bake every procedural slot")
        unknown = [s for s in slots if s not in pbr.SLOTS]
        if unknown:
            raise HandlerError(
                "unknown slot(s): %s" % ", ".join(unknown),
                hint="valid slots: %s" % ", ".join(sorted(pbr.SLOTS)))

    return {"meshes": shapes, "out_dir": out_dir, "resolution": resolution,
            "slots": list(slots) if slots is not None else None}


def _uv_count(cmds, shape: str) -> int:
    try:
        return int(cmds.polyEvaluate(shape, uvcoord=True) or 0)
    except Exception:  # noqa: BLE001 - a shape that cannot answer has none
        return 0


def plan_bakes(cmds, shapes: List[str],
               slots: Optional[List[str]]) -> Tuple[List[Dict[str, Any]],
                                                    List[str]]:
    """What this call would bake, and what it is skipping. Pre-mutation.

    One job per (material, attr) - NOT per mesh. MEASURED (probe P2d/P2e):
    convertSolidTx samples through UVs, not world geometry - a transform
    change AND a real vertex deformation both left the bake byte-identical
    - so a material worn by several requested meshes bakes ONCE.

    SCOPE LIMIT on that measurement: it was taken on placement-less `noise`
    networks (the recipes this toolbox authors). A network driven through a
    place2dTexture with non-default placement is NOT covered by it; such a
    job carries a warning rather than a refusal, because the bake is still
    per-material by construction and the warning is what a reviewer needs
    to re-measure if it ever matters.
    """
    for shape in shapes:
        if _uv_count(cmds, shape) == 0:
            raise HandlerError(
                "%s has no UVs - a bake samples through UV space, and Maya "
                "does NOT refuse this: convertSolidTx silently writes a "
                "flat, useless image (MEASURED, #714 probe P2c)" % shape,
                hint="maya_uv_atlas creates UVs (project='box' is enough for "
                     "tiling detail); bake after that")

    claims = texclaim.material_claims(cmds, shapes)
    jobs: List[Dict[str, Any]] = []
    warnings: List[str] = []
    seen = set()
    for claim in claims:
        slot = claim["slot"]
        if slots is not None and slot not in slots:
            continue
        if claim["classification"] == "file":
            warnings.append(
                "%s.%s is already file-backed - nothing to bake"
                % (claim["material"], claim["attr"]))
            continue
        key = (claim["material"], claim["attr"])
        if key in seen:
            continue
        seen.add(key)

        kind = pbr.SLOTS[slot][1] if slot in pbr.SLOTS else "color"
        terminals = claim["terminals"]
        if len(terminals) != 1:
            raise HandlerError(
                "%s.%s is driven by %d terminals (%s) - this tool bakes one "
                "network per slot and will not guess which to keep"
                % (claim["material"], claim["attr"], len(terminals),
                   ", ".join(t["node"] for t in terminals)),
                hint="simplify the network, or bake the slots separately")
        terminal = terminals[0]

        bump_node = None
        if kind == "normal":
            if "bump2d" not in claim["via"]:
                raise HandlerError(
                    "%s.%s is driven procedurally with no bump2d in the "
                    "chain - a tangent-space normal bake is a different "
                    "capability this tool does not have"
                    % (claim["material"], claim["attr"]),
                    hint="author the normal through a bump2d (the noise_bump "
                         "recipe does), or bake the other slots and leave "
                         "this one")
            bump_node = _bump_node_for(cmds, claim)

        if any(t["type"] == "unresolved(depth)" for t in terminals):
            raise HandlerError(
                "%s.%s's network could not be resolved (a cycle, or deeper "
                "than the walk follows) - refusing rather than baking a "
                "guess" % (claim["material"], claim["attr"]),
                hint="simplify the shading network feeding this slot")

        if _has_placement(cmds, terminal["node"]):
            warnings.append(
                "%s.%s samples through a place2dTexture - the bake is still "
                "written once per material, but #714's mesh-independence "
                "measurement covered placement-less networks only; check the "
                "result on each mesh that wears it"
                % (claim["material"], claim["attr"]))

        jobs.append({
            "material": claim["material"], "sg": claim["sg"],
            "attr": claim["attr"], "slot": slot, "kind": kind,
            "terminal_plug": _bake_source_plug(terminal, kind),
            "mesh": claim["mesh"], "meshes": list(claim["meshes"]),
            "via": list(claim["via"]), "bump_node": bump_node,
            "basename": "%s_%s_baked.png" % (claim["material"], slot),
        })
        if len(claim["meshes"]) > 1:
            warnings.append(
                "%s is worn by %d meshes (%s) - baking it changes the look "
                "of every one of them, which is the point, but it is not "
                "reversible without maya_undo"
                % (claim["material"], len(claim["meshes"]),
                   ", ".join(claim["meshes"])))

    if not jobs:
        raise HandlerError(
            "no procedural texture network to bake on the requested "
            "mesh(es)%s" % (" for slot(s) %s" % ", ".join(slots)
                            if slots else ""),
            hint="maya_export_fbx's textures.dropped_maps names what a "
                 "scene actually carries; a file-backed slot needs no bake")
    return jobs, warnings


def _bake_source_plug(terminal: Dict[str, Any], kind: str) -> str:
    """Which plug convertSolidTx samples.

    MEASURED (probe P3): `noise.outColorR` bakes directly as a usable
    scalar, so a height/scalar bake needs no intermediate node. Colour
    slots bake the terminal's outColor.
    """
    if kind in ("scalar", "normal"):
        return "%s.outColorR" % terminal["node"]
    return "%s.outColor" % terminal["node"]


def _bump_node_for(cmds, claim: Dict[str, Any]) -> Optional[str]:
    """The bump2d between the terminal and the shader, if any. The rewire
    keeps it (bumpDepth is the authored look) and only replaces what feeds
    its bumpValue."""
    sources = cmds.listConnections("%s.%s" % (claim["material"],
                                              claim["attr"]),
                                   source=True, destination=False) or []
    for node in sources:
        try:
            if cmds.nodeType(node) == "bump2d":
                return node
        except Exception:  # noqa: BLE001 - a node that cannot answer is not it
            pass
    return None


def _has_placement(cmds, node: str) -> bool:
    try:
        sources = cmds.listConnections(node, source=True, destination=False) or []
        return any(cmds.nodeType(n) == "place2dTexture" for n in sources)
    except Exception:  # noqa: BLE001 - unknown placement is reported as none
        return False
```

- [ ] **Step 4: Run to verify pass**

```bash
python -m pytest tests/test_texbake.py -q
```

Expected: PASS, 13 tests. If a test fails because the fake does not answer a call the real code makes, extend the FAKE (it must model Maya, not dodge it) — never weaken the assertion.

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/texbake.py tests/test_texbake.py
git commit -m "feat(#714): texbake validation and bake planning, with measured refusals"
```

---

### Task 3: The two-phase bake

**Files:**
- Modify: `maya_plugin/handlers/texbake.py`
- Modify: `tests/test_texbake.py`

**Interfaces:**
- Consumes: `pngprobe.uniformity(path)`, `session.auto_checkpoint(reason) -> {"checkpoint_id", "path"}`, `naming.unique_name(cmds, base)`, `pbr._PLACE2D_LINKS`.
- Produces: `texbake.bake_textures(params) -> dict` with keys `meshes`, `out_dir`, `resolution`, `baked` (list of `{material, slot, attr, file, basename, resolution, colorspace, wired_plug, kept_intermediates, deleted_nodes, pixel_check}`), `skipped_file_backed`, `checkpoint_id`, `warnings`.

The two-phase rule is the heart of this task: **phase A** bakes every job to `<out_dir>/<basename>.part.png` and verifies each one, mutating NOTHING in the scene; **phase B** runs only if every bake verified — checkpoint, rewire, `os.replace` each `.part.png` onto its final name, delete the replaced chains. A phase-A failure sweeps every `.part.png` and raises: the scene is untouched, so the caller is in exactly one of two states, never a half-baked mix.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_texbake.py`:

```python
class TestTwoPhaseBake:
    """Phase A writes and verifies with ZERO scene mutation; phase B
    rewires only if every bake verified. A caller is therefore always in
    one of exactly two states."""

    def test_a_failed_bake_leaves_the_scene_untouched(self, fake, tmp_path,
                                                      monkeypatch):
        monkeypatch.setattr(texbake, "_convert_solid_tx",
                            lambda *a, **kw: None)   # writes no file
        with pytest.raises(HandlerError, match="produced no file"):
            texbake.bake_textures(_params(tmp_path))
        assert fake.connected == []          # nothing rewired
        assert fake.deleted == []            # nothing deleted
        assert fake.checkpoints == []        # not even a checkpoint

    def test_a_degenerate_bake_refuses_before_rewiring(self, fake, tmp_path,
                                                       monkeypatch):
        # MEASURED failure mode: a flat image is what a UV-less mesh bakes.
        # The UV guard catches that case; this proves the pixel check is a
        # real second net, not decoration.
        monkeypatch.setattr(texbake, "_convert_solid_tx", _fake_bake(fake))
        monkeypatch.setattr(texbake.pngprobe, "uniformity",
                            lambda _p: {"pixel_count": 1024,
                                        "distinct_values": 1,
                                        "non_uniform": False,
                                        "unavailable_reason": None})
        with pytest.raises(HandlerError, match="flat"):
            texbake.bake_textures(_params(tmp_path))
        assert fake.connected == []
        assert not list(tmp_path.glob("*.part.png"))   # swept

    def test_a_good_bake_rewires_and_commits(self, fake, tmp_path,
                                             monkeypatch):
        monkeypatch.setattr(texbake, "_convert_solid_tx", _fake_bake(fake))
        monkeypatch.setattr(texbake.pngprobe, "uniformity",
                            lambda _p: {"pixel_count": 1024,
                                        "distinct_values": 186,
                                        "non_uniform": True,
                                        "unavailable_reason": None})
        out = texbake.bake_textures(_params(tmp_path))

        assert len(out["baked"]) == 1
        entry = out["baked"][0]
        assert entry["basename"] == "skin_mat_color_baked.png"
        assert os.path.isfile(entry["file"])          # committed, not .part
        assert not list(tmp_path.glob("*.part.png"))  # nothing left behind
        assert entry["pixel_check"]["non_uniform"] is True
        assert out["checkpoint_id"]                   # checkpointed first
        # the shader now reads the baked file, and the old noise is gone
        assert any(dst == "skin_mat.baseColor" for _src, dst in fake.connected)
        assert "mcpTex_noise" in fake.deleted

    def test_an_unmeasurable_bake_refuses_rather_than_shipping(
            self, fake, tmp_path, monkeypatch):
        monkeypatch.setattr(texbake, "_convert_solid_tx", _fake_bake(fake))
        monkeypatch.setattr(texbake.pngprobe, "uniformity",
                            lambda _p: {"pixel_count": 0,
                                        "distinct_values": 0,
                                        "non_uniform": None,
                                        "unavailable_reason": "unreadable"})
        with pytest.raises(HandlerError, match="could not be measured"):
            texbake.bake_textures(_params(tmp_path))
        assert fake.connected == []
```

Add the helper and the fake's mutation-recording surface near the top of the file (extend the existing `FakeCmds`, do not fork it):

```python
def _fake_bake(fake):
    """Stand in for convertSolidTx: write a real (tiny) PNG at the path the
    tool asked for, so the part-file/commit machinery is exercised for
    real while the pixels come from the monkeypatched uniformity check."""
    def _bake(cmds, source_plug, target, path, resolution):
        with open(path, "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n" + b"x" * 64)
        fake.baked_calls.append((source_plug, target, path, resolution))
    return _bake
```

and in `FakeCmds.__init__`: `self.connected = []`, `self.deleted = []`, `self.checkpoints = []`, `self.baked_calls = []`, `self.created = []`; plus methods:

```python
    def shadingNode(self, node_type, name=None, asTexture=False,
                    asUtility=False, **kw):
        self.types[name] = node_type
        self.created.append(name)
        return name

    def setAttr(self, plug, *values, **kw):
        pass

    def connectAttr(self, src, dst, force=False):
        self.connected.append((src, dst))
        self.conns[dst] = [src]

    def delete(self, *nodes):
        for n in nodes:
            self.deleted.append(n)
            self.types.pop(n, None)
```

and in the `fake` fixture, stub the checkpoint the way `tests/test_clip.py` does:

```python
    monkeypatch.setattr(texbake.session, "auto_checkpoint",
                        lambda reason: (cmds.checkpoints.append(reason)
                                        or {"checkpoint_id": "cp",
                                            "path": "cp.ma"}))
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_texbake.py::TestTwoPhaseBake -q
```

Expected: FAIL — `AttributeError: module 'maya_plugin.handlers.texbake' has no attribute 'bake_textures'`.

- [ ] **Step 3: Implement the bake**

Append to `maya_plugin/handlers/texbake.py` (and add `pngprobe`, `session` to its imports):

```python
def _convert_solid_tx(cmds, source_plug: str, target: str, path: str,
                      resolution: int) -> None:
    """The bake itself, isolated so tests can drive the surrounding
    machinery without Maya.

    The delete-first/assert-after discipline is the probe's: convertSolidTx
    can return normally WITHOUT writing a file, and a fixed output name
    would then read back a previous run's image as if it were this one.
    """
    if os.path.exists(path):
        os.remove(path)
    cmds.convertSolidTx(source_plug, target, resolutionX=resolution,
                        resolutionY=resolution, fileImageName=path,
                        fileFormat="png", alpha=False)


def _verify_bake(path: str, job: Dict[str, Any]) -> Dict[str, Any]:
    """Did this bake actually sample anything? Refuses on the two measured
    ways a bake can be worthless: no file at all, and a flat image."""
    if not os.path.isfile(path):
        raise HandlerError(
            "the bake of %s.%s produced no file - convertSolidTx returned "
            "without writing %s" % (job["material"], job["attr"], path),
            hint="nothing in the scene was changed; check that the mesh has "
                 "UVs and that the texture network evaluates")
    check = pngprobe.uniformity(path)
    if check["non_uniform"] is None:
        raise HandlerError(
            "the bake of %s.%s could not be measured (%s) - refusing to "
            "rewire the scene to an image this tool cannot verify"
            % (job["material"], job["attr"], check["unavailable_reason"]),
            hint="nothing was changed; the file is at %s if you want to "
                 "look at it yourself" % path)
    if not check["non_uniform"]:
        raise HandlerError(
            "the bake of %s.%s is flat - every one of its %d pixels is the "
            "same value, which means the network sampled nothing"
            % (job["material"], job["attr"], check["pixel_count"]),
            hint="the usual cause is UV space: maya_uv_atlas gives the mesh "
                 "a layout the bake can sample through. Nothing in the scene "
                 "was changed")
    return check


def _rewire(cmds, job: Dict[str, Any], final_path: str) -> Dict[str, Any]:
    """Replace the procedural chain with a file node reading the bake.

    Per-slot shapes are the ones MEASURED to survive an FBX export:
    a colour slot takes file.outColor; a scalar takes file.outColorR with
    Raw colour space (assign_pbr's data-not-colour trap); a normal keeps
    its bump2d - bumpDepth is the authored look - and only its bumpValue
    source is replaced (probe P4 measured that path surviving export).
    """
    base = "%s_%s_baked" % (job["material"], job["slot"])
    node = cmds.shadingNode("file", asTexture=True,
                            name=naming.unique_name(cmds, base))
    cmds.setAttr(node + ".fileTextureName", final_path, type="string")
    raw = job["kind"] in ("scalar", "normal")
    if raw:
        cmds.setAttr(node + ".colorSpace", "Raw", type="string")
        # Without this, Maya's colour-management rules re-apply sRGB on
        # scene open and quietly undo the line above (the pbr precedent).
        cmds.setAttr(node + ".ignoreColorSpaceFileRules", True)

    place = cmds.shadingNode("place2dTexture", asUtility=True,
                             name=naming.unique_name(cmds, base + "_p2d"))
    for src, dst in pbr._PLACE2D_LINKS:
        try:
            cmds.connectAttr("%s.%s" % (place, src), "%s.%s" % (node, dst),
                             force=True)
        except Exception:  # noqa: BLE001 - attribute sets differ by version
            pass

    if job["kind"] == "normal" and job["bump_node"]:
        cmds.connectAttr(node + ".outAlpha",
                         job["bump_node"] + ".bumpValue", force=True)
        wired_plug = "outAlpha"
        kept = [job["bump_node"]]
    elif job["kind"] == "scalar":
        cmds.connectAttr(node + ".outColorR",
                         "%s.%s" % (job["material"], job["attr"]), force=True)
        wired_plug = "outColorR"
        kept = []
    else:
        cmds.connectAttr(node + ".outColor",
                         "%s.%s" % (job["material"], job["attr"]), force=True)
        wired_plug = "outColor"
        kept = []
    return {"file_node": node, "place": place, "wired_plug": wired_plug,
            "kept_intermediates": kept,
            "colorspace": "Raw" if raw else "sRGB"}


def _doomed_nodes(cmds, job: Dict[str, Any]) -> List[str]:
    """The replaced network's nodes, minus anything still feeding something
    else. apply_texture_recipe's zero-orphans value, inverted: delete what
    this call orphaned, never what somebody else is using."""
    terminal = job["terminal_plug"].split(".")[0]
    doomed = []
    for node in [terminal]:
        outputs = cmds.listConnections(node, source=False,
                                       destination=True) or []
        others = [o for o in outputs
                  if o != job["material"] and o not in job["via"]
                  and o != job["bump_node"]]
        if others:
            continue
        doomed.append(node)
    return doomed


def bake_textures(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    settings = validate(params, cmds)
    jobs, warnings = plan_bakes(cmds, settings["meshes"], settings["slots"])

    # --- phase A: bake and verify, mutating NOTHING -------------------
    staged: List[Dict[str, Any]] = []
    try:
        for job in jobs:
            part = os.path.join(settings["out_dir"],
                                job["basename"] + ".part.png")
            _convert_solid_tx(cmds, job["terminal_plug"], job["mesh"], part,
                              settings["resolution"])
            check = _verify_bake(part, job)
            staged.append({"job": job, "part": part, "check": check})
    except Exception:
        for entry in staged:
            try:
                os.unlink(entry["part"])
            except OSError:
                pass
        # the failing job's own part file, if it got that far
        for job in jobs:
            part = os.path.join(settings["out_dir"],
                                job["basename"] + ".part.png")
            if os.path.exists(part) and not any(e["part"] == part
                                                for e in staged):
                try:
                    os.unlink(part)
                except OSError:
                    pass
        raise

    # --- phase B: every bake verified, so commit ----------------------
    checkpoint = session.auto_checkpoint("bake_textures")
    baked = []
    for entry in staged:
        job, part = entry["job"], entry["part"]
        final_path = os.path.join(settings["out_dir"], job["basename"])
        os.replace(part, final_path)
        doomed = _doomed_nodes(cmds, job)
        wiring = _rewire(cmds, job, final_path.replace("\\", "/"))
        if doomed:
            cmds.delete(*doomed)
        baked.append({
            "material": job["material"], "slot": job["slot"],
            "attr": job["attr"], "file": final_path,
            "basename": job["basename"], "resolution": settings["resolution"],
            "colorspace": wiring["colorspace"],
            "wired_plug": wiring["wired_plug"],
            "kept_intermediates": wiring["kept_intermediates"],
            "deleted_nodes": doomed, "pixel_check": entry["check"],
        })

    # Postcondition: the slot must no longer read as procedural. A bake
    # that "succeeded" while leaving the claim procedural is a bug in this
    # tool, not a caller error - so it raises rather than warning.
    remaining = texclaim.material_claims(cmds, settings["meshes"])
    still = [c for c in remaining
             if c["classification"] == "procedural"
             and any(b["material"] == c["material"] and b["attr"] == c["attr"]
                     for b in baked)]
    if still:
        raise HandlerError(
            "POSTCONDITION FAILED: %s still reads as procedural after "
            "baking - the scene has been modified and a checkpoint (%s) "
            "was taken before the change"
            % (", ".join("%s.%s" % (c["material"], c["attr"]) for c in still),
               checkpoint["checkpoint_id"]),
            hint="maya_restore_checkpoint returns the scene; this is a bug "
                 "in maya_bake_textures, please report the network shape")

    return {
        "meshes": settings["meshes"], "out_dir": settings["out_dir"],
        "resolution": settings["resolution"], "baked": baked,
        "skipped_file_backed": [w for w in warnings
                                if "already file-backed" in w],
        "checkpoint_id": checkpoint["checkpoint_id"],
        "warnings": warnings,
    }
```

- [ ] **Step 4: Run the file**

```bash
python -m pytest tests/test_texbake.py -q
```

Expected: PASS, 17 tests.

- [ ] **Step 5: Run the full headless suite**

```bash
python -m pytest tests -q --junitxml=$env:TEMP\t714p2_t3.xml
```

Expected: 1581 + this branch's new tests, 0 failures. Read the XML.

- [ ] **Step 6: Commit**

```bash
git add maya_plugin/handlers/texbake.py tests/test_texbake.py
git commit -m "feat(#714): the two-phase bake - verify everything before touching the scene"
```

---

### Task 4: Register the tool (dispatcher + MCP surface + docs)

**Files:**
- Modify: the plugin's command table (grep for `"export_fbx":` in `maya_plugin/` to find where handlers are registered)
- Modify: `src/maya_mcp/schemas.py`, `src/maya_mcp/server.py`
- Modify: `maya_plugin/handlers/texture_recipes.py`
- Modify: `docs/protocol.md`
- Modify: `tests/test_server_tools.py`, `tests/test_texture_recipes.py`

**Interfaces:**
- Consumes: `texbake.bake_textures`'s result shape (Task 3).
- Produces: the `bake_textures` command; `BakedMap`/`BakeTexturesResult` models; the `maya_bake_textures` MCP tool.

- [ ] **Step 1: Write the failing wrapper tests**

Read `tests/test_server_tools.py`'s existing helpers first (phase 1 added `_export_result_with`/`_capture_request`-style helpers — reuse the file's real ones). Add:

```python
def test_bake_textures_forwards_the_baked_list():
    """#714 phase 2: BakeTexturesResult is extra='ignore', so an undeclared
    field is dropped silently on the way to the caller (the #757 class)."""
    result = _bake_result_with(
        baked=[{"material": "skin_mat", "slot": "color", "attr": "baseColor",
                "file": "C:/out/skin_mat_color_baked.png",
                "basename": "skin_mat_color_baked.png", "resolution": 1024,
                "colorspace": "sRGB", "wired_plug": "outColor",
                "kept_intermediates": [], "deleted_nodes": ["mcpTex_noise"],
                "pixel_check": {"pixel_count": 1048576,
                                "distinct_values": 186,
                                "non_uniform": True,
                                "unavailable_reason": None}}],
        warnings=["skin_mat is worn by 2 meshes"])
    assert result.baked[0].basename == "skin_mat_color_baked.png"
    assert result.baked[0].pixel_check.non_uniform is True
    assert result.baked[0].deleted_nodes == ["mcpTex_noise"]
    assert result.checkpoint_id
    assert result.warnings


def test_bake_textures_passes_its_params_to_the_wire():
    sent = _capture_request(lambda tool: tool(
        meshes=["|body"], out_dir="C:/out", resolution=2048,
        slots=["color"]))
    assert sent["params"] == {"meshes": ["|body"], "out_dir": "C:/out",
                              "resolution": 2048, "slots": ["color"]}
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_server_tools.py -k bake -q
```

Expected: FAIL — no such tool / no such model.

- [ ] **Step 3: Add the models**

In `src/maya_mcp/schemas.py`:

```python
class PixelCheck(BaseModel):
    """Whether the baked image actually sampled anything."""

    model_config = ConfigDict(extra="ignore")

    pixel_count: int
    distinct_values: int
    non_uniform: Optional[bool] = Field(default=None, description=(
        "True when the image carries more than one distinct pixel value. "
        "False means the bake is flat - the network sampled nothing, which "
        "is what a UV-less mesh produces (Maya does not refuse it). None "
        "means the image could not be read; see unavailable_reason."))
    unavailable_reason: Optional[str] = None


class BakedMap(BaseModel):
    """One procedural network, now a file texture the FBX can carry."""

    model_config = ConfigDict(extra="ignore")

    material: str
    slot: str
    attr: str
    file: str = Field(description="Absolute path of the image written.")
    basename: str = Field(description=(
        "The name a consumer sees in the FBX's Texture/Video records - the "
        "same string maya_export_fbx reports in textures.file_maps."))
    resolution: int
    colorspace: str = Field(description=(
        "'Raw' for scalar and normal data, 'sRGB' for colour. Data read as "
        "colour renders quietly wrong."))
    wired_plug: str = Field(description=(
        "Which plug of the new file node drives the slot: outColor, "
        "outColorR, or outAlpha (into the kept bump2d)."))
    kept_intermediates: List[str] = Field(default_factory=list, description=(
        "Nodes deliberately preserved - a normal slot keeps its bump2d "
        "because bumpDepth is part of the authored look."))
    deleted_nodes: List[str] = Field(default_factory=list, description=(
        "The replaced procedural nodes. Nodes still feeding something else "
        "are left alone and named in warnings."))
    pixel_check: PixelCheck


class BakeTexturesResult(BaseModel):
    """What maya_bake_textures changed in the scene, and where the images went.

    The rewire is PERSISTENT: the next render shows exactly what an export
    will carry. Re-judge it before exporting - that is the whole point of
    baking as a scene edit rather than an export-time trick.
    """

    model_config = ConfigDict(extra="ignore")

    meshes: List[str]
    out_dir: str
    resolution: int
    baked: List[BakedMap] = Field(default_factory=list)
    skipped_file_backed: List[str] = Field(default_factory=list, description=(
        "Slots that already read from a file and needed no bake."))
    checkpoint_id: str = Field(description=(
        "Taken before the scene was modified; maya_restore_checkpoint "
        "returns the pre-bake state."))
    warnings: List[str] = Field(default_factory=list)
```

- [ ] **Step 4: Add the tool**

In `src/maya_mcp/server.py`, beside the other texture tools (copy the surrounding tool's decorator/annotation idiom exactly):

```python
    @mcp.tool(
        title="Bake procedural textures to files",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
    )
    def maya_bake_textures(
        meshes: Annotated[List[str], Field(description=(
            "Meshes whose materials should be baked. A material worn by "
            "several of them is baked ONCE - the bake samples through UV "
            "space, not world geometry (measured)."
        ))],
        out_dir: Annotated[str, Field(description=(
            "Absolute directory the images are written to. It must already "
            "exist; there is no default, because a guessed location is how "
            "bake files get lost from a delivery."
        ))],
        resolution: Annotated[int, Field(description=(
            "Square bake size: 256, 512, 1024, 2048 or 4096."
        ))] = 1024,
        slots: Annotated[Optional[List[str]], Field(description=(
            "Limit the bake to these slots (color, emission_color, "
            "metalness, roughness, normal). Omit to bake every procedural "
            "slot found."
        ))] = None,
    ) -> BakeTexturesResult:
        """Turn procedural texture networks into file textures the FBX can carry.

        Maya's FBX exporter cannot write a procedural network at all, so a
        noise/ramp/layered look is judged in renders and then silently
        missing from the exported file. This bakes those networks to images
        and REWIRES THE SCENE to use them, so the next render is what
        actually ships - re-judge it, then export.

        Nothing is changed unless every requested bake succeeds and is
        verified to have sampled something; a checkpoint is taken before the
        rewire either way."""
        return BakeTexturesResult.model_validate(
            maya.request(
                "bake_textures",
                {"meshes": meshes, "out_dir": out_dir,
                 "resolution": resolution, "slots": slots},
                timeout_s=EXPORT_TIMEOUT_S,
            )
        )
```

Register the handler in the plugin's command table next to `export_fbx` (`"bake_textures": texbake.bake_textures`), importing `texbake` where the other handlers are imported.

- [ ] **Step 5: Extend the recipe warning now that the tool exists**

In `maya_plugin/handlers/texture_recipes.py`, the procedural-recipe warning phase 1 added currently ends "use file textures … for anything that must survive export". Now that the bake tool exists, name it — and add the no-UV early signal the spec asks for:

```python
    warnings: List[str] = []
    if recipe != "file_texture":
        warnings.append(
            "this recipe builds a procedural network that Maya's FBX "
            "exporter silently drops - maya_export_fbx reports it in "
            "textures.dropped_maps; maya_bake_textures converts it to a "
            "file texture that does survive")
        if not (cmds.polyEvaluate(shape, uvcoord=True) or 0):
            warnings.append(
                "this mesh has no UVs, so maya_bake_textures will refuse it "
                "- maya_uv_atlas creates a layout (project='box' is enough "
                "for tiling detail)")
```

Update `tests/test_texture_recipes.py`'s existing warning test to the new text and add one for the no-UV signal (the fake needs a `polyEvaluate` returning 0).

- [ ] **Step 6: Update `docs/protocol.md`**

Add a `bake_textures` row to the tool table with its params and result, and a short paragraph: the rewire is persistent, so post-bake renders are what the export carries; nothing changes unless every bake verifies; a checkpoint is taken before the rewire; a mesh with no UVs is refused because Maya silently bakes a flat image instead of erroring; a material worn by several meshes bakes once. Also update the export_fbx texture paragraph's remedy line to name `maya_bake_textures`.

- [ ] **Step 7: Run the affected suites**

```bash
python -m pytest tests/test_server_tools.py tests/test_texture_recipes.py tests/test_texbake.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add maya_plugin src/maya_mcp docs/protocol.md tests
git commit -m "feat(#714): register maya_bake_textures and point the recipe warning at it"
```

---

### Task 5: Real Maya — bake, export, and prove the map survives

**Files:**
- Modify: `tests/test_handlers_mayapy.py` (new class beside `TestTextureHonestyInMaya`)

**Interfaces:**
- Consumes: everything from Tasks 1-4.
- Produces: measured facts recorded in docstrings.

This is the task that proves the tool does what the ticket promised: a look that vanished from the FBX before now arrives in it. **Real Maya is the contract** — if an assertion fails, fix the PRODUCT to the measured truth and record the measurement; never force a literal.

- [ ] **Step 1: Write the tests**

```python
class TestBakeTexturesInMaya:
    """#714 phase 2 against a real exporter. The claim under test is the
    whole point of the ticket: a procedural look that CANNOT survive an
    FBX export does survive once baked."""

    def test_a_baked_noise_survives_the_export_that_dropped_it(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import (export, material, texbake,
                                          texture_recipes, uvatlas)

        mesh = cmds.ls(cmds.polyCube(name="bake_cube")[0], long=True)[0]
        uvatlas.uv_atlas({"mesh": mesh, "project": "box"})
        material.assign_material({"mesh": mesh, "material": "bake_mat",
                                  "shader": "standardSurface"})
        recipe = texture_recipes.apply_texture_recipe({
            "mesh": mesh, "recipe": "ramp_gradient"})
        ramp = [n for n in recipe["nodes"] if "ramp" in n][0]

        # BEFORE: the export drops it and says so (phase 1's report).
        before_path = str(tmp_path / "before.fbx").replace("\\", "/")
        before = export.export_fbx({"path": before_path,
                                    "metres_per_unit": 1.0, "nodes": [mesh]})
        assert [d["terminal"] for d in before["textures"]["dropped_maps"]] \
            == [ramp]

        out_dir = str(tmp_path).replace("\\", "/")
        baked = texbake.bake_textures({"meshes": [mesh], "out_dir": out_dir})
        assert len(baked["baked"]) == 1
        entry = baked["baked"][0]
        assert entry["pixel_check"]["non_uniform"] is True
        assert os.path.isfile(entry["file"])

        # AFTER: nothing is dropped, and the image is IN the bytes.
        after_path = str(tmp_path / "after.fbx").replace("\\", "/")
        after = export.export_fbx({"path": after_path,
                                   "metres_per_unit": 1.0, "nodes": [mesh]})
        assert after["textures"]["dropped_maps"] == []
        names = [m["basename"] for m in after["textures"]["file_maps"]]
        assert entry["basename"] in names
        assert all(m["found_in_file"] for m in after["textures"]["file_maps"])
        with open(after_path, "rb") as fh:
            assert entry["basename"].encode() in fh.read()

    def test_a_baked_scene_passes_require_baked_textures(self, tmp_path):
        """The contract phase 1 gave a delivery gate now has a way to be
        satisfied rather than only refused."""
        import maya.cmds as cmds

        from maya_plugin.handlers import (export, material, texbake,
                                          texture_recipes, uvatlas)

        mesh = cmds.ls(cmds.polyCube(name="strict_bake")[0], long=True)[0]
        uvatlas.uv_atlas({"mesh": mesh, "project": "box"})
        material.assign_material({"mesh": mesh, "material": "strict_bake_mat",
                                  "shader": "standardSurface"})
        texture_recipes.apply_texture_recipe({"mesh": mesh,
                                              "recipe": "noise_bump"})
        texbake.bake_textures({"meshes": [mesh],
                               "out_dir": str(tmp_path).replace("\\", "/")})
        path = str(tmp_path / "strict.fbx").replace("\\", "/")
        out = export.export_fbx({"path": path, "metres_per_unit": 1.0,
                                 "nodes": [mesh],
                                 "require_baked_textures": True})
        assert out["textures"]["dropped_maps"] == []

    def test_a_uvless_mesh_is_refused_and_nothing_is_written(self, tmp_path):
        """MEASURED (probe P2c): convertSolidTx does NOT raise here - it
        writes a flat image. The refusal is ours, and it must fire before
        any file appears."""
        import maya.cmds as cmds
        import pytest as _pytest

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import (material, texbake, texture_recipes)

        mesh = cmds.ls(cmds.polyCube(name="nouv_cube")[0], long=True)[0]
        shape = cmds.listRelatives(mesh, shapes=True, fullPath=True)[0]
        cmds.polyMapDel(shape + ".map[*]")
        material.assign_material({"mesh": mesh, "material": "nouv_mat",
                                  "shader": "standardSurface"})
        texture_recipes.apply_texture_recipe({"mesh": mesh,
                                              "recipe": "ramp_gradient"})
        out_dir = str(tmp_path).replace("\\", "/")
        with _pytest.raises(HandlerError, match="no UVs"):
            texbake.bake_textures({"meshes": [mesh], "out_dir": out_dir})
        assert os.listdir(out_dir) == []

    def test_a_shared_material_bakes_once_for_both_meshes(self, tmp_path):
        """MEASURED (probe P2d/P2e): sampling is mesh-independent, so one
        image serves every wearer - and both meshes must end up reading it."""
        import maya.cmds as cmds

        from maya_plugin.handlers import (material, texbake, texclaim,
                                          texture_recipes, uvatlas)

        a = cmds.ls(cmds.polyCube(name="share_a")[0], long=True)[0]
        b = cmds.ls(cmds.polyCube(name="share_b")[0], long=True)[0]
        for mesh in (a, b):
            uvatlas.uv_atlas({"mesh": mesh, "project": "box"})
        material.assign_material({"mesh": a, "material": "shared_mat",
                                  "shader": "standardSurface"})
        material.assign_material({"mesh": b, "material": "shared_mat",
                                  "shader": "standardSurface"})
        texture_recipes.apply_texture_recipe({"mesh": a,
                                              "recipe": "ramp_gradient"})
        out = texbake.bake_textures({"meshes": [a, b],
                                     "out_dir": str(tmp_path).replace("\\", "/")})
        assert len(out["baked"]) == 1
        shapes = [cmds.listRelatives(m, shapes=True, fullPath=True)[0]
                  for m in (a, b)]
        claims = texclaim.material_claims(cmds, shapes)
        assert claims and all(c["classification"] == "file" for c in claims)
```

- [ ] **Step 2: Run the class**

```bash
E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -k BakeTextures -q --junitxml=$env:TEMP\t714p2_t5.xml
```

Expected: 4 passed. Read the XML.

- [ ] **Step 3: Run the full mayapy suite**

```bash
E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q --junitxml=$env:TEMP\t714p2_t5full.xml; echo "exit=$LASTEXITCODE"
```

Expected: exit=0, 175 tests (171 baseline + 4). Note that these tests add animated-export-free FBX writes only; if the count differs, say which tests appeared or vanished.

- [ ] **Step 4: Commit**

```bash
git add tests/test_handlers_mayapy.py
git commit -m "test(#714): real Maya - a baked look survives the export that dropped it"
```

---

### Task 6: The live gate

**Files:**
- Create: `evals/texbake_live.py`

**Interfaces:**
- Consumes: the MCP tool surface over TCP (follow `evals/live_call.py`'s client pattern, and `evals/drifter_live.py`'s check-recording style — read both first).

The gate encodes the thing headless tests structurally cannot: that the pixels a builder judges after baking are the pixels that ship. It renders BEFORE and AFTER and reports both for judgment.

- [ ] **Step 1: Launch and verify your own Maya**

Follow the Global Constraints live-Maya rule exactly: launch on 9877 with the repo as CWD, verify the listener pid matches your process, `cmds.about(batch=True)` is False, and `maya_plugin.__file__` is under `D:\devel\maya-mcp`.

- [ ] **Step 2: Write the gate**

`evals/texbake_live.py`, with a `--build`-style self-contained fixture (the phase-1 lesson: a gate that needs an uncommitted driver is not a gate). It must:

1. Build a fresh scene: a cube, `uv_atlas` box projection, `assign_material`, and all three procedural recipes across different slots (`ramp_gradient` on colour, `noise_bump` on normal, plus a `file_texture` so a survivor is in the mix).
2. `render_scene` BEFORE the bake; keep the path.
3. `export_fbx` BEFORE — record `textures.dropped_maps` (the loss, measured).
4. `bake_textures` — record every `baked` entry's `pixel_check` and file size.
5. `render_scene` AFTER; keep the path.
6. `export_fbx` AFTER — assert `dropped_maps` is empty, every `file_maps` entry has `found_in_file: True`, and each baked basename's bytes are in the file (open it and check).
7. Assert `require_baked_textures=True` now PASSES on the same scene.
8. Print a verdict line with measured numbers: dropped-before count, baked count, distinct-pixel values per bake, dropped-after count, and both render paths.

Report both render images for judgment (the before/after pair is the gate's real product — a bake that ships a visibly wrong image passes every byte check).

- [ ] **Step 3: Run it**

```bash
$env:MAYA_MCP_PORT='9877'; python evals\texbake_live.py --build
```

Report the verdict line verbatim. **Look at both renders** and say whether the AFTER render still reads as the material the BEFORE render showed — a bake that is technically present but visually wrong is a finding, not a pass.

- [ ] **Step 4: Kill your Maya, verify the port released**

```bash
taskkill /F /T /PID <your pid>
```

- [ ] **Step 5: Commit**

```bash
git add evals/texbake_live.py
git commit -m "test(#714): live gate - the pixels judged after baking are the pixels exported"
```

---

### Task 7: Whole-branch verification

- [ ] **Step 1: Full headless suite**

```bash
python -m pytest tests -q --junitxml=$env:TEMP\t714p2_final.xml
```

Expected: 1581 baseline + every test this branch added; 0 failures.

- [ ] **Step 2: Full mayapy suite, twice**

```bash
E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q --junitxml=$env:TEMP\t714p2_mp1.xml; echo "exit=$LASTEXITCODE"
E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q --junitxml=$env:TEMP\t714p2_mp2.xml; echo "exit=$LASTEXITCODE"
```

Expected: exit=0 both runs (a non-zero exit is the #729 teardown class — investigate, do not retry away).

- [ ] **Step 3: Docs coherence**

```bash
git diff main...HEAD -- docs/protocol.md
```

Check the `bake_textures` entry against shipped behavior: params, result fields, the persistent-rewire statement, the checkpoint, the no-UV refusal, bake-once-per-material. Confirm the export_fbx remedy line now names the tool. Fix docs gaps; change no product code.

- [ ] **Step 4: Staging check**

```bash
git status --short
```

`evals/golem_rerun_665/out_v4/` must still be untracked and unmodified.

- [ ] **Step 5: Commit any fixes**

```bash
git add docs tests evals
git commit -m "test(#714): whole-branch verification for phase 2"
```

- [ ] **Step 6: Review, merge, deploy, ticket**

Use superpowers:requesting-code-review on `git diff main...HEAD`; fix findings; use superpowers:finishing-a-development-branch to merge to `main`; deploy with `python maya_plugin/install.py --yes` and report the stamp (running Mayas hold old modules until restart). Then update #714 with the measured suite counts, the live gate verdict, the before/after render judgment, and set it **Resolved** — phase 2 closes the ticket.

---

## Self-Review

**Spec coverage (§3):** params → Task 2; mechanics/per-slot wiring → Task 3; part-file + two-phase all-or-nothing + checkpoint → Task 3; deletion policy → Task 3 (`_doomed_nodes`); postcondition re-walk → Task 3; refusals (no-UV, normal-without-bump2d, unresolved chains) → Tasks 2-3; warnings (shared material, placement scope limit, already-file-backed) → Task 2; §3.4 shared-material arm → Task 2 (permissive, per the probe) with a mayapy proof in Task 5; §3.5 tests → Tasks 1-6.

**Deliberate spec deviations, both reported here rather than silently taken:** (1) the spec's `capture_before`/`capture_after` fields are NOT in the result — the live gate renders and judges the pair instead, which is where judgment actually happens, and a viewport capture inside a batch-mode handler is null anyway; if the reviewer wants the fields, they are a small addition to Task 3. (2) The spec floats a UV-bbox-outside-[0,1] warning; the probes measured box-projection UVs baking usably, so it would fire on the normal case and is omitted as noise.

**Placeholder scan:** every step carries real code or an exact command. Task 6's gate is described as numbered requirements rather than a full listing because it composes existing tools over TCP and the file's own style must be matched — the requirements are exact and each is independently checkable.

**Type consistency:** job dicts carry the same keys across Tasks 2-3 (`material`, `sg`, `attr`, `slot`, `kind`, `terminal_plug`, `mesh`, `meshes`, `via`, `bump_node`, `basename`); `pngprobe.uniformity`'s four keys are identical in Tasks 1, 3 and the schema; `bake_textures`'s result keys match the models in Task 4 field-for-field.
