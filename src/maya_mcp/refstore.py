"""Reference images, held in the MCP server process.

Deliberately NOT stored in the Maya scene: references then survive new_scene,
never dirty the user's file, and cannot be destroyed by a scene operation.
The store is per-server-process and intentionally not persisted - a reference
is a working aid for the current session, not an asset.
"""

from __future__ import annotations

import base64
import binascii
import io
import os
from typing import Dict, List

from PIL import Image as PILImage


class ReferenceStore:
    def __init__(self) -> None:
        self._images: Dict[str, bytes] = {}

    def put(self, ref_id: str, source: str) -> Dict[str, object]:
        if not isinstance(ref_id, str) or not ref_id.strip():
            raise ValueError("ref_id must be a non-empty string")
        raw = self._read(source)
        try:
            img = PILImage.open(io.BytesIO(raw))
            img.load()
        except Exception as exc:
            raise ValueError("reference is not a decodable image: %s" % exc) from exc
        self._images[ref_id] = raw
        return {
            "ref_id": ref_id,
            "width": img.width,
            "height": img.height,
            "bytes": len(raw),
        }

    def get(self, ref_id: str) -> bytes:
        if ref_id not in self._images:
            raise KeyError(
                "no reference %r; loaded references: %s"
                % (ref_id, ", ".join(sorted(self._images)) or "none")
            )
        return self._images[ref_id]

    def list_ids(self) -> List[str]:
        return sorted(self._images)

    @staticmethod
    def _read(source: str) -> bytes:
        if os.path.isfile(source):
            with open(source, "rb") as fh:
                return fh.read()
        try:
            return base64.b64decode(source, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(
                "source is neither an existing file path nor valid base64: %s" % exc
            ) from exc
