"""Integrity-checked backup / restore for machine-local runtime state.

Operational rollout, step 3. The runtime's durable state (lease ledger, recovery
store, task-lock ledger, append-only audit / shadow ledgers) lives outside Git by
contract, so a host move must be able to carry it without losing or corrupting
the audit history. tools/bro_backup.py archives a named set of those stores with a
per-file checksum manifest and restores them with the manifest re-verified.

These tests prove the load-bearing property is integrity, not just copying: a
round trip is byte-faithful and the restored audit chain still verifies; a broken
ledger chain refuses to be archived; a tampered archive is caught before restore;
restore will not silently clobber; and an empty-destination / no-symlink guard
holds.
"""
import hashlib
import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))

import bro_audit_log
import bro_backup

NOW = 1_700_000_000


def _sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


class BackupRestoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="bro-backup-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        # A realistic external state set: an append-only shadow ledger (+head
        # sidecar) and a recovery store directory of transaction journals.
        self.ledger = self.tmp / "state" / "shadow-ledger.jsonl"
        self.ledger.parent.mkdir(parents=True)
        bro_audit_log.append(self.ledger, "shadow-would-block", {"reason": "one"})
        bro_audit_log.append(self.ledger, "shadow-would-block", {"reason": "two"})
        self.store = self.tmp / "state" / "recovery-store"
        self.store.mkdir()
        (self.store / "a.state.json").write_text(json.dumps({"phase": "PREPARED"}), encoding="utf-8")
        (self.store / "nested").mkdir()
        (self.store / "nested" / "b.state.json").write_text(json.dumps({"phase": "MUTATION_RECORDED"}), encoding="utf-8")
        self.sources = {"shadow": self.ledger, "recovery": self.store}

    def _backup(self, dest=None):
        dest = dest or (self.tmp / "archive")
        bro_backup.backup(self.sources, dest, now=NOW)
        return dest

    def test_round_trip_is_byte_faithful_and_chain_valid(self):
        archive = self._backup()
        bro_backup.verify_archive(archive)  # manifest + chains verify
        out = self.tmp / "restored"
        restored = bro_backup.restore(archive, {"shadow": out / "shadow", "recovery": out / "recovery"})
        self.assertEqual(restored, {"shadow": 2, "recovery": 2})  # ledger+head; two journals
        # byte-faithful
        self.assertEqual(_sha(out / "shadow" / "shadow-ledger.jsonl"), _sha(self.ledger))
        self.assertEqual(_sha(out / "recovery" / "nested" / "b.state.json"),
                         _sha(self.store / "nested" / "b.state.json"))
        # the restored append-only ledger still verifies through its head anchor
        self.assertEqual(bro_audit_log.verify(out / "shadow" / "shadow-ledger.jsonl"), 2)

    def test_broken_ledger_chain_refuses_backup(self):
        # tamper a record in the middle of the chain
        lines = self.ledger.read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[0]); rec["payload"] = {"reason": "forged"}
        lines[0] = json.dumps(rec, sort_keys=True)
        self.ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaises(bro_backup.BackupError):
            self._backup()

    def test_tampered_archive_is_caught_before_restore(self):
        archive = self._backup()
        target = archive / "recovery" / "a.state.json"
        target.write_text(json.dumps({"phase": "TAMPERED"}), encoding="utf-8")
        with self.assertRaises(bro_backup.BackupError):
            bro_backup.verify_archive(archive)
        with self.assertRaises(bro_backup.BackupError):
            bro_backup.restore(archive, {"recovery": self.tmp / "r2"})

    def test_restore_refuses_to_clobber_without_force(self):
        archive = self._backup()
        out = self.tmp / "restored"
        bro_backup.restore(archive, {"recovery": out / "recovery"})
        with self.assertRaises(bro_backup.BackupError):
            bro_backup.restore(archive, {"recovery": out / "recovery"})
        # force overwrites cleanly
        self.assertEqual(bro_backup.restore(archive, {"recovery": out / "recovery"}, force=True), {"recovery": 2})

    def test_nonempty_destination_is_refused(self):
        dest = self.tmp / "archive"
        dest.mkdir(); (dest / "stray").write_text("x", encoding="utf-8")
        with self.assertRaises(bro_backup.BackupError):
            self._backup(dest)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink unsupported")
    def test_symlink_in_source_is_refused(self):
        try:
            (self.store / "link.json").symlink_to(self.store / "a.state.json")
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation not permitted")
        with self.assertRaises(bro_backup.BackupError):
            self._backup()


if __name__ == "__main__":
    unittest.main()
