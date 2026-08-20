# Rigging Phase 3 — pose_ik Implementation Plan (#671)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One command, `pose_ik(root, joint, target, pole?, start?, keep=True)`: solve a joint chain to a world-space target, bake the result to plain FK rotations, delete the handle — no persistent IK state ever exists in the scene.

**Architecture:** Pure chain geometry (reach, deviation, pole derivation, pre-bend) lives in `rigmath.py` so the headless suite carries it; `rigging.pose_ik` is orchestration only — it drives Maya's `ikRPsolver` through a transient `ikHandle`, reads the solved rotations, deletes every IK node, re-applies the rotations as plain FK (the phase-1 pose currency), and reports MEASURED numbers: `achieved_position`, `residual`, per-mesh displacement. Spec section: `docs/superpowers/specs/2026-08-19-rigging-surface-design.md` "Phase 3 — IK posing".

**Tech Stack:** Python (Maya plugin handlers + FastMCP server), pytest three-leg testing (pure math / FakeCmds orchestration / mayapy real-Maya), live gate eval over the TCP client.

## Global Constraints

- **Angles are degrees at the boundary** (#636): every rotation read converts via `units.ui_to_degrees(cmds, v)`, every write via `units.degrees_to_ui(cmds, v)`.
- **Positions are ordinary geometry numbers** (#629/#634): `target`, `pole`, `achieved_position`, `residual` are scene units, no conversion.
- **Report measured, never echoed** (#636): `achieved_position` and `residual` are re-read from the scene AFTER the bake, not taken from the solver's claim.
- **Silence is never an answer** (#638/#640): out-of-reach targets, straight chains without a pole, missed reachable targets, keep=false restores — all go to `warnings`.
- **Mutating commands auto-checkpoint** exactly once, after validation, before the first scene write (`session.auto_checkpoint("pose_ik")`).
- **No persistent IK state**: after the call returns, `cmds.ls(type="ikHandle")`, `ls(type="ikEffector")`, and any pole locator/constraint are empty — asserted in mayapy and in the live gate.
- **The stored pose stays the phase-1 rotation map**: `rotations` in the result must reproduce the achieved position when re-applied via `pose_skeleton` (asserted in mayapy).
- Two-Maya policy: the live gate runs on a disposable agent-launched Maya, port **9878**, **neutral cwd** (#604), pid verified (#648). Never `new_scene` on the user's 9877.
- Suites: `uv run pytest -q` (currently 1135 passed + 1 skipped) and `E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q` (currently 119 passed + 1 skipped) must stay green; counts only grow.

## File structure

| file | responsibility |
|---|---|
| `maya_plugin/handlers/rigmath.py` (modify) | Pure chain geometry: `dist`, `chain_reach`, `chain_deviation`, `default_pole`, `plane_normal`, `local_components`, `prebend_rotations`. |
| `maya_plugin/handlers/rigging.py` (modify) | `pose_ik` handler + helpers `_resolve_joint`, `_chain_between`. |
| `maya_plugin/maya_mcp_plugin.py` (modify) | Register `"pose_ik"` in the handler map. |
| `src/maya_mcp/schemas.py` (modify) | `PoseIkResult`. |
| `src/maya_mcp/server.py` (modify) | `maya_pose_ik` tool (50 total). |
| `docs/protocol.md` (modify) | Phase-3 command section. |
| `evals/humanoid_ik_live.py` (create) | The live gate: the #668 humanoid re-posed via IK targets. Imports build DATA from `evals/humanoid_live.py` (constants only — humanoid_live.py itself is untouched, so its 45/45 baseline stands without a re-run). |
| `tests/test_rigmath.py`, `tests/test_rigging.py`, `tests/test_server_tools.py`, `tests/test_handlers_mayapy.py` (modify) | Coverage per leg. |

### Contract decisions locked here (plan-level refinements of the spec)

1. **`start` parameter added** (optional). The spec's `(root, joint, target)` cannot say where the chain begins; default = **two joints above `joint`** — the classic 2-bone limb, which makes `root=pelvis, joint=L_ankle` solve hip→knee→ankle and `joint=L_wrist` solve shoulder→elbow→wrist with zero extra input. Longer chains (a serpent spine) pass `start` explicitly.
2. **`pole` is a world POSITION** (like `target`), not a vector — implemented via a transient locator + `poleVectorConstraint`, both deleted with the handle. Unambiguous world-space semantics, no parent-space trap.
3. **Default pole preserves the chain's own bend plane** when the chain is already bent (`rigmath.default_pole`); a straight chain with no pole warns and lets the solver guess — the residual and the warning carry the truth.
4. **Straight-chain pre-bend**: Maya's RP solver cannot fold a perfectly collinear chain (zero preferred angle — a known Maya trap, and the humanoid's bind-pose limbs ARE collinear). When the chain is straight and a pole exists, interior joints get a ±5° nudge toward the pole before the handle is created; the solve overwrites the nudge. Computed in pure math (`prebend_rotations`), sign derived and pinned by test.
5. **`keep=false`** solves, measures everything (achieved/residual/rotations/displacement), then restores the rotations the call found — a "what would it take" dry-run. The measured numbers describe the solved pose, and a warning says the restore happened.
6. **Result** (spec shape + this project's measured-reporting rules): `{achieved_position, residual, rotations, chain, pole_used, kept, max_displacement, displaced_vertices, per_mesh, warnings}`. `rotations` keys are canonical long names — directly usable as `pose_skeleton`'s map.

---

### Task 1: Pure chain geometry in rigmath

**Files:**
- Modify: `maya_plugin/handlers/rigmath.py` (append at end)
- Test: `tests/test_rigmath.py` (append at end)

**Interfaces:**
- Consumes: nothing new (stdlib `math`, existing `vec3`).
- Produces (exact signatures Task 2 calls):
  - `dist(a: List[float], b: List[float]) -> float`
  - `chain_reach(positions: List[List[float]]) -> float`
  - `chain_deviation(positions: List[List[float]]) -> float`
  - `default_pole(positions, collinear_ratio: float) -> Optional[List[float]]`
  - `plane_normal(start, target, pole) -> Optional[List[float]]`
  - `local_components(vec, matrix16: List[float]) -> List[float]`
  - `prebend_rotations(positions, matrices: Dict[int, List[float]], target, pole, angle_deg: float) -> Dict[int, List[float]]`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_rigmath.py`:

```python
class TestPoseIkChainGeometry:
    # A leg-like chain, deliberately in metre-magnitude scene numbers
    # (#629/#634): hip -> knee -> ankle.
    STRAIGHT = [[0.1, 0.95, 0.0], [0.1, 0.50, 0.0], [0.1, 0.08, 0.0]]
    BENT = [[0.1, 0.95, 0.0], [0.1, 0.50, 0.10], [0.1, 0.08, 0.0]]

    def test_dist_and_reach(self):
        assert rigmath.dist([0, 0, 0], [3, 4, 0]) == pytest.approx(5.0)
        assert rigmath.chain_reach(self.STRAIGHT) == pytest.approx(0.87)

    def test_deviation_zero_on_a_straight_chain(self):
        assert rigmath.chain_deviation(self.STRAIGHT) == pytest.approx(0.0)
        assert rigmath.chain_deviation([[0, 0, 0], [1, 1, 1]]) == 0.0

    def test_deviation_measures_the_bent_knee(self):
        # knee sits 0.10 off the hip-ankle line, minus the tilt component
        dev = rigmath.chain_deviation(self.BENT)
        assert 0.05 < dev <= 0.10

    def test_default_pole_none_when_straight(self):
        assert rigmath.default_pole(self.STRAIGHT, 0.01) is None
        assert rigmath.default_pole([[0, 0, 0], [1, 0, 0]], 0.01) is None

    def test_default_pole_preserves_the_bend_plane(self):
        pole = rigmath.default_pole(self.BENT, 0.01)
        assert pole is not None
        # the knee bends toward +Z, so the pole must sit +Z of the knee
        assert pole[2] > self.BENT[1][2]
        # ...at a comfortable distance (the chain's own reach)
        assert rigmath.dist(pole, self.BENT[1]) == pytest.approx(
            rigmath.chain_reach(self.BENT))

    def test_plane_normal_is_unit_and_refuses_degenerate(self):
        n = rigmath.plane_normal([0, 0, 0], [0, -2, 0], [0, -1, 1])
        assert n == pytest.approx([-1.0, 0.0, 0.0])
        assert rigmath.plane_normal([0, 0, 0], [0, -2, 0], [0, -1, 0]) is None

    def test_local_components_identity_and_rotated(self):
        identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
        assert rigmath.local_components([0, 0, 1], identity) == pytest.approx(
            [0.0, 0.0, 1.0])
        # a frame rotated +90 about Z: local X points at world +Y
        rot_z90 = [0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
        assert rigmath.local_components([1, 0, 0], rot_z90) == pytest.approx(
            [0.0, -1.0, 0.0])

    def test_prebend_folds_the_knee_toward_the_pole(self):
        # Straight 2-bone chain down -Y, target short of reach, pole at +Z
        # (knee forward). Derivation pinned: fold the foot BACKWARD (-Z) so
        # the solver's compensation at the hip pushes the knee FORWARD.
        # With an identity local frame and plane normal -X, that is +5 deg
        # about local X on the one interior joint.
        positions = [[0, 0, 0], [0, -1, 0], [0, -2, 0]]
        identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
        out = rigmath.prebend_rotations(
            positions, {1: identity}, [0, -1.5, 0], [0, -1, 1], 5.0)
        assert set(out) == {1}
        assert out[1] == pytest.approx([5.0, 0.0, 0.0])

    def test_prebend_empty_when_pole_sits_on_the_line(self):
        positions = [[0, 0, 0], [0, -1, 0], [0, -2, 0]]
        out = rigmath.prebend_rotations(
            positions, {1: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]},
            [0, -1.5, 0], [0, -3, 0], 5.0)
        assert out == {}
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_rigmath.py::TestPoseIkChainGeometry -q`. Expected: FAIL, `AttributeError: ... has no attribute 'dist'`.

- [ ] **Step 3: Implement** — append to `maya_plugin/handlers/rigmath.py`:

```python
# --- phase 3 (#671): IK chain geometry --------------------------------------


def _sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0]]


def dist(a: List[float], b: List[float]) -> float:
    return math.sqrt(_dot(_sub(a, b), _sub(a, b)))


def chain_reach(positions: List[List[float]]) -> float:
    """Sum of bone lengths - the furthest the chain can straighten."""
    return sum(dist(positions[i], positions[i + 1])
               for i in range(len(positions) - 1))


def _perp_offsets(positions):
    """(interior point, its perpendicular offset from the start-end line)."""
    axis = _sub(positions[-1], positions[0])
    length = math.sqrt(_dot(axis, axis))
    out = []
    for mid in positions[1:-1]:
        offset = _sub(mid, positions[0])
        if length < 1e-12:
            out.append((mid, offset))
            continue
        along = _dot(offset, axis) / (length * length)
        out.append((mid, _sub(offset, [v * along for v in axis])))
    return out


def chain_deviation(positions: List[List[float]]) -> float:
    """How far the most-bent interior joint sits off the start-end line.
    Below ~1% of reach the RP solver sees a straight chain and cannot fold
    it on its own - the pre-bend exists for exactly that case."""
    if len(positions) < 3:
        return 0.0
    return max((math.sqrt(_dot(p, p)) for _, p in _perp_offsets(positions)),
               default=0.0)


def default_pole(positions, collinear_ratio: float) -> Optional[List[float]]:
    """A pole that PRESERVES the chain's own bend plane - the least
    surprising default: an already-bent knee keeps facing the way it faces.
    None when the chain is too straight to have a plane of its own."""
    if len(positions) < 3:
        return None
    reach = chain_reach(positions)
    best_mid, best_perp, best_norm = None, None, 0.0
    for mid, perp in _perp_offsets(positions):
        norm = math.sqrt(_dot(perp, perp))
        if norm > best_norm:
            best_mid, best_perp, best_norm = mid, perp, norm
    if best_mid is None or best_norm < collinear_ratio * max(reach, 1e-12):
        return None
    return [best_mid[k] + best_perp[k] / best_norm * reach for k in range(3)]


def plane_normal(start, target, pole) -> Optional[List[float]]:
    """Unit normal of the solve plane, or None when the pole sits on the
    start-target line (no plane - the solver would have to guess)."""
    n = _cross(_sub(target, start), _sub(pole, start))
    length = math.sqrt(_dot(n, n))
    if length < 1e-9:
        return None
    return [v / length for v in n]


def local_components(vec, matrix16: List[float]) -> List[float]:
    """A world vector expressed in a joint's local frame. Maya's xform
    matrix is row-major with rows 0..2 = the local axes in world space;
    joints in this project are identity-scale (the export gate's rule), so
    projecting onto the normalized rows IS the inverse rotation."""
    out = []
    for row in range(3):
        axis = matrix16[row * 4:row * 4 + 3]
        length = math.sqrt(_dot(axis, axis)) or 1.0
        out.append(_dot(vec, axis) / length)
    return out


def prebend_rotations(positions, matrices: Dict[int, List[float]], target,
                      pole, angle_deg: float) -> Dict[int, List[float]]:
    """Per-interior-joint local euler nudges (DEGREES) that fold a straight
    chain so its bend lands on the pole's side of the solve plane.

    Sign, derived and pinned by test_prebend_folds_the_knee_toward_the_pole:
    folding a mid joint by +t about the plane normal moves the EFFECTOR
    along cross(normal, child - mid); the solver's compensation at the
    start joint then pushes the mid joint the OPPOSITE way - so bend
    against that direction to end up pole-side.
    """
    normal = plane_normal(positions[0], target, pole)
    if normal is None:
        return {}
    out: Dict[int, List[float]] = {}
    for i in range(1, len(positions) - 1):
        mid, child = positions[i], positions[i + 1]
        swing = _cross(normal, _sub(child, mid))
        sign = -1.0 if _dot(swing, _sub(pole, mid)) > 0 else 1.0
        out[i] = [angle_deg * sign * c
                  for c in local_components(normal, matrices[i])]
    return out
```

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_rigmath.py -q`. Expected: PASS (whole file — the older classes must stay green).

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/rigmath.py tests/test_rigmath.py
git commit -m "feat(#671): pure IK chain geometry - reach, deviation, default pole, prebend"
```

---

### Task 2: The pose_ik handler under FakeCmds

**Files:**
- Modify: `maya_plugin/handlers/rigging.py` (append at end)
- Test: `tests/test_rigging.py` (FakeCmds additions near the top of the class; new test class at end)

**Interfaces:**
- Consumes: Task 1's rigmath functions; existing `_require_joint`, `_hierarchy_joints`, `_bound_meshes`, `session.auto_checkpoint`, `sculpt.vertex_positions`, `sculpt_math.max_displacement`, `sculpt_math.bbox_extent`, `rigmath.displaced_count`, `naming.unique_name`, `units.degrees_to_ui/ui_to_degrees`, `NOOP_POSE_RATIO`.
- Produces: `rigging.pose_ik(params: Dict) -> Dict` with keys `achieved_position, residual, rotations, chain, pole_used, kept, max_displacement, displaced_vertices, per_mesh, warnings`; helpers `_resolve_joint(cmds, joints, name, what)`, `_chain_between(cmds, joints, start, end)` (Task 4/7 rely on the exact result keys; Task 5's schema mirrors them).

- [ ] **Step 1: Extend FakeCmds** in `tests/test_rigging.py`. Add to `__init__`:

```python
        self.positions = {}    # node long name -> [x, y, z] for xform queries
        self.matrices = {}     # node long name -> 16 floats for matrix queries
```

Replace the existing `listRelatives` with (adds the `parent` branch, everything else verbatim):

```python
    def listRelatives(self, node, children=False, parent=False,
                      allDescendents=False, type=None, fullPath=False, **kw):
        if parent:
            p = self.parents.get(node)
            return [p] if p else None
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
```

Replace the existing `xform` with (adds write form, matrix query, per-node positions; the [1,2,3] default keeps every older test exact):

```python
    def xform(self, node, query=False, worldSpace=False, translation=False,
              matrix=False, **kw):
        if query and matrix:
            self.calls.append(("xform_matrix", node))
            return self.matrices.get(
                node, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])
        if not query and not isinstance(translation, bool):
            self.calls.append(("xform_set", node, tuple(translation)))
            return None
        self.calls.append(("xform_query", node))
        return list(self.positions.get(node, [1.0, 2.0, 3.0]))
```

Add IK node fakes after `skinCluster`:

```python
    def ikHandle(self, startJoint=None, endEffector=None, solver=None,
                 name=None, **kw):
        handle, effector = "|" + name, "|" + name + "_eff"
        self.objects.extend([handle, effector])
        self.calls.append(("ikHandle", startJoint, endEffector, solver, name))
        return [handle, effector]

    def spaceLocator(self, name=None, **kw):
        self.objects.append("|" + name)
        self.calls.append(("spaceLocator", name))
        return ["|" + name]

    def poleVectorConstraint(self, locator, handle, **kw):
        self.calls.append(("poleVectorConstraint", locator, handle))
        return [handle + "_pvc"]

    def delete(self, *names, **kw):
        self.calls.append(("delete", names))
        for n in names:
            if n in self.objects:
                self.objects.remove(n)
```

- [ ] **Step 2: Write the failing tests** — append to `tests/test_rigging.py`:

```python
class TestPoseIk:
    def _rig(self, fake, bent=True):
        fake.objects = ["|pelvis", "|pelvis|hip", "|pelvis|hip|knee",
                        "|pelvis|hip|knee|ankle"]
        fake.parents = {"|pelvis|hip": "|pelvis",
                        "|pelvis|hip|knee": "|pelvis|hip",
                        "|pelvis|hip|knee|ankle": "|pelvis|hip|knee"}
        knee_z = 0.05 if bent else 0.0   # bent skips the prebend path
        fake.positions = {"|pelvis": [0.0, 1.0, 0.0],
                          "|pelvis|hip": [0.1, 0.95, 0.0],
                          "|pelvis|hip|knee": [0.1, 0.5, knee_z],
                          "|pelvis|hip|knee|ankle": [0.1, 0.08, 0.0]}

    def test_default_start_is_two_joints_up(self, fake):
        self._rig(fake)
        out = rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                               "target": [0.1, 0.6, 0.2]})
        assert out["chain"] == ["|pelvis|hip", "|pelvis|hip|knee",
                                "|pelvis|hip|knee|ankle"]
        made = [c for c in fake.calls if c[0] == "ikHandle"]
        assert made == [("ikHandle", "|pelvis|hip", "|pelvis|hip|knee|ankle",
                         rigging.IK_SOLVER, "ankle_ikh")]

    def test_solve_bake_delete_order(self, fake):
        self._rig(fake)
        out = rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                               "target": [0.1, 0.6, 0.2]})
        names = [c[0] for c in fake.calls]
        # the handle is moved to the target, rotations are read, the IK
        # nodes die, and ONLY THEN the rotations are re-applied as plain FK
        target_set = names.index("xform_set")
        deleted = names.index("delete")
        assert target_set < deleted
        rebakes = [i for i, c in enumerate(fake.calls)
                   if c[0] == "setAttr" and c[1].endswith(".rotate")
                   and i > deleted]
        assert len(rebakes) == 3          # one per chain joint
        # nothing IK-shaped survives
        assert not any("ikh" in o for o in fake.objects)
        assert out["kept"] is True
        assert set(out["rotations"]) == set(out["chain"])

    def test_default_pole_rides_the_bent_knee(self, fake):
        self._rig(fake, bent=True)
        out = rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                               "target": [0.1, 0.6, 0.2]})
        assert out["pole_used"] is not None
        assert out["pole_used"][2] > 0            # knee bends +Z
        assert any(c[0] == "poleVectorConstraint" for c in fake.calls)

    def test_straight_chain_without_pole_warns_and_uses_no_constraint(self, fake):
        self._rig(fake, bent=False)
        out = rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                               "target": [0.1, 0.6, 0.2]})
        assert out["pole_used"] is None
        assert not any(c[0] == "poleVectorConstraint" for c in fake.calls)
        assert any("STRAIGHT" in w for w in out["warnings"])

    def test_straight_chain_with_pole_prebends_the_knee(self, fake):
        self._rig(fake, bent=False)
        rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                         "target": [0.1, 0.6, 0.2], "pole": [0.1, 0.5, 0.5]})
        handle_at = [i for i, c in enumerate(fake.calls)
                     if c[0] == "ikHandle"][0]
        prebends = [i for i, c in enumerate(fake.calls)
                    if c[0] == "setAttr" and c[1] == "|pelvis|hip|knee.rotate"
                    and i < handle_at]
        assert prebends, "the interior joint must be nudged BEFORE the handle exists"

    def test_out_of_reach_target_warns_with_the_reach(self, fake):
        self._rig(fake)
        out = rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                               "target": [5.0, 5.0, 5.0]})
        assert any("reaches only" in w for w in out["warnings"])

    def test_keep_false_restores_and_says_so(self, fake):
        self._rig(fake)
        fake.attrs["|pelvis|hip|knee.rotate"] = [(0.0, 7.0, 0.0)]
        out = rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                               "target": [0.1, 0.6, 0.2], "keep": False})
        assert out["kept"] is False
        assert fake.attrs["|pelvis|hip|knee.rotate"] == [(0.0, 7.0, 0.0)]
        assert any("keep=false" in w for w in out["warnings"])

    def test_one_checkpoint_after_validation(self, fake, monkeypatch):
        self._rig(fake)
        events = []
        monkeypatch.setattr(session, "auto_checkpoint",
                            lambda reason: events.append(reason) or
                            {"checkpoint_id": "001_" + reason, "path": "x.ma"})
        with pytest.raises(HandlerError):
            rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                             "target": "not-a-vec"})
        assert events == []
        rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                         "target": [0.1, 0.6, 0.2]})
        assert events == ["pose_ik"]

    def test_refusals(self, fake):
        self._rig(fake)
        with pytest.raises(HandlerError, match="BELOW the root"):
            rigging.pose_ik({"root": "pelvis", "joint": "pelvis",
                             "target": [0, 0, 0]})
        with pytest.raises(HandlerError, match="missing required param 'target'"):
            rigging.pose_ik({"root": "pelvis", "joint": "ankle"})
        with pytest.raises(HandlerError, match="keep must be"):
            rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                             "target": [0, 0, 0], "keep": "yes"})
        with pytest.raises(HandlerError, match="single bone"):
            rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                             "target": [0, 0, 0], "start": "knee"})
        with pytest.raises(HandlerError, match="not an ancestor"):
            rigging.pose_ik({"root": "pelvis", "joint": "knee",
                             "target": [0, 0, 0], "start": "ankle"})
        with pytest.raises(HandlerError, match="no default chain"):
            rigging.pose_ik({"root": "pelvis", "joint": "hip",
                             "target": [0, 0, 0]})
        with pytest.raises(HandlerError, match="not a joint under this root"):
            rigging.pose_ik({"root": "pelvis", "joint": "elbow",
                             "target": [0, 0, 0]})
