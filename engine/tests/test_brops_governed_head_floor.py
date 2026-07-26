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
        for hs, ec, ls, feh in [(0, 1, 1, H1), (1, 1, 0, H1), (1, 2, 1, H1), (1, 1, 1, "x" * 10)]:
            with self.assertRaises(GovernedSignRefused) as ctx:
                self._floor(hs, ec, ls, feh)
            self.assertEqual(ctx.exception.reason, "evidence_fork")


if __name__ == "__main__":
    unittest.main()
