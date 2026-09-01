"""Deployed-plugin staleness handshake: digest, stamp, and the mismatch warning.

The failure this guards against is a GREEN RESULT THAT MEANS NOTHING - the live
Maya importing a copy of the plugin that predates the code under test. Every
test here is headless and touches only tmp dirs.
"""

import json
import os
import subprocess

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


def _git(cwd, *args):
    """git in a throwaway fixture repo, with an identity of its own so the test
    does not depend on whatever the machine's global config happens to hold."""
    out = subprocess.run(
        ("git", "-c", "user.email=fixture@example.invalid", "-c", "user.name=fixture",
         "-c", "commit.gpgsign=false") + args,
        cwd=cwd, capture_output=True, text=True, timeout=30,
    )
    assert out.returncode == 0, "git %s failed: %s%s" % (args, out.stdout, out.stderr)
    return out.stdout


def _fixture_repo(root):
    """A real repo shaped like this one: a maya_plugin/ package that ships, an
    evals/ tree that does not, and the .gitignore rules that hide bytecode.

    Deliberately NOT a subprocess mock. The defect #796 closes is in what git is
    ASKED - a canned return value answers every pathspec identically, so a mock
    can only ever confirm the bug.
    """
    os.makedirs(os.path.join(root, "maya_plugin", "handlers"))
    os.makedirs(os.path.join(root, "evals"))
    _pkg(os.path.join(root, "maya_plugin"), {"version.py": "x = 1\n", "handlers/b.py": "y = 2\n"})
    _pkg(root, {".gitignore": "__pycache__/\n*.pyc\n", "README.md": "readme\n"})
    _git(root, "init")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    return root


class TestGitStampScopesDirtToThePackage:
    """#796: the stamp describes the DEPLOYED package, so only maya_plugin/ can
    dirty it. Before this, any untracked file anywhere - and this repo always
    carries a dozen untracked eval OUTPUT dirs - stamped every install +dirty,
    which is why deploys were done from throwaway worktrees."""

    def test_a_clean_checkout_is_clean(self, tmp_path):
        repo = _fixture_repo(str(tmp_path / "repo"))
        assert version.git_stamp(repo)["dirty"] is False

    def test_an_untracked_file_outside_the_package_leaves_the_stamp_clean(self, tmp_path):
        """A rendered eval output cannot change what was installed."""
        repo = _fixture_repo(str(tmp_path / "repo"))
        _pkg(os.path.join(repo, "evals"), {"out.png": "not really a png\n"})
        assert version.git_stamp(repo)["dirty"] is False

    def test_an_untracked_directory_outside_the_package_leaves_the_stamp_clean(self, tmp_path):
        """The shape this repo actually carries: `?? evals/surfdetail_live/`."""
        repo = _fixture_repo(str(tmp_path / "repo"))
        _pkg(os.path.join(repo, "evals", "surfdetail_live"), {"render.png": "bytes\n"})
        assert version.git_stamp(repo)["dirty"] is False

    def test_a_modification_inside_the_package_still_reports_dirty(self, tmp_path):
        repo = _fixture_repo(str(tmp_path / "repo"))
        _pkg(os.path.join(repo, "maya_plugin"), {"version.py": "x = 2  # edited\n"})
        assert version.git_stamp(repo)["dirty"] is True

    def test_a_modification_in_a_package_subdirectory_still_reports_dirty(self, tmp_path):
        repo = _fixture_repo(str(tmp_path / "repo"))
        _pkg(os.path.join(repo, "maya_plugin"), {"handlers/b.py": "y = 99\n"})
        assert version.git_stamp(repo)["dirty"] is True

    def test_a_new_untracked_file_inside_the_package_reports_dirty(self, tmp_path):
        """The #718-class miss: a handler module that exists only in the working
        tree ships in the copy, so it MUST count."""
        repo = _fixture_repo(str(tmp_path / "repo"))
        _pkg(os.path.join(repo, "maya_plugin"), {"handlers/c.py": "z = 3\n"})
        assert version.git_stamp(repo)["dirty"] is True

    def test_a_deleted_file_inside_the_package_reports_dirty(self, tmp_path):
        repo = _fixture_repo(str(tmp_path / "repo"))
        os.unlink(os.path.join(repo, "maya_plugin", "handlers", "b.py"))
        assert version.git_stamp(repo)["dirty"] is True

    def test_bytecode_under_the_package_is_not_dirt(self, tmp_path):
        """The inert-fix trap (#714, #772, #775 all shipped one). Scoping to
        maya_plugin only helps if .gitignore already hides the __pycache__ that
        every import writes there - otherwise the stamp swaps one permanent
        false dirty for another."""
        repo = _fixture_repo(str(tmp_path / "repo"))
        _pkg(os.path.join(repo, "maya_plugin", "__pycache__"),
             {"version.cpython-311.pyc": "\x00compiled\n"})
        assert version.git_stamp(repo)["dirty"] is False

    def test_this_repos_own_bytecode_is_ignored(self):
        """The same claim against the REAL checkout, where the .pyc files are
        already on disk - the fixture's .gitignore is written by this test, and
        proving the fix on a tree of the test's own making proves nothing."""
        repo = os.path.dirname(os.path.dirname(os.path.abspath(version.__file__)))
        out = subprocess.run(
            # The pathspec the module actually uses, not a hand-copied twin -
            # a duplicate here could drift and keep passing (#796).
            ("git", "status", "--porcelain", "--", version._PACKAGE_PATHSPEC),
            cwd=repo, capture_output=True, text=True, timeout=30,
        )
        assert out.returncode == 0
        assert "__pycache__" not in out.stdout
        assert ".pyc" not in out.stdout

    def test_not_a_repo_still_returns_the_documented_shape(self, tmp_path):
        """Unchanged contract: "cannot tell" stays a distinct answer, and the
        key set is what install.py destructures."""
        stamp = version.git_stamp(str(tmp_path))
        assert set(stamp) == {"commit", "dirty"}
        assert stamp["commit"] is None
        assert stamp["dirty"] is None


