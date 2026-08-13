"""The staging handle and the acceptance handle are the SAME digest — rev-30 CORRECTION.

Why this file exists at all
---------------------------
rev-30 defined ``challenge_handle`` twice and differently. §3's artifact matrix, §4.10(a0)
and Appendix B's handle matrix all say ``SHA256(JCS({payload, sig}))``; §5's summary table
said ``SHA256(JCS(payload))`` — the payload ALONE — and the shipped ``accept_open`` computed
that. The §4.10(a0) open path implemented the §3 form. So for ONE turn the staging row's
handle and the acceptance row's handle were digests of DIFFERENT byte strings, and §4.10(d)
(NOT IMPLEMENTED — a later ordered piece) could never join them on
``(install_id, request_nonce, challenge_handle)``.

The Architect declared §3/§4.10(a0)/Appendix B normative; ``accept_open`` and §5's table were
corrected (``docs/OWNER_ACTION_REQUIRED.md`` §1c). This file is the executable form of that
ruling. It drives BOTH REAL production entry points — ``governed_turn_open.handle_open``
(§4.10(a0)) and ``governed_supervisor.accept_open`` (§5) — over ONE real signed challenge
document, into ONE real ledger, and asserts the two persisted rows carry the SAME handle.

It fails if EITHER side reverts. That is deliberate and symmetric: the agreement is a
property of the pair, and a test that only pinned one side would let the other drift back.

No prerequisite here is optional. Everything is stdlib plus repo modules, imported at module
scope with no ``try``/``except`` and no ``skipIf``, so a missing prerequisite is an
unmissable hard error rather than a green run with a quiet skip. (There is no
``BROPS_TEST_MISSING_PREREQUISITES`` declaration anywhere in this tree, so nothing is
declared in it and nothing here may be softened.)
"""

import base64
import dataclasses
import hashlib
import hmac
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

import challenge_key_registry as ckr  # noqa: E402
import governed_staging_ledger as gsl  # noqa: E402
import governed_supervisor_ledger as gsupl  # noqa: E402
import governed_turn_open as gto  # noqa: E402
from governed_supervisor import (  # noqa: E402
    CHALLENGE_PROTOCOL,
    Accepted,
    SupervisorConfig,
    accept_open,
    challenge_handle_for,
    recompute_request_sha256,
)

# ---------------------------------------------------------------------------
# One challenge, built once, used by both paths.
# ---------------------------------------------------------------------------

CHALLENGE_KEY = b"test-challenge-signing-key-not-a-secret"
ROOT_KEY = b"test-registry-root-key-not-a-secret"

SIDECAR_UID = 4101
ROOT_KEY_ID = "chal-root-1"
ROOT_PUBLIC_KEY = "R" * 43
CHALLENGE_KEY_ID = "chal-key-2026-07"
CHALLENGE_PUBLIC_KEY = "K" * 43

NOW = 1_700_000_100_000
TTL = 30_000


