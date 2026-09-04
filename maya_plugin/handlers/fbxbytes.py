"""Read what an FBX actually contains, without Maya.

The unit defect this exists to catch is written by the FBX exporter and is not
present in the Maya scene, so no in-Maya check can see it. This reader is pure
stdlib on purpose: the gate has to run in the normal test suite, against the
committed artifact, on every run.

Binary FBX layout: a 27-byte header ("Kaydara FBX Binary", version at offset
23), then nested node records. Offsets are 64-bit from version 7500. Each
record is EndOffset / NumProperties / PropertyListLen, a u8 name length, the
name, its properties, optional nested records, and a null terminator record -
EndOffset == 0 marks the end of a sibling list.
"""
import math
import os
import struct
import zlib
from dataclasses import dataclass, field
from typing import Optional

IDENTITY = (1.0, 1.0, 1.0)
ORIGIN = (0.0, 0.0, 0.0)

_SIMPLE = {b"C": ("<?", 1), b"B": ("<B", 1), b"Y": ("<h", 2), b"I": ("<i", 4),
           b"F": ("<f", 4), b"D": ("<d", 8), b"L": ("<q", 8)}
_ARRAYS = (b"f", b"d", b"l", b"i", b"c", b"b")

# FBX KTime: ticks per second. The SDK constant; PINNED against a real Maya
# export of a clip with a measured duration (TestClipExportInMaya) rather
# than trusted from documentation.
KTIME_PER_SECOND = 46186158000

# Every FBX property that carries a vec3 into a node's transform.
_TRIPLES = {
    "Lcl Translation": "translation",
    "Lcl Rotation": "rotation",
    "Lcl Scaling": "scaling",
    "RotationOffset": "rotation_offset",
    "RotationPivot": "rotation_pivot",
    "ScalingOffset": "scaling_offset",
    "ScalingPivot": "scaling_pivot",
    "PreRotation": "pre_rotation",
    "PostRotation": "post_rotation",
    "GeometricTranslation": "geometric_translation",
    "GeometricRotation": "geometric_rotation",
    "GeometricScaling": "geometric_scaling",
}


@dataclass
class FbxNode:
    name: str
    kind: str
    translation: tuple = ORIGIN
    scaling: tuple = IDENTITY
    # Everything below is needed only to compose a HIERARCHY. The demigol
    # deliveries are one flat rank of chunks under a Null, so translation alone
    # placed them; a rig nests 33 chunks six deep and rotates ten of them about
    # pivots that are not the origin, so a world measurement needs the lot.
    rotation: tuple = ORIGIN
    rotation_pivot: tuple = ORIGIN
    rotation_order: int = 0
    # FBX applies these unconditionally too, and Maya writes them the moment a
    # pivot is moved (rotation_offset is Maya's rotatePivotTranslate) or a joint
    # is oriented (pre_rotation is jointOrient). Dropping them reported a height
    # 21% wrong for a file this server built - maya-mcp #645.
    rotation_offset: tuple = ORIGIN
    scaling_offset: tuple = ORIGIN
    scaling_pivot: tuple = ORIGIN
    pre_rotation: tuple = ORIGIN
    post_rotation: tuple = ORIGIN
    # The geometric transform belongs to the VERTICES, not to the node: it is
    # never inherited by children. Kept apart from the chain for that reason.
    geometric_translation: tuple = ORIGIN
    geometric_rotation: tuple = ORIGIN
    geometric_scaling: tuple = IDENTITY
    inherit_type: int = 0
    uid: Optional[int] = None
    parent: Optional[int] = None
    geometry: Optional[int] = None


