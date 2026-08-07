import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))

from bro_contracts import (
    ContractError,
    canonical_json_sha256,
    is_absolute_scope,
    load_mode_grant_from_env,
    safe_repo_path,
    safe_work_path,
    validate_agent_profile,
    validate_task_contract,
)

TASK_CONTRACT_SCHEMA = json.loads(
    (ROOT / "schemas" / "task-contract.schema.json").read_text(encoding="utf-8"))


def contract(**overrides):
    """A minimal task contract that validate_task_contract accepts."""
    value = {
        "schema": 1,
        "task_id": "task-contract-fixture",
        "title": "Fixture",
        "objective": "Exercise task contract validation",
        "mode": "work",
        "risk": "low",
        "pack_id": "ai-agent-builders",
        "agent_id": "agt-p01-r01",
        "assignee_role": "Agent Architect",
        "scope": ["docs"],
        "prohibited_scope": ["release"],
        "inputs": [],
        "core_skills": ["ai-agent-engineering"],
        "additional_skills": [],
        "reference_skills": [],
        "done_criteria": ["done"],
        "verification": {"required": False, "verifier_agent_id": None,
                         "verifier_role": None, "commands": []},
        "rollback": {"strategy": "Discard the isolated worktree", "commands": []},
        "repository": {"full_name": "menqstudio/Bro", "branch": "feature-x",
                       "worktree": ".", "base_commit": "a" * 40,
                       "tree_identity": "b" * 64},
    }
    value.update(overrides)
    return value


class ContractTests(unittest.TestCase):
    def test_safe_repository_paths(self):
        self.assertEqual(safe_repo_path("docs/ARCHITECTURE.md"), "docs/ARCHITECTURE.md")
        for value in ("../secret", "/absolute/path", "C:/Windows/System32"):
            with self.assertRaises(ContractError):
                safe_repo_path(value)

    def test_repository_paths_refuse_backslashes_instead_of_folding_them(self):
        # Folding "a\b" to "a/b" is what made this validator accept strings the
        # schema rejects; a backslash is also the classic way to smuggle a
        # separator past a ".." rule on a platform that treats it as one.
        for value in ("docs\\ARCHITECTURE.md", "docs\\..\\..\\etc"):
            with self.assertRaises(ContractError):
                safe_repo_path(value)


class WorkPathTests(unittest.TestCase):
    """A scope entry may name a location outside this checkout. The syntax gate
    has to accept that without accepting a way to mean something else."""

    def test_absolute_scope_entries_are_accepted(self):
        for value in ("/srv/project", "C:/Users/Admin/Desktop/proj", "c:/x"):
            self.assertEqual(safe_work_path(value), value)
            self.assertTrue(is_absolute_scope(value))

    def test_repo_relative_entries_still_work(self):
        self.assertEqual(safe_work_path("docs/ARCHITECTURE.md"), "docs/ARCHITECTURE.md")
        self.assertFalse(is_absolute_scope("docs"))

    def test_absolute_scope_entries_refuse_every_way_of_meaning_something_else(self):
        for value in (
            "/srv/../etc",            # walks out of what it names
            "C:/Users/../Windows",    # same, drive form
            "C:\\Users\\Admin",       # backslash separator
            "/srv/project\\x",        # smuggled separator
            "/",                      # a filesystem root is not a scope
            "C:/",
            "//host/share",           # UNC bypasses normal resolution
            "/srv/*",                 # a scope must be provably literal
            "/srv/pro:ject",          # alternate data stream marker
            "/srv/ project",          # padded segment
            "/srv/project\x00",
        ):
            with self.assertRaises(ContractError, msg=value):
                safe_work_path(value)

    def test_task_contract_accepts_an_absolute_scope(self):
        value = contract(scope=["C:/Users/Admin/Desktop/proj"],
                         prohibited_scope=["C:/Users/Admin/Desktop/proj/.git"])
        self.assertEqual(validate_task_contract(value, ROOT), value)

    def test_task_contract_still_refuses_a_traversing_scope(self):
        with self.assertRaises(ContractError):
            validate_task_contract(contract(scope=["../../etc"]), ROOT)

    def test_inputs_stay_repository_relative(self):
        # inputs are files read from THIS checkout; the schema types them as
        # repoPath, and the validator must agree rather than quietly widen.
        with self.assertRaises(ContractError):
            validate_task_contract(contract(inputs=["/etc/passwd"]), ROOT)


