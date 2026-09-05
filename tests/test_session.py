"""session handler tests against a fake cmds — no Maya required."""

import os

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import session


class FakeCmds:
    """#799: this handler's Maya surface is files and queues, not nodes -
    there is nothing here to delete and no plug to write, so contract points
    1 and 2 have no purchase. Point 3 does: `redo` could never fail while
    `undo` could, which left redo's queue-exhausted branch with no test in
    the file, and `workspace` answered the project ROOT for a bare call that
    Maya answers with the workspace NAME.

    Round 2 correction: round 1 claimed `workspace` "used to answer any
    flags at all". It did not - HEAD's signature had no **kw, so an
    unmodelled flag already raised TypeError. What it really answered
    wrongly was the bare call, and round 1's guard could not refuse that
    either because both its flags defaulted to True. See workspace() below."""

    def __init__(self, tmp_path, scene_name=""):
        self._tmp = str(tmp_path)
        self.scene_name = scene_name
        self.modified = False
        self.saved_to = []
        self.opened = []
        self.new_calls = 0
        self.undo_calls = 0
        self.redo_calls = 0
        # The undo queue as Maya keeps it, bottom to top, by entry NAME - and
        # the answer to the question the previous version of this comment
        # refused to guess. MEASURED (#820, evals/undo_probe_820b.py, Maya
        # 2027): cmds.undo() on an EMPTY queue does NOT raise - it returns
        # None (redo returns the linear unit) - so the old "except
        # RuntimeError: break" was dead code and both handlers counted
        # attempts: undo after new_scene reported undone=1. Maya's own
        # callbacks also push entries that change nothing
        # (selectionMaskResetAll, hikDefinitionFileNewCallback;, and a
        # nameless "" entry new_scene leaves), AFTER a tool's chunk closes.
        self.undo_queue = []
        self.redo_queue = []
        self.unit_preference = "m"  # what a new scene comes up in
        self.linear = "m"  # a session left in metres, as an eval can leave it
        self.unit_set_calls = []

    def currentUnit(self, query=False, linear=None):
        if query:
            assert linear is True
            return self.linear
        self.unit_set_calls.append(linear)
        self.linear = linear
        return linear

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
            self.scene_name = ""  # an empty scene is untitled, as in Maya
            # Maya resets the linear unit to the user's preference on a new
            # scene. Modelled so a set-BEFORE-file() refactor is silently
            # undone here exactly as it would be in Maya, and the ordering
            # test below can actually catch it.
            self.linear = self.unit_preference
            return None
        if kw.get("exportAll") or kw.get("save"):
            target = args[0] if args else self.scene_name
            self.saved_to.append(target)
            with open(target, "w") as fh:
                fh.write("fake maya ascii\n")
            return None
        if kw.get("open"):
            self.opened.append(args[0])
            # Maya's scene name follows the opened file - and _checkpoint_dir
            # is derived from it, which is the whole of #649. Modelled here so
            # the tests below can see where the NEXT checkpoint would land.
            self.scene_name = args[0]
            return None
        if kw.get("rename"):
            value = kw["rename"]
            self.scene_name = value if isinstance(value, str) else args[0]
            return None
        raise AssertionError("unexpected file call %r %r" % (args, kw))

    def workspace(self, *args, **kw):
        # #799 round 2: the round-1 guard was inert and its rationale was
        # wrong about HEAD. The signature was `workspace(self, query=True,
        # rootDirectory=True)` with no **kw, so `fileRule`/`active`/
        # `directory` already raised TypeError before round 1 touched it -
        # and BOTH flags defaulting to True meant the only call the new
        # assert could refuse was an explicit query=False, which no handler
        # writes. Reverting that method to HEAD's one-line `return
        # self._tmp` changed no test.
        #
        # What actually needs refusing is the BARE call. `cmds.workspace()`
        # in Maya returns the current workspace NAME, not its root
        # directory, so a handler that dropped the flags would be handed a
        # path-shaped answer here and a name in the live session - the
        # #714/#764 shape exactly. Defaulting both to False is what lets
        # the assert see it.
        assert not args, "the checkpoint dir asks a QUERY, with no operand: %r" % (args,)
        assert kw.get("query") and kw.get("rootDirectory"), (
            "the checkpoint dir comes from the project ROOT and nothing else; "
            "a bare cmds.workspace() answers the workspace NAME in Maya (%r)" % (kw,))
        assert set(kw) == {"query", "rootDirectory"}, (
            "unmodelled workspace flag: %r" % (sorted(set(kw) - {"query", "rootDirectory"}),))
        return self._tmp

    def undoInfo(self, query=False, undoQueueEmpty=False, redoQueueEmpty=False,
                 undoName=False, redoName=False, **kw):
        assert query, "this fake models the queries only"
        if undoQueueEmpty:
            return not self.undo_queue
        if redoQueueEmpty:
            return not self.redo_queue
        if undoName:
            return self.undo_queue[-1] if self.undo_queue else ""
        if redoName:
            return self.redo_queue[-1] if self.redo_queue else ""
        raise AssertionError("unexpected undoInfo query %r" % (kw,))

    def undo(self):
        # Measured: no raise on an empty queue, just None.
        self.undo_calls += 1
        if not self.undo_queue:
            return None
        self.redo_queue.append(self.undo_queue.pop())
        return None

    def redo(self):
        self.redo_calls += 1
        if not self.redo_queue:
            return "centimeter"   # measured: cmds.redo() on empty answers this
        self.undo_queue.append(self.redo_queue.pop())
        return None


