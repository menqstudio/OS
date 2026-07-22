"""Unit tests for the bridge engine adapter (T-003 + Wave 3a slice 3).

The engine supervisor is dependency-injected (no real keys/leases/wall needed).
Trust is now a DESKTOP signature check (design §3), so the adapter makes NO trust
decision: it carries the run's SIGNED receipt material and is otherwise fail-closed.
These tests pin: fail-closed, receipt-mandatory, signed-material-carried, and that
there is NO self-asserted `verified` field the desktop could be fooled into trusting.
"""
import sys
import pathlib
import types
import unittest

# Make `import engine_adapter` work whether run from repo root or bridge/.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import engine_adapter  # noqa: E402


def _outcome(task_id="t1", status="completed", exit_code=0, evidence=("ev-1",),
             message="", envelope_jcs_b64=None, signature_b64=None):
    return types.SimpleNamespace(
        task_id=task_id, status=status, exit_code=exit_code,
        evidence=tuple(evidence), message=message,
        receipt_envelope_jcs_b64=envelope_jcs_b64,
        receipt_signature_b64=signature_b64,
    )


VALID_REQUEST = {"task_id": "t1", "task_class": "standard-builder", "rationale": "reply to user"}


class RunGovernedTurnTests(unittest.TestCase):
    def _run(self, *, run_task, read_result=lambda o: "hello", request=None):
        return engine_adapter.run_governed_turn(
            request if request is not None else dict(VALID_REQUEST),
            run_task=run_task, read_result=read_result,
        )

    def test_completed_carries_signed_material_and_no_verified_field(self):
        res = self._run(run_task=lambda r: _outcome(envelope_jcs_b64="env==", signature_b64="sig=="))
        self.assertTrue(res["ok"])
        self.assertEqual(res["result"], "hello")
        self.assertEqual(res["receipt"]["status"], "completed")
        self.assertEqual(res["receipt"]["evidence"], ["ev-1"])
        # The signed material the DESKTOP verifies is carried through verbatim.
        self.assertEqual(res["receipt"]["envelope_jcs_b64"], "env==")
        self.assertEqual(res["receipt"]["signature_b64"], "sig==")
        # There is NO self-asserted trust boolean — trust is a desktop signature check.
        self.assertNotIn("verified", res["receipt"])
        self.assertIsNone(res["error"])

    def test_unsigned_completed_run_returns_ok_with_null_wire_no_trust_claim(self):
        # Wave 3a has no isolated signer -> no signature. The bridge does NOT assert
        # trust; it carries a null wire and the DESKTOP Blocks it (verified elsewhere).
        res = self._run(run_task=lambda r: _outcome())  # envelope/signature default None
        self.assertTrue(res["ok"])
        self.assertIsNone(res["receipt"]["envelope_jcs_b64"])
        self.assertIsNone(res["receipt"]["signature_b64"])
        self.assertNotIn("verified", res["receipt"])

    def test_denied_run_is_fail_closed_no_result(self):
        res = self._run(run_task=lambda r: _outcome(status="denied", evidence=(), message="not authorized"))
        self.assertFalse(res["ok"])
        self.assertIsNone(res["result"])          # <-- the whole point
        self.assertIn("not completed", res["error"])

    def test_completed_without_evidence_refuses_result(self):
        # A completed run with no evidence is NOT a receipt -> no result.
        res = self._run(run_task=lambda r: _outcome(status="completed", evidence=()))
        self.assertFalse(res["ok"])
        self.assertIsNone(res["result"])
        self.assertIsNone(res["receipt"])
        self.assertIn("no evidence", res["error"])

    def test_supervisor_exception_is_fail_closed(self):
        def boom(_r):
            raise RuntimeError("lease service down")
        res = self._run(run_task=boom)
        self.assertFalse(res["ok"])
        self.assertIsNone(res["result"])
        self.assertIn("supervisor error", res["error"])

    def test_invalid_request_never_reaches_supervisor(self):
        called = []
        res = self._run(run_task=lambda r: called.append(r) or _outcome(),
                        request={"task_id": "t1"})  # missing task_class + rationale
        self.assertFalse(res["ok"])
        self.assertIsNone(res["result"])
        self.assertIn("invalid task request", res["error"])
        self.assertEqual(called, [])  # supervisor was never called

    def test_completed_but_empty_result_is_rejected(self):
        res = self._run(run_task=lambda r: _outcome(), read_result=lambda o: "")
        self.assertFalse(res["ok"])
        self.assertIsNone(res["result"])
        self.assertIn("no textual result", res["error"])

    def test_result_read_error_is_fail_closed(self):
        def bad_read(_o):
            raise OSError("output file missing")
        res = self._run(run_task=lambda r: _outcome(), read_result=bad_read)
        self.assertFalse(res["ok"])
        self.assertIsNone(res["result"])
        self.assertIn("could not read builder result", res["error"])

    def test_failure_never_carries_a_result_invariant(self):
        # Sweep the failure modes; result must be None in every one.
        cases = [
            lambda: self._run(run_task=lambda r: _outcome(status="denied", evidence=())),
            lambda: self._run(run_task=lambda r: _outcome(status="uncontained", evidence=("e",))),
            lambda: self._run(run_task=lambda r: _outcome(evidence=())),
            lambda: self._run(run_task=lambda r: (_ for _ in ()).throw(RuntimeError("x"))),
        ]
        for run in cases:
            res = run()
            self.assertFalse(res["ok"])
            self.assertIsNone(res["result"])

    def test_no_verified_field_anywhere_even_on_failure(self):
        # The removed authority must not resurface in any receipt the adapter emits.
        res = self._run(run_task=lambda r: _outcome(status="denied", evidence=("e",)))
        self.assertIsNotNone(res["receipt"])
        self.assertNotIn("verified", res["receipt"])


if __name__ == "__main__":
    unittest.main()