class ContractSchemaAgreementTests(unittest.TestCase):
    """schemas/task-contract.schema.json must be what actually validates.

    The real check is the hand-written validator, so the schema can drift into
    describing a different language and nobody notices — it had. One corpus goes
    through both; any string the two disagree about fails this test, in either
    direction. Deleting or loosening either side turns this red.
    """

    CORPUS = (
        "docs", "docs/ARCHITECTURE.md", ".", "..", "./x", "docs/", "a//b",
        "a\\b", "~/x", "a~b", "C:/x", "C:x", "C:", "/abs/x", "/", "C:/",
        "//srv/s", "/x/../y", "docs/*.md", "docs/a?b", "docs/[a]", "a b/c",
        " ", "  docs", "docs  ", "...", "/x", "/a:b", "C:\\x", "\\\\?\\C:/x",
        "C:/Users/Admin/Desktop/proj", "c:/x", "/x/y/", "/x//y", "/.", "/..",
        "/~/x", "engine/runtime", "engine\\runtime", "docs/.hidden",
        "docs/..hidden", "/mnt/c/Users/x", "1:/x", "/x\x00y", "docs/x\x00",
        "x" * 300,
    )

    def _schema_accepts(self, definition, value):
        import jsonschema
        try:
            jsonschema.validate(
                value,
                {"$defs": TASK_CONTRACT_SCHEMA["$defs"], "$ref": f"#/$defs/{definition}"})
            return True
        except jsonschema.ValidationError:
            return False

    def _validator_accepts(self, function, value):
        try:
            function(value)
            return True
        except ContractError:
            return False

    def test_work_path_definition_matches_the_validator(self):
        for value in self.CORPUS:
            self.assertEqual(
                self._schema_accepts("workPath", value),
                self._validator_accepts(safe_work_path, value),
                msg=f"schema and safe_work_path disagree about {value!r}")

    def test_repo_path_definition_matches_the_validator(self):
        for value in self.CORPUS:
            self.assertEqual(
                self._schema_accepts("repoPath", value),
                self._validator_accepts(safe_repo_path, value),
                msg=f"schema and safe_repo_path disagree about {value!r}")

    def test_a_runtime_accepted_contract_validates_against_the_whole_schema(self):
        import jsonschema
        for value in (contract(),
                      contract(scope=["C:/Users/Admin/Desktop/proj"]),
                      contract(scope=["/srv/project", "docs"])):
            validate_task_contract(value, ROOT)
            jsonschema.validate(value, TASK_CONTRACT_SCHEMA)

    def test_a_padded_scope_entry_is_refused_by_both_sides(self):
        """Agreement has to hold at the CONTRACT level, not only for the helper.

        The generic list validator trims each entry, so " docs" used to validate
        as "docs" here while the schema rejected it — and the padded original is
        what the enforcement layers would then match against.
        """
        import jsonschema
        value = contract(scope=[" docs"])
        with self.assertRaises(ContractError):
            validate_task_contract(value, ROOT)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(value, TASK_CONTRACT_SCHEMA)


class MandatoryFlowRoleTests(unittest.TestCase):
    """The mandatory "Automation & Flow Engineer" exists once per pack and carries
    a canonical agent_id, but contract validation derived its pack/role map
    straight from packs/registry.json — which does not list it. All 52 of those
    identities validated as "not registered in pack" and could never be assigned
    work. One derivation, in bro_identity, is the fix; this proves it."""

    FLOW_ROLE = "Automation & Flow Engineer"

    def test_every_flow_identity_can_receive_a_task_contract(self):
        from bro_identity import all_agent_identities
        flow = [(agent_id, pack_id) for agent_id, (pack_id, role)
                in all_agent_identities(ROOT).items() if role == self.FLOW_ROLE]
        self.assertEqual(len(flow), 52)
        for agent_id, pack_id in flow:
            value = contract(pack_id=pack_id, agent_id=agent_id,
                             assignee_role=self.FLOW_ROLE)
            self.assertEqual(validate_task_contract(value, ROOT), value)

    def test_flow_identity_agent_profile_is_registered(self):
        value = {
            "schema": 1, "agent_id": "agt-p01-r06", "pack_id": "ai-agent-builders",
            "role": self.FLOW_ROLE, "core_skills": ["ai-agent-engineering"],
            "allowed_modes": ["review", "work"], "can_verify": False, "can_push": False,
        }
        self.assertEqual(validate_agent_profile(value, ROOT), value)

    def test_an_invented_role_is_still_unregistered(self):
        with self.assertRaises(ContractError):
            validate_task_contract(contract(assignee_role="Automation & Flow Enginee"), ROOT)


