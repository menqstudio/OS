"""One-shot sidecar orchestration for Wave 3b-1B governed protocols.

The sidecar is transport-only.  It stages exact canonical artifacts, relays the
supervisor's signed/refused verdict, and never pulls output during submit.  Internal
pre-result refusals are returned only as the bounded signature-free diagnostic protocol.
"""
from __future__ import annotations

import pathlib
import sys
from typing import Any, Mapping

_HERE = pathlib.Path(__file__).resolve().parent
_ENGINE = _HERE.parent / "engine"
for sub in ("runtime", "tools"):
    p = str(_ENGINE / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import brops_socket  # noqa: E402
from bro_signature import canonical_bytes  # noqa: E402
from brops_governed_common import (  # noqa: E402
    MAX_STAGING_CHUNKS, STAGING_CHUNK_BYTES, GovernedProtocolError,
    b64url_decode, b64url_encode, bounded_diagnostic, transport_failure,
    governed_generation_config_bytes, history_bytes, require_exact_keys,
    require_id, sha256_hex, system_bytes,
)
from brops_governed_supervisor import (  # noqa: E402
    EVIDENCE_REQUEST, OPEN, OUTPUT_READ, STAGING_CHUNK, STAGING_FINAL,
    STAGING_OPEN, TURN_RESULT,
)

SUBMIT = "bridge.governed-turn-submit.v1"
RESULT = "bridge.governed-turn-result.v1"
OUTPUT_READ_BRIDGE = "bridge.governed-turn-output-read.v1"
OUTPUT_READ_RESULT_BRIDGE = "bridge.governed-turn-output-read-result.v1"
DIAGNOSTIC = "bridge.governed-turn-diagnostic.v1"
# §4.10(d) pre-acceptance evidence-request reply (disjoint from GOVERNED_REFUSAL_REASONS).
EVIDENCE_REQUEST_RESULT = "brops.governed-evidence-request-result.v1"

_SUBMIT_KEYS = {"protocol", "task_id", "challenge_doc_b64", "system", "history", "generation_config"}
_OUTPUT_KEYS = {"protocol", "output_stream_id", "receipt_id", "execution_attempt_id", "seq"}


def _call(socket_path: str, frame: dict[str, Any]) -> dict[str, Any]:
    return brops_socket.request(socket_path, frame, timeout=125.0)


def _challenge(request: Mapping[str, Any]) -> tuple[bytes, dict[str, Any]]:
    raw = b64url_decode(request["challenge_doc_b64"], max_bytes=4096)
    try:
        doc = __import__("json").loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise GovernedProtocolError("malformed challenge") from exc
    if not isinstance(doc, dict) or set(doc) != {"payload", "sig"} or canonical_bytes(doc) != raw:
        raise GovernedProtocolError("noncanonical challenge")
    payload = doc["payload"]
    if not isinstance(payload, dict) or payload.get("protocol") != "brops.governed-turn-challenge.v1":
        raise GovernedProtocolError("wrong challenge protocol")
    return raw, payload


def _internal(reply: Mapping[str, Any], stage: str) -> dict[str, str] | None:
    """A well-formed internal `refused` reply from a supervisor hop → ONE §4.10(h)
    diagnostic tagged with that hop's concrete stage.  Non-refused replies return None."""
    if reply.get("status") != "refused":
        return None
    return bounded_diagnostic(stage, str(reply.get("reason", "malformed")))


def _stage(socket_path: str, *, install_id: str, nonce: str, challenge_handle: str,
           artifact: str, data: bytes, expected_hash: str) -> dict[str, str] | None:
    if sha256_hex(data) != expected_hash:
        # Local pre-flight inconsistency (the sidecar's own bytes do not hash to the
        # challenge-declared digest) — not a supervisor refusal → transport failure.
        return transport_failure(f"artifact_digest_mismatch:{artifact}")
    opened = _call(socket_path, {
        "protocol": STAGING_OPEN, "install_id": install_id,
        "challenge_handle": challenge_handle, "request_nonce": nonce,
        "artifact": artifact, "declared_len": len(data), "declared_sha256": expected_hash,
    })
    diag = _internal(opened, "staging-open")
    if diag:
        return diag
    session = opened.get("staging_session_id")
    next_seq = opened.get("next_seq")
    if not isinstance(session, str) or not isinstance(next_seq, int):
        return transport_failure("malformed_staging_open_reply")
    chunks = [data[i:i + STAGING_CHUNK_BYTES] for i in range(0, len(data), STAGING_CHUNK_BYTES)]
    if len(chunks) > MAX_STAGING_CHUNKS:
        # Local structural over-limit (would be refused at staging-chunk anyway).
        return transport_failure("too_many_chunks")
    for seq in range(next_seq, len(chunks)):
        ack = _call(socket_path, {
            "protocol": STAGING_CHUNK, "staging_session_id": session,
            "seq": seq, "bytes_b64": b64url_encode(chunks[seq]),
        })
        diag = _internal(ack, "staging-chunk")
        if diag:
            return diag
        if ack.get("status") != "ack" or ack.get("next_seq") != seq + 1:
            return transport_failure("malformed_staging_ack")
    final = _call(socket_path, {
        "protocol": STAGING_FINAL, "staging_session_id": session, "seq": len(chunks),
    })
    diag = _internal(final, "staging-final")
    if diag:
        return diag
    if final.get("status") != "published" or final.get("handle") != expected_hash:
        return transport_failure("malformed_staging_final_reply")
    return None


def submit(request: Mapping[str, Any], supervisor_socket: str) -> dict[str, Any]:
    try:
        require_exact_keys(request, _SUBMIT_KEYS, "governed submit")
        if request["protocol"] != SUBMIT:
            raise GovernedProtocolError("wrong submit protocol")
        task_id = require_id(request["task_id"], "task_id")
        challenge_bytes, challenge = _challenge(request)
        if challenge.get("task_id") != task_id:
            # context_mismatch is a governed-turn-open internal reason (§4.10 routing table).
            return bounded_diagnostic("governed-turn-open", "context_mismatch")
        sb = system_bytes(request["system"])
        hb = history_bytes(request["history"])
        cb = governed_generation_config_bytes(request["generation_config"])
        expected = {
            "system": challenge["system_sha256"],
            "history": challenge["history_sha256"],
            "generation_config": challenge["generation_config_sha256"],
        }
    except (GovernedProtocolError, KeyError, TypeError, ValueError) as exc:
        return transport_failure(f"malformed_submit:{exc}")
    try:
        opened = _call(supervisor_socket, {
            "protocol": OPEN, "install_id": challenge["install_id"],
            "request_nonce": challenge["request_nonce"],
            "challenge_doc_b64": b64url_encode(challenge_bytes),
        })
        diag = _internal(opened, "governed-turn-open")
        if diag:
            return diag
        challenge_handle = opened.get("challenge_handle")
        if not isinstance(challenge_handle, str) or challenge_handle != sha256_hex(challenge_bytes):
            return transport_failure("malformed_turn_open_reply")
        for name, data in (("system", sb), ("history", hb), ("generation_config", cb)):
            diag = _stage(
                supervisor_socket, install_id=challenge["install_id"],
                nonce=challenge["request_nonce"], challenge_handle=challenge_handle,
                artifact=name, data=data, expected_hash=expected[name],
            )
            if diag:
                return diag
        terminal = _call(supervisor_socket, {
            "protocol": EVIDENCE_REQUEST, "install_id": challenge["install_id"],
            "challenge_handle": challenge_handle, "request_nonce": challenge["request_nonce"],
        })
    except Exception as exc:  # noqa: BLE001 — transport failures are diagnostic only
        return transport_failure(str(exc))
    # §4.10(d) tagged union: a PRE-ACCEPTANCE evidence-request gate failure is an internal
    # refusal (disjoint from GOVERNED_REFUSAL_REASONS) → ONE diagnostic, stage evidence-request.
    if terminal.get("protocol") == EVIDENCE_REQUEST_RESULT:
        if terminal.get("status") == "refused":
            return bounded_diagnostic("evidence-request", str(terminal.get("reason", "malformed")))
        return transport_failure("malformed_evidence_request_reply")
    if terminal.get("protocol") != TURN_RESULT:
        return transport_failure("malformed_terminal_reply")
    if terminal.get("status") == "refused":
        return {
            "protocol": RESULT, "ok": False, "output_stream_id": None, "receipt": None,
            "error": {"reason": terminal.get("reason", "malformed"), "receipt_id": terminal.get("receipt_id")},
        }
    if terminal.get("status") != "signed":
        return transport_failure("malformed_terminal_reply")
    receipt = {
        "task_id": task_id, "status": "completed", "exit_code": 0,
        "key_id": terminal["key_id"], "receipt_id": terminal["receipt_id"],
        "evidence": [f"evidence:record:{terminal.get('run_id','')}", f"evidence:receipt:{terminal.get('receipt_id','')}"] ,
        "envelope_jcs_b64": terminal["envelope_jcs_b64"], "signature_b64": terminal["signature_b64"],
        "containment_evidence_b64": terminal.get("containment_evidence_b64"),
        "attestation_evidence_jcs_b64": terminal["attestation_evidence_jcs_b64"],
        "attestation_signature_b64": terminal["attestation_signature_b64"],
        "supervisor_attestation_key_id": terminal["supervisor_attestation_key_id"],
        "run_id": terminal["run_id"], "execution_attempt_id": terminal["execution_attempt_id"],
        "lease_id": terminal["lease_id"], "challenge_accepted_at_ms": terminal["challenge_accepted_at_ms"],
        "challenge_handle": terminal["challenge_handle"], "challenge_key_id": terminal["challenge_key_id"],
        "challenge_registry_handle": terminal["challenge_registry_handle"],
        "challenge_registry_hash": terminal["challenge_registry_hash"],
        "challenge_registry_epoch": terminal["challenge_registry_epoch"],
        "challenge_registry_root_key_id": terminal["challenge_registry_root_key_id"],
        "lease_handle": terminal["lease_handle"], "execution_receipt_handle": terminal["execution_receipt_handle"],
        "output_sha256": terminal["output_sha256"], "output_bytes": terminal["output_bytes"],
        "evidence_event_count": terminal["evidence_event_count"],
        "evidence_last_sequence": terminal["evidence_last_sequence"],
        "evidence_head_sequence": terminal["evidence_head_sequence"],
        "evidence_final_event_hash": terminal["evidence_final_event_hash"],
    }
    return {
        "protocol": RESULT, "ok": True, "output_stream_id": terminal["output_stream_id"],
        "receipt": receipt, "error": None,
    }


def output_read(request: Mapping[str, Any], supervisor_socket: str) -> dict[str, Any]:
    try:
        require_exact_keys(request, _OUTPUT_KEYS, "bridge output read")
        if request["protocol"] != OUTPUT_READ_BRIDGE:
            raise GovernedProtocolError("wrong output protocol")
        forwarded = dict(request)
        forwarded["protocol"] = OUTPUT_READ
        reply = _call(supervisor_socket, forwarded)
    except (GovernedProtocolError, KeyError, TypeError, ValueError) as exc:
        return transport_failure(f"malformed_output_read:{exc}")
    except Exception as exc:  # noqa: BLE001
        return transport_failure(str(exc))
    if reply.get("protocol") != "brops.governed-turn-output-read-result.v1":
        return transport_failure("malformed_output_read_reply")
    out = dict(reply)
    out["protocol"] = OUTPUT_READ_RESULT_BRIDGE
    return out