@pytest.fixture
def fake(tmp_path, monkeypatch):
    fake = FakeCmds(tmp_path)
    monkeypatch.setattr(session, "_cmds", lambda: fake)
    # The id -> path registry is module state that outlives one handler call
    # by design; give each test a clean one.
    monkeypatch.setattr(session, "_WRITTEN", {})
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


def test_restore_rejects_path_traversal(fake):
    with pytest.raises(HandlerError) as exc:
        session.restore_checkpoint({"checkpoint_id": "../../foo"})
    assert ".." in str(exc.value)
    assert exc.value.hint


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


class TestCheckpointIdsSurviveASceneChange:
    """maya-mcp #649 - a checkpoint id is unique only inside ONE directory, and
    that directory is derived from the open scene. Every destructive op hands
    out an id and then changes the scene, so the documented recovery path
    resolved somewhere else: unreachable at best, a DIFFERENT scene's
    checkpoint of the same number at worst."""

    def test_new_scenes_own_checkpoint_is_restorable_afterwards(self, fake, tmp_path):
        scene_dir = tmp_path / "shot"
        scene_dir.mkdir()
        fake.scene_name = str(scene_dir / "golem.ma")

        result = session.new_scene({"confirm": True})
        assert fake.scene_name == ""  # ids now resolve against the workspace root

        restored = session.restore_checkpoint({"checkpoint_id": result["pre_checkpoint"]})
        assert restored["path"] == result["pre_checkpoint_path"]
        assert os.path.dirname(restored["path"]) == str(scene_dir / "checkpoints")

    def test_open_scene_returns_the_path_of_its_own_checkpoint(self, fake, tmp_path):
        scene_dir = tmp_path / "shot"
        scene_dir.mkdir()
        fake.scene_name = str(scene_dir / "golem.ma")
        target = tmp_path / "other.ma"
        target.write_text("x")

        result = session.open_scene({"path": str(target), "confirm": True})
        assert result["pre_checkpoint_path"].startswith(str(scene_dir / "checkpoints"))
        assert session.restore_checkpoint(
            {"checkpoint_id": result["pre_checkpoint"]}
        )["path"] == result["pre_checkpoint_path"]

    def test_an_id_never_resolves_to_another_directorys_file(self, fake, tmp_path):
        (tmp_path / "shot_a").mkdir()
        fake.scene_name = str(tmp_path / "shot_a" / "a.ma")
        saved = session.checkpoint({"label": "target"})

        # the same NNN_label, a different scene's work - silently opening this
        # instead of the file the id was issued for is the dangerous half.
        decoy = tmp_path / "shot_b" / "checkpoints"
        decoy.mkdir(parents=True)
        (decoy / "001_target.ma").write_text("the wrong scene")
        fake.scene_name = str(tmp_path / "shot_b" / "b.ma")

        restored = session.restore_checkpoint({"checkpoint_id": "001_target"})
        assert restored["path"] == saved["path"]
        assert fake.opened[-1] == saved["path"]

    def test_checkpoints_do_not_nest_after_a_restore(self, fake, tmp_path):
        cp_dir = tmp_path / "checkpoints"
        cp_dir.mkdir()
        (cp_dir / "003_target.ma").write_text("x")
        session.restore_checkpoint({"checkpoint_id": "003_target"})

        # the scene is now a file INSIDE checkpoints/; the next checkpoint must
        # land beside it, not in checkpoints/checkpoints/ with numbering reset.
        following = session.checkpoint({"label": "after"})
        assert os.path.dirname(following["path"]) == str(cp_dir)
        assert not os.path.isdir(str(cp_dir / "checkpoints"))
        assert following["checkpoint_id"] == "005_after"

    def test_restore_by_path_needs_no_id(self, fake, tmp_path):
        target = tmp_path / "elsewhere" / "007_far.ma"
        target.parent.mkdir()
        target.write_text("x")
        result = session.restore_checkpoint({"path": str(target)})
        assert result["restored"] == "007_far"
        assert fake.opened[-1] == str(target)

    def test_restore_by_missing_path_errors_before_touching_the_scene(self, fake, tmp_path):
        with pytest.raises(HandlerError) as exc:
            session.restore_checkpoint({"path": str(tmp_path / "nope.ma")})
        assert "not found" in str(exc.value)
        assert fake.opened == [] and fake.saved_to == []

    def test_restore_requires_an_id_or_a_path(self, fake):
        with pytest.raises(HandlerError) as exc:
            session.restore_checkpoint({})
        assert "checkpoint_id" in str(exc.value)

    def test_restore_reports_how_to_undo_itself(self, fake, tmp_path):
        cp_dir = tmp_path / "checkpoints"
        cp_dir.mkdir()
        (cp_dir / "003_target.ma").write_text("x")
        result = session.restore_checkpoint({"checkpoint_id": "003_target"})
        assert result["pre_restore_path"].endswith(
            result["pre_restore_checkpoint"] + ".ma"
        )
        assert os.path.isfile(result["pre_restore_path"])

    def test_a_pruned_id_does_not_resolve_to_a_stale_remembered_path(self, fake, tmp_path):
        saved = session.checkpoint({"label": "doomed"})
        os.unlink(saved["path"])
        with pytest.raises(HandlerError) as exc:
            session.restore_checkpoint({"checkpoint_id": saved["checkpoint_id"]})
        assert "not found" in str(exc.value)


