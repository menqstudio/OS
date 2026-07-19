import json
import os
import pathlib
import shlex
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))

from bro_completion import (
    CompletionError,
    authorize_conductor_stop,
    authorize_stop,
    validate_completion,
    validate_verifier_receipt,
)
from bro_policy import CANONICAL_CONDUCTOR_ID, CONDUCTOR_ROLE, UNKNOWN_ROLE, State
from bro_repository_state import RepositoryState


TASK = {
    "task_id": "task-complete-1",
    "agent_id": "agt-p01-r01",
    "risk": "critical",
    "done_criteria": ["tests green"],
    "verification": {
        "required": True,
        "verifier_agent_id": "agt-p01-r02",
        "verifier_role": "Independent Verifier",
    },
}


def manifest():
    from bro_contracts import canonical_json_sha256
    return {
        "schema": 1,
        "task_id": TASK["task_id"],
        "agent_id": TASK["agent_id"],
        "task_contract_sha256": canonical_json_sha256(TASK),
        "candidate_head": "a" * 40,
        "candidate_tree": "b" * 64,
        "done_criteria": [{"criterion": "tests green", "status": "satisfied", "evidence_event_ids": ["evt-1"]}],
        "tests": [{"command": ["python", "-m", "unittest"], "status": "passed", "evidence_event_id": "evt-1", "execution_receipt_id": "rcpt-0000000000000001"}],
        "evidence_event_ids": ["evt-1"],
        "open_risks": [],
        "rollback_ready": True,
        "issued_at_epoch": 1000,
    }


class CompletionGateTests(unittest.TestCase):
    def test_missing_manifest_denies_stop(self):
        with (patch("bro_completion._authenticated_task", return_value=TASK),
              patch("bro_completion._signed_env", side_effect=CompletionError("missing BRO_COMPLETION_MANIFEST"))):
            allowed, reason = authorize_stop(TASK["agent_id"], ROOT, session_id="s", role="specialist", mode="work")
        self.assertFalse(allowed)
        self.assertIn("missing BRO_COMPLETION_MANIFEST", reason)

    def test_dirty_repository_denies_completion(self):
        with (
            patch("bro_completion._signed_env", return_value=manifest()),
            patch("bro_completion.resolve_state", return_value=RepositoryState(ROOT, ROOT, "x", "a" * 40, "b" * 64)),
            patch("bro_completion.validate_evidence_chain"),
            patch("bro_completion._validate_execution_receipts"),
            patch("bro_completion._clean_repository", side_effect=CompletionError("repository is dirty")),
        ):
            with self.assertRaises(CompletionError):
                validate_completion(TASK, TASK["agent_id"], ROOT)

    def test_pending_or_ambiguous_lease_denies_completion(self):
        with (
            patch("bro_completion._signed_env", return_value=manifest()),
            patch("bro_completion.resolve_state", return_value=RepositoryState(ROOT, ROOT, "x", "a" * 40, "b" * 64)),
            patch("bro_completion.validate_evidence_chain"),
            patch("bro_completion._validate_execution_receipts"),
            patch("bro_completion._clean_repository"),
            patch("bro_completion._no_pending_execution", side_effect=CompletionError("pending or ambiguous execution lease exists")),
        ):
            with self.assertRaises(CompletionError):
                validate_completion(TASK, TASK["agent_id"], ROOT)

    def test_evidence_link_mismatch_denies_completion(self):
        with (
            patch("bro_completion._signed_env", return_value=manifest()),
            patch("bro_completion.resolve_state", return_value=RepositoryState(ROOT, ROOT, "x", "a" * 40, "b" * 64)),
            patch("bro_completion.validate_evidence_chain", side_effect=CompletionError("evidence chain linkage mismatch")),
        ):
            with self.assertRaises(CompletionError):
                validate_completion(TASK, TASK["agent_id"], ROOT)

    def test_bad_verifier_verdict_denied(self):
        receipt = {"schema": 1, "verdict": "RED"}
        with patch("bro_completion._signed_env", return_value=receipt):
            with self.assertRaises(CompletionError):
                validate_verifier_receipt(TASK, manifest(), manifest()["task_contract_sha256"], ROOT)

    def test_valid_manifest_and_verifier_allow_stop(self):
        with (
            patch("bro_completion._authenticated_task", return_value=TASK),
            patch("bro_completion.validate_completion", return_value=(manifest(), manifest()["task_contract_sha256"])),
            patch("bro_completion.validate_verifier_receipt", return_value={"verdict": "GREEN"}),
        ):
            allowed, reason = authorize_stop(TASK["agent_id"], ROOT, session_id="s", role="specialist", mode="work")
        self.assertTrue(allowed)
        self.assertIn("GREEN", reason)


