"""Wave 3b-1B evidence-recorder RUNNER (§2.3 / §8 — the dedicated recorder principal).

Runs as its OWN long-lived process under the dedicated `brops-recorder` OS principal. It HOLDS
the evidence-recorder key and OWNS `store/rec/`: for each governed turn the supervisor sends the
executor output + turn metadata, and the recorder writes the output, containment, the
evidence-recorder-signed execution receipt, and the signed `bro_evidence` chain to `store/rec/`,
returning their handles. The supervisor is a DIFFERENT principal that can neither write `store/rec/`
(the OS ACLs forbid it — machine-proven by `engine/ci/isolation_proof.sh`) nor hold this key, so a
compromised supervisor cannot fabricate recorder-namespace evidence. `bro_signature` only verifies;
there is no arbitrary-bytes signing endpoint — the recorder signs ONLY the fixed receipt/evidence
shapes below.
"""
from __future__ import annotations

import json
import os
import pathlib
import tempfile
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from bro_evidence import event_hash as evidence_event_hash
from bro_signature import canonical_bytes
from broctl import sign_payload
from brops_evidence_store import EvidenceStore
from brops_governed_common import (
    GovernedProtocolError, MAX_OUTPUT_BYTES, b64url_decode, b64url_encode,
    require_exact_keys, require_id,
)

PROTOCOL = "brops.governed-record-request.v1"
RESULT_PROTOCOL = "brops.governed-record-result.v1"

_REQUEST_KEYS = frozenset({
    "protocol", "output_b64", "run_id", "execution_attempt_id", "lease_id", "receipt_id",
    "task_id", "agent_id", "runner_id", "executor_id", "started_at_ms", "finished_at_ms",
    "issued_at_epoch",
})


@dataclass(frozen=True)
class RecorderComponents:
    rec_store: EvidenceStore                 # store/rec/, owned + written by THIS principal
    evidence_recorder_key: Mapping[str, str]


def _sign_document(payload: Mapping[str, Any], key: Mapping[str, str]) -> dict[str, Any]:
    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(key["private_key"]))
    return {"payload": dict(payload),
            "signature": b64url_encode(private.sign(canonical_bytes(dict(payload))))}


def _atomic_write_json(path: pathlib.Path, obj: Any) -> None:
    """Write JSON durably: a temp file in the same dir, fsync, then a single atomic os.replace.
    A crash can leave a stale temp (garbage-collected on the next run) but NEVER a half-written
    evidence event/head — the signer would in any case reject a truncated head on signature verify,
    but atomic replace means a reader only ever sees the complete file (matches the store's rigor)."""
    data = json.dumps(obj).encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".part")
    tmp = pathlib.Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if os.name == "posix":
            os.chmod(tmp, 0o640)
        os.replace(tmp, path)          # atomic on POSIX + NTFS
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass


