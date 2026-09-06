"""Session safety (§5.6): checkpoints, undo/redo, scene lifecycle.

Checkpoints are incremental saves to <project>/checkpoints/NNN_label.ma.
Keep the newest 20, prune older. Undo works because every mutating tool
call is one undo chunk (dispatcher); undo/redo/scene-load handlers are
chunk-exempt via no_undo_chunk (they manipulate the queue themselves).
"""

from __future__ import annotations

import os
import re
from typing import List, Any, Dict, Optional

from ..dispatcher import HandlerError, refuse_inert, require_known_keys
from . import ledger, units

KEEP_CHECKPOINTS = 20
MAX_UNDO_STEPS = 50
CHECKPOINT_DIRNAME = "checkpoints"
# Three digits OR MORE. `\d{3}` exactly is how every checkpoint on this machine
# between 2026-08-15 and 2026-09-05 came to be numbered 1000 (maya-mcp #835):
# the writer's "%03d" grows to four digits on its own, but a pattern that
# could not read "1000_" back left the maximum at 999 forever, so every later
# save was 1000 again - overwriting the same-label file - and the ring never
# pruned a file it could not see. 38 such files were found in the default
# project's checkpoints dir, the one every untitled scene shares.
_NUMBERED = re.compile(r"^(\d{3,})_(.+)\.ma$")

# A checkpoint id is only unique inside ONE directory, and the directory is
# derived from the open scene - which is exactly what the destructive ops that
# hand out ids then change. So remember where every id this session wrote
# actually went; an id is resolved against this first (maya-mcp #649).
_WRITTEN: Dict[str, str] = {}


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _checkpoint_dir(cmds) -> str:
    scene = cmds.file(query=True, sceneName=True) or ""
    base = os.path.dirname(scene) if scene else cmds.workspace(
        query=True, rootDirectory=True
    )
    # Restoring (or opening) a checkpoint leaves the session with a scene
    # INSIDE the checkpoints dir. Joining again would nest checkpoints/
    # checkpoints/ one level deeper per restore, restarting numbering at 001
    # in each new level - so the same id then names several different files
    # (maya-mcp #649). A checkpoints dir is its own checkpoint dir.
    if os.path.basename(os.path.normpath(base)).lower() == CHECKPOINT_DIRNAME:
        path = base
    else:
        path = os.path.join(base, CHECKPOINT_DIRNAME)
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


def _claim_number(cp_dir: str, slug: str) -> "tuple[str, str]":
    """Take the next free number by creating its file exclusively.

    The checkpoint dir of an UNTITLED scene is the workspace's, which every
    Maya on the machine shares - the user's session and the agent Mayas
    alike (maya-mcp #835). Two of them reading the directory in the same
    instant would otherwise both take max+1 and the second save would
    overwrite the first. An O_EXCL create makes the number a claim the other
    process's listing already sees; on a collision this one simply moves up.
    """
    entries = _existing(cp_dir)
    number = (entries[-1][0] + 1) if entries else 1
    while True:
        stem = "%03d_%s" % (number, slug)
        path = os.path.join(cp_dir, stem + ".ma")
        try:
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        except FileExistsError:
            number += 1
            continue
        return stem, path


def _save_checkpoint(cmds, label: str) -> Dict[str, str]:
    cp_dir = _checkpoint_dir(cmds)
    stem, path = _claim_number(cp_dir, _sanitize(label))
    try:
        # force=True overwrites the empty claim with the scene.
        cmds.file(path, exportAll=True, type="mayaAscii", force=True,
                  preserveReferences=True)
    except Exception:
        # An empty claim left behind would be listed as a checkpoint and
        # restore as an empty scene; the number can be reused.
        try:
            if os.path.isfile(path) and os.path.getsize(path) == 0:
                os.unlink(path)
        except OSError:
            pass
        raise
    for _, name in _existing(cp_dir)[:-KEEP_CHECKPOINTS]:
        try:
            os.unlink(os.path.join(cp_dir, name))
        except OSError:
            pass
    _WRITTEN[stem] = path
    for stale in [k for k, v in _WRITTEN.items() if not os.path.isfile(v)]:
        del _WRITTEN[stale]  # pruned by the ring, or deleted underneath us
    return {"checkpoint_id": stem, "path": path}


