"""Deployed-plugin staleness handshake.

The live Maya imports <Documents>/maya/scripts/maya_plugin - NOT this repo - so
a live check can pass, or fail, against code that is nothing like the working
tree. It has cost this project hours twice: once at M2.4 with a deployed copy
eight tasks behind, and again on the revision-2 art run, where the first live
gate died on `ImportError: cannot import name 'combine'` because two new modules
had never been deployed. The expensive part is never the fix - it is the time
spent believing the result.

The truth here is a CONTENT DIGEST, not a commit: it catches a hand-edited
deployed copy and an install cut from a dirty tree, and it needs no git inside
Maya. The commit recorded alongside it is for human legibility only.

Nothing in this module may raise into a caller. A staleness warning that breaks
the run it was meant to protect is worse than no warning at all.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, Optional

STAMP_NAME = "deployed_stamp.json"

# What `git_stamp` asks git about. `:(top)` pins it to the repository root, so
# the answer is the same from any directory in the working tree - a bare
# "maya_plugin" resolves against the cwd and matches nothing one level down
# (#796). Kept beside install.py's copy source: they must name the same tree.
_PACKAGE_PATHSPEC = ":(top)maya_plugin"

# Never copied into the deployed package (install.py), or written after the copy
# (the stamp) - counting either would make a freshly installed plugin read stale.
_IGNORED_NAMES = {"__pycache__", "install.py", STAMP_NAME}

INSTALL_HINT = (
    "redeploy:  python maya_plugin/install.py --yes\n"
    "then RESTART Maya (or re-import the plugin) - a reinstall alone does not\n"
    "reload modules Python has already imported."
)

RESTART_HINT = (
    "RESTART Maya (or re-import the plugin). The install has already run -\n"
    "running it again cannot help, because Python is still holding the modules\n"
    "it imported before the deploy."
)


def _iter_sources(package_dir: str):
    """(relative posix path, absolute path) for every source file that is
    actually deployed, sorted so the digest is stable across filesystems."""
    found = []
    for root, dirs, files in os.walk(package_dir):
        dirs[:] = sorted(d for d in dirs if d not in _IGNORED_NAMES)
        for name in sorted(files):
            if name in _IGNORED_NAMES or name.endswith(".pyc"):
                continue
            absolute = os.path.join(root, name)
            relative = os.path.relpath(absolute, package_dir).replace(os.sep, "/")
            found.append((relative, absolute))
    return found


def package_digest(package_dir: str) -> Optional[str]:
    """sha256 over the package's deployed files (path AND bytes).

    None when the directory is missing or unreadable - "cannot tell" is a
    distinct answer from "differs", and only the latter warrants a warning.
    """
    if not os.path.isdir(package_dir):
        return None
    digest = hashlib.sha256()
    try:
        for relative, absolute in _iter_sources(package_dir):
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            with open(absolute, "rb") as fh:
                digest.update(fh.read())
            digest.update(b"\0")
    except OSError:
        return None
    return digest.hexdigest()


def write_stamp(package_dir: str, commit: Optional[str], dirty: Optional[bool]) -> Dict[str, Any]:
    """Record what was installed, into the installed copy. Called by install.py
    AFTER the copy, so the digest it stores describes the files just written."""
    stamp = {
        "commit": commit,
        "dirty": dirty,
        "installed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "digest": package_digest(package_dir),
    }
    with open(os.path.join(package_dir, STAMP_NAME), "w", encoding="utf-8") as fh:
        json.dump(stamp, fh, indent=2, sort_keys=True)
    return stamp


def read_stamp(package_dir: str) -> Optional[Dict[str, Any]]:
    """The stamp written at install time, or None - unstamped (installed before
    this handshake existed, or copied by hand) and corrupt both degrade to None."""
    try:
        with open(os.path.join(package_dir, STAMP_NAME), encoding="utf-8") as fh:
            stamp = json.load(fh)
    except (OSError, ValueError):
        return None
    return stamp if isinstance(stamp, dict) else None


# The identity of the code that is actually RUNNING, captured once when this
# module is imported. The plugin imports every module at load, so what was on
# disk at that moment IS the loaded session; what is on disk LATER is whatever
# install.py wrote since. Between a deploy and a restart the two diverge, and
# that divergence is the one signal `ping` used to be blind to: it re-read the
# disk on every call and reported the freshly deployed copy as "live" while the
# interpreter still held the old modules (#604 - a caller measured the old
# handlers and attributed the results to the new branch).
_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
_LOADED_DIGEST = package_digest(_PACKAGE_DIR)
_LOADED_STAMP = read_stamp(_PACKAGE_DIR)
_IMPORTED_AT = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def plugin_info(package_dir: Optional[str] = None) -> Dict[str, Any]:
    """What `ping` hands back: which copy is LOADED, and what is on disk now.

    `digest`/`stamp` describe the files on disk at call time; `loaded_digest`/
    `loaded_stamp` describe what this session imported. The loaded pair only
    exists for the package this module actually lives in - for an explicit
    other `package_dir` (install verification, tests) there is no loaded copy
    to speak about, and inventing one would be the same lie in reverse.
    """
    if package_dir is None:
        package_dir = _PACKAGE_DIR
    info: Dict[str, Any] = {
        "package_dir": package_dir,
        "digest": package_digest(package_dir),
        "stamp": read_stamp(package_dir),
    }
    if package_dir == _PACKAGE_DIR:
        info["loaded_digest"] = _LOADED_DIGEST
        info["loaded_stamp"] = _LOADED_STAMP
        info["imported_at"] = _IMPORTED_AT
        # The human-readable form of the divergence, for anyone eyeballing a
        # raw ping. compare() derives its own verdict and does not read this.
        info["restart_required"] = bool(
            _LOADED_DIGEST and info["digest"] and _LOADED_DIGEST != info["digest"]
        )
    return info


def git_stamp(repo_dir: str) -> Dict[str, Any]:
    """{"commit", "dirty"} for a working tree; both None when git cannot answer.

    Only ever called outside Maya (install time, eval harness), so the
    subprocess cost is irrelevant and a missing git is merely uninformative.

    `dirty` is scoped to maya_plugin/ because a stamp describes the DEPLOYED
    package, and install.py copies nothing else: a rendered PNG under evals/ or
    an edited plan under docs/ cannot change what was installed, so calling that
    install "+dirty" is simply a false statement about the artifact. Unscoped,
    it was always true - this repo permanently carries a dozen untracked eval
    OUTPUT directories - and the flag said nothing at all. #796. Do not drop the
    pathspec to "be safe": the cost of the false positive was a throwaway
    git-worktree ritual before every single deploy.

    The pathspec is only half of it. Every import writes maya_plugin/__pycache__
    and that is untracked too, so this leans on .gitignore hiding __pycache__/
    and *.pyc - measured, not assumed, and pinned by a test against this very
    checkout. Delete those ignore rules and the flag pins to true again.

    Two traps come with scoping, and both would have been read as "clean":

    A relative pathspec resolves against `repo_dir`, so `git_stamp(<repo>/evals)`
    matched nothing and reported a confident False while the plugin was edited -
    the scoping quietly narrowed the contract from "any directory in a working
    tree" to "a directory that CONTAINS maya_plugin". `:(top)` anchors the
    pathspec at the repository root instead, so every directory in the tree
    answers for the same package. A git too old to know that magic fails the
    command outright, which lands on the None below - never on a false clean.

    And git exits 0 printing NOTHING both when the packaged tree is clean and
    when the pathspec matched nothing at all (measured). Those are different
    answers, so a tree that ships no maya_plugin/ gets `dirty: None`, matching
    this module's standing rule that "cannot tell" is distinct from "differs" -
    the alternative, falling back to the unscoped query, would answer a question
    nobody asked (is ANYTHING here dirty?) with the very false positive #796
    exists to delete. `commit` stays knowable either way.
    """
    def _git(*args: str) -> Optional[str]:
        try:
            out = subprocess.run(
                ("git",) + args, cwd=repo_dir, capture_output=True, text=True, timeout=10
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout.strip() if out.returncode == 0 else None

    commit = _git("rev-parse", "HEAD")
    if commit is None:
        return {"commit": None, "dirty": None}
    status = _git("status", "--porcelain", "--", _PACKAGE_PATHSPEC)
    if status is None:
        return {"commit": commit, "dirty": None}
    if status:
        return {"commit": commit, "dirty": True}
    # Empty output is two answers wearing one hat. Ask git whether it knows a
    # packaged tree here at all before calling this clean; ls-files is the same
    # question in the same vocabulary, so it cannot disagree with the pathspec
    # the status used. Only reached on the clean path, so it costs nothing the
    # rest of the time - and git_stamp runs at install time, never in Maya.
    tracked = _git("ls-files", "--", _PACKAGE_PATHSPEC)
    if not tracked:
        return {"commit": commit, "dirty": None}
    return {"commit": commit, "dirty": False}


def _git_returncode(repo_dir: str, *args: str) -> Optional[int]:
    """The exit status of a git command, or None when git could not run it.

    Distinct from git_stamp's helper: `merge-base --is-ancestor` answers with
    its EXIT CODE (0 yes, 1 no) and prints nothing, so a helper that only
    returns stdout cannot read it. 128 - an unknown object - is neither yes nor
    no, and must not be flattened into either.
    """
    try:
        out = subprocess.run(
            ("git",) + args, cwd=repo_dir, capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.returncode


def commit_relation(
    repo_dir: str, source_commit: Optional[str], deployed_commit: Optional[str]
) -> str:
    """How the source tree stands to the commit already deployed.

    One of "same", "upgrade" (the deployed commit is an ancestor of the source),
    "downgrade" (the source is an ancestor of the deployed commit), "divergent"
    (neither reaches the other - separate branches), or "unknown".

    "unknown" is a real answer, not a failure: a stamp from another clone, a
    deleted branch, or a tree with no git at all lands here, and this module's
    standing rule is that "cannot tell" is a different answer from "differs".
    """
    if not source_commit or not deployed_commit:
        return "unknown"
    if source_commit == deployed_commit:
        return "same"
    forward = _git_returncode(
        repo_dir, "merge-base", "--is-ancestor", deployed_commit, source_commit
    )
    backward = _git_returncode(
        repo_dir, "merge-base", "--is-ancestor", source_commit, deployed_commit
    )
    if forward not in (0, 1) or backward not in (0, 1):
        return "unknown"
    if forward == 0:
        return "upgrade"
    if backward == 0:
        return "downgrade"
    return "divergent"


def module_regression(source_pkg: str, deployed_pkg: str) -> list:
    """Modules the deployed copy has that the incoming source does not - but
    ONLY when the source adds nothing of its own.

    The git-free backstop. A tree that both removes and adds modules is a
    refactor and passes; a tree whose module set is a strict SUBSET of what is
    already deployed can only be a rollback, and that is detectable with no
    repository at all - which is the shape a copied-around tree takes.
    """
    source = {relative for relative, _ in _iter_sources(source_pkg)}
    deployed = {relative for relative, _ in _iter_sources(deployed_pkg)}
    missing = sorted(deployed - source)
    if not missing or (source - deployed):
        return []
    return missing


FORCE_HINT = (
    "If this rollback is deliberate, say so explicitly:\n"
    "    python maya_plugin/install.py --yes --force"
)


def _refusal(reason: str, detail: list) -> str:
    lines = ["", "!" * 72, "REFUSING to deploy: %s" % reason]
    lines.extend(detail)
    lines.append("")
    lines.extend(FORCE_HINT.splitlines())
    lines.append("!" * 72)
    return "\n".join(lines)


def deploy_guard(source_pkg: str, deployed_pkg: str, repo_dir: str) -> Optional[str]:
    """Refusal text for an install that would REPLACE a newer deployed plugin
    with an older one, or None to proceed.

    The deployed copy is shared by every Maya on the machine and install.py
    rmtree's it, so the last writer wins silently. A source tree on a divergent
    branch - an art worktree, a stale clone - can strip whole handler modules
    out of every session with no warning and no record. Reading the stamp that
    is already there costs one subprocess and closes that hole.

    Silent whenever the answer is genuinely "cannot tell": an unstamped copy
    (installed before the handshake existed, or copied by hand), a missing
    target, or a commit git does not recognise AND no capability regression to
    show for it. Blocking on ignorance would strand ordinary upgrades.
    """
    if not os.path.isdir(deployed_pkg):
        return None
    stamp = read_stamp(deployed_pkg)
    if stamp is None:
        return None

    source_commit = git_stamp(repo_dir)["commit"]
    deployed_commit = stamp.get("commit")
    relation = commit_relation(repo_dir, source_commit, deployed_commit)
    if relation in ("same", "upgrade"):
        return None

    installed = stamp.get("installed_at") or "unknown"
    detail = [
        "  source   commit : %s" % ((source_commit or "no git - cannot tell")[:12]),
        "  deployed commit : %s (installed %s)"
        % ((deployed_commit or "unstamped")[:12], installed),
        "  deployed at     : %s" % deployed_pkg,
    ]

    if relation == "downgrade":
        return _refusal(
            "the deployed plugin is NEWER than this source tree.", detail
        )
    if relation == "divergent":
        return _refusal(
            "this source tree and the deployed plugin diverge - neither commit "
            "reaches the other, so this is a branch swap, not an upgrade.",
            detail,
        )

    missing = module_regression(source_pkg, deployed_pkg)
    if not missing:
        return None
    return _refusal(
        "git cannot relate the two commits, and this source tree would REMOVE "
        "%d module(s) while adding none - a capability regression." % len(missing),
        detail + ["  would remove    : %s" % ", ".join(missing)],
    )


def compare(
    plugin: Optional[Dict[str, Any]],
    working_digest: Optional[str],
    working_commit: Optional[str] = None,
) -> Optional[str]:
    """The warning text for a live plugin that is not this working tree, or None.

    Pure and total: every ambiguous case resolves to either a warning or
    silence, and silence is reserved for "they match" and "cannot tell".

    The live identity is the LOADED digest when the plugin reports one, falling
    back to the on-disk digest for plugins that predate the distinction. Judging
    by the disk is #604's bug: in the window between install.py and a restart,
    the disk holds exactly the code that is NOT running.
    """
    if working_digest is None:
        return None  # no working tree to compare against; do not cry wolf

    plugin = plugin or {}
    disk_digest = plugin.get("digest")
    live_digest = plugin.get("loaded_digest") or disk_digest
    package_dir = plugin.get("package_dir") or "<unknown>"
    if live_digest == working_digest:
        # Deliberately silent even when the DISK now differs: live results
        # still describe this working tree, and whoever deployed the other
        # tree gets the warning on their own next check.
        return None

    deployed_not_restarted = bool(
        plugin.get("loaded_digest") and disk_digest == working_digest
    )

    lines = ["", "!" * 72]
    if not live_digest:
        lines.append(
            "STALE PLUGIN: the live Maya reports no package digest, which means it "
            "is running a build older than this staleness check itself."
        )
    elif deployed_not_restarted:
        lines.append(
            "STALE SESSION: the deploy landed but Maya was NOT restarted. The "
            "files on disk ARE this working tree; the running session imported "
            "the previous copy and answers with ITS code."
        )
        lines.append("  loaded  digest : %s" % live_digest[:12])
        lines.append("  on-disk digest : %s (= working tree)" % str(disk_digest)[:12])
    else:
        lines.append(
            "STALE PLUGIN: the live Maya is NOT running this working tree. Results "
            "from it describe other code."
        )
        lines.append("  deployed digest : %s" % live_digest[:12])
        lines.append("  working  digest : %s" % working_digest[:12])

    # The stamp that describes the RUNNING code is the loaded one when it
    # exists; the disk stamp describes whatever was installed most recently.
    stamp = (plugin.get("loaded_stamp") if plugin.get("loaded_digest") else None) or plugin.get("stamp") or {}
    if stamp.get("commit"):
        lines.append(
            "  running commit  : %s%s (installed %s)"
            % (
                str(stamp["commit"])[:12],
                "+dirty" if stamp.get("dirty") else "",
                stamp.get("installed_at") or "unknown",
            )
        )
    else:
        lines.append("  running commit  : unstamped (installed before this check, or copied by hand)")
    if working_commit:
        lines.append("  working commit  : %s" % str(working_commit)[:12])
    lines.append("  live package    : %s" % package_dir)
    lines.append(RESTART_HINT if deployed_not_restarted else INSTALL_HINT)
    lines.append("!" * 72)
    return "\n".join(lines)
