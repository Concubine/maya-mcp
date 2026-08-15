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

# Never copied into the deployed package (install.py), or written after the copy
# (the stamp) - counting either would make a freshly installed plugin read stale.
_IGNORED_NAMES = {"__pycache__", "install.py", STAMP_NAME}

INSTALL_HINT = (
    "redeploy:  python maya_plugin/install.py --yes\n"
    "then RESTART Maya (or re-import the plugin) - a reinstall alone does not\n"
    "reload modules Python has already imported."
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


def plugin_info(package_dir: Optional[str] = None) -> Dict[str, Any]:
    """What `ping` hands back: which copy is live, and what is in it."""
    if package_dir is None:
        package_dir = os.path.dirname(os.path.abspath(__file__))
    return {
        "package_dir": package_dir,
        "digest": package_digest(package_dir),
        "stamp": read_stamp(package_dir),
    }


def git_stamp(repo_dir: str) -> Dict[str, Any]:
    """{"commit", "dirty"} for a working tree; both None when git cannot answer.

    Only ever called outside Maya (install time, eval harness), so the
    subprocess cost is irrelevant and a missing git is merely uninformative.
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
    status = _git("status", "--porcelain")
    return {"commit": commit, "dirty": None if status is None else bool(status)}


def compare(
    plugin: Optional[Dict[str, Any]],
    working_digest: Optional[str],
    working_commit: Optional[str] = None,
) -> Optional[str]:
    """The warning text for a live plugin that is not this working tree, or None.

    Pure and total: every ambiguous case resolves to either a warning or
    silence, and silence is reserved for "they match" and "cannot tell".
    """
    if working_digest is None:
        return None  # no working tree to compare against; do not cry wolf

    plugin = plugin or {}
    live_digest = plugin.get("digest")
    package_dir = plugin.get("package_dir") or "<unknown>"
    if live_digest == working_digest:
        return None

    lines = ["", "!" * 72]
    if not live_digest:
        lines.append(
            "STALE PLUGIN: the live Maya reports no package digest, which means it "
            "is running a build older than this staleness check itself."
        )
    else:
        lines.append(
            "STALE PLUGIN: the live Maya is NOT running this working tree. Results "
            "from it describe other code."
        )
        lines.append("  deployed digest : %s" % live_digest[:12])
        lines.append("  working  digest : %s" % working_digest[:12])

    stamp = plugin.get("stamp") or {}
    if stamp.get("commit"):
        lines.append(
            "  deployed commit : %s%s (installed %s)"
            % (
                str(stamp["commit"])[:12],
                "+dirty" if stamp.get("dirty") else "",
                stamp.get("installed_at") or "unknown",
            )
        )
    else:
        lines.append("  deployed commit : unstamped (installed before this check, or copied by hand)")
    if working_commit:
        lines.append("  working  commit : %s" % str(working_commit)[:12])
    lines.append("  live package    : %s" % package_dir)
    lines.append(INSTALL_HINT)
    lines.append("!" * 72)
    return "\n".join(lines)
