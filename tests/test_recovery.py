import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from bro_contracts import canonical_json_sha256
from bro_recovery import RecoveryError, _load_state, _write_cas, assert_recovery_clear, prepare_mutation, prove_recovery, settle_mutation

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

    def test_success_records_after_state(self):
        self.prepare()
        after={"head":"d"*40,"tree":"e"*64,"status_hash":"f"*64}
        with patch("bro_recovery.snapshot", return_value=after):
            green, _ = settle_mutation(TASK["task_id"], "toolu_1", success=True)
        self.assertTrue(green)
        self.assertEqual(_load_state(TASK["task_id"])["phase"], "MUTATION_RECORDED")

    def test_interruption_requires_recovery(self):
        self.prepare("REVERSIBLE")
        with patch("bro_recovery.snapshot", return_value=BEFORE):
            green, _ = settle_mutation(TASK["task_id"], "toolu_1", success=False, error="interrupted")
        self.assertFalse(green)
        self.assertEqual(_load_state(TASK["task_id"])["phase"], "RECOVERY_REQUIRED")

    def test_unknown_effect_is_quarantined(self):
        self.prepare("UNKNOWN")
        with patch("bro_recovery.snapshot", return_value=BEFORE):
            settle_mutation(TASK["task_id"], "toolu_1", success=False)
        self.assertEqual(_load_state(TASK["task_id"])["phase"], "QUARANTINED")

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


if __name__ == "__main__":
    unittest.main()
