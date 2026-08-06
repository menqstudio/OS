"""END-TO-END governed turn across all THREE trusted services (rev-30 §5 v2).

This is the offline counterpart of `engine/ci/live/run_live_turn.sh`. That script needs a real
Linux host — six service accounts, a setuid launcher, `sudo`, AF_UNIX + SO_PEERCRED — so it
cannot run on the Owner's Windows box or on the CI runner used for the engine leg. What CAN be
run everywhere, and is run here, is the whole cryptographic chain in one process:

    challenge-authority  --(signed brops.governed-turn-challenge.v1)-->
    supervisor (+ its DURABLE ledger on a real file)  --(brops.run-attestation.v1)-->
    isolated signer  --(brops.governed-receipt-envelope.v1)-->  final acceptance

with THREE distinct REAL Ed25519 keypairs (challenge / supervisor-attestation / receipt), the
real modules — no mocked verifier, no stand-in signature — and the supervisor's ledger on a
temporary FILE so the run survives a simulated **supervisor restart** between execution and
attestation.

**Why this exists.** The independent audit's F-01 was not a bug inside one function; it was a
missing binding BETWEEN services: the supervisor signed facts the broker chose. A test that
exercises one module cannot see that. This one walks the whole protocol and then asserts the
property directly — *a run the supervisor did not authorize and watch terminate cannot be
attested, and therefore cannot become a signed receipt.*

**What this does NOT cover** (still requires the Linux kit, and must not be read as covered):
the OS trust boundary itself — SO_PEERCRED peer auth, the four separate uids, key custody file
modes — and the privileged recorder → setuid launcher → contained executor spawn. Here the
"execution" is the test writing the reply bytes into the content-addressed store. So this proves
the PROTOCOL and the CRYPTO, not the ISOLATION.
"""

import hashlib
import json
import os
import pathlib
import sqlite3
import sys
import tempfile
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

import governed_supervisor_ledger as gsl  # noqa: E402
from challenge_authority import (  # noqa: E402
    AuthorityConfig,
    _canonical_bytes as authority_canonical_bytes,
    issue_challenge,
)
from governed_supervisor import (  # noqa: E402
    SupervisorConfig,
    _canonical_bytes as supervisor_canonical_bytes,
    recompute_request_sha256 as supervisor_recompute_request_sha256,
)
from governed_supervisor_server import (  # noqa: E402
    OP_ACCEPT_OPEN,
    OP_ATTEST_RUN,
    OP_COMPLETE_RUN,
    OP_EXECUTION_STARTED,
    OP_LAUNCH_GATE,
    REFUSE_NO_TERMINAL_RUN,
    ServerError,
    dispatch,
)
from isolated_signer import (  # noqa: E402
    ENVELOPE_ARTIFACT_TYPE,
    REFUSAL_ARTIFACT_TYPE,
    ArtifactStore,
    IsolatedSigner,
    SignerConfig,
)

NOW = 1_700_000_000_000

CHALLENGE_KEY_ID = "chal-key-e2e"
SUP_ATTEST_KEY_ID = "sup-attest-key-e2e"
RECEIPT_KEY_ID = "receipt-key-e2e"

SUPERVISOR_ID = "e2e-supervisor"
EXECUTOR_ID = "e2e-executor"
BUILDER_ID = "e2e-builder"

REPLY_BYTES = b"the exact governed reply bytes the executor produced"