@dataclass
class FbxFacts:
    version: int
    nodes: list = field(default_factory=list)
    meshes: list = field(default_factory=list)
    unit_scale_factor: Optional[float] = None
    # Byte offset of the UnitScaleFactor double, so the declaration can be
    # corrected in place. See set_unit_scale_factor.
    unit_scale_offset: Optional[int] = None
    # Geometry UID -> flat vertex tuple, so vertices can be matched to the node
    # that carries them. `meshes` keeps the same tuples in file order.
    geometries: dict = field(default_factory=dict)
    # Skin records (#602 phase 1). skins: deformer uid -> {"geometry": uid,
    # "clusters": [uid]}; clusters: uid -> {"indexes", "weights", "model"}.
    skins: dict = field(default_factory=dict)
    clusters: dict = field(default_factory=dict)
    bind_pose_count: int = 0
    # Blend shapes (#602 phase 5 / #691). shape_geoms: Shape-class Geometry
    # uid -> {"name", "points" (delta-vertex COUNT - nothing needs the
    # floats), "indexes" (tuple of sparse vertex ids)}. blend_channels:
    # BlendShapeChannel deformer uid -> {"name", "shape" geom uid,
    # "deformer" uid}. blend_deformers: BlendShape deformer uid ->
    # {"geometry" mesh-geometry uid, "channels": [uid]}.
    shape_geoms: dict = field(default_factory=dict)
    blend_channels: dict = field(default_factory=dict)
    blend_deformers: dict = field(default_factory=dict)
    # Animation (#602 phase 6 / #695 / #718 Task 10b). anim_curves:
    # AnimationCurve uid -> {"key_count", "first_tick", "last_tick"} - counts
    # and endpoints only, never the arrays (a 61-frame bake x 60+ curves of
    # floats is memory nothing asks about). anim_nodes: AnimationCurveNode
    # uid -> {"name", "target" uid, "target_kind" "model"|"channel"|None,
    # "property" (the OP-connection property string, e.g. "Lcl Rotation"),
    # "curves": [uid], "layer": AnimationLayer uid or None}.
    # anim_stacks_by_uid: AnimationStack uid -> its name (a "take" IS an
    # AnimationStack; the Takes section below is a separate legacy record of
    # the same data, kept for its LocalTime start/stop ticks).
    # anim_layers_by_uid: AnimationLayer uid -> the AnimationStack uid that
    # owns it. Resolving a curve node's layer to its stack's name is what
    # lets anim_facts attribute a curve record to the take it belongs to.
    #
    # MEASURED (#718 Task 10, t718-10-report.md finding #3): a multi-take
    # export writes THREE AnimationCurveNode records per animated plug, not
    # one - one full-span node under Maya's own always-present default take
    # ("Take 001"), plus one per named take carrying that take's own range.
    # These used to be dropped as "membership adds nothing a violation would
    # read"; that claim was false. Without the layer/stack chain there is no
    # way to tell the three apart, and a first-wins collapse on an
    # FBX-internal object UID (not stable across identical exports) measured
    # 6 passes and 2 failures over 8 back-to-back exports of one correct
    # scene. takes come from the Takes section: name + LocalTime endpoint
    # ticks.
    anim_curves: dict = field(default_factory=dict)
    anim_nodes: dict = field(default_factory=dict)
    anim_stacks: int = 0
    anim_layers: set = field(default_factory=set)
    anim_stacks_by_uid: dict = field(default_factory=dict)
    anim_layers_by_uid: dict = field(default_factory=dict)
    takes: list = field(default_factory=list)
    # Textures (#714). textures: Texture uid -> {"name", "filename"};
    # videos: Video uid -> the same. Maya writes a file texture as a
    # Texture object plus a Video object carrying the image path, and
    # writes NOTHING for a procedural network - which is the whole defect
    # #714 gates. Connections are deliberately not resolved: the gate
    # compares image BASENAMES against the scene's claim, and the claim
    # already knows which material each map belongs to.
    textures: dict = field(default_factory=dict)
    videos: dict = field(default_factory=dict)


def _clean(raw):
    # FBX writes "tower\x00\x01Model"; the object name is the part before it.
    return raw.split("\x00\x01")[0]


