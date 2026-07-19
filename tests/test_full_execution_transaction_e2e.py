"""Full execution-transaction E2E for the specialist mutation gate.

Phase 1 (tests/test_owner_authorization_e2e.py) proved the owner bundle loads and
the mode grant anchors the task/agent/skill hashes. It stopped there: no test
drove runtime/bro_control_plane.authorize_tool all the way to ALLOW a real
specialist mutation, and none settled the resulting transaction.

This does. It assembles every artifact the mutation gate consumes against the
real repository ROOT — task contract, agent profile, skill receipt, Ed25519 mode
grant, workspace binding with a real control-plane digest, an active task-lock
ledger entry, an Ed25519 execution lease, and a signed PREPARED recovery record —
then drives authorize_tool("Write", ...) to (True, ...) and settle_execution_tool
to finalize the lease and record the mutation.

Exercised for real: the Ed25519 verification of the grant/lease/recovery against
an operator-signed trusted-key registry; the workspace binding and its
control-plane digest recomputed over ROOT; the path-scope gate; the execution
lease ledger reservation and finalization; and the recovery CAS store. Substituted
only where the environment cannot be faithfully reproduced inside a unit test and
exactly as the per-component Ed25519 tests already do: the environmental git
observations (HEAD / tree identity / branch, `git status`), and the trust root —
the committed registry's issuer private key is deliberately not on disk, so the
test signs against its own operator-signed dev registry.

The last two tests prove the gate is not vacuous: dropping the execution lease or
the mode grant flips the same assembled transaction to DENY.
"""
import hashlib
import json
import os
import pathlib
import shutil
import sys
import tempfile
import time
import unittest
from contextlib import ExitStack
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))

from bro_authorization import classify_tool_action
from bro_contracts import canonical_json_sha256
from bro_control_plane import authorize_tool, settle_execution_tool
from bro_policy import State
from bro_repository_state import RepositoryState, _normal
import bro_signature

from bro_authorize_specialist import build_mode_grant_payload, sign_mode_grant
from bro_bind_workspace import build_binding
from bro_skill_receipt import build_skill_receipt
from broctl import build_registry, generate_key, sign_payload

# Deterministic stand-ins for the environmental git observations. They must be
# internally consistent across every artifact and every patched seam.
HEAD = "a" * 40
TREE = "b" * 64
STATUS = "c" * 64
BRANCH = "owner-auth-exec-e2e"          # a non-main branch: main is denied for mutation
SID = "sess-exec-e2e"
AGENT = "agt-p01-r02"                    # ai-agent-builders / Agent Builder (can_build)
TUID = "toolu_exec_e2e_1"
TARGET = "docs/e2e-allow.md"            # non-protected, in-scope, need not exist
TOOL_INPUT = {"file_path": TARGET}


def _task():
    return {
        "schema": 1, "task_id": "task-exec-e2e", "title": "Full execution transaction E2E",
        "objective": "Drive authorize_tool to ALLOW a specialist mutation end to end.",
        "mode": "work", "risk": "low", "pack_id": "ai-agent-builders",
        "agent_id": AGENT, "assignee_role": "Agent Builder",
        "scope": ["docs"], "prohibited_scope": ["release"], "inputs": [],
        "core_skills": ["ai-agent-engineering"], "additional_skills": [], "reference_skills": [],
        "done_criteria": ["The mutation authorizes end to end"],
        "verification": {"required": False, "verifier_agent_id": None, "verifier_role": None, "commands": []},
        "rollback": {"strategy": "Discard the isolated worktree", "commands": []},
        "repository": {"full_name": "menqstudio/Bro", "branch": BRANCH,
                       "worktree": str(ROOT), "base_commit": HEAD, "tree_identity": TREE},
    }


def _agent():
    return {"schema": 1, "agent_id": AGENT, "pack_id": "ai-agent-builders",
            "role": "Agent Builder", "core_skills": ["ai-agent-engineering"],
            "allowed_modes": ["review", "work"], "can_verify": False, "can_push": False}


