"""Tests for bridge/engine_sidecar.py — the stdin->stdout process entry.

Pins the sidecar contract: it always emits a schema-shaped bridge-result, the
self-test mode proves the transport round-trip (carrying the receipt material for the
DESKTOP to verify — the sidecar asserts NO trust), and every real-mode / error path
is fail-closed (result is null). No engine, no provisioning required.
"""
from __future__ import annotations

import io
import json
import os
import pathlib
import unittest

import engine_sidecar

_CONTRACTS = pathlib.Path(__file__).resolve().parents[1] / "contracts"
_RESULT_SCHEMA = json.loads((_CONTRACTS / "bridge-result.schema.json").read_text("utf-8"))

try:
    import jsonschema

    def _validate(doc: dict) -> None:
        jsonschema.validate(doc, _RESULT_SCHEMA)
except Exception:  # pragma: no cover - jsonschema is a declared dep
    def _validate(doc: dict) -> None:  # minimal structural fallback
        assert set(doc) == {"ok", "result", "receipt", "error"}


_VALID = {
    "task_id": "t-0001", "task_class": "standard-builder", "rationale": "reply",
    "system": "you are a specialist",
    "history": [{"role": "user", "content": "hello"}],
    "request": {
        "protocol": "brops.request.v1", "workspace_id": "ws", "install_id": "in",
        "request_nonce": "nonce-1", "system_sha256": "aa" * 32, "history_sha256": "bb" * 32,
        "generation_config_sha256": "cc" * 32, "requested_at": "1000",
    },
}


