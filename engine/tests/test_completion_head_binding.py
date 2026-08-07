"""O-5 — the evidence high-water mark must live in signed state, not only on disk.

Before this, `_check_manifest`'s strict required set carried no `evidence_head_sha256` and no
`head_sequence`, and every production entry point passed `min_head_sequence=None`. The whole
anti-rollback property therefore rested on a directory of small JSON files: the signed artifact
the builder produced said nothing at all about which evidence head it was claiming against.

These tests pin the three things that changed:

* the manifest MUST name the head it completes against, by monotonic sequence and by the digest
  of the signed head document, and both are checked against the store;
* a rollback is still caught when the floor directory is wiped and re-provisioned, because the
  recorder-signed events the builder wants to forget are still in the store and it cannot
  re-mint them;
* a high-water mark this deployment cannot establish is a REFUSAL that names the
  owner-provided key which would close it — never a silent default of zero.
"""

import json
import os
import pathlib
import shutil
import sys
import time
import unittest
import unittest.mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

from bro_contracts import canonical_json_sha256
from broctl import build_registry, sign_payload
# EvidenceFixture carries no test methods, so importing it does not re-run another
# module's suite under this one's name.
from test_evidence_chain import YEAR, EvidenceFixture

TASK = {
    "task_id": "task-1",
    "agent_id": "agt-p01-r01",
    "risk": "low",
    "done_criteria": ["work recorded"],
    "verification": {"required": False, "commands": ["python -m unittest"]},
}


class HeadBindingFixture(EvidenceFixture):
    """A real signed chain plus a real trusted-key registry valid against the real clock.

    `_check_manifest` runs the manifest freshness window against `time.time()`, so the
    registry cannot be pinned at the frozen NOW the pure evidence tests use.
    """

    def setUp(self):
        super().setUp()
        real_now = int(time.time())
        self.repo = self.tmp / "repo"
        (self.repo / "config").mkdir(parents=True)
        (self.repo / "config" / "trusted-keys.json").write_text(
            json.dumps(build_registry(list(self.keys.values()), real_now - 60, YEAR)),
            encoding="utf-8")
        from bro_signature import load_trusted_keys
        self.live_keys = load_trusted_keys(self.repo)
        # `_check_verifier_receipt` reads the independence floor straight off disk.
        (self.repo / "agents").mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / "agents" / "authority-policy.json",
                    self.repo / "agents" / "authority-policy.json")

        import bro_completion
        self.completion = bro_completion

        self.provision_floor()
        # A test process is a deployment with no principal separation: it owns the floor that
        # polices it, which the R-06 custody rule refuses by default. Say so rather than
        # weaken the rule. (POSIX-only refusal, so this is a no-op on Windows.)
        ack = unittest.mock.patch.dict(
            os.environ, {"BRO_OPERATOR_ROOT_PIN_SELF_OWNED": "acknowledged"})
        ack.start()
        self.addCleanup(ack.stop)

    # ---- fixture helpers -----------------------------------------------------------

    def provision_floor(self):
        """Bootstrap the anti-rollback floor the way a deployment deliberately would."""
        directory = self.store / "head-floor"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "_index.json").write_text(json.dumps({"tasks": []}), encoding="utf-8")

    def head_document(self, task_id="task-1"):
        return json.loads(
            (self.store / f"{task_id}.head.json").read_text(encoding="utf-8"))

    def binding(self, task_id="task-1"):
        document = self.head_document(task_id)
        return {
            "evidence_head_sha256": canonical_json_sha256(document),
            "head_sequence": document["payload"]["head_sequence"],
        }

    def reseal_head(self, head_sequence, task_id="task-1"):
        """Re-sign the existing head with a different ``head_sequence``.

        Every signature stays genuine — that is the point. A rollback is not forgery, it is
        re-presenting an authentic older anchor.
        """
        payload = self.head_document(task_id)["payload"]
        payload["head_sequence"] = head_sequence
        (self.store / f"{task_id}.head.json").write_text(
            json.dumps(sign_payload(self.keys["evidence-recorder"]["private_key"], payload)),
            encoding="utf-8")

    def manifest(self, *, event_ids=None, task_id="task-1", **overrides):
        ids = list(self.chain if event_ids is None else event_ids)
        now = int(time.time())
        payload = {
            "schema": 1,
            "task_id": task_id,
            "agent_id": TASK["agent_id"],
            "task_contract_sha256": canonical_json_sha256(TASK),
            "candidate_head": "a" * 40,
            "candidate_tree": "b" * 64,
            "done_criteria": [{"criterion": "work recorded", "status": "satisfied",
                               "evidence_event_ids": [ids[0]]}],
            "tests": [{"command": ["python", "-m", "unittest"], "status": "passed",
                       "evidence_event_id": ids[-1],
                       "execution_receipt_id": "rcpt-0000000000000001"}],
            "evidence_event_ids": ids,
            **self.binding(task_id),
            "open_risks": [],
            "rollback_ready": True,
            "nonce": "nonce-head-binding-0001",
            "issued_at_epoch": now,
            "expires_at_epoch": now + 3600,
        }
        payload.update(overrides)
        for key in [k for k, v in overrides.items() if v is _ABSENT]:
            payload.pop(key)
        return payload

    def check(self, manifest, task=None):
        """Run the real `_check_manifest`, with only the execution-receipt lookup stubbed.

        Receipts are a separate signed artifact with their own suite; everything this file
        is about — the shape, the head binding, the floor — runs for real.
        """
        with unittest.mock.patch.object(self.completion, "_require_signer_identity"), \
                unittest.mock.patch.object(self.completion, "_validate_execution_receipts",
                                           return_value=[]):
            return self.completion._check_manifest(
                task or TASK, TASK["agent_id"], manifest, root=self.repo, now=None,
                keys=self.live_keys, evidence_store=self.store, receipt_store=self.store,
                require_live=False)

    def refusal(self, manifest, task=None):
        from bro_completion import CompletionError
        with self.assertRaises(CompletionError) as caught:
            self.check(manifest, task)
        return str(caught.exception)


