# Rigging Phase 5 — blend shapes Implementation Plan (#691)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two commands — `create_blendshape(mesh, targets=[{name, target_mesh}])` wires ordinary sculpted meshes as morph targets (front-of-chain, targets consumed, per-target delta MEASURED), `set_blendshape_weights(mesh, weights={name: 0..1})` drives them and measures what moved — plus shapes riding along in every FBX export with the byte gate asserting one Shape record per authored target name.

**Architecture:** One new handler module `blendshape.py`, all-`cmds` orchestration with a module-level `_points` seam (the `rigging._set_skin_weights` monkeypatch precedent) — there is no new math, so no new math module (displacement is `sculpt_math.max_displacement`, already pure and tested). `fbxbytes.py` learns to read Shape geometries and BlendShape/BlendShapeChannel deformers WITHOUT letting delta clouds pollute `meshes`/`mesh_count`/bounds; `export.py` pins `FBXExportShapes -v true` unconditionally and gains `shape_violations` so a scene-authored target missing from the file refuses the export. Spec: `docs/superpowers/specs/2026-08-20-rigging-p5-blendshapes-design.md` (settled decisions are binding) on top of the Phase 5 section of `2026-08-19-rigging-surface-design.md`. Ticket #691.

**Tech Stack:** Python (Maya plugin handlers + FastMCP server), pytest three-leg testing (FakeCmds orchestration / synthetic-facts fbxbytes / mayapy real-Maya), live gate over the TCP client extending the #668 humanoid.

## Global Constraints