class TestAPathNamesItsOwnCheckpoint:
    """#797 row 23: `path` wins outright - it overwrites `checkpoint_id`
    with its own stem and restores the file it names. A caller who passes
    BOTH and means two different checkpoints gets the path's one, with the
    id they typed echoed back as `restored` only because the handler
    rewrote it first. Refused now, before Maya is even imported, unless the
    id IS the path's stem (the wrapper's documented "both accepted" case).
    """

    MISMATCH = {"checkpoint_id": "003_other", "path": "C:/cp/007_pre.ma"}

    def test_an_id_that_is_not_the_paths_stem_refuses(self, fake):
        with pytest.raises(HandlerError) as exc:
            session.restore_checkpoint(dict(self.MISMATCH))
        message = str(exc.value)
        assert "restore_checkpoint does not use 'checkpoint_id'" in message
        assert "when path is also given" in message
        assert "007_pre" in message
        assert exc.value.hint

    def test_the_refusal_precedes_the_isfile_check(self, fake):
        # The contract entry names a path that does not exist: a "not
        # found" refusal here would be answering a question the caller
        # never asked, and would flip to a silent overwrite the moment the
        # file DID exist.
        with pytest.raises(HandlerError, match="does not use 'checkpoint_id'"):
            session.restore_checkpoint(dict(self.MISMATCH))
        assert fake.opened == [] and fake.saved_to == []

    def test_the_refusal_precedes_maya_itself(self, monkeypatch):
        # No `fake` fixture: `_cmds()` here is the real `import maya.cmds`,
        # which does not exist in this process. Reaching it is an
        # ImportError, and that ImportError is the #767 proof - the same
        # assertion tests/test_branch_contract.py makes.
        def boom():
            raise AssertionError("restore_checkpoint reached Maya")
        monkeypatch.setattr(session, "_cmds", boom)
        with pytest.raises(HandlerError, match="does not use 'checkpoint_id'"):
            session.restore_checkpoint(dict(self.MISMATCH))

    def test_an_id_that_matches_the_paths_stem_proceeds(self, fake, tmp_path):
        target = tmp_path / "elsewhere" / "007_far.ma"
        target.parent.mkdir()
        target.write_text("x")
        result = session.restore_checkpoint({"checkpoint_id": "007_far",
                                             "path": str(target)})
        assert result["restored"] == "007_far"
        assert fake.opened[-1] == str(target)

    def test_the_wrappers_none_for_the_absent_one_is_not_a_conflict(
            self, fake, tmp_path):
        # server.py sends BOTH keys on every call, None for whichever the
        # caller left unset (#797 wrapper-default change). Neither shape
        # may look like "both given".
        target = tmp_path / "008_bypath.ma"
        target.write_text("x")
        assert session.restore_checkpoint(
            {"checkpoint_id": None, "path": str(target)})["restored"] == \
            "008_bypath"
        # the first restore's own auto_pre_restore already made this dir
        cp_dir = tmp_path / "checkpoints"
        cp_dir.mkdir(exist_ok=True)
        (cp_dir / "003_target.ma").write_text("x")
        assert session.restore_checkpoint(
            {"checkpoint_id": "003_target", "path": None})["restored"] == \
            "003_target"

    def test_an_empty_string_for_either_is_not_a_conflict_either(
            self, fake, tmp_path):
        # The pre-#797 wrapper sent "" rather than None, and a session
        # resumed against an older server still does.
        target = tmp_path / "009_bypath.ma"
        target.write_text("x")
        assert session.restore_checkpoint(
            {"checkpoint_id": "", "path": str(target)})["restored"] == \
            "009_bypath"


