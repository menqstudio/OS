"""Wave 3b-1 — the authoritative live RunStateProvider (design §1.3; audit P0-3).

The supervisor must build receipt evidence ONLY from a run it can independently prove
was leased, completed, contained, and policy-conformant — not from an injected/asserted
state. This provider reads the supervisor's own protected per-attempt run record and
**re-validates the SIGNED artifacts inside it against the trusted-key registry** before it
will yield a `RunState`:

  * the **execution lease** — `verify_artifact(..., "execution-lease")` (authentic, signed
    by the issuer authority) + `validate_execution_lease` (bound to this task/agent/session,
    right capabilities, unexpired);
  * the **passing execution receipt** — `verify_passing_receipt` (signed by the
    evidence-recorder authority over the candidate head/tree, `exit_code == 0`);
  * the **evidence-chain head + chain** — `load_head` + `validate_chain` (the signed head
    reproduces the linked, verified event chain);
  * **containment + terminal status** — the record must assert `decision == completed` and
    `contained is True`.

Any failure ⇒ fail-closed (raise `RunStateValidationError`); a missing record ⇒ `None`.
Only when EVERY check passes does it construct the `RunState` from the record's
authoritative fields, so `produce_sign_request` attests real, proven runs only.
"""

from __future__ import annotations

import base64
import json
import pathlib
from typing import Any

from bro_evidence import load_head, validate_chain
from bro_execution_lease import validate_execution_lease
from bro_receipt import verify_passing_receipt
from bro_signature import verify_artifact
from brops_supervisor_attest import RunState


class RunStateValidationError(Exception):
    """A found run record whose authoritative artifacts did not validate — fail-closed."""


# The authoritative fields the record must carry for the RunState (the supervisor's own
# observed run I/O + identities + timestamps).
_RUNSTATE_STR_FIELDS = (
    "lease_id", "request_nonce", "receipt_id", "workspace_id", "install_id",
    "supervisor_id", "executor_id", "builder_id", "policy_id", "policy_version",
    "requested_at", "completed_at", "system", "output", "generation_config",
)


