"""Image pipeline tests: base64 decode + downscale, and server-side compositing.

Compositing (contact_sheet, side_by_side) is pure PIL, no Maya, no MCP.
"""

import base64
import io

import pytest
from PIL import Image as PILImage

from maya_mcp import images


def png_b64(width, height, color=(120, 90, 60)):
    img = PILImage.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def dims(png_bytes):
    return PILImage.open(io.BytesIO(png_bytes)).size


class TestDownscale:
    def test_large_image_capped_to_max_edge_preserving_aspect(self):
        png = images.decode_and_downscale(png_b64(2000, 1000), max_px=768)
        assert dims(png) == (768, 384)

    def test_tall_image_caps_height(self):
        png = images.decode_and_downscale(png_b64(500, 1500), max_px=750)
        assert dims(png) == (250, 750)

    def test_small_image_untouched_dimensions(self):
        png = images.decode_and_downscale(png_b64(300, 200), max_px=768)
        assert dims(png) == (300, 200)

    def test_output_is_png(self):
        png = images.decode_and_downscale(png_b64(100, 100), max_px=768)
        assert png[:8] == b"\x89PNG\r\n\x1a\n"

    def test_invalid_base64_raises_value_error(self):
        with pytest.raises(ValueError, match="base64"):
            images.decode_and_downscale("!!!not-base64!!!", max_px=768)

    def test_invalid_image_data_raises_value_error(self):
        garbage = base64.b64encode(b"not an image at all").decode("ascii")
        with pytest.raises(ValueError, match="image"):
            images.decode_and_downscale(garbage, max_px=768)

    def test_default_max_px_from_env(self, monkeypatch):
        monkeypatch.setenv("MAYA_MCP_MAX_IMAGE_PX", "128")
        png = images.decode_and_downscale(png_b64(1000, 1000))
        assert dims(png) == (128, 128)


def _png(color, size=(64, 64)):
    buf = io.BytesIO()
    PILImage.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def test_contact_sheet_grid_dimensions_and_cell_order():
    cells = [_png((i * 25, 0, 0)) for i in range(8)]
    sheet = images.contact_sheet(cells)
    im = PILImage.open(io.BytesIO(sheet))
    # 8 cells -> 4x2 grid of 64px cells
    assert im.size == (4 * 64, 2 * 64)
    # cell 0 top-left, cell 4 starts the second row - order must be row-major,
    # because the caller reads the sheet as "frame 0 first, going right"
    assert im.convert("RGB").getpixel((2, 2)) == (0, 0, 0)
    assert im.convert("RGB").getpixel((2, 64 + 2)) == (100, 0, 0)


def test_contact_sheet_handles_a_non_square_count():
    sheet = images.contact_sheet([_png((0, 0, 0)) for _ in range(5)])
    im = PILImage.open(io.BytesIO(sheet))
    # 5 cells -> 3 cols x 2 rows, last cell blank rather than a crash
    assert im.size == (3 * 64, 2 * 64)


def test_contact_sheet_rejects_an_empty_list():
    with pytest.raises(ValueError):
        images.contact_sheet([])


def test_side_by_side_puts_reference_left_and_current_right():
    left, right = _png((255, 0, 0)), _png((0, 0, 255))
    out = images.side_by_side(left, right)
    im = PILImage.open(io.BytesIO(out)).convert("RGB")
    assert im.size[0] >= 128
    assert im.getpixel((2, im.size[1] - 2)) == (255, 0, 0)
    assert im.getpixel((im.size[0] - 2, im.size[1] - 2)) == (0, 0, 255)


def _rgba_png(color, size=(16, 16)):
    buf = io.BytesIO()
    PILImage.new("RGBA", size, color).save(buf, format="PNG")
    return buf.getvalue()


class TestPixelStats:
    def test_fully_transparent_frame_is_blank(self):
        # The exact failure this exists to catch: a playblast from a Maya with
        # no mapped window returns a valid PNG of nothing.
        stats = images.pixel_stats(_rgba_png((0, 0, 0, 0)))
        assert stats["opaque_px"] == 0
        assert stats["total_px"] == 256
        assert stats["blank"] is True

    def test_solid_black_rgb_frame_is_blank(self):
        # Arnold on an unlit scene: opaque, but nothing is in it.
        stats = images.pixel_stats(_png((0, 0, 0), size=(8, 8)))
        assert stats["opaque_px"] == 0
        assert stats["distinct_colors"] == 1
        assert stats["blank"] is True

    def test_lit_frame_is_not_blank(self):
        img = PILImage.new("RGB", (10, 10), (0, 0, 0))
        for x in range(4):
            for y in range(4):
                img.putpixel((x, y), (200, 30 + x * 5, 20))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        stats = images.pixel_stats(buf.getvalue())
        assert stats["opaque_px"] == 16
        assert stats["distinct_colors"] == 5  # 4 lit shades + the background
        assert stats["blank"] is False

    def test_partially_transparent_frame_counts_only_opaque(self):
        img = PILImage.new("RGBA", (4, 4), (0, 0, 0, 0))
        img.putpixel((1, 1), (255, 0, 0, 255))
        img.putpixel((2, 2), (0, 255, 0, 128))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        stats = images.pixel_stats(buf.getvalue())
        assert stats["opaque_px"] == 2
        assert stats["blank"] is False

    def test_a_uniform_lit_frame_is_still_blank(self):
        # One flat colour edge to edge is a renderer failure or a camera inside
        # an object, not a picture of anything.
        stats = images.pixel_stats(_png((90, 90, 90), size=(8, 8)))
        assert stats["distinct_colors"] == 1
        assert stats["blank"] is True

    def test_rejects_undecodable_bytes(self):
        with pytest.raises(ValueError, match="image"):
            images.pixel_stats(b"not a png")
