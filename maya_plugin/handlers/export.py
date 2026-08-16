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


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _mel():
    import maya.mel as mel  # noqa: PLC0415 - only importable inside Maya

    return mel


def _bounds(facts):
    """World bounds and height from the FILE, plus why they are null when they are.

    fbxbytes._rotation implements only the default XYZ euler order and raises
    otherwise - deliberately, since a wrong assumption would move geometry
    silently. That must not fail an export whose bytes already passed the gate,
    so a rotation order the reader cannot compose costs the measurement, not
    the file. That is a DIFFERENT cause from an empty file and the schema used
    to conflate them, so the reader's own message is propagated rather than
    collapsed into "no geometry" - a rig with an ordinary non-default rotate
    order on a shoulder or hip must not be reported as if it had no geometry.
    """
    try:
        lo, hi = fbxbytes.world_vertex_bounds(facts)
    except ValueError as exc:
        return None, None, None, str(exc)
    if any(v == float("inf") for v in lo):
        return None, None, None, "the file holds no geometry"
    return list(lo), list(hi), hi[1] - lo[1], None


def export_fbx(params: Dict[str, Any]) -> Dict[str, Any]:
    path, nodes = _validate(params)
    cmds = _cmds()
    mel = _mel()

    if nodes:
        missing = [n for n in nodes if not cmds.objExists(n)]
        if missing:
            raise HandlerError(
                "no such object(s): %s" % ", ".join(missing[:6]),
                hint="names are case-sensitive; maya_get_scene_graph lists what "
                     "the scene actually contains")

    cmds.loadPlugin("fbxmaya", quiet=True)
    for statement in FBX_PREAMBLE_MEL:
        mel.eval(statement)
    # A bare float. The `-v` form raises, and both delivery generators used to
    # swallow that inside `except Exception: pass`.
    mel.eval("FBXExportScaleFactor %g" % EXPORT_SCALE_FACTOR)

    # Write to a SIBLING TEMP PATH, never straight to `path`. `cmds.file(...,
    # force=True)` overwrites whatever is already there, and re-exporting over
    # a shipped delivery after a scene edit that leaves a violation must not
    # cost that delivery its good file just because the new attempt failed.
    # `path` is touched only once the gate below has passed - keep the .fbx
    # extension, because Maya's FBX exporter is extension-sensitive.
    tmp_path = path + ".part.fbx"

    if nodes:
        cmds.select(nodes, replace=True)
        cmds.file(tmp_path, force=True, options="v=0", type="FBX export",
                  pr=True, es=True)
    else:
        cmds.file(tmp_path, force=True, options="v=0", type="FBX export",
                  pr=True, ea=True)

    try:
        # Maya writes UnitScaleFactor 1.0 for a metre-native scene and offers
        # no way to change it, so the declaration is corrected here: one
        # IEEE-754 double overwritten with another of the same width, so
        # nothing in the file moves.
        fbxbytes.set_unit_scale_factor(tmp_path)

        # Re-read the BYTES. This is the whole point of the tool: the defect
        # it guards is written by the exporter and is absent from the Maya
        # scene, so every in-Maya check is structurally blind to it.
        facts = fbxbytes.read_fbx(tmp_path)
    except Exception:
        # Both calls above can raise on a legitimately bad file (a truncated
        # write, a UnitScaleFactor-less FBX, an unrecognised typecode) and
        # neither is a HandlerError. Whatever it is, it must not leave an
        # ungated, unpatched file behind for a later run to trip over -
        # best-effort cleanup, then let the real exception through unchanged.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    violations = gate_violations(facts)
    if violations:
        try:
            os.unlink(tmp_path)
        except OSError as unlink_exc:
            # Worse than the ordinary failure below: the bad file is still on
            # disk, and a message that claims otherwise is exactly the kind of
            # false-green report this tool exists to prevent (#642).
            raise HandlerError(
                "the exported FBX failed the unit gate and COULD NOT BE "
                "DELETED (%s) - a bad file is STILL ON DISK at %s (a temp "
                "file; %s itself was never written and is untouched) and was "
                "NOT removed: %s"
                % (unlink_exc, tmp_path, path, "; ".join(violations[:4])),
                hint="the scene is the problem, not the export settings. Freeze "
                     "transforms so no node carries scale, and author so one "
                     "unit means one metre (linear_unit 'cm' in this repo's "
                     "convention). Deletion itself failed - remove %s by hand "
                     "before it reaches a delivery" % tmp_path) from unlink_exc
        raise HandlerError(
            "the exported FBX failed the unit gate and was never written to "
            "%s - the temp file was deleted, and any pre-existing file at "
            "that path was never touched: %s"
            % (path, "; ".join(violations[:4])),
            hint="the scene is the problem, not the export settings. Freeze "
                 "transforms so no node carries scale, and author so one unit "
                 "means one metre (linear_unit 'cm' in this repo's convention). "
                 "Nothing reaches %s until it passes - a wrong file on disk is "
                 "how maya-mcp #629 reached three deliveries" % path)

    # Only now, with the gate passed, does the real path get touched.
    os.replace(tmp_path, path)

    lo, hi, height, bounds_unavailable_reason = _bounds(facts)
    return {
        "path": path,
        "bytes": os.path.getsize(path),
        "fbx_version": facts.version,
        "node_count": len(facts.nodes),
        "mesh_count": len(facts.meshes),
        "root_nodes": [n.name for n in facts.nodes if n.parent is None],
        "unit_scale_factor": facts.unit_scale_factor,
        "metres_per_unit": 1.0,
        "world_bounds_min": lo,
        "world_bounds_max": hi,
        "height_m": height,
        "bounds_unavailable_reason": bounds_unavailable_reason,
    }
