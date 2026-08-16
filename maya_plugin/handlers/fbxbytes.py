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
                    if key in ("Lcl Scaling", "Lcl Translation", "Lcl Rotation",
                               "RotationPivot"):
                        triple = tuple(float(v) for v in values[-3:])
                        setattr(node, {"Lcl Scaling": "scaling",
                                       "Lcl Translation": "translation",
                                       "Lcl Rotation": "rotation",
                                       "RotationPivot": "rotation_pivot"}[key],
                                triple)
                    elif key == "RotationOrder":
                        node.rotation_order = int(values[-1])

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


def _local(node, rotation=None):
    """Return (M, t) such that a point p in this node's space maps to p.M + t.

    Maya writes, and FBX stores, `(p - rp) . R + rp + translation`. Scaling is
    applied about the origin: exact for the identity scale a delivery must have,
    and the scale check runs first precisely so this is never the loose one.

    `rotation` overrides the node's own euler triple, which is how a POSE is
    measured: a pose is per-chunk rotations and nothing else, so substituting
    them here and re-composing is the whole of applying one.
    """
    R = _rotation(node.rotation if rotation is None else rotation,
                  node.rotation_order)
    s = node.scaling
    M = [[R[r][c] * s[r] for c in range(3)] for r in range(3)]
    rp = node.rotation_pivot
    offset = [node.translation[c] + rp[c] - sum(rp[r] * R[r][c] for r in range(3))
              for c in range(3)]
    return M, offset


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
        chain = []
        walker = node
        seen = set()
        while walker is not None and walker.uid not in seen:
            seen.add(walker.uid)
            chain.append(_local(walker, (rotations or {}).get(walker.name)))
            walker = by_uid.get(walker.parent)
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
