"""Offline tests for the supervisor's §4.9 RUN-ATTESTATION (rev-30 §4.1/§4.9, §5 v2).

These prove the production piece end-to-end WITHOUT a socket or the OS trust chain, using a
REAL Ed25519 keypair (``cryptography``) and a REAL durable ledger (in-memory SQLite over the
shared DDL):

  * the supervisor builds the §4.9 evidence from its OWN durable terminal run state and signs
    ``JCS(evidence)``; the isolated signer VERIFIES that attestation over the identical
    evidence bytes against the pinned attestation key and re-hashes them into
    ``attestation_evidence_sha256`` (byte-for-byte agreement);
  * a wrong ``supervisor_key_id`` is refused BEFORE the signature is even checked;
  * a tampered evidence field breaks the attestation signature;
  * the ``attest-run`` server op over a FULL governed lifecycle
    (accept-open → launch-gate → execution-started → complete-run → attest-run).

**F-01.** The old version of this file fed ``build_run_attestation`` a hand-built ``facts``
mapping, because that is what the endpoint accepted — which is precisely why the broker uid
could mint a signed receipt for a run that never happened. There is no such path any more:
the evidence comes from the ledger, and the tests below have to actually run a governed
lifecycle to obtain one.

The signature is base64url(64B) — the exact ``sig`` encoding §4.1 specifies and the Rust
broker (governed_verification.rs) decodes with ``URL_SAFE_NO_PAD``.
"""

import base64
import hashlib
import json
import pathlib
import sqlite3
import sys
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