def test_undo_counts_steps_and_stops_at_queue_end(fake):
    fake.undo_queue = ["maya-mcp", "maya-mcp"]
    result = session.undo({"steps": 5})
    assert result == {"undone": 2, "requested": 5, "skipped": [], "queue_empty": True}
    assert fake.undo_calls == 2, "an empty queue is not undone into"


def test_undo_on_an_empty_queue_calls_nothing_and_says_zero(fake):
    # #820: the old handler reported undone=1 after new_scene, because
    # cmds.undo() on an empty queue does not raise.
    assert session.undo({"steps": 1}) == {"undone": 0, "requested": 1, "skipped": [],
                                          "queue_empty": True}
    assert fake.undo_calls == 0


def test_undo_steps_over_mayas_no_op_entries_without_counting_them(fake):
    # bottom -> top, exactly the shape the probe enumerated after two creates
    fake.undo_queue = ["", "maya-mcp", "hikDefinitionFileNewCallback;", "maya-mcp",
                       "selectionMaskResetAll", "selectionMaskResetAll"]
    out = session.undo({"steps": 1})
    assert out == {"undone": 1, "requested": 1,
                   "skipped": ["selectionMaskResetAll", "selectionMaskResetAll"],
                   "queue_empty": False}
    assert fake.undo_queue == ["", "maya-mcp", "hikDefinitionFileNewCallback;"]
    out = session.undo({"steps": 1})
    assert out["undone"] == 1 and out["skipped"] == ["hikDefinitionFileNewCallback;"]
    assert fake.undo_queue == [""]
    # the nameless bottom entry IS the end: never popped, nothing counted
    out = session.undo({"steps": 1})
    assert out == {"undone": 0, "requested": 1, "skipped": [], "queue_empty": True}
    assert fake.undo_queue == [""]


def test_boot_window_entries_are_no_ops_too(fake):
    # MEASURED in the first ~10 s after boot: deferred plugin autoloads and
    # Arnold's deferred registration land as named entries that change nothing
    fake.undo_queue = ["maya-mcp", 'autoLoadPlugin("", "MayaMuscle", "MayaMuscle")',
                       "mtoa.cmds.registerArnoldRenderer._register"]
    out = session.undo({"steps": 1})
    assert out["undone"] == 1
    assert out["skipped"] == ["mtoa.cmds.registerArnoldRenderer._register",
                              'autoLoadPlugin("", "MayaMuscle", "MayaMuscle")']
    assert fake.undo_queue == []


