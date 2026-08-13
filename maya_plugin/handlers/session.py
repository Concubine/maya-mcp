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


def auto_checkpoint(reason: str) -> Dict[str, str]:
    """Shared pre-destructive-op checkpoint. Returns {"checkpoint_id", "path"} -
    checkpoint_id is the stem (NNN_label) maya_restore_checkpoint expects; path
    is the file it was saved to."""
    return _save_checkpoint(_cmds(), "auto_" + reason)


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
    if ".." in checkpoint_id:
        raise HandlerError(
            "checkpoint_id %r must not contain '..'" % checkpoint_id,
            hint="pass the NNN_label stem exactly as returned by maya_checkpoint, "
            "e.g. '007_pre_rune' - not a path",
        )
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
    # new_scene is genuinely unrecoverable (no undo chunk survives a scene
    # replace) - unlike every other destructive op here it took no
    # checkpoint of its own, so a confirm=true retry after a refusal was
    # permanent total loss. Checkpoint AFTER validation (so a refused call
    # burns nothing) and BEFORE the destructive file() call.
    pre = auto_checkpoint("pre_new_scene")
    _cmds().file(new=True, force=True)
    ledger.clear()
    return {"new_scene": True, "pre_checkpoint": pre["checkpoint_id"]}


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
    # Same rationale as new_scene: replacing the scene destroys the undo
    # queue, so this is the only recovery path. Checkpoint after validation,
    # before the destructive open.
    pre = auto_checkpoint("pre_open_scene")
    cmds.file(path, open=True, force=True)
    ledger.clear()
    return {"opened": path, "pre_checkpoint": pre["checkpoint_id"]}


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
