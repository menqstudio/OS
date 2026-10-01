"""Test helper: an in-memory supervisor ledger, an accepted attempt, and a framed connection.

Three suites each need the supervisor's ledger with one `governed_turn_acceptance` row in it —
`test_governed_output_stream` (a stream's FOREIGN KEY requires one), `test_governed_output_read`
and `test_governed_run_attestation` — and each had its own `ledger()`; two had the same 20-field
`gsl.NewAcceptance(...)` body, differing only in how the default challenge handle was spelled
(one of them from `hash(str)`, which is randomised per process). `FakeConn` was written twice as
well. One copy of each lives here.

Not a test module (no ``test_`` prefix), so unittest discovery ignores it.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3

import governed_supervisor_ledger as gsl

#: The length prefix of one frame, as the supervisor's front door reads it.
LENGTH_PREFIX_BYTES = 4


def ledger() -> sqlite3.Connection:
    """The supervisor ledger, in memory, with the canonical schema applied."""
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    gsl.apply_schema(conn)
    return conn


def accept(conn, attempt="attempt-1", *, install_id="inst-1", nonce="nonce-1",
           receipt_id="rcpt-1", handle=None, now_ms=1_000_000) -> str:
    """Create one acceptance row through the real §5 CAS and return its attempt id.

    Nothing here inserts a bare row: a test that needs an accepted attempt walks
    ``accept_prepare`` to get one. The default challenge handle is derived from the attempt id
    with SHA-256, so it is the same on every run and distinct for distinct attempts (the handle
    is UNIQUE in the ledger).
    """
    gsl.accept_prepare(conn, gsl.NewAcceptance(
        install_id=install_id, request_nonce=nonce,
        challenge_handle=handle or hashlib.sha256(attempt.encode("utf-8")).hexdigest(),
        run_id="run-1", task_id="task-1", workspace_id="ws-1",
        execution_attempt_id=attempt, challenge_accepted_at_ms=now_ms,
        challenge_registry_handle="d" * 64, challenge_registry_hash="e" * 64,
        challenge_registry_epoch=7, challenge_registry_root_key_id="root-1",
        lease_payload_bytes=b"{}", lease_id="lease-1",
        lease_issued_at_ms=now_ms, lease_expires_at_ms=now_ms + 210_000,
        receipt_id=receipt_id, supervisor_id="sup-1", requested_at_ms=now_ms - 10,
        request_sha256="f" * 64, system_handle="1" * 64, history_handle="2" * 64,
        generation_config_handle="3" * 64,
    ), now_ms)
    return attempt


class FakeConn:
    """A peer connection: `inbound` is what the peer sent, `out` is what was written back."""

    def __init__(self, peer_uid, inbound: bytes = b""):
        self.peer_uid = peer_uid
        self._in = inbound
        self.out = b""
        self.closed = False

    def recv_exactly(self, n: int) -> bytes:
        chunk = self._in[:n]
        self._in = self._in[n:]
        return chunk

    def send_all(self, data: bytes) -> None:
        self.out += data

    def close(self) -> None:
        self.closed = True

    def decoded_reply(self):
        length = int.from_bytes(self.out[:LENGTH_PREFIX_BYTES], "big")
        body = self.out[LENGTH_PREFIX_BYTES:LENGTH_PREFIX_BYTES + length]
        return json.loads(body.decode("utf-8"))