def test_the_stop_is_the_name_not_the_empty_flag(fake):
    # MEASURED: undoQueueEmpty reads True with entries still on the queue
    # after idle processing; the handler must never consult it.
    fake.undo_queue = ["maya-mcp", "maya-mcp"]
    calls = []
    real = fake.undoInfo

    def spy(**kw):
        calls.append(kw)
        return real(**kw)
    fake.undoInfo = spy
    assert session.undo({"steps": 2})["undone"] == 2
    assert not any(k.get("undoQueueEmpty") or k.get("redoQueueEmpty") for k in calls)


def test_undo_rejects_bad_steps(fake):
    with pytest.raises(HandlerError):
        session.undo({"steps": 0})


def test_redo_counts_steps_and_stops_at_queue_end(fake):
    # #799: redo had no test whatsoever, because the fake's redo() could not
    # fail. Its "except RuntimeError: break" was dead code under test, and
    # so was every claim the result makes about how many steps really ran.
    fake.redo_queue = ["maya-mcp"] * 3
    assert session.redo({"steps": 5}) == {"redone": 3, "requested": 5, "skipped": [],
                                          "queue_empty": True}
    assert fake.redo_calls == 3


def test_redo_steps_over_mayas_no_op_entries_too(fake):
    fake.redo_queue = ["maya-mcp", "selectionMaskResetAll"]
    out = session.redo({"steps": 1})
    assert out == {"redone": 1, "requested": 1, "skipped": ["selectionMaskResetAll"],
                   "queue_empty": True}
    assert fake.undo_queue == ["selectionMaskResetAll", "maya-mcp"]


def test_redo_rejects_bad_steps(fake):
    with pytest.raises(HandlerError):
        session.redo({"steps": session.MAX_UNDO_STEPS + 1})
    assert fake.redo_calls == 0


def test_new_scene_requires_confirm(fake):
    with pytest.raises(HandlerError) as exc:
        session.new_scene({})
    assert "confirm" in exc.value.hint
    assert fake.new_calls == 0
    # C1: a validation failure must never burn a checkpoint.
    assert fake.saved_to == []


def test_new_scene_with_confirm(fake):
    result = session.new_scene({"confirm": True})
    assert result["new_scene"] is True
    assert fake.new_calls == 1
    # C1: new_scene destroys the undo queue with it, so an auto-checkpoint
    # is the only way back - it must be taken and its id returned.
    assert result["pre_checkpoint"] == "001_auto_pre_new_scene"
    assert fake.saved_to == [
        os.path.join(fake._tmp, "checkpoints", "001_auto_pre_new_scene.ma")
    ]


class TestNewSceneOwnsTheLinearUnit:
    """maya-mcp #634 - reporting alone is not enough.

    An eval that sets `m` leaves the session that way for whatever is built
    next, and no in-Maya measurement can see the difference (#629). So
    new_scene STATES the unit rather than inheriting it.
    """

    def test_it_forces_the_metre_true_unit_by_default(self, fake):
        assert fake.linear == "m"  # the session arrives dirty
        result = session.new_scene({"confirm": True})
        assert fake.unit_set_calls == ["cm"]
        assert result["units"] == {"linear_unit": "cm", "export_metres_per_unit": 1.0}

    def test_an_explicit_unit_is_honoured(self, fake):
        result = session.new_scene({"confirm": True, "linear_unit": "m"})
        assert fake.unit_set_calls == ["m"]
        assert result["units"]["export_metres_per_unit"] == 100.0

    def test_an_unknown_unit_is_rejected_before_the_scene_is_destroyed(self, fake):
        # Ordering matters exactly as it does for confirm: a bad param must
        # never cost the user their scene.
        with pytest.raises(HandlerError) as exc:
            session.new_scene({"confirm": True, "linear_unit": "furlong"})
        assert "furlong" in str(exc.value)
        assert fake.new_calls == 0
        assert fake.saved_to == []
        assert fake.unit_set_calls == []

    def test_the_unit_is_set_after_the_scene_is_replaced(self, fake):
        # cmds.file(new=True) resets the linear unit to the user's preference,
        # so setting it first would be silently undone.
        session.new_scene({"confirm": True})
        assert fake.new_calls == 1 and fake.unit_set_calls == ["cm"]
        assert fake.linear == "cm"