def _resolve(cmds, checkpoint_id: str) -> Optional[str]:
    """Where this id actually is. The remembered path wins over the current
    scene's checkpoint dir, because the ops that hand out ids (new_scene,
    open_scene, restore_checkpoint) move that dir out from under the id they
    just returned - maya-mcp #649."""
    remembered = _WRITTEN.get(checkpoint_id)
    if remembered and os.path.isfile(remembered):
        return remembered
    path = os.path.join(_checkpoint_dir(cmds), checkpoint_id + ".ma")
    return path if os.path.isfile(path) else None


def auto_checkpoint(reason: str) -> Dict[str, str]:
    """Shared pre-destructive-op checkpoint. Returns {"checkpoint_id", "path"} -
    checkpoint_id is the stem (NNN_label) maya_restore_checkpoint expects; path
    is the file it was saved to."""
    return _save_checkpoint(_cmds(), "auto_" + reason)


# ------------------------------------------------------------------ handlers


# Every top-level key checkpoint reads. Anything else is refused rather
# than ignored (#767): an unread key does not fail, it succeeds and does
# something else.
CHECKPOINT_KEYS = ("label",)
# `name` is what all but one of these tools call the string you choose for
# the thing being made, so it is the word a caller naming a checkpoint
# reaches for first; it shares no prefix with `label`, so the typo fallback
# could never suggest it.
CHECKPOINT_SYNONYMS = {"name": "label"}


def checkpoint(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, CHECKPOINT_KEYS, "checkpoint",
                       CHECKPOINT_SYNONYMS)
    label = params.get("label")
    if not isinstance(label, str) or not label.strip():
        raise HandlerError(
            "missing required param 'label'",
            hint="pass a short label, e.g. label='pre_rune'",
        )
    return _save_checkpoint(_cmds(), label)


# Every top-level key restore_checkpoint reads. Anything else is refused
# rather than ignored (#767): an unread key does not fail, it succeeds and
# does something else - here it would silently take the missing-argument
# branch and refuse for the wrong reason.
RESTORE_CHECKPOINT_KEYS = ("checkpoint_id", "path")
# `id` is the generic abbreviation for an identifier, and a caller who has
# the id in hand shortens the word without thinking. It is two characters
# long, so the three-character prefix fallback cannot reach the real key
# from it - only a recorded synonym can.
RESTORE_CHECKPOINT_SYNONYMS = {"id": "checkpoint_id"}


