"""Offline tests for the governed-supervisor acceptance/lease core (rev-30 §5).

No socket, no OS trust chain, no real signer: signing/verification is a real
``hmac`` over the exact canonical bytes the supervisor reassembles, and
``request_sha256`` is a real ``hashlib.sha256`` re-derivation from the challenge
fields — both injected as the pure seams the design mandates. The clock is a
fixed int and lease/attempt ids come from a deterministic counter.

These exercise the normative behaviours of the slice:

  * a fully-valid signed challenge -> a lease (expiry = now + 210000, pinned
    executable digests from the supervisor's OWN config) PLUS the durable acceptance
    record the ledger CASes into existence;
  * an expired challenge -> ``challenge_expired`` (no lease);
  * a challenge whose ``request_sha256`` does not re-derive -> mismatch (no lease);
  * a challenge addressed to ANOTHER supervisor -> ``supervisor_mismatch``;
  * a forged signature / malformed shape -> refused (no lease);
  * **F-01**: the run attestation is built from durable state, never from caller facts.

The step-8a launch gate is no longer here — it moved into the durable ledger
(``governed_supervisor_ledger.gate_and_start``), and its boundary behaviour is covered by
``test_governed_supervisor_ledger.LaunchGateTests``.
"""

import hashlib
import hmac
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from governed_supervisor import (  # noqa: E402
    ATTEST_INPUT_FIELDS,
    CHALLENGE_PROTOCOL,
    LEASE_DURATION_MS,
    REFUSE_CHALLENGE_EXPIRED,
    REFUSE_MALFORMED,
    REFUSE_REQUEST_SHA256_MISMATCH,
    REFUSE_SIGNATURE_INVALID,
    REFUSE_SUPERVISOR_MISMATCH,
    Accepted,
    RunAttestation,
    SupervisorConfig,
    SupervisorError,
    Refusal,
    accept_open,
    build_run_attestation,
    evidence_from_state,
    recompute_request_sha256,
)
from governed_supervisor_ledger import AttestationState  # noqa: E402

# The supervisor's OWN canonical (brops.request.v1) recompute is the injected
# binding seam — genuinely independent of the authority (it re-derives from the
# challenge payload's own fields).
_recompute_request_sha256 = recompute_request_sha256

# A stand-in challenge signing key. In production the challenge authority holds
# an isolated key; here a fixed secret makes the hmac deterministic and offline.
CHALLENGE_KEY = b"test-challenge-key-not-a-secret"

LAUNCHER_SHA = "1" * 64
EXECUTOR_SHA = "2" * 64

NOW = 1_000_000  # fixed epoch-ms clock for the deterministic cases.


