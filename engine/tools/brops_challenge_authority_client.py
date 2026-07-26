"""Bounded desktop client for the dedicated challenge authority.

Reads one exact authority request from stdin and writes its exact reply. Explicit
`status=refused` replies are terminal and are never retried. Only ambiguous transport
failures (connect/timeout/lost reply) use the fixed rev-26 3-attempt budget.
"""
from __future__ import annotations

import json
import os
import sys
import time

import brops_socket
from bro_signature import canonical_bytes
from brops_governed_common import (
    AUTHORITY_ATTEMPT_TIMEOUT_MS,
    AUTHORITY_CHANNEL_FRAME_BYTES,
    AUTHORITY_REQUEST_FRAME_BYTES,
    AUTHORITY_RETRY_BACKOFF_MS,
    MAX_AUTHORITY_ATTEMPTS,
    GovernedProtocolError,
    require_exact_keys,
)
from brops_challenge_authority import (
    CREATE_PROTOCOL,
    CREATE_RESULT_PROTOCOL,
    ISSUE_PROTOCOL,
    ISSUE_RESULT_PROTOCOL,
)


def _validate_reply(request_protocol: str, reply: object) -> dict:
    if not isinstance(reply, dict):
        raise GovernedProtocolError("authority reply is not an object")
    if len(canonical_bytes(reply)) > AUTHORITY_CHANNEL_FRAME_BYTES:
        raise GovernedProtocolError("authority reply exceeds frame cap")
    expected = CREATE_RESULT_PROTOCOL if request_protocol == CREATE_PROTOCOL else ISSUE_RESULT_PROTOCOL
    if reply.get("protocol") != expected or reply.get("status") not in {"created", "issued", "refused"}:
        raise GovernedProtocolError("authority reply has wrong protocol/status")
    if reply["status"] == "created":
        require_exact_keys(reply, {"protocol", "status", "pending_challenge_id", "pending_expires_at_ms"}, "create reply")
    elif reply["status"] == "issued":
        require_exact_keys(reply, {"protocol", "status", "challenge_document_b64"}, "issue reply")
    else:
        require_exact_keys(reply, {"protocol", "status", "reason"}, "refused reply")
    return reply


def run(stdin, stdout, stderr) -> int:
    try:
        request = json.loads(stdin.read())
        if not isinstance(request, dict) or request.get("protocol") not in {CREATE_PROTOCOL, ISSUE_PROTOCOL}:
            raise GovernedProtocolError("unsupported authority request")
        if len(canonical_bytes(request)) > AUTHORITY_REQUEST_FRAME_BYTES:
            raise GovernedProtocolError("authority request exceeds frame cap")
    except Exception as exc:  # noqa: BLE001
        stderr.write(f"malformed authority request: {exc}\n")
        return 2

    socket_path = os.environ.get("BROPS_CHALLENGE_SOCKET", "").strip()
    if not socket_path:
        stderr.write("BROPS_CHALLENGE_SOCKET is not configured\n")
        return 3

    failures: list[str] = []
    for attempt in range(MAX_AUTHORITY_ATTEMPTS):
        try:
            reply = _validate_reply(
                request["protocol"],
                brops_socket.request(
                    socket_path,
                    request,
                    timeout=AUTHORITY_ATTEMPT_TIMEOUT_MS / 1000.0,
                ),
            )
            json.dump(reply, stdout, separators=(",", ":"), ensure_ascii=False)
            return 0
        except Exception as exc:  # noqa: BLE001 — only transport/ambiguous reply retries
            failures.append(str(exc))
            if attempt + 1 < MAX_AUTHORITY_ATTEMPTS:
                time.sleep(AUTHORITY_RETRY_BACKOFF_MS / 1000.0)
    stderr.write("authority transport exhausted: " + " | ".join(failures) + "\n")
    return 4


if __name__ == "__main__":
    raise SystemExit(run(sys.stdin, sys.stdout, sys.stderr))
