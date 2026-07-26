"""Wave 3b-1 — the isolated receipt-signer SERVICE (design §1.1; audit P0-1).

Runs as its OWN long-lived process under a dedicated OS principal. It binds an
ACL-controlled Unix socket and admits ONLY the supervisor's UID(s) via `SO_PEERCRED`
(`brops_socket`), then for each connection reads one `brops.sign-request.v1` frame,
signs (reusing the signer core), and returns one `brops.sign-result.v1` frame. The
sidecar NEVER connects here — only the supervisor. All config comes from the signer's own
environment; the receipt-signing key lives in the signer principal's own store,
unreachable by the sidecar.

Env:
  BROPS_SIGNER_SOCKET               — the Unix socket path to bind (in a 0700 dir).
  BROPS_ALLOWED_PEER_UIDS           — comma-separated UIDs allowed to connect (the
                                      supervisor principal). Empty ⇒ deny all (fail-closed).
  + the signer component env (BROPS_EVIDENCE_STORE_DIR, BROPS_RECEIPT_SIGNER_KEYDIR,
    BROPS_SUPERVISOR_ATTESTATION_PUBKEY / _KEY_ID, BROPS_ALLOWED_* / BROPS_EXPECTED_*).
"""

from __future__ import annotations

import os
import time
from typing import Any

import brops_socket
import brops_receipt_signer as signer
import brops_governed_signer as governed_signer


def _allowed_peer_uids(env=None) -> "frozenset[int]":
    e = os.environ if env is None else env
    raw = e.get("BROPS_ALLOWED_PEER_UIDS", "")
    return frozenset(int(x.strip()) for x in raw.split(",") if x.strip())


def run(env=None, *, max_requests: int | None = None, ready=None) -> int:
    e = os.environ if env is None else env
    legacy_components = signer.load_components(e)
    governed_components = None
    if e.get("BROPS_GOVERNED_RECORD_DIR"):
        governed_components = governed_signer.load_governed_signer_components(e)
    socket_path = e["BROPS_SIGNER_SOCKET"]
    allowed = _allowed_peer_uids(e)

    def handle(frame: dict[str, Any]) -> dict[str, Any]:
        # Protocol-disjoint dispatch: the frozen v1 handler never accepts governed-v1B
        # and the governed handler never accepts the frozen family.
        now_ms = int(time.time() * 1000)
        if frame.get("protocol") == governed_signer.PROTOCOL:
            if governed_components is None:
                return {"protocol": governed_signer.RESULT_PROTOCOL, "status": "refused", "receipt_id": None, "reason": "malformed"}
            return governed_signer.sign_governed(frame, governed_components, now_ms)
        return signer.handle_sign_request(frame, legacy_components, now_ms)

    brops_socket.serve_forever(
        socket_path, handle, allowed_peer_uids=allowed, ready=ready, max_requests=max_requests
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
