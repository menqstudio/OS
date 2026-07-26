from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = pathlib.Path(__file__).resolve().parents[1]
for sub in ("runtime", "tools"):
    sys.path.insert(0, str(ROOT / sub))

from bro_signature import canonical_bytes
from brops_challenge_authority import AuthorityConfig, ChallengeAuthority
from brops_governed_common import (
    DEFAULT_GENERATION_CONFIG, ISSUED_RETENTION_MS, PINNED_GENERATION_CONFIG_SHA256,
    b64url_decode, generation_config_sha256, request_sha256,
)


class ChallengeAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        priv = Ed25519PrivateKey.generate()
        self.pub = priv.public_key()
        private_hex = priv.private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        ).hex()
        self.now = 1_800_000_000_000
        self.auth = ChallengeAuthority(
            pathlib.Path(self.tmp.name) / "authority.db",
            AuthorityConfig("sup", "ws", "install", "challenge-k1", private_hex),
            clock_ms=lambda: self.now,
        )

    def tearDown(self):
        self.auth.close(); self.tmp.cleanup()

    def frame(self, nonce="nonce-1"):
        return {
            "protocol": "brops.governed-challenge-create-pending.v1",
            "run_id": "run-1", "task_id": "task-1", "workspace_id": "ws",
            "install_id": "install", "request_nonce": nonce,
            "system_sha256": "1" * 64, "history_sha256": "2" * 64,
            "generation_config_sha256": PINNED_GENERATION_CONFIG_SHA256,
            "requested_at_ms": self.now - 1,
        }

    def test_pinned_config_hash_and_identity_formula(self):
        self.assertEqual(generation_config_sha256(DEFAULT_GENERATION_CONFIG), PINNED_GENERATION_CONFIG_SHA256)

    def test_create_issue_and_byte_identical_replay(self):
        created = self.auth.handle(self.frame())
        self.assertEqual(created["status"], "created")
        again = self.auth.handle(self.frame())
        self.assertEqual(again["pending_challenge_id"], created["pending_challenge_id"])
        issued = self.auth.handle({
            "protocol": "brops.governed-challenge-issue.v1",
            "pending_challenge_id": created["pending_challenge_id"],
        })
        self.assertEqual(issued["status"], "issued")
        replay = self.auth.handle({
            "protocol": "brops.governed-challenge-issue.v1",
            "pending_challenge_id": created["pending_challenge_id"],
        })
        self.assertEqual(issued["challenge_document_b64"], replay["challenge_document_b64"])
        doc = json.loads(b64url_decode(issued["challenge_document_b64"]).decode("utf-8"))
        self.pub.verify(b64url_decode(doc["sig"]), canonical_bytes(doc["payload"]))
        expected = request_sha256(
            workspace_id="ws", install_id="install", request_nonce="nonce-1",
            system_sha256="1" * 64, history_sha256="2" * 64,
            generation_config_sha256=PINNED_GENERATION_CONFIG_SHA256,
            requested_at_ms=self.now - 1,
        )
        self.assertEqual(doc["payload"]["request_sha256"], expected)

    def test_request_sha_is_not_caller_supplied(self):
        f = self.frame(); f["request_sha256"] = "0" * 64
        self.assertEqual(self.auth.handle(f)["reason"], "malformed")

    def test_conflicting_retry_and_quota(self):
        a = self.auth.handle(self.frame("n1")); self.assertEqual(a["status"], "created")
        conflict = self.frame("n1"); conflict["task_id"] = "different"
        self.assertEqual(self.auth.handle(conflict)["reason"], "retry_conflict")
        self.assertEqual(self.auth.handle(self.frame("n2"))["status"], "created")
        self.assertEqual(self.auth.handle(self.frame("n3"))["reason"], "quota_pending")

    def test_pending_and_issued_retention_are_distinct(self):
        p = self.auth.handle(self.frame("pending"))
        i = self.auth.handle(self.frame("issued"))
        self.auth.handle({"protocol": "brops.governed-challenge-issue.v1", "pending_challenge_id": i["pending_challenge_id"]})
        self.now += 30_001
        self.assertEqual(self.auth.handle({"protocol": "brops.governed-challenge-issue.v1", "pending_challenge_id": p["pending_challenge_id"]})["reason"], "pending_expired")
        self.assertEqual(self.auth.handle({"protocol": "brops.governed-challenge-issue.v1", "pending_challenge_id": i["pending_challenge_id"]})["status"], "issued")
        self.now += ISSUED_RETENTION_MS + 1
        self.auth.sweep()
        self.assertEqual(self.auth.handle({"protocol": "brops.governed-challenge-issue.v1", "pending_challenge_id": i["pending_challenge_id"]})["reason"], "no_pending_row")

    def test_present_but_retention_expired_issued_is_pending_expired(self):
        # §2.1.1(d): a physically-present but retention-expired ISSUED row (NOT yet swept) must
        # refuse with `pending_expired`, not the swept-case `no_pending_row`.
        i = self.auth.handle(self.frame("issued2"))
        self.auth.handle({"protocol": "brops.governed-challenge-issue.v1", "pending_challenge_id": i["pending_challenge_id"]})
        self.now += ISSUED_RETENTION_MS + 1  # advance past retention but DO NOT sweep
        refused = self.auth.handle({"protocol": "brops.governed-challenge-issue.v1", "pending_challenge_id": i["pending_challenge_id"]})
        self.assertEqual(refused["reason"], "pending_expired")
        # Once the row is physically swept, the swept case ⇒ no_pending_row.
        self.auth.sweep()
        gone = self.auth.handle({"protocol": "brops.governed-challenge-issue.v1", "pending_challenge_id": i["pending_challenge_id"]})
        self.assertEqual(gone["reason"], "no_pending_row")

    def test_oversize_issue_frame_is_malformed_not_oversize(self):
        # `oversize` is not a member of the issue-result refused enum (§2.1 (B)); an oversize
        # ISSUE frame must be answered with the in-set `malformed`.
        big = {"protocol": "brops.governed-challenge-issue.v1", "pending_challenge_id": "x" * 5000}
        refused = self.auth.handle(big)
        self.assertEqual(refused["reason"], "malformed")

    def test_generation_config_rejects_noncanonical_numbers(self):
        from brops_governed_common import validate_generation_config, GovernedProtocolError
        bad = dict(DEFAULT_GENERATION_CONFIG)
        for key, value in [
            ("temperature", "1e0"), ("temperature", "-0.00"),
            ("temperature", "1.0"), ("temperature", "2.01"),
            ("top_p", "1.01"), ("max_output_tokens", "0256"),
            ("max_output_tokens", "1048577"),
        ]:
            candidate = dict(bad); candidate[key] = value
            with self.assertRaises(GovernedProtocolError):
                validate_generation_config(candidate)


if __name__ == "__main__":
    unittest.main()
