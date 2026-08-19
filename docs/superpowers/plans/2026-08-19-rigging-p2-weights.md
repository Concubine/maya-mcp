# Rigging Phase 2 — weights craft + the humanoid (#668) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Four new commands — `mirror_weights`, `smooth_weights`, `set_region_weights`, `weight_report` — plus per-mesh displacement reporting in `pose_skeleton` (review item a) and honest multi-mesh skin-violation messages in export (item b), gated by the ~20-joint humanoid posed through the golem five-pose set, judged renders + a per-edge tearing detector (item c).

**Architecture:** All weight-table math is pure Python in `rigmath.py` (headless-tested): vertex/influence mirror pairing by reflected position, laplacian smoothing with influence pruning, radius/face region factors, and report stats. `rigging.py` grows only IO: one shared table reader already exists (`_skin_weights`), this phase adds the shared writer (`_set_skin_weights` via `MFnSkinCluster.setWeights`), a skinCluster locator, and a vertex-adjacency reader. Every mutator re-reads the table after writing and reports MEASURED post-op integrity (unweighted vertices, changed rows) — a craft op must never silently break the bind gate.

**Tech Stack:** Python (Maya-embedded + plain), `maya.cmds`, `maya.api.OpenMaya`/`OpenMayaAnim`, pytest, existing stdlib FBX byte reader.

**Design spec:** `docs/superpowers/specs/2026-08-19-rigging-surface-design.md`, Phase 2 section. Ticket: #668.

## Decisions this plan locks (the ticket's open questions)

- **Mirror is pure math, not `copySkinWeights`.** Maya's mirror has direction/association semantics we would have to measure and then trust; positional pairing (vertex → nearest reflected vertex, influence → nearest reflected influence) is deterministic, headless-testable, and fails legibly (unpaired counts, refusal on an asymmetric skeleton).
- **`preset="biped"` is NOT built this phase.** The humanoid eval hand-lists its 20 joints; the eval prints how that felt (line count, error count) and the verdict is recorded on #668 at gate time. (Spec: "decide with the humanoid build in hand".)
- **Item (e): `bind_skin`'s mid-chain-root warning STAYS a warning.** Region weights edit an existing bind's influences; nothing in phase 2 makes sub-joint binds more attractive, and the warning already names the pulled-in joints. Recorded here so the first commit does not relitigate it.
- **Item (d)** (unskinned scene with a scaled joint refuses export): no change; note stands in #668, revisit only if the humanoid run hits it.
- **Item (f)** (blend-shape "Indexes" records): phase-5 note, no phase-2 action.
- **Weight ops require an existing bind** and refuse otherwise (hint: `bind_skin` first). They operate on the mesh's one skinCluster (re-binding is already refused, so one is all there can be).
- **Mirror direction currency:** `direction="+to-"` (default) copies the +axis side onto the −axis side; `"-to+"` reverses. Author left (+X, Maya convention), mirror to right.

## Global Constraints