_ABSENT = object()


class ManifestRequiresTheHeadBindingTests(HeadBindingFixture):
    """The required-field half: the binding cannot be omitted or mistyped."""

    def test_a_manifest_carrying_the_binding_is_accepted(self):
        manifest, _hash, _receipts = self.check(self.manifest())
        self.assertEqual(manifest["head_sequence"], 1)

    def test_a_manifest_without_head_sequence_is_refused(self):
        message = self.refusal(self.manifest(head_sequence=_ABSENT))
        self.assertIn("invalid completion manifest shape", message)

    def test_a_manifest_without_the_evidence_head_digest_is_refused(self):
        message = self.refusal(self.manifest(evidence_head_sha256=_ABSENT))
        self.assertIn("invalid completion manifest shape", message)

    def test_a_manifest_omitting_the_binding_entirely_fails_the_shape_check(self):
        # The strict set is exact, so dropping ONE field is refused whatever the required set
        # says — the manifest simply stops matching it. Dropping BOTH is the case that
        # actually pins membership: with the fields out of the required set this manifest is
        # a perfectly well-shaped one, and the refusal has to come from somewhere else.
        message = self.refusal(
            self.manifest(head_sequence=_ABSENT, evidence_head_sha256=_ABSENT))
        self.assertIn("invalid completion manifest shape", message)

    def test_head_sequence_must_be_a_positive_integer(self):
        for bad in ("1", 0, -3, True, 1.0):
            with self.subTest(bad=bad):
                message = self.refusal(self.manifest(head_sequence=bad))
                self.assertIn("head_sequence must be a positive integer", message)

    def test_the_evidence_head_digest_must_be_a_sha256(self):
        for bad in ("not-a-digest", "A" * 64, 12, "a" * 63):
            with self.subTest(bad=bad):
                message = self.refusal(self.manifest(evidence_head_sha256=bad))
                self.assertIn("evidence_head_sha256 must be a sha256 digest", message)


