"""author_physics (#676): physics-body data measured from the scene.

READ-ONLY: no checkpoint, nothing in the scene changes - the perception
tool for the destruction handoff, the way weight_report serves weights.
Mass = MEASURED closed-mesh volume x one density constant (the motion
handoff's rule: author volumes, masses are abstract, the engine
rescales); COM is the tetra-weighted solid centre, never a bbox centre
(#640); the collider is ONE primitive fitted in the mesh's own principal
frame with its honesty MEASURED (volume_ratio, max_escape). Joint limits
and flat-hierarchy parents are DESIGN INTENT - never scene-measurable -
and arrive via `overrides`; the tool converts hinge currency to the
handoff's swing/twist cone. Silence is never an answer: open meshes,
inverted winding, degenerate chunks, poor fits and missing overrides are
warnings with numbers. Validation is ANALYTIC - nothing simulates (#675).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..dispatcher import HandlerError, require_known_keys
from . import naming, physmath, sculpt_math


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _short(name: str) -> str:
    return name.split("|")[-1]


DENSITY_DEFAULT = 1.0
# Warning thresholds DERIVED from the delivered golem's own worst honest
# fits (evals/golem_delivery/chunks.json - committed ground truth, not a
# guess): worst volume_ratio 2.35 (golem_C_waist_gasket's box over a
# ring), worst max_escape 0.13221 on golem_L/R_thigh = 9.13% of that
# chunk's bbox diagonal. A fit worse than the worst a shipped, judged
# delivery tolerated is worth a warning - with the numbers attached.
VOLUME_RATIO_WARN = 2.4
ESCAPE_RATIO_WARN = 0.10
# |volume| below this fraction of bbox-diagonal cubed is float-noise
# scale: the chunk is a sheet, a line or a point, and its mass is fiction.
DEGENERATE_VOLUME_RATIO = 1e-6

OVERRIDE_KEYS = {"parent", "hinge_axis", "hinge_range_deg",
                 "twist_range_deg"}


def _points_and_triangles(transform: str):
    """World points + triangles via OpenMaya.

    Modeled on array._mesh_signed_volume's reader; carried here rather
    than shared because array's copy is frozen, tested behavior that
    returns only a volume, while this one hands the geometry to four
    computations (volume, COM, watertightness, collider fit) in ONE read.
    Module-level ON PURPOSE: FakeCmds cannot fake OpenMaya, so
    tests/test_physics.py monkeypatches this seam - the
    rigging._set_skin_weights precedent.
    """
    import maya.api.OpenMaya as om  # noqa: PLC0415

    sel = om.MSelectionList()
    sel.add(transform)
    dag = sel.getDagPath(0)
    dag.extendToShape()
    mesh = om.MFnMesh(dag)
    raw_points = mesh.getPoints(om.MSpace.kWorld)
    _counts, indices = mesh.getTriangles()
    points = [(p.x, p.y, p.z) for p in raw_points]
    triangles = [(indices[i], indices[i + 1], indices[i + 2])
                 for i in range(0, len(indices), 3)]
    return points, triangles


def _mesh_shape(cmds, transform: str) -> Optional[str]:
    shapes = cmds.listRelatives(transform, shapes=True, fullPath=True,
                                noIntermediate=True) or []
    if shapes and cmds.nodeType(shapes[0]) == "mesh":
        return shapes[0]
    return None


def _collect_chunks(cmds, params: Dict[str, Any],
                    warnings: List[str]) -> List[str]:
    root = params.get("root")
    chunks = params.get("chunks")
    if (root is None) == (chunks is None):
        raise HandlerError(
            "pass exactly one of 'root' or 'chunks'",
            hint="root walks mesh-bearing descendants; chunks lists "
                 "transforms explicitly")
    if chunks is not None:
        if (not isinstance(chunks, list) or not chunks
                or not all(isinstance(c, str) and c.strip() for c in chunks)):
            raise HandlerError(
                "chunks must be a non-empty list of transform names",
                hint="e.g. [\"golem_C_pelvis\", \"golem_C_belly\"]")
        if params.get("exclude") is not None:
            raise HandlerError(
                "exclude is root-mode only",
                hint="chunks mode already enumerates exactly what to "
                     "measure; drop exclude or use root")
        out = []
        for name in chunks:
            long = naming.require_object(cmds, name)
            if _mesh_shape(cmds, long) is None:
                raise HandlerError(
                    "%s has no mesh shape - not a chunk" % long,
                    hint="physics bodies are measured from geometry; pass "
                         "only mesh-bearing transforms")
            out.append(long)
        return out
    root_long = naming.require_object(cmds, str(root))
    nodes = [root_long] + (cmds.listRelatives(
        root_long, allDescendents=True, fullPath=True,
        type="transform") or [])
    found = sorted(n for n in nodes if _mesh_shape(cmds, n) is not None)
    exclude = params.get("exclude") or []
    if exclude:
        if (not isinstance(exclude, list)
                or not all(isinstance(e, str) for e in exclude)):
            raise HandlerError("exclude must be a list of name substrings")
        lowered = [e.lower() for e in exclude]
        dropped = [n for n in found
                   if any(e in _short(n).lower() for e in lowered)]
        if dropped:
            warnings.append(
                "excluded %d chunk(s) by name: %s"
                % (len(dropped), ", ".join(_short(n) for n in dropped)))
        found = [n for n in found if n not in dropped]
    if not found:
        raise HandlerError(
            "no mesh-bearing transforms under %s survive" % root_long,
            hint="groups without shapes are never chunks; check `exclude`")
    return found


def _parent_of(cmds, chunk: str, chunk_set,
               warnings: Optional[List[str]] = None) -> Optional[str]:
    """The chunk this one articulates against - plain groups between a chunk
    and its parent chunk are skipped, not parents.

    Two rig shapes reach here. In a GROUP rig the parent chunk is a genuine
    ancestor, and the upward walk finds it. In a rigid-parent rig (#713) each
    chunk hangs off its own jnt_*, so the parent chunk is NOT an ancestor at
    all - it is a sibling branch hanging off an ancestor JOINT, which no
    upward walk can reach. Reading that as parentless returned all 15 bodies
    with parent:null and silently dropped every joint limit with them (#722).

    So once the walk crosses the chunk's own joint, each ancestor joint is
    asked what chunk IT carries. Chunks on the SAME joint are deliberately
    never candidates for each other: they are welded (no articulation is
    possible between them) and parenting them to each other would build a
    cycle. Several chunks on one ancestor joint are structurally
    interchangeable - all welded to it - so the first by name is taken and
    the choice is reported, never silent.
    """
    node = chunk
    own_joint_seen = False
    while True:
        parents = cmds.listRelatives(node, parent=True, fullPath=True)
        if not parents:
            return None
        node = parents[0]
        if node in chunk_set:
            return node
        if cmds.nodeType(node) == "joint":
            if not own_joint_seen:
                own_joint_seen = True   # our own joint: its chunks are siblings
                continue
            carried = sorted(
                c for c in (cmds.listRelatives(node, children=True,
                                               fullPath=True,
                                               type="transform") or [])
                if c in chunk_set)
            if not carried:
                continue
            if len(carried) > 1 and warnings is not None:
                warnings.append(
                    "%s: joint %s carries %d chunks (%s) - they are welded "
                    "to it, so %s was taken as the parent; pass "
                    "overrides={%r: {'parent': ...}} to name another"
                    % (_short(chunk), _short(node), len(carried),
                       ", ".join(_short(c) for c in carried),
                       _short(carried[0]), _short(chunk)))
            return carried[0]


def _vec3(value) -> Optional[List[float]]:
    if (not isinstance(value, (list, tuple)) or len(value) != 3
            or not all(isinstance(v, (int, float))
                       and not isinstance(v, bool) for v in value)):
        return None
    return [float(v) for v in value]


def _range2(value) -> Optional[Tuple[float, float]]:
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or not all(isinstance(v, (int, float))
                       and not isinstance(v, bool) for v in value)):
        return None
    return float(value[0]), float(value[1])


def _validated_overrides(params: Dict[str, Any], chunk_shorts,
                         warnings: List[str]) -> Dict[str, Dict[str, Any]]:
    overrides = params.get("overrides") or {}
    if not isinstance(overrides, dict):
        raise HandlerError(
            "overrides must be a map of chunk short name -> override",
            hint="{'golem_L_shin': {'hinge_axis': [1,0,0], "
                 "'hinge_range_deg': [0, 110]}}")
    unknown = sorted(k for k in overrides if k not in chunk_shorts)
    if unknown:
        warnings.append(
            "overrides name %d chunk(s) not in this call, ignored: %s"
            % (len(unknown), ", ".join(unknown)))
    for name, spec in overrides.items():
        if not isinstance(spec, dict):
            raise HandlerError("override for %r must be a dict" % name)
        stray = sorted(set(spec) - OVERRIDE_KEYS)
        if stray:
            raise HandlerError(
                "override for %r has unknown key(s): %s"
                % (name, ", ".join(stray)),
                hint="allowed: parent, hinge_axis, hinge_range_deg, "
                     "twist_range_deg")
        has_axis = "hinge_axis" in spec
        has_range = "hinge_range_deg" in spec
        if has_axis != has_range:
            raise HandlerError(
                "override for %r: hinge_axis and hinge_range_deg travel "
                "together" % name,
                hint="the axis says WHICH way the hinge folds, the range "
                     "says HOW FAR - neither means anything alone")
        if has_axis:
            axis = _vec3(spec["hinge_axis"])
            if axis is None or physmath._length(axis) < 1e-9:
                raise HandlerError(
                    "override for %r: hinge_axis must be a non-zero "
                    "[x, y, z]" % name)
            rng = _range2(spec["hinge_range_deg"])
            if rng is None or rng[0] > rng[1]:
                raise HandlerError(
                    "override for %r: hinge_range_deg must be [lo, hi] "
                    "degrees with lo <= hi" % name)
        if "twist_range_deg" in spec:
            if not has_axis:
                raise HandlerError(
                    "override for %r: twist_range_deg needs hinge_axis + "
                    "hinge_range_deg" % name,
                    hint="twist is measured about the hinge axis")
            twist = _range2(spec["twist_range_deg"])
            if twist is None or twist[0] > twist[1]:
                raise HandlerError(
                    "override for %r: twist_range_deg must be [lo, hi] "
                    "degrees with lo <= hi" % name)
        if "parent" in spec and not (isinstance(spec["parent"], str)
                                     and spec["parent"].strip()):
            raise HandlerError(
                "override for %r: parent must be a chunk name" % name)
    return overrides


# Every top-level key author_physics reads. Anything else is refused rather
# than ignored (#767): an unread key does not fail, it succeeds and does
# something else. The root-vs-chunks exclusivity refusal stays in
# _collect_chunks - this guard only answers "is this key read at all".
AUTHOR_PHYSICS_KEYS = ("root", "chunks", "exclude", "density", "overrides")
# `chunks` is this tool's word for the bodies; every other tool in the set
# calls a list of objects `meshes` or `names`, and `mass` is what the RESULT
# reports (mass = volume x density), so a caller reaches for the output's
# noun as the input. `joints`/`limits` name what an override actually
# carries, and `ignore`/`skip` are the plain words for `exclude`.
AUTHOR_PHYSICS_SYNONYMS = {
    "mesh": "chunks", "meshes": "chunks", "bodies": "chunks",
    "parts": "chunks", "mass": "density", "joints": "overrides",
    "limits": "overrides", "ignore": "exclude", "skip": "exclude",
}


def author_physics(params: Dict[str, Any]) -> Dict[str, Any]:
    require_known_keys(params, AUTHOR_PHYSICS_KEYS, "author_physics",
                       AUTHOR_PHYSICS_SYNONYMS)
    cmds = _cmds()
    warnings: List[str] = []
    density = params.get("density", DENSITY_DEFAULT)
    if (not isinstance(density, (int, float)) or isinstance(density, bool)
            or density <= 0):
        raise HandlerError(
            "density must be a positive number",
            hint="mass = |volume| x density; the default 1.0 makes mass "
                 "numerically equal volume - the engine owns the real "
                 "constant")
    chunks = _collect_chunks(cmds, params, warnings)
    shorts = {_short(c) for c in chunks}
    if len(shorts) != len(chunks):
        raise HandlerError(
            "chunk short names collide",
            hint="overrides and parents key by short name - rename the "
                 "duplicates first")
    overrides = _validated_overrides(params, shorts, warnings)
    chunk_set = set(chunks)
    by_short = {_short(c): c for c in chunks}

    bodies: List[Dict[str, Any]] = []
    total_volume = 0.0
    parentless: List[str] = []
    for chunk in chunks:
        short = _short(chunk)
        spec = overrides.get(short, {})
        try:
            points, triangles = _points_and_triangles(chunk)
        except Exception as exc:  # OpenMaya read failed on a valid node
            warnings.append(
                "%s: mesh unreadable (%s) - chunk SKIPPED" % (chunk, exc))
            continue
        if not triangles:
            warnings.append(
                "%s: no triangles - chunk SKIPPED" % chunk)
            continue
        flat = [v for p in points for v in p]
        extent = sculpt_math.bbox_extent(flat)
        signed, com = physmath.solid_com(points, triangles)
        open_edges = physmath.open_edge_count(triangles)
        volume = abs(signed)
        watertight = open_edges == 0
        if not watertight:
            warnings.append(
                "%s: %d boundary edge(s) - not watertight, so the "
                "signed-volume reading (%.6g) is unreliable; volume and "
                "mass carry it anyway, flagged" % (chunk, open_edges, signed))
        elif signed < 0:
            warnings.append(
                "%s: the winding faces INWARD (signed volume %.6g - the "
                "mirror trap); |volume| is reported" % (chunk, signed))
        if extent > 0 and volume < DEGENERATE_VOLUME_RATIO * extent ** 3:
            warnings.append(
                "%s: near-zero volume %.6g against a size of %.4g - a "
                "sheet or degenerate chunk; its mass is fiction"
                % (chunk, volume, extent))
        if com is None:
            n = len(points)
            com = [sum(p[k] for p in points) / n for k in range(3)]
            warnings.append(
                "%s: volume ~ 0, solid COM undefined - the VERTEX centroid "
                "is reported instead" % chunk)

        collider = physmath.fit_collider(flat, signed)
        ratio = collider["volume_ratio"]
        if ratio is not None and ratio > VOLUME_RATIO_WARN:
            warnings.append(
                "%s: collider volume_ratio %.4g exceeds %.4g (the worst "
                "the delivered golem shipped was 2.35) - the %s wastes "
                "most of its volume" % (chunk, ratio, VOLUME_RATIO_WARN,
                                        collider["kind"]))
        if extent > 0 and collider["max_escape"] > ESCAPE_RATIO_WARN * extent:
            warnings.append(
                "%s: collider max_escape %.4g is over %d%% of the chunk's "
                "%.4g size - vertices stick far outside the %s"
                % (chunk, collider["max_escape"],
                   int(ESCAPE_RATIO_WARN * 100), extent, collider["kind"]))

        if "parent" in spec:
            parent_short = _short(spec["parent"])
            if parent_short == short or parent_short not in by_short:
                raise HandlerError(
                    "override for %r: parent %r is not another chunk in "
                    "this call" % (short, spec["parent"]),
                    hint="parents must be measured bodies too - include "
                         "the parent in root/chunks")
            parent = by_short[parent_short]
        else:
            parent = _parent_of(cmds, chunk, chunk_set, warnings)
        if parent is None:
            if any(k in spec for k in ("hinge_axis", "hinge_range_deg",
                                       "twist_range_deg")):
                raise HandlerError(
                    "override for %r supplies joint limits, but the chunk "
                    "resolves parentless - a limit with no joint to attach "
                    "to would be dropped, and the manifest would look "
                    "complete with no limits in it (#722)" % short,
                    hint="pass overrides={%r: {'parent': '<chunk>'}} so the "
                         "body has a joint, or drop the limit keys" % short)
            parentless.append(chunk)

        joint: Optional[Dict[str, Any]] = None
        if parent is not None:
            if "hinge_axis" in spec:
                lo, hi = _range2(spec["hinge_range_deg"])
                joint = physmath.cone_from_hinge(
                    spec["hinge_axis"], (lo, hi),
                    _range2(spec.get("twist_range_deg", [0.0, 0.0])))
                joint["source"] = "override"
                if not (lo <= 0.0 <= hi):
                    warnings.append(
                        "%s: hinge_range_deg [%g, %g] EXCLUDES the rest "
                        "pose (0 deg) - the body cannot sit where it was "
                        "authored" % (chunk, lo, hi))
            else:
                joint = physmath.cone_from_hinge([1.0, 0.0, 0.0], (0.0, 0.0))
                joint["source"] = "default_locked"
                warnings.append(
                    "%s: no joint override - emitted a LOCKED joint "
                    "(swing1=0, twist 0..0). Limits are design intent, "
                    "never scene-measurable; pass overrides={%r: "
                    "{'hinge_axis': [x,y,z], 'hinge_range_deg': [lo, hi]}}"
                    % (chunk, short))

        bodies.append({
            "chunk": chunk,
            "parent": parent,
            "mass": volume * float(density),
            "volume": volume,
            "signed_volume": signed,
            "com": com,
            "watertight": watertight,
            "open_edges": open_edges,
            "verts": len(points),
            "tris": len(triangles),
            "collider": collider,
            "joint": joint,
        })
        total_volume += volume

    if not bodies:
        raise HandlerError(
            "no measurable chunk survived",
            hint="every candidate was skipped - see the warnings that "
                 "would have accompanied a partial result")
    if len(parentless) > 1:
        warnings.append(
            "%d parentless bodies (%s) - a physics rig usually has ONE "
            "root. Chunk transforms are often flat siblings; parenthood "
            "is design intent then - pass overrides={name: {'parent': "
            "...}}" % (len(parentless),
                       ", ".join(_short(c) for c in parentless[:8])))

    return {
        "bodies": bodies,
        "density": float(density),
        "total_volume": total_volume,
        "warnings": warnings,
    }
