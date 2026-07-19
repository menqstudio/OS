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

from bro_contracts import canonical_json_sha256
from bro_release_v3 import ReleaseV3Error, _validate_executor_state, validate_release_grant_v3


def task():
    return {"task_id":"task-release","agent_id":"agt-p01-r01","repository":{"full_name":"menqstudio/Bro","branch":"release-v3"}}


def manifest():
    return {"candidate_head":"a"*40,"candidate_tree":"b"*64,"x":1}


def receipt():
    return {"verdict":"GREEN","y":2}


def grant(now=1000):
    t,m,r=task(),manifest(),receipt()
    return {
        "schema":3,"grant_id":"grant-v3","nonce":"nonce-000000000001",
        "principal_id":"owner-gev","task_id":t["task_id"],
        "task_contract_sha256":canonical_json_sha256(t),
        "completion_manifest_sha256":canonical_json_sha256(m),
        "verifier_receipt_sha256":canonical_json_sha256(r),
        "repository":"menqstudio/Bro","remote":"https://github.com/menqstudio/Bro.git",
        "branch":"release-v3","expected_head_sha":"a"*40,
        "expected_tree_identity":"b"*64,"allowed_action":"git-push",
        "issued_at_epoch":now-10,"expires_at_epoch":now+100,
    }


class ReleaseV3Tests(unittest.TestCase):
    def validate(self, value, now=1000):
        with patch("bro_release_v3.resolve_state", return_value=SimpleNamespace(head_sha="a"*40, tree_identity="b"*64)), patch("bro_release_v3._origin", return_value="git@github.com:menqstudio/Bro.git"):
            return validate_release_grant_v3(value, task=task(), manifest=manifest(), receipt=receipt(), now=now)

    def test_exact_evidence_bound_grant_is_valid(self):
        self.assertEqual(self.validate(grant())["schema"], 3)

    def test_v2_live_grant_is_denied(self):
        value=grant(); value["schema"]=2
        with self.assertRaises(ReleaseV3Error): self.validate(value)

    def test_wrong_owner_action_and_hashes_are_denied(self):
        for field,wrong in (("principal_id","Gev"),("allowed_action","merge"),("task_contract_sha256","0"*64),("completion_manifest_sha256","1"*64),("verifier_receipt_sha256","2"*64),("expected_head_sha","c"*40),("expected_tree_identity","d"*64),("branch","other")):
            value=grant(); value[field]=wrong
            with self.assertRaises(ReleaseV3Error, msg=field): self.validate(value)

    def test_expired_grant_is_denied(self):
        value=grant(); value["expires_at_epoch"]=999
        with self.assertRaises(ReleaseV3Error): self.validate(value)

    def test_remote_mismatch_is_denied(self):
        value=grant(); value["remote"]="other/repo"
        with self.assertRaises(ReleaseV3Error): self.validate(value)

    def test_release_settlement_requires_canonical_executor_state(self):
        with patch("bro_release_v3.expected_agent_id", return_value="agt-p01-r01"):
            _validate_executor_state("agt-p01-r01", "release", "push-executor")
            for agent, mode, role in [
                ("wrong", "release", "push-executor"),
                ("agt-p01-r01", "work", "push-executor"),
                ("agt-p01-r01", "release", "builder"),
            ]:
                with self.assertRaises(ReleaseV3Error):
                    _validate_executor_state(agent, mode, role)


