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
from PIL import ImageStat

DEFAULT_MAX_PX = 768
# A contact sheet is read CELL by cell, so it gets the largest frame an LLM
# takes at full detail - 1568 px on the long edge (Anthropic's documented
# ceiling; anything larger is downsampled by the model itself, so sending
# more is bytes for nothing). Under the single-image cap above, 8 turntable
# frames came back as a 768x384 sheet of 192-px cells at every `resolution`
# from 256 to 1024 (MEASURED through the wrapper, redmine #832), which a
# fresh agent could judge for silhouette and nothing else - and the knob it
# raised twice to fix that changed nothing it could see.
DEFAULT_MAX_SHEET_PX = 1568


def max_image_px() -> int:
    try:
        return int(os.environ.get("MAYA_MCP_MAX_IMAGE_PX", DEFAULT_MAX_PX))
    except ValueError:
        return DEFAULT_MAX_PX


def max_sheet_px() -> int:
    try:
        return int(os.environ.get("MAYA_MCP_MAX_SHEET_PX", DEFAULT_MAX_SHEET_PX))
    except ValueError:
        return DEFAULT_MAX_SHEET_PX


def png_size(png: bytes) -> tuple[int, int]:
    """(width, height) of PNG bytes, without decoding the pixels."""
    return PILImage.open(io.BytesIO(png)).size


def grid_for(count: int, cols: int | None = None) -> tuple[int, int]:
    """The (cols, rows) contact_sheet lays `count` cells out in.

    Favor a wide-ish rectangle over a tall one: pick rows as the floor of
    sqrt(n) and let cols absorb the remainder, so an exact square count
    (8 -> 4x2, 16 -> 4x4) lands flush and others get one partially-filled
    last row rather than a lopsided column count.
    """
    count = max(1, int(count))
    if cols is None:
        rows_for_cols = max(1, int(math.floor(math.sqrt(count))))
        cols = int(math.ceil(count / rows_for_cols))
    cols = max(1, int(cols))
    return cols, int(math.ceil(count / cols))


def sheet_report(sheet_size, message_size, count: int, cols: int,
                 requested_cell: int, path: str | None) -> list[str]:
    """What the message's copy of a sheet carries per cell - and, when the
    cap shrank the cells below what was asked, why and what to do about it.

    The first line is always there: a caller who asked for 1024-px cells
    and reads a sheet of 392-px ones deserves the number, not a blur to
    infer it from. The note only follows when the MESSAGE copy is what
    shrank them - cells smaller than asked for any other reason (the plugin
    drew smaller frames, #797 row 36) are that handler's warning to give,
    and blaming the cap here would be a lie.
    """
    width, height = int(message_size[0]), int(message_size[1])
    cell = width // max(1, int(cols))
    lines = ["sheet: %dx%d px, %d cells of %d px in %d columns"
             % (width, height, count, cell, cols)]
    if cell < requested_cell and (width, height) != tuple(int(v) for v in sheet_size):
        if path:
            full = "the file at %s has the full %d-px cells" % (path, requested_cell)
        else:
            full = "path= writes the full %d-px cells" % requested_cell
        lines.append(
            "note: the cells came out at %d px, not the %d asked: the returned sheet "
            "is capped at %d px on its long edge (MAYA_MCP_MAX_SHEET_PX, the largest "
            "frame an LLM reads at full detail), and %d columns of %d px need %d. "
            "Fewer columns carry bigger cells, and %s"
            % (cell, requested_cell, max(width, height), cols, requested_cell,
               cols * requested_cell, full))
    return lines


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


def resolve_output_path(path: str) -> str:
    """Validate an image output path on the same contract as export_fbx's.

    One rule across the tool surface beats two, so the reasoning is that
    tool's: a relative path resolves against a working directory that is not
    the one you ran anything from, and a tool does not create directories it
    was not asked to create.
    """
    if not isinstance(path, str) or not path.strip():
        raise ValueError(
            "path must be a non-empty string, e.g. path='D:/run/hero.png'"
        )
    path = path.strip().replace("\\", "/")
    if not path.lower().endswith(".png"):
        raise ValueError("path %r must end in .png - these tools write PNG" % path)
    if not os.path.isabs(path):
        raise ValueError(
            "path %r must be absolute: a relative path resolves against the "
            "server's working directory, not yours" % path
        )
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        raise ValueError(
            "the directory %r does not exist - create it first; this tool does "
            "not make directories it was not asked to make" % parent
        )
    return path


def label_paths(path: str, labels) -> list[str]:
    """One output path per image produced by a call.

    A call that makes ONE image writes exactly the path asked for. A call that
    makes several cannot, so each label goes in before the extension:
    `D:/run/hero.png` with angles front and side writes `hero_front.png` and
    `hero_side.png`. Predicting the filenames matters more than brevity - the
    caller has to be able to name them in a manifest afterwards.
    """
    labels = list(labels)
    if len(labels) <= 1:
        return [path]
    stem, ext = os.path.splitext(path)
    return ["%s_%s%s" % (stem, _slug(label), ext) for label in labels]


def _slug(label: str) -> str:
    """A label as a filename fragment. Subject names are long DAG paths."""
    cleaned = "".join(
        ch if (ch.isalnum() or ch in "-_") else "_" for ch in str(label).strip("|")
    )
    return cleaned.strip("_") or "frame"


def write_png(path: str, png: bytes) -> str:
    """Write PNG bytes to `path` via a sibling temp, so no reader ever sees half."""
    tmp = path + ".part.png"
    with open(tmp, "wb") as fh:
        fh.write(png)
    os.replace(tmp, path)
    return path


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
    cols, rows = grid_for(len(tiles), cols)
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


def map_census(path: str) -> dict:
    """An exact account of a written map's values (#866).

    The plugin's own scan stops at the second distinct value on purpose (a
    4096 bake is 16.7M pixels of pure-Python unfiltering inside Maya), and
    two field reports read that 2 as a count and nearly binned rich bakes
    on it. The server has PIL and the file, so it counts: distinct RGB
    values over the whole image, and the luma range and spread - a flat map
    has a stddev of 0, a rich AO map reads tens. Never raises: an
    unreadable file is reported as such, distinct from "1".
    """
    try:
        img = PILImage.open(path)
        img.load()
    except Exception as exc:  # noqa: BLE001 - reported, never raised
        return {"census_unavailable_reason": "%s: %s" % (type(exc).__name__, exc)}
    rgb = img.convert("RGB")
    total = max(1, rgb.width * rgb.height)
    colours = rgb.getcolors(maxcolors=total) or []
    stat = ImageStat.Stat(rgb.convert("L"))
    return {
        "distinct_values": len(colours),
        "luma_min": int(stat.extrema[0][0]),
        "luma_max": int(stat.extrema[0][1]),
        "luma_mean": round(float(stat.mean[0]), 2),
        "luma_stddev": round(float(stat.stddev[0]), 2),
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
