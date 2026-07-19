"""Shadow (observe-only) enforcement for the PreToolUse / PostToolUse wall.

Operational rollout, step 1. BRO_ENFORCEMENT=shadow makes the wall observe rather
than block: a decision it would have blocked is recorded to the append-only
BRO_SHADOW_LEDGER instead of being enforced, so an operator can measure a rollout
against real traffic before flipping to enforce.

These tests exercise the shadow wrapper in runtime/bro_hook.py directly. The real
authorization verdict is stubbed — tests/test_full_execution_transaction_e2e.py
already proves authorize_tool's behaviour end to end; here the concern is only
what the wall DOES with a verdict under each enforcement setting. The load-bearing
property is fail-safety: shadow softens a block ONLY when it was durably recorded,
so a missing, in-repo, or unwritable ledger still enforces — a bypass that cannot
be recorded is a bypass that is not granted.
"""
import contextlib
import io
import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

import bro_audit_log
import bro_hook

PAYLOAD = {"tool_name": "Write", "tool_input": {"file_path": "docs/x.md"},
           "tool_use_id": "toolu_shadow_1", "session_id": "sess-shadow"}
BASE_ENV = {"BRO_MODE": "work", "BRO_ROLE": "specialist",
            "BRO_AGENT_ID": "agt-p01-r02", "BRO_SESSION_ID": "sess-shadow"}


class ShadowModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="bro-shadow-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.ledger = self.tmp / "shadow-ledger.jsonl"

    def _run_pretool(self, env, *, verdict=(False, "policy denied: out of scope")):
        merged = {**BASE_ENV, **env}
        # keys explicitly absent must not leak from the ambient environment
        for key in ("BRO_ENFORCEMENT", "BRO_SHADOW_LEDGER"):
            if key not in merged:
                merged[key] = ""
        out = io.StringIO()
        with patch.object(sys, "argv", ["bro_hook.py", "pre-tool"]), \
                patch("sys.stdin", io.StringIO(json.dumps(PAYLOAD))), \
                patch("bro_hook.receipt_fresh", return_value=(True, "fresh")), \
                patch("bro_hook.authorize_tool", return_value=verdict), \
                patch.dict(os.environ, merged, clear=False), \
                contextlib.redirect_stdout(out):
            for key, value in merged.items():
                if value == "":
                    os.environ.pop(key, None)
            rc = bro_hook.main()
        self.assertEqual(rc, 0)
        text = out.getvalue().strip()
        return json.loads(text) if text else None

    def _is_deny(self, result):
        return bool(result) and result.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"

    def test_enforce_mode_denies(self):
        result = self._run_pretool({})  # BRO_ENFORCEMENT unset -> enforce
        self.assertTrue(self._is_deny(result))
        self.assertFalse(self.ledger.exists())

    def test_shadow_with_ledger_observes_instead_of_blocking(self):
        result = self._run_pretool({"BRO_ENFORCEMENT": "shadow", "BRO_SHADOW_LEDGER": str(self.ledger)})
        self.assertFalse(self._is_deny(result))
        self.assertIn("[SHADOW]", result["hookSpecificOutput"]["additionalContext"])
        # the would-block decision is on the append-only chain, and the chain verifies
        self.assertEqual(bro_audit_log.verify(self.ledger), 1)
        records = bro_audit_log.read_all(self.ledger)
        self.assertEqual(records[0]["kind"], "shadow-would-block")
        self.assertEqual(records[0]["payload"]["kind"], "pre-tool-deny")
        self.assertIn("out of scope", records[0]["payload"]["reason"])
        self.assertEqual(records[0]["payload"]["tool"], "Write")

    def test_shadow_without_ledger_still_enforces(self):
        # shadow enabled but no ledger: a bypass we cannot record is not granted
        result = self._run_pretool({"BRO_ENFORCEMENT": "shadow"})
        self.assertTrue(self._is_deny(result))

    def test_shadow_with_in_repo_ledger_still_enforces(self):
        # the audit ledger must live outside the repo; an in-repo path is rejected
        # by append, so _observe fails to record and the block is enforced
        in_repo = ROOT / "shadow-ledger-should-not-exist.jsonl"
        self.addCleanup(lambda: in_repo.exists() and in_repo.unlink())
        result = self._run_pretool({"BRO_ENFORCEMENT": "shadow", "BRO_SHADOW_LEDGER": str(in_repo)})
        self.assertTrue(self._is_deny(result))
        self.assertFalse(in_repo.exists())

    def test_shadow_does_not_record_or_alter_an_allow(self):
        result = self._run_pretool(
            {"BRO_ENFORCEMENT": "shadow", "BRO_SHADOW_LEDGER": str(self.ledger)},
            verdict=(True, "allowed"))
        # an allow emits no PreToolUse decision and writes nothing: shadow observes
        # only what enforcement would have blocked
        self.assertIsNone(result)
        self.assertFalse(self.ledger.exists())

    def test_shadow_records_accumulate_on_the_chain(self):
        env = {"BRO_ENFORCEMENT": "shadow", "BRO_SHADOW_LEDGER": str(self.ledger)}
        self._run_pretool(env, verdict=(False, "policy denied: first"))
        self._run_pretool(env, verdict=(False, "policy denied: second"))
        self.assertEqual(bro_audit_log.verify(self.ledger), 2)
        reasons = [r["payload"]["reason"] for r in bro_audit_log.read_all(self.ledger)]
        self.assertTrue(any("first" in r for r in reasons))
        self.assertTrue(any("second" in r for r in reasons))


if __name__ == "__main__":
    unittest.main()
