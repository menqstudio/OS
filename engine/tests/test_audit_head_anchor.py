"""O-2 — the audit ledger's signed head anchor, from dead code to enforced.

Before this, ``head_anchor_payload``/``attach_head_anchor`` had zero callers, so no
``.head.sig`` was ever written, and every production ``verify()`` was called with no
keys — falling through to the PLAINTEXT ``.head`` branch, a sidecar that the
ledger's own ``append()`` rewrites. Whoever could write the ledger could drop
records, recompute the chain, rewrite that head, and ``verify()`` reported the chain
intact.

These tests pin the whole closure:

* ``append()`` attaches an Ed25519-signed head anchor produced by the OWNER's
  signing command, and refuses any document that is not a signature over exactly
  the payload the ledger assembled;
* a keyed ``verify()`` REQUIRES that anchor, so the drop-records-and-rewrite-the-head
  forgery now fails where it previously passed;
* "unanchored" and "tampered" stay different facts (``AuditAnchorMissing`` versus a
  plain ``AuditError``) because they call for different actions;
* custody is the owner's: with no signing command configured the engine refuses by
  name and says exactly what must be provided. It invents no key, and it refuses a
  signing command that lives inside the engine, because an anchor signed by
  something the ledger's writer can reach proves nothing.
"""
import json
import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

import bro_audit_log
from bro_audit_log import (
    AuditAnchorCustodyMissing,
    AuditAnchorMissing,
    AuditError,
    append,
    attach_head_anchor,
    head_anchor_payload,
    verify,
)

import _audit_anchor


class AnchoredLedgerFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="bro-anchor-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.ledger = self.tmp / "audit.jsonl"
        self.custody = _audit_anchor.provision(self)

    def anchor_path(self):
        return self.ledger.with_name(self.ledger.name + ".head.sig")

    def head_path(self):
        return self.ledger.with_name(self.ledger.name + ".head")

    def fill(self, n=3):
        for i in range(n):
            append(self.ledger, "decision", {"i": i})

    def drop_last_record_and_rewrite_head(self):
        """The exact O-2 forgery: the ledger's writer drops its most recent record
        and rewrites the plaintext head it also controls."""
        lines = self.ledger.read_text(encoding="utf-8").splitlines()
        kept = lines[:-1]
        self.ledger.write_text("\n".join(kept) + "\n", encoding="utf-8")
        tail = json.loads(kept[-1])
        self.head_path().write_text(
            json.dumps({"count": len(kept), "last_hash": tail["hash"]}), encoding="utf-8")


class AppendProducesAnAnchorTests(AnchoredLedgerFixture):
    def test_append_attaches_a_signed_head_anchor(self):
        # The producer that did not exist: appending now installs a .head.sig whose
        # payload describes this exact chain.
        self.fill(3)
        self.assertTrue(self.anchor_path().exists(),
                        "append() must install a signed head anchor")
        document = json.loads(self.anchor_path().read_text(encoding="utf-8"))
        self.assertEqual(document["payload"]["artifact_type"], "audit-head")
        self.assertEqual(document["payload"]["count"], 3)
        self.assertEqual(document["payload"]["ledger"], self.ledger.name)
        self.assertEqual(document["payload"]["key_id"], self.custody.key_id)
        # And the keyed verify — the authoritative one — accepts it.
        self.assertEqual(verify(self.ledger, keys=self.custody.trusted), 3)

    def test_each_anchor_names_the_one_it_supersedes(self):
        # previous_anchor_sha256 lets the owner's signer chain its own decisions.
        append(self.ledger, "decision", {"i": 0})
        first = json.loads(self.anchor_path().read_text(encoding="utf-8"))
        self.assertIsNone(first["payload"]["previous_anchor_sha256"])
        append(self.ledger, "decision", {"i": 1})
        second = json.loads(self.anchor_path().read_text(encoding="utf-8"))
        self.assertEqual(len(second["payload"]["previous_anchor_sha256"]), 64)

    def test_out_of_band_anchor_round_trip_still_works(self):
        # head_anchor_payload/attach_head_anchor were the dead code; they remain the
        # operator's by-hand path and must still function.
        self.fill(2)
        payload = head_anchor_payload(self.ledger, key_id=self.custody.key_id,
                                      now=_audit_anchor.NOW)
        document = self.custody.sign(_audit_anchor.ANCHOR_AUTHORITY, payload)
        attach_head_anchor(self.ledger, document, self.custody.trusted)
        self.assertEqual(verify(self.ledger, keys=self.custody.trusted), 2)