class ConductorStopTests(unittest.TestCase):
    """Demanding a builder's completion manifest from the conductor is a category
    error: Bro delegates and never builds, so the artifact can never exist. The
    gate was not strict, it was unsatisfiable."""

    def setUp(self):
        self.state_dir = pathlib.Path(tempfile.mkdtemp(prefix="bro-stop-"))
        self.addCleanup(shutil.rmtree, self.state_dir, ignore_errors=True)
        self.env = {"BRO_SESSION_STATE_DIR": str(self.state_dir)}
        for key in ("BRO_TASK_CONTRACT",):
            self.env.pop(key, None)

    def conductor(self, session="s-1"):
        return State("review", CONDUCTOR_ROLE, session, CANONICAL_CONDUCTOR_ID)

    def authorize(self, state, **extra):
        env = {k: v for k, v in os.environ.items() if k != "BRO_TASK_CONTRACT"}
        env.update(self.env)
        env.update(extra)
        with patch.dict(os.environ, env, clear=True):
            return authorize_conductor_stop(state, ROOT)

    def test_conductor_without_a_contract_may_finish(self):
        allowed, reason = self.authorize(self.conductor())
        self.assertTrue(allowed, reason)
        self.assertIn("no builder evidence is owed", reason)

    def test_specialist_may_not_use_the_exemption(self):
        allowed, reason = self.authorize(State("work", "specialist", "s-1", "agt-p01-r01"))
        self.assertFalse(allowed)
        self.assertIn("canonical conductor", reason)

    def test_role_name_alone_may_not_use_the_exemption(self):
        allowed, _ = self.authorize(State("review", CONDUCTOR_ROLE, "s-1", "agt-p01-r01"))
        self.assertFalse(allowed)

    def test_canonical_id_without_the_role_may_not_use_the_exemption(self):
        allowed, _ = self.authorize(State("review", "specialist", "s-1", CANONICAL_CONDUCTOR_ID))
        self.assertFalse(allowed)

    def test_unauthenticated_may_not_use_the_exemption(self):
        allowed, _ = self.authorize(State("review", UNKNOWN_ROLE, "s-1", ""))
        self.assertFalse(allowed)

    def test_conductor_holding_a_contract_owes_the_full_gate(self):
        """A bound contract means Bro executed, and executed work owes evidence."""
        contract = self.state_dir / "task.json"
        contract.write_text(json.dumps(TASK), encoding="utf-8")
        allowed, reason = self.authorize(self.conductor(), BRO_TASK_CONTRACT=str(contract))
        self.assertFalse(allowed)
        self.assertIn("executor for this turn", reason)

    def test_frozen_session_must_terminate_not_finish(self):
        from bro_freeze import freeze_authority

        with patch.dict(os.environ, self.env):
            freeze_authority("s-frozen", "task-sec-1", "0" * 64)
        allowed, reason = self.authorize(self.conductor("s-frozen"))
        self.assertFalse(allowed)
        self.assertIn("frozen", reason)

    def test_unreadable_freeze_marker_fails_closed(self):
        (self.state_dir / "s-bad.freeze.json").write_text("{not json", encoding="utf-8")
        allowed, reason = self.authorize(self.conductor("s-bad"))
        self.assertFalse(allowed)
        self.assertIn("freeze state gate RED", reason)

    def test_specialist_stop_gate_is_unchanged(self):
        """The exemption must not soften the path it does not cover."""
        with (patch("bro_completion._authenticated_task", return_value=TASK),
              patch("bro_completion._signed_env",
                    side_effect=CompletionError("missing BRO_COMPLETION_MANIFEST"))):
            allowed, reason = authorize_stop(TASK["agent_id"], ROOT, session_id="s", role="specialist", mode="work")
        self.assertFalse(allowed)
        self.assertIn("missing BRO_COMPLETION_MANIFEST", reason)