class LiveRunStateProvider:
    """Reads + validates the supervisor's protected per-attempt run records.

    `state_dir` holds one JSON record per attempt named `<run_id>__<attempt_id>.json`.
    `trusted_keys` is the loaded signed-manifest registry (`load_trusted_keys`).
    `evidence_store` is the directory of signed evidence events/heads.
    `now_epoch` is the current time in EPOCH SECONDS for the engine validity windows.
    """

    def __init__(
        self,
        *,
        state_dir: pathlib.Path,
        trusted_keys: dict,
        evidence_store: pathlib.Path,
        now_epoch: int,
        required_capabilities: tuple[str, ...],
    ) -> None:
        self.state_dir = pathlib.Path(state_dir)
        self.trusted_keys = trusted_keys
        self.evidence_store = pathlib.Path(evidence_store)
        self.now_epoch = now_epoch
        self.required_capabilities = required_capabilities

    def _record_path(self, run_id: str, execution_attempt_id: str) -> pathlib.Path:
        safe = f"{run_id}__{execution_attempt_id}.json"
        return self.state_dir / safe

    def terminal_run_state(self, run_id: str, execution_attempt_id: str) -> RunState | None:
        path = self._record_path(run_id, execution_attempt_id)
        if not path.is_file():
            return None  # no such attempt — not terminal (produce_sign_request fails closed)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RunStateValidationError(f"unreadable run record: {exc}")
        if not isinstance(record, dict):
            raise RunStateValidationError("run record is not an object")

        if record.get("run_id") != run_id or record.get("execution_attempt_id") != execution_attempt_id:
            raise RunStateValidationError("run record identity does not match the requested handle")

        # Terminal + contained (the supervisor's own verdict, re-checked below by artifacts).
        if record.get("decision") != "completed":
            raise RunStateValidationError(f"run is not completed: {record.get('decision')}")
        if record.get("contained") is not True:
            raise RunStateValidationError("run is not marked contained")

        task = record.get("task")
        if not isinstance(task, dict) or not task.get("task_id"):
            raise RunStateValidationError("run record has no task")
        task_id = task["task_id"]

        # 1. Execution lease — authentic + bound + unexpired.
        lease_doc = record.get("lease_document")
        if not isinstance(lease_doc, dict):
            raise RunStateValidationError("run record has no lease document")
        try:
            lease_payload = verify_artifact(
                lease_doc, "execution-lease", self.trusted_keys, now=self.now_epoch
            )
            validate_execution_lease(
                lease_payload,
                task=task,
                agent_id=record.get("agent_id", ""),
                session_id=record.get("session_id", ""),
                required_capabilities=self.required_capabilities,
                control_plane_digest=record.get("control_plane_digest"),
                workspace_id=record.get("workspace_id"),
                now=self.now_epoch,
            )
        except Exception as exc:  # noqa: BLE001 — any lease failure is fail-closed
            raise RunStateValidationError(f"execution lease did not validate: {exc}")

        # 2. Passing execution receipt — signed, exit 0, over the candidate head/tree.
        receipt_doc = record.get("receipt_document")
        if not isinstance(receipt_doc, dict):
            raise RunStateValidationError("run record has no receipt document")
        try:
            verify_passing_receipt(
                receipt_doc,
                self.trusted_keys,
                task_id=task_id,
                candidate_head=record.get("candidate_head", ""),
                candidate_tree=record.get("candidate_tree", ""),
                now=self.now_epoch,
            )
        except Exception as exc:  # noqa: BLE001
            raise RunStateValidationError(f"passing receipt did not verify: {exc}")

        # 3. Evidence-chain head + chain.
        event_ids = record.get("evidence_event_ids")
        if not isinstance(event_ids, list) or not event_ids:
            raise RunStateValidationError("run record has no evidence event ids")
        try:
            load_head(self.evidence_store, task_id, self.trusted_keys, now=self.now_epoch)
            validate_chain(
                task_id, event_ids, self.trusted_keys, store=self.evidence_store, now=self.now_epoch
            )
        except Exception as exc:  # noqa: BLE001
            raise RunStateValidationError(f"evidence chain did not validate: {exc}")

        # Every authoritative artifact validated — build the RunState from the record.
        for field in _RUNSTATE_STR_FIELDS:
            if not isinstance(record.get(field), str) or record[field] == "":
                raise RunStateValidationError(f"run record field `{field}` is missing")
        history = record.get("history")
        if not isinstance(history, list):
            raise RunStateValidationError("run record `history` must be a list")
        containment_evidence = record.get("containment_evidence")
        if not isinstance(containment_evidence, dict):
            raise RunStateValidationError("run record `containment_evidence` must be an object")
        try:
            policy_bundle = base64.urlsafe_b64decode(
                record["policy_bundle_b64"] + "=" * (-len(record["policy_bundle_b64"]) % 4)
            )
        except Exception as exc:  # noqa: BLE001
            raise RunStateValidationError(f"policy_bundle_b64 not decodable: {exc}")

        return RunState(
            run_id=run_id,
            execution_attempt_id=execution_attempt_id,
            lease_id=record["lease_id"],
            request_nonce=record["request_nonce"],
            receipt_id=record["receipt_id"],
            decision="completed",
            workspace_id=record["workspace_id"],
            install_id=record["install_id"],
            supervisor_id=record["supervisor_id"],
            executor_id=record["executor_id"],
            builder_id=record["builder_id"],
            policy_id=record["policy_id"],
            policy_version=record["policy_version"],
            requested_at=record["requested_at"],
            completed_at=record["completed_at"],
            system=record["system"],
            history=history,
            output=record["output"],
            generation_config=record["generation_config"],
            containment_evidence=containment_evidence,
            policy_bundle=policy_bundle,
        )
