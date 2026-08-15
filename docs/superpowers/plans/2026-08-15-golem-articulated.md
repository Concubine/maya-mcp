# Golem, articulated — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the #603 pivot tool, then build the articulated golem of
`docs/superpowers/specs/2026-08-15-golem-articulated-design.md` through MCP tool
commands, and report where the toolset fought the brief.

**Architecture:** Two phases. Tasks 1–3 add per-object pivot placement to the plugin
and the MCP surface (TDD, headless tests, then a live gate). Tasks 4–11 drive a live
Maya through `mcp__maya__*` tools to build 29 chunks, and record a ledger row per
build step. `execute_python` is free for measurement; every use of it to BUILD is a
finding.

**Tech Stack:** Python 3, `maya.cmds` inside Maya, pytest headless with a `FakeCmds`
double, FastMCP + pydantic on the server side, `uv` for running.

## Global Constraints

- Head height = 1.0 scene unit. Every dimension in this plan is in those units.
- Coordinate frame: +Y up, +X the golem's left, +Z forward (facing camera).
- Build the centre and LEFT side only; the right side is mirrored across X=0.
- Every chunk stays a separate closed watertight mesh. Never fuse the figure.
- Chunk names are `golem_<side>_<part>`, side ∈ `C`, `L`, `R`.
- Two-Maya policy (#577): the user's Maya is port **9877**. `evals/live_call.py`
  defaults to 9878, so live scripts need `MAYA_MCP_PORT=9877`.
- #579 is OPEN: `maya_new_scene` wedges Maya after an isolate capture of a
  boolean-produced mesh. Never call `maya_new_scene` after Task 6. Restart Maya
  instead.
- The staleness handshake must read clean before any render is judged.
- Run pytest as `uv run pytest`.

---

## Revision, 2026-08-15 — after the final whole-branch review

Three findings from the review change how this plan runs. They do not change the
design; they change where pivots are placed and what counts as proof.

**1. A pivot set in Task 4 will not survive to Task 8.** `boolean_op` produces a
NEW node carrying Maya's pivot, not yours (Task 6 cuts four sockets), and
`mesh_cleanup` defaults `freeze_transforms=True`, which resets pivots to the
origin. Whatever `array` mode=mirror leaves on a mirrored child is unproven
(`array.py:236-251` groups, sets a group pivot, negative-scales, freezes,
unparents, deletes the group).

So the rig is placed **twice**, deliberately:

- Task 4 keeps its `pivots` map. That call is the point of #603 and of this
  benchmark — can the toolset place a rig in one call? — and the answer is
  ledger evidence either way.
- **Task 8 gains a re-place pass** over all 29 chunks, after every boolean and
  every mirror, using `transform.pivot` (the proven-live path). Task 8 must
  first MEASURE which of the Task 4 pivots survived and record the count. A
  rig that has to be placed twice is itself a finding for the report.

**2. `assemble`'s reported pivot is not evidence.** It was computed from the
input, so Task 4 Step 4's "every object's `pivot` equals the map" could not
fail. Being fixed to query Maya back; until `evals/assemble_pivots_live.py`
passes, verify pivots with an independent `execute_python` query, not with the
response. Measurement, so not an escape.

**3. Read names back from the response.** `pivots` is keyed by chunk label, but
returned names come from `naming.unique_name` and become `golem_L_upperarm1` if
the name is taken. The pivot still lands correctly; local `{name: pivot}`
bookkeeping would not. Start from an empty scene and trust `objects[i]["name"]`.

Also carried: single-part and multi-part chunks are structurally different —
a multi-part chunk comes back frozen to identity, a single-part chunk keeps its
`scale = dim` and rotate. Both appear in this build. Anything reading transforms
alongside pivots must not assume the two are interchangeable.

---

## File Structure

| File | Responsibility |
|---|---|
| `maya_plugin/handlers/modeling.py` | `transform` gains a `pivot` vec3 (Task 1) |
| `maya_plugin/handlers/assemble.py` | `assemble` gains a `pivots` chunk→vec3 map (Task 2) |
| `tests/test_modeling.py` | headless tests for `transform.pivot` |
| `tests/test_assemble.py` | headless tests for `assemble.pivots` |
| `src/maya_mcp/schemas.py` | `TransformedObject.pivot` field |
| `src/maya_mcp/server.py` | `maya_transform` and `maya_assemble` parameters |
| `evals/pivot_live.py` | live gate proving pivots land in a real Maya |
| `evals/golem_run_2/tool_ledger.md` | one row per build step — the report's evidence |
| `evals/golem_run_2/*.png` | renders kept as artifacts |
| `docs/superpowers/specs/2026-08-15-golem-tool-gaps-ranked.md` | the deliverable report |

**Design decision, deviating from #603 as filed.** The ticket proposed a per-*part*
pivot in `assemble`. That is wrong: parts unite into chunks, so five parts sharing
one chunk have one pivot between them. This plan adds a per-*chunk* map instead —
`pivots: {chunk_name: [x,y,z]}`. Record this on #603 when closing.

**YAGNI.** Explicit vec3 only. The named modes floated in #603 (`min_y` and friends)
are NOT built — every joint centre in this build is already known from the design,
and a foot's ground plane is derivable from `maya_get_object_info`.

---

### Task 1: `transform` accepts a pivot

**Files:**
- Modify: `maya_plugin/handlers/modeling.py:281-316`
- Test: `tests/test_modeling.py`

**Interfaces:**
- Consumes: `modeling._vec3(params, key)`, existing, returns `Optional[List[float]]`.
- Produces: `transform` accepts `pivot: [x,y,z]` (world space, absolute). Each entry
  in the returned `objects` list gains `"pivot": [x,y,z]`, always present.

Semantics that matter: setting a pivot must NOT move the geometry, and the pivot is
applied BEFORE translate/rotate/scale so a relative rotation in the same call turns
about the new pivot.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_modeling.py`:

```python
def test_transform_pivot_alone_is_enough(monkeypatch):
    fake = FakeCmds(objects={"|a"})
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    result = modeling.transform({"names": ["|a"], "pivot": [1.0, 2.0, 3.0]})
    assert result["objects"][0]["pivot"] == [1.0, 2.0, 3.0]
    pivot_calls = [c for c in fake.calls if c[0] == "xform" and "pivots" in c[2]]
    assert len(pivot_calls) == 1
    assert pivot_calls[0][2]["pivots"] == (1.0, 2.0, 3.0)
    assert pivot_calls[0][2]["worldSpace"] is True


def test_transform_pivot_applied_before_rotate(monkeypatch):
    fake = FakeCmds(objects={"|a"})
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    modeling.transform({"names": ["|a"], "pivot": [0.0, 5.0, 0.0],
                        "rotate": [0.0, 90.0, 0.0]})
    kinds = [c[2] for c in fake.calls if c[0] == "xform"]
    pivot_at = next(i for i, kw in enumerate(kinds) if "pivots" in kw)
    rotate_at = next(i for i, kw in enumerate(kinds) if "rotation" in kw)
    assert pivot_at < rotate_at, "pivot must be set before the rotation uses it"


def test_transform_pivot_rejects_bad_shape(monkeypatch):
    fake = FakeCmds(objects={"|a"})
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        modeling.transform({"names": ["|a"], "pivot": [1.0, 2.0]})
    assert "pivot" in str(exc.value)


def test_transform_still_refuses_an_empty_call(monkeypatch):
    fake = FakeCmds(objects={"|a"})
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        modeling.transform({"names": ["|a"]})
    assert "pivot" in exc.value.hint
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_modeling.py -k pivot -v`
Expected: FAIL. `test_transform_pivot_alone_is_enough` raises `HandlerError:
nothing to do`; the others fail on the missing key or ordering.

- [ ] **Step 3: Teach FakeCmds to record a pivot query**

`FakeCmds.xform` in `tests/test_modeling.py:71` returns scale for any query that
isn't translation or rotation, so a pivot query would silently return scale. Fix the
double before trusting it. Replace the query branch:

```python
    def xform(self, name, **kw):
        if kw.get("query"):
            t, r, s = self.xf.get(name, ((0, 0, 0), (0, 0, 0), (1, 1, 1)))
            if kw.get("translation"):
                return list(t)
            if kw.get("rotation"):
                return list(r)
            if kw.get("rotatePivot") or kw.get("pivots"):
                return list(self.pivots.get(name, (0, 0, 0)))
            return list(s)
        if "pivots" in kw:
            self.pivots[name] = tuple(kw["pivots"])
        self.calls.append(("xform", name, kw))
```

and add `self.pivots = {}` to `FakeCmds.__init__` beside `self.xf = {}`.

- [ ] **Step 4: Implement it**

In `maya_plugin/handlers/modeling.py`, replace the body of `transform` from the
`translate = ` line through the `_apply_xform` call:

```python
    translate = _vec3(params, "translate")
    rotate = _vec3(params, "rotate")
    scale = _vec3(params, "scale")
    pivot = _vec3(params, "pivot")
    if translate is None and rotate is None and scale is None and pivot is None:
        raise HandlerError(
            "nothing to do",
            hint="pass at least one of translate, rotate, scale, pivot",
        )
    relative = params.get("relative", True) is not False
    resolved = [naming.require_object(cmds, str(n)) for n in names]

    warnings: List[str] = []
    objects: List[Dict[str, Any]] = []
    for name in resolved:
        moved = ledger.check(cmds, name)
        if moved:
            warnings.append(moved)
        # Pivot FIRST: a relative rotation in the same call must turn about the
        # new pivot, not the old one. `pivots` moves the pivot without moving
        # the geometry, which is the whole point - a rig is pivots.
        if pivot is not None:
            cmds.xform(name, worldSpace=True, pivots=tuple(pivot))
        _apply_xform(cmds, name, translate, rotate, scale, relative)
        ledger.record(cmds, name)
        objects.append(
            {
                "name": name,
                "translate": cmds.xform(name, query=True, worldSpace=True, translation=True),
                "rotate": cmds.xform(name, query=True, worldSpace=True, rotation=True),
                "scale": cmds.xform(name, query=True, worldSpace=True, scale=True),
                "pivot": cmds.xform(name, query=True, worldSpace=True, rotatePivot=True),
            }
        )
    return {"objects": objects, "warnings": warnings}
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_modeling.py -v`
Expected: PASS, including the pre-existing transform tests.

- [ ] **Step 6: Commit**

```bash
git add maya_plugin/handlers/modeling.py tests/test_modeling.py
git commit -m "feat(modeling): a pivot is a place, not a mode"
```

---

### Task 2: `assemble` accepts a per-chunk pivot map

**Files:**
- Modify: `maya_plugin/handlers/assemble.py:288-296` and `:346-379`
- Test: `tests/test_assemble.py`

**Interfaces:**
- Consumes: `combine.PIVOT_MODES`, `combine.unite(cmds, nodes, name, pivot_mode, freeze)`.
- Produces: `assemble` accepts `pivots: {chunk_name: [x, y, z]}`. Chunks named in the
  map get that world-space pivot; chunks absent from it keep the existing global
  `pivot` mode. Every entry in the result's `objects` list carries its `pivot`,
  including single-part chunks that previously reported `None`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_assemble.py`:

```python
def test_assemble_explicit_pivot_overrides_mode(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(assemble, "_cmds", lambda: fake)
    result = assemble.assemble({
        "name": "golem",
        "parts": [
            {"kind": "cube", "pos": [0, 1, 0], "dim": [1, 1, 1], "chunk": "arm"},
            {"kind": "cube", "pos": [0, 2, 0], "dim": [1, 1, 1], "chunk": "arm"},
        ],
        "pivot": "center",
        "pivots": {"arm": [0.0, 3.0, 0.0]},
    })
    arm = next(o for o in result["objects"] if o["name"].endswith("arm"))
    assert arm["pivot"] == [0.0, 3.0, 0.0]


def test_assemble_pivots_reach_single_part_chunks(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(assemble, "_cmds", lambda: fake)
    result = assemble.assemble({
        "name": "golem",
        "parts": [{"kind": "cube", "pos": [0, 1, 0], "dim": [1, 1, 1], "chunk": "fist"}],
        "pivots": {"fist": [1.0, 2.0, 3.0]},
    })
    assert result["objects"][0]["pivot"] == [1.0, 2.0, 3.0]


def test_assemble_unlisted_chunks_keep_the_mode(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(assemble, "_cmds", lambda: fake)
    result = assemble.assemble({
        "name": "golem",
        "parts": [
            {"kind": "cube", "pos": [0, 1, 0], "dim": [1, 1, 1], "chunk": "a"},
            {"kind": "cube", "pos": [0, 2, 0], "dim": [1, 1, 1], "chunk": "a"},
            {"kind": "cube", "pos": [0, 3, 0], "dim": [1, 1, 1], "chunk": "b"},
            {"kind": "cube", "pos": [0, 4, 0], "dim": [1, 1, 1], "chunk": "b"},
        ],
        "pivots": {"a": [9.0, 9.0, 9.0]},
    })
    by_chunk = {o["name"].split("|")[-1]: o for o in result["objects"]}
    assert by_chunk["a"]["pivot"] == [9.0, 9.0, 9.0]
    assert by_chunk["b"]["pivot"] != [9.0, 9.0, 9.0]


def test_assemble_pivots_rejects_an_unknown_chunk(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(assemble, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        assemble.assemble({
            "name": "golem",
            "parts": [{"kind": "cube", "pos": [0, 1, 0], "dim": [1, 1, 1], "chunk": "arm"}],
            "pivots": {"leg": [0.0, 0.0, 0.0]},
        })
    assert "leg" in str(exc.value)


def test_assemble_pivots_rejects_a_bad_vector(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(assemble, "_cmds", lambda: fake)
    with pytest.raises(HandlerError):
        assemble.assemble({
            "name": "golem",
            "parts": [{"kind": "cube", "pos": [0, 1, 0], "dim": [1, 1, 1], "chunk": "arm"}],
            "pivots": {"arm": [0.0, 0.0]},
        })
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_assemble.py -k pivot -v`
Expected: FAIL. `pivots` is not a recognised key, so the explicit-pivot assertions
fail and the unknown-chunk case raises nothing.

- [ ] **Step 3: Validate the map**

In `maya_plugin/handlers/assemble.py`, immediately after the `pivot_mode` block that
ends at line 293, insert:

```python
    explicit_pivots: Dict[str, List[float]] = {}
    raw_pivots = params.get("pivots")
    if raw_pivots is not None:
        if not isinstance(raw_pivots, dict):
            raise HandlerError(
                "pivots must be a map of chunk name to [x, y, z]",
                hint='e.g. pivots={"golem_L_upperarm": [1.25, 3.95, 0.15]}',
            )
        known = {part["chunk"] for part in resolved}
        for chunk_name, value in raw_pivots.items():
            if chunk_name not in known:
                raise HandlerError(
                    "pivots names chunk %r, which no part builds" % chunk_name,
                    hint="chunks in this call: %s" % ", ".join(sorted(known)),
                )
            # _vec3 returns None for an absent value; an explicit map has no
            # "absent" - naming a chunk and giving it nothing is a mistake.
            if value is None:
                raise HandlerError(
                    "pivots[%r] is null; a pivot is a world-space point" % chunk_name,
                    hint="e.g. [1.25, 3.95, 0.15], or drop the key to keep the "
                    "global pivot mode",
                )
            explicit_pivots[chunk_name] = _vec3(value, "pivots[%r]" % chunk_name)
```

- [ ] **Step 4: Apply the pivots**

Still in `assemble.py`, replace the two result-building branches at lines 346–379:

```python
    objects: List[Dict[str, Any]] = []
    for chunk in chunks:
        nodes = members[chunk]
        wanted = explicit_pivots.get(chunk)
        if merge and len(nodes) > 1:
            result = combine.unite(cmds, nodes, chunk, pivot_mode, freeze)
            placed = result["pivot"]
            if wanted is not None:
                cmds.xform(result["name"], worldSpace=True, pivots=tuple(wanted))
                placed = list(wanted)
            objects.append({
                "name": result["name"], "parts": len(nodes),
                "tris": result["tris"], "verts": result["verts"],
                "faces": result["faces"], "shells": result["shells"],
                "pivot": placed, "combined": True,
            })
            warnings.extend(result["warnings"])
            ledger.record(cmds, result["name"])
        else:
            # A chunk of one is still that chunk: a caller who labelled it
            # expects an object under that name whether it took five boxes or
            # one. An explicitly named part keeps its own name - that is the
            # caller being specific, not defaulting.
            if len(nodes) == 1 and not explicit[chunk] and _short(nodes[0]) != chunk:
                nodes = [(cmds.ls(cmds.rename(nodes[0],
                                              naming.unique_name(cmds, chunk)),
                                  long=True) or [nodes[0]])[0]]
            for node in nodes:
                if wanted is not None:
                    cmds.xform(node, worldSpace=True, pivots=tuple(wanted))
                shape = cmds.listRelatives(node, shapes=True, fullPath=True,
                                           noIntermediate=True)[0]
                objects.append({
                    "name": node, "parts": 1,
                    "tris": cmds.polyEvaluate(shape, triangle=True),
                    "verts": cmds.polyEvaluate(shape, vertex=True),
                    "faces": cmds.polyEvaluate(shape, face=True),
                    "shells": cmds.polyEvaluate(shape, shell=True),
                    "pivot": list(wanted) if wanted is not None else None,
                    "combined": False,
                })
                ledger.record(cmds, node)
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_assemble.py -v`
Expected: PASS, including every pre-existing assemble test.

- [ ] **Step 6: Commit**

```bash
git add maya_plugin/handlers/assemble.py tests/test_assemble.py
git commit -m "feat(assemble): 29 pivots in the call that builds them"
```

---

### Task 3: Put it on the MCP surface, deploy, and gate it live

**Files:**
- Modify: `src/maya_mcp/schemas.py:163-169`
- Modify: `src/maya_mcp/server.py:929-951` and the `maya_assemble` tool
- Create: `evals/pivot_live.py`
- Test: `tests/test_server_tools.py`

**Interfaces:**
- Consumes: Task 1's `transform.pivot`, Task 2's `assemble.pivots`.
- Produces: `mcp__maya__maya_transform(..., pivot=[x,y,z])` and
  `mcp__maya__maya_assemble(..., pivots={chunk: [x,y,z]})`. Every later task uses these.

- [ ] **Step 1: Add the schema field**

In `src/maya_mcp/schemas.py`, `TransformedObject` gains a pivot:

```python
class TransformedObject(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    translate: List[float]
    rotate: List[float]
    scale: List[float]
    pivot: Optional[List[float]] = Field(
        default=None,
        description="World-space rotate pivot after the call - the point this "
                    "object turns about, which is what a ragdoll reads.",
    )
```

`AssembledObject.pivot` already exists at `schemas.py:386`; leave it alone.

- [ ] **Step 2: Add the tool parameters**

In `src/maya_mcp/server.py`, `maya_transform` (line 929) gains `pivot` after `scale`:

```python
        pivot: Annotated[Vec3, Field(description=(
            "World-space point to place the object's pivot at. Does NOT move the "
            "geometry - it moves what the geometry turns about. Applied before "
            "translate/rotate/scale, so a relative rotate in the same call turns "
            "about the new pivot."
        ))] = None,
```

and pass it through:

```python
                {"names": names, "translate": translate, "rotate": rotate,
                 "scale": scale, "relative": relative, "pivot": pivot},
```

In `maya_assemble`, add:

```python
        pivots: Annotated[Optional[Dict[str, List[float]]], Field(description=(
            "Chunk name -> world-space pivot. Chunks left out keep the global "
            "`pivot` mode. For an articulated figure this is the rig: each chunk "
            "pivots at its own joint, which `center` never gets right."
        ))] = None,
```

and add `"pivots": pivots` to its request dict.

- [ ] **Step 3: Run the server tool tests**

Run: `uv run pytest tests/test_server_tools.py -v`
Expected: PASS. If that file asserts an exact parameter list for these tools, update
those expectations to include `pivot` / `pivots`.

- [ ] **Step 4: Write the live gate**

Create `evals/pivot_live.py`. Headless green means nothing here — the point is that a
real Maya moves the pivot and does NOT move the mesh:

```python
"""Live gate for #603: a pivot lands, and the geometry does not move."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from evals.live_call import call, structured_result  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9877"))


def main() -> int:
    call("execute_python", {"code": "import maya.cmds as cmds\n"
                                    "cmds.polyCube(name='pivotGate')\n"
                                    "cmds.xform('pivotGate', worldSpace=True, "
                                    "translation=(2, 3, 4))\n"
                                    "'built'"}, port=PORT)

    before = structured_result(call("execute_python", {"code":
        "import maya.cmds as cmds\n"
        "(cmds.xform('pivotGate', q=True, ws=True, translation=True),\n"
        " cmds.xform('pivotGate', q=True, ws=True, boundingBox=True))"
    }, port=PORT)["result"], "before")

    response = call("transform", {"names": ["pivotGate"], "pivot": [0.0, 10.0, 0.0]},
                    port=PORT)
    if response.get("error"):
        print("FAIL transform: %s" % response["error"])
        return 1
    reported = response["result"]["objects"][0]["pivot"]

    after = structured_result(call("execute_python", {"code":
        "import maya.cmds as cmds\n"
        "(cmds.xform('pivotGate', q=True, ws=True, rotatePivot=True),\n"
        " cmds.xform('pivotGate', q=True, ws=True, translation=True),\n"
        " cmds.xform('pivotGate', q=True, ws=True, boundingBox=True))"
    }, port=PORT)["result"], "after")

    pivot, translate, bbox = after
    ok = True
    if max(abs(a - b) for a, b in zip(pivot, [0.0, 10.0, 0.0])) > 1e-4:
        print("FAIL pivot is at %s, wanted [0, 10, 0]" % (pivot,)); ok = False
    if max(abs(a - b) for a, b in zip(reported, pivot)) > 1e-4:
        print("FAIL reported %s but Maya says %s" % (reported, pivot)); ok = False
    if max(abs(a - b) for a, b in zip(before[1], bbox)) > 1e-4:
        print("FAIL the mesh MOVED: %s -> %s" % (before[1], bbox)); ok = False
    if max(abs(a - b) for a, b in zip(before[0], translate)) > 1e-4:
        print("FAIL translate changed: %s -> %s" % (before[0], translate)); ok = False

    call("execute_python", {"code": "import maya.cmds as cmds\n"
                                    "cmds.delete('pivotGate')\n'cleaned'"}, port=PORT)
    print("PASS pivot=%s bbox unchanged" % (pivot,) if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Deploy and restart**

```bash
uv run python maya_plugin/install.py --yes
```

Then restart Maya. The install prints the commit and digest it stamped; the running
session must report the same pair back.

- [ ] **Step 6: Confirm the handshake is clean**

Run: `MAYA_MCP_PORT=9877 uv run python -c "from evals.live_call import staleness_warning; print(staleness_warning(9877) or 'CLEAN')"`
Expected: `CLEAN`. Anything else means the live Maya is running other code and every
measurement after this point is worthless — fix it before continuing.

- [ ] **Step 7: Run the live gate**

Run: `MAYA_MCP_PORT=9877 uv run python evals/pivot_live.py`
Expected: `PASS pivot=[0.0, 10.0, 0.0] bbox unchanged`

- [ ] **Step 8: Commit**

```bash
git add src/maya_mcp/schemas.py src/maya_mcp/server.py evals/pivot_live.py tests/test_server_tools.py
git commit -m "feat(mcp): pivot on the surface, and a live gate that proves the mesh stays put"
```

---

### Task 4: The 29-chunk body, in one `assemble` call

**Files:**
- Create: `evals/golem_run_2/tool_ledger.md`

**Interfaces:**
- Consumes: `mcp__maya__maya_assemble` with `pivots` from Task 3.
- Produces: 18 chunks in the scene named `golem_C_*` and `golem_L_*`. Task 7 mirrors
  the 11 `golem_L_*` chunks to `golem_R_*` for 29 total.

Positions below are derived in the design doc. The leg is a real chain: hip ball at
Y=2.15, knee at [0.55, 1.116, 0.376], ankle at [0.55, 0.35, 0.145] — a 36.7° knee
flex, which is the coil.

- [ ] **Step 1: Start the ledger**

Create `evals/golem_run_2/tool_ledger.md`:

```markdown
# #601 build ledger — one row per build step

`escaped` = this step BUILT something through execute_python. Measurement calls are
not escapes and are not listed.

| # | Step | Tool | Calls | Escaped | Why |
|---|------|------|-------|---------|-----|
```

- [ ] **Step 2: Checkpoint before touching the scene**

Call `mcp__maya__maya_checkpoint` with label `golem_run_2_start`.

- [ ] **Step 3: Build the centre and left chunks**

One `mcp__maya__maya_assemble` call. `name` = `golem`, `combine` = true,
`pivot` = `center` (the fallback for anything not in `pivots`), `atlas` = 4×4.

Parts — `chunk`, `kind`, `pos`, `dim`, `rotate` where non-zero:

| chunk | kind | pos | dim | rotate |
|---|---|---|---|---|
| `golem_C_pelvis` | sphere | [0, 2.45, 0] | [1.5, 0.9, 1.2] | |
| `golem_C_waist_gasket` | sphere | [0, 2.9, 0.02] | [1.35, 0.35, 1.1] | |
| `golem_C_belly` | sphere | [0, 3.0, 0.05] | [1.45, 0.95, 1.15] | |
| `golem_C_chest_girdle` | cube | [0, 3.6, 0.1] | [2.2, 1.0, 1.3] | |
| `golem_C_neck_gasket` | sphere | [0, 4.05, 0.25] | [0.5, 0.35, 0.5] | |
| `golem_C_head` | sphere | [0, 4.5, 0.3] | [1.0, 1.0, 1.0] | |
| `golem_C_brow` | cube | [0, 4.65, 0.72] | [0.7, 0.35, 0.2] | [-15, 0, 0] |

> **Amended at Step 5, 2026-08-15, with the user.** The head was at Y=4.0 and the
> neck gasket at 3.62. Measured: the chest girdle spans 3.1–4.1, so **0.6 of the
> 1.0 head sat inside it** and the total came to 4.5 against the design's stated
> ~5.0. *"Head at the shoulder line"* reads two ways; centring the head ON 4.0
> rather than AT it reconciles the design's own total and leaves 0.1 of
> interpenetration instead of 0.6. The neck gasket moves up to the new seam.
> Measured after: total **5.0**, head 4.0–5.0, buried **0.1**, foot bottom 0.0,
> fist bottom 0.75.
| `golem_L_shoulder` | sphere | [1.15, 3.95, 0.15] | [1.1, 1.1, 1.1] | |
| `golem_L_upperarm` | cylinder | [1.25, 3.35, 0.15] | [0.62, 1.2, 0.62] | |
| `golem_L_elbow_gasket` | sphere | [1.25, 2.75, 0.15] | [0.6, 0.3, 0.6] | |
| `golem_L_forearm` | cylinder | [1.25, 2.075, 0.15] | [0.58, 1.35, 0.58] | |
| `golem_L_wrist_gasket` | sphere | [1.25, 1.4, 0.15] | [0.55, 0.28, 0.55] | |
| `golem_L_fist` | cube | [1.25, 1.075, 0.15] | [0.72, 0.65, 0.7] | |
| `golem_L_thigh` | cylinder | [0.55, 1.633, 0.188] | [0.78, 1.1, 0.78] | [-20, 0, 0] |
| `golem_L_knee_gasket` | sphere | [0.55, 1.116, 0.376] | [0.72, 0.3, 0.72] | [-2, 0, 0] |
| `golem_L_shin` | cylinder | [0.55, 0.733, 0.2605] | [0.62, 0.8, 0.62] | [17, 0, 0] |
| `golem_L_ankle_gasket` | sphere | [0.55, 0.35, 0.145] | [0.6, 0.28, 0.6] | [8, 0, 0] |
| `golem_L_foot` | cube | [0.55, 0.175, 0.34] | [0.75, 0.35, 1.2] | |

`pivots` — each chunk's PROXIMAL joint, which is the rig:

```json
{
  "golem_C_pelvis":        [0, 2.45, 0],
  "golem_C_waist_gasket":  [0, 2.9, 0.02],
  "golem_C_belly":         [0, 2.9, 0.02],
  "golem_C_chest_girdle":  [0, 3.45, 0.05],
  "golem_C_neck_gasket":   [0, 4.05, 0.25],
  "golem_C_head":          [0, 4.05, 0.25],
  "golem_C_brow":          [0, 4.5, 0.3],
  "golem_L_shoulder":      [0.9, 3.85, 0.1],
  "golem_L_upperarm":      [1.25, 3.95, 0.15],
  "golem_L_elbow_gasket":  [1.25, 2.75, 0.15],
  "golem_L_forearm":       [1.25, 2.75, 0.15],
  "golem_L_wrist_gasket":  [1.25, 1.4, 0.15],
  "golem_L_fist":          [1.25, 1.4, 0.15],
  "golem_L_thigh":         [0.55, 2.15, 0],
  "golem_L_knee_gasket":   [0.55, 1.116, 0.376],
  "golem_L_shin":          [0.55, 1.116, 0.376],
  "golem_L_ankle_gasket":  [0.55, 0.35, 0.145],
  "golem_L_foot":          [0.55, 0.35, 0.145]
}
```

- [ ] **Step 4: Verify the build measured what you asked for**

Check the `maya_assemble` result: `objects` has 18 entries, `outside_patch` is 0, and
every object's `pivot` equals the value from the map above.

Then confirm the silhouette independently — call `mcp__maya__maya_execute_python`
(measurement, not a build, so not an escape):

```python
import maya.cmds as cmds
bb = cmds.exactWorldBoundingBox("golem_C_pelvis", "golem_C_head", "golem_L_foot",
                                "golem_L_fist")
{"height_top": round(bb[4], 3), "foot_bottom": round(bb[1], 3),
 "fist_bottom": round(cmds.exactWorldBoundingBox("golem_L_fist")[1], 3)}
```

Expected: `foot_bottom` ≈ 0.0, `fist_bottom` ≈ 0.75, `height_top` ≈ 4.5.
A `foot_bottom` far off zero means the golem is floating or sunk — fix before shaping.

- [ ] **Step 5: Look at it**

Call `mcp__maya__maya_capture_viewport` at the three-quarter angle. The silhouette
must already read as a squat crouching figure. If it reads as a stack of tubes, stop
and fix proportions now — every later task is more expensive to redo.

- [ ] **Step 6: Record the ledger row and commit**

Append: `| 1 | 18 chunks + 18 pivots | assemble | 1 | no | |`

```bash
git add evals/golem_run_2/tool_ledger.md
git commit -m "chore(golem): the body, in one call"
```

---

### Task 5: Shaping — the hunch, the taper, the pressed clay

**Files:**
- Modify: `evals/golem_run_2/tool_ledger.md`

**Interfaces:**
- Consumes: the 18 chunks from Task 4, by name.
- Produces: the same 18 chunks, shaped. No renames, no new objects — Task 7 mirrors
  by name and will not find renamed chunks.

- [ ] **Step 1: Checkpoint**

`mcp__maya__maya_checkpoint`, label `before_shaping`.

- [ ] **Step 2: Taper the limb segments**

For each of `golem_L_upperarm`, `golem_L_forearm`, `golem_L_thigh`, `golem_L_shin`:
call `mcp__maya__maya_deform` with `deformer` = `flare`, and params that narrow the
distal end. Thigh narrows most (heavy at the hip, tapering to the knee) — that is the
proximal weighting the design relies on for the leg's momentum response.

- [ ] **Step 3: Bend the torso into the hunch**

`mcp__maya__maya_deform` with `deformer` = `bend` on `golem_C_belly` and
`golem_C_chest_girdle`, curving forward so the head sits ahead of the pelvis.

- [ ] **Step 4: Rough the gaskets into rubble**

`mcp__maya__maya_sculpt_ops` on each of the 6 left/centre gaskets with a
`displace_noise` op. A smooth sphere at a joint reads as a ball bearing; the collar
must read as packed rubble.

- [ ] **Step 5: Slump the joins, harden the plates**

`mcp__maya__maya_sculpt_ops` on the body chunks: `soft_move` and `inflate_region`
where chunks meet, so they read as pressed together; `bevel_edges` and `crease_edges`
on the brow, fists, and foot slabs where seams will glow.

- [ ] **Step 6: Look at it, then measure it**

`mcp__maya__maya_capture_viewport`. Then confirm nothing was renamed or lost:

```python
import maya.cmds as cmds
sorted(n for n in cmds.ls("golem_*", long=False, type="transform"))
```

Expected: the same 18 names from Task 4.

- [ ] **Step 7: Ledger and commit**

One row per tool used, with call counts. If any shaping step needed
`execute_python` to BUILD, mark `escaped = yes` and write the reason plainly.

```bash
git add evals/golem_run_2/tool_ledger.md
git commit -m "chore(golem): shaped - hunch, taper, and pressed joins"
```

---

### Task 6: Four sockets and the rune

**Files:**
- Modify: `evals/golem_run_2/tool_ledger.md`

**Interfaces:**
- Consumes: `golem_L_shoulder`, `golem_C_pelvis`, `golem_C_brow`.
- Produces: the same chunk names, now boolean-produced meshes.

**HAZARD — #579 is open from here to the end of the run.** These booleans plus an
isolate capture are exactly the combination that wedges Maya on `new_scene`. Do NOT
call `mcp__maya__maya_new_scene` for the rest of this plan. If Maya wedges, restart it.

- [ ] **Step 1: Checkpoint before EACH boolean**

`mcp__maya__maya_checkpoint` with labels `before_socket_shoulder_L`,
`before_socket_hip_L`, `before_rune`. One per boolean, not one for the group — the
point is to be able to step back exactly one operation.

- [ ] **Step 2: Cut the left shoulder socket**

Build a cutter sphere with `mcp__maya__maya_create_primitive` at the shoulder ball
centre [1.25, 3.95, 0.15], slightly larger than the upper arm's proximal end
(dim ~0.7). Then `mcp__maya__maya_boolean_op` with `op` = `difference`,
`a` = `golem_L_shoulder`, `b` = the cutter.

Verify the result is still one closed shell:

```python
import maya.cmds as cmds
{"shells": cmds.polyEvaluate("golem_L_shoulder", shell=True),
 "tris": cmds.polyEvaluate("golem_L_shoulder", triangle=True)}
```

Expected: `shells` = 1. More than one means the boolean fragmented the chunk —
restore the checkpoint and enlarge the cutter overlap.

- [ ] **Step 3: Cut the left hip socket**

Same, cutter at [0.55, 2.15, 0], dim ~0.65, against `golem_C_pelvis`.

Note in the ledger: the pelvis is a CENTRE chunk, so it takes both hip sockets. The
right one cannot be mirrored with the limbs — cut it here too, with a cutter at
[-0.55, 2.15, 0].

- [ ] **Step 4: Etch the aleph**

`mcp__maya__maya_etch_text` on `golem_C_brow` — a single inverted and mirrored aleph
(א), carved as a recess. No applied letter geometry, no emission in the recess; the
surrounding crack glow does that work.

- [ ] **Step 5: Confirm the pivots survived the booleans**

A boolean rebuilds the mesh, and a rebuilt mesh may not keep its pivot. This is a
real finding either way:

```python
import maya.cmds as cmds
{n: [round(v, 4) for v in cmds.xform(n, q=True, ws=True, rotatePivot=True)]
 for n in ("golem_L_shoulder", "golem_C_pelvis", "golem_C_brow")}
```

Expected: `golem_L_shoulder` = [0.9, 3.85, 0.1], `golem_C_pelvis` = [0, 2.45, 0],
`golem_C_brow` = [0, 4.0, 0.3]. If any moved, re-place it with
`mcp__maya__maya_transform` `pivot` — and record in the ledger that `boolean_op`
does not preserve pivots, because that is a gap the report should carry.

- [ ] **Step 6: Ledger and commit**

```bash
git add evals/golem_run_2/tool_ledger.md
git commit -m "chore(golem): sockets cut, and the word carved"
```

---

### Task 7: Mirror the left side

**Files:**
- Modify: `evals/golem_run_2/tool_ledger.md`

**Interfaces:**
- Consumes: the 11 `golem_L_*` chunks.
- Produces: 11 `golem_R_*` chunks. Scene total is 29.

`maya_array` mode=mirror takes a single polygon mesh, so this is 11 calls. Count them
honestly — the cost of that shape is one of the five claims #601 exists to test.

- [ ] **Step 1: Checkpoint**

`mcp__maya__maya_checkpoint`, label `before_mirror`.

- [ ] **Step 2: Mirror each left chunk across X=0**

For each of `golem_L_shoulder`, `golem_L_upperarm`, `golem_L_elbow_gasket`,
`golem_L_forearm`, `golem_L_wrist_gasket`, `golem_L_fist`, `golem_L_thigh`,
`golem_L_knee_gasket`, `golem_L_shin`, `golem_L_ankle_gasket`, `golem_L_foot`:

`mcp__maya__maya_array` with `mode` = `mirror`, `axis` = `x`, `pivot` = [0, 0, 0],
`name_prefix` = the chunk name with `_L_` replaced by `_R_`.

Read the `warnings` on every call. `_mirror` checks signed volume and warns when a
mirrored mesh's normals inverted — an inverted chunk renders inside out and looks
like a lighting bug. Do not skim past these.

- [ ] **Step 3: Rename to the R convention if the prefix did not take**

Check the returned names. If `maya_array` produced `golem_L_thigh_mirror1` style
names rather than the requested prefix, use `mcp__maya__maya_rename` per chunk — and
record in the ledger that the mirror's naming needed a second call each time.

- [ ] **Step 4: Place the right-side pivots**

A mirrored chunk's pivot is not automatically the mirror of its source pivot. Call
`mcp__maya__maya_transform` with `pivot` per right chunk, using the left values with
X negated — e.g. `golem_R_upperarm` gets [-1.25, 3.95, 0.15].

If all 11 can go in one call each, that is 11 calls; note in the ledger whether a
single `maya_transform` accepting a LIST of names but only ONE pivot forced one call
per chunk. That is a gap worth ranking.

- [ ] **Step 5: Measure the symmetry**

```python
import maya.cmds as cmds
out = {}
for part in ("shoulder", "upperarm", "forearm", "fist", "thigh", "shin", "foot"):
    l = cmds.xform("golem_L_%s" % part, q=True, ws=True, rotatePivot=True)
    r = cmds.xform("golem_R_%s" % part, q=True, ws=True, rotatePivot=True)
    out[part] = [round(l[0] + r[0], 4), round(l[1] - r[1], 4), round(l[2] - r[2], 4)]
out
```

Expected: every value ≈ [0, 0, 0] — X sums to zero, Y and Z match.

- [ ] **Step 6: Count the scene**

```python
import maya.cmds as cmds
len([n for n in cmds.ls("golem_*", type="transform") if not n.endswith("Shape")])
```

Expected: 29.

- [ ] **Step 7: Ledger and commit**

```bash
git add evals/golem_run_2/tool_ledger.md
git commit -m "chore(golem): the right side, eleven calls at a time"
```

---

### Task 8: The hierarchy

**Files:**
- Modify: `evals/golem_run_2/tool_ledger.md`

**Interfaces:**
- Consumes: all 29 chunks.
- Produces: one rooted tree under `golem_C_pelvis`. Later tasks address chunks by
  their long names, which now include the parent path.

- [ ] **Step 1: Checkpoint**

`mcp__maya__maya_checkpoint`, label `before_hierarchy`.

- [ ] **Step 2: Parent the tree**

`mcp__maya__maya_parent` per edge. The tree, from the design:

```
golem_C_pelvis
├─ golem_C_waist_gasket
├─ golem_C_belly
│  └─ golem_C_chest_girdle
│     ├─ golem_C_neck_gasket
│     ├─ golem_C_head
│     │  └─ golem_C_brow
│     └─ golem_<L|R>_shoulder
│        └─ golem_<L|R>_upperarm
│           ├─ golem_<L|R>_elbow_gasket
│           └─ golem_<L|R>_forearm
│              ├─ golem_<L|R>_wrist_gasket
│              └─ golem_<L|R>_fist
└─ golem_<L|R>_thigh
   ├─ golem_<L|R>_knee_gasket
   └─ golem_<L|R>_shin
      ├─ golem_<L|R>_ankle_gasket
      └─ golem_<L|R>_foot
```

Gaskets parent to the PROXIMAL member of their joint, per the design — the elbow
gasket hangs off the upper arm, not the forearm.

That is 28 edges, so 28 `maya_parent` calls unless the tool accepts a batch. Check
its signature first; if it takes one child per call, record the count.

- [ ] **Step 3: Verify parenting did not move anything or lose a pivot**

Reparenting can change a transform's local values. What must not change is where the
chunk sits in the world, or where it turns about:

```python
import maya.cmds as cmds
bad = {}
want = {"golem_L_upperarm": [1.25, 3.95, 0.15], "golem_L_shin": [0.55, 1.116, 0.376],
        "golem_R_upperarm": [-1.25, 3.95, 0.15], "golem_L_foot": [0.55, 0.35, 0.145]}
for name, expect in want.items():
    got = cmds.xform(name, q=True, ws=True, rotatePivot=True)
    if max(abs(a - b) for a, b in zip(got, expect)) > 1e-3:
        bad[name] = [round(v, 4) for v in got]
bad or "all pivots held"
```

Expected: `all pivots held`. If not, that is a finding — record it and re-place them.

- [ ] **Step 4: Ledger and commit**

```bash
git add evals/golem_run_2/tool_ledger.md
git commit -m "chore(golem): one tree, rooted at the pelvis"
```

---

### Task 9: UVs, material, and the glow that travels with the body

**Files:**
- Modify: `evals/golem_run_2/tool_ledger.md`

**Interfaces:**
- Consumes: all 29 chunks, parented.
- Produces: every chunk shaded, with per-chunk emission.

- [ ] **Step 1: Checkpoint**

`mcp__maya__maya_checkpoint`, label `before_shading`.

- [ ] **Step 2: Atlas the UVs**

`mcp__maya__maya_uv_atlas` across the 29 chunks. Task 4 already packed the 18 built
ones into a 4×4 atlas; the mirrored chunks inherit their source's UVs, so confirm
whether the mirror preserved them before re-packing:

```python
import maya.cmds as cmds
{n: cmds.polyEvaluate(n, uvcoord=True) for n in ("golem_L_thigh", "golem_R_thigh")}
```

Expected: equal counts. A zero on the right side means the mirror dropped UVs — a
finding, and a reason to re-atlas.

- [ ] **Step 3: Assign the three-map material**

`mcp__maya__maya_assign_pbr` with a real base-colour / roughness / normal atlas —
cracked kiln plates over matte terracotta, roughness ~0.85. This is claim 2 of #601:
the kit steel was authored for a building, so record honestly whether a creature's
chunk shapes read acceptably against maps authored for flat plates.

- [ ] **Step 4: Bake the seam glow per chunk**

Emission is per chunk, NOT a world-space network — the design's reason is that a
world ramp would change an arm's glow the moment the arm moves.

Compute each chunk's rest distance from the rune at [0, 4.15, 0.72], then set that
chunk's emission from a falloff over that distance: brightest at the brow, near dead
at the feet. Use `mcp__maya__maya_assign_material` per chunk with the computed
emission value.

Distances are a measurement, so computing them via `execute_python` is not an escape.
Setting the material is a build — if it goes through `execute_python` rather than
`maya_assign_material`, that is an escape and must be recorded.

- [ ] **Step 5: Verify the falloff is monotonic down the body**

```python
import maya.cmds as cmds
[(n, round(cmds.getAttr(cmds.listConnections(
    cmds.listRelatives(n, shapes=True, fullPath=True)[0], type="shadingEngine")[0]
    .replace("SG", "") + ".emissionWeight"), 3))
 for n in ("golem_C_brow", "golem_C_head", "golem_C_chest_girdle",
           "golem_C_pelvis", "golem_L_shin", "golem_L_foot")]
```

Expected: values decreasing down that list. If the attribute path differs on the
shader this build produced, read it off `maya_get_object_info`'s shading section
instead — but do confirm the ordering, because "the glow dims with distance from the
word" is the whole material story.

- [ ] **Step 6: Ledger and commit**

```bash
git add evals/golem_run_2/tool_ledger.md
git commit -m "chore(golem): clay, cracks, and a glow that travels with the chunk"
```

---

### Task 10: Light it, and get the renders out

**Files:**
- Create: `evals/golem_run_2/*.png`
- Modify: `evals/golem_run_2/tool_ledger.md`

**Interfaces:**
- Consumes: the shaded, parented golem.
- Produces: a per-chunk contact sheet, a hero turntable, and an SSAO check, all kept
  as artifacts.

- [ ] **Step 1: Light it**

`mcp__maya__maya_setup_lighting` with `preset` = `environment` for the dome, then a
warm key. This is claim 3 of #601 — the body is matte clay rather than metal, so
record what the dome actually contributes here versus the three-point rig.

- [ ] **Step 2: The per-chunk contact sheet, in ONE call**

`mcp__maya__maya_render_sheet` with all 29 chunk names as `subjects`. The cap is 48
(`render.py:38`), so 29 fits. This is claim 4: the kit sheet cost 41 round-trips, and
this is the call that is supposed to replace them. Record the wall-clock time and the
call count — 1 — against that 41.

- [ ] **Step 3: The hero turntable**

`mcp__maya__maya_capture_turntable`, 8 frames.

- [ ] **Step 4: The SSAO pass**

Per the #574 design, the joins must read under ambient occlusion, not only in beauty.
Render an AO check and look at whether the gasket collars actually sell the joins or
just look like separate balls.

- [ ] **Step 5: Save the artifacts**

Write every image under `evals/golem_run_2/`. Name them for what they show:
`contact_sheet.png`, `turntable_00.png`…, `ssao.png`, `hero_three_quarter.png`.

- [ ] **Step 6: Judge it against the rubric, in writing**

Three questions from the design, answered honestly in the ledger file:
- Does the silhouette read at thumbnail size — squat, crouched, arms to mid-shin?
- Do the joins carry under SSAO?
- Does the glow logic read as one idea, rune → seams → key?

If any answer is no, say so. A benchmark that reports a golem it did not build is
worth nothing.

- [ ] **Step 7: Commit**

```bash
git add evals/golem_run_2/
git commit -m "chore(golem): renders, and the sheet that cost one call"
```

---

### Task 11: The report

**Files:**
- Create: `docs/superpowers/specs/2026-08-15-golem-tool-gaps-ranked.md`
- Modify: `evals/golem_run_2/tool_ledger.md`

**Interfaces:**
- Consumes: the completed ledger, every measurement recorded along the way.
- Produces: the #601 deliverable.

- [ ] **Step 1: Close the ledger with the utilisation totals**

Total build steps, how many went through tools, how many escaped to
`execute_python`, and a one-line reason per escape. Measurement calls are excluded
and that exclusion is stated.

- [ ] **Step 2: Answer the five claims explicitly**

One short section each, with the measured evidence:
1. `assemble` against a real chunk breakdown — did the flat parts-list-with-a-chunk-label shape fit how a figure decomposes?
2. `assign_pbr` with a three-map atlas authored for a building, used on a creature.
3. The `environment` dome on a matte-clay body with emissive seams.
4. `render_sheet` at 29 subjects, against the kit sheet's 41 round-trips.
5. `maya_array` mirror for limb pairs — 11 calls, plus whatever renaming and pivot
   replacement cost.

- [ ] **Step 3: Write the ranked gaps**

Follow the structure of `docs/superpowers/specs/2026-08-15-tool-gaps-ranked.md`:
tiers by cost-versus-payback, each item stating the price of building it and the
benefit measured in this run, plus an explicit "NOT gaps — do not build these"
section. Every item must cite evidence from this run.

#603 is already built, so it appears as a resolved item with its measured payback —
what 29 pivots would have cost as escapes versus what they cost in the map.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-08-15-golem-tool-gaps-ranked.md evals/golem_run_2/tool_ledger.md
git commit -m "docs(golem): what the toolset fought, ranked by what fixing it is worth"
```

- [ ] **Step 5: Close the tickets**

One `update_issue` on #601 carrying the notes (files, commits, measured results,
utilisation totals) and status Resolved.

One `update_issue` on #603 carrying the per-chunk-map deviation from the filed
design, the live gate result, and status Resolved.

Leave #602 (skeletal rigging) as New, and add one line to it recording whether the
chunk-hierarchy workaround actually held — that is the question it was parked on.

---

## Self-Review

**Spec coverage.** Proportions → Task 4. Joint treatment: gaskets → Task 4, four
sockets → Task 6. Momentum-by-proportion → Task 5 (taper places the mass). Chunk
manifest → Tasks 4 and 7. Rig hierarchy and pivots → Tasks 4, 7, 8. Materials and
per-chunk glow → Task 9. Presentation → Task 10. Tooling holes → Tasks 1–3 (#603),
#602 noted in Task 11. Benchmark method and instrumentation → the ledger, Tasks 4–11.
Hazards → Task 6's #579 warning, Task 3's handshake, the port constraint in Global
Constraints. Deliverables → Tasks 10 and 11.

**Gap found and closed:** the design's build order lists the rune etch at step 6 and
mirroring at 7; the pelvis takes BOTH hip sockets and cannot be mirrored, so Task 6
Step 3 cuts the right hip explicitly.

**Type consistency:** `pivot` (singular, vec3) on `transform` throughout;
`pivots` (plural, chunk→vec3 map) on `assemble` throughout. `TransformedObject.pivot`
and `AssembledObject.pivot` are both `Optional[List[float]]`.
