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
import maya_export                                  # noqa: E402
from maya_plugin.handlers import export             # noqa: E402

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


# Copied verbatim from evals/maya_export.py as it stood at commit 7df1863,
# BEFORE this task rewrote it. This literal is the contract: demigol_kit.py,
# demigol_structures.py and units_live.py all ship their deliveries through
# this exact string, and re-validating a change to it would cost a live art
# run. Composing it from the handler is only safe because this assertion
# proves the composition produced the same bytes.
SHIPPED_PREAMBLE = (
    "\n"
    "import maya.cmds as cmds\n"
    "import maya.mel as mel\n"
    'cmds.loadPlugin("fbxmaya", quiet=True)\n'
    "mel.eval('FBXResetExport')\n"
    "mel.eval('FBXExportFileVersion -v FBX202000')\n"
    "mel.eval('FBXExportUpAxis y')\n"
    "mel.eval('FBXExportInputConnections -v false')\n"
    "mel.eval('FBXExportEmbeddedTextures -v false')\n"
    "mel.eval('FBXExportScaleFactor %g' % EXPORT_SCALE_FACTOR)\n"
)


def test_the_composed_preamble_is_byte_identical():
    assert maya_export.EXPORT_PREAMBLE == SHIPPED_PREAMBLE


def test_the_scale_factor_has_one_definition():
    assert maya_export.EXPORT_SCALE_FACTOR is export.EXPORT_SCALE_FACTOR
    assert export.EXPORT_SCALE_FACTOR == 1.0


def test_the_dead_end_is_not_in_the_preamble():
    # FBXExportConvertUnitString runs without error and does NOTHING - six
    # selector/dynamic-conversion combinations were byte-identical. It must not
    # come back as decoration.
    assert not any("ConvertUnit" in s for s in export.FBX_PREAMBLE_MEL)
    # And the -v form of the scale factor RAISES; both generators used to
    # swallow that inside `except Exception: pass`.
    assert not any(s.startswith("FBXExportScaleFactor") for s in export.FBX_PREAMBLE_MEL)


def test_the_preamble_is_the_measured_five_in_order():
    # FBXResetExport first, or a setting from a previous export survives.
    assert export.FBX_PREAMBLE_MEL == (
        "FBXResetExport",
        "FBXExportFileVersion -v FBX202000",
        "FBXExportUpAxis y",
        "FBXExportInputConnections -v false",
        "FBXExportEmbeddedTextures -v false",
    )
