import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))

from bro_receipt import (
    ReceiptError,
    catalog_sha256,
    transcript_sha256,
    verify_passing_receipt,
    verify_receipt,
    verify_receipt_set,
)
from bro_run_receipt import candidate_state, run_and_sign
from bro_signature import load_trusted_keys
from broctl import build_registry, generate_key, sign_payload

NOW = 1_700_000_000
YEAR = 365 * 24 * 60 * 60
AUTHORITIES = ["operator-root", "issuer", "evidence-recorder", "builder",
               "verifier", "release"]


class ReceiptFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="bro-rcpt-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

        self.keys = {a: generate_key(a, f"dev-{a}", False) for a in AUTHORITIES}
        self.registry_root = self.tmp / "registry"
        (self.registry_root / "config").mkdir(parents=True)
        (self.registry_root / "config" / "trusted-keys.json").write_text(
            json.dumps(build_registry(list(self.keys.values()), NOW, YEAR)),
            encoding="utf-8")
        self.trusted = load_trusted_keys(self.registry_root)

        # A repository whose catalog the verifier can read, standing in for ROOT.
        self.repo = self.tmp / "repo"
        (self.repo / "tests").mkdir(parents=True)
        (self.repo / "tests" / "catalog.json").write_text(
            json.dumps({"schema": 1, "tests": []}), encoding="utf-8")
        for args in (["init", "-q"], ["config", "user.email", "t@example.com"],
                     ["config", "user.name", "t"]):
            subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                           capture_output=True)
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"], check=True,
                       capture_output=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "init"],
                       check=True, capture_output=True)
        self.head, self.tree = candidate_state(self.repo)

    def make(self, command=None, key="evidence-recorder", task_id="task-1"):
        document, _ = run_and_sign(
            command or [sys.executable, "-c", "print('ok')"],
            key=self.keys[key], task_id=task_id, root=self.repo,
            runner_id="test-runner", now=NOW)
        return document

    def check(self, document, **overrides):
        kwargs = dict(task_id="task-1", candidate_head=self.head,
                      candidate_tree=self.tree, root=self.repo, now=NOW + 10)
        kwargs.update(overrides)
        return verify_receipt(document, self.trusted, **kwargs)


class TranscriptTests(unittest.TestCase):
    def test_line_endings_do_not_change_the_digest(self):
        """CI runs Windows and Linux; a receipt must verify on both."""
        self.assertEqual(transcript_sha256("a\r\nb"), transcript_sha256("a\nb"))

    def test_content_changes_the_digest(self):
        self.assertNotEqual(transcript_sha256("284 passed"), transcript_sha256("283 passed"))


