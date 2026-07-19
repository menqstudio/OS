import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))

from bro_signature import SignatureError, verify_artifact
from bro_supervisor import (
    COMPLETED,
    DENIED,
    EXPIRED,
    FAILED,
    SupervisorError,
    SupervisorResult,
    TaskRequest,
    authorize_request,
    issue_lease,
    run_task,
)
from broctl import build_registry, generate_key, sign_payload

NOW = 1_700_000_000
YEAR = 365 * 24 * 60 * 60
AUTHORITIES = ["operator-root", "issuer", "evidence-recorder", "builder",
               "verifier", "release"]

# A builder that reports what it was handed, so the tests can prove what reached it.
DUMP_ENV = (
    "import json,os;"
    "print(json.dumps({k:v for k,v in os.environ.items() if k.startswith('BRO_')}))"
)


class SupervisorFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="bro-sup-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

        self.keydir = self.tmp / "keys"
        self.keydir.mkdir()
        self.keys = {}
        for authority in AUTHORITIES:
            key = generate_key(authority, f"dev-{authority}", False)
            self.keys[authority] = key
            (self.keydir / f"{authority}.json").write_text(json.dumps(key), encoding="utf-8")

        self.registry_root = self.tmp / "registry"
        (self.registry_root / "config").mkdir(parents=True)
        self.registry = build_registry(list(self.keys.values()), NOW, YEAR)
        (self.registry_root / "config" / "trusted-keys.json").write_text(
            json.dumps(self.registry), encoding="utf-8")
        from _operator_pin import use_operator_pin
        use_operator_pin(self, self.keys["operator-root"]["public_key"])  # external pin
        from bro_signature import load_trusted_keys
        self.trusted = load_trusted_keys(self.registry_root)

        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        for args in (["init", "-q"], ["config", "user.email", "t@example.com"],
                     ["config", "user.name", "t"]):
            subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                           capture_output=True)
        (self.repo / "src.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"], check=True,
                       capture_output=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "init"],
                       check=True, capture_output=True)

        self.binding = self.tmp / "binding.json"
        self.binding.write_text(json.dumps({
            "schema": 1, "workspace_id": "bro-test", "repository": "menqstudio/bro",
            "root": str(self.repo), "control_plane_digest": "a" * 64, "active": True,
        }), encoding="utf-8")

    def request(self, task_class="standard-builder", scope=()):
        return TaskRequest("task-1", task_class, "because", tuple(scope))

    def approval(self, task_id="task-1", scope=("runtime/bro_policy.py",), approve=True):
        return sign_payload(self.keys["operator-root"]["private_key"], {
            "artifact_type": "protected-authority",
            "key_id": self.keys["operator-root"]["key_id"],
            "task_id": task_id, "owner_approval": approve,
            "protected_scope": list(scope), "issued_at_epoch": NOW,
        })

    def supervise(self, request, builder=None, **kwargs):
        return run_task(
            request, repository_root=self.repo, keydir=self.keydir,
            registry_root=self.registry_root, binding_path=self.binding,
            builder_command=builder or [sys.executable, "-c", DUMP_ENV],
            now=NOW, **kwargs)


class RequestValidationTests(SupervisorFixture):
    def test_unknown_task_class_denied(self):
        with self.assertRaises(SupervisorError):
            TaskRequest.load({"task_id": "t", "task_class": "superuser", "rationale": "r"})

    def test_missing_field_denied(self):
        with self.assertRaises(SupervisorError):
            TaskRequest.load({"task_id": "t", "task_class": "standard-builder"})

    def test_pattern_scope_denied(self):
        with self.assertRaises(SupervisorError):
            TaskRequest.load({"task_id": "t", "task_class": "security-maintenance",
                              "rationale": "r", "protected_scope": ["runtime/**"]})


class ApprovalTests(SupervisorFixture):
    def test_standard_task_needs_no_approval(self):
        reason = authorize_request(self.request(), None, self.trusted, now=NOW)
        self.assertIn("no owner approval required", reason)

    def test_standard_task_may_not_carry_protected_scope(self):
        with self.assertRaises(SupervisorError):
            authorize_request(self.request(scope=["runtime/bro_policy.py"]), None,
                              self.trusted, now=NOW)

    def test_security_task_without_approval_denied(self):
        request = self.request("security-maintenance", ["runtime/bro_policy.py"])
        with self.assertRaises(SupervisorError) as caught:
            authorize_request(request, None, self.trusted, now=NOW)
        self.assertIn("owner-signed approval", str(caught.exception))

    def test_security_task_without_scope_denied(self):
        with self.assertRaises(SupervisorError):
            authorize_request(self.request("security-maintenance"), self.approval(),
                              self.trusted, now=NOW)

    def test_security_task_with_owner_approval_allowed(self):
        request = self.request("security-maintenance", ["runtime/bro_policy.py"])
        reason = authorize_request(request, self.approval(), self.trusted, now=NOW)
        self.assertIn("approved by", reason)

    def test_scope_beyond_approval_denied(self):
        request = self.request("security-maintenance",
                               ["runtime/bro_policy.py", "runtime/bro_hook.py"])
        with self.assertRaises(SupervisorError) as caught:
            authorize_request(request, self.approval(), self.trusted, now=NOW)
        self.assertIn("beyond the owner's approval", str(caught.exception))

    def test_approval_for_another_task_denied(self):
        request = self.request("security-maintenance", ["runtime/bro_policy.py"])
        with self.assertRaises(SupervisorError) as caught:
            authorize_request(request, self.approval(task_id="other"), self.trusted, now=NOW)
        self.assertIn("different task", str(caught.exception))

    def test_approval_that_does_not_approve_denied(self):
        request = self.request("security-maintenance", ["runtime/bro_policy.py"])
        with self.assertRaises(SupervisorError):
            authorize_request(request, self.approval(approve=False), self.trusted, now=NOW)

    def test_builder_signed_approval_denied(self):
        """Only the owner approves protected work."""
        forged = sign_payload(self.keys["builder"]["private_key"], {
            "artifact_type": "protected-authority",
            "key_id": self.keys["builder"]["key_id"], "task_id": "task-1",
            "owner_approval": True, "protected_scope": ["runtime/bro_policy.py"]})
        request = self.request("security-maintenance", ["runtime/bro_policy.py"])
        with self.assertRaises(SignatureError):
            authorize_request(request, forged, self.trusted, now=NOW)