class FullExecutionTransactionE2ETests(unittest.TestCase):
    def setUp(self):
        self.now = int(time.time())
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="bro-exec-e2e-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

        # Operator-signed dev registry (the committed registry's issuer key is not
        # on disk). load_trusted_keys is redirected here for every in-process verify.
        (self.tmp / "config").mkdir(parents=True)
        operator = generate_key("operator-root", "op", False)
        self.issuer = generate_key("issuer", "iss", False)
        (self.tmp / "config" / "trusted-keys.json").write_text(
            json.dumps(build_registry([operator, self.issuer], self.now, 100_000)), encoding="utf-8")

        # External ledgers / stores, all outside the repository.
        self.locks = self.tmp / "locks"; self.locks.mkdir()
        self.lease_ledger = self.tmp / "lease-ledger"; self.lease_ledger.mkdir()
        self.recovery_store = self.tmp / "recovery-store"; self.recovery_store.mkdir()
        self.session_dir = self.tmp / "sessions"; self.session_dir.mkdir()

        self.task, self.agent = _task(), _agent()
        self.task_id = self.task["task_id"]

    # ---- artifact producers -------------------------------------------------
    def _sign(self, artifact_type, body):
        payload = {"artifact_type": artifact_type, "key_id": self.issuer["key_id"], **body}
        return sign_payload(self.issuer["private_key"], payload)

    def _write(self, name, obj):
        path = self.tmp / name
        path.write_text(json.dumps(obj), encoding="utf-8")
        return str(path)

    def _lease_body(self):
        return {
            "schema": 1, "lease_id": "lease-exec-e2e-1", "nonce": "exec-lease-nonce-000001",
            "task_id": self.task_id, "agent_id": AGENT, "session_id": SID,
            "repository": "menqstudio/Bro", "branch": BRANCH, "worktree": str(ROOT),
            "head_sha": HEAD, "tree_identity": TREE,
            "allowed_capabilities": ["WRITE_REPOSITORY"],
            "issued_at_epoch": self.now, "expires_at_epoch": self.now + 3600, "max_tool_calls": 8,
        }

    def _recovery_body(self, classification):
        action = {"tool": classification.tool, "action": classification.action,
                  "capabilities": list(classification.capabilities), "targets": list(classification.targets)}
        return {
            "schema": 1, "record_id": "rec-exec-e2e-1", "task_id": self.task_id, "agent_id": AGENT,
            "session_id": SID, "tool_use_id": TUID, "phase": "PREPARED", "effect_class": "REVERSIBLE",
            "action_hash": canonical_json_sha256(action),
            "capabilities": list(classification.capabilities), "targets": list(classification.targets),
            "before_head": HEAD, "before_tree": TREE, "after_head": None, "after_tree": None,
            "before_status_hash": STATUS, "after_status_hash": None,
            "recovery_proof_hash": None, "irreversible_effects": [], "state_version": 0,
            "previous_record_hash": None, "issued_at_epoch": self.now,
        }

    def _write_lock(self):
        lock = {
            "schema": 1, "status": "active", "task_id": self.task_id, "agent_id": AGENT,
            "session_id": SID, "worktree": _normal(ROOT), "branch": BRANCH,
            "head_sha": HEAD, "tree_identity": TREE,
        }
        key = hashlib.sha256(_normal(ROOT).encode("utf-8")).hexdigest()
        (self.locks / f"{key}.json").write_text(json.dumps(lock), encoding="utf-8")

    def _bundle_env(self):
        """Assemble the complete transaction and return the BRO_* environment."""
        classification = classify_tool_action("Write", TOOL_INPUT)
        receipt = build_skill_receipt(self.task, self.agent, root=ROOT, now=self.now)
        grant = sign_mode_grant(build_mode_grant_payload(
            self.task, self.agent, receipt, session_id=SID, role="specialist", mode="work",
            head_sha=HEAD, tree_identity=TREE, now=self.now), self.issuer, self.now)
        lease = self._sign("execution-lease", self._lease_body())
        recovery = self._sign("recovery-record", self._recovery_body(classification))
        binding = build_binding(ROOT, "bro-exec-e2e", "test-operator", 3600, self.now)
        binding_path = self.tmp / "workspace-binding.json"
        binding_path.write_text(json.dumps(binding), encoding="utf-8")
        self._write_lock()
        return {
            "BRO_MODE": "work", "BRO_ROLE": "specialist", "BRO_AGENT_ID": AGENT, "BRO_SESSION_ID": SID,
            "BRO_TASK_CONTRACT": self._write("task-contract.json", self.task),
            "BRO_AGENT_PROFILE": self._write("agent-profile.json", self.agent),
            "BRO_SKILL_RECEIPT": self._write("skill-receipt.json", receipt),
            "BRO_MODE_GRANT": self._write("mode-grant.signed.json", grant),
            "BRO_WORKSPACE_BINDING": str(binding_path),
            "BRO_SESSION_STATE_DIR": str(self.session_dir),
            "BRO_TASK_LOCK_LEDGER": str(self.locks),
            "BRO_EXECUTION_LEASE": self._write("execution-lease.signed.json", lease),
            "BRO_EXECUTION_LEASE_LEDGER": str(self.lease_ledger),
            "BRO_RECOVERY_RECORD": self._write("recovery-record.signed.json", recovery),
            "BRO_RECOVERY_STORE": str(self.recovery_store),
        }

    # ---- seam patches -------------------------------------------------------
    def _patches(self):
        real_load = bro_signature.load_trusted_keys
        reg = self.tmp
        stack = ExitStack()
        stack.enter_context(patch("bro_signature.load_trusted_keys",
                                  new=lambda root=None, operator_public_key=None: real_load(reg)))
        stack.enter_context(patch("bro_contracts.current_commit", return_value=HEAD))
        stack.enter_context(patch("bro_contracts.current_tree_identity", return_value=TREE))
        stack.enter_context(patch("bro_repository_state.resolve_state", return_value=RepositoryState(
            root=ROOT.resolve(), cwd=ROOT.resolve(), branch=BRANCH, head_sha=HEAD, tree_identity=TREE)))
        stack.enter_context(patch("bro_recovery.snapshot",
                                  return_value={"head": HEAD, "tree": TREE, "status_hash": STATUS}))
        return stack

    def _state(self):
        return State("work", "specialist", SID, AGENT)

    # ---- tests --------------------------------------------------------------
    def test_specialist_mutation_authorizes_and_settles_end_to_end(self):
        env = self._bundle_env()
        with self._patches(), patch.dict(os.environ, env, clear=False):
            allowed, reason = authorize_tool(self._state(), "Write", TOOL_INPUT, tool_use_id=TUID)
            self.assertTrue(allowed, reason)
            self.assertIn("WRITE_REPOSITORY", reason)
            self.assertIn("recovery journal prepared", reason)
            # the lease reservation and recovery PREPARED record are now on disk
            self.assertEqual([p.suffix for p in self.lease_ledger.iterdir()], [".active"])
            state_file = self.recovery_store / f"{hashlib.sha256(self.task_id.encode()).hexdigest()}.state.json"
            self.assertEqual(json.loads(state_file.read_text())["phase"], "PREPARED")

            # settle the transaction: lease consumed, mutation journal recorded
            governed, recovery_green, msg = settle_execution_tool(
                self._state(), "Write", TOOL_INPUT, TUID, success=True)
            self.assertTrue(governed, msg)
            self.assertTrue(recovery_green, msg)
            self.assertIn("execution lease consumed", msg)
            self.assertEqual([p.suffix for p in self.lease_ledger.iterdir()], [".used"])
            self.assertEqual(json.loads(state_file.read_text())["phase"], "MUTATION_RECORDED")

    def test_missing_execution_lease_denies_and_rolls_back_recovery(self):
        env = self._bundle_env()
        env.pop("BRO_EXECUTION_LEASE")
        with self._patches(), patch.dict(os.environ, env, clear=False):
            os.environ.pop("BRO_EXECUTION_LEASE", None)
            allowed, reason = authorize_tool(self._state(), "Write", TOOL_INPUT, tool_use_id=TUID)
            self.assertFalse(allowed)
            self.assertIn("transaction gate RED", reason)
            # the recovery journal prepared before the lease failure was cancelled
            state_file = self.recovery_store / f"{hashlib.sha256(self.task_id.encode()).hexdigest()}.state.json"
            self.assertFalse(state_file.exists())
            # and no lease reservation leaked
            self.assertEqual(list(self.lease_ledger.iterdir()), [])

    def test_missing_mode_grant_denies_before_any_transaction(self):
        env = self._bundle_env()
        env.pop("BRO_MODE_GRANT")
        with self._patches(), patch.dict(os.environ, env, clear=False):
            os.environ.pop("BRO_MODE_GRANT", None)
            allowed, reason = authorize_tool(self._state(), "Write", TOOL_INPUT, tool_use_id=TUID)
            self.assertFalse(allowed)
            self.assertIn("mode grant RED", reason)
            self.assertEqual(list(self.lease_ledger.iterdir()), [])

    def test_out_of_scope_target_denies_with_full_bundle(self):
        # Everything is present and valid; only the write target lies outside the
        # task's ["docs"] scope. The scope gate must bite before any transaction.
        env = self._bundle_env()
        out_of_scope = {"file_path": "notes/out-of-scope.md"}
        with self._patches(), patch.dict(os.environ, env, clear=False):
            allowed, reason = authorize_tool(self._state(), "Write", out_of_scope, tool_use_id=TUID)
            self.assertFalse(allowed)
            self.assertIn("scope gate RED", reason)
            self.assertEqual(list(self.lease_ledger.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
