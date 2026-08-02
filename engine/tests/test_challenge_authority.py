"""Offline tests for the desktop-challenge-authority service core (rev-30 §2.1 / §2.1.1).

No sockets, no keys, no OS trust chain: the store is a plain dict, the clock is
a fake, and signing is a stub. These exercise the normative behaviours:

  * create-pending rejects anything but the fixed §2.1 shape (extra/arbitrary
    field, missing field) AND rejects a caller-supplied request_sha256 as a
    malformed unknown field (the authority recomputes it);
  * the authority RECOMPUTES request_sha256 itself via the canonical
    brops.request.v1 envelope and signs THAT into the §4.1 challenge;
  * peer_is_broker allowlists ONLY the broker UID (renderer + sidecar denied);
  * issue uses the stored (broker-supplied) nonce, never a freshly minted one;
  * issue persists the exact signed document and a repeat issue on a live
    ISSUED row replays it BYTE-FOR-BYTE (never re-signs / re-stamps), while an
    unknown id ⇒ no_pending_row and a logically-expired row ⇒ pending_expired.
"""

import hashlib
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from challenge_authority import (  # noqa: E402
    CHALLENGE_PROTOCOL,
    ISSUED_RETENTION_MS,
    MAX_CHALLENGE_TTL_MS,
    PENDING_TTL_MS,
    REASON_NO_PENDING_ROW,
    REASON_PENDING_EXPIRED,
    REASON_RETRY_CONFLICT,
    REQUEST_ENVELOPE_PROTOCOL,
    AuthorityConfig,
    ChallengeAuthorityError,
    PendingStore,
    issue_challenge,
    issue_challenge_document,
    peer_is_broker,
    recompute_request_sha256,
    validate_create_pending,
)

# UIDs used across the trust-boundary tests. Distinct principals per §2.1.
BROKER_UID = 4001
RENDERER_UID = 1000  # interactive login / renderer identity
SIDECAR_UID = 4004

# The exact §2.1 create-pending required set (NO request_sha256 — recomputed).
VALID_FIELDS = {
    "run_id": "run-1",
    "task_id": "task-1",
    "workspace_id": "ws-1",
    "install_id": "install-xyz",
    "request_nonce": "550e8400-e29b-41d4-a716-446655440000",
    "system_sha256": "a" * 64,
    "history_sha256": "b" * 64,
    "generation_config_sha256": "c" * 64,
    "requested_at_ms": 1_700_000_000_000,
}

NOW = 1_000_000


def _config():
    return AuthorityConfig(challenge_key_id="key-2026-07", supervisor_id="sup-1")


class ValidateCreatePendingTests(unittest.TestCase):
    def test_valid_fixed_shape_accepted(self):
        out = validate_create_pending(VALID_FIELDS)
        self.assertEqual(set(out.keys()), set(VALID_FIELDS.keys()))
        self.assertEqual(out["request_nonce"], VALID_FIELDS["request_nonce"])
        self.assertEqual(out["run_id"], "run-1")

    def test_caller_supplied_request_sha256_rejected_as_malformed(self):
        # §2.1: a caller request_sha256 is an unknown field ⇒ malformed.
        bad = dict(VALID_FIELDS)
        bad["request_sha256"] = "a" * 64
        with self.assertRaises(ChallengeAuthorityError) as cm:
            validate_create_pending(bad)
        self.assertIn("request_sha256", str(cm.exception))

    def test_extra_arbitrary_field_rejected(self):
        bad = dict(VALID_FIELDS)
        bad["evil_bytes"] = "arbitrary-attacker-controlled"
        with self.assertRaises(ChallengeAuthorityError):
            validate_create_pending(bad)

    def test_missing_field_rejected(self):
        for field in VALID_FIELDS:
            bad = dict(VALID_FIELDS)
            del bad[field]
            with self.assertRaises(ChallengeAuthorityError):
                validate_create_pending(bad)

    def test_bad_component_sha256_rejected(self):
        for field in ("system_sha256", "history_sha256", "generation_config_sha256"):
            for value in ["z" * 64, "a" * 63, "a" * 65, 12345, None]:
                bad = dict(VALID_FIELDS)
                bad[field] = value
                with self.assertRaises(ChallengeAuthorityError):
                    validate_create_pending(bad)

    def test_empty_nonce_rejected(self):
        bad = dict(VALID_FIELDS)
        bad["request_nonce"] = ""
        with self.assertRaises(ChallengeAuthorityError):
            validate_create_pending(bad)

    def test_oversize_id_rejected(self):
        bad = dict(VALID_FIELDS)
        bad["run_id"] = "x" * 129
        with self.assertRaises(ChallengeAuthorityError):
            validate_create_pending(bad)

    def test_non_int_requested_at_rejected(self):
        for value in ["123", 0, -1, True, None, 1.5]:
            bad = dict(VALID_FIELDS)
            bad["requested_at_ms"] = value
            with self.assertRaises(ChallengeAuthorityError):
                validate_create_pending(bad)

    def test_non_mapping_rejected(self):
        with self.assertRaises(ChallengeAuthorityError):
            validate_create_pending(["not", "a", "mapping"])

    def test_component_sha256_normalized_lowercase(self):
        upper = dict(VALID_FIELDS)
        upper["system_sha256"] = "A" * 64
        out = validate_create_pending(upper)
        self.assertEqual(out["system_sha256"], "a" * 64)


