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

    def _lease_record(self, i):
        # a well-formed lease record carries the identity fields the writer emits
        return json.dumps({"schema": 1, "lease_id_sha256": f"{i:064x}"}, sort_keys=True)

    def _leases(self, active=0, used=0, ambiguous=0):
        led = self.tmp / "leases"; led.mkdir(exist_ok=True)
        for kind, n in (("active", active), ("used", used), ("ambiguous", ambiguous)):
            for i in range(n):
                (led / f"{kind}{i}.{kind}").write_text(self._lease_record(i), encoding="utf-8")
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
        self.assertEqual(report["leases"], {"active": 1, "used": 2, "ambiguous": 1, "degraded": 0})
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

    # --- blocker 4: corrupt/unreadable/unrecognised state must fail closed ---
    def test_unreadable_journal_raises_attention(self):
        # the exact reproduced case: an unreadable journal must not report GREEN
        store = self.tmp / "recovery"; store.mkdir()
        (store / "bad.state.json").write_text("{ this is not json", encoding="utf-8")
        report = bro_monitor.scan(recovery_store=store)
        self.assertEqual(report["recovery"]["by_phase"], {"unreadable": 1})
        self.assertEqual(report["recovery"]["degraded"], 1)
        self.assertEqual(report["health"], "ATTENTION")

    def test_unrecognised_phase_raises_attention(self):
        store = self._recovery("MUTATION_RECORDED", "SOMETHING_WEIRD")
        report = bro_monitor.scan(recovery_store=store)
        self.assertEqual(report["recovery"]["degraded"], 1)   # the unknown phase
        self.assertEqual(report["recovery"]["blocking"], 0)
        self.assertEqual(report["health"], "ATTENTION")

    def test_missing_phase_field_raises_attention(self):
        store = self.tmp / "recovery"; store.mkdir()
        (store / "x.state.json").write_text(json.dumps({"task_id": "t"}), encoding="utf-8")  # no phase
        report = bro_monitor.scan(recovery_store=store)
        self.assertEqual(report["recovery"]["degraded"], 1)
        self.assertEqual(report["health"], "ATTENTION")

    def test_resting_phases_stay_green(self):
        store = self._recovery("MUTATION_RECORDED", "REWORK_REQUIRED")
        report = bro_monitor.scan(recovery_store=store)
        self.assertEqual(report["recovery"]["degraded"], 0)
        self.assertEqual(report["recovery"]["blocking"], 0)
        self.assertEqual(report["health"], "GREEN")

    # --- blocker 4 review changes: configured-but-unusable / corrupt records ---
    def test_no_config_is_distinct_from_configured_missing(self):
        # nothing configured -> nothing to watch -> GREEN
        self.assertEqual(bro_monitor.scan()["health"], "GREEN")

    def test_configured_but_missing_store_raises_attention(self):
        missing = self.tmp / "does-not-exist"
        report = bro_monitor.scan(recovery_store=missing)
        self.assertEqual(report["health"], "ATTENTION")
        self.assertTrue(any("configured but missing" in a for a in report["attention"]))

    def test_store_path_of_wrong_type_raises_attention(self):
        f = self.tmp / "a-file"; f.write_text("x", encoding="utf-8")
        report = bro_monitor.scan(lease_ledger=f)  # a file where a dir is expected
        self.assertEqual(report["health"], "ATTENTION")

    def test_json_array_journal_does_not_crash_and_alerts(self):
        store = self.tmp / "recovery"; store.mkdir()
        (store / "arr.state.json").write_text("[]", encoding="utf-8")  # valid JSON, not an object
        report = bro_monitor.scan(recovery_store=store)
        self.assertEqual(report["recovery"]["degraded"], 1)
        self.assertEqual(report["health"], "ATTENTION")

    def test_corrupt_lease_record_raises_attention(self):
        led = self.tmp / "leases"; led.mkdir()
        (led / "x.active").write_text("{ not json", encoding="utf-8")
        report = bro_monitor.scan(lease_ledger=led)
        self.assertEqual(report["leases"]["degraded"], 1)
        self.assertEqual(report["health"], "ATTENTION")

    def test_corrupt_lock_record_raises_attention(self):
        led = self.tmp / "locks"; led.mkdir()
        (led / "x.json").write_text("[]", encoding="utf-8")  # not an object
        report = bro_monitor.scan(task_lock_ledger=led)
        self.assertEqual(report["locks"]["degraded"], 1)
        self.assertEqual(report["health"], "ATTENTION")

    def test_corrupt_shadow_ledger_does_not_crash_and_alerts(self):
        # the exact reproduced crash: a shadow ledger that is not valid JSON must
        # degrade to ATTENTION, not raise JSONDecodeError out of scan(). `read_all`
        # does a bare json.loads per line, so this is NOT an AuditError.
        led = self.tmp / "shadow.jsonl"
        led.write_text("{broken\n", encoding="utf-8")
        report = bro_monitor.scan(shadow_ledger=led)  # must not raise
        self.assertFalse(report["shadow"]["readable"])
        self.assertFalse(report["shadow"]["chain_ok"])
        self.assertEqual(report["health"], "ATTENTION")
        self.assertIn("shadow ledger is unreadable or corrupt", report["attention"])

    def test_empty_object_lease_record_is_degraded(self):
        # `{}` is well-formed JSON but not a lease; it must not count as healthy.
        led = self.tmp / "leases"; led.mkdir()
        (led / "x.active").write_text("{}", encoding="utf-8")
        report = bro_monitor.scan(lease_ledger=led)
        self.assertEqual(report["leases"]["active"], 1)
        self.assertEqual(report["leases"]["degraded"], 1)
        self.assertEqual(report["health"], "ATTENTION")

    def test_valid_lease_record_stays_green(self):
        led = self.tmp / "leases"; led.mkdir()
        (led / "x.active").write_text(self._lease_record(1), encoding="utf-8")
        report = bro_monitor.scan(lease_ledger=led)
        self.assertEqual(report["leases"], {"active": 1, "used": 0, "ambiguous": 0, "degraded": 0})
        self.assertEqual(report["health"], "GREEN")

    def test_non_object_shadow_shapes_do_not_crash_and_alert(self):
        # each line parses as valid JSON but is not an object (or has a non-object
        # payload); the by-kind pass must not blow up with AttributeError.
        for i, body in enumerate(("[]", '"record"', "null", '{"payload": []}')):
            with self.subTest(body=body):
                led = self.tmp / f"shadow-{i}.jsonl"
                led.write_text(body + "\n", encoding="utf-8")
                report = bro_monitor.scan(shadow_ledger=led)  # must not raise
                self.assertFalse(report["shadow"]["readable"])
                self.assertEqual(report["health"], "ATTENTION")
                self.assertIn("shadow ledger is unreadable or corrupt", report["attention"])

    def test_null_valued_lease_fields_are_degraded(self):
        # keys present but null values must not pass as a healthy lease
        led = self.tmp / "leases"; led.mkdir()
        (led / "x.active").write_text(
            json.dumps({"schema": None, "lease_id_sha256": None}), encoding="utf-8")
        report = bro_monitor.scan(lease_ledger=led)
        self.assertEqual(report["leases"]["degraded"], 1)
        self.assertEqual(report["health"], "ATTENTION")

    def test_wrong_schema_or_non_hex_lease_is_degraded(self):
        led = self.tmp / "leases"; led.mkdir()
        (led / "a.active").write_text(
            json.dumps({"schema": 2, "lease_id_sha256": "a" * 64}), encoding="utf-8")
        (led / "b.active").write_text(
            json.dumps({"schema": 1, "lease_id_sha256": "NOTHEX"}), encoding="utf-8")
        (led / "c.active").write_text(
            json.dumps({"schema": 1, "lease_id_sha256": "A" * 64}), encoding="utf-8")  # uppercase
        report = bro_monitor.scan(lease_ledger=led)
        self.assertEqual(report["leases"]["degraded"], 3)
        self.assertEqual(report["health"], "ATTENTION")

    def test_shadow_record_missing_kind_does_not_crash(self):
        # verify_chain builds `{k: rec[k] for k in (...,"kind",...)}` after the seq
        # and prev_hash checks, so a record that passes linkage but drops `kind`
        # raised KeyError past the guard. Append a real record, then strip `kind`
        # so seq(0)/prev_hash(GENESIS) still pass and verify reaches the KeyError.
        led = self.tmp / "shadow.jsonl"
        bro_audit_log.append(led, "shadow-would-block", {"kind": "pre-tool-deny", "reason": "x"})
        rec = json.loads(led.read_text(encoding="utf-8").splitlines()[0])
        del rec["kind"]
        led.write_text(json.dumps(rec, sort_keys=True) + "\n", encoding="utf-8")
        report = bro_monitor.scan(shadow_ledger=led)  # must not raise
        self.assertFalse(report["shadow"]["readable"])
        self.assertEqual(report["health"], "ATTENTION")
        self.assertIn("shadow ledger is unreadable or corrupt", report["attention"])

    def test_lease_hex_with_trailing_newline_is_degraded(self):
        # `$` matches before a trailing newline; fullmatch closes it.
        led = self.tmp / "leases"; led.mkdir()
        (led / "x.active").write_text(
            json.dumps({"schema": 1, "lease_id_sha256": "a" * 64 + "\n"}), encoding="utf-8")
        report = bro_monitor.scan(lease_ledger=led)
        self.assertEqual(report["leases"]["degraded"], 1)
        self.assertEqual(report["health"], "ATTENTION")

    def test_lease_schema_boolean_true_is_degraded(self):
        # True == 1 in Python; a boolean schema must not pass the int==1 check.
        led = self.tmp / "leases"; led.mkdir()
        (led / "x.active").write_text(
            json.dumps({"schema": True, "lease_id_sha256": "a" * 64}), encoding="utf-8")
        report = bro_monitor.scan(lease_ledger=led)
        self.assertEqual(report["leases"]["degraded"], 1)
        self.assertEqual(report["health"], "ATTENTION")


if __name__ == "__main__":
    unittest.main()
