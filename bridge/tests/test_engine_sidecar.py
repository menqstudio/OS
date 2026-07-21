"""Tests for bridge/engine_sidecar.py — the stdin->stdout process entry.

Pins the sidecar contract: it always emits a schema-shaped bridge-result, the
self-test mode proves the verified=true happy path, and every real-mode / error
path is fail-closed (result is null). No engine, no provisioning required.
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


_VALID = {"task_id": "t-0001", "task_class": "standard-builder", "rationale": "reply"}


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
                       (*engine_sidecar._PROVISION_ENV, "BRIDGE_SIDECAR_FAKE")}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v

    def test_self_test_mode_emits_verified_result(self):
        doc = _drive(_VALID, argv=["--self-test"])
        self.assertTrue(doc["ok"])
        self.assertIsInstance(doc["result"], str)
        self.assertTrue(doc["result"])  # non-empty
        self.assertIsNone(doc["error"])
        self.assertIsNotNone(doc["receipt"])
        self.assertTrue(doc["receipt"]["verified"])
        self.assertEqual(doc["receipt"]["status"], "completed")

    def test_env_var_does_NOT_activate_fake(self):
        # SECURITY (Architect merge-blocker): fake mode is --self-test (CLI) ONLY.
        # A production launch inherits its parent env; an env-activated fake verifier
        # there would fabricate a "verified" result. Setting the env var WITHOUT the
        # flag must reach real mode and fail closed — never a fake verified receipt.
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

    def test_real_mode_provisioned_but_unaudited_fails_closed(self):
        env = {k: "x" for k in engine_sidecar._PROVISION_ENV}
        doc = _drive(_VALID, env=env)
        self.assertFalse(doc["ok"])
        self.assertIsNone(doc["result"])
        self.assertIn("pending Architect audit", doc["error"])

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
    """The schema itself must ENFORCE ok:true => non-null result + verified receipt."""

    _CONSISTENT_OK = {
        "ok": True,
        "result": "hello",
        "receipt": {"task_id": "t", "status": "completed", "evidence": ["e"], "verified": True},
        "error": None,
    }
    _CONSISTENT_FAIL = {"ok": False, "result": None, "receipt": None, "error": "denied"}

    def _valid(self, doc):
        return _jsonschema.Draft7Validator(_RESULT_SCHEMA).is_valid(doc)

    def test_consistent_success_is_accepted(self):
        self.assertTrue(self._valid(self._CONSISTENT_OK))

    def test_consistent_failure_is_accepted(self):
        self.assertTrue(self._valid(self._CONSISTENT_FAIL))

    def test_ok_true_with_null_result_is_rejected(self):
        bad = dict(self._CONSISTENT_OK, result=None)
        self.assertFalse(self._valid(bad))

    def test_ok_true_with_unverified_receipt_is_rejected(self):
        bad = dict(self._CONSISTENT_OK,
                   receipt=dict(self._CONSISTENT_OK["receipt"], verified=False))
        self.assertFalse(self._valid(bad))

    def test_ok_true_with_null_receipt_is_rejected(self):
        bad = dict(self._CONSISTENT_OK, receipt=None)
        self.assertFalse(self._valid(bad))

    def test_ok_false_with_non_null_result_is_rejected(self):
        bad = dict(self._CONSISTENT_FAIL, result="leaked output")
        self.assertFalse(self._valid(bad))


if __name__ == "__main__":
    unittest.main()
