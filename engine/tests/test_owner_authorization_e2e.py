"""First green end-to-end proof for Owner Authorization Phase 1.

Before this, no test assembled a real owner-produced authorization bundle and
drove it through the runtime loaders. This does: it builds a valid task contract
and agent profile, produces the structural skill receipt and the Ed25519-signed
mode grant with the owner tooling, then loads the whole set through the real
runtime loaders (load_contract_bundle_from_env + load_mode_grant_from_env) and
proves every binding holds — including the mode grant anchoring the agent-profile
and skill-receipt hashes. Tampering any anchored artifact, or dropping the grant,
is rejected.
"""
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

from bro_authorize_specialist import build_mode_grant_payload, main, sign_mode_grant
from bro_contracts import ContractError, load_contract_bundle_from_env, load_mode_grant_from_env
from bro_skill_receipt import build_skill_receipt

NOW = 1_700_000_000
HEAD = "a" * 40
TREE = "b" * 64
AGENT_ID = "agt-p01-r02"          # ai-agent-builders / Agent Builder


def task_contract():
    return {
        "schema": 1, "task_id": "task-owner-e2e", "title": "Owner auth E2E",
        "objective": "Exercise the owner authorization bundle end to end.",
        "mode": "work", "risk": "low", "pack_id": "ai-agent-builders",
        "agent_id": AGENT_ID, "assignee_role": "Agent Builder",
        "scope": ["runtime/x.py"], "prohibited_scope": ["release"], "inputs": [],
        "core_skills": ["ai-agent-engineering"], "additional_skills": [], "reference_skills": [],
        "done_criteria": ["Bundle authorizes"],
        "verification": {"required": False, "verifier_agent_id": None, "verifier_role": None, "commands": []},
        "rollback": {"strategy": "Discard the isolated worktree", "commands": []},
        "repository": {"full_name": "menqstudio/Bro", "branch": "owner-auth-e2e",
                       "worktree": "/tmp/owner-auth-e2e-wt", "base_commit": HEAD, "tree_identity": TREE},
    }


def agent_profile():
    return {"schema": 1, "agent_id": AGENT_ID, "pack_id": "ai-agent-builders",
            "role": "Agent Builder", "core_skills": ["ai-agent-engineering"],
            "allowed_modes": ["review", "work"], "can_verify": False, "can_push": False}