class ManifestIsBoundToOneSignedHeadTests(HeadBindingFixture):
    """The binding half: the store must hold exactly the head the manifest names."""

    def test_a_manifest_naming_a_different_signed_head_is_refused(self):
        # Same sequence, different signed document: the recorder re-anchored the chain and
        # the builder is completing against the head it remembers.
        stale = self.binding()["evidence_head_sha256"]
        self.write_chain("task-1", ["work-started", "tests-passed", "tests-failed",
                                    "rolled-back", "re-anchored"])
        message = self.refusal(self.manifest(
            event_ids=[f"task-1-e{n}" for n in range(1, 6)],
            evidence_head_sha256=stale))
        self.assertIn("a different signed head", message)

    def test_a_manifest_left_behind_by_a_re_anchor_is_refused(self):
        # The store moved on to head_sequence 3; a manifest still binding 1 is not a
        # completion of the state that exists.
        self.reseal_head(3)
        message = self.refusal(self.manifest(head_sequence=1))
        self.assertIn("head_sequence 1", message)
        self.assertIn("is at 3", message)

    def test_the_verifier_receipt_inherits_the_manifest_binding(self):
        # The receipt is bound to the manifest by hash, so it must anchor at the same head
        # rather than carry a second, independently forgeable copy of the mark.
        from bro_completion import CompletionError
        manifest = self.manifest()
        receipt = {
            "schema": 1, "receipt_id": "rcpt-0000000000000002", "task_id": "task-1",
            "builder_agent_id": TASK["agent_id"], "verifier_agent_id": "agt-p01-r02",
            "verifier_role": "Independent Verifier", "independence_level": "L4",
            "task_contract_sha256": canonical_json_sha256(TASK),
            "completion_manifest_sha256": canonical_json_sha256(manifest),
            "candidate_head": "a" * 40, "candidate_tree": "b" * 64,
            "evidence_event_ids": list(self.chain), "verdict": "GREEN",
            "issued_at_epoch": manifest["issued_at_epoch"],
            "expires_at_epoch": manifest["expires_at_epoch"],
        }
        # Roll the store's head forward underneath both artifacts.
        self.reseal_head(9)
        with unittest.mock.patch.object(self.completion, "_require_signer_identity"), \
                unittest.mock.patch.object(self.completion, "validate_verifier_assignment"), \
                self.assertRaises(CompletionError) as caught:
            self.completion._check_verifier_receipt(
                dict(TASK, verification={"required": True,
                                         "verifier_agent_id": "agt-p01-r02",
                                         "verifier_role": "Independent Verifier"}),
                manifest, canonical_json_sha256(TASK), receipt,
                root=self.repo, now=None, keys=self.live_keys, evidence_store=self.store)
        self.assertIn("is at 9", str(caught.exception))


