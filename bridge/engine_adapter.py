"""Bridge engine adapter — Phase 1, slice 1 (T-003).

Desktop-facing entrypoint. Turns a desktop AI-turn request into a GOVERNED run
through the engine supervisor: the supervisor issues a lease to a SEPARATE
builder, runs it behind the wall, and returns a receipt. The desktop is a
conductor and never holds the lease / key / environment — those live in the
operator-provisioned supervisor sidecar that hosts this adapter (engine_sidecar.py).

Invariants (Architect sign-off, T-003):
  * fail-closed  — any error, or a run that is not COMPLETED, yields NO result.
  * receipt mandatory — a result is returned ONLY together with a non-empty
    receipt (status "completed" + evidence). Denied / uncontained -> error only.
  * engine core untouched — this only *calls* bro_supervisor.run_task through an
    injected callable; it imports no lease/key/wall logic itself.
"""
from __future__ import annotations

import json
import pathlib
from typing import Any, Callable

import jsonschema

# Mirror of bro_supervisor's terminal success status, kept local so this module
# is testable without importing the engine.
COMPLETED = "completed"

_CONTRACTS = pathlib.Path(__file__).resolve().parent / "contracts"
_REQUEST_SCHEMA = json.loads((_CONTRACTS / "task-request.schema.json").read_text(encoding="utf-8"))

Request = dict[str, Any]
Receipt = dict[str, Any]
Result = dict[str, Any]


def _fail(task_id: str | None, error: str, *, receipt: Receipt | None = None) -> Result:
    # Fail-closed: a failure NEVER carries a result.
    return {"ok": False, "result": None, "receipt": receipt, "error": error}


def _receipt_of(outcome: Any) -> Receipt:
    return {
        "task_id": getattr(outcome, "task_id", None),
        "status": getattr(outcome, "status", None),
        "exit_code": getattr(outcome, "exit_code", None),
        "evidence": list(getattr(outcome, "evidence", ()) or ()),
        # A receipt is a receipt only once it VERIFIES. Default false; set true by
        # run_governed_turn ONLY after the injected verifier confirms the evidence.
        "verified": False,
    }


def run_governed_turn(
    request: Request,
    *,
    run_task: Callable[[Request], Any],
    verify_receipt: Callable[[Any], bool],
    read_result: Callable[[Any], str],
) -> Result:
    """Run one desktop AI turn as a governed engine task.

    Parameters
    ----------
    request : dict
        A bridge.task-request (validated here against the contract).
    run_task : callable(request_dict) -> SupervisorResult
        The engine supervisor, already bound to the sidecar's operator
        provisioning (keys, registry, workspace binding, repo, builder command).
    verify_receipt : callable(SupervisorResult) -> bool
        Confirms the run's evidence is a genuine SIGNED/verified receipt. The
        adapter holds no keys, so it delegates verification to the engine
        (wired in the sidecar). A result is NEVER returned for an outcome that
        does not verify — "receipt mandatory" means "verified receipt mandatory".
    read_result : callable(SupervisorResult) -> str
        Reads the builder's captured output after a COMPLETED, verified run.

    Returns
    -------
    dict conforming to bridge/contracts/bridge-result.schema.json.
    """
    task_id = request.get("task_id") if isinstance(request, dict) else None

    # Fail-closed on a malformed request — never reach the supervisor with junk.
    try:
        jsonschema.validate(request, _REQUEST_SCHEMA)
    except jsonschema.ValidationError as exc:
        return _fail(task_id, f"invalid task request: {exc.message}")

    # Any supervisor / authorization error is a closed door, not a result.
    try:
        outcome = run_task(request)
    except Exception as exc:  # noqa: BLE001 — deliberately fail closed on anything
        return _fail(task_id, f"supervisor error: {exc}")

    receipt = _receipt_of(outcome)

    if receipt["status"] != COMPLETED:
        # denied / uncontained / any non-success terminal state -> no result
        return _fail(
            receipt["task_id"] or task_id,
            f"run not completed: {receipt['status']}: {getattr(outcome, 'message', '')}".rstrip(": "),
            receipt=receipt,
        )

    if not receipt["evidence"]:
        # Receipt mandatory: a completed run with no evidence is not a receipt.
        return _fail(
            receipt["task_id"] or task_id,
            "completed run produced no evidence — refusing an unreceipted result",
        )

    # A receipt is only a receipt if it VERIFIES. The adapter holds no keys, so it
    # delegates to the injected verifier (wired to the engine's evidence/signature
    # verification in the sidecar). Fail-closed on a failed or erroring verification.
    try:
        verified = bool(verify_receipt(outcome))
    except Exception as exc:  # noqa: BLE001 — fail closed
        return _fail(receipt["task_id"] or task_id, f"receipt verification error: {exc}", receipt=receipt)
    receipt["verified"] = verified
    if not verified:
        return _fail(
            receipt["task_id"] or task_id,
            "run evidence did not verify — refusing an unverified receipt",
            receipt=receipt,
        )

    try:
        result = read_result(outcome)
    except Exception as exc:  # noqa: BLE001
        return _fail(receipt["task_id"] or task_id, f"could not read builder result: {exc}", receipt=receipt)

    if not isinstance(result, str) or not result:
        return _fail(receipt["task_id"] or task_id, "builder produced no textual result", receipt=receipt)

    return {"ok": True, "result": result, "receipt": receipt, "error": None}
