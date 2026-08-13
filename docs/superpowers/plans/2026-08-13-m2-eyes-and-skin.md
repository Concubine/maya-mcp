# M2 — Eyes & Skin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Claude the ability to light, material, and texture a model in Maya — and to see whether the result is right.

**Architecture:** Same two-process shape as M0/M1. Pure logic and Maya calls live in `maya_plugin/handlers/*.py` behind the dispatcher (one call, one undo step); thin `@mcp.tool` wrappers in `src/maya_mcp/server.py` marshal params and decode images. Perception tools are `readOnly` and take no undo chunk. Server-side image compositing (contact sheets, side-by-side) lives in `src/maya_mcp/images.py` and never touches Maya.

**Tech Stack:** Python 3.12, uv, MCP Python SDK v2, Pillow, Maya 2027 (`maya.cmds` + `maya.api.OpenMaya`), pytest (headless with fake `cmds`; `mayapy -m pytest` against real Maya).

**Spec:** `docs/superpowers/specs/2026-08-13-m2-eyes-and-skin-design.md`
**Ticket:** redmine #581

## Global Constraints

- **Scope is conceptual, not golem-shaped.** These are general game-art tools; the golem is one consumer, never the specification.
- **Viewport judgement only.** No UV layout, no texture baking, no file export, no engine conventions. Out of scope for every task here.
- **One material per mesh.** Object-level shading groups only; per-face assignment stays deferred (M1 proved it silently no-ops on boolean output).
- **Zero orphans.** Every authoring tool records the nodes it creates and sweeps exactly those on failure. After any failed call, scene node counts are unchanged.
- **Checkpoints are for what undo cannot reach.** Only `setup_lighting(replace_existing=True)` auto-checkpoints. `assign_material` and `apply_texture_recipe` must NOT — look-dev is a loop of many small tweaks, and checkpointing each would evict valuable checkpoints from the ring.
- **Semantic texture slots.** Recipes name `color` / `roughness` / `normal`; the tool maps to the real attribute per shader type. A slot the shader lacks is a hinted `HandlerError`, never a silent no-op.
- **No bundled HDRI.** `hdri` preset errors without `hdri_path`.
- **Turntable:** 8 frames default, 16 maximum.
- **Judged-run artifacts:** committed as downscaled PNGs under `evals/`; `.mb` scene files stay gitignored.
- **Two-Maya policy (from #577):** any call that has never run live goes to a disposable agent-launched Maya on `MAYA_MCP_PORT=9878` first. The user's Maya on 9877 is only for pixel proofs. Never call `maya_new_scene`/`maya_open_scene` on the user's Maya — see redmine #579.
- **Never `importlib.reload(maya_mcp_plugin)`** on a live server; it orphans the running server. To hot-patch a handler, reload the handler module *and* re-point the map: `srv = P._active_server; srv._dispatcher._handlers = P._build_handlers()`.

---

## File Structure

**Plugin side (runs inside Maya):**
- `maya_plugin/handlers/objinfo.py` — NEW. `get_object_info` and its per-section readers.
- `maya_plugin/handlers/capture.py` — MODIFY. Add scene-lighting control to `_capture_one` + `_PanelState`; add `capture_turntable`.
- `maya_plugin/handlers/lighting.py` — NEW. `setup_lighting`, preset rigs, exact light teardown.
- `maya_plugin/handlers/material.py` — NEW. `assign_material`, the semantic-slot map, shader param whitelists.
- `maya_plugin/handlers/texture_recipes.py` — NEW. The four named recipes and their created-node bookkeeping.
- `maya_plugin/maya_mcp_plugin.py` — MODIFY. Register the six new commands in `_build_handlers()`.

**Server side (the MCP process, no Maya):**
- `src/maya_mcp/images.py` — MODIFY. Add `contact_sheet()` and `side_by_side()`.
- `src/maya_mcp/refstore.py` — NEW. In-process reference-image store.
- `src/maya_mcp/schemas.py` — MODIFY. Result models for the new structured-output tools.
- `src/maya_mcp/server.py` — MODIFY. Seven new `@mcp.tool` wrappers.

**Tests:**
- `tests/test_objinfo.py`, `tests/test_lighting.py`, `tests/test_material.py`, `tests/test_texture_recipes.py` — NEW, headless with fake `cmds`.
- `tests/test_images.py`, `tests/test_refstore.py` — NEW, pure server-side.
- `tests/test_handlers_mayapy.py` — MODIFY. Real-Maya coverage per task.
- `tests/test_server_tools.py` — MODIFY. Wrapper coverage.
- `evals/m2_judged_run.py` — NEW. The recorded judged run.

Split by responsibility: lighting, material, and texture authoring each get their own module rather than one `look.py`, because each has a distinct failure mode (node deletion / SG collapse / orphan sweeping) and they are reviewed independently.

---

### Task 1: `get_object_info` — the readback everything else is tested against

Everything in M2 is verified by reading state back. This lands first so later tasks have something to assert against.

**Files:**
- Create: `maya_plugin/handlers/objinfo.py`
- Create: `tests/test_objinfo.py`
- Modify: `maya_plugin/maya_mcp_plugin.py` (register `get_object_info`)
- Modify: `src/maya_mcp/schemas.py` (add `ObjectInfoResult`)
- Modify: `src/maya_mcp/server.py` (add `maya_get_object_info`)
- Modify: `tests/test_handlers_mayapy.py` (real-Maya section coverage)

**Interfaces:**
- Consumes: `maya_plugin.handlers.naming.require_object`, `maya_plugin.handlers.meshcheck.mesh_stats`, `maya_plugin.dispatcher.HandlerError`.
- Produces: `objinfo.get_object_info(params: Dict) -> Dict` with keys `name`, and optionally `transform`, `mesh_stats`, `uvs`, `shading`, `history`. The `shading` section is `{"shading_groups": [str], "materials": [str], "per_face": bool}` — later tasks assert material assignment through exactly this shape.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_objinfo.py
"""get_object_info section readers against a fake cmds - no Maya required."""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import objinfo


class FakeCmds:
    def __init__(self):
        self.objects = {"|golem|torso"}
        self.shapes = {"|golem|torso": "|golem|torso|torsoShape"}
        self.sets = {"|golem|torso|torsoShape": ["clay_SG"]}
        self.set_members = {"clay_SG": ["|golem|torso|torsoShape"]}
        self.connections = {"clay_SG": ["clay_mat"]}

    def ls(self, name=None, long=False, **kw):
        return [o for o in self.objects if o == name or o.split("|")[-1] == name]

    def listRelatives(self, node, shapes=False, fullPath=False, noIntermediate=False):
        return [self.shapes[node]] if node in self.shapes else None

    def nodeType(self, node):
        return "mesh"

    def xform(self, name, query=False, worldSpace=False, **kw):
        if kw.get("translation"):
            return [1.0, 2.0, 3.0]
        if kw.get("rotation"):
            return [0.0, 90.0, 0.0]
        return [1.0, 1.0, 1.0]

    def listSets(self, object=None, type=None):
        return list(self.sets.get(object, []))

    def sets(self, sg, query=False):
        return list(self.set_members.get(sg, []))

    def listConnections(self, node, source=True, destination=False, type=None):
        return list(self.connections.get(node, []))

    def polyEvaluate(self, name, uvSetCount=False, **kw):
        return 1

    def polyUVSet(self, name, query=False, allUVSets=False):
        return ["map1"]

    def listHistory(self, node):
        return [node, "polySoftEdge1"]


def test_shading_section_reports_the_assigned_material(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(objinfo, "_cmds", lambda: fake)
    result = objinfo.get_object_info({"name": "|golem|torso", "include": ["shading"]})
    assert result["shading"]["shading_groups"] == ["clay_SG"]
    assert result["shading"]["materials"] == ["clay_mat"]
    assert result["shading"]["per_face"] is False


def test_default_include_is_transform_and_mesh_stats(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(objinfo, "_cmds", lambda: fake)
    monkeypatch.setattr(objinfo, "_mesh_stats", lambda shape: {"tris": 12})
    result = objinfo.get_object_info({"name": "|golem|torso"})
    assert set(result) == {"name", "transform", "mesh_stats"}
    assert result["transform"]["translate"] == [1.0, 2.0, 3.0]


def test_unknown_section_is_rejected_with_the_valid_list(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(objinfo, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        objinfo.get_object_info({"name": "|golem|torso", "include": ["vertices"]})
    assert "mesh_stats" in exc.value.hint


def test_per_face_membership_is_reported(monkeypatch):
    # M1 established that per-face shading is unreliable; get_object_info must
    # surface it rather than hide it, because a caller seeing one SG would
    # otherwise assume healthy object-level assignment.
    fake = FakeCmds()
    fake.set_members["clay_SG"] = ["|golem|torso|torsoShape.f[0:5]"]
    monkeypatch.setattr(objinfo, "_cmds", lambda: fake)
    result = objinfo.get_object_info({"name": "|golem|torso", "include": ["shading"]})
    assert result["shading"]["per_face"] is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /d/devel/maya-mcp && uv run pytest tests/test_objinfo.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'maya_plugin.handlers.objinfo'`

- [ ] **Step 3: Write the implementation**

```python
# maya_plugin/handlers/objinfo.py
"""get_object_info: structured readback of one object (design doc 5.1).

Sections are summaries, never raw component data - uvs and history report
counts and node types so a large mesh cannot blow the response budget.
The shading section is how every M2 authoring tool is verified.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..dispatcher import HandlerError
from . import naming

SECTIONS = ("transform", "mesh_stats", "uvs", "shading", "history")
DEFAULT_SECTIONS = ["transform", "mesh_stats"]


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _mesh_stats(shape: str) -> Dict[str, Any]:
    from . import meshcheck  # noqa: PLC0415 - keep import cheap headless

    return meshcheck.mesh_stats(shape)


def _shape_of(cmds, transform: str):
    shapes = (
        cmds.listRelatives(transform, shapes=True, fullPath=True, noIntermediate=True)
        or []
    )
    return shapes[0] if shapes else None


def _transform_section(cmds, name: str) -> Dict[str, Any]:
    return {
        "translate": cmds.xform(name, query=True, worldSpace=True, translation=True),
        "rotate": cmds.xform(name, query=True, worldSpace=True, rotation=True),
        "scale": cmds.xform(name, query=True, worldSpace=True, scale=True),
    }


def _shading_section(cmds, shape: str) -> Dict[str, Any]:
    sgs = cmds.listSets(object=shape, type=1) or []
    materials: List[str] = []
    per_face = False
    for sg in sgs:
        for member in cmds.sets(sg, query=True) or []:
            if ".f[" in member:
                per_face = True
        for mat in cmds.listConnections(sg, source=True, type=None) or []:
            if mat not in materials:
                materials.append(mat)
    return {"shading_groups": list(sgs), "materials": materials, "per_face": per_face}


def _uvs_section(cmds, shape: str) -> Dict[str, Any]:
    sets = cmds.polyUVSet(shape, query=True, allUVSets=True) or []
    return {"uv_sets": list(sets), "count": len(sets)}


def _history_section(cmds, shape: str) -> Dict[str, Any]:
    nodes = cmds.listHistory(shape) or []
    types = []
    for node in nodes:
        t = cmds.nodeType(node)
        if t not in types:
            types.append(t)
    return {"node_count": len(nodes), "node_types": types}


def get_object_info(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    name = naming.require_object(cmds, str(params.get("name") or ""))
    include = params.get("include") or DEFAULT_SECTIONS
    if not isinstance(include, list) or not include:
        raise HandlerError(
            "include must be a non-empty list of section names",
            hint="valid sections: %s" % ", ".join(SECTIONS),
        )
    unknown = [s for s in include if s not in SECTIONS]
    if unknown:
        raise HandlerError(
            "unknown section(s): %s" % ", ".join(str(u) for u in unknown),
            hint="valid sections: %s" % ", ".join(SECTIONS),
        )

    out: Dict[str, Any] = {"name": name}
    shape = _shape_of(cmds, name)
    needs_shape = {"mesh_stats", "uvs", "shading", "history"}
    if shape is None and needs_shape.intersection(include):
        raise HandlerError(
            "%s has no shape node" % name,
            hint="mesh_stats/uvs/shading/history need a shape; groups support "
            "only the transform section",
        )

    if "transform" in include:
        out["transform"] = _transform_section(cmds, name)
    if "mesh_stats" in include:
        out["mesh_stats"] = _mesh_stats(shape)
    if "uvs" in include:
        out["uvs"] = _uvs_section(cmds, shape)
    if "shading" in include:
        out["shading"] = _shading_section(cmds, shape)
    if "history" in include:
        out["history"] = _history_section(cmds, shape)
    return out


get_object_info.no_undo_chunk = True
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /d/devel/maya-mcp && uv run pytest tests/test_objinfo.py -q`
Expected: PASS, 4 passed

- [ ] **Step 5: Register the command in the plugin**

In `maya_plugin/maya_mcp_plugin.py`, add `objinfo` to the handlers import block and add this entry to the dict returned by `_build_handlers()`:

```python
        "get_object_info": objinfo.get_object_info,
```

- [ ] **Step 6: Add the result schema**

In `src/maya_mcp/schemas.py`:

```python
class ObjectInfoResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="Canonical long name of the object queried.")
    transform: Optional[dict] = Field(
        default=None, description="World-space translate/rotate/scale."
    )
    mesh_stats: Optional[dict] = Field(
        default=None,
        description="tris, verts, faces, boundary_edges, nonmanifold_edges, watertight.",
    )
    uvs: Optional[dict] = Field(
        default=None, description="UV set names and count - a summary, never raw UVs."
    )
    shading: Optional[dict] = Field(
        default=None,
        description=(
            "shading_groups, materials, and per_face - per_face=true means "
            "face-level assignment, which is unreliable on boolean output."
        ),
    )
    history: Optional[dict] = Field(
        default=None, description="Construction-history node count and distinct node types."
    )
```

- [ ] **Step 7: Add the MCP tool wrapper**

In `src/maya_mcp/server.py`, alongside the other perception tools:

```python
    @mcp.tool(
        title="Get object info",
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True
        ),
    )
    def maya_get_object_info(
        name: Annotated[str, Field(min_length=1, description=(
            "Canonical long name, e.g. |golem|torso."
        ))],
        include: Annotated[
            List[Literal["transform", "mesh_stats", "uvs", "shading", "history"]],
            Field(description=(
                "Sections to return. uvs and history are summaries (counts and "
                "node types), never raw component data."
            )),
        ] = ["transform", "mesh_stats"],
    ) -> ObjectInfoResult:
        """Read one object's transform, mesh stats, UV sets, shading, or history.

        The shading section is how you verify a material actually landed."""
        return ObjectInfoResult.model_validate(
            maya.request(
                "get_object_info",
                {"name": name, "include": list(include)},
                timeout_s=SCENE_TIMEOUT_S,
            )
        )
```

Add `ObjectInfoResult` to the `from .schemas import (...)` list at the top of the file.

- [ ] **Step 8: Add real-Maya coverage**

Append to `tests/test_handlers_mayapy.py`:

```python
class TestObjectInfoInMaya:
    def test_sections_against_a_real_mesh(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import objinfo

        cmds.file(rename=str(tmp_path / "objinfo.ma"))
        cmds.polyCube(name="infocube", w=2, h=2, d=2)
        cmds.xform("|infocube", translation=[1, 2, 3])

        info = objinfo.get_object_info(
            {"name": "|infocube",
             "include": ["transform", "mesh_stats", "uvs", "shading", "history"]}
        )
        assert info["name"] == "|infocube"
        assert info["transform"]["translate"] == pytest.approx([1.0, 2.0, 3.0])
        assert info["mesh_stats"]["watertight"] is True
        assert info["mesh_stats"]["tris"] == 12
        assert info["uvs"]["count"] >= 1
        # a fresh polyCube is in initialShadingGroup at object level
        assert info["shading"]["shading_groups"] == ["initialShadingGroup"]
        assert info["shading"]["per_face"] is False
        assert info["history"]["node_count"] >= 1

    def test_group_without_a_shape_rejects_mesh_sections(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import objinfo

        cmds.file(rename=str(tmp_path / "objinfo_group.ma"))
        cmds.polyCube(name="gchild")
        cmds.group("|gchild", name="ginfo")
        with pytest.raises(HandlerError, match="no shape node"):
            objinfo.get_object_info({"name": "|ginfo", "include": ["mesh_stats"]})
```

- [ ] **Step 9: Run both suites**

Run: `cd /d/devel/maya-mcp && uv run pytest -q`
Expected: PASS, previous count + 4

Run: `cd /d/devel/maya-mcp && E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q`
Expected: PASS, previous count + 2

- [ ] **Step 10: Commit**

```bash
git add maya_plugin/handlers/objinfo.py maya_plugin/maya_mcp_plugin.py src/maya_mcp/schemas.py src/maya_mcp/server.py tests/test_objinfo.py tests/test_handlers_mayapy.py
git commit -m "feat(m2): get_object_info - structured readback incl. shading (redmine #581)"
```

---

### Task 2: Lighting-aware capture — the blocking requirement

Spec §2. Today `capture_viewport` renders in default viewport lighting, so a lit model is judged unlit. Without this every other M2 tool is decorative.

**Files:**
- Modify: `maya_plugin/handlers/capture.py` (`_PanelState`, `_capture_one`, `capture_viewport`)
- Modify: `src/maya_mcp/server.py` (`maya_capture_viewport` gains `lighting`)
- Modify: `tests/test_capture.py`
- Modify: `tests/test_handlers_mayapy.py`

**Interfaces:**
- Consumes: existing `capture._PanelState`, `capture._capture_one`.
- Produces: `capture_viewport` accepts `lighting: str` ∈ `{"default", "scene", "flat"}` (default `"default"`) and `shadows: bool` (default `False`). `_capture_one` gains matching positional params. Task 3's turntable calls `_capture_one` with the same signature.

**Why `_PanelState` must change too:** it currently snapshots `lights`/`cameras`/`locators`/`manipulators`/`textures` — those are *icon visibility* flags. Scene lighting is `displayLights` (`"default"|"all"|"flat"|"none"`) and `shadows`, neither of which is saved or restored. Setting them without extending the snapshot would leak capture state into the user's viewport.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_capture.py
def test_lighting_scene_sets_displayLights_all_and_restores_it(monkeypatch):
    # The blocking M2 requirement: a lit model must be capturable lit.
    # displayLights/shadows must also be RESTORED - they were not part of
    # _PanelState before, so setting them would have leaked into the user's
    # viewport permanently.
    fake = FakeCaptureCmds()
    fake.editor_state["displayLights"] = "default"
    fake.editor_state["shadows"] = False
    monkeypatch.setattr(capture, "_cmds", lambda: fake)

    capture.capture_viewport({
        "angles": ["front"], "lighting": "scene", "shadows": True,
    })

    applied = [c for c in fake.calls if c[0] == "modelEditor" and c[2].get("edit")]
    assert any(c[2].get("displayLights") == "all" for c in applied), applied
    assert any(c[2].get("shadows") is True for c in applied), applied
    # restored to what it was before the capture
    assert fake.editor_state["displayLights"] == "default"
    assert fake.editor_state["shadows"] is False


def test_lighting_rejects_an_unknown_mode(monkeypatch):
    fake = FakeCaptureCmds()
    monkeypatch.setattr(capture, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        capture.capture_viewport({"angles": ["front"], "lighting": "cinematic"})
    assert "scene" in exc.value.hint
```

If `FakeCaptureCmds` in `tests/test_capture.py` does not already track `modelEditor` edit/query state in an `editor_state` dict, extend it so that `modelEditor(panel, edit=True, **kw)` writes each kw into `self.editor_state` and `modelEditor(panel, query=True, <flag>=True)` reads it back. Record every call in `self.calls` as `("modelEditor", panel, kwargs)`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /d/devel/maya-mcp && uv run pytest tests/test_capture.py -q -k lighting`
Expected: FAIL — no `displayLights` in the applied editor kwargs

- [ ] **Step 3: Extend `_PanelState` to snapshot and restore the lighting flags**

In `maya_plugin/handlers/capture.py`, inside `_PanelState.__init__`, after the existing `self.textures = me(textures=True)` line:

```python
        # Scene-lighting state. These are NOT the icon-visibility flags above:
        # displayLights selects which lights actually light the shaded view,
        # and shadows toggles viewport shadow casting. Neither was snapshotted
        # before M2 because nothing set them - capture rendered in Maya's
        # default headlight regardless of the scene's own rig, which is
        # exactly the gap this task closes (spec 2).
        self.display_lights = me(displayLights=True)
        self.shadows = bool(me(shadows=True))
```

And in `_PanelState.restore`, add both flags to the existing `cmds.modelEditor(panel, edit=True, ...)` call:

```python
                displayLights=self.display_lights,
                shadows=self.shadows,
```

- [ ] **Step 4: Add the validated params and apply them**

At module level in `capture.py`, next to `VALID_SHADING`:

```python
# displayLights modes we expose. "scene" is the one that makes a lit model
# judgeable; "default" is Maya's headlight (what every capture did before M2).
VALID_LIGHTING = ("default", "scene", "flat")
_LIGHTING_TO_DISPLAY = {"default": "default", "scene": "all", "flat": "flat"}
```

In `capture_viewport`, after the `buffer` validation block:

```python
    lighting = params.get("lighting", "default")
    if lighting not in VALID_LIGHTING:
        raise HandlerError(
            "unknown lighting mode %r" % lighting,
            hint="valid lighting modes: %s ('scene' lights the model with the "
            "scene's own lights; 'default' is Maya's headlight)"
            % ", ".join(VALID_LIGHTING),
        )
    shadows = bool(params.get("shadows", False))
```

Pass both into the `_capture_one(...)` call, and add them to `_capture_one`'s signature after `resolution`. Inside `_capture_one`, add to `editor_kwargs`:

```python
            "displayLights": _LIGHTING_TO_DISPLAY[lighting],
            "shadows": shadows,
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd /d/devel/maya-mcp && uv run pytest tests/test_capture.py -q`
Expected: PASS

- [ ] **Step 6: Add the real-Maya gate that proves lighting reaches pixels**

This is the test that fails if lighting silently stops reaching captures. Append to `tests/test_handlers_mayapy.py`:

```python
class TestCaptureLightingInMaya:
    def test_scene_lighting_changes_the_pixels(self, tmp_path):
        # Spec 2: a capture must be able to use the scene's own lights.
        # Asserting the modelEditor flag alone would pass even if VP2 ignored
        # it - so compare actual pixels between the two modes.
        import base64
        import maya.cmds as cmds

        from maya_plugin.handlers import capture

        if not cmds.about(query=True, batch=True) is False:
            pytest.skip("viewport capture needs a GUI Maya")

        cmds.file(rename=str(tmp_path / "lighting.ma"))
        cmds.polyCube(name="litcube", w=4, h=4, d=4)
        light = cmds.directionalLight(name="keyish", intensity=3.0)
        cmds.xform(cmds.listRelatives(light, parent=True)[0], rotation=[-35, 25, 0])

        shots = {}
        for mode in ("default", "scene"):
            out = capture.capture_viewport({
                "angles": ["three_quarter"], "lighting": mode,
                "wireframe_overlay": False, "resolution": [256, 256],
                "isolate": ["|litcube"],
            })
            shots[mode] = base64.b64decode(out["images"][0]["png_b64"])

        assert shots["default"] != shots["scene"], (
            "scene lighting produced pixel-identical output to the default "
            "headlight - displayLights is not reaching VP2"
        )
```

- [ ] **Step 7: Run it live**

Start a disposable Maya first (never the user's):

```bash
MAYA_MCP_PORT=9878 "E:/Autodesk/Maya2027/bin/maya.exe" &
```

Run: `cd /d/devel/maya-mcp && E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py::TestCaptureLightingInMaya -q`
Expected: PASS, or SKIP in a batch-mode `mayapy` (the pixel proof then belongs to the judged run in Task 8).

- [ ] **Step 8: Add the `lighting` and `shadows` params to the MCP tool**

In `src/maya_mcp/server.py`, in `maya_capture_viewport`'s signature after `buffer`:

```python
        lighting: Annotated[
            Literal["default", "scene", "flat"],
            Field(description=(
                "'scene' renders with the scene's own lights - required to judge "
                "a lit model; 'default' is Maya's headlight; 'flat' is unlit."
            )),
        ] = "default",
        shadows: Annotated[
            bool, Field(description="Viewport shadow casting; only meaningful with lighting='scene'.")
        ] = False,
```

and add `"lighting": lighting, "shadows": shadows,` to the request params dict.

- [ ] **Step 9: Run the full suites**

Run: `cd /d/devel/maya-mcp && uv run pytest -q`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add maya_plugin/handlers/capture.py src/maya_mcp/server.py tests/test_capture.py tests/test_handlers_mayapy.py
git commit -m "feat(m2): capture with scene lighting - a lit model is now judgeable (redmine #581)"
```

---

### Task 3: `capture_turntable` — eight views for one image

**Files:**
- Modify: `maya_plugin/handlers/capture.py` (add `capture_turntable`)
- Modify: `src/maya_mcp/images.py` (add `contact_sheet`)
- Create: `tests/test_images.py`
- Modify: `maya_plugin/maya_mcp_plugin.py`, `src/maya_mcp/server.py`, `tests/test_capture.py`

**Interfaces:**
- Consumes: `capture._capture_one` (with Task 2's signature), `capture.camera_placement`.
- Produces: `capture.capture_turntable(params) -> {"images": [{"index": int, "azimuth": float, "png_b64": str}], "n_frames": int}`. Server-side, `images.contact_sheet(pngs: List[bytes], cols: int | None = None) -> bytes` composites them into one PNG.

- [ ] **Step 1: Write the failing test for the compositor**

```python
# tests/test_images.py
"""Server-side image compositing - pure PIL, no Maya, no MCP."""

import io

import pytest
from PIL import Image as PILImage

from maya_mcp import images


def _png(color, size=(64, 64)):
    buf = io.BytesIO()
    PILImage.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def test_contact_sheet_grid_dimensions_and_cell_order():
    cells = [_png((i * 25, 0, 0)) for i in range(8)]
    sheet = images.contact_sheet(cells)
    im = PILImage.open(io.BytesIO(sheet))
    # 8 cells -> 4x2 grid of 64px cells
    assert im.size == (4 * 64, 2 * 64)
    # cell 0 top-left, cell 4 starts the second row - order must be row-major,
    # because the caller reads the sheet as "frame 0 first, going right"
    assert im.convert("RGB").getpixel((2, 2)) == (0, 0, 0)
    assert im.convert("RGB").getpixel((2, 64 + 2)) == (100, 0, 0)


def test_contact_sheet_handles_a_non_square_count():
    sheet = images.contact_sheet([_png((0, 0, 0)) for _ in range(5)])
    im = PILImage.open(io.BytesIO(sheet))
    # 5 cells -> 3 cols x 2 rows, last cell blank rather than a crash
    assert im.size == (3 * 64, 2 * 64)


def test_contact_sheet_rejects_an_empty_list():
    with pytest.raises(ValueError):
        images.contact_sheet([])


def test_side_by_side_puts_reference_left_and_current_right():
    left, right = _png((255, 0, 0)), _png((0, 0, 255))
    out = images.side_by_side(left, right)
    im = PILImage.open(io.BytesIO(out)).convert("RGB")
    assert im.size[0] >= 128
    assert im.getpixel((2, im.size[1] - 2)) == (255, 0, 0)
    assert im.getpixel((im.size[0] - 2, im.size[1] - 2)) == (0, 0, 255)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /d/devel/maya-mcp && uv run pytest tests/test_images.py -q`
Expected: FAIL — `AttributeError: module 'maya_mcp.images' has no attribute 'contact_sheet'`

- [ ] **Step 3: Implement the compositors**

Append to `src/maya_mcp/images.py`:

```python
import math


def _open(png: bytes) -> PILImage.Image:
    return PILImage.open(io.BytesIO(png)).convert("RGB")


def _to_png(img: PILImage.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def contact_sheet(pngs, cols: int | None = None) -> bytes:
    """Composite frames into one row-major grid image.

    Row-major matters: the caller reads the sheet as "frame 0 top-left, going
    right", and a column-major sheet would silently mislabel every view.
    """
    if not pngs:
        raise ValueError("contact_sheet needs at least one image")
    tiles = [_open(p) for p in pngs]
    cell_w = max(t.width for t in tiles)
    cell_h = max(t.height for t in tiles)
    if cols is None:
        cols = min(len(tiles), max(1, int(math.ceil(math.sqrt(len(tiles) * 2)))))
    rows = int(math.ceil(len(tiles) / cols))
    sheet = PILImage.new("RGB", (cols * cell_w, rows * cell_h), (18, 18, 20))
    for i, tile in enumerate(tiles):
        x = (i % cols) * cell_w
        y = (i // cols) * cell_h
        sheet.paste(tile, (x, y))
    return _to_png(sheet)


def side_by_side(left_png: bytes, right_png: bytes, gap: int = 8) -> bytes:
    """Reference on the left, current viewport on the right, same scale."""
    left, right = _open(left_png), _open(right_png)
    height = max(left.height, right.height)

    def fit(img):
        if img.height == height:
            return img
        w = max(1, round(img.width * height / img.height))
        return img.resize((w, height), PILImage.LANCZOS)

    left, right = fit(left), fit(right)
    canvas = PILImage.new(
        "RGB", (left.width + gap + right.width, height), (18, 18, 20)
    )
    canvas.paste(left, (0, 0))
    canvas.paste(right, (left.width + gap, 0))
    return _to_png(canvas)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd /d/devel/maya-mcp && uv run pytest tests/test_images.py -q`
Expected: PASS, 4 passed

- [ ] **Step 5: Write the failing turntable handler test**

```python
# append to tests/test_capture.py
def test_turntable_defaults_to_eight_frames_evenly_spaced(monkeypatch):
    fake = FakeCaptureCmds()
    monkeypatch.setattr(capture, "_cmds", lambda: fake)
    seen = []

    def fake_capture_one(angle, *args, **kwargs):
        seen.append(angle)
        return {"png_b64": "x", "camera_position": [0, 0, 0],
                "camera_rotation": [0, 0, 0], "camera": "|cam"}

    monkeypatch.setattr(capture, "_capture_one", fake_capture_one)
    result = capture.capture_turntable({"target": "|golem"})
    assert result["n_frames"] == 8
    assert [i["azimuth"] for i in result["images"]] == [0, 45, 90, 135, 180, 225, 270, 315]


def test_turntable_caps_at_sixteen_frames(monkeypatch):
    fake = FakeCaptureCmds()
    monkeypatch.setattr(capture, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        capture.capture_turntable({"target": "|golem", "n_frames": 32})
    assert "16" in str(exc.value)
```

- [ ] **Step 6: Run to verify it fails**

Run: `cd /d/devel/maya-mcp && uv run pytest tests/test_capture.py -q -k turntable`
Expected: FAIL — `AttributeError: module has no attribute 'capture_turntable'`

- [ ] **Step 7: Implement `capture_turntable`**

In `maya_plugin/handlers/capture.py`:

```python
TURNTABLE_DEFAULT_FRAMES = 8
TURNTABLE_MAX_FRAMES = 16


def capture_turntable(params: Dict[str, Any]) -> Dict[str, Any]:
    """N evenly-spaced azimuths around the subject, for one composite image.

    The frame cap is about grid legibility, not tokens: this returns ONE
    contact sheet regardless of n_frames, so capture_viewport's 4-image
    ceiling does not apply - but a 32-cell sheet is unreadable at any sane
    resolution.
    """
    n_frames = params.get("n_frames", TURNTABLE_DEFAULT_FRAMES)
    if (
        not isinstance(n_frames, int) or isinstance(n_frames, bool)
        or not (2 <= n_frames <= TURNTABLE_MAX_FRAMES)
    ):
        raise HandlerError(
            "n_frames must be an integer 2..%d" % TURNTABLE_MAX_FRAMES,
            hint="the cap is grid legibility - the result is one contact sheet",
        )
    target = params.get("target")
    isolate = [str(target)] if target else None
    shading = params.get("shading", "smoothShaded")
    if shading not in VALID_SHADING:
        raise HandlerError(
            "unknown shading mode %r" % shading,
            hint="valid shading modes: %s" % ", ".join(VALID_SHADING),
        )
    lighting = params.get("lighting", "default")
    if lighting not in VALID_LIGHTING:
        raise HandlerError(
            "unknown lighting mode %r" % lighting,
            hint="valid lighting modes: %s" % ", ".join(VALID_LIGHTING),
        )
    resolution = clamp_resolution(params.get("resolution") or 384)
    shadows = bool(params.get("shadows", False))

    images_out = []
    for i in range(n_frames):
        azimuth = 360.0 * i / n_frames
        shot = _capture_one(
            ("azimuth", azimuth), shading, False, "beauty", isolate, True,
            resolution, lighting, shadows,
        )
        images_out.append(
            {"index": i, "azimuth": azimuth, "png_b64": shot["png_b64"]}
        )
    return {"images": images_out, "n_frames": n_frames}


capture_turntable.no_undo_chunk = True
```

`_capture_one` must accept an `("azimuth", degrees)` tuple as its `angle`. In `_capture_one`, replace the `if angle == "current":` branch condition handling so that:

```python
        if angle == "current":
            capture_cam = state.camera
        else:
            bbox_min, bbox_max = _scene_bbox(cmds, isolate)
            if isinstance(angle, (tuple, list)) and angle[0] == "azimuth":
                position, rotation = camera_placement_azimuth(
                    float(angle[1]), bbox_min, bbox_max
                )
            else:
                position, rotation = camera_placement(angle, bbox_min, bbox_max)
```

and add next to `camera_placement`:

```python
def camera_placement_azimuth(azimuth_deg: float, bbox_min, bbox_max):
    """Same framing math as camera_placement, at an arbitrary azimuth.

    Elevation is fixed at the three_quarter value so a turntable reads as one
    orbit rather than a wobble.
    """
    return _placement(azimuth_deg, 27.938, bbox_min, bbox_max)
```

Refactor the body of the existing `camera_placement` into `_placement(azimuth, elevation, bbox_min, bbox_max)` and have `camera_placement` look its angle up in `_ANGLE_DIRECTIONS` and delegate. This keeps one copy of the framing math — the existing named-angle tests must still pass unchanged, which is the proof the refactor was behaviour-preserving.

- [ ] **Step 8: Run to verify pass**

Run: `cd /d/devel/maya-mcp && uv run pytest tests/test_capture.py -q`
Expected: PASS, including every pre-existing `camera_placement` test

- [ ] **Step 9: Register and wrap**

In `maya_plugin/maya_mcp_plugin.py` `_build_handlers()`:

```python
        "capture_turntable": capture.capture_turntable,
```

In `src/maya_mcp/server.py`:

```python
    @mcp.tool(
        title="Capture turntable",
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True
        ),
    )
    def maya_capture_turntable(
        target: Annotated[Optional[str], Field(description=(
            "Object to orbit and frame; omit to frame the whole scene."
        ))] = None,
        n_frames: Annotated[int, Field(ge=2, le=16, description=(
            "Views around the subject. Returns ONE contact sheet regardless."
        ))] = 8,
        resolution: Annotated[int, Field(ge=64, le=1024, description=(
            "Per-cell resolution, before the sheet is downscaled."
        ))] = 384,
        lighting: Annotated[
            Literal["default", "scene", "flat"],
            Field(description="'scene' uses the scene's own lights."),
        ] = "default",
    ) -> list:
        """Orbit the subject and return a single contact-sheet image.

        Eight views for the token cost of one image - the final judgement pass."""
        result = maya.request(
            "capture_turntable",
            {"target": target, "n_frames": n_frames,
             "resolution": resolution, "lighting": lighting},
            timeout_s=CAPTURE_TIMEOUT_S,
        )
        cells = [
            images.decode_and_downscale(shot["png_b64"], max_px=resolution)
            for shot in result.get("images", [])
        ]
        sheet = images.contact_sheet(cells)
        return [
            Image(data=images.decode_and_downscale(
                base64.b64encode(sheet).decode("ascii")), format="png"),
            "turntable: %d frames, azimuths %s" % (
                result.get("n_frames", 0),
                json.dumps([s["azimuth"] for s in result.get("images", [])]),
            ),
        ]
```

Add `import base64` to `server.py` if not already present.

- [ ] **Step 10: Run the suites and commit**

Run: `cd /d/devel/maya-mcp && uv run pytest -q`
Expected: PASS

```bash
git add maya_plugin/handlers/capture.py maya_plugin/maya_mcp_plugin.py src/maya_mcp/images.py src/maya_mcp/server.py tests/test_images.py tests/test_capture.py
git commit -m "feat(m2): capture_turntable + server-side contact sheet (redmine #581)"
```

---

### Task 4: Reference images — `load_reference_image` + `compare_to_reference`

Closes the blind-correction loop. These live **entirely server-side**: the store is in the MCP process, so references survive `new_scene`, never dirty the user's file, and cannot be destroyed by a scene op.

**Files:**
- Create: `src/maya_mcp/refstore.py`
- Create: `tests/test_refstore.py`
- Modify: `src/maya_mcp/server.py`, `tests/test_server_tools.py`

**Interfaces:**
- Consumes: `images.side_by_side` (Task 3), `images.decode_and_downscale`.
- Produces: `refstore.ReferenceStore` with `put(ref_id: str, source: str) -> dict` (`{"ref_id", "width", "height", "bytes"}`), `get(ref_id: str) -> bytes`, `list_ids() -> List[str]`. Raises `KeyError` for a missing id.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_refstore.py
"""In-process reference-image store. No Maya, no MCP."""

import base64
import io

import pytest
from PIL import Image as PILImage

from maya_mcp import refstore


def _png_bytes(color=(10, 200, 10), size=(40, 30)):
    buf = io.BytesIO()
    PILImage.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def test_put_from_a_file_path_then_get(tmp_path):
    path = tmp_path / "ref.png"
    path.write_bytes(_png_bytes())
    store = refstore.ReferenceStore()
    meta = store.put("hero", str(path))
    assert meta["ref_id"] == "hero"
    assert (meta["width"], meta["height"]) == (40, 30)
    assert store.get("hero") == path.read_bytes()


def test_put_from_base64():
    store = refstore.ReferenceStore()
    b64 = base64.b64encode(_png_bytes()).decode("ascii")
    meta = store.put("inline", b64)
    assert meta["width"] == 40
    assert store.get("inline")


def test_get_unknown_id_raises_with_the_known_ids():
    store = refstore.ReferenceStore()
    store.put("a", base64.b64encode(_png_bytes()).decode("ascii"))
    with pytest.raises(KeyError) as exc:
        store.get("missing")
    assert "a" in str(exc.value)


def test_put_rejects_a_non_image():
    store = refstore.ReferenceStore()
    with pytest.raises(ValueError):
        store.put("junk", base64.b64encode(b"not an image").decode("ascii"))


def test_put_overwrites_the_same_id():
    store = refstore.ReferenceStore()
    store.put("x", base64.b64encode(_png_bytes((1, 1, 1))).decode("ascii"))
    store.put("x", base64.b64encode(_png_bytes((2, 2, 2), (8, 8))).decode("ascii"))
    assert store.list_ids() == ["x"]
    im = PILImage.open(io.BytesIO(store.get("x")))
    assert im.size == (8, 8)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /d/devel/maya-mcp && uv run pytest tests/test_refstore.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'maya_mcp.refstore'`

- [ ] **Step 3: Implement the store**

```python
# src/maya_mcp/refstore.py
"""Reference images, held in the MCP server process.

Deliberately NOT stored in the Maya scene: references then survive new_scene,
never dirty the user's file, and cannot be destroyed by a scene operation.
The store is per-server-process and intentionally not persisted - a reference
is a working aid for the current session, not an asset.
"""

from __future__ import annotations

import base64
import binascii
import io
import os
from typing import Dict, List

from PIL import Image as PILImage


class ReferenceStore:
    def __init__(self) -> None:
        self._images: Dict[str, bytes] = {}

    def put(self, ref_id: str, source: str) -> Dict[str, object]:
        if not isinstance(ref_id, str) or not ref_id.strip():
            raise ValueError("ref_id must be a non-empty string")
        raw = self._read(source)
        try:
            img = PILImage.open(io.BytesIO(raw))
            img.load()
        except Exception as exc:
            raise ValueError("reference is not a decodable image: %s" % exc) from exc
        self._images[ref_id] = raw
        return {
            "ref_id": ref_id,
            "width": img.width,
            "height": img.height,
            "bytes": len(raw),
        }

    def get(self, ref_id: str) -> bytes:
        if ref_id not in self._images:
            raise KeyError(
                "no reference %r; loaded references: %s"
                % (ref_id, ", ".join(sorted(self._images)) or "none")
            )
        return self._images[ref_id]

    def list_ids(self) -> List[str]:
        return sorted(self._images)

    @staticmethod
    def _read(source: str) -> bytes:
        if os.path.isfile(source):
            with open(source, "rb") as fh:
                return fh.read()
        try:
            return base64.b64decode(source, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(
                "source is neither an existing file path nor valid base64: %s" % exc
            ) from exc
```

- [ ] **Step 4: Run to verify pass**

Run: `cd /d/devel/maya-mcp && uv run pytest tests/test_refstore.py -q`
Expected: PASS, 5 passed

- [ ] **Step 5: Add both MCP tools**

In `src/maya_mcp/server.py`, near the other perception tools. Create one module-level store instance alongside the `maya` connection object:

```python
_references = refstore.ReferenceStore()
```

```python
    @mcp.tool(
        title="Load reference image",
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=True
        ),
    )
    def maya_load_reference_image(
        source: Annotated[str, Field(min_length=1, description=(
            "Absolute path to an image file, or raw base64 image data."
        ))],
        ref_id: Annotated[str, Field(min_length=1, description=(
            "Short id you will pass to maya_compare_to_reference, e.g. 'hero_front'."
        ))],
    ) -> ReferenceResult:
        """Store a reference image in the server for later side-by-side comparison.

        Held in the MCP process, not the Maya scene - it survives new_scene and
        never dirties your file."""
        return ReferenceResult.model_validate(_references.put(ref_id, source))

    @mcp.tool(
        title="Compare to reference",
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True
        ),
    )
    def maya_compare_to_reference(
        ref_id: Annotated[str, Field(min_length=1, description=(
            "Id from maya_load_reference_image."
        ))],
        angle: Annotated[
            Literal["front", "side", "back", "top", "three_quarter", "current"],
            Field(description="Viewport angle to capture for the right-hand panel."),
        ] = "three_quarter",
        resolution: Annotated[int, Field(ge=64, le=1024)] = 640,
        lighting: Annotated[
            Literal["default", "scene", "flat"],
            Field(description="'scene' uses the scene's own lights."),
        ] = "default",
    ) -> list:
        """One side-by-side image: the reference on the left, your viewport on the right.

        Corrects toward a target instead of a vague ideal."""
        reference = _references.get(ref_id)
        result = maya.request(
            "capture_viewport",
            {"angles": [angle], "shading": "smoothShaded",
             "wireframe_overlay": False, "buffer": "beauty", "isolate": None,
             "frame_all": True, "resolution": resolution,
             "lighting": lighting, "shadows": False},
            timeout_s=CAPTURE_TIMEOUT_S,
        )
        shots = result.get("images", [])
        if not shots:
            raise ValueError("capture returned no image to compare against")
        current = images.decode_and_downscale(shots[0]["png_b64"], max_px=resolution)
        composite = images.side_by_side(reference, current)
        return [
            Image(data=composite, format="png"),
            "left: reference %r | right: viewport %s" % (ref_id, angle),
        ]
```

Add to `src/maya_mcp/schemas.py`:

```python
class ReferenceResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ref_id: str = Field(description="Id to pass to maya_compare_to_reference.")
    width: int
    height: int
    bytes: int = Field(description="Stored size of the reference image.")
```

Import `refstore` and `ReferenceResult` in `server.py`.

- [ ] **Step 6: Add wrapper coverage**

Append to `tests/test_server_tools.py`, following the existing `FakeConn` pattern in that file:

```python
def test_compare_to_reference_errors_clearly_for_an_unknown_ref_id():
    # The failure a user will actually hit: comparing before loading.
    store = refstore.ReferenceStore()
    with pytest.raises(KeyError) as exc:
        store.get("never_loaded")
    assert "none" in str(exc.value)
```

- [ ] **Step 7: Run the suites and commit**

Run: `cd /d/devel/maya-mcp && uv run pytest -q`
Expected: PASS

```bash
git add src/maya_mcp/refstore.py src/maya_mcp/schemas.py src/maya_mcp/server.py tests/test_refstore.py tests/test_server_tools.py
git commit -m "feat(m2): reference images + side-by-side compare (redmine #581)"
```

---

### Task 5: `setup_lighting` — the only destructive tool here

**Files:**
- Create: `maya_plugin/handlers/lighting.py`
- Create: `tests/test_lighting.py`
- Modify: `maya_plugin/maya_mcp_plugin.py`, `src/maya_mcp/schemas.py`, `src/maya_mcp/server.py`, `tests/test_handlers_mayapy.py`

**Interfaces:**
- Consumes: `session.auto_checkpoint`, `naming.unique_name`, `HandlerError`.
- Produces: `lighting.setup_lighting(params) -> {"preset": str, "lights": [str], "removed": [str], "checkpoint_id": str | None, "warnings": [str]}`.

**The dangerous part:** `replace_existing=True` deletes user-authored nodes. "The prior lights" must mean light *transforms and their shapes* and nothing else — never anything merely selected or parented nearby. The mechanical gate is a full node-count diff.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_lighting.py
"""setup_lighting against a fake cmds - no Maya required."""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import lighting


class FakeCmds:
    def __init__(self, existing_lights=()):
        self.lights = list(existing_lights)     # shape names
        self.deleted = []
        self.created = []
        self.attrs = {}
        self.objects = set()

    def ls(self, *args, long=False, type=None, **kw):
        if type == "light":
            return list(self.lights)
        return []

    def listRelatives(self, node, parent=False, fullPath=False, **kw):
        return [node.replace("Shape", "")] if parent else None

    def objExists(self, name):
        return name in self.objects

    def delete(self, *names, **kw):
        for n in names:
            self.deleted.append(n)
            self.objects.discard(n)

    def directionalLight(self, name=None, intensity=1.0, **kw):
        shape = (name or "dirLight") + "Shape"
        self.created.append(("directionalLight", name, intensity))
        self.objects.add("|" + (name or "dirLight"))
        return shape

    def xform(self, name, **kw):
        if kw.get("query"):
            return [0.0, 0.0, 0.0]
        self.attrs.setdefault(name, []).append(kw)

    def setAttr(self, attr, *value, **kw):
        self.attrs[attr] = value

    def rename(self, old, new):
        return new


def test_three_point_builds_three_lights(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(lighting, "_cmds", lambda: fake)
    monkeypatch.setattr(lighting, "_auto_checkpoint", lambda reason: None)
    result = lighting.setup_lighting({"preset": "three_point", "replace_existing": False})
    assert result["preset"] == "three_point"
    assert len(result["lights"]) == 3
    assert result["removed"] == []


def test_replace_existing_removes_only_light_transforms(monkeypatch):
    # The dangerous path: this deletes user-authored nodes. It must touch
    # lights and nothing else - not a selection, not a sibling in the group.
    fake = FakeCmds(existing_lights=["oldKeyShape", "oldFillShape"])
    fake.objects.update({"|oldKey", "|oldFill", "|golem", "|camera1"})
    monkeypatch.setattr(lighting, "_cmds", lambda: fake)
    monkeypatch.setattr(lighting, "_auto_checkpoint",
                        lambda reason: {"checkpoint_id": "007_auto_lighting"})
    result = lighting.setup_lighting({"preset": "single_sun", "replace_existing": True})
    assert sorted(result["removed"]) == ["oldFill", "oldKey"]
    assert "|golem" not in fake.deleted
    assert "|camera1" not in fake.deleted
    assert result["checkpoint_id"] == "007_auto_lighting"


def test_replace_existing_false_takes_no_checkpoint(monkeypatch):
    # Checkpoints are for what undo cannot reach. Additive lighting is
    # ordinary undoable work and must not burn one.
    fake = FakeCmds(existing_lights=["oldKeyShape"])
    monkeypatch.setattr(lighting, "_cmds", lambda: fake)
    calls = []
    monkeypatch.setattr(lighting, "_auto_checkpoint",
                        lambda reason: calls.append(reason))
    lighting.setup_lighting({"preset": "single_sun", "replace_existing": False})
    assert calls == []


def test_hdri_without_a_path_is_rejected(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(lighting, "_cmds", lambda: fake)
    monkeypatch.setattr(lighting, "_auto_checkpoint", lambda reason: None)
    with pytest.raises(HandlerError) as exc:
        lighting.setup_lighting({"preset": "hdri"})
    assert "hdri_path" in str(exc.value) or "hdri_path" in exc.value.hint


def test_unknown_preset_lists_the_valid_ones(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(lighting, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        lighting.setup_lighting({"preset": "cinematic"})
    assert "three_point" in exc.value.hint


def test_invalid_preset_burns_no_checkpoint(monkeypatch):
    # Same discipline M1 established for sculpt_ops/remesh: validate fully
    # before spending a checkpoint.
    fake = FakeCmds(existing_lights=["oldKeyShape"])
    monkeypatch.setattr(lighting, "_cmds", lambda: fake)
    calls = []
    monkeypatch.setattr(lighting, "_auto_checkpoint",
                        lambda reason: calls.append(reason))
    with pytest.raises(HandlerError):
        lighting.setup_lighting({"preset": "nope", "replace_existing": True})
    assert calls == []
    assert fake.deleted == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /d/devel/maya-mcp && uv run pytest tests/test_lighting.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'maya_plugin.handlers.lighting'`

- [ ] **Step 3: Implement**

```python
# maya_plugin/handlers/lighting.py
"""setup_lighting: preset rigs (design doc 5.4).

"A model can't be judged unlit; M2 blocks on this."

This is the only destructive tool in M2: replace_existing=True deletes
user-authored nodes, so it auto-checkpoints - AFTER validation, so a refused
call never burns one (the correction M1 made to sculpt_ops/remesh).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..dispatcher import HandlerError
from . import naming

PRESETS = ("three_point", "single_sun", "hdri")

# (suffix, intensity multiplier, rotate) - a conventional key/fill/rim rig.
_THREE_POINT = (
    ("key", 1.0, [-35.0, 30.0, 0.0]),
    ("fill", 0.35, [-15.0, -55.0, 0.0]),
    ("rim", 0.7, [-10.0, 165.0, 0.0]),
)
_SINGLE_SUN = (("sun", 1.0, [-45.0, 25.0, 0.0]),)


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _auto_checkpoint(reason: str):
    from . import session  # noqa: PLC0415 - avoid an import cycle

    return session.auto_checkpoint(reason)


def _existing_light_transforms(cmds) -> List[str]:
    """Transforms that own a light shape - and nothing else.

    Deliberately derived from ls(type="light"), not from a selection or a
    naming convention: this list is about to be deleted.
    """
    out: List[str] = []
    for shape in cmds.ls(type="light", long=True) or []:
        parents = cmds.listRelatives(shape, parent=True, fullPath=True) or []
        for parent in parents:
            if parent not in out:
                out.append(parent)
    return out


def _build(cmds, prefix: str, specs, intensity: float) -> List[str]:
    created: List[str] = []
    for suffix, factor, rotate in specs:
        name = naming.unique_name(cmds, "%s_%s" % (prefix, suffix))
        shape = cmds.directionalLight(name=name, intensity=intensity * factor)
        parents = cmds.listRelatives(shape, parent=True, fullPath=True) or []
        transform = parents[0] if parents else shape
        cmds.xform(transform, rotation=rotate, worldSpace=True)
        created.append(transform)
    return created


def setup_lighting(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    preset = params.get("preset")
    if preset not in PRESETS:
        raise HandlerError(
            "unknown lighting preset %r" % preset,
            hint="valid presets: %s" % ", ".join(PRESETS),
        )
    intensity = params.get("intensity", 1.0)
    if (
        not isinstance(intensity, (int, float)) or isinstance(intensity, bool)
        or not (0.0 < intensity <= 20.0)
    ):
        raise HandlerError(
            "intensity must be a number in (0, 20]",
            hint="got %r; 1.0 is the neutral default" % (intensity,),
        )
    hdri_path = params.get("hdri_path")
    if preset == "hdri" and not hdri_path:
        raise HandlerError(
            "the hdri preset requires hdri_path",
            hint="maya-mcp bundles no HDRI (they are large and separately "
            "licensed) - pass an absolute path to your own .hdr/.exr",
        )
    replace_existing = params.get("replace_existing", True) is not False

    # Everything above is validation; only now is it safe to spend a
    # checkpoint or delete anything.
    checkpoint_id: Optional[str] = None
    removed: List[str] = []
    if replace_existing:
        existing = _existing_light_transforms(cmds)
        if existing:
            info = _auto_checkpoint("lighting")
            checkpoint_id = (info or {}).get("checkpoint_id")
            for transform in existing:
                cmds.delete(transform)
                removed.append(transform.split("|")[-1])

    if preset == "three_point":
        lights = _build(cmds, "mcpLight", _THREE_POINT, float(intensity))
    elif preset == "single_sun":
        lights = _build(cmds, "mcpLight", _SINGLE_SUN, float(intensity))
    else:
        lights = _build_hdri(cmds, str(hdri_path), float(intensity))

    return {
        "preset": preset,
        "lights": lights,
        "removed": removed,
        "checkpoint_id": checkpoint_id,
        "warnings": [],
    }


def _build_hdri(cmds, hdri_path: str, intensity: float) -> List[str]:
    """Dome light driven by a file texture.

    aiSkyDomeLight is Arnold-only, so this uses Maya's own light + file node
    to stay renderer-agnostic (compatibility rule, design doc 6).
    """
    name = naming.unique_name(cmds, "mcpLight_dome")
    shape = cmds.directionalLight(name=name, intensity=intensity)
    parents = cmds.listRelatives(shape, parent=True, fullPath=True) or []
    transform = parents[0] if parents else shape
    tex = cmds.shadingNode("file", asTexture=True,
                           name=naming.unique_name(cmds, "mcpLight_domeTex"))
    cmds.setAttr(tex + ".fileTextureName", hdri_path, type="string")
    cmds.connectAttr(tex + ".outColor", shape + ".color", force=True)
    return [transform]


setup_lighting.no_undo_chunk = False
```

- [ ] **Step 4: Run to verify pass**

Run: `cd /d/devel/maya-mcp && uv run pytest tests/test_lighting.py -q`
Expected: PASS, 6 passed

- [ ] **Step 5: Add the real-Maya node-count gate**

Append to `tests/test_handlers_mayapy.py`:

```python
class TestLightingInMaya:
    def test_replace_existing_removes_exactly_the_prior_lights(self, tmp_path):
        # A full node-count diff, not a spot check: this tool deletes user
        # work, and "removed one thing too many" is the failure that matters.
        import maya.cmds as cmds

        from maya_plugin.handlers import lighting

        cmds.file(new=True, force=True)
        cmds.file(rename=str(tmp_path / "lighting.ma"))
        cmds.polyCube(name="keepme")
        cmds.spaceLocator(name="keepme_loc")
        old = cmds.directionalLight(name="old_key")
        before = set(cmds.ls(long=True))

        result = lighting.setup_lighting(
            {"preset": "three_point", "replace_existing": True}
        )

        assert cmds.objExists("|keepme")
        assert cmds.objExists("|keepme_loc")
        assert not cmds.objExists("|old_key")
        assert len(result["lights"]) == 3
        assert result["removed"] == ["old_key"]
        # every surviving pre-existing node is still there
        after = set(cmds.ls(long=True))
        vanished = {n for n in before - after if "old_key" not in n}
        assert vanished == set(), "setup_lighting deleted more than the lights: %s" % vanished

    def test_lights_actually_light_the_scene(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import lighting

        cmds.file(new=True, force=True)
        cmds.file(rename=str(tmp_path / "lighting_shape.ma"))
        result = lighting.setup_lighting({"preset": "single_sun", "intensity": 2.0})
        shapes = cmds.listRelatives(result["lights"][0], shapes=True, fullPath=True)
        assert cmds.nodeType(shapes[0]) == "directionalLight"
        assert cmds.getAttr(shapes[0] + ".intensity") == pytest.approx(2.0)
```

- [ ] **Step 6: Register, schema, wrapper**

`_build_handlers()`: `"setup_lighting": lighting.setup_lighting,`

`schemas.py`:

```python
class LightingResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    preset: str
    lights: List[str] = Field(description="Canonical long names of the lights created.")
    removed: List[str] = Field(
        default_factory=list, description="Short names of lights deleted by replace_existing."
    )
    checkpoint_id: Optional[str] = Field(
        default=None,
        description="Auto-checkpoint taken before deleting lights; None if nothing was deleted.",
    )
    warnings: List[str] = Field(default_factory=list)
```

`server.py`:

```python
    @mcp.tool(
        title="Setup lighting",
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=True, idempotentHint=False
        ),
    )
    def maya_setup_lighting(
        preset: Annotated[
            Literal["three_point", "single_sun", "hdri"],
            Field(description="Light rig to build."),
        ],
        intensity: Annotated[float, Field(gt=0, le=20, description=(
            "Overall rig intensity; 1.0 is neutral."
        ))] = 1.0,
        hdri_path: Annotated[Optional[str], Field(description=(
            "Absolute path to an .hdr/.exr. Required for preset='hdri' - no HDRI "
            "is bundled."
        ))] = None,
        replace_existing: Annotated[bool, Field(description=(
            "Delete existing lights first. Auto-checkpoints before doing so. "
            "Only light transforms are removed; other nodes are never touched."
        ))] = True,
    ) -> LightingResult:
        """Build a lighting rig so the model can actually be judged.

        Pair with maya_capture_viewport(lighting='scene') to see it."""
        return LightingResult.model_validate(
            maya.request(
                "setup_lighting",
                {"preset": preset, "intensity": intensity,
                 "hdri_path": hdri_path, "replace_existing": replace_existing},
                timeout_s=SCENE_TIMEOUT_S,
            )
        )
```

- [ ] **Step 7: Run everything and commit**

Run: `cd /d/devel/maya-mcp && uv run pytest -q` → PASS
Run: `cd /d/devel/maya-mcp && E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q` → PASS

```bash
git add maya_plugin/handlers/lighting.py maya_plugin/maya_mcp_plugin.py src/maya_mcp/schemas.py src/maya_mcp/server.py tests/test_lighting.py tests/test_handlers_mayapy.py
git commit -m "feat(m2): setup_lighting presets, deleting exactly the prior lights (redmine #581)"
```

---

### Task 6: `assign_material`

**Files:**
- Create: `maya_plugin/handlers/material.py`
- Create: `tests/test_material.py`
- Modify: `maya_plugin/maya_mcp_plugin.py`, `src/maya_mcp/schemas.py`, `src/maya_mcp/server.py`, `tests/test_handlers_mayapy.py`

**Interfaces:**
- Consumes: `naming.require_mesh`, `naming.unique_name`, `meshcheck.ensure_object_shading`, `meshcheck.first_sg`.
- Produces: `material.assign_material(params) -> {"mesh": str, "material": str, "shading_group": str, "shader": str, "warnings": [str]}`. Task 7 consumes `material.SHADER_SLOTS` and `material.resolve_slot(shader_type, slot)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_material.py
"""assign_material and the semantic-slot map - no Maya required."""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import material


def test_resolve_slot_maps_semantic_names_per_shader():
    assert material.resolve_slot("standardSurface", "color") == "baseColor"
    assert material.resolve_slot("lambert", "color") == "color"
    assert material.resolve_slot("standardSurface", "roughness") == "specularRoughness"
    assert material.resolve_slot("standardSurface", "normal") == "normalCamera"
    assert material.resolve_slot("lambert", "normal") == "normalCamera"


def test_resolve_slot_rejects_a_slot_the_shader_lacks():
    # A texture wired to nothing changes no pixels and looks like success.
    # This must be a loud error, never a silent no-op.
    with pytest.raises(HandlerError) as exc:
        material.resolve_slot("lambert", "roughness")
    assert "lambert" in str(exc.value)
    assert "color" in exc.value.hint


def test_unknown_material_param_is_rejected_with_the_whitelist(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(material, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        material.assign_material({
            "mesh": "|torso", "shader": "standardSurface",
            "params": {"subsurface_radius": 3},
        })
    assert "roughness" in exc.value.hint


def test_assign_creates_shader_and_object_level_sg(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(material, "_cmds", lambda: fake)
    result = material.assign_material({
        "mesh": "|torso", "shader": "standardSurface",
        "params": {"baseColor": [0.4, 0.3, 0.25], "roughness": 0.8},
    })
    assert result["shader"] == "standardSurface"
    assert result["shading_group"].endswith("SG")
    assert ("setAttr", "baseColor") in [
        (c[0], c[1].split(".")[-1]) for c in fake.calls if c[0] == "setAttr"
    ]


class FakeCmds:
    def __init__(self):
        self.objects = {"|torso"}
        self.shapes = {"|torso": ("|torso|torsoShape", "mesh")}
        self.calls = []

    def ls(self, name=None, long=False, **kw):
        return [o for o in self.objects if o == name or o.split("|")[-1] == name]

    def objExists(self, name):
        return name in self.objects

    def listRelatives(self, node, shapes=False, fullPath=False, noIntermediate=False):
        entry = self.shapes.get(node)
        return [entry[0]] if entry else None

    def nodeType(self, node):
        return "mesh"

    def shadingNode(self, node_type, asShader=False, name=None, **kw):
        self.calls.append(("shadingNode", node_type, name))
        self.objects.add(name)
        return name

    def sets(self, *args, **kw):
        if kw.get("renderable"):
            self.calls.append(("sets", kw.get("name")))
            self.objects.add(kw.get("name"))
            return kw.get("name")
        return []

    def connectAttr(self, src, dst, force=False):
        self.calls.append(("connectAttr", src, dst))

    def setAttr(self, attr, *value, **kw):
        self.calls.append(("setAttr", attr, value))

    def listConnections(self, node, type=None, **kw):
        return []

    def listSets(self, object=None, type=None):
        return []
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /d/devel/maya-mcp && uv run pytest tests/test_material.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# maya_plugin/handlers/material.py
"""assign_material: one material per mesh, object-level (design doc 5.4).

Object-level shading groups ONLY. M1 established that per-face assignment
silently no-ops and corrupts shading groups on boolean output, which is why
modeling._do_boolean collapses to a single object-level SG - honouring that
here keeps one rule in the codebase instead of two contradictory ones.
Multi-material looks come from splitting geometry, which game engines prefer
anyway.

Does NOT auto-checkpoint: assigning a material is fully covered by
one-call-one-undo-step, and look-dev is a loop of many small tweaks -
checkpointing each would evict genuinely valuable checkpoints from the ring.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..dispatcher import HandlerError
from . import meshcheck, naming

SHADERS = ("standardSurface", "lambert", "blinn")

# Whitelisted authoring params per shader, by their REAL attribute names.
PARAM_WHITELIST = {
    "standardSurface": {
        "baseColor", "roughness", "metalness", "emission", "emissionColor",
        "specular",
    },
    "lambert": {"color", "transparency", "incandescence"},
    "blinn": {"color", "transparency", "incandescence", "eccentricity",
              "specularColor"},
}

# Real attribute name for each whitelisted param, per shader.
_ATTR = {
    "standardSurface": {
        "baseColor": "baseColor", "roughness": "specularRoughness",
        "metalness": "metalness", "emission": "emission",
        "emissionColor": "emissionColor", "specular": "specular",
    },
    "lambert": {
        "color": "color", "transparency": "transparency",
        "incandescence": "incandescence",
    },
    "blinn": {
        "color": "color", "transparency": "transparency",
        "incandescence": "incandescence", "eccentricity": "eccentricity",
        "specularColor": "specularColor",
    },
}

# Semantic slots a texture recipe can target (Task 7 consumes this).
SHADER_SLOTS = {
    "standardSurface": {
        "color": "baseColor", "roughness": "specularRoughness",
        "normal": "normalCamera",
    },
    "lambert": {"color": "color", "normal": "normalCamera"},
    "blinn": {"color": "color", "roughness": "eccentricity",
              "normal": "normalCamera"},
}

_COLOR_ATTRS = {"baseColor", "color", "emissionColor", "specularColor",
                "incandescence", "transparency"}


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def resolve_slot(shader_type: str, slot: str) -> str:
    """Semantic slot -> real attribute for this shader type.

    A slot the shader genuinely lacks is an error, never a silent no-op: a
    texture connected to nothing changes no pixels and reads as success.
    """
    slots = SHADER_SLOTS.get(shader_type)
    if slots is None:
        raise HandlerError(
            "unknown shader type %r" % shader_type,
            hint="valid shaders: %s" % ", ".join(SHADERS),
        )
    if slot not in slots:
        raise HandlerError(
            "shader %s has no %r slot" % (shader_type, slot),
            hint="slots available on %s: %s"
            % (shader_type, ", ".join(sorted(slots))),
        )
    return slots[slot]


def assign_material(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    mesh_long, shape = naming.require_mesh(cmds, str(params.get("mesh") or ""))
    shader = params.get("shader", "standardSurface")
    if shader not in SHADERS:
        raise HandlerError(
            "unknown shader %r" % shader,
            hint="valid shaders: %s" % ", ".join(SHADERS),
        )
    values = dict(params.get("params") or {})
    unknown = set(values) - PARAM_WHITELIST[shader]
    if unknown:
        raise HandlerError(
            "unknown params for %s: %s" % (shader, ", ".join(sorted(unknown))),
            hint="valid params: %s" % ", ".join(sorted(PARAM_WHITELIST[shader])),
        )

    requested = params.get("name") or (mesh_long.split("|")[-1] + "_mat")
    mat_name = naming.unique_name(cmds, str(requested))
    mat = cmds.shadingNode(shader, asShader=True, name=mat_name)
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                   name=mat_name + "SG")
    cmds.connectAttr(mat + ".outColor", sg + ".surfaceShader", force=True)

    for key, value in values.items():
        attr = "%s.%s" % (mat, _ATTR[shader][key])
        if _ATTR[shader][key] in _COLOR_ATTRS:
            if (
                not isinstance(value, (list, tuple)) or len(value) != 3
                or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                           for v in value)
            ):
                raise HandlerError(
                    "%s must be [r, g, b]" % key,
                    hint="got %r; colour components are 0..1" % (value,),
                )
            cmds.setAttr(attr, float(value[0]), float(value[1]), float(value[2]),
                         type="double3")
        else:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise HandlerError(
                    "%s must be a number" % key, hint="got %r" % (value,)
                )
            cmds.setAttr(attr, float(value))

    shading = meshcheck.ensure_object_shading(cmds, shape, sg)
    warnings: List[str] = []
    if shading["sg"] != sg:
        warnings.append(
            "assignment collapsed onto existing shading group %s" % shading["sg"]
        )
    return {
        "mesh": mesh_long,
        "material": mat,
        "shading_group": shading["sg"],
        "shader": shader,
        "warnings": warnings,
    }
```

- [ ] **Step 4: Run to verify pass**

Run: `cd /d/devel/maya-mcp && uv run pytest tests/test_material.py -q`
Expected: PASS, 4 passed

- [ ] **Step 5: Real-Maya round-trip through `get_object_info`**

This is the spec's headline mechanical gate — assigned, then read back through Task 1's tool. Append to `tests/test_handlers_mayapy.py`:

```python
class TestMaterialInMaya:
    def test_assigned_material_reads_back_through_get_object_info(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import material, objinfo

        cmds.file(new=True, force=True)
        cmds.file(rename=str(tmp_path / "material.ma"))
        cmds.polyCube(name="matcube", w=2, h=2, d=2)

        result = material.assign_material({
            "mesh": "|matcube", "shader": "standardSurface",
            "params": {"baseColor": [0.4, 0.3, 0.25], "roughness": 0.8},
            "name": "clay",
        })
        info = objinfo.get_object_info({"name": "|matcube", "include": ["shading"]})
        assert info["shading"]["materials"] == [result["material"]]
        assert info["shading"]["per_face"] is False
        assert cmds.getAttr(result["material"] + ".specularRoughness") == pytest.approx(0.8)

    def test_assign_takes_no_checkpoint(self, tmp_path):
        # Look-dev is a loop of small tweaks; checkpointing each would evict
        # the checkpoints that matter.
        import maya.cmds as cmds

        from maya_plugin.handlers import material, session

        cmds.file(new=True, force=True)
        cmds.file(rename=str(tmp_path / "material_cp.ma"))
        cmds.polyCube(name="cpcube")
        before = len(session._existing(session._checkpoint_dir(cmds)))
        material.assign_material({"mesh": "|cpcube", "params": {"roughness": 0.5}})
        after = len(session._existing(session._checkpoint_dir(cmds)))
        assert after == before
```

- [ ] **Step 6: Register, schema, wrapper**

`_build_handlers()`: `"assign_material": material.assign_material,`

`schemas.py`:

```python
class MaterialResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mesh: str
    material: str = Field(description="Name of the shader node created.")
    shading_group: str
    shader: str
    warnings: List[str] = Field(default_factory=list)
```

`server.py`:

```python
    @mcp.tool(
        title="Assign material",
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=False
        ),
    )
    def maya_assign_material(
        mesh: Annotated[str, Field(min_length=1, description="Canonical long name.")],
        shader: Annotated[
            Literal["standardSurface", "lambert", "blinn"],
            Field(description="Shader type to create."),
        ] = "standardSurface",
        params: Annotated[dict, Field(description=(
            "Whitelisted per shader. standardSurface: baseColor, roughness, "
            "metalness, emission, emissionColor, specular. lambert: color, "
            "transparency, incandescence. blinn adds eccentricity, "
            "specularColor. Colours are [r, g, b] in 0..1. Unknown keys are "
            "rejected with that shader's whitelist in the hint."
        ))] = {},
        name: Annotated[Optional[str], Field(description=(
            "Material name; defaults to <mesh>_mat. Collisions get a _NNN suffix."
        ))] = None,
    ) -> MaterialResult:
        """Assign one material to a whole mesh (object-level shading only).

        Multi-material looks come from splitting geometry into separate meshes -
        per-face assignment is unreliable on boolean output."""
        return MaterialResult.model_validate(
            maya.request(
                "assign_material",
                {"mesh": mesh, "shader": shader, "params": params, "name": name},
                timeout_s=SCENE_TIMEOUT_S,
            )
        )
```

- [ ] **Step 7: Run everything and commit**

```bash
git add maya_plugin/handlers/material.py maya_plugin/maya_mcp_plugin.py src/maya_mcp/schemas.py src/maya_mcp/server.py tests/test_material.py tests/test_handlers_mayapy.py
git commit -m "feat(m2): assign_material - object-level PBR shading (redmine #581)"
```

---

### Task 7: `apply_texture_recipe`

**Files:**
- Create: `maya_plugin/handlers/texture_recipes.py`
- Create: `tests/test_texture_recipes.py`
- Modify: `maya_plugin/maya_mcp_plugin.py`, `src/maya_mcp/schemas.py`, `src/maya_mcp/server.py`, `tests/test_handlers_mayapy.py`

**Interfaces:**
- Consumes: `material.resolve_slot`, `material.SHADER_SLOTS`, `naming.require_mesh`, `naming.unique_name`.
- Produces: `texture_recipes.apply_texture_recipe(params) -> {"mesh": str, "recipe": str, "slot": str, "nodes": [str], "warnings": [str]}`.

**The discipline that matters:** every node created is tracked, and a failure anywhere sweeps exactly those nodes — the `etch_text` `finally` pattern. The test asserts it on a *forced mid-recipe failure*, not only on the happy path.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_texture_recipes.py
"""Named texture recipes - no Maya required."""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import texture_recipes


class FakeCmds:
    def __init__(self):
        self.objects = {"|torso", "clay_mat"}
        self.shapes = {"|torso": ("|torso|torsoShape", "mesh")}
        self.created = []
        self.connections = []
        self.deleted = []
        self.fail_on = None

    def ls(self, name=None, long=False, **kw):
        return [o for o in self.objects if o == name or o.split("|")[-1] == name]

    def objExists(self, name):
        return name in self.objects

    def listRelatives(self, node, shapes=False, fullPath=False, noIntermediate=False):
        entry = self.shapes.get(node)
        return [entry[0]] if entry else None

    def nodeType(self, node):
        return "mesh" if node.endswith("Shape") else "standardSurface"

    def listConnections(self, node, type=None, **kw):
        if type == "shadingEngine":
            return ["clay_matSG"]
        return ["clay_mat"]

    def listSets(self, object=None, type=None):
        return ["clay_matSG"]

    def shadingNode(self, node_type, name=None, **kw):
        if self.fail_on == node_type:
            raise RuntimeError("forced failure creating %s" % node_type)
        self.created.append(name)
        self.objects.add(name)
        return name

    def connectAttr(self, src, dst, force=False):
        self.connections.append((src, dst))

    def setAttr(self, attr, *value, **kw):
        pass

    def delete(self, *names, **kw):
        for n in names:
            self.deleted.append(n)
            self.objects.discard(n)


def test_noise_bump_builds_and_connects_to_the_normal_slot(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(texture_recipes, "_cmds", lambda: fake)
    result = texture_recipes.apply_texture_recipe(
        {"mesh": "|torso", "recipe": "noise_bump", "params": {"scale": 2.0}}
    )
    assert result["recipe"] == "noise_bump"
    assert result["slot"] == "normal"
    assert len(result["nodes"]) == 2          # noise + bump2d
    assert any(dst.endswith(".normalCamera") for _, dst in fake.connections)


def test_unknown_recipe_lists_the_valid_ones(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(texture_recipes, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        texture_recipes.apply_texture_recipe({"mesh": "|torso", "recipe": "marble"})
    assert "noise_bump" in exc.value.hint


def test_failure_midway_sweeps_every_node_it_created(monkeypatch):
    # The zero-orphan rule, asserted on the path that actually breaks it.
    fake = FakeCmds()
    fake.fail_on = "bump2d"        # noise is created first, then this raises
    monkeypatch.setattr(texture_recipes, "_cmds", lambda: fake)
    with pytest.raises(Exception):
        texture_recipes.apply_texture_recipe(
            {"mesh": "|torso", "recipe": "noise_bump"}
        )
    assert fake.deleted == fake.created, (
        "recipe left orphans: created %s, deleted %s" % (fake.created, fake.deleted)
    )


def test_file_texture_requires_a_path(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(texture_recipes, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        texture_recipes.apply_texture_recipe(
            {"mesh": "|torso", "recipe": "file_texture"}
        )
    assert "file_path" in str(exc.value) or "file_path" in exc.value.hint
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /d/devel/maya-mcp && uv run pytest tests/test_texture_recipes.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# maya_plugin/handlers/texture_recipes.py
"""Named texture recipes (design doc 5.4, narrowed).

The doc specifies an arbitrary NodeSpec DAG. That is deferred: it is the
largest single item in M2 and hard to test meaningfully without real usage
showing which nodes matter. A small set of validated recipes covers most
genuine need at a fraction of the surface area; the general builder lands
later, informed by which recipes people actually reach for.

Every node a recipe creates is tracked, so any failure sweeps exactly those
nodes and nothing else - the etch_text finally pattern from M1.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from ..dispatcher import HandlerError
from . import material, naming

RECIPES = ("noise_bump", "ramp_gradient", "layered_mask", "file_texture")
# Which semantic slot each recipe drives.
RECIPE_SLOT = {
    "noise_bump": "normal",
    "ramp_gradient": "color",
    "layered_mask": "color",
    "file_texture": "color",
}


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _shader_of(cmds, shape: str):
    """The shader node feeding this shape, and its type."""
    sgs = cmds.listSets(object=shape, type=1) or []
    if not sgs:
        raise HandlerError(
            "%s has no shading group" % shape,
            hint="call maya_assign_material first - a texture needs a shader "
            "to connect to",
        )
    shaders = cmds.listConnections(sgs[0], type=None) or []
    if not shaders:
        raise HandlerError(
            "shading group %s has no shader" % sgs[0],
            hint="call maya_assign_material first",
        )
    shader = shaders[0]
    return shader, cmds.nodeType(shader)


def _noise_bump(cmds, tracker, shader, attr, params) -> None:
    scale = float(params.get("scale", 1.0))
    depth = float(params.get("depth", 0.4))
    noise = tracker(cmds.shadingNode("noise", asTexture=True,
                                     name=naming.unique_name(cmds, "mcpTex_noise")))
    bump = tracker(cmds.shadingNode("bump2d", asUtility=True,
                                    name=naming.unique_name(cmds, "mcpTex_bump")))
    cmds.setAttr(noise + ".frequency", 8.0 * scale)
    cmds.setAttr(bump + ".bumpDepth", depth)
    cmds.connectAttr(noise + ".outColorR", bump + ".bumpValue", force=True)
    cmds.connectAttr(bump + ".outNormal", "%s.%s" % (shader, attr), force=True)


def _ramp_gradient(cmds, tracker, shader, attr, params) -> None:
    ramp = tracker(cmds.shadingNode("ramp", asTexture=True,
                                    name=naming.unique_name(cmds, "mcpTex_ramp")))
    cmds.connectAttr(ramp + ".outColor", "%s.%s" % (shader, attr), force=True)


def _layered_mask(cmds, tracker, shader, attr, params) -> None:
    layered = tracker(cmds.shadingNode(
        "layeredTexture", asTexture=True,
        name=naming.unique_name(cmds, "mcpTex_layered")))
    mask = tracker(cmds.shadingNode(
        "noise", asTexture=True, name=naming.unique_name(cmds, "mcpTex_mask")))
    cmds.connectAttr(mask + ".outAlpha", layered + ".inputs[0].alpha", force=True)
    cmds.connectAttr(layered + ".outColor", "%s.%s" % (shader, attr), force=True)


def _file_texture(cmds, tracker, shader, attr, params) -> None:
    path = params.get("file_path")
    if not path:
        raise HandlerError(
            "the file_texture recipe requires file_path",
            hint="pass an absolute path to an image file",
        )
    node = tracker(cmds.shadingNode("file", asTexture=True,
                                    name=naming.unique_name(cmds, "mcpTex_file")))
    cmds.setAttr(node + ".fileTextureName", str(path), type="string")
    cmds.connectAttr(node + ".outColor", "%s.%s" % (shader, attr), force=True)


_BUILDERS: Dict[str, Callable] = {
    "noise_bump": _noise_bump,
    "ramp_gradient": _ramp_gradient,
    "layered_mask": _layered_mask,
    "file_texture": _file_texture,
}


def apply_texture_recipe(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    mesh_long, shape = naming.require_mesh(cmds, str(params.get("mesh") or ""))
    recipe = params.get("recipe")
    if recipe not in RECIPES:
        raise HandlerError(
            "unknown recipe %r" % recipe,
            hint="valid recipes: %s" % ", ".join(RECIPES),
        )
    shader, shader_type = _shader_of(cmds, shape)
    slot = params.get("slot") or RECIPE_SLOT[recipe]
    attr = material.resolve_slot(shader_type, slot)

    created: List[str] = []

    def tracker(node: str) -> str:
        created.append(node)
        return node

    try:
        _BUILDERS[recipe](cmds, tracker, shader, attr, params.get("params") or {})
    except Exception:
        # zero orphans: sweep exactly what this call built, nothing else
        for node in reversed(created):
            if cmds.objExists(node):
                try:
                    cmds.delete(node)
                except Exception:
                    pass
        raise

    return {
        "mesh": mesh_long,
        "recipe": recipe,
        "slot": slot,
        "nodes": created,
        "warnings": [],
    }
```

- [ ] **Step 4: Run to verify pass**

Run: `cd /d/devel/maya-mcp && uv run pytest tests/test_texture_recipes.py -q`
Expected: PASS, 4 passed

- [ ] **Step 5: Real-Maya orphan audit**

Append to `tests/test_handlers_mayapy.py`:

```python
class TestTextureRecipesInMaya:
    def test_recipe_connects_and_leaves_no_orphans_on_failure(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import material, texture_recipes

        cmds.file(new=True, force=True)
        cmds.file(rename=str(tmp_path / "recipes.ma"))
        cmds.polyCube(name="texcube", w=2, h=2, d=2)
        material.assign_material({"mesh": "|texcube", "name": "clay"})

        before = set(cmds.ls(long=True))
        result = texture_recipes.apply_texture_recipe(
            {"mesh": "|texcube", "recipe": "noise_bump"}
        )
        assert len(result["nodes"]) == 2
        assert cmds.listConnections("clay.normalCamera") != []

        # a failing recipe must return the scene to exactly this state
        mid = set(cmds.ls(long=True))
        with pytest.raises(HandlerError):
            texture_recipes.apply_texture_recipe(
                {"mesh": "|texcube", "recipe": "file_texture"}  # no file_path
            )
        assert set(cmds.ls(long=True)) == mid
```

- [ ] **Step 6: Register, schema, wrapper**

`_build_handlers()`: `"apply_texture_recipe": texture_recipes.apply_texture_recipe,`

`schemas.py`:

```python
class TextureRecipeResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mesh: str
    recipe: str
    slot: str = Field(description="Semantic slot driven: color, roughness, or normal.")
    nodes: List[str] = Field(description="Texture nodes created by the recipe.")
    warnings: List[str] = Field(default_factory=list)
```

`server.py`:

```python
    @mcp.tool(
        title="Apply texture recipe",
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=False
        ),
    )
    def maya_apply_texture_recipe(
        mesh: Annotated[str, Field(min_length=1, description="Canonical long name.")],
        recipe: Annotated[
            Literal["noise_bump", "ramp_gradient", "layered_mask", "file_texture"],
            Field(description=(
                "noise_bump - surface grain via bump; ramp_gradient - gradient "
                "into colour; layered_mask - masked blend; file_texture - an "
                "image file. Requires a material on the mesh first."
            )),
        ],
        params: Annotated[dict, Field(description=(
            "noise_bump: scale, depth. file_texture: file_path (required). "
            "Others take no params yet."
        ))] = {},
        slot: Annotated[
            Optional[Literal["color", "roughness", "normal"]],
            Field(description=(
                "Override the recipe's default slot. Mapped to the real attribute "
                "per shader type; a slot the shader lacks is an error, not a no-op."
            )),
        ] = None,
    ) -> TextureRecipeResult:
        """Build a named texture network and wire it into the mesh's shader."""
        return TextureRecipeResult.model_validate(
            maya.request(
                "apply_texture_recipe",
                {"mesh": mesh, "recipe": recipe, "params": params, "slot": slot},
                timeout_s=SCENE_TIMEOUT_S,
            )
        )
```

- [ ] **Step 7: Run everything and commit**

```bash
git add maya_plugin/handlers/texture_recipes.py maya_plugin/maya_mcp_plugin.py src/maya_mcp/schemas.py src/maya_mcp/server.py tests/test_texture_recipes.py tests/test_handlers_mayapy.py
git commit -m "feat(m2): named texture recipes with zero-orphan sweeping (redmine #581)"
```

---

### Task 8: The judged run, docs, and ticket

The milestone gate. Everything before this asserted plumbing; this is the part that asks whether it looks right.

**Files:**
- Create: `evals/m2_judged_run.py`
- Create: `evals/m2_run/` (committed PNGs)
- Modify: `README.md`, `docs/protocol.md`
- Modify: `.superpowers/sdd/progress.md`

- [ ] **Step 1: Write the judged-run driver**

```python
# evals/m2_judged_run.py
"""M2 exit test: light, material, and judge a model against a reference.

Drives the live plugin over TCP, exactly like evals/isolate_regression.py.
Writes every capture to evals/m2_run/ so the run is reviewable after the fact -
these PNGs are M2's only exit evidence.

Run:  .venv/Scripts/python.exe evals/m2_judged_run.py <reference_image_path>
Exit: 0 completed, 1 a tool failed, 2 could not connect.
"""

from __future__ import annotations

import base64
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from maya_plugin import protocol  # noqa: E402

HOST = os.environ.get("MAYA_MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("MAYA_MCP_PORT", 9877))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "m2_run")


def call(cmd, params, timeout_s=120.0):
    sock = socket.create_connection((HOST, PORT), timeout=timeout_s + 30)
    try:
        sock.sendall(protocol.encode_frame(protocol.make_request(cmd, params, timeout_s)))
        resp = protocol.read_frame(sock.recv)
    finally:
        sock.close()
    if resp.get("status") != "ok":
        raise RuntimeError("%s failed: %s" % (cmd, resp.get("error")))
    return resp["result"]


def save(result, name):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    with open(path, "wb") as fh:
        fh.write(base64.b64decode(result["images"][0]["png_b64"]))
    print("  ->", path)
    return path


def main():
    print("1. building a subject")
    call("create_primitive", {"kind": "sphere", "name": "m2_subject",
                              "divisions": 3})
    print("2. lighting it")
    lit = call("setup_lighting", {"preset": "three_point", "intensity": 1.2})
    print("  lights:", lit["lights"], "removed:", lit["removed"])

    print("3. unlit vs lit - the spec 2 requirement, visible")
    save(call("capture_viewport", {"angles": ["three_quarter"],
                                   "lighting": "default", "resolution": 640}),
         "01_default_lighting.png")
    save(call("capture_viewport", {"angles": ["three_quarter"],
                                   "lighting": "scene", "resolution": 640}),
         "02_scene_lighting.png")

    print("4. material + texture")
    mat = call("assign_material", {
        "mesh": "|m2_subject", "shader": "standardSurface",
        "params": {"baseColor": [0.45, 0.32, 0.26], "roughness": 0.85},
        "name": "m2_clay"})
    print("  material:", mat["material"], "sg:", mat["shading_group"])
    tex = call("apply_texture_recipe", {"mesh": "|m2_subject",
                                        "recipe": "noise_bump",
                                        "params": {"scale": 2.0, "depth": 0.5}})
    print("  texture nodes:", tex["nodes"])
    save(call("capture_viewport", {"angles": ["three_quarter"],
                                   "lighting": "scene", "resolution": 640}),
         "03_materialed.png")

    print("5. readback check")
    info = call("get_object_info", {"name": "|m2_subject", "include": ["shading"]})
    assert info["shading"]["materials"] == [mat["material"]], info
    assert info["shading"]["per_face"] is False, info
    print("  shading reads back:", info["shading"])

    print("6. turntable")
    tt = call("capture_turntable", {"target": "|m2_subject", "n_frames": 8,
                                    "lighting": "scene"})
    os.makedirs(OUT, exist_ok=True)
    for shot in tt["images"]:
        with open(os.path.join(OUT, "tt_%02d.png" % shot["index"]), "wb") as fh:
            fh.write(base64.b64decode(shot["png_b64"]))
    print("  %d frames written" % tt["n_frames"])

    print("\nJUDGED RUN COMPLETE - review evals/m2_run/ by eye.")
    print("01 vs 02 must differ (scene lighting reaches pixels).")
    print("03 must show surface grain from the noise_bump recipe.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ConnectionRefusedError, OSError) as exc:
        print("could not reach the plugin on %s:%d - is Maya open? (%s)"
              % (HOST, PORT, exc))
        sys.exit(2)
    except Exception as exc:
        print("FAILED:", exc)
        sys.exit(1)
```

- [ ] **Step 2: Run it on the disposable Maya first**

```bash
MAYA_MCP_PORT=9878 "E:/Autodesk/Maya2027/bin/maya.exe" &
```

Run: `cd /d/devel/maya-mcp && MAYA_MCP_PORT=9878 .venv/Scripts/python.exe evals/m2_judged_run.py`
Expected: exit 0, and `evals/m2_run/` populated. A disposable Maya does not render, so the PNGs will be blank — this run only proves the *tool chain* completes. If any tool errors, fix it before touching the user's Maya.

- [ ] **Step 3: Run it on the user's Maya for the real pixels**

Ask the user to confirm their Maya is open, then:

Run: `cd /d/devel/maya-mcp && .venv/Scripts/python.exe evals/m2_judged_run.py`
Expected: exit 0

Then verify by eye, and state the result plainly:
- `01_default_lighting.png` and `02_scene_lighting.png` must visibly differ. If they do not, `displayLights` is not reaching VP2 and Task 2 is not actually done.
- `03_materialed.png` must show the clay colour and visible surface grain.
- The turntable frames must orbit the subject, not wobble.

- [ ] **Step 4: Commit the artifacts**

```bash
git add evals/m2_judged_run.py evals/m2_run/*.png
git commit -m "eval(m2): judged run driver + recorded exit evidence (redmine #581)"
```

- [ ] **Step 5: Update the docs**

In `README.md`, add the seven new tools to the tool-catalog table with one-line descriptions each. In `docs/protocol.md`, append the six new plugin command names (`get_object_info`, `capture_turntable`, `setup_lighting`, `assign_material`, `apply_texture_recipe`) to the command list — note that `load_reference_image` and `compare_to_reference` are **server-side only** and have no plugin command, which is worth stating explicitly so the two lists can be reconciled.

- [ ] **Step 6: Full three-leg sweep**

Run: `cd /d/devel/maya-mcp && uv run pytest -q` → PASS
Run: `cd /d/devel/maya-mcp && E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q` → PASS
Run: `cd /d/devel/maya-mcp && .venv/Scripts/python.exe evals/isolate_regression.py` → exit 0

- [ ] **Step 7: Commit docs and close out**

```bash
git add README.md docs/protocol.md
git commit -m "docs(m2): tool catalog + protocol command list for M2 (redmine #581)"
```

Then use `superpowers:finishing-a-development-branch`, and update redmine #581 with what landed, the test counts, the sweep results, and the judged-run outcome. Status **Resolved** if all three legs pass and the judged run looks right; **Feedback** if the judged run needs the user's eyes.

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| §2 lighting-aware capture (blocking) | 2, proven in 8 |
| §3.1 `get_object_info` | 1 |
| §3.1 `capture_turntable` | 3 |
| §3.1 `load_reference_image` / `compare_to_reference` | 4 |
| §3.2 `assign_material` | 6 |
| §3.2 `apply_texture_recipe` | 7 |
| §3.2 `setup_lighting` | 5 |
| §4 checkpoint only for `setup_lighting` | 5 (asserted), 6 (asserted absent) |
| §4 zero orphans | 7 (forced-failure test) |
| §4 references not scene state | 4 |
| §5.1 material readable back | 6 |
| §5.1 lighting reaches pixels | 2 |
| §5.1 exact light removal | 5 (node-count diff) |
| §5.1 turntable grid/order | 3 |
| §5.1 compare panel split | 3 (`side_by_side` test) |
| §5.2 judged run | 8 |
| §6 eyes before skin | task order 1→4 before 5→7 |
| §7 semantic slots | 6 (`resolve_slot`) |
| §7 no bundled HDRI | 5 |
| §7 turntable 8/16 | 3 |
| §7 artifacts committed | 8 |

No gaps.

**Placeholder scan:** every code step contains complete runnable code; no "add error handling" or "similar to Task N" steps.

**Type consistency:** `_capture_one`'s signature gains `lighting, shadows` in Task 2 and is called with exactly that arity by Task 3's turntable. `material.SHADER_SLOTS` / `material.resolve_slot` defined in Task 6 are consumed by Task 7 under the same names. `objinfo.get_object_info`'s `shading` shape (`shading_groups`, `materials`, `per_face`) defined in Task 1 is asserted verbatim in Tasks 6 and 8. `images.contact_sheet` / `images.side_by_side` defined in Task 3 are consumed in Tasks 3 and 4.

**One risk flagged for the implementer:** Task 3 refactors `camera_placement` into a shared `_placement` helper. The existing named-angle tests must pass unchanged — that is the proof the refactor preserved behaviour. If they need editing, the refactor is wrong.