class RollbackTests(HeadBindingFixture):
    """The anti-rollback half, including with the floor deleted."""

    def advance_to(self, head_sequence):
        """Walk the deployment up to ``head_sequence`` the way a real one gets there.

        A task is first measured at the recorder's first anchor (sequence 1) and only then
        re-anchored upward; the mark is what makes the later, higher sequence establishable.
        """
        self.check(self.manifest())
        self.reseal_head(head_sequence)
        self.check(self.manifest())

    def test_a_completion_that_rolls_the_sequence_backwards_is_refused(self):
        # The attack the mark exists for: reach 5, retain the genuinely-signed head 1, and
        # re-present it later. Every signature verifies; only a mark that outlives the call
        # can see it.
        self.advance_to(5)
        self.reseal_head(1)
        message = self.refusal(self.manifest())
        self.assertIn("stale", message)

    def test_deleting_the_floor_does_not_hide_a_rolled_back_chain(self):
        # Wipe the floor AND re-provision it, which is the residual R-06 left open: a
        # deleted floor refuses, but a deleted-and-re-bootstrapped one reads as brand new.
        # The rollback is still caught, because the recorder-signed events the builder wants
        # to forget are still in the store and it cannot re-mint them against an older head.
        self.advance_to(5)
        shutil.rmtree(self.store / "head-floor")
        self.provision_floor()
        self.assertEqual(json.loads((self.store / "head-floor" / "_index.json")
                                    .read_text(encoding="utf-8")), {"tasks": []})

        # The retained older anchor, describing only the first two events.
        self.write_head("task-1", self.event_digest(2), 2, 2, head_sequence=1)
        message = self.refusal(self.manifest(event_ids=self.chain[:2]))
        self.assertIn("the evidence store holds signed events for task-1", message)
        self.assertIn("task-1-e3", message)

    def test_a_wiped_floor_cannot_silently_re_establish_a_high_water_mark(self):
        # The other half of the same wipe: a manifest binding a re-anchored head (>1) with
        # no durable mark behind it is unprovable, so it refuses and names the owner key.
        self.advance_to(5)
        shutil.rmtree(self.store / "head-floor")
        self.provision_floor()
        message = self.refusal(self.manifest())
        self.assertIn("cannot establish the evidence high-water mark", message)
        self.assertIn("BRO_EVIDENCE_FLOOR_ANCHOR", message)
        self.assertIn("operator-root-signed", message)
        self.assertIn("none is compiled in", message)

    def test_a_presented_floor_anchor_that_cannot_verify_refuses(self):
        # A presented anchor is never a fallback: one this deployment cannot verify is a
        # refusal that says what the owner must mint. `evidence-floor-anchor` is now a
        # registered artifact type (bro_signature.ARTIFACT_AUTHORITY), so the anchor is
        # signed here by an authority that may NOT sign it — registering the type gave
        # nobody a key, and this is what that looks like from the consuming side. The
        # matching positive path, and the case where the type is registered but no key is
        # pinned for it, live in test_owner_artifact_registration.py.
        from bro_completion import CompletionError
        self.advance_to(5)
        shutil.rmtree(self.store / "head-floor")
        self.provision_floor()
        anchor = self.tmp / "floor-anchor.json"
        anchor.write_text(json.dumps(sign_payload(
            self.keys["builder"]["private_key"],
            {"artifact_type": "evidence-floor-anchor",
             "key_id": self.keys["builder"]["key_id"],
             "task_id": "task-1", "head_sequence": 5})), encoding="utf-8")
        with unittest.mock.patch.dict(os.environ,
                                      {"BRO_EVIDENCE_FLOOR_ANCHOR": str(anchor)}):
            with self.assertRaises(CompletionError) as caught:
                self.check(self.manifest())
        message = str(caught.exception)
        self.assertIn("does not verify as an operator-signed evidence-floor-anchor", message)
        self.assertIn("none is compiled in", message)

    def test_a_second_signed_head_at_the_same_sequence_is_refused(self):
        # A counter that does not move is not a high-water mark. Two genuinely signed heads
        # sharing one sequence means the sequence has stopped ordering anything.
        self.check(self.manifest())
        self.write_chain("task-1", ["work-started", "tests-passed", "tests-failed",
                                    "rolled-back", "re-anchored"])
        message = self.refusal(
            self.manifest(event_ids=[f"task-1-e{n}" for n in range(1, 6)]))
        self.assertIn("changed without advancing head_sequence", message)

    def test_a_mark_that_names_no_signed_head_is_refused(self):
        # The mark points at signed bytes; a record reduced to a bare number cannot say
        # which head it measured, and a number alone is what an attacker can write.
        self.check(self.manifest())
        mark = self.store / "head-floor" / "task-1.floor.json"
        record = json.loads(mark.read_text(encoding="utf-8"))
        self.assertEqual(record["evidence_head_sha256"],
                         self.binding()["evidence_head_sha256"])
        del record["evidence_head_sha256"]
        mark.write_text(json.dumps(record), encoding="utf-8")
        message = self.refusal(self.manifest())
        self.assertIn("records no signed head digest", message)

    # ---- helper ---------------------------------------------------------------------

    def event_digest(self, position, task_id="task-1"):
        """The event hash of the chain's ``position``-th event, for a truncated head."""
        from bro_evidence import event_hash
        document = json.loads(
            (self.store / f"{task_id}-e{position}.json").read_text(encoding="utf-8"))
        return event_hash(document["payload"])


if __name__ == "__main__":
    unittest.main()