class RecomputeRequestSha256Tests(unittest.TestCase):
    def test_recompute_matches_canonical_envelope(self):
        facts = validate_create_pending(VALID_FIELDS)
        envelope = {
            "protocol": REQUEST_ENVELOPE_PROTOCOL,
            "workspace_id": facts["workspace_id"],
            "install_id": facts["install_id"],
            "request_nonce": facts["request_nonce"],
            "system_sha256": facts["system_sha256"],
            "history_sha256": facts["history_sha256"],
            "generation_config_sha256": facts["generation_config_sha256"],
            "requested_at": str(facts["requested_at_ms"]),
        }
        expected = hashlib.sha256(
            json.dumps(
                envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(recompute_request_sha256(facts), expected)

    def test_recompute_is_deterministic(self):
        facts = validate_create_pending(VALID_FIELDS)
        self.assertEqual(recompute_request_sha256(facts), recompute_request_sha256(facts))

    def test_recompute_changes_with_a_component_hash(self):
        facts = validate_create_pending(VALID_FIELDS)
        other = dict(facts)
        other["system_sha256"] = "d" * 64
        self.assertNotEqual(recompute_request_sha256(facts), recompute_request_sha256(other))


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


class CreatePendingStoreTests(unittest.TestCase):
    def test_create_mints_fresh_id_and_recomputes_request_sha256(self):
        store = PendingStore(id_fn=lambda: "opaque-id-1")
        pid, expires = store.create_pending(validate_create_pending(VALID_FIELDS), NOW)
        self.assertEqual(pid, "opaque-id-1")
        self.assertEqual(expires, NOW + PENDING_TTL_MS)
        stored = store.get(pid)
        self.assertEqual(stored["request_nonce"], VALID_FIELDS["request_nonce"])
        self.assertEqual(stored["pending_challenge_id"], "opaque-id-1")
        self.assertEqual(stored["state"], "PENDING")
        # The stored request_sha256 is the authority-recomputed value.
        self.assertEqual(
            stored["request_sha256"],
            recompute_request_sha256(validate_create_pending(VALID_FIELDS)),
        )

    def test_idempotent_repeat_returns_same_id(self):
        ids = iter(["p1", "p2"])
        store = PendingStore(id_fn=lambda: next(ids))
        pid1, exp1 = store.create_pending(validate_create_pending(VALID_FIELDS), NOW)
        pid2, exp2 = store.create_pending(validate_create_pending(VALID_FIELDS), NOW + 500)
        self.assertEqual(pid1, pid2)  # lost-reply-safe retry, id never re-minted
        self.assertEqual(exp1, exp2)

    def test_same_nonce_differing_fact_is_retry_conflict(self):
        ids = iter(["p1", "p2"])
        store = PendingStore(id_fn=lambda: next(ids))
        store.create_pending(validate_create_pending(VALID_FIELDS), NOW)
        conflicting = dict(VALID_FIELDS)
        conflicting["task_id"] = "task-DIFFERENT"  # same (install_id, request_nonce)
        with self.assertRaises(ChallengeAuthorityError) as cm:
            store.create_pending(validate_create_pending(conflicting), NOW + 1)
        self.assertEqual(cm.exception.reason, REASON_RETRY_CONFLICT)


class IssueTests(unittest.TestCase):
    def _create(self, store, now=NOW):
        return store.create_pending(validate_create_pending(VALID_FIELDS), now)

    def test_issue_builds_full_field_challenge_from_stored_row(self):
        store = PendingStore(id_fn=lambda: "pending-abc")
        pid, _ = self._create(store)

        signed_bytes = {}

        def sign_fn(data):
            signed_bytes["data"] = data
            return "sig-deadbeef"

        doc = issue_challenge_document(
            store, pid, _config(), sign_fn, clock_ms=lambda: 1_000_050
        )
        payload = doc["payload"]
        # Broker/desktop-supplied facts copied verbatim.
        self.assertEqual(payload["request_nonce"], VALID_FIELDS["request_nonce"])
        self.assertEqual(payload["run_id"], "run-1")
        self.assertEqual(payload["task_id"], "task-1")
        self.assertEqual(payload["workspace_id"], "ws-1")
        self.assertEqual(payload["install_id"], "install-xyz")
        self.assertEqual(payload["system_sha256"], "a" * 64)
        self.assertEqual(payload["history_sha256"], "b" * 64)
        self.assertEqual(payload["generation_config_sha256"], "c" * 64)
        self.assertEqual(payload["requested_at_ms"], VALID_FIELDS["requested_at_ms"])
        self.assertEqual(payload["protocol"], CHALLENGE_PROTOCOL)
        # request_sha256 is AUTHORITY-recomputed, not caller-supplied.
        self.assertEqual(
            payload["request_sha256"],
            recompute_request_sha256(validate_create_pending(VALID_FIELDS)),
        )
        # Authority-owned fields from config.
        self.assertEqual(payload["challenge_key_id"], "key-2026-07")
        self.assertEqual(payload["supervisor_id"], "sup-1")
        # Clock-stamped, TTL-bounded.
        self.assertEqual(payload["challenge_issued_at_ms"], 1_000_050)
        self.assertEqual(
            payload["challenge_expires_at_ms"], 1_000_050 + MAX_CHALLENGE_TTL_MS
        )
        self.assertEqual(doc["sig"], "sig-deadbeef")
        self.assertIn(b"550e8400-e29b-41d4-a716-446655440000", signed_bytes["data"])

    def test_issue_persists_and_replays_byte_for_byte(self):
        store = PendingStore(id_fn=lambda: "pending-replay")
        pid, _ = self._create(store)

        sign_calls = {"n": 0}

        def sign_fn(_data):
            sign_calls["n"] += 1
            return "sig-%d" % sign_calls["n"]

        doc1 = issue_challenge_document(
            store, pid, _config(), sign_fn, clock_ms=lambda: NOW
        )
        # A repeat issue LATER (clock advanced, still within retention) must
        # re-return the STORED document byte-for-byte — never re-sign/re-stamp.
        doc2 = issue_challenge_document(
            store, pid, _config(), sign_fn, clock_ms=lambda: NOW + 40_000
        )
        self.assertEqual(sign_calls["n"], 1)  # signed EXACTLY once
        self.assertEqual(doc1, doc2)
        self.assertEqual(
            json.dumps(doc1, sort_keys=True), json.dumps(doc2, sort_keys=True)
        )
        # Never re-stamped: the challenge time is the first-issue time.
        self.assertEqual(doc2["payload"]["challenge_issued_at_ms"], NOW)
        self.assertEqual(doc2["sig"], "sig-1")

    def test_replay_survives_a_fresh_config_and_signer(self):
        # A lost-reply retry may reach a fresh authority instance; the replay is
        # the STORED bytes, independent of any new config/signer/clock.
        store = PendingStore(id_fn=lambda: "pending-2")
        pid, _ = self._create(store)
        doc1 = issue_challenge_document(store, pid, _config(), lambda b: "sig-A", lambda: NOW)
        doc2 = issue_challenge_document(
            store, pid,
            AuthorityConfig(challenge_key_id="OTHER-KEY", supervisor_id="OTHER-SUP"),
            lambda b: "sig-B",
            lambda: NOW + 1,
        )
        self.assertEqual(doc1, doc2)  # stored bytes win; no re-sign under new key

    def test_unknown_id_is_no_pending_row(self):
        store = PendingStore()
        with self.assertRaises(ChallengeAuthorityError) as cm:
            issue_challenge_document(store, "nope", _config(), lambda b: "s", lambda: NOW)
        self.assertEqual(cm.exception.reason, REASON_NO_PENDING_ROW)

    def test_expired_pending_row_is_pending_expired(self):
        store = PendingStore(id_fn=lambda: "pending-exp")
        pid, expires = self._create(store, now=NOW)  # pending_expires = NOW + 30000
        with self.assertRaises(ChallengeAuthorityError) as cm:
            issue_challenge_document(
                store, pid, _config(), lambda b: "s", clock_ms=lambda: expires + 1
            )
        self.assertEqual(cm.exception.reason, REASON_PENDING_EXPIRED)

    def test_pending_at_exact_ttl_boundary_still_issues(self):
        store = PendingStore(id_fn=lambda: "pending-b")
        pid, expires = self._create(store, now=NOW)
        # now == pending_expires_at_ms is NOT past expiry -> still issues.
        doc = issue_challenge_document(
            store, pid, _config(), lambda b: "s", clock_ms=lambda: expires
        )
        self.assertEqual(doc["payload"]["challenge_issued_at_ms"], expires)

    def test_retention_expired_issued_row_is_pending_expired(self):
        store = PendingStore(id_fn=lambda: "pending-ret")
        pid, _ = self._create(store, now=NOW)
        issue_challenge_document(store, pid, _config(), lambda b: "s", lambda: NOW)
        # issued_at == NOW; retention expires at NOW + ISSUED_RETENTION_MS.
        with self.assertRaises(ChallengeAuthorityError) as cm:
            issue_challenge_document(
                store, pid, _config(), lambda b: "s",
                clock_ms=lambda: NOW + ISSUED_RETENTION_MS + 1,
            )
        self.assertEqual(cm.exception.reason, REASON_PENDING_EXPIRED)

    def test_issued_row_at_exact_retention_boundary_still_replays(self):
        store = PendingStore(id_fn=lambda: "pending-ret2")
        pid, _ = self._create(store, now=NOW)
        first = issue_challenge_document(store, pid, _config(), lambda b: "s", lambda: NOW)
        replay = issue_challenge_document(
            store, pid, _config(), lambda b: "s",
            clock_ms=lambda: NOW + ISSUED_RETENTION_MS,
        )
        self.assertEqual(first, replay)

    def test_issue_rejects_tampered_row_with_invalid_fact(self):
        # Even if the store were tampered, issue re-validates before signing.
        tampered = dict(validate_create_pending(VALID_FIELDS))
        tampered["request_nonce"] = ""  # invalid stored value
        with self.assertRaises(ChallengeAuthorityError):
            issue_challenge(tampered, _config(), lambda b: "sig", lambda: 1)

    def test_ttl_cannot_exceed_cap(self):
        with self.assertRaises(ChallengeAuthorityError):
            AuthorityConfig(
                challenge_key_id="k",
                supervisor_id="s",
                challenge_ttl_ms=MAX_CHALLENGE_TTL_MS + 1,
            )


if __name__ == "__main__":
    unittest.main()
