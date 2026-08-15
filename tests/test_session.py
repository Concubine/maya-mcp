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
            return None
        if kw.get("rename"):
            value = kw["rename"]
            self.scene_name = value if isinstance(value, str) else args[0]
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