```

- [ ] **Step 3: Run to verify failure** — `uv run pytest tests/test_rigging.py::TestPoseIk -q`. Expected: FAIL, `AttributeError: ... no attribute 'pose_ik'`.

- [ ] **Step 4: Implement** — append to `maya_plugin/handlers/rigging.py`:

```python
# --- phase 3 (#671): pose_ik -------------------------------------------------

# A chain whose interior joints deviate by less than this fraction of its
# reach is "straight": Maya's RP solver cannot fold a collinear chain on its
# own (zero preferred angle), so pose_ik pre-bends it PREBEND_DEG toward the
# pole to break the tie. The solve overwrites the nudge; residual reports
# whatever the solver actually achieved.
COLLINEAR_RATIO = 0.01
PREBEND_DEG = 5.0
IK_SOLVER = "ikRPsolver"
# Above this miss (scene units) a solve that COULD have reached warns; an
# out-of-reach miss is explained by the reach warning instead.
RESIDUAL_WARN = 1e-3


def _resolve_joint(cmds, joints: List[str], name, what: str) -> str:
    """One joint out of `joints`, by long or unique short name."""
    if not isinstance(name, str) or not name.strip():
        raise HandlerError("missing required param %r" % what,
                           hint="a joint name from maya_create_skeleton")
    if name in joints:
        return name
    matches = [j for j in joints if _short(j) == _short(name)]
    if not matches:
        raise HandlerError(
            "%s %r is not a joint under this root" % (what, name),
            hint="joints here: %s" % ", ".join(_short(j) for j in joints[:12]))
    if len(matches) > 1:
        raise HandlerError(
            "%s %r is ambiguous under this root (%d matches)"
            % (what, name, len(matches)),
            hint="use the long name, e.g. %s" % matches[0])
    return matches[0]


