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


@dataclass
class FbxFacts:
    version: int
    nodes: list = field(default_factory=list)
    meshes: list = field(default_factory=list)
    unit_scale_factor: Optional[float] = None


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
            for _ in range(nprops):
                val, pos = prop(pos)
                values.append(val)

            if name == "Vertices" and values and isinstance(values[0], tuple):
                facts.meshes.append(values[0])
            elif name == "P" and values and isinstance(values[0], str):
                key = values[0]
                if key == "UnitScaleFactor":
                    facts.unit_scale_factor = float(values[-1])
                elif node is not None and key in ("Lcl Scaling", "Lcl Translation"):
                    triple = tuple(float(v) for v in values[-3:])
                    if key == "Lcl Scaling":
                        node.scaling = triple
                    else:
                        node.translation = triple

            child = node
            if name == "Model":
                strs = [v for v in values if isinstance(v, str)]
                child = FbxNode(name=_clean(strs[0]) if strs else "?",
                                kind=strs[1] if len(strs) > 1 else "?")
                facts.nodes.append(child)
            if pos < end_off:
                walk(pos, end_off, child)
            pos = end_off
        return pos

    walk(27, len(data), None)
    return facts