- **Decisions settled with the user 2026-08-20** (design doc — do not relitigate): front-of-chain; topology must match (refusal with both counts, no wrap fallback); targets are CONSUMED (deleted after wiring); weights all-0 IS the reset and `reset_pose`'s contract is untouched; shapes export automatically with no caller-facing parameter; the byte gate asserts one Shape record per declared target name with non-empty delta data.
- **Report measured, never echoed** (#636): `max_delta` is read from the base mesh with the weight driven to 1, `max_displacement` from before/after vertex reads, achieved weights re-read via `getAttr` after the write. Distances are scene units (#629/#634), no angles exist anywhere in this phase.
- **Silence is never an answer** (#638/#640): zero-delta targets, a call that changed no weight, scene targets absent from the exported file — warnings or violations with numbers/names, never omissions.
- **Mutators auto-checkpoint** (`session.auto_checkpoint`), one checkpoint per call, taken only after validation passes (a bad call must cost nothing).
- **The name is the contract**: each target's `name` becomes the weight alias (`aliasAttr`), the `set_blendshape_weights` key, and the exported Shape/channel record name. Names must be plain identifiers because they become Maya attribute names.
- Two-Maya policy: the live gate runs on a disposable agent-launched Maya, port **9878** (`MAYA_MCP_PORT` overrides), **neutral cwd** (#604), pid verified (#648). Never `new_scene` on the user's 9877.
- Suites at branch base (`rigging-p5-blendshapes`, on main 924c928): `uv run pytest -q` = **1212 passed + 1 skipped**, `E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q` = **132 passed + 1 skipped**. Both stay green; counts only grow. 51 tools currently; this phase makes **53**.
- **Plan literals are measured, not guessed**: the FBX channel/shape record NAMING Maya actually writes is pinned by a mayapy test (Task 4) before the gate relies on it; `fbxbytes.shape_facts` cleans names defensively (`_clean` + `split(".")[-1]`) so either observed form matches the alias.
- The delivery under `evals/golem_delivery/` stays frozen; `evals/humanoid_live/` baseline files are NOT rewritten by this phase — the new gate writes its own `evals/blendshape_live/` directory.

## File structure

| file | responsibility |
|---|---|
| `maya_plugin/handlers/blendshape.py` (create) | `create_blendshape`, `set_blendshape_weights`, seams `_points`, `_blend_node_for`, `_aliases`, validation `_validated_targets`. |
| `maya_plugin/handlers/fbxbytes.py` (modify) | Shape-geometry + BlendShape/BlendShapeChannel records into new `FbxFacts` fields; `shape_facts()`. Mesh records keep their exact current behavior. |
| `maya_plugin/handlers/export.py` (modify) | `FBX_SHAPES_MEL` pinned true; `_scene_shape_aliases`; `shape_violations`; `shapes` block in the result. |
| `maya_plugin/maya_mcp_plugin.py` (modify) | Import `blendshape`, register `"create_blendshape"`, `"set_blendshape_weights"`. |
| `src/maya_mcp/schemas.py` (modify) | `BlendshapeTargetSpec` (input), `TargetDelta`, `CreateBlendshapeResult`, `TargetDisplacement`, `SetBlendshapeWeightsResult`, `ShapeRecord`, `ShapeFacts`, `ExportFbxResult.shapes`. |
| `src/maya_mcp/server.py` (modify) | `maya_create_blendshape`, `maya_set_blendshape_weights` (53 total). |
| `docs/protocol.md` (modify) | Phase-5 command section. |
| `evals/blendshape_live.py` (create) | The live gate: humanoid + expression + corrective, judged renders 0/0.5/1, measured monotonic displacement, corrective judged AT a posed elbow, skinned+shaped export byte-gated, `evals/blendshape_live/baseline.json`. |
| `tests/test_blendshape.py` (create), `tests/test_fbxbytes.py` (modify), `tests/test_export_fbx.py` (modify), `tests/test_server_tools.py` (modify), `tests/test_handlers_mayapy.py` (modify) | Coverage per leg. |

### Contract decisions locked here (plan-level refinements of the spec)

1. **One blendShape node per mesh, additive.** `create_blendshape` on a mesh that already has a blendShape (from this tool or otherwise, found via `listHistory`) ADDS the new targets to that node at the next free indices instead of stacking a second deformer — stacked blendShapes are the weights-unexplainable failure re-materialized, and additive create keeps iterative authoring alive (author the expression, judge it, add the corrective). A `name` colliding with an existing alias refuses. `set_blendshape_weights` addresses the mesh's one node.
2. **Alias explicitly, never trust the target mesh's name.** After wiring, each new index is aliased with `cmds.aliasAttr(name, node + ".w[i]")` so the caller's `name` is the contract even when the target mesh was called `humanoid_brow_003`. `_aliases` reads `cmds.listAttr(node + ".w", multi=True)` — index order.
3. **Measured `max_delta` at weight 1 through the real deformer**: after wiring, baseline vertex read, then per new target: drive its weight to 1 (others untouched), re-read, `sculpt_math.max_displacement`, restore 0. Pre-existing targets keep whatever weights they held — those cancel out of the before/after comparison. Deltas live in OBJECT space in the node, so a target duplicate that was translated aside for sculpting contributes no false delta (measured in Task 4). A target measuring below `ZERO_DELTA_RATIO = 1e-7` of the base's bbox diagonal warns "(near-)identical to the base" — the threshold sits far below `NOOP_POSE_RATIO` on purpose: a 1 mm blink on a 2 m figure is a legitimate 5e-4 shape.
4. **Targets consumed AFTER measuring**: `cmds.delete` on each target transform once its delta is measured (deltas persist in the node — pinned by a mayapy test). Duplicate `target_mesh` entries in one call refuse (one mesh cannot be consumed twice).
5. **`set_blendshape_weights` applies sequentially in call order** and measures per step: `per_target[i].max_displacement` is the move each weight landing caused given the previous ones already applied; `max_displacement` is overall before→after (which can be less than a step when shapes oppose). `weights` in the result is EVERY alias re-read from the node, not just the ones the call named. Unknown names refuse (listing what exists); values outside 0..1 refuse; a call whose every value already held warns "nothing moved".
6. **Export refuses a missing authored shape.** `export_fbx` collects the weight aliases of every blendShape reachable from the exported meshes (`_scene_shape_aliases` — selected exports walk their own `nodes`, whole-scene walks every non-intermediate mesh shape) and `shape_violations` fails the gate if any is absent from the file's channel names, if a shape carries zero delta points, if indexes ≠ points, or if the records are structurally unreadable. Same tmp-path + delete-on-violation flow the unit and skin gates already use.
7. **Shape geometries never pollute mesh facts.** In `fbxbytes.walk`, a `Geometry` record whose class string is `"Shape"` becomes a `("shape", uid)` child: its `Vertices` stores a COUNT (not the floats — nothing needs delta magnitudes from bytes), its `Indexes` (already int-decoded by name) stores the tuple. Everything else keeps the exact current behavior, so `mesh_count`, `world_vertex_bounds` and the committed-artifact tests are untouched.
8. **Gate targets** (user chose BOTH): one facial expression (`brow_raise`) judged front-on at 0/0.5/1, one muscle corrective (`L_elbow_bulge`) authored on the FOREARM (not at the elbow pivot — a delta centred on the pivot cannot distinguish deformation orders) and judged AT a 90°-bent elbow, with the measured front-of-chain proof: the displaced-vertex centroid rides the posed forearm, not the bind location.

---

### Task 1: The blendshape handler under FakeCmds

**Files:**
- Create: `maya_plugin/handlers/blendshape.py`
- Modify: `maya_plugin/maya_mcp_plugin.py` (handlers import list + two `_build_handlers` entries after `"author_physics"`)
- Test: `tests/test_blendshape.py`

**Interfaces:**
- Consumes: `naming.require_mesh`, `naming.unique_name`, `sculpt.vertex_positions`, `sculpt_math.max_displacement`, `sculpt_math.bbox_extent`, `session.auto_checkpoint`, `HandlerError`.
- Produces (Task 5's schemas and Task 7's gate read these keys by name):
  - `blendshape.create_blendshape(params) -> {mesh, blend_shape, targets: [{name, max_delta, vertex_count}], warnings}`
  - `blendshape.set_blendshape_weights(params) -> {mesh, blend_shape, weights: {alias: float}, max_displacement, per_target: [{name, weight, max_displacement}], warnings}`
  - Module-level `_points(mesh_long)` is the seam tests monkeypatch.

- [ ] **Step 1: Write the failing tests** — create `tests/test_blendshape.py`:

```python
"""create_blendshape / set_blendshape_weights (#691) under a FakeCmds.

Real deformation is mayapy's job (tests/test_handlers_mayapy.py); this file
pins validation, the alias contract, target consumption, the additive-create
rule, sequential measurement and every refusal path. The vertex seam
blendshape._points is monkeypatched - FakeCmds cannot deform, and that is
exactly why the seam is module-level (the rigging._set_skin_weights
precedent).
"""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import blendshape


class FakeCmds:
    """Transforms in `objects` (long names), shapes in `shapes`, per-shape
    history in `history`. blendShape nodes live in `blend_nodes` with their
    aliases in `aliases[node]` (index order); weights in `weights[(node,
    alias)]`. setAttr/getAttr accept both the `node.w[i]` plug form the
    handler uses during create and the `node.alias` form set_weights uses."""

    def __init__(self):
        self.objects = []
        self.shapes = {}          # transform long -> shape long
        self.history = {}         # shape long -> [node names]
        self.vertex_counts = {}   # transform long -> int
        self.blend_nodes = set()
        self.aliases = {}         # node -> [alias, ...]
        self.weights = {}         # (node, alias) -> float
        self.deleted = []
        self.created = []         # blendShape() create-call records
        self.edited = []          # blendShape(edit=True) records
        self.checkpoints = []

    # --- resolution ----------------------------------------------------
    def ls(self, pattern=None, long=False, type=None, **kw):
        if isinstance(pattern, list):
            if type == "blendShape":
                return [n for n in pattern if n in self.blend_nodes]
            return list(pattern)
        if pattern is None:
            return list(self.objects)
        return [o for o in self.objects
                if o == pattern or o.split("|")[-1] == pattern]

    def objExists(self, name):
        return bool(self.ls(name)) or name in self.blend_nodes

    def listRelatives(self, node, shapes=False, fullPath=False,
                      noIntermediate=False, **kw):
        if shapes:
            s = self.shapes.get(node)
            return [s] if s else None
        return None

    def nodeType(self, node):
        if node in self.blend_nodes:
            return "blendShape"
        return "mesh" if node.endswith("Shape") else "transform"

    def listHistory(self, node, pruneDagObjects=False, **kw):
        return list(self.history.get(node, []))

    def polyEvaluate(self, node, vertex=False, **kw):
        return self.vertex_counts[node]

    # --- the blendShape surface the handler drives ----------------------
    def blendShape(self, *args, **kw):
        if kw.get("edit"):
            node = args[0]
            base, index, target, _w = kw["target"]
            self.edited.append({"node": node, "index": index,
                                "target": target})
            self.aliases[node].append("w[%d]" % index)  # unaliased until aliasAttr
            return [node]
        *targets, base = args
        node = kw["name"]
        assert kw.get("frontOfChain") is True
        self.blend_nodes.add(node)
        self.aliases[node] = ["w[%d]" % i for i in range(len(targets))]
        self.created.append({"node": node, "base": base,
                             "targets": list(targets)})
        self.history.setdefault(self.shapes[base], []).append(node)
        return [node]

    def aliasAttr(self, alias, plug):
        node, index = plug.split(".w[")
        index = int(index[:-1])
        self.aliases[node][index] = alias
        self.weights.setdefault((node, alias), 0.0)

    def listAttr(self, plug, multi=False):
        node = plug.split(".")[0]
        return list(self.aliases.get(node, [])) or None

    def _resolve_weight_key(self, key):
        node, attr = key.split(".", 1)
        if attr.startswith("w[") and attr.endswith("]"):
            attr = self.aliases[node][int(attr[2:-1])]
        return node, attr

    def setAttr(self, key, value):
        node, alias = self._resolve_weight_key(key)
        self.weights[(node, alias)] = float(value)

    def getAttr(self, key):
        node, alias = self._resolve_weight_key(key)
        return self.weights[(node, alias)]

    def delete(self, *names):
        for n in names:
            self.deleted.append(n)
            self.objects.remove(n)


@pytest.fixture
def fake(monkeypatch):
    fake = FakeCmds()
    fake.deltas = {}   # alias -> per-unit-weight displacement of vertex 0
    monkeypatch.setattr(blendshape, "_cmds", lambda: fake)
    monkeypatch.setattr(blendshape.session, "auto_checkpoint",
                        lambda label: fake.checkpoints.append(label) or
                        {"checkpoint_id": "cp"})

    def points(mesh):
        # A 2-vertex mesh 1.0 wide (so bbox_extent is 1.0); vertex 0 rises
        # by sum(weight * delta) over every alias on every node - the
        # minimal linear model of what a blendShape does.
        lift = sum(fake.weights.get((node, alias), 0.0)
                   * fake.deltas.get(alias, 0.0)
                   for node in fake.aliases
                   for alias in fake.aliases[node])
        return [0.0, lift, 0.0, 1.0, 0.0, 0.0]

    monkeypatch.setattr(blendshape, "_points", points)
    return fake


def _scene(fake):
    fake.objects = ["|humanoid", "|brow", "|bulge"]
    fake.shapes = {"|humanoid": "|humanoid|humanoidShape",
                   "|brow": "|brow|browShape",
                   "|bulge": "|bulge|bulgeShape"}
    fake.vertex_counts = {"|humanoid": 2, "|brow": 2, "|bulge": 2}


def _create(fake, targets):
    return blendshape.create_blendshape(
        {"mesh": "humanoid", "targets": targets})


class TestCreateValidation:
    def test_refusals(self, fake):
        _scene(fake)
        with pytest.raises(HandlerError, match="targets must be"):
            blendshape.create_blendshape({"mesh": "humanoid"})
        with pytest.raises(HandlerError, match="targets must be"):
            blendshape.create_blendshape({"mesh": "humanoid", "targets": []})
        with pytest.raises(HandlerError, match="plain identifier"):
            _create(fake, [{"name": "2bad", "target_mesh": "brow"}])
        with pytest.raises(HandlerError, match="plain identifier"):
            _create(fake, [{"name": "has space", "target_mesh": "brow"}])
        with pytest.raises(HandlerError, match="appears twice"):
            _create(fake, [{"name": "a", "target_mesh": "brow"},
                           {"name": "a", "target_mesh": "bulge"}])
        with pytest.raises(HandlerError, match="reuses"):
            _create(fake, [{"name": "a", "target_mesh": "brow"},
                           {"name": "b", "target_mesh": "brow"}])
        with pytest.raises(HandlerError, match="its own target"):
            _create(fake, [{"name": "a", "target_mesh": "humanoid"}])
        with pytest.raises(HandlerError, match="not found"):
            _create(fake, [{"name": "a", "target_mesh": "nope"}])
        # nothing above reached the checkpoint - a bad call costs nothing
        assert fake.checkpoints == []

    def test_topology_mismatch_refused_with_both_counts(self, fake):
        _scene(fake)
        fake.vertex_counts["|brow"] = 3
        with pytest.raises(HandlerError,
                           match="topology does not match") as exc:
            _create(fake, [{"name": "a", "target_mesh": "brow"}])
        assert "2" in str(exc.value) and "3" in str(exc.value)


class TestCreate:
    def test_wires_aliases_measures_and_consumes(self, fake):
        _scene(fake)
        fake.deltas = {"brow_raise": 0.25, "bulge_up": 0.1}
        out = _create(fake, [
            {"name": "brow_raise", "target_mesh": "brow"},
            {"name": "bulge_up", "target_mesh": "bulge"}])
        assert out["mesh"] == "|humanoid"
        node = out["blend_shape"]
        assert fake.aliases[node] == ["brow_raise", "bulge_up"]
        by = {t["name"]: t for t in out["targets"]}
        assert by["brow_raise"]["max_delta"] == pytest.approx(0.25)
        assert by["bulge_up"]["max_delta"] == pytest.approx(0.1)
        assert by["brow_raise"]["vertex_count"] == 2
        # measured, then restored: every weight back at 0
        assert all(w == 0.0 for w in fake.weights.values())
        # consumed
        assert "|brow" in fake.deleted and "|bulge" in fake.deleted
        assert fake.checkpoints == ["create_blendshape"]

    def test_zero_delta_target_warns_but_wires(self, fake):
        _scene(fake)
        fake.deltas = {"noop": 0.0}
        out = _create(fake, [{"name": "noop", "target_mesh": "brow"}])
        assert any("identical to the base" in w for w in out["warnings"])
        assert out["targets"][0]["max_delta"] == 0.0
        assert "|brow" in fake.deleted

    def test_second_create_adds_to_the_same_node(self, fake):
        _scene(fake)
        fake.deltas = {"a": 0.2, "b": 0.3}
        first = _create(fake, [{"name": "a", "target_mesh": "brow"}])
        out = _create(fake, [{"name": "b", "target_mesh": "bulge"}])
        assert out["blend_shape"] == first["blend_shape"]
        assert fake.aliases[out["blend_shape"]] == ["a", "b"]
        assert fake.edited and fake.edited[0]["index"] == 1

    def test_alias_collision_with_existing_target_refused(self, fake):
        _scene(fake)
        fake.deltas = {"a": 0.2}
        _create(fake, [{"name": "a", "target_mesh": "brow"}])
        with pytest.raises(HandlerError, match="already exists"):
            _create(fake, [{"name": "a", "target_mesh": "bulge"}])


class TestSetWeights:
    def _wired(self, fake):
        _scene(fake)
        fake.deltas = {"brow_raise": 0.25, "bulge_up": 0.1}
        return _create(fake, [
            {"name": "brow_raise", "target_mesh": "brow"},
            {"name": "bulge_up", "target_mesh": "bulge"}])["blend_shape"]

    def test_refusals(self, fake):
        _scene(fake)
        with pytest.raises(HandlerError, match="no blendShape"):
            blendshape.set_blendshape_weights(
                {"mesh": "humanoid", "weights": {"a": 1.0}})
        node = self._wired(fake)
        for bad in ({}, None, []):
            with pytest.raises(HandlerError, match="non-empty map"):
                blendshape.set_blendshape_weights(
                    {"mesh": "humanoid", "weights": bad})
        with pytest.raises(HandlerError, match="not a target"):
            blendshape.set_blendshape_weights(
                {"mesh": "humanoid", "weights": {"nope": 0.5}})
        for value in (-0.1, 1.5, True, "x"):
            with pytest.raises(HandlerError, match="0..1"):
                blendshape.set_blendshape_weights(
                    {"mesh": "humanoid", "weights": {"brow_raise": value}})
        assert node in fake.blend_nodes  # nothing was harmed

    def test_sequential_measurement_and_reread(self, fake):
        self._wired(fake)
        out = blendshape.set_blendshape_weights(
            {"mesh": "humanoid",
             "weights": {"brow_raise": 1.0, "bulge_up": 0.5}})
        steps = {p["name"]: p for p in out["per_target"]}
        assert steps["brow_raise"]["max_displacement"] == pytest.approx(0.25)
        assert steps["bulge_up"]["max_displacement"] == pytest.approx(0.05)
        assert steps["brow_raise"]["weight"] == 1.0
        assert out["weights"] == {"brow_raise": 1.0, "bulge_up": 0.5}
        assert out["max_displacement"] == pytest.approx(0.30)
        assert out["warnings"] == []

    def test_all_zero_is_the_reset(self, fake):
        self._wired(fake)
        blendshape.set_blendshape_weights(
            {"mesh": "humanoid",
             "weights": {"brow_raise": 1.0, "bulge_up": 1.0}})
        out = blendshape.set_blendshape_weights(
            {"mesh": "humanoid",
             "weights": {"brow_raise": 0.0, "bulge_up": 0.0}})
        assert out["weights"] == {"brow_raise": 0.0, "bulge_up": 0.0}
        assert out["max_displacement"] == pytest.approx(0.35)

    def test_unnamed_aliases_still_reported(self, fake):
        self._wired(fake)
        out = blendshape.set_blendshape_weights(
            {"mesh": "humanoid", "weights": {"brow_raise": 0.5}})
        assert set(out["weights"]) == {"brow_raise", "bulge_up"}
        assert out["weights"]["bulge_up"] == 0.0

    def test_noop_call_warns(self, fake):
        self._wired(fake)
        out = blendshape.set_blendshape_weights(
            {"mesh": "humanoid", "weights": {"brow_raise": 0.0}})
        assert any("nothing moved" in w for w in out["warnings"])
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_blendshape.py -q`. Expected: FAIL, `ImportError`/`AttributeError` on `blendshape`.

- [ ] **Step 3: Implement** — create `maya_plugin/handlers/blendshape.py`:

```python
"""Blend shapes, phase 5 of #602 (#691): create_blendshape,
set_blendshape_weights.

Targets are ordinary meshes authored with the existing modeling/sculpt tools;
this module only wires deltas and measures what they do. The deformer goes
FRONT-OF-CHAIN (before any skinCluster): a shape models the neutral surface
and the skin carries the shaped surface to the pose, which is what makes an
elbow corrective correct at a bent elbow. Every number is a distance in scene
units MEASURED from vertices after the write (#636), never echoed - the
target's own vertices are not trusted even for max_delta, because what
matters is what the DEFORMER does to the base, not what the sculpt looked
like.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..dispatcher import HandlerError
from . import naming, sculpt, sculpt_math, session

MAX_TARGETS = 20
# Below this fraction of the base's bbox diagonal, a target's measured delta
# is float noise, not a shape: the target is (near-)identical to the base -
# almost always a duplicate that was never sculpted. Deliberately FAR below
# the 1e-2 noop ratio the pose/sculpt ops use: a 1 mm blink on a 2 m figure
# is a legitimate 5e-4 shape and must not warn.
ZERO_DELTA_RATIO = 1e-7


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _short(name: str) -> str:
    return name.split("|")[-1]


def _points(mesh_long: str) -> List[float]:
    """World-space vertex positions. Module-level so tests monkeypatch it:
    FakeCmds cannot deform, and the measurement is the part only a real Maya
    can supply (the rigging._set_skin_weights precedent)."""
    return sculpt.vertex_positions(_cmds(), mesh_long)


def _blend_node_for(cmds, mesh_shape: str) -> Optional[str]:
    """The mesh's ONE blendShape node, or None. One is all there can be:
    create_blendshape ADDS targets to an existing node instead of stacking a
    second deformer - stacked blendShapes are stacked skinClusters'
    weights-unexplainable failure with a different node type."""
    nodes = cmds.ls(cmds.listHistory(mesh_shape, pruneDagObjects=True) or [],
                    type="blendShape") or []
    return nodes[0] if nodes else None


def _aliases(cmds, node: str) -> List[str]:
    """Weight alias names in index order - the target-name contract."""
    return cmds.listAttr(node + ".w", multi=True) or []


def _validated_targets(cmds, mesh_long: str, targets,
                       existing: List[str]) -> List[Tuple[str, str]]:
    """[(name, target long name)] or a refusal. Runs BEFORE the checkpoint."""
    if (not isinstance(targets, list) or not targets
            or len(targets) > MAX_TARGETS):
        raise HandlerError(
            "targets must be a list of 1..%d {name, target_mesh} entries"
            % MAX_TARGETS,
            hint='e.g. targets=[{"name": "brow_raise", '
                 '"target_mesh": "humanoid_brow"}]')
    seen_names = set(existing)
    seen_meshes: Dict[str, str] = {}
    out: List[Tuple[str, str]] = []
    for i, entry in enumerate(targets):
        if not isinstance(entry, dict):
            raise HandlerError("targets[%d] must be {name, target_mesh}" % i)
        name = entry.get("name")
        if (not isinstance(name, str) or not name
                or not name.replace("_", "").isalnum()
                or name[0].isdigit()):
            raise HandlerError(
                "targets[%d].name %r must be a plain identifier (letters, "
                "digits, underscore; not starting with a digit)" % (i, name),
                hint="the name becomes the weight attribute, the "
                     "set_blendshape_weights key, and the exported Shape "
                     "record name")
        if name in existing:
            raise HandlerError(
                "target name %r already exists on this mesh's blendShape"
                % name,
                hint="existing targets: %s" % ", ".join(existing))
        if name in seen_names:
            raise HandlerError("target name %r appears twice in this call"
                               % name)
        seen_names.add(name)
        t_long, _shape = naming.require_mesh(
            cmds, str(entry.get("target_mesh") or ""))
        if t_long == mesh_long:
            raise HandlerError(
                "targets[%d]: the base mesh cannot be its own target" % i)
        if t_long in seen_meshes:
            raise HandlerError(
                "targets[%d] reuses %s, already consumed by target %r"
                % (i, t_long, seen_meshes[t_long]),
                hint="each target mesh is deleted after wiring, so one mesh "
                     "can carry only one target")
        seen_meshes[t_long] = name
        out.append((name, t_long))
    return out


def create_blendshape(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    mesh_long, mesh_shape = naming.require_mesh(
        cmds, str(params.get("mesh") or ""))
    node = _blend_node_for(cmds, mesh_shape)
    existing = _aliases(cmds, node) if node else []
    resolved = _validated_targets(cmds, mesh_long, params.get("targets"),
                                  existing)

    base_count = cmds.polyEvaluate(mesh_long, vertex=True)
    for name, t_long in resolved:
        t_count = cmds.polyEvaluate(t_long, vertex=True)
        if t_count != base_count:
            raise HandlerError(
                "target %r topology does not match: %s has %d vertices, %s "
                "has %d" % (name, _short(mesh_long), base_count,
                            _short(t_long), t_count),
                hint="a target must be a same-topology copy of the base "
                     "(maya_duplicate, then sculpt) - there is no wrap "
                     "fallback")

    session.auto_checkpoint("create_blendshape")

    if node is None:
        node = cmds.blendShape(
            *[t for _, t in resolved], mesh_long,
            frontOfChain=True,
            name=naming.unique_name(cmds, _short(mesh_long) + "_shapes"))[0]
        new_indices = list(range(len(resolved)))
    else:
        start = len(existing)
        new_indices = []
        for offset, (_name, t_long) in enumerate(resolved):
            cmds.blendShape(node, edit=True,
                            target=(mesh_long, start + offset, t_long, 1.0))
            new_indices.append(start + offset)
    for idx, (name, _t) in zip(new_indices, resolved):
        cmds.aliasAttr(name, "%s.w[%d]" % (node, idx))

    # MEASURED per target (#636): drive each new weight to 1 alone and
    # re-read the BASE mesh through the real deformer. Pre-existing targets
    # keep whatever weights they held - constant on both sides of the
    # comparison, so they cancel.
    warnings: List[str] = []
    baseline = _points(mesh_long)
    extent = sculpt_math.bbox_extent(baseline)
    targets_out: List[Dict[str, Any]] = []
    for idx, (name, _t_long) in zip(new_indices, resolved):
        plug = "%s.w[%d]" % (node, idx)
        cmds.setAttr(plug, 1.0)
        max_delta = sculpt_math.max_displacement(baseline, _points(mesh_long))
        cmds.setAttr(plug, 0.0)
        if extent > 0 and max_delta < extent * ZERO_DELTA_RATIO:
            warnings.append(
                "target %r measured max_delta %.3g against a %.3g-wide "
                "mesh - the target is (near-)identical to the base. It was "
                "wired anyway, but a duplicate that was never sculpted is "
                "the usual cause" % (name, max_delta, extent))
        targets_out.append({"name": name, "max_delta": max_delta,
                            "vertex_count": base_count})

    # Consume the targets: the deltas live in the deformer now, and a stale
    # editable copy invites sculpting a mesh that no longer feeds anything
    # (the boolean-operand reap logic).
    doomed = [t for _n, t in resolved if cmds.objExists(t)]
    if doomed:
        cmds.delete(*doomed)

    return {"mesh": mesh_long, "blend_shape": node,
            "targets": targets_out, "warnings": warnings}


def set_blendshape_weights(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    mesh_long, mesh_shape = naming.require_mesh(
        cmds, str(params.get("mesh") or ""))
    node = _blend_node_for(cmds, mesh_shape)
    if node is None:
        raise HandlerError(
            "%s has no blendShape" % mesh_long,
            hint="create_blendshape wires targets first")
    aliases = _aliases(cmds, node)
    weights = params.get("weights")
    if not isinstance(weights, dict) or not weights:
        raise HandlerError(
            "weights must be a non-empty map of target name to 0..1",
            hint='e.g. weights={"brow_raise": 0.5}; 0 for every target is '
                 'the reset')
    for name, value in weights.items():
        if name not in aliases:
            raise HandlerError(
                "%r is not a target of %s" % (name, node),
                hint="targets here: %s" % ", ".join(aliases))
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not 0.0 <= float(value) <= 1.0):
            raise HandlerError(
                "weights[%r] must be a number in 0..1, got %r"
                % (name, value))

    session.auto_checkpoint("set_blendshape_weights")

    # Sequential on purpose: each weight lands and is measured against the
    # state the previous ones left, in call order - so per_target reports
    # what each shape actually contributed, and the total is the honest
    # before/after (which can be SMALLER than a step when shapes oppose).
    before = _points(mesh_long)
    prev = before
    per_target: List[Dict[str, Any]] = []
    changed = False
    for name, value in weights.items():
        attr = "%s.%s" % (node, name)
        old = float(cmds.getAttr(attr))
        cmds.setAttr(attr, float(value))
        now = _points(mesh_long)
        achieved = float(cmds.getAttr(attr))
        per_target.append({
            "name": name,
            "weight": achieved,
            "max_displacement": sculpt_math.max_displacement(prev, now)})
        prev = now
        if abs(achieved - old) > 1e-9:
            changed = True

    warnings: List[str] = []
    if not changed:
        warnings.append(
            "every requested weight already held its value - nothing moved")
    out_weights = {a: float(cmds.getAttr("%s.%s" % (node, a)))
                   for a in aliases}
    return {"mesh": mesh_long, "blend_shape": node,
            "weights": out_weights,
            "max_displacement": sculpt_math.max_displacement(before, prev),
            "per_target": per_target, "warnings": warnings}
```

- [ ] **Step 4: Register** — in `maya_plugin/maya_mcp_plugin.py`, add `blendshape` to the existing `from .handlers import ...` list, and in `_build_handlers` after `"author_physics": physics.author_physics,` add:

```python
        "create_blendshape": blendshape.create_blendshape,
        "set_blendshape_weights": blendshape.set_blendshape_weights,
```

- [ ] **Step 5: Run to verify pass** — `uv run pytest tests/test_blendshape.py -q`. Expected: PASS (all). Then the whole suite: `uv run pytest -q` — 1212+new passed, 1 skipped.

- [ ] **Step 6: Commit**

```bash
git add maya_plugin/handlers/blendshape.py maya_plugin/maya_mcp_plugin.py tests/test_blendshape.py
git commit -m "feat(#691): create_blendshape / set_blendshape_weights - front-of-chain, consumed targets, measured deltas"
```

---

### Task 2: fbxbytes reads Shape and BlendShape records

**Files:**
- Modify: `maya_plugin/handlers/fbxbytes.py`
- Test: `tests/test_fbxbytes.py` (add a class)

**Interfaces:**
- Consumes: nothing new.
- Produces: `FbxFacts.shape_geoms` (`{uid: {"name", "points", "indexes"}}`), `FbxFacts.blend_channels` (`{uid: {"name", "shape", "deformer"}}`), `FbxFacts.blend_deformers` (`{uid: {"geometry", "channels"}}`), and `fbxbytes.shape_facts(facts) -> {"blend_deformers", "channels", "shapes": [{"name", "points", "indexes"}], "unavailable_reason"}` (Task 3 gates on it, Task 5's schema mirrors it).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_fbxbytes.py`:

```python
class TestShapeFacts:
    """Blend-shape records (#691). Synthetic facts here; that these shapes
    match what Maya WRITES is pinned under mayapy
    (TestBlendshapeExportInMaya), which is also where the channel-naming
    measurement lives."""

    def _facts(self):
        facts = FbxFacts(version=7500)
        facts.nodes.append(FbxNode(name="humanoid", kind="Mesh", uid=1,
                                   geometry=10))
        facts.geometries[10] = (0.0, 0.0, 0.0)
        facts.shape_geoms[20] = {"name": "brow_raise", "points": 6,
                                 "indexes": (0, 1, 2, 3, 4, 5)}
        facts.blend_channels[30] = {"name": "brow_raise", "shape": 20,
                                    "deformer": 40}
        facts.blend_deformers[40] = {"geometry": 10, "channels": [30]}
        return facts

    def test_a_healthy_file_reads_clean(self):
        out = fbxbytes.shape_facts(self._facts())
        assert out["blend_deformers"] == 1 and out["channels"] == 1
        assert out["shapes"] == [
            {"name": "brow_raise", "points": 6, "indexes": 6}]
        assert out["unavailable_reason"] is None

    def test_channel_names_are_cleaned_to_the_alias(self):
        facts = self._facts()
        facts.blend_channels[30]["name"] = "humanoid_shapes.brow_raise"
        out = fbxbytes.shape_facts(facts)
        assert out["shapes"][0]["name"] == "brow_raise"

    def test_orphan_links_are_reasons_never_guesses(self):
        facts = self._facts()
        facts.blend_channels[30]["shape"] = None
        facts.blend_deformers[40]["geometry"] = None
        out = fbxbytes.shape_facts(facts)
        assert "links no shape geometry" in out["unavailable_reason"]
        assert "deforms no geometry" in out["unavailable_reason"]
        assert out["shapes"][0]["points"] == 0

    def test_shapes_are_sorted_by_name(self):
        facts = self._facts()
        facts.shape_geoms[21] = {"name": "a_first", "points": 3,
                                 "indexes": (0, 1, 2)}
        facts.blend_channels[31] = {"name": "a_first", "shape": 21,
                                    "deformer": 40}
        facts.blend_deformers[40]["channels"].append(31)
        out = fbxbytes.shape_facts(facts)
        assert [s["name"] for s in out["shapes"]] == ["a_first",
                                                      "brow_raise"]

    def test_a_shapeless_facts_reads_empty(self):
        out = fbxbytes.shape_facts(FbxFacts(version=7500))
        assert out == {"blend_deformers": 0, "channels": 0, "shapes": [],
                       "unavailable_reason": None}
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_fbxbytes.py -q`. Expected: FAIL (`shape_geoms` unknown / `shape_facts` missing).

- [ ] **Step 3: Implement.** Four edits inside `fbxbytes.py`:

**(a)** `FbxFacts` gains, after `bind_pose_count`:

```python
    # Blend shapes (#602 phase 5 / #691). shape_geoms: Shape-class Geometry
    # uid -> {"name", "points" (delta-vertex COUNT - nothing needs the
    # floats), "indexes" (tuple of sparse vertex ids)}. blend_channels:
    # BlendShapeChannel deformer uid -> {"name", "shape" geom uid,
    # "deformer" uid}. blend_deformers: BlendShape deformer uid ->
    # {"geometry" mesh-geometry uid, "channels": [uid]}.
    shape_geoms: dict = field(default_factory=dict)
    blend_channels: dict = field(default_factory=dict)
    blend_deformers: dict = field(default_factory=dict)
```

**(b)** In `walk`, the `Vertices` branch becomes (Shape delta clouds must NEVER reach `meshes`/`geometries` — they would inflate `mesh_count` and corrupt `world_vertex_bounds`):

```python
            if name == "Vertices" and values and isinstance(values[0], tuple):
                if isinstance(node, tuple) and node[0] == "shape":
                    facts.shape_geoms[node[1]]["points"] = len(values[0]) // 3
                else:
                    facts.meshes.append(values[0])
                    if isinstance(node, int):
                        facts.geometries[node] = values[0]
```

**(c)** In `walk`, the `Geometry` child branch becomes (class `"Shape"` is special; anything else keeps today's exact behavior):

```python
            elif name == "Geometry":
                uid = values[0] if values and isinstance(values[0], int) else None
                strs = [v for v in values if isinstance(v, str)]
                if uid is not None and strs and strs[-1] == "Shape":
                    facts.shape_geoms[uid] = {"name": _clean(strs[0]),
                                              "points": 0, "indexes": ()}
                    child = ("shape", uid)
                else:
                    child = uid
```

the `Deformer` branch gains two classes after the `Cluster` arm:

```python
                elif uid is not None and klass == "BlendShape":
                    facts.blend_deformers[uid] = {"geometry": None,
                                                  "channels": []}
                    child = ("blend", uid)
                elif uid is not None and klass == "BlendShapeChannel":
                    facts.blend_channels[uid] = {
                        "name": _clean(strs[0]) if strs else "?",
                        "shape": None, "deformer": None}
                    child = ("channel", uid)
```

and the cluster `Indexes` arm gains a shape sibling (the `want_ints=(name == "Indexes")` decode already covers it — the #668 carry-note (f) coming due):

```python
            elif (name == "Indexes" and isinstance(node, tuple)
                    and node[0] == "shape" and values
                    and isinstance(values[0], tuple)):
                facts.shape_geoms[node[1]]["indexes"] = values[0]
```

**(d)** The connection loop gains three arms at the END of the existing elif chain:

```python
        elif child in facts.shape_geoms and parent in facts.blend_channels:
            facts.blend_channels[parent]["shape"] = child
        elif child in facts.blend_channels and parent in facts.blend_deformers:
            facts.blend_deformers[parent]["channels"].append(child)
            facts.blend_channels[child]["deformer"] = parent
        elif child in facts.blend_deformers and parent in facts.geometries:
            facts.blend_deformers[child]["geometry"] = parent
```

**(e)** New function after `skin_facts`:

```python
def shape_facts(facts):
    """What the file's blend-shape records hold. Reading, not policy (#645).

    Per channel: the alias name maya_create_blendshape authored and the
    linked Shape geometry's payload sizes. Maya has been observed writing
    the channel name either bare or deformer-qualified, so the name is
    cleaned to its last dot-segment (measured under mayapy,
    TestBlendshapeExportInMaya - the naming pin for this reader). Structural
    link failures are reasons, never guesses; POLICY (empty deltas,
    index/point mismatch, missing declared names) lives in
    export.shape_violations.
    """
    reasons = []
    shapes = []
    for uid, channel in facts.blend_channels.items():
        entry = {"name": channel["name"].split(".")[-1],
                 "points": 0, "indexes": 0}
        geom_uid = channel["shape"]
        if geom_uid is None or geom_uid not in facts.shape_geoms:
            reasons.append("channel %r links no shape geometry"
                           % entry["name"])
        else:
            geom = facts.shape_geoms[geom_uid]
            entry["points"] = geom["points"]
            entry["indexes"] = len(geom["indexes"])
        if channel["deformer"] is None:
            reasons.append("channel %r links no blendShape deformer"
                           % entry["name"])
        shapes.append(entry)
    for uid, deformer in facts.blend_deformers.items():
        if deformer["geometry"] is None:
            reasons.append(
                "blendShape deformer %d deforms no geometry this reader "
                "holds" % uid)
    return {
        "blend_deformers": len(facts.blend_deformers),
        "channels": len(facts.blend_channels),
        "shapes": sorted(shapes, key=lambda e: e["name"]),
        "unavailable_reason": "; ".join(reasons) or None,
    }
```

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_fbxbytes.py tests/test_export_fbx.py -q`. Expected: PASS — including every pre-existing test (the committed-artifact and skin tests prove meshes/bounds behavior is untouched).

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/fbxbytes.py tests/test_fbxbytes.py
git commit -m "feat(#691): fbxbytes reads Shape geometries and BlendShape channels - delta clouds never pollute mesh facts"
```

---

### Task 3: Shapes ride along in export, gated

**Files:**
- Modify: `maya_plugin/handlers/export.py`
- Test: `tests/test_export_fbx.py` (add a class)

**Interfaces:**
- Consumes: Task 2's `fbxbytes.shape_facts`.
- Produces: `export.FBX_SHAPES_MEL`, `export.shape_violations(sfacts, declared) -> List[str]`, `export._scene_shape_aliases(cmds, nodes) -> List[str]`; `export_fbx`'s result gains `"shapes"` (the `shape_facts` dict, or `None` when the scene declares no targets and the file carries none). Task 5's `ShapeFacts` schema mirrors the dict exactly.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_export_fbx.py`:

```python
class TestShapeViolations:
    """#691: the shapes-ride-along contract, judged from the BYTES against
    what the SCENE declared."""

    def _clean(self, names=("brow_raise",)):
        return {"blend_deformers": 1, "channels": len(names),
                "shapes": [{"name": n, "points": 6, "indexes": 6}
                           for n in names],
                "unavailable_reason": None}

    def test_a_matching_file_passes(self):
        assert export.shape_violations(self._clean(), ["brow_raise"]) == []

    def test_nothing_declared_nothing_carried_passes(self):
        empty = {"blend_deformers": 0, "channels": 0, "shapes": [],
                 "unavailable_reason": None}
        assert export.shape_violations(empty, []) == []

    def test_a_declared_target_missing_from_the_file_fails(self):
        out = export.shape_violations(self._clean(), ["brow_raise",
                                                      "bulge_up"])
        assert any("bulge_up" in v and "absent" in v for v in out)

    def test_an_empty_delta_payload_fails(self):
        sfacts = self._clean()
        sfacts["shapes"][0]["points"] = 0
        out = export.shape_violations(sfacts, ["brow_raise"])
        assert any("no delta vertices" in v for v in out)

    def test_an_index_point_mismatch_fails(self):
        sfacts = self._clean()
        sfacts["shapes"][0]["indexes"] = 4
        out = export.shape_violations(sfacts, ["brow_raise"])
        assert any("6" in v and "4" in v for v in out)

    def test_unreadable_records_fail(self):
        sfacts = self._clean()
        sfacts["unavailable_reason"] = "channel 'x' links no shape geometry"
        out = export.shape_violations(sfacts, ["brow_raise"])
        assert any("unreadable" in v for v in out)

    def test_the_preamble_now_pins_shapes_on(self):
        assert export.FBX_SHAPES_MEL == ("FBXExportShapes -v true",)
        # ...and the delivery generators' composed preamble is untouched:
        # FBX_PREAMBLE_MEL is pinned byte-for-byte elsewhere in this file.
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_export_fbx.py -q`. Expected: FAIL (`shape_violations` missing). (Adjust the import line at the top of the test file if it imports names individually rather than the module.)

- [ ] **Step 3: Implement.** In `export.py`:

**(a)** After `FBX_SKINS_MEL`, add:

```python
# Shape export pinned ON, always, with no caller-facing knob (#691 design
# decision): morph targets simply ride along whenever a blendShape exists. A
# scene without one writes no Shape records either way (pinned under mayapy),
# so the only scenes the pin affects are the ones whose authors want their
# shapes. Both states are never composed because there is no false state -
# the determinism argument collapses to one line.
FBX_SHAPES_MEL: Tuple[str, ...] = ("FBXExportShapes -v true",)
```

**(b)** In `export_fbx`, the preamble loop becomes:

```python
    for statement in (FBX_PREAMBLE_MEL + FBX_SCENE_CONTENT_MEL
                      + FBX_SHAPES_MEL + FBX_SKINS_MEL[include_skins]):
        mel.eval(statement)
```

**(c)** New helpers after `skin_violations`:

```python
def _scene_shape_aliases(cmds, nodes) -> List[str]:
    """Weight aliases of every blendShape reachable from the exported
    meshes - what the FILE must now carry. A selected export walks its own
    `nodes` (DAG-expanded, so a group export finds its children); a
    whole-scene export walks every non-intermediate mesh shape."""
    if nodes:
        shapes = cmds.ls(nodes, dagObjects=True, type="mesh",
                         long=True, noIntermediate=True) or []
    else:
        shapes = cmds.ls(type="mesh", long=True, noIntermediate=True) or []
    aliases: List[str] = []
    for shape in shapes:
        for bs in cmds.ls(cmds.listHistory(shape, pruneDagObjects=True)
                          or [], type="blendShape") or []:
            for alias in cmds.listAttr(bs + ".w", multi=True) or []:
                if alias not in aliases:
                    aliases.append(alias)
    return aliases


def shape_violations(sfacts, declared: List[str]) -> List[str]:
    """Ways the file's Shape records break the shapes-ride-along contract.

    `declared` is what the scene authored (the weight aliases); the file
    must carry each as a channel with a non-empty, self-consistent delta
    payload. Extra channels the scene did not declare are NOT a violation -
    a hand-built blendShape made outside this tool still deserves to
    export."""
    out: List[str] = []
    names = [s["name"] for s in sfacts["shapes"]]
    missing = [a for a in declared if a not in names]
    if missing:
        out.append(
            "the scene's blendShape target(s) %s are absent from the file "
            "(it carries: %s)"
            % (", ".join(missing), ", ".join(names) or "none"))
    for s in sfacts["shapes"]:
        if s["points"] == 0:
            out.append("shape %r carries no delta vertices" % s["name"])
        elif s["indexes"] != s["points"]:
            out.append("shape %r holds %d indexes but %d delta points"
                       % (s["name"], s["indexes"], s["points"]))
    if sfacts["unavailable_reason"]:
        out.append("shape records unreadable: %s"
                   % sfacts["unavailable_reason"])
    return out
```

**(d)** Wire into `export_fbx`. Before the `cmds.loadPlugin` line, collect the declaration (a scene query, so it must precede nothing in particular, but grouping it with the other scene reads keeps it obvious):

```python
    declared_shapes = _scene_shape_aliases(cmds, nodes)
```

After the skin block (`violations += skin_bad`), add:

```python
    shapes_block = fbxbytes.shape_facts(facts)
    shape_bad = shape_violations(shapes_block, declared_shapes)
    violations += shape_bad
```

Extend the hint the same way `skin_hint` works, directly after it:

```python
    shape_hint = (
        " For shape violations: the exported selection must include the "
        "shaped mesh itself - shapes travel with their mesh, and a "
        "selection that lists only other nodes leaves them behind."
        if shape_bad else "")
```

and append `+ shape_hint` wherever `+ skin_hint` appears (both raise sites). In the returned dict, after `"skin": skin_block,` add:

```python
        "shapes": (shapes_block
                   if declared_shapes or shapes_block["channels"] else None),
```

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_export_fbx.py tests/test_fbxbytes.py -q`. Expected: PASS including every pre-existing export test (shape-less scenes: `declared` empty, `shapes` block `None`, no violation possible).

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/export.py tests/test_export_fbx.py
git commit -m "feat(#691): shapes ride along in every export - FBXExportShapes pinned, byte gate asserts declared targets"
```

---

### Task 4: The real-Maya leg (mayapy) — behavior and the naming measurement

**Files:**
- Test: `tests/test_handlers_mayapy.py` (add two classes at the end)

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: the MEASURED pin for FBX channel naming that `shape_facts`'s cleaning and the gate's assertions rest on. If Maya writes channel names in a third form neither `alias` nor `prefix.alias`, THIS is where it surfaces — fix `shape_facts`'s cleaning there and then, recording the measured string in the test.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_handlers_mayapy.py`:

```python
class TestBlendshapeInMaya:
    def _base_and_target(self, cmds, bump=0.3, axis=(0.0, 1.0, 0.0)):
        base = cmds.polyCube(name="bs_base", width=1, height=1, depth=1)[0]
        target = cmds.duplicate(base, name="bs_target")[0]
        cmds.move(bump * axis[0], bump * axis[1], bump * axis[2],
                  target + ".vtx[0]", relative=True)
        base_long = cmds.ls(base, long=True)[0]
        target_long = cmds.ls(target, long=True)[0]
        return base_long, target_long

    def test_create_measures_the_real_delta_and_consumes(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import blendshape

        base, target = self._base_and_target(cmds, bump=0.3)
        out = blendshape.create_blendshape({
            "mesh": base,
            "targets": [{"name": "puff", "target_mesh": target}]})
        assert out["targets"][0]["max_delta"] == pytest.approx(0.3, abs=1e-6)
        assert out["targets"][0]["vertex_count"] == 8
        assert not cmds.objExists(target)          # consumed
        # deltas survive the consumption: weight 1 still moves the vertex
        weighted = blendshape.set_blendshape_weights(
            {"mesh": base, "weights": {"puff": 1.0}})
        assert weighted["max_displacement"] == pytest.approx(0.3, abs=1e-6)
        assert weighted["weights"] == {"puff": 1.0}

    def test_half_weight_is_half_the_delta(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import blendshape

        base, target = self._base_and_target(cmds, bump=0.4)
        blendshape.create_blendshape({
            "mesh": base,
            "targets": [{"name": "puff", "target_mesh": target}]})
        out = blendshape.set_blendshape_weights(
            {"mesh": base, "weights": {"puff": 0.5}})
        assert out["max_displacement"] == pytest.approx(0.2, abs=1e-6)

    def test_a_translated_duplicate_contributes_no_false_delta(self):
        # Deltas are object-space in the node: a copy moved aside for
        # sculpting clarity is byte-identical as a target (design decision:
        # measured here, relied on by the gate's authoring flow).
        import maya.cmds as cmds

        from maya_plugin.handlers import blendshape

        base, target = self._base_and_target(cmds, bump=0.3)
        cmds.setAttr(target + ".translateX", 5.0)
        out = blendshape.create_blendshape({
            "mesh": base,
            "targets": [{"name": "puff", "target_mesh": target}]})
        assert out["targets"][0]["max_delta"] == pytest.approx(0.3, abs=1e-6)

    def test_topology_mismatch_refused(self):
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import blendshape

        base = cmds.ls(cmds.polyCube(name="bs_base8")[0], long=True)[0]
        ball = cmds.ls(cmds.polySphere(name="bs_ball")[0], long=True)[0]
        with pytest.raises(HandlerError, match="topology does not match"):
            blendshape.create_blendshape({
                "mesh": base,
                "targets": [{"name": "bad", "target_mesh": ball}]})

    def test_front_of_chain_under_a_skin(self):
        """The phase's load-bearing ordering claim, measured two ways.

        The cube is bound, the root rotated 90 about Z, THEN the shape is
        wired (the risky order - frontOfChain has to reach past the
        existing skinCluster). The target's delta is +X in object space;
        front-of-chain means the skin ROTATES it, so at the posed joint the
        vertex must move +Y in world. Wrong order would move it +X.
        """
        import maya.cmds as cmds

        from maya_plugin.handlers import blendshape, rigging, sculpt

        base, target = self._base_and_target(cmds, bump=0.3,
                                             axis=(1.0, 0.0, 0.0))
        skeleton = rigging.create_skeleton({"joints": [
            {"name": "bs_j1", "position": [0.0, 0.0, 0.0]},
            {"name": "bs_j2", "position": [1.0, 0.0, 0.0]}]})
        rigging.bind_skin({"mesh": base, "root": skeleton["root"]})
        rigging.pose_skeleton({"root": skeleton["root"],
                               "rotations": {"bs_j1": [0, 0, 90]}})

        out = blendshape.create_blendshape({
            "mesh": base,
            "targets": [{"name": "fix", "target_mesh": target}]})
        assert out["targets"][0]["max_delta"] == pytest.approx(0.3, abs=1e-4)

        # structural: the blendShape sits UPSTREAM of the skinCluster
        shape = cmds.listRelatives(base, shapes=True, fullPath=True,
                                   noIntermediate=True)[0]
        history = cmds.listHistory(shape, pruneDagObjects=True)
        sc = cmds.ls(history, type="skinCluster")[0]
        bs = cmds.ls(history, type="blendShape")[0]
        assert history.index(sc) < history.index(bs)

        # behavioral: the object-space +X delta lands as world +Y
        before = sculpt.vertex_positions(cmds, base)
        blendshape.set_blendshape_weights({"mesh": base,
                                           "weights": {"fix": 1.0}})
        after = sculpt.vertex_positions(cmds, base)
        moved = max(range(len(before) // 3),
                    key=lambda i: sum((after[3 * i + k] - before[3 * i + k]) ** 2
                                      for k in range(3)))
        delta = [after[3 * moved + k] - before[3 * moved + k]
                 for k in range(3)]
        assert delta[1] == pytest.approx(0.3, abs=1e-4)   # +Y, rotated
        assert abs(delta[0]) < 1e-4                        # not +X

    def test_additive_create_and_alias_collision(self):
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import blendshape

        base, t1 = self._base_and_target(cmds, bump=0.2)
        first = blendshape.create_blendshape({
            "mesh": base, "targets": [{"name": "a", "target_mesh": t1}]})
        t2 = cmds.ls(cmds.duplicate(base, name="bs_t2")[0], long=True)[0]
        cmds.move(0, 0, 0.1, t2 + ".vtx[1]", relative=True)
        second = blendshape.create_blendshape({
            "mesh": base, "targets": [{"name": "b", "target_mesh": t2}]})
        assert second["blend_shape"] == first["blend_shape"]
        weighted = blendshape.set_blendshape_weights(
            {"mesh": base, "weights": {"a": 1.0, "b": 1.0}})
        assert set(weighted["weights"]) == {"a", "b"}
        t3 = cmds.ls(cmds.duplicate(base, name="bs_t3")[0], long=True)[0]
        with pytest.raises(HandlerError, match="already exists"):
            blendshape.create_blendshape({
                "mesh": base, "targets": [{"name": "a", "target_mesh": t3}]})


class TestBlendshapeExportInMaya:
    def test_shapes_ride_along_and_the_bytes_name_them(self, tmp_path):
        """THE NAMING MEASUREMENT (#691 plan constraint): whatever Maya
        writes as the channel name, shape_facts must clean it to the
        authored alias. If this assertion fails, the fix belongs in
        fbxbytes.shape_facts's name cleaning - record the measured raw
        string in a comment here when adjusting."""
        import maya.cmds as cmds

        from maya_plugin.handlers import blendshape, export, fbxbytes

        base = cmds.ls(cmds.polyCube(name="bs_exp")[0], long=True)[0]
        target = cmds.ls(cmds.duplicate(base, name="bs_exp_t")[0],
                         long=True)[0]
        cmds.move(0, 0.3, 0, target + ".vtx[0]", relative=True)
        blendshape.create_blendshape({
            "mesh": base,
            "targets": [{"name": "puff", "target_mesh": target}]})

        path = str(tmp_path / "shaped.fbx").replace("\\", "/")
        result = export.export_fbx({"path": path, "metres_per_unit": 1.0})
        shapes = result["shapes"]
        assert shapes is not None and shapes["channels"] == 1
        assert shapes["shapes"][0]["name"] == "puff"
        assert shapes["shapes"][0]["points"] > 0
        assert shapes["shapes"][0]["indexes"] == shapes["shapes"][0]["points"]
        # Shape geometries must not inflate mesh facts
        assert result["mesh_count"] == 1
        # an independent read of the bytes agrees with the tool
        assert fbxbytes.shape_facts(fbxbytes.read_fbx(path)) == shapes

    def test_a_shapeless_scene_reports_no_shapes_block(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import export

        cmds.polyCube(name="bs_plain")
        path = str(tmp_path / "plain.fbx").replace("\\", "/")
        result = export.export_fbx({"path": path, "metres_per_unit": 1.0})
        assert result["shapes"] is None
        assert result["mesh_count"] == 1

    def test_skins_and_shapes_coexist_in_one_file(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import blendshape, export, rigging

        base = cmds.ls(cmds.polyCube(name="bs_both")[0], long=True)[0]
        target = cmds.ls(cmds.duplicate(base, name="bs_both_t")[0],
                         long=True)[0]
        cmds.move(0, 0.2, 0, target + ".vtx[0]", relative=True)
        skeleton = rigging.create_skeleton({"joints": [
            {"name": "bb_j1", "position": [0.0, 0.0, 0.0]},
            {"name": "bb_j2", "position": [1.0, 0.0, 0.0]}]})
        rigging.bind_skin({"mesh": base, "root": skeleton["root"]})
        blendshape.create_blendshape({
            "mesh": base,
            "targets": [{"name": "fix", "target_mesh": target}]})
        path = str(tmp_path / "both.fbx").replace("\\", "/")
        result = export.export_fbx({"path": path, "metres_per_unit": 1.0,
                                    "include_skins": True})
        assert result["skin"]["deformers"] == 1
        assert result["skin"]["clusters"] == 2
        assert result["shapes"]["channels"] == 1
        assert result["shapes"]["shapes"][0]["name"] == "fix"
```

- [ ] **Step 2: Run to verify** — `E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q`. Expected: the new tests PASS along with all 132+1 existing. **If the naming test fails on the channel name**: read the raw `facts.blend_channels` values it got, adjust `shape_facts`'s cleaning to cover the measured form, record the measured string in the test comment, re-run. That is the measurement this plan budgets for — everything else failing means a real defect.

- [ ] **Step 3: Commit**

```bash
git add tests/test_handlers_mayapy.py maya_plugin/handlers/fbxbytes.py
git commit -m "test(#691): blendshape measured against a real Maya - front-of-chain proof, consumed targets, Shape-record naming pinned"
```

(Include `fbxbytes.py` only if the naming measurement forced a cleaning fix.)

---

### Task 5: Schemas and the two MCP tools (53)

**Files:**
- Modify: `src/maya_mcp/schemas.py` (new models near the rigging block; `ShapeRecord`/`ShapeFacts` next to `SkinFacts`; `shapes` field on `ExportFbxResult`)
- Modify: `src/maya_mcp/server.py` (two tools after `maya_author_physics`)
- Test: `tests/test_server_tools.py`

**Interfaces:**
- Consumes: Task 1's result dicts, Task 3's `shapes` block.
- Produces: `maya_create_blendshape(mesh, targets: List[BlendshapeTargetSpec]) -> CreateBlendshapeResult`, `maya_set_blendshape_weights(mesh, weights: Dict[str, float]) -> SetBlendshapeWeightsResult`.

- [ ] **Step 1: Write the failing tests** — in `tests/test_server_tools.py`, add `"maya_create_blendshape"` and `"maya_set_blendshape_weights"` to the `test_session_tools_registered` set, and append:

```python
class TestBlendshapeTools:
    def test_create_marshals_targets_and_returns_measured(self):
        conn = FakeConn(responses={"create_blendshape": {
            "mesh": "|humanoid", "blend_shape": "humanoid_shapes",
            "targets": [{"name": "brow_raise", "max_delta": 0.05,
                         "vertex_count": 33414}],
            "warnings": []}})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_create_blendshape", {
            "mesh": "|humanoid",
            "targets": [{"name": "brow_raise",
                         "target_mesh": "|humanoid_brow"}]}))
        params = conn.calls[0]["params"]
        assert conn.calls[0]["cmd"] == "create_blendshape"
        assert params["targets"] == [{"name": "brow_raise",
                                      "target_mesh": "|humanoid_brow"}]
        payload = result[1]
        assert payload["targets"][0]["max_delta"] == 0.05

    def test_set_weights_marshals_and_returns_measured(self):
        conn = FakeConn(responses={"set_blendshape_weights": {
            "mesh": "|humanoid", "blend_shape": "humanoid_shapes",
            "weights": {"brow_raise": 0.5},
            "max_displacement": 0.024,
            "per_target": [{"name": "brow_raise", "weight": 0.5,
                            "max_displacement": 0.024}],
            "warnings": []}})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_set_blendshape_weights", {
            "mesh": "|humanoid", "weights": {"brow_raise": 0.5}}))
        assert conn.calls[0]["params"] == {"mesh": "|humanoid",
                                           "weights": {"brow_raise": 0.5}}
        assert result[1]["max_displacement"] == 0.024

    def test_annotations(self):
        mcp = server_mod.create_server(FakeConn())
        by_name = {t.name: t for t in run(mcp.list_tools())}
        create = by_name["maya_create_blendshape"].annotations
        assert (create.read_only_hint, create.destructive_hint,
                create.idempotent_hint) == (False, True, False)
        weigh = by_name["maya_set_blendshape_weights"].annotations
        assert (weigh.read_only_hint, weigh.destructive_hint,
                weigh.idempotent_hint) == (False, True, True)
```

(Match the payload-unpacking idiom of the neighbouring tests in that file — if they read `result[1]` as a dict, keep it; if they use `.structured_content`, mirror that. The existing `maya_author_physics` tests at line ~1769 are the closest model.)

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_server_tools.py -q`. Expected: FAIL (registration set mismatch + unknown tools).

- [ ] **Step 3: Implement schemas** — in `src/maya_mcp/schemas.py`, next to the rigging results:

```python
class BlendshapeTargetSpec(BaseModel):
    """One morph target to wire: an ordinary same-topology mesh."""

    name: str = Field(description=(
        "Weight name - becomes the attribute alias, the "
        "set_blendshape_weights key, and the exported Shape record name. "
        "Plain identifier."))
    target_mesh: str = Field(description=(
        "Same-topology copy of the base (maya_duplicate, then sculpt). "
        "CONSUMED: deleted once its deltas are wired."))


class TargetDelta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    max_delta: float = Field(description=(
        "MEASURED: the furthest any base vertex moves with this weight "
        "driven to 1 through the real deformer - never read off the "
        "target's own vertices. Near zero warns: the target is a duplicate "
        "that was never sculpted."))
    vertex_count: int


class CreateBlendshapeResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mesh: str
    blend_shape: str = Field(description=(
        "The deformer node. One per mesh: creating again ADDS targets to "
        "it rather than stacking a second."))
    targets: List[TargetDelta]
    warnings: List[str] = Field(default_factory=list)


class TargetDisplacement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    weight: float = Field(description="Achieved weight, re-read after the write.")
    max_displacement: float = Field(description=(
        "What this weight landing moved, measured in call order against "
        "the state the previous entries left."))


class SetBlendshapeWeightsResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mesh: str
    blend_shape: str
    weights: Dict[str, float] = Field(description=(
        "EVERY target's weight re-read from the node - including targets "
        "this call did not name."))
    max_displacement: float = Field(description=(
        "Overall before/after vertex move for the whole call - can be "
        "smaller than a per-target step when shapes oppose."))
    per_target: List[TargetDisplacement]
    warnings: List[str] = Field(default_factory=list)
```

Next to `SkinFacts`:

```python
class ShapeRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(description=(
        "The weight alias maya_create_blendshape authored, cleaned from "
        "the file's channel name."))
    points: int = Field(description="Delta vertices the Shape record carries.")
    indexes: int = Field(description="Sparse vertex indexes alongside them.")


class ShapeFacts(BaseModel):
    """Blend-shape records read back OUT OF THE FILE, never from the scene."""

    model_config = ConfigDict(extra="ignore")

    blend_deformers: int
    channels: int
    shapes: List[ShapeRecord]
    unavailable_reason: Optional[str] = None
```

and on `ExportFbxResult`, after `skin`:

```python
    shapes: Optional[ShapeFacts] = Field(
        default=None,
        description=(
            "Blend-shape facts when the scene declares targets or the file "
            "carries channels; null for a shape-less export. Shapes ride "
            "along automatically - there is no parameter to enable them."))
```

- [ ] **Step 4: Implement the tools** — in `src/maya_mcp/server.py`, import the new schema names alongside the existing ones, and after `maya_author_physics`:

```python
    @mcp.tool(
        title="Wire blend-shape targets",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
    )
    def maya_create_blendshape(
        mesh: Annotated[str, Field(description="Base mesh (long name).")],
        targets: Annotated[List[BlendshapeTargetSpec], Field(description=(
            "Targets to wire. Each is an ordinary mesh authored with the "
            "existing modeling/sculpt tools - duplicate the base, sculpt "
            "the change, pass it here. Same topology required."
        ))],
    ) -> CreateBlendshapeResult:
        """Wire sculpted meshes as morph targets and MEASURE each delta.

        The deformer goes FRONT-OF-CHAIN - before any skinCluster - so a
        shape models the neutral surface and the skin carries it to the
        pose; that ordering is what makes an elbow corrective correct at a
        bent elbow. Target meshes are CONSUMED (the deltas live in the
        deformer; a stale copy invites sculpting a mesh that feeds
        nothing). Creating again on the same mesh ADDS targets to the one
        node. max_delta is measured through the real deformer at weight 1,
        and a near-zero delta warns - a duplicate that was never sculpted
        looks exactly like success otherwise."""
        return CreateBlendshapeResult.model_validate(
            maya.request(
                "create_blendshape",
                {"mesh": mesh,
                 "targets": [t.model_dump() for t in targets]},
                timeout_s=BOOL_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Set blend-shape weights",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=True
        ),
    )
    def maya_set_blendshape_weights(
        mesh: Annotated[str, Field(description="The shaped mesh (long name).")],
        weights: Annotated[Dict[str, float], Field(description=(
            "Map of target name to weight 0..1 - absolute values, so "
            "re-applying is idempotent. 0 for every target IS the reset; "
            "the skeleton pose currency is untouched."
        ))],
    ) -> SetBlendshapeWeightsResult:
        """Drive morph-target weights and MEASURE what moved.

        Weights land sequentially in call order; per_target reports what
        each landing moved, max_displacement the honest before/after of
        the whole call, and the returned weights map is EVERY target
        re-read from the node. Unknown names are refused with the list of
        targets that exist."""
        return SetBlendshapeWeightsResult.model_validate(
            maya.request(
                "set_blendshape_weights",
                {"mesh": mesh, "weights": weights},
                timeout_s=BOOL_TIMEOUT_S,
            )
        )
```

- [ ] **Step 5: Run to verify pass** — `uv run pytest tests/test_server_tools.py -q`, then the whole suite `uv run pytest -q`. Expected: PASS, count grown, 53 tools.

- [ ] **Step 6: Commit**

```bash
git add src/maya_mcp/schemas.py src/maya_mcp/server.py tests/test_server_tools.py
git commit -m "feat(#691): maya_create_blendshape / maya_set_blendshape_weights MCP tools - 53 tools"
```

---

### Task 6: Protocol documentation

**Files:**
- Modify: `docs/protocol.md` (after the `author_physics` section)

- [ ] **Step 1: Write the entry** — matching the file's table+prose format:

```markdown
| `create_blendshape` | `{ mesh, targets: [{name, target_mesh}] }` | `{ mesh, blend_shape, targets: [{name, max_delta, vertex_count}], warnings }` |
| `set_blendshape_weights` | `{ mesh, weights: {name: 0..1} }` | `{ mesh, blend_shape, weights, max_displacement, per_target, warnings }` |

`create_blendshape` wires ordinary sculpted meshes as morph targets. The
deformer evaluates **front-of-chain** (before any skinCluster): a shape
models the neutral surface and the skin carries the shaped surface to the
pose, which is what makes a muscle corrective correct at a bent joint.
Targets must match the base's topology (refused with both vertex counts -
no wrap fallback) and are **consumed** once wired: the deltas live in the
deformer, and a stale editable copy invites sculpting a mesh that feeds
nothing. Each target's `name` becomes the weight alias, the
`set_blendshape_weights` key, and the exported Shape record's name.
`max_delta` is measured through the real deformer at weight 1; a target
measuring (near-)identical to the base warns. Creating again on the same
mesh ADDS targets to its one blendShape node - stacking a second deformer
is refused by construction.

`set_blendshape_weights` drives the named weights (0..1, absolute), lands
them sequentially in call order, and measures per step; the returned
`weights` map is every target re-read from the node. All-zero weights IS
the reset - the phase-1 pose-map currency is untouched.

Export: shapes ride along automatically (`FBXExportShapes` pinned on -
there is no parameter). The byte gate refuses an export whose scene
declares a target the file does not carry, and the result's `shapes` block
reports each channel's name and delta payload as read from the bytes.
```

- [ ] **Step 2: Commit**

```bash
git add docs/protocol.md
git commit -m "docs(#691): protocol entry for create_blendshape / set_blendshape_weights"
```

---

### Task 7: The live gate — humanoid expression + corrective, judged and measured

**Files:**
- Create: `evals/blendshape_live.py`
- Create (generated by the run, then committed): `evals/blendshape_live/baseline.json`, renders, `humanoid_shaped.fbx`

**Interfaces:**
- Consumes: everything above, deployed; `evals/humanoid_live.py`'s `PARTS`, `JOINTS`, `MESH` constants (importable — its `main()` is `__main__`-guarded).

**Deploy first (the #604 trap):** the disposable Maya must run THIS branch.

- [ ] **Step 1: Deploy and restart the disposable Maya**

```bash
uv run python maya_plugin/install.py --yes
```

Then start (or restart) the agent-launched Maya with a NEUTRAL cwd (never the repo — Maya puts its cwd on `sys.path` and would import the repo copy), `MAYA_MCP_PORT=9878`. Verify with a ping through the TCP client: `restart_required` must be false and the stamp must match `git rev-parse --short=12 HEAD`. Match the listener's pid to the process you launched (#648) — `Stop-Process` lies, use `taskkill /F /T` if a stale one holds the port.

- [ ] **Step 2: Write the gate** — create `evals/blendshape_live.py`:

```python
"""Phase-5 gate for #691: blend shapes on the #668 humanoid.

The user chose BOTH target kinds (2026-08-20):

    1  brow_raise    - facial expression, judged front-on at 0 / 0.5 / 1
    2  L_elbow_bulge - muscle corrective ON THE FOREARM, judged AT a
       90-degree elbow, with the measured front-of-chain proof: the
       displaced-vertex centroid rides the POSED forearm, not the bind
       location. (A delta centred on the elbow pivot could not tell the
       deformation orders apart, which is why the bulge sits at x=0.55.)

Measured checks (this script) + judged renders (the acceptance):
    build humanoid + skeleton + bind (no craft pass: this gate judges
    SHAPES; #668's gate owns weight craft) -> author two targets with
    duplicate+sculpt -> create_blendshape (consumed, deltas measured) ->
    monotonic displacement sweep 0/0.5/1 -> corrective at the posed elbow
    -> reset both currencies -> export include_skins + shapes, byte-gated.

DESTRUCTIVE: calls new_scene. Port 9878, the agent-launched Maya, per the
two-Maya policy - never point this at the user's 9877.

Run:  uv run python evals/blendshape_live.py
Exit: 0 pass, 1 fail, 2 no connection.
"""

from __future__ import annotations

import base64
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from humanoid_live import JOINTS, MESH, PARTS  # noqa: E402
from live_call import call, structured_result  # noqa: E402
from maya_plugin.handlers import fbxbytes  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
OUT_DIR = os.path.join(_HERE, "blendshape_live")
JOINT_COUNT = 20

# Sculpt literals, derived from the humanoid's authored geometry (the PARTS
# table): the head sphere is centred (0, 1.74, 0) with scale (.20, .26,
# .20), so its brow front sits near (0, 1.80, 0.15); the L arm cylinder
# runs x 0.14..0.70 at y 1.50, so the forearm midpoint is (0.55, 1.50, 0).
BROW_CENTER = [0.0, 1.80, 0.15]
BROW_RADIUS = 0.14
BROW_DELTA = [0.0, 0.04, 0.03]
BULGE_CENTER = [0.55, 1.50, 0.0]
BULGE_RADIUS = 0.12
BULGE_AMOUNT = 0.04

CHECKS = []


def check(label, passed, detail=""):
    CHECKS.append((bool(passed), label))
    print("%s %s%s" % ("PASS" if passed else "FAIL", label,
                       ("  [%s]" % detail) if detail else ""))
    return bool(passed)


def send(command, params, timeout_s=300.0):
    try:
        return call(command, params, timeout_s=timeout_s, port=PORT)
    except (ConnectionRefusedError, OSError) as exc:
        print("could not reach a Maya plugin on %s: %s" % (PORT, exc))
        sys.exit(2)


def ok(command, params, timeout_s=300.0):
    response = send(command, params, timeout_s)
    if response.get("status") != "ok":
        print("FAIL: %s: %s" % (command,
                                json.dumps(response.get("error"))[:600]))
        sys.exit(1)
    return response.get("result") or {}


def py(code, what, timeout_s=300.0):
    return structured_result(ok("execute_python", {"code": code},
                                timeout_s), what)


def out(name):
    return os.path.join(OUT_DIR, name)


# Stores the current vertices as the NEUTRAL baseline on the first call;
# afterwards reports max displacement vs that baseline and the centroid of
# every vertex that moved more than a millimetre - the front-of-chain
# evidence.
VERT_PROBE = """
import maya.cmds as cmds
_flat = cmds.xform(%(mesh)r + '.vtx[*]', query=True, worldSpace=True,
                   translation=True)
if %(store)s:
    BS_NEUTRAL = list(_flat)
_worst = 0.0
_cx = _cy = _cz = 0.0
_n = 0
for _i in range(0, len(_flat), 3):
    _dx = _flat[_i] - BS_NEUTRAL[_i]
    _dy = _flat[_i + 1] - BS_NEUTRAL[_i + 1]
    _dz = _flat[_i + 2] - BS_NEUTRAL[_i + 2]
    _d = (_dx * _dx + _dy * _dy + _dz * _dz) ** 0.5
    if _d > _worst:
        _worst = _d
    if _d > 1e-3:
        _cx += _flat[_i]; _cy += _flat[_i + 1]; _cz += _flat[_i + 2]
        _n += 1
{'max_disp': round(_worst, 6),
 'moved': _n,
 'centroid': ([round(_cx / _n, 4), round(_cy / _n, 4),
               round(_cz / _n, 4)] if _n else None)}
"""


def probe(store, what):
    return py(VERT_PROBE % {"mesh": "|" + MESH, "store": repr(bool(store))},
              what)


def render(tag, angles=("front",)):
    params = {"angles": list(angles), "target": ["|" + MESH],
              "resolution": 640, "samples": 3, "renderer": "arnold"}
    response = send("render_scene", params, timeout_s=900.0)
    if response.get("status") != "ok":
        params["renderer"] = "hw2"
        response = send("render_scene", params, timeout_s=900.0)
    if response.get("status") != "ok":
        check("render %s" % tag, False,
              json.dumps(response.get("error"))[:200])
        return
    for image in response["result"]["images"]:
        path = out("humanoid_%s_%s.png" % (tag, image["angle"]))
        with open(path, "wb") as fh:
            fh.write(base64.b64decode(image["png_b64"]))
    check("render %s" % tag, True,
          "renderer=%s" % response["result"].get("renderer"))


def main():
    if PORT == 9877:
        print("refusing to run on 9877: this eval discards the open scene "
              "(two-Maya policy). Launch a disposable Maya on 9878.")
        return 2

    os.makedirs(OUT_DIR, exist_ok=True)
    identity = py("import os\n{'pid': os.getpid()}", "identity")
    print("Maya on %d: pid %s, writing to %s\n"
          % (PORT, identity["pid"], OUT_DIR))

    # ---- 1. the humanoid, bound (no craft pass: #668's gate owns craft)
    ok("new_scene", {"confirm": True})
    for kind, name, divisions, scale, translate, rotate in PARTS:
        params = {"kind": kind, "name": name, "divisions": divisions,
                  "scale": scale, "translate": translate}
        if rotate:
            params["rotate"] = rotate
        ok("create_primitive", params)
    ok("combine", {"names": [p[1] for p in PARTS], "name": MESH})
    py("import maya.cmds as cmds\n"
       "cmds.makeIdentity(%r, apply=True, translate=False, rotate=True, "
       "scale=True, normal=0, preserveNormals=True)\nTrue"
       % ("|" + MESH), "freeze the combined mesh")
    skeleton = ok("create_skeleton", {"joints": JOINTS})
    root = skeleton["root"]
    bind = ok("bind_skin", {"mesh": "|" + MESH, "root": root},
              timeout_s=600.0)
    check("the bind leaves NO vertex unowned",
          bind["unweighted_vertices"] == 0,
          "unweighted=%d" % bind["unweighted_vertices"])

    # ---- 2. author the two targets: duplicate + sculpt, the ordinary loop
    ok("duplicate", {"name": "|" + MESH, "new_name": "humanoid_brow"})
    ok("sculpt_ops", {"mesh": "|humanoid_brow", "ops": [
        {"op": "soft_move", "center": BROW_CENTER, "radius": BROW_RADIUS,
         "delta": BROW_DELTA, "falloff": "smooth"}]})
    ok("duplicate", {"name": "|" + MESH, "new_name": "humanoid_elbow"})
    ok("sculpt_ops", {"mesh": "|humanoid_elbow", "ops": [
        {"op": "inflate_region", "center": BULGE_CENTER,
         "radius": BULGE_RADIUS, "amount": BULGE_AMOUNT,
         "falloff": "smooth"}]})

    wired = ok("create_blendshape", {"mesh": "|" + MESH, "targets": [
        {"name": "brow_raise", "target_mesh": "|humanoid_brow"},
        {"name": "L_elbow_bulge", "target_mesh": "|humanoid_elbow"}]})
    deltas = {t["name"]: t["max_delta"] for t in wired["targets"]}
    check("both targets wired with real measured deltas",
          deltas.get("brow_raise", 0) > 0.01
          and deltas.get("L_elbow_bulge", 0) > 0.01,
          json.dumps(deltas))
    consumed = py(
        "import maya.cmds as cmds\n"
        "{'brow': cmds.objExists('humanoid_brow'),"
        " 'elbow': cmds.objExists('humanoid_elbow')}", "consumption")
    check("the target meshes were consumed",
          not consumed["brow"] and not consumed["elbow"],
          json.dumps(consumed))

    # ---- 3. expression sweep 0 / 0.5 / 1: monotonic, rendered, judged
    ok("setup_lighting", {"preset": "three_point"})
    probe(store=True, what="neutral baseline")
    render("brow_0")
    sweep = {}
    for weight in (0.5, 1.0):
        ok("set_blendshape_weights",
           {"mesh": "|" + MESH, "weights": {"brow_raise": weight}})
        measured = probe(store=False, what="brow at %.1f" % weight)
        sweep[weight] = measured["max_disp"]
        render("brow_%s" % str(weight).replace(".", "_"))
    check("displacement is strictly monotonic across 0 / 0.5 / 1",
          0.0 < sweep[0.5] < sweep[1.0],
          "0.5 -> %.4f, 1.0 -> %.4f" % (sweep[0.5], sweep[1.0]))
    check("weight 1 reproduces the wiring-time delta",
          abs(sweep[1.0] - deltas["brow_raise"]) < 1e-3,
          "sweep=%.4f wired=%.4f" % (sweep[1.0], deltas["brow_raise"]))
    reset = ok("set_blendshape_weights",
               {"mesh": "|" + MESH, "weights": {"brow_raise": 0.0}})
    back = probe(store=False, what="after weight reset")
    check("all-zero weights IS the reset",
          back["max_disp"] < 1e-6, "residual=%.3g" % back["max_disp"])

    # ---- 4. the corrective AT a posed elbow: front-of-chain, seen and measured
    posed = ok("pose_skeleton", {"root": root,
                                 "rotations": {"L_elbow": [0, 0, 90]}})
    joints_now = {j["name"].split("|")[-1]: j["world_position"]
                  for j in posed["joints"]}
    forearm_mid = [(a + b) / 2.0 for a, b in
                   zip(joints_now["L_elbow"], joints_now["L_wrist"])]
    probe(store=True, what="posed-elbow baseline")
    render("elbow_posed_w0")
    ok("set_blendshape_weights",
       {"mesh": "|" + MESH, "weights": {"L_elbow_bulge": 1.0}})
    at_pose = probe(store=False, what="corrective at the posed elbow")
    render("elbow_posed_w1")
    check("the corrective moves the mesh at the pose",
          at_pose["max_disp"] > 0.01, "max_disp=%.4f" % at_pose["max_disp"])

    def dist(a, b):
        return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5

    bind_site = dist(at_pose["centroid"], BULGE_CENTER)
    posed_site = dist(at_pose["centroid"], forearm_mid)
    check("front-of-chain: the bulge rides the POSED forearm",
          at_pose["centroid"] is not None and posed_site < bind_site,
          "centroid=%s d(posed)=%.3f d(bind)=%.3f"
          % (at_pose["centroid"], posed_site, bind_site))

    # ---- 5. reset BOTH currencies, then export skins + shapes together
    ok("set_blendshape_weights",
       {"mesh": "|" + MESH, "weights": {"L_elbow_bulge": 0.0}})
    ok("reset_pose", {"root": root})

    fbx = out("humanoid_shaped.fbx")
    if os.path.exists(fbx):
        os.unlink(fbx)
    result = ok("export_fbx", {"path": fbx.replace("\\", "/"),
                               "metres_per_unit": 1.0,
                               "include_skins": True}, timeout_s=600.0)
    shapes = result["shapes"]
    print("  shapes: %s" % json.dumps(shapes))
    check("the file carries both channels by their authored names",
          shapes is not None
          and [s["name"] for s in shapes["shapes"]]
          == ["L_elbow_bulge", "brow_raise"],
          json.dumps(shapes))
    check("every shape carries a self-consistent, non-empty delta payload",
          all(s["points"] > 0 and s["indexes"] == s["points"]
              for s in shapes["shapes"]))
    check("skins survived alongside shapes",
          result["skin"]["deformers"] == 1
          and result["skin"]["clusters"] == JOINT_COUNT
          and result["skin"]["unweighted_file_vertices"] == 0,
          json.dumps(result["skin"]))
    facts = fbxbytes.read_fbx(fbx)
    check("an independent byte read agrees with the tool",
          fbxbytes.shape_facts(facts) == shapes)
    check("shape geometries do not inflate mesh facts",
          result["mesh_count"] == 1, "mesh_count=%d" % result["mesh_count"])
    limbs = [n for n in facts.nodes if n.kind == "LimbNode"]
    check("the bytes still carry %d LimbNode joints" % JOINT_COUNT,
          len(limbs) == JOINT_COUNT, "LimbNodes=%d" % len(limbs))
    check("the file declares metres",
          facts.unit_scale_factor == fbxbytes.DECLARES_METRES)

    with open(out("baseline.json"), "w") as fh:
        json.dump({
            "fbx": "humanoid_shaped.fbx",
            "bytes": result["bytes"],
            "targets": deltas,
            "sweep": {str(k): v for k, v in sweep.items()},
            "corrective_at_pose": {
                "max_disp": at_pose["max_disp"],
                "centroid": at_pose["centroid"],
                "forearm_mid": [round(v, 4) for v in forearm_mid]},
            "shapes": shapes,
            "skin": result["skin"],
        }, fh, indent=2, sort_keys=True)
    print("  baseline: %s" % out("baseline.json"))

    print("\n" + "=" * 72)
    print("JUDGE the renders in %s:" % OUT_DIR)
    print("  brow_0 / brow_0_5 / brow_1: the brow must visibly, smoothly")
    print("  rise - a dent, a spike, or no visible change at 1.0 is a FAIL")
    print("  even with every number green.")
    print("  elbow_posed_w0 vs elbow_posed_w1: the bulge must appear ON the")
    print("  BENT forearm, oriented with it - a bulge floating at the bind")
    print("  position is the deformation-order failure this gate exists")
    print("  to catch.")
    print("=" * 72 + "\n")

    failed = [label for passed, label in CHECKS if not passed]
    print("\n%d/%d passed" % (len(CHECKS) - len(failed), len(CHECKS)))
    for label in failed:
        print("  FAILED: %s" % label)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Run the gate** — `uv run python evals/blendshape_live.py` against the deployed disposable Maya. Every numbered check must PASS. Then JUDGE the renders (both the implementer and a second look — the p2/p3 precedent is implementer AND controller): the brow sweep must read as an expression, the posed-elbow pair must show the bulge on the bent forearm. If the sculpt literals produce an unreadable shape (too subtle, wrong spot), adjust `BROW_*`/`BULGE_*` from what the renders show and re-run — the constants are derived from the PARTS table, but pixels outrank derivations.

- [ ] **Step 4: Re-run both suites on the branch**

```bash
uv run pytest -q
E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q
```

Expected: all green, counts strictly above 1212/132.

- [ ] **Step 5: Commit the gate and its evidence**

```bash
git add evals/blendshape_live.py evals/blendshape_live/
git commit -m "feat(#691): blendshape live gate - expression sweep, corrective at a posed elbow, skins+shapes export byte-gated"
```

- [ ] **Step 6: Ticket checkpoint** — update #691 (one `update_issue`): measured gate numbers, suite counts, renders judged, any divergences; leave In Progress until merge, then Resolved with the final commit hash per the finishing flow.

---

## Self-review notes (already applied)

- Spec coverage: create (Task 1), set weights (Task 1), front-of-chain (Tasks 1+4+7), consumed targets (1+4+7), topology refusal (1+4), weights-0 reset (1+7), automatic export (3+4+7), Shape byte gate + carry-note (f) Indexes (2+3+4+7), both gate targets + monotonic sweep + posed-joint judgment (7).
- Type consistency: `blend_shape` (snake) is the result key everywhere; `targets[].{name,max_delta,vertex_count}`; `per_target[].{name,weight,max_displacement}`; `shapes` block `{blend_deformers, channels, shapes[], unavailable_reason}` — identical in handler, fbxbytes, export, schemas, gate.
- Known measurement points budgeted: FBX channel naming (Task 4), sculpt literals vs renders (Task 7). Everything else is pinned by existing measured behavior.
