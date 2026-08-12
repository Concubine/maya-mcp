"""Image pipeline tests: base64 decode + downscale to the configured cap."""

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
