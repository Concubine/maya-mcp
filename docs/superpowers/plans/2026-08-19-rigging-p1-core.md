# Rigging Phase 1 — skeleton, bind, pose (#602) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Four new commands — `create_skeleton`, `bind_skin`, `pose_skeleton`, `reset_pose` — plus `include_skins` on `maya_export_fbx`, gated by the serpent (12-joint bend, measured deformation, skinned FBX byte-verified).

**Architecture:** One new handler module (`rigging.py`) backed by a pure-math module (`rigmath.py`, headless-testable), wired through the existing dispatcher/MCP-server pattern. The FBX byte reader (`fbxbytes.py`) grows skin-record parsing so the export gate can verify SkinCluster records, per-vertex weight sums, and a BindPose from the bytes. Deformation is fully measurable in headless mayapy (`joint`/`skinCluster` work standalone), so the mayapy suite carries correctness; the live gate (`evals/serpent_live.py`) carries export bytes and judged renders.

**Tech Stack:** Python (Maya-embedded + plain), `maya.cmds`, `maya.api.OpenMaya`/`OpenMayaAnim` (skin weights), pytest, stdlib-only FBX byte reader.

**Design spec:** `docs/superpowers/specs/2026-08-19-rigging-surface-design.md` (committed, user-approved). This plan is its Phase 1 section only.

## Global Constraints

