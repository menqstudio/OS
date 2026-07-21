"""Unit tests for the bridge engine adapter (T-003, slice 1).

The engine supervisor is dependency-injected (no real keys/leases/wall needed),
so these tests pin the two invariants that matter: fail-closed, receipt-mandatory.
"""
import sys
import pathlib
import types
import unittest

# Make `import engine_adapter` work whether run from repo root or bridge/.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import engine_adapter  # noqa: E402


def _outcome(task_id="t1", status="completed", exit_code=0, evidence=("ev-1",), message=""):
    return types.SimpleNamespace(
        task_id=task_id, status=status, exit_code=exit_code,
        evidence=tuple(evidence), message=message,
    )


VALID_REQUEST = {"task_id": "t1", "task_class": "standard-builder", "rationale": "reply to user"}


class RunGovernedTurnTests(unittest.TestCase):
    def _run(self, *, run_task, verify_receipt=lambda o: True, read_result=lambda o: "hello", request=None):
        return engine_adapter.run_governed_turn(
            request if request is not None else dict(VALID_REQUEST),
            run_task=run_task, verify_receipt=verify_receipt, read_result=read_result,
        )

    def test_completed_verified_returns_result_and_receipt(self):
        res = self._run(run_task=lambda r: _outcome())
        self.assertTrue(res["ok"])
        self.assertEqual(res["result"], "hello")
        self.assertIsNotNone(res["receipt"])
        self.assertEqual(res["receipt"]["status"], "completed")
        self.assertEqual(res["receipt"]["evidence"], ["ev-1"])
        self.assertTrue(res["receipt"]["verified"])   # a result implies a VERIFIED receipt
        self.assertIsNone(res["error"])

    def test_unverified_receipt_is_fail_closed(self):
        # Completed + evidence, but the evidence does NOT verify -> no result.
        res = self._run(run_task=lambda r: _outcome(), verify_receipt=lambda o: False)
        self.assertFalse(res["ok"])
        self.assertIsNone(res["result"])              # <-- never a result without a verified receipt
        self.assertFalse(res["receipt"]["verified"])
        self.assertIn("did not verify", res["error"])

    def test_verification_exception_is_fail_closed(self):
        def boom(_o):
            raise RuntimeError("verifier unreachable")
        res = self._run(run_task=lambda r: _outcome(), verify_receipt=boom)
        self.assertFalse(res["ok"])
        self.assertIsNone(res["result"])
        self.assertIn("verification error", res["error"])

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
            lambda: self._run(run_task=lambda r: _outcome(), verify_receipt=lambda o: False),
            lambda: self._run(run_task=lambda r: (_ for _ in ()).throw(RuntimeError("x"))),
        ]
        for run in cases:
            res = run()
            self.assertFalse(res["ok"])
            self.assertIsNone(res["result"])


if __name__ == "__main__":
    unittest.main()