def _b64u(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64u(text: str) -> bytes:
    import base64

    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _Key:
    """One REAL Ed25519 keypair, exposed as the sign/verify seams the services take."""

    def __init__(self):
        self._sk = Ed25519PrivateKey.generate()
        self._pk = self._sk.public_key()

    def sign(self, message: bytes) -> str:
        return _b64u(self._sk.sign(message))

    def verify(self, message: bytes, sig_b64: str) -> bool:
        try:
            self._pk.verify(_unb64u(sig_b64), message)
            return True
        except Exception:
            return False


class GovernedChainE2E(unittest.TestCase):
    """One test class, one full chain, driven step by step so a failure names the hop."""

    def setUp(self):
        # ---- three DISTINCT real keypairs: the point of the split-key design ----
        self.challenge_key = _Key()
        self.attest_key = _Key()
        self.receipt_key = _Key()
        self.assertNotEqual(
            self.challenge_key.sign(b"x"), self.attest_key.sign(b"x"),
            "the three services must hold genuinely different keys",
        )

        # ---- the content-addressed protected store the signer reads ----
        self.store = ArtifactStore()
        self.handles = {
            name: self.store.put(data)
            for name, data in {
                "system": b"you are a governed agent",
                "history": b'[{"content":"hi","role":"user"}]',
                "generation_config": b'{"temperature":0}',
                "policy_bundle": b"policy-bundle-bytes",
                "containment": b'{"containment":"ok"}',
                "record": b'{"terminal_record":"COMPLETED"}',
                "lease": b'{"lease":"signed-lease-payload"}',
                "execution_receipt": b'{"execution_receipt":"ok"}',
            }.items()
        }

        # ---- the supervisor's DURABLE ledger, on a real file (restart-survivable) ----
        self._tmpdir = tempfile.mkdtemp(prefix="brops-e2e-")
        self.ledger_path = os.path.join(self._tmpdir, "supervisor-ledger.db")
        self.ledger_conn = self._open_ledger()
        self.addCleanup(self._cleanup)

        # ---- service configs ----
        self.authority_config = AuthorityConfig(
            challenge_key_id=CHALLENGE_KEY_ID, supervisor_id=SUPERVISOR_ID
        )
        self.supervisor_config = SupervisorConfig(
            launcher_executable_sha256="1" * 64,
            executor_executable_sha256="2" * 64,
            id_fn=self._mint_id,
            supervisor_id=SUPERVISOR_ID,
            executor_id=EXECUTOR_ID,
            builder_id=BUILDER_ID,
            policy_id="e2e-policy",
            policy_version="1",
            policy_bundle_handle=self.handles["policy_bundle"],
            challenge_registry_handle=_sha256_hex(b"challenge-registry"),
            challenge_registry_hash=_sha256_hex(b"manifest"),
            challenge_registry_epoch=2,
            challenge_registry_root_key_id="e2e-root-1",
        )
        self._minted = 0

    def _mint_id(self):
        self._minted += 1
        return "e2e-id-%04d" % self._minted

    def _open_ledger(self):
        conn = sqlite3.connect(self.ledger_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        gsl.apply_schema(conn)
        return conn

    def _cleanup(self):
        try:
            self.ledger_conn.close()
        except sqlite3.Error:
            pass

    # -- the three services ------------------------------------------------

    def _issue_challenge(self, nonce="550e8400-e29b-41d4-a716-446655440000"):
        """Hop 1: the challenge authority signs the turn facts the broker submitted."""
        row = {
            "run_id": "e2e-run-1",
            "task_id": "e2e-task-1",
            "workspace_id": "e2e-ws-1",
            "install_id": "e2e-install-1",
            "request_nonce": nonce,
            "system_sha256": self.handles["system"],
            "history_sha256": self.handles["history"],
            "generation_config_sha256": self.handles["generation_config"],
            "requested_at_ms": NOW - 5_000,
        }
        return issue_challenge(
            row, self.authority_config, self.challenge_key.sign, lambda: NOW
        )

    def _supervisor(self, request, now=NOW):
        """Hops 2–5: the supervisor front door over its durable ledger."""
        return dispatch(
            request,
            self.supervisor_config,
            # REAL verification: the challenge key, over the canonical bytes the SUPERVISOR
            # reassembles from the payload itself. If governed_supervisor._canonical_bytes and
            # challenge_authority._canonical_bytes ever diverged, this hop would fail here.
            lambda message, sig: self.challenge_key.verify(message, sig),
            supervisor_recompute_request_sha256,
            lambda: now,
            conn=self.ledger_conn,
            sign_attestation=self.attest_key.sign,
            supervisor_attestation_key_id=SUP_ATTEST_KEY_ID,
        )

    def _signer(self):
        """Hop 6: the isolated signer, holding the receipt key behind its own seam."""
        config = SignerConfig(
            receipt_key_id=RECEIPT_KEY_ID,
            receipt_private_key_handle="kms://receipt",
            supervisor_attestation_key_id=SUP_ATTEST_KEY_ID,
            supervisor_attestation_key_handle="kms://sup-attest",
            allowed_executor_ids={EXECUTOR_ID},
            allowed_builder_ids={BUILDER_ID},
            allowed_supervisor_ids={SUPERVISOR_ID},
        )
        return IsolatedSigner(
            config=config,
            store=self.store,
            sign_fn=lambda _handle, message: self.receipt_key.sign(message),
            verify_attestation=lambda _handle, message, sig: self.attest_key.verify(message, sig),
            clock_ms=lambda: NOW,
        )

    # -- the full lifecycle ------------------------------------------------

    def _run_turn(self, nonce="550e8400-e29b-41d4-a716-446655440000", output=REPLY_BYTES):
        """accept-open → launch-gate → (execution) → execution-started → complete-run.
        Returns (attempt_id, output_handle)."""
        challenge = self._issue_challenge(nonce)
        accepted = self._supervisor({"op": OP_ACCEPT_OPEN, "challenge_doc": challenge})
        self.assertTrue(accepted["ok"], accepted)
        attempt = accepted["lease"]["execution_attempt_id"]

        gate = self._supervisor({"op": OP_LAUNCH_GATE, "execution_attempt_id": attempt})
        self.assertTrue(gate["ok"], gate)
        self.assertTrue(gate["proceed"])

        started = self._supervisor({
            "op": OP_EXECUTION_STARTED, "execution_attempt_id": attempt,
            "process_group_id": "4242", "cgroup_id": "cg-e2e",
            "execution_started_marker": None,
        })
        self.assertTrue(started["ok"], started)

        # "Execution": in the Linux kit this is the recorder → setuid launcher → contained
        # executor. Here the reply bytes are simply content-addressed into the store.
        output_handle = self.store.put(output)

        completed = self._supervisor({
            "op": OP_COMPLETE_RUN, "execution_attempt_id": attempt,
            "produced": {
                "output_handle": output_handle,
                "containment_evidence_handle": self.handles["containment"],
                "record_handle": self.handles["record"],
                "lease_handle": self.handles["lease"],
                "execution_receipt_handle": self.handles["execution_receipt"],
                "completed_at_ms": NOW,
                "evidence_final_event_hash": _sha256_hex(b"evidence-head-1"),
                "evidence_event_count": 3,
                "evidence_last_sequence": 3,
                "evidence_head_sequence": 7,
            },
        })
        self.assertTrue(completed["ok"], completed)
        return attempt, output_handle

    def _attest(self, attempt, run_id="e2e-run-1"):
        return self._supervisor(
            {"op": OP_ATTEST_RUN, "run_id": run_id, "execution_attempt_id": attempt}
        )

    def _sign(self, attestation_reply):
        evidence_jcs = _unb64u(attestation_reply["evidence_jcs_b64"])
        return evidence_jcs, self._signer().sign_result({
            "protocol": "brops.sign-request.v1",
            "attestation": attestation_reply["attestation"],
            # The broker parses the evidence FROM the attested bytes rather than rebuilding it,
            # so what the signer validates is what the supervisor signed, by construction.
            "evidence": json.loads(evidence_jcs.decode("utf-8")),
        })

    # -- tests -------------------------------------------------------------

    def test_full_chain_produces_a_verifiable_receipt_envelope(self):
        attempt, output_handle = self._run_turn()

        # ---- SUPERVISOR RESTART between execution and attestation ----------------
        # The whole point of F-01 is that the attestation rests on state the supervisor
        # durably owns. Drop the connection and reopen the file: if any of it lived in
        # process memory, the attestation below would be impossible.
        self.ledger_conn.close()
        self.ledger_conn = self._open_ledger()

        attn = self._attest(attempt)
        self.assertTrue(attn["ok"], attn)
        evidence_jcs, result = self._sign(attn)
        self.assertEqual(result["artifact_type"], ENVELOPE_ARTIFACT_TYPE, result)
        self.assertEqual(result["status"], "signed")

        payload = result["payload"]
        signature = result["signature_b64"]

        # ---- the final-acceptance checks the broker performs (governed_verification.rs) ----
        # (1) the receipt signature verifies under the pinned receipt key over JCS(payload)
        self.assertTrue(
            self.receipt_key.verify(supervisor_canonical_bytes(payload), signature),
            "the envelope signature must verify over the canonical payload bytes",
        )
        # (2) the attestation digest in the envelope commits to the exact attested bytes
        self.assertEqual(payload["attestation_evidence_sha256"], _sha256_hex(evidence_jcs))
        # (3) the supervisor's signature over those bytes verifies under the attestation key
        self.assertTrue(
            self.attest_key.verify(evidence_jcs, attn["attestation"]["sig"])
        )
        # (4) the output is bound by digest AND length to the bytes "execution" produced
        self.assertEqual(payload["output_sha256"], output_handle)
        self.assertEqual(payload["output_sha256"], _sha256_hex(REPLY_BYTES))
        self.assertEqual(payload["output_bytes"], len(REPLY_BYTES))
        # (5) request_sha256 re-derives from the same canonical envelope both ends compute
        self.assertEqual(
            payload["request_sha256"],
            supervisor_recompute_request_sha256({
                "workspace_id": "e2e-ws-1",
                "install_id": "e2e-install-1",
                "request_nonce": "550e8400-e29b-41d4-a716-446655440000",
                "system_sha256": self.handles["system"],
                "history_sha256": self.handles["history"],
                "generation_config_sha256": self.handles["generation_config"],
                "requested_at_ms": NOW - 5_000,
            }),
        )
        # (6) the identities are the SUPERVISOR's, and the receipt_id was minted by it
        self.assertEqual(payload["execution_attempt_id"], attempt)
        self.assertEqual(payload["run_id"], "e2e-run-1")
        self.assertEqual(payload["supervisor_attestation_key_id"], SUP_ATTEST_KEY_ID)
        self.assertEqual(payload["key_id"], RECEIPT_KEY_ID)
        self.assertTrue(payload["receipt_id"].startswith("e2e-id-"))

    def test_the_authority_and_the_supervisor_agree_on_canonical_bytes(self):
        # A silent divergence between the two `_canonical_bytes` implementations would make
        # every challenge signature fail — or, worse, make the supervisor verify different
        # bytes than were signed. Pin the agreement explicitly.
        challenge = self._issue_challenge()
        payload = challenge["payload"]
        self.assertEqual(
            authority_canonical_bytes(payload), supervisor_canonical_bytes(payload)
        )
        self.assertTrue(
            self.challenge_key.verify(supervisor_canonical_bytes(payload), challenge["sig"])
        )

    # ---- F-01: the attack the audit demonstrated, replayed against the fix ----

    def test_a_fabricated_run_cannot_be_attested_or_signed(self):
        """The audit's F-01 attack, end to end.

        The broker uid writes whatever reply bytes it likes into the store (it legitimately
        can — it is the party that content-addresses real output), then asks for an attestation
        naming a run that never happened. Before the fix this produced a genuine signed
        envelope. Now there is no acceptance row, so there is nothing to attest, and no
        argument through which the missing facts could be supplied.
        """
        forged_output = self.store.put(b"a reply no governed execution ever produced")
        self.assertIsNotNone(self.store.read_verified(forged_output))  # it IS in the store

        refusal = self._attest("attempt-that-never-existed", run_id="run-that-never-existed")
        self.assertFalse(refusal["ok"])
        self.assertEqual(refusal["reason"], REFUSE_NO_TERMINAL_RUN)
        self.assertNotIn("attestation", refusal)
        self.assertNotIn("evidence_jcs_b64", refusal)

    def test_the_old_facts_door_no_longer_exists(self):
        """The pre-fix request shape is refused outright, not silently ignored."""
        attempt, _ = self._run_turn()
        with self.assertRaises(ServerError) as caught:
            self._supervisor({
                "op": OP_ATTEST_RUN, "run_id": "e2e-run-1", "execution_attempt_id": attempt,
                "facts": {"output_handle": "9" * 64, "receipt_id": "attacker-chosen"},
            })
        self.assertIn("facts", str(caught.exception))

    def test_an_unfinished_run_cannot_be_attested(self):
        challenge = self._issue_challenge()
        accepted = self._supervisor({"op": OP_ACCEPT_OPEN, "challenge_doc": challenge})
        attempt = accepted["lease"]["execution_attempt_id"]
        self._supervisor({"op": OP_LAUNCH_GATE, "execution_attempt_id": attempt})
        # Leased and gated, but never started or completed.
        refusal = self._attest(attempt)
        self.assertFalse(refusal["ok"])
        self.assertEqual(refusal["reason"], REFUSE_NO_TERMINAL_RUN)

    def test_a_replayed_challenge_yields_one_attempt_and_one_receipt(self):
        challenge = self._issue_challenge()
        first = self._supervisor({"op": OP_ACCEPT_OPEN, "challenge_doc": challenge})
        second = self._supervisor({"op": OP_ACCEPT_OPEN, "challenge_doc": challenge})
        self.assertEqual(first["lease"], second["lease"])
        rows = self.ledger_conn.execute(
            "SELECT COUNT(*) FROM governed_turn_acceptance"
        ).fetchone()[0]
        self.assertEqual(rows, 1, "a replayed signed challenge must not mint a second attempt")

    def test_the_same_terminal_run_attests_to_the_identical_envelope(self):
        attempt, _ = self._run_turn()
        a_evidence, a_result = self._sign(self._attest(attempt))
        b_evidence, b_result = self._sign(self._attest(attempt))
        self.assertEqual(a_evidence, b_evidence)
        self.assertEqual(a_result["payload"], b_result["payload"])
        self.assertEqual(a_result["signature_b64"], b_result["signature_b64"])

    def test_a_second_execution_cannot_rewrite_what_was_attested(self):
        attempt, first_handle = self._run_turn()
        attested_before, _ = self._sign(self._attest(attempt))

        # Produce different bytes and try to re-report them for the SAME attempt.
        other_handle = self.store.put(b"different bytes, same attempt")
        refusal = self._supervisor({
            "op": OP_COMPLETE_RUN, "execution_attempt_id": attempt,
            "produced": {
                "output_handle": other_handle,
                "containment_evidence_handle": self.handles["containment"],
                "record_handle": self.handles["record"],
                "lease_handle": self.handles["lease"],
                "execution_receipt_handle": self.handles["execution_receipt"],
                "completed_at_ms": NOW,
                "evidence_final_event_hash": _sha256_hex(b"evidence-head-1"),
                "evidence_event_count": 3,
                "evidence_last_sequence": 3,
                "evidence_head_sequence": 7,
            },
        })
        self.assertFalse(refusal["ok"])
        attested_after, _ = self._sign(self._attest(attempt))
        self.assertEqual(attested_before, attested_after,
                         "the attested evidence must be immutable once recorded")

    def test_a_stale_evidence_head_refuses_the_completion(self):
        # Advance the floor with a real turn, then run a second turn presenting an OLDER head.
        self._run_turn()
        challenge = self._issue_challenge(nonce="6ba7b810-9dad-11d1-80b4-00c04fd430c8")
        accepted = self._supervisor({"op": OP_ACCEPT_OPEN, "challenge_doc": challenge})
        attempt = accepted["lease"]["execution_attempt_id"]
        self._supervisor({"op": OP_LAUNCH_GATE, "execution_attempt_id": attempt})
        self._supervisor({
            "op": OP_EXECUTION_STARTED, "execution_attempt_id": attempt,
            "process_group_id": "4243", "cgroup_id": "cg-e2e",
            "execution_started_marker": None,
        })
        refusal = self._supervisor({
            "op": OP_COMPLETE_RUN, "execution_attempt_id": attempt,
            "produced": {
                "output_handle": self.store.put(b"rolled-back run"),
                "containment_evidence_handle": self.handles["containment"],
                "record_handle": self.handles["record"],
                "lease_handle": self.handles["lease"],
                "execution_receipt_handle": self.handles["execution_receipt"],
                "completed_at_ms": NOW,
                "evidence_final_event_hash": _sha256_hex(b"evidence-head-OLD"),
                "evidence_event_count": 2,
                "evidence_last_sequence": 2,
                "evidence_head_sequence": 6,   # BELOW the floor the first turn established
            },
        })
        self.assertFalse(refusal["ok"])
        self.assertEqual(refusal["reason"], "stale_evidence")
        self.assertFalse(self._attest(attempt)["ok"])

    def test_a_tampered_output_blob_breaks_the_signed_binding(self):
        # The signer DERIVES output_sha256/output_bytes from the store bytes, so an envelope
        # can never name output the store does not hold.
        attempt, output_handle = self._run_turn()
        attn = self._attest(attempt)
        _evidence, result = self._sign(attn)
        self.assertEqual(result["payload"]["output_sha256"], output_handle)

        # Remove the blob and the signer refuses rather than signing an unresolvable handle.
        self.store._blobs.pop(output_handle, None)  # noqa: SLF001 - test reaches into the fake
        _evidence2, refused = self._sign(attn)
        self.assertEqual(refused["artifact_type"], REFUSAL_ARTIFACT_TYPE)

    def test_a_challenge_for_another_supervisor_is_refused(self):
        other_authority = AuthorityConfig(
            challenge_key_id=CHALLENGE_KEY_ID, supervisor_id="some-other-supervisor"
        )
        row = {
            "run_id": "e2e-run-1", "task_id": "e2e-task-1", "workspace_id": "e2e-ws-1",
            "install_id": "e2e-install-1",
            "request_nonce": "6ba7b811-9dad-11d1-80b4-00c04fd430c8",
            "system_sha256": self.handles["system"],
            "history_sha256": self.handles["history"],
            "generation_config_sha256": self.handles["generation_config"],
            "requested_at_ms": NOW - 5_000,
        }
        challenge = issue_challenge(
            row, other_authority, self.challenge_key.sign, lambda: NOW
        )
        reply = self._supervisor({"op": OP_ACCEPT_OPEN, "challenge_doc": challenge})
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["reason"], "supervisor_mismatch")


if __name__ == "__main__":
    unittest.main()
