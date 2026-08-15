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
# The authoring unit, and the only thing that decides vertex magnitude.
#
# Maya's internal linear unit is centimetres whatever `currentUnit` reports, and
# the FBX exporter writes those internal numbers. So a scene authored with
# `currentUnit("m")` puts 300 in the file for a 3 m cube; authoring the same
# numbers under `currentUnit("cm")` makes 1 internal unit mean 1 metre and the
# file gets 3.0. Nothing else in either generator changes - the numbers written
# are identical, only their unit label moves.
#
# A post-hoc scale-and-freeze pass was tried instead and abandoned: freezing
# scale on a group bakes each child's WORLD POSITION into its vertices, which
# silently wrecks the layout (measured - chunk points came out at -13.39 in
# object space and the building read 26.5 m instead of 30.94 m).
AUTHORING_UNIT = "cm"

# polyAutoProjection reads world size in the scene's own units, so the UV
# constant is a property of the authoring convention. 1 unit = 1 m means 1.0.
UV_PER_METRE = 1.0

EXPORT_PREAMBLE = r'''
import maya.cmds as cmds
import maya.mel as mel
cmds.loadPlugin("fbxmaya", quiet=True)
mel.eval('FBXResetExport')
mel.eval('FBXExportFileVersion -v FBX202000')
mel.eval('FBXExportUpAxis y')
mel.eval('FBXExportInputConnections -v false')
mel.eval('FBXExportEmbeddedTextures -v false')
mel.eval('FBXExportScaleFactor %g' % EXPORT_SCALE_FACTOR)
'''

# Once the scene is metre-native there is no unit conversion left to make, so
# the exporter writes no compensating node and the factor must be 1. Measured
# both ways: at 100 the heroes' group Null came back at scale (100,100,100) and
# all 41 kit meshes at (100,100,100), with the vertices already correct in both.
#
# This is only true BECAUSE the authoring unit changed. A metre-authored scene
# does get a 0.01 conversion node, which is what made 100 look right earlier -
# it was cancelling a conversion that no longer happens.
EXPORT_SCALE_FACTOR = 1.0
