"""Offline tests for the AF_UNIX isolated-signer server wiring (rev-30 §7 / §4.9).

No real socket, no keys, no OS trust chain: a ``FakeConn`` supplies the peer uid
and a byte buffer, the artifact store is a plain dict, the clock is fixed, and
Ed25519 signing + attestation verification are stubs. These mirror
``test_challenge_authority_server`` and exercise the normative wiring behaviours:

  * a non-broker peer is DENIED before any frame is read (renderer/sidecar);
  * an oversize / short / truncated length-prefixed frame is refused
    (fail-closed on bounds);
  * a valid ``sign-result`` frame dispatches into the REAL ``IsolatedSigner``,
    which recompute-then-signs, and the reply carries the flat 23-key §4.9
    envelope + a signature that Ed25519-verifies over ``JCS(payload)``;
  * an unknown op is rejected;
  * a signer refusal (bad attestation) surfaces as a fail-closed typed error
    reply carrying the fixed reason, never a partial success.

The server is exercised through injected-socket/mock seams only — no real Linux
socket is opened.
"""

import base64
import hashlib
import json
import pathlib
import sys
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.exceptions import InvalidSignature

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from isolated_signer import (  # noqa: E402
    ATTESTATION_PROTOCOL,
    ENVELOPE_ARTIFACT_TYPE,
    REFUSAL_ARTIFACT_TYPE,
    REASON_ATTESTATION_INVALID,
    SIGN_REQUEST_PROTOCOL,
    ArtifactStore,
    IsolatedSigner,
    SignerConfig,
)
from isolated_signer_server import (  # noqa: E402
    LENGTH_PREFIX_BYTES,
    MAX_FRAME_BYTES,
    OP_SIGN_RESULT,
    FrameError,
    dispatch,
    handle_connection,
    peer_is_broker,
    read_frame,
    serve_forever,
)

BROKER_UID = 4001
RENDERER_UID = 1000
SIDECAR_UID = 4004

