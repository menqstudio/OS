#!/usr/bin/env python3
"""bridge/engine_sidecar.py — the process the desktop cockpit shells out to.

The desktop is a *conductor*: it never holds a lease, a key, or the engine. It
writes ONE `bridge.task-request` JSON to this sidecar's **stdin** and reads ONE
`bridge.result` JSON from **stdout**. The sidecar hosts
`bridge.engine_adapter.run_governed_turn`, injecting the three engine-side
callables (`run_task` / `verify_receipt` / `read_result`). The adapter enforces the
product-wide invariant: **a result is returned ONLY with a receipt whose evidence
VERIFIES (`verified=true`); every failure is fail-closed (`result=null`).**

Modes
-----
* ``--self-test`` / ``BRIDGE_SIDECAR_FAKE=1`` — inject canned callables (no engine,
  no provisioning). Proves the stdin->stdout->bridge-result path end to end,
  including the ``verified=true`` happy path. Used by CI + unit tests.
  **Never for real use** (it fabricates a passing verifier).
* real (default) — wire the engine. Requires operator-provisioned state on disk
  (issuer key, trusted-key registry, signed workspace binding, builder command),
  supplied via env: ``BRO_KEYDIR``, ``BRO_REGISTRY_ROOT``, ``BRO_BINDING``,
  ``BRO_REPOSITORY_ROOT``, ``BRO_BUILDER_COMMAND``. Absent provisioning -> fail
  closed.

SECURITY — the verify seam is deliberately NOT wired here yet
------------------------------------------------------------
Deciding that a `SupervisorResult` carries a *genuine signed, verified* receipt is
security-critical (a wrong verifier would let an unverified turn masquerade as
verified). That wiring (engine-delegated receipt verification + result extraction)
is a **🛑 Architect-audited follow-up** per the roadmap's §G/§I. Until it lands,
real mode **fails closed** rather than risk emitting an unverified result. The
sidecar's contract, provisioning checks, and fail-closed plumbing are complete and
tested now; only the audited verifier swap remains.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
from typing import Any, Callable

_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from engine_adapter import run_governed_turn  # noqa: E402  (bridge/ on path above)

_TRUTHY = {"1", "true", "yes", "on"}
# Operator-provisioned state the real supervisor requires (none may come from the desktop).
_PROVISION_ENV = (
    "BRO_KEYDIR",
    "BRO_REGISTRY_ROOT",
    "BRO_BINDING",
    "BRO_REPOSITORY_ROOT",
    "BRO_BUILDER_COMMAND",
)


def _fail(task_id: Any, error: str) -> dict:
    """Fail-closed bridge-result (mirrors engine_adapter._fail): never a result."""
    return {"ok": False, "result": None, "receipt": None, "error": str(error)}


# --------------------------------------------------------------------------- #
# Fake mode — CI smoke only. Mirrors bridge/tests/test_engine_adapter.py seams.
# --------------------------------------------------------------------------- #
class _FakeOutcome:
    """A canned, completed SupervisorResult-shaped object (duck-typed)."""

    def __init__(self, task_id: str, text: str) -> None:
        self.task_id = task_id
        self.status = "completed"
        self.exit_code = 0
        self.evidence = ("evidence:self-test",)
        self.message = text
        self._text = text


def _fake_run_task(request: dict) -> _FakeOutcome:
    return _FakeOutcome(
        str(request.get("task_id", "t-self-test")),
        "SELF-TEST OK — governed round-trip plumbing verified. rationale="
        + str(request.get("rationale", "")),
    )


def _fake_verify(outcome: Any) -> bool:  # noqa: ARG001 — canned pass, self-test only
    return True


def _fake_read(outcome: Any) -> str:
    return getattr(outcome, "_text", "")


# --------------------------------------------------------------------------- #
# Real mode — provisioning + (audit-pending) engine wiring.
# --------------------------------------------------------------------------- #
def _real_callables(
    request: dict,
) -> tuple[Callable[[dict], Any], Callable[[Any], bool], Callable[[Any], str]]:
    """Return the engine-bound callables, or raise RuntimeError with a fail-closed
    reason. Two gates, both fail-closed:

    1. provisioning — every `_PROVISION_ENV` var must be present (operator step);
    2. verify seam — engine-delegated receipt verification is Architect-audited and
       not yet wired, so real mode refuses to emit an unverified result.
    """
    missing = [k for k in _PROVISION_ENV if not os.environ.get(k, "").strip()]
    if missing:
        raise RuntimeError(
            "governed engine not provisioned: missing " + ", ".join(missing)
        )
    # Provisioning is present, but trusting a receipt as VERIFIED is the security
    # crux (see module SECURITY note). Refuse rather than guess.
    raise RuntimeError(
        "governed engine real-mode receipt verification is pending Architect audit "
        "(Phase 1 slice 2 security seam); refusing to emit an unverified result"
    )


# --------------------------------------------------------------------------- #
# Entry
# --------------------------------------------------------------------------- #
def run(argv: list[str], stdin, stdout) -> int:
    """Read one task-request from stdin, write one bridge-result to stdout.

    Always exits 0 and always writes a schema-shaped bridge-result — the verdict
    travels in the payload (`ok`), never in the exit status. Fail-closed on every
    error path.
    """
    task_id: Any = None
    try:
        raw = stdin.read()
        request = json.loads(raw) if raw and raw.strip() else {}
        if not isinstance(request, dict):
            raise ValueError("task-request must be a JSON object")
        task_id = request.get("task_id")
    except Exception as exc:  # noqa: BLE001 — any parse failure is fail-closed
        json.dump(_fail(task_id, f"invalid task-request on stdin: {exc}"), stdout)
        return 0

    fake = ("--self-test" in argv) or (
        os.environ.get("BRIDGE_SIDECAR_FAKE", "").strip().lower() in _TRUTHY
    )
    try:
        if fake:
            result = run_governed_turn(
                request,
                run_task=_fake_run_task,
                verify_receipt=_fake_verify,
                read_result=_fake_read,
            )
        else:
            run_task, verify_receipt, read_result = _real_callables(request)
            result = run_governed_turn(
                request,
                run_task=run_task,
                verify_receipt=verify_receipt,
                read_result=read_result,
            )
    except Exception as exc:  # noqa: BLE001 — fail closed, never leak a partial result
        result = _fail(task_id, exc)

    json.dump(result, stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:], sys.stdin, sys.stdout))
