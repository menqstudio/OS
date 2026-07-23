"""Wave 3b-1 — the supervisor evidence/attestation SERVICE (design §1.1, §1.3, §4.4;
audit P0-1, P0-2, P0-3).

Runs as its OWN process under a dedicated principal. It is the ONLY peer the signer
service admits, and it is the sidecar's only reachable governance endpoint. Its socket
accepts ONLY `brops.evidence-request.v1` = `{run_id, execution_attempt_id}` — never a
caller-supplied evidence object (P0-2). For each request it:

  1. builds an AUTHORITATIVE `RunState` from its own protected state via
     `LiveRunStateProvider` (validates the signed lease / passing receipt / evidence
     chain / containment — P0-3), then
  2. `produce_sign_request` (publishes artifacts to the store + attests with the
     supervisor-attestation key it alone holds), then
  3. connects to the SIGNER service over the ACL'd socket and relays the request, and
  4. returns the signer's `brops.sign-result.v1` to the sidecar.

Any failure is a fail-closed structured refusal — never a partial/unsigned result.

Env:
  BROPS_SUPERVISOR_SOCKET             — Unix socket to bind (0700 dir).
  BROPS_SUPERVISOR_ALLOWED_PEER_UIDS  — UIDs allowed to connect (the sidecar principal).
  BROPS_SIGNER_SOCKET                 — the signer service socket to relay to.
  BROPS_SUPERVISOR_ATTESTATION_KEYDIR — the supervisor-attestation key store.
  BROPS_EVIDENCE_STORE_DIR            — the content-addressed store.
  BROPS_RUNSTATE_DIR                  — protected per-attempt run records.
  BROPS_REGISTRY_ROOT                 — trusted-key registry root.
  BROPS_REQUIRED_CAPABILITIES         — comma-separated lease capabilities required.
"""

from __future__ import annotations

import json
import os
import pathlib
import time
from typing import Any

import brops_protocol
import brops_socket
from bro_signature import load_trusted_keys
from brops_canonical import b64url, containment_evidence_bytes
from brops_evidence_store import EvidenceStore
from brops_live_runstate import LiveRunStateProvider
from brops_supervisor_attest import load_attestation_key, produce_sign_request

EVIDENCE_REQUEST_PROTOCOL = "brops.evidence-request.v1"
SIGN_RESULT_PROTOCOL = "brops.sign-result.v1"
GOVERNED_RESULT_PROTOCOL = "brops.governed-result.v1"


_CONTRACTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "contracts"


def _sign_result_schema() -> dict:
    return json.loads((_CONTRACTS_DIR / "brops-sign-result.v1.schema.json").read_text("utf-8"))


def _refused(reason: str) -> dict[str, Any]:
    return {"protocol": GOVERNED_RESULT_PROTOCOL, "status": "refused", "reason": reason}


class SupervisorService:
    def __init__(self, env=None) -> None:
        e = os.environ if env is None else env
        self.socket_path = e["BROPS_SUPERVISOR_SOCKET"]
        self.signer_socket = e["BROPS_SIGNER_SOCKET"]
        self.state_dir = e["BROPS_RUNSTATE_DIR"]
        self.evidence_store = EvidenceStore(e["BROPS_EVIDENCE_STORE_DIR"])
        self.trusted_keys = load_trusted_keys(pathlib.Path(e["BROPS_REGISTRY_ROOT"]))
        self.attestation_key = load_attestation_key(e["BROPS_SUPERVISOR_ATTESTATION_KEYDIR"])
        self.required_capabilities = tuple(
            x.strip() for x in e.get("BROPS_REQUIRED_CAPABILITIES", "EXECUTE_CODE").split(",") if x.strip()
        )
        self.allowed_peer_uids = frozenset(
            int(x.strip()) for x in e.get("BROPS_SUPERVISOR_ALLOWED_PEER_UIDS", "").split(",") if x.strip()
        )

    def handle(self, frame: dict[str, Any]) -> dict[str, Any]:
        # Accept ONLY the {run_id, execution_attempt_id} handle — never evidence (P0-2).
        if (
            not isinstance(frame, dict)
            or frame.get("protocol") != EVIDENCE_REQUEST_PROTOCOL
            or set(frame) != {"protocol", "run_id", "execution_attempt_id"}
            or not isinstance(frame.get("run_id"), str)
            or not isinstance(frame.get("execution_attempt_id"), str)
        ):
            return _refused("malformed")

        provider = LiveRunStateProvider(
            state_dir=pathlib.Path(self.state_dir),
            trusted_keys=self.trusted_keys,
            evidence_store=self.evidence_store.root,
            now_epoch=int(time.time()),
            required_capabilities=self.required_capabilities,
        )
        # Build the AUTHORITATIVE run state (validates signed lease/receipt/evidence/
        # containment) and attest, both from the supervisor's own state (P0-2, P0-3).
        try:
            run_state = provider.terminal_run_state(frame["run_id"], frame["execution_attempt_id"])
            if run_state is None:
                return _refused("run_binding_invalid")
            request = produce_sign_request(
                frame["run_id"],
                frame["execution_attempt_id"],
                run_state_provider=provider,
                store=self.evidence_store,
                attestation_key=self.attestation_key,
            )
        except Exception:  # noqa: BLE001 — no authoritative state ⇒ fail-closed refusal
            return _refused("run_binding_invalid")

        # Relay to the isolated SIGNER service over the ACL'd socket (the sidecar never
        # reaches the signer — only the supervisor does).
        try:
            sign_result = brops_socket.request(self.signer_socket, request)
        except Exception:  # noqa: BLE001 — signer unreachable ⇒ fail-closed
            return _refused("malformed")
        # Strictly validate the signer's response against its contract before trusting any
        # field (audit P1) — a malformed/oversize response is fail-closed.
        try:
            brops_protocol.validate(sign_result, _sign_result_schema())
        except brops_protocol.ProtocolError:
            return _refused("malformed")
        if sign_result.get("status") != "signed":
            return {"protocol": GOVERNED_RESULT_PROTOCOL, "status": "refused",
                    "reason": sign_result.get("reason", "malformed")}

        # A governed-result the sidecar relays to the desktop: the run output + the signed
        # receipt wire + the forensic-attestation record + containment bytes.
        return {
            "protocol": GOVERNED_RESULT_PROTOCOL,
            "status": "signed",
            "output": run_state.output,
            "receipt": {
                "envelope_jcs_b64": sign_result["envelope_jcs_b64"],
                "signature_b64": sign_result["signature_b64"],
                "containment_evidence_b64": b64url(containment_evidence_bytes(run_state.containment_evidence)),
                "attestation_evidence_jcs_b64": sign_result["attestation_evidence_jcs_b64"],
                "attestation_signature_b64": sign_result["attestation_signature_b64"],
                "supervisor_attestation_key_id": sign_result["supervisor_attestation_key_id"],
                "run_id": sign_result["run_id"],
                "execution_attempt_id": sign_result["execution_attempt_id"],
                "lease_id": sign_result["lease_id"],
            },
        }

    def run(self, *, max_requests: int | None = None, ready=None) -> int:
        brops_socket.serve_forever(
            self.socket_path,
            self.handle,
            allowed_peer_uids=self.allowed_peer_uids,
            ready=ready,
            max_requests=max_requests,
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(SupervisorService().run())
