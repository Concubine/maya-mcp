"""Deployed-plugin staleness handshake: digest, stamp, and the mismatch warning.

The failure this guards against is a GREEN RESULT THAT MEANS NOTHING - the live
Maya importing a copy of the plugin that predates the code under test. Every
test here is headless and touches only tmp dirs.
"""

import json
import os

from maya_plugin import version


def _pkg(root, files):
    os.makedirs(root, exist_ok=True)
    for rel, text in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    return root


class TestPackageDigest:
    def test_identical_trees_digest_the_same(self, tmp_path):
        files = {"a.py": "x = 1\n", "handlers/b.py": "y = 2\n"}
        one = _pkg(str(tmp_path / "one"), files)
        two = _pkg(str(tmp_path / "two"), files)
        assert version.package_digest(one) == version.package_digest(two)

    def test_a_changed_line_changes_the_digest(self, tmp_path):
        one = _pkg(str(tmp_path / "one"), {"a.py": "x = 1\n"})
        two = _pkg(str(tmp_path / "two"), {"a.py": "x = 2\n"})
        assert version.package_digest(one) != version.package_digest(two)

    def test_a_missing_module_changes_the_digest(self, tmp_path):
        """The exact shape of the bug this closes: `cannot import name 'combine'`
        because a NEW module was never deployed."""
        full = _pkg(str(tmp_path / "full"), {"a.py": "x = 1\n", "combine.py": "z = 3\n"})
        stale = _pkg(str(tmp_path / "stale"), {"a.py": "x = 1\n"})
        assert version.package_digest(full) != version.package_digest(stale)

    def test_the_path_matters_not_just_the_bytes(self, tmp_path):
        one = _pkg(str(tmp_path / "one"), {"a.py": "x = 1\n"})
        two = _pkg(str(tmp_path / "two"), {"b.py": "x = 1\n"})
        assert version.package_digest(one) != version.package_digest(two)

    def test_ignores_pycache_the_stamp_and_the_installer(self, tmp_path):
        """install.py is never copied and the stamp is written after the copy, so
        counting either would make every freshly installed plugin read stale."""
        base = {"a.py": "x = 1\n"}
        clean = _pkg(str(tmp_path / "clean"), base)
        noisy = _pkg(str(tmp_path / "noisy"), dict(base, **{
            "install.py": "print('installer')\n",
            version.STAMP_NAME: '{"commit": "deadbeef"}',
            "__pycache__/a.cpython-311.pyc": "compiled junk",
        }))
        assert version.package_digest(clean) == version.package_digest(noisy)

    def test_missing_directory_digests_to_none(self, tmp_path):
        assert version.package_digest(str(tmp_path / "nope")) is None


class TestStamp:
    def test_write_then_read_round_trips(self, tmp_path):
        pkg = _pkg(str(tmp_path / "pkg"), {"a.py": "x = 1\n"})
        written = version.write_stamp(pkg, commit="abc1234", dirty=False)
        read = version.read_stamp(pkg)
        assert read["commit"] == "abc1234"
        assert read["dirty"] is False
        assert read["installed_at"] == written["installed_at"]

    def test_read_returns_none_when_never_installed(self, tmp_path):
        pkg = _pkg(str(tmp_path / "pkg"), {"a.py": "x = 1\n"})
        assert version.read_stamp(pkg) is None

    def test_read_returns_none_on_corrupt_stamp(self, tmp_path):
        """A broken stamp must degrade to 'unstamped', never take ping down."""
        pkg = _pkg(str(tmp_path / "pkg"), {"a.py": "x = 1\n",
                                           version.STAMP_NAME: "{not json"})
        assert version.read_stamp(pkg) is None

    def test_stamp_records_the_digest_of_what_was_installed(self, tmp_path):
        pkg = _pkg(str(tmp_path / "pkg"), {"a.py": "x = 1\n"})
        version.write_stamp(pkg, commit="abc1234", dirty=True)
        assert version.read_stamp(pkg)["digest"] == version.package_digest(pkg)

    def test_stamp_is_json_a_human_can_read(self, tmp_path):
        pkg = _pkg(str(tmp_path / "pkg"), {"a.py": "x = 1\n"})
        version.write_stamp(pkg, commit="abc1234", dirty=False)
        with open(os.path.join(pkg, version.STAMP_NAME), encoding="utf-8") as fh:
            assert json.load(fh)["commit"] == "abc1234"


class TestCompare:
    def _info(self, digest, **stamp):
        return {"package_dir": "C:/fake/maya_plugin", "digest": digest,
                "stamp": (stamp or None)}

    def test_matching_digests_are_silent(self):
        assert version.compare(self._info("aaa", commit="abc1234"), "aaa") is None

    def test_mismatch_names_both_sides_and_how_to_fix_it(self):
        warning = version.compare(
            self._info("aaa", commit="abc1234", installed_at="2026-08-01T10:00:00Z"),
            "bbb",
            working_commit="9999999",
        )
        assert warning is not None
        assert "abc1234" in warning and "9999999" in warning
        assert "2026-08-01" in warning
        assert "install.py" in warning
        assert "restart" in warning.lower()  # a reinstall alone does not reload Maya

    def test_unstamped_plugin_still_compares_by_digest(self):
        """Installed before the handshake existed, or copied by hand - the digest
        is the truth, the stamp is only there to name the commit."""
        assert version.compare(self._info("aaa"), "aaa") is None
        assert version.compare(self._info("aaa"), "bbb") is not None

    def test_plugin_that_reports_no_digest_at_all_is_a_warning(self):
        """A plugin too old to know about this handshake is exactly the stale copy
        we are hunting - silence here would be the bug."""
        assert version.compare({"package_dir": "x"}, "aaa") is not None
        assert version.compare(None, "aaa") is not None

    def test_unknown_working_digest_does_not_cry_wolf(self):
        """No repo to compare against (installed wheel, odd cwd) - say nothing
        rather than warn on every call."""
        assert version.compare(self._info("aaa"), None) is None

    def test_warning_mentions_the_deployed_package_dir(self):
        warning = version.compare(self._info("aaa"), "bbb")
        assert "C:/fake/maya_plugin" in warning