def test_new_scene_checkpoints_before_the_destructive_call(fake, monkeypatch):
    # C1: prove the ordering, not just that both things happened - if
    # auto_checkpoint itself blows up, the scene must NOT have been replaced.
    def _boom(reason):
        raise RuntimeError("checkpoint boom")

    monkeypatch.setattr(session, "auto_checkpoint", _boom)
    with pytest.raises(RuntimeError, match="checkpoint boom"):
        session.new_scene({"confirm": True})
    assert fake.new_calls == 0


def test_open_scene_missing_file(fake):
    with pytest.raises(HandlerError):
        session.open_scene({"path": "Z:/does/not/exist.ma"})
    assert fake.saved_to == []


def test_open_scene_unsaved_changes_needs_confirm(fake, tmp_path):
    target = tmp_path / "scene.ma"
    target.write_text("x")
    fake.modified = True
    with pytest.raises(HandlerError) as exc:
        session.open_scene({"path": str(target)})
    assert "unsaved" in str(exc.value)
    # C1: the refusal must not have taken a checkpoint either.
    assert fake.saved_to == []
    result = session.open_scene({"path": str(target), "confirm": True})
    assert result["opened"] == str(target)
    # C1: open_scene is just as unrecoverable via undo as new_scene.
    assert result["pre_checkpoint"] == "001_auto_pre_open_scene"


def test_open_scene_checkpoints_before_the_destructive_call(fake, monkeypatch, tmp_path):
    target = tmp_path / "scene2.ma"
    target.write_text("x")

    def _boom(reason):
        raise RuntimeError("checkpoint boom")

    monkeypatch.setattr(session, "auto_checkpoint", _boom)
    with pytest.raises(RuntimeError, match="checkpoint boom"):
        session.open_scene({"path": str(target), "confirm": True})
    assert fake.opened == []


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


class RecordingIprCmds:
    """Only what stop_idle_ipr touches; every surface is recorded."""

    WINDOW = "ArnoldRenderView"

    def __init__(self, batch=False, window=True):
        self.batch, self.window_open = batch, window
        self.calls = []

    def about(self, batch=False):
        assert batch, "stop_idle_ipr asks one thing about the session"
        return self.batch

    def window(self, name, exists=False):
        # #799: `return self.window_open` for ANY name meant this fake would
        # have reported an open view for a window stop_idle_ipr never asks
        # about, so a typo in the measured name (#721p2 measured it as
        # exactly "ArnoldRenderView") could not fail a test here.
        assert exists, "existence is the only question asked of a window"
        return self.window_open if name == self.WINDOW else False

    def deleteUI(self, name):
        if name != self.WINDOW:
            raise RuntimeError("Object '%s' not found." % name)
        self.calls.append(("deleteUI", name))
        self.window_open = False


class TestStopIdleIpr:
    def test_batch_mode_does_nothing(self):
        cmds = RecordingIprCmds(batch=True)
        assert session.stop_idle_ipr(cmds) == []
        assert cmds.calls == []

    def test_no_window_does_nothing(self):
        assert session.stop_idle_ipr(RecordingIprCmds(window=False)) == []

    def test_an_open_view_is_stopped_and_closed(self):
        cmds = RecordingIprCmds()
        actions = session.stop_idle_ipr(cmds)
        assert actions   # something was done, and it is reported
        assert ("deleteUI", "ArnoldRenderView") in cmds.calls

    def test_a_fake_without_ui_surfaces_degrades_to_noop(self):
        class Bare:
            pass
        assert session.stop_idle_ipr(Bare()) == []