class LeaseTests(SupervisorFixture):
    def lease(self, key="issuer"):
        return issue_lease(
            self.request(), self.keys[key], workspace_id="bro-test",
            repository="menqstudio/bro", worktree="/w", agent_id="agt-p01-r01",
            session_id="s-1", control_plane_digest="a" * 64, ttl_seconds=900, now=NOW)

    def test_lease_is_issuer_signed_and_verifies(self):
        payload = verify_artifact(self.lease(), "execution-lease", self.trusted, now=NOW + 1)
        self.assertEqual(payload["task_id"], "task-1")
        self.assertEqual(payload["expires_at_epoch"], NOW + 900)

    def test_builder_key_may_not_issue_a_lease(self):
        with self.assertRaises(SupervisorError) as caught:
            self.lease("builder")
        self.assertIn("may not issue execution leases", str(caught.exception))

    def test_lease_binds_the_control_plane_digest(self):
        payload = verify_artifact(self.lease(), "execution-lease", self.trusted, now=NOW + 1)
        self.assertEqual(payload["control_plane_digest"], "a" * 64)

    def test_tampered_lease_denied(self):
        lease = self.lease()
        lease["payload"]["expires_at_epoch"] = NOW + 10 ** 9
        with self.assertRaises(SignatureError):
            verify_artifact(lease, "execution-lease", self.trusted, now=NOW + 1)


class LeaseContainmentTests(SupervisorFixture):
    """The rule the whole split exists for: Bro asks, Bro never holds."""

    def test_builder_receives_the_lease(self):
        result = self.supervise(self.request(),
                          builder=[sys.executable, "-c", DUMP_ENV.replace(
                              "print(json.dumps(", "print('evidence:'+json.dumps(")])
        self.assertEqual(result.status, COMPLETED, result.message)
        env = json.loads(result.evidence[0][len("evidence:"):])
        self.assertIn("BRO_EXECUTION_LEASE", env)
        self.assertEqual(env["BRO_ROLE"], "specialist")

    def test_result_carries_no_lease_or_key(self):
        result = self.supervise(self.request())
        blob = json.dumps(result.__dict__)
        self.assertNotIn("private_key", blob)
        self.assertNotIn("BRO_EXECUTION_LEASE", blob)
        self.assertNotIn(self.keys["issuer"]["private_key"], blob)

    def test_result_shape_is_outcomes_and_evidence_only(self):
        self.assertEqual(
            set(SupervisorResult("t", "s", "m").__dict__),
            {"task_id", "status", "message", "exit_code", "evidence"})

    def test_lease_file_is_removed_after_the_run(self):
        leases = []
        result = self.supervise(
            self.request(),
            builder=[sys.executable, "-c",
                     "import os;print('evidence:'+os.environ['BRO_EXECUTION_LEASE'])"])
        self.assertEqual(result.status, COMPLETED, result.message)
        leases.append(result.evidence[0][len("evidence:"):])
        self.assertFalse(pathlib.Path(leases[0]).exists(),
                         "a lease that outlives its builder is a credential on disk")

    def test_builder_does_not_inherit_the_supervisor_environment(self):
        result = self.supervise(
            self.request(),
            builder=[sys.executable, "-c",
                     "import json,os;print('evidence:'+json.dumps(sorted(os.environ)))"])
        names = json.loads(result.evidence[0][len("evidence:"):])
        self.assertNotIn("BRO_TASK_CONTRACT", names)
        self.assertNotIn("BRO_COMPLETION_KEY", names)


class RunTests(SupervisorFixture):
    def test_denied_security_task_never_spawns_a_builder(self):
        request = self.request("security-maintenance", ["runtime/bro_policy.py"])
        result = self.supervise(request, builder=[sys.executable, "-c", "raise SystemExit(0)"])
        self.assertEqual(result.status, DENIED)
        self.assertIn("owner-signed approval", result.message)

    def test_failing_builder_reports_failed(self):
        result = self.supervise(self.request(),
                          builder=[sys.executable, "-c", "raise SystemExit(3)"])
        self.assertEqual(result.status, FAILED)
        self.assertEqual(result.exit_code, 3)

    def test_builder_exceeding_its_lease_is_terminated(self):
        result = self.supervise(self.request(),
                          builder=[sys.executable, "-c", "import time;time.sleep(30)"],
                          ttl_seconds=1)
        self.assertEqual(result.status, EXPIRED)
        self.assertIn("terminated", result.message)

    def test_builder_runs_in_its_own_worktree(self):
        result = self.supervise(
            self.request(),
            builder=[sys.executable, "-c", "import os;print('evidence:'+os.getcwd())"])
        cwd = result.evidence[0][len("evidence:"):]
        self.assertNotEqual(pathlib.Path(cwd).resolve(), self.repo.resolve())
        self.assertTrue((pathlib.Path(cwd) / "src.txt").exists())


if __name__ == "__main__":
    unittest.main()
