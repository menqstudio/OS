"""The evidence store holds more than one kind of evidence-recorder statement.

`artifact_type` names the AUTHORITY that may sign a document, not its shape:
`bro_signature.ARTIFACT_AUTHORITY` maps `evidence-event` to the evidence-recorder, and
the recorder signs two different true statements under it — a chain event, and an
execution receipt (`tools/bro_run_receipt.run_and_sign`, verified by
`bro_receipt.verify_receipt` as an `evidence-event` deliberately, because that is the
authority a receipt must carry).

The durable runtime keeps both in the same flat store. `bro_evidence._scan_events` read
the artifact type as if it were a shape, so the governance read surface
(`read_chain` / `read_chains`) raised "unexpected shape" on the first receipt it met and
was unusable on any real store. The receipt was not mislabelled; the reader was too
narrow. These tests hold the reader to that.

The receipts here are produced by the REAL producer against a real git worktree, not by
a hand-written dict: a fixture that invents the shape would keep passing on the day the
producer changed it.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from bro_evidence import EvidenceError, read_chain, read_chains
from bro_run_receipt import run_and_sign
from bro_signature import load_trusted_keys
from broctl import build_registry, generate_key, sign_payload
from _operator_pin import use_operator_pin
from test_orchestration_runtime import AGENT, build_evidence

AUTHORITIES = ["operator-root", "issuer", "evidence-recorder", "builder",
               "verifier", "release"]
RUN_CMD = [sys.executable, "-c", "print('ok')"]


class SharedEvidenceStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        base = pathlib.Path(self.temporary.name)
        self.store = base / "evidence"
        self.store.mkdir()
        self.keys = {a: generate_key(a, f"dev-{a}", False) for a in AUTHORITIES}
        use_operator_pin(self, self.keys["operator-root"]["public_key"])
        registry_root = base / "registry"
        (registry_root / "config").mkdir(parents=True)
        self.now = int(time.time())
        (registry_root / "config" / "trusted-keys.json").write_text(
            json.dumps(build_registry(list(self.keys.values()), self.now - 60, 86400)),
            encoding="utf-8")
        self.trusted = load_trusted_keys(registry_root)

    def clean_repository(self) -> pathlib.Path:
        """A committed, clean worktree — `run_and_sign` refuses to attest a dirty one."""
        clean = pathlib.Path(self.temporary.name) / f"repo-{len(list(pathlib.Path(self.temporary.name).iterdir()))}"
        (clean / "tests").mkdir(parents=True)
        shutil.copy(ROOT / "tests" / "catalog.json", clean / "tests" / "catalog.json")
        for args in (["init", "-q"], ["config", "user.email", "t@e.com"],
                     ["config", "user.name", "t"]):
            subprocess.run(["git", "-C", str(clean), *args], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(clean), "add", "-A"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(clean), "commit", "-qm", "init"],
                       check=True, capture_output=True)
        return clean

    def drop_receipt(self, task_id: str) -> str:
        """One real execution receipt, in the same store as the chain."""
        document, _ = run_and_sign(RUN_CMD, key=self.keys["evidence-recorder"],
                                   task_id=task_id, root=self.clean_repository(),
                                   runner_id="runner", now=self.now)
        receipt_id = document["payload"]["receipt_id"]
        (self.store / f"{receipt_id}.json").write_text(json.dumps(document), encoding="utf-8")
        return receipt_id

    # --- the reader must see past a receipt, and only past a receipt ----------------

    def test_a_receipt_sharing_the_store_does_not_break_the_chain_read(self) -> None:
        ids = build_evidence(self.store, self.keys, "task-shared", 2)
        self.drop_receipt("task-shared")
        chain = read_chain(self.store, "task-shared", self.trusted)
        self.assertEqual([event["event_id"] for event in chain], ids)

    def test_the_receipt_is_not_smuggled_into_the_chain_as_an_event(self) -> None:
        """Skipping it must mean skipping it: a receipt is not a chain event, and a
        reader that counted it would break the head anchor it is checked against."""
        build_evidence(self.store, self.keys, "task-notevent", 2)
        receipt_id = self.drop_receipt("task-notevent")
        chain = read_chain(self.store, "task-notevent", self.trusted)
        self.assertEqual(len(chain), 2)
        self.assertNotIn(receipt_id, [event["event_id"] for event in chain])

    def test_many_chains_read_in_one_pass_survive_receipts_for_each(self) -> None:
        expected = {}
        for task_id in ("task-multi-a", "task-multi-b"):
            expected[task_id] = build_evidence(self.store, self.keys, task_id, 2)
            self.drop_receipt(task_id)
        chains = read_chains(self.store, list(expected), self.trusted)
        self.assertEqual({task: [event["event_id"] for event in events]
                          for task, events in chains.items()}, expected)

    def test_a_receipt_for_an_unread_task_is_still_ignored(self) -> None:
        build_evidence(self.store, self.keys, "task-only", 2)
        self.drop_receipt("task-other")
        self.assertEqual(len(read_chain(self.store, "task-only", self.trusted)), 2)

    # --- everything that is NOT a receipt is still a hard error ---------------------

    def test_a_document_claiming_to_be_an_event_in_neither_shape_is_refused(self) -> None:
        """Widening the reader must not become "skip anything unfamiliar": that is the
        silent truncation the anchor exists to prevent.

        This document has no `sequence` at all, which is what makes the field-set gate
        load-bearing rather than merely early: without it the scan reaches straight past
        the shape it never checked and dies indexing a field that is not there — an
        unhandled KeyError where a refusal belongs.
        """
        build_evidence(self.store, self.keys, "task-odd", 2)
        payload = {
            "artifact_type": "evidence-event",
            "key_id": self.keys["evidence-recorder"]["key_id"],
            "task_id": "task-odd", "event_id": "task-odd-x1",
            "surprise": "a field neither shape has",
        }
        (self.store / "task-odd-x1.json").write_text(
            json.dumps(sign_payload(self.keys["evidence-recorder"]["private_key"], payload)),
            encoding="utf-8")
        with self.assertRaises(EvidenceError) as caught:
            read_chain(self.store, "task-odd", self.trusted)
        self.assertIn("unexpected shape", str(caught.exception))

    def test_an_event_disguised_as_a_receipt_cannot_shorten_the_chain(self) -> None:
        """The shape is read before the signature, so rewriting an event into receipt
        shape does make the scan step over it. It cannot forge a shorter history: the
        chain still has to reproduce the signed head's count and final hash."""
        ids = build_evidence(self.store, self.keys, "task-hide", 2)
        receipt_shape = json.loads(
            (self.store / f"{self.drop_receipt('task-hide')}.json").read_text(encoding="utf-8"))
        receipt_shape["payload"]["task_id"] = "task-hide"
        (self.store / f"{ids[-1]}.json").write_text(json.dumps(receipt_shape), encoding="utf-8")
        with self.assertRaises(EvidenceError) as caught:
            read_chain(self.store, "task-hide", self.trusted)
        self.assertIn("incomplete", str(caught.exception))

    def test_a_receipt_shaped_document_that_is_not_signed_is_not_a_way_in(self) -> None:
        """A receipt is skipped because it is another statement, not because skipping is
        safe: it never becomes part of the chain, signed or not."""
        ids = build_evidence(self.store, self.keys, "task-unsigned", 2)
        document = json.loads(
            (self.store / f"{self.drop_receipt('task-unsigned')}.json").read_text(encoding="utf-8"))
        document["signature"] = "00" * 64
        (self.store / "rcpt-unsigned.json").write_text(json.dumps(document), encoding="utf-8")
        chain = read_chain(self.store, "task-unsigned", self.trusted)
        self.assertEqual([event["event_id"] for event in chain], ids)


if __name__ == "__main__":
    unittest.main()