def _repo_without_the_package(root):
    """A real repo that ships no maya_plugin/ at all - a stripped clone, a
    consumer checkout, or simply the wrong directory handed to git_stamp."""
    os.makedirs(os.path.join(root, "evals"))
    _pkg(root, {".gitignore": "__pycache__/\n*.pyc\n", "README.md": "readme\n"})
    _git(root, "init")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    return root


class TestGitStampWithoutAPackagedTreeCannotTell:
    """#796 review: a pathspec that matches NOTHING makes git exit 0 printing
    nothing - byte-identical to "the packaged tree is clean" (measured). The
    first cut of the scoping read that as a confident False, which silently
    narrowed the contract from "any directory in a working tree" to "a directory
    that happens to contain maya_plugin". This module's standing rule is the
    opposite: "cannot tell" is a distinct answer from "differs"."""

    def test_a_subdirectory_of_the_worktree_still_sees_the_package(self, tmp_path):
        """The reviewer's measured case: git_stamp(<repo>/evals) reported a
        false clean while three plugin files were edited. The pathspec is
        anchored at the repo top now, so any directory in the tree answers."""
        repo = _fixture_repo(str(tmp_path / "repo"))
        _pkg(os.path.join(repo, "maya_plugin"), {"version.py": "x = 2  # edited\n"})
        assert version.git_stamp(os.path.join(repo, "evals"))["dirty"] is True

    def test_a_clean_subdirectory_of_the_worktree_reads_clean(self, tmp_path):
        """And the anchoring must not turn every subdirectory into "unknown"."""
        repo = _fixture_repo(str(tmp_path / "repo"))
        assert version.git_stamp(os.path.join(repo, "evals"))["dirty"] is False

    def test_a_repo_that_ships_no_package_cannot_tell(self, tmp_path):
        """No maya_plugin anywhere in the tree: there is no deployed package for
        the flag to describe, so False would be an answer to a question nobody
        asked. The commit half is still perfectly knowable."""
        repo = _repo_without_the_package(str(tmp_path / "bare"))
        _pkg(repo, {"README.md": "edited\n"})
        stamp = version.git_stamp(repo)
        assert stamp["commit"] is not None
        assert stamp["dirty"] is None

    def test_a_repo_that_ships_no_package_cannot_tell_when_clean_either(self, tmp_path):
        """Not a dirt detector wearing a disguise - the answer is "cannot tell"
        whatever the rest of the tree looks like."""
        repo = _repo_without_the_package(str(tmp_path / "bare"))
        assert version.git_stamp(repo)["dirty"] is None

    def test_the_cannot_tell_answer_keeps_the_documented_shape(self, tmp_path):
        """install.py destructures this dict; a new key or a missing one would
        break the caller more loudly than the wrong flag ever did."""
        repo = _repo_without_the_package(str(tmp_path / "bare"))
        assert set(version.git_stamp(repo)) == {"commit", "dirty"}
