import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
import unittest.mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))

from bro_evidence import (
    EvidenceError,
    event_hash,
    load_head,
    validate_chain,
    validate_criterion_evidence,
)
from bro_signature import load_trusted_keys
from broctl import build_registry, generate_key, sign_payload

NOW = 1_700_000_000
YEAR = 365 * 24 * 60 * 60
AUTHORITIES = ["operator-root", "issuer", "evidence-recorder", "builder",
               "verifier", "release"]


class EvidenceFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="bro-ev-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.store = self.tmp / "store"
        self.store.mkdir()

        self.keys = {a: generate_key(a, f"dev-{a}", False) for a in AUTHORITIES}
        registry_root = self.tmp / "registry"
        (registry_root / "config").mkdir(parents=True)
        (registry_root / "config" / "trusted-keys.json").write_text(
            json.dumps(build_registry(list(self.keys.values()), NOW, YEAR)),
            encoding="utf-8")
        self.trusted = load_trusted_keys(registry_root)

        # e3 is the failure a truncating builder would rather not mention;
        # e4 is the rollback that leaves the tree clean afterwards.
        self.chain = self.write_chain("task-1", [
            "work-started", "tests-passed", "tests-failed", "rolled-back"])

    def sign(self, authority, payload):
        return sign_payload(self.keys[authority]["private_key"],
                            dict(payload, key_id=self.keys[authority]["key_id"]))

    def write_chain(self, task_id, event_types, *, head_authority="evidence-recorder",
                    head_count=None):
        previous, ids, digest = None, [], ""
        for sequence, event_type in enumerate(event_types, start=1):
            event_id = f"{task_id}-e{sequence}"
            payload = {
                "artifact_type": "evidence-event",
                "key_id": self.keys["evidence-recorder"]["key_id"],
                "event_id": event_id, "sequence": sequence,
                "previous_event_hash": previous, "task_id": task_id,
                "event_type": event_type, "agent_id": "agt-p01-r01",
                "payload_hash": "a" * 64, "issued_at_epoch": NOW,
            }
            document = sign_payload(self.keys["evidence-recorder"]["private_key"], payload)
            (self.store / f"{event_id}.json").write_text(json.dumps(document),
                                                         encoding="utf-8")
            digest = event_hash(payload)
            previous = digest
            ids.append(event_id)
        self.write_head(task_id, digest, head_count or len(ids), len(ids),
                        authority=head_authority)
        return ids

    def write_head(self, task_id, final_hash, count, last_sequence,
                   *, authority="evidence-recorder"):
        payload = {
            "artifact_type": "evidence-head",
            "key_id": self.keys[authority]["key_id"],
            "task_id": task_id, "final_event_hash": final_hash,
            "event_count": count, "last_sequence": last_sequence,
            "issued_at_epoch": NOW,
        }
        (self.store / f"{task_id}.head.json").write_text(
            json.dumps(sign_payload(self.keys[authority]["private_key"], payload)),
            encoding="utf-8")

    def check(self, ids, task_id="task-1"):
        return validate_chain(task_id, ids, self.trusted, store=self.store, now=NOW + 10)


