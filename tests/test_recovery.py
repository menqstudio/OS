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

from bro_completion import CompletionError, _no_pending_recovery
from bro_contracts import canonical_json_sha256
from bro_recovery import RecoveryError, _load_state, _state_path, _write_cas, assert_recovery_clear, prepare_mutation, prove_recovery, settle_mutation

TASK = {"task_id": "task-recovery-1"}
ACTION = {"tool":"Write","action":"write","capabilities":["WRITE_REPOSITORY"],"targets":["runtime/x.py"]}
BEFORE = {"head":"a"*40,"tree":"b"*64,"status_hash":"c"*64}


def record(effect="REVERSIBLE"):
    return {"schema":1,"record_id":"recovery-1","task_id":TASK["task_id"],"agent_id":"agt-p01-r01","session_id":"session-1","tool_use_id":"toolu_1","phase":"PREPARED","effect_class":effect,"action_hash":canonical_json_sha256(ACTION),"capabilities":["WRITE_REPOSITORY"],"targets":["runtime/x.py"],"before_head":BEFORE["head"],"before_tree":BEFORE["tree"],"after_head":None,"after_tree":None,"before_status_hash":BEFORE["status_hash"],"after_status_hash":None,"recovery_proof_hash":None,"irreversible_effects":[],"state_version":0,"previous_record_hash":None,"issued_at_epoch":1000}


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.environ["BRO_RECOVERY_STORE"] = self.temp.name

    def tearDown(self):
        os.environ.pop("BRO_RECOVERY_STORE", None)
        self.temp.cleanup()

    def prepare(self, effect="REVERSIBLE"):
        with patch("bro_recovery.snapshot", return_value=BEFORE), patch("bro_recovery._signed_record", return_value=record(effect)):
            return prepare_mutation(task=TASK,agent_id="agt-p01-r01",session_id="session-1",tool_use_id="toolu_1",capabilities=("WRITE_REPOSITORY",),targets=("runtime/x.py",),tool="Write",action_name="write")

    def test_prepared_journal_blocks_second_mutation(self):
        self.prepare()
        with self.assertRaises(RecoveryError):
            assert_recovery_clear(TASK["task_id"])

    def test_compare_and_swap_rejects_stale_transition(self):
        self.prepare()
        with self.assertRaises(RecoveryError):
            _write_cas(TASK["task_id"], 0, record())

    def test_compare_and_swap_fails_closed_when_transition_lock_exists(self):
        lock = _state_path(TASK["task_id"]).with_suffix(".lock")
        lock.write_text("busy", encoding="utf-8")
        with self.assertRaises(RecoveryError):
            _write_cas(TASK["task_id"], 0, record())
        self.assertFalse(_state_path(TASK["task_id"]).exists())

    def test_success_records_after_state(self):
        self.prepare()
        after={"head":"d"*40,"tree":"e"*64,"status_hash":"f"*64}
        with patch("bro_recovery.snapshot", return_value=after):
            green, _ = settle_mutation(TASK["task_id"], "toolu_1", success=True)
        self.assertTrue(green)
        self.assertEqual(_load_state(TASK["task_id"])["phase"], "MUTATION_RECORDED")
        _no_pending_recovery(TASK["task_id"])

    def test_interruption_requires_recovery_and_blocks_completion(self):
        self.prepare("REVERSIBLE")
        with patch("bro_recovery.snapshot", return_value=BEFORE):
            green, _ = settle_mutation(TASK["task_id"], "toolu_1", success=False, error="interrupted")
        self.assertFalse(green)
        self.assertEqual(_load_state(TASK["task_id"])["phase"], "RECOVERY_REQUIRED")
        with self.assertRaises(CompletionError):
            _no_pending_recovery(TASK["task_id"])

    def test_unknown_effect_is_quarantined(self):
        self.prepare("UNKNOWN")
        with patch("bro_recovery.snapshot", return_value=BEFORE):
            settle_mutation(TASK["task_id"], "toolu_1", success=False)
        self.assertEqual(_load_state(TASK["task_id"])["phase"], "QUARANTINED")
        with self.assertRaises(CompletionError):
            _no_pending_recovery(TASK["task_id"])

    def test_irreversible_effect_is_never_marked_restored(self):
        self.prepare("IRREVERSIBLE")
        with patch("bro_recovery.snapshot", return_value=BEFORE):
            settle_mutation(TASK["task_id"], "toolu_1", success=False, error="external send occurred")
        state=_load_state(TASK["task_id"])
        self.assertEqual(state["phase"], "FAILED_WITH_IRREVERSIBLE_EFFECT")
        self.assertTrue(state["irreversible_effects"])
        with self.assertRaises(RecoveryError):
            prove_recovery(TASK["task_id"], "1"*64)

    def test_recovery_requires_exact_original_state(self):
        self.prepare("REVERSIBLE")
        changed={"head":"d"*40,"tree":"e"*64,"status_hash":"f"*64}
        with patch("bro_recovery.snapshot", return_value=changed):
            settle_mutation(TASK["task_id"], "toolu_1", success=False)
            with self.assertRaises(RecoveryError):
                prove_recovery(TASK["task_id"], "1"*64)
        with patch("bro_recovery.snapshot", return_value=BEFORE):
            message=prove_recovery(TASK["task_id"], "1"*64)
        self.assertIn("rework", message)
        self.assertEqual(_load_state(TASK["task_id"])["phase"], "REWORK_REQUIRED")
        with self.assertRaises(CompletionError):
            _no_pending_recovery(TASK["task_id"])


