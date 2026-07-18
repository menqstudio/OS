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

from bro_contracts import ContractError, load_mode_grant_from_env, safe_repo_path, validate_agent_profile


class ContractTests(unittest.TestCase):
    def test_safe_repository_paths(self):
        self.assertEqual(safe_repo_path("docs/ARCHITECTURE.md"), "docs/ARCHITECTURE.md")
        for value in ("../secret", "/absolute/path", "C:/Windows/System32"):
            with self.assertRaises(ContractError):
                safe_repo_path(value)

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

    def _fixture(self):
        from broctl import build_registry, generate_key, sign_payload
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="bro-mg-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "config").mkdir(parents=True)
        operator = generate_key("operator-root", "op", False)
        issuer = generate_key("issuer", "iss", False)
        registry = build_registry([operator, issuer], self.NOW, 10_000)
        (tmp / "config" / "trusted-keys.json").write_text(json.dumps(registry), encoding="utf-8")
        return tmp, operator, issuer, sign_payload

    def _grant(self, mode="work", task_sha="c" * 64):
        return {
            "schema": 1, "grant_id": "g-1", "nonce": "n" * 16, "session_id": "sess",
            "agent_id": "agt-p01-r01", "role": "specialist", "mode": mode,
            "task_contract_sha256": task_sha, "repository": "menqstudio/Bro",
            "branch": "feature-x", "head_sha": "a" * 40, "tree_identity": "b" * 64,
            "issued_at_epoch": self.NOW, "expires_at_epoch": self.NOW + 3600,
        }

    def _sign(self, sign_payload, key, grant):
        body = {"artifact_type": "mode-grant", "key_id": key["key_id"], **grant}
        return sign_payload(key["private_key"], body)

    def _load(self, tmp, signed):
        path = tmp / "grant.signed.json"
        path.write_text(json.dumps(signed), encoding="utf-8")
        bundle = SimpleNamespace(agent={"agent_id": "agt-p01-r01"}, task_sha256="c" * 64)
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


if __name__ == "__main__":
    unittest.main()
