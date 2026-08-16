"""maya-mcp #642: the export tool, and the gate it runs on its own bytes.

Nothing here imports Maya. The handler's Maya calls are faked, because the
point of this suite is the logic that decides whether a written file is
allowed to survive - and that logic must be checkable without a Maya licence.
"""
import os
import sys
from pathlib import Path

import pytest

_EVALS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "evals")
if _EVALS not in sys.path:
    sys.path.insert(0, _EVALS)

import fbx_probe                                    # noqa: E402
from maya_plugin.handlers import fbxbytes           # noqa: E402

REPO = Path(__file__).resolve().parents[1]
GOLEM = REPO / "evals" / "golem_delivery" / "golem.fbx"


def test_the_reader_lives_in_the_plugin_now():
    # It has to: maya_export_fbx reads back a file on the MAYA machine's disk,
    # and the server cannot assume it shares that filesystem.
    facts = fbxbytes.read_fbx(GOLEM)
    assert facts.unit_scale_factor == fbxbytes.DECLARES_METRES


def test_the_eval_shim_is_the_same_names():
    # evals/delivery_units.py resolves fbx_probe.read_fbx as an ATTRIBUTE at
    # call time and tests/test_delivery_units.py monkeypatches it in seven
    # places, so patch and lookup have to land on the same module object.
    for name in ("read_fbx", "world_vertex_bounds", "set_unit_scale_factor",
                 "FbxNode", "FbxFacts", "DECLARES_METRES"):
        assert getattr(fbx_probe, name) is getattr(fbxbytes, name), name


def test_the_shim_stays_patchable(monkeypatch):
    import delivery_units
    sentinel = fbxbytes.FbxFacts(version=7700, nodes=[], meshes=[],
                                 unit_scale_factor=fbxbytes.DECLARES_METRES)
    monkeypatch.setattr(fbx_probe, "read_fbx", lambda _p: sentinel)
    assert delivery_units.check_delivery("ignored.fbx", ceiling_m=2.0) == []
