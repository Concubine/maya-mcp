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


class TestOutputPaths:
    """#639: the four image tools could not write a file, so a plan whose
    deliverable was 'write every image under evals/<run>/' could not be
    followed through the tool surface at all."""

    def test_a_relative_path_is_refused(self):
        with pytest.raises(ValueError, match="absolute"):
            images.resolve_output_path("run/hero.png")

    def test_a_non_png_extension_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match=r"\.png"):
            images.resolve_output_path(str(tmp_path / "hero.jpg"))

    def test_a_missing_directory_is_refused_rather_than_created(self, tmp_path):
        missing = tmp_path / "nope" / "hero.png"
        with pytest.raises(ValueError, match="does not exist"):
            images.resolve_output_path(str(missing))
        assert not (tmp_path / "nope").exists()

    def test_backslashes_are_normalised(self, tmp_path):
        raw = str(tmp_path).replace("/", "\\") + "\\hero.png"
        assert images.resolve_output_path(raw) == str(tmp_path).replace(
            "\\", "/"
        ) + "/hero.png"

    def test_one_image_keeps_the_path_it_was_given(self):
        assert images.label_paths("D:/run/hero.png", ["front"]) == ["D:/run/hero.png"]

    def test_several_images_get_the_label_before_the_extension(self):
        assert images.label_paths("D:/run/hero.png", ["front", "three_quarter"]) == [
            "D:/run/hero_front.png", "D:/run/hero_three_quarter.png"
        ]

    def test_a_dag_path_label_becomes_a_usable_filename(self):
        out = images.label_paths("D:/run/kit.png", ["|golem|chest", "|golem|arm_L"])
        assert out == ["D:/run/kit_golem_chest.png", "D:/run/kit_golem_arm_L.png"]

    def test_a_label_of_nothing_still_produces_a_name(self):
        assert images.label_paths("D:/run/x.png", ["", "|"]) == [
            "D:/run/x_frame.png", "D:/run/x_frame.png"
        ]

    def test_write_png_lands_the_bytes(self, tmp_path):
        target = str(tmp_path / "hero.png")
        payload = base64.b64decode(png_b64(8, 8))
        assert images.write_png(target, payload) == target
        with open(target, "rb") as fh:
            assert fh.read() == payload
        # and nothing half-written was left behind
        assert not (tmp_path / "hero.png.part.png").exists()

    def test_write_png_replaces_an_existing_file_whole(self, tmp_path):
        target = str(tmp_path / "hero.png")
        images.write_png(target, base64.b64decode(png_b64(8, 8)))
        second = base64.b64decode(png_b64(16, 16))
        images.write_png(target, second)
        with open(target, "rb") as fh:
            assert fh.read() == second


class TestSheetsCarryTheirCells:
    """#832: a contact sheet is read CELL by cell, and the message copy used
    to be capped at the single-image 768 px - so 8 frames came back as 192-px
    cells at every `resolution` from 256 to 1024 (measured through the
    wrapper, evals/capture_params_probe_832). The sheet now gets the largest
    frame an LLM reads at full detail, and the wrapper says what the cells
    came out as."""

    def test_the_grid_is_the_one_contact_sheet_lays_out(self):
        assert images.grid_for(8) == (4, 2)
        assert images.grid_for(16) == (4, 4)
        assert images.grid_for(4) == (2, 2)
        assert images.grid_for(2) == (2, 1)
        assert images.grid_for(6) == (3, 2)
        assert images.grid_for(1) == (1, 1)
        assert images.grid_for(6, cols=6) == (6, 1)
        assert images.grid_for(5, cols=2) == (2, 3)

    def test_the_sheet_cap_is_the_largest_frame_an_llm_reads(self, monkeypatch):
        monkeypatch.delenv("MAYA_MCP_MAX_SHEET_PX", raising=False)
        assert images.max_sheet_px() == 1568
        monkeypatch.setenv("MAYA_MCP_MAX_SHEET_PX", "1024")
        assert images.max_sheet_px() == 1024

    def test_a_sheet_within_the_cap_reports_its_cells_whole(self):
        lines = images.sheet_report((1536, 768), (1536, 768), count=8, cols=4,
                                    requested_cell=384, path=None)
        assert lines == ["sheet: 1536x768 px, 8 cells of 384 px in 4 columns"]

    def test_a_capped_sheet_says_what_the_cells_came_out_as_and_why(self):
        lines = images.sheet_report((4096, 2048), (1568, 784), count=8, cols=4,
                                    requested_cell=1024, path=None)
        assert lines[0] == "sheet: 1568x784 px, 8 cells of 392 px in 4 columns"
        note = lines[1]
        assert "392 px" in note and "1024" in note and "1568" in note
        assert "path" in note  # the way to get the full cells
        assert "columns" in note  # and the other way

    def test_a_capped_sheet_with_a_file_names_the_file(self):
        lines = images.sheet_report((4096, 2048), (1568, 784), count=8, cols=4,
                                    requested_cell=1024, path="D:/run/turn.png")
        assert "D:/run/turn.png" in lines[1] and "1024" in lines[1]

    def test_smaller_cells_that_were_not_the_cap_get_no_cap_note(self):
        # The plugin drew smaller frames than asked (the M3dView fallback,
        # #797 row 36) - the handler's own warning covers that; blaming the
        # cap here would be a lie.
        lines = images.sheet_report((1024, 512), (1024, 512), count=8, cols=4,
                                    requested_cell=384, path=None)
        assert lines == ["sheet: 1024x512 px, 8 cells of 256 px in 4 columns"]
