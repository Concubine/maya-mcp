"""Install the maya-mcp plugin into Maya's shared scripts directory.

Copies the maya_plugin package to <Documents>/maya/scripts/maya_plugin and
(optionally) appends an autoload snippet to userSetup.py. Prints exactly what
it will do and asks before touching anything; pass --yes to skip the prompts.

Usage:  python maya_plugin/install.py [--yes] [--scripts-dir PATH]
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from maya_plugin import version  # noqa: E402 - after the sys.path fix-up above

MARKER = "# >>> maya-mcp autoload >>>"
AUTOLOAD_SNIPPET = """
{marker}
try:
    from maya_plugin import maya_mcp_plugin
    import maya.utils
    maya.utils.executeDeferred(maya_mcp_plugin.start_server)
except Exception as _maya_mcp_exc:
    print("maya-mcp autoload failed:", _maya_mcp_exc)
# <<< maya-mcp autoload <<<
""".format(marker=MARKER)


def default_scripts_dir() -> str:
    return os.path.join(os.path.expanduser("~"), "Documents", "maya", "scripts")


def confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        print(prompt + " [--yes]")
        return True
    answer = input(prompt + " [y/N] ").strip().lower()
    return answer in ("y", "yes")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="skip confirmation prompts")
    parser.add_argument(
        "--force",
        action="store_true",
        help="deploy even when the guard judges it a rollback or a branch swap",
    )
    parser.add_argument(
        "--scripts-dir",
        default=default_scripts_dir(),
        help="Maya scripts directory (default: %(default)s)",
    )
    args = parser.parse_args()

    source = os.path.dirname(os.path.abspath(__file__))
    target = os.path.join(args.scripts_dir, "maya_plugin")
    user_setup = os.path.join(args.scripts_dir, "userSetup.py")

    if not os.path.isdir(os.path.dirname(target)):
        print(
            "Maya scripts directory not found: %s\n"
            "Is Maya installed? Pass --scripts-dir if your prefs live elsewhere."
            % args.scripts_dir
        )
        return 1

    # BEFORE the prompt and long before the rmtree: the deployed copy is shared
    # by every Maya on this machine, and replacing a newer one with an older one
    # is silent, machine-wide, and unrecorded unless something refuses here.
    repo = os.path.dirname(source)
    refusal = version.deploy_guard(source, target, repo)
    if refusal:
        if not args.force:
            print(refusal)
            return 1
        print(
            refusal.replace(version.FORCE_HINT, "").replace(
                "REFUSING to deploy:", "--force given; deploying anyway over:"
            )
        )

    print("This will:")
    print("  1. copy  %s" % source)
    print("     to    %s  (replacing any previous copy)" % target)
    if not confirm("Proceed with the copy?", args.yes):
        print("Aborted; nothing was changed.")
        return 1

    if os.path.isdir(target):
        shutil.rmtree(target)
    shutil.copytree(
        source, target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "install.py"),
    )
    print("Copied plugin to %s" % target)

    # Stamp the copy with what it was cut from. Without this a live check can
    # pass against a plugin that predates the code under test - the failure mode
    # that cost hours at M2.4 and again on the revision-2 art run.
    git = version.git_stamp(repo)
    stamp = version.write_stamp(target, commit=git["commit"], dirty=git["dirty"])
    print(
        "Stamped as %s%s (digest %s)"
        % (
            (stamp["commit"] or "no-git")[:12],
            "+dirty" if stamp["dirty"] else "",
            (stamp["digest"] or "unknown")[:12],
        )
    )

    existing = ""
    if os.path.exists(user_setup):
        with open(user_setup, "r", encoding="utf-8") as fh:
            existing = fh.read()
    if MARKER in existing:
        print("userSetup.py already contains the maya-mcp autoload; leaving it as is.")
    else:
        print("\nAutoload snippet for %s:" % user_setup)
        print(AUTOLOAD_SNIPPET)
        if confirm("Append this snippet to userSetup.py?", args.yes):
            with open(user_setup, "a", encoding="utf-8") as fh:
                fh.write(AUTOLOAD_SNIPPET)
            print("Appended autoload to %s" % user_setup)
        else:
            print(
                "Skipped. Start the plugin manually in Maya's Script Editor:\n"
                "    from maya_plugin import maya_mcp_plugin\n"
                "    maya_mcp_plugin.start_server()"
            )

    print("\nDone. Restart Maya (or run start_server() manually) and the plugin")
    print("will listen on 127.0.0.1:9877 (MAYA_MCP_HOST/MAYA_MCP_PORT to change).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