def read_fbx(path):
    with open(path, "rb") as fh:
        data = fh.read()
    if not data.startswith(b"Kaydara FBX Binary"):
        raise ValueError("%s is not a binary FBX" % path)

    version = struct.unpack_from("<I", data, 23)[0]
    wide = version >= 7500
    off_fmt = "<QQQ" if wide else "<III"
    off_size = 24 if wide else 12
    facts = FbxFacts(version=version)
    _connections = []

    def prop(pos, want_ints=False, want_longs=False, want_floats=False):
        """Decode one property. `want_ints`/`want_longs`/`want_floats` are
        gated by the CALLER on purpose.

        Int/long/float arrays are decoded only where a record needs them (a
        cluster's Indexes, an AnimationCurve's KeyTime), never for
        PolygonVertexIndex or KeyValueFloat - a 4M-face kit, or a 61-frame
        bake x 60+ curves, would balloon this reader's memory for numbers
        nothing asks about.
        """
        code = data[pos:pos + 1]
        pos += 1
        if code in _SIMPLE:
            fmt, size = _SIMPLE[code]
            return struct.unpack_from(fmt, data, pos)[0], pos + size
        if code in (b"S", b"R"):
            n = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            raw = data[pos:pos + n]
            val = raw.decode("utf-8", "replace") if code == b"S" else raw
            return val, pos + n
        if code in _ARRAYS:
            length, encoding, comp = struct.unpack_from("<III", data, pos)
            pos += 12
            payload = data[pos:pos + comp]
            pos += comp
            fmt = None
            if code == b"d":
                fmt = "<%dd"
            elif want_ints and code == b"i":
                fmt = "<%di"
            elif want_longs and code == b"l":
                fmt = "<%dq"
            elif want_floats and code == b"f":
                fmt = "<%df"
            if fmt is not None:
                raw = zlib.decompress(payload) if encoding == 1 else payload
                return struct.unpack(fmt % length, raw), pos
            return None, pos
        raise ValueError("unknown FBX typecode %r at %d" % (code, pos))

    def walk(pos, end, node):
        while pos < end:
            end_off, nprops, _plen = struct.unpack_from(off_fmt, data, pos)
            if end_off == 0:
                return pos + off_size + 1
            pos += off_size
            nlen = data[pos]
            pos += 1
            name = data[pos:pos + nlen].decode("utf-8", "replace")
            pos += nlen

            values = []
            starts = []
            for _ in range(nprops):
                starts.append(pos + 1)   # skip the typecode byte
                val, pos = prop(pos, want_ints=(name == "Indexes"),
                                want_longs=(name == "KeyTime"),
                                want_floats=False)
                values.append(val)

            if (name in ("FileName", "RelativeFilename", "Filename")
                    and isinstance(node, tuple) and node[0] == "texnode"
                    and values and isinstance(values[0], str)):
                # The bare CHILD RECORD shape (a different Maya version's
                # export than the nested P property above). MEASURED on
                # the committed drifter fixture: Video's primary full-path
                # field is spelled "Filename" (lowercase n) while Texture's
                # is "FileName" - both write "RelativeFilename" the same
                # way, so all three spellings are recognised here.
                store = (facts.textures if node[2] == "Texture"
                         else facts.videos)
                current = store.get(node[1])
                if current is not None and not current["filename"]:
                    current["filename"] = values[0]
            elif name == "Vertices" and values and isinstance(values[0], tuple):
                if isinstance(node, tuple) and node[0] == "shape":
                    facts.shape_geoms[node[1]]["points"] = len(values[0]) // 3
                else:
                    facts.meshes.append(values[0])
                    if isinstance(node, int):
                        facts.geometries[node] = values[0]
            elif name == "C" and len(values) >= 3:
                # ("OO", child, parent) or ("OP", child, parent, property).
                # Geometry connects to its Model the same way a Model
                # connects to its parent Model, so one pass wires both; the
                # 0 parent is the scene root. An OP connection (an
                # AnimationCurveNode into a Model's "Lcl Rotation", say)
                # carries a fourth property-string value - link_prop.
                _connections.append(
                    (values[1], values[2],
                     values[3] if len(values) > 3
                     and isinstance(values[3], str) else None))
            elif name == "P" and values and isinstance(values[0], str):
                key = values[0]
                if key == "UnitScaleFactor":
                    facts.unit_scale_factor = float(values[-1])
                    facts.unit_scale_offset = starts[-1]
                elif isinstance(node, FbxNode):
                    if key in _TRIPLES:
                        setattr(node, _TRIPLES[key],
                                tuple(float(v) for v in values[-3:]))
                    elif key == "RotationOrder":
                        node.rotation_order = int(values[-1])
                    elif key == "InheritType":
                        node.inherit_type = int(values[-1])
                elif isinstance(node, tuple) and node[0] == "texnode":
                    # MEASURED on the committed drifter fixture: Video
                    # writes its path as a nested Properties70 P "Path"/
                    # "RelPath" pair (Texture does not - it only carries
                    # UseMaterial there). Both objects ALSO carry the bare
                    # FileName/RelativeFilename child records below, so
                    # this file exercises both shapes at once; keep both,
                    # Maya's other export paths write only one or the
                    # other.
                    if key in ("FileName", "RelativeFilename", "Path",
                               "RelPath"):
                        store = (facts.textures if node[2] == "Texture"
                                 else facts.videos)
                        current = store.get(node[1])
                        if current is not None and not current["filename"]:
                            value = values[-1]
                            if isinstance(value, str):
                                current["filename"] = value

            child = node
            if name == "Model":
                strs = [v for v in values if isinstance(v, str)]
                uid = values[0] if values and isinstance(values[0], int) else None
                child = FbxNode(name=_clean(strs[0]) if strs else "?",
                                kind=strs[1] if len(strs) > 1 else "?", uid=uid)
                facts.nodes.append(child)
            elif name == "Geometry":
                uid = values[0] if values and isinstance(values[0], int) else None
                strs = [v for v in values if isinstance(v, str)]
                if uid is not None and strs and strs[-1] == "Shape":
                    facts.shape_geoms[uid] = {"name": _clean(strs[0]),
                                              "points": 0, "indexes": ()}
                    child = ("shape", uid)
                else:
                    child = uid
            elif name == "Deformer":
                uid = values[0] if values and isinstance(values[0], int) else None
                strs = [v for v in values if isinstance(v, str)]
                klass = strs[-1] if strs else ""
                if uid is not None and klass == "Skin":
                    facts.skins[uid] = {"geometry": None, "clusters": []}
                    child = ("skin", uid)
                elif uid is not None and klass == "Cluster":
                    facts.clusters[uid] = {"indexes": (), "weights": (),
                                           "model": None}
                    child = ("cluster", uid)
                elif uid is not None and klass == "BlendShape":
                    facts.blend_deformers[uid] = {"geometry": None,
                                                  "channels": []}
                    child = ("blend", uid)
                elif uid is not None and klass == "BlendShapeChannel":
                    facts.blend_channels[uid] = {
                        "name": _clean(strs[0]) if strs else "?",
                        "shape": None, "deformer": None}
                    child = ("channel", uid)
            elif name == "Pose":
                strs = [v for v in values if isinstance(v, str)]
                if strs and strs[-1] == "BindPose":
                    facts.bind_pose_count += 1
            elif name in ("Texture", "Video"):
                uid = values[0] if values and isinstance(values[0], int) else None
                strs = [v for v in values if isinstance(v, str)]
                if uid is not None:
                    record = {"name": _clean(strs[0]) if strs else "?",
                              "filename": ""}
                    if name == "Texture":
                        facts.textures[uid] = record
                    else:
                        facts.videos[uid] = record
                    child = ("texnode", uid, name)
            elif name == "AnimationCurve":
                uid = values[0] if values and isinstance(values[0], int) else None
                if uid is not None:
                    facts.anim_curves[uid] = {"key_count": 0,
                                              "first_tick": None,
                                              "last_tick": None}
                    child = ("acurve", uid)
            elif name == "AnimationCurveNode":
                uid = values[0] if values and isinstance(values[0], int) else None
                strs = [v for v in values if isinstance(v, str)]
                if uid is not None:
                    facts.anim_nodes[uid] = {
                        "name": _clean(strs[0]) if strs else "?",
                        "target": None, "target_kind": None,
                        "property": None, "curves": [], "layer": None}
                    child = ("anode", uid)
            elif name == "AnimationStack":
                facts.anim_stacks += 1
                uid = values[0] if values and isinstance(values[0], int) else None
                if uid is not None:
                    strs = [v for v in values if isinstance(v, str)]
                    facts.anim_stacks_by_uid[uid] = (
                        _clean(strs[0]) if strs else "?")
            elif name == "AnimationLayer":
                uid = values[0] if values and isinstance(values[0], int) else None
                if uid is not None:
                    facts.anim_layers.add(uid)
            elif name == "Take":
                strs = [v for v in values if isinstance(v, str)]
                facts.takes.append({"name": _clean(strs[0]) if strs else "?",
                                    "start_tick": None, "stop_tick": None})
                child = ("take", len(facts.takes) - 1)
            elif (name == "Indexes" and isinstance(node, tuple)
                    and node[0] == "cluster" and values
                    and isinstance(values[0], tuple)):
                facts.clusters[node[1]]["indexes"] = values[0]
            elif (name == "Indexes" and isinstance(node, tuple)
                    and node[0] == "shape" and values
                    and isinstance(values[0], tuple)):
                facts.shape_geoms[node[1]]["indexes"] = values[0]
            elif (name == "Weights" and isinstance(node, tuple)
                    and node[0] == "cluster" and values
                    and isinstance(values[0], tuple)):
                facts.clusters[node[1]]["weights"] = values[0]
            elif (name == "KeyTime" and isinstance(node, tuple)
                    and node[0] == "acurve" and values
                    and isinstance(values[0], tuple)):
                ticks = values[0]
                rec = facts.anim_curves[node[1]]
                rec["key_count"] = len(ticks)
                rec["first_tick"] = ticks[0] if ticks else None
                rec["last_tick"] = ticks[-1] if ticks else None
            elif (name == "LocalTime" and isinstance(node, tuple)
                    and node[0] == "take" and len(values) >= 2
                    and all(isinstance(v, int) for v in values[:2])):
                facts.takes[node[1]]["start_tick"] = values[0]
                facts.takes[node[1]]["stop_tick"] = values[1]
            if pos < end_off:
                walk(pos, end_off, child)
            pos = end_off
        return pos

    walk(27, len(data), None)

    by_uid = {n.uid: n for n in facts.nodes if n.uid is not None}
    for child, parent, link_prop in _connections:
        if child in by_uid and (parent in by_uid or parent == 0):
            # 0 is the scene root: an explicit "no parent", kept distinct
            # from connections into non-Model records (clusters, materials),
            # which must not null a real parent.
            by_uid[child].parent = parent if parent in by_uid else None
        elif child in by_uid and parent in facts.clusters:
            facts.clusters[parent]["model"] = child
        elif child in facts.geometries and parent in by_uid:
            by_uid[parent].geometry = child
        elif child in facts.clusters and parent in facts.skins:
            facts.skins[parent]["clusters"].append(child)
        elif child in facts.skins and parent in facts.geometries:
            facts.skins[child]["geometry"] = parent
        elif child in facts.shape_geoms and parent in facts.blend_channels:
            facts.blend_channels[parent]["shape"] = child
        elif child in facts.blend_channels and parent in facts.blend_deformers:
            facts.blend_deformers[parent]["channels"].append(child)
            facts.blend_channels[child]["deformer"] = parent
        elif child in facts.blend_deformers and parent in facts.geometries:
            facts.blend_deformers[child]["geometry"] = parent
        elif child in facts.anim_curves and parent in facts.anim_nodes:
            facts.anim_nodes[parent]["curves"].append(child)
        elif child in facts.anim_nodes and parent in by_uid:
            facts.anim_nodes[child]["target"] = parent
            facts.anim_nodes[child]["target_kind"] = "model"
            facts.anim_nodes[child]["property"] = link_prop
        elif child in facts.anim_nodes and parent in facts.blend_channels:
            facts.anim_nodes[child]["target"] = parent
            facts.anim_nodes[child]["target_kind"] = "channel"
            facts.anim_nodes[child]["property"] = link_prop
        elif child in facts.anim_nodes and parent in facts.anim_layers:
            # AnimationCurveNode -> AnimationLayer. #718 Task 10 measured
            # that membership is exactly what a violation needs: without it,
            # a segmented multi-take file's three duplicate curve records
            # per plug cannot be told apart, and a first-wins collapse on an
            # FBX-internal UID is not stable across identical exports.
            facts.anim_nodes[child]["layer"] = parent
        elif child in facts.anim_layers and parent in facts.anim_stacks_by_uid:
            # AnimationLayer -> AnimationStack. Combined with the arm above,
            # this resolves a curve node to the take (stack NAME) that owns
            # it - anim_facts does that resolution and reports it as "take".
            facts.anim_layers_by_uid[child] = parent
    return facts


