"""#714 phase 2: the bake tool inspects its own output.

MEASURED (evals/bake_probe_714.py, P3): convertSolidTx writes 8-bit RGB
(colour type 2), no interlace - so that is the shape this reader must
handle. Anything else it cannot read is reported, never guessed at.
"""

import struct
import zlib

import pytest

from maya_plugin.handlers import pngprobe


def _png(path, rows, bit_depth=8, colour_type=2):
    """A real PNG built the way evals/tool_gaps_live.py's write_png does -
    no Pillow anywhere in this repo. `rows` is a list of lists of
    per-pixel tuples."""
    raw = bytearray()
    for row in rows:
        raw.append(0)                      # filter type 0 (None)
        for px in row:
            raw.extend(px)

    def chunk(tag, payload):
        body = tag + payload
        return (struct.pack(">I", len(payload)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    width, height = len(rows[0]), len(rows)
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, bit_depth,
                                        colour_type, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(raw)))
           + chunk(b"IEND", b""))
    path.write_bytes(png)
    return str(path)


class TestReadPng:
    def test_it_reads_dimensions_and_pixels(self, tmp_path):
        path = _png(tmp_path / "two.png",
                    [[(255, 0, 0), (0, 255, 0)],
                     [(0, 0, 255), (9, 9, 9)]])
        out = pngprobe.read_png(path)
        assert out["width"] == 2 and out["height"] == 2
        assert out["bit_depth"] == 8 and out["colour_type"] == 2
        assert (255, 0, 0) in out["pixels"] and (9, 9, 9) in out["pixels"]

    def test_a_non_png_raises(self, tmp_path):
        bad = tmp_path / "not.png"
        bad.write_bytes(b"nope")
        with pytest.raises(ValueError, match="PNG"):
            pngprobe.read_png(str(bad))


class TestUniformity:
    def test_a_varied_image_is_non_uniform(self, tmp_path):
        path = _png(tmp_path / "varied.png",
                    [[(1, 1, 1), (2, 2, 2)], [(3, 3, 3), (4, 4, 4)]])
        out = pngprobe.uniformity(path)
        assert out["pixel_count"] == 4
        assert out["distinct_values"] == 4
        assert out["non_uniform"] is True
        assert out["unavailable_reason"] is None

    def test_a_flat_image_is_uniform(self, tmp_path):
        # The MEASURED failure mode: a UV-less mesh bakes exactly this.
        path = _png(tmp_path / "flat.png",
                    [[(7, 7, 7), (7, 7, 7)], [(7, 7, 7), (7, 7, 7)]])
        out = pngprobe.uniformity(path)
        assert out["distinct_values"] == 1
        assert out["non_uniform"] is False

    def test_an_unreadable_file_reports_rather_than_raising(self, tmp_path):
        bad = tmp_path / "broken.png"
        bad.write_bytes(b"\x89PNG\r\n\x1a\n" + b"garbage")
        out = pngprobe.uniformity(str(bad))
        assert out["non_uniform"] is None
        assert out["unavailable_reason"]
        assert out["distinct_values"] == 0

    def test_a_missing_file_reports_rather_than_raising(self, tmp_path):
        out = pngprobe.uniformity(str(tmp_path / "nope.png"))
        assert out["non_uniform"] is None
        assert "nope.png" in out["unavailable_reason"]


def _paeth_predictor(a, b, c):
    """The PNG spec's Paeth predictor - a=left, b=up, c=upper-left."""
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _png_with_filters(path, rows, filter_types, stride=3):
    """A PNG whose rows are ENCODED with real per-row filters (types 0-4),
    not just filter type 0 like `_png`'s images. This is not covered by
    the brief's own fixture, and the unfilter loop (predictors reading the
    RECONSTRUCTED previous row) is exactly the part most likely to be
    subtly wrong, so it is exercised here by round-tripping: encode with
    the spec's forward filters, decode with pngprobe, and check the
    original pixel values come back unchanged."""
    assert len(rows) == len(filter_types)
    width = len(rows[0])

    def to_bytes(row):
        raw = bytearray()
        for px in row:
            raw.extend(px)
        return raw

    raw_rows = [to_bytes(r) for r in rows]
    encoded = bytearray()
    prev = bytearray(width * stride)
    for raw, ftype in zip(raw_rows, filter_types):
        filt = bytearray(len(raw))
        for i in range(len(raw)):
            left = raw[i - stride] if i >= stride else 0
            up = prev[i]
            upleft = prev[i - stride] if i >= stride else 0
            if ftype == 0:
                filt[i] = raw[i]
            elif ftype == 1:
                filt[i] = (raw[i] - left) & 0xFF
            elif ftype == 2:
                filt[i] = (raw[i] - up) & 0xFF
            elif ftype == 3:
                filt[i] = (raw[i] - ((left + up) >> 1)) & 0xFF
            elif ftype == 4:
                filt[i] = (raw[i] - _paeth_predictor(left, up, upleft)) & 0xFF
            else:
                raise ValueError("bad filter type %d" % ftype)
        encoded.append(ftype)
        encoded.extend(filt)
        prev = raw

    def chunk(tag, payload):
        body = tag + payload
        return (struct.pack(">I", len(payload)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    height = len(rows)
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2,
                                        0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(encoded)))
           + chunk(b"IEND", b""))
    path.write_bytes(png)
    return str(path)


class TestFilterRoundTrip:
    def test_every_filter_type_decodes_to_the_original_pixels(self, tmp_path):
        # One row per filter type 0-4, varied values so Sub/Up/Average/
        # Paeth each predict from genuinely different left/up/upleft
        # neighbours instead of degenerating to a trivial 0 case.
        rows = [
            [(10, 20, 30), (40, 50, 60), (70, 80, 90)],
            [(15, 25, 35), (45, 55, 65), (75, 85, 95)],
            [(200, 100, 50), (10, 250, 5), (128, 128, 128)],
            [(0, 255, 0), (255, 0, 255), (1, 2, 3)],
            [(255, 255, 255), (0, 0, 0), (127, 64, 200)],
        ]
        path = _png_with_filters(tmp_path / "filtered.png", rows,
                                  filter_types=[0, 1, 2, 3, 4])
        out = pngprobe.read_png(path)
        expected = [px for row in rows for px in row]
        assert out["pixels"] == expected

    def test_an_unknown_filter_type_is_reported_not_guessed(self, tmp_path):
        # Filter type 9 isn't in the PNG spec (only 0-4 are defined), so
        # this is built by hand rather than through _png_with_filters,
        # whose encoder only knows how to produce the real five.
        raw = bytes([9]) + bytes([1, 2, 3, 4, 5, 6])

        def chunk(tag, payload):
            body = tag + payload
            return (struct.pack(">I", len(payload)) + body
                    + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

        png = (b"\x89PNG\r\n\x1a\n"
               + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 1, 8, 2, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(raw))
               + chunk(b"IEND", b""))
        path = tmp_path / "badfilter.png"
        path.write_bytes(png)
        with pytest.raises(ValueError, match="filter"):
            pngprobe.read_png(str(path))
