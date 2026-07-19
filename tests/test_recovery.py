import json
import os
import pathlib
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))

from bro_completion import CompletionError, _no_pending_recovery
from bro_contracts import canonical_json_sha256
from bro_recovery import RecoveryError, _load_state, _state_path, _write_cas, assert_recovery_clear, prepare_mutation, prove_recovery, settle_mutation
from bro_signature import load_trusted_keys, verify_artifact
from broctl import build_registry, generate_key, sign_payload
from _operator_pin import use_operator_pin

TASK = {"task_id": "task-recovery-1"}
ACTION = {"tool":"Write","action":"write","capabilities":["WRITE_REPOSITORY"],"targets":["runtime/x.py"]}
BEFORE = {"head":"a"*40,"tree":"b"*64,"status_hash":"c"*64}


def record(effect="REVERSIBLE"):
    return {"schema":1,"record_id":"recovery-1","task_id":TASK["task_id"],"agent_id":"agt-p01-r01","session_id":"session-1","tool_use_id":"toolu_1","phase":"PREPARED","effect_class":effect,"action_hash":canonical_json_sha256(ACTION),"capabilities":["WRITE_REPOSITORY"],"targets":["runtime/x.py"],"before_head":BEFORE["head"],"before_tree":BEFORE["tree"],"after_head":None,"after_tree":None,"before_status_hash":BEFORE["status_hash"],"after_status_hash":None,"recovery_proof_hash":None,"irreversible_effects":[],"state_version":0,"previous_record_hash":None,"issued_at_epoch":1000}


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.environ["BRO_RECOVERY_STORE"] = self.temp.name
        # an ephemeral registry holding the owner-held recovery authority; recovery
        # proofs are signed by it and verified against it
        self.regdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.regdir.cleanup)
        self.keys = {a: generate_key(a, f"dev-{a}", False) for a in ("operator-root", "recovery")}
        use_operator_pin(self, self.keys["operator-root"]["public_key"])
        self.root = pathlib.Path(self.regdir.name)
        (self.root / "config").mkdir(parents=True)
        self.now = int(time.time())
        (self.root / "config" / "trusted-keys.json").write_text(
            json.dumps(build_registry(list(self.keys.values()), self.now - 60, 86400)), encoding="utf-8")

    def proof(self, *, key="recovery", **over):
        """A recovery-proof signed by the recovery authority, bound by default to the
        task's current recovery state; overrides let a test break a single binding."""
        st = _load_state(TASK["task_id"]) or {}
        payload = {
            "artifact_type": "recovery-proof", "key_id": self.keys[key]["key_id"], "schema": 1,
            "task_id": TASK["task_id"], "record_id": st.get("record_id", "recovery-1"),
            "before_head": st.get("before_head", BEFORE["head"]),
            "before_tree": st.get("before_tree", BEFORE["tree"]),
            "before_status_hash": st.get("before_status_hash", BEFORE["status_hash"]),
            "effect_class": st.get("effect_class", "REVERSIBLE"),
            "state_version": st.get("state_version", 0), "issued_at_epoch": self.now,
        }
        payload.update(over)
        return sign_payload(self.keys[key]["private_key"], payload)

    def prove(self, document=None):
        return prove_recovery(TASK["task_id"], self.proof() if document is None else document,
                              root=self.root, now=self.now)

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
            self.prove()

    def test_recovery_requires_exact_original_state(self):
        self.prepare("REVERSIBLE")
        changed={"head":"d"*40,"tree":"e"*64,"status_hash":"f"*64}
        with patch("bro_recovery.snapshot", return_value=changed):
            settle_mutation(TASK["task_id"], "toolu_1", success=False)
            with self.assertRaises(RecoveryError):
                self.prove()
        with patch("bro_recovery.snapshot", return_value=BEFORE):
            message=self.prove()
        self.assertIn("rework", message)
        self.assertEqual(_load_state(TASK["task_id"])["phase"], "REWORK_REQUIRED")
        with self.assertRaises(CompletionError):
            _no_pending_recovery(TASK["task_id"])

    # ---- owner-signed recovery proof (blocker 7) ----------------------------
    def _to_recovery_required(self):
        self.prepare("REVERSIBLE")
        with patch("bro_recovery.snapshot", return_value=BEFORE):
            settle_mutation(TASK["task_id"], "toolu_1", success=False, error="interrupted")

    def test_unsigned_or_hex_token_no_longer_proves_recovery(self):
        self._to_recovery_required()
        with patch("bro_recovery.snapshot", return_value=BEFORE):
            for bogus in ("d" * 64, {"not": "a signed artifact"}):
                with self.assertRaises(RecoveryError):
                    self.prove(bogus)

    def test_proof_signed_by_a_non_recovery_authority_is_denied(self):
        self._to_recovery_required()
        with patch("bro_recovery.snapshot", return_value=BEFORE):
            with self.assertRaises(RecoveryError):
                self.prove(self.proof(key="operator-root"))

    def test_proof_bound_to_a_different_recovery_is_denied(self):
        self._to_recovery_required()
        with patch("bro_recovery.snapshot", return_value=BEFORE):
            for field, wrong in (("record_id", "other-record"), ("before_head", "9" * 40),
                                 ("state_version", 999), ("task_id", "task-other")):
                with self.assertRaises(RecoveryError):
                    self.prove(self.proof(**{field: wrong}))

    def test_owner_signed_proof_is_persisted_and_re_verifiable(self):
        self._to_recovery_required()
        with patch("bro_recovery.snapshot", return_value=BEFORE):
            self.prove()
        state = _load_state(TASK["task_id"])
        self.assertEqual(state["phase"], "REWORK_REQUIRED")
        doc = state["recovery_proof_document"]
        self.assertEqual(state["recovery_proof_hash"], canonical_json_sha256(doc))
        # re-verify the persisted signed proof against the registry — from the record
        payload = verify_artifact(doc, "recovery-proof", load_trusted_keys(self.root), now=self.now)
        self.assertEqual(payload["record_id"], "recovery-1")
        self.assertEqual(payload["task_id"], TASK["task_id"])


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
