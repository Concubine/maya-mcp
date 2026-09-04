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
        # The streaming scan stops as soon as a SECOND distinct value is
        # found (review fix #714 Important 4) - non_uniform is already
        # proven at that point, so distinct_values is capped at 2 rather
        # than paying to keep counting the other two pixels.
        assert out["distinct_values"] == 2
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


class TestStreamingUniformity:
    """#714 review Important 4: read_png materializes every pixel as a
    Python tuple, ~1.2GB transient at the advertised 4096 bake resolution.
    uniformity must never build that list - it streams the unfiltered rows
    and stops as soon as a second distinct value proves non_uniform."""

    def test_a_flat_images_streaming_answer_matches_read_png_exactly(
            self, tmp_path):
        # The flat case can never short-circuit (there is no second
        # distinct value to find), so streaming and read_png-based
        # counting must agree exactly here, not just up to a cap.
        rows = [[(7, 7, 7), (7, 7, 7)], [(7, 7, 7), (7, 7, 7)]]
        path = _png(tmp_path / "flat2.png", rows)
        streamed = pngprobe.uniformity(path)
        png = pngprobe.read_png(path)
        assert streamed["pixel_count"] == len(png["pixels"]) == 4
        assert streamed["distinct_values"] == len(set(png["pixels"])) == 1
        assert streamed["non_uniform"] is False

    def test_a_non_uniform_scan_never_reaches_the_last_row(
            self, tmp_path, monkeypatch):
        # A tall image whose first row already carries two colours - the
        # streaming scan must never ask _unfilter_rows for the later rows.
        # That is the whole point of the fix: a 4096-tall bake must not
        # pay to unfilter and box every one of its rows just to learn it
        # is non-uniform.
        height = 200
        rows = ([[(1, 1, 1), (2, 2, 2)]]
               + [[(9, 9, 9), (9, 9, 9)]] * (height - 1))
        path = _png(tmp_path / "tall.png", rows)

        real = pngprobe._unfilter_rows
        seen_rows = []

        def spy(raw, width, h, stride):
            for row in real(raw, width, h, stride):
                seen_rows.append(row)
                yield row

        monkeypatch.setattr(pngprobe, "_unfilter_rows", spy)
        out = pngprobe.uniformity(path)

        assert out["non_uniform"] is True
        assert out["pixel_count"] == 2 * height   # total is still exact
        assert len(seen_rows) < height             # never reached the tail

    def test_no_full_pixels_list_is_ever_built(self, tmp_path, monkeypatch):
        # read_png is the ONLY place allowed to build a `pixels` list of
        # boxed tuples - uniformity must not call it at all.
        rows = [[(1, 1, 1), (2, 2, 2)], [(3, 3, 3), (4, 4, 4)]]
        path = _png(tmp_path / "spied.png", rows)

        def boom(_path):
            raise AssertionError("uniformity must not call read_png")

        monkeypatch.setattr(pngprobe, "read_png", boom)
        out = pngprobe.uniformity(path)
        assert out["non_uniform"] is True


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