def restore_checkpoint(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, RESTORE_CHECKPOINT_KEYS, "restore_checkpoint",
                       RESTORE_CHECKPOINT_SYNONYMS)
    explicit = params.get("path")
    checkpoint_id = str(params.get("checkpoint_id") or "")

    # #797 row 23: `path` wins outright below - it overwrites checkpoint_id
    # with its own stem, so a caller who passed BOTH and meant two
    # different checkpoints restored the path's one and got the id they
    # typed echoed back as `restored`, rewritten before it was ever
    # reported. The id is inert on this branch, so it is refused rather
    # than overwritten. BEFORE the isfile check on purpose: "that file does
    # not exist" answers a question the caller never asked, and the moment
    # the file DID exist the conflict would go silent again. Both must be
    # NON-EMPTY to be a conflict: server.py sends both keys on every call,
    # None for the one the caller left unset (and "" from an older wrapper).
    if explicit and checkpoint_id:
        # Derived exactly the way the overwrite below derives it, off the
        # SAME abspath - so the stem this refusal names is the id that
        # would have replaced theirs, not an approximation of it.
        stem = os.path.splitext(
            os.path.basename(os.path.abspath(str(explicit))))[0]
        if checkpoint_id != stem:
            refuse_inert(
                "restore_checkpoint", "checkpoint_id",
                "when path is also given",
                "the path names its own checkpoint (%s) and the id would be "
                "overwritten by it" % stem,
                hint="pass ONE of them - path=%r to restore that file, or "
                     "checkpoint_id=%r on its own to resolve the id against "
                     "this session's checkpoint directory"
                     % (str(explicit), checkpoint_id))

    cmds = _cmds()

    if explicit:
        path = os.path.abspath(str(explicit))
        if not os.path.isfile(path):
            raise HandlerError(
                "checkpoint file %r not found" % path,
                hint="path must be an absolute path to a .ma written by a "
                "checkpoint - it is returned alongside every checkpoint_id",
            )
        checkpoint_id = os.path.splitext(os.path.basename(path))[0]
    elif checkpoint_id:
        if ".." in checkpoint_id or os.path.isabs(checkpoint_id):
            raise HandlerError(
                "checkpoint_id %r must not contain '..' or be a path" % checkpoint_id,
                hint="pass the NNN_label stem exactly as returned by maya_checkpoint, "
                "e.g. '007_pre_rune' - or pass the file itself as path=",
            )
        path = _resolve(cmds, checkpoint_id)
        if path is None:
            cp_dir = _checkpoint_dir(cmds)
            available = ", ".join(name[:-3] for _, name in _existing(cp_dir)[-5:])
            raise HandlerError(
                "checkpoint %r not found" % checkpoint_id,
                hint="ids are per-directory and this session is in %s - most "
                "recent there: %s. If the id came from before a scene change, "
                "pass its path= instead."
                % (cp_dir, available or "none saved yet"),
            )
    else:
        raise HandlerError(
            "missing required param 'checkpoint_id'",
            hint="pass the NNN_label stem returned by maya_checkpoint, or path= "
            "to restore a checkpoint file directly",
        )

    pre = _save_checkpoint(cmds, "auto_pre_restore")
    cmds.file(path, open=True, force=True)
    ledger.clear()
    return {
        "restored": checkpoint_id,
        "path": path,
        "pre_restore_checkpoint": pre["checkpoint_id"],
        "pre_restore_path": pre["path"],
    }


restore_checkpoint.no_undo_chunk = True
# redmine #847: a scene replace right after a capture used to spin Maya
# forever. The replace was never the defect - the capture armed Maya's
# invisibility evaluator, whose tear-down inside file-new/open crashes; the
# fix is the evaluator bracket in handlers/capture.py, and the flush hop
# these handlers carried for a day was a timing artefact, measured and removed.


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


# Every top-level key undo reads. Anything else is refused rather than
# ignored (#767): an unread key does not fail, it succeeds and does
# something else - an ignored count here falls back to the default of one
# step and looks like a success.
UNDO_KEYS = ("steps",)
# `count` is this repo's own word for how many of something to make - it is
# what maya_array takes - so it travels to any tool that repeats an action.
UNDO_SYNONYMS = {"count": "steps"}


# Entries Maya's OWN callbacks push onto the undo queue that change nothing in
# the scene - MEASURED (#820, evals/undo_probe_820b.py, Maya 2027):
#   * "selectionMaskResetAll" - the deferred selection-mask callback, pushed
#     after any call that touched the selection (most tools do), once Maya
#     goes idle - i.e. between an agent's requests;
#   * "hikDefinitionFileNewCallback;" - HumanIK's new-file callback;
#   * "" - a nameless entry new_scene leaves at the bottom of the queue
#     (never popped: an empty name is how the walk recognises the end).
# They land AFTER a tool's chunk closes - the plugin flushes Maya's pending
# idle events BEFORE it opens a chunk (maya_mcp_plugin._undo_hooks), so a
# callback never runs INSIDE a chunk and turns a query into a "step" - and
# "one tool call = one undo step" holds only if undo/redo step over them
# without counting them. Undoing one changed no object in any measurement
# (the probe walks the queue and checks).
NO_OP_UNDO_ENTRIES = frozenset({"selectionMaskResetAll",
                                "hikDefinitionFileNewCallback;"})
# Two more families, seen in the boot window and after it: Maya's deferred
# plugin autoloads ('autoLoadPlugin("", "MayaMuscle", "MayaMuscle")') and
# Arnold's deferred registration ('mtoa.cmds.registerArnoldRenderer._register').
# A plugin LOAD also flushes the whole queue - see maya_mcp_plugin's startup
# note - which is why the server waits for the autoloads before it listens.
NO_OP_UNDO_PREFIXES = ("autoLoadPlugin(", "mtoa.")


