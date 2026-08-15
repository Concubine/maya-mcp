"""The delivery unit gate, checked against the artifact rather than the scene.

This suite exists because every in-Maya check is structurally blind to the
defect it guards. Measured on 2026-08-15: a probe cube reads 3.0 m at scale
[1,1,1] with transforms frozen in Maya, and exports as 300.0. The scene was
never wrong - the exporter writes the error - so `geometry_self_check` passed
green on all three ships of maya-mcp #629.

Nothing here imports Maya, so it runs in the normal suite on every run.
"""
import json
import os
import sys
from pathlib import Path

import pytest

_EVALS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "evals")
if _EVALS not in sys.path:
    sys.path.insert(0, _EVALS)

import fbx_probe          # noqa: E402

REPO = Path(__file__).resolve().parents[1]
KIT = REPO / "evals" / "demigol_kit" / "demigol_kit.fbx"
STRUCTURES = REPO / "evals" / "demigol_structures"
TOWER = STRUCTURES / "tower.fbx"
HEROES = ["tower", "block", "slab", "stump"]


def test_reader_finds_every_kit_mesh():
    facts = fbx_probe.read_fbx(KIT)
    assert facts.version == 7700
    assert len(facts.meshes) == 41


def test_reader_strips_the_fbx_name_separator():
    facts = fbx_probe.read_fbx(TOWER)
    names = [n.name for n in facts.nodes]
    assert "tower" in names, names[:5]
    assert not any("\x00" in n for n in names)


def test_reader_defaults_absent_records_to_identity():
    facts = fbx_probe.read_fbx(TOWER)
    # 673 chunks are written without an Lcl Scaling record; only the group Null
    # carries one. Absent must read as identity, never as missing.
    assert all(n.scaling == (1.0, 1.0, 1.0)
               for n in facts.nodes if n.name != "tower")
