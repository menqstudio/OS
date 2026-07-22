"""Cross-language JCS parity for the canonical request envelope (design §2, §10.1).

The Rust verifier (`brops-core::receipt::request_envelope_sha256`) and any Python
signer/adapter MUST produce **byte-identical** canonical bytes for the same envelope,
so a signature made on one side verifies on the other. For the receipt/request shape —
a flat map of ASCII-keyed string values — RFC 8785 (JCS) reduces to
`json.dumps(sort_keys=True, separators=(",", ":"))`. This test pins that Python's
canonical hash equals the value the matching Rust test asserts; if either side's
canonicalization drifts, both fail.
"""
import hashlib
import json
import unittest


def jcs(obj: dict) -> bytes:
    """RFC 8785 JCS for a flat ASCII-keyed string map: sorted keys, no whitespace,
    standard minimal JSON string escaping, UTF-8 bytes."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class JcsParityTests(unittest.TestCase):
    # Must equal the Rust test `receipt.rs::
    # request_envelope_jcs_matches_python_cross_language_parity`.
    _EXPECTED = "e6b54c0426e36d869d0451dbc68480c87f053bcea52f3fff52ba9cd10723f31b"

    def test_request_envelope_hash_matches_rust(self):
        env = {
            "protocol": "brops.request.v1",
            "workspace_id": "ws-1",
            "install_id": "install-1",
            "request_nonce": "nonce-xyz",
            "system_sha256": "55" * 32,
            "history_sha256": "66" * 32,
            "generation_config_sha256": "44" * 32,
            "requested_at": "1000",
        }
        self.assertEqual(hashlib.sha256(jcs(env)).hexdigest(), self._EXPECTED)

    def test_key_order_does_not_change_the_hash(self):
        # Canonicalization is order-independent (sorted keys) — same map, any input order.
        a = {"b": "2", "a": "1", "c": "3"}
        b = {"c": "3", "a": "1", "b": "2"}
        self.assertEqual(jcs(a), jcs(b))


if __name__ == "__main__":
    unittest.main()