class TaskRiskCeilingTests(unittest.TestCase):
    """agents/authority-policy.json caps every role at a risk_ceiling, and until
    now only the verifier half of an assignment was ever compared against it — a
    builder capped at "high" could be handed a "critical" task and nothing
    objected."""

    def _critical(self, **overrides):
        return contract(
            risk="critical",
            verification={"required": True, "verifier_agent_id": "agt-p01-r05",
                          "verifier_role": "Independent Verifier", "commands": []},
            **overrides)

    def test_critical_task_is_refused_for_a_high_ceiling_builder(self):
        with self.assertRaises(ContractError) as caught:
            validate_task_contract(self._critical(), ROOT)
        self.assertIn("risk ceiling", str(caught.exception))

    def test_the_same_contract_at_the_ceiling_is_accepted(self):
        # Proves the refusal above is the ceiling and nothing else in the contract.
        value = self._critical()
        value["risk"] = "high"
        self.assertEqual(validate_task_contract(value, ROOT), value)

    def test_a_critical_ceiling_role_may_hold_a_critical_task(self):
        value = self._critical(agent_id="agt-p01-r05",
                               assignee_role="Independent Verifier")
        value["verification"]["verifier_agent_id"] = "agt-p01-r01"
        value["verification"]["verifier_role"] = "Agent Architect"
        self.assertEqual(validate_task_contract(value, ROOT), value)

    def test_only_push_executor_may_have_push_capability(self):
        value = {
            "schema": 1,
            "agent_id": "agt-p01-r01",
            "pack_id": "ai-agent-builders",
            "role": "Agent Architect",
            "core_skills": ["ai-agent-engineering"],
            "allowed_modes": ["review", "work"],
            "can_verify": False,
            "can_push": True,
        }
        with self.assertRaises(ContractError):
            validate_agent_profile(value, ROOT)

    def test_registered_base_agent_profile_is_valid(self):
        value = {
            "schema": 1,
            "agent_id": "agt-p01-r01",
            "pack_id": "ai-agent-builders",
            "role": "Agent Architect",
            "core_skills": ["ai-agent-engineering"],
            "allowed_modes": ["review", "work"],
            "can_verify": False,
            "can_push": False,
        }
        self.assertEqual(validate_agent_profile(value, ROOT), value)


