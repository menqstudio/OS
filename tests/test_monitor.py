"""Live health monitor over the runtime's machine-local state.

Operational rollout, step 5. tools/bro_monitor.py reads (never mutates) the shadow
ledger, recovery store, execution-lease ledger and task-lock ledger and reports a
single health verdict a cron/alerting probe can act on. These tests prove the
verdict is driven by the conditions that actually need a human: a blocking
recovery journal, a quarantined lease, or a shadow ledger whose append-only chain
no longer verifies flip it to ATTENTION (non-zero exit); an empty or healthy set
is GREEN.
"""
import contextlib
import io
import json
import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))

import bro_audit_log
import bro_monitor


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="bro-monitor-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _shadow(self):
        led = self.tmp / "shadow.jsonl"
        bro_audit_log.append(led, "shadow-would-block", {"kind": "pre-tool-deny", "reason": "a"})
        bro_audit_log.append(led, "shadow-would-block", {"kind": "pre-tool-deny", "reason": "b"})
        bro_audit_log.append(led, "shadow-would-block", {"kind": "execution-settlement-block", "reason": "c"})
        return led

    def _recovery(self, *phases):
        store = self.tmp / "recovery"; store.mkdir(exist_ok=True)
        for i, phase in enumerate(phases):
            (store / f"{i:02d}.state.json").write_text(json.dumps({"phase": phase}), encoding="utf-8")
        return store

    def _leases(self, active=0, used=0, ambiguous=0):
        led = self.tmp / "leases"; led.mkdir(exist_ok=True)
        for kind, n in (("active", active), ("used", used), ("ambiguous", ambiguous)):
            for i in range(n):
                (led / f"{kind}{i}.{kind}").write_text("{}", encoding="utf-8")
        return led

    def test_empty_state_is_green(self):
        report = bro_monitor.scan()
        self.assertEqual(report["health"], "GREEN")
        self.assertEqual(report["shadow"]["records"], 0)
        self.assertEqual(report["recovery"]["journals"], 0)

    def test_shadow_records_are_counted_by_kind(self):
        report = bro_monitor.scan(shadow_ledger=self._shadow())
        self.assertEqual(report["shadow"]["records"], 3)
        self.assertTrue(report["shadow"]["chain_ok"])
        self.assertEqual(report["shadow"]["by_kind"],
                         {"pre-tool-deny": 2, "execution-settlement-block": 1})
        self.assertEqual(report["health"], "GREEN")  # would-blocks alone are not an alert

    def test_blocking_recovery_journal_raises_attention(self):
        store = self._recovery("MUTATION_RECORDED", "RECOVERY_REQUIRED", "PREPARED")
        report = bro_monitor.scan(recovery_store=store)
        self.assertEqual(report["recovery"]["journals"], 3)
        self.assertEqual(report["recovery"]["blocking"], 2)  # RECOVERY_REQUIRED + PREPARED
        self.assertEqual(report["recovery"]["by_phase"]["MUTATION_RECORDED"], 1)
        self.assertEqual(report["health"], "ATTENTION")

    def test_quarantined_lease_raises_attention(self):
        report = bro_monitor.scan(lease_ledger=self._leases(active=1, used=2, ambiguous=1))
        self.assertEqual(report["leases"], {"active": 1, "used": 2, "ambiguous": 1})
        self.assertEqual(report["health"], "ATTENTION")

    def test_broken_shadow_chain_raises_attention(self):
        led = self._shadow()
        lines = led.read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[0]); rec["payload"] = {"kind": "forged"}
        lines[0] = json.dumps(rec, sort_keys=True)
        led.write_text("\n".join(lines) + "\n", encoding="utf-8")
        report = bro_monitor.scan(shadow_ledger=led)
        self.assertFalse(report["shadow"]["chain_ok"])
        self.assertEqual(report["health"], "ATTENTION")

    def test_cli_exit_codes_and_json(self):
        store = self._recovery("PREPARED")
        with contextlib.redirect_stdout(io.StringIO()):
            attention = bro_monitor.main(["--recovery-store", str(store), "--json"])
            green = bro_monitor.main(["--recovery-store", str(self._recovery("MUTATION_RECORDED"))])
        self.assertEqual(attention, 2)  # blocking journal -> non-zero exit
        self.assertEqual(green, 0)


if __name__ == "__main__":
    unittest.main()
