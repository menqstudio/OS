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
        # The SIGNED receipt material the DESKTOP verifies (design §3): the exact
        # canonical envelope bytes (base64url) and the Ed25519 signature over them.
        # `None` when the engine produced no signed receipt (Wave 3a has no isolated
        # signer) — the desktop then Blocks. There is NO self-asserted `verified`
        # boolean; trust is the desktop's signature check, never a bridge claim.
        "envelope_jcs_b64": getattr(outcome, "receipt_envelope_jcs_b64", None),
        "signature_b64": getattr(outcome, "receipt_signature_b64", None),
    }


def run_governed_turn(
    request: Request,
    *,
    run_task: Callable[[Request], Any],
    read_result: Callable[[Any], str],
) -> Result:
    """Run one desktop AI turn as a governed engine task.

    The adapter holds no keys and makes NO trust decision: it packages the run's
    SIGNED receipt material (`envelope_jcs_b64` + `signature_b64`) for the DESKTOP,
    which is the final authority and cryptographically verifies the signature
    (design §3). There is no `verify_receipt` callable and no self-asserted
    `verified` boolean — an unsigned/missing receipt is simply carried through, and
    the desktop Blocks it.

    Parameters
    ----------
    request : dict
        A bridge.task-request (validated here against the contract).
    run_task : callable(request_dict) -> SupervisorResult
        The engine supervisor, already bound to the sidecar's operator
        provisioning (keys, registry, workspace binding, repo, builder command).
    read_result : callable(SupervisorResult) -> str
        Reads the builder's captured output after a COMPLETED run.

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

    # NO trust decision here: the adapter carries the receipt's signed material
    # (envelope_jcs_b64 + signature_b64, possibly None) and lets the DESKTOP verify
    # the signature. An unsigned/missing receipt is not a bridge failure — the desktop
    # Blocks it. (design §3 — desktop is the final authority; Python is transport.)
    try:
        result = read_result(outcome)
    except Exception as exc:  # noqa: BLE001
        return _fail(receipt["task_id"] or task_id, f"could not read builder result: {exc}", receipt=receipt)

    if not isinstance(result, str) or not result:
        return _fail(receipt["task_id"] or task_id, "builder produced no textual result", receipt=receipt)

    return {"ok": True, "result": result, "receipt": receipt, "error": None}