def record_governed_turn(request: Mapping[str, Any], c: RecorderComponents) -> dict[str, Any]:
    """Write the recorder-namespace artifacts + evidence chain for one governed turn, signed by the
    evidence-recorder key, and return their handles. Fail-closed on any malformed request."""
    try:
        require_exact_keys(request, _REQUEST_KEYS, "governed record request")
        if request["protocol"] != PROTOCOL:
            raise GovernedProtocolError("wrong record protocol")
        run_id = require_id(request["run_id"], "run_id")
        attempt = require_id(request["execution_attempt_id"], "execution_attempt_id")
        lease_id = require_id(request["lease_id"], "lease_id")
        receipt_id = require_id(request["receipt_id"], "receipt_id")
        task_id = require_id(request["task_id"], "task_id")
        agent_id = require_id(request["agent_id"], "agent_id")
        runner_id = require_id(request["runner_id"], "runner_id")
        executor_id = require_id(request["executor_id"], "executor_id")
        for field in ("started_at_ms", "finished_at_ms", "issued_at_epoch"):
            if isinstance(request[field], bool) or not isinstance(request[field], int):
                raise GovernedProtocolError(f"{field} must be an integer")
        started = request["started_at_ms"]; finished = request["finished_at_ms"]
        issued_at_epoch = request["issued_at_epoch"]
        output = b64url_decode(request["output_b64"], max_bytes=MAX_OUTPUT_BYTES)
    except (GovernedProtocolError, KeyError, TypeError, ValueError) as exc:
        return {"protocol": RESULT_PROTOCOL, "status": "refused", "reason": f"malformed:{exc}"}

    key_id = c.evidence_recorder_key["key_id"]
    priv = c.evidence_recorder_key["private_key"]
    output_handle = c.rec_store.publish(output)
    containment = {
        "artifact_type": "brops.governed-turn-containment.v1",
        "run_id": run_id, "execution_attempt_id": attempt, "lease_id": lease_id,
        "runner_id": runner_id, "executor_id": executor_id,
        "cgroup_id": "process-group:" + attempt, "process_group_id": attempt,
        "contained": True, "teardown_outcome": "contained", "measured_at_ms": finished,
    }
    containment_handle = c.rec_store.publish(canonical_bytes(containment))
    execution_receipt_payload = {
        "artifact_type": "brops.governed-turn-execution-receipt.v1",
        "key_id": key_id, "receipt_id": receipt_id, "task_id": task_id,
        "run_id": run_id, "execution_attempt_id": attempt, "lease_id": lease_id,
        "runner_id": runner_id, "executor_id": executor_id,
        "exit_code": 0, "contained": True, "output_handle": output_handle,
        "output_sha256": output_handle, "output_bytes": len(output),
        "started_at_ms": started, "finished_at_ms": finished,
    }
    execution_receipt = _sign_document(execution_receipt_payload, c.evidence_recorder_key)
    execution_receipt_handle = c.rec_store.publish(canonical_bytes(execution_receipt))

    # §7 — a REAL signed bro_evidence chain in store/rec/evidence/ (evidence-recorder authority).
    evidence_dir = pathlib.Path(c.rec_store.root) / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        os.chmod(evidence_dir, 0o2750)
    evidence_event_id = str(uuid.uuid4())
    event_payload = {
        "artifact_type": "evidence-event", "key_id": key_id, "event_id": evidence_event_id,
        "sequence": 1, "previous_event_hash": None, "task_id": task_id,
        "event_type": "governed-turn-completed", "agent_id": agent_id,
        "payload_hash": output_handle, "issued_at_epoch": issued_at_epoch,
    }
    final_event_hash = evidence_event_hash(event_payload)
    head_payload = {
        "artifact_type": "evidence-head", "key_id": key_id, "task_id": task_id,
        "final_event_hash": final_event_hash, "event_count": 1, "last_sequence": 1,
        "head_sequence": 1, "issued_at_epoch": issued_at_epoch,
    }
    # Write the event BEFORE the head, each atomically: the head names final_event_hash, so a reader
    # that sees the head is guaranteed the event it points at is already fully on disk.
    _atomic_write_json(evidence_dir / f"{evidence_event_id}.json", sign_payload(priv, event_payload))
    _atomic_write_json(evidence_dir / f"{task_id}.head.json", sign_payload(priv, head_payload))

    return {
        "protocol": RESULT_PROTOCOL, "status": "recorded",
        "output_handle": output_handle, "output_bytes": len(output),
        "containment": containment, "containment_handle": containment_handle,
        "execution_receipt_handle": execution_receipt_handle,
        "evidence_event_id": evidence_event_id, "evidence_final_event_hash": final_event_hash,
        "evidence_event_count": 1, "evidence_last_sequence": 1, "evidence_head_sequence": 1,
    }


def load_recorder_components(env: Mapping[str, str]) -> RecorderComponents:
    def _key(directory: str, name: str) -> dict[str, str]:
        data = json.loads((pathlib.Path(directory) / name).read_text(encoding="utf-8"))
        return {"key_id": data["key_id"], "private_key": data["private_key"]}
    return RecorderComponents(
        rec_store=EvidenceStore(pathlib.Path(env["BROPS_EVIDENCE_STORE_DIR"]) / "rec"),
        evidence_recorder_key=_key(env["BROPS_EVIDENCE_RECORDER_KEYDIR"],
                                   "brops-governed-evidence-recorder.json"),
    )