RECEIPT_KEY_ID = "iso-signer-2026-07"
SUP_KEY_ID = "sup-attest-2026-07"
NOW_MS = 1_700_000_000_000
OUTPUT = b"the exact governed reply bytes"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _b64url_nopad(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _frame(obj) -> bytes:
    body = json.dumps(obj).encode("utf-8")
    return len(body).to_bytes(LENGTH_PREFIX_BYTES, "big") + body


def _build_store():
    artifacts = {
        "policy_bundle_handle": b"policy-bundle-bytes",
        "generation_config_handle": b'{"temperature":0,"top_p":1}',
        "system_handle": b"you are Bro, a governed conductor",
        "history_handle": b'[{"role":"user","content":"hello"}]',
        "output_handle": OUTPUT,
        "containment_evidence_handle": b'{"containment":"verified"}',
        "record_handle": b'{"terminal_record":"COMPLETED"}',
        "lease_handle": b'{"lease":"signed-lease"}',
        "execution_receipt_handle": b'{"execution_receipt":"ok"}',
    }
    store = ArtifactStore()
    handles = {f: store.put(d) for f, d in artifacts.items()}
    return store, handles


def _evidence(handles):
    return {
        "run_id": "run-9",
        "execution_attempt_id": "attempt-2",
        "task_id": "task-42",
        "request_nonce": "nonce-abc-123",
        "receipt_id": "receipt-xyz",
        "decision": "completed",
        "workspace_id": "ws-7",
        "install_id": "install-7",
        "supervisor_id": "sup-1",
        "executor_id": "exec-1",
        "builder_id": "builder-1",
        "policy_id": "policy-9",
        "policy_version": "2.1.0",
        "policy_bundle_handle": handles["policy_bundle_handle"],
        "generation_config_handle": handles["generation_config_handle"],
        "system_handle": handles["system_handle"],
        "history_handle": handles["history_handle"],
        "output_handle": handles["output_handle"],
        "containment_evidence_handle": handles["containment_evidence_handle"],
        "record_handle": handles["record_handle"],
        "lease_handle": handles["lease_handle"],
        "execution_receipt_handle": handles["execution_receipt_handle"],
        "evidence_final_event_hash": "d" * 64,
        "requested_at": NOW_MS - 8_000,
        "challenge_accepted_at_ms": NOW_MS - 6_000,
        "completed_at": NOW_MS - 2_000,
        "evidence_event_count": 5,
        "evidence_last_sequence": 17,
        "evidence_head_sequence": 2,
    }


def _sign_request(evidence, sig="GOOD-SIG", supervisor_key_id=SUP_KEY_ID):
    return {
        "protocol": SIGN_REQUEST_PROTOCOL,
        "attestation": {
            "attestation_protocol": ATTESTATION_PROTOCOL,
            "supervisor_key_id": supervisor_key_id,
            "sig": sig,
        },
        "evidence": evidence,
    }


class FakeConn:
    """A socket stand-in: fixed peer_uid, an inbound byte buffer, and a capture
    of everything written back. No OS involved."""

    def __init__(self, peer_uid, inbound: bytes = b""):
        self.peer_uid = peer_uid
        self._in = inbound
        self.out = b""
        self.closed = False

    def recv_exactly(self, n: int) -> bytes:
        chunk = self._in[:n]
        self._in = self._in[n:]
        return chunk

    def send_all(self, data: bytes) -> None:
        self.out += data

    def close(self) -> None:
        self.closed = True

    def decoded_reply(self):
        length = int.from_bytes(self.out[:LENGTH_PREFIX_BYTES], "big")
        body = self.out[LENGTH_PREFIX_BYTES:LENGTH_PREFIX_BYTES + length]
        return json.loads(body.decode("utf-8"))


def _make_signer(verify=None):
    """A REAL IsolatedSigner over a real Ed25519 sign_fn (the server imports and
    calls it; it does not reimplement signing). Returns (signer, pub, handles)."""
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()

    def sign_fn(private_key_handle, message_bytes):
        assert private_key_handle is priv  # opaque handle == the key
        return _b64url_nopad(priv.sign(message_bytes))

    store, handles = _build_store()
    config = SignerConfig(
        receipt_key_id=RECEIPT_KEY_ID,
        receipt_private_key_handle=priv,
        supervisor_attestation_key_id=SUP_KEY_ID,
        supervisor_attestation_key_handle=object(),
        allowed_executor_ids={"exec-1"},
        allowed_builder_ids={"builder-1"},
        allowed_supervisor_ids={"sup-1"},
    )
    signer = IsolatedSigner(
        config=config,
        store=store,
        sign_fn=sign_fn,
        verify_attestation=verify or (lambda h, m, s: s == "GOOD-SIG"),
        clock_ms=lambda: NOW_MS,
    )
    return signer, pub, handles


class PeerDenyTests(unittest.TestCase):
    def test_non_broker_peer_denied_before_any_frame(self):
        signer, _pub, handles = _make_signer()
        # A valid sign-result frame is queued, but the renderer peer must be
        # refused BEFORE it is ever read.
        conn = FakeConn(
            RENDERER_UID,
            inbound=_frame(
                {"op": OP_SIGN_RESULT, "sign_request": _sign_request(_evidence(handles))}
            ),
        )
        reply = handle_connection(conn, BROKER_UID, signer)
        self.assertFalse(reply["ok"])
        self.assertIn("peer", reply["error"])
        # Nothing was ever read from the connection: the frame is untouched.
        self.assertEqual(conn._in, _frame(  # type: ignore[attr-defined]
            {"op": OP_SIGN_RESULT, "sign_request": _sign_request(_evidence(handles))}
        ))
        self.assertEqual(conn.decoded_reply(), reply)

    def test_sidecar_peer_denied(self):
        signer, _pub, handles = _make_signer()
        conn = FakeConn(
            SIDECAR_UID,
            inbound=_frame(
                {"op": OP_SIGN_RESULT, "sign_request": _sign_request(_evidence(handles))}
            ),
        )
        reply = handle_connection(conn, BROKER_UID, signer)
        self.assertFalse(reply["ok"])

    def test_peer_is_broker_rejects_bool_and_non_int(self):
        self.assertFalse(peer_is_broker(True, BROKER_UID))
        self.assertFalse(peer_is_broker(BROKER_UID, True))
        self.assertFalse(peer_is_broker("4001", BROKER_UID))
        self.assertFalse(peer_is_broker(None, BROKER_UID))
        self.assertTrue(peer_is_broker(BROKER_UID, BROKER_UID))


class FrameBoundTests(unittest.TestCase):
    def test_oversize_frame_refused(self):
        # Declare a length past the hard bound; the body is never even read.
        header = (MAX_FRAME_BYTES + 1).to_bytes(LENGTH_PREFIX_BYTES, "big")
        signer, _pub, _handles = _make_signer()
        conn = FakeConn(BROKER_UID, inbound=header)
        reply = handle_connection(conn, BROKER_UID, signer)
        self.assertFalse(reply["ok"])
        self.assertIn("exceeds", reply["error"])

    def test_short_header_refused(self):
        signer, _pub, _handles = _make_signer()
        conn = FakeConn(BROKER_UID, inbound=b"\x00\x01")  # only 2 of 4 bytes
        reply = handle_connection(conn, BROKER_UID, signer)
        self.assertFalse(reply["ok"])

    def test_truncated_body_refused(self):
        signer, _pub, _handles = _make_signer()
        # Header promises 100 bytes; only 3 are present.
        conn = FakeConn(
            BROKER_UID, inbound=(100).to_bytes(LENGTH_PREFIX_BYTES, "big") + b"abc"
        )
        reply = handle_connection(conn, BROKER_UID, signer)
        self.assertFalse(reply["ok"])

    def test_read_frame_rejects_zero_length(self):
        conn = FakeConn(BROKER_UID, inbound=(0).to_bytes(LENGTH_PREFIX_BYTES, "big"))
        with self.assertRaises(FrameError):
            read_frame(conn)


class DispatchTests(unittest.TestCase):
    def test_valid_sign_result_returns_signed_envelope(self):
        signer, pub, handles = _make_signer()
        conn = FakeConn(
            BROKER_UID,
            inbound=_frame(
                {"op": OP_SIGN_RESULT, "sign_request": _sign_request(_evidence(handles))}
            ),
        )
        reply = handle_connection(conn, BROKER_UID, signer)
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["op"], OP_SIGN_RESULT)
        self.assertEqual(reply["artifact_type"], ENVELOPE_ARTIFACT_TYPE)

        payload = reply["payload"]
        # The flat 23-key §4.9 envelope, produced by the REAL signer.
        self.assertEqual(len(payload), 23)
        self.assertEqual(payload["key_id"], RECEIPT_KEY_ID)
        self.assertEqual(payload["supervisor_attestation_key_id"], SUP_KEY_ID)
        # Store-derived, recomputed by the signer (not caller-supplied).
        self.assertEqual(payload["output_sha256"], _sha(OUTPUT))
        self.assertEqual(payload["output_bytes"], len(OUTPUT))

        # The returned signature Ed25519-verifies over JCS(payload) — the exact
        # bytes the Rust broker reconstructs — under the signer's public key.
        jcs = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        sig_b64 = reply["signature"]
        raw = base64.urlsafe_b64decode(sig_b64 + "=" * (-len(sig_b64) % 4))
        self.assertEqual(len(raw), 64)  # Ed25519 signature size
        pub.verify(raw, jcs)  # raises InvalidSignature on failure

        # Tampering any signed field breaks verification (defence proof).
        tampered = dict(payload)
        tampered["completed_at_ms"] = payload["completed_at_ms"] + 1
        tampered_jcs = json.dumps(
            tampered, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        with self.assertRaises(InvalidSignature):
            pub.verify(raw, tampered_jcs)

        self.assertEqual(conn.decoded_reply(), reply)

    def test_dispatch_passes_verified_inputs_straight_to_signer(self):
        # The op is a thin wrapper: the nested sign_request reaches the signer
        # verbatim and yields a signed envelope, never a re-signed oracle blob.
        signer, _pub, handles = _make_signer()
        reply = dispatch(
            {"op": OP_SIGN_RESULT, "sign_request": _sign_request(_evidence(handles))},
            signer,
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["payload"]["run_id"], "run-9")
        self.assertTrue(reply["signature"])

    def test_unknown_op_rejected(self):
        signer, _pub, _handles = _make_signer()
        conn = FakeConn(BROKER_UID, inbound=_frame({"op": "sign-anything"}))
        reply = handle_connection(conn, BROKER_UID, signer)
        self.assertFalse(reply["ok"])
        self.assertIn("unknown op", reply["error"])

    def test_missing_op_rejected(self):
        signer, _pub, handles = _make_signer()
        conn = FakeConn(
            BROKER_UID,
            inbound=_frame({"sign_request": _sign_request(_evidence(handles))}),
        )
        reply = handle_connection(conn, BROKER_UID, signer)
        self.assertFalse(reply["ok"])


class SignerRefusalTests(unittest.TestCase):
    def test_bad_attestation_surfaces_typed_refusal(self):
        signer, _pub, handles = _make_signer()
        conn = FakeConn(
            BROKER_UID,
            inbound=_frame(
                {
                    "op": OP_SIGN_RESULT,
                    "sign_request": _sign_request(_evidence(handles), sig="FORGED"),
                }
            ),
        )
        reply = handle_connection(conn, BROKER_UID, signer)
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["reason"], REASON_ATTESTATION_INVALID)
        self.assertEqual(reply["artifact_type"], REFUSAL_ARTIFACT_TYPE)
        # No signature/payload leaked on a refusal.
        self.assertNotIn("payload", reply)
        self.assertNotIn("signature", reply)

    def test_malformed_sign_request_surfaces_typed_refusal(self):
        # A structurally malformed sign_request is refused (typed) by the signer,
        # never crashes the wiring.
        signer, _pub, _handles = _make_signer()
        conn = FakeConn(
            BROKER_UID,
            inbound=_frame({"op": OP_SIGN_RESULT, "sign_request": {"protocol": "wrong"}}),
        )
        reply = handle_connection(conn, BROKER_UID, signer)
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["artifact_type"], REFUSAL_ARTIFACT_TYPE)
        self.assertIsNotNone(reply["reason"])


class ServeLoopTests(unittest.TestCase):
    def test_serve_forever_drives_injected_acceptor(self):
        signer, _pub, handles = _make_signer()
        conns = [
            FakeConn(
                BROKER_UID,
                inbound=_frame(
                    {
                        "op": OP_SIGN_RESULT,
                        "sign_request": _sign_request(_evidence(handles)),
                    }
                ),
            )
        ]
        served = list(conns)

        def accept_one():
            return conns.pop(0) if conns else None

        serve_forever(accept_one, BROKER_UID, signer)

        # The single connection was handled, replied to, and closed.
        self.assertTrue(served[0].closed)
        reply = served[0].decoded_reply()
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["artifact_type"], ENVELOPE_ARTIFACT_TYPE)


if __name__ == "__main__":
    unittest.main()