class ReleaseGrantEd25519Tests(unittest.TestCase):
    """Owner Authorization Phase 1: the live Release Grant V3 is verified with
    Ed25519 against the operator-signed registry, not HMAC. The push gate runs in
    the executor's process, so only the offline release authority can sign a
    grant; a wrong-authority or tampered grant is refused, the signed grant
    conforms to the schema, and the nonce reserve/finalize ledger flow is
    unchanged."""

    NOW = 1000

    def _fixture(self):
        sys.path.insert(0, str(ROOT / "tools"))
        from broctl import build_registry, generate_key, sign_payload
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="bro-rel-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "config").mkdir(parents=True)
        keys = {a: generate_key(a, f"dev-{a}", False)
                for a in ("operator-root", "release", "issuer")}
        (tmp / "config" / "trusted-keys.json").write_text(
            json.dumps(build_registry(list(keys.values()), self.NOW, 100_000)), encoding="utf-8")
        return tmp, keys, sign_payload

    def _sign(self, sign_payload, key, payload):
        body = {"artifact_type": "release-grant", "key_id": key["key_id"], **payload}
        return sign_payload(key["private_key"], body)

    def _signed_call(self, tmp, doc):
        from bro_release_v3 import _signed
        path = tmp / "grant.signed.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        with patch.dict(os.environ, {"BRO_RELEASE_GRANT": str(path)}):
            return _signed("BRO_RELEASE_GRANT", "release-grant", root=tmp, now=self.NOW)

    def test_release_authority_signed_grant_loads(self):
        tmp, keys, sign = self._fixture()
        loaded = self._signed_call(tmp, self._sign(sign, keys["release"], grant(self.NOW)))
        self.assertEqual(loaded["principal_id"], "owner-gev")

    def test_wrong_authority_may_not_sign_release_grant(self):
        tmp, keys, sign = self._fixture()
        with self.assertRaises(ReleaseV3Error):
            self._signed_call(tmp, self._sign(sign, keys["issuer"], grant(self.NOW)))

    def test_tampered_release_grant_is_rejected(self):
        tmp, keys, sign = self._fixture()
        signed = self._sign(sign, keys["release"], grant(self.NOW))
        signed["payload"]["allowed_action"] = "merge"  # altered after signing
        with self.assertRaises(ReleaseV3Error):
            self._signed_call(tmp, signed)

    def test_signed_grant_conforms_to_schema(self):
        import jsonschema
        tmp, keys, sign = self._fixture()
        signed = self._sign(sign, keys["release"], grant(self.NOW))
        schema = json.loads((ROOT / "schemas" / "release-grant.schema.json").read_text(encoding="utf-8"))
        jsonschema.validate(signed, schema)
        self.assertEqual(len(signed["signature"]), 128)

    def test_nonce_reserve_finalize_unchanged_on_signed_grant(self):
        from bro_security import SecurityError, finalize_nonce, reserve_nonce
        tmp, keys, sign = self._fixture()
        payload = self._signed_call(tmp, self._sign(sign, keys["release"], grant(self.NOW)))
        ledger = tmp / "ledger"
        cmd = "git push origin HEAD:release-v3"
        reserve_nonce(payload, ledger, "tool-1", cmd)
        with self.assertRaises(SecurityError):          # replay of the reservation is denied
            reserve_nonce(payload, ledger, "tool-1", cmd)
        finalize_nonce(payload, ledger, "tool-1", cmd)  # the reserved nonce finalizes


class LegacyReleaseGrantRetiredTests(unittest.TestCase):
    """Ed25519 Release Grant V3 (bro_release_v3) is the only live release path.
    The unsigned v1 loader and the HMAC v2 loader in bro_contracts were dead code
    — no runtime module or test called them — and are retired. This guards against
    their re-introduction: a second, weaker release-authorization path is exactly
    the kind of drift the single V3 path exists to prevent."""

    def test_legacy_release_grant_loaders_are_gone(self):
        import bro_contracts
        for symbol in (
            "validate_release_grant",           # v1 (unsigned)
            "load_release_grant_from_env",      # v1 loader
            "validate_release_grant_v2",        # v2 (HMAC)
            "load_release_grant_v2_from_env",   # v2 loader
            "_signed_payload_from_env",         # helper only the v2 loader used
        ):
            self.assertFalse(hasattr(bro_contracts, symbol),
                             f"legacy release-grant symbol still present: {symbol}")

    def test_v3_release_path_remains(self):
        from bro_release_v3 import validate_release_grant_v3  # noqa: F401  the live path


if __name__ == "__main__":
    unittest.main()
