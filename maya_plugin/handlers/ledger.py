"""Transform ledger: detect live-user edits between tool calls (#577 req 4c).

The user tumbles the viewport and rotates objects mid-session. Tools that
write transforms record what they wrote; tools that later touch the same
object compare and surface a warning instead of silently assuming
script-only mutation. In-memory only — resets with the plugin/scene.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

_TOLERANCE = 1e-4

_written: Dict[str, Tuple[tuple, tuple, tuple]] = {}


def _read(cmds, name):
    t = tuple(cmds.xform(name, query=True, worldSpace=True, translation=True))
    r = tuple(cmds.xform(name, query=True, worldSpace=True, rotation=True))
    s = tuple(cmds.xform(name, query=True, worldSpace=True, scale=True))
    return t, r, s


def record(cmds, name: str) -> None:
    _written[name] = _read(cmds, name)


def check(cmds, name: str) -> Optional[str]:
    """Warning text if `name` moved since the last tool write; else None."""
    expected = _written.get(name)
    if expected is None:
        return None
    actual = _read(cmds, name)
    for exp_vec, act_vec in zip(expected, actual):
        if any(abs(e - a) > _TOLERANCE for e, a in zip(exp_vec, act_vec)):
            return (
                "%s was modified outside maya-mcp since the last tool write "
                "(expected t/r/s %s, found %s); proceeding from the current values"
                % (name, expected, actual)
            )
    return None


def rekey(old: str, new: str) -> None:
    """Follow a rename: `old` and everything under it now live under `new`.

    Entries are keyed by canonical long path, so renaming a node moves the
    node AND every descendant out from under their entries. MEASURED (#829):
    renaming a group `|rig` to `|lamp_rig` left `|rig|kid_a` and `|rig|kid_b`
    in here pointing at paths that no longer exist, which silently retires
    the "someone moved this outside maya-mcp" check for the whole subtree.

    A rename moves nothing, so the recorded values stay valid - only the key
    changes.
    """
    for key in [k for k in _written if k == old or k.startswith(old + "|")]:
        _written[new + key[len(old):]] = _written.pop(key)


def forget(name: str) -> None:
    _written.pop(name, None)


def clear() -> None:
    _written.clear()