def _rotation(deg, order):
    """Row-vector rotation matrix for an XYZ euler triple, in degrees."""
    if order:
        # Only the default order is implemented, and a wrong assumption here
        # would move geometry silently rather than fail. Nothing has needed it:
        # measured 0 on every node of every delivery so far.
        raise ValueError("rotation order %d is not implemented" % order)
    cx, cy, cz = (math.cos(math.radians(v)) for v in deg)
    sx, sy, sz = (math.sin(math.radians(v)) for v in deg)
    return [[cy * cz, cy * sz, -sy],
            [sx * sy * cz - cx * sz, sx * sy * sz + cx * cz, sx * cy],
            [cx * sy * cz + sx * sz, cx * sy * sz - sx * cz, cx * cy]]


def _matmul(a, b):
    """a then b, for row vectors: p.(a.b) applies a first."""
    return [[sum(a[r][k] * b[k][c] for k in range(3)) for c in range(3)]
            for r in range(3)]


def _transposed(m):
    """Also the inverse, for the rotation matrices this module builds."""
    return [[m[c][r] for c in range(3)] for r in range(3)]


def _local(node, rotation=None):
    """Return (M, t) such that a point p in this node's space maps to p.M + t.

    FBX composes a node's local transform as

        T . Roff . Rp . Rpre . R . Rpost-1 . Rp-1 . Soff . Sp . S . Sp-1

    and applies every term unconditionally. In row-vector order that is

        q = (p - Sp) . S + Sp + Soff
        r = (q - Rp) . Rpost-1 . R . Rpre + Rp + Roff + T

    This reader used to keep only T, R, Rp and S-about-the-origin. The rest are
    not exotic: Maya writes Roff (rotatePivotTranslate) whenever a pivot is
    moved - which maya_transform's `pivot` parameter does deliberately - and
    Rpre whenever a joint is oriented. Dropping them reported 44.90 for a
    clock tower Maya measures at 37.10 (maya-mcp #645).

    `rotation` overrides the node's own euler triple, which is how a POSE is
    measured: a pose is per-chunk rotations and nothing else, so substituting
    them here and re-composing is the whole of applying one.
    """
    R = _rotation(node.rotation if rotation is None else rotation,
                  node.rotation_order)
    if node.pre_rotation != ORIGIN:
        R = _matmul(R, _rotation(node.pre_rotation, 0))
    if node.post_rotation != ORIGIN:
        R = _matmul(_transposed(_rotation(node.post_rotation, 0)), R)

    s = node.scaling
    M = [[R[r][c] * s[r] for c in range(3)] for r in range(3)]
    sp, so = node.scaling_pivot, node.scaling_offset
    rp, ro = node.rotation_pivot, node.rotation_offset
    # Everything the point picks up before the rotation, gathered so it can be
    # rotated in one go: (Sp + Soff - Sp.S) from the scaling half, -Rp from the
    # rotation half.
    pre = [sp[c] + so[c] - sp[c] * s[c] - rp[c] for c in range(3)]
    offset = [sum(pre[r] * R[r][c] for r in range(3))
              + rp[c] + ro[c] + node.translation[c] for c in range(3)]
    return M, offset


