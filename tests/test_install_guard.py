"""#755: install.py must refuse to overwrite a NEWER deployed plugin with an
OLDER source tree.

The hazard is not hypothetical. `D:\\devel\\maya-mcp-art` holds a maya_plugin
from a divergent branch missing seven handler modules entirely; one
`install.py --yes` from that root strips half the toolset out of every Maya on
the machine, silently, because install.py never looked at what it was replacing.

Every test here builds a REAL git repository in tmp_path and stamps a REAL
deployed copy, so the relation being asserted is the one git actually reports.
"""

import json
import os
import shutil
import subprocess
import sys

import pytest

from maya_plugin import version

REAL_PKG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "maya_plugin"
)


def _git(repo, *args):
    out = subprocess.run(
        ("git",) + args, cwd=repo, capture_output=True, text=True, timeout=30
    )
    assert out.returncode == 0, "git %s failed: %s" % (" ".join(args), out.stderr)
    return out.stdout.strip()


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _commit(repo, message):
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    """A source repo with a maya_plugin package and one commit.

    It carries the REAL version.py and install.py, so the end-to-end tests can
    run the installer as a user runs it - `python maya_plugin/install.py` from
    the repo root - instead of reaching into this process."""
    root = str(tmp_path / "repo")
    pkg = os.path.join(root, "maya_plugin")
    _write(os.path.join(pkg, "__init__.py"), "")
    _write(os.path.join(pkg, "handlers", "clip.py"), "# clip\n")
    for name in ("version.py", "install.py"):
        os.makedirs(pkg, exist_ok=True)
        shutil.copy2(os.path.join(REAL_PKG, name), os.path.join(pkg, name))
    _git(root, "init", "-q", "-b", "main")
    first = _commit(root, "first")
    return {"root": root, "pkg": pkg, "first": first}


def _deploy(tmp_path, source_pkg, commit, name="deployed"):
    """Stand in for a previous install: copy the package and stamp it."""
    target = str(tmp_path / name / "maya_plugin")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.copytree(source_pkg, target)
    version.write_stamp(target, commit=commit, dirty=False)
    return target


class TestCommitRelation:
    """The five rows of the table, each against real git history."""

    def test_the_same_commit_relates_as_same(self, repo):
        assert version.commit_relation(
            repo["root"], repo["first"], repo["first"]
        ) == "same"

    def test_a_deployed_ancestor_relates_as_upgrade(self, repo):
        _write(os.path.join(repo["pkg"], "handlers", "rigging.py"), "# rigging\n")
        second = _commit(repo["root"], "second")
        assert version.commit_relation(
            repo["root"], second, repo["first"]
        ) == "upgrade"

    def test_an_older_source_relates_as_downgrade(self, repo):
        _write(os.path.join(repo["pkg"], "handlers", "rigging.py"), "# rigging\n")
        second = _commit(repo["root"], "second")
        assert version.commit_relation(
            repo["root"], repo["first"], second
        ) == "downgrade"

    def test_two_branches_relate_as_divergent(self, repo):
        """The art-worktree shape: neither commit reaches the other."""
        _write(os.path.join(repo["pkg"], "handlers", "rigging.py"), "# rigging\n")
        main_tip = _commit(repo["root"], "main work")
        _git(repo["root"], "checkout", "-q", "-b", "art", repo["first"])
        _write(os.path.join(repo["pkg"], "handlers", "art.py"), "# art\n")
        art_tip = _commit(repo["root"], "art work")
        assert version.commit_relation(repo["root"], art_tip, main_tip) == "divergent"

    def test_an_unknown_commit_relates_as_unknown(self, repo):
        """A stamp from another clone, or a deleted branch: git cannot answer,
        and 'cannot tell' is not 'differs'."""
        assert version.commit_relation(
            repo["root"], repo["first"], "0" * 40
        ) == "unknown"

    def test_a_missing_commit_relates_as_unknown(self, repo):
        assert version.commit_relation(repo["root"], repo["first"], None) == "unknown"


class TestModuleRegression:
    """The git-free backstop: a capability regression is visible in the file
    list alone, which is the shape a copied-around tree with no git takes."""

    def test_a_source_missing_modules_and_adding_none_is_a_regression(self, tmp_path, repo):
        target = _deploy(tmp_path, repo["pkg"], repo["first"])
        os.unlink(os.path.join(repo["pkg"], "handlers", "clip.py"))
        assert version.module_regression(repo["pkg"], target) == ["handlers/clip.py"]

    def test_a_source_that_also_adds_modules_is_not_a_regression(self, tmp_path, repo):
        """Deleting a handler while adding another is a refactor, not a
        rollback. Refusing it would make the guard a nuisance."""
        target = _deploy(tmp_path, repo["pkg"], repo["first"])
        os.unlink(os.path.join(repo["pkg"], "handlers", "clip.py"))
        _write(os.path.join(repo["pkg"], "handlers", "clip2.py"), "# successor\n")
        assert version.module_regression(repo["pkg"], target) == []

    def test_an_identical_module_set_is_not_a_regression(self, tmp_path, repo):
        target = _deploy(tmp_path, repo["pkg"], repo["first"])
        assert version.module_regression(repo["pkg"], target) == []

    def test_the_stamp_itself_is_never_counted_as_a_module(self, tmp_path, repo):
        """The deployed copy always carries a stamp the source does not."""
        target = _deploy(tmp_path, repo["pkg"], repo["first"])
        assert version.STAMP_NAME not in version.module_regression(repo["pkg"], target)