class TestTheFakeRefusesWhatMayaRefuses:
    """#799 round 2: nothing asserted the round-1 hardening, so reverting it
    left the suite green - the "a green suite proves nothing" failure this
    ticket exists to remove, one level up in the harness.

    Only what THIS fake models. session.py's Maya surface is files, a
    workspace query and two undo queues; it holds no node, so there is no
    deleted-node query, no connection-fed or locked plug and no
    setKeyframe here (grep over session.py finds zero setAttr/xform/
    connectAttr/setKeyframe calls). The node-shaped barriers live in the
    fakes that own those calls.
    """

    def test_a_bare_workspace_call_is_refused_not_answered_with_the_root(self, fake):
        # In Maya this returns the workspace NAME. Answering it with the
        # project root - which is what HEAD and round 1 both did - is the
        # #764 shape: a handler drops the flags, the test stays green, the
        # live session hands back a name and the checkpoint dir is garbage.
        with pytest.raises(AssertionError, match="workspace NAME"):
            fake.workspace()

    def test_a_workspace_query_for_something_else_is_refused(self, fake):
        with pytest.raises(AssertionError, match="ROOT"):
            fake.workspace(query=True, fileRule="images")

    def test_a_workspace_flag_the_handler_never_uses_is_refused(self, fake):
        with pytest.raises(AssertionError, match="unmodelled workspace flag"):
            fake.workspace(query=True, rootDirectory=True, active=True)

    def test_the_one_call_the_handler_really_makes_still_answers(self, fake, tmp_path):
        # The counterpart, so the guard cannot be tightened into refusing
        # the live call: strict-direction wrongness is as bad as permissive.
        assert fake.workspace(query=True, rootDirectory=True) == str(tmp_path)

    def test_a_file_call_the_handler_never_makes_is_refused(self, fake):
        # The `file` fake's fallback is an AssertionError, not an invented
        # answer - reference edits, imports and exportSelected are not
        # session.py's surface and must not be silently accepted.
        with pytest.raises(AssertionError, match="unexpected file call"):
            fake.file("anything.ma", reference=True)

    def test_an_unmodelled_file_query_is_refused(self, fake):
        with pytest.raises(AssertionError, match="unexpected file query"):
            fake.file(query=True, list=True)

    def test_the_unit_query_refuses_anything_but_the_linear_unit(self, fake):
        with pytest.raises(AssertionError):
            fake.currentUnit(query=True, linear=False)

    def test_redo_can_run_out_the_way_undo_can(self, fake):
        # #799 wanted redo's exhausted branch reachable; #820 measured what
        # exhaustion IS: cmds.redo() answers "centimeter" and raises nothing,
        # so the handler must stop on the queue-empty query, not on an error.
        assert fake.redo() == "centimeter"
        assert session.redo({"steps": 3}) == {"redone": 0, "requested": 3, "skipped": [],
                                              "queue_empty": True}


class TestTheIprFakeRefusesWhatMayaRefuses:
    """RecordingIprCmds: #721p2 measured the window as exactly
    "ArnoldRenderView", and a fake that reported an open view for ANY name
    could not fail for a typo in it."""

    def test_a_window_the_handler_never_asks_about_is_not_reported_open(self):
        cmds = RecordingIprCmds()
        assert cmds.window("ArnoldRenderVeiw", exists=True) is False
        assert cmds.window(RecordingIprCmds.WINDOW, exists=True) is True

    def test_asking_a_window_anything_but_existence_is_refused(self):
        with pytest.raises(AssertionError, match="existence"):
            RecordingIprCmds().window(RecordingIprCmds.WINDOW)

    def test_deleting_a_window_that_is_not_there_raises_the_way_maya_does(self):
        with pytest.raises(RuntimeError, match="not found"):
            RecordingIprCmds().deleteUI("ArnoldRenderVeiw")

    def test_about_answers_one_question_only(self):
        with pytest.raises(AssertionError, match="one thing"):
            RecordingIprCmds().about()


# --- maya-mcp #835: the counter must survive 999 -------------------------
# Every checkpoint written in an untitled scene on this machine between
# 2026-08-15 and 2026-09-05 was id 1000: _NUMBERED matched exactly three
# digits, so once 1000_<label>.ma existed the max stayed at 999 and every
# later save was numbered 1000 again, overwriting the same-label file. The
# ring never pruned a 1000 file either. Measured on disk: 38 files named
# 1000_* in the default project's checkpoints dir.