def _geometric(node):
    """(M, t) for the geometric transform: (v . Gs) . Gr + Gt.

    FBX applies this to the node's own vertices and NEVER to its children,
    which is why it is not part of _local.
    """
    R = _rotation(node.geometric_rotation, 0)
    gs = node.geometric_scaling
    M = [[R[r][c] * gs[r] for c in range(3)] for r in range(3)]
    return M, list(node.geometric_translation)


def _is(triple, reference, tol=1e-9):
    return all(abs(triple[c] - reference[c]) <= tol for c in range(3))


def _has_geometric(node):
    return not (_is(node.geometric_translation, ORIGIN)
                and _is(node.geometric_rotation, ORIGIN)
                and _is(node.geometric_scaling, IDENTITY))


def _refuse_unsupported_inheritance(node, parent, posed=None):
    """FBX InheritType 1 (eInheritRSrs) does not hand a parent's scale to a
    rotated child the way plain parent-then-child composition does.

    Maya writes InheritType 1 on every node it exports, so this cannot simply
    be asserted away - but it only diverges when a scaled parent has a rotated
    child, which no delivery measured so far does (scale sits on leaf meshes).
    Refusing there beats composing a matrix that is quietly wrong: a number
    this reader reports has to be one a consumer can trust (maya-mcp #645).
    """
    if parent is None or node.inherit_type == 0 or _is(parent.scaling, IDENTITY):
        return
    rotation = node.rotation if posed is None else posed
    if (_is(rotation, ORIGIN) and _is(node.pre_rotation, ORIGIN)
            and _is(node.post_rotation, ORIGIN)):
        return
    raise ValueError(
        "%r is rotated under %r, which is scaled %s, with InheritType %d: FBX "
        "does not compose that as parent-then-child and this reader will not "
        "guess. Freeze the parent's scale, or measure in Maya."
        % (node.name, parent.name, tuple(round(v, 4) for v in parent.scaling),
           node.inherit_type)
    )


