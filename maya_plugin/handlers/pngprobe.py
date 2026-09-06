"""A minimal PNG reader, so a bake can be checked for being degenerate.

#714 phase 2. Two measurements make this necessary rather than nice:
convertSolidTx writes a FLAT image (and raises nothing) when the mesh has
no UVs, and the FBX export never validates that a texture file exists or
is any good - so nothing downstream would catch a bad bake. The bake tool
has to inspect its own output.

Deliberately not a general PNG library: it reads 8-bit non-interlaced
images, which is what Maya's own bake was MEASURED to write (P3: bit
depth 8, colour type 2), and reports anything else as unreadable rather
than guessing. `uniformity` never raises - a bake that cannot be measured
is reported as unmeasured, never silently passed.
"""

from __future__ import annotations

import os
import struct
import zlib
from typing import Any, Dict

_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# colour type -> samples per pixel
_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def _unfilter_rows(raw: bytes, width: int, height: int, stride: int):
    """Undo PNG's per-row filters, one row at a time. The five filter
    types are the format's own; a row's predictor reads the RECONSTRUCTED
    previous row, which is why `prev` is only replaced once a row is
    finished.

    A generator on purpose: `uniformity` below only needs rows up to the
    one where a second distinct pixel value turns up, and stops pulling
    from this generator right there - the rows after that point are never
    filtered at all. `_unfilter` (below) drains it into a list for
    `read_png`, whose contract is the whole image."""
    prev = bytearray(width * stride)
    pos = 0
    for _ in range(height):
        ftype = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + width * stride])
        pos += width * stride
        for i in range(len(line)):
            left = line[i - stride] if i >= stride else 0
            up = prev[i]
            upleft = prev[i - stride] if i >= stride else 0
            if ftype == 1:
                line[i] = (line[i] + left) & 0xFF
            elif ftype == 2:
                line[i] = (line[i] + up) & 0xFF
            elif ftype == 3:
                line[i] = (line[i] + ((left + up) >> 1)) & 0xFF
            elif ftype == 4:
                p = left + up - upleft
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - upleft)
                pred = left if (pa <= pb and pa <= pc) else (
                    up if pb <= pc else upleft)
                line[i] = (line[i] + pred) & 0xFF
            elif ftype != 0:
                raise ValueError("unknown PNG filter type %d" % ftype)
        row = bytes(line)
        yield row
        prev = line


def _unfilter(raw: bytes, width: int, height: int, stride: int) -> list:
    """The whole image's unfiltered rows, as a list. See `_unfilter_rows`."""
    return list(_unfilter_rows(raw, width, height, stride))


def _read_header_and_idat(path: str):
    """The IHDR fields plus the raw (still-compressed) IDAT bytes, with the
    same validation `read_png` has always done. Shared by `read_png` and
    the streaming `uniformity` below, neither of which wants a second copy
    of this chunk-walking loop."""
    with open(path, "rb") as fh:
        data = fh.read()
    if not data.startswith(_SIGNATURE):
        raise ValueError("%s is not a PNG" % path)
    pos = len(_SIGNATURE)
    header = None
    idat = bytearray()
    while pos + 8 <= len(data):
        length = struct.unpack_from(">I", data, pos)[0]
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        if tag == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif tag == b"IDAT":
            idat.extend(body)
        elif tag == b"IEND":
            break
        pos += 12 + length
    if header is None:
        raise ValueError("%s carries no IHDR" % path)
    width, height, bit_depth, colour_type, _comp, _filt, interlace = header
    if bit_depth != 8:
        raise ValueError("%s is %d-bit; this reader handles 8-bit only"
                         % (path, bit_depth))
    if interlace:
        raise ValueError("%s is interlaced; this reader handles "
                         "non-interlaced only" % path)
    stride = _CHANNELS.get(colour_type)
    if stride is None:
        raise ValueError("%s has unknown colour type %d"
                         % (path, colour_type))
    return width, height, bit_depth, colour_type, stride, bytes(idat)


def read_png(path) -> Dict[str, Any]:
    """Dimensions, header fields and the flat pixel list. Raises ValueError
    on anything this reader does not handle - callers that must not fail
    use `uniformity` instead."""
    path = str(path)
    width, height, bit_depth, colour_type, stride, idat = (
        _read_header_and_idat(path))
    rows = _unfilter(zlib.decompress(idat), width, height, stride)
    pixels = []
    for row in rows:
        for x in range(width):
            pixels.append(tuple(row[x * stride:(x + 1) * stride]))
    return {"width": width, "height": height, "bit_depth": bit_depth,
            "colour_type": colour_type, "pixels": pixels}