class TheForgeryThatUsedToPassTests(AnchoredLedgerFixture):
    def test_rewritten_head_over_dropped_records_is_refused(self):
        """THE O-2 test: append, rewrite the head, and verify() must REFUSE."""
        self.fill(3)
        self.drop_last_record_and_rewrite_head()

        # The defect, still demonstrable: the unkeyed structural check — what every
        # production caller used to run — reports the forged chain as intact.
        self.assertEqual(verify(self.ledger), 2)

        # The closure: the keyed check refuses, because the writer cannot re-sign.
        with self.assertRaises(AuditError) as caught:
            verify(self.ledger, keys=self.custody.trusted)
        # …and it refuses as TAMPERING, not as "unanchored": the anchor is present
        # and disagrees. Collapsing the two would lose the one that gets acted on.
        self.assertNotIsInstance(caught.exception, AuditAnchorMissing)
        self.assertIn("count disagrees with chain length", str(caught.exception))

    def test_a_forger_who_also_deletes_the_anchor_is_refused_too(self):
        # Removing the signature is not a way out: keyed verification requires one.
        self.fill(3)
        self.drop_last_record_and_rewrite_head()
        self.anchor_path().unlink()
        with self.assertRaises(AuditAnchorMissing):
            verify(self.ledger, keys=self.custody.trusted)

    def test_emptied_ledger_with_both_sidecars_deleted_is_refused(self):
        # A wipe to zero records used to slip through the keyed branch entirely:
        # no records meant the missing-anchor branch was skipped and verify()
        # returned a clean 0. An existing ledger file must be anchored, always.
        self.fill(2)
        self.ledger.write_text("", encoding="utf-8")
        self.head_path().unlink()
        self.anchor_path().unlink()
        with self.assertRaises(AuditAnchorMissing):
            verify(self.ledger, keys=self.custody.trusted)

    def test_a_ledger_that_never_existed_is_not_an_anchor_failure(self):
        # Precision the other way: nothing was ever recorded, so there is nothing to
        # anchor and nothing to report.
        self.assertEqual(verify(self.tmp / "never-created.jsonl",
                                keys=self.custody.trusted), 0)


class UnanchoredIsItsOwnFactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="bro-unanchored-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.ledger = self.tmp / "audit.jsonl"
        self.custody = _audit_anchor.provision(self)
        _audit_anchor.without_custody(self)

    def test_unanchored_ledger_refuses_with_its_own_type_and_says_why(self):
        append(self.ledger, "decision", {"i": 0})
        self.assertFalse(self.ledger.with_name(self.ledger.name + ".head.sig").exists())
        with self.assertRaises(AuditAnchorMissing) as caught:
            verify(self.ledger, keys=self.custody.trusted)
        message = str(caught.exception)
        self.assertIn("UNANCHORED", message)
        self.assertIn("different fact from tampering", message)
        # The refusal must tell the owner exactly what to provide.
        self.assertIn("BRO_AUDIT_ANCHOR_SIGNER", message)
        self.assertIn("BRO_AUDIT_ANCHOR_KEY_ID", message)

    def test_unkeyed_verify_still_works_for_an_unanchored_ledger(self):
        # The structural check keeps its old meaning; it simply is not authority.
        append(self.ledger, "decision", {"i": 0})
        self.assertEqual(verify(self.ledger), 1)


class CustodyIsTheOwnersTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="bro-custody-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.ledger = self.tmp / "audit.jsonl"

    def test_absent_custody_is_a_named_loud_refusal_not_an_invented_key(self):
        with self.assertRaises(AuditAnchorCustodyMissing) as caught:
            bro_audit_log.anchor_custody(env={})
        message = str(caught.exception)
        self.assertIn("BRO_AUDIT_ANCHOR_SIGNER", message)
        self.assertIn("BRO_AUDIT_ANCHOR_KEY_ID", message)
        self.assertIn("none will be invented", message)
        # It must name the ONE authority that can anchor, and say out loud that the two
        # the app's own trust store used to carry are not it. A refusal that still said
        # "evidence-recorder or operator-root" would send an owner to provision exactly
        # the key that reopens O-2.
        self.assertIn("audit-anchor", message)
        self.assertIn("are NOT accepted", message)
        self.assertIn("anti-rollback", message)

    def test_half_configured_custody_is_refused_not_silently_ignored(self):
        # A key id with no signer (or the reverse) must not degrade to "unanchored".
        self.assertTrue(bro_audit_log.anchor_custody_configured(
            env={"BRO_AUDIT_ANCHOR_KEY_ID": "k"}))
        with self.assertRaises(AuditAnchorCustodyMissing):
            bro_audit_log.anchor_custody(env={"BRO_AUDIT_ANCHOR_KEY_ID": "k"})

    def test_a_signer_inside_the_engine_is_refused(self):
        # An anchor signed by something the ledger's own writer can reach proves
        # nothing; shipping it would read as protection while providing none.
        inside = ROOT / "runtime" / "bro_audit_log.py"
        with self.assertRaises(AuditAnchorCustodyMissing) as caught:
            bro_audit_log.anchor_custody(env={
                "BRO_AUDIT_ANCHOR_SIGNER": str(inside),
                "BRO_AUDIT_ANCHOR_KEY_ID": "k"})
        self.assertIn("must not live inside this engine", str(caught.exception))

    def test_a_relative_or_missing_signer_is_refused(self):
        for value in ("signer.py", str(self.tmp / "nope.py")):
            with self.subTest(value=value):
                with self.assertRaises(AuditAnchorCustodyMissing):
                    bro_audit_log.anchor_custody(env={
                        "BRO_AUDIT_ANCHOR_SIGNER": value,
                        "BRO_AUDIT_ANCHOR_KEY_ID": "k"})


class SignerMisbehaviourFailsClosedTests(AnchoredLedgerFixture):
    def test_a_signer_that_signs_a_different_payload_is_refused(self):
        # A signing command is not trusted to decide what the head is. It signs the
        # payload the ledger assembled, or its answer is thrown away.
        _audit_anchor.use_variant_signer(self, self.custody, sign_different=True)
        with self.assertRaises(AuditError) as caught:
            append(self.ledger, "decision", {"i": 0})
        self.assertIn("DIFFERENT payload", str(caught.exception))
        self.assertFalse(self.anchor_path().exists())

    def test_a_refusing_signer_fails_the_append_closed(self):
        _audit_anchor.use_variant_signer(self, self.custody, refuse_all=True)
        with self.assertRaises(AuditError) as caught:
            append(self.ledger, "decision", {"i": 0})
        self.assertIn("signing command refused", str(caught.exception))

    def test_appending_past_an_anchor_without_custody_is_refused(self):
        # Custody vanishing must not quietly produce an unanchored tail that later
        # reads as tampering.
        self.fill(2)
        _audit_anchor.without_custody(self)
        with self.assertRaises(AuditAnchorCustodyMissing) as caught:
            append(self.ledger, "decision", {"i": 99})
        self.assertIn("would strand", str(caught.exception))
        self.assertEqual(verify(self.ledger, keys=self.custody.trusted), 2,
                         "the refused append must not have been written")

    def test_the_owners_signer_refuses_to_re_anchor_a_truncated_ledger(self):
        # Anti-rollback, the property the runtime REQUIRES of a real signer: after a
        # truncation the writer cannot get a fresh signature for the shorter chain.
        self.fill(3)
        lines = self.ledger.read_text(encoding="utf-8").splitlines()
        self.ledger.write_text(lines[0] + "\n", encoding="utf-8")
        head = json.loads(lines[0])
        self.head_path().write_text(
            json.dumps({"count": 1, "last_hash": head["hash"]}), encoding="utf-8")
        with self.assertRaises(AuditError) as caught:
            append(self.ledger, "decision", {"i": 9})
        self.assertIn("below one already signed", str(caught.exception))

    def test_installing_an_anchor_for_a_shorter_chain_is_refused(self):
        # Defence in depth on the install side: even a validly signed anchor may not
        # walk the recorded count backwards.
        self.fill(3)
        lines = self.ledger.read_text(encoding="utf-8").splitlines()
        self.ledger.write_text(lines[0] + "\n", encoding="utf-8")
        head = json.loads(lines[0])
        self.head_path().write_text(
            json.dumps({"count": 1, "last_hash": head["hash"]}), encoding="utf-8")
        rollback = self.custody.sign(_audit_anchor.ANCHOR_AUTHORITY, {
            "artifact_type": "audit-head",
            "key_id": self.custody.key_id,
            "ledger": self.ledger.name,
            "count": 1,
            "last_hash": head["hash"],
            "previous_anchor_sha256": None,
            "issued_at_epoch": _audit_anchor.NOW,
        })
        with self.assertRaises(AuditError) as caught:
            attach_head_anchor(self.ledger, rollback, self.custody.trusted)
        self.assertIn("rollback refused", str(caught.exception))