import governed_supervisor_ledger as gsl  # noqa: E402
from governed_supervisor import (  # noqa: E402
    ATTESTATION_PROTOCOL,
    CHALLENGE_PROTOCOL,
    DECISION_COMPLETED,
    RunAttestation,
    SupervisorConfig,
    SupervisorError,
    _canonical_bytes,
    build_run_attestation,
    evidence_from_state,
)
from governed_supervisor_server import (  # noqa: E402
    LENGTH_PREFIX_BYTES,
    OP_ACCEPT_OPEN,
    OP_ATTEST_RUN,
    OP_COMPLETE_RUN,
    OP_EXECUTION_STARTED,
    OP_LAUNCH_GATE,
    REFUSE_NO_TERMINAL_RUN,
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

_OPEN = []


def tearDownModule():
    while _OPEN:
        try:
            _OPEN.pop().close()
        except sqlite3.Error:
            pass


def _ledger():
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    gsl.apply_schema(conn)
    _OPEN.append(conn)
    return conn


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


def _config(handles, supervisor_id="sup-1"):
    """The supervisor's OWN provisioning — including the identity block the isolated signer
    allowlists, which after F-01 no caller can contribute."""
    return SupervisorConfig(
        launcher_executable_sha256="1" * 64,
        executor_executable_sha256="2" * 64,
        id_fn=lambda: "id-1",
        supervisor_id=supervisor_id,
        executor_id="exec-1",
        builder_id="builder-1",
        policy_id="policy-1",
        policy_version="1.0.0",
        policy_bundle_handle=handles["policy_bundle_handle"],
        challenge_registry_handle="reg-handle",
        challenge_registry_hash="reg-hash",
        challenge_registry_epoch=2,
        challenge_registry_root_key_id="root-1",
    )


def _state(handles):
    """The supervisor's durable terminal run state for one attempt."""
    return gsl.AttestationState(
        run_id="run-abc",
        execution_attempt_id="attempt-1",
        task_id="task-1",
        request_nonce="550e8400-e29b-41d4-a716-446655440000",
        receipt_id="receipt-777",
        workspace_id="ws-1",
        install_id="install-xyz",
        supervisor_id="sup-1",
        requested_at_ms=NOW_MS - 5_000,
        challenge_accepted_at_ms=NOW_MS - 3_000,
        completed_at_ms=NOW_MS - 1_000,
        system_handle=handles["system_handle"],
        history_handle=handles["history_handle"],
        generation_config_handle=handles["generation_config_handle"],
        output_handle=handles["output_handle"],
        containment_evidence_handle=handles["containment_evidence_handle"],
        record_handle=handles["record_handle"],
        lease_handle=handles["lease_handle"],
        execution_receipt_handle=handles["execution_receipt_handle"],
        evidence_final_event_hash="a" * 64,
        evidence_event_count=3,
        evidence_last_sequence=3,
        evidence_head_sequence=4,
    )


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
        attn = build_run_attestation(
            _state(handles), config=_config(handles),
            supervisor_key_id=SUP_KEY_ID, sign_attestation=ed.sign_attestation,
        )
        self.assertIsInstance(attn, RunAttestation)
        # The 3-field attestation object the signer verifies.
        self.assertEqual(
            set(attn.attestation.keys()),
            {"attestation_protocol", "supervisor_key_id", "sig"},
        )
        self.assertEqual(attn.attestation["attestation_protocol"], ATTESTATION_PROTOCOL)
        self.assertEqual(attn.attestation["supervisor_key_id"], SUP_KEY_ID)
        # The supervisor STAMPS decision=completed and builds EXACTLY the signer's evidence
        # shape; the signed bytes are JCS(evidence).
        evidence = {**evidence_from_state(_state(handles), _config(handles)),
                    "decision": DECISION_COMPLETED}
        self.assertEqual(set(evidence.keys()), set(EVIDENCE_FIELDS))
        self.assertEqual(attn.evidence_jcs, _canonical_bytes(evidence))
        self.assertEqual(attn.attestation_evidence_sha256, _h(attn.evidence_jcs))
        # The sig is a real detached Ed25519 over exactly those bytes.
        self.assertTrue(ed.verify_attestation(None, attn.evidence_jcs, attn.attestation["sig"]))

    def test_verifies_under_signer_verify_path_and_binds_the_digest(self):
        ed = _Ed25519()
        store, handles = _build_store()
        config = _config(handles)
        attn = build_run_attestation(
            _state(handles), config=config,
            supervisor_key_id=SUP_KEY_ID, sign_attestation=ed.sign_attestation,
        )
        signer = _make_signer(ed, store)
        # Full sign_result: the supervisor's attestation must verify inside the signer's real
        # verify path, and the envelope's attestation_evidence_sha256 must equal
        # sha256(evidence_jcs) the supervisor produced. The evidence handed to the signer is
        # PARSED FROM the attested bytes — exactly what the broker now does.
        sign_request = {
            "protocol": "brops.sign-request.v1",
            "attestation": attn.attestation,
            "evidence": json.loads(attn.evidence_jcs.decode("utf-8")),
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
        attn = build_run_attestation(
            _state(handles), config=_config(handles),
            supervisor_key_id="attacker-key", sign_attestation=ed.sign_attestation,
        )
        signer = _make_signer(ed, store)
        result = signer.sign_result(
            {
                "protocol": "brops.sign-request.v1",
                "attestation": attn.attestation,
                "evidence": json.loads(attn.evidence_jcs.decode("utf-8")),
            }
        )
        self.assertEqual(result["artifact_type"], REFUSAL_ARTIFACT_TYPE)
        self.assertEqual(result["reason"], REASON_ATTESTATION_INVALID)

    def test_tampered_evidence_field_breaks_verification(self):
        ed = _Ed25519()
        store, handles = _build_store()
        attn = build_run_attestation(
            _state(handles), config=_config(handles),
            supervisor_key_id=SUP_KEY_ID, sign_attestation=ed.sign_attestation,
        )
        signer = _make_signer(ed, store)
        # Feed the signer a tampered evidence (run_id flipped) with the ORIGINAL attestation
        # sig: the signer re-hashes different bytes -> sig invalid.
        tampered = json.loads(attn.evidence_jcs.decode("utf-8"))
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

    def test_the_identities_the_signer_allowlists_come_from_supervisor_provisioning(self):
        # F-01: a broker that could name executor_id/builder_id was choosing the values the
        # signer's allowlist would check. `executor_id`/`builder_id`/`policy_*` now come from
        # supervisor CONFIG; `supervisor_id` comes from the acceptance ROW (recorded from the
        # signed challenge at accept time, so a config edit cannot retroactively rewrite what
        # was accepted). Either way the requester contributes nothing.
        ed = _Ed25519()
        store, handles = _build_store()
        config = _config(handles)
        self.assertEqual(
            evidence_from_state(_state(handles), config)["executor_id"], "exec-1"
        )
        # Provision an executor identity the signer does NOT allowlist: the refusal proves
        # the value the allowlist checks is the supervisor's, not the caller's.
        rogue = SupervisorConfig(
            launcher_executable_sha256="1" * 64,
            executor_executable_sha256="2" * 64,
            id_fn=lambda: "id-1",
            supervisor_id="sup-1",
            executor_id="exec-ROGUE",
            builder_id="builder-1",
            policy_id="policy-1",
            policy_version="1.0.0",
            policy_bundle_handle=handles["policy_bundle_handle"],
            challenge_registry_handle="reg-handle",
            challenge_registry_hash="reg-hash",
            challenge_registry_epoch=2,
            challenge_registry_root_key_id="root-1",
        )
        attn = build_run_attestation(
            _state(handles), config=rogue,
            supervisor_key_id=SUP_KEY_ID, sign_attestation=ed.sign_attestation,
        )
        evidence = json.loads(attn.evidence_jcs.decode("utf-8"))
        self.assertEqual(evidence["executor_id"], "exec-ROGUE")
        result = _make_signer(ed, store).sign_result(
            {
                "protocol": "brops.sign-request.v1",
                "attestation": attn.attestation,
                "evidence": evidence,
            }
        )
        self.assertEqual(result["artifact_type"], REFUSAL_ARTIFACT_TYPE)

    def test_config_faults_raise(self):
        ed = _Ed25519()
        _store, handles = _build_store()
        state, config = _state(handles), _config(handles)
        with self.assertRaises(SupervisorError):
            build_run_attestation(state, config=config, supervisor_key_id="",
                                  sign_attestation=ed.sign_attestation)
        with self.assertRaises(SupervisorError):
            build_run_attestation(state, config=config, supervisor_key_id=SUP_KEY_ID,
                                  sign_attestation="nope")
        with self.assertRaises(SupervisorError):
            build_run_attestation(state, config=config, supervisor_key_id=SUP_KEY_ID,
                                  sign_attestation=lambda m: "")

    def test_a_caller_mapping_is_not_an_attestation_state(self):
        # The old attack surface, gone: there is no `facts` door to push a mapping through.
        ed = _Ed25519()
        _store, handles = _build_store()
        with self.assertRaises(SupervisorError):
            build_run_attestation(
                {"run_id": "run-abc"}, config=_config(handles),
                supervisor_key_id=SUP_KEY_ID, sign_attestation=ed.sign_attestation,
            )


# ---------------------------------------------------------------------------
# attest-run server op, driven over a FULL governed lifecycle
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


def _fixed_request_sha256(_payload):
    return "0" * 64


def _challenge_doc(handles, nonce="550e8400-e29b-41d4-a716-446655440000"):
    """A challenge whose component digests ARE the store handles, so the evidence the
    supervisor later assembles names artifacts the isolated signer can actually resolve."""
    return {
        "payload": {
            "protocol": CHALLENGE_PROTOCOL,
            "challenge_key_id": "chal-key",
            "run_id": "run-abc",
            "task_id": "task-1",
            "workspace_id": "ws-1",
            "install_id": "install-xyz",
            "supervisor_id": "sup-1",
            "request_nonce": nonce,
            "system_sha256": handles["system_handle"],
            "history_sha256": handles["history_handle"],
            "generation_config_sha256": handles["generation_config_handle"],
            "request_sha256": "0" * 64,
            "requested_at_ms": NOW_MS - 5_000,
            "challenge_issued_at_ms": NOW_MS - 4_000,
            "challenge_expires_at_ms": NOW_MS + 10_000,
        },
        "sig": "hmac-stand-in",
    }


def _run_evidence(output_handle, *, head_sequence=4, event_count=3):
    """A recorder evidence chain shaped as `governed_recorder` writes one (audit F-01)."""
    import hashlib as _h, json as _j

    def canon(payload):
        return _j.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def sha(data):
        return _h.sha256(data).hexdigest()

    payloads = [("lease-validated", {"n": i}) for i in range(1, event_count)]
    payloads.append(("output-captured", {"launcher_exit": 0, "output_sha256": output_handle}))
    previous, events = None, []
    for sequence, (event_type, payload) in enumerate(payloads, start=1):
        event = {"event_type": event_type, "payload": payload,
                 "payload_sha256": sha(canon(payload)),
                 "previous_event_hash": previous, "sequence": sequence}
        previous = sha(canon(event))
        events.append(event)
    return _j.dumps({"event_count": len(events), "events": events,
                     "final_event_hash": previous, "head_sequence": head_sequence,
                     "last_sequence": len(events),
                     "protocol": "brops.run-evidence-chain.v1"},
                    sort_keys=True, separators=(",", ":")).encode("utf-8")


class AttestRunServerTests(unittest.TestCase):
    def setUp(self):
        self.ed = _Ed25519()
        self.store, self.handles = _build_store()
        self.config = _config(self.handles)
        self.ledger_conn = _ledger()

    def _op(self, request, key_id=SUP_KEY_ID, ed=True):
        return dispatch(
            request,
            self.config,
            _noop_verify,
            _fixed_request_sha256,
            lambda: NOW_MS,
            conn=self.ledger_conn,
            publish_artifact=self.store.put,
            # F-01: the supervisor reads the RECORDER's chain for the evidence head and to check
            # that `output_handle` is the digest the recorder captured. Never caller-supplied.
            read_run_evidence=lambda attempt: _run_evidence(self.handles["output_handle"]),
            sign_attestation=(self.ed.sign_attestation if ed else None),
            supervisor_attestation_key_id=key_id if ed else None,
        )

    def _run_lifecycle(self, nonce="550e8400-e29b-41d4-a716-446655440000"):
        """accept-open → launch-gate → execution-started → complete-run. Returns the attempt."""
        accepted = self._op({"op": OP_ACCEPT_OPEN,
                             "challenge_doc": _challenge_doc(self.handles, nonce)})
        self.assertTrue(accepted["ok"], accepted)
        attempt = accepted["lease"]["execution_attempt_id"]
        self.assertTrue(self._op({"op": OP_LAUNCH_GATE,
                                  "execution_attempt_id": attempt})["ok"])
        self.assertTrue(self._op({
            "op": OP_EXECUTION_STARTED, "execution_attempt_id": attempt,
            "process_group_id": "1234", "cgroup_id": "cg-1",
            "execution_started_marker": None,
        })["ok"])
        self.assertTrue(self._op({
            "op": OP_COMPLETE_RUN, "execution_attempt_id": attempt,
            "produced": {
                "output_handle": self.handles["output_handle"],
                "containment_evidence_handle": self.handles["containment_evidence_handle"],
                # The supervisor stamped `challenge_accepted_at_ms` from its own clock at
                # accept-open (NOW_MS here), so a completion must not predate it — the signer's
                # `_check_timestamps` enforces requested_at <= challenge_accepted <= completed.
                "completed_at_ms": NOW_MS,
            },
        })["ok"])
        return attempt

    def test_happy_path_returns_attestation_and_exact_evidence_jcs(self):
        attempt = self._run_lifecycle()
        reply = self._op({"op": OP_ATTEST_RUN, "run_id": "run-abc",
                          "execution_attempt_id": attempt})
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["op"], OP_ATTEST_RUN)
        self.assertEqual(reply["attestation"]["attestation_protocol"], ATTESTATION_PROTOCOL)
        self.assertEqual(reply["attestation"]["supervisor_key_id"], SUP_KEY_ID)
        evidence_jcs = _unb64u(reply["evidence_jcs_b64"])
        self.assertEqual(reply["attestation_evidence_sha256"], _h(evidence_jcs))
        self.assertTrue(
            self.ed.verify_attestation(None, evidence_jcs, reply["attestation"]["sig"])
        )
        evidence = json.loads(evidence_jcs.decode("utf-8"))
        self.assertEqual(set(evidence.keys()), set(EVIDENCE_FIELDS))
        self.assertEqual(evidence["decision"], DECISION_COMPLETED)

    def test_the_attested_evidence_signs_a_real_receipt_envelope(self):
        # The whole chain, offline: a governed lifecycle the supervisor authorized produces an
        # attestation the ISOLATED SIGNER accepts and turns into a signed envelope.
        attempt = self._run_lifecycle()
        reply = self._op({"op": OP_ATTEST_RUN, "run_id": "run-abc",
                          "execution_attempt_id": attempt})
        evidence_jcs = _unb64u(reply["evidence_jcs_b64"])
        result = _make_signer(self.ed, self.store).sign_result({
            "protocol": "brops.sign-request.v1",
            "attestation": reply["attestation"],
            "evidence": json.loads(evidence_jcs.decode("utf-8")),
        })
        self.assertEqual(result["artifact_type"], ENVELOPE_ARTIFACT_TYPE, result)
        self.assertEqual(result["status"], "signed")
        self.assertEqual(
            result["payload"]["attestation_evidence_sha256"],
            reply["attestation_evidence_sha256"],
        )
        # The receipt_id in the signed envelope was MINTED BY THE SUPERVISOR at acceptance —
        # it was never a value the requester supplied.
        self.assertEqual(result["payload"]["receipt_id"], "id-1")

    def test_non_broker_peer_denied_before_any_frame(self):
        conn = FakeConn(
            RENDERER_UID,
            inbound=_frame({"op": OP_ATTEST_RUN, "run_id": "run-abc",
                            "execution_attempt_id": "attempt-1"}),
        )
        reply = handle_connection(
            conn, BROKER_UID, self.config, _noop_verify, _fixed_request_sha256,
            lambda: NOW_MS, ledger_conn=self.ledger_conn, publish_artifact=self.store.put,
            sign_attestation=self.ed.sign_attestation,
            supervisor_attestation_key_id=SUP_KEY_ID,
        )
        self.assertFalse(reply["ok"])
        self.assertIn("peer", reply["error"])
        self.assertNotIn("attestation", reply)

    def test_the_old_facts_protocol_is_refused_outright(self):
        attempt = self._run_lifecycle()
        conn = FakeConn(BROKER_UID, inbound=_frame({
            "op": OP_ATTEST_RUN, "run_id": "run-abc", "execution_attempt_id": attempt,
            "facts": {"output_handle": "9" * 64},
        }))
        reply = handle_connection(
            conn, BROKER_UID, self.config, _noop_verify, _fixed_request_sha256,
            lambda: NOW_MS, ledger_conn=self.ledger_conn, publish_artifact=self.store.put,
            sign_attestation=self.ed.sign_attestation,
            supervisor_attestation_key_id=SUP_KEY_ID,
        )
        self.assertFalse(reply["ok"])
        self.assertIn("facts", reply["error"])
        self.assertNotIn("attestation", reply)

    def test_a_run_that_never_happened_gets_no_attestation(self):
        reply = self._op({"op": OP_ATTEST_RUN, "run_id": "run-ghost",
                          "execution_attempt_id": "attempt-ghost"})
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["reason"], REFUSE_NO_TERMINAL_RUN)
        self.assertNotIn("attestation", reply)

    def test_op_unavailable_without_seam_fails_closed(self):
        conn = FakeConn(BROKER_UID, inbound=_frame({
            "op": OP_ATTEST_RUN, "run_id": "run-abc", "execution_attempt_id": "attempt-1",
        }))
        reply = handle_connection(
            conn, BROKER_UID, self.config, _noop_verify, _fixed_request_sha256,
            lambda: NOW_MS, ledger_conn=self.ledger_conn, publish_artifact=self.store.put,
        )
        self.assertFalse(reply["ok"])
        self.assertNotIn("attestation", reply)


if __name__ == "__main__":
    unittest.main()