def uniformity(path) -> Dict[str, Any]:
    """How many distinct pixel values the image carries - the honest test
    for "did this bake actually sample anything?".

    Never raises. A file that cannot be read reports non_uniform=None with
    a reason, so a caller says "could not measure this bake" instead of
    either crashing or claiming the bake is fine.

    Streams rather than calling `read_png`: `read_png` materializes every
    pixel as a Python tuple in a `pixels` list, which at the advertised
    4096 bake resolution is ~16.7M tuples (~1.2GB transient, tens of
    seconds of pure-Python work) inside the user's live Maya process for
    every map baked. The only question this function answers is "is there
    more than one distinct pixel value", so it walks `_unfilter_rows`
    (never building the full row list either) and stops as soon as a
    SECOND distinct value turns up - that already answers non_uniform=True
    and nothing past it changes the answer. `distinct_values_seen` says
    exactly that: how many values the scan SAW before it stopped - 0
    (unreadable), 1 (flat) or 2 (non-uniform, and no further). It used to
    be called `distinct_values`, and two field reports (redmine #866) read
    the 2 as a count and nearly binned rich bakes on it: the exact count
    is the MCP server's to take from the written file, where PIL is.
    """
    path = str(path)
    if not os.path.isfile(path):
        return {"pixel_count": 0, "distinct_values_seen": 0, "non_uniform": None,
                "unavailable_reason": "no file at %s" % path}
    try:
        width, height, _bit_depth, _colour_type, stride, idat = (
            _read_header_and_idat(path))
        raw = zlib.decompress(idat)
    except Exception as exc:  # noqa: BLE001 - any read failure is reportable
        return {"pixel_count": 0, "distinct_values_seen": 0, "non_uniform": None,
                "unavailable_reason": "%s: %s" % (type(exc).__name__, exc)}

    total = width * height
    seen = set()
    scanned = 0
    try:
        for row in _unfilter_rows(raw, width, height, stride):
            for x in range(width):
                seen.add(row[x * stride:(x + 1) * stride])
                scanned += 1
                if len(seen) >= 2:
                    # Non-uniform is already proven; the remaining pixels
                    # (unscanned rows included - the generator is simply
                    # never asked for another row) cannot change that.
                    return {"pixel_count": total, "distinct_values_seen": 2,
                            "non_uniform": True, "unavailable_reason": None}
    except Exception as exc:  # noqa: BLE001 - any read failure is reportable
        return {"pixel_count": 0, "distinct_values_seen": 0, "non_uniform": None,
                "unavailable_reason": "%s: %s" % (type(exc).__name__, exc)}
    distinct = len(seen)
    return {"pixel_count": scanned, "distinct_values_seen": distinct,
            "non_uniform": distinct > 1, "unavailable_reason": None}


# A pixel this transparent is background, not subject. Matches the alpha floor
# the MCP server's own `images.pixel_stats` uses, so "blank" means one thing
# on both sides of the wire.
_ALPHA_FLOOR = 8
# Rows and columns taken by the cheap first pass. A subject covering 0.1% of
# the frame still lands ~65 samples in a 768px capture, so the fast pass finds
# anything a viewer could see; anything it misses gets the exhaustive pass.
_SAMPLE_STEP = 4