class WholeChainTests(EvidenceFixture):
    def test_full_chain_verifies(self):
        digest = self.check(self.chain)
        self.assertEqual(len(digest), 64)

    def test_truncated_chain_denied(self):
        """The whole point: every event is genuine, the links are genuine, and
        the two the builder dropped are the failure and its rollback."""
        with self.assertRaises(EvidenceError) as caught:
            self.check(self.chain[:2])
        self.assertIn("incomplete", str(caught.exception))

    def test_dropping_only_the_last_event_denied(self):
        with self.assertRaises(EvidenceError):
            self.check(self.chain[:-1])

    def test_dropping_from_the_front_denied(self):
        """Caught by the sequence check before linkage even gets a say: an event
        that says it is number two cannot be the first one submitted."""
        with self.assertRaises(EvidenceError) as caught:
            self.check(self.chain[1:])
        self.assertIn("reordered or has a gap", str(caught.exception))

    def test_linkage_break_denied(self):
        forged = self.write_chain("task-3", ["a", "b"])
        with self.assertRaises(EvidenceError) as caught:
            validate_chain("task-1", [self.chain[0], forged[1]], self.trusted,
                           store=self.store, now=NOW + 10)
        self.assertIn("binding mismatch", str(caught.exception))

    def test_reordered_chain_denied(self):
        with self.assertRaises(EvidenceError):
            self.check([self.chain[0], self.chain[2], self.chain[1], self.chain[3]])

    def test_duplicate_event_denied(self):
        with self.assertRaises(EvidenceError) as caught:
            self.check([*self.chain, self.chain[-1]])
        self.assertIn("unique", str(caught.exception))

    def test_empty_chain_denied(self):
        with self.assertRaises(EvidenceError):
            self.check([])


class HeadAuthorityTests(EvidenceFixture):
    def test_builder_signed_head_denied(self):
        """Under HMAC the builder held the key and could mint this head itself.
        The whole anchor rests on it being unable to."""
        self.write_head("task-1", "b" * 64, 2, 2, authority="builder")
        with self.assertRaises(EvidenceError) as caught:
            self.check(self.chain)
        self.assertIn("may not sign evidence-head", str(caught.exception))

    def test_verifier_signed_head_denied(self):
        self.write_head("task-1", "b" * 64, 4, 4, authority="verifier")
        with self.assertRaises(EvidenceError):
            self.check(self.chain)

    def test_missing_head_denied(self):
        """A missing head must fail, not read as an empty chain: otherwise you
        omit the head and then omit whatever else you like."""
        (self.store / "task-1.head.json").unlink()
        with self.assertRaises(EvidenceError) as caught:
            self.check(self.chain)
        self.assertIn("not found", str(caught.exception))

    def test_tampered_head_denied(self):
        document = json.loads((self.store / "task-1.head.json").read_text(encoding="utf-8"))
        document["payload"]["event_count"] = 2
        (self.store / "task-1.head.json").write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaises(EvidenceError) as caught:
            self.check(self.chain)
        self.assertIn("signature", str(caught.exception))

    def test_head_for_another_task_denied(self):
        payload = {
            "artifact_type": "evidence-head",
            "key_id": self.keys["evidence-recorder"]["key_id"],
            "task_id": "task-other", "final_event_hash": "c" * 64,
            "event_count": 4, "last_sequence": 4, "issued_at_epoch": NOW,
        }
        (self.store / "task-1.head.json").write_text(
            json.dumps(sign_payload(self.keys["evidence-recorder"]["private_key"], payload)),
            encoding="utf-8")
        with self.assertRaises(EvidenceError) as caught:
            self.check(self.chain)
        self.assertIn("different task", str(caught.exception))

    def test_head_count_disagreeing_with_its_sequence_denied(self):
        self.write_head("task-1", "d" * 64, 4, 9)
        with self.assertRaises(EvidenceError):
            self.check(self.chain)

    def test_head_naming_a_different_final_hash_denied(self):
        self.write_head("task-1", "e" * 64, 4, 4)
        with self.assertRaises(EvidenceError) as caught:
            self.check(self.chain)
        self.assertIn("does not end at the signed head", str(caught.exception))

    def test_head_loads_cleanly(self):
        head = load_head(self.store, "task-1", self.trusted, now=NOW + 10)
        self.assertEqual(head.event_count, 4)
        self.assertEqual(head.last_sequence, 4)


