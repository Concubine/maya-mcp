"""The single place the delivery unit is decided.

Measured facts this encodes, none of them guessable from the API docs:

* `FBXExportConvertUnitString m` runs without error and does NOTHING. After it,
  the exporter still reports UnitsSelector=Centimeters, DynamicScaleConversion=1.
  Six combinations of selector and dynamic conversion produced byte-identical
  unit behaviour. It is removed rather than kept as decoration.
* `FBXExportScaleFactor` takes a BARE FLOAT. The `-v` form raises, and both
  generators swallowed that inside `except Exception: pass`.
* The factor MULTIPLIES the root node scale the exporter writes. The exporter
  always writes 0.01 there, so 100 cancels it to identity and the record is
  omitted entirely. Confirmed by the reciprocal: factor 0.01 wrote 0.0001.
* Because the factor only cancels the node scale, the VERTICES must already be
  metre-magnitude - hence BAKE_TO_METRES has to run first. Maya's internal
  linear unit is centimetres whatever `currentUnit` says, so a metre-authored
  scene exports at x100 with a compensating 0.01 on the exported root. That
  renders correctly and leaves the bare mesh 100x oversized, which is the
  defect in maya-mcp #629.

The two generators previously held divergent copies of this, and the divergence
was load-bearing: the heroes select one group so one Null took the 0.01, while
the kit selects 41 roots so all 41 Meshes took it. One preamble, one behaviour.
"""

# Scale the exported roots to metre magnitude and freeze, so the vertices
# themselves carry metres. Runs AFTER UVs are assigned and after the in-Maya
# checks: freezing a uniform scale does not touch UVs, and the checks are
# written against the metre-authored scene. Reordering this before UV
# assignment would silently move every UV - and with them the brick pitch.
BAKE_TO_METRES = r'''
import maya.cmds as cmds
for _root in ROOTS:
    cmds.setAttr(_root + ".scale", 0.01, 0.01, 0.01, type="double3")
    cmds.makeIdentity(_root, apply=True, translate=False, rotate=False, scale=True)
'''

EXPORT_PREAMBLE = r'''
import maya.cmds as cmds
import maya.mel as mel
cmds.loadPlugin("fbxmaya", quiet=True)
mel.eval('FBXResetExport')
mel.eval('FBXExportFileVersion -v FBX202000')
mel.eval('FBXExportUpAxis y')
mel.eval('FBXExportInputConnections -v false')
mel.eval('FBXExportEmbeddedTextures -v false')
mel.eval('FBXExportScaleFactor 100')
'''
