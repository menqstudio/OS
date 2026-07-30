"""Offline tests for the isolated receipt-signer core (rev-30 §7 / §4.9).

No sockets, no keys, no OS trust chain: the artifact store is a plain dict, the
clock is a fake, and Ed25519 signing + attestation verification are stubs. These
exercise the normative signer behaviours:

  * a valid attested sign-request => a well-formed
    ``brops.governed-receipt-envelope.v1`` §4.9 envelope whose flat payload was
    RECOMPUTED by the signer (its store-derived ``*_sha256`` derived from the
    store bytes, its ``request_sha256`` recomputed, not copied from the caller);
  * an unattested / malformed / oversize / out-of-scope request => a typed
    fail-closed refusal (never a partial success);
  * the signer NEVER signs the caller-supplied output bytes directly — the bytes
    handed to ``sign_fn`` are exactly ``JCS(recomputed_payload)`` and the raw
    artifact bytes never appear in the signed message; an inline ``output_bytes``
    field is rejected as an unknown field.
"""

import hashlib
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from isolated_signer import (  # noqa: E402
    ATTESTATION_PROTOCOL,
    ENVELOPE_ARTIFACT_TYPE,
    ENVELOPE_INTEGER_KEYS,
    ENVELOPE_PAYLOAD_FIELDS,
    REQUEST_PROTOCOL,
    REFUSAL_ARTIFACT_TYPE,
    REASON_ATTESTATION_INVALID,
    REASON_CONTAINMENT_MISSING,
    REASON_HANDLE_MISSING,
    REASON_IDENTITY_DENIED,
    REASON_MALFORMED,
    REASON_NOT_COMPLETED,
    REASON_OVERSIZE,
    REASON_TIMESTAMP_INVALID,
    SIGN_REQUEST_PROTOCOL,
    ArtifactStore,
    IsolatedSigner,
    SignerConfig,
    _canonical_bytes,
    _jcs_bytes,
    _sha256_hex,
    validate_sign_request,
)

RECEIPT_KEY_ID = "receipt-key-2026-07"
SUP_KEY_ID = "sup-attest-key-2026-07"
RECEIPT_PRIV_HANDLE = "kms://receipt/2026-07"  # OPAQUE — no key bytes inline.
SUP_PUB_HANDLE = "kms://sup-attest/2026-07"

NOW_MS = 1_700_000_000_000

# A distinctive marker so a test can prove the raw output bytes are never signed.
OUTPUT_MARKER = b"TOP-SECRET-OUTPUT-PLAINTEXT-MARKER-\x00-do-not-sign"


