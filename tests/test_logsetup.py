"""maya-mcp #650: a log that several Mayas share stops dead at the cap.

The bug is an OS fact, not a Python one - Windows refuses to rename a file
another process holds open - so these tests hold a second handle and assert on
what actually lands in the file. `_HELD` marks the tests that only *fail* on
Windows; they are still meaningful elsewhere, where they assert the fixed
behaviour is reached by rotating rather than by degrading.
"""

from __future__ import annotations

import logging
import os

import pytest

from maya_plugin import logsetup


def _handler(path, **kwargs):
    h = logsetup.ResilientRotatingFileHandler(path, **kwargs)
    h.setFormatter(logging.Formatter("%(message)s"))
    return h


def _logger(name, handler):
    log = logging.getLogger(name)
    log.handlers = []
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
    return log


def _read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


class TestProcessPrivatePaths:
    def test_the_filename_carries_the_pid(self, tmp_path):
        path = logsetup.process_log_path("plugin", directory=str(tmp_path))
        assert os.path.basename(path) == "plugin-%d.log" % os.getpid()

    def test_two_processes_get_two_files(self, tmp_path):
        mine = logsetup.process_log_path("plugin", directory=str(tmp_path))
        theirs = logsetup.process_log_path("plugin", directory=str(tmp_path), pid=4321)
        assert mine != theirs

    def test_log_dir_honours_the_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MAYA_MCP_LOG_DIR", str(tmp_path))
        assert logsetup.log_dir() == str(tmp_path)

    def test_log_dir_defaults_under_the_home_directory(self, monkeypatch):
        monkeypatch.delenv("MAYA_MCP_LOG_DIR", raising=False)
        assert logsetup.log_dir().endswith(os.path.join(".maya-mcp", "logs"))

    def test_no_file_is_created_until_something_is_logged(self, tmp_path):
        path = str(tmp_path / "plugin-1.log")
        _handler(path)
        assert not os.path.exists(path)


class TestRolloverUnderContention:
    """The #650 defect itself, reproduced through a second open handle."""

    def test_a_held_file_does_not_stop_logging(self, tmp_path):
        # Two handlers on ONE path is precisely the two-Maya situation: Windows
        # locks per HANDLE, not per process, so this reproduces the rename
        # failure without needing a second interpreter.
        path = str(tmp_path / "plugin-shared.log")
        a, b = _handler(path, maxBytes=200), _handler(path, maxBytes=200)
        log_a, log_b = _logger("t650.a", a), _logger("t650.b", b)
        try:
            for i in range(8):
                log_a.info("A" * 60 + " %d" % i)
                log_b.info("B" * 60 + " %d" % i)
        finally:
            a.close()
            b.close()

        text = _read(path)
        # Before the fix the last records were dropped outright. The claim is
        # narrow and total: the FINAL message written must be in the file.
        assert "A" * 60 + " 7" in text or "B" * 60 + " 7" in text

    def test_a_failed_rollover_says_so_in_the_log(self, tmp_path):
        path = str(tmp_path / "plugin-degraded.log")
        handler = _handler(path, maxBytes=100)
        log = _logger("t650.degrade", handler)
        try:
            log.info("x" * 200)  # over the cap; next record wants a rollover
            with open(path, "a", encoding="utf-8"):  # somebody tails the file
                log.info("second record, rollover impossible")
                degraded = handler.degraded
                text = _read(path)
        finally:
            handler.close()

        if not degraded:
            pytest.skip("this platform can rename a file that is held open")
        assert "cannot rotate" in text
        assert "second record, rollover impossible" in text  # NOT dropped

    def test_the_degraded_notice_is_said_once_not_per_record(self, tmp_path):
        path = str(tmp_path / "plugin-once.log")
        handler = _handler(path, maxBytes=100)
        log = _logger("t650.once", handler)
        try:
            log.info("x" * 200)
            with open(path, "a", encoding="utf-8"):
                for i in range(10):
                    log.info("record %d" % i)
                degraded = handler.degraded
                text = _read(path)
        finally:
            handler.close()

        if not degraded:
            pytest.skip("this platform can rename a file that is held open")
        assert text.count("cannot rotate") == 1
        for i in range(10):
            assert "record %d" % i in text

    def test_it_stops_retrying_the_rename_but_not_forever(self, tmp_path):
        path = str(tmp_path / "plugin-retry.log")
        handler = _handler(path, maxBytes=100)
        log = _logger("t650.retry", handler)
        try:
            log.info("x" * 200)
            with open(path, "a", encoding="utf-8"):
                log.info("triggers the failure")
                if not handler.degraded:
                    pytest.skip("this platform can rename a file that is held open")
                # Degraded: no rename attempt until another full cap accumulates.
                assert handler.shouldRollover(_record("small")) is False
                # Grow past the retry threshold and it must try again - a
                # contender that goes away has to be picked back up.
                handler._retry_at_bytes = 0
                assert handler.shouldRollover(_record("small")) is True
        finally:
            handler.close()

    def test_rotation_still_happens_when_nothing_is_held(self, tmp_path):
        path = str(tmp_path / "plugin-solo.log")
        handler = _handler(path, maxBytes=200, backupCount=2)
        log = _logger("t650.solo", handler)
        try:
            for i in range(20):
                log.info("y" * 60 + " %d" % i)
            assert handler.degraded is False
        finally:
            handler.close()
        assert os.path.exists(path + ".1")  # the cap is still enforced
        assert os.path.getsize(path) <= 400