class CompletionEd25519Tests(unittest.TestCase):
    """Owner Authorization Phase 1: completion manifests and verifier receipts are
    verified with Ed25519 against the operator-signed registry, not HMAC. A
    completion is signed by the builder authority and a receipt by the verifier
    authority; a policed builder process holds neither, so it cannot mint its own
    GREEN completion or receipt. Wrong-authority and tampered artifacts are
    refused, and a signed artifact conforms to its JSON schema."""

    NOW = 1_700_000_000

    def _fixture(self):
        sys.path.insert(0, str(ROOT / "tools"))
        from broctl import build_registry, generate_key, sign_payload
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="bro-comp-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "config").mkdir(parents=True)
        keys = {a: generate_key(a, f"dev-{a}", False)
                for a in ("operator-root", "builder", "verifier")}
        (tmp / "config" / "trusted-keys.json").write_text(
            json.dumps(build_registry(list(keys.values()), self.NOW, 100_000)), encoding="utf-8")
        from _operator_pin import use_operator_pin
        use_operator_pin(self, keys["operator-root"]["public_key"])  # external operator-root pin
        return tmp, keys, sign_payload

    def _sign(self, sign_payload, key, artifact_type, payload):
        body = {"artifact_type": artifact_type, "key_id": key["key_id"], **payload}
        return sign_payload(key["private_key"], body)

    def _manifest(self):
        return {
            "schema": 1, "task_id": "task-x", "agent_id": "agt-p01-r02",
            "task_contract_sha256": "a" * 64, "candidate_head": "b" * 40, "candidate_tree": "c" * 64,
            "done_criteria": [{"criterion": "done", "status": "satisfied", "evidence_event_ids": ["e1"]}],
            "tests": [{"command": ["pytest"], "status": "passed", "evidence_event_id": "e2", "execution_receipt_id": "rcpt-00000000000000e2"}],
            "evidence_event_ids": ["e1", "e2"], "open_risks": [], "rollback_ready": True,
            "issued_at_epoch": self.NOW,
        }

    def _receipt(self):
        return {
            "schema": 1, "receipt_id": "rcpt-1", "task_id": "task-x",
            "builder_agent_id": "agt-p01-r02", "verifier_agent_id": "agt-p01-r05",
            "verifier_role": "Independent Verifier", "independence_level": "L4",
            "task_contract_sha256": "a" * 64, "completion_manifest_sha256": "d" * 64,
            "candidate_head": "b" * 40, "candidate_tree": "c" * 64, "evidence_event_ids": ["e1"],
            "verdict": "GREEN", "issued_at_epoch": self.NOW, "expires_at_epoch": self.NOW + 3600,
        }

    def _load(self, tmp, env, artifact_type, signed):
        from bro_completion import _signed_env
        path = tmp / "artifact.signed.json"
        path.write_text(json.dumps(signed), encoding="utf-8")
        with patch.dict(os.environ, {env: str(path)}):
            return _signed_env(env, artifact_type, root=tmp, now=self.NOW)

    def test_builder_signed_completion_loads_and_matches_schema(self):
        import jsonschema
        tmp, keys, sign = self._fixture()
        signed = self._sign(sign, keys["builder"], "completion-manifest", self._manifest())
        loaded = self._load(tmp, "BRO_COMPLETION_MANIFEST", "completion-manifest", signed)
        self.assertEqual(loaded["task_id"], "task-x")
        schema = json.loads((ROOT / "schemas" / "completion-manifest.schema.json").read_text(encoding="utf-8"))
        jsonschema.validate(signed["payload"], schema)

    def test_wrong_authority_may_not_sign_completion(self):
        tmp, keys, sign = self._fixture()
        signed = self._sign(sign, keys["verifier"], "completion-manifest", self._manifest())
        with self.assertRaises(CompletionError):
            self._load(tmp, "BRO_COMPLETION_MANIFEST", "completion-manifest", signed)

    def test_tampered_completion_is_rejected(self):
        tmp, keys, sign = self._fixture()
        signed = self._sign(sign, keys["builder"], "completion-manifest", self._manifest())
        signed["payload"]["candidate_head"] = "f" * 40
        with self.assertRaises(CompletionError):
            self._load(tmp, "BRO_COMPLETION_MANIFEST", "completion-manifest", signed)

    def test_verifier_signed_receipt_loads_and_matches_schema(self):
        import jsonschema
        tmp, keys, sign = self._fixture()
        signed = self._sign(sign, keys["verifier"], "verifier-receipt", self._receipt())
        loaded = self._load(tmp, "BRO_VERIFIER_RECEIPT", "verifier-receipt", signed)
        self.assertEqual(loaded["verdict"], "GREEN")
        schema = json.loads((ROOT / "schemas" / "verifier-receipt.schema.json").read_text(encoding="utf-8"))
        jsonschema.validate(signed["payload"], schema)

    def test_wrong_authority_may_not_sign_receipt(self):
        tmp, keys, sign = self._fixture()
        signed = self._sign(sign, keys["builder"], "verifier-receipt", self._receipt())
        with self.assertRaises(CompletionError):
            self._load(tmp, "BRO_VERIFIER_RECEIPT", "verifier-receipt", signed)

    def test_tampered_receipt_is_rejected(self):
        tmp, keys, sign = self._fixture()
        signed = self._sign(sign, keys["verifier"], "verifier-receipt", self._receipt())
        signed["payload"]["verdict"] = "RED"
        with self.assertRaises(CompletionError):
            self._load(tmp, "BRO_VERIFIER_RECEIPT", "verifier-receipt", signed)


