"""Offline tests for the governed-supervisor acceptance/lease core (rev-30 §5).

No socket, no OS trust chain, no real signer: signing/verification is a real
``hmac`` over the exact canonical bytes the supervisor reassembles, and
``request_sha256`` is a real ``hashlib.sha256`` re-derivation from the challenge
fields — both injected as the pure seams the design mandates. The clock is a
fixed int and lease/attempt ids come from a deterministic counter.

These exercise the normative behaviours of the slice:

  * a fully-valid signed challenge -> a lease (expiry = now + 210000, pinned
    executable digests from the supervisor's OWN config);
  * an expired challenge -> ``challenge_expired`` (no lease);
  * a challenge whose ``request_sha256`` does not re-derive -> mismatch (no lease);
  * a forged signature / malformed shape -> refused (no lease);
  * the step-8a launch gate: proceed at the exact budget boundary, refuse below it.
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
    CHALLENGE_PROTOCOL,
    LEASE_DURATION_MS,
    MIN_LAUNCH_REMAINING_MS,
    REFUSE_CHALLENGE_EXPIRED,
    REFUSE_LEASE_EXPIRED,
    REFUSE_MALFORMED,
    REFUSE_REQUEST_SHA256_MISMATCH,
    REFUSE_SIGNATURE_INVALID,
    Lease,
    LaunchProceed,
    Refusal,
    SupervisorConfig,
    accept_open,
    launch_gate,
)

# A stand-in challenge signing key. In production the challenge authority holds
# an isolated key; here a fixed secret makes the hmac deterministic and offline.
CHALLENGE_KEY = b"test-challenge-key-not-a-secret"

LAUNCHER_SHA = "1" * 64
EXECUTOR_SHA = "2" * 64

NOW = 1_000_000  # fixed epoch-ms clock for the deterministic cases.


def _canonical(payload) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _recompute_request_sha256(payload) -> str:
    """Re-derive request_sha256 from the challenge's OWN fields (the injected
    binding seam). A real supervisor recomputes the governed-request digest; here
    we hash a canonical subset so the test's valid doc round-trips exactly."""
    basis = {
        "request_nonce": payload["request_nonce"],
        "conversation_id": payload["conversation_id"],
        "install_id": payload["install_id"],
        "workspace_id": payload["workspace_id"],
    }
    return hashlib.sha256(_canonical(basis)).hexdigest()


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
    )


def _valid_payload(issued=NOW, ttl=30_000):
    """A well-formed challenge payload whose request_sha256 re-derives from its own
    fields (so an honest re-derivation matches)."""
    payload = {
        "protocol": CHALLENGE_PROTOCOL,
        "challenge_key_id": "chal-key-2026-07",
        "request_nonce": "nonce-abc-123",
        "request_sha256": "",  # filled below from the recompute seam
        "conversation_id": "conv-1",
        "install_id": "install-1",
        "workspace_id": "ws-1",
        "supervisor_id": "sup-1",
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
        self.assertIsInstance(result, Lease)
        # Lease expiry is the supervisor's own clock + the fixed 210000 duration.
        self.assertEqual(result.lease_expires_at_ms, NOW + LEASE_DURATION_MS)
        self.assertEqual(result.lease_expires_at_ms, NOW + 210_000)
        # The pinned executable digests come from config, NOT the challenge.
        self.assertEqual(result.launcher_executable_sha256, LAUNCHER_SHA)
        self.assertEqual(result.executor_executable_sha256, EXECUTOR_SHA)
        # Two distinct opaque ids were minted.
        self.assertTrue(result.lease_id)
        self.assertTrue(result.execution_attempt_id)
        self.assertNotEqual(result.lease_id, result.execution_attempt_id)

    def test_lease_at_exact_expiry_boundary_still_accepts(self):
        # now == challenge_expires_at_ms is NOT past expiry -> still a lease.
        payload = _valid_payload(issued=NOW - 30_000)  # expires exactly at NOW
        self.assertEqual(payload["challenge_expires_at_ms"], NOW)
        self.assertIsInstance(_accept(_signed_doc(payload), now=NOW), Lease)


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
        # Change a field that feeds the digest (and re-sign) -> the stored
        # request_sha256 no longer re-derives -> mismatch, never a lease.
        payload = _valid_payload()
        payload["conversation_id"] = "conv-TAMPERED"  # digest basis changed
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


class LaunchGateTests(unittest.TestCase):
    def _lease(self, expires):
        return Lease(
            lease_id="l-1",
            execution_attempt_id="a-1",
            lease_expires_at_ms=expires,
            launcher_executable_sha256=LAUNCHER_SHA,
            executor_executable_sha256=EXECUTOR_SHA,
        )

    def test_proceeds_at_exact_budget_boundary(self):
        # remaining == MIN_LAUNCH_REMAINING_MS proceeds.
        lease = self._lease(expires=NOW + MIN_LAUNCH_REMAINING_MS)
        result = launch_gate(lease, NOW)
        self.assertIsInstance(result, LaunchProceed)
        self.assertIs(result.lease, lease)

    def test_refuses_one_ms_below_boundary(self):
        # remaining == MIN - 1 refuses with lease_expired.
        lease = self._lease(expires=NOW + MIN_LAUNCH_REMAINING_MS - 1)
        result = launch_gate(lease, NOW)
        self.assertIsInstance(result, Refusal)
        self.assertEqual(result.reason, REFUSE_LEASE_EXPIRED)

    def test_refuses_already_expired_lease(self):
        lease = self._lease(expires=NOW - 1)
        self.assertEqual(launch_gate(lease, NOW).reason, REFUSE_LEASE_EXPIRED)

    def test_freshly_issued_lease_passes_the_gate(self):
        # A lease issued right now (expiry = now + 210000) has 210000 remaining,
        # comfortably above the 180000 gate.
        result = _accept(_signed_doc(_valid_payload()))
        self.assertIsInstance(result, Lease)
        self.assertIsInstance(launch_gate(result, NOW), LaunchProceed)

    def test_gate_near_lease_expiry_refuses(self):
        # A lease with only 179999 ms of runway (deep into its life) is refused.
        lease = self._lease(expires=NOW + LEASE_DURATION_MS)
        late = NOW + LEASE_DURATION_MS - (MIN_LAUNCH_REMAINING_MS - 1)
        self.assertEqual(launch_gate(lease, late).reason, REFUSE_LEASE_EXPIRED)


if __name__ == "__main__":
    unittest.main()