def world_vertex_bounds(facts, rotations=None):
    """Axis-aligned bounds of every vertex, composed through the hierarchy.

    The demigol gate could read vertex magnitude straight out of the file
    because its chunks sit in one flat rank. A rig cannot: a 4 m creature is 33
    chunks whose own vertices are all under 1 m, so the only way to assert the
    delivered height from the BYTES is to compose the tree.

    `rotations` maps node name -> euler triple in degrees and applies a POSE:
    the delivery states poses as per-chunk rotations, so measuring one is
    substituting them here. Names absent from the map keep the file's own.
    """
    by_uid = {n.uid: n for n in facts.nodes if n.uid is not None}
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for node in facts.nodes:
        verts = facts.geometries.get(node.geometry)
        if not verts:
            continue
        # The geometric transform belongs to these vertices alone, so it goes
        # in front of the chain and no child ever sees it.
        chain = [_geometric(node)] if _has_geometric(node) else []
        walker = node
        seen = set()
        while walker is not None and walker.uid not in seen:
            seen.add(walker.uid)
            posed = (rotations or {}).get(walker.name)
            parent = by_uid.get(walker.parent)
            _refuse_unsupported_inheritance(walker, parent, posed)
            chain.append(_local(walker, posed))
            walker = parent
        for i in range(0, len(verts), 3):
            p = list(verts[i:i + 3])
            for M, off in chain:
                p = [sum(p[r] * M[r][c] for r in range(3)) + off[c] for c in range(3)]
            for c in range(3):
                lo[c] = min(lo[c], p[c])
                hi[c] = max(hi[c], p[c])
    return tuple(lo), tuple(hi)


# FBX declares its unit as centimetres-per-file-unit: 1.0 means the numbers are
# centimetres, 100.0 means they are metres.
DECLARES_METRES = 100.0


def set_unit_scale_factor(path, value=DECLARES_METRES):
    """Correct the unit DECLARATION in place, leaving all geometry untouched.

    Maya's exporter writes 1.0 here for a metre-native scene and offers no way
    to change it - measured across nine combinations of currentUnit,
    UnitsSelector, DynamicScaleConversion and FBXExportScaleFactor, every one
    byte-identical. That leaves the file self-contradictory: metre-magnitude
    vertices declared as centimetres, so a correct consumer reads a 3 m piece
    as 3 cm.

    This overwrites one IEEE-754 double with another of the same width, so no
    offset, length or nested record in the file moves.
    """
    facts = read_fbx(path)
    if facts.unit_scale_offset is None:
        raise ValueError("%s declares no UnitScaleFactor" % path)
    with open(path, "r+b") as fh:
        fh.seek(facts.unit_scale_offset)
        fh.write(struct.pack("<d", float(value)))
    return read_fbx(path).unit_scale_factor