class OnlyTheAnchorAuthorityMayAnchorTests(AnchoredLedgerFixture):
    """The half of O-2 the signed anchor did NOT close until the authority narrowed.

    ``ANCHOR_AUTHORITIES`` used to be ``("evidence-recorder", "operator-root")`` on the
    premise that the ledger's writer held neither key. A deployment that provisions its
    own trust material holds BOTH, so the writer could truncate the chain, recompute it,
    sign a fresh anchor with a key out of its own store and get a green keyed
    ``verify()``. These cases present a *validly signed, registry-resolvable* anchor from
    each of those authorities and require the refusal — and require it to name the
    authority, so an operator reading it learns which key is wrong rather than hunting a
    signature that is in fact perfectly good.
    """

    FORGEABLE = ("evidence-recorder", "operator-root")

    def test_the_only_accepted_anchor_authority_is_audit_anchor(self):
        self.assertEqual(bro_audit_log.ANCHOR_AUTHORITIES, ("audit-anchor",))
        # Named directly here rather than granted through the registry, on purpose:
        # `audit-head` is out-of-registry, so rewriting the registry cannot hand anyone
        # the right to sign this ledger's own head.
        import broctl
        self.assertEqual(broctl.OUT_OF_REGISTRY_ARTIFACTS["audit-head"],
                         bro_audit_log.ANCHOR_AUTHORITIES)

    def test_a_validly_signed_anchor_from_another_authority_is_refused_by_name(self):
        for authority in self.FORGEABLE:
            with self.subTest(authority=authority):
                # A fresh ledger per authority, inside ONE provisioned custody: re-running
                # setUp would stack a second registry patch over the first and mint a
                # second key under the same key id.
                self.ledger = self.tmp / f"audit-{authority}.jsonl"
                self.fill(1)
                payload = head_anchor_payload(
                    self.ledger, key_id=self.custody.keys[authority]["key_id"],
                    now=_audit_anchor.NOW)
                document = self.custody.sign(authority, payload)
                # The signature itself is good and the key IS in the registry the engine
                # reads — this is not a forged signature, it is the wrong principal.
                with self.assertRaises(AuditError) as caught:
                    attach_head_anchor(self.ledger, document, self.custody.trusted)
                message = str(caught.exception)
                self.assertIn(f"({authority}) may not sign audit-head", message)
                self.assertIn("audit-anchor", message)
                # Refused BEFORE installation: a refused anchor must not land on disk.
                installed = json.loads(self.anchor_path().read_text(encoding="utf-8"))
                self.assertEqual(installed["payload"]["key_id"], self.custody.key_id)

    def test_the_truncation_forgery_with_a_key_the_writer_holds_is_refused(self):
        """THE O-2 negative, end to end, against the real verify().

        The writer drops records, recomputes the plaintext head it also controls, and
        signs a fresh anchor for the shorter chain with a private key sitting in its own
        trust store. Before the narrowing this returned a clean count. It must now refuse,
        and refuse for the authority, not for the chain.
        """
        for authority in self.FORGEABLE:
            with self.subTest(authority=authority):
                self.ledger = self.tmp / f"forged-{authority}.jsonl"
                self.fill(3)
                lines = self.ledger.read_text(encoding="utf-8").splitlines()
                self.ledger.write_text(lines[0] + "\n", encoding="utf-8")
                head = json.loads(lines[0])
                self.head_path().write_text(
                    json.dumps({"count": 1, "last_hash": head["hash"]}), encoding="utf-8")
                # Written straight to the sidecar: the install-side monotonic check is
                # explicitly defence in depth and a writer simply bypasses it.
                self.anchor_path().write_text(json.dumps(self.custody.sign(authority, {
                    "artifact_type": "audit-head",
                    "key_id": self.custody.keys[authority]["key_id"],
                    "ledger": self.ledger.name,
                    "count": 1,
                    "last_hash": head["hash"],
                    "previous_anchor_sha256": None,
                    "issued_at_epoch": _audit_anchor.NOW,
                }), sort_keys=True), encoding="utf-8")
                # The chain and the plaintext head agree with the anchor, so nothing but
                # the authority can be the reason.
                self.assertEqual(verify(self.ledger), 1)
                with self.assertRaises(AuditError) as caught:
                    verify(self.ledger, keys=self.custody.trusted)
                message = str(caught.exception)
                self.assertIn(f"({authority}) may not sign audit-head", message)
                self.assertNotIn("disagrees", message)

    def test_the_anchor_authority_can_be_granted_no_registry_artifact_at_all(self):
        """Why the narrowing cannot be undone by writing the registry.

        `audit-anchor` binds no artifact type in `ARTIFACT_AUTHORITY`, so its entries
        carry an EMPTY `allowed_artifact_types` and any attempt to grant one — including
        `audit-head` itself — fails to parse. The registry can name the key; it can never
        widen what the key is for.
        """
        import bro_signature
        entry = {
            "key_id": "dev-audit-anchor", "public_key": "ab" * 32,
            "authority_type": "audit-anchor", "allowed_artifact_types": [],
            "not_before_epoch": 0, "not_after_epoch": 9_999_999_999,
            "status": "active", "issued_by": "dev-operator-root",
        }
        self.assertEqual(bro_signature._parse_key(entry).allowed_artifact_types, ())
        for artifact in ("audit-head", "evidence-head", "conductor-session"):
            with self.subTest(artifact=artifact):
                with self.assertRaises(bro_signature.SignatureError):
                    bro_signature._parse_key(dict(entry, allowed_artifact_types=[artifact]))
        # And the empty grant stays a refusal for every OTHER authority: only an
        # out-of-registry-only authority may allow nothing. The list is written out
        # rather than derived from OUT_OF_REGISTRY_ONLY_AUTHORITIES on purpose - a test
        # that computes its expectation from the constant it is checking passes happily
        # when that constant is widened to everything, which is exactly the mutation
        # this case has to catch.
        self.assertEqual(bro_signature.OUT_OF_REGISTRY_ONLY_AUTHORITIES,
                         frozenset({"audit-anchor"}))
        for authority in ("builder", "control-room", "evidence-floor", "evidence-recorder",
                          "issuer", "operator-root", "recovery", "release", "verifier"):
            with self.subTest(authority=authority):
                with self.assertRaises(bro_signature.SignatureError) as caught:
                    bro_signature._parse_key(dict(entry, authority_type=authority))
                self.assertIn("allows no artifact types", str(caught.exception))
        # The written-out list is the whole of AUTHORITY_TYPES minus the exemption, so it
        # cannot silently stop covering a newly added authority either.
        self.assertEqual(
            bro_signature.AUTHORITY_TYPES,
            {"builder", "control-room", "evidence-floor", "evidence-recorder", "issuer",
             "operator-root", "recovery", "release", "verifier", "audit-anchor"})


