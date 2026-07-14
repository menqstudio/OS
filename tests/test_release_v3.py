import pathlib
import sys
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


if __name__ == "__main__":
    unittest.main()
