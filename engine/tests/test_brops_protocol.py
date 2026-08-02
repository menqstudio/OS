"""Wave 3b-1 — framed, bounded, strict IPC codec (design §1.9, §4; audit P1-4)."""

import io
import json
import pathlib
import struct
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

import brops_protocol as bp


class ProtocolTests(unittest.TestCase):
    def test_round_trip(self):
        obj = {"protocol": "brops.sign-request.v1", "n": 1, "s": "héllo"}
        buf = io.BytesIO(bp.encode_frame(obj))
        self.assertEqual(bp.read_frame(buf), obj)

    def test_length_prefix_is_u32_be(self):
        frame = bp.encode_frame({"a": 1})
        (declared,) = struct.unpack(">I", frame[:4])
        self.assertEqual(declared, len(frame) - 4)

    def test_oversize_declared_length_is_refused_before_reading_body(self):
        # A hostile prefix claiming > cap must fail without reading a huge body.
        header = struct.pack(">I", bp.MAX_FRAME_BYTES + 1)
        with self.assertRaises(bp.ProtocolError):
            bp.read_frame(io.BytesIO(header + b"x"))

    def test_oversize_body_is_refused_on_encode(self):
        with self.assertRaises(bp.ProtocolError):
            bp.encode_frame({"big": "x" * (bp.MAX_FRAME_BYTES + 1)})

    def test_duplicate_keys_are_rejected(self):
        raw = b'{"a":1,"a":2}'
        with self.assertRaises(bp.ProtocolError):
            bp.strict_loads(raw)

    def test_non_object_top_level_is_rejected(self):
        with self.assertRaises(bp.ProtocolError):
            bp.strict_loads(b"[1,2,3]")

    def test_short_read_is_fail_closed(self):
        header = struct.pack(">I", 100)
        with self.assertRaises(bp.ProtocolError):
            bp.read_frame(io.BytesIO(header + b"only-a-few"))

    def test_invalid_utf8_is_rejected(self):
        with self.assertRaises(bp.ProtocolError):
            bp.strict_loads(b"\xff\xfe not utf8")

    def test_base64url_validation(self):
        self.assertTrue(bp.is_base64url("abcABC-_09"))
        self.assertFalse(bp.is_base64url("has+slash/and=pad"))
        self.assertFalse(bp.is_base64url(123))

    def test_schema_validation_rejects_unknown_fields(self):
        schema = json.loads((ROOT / "contracts" / "brops-evidence-request.v1.schema.json").read_text("utf-8"))
        bp.validate({"protocol": "brops.evidence-request.v1", "run_id": "r", "execution_attempt_id": "a"}, schema)
        with self.assertRaises(bp.ProtocolError):
            bp.validate(
                {"protocol": "brops.evidence-request.v1", "run_id": "r",
                 "execution_attempt_id": "a", "evidence": {"forged": True}},
                schema,
            )


if __name__ == "__main__":
    unittest.main()
