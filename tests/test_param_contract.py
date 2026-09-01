"""The param contract, enforced for every registered command (#767).

Three guarantees, all headless:

1. Every command REFUSES an unknown top-level params key ("does not take"),
   via require_known_keys as the handler's first statement — so the refusal
   holds on every call path (dispatcher, direct handler call, mayapy tests)
   and fires before any Maya touch. #764 measured the alternative: an unread
   key does not fail, it succeeds and does something else, and eleven tests
   asserted against a differently-named material for months.

2. Every command declares its keys as a module-level <CMD>_KEYS tuple (plus
   an optional <CMD>_SYNONYMS dict whose targets are all real keys). The
   convention is load-bearing: it is how THIS file finds the tuples, so a
   future command that skips it fails here rather than shipping unguarded.

3. Drift cannot turn a legitimate MCP caller into a refusal: every key the
   server wrapper in src/maya_mcp/server.py can send for a command is in
   that command's tuple. Parsed from the AST — the wrapper dicts are
   literals (plus a few tracked `params = {...}` / `params["k"] = ...`
   variables), and an unresolvable call shape is a FAILURE naming the
   wrapper, never a silent skip.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.maya_mcp_plugin import _build_handlers

HANDLERS = _build_handlers()
COMMANDS = sorted(HANDLERS)

SERVER_PY = Path(__file__).resolve().parents[1] / "src" / "maya_mcp" / "server.py"


def _keys_constant(command: str):
    handler = HANDLERS[command]
    module = sys.modules[handler.__module__]
    name = command.upper() + "_KEYS"
    assert hasattr(module, name), (
        "%s defines no %s - every command declares its allowed top-level "
        "params as a module-level tuple (#767)" % (handler.__module__, name)
    )
    return getattr(module, name), module


@pytest.mark.parametrize("command", COMMANDS)
def test_unknown_key_refuses(command):
    with pytest.raises(HandlerError) as exc:
        HANDLERS[command]({"definitely_not_a_param_767": 1})
    assert "does not take" in str(exc.value), (
        "%s raised, but not the unknown-key refusal - the guard must run "
        "before anything else can fail" % command
    )


@pytest.mark.parametrize("command", COMMANDS)
def test_keys_constant_exists(command):
    keys, module = _keys_constant(command)
    assert isinstance(keys, tuple), "%s_KEYS must be a tuple" % command.upper()
    assert all(isinstance(k, str) for k in keys)
    assert len(set(keys)) == len(keys), "duplicate keys in %s_KEYS" % command.upper()
    synonyms = getattr(module, command.upper() + "_SYNONYMS", None)
    if synonyms is not None:
        assert isinstance(synonyms, dict)
        for wrong, right in synonyms.items():
            assert isinstance(wrong, str) and isinstance(right, str)
            assert right in keys, (
                "%s_SYNONYMS maps %r to %r, which is not an allowed key"
                % (command.upper(), wrong, right)
            )
            assert wrong not in keys, (
                "%s_SYNONYMS maps %r, which IS an allowed key - a synonym "
                "entry for a real key would shadow it"
                % (command.upper(), wrong)
            )


# --------------------------------------------------------------- wrapper drift


def _wrapper_sent_keys():
    """command -> set of top-level params keys the MCP wrapper can send.

    Walks every function in server.py. Handles the two shapes the wrappers
    actually use: a dict literal inline in the maya.request(...) call, and a
    `params = {...literal...}` variable later extended via `params["k"] = v`
    before maya.request(cmd, params). Anything else lands in `unresolved` and
    fails the drift test by name - a new dynamic pattern must be looked at.
    """
    tree = ast.parse(SERVER_PY.read_text(encoding="utf-8"))
    sent: dict = {}
    unresolved: list = []

    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # dict-literal variables assigned in this function, name -> keys.
        # Every tool wrapper is nested inside create_server and they all
        # spell the variable `params`, so descending into nested functions
        # would pool one tool's keys into its neighbour's.
        dict_vars: dict = {}
        for node in _own_nodes(func):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
                keys = _literal_dict_keys(node.value)
                for target in node.targets:
                    if isinstance(target, ast.Name) and keys is not None:
                        dict_vars[target.id] = set(keys)
            elif (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and isinstance(node.value, ast.Dict)
            ):
                keys = _literal_dict_keys(node.value)
                if keys is not None:
                    dict_vars[node.target.id] = set(keys)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Subscript)
                        and isinstance(target.value, ast.Name)
                        and target.value.id in dict_vars
                        and isinstance(target.slice, ast.Constant)
                        and isinstance(target.slice.value, str)
                    ):
                        dict_vars[target.value.id].add(target.slice.value)
        for node in _own_nodes(func):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "request"
            ):
                continue
            if not (
                node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                unresolved.append("%s: non-literal command name" % func.name)
                continue
            command = node.args[0].value
            if len(node.args) < 2:
                keys = set()
            elif isinstance(node.args[1], ast.Dict):
                literal = _literal_dict_keys(node.args[1])
                if literal is None:
                    unresolved.append("%s -> %s: non-literal dict key" % (func.name, command))
                    continue
                keys = set(literal)
            elif (
                isinstance(node.args[1], ast.Name)
                and node.args[1].id in dict_vars
            ):
                keys = set(dict_vars[node.args[1].id])
            else:
                unresolved.append("%s -> %s: params arg not resolvable" % (func.name, command))
                continue
            sent.setdefault(command, set()).update(keys)

    return sent, unresolved


_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _own_nodes(func):
    """Every node inside `func` that is not inside a nested function.

    A nested def is skipped whole: ast.walk would pool every tool wrapper's
    `params` into create_server's, and they all use that one name.
    """
    stack = [n for n in func.body if not isinstance(n, _FUNC_NODES)]
    while stack:
        node = stack.pop()
        yield node
        for child in ast.iter_child_nodes(node):
            if not isinstance(child, _FUNC_NODES):
                stack.append(child)


def _literal_dict_keys(node: ast.Dict):
    keys = []
    for key in node.keys:
        if key is None:  # **splat
            return None
        if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
            return None
        keys.append(key.value)
    return keys


PROTOCOL_MD = Path(__file__).resolve().parents[1] / "docs" / "protocol.md"

# `{ mesh, shader?, params? }` in the params column of a command table row.
_ROW = re.compile(r"^\|\s*`(\w+)`\s*\|\s*`\{(.*?)\}`\s*\|", re.M)


def _documented_params():
    """command -> set of param names its protocol.md table row lists.

    Only the outermost brace group is read; a row whose params column is not
    a plain brace list (a few carry prose or nested result shapes) is skipped
    rather than guessed at.
    """
    out = {}
    for match in _ROW.finditer(PROTOCOL_MD.read_text(encoding="utf-8")):
        command, body = match.group(1), match.group(2)
        if command not in HANDLERS or "{" in body:
            continue
        # Drop bracketed value shapes first - `rotation: [rx,ry,rz]` would
        # otherwise contribute rx/ry/rz as if they were params.
        body = re.sub(r"\[[^\]]*\]", "", body)
        names = set()
        for part in body.split(","):
            name = part.split(":")[0].split("=")[0].strip()
            name = name.strip("`?* ").replace("\\", "").strip()
            # `divisions? \| subdivisions?` - a row offering alternatives.
            for piece in name.split("|"):
                piece = piece.strip().strip("?").strip()
                if piece.isidentifier():
                    names.add(piece)
        out.setdefault(command, set()).update(names)
    return out


def test_documented_params_are_accepted():
    """A stale table row is now a runtime REFUSAL, not a documentation nit.

    Before #767 an unknown key was ignored, so a doc listing a param the
    handler never read cost nothing. Now a caller who copies that row gets
    their call refused - which is how protocol.md's `timeout_s=120` inside
    author_clip's params would have behaved.
    """
    documented = _documented_params()
    assert len(documented) > 30, (
        "only %d command rows parsed - the table format changed and this "
        "check went blind" % len(documented)
    )
    problems = []
    for command, params in sorted(documented.items()):
        allowed, _module = _keys_constant(command)
        extra = sorted(params - set(allowed))
        if extra:
            problems.append("%s: protocol.md documents %s, which the handler "
                            "refuses" % (command, extra))
    assert not problems, "; ".join(problems)


def test_wrapper_keys_accepted():
    sent, unresolved = _wrapper_sent_keys()
    assert not unresolved, (
        "wrapper call sites this parser cannot resolve (extend the parser, "
        "do not skip): %s" % "; ".join(unresolved)
    )
    assert sent, "no maya.request call sites found - parser broken?"
    problems = []
    for command, keys in sorted(sent.items()):
        assert command in HANDLERS, (
            "server.py wrapper requests unknown command %r" % command
        )
        allowed, _module = _keys_constant(command)
        extra = sorted(keys - set(allowed))
        if extra:
            problems.append("%s: wrapper sends %s the handler would refuse"
                            % (command, extra))
    assert not problems, "; ".join(problems)
