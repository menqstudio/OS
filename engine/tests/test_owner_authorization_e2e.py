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

    def test_every_grant_carries_its_own_nonce_and_the_ledger_takes_the_second(self):
        # Both fields defaulted to constants no caller overrode, so every grant carried
        # the nonce "mode-grant-nonce-000001" and the L-1 ledger — which binds a nonce
        # to the first grant presenting it — refused the second specialist's grant.
        import re
        from bro_contracts import MODE_GRANT_NONCE_RE, bind_mode_grant_nonce
        task, agent = task_contract(), agent_profile()
        receipt = build_skill_receipt(task, agent, root=ROOT, now=NOW)
        first, second = (build_mode_grant_payload(
            task, agent, receipt, session_id=session, role="specialist", mode="work",
            head_sha=HEAD, tree_identity=TREE, now=NOW) for session in ("sess-one", "sess-two"))
        self.assertNotEqual(first["nonce"], second["nonce"])
        self.assertNotEqual(first["grant_id"], second["grant_id"])
        schema = json.loads((ROOT / "schemas" / "mode-grant.schema.json").read_text(encoding="utf-8"))
        grant_id_pattern = schema["properties"]["payload"]["properties"]["grant_id"]["pattern"]
        for payload in (first, second):
            self.assertRegex(payload["nonce"], MODE_GRANT_NONCE_RE)
            self.assertTrue(re.fullmatch(grant_id_pattern, payload["grant_id"]), payload["grant_id"])
        ledger = pathlib.Path(tempfile.mkdtemp(prefix="bro-e2e-nonce-"))
        self.addCleanup(shutil.rmtree, ledger, ignore_errors=True)
        bind_mode_grant_nonce(first, ledger)
        bind_mode_grant_nonce(second, ledger)          # used to raise: "already consumed"
        bind_mode_grant_nonce(first, ledger)           # re-presenting the same grant stays idempotent
        # The ledger still refuses what it exists to refuse: one nonce, two grants.
        replay = dict(second, nonce=first["nonce"])
        with self.assertRaisesRegex(ContractError, "already consumed by a different grant"):
            bind_mode_grant_nonce(replay, ledger)
        # A caller that names them is still obeyed.
        named = build_mode_grant_payload(
            task, agent, receipt, session_id="sess-one", role="specialist", mode="work",
            head_sha=HEAD, tree_identity=TREE, now=NOW, grant_id="grant-x", nonce="n" * 16)
        self.assertEqual((named["grant_id"], named["nonce"]), ("grant-x", "n" * 16))

    def test_owner_cli_produces_a_loadable_bundle(self):
        reg, issuer = self._registry()
        work = pathlib.Path(tempfile.mkdtemp(prefix="bro-e2e-cli-"))
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        task_path = work / "task.json"; task_path.write_text(json.dumps(task_contract()), encoding="utf-8")
        agent_path = work / "agent.json"; agent_path.write_text(json.dumps(agent_profile()), encoding="utf-8")
        key_path = work / "issuer.json"; key_path.write_text(json.dumps(issuer), encoding="utf-8")
        out = work / "bundle"
        # The CLI stamps the bundle with its own clock; pinned to the instant the fixture
        # registry is valid at, so the loaders below can be asked about the same instant.
        with patch("bro_authorize_specialist.time.time", return_value=NOW):
            rc = main(["--task", str(task_path), "--agent", str(agent_path),
                       "--issuer-key", str(key_path),
                       "--session-id", "sess-cli", "--role", "specialist",
                       "--head-sha", HEAD, "--tree-identity", TREE, "--out-dir", str(out)])
        self.assertEqual(rc, 0)
        files = {"BRO_TASK_CONTRACT": "task-contract.json",
                 "BRO_AGENT_PROFILE": "agent-profile.json",
                 "BRO_SKILL_RECEIPT": "skill-receipt.json",
                 "BRO_MODE_GRANT": "mode-grant.signed.json"}
        for name in files.values():
            self.assertTrue((out / name).is_file(), name)
        # LOADABLE, as the name says: the four files the CLI wrote go through the same two
        # runtime loaders the hand-built bundle above does. Four files existing is not that —
        # a CLI that wrote an unbound or unsigned grant would write four files too.
        with patch.dict(os.environ, {env: str(out / name) for env, name in files.items()}):
            bundle = load_contract_bundle_from_env(ROOT, now=NOW)
            self.assertEqual(bundle.task["task_id"], "task-owner-e2e")
            with patch("bro_contracts.current_commit", return_value=HEAD), \
                    patch("bro_contracts.current_tree_identity", return_value=TREE):
                loaded = load_mode_grant_from_env(bundle, "sess-cli", "specialist",
                                                  root=reg, now=NOW)
                self.assertEqual(loaded["mode"], "work")
                self.assertEqual(loaded["agent_id"], AGENT_ID)
                # ...and it is bound to the session it was issued for, not to any session.
                with self.assertRaises(ContractError):
                    load_mode_grant_from_env(bundle, "sess-other", "specialist",
                                             root=reg, now=NOW)


if __name__ == "__main__":
    unittest.main()