def _opaque_in_row(row, stride: int, step: int) -> bool:
    if stride == 4:
        return any(row[x * stride + 3] > _ALPHA_FLOOR
                   for x in range(0, len(row) // stride, step))
    # No alpha channel to go on: black is the background a capture leaves
    # behind, the same fallback images.pixel_stats makes.
    return any(any(row[x * stride:x * stride + 3])
               for x in range(0, len(row) // stride, step))


def opacity(path) -> Dict[str, Any]:
    """Did this frame draw ANYTHING, or is it a picture of nothing?

    The failure this exists to catch, measured on maya-mcp #765: a viewport
    playblast that returns success and writes a valid PNG carrying real RGB
    but an alpha channel that is zero EVERYWHERE. Every pixel is transparent,
    so a viewer composites it to flat white and a human reads it as "blank",
    while pixel-value tests see plenty of variety - the broken frames measured
    13 distinct values against 15 for a correct capture of a cube, so
    `uniformity` cannot tell them apart. Opaque coverage can: 0 against 18872.

    Never raises; an unreadable file reports blank=None with a reason, so a
    caller says "could not measure this frame" rather than either crashing or
    claiming the frame is fine.

    Two passes, because the cheap answer is only trustworthy in one direction.
    A sampled scan proves NOT-blank as soon as it hits one opaque pixel, which
    is the common case and costs almost nothing. Claiming a frame IS blank is
    the expensive claim, so it is only made after walking every pixel.
    """
    path = str(path)
    if not os.path.isfile(path):
        return {"blank": None, "opaque_found": False, "scanned": 0,
                "unavailable_reason": "no file at %s" % path}
    try:
        width, height, _bit_depth, _colour_type, stride, idat = (
            _read_header_and_idat(path))
        raw = zlib.decompress(idat)
    except Exception as exc:  # noqa: BLE001 - any read failure is reportable
        return {"blank": None, "opaque_found": False, "scanned": 0,
                "unavailable_reason": "%s: %s" % (type(exc).__name__, exc)}

    for step in (_SAMPLE_STEP, 1):
        scanned = 0
        try:
            for index, row in enumerate(
                _unfilter_rows(raw, width, height, stride)
            ):
                if step > 1 and index % step:
                    continue
                scanned += len(row) // stride // step
                if _opaque_in_row(row, stride, step):
                    return {"blank": False, "opaque_found": True,
                            "scanned": scanned, "unavailable_reason": None}
        except Exception as exc:  # noqa: BLE001 - any read failure is reportable
            return {"blank": None, "opaque_found": False, "scanned": scanned,
                    "unavailable_reason": "%s: %s" % (type(exc).__name__, exc)}
    return {"blank": True, "opaque_found": False, "scanned": width * height,
            "unavailable_reason": None}


# Every Nth pixel of every Nth row for the colour census below. The thing it
# looks for covers 76% of the frame when it happens (measured, #830), so a
# 1-in-64 sample settles it; the point of sampling at all is that this runs on
# EVERY captured frame, unlike the blank walk which only pays in the rare case.
_CENSUS_STEP = 8


def dominant_colour(path) -> Dict[str, Any]:
    """The most common opaque RGB in a frame, and what share of it that is.

    Exists for #830: a shape VP2 draws before its shading assignment has bound
    comes back flat unassigned-green, a valid PNG full of opaque pixels that
    passes every other check this module makes. `opacity` cannot see it - the
    frame is not blank - and `uniformity` cannot either, since it stops at two
    distinct values and a lit correct frame has thousands.

    What separates them is FLATNESS at one exact value: the measured bad frame
    was 76% a single RGB, where a correctly shaded one spreads across the
    lighting ramp. Reported as a measurement, never a verdict; the caller
    decides what a given colour means.

    Never raises - an unreadable file reports top_rgb None with a reason.
    """
    path = str(path)
    if not os.path.isfile(path):
        return {"top_rgb": None, "top_share": None, "sampled": 0,
                "unavailable_reason": "no file at %s" % path}
    try:
        width, height, _bit_depth, _colour_type, stride, idat = (
            _read_header_and_idat(path))
        raw = zlib.decompress(idat)
    except Exception as exc:  # noqa: BLE001 - any read failure is reportable
        return {"top_rgb": None, "top_share": None, "sampled": 0,
                "unavailable_reason": "%s: %s" % (type(exc).__name__, exc)}

    counts: Dict[tuple, int] = {}
    sampled = 0
    try:
        for index, row in enumerate(_unfilter_rows(raw, width, height, stride)):
            if index % _CENSUS_STEP:
                continue
            for x in range(0, width, _CENSUS_STEP):
                base = x * stride
                if stride == 4 and row[base + 3] <= _ALPHA_FLOOR:
                    continue  # background, not subject
                rgb = tuple(row[base:base + 3])
                counts[rgb] = counts.get(rgb, 0) + 1
                sampled += 1
    except Exception as exc:  # noqa: BLE001 - any read failure is reportable
        return {"top_rgb": None, "top_share": None, "sampled": sampled,
                "unavailable_reason": "%s: %s" % (type(exc).__name__, exc)}

    if not sampled:
        return {"top_rgb": None, "top_share": None, "sampled": 0,
                "unavailable_reason": "no opaque pixels sampled"}
    top_rgb, top_n = max(counts.items(), key=lambda kv: kv[1])
    return {"top_rgb": list(top_rgb), "top_share": top_n / sampled,
            "sampled": sampled, "unavailable_reason": None}
