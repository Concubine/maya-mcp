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

# What the whole-scene branch writes BESIDES geometry, pinned at the values
# Maya was measured to use anyway (#646): an ordinary lit scene with a user
# camera wrote three Light Models and one Camera Model. The values do not
# change the file - being stated does. Left unpinned, FBXResetExport's defaults
# decide it, which is the ambient-setting problem the preamble above exists to
# remove.
#
# Deliberately NOT part of FBX_PREAMBLE_MEL: that tuple composes the preamble
# string demigol_kit.py, demigol_structures.py and units_live.py ship their
# deliveries through, and tests/test_export_fbx.py pins it byte-for-byte
# against a literal copied from before the composition refactor. Those
# generators export selections of geometry, where neither flag can matter, so
# they keep the validated string and this tool gets the determinism.
FBX_SCENE_CONTENT_MEL: Tuple[str, ...] = (
    "FBXExportCameras -v true",
    "FBXExportLights -v true",
)

# Skin export switches, both states explicit so FBXResetExport's defaults never
# decide it (the same determinism argument as FBX_SCENE_CONTENT_MEL).
#
# MEASURED under mayapy, not read in a manual. `FBXExportSkins -v true` alone
# carries the skinCluster deformer, one cluster per joint and the BindPose,
# PROVIDED the selection lists the skeleton root alongside the mesh: with
# nodes=[mesh, root], all four of {both flags, skins only, input connections
# only, neither} wrote byte-identical 48192-byte files (that figure is this
# measurement's mayapy A/B scene; the committed fixture is a different,
# whole-scene export, so its 48208 bytes do not contradict it). So the extra
# `FBXExportInputConnections -v true` this was first written with buys nothing
# for the documented call and is deliberately NOT here - turning it on makes a
# SELECTED export silently drag in every input-connected node (materials,
# texture networks, constraint targets) that the caller did not ask for, and
# the preamble pins it false for exactly that reason.
#
# What it did buy: with nodes=[mesh] and the root left out, input connections
# ON pulls the joints in and the export succeeds. That convenience is refused
# on purpose. With it off, the file carries a deformer record with ZERO
# clusters (measured: deformers=1, clusters=0, 140 unweighted vertices), and
# skin_violations names the missing skeleton - a refusal that tells the caller
# what to fix beats an export that quietly widened its own selection.
FBX_SKINS_MEL = {
    True: ("FBXExportSkins -v true",),
    False: ("FBXExportSkins -v false",),
}

# Shape export pinned ON, always, with no caller-facing knob (#691 design
# decision): morph targets simply ride along whenever a blendShape exists. A
# scene without one writes no Shape records either way (pinned under mayapy),
# so the only scenes the pin affects are the ones whose authors want their
# shapes. Both states are never composed because there is no false state -
# the determinism argument collapses to one line.
FBX_SHAPES_MEL: Tuple[str, ...] = ("FBXExportShapes -v true",)

# A file-side weight sum further than this from 1.0 was not normalised and will
# deform differently in every consumer.
#
# MEASURED, and NOT the 1e-3 this was first written with: Maya's FBX exporter
# DROPS every skin weight strictly below 1e-3 and does not renormalise what is
# left. Across four binds the smallest weight kept was 1.072e-3 and the largest
# dropped 9.941e-4, while Maya's own in-scene sums were 1.0 to 2.2e-16. A
# vertex therefore loses up to (influences - 1) x 1e-3, and bind_skin allows
# MAX_INFLUENCES_CEILING = 8, so the arithmetic worst case is 7e-3. At 1e-3
# this gate REFUSED a correct 12-joint max_influences=8 bind whose file-side
# error was 1.381872e-3 (a 20-joint one measured 9.940742e-4, inside the old
# tolerance by 0.6%). 1e-2 clears the exporter's own pruning with room and
# still catches what this check is for - an unnormalised bind, or a lost
# influence set, which are order 0.1 to 1.0, not 0.001. A vertex left with NO
# ownership at all is counted separately, by unweighted_file_vertices.
WEIGHT_SUM_TOL = 1e-2

# Once the scene is metre-native there is no unit conversion left to make, so
# the exporter writes no compensating node and the factor must be 1. Measured
# both ways: at 100 the heroes' group Null came back at scale (100,100,100).
EXPORT_SCALE_FACTOR = 1.0

SCALE_TOL = 1e-3