def _h(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _build_store():
    """Content-addressed store holding each artifact; return (store, handles)."""
    artifacts = {
        "policy_bundle_handle": b"policy-bundle-bytes",
        "generation_config_handle": b'{"temperature":0}',
        "system_handle": b"you are a governed agent",
        "history_handle": b'[{"content":"hi","role":"user"}]',
        "output_handle": OUTPUT_MARKER,  # the sensitive reply bytes
        "containment_evidence_handle": b'{"containment":"ok"}',
        # Protected-chain artifacts the signer deep-verifies (must resolve).
        "record_handle": b'{"terminal_record":"COMPLETED"}',
        "lease_handle": b'{"lease":"signed-lease-payload"}',
        "execution_receipt_handle": b'{"execution_receipt":"ok"}',
    }
    store = ArtifactStore()
    handles = {}
    for field, data in artifacts.items():
        handles[field] = store.put(data)
    return store, handles


def _evidence(handles):
    return {
        "run_id": "run-abc",
        "execution_attempt_id": "attempt-1",
        "task_id": "task-1",
        "request_nonce": "550e8400-e29b-41d4-a716-446655440000",
        "receipt_id": "receipt-777",
        "decision": "completed",
        "workspace_id": "ws-1",
        "install_id": "install-xyz",
        "supervisor_id": "sup-1",
        "executor_id": "exec-1",
        "builder_id": "builder-1",
        "policy_id": "policy-1",
        "policy_version": "1.0.0",
        "policy_bundle_handle": handles["policy_bundle_handle"],
        "generation_config_handle": handles["generation_config_handle"],
        "system_handle": handles["system_handle"],
        "history_handle": handles["history_handle"],
        "output_handle": handles["output_handle"],
        "containment_evidence_handle": handles["containment_evidence_handle"],
        "record_handle": handles["record_handle"],
        "lease_handle": handles["lease_handle"],
        "execution_receipt_handle": handles["execution_receipt_handle"],
        "evidence_final_event_hash": "a" * 64,
        "requested_at": NOW_MS - 5_000,
        "challenge_accepted_at_ms": NOW_MS - 3_000,
        "completed_at": NOW_MS - 1_000,
        "evidence_event_count": 3,
        "evidence_last_sequence": 12,
        "evidence_head_sequence": 4,
    }


def _expected_request_sha256(handles):
    """The canonical request digest the broker (receipt.rs) recomputes."""
    request_envelope = {
        "protocol": REQUEST_PROTOCOL,
        "workspace_id": "ws-1",
        "install_id": "install-xyz",
        "request_nonce": "550e8400-e29b-41d4-a716-446655440000",
        "system_sha256": _h(b"you are a governed agent"),
        "history_sha256": _h(b'[{"content":"hi","role":"user"}]'),
        "generation_config_sha256": _h(b'{"temperature":0}'),
        "requested_at": str(NOW_MS - 5_000),
    }
    return _sha256_hex(_jcs_bytes(request_envelope))


def _request(evidence, sig="GOOD-SIG", supervisor_key_id=SUP_KEY_ID):
    return {
        "protocol": SIGN_REQUEST_PROTOCOL,
        "attestation": {
            "attestation_protocol": ATTESTATION_PROTOCOL,
            "supervisor_key_id": supervisor_key_id,
            "sig": sig,
        },
        "evidence": evidence,
    }


class _Recorder:
    """Captures exactly what bytes get handed to sign_fn."""

    def __init__(self):
        self.signed_messages = []
        self.signed_handles = []

    def sign_fn(self, private_key_handle, message_bytes):
        self.signed_handles.append(private_key_handle)
        self.signed_messages.append(message_bytes)
        return "SIG:" + hashlib.sha256(message_bytes).hexdigest()


def _accepting_verifier(key_handle, message_bytes, sig_b64):
    return sig_b64 == "GOOD-SIG"


def _make_signer(sign_fn=None, verify=_accepting_verifier, clock=None):
    store, handles = _build_store()
    config = SignerConfig(
        receipt_key_id=RECEIPT_KEY_ID,
        receipt_private_key_handle=RECEIPT_PRIV_HANDLE,
        supervisor_attestation_key_id=SUP_KEY_ID,
        supervisor_attestation_key_handle=SUP_PUB_HANDLE,
        allowed_executor_ids={"exec-1"},
        allowed_builder_ids={"builder-1"},
        allowed_supervisor_ids={"sup-1"},
    )
    recorder = _Recorder()
    signer = IsolatedSigner(
        config=config,
        store=store,
        sign_fn=sign_fn or recorder.sign_fn,
        verify_attestation=verify,
        clock_ms=clock or (lambda: NOW_MS),
    )
    return signer, store, handles, recorder


class ValidSignTest(unittest.TestCase):
    def test_valid_request_returns_well_formed_envelope(self):
        signer, store, handles, _ = _make_signer()
        result = signer.sign_result(_request(_evidence(handles)))

        self.assertEqual(result["artifact_type"], ENVELOPE_ARTIFACT_TYPE)
        self.assertEqual(result["status"], "signed")
        self.assertTrue(result["signature_b64"])

        payload = result["payload"]
        # payload is EXACTLY the 23-key §4.9 flat envelope, nothing more.
        self.assertEqual(set(payload.keys()), set(ENVELOPE_PAYLOAD_FIELDS))
        self.assertEqual(len(payload), 23)
        # frozen §4.9 identity, with key_id INSIDE the signed payload.
        self.assertEqual(payload["artifact_type"], ENVELOPE_ARTIFACT_TYPE)
        self.assertEqual(payload["key_id"], RECEIPT_KEY_ID)
        self.assertEqual(payload["supervisor_attestation_key_id"], SUP_KEY_ID)
        # forensic binding: attestation_evidence_sha256 is over JCS(evidence).
        self.assertEqual(
            payload["attestation_evidence_sha256"],
            _h(_canonical_bytes(_evidence(handles))),
        )
        # the 6 integer fields are bare ints (not stringified).
        for key in ENVELOPE_INTEGER_KEYS:
            self.assertIsInstance(payload[key], int)
            self.assertNotIsInstance(payload[key], bool)
        self.assertEqual(payload["completed_at_ms"], NOW_MS - 1_000)
        self.assertEqual(payload["challenge_accepted_at_ms"], NOW_MS - 3_000)
        self.assertEqual(payload["output_bytes"], len(OUTPUT_MARKER))

    def test_store_derived_fields_are_recomputed_not_caller_supplied(self):
        signer, store, handles, _ = _make_signer()
        result = signer.sign_result(_request(_evidence(handles)))
        payload = result["payload"]
        # output_sha256/output_bytes DERIVED from the exact store bytes.
        self.assertEqual(payload["output_sha256"], _h(OUTPUT_MARKER))
        self.assertEqual(payload["output_sha256"], handles["output_handle"])
        self.assertEqual(payload["output_bytes"], len(OUTPUT_MARKER))
        # request_sha256 RECOMPUTED via the receipt.rs request-envelope formula.
        self.assertEqual(payload["request_sha256"], _expected_request_sha256(handles))
        # protected-chain handles carried verbatim.
        self.assertEqual(payload["record_handle"], handles["record_handle"])
        self.assertEqual(payload["lease_handle"], handles["lease_handle"])
        self.assertEqual(
            payload["execution_receipt_handle"], handles["execution_receipt_handle"]
        )

    def test_inline_sha256_claim_is_rejected(self):
        # A caller cannot smuggle a chosen output_sha256 — unknown field.
        signer, store, handles, _ = _make_signer()
        ev = _evidence(handles)
        ev["output_sha256"] = "f" * 64  # attacker-chosen hash claim
        result = signer.sign_result(_request(ev))
        self.assertEqual(result["artifact_type"], REFUSAL_ARTIFACT_TYPE)
        self.assertEqual(result["reason"], REASON_MALFORMED)


class NeverSignsCallerBytesTest(unittest.TestCase):
    def test_signer_signs_only_recomputed_payload_never_output_bytes(self):
        signer, store, handles, recorder = _make_signer()
        result = signer.sign_result(_request(_evidence(handles)))
        self.assertEqual(result["status"], "signed")

        # sign_fn was called exactly once, with the receipt private key handle.
        self.assertEqual(len(recorder.signed_messages), 1)
        self.assertEqual(recorder.signed_handles, [RECEIPT_PRIV_HANDLE])

        signed = recorder.signed_messages[0]
        # The signed bytes are EXACTLY JCS(recomputed payload) — the same
        # encoding the Rust broker reconstructs.
        self.assertEqual(signed, _jcs_bytes(result["payload"]))
        # The raw sensitive output bytes NEVER appear in the signed message —
        # only their sha256 does. This is not a sign(arbitrary_bytes) oracle.
        self.assertNotIn(OUTPUT_MARKER, signed)
        self.assertNotIn(b"do-not-sign", signed)

    def test_output_bytes_inline_field_is_refused(self):
        # Smuggling raw bytes inline is rejected before anything is signed.
        signer, store, handles, recorder = _make_signer()
        ev = _evidence(handles)
        ev["output_bytes"] = OUTPUT_MARKER.decode("latin-1")
        result = signer.sign_result(_request(ev))
        self.assertEqual(result["artifact_type"], REFUSAL_ARTIFACT_TYPE)
        self.assertEqual(result["reason"], REASON_MALFORMED)
        self.assertEqual(recorder.signed_messages, [])  # nothing signed


class RefusalTest(unittest.TestCase):
    def test_bad_attestation_is_refused(self):
        signer, store, handles, recorder = _make_signer()
        result = signer.sign_result(_request(_evidence(handles), sig="FORGED"))
        self.assertEqual(result["reason"], REASON_ATTESTATION_INVALID)
        self.assertEqual(recorder.signed_messages, [])

    def test_wrong_supervisor_key_is_refused(self):
        signer, store, handles, recorder = _make_signer()
        req = _request(_evidence(handles), supervisor_key_id="attacker-key")
        result = signer.sign_result(req)
        self.assertEqual(result["reason"], REASON_ATTESTATION_INVALID)
        self.assertEqual(recorder.signed_messages, [])

    def test_verifier_that_raises_is_treated_as_invalid(self):
        def _boom(key_handle, message_bytes, sig_b64):
            raise RuntimeError("verifier exploded")

        signer, store, handles, recorder = _make_signer(verify=_boom)
        result = signer.sign_result(_request(_evidence(handles)))
        self.assertEqual(result["reason"], REASON_ATTESTATION_INVALID)
        self.assertEqual(recorder.signed_messages, [])

    def test_non_completed_decision_is_refused(self):
        signer, store, handles, _ = _make_signer()
        ev = _evidence(handles)
        ev["decision"] = "blocked"
        self.assertEqual(
            signer.sign_result(_request(ev))["reason"], REASON_NOT_COMPLETED
        )

    def test_unknown_identity_is_refused(self):
        signer, store, handles, _ = _make_signer()
        ev = _evidence(handles)
        ev["executor_id"] = "rogue-executor"
        self.assertEqual(
            signer.sign_result(_request(ev))["reason"], REASON_IDENTITY_DENIED
        )

    def test_future_completed_at_is_refused(self):
        signer, store, handles, _ = _make_signer()
        ev = _evidence(handles)
        ev["completed_at"] = NOW_MS + 10 * 60_000  # far future
        self.assertEqual(
            signer.sign_result(_request(ev))["reason"], REASON_TIMESTAMP_INVALID
        )

    def test_missing_handle_is_refused(self):
        signer, store, handles, _ = _make_signer()
        ev = _evidence(handles)
        # A well-formed but absent handle (never stored).
        ev["system_handle"] = "a" * 64
        self.assertEqual(
            signer.sign_result(_request(ev))["reason"], REASON_HANDLE_MISSING
        )

    def test_missing_chain_handle_is_refused(self):
        # A protected-chain handle that does not resolve in the store => the
        # signer refuses to mint an envelope naming an unseen record.
        signer, store, handles, _ = _make_signer()
        ev = _evidence(handles)
        ev["execution_receipt_handle"] = "c" * 64
        self.assertEqual(
            signer.sign_result(_request(ev))["reason"], REASON_HANDLE_MISSING
        )

    def test_missing_containment_has_specific_reason(self):
        signer, store, handles, _ = _make_signer()
        ev = _evidence(handles)
        ev["containment_evidence_handle"] = "b" * 64
        self.assertEqual(
            signer.sign_result(_request(ev))["reason"], REASON_CONTAINMENT_MISSING
        )

    def test_malformed_shapes_are_refused(self):
        signer, store, handles, _ = _make_signer()
        for bad in (
            None,
            [],
            {"protocol": "wrong", "attestation": {}, "evidence": {}},
            {"protocol": SIGN_REQUEST_PROTOCOL, "evidence": {}},  # missing attestation
            {"protocol": SIGN_REQUEST_PROTOCOL, "attestation": {}, "evidence": {},
             "extra": 1},  # unknown top-level field
        ):
            result = signer.sign_result(bad)
            self.assertEqual(result["artifact_type"], REFUSAL_ARTIFACT_TYPE)
            self.assertEqual(result["reason"], REASON_MALFORMED)

    def test_non_integer_evidence_head_count_is_refused(self):
        # The evidence-head counters must be bare positive integers.
        signer, store, handles, _ = _make_signer()
        ev = _evidence(handles)
        ev["evidence_event_count"] = "3"  # stringified => malformed
        self.assertEqual(
            signer.sign_result(_request(ev))["reason"], REASON_MALFORMED
        )
        ev = _evidence(handles)
        ev["evidence_head_sequence"] = 0  # must be >= 1
        self.assertEqual(
            signer.sign_result(_request(ev))["reason"], REASON_MALFORMED
        )

    def test_oversize_request_is_refused(self):
        signer, store, handles, _ = _make_signer()
        ev = _evidence(handles)
        # Blow the request past the whole-frame cap via an unknown giant field;
        # the size gate fires before/independent of shape validation.
        ev["run_id"] = "x" * (300 * 1024)
        result = signer.sign_result(_request(ev))
        self.assertEqual(result["artifact_type"], REFUSAL_ARTIFACT_TYPE)
        self.assertEqual(result["reason"], REASON_OVERSIZE)

    def test_non_hex_handle_is_refused(self):
        signer, store, handles, _ = _make_signer()
        ev = _evidence(handles)
        ev["output_handle"] = "not-a-hex-digest"
        self.assertEqual(
            signer.sign_result(_request(ev))["reason"], REASON_MALFORMED
        )


class StoreTest(unittest.TestCase):
    def test_store_refuses_lying_handle(self):
        store = ArtifactStore()
        with self.assertRaises(Exception):
            store.put(b"real-bytes", handle="0" * 64)

    def test_validate_sign_request_returns_normalized_pair(self):
        _, handles = _build_store()
        attestation, evidence = validate_sign_request(_request(_evidence(handles)))
        self.assertEqual(attestation["supervisor_key_id"], SUP_KEY_ID)
        self.assertEqual(evidence["decision"], "completed")


if __name__ == "__main__":
    unittest.main()
