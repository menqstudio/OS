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


class RestoreTraversalTests(unittest.TestCase):
    """Security remediation, blocker 3 (audit: backup restore path traversal).

    A restore must never trust the manifest's paths. A crafted archive that names
    an entry `../…`, an absolute path, a symlink, or a duplicate must be rejected
    BEFORE any byte is written outside the target."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="bro-trav-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _archive(self, rel, *, content=b"pwned", place_at=None):
        """Craft an archive whose single entry has an attacker-chosen rel, with a
        payload placed so checksum verification would otherwise pass."""
        archive = self.tmp / "archive"; (archive / "s").mkdir(parents=True)
        payload = place_at if place_at is not None else (archive / "s" / rel)
        payload.parent.mkdir(parents=True, exist_ok=True)
        payload.write_bytes(content)
        manifest = {"schema": 1, "created_at_epoch": 0, "sources": {"s": {"kind": "dir", "files": [
            {"rel": rel, "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content), "audit_chain": None}]}}}
        (archive / bro_backup.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
        return archive

    def test_dotdot_traversal_is_rejected_before_write(self):
        archive = self._archive("../escape.txt", place_at=self.tmp / "archive" / "escape.txt")
        target = self.tmp / "target"; target.mkdir()
        with self.assertRaises(bro_backup.BackupError):
            bro_backup.restore(archive, {"s": target})
        # nothing was written outside the target
        self.assertFalse((self.tmp / "escape.txt").exists())
        self.assertFalse((target.parent / "escape.txt").exists())

    def test_absolute_path_entry_is_rejected(self):
        archive = self._archive("/tmp/bro-evil.txt", place_at=self.tmp / "archive" / "s" / "x")
        with self.assertRaises(bro_backup.BackupError):
            bro_backup.verify_archive(archive)

    def test_backslash_path_entry_is_rejected(self):
        archive = self._archive("..\\escape.txt", place_at=self.tmp / "archive" / "s" / "x")
        with self.assertRaises(bro_backup.BackupError):
            bro_backup.verify_archive(archive)

    def test_symlinked_archive_entry_is_rejected(self):
        archive = self.tmp / "archive"; (archive / "s").mkdir(parents=True)
        secret = self.tmp / "secret.txt"; secret.write_bytes(b"top")
        try:
            (archive / "s" / "link.txt").symlink_to(secret)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation not permitted")
        manifest = {"schema": 1, "created_at_epoch": 0, "sources": {"s": {"kind": "dir", "files": [
            {"rel": "link.txt", "sha256": hashlib.sha256(b"top").hexdigest(), "bytes": 3, "audit_chain": None}]}}}
        (archive / bro_backup.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(bro_backup.BackupError):
            bro_backup.verify_archive(archive)

    def test_duplicate_entry_is_rejected(self):
        archive = self.tmp / "archive"; (archive / "s").mkdir(parents=True)
        (archive / "s" / "a.txt").write_bytes(b"x")
        h = hashlib.sha256(b"x").hexdigest()
        manifest = {"schema": 1, "created_at_epoch": 0, "sources": {"s": {"kind": "dir", "files": [
            {"rel": "a.txt", "sha256": h, "bytes": 1, "audit_chain": None},
            {"rel": "a.txt", "sha256": h, "bytes": 1, "audit_chain": None}]}}}
        (archive / bro_backup.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(bro_backup.BackupError):
            bro_backup.verify_archive(archive)

    def test_source_directory_symlink_restores_nothing_outside(self):
        # archive/<source> is a symlink to an external directory; restoring it
        # would copy external files into the target. It must be rejected.
        archive = self.tmp / "archive"; archive.mkdir()
        external = self.tmp / "external"; external.mkdir()
        (external / "secret.txt").write_bytes(b"top")
        try:
            (archive / "s").symlink_to(external, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation not permitted")
        manifest = {"schema": 1, "created_at_epoch": 0, "sources": {"s": {"kind": "dir", "files": [
            {"rel": "secret.txt", "sha256": hashlib.sha256(b"top").hexdigest(), "bytes": 3, "audit_chain": None}]}}}
        (archive / bro_backup.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
        target = self.tmp / "target"; target.mkdir()
        with self.assertRaises(bro_backup.BackupError):
            bro_backup.restore(archive, {"s": target})
        self.assertFalse((target / "secret.txt").exists())

    def test_intermediate_symlink_component_is_rejected(self):
        archive = self.tmp / "archive"; (archive / "s").mkdir(parents=True)
        external = self.tmp / "ext"; external.mkdir(); (external / "f.txt").write_bytes(b"x")
        try:
            (archive / "s" / "sub").symlink_to(external, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation not permitted")
        manifest = {"schema": 1, "created_at_epoch": 0, "sources": {"s": {"kind": "dir", "files": [
            {"rel": "sub/f.txt", "sha256": hashlib.sha256(b"x").hexdigest(), "bytes": 1, "audit_chain": None}]}}}
        (archive / bro_backup.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(bro_backup.BackupError):
            bro_backup.verify_archive(archive)

    def test_dot_slash_duplicate_is_rejected(self):
        archive = self.tmp / "archive"; (archive / "s").mkdir(parents=True)
        (archive / "s" / "a.txt").write_bytes(b"x")
        h = hashlib.sha256(b"x").hexdigest()
        manifest = {"schema": 1, "created_at_epoch": 0, "sources": {"s": {"kind": "dir", "files": [
            {"rel": "a.txt", "sha256": h, "bytes": 1, "audit_chain": None},
            {"rel": "./a.txt", "sha256": h, "bytes": 1, "audit_chain": None}]}}}
        (archive / bro_backup.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(bro_backup.BackupError):
            bro_backup.verify_archive(archive)

    def test_malicious_source_name_is_rejected(self):
        archive = self.tmp / "archive"; archive.mkdir()
        manifest = {"schema": 1, "created_at_epoch": 0, "sources": {"../evil": {"kind": "dir", "files": [
            {"rel": "a.txt", "sha256": hashlib.sha256(b"x").hexdigest(), "bytes": 1, "audit_chain": None}]}}}
        (archive / bro_backup.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(bro_backup.BackupError):
            bro_backup.verify_archive(archive)

    def test_windows_drive_rel_is_rejected(self):
        # `C:/Windows/evil.txt` is not absolute under POSIX parsing, so it slipped
        # past `_safe_rel`; on a Windows restore host `target / "C:" / ...` resets
        # to the C: drive and escapes. Rejected deterministically on ANY host.
        for rel in ("C:/Windows/evil.txt", "C:evil.txt", "sub/C:/evil.txt", "sub/stream.txt:ads"):
            with self.assertRaises(bro_backup.BackupError, msg=rel):
                bro_backup._safe_rel(rel)

    def test_windows_drive_source_name_is_rejected(self):
        for name in ("C:", "C:evil", "D:"):
            with self.assertRaises(bro_backup.BackupError, msg=name):
                bro_backup._safe_name(name)

    def test_windows_drive_rel_rejected_through_verify(self):
        archive = self.tmp / "archive"; (archive / "s").mkdir(parents=True)
        (archive / "s" / "x").write_bytes(b"x")
        manifest = {"schema": 1, "created_at_epoch": 0, "sources": {"s": {"kind": "dir", "files": [
            {"rel": "C:/Windows/evil.txt", "sha256": hashlib.sha256(b"x").hexdigest(),
             "bytes": 1, "audit_chain": None}]}}}
        (archive / bro_backup.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(bro_backup.BackupError):
            bro_backup.verify_archive(archive)

    def test_ordinary_relative_paths_still_accepted(self):
        # a plain nested ledger path must remain valid — the drive guard is precise
        self.assertEqual(bro_backup._safe_rel("sub/dir/ledger.jsonl").as_posix(),
                         "sub/dir/ledger.jsonl")
        self.assertEqual(bro_backup._safe_name("recovery"), "recovery")


if __name__ == "__main__":
    unittest.main()