def _scale_reaches_vertices(facts) -> set:
    """ids of the nodes whose scale actually multiplies a vertex.

    The identity-scale rule exists to catch a scale COMPENSATING for a wrong
    vertex magnitude, so it only means anything for a node that scales
    vertices: the one carrying the geometry, and every ancestor above it.

    Applying it to the rest is not merely redundant, it is wrong in the
    direction that costs an export. A whole-scene export writes lights and
    cameras as `Model` records too (measured: three Lights and a Camera from
    an ordinary lit scene), and a scaled light, or a scaled annotation
    locator, would refuse the whole export with a message blaming vertex
    magnitude and advising the caller to freeze transforms - advice that means
    nothing for a light (#646).

    A locator and a group are BOTH `Null` in the file, so kind cannot separate
    them and the test has to be structural. Kind is still consulted in one
    direction only: a `Model` declared "Mesh" is gated even if its geometry
    link did not resolve, because the failure to exempt is cheap and the
    failure to gate is #629. A skinned joint's scale multiplies vertices
    without being the mesh's ancestor, so LimbNodes gate like meshes (#602 P1).
    """
    by_uid = {n.uid: n for n in facts.nodes if n.uid is not None}
    reaching: set = set()
    for node in facts.nodes:
        if node.geometry is None and node.kind not in ("Mesh", "LimbNode"):
            continue
        walker = node
        while walker is not None and id(walker) not in reaching:
            reaching.add(id(walker))
            walker = by_uid.get(walker.parent)
    return reaching


def gate_violations(facts) -> List[str]:
    """Ways the written file breaks the export invariant, as readable strings.

    Two assertions, and only two, because these are the two that hold for EVERY
    export this server can be asked to make:

      scale        a compensating node scale makes a wrong vertex magnitude
                   render correctly, which is how three revisions shipped at
                   100x with every in-Maya check green (#596, #600, #629).
                   Asserted on the nodes whose scale reaches a vertex - see
                   _scale_reaches_vertices for why that is not every node
      declaration  metre-magnitude vertices declared as centimetres is the same
                   defect inverted, and a consumer measures unit scale on import

    Deliberately absent, though evals/delivery_units.py checks them: the
    one-root rule (a RIG rule - the demigol kit legitimately exports 41 roots)
    and the lattice/ceiling checks (per-delivery contract envelopes, not
    properties of a correct export). This tool asserts what it is responsible
    for; the delivery gates keep asserting what they are, against the same bytes.
    """
    out: List[str] = []
    reaching = _scale_reaches_vertices(facts)
    for node in facts.nodes:
        if id(node) not in reaching:
            continue
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


def skin_violations(sfacts) -> List[str]:
    """Ways the skin records break the include_skins contract."""
    out: List[str] = []
    if sfacts["deformers"] == 0:
        out.append(
            "include_skins=true but the file holds no skin deformer - "
            "nothing exported is bound")
        return out
    if sfacts["clusters"] == 0 or sfacts["influenced_models"] == 0:
        # Reports the measurement first; the diagnosis is offered as the one
        # cause this project has MEASURED (a selected export listing the mesh
        # without the skeleton root), not asserted as the only one (#668
        # review item b).
        out.append(
            "the file's skin deformer links no joints (%d clusters, %d "
            "influenced models); the one measured cause is a selected export "
            "that lists the mesh without the skeleton root"
            % (sfacts["clusters"], sfacts["influenced_models"]))
        return out
    if not sfacts["bind_pose_present"]:
        out.append("the file holds no BindPose record")
    scope = (" (across %d skin deformers - the count is file-wide, not per "
             "mesh)" % sfacts["deformers"]) if sfacts["deformers"] > 1 else ""
    if sfacts["unweighted_file_vertices"]:
        out.append("%d file vertices carry no weight%s"
                   % (sfacts["unweighted_file_vertices"], scope))
    err = sfacts["max_weight_sum_error"]
    if err is not None and err > WEIGHT_SUM_TOL:
        out.append("per-vertex weight sums are off by up to %g%s" % (err, scope))
    if sfacts["unavailable_reason"]:
        out.append("skin records unreadable: %s" % sfacts["unavailable_reason"])
    return out


def _scene_shape_aliases(cmds, nodes) -> List[str]:
    """Weight aliases of every blendShape reachable from the exported
    meshes - what the FILE must now carry. A selected export walks its own
    `nodes` (DAG-expanded, so a group export finds its children); a
    whole-scene export walks every non-intermediate mesh shape."""
    if nodes:
        shapes = cmds.ls(nodes, dagObjects=True, type="mesh",
                         long=True, noIntermediate=True) or []
    else:
        shapes = cmds.ls(type="mesh", long=True, noIntermediate=True) or []
    aliases: List[str] = []
    for shape in shapes:
        for bs in cmds.ls(cmds.listHistory(shape, pruneDagObjects=True)
                          or [], type="blendShape") or []:
            for alias in cmds.listAttr(bs + ".w", multi=True) or []:
                if alias not in aliases:
                    aliases.append(alias)
    return aliases


