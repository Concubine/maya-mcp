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
import struct
import zlib
from dataclasses import dataclass, field
from typing import Optional

IDENTITY = (1.0, 1.0, 1.0)
ORIGIN = (0.0, 0.0, 0.0)

_SIMPLE = {b"C": ("<?", 1), b"B": ("<B", 1), b"Y": ("<h", 2), b"I": ("<i", 4),
           b"F": ("<f", 4), b"D": ("<d", 8), b"L": ("<q", 8)}
_ARRAYS = (b"f", b"d", b"l", b"i", b"c", b"b")

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

    def prop(pos):
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
            if code == b"d":
                raw = zlib.decompress(payload) if encoding == 1 else payload
                return struct.unpack("<%dd" % length, raw), pos
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
                val, pos = prop(pos)
                values.append(val)

            if name == "Vertices" and values and isinstance(values[0], tuple):
                facts.meshes.append(values[0])
                if isinstance(node, int):
                    facts.geometries[node] = values[0]
            elif name == "C" and len(values) >= 3:
                # ("OO", child, parent). Geometry connects to its Model the same
                # way a Model connects to its parent Model, so one pass wires
                # both; the 0 parent is the scene root.
                _connections.append((values[1], values[2]))
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

            child = node
            if name == "Model":
                strs = [v for v in values if isinstance(v, str)]
                uid = values[0] if values and isinstance(values[0], int) else None
                child = FbxNode(name=_clean(strs[0]) if strs else "?",
                                kind=strs[1] if len(strs) > 1 else "?", uid=uid)
                facts.nodes.append(child)
            elif name == "Geometry":
                child = values[0] if values and isinstance(values[0], int) else None
            if pos < end_off:
                walk(pos, end_off, child)
            pos = end_off
        return pos

    walk(27, len(data), None)

    by_uid = {n.uid: n for n in facts.nodes if n.uid is not None}
    for child, parent in _connections:
        if child in by_uid:
            by_uid[child].parent = parent if parent in by_uid else None
        elif child in facts.geometries and parent in by_uid:
            by_uid[parent].geometry = child
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