class ModeGrantEd25519Tests(unittest.TestCase):
    """Owner Authorization Phase 1: the mode grant is verified with Ed25519 against
    the operator-signed trusted-key registry, not HMAC. Only the offline issuer key
    can authorize a mode; a builder holding the public registry cannot mint one, and
    a wrong-authority or tampered grant is refused."""

    NOW = 1_700_000_000
    AGENT = {"agent_id": "agt-p01-r01", "role": "Agent Builder"}
    SKILL = {"receipt_id": "sr-1", "skills": ["ai-agent-engineering"]}

    def _fixture(self):
        from broctl import build_registry, generate_key, sign_payload
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="bro-mg-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "config").mkdir(parents=True)
        operator = generate_key("operator-root", "op", False)
        issuer = generate_key("issuer", "iss", False)
        registry = build_registry([operator, issuer], self.NOW, 10_000)
        (tmp / "config" / "trusted-keys.json").write_text(json.dumps(registry), encoding="utf-8")
        from _operator_pin import use_operator_pin
        use_operator_pin(self, operator["public_key"])  # external operator-root pin
        return tmp, operator, issuer, sign_payload

    def _grant(self, mode="work", task_sha="c" * 64):
        return {
            "schema": 1, "grant_id": "g-1", "nonce": "n" * 16, "session_id": "sess",
            "agent_id": "agt-p01-r01", "role": "specialist", "mode": mode,
            "task_contract_sha256": task_sha,
            "agent_profile_sha256": canonical_json_sha256(self.AGENT),
            "skill_receipt_sha256": canonical_json_sha256(self.SKILL),
            "repository": "menqstudio/Bro",
            "branch": "feature-x", "head_sha": "a" * 40, "tree_identity": "b" * 64,
            "issued_at_epoch": self.NOW, "expires_at_epoch": self.NOW + 3600,
        }

    def _sign(self, sign_payload, key, grant):
        body = {"artifact_type": "mode-grant", "key_id": key["key_id"], **grant}
        return sign_payload(key["private_key"], body)

    def _load(self, tmp, signed):
        path = tmp / "grant.signed.json"
        path.write_text(json.dumps(signed), encoding="utf-8")
        bundle = SimpleNamespace(agent=self.AGENT, task_sha256="c" * 64, skill_receipt=self.SKILL)
        with patch.dict(os.environ, {"BRO_MODE_GRANT": str(path)}), \
                patch("bro_contracts.current_commit", return_value="a" * 40), \
                patch("bro_contracts.current_tree_identity", return_value="b" * 64):
            return load_mode_grant_from_env(bundle, "sess", "specialist", root=tmp, now=self.NOW)

    def test_issuer_signed_mode_grant_loads(self):
        tmp, _operator, issuer, sign = self._fixture()
        result = self._load(tmp, self._sign(sign, issuer, self._grant()))
        self.assertEqual(result["mode"], "work")

    def test_operator_key_may_not_sign_a_mode_grant(self):
        tmp, operator, _issuer, sign = self._fixture()
        with self.assertRaises(ContractError):
            self._load(tmp, self._sign(sign, operator, self._grant()))

    def test_tampered_grant_is_rejected(self):
        tmp, _operator, issuer, sign = self._fixture()
        signed = self._sign(sign, issuer, self._grant())
        signed["payload"]["mode"] = "release"  # altered after signing
        with self.assertRaises(ContractError):
            self._load(tmp, signed)

    def test_binding_mismatch_is_rejected(self):
        tmp, _operator, issuer, sign = self._fixture()
        # grant bound to a different task hash than the bundle carries
        signed = self._sign(sign, issuer, self._grant(task_sha="d" * 64))
        with self.assertRaises(ContractError):
            self._load(tmp, signed)

    def test_wrong_agent_profile_hash_is_rejected(self):
        tmp, _operator, issuer, sign = self._fixture()
        g = self._grant()
        g["agent_profile_sha256"] = "e" * 64  # not the bundle's agent-profile hash
        with self.assertRaises(ContractError):
            self._load(tmp, self._sign(sign, issuer, g))

    def test_wrong_skill_receipt_hash_is_rejected(self):
        tmp, _operator, issuer, sign = self._fixture()
        g = self._grant()
        g["skill_receipt_sha256"] = "f" * 64  # not the bundle's skill-receipt hash
        with self.assertRaises(ContractError):
            self._load(tmp, self._sign(sign, issuer, g))

    def test_signed_grant_conforms_to_the_schema(self):
        """The mode-grant JSON schema must describe the real Ed25519 document: a
        128-hex signature and a payload carrying artifact_type/key_id. A signed
        grant validating against schemas/mode-grant.schema.json proves the schema
        no longer drifts from the runtime."""
        import jsonschema
        _tmp, _operator, issuer, sign = self._fixture()
        signed = self._sign(sign, issuer, self._grant())
        schema = json.loads((ROOT / "schemas" / "mode-grant.schema.json").read_text(encoding="utf-8"))
        jsonschema.validate(signed, schema)
        self.assertEqual(len(signed["signature"]), 128)


class SkillReceiptProducerTests(unittest.TestCase):
    """Owner Authorization Phase 1: the skill-receipt producer builds a receipt
    whose per-skill hashes match the on-disk SKILL.md files and whose bindings
    satisfy validate_skill_receipt. Before this there was no producer for the
    skill receipt at all."""

    NOW = 1_700_000_000

    def _task(self):
        return {
            "task_id": "task-skill", "agent_id": "agt-p01-r01",
            "core_skills": ["ai-agent-engineering"], "additional_skills": [], "reference_skills": [],
            "repository": {"base_commit": "a" * 40, "tree_identity": "b" * 64},
        }

    def test_produced_receipt_validates(self):
        from bro_contracts import validate_skill_receipt
        from bro_skill_receipt import build_skill_receipt
        task, agent = self._task(), {"agent_id": "agt-p01-r01"}
        receipt = build_skill_receipt(task, agent, root=ROOT, now=self.NOW)
        validated = validate_skill_receipt(receipt, task, canonical_json_sha256(task), agent, ROOT, self.NOW)
        self.assertEqual(validated["task_id"], "task-skill")
        self.assertEqual(receipt["skills"][0]["path"], "skills/ai-agent-engineering/SKILL.md")

    def test_corrupted_skill_hash_is_rejected(self):
        from bro_contracts import validate_skill_receipt
        from bro_skill_receipt import build_skill_receipt
        task, agent = self._task(), {"agent_id": "agt-p01-r01"}
        receipt = build_skill_receipt(task, agent, root=ROOT, now=self.NOW)
        receipt["skills"][0]["sha256"] = "0" * 64  # no longer matches the on-disk SKILL.md
        with self.assertRaises(ContractError):
            validate_skill_receipt(receipt, task, canonical_json_sha256(task), agent, ROOT, self.NOW)


if __name__ == "__main__":
    unittest.main()
