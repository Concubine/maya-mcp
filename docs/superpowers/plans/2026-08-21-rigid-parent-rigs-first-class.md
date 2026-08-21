# Rigid-Parent Rigs Are First-Class — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the rigging/animation surface treat a rigid-parent rig — meshes parented under joints with NO skinCluster — as a first-class citizen, instead of silently reporting zeros, refusing to render it, dropping its joint limits, and mis-building its skeleton.

**Architecture:** Four independent handler fixes, one per ticket, sharing one root cause: every tool in the animation surface was written against SKINNED rigs, where motion means deformation and hierarchy means mesh-under-mesh. The #713 golem proved a second legal shape (joints as rigid parents; two readings of one file), and each fix teaches one tool to see it. Pure-math changes go in the `*math` modules with plain-Python tests; Maya-touching changes get mayapy tests where a fixture exists and unit tests with a fake `cmds` otherwise.

**Tech Stack:** Python 3, `maya.cmds` inside the plugin, pytest, the repo's fake-cmds test pattern (see `tests/test_clip.py`), `uv run` for everything.

## Global Constraints

- **Report measured, never echoed (#636).** A structural zero is an echo. Any number a tool returns must come from reading the scene after the change.
- **Silence is never an answer.** Warnings carry numbers and names, never bare adjectives.
- **A refusal beats a silent drop.** Design intent that cannot land must raise, not warn-and-continue.
- **No behaviour change for skinned rigs.** Every fix here is additive: existing skinned-rig tests must pass untouched. If one changes, that is a regression, not an update.
- Every task ends with `uv run pytest tests/ --junitxml=<tmp>.xml -q` green (the pytest summary line is lost to stdout buffering on this machine — read the junit XML).
- Commit per task, message form `fix(#NNN): <what>`.

---

### Task 1: #721 — `author_clip` accepts `timeout_s`

The tool's own timeout error tells the caller to pass a larger `timeout_s`, and no schema offers one. This is the #640 fix applied to the clip tools.

**Files:**
- Modify: `src/maya_mcp/server.py` (the `maya_author_clip` tool, ~line 2295; `BOOL_TIMEOUT_S` is at ~line 104)
- Test: `tests/test_server_tools.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `maya_author_clip(..., timeout_s: int = 120)` clamped to `MAX_RENDER_TIMEOUT_S` semantics — the dispatcher already clamps at `MAX_TIMEOUT_S`.

- [ ] **Step 1: Write the failing test**

In `tests/test_server_tools.py`, beside the existing tool-schema tests:

```python
def test_author_clip_exposes_timeout_s():
    """#721: the timeout error tells callers to raise timeout_s; the schema
    must offer one."""
    tool = _tool_by_name("maya_author_clip")
    props = tool.parameters["properties"]
    assert "timeout_s" in props, sorted(props)
    assert props["timeout_s"]["default"] == 120
```

If `_tool_by_name` does not exist in that module, use whatever helper the neighbouring tests use to reach a tool's schema — copy their idiom exactly rather than inventing one.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_server_tools.py::test_author_clip_exposes_timeout_s -q`
Expected: FAIL with `KeyError`/`AssertionError` naming the absent `timeout_s`.

- [ ] **Step 3: Add the parameter**

In `src/maya_mcp/server.py`, in `maya_author_clip`'s signature after `loop`:

```python
        timeout_s: Annotated[
            int,
            Field(ge=1, le=1800, description=(
                "Seconds before the call times out. Raise it for a long "
                "clip on a heavy scene - and note that an open Arnold "
                "RenderView (IPR) re-renders on every scene mutation, "
                "which can stall keyframing for minutes (maya-mcp #721)."
            )),
        ] = 120,
```

and change the request call's last argument from `timeout_s=BOOL_TIMEOUT_S` to `timeout_s=float(timeout_s)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_server_tools.py -q`
Expected: PASS, and every other tool-schema test still green.

- [ ] **Step 5: Commit**

```bash
git add src/maya_mcp/server.py tests/test_server_tools.py
git commit -m "fix(#721): author_clip takes timeout_s so its own timeout advice is followable"
```

---

### Task 2: #720 — rigid-parented meshes are visible to displacement measurement

`rigging._bound_meshes` answers "which meshes does this skeleton deform" by looking for skinClusters. In a rigid-parent rig the answer is "the mesh descendants of these joints", so `author_clip`/`pose_skeleton` measure nothing and report `max_displacement: 0` — an echo, forbidden by #636.

**Files:**
- Modify: `maya_plugin/handlers/rigging.py` (`_bound_meshes`, line 253)
- Test: `tests/test_rigging.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `rigging._bound_meshes(cmds, joint_set)` now returns skinned meshes PLUS mesh-bearing transforms parented under any joint in `joint_set`, de-duplicated, long names, stable order. Task 3 does not use it; `clip.author_clip`, `clip.preview_clip`, `rigging.pose_skeleton` and `rigging.reset_pose` all consume it unchanged.

- [ ] **Step 1: Read the current implementation**

Read `maya_plugin/handlers/rigging.py:253-267` and the fake-`cmds` pattern at the top of `tests/test_rigging.py`. The new behaviour must not change what a skinned rig returns.

- [ ] **Step 2: Write the failing test**

In `tests/test_rigging.py`, using that module's existing fake-cmds idiom:

```python
def test_bound_meshes_finds_rigidly_parented_children():
    """#720: a chunk parented under a joint moves with it. No skinCluster
    exists, and reporting zero displacement for it is an echo (#636)."""
    cmds = FakeCmds(
        # |root|jnt_torso with a mesh transform parented directly under it
        relatives={"|root|jnt_torso": ["|root|jnt_torso|torso_plates"]},
        meshes={"|root|jnt_torso|torso_plates": ["|root|jnt_torso|torso_platesShape"]},
        skin_clusters={},
    )
    found = rigging._bound_meshes(cmds, {"|root|jnt_torso"})
    assert found == ["|root|jnt_torso|torso_plates"]


def test_bound_meshes_still_finds_skinned_meshes_only_once():
    """A skinned mesh that is ALSO a joint descendant must appear once."""
    cmds = FakeCmds(
        relatives={"|root|jnt_a": ["|root|jnt_a|body"]},
        meshes={"|root|jnt_a|body": ["|root|jnt_a|bodyShape"]},
        skin_clusters={"|root|jnt_a|bodyShape": "skinCluster1"},
        skin_influences={"skinCluster1": ["|root|jnt_a"]},
    )
    assert rigging._bound_meshes(cmds, {"|root|jnt_a"}) == ["|root|jnt_a|body"]
```

Adjust the fake's constructor keywords to match the ones `tests/test_rigging.py` already uses — do not add new fake capabilities if the existing fake can express this.

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_rigging.py -k bound_meshes -q`
Expected: the first test FAILS (returns `[]`); the second may already pass.

- [ ] **Step 4: Extend `_bound_meshes`**

Keep the existing skin-based discovery, then add descendant discovery. Preserve order (skinned first, then descendants) and de-duplicate:

```python
def _bound_meshes(cmds, joint_set) -> List[str]:
    """Meshes this skeleton MOVES - by deformation or by rigid parenting.

    Two rig shapes are legal here. A skinned mesh is found through its
    skinCluster's influences. A rigid-parent rig (maya-mcp #713: chunks
    parented under joints, no deformer) is found structurally: a mesh
    transform under a joint moves with that joint, and reporting zero
    displacement for it would be an echo, not a measurement (#636).
    """
    found: List[str] = []

    # (existing skinCluster-based discovery, unchanged, appending to `found`)

    for joint in sorted(joint_set):
        for node in cmds.listRelatives(joint, allDescendents=True,
                                       fullPath=True, type="transform") or []:
            if not cmds.listRelatives(node, shapes=True, fullPath=True,
                                      type="mesh"):
                continue
            if node not in found:
                found.append(node)
    return found
```

Replace the comment line with the module's real existing skin discovery code — do not delete it.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_rigging.py tests/test_clip.py -q`
Expected: PASS, including every pre-existing skinned-rig test.

- [ ] **Step 6: Commit**

```bash
git add maya_plugin/handlers/rigging.py tests/test_rigging.py
git commit -m "fix(#720): _bound_meshes sees rigidly-parented chunks, so displacement is measured not echoed"
```

---

### Task 3: #720 (part 2) — `preview_clip` renders a rigid-parent rig

With Task 2 landed, `preview_clip`'s refusal at `clip.py:484-488` ("no skinned mesh is bound to this skeleton — bare joints render nothing") stops firing for rigid-parent rigs automatically, because `meshes` is no longer empty. This task proves that and fixes the now-wrong hint.

**Files:**
- Modify: `maya_plugin/handlers/clip.py:484-488` (the refusal) and `clip.py:239-242` (the same-shaped warning in `author_clip`)
- Test: `tests/test_clip.py`

**Interfaces:**
- Consumes: Task 2's `_bound_meshes`.
- Produces: no signature change. `preview_clip` refuses only when the skeleton moves NO mesh at all, by either mechanism.

- [ ] **Step 1: Write the failing test**

```python
def test_preview_clip_accepts_a_rigidly_parented_rig(monkeypatch):
    """#720: chunks under joints render fine; only a skeleton that moves
    nothing at all has nothing to preview."""
    monkeypatch.setattr(clip.rigging, "_bound_meshes",
                        lambda cmds, joints: ["|root|jnt_a|chunk"])
    # ... assemble the module's existing preview_clip fixture, then:
    result = clip.preview_clip({"root": "|root", "name": "idle"})
    assert result["clip"] == "idle"
```

Follow `tests/test_clip.py`'s existing `preview_clip` test setup verbatim for the fake cmds, clip metadata and the `render._run_shots` monkeypatch; only the `_bound_meshes` answer differs.

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `uv run pytest tests/test_clip.py -k rigidly_parented -q`
Expected: PASS once Task 2 is in (the refusal no longer triggers). If it FAILS, the refusal has a second cause — read the traceback and fix that before continuing.

- [ ] **Step 3: Correct the two now-wrong messages**

In `clip.py`, the `preview_clip` refusal becomes:

```python
    if not meshes:
        raise HandlerError(
            "this skeleton moves no mesh - neither a skinned bind nor a "
            "mesh parented under one of its joints; bare joints render "
            "nothing",
            hint="bind_skin for a deforming rig, or parent the chunks "
                 "under their joints for a rigid-body rig")
```

and `author_clip`'s warning becomes:

```python
    if not meshes:
        warnings.append(
            "this skeleton moves no mesh (no skinned bind, no mesh "
            "parented under its joints) - the clip moves bare joints "
            "only; displacement below is measured against nothing")
```

- [ ] **Step 4: Run the full clip suite**

Run: `uv run pytest tests/test_clip.py tests/test_rigging.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/clip.py tests/test_clip.py
git commit -m "fix(#720): preview_clip renders rigid-parent rigs; refusals name both rig shapes"
```

---

### Task 4: #722 — `author_physics` reads ancestry through joints, and refuses undeliverable overrides

Two defects, one task, because the second is what makes the first safe. `physics._parent_of` walks up looking for another chunk; in a rigid-parent rig the walk passes through `jnt_*` joints and finds nothing, so every body comes back `parent: null` — and every `hinge_range_deg` override is then silently dropped, yielding a complete-looking manifest with no joint limits.

**Files:**
- Modify: `maya_plugin/handlers/physics.py` (`_parent_of` at line 141; `author_physics`'s override loop at lines 310-325)
- Test: `tests/test_physics.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `_parent_of` unchanged in signature. `author_physics` raises `HandlerError` when an override supplies joint limits for a chunk that resolves parentless.

- [ ] **Step 1: Write the failing tests**

```python
def test_parent_of_walks_through_joints():
    """#722: a rigid-parent rig interposes joints between chunks. A joint is
    a link in the chain, not the end of it."""
    cmds = FakeCmds(parents={
        "|golem|jnt_pelvis|pelvis_plates": "|golem|jnt_pelvis",
        "|golem|jnt_pelvis": "|golem",
        "|golem|jnt_pelvis|jnt_torso|torso_plates": "|golem|jnt_pelvis|jnt_torso",
        "|golem|jnt_pelvis|jnt_torso": "|golem|jnt_pelvis",
    })
    chunk_set = {"|golem|jnt_pelvis|pelvis_plates",
                 "|golem|jnt_pelvis|jnt_torso|torso_plates"}
    assert physics._parent_of(
        cmds, "|golem|jnt_pelvis|jnt_torso|torso_plates", chunk_set
    ) == "|golem|jnt_pelvis|pelvis_plates"


def test_hinge_override_on_a_parentless_chunk_refuses():
    """#722: a limit that cannot attach to a joint must not vanish - the
    manifest would look complete and carry no limits at all."""
    with pytest.raises(HandlerError) as excinfo:
        physics.author_physics({
            "chunks": ["|a", "|b"],
            "overrides": {"b": {"hinge_range_deg": [0, 90]}},
        })
    assert "parentless" in str(excinfo.value)
```

Build the fakes with `tests/test_physics.py`'s existing helpers; the second test needs whatever mesh/volume stubbing that module already uses for `author_physics`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_physics.py -k "walks_through_joints or parentless" -q`
Expected: both FAIL — the first returns `None`, the second does not raise.

- [ ] **Step 3: Teach `_parent_of` that joints are links**

```python
def _parent_of(cmds, chunk: str, chunk_set) -> Optional[str]:
    """Nearest chunk ancestor. Plain groups AND JOINTS between a chunk and
    its parent chunk are skipped, not parents.

    Joints earn the same treatment groups always had: a rigid-parent rig
    (maya-mcp #713) hangs each chunk under its joint, so chunk-to-chunk
    ancestry runs THROUGH the skeleton. Reading a joint as the end of the
    walk reported every body parentless and silently dropped every joint
    limit with it (#722).
    """
    node = chunk
    while True:
        parents = cmds.listRelatives(node, parent=True, fullPath=True)
        if not parents:
            return None
        node = parents[0]
        if node in chunk_set:
            return node
```

The body is unchanged — the walk already skips anything not in `chunk_set`, joints included. **Verify this by running the first test before editing anything else:** if it now passes with only the docstring changed, the real defect was elsewhere (likely `_collect_chunks` excluding joint-parented transforms, `physics.py:86`), and that is what to fix. Read the traceback, then fix the actual cause.

- [ ] **Step 4: Make an undeliverable override refuse**

In `author_physics`, where `parent is None` currently just appends to `parentless` (line 321):

```python
        if parent is None:
            if any(k in spec for k in ("hinge_axis", "hinge_range_deg",
                                       "twist_range_deg")):
                raise HandlerError(
                    "override for %r supplies joint limits, but the chunk "
                    "resolves parentless - a limit with no joint to attach "
                    "to would be dropped, and the manifest would look "
                    "complete with no limits in it (#722)" % short,
                    hint="pass overrides={%r: {'parent': '<chunk>'}} so the "
                         "body has a joint, or drop the limit keys" % short)
            parentless.append(chunk)
```

`spec` is the per-chunk override dict already in scope in that loop — confirm the local name while editing.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_physics.py tests/test_physmath.py -q`
Expected: PASS, with every existing chunk-hierarchy test untouched.

- [ ] **Step 6: Commit**

```bash
git add maya_plugin/handlers/physics.py tests/test_physics.py
git commit -m "fix(#722): chunk ancestry walks through joints; an undeliverable limit override refuses"
```

---

### Task 5: #719 — `create_skeleton` can build world-aligned joints at exact positions

`orient: [0,0,0]` currently makes Maya lay each bone at bone-length along +X, silently discarding the caller's `position`. Omitting `orient` keeps positions but auto-orients local X down the bone. Neither builds the world-aligned sagittal rig a rigid-parent creature wants, so the #713 builder escaped to python.

**Files:**
- Modify: `maya_plugin/handlers/rigging.py` (`create_skeleton`, lines 63-81)
- Test: `tests/test_rigging.py`, and `tests/test_handlers_mayapy.py` if that module has a create_skeleton battery

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `create_skeleton` keeps every joint at its requested world position REGARDLESS of `orient`. Reported `position` per joint must equal the requested one to 1e-6.

- [ ] **Step 1: Write the failing test**

```python
def test_explicit_orient_keeps_the_requested_positions():
    """#719: orient must not cost the caller their positions. Maya's
    joint(orientJoint=...) edit moves children; explicit orients are applied
    AFTER positions are restored."""
    result = rigging.create_skeleton({"joints": [
        {"name": "jnt_root", "position": [0, 0, 0]},
        {"name": "jnt_torso", "position": [0, 2.05, 0], "parent": "jnt_root",
         "orient": [0, 0, 0]},
    ]})
    torso = [j for j in result["joints"] if j["name"].endswith("jnt_torso")][0]
    assert torso["position"] == pytest.approx([0, 2.05, 0], abs=1e-6)
    assert torso["orient"] == pytest.approx([0, 0, 0], abs=1e-6)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_rigging.py -k explicit_orient -q`
Expected: FAIL — the measured position is the bone-length-along-X placement, not `[0, 2.05, 0]`.

If `create_skeleton` cannot run under the fake cmds in that module, write this as a mayapy test in `tests/test_handlers_mayapy.py` instead, following that file's existing skeleton tests, and run it with the mayapy invocation that module documents.

- [ ] **Step 3: Re-assert positions after orienting**

In `create_skeleton`, after the explicit-orient loop (line 81), add:

```python
    # Setting jointOrient does not move a joint, but the orientJoint edit
    # above DOES move children, and Maya's own +X-down-the-bone placement
    # discards the caller's position when an explicit orient is given
    # (#719). The requested world positions are the contract, so they are
    # re-asserted here, parents first (a parent move carries its children).
    for joint in resolved:
        node = long_names[joint["name"]]
        cmds.xform(node, worldSpace=True, translation=joint["position"])
```

`resolved` is already in topological order (parents before children — `rigmath.resolve_joints` guarantees it), which is why this loop is safe in place.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_rigging.py tests/test_rigmath.py -q`
Expected: PASS. Every existing create_skeleton test — including the auto-orient ones — must still pass; if an auto-orient test now fails, the re-assertion is fighting a deliberate behaviour, so read that test before changing it.

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/rigging.py tests/test_rigging.py
git commit -m "fix(#719): create_skeleton keeps requested positions when an explicit orient is given"
```

---

### Task 6: Live gate — the rigid-parent rig, measured end to end

Headless tests can pass while the real behaviour is wrong (`maya-mcp-live-gate-is-the-gate`). This task proves all four fixes on a live disposable Maya against a rig of the #713 shape.

**Files:**
- Create: `evals/rigid_rig_live.py`
- Reference: `evals/clip_live.py` (the closest existing live gate — copy its structure, pid verification, and `--junitxml`-free measured-numbers reporting)

**Interfaces:**
- Consumes: Tasks 1-5.
- Produces: a runnable gate printing measured numbers and a PASS/FAIL count, plus `evals/rigid_rig_live/baseline.json`.

- [ ] **Step 1: Read the existing gate**

Read `evals/clip_live.py` end to end. Copy its port/pid discipline and its refusal to trust a stale plugin (`ping`'s `restart_required`).

- [ ] **Step 2: Write the gate**

It must build, in a scratch scene: a 3-joint world-aligned skeleton via `create_skeleton` with explicit `orient: [0,0,0]`, a cube parented under each joint (no `bind_skin` anywhere), then assert, each as one measured check:

1. every joint's world position equals the requested one within 1e-6 (#719)
2. `author_clip` on that skeleton reports a NON-ZERO `max_displacement` in `per_key` (#720/#636)
3. `preview_clip` returns frames rather than refusing (#720)
4. `author_physics` on the three chunks reports each one's parent as the chunk above it, not `null` (#722)
5. `author_physics` with a `hinge_range_deg` override on a genuinely parentless chunk RAISES (#722)
6. `export_fbx(include_animation=True)` passes its own gate, and the bytes carry the named take (reuse `evals/fbx_probe.py`)

- [ ] **Step 3: Run it against the disposable Maya**

Run: `MAYA_MCP_PORT=9879 uv run python evals/rigid_rig_live.py`
Expected: every check PASS, with the measured number printed beside each. A zero displacement in check 2 means Task 2 did not take.

- [ ] **Step 4: Commit gate and baseline**

```bash
git add evals/rigid_rig_live.py evals/rigid_rig_live/baseline.json
git commit -m "test(#713): live gate for rigid-parent rigs across the animation surface"
```

- [ ] **Step 5: Close the tickets**

Update #719, #720, #721, #722 with the measured gate numbers and set each to Resolved. One `update_issue` per ticket carrying both notes and status.

---

## Not in this plan

Two tickets from the same run are deliberately a SEPARATE round — they are export-honesty and capability work, not the rigid-parent theme, and each is large enough to deserve its own plan:

- **#714** — FBX export silently drops procedural texture maps (bake via `convertSolidTx`, or report `dropped_maps` with names). Ties to the roadmap's Tier-0 baking item.
- **#718** — multiple named takes in one FBX. The most-wanted capability of the #713 run; needs a design decision about how several clips coexist on one skeleton before any code.
