"""Offline tests for the supervisor's §4.9 RUN-ATTESTATION (rev-30 §4.1/§4.9).

These prove the missing production piece end-to-end WITHOUT a socket or the OS
trust chain, using a REAL Ed25519 keypair (``cryptography``):

  * the supervisor builds the §4.9 evidence from its OWN trusted run facts and
    signs ``JCS(evidence)``; the isolated signer VERIFIES that attestation over
    the identical evidence bytes against the pinned attestation key and re-hashes
    them into ``attestation_evidence_sha256`` (byte-for-byte agreement);
  * a wrong ``supervisor_key_id`` is refused BEFORE the signature is even checked;
  * a tampered evidence field breaks the attestation signature;
  * the ``attest-run`` server op: happy path returns the attestation + the exact
    evidence JCS bytes; a non-broker peer is denied; malformed facts /
    missing-seam fail closed.

The signature is base64url(64B) — the exact ``sig`` encoding §4.1 specifies and
the Rust broker (governed_verification.rs) decodes with ``URL_SAFE_NO_PAD``.
"""

import base64
import hashlib
import json
import pathlib
import sys
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from governed_supervisor import (  # noqa: E402
    ATTESTATION_PROTOCOL,
    DECISION_COMPLETED,
    REFUSE_MALFORMED,
    Refusal,
    RunAttestation,
    SupervisorError,
    _canonical_bytes,
    build_run_attestation,
)
from governed_supervisor_server import (  # noqa: E402
    LENGTH_PREFIX_BYTES,
    OP_ATTEST_RUN,
    dispatch,
    handle_connection,
)
from isolated_signer import (  # noqa: E402
    ENVELOPE_ARTIFACT_TYPE,
    EVIDENCE_FIELDS,
    REASON_ATTESTATION_INVALID,
    REFUSAL_ARTIFACT_TYPE,
    ArtifactStore,
    IsolatedSigner,
    SignerConfig,
)

SUP_KEY_ID = "sup-attest-key-2026-07"
RECEIPT_KEY_ID = "receipt-key-2026-07"
NOW_MS = 1_700_000_000_000

