"""install.py: the deploy step, and the stamp that makes staleness visible.

Installs this repo's real maya_plugin into a tmp "scripts dir", so the whole
handshake is exercised end to end - copy, stamp, then compare the deployed copy
against the working tree exactly as evals/live_call.py does.
"""

import os
import sys

from maya_plugin import install, version

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_PKG = os.path.join(REPO_ROOT, "maya_plugin")


def _install(tmp_path, monkeypatch):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(
        sys, "argv",
        ["install.py", "--yes", "--scripts-dir", str(scripts_dir)],
    )
    assert install.main() == 0
    return str(scripts_dir / "maya_plugin")


class TestInstall:
    def test_a_fresh_install_reads_as_current(self, tmp_path, monkeypatch):
        """The check's whole value rests on this: install, and the warning is
        silent. If a clean deploy warned, every run would learn to ignore it."""
        target = _install(tmp_path, monkeypatch)
        plugin = version.plugin_info(target)
        assert version.compare(plugin, version.package_digest(SOURCE_PKG)) is None

    def test_a_missing_module_makes_the_install_read_stale(self, tmp_path, monkeypatch):
        """The revision-2 failure, reproduced: the deployed copy lacks a module
        the working tree has, and the first live gate dies on ImportError."""
        target = _install(tmp_path, monkeypatch)
        os.unlink(os.path.join(target, "handlers", "combine.py"))
        warning = version.compare(
            version.plugin_info(target), version.package_digest(SOURCE_PKG)
        )
        assert warning is not None
        assert "STALE PLUGIN" in warning
        assert "install.py" in warning

    def test_the_stamp_records_the_commit_it_was_cut_from(self, tmp_path, monkeypatch):
        target = _install(tmp_path, monkeypatch)
        stamp = version.read_stamp(target)
        assert stamp is not None
        assert stamp["installed_at"].endswith("Z")
        # This repo is a git checkout, so the commit is real; if git ever cannot
        # answer, the stamp still exists and the digest still does the work.
        assert stamp["commit"] == version.git_stamp(REPO_ROOT)["commit"]

    def test_the_installer_itself_is_not_deployed(self, tmp_path, monkeypatch):
        target = _install(tmp_path, monkeypatch)
        assert not os.path.exists(os.path.join(target, "install.py"))

    def test_reinstalling_over_a_previous_copy_clears_stale_files(self, tmp_path, monkeypatch):
        target = _install(tmp_path, monkeypatch)
        orphan = os.path.join(target, "handlers", "removed_last_milestone.py")
        with open(orphan, "w", encoding="utf-8") as fh:
            fh.write("# left over from an older deploy\n")
        _install(tmp_path, monkeypatch)
        assert not os.path.exists(orphan)
        assert version.compare(
            version.plugin_info(target), version.package_digest(SOURCE_PKG)
        ) is None