def is_no_op_entry(name: str) -> bool:
    name = (name or "").strip()
    return name in NO_OP_UNDO_ENTRIES or name.startswith(NO_OP_UNDO_PREFIXES)


def _walk_queue(cmds, steps: int, name_flag: str, step,
                skipped: List[str]) -> int:
    """Perform `steps` REAL undo/redo steps, stepping over Maya's no-op
    entries, and stop at the end of the queue.

    The end is an EMPTY NAME, never the `undoQueueEmpty` /
    `redoQueueEmpty` flag: MEASURED (#820), that flag reads True with
    entries still on the queue once Maya has processed idle events between
    requests - the first gate run stopped on it with a cube still standing.
    The queue's bottom is a nameless entry `new_scene` leaves, and the name
    query answers "" for it and for a truly empty queue alike; neither is a
    step, so both end the walk. cmds.undo() / cmds.redo() on an empty queue
    do NOT raise (measured - they return None / the linear unit), so nothing
    else could stop it.
    """
    done = 0
    while done < steps:
        head = cmds.undoInfo(query=True, **{name_flag: True}) or ""
        if head == "":
            break
        step()
        if is_no_op_entry(head):
            skipped.append(head)
            continue
        done += 1
    return done


def _queue_end(cmds, name_flag: str) -> bool:
    return (cmds.undoInfo(query=True, **{name_flag: True}) or "") == ""


def undo(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, UNDO_KEYS, "undo", UNDO_SYNONYMS)
    cmds = _cmds()
    steps = _steps(params)
    skipped: List[str] = []
    done = _walk_queue(cmds, steps, "undoName", cmds.undo, skipped)
    return {"undone": done, "requested": steps, "skipped": skipped,
            "queue_empty": _queue_end(cmds, "undoName")}


undo.no_undo_chunk = True


# Every top-level key redo reads; the rest is refused rather than ignored,
# for undo's reason (#767).
REDO_KEYS = ("steps",)
# `count` reaches redo by the same route it reaches undo: it is the word
# maya_array uses for how many, and the two commands are typed together.
REDO_SYNONYMS = {"count": "steps"}


def redo(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, REDO_KEYS, "redo", REDO_SYNONYMS)
    cmds = _cmds()
    steps = _steps(params)
    skipped: List[str] = []
    done = _walk_queue(cmds, steps, "redoName", cmds.redo, skipped)
    return {"redone": done, "requested": steps, "skipped": skipped,
            "queue_empty": _queue_end(cmds, "redoName")}


redo.no_undo_chunk = True


# Every top-level key new_scene reads. Anything else is refused rather than
# ignored (#767), and refused FIRST: this handler already validates
# everything before it spends a checkpoint, and an unknown key is just one
# more thing that must never cost the user their scene.
NEW_SCENE_KEYS = ("confirm", "linear_unit")
# `units` is what the RESULT calls the block this command hands back, so a
# caller who read one result reaches for it as the input, and `unit` is the
# same word said singular. `force` is maya.cmds' own name for the flag on
# the file(new=True, force=True) call underneath - the word is right there
# in the API being wrapped. None of the three shares a prefix with the key
# it means.
NEW_SCENE_SYNONYMS = {"units": "linear_unit", "unit": "linear_unit",
                      "force": "confirm"}


