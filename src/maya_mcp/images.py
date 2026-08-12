"""Image handling on the server side: decode plugin payloads, enforce size caps.

Viewport captures travel as base64 PNG inside result frames; before they reach
the LLM they are downscaled to MAYA_MCP_MAX_IMAGE_PX on the longest edge.
(The contact-sheet compositor for turntables lands in M2.)
"""

from __future__ import annotations

import base64
import binascii
import io
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
