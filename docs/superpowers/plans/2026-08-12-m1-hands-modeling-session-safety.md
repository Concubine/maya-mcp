# M1 — Hands: Structured Modeling Tools + Session Safety — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** All design-doc §5.3 structured modeling tools + §5.6 session safety for maya-mcp, hardened against the five golem-run pain points in redmine #577 (boolean SG corruption, etch-text placement, displace_noise, viewport/camera discipline, live-user awareness).

**Architecture:** Same three-layer shape as M0 — pure/testable math in `maya_plugin/handlers/*` modules with a lazy `_cmds()` import, `HandlerError(message, hint)` for anticipated failures, handlers registered in `maya_mcp_plugin._build_handlers()`, thin validated `@mcp.tool` wrappers in `src/maya_mcp/server.py`, Pydantic result models in `src/maya_mcp/schemas.py`. Every handler call is one undo chunk via the dispatcher; undo/redo/scene-load handlers opt OUT of chunking via a new `no_undo_chunk` attribute.

**Tech Stack:** Python 3.10+ (plugin side runs in Maya 2027's embedded Python), MCP Python SDK v2 (`mcp.server.MCPServer`, snake_case `ToolAnnotations` — FastMCP v1 is gone), Pydantic v2, `maya.api.OpenMaya` (API 2.0) for mesh math, pytest.

**Ticket:** redmine #577 (project 35, maya-mcp). Repo: `D:\devel\maya-mcp`. Work on branch `feature/m1-hands` (create via superpowers:using-git-worktrees at execution start).

## Global Constraints

- Tool names prefixed `maya_`; responses that name scene nodes return **canonical long names** (`|group|node`).
- Every error carries a `hint` saying what to try next. Raise `HandlerError` for anticipated conditions; let unexpected exceptions propagate (dispatcher attaches the full traceback).
- Text responses ≤ 4 KB; nothing in M1 returns unbounded data.
- Requested names that collide get deterministic suffixes (`golem_arm` → `golem_arm_001`); the assigned name is always returned.
- Tools address objects only by name, never by selection state; any selection a handler makes must be cleared/restored before returning.
- Destructive ops (`boolean_op`, `etch_text`, `remesh_retopo`, `execute_python(risky=True)`) auto-checkpoint first via `session.auto_checkpoint()`.
- MCP SDK v2 API only: `from mcp.server import MCPServer`, `from mcp.types import ToolAnnotations` with `read_only_hint`/`destructive_hint`/`idempotent_hint` (snake_case).
- Headless suite must pass with no Maya installed: `uv run pytest` (from repo root). Real-geometry suite: `E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q` (skips cleanly when maya is not importable).
- `evals/isolate_regression.py` must stay green after any change to `maya_plugin/handlers/capture.py` (needs live Maya editor + plugin on TCP 9877).
- Handler test convention (see `tests/test_scene.py`): a `FakeCmds` class implementing exactly the cmds surface the handler may touch, injected by monkeypatching the module's `_cmds`; anything else raises, keeping the handler honest about its API footprint.
- Commit after every task with a `feat(m1):` / `test(m1):` / `refactor(m1):` prefix.

## File Map (what this plan creates/modifies)

| File | Role |
|---|---|
| `maya_plugin/dispatcher.py` (modify) | `no_undo_chunk` opt-out for undo/redo/scene-load handlers |
| `maya_plugin/handlers/naming.py` (new) | `unique_name`, `require_object`, `require_mesh` |
| `maya_plugin/handlers/ledger.py` (new) | transform ledger — live-user-move detection (#577 req 4c) |
| `maya_plugin/handlers/session.py` (new) | checkpoint/restore/undo/redo/new/open/save + `auto_checkpoint` |
| `maya_plugin/handlers/code_exec.py` (modify) | `risky=True` delegates to `session.auto_checkpoint` |
| `maya_plugin/handlers/meshcheck.py` (new) | OpenMaya mesh stats + shading-group verify/repair (#577 req 1) |
| `maya_plugin/handlers/modeling.py` (new) | primitives, duplicate/transform/group/parent/rename/delete, boolean_op, mesh_cleanup, remesh_retopo |
| `maya_plugin/handlers/etch.py` (new) | `etch_text` glyph-carve pipeline + pure placement math (#577 req 2) |
| `maya_plugin/handlers/sculpt_math.py` (new) | pure value-noise/fbm/falloff math (#577 req 3) |
| `maya_plugin/handlers/sculpt.py` (new) | `sculpt_ops` tagged union + `deform` |
| `maya_plugin/handlers/viewport.py` (new) | `set_viewport`, `set_camera` (#577 req 4a/4b) |
| `maya_plugin/handlers/capture.py` (modify) | hide light/camera/locator/texture-placement icons during capture; camera name in results |
| `maya_plugin/maya_mcp_plugin.py` (modify) | register all new handlers |
| `src/maya_mcp/server.py` (modify) | ~23 new `@mcp.tool` wrappers (design doc: all tools live here) |
| `src/maya_mcp/schemas.py` (modify) | result models for the new tools |
| `tests/test_naming.py`, `tests/test_ledger.py`, `tests/test_session.py`, `tests/test_modeling.py`, `tests/test_sculpt_math.py`, `tests/test_etch_math.py`, `tests/test_viewport.py` (new) | headless suites |
| `tests/test_dispatcher.py`, `tests/test_capture.py`, `tests/test_server_tools.py` (modify) | extend for opt-out / icon-hiding / new tools |
| `tests/test_handlers_mayapy.py` (modify) | real-geometry tests + the M1 acceptance gate |

---

### Task 1: Dispatcher undo-chunk opt-out

Undo/redo and scene-load handlers must NOT run inside an undo chunk: `cmds.undo()` inside an open chunk undoes the wrong thing, and `file(open)` invalidates the queue mid-chunk.

**Files:**
- Modify: `maya_plugin/dispatcher.py:193-205` (`_run_job`)
- Test: `tests/test_dispatcher.py` (append)

**Interfaces:**
- Produces: convention — setting `handler_fn.no_undo_chunk = True` on any registered handler makes the dispatcher skip `undo_open`/`undo_close` for that handler. Task 3 uses this for `undo`, `redo`, `restore_checkpoint`, `new_scene`, `open_scene`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_dispatcher.py`, reusing its existing pattern for building a dispatcher with recording undo hooks):

```python
def test_no_undo_chunk_handler_skips_hooks():
    calls = []

    def normal(params):
        return {"ok": 1}

    def exempt(params):
        return {"ok": 2}

    exempt.no_undo_chunk = True

    d = Dispatcher(
        {"normal": normal, "exempt": exempt},
        undo_open=lambda: calls.append("open"),
        undo_close=lambda: calls.append("close"),
    )
    try:
        d.handle_request({"v": 1, "id": "a", "cmd": "normal", "params": {}})
        assert calls == ["open", "close"]
        d.handle_request({"v": 1, "id": "b", "cmd": "exempt", "params": {}})
        assert calls == ["open", "close"]  # unchanged: hooks skipped
    finally:
        d.shutdown()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_dispatcher.py::test_no_undo_chunk_handler_skips_hooks -q`
Expected: FAIL — calls == `["open", "close", "open", "close"]`.

- [ ] **Step 3: Implement** — in `_run_job`, gate the hooks:

```python
    def _run_job(
        self, req_id: str, handler: Callable, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        start = time.monotonic()
        use_chunk = not getattr(handler, "no_undo_chunk", False)

        def run_on_main() -> Dict[str, Any]:
            if use_chunk and self._undo_open is not None:
                self._undo_open()
            try:
                return handler(params)
            finally:
                if use_chunk and self._undo_close is not None:
                    self._undo_close()
```

(rest of `_run_job` unchanged)

- [ ] **Step 4: Run the full dispatcher suite**

Run: `uv run pytest tests/test_dispatcher.py -q` — Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/dispatcher.py tests/test_dispatcher.py
git commit -m "feat(m1): dispatcher no_undo_chunk opt-out for undo/scene-load handlers"
```

---

### Task 2: Naming + transform-ledger helpers

**Files:**
- Create: `maya_plugin/handlers/naming.py`
- Create: `maya_plugin/handlers/ledger.py`
- Test: `tests/test_naming.py`, `tests/test_ledger.py`

**Interfaces:**
- Produces: `naming.unique_name(cmds, requested) -> str`; `naming.require_object(cmds, name) -> str` (canonical long name or HandlerError); `naming.require_mesh(cmds, name) -> tuple[str, str]` (transform long name, shape long name).
- Produces: `ledger.record(cmds, name)` — store the tool-written world transform; `ledger.check(cmds, name) -> str | None` — warning string if the live user moved the object since the last tool write (#577 req 4c); `ledger.forget(name)`; `ledger.clear()`.
- Consumes: `HandlerError` from `maya_plugin.dispatcher`.

- [ ] **Step 1: Write failing tests** — `tests/test_naming.py`:

```python
import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import naming


class FakeCmds:
    def __init__(self, objects=None, shapes=None):
        self.objects = set(objects or [])
        self.shapes = shapes or {}  # long transform -> (shape_long, node_type)

    def objExists(self, name):
        return any(o == name or o.split("|")[-1] == name for o in self.objects)

    def ls(self, name, long=False):
        assert long
        return [o for o in self.objects if o == name or o.split("|")[-1] == name]

    def listRelatives(self, node, shapes=False, fullPath=False, noIntermediate=False):
        assert shapes and fullPath and noIntermediate
        entry = self.shapes.get(node)
        return [entry[0]] if entry else None

    def nodeType(self, node):
        for shape, ntype in self.shapes.values():
            if shape == node:
                return ntype
        raise AssertionError("unexpected nodeType call")


def test_unique_name_passthrough_when_free():
    assert naming.unique_name(FakeCmds(), "golem_arm") == "golem_arm"


def test_unique_name_deterministic_suffix():
    fake = FakeCmds(objects={"golem_arm", "golem_arm_001"})
    assert naming.unique_name(fake, "golem_arm") == "golem_arm_002"


def test_require_object_missing_has_hint():
    with pytest.raises(HandlerError) as exc:
        naming.require_object(FakeCmds(), "|nope")
    assert "maya_get_scene_graph" in exc.value.hint


def test_require_object_ambiguous_short_name():
    fake = FakeCmds(objects={"|a|torso", "|b|torso"})
    with pytest.raises(HandlerError) as exc:
        naming.require_object(fake, "torso")
    assert "ambiguous" in str(exc.value)


def test_require_mesh_rejects_non_mesh():
    fake = FakeCmds(
        objects={"|keyLight"},
        shapes={"|keyLight": ("|keyLight|keyLightShape", "pointLight")},
    )
    with pytest.raises(HandlerError) as exc:
        naming.require_mesh(fake, "|keyLight")
    assert "not a polygon mesh" in str(exc.value)


def test_require_mesh_returns_long_names():
    fake = FakeCmds(
        objects={"|golem|torso"},
        shapes={"|golem|torso": ("|golem|torso|torsoShape", "mesh")},
    )
    assert naming.require_mesh(fake, "|golem|torso") == (
        "|golem|torso",
        "|golem|torso|torsoShape",
    )
```

`tests/test_ledger.py`:

```python
from maya_plugin.handlers import ledger


class FakeCmds:
    def __init__(self):
        self.xforms = {}  # name -> (t, r, s)

    def xform(self, name, query=True, worldSpace=True, translation=False,
              rotation=False, scale=False):
        t, r, s = self.xforms[name]
        if translation:
            return list(t)
        if rotation:
            return list(r)
        return list(s)


def test_check_without_record_is_none():
    ledger.clear()
    fake = FakeCmds()
    fake.xforms["|a"] = ((0, 0, 0), (0, 0, 0), (1, 1, 1))
    assert ledger.check(fake, "|a") is None


def test_unchanged_transform_no_warning():
    ledger.clear()
    fake = FakeCmds()
    fake.xforms["|a"] = ((1, 2, 3), (0, 0, 0), (1, 1, 1))
    ledger.record(fake, "|a")
    assert ledger.check(fake, "|a") is None


def test_user_moved_object_warns_with_values():
    ledger.clear()
    fake = FakeCmds()
    fake.xforms["|a"] = ((1, 2, 3), (0, 0, 0), (1, 1, 1))
    ledger.record(fake, "|a")
    fake.xforms["|a"] = ((1, 2, 9), (0, 45, 0), (1, 1, 1))  # live user tumbled it
    warning = ledger.check(fake, "|a")
    assert warning is not None and "outside" in warning and "|a" in warning
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_naming.py tests/test_ledger.py -q` → import errors (modules do not exist).

- [ ] **Step 3: Implement `maya_plugin/handlers/naming.py`:**

```python
"""Name helpers: collision-free naming and object resolution with hints."""

from __future__ import annotations

from typing import Tuple

from ..dispatcher import HandlerError

_MAX_SUFFIX = 999


def unique_name(cmds, requested: str) -> str:
    """The requested name, or the first free deterministic _NNN suffix."""
    if not cmds.objExists(requested):
        return requested
    for i in range(1, _MAX_SUFFIX + 1):
        candidate = "%s_%03d" % (requested, i)
        if not cmds.objExists(candidate):
            return candidate
    raise HandlerError(
        "no free name for %r after %d suffixes" % (requested, _MAX_SUFFIX),
        hint="choose a different base name",
    )


def require_object(cmds, name: str) -> str:
    """Resolve `name` to exactly one canonical long name."""
    matches = cmds.ls(name, long=True) or []
    if not matches:
        raise HandlerError(
            "object %r not found" % name,
            hint="call maya_get_scene_graph to list objects; use canonical long names",
        )
    if len(matches) > 1:
        raise HandlerError(
            "name %r is ambiguous (%d matches)" % (name, len(matches)),
            hint="use the canonical long name, e.g. %s" % matches[0],
        )
    return matches[0]


def require_mesh(cmds, name: str) -> Tuple[str, str]:
    """Resolve to (transform long name, mesh shape long name) or fail with a hint."""
    transform = require_object(cmds, name)
    shapes = (
        cmds.listRelatives(transform, shapes=True, fullPath=True, noIntermediate=True)
        or []
    )
    if not shapes or cmds.nodeType(shapes[0]) != "mesh":
        raise HandlerError(
            "%s is not a polygon mesh" % transform,
            hint="this tool needs a mesh; call maya_get_scene_graph with filter='mesh'",
        )
    return transform, shapes[0]
```

- [ ] **Step 4: Implement `maya_plugin/handlers/ledger.py`:**

```python
"""Transform ledger: detect live-user edits between tool calls (#577 req 4c).

The user tumbles the viewport and rotates objects mid-session. Tools that
write transforms record what they wrote; tools that later touch the same
object compare and surface a warning instead of silently assuming
script-only mutation. In-memory only — resets with the plugin/scene.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

_TOLERANCE = 1e-4

_written: Dict[str, Tuple[tuple, tuple, tuple]] = {}


def _read(cmds, name):
    t = tuple(cmds.xform(name, query=True, worldSpace=True, translation=True))
    r = tuple(cmds.xform(name, query=True, worldSpace=True, rotation=True))
    s = tuple(cmds.xform(name, query=True, worldSpace=True, scale=True))
    return t, r, s


def record(cmds, name: str) -> None:
    _written[name] = _read(cmds, name)


def check(cmds, name: str) -> Optional[str]:
    """Warning text if `name` moved since the last tool write; else None."""
    expected = _written.get(name)
    if expected is None:
        return None
    actual = _read(cmds, name)
    for exp_vec, act_vec in zip(expected, actual):
        if any(abs(e - a) > _TOLERANCE for e, a in zip(exp_vec, act_vec)):
            return (
                "%s was modified outside maya-mcp since the last tool write "
                "(expected t/r/s %s, found %s); proceeding from the current values"
                % (name, expected, actual)
            )
    return None


def forget(name: str) -> None:
    _written.pop(name, None)


def clear() -> None:
    _written.clear()
```

- [ ] **Step 5: Run tests** — `uv run pytest tests/test_naming.py tests/test_ledger.py -q` → all PASS.

- [ ] **Step 6: Commit**

```bash
git add maya_plugin/handlers/naming.py maya_plugin/handlers/ledger.py tests/test_naming.py tests/test_ledger.py
git commit -m "feat(m1): naming + transform-ledger helpers"
```

---

### Task 3: Session safety — checkpoints, undo/redo, scene ops (§5.6)

**Files:**
- Create: `maya_plugin/handlers/session.py`
- Modify: `maya_plugin/handlers/code_exec.py` (delete `_auto_checkpoint`, delegate to session)
- Modify: `maya_plugin/maya_mcp_plugin.py` (`_build_handlers`)
- Modify: `src/maya_mcp/server.py`, `src/maya_mcp/schemas.py`
- Test: `tests/test_session.py` (new), `tests/test_server_tools.py` (extend), `tests/test_handlers_mayapy.py` (extend)

**Interfaces:**
- Produces (plugin-internal): `session.auto_checkpoint(reason: str) -> str` — saves `<checkpoints>/NNN_auto_<reason>.ma`, returns the path. Called by `code_exec` (risky=True), `boolean_op` (Task 6), `etch_text` (Task 7), `remesh_retopo` (Task 9).
- Produces (handlers, registered under these command names): `checkpoint`, `restore_checkpoint`, `undo`, `redo`, `new_scene`, `open_scene`, `save_scene`. (`reset_namespace` already exists in code_exec — this task exposes it as an MCP tool.)
- Produces (MCP tools): `maya_checkpoint(label)`, `maya_restore_checkpoint(checkpoint_id)`, `maya_undo(steps)`, `maya_redo(steps)`, `maya_new_scene(confirm)`, `maya_open_scene(path, confirm)`, `maya_save_scene(path)`, `maya_reset_namespace()`.
- Checkpoint id format: filename stem `NNN_label` (e.g. `007_pre_rune`). Keep the newest 20 files; prune older by number.

Design decisions (documenting per design-doc §9 convention):
- `restore_checkpoint` takes an `auto_pre_restore` checkpoint of the current state first, then `file(open, force=True)` — restore must never be a one-way door. It also discards the undo queue (inherent to file open; say so in the tool description) and calls `ledger.clear()`.
- `open_scene`/`new_scene` refuse when the scene has unsaved changes unless `confirm=true` (small safety addition over the doc signature; the doc already demands confirm for new_scene).
- `undo`/`redo`/`restore_checkpoint`/`new_scene`/`open_scene` are marked `no_undo_chunk = True` (Task 1).

- [ ] **Step 1: Write failing headless tests** — `tests/test_session.py`. Follow the `test_scene.py` FakeCmds convention; monkeypatch `session._cmds`. Test list (write all of these, complete):

```python
"""session handler tests against a fake cmds — no Maya required."""

import os

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import session


class FakeCmds:
    def __init__(self, tmp_path, scene_name=""):
        self._tmp = str(tmp_path)
        self.scene_name = scene_name
        self.modified = False
        self.saved_to = []
        self.opened = []
        self.new_calls = 0
        self.undo_calls = 0
        self.redo_calls = 0
        self.undo_fail_after = None  # raise RuntimeError after N successful undos

    # session._cmds() surface
    def file(self, *args, **kw):
        if kw.get("query"):
            if kw.get("sceneName"):
                return self.scene_name
            if kw.get("modified"):
                return self.modified
            raise AssertionError("unexpected file query")
        if kw.get("new"):
            self.new_calls += 1
            return None
        if kw.get("exportAll") or kw.get("save"):
            self.saved_to.append(args[0] if args else self.scene_name)
            return None
        if kw.get("open"):
            self.opened.append(args[0])
            return None
        if kw.get("rename"):
            self.scene_name = args[0]
            return None
        raise AssertionError("unexpected file call %r %r" % (args, kw))

    def workspace(self, query=True, rootDirectory=True):
        return self._tmp

    def undo(self):
        if self.undo_fail_after is not None and self.undo_calls >= self.undo_fail_after:
            raise RuntimeError("nothing to undo")
        self.undo_calls += 1

    def redo(self):
        self.redo_calls += 1


@pytest.fixture
def fake(tmp_path, monkeypatch):
    fake = FakeCmds(tmp_path)
    monkeypatch.setattr(session, "_cmds", lambda: fake)
    return fake


def test_checkpoint_writes_numbered_file_and_returns_id(fake, tmp_path):
    result = session.checkpoint({"label": "Pre Rune!"})
    assert result["checkpoint_id"] == "001_pre_rune"  # sanitized label
    assert result["path"].endswith("001_pre_rune.ma")
    assert fake.saved_to == [result["path"]]


def test_checkpoint_numbering_continues_from_existing(fake, tmp_path):
    cp_dir = tmp_path / "checkpoints"
    cp_dir.mkdir()
    (cp_dir / "007_older.ma").write_text("x")
    result = session.checkpoint({"label": "next"})
    assert result["checkpoint_id"] == "008_next"


def test_checkpoint_prunes_beyond_20(fake, tmp_path):
    cp_dir = tmp_path / "checkpoints"
    cp_dir.mkdir()
    for i in range(1, 21):
        (cp_dir / ("%03d_old.ma" % i)).write_text("x")
    session.checkpoint({"label": "newest"})
    remaining = sorted(os.listdir(str(cp_dir)))
    assert len(remaining) == 20
    assert "001_old.ma" not in remaining
    assert "021_newest.ma" in remaining


def test_restore_unknown_id_hints_listing(fake):
    with pytest.raises(HandlerError) as exc:
        session.restore_checkpoint({"checkpoint_id": "042_nope"})
    assert "042_nope" in str(exc.value)


def test_restore_takes_pre_restore_checkpoint_then_opens(fake, tmp_path):
    cp_dir = tmp_path / "checkpoints"
    cp_dir.mkdir()
    (cp_dir / "003_target.ma").write_text("x")
    result = session.restore_checkpoint({"checkpoint_id": "003_target"})
    assert result["restored"] == "003_target"
    assert any("auto_pre_restore" in p for p in fake.saved_to)
    assert fake.opened and fake.opened[0].endswith("003_target.ma")


def test_undo_counts_steps_and_stops_at_queue_end(fake):
    fake.undo_fail_after = 2
    result = session.undo({"steps": 5})
    assert result == {"undone": 2, "requested": 5}


def test_undo_rejects_bad_steps(fake):
    with pytest.raises(HandlerError):
        session.undo({"steps": 0})


def test_new_scene_requires_confirm(fake):
    with pytest.raises(HandlerError) as exc:
        session.new_scene({})
    assert "confirm" in exc.value.hint
    assert fake.new_calls == 0


def test_new_scene_with_confirm(fake):
    result = session.new_scene({"confirm": True})
    assert result == {"new_scene": True}
    assert fake.new_calls == 1


def test_open_scene_missing_file(fake):
    with pytest.raises(HandlerError):
        session.open_scene({"path": "Z:/does/not/exist.ma"})


def test_open_scene_unsaved_changes_needs_confirm(fake, tmp_path):
    target = tmp_path / "scene.ma"
    target.write_text("x")
    fake.modified = True
    with pytest.raises(HandlerError) as exc:
        session.open_scene({"path": str(target)})
    assert "unsaved" in str(exc.value)
    result = session.open_scene({"path": str(target), "confirm": True})
    assert result["opened"] == str(target)


def test_save_scene_untitled_without_path_errors(fake):
    with pytest.raises(HandlerError) as exc:
        session.save_scene({})
    assert "path" in exc.value.hint


def test_save_scene_with_path_renames_then_saves(fake, tmp_path):
    target = str(tmp_path / "out.ma")
    result = session.save_scene({"path": target})
    assert result["path"] == target
    assert fake.scene_name == target


def test_undo_handlers_are_chunk_exempt():
    for fn in (session.undo, session.redo, session.restore_checkpoint,
               session.new_scene, session.open_scene):
        assert getattr(fn, "no_undo_chunk", False) is True
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_session.py -q` → import error.

- [ ] **Step 3: Implement `maya_plugin/handlers/session.py`:**

```python
"""Session safety (§5.6): checkpoints, undo/redo, scene lifecycle.

Checkpoints are incremental saves to <project>/checkpoints/NNN_label.ma.
Keep the newest 20, prune older. Undo works because every mutating tool
call is one undo chunk (dispatcher); undo/redo/scene-load handlers are
chunk-exempt via no_undo_chunk (they manipulate the queue themselves).
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional

from ..dispatcher import HandlerError
from . import ledger

KEEP_CHECKPOINTS = 20
MAX_UNDO_STEPS = 50
_NUMBERED = re.compile(r"^(\d{3})_(.+)\.ma$")


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _checkpoint_dir(cmds) -> str:
    scene = cmds.file(query=True, sceneName=True) or ""
    base = os.path.dirname(scene) if scene else cmds.workspace(
        query=True, rootDirectory=True
    )
    path = os.path.join(base, "checkpoints")
    os.makedirs(path, exist_ok=True)
    return path


def _sanitize(label: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "_", str(label).strip().lower()).strip("_")
    return (slug or "checkpoint")[:40]


def _existing(cp_dir: str):
    entries = []
    for name in os.listdir(cp_dir):
        match = _NUMBERED.match(name)
        if match:
            entries.append((int(match.group(1)), name))
    return sorted(entries)


def _save_checkpoint(cmds, label: str) -> Dict[str, str]:
    cp_dir = _checkpoint_dir(cmds)
    entries = _existing(cp_dir)
    number = (entries[-1][0] + 1) if entries else 1
    stem = "%03d_%s" % (number, _sanitize(label))
    path = os.path.join(cp_dir, stem + ".ma")
    cmds.file(path, exportAll=True, type="mayaAscii", force=True,
              preserveReferences=True)
    for _, name in _existing(cp_dir)[:-KEEP_CHECKPOINTS]:
        try:
            os.unlink(os.path.join(cp_dir, name))
        except OSError:
            pass
    return {"checkpoint_id": stem, "path": path}


def auto_checkpoint(reason: str) -> str:
    """Shared pre-destructive-op checkpoint. Returns the saved path."""
    return _save_checkpoint(_cmds(), "auto_" + reason)["path"]


# ------------------------------------------------------------------ handlers


def checkpoint(params: Dict[str, Any]) -> Dict[str, Any]:
    label = params.get("label")
    if not isinstance(label, str) or not label.strip():
        raise HandlerError(
            "missing required param 'label'",
            hint="pass a short label, e.g. label='pre_rune'",
        )
    return _save_checkpoint(_cmds(), label)


def restore_checkpoint(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    checkpoint_id = str(params.get("checkpoint_id") or "")
    cp_dir = _checkpoint_dir(cmds)
    path = os.path.join(cp_dir, checkpoint_id + ".ma")
    if not os.path.isfile(path):
        available = ", ".join(name[:-3] for _, name in _existing(cp_dir)[-5:])
        raise HandlerError(
            "checkpoint %r not found" % checkpoint_id,
            hint="most recent checkpoints: %s" % (available or "none saved yet"),
        )
    pre = _save_checkpoint(cmds, "auto_pre_restore")
    cmds.file(path, open=True, force=True)
    ledger.clear()
    return {"restored": checkpoint_id, "pre_restore_checkpoint": pre["checkpoint_id"]}


restore_checkpoint.no_undo_chunk = True


def _steps(params: Dict[str, Any]) -> int:
    steps = params.get("steps", 1)
    if not isinstance(steps, int) or isinstance(steps, bool) or not (
        1 <= steps <= MAX_UNDO_STEPS
    ):
        raise HandlerError(
            "steps must be an integer between 1 and %d" % MAX_UNDO_STEPS,
            hint="each mutating tool call is exactly one undo step",
        )
    return steps


def undo(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    steps = _steps(params)
    done = 0
    for _ in range(steps):
        try:
            cmds.undo()
        except RuntimeError:
            break  # queue exhausted
        done += 1
    return {"undone": done, "requested": steps}


undo.no_undo_chunk = True


def redo(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    steps = _steps(params)
    done = 0
    for _ in range(steps):
        try:
            cmds.redo()
        except RuntimeError:
            break
        done += 1
    return {"redone": done, "requested": steps}


redo.no_undo_chunk = True


def new_scene(params: Dict[str, Any]) -> Dict[str, Any]:
    if params.get("confirm") is not True:
        raise HandlerError(
            "new_scene discards the current scene and requires confirmation",
            hint="pass confirm=true; call maya_checkpoint or maya_save_scene first "
            "if the current state matters",
        )
    _cmds().file(new=True, force=True)
    ledger.clear()
    return {"new_scene": True}


new_scene.no_undo_chunk = True


def open_scene(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    path = str(params.get("path") or "")
    if not os.path.isfile(path):
        raise HandlerError(
            "scene file %r not found" % path,
            hint="pass an absolute path to an existing .ma/.mb file",
        )
    if cmds.file(query=True, modified=True) and params.get("confirm") is not True:
        raise HandlerError(
            "the current scene has unsaved changes",
            hint="pass confirm=true to discard them, or maya_save_scene / "
            "maya_checkpoint first",
        )
    cmds.file(path, open=True, force=True)
    ledger.clear()
    return {"opened": path}


open_scene.no_undo_chunk = True


def save_scene(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    path: Optional[str] = params.get("path")
    if path:
        cmds.file(rename=path)
    current = cmds.file(query=True, sceneName=True) or ""
    if not current:
        raise HandlerError(
            "the scene has never been saved and no path was given",
            hint="pass path='D:/.../scene.ma' on the first save",
        )
    file_type = "mayaBinary" if current.lower().endswith(".mb") else "mayaAscii"
    cmds.file(save=True, type=file_type)
    return {"path": current}
```

- [ ] **Step 4: Run tests** — `uv run pytest tests/test_session.py -q` → all PASS.

- [ ] **Step 5: Refactor `code_exec.py`** — delete `_auto_checkpoint` (lines 74-88) and the `import os`/`import time` it needed; replace its call site in `execute_python`:

```python
    checkpoint_path: Optional[str] = None
    if params.get("risky"):
        from . import session  # noqa: PLC0415 - avoid cycle at import time

        checkpoint_path = session.auto_checkpoint("risky_exec")
```

Run: `uv run pytest tests/test_code_exec.py -q` → PASS (existing risky-path tests may monkeypatch `_auto_checkpoint`; update them to monkeypatch `session.auto_checkpoint`).

- [ ] **Step 6: Register handlers** — in `maya_mcp_plugin._build_handlers` add:

```python
from .handlers import capture, code_exec, scene, session

        "checkpoint": session.checkpoint,
        "restore_checkpoint": session.restore_checkpoint,
        "undo": session.undo,
        "redo": session.redo,
        "new_scene": session.new_scene,
        "open_scene": session.open_scene,
        "save_scene": session.save_scene,
```

- [ ] **Step 7: Add schemas** — append to `src/maya_mcp/schemas.py`:

```python
class CheckpointResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    checkpoint_id: str = Field(description="Stem NNN_label; pass to maya_restore_checkpoint.")
    path: str = Field(description="Saved .ma file path.")


class RestoreResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    restored: str
    pre_restore_checkpoint: str = Field(
        description="Auto-checkpoint of the state before restoring, in case you change your mind."
    )


class UndoResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    undone: int = 0
    redone: int = 0
    requested: int
```

- [ ] **Step 8: Add MCP tools** — in `create_server` (`src/maya_mcp/server.py`), following the existing wrapper pattern (`maya.request(cmd, params, timeout_s=...)` + `Model.model_validate`). All eight, complete:

```python
    SESSION_TIMEOUT_S = 60.0  # checkpoint saves of heavy scenes take a while

    @mcp.tool(
        title="Save checkpoint",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=False
        ),
    )
    def maya_checkpoint(
        label: Annotated[str, Field(min_length=1, max_length=60, description=(
            "Short label for the checkpoint, e.g. 'pre_rune'. Sanitized to "
            "[a-z0-9_-]; the returned checkpoint_id is NNN_label."
        ))],
    ) -> CheckpointResult:
        """Incremental scene save to <project>/checkpoints/. Keeps the newest
        20; older ones are pruned. Cheap insurance before experiments."""
        return CheckpointResult.model_validate(
            maya.request("checkpoint", {"label": label}, timeout_s=SESSION_TIMEOUT_S)
        )

    @mcp.tool(
        title="Restore checkpoint",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
    )
    def maya_restore_checkpoint(
        checkpoint_id: Annotated[str, Field(description=(
            "Id returned by maya_checkpoint (NNN_label)."
        ))],
    ) -> RestoreResult:
        """Replace the current scene with a checkpoint. An auto-checkpoint of
        the current state is taken first. Discards the undo queue (file load)."""
        return RestoreResult.model_validate(
            maya.request(
                "restore_checkpoint", {"checkpoint_id": checkpoint_id},
                timeout_s=SESSION_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Undo",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
    )
    def maya_undo(
        steps: Annotated[int, Field(ge=1, le=50, description=(
            "How many tool calls to undo; each mutating call is one step."
        ))] = 1,
    ) -> UndoResult:
        """Undo the last N mutating tool calls. Undo is cheaper than re-modeling;
        returns how many steps actually landed (the queue may be shorter)."""
        return UndoResult.model_validate(
            maya.request("undo", {"steps": steps}, timeout_s=SESSION_TIMEOUT_S)
        )

    @mcp.tool(
        title="Redo",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
    )
    def maya_redo(
        steps: Annotated[int, Field(ge=1, le=50, description="Steps to redo.")] = 1,
    ) -> UndoResult:
        """Redo previously undone tool calls."""
        return UndoResult.model_validate(
            maya.request("redo", {"steps": steps}, timeout_s=SESSION_TIMEOUT_S)
        )

    @mcp.tool(
        title="New scene",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
    )
    def maya_new_scene(
        confirm: Annotated[bool, Field(description=(
            "Must be true; the current scene is discarded."
        ))] = False,
    ) -> dict:
        """Start an empty scene. REFUSES without confirm=true."""
        return maya.request("new_scene", {"confirm": confirm}, timeout_s=SESSION_TIMEOUT_S)

    @mcp.tool(
        title="Open scene",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
    )
    def maya_open_scene(
        path: Annotated[str, Field(description="Absolute path to a .ma/.mb file.")],
        confirm: Annotated[bool, Field(description=(
            "Required (true) only when the current scene has unsaved changes."
        ))] = False,
    ) -> dict:
        """Open a scene file, replacing the current scene."""
        return maya.request(
            "open_scene", {"path": path, "confirm": confirm}, timeout_s=SESSION_TIMEOUT_S
        )

    @mcp.tool(
        title="Save scene",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=True
        ),
    )
    def maya_save_scene(
        path: Annotated[Optional[str], Field(description=(
            "Target path for save-as; omit to save in place (errors on an "
            "untitled scene)."
        ))] = None,
    ) -> dict:
        """Save the scene (.ma or .mb by extension)."""
        return maya.request("save_scene", {"path": path}, timeout_s=SESSION_TIMEOUT_S)

    @mcp.tool(
        title="Reset Python namespace",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=True
        ),
    )
    def maya_reset_namespace() -> dict:
        """Clear the persistent maya_execute_python namespace."""
        return maya.request("reset_namespace", {}, timeout_s=SCENE_TIMEOUT_S)
```

- [ ] **Step 9: Extend `tests/test_server_tools.py`** following its existing fake-connection pattern: assert the eight tools are registered, that `maya_checkpoint` forwards `{"label": ...}` to command `checkpoint`, and that `maya_new_scene()` (default confirm=False) forwards `confirm: False` (the plugin refuses — the refusal round-trip is the plugin's own test).

- [ ] **Step 10: Extend `tests/test_handlers_mayapy.py`** — real checkpoint/undo cycle:

```python
class TestSessionInMaya:
    def test_checkpoint_restore_roundtrip(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import session

        cmds.file(rename=str(tmp_path / "work.ma"))
        cmds.polyCube(name="keeper")
        cp = session.checkpoint({"label": "with_keeper"})
        cmds.polySphere(name="stray")
        result = session.restore_checkpoint({"checkpoint_id": cp["checkpoint_id"]})
        assert result["restored"] == cp["checkpoint_id"]
        assert cmds.objExists("keeper")
        assert not cmds.objExists("stray")

    def test_undo_reverses_a_chunked_change(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import session

        cmds.undoInfo(openChunk=True, chunkName="maya-mcp")
        cmds.polyCube(name="undo_me")
        cmds.undoInfo(closeChunk=True)
        assert cmds.objExists("undo_me")
        result = session.undo({"steps": 1})
        assert result["undone"] == 1
        assert not cmds.objExists("undo_me")
```

- [ ] **Step 11: Run everything**

Run: `uv run pytest -q` → all PASS.
Run: `E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q` → PASS.

- [ ] **Step 12: Commit**

```bash
git add maya_plugin/handlers/session.py maya_plugin/handlers/code_exec.py maya_plugin/maya_mcp_plugin.py src/maya_mcp/server.py src/maya_mcp/schemas.py tests/
git commit -m "feat(m1): session safety - checkpoints, undo/redo, scene lifecycle"
```

---

### Task 4: meshcheck — manifold stats + shading-group verify/repair

The golem run proved (#577 req 1): per-face shader assignment silently no-ops on `polyCBoolOp` output AND corrupts the shading groups — faces later drop to unassigned-green. The remedy is object-level reassignment; this module supplies the check and the repair that Tasks 6/7/9 run inside their tools.

**Files:**
- Create: `maya_plugin/handlers/meshcheck.py`
- Test: `tests/test_handlers_mayapy.py` (extend — this module is OpenMaya-bound; there is no meaningful fake)

**Interfaces:**
- Produces: `meshcheck.mesh_stats(transform_or_shape: str) -> dict` with keys `tris`, `verts`, `faces`, `boundary_edges`, `nonmanifold_edges`, `watertight` (bool: no boundary and no non-manifold edges).
- Produces: `meshcheck.ensure_object_shading(cmds, shape: str, fallback_sg: str | None) -> dict` with keys `sg` (the shading group now covering the shape) and `repaired` (bool: True when membership was collapsed to object level).
- Produces: `meshcheck.first_sg(cmds, shape: str) -> str | None` — the shape's first connected shadingEngine (callers snapshot input A's material before a boolean).

- [ ] **Step 1: Write failing mayapy tests** (append to `tests/test_handlers_mayapy.py`):

```python
class TestMeshcheckInMaya:
    def test_closed_cube_is_watertight(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import meshcheck

        cube = cmds.polyCube(name="wt_cube")[0]
        stats = meshcheck.mesh_stats(cube)
        assert stats["tris"] == 12
        assert stats["boundary_edges"] == 0
        assert stats["nonmanifold_edges"] == 0
        assert stats["watertight"] is True

    def test_open_plane_is_not_watertight(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import meshcheck

        plane = cmds.polyPlane(name="wt_plane", sx=1, sy=1)[0]
        stats = meshcheck.mesh_stats(plane)
        assert stats["boundary_edges"] == 4
        assert stats["watertight"] is False

    def test_ensure_object_shading_repairs_partial_assignment(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import meshcheck

        cube = cmds.polyCube(name="sg_cube")[0]
        shape = cmds.listRelatives(cube, shapes=True, fullPath=True)[0]
        shader = cmds.shadingNode("lambert", asShader=True, name="sg_red")
        sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                       name="sg_redSG")
        cmds.connectAttr(shader + ".outColor", sg + ".surfaceShader", force=True)
        # per-face assignment on half the cube = partial coverage
        cmds.sets(cube + ".f[0:2]", edit=True, forceElement=sg)
        result = meshcheck.ensure_object_shading(cmds, shape, fallback_sg=sg)
        assert result["repaired"] is True
        assert result["sg"] == sg
        # whole shape is now an object-level member
        assert shape in (cmds.sets(sg, query=True) or [])

    def test_ensure_object_shading_leaves_healthy_mesh_alone(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import meshcheck

        cube = cmds.polyCube(name="sg_ok_cube")[0]
        shape = cmds.listRelatives(cube, shapes=True, fullPath=True)[0]
        # fresh primitives are object-level members of initialShadingGroup
        result = meshcheck.ensure_object_shading(cmds, shape, fallback_sg=None)
        assert result["repaired"] is False
        assert result["sg"] == "initialShadingGroup"
```

- [ ] **Step 2: Run to verify failure** — `E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -k Meshcheck -q` → import error.

- [ ] **Step 3: Implement `maya_plugin/handlers/meshcheck.py`:**

```python
"""Mesh integrity + shading-group discipline (golem-run lesson, #577 req 1).

Per-face shader assignment on polyCBoolOp output silently no-ops and corrupts
the shading groups (faces drop to unassigned-green in VP2). Only object-level
assignment is reliable after a boolean — ensure_object_shading collapses any
partial/absent membership to a single object-level SG and reports it.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..dispatcher import HandlerError


def _mesh_fn(name: str):
    import maya.api.OpenMaya as om  # noqa: PLC0415 - only importable inside Maya

    sel = om.MSelectionList()
    try:
        sel.add(name)
    except RuntimeError:
        raise HandlerError(
            "object %r not found" % name,
            hint="call maya_get_scene_graph to list objects",
        ) from None
    dag = sel.getDagPath(0)
    try:
        dag.extendToShape()
    except RuntimeError:
        pass  # already a shape
    return om, dag


def mesh_stats(name: str) -> Dict[str, Any]:
    om, dag = _mesh_fn(name)
    fn = om.MFnMesh(dag)
    tri_counts, _ = fn.getTriangles()
    boundary = 0
    nonmanifold = 0
    edge_it = om.MItMeshEdge(dag)
    while not edge_it.isDone():
        connected = edge_it.numConnectedFaces()
        if connected == 1:
            boundary += 1
        elif connected > 2:
            nonmanifold += 1
        edge_it.next()
    return {
        "tris": sum(tri_counts),
        "verts": fn.numVertices,
        "faces": fn.numPolygons,
        "boundary_edges": boundary,
        "nonmanifold_edges": nonmanifold,
        "watertight": boundary == 0 and nonmanifold == 0,
    }


def first_sg(cmds, shape: str) -> Optional[str]:
    engines = cmds.listConnections(shape, type="shadingEngine") or []
    return engines[0] if engines else None


def ensure_object_shading(cmds, shape: str, fallback_sg: Optional[str]) -> Dict[str, Any]:
    """Collapse shading to one object-level SG unless it is already exactly that.

    Healthy = exactly one shading group and the shape itself (not face
    components) is a member. Anything else — no SG, several SGs, or face-level
    membership — is unreliable on boolean output and gets force-assigned.
    """
    sgs = cmds.listSets(object=shape, type=1) or []
    if len(sgs) == 1:
        members = cmds.sets(sgs[0], query=True) or []
        short = shape.split("|")[-1]
        if any(m.split("|")[-1] == short and ".f[" not in m for m in members):
            return {"sg": sgs[0], "repaired": False}
    target = fallback_sg or (sgs[0] if sgs else "initialShadingGroup")
    cmds.sets(shape, edit=True, forceElement=target)
    return {"sg": target, "repaired": True}
```

- [ ] **Step 4: Run tests** — `E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -k Meshcheck -q` → PASS. Also `uv run pytest -q` (headless suite unaffected, still green).

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/meshcheck.py tests/test_handlers_mayapy.py
git commit -m "feat(m1): meshcheck - manifold stats + shading-group verify/repair"
```

---

### Task 5: Modeling basics — primitives, duplicate, transform, group/parent/rename/delete

**Files:**
- Create: `maya_plugin/handlers/modeling.py`
- Modify: `maya_plugin/maya_mcp_plugin.py`, `src/maya_mcp/server.py`, `src/maya_mcp/schemas.py`
- Test: `tests/test_modeling.py` (new, headless validation), `tests/test_handlers_mayapy.py` (extend, real geometry), `tests/test_server_tools.py` (extend)

**Interfaces:**
- Consumes: `naming.unique_name/require_object/require_mesh`, `ledger.record/check/forget` (Task 2).
- Produces (handlers → commands): `create_primitive`, `duplicate`, `transform`, `group`, `parent`, `rename`, `delete_objects`.
- Produces (MCP tools): `maya_create_primitive(kind, name, translate, rotate, scale, divisions)`, `maya_duplicate(name, new_name, translate, rotate, scale)`, `maya_transform(names, translate, rotate, scale, relative)`, `maya_group(names, group_name)`, `maya_parent(child, parent)`, `maya_rename(name, new_name)`, `maya_delete_objects(names)`.
- All mutation results carry `{"name": <canonical long name>, "warnings": [str]}`; `transform` returns per-object `{name, translate, rotate, scale}` AFTER the edit plus ledger warnings.

- [ ] **Step 1: Write failing headless tests** — `tests/test_modeling.py`. These cover validation and orchestration only (geometry correctness is mayapy's job). Build a FakeCmds recording calls; monkeypatch `modeling._cmds`. Complete test list:

```python
"""modeling handler validation tests against a fake cmds — no Maya required."""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import ledger, modeling


class FakeCmds:
    """Records calls; simulates a flat scene namespace."""

    def __init__(self, objects=(), shapes=None):
        self.objects = set(objects)
        self.shapes = shapes or {}  # long transform -> (shape_long, node_type)
        self.calls = []
        self.xf = {}

    def objExists(self, name):
        return any(o == name or o.split("|")[-1] == name for o in self.objects)

    def ls(self, name=None, long=False, **kw):
        assert long
        return [o for o in self.objects if o == name or o.split("|")[-1] == name]

    def listRelatives(self, node, shapes=False, fullPath=False, noIntermediate=False):
        assert shapes and fullPath and noIntermediate
        entry = self.shapes.get(node)
        return [entry[0]] if entry else None

    def nodeType(self, node):
        for shape, ntype in self.shapes.values():
            if shape == node:
                return ntype
        raise AssertionError("unexpected nodeType call")

    def polyCube(self, name=None, constructionHistory=False, **kw):
        self.calls.append(("polyCube", name, kw))
        long_name = "|" + name
        self.objects.add(long_name)
        self.xf[long_name] = ((0, 0, 0), (0, 0, 0), (1, 1, 1))
        return [name, name + "Shape"]

    def xform(self, name, **kw):
        if kw.get("query"):
            t, r, s = self.xf.get(name, ((0, 0, 0), (0, 0, 0), (1, 1, 1)))
            if kw.get("translation"):
                return list(t)
            if kw.get("rotation"):
                return list(r)
            return list(s)
        self.calls.append(("xform", name, kw))

    def delete(self, *names):
        self.calls.append(("delete", names))
        for n in names:
            self.objects.discard(n)


@pytest.fixture(autouse=True)
def clean_ledger():
    ledger.clear()
    yield
    ledger.clear()


def test_create_primitive_rejects_unknown_kind():
    with pytest.raises(HandlerError) as exc:
        modeling.create_primitive({"kind": "dodecahedron", "name": "x"})
    assert "cube" in exc.value.hint  # hint lists valid kinds


def test_create_primitive_requires_name():
    with pytest.raises(HandlerError):
        modeling.create_primitive({"kind": "cube"})


def test_create_primitive_collision_gets_suffix(monkeypatch):
    fake = FakeCmds(objects={"|golem_arm"})
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    result = modeling.create_primitive({"kind": "cube", "name": "golem_arm"})
    assert result["name"] == "|golem_arm_001"


def test_transform_missing_object_errors(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    with pytest.raises(HandlerError):
        modeling.transform({"names": ["|nope"], "translate": [1, 0, 0]})


def test_transform_requires_some_component(monkeypatch):
    fake = FakeCmds(objects={"|a"})
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        modeling.transform({"names": ["|a"]})
    assert "translate" in exc.value.hint


def test_transform_reports_user_moved_warning(monkeypatch):
    fake = FakeCmds(objects={"|a"})
    fake.xf["|a"] = ((0, 0, 0), (0, 0, 0), (1, 1, 1))
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    ledger.record(fake, "|a")
    fake.xf["|a"] = ((5, 0, 0), (0, 0, 0), (1, 1, 1))  # user dragged it
    result = modeling.transform({"names": ["|a"], "translate": [1, 0, 0]})
    assert any("outside" in w for w in result["warnings"])


def test_delete_objects_lists_all_missing(monkeypatch):
    fake = FakeCmds(objects={"|a"})
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        modeling.delete_objects({"names": ["|a", "|gone", "|also_gone"]})
    assert "|gone" in str(exc.value) and "|also_gone" in str(exc.value)
    assert not any(c[0] == "delete" for c in fake.calls)  # nothing deleted
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_modeling.py -q` → import error.

- [ ] **Step 3: Implement `maya_plugin/handlers/modeling.py`** (this task's half; boolean/cleanup/remesh land in Tasks 6/9 in this same file):

```python
"""Structured modeling (§5.3): reliability layer over maya.cmds.

Tools address objects by name only, never selection. Requested names that
collide get deterministic _NNN suffixes; canonical long names come back.
Transform-writing handlers record to the ledger and surface live-user edits
as warnings (#577 req 4c).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..dispatcher import HandlerError
from . import ledger, naming

PRIMITIVE_KINDS = ("cube", "sphere", "cylinder", "plane", "torus", "cone")
MAX_DIVISIONS = 200


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _vec3(params: Dict[str, Any], key: str) -> Optional[List[float]]:
    value = params.get(key)
    if value is None:
        return None
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 3
        or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)
    ):
        raise HandlerError(
            "%s must be a list of 3 numbers, got %r" % (key, value),
            hint="e.g. %s=[0, 1.5, 0]" % key,
        )
    return [float(v) for v in value]


def _apply_xform(cmds, name: str, translate, rotate, scale, relative: bool) -> None:
    kwargs: Dict[str, Any] = {"relative": True} if relative else {"worldSpace": True, "absolute": True}
    if translate is not None:
        cmds.xform(name, translation=translate, **kwargs)
    if rotate is not None:
        cmds.xform(name, rotation=rotate, **kwargs)
    if scale is not None:
        if relative:
            cmds.xform(name, scale=scale, relative=True)
        else:
            cmds.xform(name, scale=scale)


def _long(cmds, name: str) -> str:
    matches = cmds.ls(name, long=True) or [name]
    return matches[0]


def create_primitive(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    kind = params.get("kind")
    if kind not in PRIMITIVE_KINDS:
        raise HandlerError(
            "unknown primitive kind %r" % kind,
            hint="valid kinds: %s" % ", ".join(PRIMITIVE_KINDS),
        )
    requested = params.get("name")
    if not isinstance(requested, str) or not requested.strip():
        raise HandlerError(
            "missing required param 'name'",
            hint="pass the object name to create, e.g. name='golem_torso'",
        )
    divisions = params.get("divisions", 1)
    if not isinstance(divisions, int) or not (1 <= divisions <= MAX_DIVISIONS):
        raise HandlerError(
            "divisions must be an integer 1..%d" % MAX_DIVISIONS,
            hint="1 = Maya defaults; higher multiplies subdivision counts",
        )
    name = naming.unique_name(cmds, requested)

    creators = {
        "cube": lambda: cmds.polyCube(
            name=name, constructionHistory=False,
            subdivisionsWidth=divisions, subdivisionsHeight=divisions,
            subdivisionsDepth=divisions,
        ),
        "plane": lambda: cmds.polyPlane(
            name=name, constructionHistory=False,
            subdivisionsWidth=divisions, subdivisionsHeight=divisions,
        ),
        "sphere": lambda: cmds.polySphere(
            name=name, constructionHistory=False,
            subdivisionsAxis=20 * divisions, subdivisionsHeight=20 * divisions,
        ),
        "cylinder": lambda: cmds.polyCylinder(
            name=name, constructionHistory=False,
            subdivisionsAxis=20 * divisions, subdivisionsHeight=divisions,
        ),
        "cone": lambda: cmds.polyCone(
            name=name, constructionHistory=False,
            subdivisionsAxis=20 * divisions, subdivisionsHeight=divisions,
        ),
        "torus": lambda: cmds.polyTorus(
            name=name, constructionHistory=False,
            subdivisionsAxis=20 * divisions, subdivisionsHeight=20 * divisions,
        ),
    }
    created = creators[kind]()[0]
    long_name = _long(cmds, created)
    _apply_xform(
        cmds, long_name,
        _vec3(params, "translate"), _vec3(params, "rotate"), _vec3(params, "scale"),
        relative=False,
    )
    ledger.record(cmds, long_name)
    return {"name": long_name, "warnings": []}


def duplicate(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    source = naming.require_object(cmds, str(params.get("name") or ""))
    requested = params.get("new_name")
    if not isinstance(requested, str) or not requested.strip():
        raise HandlerError(
            "missing required param 'new_name'",
            hint="pass the name for the copy, e.g. new_name='golem_arm_L'",
        )
    warnings = [w for w in [ledger.check(cmds, source)] if w]
    new_name = naming.unique_name(cmds, requested)
    copy = cmds.duplicate(source, name=new_name, returnRootsOnly=True)[0]
    long_name = _long(cmds, copy)
    _apply_xform(
        cmds, long_name,
        _vec3(params, "translate"), _vec3(params, "rotate"), _vec3(params, "scale"),
        relative=True,
    )
    ledger.record(cmds, long_name)
    return {"name": long_name, "warnings": warnings}


def transform(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    names = params.get("names")
    if not isinstance(names, list) or not names:
        raise HandlerError(
            "names must be a non-empty list of object names",
            hint='e.g. names=["|golem|torso"]',
        )
    translate = _vec3(params, "translate")
    rotate = _vec3(params, "rotate")
    scale = _vec3(params, "scale")
    if translate is None and rotate is None and scale is None:
        raise HandlerError(
            "nothing to do",
            hint="pass at least one of translate, rotate, scale",
        )
    relative = params.get("relative", True) is not False
    resolved = [naming.require_object(cmds, str(n)) for n in names]

    warnings: List[str] = []
    objects: List[Dict[str, Any]] = []
    for name in resolved:
        moved = ledger.check(cmds, name)
        if moved:
            warnings.append(moved)
        _apply_xform(cmds, name, translate, rotate, scale, relative)
        ledger.record(cmds, name)
        objects.append(
            {
                "name": name,
                "translate": cmds.xform(name, query=True, worldSpace=True, translation=True),
                "rotate": cmds.xform(name, query=True, worldSpace=True, rotation=True),
                "scale": cmds.xform(name, query=True, worldSpace=True, scale=True),
            }
        )
    return {"objects": objects, "warnings": warnings}


def group(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    names = params.get("names")
    if not isinstance(names, list) or not names:
        raise HandlerError(
            "names must be a non-empty list", hint='e.g. names=["|a", "|b"]'
        )
    resolved = [naming.require_object(cmds, str(n)) for n in names]
    requested = params.get("group_name")
    if not isinstance(requested, str) or not requested.strip():
        raise HandlerError(
            "missing required param 'group_name'", hint="e.g. group_name='golem'"
        )
    grp = cmds.group(*resolved, name=naming.unique_name(cmds, requested))
    return {"name": _long(cmds, grp), "warnings": []}


def parent(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    child = naming.require_object(cmds, str(params.get("child") or ""))
    target = naming.require_object(cmds, str(params.get("parent") or ""))
    moved = cmds.parent(child, target)
    long_name = _long(cmds, moved[0])
    ledger.forget(child)  # its long name just changed
    ledger.record(cmds, long_name)
    return {"name": long_name, "warnings": []}


def rename(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    old = naming.require_object(cmds, str(params.get("name") or ""))
    requested = params.get("new_name")
    if not isinstance(requested, str) or not requested.strip():
        raise HandlerError(
            "missing required param 'new_name'", hint="pass the new object name"
        )
    new = cmds.rename(old, naming.unique_name(cmds, requested))
    ledger.forget(old)
    long_name = _long(cmds, new)
    ledger.record(cmds, long_name)
    return {"name": long_name, "warnings": []}


def delete_objects(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    names = params.get("names")
    if not isinstance(names, list) or not names:
        raise HandlerError(
            "names must be a non-empty list", hint='e.g. names=["|scrap"]'
        )
    missing = [str(n) for n in names if not cmds.objExists(str(n))]
    if missing:
        raise HandlerError(
            "objects not found: %s (nothing was deleted)" % ", ".join(missing),
            hint="call maya_get_scene_graph to list objects; the delete is "
            "all-or-nothing",
        )
    resolved = [naming.require_object(cmds, str(n)) for n in names]
    cmds.delete(*resolved)
    for name in resolved:
        ledger.forget(name)
    return {"deleted": resolved, "warnings": []}
```

- [ ] **Step 4: Run headless tests** — `uv run pytest tests/test_modeling.py -q` → PASS.

- [ ] **Step 5: Register handlers** in `_build_handlers`:

```python
        "create_primitive": modeling.create_primitive,
        "duplicate": modeling.duplicate,
        "transform": modeling.transform,
        "group": modeling.group,
        "parent": modeling.parent,
        "rename": modeling.rename,
        "delete_objects": modeling.delete_objects,
```

- [ ] **Step 6: Schemas** — append to `schemas.py`:

```python
class NameResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="Canonical long name of the affected object.")
    warnings: List[str] = Field(default_factory=list)


class TransformedObject(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    translate: List[float]
    rotate: List[float]
    scale: List[float]


class TransformResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    objects: List[TransformedObject]
    warnings: List[str] = Field(
        default_factory=list,
        description="Includes live-user-edit notices when an object moved outside maya-mcp.",
    )


class DeleteResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    deleted: List[str]
    warnings: List[str] = Field(default_factory=list)
```

- [ ] **Step 7: MCP tools** in `server.py`. Pattern identical for all seven; two shown complete, replicate mechanically for the rest (`maya_duplicate`, `maya_group`, `maya_parent`, `maya_rename`, `maya_delete_objects` — each forwards its params dict verbatim to the same-named command, `timeout_s=SCENE_TIMEOUT_S`, `destructive_hint=True` for delete, False otherwise, `read_only_hint=False`, `idempotent_hint=False`):

```python
    Vec3 = Annotated[
        Optional[List[float]],
        Field(min_length=3, max_length=3, description="XYZ triple."),
    ]

    @mcp.tool(
        title="Create primitive",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=False
        ),
    )
    def maya_create_primitive(
        kind: Annotated[
            Literal["cube", "sphere", "cylinder", "plane", "torus", "cone"],
            Field(description="Primitive type."),
        ],
        name: Annotated[str, Field(min_length=1, description=(
            "Requested name; collisions get a deterministic _NNN suffix and the "
            "assigned canonical long name is returned."
        ))],
        translate: Vec3 = None,
        rotate: Vec3 = None,
        scale: Vec3 = None,
        divisions: Annotated[int, Field(ge=1, le=200, description=(
            "1 = Maya defaults; higher multiplies subdivision counts."
        ))] = 1,
    ) -> NameResult:
        """Create a polygon primitive at an optional transform (no construction
        history)."""
        return NameResult.model_validate(
            maya.request(
                "create_primitive",
                {"kind": kind, "name": name, "translate": translate,
                 "rotate": rotate, "scale": scale, "divisions": divisions},
                timeout_s=SCENE_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Transform objects",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=False
        ),
    )
    def maya_transform(
        names: Annotated[List[str], Field(min_length=1, description=(
            "Canonical long names of the objects to move."
        ))],
        translate: Vec3 = None,
        rotate: Vec3 = None,
        scale: Vec3 = None,
        relative: Annotated[bool, Field(description=(
            "True (default): offsets relative to current values. False: absolute "
            "world-space translate, object-space rotate/scale."
        ))] = True,
    ) -> TransformResult:
        """Move/rotate/scale objects by name. Returns the resulting transforms —
        trust these over your own bookkeeping: the live user may also be moving
        things, and warnings will say so."""
        return TransformResult.model_validate(
            maya.request(
                "transform",
                {"names": names, "translate": translate, "rotate": rotate,
                 "scale": scale, "relative": relative},
                timeout_s=SCENE_TIMEOUT_S,
            )
        )
```

- [ ] **Step 8: mayapy real-geometry tests** (append to `tests/test_handlers_mayapy.py`):

```python
class TestModelingInMaya:
    def test_create_transform_duplicate_roundtrip(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        created = modeling.create_primitive(
            {"kind": "cube", "name": "mb_cube", "translate": [1, 2, 3]}
        )
        assert created["name"] == "|mb_cube"
        assert cmds.xform("|mb_cube", q=True, ws=True, t=True) == [1.0, 2.0, 3.0]

        copy = modeling.duplicate(
            {"name": "|mb_cube", "new_name": "mb_cube_b", "translate": [2, 0, 0]}
        )
        assert copy["name"] == "|mb_cube_b"
        assert cmds.xform("|mb_cube_b", q=True, ws=True, t=True) == [3.0, 2.0, 3.0]

        moved = modeling.transform(
            {"names": ["|mb_cube"], "translate": [0, 0, 0], "relative": False}
        )
        assert moved["objects"][0]["translate"] == [0.0, 0.0, 0.0]

    def test_group_parent_rename_delete(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        modeling.create_primitive({"kind": "cube", "name": "gp_a"})
        modeling.create_primitive({"kind": "cube", "name": "gp_b"})
        grp = modeling.group({"names": ["|gp_a", "|gp_b"], "group_name": "gp_grp"})
        assert grp["name"] == "|gp_grp"
        modeling.create_primitive({"kind": "cube", "name": "gp_c"})
        parented = modeling.parent({"child": "|gp_c", "parent": "|gp_grp"})
        assert parented["name"] == "|gp_grp|gp_c"
        renamed = modeling.rename({"name": "|gp_grp|gp_c", "new_name": "gp_kid"})
        assert renamed["name"] == "|gp_grp|gp_kid"
        modeling.delete_objects({"names": ["|gp_grp"]})
        assert not cmds.objExists("gp_grp")
```

- [ ] **Step 9: Run everything** — `uv run pytest -q` and `E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q` → all PASS.

- [ ] **Step 10: Commit**

```bash
git add maya_plugin/handlers/modeling.py maya_plugin/maya_mcp_plugin.py src/maya_mcp/server.py src/maya_mcp/schemas.py tests/
git commit -m "feat(m1): modeling basics - primitives, duplicate, transform, hierarchy ops"
```

---

### Task 6: maya_boolean_op — with in-tool SG cleanup (#577 req 1)

**Files:**
- Modify: `maya_plugin/handlers/modeling.py` (add `boolean_op` + shared `_do_boolean`)
- Modify: `maya_plugin/maya_mcp_plugin.py`, `src/maya_mcp/server.py`, `src/maya_mcp/schemas.py`
- Test: `tests/test_modeling.py` (validation), `tests/test_handlers_mayapy.py` (geometry + SG regression)

**Interfaces:**
- Consumes: `session.auto_checkpoint` (Task 3), `meshcheck.mesh_stats/first_sg/ensure_object_shading` (Task 4).
- Produces: `modeling._do_boolean(cmds, a_long, b_long, op, new_name) -> dict` — shared by `etch_text` (Task 7). Returns `{"name", "tris", "watertight", "warnings"}`.
- Produces MCP tool: `maya_boolean_op(a, b, op, new_name)`.

- [ ] **Step 1: Failing mayapy tests** (append to `tests/test_handlers_mayapy.py`):

```python
class TestBooleanInMaya:
    def test_difference_carves_and_is_clean(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        cmds.file(rename=str(tmp_path / "bool.ma"))
        cmds.polyCube(name="base", w=2, h=2, d=2)
        cmds.polySphere(name="cutter", r=1.2)
        cmds.xform("cutter", ws=True, t=(1, 1, 1))
        result = modeling.boolean_op(
            {"a": "|base", "b": "|cutter", "op": "difference", "new_name": "carved"}
        )
        assert result["name"] == "|carved"
        assert result["watertight"] is True
        assert result["tris"] > 12
        # inputs consumed, no leftover boolean nodes, no construction history
        assert not cmds.objExists("base") and not cmds.objExists("cutter")
        assert cmds.ls(type="polyCBoolOp") == []
        shape = cmds.listRelatives("|carved", shapes=True, fullPath=True)[0]
        assert cmds.listHistory(shape) == [shape]

    def test_boolean_keeps_object_level_shading(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        cmds.file(rename=str(tmp_path / "boolsg.ma"))
        cmds.polyCube(name="base2", w=2, h=2, d=2)
        shader = cmds.shadingNode("lambert", asShader=True, name="bool_clay")
        sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                       name="bool_claySG")
        cmds.connectAttr(shader + ".outColor", sg + ".surfaceShader", force=True)
        cmds.sets("base2", edit=True, forceElement=sg)
        cmds.polySphere(name="cutter2", r=1.2)
        result = modeling.boolean_op(
            {"a": "|base2", "b": "|cutter2", "op": "difference", "new_name": "carved2"}
        )
        # the run's trap: output must end object-level assigned to A's material
        shape = cmds.listRelatives("|carved2", shapes=True, fullPath=True)[0]
        assert shape in (cmds.sets(sg, query=True) or [])

    def test_boolean_takes_auto_checkpoint(self, tmp_path):
        import os

        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        cmds.file(rename=str(tmp_path / "boolcp.ma"))
        cmds.polyCube(name="base3")
        cmds.polySphere(name="cutter3")
        modeling.boolean_op(
            {"a": "|base3", "b": "|cutter3", "op": "union", "new_name": "fused3"}
        )
        cp_dir = str(tmp_path / "checkpoints")
        assert any("auto_boolean" in f for f in os.listdir(cp_dir))
```

Also append to `tests/test_modeling.py` (headless validation):

```python
def test_boolean_rejects_unknown_op(monkeypatch):
    fake = FakeCmds(objects={"|a", "|b"})
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        modeling.boolean_op({"a": "|a", "b": "|b", "op": "xor", "new_name": "x"})
    assert "union" in exc.value.hint


def test_boolean_rejects_same_object(monkeypatch):
    fake = FakeCmds(
        objects={"|a"},
        shapes={"|a": ("|a|aShape", "mesh")},
    )
    monkeypatch.setattr(modeling, "_cmds", lambda: fake)
    with pytest.raises(HandlerError):
        modeling.boolean_op({"a": "|a", "b": "|a", "op": "union", "new_name": "x"})
```

- [ ] **Step 2: Run to verify failure** — both suites; `boolean_op` does not exist.

- [ ] **Step 3: Implement** (append to `modeling.py`):

```python
BOOLEAN_OPS = {"union": 1, "difference": 2, "intersection": 3}


def _do_boolean(cmds, a_long: str, b_long: str, op: str, new_name: str) -> Dict[str, Any]:
    """Shared boolean core: polyCBoolOp + the golem-run cleanup discipline.

    Per-face shader assignment on boolean output silently no-ops and corrupts
    shading groups (redmine #577 req 1), so: delete history immediately, then
    collapse shading to one object-level SG (input A's material wins).
    """
    from . import meshcheck  # noqa: PLC0415 - keep module import cheap headless

    _, a_shape = naming.require_mesh(cmds, a_long)
    fallback_sg = meshcheck.first_sg(cmds, a_shape)

    result = cmds.polyCBoolOp(a_long, b_long, op=BOOLEAN_OPS[op], name=new_name)
    out = cmds.rename(result[0], new_name)
    out_long = _long(cmds, out)
    cmds.delete(out_long, constructionHistory=True)

    warnings: List[str] = []
    _, out_shape = naming.require_mesh(cmds, out_long)
    shading = meshcheck.ensure_object_shading(cmds, out_shape, fallback_sg)
    if shading["repaired"]:
        warnings.append(
            "shading collapsed to object-level %s (per-face assignment is "
            "unreliable on boolean output)" % shading["sg"]
        )
    stats = meshcheck.mesh_stats(out_long)
    if not stats["watertight"]:
        warnings.append(
            "result is not watertight (%d boundary, %d non-manifold edges); "
            "run maya_mesh_cleanup" % (stats["boundary_edges"], stats["nonmanifold_edges"])
        )
    ledger.forget(a_long)
    ledger.forget(b_long)
    ledger.record(cmds, out_long)
    return {
        "name": out_long,
        "tris": stats["tris"],
        "watertight": stats["watertight"],
        "warnings": warnings,
    }


def boolean_op(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    op = params.get("op")
    if op not in BOOLEAN_OPS:
        raise HandlerError(
            "unknown boolean op %r" % op,
            hint="valid ops: union, difference, intersection",
        )
    a_long = naming.require_mesh(cmds, str(params.get("a") or ""))[0]
    b_long = naming.require_mesh(cmds, str(params.get("b") or ""))[0]
    if a_long == b_long:
        raise HandlerError(
            "a and b are the same object", hint="pass two different meshes"
        )
    requested = params.get("new_name")
    if not isinstance(requested, str) or not requested.strip():
        raise HandlerError(
            "missing required param 'new_name'", hint="name for the result mesh"
        )
    from . import session  # noqa: PLC0415

    session.auto_checkpoint("boolean")
    return _do_boolean(cmds, a_long, b_long, op, naming.unique_name(cmds, requested))
```

- [ ] **Step 4: Register + tool + schema.** Handler: `"boolean_op": modeling.boolean_op`. Schema:

```python
class BooleanResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    tris: int
    watertight: bool
    warnings: List[str] = Field(default_factory=list)
```

Tool (in `server.py`; `BOOL_TIMEOUT_S = 120.0`):

```python
    @mcp.tool(
        title="Boolean operation",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
    )
    def maya_boolean_op(
        a: Annotated[str, Field(description="First mesh (kept material wins).")],
        b: Annotated[str, Field(description="Second mesh; both inputs are consumed.")],
        op: Annotated[Literal["union", "difference", "intersection"],
                      Field(description="difference = a minus b.")],
        new_name: Annotated[str, Field(min_length=1, description="Name for the result.")],
    ) -> BooleanResult:
        """Boolean two meshes. Auto-checkpoints first; deletes construction
        history and collapses shading to one object-level material (per-face
        shading does not survive booleans). Non-watertight results come back
        ok with a warning + cleanup hint."""
        return BooleanResult.model_validate(
            maya.request(
                "boolean_op", {"a": a, "b": b, "op": op, "new_name": new_name},
                timeout_s=BOOL_TIMEOUT_S,
            )
        )
```

- [ ] **Step 5: Run both suites; commit**

```bash
git add maya_plugin/handlers/modeling.py maya_plugin/maya_mcp_plugin.py src/maya_mcp/server.py src/maya_mcp/schemas.py tests/
git commit -m "feat(m1): boolean_op with auto-checkpoint, history delete, SG collapse, manifold check"
```

---

### Task 7: maya_etch_text — glyph carving in one call (#577 req 2)

The golem run needed 6 blind iterations to place the aleph cutter. One tool call must do: glyph → sized → oriented to the target FACE's normal frame → depth-forced (Type extrude attrs are unreliable — measure bbox, force via scale) → boolean difference → cleanup.

**Files:**
- Create: `maya_plugin/handlers/etch.py`
- Modify: `maya_plugin/maya_mcp_plugin.py`, `src/maya_mcp/server.py`, `src/maya_mcp/schemas.py`
- Test: `tests/test_etch_math.py` (pure math, headless), `tests/test_handlers_mayapy.py` (live pipeline; skips if the Type plugin cannot load headless)

**Interfaces:**
- Consumes: `modeling._do_boolean` (Task 6), `session.auto_checkpoint` (Task 3), `naming.require_mesh` (Task 2).
- Produces (pure, headless-testable): `etch.face_frame_transform(face_center, face_normal, glyph_bbox_min, glyph_bbox_max, width, depth) -> dict` with keys `scale` (xyz), `rotate` (Maya xyz euler deg aligning glyph +Z to the face normal — same convention as `capture.camera_placement`), `translate` (glyph center goes to the face center; cutter thickness 2*depth straddles the surface so the carve depth is exactly `depth`).
- Produces MCP tool: `maya_etch_text(mesh, text, face, width, depth, font, mirror, rotate_deg)`.

- [ ] **Step 1: Failing pure-math tests** — `tests/test_etch_math.py`:

```python
import math

from maya_plugin.handlers import etch

BBOX = ([-0.5, -1.0, 0.0], [0.5, 1.0, 0.25])  # raw glyph: 1 wide, 2 tall, 0.25 thick


def test_facing_plus_z_no_rotation():
    result = etch.face_frame_transform(
        face_center=[0, 3.4, 1.3], face_normal=[0, 0, 1],
        glyph_bbox_min=BBOX[0], glyph_bbox_max=BBOX[1],
        width=0.6, depth=0.1,
    )
    assert result["rotate"] == [0.0, 0.0, 0.0]
    sx, sy, sz = result["scale"]
    assert math.isclose(sx, 0.6, rel_tol=1e-6)          # 1.0 wide -> 0.6
    assert math.isclose(sy, 0.6, rel_tol=1e-6)          # uniform in-plane
    assert math.isclose(sz, 0.8, rel_tol=1e-6)          # 0.25 thick -> 2*depth
    assert result["translate"] == [0.0, 3.4, 1.3]


def test_tilted_plate_normal_matches_brow_math():
    # the golem brow plate: rx -18 => n = (0, sin18, cos18)
    n = [0.0, math.sin(math.radians(18)), math.cos(math.radians(18))]
    result = etch.face_frame_transform(
        face_center=[0, 3.46, 1.32], face_normal=n,
        glyph_bbox_min=BBOX[0], glyph_bbox_max=BBOX[1],
        width=1.0, depth=0.1,
    )
    assert math.isclose(result["rotate"][0], -18.0, abs_tol=1e-3)
    assert math.isclose(result["rotate"][1], 0.0, abs_tol=1e-3)


def test_normal_is_normalized_before_use():
    a = etch.face_frame_transform([0, 0, 0], [0, 0, 1], *BBOX, width=1, depth=0.1)
    b = etch.face_frame_transform([0, 0, 0], [0, 0, 7], *BBOX, width=1, depth=0.1)
    assert a == b


def test_degenerate_glyph_bbox_raises():
    import pytest

    from maya_plugin.dispatcher import HandlerError

    with pytest.raises(HandlerError):
        etch.face_frame_transform(
            [0, 0, 0], [0, 0, 1], [0, 0, 0], [0, 0, 0], width=1, depth=0.1
        )
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_etch_math.py -q`.

- [ ] **Step 3: Implement `maya_plugin/handlers/etch.py`:**

```python
"""etch_text: carve text/glyphs into a mesh face in one call (#577 req 2).

Golem-run lessons baked in: the Type node's extrude attrs are unreliable
(measure the raw bbox and force depth via scale); placement is computed in
the target face's actual normal frame from mesh data (plane math breaks on
polySmooth-bowed faces); boolean output needs the Task-6 SG cleanup; every
Type-network node this tool creates is deleted afterwards — zero orphans.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

from ..dispatcher import HandlerError
from . import naming

DEFAULT_WIDTH = 0.6
DEFAULT_DEPTH = 0.1
DEFAULT_FONT = "Arial"
_TYPE_NODE_TYPES = ("type", "typeExtrude", "vectorAdjust", "shellDeformer")


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


# ------------------------------------------------------------------ pure math


def face_frame_transform(
    face_center: List[float],
    face_normal: List[float],
    glyph_bbox_min: List[float],
    glyph_bbox_max: List[float],
    width: float,
    depth: float,
) -> Dict[str, List[float]]:
    """Scale/rotate/translate placing a raw +Z-facing glyph onto a face.

    Cutter thickness is forced to 2*depth and its center sits ON the face, so
    the boolean difference carves exactly `depth` into the surface regardless
    of what the Type node's extrude attrs actually produced.
    """
    size = [hi - lo for lo, hi in zip(glyph_bbox_min, glyph_bbox_max)]
    if min(size) <= 1e-9:
        raise HandlerError(
            "glyph bounding box is degenerate (%r)" % (size,),
            hint="the Type node produced no geometry; check the text/font",
        )
    length = math.sqrt(sum(n * n for n in face_normal))
    if length <= 1e-9:
        raise HandlerError("face normal is zero", hint="pick a non-degenerate face")
    nx, ny, nz = (n / length for n in face_normal)

    in_plane = width / size[0]
    scale = [in_plane, in_plane, (2.0 * depth) / size[2]]
    # Same convention as capture.camera_placement: pitch = -elevation,
    # yaw = azimuth (0 = +Z), no roll, Maya xyz rotate order.
    elevation = math.degrees(math.asin(max(-1.0, min(1.0, ny))))
    azimuth = math.degrees(math.atan2(nx, nz))
    rotate = [-elevation, azimuth, 0.0]
    return {"scale": scale, "rotate": rotate, "translate": list(face_center)}


# ------------------------------------------------------------------- handler


def _face_center_normal(mesh_long: str, face: int):
    import maya.api.OpenMaya as om  # noqa: PLC0415

    sel = om.MSelectionList()
    sel.add(mesh_long)
    dag = sel.getDagPath(0)
    it = om.MItMeshPolygon(dag)
    if face < 0 or face >= it.count():
        raise HandlerError(
            "face %d out of range (mesh has %d faces)" % (face, it.count()),
            hint="faces are 0-indexed; capture with wireframe_overlay to pick one",
        )
    it.setIndex(face)
    center = it.center(om.MSpace.kWorld)
    normal = it.getNormal(om.MSpace.kWorld)
    return [center.x, center.y, center.z], [normal.x, normal.y, normal.z]


def _create_glyph(cmds, text: str, font: str) -> str:
    if not cmds.loadPlugin("Type", quiet=True):
        if "type" not in (cmds.pluginInfo(query=True, listPlugins=True) or []):
            raise HandlerError(
                "the Type plugin is not available in this Maya",
                hint="etch needs Maya's Type tool; carve with maya_boolean_op "
                "and a custom cutter mesh instead",
            )
    import maya.mel as mel  # noqa: PLC0415

    before = set(cmds.ls(type="transform"))
    mel.eval("CreatePolygonType;")
    created = [t for t in cmds.ls(type="transform") if t not in before]
    if not created:
        raise HandlerError(
            "CreatePolygonType produced no transform",
            hint="the Type plugin misbehaved; retry or carve with maya_boolean_op",
        )
    glyph_tf = created[0]
    type_node = (cmds.ls(type="type") or [])[-1]
    hex_codes = " ".join("%X" % ord(ch) for ch in text)
    cmds.setAttr(type_node + ".textInput", hex_codes, type="string")
    cmds.setAttr(type_node + ".currentFont", font, type="string")
    cmds.setAttr(type_node + ".alignmentMode", 2)  # center
    try:
        cmds.setAttr(type_node + ".extrudeEnable", 1)
        cmds.setAttr(type_node + ".extrudeDistance", 0.1)
    except Exception:
        pass  # depth is forced via scale anyway
    cmds.refresh()
    return glyph_tf


def etch_text(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    from . import modeling, session  # noqa: PLC0415

    mesh_long, _ = naming.require_mesh(cmds, str(params.get("mesh") or ""))
    text = params.get("text")
    if not isinstance(text, str) or not text.strip():
        raise HandlerError(
            "missing required param 'text'",
            hint="pass the characters to carve, e.g. text='\\u05d0' for an aleph",
        )
    face = params.get("face")
    if not isinstance(face, int) or isinstance(face, bool):
        raise HandlerError(
            "missing required param 'face' (int face id)",
            hint="pick the face to carve into; capture with wireframe_overlay "
            "to identify face ids",
        )
    width = float(params.get("width") or DEFAULT_WIDTH)
    depth = float(params.get("depth") or DEFAULT_DEPTH)
    if width <= 0 or depth <= 0:
        raise HandlerError("width and depth must be positive", hint="sizes are in scene units")
    font = str(params.get("font") or DEFAULT_FONT)
    mirror = bool(params.get("mirror", False))
    rotate_deg = float(params.get("rotate_deg") or 0.0)

    center, normal = _face_center_normal(mesh_long, face)
    session.auto_checkpoint("etch")

    def _ls_safe(node_type: str) -> set:
        # unknown node types raise until the Type plugin has been loaded once
        try:
            return set(cmds.ls(type=node_type) or [])
        except Exception:
            return set()

    node_snapshot = {t: _ls_safe(t) for t in _TYPE_NODE_TYPES}
    glyph_tf = _create_glyph(cmds, text, font)
    try:
        bbox = cmds.exactWorldBoundingBox(glyph_tf)
        placement = face_frame_transform(center, normal, bbox[:3], bbox[3:], width, depth)
        scale = placement["scale"]
        if mirror:
            scale = [-scale[0], scale[1], scale[2]]
        cmds.xform(glyph_tf, scale=scale)
        cmds.xform(glyph_tf, rotation=placement["rotate"], worldSpace=True)
        if rotate_deg:
            cmds.rotate(rotate_deg, glyph_tf, z=True, objectSpace=True, relative=True)
        # after scaling, recenter the glyph bbox onto the face center
        bbox = cmds.exactWorldBoundingBox(glyph_tf)
        current = [(lo + hi) / 2.0 for lo, hi in zip(bbox[:3], bbox[3:])]
        offset = [t - c for t, c in zip(placement["translate"], current)]
        cmds.xform(glyph_tf, translation=offset, relative=True, worldSpace=True)
        cmds.delete(glyph_tf, constructionHistory=True)  # freeze type network out

        result = modeling._do_boolean(
            cmds, mesh_long, glyph_tf, "difference",
            naming.unique_name(cmds, str(params.get("new_name") or "") or
                               mesh_long.split("|")[-1] + "_etched"),
        )
    finally:
        # zero orphan history nodes: sweep anything the Type network left behind
        for node_type, before in node_snapshot.items():
            for node in _ls_safe(node_type) - before:
                try:
                    cmds.delete(node)
                except Exception:
                    pass
    result["carved_text"] = text
    return result
```

- [ ] **Step 4: Register + tool + mayapy test.** Handler: `"etch_text": etch.etch_text`. Tool (schema reuses `BooleanResult` plus `carved_text` — add `carved_text: Optional[str] = None` to `BooleanResult`):

```python
    @mcp.tool(
        title="Etch text into a face",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
    )
    def maya_etch_text(
        mesh: Annotated[str, Field(description="Target mesh (canonical long name).")],
        text: Annotated[str, Field(min_length=1, max_length=32, description=(
            "Characters to carve; Unicode ok (Hebrew renders in correct RTL "
            "visual order)."
        ))],
        face: Annotated[int, Field(ge=0, description=(
            "Face id to carve into; the glyph is oriented to this face's actual "
            "normal (works on smoothed/bowed faces)."
        ))],
        width: Annotated[float, Field(gt=0, description="Carve width, scene units.")] = 0.6,
        depth: Annotated[float, Field(gt=0, description="Recess depth, scene units.")] = 0.1,
        font: Annotated[str, Field(description="Font for the Type node.")] = "Arial",
        mirror: Annotated[bool, Field(description=(
            "Mirror the glyph horizontally (e.g. the golem's inverted-mirrored aleph)."
        ))] = False,
        rotate_deg: Annotated[float, Field(description=(
            "Extra in-plane rotation in degrees (180 = inverted)."
        ))] = 0.0,
        new_name: Annotated[Optional[str], Field(description=(
            "Name for the carved result; defaults to <mesh>_etched."
        ))] = None,
    ) -> BooleanResult:
        """Carve text into a mesh face in ONE call: glyph -> sized -> oriented
        to the face's normal frame -> depth-forced -> boolean difference ->
        cleanup. Auto-checkpoints first; leaves zero Type/history nodes behind."""
        return BooleanResult.model_validate(
            maya.request(
                "etch_text",
                {"mesh": mesh, "text": text, "face": face, "width": width,
                 "depth": depth, "font": font, "mirror": mirror,
                 "rotate_deg": rotate_deg, "new_name": new_name},
                timeout_s=BOOL_TIMEOUT_S,
            )
        )
```

mayapy test (append; Type plugin may not load in standalone — skip cleanly, the live smoke in Task 11 covers it):

```python
class TestEtchInMaya:
    def test_etch_carves_recess(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import etch

        if not cmds.loadPlugin("Type", quiet=True):
            pytest.skip("Type plugin unavailable in standalone")
        cmds.file(rename=str(tmp_path / "etch.ma"))
        cmds.polyCube(name="plate", w=2, h=1, d=0.3)
        before = cmds.polyEvaluate("plate", triangle=True)
        result = etch.etch_text(
            {"mesh": "|plate", "text": "א", "face": 0, "width": 0.8,
             "depth": 0.05, "mirror": True, "rotate_deg": 180.0}
        )
        assert result["tris"] > before
        # zero orphans from the Type network
        assert cmds.ls(type="type") == []
        assert cmds.ls(type="typeExtrude") == []
```

- [ ] **Step 5: Run both suites; commit**

```bash
git add maya_plugin/handlers/etch.py maya_plugin/maya_mcp_plugin.py src/maya_mcp/server.py src/maya_mcp/schemas.py tests/
git commit -m "feat(m1): etch_text - one-call glyph carve with face-frame placement"
```

---

### Task 8: sculpt_ops — tagged-union sculpting incl. displace_noise (#577 req 3)

`displace_noise` ports the golem run's `displace_chunks.py` — the single highest-value quality fix of that session (killed the untouched-primitive read on all 14 chunks in one pass). The noise math is pure and headless-tested; vertex application uses OpenMaya (design-doc §9 open question 5: decided — OpenMaya weighted offsets, not softSelect, because it is deterministic, selection-free, and needs no global state restore).

**Files:**
- Create: `maya_plugin/handlers/sculpt_math.py` (pure), `maya_plugin/handlers/sculpt.py`
- Modify: `maya_plugin/maya_mcp_plugin.py`, `src/maya_mcp/server.py`, `src/maya_mcp/schemas.py`
- Test: `tests/test_sculpt_math.py` (headless), `tests/test_handlers_mayapy.py` (extend)

**Interfaces:**
- Produces (pure): `sculpt_math.vnoise(x, y, z) -> float` in [0,1] (hash-based trilinear value noise, verbatim port); `sculpt_math.fbm(x, y, z, octaves=2) -> float` signed, octave 2 matching the run's `freq*2.3, +7 offset, *0.45 amplitude`; `sculpt_math.falloff_weight(dist, radius, falloff) -> float` (`"smooth"` = smoothstep, `"linear"`).
- Produces (handler → command): `sculpt_ops`. Ops applied in order; abort-and-report on first failure via HandlerError listing which ops landed (they stay applied — the whole call is one undo chunk, so `maya_undo` reverts all of them).
- Produces MCP tool: `maya_sculpt_ops(mesh, ops)` where each op is a dict with an `op` tag: `soft_move {center|vertex_id, radius, falloff, delta}`, `inflate_region {center, radius, amount}`, `displace_noise {amp, freq, octaves, soften_angle}`, `smooth {divisions}`, `extrude_faces {faces, distance, keep_together}`, `bevel_edges {edges, width, segments}`, `crease_edges {edges, amount}`, `bridge {edges_a, edges_b}`.

- [ ] **Step 1: Failing pure-math tests** — `tests/test_sculpt_math.py`:

```python
import math

from maya_plugin.handlers import sculpt_math


def test_vnoise_deterministic_and_bounded():
    samples = [
        sculpt_math.vnoise(x * 0.7, x * 0.3, x * 1.1) for x in range(50)
    ]
    assert samples == [
        sculpt_math.vnoise(x * 0.7, x * 0.3, x * 1.1) for x in range(50)
    ]
    assert all(0.0 <= s <= 1.0 for s in samples)
    assert max(samples) - min(samples) > 0.3  # actually varies


def test_fbm_signed_and_octaves_add_detail():
    one = [sculpt_math.fbm(x * 0.5, 0.0, 0.0, octaves=1) for x in range(40)]
    two = [sculpt_math.fbm(x * 0.5, 0.0, 0.0, octaves=2) for x in range(40)]
    assert any(v < 0 for v in two) and any(v > 0 for v in two)
    assert one != two


def test_falloff_weight_edges():
    assert sculpt_math.falloff_weight(0.0, 2.0, "smooth") == 1.0
    assert sculpt_math.falloff_weight(2.0, 2.0, "smooth") == 0.0
    assert sculpt_math.falloff_weight(3.0, 2.0, "linear") == 0.0
    assert math.isclose(sculpt_math.falloff_weight(1.0, 2.0, "linear"), 0.5)
    mid_smooth = sculpt_math.falloff_weight(1.0, 2.0, "smooth")
    assert math.isclose(mid_smooth, 0.5)  # smoothstep(0.5) = 0.5
```

- [ ] **Step 2: Verify failure, then implement `sculpt_math.py`:**

```python
"""Pure sculpt math: value noise (golem-run displace port) + falloffs."""

from __future__ import annotations

import math


def vnoise(x: float, y: float, z: float) -> float:
    """Cheap deterministic 3D value noise, trilinear interpolation, [0,1]."""

    def h(ix: int, iy: int, iz: int) -> float:
        n = (ix * 73856093) ^ (iy * 19349663) ^ (iz * 83492791)
        n = (n ^ (n >> 13)) * 1274126177
        return ((n ^ (n >> 16)) & 0xFFFF) / 65535.0

    ix, iy, iz = math.floor(x), math.floor(y), math.floor(z)
    fx, fy, fz = x - ix, y - iy, z - iz
    ix, iy, iz = int(ix), int(iy), int(iz)

    def s(t: float) -> float:
        return t * t * (3 - 2 * t)

    fx, fy, fz = s(fx), s(fy), s(fz)
    c = [[[h(ix + a, iy + b, iz + cc) for cc in (0, 1)] for b in (0, 1)] for a in (0, 1)]

    def lerp(a: float, b: float, t: float) -> float:
        return a + (b - a) * t

    return lerp(
        lerp(lerp(c[0][0][0], c[0][0][1], fz), lerp(c[0][1][0], c[0][1][1], fz), fy),
        lerp(lerp(c[1][0][0], c[1][0][1], fz), lerp(c[1][1][0], c[1][1][1], fz), fy),
        fx,
    )


def fbm(x: float, y: float, z: float, octaves: int = 2) -> float:
    """Signed fractal value noise. Octave 2 with amp 0.45 / lacunarity 2.3 /
    +7 offset reproduces the golem run's two-octave recipe exactly."""
    total, amp, freq, offset = 0.0, 1.0, 1.0, 0.0
    for _ in range(max(1, octaves)):
        total += (vnoise(x * freq + offset, y * freq, z * freq) - 0.5) * 2.0 * amp
        amp *= 0.45
        freq *= 2.3
        offset += 7.0
    return total


def falloff_weight(dist: float, radius: float, falloff: str) -> float:
    if radius <= 0.0 or dist >= radius:
        return 0.0
    t = 1.0 - dist / radius
    if falloff == "linear":
        return t
    return t * t * (3 - 2 * t)  # smoothstep
```

Run: `uv run pytest tests/test_sculpt_math.py -q` → PASS.

- [ ] **Step 3: Implement `maya_plugin/handlers/sculpt.py`:**

```python
"""sculpt_ops: the golem-maker (§5.3). Ops apply in order; the first failure
aborts with a report of what landed (one undo chunk — maya_undo reverts all)."""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from ..dispatcher import HandlerError
from . import naming, sculpt_math

MAX_OPS = 20
FALLOFFS = ("smooth", "linear")


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _om_mesh(mesh_long: str):
    import maya.api.OpenMaya as om  # noqa: PLC0415

    sel = om.MSelectionList()
    sel.add(mesh_long)
    dag = sel.getDagPath(0)
    return om, om.MFnMesh(dag)


def _num(op: Dict[str, Any], key: str, default=None, positive=False) -> float:
    value = op.get(key, default)
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HandlerError(
            "op %r needs numeric %r" % (op.get("op"), key),
            hint="e.g. %s=1.5" % key,
        )
    if positive and value <= 0:
        raise HandlerError("%r must be positive" % key, hint="got %r" % value)
    return float(value)


def _resolve_center(om, fn, op: Dict[str, Any]):
    if "vertex_id" in op:
        vid = op["vertex_id"]
        if not isinstance(vid, int) or not (0 <= vid < fn.numVertices):
            raise HandlerError(
                "vertex_id %r out of range (mesh has %d verts)" % (vid, fn.numVertices),
                hint="vertex ids are 0-indexed",
            )
        p = fn.getPoint(vid, om.MSpace.kWorld)
        return [p.x, p.y, p.z]
    center = op.get("center")
    if (
        not isinstance(center, (list, tuple)) or len(center) != 3
        or not all(isinstance(v, (int, float)) for v in center)
    ):
        raise HandlerError(
            "op %r needs center=[x,y,z] or vertex_id" % op.get("op"),
            hint="world-space coordinates",
        )
    return [float(v) for v in center]


def _weighted_offset(mesh_long: str, op: Dict[str, Any], along_normal: bool) -> None:
    om, fn = _om_mesh(mesh_long)
    center = _resolve_center(om, fn, op)
    radius = _num(op, "radius", positive=True)
    falloff = op.get("falloff", "smooth")
    if falloff not in FALLOFFS:
        raise HandlerError(
            "unknown falloff %r" % falloff, hint="valid: smooth, linear"
        )
    if along_normal:
        amount = _num(op, "amount")
        normals = fn.getVertexNormals(False, om.MSpace.kWorld)
    else:
        delta = op.get("delta")
        if not isinstance(delta, (list, tuple)) or len(delta) != 3:
            raise HandlerError(
                "soft_move needs delta=[dx,dy,dz]", hint="world-space offset"
            )
        delta = [float(v) for v in delta]
    points = fn.getPoints(om.MSpace.kWorld)
    out = om.MPointArray()
    c = om.MPoint(*center)
    for i in range(len(points)):
        p = points[i]
        w = sculpt_math.falloff_weight(p.distanceTo(c), radius, falloff)
        if along_normal:
            n = normals[i]
            out.append(om.MPoint(p.x + n.x * amount * w, p.y + n.y * amount * w,
                                 p.z + n.z * amount * w))
        else:
            out.append(om.MPoint(p.x + delta[0] * w, p.y + delta[1] * w,
                                 p.z + delta[2] * w))
    fn.setPoints(out, om.MSpace.kWorld)


def _op_soft_move(cmds, mesh_long: str, op: Dict[str, Any]) -> None:
    _weighted_offset(mesh_long, op, along_normal=False)


def _op_inflate_region(cmds, mesh_long: str, op: Dict[str, Any]) -> None:
    _weighted_offset(mesh_long, op, along_normal=True)


def _op_displace_noise(cmds, mesh_long: str, op: Dict[str, Any]) -> None:
    amp = _num(op, "amp", 0.05, positive=True)
    freq = _num(op, "freq", 2.6, positive=True)
    octaves = op.get("octaves", 2)
    if not isinstance(octaves, int) or not (1 <= octaves <= 6):
        raise HandlerError("octaves must be an integer 1..6", hint="2 matches the golem recipe")
    om, fn = _om_mesh(mesh_long)
    points = fn.getPoints(om.MSpace.kWorld)
    normals = fn.getVertexNormals(False, om.MSpace.kWorld)
    out = om.MPointArray()
    for i in range(len(points)):
        p = points[i]
        d = sculpt_math.fbm(p.x * freq, p.y * freq, p.z * freq, octaves) * amp
        n = normals[i]
        out.append(om.MPoint(p.x + n.x * d, p.y + n.y * d, p.z + n.z * d))
    fn.setPoints(out, om.MSpace.kWorld)
    soften = op.get("soften_angle")
    if soften is not None:
        cmds.polySoftEdge(mesh_long, angle=float(soften), constructionHistory=False)


def _components(mesh_long: str, spec: Any, kind: str, key: str) -> str:
    if not isinstance(spec, str) or not spec.startswith(kind + "["):
        raise HandlerError(
            "%s must be a component string like '%s[3:7]'" % (key, kind),
            hint="got %r" % (spec,),
        )
    return "%s.%s" % (mesh_long, spec)


def _op_smooth(cmds, mesh_long: str, op: Dict[str, Any]) -> None:
    divisions = op.get("divisions", 1)
    if not isinstance(divisions, int) or not (1 <= divisions <= 3):
        raise HandlerError("divisions must be 1..3", hint="each level quadruples polycount")
    cmds.polySmooth(mesh_long, divisions=divisions, constructionHistory=False)


def _op_extrude_faces(cmds, mesh_long: str, op: Dict[str, Any]) -> None:
    faces = _components(mesh_long, op.get("faces"), "f", "faces")
    cmds.polyExtrudeFacet(
        faces, localTranslateZ=_num(op, "distance"),
        keepFacesTogether=bool(op.get("keep_together", True)),
        constructionHistory=False,
    )


def _op_bevel_edges(cmds, mesh_long: str, op: Dict[str, Any]) -> None:
    edges = _components(mesh_long, op.get("edges"), "e", "edges")
    segments = op.get("segments", 1)
    if not isinstance(segments, int) or not (1 <= segments <= 10):
        raise HandlerError("segments must be 1..10", hint="got %r" % (segments,))
    cmds.polyBevel3(
        edges, offset=_num(op, "width", positive=True), segments=segments,
        chamfer=True, constructionHistory=False,
    )


def _op_crease_edges(cmds, mesh_long: str, op: Dict[str, Any]) -> None:
    edges = _components(mesh_long, op.get("edges"), "e", "edges")
    amount = _num(op, "amount")
    if not (0.0 <= amount <= 10.0):
        raise HandlerError("amount must be 0..10", hint="stone-plate joints read well near 2-4")
    cmds.polyCrease(edges, value=amount)


def _op_bridge(cmds, mesh_long: str, op: Dict[str, Any]) -> None:
    edges_a = _components(mesh_long, op.get("edges_a"), "e", "edges_a")
    edges_b = _components(mesh_long, op.get("edges_b"), "e", "edges_b")
    cmds.select(edges_a, edges_b, replace=True)
    try:
        cmds.polyBridgeEdge(constructionHistory=False)
    finally:
        cmds.select(clear=True)


_OPS: Dict[str, Callable] = {
    "soft_move": _op_soft_move,
    "inflate_region": _op_inflate_region,
    "displace_noise": _op_displace_noise,
    "smooth": _op_smooth,
    "extrude_faces": _op_extrude_faces,
    "bevel_edges": _op_bevel_edges,
    "crease_edges": _op_crease_edges,
    "bridge": _op_bridge,
}


def sculpt_ops(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    mesh_long, _ = naming.require_mesh(cmds, str(params.get("mesh") or ""))
    ops = params.get("ops")
    if not isinstance(ops, list) or not ops or len(ops) > MAX_OPS:
        raise HandlerError(
            "ops must be a list of 1..%d operations" % MAX_OPS,
            hint='e.g. ops=[{"op": "displace_noise", "amp": 0.06, "freq": 2.6}]',
        )
    applied: List[str] = []
    for index, op in enumerate(ops):
        kind = op.get("op") if isinstance(op, dict) else None
        fn = _OPS.get(kind) if isinstance(kind, str) else None
        if fn is None:
            raise HandlerError(
                "op %d: unknown op %r; ops %s were already applied"
                % (index, kind, applied or "none"),
                hint="valid ops: %s. Applied ops stay; maya_undo(1) reverts "
                "this whole call" % ", ".join(sorted(_OPS)),
            )
        try:
            fn(cmds, mesh_long, op)
        except HandlerError as exc:
            raise HandlerError(
                "op %d (%s) failed: %s; ops %s were already applied"
                % (index, kind, exc, applied or "none"),
                hint=(exc.hint or "") + " — applied ops stay; maya_undo(1) "
                "reverts this whole call",
            ) from None
        applied.append(kind)
    tris = cmds.polyEvaluate(mesh_long, triangle=True)
    return {"applied": len(applied), "ops": applied, "tris": tris, "warnings": []}
```

- [ ] **Step 4: Register (`"sculpt_ops": sculpt.sculpt_ops`) + schema + tool:**

```python
class SculptResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    applied: int
    ops: List[str]
    tris: int
    warnings: List[str] = Field(default_factory=list)
```

```python
    @mcp.tool(
        title="Sculpt operations",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
    )
    def maya_sculpt_ops(
        mesh: Annotated[str, Field(description="Target mesh (canonical long name).")],
        ops: Annotated[List[dict], Field(min_length=1, max_length=20, description=(
            'Applied in order; aborts on first failure reporting what landed. '
            'Tagged by "op": '
            'soft_move {center:[x,y,z]|vertex_id, radius, falloff:"smooth"|"linear", delta:[x,y,z]} '
            '— THE organic tool, weighted vertex offsets; '
            'inflate_region {center, radius, amount} — push along normals; '
            'displace_noise {amp:0.05, freq:2.6, octaves:2, soften_angle:55?} '
            '— value-noise rock-surface breakup, kills the untouched-primitive look; '
            'smooth {divisions:1..3}; '
            'extrude_faces {faces:"f[120:135]", distance, keep_together:true}; '
            'bevel_edges {edges:"e[3:7]", width, segments:1..10}; '
            'crease_edges {edges, amount:0..10} — stone-plate joints; '
            'bridge {edges_a, edges_b}.'
        ))],
    ) -> SculptResult:
        """Apply sculpt ops in order to one mesh. The whole call is ONE undo
        step; on partial failure, applied ops stay and maya_undo(1) reverts."""
        return SculptResult.model_validate(
            maya.request(
                "sculpt_ops", {"mesh": mesh, "ops": ops}, timeout_s=BOOL_TIMEOUT_S
            )
        )
```

- [ ] **Step 5: mayapy tests** (append):

```python
class TestSculptInMaya:
    def test_displace_noise_moves_verts_and_keeps_count(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import sculpt

        cmds.polySphere(name="rock", subdivisionsAxis=12, subdivisionsHeight=12)
        before = cmds.xform("rock.vtx[5]", q=True, ws=True, t=True)
        verts = cmds.polyEvaluate("rock", vertex=True)
        result = sculpt.sculpt_ops(
            {"mesh": "|rock",
             "ops": [{"op": "displace_noise", "amp": 0.08, "freq": 2.6,
                      "octaves": 2, "soften_angle": 55}]}
        )
        assert result["applied"] == 1
        assert cmds.polyEvaluate("rock", vertex=True) == verts
        assert cmds.xform("rock.vtx[5]", q=True, ws=True, t=True) != before

    def test_soft_move_is_local(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import sculpt

        cmds.polyPlane(name="pad", sx=10, sy=10, w=10, h=10)
        far_before = cmds.xform("pad.vtx[0]", q=True, ws=True, t=True)
        sculpt.sculpt_ops(
            {"mesh": "|pad",
             "ops": [{"op": "soft_move", "center": [0, 0, 0], "radius": 2.0,
                      "falloff": "smooth", "delta": [0, 1, 0]}]}
        )
        center_y = cmds.xform("pad.vtx[60]", q=True, ws=True, t=True)[1]
        assert center_y > 0.5  # lifted
        assert cmds.xform("pad.vtx[0]", q=True, ws=True, t=True) == far_before

    def test_abort_and_report_lists_applied(self):
        import pytest as _pytest

        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import sculpt

        cmds.polyCube(name="ar_cube")
        with _pytest.raises(HandlerError) as exc:
            sculpt.sculpt_ops(
                {"mesh": "|ar_cube",
                 "ops": [{"op": "smooth", "divisions": 1},
                         {"op": "extrude_faces", "faces": "NOT_A_COMPONENT",
                          "distance": 1.0}]}
            )
        assert "smooth" in str(exc.value)  # reports what landed
```

- [ ] **Step 6: Run both suites; commit**

```bash
git add maya_plugin/handlers/sculpt_math.py maya_plugin/handlers/sculpt.py maya_plugin/maya_mcp_plugin.py src/maya_mcp/server.py src/maya_mcp/schemas.py tests/
git commit -m "feat(m1): sculpt_ops - weighted offsets, displace_noise port, topology ops"
```

---

### Task 9: deform, remesh_retopo, mesh_cleanup

**Files:**
- Modify: `maya_plugin/handlers/sculpt.py` (add `deform`), `maya_plugin/handlers/modeling.py` (add `remesh_retopo`, `mesh_cleanup`)
- Modify: `maya_plugin/maya_mcp_plugin.py`, `src/maya_mcp/server.py`, `src/maya_mcp/schemas.py`
- Test: `tests/test_handlers_mayapy.py` (extend), `tests/test_modeling.py` (validation)

**Interfaces:**
- Produces (handlers): `deform`, `remesh_retopo`, `mesh_cleanup`.
- Produces (MCP tools): `maya_deform(mesh, deformer, params, delete_history_after)`, `maya_remesh_retopo(mesh, target_polycount, keep_original)`, `maya_mesh_cleanup(mesh, merge_verts_threshold, delete_history, freeze_transforms, conform_normals)`.

Implementation notes (complete behavior spec):

`deform` (in sculpt.py): `deformer` one of `bend|lattice|squash|twist|sculpt`. Non-lattice use `cmds.nonLinear(mesh_long, type=deformer)`; lattice uses `cmds.lattice(mesh_long, divisions=params.get("divisions", [2,5,2]), objectCentered=True, ldivisions=...)`. Whitelist `params` per type — bend/squash/twist: `curvature`, `lowBound`, `highBound`, `factor`, `startAngle`, `endAngle`, plus `rotate`/`translate` applied to the deformer handle via `cmds.xform`; reject unknown keys with a hint listing the whitelist. Returns `{"deformer_nodes": [...long names...], "warnings": []}` so the LLM can tweak attrs via `maya_execute_python`. `delete_history_after=True` → `cmds.delete(mesh_long, constructionHistory=True)` (bakes the deformation; deformer nodes are consumed) and returns `{"deformer_nodes": [], "baked": True}`.

`remesh_retopo` (in modeling.py): `session.auto_checkpoint("remesh")` first. `keep_original=True` (default) → duplicate the mesh to `<name>_orig`, hide it (`visibility=False`), operate on the original name. Feature-detect in order and record which ran: `polyRetopo(mesh, targetFaceCount=target)` if `hasattr(cmds, "polyRetopo")` and it does not raise; else `polyRemesh(mesh)`; else `polyReduce(mesh, percentage=...)` computed from current/target face counts. Delete history after. Return `{"name", "tris", "method": "polyRetopo"|"polyRemesh"|"polyReduce", "warnings"}` — a fallback adds a warning naming what was unavailable (§6 compatibility: degrade with a reported fallback rather than failing).

`mesh_cleanup` (in modeling.py): capture `meshcheck.mesh_stats` before; then in order: `cmds.polyMergeVertex(mesh_long, distance=merge_verts_threshold)` (default 0.001), `conform_normals=True` → `cmds.polyNormal(mesh_long, normalMode=2, constructionHistory=False)`, `freeze_transforms=True` → `cmds.makeIdentity(mesh_long, apply=True, translate=True, rotate=True, scale=True)` + `ledger.record` after (frozen transform is a tool write), `delete_history=True` → `cmds.delete(mesh_long, constructionHistory=True)`. Return `{"name", "before": stats, "after": stats, "warnings"}`.

- [ ] **Step 1: Failing mayapy tests** (append; complete):

```python
class TestDeformRemeshCleanupInMaya:
    def test_bend_deformer_created_and_baked(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import sculpt

        cmds.polyCylinder(name="col", sx=8, sy=12, height=6)
        result = sculpt.deform(
            {"mesh": "|col", "deformer": "bend", "params": {"curvature": 45}}
        )
        assert result["deformer_nodes"]
        baked = sculpt.deform(
            {"mesh": "|col", "deformer": "bend", "params": {"curvature": -20},
             "delete_history_after": True}
        )
        assert baked["baked"] is True
        shape = cmds.listRelatives("|col", shapes=True, fullPath=True)[0]
        assert cmds.listHistory(shape) == [shape]

    def test_deform_rejects_unknown_param(self):
        import pytest as _pytest

        import maya.cmds as cmds

        from maya_plugin.dispatcher import HandlerError
        from maya_plugin.handlers import sculpt

        cmds.polyCube(name="dp_cube")
        with _pytest.raises(HandlerError) as exc:
            sculpt.deform(
                {"mesh": "|dp_cube", "deformer": "bend",
                 "params": {"wobble": 3}}
            )
        assert "curvature" in exc.value.hint  # hint lists the whitelist

    def test_remesh_reports_method_and_keeps_original(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        cmds.file(rename=str(tmp_path / "remesh.ma"))
        cmds.polySphere(name="blob", subdivisionsAxis=40, subdivisionsHeight=40)
        result = modeling.remesh_retopo(
            {"mesh": "|blob", "target_polycount": 400, "keep_original": True}
        )
        assert result["method"] in ("polyRetopo", "polyRemesh", "polyReduce")
        assert cmds.objExists("blob_orig")
        assert cmds.getAttr("blob_orig.visibility") is False

    def test_cleanup_reports_before_after(self):
        import maya.cmds as cmds

        from maya_plugin.handlers import modeling

        cmds.polyCube(name="dirty")
        cmds.xform("dirty", t=(3, 1, 0), ro=(10, 20, 30))
        result = modeling.mesh_cleanup({"mesh": "|dirty"})
        assert result["before"]["tris"] == result["after"]["tris"] == 12
        # frozen: transform is identity now
        assert cmds.xform("dirty", q=True, ws=True, t=True) == [0.0, 0.0, 0.0]
```

- [ ] **Step 2: Implement per the notes above.** Complete `deform` skeleton (sculpt.py):

```python
DEFORMER_WHITELIST = {
    "bend": {"curvature", "lowBound", "highBound", "rotate", "translate"},
    "squash": {"factor", "lowBound", "highBound", "rotate", "translate"},
    "twist": {"startAngle", "endAngle", "lowBound", "highBound", "rotate", "translate"},
    "sculpt": {"maxDisplacement", "dropoffDistance", "translate", "rotate"},
    "lattice": {"divisions", "translate", "rotate"},
}


def deform(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    mesh_long, _ = naming.require_mesh(cmds, str(params.get("mesh") or ""))
    deformer = params.get("deformer")
    if deformer not in DEFORMER_WHITELIST:
        raise HandlerError(
            "unknown deformer %r" % deformer,
            hint="valid: %s" % ", ".join(sorted(DEFORMER_WHITELIST)),
        )
    dparams = params.get("params") or {}
    unknown = set(dparams) - DEFORMER_WHITELIST[deformer]
    if unknown:
        raise HandlerError(
            "unknown params for %s: %s" % (deformer, ", ".join(sorted(unknown))),
            hint="valid params: %s" % ", ".join(sorted(DEFORMER_WHITELIST[deformer])),
        )
    handle_xform = {k: dparams.pop(k) for k in ("translate", "rotate") if k in dparams}
    if deformer == "lattice":
        divisions = dparams.get("divisions", [2, 5, 2])
        nodes = cmds.lattice(
            mesh_long, divisions=divisions, objectCentered=True
        )
    else:
        nodes = cmds.nonLinear(mesh_long, type=deformer, **dparams)
    handle = nodes[-1]
    if "translate" in handle_xform:
        cmds.xform(handle, translation=handle_xform["translate"], worldSpace=True)
    if "rotate" in handle_xform:
        cmds.xform(handle, rotation=handle_xform["rotate"], worldSpace=True)
    if params.get("delete_history_after"):
        cmds.delete(mesh_long, constructionHistory=True)
        return {"deformer_nodes": [], "baked": True, "warnings": []}
    long_nodes = [(cmds.ls(n, long=True) or [n])[0] for n in nodes]
    return {"deformer_nodes": long_nodes, "baked": False, "warnings": []}
```

`remesh_retopo` and `mesh_cleanup` follow the implementation notes verbatim; write them in `modeling.py` with the same validation style as `boolean_op` (require_mesh, positive-int `target_polycount` with a 100..200000 range check, threshold `0 < merge_verts_threshold <= 1.0`).

- [ ] **Step 3: Register handlers** (`deform`, `remesh_retopo`, `mesh_cleanup`), add schemas:

```python
class DeformResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    deformer_nodes: List[str]
    baked: bool = False
    warnings: List[str] = Field(default_factory=list)


class RemeshResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    tris: int
    method: str = Field(description="Which path ran: polyRetopo, polyRemesh, or polyReduce.")
    warnings: List[str] = Field(default_factory=list)


class MeshStats(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tris: int
    verts: int
    faces: int
    boundary_edges: int
    nonmanifold_edges: int
    watertight: bool


class CleanupResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    before: MeshStats
    after: MeshStats
    warnings: List[str] = Field(default_factory=list)
```

and three thin tools following the established pattern (`maya_deform` destructive_hint=True forwarding `{mesh, deformer, params, delete_history_after}`; `maya_remesh_retopo` destructive_hint=True, `target_polycount` `Field(ge=100, le=200000)`, docstring noting the auto-checkpoint and reported fallback path; `maya_mesh_cleanup` destructive_hint=False, defaults `merge_verts_threshold=0.001`, `delete_history=True`, `freeze_transforms=True`, `conform_normals=True`; all `timeout_s=BOOL_TIMEOUT_S`).

- [ ] **Step 4: Run both suites; commit**

```bash
git add maya_plugin/handlers/sculpt.py maya_plugin/handlers/modeling.py maya_plugin/maya_mcp_plugin.py src/maya_mcp/server.py src/maya_mcp/schemas.py tests/
git commit -m "feat(m1): deform, remesh_retopo with reported fallback, mesh_cleanup"
```

---

### Task 10: Viewport + camera discipline (#577 req 4a/4b) and capture icon-hiding

Golem-run pain: displayLights/icon visibility/background drifted constantly; light icons and place3dTexture manipulators render into playblasts; capture angle "current" silently used a stale turntable camera twice.

**Files:**
- Create: `maya_plugin/handlers/viewport.py`
- Modify: `maya_plugin/handlers/capture.py` (icon-hiding during capture; camera name in results)
- Modify: `maya_plugin/maya_mcp_plugin.py`, `src/maya_mcp/server.py`, `src/maya_mcp/schemas.py`
- Test: `tests/test_viewport.py` (headless: pure look_at math + fake-cmds orchestration), `tests/test_capture.py` (extend), `tests/test_handlers_mayapy.py` (arg-marshaling only; capture needs a GUI)

**Interfaces:**
- Produces (pure): `viewport.look_at_rotation(position, target) -> [rx, ry, rz]` — Maya xyz euler pointing a camera at `position` toward `target`; same convention as `capture.camera_placement` (pitch = −elevation, yaw = azimuth with 0 = +Z, roll 0).
- Produces (handlers): `set_viewport`, `set_camera`.
- Produces (MCP tools): `maya_set_viewport(...)` — every param optional; only provided ones change; ALWAYS returns the full resulting panel state (so a bare call is the state query); `maya_set_camera(camera, position, look_at, focal_length, set_active)`.
- Capture change: `camera_positions[i]` gains a `"camera"` key (long name of the camera used) so a stale "current" camera is visible instead of silent.

- [ ] **Step 1: Failing headless tests** — `tests/test_viewport.py`:

```python
import math

from maya_plugin.handlers import viewport


def test_look_at_straight_down_z():
    # camera at +Z looking back at origin: no rotation
    assert viewport.look_at_rotation([0, 0, 10], [0, 0, 0]) == [0.0, 0.0, 0.0]


def test_look_at_from_above():
    rx, ry, rz = viewport.look_at_rotation([0, 10, 0], [0, 0, 0])
    assert math.isclose(rx, -90.0, abs_tol=1e-6)
    assert rz == 0.0


def test_look_at_three_quarter_matches_capture_convention():
    # 45 deg azimuth, ~28 elevation — the default persp orientation
    el, az = math.radians(27.938), math.radians(45.0)
    pos = [10 * math.cos(el) * math.sin(az), 10 * math.sin(el),
           10 * math.cos(el) * math.cos(az)]
    rx, ry, rz = viewport.look_at_rotation(pos, [0, 0, 0])
    assert math.isclose(rx, -27.938, abs_tol=1e-3)
    assert math.isclose(ry, 45.0, abs_tol=1e-3)


def test_look_at_degenerate_distance_raises():
    import pytest

    from maya_plugin.dispatcher import HandlerError

    with pytest.raises(HandlerError):
        viewport.look_at_rotation([1, 2, 3], [1, 2, 3])
```

Extend `tests/test_capture.py` (following its existing fake pattern): assert `_capture_one`'s modelEditor edit kwargs now include `lights=False, cameras=False, locators=False, manipulators=False, textures=False`, that `_PanelState` snapshots and restores those five flags, and that each `camera_positions` entry carries a `"camera"` key.

- [ ] **Step 2: Implement `maya_plugin/handlers/viewport.py`:**

```python
"""Persistent viewport/camera discipline (#577 req 4a/4b).

Unlike capture (which restores everything), these handlers make DELIBERATE
persistent changes: the LLM sets up its working view once instead of fighting
drifted panel state every capture. set_viewport doubles as the state query —
call it with no changes to read the current panel configuration.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from ..dispatcher import HandlerError
from . import naming
from .capture import _find_model_panel

DEFAULT_CAMERA = "mcpCam"
_EDITOR_FLAGS = {
    # param name -> modelEditor flag
    "show_grid": "grid",
    "show_light_icons": "lights",
    "show_camera_icons": "cameras",
    "show_locators": "locators",
    "show_manipulators": "manipulators",
    "show_texture_placements": "textures",
    "wireframe_on_shaded": "wireframeOnShaded",
}
_DISPLAY_LIGHTS = ("default", "all", "active", "flat", "none")


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def look_at_rotation(position: List[float], target: List[float]) -> List[float]:
    """Maya xyz euler (deg) for a camera at `position` looking at `target`.

    Convention matches capture.camera_placement: pitch = -elevation,
    yaw = azimuth (0 = +Z), no roll.
    """
    v = [p - t for p, t in zip(position, target)]  # target -> position offset
    length = math.sqrt(sum(c * c for c in v))
    if length <= 1e-9:
        raise HandlerError(
            "camera position and look_at coincide",
            hint="separate them; the camera needs a viewing direction",
        )
    elevation = math.degrees(math.asin(v[1] / length))
    azimuth = math.degrees(math.atan2(v[0], v[2]))
    return [-elevation, azimuth, 0.0]


def set_viewport(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    panel = _find_model_panel(cmds)
    edits: Dict[str, Any] = {}
    for param, flag in _EDITOR_FLAGS.items():
        value = params.get(param)
        if value is not None:
            edits[flag] = bool(value)
    display_lights = params.get("display_lights")
    if display_lights is not None:
        if display_lights not in _DISPLAY_LIGHTS:
            raise HandlerError(
                "unknown display_lights %r" % display_lights,
                hint="valid: %s" % ", ".join(_DISPLAY_LIGHTS),
            )
        edits["displayLights"] = display_lights
    if edits:
        cmds.modelEditor(panel, edit=True, **edits)

    state = {"panel": panel}
    for param, flag in _EDITOR_FLAGS.items():
        state[param] = bool(cmds.modelEditor(panel, query=True, **{flag: True}))
    state["display_lights"] = cmds.modelEditor(panel, query=True, displayLights=True)
    state["camera"] = cmds.modelPanel(panel, query=True, camera=True)
    return state


def set_camera(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    name = str(params.get("camera") or DEFAULT_CAMERA)
    warnings: List[str] = []
    if cmds.objExists(name):
        cam = naming.require_object(cmds, name)
    else:
        cam = cmds.camera(name=name)[0]
        cam = (cmds.ls(cam, long=True) or [cam])[0]

    position = params.get("position")
    look_at = params.get("look_at")
    if position is not None:
        if not isinstance(position, (list, tuple)) or len(position) != 3:
            raise HandlerError(
                "position must be [x, y, z]", hint="world-space coordinates"
            )
        cmds.xform(cam, translation=[float(v) for v in position], worldSpace=True)
    if look_at is not None:
        if not isinstance(look_at, (list, tuple)) or len(look_at) != 3:
            raise HandlerError("look_at must be [x, y, z]", hint="world-space point")
        current = cmds.xform(cam, query=True, worldSpace=True, translation=True)
        cmds.xform(
            cam, rotation=look_at_rotation(current, [float(v) for v in look_at]),
            worldSpace=True,
        )
    focal = params.get("focal_length")
    if focal is not None:
        shape = cmds.listRelatives(cam, shapes=True, fullPath=True)[0]
        cmds.setAttr(shape + ".focalLength", float(focal))
    if params.get("set_active", True):
        panel = _find_model_panel(cmds)
        cmds.lookThru(panel, cam)
    return {
        "name": cam,
        "position": cmds.xform(cam, query=True, worldSpace=True, translation=True),
        "rotation": cmds.xform(cam, query=True, worldSpace=True, rotation=True),
        "warnings": warnings,
    }
```

- [ ] **Step 3: Capture modifications** (`capture.py`):
  1. `_PanelState.__init__` additionally snapshots `lights`, `cameras`, `locators`, `manipulators`, `textures` via the same `me()` helper; `restore()` writes them back in the same modelEditor edit call as the existing flags.
  2. `_capture_one` `editor_kwargs` gains `"lights": False, "cameras": False, "locators": False, "manipulators": False, "textures": False` — icons and texture-placement manipulators must never pollute captures.
  3. Each `camera_positions` entry gains `"camera": capture_cam` (resolved long: `cmds.ls(capture_cam, long=True)[0]`); when `angle == "current"` the LLM can now SEE which camera it captured through instead of silently trusting a stale one.

- [ ] **Step 4: Register (`"set_viewport"`, `"set_camera"`) + schemas + tools:**

```python
class ViewportState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    panel: str
    show_grid: bool
    show_light_icons: bool
    show_camera_icons: bool
    show_locators: bool
    show_manipulators: bool
    show_texture_placements: bool
    wireframe_on_shaded: bool
    display_lights: str
    camera: str


class CameraResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    position: List[float]
    rotation: List[float]
    warnings: List[str] = Field(default_factory=list)
```

```python
    @mcp.tool(
        title="Configure viewport",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=True
        ),
    )
    def maya_set_viewport(
        show_grid: Annotated[Optional[bool], Field(description="Grid visibility.")] = None,
        show_light_icons: Annotated[Optional[bool], Field(description=(
            "Light icons render into playblasts - keep off while capturing art."
        ))] = None,
        show_camera_icons: Annotated[Optional[bool], Field(description="Camera icons.")] = None,
        show_locators: Annotated[Optional[bool], Field(description="Locator display.")] = None,
        show_manipulators: Annotated[Optional[bool], Field(description="Manipulator display.")] = None,
        show_texture_placements: Annotated[Optional[bool], Field(description=(
            "place3dTexture widgets - they render into captures too."
        ))] = None,
        wireframe_on_shaded: Annotated[Optional[bool], Field(description="Wire overlay.")] = None,
        display_lights: Annotated[
            Optional[Literal["default", "all", "active", "flat", "none"]],
            Field(description="Which lights illuminate the viewport."),
        ] = None,
    ) -> ViewportState:
        """Persistently configure the working viewport (unlike captures, which
        restore themselves). Only the params you pass change; the FULL resulting
        state always comes back - call with no params to just read it."""
        return ViewportState.model_validate(
            maya.request(
                "set_viewport",
                {"show_grid": show_grid, "show_light_icons": show_light_icons,
                 "show_camera_icons": show_camera_icons,
                 "show_locators": show_locators,
                 "show_manipulators": show_manipulators,
                 "show_texture_placements": show_texture_placements,
                 "wireframe_on_shaded": wireframe_on_shaded,
                 "display_lights": display_lights},
                timeout_s=SCENE_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Set camera",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=True
        ),
    )
    def maya_set_camera(
        camera: Annotated[str, Field(description=(
            "Camera name; created if missing. Use a dedicated named camera "
            "instead of trusting whatever the panel last looked through."
        ))] = "mcpCam",
        position: Annotated[Optional[List[float]], Field(
            min_length=3, max_length=3, description="World-space position.",
        )] = None,
        look_at: Annotated[Optional[List[float]], Field(
            min_length=3, max_length=3, description="World-space aim point.",
        )] = None,
        focal_length: Annotated[Optional[float], Field(gt=0, description="mm.")] = None,
        set_active: Annotated[bool, Field(description=(
            "Make the viewport look through this camera (what capture 'current' uses)."
        ))] = True,
    ) -> CameraResult:
        """Create/position a named camera and (by default) make it the active
        viewport camera, so capture_viewport 'current' is deterministic."""
        return CameraResult.model_validate(
            maya.request(
                "set_camera",
                {"camera": camera, "position": position, "look_at": look_at,
                 "focal_length": focal_length, "set_active": set_active},
                timeout_s=SCENE_TIMEOUT_S,
            )
        )
```

- [ ] **Step 5: Run headless + mayapy suites.** Then run the live capture regression (Maya editor open, plugin loaded): `.venv/Scripts/python.exe evals/isolate_regression.py` → exit 0 (Global Constraints: required after ANY capture.py change).

- [ ] **Step 6: Commit**

```bash
git add maya_plugin/handlers/viewport.py maya_plugin/handlers/capture.py maya_plugin/maya_mcp_plugin.py src/maya_mcp/server.py src/maya_mcp/schemas.py tests/
git commit -m "feat(m1): set_viewport/set_camera discipline + capture icon-hiding"
```

---

### Task 11: M1 acceptance gate + full sweep

The design-doc M1 exit test: *boolean a rune cavity into a cube, undo it, restore a checkpoint; zero orphan history nodes.*

**Files:**
- Test: `tests/test_handlers_mayapy.py` (append the gate)

- [ ] **Step 1: Write the gate test** (drives handlers through a real `Dispatcher` with real undo-chunk hooks, exactly as the plugin wires them — this is what proves the one-call-one-undo-step discipline end to end):

```python
class TestM1AcceptanceGate:
    def test_boolean_rune_cavity_undo_restore_zero_orphans(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.dispatcher import Dispatcher
        from maya_plugin.maya_mcp_plugin import _build_handlers, _undo_hooks

        cmds.file(rename=str(tmp_path / "gate.ma"))
        undo_open, undo_close = _undo_hooks()
        dispatcher = Dispatcher(
            _build_handlers(), undo_open=undo_open, undo_close=undo_close
        )

        def call(cmd, **params):
            frame = {"v": 1, "id": cmd, "cmd": cmd, "params": params}
            response = dispatcher.handle_request(frame)
            assert response["status"] == "ok", response
            return response["result"]

        try:
            call("create_primitive", kind="cube", name="gate_block",
                 scale=[2, 2, 2])
            checkpoint = call("checkpoint", label="pre_cavity")

            # rune cavity: a cutter cube booleaned out of the block
            call("create_primitive", kind="cube", name="gate_cutter",
                 translate=[0, 0, 1.0], scale=[0.6, 1.2, 0.4])
            carved = call("boolean_op", a="|gate_block", b="|gate_cutter",
                          op="difference", new_name="gate_carved")
            assert carved["watertight"] is True
            assert carved["tris"] > 12

            # zero orphan history nodes, ever
            assert cmds.ls(type="polyCBoolOp") == []
            shape = cmds.listRelatives("|gate_carved", shapes=True,
                                       fullPath=True)[0]
            assert cmds.listHistory(shape) == [shape]

            # undo the boolean: ONE step (the whole tool call was one chunk)
            undone = call("undo", steps=1)
            assert undone["undone"] == 1
            assert cmds.objExists("gate_block") and cmds.objExists("gate_cutter")
            assert not cmds.objExists("gate_carved")

            # restore the pre-cavity checkpoint: block only, no cutter
            restored = call("restore_checkpoint",
                            checkpoint_id=checkpoint["checkpoint_id"])
            assert restored["restored"] == checkpoint["checkpoint_id"]
            assert cmds.objExists("gate_block")
            assert not cmds.objExists("gate_cutter")
            assert not cmds.objExists("gate_carved")

            # scene-wide orphan sweep
            for orphan_type in ("polyCBoolOp", "type", "typeExtrude", "groupParts"):
                assert cmds.ls(type=orphan_type) == [], orphan_type
        finally:
            dispatcher.shutdown()
```

- [ ] **Step 2: Run the gate** — `E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py::TestM1AcceptanceGate -q` → PASS.

- [ ] **Step 3: Full sweep, all three legs:**

```bash
uv run pytest -q
```
Expected: all headless tests PASS (M0 baseline 116 + every new M1 test), zero skips other than documented GUI-only ones.

```bash
E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q
```
Expected: PASS (Type-plugin test may skip in standalone — acceptable, covered live).

Live leg (Maya editor open with the plugin autoloaded, #577 req 5):

```bash
.venv/Scripts/python.exe evals/isolate_regression.py
```
Expected: exit 0.

- [ ] **Step 4: Live smoke of the new tools** (editor open; drive via the MCP server or the direct-TCP client pattern from the golem run): one `maya_etch_text` carving an aleph (`text="א", mirror=true, rotate_deg=180`) into a cube face and one `maya_capture_viewport` confirming (a) the carve is visible and (b) no light/manipulator icons in the frame. This is the only place the Type pipeline and icon-hiding are proven against a real GUI.

- [ ] **Step 5: Commit**

```bash
git add tests/test_handlers_mayapy.py
git commit -m "test(m1): acceptance gate - boolean cavity, undo, restore, zero orphans"
```

---

### Task 12: Docs + ticket wrap

**Files:**
- Modify: `README.md` (tool catalog table: add the ~23 M1 tools with one-line descriptions; note the checkpoint directory and the undo-per-tool-call contract)
- Modify: `docs/protocol.md` (append the new command names to the command list)

- [ ] **Step 1: Update README + protocol doc** as above (keep each tool line to one sentence; the schemas are the reference).

- [ ] **Step 2: Verify the server still boots clean with no Maya** — `uv run maya-mcp` should start and (per M0 behavior) report "plugin not connected" errors with launch instructions rather than crashing. MCP Inspector check (optional but cheap): `npx @modelcontextprotocol/inspector` → every tool schema loads, annotations present.

- [ ] **Step 3: Commit + finish**

```bash
git add README.md docs/protocol.md
git commit -m "docs(m1): tool catalog + protocol command list for M1"
```

Then use superpowers:finishing-a-development-branch (merge `feature/m1-hands` per its flow) and update redmine #577: notes = what landed (tool list, test counts, gate + sweep results, live-smoke result), status = **Resolved** if all three sweep legs passed, **Feedback** if the live smoke needs the user's eyes.

---

## Self-Review Notes (deviations the implementer should know)

- `maya_open_scene`/`maya_new_scene` gained a `confirm` guard for unsaved changes — a safety addition beyond the doc's signatures; documented in the tool descriptions.
- `soft_move` decided design-doc §9 open question 5: OpenMaya weighted offsets, not `softSelect` (deterministic, selection-free, nothing to restore).
- `sculpt_ops` op `displace_noise` is an M1 addition to the doc's SculptOp union (ticket #577 req 3); `bridge` takes `edges_a`/`edges_b` per the doc.
- `maya_etch_text` is the ticket's "NEW TOOL WORTH ADDING"; it reuses `boolean_op`'s core so the SG-cleanup discipline exists in exactly one place.
- `remesh_retopo` `keep_original` hides `<name>_orig` rather than deleting it; the doc says "keep_original: bool = True" — interpretation documented in the tool description.
- The transform ledger is in-memory per-plugin-session; a plugin restart forgets prior writes (acceptable: warnings are advisory).