def _record(message):
    return logging.LogRecord("t", logging.INFO, __file__, 1, message, None, None)


class TestPruning:
    def _touch(self, directory, name, mtime):
        path = os.path.join(str(directory), name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("x")
        os.utime(path, (mtime, mtime))
        return path

    def test_it_keeps_the_newest_sessions_and_drops_the_rest(self, tmp_path):
        for pid in range(1, 6):
            self._touch(tmp_path, "plugin-%d.log" % pid, 1_000_000 + pid * 100)
        logsetup.prune("plugin", directory=str(tmp_path), keep_sessions=2)
        left = sorted(os.listdir(str(tmp_path)))
        assert left == ["plugin-4.log", "plugin-5.log"]

    def test_a_sessions_backups_go_with_it(self, tmp_path):
        self._touch(tmp_path, "plugin-1.log", 1_000_100)
        self._touch(tmp_path, "plugin-1.log.1", 1_000_050)
        self._touch(tmp_path, "plugin-9.log", 2_000_000)
        logsetup.prune("plugin", directory=str(tmp_path), keep_sessions=1)
        assert sorted(os.listdir(str(tmp_path))) == ["plugin-9.log"]

    def test_the_legacy_shared_log_is_never_deleted(self, tmp_path):
        # plugin.log and its backups predate this fix and are somebody's record
        # of an incident; pruning must not reap history it did not create.
        for name in ("plugin.log", "plugin.log.1", "plugin.log.3"):
            self._touch(tmp_path, name, 1_000_000)
        for pid in range(1, 4):
            self._touch(tmp_path, "plugin-%d.log" % pid, 2_000_000 + pid)
        logsetup.prune("plugin", directory=str(tmp_path), keep_sessions=0)
        assert sorted(os.listdir(str(tmp_path))) == [
            "plugin.log",
            "plugin.log.1",
            "plugin.log.3",
        ]

    def test_another_stems_logs_are_left_alone(self, tmp_path):
        self._touch(tmp_path, "server-1.log", 1_000_000)
        self._touch(tmp_path, "plugin-1.log", 1_000_000)
        logsetup.prune("plugin", directory=str(tmp_path), keep_sessions=0)
        assert os.listdir(str(tmp_path)) == ["server-1.log"]

    def test_a_held_log_survives_pruning(self, tmp_path):
        held = self._touch(tmp_path, "plugin-1.log", 1_000_000)
        with open(held, "a", encoding="utf-8"):
            logsetup.prune("plugin", directory=str(tmp_path), keep_sessions=0)
            survived = os.path.exists(held)
        # On Windows the OS itself is the interlock protecting a live session.
        if not survived:
            pytest.skip("this platform can delete a file that is held open")

    def test_a_missing_directory_is_not_an_error(self, tmp_path):
        assert logsetup.prune("plugin", directory=str(tmp_path / "nope")) == []


class TestConfigure:
    def test_it_attaches_one_handler_and_only_one(self, tmp_path):
        log = logging.getLogger("t650.configure")
        log.handlers = []
        first = logsetup.configure(log, "plugin", directory=str(tmp_path))
        second = logsetup.configure(log, "plugin", directory=str(tmp_path))
        try:
            assert first is second
            assert len(log.handlers) == 1
        finally:
            first.close()
            log.handlers = []

    def test_it_writes_to_the_process_private_path(self, tmp_path):
        log = logging.getLogger("t650.writes")
        log.handlers = []
        handler = logsetup.configure(log, "plugin", directory=str(tmp_path))
        try:
            log.info("hello from the fixture")
        finally:
            handler.close()
            log.handlers = []
        expected = str(tmp_path / ("plugin-%d.log" % os.getpid()))
        assert "hello from the fixture" in _read(expected)

    def test_a_bad_log_level_does_not_raise(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MAYA_MCP_LOG_LEVEL", "trace ")
        log = logging.getLogger("t650.badlevel")
        log.handlers = []
        handler = logsetup.configure(log, "plugin", directory=str(tmp_path))
        try:
            assert log.level == logging.INFO
        finally:
            handler.close()
            log.handlers = []

    def test_an_unwritable_directory_is_a_no_op_not_a_crash(self, tmp_path):
        # A file where the log directory should be: makedirs must fail.
        blocker = tmp_path / "blocked"
        blocker.write_text("not a directory", encoding="utf-8")
        log = logging.getLogger("t650.unwritable")
        log.handlers = []
        assert logsetup.configure(log, "plugin", directory=str(blocker / "logs")) is None
        assert log.handlers == []

    def test_configure_prunes_before_it_opens(self, tmp_path):
        stale = tmp_path / "plugin-999999.log"
        stale.write_text("old", encoding="utf-8")
        os.utime(str(stale), (1_000_000, 1_000_000))
        log = logging.getLogger("t650.prunes")
        log.handlers = []
        handler = logsetup.configure(
            log, "plugin", directory=str(tmp_path), keep_sessions=0
        )
        try:
            assert not stale.exists()
        finally:
            handler.close()
            log.handlers = []