def skin_facts(facts, tol=1e-3):
    """What the file's skin records actually hold. Reading, not policy.

    Weight sums are composed per vertex across every cluster of each skin; a
    correct bind normalises them to 1.0 in the file. max_weight_sum_error is
    measured over vertices carrying ANY weight; vertices carrying none are
    counted separately - the file-side image of bind_skin's
    unweighted_vertices gate. Anything this reader cannot verify goes out as
    None with a reason, never a plausible guess (#645).
    """
    influenced = {c["model"] for c in facts.clusters.values()
                  if c["model"] is not None}
    max_err = None
    unweighted = 0
    # #817: how many clusters carry a NON-ZERO weight for each vertex - the
    # number a 4-influence consumer caps. Read from the records that ship,
    # so a weight the exporter dropped (it drops anything below 1e-3
    # without renormalising - see WEIGHT_SUM_TOL's note in export.py) is
    # not counted as an influence the consumer will see.
    max_influences = None
    over_four = 0
    reasons = []
    for uid, skin in facts.skins.items():
        verts = facts.geometries.get(skin["geometry"])
        if not verts:
            reasons.append(
                "skin %d connects to no geometry this reader holds" % uid)
            continue
        num = len(verts) // 3
        sums = [0.0] * num
        counts = [0] * num
        readable = True
        for cluster_uid in skin["clusters"]:
            cluster = facts.clusters.get(cluster_uid) or {}
            idx = cluster.get("indexes") or ()
            wts = cluster.get("weights") or ()
            if len(idx) != len(wts):
                readable = False
                reasons.append(
                    "cluster %d holds %d indexes but %d weights"
                    % (cluster_uid, len(idx), len(wts)))
                continue
            for i, w in zip(idx, wts):
                if 0 <= i < num:
                    sums[i] += w
                    if w > tol:
                        counts[i] += 1
                else:
                    readable = False
                    reasons.append(
                        "cluster %d indexes vertex %d of %d"
                        % (cluster_uid, i, num))
                    break
        if not readable:
            continue
        for s in sums:
            if s <= tol:
                unweighted += 1
            else:
                err = abs(s - 1.0)
                if max_err is None or err > max_err:
                    max_err = err
        if counts:
            top = max(counts)
            max_influences = top if max_influences is None else max(max_influences, top)
            over_four += sum(1 for c in counts if c > 4)
    return {
        "deformers": len(facts.skins),
        "clusters": len(facts.clusters),
        "influenced_models": len(influenced),
        "bind_pose_present": facts.bind_pose_count > 0,
        "max_weight_sum_error": max_err,
        "unweighted_file_vertices": unweighted,
        "max_influences": max_influences,
        "vertices_over_4_influences": over_four,
        "unavailable_reason": "; ".join(reasons) or None,
    }


def shape_facts(facts):
    """What the file's blend-shape records hold. Reading, not policy (#645).

    Per channel: the alias name maya_create_blendshape authored and the
    linked Shape geometry's payload sizes. Maya has been observed writing
    the channel name either bare or deformer-qualified, so the name is
    cleaned to its last dot-segment (measured under mayapy,
    TestBlendshapeExportInMaya - the naming pin for this reader). Structural
    link failures are reasons, never guesses; POLICY (empty deltas,
    index/point mismatch, missing declared names) lives in
    export.shape_violations.
    """
    reasons = []
    shapes = []
    for uid, channel in facts.blend_channels.items():
        entry = {"name": channel["name"].split(".")[-1],
                 "points": 0, "indexes": 0}
        geom_uid = channel["shape"]
        if geom_uid is None or geom_uid not in facts.shape_geoms:
            reasons.append("channel %r links no shape geometry"
                           % entry["name"])
        else:
            geom = facts.shape_geoms[geom_uid]
            entry["points"] = geom["points"]
            entry["indexes"] = len(geom["indexes"])
        if channel["deformer"] is None:
            reasons.append("channel %r links no blendShape deformer"
                           % entry["name"])
        shapes.append(entry)
    for uid, deformer in facts.blend_deformers.items():
        if deformer["geometry"] is None:
            reasons.append(
                "blendShape deformer %d deforms no geometry this reader "
                "holds" % uid)
    return {
        "blend_deformers": len(facts.blend_deformers),
        "channels": len(facts.blend_channels),
        "shapes": sorted(shapes, key=lambda e: e["name"]),
        "unavailable_reason": "; ".join(reasons) or None,
    }


