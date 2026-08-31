"""A minimal PNG writer - the AO composite's output side.

#770. pngprobe (#714) is the reader half: it exists because nothing
downstream verifies a bake, so the tool checks its own work. This is the
writer half, needed once a tool COMPOSES pixels (apply_ao multiplies a
baked AO map into a colour map) instead of only checking them. Same
technique the eval scripts have always hand-rolled (struct + zlib, filter
type 0, one IDAT), promoted to production; still no image dependency.

Deliberately writes exactly one shape: 8-bit RGB (colour type 2),
non-interlaced - the same shape pngprobe.read_png fully round-trips, so
every byte-check downstream reads what this wrote.
"""

from __future__ import annotations

import struct
import zlib
from typing import Sequence, Tuple

_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(tag: bytes, payload: bytes) -> bytes:
    body = tag + payload
    return (struct.pack(">I", len(payload)) + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))


def write_png(path: str, width: int, height: int,
              pixels: Sequence[Tuple[int, int, int]]) -> None:
    """Write `pixels` (row-major, top row first) as an 8-bit RGB PNG.

    Raises ValueError rather than writing a file whose dimensions lie
    about its content - a wrong-sized map that parses is exactly the kind
    of quiet corruption this repo's byte-checks exist to catch.
    """
    if len(pixels) != width * height:
        raise ValueError(
            "%d pixels do not fill a %dx%d image" % (len(pixels), width,
                                                     height))
    raw = bytearray()
    pos = 0
    for _ in range(height):
        raw.append(0)  # filter type 0 (None)
        for _ in range(width):
            px = pixels[pos]
            pos += 1
            if len(px) != 3:
                raise ValueError(
                    "pixel %r is not an RGB triple - this writer writes "
                    "8-bit RGB only" % (px,))
            raw.extend(px)
    data = (_SIGNATURE
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2,
                                          0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(bytes(raw)))
            + _chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(data)