class AnchorPayloadShapeTests(AnchoredLedgerFixture):
    def test_an_anchor_carrying_extra_fields_is_refused(self):
        # Fields the verifier does not check are fields whose meaning the signer,
        # not the verifier, decided.
        self.fill(1)
        payload = head_anchor_payload(self.ledger, key_id=self.custody.key_id,
                                      now=_audit_anchor.NOW)
        payload["waiver"] = "trust me"
        with self.assertRaises(AuditError) as caught:
            attach_head_anchor(self.ledger,
                               self.custody.sign(_audit_anchor.ANCHOR_AUTHORITY, payload),
                               self.custody.trusted)
        self.assertIn("wrong field set", str(caught.exception))

    def test_an_anchor_missing_a_field_is_refused(self):
        self.fill(1)
        payload = head_anchor_payload(self.ledger, key_id=self.custody.key_id,
                                      now=_audit_anchor.NOW)
        del payload["previous_anchor_sha256"]
        with self.assertRaises(AuditError):
            attach_head_anchor(self.ledger,
                               self.custody.sign(_audit_anchor.ANCHOR_AUTHORITY, payload),
                               self.custody.trusted)

    def test_an_anchor_for_a_different_ledger_is_refused(self):
        self.fill(1)
        payload = head_anchor_payload(self.ledger, key_id=self.custody.key_id,
                                      now=_audit_anchor.NOW)
        payload["ledger"] = "someone-elses.jsonl"
        with self.assertRaises(AuditError) as caught:
            attach_head_anchor(self.ledger,
                               self.custody.sign(_audit_anchor.ANCHOR_AUTHORITY, payload),
                               self.custody.trusted)
        self.assertIn("different ledger", str(caught.exception))

    def test_an_unreadable_anchor_is_a_refusal_not_a_pass(self):
        self.fill(1)
        self.anchor_path().write_text("{ not json", encoding="utf-8")
        with self.assertRaises(AuditError) as caught:
            verify(self.ledger, keys=self.custody.trusted)
        self.assertIn("unreadable audit head anchor", str(caught.exception))