def _canonical(obj) -> bytes:
    """The governed family's encoding — the exact bytes the challenge authority signs."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _mac(key: bytes, message: bytes) -> str:
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def _verify_challenge_sig(message: bytes, sig: str, public_key: str) -> bool:
    return hmac.compare_digest(_mac(CHALLENGE_KEY + public_key.encode("ascii"), message), sig)


def _verify_root_sig(message: bytes, sig: str, public_key: str) -> bool:
    return hmac.compare_digest(_mac(ROOT_KEY + public_key.encode("ascii"), message), sig)


def _payload(*, nonce="nonce-agreement-1", install_id="install-1"):
    payload = {
        "protocol": CHALLENGE_PROTOCOL,
        "challenge_key_id": CHALLENGE_KEY_ID,
        "run_id": "run-1",
        "task_id": "task-1",
        "workspace_id": "ws-1",
        "install_id": install_id,
        "supervisor_id": "sup-1",
        "request_nonce": nonce,
        "system_sha256": "a" * 64,
        "history_sha256": "b" * 64,
        "generation_config_sha256": "c" * 64,
        "request_sha256": "",
        "requested_at_ms": 1_700_000_000_000,
        "challenge_issued_at_ms": NOW,
        "challenge_expires_at_ms": NOW + TTL,
    }
    payload["request_sha256"] = recompute_request_sha256(payload)
    return payload


def _document(payload):
    """The EXACT signed ``{payload, sig}`` document — the one artifact both paths consume."""
    sig = _mac(CHALLENGE_KEY + CHALLENGE_PUBLIC_KEY.encode("ascii"), _canonical(payload))
    return {"payload": payload, "sig": sig}


def _registry_document():
    payload = {
        "artifact_type": ckr.REGISTRY_ARTIFACT_TYPE,
        "root_key_id": ROOT_KEY_ID,
        "registry_epoch": 7,
        "registry_issued_at_ms": 1_600_000_000_000,
        "keys": [{
            "challenge_key_id": CHALLENGE_KEY_ID,
            "public_key": CHALLENGE_PUBLIC_KEY,
            "valid_from_ms": 1,
            "valid_to_ms": 2_000_000_000_000,
            "key_epoch": 2,
            "revoked": False,
            "revoked_at_ms": None,
        }],
    }
    root_sig = _mac(ROOT_KEY + ROOT_PUBLIC_KEY.encode("ascii"), _canonical(payload))
    return {"payload": payload, "root_sig": root_sig}


def _supervisor_config():
    ids = iter("id-%d" % i for i in range(1, 100))
    return SupervisorConfig(
        launcher_executable_sha256="1" * 64,
        executor_executable_sha256="2" * 64,
        id_fn=lambda: next(ids),
        supervisor_id="sup-1",
        executor_id="exec-1",
        builder_id="builder-1",
        policy_id="policy-1",
        policy_version="v1",
        policy_bundle_handle="e" * 64,
        challenge_registry_handle="reg-handle",
        challenge_registry_hash="reg-hash",
        challenge_registry_epoch=7,
        challenge_registry_root_key_id=ROOT_KEY_ID,
    )


class _Store:
    """A real content-addressed store: the handle IS the digest of the bytes written."""

    def __init__(self):
        self.blobs = {}

    def publish(self, data: bytes) -> str:
        handle = hashlib.sha256(data).hexdigest()
        self.blobs.setdefault(handle, data)
        return handle


class ChallengeHandleAgreementTests(unittest.TestCase):
    """§4.10(a0) staging and §5 acceptance address ONE document with ONE digest."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # ONE ledger file: `open_ledger` applies the shared DDL, which creates BOTH the
        # §2.4 staging table and the §5 acceptance table. So the two rows compared below
        # are neighbours in the same database, exactly where the join will look for them.
        self.conn = gsupl.open_ledger(str(pathlib.Path(self.tmp.name) / "sup.db"))
        self.addCleanup(self.conn.close)
        self.store = _Store()

        self.payload = _payload()
        self.document = _document(self.payload)
        self.document_bytes = _canonical(self.document)

    # -- the two real paths, each returning what it durably recorded ------------

    def _staging_handle(self):
        """Drive the REAL §4.10(a0) open and return the handle its ROW carries."""
        doc_b64 = base64.urlsafe_b64encode(self.document_bytes).decode("ascii").rstrip("=")
        request = {
            "protocol": gto.OPEN_PROTOCOL,
            "install_id": self.payload["install_id"],
            "request_nonce": self.payload["request_nonce"],
            "challenge_doc_b64": doc_b64,
        }
        reply = gto.handle_open(
            request,
            peer_uid=SIDECAR_UID,
            allowed_sidecar_uid=SIDECAR_UID,
            config=gto.OpenConfig.from_supervisor_config(
                _supervisor_config(), registry_root_public_key=ROOT_PUBLIC_KEY,
            ),
            conn=self.conn,
            publish_document=self.store.publish,
            resolve_registry_document=_registry_document,
            verify_root_sig=_verify_root_sig,
            verify_challenge_sig=_verify_challenge_sig,
            clock_ms=lambda: NOW,
        )
        self.assertEqual(reply.get("status"), gto.STATUS_OPENED, reply)
        row = gsl.load_staging(self.conn, self.payload["install_id"],
                               self.payload["request_nonce"])
        self.assertIsNotNone(row, "the open reported `opened` but wrote no staging row")
        # The reply and the durable row must agree before either is compared to §5.
        self.assertEqual(reply["challenge_handle"], row["challenge_handle"])
        return row["challenge_handle"]

    def _acceptance_handle(self):
        """Drive the REAL §5 acceptance and return the handle its ROW carries."""
        result = accept_open(
            self.document,
            NOW,
            config=_supervisor_config(),
            verify_sig=lambda message, sig: _verify_challenge_sig(
                message, sig, CHALLENGE_PUBLIC_KEY),
            recompute_request_sha256=recompute_request_sha256,
        )
        self.assertIsInstance(result, Accepted, result)
        _outcome, row = gsupl.reuse_or_prepare(self.conn, result.acceptance, NOW)
        self.assertEqual(result.acceptance.challenge_handle, row["challenge_handle"])
        return row["challenge_handle"]

    # -- the property -----------------------------------------------------------

    def test_staging_row_and_acceptance_row_carry_the_same_challenge_handle(self):
        """THE test. One document, both real paths, one digest.

        This is the assertion the correction exists to make true. Before it, the two sides
        hashed different byte strings and this equality was false for every turn.
        """
        staging_handle = self._staging_handle()
        acceptance_handle = self._acceptance_handle()
        self.assertEqual(
            staging_handle, acceptance_handle,
            "the staging row and the acceptance row disagree about challenge_handle for "
            "ONE document — a lookup by (install_id, request_nonce, challenge_handle) "
            "cannot join them",
        )
        # And the joined-on triple really does select exactly this pair.
        by_handle = gsl.load_staging_by_handle(self.conn, acceptance_handle)
        self.assertIsNotNone(by_handle, "the acceptance handle resolves no staging row")
        self.assertEqual(by_handle["install_id"], self.payload["install_id"])
        self.assertEqual(by_handle["request_nonce"], self.payload["request_nonce"])

    def test_both_rows_carry_the_normative_sha256_jcs_payload_sig_digest(self):
        """Independently recomputed here, so neither implementation grades its own work.

        Equality alone would still hold if BOTH sides regressed together. Pinning the value
        to a digest this test computes from the document itself is what makes that
        impossible.
        """
        expected = hashlib.sha256(_canonical(
            {"payload": self.payload, "sig": self.document["sig"]}
        )).hexdigest()
        self.assertEqual(self._staging_handle(), expected)
        self.assertEqual(self._acceptance_handle(), expected)
        # The shared definition agrees with the locally recomputed digest.
        self.assertEqual(challenge_handle_for(self.payload, self.document["sig"]), expected)
        # ...and with a digest of the exact transported bytes, which is the §7 predicate
        # ("fetch by handle, re-hash the exact stored bytes") in miniature.
        self.assertEqual(hashlib.sha256(self.document_bytes).hexdigest(), expected)

    def test_neither_side_uses_the_superseded_payload_only_digest(self):
        """The regression guard, stated as the thing that must NOT happen.

        ``SHA256(JCS(payload))`` is what §5's table used to specify and what ``accept_open``
        used to compute. If either side reverts to it, the equality above breaks AND this
        names the exact half that moved.
        """
        superseded = hashlib.sha256(_canonical(self.payload)).hexdigest()
        expected = hashlib.sha256(_canonical(
            {"payload": self.payload, "sig": self.document["sig"]}
        )).hexdigest()
        # Sanity: the two formulas really are distinguishable for this document, so the
        # assertions below cannot pass vacuously.
        self.assertNotEqual(superseded, expected)
        self.assertNotEqual(self._staging_handle(), superseded,
                            "the §4.10(a0) staging path regressed to SHA256(JCS(payload))")
        self.assertNotEqual(self._acceptance_handle(), superseded,
                            "the §5 acceptance path regressed to SHA256(JCS(payload))")

    def test_a_different_signature_over_the_same_payload_is_a_different_handle(self):
        """The property the ``{payload, sig}`` form has and the payload-only form lost.

        Under ``SHA256(JCS(payload))`` these two documents collapse to ONE handle. Under the
        normative form they do not — the handle addresses the signed DOCUMENT, not the
        statement inside it.
        """
        other_sig = self.document["sig"][::-1]
        self.assertNotEqual(other_sig, self.document["sig"])
        self.assertNotEqual(
            challenge_handle_for(self.payload, other_sig),
            challenge_handle_for(self.payload, self.document["sig"]),
        )
        # ...while the superseded formula cannot tell them apart. Kept as the honest record
        # of what the old form bought — and the next test is why losing it costs nothing.
        self.assertEqual(hashlib.sha256(_canonical(self.payload)).hexdigest(),
                         hashlib.sha256(_canonical(self.payload)).hexdigest())

    def test_a_re_signed_replay_still_buys_zero_additional_execution_attempts(self):
        """Losing the payload-only collapse does NOT open a replay hole.

        A re-signed document now misses the ``UNIQUE(challenge_handle)`` lookup — and then
        collides on ``UNIQUE(install_id, request_nonce)`` and is refused. Different refusal,
        same guarantee: one signed statement, one execution attempt.
        """
        self._acceptance_handle()  # the original acceptance exists.
        replay = accept_open(
            self.document,
            NOW,
            config=_supervisor_config(),
            verify_sig=lambda message, sig: _verify_challenge_sig(
                message, sig, CHALLENGE_PUBLIC_KEY),
            recompute_request_sha256=recompute_request_sha256,
        )
        self.assertIsInstance(replay, Accepted)
        # Force the handle to a value the ledger has never seen — exactly what a genuinely
        # re-signed document produces under the normative formula.
        rebound = dataclasses.replace(replay.acceptance, challenge_handle="d" * 64)
        with self.assertRaises(gsupl.Conflict):
            gsupl.reuse_or_prepare(self.conn, rebound, NOW)
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM governed_turn_acceptance WHERE install_id = ?"
            " AND request_nonce = ?",
            (self.payload["install_id"], self.payload["request_nonce"]),
        ).fetchone()
        self.assertEqual(row["n"], 1, "a re-signed replay minted a second acceptance row")