def new_scene(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, NEW_SCENE_KEYS, "new_scene",
                       NEW_SCENE_SYNONYMS)
    if params.get("confirm") is not True:
        raise HandlerError(
            "new_scene discards the current scene and requires confirmation",
            hint="pass confirm=true; call maya_checkpoint or maya_save_scene first "
            "if the current state matters",
        )
    # Validate the unit BEFORE the checkpoint, for the same reason confirm is
    # validated first: a bad param must never cost the user their scene.
    requested = params.get("linear_unit", units.METRE_TRUE_UNIT)
    units.require_known_unit(requested)
    # new_scene is genuinely unrecoverable (no undo chunk survives a scene
    # replace) - unlike every other destructive op here it took no
    # checkpoint of its own, so a confirm=true retry after a refusal was
    # permanent total loss. Checkpoint AFTER validation (so a refused call
    # burns nothing) and BEFORE the destructive file() call.
    pre = auto_checkpoint("pre_new_scene")
    cmds = _cmds()
    cmds.file(new=True, force=True)
    # AFTER the replace, never before: a new scene comes up in the user's
    # preference, which would silently undo a unit set beforehand. Setting it
    # here is the point of maya-mcp #634 - an eval that leaves the session in
    # metres must not decide the scale of whatever gets built next.
    unit_block = units.set_linear_unit(cmds, requested)
    ledger.clear()
    return {
        "new_scene": True,
        "pre_checkpoint": pre["checkpoint_id"],
        # The empty scene resolves its checkpoint dir to the workspace root, so
        # the id above no longer names a file anything can find by id alone
        # from a stale plugin - the path is the durable handle (maya-mcp #649).
        "pre_checkpoint_path": pre["path"],
        "units": unit_block,
    }


new_scene.no_undo_chunk = True


# Every top-level key open_scene reads. Anything else is refused rather than
# ignored (#767), and before the checkpoint for new_scene's reason: a
# misspelt confirm that is merely dropped turns an unsaved scene into a
# discarded one.
OPEN_SCENE_KEYS = ("path", "confirm")
# `file` is what maya.cmds calls the command doing the work here, and
# `scene` is the word this tool's own name ends in, so both are what a
# caller types when naming the thing to open. `force` is the flag name on
# the file(open=True, force=True) call underneath.
OPEN_SCENE_SYNONYMS = {"file": "path", "scene": "path", "force": "confirm"}


def open_scene(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, OPEN_SCENE_KEYS, "open_scene",
                       OPEN_SCENE_SYNONYMS)
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
    return {"opened": path, "pre_checkpoint": pre["checkpoint_id"],
            "pre_checkpoint_path": pre["path"]}


open_scene.no_undo_chunk = True


# Every top-level key save_scene reads. Anything else is refused rather than
# ignored (#767): a dropped path here does not fail, it writes over
# whatever the session happens to have open.
SAVE_SCENE_KEYS = ("path",)
# `file` is maya.cmds' own name for the command being wrapped, and the
# destination of a save is the thing a caller most naturally calls a file.
SAVE_SCENE_SYNONYMS = {"file": "path"}


def save_scene(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, SAVE_SCENE_KEYS, "save_scene",
                       SAVE_SCENE_SYNONYMS)
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


def stop_idle_ipr(cmds) -> list:
    """Best-effort: close the Arnold RenderView window; returns what was
    done, [] when there was nothing to do. #721: an idle IPR view
    re-renders on EVERY scene mutation - the first keyframe call after a
    render_scene hero pass wedged Maya for 30+ minutes. render tools call
    this after finishing; keyframe tools call it before starting.
    Interactive sessions only - batch has no UI to leak.

    MEASURED (#721p2 probe, progress.md): the window is really named
    "ArnoldRenderView" (both a `window` and a `workspaceControl` by that
    name track each other exactly across open/close). `deleteUI` on it is
    the one measured-effective stop - both existence probes flip
    True -> False, twice, on a live re-test.

    The ARV's "Run IPR" option was ALSO probed as a stop mechanism
    (`cmds.arnoldRenderView(option=("Run IPR", "0"))`, the value mtoa's own
    shipped source uses everywhere it touches this option) and is INERT
    from script: `getoption("Run IPR")` stayed "1" after setting it to "0"
    live, twice. It is deliberately NOT called here - do not re-add it
    without a fresh measurement showing it actually changes state, and
    never report an action this call did not itself verify happened.
    """
    actions = []
    try:
        if cmds.about(batch=True):
            return actions
    except Exception:
        return actions  # not a real cmds (headless fake): nothing to do
    try:
        if cmds.window("ArnoldRenderView", exists=True):
            cmds.deleteUI("ArnoldRenderView")
            actions.append("closed the Arnold RenderView window")
    except Exception:
        pass
    return actions