import subprocess

from bro_contracts import canonical_json_sha256
from test_orchestration_runtime import AGENT, build_evidence

RCPT_NOW = 1_700_000_000
RCPT_YEAR = 365 * 24 * 60 * 60
RCPT_AUTHORITIES = ["operator-root", "builder", "evidence-recorder", "verifier"]


class ExecutionReceiptGateTests(unittest.TestCase):
    """Blocker 6a: execution receipts feed the completion verdict.

    Each completion-manifest test must cite a runner-signed execution receipt for
    THIS candidate — a green `true` or a receipt from another commit is not a proof
    the suite passed here. Drives _validate_execution_receipts directly against a
    real signed receipt store; signature/authority itself is covered by
    test_execution_receipts."""

    def setUp(self):
        from broctl import build_registry, generate_key
        from bro_run_receipt import candidate_state
        from _operator_pin import use_operator_pin

        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="bro-exec-rcpt-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.keys = {a: generate_key(a, f"dev-{a}", False) for a in RCPT_AUTHORITIES}
        use_operator_pin(self, self.keys["operator-root"]["public_key"])
        # one root that carries BOTH the trusted-key registry and the test catalog
        self.root = self.tmp / "repo"
        (self.root / "config").mkdir(parents=True)
        (self.root / "tests").mkdir(parents=True)
        (self.root / "config" / "trusted-keys.json").write_text(
            json.dumps(build_registry(list(self.keys.values()), RCPT_NOW, RCPT_YEAR)), encoding="utf-8")
        (self.root / "tests" / "catalog.json").write_text(
            json.dumps({"schema": 1, "tests": []}), encoding="utf-8")
        for args in (["init", "-q"], ["config", "user.email", "t@e.com"], ["config", "user.name", "t"]):
            subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.root), "add", "-A"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "init"], check=True, capture_output=True)
        self.head, self.tree = candidate_state(self.root)
        self.store = self.tmp / "exec-receipts"
        self.store.mkdir()

    OK_CMD = [sys.executable, "-c", "print('ok')"]
    SUITE_CMD = [sys.executable, "-c", "print('suite')"]

    def _receipt(self, command, *, task_id="task-x", key="evidence-recorder"):
        from bro_run_receipt import run_and_sign
        doc, _ = run_and_sign(command, key=self.keys[key], task_id=task_id,
                              root=self.root, runner_id="runner", now=RCPT_NOW)
        rid = doc["payload"]["receipt_id"]
        (self.store / f"{rid}.json").write_text(json.dumps(doc), encoding="utf-8")
        return rid, list(doc["payload"]["command"])

    def _task(self, required):
        # the trusted required-command set lives in the signed task contract
        return {"task_id": "task-x", "verification": {"commands": [shlex.join(c) for c in required]}}

    def _validate(self, tests, *, task=None, required=None, head=None, tree=None):
        from bro_completion import _validate_execution_receipts
        with patch.dict(os.environ, {"BRO_EXECUTION_RECEIPTS": str(self.store)}):
            _validate_execution_receipts(task or self._task(required or [self.OK_CMD]),
                                         tests, head or self.head, tree or self.tree,
                                         self.root, RCPT_NOW + 10)

    def _entry(self, rid, command):
        return {"command": command, "status": "passed",
                "evidence_event_id": "e1", "execution_receipt_id": rid}

    def test_valid_receipt_covering_the_required_command_passes(self):
        rid, command = self._receipt(self.OK_CMD)
        self._validate([self._entry(rid, command)], required=[self.OK_CMD])  # must not raise

    def test_malformed_or_missing_receipt_id_is_denied(self):
        for cited in (None, "", "alias-one", "rcpt-XYZ", "rcpt-" + "0" * 15):
            entry = {"command": self.OK_CMD, "status": "passed", "evidence_event_id": "e1"}
            if cited is not None:
                entry["execution_receipt_id"] = cited
            with self.assertRaises(CompletionError) as c:
                self._validate([entry])
            self.assertIn("malformed execution receipt id", str(c.exception))

    def test_unknown_receipt_id_is_denied(self):
        with self.assertRaises(CompletionError):
            self._validate([self._entry("rcpt-" + "0" * 16, self.OK_CMD)])

    def test_non_zero_exit_is_denied(self):
        failing = [sys.executable, "-c", "import sys; sys.exit(1)"]
        rid, command = self._receipt(failing)
        with self.assertRaises(CompletionError) as c:
            self._validate([self._entry(rid, command)], required=[failing])
        self.assertIn("non-zero exit", str(c.exception))

    def test_manifest_command_not_matching_the_receipt_is_denied(self):
        rid, _command = self._receipt(self.OK_CMD)
        with self.assertRaises(CompletionError) as c:
            self._validate([self._entry(rid, ["pytest", "-q"])], required=[self.OK_CMD])
        self.assertIn("different command", str(c.exception))

    def test_green_true_cannot_substitute_for_the_required_suite(self):
        # BYPASS 1: the builder controls the manifest AND the signed cheap receipt,
        # but the required command comes from the trusted contract, not the manifest.
        rid, command = self._receipt(self.OK_CMD)  # a cheap passing command
        with self.assertRaises(CompletionError) as c:
            self._validate([self._entry(rid, command)], required=[self.SUITE_CMD])
        self.assertIn("no passing execution receipt for required command", str(c.exception))

    def test_one_signed_receipt_under_two_aliases_is_denied(self):
        # BYPASS 2: copy one signed receipt to a second, pattern-valid filename and
        # cite both. The signed receipt_id no longer equals the second cited id.
        rid, command = self._receipt(self.OK_CMD)
        alias = "rcpt-" + "a" * 16
        (self.store / f"{alias}.json").write_text(
            (self.store / f"{rid}.json").read_text(encoding="utf-8"), encoding="utf-8")
        with self.assertRaises(CompletionError) as c:
            self._validate([self._entry(rid, command), self._entry(alias, command)],
                           required=[self.OK_CMD])
        self.assertIn("id mismatch", str(c.exception))

    def test_receipt_for_a_different_candidate_is_denied(self):
        rid, command = self._receipt(self.OK_CMD)
        with self.assertRaises(CompletionError):
            self._validate([self._entry(rid, command)], required=[self.OK_CMD], head="f" * 40)

    def test_receipt_for_a_different_task_is_denied(self):
        rid, command = self._receipt(self.OK_CMD, task_id="other-task")
        with self.assertRaises(CompletionError):
            self._validate([self._entry(rid, command)], required=[self.OK_CMD])

    def test_no_trusted_required_command_defined_is_denied(self):
        rid, command = self._receipt(self.OK_CMD)
        # empty contract commands AND a catalog with no discovery_command
        with self.assertRaises(CompletionError) as c:
            self._validate([self._entry(rid, command)], task={"task_id": "task-x", "verification": {"commands": []}})
        self.assertIn("declares no verification.commands", str(c.exception))


