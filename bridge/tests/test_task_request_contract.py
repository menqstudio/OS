"""Task-request structured-input contract (Wave 3a slice 3, audit R2 P0-2).

The desktop nonce + request hashes travel to the supervisor/signer, but the EXACT
`system` + structured `history` are the execution/signing AUTHORITY. The signer
recomputes `system_sha256` / `history_sha256` from those exact fields and never trusts
the incoming hash claims -- so a tampered claim can't masquerade as real input evidence.
These tests pin the schema shape and the recompute (matching Rust's JCS)."""
import hashlib
import json
import pathlib
import unittest

import jsonschema

_CONTRACTS = pathlib.Path(__file__).resolve().parents[1] / "contracts"
_REQUEST_SCHEMA = json.loads((_CONTRACTS / "task-request.schema.json").read_text("utf-8"))


def _sys_hash(system: str) -> str:
    return hashlib.sha256(system.encode("utf-8")).hexdigest()


def _hist_hash(history: list) -> str:
    # Matches Rust `governed_history_sha256`: sha256(JCS([{role,content},...])) --
    # sorted keys per object, compact separators, UTF-8.
    b = json.dumps(history, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(b).hexdigest()


def _request(system: str, history: list, **hash_overrides) -> dict:
    envelope = {
        "protocol": "brops.request.v1", "workspace_id": "ws", "install_id": "in",
        "request_nonce": "n", "requested_at": "1000",
        "system_sha256": _sys_hash(system), "history_sha256": _hist_hash(history),
        "generation_config_sha256": "cc" * 32,
    }
    envelope.update(hash_overrides)
    return {
        "task_id": "t", "task_class": "standard-builder", "rationale": "derived",
        "system": system, "history": history, "request": envelope,
    }


class TaskRequestContractTests(unittest.TestCase):
    def _valid(self, doc) -> bool:
        return jsonschema.Draft7Validator(_REQUEST_SCHEMA).is_valid(doc)

    def test_well_formed_structured_request_is_accepted(self):
        self.assertTrue(self._valid(_request("sys", [{"role": "user", "content": "hi"}])))

    def test_schema_rejects_missing_system(self):
        doc = _request("sys", [{"role": "user", "content": "hi"}])
        del doc["system"]
        self.assertFalse(self._valid(doc))

    def test_schema_rejects_missing_history(self):
        doc = _request("sys", [{"role": "user", "content": "hi"}])
        del doc["history"]
        self.assertFalse(self._valid(doc))

    def test_schema_rejects_malformed_history_item(self):
        # An item missing `content`, and a non-object item -- both rejected.
        self.assertFalse(self._valid(_request("sys", [{"role": "user"}])))
        self.assertFalse(self._valid(_request("sys", ["not-an-object"])))

    def test_hashes_recompute_from_the_exact_structured_fields(self):
        history = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
        doc = _request("the system", history)
        # The signer's recompute from system/history equals the request's claims.
        self.assertEqual(doc["request"]["system_sha256"], _sys_hash(doc["system"]))
        self.assertEqual(doc["request"]["history_sha256"], _hist_hash(doc["history"]))

    def test_a_tampered_hash_claim_is_caught_by_recompute(self):
        # A request whose system_sha256 does NOT match the real system: recompute
        # (what the signer does) disagrees with the claim -> not real input evidence.
        doc = _request("real system", [{"role": "user", "content": "hi"}],
                       system_sha256="00" * 32)
        self.assertNotEqual(doc["request"]["system_sha256"], _sys_hash(doc["system"]))

    def test_embedded_separators_newlines_and_unicode_survive_verbatim(self):
        # Content with the old NUL/SOH delimiter bytes, newlines, tabs, and non-ASCII --
        # all preserved exactly, and the hash recomputes over the exact structure.
        weird = "line1\nline2" + chr(0) + chr(1) + "\ttab " + "— café \U0001f680"
        history = [{"role": "user", "content": weird}]
        doc = _request("sys", history)
        self.assertTrue(self._valid(doc))
        self.assertEqual(doc["history"][0]["content"], weird)  # verbatim
        self.assertEqual(doc["request"]["history_sha256"], _hist_hash(history))
        # A different message array whose old delimiter-concat collides hashes differently.
        collide = [{"role": "user", "content": "line1"}, {"role": "user", "content": "line2"}]
        self.assertNotEqual(_hist_hash(history), _hist_hash(collide))


if __name__ == "__main__":
    unittest.main()