class TestOpacity:
    """#765: the frame that measured "fine" and showed nothing.

    The numbers in these tests are the measured ones. A broken viewport
    capture of a cube carried 13 distinct pixel values; a correct capture of
    the same cube carried 15. Distinctness cannot separate them. Opaque
    coverage separates them absolutely: 0 against 18872.
    """

    def _rgba(self, path, rows):
        return _png(path, rows, colour_type=6)

    def test_a_frame_with_zero_alpha_everywhere_is_blank(self, tmp_path):
        # Real RGB, no alpha anywhere - the exact shape of the #765 frames.
        # A viewer composites this to flat white; a human calls it blank.
        rows = [[(90, 90, 90, 0), (60, 60, 60, 0)],
                [(30, 30, 30, 0), (200, 10, 10, 0)]]
        out = pngprobe.opacity(self._rgba(tmp_path / "ghost.png", rows))
        assert out["blank"] is True
        assert out["unavailable_reason"] is None

    def test_one_opaque_pixel_is_enough_to_not_be_blank(self, tmp_path):
        rows = [[(0, 0, 0, 0), (0, 0, 0, 0)],
                [(0, 0, 0, 0), (90, 90, 90, 255)]]
        out = pngprobe.opacity(self._rgba(tmp_path / "speck.png", rows))
        assert out["blank"] is False
        assert out["opaque_found"] is True

    def test_a_barely_visible_alpha_still_counts_as_background(self, tmp_path):
        # The floor matches images.pixel_stats' so "blank" means one thing on
        # both sides of the wire.
        rows = [[(200, 200, 200, 8), (200, 200, 200, 3)]]
        assert pngprobe.opacity(
            self._rgba(tmp_path / "haze.png", rows))["blank"] is True

    def test_a_subject_smaller_than_the_sample_grid_is_still_found(
        self, tmp_path
    ):
        # The cheap pass samples every 4th row and column, so a single opaque
        # pixel at an unsampled position must still be caught by the second,
        # exhaustive pass - claiming a frame is blank is the expensive claim
        # and is never made on a sample.
        rows = [[(0, 0, 0, 0)] * 9 for _ in range(9)]
        rows[5][6] = (255, 255, 255, 255)
        out = pngprobe.opacity(self._rgba(tmp_path / "needle.png", rows))
        assert out["blank"] is False

    def test_an_image_without_alpha_falls_back_to_non_black(self, tmp_path):
        # An RGB PNG has no alpha to go on; black is the background a capture
        # leaves behind, the same fallback images.pixel_stats makes.
        assert pngprobe.opacity(
            _png(tmp_path / "black.png", [[(0, 0, 0), (0, 0, 0)]])
        )["blank"] is True
        assert pngprobe.opacity(
            _png(tmp_path / "lit.png", [[(0, 0, 0), (1, 0, 0)]])
        )["blank"] is False

    def test_an_unreadable_file_reports_rather_than_raising(self, tmp_path):
        path = tmp_path / "junk.png"
        path.write_bytes(b"not a png at all")
        out = pngprobe.opacity(str(path))
        assert out["blank"] is None
        assert out["unavailable_reason"]

    def test_a_missing_file_reports_rather_than_raising(self, tmp_path):
        out = pngprobe.opacity(str(tmp_path / "nope.png"))
        assert out["blank"] is None
        assert "no file" in out["unavailable_reason"]


class TestDominantColour:
    """#830: a frame VP2 drew before the shading assignment bound comes back
    flat unassigned-green - a valid PNG, fully opaque, wrong material. It
    passes `opacity` (not blank) and `uniformity` (thousands of values in a
    correct frame, so a two-value cap says nothing). What separates them is
    flatness at ONE exact value: 76-83% of the measured bad frames."""

    GREEN = (0, 208, 57)

    def _flat(self, tmp_path, colour, share, size=32):
        """A frame that is `share` one colour and the rest a gradient."""
        rows = []
        flat_rows = int(size * share)
        for y in range(size):
            if y < flat_rows:
                rows.append([colour + (255,)] * size)
            else:
                rows.append([(x * 7 % 256, y * 3 % 256, 40, 255)
                             for x in range(size)])
        return _png(tmp_path / "f.png", rows, colour_type=6)

    def test_it_finds_the_flat_colour_and_its_share(self, tmp_path):
        out = pngprobe.dominant_colour(self._flat(tmp_path, self.GREEN, 0.75))
        assert out["top_rgb"] == list(self.GREEN)
        assert 0.6 < out["top_share"] < 0.9
        assert out["unavailable_reason"] is None

    def test_a_varied_frame_reports_a_small_share(self, tmp_path):
        out = pngprobe.dominant_colour(self._flat(tmp_path, self.GREEN, 0.0))
        assert out["top_share"] < 0.25

    def test_transparent_pixels_are_background_not_subject(self, tmp_path):
        # Half the frame is transparent green: it must not count, or every
        # capture with a big empty margin would read as one flat colour.
        size = 32
        rows = [[(0, 208, 57, 0)] * size for _ in range(size // 2)]
        rows += [[(200, 10, 10, 255)] * size for _ in range(size // 2)]
        out = pngprobe.dominant_colour(_png(tmp_path / "t.png", rows,
                                            colour_type=6))
        assert out["top_rgb"] == [200, 10, 10]
        assert out["top_share"] == 1.0

    def test_a_fully_transparent_frame_says_it_could_not_measure(self, tmp_path):
        rows = [[(0, 208, 57, 0)] * 8 for _ in range(8)]
        out = pngprobe.dominant_colour(_png(tmp_path / "e.png", rows,
                                            colour_type=6))
        assert out["top_rgb"] is None
        assert "no opaque pixels" in out["unavailable_reason"]

    def test_an_unreadable_file_reports_rather_than_raising(self, tmp_path):
        out = pngprobe.dominant_colour(tmp_path / "nope.png")
        assert out["top_rgb"] is None and out["unavailable_reason"]
