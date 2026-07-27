"""Offline tests for the desktop-challenge-authority service core (rev-30 §2.1).

No sockets, no keys, no OS trust chain: the store is a plain dict, the clock is
a fake, and signing is a stub. These exercise the three normative behaviours:

  * create-pending rejects anything but the fixed shape (extra/arbitrary field);
  * peer_is_broker allowlists ONLY the broker UID (renderer + sidecar denied);
  * issue uses the stored (broker-supplied) nonce, never a freshly minted one.
"""

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from challenge_authority import (  # noqa: E402
    CHALLENGE_PROTOCOL,
    MAX_CHALLENGE_TTL_MS,
    AuthorityConfig,
    ChallengeAuthorityError,
    PendingStore,
    issue_challenge,
    peer_is_broker,
    validate_create_pending,
)

# UIDs used across the trust-boundary tests. Distinct principals per §2.1.
BROKER_UID = 4001
RENDERER_UID = 1000  # interactive login / renderer identity
SIDECAR_UID = 4004

VALID_FIELDS = {
    "request_nonce": "550e8400-e29b-41d4-a716-446655440000",
    "request_sha256": "a" * 64,
    "conversation_id": "conv-123",
    "install_id": "install-xyz",
}


def _config():
    return AuthorityConfig(
        challenge_key_id="key-2026-07",
        workspace_id="ws-1",
        supervisor_id="sup-1",
    )


class ValidateCreatePendingTests(unittest.TestCase):
    def test_valid_fixed_shape_accepted(self):
        out = validate_create_pending(VALID_FIELDS)
        self.assertEqual(set(out.keys()), set(VALID_FIELDS.keys()))
        self.assertEqual(out["request_nonce"], VALID_FIELDS["request_nonce"])

    def test_extra_arbitrary_field_rejected(self):
        bad = dict(VALID_FIELDS)
        bad["evil_bytes"] = "arbitrary-attacker-controlled"
        with self.assertRaises(ChallengeAuthorityError):
            validate_create_pending(bad)

    def test_missing_field_rejected(self):
        bad = dict(VALID_FIELDS)
        del bad["install_id"]
        with self.assertRaises(ChallengeAuthorityError):
            validate_create_pending(bad)

    def test_bad_sha256_rejected(self):
        for value in ["z" * 64, "a" * 63, "a" * 65, 12345, None]:
            bad = dict(VALID_FIELDS)
            bad["request_sha256"] = value
            with self.assertRaises(ChallengeAuthorityError):
                validate_create_pending(bad)

    def test_empty_nonce_rejected(self):
        bad = dict(VALID_FIELDS)
        bad["request_nonce"] = ""
        with self.assertRaises(ChallengeAuthorityError):
            validate_create_pending(bad)

    def test_non_mapping_rejected(self):
        with self.assertRaises(ChallengeAuthorityError):
            validate_create_pending(["not", "a", "mapping"])

    def test_sha256_normalized_lowercase(self):
        upper = dict(VALID_FIELDS)
        upper["request_sha256"] = "A" * 64
        out = validate_create_pending(upper)
        self.assertEqual(out["request_sha256"], "a" * 64)


class PeerAuthTests(unittest.TestCase):
    def test_broker_allowed(self):
        self.assertTrue(peer_is_broker(BROKER_UID, BROKER_UID))

    def test_renderer_denied(self):
        self.assertFalse(peer_is_broker(RENDERER_UID, BROKER_UID))

    def test_sidecar_denied(self):
        self.assertFalse(peer_is_broker(SIDECAR_UID, BROKER_UID))

    def test_non_int_denied(self):
        self.assertFalse(peer_is_broker("4001", BROKER_UID))
        self.assertFalse(peer_is_broker(None, BROKER_UID))
        # bool must not sneak through int-ness (True == 1).
        self.assertFalse(peer_is_broker(True, 1))


class IssueTests(unittest.TestCase):
    def test_issue_uses_stored_nonce_never_minted(self):
        # Deterministic store id + fake clock + stub signer: no OS chain.
        store = PendingStore(id_fn=lambda: "pending-abc")
        pending_id = store.create_pending(validate_create_pending(VALID_FIELDS))
        row = store.consume(pending_id)

        signed_bytes = {}

        def sign_fn(data):
            signed_bytes["data"] = data
            return "sig-deadbeef"

        doc = issue_challenge(row, _config(), sign_fn, clock_ms=lambda: 1_000_000)

        payload = doc["payload"]
        # The authority copies the BROKER-supplied nonce verbatim; it never
        # mints a new one.
        self.assertEqual(payload["request_nonce"], VALID_FIELDS["request_nonce"])
        self.assertEqual(payload["request_sha256"], VALID_FIELDS["request_sha256"])
        self.assertEqual(payload["protocol"], CHALLENGE_PROTOCOL)
        # Authority-owned fields come from its own config, not the caller.
        self.assertEqual(payload["challenge_key_id"], "key-2026-07")
        self.assertEqual(payload["workspace_id"], "ws-1")
        self.assertEqual(payload["supervisor_id"], "sup-1")
        # Clock-stamped, TTL-bounded.
        self.assertEqual(payload["challenge_issued_at_ms"], 1_000_000)
        self.assertEqual(
            payload["challenge_expires_at_ms"], 1_000_000 + MAX_CHALLENGE_TTL_MS
        )
        self.assertEqual(doc["sig"], "sig-deadbeef")
        # sign_fn saw exactly the assembled payload's canonical bytes.
        self.assertIn(b"550e8400-e29b-41d4-a716-446655440000", signed_bytes["data"])

    def test_pending_row_one_time_consume(self):
        store = PendingStore(id_fn=lambda: "pending-once")
        pending_id = store.create_pending(validate_create_pending(VALID_FIELDS))
        store.consume(pending_id)
        with self.assertRaises(ChallengeAuthorityError):
            store.consume(pending_id)

    def test_issue_rejects_tampered_row_with_extra_field(self):
        # Even if the store were tampered to carry arbitrary bytes, issue
        # re-validates the fixed shape before signing.
        tampered = dict(VALID_FIELDS)
        tampered["request_nonce"] = ""  # invalid stored value
        with self.assertRaises(ChallengeAuthorityError):
            issue_challenge(tampered, _config(), lambda b: "sig", lambda: 1)

    def test_ttl_cannot_exceed_cap(self):
        with self.assertRaises(ChallengeAuthorityError):
            AuthorityConfig(
                challenge_key_id="k",
                workspace_id="w",
                supervisor_id="s",
                challenge_ttl_ms=MAX_CHALLENGE_TTL_MS + 1,
            )

    def test_create_pending_mints_fresh_id_only(self):
        store = PendingStore(id_fn=lambda: "opaque-id-1")
        pid = store.create_pending(validate_create_pending(VALID_FIELDS))
        self.assertEqual(pid, "opaque-id-1")
        stored = store.get(pid)
        # The authority mints only the pending id; the nonce is the broker's.
        self.assertEqual(stored["request_nonce"], VALID_FIELDS["request_nonce"])
        self.assertEqual(stored["pending_challenge_id"], "opaque-id-1")


if __name__ == "__main__":
    unittest.main()