- **Branch:** create `rigging-p2-weights` from `main` (at 11f5d98) before the first change. Run `git status` and `git branch --show-current` FIRST — if foreign edits appear (the demigul-art agent shares this machine), stop and report. Never touch `evals/demigol_*`, `shard_*` files, or branch `shards-delivery`.
- **Angles are degrees at every boundary** (#636); positions are scene units under the metre-authoring convention (#629/#634).
- **Results carry measured numbers**: after every weight write, re-read the table and report from the re-read, never from the computed table (`assemble`'s pivot rule).
- **Silence is never an answer**: unpaired vertices, sole-owner vertices, posed-mesh mirroring — all go to `warnings`.
- **Mutating commands call `session.auto_checkpoint` exactly once**, after validation, before the first scene change. `weight_report` is a measurement: NO checkpoint.
- Headless suite: `uv run pytest -q` from repo root — currently 1073 passed + 1 skipped; must stay green with no Maya installed.
- Mayapy suite: `E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q` — currently 110 passed + 1 skipped.
- Two-Maya policy: the live gate runs against a disposable agent-launched Maya on port **9878** with a **neutral cwd** (a repo cwd makes Maya import the repo plugin and bypass the deploy — #604); verify the answering **pid** (#648). Never `new_scene` on the user's 9877. Deploy first: `uv run python maya_plugin/install.py --yes`.
- Commit style: `feat(#668): <what>` / `test(#668): <what>` / `docs(#668): <what>`, each task ends committed.
- Error style: `HandlerError(message, hint=...)`.
- `WEIGHT_TOL = 1e-4` (rigmath) is the existing "is this an influence at all" threshold — reuse it, never invent a second one.

## File Structure

| File | Responsibility |
|---|---|
| `maya_plugin/handlers/rigmath.py` (modify) | Pure math: row normalize/prune, changed-row diff, report stats, mirror pairing/table, smoothing, region factors/apply. No Maya imports. |
| `maya_plugin/handlers/rigging.py` (modify) | Four new handlers (IO only) + `_skin_cluster_for`, `_set_skin_weights`, `_vertex_adjacency`, `_resolve_influence`; `pose_skeleton` gains `per_mesh`. |
| `maya_plugin/handlers/export.py` (modify) | Item (b): skin-violation messages qualified for multi-deformer files; the clusters==0 message stops asserting an unmeasured cause. |
| `maya_plugin/maya_mcp_plugin.py` (modify) | Registers the four commands. |
| `src/maya_mcp/schemas.py` (modify) | `WeightReportResult`, `MirrorWeightsResult`, `SmoothWeightsResult`, `SetRegionWeightsResult`, `MeshDisplacement`, `PoseSkeletonResult.per_mesh`. |
| `src/maya_mcp/server.py` (modify) | Four MCP tools (49 total). |
| `tests/test_rigmath.py`, `tests/test_rigging.py`, `tests/test_server_tools.py`, `tests/test_export_fbx.py`, `tests/test_handlers_mayapy.py` (modify) | Coverage per leg. |
| `docs/protocol.md` (modify) | "Commands (rigging phase 2 / #668)" section; `pose_skeleton` row gains `per_mesh`. |
| `evals/humanoid_live.py` (create), `evals/humanoid_live/` (outputs) | The phase gate. |

---

### Task 1: rigmath weight-table primitives

**Files:**
- Modify: `maya_plugin/handlers/rigmath.py`
- Test: `tests/test_rigmath.py`

**Interfaces:**
- Produces: `rigmath.normalize_row(row: List[float]) -> List[float]` (all-zero stays all-zero); `rigmath.prune_row(row, max_influences: int) -> List[float]` (keep the largest N, renormalize); `rigmath.changed_rows(before: List[float], after: List[float], ncols: int, tol=WEIGHT_TOL) -> int` (rows where any column moved more than tol; raises ValueError on length mismatch, same message style as `displaced_count`).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_rigmath.py`:

```python
class TestRowPrimitives:
    def test_normalize_row_sums_to_one(self):
        assert rigmath.normalize_row([1.0, 3.0]) == [0.25, 0.75]

    def test_normalize_all_zero_row_stays_zero(self):
        assert rigmath.normalize_row([0.0, 0.0]) == [0.0, 0.0]

    def test_prune_keeps_the_largest_and_renormalizes(self):
        out = rigmath.prune_row([0.5, 0.3, 0.15, 0.05], 2)
        assert out == pytest.approx([0.625, 0.375, 0.0, 0.0])

    def test_prune_with_room_changes_nothing(self):
        assert rigmath.prune_row([0.6, 0.4, 0.0], 4) == pytest.approx([0.6, 0.4, 0.0])

    def test_changed_rows_counts_rows_not_cells(self):
        before = [1.0, 0.0, 0.5, 0.5]
        after = [0.0, 1.0, 0.5, 0.5]          # row 0: both cells moved
        assert rigmath.changed_rows(before, after, 2) == 1

    def test_changed_rows_ignores_float_dust(self):
        assert rigmath.changed_rows([1.0, 0.0], [1.0 - 1e-6, 1e-6], 2) == 0

    def test_changed_rows_refuses_mismatched_tables(self):
        with pytest.raises(ValueError, match="not the same"):
            rigmath.changed_rows([1.0], [1.0, 0.0], 2)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_rigmath.py::TestRowPrimitives -q`
Expected: FAIL — `AttributeError: ... has no attribute 'normalize_row'`

- [ ] **Step 3: Implement** — append to `maya_plugin/handlers/rigmath.py`:

```python
def normalize_row(row: List[float]) -> List[float]:
    """One vertex's weights scaled to sum 1. An all-zero row has nothing to
    scale and stays zero - the caller counts it as unweighted, not an error."""
    total = sum(row)
    if total <= 0.0:
        return list(row)
    return [w / total for w in row]


def prune_row(row: List[float], max_influences: int) -> List[float]:
    """Keep the max_influences largest weights, zero the rest, renormalize.
    Smoothing bleeds weight onto every neighbouring influence; without this
    every smooth pass would grow influence counts past what bind_skin promised
    the exporter."""
    keep = set(sorted(range(len(row)), key=lambda j: row[j], reverse=True)
               [:max_influences])
    return normalize_row([row[j] if j in keep else 0.0
                          for j in range(len(row))])


def changed_rows(before: List[float], after: List[float], ncols: int,
                 tol: float = WEIGHT_TOL) -> int:
    """How many vertices' weight rows actually differ - the measured 'what did
    this op do' number every weight mutator reports."""
    if len(before) != len(after) or (ncols and len(before) % ncols):
        raise ValueError(
            "weight tables are %d and %d entries - not the same table"
            % (len(before), len(after)))
    changed = 0
    for v in range(0, len(before), ncols):
        if any(abs(after[v + j] - before[v + j]) > tol for j in range(ncols)):
            changed += 1
    return changed
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_rigmath.py -q`
Expected: PASS (all, including phase-1 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/test_rigmath.py maya_plugin/handlers/rigmath.py
git commit -m "feat(#668): weight-table row primitives - normalize, prune, changed-row diff"
```

---

### Task 2: rigmath.weight_report_stats

**Files:**
- Modify: `maya_plugin/handlers/rigmath.py`
- Test: `tests/test_rigmath.py`

**Interfaces:**
- Consumes: `weight_stats(influences, weights, num_verts, max_influences)` (phase 1).
- Produces: `rigmath.weight_report_stats(influences, weights, num_verts, max_influences, sample=8) -> dict` with keys: everything `weight_stats` returns, plus `unweighted_sample: List[int]`, `exceeded_sample: List[int]` (first `sample` offending vertex ids), `max_weight_sum_error: float` (over vertices holding ANY weight; `0.0` when none do), `histogram: List[{"influences": int, "vertices": int}]` sorted by influence count.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_rigmath.py`:

```python
class TestWeightReportStats:
    # 3 verts x 2 joints: v0 owned by j0, v1 split, v2 unweighted
    TABLE = [1.0, 0.0,   0.6, 0.4,   0.0, 0.0]

    def test_report_carries_the_stats_plus_samples(self):
        out = rigmath.weight_report_stats(["j0", "j1"], self.TABLE, 3, 4)
        assert out["unweighted_vertices"] == 1
        assert out["unweighted_sample"] == [2]
        assert out["exceeded_sample"] == []
        assert out["per_joint"][0]["vertices"] == 2

    def test_histogram_buckets_by_influence_count(self):
        out = rigmath.weight_report_stats(["j0", "j1"], self.TABLE, 3, 4)
        assert out["histogram"] == [
            {"influences": 0, "vertices": 1},
            {"influences": 1, "vertices": 1},
            {"influences": 2, "vertices": 1}]

    def test_weight_sum_error_measures_held_rows_only(self):
        table = [0.7, 0.2,   0.0, 0.0]      # v0 sums to 0.9, v1 holds nothing
        out = rigmath.weight_report_stats(["a", "b"], table, 2, 4)
        assert out["max_weight_sum_error"] == pytest.approx(0.1)

    def test_exceeded_sample_lists_the_offenders(self):
        table = [0.4, 0.3, 0.3,   1.0, 0.0, 0.0]
        out = rigmath.weight_report_stats(["a", "b", "c"], table, 2, 2)
        assert out["max_influences_exceeded"] == 1
        assert out["exceeded_sample"] == [0]

    def test_sample_lists_are_capped(self):
        table = [0.0] * 20                   # 10 verts x 2, all unweighted
        out = rigmath.weight_report_stats(["a", "b"], table, 10, 4, sample=3)
        assert out["unweighted_vertices"] == 10
        assert out["unweighted_sample"] == [0, 1, 2]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_rigmath.py::TestWeightReportStats -q`
Expected: FAIL — no attribute `weight_report_stats`

- [ ] **Step 3: Implement** — append to `maya_plugin/handlers/rigmath.py`:

```python
def weight_report_stats(influences: List[str], weights: List[float],
                        num_verts: int, max_influences: int,
                        sample: int = 8) -> Dict[str, Any]:
    """weight_stats plus what an agent needs to ACT on a bad bind: which
    vertices offend (sample ids for set_region_weights targeting), how far
    sums drift, and the influence-count histogram that makes 'one joint owns
    everything' and 'weights smeared across eight joints' both legible."""
    out = weight_stats(influences, weights, num_verts, max_influences)
    ncols = len(influences)
    unweighted_sample: List[int] = []
    exceeded_sample: List[int] = []
    histogram: Dict[int, int] = {}
    max_err = 0.0
    for v in range(num_verts):
        held = 0
        total = 0.0
        for j in range(ncols):
            w = weights[v * ncols + j]
            total += w
            if w > WEIGHT_TOL:
                held += 1
        histogram[held] = histogram.get(held, 0) + 1
        if held == 0:
            if len(unweighted_sample) < sample:
                unweighted_sample.append(v)
        else:
            max_err = max(max_err, abs(total - 1.0))
        if held > max_influences and len(exceeded_sample) < sample:
            exceeded_sample.append(v)
    out["unweighted_sample"] = unweighted_sample
    out["exceeded_sample"] = exceeded_sample
    out["max_weight_sum_error"] = max_err
    out["histogram"] = [{"influences": k, "vertices": histogram[k]}
                        for k in sorted(histogram)]
    return out
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_rigmath.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_rigmath.py maya_plugin/handlers/rigmath.py
git commit -m "feat(#668): weight_report_stats - samples, sum error, influence histogram"
```

---

### Task 3: `weight_report` end-to-end (handler, dispatcher, schema, MCP tool)

**Files:**
- Modify: `maya_plugin/handlers/rigging.py`, `maya_plugin/maya_mcp_plugin.py`, `src/maya_mcp/schemas.py`, `src/maya_mcp/server.py`
- Test: `tests/test_rigging.py`, `tests/test_server_tools.py`, `tests/test_handlers_mayapy.py`

**Interfaces:**
- Consumes: `_skin_weights(sc, mesh_shape)`, `rigmath.weight_report_stats`, `naming.require_mesh`.
- Produces: handler `rigging.weight_report(params) -> {mesh, skin_cluster, vertices, max_influences, unweighted_vertices, unweighted_sample, max_influences_exceeded, exceeded_sample, max_weight_sum_error, histogram, per_joint, warnings}`; shared `rigging._skin_cluster_for(cmds, mesh_long, mesh_shape) -> str` (raises HandlerError "not bound" with hint "bind_skin first"); MCP tool `maya_weight_report` (read_only_hint=True); command name `weight_report`; schema `WeightReportResult` (+ `InfluenceBucket`).

- [ ] **Step 1: Write the failing headless tests** — append to `tests/test_rigging.py`:

```python
class TestWeightReport:
    def _bound_mesh(self, fake, monkeypatch):
        fake.objects.append("|serpent")
        fake.shapes = {"|serpent": "|serpent|serpentShape"}
        def listRelatives(node, shapes=False, **kw):
            if shapes:
                return [fake.shapes.get(node)]
            return FakeCmds.listRelatives(fake, node, **kw)
        fake.listRelatives = listRelatives
        fake.skin_history = ["skin1"]
        fake.attrs["skin1.maxInfluences"] = 4
        # 3 verts x 2 joints: v2 unweighted
        monkeypatch.setattr(
            rigging, "_skin_weights",
            lambda sc, shape: (["|r|a", "|r|b"],
                               [1.0, 0.0, 0.6, 0.4, 0.0, 0.0], 3))

    def test_report_is_measured_and_never_checkpoints(self, fake, monkeypatch):
        self._bound_mesh(fake, monkeypatch)
        monkeypatch.setattr(session, "auto_checkpoint",
                            lambda reason: pytest.fail("a measurement checkpointed"))
        out = rigging.weight_report({"mesh": "serpent"})
        assert out["skin_cluster"] == "skin1"
        assert out["vertices"] == 3
        assert out["max_influences"] == 4
        assert out["unweighted_vertices"] == 1
        assert out["unweighted_sample"] == [2]
        assert any("belong to NO joint" in w for w in out["warnings"])

    def test_unbound_mesh_is_refused_with_the_bind_hint(self, fake, monkeypatch):
        self._bound_mesh(fake, monkeypatch)
        fake.skin_history = []
        with pytest.raises(HandlerError, match="not bound") as err:
            rigging.weight_report({"mesh": "serpent"})
        assert "bind_skin" in err.value.hint
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_rigging.py::TestWeightReport -q`
Expected: FAIL — no attribute `weight_report`

- [ ] **Step 3: Implement handler** — append to `maya_plugin/handlers/rigging.py`:

```python
def _skin_cluster_for(cmds, mesh_long: str, mesh_shape: str) -> str:
    """The mesh's one skinCluster. One is all there can be: bind_skin refuses
    stacking, and every weight op edits an existing bind rather than guessing."""
    existing = cmds.ls(cmds.listHistory(mesh_shape, pruneDagObjects=True) or [],
                       type="skinCluster") or []
    if not existing:
        raise HandlerError(
            "%s is not bound" % mesh_long,
            hint="bind_skin first - weight ops edit an existing skinCluster")
    return existing[0]


def weight_report(params: Dict[str, Any]) -> Dict[str, Any]:
    """The perception tool: how an agent judges weights without a viewport.
    A measurement - no checkpoint, nothing in the scene changes."""
    cmds = _cmds()
    mesh_long, mesh_shape = naming.require_mesh(cmds, str(params.get("mesh") or ""))
    sc = _skin_cluster_for(cmds, mesh_long, mesh_shape)
    max_influences = int(cmds.getAttr(sc + ".maxInfluences"))
    influences, weights, num_verts = _skin_weights(sc, mesh_shape)
    stats = rigmath.weight_report_stats(influences, weights, num_verts,
                                        max_influences)
    warnings: List[str] = []
    if stats["unweighted_vertices"]:
        warnings.append(
            "%d vertices belong to NO joint - they stay behind when the "
            "creature moves. set_region_weights can hand them to a joint; "
            "unweighted_sample says where to aim."
            % stats["unweighted_vertices"])
    if stats["max_influences_exceeded"]:
        warnings.append(
            "%d vertices carry more than the cluster's max_influences=%d"
            % (stats["max_influences_exceeded"], max_influences))
    empty = [p["joint"] for p in stats["per_joint"] if p["vertices"] == 0]
    if empty:
        warnings.append(
            "%d joint(s) own no vertices: %s"
            % (len(empty), ", ".join(_short(j) for j in empty[:8])))
    return {
        "mesh": mesh_long,
        "skin_cluster": sc,
        "vertices": num_verts,
        "max_influences": max_influences,
        "unweighted_vertices": stats["unweighted_vertices"],
        "unweighted_sample": stats["unweighted_sample"],
        "max_influences_exceeded": stats["max_influences_exceeded"],
        "exceeded_sample": stats["exceeded_sample"],
        "max_weight_sum_error": stats["max_weight_sum_error"],
        "histogram": stats["histogram"],
        "per_joint": stats["per_joint"],
        "warnings": warnings,
    }
```

Also refactor `bind_skin` to use `_skin_cluster_for`'s query for its rebind check? **No** — bind_skin's refusal message ("already bound") is the inverse condition; leave it.

- [ ] **Step 4: Register the command** — `maya_plugin/maya_mcp_plugin.py`, in the handlers map after `"reset_pose"`:

```python
        "weight_report": rigging.weight_report,
```

- [ ] **Step 5: Run headless rigging tests**

Run: `uv run pytest tests/test_rigging.py -q`
Expected: PASS

- [ ] **Step 6: Schema** — `src/maya_mcp/schemas.py`, after `ResetPoseResult`:

```python
class InfluenceBucket(BaseModel):
    model_config = ConfigDict(extra="ignore")

    influences: int
    vertices: int


class WeightReportResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mesh: str
    skin_cluster: str
    vertices: int
    max_influences: int = Field(
        description="The cluster's own ceiling, measured from the node.")
    unweighted_vertices: int
    unweighted_sample: List[int] = Field(
        description="First few unowned vertex ids - set_region_weights targets.")
    max_influences_exceeded: int
    exceeded_sample: List[int]
    max_weight_sum_error: float
    histogram: List[InfluenceBucket] = Field(
        description=(
            "Vertices bucketed by how many joints meaningfully hold them. "
            "'One joint owns everything' and 'weights smeared over eight "
            "joints' are both legible here."))
    per_joint: List[SkinJointStats]
    warnings: List[str] = Field(default_factory=list)
```

- [ ] **Step 7: MCP tool** — `src/maya_mcp/server.py`: import `WeightReportResult`, then after `maya_reset_pose`:

```python
    @mcp.tool(
        title="Report skin weights",
        annotations=ToolAnnotations(read_only_hint=True),
    )
    def maya_weight_report(
        mesh: Annotated[str, Field(description="A bound mesh (long name).")],
    ) -> WeightReportResult:
        """MEASURE a bind's weights: the perception tool for weights craft.

        Judge a bind from this plus a posed render, the way get_object_info
        serves modeling: per-joint ownership, unweighted vertices (with sample
        ids to aim set_region_weights at), influence-count histogram, and
        weight-sum drift. Read-only."""
        return WeightReportResult.model_validate(
            maya.request("weight_report", {"mesh": mesh},
                         timeout_s=BOOL_TIMEOUT_S)
        )
```

- [ ] **Step 8: Server-tool test** — append to `tests/test_server_tools.py`, following the file's existing fake-request pattern for phase-1 tools (find `maya_bind_skin`'s test and copy its structure):

```python
    async def test_weight_report_marshals_and_validates(self, server_and_fake):
        server, fake = server_and_fake
        fake.responses["weight_report"] = {
            "mesh": "|h", "skin_cluster": "hSkin", "vertices": 8,
            "max_influences": 4, "unweighted_vertices": 0,
            "unweighted_sample": [], "max_influences_exceeded": 0,
            "exceeded_sample": [], "max_weight_sum_error": 0.0,
            "histogram": [{"influences": 2, "vertices": 8}],
            "per_joint": [{"joint": "|r|a", "vertices": 8, "mean_weight": 0.5}],
            "warnings": []}
        result = await server.call_tool("maya_weight_report", {"mesh": "|h"})
        assert fake.requests[-1] == ("weight_report", {"mesh": "|h"})
        assert result.structured_content["vertices"] == 8
```

(Adapt fixture/helper names to what the file actually uses — read its phase-1 rigging tests first; the assertion pattern above is the contract.)

- [ ] **Step 9: Mayapy test** — append to `tests/test_handlers_mayapy.py` after `TestPoseSkeletonInMaya`:

```python
class TestWeightReportInMaya:
    def test_report_agrees_with_bind_and_is_read_only(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        mesh = _serpent_cylinder(cmds, name="wr_tube")
        skel = rigging.create_skeleton({
            "chain": [[0, 0, 0], [0, 2, 0], [0, 4, 0]], "chain_prefix": "wr_j"})
        bind = rigging.bind_skin({"mesh": mesh, "root": skel["root"]})
        out = rigging.weight_report({"mesh": mesh})
        assert out["skin_cluster"] == bind["skin_cluster"]
        assert out["unweighted_vertices"] == 0
        assert out["max_influences"] == 4
        assert out["max_weight_sum_error"] < 1e-6   # in-scene sums are exact
        assert sum(b["vertices"] for b in out["histogram"]) == out["vertices"]
        assert [p["joint"] for p in out["per_joint"]] == bind["influences"]

    def test_report_on_an_unbound_mesh_refuses(self):
        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import rigging

        mesh = _serpent_cylinder(cmds, name="wr_bare")
        with pytest.raises(HandlerError, match="not bound"):
            rigging.weight_report({"mesh": mesh})
```

- [ ] **Step 10: Run both suites**

Run: `uv run pytest -q` then `E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q`
Expected: PASS both (mayapy gains 2)

- [ ] **Step 11: Commit**

```bash
git add -A
git commit -m "feat(#668): weight_report - the weights perception tool, wired end to end"
```

---

### Task 4: rigmath mirror math

**Files:**
- Modify: `maya_plugin/handlers/rigmath.py`
- Test: `tests/test_rigmath.py`

**Interfaces:**
- Produces:
  - `rigmath.mirror_pairs(positions: List[float], axis_index: int, tolerance: float, source_positive: bool = True) -> (pairs: List[(src, dst)], on_plane: List[int], unpaired: List[int])` — flat xyz list; source side is coord > tolerance (or < −tolerance when `source_positive=False`); dst is the vertex nearest the reflected position within `tolerance`; on-plane vertices (|coord| ≤ tolerance) are neither source nor destination.
  - `rigmath.mirror_influence_map(influence_positions: List[List[float]], axis_index: int, tolerance: float) -> (mapping: List[int], unmatched: List[int])` — for EVERY column: its mirror partner's column (on-plane joints map to themselves); off-plane columns with no partner land in `unmatched` and map to themselves.
  - `rigmath.mirror_weight_table(weights, ncols, pairs, mapping) -> List[float]` — for each (src, dst), `out[dst][mapping[j]] = weights[src][j]`; everything else unchanged. Rows stay normalized because a mirrored row is a permutation of a normalized row.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_rigmath.py`:

```python
class TestMirrorPairs:
    # 4 verts: +X pair, -X pair, on-plane, +X orphan
    POS = [1.0, 0.0, 0.0,   -1.0, 0.0, 0.0,
           0.0, 5.0, 0.0,    2.0, 9.0, 0.0]

    def test_pairs_source_positive_by_default(self):
        pairs, on_plane, unpaired = rigmath.mirror_pairs(self.POS, 0, 1e-3)
        assert pairs == [(0, 1)]
        assert on_plane == [2]
        assert unpaired == [3]

    def test_direction_reverses_source_and_destination(self):
        pairs, _, unpaired = rigmath.mirror_pairs(
            self.POS, 0, 1e-3, source_positive=False)
        assert pairs == [(1, 0)]
        assert unpaired == []          # vert 3 sits on the +X side now

    def test_tolerance_is_the_match_radius(self):
        pos = [1.0, 0.0, 0.0,   -1.0, 0.05, 0.0]
        assert rigmath.mirror_pairs(pos, 0, 1e-3)[0] == []
        assert rigmath.mirror_pairs(pos, 0, 0.1)[0] == [(0, 1)]

    def test_other_axes_reflect_their_own_coordinate(self):
        pos = [0.0, 1.0, 0.0,   0.0, -1.0, 0.0]
        assert rigmath.mirror_pairs(pos, 1, 1e-3)[0] == [(0, 1)]


class TestMirrorInfluenceMap:
    def test_bilateral_joints_pair_and_center_maps_to_self(self):
        joints = [[0.0, 1.0, 0.0], [0.5, 1.0, 0.0], [-0.5, 1.0, 0.0]]
        mapping, unmatched = rigmath.mirror_influence_map(joints, 0, 1e-3)
        assert mapping == [0, 2, 1]
        assert unmatched == []

    def test_an_off_plane_joint_without_a_partner_is_named(self):
        joints = [[0.0, 1.0, 0.0], [0.5, 1.0, 0.0]]
        mapping, unmatched = rigmath.mirror_influence_map(joints, 0, 1e-3)
        assert mapping == [0, 1]
        assert unmatched == [1]


class TestMirrorWeightTable:
    def test_source_weights_land_on_swapped_columns(self):
        # 2 verts x 3 joints (center, L, R): v0 is the +X source
        weights = [0.2, 0.8, 0.0,   1.0, 0.0, 0.0]
        out = rigmath.mirror_weight_table(
            weights, 3, [(0, 1)], [0, 2, 1])
        assert out[3:] == [0.2, 0.0, 0.8]
        assert out[:3] == [0.2, 0.8, 0.0]       # source untouched
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_rigmath.py::TestMirrorPairs -q`
Expected: FAIL — no attribute `mirror_pairs`

- [ ] **Step 3: Implement** — append to `maya_plugin/handlers/rigmath.py` (add `import math` at the top of the file if absent):

```python
def _cell(x: float, y: float, z: float, size: float):
    return (int(math.floor(x / size)), int(math.floor(y / size)),
            int(math.floor(z / size)))


def _nearest_within(positions: List[float], candidates_by_cell, target,
                    tolerance: float):
    """Index of the position nearest `target` within `tolerance`, else None.
    Grid-hash lookup: O(27) cells, not O(n) - the humanoid has ~15k verts."""
    base = _cell(target[0], target[1], target[2], tolerance)
    best, best_d2 = None, tolerance * tolerance
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                for i in candidates_by_cell.get(
                        (base[0] + dx, base[1] + dy, base[2] + dz), ()):
                    px, py, pz = positions[3 * i:3 * i + 3]
                    d2 = ((px - target[0]) ** 2 + (py - target[1]) ** 2
                          + (pz - target[2]) ** 2)
                    if d2 <= best_d2:
                        best, best_d2 = i, d2
    return best


def mirror_pairs(positions: List[float], axis_index: int, tolerance: float,
                 source_positive: bool = True):
    """(source, destination) vertex pairs across the mirror plane, by
    reflected position. On-plane vertices are neither; a source vertex whose
    reflection lands on no vertex is unpaired - an asymmetric mesh, reported
    not guessed."""
    n = len(positions) // 3
    by_cell: Dict[Any, List[int]] = {}
    for i in range(n):
        by_cell.setdefault(
            _cell(positions[3 * i], positions[3 * i + 1],
                  positions[3 * i + 2], tolerance), []).append(i)
    pairs, on_plane, unpaired = [], [], []
    for i in range(n):
        c = positions[3 * i + axis_index]
        if abs(c) <= tolerance:
            on_plane.append(i)
            continue
        if (c > 0) != source_positive:
            continue
        target = list(positions[3 * i:3 * i + 3])
        target[axis_index] = -target[axis_index]
        partner = _nearest_within(positions, by_cell, target, tolerance)
        if partner is None:
            unpaired.append(i)
        else:
            pairs.append((i, partner))
    return pairs, on_plane, unpaired


def mirror_influence_map(influence_positions: List[List[float]],
                         axis_index: int, tolerance: float):
    """Column j of the source side writes column mapping[j] on the mirrored
    side: the influence nearest j's reflected position. On-plane influences
    (spine, head) map to themselves; an off-plane influence with no partner
    maps to itself AND is returned in unmatched - the handler refuses on it,
    because copying left-arm weights onto left-arm joints for right-side
    vertices is exactly the silent wrong answer this surface never gives."""
    flat: List[float] = []
    for p in influence_positions:
        flat.extend(p)
    n = len(influence_positions)
    by_cell: Dict[Any, List[int]] = {}
    for i in range(n):
        by_cell.setdefault(
            _cell(flat[3 * i], flat[3 * i + 1], flat[3 * i + 2], tolerance),
            []).append(i)
    mapping, unmatched = [], []
    for i in range(n):
        c = flat[3 * i + axis_index]
        if abs(c) <= tolerance:
            mapping.append(i)
            continue
        target = list(flat[3 * i:3 * i + 3])
        target[axis_index] = -target[axis_index]
        partner = _nearest_within(flat, by_cell, target, tolerance)
        if partner is None or partner == i:
            mapping.append(i)
            unmatched.append(i)
        else:
            mapping.append(partner)
    return mapping, unmatched


def mirror_weight_table(weights: List[float], ncols: int, pairs,
                        mapping: List[int]) -> List[float]:
    """Write each source row onto its partner through the influence map.
    A mirrored row is a permutation of a normalized row, so normalization
    survives by construction."""
    out = list(weights)
    for src, dst in pairs:
        for j in range(ncols):
            out[dst * ncols + mapping[j]] = weights[src * ncols + j]
    return out
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_rigmath.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_rigmath.py maya_plugin/handlers/rigmath.py
git commit -m "feat(#668): mirror math - positional vertex/influence pairing, table mirror"
```

---

### Task 5: `mirror_weights` end-to-end

**Files:**
- Modify: `maya_plugin/handlers/rigging.py`, `maya_plugin/maya_mcp_plugin.py`, `src/maya_mcp/schemas.py`, `src/maya_mcp/server.py`
- Test: `tests/test_rigging.py`, `tests/test_server_tools.py`, `tests/test_handlers_mayapy.py`

**Interfaces:**
- Consumes: Task 4's mirror math, `_skin_cluster_for`, `_skin_weights`, `sculpt.vertex_positions`.
- Produces: handler `rigging.mirror_weights(params: {mesh, axis?, direction?}) -> {mesh, skin_cluster, axis, direction, mirrored_vertices, on_plane_vertices, unpaired_vertices, changed_vertices, unweighted_vertices, warnings}`; shared writer `rigging._set_skin_weights(skin_cluster, mesh_shape, ncols, weights)`; constants `rigging.MIRROR_AXES = {"x": 0, "y": 1, "z": 2}`, `rigging.MIRROR_DIRECTIONS = {"+to-": True, "-to+": False}`, `rigging.MIRROR_TOL = 1e-3`; MCP tool `maya_mirror_weights`; schema `MirrorWeightsResult`.

- [ ] **Step 1: Write the failing headless tests** — append to `tests/test_rigging.py`:

```python
class TestMirrorWeights:
    def _bound(self, fake, monkeypatch,
               positions=(1.0, 0.5, 0.0,  -1.0, 0.5, 0.0),
               weights=(0.0, 1.0, 0.0,     1.0, 0.0, 0.0),
               joints=("|r", "|r|L_a", "|r|R_a"),
               joint_pos=((0.0, 1, 0), (0.5, 1, 0), (-0.5, 1, 0))):
        fake.objects.append("|hum")
        fake.shapes = {"|hum": "|hum|humShape"}
        def listRelatives(node, shapes=False, **kw):
            if shapes:
                return [fake.shapes.get(node)]
            return FakeCmds.listRelatives(fake, node, **kw)
        fake.listRelatives = listRelatives
        fake.skin_history = ["skin1"]
        fake.attrs["skin1.maxInfluences"] = 4
        for j, p in zip(joints, joint_pos):
            fake.attrs[j + ".rotate"] = [(0.0, 0.0, 0.0)]
        state = {"weights": list(weights)}
        monkeypatch.setattr(
            rigging, "_skin_weights",
            lambda sc, shape: (list(joints), list(state["weights"]),
                               len(positions) // 3))
        written = {}
        def set_weights(sc, shape, ncols, table):
            written["table"] = list(table)
            state["weights"] = list(table)
        monkeypatch.setattr(rigging, "_set_skin_weights", set_weights)
        from maya_plugin.handlers import sculpt
        monkeypatch.setattr(sculpt, "vertex_positions",
                            lambda cmds, mesh: list(positions))
        jp = {j: list(p) for j, p in zip(joints, joint_pos)}
        def xform(node, query=False, worldSpace=False, translation=False, **kw):
            return jp.get(node, [0.0, 0.0, 0.0])
        fake.xform = xform
        return written

    def test_mirror_writes_swapped_columns_and_measures_back(self, fake, monkeypatch):
        written = self._bound(fake, monkeypatch)
        out = rigging.mirror_weights({"mesh": "hum"})
        assert written["table"][3:6] == [0.0, 0.0, 1.0]   # L column -> R column
        assert out["mirrored_vertices"] == 1
        assert out["changed_vertices"] == 1
        assert out["unweighted_vertices"] == 0

    def test_unknown_axis_and_direction_are_refused(self, fake, monkeypatch):
        self._bound(fake, monkeypatch)
        with pytest.raises(HandlerError, match="axis"):
            rigging.mirror_weights({"mesh": "hum", "axis": "w"})
        with pytest.raises(HandlerError, match="direction"):
            rigging.mirror_weights({"mesh": "hum", "direction": "sideways"})

    def test_an_asymmetric_skeleton_is_refused_by_name(self, fake, monkeypatch):
        self._bound(fake, monkeypatch,
                    joints=("|r", "|r|L_a"),
                    joint_pos=((0.0, 1, 0), (0.5, 1, 0)),
                    weights=(0.0, 1.0, 1.0, 0.0))
        with pytest.raises(HandlerError, match="no mirror partner") as err:
            rigging.mirror_weights({"mesh": "hum"})
        assert "L_a" in str(err.value)

    def test_unpaired_vertices_warn_but_do_not_refuse(self, fake, monkeypatch):
        self._bound(fake, monkeypatch,
                    positions=(1.0, 0.5, 0.0,  -1.0, 0.5, 0.0,  2.0, 9.0, 0.0),
                    weights=(0.0, 1.0, 0.0,  1.0, 0.0, 0.0,  0.0, 1.0, 0.0))
        out = rigging.mirror_weights({"mesh": "hum"})
        assert out["unpaired_vertices"] == 1
        assert any("unpaired" in w for w in out["warnings"])

    def test_a_posed_skeleton_warns_before_mirroring(self, fake, monkeypatch):
        self._bound(fake, monkeypatch)
        fake.attrs["|r|L_a.rotate"] = [(0.0, 0.0, 30.0)]
        out = rigging.mirror_weights({"mesh": "hum"})
        assert any("posed" in w for w in out["warnings"])

    def test_mirror_checkpoints_once_after_validation(self, fake, monkeypatch):
        self._bound(fake, monkeypatch)
        events = []
        monkeypatch.setattr(session, "auto_checkpoint",
                            lambda reason: events.append(reason) or
                            {"checkpoint_id": "001", "path": "x.ma"})
        rigging.mirror_weights({"mesh": "hum"})
        assert events == ["mirror_weights"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_rigging.py::TestMirrorWeights -q`
Expected: FAIL — no attribute `mirror_weights`

- [ ] **Step 3: Implement** — append to `maya_plugin/handlers/rigging.py`:

```python
MIRROR_AXES = {"x": 0, "y": 1, "z": 2}
MIRROR_DIRECTIONS = {"+to-": True, "-to+": False}
# Positional match radius, scene units. Numbers mean metres here (#629/#634),
# so this is a millimetre - tight enough that a real partner is unambiguous,
# loose enough for float noise from combine/freeze.
MIRROR_TOL = 1e-3


def _set_skin_weights(skin_cluster: str, mesh_shape: str, ncols: int,
                      weights: List[float]) -> None:
    """The one write path: the whole table in one API call, no normalization
    by Maya (normalize=False) - rows arrive normalized from rigmath, and
    letting the node renormalize would un-measure what we just computed."""
    import maya.api.OpenMaya as om          # noqa: PLC0415
    import maya.api.OpenMayaAnim as oma     # noqa: PLC0415

    sel = om.MSelectionList()
    sel.add(mesh_shape)
    sel.add(skin_cluster)
    dag = sel.getDagPath(0)
    fn = oma.MFnSkinCluster(sel.getDependNode(1))
    comp_fn = om.MFnSingleIndexedComponent()
    comp = comp_fn.create(om.MFn.kMeshVertComponent)
    comp_fn.setCompleteData(om.MFnMesh(dag).numVertices)
    fn.setWeights(dag, comp, om.MIntArray(range(ncols)),
                  om.MDoubleArray(weights), False)


def _pose_warning(cmds, influences: List[str]) -> Optional[str]:
    """Weight ops pair vertices by POSITION; a posed mesh pairs garbage."""
    for joint in influences:
        rot = cmds.getAttr(joint + ".rotate")[0]
        if any(abs(v) > 1e-6 for v in rot):
            return ("the skeleton is posed (%s carries rotation) - vertex "
                    "positions drive the pairing, so mirror from the bind "
                    "pose: reset_pose first" % _short(joint))
    return None


def mirror_weights(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    mesh_long, mesh_shape = naming.require_mesh(cmds, str(params.get("mesh") or ""))
    axis = params.get("axis", "x")
    if axis not in MIRROR_AXES:
        raise HandlerError("unknown axis %r; one of: x, y, z" % (axis,),
                           hint="the mirror plane is the one the axis crosses")
    direction = params.get("direction", "+to-")
    if direction not in MIRROR_DIRECTIONS:
        raise HandlerError(
            "unknown direction %r; one of: %s"
            % (direction, ", ".join(sorted(MIRROR_DIRECTIONS))),
            hint="'+to-' copies the +%s side onto the -%s side" % (axis, axis))
    sc = _skin_cluster_for(cmds, mesh_long, mesh_shape)
    influences, weights, num_verts = _skin_weights(sc, mesh_shape)

    inf_positions = [
        [float(v) for v in cmds.xform(j, query=True, worldSpace=True,
                                      translation=True)]
        for j in influences]
    mapping, unmatched = rigmath.mirror_influence_map(
        inf_positions, MIRROR_AXES[axis], MIRROR_TOL)
    if unmatched:
        raise HandlerError(
            "%d influence(s) have no mirror partner across %s: %s"
            % (len(unmatched), axis,
               ", ".join(_short(influences[i]) for i in unmatched[:8])),
            hint="mirroring needs a bilaterally symmetric skeleton - a joint "
                 "on one side must have a positional twin on the other")

    warnings: List[str] = []
    posed = _pose_warning(cmds, influences)
    if posed:
        warnings.append(posed)

    positions = sculpt.vertex_positions(cmds, mesh_long)
    pairs, on_plane, unpaired = rigmath.mirror_pairs(
        positions, MIRROR_AXES[axis], MIRROR_TOL,
        source_positive=MIRROR_DIRECTIONS[direction])
    if unpaired:
        warnings.append(
            "%d source vertices are unpaired (no vertex within %g of the "
            "reflected position) and kept their weights - the mesh is not "
            "symmetric across %s there"
            % (len(unpaired), MIRROR_TOL, axis))

    session.auto_checkpoint("mirror_weights")
    new_table = rigmath.mirror_weight_table(weights, len(influences), pairs,
                                            mapping)
    _set_skin_weights(sc, mesh_shape, len(influences), new_table)

    _, after, _ = _skin_weights(sc, mesh_shape)
    stats = rigmath.weight_stats(influences, after, num_verts,
                                 int(cmds.getAttr(sc + ".maxInfluences")))
    if stats["unweighted_vertices"]:
        warnings.append("%d vertices belong to NO joint after the mirror"
                        % stats["unweighted_vertices"])
    return {
        "mesh": mesh_long,
        "skin_cluster": sc,
        "axis": axis,
        "direction": direction,
        "mirrored_vertices": len(pairs),
        "on_plane_vertices": len(on_plane),
        "unpaired_vertices": len(unpaired),
        "changed_vertices": rigmath.changed_rows(weights, after,
                                                 len(influences)),
        "unweighted_vertices": stats["unweighted_vertices"],
        "warnings": warnings,
    }
```

- [ ] **Step 4: Register** — `maya_mcp_plugin.py` handlers map: `"mirror_weights": rigging.mirror_weights,`

- [ ] **Step 5: Run headless**

Run: `uv run pytest tests/test_rigging.py tests/test_rigmath.py -q`
Expected: PASS

- [ ] **Step 6: Schema + MCP tool.** `schemas.py`:

```python
class MirrorWeightsResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mesh: str
    skin_cluster: str
    axis: str
    direction: str
    mirrored_vertices: int = Field(
        description="Source-side vertices whose rows were written across.")
    on_plane_vertices: int
    unpaired_vertices: int = Field(
        description=(
            "Source vertices with no positional twin - an asymmetric mesh, "
            "left unchanged and warned about, never guessed."))
    changed_vertices: int = Field(
        description="MEASURED after re-reading the table, not computed.")
    unweighted_vertices: int
    warnings: List[str] = Field(default_factory=list)
```

`server.py` (import `MirrorWeightsResult`):

```python
    @mcp.tool(
        title="Mirror skin weights",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=True
        ),
    )
    def maya_mirror_weights(
        mesh: Annotated[str, Field(description="A bound mesh (long name).")],
        axis: Annotated[Literal["x", "y", "z"], Field(description=(
            "Mirror plane normal. x mirrors across the YZ plane - the "
            "bilateral-creature default."
        ))] = "x",
        direction: Annotated[Literal["+to-", "-to+"], Field(description=(
            "'+to-' copies the +axis side onto the -axis side. Author left "
            "(+X, Maya convention), mirror to right."
        ))] = "+to-",
    ) -> MirrorWeightsResult:
        """Copy one side's skin weights onto the other, by position.

        Vertices pair with the vertex nearest their reflection; influences
        pair the same way, so L_shoulder weights land on R_shoulder. Refuses
        an asymmetric skeleton (a joint with no twin); asymmetric mesh
        regions are counted in unpaired_vertices and left unchanged. Run from
        the bind pose - a posed mesh pairs garbage and warns."""
        return MirrorWeightsResult.model_validate(
            maya.request("mirror_weights",
                         {"mesh": mesh, "axis": axis, "direction": direction},
                         timeout_s=BOOL_TIMEOUT_S)
        )
```

- [ ] **Step 7: Server-tool test** (same pattern as Task 3 Step 8): fake a `mirror_weights` response, assert marshaling of `{"mesh", "axis", "direction"}` and a validated `mirrored_vertices`.

- [ ] **Step 8: Mayapy test** — append to `tests/test_handlers_mayapy.py`:

```python
class TestMirrorWeightsInMaya:
    def _bilateral(self, cmds, rigging):
        """A cube spanning x in [-1, 1] bound to a 3-joint T: center root,
        one joint per side."""
        mesh = cmds.polyCube(width=2, height=1, depth=1,
                             subdivisionsX=8, name="mir_box")[0]
        mesh = cmds.ls(mesh, long=True)[0]
        skel = rigging.create_skeleton({"joints": [
            {"name": "mir_root", "position": [0, 0.5, 0]},
            {"name": "mir_L", "position": [0.7, 0.5, 0], "parent": "mir_root"},
            {"name": "mir_R", "position": [-0.7, 0.5, 0], "parent": "mir_root"},
        ]})
        rigging.bind_skin({"mesh": mesh, "root": skel["root"]})
        return mesh, skel

    def test_hand_authored_left_weights_arrive_on_the_right(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        mesh, skel = self._bilateral(cmds, rigging)
        # Deliberately skew ONE +X vertex fully to the LEFT joint.
        sc = rigging.weight_report({"mesh": mesh})["skin_cluster"]
        shape = cmds.listRelatives(mesh, shapes=True, fullPath=True)[0]
        target = None
        for i in range(cmds.polyEvaluate(mesh, vertex=True)):
            pos = cmds.xform("%s.vtx[%d]" % (mesh, i), query=True,
                             worldSpace=True, translation=True)
            if pos[0] > 0.9:
                target = i
                break
        cmds.skinPercent(sc, "%s.vtx[%d]" % (mesh, target),
                         transformValue=[("mir_L", 1.0)])
        out = rigging.mirror_weights({"mesh": mesh, "axis": "x"})
        assert out["mirrored_vertices"] > 0
        assert out["changed_vertices"] > 0
        assert out["unweighted_vertices"] == 0
        # The mirrored twin of `target` is fully owned by mir_R now.
        pos = cmds.xform("%s.vtx[%d]" % (mesh, target), query=True,
                         worldSpace=True, translation=True)
        for i in range(cmds.polyEvaluate(mesh, vertex=True)):
            q = cmds.xform("%s.vtx[%d]" % (mesh, i), query=True,
                           worldSpace=True, translation=True)
            if (abs(q[0] + pos[0]) < 1e-3 and abs(q[1] - pos[1]) < 1e-3
                    and abs(q[2] - pos[2]) < 1e-3):
                w = cmds.skinPercent(sc, "%s.vtx[%d]" % (mesh, i),
                                     query=True, value=True)
                assert max(w) == pytest.approx(1.0, abs=1e-6)
                infs = cmds.skinCluster(sc, query=True, influence=True)
                assert infs[w.index(max(w))].split("|")[-1] == "mir_R"
                break
        else:
            pytest.fail("no mirrored twin found for the authored vertex")

    def test_mirror_is_idempotent(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        mesh, skel = self._bilateral(cmds, rigging)
        rigging.mirror_weights({"mesh": mesh})
        out = rigging.mirror_weights({"mesh": mesh})
        assert out["changed_vertices"] == 0
```

- [ ] **Step 9: Run both suites** (as Task 3 Step 10). Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat(#668): mirror_weights - author one side, mirror by position"
```

---

### Task 6: rigmath smoothing math

**Files:**
- Modify: `maya_plugin/handlers/rigmath.py`
- Test: `tests/test_rigmath.py`

**Interfaces:**
- Produces: `rigmath.smooth_weight_table(weights, ncols, adjacency: List[List[int]], iterations: int, max_influences: int, rows: Optional[set] = None, alpha: float = SMOOTH_ALPHA) -> List[float]`; constants `SMOOTH_ALPHA = 0.5`, `MAX_SMOOTH_ITERATIONS = 50`. Per iteration each targeted row becomes `(1-alpha)*own + alpha*neighbor_mean`, then `prune_row(..., max_influences)`. Vertices with no neighbors and rows outside `rows` are untouched.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_rigmath.py`:

```python
class TestSmoothWeightTable:
    # 3 verts in a line (0-1-2), 2 joints, a hard stair-step at v1
    TABLE = [1.0, 0.0,   1.0, 0.0,   0.0, 1.0]
    ADJ = [[1], [0, 2], [1]]

    def test_one_pass_softens_the_step_and_stays_normalized(self):
        out = rigmath.smooth_weight_table(self.TABLE, 2, self.ADJ, 1, 4)
        # v1: 0.5*own(1,0) + 0.5*mean((1,0),(0,1)) = (0.75, 0.25)
        assert out[2:4] == pytest.approx([0.75, 0.25])
        assert sum(out[0:2]) == pytest.approx(1.0)
        assert sum(out[4:6]) == pytest.approx(1.0)

    def test_rows_filter_limits_who_moves(self):
        out = rigmath.smooth_weight_table(self.TABLE, 2, self.ADJ, 1, 4,
                                          rows={1})
        assert out[0:2] == pytest.approx([1.0, 0.0])   # v0 untouched
        assert out[4:6] == pytest.approx([0.0, 1.0])   # v2 untouched
        assert out[2:4] == pytest.approx([0.75, 0.25])

    def test_pruning_holds_the_influence_ceiling(self):
        table = [1.0, 0.0, 0.0,   0.0, 1.0, 0.0,   0.0, 0.0, 1.0]
        adj = [[1, 2], [0, 2], [0, 1]]
        out = rigmath.smooth_weight_table(table, 3, adj, 1, 2)
        for v in range(3):
            row = out[3 * v:3 * v + 3]
            assert sum(1 for w in row if w > rigmath.WEIGHT_TOL) <= 2
            assert sum(row) == pytest.approx(1.0)

    def test_isolated_vertices_are_left_alone(self):
        out = rigmath.smooth_weight_table([1.0, 0.0], 2, [[]], 3, 4)
        assert out == [1.0, 0.0]

    def test_more_iterations_move_further(self):
        one = rigmath.smooth_weight_table(self.TABLE, 2, self.ADJ, 1, 4)
        three = rigmath.smooth_weight_table(self.TABLE, 2, self.ADJ, 3, 4)
        assert three[2] < one[2]          # v1's j0 share keeps eroding
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_rigmath.py::TestSmoothWeightTable -q`
Expected: FAIL

- [ ] **Step 3: Implement** — append to `maya_plugin/handlers/rigmath.py`:

```python
# Half own, half neighbourhood: strong enough that 2-3 passes visibly soften
# a stair-step, weak enough that a pass cannot invert local ownership.
SMOOTH_ALPHA = 0.5
MAX_SMOOTH_ITERATIONS = 50


def smooth_weight_table(weights: List[float], ncols: int,
                        adjacency: List[List[int]], iterations: int,
                        max_influences: int, rows=None,
                        alpha: float = SMOOTH_ALPHA) -> List[float]:
    """Laplacian smoothing over the mesh graph, the fix for stair-stepped
    falloff at hips and shoulders. Every smoothed row is pruned back to
    max_influences and renormalized - smoothing bleeds weight onto every
    neighbouring influence, and unchecked that breaks the bind's promise to
    the exporter."""
    num = len(weights) // ncols
    targets = list(range(num)) if rows is None else sorted(rows)
    current = list(weights)
    for _ in range(iterations):
        nxt = list(current)
        for v in targets:
            neighbours = adjacency[v]
            if not neighbours:
                continue
            row = []
            for j in range(ncols):
                mean = (sum(current[n * ncols + j] for n in neighbours)
                        / len(neighbours))
                row.append((1.0 - alpha) * current[v * ncols + j]
                           + alpha * mean)
            nxt[v * ncols:(v + 1) * ncols] = prune_row(row, max_influences)
        current = nxt
    return current
```

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_rigmath.py -q`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_rigmath.py maya_plugin/handlers/rigmath.py
git commit -m "feat(#668): laplacian weight smoothing with influence pruning"
```

---

### Task 7: `smooth_weights` end-to-end

**Files:**
- Modify: `maya_plugin/handlers/rigging.py`, `maya_plugin/maya_mcp_plugin.py`, `src/maya_mcp/schemas.py`, `src/maya_mcp/server.py`
- Test: `tests/test_rigging.py`, `tests/test_server_tools.py`, `tests/test_handlers_mayapy.py`

**Interfaces:**
- Consumes: Task 6 math, `_skin_cluster_for`, `_skin_weights`, `_set_skin_weights`, `_pose_warning`.
- Produces: handler `rigging.smooth_weights(params: {mesh, joints?, iterations?}) -> {mesh, skin_cluster, iterations, smoothed_vertices, changed_vertices, unweighted_vertices, max_influences_exceeded, warnings}`; helper `rigging._vertex_adjacency(mesh_shape) -> List[List[int]]`; helper `rigging._resolve_influences(influences, names) -> List[int]` (column indices; long or unique short names; unknown/ambiguous refused listing candidates); MCP tool `maya_smooth_weights`; schema `SmoothWeightsResult`.
- `joints` semantics: rows smoothed = vertices where ANY named joint holds weight > `WEIGHT_TOL` (default: every vertex). `iterations`: int 1..`MAX_SMOOTH_ITERATIONS`, default 1.

- [ ] **Step 1: Write the failing headless tests** — append to `tests/test_rigging.py`:

```python
class TestSmoothWeights:
    def _bound(self, fake, monkeypatch, weights, joints=("|r|a", "|r|b"),
               adjacency=((1,), (0, 2), (1,))):
        fake.objects.append("|hum")
        fake.shapes = {"|hum": "|hum|humShape"}
        def listRelatives(node, shapes=False, **kw):
            if shapes:
                return [fake.shapes.get(node)]
            return FakeCmds.listRelatives(fake, node, **kw)
        fake.listRelatives = listRelatives
        fake.skin_history = ["skin1"]
        fake.attrs["skin1.maxInfluences"] = 4
        for j in joints:
            fake.attrs[j + ".rotate"] = [(0.0, 0.0, 0.0)]
        state = {"weights": list(weights)}
        monkeypatch.setattr(
            rigging, "_skin_weights",
            lambda sc, shape: (list(joints), list(state["weights"]),
                               len(weights) // len(joints)))
        def set_weights(sc, shape, ncols, table):
            state["weights"] = list(table)
        monkeypatch.setattr(rigging, "_set_skin_weights", set_weights)
        monkeypatch.setattr(rigging, "_vertex_adjacency",
                            lambda shape: [list(a) for a in adjacency])
        return state

    def test_smooth_measures_what_changed(self, fake, monkeypatch):
        state = self._bound(fake, monkeypatch,
                            [1.0, 0.0, 1.0, 0.0, 0.0, 1.0])
        out = rigging.smooth_weights({"mesh": "hum"})
        assert out["iterations"] == 1
        assert out["smoothed_vertices"] == 3
        assert out["changed_vertices"] >= 1
        assert out["unweighted_vertices"] == 0
        assert state["weights"][2:4] == pytest.approx([0.75, 0.25])

    def test_joints_filter_selects_rows_by_held_weight(self, fake, monkeypatch):
        self._bound(fake, monkeypatch, [1.0, 0.0, 1.0, 0.0, 0.0, 1.0])
        out = rigging.smooth_weights({"mesh": "hum", "joints": ["b"]})
        # only v2 holds b -> only v2 is a smoothing target
        assert out["smoothed_vertices"] == 1

    def test_unknown_joint_is_refused_with_candidates(self, fake, monkeypatch):
        self._bound(fake, monkeypatch, [1.0, 0.0, 1.0, 0.0, 0.0, 1.0])
        with pytest.raises(HandlerError, match="not an influence") as err:
            rigging.smooth_weights({"mesh": "hum", "joints": ["nope"]})
        assert "a" in err.value.hint

    def test_iterations_bounds(self, fake, monkeypatch):
        self._bound(fake, monkeypatch, [1.0, 0.0, 1.0, 0.0, 0.0, 1.0])
        with pytest.raises(HandlerError, match="iterations"):
            rigging.smooth_weights({"mesh": "hum", "iterations": 0})
        with pytest.raises(HandlerError, match="iterations"):
            rigging.smooth_weights({"mesh": "hum", "iterations": 999})
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_rigging.py::TestSmoothWeights -q`. Expected: FAIL.

- [ ] **Step 3: Implement** — append to `maya_plugin/handlers/rigging.py`:

```python
def _vertex_adjacency(mesh_shape: str) -> List[List[int]]:
    """Neighbour vertex ids per vertex, from the mesh graph."""
    import maya.api.OpenMaya as om          # noqa: PLC0415

    sel = om.MSelectionList()
    sel.add(mesh_shape)
    it = om.MItMeshVertex(sel.getDagPath(0))
    adjacency: List[List[int]] = []
    while not it.isDone():
        adjacency.append(list(it.getConnectedVertices()))
        it.next()
    return adjacency


def _resolve_influences(influences: List[str], names) -> List[int]:
    """Column indices for user-named joints; long or unique short names."""
    if not isinstance(names, list) or not names or not all(
            isinstance(n, str) and n.strip() for n in names):
        raise HandlerError("joints must be a non-empty list of joint names")
    by_short: Dict[str, List[int]] = {}
    for idx, j in enumerate(influences):
        by_short.setdefault(_short(j), []).append(idx)
    columns: List[int] = []
    for name in names:
        if name in influences:
            columns.append(influences.index(name))
            continue
        matches = by_short.get(_short(name), [])
        if not matches:
            raise HandlerError(
                "%r is not an influence of this skinCluster" % name,
                hint="influences here: %s"
                     % ", ".join(_short(j) for j in influences[:12]))
        if len(matches) > 1:
            raise HandlerError(
                "%r is ambiguous (%d influences match)" % (name, len(matches)),
                hint="use the long name, e.g. %s" % influences[matches[0]])
        columns.append(matches[0])
    return columns


def smooth_weights(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    mesh_long, mesh_shape = naming.require_mesh(cmds, str(params.get("mesh") or ""))
    iterations = params.get("iterations", 1)
    if (not isinstance(iterations, int) or isinstance(iterations, bool)
            or not 1 <= iterations <= rigmath.MAX_SMOOTH_ITERATIONS):
        raise HandlerError(
            "iterations must be an integer 1..%d"
            % rigmath.MAX_SMOOTH_ITERATIONS,
            hint="2-3 passes visibly soften a stair-step; more is mush")
    sc = _skin_cluster_for(cmds, mesh_long, mesh_shape)
    max_influences = int(cmds.getAttr(sc + ".maxInfluences"))
    influences, weights, num_verts = _skin_weights(sc, mesh_shape)

    rows = None
    if params.get("joints") is not None:
        columns = _resolve_influences(influences, params.get("joints"))
        ncols = len(influences)
        rows = {v for v in range(num_verts)
                if any(weights[v * ncols + j] > rigmath.WEIGHT_TOL
                       for j in columns)}

    # No _pose_warning here on purpose: smoothing reads the mesh GRAPH
    # (adjacency), not positions, so pose cannot corrupt it.
    warnings: List[str] = []

    session.auto_checkpoint("smooth_weights")
    adjacency = _vertex_adjacency(mesh_shape)
    new_table = rigmath.smooth_weight_table(
        weights, len(influences), adjacency, iterations, max_influences,
        rows=rows)
    _set_skin_weights(sc, mesh_shape, len(influences), new_table)

    _, after, _ = _skin_weights(sc, mesh_shape)
    stats = rigmath.weight_stats(influences, after, num_verts, max_influences)
    if stats["unweighted_vertices"]:
        warnings.append("%d vertices belong to NO joint after smoothing"
                        % stats["unweighted_vertices"])
    return {
        "mesh": mesh_long,
        "skin_cluster": sc,
        "iterations": iterations,
        "smoothed_vertices": num_verts if rows is None else len(rows),
        "changed_vertices": rigmath.changed_rows(weights, after,
                                                 len(influences)),
        "unweighted_vertices": stats["unweighted_vertices"],
        "max_influences_exceeded": stats["max_influences_exceeded"],
        "warnings": warnings,
    }
```

- [ ] **Step 4: Register** — `"smooth_weights": rigging.smooth_weights,`

- [ ] **Step 5: Run headless** — `uv run pytest tests/test_rigging.py -q`. Expected: PASS.

- [ ] **Step 6: Schema + MCP tool.** `schemas.py`:

```python
class SmoothWeightsResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mesh: str
    skin_cluster: str
    iterations: int
    smoothed_vertices: int
    changed_vertices: int = Field(
        description="MEASURED after re-reading the table.")
    unweighted_vertices: int
    max_influences_exceeded: int
    warnings: List[str] = Field(default_factory=list)
```

`server.py`:

```python
    @mcp.tool(
        title="Smooth skin weights",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
    )
    def maya_smooth_weights(
        mesh: Annotated[str, Field(description="A bound mesh (long name).")],
        joints: Annotated[Optional[List[str]], Field(description=(
            "Limit smoothing to vertices these joints hold - aim it at the "
            "hip or shoulder that stair-steps. Default: the whole mesh."
        ))] = None,
        iterations: Annotated[int, Field(ge=1, le=50, description=(
            "Laplacian passes. 2-3 visibly soften a hard falloff edge."
        ))] = 1,
    ) -> SmoothWeightsResult:
        """Soften stair-stepped weight falloff over the mesh graph.

        Each pass averages a vertex's weights with its neighbours', then
        prunes back to the cluster's max_influences and renormalizes, so
        smoothing never breaks the bind's promise to the exporter. Reports
        measured changed_vertices and post-op integrity."""
        params = {"mesh": mesh, "iterations": iterations}
        if joints is not None:
            params["joints"] = joints
        return SmoothWeightsResult.model_validate(
            maya.request("smooth_weights", params, timeout_s=BOOL_TIMEOUT_S)
        )
```

- [ ] **Step 7: Server-tool test** (Task 3 pattern): assert `joints` is omitted from the request when None and passed verbatim when given.

- [ ] **Step 8: Mayapy test** — append to `tests/test_handlers_mayapy.py`:

```python
class TestSmoothWeightsInMaya:
    def test_smoothing_a_hard_edge_reduces_the_step(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        mesh = _serpent_cylinder(cmds, name="sm_tube")
        skel = rigging.create_skeleton({
            "chain": [[0, 0, 0], [0, 2, 0], [0, 4, 0]], "chain_prefix": "sm_j"})
        bind = rigging.bind_skin({"mesh": mesh, "root": skel["root"]})
        sc = bind["skin_cluster"]
        # Manufacture a stair-step: every vertex below y=2 fully to joint 1,
        # above fully to joint 2.
        n = cmds.polyEvaluate(mesh, vertex=True)
        for i in range(n):
            y = cmds.xform("%s.vtx[%d]" % (mesh, i), query=True,
                           worldSpace=True, translation=True)[1]
            owner = "sm_j_01" if y < 2.0 else "sm_j_02"
            cmds.skinPercent(sc, "%s.vtx[%d]" % (mesh, i),
                             transformValue=[(owner, 1.0)])
        out = rigging.smooth_weights({"mesh": mesh, "iterations": 2})
        assert out["changed_vertices"] > 0
        assert out["unweighted_vertices"] == 0
        assert out["max_influences_exceeded"] == 0
        # Some vertex near the seam is now genuinely shared.
        report = rigging.weight_report({"mesh": mesh})
        shared = [b for b in report["histogram"] if b["influences"] >= 2]
        assert shared and sum(b["vertices"] for b in shared) > 0

    def test_joint_filter_leaves_the_far_end_alone(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging, sculpt

        mesh = _serpent_cylinder(cmds, name="sm_tube2")
        skel = rigging.create_skeleton({
            "chain": [[0, 0, 0], [0, 2, 0], [0, 4, 0]], "chain_prefix": "sn_j"})
        rigging.bind_skin({"mesh": mesh, "root": skel["root"]})
        before = rigging.weight_report({"mesh": mesh})
        out = rigging.smooth_weights({"mesh": mesh, "joints": ["sn_j_03"],
                                      "iterations": 1})
        assert out["smoothed_vertices"] < before["vertices"]
```

- [ ] **Step 9: Run both suites.** Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat(#668): smooth_weights - graph laplacian over an existing bind"
```

---

### Task 8: rigmath region math

**Files:**
- Modify: `maya_plugin/handlers/rigmath.py`
- Test: `tests/test_rigmath.py`

**Interfaces:**
- Produces:
  - `rigmath.radius_factors(positions: List[float], center: List[float], radius: float, falloff: str) -> Dict[int, float]` — vertex → factor in (0, 1]; `"none"` gives 1.0 inside the radius, `"linear"` gives `1 - d/radius`.
  - `rigmath.apply_region_weights(weights, ncols, joint_col: int, factors: Dict[int, float], weight: float) -> (List[float], sole_owner: int)` — per factored vertex: `new_j = old_j + (weight - old_j) * factor`; other columns scale by `(1 - new_j) / others_sum`; when the joint was the sole owner (`others_sum == 0`) and `weight < 1`, the remainder has nowhere to go: the row normalizes to the joint alone and the vertex is counted in `sole_owner`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_rigmath.py`:

```python
class TestRadiusFactors:
    POS = [0.0, 0.0, 0.0,   1.0, 0.0, 0.0,   3.0, 0.0, 0.0]

    def test_linear_falloff_fades_with_distance(self):
        out = rigmath.radius_factors(self.POS, [0, 0, 0], 2.0, "linear")
        assert out[0] == pytest.approx(1.0)
        assert out[1] == pytest.approx(0.5)
        assert 2 not in out

    def test_none_falloff_is_flat_inside(self):
        out = rigmath.radius_factors(self.POS, [0, 0, 0], 2.0, "none")
        assert out == {0: 1.0, 1: 1.0}


class TestApplyRegionWeights:
    def test_target_blends_and_others_rescale_proportionally(self):
        # 1 vert x 3 joints: j0 has 0.2, j1 0.6, j2 0.2 - push j0 to 0.8
        out, sole = rigmath.apply_region_weights(
            [0.2, 0.6, 0.2], 3, 0, {0: 1.0}, 0.8)
        assert out == pytest.approx([0.8, 0.15, 0.05])
        assert sole == 0

    def test_factor_scales_the_blend(self):
        out, _ = rigmath.apply_region_weights(
            [0.0, 1.0], 2, 0, {0: 0.5}, 1.0)
        assert out == pytest.approx([0.5, 0.5])

    def test_sole_owner_with_partial_weight_is_counted(self):
        out, sole = rigmath.apply_region_weights(
            [1.0, 0.0], 2, 0, {0: 1.0}, 0.6)
        assert out == pytest.approx([1.0, 0.0])   # nowhere to put the rest
        assert sole == 1

    def test_unfactored_vertices_are_untouched(self):
        out, _ = rigmath.apply_region_weights(
            [1.0, 0.0, 0.0, 1.0], 2, 0, {1: 1.0}, 1.0)
        assert out[:2] == [1.0, 0.0]
        assert out[2:] == pytest.approx([1.0, 0.0])
```

- [ ] **Step 2: Run to verify failure** — expected FAIL.

- [ ] **Step 3: Implement** — append to `maya_plugin/handlers/rigmath.py`:

```python
def radius_factors(positions: List[float], center: List[float],
                   radius: float, falloff: str) -> Dict[int, float]:
    """Vertex -> blend factor for a spherical region. Factors are (0, 1]:
    a zero factor is not-in-the-region, never a stored no-op."""
    out: Dict[int, float] = {}
    for v in range(len(positions) // 3):
        dx = positions[3 * v] - center[0]
        dy = positions[3 * v + 1] - center[1]
        dz = positions[3 * v + 2] - center[2]
        d = math.sqrt(dx * dx + dy * dy + dz * dz)
        if d > radius:
            continue
        factor = 1.0 if falloff == "none" else 1.0 - d / radius
        if factor > 0.0:
            out[v] = factor
    return out


def apply_region_weights(weights: List[float], ncols: int, joint_col: int,
                         factors: Dict[int, float], weight: float):
    """Blend one joint toward `weight` on the factored vertices; the other
    influences share what remains in their existing proportions. A vertex the
    joint solely owns cannot shed weight it has nobody to give to - it stays
    fully owned and is counted, because a silent 0.6 that reads back 1.0 is
    the lying-success defect class (#636)."""
    out = list(weights)
    sole_owner = 0
    for v, factor in factors.items():
        base = v * ncols
        old_j = weights[base + joint_col]
        new_j = old_j + (weight - old_j) * factor
        others = sum(weights[base + j] for j in range(ncols)
                     if j != joint_col)
        if others > 0.0:
            scale = (1.0 - new_j) / others
            for j in range(ncols):
                out[base + j] = new_j if j == joint_col \
                    else weights[base + j] * scale
        else:
            if new_j < 1.0 and old_j > 0.0:
                sole_owner += 1
            out[base + joint_col] = 1.0 if (old_j > 0.0 or new_j > 0.0) \
                else 0.0
    return out, sole_owner
```

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_rigmath.py -q`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_rigmath.py maya_plugin/handlers/rigmath.py
git commit -m "feat(#668): region weight math - radius falloff, proportional rebalance"
```

---

### Task 9: `set_region_weights` end-to-end

**Files:**
- Modify: `maya_plugin/handlers/rigging.py`, `maya_plugin/maya_mcp_plugin.py`, `src/maya_mcp/schemas.py`, `src/maya_mcp/server.py`
- Test: `tests/test_rigging.py`, `tests/test_server_tools.py`, `tests/test_handlers_mayapy.py`

**Interfaces:**
- Consumes: Task 8 math, `_skin_cluster_for`, `_resolve_influences`, `_set_skin_weights`, `sculpt.vertex_positions`.
- Produces: handler `rigging.set_region_weights(params: {mesh, joint, faces? | within_radius_of?, radius?, weight, falloff?}) -> {mesh, skin_cluster, joint, vertices_in_region, changed_vertices, sole_owner_vertices, unweighted_vertices, warnings}`; MCP tool `maya_set_region_weights`; schema `SetRegionWeightsResult`.
- Validation: `weight` float 0..1 (required); exactly one of `faces` (list of int face ids, all within `polyEvaluate(face=True)`) or `within_radius_of` ([x,y,z] with `radius` > 0); `falloff` in {"linear","none"}, default "linear", refused with `faces` (faces are a hard assignment, factor 1.0); empty region (no vertices) is refused, not a silent no-op.

- [ ] **Step 1: Write the failing headless tests** — append to `tests/test_rigging.py`:

```python
class TestSetRegionWeights:
    def _bound(self, fake, monkeypatch,
               positions=(0.0, 0.0, 0.0,  1.0, 0.0, 0.0),
               weights=(0.5, 0.5, 0.5, 0.5),
               joints=("|r|a", "|r|b")):
        fake.objects.append("|hum")
        fake.shapes = {"|hum": "|hum|humShape"}
        def listRelatives(node, shapes=False, **kw):
            if shapes:
                return [fake.shapes.get(node)]
            return FakeCmds.listRelatives(fake, node, **kw)
        fake.listRelatives = listRelatives
        fake.skin_history = ["skin1"]
        fake.attrs["skin1.maxInfluences"] = 4
        for j in joints:
            fake.attrs[j + ".rotate"] = [(0.0, 0.0, 0.0)]
        state = {"weights": list(weights)}
        monkeypatch.setattr(
            rigging, "_skin_weights",
            lambda sc, shape: (list(joints), list(state["weights"]),
                               len(positions) // 3))
        def set_weights(sc, shape, ncols, table):
            state["weights"] = list(table)
        monkeypatch.setattr(rigging, "_set_skin_weights", set_weights)
        from maya_plugin.handlers import sculpt
        monkeypatch.setattr(sculpt, "vertex_positions",
                            lambda cmds, mesh: list(positions))
        fake.face_count = 4
        def polyEvaluate(mesh, face=False, vertex=False, **kw):
            return fake.face_count if face else len(positions) // 3
        fake.polyEvaluate = polyEvaluate
        def plcc(*comps, fromFace=False, toVertex=False, **kw):
            return ["|hum.vtx[0]"]
        fake.polyListComponentConversion = plcc
        return state

    def test_radius_mode_blends_and_reports(self, fake, monkeypatch):
        state = self._bound(fake, monkeypatch)
        out = rigging.set_region_weights({
            "mesh": "hum", "joint": "a", "within_radius_of": [0, 0, 0],
            "radius": 0.5, "weight": 1.0})
        assert out["vertices_in_region"] == 1
        assert out["changed_vertices"] == 1
        assert state["weights"][:2] == pytest.approx([1.0, 0.0])
        assert state["weights"][2:] == pytest.approx([0.5, 0.5])

    def test_faces_mode_converts_and_assigns_hard(self, fake, monkeypatch):
        state = self._bound(fake, monkeypatch)
        out = rigging.set_region_weights({
            "mesh": "hum", "joint": "b", "faces": [0], "weight": 1.0})
        assert out["vertices_in_region"] == 1
        assert state["weights"][:2] == pytest.approx([0.0, 1.0])

    def test_exactly_one_region_form(self, fake, monkeypatch):
        self._bound(fake, monkeypatch)
        with pytest.raises(HandlerError, match="exactly one"):
            rigging.set_region_weights({"mesh": "hum", "joint": "a",
                                        "weight": 1.0})
        with pytest.raises(HandlerError, match="exactly one"):
            rigging.set_region_weights({
                "mesh": "hum", "joint": "a", "faces": [0],
                "within_radius_of": [0, 0, 0], "radius": 1, "weight": 1.0})

    def test_weight_bounds_and_radius_requirements(self, fake, monkeypatch):
        self._bound(fake, monkeypatch)
        with pytest.raises(HandlerError, match="weight"):
            rigging.set_region_weights({"mesh": "hum", "joint": "a",
                                        "faces": [0], "weight": 1.5})
        with pytest.raises(HandlerError, match="radius"):
            rigging.set_region_weights({
                "mesh": "hum", "joint": "a", "within_radius_of": [0, 0, 0],
                "weight": 1.0})

    def test_falloff_is_a_radius_mode_concept(self, fake, monkeypatch):
        self._bound(fake, monkeypatch)
        with pytest.raises(HandlerError, match="falloff"):
            rigging.set_region_weights({
                "mesh": "hum", "joint": "a", "faces": [0], "weight": 1.0,
                "falloff": "linear"})

    def test_an_empty_region_is_refused_not_a_noop(self, fake, monkeypatch):
        self._bound(fake, monkeypatch)
        with pytest.raises(HandlerError, match="no vertices"):
            rigging.set_region_weights({
                "mesh": "hum", "joint": "a", "within_radius_of": [99, 99, 99],
                "radius": 0.1, "weight": 1.0})

    def test_out_of_range_face_is_refused(self, fake, monkeypatch):
        self._bound(fake, monkeypatch)
        with pytest.raises(HandlerError, match="face"):
            rigging.set_region_weights({"mesh": "hum", "joint": "a",
                                        "faces": [99], "weight": 1.0})
```

- [ ] **Step 2: Run to verify failure** — expected FAIL.

- [ ] **Step 3: Implement** — append to `maya_plugin/handlers/rigging.py`:

```python
REGION_FALLOFFS = ("linear", "none")


def _region_vertex_ids_from_faces(cmds, mesh_long: str, faces) -> List[int]:
    if (not isinstance(faces, list) or not faces or not all(
            isinstance(f, int) and not isinstance(f, bool) and f >= 0
            for f in faces)):
        raise HandlerError("faces must be a non-empty list of face ids")
    face_count = cmds.polyEvaluate(mesh_long, face=True)
    bad = [f for f in faces if f >= face_count]
    if bad:
        raise HandlerError(
            "face id(s) out of range: %s (mesh has %d faces)"
            % (", ".join(str(f) for f in bad[:8]), face_count))
    comps = ["%s.f[%d]" % (mesh_long, f) for f in faces]
    verts = cmds.polyListComponentConversion(
        *comps, fromFace=True, toVertex=True) or []
    ids: List[int] = []
    for comp in cmds.ls(verts, flatten=True) or []:
        ids.append(int(comp[comp.rindex("[") + 1:-1]))
    return sorted(set(ids))


def set_region_weights(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    mesh_long, mesh_shape = naming.require_mesh(cmds, str(params.get("mesh") or ""))
    weight = params.get("weight")
    if (not isinstance(weight, (int, float)) or isinstance(weight, bool)
            or not 0.0 <= float(weight) <= 1.0):
        raise HandlerError("weight must be a number in 0..1",
                           hint="1.0 hands the region fully to the joint")
    weight = float(weight)
    faces = params.get("faces")
    center = params.get("within_radius_of")
    if (faces is None) == (center is None):
        raise HandlerError(
            "pass exactly one of 'faces' or 'within_radius_of'",
            hint="faces=[ids] for a picked patch; within_radius_of=[x,y,z] "
                 "with radius for a spherical region")
    falloff = params.get("falloff")
    if faces is not None and falloff is not None:
        raise HandlerError(
            "falloff only applies to within_radius_of - faces are a hard "
            "assignment",
            hint="drop falloff, or switch to within_radius_of")
    falloff = "linear" if falloff is None else falloff
    if falloff not in REGION_FALLOFFS:
        raise HandlerError("unknown falloff %r; one of: %s"
                           % (falloff, ", ".join(REGION_FALLOFFS)))
    radius = params.get("radius")
    if center is not None:
        center = rigmath.vec3(center, "within_radius_of")
        if (not isinstance(radius, (int, float)) or isinstance(radius, bool)
                or float(radius) <= 0.0):
            raise HandlerError("within_radius_of needs a radius > 0",
                               hint="scene units, like every position here")
        radius = float(radius)
    elif radius is not None:
        raise HandlerError("radius only applies to within_radius_of")

    sc = _skin_cluster_for(cmds, mesh_long, mesh_shape)
    influences, weights, num_verts = _skin_weights(sc, mesh_shape)
    joint_col = _resolve_influences(influences, [params.get("joint")])[0]

    if faces is not None:
        factors = {v: 1.0
                   for v in _region_vertex_ids_from_faces(cmds, mesh_long,
                                                          faces)}
    else:
        positions = sculpt.vertex_positions(cmds, mesh_long)
        factors = rigmath.radius_factors(positions, center, radius, falloff)
    if not factors:
        raise HandlerError(
            "the region holds no vertices",
            hint="within_radius_of/radius missed the mesh entirely - "
                 "get_object_info reports where the mesh actually is")

    warnings: List[str] = []
    posed = _pose_warning(cmds, influences)
    if posed:
        warnings.append(posed)

    session.auto_checkpoint("set_region_weights")
    new_table, sole_owner = rigmath.apply_region_weights(
        weights, len(influences), joint_col, factors, weight)
    _set_skin_weights(sc, mesh_shape, len(influences), new_table)

    _, after, _ = _skin_weights(sc, mesh_shape)
    stats = rigmath.weight_stats(influences, after, num_verts,
                                 int(cmds.getAttr(sc + ".maxInfluences")))
    if sole_owner:
        warnings.append(
            "%d vertices are solely owned by %s - a weight below 1.0 has no "
            "other influence to give the remainder to, so they stay fully "
            "owned" % (sole_owner, _short(influences[joint_col])))
    if stats["unweighted_vertices"]:
        warnings.append("%d vertices belong to NO joint after the edit"
                        % stats["unweighted_vertices"])
    return {
        "mesh": mesh_long,
        "skin_cluster": sc,
        "joint": influences[joint_col],
        "vertices_in_region": len(factors),
        "changed_vertices": rigmath.changed_rows(weights, after,
                                                 len(influences)),
        "sole_owner_vertices": sole_owner,
        "unweighted_vertices": stats["unweighted_vertices"],
        "warnings": warnings,
    }
```

(`_pose_warning` IS wanted here: region centers and radii are world positions.)

- [ ] **Step 4: Register** — `"set_region_weights": rigging.set_region_weights,`

- [ ] **Step 5: Run headless** — `uv run pytest tests/test_rigging.py -q`. Expected: PASS.

- [ ] **Step 6: Schema + MCP tool.** `schemas.py`:

```python
class SetRegionWeightsResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mesh: str
    skin_cluster: str
    joint: str
    vertices_in_region: int
    changed_vertices: int = Field(
        description="MEASURED after re-reading the table.")
    sole_owner_vertices: int = Field(
        description=(
            "Vertices the joint solely owns: a weight below 1.0 has no other "
            "influence to hand the remainder to, so they stay fully owned "
            "(warned, never silent)."))
    unweighted_vertices: int
    warnings: List[str] = Field(default_factory=list)
```

`server.py`:

```python
    @mcp.tool(
        title="Set region skin weights",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=True
        ),
    )
    def maya_set_region_weights(
        mesh: Annotated[str, Field(description="A bound mesh (long name).")],
        joint: Annotated[str, Field(description=(
            "The influence to weight - long name, or a unique short name."
        ))],
        weight: Annotated[float, Field(ge=0.0, le=1.0, description=(
            "Target weight at the region's strongest point. Other influences "
            "share the remainder in their existing proportions."
        ))],
        faces: Annotated[Optional[List[int]], Field(description=(
            "Face ids naming the region - a hard assignment (no falloff). "
            "Pass either faces or within_radius_of, never both."
        ))] = None,
        within_radius_of: Annotated[Optional[List[float]], Field(description=(
            "World [x,y,z] center of a spherical region; requires radius."
        ))] = None,
        radius: Annotated[Optional[float], Field(description=(
            "Region radius, scene units."
        ))] = None,
        falloff: Annotated[Optional[Literal["linear", "none"]], Field(
            description=(
                "Radius mode only: linear fades the blend toward the edge; "
                "none applies weight flat across the region."
            ))] = None,
    ) -> SetRegionWeightsResult:
        """Explicitly assign a joint's weight over a region - the fix for
        where the bind guessed wrong.

        weight_report's unweighted_sample and per_joint say where to aim.
        Reports measured changed_vertices and post-op integrity; an empty
        region refuses rather than silently doing nothing."""
        params = {"mesh": mesh, "joint": joint, "weight": weight}
        if faces is not None:
            params["faces"] = faces
        if within_radius_of is not None:
            params["within_radius_of"] = within_radius_of
        if radius is not None:
            params["radius"] = radius
        if falloff is not None:
            params["falloff"] = falloff
        return SetRegionWeightsResult.model_validate(
            maya.request("set_region_weights", params,
                         timeout_s=BOOL_TIMEOUT_S)
        )
```

- [ ] **Step 7: Server-tool test** (Task 3 pattern): radius-mode call marshals all params; optional params omitted when None.

- [ ] **Step 8: Mayapy test** — append to `tests/test_handlers_mayapy.py`:

```python
class TestSetRegionWeightsInMaya:
    def test_radius_region_hands_vertices_to_the_joint(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        mesh = _serpent_cylinder(cmds, name="rg_tube")
        skel = rigging.create_skeleton({
            "chain": [[0, 0, 0], [0, 2, 0], [0, 4, 0]], "chain_prefix": "rg_j"})
        rigging.bind_skin({"mesh": mesh, "root": skel["root"]})
        out = rigging.set_region_weights({
            "mesh": mesh, "joint": "rg_j_03", "within_radius_of": [0, 4, 0],
            "radius": 1.0, "weight": 1.0, "falloff": "none"})
        assert out["vertices_in_region"] > 0
        assert out["changed_vertices"] > 0
        assert out["unweighted_vertices"] == 0
        sc = out["skin_cluster"]
        # The vertex nearest the tip is fully the tip joint's now.
        n = cmds.polyEvaluate(mesh, vertex=True)
        best, best_d = None, 1e9
        for i in range(n):
            p = cmds.xform("%s.vtx[%d]" % (mesh, i), query=True,
                           worldSpace=True, translation=True)
            d = (p[0] ** 2 + (p[1] - 4.0) ** 2 + p[2] ** 2) ** 0.5
            if d < best_d:
                best, best_d = i, d
        weights = cmds.skinPercent(sc, "%s.vtx[%d]" % (mesh, best),
                                   query=True, value=True)
        assert max(weights) == pytest.approx(1.0, abs=1e-6)

    def test_faces_region_converts_to_vertices(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        mesh = _serpent_cylinder(cmds, name="rg_tube2")
        skel = rigging.create_skeleton({
            "chain": [[0, 0, 0], [0, 2, 0], [0, 4, 0]], "chain_prefix": "rf_j"})
        rigging.bind_skin({"mesh": mesh, "root": skel["root"]})
        out = rigging.set_region_weights({
            "mesh": mesh, "joint": "rf_j_01", "faces": [0, 1], "weight": 1.0})
        assert out["vertices_in_region"] >= 4
        assert out["changed_vertices"] >= 0
```

- [ ] **Step 9: Run both suites.** Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat(#668): set_region_weights - explicit assignment where the bind guessed wrong"
```

---

### Task 10: Review item (a) — per-mesh displacement in `pose_skeleton`

**Files:**
- Modify: `maya_plugin/handlers/rigging.py` (`pose_skeleton`), `src/maya_mcp/schemas.py` (`PoseSkeletonResult`), `docs/protocol.md` (row update happens in Task 12)
- Test: `tests/test_rigging.py`, `tests/test_handlers_mayapy.py`

**Interfaces:**
- Produces: `pose_skeleton` result gains `per_mesh: [{mesh, max_displacement, displaced_vertices}]`; the noop warning fires PER MESH (an inert mesh among moving ones is named); top-level `max_displacement`/`displaced_vertices` unchanged. Also: a fake test pinning `reset_pose`'s existing multi-bindpose warning.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_rigging.py`:

```python
class TestPosePerMesh:
    def test_reset_with_two_bind_poses_warns_and_restores_the_first(self, fake):
        fake.objects += ["|r", "|r|a"]
        fake.parents = {"|r|a": "|r"}
        fake.bind_poses = ["bindPose1", "bindPose2"]
        out = rigging.reset_pose({"root": "r"})
        assert any("2 bind poses" in w for w in out["warnings"])
        restored = [c for c in fake.calls
                    if c[0] == "dagPose" and c[2].get("restore")]
        assert restored and restored[0][1][0] == "bindPose1"

    def test_pose_reports_per_mesh_and_names_the_inert_one(self, fake, monkeypatch):
        fake.objects += ["|r", "|r|a"]
        fake.parents = {"|r|a": "|r"}
        fake.skin_clusters = ["scA", "scB"]
        fake.skin_influences = {"scA": ["|r|a"], "scB": ["|r|a"]}
        fake.skin_geometry = {"scA": ["|meshA|meshAShape"],
                              "scB": ["|meshB|meshBShape"]}
        fake.objects += ["|meshA", "|meshB"]
        fake.parents.update({"|meshA|meshAShape": "|meshA",
                             "|meshB|meshBShape": "|meshB"})
        # _bound_meshes asks a shape for its parent transform; the base fake
        # only answers children queries.
        def listRelatives(node, parent=False, fullPath=False, **kw):
            if parent:
                p = fake.parents.get(node)
                return [p] if p else None
            return FakeCmds.listRelatives(fake, node, **kw)
        fake.listRelatives = listRelatives
        from maya_plugin.handlers import sculpt
        state = {"posed": False}
        def positions(cmds, mesh):
            # meshA moves 1.0 when posed; meshB never moves.
            if mesh == "|meshA" and state["posed"]:
                return [0.0, 1.0, 0.0,  0.0, 3.0, 0.0]
            if mesh == "|meshA":
                return [0.0, 0.0, 0.0,  0.0, 2.0, 0.0]
            return [5.0, 0.0, 0.0,  5.0, 2.0, 0.0]
        monkeypatch.setattr(sculpt, "vertex_positions", positions)
        real_set = fake.setAttr
        def set_attr(plug, *values, **kw):
            state["posed"] = True
            return real_set(plug, *values, **kw)
        fake.setAttr = set_attr
        out = rigging.pose_skeleton({"root": "r",
                                     "rotations": {"a": [0, 0, 30]}})
        assert len(out["per_mesh"]) == 2
        by_mesh = {m["mesh"]: m for m in out["per_mesh"]}
        assert by_mesh["|meshA"]["max_displacement"] == pytest.approx(1.0)
        assert by_mesh["|meshB"]["max_displacement"] == 0.0
        assert out["max_displacement"] == pytest.approx(1.0)
        assert any("meshB" in w and "near-zero" in w for w in out["warnings"])
```

- [ ] **Step 2: Run to verify failure** — expected FAIL (`per_mesh` missing / warning absent).

- [ ] **Step 3: Implement** — in `rigging.pose_skeleton`, replace the displacement-measurement block (the `max_disp = 0.0` loop and the warning block) with:

```python
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

    warnings: List[str] = []
    if not meshes:
        warnings.append(
            "no skinned mesh is bound to this skeleton - the pose moved bare "
            "joints only; bind_skin first if deformation was the point")
    else:
        # Per mesh, not combined: a combined max hides one inert mesh among
        # several (#668 review item a).
        for entry in per_mesh:
            extent = sculpt_math.bbox_extent(before[entry["mesh"]])
            if extent > 0 and entry["max_displacement"] < extent * NOOP_POSE_RATIO:
                warnings.append(
                    "%s moved by %.4g against a size of %.4g - near-zero "
                    "deformation usually means the rotations landed on joints "
                    "that own none of its vertices"
                    % (entry["mesh"], entry["max_displacement"], extent))

    return {"applied": len(resolved), "joints": joints_out,
            "max_displacement": max_disp, "displaced_vertices": displaced,
            "per_mesh": per_mesh, "warnings": warnings}
```

- [ ] **Step 4: Schema** — `schemas.py`: add before `PoseSkeletonResult` and wire in:

```python
class MeshDisplacement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mesh: str
    max_displacement: float
    displaced_vertices: int
```

and in `PoseSkeletonResult`:

```python
    per_mesh: List[MeshDisplacement] = Field(
        default_factory=list,
        description=(
            "Displacement per bound mesh - the combined max can hide one "
            "inert mesh among several, so each is measured alone."))
```

- [ ] **Step 5: Mayapy test** — append inside `TestPoseSkeletonInMaya`:

```python
    def test_per_mesh_reports_each_bound_mesh_alone(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import rigging

        mesh, skel = self._bound_serpent(cmds, rigging, name="pm_tube")
        mid = skel["joints"][1]["name"]
        out = rigging.pose_skeleton({"root": skel["root"],
                                     "rotations": {mid: [0, 0, 45]}})
        assert len(out["per_mesh"]) == 1
        assert out["per_mesh"][0]["mesh"] == mesh
        assert out["per_mesh"][0]["max_displacement"] == pytest.approx(
            out["max_displacement"])
```

- [ ] **Step 6: Run both suites and the existing serpent expectations** — `uv run pytest -q` and mayapy. `evals/serpent_live.py` reads only fields that still exist, no change needed. Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(#668): pose_skeleton reports per-mesh displacement; inert meshes are named (review item a)"
```

---

### Task 11: Review item (b) — honest multi-mesh skin-violation messages

**Files:**
- Modify: `maya_plugin/handlers/export.py` (`skin_violations`)
- Test: `tests/test_export_fbx.py`

**Interfaces:**
- Produces: same function signature and return type; message changes only. (1) The `clusters == 0 or influenced_models == 0` message reports the measurement and demotes the cause to "the one measured cause is..." phrasing. (2) `unweighted_file_vertices` and weight-sum messages gain "across N skin deformers — file-wide, not per mesh" when `deformers > 1`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_export_fbx.py` (match the file's existing `skin_violations` unit-test style — it tests the function directly with dict fixtures; find the phase-1 tests for `skin_violations` and place these beside them):

```python
    def test_multi_deformer_totals_say_they_are_file_wide(self):
        sfacts = {"deformers": 2, "clusters": 6, "influenced_models": 2,
                  "bind_pose_present": True, "unweighted_file_vertices": 3,
                  "max_weight_sum_error": None, "unavailable_reason": None}
        out = export.skin_violations(sfacts)
        assert any("file-wide" in v and "2 skin deformers" in v for v in out)

    def test_single_deformer_totals_stay_unqualified(self):
        sfacts = {"deformers": 1, "clusters": 3, "influenced_models": 1,
                  "bind_pose_present": True, "unweighted_file_vertices": 3,
                  "max_weight_sum_error": None, "unavailable_reason": None}
        out = export.skin_violations(sfacts)
        assert not any("file-wide" in v for v in out)

    def test_no_cluster_message_reports_before_it_diagnoses(self):
        sfacts = {"deformers": 1, "clusters": 0, "influenced_models": 0,
                  "bind_pose_present": True, "unweighted_file_vertices": 0,
                  "max_weight_sum_error": None, "unavailable_reason": None}
        out = export.skin_violations(sfacts)
        assert any("links no joints" in v and "one measured cause" in v
                   for v in out)
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_export_fbx.py -q`. Expected: the new tests FAIL; note which EXISTING tests assert the old wording — update those assertions in the same commit.

- [ ] **Step 3: Implement** — in `export.skin_violations`, replace the two message sites:

```python
    if sfacts["clusters"] == 0 or sfacts["influenced_models"] == 0:
        # Reports the measurement first; the diagnosis is offered as the one
        # cause this project has MEASURED (a selected export listing the mesh
        # without the skeleton root), not asserted as the only one (#668
        # review item b).
        out.append(
            "the file's skin deformer links no joints (%d clusters, %d "
            "influenced models); the one measured cause is a selected export "
            "that lists the mesh without the skeleton root"
            % (sfacts["clusters"], sfacts["influenced_models"]))
        return out
```

and:

```python
    scope = (" (across %d skin deformers - the count is file-wide, not per "
             "mesh)" % sfacts["deformers"]) if sfacts["deformers"] > 1 else ""
    if sfacts["unweighted_file_vertices"]:
        out.append("%d file vertices carry no weight%s"
                   % (sfacts["unweighted_file_vertices"], scope))
    err = sfacts["max_weight_sum_error"]
    if err is not None and err > WEIGHT_SUM_TOL:
        out.append("per-vertex weight sums are off by up to %g%s"
                   % (err, scope))
```

- [ ] **Step 4: Run** — `uv run pytest tests/test_export_fbx.py tests/test_fbxbytes.py -q`. Expected: PASS (with any old-wording assertions updated).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "fix(#668): skin violations report file-wide scope and measured causes (review item b)"
```

---

### Task 12: Protocol documentation

**Files:**
- Modify: `docs/protocol.md`

- [ ] **Step 1: Update the phase-1 `pose_skeleton` row** to `{ applied, joints: [{name, world_position}], max_displacement, displaced_vertices, per_mesh, warnings }` and append one sentence to its paragraph: "Each bound mesh is also measured alone in `per_mesh` — a combined max can hide one inert mesh among several."

- [ ] **Step 2: Add the phase-2 section** after the phase-1 section:

```markdown
## Commands (rigging phase 2 / #668)

| cmd | params | result |
|---|---|---|
| `weight_report` | `{ mesh }` | `{ mesh, skin_cluster, vertices, max_influences, unweighted_vertices, unweighted_sample, max_influences_exceeded, exceeded_sample, max_weight_sum_error, histogram, per_joint, warnings }` |
| `mirror_weights` | `{ mesh, axis?, direction? }` | `{ mesh, skin_cluster, axis, direction, mirrored_vertices, on_plane_vertices, unpaired_vertices, changed_vertices, unweighted_vertices, warnings }` |
| `smooth_weights` | `{ mesh, joints?, iterations? }` | `{ mesh, skin_cluster, iterations, smoothed_vertices, changed_vertices, unweighted_vertices, max_influences_exceeded, warnings }` |
| `set_region_weights` | `{ mesh, joint, faces? \| within_radius_of? + radius?, weight, falloff? }` | `{ mesh, skin_cluster, joint, vertices_in_region, changed_vertices, sole_owner_vertices, unweighted_vertices, warnings }` |

Binding is one call; *good* weights are the craft, and agents cannot paint —
so the craft is programmatic. All four operate on an existing bind and refuse
an unbound mesh. `weight_report` is the perception tool (a measurement, no
checkpoint): per-joint ownership, offending-vertex samples, the
influence-count histogram, weight-sum drift. The three mutators write the
whole table in one API call, then **re-read it and report from the re-read**:
`changed_vertices` and post-op integrity (`unweighted_vertices`) are
measured, never computed.

`mirror_weights` pairs vertices and influences by reflected position
(`+to-` copies the +axis side onto the −axis side). An asymmetric skeleton —
an off-plane joint with no positional twin — refuses; asymmetric mesh regions
are counted in `unpaired_vertices`, left unchanged, and warned about. Run it
from the bind pose; a posed mesh pairs garbage and warns.

`smooth_weights` is laplacian smoothing over the mesh graph — the fix for
stair-stepped falloff at hips and shoulders. Every smoothed row is pruned
back to the cluster's `max_influences` and renormalized, so smoothing never
breaks the bind's promise to the exporter. `joints` limits smoothing to
vertices those joints hold.

`set_region_weights` blends one joint toward `weight` over a region — face
ids (hard assignment) or a sphere (`within_radius_of` + `radius`, `linear` or
`none` falloff) — while the other influences share the remainder in their
existing proportions. An empty region refuses rather than silently doing
nothing; a vertex the joint solely owns cannot shed weight (nobody to give it
to) and is counted in `sole_owner_vertices`.
```

- [ ] **Step 3: Commit**

```bash
git add docs/protocol.md
git commit -m "docs(#668): protocol entries for the weights-craft surface"
```

---

### Task 13: The humanoid live gate — `evals/humanoid_live.py`

**Files:**
- Create: `evals/humanoid_live.py`
- Output dir: `evals/humanoid_live/` (renders, `humanoid.fbx`, `baseline.json`)

**Interfaces:**
- Consumes: every phase-1 and phase-2 command over TCP (`live_call.call`), `evals/golem_delivery/poses.json` (the five-pose `joints_deg` abstractions), `fbxbytes`, `export.WEIGHT_SUM_TOL`.
- Produces: exit 0/1/2 like `serpent_live.py`; renders for judgment (bind + 5 poses × front/side); per-edge tearing numbers (review item c); a biped-preset verdict block; `baseline.json`.

The complete file:

```python
"""Phase-2 gate for #668: the humanoid. ~20 joints, bound and craft-weighted,
posed through the golem five-pose set adapted to a biped - the poses exercise
exactly the joints that are hard (hips, shoulders, spine).

Measured checks (this script) + judged renders (the acceptance):

    1  build one combined humanoid mesh + 20-joint skeleton + bind
    2  weights craft: region-author the LEFT shoulder, mirror to the right,
       smooth the hips/shoulders; weight_report must end clean
       (unweighted 0, exceeded 0) and L/R must be symmetric
    3  five poses (rest/crouch/extend/air/absorb from the golem set):
       per-mesh displacement > 0, shells unchanged, and the PER-EDGE
       tearing detector - every edge vs ITS OWN bind length (review item c)
    4  renders per pose - JUDGED: hips and shoulders must read as one
       continuous body, no candy-wrapper pinch, no tearing
    5  reset between poses, byte-identical topology at the end
    6  export include_skins from the bind pose; byte gate + baseline

DESTRUCTIVE: calls new_scene. Port 9878, the agent-launched Maya, per the
two-Maya policy - never point this at the user's 9877.

Run:  uv run python evals/humanoid_live.py
Exit: 0 pass, 1 fail, 2 no connection.
"""

from __future__ import annotations

import base64
import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from live_call import call, structured_result  # noqa: E402
from maya_plugin.handlers import fbxbytes  # noqa: E402
from maya_plugin.handlers.export import WEIGHT_SUM_TOL  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
OUT_DIR = os.path.join(_HERE, "humanoid_live")
POSES_PATH = os.path.join(_HERE, "golem_delivery", "poses.json")

MESH = "humanoid"
JOINT_COUNT = 20
# Per-edge ceiling (review item c): each edge vs ITS OWN bind length. Looser
# than the serpent's global 1.5x because hip/shoulder creases legitimately
# stretch single short edges harder than a uniform tube ever does.
EDGE_STRETCH_MAX = 1.8
PIECES = 8               # torso, head, 2 arms, 2 legs, 2 feet -> shells

# The skeleton, hand-listed. This block IS the preset="biped" experiment:
# the verdict block at the end reports how it felt (spec: decide with the
# humanoid build in hand).
JOINTS = [
    {"name": "pelvis",     "position": [0.0,  1.00, 0.0]},
    {"name": "spine_01",   "position": [0.0,  1.15, 0.0], "parent": "pelvis"},
    {"name": "spine_02",   "position": [0.0,  1.30, 0.0], "parent": "spine_01"},
    {"name": "chest",      "position": [0.0,  1.45, 0.0], "parent": "spine_02"},
    {"name": "neck",       "position": [0.0,  1.60, 0.0], "parent": "chest"},
    {"name": "head",       "position": [0.0,  1.72, 0.0], "parent": "neck"},
    {"name": "L_shoulder", "position": [0.22, 1.50, 0.0], "parent": "chest"},
    {"name": "L_elbow",    "position": [0.45, 1.50, 0.0], "parent": "L_shoulder"},
    {"name": "L_wrist",    "position": [0.68, 1.50, 0.0], "parent": "L_elbow"},
    {"name": "R_shoulder", "position": [-0.22, 1.50, 0.0], "parent": "chest"},
    {"name": "R_elbow",    "position": [-0.45, 1.50, 0.0], "parent": "R_shoulder"},
    {"name": "R_wrist",    "position": [-0.68, 1.50, 0.0], "parent": "R_elbow"},
    {"name": "L_hip",      "position": [0.10, 0.95, 0.0], "parent": "pelvis"},
    {"name": "L_knee",     "position": [0.10, 0.50, 0.0], "parent": "L_hip"},
    {"name": "L_ankle",    "position": [0.10, 0.08, 0.0], "parent": "L_knee"},
    {"name": "L_toe",      "position": [0.10, 0.02, 0.14], "parent": "L_ankle"},
    {"name": "R_hip",      "position": [-0.10, 0.95, 0.0], "parent": "pelvis"},
    {"name": "R_knee",     "position": [-0.10, 0.50, 0.0], "parent": "R_hip"},
    {"name": "R_ankle",    "position": [-0.10, 0.08, 0.0], "parent": "R_knee"},
    {"name": "R_toe",      "position": [-0.10, 0.02, 0.14], "parent": "R_ankle"},
]

# Body pieces: kind, name, scale, translate, rotate. Divisions kept modest -
# the around-vs-along coupling (#669) makes length rows expensive; this eval
# is that ticket's second data point.
DIVISIONS = 8
PARTS = [
    ("cylinder", "torso", [0.34, 0.60, 0.22], [0.0, 1.32, 0.0], None),
    ("sphere",   "head_p", [0.20, 0.24, 0.20], [0.0, 1.78, 0.0], None),
    ("cylinder", "arm_L", [0.10, 0.48, 0.10], [0.45, 1.50, 0.0], [0, 0, 90]),
    ("cylinder", "arm_R", [0.10, 0.48, 0.10], [-0.45, 1.50, 0.0], [0, 0, 90]),
    ("cylinder", "leg_L", [0.11, 0.92, 0.11], [0.10, 0.52, 0.0], None),
    ("cylinder", "leg_R", [0.11, 0.92, 0.11], [-0.10, 0.52, 0.0], None),
    ("cube",     "foot_L", [0.10, 0.08, 0.26], [0.10, 0.05, 0.06], None),
    ("cube",     "foot_R", [0.10, 0.08, 0.26], [-0.10, 0.05, 0.06], None),
]

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


# Captures every edge's CURRENT length; on the first call it also stores the
# list as the bind baseline in the plugin's persistent exec namespace, so the
# per-edge comparison (review item c) never round-trips thousands of floats.
EDGE_PROBE = """
import maya.cmds as cmds
import maya.api.OpenMaya as om
_mesh = %(mesh)r
_shape = cmds.listRelatives(_mesh, shapes=True, fullPath=True)[0]
_flat = cmds.xform(_mesh + '.vtx[*]', query=True, worldSpace=True,
                   translation=True)
_sel = om.MSelectionList()
_sel.add(_shape)
_it = om.MItMeshEdge(_sel.getDagPath(0))
_lengths = []
while not _it.isDone():
    _a = _it.vertexId(0) * 3
    _b = _it.vertexId(1) * 3
    _dx = _flat[_a] - _flat[_b]
    _dy = _flat[_a + 1] - _flat[_b + 1]
    _dz = _flat[_a + 2] - _flat[_b + 2]
    _lengths.append((_dx * _dx + _dy * _dy + _dz * _dz) ** 0.5)
    _it.next()
if %(store)s:
    HUMANOID_BIND_EDGES = list(_lengths)
_worst = 0.0
_worst_i = -1
for _i in range(len(_lengths)):
    _b0 = HUMANOID_BIND_EDGES[_i]
    if _b0 > 1e-9 and _lengths[_i] / _b0 > _worst:
        _worst = _lengths[_i] / _b0
        _worst_i = _i
{'edges': len(_lengths),
 'shells': cmds.polyEvaluate(_mesh, shell=True),
 'vertices': len(_flat) // 3,
 'max_edge_ratio': round(_worst, 6),
 'worst_edge': _worst_i}
"""


def edge_probe(store, what):
    return py(EDGE_PROBE % {"mesh": "|" + MESH, "store": repr(bool(store))},
              what)


def biped_pose(joints_deg):
    """The golem pose abstraction (hip/knee/ankle/shoulder/elbow, degrees)
    on the biped. Legs bend about X (forward); arms are X-aligned chains, so
    their swing is about Z, mirrored per side; a light spine curl keeps the
    silhouette honest."""
    hip = joints_deg["hip"]
    knee = joints_deg["knee"]
    ankle = joints_deg["ankle"]
    shoulder = joints_deg["shoulder"]
    elbow = joints_deg["elbow"]
    spine = -hip / 6.0
    return {
        "L_hip": [hip, 0, 0], "R_hip": [hip, 0, 0],
        "L_knee": [knee, 0, 0], "R_knee": [knee, 0, 0],
        "L_ankle": [ankle, 0, 0], "R_ankle": [ankle, 0, 0],
        "L_shoulder": [0, 0, -abs(shoulder)],
        "R_shoulder": [0, 0, abs(shoulder)],
        "L_elbow": [0, 0, -abs(elbow)],
        "R_elbow": [0, 0, abs(elbow)],
        "spine_01": [spine, 0, 0], "spine_02": [spine, 0, 0],
        "chest": [spine, 0, 0],
    }


def render(tag):
    params = {"angles": ["front", "side"], "target": ["|" + MESH],
              "resolution": 640, "samples": 3, "renderer": "arnold"}
    response = send("render_scene", params, timeout_s=900.0)
    if response.get("status") != "ok":
        params["renderer"] = "hw2"
        response = send("render_scene", params, timeout_s=900.0)
    if response.get("status") != "ok":
        check("render %s" % tag, False,
              json.dumps(response.get("error"))[:200])
        return
    written = []
    for image in response["result"]["images"]:
        path = out("humanoid_%s_%s.png" % (tag, image["angle"]))
        with open(path, "wb") as fh:
            fh.write(base64.b64decode(image["png_b64"]))
        written.append(path)
    check("render %s" % tag, len(written) == 2,
          "renderer=%s" % response["result"].get("renderer"))
    return written


def main():
    if PORT == 9877:
        print("refusing to run on 9877: this eval discards the open scene "
              "(two-Maya policy). Launch a disposable Maya on 9878.")
        return 2

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(POSES_PATH) as fh:
        golem_poses = json.load(fh)
    identity = py("import os\n{'pid': os.getpid()}", "identity")
    print("Maya on %d: pid %s, writing to %s\n"
          % (PORT, identity["pid"], OUT_DIR))

    # ---- 1. build one mesh, one skeleton, bind
    ok("new_scene", {"confirm": True})
    for kind, name, scale, translate, rotate in PARTS:
        params = {"kind": kind, "name": name, "divisions": DIVISIONS,
                  "scale": scale, "translate": translate}
        if rotate:
            params["rotate"] = rotate
        ok("create_primitive", params)
    ok("combine", {"objects": [p[1] for p in PARTS], "name": MESH})
    frozen = py(
        "import maya.cmds as cmds\n"
        "cmds.makeIdentity(%r, apply=True, translate=False, rotate=True, "
        "scale=True, normal=0, preserveNormals=True)\n"
        "[round(v, 9) for v in cmds.getAttr(%r + '.scale')[0]]"
        % ("|" + MESH, "|" + MESH), "freeze the combined mesh")
    check("the humanoid carries no node scale before binding",
          frozen == [1.0, 1.0, 1.0], "scale=%s" % (frozen,))

    skeleton = ok("create_skeleton", {"joints": JOINTS})
    check("the skeleton built all %d joints" % JOINT_COUNT,
          len(skeleton["joints"]) == JOINT_COUNT,
          "root=%s" % skeleton["root"])
    root = skeleton["root"]

    bind = ok("bind_skin", {"mesh": "|" + MESH, "root": root},
              timeout_s=600.0)
    check("the bind leaves NO vertex unowned",
          bind["unweighted_vertices"] == 0,
          "unweighted=%d warnings=%s"
          % (bind["unweighted_vertices"], bind["warnings"]))
    at_bind = edge_probe(store=True, what="bind-pose edge baseline")
    print("  bind: %s" % json.dumps(at_bind))
    check("the combined mesh is %d shells" % PIECES,
          at_bind["shells"] == PIECES, "shells=%d" % at_bind["shells"])

    # ---- 2. the craft pass
    report0 = ok("weight_report", {"mesh": "|" + MESH})
    print("  bind report: unweighted=%d exceeded=%d hist=%s"
          % (report0["unweighted_vertices"],
             report0["max_influences_exceeded"],
             json.dumps(report0["histogram"])))

    region = ok("set_region_weights", {
        "mesh": "|" + MESH, "joint": "L_shoulder",
        "within_radius_of": [0.24, 1.50, 0.0], "radius": 0.12,
        "weight": 0.85, "falloff": "linear"})
    check("the shoulder region took the authored weight",
          region["vertices_in_region"] > 0 and region["changed_vertices"] > 0,
          "region=%d changed=%d" % (region["vertices_in_region"],
                                    region["changed_vertices"]))

    mirror = ok("mirror_weights", {"mesh": "|" + MESH, "axis": "x"})
    check("the mirror wrote the right side from the left",
          mirror["mirrored_vertices"] > 0 and mirror["unweighted_vertices"] == 0,
          "mirrored=%d unpaired=%d changed=%d"
          % (mirror["mirrored_vertices"], mirror["unpaired_vertices"],
             mirror["changed_vertices"]))

    smooth = ok("smooth_weights", {
        "mesh": "|" + MESH,
        "joints": ["L_hip", "R_hip", "L_shoulder", "R_shoulder"],
        "iterations": 2})
    check("smoothing touched the hard joints and kept integrity",
          smooth["changed_vertices"] > 0
          and smooth["unweighted_vertices"] == 0
          and smooth["max_influences_exceeded"] == 0,
          "smoothed=%d changed=%d" % (smooth["smoothed_vertices"],
                                      smooth["changed_vertices"]))

    report = ok("weight_report", {"mesh": "|" + MESH})
    check("the crafted weights are clean",
          report["unweighted_vertices"] == 0
          and report["max_influences_exceeded"] == 0,
          "unweighted=%d exceeded=%d sum_err=%.2g"
          % (report["unweighted_vertices"],
             report["max_influences_exceeded"],
             report["max_weight_sum_error"]))
    by_joint = {p["joint"].split("|")[-1]: p["vertices"]
                for p in report["per_joint"]}
    lr = [("L_shoulder", "R_shoulder"), ("L_hip", "R_hip"),
          ("L_knee", "R_knee"), ("L_elbow", "R_elbow")]
    asym = {"%s/%s" % (a, b): (by_joint.get(a, 0), by_joint.get(b, 0))
            for a, b in lr
            if abs(by_joint.get(a, 0) - by_joint.get(b, 0))
            > 0.02 * max(by_joint.get(a, 0), by_joint.get(b, 1))}
    check("left and right ownership are symmetric within 2%", not asym,
          json.dumps(asym) if asym else
          "; ".join("%s=%d/%d" % (a, by_joint.get(a, 0), by_joint.get(b, 0))
                    for a, b in lr))

    # ---- 3+4. the five poses, measured and rendered
    ok("setup_lighting", {"preset": "three_point"})
    render("bind")
    baseline_poses = {}
    for pose_name in ("rest", "crouch", "extend", "air", "absorb"):
        rotations = biped_pose(golem_poses[pose_name]["joints_deg"])
        posed = ok("pose_skeleton", {"root": root, "rotations": rotations})
        inert = [m for m in posed["per_mesh"] if m["max_displacement"] < 1e-3]
        check("%s: the mesh moved with the skeleton" % pose_name,
              posed["max_displacement"] > 0.05 and not inert,
              "max_disp=%.4f displaced=%d"
              % (posed["max_displacement"], posed["displaced_vertices"]))
        probe = edge_probe(store=False, what="%s edge probe" % pose_name)
        check("%s: no edge stretched past %.1fx ITS OWN bind length"
              % (pose_name, EDGE_STRETCH_MAX),
              probe["max_edge_ratio"] <= EDGE_STRETCH_MAX,
              "max_edge_ratio=%.3f (edge %d)"
              % (probe["max_edge_ratio"], probe["worst_edge"]))
        check("%s: topology unchanged" % pose_name,
              probe["shells"] == PIECES
              and probe["edges"] == at_bind["edges"],
              "shells=%d edges=%d" % (probe["shells"], probe["edges"]))
        render(pose_name)
        baseline_poses[pose_name] = {
            "rotations_deg": rotations,
            "max_displacement": posed["max_displacement"],
            "max_edge_ratio": probe["max_edge_ratio"],
        }
        reset = ok("reset_pose", {"root": root})
        back = edge_probe(store=False, what="%s reset probe" % pose_name)
        check("%s: reset returned the mesh to bind" % pose_name,
              back["max_edge_ratio"] <= 1.0 + 1e-6,
              "max_edge_ratio=%.6f after reset" % back["max_edge_ratio"])

    print("\n" + "=" * 72)
    print("JUDGE: each posed render must read as ONE CONTINUOUS BODY.")
    print("Candy-wrapper pinching at shoulders, a hip crease that tears")
    print("open, or a limb that stays behind is a FAIL even with every")
    print("number above green. Renders: %s" % OUT_DIR)
    print("=" * 72 + "\n")

    # ---- 6. skinned export from the bind pose
    fbx = out("humanoid.fbx")
    if os.path.exists(fbx):
        os.unlink(fbx)
    response = send("export_fbx", {"path": fbx.replace("\\", "/"),
                                   "metres_per_unit": 1.0,
                                   "include_skins": True}, timeout_s=600.0)
    exported = check("the skinned humanoid exports",
                     response.get("status") == "ok",
                     json.dumps(response.get("error"))[:300])
    if exported:
        result = response["result"]
        skin = result["skin"]
        print("  skin: %s" % json.dumps(skin))
        check("one deformer, one cluster per joint",
              skin["deformers"] == 1 and skin["clusters"] == JOINT_COUNT,
              "deformers=%d clusters=%d"
              % (skin["deformers"], skin["clusters"]))
        check("a bind pose, no unowned file vertices",
              skin["bind_pose_present"] is True
              and skin["unweighted_file_vertices"] == 0)
        check("file weight sums inside the exporter's pruning",
              skin["max_weight_sum_error"] is not None
              and skin["max_weight_sum_error"] < WEIGHT_SUM_TOL,
              "err=%r tol=%g" % (skin["max_weight_sum_error"],
                                 WEIGHT_SUM_TOL))
        facts = fbxbytes.read_fbx(fbx)
        limbs = [n for n in facts.nodes if n.kind == "LimbNode"]
        check("the bytes carry %d LimbNode joints" % JOINT_COUNT,
              len(limbs) == JOINT_COUNT, "LimbNodes=%d" % len(limbs))
        check("an independent byte read agrees with the tool",
              fbxbytes.skin_facts(facts) == skin)
        with open(out("baseline.json"), "w") as fh:
            json.dump({
                "fbx": "humanoid.fbx",
                "bytes": result["bytes"],
                "joint_models": len(limbs),
                "skin": skin,
                "world_bounds_min": result["world_bounds_min"],
                "world_bounds_max": result["world_bounds_max"],
                "poses": baseline_poses,
            }, fh, indent=2, sort_keys=True)
        print("  baseline: %s" % out("baseline.json"))

    print("\n" + "-" * 72)
    print("PRESET VERDICT INPUT (#668 open question): the skeleton above is")
    print("%d hand-listed joints, %d lines of literal data. Record on the"
          % (JOINT_COUNT, len(JOINTS)))
    print("ticket whether that was a papercut worth preset=\"biped\" or fine.")
    print("-" * 72)

    failed = [label for passed, label in CHECKS if not passed]
    print("\n%d/%d passed" % (len(CHECKS) - len(failed), len(CHECKS)))
    for label in failed:
        print("  FAILED: %s" % label)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 1: Write the file** exactly as above; adjust ONLY where reality disagrees (e.g. `combine`'s param names — check `docs/protocol.md`'s combine row and `maya_plugin/handlers/combine.py` before running; `create_primitive`'s `rotate` param spelling likewise).

- [ ] **Step 2: Deploy and launch the gate Maya**

```bash
uv run python maya_plugin/install.py --yes
```

Launch a disposable Maya on 9878 with a NEUTRAL cwd (not the repo), per the two-Maya policy; verify the pid answering 9878 is the one just launched (#648 — `netstat -ano | findstr 9878`, match against the launched process; `taskkill /F /T` any stale claimant first).

- [ ] **Step 3: Run the gate**

```bash
uv run python evals/humanoid_live.py
```

Expected: exit 0 with all checks green. Iterate on FAILures — the craft constants (region radius, smoothing iterations, `EDGE_STRETCH_MAX`) may need tuning against measured reality; every tuned number gets a comment saying what was measured, in the eval file.

- [ ] **Step 4: Judge the renders.** Read all 12 renders. The acceptance is the JUDGED one (spec): hips/shoulders read as one continuous body in every pose. If a pose fails the eye, fix weights craft (or the tools) and re-run — a green number sheet does not override the pixels.

- [ ] **Step 5: Run the gate a second time** (fresh scene each run — proves repeatability, the serpent precedent). Expected: exit 0 twice.

- [ ] **Step 6: Commit the eval + artifacts**

```bash
git add evals/humanoid_live.py evals/humanoid_live/
git commit -m "feat(#668): humanoid live gate - craft pass, five poses, per-edge tearing, skinned export"
```

---

### Task 14: Final verification and closeout prep

- [ ] **Step 1: Full headless suite** — `uv run pytest -q`. Expected: green, count > 1073.
- [ ] **Step 2: Full mayapy suite** — `E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q`. Expected: green, count > 110.
- [ ] **Step 3: Serpent regression** — `uv run python evals/serpent_live.py` against the 9878 Maya. Expected: 25/25 — phase 2 must not have moved phase 1.
- [ ] **Step 4:** `git status` clean; every task committed.
- [ ] **Step 5:** Use superpowers:finishing-a-development-branch. Update #668 (notes: measured gate numbers, suite counts, the preset verdict, item (e) decision) — status per the outcome. Record the biped-preset verdict on #668 explicitly.

## Self-Review Notes

- Spec coverage: `mirror_weights` (T4-5), `smooth_weights` (T6-7), `set_region_weights` (T8-9), `weight_report` (T2-3), humanoid gate with five golem poses + judged renders (T13), preset question deferred-and-instrumented (T13 verdict block + plan header decision). Review items: (a) T10, (b) T11, (c) T13's per-edge probe, (d)/(e)/(f) decisions recorded in the header.
- Type consistency: `per_joint` reuses `SkinJointStats`; all mutators share `_skin_cluster_for`/`_set_skin_weights`/`_skin_weights`; `changed_vertices` everywhere comes from `rigmath.changed_rows` on the re-read table.
- Known adaptation points (deliberate, flagged in-place): test_server_tools fixture names (T3/T5/T7/T9 say "follow the file's existing pattern"), `combine`/`create_primitive` param spellings in the eval (T13 Step 1).