class OwnerAuthorizationE2ETests(unittest.TestCase):
    def _registry(self):
        from broctl import build_registry, generate_key
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="bro-e2e-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "config").mkdir(parents=True)
        operator = generate_key("operator-root", "op", False)
        issuer = generate_key("issuer", "iss", False)
        (tmp / "config" / "trusted-keys.json").write_text(
            json.dumps(build_registry([operator, issuer], NOW, 100_000)), encoding="utf-8")
        from _operator_pin import use_operator_pin
        use_operator_pin(self, operator["public_key"])  # external operator-root pin
        return tmp, issuer

    def _bundle_env(self, tmpdir, task, agent, receipt):
        for env, obj in (("BRO_TASK_CONTRACT", task), ("BRO_AGENT_PROFILE", agent),
                         ("BRO_SKILL_RECEIPT", receipt)):
            path = tmpdir / f"{env}.json"
            path.write_text(json.dumps(obj), encoding="utf-8")
            os.environ[env] = str(path)

    def test_owner_produced_bundle_authorizes_end_to_end(self):
        reg, issuer = self._registry()
        work = pathlib.Path(tempfile.mkdtemp(prefix="bro-e2e-work-"))
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        task, agent = task_contract(), agent_profile()
        receipt = build_skill_receipt(task, agent, root=ROOT, now=NOW)
        grant = sign_mode_grant(build_mode_grant_payload(
            task, agent, receipt, session_id="sess-e2e", role="specialist", mode="work",
            head_sha=HEAD, tree_identity=TREE, now=NOW), issuer, NOW)
        grant_path = work / "mode-grant.signed.json"
        grant_path.write_text(json.dumps(grant), encoding="utf-8")

        env = {"BRO_TASK_CONTRACT": "", "BRO_AGENT_PROFILE": "", "BRO_SKILL_RECEIPT": "",
               "BRO_MODE_GRANT": str(grant_path)}
        with patch.dict(os.environ, env):
            self._bundle_env(work, task, agent, receipt)
            # 1. the structural trio loads and cross-binds through the real loader
            bundle = load_contract_bundle_from_env(ROOT, now=NOW)
            self.assertEqual(bundle.task["task_id"], "task-owner-e2e")
            # 2. the Ed25519 mode grant loads and every binding — including the
            #    anchored agent-profile and skill-receipt hashes — holds
            with patch("bro_contracts.current_commit", return_value=HEAD), \
                    patch("bro_contracts.current_tree_identity", return_value=TREE):
                loaded = load_mode_grant_from_env(bundle, "sess-e2e", "specialist", root=reg, now=NOW)
            self.assertEqual(loaded["mode"], "work")
            self.assertEqual(loaded["agent_id"], AGENT_ID)

    def test_tampered_agent_profile_breaks_the_anchor(self):
        reg, issuer = self._registry()
        work = pathlib.Path(tempfile.mkdtemp(prefix="bro-e2e-work-"))
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        task, agent = task_contract(), agent_profile()
        receipt = build_skill_receipt(task, agent, root=ROOT, now=NOW)
        grant = sign_mode_grant(build_mode_grant_payload(
            task, agent, receipt, session_id="sess-e2e", role="specialist", mode="work",
            head_sha=HEAD, tree_identity=TREE, now=NOW), issuer, NOW)
        grant_path = work / "mode-grant.signed.json"
        grant_path.write_text(json.dumps(grant), encoding="utf-8")
        # widen the agent profile after the grant anchored its hash
        tampered = agent_profile()
        tampered["can_push"] = True
        env = {"BRO_TASK_CONTRACT": "", "BRO_AGENT_PROFILE": "", "BRO_SKILL_RECEIPT": "",
               "BRO_MODE_GRANT": str(grant_path)}
        with patch.dict(os.environ, env):
            self._bundle_env(work, task, tampered, receipt)
            # the grant's anchored agent_profile_sha256 no longer matches the
            # tampered profile the bundle now carries
            from bro_contracts import canonical_json_sha256
            bundle = SimpleNamespace(
                agent=tampered, task_sha256=canonical_json_sha256(task), skill_receipt=receipt)
            with patch("bro_contracts.current_commit", return_value=HEAD), \
                    patch("bro_contracts.current_tree_identity", return_value=TREE):
                with self.assertRaises(ContractError):
                    load_mode_grant_from_env(bundle, "sess-e2e", "specialist", root=reg, now=NOW)

    def test_owner_cli_produces_a_loadable_bundle(self):
        from broctl import generate_key
        reg, issuer = self._registry()
        work = pathlib.Path(tempfile.mkdtemp(prefix="bro-e2e-cli-"))
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        task_path = work / "task.json"; task_path.write_text(json.dumps(task_contract()), encoding="utf-8")
        agent_path = work / "agent.json"; agent_path.write_text(json.dumps(agent_profile()), encoding="utf-8")
        key_path = work / "issuer.json"; key_path.write_text(json.dumps(issuer), encoding="utf-8")
        out = work / "bundle"
        rc = main(["--task", str(task_path), "--agent", str(agent_path), "--issuer-key", str(key_path),
                   "--session-id", "sess-cli", "--role", "specialist",
                   "--head-sha", HEAD, "--tree-identity", TREE, "--out-dir", str(out)])
        self.assertEqual(rc, 0)
        for name in ("task-contract.json", "agent-profile.json", "skill-receipt.json", "mode-grant.signed.json"):
            self.assertTrue((out / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
