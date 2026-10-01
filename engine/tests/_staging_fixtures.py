"""Test helper: the durable staging ledger two suites walk a turn through.

`test_governed_staging_upload` (§4.10(a)(b)(c)) and `test_governed_evidence_request` (§4.10(d))
both need the same ground: one real SQLite ledger on a real file, one real staging root, a
content-addressed store whose handle IS the digest, a turn opened through
``governed_staging_ledger.open_staging``, and a framed connection for the front door. Each had its
own copy of all of it, and the copies had started to disagree — ``new_turn`` derived the challenge
handle from ``nonce`` alone in one and from ``nonce + install`` in the other. A fixture that
disagrees with its twin about what a turn IS tests the disagreement.

Not a test module (no ``test_`` prefix), so unittest discovery ignores it.
"""
from __future__ import annotations

import base64
import hashlib
import json
import pathlib
import tempfile
import unittest

import governed_staging_ledger as gsl
import governed_staging_upload as gsu

SIDECAR_UID = 4101
BROKER_UID = 4102

NOW = 1_700_000_100_000
EXPIRES = NOW + 30_000

CHUNK = gsu.MAX_STAGING_CHUNK_BYTES          # 184320

SYSTEM_BYTES = b"you are a governed assistant.\n" * 7
HISTORY_BYTES = bytes((i * 7 + 11) % 251 for i in range(CHUNK + 4096))
GENCFG_BYTES = b'{"max_tokens":512,"temperature":0.2}'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


class Store:
    """A real content-addressed store: the handle IS the digest of the bytes written."""

    def __init__(self):
        self.blobs = {}

    def publish(self, data: bytes) -> str:
        handle = sha(data)
        self.blobs.setdefault(handle, data)
        return handle


class FramedConn:
    """A framed connection stand-in: one request in, one reply out.

    ``raw`` lets a test send bytes that are NOT the compact serialization of ``body`` —
    which is the only way to show that the front door's frame cap is about what arrived on
    the wire and not about what the decoder made of it.
    """

    def __init__(self, peer_uid, body, raw=None):
        self.peer_uid = peer_uid
        payload = raw if raw is not None else json.dumps(
            body, separators=(",", ":")).encode("utf-8")
        self._inbox = len(payload).to_bytes(4, "big") + payload
        self.sent = bytearray()

    def recv_exactly(self, n):
        head, self._inbox = self._inbox[:n], self._inbox[n:]
        return head

    def send_all(self, data):
        self.sent.extend(data)

    def close(self):
        pass

    def reply(self):
        return json.loads(bytes(self.sent[4:]).decode("utf-8"))


class StagingLedgerCase(unittest.TestCase):
    """One durable ledger on a REAL file, one REAL staging root and one real store per test.

    The staging row is created through ``governed_staging_ledger.open_staging`` — the same
    CAS §4.10(a0) drives — rather than by replaying a signed challenge. What the later hops
    need from the turn is exactly the three committed digests and the ``UPLOADING`` state;
    how the supervisor came to believe them is §4.10(a0)'s tested concern.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._cleanup)
        self.base = pathlib.Path(self.tmp.name)
        self.conn = gsl.open_ledger(str(self.base / "sup.db"))
        self.staging_root = self.base / "staging"
        self.store = Store()
        self.clock = NOW
        self.turn = self.new_turn()

    def _cleanup(self):
        try:
            self.conn.close()
        except Exception:
            pass
        try:
            self.tmp.cleanup()
        except OSError:
            # Windows keeps a handle on a just-closed SQLite file for a moment; the temp
            # dir is the OS's problem, not the test's verdict.
            pass

    def new_turn(self, *, nonce="nonce-1", handle=None, expires=EXPIRES, now=None,
                 install="inst-1", system=None, history=None, gencfg=None):
        # The handle stands in for the digest of a signed challenge document, which is unique
        # to the (install, nonce) it was issued for — so both go into the stand-in.
        handle = handle or sha(nonce.encode("utf-8") + install.encode("utf-8") + b"|ch")
        row = gsl.NewStaging(
            install_id=install,
            request_nonce=nonce,
            challenge_handle=handle,
            run_id="run-1",
            task_id="task-1",
            workspace_id="ws-1",
            system_sha256=sha(system if system is not None else SYSTEM_BYTES),
            history_sha256=sha(history if history is not None else HISTORY_BYTES),
            generation_config_sha256=sha(gencfg if gencfg is not None else GENCFG_BYTES),
            challenge_expires_at_ms=expires,
        )
        gsl.open_staging(self.conn, row, NOW if now is None else now)
        return row

    def turn_row(self, turn=None):
        turn = turn or self.turn
        return gsl.load_staging(self.conn, turn.install_id, turn.request_nonce)