class EventShapeTests(EvidenceFixture):
    def test_event_signed_by_the_builder_denied(self):
        payload = {
            "artifact_type": "evidence-event",
            "key_id": self.keys["builder"]["key_id"], "event_id": "task-1-e1",
            "sequence": 1, "previous_event_hash": None, "task_id": "task-1",
            "event_type": "invented", "agent_id": "agt-p01-r01",
            "payload_hash": "a" * 64, "issued_at_epoch": NOW,
        }
        (self.store / "task-1-e1.json").write_text(
            json.dumps(sign_payload(self.keys["builder"]["private_key"], payload)),
            encoding="utf-8")
        with self.assertRaises(EvidenceError):
            self.check(self.chain)

    def test_event_for_another_task_denied(self):
        other = self.write_chain("task-2", ["work-started"])
        with self.assertRaises(EvidenceError) as caught:
            self.check([other[0]])
        self.assertIn("binding mismatch", str(caught.exception))

    def test_missing_event_denied(self):
        (self.store / self.chain[1]).with_suffix(".json").unlink(missing_ok=True)
        (self.store / f"{self.chain[1]}.json").unlink(missing_ok=True)
        with self.assertRaises(EvidenceError) as caught:
            self.check(self.chain)
        self.assertIn("not found", str(caught.exception))


class CriterionEvidenceTests(unittest.TestCase):
    def test_criterion_inside_the_chain_accepted(self):
        validate_criterion_evidence("t", ["e1", "e2"], ["e1", "e2", "e3"])

    def test_criterion_citing_outside_the_chain_denied(self):
        with self.assertRaises(EvidenceError) as caught:
            validate_criterion_evidence("t", ["e1", "e9"], ["e1", "e2"])
        self.assertIn("outside the validated chain", str(caught.exception))




class CompletionIntegrationTests(EvidenceFixture):
    """bro_completion.validate_evidence_chain had never executed under test: every
    test that would have run it mocked it out, which is exactly how a
    backward-only linkage check survived. These run the real body."""

    def setUp(self):
        super().setUp()
        # The production wrapper checks key validity against the real clock, so
        # the fixture registry has to be valid now rather than at the frozen NOW
        # the rest of these tests use.
        import time as _time
        real_now = int(_time.time())
        self.repo = self.tmp / "repo"
        (self.repo / "config").mkdir(parents=True)
        (self.repo / "config" / "trusted-keys.json").write_text(
            json.dumps(build_registry(list(self.keys.values()), real_now - 60, YEAR)),
            encoding="utf-8")
        import bro_completion
        self.completion = bro_completion

    def chain_check(self, ids, task_id="task-1"):
        with unittest.mock.patch.dict(os.environ,
                                      {"BRO_EVIDENCE_STORE": str(self.store)}):
            return self.completion.validate_evidence_chain(task_id, ids, self.repo)

    def test_full_chain_passes_the_real_completion_wrapper(self):
        self.assertEqual(len(self.chain_check(self.chain)), 64)

    def test_truncated_chain_denied_by_the_real_wrapper(self):
        from bro_completion import CompletionError
        with self.assertRaises(CompletionError) as caught:
            self.chain_check(self.chain[:2])
        self.assertIn("incomplete", str(caught.exception))

    def test_builder_signed_head_denied_by_the_real_wrapper(self):
        from bro_completion import CompletionError
        self.write_head("task-1", "b" * 64, 4, 4, authority="builder")
        with self.assertRaises(CompletionError) as caught:
            self.chain_check(self.chain)
        self.assertIn("may not sign evidence-head", str(caught.exception))

    def test_missing_registry_fails_closed(self):
        from bro_completion import CompletionError
        (self.repo / "config" / "trusted-keys.json").unlink()
        with self.assertRaises(CompletionError):
            self.chain_check(self.chain)

    def test_evidence_store_inside_the_repository_denied(self):
        from bro_completion import CompletionError
        inside = self.repo / "store"
        inside.mkdir()
        with unittest.mock.patch.dict(os.environ, {"BRO_EVIDENCE_STORE": str(inside)}):
            with self.assertRaises(CompletionError):
                self.completion.validate_evidence_chain("task-1", self.chain, self.repo)

if __name__ == "__main__":
    unittest.main()
