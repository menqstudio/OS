"""Task-request structured-input contract (Wave 3a slice 3, audit R2 P0-2).

The desktop nonce + request hashes travel to the supervisor/signer, but the EXACT
`system` + structured `history` are the execution/signing AUTHORITY. The signer
recomputes `system_sha256` / `history_sha256` from those exact fields and never trusts
the incoming hash claims -- so a tampered claim can't masquerade as real input evidence.
These tests pin the schema shape and the recompute (matching Rust's JCS).

The recompute is the ENGINE's (`brops_canonical.system_sha256` / `history_sha256`), imported and
held to digests written out below. This file used to carry its own copy of both formulas and
compare the copy with itself, which pinned nothing the signer runs."""
import json
import pathlib
import sys
import unittest

import jsonschema

_BRIDGE = pathlib.Path(__file__).resolve().parents[1]
_ENGINE_RUNTIME = _BRIDGE.parent / "engine" / "runtime"
if str(_ENGINE_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_ENGINE_RUNTIME))

import brops_canonical as bc  # noqa: E402

_CONTRACTS = _BRIDGE / "contracts"
_REQUEST_SCHEMA = json.loads((_CONTRACTS / "task-request.schema.json").read_text("utf-8"))

# The production formulas, under the names the fixtures below already use. `history_sha256`
# matches Rust `governed_history_sha256`: sha256(JCS([{role,content},...])) -- sorted keys per
# object, compact separators, UTF-8.
_sys_hash = bc.system_sha256
_hist_hash = bc.history_sha256


def _request(system: str, history: list, **hash_overrides) -> dict:
    envelope = {
        "protocol": "brops.request.v1", "workspace_id": "ws", "install_id": "in",
        "request_nonce": "n", "requested_at": "1000",
        "generation_config_sha256": "cc" * 32,
    }
    envelope.update(hash_overrides)
    # Computed only when not overridden: a deliberately malformed history has no digest under the
    # production formula, and a test of the SCHEMA states its own claim instead.
    if "system_sha256" not in envelope:
        envelope["system_sha256"] = _sys_hash(system)
    if "history_sha256" not in envelope:
        envelope["history_sha256"] = _hist_hash(history)
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
        for malformed in ([{"role": "user"}], ["not-an-object"]):
            doc = _request("sys", malformed, history_sha256="bb" * 32)
            self.assertFalse(self._valid(doc))
            # The history is the ONLY thing wrong with it.
            self.assertTrue(self._valid(dict(doc, history=[{"role": "user", "content": "hi"}])))

    def test_hashes_recompute_from_the_exact_structured_fields(self):
        history = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
        # Leading space, capitals and a trailing newline: the system string is hashed RAW, so a
        # recompute that trimmed or normalised it would disagree with the digest below.
        doc = _request(" The System\n", history)
        # The signer's recompute from system/history, held to digests that are written out:
        # sha256 of the raw UTF-8 system string, and sha256 of
        # `[{"content":"a","role":"user"},{"content":"b","role":"assistant"}]`.
        self.assertEqual(bc.system_sha256(doc["system"]),
                         "a67d2393e686138b3fd832ecbe495a98e58ee09a7243a01f6bada8d636674361")
        self.assertEqual(bc.history_sha256(doc["history"]),
                         "8a02dbdda04f507f1cde26f33adbf21568b1e4806b478912b271d0ee11ccba91")
        self.assertEqual(
            bc.history_bytes(doc["history"]),
            b'[{"content":"a","role":"user"},{"content":"b","role":"assistant"}]')

    def test_a_tampered_hash_claim_is_caught_by_recompute(self):
        # A request whose system_sha256 does NOT match the real system: recompute
        # (what the signer does) disagrees with the claim -> not real input evidence.
        doc = _request("Real System ", [{"role": "user", "content": "hi"}],
                       system_sha256="00" * 32)
        recomputed = bc.system_sha256(doc["system"])
        self.assertEqual(recomputed, "e08caf22a27367059f1343fe8a6671a870a82bd0fa0531109f00c41b5f041a1c")
        self.assertNotEqual(doc["request"]["system_sha256"], recomputed)
        # ...and the envelope digest the signer derives follows the RECOMPUTED value, so a
        # receipt can never be bound to the claim.
        envelope = {k: v for k, v in doc["request"].items() if k != "protocol"}
        self.assertNotEqual(bc.request_sha256(**envelope),
                            bc.request_sha256(**dict(envelope, system_sha256=recomputed)))

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
