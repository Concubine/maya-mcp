"""Image handling on the server side: decode plugin payloads, enforce size caps.

Viewport captures travel as base64 PNG inside result frames; before they reach
the LLM they are downscaled to MAYA_MCP_MAX_IMAGE_PX on the longest edge.
contact_sheet() composites a turntable's N frames into one row-major grid
image so a final judgement pass costs one image instead of N.
"""

from __future__ import annotations

import base64
import binascii
import io
import math
import os

from PIL import Image as PILImage

DEFAULT_MAX_PX = 768


def max_image_px() -> int:
    try:
        return int(os.environ.get("MAYA_MCP_MAX_IMAGE_PX", DEFAULT_MAX_PX))
    except ValueError:
        return DEFAULT_MAX_PX


def decode_and_downscale(png_b64: str, max_px: int | None = None) -> bytes:
    """Decode a base64 PNG and cap its longest edge at max_px; returns PNG bytes."""
    if max_px is None:
        max_px = max_image_px()
    try:
        raw = base64.b64decode(png_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("viewport payload is not valid base64: %s" % exc) from exc
    try:
        img = PILImage.open(io.BytesIO(raw))
        img.load()
    except Exception as exc:
        raise ValueError("viewport payload is not a decodable image: %s" % exc) from exc

    width, height = img.size
    longest = max(width, height)
    if longest > max_px:
        scale = max_px / longest
        img = img.resize(
            (max(1, round(width * scale)), max(1, round(height * scale))),
            PILImage.LANCZOS,
        )

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _open(png: bytes) -> PILImage.Image:
    return PILImage.open(io.BytesIO(png)).convert("RGB")


def _to_png(img: PILImage.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def contact_sheet(pngs, cols: int | None = None) -> bytes:
    """Composite frames into one row-major grid image.

    Row-major matters: the caller reads the sheet as "frame 0 top-left, going
    right", and a column-major sheet would silently mislabel every view.
    """
    if not pngs:
        raise ValueError("contact_sheet needs at least one image")
    tiles = [_open(p) for p in pngs]
    cell_w = max(t.width for t in tiles)
    cell_h = max(t.height for t in tiles)
    if cols is None:
        # Favor a wide-ish rectangle over a tall one: pick rows as the floor
        # of sqrt(n) and let cols absorb the remainder, so an exact square
        # count (8 -> 4x2, 16 -> 4x4) lands flush and others get one
        # partially-filled last row rather than a lopsided column count.
        rows_for_cols = max(1, int(math.floor(math.sqrt(len(tiles)))))
        cols = int(math.ceil(len(tiles) / rows_for_cols))
    rows = int(math.ceil(len(tiles) / cols))
    sheet = PILImage.new("RGB", (cols * cell_w, rows * cell_h), (18, 18, 20))
    for i, tile in enumerate(tiles):
        x = (i % cols) * cell_w
        y = (i // cols) * cell_h
        sheet.paste(tile, (x, y))
    return _to_png(sheet)


# An 8-bit alpha of 8 or less is invisible against any background; counting it
# as opaque would let a "successful" transparent playblast pass the blank check.
_ALPHA_FLOOR = 9

# A channel at 250+ of 255 is blown: the detail that was there is gone and no
# amount of grading brings it back.
_CLIP_LEVEL = 250


def pixel_stats(png: bytes) -> dict:
    """Opaque-pixel and colour counts for one rendered frame.

    The failure mode a render path must catch is a valid PNG of nothing: an
    unlit scene, a camera aimed at empty space and a window-less playblast all
    return success and an image with no subject in it. Nothing comes in two
    shapes, so both are counted - fully transparent (alpha), and a single flat
    colour edge to edge (an unlit render, or a camera inside an object).
    """
    try:
        img = PILImage.open(io.BytesIO(png))
        img.load()
    except Exception as exc:
        raise ValueError("not a decodable image: %s" % exc) from exc

    total = img.width * img.height
    rgb = img.convert("RGB")
    colors = rgb.getcolors(maxcolors=max(1, total)) or []
    distinct = len(colors)

    if "A" in img.getbands():
        alpha_hist = img.convert("RGBA").getchannel("A").histogram()
        opaque = sum(alpha_hist[_ALPHA_FLOOR:])
    else:
        # No alpha to go on: black is the background a render leaves behind.
        opaque = sum(count for count, color in colors if color != (0, 0, 0))

    # Exposure, measured rather than guessed. The #585 art run took four passes
    # to land an exposure because nothing reported one: the first render blew
    # every surface to flat saturated primaries, which looks exactly like a
    # material failure and is not one. Computed over the whole frame, so a
    # transparent background counts as black - read mean_luma against a
    # comparable frame, not as an absolute.
    clipped = sum(count for count, color in colors if max(color) >= _CLIP_LEVEL)
    luma_sum = sum(
        count * (0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2])
        for count, color in colors
    )

    return {
        "opaque_px": opaque,
        "total_px": total,
        "distinct_colors": distinct,
        "blank": opaque == 0 or distinct <= 1,
        "clipped_px": clipped,
        "clipped_fraction": round(clipped / total, 4) if total else 0.0,
        "mean_luma": round(luma_sum / total, 1) if total else 0.0,
    }


def side_by_side(left_png: bytes, right_png: bytes, gap: int = 8) -> bytes:
    """Reference on the left, current viewport on the right, same scale."""
    left, right = _open(left_png), _open(right_png)
    height = max(left.height, right.height)

    def fit(img):
        if img.height == height:
            return img
        w = max(1, round(img.width * height / img.height))
        return img.resize((w, height), PILImage.LANCZOS)

    left, right = fit(left), fit(right)
    canvas = PILImage.new(
        "RGB", (left.width + gap + right.width, height), (18, 18, 20)
    )
    canvas.paste(left, (0, 0))
    canvas.paste(right, (left.width + gap, 0))
    return _to_png(canvas)
