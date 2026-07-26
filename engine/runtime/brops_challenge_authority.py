"""Dedicated Wave 3b-1B desktop challenge authority.

The API is intentionally not a generic signing oracle.  A caller first proposes a
strict fixed-shape set of ids/hashes; the authority recomputes request_sha256 and
persists its own protected row.  A second request supplies only that opaque row id;
the authority assembles and signs the canonical challenge once, then replays the
stored exact document for lost-reply retries.
"""
from __future__ import annotations

import json
import os
import pathlib
import secrets
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Mapping

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from bro_signature import canonical_bytes
from brops_governed_common import (
    AUTHORITY_CHANNEL_FRAME_BYTES,
    AUTHORITY_REQUEST_FRAME_BYTES,
    CHALLENGE_TTL_MS,
    ISSUED_RETENTION_MS,
    MAX_CONCURRENT_GOVERNED_TURNS,
    MAX_FUTURE_SKEW_MS,
    MAX_ISSUED_BYTES_PER_INSTALL,
    MAX_ISSUED_ROWS_PER_INSTALL,
    PENDING_TTL_MS,
    GovernedProtocolError,
    b64url_decode,
    b64url_encode,
    request_sha256,
    require_exact_keys,
    require_hex64,
    require_id,
    require_ms,
    sha256_hex,
)

CREATE_PROTOCOL = "brops.governed-challenge-create-pending.v1"
CREATE_RESULT_PROTOCOL = "brops.governed-challenge-create-pending-result.v1"
ISSUE_PROTOCOL = "brops.governed-challenge-issue.v1"
ISSUE_RESULT_PROTOCOL = "brops.governed-challenge-issue-result.v1"
CHALLENGE_PROTOCOL = "brops.governed-turn-challenge.v1"

_CREATE_KEYS = {
    "protocol", "run_id", "task_id", "workspace_id", "install_id",
    "request_nonce", "system_sha256", "history_sha256",
    "generation_config_sha256", "requested_at_ms",
}
_ISSUE_KEYS = {"protocol", "pending_challenge_id"}


@dataclass(frozen=True)
class AuthorityConfig:
    supervisor_id: str
    workspace_id: str
    install_id: str
    challenge_key_id: str
    private_key_hex: str