class SigningTests(ReceiptFixture):
    def test_receipt_verifies(self):
        payload = self.check(self.make())
        self.assertEqual(payload["exit_code"], 0)
        self.assertEqual(payload["candidate_head"], self.head)
        self.assertEqual(payload["runner_id"], "test-runner")

    def test_runner_reads_head_from_git_not_from_its_caller(self):
        payload = self.check(self.make())
        self.assertEqual(payload["candidate_head"], self.head)
        self.assertEqual(payload["candidate_tree"], self.tree)

    def test_builder_key_may_not_sign_a_receipt(self):
        with self.assertRaises(ReceiptError) as caught:
            self.make(key="builder")
        self.assertIn("evidence-recorder authority", str(caught.exception))

    def test_verifier_key_may_not_sign_a_receipt(self):
        with self.assertRaises(ReceiptError):
            self.make(key="verifier")

    def test_dirty_worktree_refused(self):
        (self.repo / "dirt.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(ReceiptError) as caught:
            self.make()
        self.assertIn("dirty", str(caught.exception))

    def test_failing_command_is_recorded_honestly(self):
        """A receipt records the outcome; it does not launder it."""
        document = self.make([sys.executable, "-c", "raise SystemExit(3)"])
        payload = self.check(document)
        self.assertEqual(payload["exit_code"], 3)


class VerificationTests(ReceiptFixture):
    def test_wrong_task_denied(self):
        with self.assertRaises(ReceiptError) as caught:
            self.check(self.make(), task_id="other")
        self.assertIn("different task", str(caught.exception))

    def test_wrong_head_denied(self):
        with self.assertRaises(ReceiptError) as caught:
            self.check(self.make(), candidate_head="b" * 40)
        self.assertIn("different HEAD", str(caught.exception))

    def test_wrong_tree_denied(self):
        with self.assertRaises(ReceiptError) as caught:
            self.check(self.make(), candidate_tree="c" * 40)
        self.assertIn("different tree", str(caught.exception))

    def test_tampered_transcript_hash_denied(self):
        document = self.make()
        document["payload"]["stdout_sha256"] = "0" * 64
        with self.assertRaises(ReceiptError) as caught:
            self.check(document)
        self.assertIn("signature", str(caught.exception))

    def test_tampered_exit_code_denied(self):
        """Turning a red run green is the attack this exists to stop."""
        document = self.make([sys.executable, "-c", "raise SystemExit(1)"])
        document["payload"]["exit_code"] = 0
        with self.assertRaises(ReceiptError):
            self.check(document)

    def test_changed_catalog_denied(self):
        document = self.make()
        (self.repo / "tests" / "catalog.json").write_text(
            json.dumps({"schema": 1, "tests": [{"id": "new"}]}), encoding="utf-8")
        with self.assertRaises(ReceiptError) as caught:
            self.check(document)
        self.assertIn("different test catalog", str(caught.exception))

    def test_unsigned_receipt_denied(self):
        with self.assertRaises(ReceiptError):
            self.check({"payload": {"task_id": "task-1"}, "signature": "00" * 64})

    def test_missing_field_denied(self):
        """Signed, so the signature passes and the shape check is what refuses."""
        payload = dict(self.make()["payload"])
        del payload["runner_id"]
        document = sign_payload(self.keys["evidence-recorder"]["private_key"], payload)
        with self.assertRaises(ReceiptError) as caught:
            self.check(document)
        self.assertIn("missing fields", str(caught.exception))

    def test_smuggled_field_denied(self):
        payload = dict(self.make()["payload"], note="trust me")
        document = sign_payload(self.keys["evidence-recorder"]["private_key"], payload)
        with self.assertRaises(ReceiptError) as caught:
            self.check(document)
        self.assertIn("unexpected fields", str(caught.exception))

    def test_receipt_from_the_future_denied(self):
        payload = dict(self.make()["payload"], started_at_epoch=NOW + 7200,
                       finished_at_epoch=NOW + 7300)
        document = sign_payload(self.keys["evidence-recorder"]["private_key"], payload)
        with self.assertRaises(ReceiptError) as caught:
            self.check(document)
        self.assertIn("future", str(caught.exception))

    def test_finished_before_started_denied(self):
        payload = dict(self.make()["payload"], finished_at_epoch=NOW - 5)
        document = sign_payload(self.keys["evidence-recorder"]["private_key"], payload)
        with self.assertRaises(ReceiptError) as caught:
            self.check(document)
        self.assertIn("before it started", str(caught.exception))


class PassingReceiptTests(ReceiptFixture):
    def kwargs(self):
        return dict(task_id="task-1", candidate_head=self.head,
                    candidate_tree=self.tree, root=self.repo, now=NOW + 10)

    def test_passing_receipt_accepted(self):
        verify_passing_receipt(self.make(), self.trusted, **self.kwargs())

    def test_failing_receipt_rejected(self):
        document = self.make([sys.executable, "-c", "raise SystemExit(2)"])
        with self.assertRaises(ReceiptError) as caught:
            verify_passing_receipt(document, self.trusted, **self.kwargs())
        self.assertIn("failing run", str(caught.exception))

    def test_required_command_set_must_all_have_passed(self):
        """Otherwise a builder runs the one cheap command it knows will pass."""
        cheap = [sys.executable, "-c", "print('ok')"]
        suite = [sys.executable, "-c", "print('suite')"]
        documents = [self.make(cheap)]
        with self.assertRaises(ReceiptError) as caught:
            verify_receipt_set(documents, self.trusted,
                               required_commands=[cheap, suite], **self.kwargs())
        self.assertIn("no passing receipt for required command", str(caught.exception))

    def test_full_required_set_accepted(self):
        cheap = [sys.executable, "-c", "print('ok')"]
        suite = [sys.executable, "-c", "print('suite')"]
        documents = [self.make(cheap), self.make(suite)]
        payloads = verify_receipt_set(documents, self.trusted,
                                      required_commands=[cheap, suite], **self.kwargs())
        self.assertEqual(len(payloads), 2)


class CatalogTests(ReceiptFixture):
    def test_catalog_digest_tracks_the_file(self):
        before = catalog_sha256(self.repo)
        (self.repo / "tests" / "catalog.json").write_text(
            json.dumps({"schema": 1, "tests": [{"id": "x"}]}), encoding="utf-8")
        self.assertNotEqual(before, catalog_sha256(self.repo))

    def test_missing_catalog_fails_closed(self):
        (self.repo / "tests" / "catalog.json").unlink()
        with self.assertRaises(ReceiptError):
            catalog_sha256(self.repo)


if __name__ == "__main__":
    unittest.main()
