"""§7 durable evidence-head anti-rollback floor — the A–E CAS matrix (in-process, cross-platform).

Drives apply_head_floor() directly against a temp signer-owned floor DB: bootstrap, idempotent
re-sign, rollback (stale_evidence), fork, unchanged re-anchor, valid prefix-extend, and the
degenerate-head guard. The full accept->sign E2E through the floor runs on Linux CI.
"""
from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
for sub in ("runtime", "tools"):
    sys.path.insert(0, str(ROOT / sub))

from brops_governed_signer import apply_head_floor, GovernedSignRefused  # noqa: E402

H1 = "a" * 64
H2 = "b" * 64
H3 = "c" * 64


class HeadFloorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = pathlib.Path(self.tmp.name) / "floor.db"
        self.now = 1_800_000_000_000

    def tearDown(self):
        self.tmp.cleanup()

    def _floor(self, hs, ec, ls, feh, detailed=None):
        apply_head_floor(self.db, "install", "task-1", hs, ec, ls, feh, self.now, detailed)

    def test_bootstrap_then_idempotent_resign(self):
        self._floor(1, 1, 1, H1)                 # bootstrap
        self._floor(1, 1, 1, H1)                 # B: identical re-sign is idempotent (no raise)

    def test_rollback_to_lower_head_sequence_is_stale(self):
        self._floor(3, 1, 1, H1)                 # high-water 3
        with self.assertRaises(GovernedSignRefused) as ctx:
            self._floor(2, 1, 1, H1)             # A: older signed head
        self.assertEqual(ctx.exception.reason, "stale_evidence")

    def test_same_head_sequence_different_content_is_fork(self):
        self._floor(1, 1, 1, H1)
        with self.assertRaises(GovernedSignRefused) as ctx:
            self._floor(1, 1, 1, H2)             # B fork: same head, different final hash
        self.assertEqual(ctx.exception.reason, "evidence_fork")

    def test_unchanged_reanchor_advances_head_only(self):
        self._floor(1, 1, 1, H1)
        self._floor(5, 1, 1, H1)                 # C: higher head, identical content → advance (no raise)
        # a subsequent lower head is now stale against the advanced high-water
        with self.assertRaises(GovernedSignRefused) as ctx:
            self._floor(4, 1, 1, H1)
        self.assertEqual(ctx.exception.reason, "stale_evidence")

    def test_valid_prefix_extension_advances(self):
        self._floor(1, 1, 1, H1)                 # stored chain of 1 ending at H1
        detailed = {"event_count": 2, "event_hashes": [H1, H2], "previous_event_hashes": [None, H1]}
        self._floor(2, 2, 2, H2, detailed)       # D: new 2-event chain reproduces the stored prefix

    def test_extension_missing_prefix_is_fork(self):
        self._floor(1, 1, 1, H1)
        bad = {"event_count": 2, "event_hashes": [H3, H2], "previous_event_hashes": [None, H3]}
        with self.assertRaises(GovernedSignRefused) as ctx:
            self._floor(2, 2, 2, H2, bad)        # D fail: index-0 hash != stored final_event_hash
        self.assertEqual(ctx.exception.reason, "evidence_fork")

    def test_higher_head_divergent_content_no_extension_is_fork(self):
        self._floor(1, 1, 1, H1)
        with self.assertRaises(GovernedSignRefused) as ctx:
            self._floor(2, 1, 1, H2)             # E: higher head, same count, different content
        self.assertEqual(ctx.exception.reason, "evidence_fork")

    def test_degenerate_head_is_fork(self):
        # <1 counts, last!=count, wrong-length hash, AND a 64-char NON-hex final hash.
        for hs, ec, ls, feh in [(0, 1, 1, H1), (1, 1, 0, H1), (1, 2, 1, H1),
                                (1, 1, 1, "x" * 10), (1, 1, 1, "z" * 64), (1, 1, 1, "A" * 64)]:
            with self.assertRaises(GovernedSignRefused) as ctx:
                self._floor(hs, ec, ls, feh)
            self.assertEqual(ctx.exception.reason, "evidence_fork")

    def test_concurrent_advances_serialize_without_lost_update_or_lock_error(self):
        # §7 concurrency: apply_head_floor runs its A–E matrix inside a single BEGIN IMMEDIATE tx on a
        # WAL db with a busy timeout, so racing signers SERIALIZE — no "database is locked" crash and
        # no lost update. Bootstrap at head 1, then race 16 threads each attempting the SAME case-C
        # advance to head 2 (identical content, higher head). The first to grab the write lock advances
        # the high-water; every other thread blocks on BEGIN IMMEDIATE, then re-reads head 2 and is an
        # idempotent no-op. Invariant: zero unexpected exceptions and the stored high-water is EXACTLY 2.
        import sqlite3
        import threading

        self._floor(1, 1, 1, H1)                                     # bootstrap high-water 1
        start = threading.Barrier(16)
        errors: list[BaseException] = []

        def advance() -> None:
            start.wait()                                             # maximize contention
            try:
                self._floor(2, 1, 1, H1)                            # C: same content, head 1 -> 2
            except GovernedSignRefused:
                # a legitimate matrix outcome (never expected here, but not a lock/corruption bug)
                pass
            except BaseException as exc:                            # sqlite "database is locked", etc.
                errors.append(exc)

        threads = [threading.Thread(target=advance) for _ in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        self.assertEqual(errors, [], f"concurrent floor writes raised: {errors!r}")
        conn = sqlite3.connect(str(self.db))
        try:
            (hw,) = conn.execute(
                "SELECT highest_head_sequence FROM governed_evidence_head_floor "
                "WHERE install_id='install' AND task_id='task-1'").fetchone()
        finally:
            conn.close()
        self.assertEqual(hw, 2)                                      # advanced exactly once, no lost update
        # the floor now holds: any older head is stale (proves the concurrent advance was durable).
        with self.assertRaises(GovernedSignRefused) as ctx:
            self._floor(1, 1, 1, H1)
        self.assertEqual(ctx.exception.reason, "stale_evidence")


if __name__ == "__main__":
    unittest.main()