class RecoveryRecordEd25519Tests(unittest.TestCase):
    """Owner Authorization Phase 1: the prepared recovery record is verified with
    Ed25519 against the operator-signed registry, not HMAC. It shares the mutation
    boundary and per-action authorizer with the execution lease, so it takes the
    ISSUER authority; a builder process cannot forge its own before-state journal.
    Wrong-authority and tampered records are refused, and a signed record conforms
    to the schema."""

    NOW = 1000

    def _fixture(self):
        sys.path.insert(0, str(ROOT / "tools"))
        from broctl import build_registry, generate_key, sign_payload
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="bro-rec-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "config").mkdir(parents=True)
        keys = {a: generate_key(a, f"dev-{a}", False)
                for a in ("operator-root", "issuer", "builder")}
        (tmp / "config" / "trusted-keys.json").write_text(
            json.dumps(build_registry(list(keys.values()), self.NOW, 100_000)), encoding="utf-8")
        from _operator_pin import use_operator_pin
        use_operator_pin(self, keys["operator-root"]["public_key"])  # external operator-root pin
        return tmp, keys, sign_payload

    def _sign(self, sign_payload, key, payload):
        body = {"artifact_type": "recovery-record", "key_id": key["key_id"], **payload}
        return sign_payload(key["private_key"], body)

    def _load(self, tmp, doc):
        from bro_recovery import _signed_record
        path = tmp / "record.signed.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        with patch.dict(os.environ, {"BRO_RECOVERY_RECORD": str(path)}):
            return _signed_record(root=tmp, now=self.NOW)

    def test_issuer_signed_record_loads(self):
        tmp, keys, sign = self._fixture()
        loaded = self._load(tmp, self._sign(sign, keys["issuer"], record()))
        self.assertEqual(loaded["phase"], "PREPARED")

    def test_wrong_authority_may_not_sign_record(self):
        tmp, keys, sign = self._fixture()
        with self.assertRaises(RecoveryError):
            self._load(tmp, self._sign(sign, keys["builder"], record()))

    def test_tampered_record_is_rejected(self):
        tmp, keys, sign = self._fixture()
        signed = self._sign(sign, keys["issuer"], record())
        signed["payload"]["phase"] = "MUTATION_RECORDED"  # altered after signing
        with self.assertRaises(RecoveryError):
            self._load(tmp, signed)

    def test_signed_record_conforms_to_schema(self):
        import jsonschema
        tmp, keys, sign = self._fixture()
        signed = self._sign(sign, keys["issuer"], record())
        schema = json.loads((ROOT / "schemas" / "recovery-record.schema.json").read_text(encoding="utf-8"))
        jsonschema.validate(signed, schema)
        self.assertEqual(len(signed["signature"]), 128)


if __name__ == "__main__":
    unittest.main()
