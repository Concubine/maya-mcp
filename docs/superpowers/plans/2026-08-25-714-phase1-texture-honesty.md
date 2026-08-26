# #714 Phase 1 — Export Texture Honesty Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `maya_export_fbx` tell the truth about texture maps — name every procedural map the FBX exporter drops, byte-verify that every file-backed map actually reached the file, and refuse on demand — so a flat-shipped asset can never again pass as green.

**Architecture:** A new pure-ish walker module (`texclaim.py`) produces the SCENE's claim about what each exported material carries; `fbxbytes.py` learns to parse Texture/Video records so the FILE's side can be measured; a new pure comparator (`export.texture_violations`) puts the two together and feeds the existing refusal flow. No baking, no scene mutation, no MEL-preamble changes. Phase 2 (the bake tool) is a separate plan, gated on the five probes this plan also runs.

**Tech Stack:** Python (Maya plugin + FastMCP server), pytest headless (`python -m pytest tests -q`), mayapy suite (`E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q`), live gates in `evals/` driven over TCP against an agent-launched Maya.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-25-714-export-texture-honesty-design.md` (committed `d44f1aa`). Where this plan and the spec disagree, the spec governs — report the conflict rather than silently diverging.
- Branch: `fix-714-texture-honesty` off `main`. Commits: `feat(#714): …` / `fix(#714): …` / `test(#714): …` / `docs(#714): …`.
- **Never touch `evals/golem_rerun_665/out_v4/`** (another agent's untracked work) and never regenerate anything else under `evals/golem_rerun_665/`.
- Measure suites with `--junitxml=$env:TEMP\<name>.xml` and read counts from the XML — the pytest summary line is lost to stdout buffering on this machine. Report MEASURED numbers, never "tests pass".
- mayapy: `E:\Autodesk\Maya2027\bin\mayapy.exe`. The mayapy suite is ONE persistent process; module state persists across tests by design.
- **Live Maya rule:** the MCP server `maya` reaches `127.0.0.1:9877`; the server `maya9879` is the USER'S art session — **never call any `mcp__maya9879__*` tool**. Launch your own: `$env:MAYA_MCP_PORT='9877'; Start-Process 'E:\Autodesk\Maya2027\bin\maya.exe' -WorkingDirectory 'D:\devel\maya-mcp'`, poll `Test-NetConnection 127.0.0.1 -Port 9877 -InformationLevel Quiet`, then VERIFY the listener's pid matches the process you started (`Get-NetTCPConnection -LocalPort 9877 -State Listen`) before trusting anything. Kill only your own pid with `taskkill /F /T /PID <pid>` and verify the port released. If the MCP tools are unreachable: STOP and report, no fallbacks.
- Windows shell is PowerShell; `&&` is unavailable — chain with `;`.
- `docs/protocol.md` is the tool contract: every result-shape or parameter change lands there in the same task as the code.
- Baseline at branch time: headless 1528 pass + 1 skip; mayapy 164 pass + 1 skip.

## File Structure

| File | Responsibility |
|---|---|
| `maya_plugin/handlers/texclaim.py` (create) | The scene's texture claim: pure classification helpers + one `cmds`-touching walker. Shared by export now and the phase-2 bake tool later. |
| `maya_plugin/handlers/fbxbytes.py` (modify) | Gains Texture/Video record parsing + `texture_facts(facts)`, alongside the existing skin/shape/anim fact composers. |
| `maya_plugin/handlers/export.py` (modify) | Gains `require_baked_textures` validation, the pure `texture_violations` comparator, the pre-write strict refusal, and the `textures`/`warnings` result fields. |
| `maya_plugin/handlers/texture_recipes.py` (modify) | One authoring-time warning on the three procedural recipes. |
| `src/maya_mcp/schemas.py`, `src/maya_mcp/server.py` (modify) | `TextureFacts`/`FileMapFact`/`DroppedMapFact` models, two new `ExportFbxResult` fields, the new tool parameter. |
| `tests/test_texclaim.py` (create) | Pure classification + walker tests over fake cmds. |
| `tests/test_export_fbx.py`, `tests/test_fbxbytes.py`, `tests/test_texture_recipes.py`, `tests/test_server_tools.py` (modify) | Violation matrix, byte parsing against the committed fixture, recipe warning, wrapper forwarding. |
| `tests/test_handlers_mayapy.py` (modify) | Real-Maya export-then-read-bytes proofs. |
| `evals/drifter_live.py` (modify) | Live gate: the product's `textures` block cross-checked against the eval's own independent walker. |
| `evals/bake_probe_714.py` (create) | The five probes. Standalone, not part of any suite. |

---

### Task 1: `texclaim.py` — the scene's claim

**Files:**
- Create: `maya_plugin/handlers/texclaim.py`
- Create: `tests/test_texclaim.py`

**Interfaces:**
- Consumes: `pbr.SLOTS` (`{slot: (attr, kind)}`), `material.SHADER_SLOTS` (`{shader_type: {slot: attr}}`) — both already exist.
- Produces:
  - `AUTHORED_ATTRS: tuple[str, ...]` — derived at import from those two tables.
  - `PASS_THROUGH_TYPES = ("bump2d", "reverse")`
  - `SLOT_FOR_ATTR: dict[str, str]` — attr → semantic slot name (first match wins across the two tables).
  - `classify(terminals) -> str` — `"file"` when every terminal is a file node, `"procedural"` when any is not, `"value"` when there are none. `terminals` is a list of `{"node": str, "type": str}`.
  - `material_claims(cmds, shapes) -> list[dict]` — one dict per (shape, shader, attr) with keys: `mesh`, `material`, `sg`, `attr`, `slot` (or `None`), `classification`, `terminals` (list of `{node, type, file_path, basename, on_disk, colorspace}` — the file-only keys are `None` for procedural terminals), `via` (intermediate node types in walk order), `semantics_lost` (list of strings).

- [ ] **Step 1: Write the failing pure-classification tests**

Create `tests/test_texclaim.py`:

```python
"""#714: the scene-side texture claim. Pure classification first; the
walker's cmds surface is faked below the way test_texture_recipes.py does."""

import pytest

from maya_plugin.handlers import texclaim


class TestAuthoredAttrs:
    def test_derived_from_the_slot_tables_not_copied(self):
        # #714: a new slot in pbr.SLOTS or material.SHADER_SLOTS must widen
        # the walk automatically - a copied constant is how a slot silently
        # falls out of the claim.
        from maya_plugin.handlers import material, pbr

        expected = {attr for attr, _kind in pbr.SLOTS.values()}
        for slots in material.SHADER_SLOTS.values():
            expected |= set(slots.values())
        assert set(texclaim.AUTHORED_ATTRS) == expected
        assert "baseColor" in texclaim.AUTHORED_ATTRS
        assert "normalCamera" in texclaim.AUTHORED_ATTRS
        assert "eccentricity" in texclaim.AUTHORED_ATTRS

    def test_slot_for_attr_maps_back(self):
        assert texclaim.SLOT_FOR_ATTR["baseColor"] == "color"
        assert texclaim.SLOT_FOR_ATTR["normalCamera"] == "normal"
        assert texclaim.SLOT_FOR_ATTR.get("nosuchattr") is None


class TestClassify:
    def test_all_file_terminals_are_a_file_claim(self):
        assert texclaim.classify([{"node": "t", "type": "file"}]) == "file"

    def test_any_non_file_terminal_makes_it_procedural(self):
        # The MIX is what the exporter loses: a layeredTexture blending two
        # real files still cannot travel.
        assert texclaim.classify([
            {"node": "a", "type": "file"},
            {"node": "b", "type": "layeredTexture"}]) == "procedural"

    def test_no_terminals_is_a_value(self):
        assert texclaim.classify([]) == "value"
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_texclaim.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'maya_plugin.handlers.texclaim'`.

- [ ] **Step 3: Write the pure half of the module**

Create `maya_plugin/handlers/texclaim.py`:

```python
"""The scene's claim about what texture maps each material carries (#714).

Maya's FBX exporter silently drops procedural texture networks: a `file`
node survives as a Texture+Video record pair carrying the image basename,
and anything else (noise, ramp, layeredTexture) vanishes with no API-visible
signal. MEASURED in evals/drifter_live.py's texture probe: 1 Texture + 1
Video for the file node, zero occurrences of the procedural node names.

The export gate needs to know what the scene THINKS it has before it can
say what the file lost - and nothing records that: no metadata node, and
node naming is inconsistent across the two authoring tools (mcpTex_* in
texture_recipes.py, <material>_<slot>_* in pbr.py). So the only honest
answer is to walk the shading graph. This module is that walk, split the
usual way: pure classification here, one cmds-touching enumerator below.

It is deliberately shared with the phase-2 bake tool: two walkers would be
two things to get wrong.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from . import material, pbr

# Every attribute this toolbox's authoring surface can drive. DERIVED from
# the slot tables rather than copied, so a new slot cannot silently fall out
# of the claim. A hand-wired texture on an attr outside this union is not
# claimed - it surfaces as an "unclaimed record" WARNING at the gate, never
# a violation (refusing a file we failed to enumerate would be worse than
# the gap).
_ATTRS: List[str] = [attr for attr, _kind in pbr.SLOTS.values()]
for _slots in material.SHADER_SLOTS.values():
    _ATTRS.extend(_slots.values())
AUTHORED_ATTRS = tuple(sorted(set(_ATTRS)))

# attr -> the semantic slot name callers know it by. First table wins; the
# two agree wherever they overlap (baseColor is "color" in both).
SLOT_FOR_ATTR: Dict[str, str] = {}
for _slot, (_attr, _kind) in pbr.SLOTS.items():
    SLOT_FOR_ATTR.setdefault(_attr, _slot)
for _slots in material.SHADER_SLOTS.values():
    for _slot, _attr in _slots.items():
        SLOT_FOR_ATTR.setdefault(_attr, _slot)

# The only intermediates the walk steps THROUGH. bump2d carries a map into
# normalCamera (assign_pbr and the noise_bump recipe both use it); reverse
# is assign_pbr's invert. place2dTexture is placement, not content, and is
# never a terminal or a pass-through - it feeds the file node's uv plugs,
# which the walk does not follow.
PASS_THROUGH_TYPES = ("bump2d", "reverse")

# Plugs that select ONE channel of an image. FBX carries the image, never
# the swizzle, so a claim wired this way is reported as semantics_lost.
_SWIZZLE_PLUGS = ("outColorR", "outColorG", "outColorB", "outAlpha")

# A pathological or hand-built graph must not hang the export.
MAX_DEPTH = 8


def classify(terminals: List[Dict[str, Any]]) -> str:
    """"file", "procedural", or "value" for one slot's terminal set.

    A slot is a file claim ONLY when every terminal is a file node. Any
    non-file contributor anywhere upstream makes it procedural - a
    layeredTexture mixing two real files is procedural, because the MIX is
    what the exporter loses, not the images.
    """
    if not terminals:
        return "value"
    return ("file" if all(t["type"] == "file" for t in terminals)
            else "procedural")
```

- [ ] **Step 4: Run to verify the pure tests pass**

```bash
python -m pytest tests/test_texclaim.py -q
```

Expected: PASS (5 tests).

- [ ] **Step 5: Write the failing walker tests**

Append to `tests/test_texclaim.py`:

```python
class FakeCmds:
    """A shading graph, faked at the four calls the walker makes.

    Scene: |body has SG bodySG -> shader 'skin_mat' (standardSurface).
    Graphs are declared per test by writing `conns` and `types`.
    """

    def __init__(self):
        self.sets = {"|bodyShape": ["bodySG"]}
        # plug -> [source plugs]
        self.conns = {"bodySG.surfaceShader": ["skin_mat.outColor"]}
        self.types = {"skin_mat": "standardSurface"}
        self.attrs = {}          # "node.attr" -> value
        self.existing_attrs = set()   # "node.attr" the shader really has

    def listSets(self, object=None, type=None):
        return list(self.sets.get(object, []))

    def listConnections(self, plug, source=False, destination=True,
                        plugs=False, **kw):
        srcs = self.conns.get(plug) or []
        if not srcs:
            return None
        return list(srcs) if plugs else [s.split(".")[0] for s in srcs]

    def nodeType(self, node):
        return self.types.get(node, "transform")

    def attributeQuery(self, attr, node=None, exists=False):
        return ("%s.%s" % (node, attr)) in self.existing_attrs

    def getAttr(self, plug):
        return self.attrs.get(plug, "")

    def objExists(self, node):
        return node in self.types


def _shader_with(fake, attr, source_plug):
    fake.existing_attrs.add("skin_mat." + attr)
    fake.conns["skin_mat." + attr] = [source_plug]


class TestMaterialClaims:
    def test_a_file_texture_is_a_file_claim(self, tmp_path):
        image = tmp_path / "grain.png"
        image.write_bytes(b"x")
        fake = FakeCmds()
        fake.types["mcpTex_file"] = "file"
        fake.attrs["mcpTex_file.fileTextureName"] = str(image)
        fake.attrs["mcpTex_file.colorSpace"] = "sRGB"
        _shader_with(fake, "baseColor", "mcpTex_file.outColor")

        claims = texclaim.material_claims(fake, ["|bodyShape"])

        assert len(claims) == 1
        claim = claims[0]
        assert claim["classification"] == "file"
        assert claim["slot"] == "color"
        assert claim["attr"] == "baseColor"
        assert claim["material"] == "skin_mat"
        assert claim["terminals"][0]["basename"] == "grain.png"
        assert claim["terminals"][0]["on_disk"] is True
        assert claim["semantics_lost"] == []

    def test_a_missing_image_is_claimed_but_not_on_disk(self, tmp_path):
        fake = FakeCmds()
        fake.types["mcpTex_file"] = "file"
        fake.attrs["mcpTex_file.fileTextureName"] = str(tmp_path / "gone.png")
        _shader_with(fake, "baseColor", "mcpTex_file.outColor")

        claim = texclaim.material_claims(fake, ["|bodyShape"])[0]

        assert claim["classification"] == "file"
        assert claim["terminals"][0]["on_disk"] is False

    def test_noise_through_bump2d_is_procedural_and_records_the_via(self):
        fake = FakeCmds()
        fake.types["mcpTex_noise"] = "noise"
        fake.types["mcpTex_bump"] = "bump2d"
        fake.conns["mcpTex_bump.bumpValue"] = ["mcpTex_noise.outColorR"]
        _shader_with(fake, "normalCamera", "mcpTex_bump.outNormal")

        claim = texclaim.material_claims(fake, ["|bodyShape"])[0]

        assert claim["classification"] == "procedural"
        assert claim["slot"] == "normal"
        assert claim["via"] == ["bump2d"]
        assert claim["terminals"][0]["node"] == "mcpTex_noise"
        assert claim["terminals"][0]["type"] == "noise"

    def test_a_file_through_reverse_on_a_scalar_reports_semantics_lost(
            self, tmp_path):
        image = tmp_path / "rough.png"
        image.write_bytes(b"x")
        fake = FakeCmds()
        fake.types["rough_tex"] = "file"
        fake.types["rough_inv"] = "reverse"
        fake.attrs["rough_tex.fileTextureName"] = str(image)
        fake.attrs["rough_tex.colorSpace"] = "Raw"
        fake.conns["rough_inv.inputX"] = ["rough_tex.outColorR"]
        _shader_with(fake, "specularRoughness", "rough_inv.outputX")

        claim = texclaim.material_claims(fake, ["|bodyShape"])[0]

        assert claim["classification"] == "file"
        assert claim["via"] == ["reverse"]
        lost = " ".join(claim["semantics_lost"])
        assert "outColorR" in lost and "reverse" in lost and "Raw" in lost

    def test_a_layered_texture_mixing_a_file_is_procedural(self, tmp_path):
        image = tmp_path / "base.png"
        image.write_bytes(b"x")
        fake = FakeCmds()
        fake.types["mcpTex_layered"] = "layeredTexture"
        fake.types["inner_file"] = "file"
        fake.attrs["inner_file.fileTextureName"] = str(image)
        # the walk does NOT descend into layeredTexture: it is a terminal.
        fake.conns["mcpTex_layered.inputs[0].color"] = ["inner_file.outColor"]
        _shader_with(fake, "baseColor", "mcpTex_layered.outColor")

        claim = texclaim.material_claims(fake, ["|bodyShape"])[0]

        assert claim["classification"] == "procedural"
        assert [t["type"] for t in claim["terminals"]] == ["layeredTexture"]

    def test_an_unconnected_slot_is_not_claimed_at_all(self):
        fake = FakeCmds()
        fake.existing_attrs.add("skin_mat.baseColor")
        assert texclaim.material_claims(fake, ["|bodyShape"]) == []

    def test_a_cycle_terminates_and_reports_unresolved(self):
        fake = FakeCmds()
        fake.types["a"] = "bump2d"
        fake.types["b"] = "reverse"
        fake.conns["a.bumpValue"] = ["b.outputX"]
        fake.conns["b.inputX"] = ["a.outNormal"]
        _shader_with(fake, "normalCamera", "a.outNormal")

        claim = texclaim.material_claims(fake, ["|bodyShape"])[0]

        assert claim["classification"] == "procedural"
        assert any(t["type"] == "unresolved(depth)"
                   for t in claim["terminals"])

    def test_a_shape_with_no_shading_group_is_skipped_silently(self):
        fake = FakeCmds()
        assert texclaim.material_claims(fake, ["|otherShape"]) == []
```

- [ ] **Step 6: Run to verify failure**

```bash
python -m pytest tests/test_texclaim.py::TestMaterialClaims -q
```

Expected: FAIL with `AttributeError: module 'maya_plugin.handlers.texclaim' has no attribute 'material_claims'`.

- [ ] **Step 7: Write the walker**

Append to `maya_plugin/handlers/texclaim.py`:

```python
def _file_terminal(cmds, node: str) -> Dict[str, Any]:
    """The record for a `file` terminal: where its image is and whether it
    is actually there. `on_disk` matters at the gate - the exporter's
    behaviour for a missing image is UNMEASURED (#714 probe P5), so a
    claim whose image is absent only warns."""
    try:
        path = str(cmds.getAttr(node + ".fileTextureName") or "")
    except Exception:
        path = ""
    try:
        colorspace = str(cmds.getAttr(node + ".colorSpace") or "")
    except Exception:
        colorspace = ""
    return {"node": node, "type": "file", "file_path": path,
            "basename": os.path.basename(path) if path else "",
            "on_disk": bool(path) and os.path.isfile(path),
            "colorspace": colorspace}


def _other_terminal(node: str, node_type: str) -> Dict[str, Any]:
    return {"node": node, "type": node_type, "file_path": None,
            "basename": None, "on_disk": None, "colorspace": None}


def _walk_upstream(cmds, plug: str) -> tuple:
    """(terminals, via, swizzles) reached upstream of `plug`.

    Steps THROUGH PASS_THROUGH_TYPES only; everything else terminates. All
    upstream branches are followed (a layeredTexture is itself a terminal,
    so its inputs are never entered). Depth-capped and cycle-guarded: a
    graph the walk cannot resolve yields an "unresolved(depth)" terminal,
    which classifies procedural - conservative in the direction that
    REPORTS loss rather than promising survival.
    """
    terminals: List[Dict[str, Any]] = []
    via: List[str] = []
    swizzles: List[str] = []
    seen = set()
    frontier = [(plug, 0)]
    while frontier:
        current, depth = frontier.pop(0)
        sources = cmds.listConnections(current, source=True,
                                       destination=False, plugs=True) or []
        for source in sources:
            node = source.split(".")[0]
            attr = source.split(".", 1)[1] if "." in source else ""
            if attr in _SWIZZLE_PLUGS and attr not in swizzles:
                swizzles.append(attr)
            if node in seen or depth >= MAX_DEPTH:
                terminals.append(_other_terminal(node, "unresolved(depth)"))
                continue
            seen.add(node)
            node_type = cmds.nodeType(node)
            if node_type in PASS_THROUGH_TYPES:
                if node_type not in via:
                    via.append(node_type)
                frontier.append((node, depth + 1))
            elif node_type == "file":
                terminals.append(_file_terminal(cmds, node))
            else:
                terminals.append(_other_terminal(node, node_type))
    return terminals, via, swizzles
```

Note the frontier holds a NODE (not a plug) after the first hop: `listConnections` on a bare node name returns every source connection of that node, which is what a pass-through's upstream means here (bump2d's `.bumpValue`, reverse's `.input*`).

- [ ] **Step 8: Write the enumerator and the semantics report**

Append to `maya_plugin/handlers/texclaim.py`:

```python
def _semantics_lost(swizzles: List[str], via: List[str],
                    terminals: List[Dict[str, Any]]) -> List[str]:
    """What survives as an image but not as a wiring decision.

    FBX carries the image reference. It does not carry which channel was
    selected, an inverting reverse node, or a Raw colorspace declaration -
    all three are consumer-side rewires. Reported, never gated: refusing
    them would refuse assign_pbr's own recommended mask workflow.
    """
    lost: List[str] = []
    for plug in swizzles:
        lost.append("channel swizzle %s" % plug)
    if "reverse" in via:
        lost.append("reverse-invert")
    if any((t.get("colorspace") or "") == "Raw" for t in terminals):
        lost.append("Raw colorspace")
    return lost


def material_claims(cmds, shapes: List[str]) -> List[Dict[str, Any]]:
    """What the materials on `shapes` claim to carry, per slot.

    Scoped to the shapes being exported, the same way shape aliases and
    clips are. Never matches node NAMES (mcpTex_* vs <material>_<slot>_*
    are both real conventions in this toolbox) - only graph topology and
    node types.
    """
    claims: List[Dict[str, Any]] = []
    seen_pairs = set()
    for shape in shapes:
        for sg in cmds.listSets(object=shape, type=1) or []:
            shaders = cmds.listConnections(sg + ".surfaceShader",
                                           source=True) or []
            if not shaders:
                continue
            shader = shaders[0]
            for attr in AUTHORED_ATTRS:
                if not cmds.attributeQuery(attr, node=shader, exists=True):
                    continue
                key = (shader, attr)
                terminals, via, swizzles = _walk_upstream(
                    cmds, "%s.%s" % (shader, attr))
                classification = classify(terminals)
                if classification == "value":
                    continue
                if key in seen_pairs:
                    # One material on several exported shapes: claim it
                    # once, but record every mesh that wears it.
                    for claim in claims:
                        if (claim["material"], claim["attr"]) == key:
                            if shape not in claim["meshes"]:
                                claim["meshes"].append(shape)
                    continue
                seen_pairs.add(key)
                claims.append({
                    "mesh": shape,
                    "meshes": [shape],
                    "material": shader,
                    "sg": sg,
                    "attr": attr,
                    "slot": SLOT_FOR_ATTR.get(attr),
                    "classification": classification,
                    "terminals": terminals,
                    "via": via,
                    "semantics_lost": _semantics_lost(swizzles, via,
                                                      terminals),
                })
    return claims
```

- [ ] **Step 9: Run the full file**

```bash
python -m pytest tests/test_texclaim.py -q
```

Expected: PASS, 13 tests, no warnings.

- [ ] **Step 10: Commit**

```bash
git add maya_plugin/handlers/texclaim.py tests/test_texclaim.py
git commit -m "feat(#714): texclaim - the scene's per-slot texture claim"
```

---

### Task 2: `fbxbytes` — Texture and Video records

**Files:**
- Modify: `maya_plugin/handlers/fbxbytes.py` (the `FbxFacts` dataclass ~line 82-139; the `walk()` record dispatch ~line 254-319; a new fact composer beside `skin_facts`/`shape_facts`/`anim_facts`)
- Modify: `tests/test_fbxbytes.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  - `FbxFacts.textures: dict` — Texture uid → `{"name": str, "filename": str}`
  - `FbxFacts.videos: dict` — Video uid → same shape
  - `fbxbytes.texture_facts(facts) -> dict` — `{"texture_records": int, "video_records": int, "textures": [{"name", "basename"}], "videos": [{"name", "basename"}], "unavailable_reason": Optional[str]}`

- [ ] **Step 1: Find the committed fixture the parser is pinned against**

```bash
python -c "import glob; print([p for p in glob.glob('evals/**/*.fbx', recursive=True) if 'out_v4' not in p])"
```

Use the drifter FBX (the one `evals/drifter_live.py`'s texture probe measured: 1 Texture + 1 Video, a known PNG basename). Record the exact path and the measured basename in your report — the test below hardcodes them. If NO committed FBX carries a texture, say so in your report and build the fixture assertion from the mayapy test in Task 5 instead (do not invent numbers).

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_fbxbytes.py`:

```python
class TestTextureRecords:
    """#714: the reader must see the records the exporter DOES write for a
    file texture, so the gate can prove a claimed image reached the file.

    MEASURED (evals/drifter_live.py's texture probe): a file-textured
    export carries exactly one Texture and one Video object, and the image
    basename is in the bytes; procedural node names occur zero times.
    """

    def test_the_committed_fixture_carries_one_texture_and_video(self):
        facts = fbxbytes.read_fbx(FIXTURE_WITH_TEXTURE)   # from Step 1
        assert len(facts.textures) == 1
        assert len(facts.videos) == 1

    def test_texture_facts_reports_names_and_basenames(self):
        facts = fbxbytes.read_fbx(FIXTURE_WITH_TEXTURE)
        block = texture_facts_of(facts)
        assert block["texture_records"] == 1
        assert block["video_records"] == 1
        assert block["unavailable_reason"] is None
        basenames = {t["basename"] for t in block["textures"]} | {
            v["basename"] for v in block["videos"]}
        assert FIXTURE_TEXTURE_BASENAME in basenames

    def test_a_textureless_fixture_reports_zero_not_an_error(self):
        facts = fbxbytes.read_fbx(FIXTURE_WITHOUT_TEXTURE)
        block = fbxbytes.texture_facts(facts)
        assert block == {"texture_records": 0, "video_records": 0,
                         "textures": [], "videos": [],
                         "unavailable_reason": None}
```

Define `FIXTURE_WITH_TEXTURE`, `FIXTURE_TEXTURE_BASENAME`, and `FIXTURE_WITHOUT_TEXTURE` as module constants at the top of the class from Step 1's measurement, and replace `texture_facts_of` with `fbxbytes.texture_facts` (it appears once above only to keep the two assertions visually distinct — use the real name in both).

- [ ] **Step 3: Run to verify failure**

```bash
python -m pytest tests/test_fbxbytes.py::TestTextureRecords -q
```

Expected: FAIL — `AttributeError: 'FbxFacts' object has no attribute 'textures'`.

- [ ] **Step 4: Add the fields to `FbxFacts`**

In `maya_plugin/handlers/fbxbytes.py`, after the `takes` field (~line 139):

```python
    # Textures (#714). textures: Texture uid -> {"name", "filename"};
    # videos: Video uid -> the same. Maya writes a file texture as a
    # Texture object plus a Video object carrying the image path, and
    # writes NOTHING for a procedural network - which is the whole defect
    # #714 gates. Connections are deliberately not resolved: the gate
    # compares image BASENAMES against the scene's claim, and the claim
    # already knows which material each map belongs to.
    textures: dict = field(default_factory=dict)
    videos: dict = field(default_factory=dict)
```

- [ ] **Step 5: Parse the records**

In `walk()`, add two branches alongside `elif name == "Pose":` (~line 289). The filename arrives as a child `P` property record, so the branch stores the shell and a nested-property hook fills it:

```python
            elif name in ("Texture", "Video"):
                uid = values[0] if values and isinstance(values[0], int) else None
                strs = [v for v in values if isinstance(v, str)]
                if uid is not None:
                    record = {"name": _clean(strs[0]) if strs else "?",
                              "filename": ""}
                    if name == "Texture":
                        facts.textures[uid] = record
                    else:
                        facts.videos[uid] = record
                    child = ("texnode", uid, name)
```

and in the `P`-property handling (~line 239, the `elif name == "P"` block), extend the node-context branch:

```python
                elif isinstance(node, tuple) and node[0] == "texnode":
                    if key in ("FileName", "RelativeFilename", "Path",
                               "RelPath"):
                        store = (facts.textures if node[2] == "Texture"
                                 else facts.videos)
                        current = store.get(node[1])
                        if current is not None and not current["filename"]:
                            value = values[-1]
                            if isinstance(value, str):
                                current["filename"] = value
```

Also handle the bare `FileName`/`RelativeFilename` CHILD RECORD shape (Maya writes both forms depending on version): add, next to the `Vertices` branch, a branch that fills the same slot when `name in ("FileName", "RelativeFilename")` and `node` is a `("texnode", uid, kind)` tuple and `values and isinstance(values[0], str)`. Whichever form the fixture actually uses is what the Step 2 test pins — if only one form appears, KEEP both code paths (the other is a different Maya version's shape) and say in your report which one the fixture exercised.

- [ ] **Step 6: Add the fact composer**

Add beside the other `*_facts` functions:

```python
def texture_facts(facts):
    """Texture references the FILE carries (#714).

    Basenames, not paths: the exporter may rewrite a path to a relative
    form, and the basename is the part MEASURED to survive intact
    (evals/drifter_live.py's probe). A record whose filename could not be
    read reports an empty basename rather than being dropped - the gate
    then says so instead of silently missing a match.
    """
    def rows(store):
        return [{"name": rec["name"],
                 "basename": os.path.basename(rec["filename"])
                 if rec["filename"] else ""}
                for rec in store.values()]

    return {"texture_records": len(facts.textures),
            "video_records": len(facts.videos),
            "textures": rows(facts.textures),
            "videos": rows(facts.videos),
            "unavailable_reason": None}
```

Confirm `os` is imported at the top of `fbxbytes.py`; add `import os` if it is not.

- [ ] **Step 7: Run the tests**

```bash
python -m pytest tests/test_fbxbytes.py -q
```

Expected: PASS including the three new tests. If the fixture's record layout differs from both shapes coded above, DO NOT force the test — read the actual bytes (a short `python -c` dump of the record names near the Texture object), fix the parser to the measured truth, and record the measurement in a comment on `texture_facts`.

- [ ] **Step 8: Commit**

```bash
git add maya_plugin/handlers/fbxbytes.py tests/test_fbxbytes.py
git commit -m "feat(#714): fbxbytes reads Texture/Video records"
```

---

### Task 3: `texture_violations` — the comparator

**Files:**
- Modify: `maya_plugin/handlers/export.py` (add beside `shape_violations`/`anim_violations`)
- Modify: `tests/test_export_fbx.py`

**Interfaces:**
- Consumes: `texclaim.material_claims`'s claim dicts (Task 1), `fbxbytes.texture_facts`'s block (Task 2).
- Produces: `export.texture_violations(tfacts, claims, require_baked) -> (violations: List[str], warnings: List[str])` — pure, no Maya.

- [ ] **Step 1: Write the failing matrix tests**

Append to `tests/test_export_fbx.py`:

```python
def _tfacts(basenames=(), names=()):
    return {"texture_records": len(basenames), "video_records": len(basenames),
            "textures": [{"name": n, "basename": b}
                         for n, b in zip(names or basenames, basenames)],
            "videos": [{"name": n, "basename": b}
                       for n, b in zip(names or basenames, basenames)],
            "unavailable_reason": None}


def _file_claim(basename="grain.png", on_disk=True, semantics_lost=(),
                material="skin_mat", attr="baseColor"):
    return {"mesh": "|bodyShape", "meshes": ["|bodyShape"],
            "material": material, "sg": "bodySG", "attr": attr,
            "slot": "color", "classification": "file",
            "terminals": [{"node": "tex", "type": "file",
                           "file_path": "C:/t/" + basename,
                           "basename": basename, "on_disk": on_disk,
                           "colorspace": "sRGB"}],
            "via": [], "semantics_lost": list(semantics_lost)}


def _procedural_claim(terminal="mcpTex_noise", ttype="noise"):
    return {"mesh": "|bodyShape", "meshes": ["|bodyShape"],
            "material": "skin_mat", "sg": "bodySG", "attr": "normalCamera",
            "slot": "normal", "classification": "procedural",
            "terminals": [{"node": terminal, "type": ttype,
                           "file_path": None, "basename": None,
                           "on_disk": None, "colorspace": None}],
            "via": ["bump2d"], "semantics_lost": []}


class TestTextureViolations:
    def test_a_surviving_file_claim_is_clean(self):
        bad, warn = export.texture_violations(
            _tfacts(["grain.png"]), [_file_claim()], False)
        assert bad == [] and warn == []

    def test_a_missing_on_disk_file_claim_refuses_in_both_modes(self):
        # Never-observed loss class: file-backed maps always survived in
        # every measurement, so its absence is an exporter regression and
        # refusing it breaks nobody.
        for strict in (False, True):
            bad, _warn = export.texture_violations(
                _tfacts([]), [_file_claim()], strict)
            assert len(bad) == 1
            assert "grain.png" in bad[0] and "skin_mat" in bad[0]

    def test_basename_matching_is_case_insensitive(self):
        bad, _warn = export.texture_violations(
            _tfacts(["GRAIN.PNG"]), [_file_claim("grain.png")], False)
        assert bad == []

    def test_a_claim_whose_image_is_not_on_disk_only_warns(self):
        # The exporter's behaviour for a missing image is UNMEASURED
        # (#714 probe P5) - warn until it is.
        bad, warn = export.texture_violations(
            _tfacts([]), [_file_claim(on_disk=False)], True)
        assert bad == []
        assert any("not on disk" in w for w in warn)

    def test_a_procedural_claim_warns_by_default(self):
        bad, warn = export.texture_violations(
            _tfacts([]), [_procedural_claim()], False)
        assert bad == []
        assert any("mcpTex_noise" in w and "silently drops" in w
                   for w in warn)

    def test_a_procedural_claim_violates_under_require_baked(self):
        bad, _warn = export.texture_violations(
            _tfacts([]), [_procedural_claim()], True)
        assert len(bad) == 1
        assert "normalCamera" in bad[0] or "normal" in bad[0]

    def test_semantics_lost_warns_and_never_refuses(self):
        claim = _file_claim(semantics_lost=["channel swizzle outColorR"])
        for strict in (False, True):
            bad, warn = export.texture_violations(
                _tfacts(["grain.png"]), [claim], strict)
            assert bad == []
            assert any("outColorR" in w for w in warn)

    def test_an_unclaimed_record_warns(self):
        bad, warn = export.texture_violations(
            _tfacts(["mystery.png"]), [], False)
        assert bad == []
        assert any("mystery.png" in w for w in warn)

    def test_a_procedural_name_in_the_bytes_warns_that_the_model_is_stale(
            self):
        bad, warn = export.texture_violations(
            _tfacts(["x.png"], names=["mcpTex_noise"]),
            [_procedural_claim()], False)
        assert bad == []
        assert any("stale" in w for w in warn)

    def test_an_unreadable_texture_block_warns_and_refuses_nothing(self):
        tfacts = dict(_tfacts([]), unavailable_reason="record truncated")
        bad, warn = export.texture_violations(
            tfacts, [_file_claim()], True)
        assert bad == []
        assert any("record truncated" in w for w in warn)
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_export_fbx.py::TestTextureViolations -q
```

Expected: FAIL — `AttributeError: module ... has no attribute 'texture_violations'`.

- [ ] **Step 3: Implement the comparator**

Add to `maya_plugin/handlers/export.py`, after `shape_violations`:

```python
# Tokens Maya expands itself (assign_pbr._PATTERN_TOKENS). Such a path names
# no single file, so its basename cannot be matched whole - the comparison
# falls back to the literal prefix and only ever warns (#714: the
# exporter's token handling is unmeasured).
_TEXTURE_PATTERN_TOKENS = ("<udim>", "<u>", "<v>", "<f>", "<frame0", "<tile>")


def texture_violations(tfacts, claims, require_baked):
    """How the file's texture records disagree with what the scene claims.

    Returns (violations, warnings). The asymmetry is deliberate and
    measured:

    * A FILE-backed claim missing from the bytes is a loss class never
      observed - every measurement shows file textures surviving as a
      Texture+Video pair carrying the basename - so its absence means the
      exporter regressed, and refusing it breaks no working pipeline.
    * A PROCEDURAL claim missing from the bytes is the KNOWN behaviour
      every golem-class delivery already relies on. Refusing it by default
      would retroactively break correct pipelines, so it warns unless the
      caller demands baked-only cargo.
    * semantics_lost never refuses: the image ships and the consumer
      rewires the channel. Refusing would refuse assign_pbr's own mask
      workflow.

    Comparison is by image BASENAME, case-insensitively (Windows), never by
    node name (this toolbox writes two different naming conventions and the
    exporter may rename), and never by record counts (one file node can
    drive several slots).
    """
    violations = []
    warnings = []

    if tfacts.get("unavailable_reason"):
        warnings.append(
            "the file's texture records could not be read (%s) - texture "
            "claims were NOT verified against the bytes"
            % tfacts["unavailable_reason"])
        return violations, warnings

    in_file = {(row.get("basename") or "").lower()
               for row in tfacts["textures"] + tfacts["videos"]
               if row.get("basename")}
    record_names = {(row.get("name") or "")
                    for row in tfacts["textures"] + tfacts["videos"]}
    claimed = set()

    for claim in claims:
        where = "material %r slot %r (%s)" % (
            claim["material"], claim["slot"] or "?", claim["attr"])
        if claim["classification"] == "file":
            for terminal in claim["terminals"]:
                basename = (terminal.get("basename") or "")
                claimed.add(basename.lower())
                pattern = any(tok in basename.lower()
                              for tok in _TEXTURE_PATTERN_TOKENS)
                found = basename.lower() in in_file
                if found:
                    continue
                if pattern:
                    warnings.append(
                        "%s claims the image sequence %r, whose expansion "
                        "in the file is unmeasured - no record matched"
                        % (where, basename))
                elif not terminal.get("on_disk"):
                    warnings.append(
                        "%s claims image %r, which is not on disk at export "
                        "time - the file carries no record for it"
                        % (where, basename))
                else:
                    violations.append(
                        "%s claims file texture %r but the file carries no "
                        "Texture/Video record for it"
                        % (where, basename))
            if claim["semantics_lost"]:
                warnings.append(
                    "%s survives as an image reference only - %s do not "
                    "travel in FBX and must be re-created by the consumer"
                    % (where, ", ".join(claim["semantics_lost"])))
        else:
            nodes = ", ".join(t["node"] for t in claim["terminals"])
            if require_baked:
                violations.append(
                    "%s is driven by a procedural network (%s), which "
                    "Maya's FBX exporter cannot write" % (where, nodes))
            else:
                warnings.append(
                    "%s is driven by a procedural network (%s) that Maya's "
                    "FBX exporter silently drops - the exported file does "
                    "not carry this map" % (where, nodes))
            for terminal in claim["terminals"]:
                if terminal["node"] in record_names:
                    warnings.append(
                        "%s: %r appears among the file's texture records - "
                        "the #714 drop model is stale and wants re-measuring"
                        % (where, terminal["node"]))

    for basename in sorted(b for b in in_file if b and b not in claimed):
        warnings.append(
            "the file carries texture %r that no walked material claim "
            "explains - the claim walk covers this toolbox's authored "
            "slots only" % basename)

    return violations, warnings
```

- [ ] **Step 4: Run the tests**

```bash
python -m pytest tests/test_export_fbx.py::TestTextureViolations -q
```

Expected: PASS, 10 tests.

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/export.py tests/test_export_fbx.py
git commit -m "feat(#714): texture_violations - the scene claim vs the bytes"
```

---

### Task 4: Wire it into `export_fbx`

**Files:**
- Modify: `maya_plugin/handlers/export.py` (`_validate` ~line 593-649; `export_fbx` body ~line 700-926)
- Modify: `tests/test_export_fbx.py`
- Modify: `docs/protocol.md` (the `export_fbx` row and its notes)

**Interfaces:**
- Consumes: `texclaim.material_claims`, `fbxbytes.texture_facts`, `export.texture_violations`.
- Produces: `export_fbx` result gains `"warnings": List[str]` and `"textures": Optional[dict]` where the dict is `{"texture_records", "video_records", "file_maps", "dropped_maps", "unclaimed_records", "unavailable_reason"}`; `params["require_baked_textures"]` is accepted and validated.

- [ ] **Step 1: Write the failing handler tests**

Append to `tests/test_export_fbx.py`:

```python
class TestRequireBakedTextures:
    def test_it_must_be_a_bool(self, tmp_path):
        with pytest.raises(HandlerError, match="require_baked_textures"):
            export._validate(_params(tmp_path, require_baked_textures="yes"))

    def test_a_procedural_claim_refuses_before_anything_is_written(
            self, monkeypatch, tmp_path):
        # Pre-write refusal: the cost-nothing principle. Nothing is written,
        # so there is no temp file to clean up and no path to protect.
        node = fbxbytes.FbxNode(name="golem_C_pelvis", kind="Mesh", uid=1,
                                geometry=7)
        cmds = FakeCmds()
        _install(monkeypatch, cmds, _facts([node]))
        monkeypatch.setattr(export.texclaim, "material_claims",
                            lambda _c, _s: [_procedural_claim()])
        params = _params(tmp_path, require_baked_textures=True)
        with pytest.raises(HandlerError, match="procedural"):
            export.export_fbx(params)
        assert not any(c[0] == "file" for c in cmds.calls)

    def test_a_procedural_claim_passes_by_default_and_is_named(
            self, monkeypatch, tmp_path):
        node = fbxbytes.FbxNode(name="golem_C_pelvis", kind="Mesh", uid=1,
                                geometry=7)
        cmds = FakeCmds()
        _install(monkeypatch, cmds, _facts([node]))
        monkeypatch.setattr(export.texclaim, "material_claims",
                            lambda _c, _s: [_procedural_claim()])
        out = export.export_fbx(_params(tmp_path))
        assert out["textures"]["dropped_maps"][0]["terminal"] == "mcpTex_noise"
        assert out["textures"]["dropped_maps"][0]["material"] == "skin_mat"
        assert any("silently drops" in w for w in out["warnings"])

    def test_a_textureless_export_reports_no_texture_block(
            self, monkeypatch, tmp_path):
        node = fbxbytes.FbxNode(name="golem_C_pelvis", kind="Mesh", uid=1,
                                geometry=7)
        _install(monkeypatch, FakeCmds(), _facts([node]))
        monkeypatch.setattr(export.texclaim, "material_claims",
                            lambda _c, _s: [])
        out = export.export_fbx(_params(tmp_path))
        assert out["textures"] is None
        assert out["warnings"] == []
```

`FakeCmds` in that file needs the two calls the walker seam does not cover — add `listSets` returning `[]` and `attributeQuery` returning `False` to it if absent, so the un-monkeypatched path is inert.

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_export_fbx.py::TestRequireBakedTextures -q
```

Expected: FAIL — `_validate` does not accept the parameter / `KeyError: 'textures'`.

- [ ] **Step 3: Validate the parameter**

In `export.py`'s `_validate`, next to the `include_animation` bool check, add the same shape:

```python
    require_baked = params.get("require_baked_textures", False)
    if not isinstance(require_baked, bool):
        raise HandlerError(
            "require_baked_textures must be true or false",
            hint="true refuses the export when any material slot is driven "
                 "by a procedural network Maya's FBX exporter cannot write")
```

and return it alongside the existing tuple members (update the call site's unpacking in `export_fbx` to match — it currently reads `path, nodes, include_skins, include_animation = _validate(params)`).

- [ ] **Step 4: Walk, refuse early, gate late**

In `export_fbx`, after `declared_shapes = _scene_shape_aliases(cmds, nodes)` (~line 714), add the claim and the pre-write refusal:

```python
    # #714: what the SCENE says its materials carry. Read-only queries; the
    # scene is never modified. Scoped to the exported shapes, like shape
    # aliases and clips above.
    claim_shapes = _exported_mesh_shapes(cmds, nodes)
    texture_claims = texclaim.material_claims(cmds, claim_shapes)
    if require_baked:
        procedural = [c for c in texture_claims
                      if c["classification"] == "procedural"]
        if procedural:
            raise HandlerError(
                "require_baked_textures=true but %d material slot(s) are "
                "driven by procedural networks: %s"
                % (len(procedural),
                   "; ".join("%s.%s (%s)"
                             % (c["material"], c["attr"],
                                ", ".join(t["node"] for t in c["terminals"]))
                             for c in procedural[:4])),
                hint="Maya's FBX exporter cannot write a procedural texture "
                     "network. Author the map as a file texture "
                     "(maya_assign_pbr, or the file_texture recipe), or "
                     "export with require_baked_textures=false and accept "
                     "that the look does not travel")
```

`_exported_mesh_shapes(cmds, nodes)` is a small helper next to `_scene_shape_aliases`: reuse whatever that function already does to turn `nodes` (or the whole scene) into mesh shapes. Read it and factor the shared part rather than writing a second expansion — if its expansion is inlined, extract it into `_exported_mesh_shapes` and have `_scene_shape_aliases` call it, so one rule decides "what this export covers".

After the byte facts are read and beside the other blocks (~line 847), compose the texture gate:

```python
    tex_block = fbxbytes.texture_facts(facts)
    tex_bad, tex_warnings = texture_violations(tex_block, texture_claims,
                                               require_baked)
    violations += tex_bad
    texture_hint = (
        " For texture violations: a file texture's image must exist on disk "
        "at export time and its mesh must be in the exported selection - "
        "procedural networks (noise, ramp, layeredTexture) have no FBX "
        "representation at all." if tex_bad else "")
```

Append `+ texture_hint` to BOTH HandlerError hints in the refusal branch (the unlink-failed one and the ordinary one), beside `+ skin_hint + shape_hint + anim_hint`.

- [ ] **Step 5: Compose the result block**

Before the `return` (~line 909), build the reported block, and add the two fields to the returned dict:

```python
    reported_textures = None
    if texture_claims or tex_block["texture_records"]:
        in_file = {(row.get("basename") or "").lower()
                   for row in tex_block["textures"] + tex_block["videos"]
                   if row.get("basename")}
        file_maps = []
        dropped_maps = []
        for claim in texture_claims:
            if claim["classification"] == "file":
                for terminal in claim["terminals"]:
                    basename = terminal.get("basename") or ""
                    file_maps.append({
                        "material": claim["material"],
                        "attr": claim["attr"], "slot": claim["slot"],
                        "file_node": terminal["node"], "basename": basename,
                        "on_disk": bool(terminal.get("on_disk")),
                        "found_in_file": basename.lower() in in_file,
                        "semantics_lost": claim["semantics_lost"]})
            else:
                for terminal in claim["terminals"]:
                    dropped_maps.append({
                        "material": claim["material"],
                        "attr": claim["attr"], "slot": claim["slot"],
                        "terminal": terminal["node"],
                        "terminal_type": terminal["type"],
                        "via": claim["via"], "meshes": claim["meshes"]})
        claimed = {(m["basename"] or "").lower() for m in file_maps}
        reported_textures = {
            "texture_records": tex_block["texture_records"],
            "video_records": tex_block["video_records"],
            "file_maps": file_maps,
            "dropped_maps": dropped_maps,
            "unclaimed_records": sorted(b for b in in_file
                                        if b and b not in claimed),
            "unavailable_reason": tex_block["unavailable_reason"],
        }
```

and in the returned dict, after `"animation": reported_anim,`:

```python
        "textures": reported_textures,
        "warnings": tex_warnings,
```

Add `texclaim` to export.py's `from . import ...` line.

- [ ] **Step 6: Run the export tests**

```bash
python -m pytest tests/test_export_fbx.py -q
```

Expected: PASS — every pre-existing test plus the new classes. Pre-existing tests that assert the exact result-key set (if any) must be updated to include the two new keys, not weakened.

- [ ] **Step 7: Update `docs/protocol.md`**

In the `export_fbx` row, add `require_baked_textures=false` to the params and `textures`, `warnings` to the result. Below the table, add a short paragraph: procedural texture networks have no FBX representation and are reported per material/slot in `textures.dropped_maps` with a warning; file-backed maps are byte-verified and a missing one REFUSES the export; `require_baked_textures=true` turns any procedural claim into a pre-write refusal; channel swizzle, invert and Raw colorspace are reported in `semantics_lost` and never gated (FBX cannot express them).

- [ ] **Step 8: Commit**

```bash
git add maya_plugin/handlers/export.py tests/test_export_fbx.py docs/protocol.md
git commit -m "feat(#714): export_fbx reports and gates its texture claims"
```

---

### Task 5: Real Maya — the export-then-read-bytes proofs

**Files:**
- Modify: `tests/test_handlers_mayapy.py` (new class beside `TestExportSkinsInMaya`)

**Interfaces:**
- Consumes: everything from Tasks 1-4.
- Produces: measured facts recorded in test docstrings (the repo's convention: on failure, fix the reader/violation to the MEASURED truth and record the number, never force the literal).

- [ ] **Step 1: Write the tests**

Add to `tests/test_handlers_mayapy.py`:

```python
class TestTextureHonestyInMaya:
    """#714 against a real exporter. The whole ticket rests on one measured
    claim - file textures survive as Texture+Video records, procedural
    networks vanish entirely - so it is measured here, not assumed."""

    def _png(self, path):
        """A 2x2 PNG with no dependencies (the tool_gaps_live precedent)."""
        import struct
        import zlib

        raw = b"".join(b"\x00" + bytes([255, 0, 0, 0, 255, 0])
                       for _ in range(2))

        def chunk(kind, payload):
            body = kind + payload
            return (struct.pack(">I", len(payload)) + body
                    + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

        png = (b"\x89PNG\r\n\x1a\n"
               + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(raw))
               + chunk(b"IEND", b""))
        with open(path, "wb") as fh:
            fh.write(png)
        return path

    def test_a_file_texture_survives_and_is_reported_found(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import export, material, texture_recipes

        image = self._png(str(tmp_path / "grain.png").replace("\\", "/"))
        mesh = cmds.ls(cmds.polyCube(name="tex_cube")[0], long=True)[0]
        material.assign_material({"mesh": mesh, "material": "tex_mat",
                                  "shader": "standardSurface"})
        texture_recipes.apply_texture_recipe({
            "mesh": mesh, "recipe": "file_texture",
            "params": {"file_path": image}})
        path = str(tmp_path / "textured.fbx").replace("\\", "/")
        out = export.export_fbx({"path": path, "metres_per_unit": 1.0,
                                 "nodes": [mesh]})
        block = out["textures"]
        assert block is not None
        assert block["texture_records"] >= 1
        maps = [m for m in block["file_maps"] if m["basename"] == "grain.png"]
        assert maps and maps[0]["found_in_file"] is True
        assert block["dropped_maps"] == []

    def test_a_procedural_network_is_named_dropped_and_absent_from_bytes(
            self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import export, material, texture_recipes

        mesh = cmds.ls(cmds.polyCube(name="proc_cube")[0], long=True)[0]
        material.assign_material({"mesh": mesh, "material": "proc_mat",
                                  "shader": "standardSurface"})
        recipe = texture_recipes.apply_texture_recipe({
            "mesh": mesh, "recipe": "noise_bump"})
        noise = [n for n in recipe["nodes"] if "noise" in n][0]
        path = str(tmp_path / "procedural.fbx").replace("\\", "/")
        out = export.export_fbx({"path": path, "metres_per_unit": 1.0,
                                 "nodes": [mesh]})
        dropped = out["textures"]["dropped_maps"]
        assert [d["terminal"] for d in dropped] == [noise]
        assert dropped[0]["slot"] == "normal"
        assert any("silently drops" in w for w in out["warnings"])
        with open(path, "rb") as fh:
            assert noise.encode() not in fh.read()

    def test_require_baked_textures_refuses_and_writes_nothing(self, tmp_path):
        import os

        import maya.cmds as cmds
        import pytest as _pytest

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import export, material, texture_recipes

        mesh = cmds.ls(cmds.polyCube(name="strict_cube")[0], long=True)[0]
        material.assign_material({"mesh": mesh, "material": "strict_mat",
                                  "shader": "standardSurface"})
        texture_recipes.apply_texture_recipe({"mesh": mesh,
                                              "recipe": "ramp_gradient"})
        path = str(tmp_path / "strict.fbx").replace("\\", "/")
        with _pytest.raises(HandlerError, match="procedural"):
            export.export_fbx({"path": path, "metres_per_unit": 1.0,
                               "nodes": [mesh],
                               "require_baked_textures": True})
        assert not os.path.exists(path)
        assert not os.path.exists(path + ".part.fbx")

    def test_a_whole_scene_export_claims_the_same_maps(self, tmp_path):
        """Whole-scene material carriage is its own measurement, not an
        assumption: the drifter probe measured a SELECTED export only."""
        import maya.cmds as cmds

        from maya_plugin.handlers import export, material, texture_recipes

        image = self._png(str(tmp_path / "whole.png").replace("\\", "/"))
        mesh = cmds.ls(cmds.polyCube(name="whole_cube")[0], long=True)[0]
        material.assign_material({"mesh": mesh, "material": "whole_mat",
                                  "shader": "standardSurface"})
        texture_recipes.apply_texture_recipe({
            "mesh": mesh, "recipe": "file_texture",
            "params": {"file_path": image}})
        path = str(tmp_path / "whole.fbx").replace("\\", "/")
        out = export.export_fbx({"path": path, "metres_per_unit": 1.0})
        found = [m for m in out["textures"]["file_maps"]
                 if m["basename"] == "whole.png"]
        assert found and found[0]["found_in_file"] is True
```

- [ ] **Step 2: Run just this class**

```bash
E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -k TextureHonesty -q --junitxml=$env:TEMP\t714_mayapy.xml
```

Expected: 4 passed. **If a test fails, real Maya is the contract:** read what the bytes actually carry (dump record names near the Texture object), fix the parser or the violation to the measured truth, record the measurement in the docstring, and re-run the headless suite. Never force a literal.

- [ ] **Step 3: Run the full mayapy suite**

```bash
E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q --junitxml=$env:TEMP\t714_mayapy_full.xml; echo "exit=$LASTEXITCODE"
```

Expected: exit=0, 168 pass + 1 skip (baseline 164+1, plus these 4). Read counts from the XML.

- [ ] **Step 4: Commit**

```bash
git add tests/test_handlers_mayapy.py
git commit -m "test(#714): real-Maya proofs - file textures survive, procedurals are named"
```

---

### Task 6: The MCP surface

**Files:**
- Modify: `src/maya_mcp/schemas.py` (new models near `ExportFbxResult` ~line 880)
- Modify: `src/maya_mcp/server.py` (`maya_export_fbx` ~line 907-958)
- Modify: `maya_plugin/handlers/texture_recipes.py` (~line 149-155)
- Modify: `tests/test_server_tools.py`, `tests/test_texture_recipes.py`

**Interfaces:**
- Consumes: the handler result shape from Task 4.
- Produces: `FileMapFact`, `DroppedMapFact`, `TextureFacts` models; `ExportFbxResult.textures`/`.warnings`; the `require_baked_textures` tool parameter.

- [ ] **Step 1: Write the failing wrapper tests**

Append to `tests/test_server_tools.py` (follow that file's existing fake-transport pattern for `maya_export_fbx` — read one nearby test first):

```python
def test_export_fbx_forwards_textures_and_warnings():
    """#714: ExportFbxResult is extra='ignore', so a field the model does
    not declare is dropped silently on the way to the caller - exactly the
    #757 defect class."""
    result = _export_result_with(
        textures={"texture_records": 1, "video_records": 1,
                  "file_maps": [{"material": "m", "attr": "baseColor",
                                 "slot": "color", "file_node": "t",
                                 "basename": "grain.png", "on_disk": True,
                                 "found_in_file": True,
                                 "semantics_lost": []}],
                  "dropped_maps": [{"material": "m", "attr": "normalCamera",
                                    "slot": "normal",
                                    "terminal": "mcpTex_noise",
                                    "terminal_type": "noise",
                                    "via": ["bump2d"], "meshes": ["|c"]}],
                  "unclaimed_records": [], "unavailable_reason": None},
        warnings=["material 'm' slot 'normal' ... silently drops"])
    assert result.textures.dropped_maps[0].terminal == "mcpTex_noise"
    assert result.textures.file_maps[0].found_in_file is True
    assert result.warnings


def test_export_fbx_passes_require_baked_textures_to_the_wire():
    sent = _capture_request(lambda tool: tool(
        path="C:/t/x.fbx", metres_per_unit=1.0, require_baked_textures=True))
    assert sent["params"]["require_baked_textures"] is True
```

`_export_result_with` and `_capture_request` are named after this file's existing helpers — use the real helper names it already provides; if it has none of this shape, build the two smallest ones next to the existing export test and say so in your report.

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_server_tools.py -k texture -q
```

Expected: FAIL — the model has no `textures` attribute.

- [ ] **Step 3: Add the models**

In `src/maya_mcp/schemas.py`, before `class ExportFbxResult`:

```python
class FileMapFact(BaseModel):
    """A file-backed map the scene claims, checked against the bytes."""

    model_config = ConfigDict(extra="ignore")

    material: str
    attr: str = Field(description="The shader attribute, e.g. 'baseColor'.")
    slot: Optional[str] = Field(default=None, description=(
        "The semantic slot name ('color', 'normal', ...) when the attribute "
        "maps back to one; null for an attribute outside the slot tables."))
    file_node: str
    basename: str
    on_disk: bool = Field(description=(
        "Whether the image existed on disk at export time."))
    found_in_file: bool = Field(description=(
        "Whether a Texture/Video record in the written FBX carries this "
        "basename. False REFUSES the export when the image is on disk - a "
        "file-backed map has never been measured to vanish, so its absence "
        "means the exporter regressed."))
    semantics_lost: List[str] = Field(default_factory=list, description=(
        "Wiring decisions FBX cannot carry: channel swizzle, reverse-invert, "
        "Raw colorspace. The image ships; the consumer re-creates these."))


class DroppedMapFact(BaseModel):
    """A map the scene carries that the FBX exporter cannot write at all."""

    model_config = ConfigDict(extra="ignore")

    material: str
    attr: str
    slot: Optional[str] = None
    terminal: str = Field(description="The procedural node, e.g. a noise.")
    terminal_type: str
    via: List[str] = Field(default_factory=list, description=(
        "Intermediate node types between the terminal and the shader."))
    meshes: List[str] = Field(default_factory=list)


class TextureFacts(BaseModel):
    """Texture honesty (#714): what the scene claims, what the file carries.

    The one block in this result that is NOT purely byte-derived - and it
    says so deliberately: absence cannot be read from the bytes, so the
    scene's claim is what makes a dropped map nameable.
    """

    model_config = ConfigDict(extra="ignore")

    texture_records: int
    video_records: int
    file_maps: List[FileMapFact] = Field(default_factory=list)
    dropped_maps: List[DroppedMapFact] = Field(default_factory=list)
    unclaimed_records: List[str] = Field(default_factory=list, description=(
        "Basenames in the file no walked claim explains - the walk covers "
        "this toolbox's authored slots only."))
    unavailable_reason: Optional[str] = None
```

and on `ExportFbxResult`, after `animation`:

```python
    textures: Optional[TextureFacts] = Field(
        default=None,
        description=(
            "Texture facts when the scene claims any map or the file carries "
            "any Texture record; null otherwise. Procedural networks are "
            "named in dropped_maps - Maya's FBX exporter drops them with no "
            "signal, which is what #714 exists to surface."))
    warnings: List[str] = Field(default_factory=list, description=(
        "Measured caveats about the written file - today, texture losses."))
```

- [ ] **Step 4: Add the tool parameter**

In `server.py`'s `maya_export_fbx`, after `include_animation`:

```python
        require_baked_textures: Annotated[bool, Field(description=(
            "Refuse the export when any material slot is driven by a "
            "procedural texture network (noise, ramp, layeredTexture). "
            "Maya's FBX exporter cannot write those at all and drops them "
            "silently, so a delivery that must carry its look sets this "
            "true and gets a refusal instead of a flat file. False (the "
            "default) exports anyway and names every dropped map in "
            "textures.dropped_maps."
        ))] = False,
```

and forward it in the request params dict: `"require_baked_textures": require_baked_textures`.

- [ ] **Step 5: Add the recipe warning**

In `texture_recipes.py`'s `apply_texture_recipe`, replace the `"warnings": []` in the return with a computed list:

```python
    warnings: List[str] = []
    if recipe != "file_texture":
        warnings.append(
            "this recipe builds a procedural network that Maya's FBX "
            "exporter silently drops - maya_export_fbx reports it in "
            "textures.dropped_maps; use file textures (maya_assign_pbr or "
            "the file_texture recipe) for anything that must survive export")
```

and return `"warnings": warnings`. Add to `tests/test_texture_recipes.py`:

```python
def test_procedural_recipes_warn_that_the_map_will_not_export(fake):
    out = texture_recipes.apply_texture_recipe(
        {"mesh": "body", "recipe": "noise_bump"})
    assert any("silently drops" in w for w in out["warnings"])


def test_the_file_texture_recipe_does_not_warn(fake, tmp_path):
    image = tmp_path / "t.png"
    image.write_bytes(b"x")
    out = texture_recipes.apply_texture_recipe(
        {"mesh": "body", "recipe": "file_texture",
         "params": {"file_path": str(image)}})
    assert out["warnings"] == []
```

(Match the fixture/helper names that file already uses; read its existing tests first.)

- [ ] **Step 6: Run the affected suites**

```bash
python -m pytest tests/test_server_tools.py tests/test_texture_recipes.py tests/test_export_fbx.py -q
```

Expected: PASS.

- [ ] **Step 7: Verify the recipe wrapper forwards warnings**

```bash
python -c "from maya_mcp import schemas; m=[n for n in dir(schemas) if 'Recipe' in n]; print(m); print(getattr(schemas, m[0]).model_fields.keys() if m else 'none')"
```

If the recipe result model lacks `warnings`, add it (`warnings: List[str] = Field(default_factory=list)`) with a wrapper test in `tests/test_server_tools.py` proving a handler warning reaches the caller — the #757 rule: a handler that stops being silent needs a wrapper that carries it.

- [ ] **Step 8: Commit**

```bash
git add src/maya_mcp/schemas.py src/maya_mcp/server.py maya_plugin/handlers/texture_recipes.py tests/test_server_tools.py tests/test_texture_recipes.py
git commit -m "feat(#714): MCP surface - textures block, warnings, require_baked_textures"
```

---

### Task 7: The live gate

**Files:**
- Modify: `evals/drifter_live.py` (its `export_and_check` / `_fbx_texture_facts` region, ~line 1448-1514)

**Interfaces:**
- Consumes: the `textures` block from Task 4/6.
- Produces: a cross-check gate — the eval's INDEPENDENT byte walk must agree with the product's reported block.

- [ ] **Step 1: Launch and verify your own Maya**

Follow the Global Constraints live-Maya rule exactly. Record the pid, confirm `maya_plugin.__file__` is under `D:\devel\maya-mcp` (so the BRANCH plugin serves, not the deployed one), and confirm `cmds.about(batch=True)` is False.

- [ ] **Step 2: Read the existing texture section**

Read `evals/drifter_live.py` around `_fbx_texture_facts` and `export_and_check`. It currently MEASURES the loss and deliberately does not score it. Keep its independent walker — it is the cross-check, and replacing it with the product's own reader would make the gate agree with itself.

- [ ] **Step 3: Add the cross-check**

In `export_and_check`, after the existing texture-facts measurement, add checks in that file's own check-recording style (match how its other checks report pass/fail with measured numbers):

1. The product's `result["textures"]["file_maps"]` contains the file_texture's basename with `found_in_file: True`, AND the eval's own walker found that same basename in the bytes. Fail if they disagree — a disagreement means the product's reader and the eval's reader see different files.
2. The product's `dropped_maps` names the noise_bump terminal, AND the eval's own walker finds zero occurrences of that node name in the bytes. Fail if the product claims a drop the bytes contradict, or misses one the bytes confirm.
3. `result["warnings"]` carries a line naming the dropped material/slot.

Report measured numbers in the check messages (record counts, basenames, dropped names) — the repo's rule: the gate reports numbers, not verdicts alone.

- [ ] **Step 4: Run the gate**

```bash
$env:MAYA_MCP_PORT='9877'; python evals\drifter_live.py
```

Expected: every check passes, including the three new ones. Report the measured verdict line verbatim. If a new check fails, diagnose whether the GATE or the PRODUCT is wrong before changing anything, and say which in your report.

- [ ] **Step 5: Kill your Maya and verify the port released**

```bash
taskkill /F /T /PID <your pid>
```

Then confirm `Test-NetConnection 127.0.0.1 -Port 9877 -InformationLevel Quiet` is False.

- [ ] **Step 6: Commit**

```bash
git add evals/drifter_live.py
git commit -m "test(#714): live gate cross-checks the textures block against an independent byte walk"
```

---

### Task 8: The five probes and the GO/NO-GO

**Files:**
- Create: `evals/bake_probe_714.py`

**Interfaces:**
- Consumes: nothing (standalone mayapy script).
- Produces: a printed verdict table; the GO/NO-GO decision for phase 2.

- [ ] **Step 1: Write the probe script**

Create `evals/bake_probe_714.py` — a standalone script run under `mayapy` (initialize `maya.standalone`), NOT part of any suite. It answers, printing one verdict line per probe plus a final table:

- **P1 — convertSolidTx headless:** build a poly plane, apply a `noise` texture to a standardSurface `baseColor`, call `cmds.convertSolidTx(...)` writing to a temp path. Report: did it run, did a file appear, its size. On exception, print the full error — that IS the answer.
- **P2 — UV fidelity (the GO/NO-GO):** bake the same noise on (a) a plane with clean 0..1 UVs, (b) a `polyCube` with default primitive UVs, (c) a mesh whose UVs were deleted (`polyMapDel`). For each: did it bake, and is the image non-uniform (read the PNG with `struct`/`zlib`, or if the format resists, report the file size and say the pixel check was not possible). Print the exact failure mode for (c) — it becomes the phase-2 refusal's measured message.
- **P3 — PNG format + bump-as-height:** report the written PNG's IHDR (bit depth, colour type). Then bake the pre-bump scalar (`noise.outColorR`) and report whether it produced a usable non-uniform image.
- **P4 — height-path survival:** wire `file -> bump2d(bumpInterp=0) -> normalCamera`, export via `export.export_fbx`, and report whether the image basename appears in the bytes (reuse `fbxbytes.texture_facts`).
- **P5 — missing image:** wire a `file` node whose `fileTextureName` points at a nonexistent path, export, and report what the bytes carry (Texture record present? filename?).

Each probe must be independently runnable and must not abort the script on failure — catch, print, continue. The script's last line prints a table: probe → measured result → verdict.

- [ ] **Step 2: Run it**

```bash
E:\Autodesk\Maya2027\bin\mayapy.exe evals\bake_probe_714.py
```

Record the full output in your report. If mayapy cannot run a probe at all (e.g. P1 fails immediately), that is a legitimate measured answer — do not retry more than twice or work around it.

- [ ] **Step 3: State the GO/NO-GO**

Per the spec: **phase 2 proceeds iff P2 yields usable bakes on box-projection UVs.** Write the verdict explicitly in your report and note which phase-2 design arm P2 selects (shared materials bake once if sampling is mesh-independent; refuse shared materials if it is mesh-dependent).

- [ ] **Step 4: Commit**

```bash
git add evals/bake_probe_714.py
git commit -m "test(#714): the five bake probes - evidence for the phase 2 GO/NO-GO"
```

---

### Task 9: Whole-branch verification and closeout

- [ ] **Step 1: Full headless suite**

```bash
python -m pytest tests -q --junitxml=$env:TEMP\t714_headless_final.xml
```

Expected: baseline 1528+1skip plus every test this plan added; 0 failures. Read the XML.

- [ ] **Step 2: Full mayapy suite, twice**

```bash
E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q --junitxml=$env:TEMP\t714_mp1.xml; echo "exit=$LASTEXITCODE"
E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q --junitxml=$env:TEMP\t714_mp2.xml; echo "exit=$LASTEXITCODE"
```

Expected: exit=0 both runs (a non-zero exit here would be the #729 teardown class returning — investigate before proceeding).

- [ ] **Step 3: Docs coherence**

```bash
git diff main...HEAD -- docs/protocol.md
```

Check the export_fbx row, the texture paragraph, and the recipe docs all match the shipped behavior. Fix gaps; change no product code.

- [ ] **Step 4: Confirm nothing foreign is staged**

```bash
git status --short
```

`evals/golem_rerun_665/out_v4/` must still be untracked and unmodified.

- [ ] **Step 5: Commit any verification fixes**

```bash
git add docs tests evals
git commit -m "test(#714): whole-branch verification for phase 1"
```

- [ ] **Step 6: Review, merge, deploy, ticket**

Use superpowers:requesting-code-review on `git diff main...HEAD`; fix findings (superpowers:receiving-code-review); use superpowers:finishing-a-development-branch to merge to `main`; deploy with `python maya_plugin/install.py --yes` and report the stamp (running Mayas hold old modules until restart). Then one Redmine update on #714 with: measured suite counts, the live gate verdict, the probe table, the GO/NO-GO, and status — **Resolved** if phase 2 is NO-GO (phase 1 is the whole fix), **In Progress** if phase 2 is GO (say the phase-2 plan is next).

---

## Self-Review

**Spec coverage:** §1.1 `require_baked_textures` → Task 4/6. §1.2 result fields → Task 4 (handler) + Task 6 (schema). §1.3 recipe warning → Task 6. §1.4 texclaim (derived AUTHORED_ATTRS, pass-throughs, classification, depth cap, dedupe) → Task 1. §1.5 fbxbytes parsing + violation matrix (all seven rows) → Tasks 2-3. §1.6 tests (headless/mayapy/live) → Tasks 1-3, 5, 7. §2 probes + GO/NO-GO → Task 8. §5 non-goals: no bake code appears anywhere in this plan; no MEL preamble change; no Material-record parsing.

**Known gaps handed to the implementer, deliberately:** the exact committed FBX fixture path and its basename (Task 2 Step 1 measures them — inventing them would be a fabricated literal); `test_server_tools.py`'s helper names (Task 6 Step 1 says to use the file's real helpers); `_exported_mesh_shapes`'s body (Task 4 Step 4 says to factor it out of the existing expansion rather than write a second rule). Each is a "read this and match it" instruction with the reason stated, not a TBD.

**Type consistency:** claim dicts carry the same keys in Tasks 1, 3, 4 (`classification`, `terminals`, `via`, `semantics_lost`, `meshes`); `texture_facts`'s block keys match between Task 2's composer, Task 3's comparator, and Task 4's reporter; `texture_violations(tfacts, claims, require_baked)` has one signature everywhere.
