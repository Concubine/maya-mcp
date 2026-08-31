"""#770: the AO composite writes real PNG files with no image dependency.

pngprobe (#714) promoted the eval scripts' hand-rolled PNG READER to
production; this is the matching writer, needed because apply_ao composites
AO into a colour map per texel and must write the result somewhere the
scene (and the FBX consumer) can read. Round-trips are asserted through
pngprobe.read_png - the writer and reader must agree on the format or
every downstream byte-check lies.
"""

import pytest

from maya_plugin.handlers import pngprobe, pngwrite


class TestWritePng:
    def test_round_trips_through_pngprobe(self, tmp_path):
        path = str(tmp_path / "out.png")
        pixels = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (9, 9, 9)]
        pngwrite.write_png(path, 2, 2, pixels)
        back = pngprobe.read_png(path)
        assert back["width"] == 2 and back["height"] == 2
        assert back["bit_depth"] == 8 and back["colour_type"] == 2
        assert back["pixels"] == pixels

    def test_a_large_flat_image_round_trips(self, tmp_path):
        # More than one IDAT row's worth, all-same value: exercises the
        # filter-0 path at a realistic bake size without being slow.
        path = str(tmp_path / "flat.png")
        pixels = [(7, 7, 7)] * (64 * 64)
        pngwrite.write_png(path, 64, 64, pixels)
        back = pngprobe.uniformity(path)
        assert back["pixel_count"] == 64 * 64
        assert back["non_uniform"] is False

    def test_pixel_count_mismatch_raises(self, tmp_path):
        with pytest.raises(ValueError, match="3 pixels"):
            pngwrite.write_png(str(tmp_path / "bad.png"), 2, 2,
                               [(0, 0, 0)] * 3)

    def test_a_non_rgb_tuple_raises(self, tmp_path):
        with pytest.raises(ValueError, match="RGB"):
            pngwrite.write_png(str(tmp_path / "bad.png"), 1, 1,
                               [(0, 0, 0, 255)])
