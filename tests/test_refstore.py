"""In-process reference-image store. No Maya, no MCP."""

import base64
import io

import pytest
from PIL import Image as PILImage

from maya_mcp import refstore


def _png_bytes(color=(10, 200, 10), size=(40, 30)):
    buf = io.BytesIO()
    PILImage.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def test_put_from_a_file_path_then_get(tmp_path):
    path = tmp_path / "ref.png"
    path.write_bytes(_png_bytes())
    store = refstore.ReferenceStore()
    meta = store.put("hero", str(path))
    assert meta["ref_id"] == "hero"
    assert (meta["width"], meta["height"]) == (40, 30)
    assert store.get("hero") == path.read_bytes()


def test_put_from_base64():
    store = refstore.ReferenceStore()
    b64 = base64.b64encode(_png_bytes()).decode("ascii")
    meta = store.put("inline", b64)
    assert meta["width"] == 40
    assert store.get("inline")


def test_get_unknown_id_raises_with_the_known_ids():
    store = refstore.ReferenceStore()
    store.put("a", base64.b64encode(_png_bytes()).decode("ascii"))
    with pytest.raises(KeyError) as exc:
        store.get("missing")
    assert "a" in str(exc.value)


def test_put_rejects_a_non_image():
    store = refstore.ReferenceStore()
    with pytest.raises(ValueError):
        store.put("junk", base64.b64encode(b"not an image").decode("ascii"))


def test_put_overwrites_the_same_id():
    store = refstore.ReferenceStore()
    store.put("x", base64.b64encode(_png_bytes((1, 1, 1))).decode("ascii"))
    store.put("x", base64.b64encode(_png_bytes((2, 2, 2), (8, 8))).decode("ascii"))
    assert store.list_ids() == ["x"]
    im = PILImage.open(io.BytesIO(store.get("x")))
    assert im.size == (8, 8)