def _canonical(payload) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _verify_sig(message: bytes, sig: str) -> bool:
    """Constant-time hmac check over the supervisor-reassembled canonical bytes."""
    expected = hmac.new(CHALLENGE_KEY, message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


def _sign(message: bytes) -> str:
    return hmac.new(CHALLENGE_KEY, message, hashlib.sha256).hexdigest()


def _config():
    counter = {"n": 0}

    def id_fn():
        counter["n"] += 1
        return "id-%08d" % counter["n"]

    return SupervisorConfig(
        launcher_executable_sha256=LAUNCHER_SHA,
        executor_executable_sha256=EXECUTOR_SHA,
        id_fn=id_fn,
        # The identity block the isolated signer allowlists. It comes from supervisor
        # provisioning — never from the wire (F-01).
        supervisor_id="sup-1",
        executor_id="exec-1",
        builder_id="builder-1",
        policy_id="policy-1",
        policy_version="v1",
        policy_bundle_handle="e" * 64,
        challenge_registry_handle="reg-handle",
        challenge_registry_hash="reg-hash",
        challenge_registry_epoch=7,
        challenge_registry_root_key_id="root-1",
    )


def _valid_payload(issued=NOW, ttl=30_000):
    """A well-formed §4.1 challenge payload whose request_sha256 re-derives from
    its own fields via the canonical brops.request.v1 envelope (so an honest
    re-derivation matches)."""
    payload = {
        "protocol": CHALLENGE_PROTOCOL,
        "challenge_key_id": "chal-key-2026-07",
        "run_id": "run-1",
        "task_id": "task-1",
        "workspace_id": "ws-1",
        "install_id": "install-1",
        "supervisor_id": "sup-1",
        "request_nonce": "nonce-abc-123",
        "system_sha256": "a" * 64,
        "history_sha256": "b" * 64,
        "generation_config_sha256": "c" * 64,
        "request_sha256": "",  # filled below from the recompute seam
        "requested_at_ms": 1_700_000_000_000,
        "challenge_issued_at_ms": issued,
        "challenge_expires_at_ms": issued + ttl,
    }
    payload["request_sha256"] = _recompute_request_sha256(payload)
    return payload


def _signed_doc(payload):
    return {"payload": payload, "sig": _sign(_canonical(payload))}


def _accept(doc, now=NOW, config=None):
    return accept_open(
        doc,
        now,
        config=config or _config(),
        verify_sig=_verify_sig,
        recompute_request_sha256=_recompute_request_sha256,
    )


class AcceptOpenValidTests(unittest.TestCase):
    def test_valid_challenge_yields_lease(self):
        result = _accept(_signed_doc(_valid_payload()))
        self.assertIsInstance(result, Accepted)
        lease = result.lease
        # Lease expiry is the supervisor's own clock + the fixed 210000 duration.
        self.assertEqual(lease.lease_expires_at_ms, NOW + LEASE_DURATION_MS)
        self.assertEqual(lease.lease_expires_at_ms, NOW + 210_000)
        # The pinned executable digests come from config, NOT the challenge.
        self.assertEqual(lease.launcher_executable_sha256, LAUNCHER_SHA)
        self.assertEqual(lease.executor_executable_sha256, EXECUTOR_SHA)
        # Two distinct opaque ids were minted.
        self.assertTrue(lease.lease_id)
        self.assertTrue(lease.execution_attempt_id)
        self.assertNotEqual(lease.lease_id, lease.execution_attempt_id)

    def test_acceptance_record_binds_the_signed_challenge_not_the_caller(self):
        # F-01: everything the later attestation is rebuilt from is copied here, out of the
        # payload whose signature just verified, plus supervisor-owned values.
        payload = _valid_payload()
        result = _accept(_signed_doc(payload))
        a = result.acceptance
        self.assertEqual(a.run_id, payload["run_id"])
        self.assertEqual(a.task_id, payload["task_id"])
        self.assertEqual(a.workspace_id, payload["workspace_id"])
        self.assertEqual(a.install_id, payload["install_id"])
        self.assertEqual(a.request_nonce, payload["request_nonce"])
        self.assertEqual(a.request_sha256, payload["request_sha256"])
        self.assertEqual(a.system_handle, payload["system_sha256"])
        self.assertEqual(a.history_handle, payload["history_sha256"])
        self.assertEqual(a.generation_config_handle, payload["generation_config_sha256"])
        self.assertEqual(a.requested_at_ms, payload["requested_at_ms"])
        # Supervisor-owned: the acceptance clock, the lease window, the identity, and a
        # PER-TURN receipt_id (a deployment-static one would defeat the §7.1(d) replay key).
        self.assertEqual(a.challenge_accepted_at_ms, NOW)
        self.assertEqual(a.lease_issued_at_ms, NOW)
        self.assertEqual(a.lease_expires_at_ms, NOW + LEASE_DURATION_MS)
        self.assertEqual(a.supervisor_id, "sup-1")
        self.assertTrue(a.receipt_id)
        self.assertNotIn(a.receipt_id, (a.lease_id, a.execution_attempt_id))
        # The challenge handle is the supervisor's OWN content address of the exact bytes
        # it verified — the ledger's UNIQUE on it is what makes a replay buy nothing.
        self.assertEqual(a.challenge_handle, hashlib.sha256(_canonical(payload)).hexdigest())
        # And the attempt id in the record IS the one in the lease handed to the caller.
        self.assertEqual(a.execution_attempt_id, result.lease.execution_attempt_id)

    def test_two_acceptances_of_distinct_challenges_get_distinct_receipt_ids(self):
        config = _config()
        first = _accept(_signed_doc(_valid_payload()), config=config)
        other = _valid_payload()
        other["request_nonce"] = "nonce-second"
        other["request_sha256"] = _recompute_request_sha256(other)
        second = _accept(_signed_doc(other), config=config)
        self.assertNotEqual(first.acceptance.receipt_id, second.acceptance.receipt_id)

    def test_lease_at_exact_expiry_boundary_still_accepts(self):
        # now == challenge_expires_at_ms is NOT past expiry -> still a lease.
        payload = _valid_payload(issued=NOW - 30_000)  # expires exactly at NOW
        self.assertEqual(payload["challenge_expires_at_ms"], NOW)
        self.assertIsInstance(_accept(_signed_doc(payload), now=NOW), Accepted)


class AcceptOpenAddressingTests(unittest.TestCase):
    def test_challenge_for_another_supervisor_is_refused(self):
        # Authentically signed, correctly bound — but issued for a DIFFERENT supervisor.
        # Authentic is not the same as addressed to me.
        payload = _valid_payload()
        payload["supervisor_id"] = "sup-OTHER"
        payload["request_sha256"] = _recompute_request_sha256(payload)
        result = _accept(_signed_doc(payload), now=NOW)
        self.assertIsInstance(result, Refusal)
        self.assertEqual(result.reason, REFUSE_SUPERVISOR_MISMATCH)


class AcceptOpenExpiryTests(unittest.TestCase):
    def test_expired_challenge_is_refused(self):
        payload = _valid_payload(issued=NOW - 30_001)  # expired by 1 ms at NOW
        result = _accept(_signed_doc(payload), now=NOW)
        self.assertIsInstance(result, Refusal)
        self.assertEqual(result.reason, REFUSE_CHALLENGE_EXPIRED)


class AcceptOpenBindingTests(unittest.TestCase):
    def test_request_sha256_mismatch_is_refused(self):
        payload = _valid_payload()
        # A valid-shaped but wrong request_sha256, then re-signed so the doc is
        # authentically signed for its bytes — this isolates the phase-B binding
        # check (mismatch) from the phase-A signature check.
        payload["request_sha256"] = "f" * 64
        result = _accept(_signed_doc(payload), now=NOW)
        self.assertIsInstance(result, Refusal)
        self.assertEqual(result.reason, REFUSE_REQUEST_SHA256_MISMATCH)

    def test_tampered_field_breaks_rederivation(self):
        # Change a field that feeds the digest (and re-sign) WITHOUT updating the
        # stored request_sha256 -> it no longer re-derives -> mismatch, no lease.
        payload = _valid_payload()
        payload["system_sha256"] = "d" * 64  # digest basis changed, hash stale
        result = _accept(_signed_doc(payload), now=NOW)
        self.assertIsInstance(result, Refusal)
        self.assertEqual(result.reason, REFUSE_REQUEST_SHA256_MISMATCH)


class AcceptOpenSignatureTests(unittest.TestCase):
    def test_forged_signature_is_refused(self):
        doc = _signed_doc(_valid_payload())
        doc["sig"] = "0" * 64  # not the hmac over the canonical bytes
        result = _accept(doc, now=NOW)
        self.assertIsInstance(result, Refusal)
        self.assertEqual(result.reason, REFUSE_SIGNATURE_INVALID)

    def test_payload_swapped_under_valid_old_sig_is_refused(self):
        # A signature that is valid for a DIFFERENT payload does not validate the
        # new bytes the supervisor reassembles -> signature_invalid.
        good = _valid_payload()
        other = _valid_payload()
        other["install_id"] = "install-OTHER"
        other["request_sha256"] = _recompute_request_sha256(other)
        doc = {"payload": other, "sig": _sign(_canonical(good))}
        result = _accept(doc, now=NOW)
        self.assertIsInstance(result, Refusal)
        self.assertEqual(result.reason, REFUSE_SIGNATURE_INVALID)


class AcceptOpenMalformedTests(unittest.TestCase):
    def test_non_mapping_is_malformed(self):
        self.assertEqual(_accept("not-a-doc").reason, REFUSE_MALFORMED)

    def test_missing_payload_field_is_malformed(self):
        payload = _valid_payload()
        del payload["supervisor_id"]
        # (re-sign so we know it is the SHAPE, not the sig, that refuses)
        result = _accept(_signed_doc(payload))
        self.assertEqual(result.reason, REFUSE_MALFORMED)

    def test_extra_payload_field_is_malformed(self):
        payload = _valid_payload()
        payload["evil_bytes"] = "attacker-controlled"
        self.assertEqual(_accept(_signed_doc(payload)).reason, REFUSE_MALFORMED)

    def test_extra_envelope_field_is_malformed(self):
        doc = _signed_doc(_valid_payload())
        doc["smuggled"] = "x"
        self.assertEqual(_accept(doc).reason, REFUSE_MALFORMED)

    def test_wrong_protocol_is_malformed(self):
        payload = _valid_payload()
        payload["protocol"] = "brops.some-other.v1"
        self.assertEqual(_accept(_signed_doc(payload)).reason, REFUSE_MALFORMED)

    def test_non_int_timestamp_is_malformed(self):
        payload = _valid_payload()
        payload["challenge_expires_at_ms"] = "soon"
        self.assertEqual(_accept(_signed_doc(payload)).reason, REFUSE_MALFORMED)

    def test_boolean_timestamp_is_malformed(self):
        payload = _valid_payload()
        payload["challenge_issued_at_ms"] = True  # bool is not an accepted int
        self.assertEqual(_accept(_signed_doc(payload)).reason, REFUSE_MALFORMED)

    def test_over_cap_ttl_is_malformed(self):
        payload = _valid_payload(ttl=30_001)  # 1 ms past the 30000 cap
        self.assertEqual(_accept(_signed_doc(payload)).reason, REFUSE_MALFORMED)

    def test_bad_request_sha256_shape_is_malformed(self):
        payload = _valid_payload()
        payload["request_sha256"] = "not-64-hex"
        self.assertEqual(_accept(_signed_doc(payload)).reason, REFUSE_MALFORMED)


def _state(**over):
    fields = dict(
        run_id="run-1",
        execution_attempt_id="att-1",
        task_id="task-1",
        request_nonce="nonce-abc-123",
        receipt_id="receipt-1",
        workspace_id="ws-1",
        install_id="install-1",
        supervisor_id="sup-1",
        requested_at_ms=1_700_000_000_000,
        challenge_accepted_at_ms=1_700_000_000_100,
        completed_at_ms=1_700_000_000_900,
        system_handle="a" * 64,
        history_handle="b" * 64,
        generation_config_handle="c" * 64,
        output_handle="d" * 64,
        containment_evidence_handle="e" * 64,
        record_handle="f" * 64,
        lease_handle="0" * 64,
        execution_receipt_handle="1" * 64,
        evidence_final_event_hash="2" * 64,
        evidence_event_count=3,
        evidence_last_sequence=3,
        evidence_head_sequence=12,
    )
    fields.update(over)
    return AttestationState(**fields)


class RunAttestationIsNotAnOracleTests(unittest.TestCase):
    """The F-01 regression suite, at the unit level.

    Before the fix, ``build_run_attestation(facts, …)`` signed a caller-supplied mapping.
    The defence is now the type signature: the ONLY thing it accepts is an
    ``AttestationState``, which only the durable ledger can produce.
    """

    def test_a_caller_mapping_can_no_longer_be_attested(self):
        # This is precisely the old attack: hand the supervisor a fabricated fact set.
        # It is not a refusal path any more — it is a type error at the door.
        fabricated = {field: "x" for field in ATTEST_INPUT_FIELDS}
        with self.assertRaises(SupervisorError):
            build_run_attestation(
                fabricated,
                config=_config(),
                supervisor_key_id="sup-attest-key",
                sign_attestation=lambda message: "sig",
            )

    def test_the_function_has_no_facts_parameter_at_all(self):
        import inspect

        params = set(inspect.signature(build_run_attestation).parameters)
        self.assertNotIn("facts", params)
        self.assertEqual(params, {"state", "config", "supervisor_key_id", "sign_attestation"})

    def test_evidence_is_assembled_from_state_and_config_only(self):
        config = _config()
        evidence = evidence_from_state(_state(), config)
        # Exactly the signer's evidence shape, no more and no less.
        self.assertEqual(set(evidence), set(ATTEST_INPUT_FIELDS))
        # The identities the isolated signer ALLOWLISTS come from supervisor provisioning,
        # so a caller can no longer name itself an allowed executor/builder/supervisor.
        self.assertEqual(evidence["executor_id"], "exec-1")
        self.assertEqual(evidence["builder_id"], "builder-1")
        self.assertEqual(evidence["supervisor_id"], "sup-1")
        self.assertEqual(evidence["policy_id"], "policy-1")
        self.assertEqual(evidence["policy_version"], "v1")
        self.assertEqual(evidence["policy_bundle_handle"], "e" * 64)
        # The run/binding half comes from the durable row.
        self.assertEqual(evidence["run_id"], "run-1")
        self.assertEqual(evidence["request_nonce"], "nonce-abc-123")
        self.assertEqual(evidence["receipt_id"], "receipt-1")
        self.assertEqual(evidence["output_handle"], "d" * 64)
        self.assertEqual(evidence["requested_at"], 1_700_000_000_000)
        self.assertEqual(evidence["completed_at"], 1_700_000_000_900)

    def test_a_valid_state_produces_a_signed_attestation_over_its_own_bytes(self):
        signed = {}

        def sign(message: bytes) -> str:
            signed["message"] = message
            return "sig-over-supervisor-bytes"

        result = build_run_attestation(
            _state(),
            config=_config(),
            supervisor_key_id="sup-attest-key",
            sign_attestation=sign,
        )
        self.assertIsInstance(result, RunAttestation)
        # The seam was handed exactly the JCS the supervisor assembled — never caller bytes.
        self.assertEqual(signed["message"], result.evidence_jcs)
        self.assertEqual(
            result.attestation_evidence_sha256,
            hashlib.sha256(result.evidence_jcs).hexdigest(),
        )
        # The supervisor STAMPS the decision; it is not an input anywhere.
        self.assertIn(b'"decision":"completed"', result.evidence_jcs)

    def test_a_seam_returning_no_signature_is_a_supervisor_fault_not_a_half_attestation(self):
        with self.assertRaises(SupervisorError):
            build_run_attestation(
                _state(),
                config=_config(),
                supervisor_key_id="sup-attest-key",
                sign_attestation=lambda message: "",
            )


if __name__ == "__main__":
    unittest.main()
