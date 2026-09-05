"""maya-mcp wire protocol: version-tagged, length-prefixed JSON frames.

Frame = uint32 big-endian body length + UTF-8 JSON body.

This module is the single source of truth for framing. It is imported by both
the MCP server (src/maya_mcp/connection.py) and the Maya plugin, so it must
stay stdlib-only and compatible with Maya's embedded Python (3.9+).
"""

from __future__ import annotations

import hmac
import json
import struct
import uuid
from typing import Any, Callable, Dict, Optional

PROTOCOL_VERSION = 1

# Images travel base64-encoded inside result payloads; a 4K screenshot is a few MB.
# 64 MB is far above any legitimate frame and cheap insurance against a corrupt
# length prefix making us try to allocate gigabytes.
MAX_FRAME_BYTES = 64 * 1024 * 1024

_HEADER = struct.Struct(">I")


class ProtocolError(Exception):
    """Malformed frame: bad length, truncated body, or invalid JSON."""


class ConnectionClosedError(ProtocolError):
    """The peer closed the connection cleanly at a frame boundary."""


def encode_frame(obj: Dict[str, Any]) -> bytes:
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    if len(body) > MAX_FRAME_BYTES:
        raise ProtocolError(
            "frame of %d bytes exceeds MAX_FRAME_BYTES (%d)" % (len(body), MAX_FRAME_BYTES)
        )
    return _HEADER.pack(len(body)) + body


def _recv_exact(recv: Callable[[int], bytes], n: int, *, at_boundary: bool) -> bytes:
    """Read exactly n bytes from recv(n)->bytes, which may return short reads.

    An empty read means the peer closed the socket: at a frame boundary that is
    a clean close (ConnectionClosedError), mid-frame it is a truncation error.
    """
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = recv(remaining)
        if not chunk:
            if at_boundary and remaining == n:
                raise ConnectionClosedError("connection closed by peer")
            raise ProtocolError(
                "connection closed mid-frame (%d of %d bytes missing)" % (remaining, n)
            )
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(
    recv: Callable[[int], bytes], max_bytes: int = MAX_FRAME_BYTES
) -> Dict[str, Any]:
    """Read one frame via recv(n)->bytes (short reads allowed, b'' = EOF).

    max_bytes caps the accepted body size BEFORE any allocation. The default is
    the image-bearing response cap; the plugin passes a much smaller cap for
    inbound requests, which never legitimately carry images.
    """
    header = _recv_exact(recv, _HEADER.size, at_boundary=True)
    (length,) = _HEADER.unpack(header)
    if length > max_bytes:
        raise ProtocolError(
            "incoming frame of %d bytes exceeds the %d byte cap" % (length, max_bytes)
        )
    body = _recv_exact(recv, length, at_boundary=False) if length else b""
    try:
        obj = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ProtocolError("frame body is not valid UTF-8 JSON: %s" % exc) from exc
    if not isinstance(obj, dict):
        raise ProtocolError("frame body must be a JSON object, got %s" % type(obj).__name__)
    return obj


def make_request(
    cmd: str,
    params: Dict[str, Any],
    timeout_s: float,
    token: Optional[str] = None,
    req_id: Optional[str] = None,
    timeout_adjustable: Optional[bool] = None,
) -> Dict[str, Any]:
    req: Dict[str, Any] = {
        "v": PROTOCOL_VERSION,
        "id": req_id or uuid.uuid4().hex,
        "cmd": cmd,
        "params": params,
        "timeout_s": timeout_s,
    }
    if token is not None:
        req["token"] = token
    # Whether the CALLER had a timeout_s to raise (redmine #836): the
    # dispatcher's timeout hint used to advise "pass a larger timeout_s" for
    # every command, and the bake tools had none - an unfollowable hint on
    # the call that cost the kethran run an hour. Absent means no.
    if timeout_adjustable:
        req["timeout_adjustable"] = True
    return req


def make_ok(req_id: str, result: Dict[str, Any], elapsed_ms: int) -> Dict[str, Any]:
    return {
        "v": PROTOCOL_VERSION,
        "id": req_id,
        "status": "ok",
        "result": result,
        "elapsed_ms": elapsed_ms,
    }


def make_error(
    req_id: str,
    err_type: str,
    message: str,
    maya_traceback: Optional[str] = None,
    hint: Optional[str] = None,
    elapsed_ms: Optional[int] = None,
) -> Dict[str, Any]:
    error: Dict[str, Any] = {"type": err_type, "message": message}
    if maya_traceback is not None:
        error["maya_traceback"] = maya_traceback
    if hint is not None:
        error["hint"] = hint
    resp: Dict[str, Any] = {
        "v": PROTOCOL_VERSION,
        "id": req_id,
        "status": "error",
        "error": error,
    }
    if elapsed_ms is not None:
        resp["elapsed_ms"] = elapsed_ms
    return resp


def token_ok(frame: Dict[str, Any], expected: Optional[str]) -> bool:
    """True if the frame satisfies the token requirement (constant-time compare)."""
    if expected is None:
        return True
    supplied = frame.get("token")
    if not isinstance(supplied, str):
        return False
    return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))