def _chain_between(cmds, joints: List[str], start: str, end: str) -> List[str]:
    """start..end inclusive, parents first; refuses a non-ancestor start."""
    chain = [end]
    node = end
    while node != start:
        parents = [p for p in (cmds.listRelatives(
            node, parent=True, fullPath=True, type="joint") or [])
            if p in joints]
        if not parents:
            raise HandlerError(
                "%s is not an ancestor of %s" % (_short(start), _short(end)),
                hint="start must sit above joint on the same chain")
        node = parents[0]
        chain.append(node)
    chain.reverse()
    return chain


def pose_ik(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    root_long = _require_joint(cmds, params.get("root"))
    joints = _hierarchy_joints(cmds, root_long)
    end = _resolve_joint(cmds, joints, params.get("joint"), "joint")
    if end == root_long:
        raise HandlerError(
            "joint must sit BELOW the root - the root has no chain above it",
            hint="e.g. root=pelvis, joint=L_ankle solves the left leg")
    target = rigmath.vec3(params.get("target"), "target")
    if target is None:
        raise HandlerError(
            "missing required param 'target'",
            hint="world position [x, y, z] the joint should reach")
    pole = rigmath.vec3(params.get("pole"), "pole")
    keep = params.get("keep", True)
    if not isinstance(keep, bool):
        raise HandlerError(
            "keep must be true or false",
            hint="true bakes the solved pose; false measures it, then "
                 "restores the pose the call found")

    if params.get("start") is not None:
        start = _resolve_joint(cmds, joints, params.get("start"), "start")
    else:
        # Default: two joints up - the classic 2-bone limb (hip for an
        # ankle, shoulder for a wrist). Longer chains pass start explicitly.
        path = _chain_between(cmds, joints, root_long, end)
        if len(path) < 3:
            raise HandlerError(
                "%s hangs directly under the root - no default chain exists"
                % _short(end),
                hint="pass start explicitly, or aim single bones with "
                     "pose_skeleton")
        start = path[-3]
    chain = _chain_between(cmds, joints, start, end)
    if len(chain) < 3:
        raise HandlerError(
            "the chain %s..%s is a single bone - IK needs at least two"
            % (_short(start), _short(end)),
            hint="a single bone is an aim, not a solve: rotate it with "
                 "pose_skeleton, or pass a higher start")

    positions = [[float(v) for v in cmds.xform(
        j, query=True, worldSpace=True, translation=True)] for j in chain]
    reach = rigmath.chain_reach(positions)
    distance = rigmath.dist(positions[0], target)
    warnings: List[str] = []
    if distance > reach:
        warnings.append(
            "the target sits %.4g from %s but the chain reaches only %.4g - "
            "the solve will fall short and residual reports the miss"
            % (distance, _short(start), reach))

    pole_used = pole if pole is not None else rigmath.default_pole(
        positions, COLLINEAR_RATIO)
    straight = rigmath.chain_deviation(positions) < COLLINEAR_RATIO * reach
    if straight and pole_used is None:
        warnings.append(
            "the chain is STRAIGHT and no pole was given - the solver has no "
            "bend plane, so which way the limb folds is Maya's guess; pass "
            "pole=[x,y,z], the world position the knee/elbow should face")

    session.auto_checkpoint("pose_ik")
    meshes = _bound_meshes(cmds, set(joints))
    before = {m: sculpt.vertex_positions(cmds, m) for m in meshes}
    prior = {j: tuple(cmds.getAttr(j + ".rotate")[0]) for j in chain}

    if straight and pole_used is not None:
        # A straight chain gives the solver no fold to amplify: nudge the
        # interior joints a few degrees toward the pole. The solve
        # overwrites the nudge; keep=false or the checkpoint undoes it.
        matrices = {i: [float(v) for v in cmds.xform(
            chain[i], query=True, worldSpace=True, matrix=True)]
            for i in range(1, len(chain) - 1)}
        for i, triple in rigmath.prebend_rotations(
                positions, matrices, target, pole_used, PREBEND_DEG).items():
            current = cmds.getAttr(chain[i] + ".rotate")[0]
            cmds.setAttr(chain[i] + ".rotate",
                         current[0] + units.degrees_to_ui(cmds, triple[0]),
                         current[1] + units.degrees_to_ui(cmds, triple[1]),
                         current[2] + units.degrees_to_ui(cmds, triple[2]))

    handle, effector = cmds.ikHandle(
        startJoint=start, endEffector=end, solver=IK_SOLVER,
        name=naming.unique_name(cmds, _short(end) + "_ikh"))
    locator = None
    if pole_used is not None:
        locator = cmds.spaceLocator(
            name=naming.unique_name(cmds, _short(end) + "_pole"))[0]
        cmds.xform(locator, worldSpace=True, translation=pole_used)
        cmds.poleVectorConstraint(locator, handle)
    cmds.xform(handle, worldSpace=True, translation=target)

    # Reading the effector's world position pulls the IK evaluation; the
    # solved joint rotations are then plain attribute reads, in degrees
    # (#636's unit rule).
    cmds.xform(end, query=True, worldSpace=True, translation=True)
    baked: Dict[str, List[float]] = {}
    for j in chain:
        raw = cmds.getAttr(j + ".rotate")[0]
        baked[j] = [round(units.ui_to_degrees(cmds, v), 6) for v in raw]

    doomed = [n for n in (handle, effector, locator)
              if n and cmds.objExists(n)]
    if doomed:
        cmds.delete(*doomed)
    # The bake: deleting a handle can snap joints back, so the solved values
    # are re-applied as plain FK - the same currency pose_skeleton speaks.
    for j in chain:
        cmds.setAttr(j + ".rotate",
                     units.degrees_to_ui(cmds, baked[j][0]),
                     units.degrees_to_ui(cmds, baked[j][1]),
                     units.degrees_to_ui(cmds, baked[j][2]))

    achieved = [float(v) for v in cmds.xform(
        end, query=True, worldSpace=True, translation=True)]
    residual = rigmath.dist(achieved, target)
    if residual > RESIDUAL_WARN and distance <= reach:
        warnings.append(
            "the solve missed a REACHABLE target by %.4g - joint limits, a "
            "degenerate pole, or a bend the pre-bend could not break can do "
            "this; try a pole on the intended bend side" % residual)

    max_disp = 0.0
    displaced = 0
    per_mesh: List[Dict[str, Any]] = []
    for mesh in meshes:
        after = sculpt.vertex_positions(cmds, mesh)
        mesh_disp = sculpt_math.max_displacement(before[mesh], after)
        mesh_count = rigmath.displaced_count(before[mesh], after)
        per_mesh.append({"mesh": mesh, "max_displacement": mesh_disp,
                         "displaced_vertices": mesh_count})
        max_disp = max(max_disp, mesh_disp)
        displaced += mesh_count
    if not meshes:
        warnings.append(
            "no skinned mesh is bound to this skeleton - the solve moved "
            "bare joints only; bind_skin first if deformation was the point")
    else:
        for entry in per_mesh:
            extent = sculpt_math.bbox_extent(before[entry["mesh"]])
            if extent > 0 and entry["max_displacement"] < extent * NOOP_POSE_RATIO:
                warnings.append(
                    "%s moved by %.4g against a size of %.4g - near-zero "
                    "deformation usually means the chain owns none of its "
                    "vertices"
                    % (entry["mesh"], entry["max_displacement"], extent))

    if not keep:
        for j, rot in prior.items():
            cmds.setAttr(j + ".rotate", rot[0], rot[1], rot[2])
        warnings.append(
            "keep=false: the solved pose was measured, then the pose the "
            "call found was restored - apply rotations via pose_skeleton to "
            "commit it")

    return {
        "achieved_position": achieved,
        "residual": residual,
        "rotations": baked,
        "chain": chain,
        "pole_used": pole_used,
        "kept": keep,
        "max_displacement": max_disp,
        "displaced_vertices": displaced,
        "per_mesh": per_mesh,
        "warnings": warnings,
    }
```

- [ ] **Step 5: Run to verify pass** — `uv run pytest tests/test_rigging.py -q`. Expected: PASS (whole file; the FakeCmds edits must not disturb the older classes).

- [ ] **Step 6: Full headless suite** — `uv run pytest -q`. Expected: green, count > 1135.

- [ ] **Step 7: Commit**

```bash
git add maya_plugin/handlers/rigging.py tests/test_rigging.py
git commit -m "feat(#671): pose_ik - solve to target, bake to FK, delete the handle"
```

---

### Task 3: The mayapy leg — real solves, measured

**Files:**
- Test: `tests/test_handlers_mayapy.py` (append at end)

**Interfaces:**
- Consumes: `rigging.create_skeleton`, `rigging.pose_ik`, `rigging.pose_skeleton`, `rigging.reset_pose` exactly as produced by Task 2.
- Produces: measured confirmation that (a) a STRAIGHT bind-pose limb reaches a reachable target when a pole is given, (b) the bake is plain FK that reproduces the solve, (c) no IK node survives, (d) an unreachable target's residual is the geometric miss, (e) keep=false restores.

**This is the task where reality can push back.** Two behaviors are assumed from Maya knowledge, not yet measured here: that `getAttr(.rotate)` on an IK-driven joint returns the solved rotation in mayapy, and that the 5° pre-bend suffices for the RP solver to fold a straight chain toward the pole. If either test fails, use superpowers:systematic-debugging; the sanctioned fallbacks, in order: (1) query `cmds.xform(end, ws, t)` AND `cmds.getAttr(handle + ".ikBlend")` to force a full eval before reading rotations; (2) raise `PREBEND_DEG` to 15; (3) set `preferredAngle` on interior joints in addition to the pre-bend. Record whatever was measured in the task's SDD findings.

- [ ] **Step 1: Write the tests** — append to `tests/test_handlers_mayapy.py`:

```python
class TestPoseIkInMaya:
    LEG = [
        {"name": "ik_pelvis", "position": [0.0, 1.00, 0.0]},
        {"name": "ik_hip", "position": [0.10, 0.95, 0.0], "parent": "ik_pelvis"},
        {"name": "ik_knee", "position": [0.10, 0.50, 0.0], "parent": "ik_hip"},
        {"name": "ik_ankle", "position": [0.10, 0.08, 0.0], "parent": "ik_knee"},
    ]
    TARGET = [0.10, 0.60, 0.20]       # forward+up, well inside the 0.87 reach
    POLE = [0.10, 0.50, 0.50]         # knee faces world +Z

    def _skeleton(self):
        from maya_plugin.handlers import rigging

        return rigging.create_skeleton({"joints": self.LEG})["root"]

    def test_straight_leg_reaches_the_target_with_a_pole(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        root = self._skeleton()
        out = rigging.pose_ik({"root": root, "joint": "ik_ankle",
                               "target": self.TARGET, "pole": self.POLE})
        # the bind-pose leg is perfectly straight - this asserts the
        # pre-bend actually unlocked the RP solver
        assert out["residual"] < 1e-3, out
        for axis in range(3):
            assert abs(out["achieved_position"][axis]
                       - self.TARGET[axis]) < 2e-3
        # the knee folded toward the pole, not away from it
        knee = cmds.xform(out["chain"][1], query=True, worldSpace=True,
                          translation=True)
        assert knee[2] > 0.01, "knee went to z=%.4f, away from the pole" % knee[2]
        # no persistent IK state, the spec's core promise
        assert not cmds.ls(type="ikHandle")
        assert not cmds.ls(type="ikEffector")
        assert not cmds.ls(type="poleVectorConstraint")
        assert not cmds.ls("*_pole", type="transform")

    def test_bake_is_the_phase1_pose_currency(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        root = self._skeleton()
        out = rigging.pose_ik({"root": root, "joint": "ik_ankle",
                               "target": self.TARGET, "pole": self.POLE})
        rigging.reset_pose({"root": root})
        # re-apply the returned rotations as plain FK: same achieved position
        rigging.pose_skeleton({"root": root, "rotations": out["rotations"]})
        again = cmds.xform("|ik_pelvis|ik_hip|ik_knee|ik_ankle", query=True,
                           worldSpace=True, translation=True)
        for axis in range(3):
            assert abs(again[axis] - out["achieved_position"][axis]) < 1e-4

    def test_unreachable_target_reports_the_geometric_miss(self):
        from maya_plugin.handlers import rigmath, rigging

        root = self._skeleton()
        target = [0.10, 0.95 - 2.0, 0.0]   # 2.0 below the hip, reach is 0.87
        out = rigging.pose_ik({"root": root, "joint": "ik_ankle",
                               "target": target, "pole": self.POLE})
        expected_miss = 2.0 - rigmath.chain_reach(
            [[0.10, 0.95, 0.0], [0.10, 0.50, 0.0], [0.10, 0.08, 0.0]])
        assert abs(out["residual"] - expected_miss) < 0.05
        assert any("reaches only" in w for w in out["warnings"])

    def test_keep_false_measures_then_restores(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        root = self._skeleton()
        ankle = "|ik_pelvis|ik_hip|ik_knee|ik_ankle"
        before = cmds.xform(ankle, query=True, worldSpace=True,
                            translation=True)
        out = rigging.pose_ik({"root": root, "joint": "ik_ankle",
                               "target": self.TARGET, "pole": self.POLE,
                               "keep": False})
        assert out["kept"] is False
        assert out["residual"] < 1e-3          # the solve itself was measured
        after = cmds.xform(ankle, query=True, worldSpace=True,
                           translation=True)
        for axis in range(3):
            assert abs(after[axis] - before[axis]) < 1e-6

    def test_deforms_a_bound_mesh_and_measures_it(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        root = self._skeleton()
        cmds.polyCylinder(name="ik_leg_mesh", radius=0.06, height=0.9,
                          subdivisionsHeight=8)
        cmds.setAttr("|ik_leg_mesh.translate", 0.10, 0.5, 0.0)
        cmds.makeIdentity("|ik_leg_mesh", apply=True, translate=True)
        rigging.bind_skin({"mesh": "|ik_leg_mesh", "root": root})
        out = rigging.pose_ik({"root": root, "joint": "ik_ankle",
                               "target": self.TARGET, "pole": self.POLE})
        assert out["max_displacement"] > 0.05
        assert out["per_mesh"] and out["per_mesh"][0]["displaced_vertices"] > 0
```

- [ ] **Step 2: Run** — `E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py::TestPoseIkInMaya -v`. Expected: PASS (5). On failure: systematic-debugging with the fallback ladder above; adjust the handler, re-run Task 2's suite, and record the measured cause in the commit message.

- [ ] **Step 3: Full mayapy suite** — `E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q`. Expected: green, count > 119.

- [ ] **Step 4: Commit**

```bash
git add tests/test_handlers_mayapy.py maya_plugin/handlers/rigging.py
git commit -m "test(#671): pose_ik measured against a real Maya - straight-chain fold, bake fidelity, purity"
```

---

### Task 4: Dispatcher, schema, MCP tool

**Files:**
- Modify: `maya_plugin/maya_mcp_plugin.py` (the handler map, after `"set_region_weights"`)
- Modify: `src/maya_mcp/schemas.py` (after `ResetPoseResult`)
- Modify: `src/maya_mcp/server.py` (after `maya_reset_pose`; import `PoseIkResult`)
- Test: `tests/test_server_tools.py`

**Interfaces:**
- Consumes: Task 2's result keys, `MeshDisplacement` (already in schemas.py).
- Produces: dispatcher command `"pose_ik"`; MCP tool `maya_pose_ik(root, joint, target, pole?, start?, keep=True)`; `PoseIkResult`.

- [ ] **Step 1: Write the failing tests.** In `tests/test_server_tools.py`, add `"maya_pose_ik",` to the set in `test_session_tools_registered` (after `"maya_reset_pose",`), and append near the other rigging marshaling tests:

```python
    def test_pose_ik_marshals_and_omits_optionals(self):
        conn = FakeConn(responses={"pose_ik": {
            "achieved_position": [0.1, 0.6, 0.2], "residual": 0.0004,
            "rotations": {"|p|h": [0.0, 41.0, 0.0]},
            "chain": ["|p|h", "|p|h|k", "|p|h|k|a"],
            "pole_used": [0.1, 0.5, 0.5], "kept": True,
            "max_displacement": 0.31, "displaced_vertices": 140,
            "per_mesh": [{"mesh": "|m", "max_displacement": 0.31,
                          "displaced_vertices": 140}],
            "warnings": []}})
        mcp = server_mod.create_server(conn)
        result = run(mcp.call_tool("maya_pose_ik", {
            "root": "p", "joint": "a", "target": [0.1, 0.6, 0.2]}))
        assert conn.calls[0]["cmd"] == "pose_ik"
        assert conn.calls[0]["params"] == {
            "root": "p", "joint": "a", "target": [0.1, 0.6, 0.2],
            "keep": True}
        assert result.structured_content["residual"] == 0.0004

    def test_pose_ik_forwards_pole_start_keep(self):
        conn = FakeConn(responses={"pose_ik": {
            "achieved_position": [0, 0, 0], "residual": 0.9,
            "rotations": {}, "chain": [], "pole_used": None, "kept": False,
            "max_displacement": 0.0, "displaced_vertices": 0,
            "per_mesh": [], "warnings": ["keep=false: restored"]}})
        mcp = server_mod.create_server(conn)
        run(mcp.call_tool("maya_pose_ik", {
            "root": "p", "joint": "a", "target": [0, 0, 0],
            "pole": [0, 0, 1], "start": "hip", "keep": False}))
        params = conn.calls[0]["params"]
        assert params["pole"] == [0, 0, 1]
        assert params["start"] == "hip"
        assert params["keep"] is False
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_server_tools.py -q`. Expected: FAIL (registration set mismatch + unknown tool).

- [ ] **Step 3: Implement.** In `maya_plugin/maya_mcp_plugin.py`, after `"set_region_weights": rigging.set_region_weights,` add:

```python
        "pose_ik": rigging.pose_ik,
```

In `src/maya_mcp/schemas.py`, after `ResetPoseResult`:

```python
class PoseIkResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    achieved_position: List[float] = Field(
        description=(
            "Where the joint actually ENDED, measured from the scene after "
            "the bake - never the solver's claim."))
    residual: float = Field(
        description=(
            "Measured miss distance to the target. An unreachable target is "
            "a number here, not a silent stretch."))
    rotations: Dict[str, List[float]] = Field(
        description=(
            "The solve BAKED to plain FK: per-joint local euler DEGREES, "
            "keyed by long name - feed it straight to maya_pose_skeleton. "
            "No IK state survives in the scene."))
    chain: List[str] = Field(
        description="The joints that were solved, start..joint.")
    pole_used: Optional[List[float]] = Field(
        default=None,
        description=(
            "The pole world position the solve actually used: yours, or one "
            "derived from the chain's own bend plane, or null (straight "
            "chain, no pole - the fold direction was Maya's guess)."))
    kept: bool
    max_displacement: float
    displaced_vertices: int
    per_mesh: List[MeshDisplacement] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
```

In `src/maya_mcp/server.py`: add `PoseIkResult,` to the schemas import block, and after the `maya_reset_pose` tool:

```python
    @mcp.tool(
        title="Pose a limb to a world target (IK, baked to FK)",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=True
        ),
    )
    def maya_pose_ik(
        root: Annotated[str, Field(description="Skeleton root joint.")],
        joint: Annotated[str, Field(description=(
            "End of the chain to place - the ankle, the wrist."
        ))],
        target: Annotated[List[float], Field(description=(
            "World position [x, y, z] the joint should reach."
        ))],
        pole: Annotated[Optional[List[float]], Field(description=(
            "World position the knee/elbow should face. Default: the "
            "chain's own bend plane when it has one; a STRAIGHT chain "
            "without a pole leaves the fold direction to Maya and warns."
        ))] = None,
        start: Annotated[Optional[str], Field(description=(
            "Chain start joint. Default: two joints above `joint` - the "
            "classic 2-bone limb (hip for an ankle, shoulder for a wrist). "
            "Pass explicitly for longer chains."
        ))] = None,
        keep: Annotated[bool, Field(description=(
            "true bakes the solved pose; false measures it (residual, "
            "rotations, displacement), then restores the pose it found."
        ))] = True,
    ) -> PoseIkResult:
        """Solve a chain to a world target, bake to FK, delete the handle.

        No persistent IK state ever exists in the scene: the result's
        rotations map is the same currency maya_pose_skeleton speaks, so
        export, clips, and the pose contract are untouched. residual is
        the MEASURED miss - an unreachable target is a number, not a
        silent stretch. IK here is an authoring convenience: aim the ankle
        at a point instead of deriving per-joint local bend axes."""
        params = {"root": root, "joint": joint, "target": target,
                  "keep": keep}
        if pole is not None:
            params["pole"] = pole
        if start is not None:
            params["start"] = start
        return PoseIkResult.model_validate(
            maya.request("pose_ik", params, timeout_s=BOOL_TIMEOUT_S)
        )
```

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_server_tools.py -q` then `uv run pytest -q`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/maya_mcp_plugin.py src/maya_mcp/schemas.py src/maya_mcp/server.py tests/test_server_tools.py
git commit -m "feat(#671): maya_pose_ik MCP tool - 50 tools"
```

---

### Task 5: Protocol documentation

**Files:**
- Modify: `docs/protocol.md` (new section after the phase-2 commands section)

- [ ] **Step 1: Add the section** (match the file's existing style; place after the "Commands (rigging phase 2 / #668)" block):

```markdown
## Commands (rigging phase 3 / #671)

| cmd | params | result |
|---|---|---|
| `pose_ik` | `{ root, joint, target, pole?, start?, keep? }` | `{ achieved_position, residual, rotations, chain, pole_used, kept, max_displacement, displaced_vertices, per_mesh, warnings }` |

`pose_ik` solves a joint chain to a world-space `target`, **bakes the result
to plain FK rotations, and deletes the handle** — no persistent IK state
ever exists in the scene. The `rotations` map (per-joint local euler
degrees, long-name keys) is the phase-1 pose currency: feed it straight to
`pose_skeleton`, key it in a phase-6 clip. `residual` is the measured miss
distance — an unreachable target is a number, not a silent stretch, and the
reach shortfall is spelled out in `warnings`.

The chain runs `start..joint`; `start` defaults to two joints above
`joint` — the classic 2-bone limb (hip for an ankle, shoulder for a
wrist). `pole` is a world **position** the knee/elbow should face. When
omitted, a bent chain keeps its own bend plane; a perfectly straight chain
has no plane, so the fold direction is Maya's guess and a warning says so —
pass `pole` to make it deterministic (a straight chain is quietly pre-bent
a few degrees toward the pole so the RP solver can fold at all; the solve
overwrites the nudge).

`keep=false` solves, measures everything, then restores the pose the call
found — a dry-run for "what would this pose take". `achieved_position` and
all displacement numbers are re-read from the scene after the bake, never
taken from the solver's claim.
```

- [ ] **Step 2: Commit**

```bash
git add docs/protocol.md
git commit -m "docs(#671): protocol entry for pose_ik"
```

---

### Task 6: The live gate — the humanoid re-posed by targets

**Files:**
- Create: `evals/humanoid_ik_live.py`
- Create (by running it): `evals/humanoid_ik_live/baseline.json` + renders

**Interfaces:**
- Consumes: `evals/humanoid_live.py`'s module DATA (`JOINTS`, `PARTS`, `MESH`, `JOINT_COUNT`, `PIECES`, `EDGE_PROBE`, `EDGE_STRETCH_MAX`, `TEAR_GROWTH_MIN`, `EDGE_STRETCH_BACKSTOP`, `biped_pose`) — **humanoid_live.py is not modified**, so its 45/45 baseline stands without a re-run. Also `evals/golem_delivery/poses.json`, `evals/live_call.py`, the deployed plugin on port 9878.
- Produces: the phase-3 acceptance evidence.

**What the gate proves** (the spec's "re-posed in a fraction of the calls", made measurable):

- **Part A — equivalence:** for `crouch` and `extend`, first the FK pose (phase 2's `biped_pose` map — the map that COST phase 2 a measured bend-axis study and two failed runs), recording each limb end/mid joint's achieved world position. Reset. Then the same pose rebuilt from world TARGETS only: one `pose_skeleton` for the spine + ankle FK detail, then four `pose_ik` calls (L/R leg to the ankle positions with knee poles, L/R arm to the wrist positions with elbow poles). Assert residual < 5 mm per limb, per-joint world positions within 1.5 cm of the FK pose, per-edge tearing bounded by the same phase-2 ceilings, and displacement within 15% of FK's. **The IK path needs zero local-frame knowledge — that is the biped-preset verdict from #668 made concrete.**
- **Part B — target-first authoring:** an asymmetric `reach` pose no FK map exists for: right wrist to a point front-low across the body, left foot stepped up-and-forward — 2 `pose_ik` calls from targets alone. Residuals < 5 mm, tearing bounded, judged render.
- **Part C — purity and currency:** after every pose_ik: `ls(type="ikHandle") == []`, effectors, pole locators, constraints all gone; the merged rotation maps re-applied via `pose_skeleton` after a reset land the wrist/ankle within 1 mm of the IK-achieved positions; a deliberately unreachable target reports `residual ≈ miss` and warns; final reset returns every edge ratio to ≤ 1+1e-6.
- **Call accounting** recorded in baseline.json: posing calls per pose via IK (5) vs the phase-2 knowledge cost (the measured axis table + 2 failed gate runs documented in humanoid_live's docstring).

- [ ] **Step 1: Write `evals/humanoid_ik_live.py`:**

```python
"""Phase-3 gate for #671: the #668 humanoid re-posed by IK TARGETS.

Phase 2's FK poses required a measured bend-axis study (humanoid_live's
biped_pose docstring: local X is the twist axis on every vertical bone,
legs pitch about local Y, ankles about local Z - learned across two failed
gate runs). This gate re-poses the same humanoid from world-space targets
only, and measures that the knowledge cost is gone:

    1  build + bind + craft the SAME humanoid (constants imported from
       humanoid_live; that file and its 45/45 baseline are untouched)
    2  crouch + extend: FK first (the phase-2 map), then the same pose from
       TARGETS - 1 pose_skeleton (spine/ankle detail) + 4 pose_ik (limbs);
       residual < 5 mm, joints within 1.5 cm of FK, same tearing ceilings
    3  reach: an asymmetric pose NO FK map exists for - 2 pose_ik calls
    4  purity: zero ikHandle/ikEffector/constraint/locator nodes after
       every call; rotations re-applied via pose_skeleton reproduce the
       IK-achieved positions (the bake IS the phase-1 currency)
    5  honesty: an unreachable target reports the geometric miss and warns
    6  judged renders per posed state + baseline.json

DESTRUCTIVE: calls new_scene. Port 9878, the agent-launched Maya, per the
two-Maya policy - never point this at the user's 9877.

Run:  uv run python evals/humanoid_ik_live.py
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

from live_call import call, structured_result  # noqa: E402
from humanoid_live import (  # noqa: E402 - DATA only, that module runs nothing on import
    EDGE_PROBE, EDGE_STRETCH_BACKSTOP, EDGE_STRETCH_MAX, JOINT_COUNT, JOINTS,
    MESH, PARTS, PIECES, TEAR_GROWTH_MIN, biped_pose,
)

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
OUT_DIR = os.path.join(_HERE, "humanoid_ik_live")
POSES_PATH = os.path.join(_HERE, "golem_delivery", "poses.json")

RESIDUAL_MAX = 0.005          # 5 mm on a 2 m figure
FK_MATCH_MAX = 0.015          # per-joint world-position agreement with FK
CURRENCY_MAX = 0.001          # rotations re-applied must land within 1 mm
LIMBS = {                     # joint -> (chain end, pole joint) per limb
    "L_ankle": "L_knee", "R_ankle": "R_knee",
    "L_wrist": "L_elbow", "R_wrist": "R_elbow",
}
# The pole must sit OFF the chain, on the side the joint should fold
# toward; the FK pose's own mid-joint position IS that point.
FK_DETAIL = ("spine_01", "spine_02", "chest", "L_ankle", "R_ankle")

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
        print("FAIL: %s: %s" % (command, json.dumps(response.get("error"))[:600]))
        sys.exit(1)
    return response.get("result") or {}


def py(code, what, timeout_s=300.0):
    return structured_result(ok("execute_python", {"code": code}, timeout_s), what)


def out(name):
    return os.path.join(OUT_DIR, name)


def edge_probe(store, what):
    return py(EDGE_PROBE % {"mesh": "|" + MESH, "store": repr(bool(store)),
                            "grow": TEAR_GROWTH_MIN}, what)


def render(tag):
    params = {"angles": ["front", "side"], "target": ["|" + MESH],
              "resolution": 640, "samples": 3, "renderer": "arnold"}
    response = send("render_scene", params, timeout_s=900.0)
    if response.get("status") != "ok":
        params["renderer"] = "hw2"
        response = send("render_scene", params, timeout_s=900.0)
    if response.get("status") != "ok":
        check("render %s" % tag, False, json.dumps(response.get("error"))[:200])
        return
    for image in response["result"]["images"]:
        with open(out("ik_%s_%s.png" % (tag, image["angle"])), "wb") as fh:
            fh.write(base64.b64decode(image["png_b64"]))
    check("render %s" % tag, True,
          "renderer=%s" % response["result"].get("renderer"))


def no_ik_state(tag):
    left = py(
        "import maya.cmds as cmds\n"
        "{'handles': cmds.ls(type='ikHandle') or [],\n"
        " 'effectors': cmds.ls(type='ikEffector') or [],\n"
        " 'constraints': cmds.ls(type='poleVectorConstraint') or [],\n"
        " 'locators': cmds.ls('*_pole*', type='transform') or []}",
        "%s: IK leftovers" % tag)
    check("%s: no IK state survives" % tag,
          not any(left.values()), json.dumps(left))


def joint_positions(root):
    posed = ok("pose_skeleton", {"root": root, "rotations": {"pelvis": [0, 0, 0]}})
    return {j["name"].split("|")[-1]: j["world_position"]
            for j in posed["joints"]}


def edge_checks(tag, at_bind):
    probe = edge_probe(store=False, what="%s edge probe" % tag)
    check("%s: no visible tear past %.1fx" % (tag, EDGE_STRETCH_MAX),
          probe["max_visible_ratio"] <= EDGE_STRETCH_MAX,
          "visible=%.3f unfiltered=%.3f"
          % (probe["max_visible_ratio"], probe["max_edge_ratio"]))
    check("%s: under the %.1fx backstop" % (tag, EDGE_STRETCH_BACKSTOP),
          probe["max_edge_ratio"] <= EDGE_STRETCH_BACKSTOP)
    check("%s: topology unchanged" % tag,
          probe["shells"] == PIECES and probe["edges"] == at_bind["edges"])
    return probe


def dist(a, b):
    return sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5


def main():
    if PORT == 9877:
        print("refusing to run on 9877: this eval discards the open scene "
              "(two-Maya policy). Launch a disposable Maya on 9878.")
        return 2

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(POSES_PATH) as fh:
        golem_poses = json.load(fh)
    identity = py("import os\n{'pid': os.getpid()}", "identity")
    print("Maya on %d: pid %s, writing to %s\n" % (PORT, identity["pid"], OUT_DIR))

    # ---- 1. the phase-2 humanoid, verbatim ------------------------------
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
       "scale=True, normal=0, preserveNormals=True)\nTrue" % ("|" + MESH),
       "freeze the combined mesh")
    skeleton = ok("create_skeleton", {"joints": JOINTS})
    check("skeleton built all %d joints" % JOINT_COUNT,
          len(skeleton["joints"]) == JOINT_COUNT)
    root = skeleton["root"]
    bind = ok("bind_skin", {"mesh": "|" + MESH, "root": root}, timeout_s=600.0)
    check("bind leaves no vertex unowned", bind["unweighted_vertices"] == 0)
    at_bind = edge_probe(store=True, what="bind edge baseline")

    # the phase-2 craft pass, verbatim (see humanoid_live.py for the
    # measured rationale of every number)
    torso_faces = py(
        "import maya.cmds as cmds\n"
        "_f = cmds.polySelect(%r, extendToShell=0, noSelection=True)\n"
        "{'faces': [int(i) for i in _f]}" % ("|" + MESH), "torso shell faces")
    ok("set_region_weights", {"mesh": "|" + MESH, "joint": "chest",
                              "faces": torso_faces["faces"], "weight": 0.85})
    ok("set_region_weights", {"mesh": "|" + MESH, "joint": "L_shoulder",
                              "within_radius_of": [0.32, 1.50, 0.0],
                              "radius": 0.11, "weight": 0.9,
                              "falloff": "linear"})
    ok("mirror_weights", {"mesh": "|" + MESH, "axis": "x"})
    ok("smooth_weights", {"mesh": "|" + MESH,
                          "joints": ["L_hip", "R_hip", "L_shoulder",
                                     "R_shoulder"], "iterations": 2})
    report = ok("weight_report", {"mesh": "|" + MESH})
    check("crafted weights are clean",
          report["unweighted_vertices"] == 0
          and report["max_influences_exceeded"] == 0)
    ok("setup_lighting", {"preset": "three_point"})

    baseline = {"poses": {}, "purity": {}, "honesty": {}}

    # ---- 2. equivalence: crouch + extend, FK then TARGETS ----------------
    for pose_name in ("crouch", "extend"):
        fk_map = biped_pose(golem_poses[pose_name]["joints_deg"])
        fk = ok("pose_skeleton", {"root": root, "rotations": fk_map})
        fk_joints = {j["name"].split("|")[-1]: j["world_position"]
                     for j in fk["joints"]}
        fk_probe = edge_checks("%s FK" % pose_name, at_bind)
        render("%s_fk" % pose_name)
        ok("reset_pose", {"root": root})

        # target-first: spine/ankle FK detail, then four limbs by TARGET
        detail = {j: fk_map[j] for j in FK_DETAIL if j in fk_map}
        calls = 0
        ok("pose_skeleton", {"root": root, "rotations": detail})
        calls += 1
        merged = dict(detail)
        residuals = {}
        for end_joint, mid_joint in LIMBS.items():
            solved = ok("pose_ik", {
                "root": root, "joint": end_joint,
                "target": fk_joints[end_joint],
                "pole": fk_joints[mid_joint]})
            calls += 1
            residuals[end_joint] = solved["residual"]
            merged.update(solved["rotations"])
            check("%s IK: %s residual < %.0f mm"
                  % (pose_name, end_joint, RESIDUAL_MAX * 1000),
                  solved["residual"] < RESIDUAL_MAX,
                  "residual=%.4f warnings=%s"
                  % (solved["residual"], solved["warnings"]))
        no_ik_state("%s IK" % pose_name)

        ik_joints = joint_positions(root)
        worst = max((dist(ik_joints[j], fk_joints[j]), j) for j in fk_joints)
        check("%s IK: joints match FK within %.1f cm"
              % (pose_name, FK_MATCH_MAX * 100), worst[0] < FK_MATCH_MAX,
              "worst=%.4f at %s" % worst)
        ik_probe = edge_checks("%s IK" % pose_name, at_bind)
        render("%s_ik" % pose_name)
        baseline["poses"][pose_name] = {
            "posing_calls_ik": calls, "residuals": residuals,
            "fk_worst_match": worst[0],
            "fk_max_visible_ratio": fk_probe["max_visible_ratio"],
            "ik_max_visible_ratio": ik_probe["max_visible_ratio"],
            "merged_rotations": merged,
        }
        ok("reset_pose", {"root": root})

    # ---- 3. reach: target-first authoring, no FK map exists --------------
    reach_targets = {
        "R_wrist": {"target": [0.15, 1.05, 0.35], "pole": [-0.5, 1.35, 0.25]},
        "L_ankle": {"target": [0.18, 0.30, 0.30], "pole": [0.22, 0.65, 0.55]},
    }
    merged = {}
    residuals = {}
    achieved = {}
    for end_joint, spec in reach_targets.items():
        solved = ok("pose_ik", {"root": root, "joint": end_joint,
                                "target": spec["target"],
                                "pole": spec["pole"]})
        residuals[end_joint] = solved["residual"]
        achieved[end_joint] = solved["achieved_position"]
        merged.update(solved["rotations"])
        check("reach: %s residual < %.0f mm"
              % (end_joint, RESIDUAL_MAX * 1000),
              solved["residual"] < RESIDUAL_MAX,
              "residual=%.4f" % solved["residual"])
    no_ik_state("reach")
    edge_checks("reach", at_bind)
    render("reach")
    baseline["poses"]["reach"] = {"posing_calls_ik": 2,
                                  "residuals": residuals,
                                  "merged_rotations": merged}

    # ---- 4. the bake IS the phase-1 currency ------------------------------
    ok("reset_pose", {"root": root})
    ok("pose_skeleton", {"root": root, "rotations": merged})
    replayed = joint_positions(root)
    for end_joint in reach_targets:
        err = dist(replayed[end_joint], achieved[end_joint])
        check("currency: %s replays within %.0f mm"
              % (end_joint, CURRENCY_MAX * 1000), err < CURRENCY_MAX,
              "err=%.5f" % err)
    baseline["purity"]["currency_max_err"] = max(
        dist(replayed[j], achieved[j]) for j in reach_targets)
    ok("reset_pose", {"root": root})

    # ---- 5. honesty: an unreachable target is a number --------------------
    miss = ok("pose_ik", {"root": root, "joint": "R_wrist",
                          "target": [-3.0, 1.5, 0.0], "pole": [-0.5, 1.2, 0.5]})
    check("honesty: unreachable target reports a residual > 2",
          miss["residual"] > 2.0, "residual=%.3f" % miss["residual"])
    check("honesty: the reach warning fired",
          any("reaches only" in w for w in miss["warnings"]),
          "; ".join(miss["warnings"]))
    baseline["honesty"] = {"residual": miss["residual"],
                           "warnings": miss["warnings"]}
    ok("reset_pose", {"root": root})
    final = edge_probe(store=False, what="final reset probe")
    check("final reset returns the mesh to bind",
          final["max_edge_ratio"] <= 1.0 + 1e-6,
          "max_edge_ratio=%.6f" % final["max_edge_ratio"])

    with open(out("baseline.json"), "w") as fh:
        json.dump(baseline, fh, indent=2, sort_keys=True)

    print("\n" + "=" * 72)
    print("JUDGE: every *_ik render must read as the SAME pose as its *_fk")
    print("twin, and 'reach' as a plausible asymmetric reach - one continuous")
    print("body, no candy-wrapper pinch, no tearing. Renders: %s" % OUT_DIR)
    print("=" * 72 + "\n")

    failed = [label for passed, label in CHECKS if not passed]
    print("%d/%d checks passed" % (len(CHECKS) - len(failed), len(CHECKS)))
    for label in failed:
        print("  FAILED: %s" % label)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Deploy and launch the gate Maya.**

```bash
uv run python maya_plugin/install.py --yes
```

Then from a **neutral cwd** (never the repo — #604's sys.path trap):

```bash
cd ~ && MAYA_MCP_PORT=9878 "E:/Autodesk/Maya2027/bin/maya.exe" &
```

Verify the pid answering 9878 is the one just launched (#648): `netstat -ano | findstr 9878`, match against the launched process, `taskkill /F /T` any stale claimant first, and confirm the port actually released before relaunching. Confirm via ping that `restart_required` is false and `package_dir` is the Documents deploy, not the repo.

- [ ] **Step 3: Run the gate** — `uv run python evals/humanoid_ik_live.py`. Expected: exit 0, all checks PASS, renders written. Judge the renders (implementer first, then the controlling session — the #668 precedent): each `*_ik` render must read as the same pose as its `*_fk` twin; `reach` must read as a plausible asymmetric reach. If a check fails: systematic-debugging, fix at the source (handler or math, never by loosening a gate number without a measured justification recorded in the eval's comments).

- [ ] **Step 4: Serpent regression** — `uv run python evals/serpent_live.py` against the same Maya. Expected: 25/25 — phase 3 must not have moved phase 1.

- [ ] **Step 5: Commit**

```bash
git add evals/humanoid_ik_live.py evals/humanoid_ik_live/
git commit -m "feat(#671): humanoid IK live gate - target-first posing, purity, currency, honesty"
```

---

### Task 7: Final verification and close-out

- [ ] **Step 1: Full suites once more on the finished branch** — `uv run pytest -q` and `E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q`. Expected: green, counts above 1135/119.
- [ ] **Step 2: requesting-code-review** — dispatch a reviewer against the spec section and this plan; address findings (superpowers:receiving-code-review).
- [ ] **Step 3: finishing-a-development-branch** — merge decision per the skill.
- [ ] **Step 4: Redmine** — one `update_issue` on #671: measured numbers (residuals, call counts, suite counts, gate verdict), status Resolved.

## Self-review notes

- Spec coverage: the Phase 3 section's whole contract (solve → bake → delete, residual measured, pose currency untouched) is Tasks 1–4; the gate deliverable ("humanoid re-posed in a fraction of the calls") is Task 6, sharpened into the equivalence/target-first/purity/honesty quartet. The `start` param and world-position `pole` are plan-level refinements recorded under "Contract decisions".
- The known-unknowns (IK evaluation pull in mayapy, pre-bend sufficiency) are isolated in Task 3 with an explicit fallback ladder, so a surprise there cannot silently reshape later tasks.
- Type consistency: result keys in Task 2's handler == Task 4's `PoseIkResult` fields == Task 6's reads (`residual`, `rotations`, `achieved_position`, `warnings`, `per_mesh`) — checked by name.