class TestCompareDeployedButNotRestarted:
    """#604: the handshake read CLEAN in the one window where the danger is
    real - after install.py, before a restart - because it judged by the disk,
    and the disk is exactly the copy that is NOT running then. #640 hit it too:
    two fresh fixes read as regressions against a stale in-memory plugin."""

    def _window(self):
        """The #604 window: session loaded OLD, disk holds NEW == working tree."""
        return {
            "package_dir": "C:/fake/maya_plugin",
            "digest": "newnewnew",
            "stamp": {"commit": "fff9999", "installed_at": "2026-08-19T10:00:00Z"},
            "loaded_digest": "oldoldold",
            "loaded_stamp": {"commit": "aaa1111", "installed_at": "2026-08-15T09:00:00Z"},
        }

    def test_the_604_window_is_a_warning_not_a_clean(self):
        warning = version.compare(self._window(), "newnewnew")
        assert warning is not None, (
            "disk == working tree read as CLEAN while the session ran old code - "
            "this is precisely the #604 bug"
        )

    def test_the_warning_says_restart_not_redeploy(self):
        """install.py has already run; telling the caller to run it again sends
        them around the loop that cannot fix anything."""
        warning = version.compare(self._window(), "newnewnew")
        assert "NOT restarted" in warning
        assert "RESTART" in warning
        assert "redeploy" not in warning

    def test_the_stamp_shown_is_the_running_code_s_not_the_disk_s(self):
        """The caller's question is 'whose results am I reading' - that is the
        loaded commit. Showing the freshly installed one would name the code
        that is precisely not answering."""
        warning = version.compare(self._window(), "newnewnew")
        assert "aaa1111" in warning
        assert "fff9999" not in warning

    def test_loaded_matching_the_working_tree_is_clean_even_if_disk_moved(self):
        """Someone deployed ANOTHER tree after this session loaded. Live results
        still describe this working tree, so this caller gets silence; the
        other tree's deployer gets the warning on their own check."""
        info = self._window()
        info["loaded_digest"] = "mine"
        info["digest"] = "someone-elses"
        assert version.compare(info, "mine") is None

    def test_a_plugin_without_the_loaded_field_keeps_disk_semantics(self):
        """A pre-#604 plugin reports only the disk digest; treating its absence
        as stale would warn on every old-but-matching deploy."""
        old_style = {"package_dir": "x", "digest": "aaa", "stamp": None}
        assert version.compare(old_style, "aaa") is None
        assert version.compare(old_style, "bbb") is not None

    def test_ordinary_stale_still_says_redeploy(self):
        """When the disk does NOT hold the working tree, restarting alone is
        wrong advice - the full hint must survive the new branch."""
        info = self._window()
        info["digest"] = "also-old"
        warning = version.compare(info, "newnewnew")
        assert "install.py" in warning


class TestPluginInfo:
    def test_reports_digest_and_stamp_for_the_live_package(self, tmp_path):
        pkg = _pkg(str(tmp_path / "maya_plugin"), {"a.py": "x = 1\n"})
        version.write_stamp(pkg, commit="abc1234", dirty=False)
        info = version.plugin_info(pkg)
        assert info["package_dir"] == pkg
        assert info["digest"] == version.package_digest(pkg)
        assert info["stamp"]["commit"] == "abc1234"

    def test_defaults_to_the_package_this_module_was_imported_from(self):
        info = version.plugin_info()
        assert info["package_dir"] == os.path.dirname(os.path.abspath(version.__file__))
        assert info["digest"]  # this repo checkout is a real package

    def test_never_raises_on_an_unreadable_package(self, tmp_path):
        info = version.plugin_info(str(tmp_path / "gone"))
        assert info["digest"] is None and info["stamp"] is None

    def test_the_default_package_reports_what_it_loaded(self):
        """For the package this module lives in, ping must say what the session
        imported, not just what is on disk now - the two diverge in exactly the
        window #604 is about. Here they coincide (nothing redeployed mid-test),
        which is also the assertion."""
        info = version.plugin_info()
        assert info["loaded_digest"] == info["digest"]
        assert info["restart_required"] is False
        assert info["imported_at"]

    def test_an_explicit_other_package_has_no_loaded_identity(self, tmp_path):
        """install verification points at the DEPLOYED dir from the repo's own
        interpreter; claiming a loaded identity for a package this process never
        imported would be the same lie in the other direction."""
        pkg = _pkg(str(tmp_path / "maya_plugin"), {"a.py": "x = 1\n"})
        info = version.plugin_info(pkg)
        assert "loaded_digest" not in info
        assert "restart_required" not in info


class TestGitStamp:
    def test_reads_the_commit_of_this_repo(self):
        repo = os.path.dirname(os.path.dirname(os.path.abspath(version.__file__)))
        stamp = version.git_stamp(repo)
        assert stamp["commit"] is None or len(stamp["commit"]) >= 7

    def test_no_repo_gives_an_unknown_commit_rather_than_an_error(self, tmp_path):
        stamp = version.git_stamp(str(tmp_path))
        assert stamp["commit"] is None
        assert stamp["dirty"] is None