def _connect(path: os.PathLike[str] | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS governed_pending_challenge (
          pending_challenge_id TEXT PRIMARY KEY,
          request_nonce TEXT NOT NULL,
          run_id TEXT NOT NULL, task_id TEXT NOT NULL,
          workspace_id TEXT NOT NULL, install_id TEXT NOT NULL,
          supervisor_id TEXT NOT NULL,
          system_sha256 TEXT NOT NULL, history_sha256 TEXT NOT NULL,
          generation_config_sha256 TEXT NOT NULL,
          request_sha256 TEXT NOT NULL,
          requested_at_ms INTEGER NOT NULL,
          created_at_ms INTEGER NOT NULL,
          pending_expires_at_ms INTEGER NOT NULL,
          state TEXT NOT NULL CHECK(state IN ('PENDING','ISSUED')),
          issued_at_ms INTEGER,
          issued_challenge_document TEXT,
          issued_challenge_handle TEXT,
          UNIQUE(install_id, request_nonce),
          UNIQUE(install_id, request_sha256)
        );
        CREATE INDEX IF NOT EXISTS idx_pending_expiry
          ON governed_pending_challenge(state, pending_expires_at_ms);
        CREATE INDEX IF NOT EXISTS idx_issued_retention
          ON governed_pending_challenge(state, issued_at_ms);
        """
    )
    return conn


def load_config(env: Mapping[str, str] | None = None) -> AuthorityConfig:
    e = os.environ if env is None else env
    key_path = pathlib.Path(e["BROPS_CHALLENGE_AUTHORITY_KEYDIR"]) / "brops-challenge-authority.json"
    key = json.loads(key_path.read_text("utf-8"))
    return AuthorityConfig(
        supervisor_id=require_id(e["BROPS_GOVERNED_SUPERVISOR_ID"], "supervisor_id"),
        workspace_id=require_id(e["BROPS_GOVERNED_WORKSPACE_ID"], "workspace_id"),
        install_id=require_id(e["BROPS_GOVERNED_INSTALL_ID"], "install_id"),
        challenge_key_id=require_id(key["key_id"], "challenge_key_id"),
        private_key_hex=str(key["private_key"]),
    )


class ChallengeAuthority:
    def __init__(self, db_path: os.PathLike[str] | str, config: AuthorityConfig,
                 *, clock_ms=None) -> None:
        self.conn = _connect(db_path)
        self.config = config
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))

    def close(self) -> None:
        self.conn.close()

    def sweep(self, now_ms: int | None = None) -> int:
        now = self.clock_ms() if now_ms is None else now_ms
        with self.conn:
            cur = self.conn.execute(
                """DELETE FROM governed_pending_challenge
                   WHERE (state='PENDING' AND pending_expires_at_ms < ?)
                      OR (state='ISSUED' AND issued_at_ms IS NOT NULL
                          AND issued_at_ms + ? < ?)""",
                (now, ISSUED_RETENTION_MS, now),
            )
        return cur.rowcount

    def handle(self, frame: Mapping[str, Any]) -> dict[str, Any]:
        try:
            if not isinstance(frame, Mapping):
                raise GovernedProtocolError("frame is not an object")
            if len(canonical_bytes(dict(frame))) > AUTHORITY_REQUEST_FRAME_BYTES:
                # `oversize` is in the create-pending refused set only. The issue-result
                # refused enum (§2.1 (B), line 331) is peer_denied|no_pending_row|
                # pending_expired|key_unavailable|malformed — an oversize ISSUE frame must
                # therefore be answered with an in-set reason (malformed), not `oversize`.
                if frame.get("protocol") == CREATE_PROTOCOL:
                    return self._refused("create", "oversize")
                return self._refused("issue", "malformed")
            if frame.get("protocol") == CREATE_PROTOCOL:
                return self.create_pending(frame)
            if frame.get("protocol") == ISSUE_PROTOCOL:
                return self.issue(frame)
            return self._refused("create", "malformed")
        except GovernedProtocolError as exc:
            which = "issue" if frame.get("protocol") == ISSUE_PROTOCOL else "create"
            reason = "field_invalid" if "invalid" in str(exc) or "64-hex" in str(exc) else "malformed"
            return self._refused(which, reason)

    @staticmethod
    def _refused(which: str, reason: str) -> dict[str, Any]:
        return {
            "protocol": ISSUE_RESULT_PROTOCOL if which == "issue" else CREATE_RESULT_PROTOCOL,
            "status": "refused",
            "reason": reason,
        }

    def _validate_create(self, frame: Mapping[str, Any], now: int) -> dict[str, Any]:
        require_exact_keys(frame, _CREATE_KEYS, "create-pending")
        if frame["protocol"] != CREATE_PROTOCOL:
            raise GovernedProtocolError("wrong protocol")
        out = {
            "run_id": require_id(frame["run_id"], "run_id"),
            "task_id": require_id(frame["task_id"], "task_id"),
            "workspace_id": require_id(frame["workspace_id"], "workspace_id"),
            "install_id": require_id(frame["install_id"], "install_id"),
            "request_nonce": require_id(frame["request_nonce"], "request_nonce"),
            "system_sha256": require_hex64(frame["system_sha256"], "system_sha256"),
            "history_sha256": require_hex64(frame["history_sha256"], "history_sha256"),
            "generation_config_sha256": require_hex64(
                frame["generation_config_sha256"], "generation_config_sha256"
            ),
            "requested_at_ms": require_ms(frame["requested_at_ms"], "requested_at_ms"),
        }
        if out["workspace_id"] != self.config.workspace_id or out["install_id"] != self.config.install_id:
            raise GovernedProtocolError("context invalid")
        if out["requested_at_ms"] > now + MAX_FUTURE_SKEW_MS:
            raise GovernedProtocolError("timestamp invalid")
        out["request_sha256"] = request_sha256(
            workspace_id=out["workspace_id"], install_id=out["install_id"],
            request_nonce=out["request_nonce"], system_sha256=out["system_sha256"],
            history_sha256=out["history_sha256"],
            generation_config_sha256=out["generation_config_sha256"],
            requested_at_ms=out["requested_at_ms"],
        )
        return out

    def create_pending(self, frame: Mapping[str, Any]) -> dict[str, Any]:
        now = self.clock_ms()
        try:
            facts = self._validate_create(frame, now)
        except GovernedProtocolError as exc:
            text = str(exc)
            if "timestamp" in text:
                return self._refused("create", "timestamp_invalid")
            if "context" in text or "invalid" in text or "64-hex" in text:
                return self._refused("create", "field_invalid")
            return self._refused("create", "malformed")

        # Rev-26 ordering: idempotent lookup and synchronous logical expiry happen
        # BEFORE quota and BEFORE any background sweep can erase the conflict row.
        existing = self.conn.execute(
            "SELECT * FROM governed_pending_challenge WHERE install_id=? AND request_nonce=?",
            (facts["install_id"], facts["request_nonce"]),
        ).fetchone()
        if existing is not None:
            if existing["state"] == "PENDING" and now > existing["pending_expires_at_ms"]:
                return self._refused("create", "retry_conflict")
            if existing["state"] == "ISSUED" and (
                existing["issued_at_ms"] is None
                or now > existing["issued_at_ms"] + ISSUED_RETENTION_MS
            ):
                return self._refused("create", "retry_conflict")
            keys = (
                "run_id", "task_id", "workspace_id", "install_id", "request_nonce",
                "system_sha256", "history_sha256", "generation_config_sha256",
                "requested_at_ms", "request_sha256",
            )
            if all(existing[k] == facts[k] for k in keys):
                return {
                    "protocol": CREATE_RESULT_PROTOCOL,
                    "status": "created",
                    "pending_challenge_id": existing["pending_challenge_id"],
                    "pending_expires_at_ms": existing["pending_expires_at_ms"],
                }
            return self._refused("create", "retry_conflict")

        self.sweep(now)
        live_pending = self.conn.execute(
            "SELECT COUNT(*) FROM governed_pending_challenge WHERE install_id=? AND state='PENDING' AND pending_expires_at_ms>=?",
            (facts["install_id"], now),
        ).fetchone()[0]
        live_issued, issued_bytes = self.conn.execute(
            """SELECT COUNT(*), COALESCE(SUM(LENGTH(issued_challenge_document)),0)
               FROM governed_pending_challenge
               WHERE install_id=? AND state='ISSUED' AND issued_at_ms IS NOT NULL
                 AND issued_at_ms + ?>=?""",
            (facts["install_id"], ISSUED_RETENTION_MS, now),
        ).fetchone()
        if (
            live_pending >= MAX_CONCURRENT_GOVERNED_TURNS
            or live_pending + live_issued >= MAX_ISSUED_ROWS_PER_INSTALL
            or issued_bytes >= MAX_ISSUED_BYTES_PER_INSTALL
        ):
            return self._refused("create", "quota_pending")

        pending_id = secrets.token_urlsafe(24)
        expires = now + PENDING_TTL_MS
        try:
            with self.conn:
                self.conn.execute(
                    """INSERT INTO governed_pending_challenge(
                       pending_challenge_id,request_nonce,run_id,task_id,workspace_id,install_id,
                       supervisor_id,system_sha256,history_sha256,generation_config_sha256,
                       request_sha256,requested_at_ms,created_at_ms,pending_expires_at_ms,state)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'PENDING')""",
                    (
                        pending_id, facts["request_nonce"], facts["run_id"], facts["task_id"],
                        facts["workspace_id"], facts["install_id"], self.config.supervisor_id,
                        facts["system_sha256"], facts["history_sha256"],
                        facts["generation_config_sha256"], facts["request_sha256"],
                        facts["requested_at_ms"], now, expires,
                    ),
                )
        except sqlite3.IntegrityError:
            return self._refused("create", "retry_conflict")
        return {
            "protocol": CREATE_RESULT_PROTOCOL,
            "status": "created",
            "pending_challenge_id": pending_id,
            "pending_expires_at_ms": expires,
        }

    def issue(self, frame: Mapping[str, Any]) -> dict[str, Any]:
        try:
            require_exact_keys(frame, _ISSUE_KEYS, "issue")
            if frame["protocol"] != ISSUE_PROTOCOL:
                raise GovernedProtocolError("wrong protocol")
            pending_id = require_id(frame["pending_challenge_id"], "pending_challenge_id")
        except GovernedProtocolError:
            return self._refused("issue", "malformed")
        now = self.clock_ms()
        row = self.conn.execute(
            "SELECT * FROM governed_pending_challenge WHERE pending_challenge_id=?", (pending_id,)
        ).fetchone()
        if row is None:
            return self._refused("issue", "no_pending_row")
        if row["state"] == "ISSUED":
            if row["issued_at_ms"] is None or now > row["issued_at_ms"] + ISSUED_RETENTION_MS:
                # §2.1.1(d) LOCKED: a row PHYSICALLY PRESENT but past its logical-expiry
                # predicate (retention-expired ISSUED) ⇒ `pending_expired`. Only a row that
                # is not physically present (never created, or already swept) ⇒
                # `no_pending_row`. Physical cleanup is a separate concern (sweep()); do not
                # inline-DELETE here, and do not report the swept-case reason for a present row.
                return self._refused("issue", "pending_expired")
            wire = row["issued_challenge_document"]
            try:
                b64url_decode(wire, max_bytes=4096)
            except GovernedProtocolError:
                return self._refused("issue", "key_unavailable")
            return {"protocol": ISSUE_RESULT_PROTOCOL, "status": "issued", "challenge_document_b64": wire}
        if now > row["pending_expires_at_ms"]:
            return self._refused("issue", "pending_expired")

        payload = {
            "protocol": CHALLENGE_PROTOCOL,
            "challenge_key_id": self.config.challenge_key_id,
            "run_id": row["run_id"], "task_id": row["task_id"],
            "workspace_id": row["workspace_id"], "install_id": row["install_id"],
            "supervisor_id": row["supervisor_id"],
            "request_nonce": row["request_nonce"],
            "system_sha256": row["system_sha256"],
            "history_sha256": row["history_sha256"],
            "generation_config_sha256": row["generation_config_sha256"],
            "request_sha256": row["request_sha256"],
            "requested_at_ms": row["requested_at_ms"],
            "challenge_issued_at_ms": now,
            "challenge_expires_at_ms": now + CHALLENGE_TTL_MS,
        }
        try:
            private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(self.config.private_key_hex))
            signature = private.sign(canonical_bytes(payload))
        except Exception:  # noqa: BLE001
            return self._refused("issue", "key_unavailable")
        document_bytes = canonical_bytes({"payload": payload, "sig": b64url_encode(signature)})
        if len(document_bytes) > 4096:
            return self._refused("issue", "key_unavailable")
        wire = b64url_encode(document_bytes)
        if len(canonical_bytes({"protocol": ISSUE_RESULT_PROTOCOL, "status": "issued", "challenge_document_b64": wire})) > AUTHORITY_CHANNEL_FRAME_BYTES:
            return self._refused("issue", "key_unavailable")
        handle = sha256_hex(document_bytes)
        try:
            with self.conn:
                cur = self.conn.execute(
                    """UPDATE governed_pending_challenge
                       SET state='ISSUED', issued_at_ms=?, issued_challenge_document=?,
                           issued_challenge_handle=?
                       WHERE pending_challenge_id=? AND state='PENDING'""",
                    (now, wire, handle, pending_id),
                )
                if cur.rowcount != 1:
                    replay = self.conn.execute(
                        "SELECT issued_challenge_document,issued_at_ms FROM governed_pending_challenge WHERE pending_challenge_id=? AND state='ISSUED'",
                        (pending_id,),
                    ).fetchone()
                    if replay is None:
                        # Genuinely absent (a concurrent sweep/delete removed it) ⇒ swept case.
                        return self._refused("issue", "no_pending_row")
                    if replay[1] is None or now > replay[1] + ISSUED_RETENTION_MS:
                        # §2.1.1(d): physically present but retention-expired ⇒ pending_expired.
                        return self._refused("issue", "pending_expired")
                    wire = replay[0]
        except sqlite3.DatabaseError:
            return self._refused("issue", "key_unavailable")
        return {"protocol": ISSUE_RESULT_PROTOCOL, "status": "issued", "challenge_document_b64": wire}

