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
sys.path.insert(0, str(ROOT / "tools"))

from bro_execution_lease import (
    LeaseError,
    finalize_execution_lease,
    load_execution_lease_from_env,
    quarantine_execution_lease,
    reserve_execution_lease,
    validate_execution_lease,
)


def task(worktree: str):
    return {
        "task_id": "task-lease-1",
        "repository": {
            "full_name": "menqstudio/Bro",
            "branch": "task-lease-1",
            "worktree": worktree,
            "base_commit": "a" * 40,
            "tree_identity": "b" * 64,
        },
    }


def payload(worktree: str, now: int = 1000):
    return {
        "schema": 1,
        "lease_id": "lease-000000000001",
        "nonce": "nonce-000000000001",
        "task_id": "task-lease-1",
        "agent_id": "agt-p01-r01",
        "session_id": "session-1",
        "repository": "menqstudio/Bro",
        "branch": "task-lease-1",
        "worktree": worktree,
        "head_sha": "a" * 40,
        "tree_identity": "b" * 64,
        "allowed_capabilities": ["WRITE_REPOSITORY", "EXECUTE_CODE"],
        "issued_at_epoch": now - 10,
        "expires_at_epoch": now + 100,
        "max_tool_calls": 1,
    }


class ExecutionLeaseTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("BRO_EXECUTION_LEASE_LEDGER", None)

    def validate(self, value, worktree, now=1000, required=("WRITE_REPOSITORY",)):
        return validate_execution_lease(
            value,
            task=task(worktree),
            agent_id="agt-p01-r01",
            session_id="session-1",
            required_capabilities=required,
            now=now,
        )

    def test_exact_bound_lease_is_valid(self):
        with tempfile.TemporaryDirectory() as temp:
            value = payload(temp)
            lease = self.validate(value, temp)
            self.assertEqual(lease.task_id, "task-lease-1")
            self.assertIn("WRITE_REPOSITORY", lease.allowed_capabilities)

    def test_expired_lease_is_denied(self):
        with tempfile.TemporaryDirectory() as temp:
            value = payload(temp)
            value["expires_at_epoch"] = 999
            with self.assertRaises(LeaseError):
                self.validate(value, temp)

    def test_wrong_task_agent_session_and_repository_bindings_are_denied(self):
        with tempfile.TemporaryDirectory() as temp:
            for field, wrong in (
                ("task_id", "other-task"),
                ("agent_id", "agt-p01-r02"),
                ("session_id", "other-session"),
                ("repository", "other/repo"),
                ("branch", "other-branch"),
                ("head_sha", "c" * 40),
                ("tree_identity", "d" * 64),
            ):
                value = payload(temp)
                value[field] = wrong
                with self.assertRaises(LeaseError, msg=field):
                    self.validate(value, temp)

    def test_missing_required_capability_is_denied(self):
        with tempfile.TemporaryDirectory() as temp:
            value = payload(temp)
            with self.assertRaises(LeaseError):
                self.validate(value, temp, required=("WRITE_EXTERNAL",))

    def test_atomic_reservation_denies_active_reuse_and_consumed_replay(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as ledger:
            os.environ["BRO_EXECUTION_LEASE_LEDGER"] = ledger
            lease = self.validate(payload(temp), temp)
            reserve_execution_lease(lease, "toolu_1")
            with self.assertRaises(LeaseError):
                reserve_execution_lease(lease, "toolu_2")
            finalize_execution_lease(lease, "toolu_1")
            with self.assertRaises(LeaseError):
                reserve_execution_lease(lease, "toolu_3")

    def test_success_consumes_and_failure_quarantines(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as ledger:
            os.environ["BRO_EXECUTION_LEASE_LEDGER"] = ledger
            first = self.validate(payload(temp), temp)
            reserve_execution_lease(first, "toolu_success")
            finalize_execution_lease(first, "toolu_success")
            self.assertEqual(len(list(pathlib.Path(ledger).glob("*.used"))), 1)

            second_payload = payload(temp)
            second_payload["lease_id"] = "lease-000000000002"
            second_payload["nonce"] = "nonce-000000000002"
            second = self.validate(second_payload, temp)
            reserve_execution_lease(second, "toolu_failure")
            quarantine_execution_lease(second, "toolu_failure", "unknown effect")
            self.assertEqual(len(list(pathlib.Path(ledger).glob("*.ambiguous"))), 1)
            with self.assertRaises(LeaseError):
                reserve_execution_lease(second, "toolu_retry")

    def test_wrong_tool_use_id_cannot_settle(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as ledger:
            os.environ["BRO_EXECUTION_LEASE_LEDGER"] = ledger
            lease = self.validate(payload(temp), temp)
            reserve_execution_lease(lease, "toolu_1")
            with self.assertRaises(LeaseError):
                finalize_execution_lease(lease, "toolu_wrong")


class ExecutionLeaseEd25519Tests(unittest.TestCase):
    """Owner Authorization Phase 1: the execution lease is verified with Ed25519
    against the operator-signed trusted-key registry, not HMAC. Only the offline
    issuer key can grant execution capabilities; a builder holding the public
    registry cannot mint a lease, and a wrong-authority or tampered lease is
    refused."""

    NOW = 1000

    def _fixture(self):
        from broctl import build_registry, generate_key, sign_payload
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="bro-lease-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "config").mkdir(parents=True)
        operator = generate_key("operator-root", "op", False)
        issuer = generate_key("issuer", "iss", False)
        (tmp / "config" / "trusted-keys.json").write_text(
            json.dumps(build_registry([operator, issuer], self.NOW, 100_000)), encoding="utf-8")
        from _operator_pin import use_operator_pin
        use_operator_pin(self, operator["public_key"])  # external operator-root pin
        wt = pathlib.Path(tempfile.mkdtemp(prefix="bro-wt-"))
        self.addCleanup(shutil.rmtree, wt, ignore_errors=True)
        return tmp, wt, operator, issuer, sign_payload

    def _sign(self, sign_payload, key, lease_payload):
        body = {"artifact_type": "execution-lease", "key_id": key["key_id"], **lease_payload}
        return sign_payload(key["private_key"], body)

    def _load(self, tmp, wt, signed):
        path = tmp / "lease.signed.json"
        path.write_text(json.dumps(signed), encoding="utf-8")
        with patch.dict(os.environ, {"BRO_EXECUTION_LEASE": str(path)}):
            return load_execution_lease_from_env(
                task=task(str(wt)), agent_id="agt-p01-r01", session_id="session-1",
                required_capabilities=("WRITE_REPOSITORY",), now=self.NOW, root=tmp)

    def test_issuer_signed_lease_loads(self):
        tmp, wt, _operator, issuer, sign = self._fixture()
        lease = self._load(tmp, wt, self._sign(sign, issuer, payload(str(wt), self.NOW)))
        self.assertEqual(lease.task_id, "task-lease-1")
        self.assertIn("WRITE_REPOSITORY", lease.allowed_capabilities)

    def test_operator_key_may_not_sign_a_lease(self):
        tmp, wt, operator, _issuer, sign = self._fixture()
        with self.assertRaises(LeaseError):
            self._load(tmp, wt, self._sign(sign, operator, payload(str(wt), self.NOW)))

    def test_tampered_lease_is_rejected(self):
        tmp, wt, _operator, issuer, sign = self._fixture()
        signed = self._sign(sign, issuer, payload(str(wt), self.NOW))
        signed["payload"]["max_tool_calls"] = 999  # altered after signing
        with self.assertRaises(LeaseError):
            self._load(tmp, wt, signed)


if __name__ == "__main__":
    unittest.main()