def test_checkpoint_numbering_passes_999(fake, tmp_path):
    cp_dir = tmp_path / "checkpoints"
    cp_dir.mkdir()
    (cp_dir / "999_old.ma").write_text("x")
    first = session.checkpoint({"label": "a"})
    assert first["checkpoint_id"] == "1000_a"
    second = session.checkpoint({"label": "b"})
    assert second["checkpoint_id"] == "1001_b"
    assert first["checkpoint_id"] != second["checkpoint_id"]


def test_checkpoint_ring_prunes_four_digit_files(fake, tmp_path):
    cp_dir = tmp_path / "checkpoints"
    cp_dir.mkdir()
    for i in range(985, 1005):  # 20 files straddling the 999/1000 line
        (cp_dir / ("%d_old.ma" % i)).write_text("x")
    result = session.checkpoint({"label": "newest"})
    assert result["checkpoint_id"] == "1005_newest"
    remaining = sorted(os.listdir(str(cp_dir)))
    assert "985_old.ma" not in remaining
    assert "1004_old.ma" in remaining
    assert len(remaining) == 20


def test_two_processes_sharing_a_dir_never_take_the_same_number(fake, tmp_path):
    """The default project's checkpoints dir is shared by every untitled
    scene on the machine - the user's Maya and the agent Mayas alike. The
    number is claimed on disk BEFORE the save, so a second process reading
    the dir in the same instant sees the claim and moves on; and a number
    someone else claimed in the meantime is skipped, not overwritten."""
    cp_dir = tmp_path / "checkpoints"
    cp_dir.mkdir()
    (cp_dir / "007_older.ma").write_text("x")
    seen_at_save = {}
    real_file = fake.file

    def file_that_looks_first(*args, **kw):
        if kw.get("exportAll"):
            seen_at_save["existed"] = os.path.exists(args[0])
            seen_at_save["size"] = os.path.getsize(args[0])
        return real_file(*args, **kw)

    fake.file = file_that_looks_first
    result = session.checkpoint({"label": "mine"})
    assert result["checkpoint_id"] == "008_mine"
    assert seen_at_save == {"existed": True, "size": 0}  # claimed, empty, then saved over

    # Another process claimed 009 between our listing and our save: the
    # empty claim is exactly what its listing would find, so we take 010.
    (cp_dir / "009_theirs.ma").write_text("")
    result = session.checkpoint({"label": "again"})
    assert result["checkpoint_id"] == "010_again"
    assert (cp_dir / "009_theirs.ma").read_text() == ""  # never overwritten


def test_claim_is_removed_when_the_save_fails(fake, tmp_path):
    cp_dir = tmp_path / "checkpoints"
    cp_dir.mkdir()
    real_file = fake.file

    def failing_file(*args, **kw):
        if kw.get("exportAll"):
            raise RuntimeError("disk full")
        return real_file(*args, **kw)

    fake.file = failing_file
    with pytest.raises(RuntimeError):
        session.checkpoint({"label": "doomed"})
    assert os.listdir(str(cp_dir)) == []  # no empty checkpoint left to restore


class TestSceneReplacersAskForTheFlushHop:
    """redmine #847. MEASURED on Maya 2027: after one capture_viewport with
    isolate (reliably with lighting='scene'), cmds.file(new=True) spins one
    core forever inside Maya's own undo flush. A flushUndo issued as a
    SEPARATE request beforehand lets it return in 0.1 s; the same flush
    inside the handler - before the checkpoint, after it, after
    processIdleEvents, inside a chunk - still spins. So the handlers do not
    flush themselves: they ask the dispatcher for its own main-thread hop
    (tests/test_dispatcher.py proves the hop), and Maya's event loop runs
    between the two."""

    def test_every_handler_that_replaces_the_scene_is_marked(self):
        assert session.new_scene.flush_undo_first is True
        assert session.open_scene.flush_undo_first is True
        assert session.restore_checkpoint.flush_undo_first is True

    def test_and_they_still_take_their_safety_checkpoint(self, fake):
        session.new_scene({"confirm": True})
        assert fake.saved_to and fake.new_calls == 1
