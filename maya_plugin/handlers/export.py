"""FBX export, gated on the bytes it just wrote (maya-mcp #642).

The unit decision is the one most likely to ship a broken asset and it used to
live outside the server, in a MEL preamble pasted through execute_python. It
lives here now.

Everything this module knows about the FBX exporter was measured, not read in a
manual - see evals/maya_export.py's docstring for what each line cost:

* Maya's internal linear unit is centimetres whatever `currentUnit` reports,
  and the exporter writes those internal numbers.
* `FBXExportScaleFactor` only MULTIPLIES the root node scale the exporter
  writes. It can never change vertex magnitude, so it cannot rescue a scene
  that is the wrong size - it can only add the compensating scale that makes a
  wrong file render correctly. That is the #629 defect, and the gate below
  rejects exactly that.
* Maya writes `UnitScaleFactor 1.0` for a metre-native scene and offers no way
  to change it, so the declaration is patched in the bytes afterwards.

Nothing at module level imports Maya: evals/maya_export.py imports this from a
plain interpreter to compose the preamble its generators still use.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from ..dispatcher import HandlerError
from . import fbxbytes

# The five statements, in order, with FBXResetExport first so no setting from a
# previous export survives. Held as data rather than a code blob so
# evals/maya_export.py can compose its string from this and no second copy
# exists - the divergence between two copies of this preamble was load-bearing
# once already.
FBX_PREAMBLE_MEL: Tuple[str, ...] = (
    "FBXResetExport",
    "FBXExportFileVersion -v FBX202000",
    "FBXExportUpAxis y",
    "FBXExportInputConnections -v false",
    "FBXExportEmbeddedTextures -v false",
)

# Once the scene is metre-native there is no unit conversion left to make, so
# the exporter writes no compensating node and the factor must be 1. Measured
# both ways: at 100 the heroes' group Null came back at scale (100,100,100).
EXPORT_SCALE_FACTOR = 1.0

SCALE_TOL = 1e-3


def gate_violations(facts) -> List[str]:
    """Ways the written file breaks the export invariant, as readable strings.

    Two assertions, and only two, because these are the two that hold for EVERY
    export this server can be asked to make:

      scale        a compensating node scale makes a wrong vertex magnitude
                   render correctly, which is how three revisions shipped at
                   100x with every in-Maya check green (#596, #600, #629)
      declaration  metre-magnitude vertices declared as centimetres is the same
                   defect inverted, and a consumer measures unit scale on import

    Deliberately absent, though evals/delivery_units.py checks them: the
    one-root rule (a RIG rule - the demigol kit legitimately exports 41 roots)
    and the lattice/ceiling checks (per-delivery contract envelopes, not
    properties of a correct export). This tool asserts what it is responsible
    for; the delivery gates keep asserting what they are, against the same bytes.
    """
    out: List[str] = []
    for node in facts.nodes:
        if any(abs(s - 1.0) > SCALE_TOL for s in node.scaling):
            out.append(
                "node %r has scale %s, expected identity - a compensating node "
                "scale hides a wrong vertex magnitude"
                % (node.name, tuple(round(s, 6) for s in node.scaling)))
    if facts.unit_scale_factor != fbxbytes.DECLARES_METRES:
        out.append(
            "the file declares UnitScaleFactor %r, expected %g - the vertices "
            "are metres, so the file would contradict itself"
            % (facts.unit_scale_factor, fbxbytes.DECLARES_METRES))
    return out


def _validate(params: Dict[str, Any]) -> Tuple[str, Optional[List[str]]]:
    """Check every parameter before touching Maya. A bad call must cost nothing."""
    path = params.get("path")
    if not isinstance(path, str) or not path.strip():
        raise HandlerError(
            "missing required param 'path'",
            hint="pass an absolute path ending in .fbx, e.g. "
                 "path='D:/deliver/golem.fbx'")
    path = path.strip().replace("\\", "/")
    if not path.lower().endswith(".fbx"):
        raise HandlerError(
            "path %r must end in .fbx" % path,
            hint="this tool writes FBX only")
    if not os.path.isabs(path):
        raise HandlerError(
            "path %r must be absolute" % path,
            hint="a relative path resolves against Maya's working directory, "
                 "which is not the directory you ran anything from")
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        raise HandlerError(
            "the directory %r does not exist" % parent,
            hint="create it first - this tool does not make directories it was "
                 "not asked to make")

    if params.get("metres_per_unit") is None:
        raise HandlerError(
            "missing required param 'metres_per_unit'",
            hint="pass metres_per_unit=1.0. It has NO default on purpose: a "
                 "guess about what one unit means is exactly what shipped three "
                 "deliveries at 100x (maya-mcp #629), and no in-Maya check can "
                 "see that defect")
    mpu = params["metres_per_unit"]
    if isinstance(mpu, bool) or not isinstance(mpu, (int, float)):
        raise HandlerError(
            "metres_per_unit must be a number, got %r" % (mpu,),
            hint="pass metres_per_unit=1.0")
    if abs(float(mpu) - 1.0) > SCALE_TOL:
        raise HandlerError(
            "metres_per_unit=%g is refused; only 1.0 exports" % mpu,
            hint="this is not a conversion the exporter can make. "
                 "FBXExportScaleFactor only multiplies the root node scale, so "
                 "the vertices would stay the wrong size and the file would "
                 "carry the compensating scale this tool rejects. Scale the "
                 "geometry and freeze it so one unit means one metre, then "
                 "export with metres_per_unit=1.0")

    nodes = params.get("nodes")
    if nodes is not None:
        if not isinstance(nodes, list) or not all(isinstance(n, str) for n in nodes):
            raise HandlerError(
                "nodes must be a list of object names",
                hint="e.g. nodes=['golem_C_pelvis'], or omit it to export "
                     "the whole scene")
        if not nodes:
            raise HandlerError(
                "nodes is an empty list, which would export nothing",
                hint="omit nodes entirely to export the whole scene")
    return path, nodes