def shape_violations(sfacts, declared: List[str]) -> List[str]:
    """Ways the file's Shape records break the shapes-ride-along contract.

    `declared` is what the scene authored (the weight aliases); the file
    must carry each as a channel with a non-empty, self-consistent delta
    payload. Extra channels the scene did not declare are NOT a violation -
    a hand-built blendShape made outside this tool still deserves to
    export."""
    out: List[str] = []
    names = [s["name"] for s in sfacts["shapes"]]
    missing = [a for a in declared if a not in names]
    if missing:
        out.append(
            "the scene's blendShape target(s) %s are absent from the file "
            "(it carries: %s)"
            % (", ".join(missing), ", ".join(names) or "none"))
    for s in sfacts["shapes"]:
        if s["points"] == 0:
            out.append("shape %r carries no delta vertices" % s["name"])
        elif s["indexes"] != s["points"]:
            out.append("shape %r holds %d indexes but %d delta points"
                       % (s["name"], s["indexes"], s["points"]))
    if sfacts["unavailable_reason"]:
        out.append("shape records unreadable: %s"
                   % sfacts["unavailable_reason"])
    return out


def _validate(params: Dict[str, Any]) -> Tuple[str, Optional[List[str]], bool]:
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

    include_skins = params.get("include_skins", False)
    if not isinstance(include_skins, bool):
        raise HandlerError(
            "include_skins must be true or false, got %r" % (include_skins,),
            hint="true exports skinCluster deformers and the BindPose "
                 "alongside the mesh")

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
    return path, nodes, include_skins


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
    path, nodes, include_skins = _validate(params)
    cmds = _cmds()
    mel = _mel()

    if nodes:
        missing = [n for n in nodes if not cmds.objExists(n)]
        if missing:
            raise HandlerError(
                "no such object(s): %s" % ", ".join(missing[:6]),
                hint="names are case-sensitive; maya_get_scene_graph lists what "
                     "the scene actually contains")

    declared_shapes = _scene_shape_aliases(cmds, nodes)

    cmds.loadPlugin("fbxmaya", quiet=True)
    for statement in (FBX_PREAMBLE_MEL + FBX_SCENE_CONTENT_MEL
                      + FBX_SHAPES_MEL + FBX_SKINS_MEL[include_skins]):
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
    skin_block = None
    skin_bad: List[str] = []
    if include_skins:
        skin_block = fbxbytes.skin_facts(facts)
        skin_bad = skin_violations(skin_block)
        violations += skin_bad
    # "Freeze transforms" is the action for a unit violation and means nothing
    # for a skin one, so the hint gains the action that DOES apply, and only
    # when a skin violation is among the reasons.
    skin_hint = (
        " For skin violations: the mesh must be bound (maya_bind_skin reported "
        "unweighted_vertices=0) and a selected export ('nodes') must list the "
        "skeleton root alongside the mesh." if skin_bad else "")
    shapes_block = fbxbytes.shape_facts(facts)
    shape_bad = shape_violations(shapes_block, declared_shapes)
    violations += shape_bad
    shape_hint = (
        " For shape violations: the exported selection must include the "
        "shaped mesh itself - shapes travel with their mesh, and a "
        "selection that lists only other nodes leaves them behind."
        if shape_bad else "")
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
                     "before it reaches a delivery" % tmp_path
                     + skin_hint + shape_hint) from unlink_exc
        raise HandlerError(
            "the exported FBX failed the unit gate and was never written to "
            "%s - the temp file was deleted, and any pre-existing file at "
            "that path was never touched: %s"
            % (path, "; ".join(violations[:4])),
            hint="the scene is the problem, not the export settings. Freeze "
                 "transforms so no node carries scale, and author so one unit "
                 "means one metre (linear_unit 'cm' in this repo's convention). "
                 "Nothing reaches %s until it passes - a wrong file on disk is "
                 "how maya-mcp #629 reached three deliveries" % path
                 + skin_hint + shape_hint)

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
        "skin": skin_block,
        "shapes": (shapes_block
                   if declared_shapes or shapes_block["channels"] else None),
    }
