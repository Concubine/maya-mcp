"""Compatibility shim: the FBX byte reader now lives in the plugin.

Moved to maya_plugin/handlers/fbxbytes.py for maya-mcp #642, because
maya_export_fbx has to read back the bytes it just wrote and those bytes are on
the MAYA machine's disk, where only the plugin runs. Nothing about the reader
changed; this module exists so the six callers in evals/ and tests/ did not
have to.

Re-exported by NAME on purpose. evals/delivery_units.py resolves
`fbx_probe.read_fbx` as an attribute at call time and tests/test_delivery_units.py
monkeypatches it, so the patch and the lookup must land on THIS module object.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maya_plugin.handlers.fbxbytes import (  # noqa: E402,F401 - re-export
    DECLARES_METRES,
    IDENTITY,
    ORIGIN,
    FbxFacts,
    FbxNode,
    read_fbx,
    set_unit_scale_factor,
    world_vertex_bounds,
)