BROKER_UID = 4001
RENDERER_UID = 1000


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _h(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _Ed25519:
    """A real Ed25519 keypair wired as the supervisor sign seam + the signer's
    injected verify_attestation seam."""

    def __init__(self):
        self._sk = Ed25519PrivateKey.generate()
        self._pk = self._sk.public_key()

    def sign_attestation(self, message: bytes) -> str:
        return _b64u(self._sk.sign(message))

    def verify_attestation(self, _key_handle, message: bytes, sig_b64: str) -> bool:
        try:
            self._pk.verify(_unb64u(sig_b64), message)
            return True
        except Exception:
            return False


def _build_store():
    """Content-addressed store; return (store, handles) so a full sign_result can
    resolve every handle the built evidence names."""
    artifacts = {
        "policy_bundle_handle": b"policy-bundle-bytes",
        "generation_config_handle": b'{"temperature":0}',
        "system_handle": b"you are a governed agent",
        "history_handle": b'[{"content":"hi","role":"user"}]',
        "output_handle": b"the exact governed reply bytes",
        "containment_evidence_handle": b'{"containment":"ok"}',
        "record_handle": b'{"terminal_record":"COMPLETED"}',
        "lease_handle": b'{"lease":"signed-lease-payload"}',
        "execution_receipt_handle": b'{"execution_receipt":"ok"}',
    }
    store = ArtifactStore()
    handles = {field: store.put(data) for field, data in artifacts.items()}
    return store, handles


def _facts(handles):
    """The supervisor's trusted run facts — the §4.9 evidence MINUS ``decision``
    (which the supervisor stamps itself)."""
    return {
        "run_id": "run-abc",
        "execution_attempt_id": "attempt-1",
        "task_id": "task-1",
        "request_nonce": "550e8400-e29b-41d4-a716-446655440000",
        "receipt_id": "receipt-777",
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


def _evidence_from_facts(facts):
    return {**facts, "decision": DECISION_COMPLETED}


def _make_signer(ed, store):
    config = SignerConfig(
        receipt_key_id=RECEIPT_KEY_ID,
        receipt_private_key_handle="kms://receipt",
        supervisor_attestation_key_id=SUP_KEY_ID,
        supervisor_attestation_key_handle="kms://sup-attest",
        allowed_executor_ids={"exec-1"},
        allowed_builder_ids={"builder-1"},
        allowed_supervisor_ids={"sup-1"},
    )
    return IsolatedSigner(
        config=config,
        store=store,
        sign_fn=lambda handle, msg: "SIG:" + _h(msg),
        verify_attestation=ed.verify_attestation,
        clock_ms=lambda: NOW_MS,
    )


class BuildRunAttestationTests(unittest.TestCase):
    def test_shape_and_message_bytes(self):
        ed = _Ed25519()
        _store, handles = _build_store()
        facts = _facts(handles)
        attn = build_run_attestation(
            facts, supervisor_key_id=SUP_KEY_ID, sign_attestation=ed.sign_attestation
        )
        self.assertIsInstance(attn, RunAttestation)
        # The 3-field attestation object the signer verifies.
        self.assertEqual(
            set(attn.attestation.keys()),
            {"attestation_protocol", "supervisor_key_id", "sig"},
        )
        self.assertEqual(attn.attestation["attestation_protocol"], ATTESTATION_PROTOCOL)
        self.assertEqual(attn.attestation["supervisor_key_id"], SUP_KEY_ID)
        # The supervisor STAMPS decision=completed and builds EXACTLY the signer's
        # evidence shape; the signed bytes are JCS(evidence).
        evidence = _evidence_from_facts(facts)
        self.assertEqual(set(evidence.keys()), set(EVIDENCE_FIELDS))
        self.assertEqual(attn.evidence_jcs, _canonical_bytes(evidence))
        self.assertEqual(attn.attestation_evidence_sha256, _h(attn.evidence_jcs))
        # The sig is a real detached Ed25519 over exactly those bytes.
        self.assertTrue(ed.verify_attestation(None, attn.evidence_jcs, attn.attestation["sig"]))

    def test_verifies_under_signer_verify_path_and_binds_the_digest(self):
        ed = _Ed25519()
        store, handles = _build_store()
        facts = _facts(handles)
        attn = build_run_attestation(
            facts, supervisor_key_id=SUP_KEY_ID, sign_attestation=ed.sign_attestation
        )
        signer = _make_signer(ed, store)
        # Full sign_result: the supervisor's attestation must verify inside the
        # signer's real verify path, and the envelope's attestation_evidence_sha256
        # must equal sha256(evidence_jcs) the supervisor produced.
        sign_request = {
            "protocol": "brops.sign-request.v1",
            "attestation": attn.attestation,
            "evidence": _evidence_from_facts(facts),
        }
        result = signer.sign_result(sign_request)
        self.assertEqual(result["artifact_type"], ENVELOPE_ARTIFACT_TYPE)
        self.assertEqual(result["status"], "signed")
        self.assertEqual(
            result["payload"]["attestation_evidence_sha256"],
            attn.attestation_evidence_sha256,
        )
        self.assertEqual(result["payload"]["supervisor_attestation_key_id"], SUP_KEY_ID)

    def test_wrong_supervisor_key_id_is_refused(self):
        ed = _Ed25519()
        store, handles = _build_store()
        facts = _facts(handles)
        # Attestation minted under a DIFFERENT key id than the signer pins.
        attn = build_run_attestation(
            facts, supervisor_key_id="attacker-key", sign_attestation=ed.sign_attestation
        )
        signer = _make_signer(ed, store)
        result = signer.sign_result(
            {
                "protocol": "brops.sign-request.v1",
                "attestation": attn.attestation,
                "evidence": _evidence_from_facts(facts),
            }
        )
        self.assertEqual(result["artifact_type"], REFUSAL_ARTIFACT_TYPE)
        self.assertEqual(result["reason"], REASON_ATTESTATION_INVALID)

    def test_tampered_evidence_field_breaks_verification(self):
        ed = _Ed25519()
        store, handles = _build_store()
        facts = _facts(handles)
        attn = build_run_attestation(
            facts, supervisor_key_id=SUP_KEY_ID, sign_attestation=ed.sign_attestation
        )
        signer = _make_signer(ed, store)
        # Feed the signer a tampered evidence (run_id flipped) with the ORIGINAL
        # attestation sig: the signer re-hashes different bytes -> sig invalid.
        tampered = _evidence_from_facts(facts)
        tampered["run_id"] = "run-EVIL"
        result = signer.sign_result(
            {
                "protocol": "brops.sign-request.v1",
                "attestation": attn.attestation,
                "evidence": tampered,
            }
        )
        self.assertEqual(result["artifact_type"], REFUSAL_ARTIFACT_TYPE)
        self.assertEqual(result["reason"], REASON_ATTESTATION_INVALID)

    def test_malformed_facts_fail_closed(self):
        ed = _Ed25519()
        _store, handles = _build_store()
        # A smuggled pre-built decision is an unknown field (no-oracle guard).
        bad = _facts(handles)
        bad["decision"] = "completed"
        self.assertIsInstance(
            build_run_attestation(
                bad, supervisor_key_id=SUP_KEY_ID, sign_attestation=ed.sign_attestation
            ),
            Refusal,
        )
        # A missing field also fails closed.
        missing = _facts(handles)
        del missing["run_id"]
        r = build_run_attestation(
            missing, supervisor_key_id=SUP_KEY_ID, sign_attestation=ed.sign_attestation
        )
        self.assertIsInstance(r, Refusal)
        self.assertEqual(r.reason, REFUSE_MALFORMED)
        # An uppercase (non-canonical) handle would sign different bytes -> refused.
        upper = _facts(handles)
        upper["system_handle"] = "A" * 64
        self.assertIsInstance(
            build_run_attestation(
                upper, supervisor_key_id=SUP_KEY_ID, sign_attestation=ed.sign_attestation
            ),
            Refusal,
        )

    def test_config_faults_raise(self):
        ed = _Ed25519()
        _store, handles = _build_store()
        facts = _facts(handles)
        with self.assertRaises(SupervisorError):
            build_run_attestation(facts, supervisor_key_id="", sign_attestation=ed.sign_attestation)
        with self.assertRaises(SupervisorError):
            build_run_attestation(facts, supervisor_key_id=SUP_KEY_ID, sign_attestation="nope")
        with self.assertRaises(SupervisorError):
            build_run_attestation(
                facts, supervisor_key_id=SUP_KEY_ID, sign_attestation=lambda m: ""
            )


# ---------------------------------------------------------------------------
# attest-run server op
# ---------------------------------------------------------------------------


class FakeConn:
    def __init__(self, peer_uid, inbound=b""):
        self.peer_uid = peer_uid
        self._in = inbound
        self.out = b""
        self.closed = False

    def recv_exactly(self, n):
        chunk = self._in[:n]
        self._in = self._in[n:]
        return chunk

    def send_all(self, data):
        self.out += data

    def close(self):
        self.closed = True

    def decoded_reply(self):
        length = int.from_bytes(self.out[:LENGTH_PREFIX_BYTES], "big")
        body = self.out[LENGTH_PREFIX_BYTES:LENGTH_PREFIX_BYTES + length]
        return json.loads(body.decode("utf-8"))


def _frame(obj):
    body = json.dumps(obj).encode("utf-8")
    return len(body).to_bytes(LENGTH_PREFIX_BYTES, "big") + body


def _noop_verify(_message, _sig):
    return True


def _noop_recompute(_payload):
    return "0" * 64


class AttestRunServerTests(unittest.TestCase):
    def _handle(self, conn, ed, key_id=SUP_KEY_ID):
        return handle_connection(
            conn,
            BROKER_UID,
            _fake_lease_config(),
            _noop_verify,
            _noop_recompute,
            lambda: NOW_MS,
            sign_attestation=(ed.sign_attestation if ed else None),
            supervisor_attestation_key_id=key_id,
        )

    def test_happy_path_returns_attestation_and_exact_evidence_jcs(self):
        ed = _Ed25519()
        _store, handles = _build_store()
        facts = _facts(handles)
        conn = FakeConn(BROKER_UID, inbound=_frame({"op": OP_ATTEST_RUN, "facts": facts}))
        reply = self._handle(conn, ed)
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["op"], OP_ATTEST_RUN)
        self.assertEqual(reply["attestation"]["attestation_protocol"], ATTESTATION_PROTOCOL)
        self.assertEqual(reply["attestation"]["supervisor_key_id"], SUP_KEY_ID)
        # evidence_jcs_b64 decodes to EXACTLY JCS(evidence) and its sig verifies.
        evidence_jcs = _unb64u(reply["evidence_jcs_b64"])
        self.assertEqual(evidence_jcs, _canonical_bytes(_evidence_from_facts(facts)))
        self.assertEqual(reply["attestation_evidence_sha256"], _h(evidence_jcs))
        self.assertTrue(
            ed.verify_attestation(None, evidence_jcs, reply["attestation"]["sig"])
        )
        self.assertEqual(conn.decoded_reply(), reply)

    def test_non_broker_peer_denied_before_any_frame(self):
        ed = _Ed25519()
        _store, handles = _build_store()
        conn = FakeConn(
            RENDERER_UID,
            inbound=_frame({"op": OP_ATTEST_RUN, "facts": _facts(handles)}),
        )
        reply = self._handle(conn, ed)
        self.assertFalse(reply["ok"])
        self.assertIn("peer", reply["error"])
        self.assertNotIn("attestation", reply)

    def test_malformed_facts_relayed_as_typed_refusal(self):
        ed = _Ed25519()
        _store, handles = _build_store()
        bad = _facts(handles)
        bad["evil"] = "smuggled"  # unknown field
        conn = FakeConn(BROKER_UID, inbound=_frame({"op": OP_ATTEST_RUN, "facts": bad}))
        reply = self._handle(conn, ed)
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["reason"], REFUSE_MALFORMED)
        self.assertNotIn("attestation", reply)

    def test_missing_facts_object_is_error(self):
        ed = _Ed25519()
        conn = FakeConn(BROKER_UID, inbound=_frame({"op": OP_ATTEST_RUN}))
        reply = self._handle(conn, ed)
        self.assertFalse(reply["ok"])
        self.assertIn("facts", reply["error"])

    def test_op_unavailable_without_seam_fails_closed(self):
        _store, handles = _build_store()
        conn = FakeConn(BROKER_UID, inbound=_frame({"op": OP_ATTEST_RUN, "facts": _facts(handles)}))
        # No sign_attestation seam injected -> supervisor-side config fault, never
        # a fabricated attestation.
        reply = self._handle(conn, ed=None)
        self.assertFalse(reply["ok"])
        self.assertNotIn("attestation", reply)

    def test_dispatch_direct_happy_path(self):
        ed = _Ed25519()
        _store, handles = _build_store()
        reply = dispatch(
            {"op": OP_ATTEST_RUN, "facts": _facts(handles)},
            _fake_lease_config(),
            _noop_verify,
            _noop_recompute,
            lambda: NOW_MS,
            sign_attestation=ed.sign_attestation,
            supervisor_attestation_key_id=SUP_KEY_ID,
        )
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["attestation"]["supervisor_key_id"], SUP_KEY_ID)


def _fake_lease_config():
    from governed_supervisor import SupervisorConfig

    return SupervisorConfig(
        launcher_executable_sha256="1" * 64,
        executor_executable_sha256="2" * 64,
        id_fn=lambda: "id-1",
    )


if __name__ == "__main__":
    unittest.main()