def _drive(request, argv=(), env=None):
    """Run the sidecar over an in-memory request; return the parsed bridge-result."""
    saved = {}
    if env is not None:
        for k, v in env.items():
            saved[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    try:
        stdin = io.StringIO(request if isinstance(request, str) else json.dumps(request))
        stdout = io.StringIO()
        code = engine_sidecar.run(list(argv), stdin, stdout)
        assert code == 0, "sidecar must always exit 0 (verdict travels in payload)"
        doc = json.loads(stdout.getvalue())
        _validate(doc)
        return doc
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class EngineSidecarTests(unittest.TestCase):
    # Clear any ambient provisioning / fake flag so real-mode tests are deterministic.
    def setUp(self):
        self._saved = {k: os.environ.pop(k, None) for k in
                       (*engine_sidecar._PROVISION_ENV,
                        *engine_sidecar._SIGNER_PROVISION_ENV, "BRIDGE_SIDECAR_FAKE")}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v

    def test_self_test_mode_round_trip_carries_receipt_and_asserts_no_trust(self):
        doc = _drive(_VALID, argv=["--self-test"])
        self.assertTrue(doc["ok"])
        self.assertIsInstance(doc["result"], str)
        self.assertTrue(doc["result"])  # non-empty
        self.assertIsNone(doc["error"])
        self.assertIsNotNone(doc["receipt"])
        self.assertEqual(doc["receipt"]["status"], "completed")
        # The self-test carries NO signature (no signer) and NO `verified` boolean —
        # the desktop would Block it. The round-trip is proven, not a trust bypass.
        self.assertIsNone(doc["receipt"]["signature_b64"])
        self.assertNotIn("verified", doc["receipt"])

    def test_env_var_does_NOT_activate_fake(self):
        # SECURITY (Architect merge-blocker): fake mode is --self-test (CLI) ONLY.
        # A production launch inherits its parent env; an env-activated self-test there
        # would emit a canned result. Setting the env var WITHOUT the flag must reach
        # real mode and fail closed — never a fabricated result.
        doc = _drive(_VALID, env={"BRIDGE_SIDECAR_FAKE": "1"})
        self.assertFalse(doc["ok"])
        self.assertIsNone(doc["result"])
        self.assertIsInstance(doc["error"], str)
        self.assertNotIn("SELF-TEST", doc["error"] or "")

    def test_invalid_json_stdin_fails_closed(self):
        doc = _drive("this is not json", argv=["--self-test"])
        self.assertFalse(doc["ok"])
        self.assertIsNone(doc["result"])
        self.assertIn("invalid task-request", doc["error"])

    def test_non_object_request_fails_closed(self):
        doc = _drive("[1,2,3]", argv=["--self-test"])
        self.assertFalse(doc["ok"])
        self.assertIsNone(doc["result"])

    def test_self_test_missing_required_field_fails_closed(self):
        # rationale missing -> adapter schema validation fails closed, no result.
        doc = _drive({"task_id": "t", "task_class": "standard-builder"}, argv=["--self-test"])
        self.assertFalse(doc["ok"])
        self.assertIsNone(doc["result"])

    def test_real_mode_unprovisioned_fails_closed(self):
        doc = _drive(_VALID)  # no --self-test, no env
        self.assertFalse(doc["ok"])
        self.assertIsNone(doc["result"])
        self.assertIn("not provisioned", doc["error"])

    def test_real_mode_provisioned_but_no_signer_material_fails_closed(self):
        # Supervisor provisioning present, but the receipt-signer material
        # (`_SIGNER_PROVISION_ENV`, its OWN custody — never BRO_KEYDIR) is absent.
        env = {k: "x" for k in engine_sidecar._PROVISION_ENV}
        doc = _drive(_VALID, env=env)
        self.assertFalse(doc["ok"])
        self.assertIsNone(doc["result"])
        self.assertIn("receipt signer not provisioned", doc["error"])

    def test_real_mode_fully_provisioned_still_fails_closed_pending_live_wiring(self):
        # Both env sets present: the signer chain exists, but the live supervisor
        # run-state provider + desktop trusted manifest are pending (design §5 STOP), so
        # real mode still emits nothing — never an unsigned/partial result.
        env = {k: "x" for k in (*engine_sidecar._PROVISION_ENV,
                                *engine_sidecar._SIGNER_PROVISION_ENV)}
        doc = _drive(_VALID, env=env)
        self.assertFalse(doc["ok"])
        self.assertIsNone(doc["result"])
        self.assertIn("pending", doc["error"])

    def test_self_test_signed_mints_a_real_signed_receipt_desktop_still_blocks(self):
        # Exercises the REAL Wave 3b signer/store/attestation chain end to end. The
        # bridge result is schema-valid and carries a real Ed25519 signature over the
        # canonical envelope + the containment bytes — but there is no trusted manifest,
        # so the desktop would still Block (design §5 STOP: no "Verified" in 3b-1).
        import base64

        doc = _drive(_VALID, argv=["--self-test-signed"])
        self.assertTrue(doc["ok"], doc.get("error"))
        self.assertIsInstance(doc["result"], str)
        receipt = doc["receipt"]
        self.assertEqual(receipt["status"], "completed")
        self.assertNotIn("verified", receipt)
        # Real signed wire present.
        self.assertTrue(receipt["envelope_jcs_b64"])
        self.assertTrue(receipt["signature_b64"])
        self.assertTrue(receipt["containment_evidence_b64"])
        # The envelope is the 21-field brops.receipt.v1 (decodes as strict JSON).
        env_bytes = base64.urlsafe_b64decode(
            receipt["envelope_jcs_b64"] + "=" * (-len(receipt["envelope_jcs_b64"]) % 4)
        )
        envelope = json.loads(env_bytes)
        self.assertEqual(envelope["protocol"], "brops.receipt.v1")
        self.assertEqual(envelope["decision"], "completed")
        # Forensic-attestation record relayed to the desktop (P1-6).
        self.assertTrue(receipt["attestation_evidence_jcs_b64"])
        self.assertTrue(receipt["attestation_signature_b64"])
        self.assertEqual(receipt["supervisor_attestation_key_id"], "self-test-attestation-key")
        self.assertTrue(receipt["run_id"] and receipt["lease_id"] and receipt["execution_attempt_id"])

    def test_result_never_carries_result_on_any_failure(self):
        # Sweep: every non-happy path has result is None.
        for req, argv, env in (
            ("garbage", ["--self-test"], None),
            (_VALID, [], None),                                   # unprovisioned
            (_VALID, [], {k: "x" for k in engine_sidecar._PROVISION_ENV}),  # unaudited
        ):
            doc = _drive(req, argv=argv, env=env)
            if not doc["ok"]:
                self.assertIsNone(doc["result"])


try:
    import jsonschema as _jsonschema
except Exception:  # pragma: no cover - jsonschema is a declared dep
    _jsonschema = None


@unittest.skipUnless(_jsonschema is not None, "jsonschema not installed")
class ResultSchemaInvariantTests(unittest.TestCase):
    """The schema ENFORCES ok:true => non-null result + a receipt carrying the signed
    material (envelope_jcs_b64 + signature_b64) — and NEVER a `verified` boolean."""

    _CONSISTENT_OK = {
        "ok": True,
        "result": "hello",
        "receipt": {
            "task_id": "t", "status": "completed", "evidence": ["e"],
            "envelope_jcs_b64": "env==", "signature_b64": "sig==",
        },
        "error": None,
    }
    _CONSISTENT_FAIL = {"ok": False, "result": None, "receipt": None, "error": "denied"}

    def _valid(self, doc):
        return _jsonschema.Draft7Validator(_RESULT_SCHEMA).is_valid(doc)

    def test_consistent_success_is_accepted(self):
        self.assertTrue(self._valid(self._CONSISTENT_OK))

    def test_unsigned_success_is_accepted_desktop_blocks_it(self):
        # An unsigned receipt (null wire) is a VALID payload — the desktop, not the
        # schema, is the authority that Blocks it.
        ok = dict(self._CONSISTENT_OK,
                  receipt=dict(self._CONSISTENT_OK["receipt"], envelope_jcs_b64=None, signature_b64=None))
        self.assertTrue(self._valid(ok))

    def test_consistent_failure_is_accepted(self):
        self.assertTrue(self._valid(self._CONSISTENT_FAIL))

    def test_ok_true_with_null_result_is_rejected(self):
        bad = dict(self._CONSISTENT_OK, result=None)
        self.assertFalse(self._valid(bad))

    def test_receipt_with_a_verified_field_is_rejected(self):
        # The removed self-asserted authority must not be smuggled back in.
        bad = dict(self._CONSISTENT_OK,
                   receipt=dict(self._CONSISTENT_OK["receipt"], verified=True))
        self.assertFalse(self._valid(bad))

    def test_receipt_missing_signed_material_field_is_rejected(self):
        r = dict(self._CONSISTENT_OK["receipt"])
        del r["signature_b64"]
        self.assertFalse(self._valid(dict(self._CONSISTENT_OK, receipt=r)))

    def test_ok_true_with_null_receipt_is_rejected(self):
        bad = dict(self._CONSISTENT_OK, receipt=None)
        self.assertFalse(self._valid(bad))

    def test_ok_false_with_non_null_result_is_rejected(self):
        bad = dict(self._CONSISTENT_FAIL, result="leaked output")
        self.assertFalse(self._valid(bad))


if __name__ == "__main__":
    unittest.main()