class ProductionVerifiersPassKeysTests(AnchoredLedgerFixture):
    """The other half of O-2: the call sites. Both production verifiers used to
    call verify() with no keys at all, so the signed-anchor branch could never run."""

    def test_monitor_reports_a_signed_anchor_and_stays_green(self):
        import bro_monitor
        self.fill(2)
        report = bro_monitor.scan(shadow_ledger=self.ledger)
        self.assertEqual(report["shadow"]["anchor"]["state"], "signed")
        self.assertEqual(report["health"], "GREEN")

    def test_monitor_separates_unanchored_from_tampered(self):
        import bro_monitor
        self.fill(2)
        self.drop_last_record_and_rewrite_head()
        tampered = bro_monitor.scan(shadow_ledger=self.ledger)
        # The plaintext head still agrees — this is exactly what used to read GREEN.
        self.assertTrue(tampered["shadow"]["chain_ok"])
        self.assertEqual(tampered["shadow"]["anchor"]["state"], "invalid")
        self.assertEqual(tampered["health"], "ATTENTION")
        self.assertTrue(any("does NOT verify" in a for a in tampered["attention"]))

        unanchored_ledger = self.tmp / "unanchored.jsonl"
        _audit_anchor.without_custody(self)
        append(unanchored_ledger, "decision", {"i": 0})
        unanchored = bro_monitor.scan(shadow_ledger=unanchored_ledger)
        self.assertEqual(unanchored["shadow"]["anchor"]["state"], "unanchored")
        self.assertEqual(unanchored["health"], "ATTENTION")
        self.assertTrue(any("UNANCHORED" in a for a in unanchored["attention"]))

    def test_backup_refuses_an_unanchored_ledger(self):
        import bro_backup
        unanchored = self.tmp / "state" / "unanchored.jsonl"
        unanchored.parent.mkdir(parents=True)
        _audit_anchor.without_custody(self)
        append(unanchored, "decision", {"i": 0})
        with self.assertRaises(bro_backup.BackupError) as caught:
            bro_backup.backup({"s": unanchored}, self.tmp / "archive",
                              now=_audit_anchor.NOW)
        self.assertIn("UNANCHORED", str(caught.exception))

    def test_backup_refuses_when_the_key_registry_cannot_be_loaded(self):
        # No keyless mode: a registry that will not load is a refusal, never a
        # downgrade to the plaintext head the ledger's own writer controls.
        import bro_backup
        import bro_signature
        from unittest.mock import patch
        self.fill(1)
        with patch.object(bro_signature, "load_trusted_keys",
                          side_effect=bro_signature.SignatureError("no pin")):
            with self.assertRaises(bro_backup.BackupError) as caught:
                bro_backup.backup({"s": self.ledger}, self.tmp / "archive",
                                  now=_audit_anchor.NOW)
        self.assertIn("refusing rather than falling back", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