class TestDeployGuard:
    """The composed verdict install.py acts on: refusal text, or None."""

    def test_an_upgrade_proceeds(self, tmp_path, repo):
        target = _deploy(tmp_path, repo["pkg"], repo["first"])
        _write(os.path.join(repo["pkg"], "handlers", "rigging.py"), "# rigging\n")
        _commit(repo["root"], "second")
        assert version.deploy_guard(repo["pkg"], target, repo["root"]) is None

    def test_a_reinstall_of_the_same_commit_proceeds(self, tmp_path, repo):
        target = _deploy(tmp_path, repo["pkg"], repo["first"])
        assert version.deploy_guard(repo["pkg"], target, repo["root"]) is None

    def test_a_downgrade_is_refused_and_names_both_commits(self, tmp_path, repo):
        _write(os.path.join(repo["pkg"], "handlers", "rigging.py"), "# rigging\n")
        second = _commit(repo["root"], "second")
        target = _deploy(tmp_path, repo["pkg"], second)
        _git(repo["root"], "checkout", "-q", repo["first"])

        refusal = version.deploy_guard(repo["pkg"], target, repo["root"])
        assert refusal is not None
        assert "REFUSING" in refusal
        assert repo["first"][:12] in refusal
        assert second[:12] in refusal
        assert "--force" in refusal

    def test_a_divergent_source_is_refused(self, tmp_path, repo):
        _write(os.path.join(repo["pkg"], "handlers", "rigging.py"), "# rigging\n")
        main_tip = _commit(repo["root"], "main work")
        target = _deploy(tmp_path, repo["pkg"], main_tip)
        _git(repo["root"], "checkout", "-q", "-b", "art", repo["first"])
        _write(os.path.join(repo["pkg"], "handlers", "art.py"), "# art\n")
        _commit(repo["root"], "art work")

        refusal = version.deploy_guard(repo["pkg"], target, repo["root"])
        assert refusal is not None
        assert "REFUSING" in refusal
        assert "diverge" in refusal.lower()

    def test_an_unstamped_target_proceeds(self, tmp_path, repo):
        """Nothing to protect: an unstamped copy predates the handshake, and
        blocking on it would strand anyone upgrading from an old install."""
        target = _deploy(tmp_path, repo["pkg"], repo["first"])
        os.unlink(os.path.join(target, version.STAMP_NAME))
        assert version.deploy_guard(repo["pkg"], target, repo["root"]) is None

    def test_a_missing_target_proceeds(self, tmp_path, repo):
        target = str(tmp_path / "nothing" / "maya_plugin")
        assert version.deploy_guard(repo["pkg"], target, repo["root"]) is None

    def test_without_git_a_module_regression_is_still_refused(self, tmp_path, repo):
        """The backstop carries the verdict when the commit cannot: a stamp git
        does not recognise, and a source that only removes modules."""
        target = _deploy(tmp_path, repo["pkg"], "0" * 40)
        os.unlink(os.path.join(repo["pkg"], "handlers", "clip.py"))
        refusal = version.deploy_guard(repo["pkg"], target, repo["root"])
        assert refusal is not None
        assert "handlers/clip.py" in refusal
        assert "--force" in refusal

    def test_without_git_and_without_a_regression_it_proceeds(self, tmp_path, repo):
        target = _deploy(tmp_path, repo["pkg"], "0" * 40)
        _write(os.path.join(repo["pkg"], "handlers", "extra.py"), "# extra\n")
        assert version.deploy_guard(repo["pkg"], target, repo["root"]) is None


class TestInstallerHonoursTheGuard:
    """End to end through install.main(), because the verdict is worthless if
    the installer does not act on it."""

    def _run(self, repo, scripts_dir, *extra):
        """Exactly the command a user types, from the source tree's own root."""
        out = subprocess.run(
            [sys.executable, os.path.join("maya_plugin", "install.py"),
             "--yes", "--scripts-dir", str(scripts_dir)] + list(extra),
            cwd=repo["root"], capture_output=True, text=True, timeout=120,
        )
        return out.returncode, out.stdout + out.stderr

    def _stale_setup(self, tmp_path, repo):
        """A deployed copy from a newer commit, and a source rolled back."""
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        _write(os.path.join(repo["pkg"], "handlers", "rigging.py"), "# rigging\n")
        second = _commit(repo["root"], "second")
        target = str(scripts / "maya_plugin")
        shutil.copytree(repo["pkg"], target)
        version.write_stamp(target, commit=second, dirty=False)
        _git(repo["root"], "checkout", "-q", repo["first"])
        return scripts, target, second

    def test_the_installer_refuses_and_leaves_the_copy_untouched(self, tmp_path, repo):
        scripts, target, second = self._stale_setup(tmp_path, repo)
        before = version.package_digest(target)

        code, output = self._run(repo, scripts)

        assert code != 0
        assert version.package_digest(target) == before, "the guard must refuse BEFORE the rmtree"
        assert os.path.exists(os.path.join(target, "handlers", "rigging.py"))
        with open(os.path.join(target, version.STAMP_NAME), encoding="utf-8") as fh:
            assert json.load(fh)["commit"] == second
        assert "REFUSING" in output

    def test_force_overrides_the_refusal(self, tmp_path, repo):
        scripts, target, _ = self._stale_setup(tmp_path, repo)

        code, _ = self._run(repo, scripts, "--force")

        assert code == 0
        assert not os.path.exists(os.path.join(target, "handlers", "rigging.py"))
        assert version.read_stamp(target)["commit"] == repo["first"]