def anim_facts(facts):
    """What the file's animation records hold. Reading, not policy (#645).

    Per curve node: the Model (joint) or BlendShapeChannel it drives, the
    OP-connection property that says WHICH plug ("Lcl Rotation",
    "Lcl Translation", "DeformPercent" - measured under mayapy,
    TestClipExportInMaya), the curve count, their agreed key count, and -
    #718 Task 10b - the "take" it is attributed to: the name of the
    AnimationStack whose AnimationLayer owns this curve node, resolved
    structurally through the connection chain read_fbx keeps (never a
    guess from tick ranges - two takes can share a boundary, and this
    reader reports what it read, not what it infers). `None` when the
    chain is absent (an orphan curve node, or a file this reader could not
    attribute for any reason).

    MEASURED (t718-10-report.md finding #3): a multi-take file carries one
    curve-node record per animated plug PER TAKE - a two-clip file holds
    THREE for a plug any clip touches, not one. Without "take" there is no
    way to tell them apart. Structural failures - an orphan curve node,
    curves that disagree on key count - are reasons, never guesses; POLICY
    (expected counts, take naming, zero-when-off) lives in
    export.anim_violations.
    """
    reasons = []
    targets = []
    by_uid = {n.uid: n for n in facts.nodes if n.uid is not None}
    for uid, node in sorted(facts.anim_nodes.items()):
        layer_uid = node.get("layer")
        stack_uid = (facts.anim_layers_by_uid.get(layer_uid)
                    if layer_uid is not None else None)
        take_name = (facts.anim_stacks_by_uid.get(stack_uid)
                    if stack_uid is not None else None)
        entry = {"target": None,
                 "property": (node["property"] or node["name"]),
                 "curves": len(node["curves"]),
                 "key_count": None, "duration_s": None,
                 "take": take_name}
        if node["target_kind"] == "model" and node["target"] in by_uid:
            entry["target"] = by_uid[node["target"]].name
        elif (node["target_kind"] == "channel"
                and node["target"] in facts.blend_channels):
            entry["target"] = (facts.blend_channels[node["target"]]["name"]
                               .split(".")[-1])
        else:
            reasons.append("curve node %r drives nothing this reader holds"
                           % node["name"])
        counts = set()
        first = []
        last = []
        for cuid in node["curves"]:
            curve = facts.anim_curves.get(cuid)
            if curve is None:
                continue
            counts.add(curve["key_count"])
            if curve["first_tick"] is not None:
                first.append(curve["first_tick"])
            if curve["last_tick"] is not None:
                last.append(curve["last_tick"])
        if len(counts) == 1:
            entry["key_count"] = counts.pop()
            if first and last:
                entry["duration_s"] = ((max(last) - min(first))
                                       / float(KTIME_PER_SECOND))
        elif counts:
            reasons.append(
                "curve node %r's curves disagree on key count (%s)"
                % (node["name"],
                   ", ".join(str(c) for c in sorted(counts))))
        targets.append(entry)
    takes = []
    for take in facts.takes:
        start = stop = duration = None
        if take["start_tick"] is not None:
            start = take["start_tick"] / float(KTIME_PER_SECOND)
        if take["stop_tick"] is not None:
            stop = take["stop_tick"] / float(KTIME_PER_SECOND)
        if start is not None and stop is not None:
            duration = stop - start
        takes.append({"name": take["name"], "start_s": start,
                      "stop_s": stop, "duration_s": duration})
    return {
        "stacks": facts.anim_stacks,
        "layers": len(facts.anim_layers),
        "curves": len(facts.anim_curves),
        "curve_nodes": len(facts.anim_nodes),
        "takes": takes,
        "targets": sorted(targets,
                          key=lambda e: (e["target"] or "", e["property"],
                                        e["take"] or "")),
        "unavailable_reason": "; ".join(reasons) or None,
    }


def texture_facts(facts):
    """Texture references the FILE carries (#714).

    Basenames, not paths: the exporter may rewrite a path to a relative
    form, and the basename is the part MEASURED to survive intact (the
    committed drifter fixture carries the same basename in both the
    absolute Path/FileName field and the relative RelPath/
    RelativeFilename field). A record whose filename could not be read
    reports an empty basename rather than being dropped - the gate then
    says so instead of silently missing a match.
    """
    def rows(store):
        return [{"name": rec["name"],
                 "basename": os.path.basename(rec["filename"])}
                for rec in store.values()]

    return {"texture_records": len(facts.textures),
            "video_records": len(facts.videos),
            "textures": rows(facts.textures),
            "videos": rows(facts.videos),
            "unavailable_reason": None}
