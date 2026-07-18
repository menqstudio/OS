import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

import bro_stop_controller
from bro_audit_log import AuditError, append, read_all, verify
from bro_stop_controller import is_group_alive, list_registered, register, stop_all


class AuditLedgerTests(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="bro-audit-"))
        self.ledger = self.dir / "audit.jsonl"

    def test_append_then_verify_chain(self):
        append(self.ledger, "approval", {"action": "git-push", "target": "main"})
        append(self.ledger, "incident", {"detail": "something"})
        self.assertEqual(verify(self.ledger), 2)

    def test_payload_secret_is_redacted(self):
        append(self.ledger, "incident", {"detail": "leaked token=ghp_1234567890abcdefghij1234ABCD"})
        raw = self.ledger.read_text(encoding="utf-8")
        self.assertNotIn("ghp_1234567890abcdefghij1234ABCD", raw)
        self.assertIn("REDACTED", raw)

    def test_tamper_is_detected(self):
        import json
        append(self.ledger, "a", {"x": 1})
        append(self.ledger, "b", {"x": 2})
        lines = self.ledger.read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[0])
        rec["payload"]["x"] = 999  # change the value but keep the stored hash
        lines[0] = json.dumps(rec, sort_keys=True)
        self.ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaises(AuditError):
            verify(self.ledger)

    def test_tail_truncation_is_detected(self):
        append(self.ledger, "a", {"x": 1})
        append(self.ledger, "b", {"x": 2})
        lines = self.ledger.read_text(encoding="utf-8").splitlines()
        self.ledger.write_text(lines[0] + "\n", encoding="utf-8")  # drop last, keep head
        with self.assertRaises(AuditError):
            verify(self.ledger)

    def test_ledger_inside_repo_is_refused(self):
        with self.assertRaises(AuditError):
            append(ROOT / "inside.jsonl", "x", {}, repo_root=ROOT)


class StopControllerTests(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="bro-stop-"))
        self.registry = self.dir / "processes.jsonl"
        self.audit = self.dir / "incidents.jsonl"

    @unittest.skipUnless(
        hasattr(os, "killpg"),
        "STOP Controller manages POSIX process groups (os.killpg) and reads "
        "/proc; the real-process test is Linux/POSIX-only",
    )
    def test_stops_a_real_process_group(self):
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
        )
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        # A session leader's pgid equals its pid.
        register(self.registry, "task-1", proc.pid, proc.pid)
        report = stop_all(self.registry, self.audit)
        self.assertTrue(any(e["pid"] == proc.pid for e in report["stopped"]))
        proc.wait(timeout=5)
        self.assertFalse(is_group_alive(proc.pid))

    def test_unstoppable_process_is_recorded_as_incident(self):
        register(self.registry, "task-stuck", 424242, 424242)
        with patch.object(bro_stop_controller, "terminate_group", return_value=False):
            report = stop_all(self.registry, self.audit, repo_root=ROOT)
        self.assertEqual(len(report["unstopped"]), 1)
        records = read_all(self.audit)
        self.assertTrue(any(r["kind"] == "unstopped-process" for r in records))
        self.assertEqual(verify(self.audit), len(records))

    def test_registry_round_trips(self):
        register(self.registry, "t", 10, 10)
        self.assertEqual(list_registered(self.registry)[0]["task_id"], "t")


if __name__ == "__main__":
    unittest.main()