- **Branch:** create `rigging-p1-core` from `main` before the first change. Run `git status` and `git branch --show-current` FIRST — if foreign edits appear (the demigul-art agent shares this machine), stop and report. Never touch `evals/demigol_*`, `shard_*` files, or branch `shards-delivery`.
- **Angles are degrees at every boundary** (#636). Conversion to the scene's UI angle unit happens exactly once, in `units.degrees_to_ui` (Task 3).
- **Positions are ordinary geometry numbers** — scene units, cm scene under the metre-authoring convention (#629/#634). No unit conversion on positions.
- **Results carry measured numbers**: query Maya back, never echo the input (`assemble`'s pivot rule). Displacement from vertices, never bounding boxes (#640).
- **Silence is never an answer**: dropped/renamed/inert outcomes go to `warnings`.
- **Mutating commands call `session.auto_checkpoint` exactly once**, after validation, before the first scene change.
- **The byte gate never reports a number it cannot verify** (#645): null + reason, never a guess.
- Headless suite: `uv run pytest -q` from repo root — currently 1000 tests, must stay green with no Maya installed.
- Mayapy suite: `E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q` — currently 92 tests.
- Two-Maya policy: live gate runs against a disposable agent-launched Maya on port **9878** with a **neutral cwd** (a repo cwd makes Maya import the repo plugin and bypass the deploy — #604); verify the answering **pid** (#648). Never `new_scene` on the user's 9877.
- Commit style: `feat(#602): <what>` / `test(#602): <what>`, frequent commits, each task ends committed.
- Error style: `HandlerError(message, hint=...)` — message says what is wrong, hint says what to do instead.

## File Structure

| File | Responsibility |
|---|---|
| `maya_plugin/handlers/rigmath.py` (create) | Pure validation/stats: joint-list resolution, weight stats, displaced-vertex count. No Maya imports. |
| `maya_plugin/handlers/rigging.py` (create) | The four handlers: Maya orchestration only, all policy delegated to rigmath. |
| `maya_plugin/handlers/units.py` (modify) | Gains the angle-unit table + `degrees_to_ui`/`ui_to_degrees` (promoted from sculpt.py). |
| `maya_plugin/handlers/sculpt.py` (modify) | Uses the promoted angle helpers; `_vertex_positions` becomes public `vertex_positions`. |
| `maya_plugin/handlers/fbxbytes.py` (modify) | Parses Deformer/Cluster/Pose records, decodes cluster index arrays, `skin_facts()`. |
| `maya_plugin/handlers/export.py` (modify) | `include_skins` param, skin MEL switches, skin gate violations, `skin` result block. |
| `maya_plugin/maya_mcp_plugin.py` (modify) | Registers the four commands. |
| `src/maya_mcp/schemas.py` (modify) | `CreateSkeletonResult`, `BindSkinResult`, `PoseSkeletonResult`, `ResetPoseResult`, `SkinFacts`, `ExportFbxResult.skin`. |
| `src/maya_mcp/server.py` (modify) | Four MCP tools + `include_skins` on `maya_export_fbx`. |
| `tests/test_rigmath.py` (create), `tests/test_rigging.py` (create) | Headless coverage. |
| `tests/test_units.py`, `tests/test_fbxbytes.py`, `tests/test_export_fbx.py`, `tests/test_server_tools.py`, `tests/test_handlers_mayapy.py` (modify) | Extended coverage. |
| `evals/make_skin_fixture.py` (create), `evals/rigging_fixtures/skinned_cylinder.fbx` (generated, committed) | Committed skinned artifact for headless byte-reader tests. |
| `evals/serpent_live.py` (create), `evals/serpent_live/` (outputs) | The phase gate. |
| `docs/protocol.md`, `docs/design.md` (modify) | Document the four commands; point the deferred-rigging line at the spec. |

---

### Task 1: `rigmath.resolve_joints` — pure skeleton validation

**Files:**
- Create: `maya_plugin/handlers/rigmath.py`
- Test: `tests/test_rigmath.py`

**Interfaces:**
- Produces: `rigmath.resolve_joints(params: dict) -> List[dict]` — each `{"name": str, "position": [float,float,float], "parent": Optional[str], "orient": Optional[list]}`, topologically ordered (parents before children). Raises `HandlerError` on any invalid input. Also `rigmath.vec3(value, what, default=None)` and `rigmath.MAX_JOINTS = 256`.

- [ ] **Step 1: Write the failing tests** — `tests/test_rigmath.py`:

```python
"""Pure rigging math (#602 phase 1): everything establishable without a scene."""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import rigmath


class TestResolveJointsChain:
    def test_chain_becomes_a_parented_run(self):
        out = rigmath.resolve_joints({
            "chain": [[0, 0, 0], [0, 1, 0], [0, 2, 0]], "chain_prefix": "spine"})
        assert [j["name"] for j in out] == ["spine_01", "spine_02", "spine_03"]
        assert [j["parent"] for j in out] == [None, "spine_01", "spine_02"]
        assert out[1]["position"] == [0.0, 1.0, 0.0]
        assert all(j["orient"] is None for j in out)

    def test_root_name_renames_the_first_joint_only(self):
        out = rigmath.resolve_joints({
            "chain": [[0, 0, 0], [0, 1, 0]], "chain_prefix": "s",
            "root_name": "serpent_root"})
        assert out[0]["name"] == "serpent_root"
        assert out[1]["parent"] == "serpent_root"

    def test_one_position_is_not_a_chain(self):
        with pytest.raises(HandlerError, match="at least 2"):
            rigmath.resolve_joints({"chain": [[0, 0, 0]]})

    def test_chain_positions_are_validated_as_vec3(self):
        with pytest.raises(HandlerError, match="chain\\[1\\]"):
            rigmath.resolve_joints({"chain": [[0, 0, 0], [0, "x", 0]]})

    def test_both_forms_refused(self):
        with pytest.raises(HandlerError, match="exactly one"):
            rigmath.resolve_joints({
                "chain": [[0, 0, 0], [0, 1, 0]],
                "joints": [{"name": "a", "position": [0, 0, 0]}]})

    def test_neither_form_refused(self):
        with pytest.raises(HandlerError, match="exactly one"):
            rigmath.resolve_joints({})

    def test_chain_prefix_with_explicit_joints_refused(self):
        with pytest.raises(HandlerError, match="chain_prefix"):
            rigmath.resolve_joints({
                "joints": [{"name": "a", "position": [0, 0, 0]}],
                "chain_prefix": "x"})


class TestResolveJointsExplicit:
    def _one(self, **over):
        joint = {"name": "a", "position": [0, 0, 0]}
        joint.update(over)
        return joint

    def test_single_joint_skeleton_is_fine(self):
        out = rigmath.resolve_joints({"joints": [self._one()]})
        assert out == [{"name": "a", "position": [0.0, 0.0, 0.0],
                        "parent": None, "orient": None}]

    def test_orient_is_carried_through(self):
        out = rigmath.resolve_joints({"joints": [self._one(orient=[0, 0, 90])]})
        assert out[0]["orient"] == [0.0, 0.0, 90.0]

    def test_unknown_keys_refused(self):
        with pytest.raises(HandlerError, match="unknown"):
            rigmath.resolve_joints({"joints": [self._one(radius=2)]})

    def test_duplicate_names_refused(self):
        with pytest.raises(HandlerError, match="duplicate"):
            rigmath.resolve_joints({"joints": [self._one(), self._one()]})

    def test_unknown_parent_refused(self):
        with pytest.raises(HandlerError, match="ghost"):
            rigmath.resolve_joints({"joints": [self._one(parent="ghost")]})

    def test_two_roots_refused(self):
        with pytest.raises(HandlerError, match="root"):
            rigmath.resolve_joints({"joints": [
                self._one(), self._one(name="b")]})

    def test_a_cycle_is_refused_not_looped(self):
        with pytest.raises(HandlerError, match="cycle"):
            rigmath.resolve_joints({"joints": [
                self._one(name="root"),
                self._one(name="a", parent="b"),
                self._one(name="b", parent="a")]})

    def test_parents_may_be_listed_after_children(self):
        out = rigmath.resolve_joints({"joints": [
            self._one(name="hand", parent="arm"),
            self._one(name="arm", parent="root"),
            self._one(name="root")]})
        assert [j["name"] for j in out] == ["root", "arm", "hand"]

    def test_the_joint_ceiling_holds(self):
        joints = [self._one(name="j%d" % i, parent="j0" if i else None)
                  for i in range(rigmath.MAX_JOINTS + 1)]
        with pytest.raises(HandlerError, match=str(rigmath.MAX_JOINTS)):
            rigmath.resolve_joints({"joints": joints})
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_rigmath.py -q`
Expected: FAIL — `ModuleNotFoundError` / `AttributeError: resolve_joints`

- [ ] **Step 3: Implement** — `maya_plugin/handlers/rigmath.py`:

```python
"""Pure rigging math and validation (#602 phase 1): no Maya, no scene.

The split follows arraymath/uvmath/sculpt_math: everything establishable
without Maya lives here so the headless suite carries it, and the handler
module is orchestration only.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..dispatcher import HandlerError

# A skeleton past this is a data error, not ambition: the humanoid the design
# plans for is ~20 joints, and a mocap-dense film rig is out of scope.
MAX_JOINTS = 256

# Below this a weight is float dust, not an influence: it neither holds a
# vertex nor shows up visually, and counting it would report a clean
# 4-influence bind as violating max_influences.
WEIGHT_TOL = 1e-4


def vec3(value, what: str, default=None) -> Optional[List[float]]:
    """Same contract as assemble._vec3; public because rigging validates maps."""
    if value is None:
        return default
    if (
        not isinstance(value, (list, tuple)) or len(value) != 3
        or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                   for v in value)
    ):
        raise HandlerError(
            "%s must be a list of 3 numbers, got %r" % (what, value),
            hint="e.g. %s=[0, 1.5, 0]" % what,
        )
    return [float(v) for v in value]


def resolve_joints(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Resolve `joints` or the `chain` shorthand into ONE ordered list, or
    refuse the whole call. Parents come before children in the result.

    Whole-call validation is the assemble rule: a skeleton that dies halfway
    through creation is orphan cleanup nobody asked for.
    """
    joints = params.get("joints")
    chain = params.get("chain")
    if (joints is None) == (chain is None):
        raise HandlerError(
            "pass exactly one of 'joints' or 'chain'",
            hint="joints=[{name, position, parent?, orient?}] for an explicit "
                 "hierarchy; chain=[[x,y,z], ...] with chain_prefix for a "
                 "single parented run",
        )

    if chain is not None:
        prefix = params.get("chain_prefix", "joint")
        if not isinstance(prefix, str) or not prefix.strip():
            raise HandlerError("chain_prefix must be a non-empty string")
        prefix = prefix.strip()
        if not isinstance(chain, list) or len(chain) < 2:
            raise HandlerError(
                "chain must be a list of at least 2 positions",
                hint="one joint is not a chain - pass joints=[{...}] instead",
            )
        root_name = params.get("root_name")
        joints = []
        for index, pos in enumerate(chain):
            name = "%s_%02d" % (prefix, index + 1)
            if index == 0 and root_name is not None:
                name = str(root_name)
            joints.append({
                "name": name,
                "position": vec3(pos, "chain[%d]" % index),
                "parent": joints[index - 1]["name"] if index else None,
            })
    else:
        for shorthand_only in ("chain_prefix", "root_name"):
            if params.get(shorthand_only) is not None:
                raise HandlerError(
                    "%s only applies to the chain shorthand" % shorthand_only,
                    hint="the explicit joints form names every joint itself",
                )

    if not isinstance(joints, list) or not joints:
        raise HandlerError("joints must be a non-empty list")
    if len(joints) > MAX_JOINTS:
        raise HandlerError(
            "%d joints is over the %d-joint ceiling" % (len(joints), MAX_JOINTS),
            hint="split the creature, or question the source of the list",
        )

    resolved: List[Dict[str, Any]] = []
    by_name: Dict[str, Dict[str, Any]] = {}
    for index, joint in enumerate(joints):
        where = "joints[%d]" % index
        if not isinstance(joint, dict):
            raise HandlerError("%s must be an object, got %r" % (where, joint))
        unknown = set(joint) - {"name", "position", "parent", "orient"}
        if unknown:
            raise HandlerError(
                "%s has unknown keys: %s" % (where, ", ".join(sorted(unknown))),
                hint="valid: name, position, parent, orient",
            )
        name = joint.get("name")
        if not isinstance(name, str) or not name.strip():
            raise HandlerError("%s needs a non-empty 'name'" % where)
        name = name.strip()
        if name in by_name:
            raise HandlerError(
                "duplicate joint name %r" % name,
                hint="every joint needs its own name - it is the pose map's key",
            )
        parent = joint.get("parent")
        if parent is not None and (not isinstance(parent, str) or not parent.strip()):
            raise HandlerError("%s.parent must be a joint name or null" % where)
        entry = {
            "name": name,
            "position": vec3(joint.get("position"), where + ".position"),
            "parent": parent.strip() if isinstance(parent, str) else None,
            "orient": vec3(joint.get("orient"), where + ".orient"),
        }
        if entry["position"] is None:
            raise HandlerError("%s needs a 'position'" % where,
                               hint="world-space [x, y, z] in scene units")
        resolved.append(entry)
        by_name[name] = entry

    roots = [j for j in resolved if j["parent"] is None]
    for joint in resolved:
        if joint["parent"] is not None and joint["parent"] not in by_name:
            raise HandlerError(
                "joint %r names parent %r, which is not in this call"
                % (joint["name"], joint["parent"]),
                hint="parents must be joints of the same create_skeleton call",
            )
    if len(roots) != 1:
        raise HandlerError(
            "a skeleton has exactly one root; %d joints name no parent"
            % len(roots),
            hint="two roots are two skeletons - make two calls",
        )

    # Topological order by walking down from the root; anything unreached
    # hangs off a parent cycle.
    children: Dict[str, List[Dict[str, Any]]] = {}
    for joint in resolved:
        if joint["parent"] is not None:
            children.setdefault(joint["parent"], []).append(joint)
    order: List[Dict[str, Any]] = []
    frontier = [roots[0]]
    while frontier:
        joint = frontier.pop(0)
        order.append(joint)
        frontier.extend(children.get(joint["name"], []))
    if len(order) != len(resolved):
        stranded = sorted(set(by_name) - {j["name"] for j in order})
        raise HandlerError(
            "joints form a parent cycle: %s" % ", ".join(stranded[:6]),
            hint="every joint must chain up to the root",
        )
    return order
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_rigmath.py -q`
Expected: PASS (all TestResolveJoints* tests)

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/rigmath.py tests/test_rigmath.py
git commit -m "feat(#602): rigmath.resolve_joints - whole-call skeleton validation, pure"
```

---

### Task 2: `rigmath.weight_stats` + `rigmath.displaced_count`

**Files:**
- Modify: `maya_plugin/handlers/rigmath.py` (append)
- Test: `tests/test_rigmath.py` (append)

**Interfaces:**
- Produces: `weight_stats(influences: List[str], weights: List[float], num_verts: int, max_influences: int) -> dict` with keys `unweighted_vertices: int`, `max_influences_exceeded: int`, `per_joint: [{"joint", "vertices", "mean_weight"}]`. `weights` is flat vertex-major: `weights[v * len(influences) + j]` (the `MFnSkinCluster.getWeights` layout).
- Produces: `displaced_count(before: List[float], after: List[float], tol: float = 1e-5) -> int` over flat xyz position lists.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_rigmath.py`):

```python
class TestWeightStats:
    def test_per_joint_ownership_and_means(self):
        # 3 verts x 2 joints, vertex-major.
        out = rigmath.weight_stats(
            ["|a", "|b"], [1.0, 0.0, 0.5, 0.5, 0.0, 1.0], 3, max_influences=4)
        a, b = out["per_joint"]
        assert (a["joint"], a["vertices"]) == ("|a", 2)
        assert a["mean_weight"] == pytest.approx(0.75)
        assert (b["joint"], b["vertices"]) == ("|b", 2)
        assert out["unweighted_vertices"] == 0
        assert out["max_influences_exceeded"] == 0

    def test_a_vertex_no_joint_owns_is_counted(self):
        out = rigmath.weight_stats(["|a"], [1.0, 0.0], 2, max_influences=4)
        assert out["unweighted_vertices"] == 1

    def test_float_dust_is_not_an_influence(self):
        out = rigmath.weight_stats(
            ["|a", "|b"], [1.0, rigmath.WEIGHT_TOL / 10], 1, max_influences=1)
        assert out["max_influences_exceeded"] == 0
        assert out["per_joint"][1]["vertices"] == 0

    def test_over_budget_vertices_are_counted(self):
        out = rigmath.weight_stats(
            ["|a", "|b", "|c"], [0.4, 0.3, 0.3], 1, max_influences=2)
        assert out["max_influences_exceeded"] == 1

    def test_a_joint_owning_nothing_reports_zero_mean_not_nan(self):
        out = rigmath.weight_stats(["|a", "|b"], [1.0, 0.0], 1, max_influences=4)
        assert out["per_joint"][1] == {
            "joint": "|b", "vertices": 0, "mean_weight": 0.0}

    def test_a_shape_mismatch_is_an_internal_error(self):
        with pytest.raises(ValueError):
            rigmath.weight_stats(["|a"], [1.0, 1.0, 1.0], 2, max_influences=4)


class TestDisplacedCount:
    def test_counts_only_vertices_that_moved(self):
        before = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0]
        after = [0.0, 0.0, 0.0, 1.0, 2.0, 0.0]
        assert rigmath.displaced_count(before, after) == 1

    def test_motion_below_tol_is_rest(self):
        assert rigmath.displaced_count([0.0, 0.0, 0.0], [0.0, 1e-7, 0.0]) == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_rigmath.py -q` → FAIL with `AttributeError: weight_stats`

- [ ] **Step 3: Implement** (append to `rigmath.py`):

```python
def weight_stats(influences: List[str], weights: List[float], num_verts: int,
                 max_influences: int) -> Dict[str, Any]:
    """Per-joint ownership from one flat vertex-major weight table.

    `weights[v * len(influences) + j]` is joint j's hold on vertex v - the
    layout MFnSkinCluster.getWeights returns. This is the whole of how an
    agent SEES a bind without a viewport: a joint owning zero vertices, or
    one joint owning everything, is a legible failure in these numbers.
    """
    ncols = len(influences)
    if num_verts * ncols != len(weights):
        raise ValueError(
            "weight table is %d entries, expected %d verts x %d influences"
            % (len(weights), num_verts, ncols))
    unweighted = 0
    exceeded = 0
    counts = [0] * ncols
    sums = [0.0] * ncols
    for v in range(num_verts):
        held = 0
        for j in range(ncols):
            w = weights[v * ncols + j]
            if w > WEIGHT_TOL:
                held += 1
                counts[j] += 1
                sums[j] += w
        if held == 0:
            unweighted += 1
        if held > max_influences:
            exceeded += 1
    return {
        "unweighted_vertices": unweighted,
        "max_influences_exceeded": exceeded,
        "per_joint": [
            {"joint": influences[j], "vertices": counts[j],
             "mean_weight": (sums[j] / counts[j]) if counts[j] else 0.0}
            for j in range(ncols)
        ],
    }


def displaced_count(before: List[float], after: List[float],
                    tol: float = 1e-5) -> int:
    """How many vertices moved more than `tol` between two flat xyz lists."""
    moved = 0
    for i in range(0, min(len(before), len(after)), 3):
        dx = after[i] - before[i]
        dy = after[i + 1] - before[i + 1]
        dz = after[i + 2] - before[i + 2]
        if dx * dx + dy * dy + dz * dz > tol * tol:
            moved += 1
    return moved
```

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_rigmath.py -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/rigmath.py tests/test_rigmath.py
git commit -m "feat(#602): rigmath weight stats and displaced-vertex count"
```

---

### Task 3: promote the angle-unit helpers into `units.py`

Every rigging command writes doubleAngle attributes (rotate, jointOrient) in degrees; sculpt.py already solved the UI-unit conversion for #636. One copy, in units.py.

**Files:**
- Modify: `maya_plugin/handlers/units.py`
- Modify: `maya_plugin/handlers/sculpt.py` (use the promoted helpers; make `_vertex_positions` public)
- Test: `tests/test_units.py` (append)

**Interfaces:**
- Produces: `units.DEGREES_PER_ANGLE_UNIT: dict`, `units.degrees_to_ui(cmds, degrees) -> float`, `units.ui_to_degrees(cmds, value) -> float` (both raise `HandlerError` on an unknown scene angle unit), and `sculpt.vertex_positions(cmds, mesh_long) -> List[float]` (the renamed `_vertex_positions`, same behavior).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_units.py`):

```python
class FakeAngleCmds:
    def __init__(self, unit):
        self._unit = unit

    def currentUnit(self, query=False, angle=False, **kw):
        return self._unit


class TestAngleUnits:
    def test_degrees_pass_through_a_degree_scene(self):
        assert units.degrees_to_ui(FakeAngleCmds("deg"), 90.0) == 90.0
        assert units.ui_to_degrees(FakeAngleCmds("deg"), 90.0) == 90.0

    def test_a_radian_scene_gets_radians(self):
        import math
        assert units.degrees_to_ui(FakeAngleCmds("rad"), 180.0) == pytest.approx(math.pi)
        assert units.ui_to_degrees(FakeAngleCmds("rad"), math.pi) == pytest.approx(180.0)

    def test_the_two_directions_round_trip(self):
        cmds = FakeAngleCmds("min")
        assert units.ui_to_degrees(cmds, units.degrees_to_ui(cmds, 33.3)) == pytest.approx(33.3)

    def test_an_unknown_angle_unit_is_refused_not_guessed(self):
        from maya_plugin.dispatcher import HandlerError
        with pytest.raises(HandlerError, match="angle unit"):
            units.degrees_to_ui(FakeAngleCmds("grad"), 1.0)
```

(Match the file's existing import style — it already imports `units` and `pytest`.)

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_units.py -q` → FAIL

- [ ] **Step 3: Implement.** In `units.py`, add `import math` at the top and append:

```python
# Maya's four angular units, in degrees-per-unit. setAttr/getAttr on a
# doubleAngle attribute speak the CURRENT UI angle unit, so every handler
# that states its angles in degrees (#636's rule) converts at this table.
DEGREES_PER_ANGLE_UNIT = {
    "deg": 1.0,
    "rad": 180.0 / math.pi,
    "min": 1.0 / 60.0,
    "sec": 1.0 / 3600.0,
}


def _degrees_per_unit(cmds) -> float:
    unit = cmds.currentUnit(query=True, angle=True)
    per_unit = DEGREES_PER_ANGLE_UNIT.get(unit)
    if per_unit is None:
        raise HandlerError(
            "scene angle unit %r is not one of %s"
            % (unit, ", ".join(sorted(DEGREES_PER_ANGLE_UNIT))),
            hint="this tool states its angles in degrees and cannot convert "
                 "into an unknown unit",
        )
    return per_unit


def degrees_to_ui(cmds, degrees: float) -> float:
    """Degrees -> the scene's current angular unit, for setAttr."""
    return float(degrees) / _degrees_per_unit(cmds)


def ui_to_degrees(cmds, value: float) -> float:
    """What a doubleAngle getAttr just returned -> degrees."""
    return float(value) * _degrees_per_unit(cmds)
```

In `sculpt.py`:
- delete `_DEGREES_PER_UI_ANGLE` (keep `import math` if still used elsewhere);
- `_set_deformer_attr` body becomes:

```python
    plug = "%s.%s" % (node, attr)
    if cmds.getAttr(plug, type=True) == "doubleAngle":
        value = units.degrees_to_ui(cmds, value)
    cmds.setAttr(plug, value)
```

(add `units` to sculpt's `from . import ...` line);
- rename `_vertex_positions` → `vertex_positions` and update sculpt.py's two call sites (`grep -n "_vertex_positions" maya_plugin/handlers/sculpt.py`).

- [ ] **Step 4: Run the whole headless suite** — `uv run pytest -q` → all green. If any sculpt test pinned the old hint text ("deform states its angles"), update that assertion to the units.py wording — the behavior (refuse unknown unit, converted value) is what is pinned, not the prose.

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/units.py maya_plugin/handlers/sculpt.py tests/test_units.py
git commit -m "feat(#602): promote degree<->UI-angle conversion into units, publish vertex_positions"
```

---

### Task 4: `create_skeleton` handler

**Files:**
- Create: `maya_plugin/handlers/rigging.py`
- Test: `tests/test_rigging.py` (headless), `tests/test_handlers_mayapy.py` (append)

**Interfaces:**
- Consumes: `rigmath.resolve_joints`, `naming.unique_name`, `session.auto_checkpoint`, `units.degrees_to_ui` / `ui_to_degrees`.
- Produces: handler `create_skeleton(params) -> {"root": str, "joints": [{"name", "position", "parent", "orient"}], "warnings": [str]}` — all names canonical long names, positions measured back from Maya (world), orient in degrees.

- [ ] **Step 1: Write the failing headless tests** — `tests/test_rigging.py`:

```python
"""Rigging handlers (#602 phase 1) - orchestration under a FakeCmds.

Real joints, real skinClusters and real deformation are mayapy's job
(tests/test_handlers_mayapy.py); this file pins the call SEQUENCE: one
checkpoint, unique naming, parent selection order, measured-not-echoed
reporting, and every refusal path.
"""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import rigging, session


class FakeCmds:
    def __init__(self, angle_unit="deg"):
        self.objects = []
        self.calls = []
        self.attrs = {}
        self.parents = {}       # child long -> parent long
        self._angle_unit = angle_unit
        self.selection = []

    # --- names
    def objExists(self, name):
        return any(o.split("|")[-1] == name or o == name for o in self.objects)

    def ls(self, pattern=None, long=False, type=None, **kw):
        if type == "skinCluster":
            return []
        if pattern is None:
            return list(self.objects)
        return [o for o in self.objects
                if o == pattern or o.split("|")[-1] == pattern]

    def nodeType(self, node):
        return "joint" if "joint" in self.calls_kinds.get(node, "joint") else "transform"

    # --- creation
    def select(self, *args, **kw):
        if kw.get("clear"):
            self.selection = []
        elif args:
            self.selection = list(args)
        self.calls.append(("select", tuple(args), kw.get("clear", False)))

    def joint(self, *args, **kw):
        if kw.get("edit"):
            self.calls.append(("joint_edit", args, kw))
            return None
        name = kw["name"]
        parent = self.selection[0] if self.selection else None
        long = (parent + "|" + name) if parent else ("|" + name)
        self.objects.append(long)
        self.parents[long] = parent
        self.attrs[long + ".jointOrient"] = [(0.0, 0.0, 0.0)]
        self.calls.append(("joint", name, tuple(kw["position"]), parent))
        return name

    def listRelatives(self, node, children=False, allDescendents=False,
                      type=None, fullPath=False, **kw):
        kids = [o for o, p in self.parents.items() if p == node]
        if allDescendents:
            out = []
            frontier = list(kids)
            while frontier:
                k = frontier.pop()
                out.append(k)
                frontier.extend(o for o, p in self.parents.items() if p == k)
            return out or None
        return kids or None

    def xform(self, node, query=False, worldSpace=False, translation=False, **kw):
        self.calls.append(("xform_query", node))
        return [1.0, 2.0, 3.0]  # deliberately NOT the input - proves measurement

    def setAttr(self, plug, *values, **kw):
        self.attrs[plug] = [tuple(values)] if len(values) == 3 else list(values)
        self.calls.append(("setAttr", plug, values))

    def getAttr(self, plug, type=False, **kw):
        if type:
            return "doubleAngle"
        return self.attrs.get(plug, [(0.0, 0.0, 0.0)])

    def currentUnit(self, query=False, angle=False, linear=False, **kw):
        return self._angle_unit if angle else "cm"

FakeCmds.calls_kinds = {}


@pytest.fixture
def fake(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(rigging, "_cmds", lambda: fake)
    monkeypatch.setattr(session, "auto_checkpoint",
                        lambda reason: {"checkpoint_id": "001_" + reason,
                                        "path": "x.ma"})
    return fake


class TestCreateSkeleton:
    def test_chain_parents_each_joint_under_the_previous(self, fake):
        out = rigging.create_skeleton({
            "chain": [[0, 0, 0], [0, 1, 0], [0, 2, 0]], "chain_prefix": "s"})
        made = [c for c in fake.calls if c[0] == "joint"]
        assert [m[1] for m in made] == ["s_01", "s_02", "s_03"]
        assert made[0][3] is None
        assert made[1][3] == "|s_01"
        assert out["root"] == "|s_01"
        assert [j["parent"] for j in out["joints"]] == [None, "|s_01", "|s_01|s_02"]

    def test_positions_are_measured_back_not_echoed(self, fake):
        out = rigging.create_skeleton({"chain": [[0, 0, 0], [0, 9, 0]]})
        assert out["joints"][0]["position"] == [1.0, 2.0, 3.0]

    def test_one_checkpoint_before_any_joint(self, fake, monkeypatch):
        events = []
        monkeypatch.setattr(session, "auto_checkpoint",
                            lambda reason: events.append("checkpoint") or
                            {"checkpoint_id": "001", "path": "x.ma"})
        real_joint = fake.joint
        def logged_joint(*a, **kw):
            events.append("joint")
            return real_joint(*a, **kw)
        fake.joint = logged_joint
        rigging.create_skeleton({"chain": [[0, 0, 0], [0, 1, 0]]})
        assert events[0] == "checkpoint"
        assert events.count("checkpoint") == 1

    def test_a_name_collision_warns_and_renames(self, fake):
        fake.objects.append("|s_01")
        fake.parents["|s_01"] = None
        out = rigging.create_skeleton({"chain": [[0, 0, 0], [0, 1, 0]],
                                       "chain_prefix": "s"})
        assert any("s_01" in w for w in out["warnings"])
        made = [c[1] for c in fake.calls if c[0] == "joint"]
        assert "s_01_001" in made

    def test_validation_failure_costs_nothing(self, fake, monkeypatch):
        monkeypatch.setattr(session, "auto_checkpoint",
                            lambda reason: pytest.fail("checkpointed a bad call"))
        with pytest.raises(HandlerError):
            rigging.create_skeleton({"chain": [[0, 0, 0]]})
        assert fake.objects == []
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_rigging.py -q` → FAIL (no module `rigging`)

- [ ] **Step 3: Implement** — `maya_plugin/handlers/rigging.py`:

```python
"""Skeletal rigging, phase 1 of #602: create_skeleton, bind_skin,
pose_skeleton, reset_pose.

Angles are degrees at the boundary (#636), positions are ordinary geometry
numbers (#629/#634), and every command reports what it MEASURED, not what it
was asked for: a bind reports the vertices no joint owns, a pose reports how
far the furthest vertex actually moved - from vertices, never bounding boxes
(#640). The shaping op that did nothing and said it succeeded is the worst
defect class this project knows (#636), and this module is built so that
failure is a number, not a feeling.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..dispatcher import HandlerError
from . import naming, rigmath, sculpt, sculpt_math, session, units


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _short(name: str) -> str:
    return name.split("|")[-1]


def _long(cmds, node: str) -> str:
    return (cmds.ls(node, long=True) or [node])[0]


def create_skeleton(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    resolved = rigmath.resolve_joints(params)
    session.auto_checkpoint("create_skeleton")

    warnings: List[str] = []
    long_names: Dict[str, str] = {}  # requested name -> created long name
    for joint in resolved:
        unique = naming.unique_name(cmds, joint["name"])
        if unique != joint["name"]:
            warnings.append(
                "%r already existed in the scene; created as %r"
                % (joint["name"], unique))
        if joint["parent"] is None:
            cmds.select(clear=True)
        else:
            cmds.select(long_names[joint["parent"]], replace=True)
        node = cmds.joint(name=unique, position=joint["position"])
        long_names[joint["name"]] = _long(cmds, node)

    root_long = long_names[resolved[0]["name"]]

    # Default orientation: aim the primary axis at the first child, Maya's own
    # convention; leaves are zeroed so nothing dangles a stray orient. The
    # explicit per-joint `orient` overrides afterwards. Whatever won is
    # REPORTED per joint, because orientation is where every rig surprise
    # lives.
    if cmds.listRelatives(root_long, children=True, type="joint"):
        cmds.joint(root_long, edit=True, orientJoint="xyz",
                   secondaryAxisOrient="yup", zeroScaleOrient=True,
                   children=True)
    for joint in resolved:
        node = long_names[joint["name"]]
        if not cmds.listRelatives(node, children=True, type="joint"):
            cmds.setAttr(node + ".jointOrient", 0.0, 0.0, 0.0)
        if joint["orient"] is not None:
            cmds.setAttr(node + ".jointOrient",
                         units.degrees_to_ui(cmds, joint["orient"][0]),
                         units.degrees_to_ui(cmds, joint["orient"][1]),
                         units.degrees_to_ui(cmds, joint["orient"][2]))

    joints_out = []
    for joint in resolved:
        node = long_names[joint["name"]]
        pos = cmds.xform(node, query=True, worldSpace=True, translation=True)
        raw = cmds.getAttr(node + ".jointOrient")[0]
        joints_out.append({
            "name": node,
            "position": [float(v) for v in pos],
            "parent": long_names[joint["parent"]] if joint["parent"] else None,
            "orient": [round(units.ui_to_degrees(cmds, v), 6) for v in raw],
        })
    return {"root": root_long, "joints": joints_out, "warnings": warnings}
```

- [ ] **Step 4: Run headless** — `uv run pytest tests/test_rigging.py tests/test_rigmath.py -q` → PASS

- [ ] **Step 5: Write the failing mayapy tests** (append to `tests/test_handlers_mayapy.py`):

```python
class TestCreateSkeletonInMaya:
    def test_chain_builds_parented_joints_at_the_positions(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        out = rigging.create_skeleton({
            "chain": [[0, 0, 0], [0, 2, 0], [0, 4, 0]], "chain_prefix": "sp"})
        assert out["root"] == "|sp_01"
        assert cmds.nodeType(out["root"]) == "joint"
        assert [tuple(round(v, 6) for v in j["position"])
                for j in out["joints"]] == [(0, 0, 0), (0, 2, 0), (0, 4, 0)]
        # Parented: moving the root carries the chain.
        cmds.xform("|sp_01", worldSpace=True, translation=[1, 0, 0])
        tip = cmds.xform(out["joints"][2]["name"], query=True,
                         worldSpace=True, translation=True)
        assert tip[0] == pytest.approx(1.0)

    def test_default_orient_aims_x_at_the_child_and_zeroes_the_leaf(self):
        from maya_plugin.handlers import rigging

        out = rigging.create_skeleton({
            "chain": [[0, 0, 0], [0, 2, 0]], "chain_prefix": "o"})
        # A straight +Y chain under xyz/yup: X aims at the child, so the root
        # carries a 90-degree orient about Z, and the leaf carries none.
        assert out["joints"][0]["orient"][2] == pytest.approx(90.0, abs=1e-4)
        assert out["joints"][1]["orient"] == pytest.approx([0.0, 0.0, 0.0])

    def test_explicit_orient_overrides_and_reports_in_degrees(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        cmds.currentUnit(angle="rad")
        try:
            out = rigging.create_skeleton({"joints": [
                {"name": "solo", "position": [0, 0, 0], "orient": [0, 45, 0]}]})
            assert out["joints"][0]["orient"][1] == pytest.approx(45.0, abs=1e-4)
        finally:
            cmds.currentUnit(angle="deg")

    def test_single_joint_skeleton_works(self):
        from maya_plugin.handlers import rigging

        out = rigging.create_skeleton({"joints": [
            {"name": "lone", "position": [1, 2, 3]}]})
        assert out["root"] == "|lone"
        assert out["joints"][0]["position"] == pytest.approx([1.0, 2.0, 3.0])
```

- [ ] **Step 6: Run mayapy** — `E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -k CreateSkeleton -q` → PASS (fix the handler, not the test, if the orient pin disagrees — the measured number wins and gets a comment).

- [ ] **Step 7: Commit**

```bash
git add maya_plugin/handlers/rigging.py tests/test_rigging.py tests/test_handlers_mayapy.py
git commit -m "feat(#602): create_skeleton - validated joint hierarchies with reported orients"
```

---

### Task 5: `bind_skin` handler

**Files:**
- Modify: `maya_plugin/handlers/rigging.py`
- Test: `tests/test_rigging.py`, `tests/test_handlers_mayapy.py` (append)

**Interfaces:**
- Consumes: `rigmath.weight_stats`, `naming.require_mesh` / `require_object`.
- Produces: handler `bind_skin(params) -> {"mesh", "root", "skin_cluster", "influences": [str], "unweighted_vertices": int, "max_influences_exceeded": int, "per_joint": [...], "warnings"}`. Also internal `_skin_weights(skin_cluster, mesh_shape) -> (influences, flat_weights, num_verts)` and `_require_joint(cmds, name) -> str` reused by Task 6.

- [ ] **Step 1: Write the failing headless tests** (append to `tests/test_rigging.py`; extend FakeCmds with the methods below):

Add to FakeCmds:

```python
    # --- binding
    skin_history = []      # set by tests: skinClusters in the mesh's history

    def listHistory(self, node, pruneDagObjects=False, **kw):
        return list(self.skin_history)

    def skinCluster(self, *args, **kw):
        self.calls.append(("skinCluster", args, kw))
        return ["fakeSkin1"]
```

and make `ls` return `self.skin_history` when called with the history list (mirror how `test_export_fbx.py`'s FakeCmds filters — `ls(nodes, type="skinCluster")` returns the input when `skin_history` is truthy). Tests:

```python
class TestBindSkinValidation:
    def _mesh(self, fake):
        fake.objects.append("|serpent")
        fake.shapes = {"|serpent": "|serpent|serpentShape"}
        def listRelatives(node, shapes=False, **kw):
            if shapes:
                return [fake.shapes.get(node)]
            return FakeCmds.listRelatives(fake, node, **kw)
        fake.listRelatives = listRelatives

    def test_root_must_be_a_joint(self, fake):
        self._mesh(fake)
        fake.objects.append("|not_a_joint")
        fake.node_types = {"|not_a_joint": "transform"}
        with pytest.raises(HandlerError, match="not a joint"):
            rigging.bind_skin({"mesh": "serpent", "root": "not_a_joint"})

    def test_unknown_method_lists_the_valid_ones(self, fake):
        self._mesh(fake)
        fake.objects.append("|root_j")
        with pytest.raises(HandlerError, match="closestDistance"):
            rigging.bind_skin({"mesh": "serpent", "root": "root_j",
                               "method": "psychic"})

    def test_max_influences_bounds(self, fake):
        self._mesh(fake)
        fake.objects.append("|root_j")
        with pytest.raises(HandlerError, match="max_influences"):
            rigging.bind_skin({"mesh": "serpent", "root": "root_j",
                               "max_influences": 0})

    def test_rebind_is_refused_with_the_unbind_hint(self, fake):
        self._mesh(fake)
        fake.objects.append("|root_j")
        fake.skin_history = ["oldSkin"]
        with pytest.raises(HandlerError, match="already bound") as err:
            rigging.bind_skin({"mesh": "serpent", "root": "root_j"})
        assert "unbind" in err.value.hint
```

(Adapt the FakeCmds `nodeType` to consult a `node_types` dict defaulting to `"joint"`; the exact fake shape is the implementer's to settle — what is pinned is each refusal and its hint.)

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_rigging.py -q` → FAIL (`AttributeError: bind_skin`)

- [ ] **Step 3: Implement** (append to `rigging.py`):

```python
# bindMethod values cmds.skinCluster actually takes, by the names the tool
# surface speaks. 1 (closest in hierarchy) is deliberately absent until a
# run fights for it.
BIND_METHODS = {"closestDistance": 0, "heatMap": 2, "geodesicVoxel": 3}
MAX_INFLUENCES_CEILING = 8


def _require_joint(cmds, name) -> str:
    node = naming.require_object(cmds, str(name or ""))
    if cmds.nodeType(node) != "joint":
        raise HandlerError(
            "%s is not a joint" % node,
            hint="pass the skeleton root maya_create_skeleton returned")
    return node


def _skin_weights(skin_cluster: str,
                  mesh_shape: str) -> Tuple[List[str], List[float], int]:
    """Every weight in ONE call, via the API.

    cmds.skinPercent is a call per vertex - on a real mesh that is the whole
    timeout. MFnSkinCluster.getWeights returns the entire table at once, and
    its columns follow influenceObjects() order, which is NOT necessarily the
    cmds query order - so the influence names come from the same API call.
    """
    import maya.api.OpenMaya as om          # noqa: PLC0415
    import maya.api.OpenMayaAnim as oma     # noqa: PLC0415

    sel = om.MSelectionList()
    sel.add(mesh_shape)
    sel.add(skin_cluster)
    dag = sel.getDagPath(0)
    fn = oma.MFnSkinCluster(sel.getDependNode(1))
    comp_fn = om.MFnSingleIndexedComponent()
    comp = comp_fn.create(om.MFn.kMeshVertComponent)
    num_verts = om.MFnMesh(dag).numVertices
    comp_fn.setCompleteData(num_verts)
    weights, _ncols = fn.getWeights(dag, comp)
    influences = [dp.fullPathName() for dp in fn.influenceObjects()]
    return influences, list(weights), num_verts


def bind_skin(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    mesh_long, mesh_shape = naming.require_mesh(cmds, str(params.get("mesh") or ""))
    root_long = _require_joint(cmds, params.get("root"))

    method = params.get("method", "closestDistance")
    if method not in BIND_METHODS:
        raise HandlerError(
            "unknown bind method %r" % (method,),
            hint="one of: %s" % ", ".join(sorted(BIND_METHODS)))
    max_influences = params.get("max_influences", 4)
    if (not isinstance(max_influences, int) or isinstance(max_influences, bool)
            or not 1 <= max_influences <= MAX_INFLUENCES_CEILING):
        raise HandlerError(
            "max_influences must be an integer 1..%d" % MAX_INFLUENCES_CEILING,
            hint="4 is the game-engine convention and the default")

    existing = cmds.ls(cmds.listHistory(mesh_shape, pruneDagObjects=True) or [],
                       type="skinCluster") or []
    if existing:
        raise HandlerError(
            "%s is already bound (skinCluster %s)" % (mesh_long, existing[0]),
            hint="stacked skinClusters are Maya's quietest way to make weights "
                 "unexplainable, so re-binding is refused. Unbind first via "
                 "maya_execute_python: cmds.skinCluster(%r, edit=True, "
                 "unbind=True) - or restore the checkpoint taken before the "
                 "first bind" % existing[0])

    session.auto_checkpoint("bind_skin")
    sc = cmds.skinCluster(
        root_long, mesh_long,
        bindMethod=BIND_METHODS[method],
        maximumInfluences=max_influences,
        obeyMaxInfluences=True,
        toSelectedBones=False,
        name=naming.unique_name(cmds, _short(mesh_long) + "_skin"),
    )[0]

    influences, weights, num_verts = _skin_weights(sc, mesh_shape)
    stats = rigmath.weight_stats(influences, weights, num_verts, max_influences)

    warnings: List[str] = []
    empty = [p["joint"] for p in stats["per_joint"] if p["vertices"] == 0]
    if empty:
        warnings.append(
            "%d joint(s) own no vertices and will move nothing when posed: %s"
            % (len(empty), ", ".join(_short(j) for j in empty[:8])))
    if stats["unweighted_vertices"]:
        warnings.append(
            "%d vertices belong to NO joint - they stay behind when the "
            "creature moves, and nothing looks wrong at bind time. This bind "
            "fails the phase gate." % stats["unweighted_vertices"])
    if stats["max_influences_exceeded"]:
        warnings.append(
            "%d vertices carry more than max_influences=%d meaningful weights"
            % (stats["max_influences_exceeded"], max_influences))

    return {
        "mesh": mesh_long,
        "root": root_long,
        "skin_cluster": sc,
        "influences": influences,
        "unweighted_vertices": stats["unweighted_vertices"],
        "max_influences_exceeded": stats["max_influences_exceeded"],
        "per_joint": stats["per_joint"],
        "warnings": warnings,
    }
```

- [ ] **Step 4: Run headless** — `uv run pytest tests/test_rigging.py -q` → PASS

- [ ] **Step 5: Write the failing mayapy tests** (append):

```python
def _serpent_cylinder(cmds, name="tube", height=4.0, sections=12):
    """A cylinder standing on Y with enough length subdivisions to bend."""
    node = cmds.polyCylinder(name=name, radius=0.3, height=height,
                             subdivisionsY=sections, ch=False)[0]
    cmds.xform(node, worldSpace=True, translation=[0, height / 2.0, 0])
    return (cmds.ls(node, long=True) or [node])[0]


class TestBindSkinInMaya:
    def _chain(self, rigging, n=4, height=4.0):
        step = height / (n - 1)
        return rigging.create_skeleton({
            "chain": [[0, i * step, 0] for i in range(n)],
            "chain_prefix": "bj"})

    def test_bind_owns_every_vertex(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        mesh = _serpent_cylinder(cmds)
        skel = self._chain(rigging)
        out = rigging.bind_skin({"mesh": mesh, "root": skel["root"]})
        assert out["unweighted_vertices"] == 0
        assert len(out["influences"]) == 4
        assert all(p["vertices"] > 0 for p in out["per_joint"])
        total_verts = cmds.polyEvaluate(mesh, vertex=True)
        assert sum(p["vertices"] for p in out["per_joint"]) >= total_verts

    def test_rebind_is_refused_against_a_real_skincluster(self):
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import rigging

        mesh = _serpent_cylinder(cmds, name="tube2")
        skel = self._chain(rigging)
        rigging.bind_skin({"mesh": mesh, "root": skel["root"]})
        with pytest.raises(HandlerError, match="already bound"):
            rigging.bind_skin({"mesh": mesh, "root": skel["root"]})

    def test_max_influences_is_obeyed_in_the_weights(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        mesh = _serpent_cylinder(cmds, name="tube3")
        skel = self._chain(rigging, n=6)
        out = rigging.bind_skin({"mesh": mesh, "root": skel["root"],
                                 "max_influences": 2})
        assert out["max_influences_exceeded"] == 0
```

- [ ] **Step 6: Run mayapy** — `E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -k BindSkin -q` → PASS

- [ ] **Step 7: Commit**

```bash
git add maya_plugin/handlers/rigging.py tests/test_rigging.py tests/test_handlers_mayapy.py
git commit -m "feat(#602): bind_skin - one-call bind with measured per-joint ownership"
```

---

### Task 6: `pose_skeleton` and `reset_pose`

**Files:**
- Modify: `maya_plugin/handlers/rigging.py`
- Test: `tests/test_rigging.py`, `tests/test_handlers_mayapy.py` (append)

**Interfaces:**
- Consumes: `sculpt.vertex_positions`, `sculpt_math.max_displacement`, `sculpt_math.bbox_extent`, `rigmath.displaced_count`, `rigmath.vec3`, `units.degrees_to_ui`, `_require_joint`.
- Produces: `pose_skeleton(params) -> {"applied": int, "joints": [{"name", "world_position"}], "max_displacement": float, "displaced_vertices": int, "warnings"}`; `reset_pose(params) -> {"reset": True, "max_displacement": float, "warnings"}`. Pose currency: `rotations={joint_name: [rx, ry, rz]}` per-joint LOCAL euler DEGREES — **this is the fixed currency for phases 3 and 6; do not redesign it.**

- [ ] **Step 1: Write the failing headless tests** (append to `tests/test_rigging.py` — FakeCmds needs `dagPose` recording calls and returning a canned list):

```python
class TestPoseValidation:
    def _skeleton(self, fake):
        fake.objects += ["|r", "|r|a"]
        fake.parents = {"|r|a": "|r"}

    def test_space_other_than_local_is_refused(self, fake):
        self._skeleton(fake)
        with pytest.raises(HandlerError, match="space"):
            rigging.pose_skeleton({"root": "r", "space": "world",
                                   "rotations": {"a": [0, 0, 10]}})

    def test_empty_rotations_refused(self, fake):
        self._skeleton(fake)
        with pytest.raises(HandlerError, match="rotations"):
            rigging.pose_skeleton({"root": "r", "rotations": {}})

    def test_a_joint_outside_the_root_is_refused_by_name(self, fake):
        self._skeleton(fake)
        with pytest.raises(HandlerError, match="stranger"):
            rigging.pose_skeleton({"root": "r",
                                   "rotations": {"stranger": [0, 0, 10]}})

    def test_rotations_reach_maya_in_scene_units(self, fake):
        import math
        fake._angle_unit = "rad"
        self._skeleton(fake)
        rigging.pose_skeleton({"root": "r", "rotations": {"a": [0, 0, 90]}})
        wrote = [c for c in fake.calls
                 if c[0] == "setAttr" and c[1] == "|r|a.rotate"]
        assert wrote[0][2][2] == pytest.approx(math.pi / 2)

    def test_no_bound_mesh_is_a_warning_not_silence(self, fake):
        self._skeleton(fake)
        out = rigging.pose_skeleton({"root": "r", "rotations": {"a": [0, 0, 10]}})
        assert any("no skinned mesh" in w for w in out["warnings"])
        assert out["max_displacement"] == 0.0


class TestResetPose:
    def test_unbound_skeleton_zeroes_rotations_with_a_warning(self, fake):
        fake.objects += ["|r", "|r|a"]
        fake.parents = {"|r|a": "|r"}
        out = rigging.reset_pose({"root": "r"})
        assert out["reset"] is True
        assert any("no bind pose" in w for w in out["warnings"])
        zeroed = [c for c in fake.calls
                  if c[0] == "setAttr" and c[1].endswith(".rotate")]
        assert len(zeroed) == 2
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_rigging.py -q` → FAIL

- [ ] **Step 3: Implement** (append to `rigging.py`):

```python
# Below this fraction of the bound mesh's own bbox diagonal, a pose is the
# "reported success, moved nothing" failure (#636) and warns loudly. Same
# constant and rationale as sculpt.NOOP_DISPLACEMENT_RATIO.
NOOP_POSE_RATIO = 1e-2


def _hierarchy_joints(cmds, root_long: str) -> List[str]:
    return [root_long] + (cmds.listRelatives(
        root_long, allDescendents=True, type="joint", fullPath=True) or [])


def _bound_meshes(cmds, joint_set) -> List[str]:
    """Transforms of every mesh whose skinCluster any of these joints drives."""
    out: List[str] = []
    for sc in cmds.ls(type="skinCluster") or []:
        influences = cmds.skinCluster(sc, query=True, influence=True) or []
        influences = set(cmds.ls(influences, long=True) or [])
        if not influences & joint_set:
            continue
        for shape in cmds.skinCluster(sc, query=True, geometry=True) or []:
            transform = cmds.listRelatives(shape, parent=True, fullPath=True)
            if transform and transform[0] not in out:
                out.append(transform[0])
    return out


def _resolve_rotations(cmds, joints: List[str], rotations) -> Dict[str, List[float]]:
    if not isinstance(rotations, dict) or not rotations:
        raise HandlerError(
            "rotations must be a non-empty map of joint name to [rx, ry, rz] "
            "in DEGREES",
            hint='e.g. rotations={"spine_03": [0, 0, 8.2]}')
    by_short: Dict[str, List[str]] = {}
    for j in joints:
        by_short.setdefault(_short(j), []).append(j)
    resolved: Dict[str, List[float]] = {}
    for name, value in rotations.items():
        triple = rigmath.vec3(value, "rotations[%r]" % name)
        if triple is None:
            raise HandlerError("rotations[%r] must be [rx, ry, rz]" % name)
        if name in joints:
            resolved[name] = triple
            continue
        matches = by_short.get(_short(name), [])
        if not matches:
            raise HandlerError(
                "rotations names %r, which is not a joint under this root" % name,
                hint="joints here: %s"
                     % ", ".join(_short(j) for j in joints[:12]))
        if len(matches) > 1:
            raise HandlerError(
                "%r is ambiguous under this root (%d matches)" % (name, len(matches)),
                hint="use the long name, e.g. %s" % matches[0])
        resolved[matches[0]] = triple
    return resolved


def pose_skeleton(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    root_long = _require_joint(cmds, params.get("root"))
    space = params.get("space", "local")
    if space != "local":
        raise HandlerError(
            "space %r is not supported" % (space,),
            hint="a pose is per-joint LOCAL euler rotations in degrees - the "
                 "same currency a phase-6 clip keys. Reaching a world-space "
                 "target is phase 3's pose_ik")
    joints = _hierarchy_joints(cmds, root_long)
    resolved = _resolve_rotations(cmds, joints, params.get("rotations"))

    session.auto_checkpoint("pose_skeleton")
    meshes = _bound_meshes(cmds, set(joints))
    before = {m: sculpt.vertex_positions(cmds, m) for m in meshes}

    for joint, triple in resolved.items():
        cmds.setAttr(joint + ".rotate",
                     units.degrees_to_ui(cmds, triple[0]),
                     units.degrees_to_ui(cmds, triple[1]),
                     units.degrees_to_ui(cmds, triple[2]))

    joints_out = [{
        "name": j,
        "world_position": [float(v) for v in cmds.xform(
            j, query=True, worldSpace=True, translation=True)],
    } for j in joints]

    max_disp = 0.0
    displaced = 0
    for mesh in meshes:
        after = sculpt.vertex_positions(cmds, mesh)
        max_disp = max(max_disp,
                       sculpt_math.max_displacement(before[mesh], after))
        displaced += rigmath.displaced_count(before[mesh], after)

    warnings: List[str] = []
    if not meshes:
        warnings.append(
            "no skinned mesh is bound to this skeleton - the pose moved bare "
            "joints only; bind_skin first if deformation was the point")
    else:
        extent = max(sculpt_math.bbox_extent(before[m]) for m in meshes)
        if extent > 0 and max_disp < extent * NOOP_POSE_RATIO:
            warnings.append(
                "the pose moved the mesh by %.4g against a size of %.4g - "
                "near-zero deformation usually means the rotations landed on "
                "joints that own no vertices" % (max_disp, extent))

    return {"applied": len(resolved), "joints": joints_out,
            "max_displacement": max_disp, "displaced_vertices": displaced,
            "warnings": warnings}


def reset_pose(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    root_long = _require_joint(cmds, params.get("root"))
    joints = _hierarchy_joints(cmds, root_long)

    session.auto_checkpoint("reset_pose")
    meshes = _bound_meshes(cmds, set(joints))
    before = {m: sculpt.vertex_positions(cmds, m) for m in meshes}

    warnings: List[str] = []
    poses = cmds.dagPose(root_long, query=True, bindPose=True) or []
    if poses:
        cmds.dagPose(poses[0], restore=True, g=True)
        if len(poses) > 1:
            warnings.append("%d bind poses exist; restored %s"
                            % (len(poses), poses[0]))
    else:
        for joint in joints:
            cmds.setAttr(joint + ".rotate", 0.0, 0.0, 0.0)
        warnings.append(
            "no bind pose exists (nothing is bound); rotations zeroed, which "
            "is the create_skeleton rest pose")

    max_disp = 0.0
    for mesh in meshes:
        after = sculpt.vertex_positions(cmds, mesh)
        max_disp = max(max_disp,
                       sculpt_math.max_displacement(before[mesh], after))
    return {"reset": True, "max_displacement": max_disp, "warnings": warnings}
```

- [ ] **Step 4: Run headless** — `uv run pytest tests/test_rigging.py -q` → PASS

- [ ] **Step 5: Write the failing mayapy tests** (append):

```python
class TestPoseSkeletonInMaya:
    def _bound_serpent(self, cmds, rigging, name="ptube", n=4, height=4.0):
        mesh = _serpent_cylinder(cmds, name=name, height=height)
        step = height / (n - 1)
        skel = rigging.create_skeleton({
            "chain": [[0, i * step, 0] for i in range(n)],
            "chain_prefix": name + "_j"})
        rigging.bind_skin({"mesh": mesh, "root": skel["root"]})
        return mesh, skel

    def test_a_bend_actually_moves_the_mesh(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        mesh, skel = self._bound_serpent(cmds, rigging)
        mid = skel["joints"][1]["name"]
        out = rigging.pose_skeleton({"root": skel["root"],
                                     "rotations": {mid: [0, 0, 90]}})
        # Everything above the mid joint (~2/3 of a 4-unit tube) swings a
        # quarter turn; the tip alone travels ~sqrt(2)*2.67/... - pin loosely,
        # the exact arc is the live gate's job.
        assert out["max_displacement"] > 1.0
        assert out["displaced_vertices"] > 0
        assert out["warnings"] == []
        # Joint world positions are reported for every joint, measured.
        tip = out["joints"][-1]["world_position"]
        assert tip[0] != pytest.approx(0.0, abs=1e-3)  # swung off the axis

    def test_rotations_mean_degrees_whatever_the_scene_unit_says(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        mesh, skel = self._bound_serpent(cmds, rigging, name="rtube")
        mid = skel["joints"][1]["name"]
        cmds.currentUnit(angle="rad")
        try:
            out = rigging.pose_skeleton({"root": skel["root"],
                                         "rotations": {mid: [0, 0, 90]}})
        finally:
            cmds.currentUnit(angle="deg")
        rz = cmds.getAttr(mid + ".rotateZ")  # queried in deg now
        assert rz == pytest.approx(90.0, abs=1e-4)
        assert out["max_displacement"] > 1.0

    def test_reset_pose_returns_to_bind_within_tolerance(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging, sculpt

        mesh, skel = self._bound_serpent(cmds, rigging, name="ztube")
        bind_positions = sculpt.vertex_positions(cmds, mesh)
        mid = skel["joints"][1]["name"]
        rigging.pose_skeleton({"root": skel["root"],
                               "rotations": {mid: [0, 0, 90]}})
        out = rigging.reset_pose({"root": skel["root"]})
        assert out["max_displacement"] > 1.0  # it undid a real pose
        from maya_plugin.handlers import sculpt_math
        assert sculpt_math.max_displacement(
            bind_positions, sculpt.vertex_positions(cmds, mesh)) < 1e-4

    def test_a_pose_on_an_empty_joint_warns_of_near_zero_motion(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        # Root joint far below the tube: bind gives it ~nothing.
        mesh = _serpent_cylinder(cmds, name="wtube")
        skel = rigging.create_skeleton({
            "chain": [[0, -50, 0], [0, -49, 0], [0, 2, 0], [0, 4, 0]],
            "chain_prefix": "w_j"})
        rigging.bind_skin({"mesh": mesh, "root": skel["root"]})
        out = rigging.pose_skeleton({
            "root": skel["root"],
            "rotations": {skel["joints"][0]["name"]: [0, 0, 1]}})
        # Whatever it measured is reported; if it moved almost nothing the
        # warning names the cause.
        if out["max_displacement"] < 0.05:
            assert any("near-zero" in w for w in out["warnings"])
```

- [ ] **Step 6: Run mayapy** — `E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -k "PoseSkeleton or ResetPose" -q` → PASS. Then the full mayapy suite: `E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q` → all green.

- [ ] **Step 7: Commit**

```bash
git add maya_plugin/handlers/rigging.py tests/test_rigging.py tests/test_handlers_mayapy.py
git commit -m "feat(#602): pose_skeleton/reset_pose - degree poses with vertex-measured displacement"
```

---

### Task 7: wire the four commands through the dispatcher and MCP server

**Files:**
- Modify: `maya_plugin/maya_mcp_plugin.py` (`_build_handlers`, handler import list)
- Modify: `src/maya_mcp/schemas.py`
- Modify: `src/maya_mcp/server.py`
- Test: `tests/test_server_tools.py`

**Interfaces:**
- Consumes: handlers from Tasks 4–6.
- Produces: plugin commands `create_skeleton`, `bind_skin`, `pose_skeleton`, `reset_pose`; MCP tools `maya_create_skeleton`, `maya_bind_skin`, `maya_pose_skeleton`, `maya_reset_pose`; schemas `SkeletonJoint`, `CreateSkeletonResult`, `SkinJointStats`, `BindSkinResult`, `PosedJoint`, `PoseSkeletonResult`, `ResetPoseResult`. Total registered tools: **45**.

- [ ] **Step 1: Write the failing tests.** In `tests/test_server_tools.py::TestRegistration::test_session_tools_registered`, add the four names to the expected set. Append marshaling tests (follow the file's FakeConn pattern):

```python
class TestRiggingTools:
    def test_create_skeleton_marshals_the_chain_form(self):
        conn = FakeConn(responses={"create_skeleton": {
            "root": "|s_01",
            "joints": [{"name": "|s_01", "position": [0, 0, 0],
                        "parent": None, "orient": [0, 0, 0]}],
            "warnings": []}})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_create_skeleton", {
            "chain": [[0, 0, 0], [0, 1, 0]], "chain_prefix": "s"}))
        assert conn.calls[0]["cmd"] == "create_skeleton"
        assert conn.calls[0]["params"]["chain"] == [[0, 0, 0], [0, 1, 0]]

    def test_bind_skin_defaults_travel(self):
        conn = FakeConn(responses={"bind_skin": {
            "mesh": "|m", "root": "|r", "skin_cluster": "mSkin",
            "influences": ["|r"], "unweighted_vertices": 0,
            "max_influences_exceeded": 0,
            "per_joint": [{"joint": "|r", "vertices": 8, "mean_weight": 1.0}],
            "warnings": []}})
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool("maya_bind_skin", {"mesh": "m", "root": "r"}))
        params = conn.calls[0]["params"]
        assert params["max_influences"] == 4
        assert params["method"] == "closestDistance"

    def test_pose_and_reset_round_trip(self):
        conn = FakeConn(responses={
            "pose_skeleton": {"applied": 1, "joints": [],
                              "max_displacement": 0.5,
                              "displaced_vertices": 12, "warnings": []},
            "reset_pose": {"reset": True, "max_displacement": 0.5,
                           "warnings": []}})
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool("maya_pose_skeleton", {
            "root": "r", "rotations": {"a": [0, 0, 10]}}))
        run(mcp.call_tool("maya_reset_pose", {"root": "r"}))
        assert [c["cmd"] for c in conn.calls] == ["pose_skeleton", "reset_pose"]
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_server_tools.py -q` → FAIL

- [ ] **Step 3: Implement.**

`maya_mcp_plugin.py`: add `rigging` to the `from .handlers import (...)` list; add to `_build_handlers()`:

```python
        "create_skeleton": rigging.create_skeleton,
        "bind_skin": rigging.bind_skin,
        "pose_skeleton": rigging.pose_skeleton,
        "reset_pose": rigging.reset_pose,
```

`schemas.py` (append, following the file's Field-description style):

```python
class SkeletonJoint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="Canonical long name of the created joint.")
    position: List[float] = Field(
        description="MEASURED world position after creation, scene units.")
    parent: Optional[str] = None
    orient: List[float] = Field(
        description=(
            "The jointOrient that actually landed, in DEGREES - the default "
            "aims X at the first child, and orientation is where every rig "
            "surprise lives, so it is always reported."))


class CreateSkeletonResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    root: str
    joints: List[SkeletonJoint]
    warnings: List[str] = Field(default_factory=list)


class SkinJointStats(BaseModel):
    model_config = ConfigDict(extra="ignore")

    joint: str
    vertices: int = Field(description="Vertices this joint meaningfully holds.")
    mean_weight: float


class BindSkinResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mesh: str
    root: str
    skin_cluster: str
    influences: List[str]
    unweighted_vertices: int = Field(
        description=(
            "Vertices NO joint owns. Must be 0 for a gate to pass: an "
            "unweighted vertex stays behind when the creature moves, and "
            "nothing looks wrong at bind time."))
    max_influences_exceeded: int
    per_joint: List[SkinJointStats] = Field(
        description=(
            "How to SEE a bind without a viewport: a joint owning zero "
            "vertices, or one joint owning everything, is a legible failure "
            "in these numbers."))
    warnings: List[str] = Field(default_factory=list)


class PosedJoint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    world_position: List[float]


class PoseSkeletonResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    applied: int
    joints: List[PosedJoint] = Field(
        description="Every joint under the root with its ACHIEVED world position.")
    max_displacement: float = Field(
        description=(
            "How far the furthest skinned vertex actually moved, measured "
            "before/after from vertices (never bounding boxes). Near zero "
            "against the mesh's size means the pose did nothing and warnings "
            "says why."))
    displaced_vertices: int
    warnings: List[str] = Field(default_factory=list)


class ResetPoseResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reset: bool
    max_displacement: float = Field(
        description="How far the mesh moved coming back to the bind pose.")
    warnings: List[str] = Field(default_factory=list)
```

`server.py`: add the four models to the schemas import; add after the export tool:

```python
    @mcp.tool(
        title="Create joint skeleton",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
    )
    def maya_create_skeleton(
        joints: Annotated[Optional[List[dict]], Field(description=(
            "Explicit form: one entry per joint - {name, position: [x,y,z] "
            "scene units, parent?: joint name from this same call, orient?: "
            "[x,y,z] DEGREES}. Any order; duplicate names, unknown parents "
            "and cycles refuse the whole call before any joint exists. "
            "Exactly one joint names no parent - a skeleton has one root."
        ))] = None,
        chain: Annotated[Optional[List[List[float]]], Field(description=(
            "Shorthand for one parented run: world positions, at least 2. "
            "Each joint parents to the previous; names are "
            "<chain_prefix>_01, _02, ... Pass either chain or joints, never "
            "both."
        ))] = None,
        chain_prefix: Annotated[str, Field(description=(
            "Name prefix for the chain shorthand."
        ))] = "joint",
        root_name: Annotated[Optional[str], Field(description=(
            "Renames the chain's first joint (the root)."
        ))] = None,
    ) -> CreateSkeletonResult:
        """Build a validated joint hierarchy in one call.

        Joint orientation defaults to Maya's own convention - X aims at the
        first child, leaves zeroed - and whatever orientation actually landed
        is reported per joint in degrees, because orientation is where every
        rig surprise lives. Returns canonical long names; use them as the
        keys of maya_pose_skeleton's rotations map."""
        params = {"joints": joints, "chain": chain}
        if chain is not None:
            params["chain_prefix"] = chain_prefix
            params["root_name"] = root_name
        return CreateSkeletonResult.model_validate(
            maya.request("create_skeleton", params, timeout_s=SCENE_TIMEOUT_S)
        )

    @mcp.tool(
        title="Bind mesh to skeleton",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
    )
    def maya_bind_skin(
        mesh: Annotated[str, Field(description="Mesh to bind (long name).")],
        root: Annotated[str, Field(description=(
            "Skeleton root joint from maya_create_skeleton. The whole "
            "hierarchy under it becomes influences."
        ))],
        max_influences: Annotated[int, Field(ge=1, le=8, description=(
            "Joints allowed per vertex. 4 is the game-engine convention."
        ))] = 4,
        method: Annotated[
            Literal["closestDistance", "heatMap", "geodesicVoxel"],
            Field(description=(
                "Initial weighting. closestDistance is robust everywhere; "
                "heatMap follows the surface (fails on non-manifold meshes); "
                "geodesicVoxel handles overlapping shells."
            )),
        ] = "closestDistance",
    ) -> BindSkinResult:
        """Bind a mesh to a skeleton and MEASURE the result.

        unweighted_vertices must be 0 for a deliverable bind - a vertex no
        joint owns stays behind when the creature moves, and nothing looks
        wrong at bind time. per_joint says which joints own which share of
        the mesh, which is how to see a bind without a viewport. Re-binding
        an already-bound mesh is refused (stacked skinClusters make weights
        unexplainable) - unbind first, or restore the pre-bind checkpoint."""
        return BindSkinResult.model_validate(
            maya.request(
                "bind_skin",
                {"mesh": mesh, "root": root, "max_influences": max_influences,
                 "method": method},
                timeout_s=BOOL_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Pose skeleton",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=True
        ),
    )
    def maya_pose_skeleton(
        root: Annotated[str, Field(description="Skeleton root joint.")],
        rotations: Annotated[dict, Field(description=(
            "Map of joint name to [rx, ry, rz] local euler DEGREES - absolute "
            "values, not deltas, so re-applying a pose is idempotent. This "
            "map IS the pose currency: phase-3 IK bakes into it and a "
            "phase-6 clip keys it."
        ))],
    ) -> PoseSkeletonResult:
        """Apply per-joint local rotations and MEASURE what moved.

        Reports every joint's achieved world position and the bound mesh's
        max vertex displacement (vertices, never bounding boxes). A pose
        whose displacement is near zero against the mesh's size warns
        loudly - rotations that land on joints owning no vertices look
        exactly like success otherwise."""
        return PoseSkeletonResult.model_validate(
            maya.request(
                "pose_skeleton",
                {"root": root, "rotations": rotations, "space": "local"},
                timeout_s=BOOL_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Reset to bind pose",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=True
        ),
    )
    def maya_reset_pose(
        root: Annotated[str, Field(description="Skeleton root joint.")],
    ) -> ResetPoseResult:
        """Return a skeleton to its bind pose.

        Every measurement and every export must happen from a KNOWN pose;
        'whatever the last test left behind' is not a bind pose. Unbound
        skeletons have no bind pose - rotations are zeroed (the
        create_skeleton rest pose) and a warning says so."""
        return ResetPoseResult.model_validate(
            maya.request("reset_pose", {"root": root}, timeout_s=BOOL_TIMEOUT_S)
        )
```

- [ ] **Step 4: Run** — `uv run pytest tests/test_server_tools.py tests/test_dispatcher.py -q` → PASS, then full `uv run pytest -q` → green.

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/maya_mcp_plugin.py src/maya_mcp/schemas.py src/maya_mcp/server.py tests/test_server_tools.py
git commit -m "feat(#602): register the four rigging commands - 45 tools"
```

---

### Task 8: fbxbytes reads skin records

**Files:**
- Modify: `maya_plugin/handlers/fbxbytes.py`
- Create: `evals/make_skin_fixture.py`; generated+committed: `evals/rigging_fixtures/skinned_cylinder.fbx`
- Test: `tests/test_fbxbytes.py` (append)

**Interfaces:**
- Produces: `FbxFacts.skins: dict` (skin uid → `{"geometry": uid|None, "clusters": [uid]}`), `FbxFacts.clusters: dict` (cluster uid → `{"indexes": tuple, "weights": tuple, "model": uid|None}`), `FbxFacts.bind_pose_count: int`, and `skin_facts(facts, tol=1e-3) -> {"deformers", "clusters", "influenced_models", "bind_pose_present", "max_weight_sum_error", "unweighted_file_vertices", "unavailable_reason"}` (`max_weight_sum_error` is `None` + reason when unreadable — the #645 rule).

- [ ] **Step 1: Generate the fixture.** Write `evals/make_skin_fixture.py`:

```python
"""Generate evals/rigging_fixtures/skinned_cylinder.fbx - run ONCE under
mayapy, commit the artifact. The headless fbxbytes tests pin their numbers
against this file the way test_fbxbytes.py pins the clock tower.

    E:\\Autodesk\\Maya2027\\bin\\mayapy.exe evals/make_skin_fixture.py

3-joint chain through a 2-unit cylinder, closestDistance bind, exported with
skins through the SAME handler the tool uses - so the fixture is the tool's
own output, not a hand-made file.
"""
import os
import sys

import maya.standalone

maya.standalone.initialize(name="python")
import maya.cmds as cmds  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from maya_plugin.handlers import export, rigging  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "rigging_fixtures")
os.makedirs(OUT_DIR, exist_ok=True)

cmds.file(new=True, force=True)
mesh = cmds.polyCylinder(name="fixture_tube", radius=0.3, height=2.0,
                         subdivisionsY=6, ch=False)[0]
cmds.xform(mesh, worldSpace=True, translation=[0, 1.0, 0])
skel = rigging.create_skeleton({
    "chain": [[0, 0, 0], [0, 1, 0], [0, 2, 0]], "chain_prefix": "fix"})
bind = rigging.bind_skin({"mesh": "|fixture_tube", "root": skel["root"]})
assert bind["unweighted_vertices"] == 0, bind

result = export.export_fbx({
    "path": os.path.join(OUT_DIR, "skinned_cylinder.fbx").replace("\\", "/"),
    "metres_per_unit": 1.0,
    "include_skins": True,
})
print("wrote", result["path"], result["bytes"], "bytes")
print("skin block:", result["skin"])
maya.standalone.uninitialize()
```

**Ordering note:** this script needs Task 9's `include_skins`. Do Tasks 8 and 9 as one TDD loop: write the fbxbytes reader + tests first with the fixture step deferred (Step 4 below runs after Task 9's Step 3 lands the export flag). If executing task-by-task with subagents, hand Tasks 8+9 to one subagent.

- [ ] **Step 2: Write the failing headless tests** (append to `tests/test_fbxbytes.py`):

```python
class TestSkinRecordMath:
    """skin_facts on synthetic facts - the algebra, no file needed."""

    def _facts(self, indexes, weights, verts=4):
        facts = FbxFacts(version=7500)
        facts.geometries = {10: tuple([0.0] * (verts * 3))}
        facts.skins = {20: {"geometry": 10, "clusters": [30]}}
        facts.clusters = {30: {"indexes": tuple(indexes),
                               "weights": tuple(weights), "model": 40}}
        facts.bind_pose_count = 1
        return facts

    def test_full_ownership_sums_to_one(self):
        facts = self._facts([0, 1, 2, 3], [1.0, 1.0, 1.0, 1.0])
        out = fbxbytes.skin_facts(facts)
        assert out["deformers"] == 1
        assert out["clusters"] == 1
        assert out["influenced_models"] == 1
        assert out["bind_pose_present"] is True
        assert out["max_weight_sum_error"] == pytest.approx(0.0)
        assert out["unweighted_file_vertices"] == 0
        assert out["unavailable_reason"] is None

    def test_a_vertex_with_no_weight_is_counted(self):
        facts = self._facts([0, 1, 2], [1.0, 1.0, 1.0])
        assert fbxbytes.skin_facts(facts)["unweighted_file_vertices"] == 1

    def test_an_unnormalised_sum_is_an_error_magnitude(self):
        facts = self._facts([0, 1, 2, 3], [1.0, 1.0, 1.0, 0.7])
        assert fbxbytes.skin_facts(facts)["max_weight_sum_error"] == pytest.approx(0.3)

    def test_mismatched_arrays_null_the_number_with_a_reason(self):
        facts = self._facts([0, 1], [1.0])
        out = fbxbytes.skin_facts(facts)
        assert out["max_weight_sum_error"] is None
        assert "indexes" in out["unavailable_reason"]

    def test_a_file_with_no_skins_reads_as_zero_not_error(self):
        out = fbxbytes.skin_facts(FbxFacts(version=7500))
        assert out["deformers"] == 0
        assert out["bind_pose_present"] is False


class TestSkinRecordsFromTheCommittedArtifact:
    def _facts(self):
        return fbxbytes.read_fbx(os.path.join(
            REPO, "evals", "rigging_fixtures", "skinned_cylinder.fbx"))

    def test_the_skin_and_its_clusters_are_found(self):
        facts = self._facts()
        assert len(facts.skins) == 1
        assert len(facts.clusters) == 3          # one per joint
        skin = next(iter(facts.skins.values()))
        assert skin["geometry"] in facts.geometries
        assert sorted(skin["clusters"]) == sorted(facts.clusters)

    def test_every_cluster_links_a_limb_model(self):
        facts = self._facts()
        limb_uids = {n.uid for n in facts.nodes if n.kind == "LimbNode"}
        assert len(limb_uids) == 3
        assert {c["model"] for c in facts.clusters.values()} == limb_uids

    def test_weight_sums_read_from_the_bytes(self):
        out = fbxbytes.skin_facts(self._facts())
        assert out["bind_pose_present"] is True
        assert out["unweighted_file_vertices"] == 0
        assert out["max_weight_sum_error"] < 1e-3

    def test_joint_hierarchy_survives_the_extra_connections(self):
        # The Model->Cluster connection must not clobber the Model->Model
        # parent link - the regression the wiring rework risks.
        facts = self._facts()
        limbs = [n for n in facts.nodes if n.kind == "LimbNode"]
        parents = [n.parent for n in limbs]
        assert sum(1 for p in parents if p is None) <= 1
        assert sum(1 for p in parents if p is not None) >= 2

    def test_the_unskinned_golem_still_reads_clean(self):
        facts = fbxbytes.read_fbx(
            os.path.join(REPO, "evals", "golem_delivery", "golem.fbx"))
        assert facts.skins == {}
        assert fbxbytes.skin_facts(facts)["deformers"] == 0
```

- [ ] **Step 3: Implement the reader changes** in `fbxbytes.py`:

1. `FbxFacts` gains:

```python
    # Skin records (#602 phase 1). skins: deformer uid -> {"geometry": uid,
    # "clusters": [uid]}; clusters: uid -> {"indexes", "weights", "model"}.
    skins: dict = field(default_factory=dict)
    clusters: dict = field(default_factory=dict)
    bind_pose_count: int = 0
```

2. `prop` gains an int-array path, gated by the caller so PolygonVertexIndex arrays are NOT decoded (a 4M-face kit would balloon):

```python
    def prop(pos, want_ints=False):
        ...
        if code in _ARRAYS:
            length, encoding, comp = struct.unpack_from("<III", data, pos)
            pos += 12
            payload = data[pos:pos + comp]
            pos += comp
            if code == b"d" or (want_ints and code == b"i"):
                raw = zlib.decompress(payload) if encoding == 1 else payload
                fmt = ("<%dd" if code == b"d" else "<%di") % length
                return struct.unpack(fmt, raw), pos
            return None, pos
```

and in `walk`, the property loop becomes `val, pos = prop(pos, want_ints=(name == "Indexes"))`.

3. In `walk`, after the existing `elif name == "P"` block's chain, extend the record handling (`child = node` section):

```python
            child = node
            if name == "Model":
                ...  # unchanged
            elif name == "Geometry":
                ...  # unchanged
            elif name == "Deformer":
                uid = values[0] if values and isinstance(values[0], int) else None
                strs = [v for v in values if isinstance(v, str)]
                klass = strs[-1] if strs else ""
                if uid is not None and klass == "Skin":
                    facts.skins[uid] = {"geometry": None, "clusters": []}
                    child = ("skin", uid)
                elif uid is not None and klass == "Cluster":
                    facts.clusters[uid] = {"indexes": (), "weights": (),
                                           "model": None}
                    child = ("cluster", uid)
            elif name == "Pose":
                strs = [v for v in values if isinstance(v, str)]
                if strs and strs[-1] == "BindPose":
                    facts.bind_pose_count += 1
            elif (name == "Indexes" and isinstance(node, tuple)
                    and node[0] == "cluster" and values
                    and isinstance(values[0], tuple)):
                facts.clusters[node[1]]["indexes"] = values[0]
            elif (name == "Weights" and isinstance(node, tuple)
                    and node[0] == "cluster" and values
                    and isinstance(values[0], tuple)):
                facts.clusters[node[1]]["weights"] = values[0]
```

4. Rework the connection pass — the current `by_uid[child].parent = parent if parent in by_uid else None` would let a Model→Cluster connection CLOBBER the real Model→Model parent depending on record order:

```python
    by_uid = {n.uid: n for n in facts.nodes if n.uid is not None}
    for child, parent in _connections:
        if child in by_uid and (parent in by_uid or parent == 0):
            # 0 is the scene root: an explicit "no parent", kept distinct
            # from connections into non-Model records (clusters, materials),
            # which must not null a real parent.
            by_uid[child].parent = parent if parent in by_uid else None
        elif child in by_uid and parent in facts.clusters:
            facts.clusters[parent]["model"] = child
        elif child in facts.geometries and parent in by_uid:
            by_uid[parent].geometry = child
        elif child in facts.clusters and parent in facts.skins:
            facts.skins[parent]["clusters"].append(child)
        elif child in facts.skins and parent in facts.geometries:
            facts.skins[child]["geometry"] = parent
    return facts
```

5. Append `skin_facts`:

```python
def skin_facts(facts, tol=1e-3):
    """What the file's skin records actually hold. Reading, not policy.

    Weight sums are composed per vertex across every cluster of each skin; a
    correct bind normalises them to 1.0 in the file. max_weight_sum_error is
    measured over vertices carrying ANY weight; vertices carrying none are
    counted separately - the file-side image of bind_skin's
    unweighted_vertices gate. Anything this reader cannot verify goes out as
    None with a reason, never a plausible guess (#645).
    """
    influenced = {c["model"] for c in facts.clusters.values()
                  if c["model"] is not None}
    max_err = None
    unweighted = 0
    reasons = []
    for uid, skin in facts.skins.items():
        verts = facts.geometries.get(skin["geometry"])
        if not verts:
            reasons.append(
                "skin %d connects to no geometry this reader holds" % uid)
            continue
        num = len(verts) // 3
        sums = [0.0] * num
        readable = True
        for cluster_uid in skin["clusters"]:
            cluster = facts.clusters.get(cluster_uid) or {}
            idx = cluster.get("indexes") or ()
            wts = cluster.get("weights") or ()
            if len(idx) != len(wts):
                readable = False
                reasons.append(
                    "cluster %d holds %d indexes but %d weights"
                    % (cluster_uid, len(idx), len(wts)))
                continue
            for i, w in zip(idx, wts):
                if 0 <= i < num:
                    sums[i] += w
                else:
                    readable = False
                    reasons.append(
                        "cluster %d indexes vertex %d of %d"
                        % (cluster_uid, i, num))
                    break
        if not readable:
            continue
        for s in sums:
            if s <= tol:
                unweighted += 1
            else:
                err = abs(s - 1.0)
                if max_err is None or err > max_err:
                    max_err = err
    return {
        "deformers": len(facts.skins),
        "clusters": len(facts.clusters),
        "influenced_models": len(influenced),
        "bind_pose_present": facts.bind_pose_count > 0,
        "max_weight_sum_error": max_err,
        "unweighted_file_vertices": unweighted,
        "unavailable_reason": "; ".join(reasons) or None,
    }
```

- [ ] **Step 4: Generate and commit the fixture** (after Task 9 Step 3): run `E:\Autodesk\Maya2027\bin\mayapy.exe evals/make_skin_fixture.py`, confirm the printed skin block, `git add evals/rigging_fixtures/skinned_cylinder.fbx evals/make_skin_fixture.py`.

- [ ] **Step 5: Run** — `uv run pytest tests/test_fbxbytes.py -q` → PASS including the artifact class; full `uv run pytest -q` green (the connection rework must not move any existing number — the clock tower still reads 37.10, the golem 4.02173).

- [ ] **Step 6: Commit**

```bash
git add maya_plugin/handlers/fbxbytes.py tests/test_fbxbytes.py
git commit -m "feat(#602): fbxbytes reads skin deformers, cluster weights and BindPose"
```

---

### Task 9: `include_skins` on the export gate

**Files:**
- Modify: `maya_plugin/handlers/export.py`
- Modify: `src/maya_mcp/schemas.py` (`SkinFacts`, `ExportFbxResult.skin`), `src/maya_mcp/server.py` (`maya_export_fbx` param)
- Test: `tests/test_export_fbx.py`, `tests/test_server_tools.py`, `tests/test_handlers_mayapy.py` (append)

**Interfaces:**
- Consumes: `fbxbytes.skin_facts`, Task 8's records.
- Produces: `export_fbx` accepts `include_skins: bool = False`; result gains `"skin": dict | None`. Gate: with `include_skins=True`, zero skin deformers, a missing BindPose, unweighted file vertices, or weight sums off by > `1e-3` are violations (file deleted, target untouched). Joints (kind `LimbNode`) join the identity-scale gate. `FBX_SKINS_MEL: dict` holds the MEL switches.

- [ ] **Step 1: Write the failing headless tests** (append to `tests/test_export_fbx.py`, using its existing `_facts`/FakeCmds/FakeMel harness):

```python
def test_a_scaled_joint_is_a_violation():
    # A skinned joint's scale multiplies vertices without being the mesh's
    # ancestor, so LimbNodes are gated like meshes.
    facts = _facts(nodes=[FbxNode(name="hip", kind="LimbNode",
                                  scaling=(2.0, 2.0, 2.0))])
    assert any("hip" in v for v in export.gate_violations(facts))


def test_an_identity_joint_is_not():
    facts = _facts(nodes=[FbxNode(name="hip", kind="LimbNode")])
    assert export.gate_violations(facts) == []


def test_include_skins_must_be_a_bool(tmp_path):
    with pytest.raises(HandlerError, match="include_skins"):
        export._validate(_params(tmp_path, include_skins="yes"))


def test_skin_violations_compose(monkeypatch):
    # include_skins=true with no skin in the bytes is the false-green class.
    sfacts = {"deformers": 0, "clusters": 0, "influenced_models": 0,
              "bind_pose_present": False, "max_weight_sum_error": None,
              "unweighted_file_vertices": 0, "unavailable_reason": None}
    out = export.skin_violations(sfacts)
    assert any("no skin deformer" in v for v in out)


def test_a_good_skin_block_raises_nothing():
    sfacts = {"deformers": 1, "clusters": 3, "influenced_models": 3,
              "bind_pose_present": True, "max_weight_sum_error": 2e-7,
              "unweighted_file_vertices": 0, "unavailable_reason": None}
    assert export.skin_violations(sfacts) == []


def test_bad_sums_missing_bindpose_and_unweighted_all_fire():
    sfacts = {"deformers": 1, "clusters": 3, "influenced_models": 3,
              "bind_pose_present": False, "max_weight_sum_error": 0.4,
              "unweighted_file_vertices": 7, "unavailable_reason": None}
    out = export.skin_violations(sfacts)
    assert len(out) == 3
```

Also add an end-to-end fake test following `test_a_clean_export_reports_the_file_not_the_scene`: monkeypatch `fbxbytes.skin_facts` to a good block, call `export.export_fbx` with `include_skins=True`, assert the result carries `"skin"` and that FakeMel received the `FBXExportSkins -v true` statement; and the inverse (default call sends `-v false`, result `skin` is `None`).

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_export_fbx.py -q` → FAIL

- [ ] **Step 3: Implement** in `export.py`:

```python
# Skin export switches, both states explicit so FBXResetExport's defaults
# never decide it (the same determinism argument as FBX_SCENE_CONTENT_MEL).
# The True branch also turns input connections ON: export-selected walks
# input connections to find the skinCluster and its joints, and with the
# preamble's `-v false` the deformer records are silently absent - the
# mayapy test in tests/test_handlers_mayapy.py measures exactly this.
FBX_SKINS_MEL = {
    True: ("FBXExportInputConnections -v true", "FBXExportSkins -v true"),
    False: ("FBXExportSkins -v false",),
}

# A file-side weight sum further than this from 1.0 was not normalised by the
# exporter and will deform differently in every consumer.
WEIGHT_SUM_TOL = 1e-3


def skin_violations(sfacts) -> List[str]:
    """Ways the skin records break the include_skins contract."""
    out: List[str] = []
    if sfacts["deformers"] == 0:
        out.append(
            "include_skins=true but the file holds no skin deformer - "
            "nothing exported is bound, or the mesh went out without its "
            "skeleton")
        return out
    if not sfacts["bind_pose_present"]:
        out.append("the file holds no BindPose record")
    if sfacts["unweighted_file_vertices"]:
        out.append("%d file vertices carry no weight"
                   % sfacts["unweighted_file_vertices"])
    err = sfacts["max_weight_sum_error"]
    if err is not None and err > WEIGHT_SUM_TOL:
        out.append("per-vertex weight sums are off by up to %g" % err)
    if sfacts["unavailable_reason"]:
        out.append("skin records unreadable: %s" % sfacts["unavailable_reason"])
    return out
```

`_validate` gains (before the `nodes` block):

```python
    include_skins = params.get("include_skins", False)
    if not isinstance(include_skins, bool):
        raise HandlerError(
            "include_skins must be true or false, got %r" % (include_skins,),
            hint="true exports skinCluster deformers and the BindPose "
                 "alongside the mesh")
```

and returns `(path, nodes, include_skins)` (update the caller and the existing `_validate` tests' unpacking).

`_scale_reaches_vertices`: change the skip line to

```python
        if node.geometry is None and node.kind not in ("Mesh", "LimbNode"):
            continue
```

with a docstring line: *a skinned joint's scale multiplies vertices without being the mesh's ancestor, so LimbNodes gate like meshes (#602 P1).*

`export_fbx`: MEL loop becomes

```python
    for statement in (FBX_PREAMBLE_MEL + FBX_SCENE_CONTENT_MEL
                      + FBX_SKINS_MEL[include_skins]):
        mel.eval(statement)
```

After `facts = fbxbytes.read_fbx(tmp_path)`:

```python
    violations = gate_violations(facts)
    skin_block = None
    if include_skins:
        skin_block = fbxbytes.skin_facts(facts)
        violations += skin_violations(skin_block)
```

and extend the refusal hint when skin violations are present: append to the existing hint string `" For skin violations: the mesh must be bound (maya_bind_skin reported unweighted_vertices=0) and a selected export ('nodes') must list the skeleton root alongside the mesh."` The result dict gains `"skin": skin_block`.

`schemas.py`:

```python
class SkinFacts(BaseModel):
    """Skin records read back OUT OF THE FILE, never from the scene."""

    model_config = ConfigDict(extra="ignore")

    deformers: int = Field(description="SkinCluster deformer records.")
    clusters: int = Field(description="Per-joint cluster records.")
    influenced_models: int = Field(
        description="Distinct joint Models the clusters link.")
    bind_pose_present: bool
    max_weight_sum_error: Optional[float] = Field(
        default=None,
        description=(
            "Furthest any vertex's file-side weight sum sits from 1.0. Null "
            "when the records could not be read - see unavailable_reason, "
            "never a guess."))
    unweighted_file_vertices: int = 0
    unavailable_reason: Optional[str] = None
```

and `ExportFbxResult` gains:

```python
    skin: Optional[SkinFacts] = Field(
        default=None,
        description="Skin facts when include_skins=true; null otherwise.")
```

`server.py` `maya_export_fbx` gains:

```python
        include_skins: Annotated[bool, Field(description=(
            "Export skinCluster deformers and the BindPose with the mesh. "
            "The gate then also verifies, from the bytes: skin records "
            "present, per-vertex weight sums ~1.0, BindPose present, and "
            "identity scale on every joint. For a selected export, list the "
            "skeleton root in nodes alongside the mesh."
        ))] = False,
```

passed through in the request params. Add a `test_server_tools.py` marshaling assertion (`include_skins` default False travels; explicit True travels).

- [ ] **Step 4: Run headless** — `uv run pytest tests/test_export_fbx.py tests/test_server_tools.py -q` → PASS. Now run Task 8 Step 4 (generate + commit the fixture), then `uv run pytest -q` → all green.

- [ ] **Step 5: Write the failing mayapy tests** (append):

```python
class TestExportSkinsInMaya:
    def _bound(self, cmds, rigging, name):
        mesh = _serpent_cylinder(cmds, name=name, height=2.0, sections=6)
        skel = rigging.create_skeleton({
            "chain": [[0, 0, 0], [0, 1, 0], [0, 2, 0]],
            "chain_prefix": name + "_j"})
        rigging.bind_skin({"mesh": mesh, "root": skel["root"]})
        return mesh, skel

    def test_a_skinned_selected_export_carries_the_records(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import export, fbxbytes, rigging

        mesh, skel = self._bound(cmds, rigging, "xtube")
        out = export.export_fbx({
            "path": str(tmp_path / "skinned.fbx").replace("\\", "/"),
            "metres_per_unit": 1.0,
            "nodes": [mesh, skel["root"]],
            "include_skins": True,
        })
        assert out["skin"]["deformers"] == 1
        assert out["skin"]["clusters"] == 3
        assert out["skin"]["bind_pose_present"] is True
        assert out["skin"]["unweighted_file_vertices"] == 0
        assert out["skin"]["max_weight_sum_error"] < 1e-3
        facts = fbxbytes.read_fbx(out["path"])
        assert {n.kind for n in facts.nodes} >= {"Mesh", "LimbNode"}

    def test_default_export_stays_skinless(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import export, fbxbytes, rigging

        mesh, skel = self._bound(cmds, rigging, "ytube")
        out = export.export_fbx({
            "path": str(tmp_path / "plain.fbx").replace("\\", "/"),
            "metres_per_unit": 1.0,
            "nodes": [mesh],
        })
        assert out["skin"] is None
        assert fbxbytes.read_fbx(out["path"]).skins == {}

    def test_include_skins_without_a_bound_mesh_is_refused(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import export

        cube = cmds.polyCube(name="dryCube", ch=False)[0]
        with pytest.raises(HandlerError, match="no skin deformer"):
            export.export_fbx({
                "path": str(tmp_path / "dry.fbx").replace("\\", "/"),
                "metres_per_unit": 1.0,
                "nodes": [cube],
                "include_skins": True,
            })
        assert not (tmp_path / "dry.fbx").exists()
```

- [ ] **Step 6: Run mayapy** — `E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -k ExportSkins -q`. **This step is a measurement**: if the first test finds no skin records with `FBXExportInputConnections -v true`, iterate on `FBX_SKINS_MEL[True]` (candidates, in order: add the joints explicitly to the selection inside the handler when `include_skins` — i.e. document that `nodes` must include the root, which the test already does; try `FBXExportSkins` alone). Whatever combination the test proves goes in with a comment stating it was measured here, per the module's own rule. Then the full mayapy suite → green.

- [ ] **Step 7: Commit**

```bash
git add maya_plugin/handlers/export.py src/maya_mcp/schemas.py src/maya_mcp/server.py tests/test_export_fbx.py tests/test_server_tools.py tests/test_handlers_mayapy.py
git commit -m "feat(#602): export gains include_skins - skin records gated in the bytes"
```

---

### Task 10: the serpent live gate

**Files:**
- Create: `evals/serpent_live.py`; outputs land in `evals/serpent_live/` (renders, `serpent.fbx`, `baseline.json`)

**Interfaces:**
- Consumes: the four commands + `export_fbx` over TCP via `evals/live_call.py`; `fbxbytes` imported headlessly for the byte checks.
- Produces: PASS/FAIL lines (the `export_live.py` `check()` pattern), renders for pixel judgment, `baseline.json` for the consumer-side import ticket.

- [ ] **Step 1: Write `evals/serpent_live.py`.** Structure (follow `export_live.py`'s conventions — `check()`, `CHECKS`, handshake via `live_call`):

```python
"""Phase-1 gate for #602: the serpent. A 12-joint chain through one mesh -
the purest deformation test, one variable, fails legibly (a rigid-chunk
serpent reads as a bike chain).

Measured checks (this script) + judged renders (written for pixel judgment):

    1  build serpent mesh + 12-joint chain + bind      unweighted == 0,
                                                       every joint owns verts
    2  bend 90 degrees distributed along the chain     tip travels the arc the
                                                       chain geometry implies
                                                       (FK computed here),
                                                       max_displacement in a
                                                       window around it
    3  tearing detector                                posed mesh stays ONE
                                                       shell; no edge longer
                                                       than 1.5x bind length
    4  renders (front/side, posed)                     JUDGED - not scripted
    5  reset_pose                                      mesh back to bind
    6  export include_skins                            skin block green; byte
                                                       re-read agrees; baseline
                                                       recorded for consumer

DESTRUCTIVE: calls new_scene. Port 9878, the agent-launched Maya, per the
two-Maya policy - never point this at the user's 9877.
"""
```

Key content (write in full):

- `PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))`
- Serpent: `create_primitive` cylinder, `name="serpent"`, `scale=[0.3, 3.6, 0.3]`, `divisions=8`, translated so it stands on y=0..3.6 (use `translate=[0, 1.8, 0]`).
- Chain: 12 joints `[[0, 3.6 * i / 11.0, 0] for i in range(12)]`, `chain_prefix="serp"`.
- Bind: `bind_skin(mesh, root)`; check `unweighted_vertices == 0` and `all(p["vertices"] > 0)`.
- Pose: `rotations = {joints[i]: [0, 0, 90.0 / 11.0] for i in 1..11}` (every non-root joint bends the same increment about Z — local X runs along the chain after default orient, so local Z bends it; if the measured tip disagrees in DIRECTION, the eval prints the achieved positions — trust the measurement and adjust the axis, with a comment).
- FK expectation computed in-script (pure math): segment length `L = 3.6/11`; cumulative angle `theta_k = k * (90/11)` degrees for segment k = 1..11; expected tip = `sum(L * sin(theta))` on x (or the measured swing axis), `L * (1 + sum(cos))` on y. Check reported tip `world_position` within 2% of expected, and `max_displacement` within `[0.9, 1.3] x |tip_bind - tip_posed|`.
- Tearing: via `execute_python` — one code blob that walks `MItMeshEdge` of the serpent, returns `{"shells": cmds.polyEvaluate(shell=True), "max_edge": ...}`; run once at bind, once posed; check `shells == 1` and `max_edge_posed <= 1.5 * max_edge_bind`.
- Renders: `render_scene` front + side at the posed state into `evals/serpent_live/` (name files `serpent_posed_front.png`, `serpent_posed_side.png`); print their paths under a `JUDGE:` banner.
- `reset_pose`: check `max_displacement` within 10% of the pose's, then re-measure tip via `execute_python` — back within 1e-3.
- Export: `export_fbx(path=evals/serpent_live/serpent.fbx, metres_per_unit=1.0, include_skins=True)` (whole scene: fresh scene holds only serpent + skeleton). Check the `skin` block: `deformers == 1`, `clusters == 12`, `bind_pose_present`, `unweighted_file_vertices == 0`, `max_weight_sum_error < 1e-3`.
- Byte re-read: `fbxbytes.read_fbx` the artifact locally; assert the same numbers from the bytes plus 12 `LimbNode` Models; write `baseline.json`:

```python
baseline = {
    "fbx": "serpent.fbx",
    "bytes": result["bytes"],
    "joint_models": 12,
    "skin": result["skin"],
    "world_bounds_min": result["world_bounds_min"],
    "world_bounds_max": result["world_bounds_max"],
    "bend_test": {"rotations_deg": rotations, "expected_tip": expected_tip,
                  "achieved_tip": achieved_tip},
}
```

- Exit non-zero if any check failed (`sys.exit(0 if all(...) else 1)`).

- [ ] **Step 2: Deploy and launch the agent Maya.**

```bash
python maya_plugin/install.py --yes
```

Then launch with a **neutral cwd** and port 9878 (PowerShell):

```powershell
$env:MAYA_MCP_PORT = "9878"
Start-Process "E:\Autodesk\Maya2027\bin\maya.exe" -WorkingDirectory "C:\Users\plotk"
```

Note the pid (`Get-Process maya | Select-Object Id,StartTime`), set `MAYA_MCP_EXPECT_PID` to it, wait for the port, and trust the eval's handshake output: it must report that pid and a `package_dir` under `Documents\maya\scripts` (not the repo — #604). The deployed copy is shared machine-wide with the demigul-art agent; this deploy is additive (new commands only), but say so in the session log.

- [ ] **Step 3: Run the gate.**

```bash
uv run python evals/serpent_live.py
```

Expected: every `PASS`, renders written. **Look at the renders** (Read the PNGs): the posed serpent must read as one continuous curved body — the bike-chain read (faceted rigid segments, pinched or torn hips between joints) is a FAIL even with green numbers. Record the judgment in the session.

- [ ] **Step 4: Kill the agent Maya** (`taskkill /F /T /PID <pid>` — then verify the port actually released, a kill is a claim), and commit:

```bash
git add evals/serpent_live.py evals/serpent_live/
git commit -m "feat(#602): serpent live gate - measured bend, tearing detector, skinned export baseline"
```

---

### Task 11: docs, ticket, and finish

**Files:**
- Modify: `docs/protocol.md` (four command entries + `include_skins` on export, following the file's existing per-command format)
- Modify: `docs/design.md` (the deferred-rigging line — point it at `docs/superpowers/specs/2026-08-19-rigging-surface-design.md`)

- [ ] **Step 1: Documentation.** Protocol entries state: pose currency (per-joint local euler degrees), the unweighted==0 gate meaning, the re-bind refusal, reset-to-known-pose rationale, and `include_skins`' byte assertions. Keep each to the length of the neighboring entries.

- [ ] **Step 2: Full verification** (superpowers:verification-before-completion): `uv run pytest -q` (expect ~1050+, all green), `E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q` (expect ~105+, all green), `uv run python evals/serpent_live.py` output already recorded. Commit docs.

```bash
git add docs/protocol.md docs/design.md
git commit -m "docs(#602): protocol entries for the rigging surface, design pointer to the spec"
```

- [ ] **Step 3: Redmine** (tracking-work-in-redmine): one `update_issue` on #602 — notes: commands shipped, gate numbers (unweighted count, bend displacement vs expected arc, skin byte facts), eval/baseline paths; status stays **In Progress** until merge, then **Resolved** at Step 4.

- [ ] **Step 4: Finish the branch** (superpowers:finishing-a-development-branch — the merge decision is the user's). **The day this merges**, per the spec's consumer-honesty rule, file TWO tickets in Redmine project 35:
  1. **Consumer-side serpent import** (the #647 shape): import `evals/serpent_live/serpent.fbx` somewhere real, measure bind pose, bone count (12), and deformation at a pose; compare against `evals/serpent_live/baseline.json`.
  2. **Phase 2 — weights craft + the humanoid**: scope is the spec's Phase 2 section (mirror/smooth/region/report, judged humanoid, the `preset="biped"` open question), refined by what this phase learned.

---

## Self-Review (done at planning time)

- **Spec coverage:** create_skeleton (T1/T4), bind_skin (T2/T5), pose/reset (T6), wiring (T7), byte reader P1 assertions — Deformer/Cluster records, weight sums, LimbNode scale gate, BindPose (T8/T9), serpent gate steps 1–5 incl. arc window, tearing detector, judged render, export + baseline (T10), consumer ticket at merge + phase-2 ticket (T11). Degrees/measured-numbers/warnings/checkpoint conventions are in every handler.
- **Known decision points left to measurement (deliberate, marked):** the exact MEL switch set for skinned selected exports (T9 S6); the serpent's bend axis sign (T10 S1); Maya's leaf-orient behavior (T4 S6). Each has a written procedure, not a TBD.
- **Type consistency:** `resolve_joints` output feeds `create_skeleton` directly; `weight_stats` layout matches `_skin_weights`' vertex-major flat list; `skin_facts` keys match `SkinFacts` fields and `skin_violations` consumption; `_validate` return arity change is called out.
