"""Wave 3b-1B evidence-recorder SERVICE (§2.3 / §8).

Runs as its OWN long-lived process under the dedicated `brops-recorder` OS principal. It binds an
ACL-controlled Unix socket and admits ONLY the supervisor's UID(s) via `SO_PEERCRED`, then for each
connection reads one `brops.governed-record-request.v1` frame, writes the recorder-namespace
artifacts + signed evidence chain (reusing the recorder core), and returns one
`brops.governed-record-result.v1` frame. Only this principal writes `store/rec/` and holds the
evidence-recorder key; the supervisor connects but cannot itself write `store/rec/`.

Env:
  BROPS_RECORDER_SOCKET             — the Unix socket path to bind (in a 0700 dir).
  BROPS_RECORDER_ALLOWED_PEER_UIDS  — comma-separated UIDs allowed to connect (the supervisor
                                      principal). Empty ⇒ deny all (fail-closed).
  BROPS_EVIDENCE_STORE_DIR          — the store root (this service writes only its `rec/` subtree).
  BROPS_EVIDENCE_RECORDER_KEYDIR    — dir holding brops-governed-evidence-recorder.json (0700).
"""

from __future__ import annotations

import os
from typing import Any

import brops_socket
import brops_governed_recorder as recorder


def _allowed_peer_uids(env=None) -> "frozenset[int]":
    e = os.environ if env is None else env
    raw = e.get("BROPS_RECORDER_ALLOWED_PEER_UIDS", "")
    return frozenset(int(x.strip()) for x in raw.split(",") if x.strip())


def run(env=None, *, max_requests: int | None = None, ready=None) -> int:
    e = os.environ if env is None else env
    components = recorder.load_recorder_components(e)
    socket_path = e["BROPS_RECORDER_SOCKET"]
    allowed = _allowed_peer_uids(e)

    def handle(frame: dict[str, Any]) -> dict[str, Any]:
        if frame.get("protocol") == recorder.PROTOCOL:
            return recorder.record_governed_turn(frame, components)
        return {"protocol": recorder.RESULT_PROTOCOL, "status": "refused", "reason": "malformed"}

    brops_socket.serve_forever(
        socket_path, handle, allowed_peer_uids=allowed, ready=ready, max_requests=max_requests
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
