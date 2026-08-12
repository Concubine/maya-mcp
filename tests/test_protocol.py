"""Wire protocol tests: framing, length prefixes, token, malformed input.

Pure Python — no Maya required. The protocol module is the single source of
truth for framing, shared by the MCP server and the Maya plugin.
"""

import io
import json
import struct

import pytest

from maya_plugin import protocol


def reader_from(data: bytes, chunk: int = 65536):
    """Build a recv(n) callable over a byte string, returning at most `chunk` bytes."""
    buf = io.BytesIO(data)

    def recv(n: int) -> bytes:
        return buf.read(min(n, chunk))

    return recv


class TestFraming:
    def test_encode_frame_is_uint32_be_length_plus_utf8_json(self):
        frame = protocol.encode_frame({"v": 1, "id": "a1"})
        length = struct.unpack(">I", frame[:4])[0]
        body = frame[4:]
        assert length == len(body)
        assert json.loads(body.decode("utf-8")) == {"v": 1, "id": "a1"}

    def test_roundtrip(self):
        obj = {"v": 1, "id": "x", "cmd": "ping", "params": {"unicode": "אמת"}}
        frame = protocol.encode_frame(obj)
        assert protocol.read_frame(reader_from(frame)) == obj

    def test_read_frame_handles_partial_reads(self):
        obj = {"v": 1, "id": "y", "result": {"n": 42}}
        frame = protocol.encode_frame(obj)
        # recv returns one byte at a time — read_frame must loop, not assume full reads
        assert protocol.read_frame(reader_from(frame, chunk=1)) == obj

    def test_two_frames_back_to_back(self):
        a = protocol.encode_frame({"id": "1"})
        b = protocol.encode_frame({"id": "2"})
        recv = reader_from(a + b)
        assert protocol.read_frame(recv) == {"id": "1"}
        assert protocol.read_frame(recv) == {"id": "2"}

    def test_eof_at_frame_boundary_raises_connection_closed(self):
        with pytest.raises(protocol.ConnectionClosedError):
            protocol.read_frame(reader_from(b""))

    def test_eof_mid_frame_raises_protocol_error(self):
        frame = protocol.encode_frame({"id": "z"})
        with pytest.raises(protocol.ProtocolError):
            protocol.read_frame(reader_from(frame[: len(frame) - 3]))

    def test_oversized_frame_rejected_without_reading_body(self):
        header = struct.pack(">I", protocol.MAX_FRAME_BYTES + 1)
        with pytest.raises(protocol.ProtocolError, match="exceeds"):
            protocol.read_frame(reader_from(header))

    def test_non_json_body_raises_protocol_error(self):
        body = b"\xff\xfenot json"
        frame = struct.pack(">I", len(body)) + body
        with pytest.raises(protocol.ProtocolError):
            protocol.read_frame(reader_from(frame))

    def test_non_dict_body_raises_protocol_error(self):
        body = json.dumps([1, 2, 3]).encode()
        frame = struct.pack(">I", len(body)) + body
        with pytest.raises(protocol.ProtocolError):
            protocol.read_frame(reader_from(frame))


class TestMessages:
    def test_make_request_carries_version_id_cmd_params_timeout(self):
        req = protocol.make_request("capture_viewport", {"angles": ["front"]}, timeout_s=30)
        assert req["v"] == protocol.PROTOCOL_VERSION
        assert req["cmd"] == "capture_viewport"
        assert req["params"] == {"angles": ["front"]}
        assert req["timeout_s"] == 30
        assert isinstance(req["id"], str) and req["id"]

    def test_make_request_ids_are_unique(self):
        ids = {protocol.make_request("ping", {}, 5)["id"] for _ in range(100)}
        assert len(ids) == 100

    def test_make_request_token_only_present_when_set(self):
        assert "token" not in protocol.make_request("ping", {}, 5)
        assert protocol.make_request("ping", {}, 5, token="s3cret")["token"] == "s3cret"

    def test_make_ok(self):
        resp = protocol.make_ok("id1", {"tris": 3}, elapsed_ms=12)
        assert resp == {
            "v": protocol.PROTOCOL_VERSION,
            "id": "id1",
            "status": "ok",
            "result": {"tris": 3},
            "elapsed_ms": 12,
        }

    def test_make_error_includes_type_message_traceback_hint(self):
        resp = protocol.make_error(
            "id2", "RuntimeError", "boom", maya_traceback="Traceback ...", hint="try X"
        )
        assert resp["status"] == "error"
        assert resp["error"]["type"] == "RuntimeError"
        assert resp["error"]["message"] == "boom"
        assert resp["error"]["maya_traceback"] == "Traceback ..."
        assert resp["error"]["hint"] == "try X"

    def test_make_error_omits_absent_fields(self):
        resp = protocol.make_error("id3", "ValueError", "bad")
        assert "maya_traceback" not in resp["error"]
        assert "hint" not in resp["error"]


class TestTokenCheck:
    def test_no_expected_token_accepts_anything(self):
        assert protocol.token_ok({"cmd": "ping"}, expected=None)
        assert protocol.token_ok({"cmd": "ping", "token": "whatever"}, expected=None)

    def test_expected_token_requires_exact_match(self):
        assert protocol.token_ok({"token": "abc"}, expected="abc")
        assert not protocol.token_ok({"token": "wrong"}, expected="abc")
        assert not protocol.token_ok({}, expected="abc")

    def test_token_comparison_is_constant_time_api(self):
        # token_ok must use hmac.compare_digest — non-string tokens must not crash it
        assert not protocol.token_ok({"token": 123}, expected="abc")