FLOW_KEYS = ["operator-root", "issuer", "builder", "evidence-recorder"]
FLOW_AGENT = "agt-p01-r02"
FLOW_ROLE = "Agent Builder"
FLOW_SID = "sess-stop-flow"
FLOW_RUN = [sys.executable, "-c", "print('ok')"]
FLOW_SUITE = [sys.executable, "-c", "print('suite')"]


class StopGateFullFlowTests(unittest.TestCase):
    """Blocker 6a full flow — authorize_stop end-to-end with a complete signed bundle.

    Uses a real clean git repo that also carries the real registries (copied from
    ROOT), with the trust anchor replaced by an ephemeral registry we can sign. This
    exercises the WHOLE Stop gate: the full mode-grant / bundle validation (blocker
    4), one canonical tree identity so a genuinely produced receipt is accepted
    (blocker 1), the required-command set from the signed contract with no catalog
    fallback (blockers 2, 3), and the runner-snapshot receipt (blocker 5)."""

    @classmethod
    def setUpClass(cls):
        import time as _time
        from broctl import build_registry, generate_key
        from bro_run_receipt import candidate_state
        cls.tmp = pathlib.Path(tempfile.mkdtemp(prefix="bro-stopflow-")).resolve()
        cls.root = cls.tmp / "repo"
        shutil.copytree(ROOT, cls.root, ignore=shutil.ignore_patterns(
            ".git", "__pycache__", "*.pyc", "scratchpad", ".pytest_cache"))
        cls.keys = {a: generate_key(a, f"dev-{a}", False) for a in FLOW_KEYS}
        cls.now = int(_time.time())
        (cls.root / "config" / "trusted-keys.json").write_text(
            json.dumps(build_registry(list(cls.keys.values()), cls.now - 3600, 365 * 24 * 3600)),
            encoding="utf-8")
        for args in (["init", "-q", "-b", "flow-branch"], ["config", "user.email", "t@e.com"],
                     ["config", "user.name", "t"], ["add", "-A"]):
            subprocess.run(["git", "-C", str(cls.root), *args], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(cls.root), "commit", "-qm", "init"], check=True, capture_output=True)
        cls.branch = "flow-branch"
        cls.head, cls.tree = candidate_state(cls.root)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        tag = self._testMethodName
        self.stores = {}
        for name in ("evidence", "receipts", "leases", "recovery"):
            d = self.tmp / f"{name}-{tag}"; d.mkdir(); self.stores[name] = d
        cwd0 = os.getcwd(); os.chdir(self.root); self.addCleanup(os.chdir, cwd0)
        self.pin = self.keys["operator-root"]["public_key"]

    def _task(self, commands):
        return {
            "schema": 1, "task_id": "task-stop-flow", "title": "Stop gate full flow",
            "objective": "Drive authorize_stop to GREEN end to end.",
            "mode": "work", "risk": "low", "pack_id": "ai-agent-builders",
            "agent_id": FLOW_AGENT, "assignee_role": FLOW_ROLE,
            "scope": ["docs"], "prohibited_scope": ["release"], "inputs": [],
            "core_skills": ["ai-agent-engineering"], "additional_skills": [], "reference_skills": [],
            "done_criteria": ["done"],
            "verification": {"required": False, "verifier_agent_id": None,
                             "verifier_role": None, "commands": commands},
            "rollback": {"strategy": "Discard the isolated worktree", "commands": []},
            "repository": {"full_name": "menqstudio/Bro", "branch": self.branch,
                           "worktree": str(self.root), "base_commit": self.head, "tree_identity": self.tree},
        }

    def _agent(self):
        return {"schema": 1, "agent_id": FLOW_AGENT, "pack_id": "ai-agent-builders",
                "role": FLOW_ROLE, "core_skills": ["ai-agent-engineering"],
                "allowed_modes": ["review", "work"], "can_verify": False, "can_push": False}

    def _receipt_doc(self, run_command):
        from bro_run_receipt import run_and_sign
        doc, _ = run_and_sign(run_command, key=self.keys["evidence-recorder"],
                              task_id="task-stop-flow", root=self.root, runner_id="runner", now=self.now)
        rid = doc["payload"]["receipt_id"]
        (self.stores["receipts"] / f"{rid}.json").write_text(json.dumps(doc), encoding="utf-8")
        return rid, list(doc["payload"]["command"])

    def _manifest(self, task, refs, rid, command):
        payload = {
            "artifact_type": "completion-manifest", "key_id": self.keys["builder"]["key_id"],
            "schema": 1, "task_id": "task-stop-flow", "agent_id": FLOW_AGENT,
            "task_contract_sha256": canonical_json_sha256(task),
            "candidate_head": self.head, "candidate_tree": self.tree,
            "done_criteria": [{"criterion": "done", "status": "satisfied", "evidence_event_ids": [refs[0]]}],
            "tests": [{"command": command, "status": "passed", "evidence_event_id": refs[1],
                       "execution_receipt_id": rid}],
            "evidence_event_ids": refs, "open_risks": [], "rollback_ready": True,
            "issued_at_epoch": self.now,
        }
        return self.sign(self.keys["builder"], payload)

    def sign(self, key, payload):
        from broctl import sign_payload
        return sign_payload(key["private_key"], payload)

    def _grant(self, task, *, tree=None, ttl=3600, grant_mode="work", repo=None, branch=None):
        from bro_skill_receipt import build_skill_receipt
        from bro_authorize_specialist import build_mode_grant_payload, sign_mode_grant
        agent = self._agent()
        receipt = build_skill_receipt(task, agent, root=self.root, now=self.now)
        payload = build_mode_grant_payload(
            task, agent, receipt, session_id=FLOW_SID, role="specialist", mode=grant_mode,
            head_sha=self.head, tree_identity=tree or self.tree, now=self.now, ttl_seconds=ttl)
        # a correctly SIGNED grant for another repo/branch: tamper before signing
        if repo is not None:
            payload["repository"] = repo
        if branch is not None:
            payload["branch"] = branch
        return agent, receipt, sign_mode_grant(payload, self.keys["issuer"], self.now)

    def _run(self, *, contract_commands, run_command=None, grant_tree=None, grant_ttl=3600,
             grant_mode="work", grant_repo=None, grant_branch=None, mode_value="work",
             session_id=FLOW_SID, role="specialist", acting_agent=FLOW_AGENT, present_task=None):
        from bro_completion import authorize_stop
        task = self._task(contract_commands)
        agent, receipt, grant = self._grant(task, tree=grant_tree, ttl=grant_ttl,
                                            grant_mode=grant_mode, repo=grant_repo, branch=grant_branch)
        refs = build_evidence(self.stores["evidence"], self.keys, "task-stop-flow", 2)
        rid, command = self._receipt_doc(run_command or FLOW_RUN)
        manifest = self._manifest(task, refs, rid, command)
        w = self.tmp
        files = {}
        for name, obj in (("task", present_task or task), ("agent", agent),
                          ("receipt", receipt), ("grant", grant), ("manifest", manifest)):
            f = w / f"{self._testMethodName}-{name}.json"
            f.write_text(json.dumps(obj), encoding="utf-8"); files[name] = str(f)
        env = {
            "BRO_OPERATOR_ROOT_PUBKEY": self.pin,
            "BRO_TASK_CONTRACT": files["task"], "BRO_AGENT_PROFILE": files["agent"],
            "BRO_SKILL_RECEIPT": files["receipt"], "BRO_MODE_GRANT": files["grant"],
            "BRO_COMPLETION_MANIFEST": files["manifest"],
            "BRO_EVIDENCE_STORE": str(self.stores["evidence"]),
            "BRO_EXECUTION_RECEIPTS": str(self.stores["receipts"]),
            "BRO_EXECUTION_LEASE_LEDGER": str(self.stores["leases"]),
            "BRO_RECOVERY_STORE": str(self.stores["recovery"]),
        }
        with patch.dict(os.environ, env):
            return authorize_stop(acting_agent, self.root, session_id=session_id, role=role,
                                  mode=mode_value, now=self.now)

    # ---- positive full flow (blockers 1, 4, 5) ------------------------------
    def test_full_signed_bundle_and_real_receipt_is_allowed(self):
        allowed, reason = self._run(contract_commands=[shlex.join(FLOW_RUN)])
        self.assertTrue(allowed, reason)
        self.assertIn("GREEN", reason)

    # ---- blocker 2: no catalog fallback -------------------------------------
    def test_empty_verification_commands_is_denied(self):
        allowed, reason = self._run(contract_commands=[])
        self.assertFalse(allowed)
        self.assertIn("no verification.commands", reason)

    def test_cheap_receipt_cannot_cover_the_required_suite(self):
        allowed, reason = self._run(contract_commands=[shlex.join(FLOW_SUITE)], run_command=FLOW_RUN)
        self.assertFalse(allowed)
        self.assertIn("no passing execution receipt for required command", reason)

    # ---- blocker 4: the FULL mode-grant path, not just signature+task hash ---
    def test_expired_grant_is_denied(self):
        allowed, reason = self._run(contract_commands=[shlex.join(FLOW_RUN)], grant_ttl=-100)
        self.assertFalse(allowed)
        self.assertIn("expired", reason)

    def test_grant_for_a_different_session_is_denied(self):
        allowed, reason = self._run(contract_commands=[shlex.join(FLOW_RUN)], session_id="sess-other")
        self.assertFalse(allowed)
        self.assertIn("binding mismatch: session_id", reason)

    def test_grant_bound_to_a_different_tree_is_denied(self):
        allowed, reason = self._run(contract_commands=[shlex.join(FLOW_RUN)], grant_tree="f" * 64)
        self.assertFalse(allowed)
        self.assertIn("binding mismatch: tree_identity", reason)

    def test_task_not_assigned_to_the_acting_agent_is_denied(self):
        allowed, reason = self._run(contract_commands=[shlex.join(FLOW_RUN)], acting_agent="agt-p01-r01")
        self.assertFalse(allowed)
        self.assertIn("not assigned to the acting agent", reason)

    # ---- blocker 6: grant repository / branch / mode must bind the task ------
    def test_grant_for_a_different_repository_is_denied(self):
        allowed, reason = self._run(contract_commands=[shlex.join(FLOW_RUN)],
                                    grant_repo="menqstudio/OtherRepo")
        self.assertFalse(allowed)
        self.assertIn("grant repository binding mismatch", reason)

    def test_grant_for_a_different_branch_is_denied(self):
        allowed, reason = self._run(contract_commands=[shlex.join(FLOW_RUN)],
                                    grant_branch="some-other-branch")
        self.assertFalse(allowed)
        self.assertIn("grant branch binding mismatch", reason)

    def test_grant_for_a_different_mode_is_denied(self):
        # a correctly signed release-mode grant must not authorize a work completion
        allowed, reason = self._run(contract_commands=[shlex.join(FLOW_RUN)],
                                    grant_mode="release", mode_value="work")
        self.assertFalse(allowed)
        self.assertIn("grant mode binding mismatch", reason)


if __name__ == "__main__":
    unittest.main()