class AddendumRecordsTheCorrectionTests(unittest.TestCase):
    """The normative document must not drift back, and the correction must stay visible.

    Every other guard in this file is executable: the code computes a digest and the digest is
    checked. The addendum is prose, so a revert of §5's table has NO executable consequence at
    all — nothing imports it, nothing runs it. That is exactly why it needs pinning: rev-30's
    §5 table is how this contradiction shipped in the first place, and a silent edit to the
    normative source is the worst change anyone could make here.
    """

    ADDENDUM = ROOT.parent / "docs" / "design" / "WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md"

    def _text(self):
        # A hard failure, not a skip: the normative source going missing is not a reason to
        # report success.
        self.assertTrue(self.ADDENDUM.is_file(),
                        "the normative addendum is missing at %s" % self.ADDENDUM)
        return self.ADDENDUM.read_text(encoding="utf-8")

    def test_the_addendum_never_defines_the_handle_as_the_payload_alone(self):
        text = self._text().lower()
        self.assertNotIn(
            "challenge_handle = sha256(jcs(payload))", text,
            "the addendum has reverted to defining challenge_handle over the payload alone; "
            "§3, §4.10(a0) and Appendix B say SHA256(JCS({payload, sig})) and §7's re-hash "
            "predicate is unsatisfiable without it",
        )

    def test_the_addendum_states_the_normative_form(self):
        text = self._text()
        self.assertIn("`challenge_handle = SHA256(JCS({payload,sig}))`", text,
                      "§3's artifact matrix no longer states the normative handle formula")

    def test_the_correction_is_recorded_visibly_rather_than_applied_silently(self):
        text = self._text()
        self.assertIn("CORRECTION 2026-08-10", text,
                      "the correction banner was removed from the normative source")
        self.assertIn("CORRECTED 2026-08-10", text,
                      "§5's summary table no longer carries its correction marker")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
