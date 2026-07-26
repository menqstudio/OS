"""Durable supervisor state machine for Wave 3b-1B governed model turns.

This is additive to the frozen 3b-1A evidence-request service.  It owns challenge
admission, bounded staging, acceptance, one-shot execution, recorder artifacts,
attestation, isolated-signer relay and durable output-stream capabilities.
"""
from __future__ import annotations

import json
import os
import pathlib
import secrets
import shlex
import signal
import sqlite3
import subprocess
import tempfile
import time
import hashlib
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

import brops_socket
from bro_signature import canonical_bytes
from brops_evidence_store import EvidenceStore, EvidenceStoreError
from brops_governed_common import (
    CHALLENGE_TTL_MS, EXECUTION_TIMEOUT_MS, ISSUED_RETENTION_MS,
    LEASE_DURATION_MS, MAX_CONCURRENT_GOVERNED_TURNS, MAX_GENERATION_CONFIG_BYTES,
    MAX_MESSAGE_BYTES, MAX_OUTPUT_BYTES, MAX_OUTPUT_STREAM_ROWS_PER_INSTALL,
    MAX_OUTPUT_STREAM_BYTES_PER_INSTALL,
    MAX_STAGING_CHUNKS, MAX_SYSTEM_BYTES, MIN_LAUNCH_REMAINING_MS,
    OUTPUT_STREAM_RETENTION_MS, OUTPUT_STREAM_TTL_MS, STAGING_CHUNK_BYTES,
    GovernedProtocolError, b64url_decode, b64url_encode,
    generation_config_sha256, history_bytes, model_profile_id, request_sha256,
    require_exact_keys, require_hex64, require_id, sha256_hex, system_bytes,
    validate_generation_config,
)
from brops_supervisor_attest import load_attestation_key

OPEN = "brops.governed-turn-open.v1"
OPEN_RESULT = "brops.governed-turn-open-result.v1"
STAGING_OPEN = "brops.governed-staging-open.v1"
STAGING_OPEN_RESULT = "brops.governed-staging-open-result.v1"
STAGING_CHUNK = "brops.governed-staging-chunk.v1"
STAGING_CHUNK_RESULT = "brops.governed-staging-chunk-result.v1"
STAGING_FINAL = "brops.governed-staging-final.v1"
STAGING_FINAL_RESULT = "brops.governed-staging-final-result.v1"
EVIDENCE_REQUEST = "brops.governed-evidence-request.v1"
TURN_RESULT = "brops.governed-turn-result.v1"
OUTPUT_READ = "brops.governed-turn-output-read.v1"
OUTPUT_READ_RESULT = "brops.governed-turn-output-read-result.v1"
# §4.10(d) pre-acceptance evidence-request reply: a DISJOINT internal namespace, NOT a
# GOVERNED_REFUSAL_REASONS verdict. Returned before any acceptance row exists.
EVIDENCE_REQUEST_RESULT = "brops.governed-evidence-request-result.v1"
SIGN_REQUEST = "brops.governed-sign-request.v1"
SIGN_RESULT = "brops.governed-sign-result.v1"

GOVERNED_REFUSAL_REASONS = frozenset({
    "malformed", "attestation_invalid", "handle_missing", "hash_mismatch",
    "challenge_invalidated", "run_binding_invalid", "policy_mismatch",
    "identity_denied", "lease_expired", "stale_evidence", "evidence_fork",
    "challenge_replay", "acceptance_conflict", "lease_not_ready", "output_oversize",
    "output_timeout", "retry_conflict", "stream_unknown", "stream_expired",
    "stream_binding_mismatch", "seq_out_of_range", "model_profile_unknown",
})
INTERNAL_REFUSALS = frozenset({
    "peer_denied", "doc_oversize", "noncanonical", "handle_mismatch",
    "registry_unknown", "key_invalid", "sig_invalid", "context_mismatch",
    "challenge_expired", "quota_turns", "no_staging_row", "artifact_invalid",
    "digest_mismatch", "oversize", "quota_sessions", "quota_bytes", "session_corrupt",
    "session_unknown", "seq_mismatch", "oversize_chunk", "oversize_frame",
    "over_declared", "nondeterministic_chunk", "too_many_chunks", "len_mismatch",
    "sha_mismatch", "handle_not_challenge", "publish_divergent", "inputs_not_ready",
})

_ARTIFACTS = {
    "system": (MAX_SYSTEM_BYTES, "system_sha256", "system_handle"),
    "history": (8_388_608, "history_sha256", "history_handle"),
    "generation_config": (MAX_GENERATION_CONFIG_BYTES, "generation_config_sha256", "generation_config_handle"),
}


def _key(path: os.PathLike[str] | str, filename: str) -> dict[str, str]:
    obj = json.loads((pathlib.Path(path) / filename).read_text("utf-8"))
    if set(obj) != {"key_id", "private_key"}:
        raise ValueError(f"{filename} must contain key_id/private_key")
    raw = bytes.fromhex(obj["private_key"])
    if len(raw) != 32:
        raise ValueError(f"{filename} private key must be 32 bytes")
    return {"key_id": str(obj["key_id"]), "private_key": str(obj["private_key"])}


def _sign_document(payload: Mapping[str, Any], key: Mapping[str, str], *, sig_field="signature") -> dict[str, Any]:
    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(key["private_key"]))
    return {"payload": dict(payload), sig_field: b64url_encode(private.sign(canonical_bytes(dict(payload))))}


def _verify_b64_sig(payload: Mapping[str, Any], sig: str, pub_hex: str) -> None:
    Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex)).verify(
        b64url_decode(sig, max_bytes=64), canonical_bytes(dict(payload))
    )


@dataclass(frozen=True)
class SupervisorConfig:
    workspace_id: str
    install_id: str
    supervisor_id: str
    executor_id: str
    runner_id: str
    agent_id: str
    session_id: str
    policy_id: str
    policy_version: str
    policy_bundle: bytes
    launcher_executable_sha256: str
    executor_command: tuple[str, ...]
    generation_config_allowlist: frozenset[str]
    record_dir: pathlib.Path


@dataclass(frozen=True)
class ChallengeRegistry:
    document: dict[str, Any]
    document_bytes: bytes
    handle: str
    payload_hash: str
    payload: dict[str, Any]

    @classmethod
    def load(cls, path: os.PathLike[str] | str, root_pubkeys_hex: Mapping[str, str]) -> "ChallengeRegistry":
        raw = pathlib.Path(path).read_bytes()
        obj = json.loads(raw.decode("utf-8"))
        if not isinstance(obj, dict) or canonical_bytes(obj) != raw or set(obj) != {"payload", "root_sig"}:
            raise ValueError("challenge registry must be canonical {payload,root_sig}")
        payload = obj["payload"]
        if set(payload) != {"artifact_type", "root_key_id", "registry_epoch", "registry_issued_at_ms", "keys"}:
            raise ValueError("challenge registry payload key set invalid")
        if payload["artifact_type"] != "brops.challenge-key-registry.v1":
            raise ValueError("wrong challenge registry artifact type")
        root_pub = root_pubkeys_hex.get(payload["root_key_id"])
        if not root_pub:
            raise ValueError("unknown challenge registry root")
        _verify_b64_sig(payload, obj["root_sig"], root_pub)
        if not isinstance(payload["keys"], list) or len(payload["keys"]) > 256:
            raise ValueError("challenge registry keys invalid")
        ids: set[str] = set()
        for entry in payload["keys"]:
            required = {"challenge_key_id", "public_key", "valid_from_ms", "valid_to_ms", "key_epoch", "revoked", "revoked_at_ms"}
            if not isinstance(entry, dict) or set(entry) != required:
                raise ValueError("challenge registry key invalid")
            kid = require_id(entry["challenge_key_id"], "challenge_key_id")
            if kid in ids:
                raise ValueError("duplicate challenge key")
            ids.add(kid)
            if not isinstance(entry["revoked"], bool):
                raise ValueError("revoked must be boolean")
            if entry["revoked"] and not isinstance(entry["revoked_at_ms"], int):
                raise ValueError("revoked key needs revoked_at_ms")
            if not entry["revoked"] and entry["revoked_at_ms"] is not None:
                raise ValueError("active key must have null revoked_at_ms")
            if entry["valid_from_ms"] > entry["valid_to_ms"]:
                raise ValueError("challenge key validity reversed")
            b64url_decode(entry["public_key"], max_bytes=32)
        return cls(obj, raw, sha256_hex(raw), sha256_hex(canonical_bytes(payload)), payload)

    def resolve(self, key_id: str, at_ms: int) -> dict[str, Any] | None:
        for entry in self.payload["keys"]:
            if entry["challenge_key_id"] != key_id:
                continue
            if not entry["valid_from_ms"] <= at_ms <= entry["valid_to_ms"]:
                return None
            revoked_at = entry["revoked_at_ms"]
            if entry["revoked"] and isinstance(revoked_at, int) and revoked_at <= at_ms:
                return None
            return entry
        return None


def _db(path: os.PathLike[str] | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS governed_turn_staging (
          install_id TEXT NOT NULL, request_nonce TEXT NOT NULL,
          challenge_handle TEXT NOT NULL UNIQUE, challenge_document BLOB NOT NULL,
          challenge_payload TEXT NOT NULL, state TEXT NOT NULL,
          run_id TEXT NOT NULL, task_id TEXT NOT NULL,
          challenge_expires_at_ms INTEGER NOT NULL,
          system_handle TEXT, history_handle TEXT, generation_config_handle TEXT,
          accepted_at_ms INTEGER, execution_attempt_id TEXT, lease_id TEXT,
          result_json TEXT, refusal_reason TEXT,
          PRIMARY KEY(install_id, request_nonce)
        );
        CREATE INDEX IF NOT EXISTS idx_turn_staging_live
          ON governed_turn_staging(install_id, challenge_expires_at_ms, state);
        CREATE TABLE IF NOT EXISTS governed_staging_sessions (
          staging_session_id TEXT PRIMARY KEY, challenge_handle TEXT NOT NULL,
          request_nonce TEXT NOT NULL, install_id TEXT NOT NULL, artifact TEXT NOT NULL
            CHECK(artifact IN ('system','history','generation_config')),
          declared_len INTEGER NOT NULL CHECK(declared_len >= 0 AND declared_len <= 8388608),
          declared_sha256 TEXT NOT NULL,
          next_seq INTEGER NOT NULL DEFAULT 0 CHECK(next_seq >= 0 AND next_seq <= 46),
          byte_count INTEGER NOT NULL DEFAULT 0 CHECK(byte_count >= 0 AND byte_count <= declared_len),
          session_dir TEXT NOT NULL,
          state TEXT NOT NULL CHECK(state IN ('UPLOADING','ARTIFACT_READY','SESSION_CORRUPT')),
          published_handle TEXT,
          UNIQUE(challenge_handle, artifact)
        );
        CREATE TABLE IF NOT EXISTS governed_staging_chunks (
          staging_session_id TEXT NOT NULL, seq INTEGER NOT NULL,
          chunk_sha256 TEXT NOT NULL, chunk_len INTEGER NOT NULL CHECK(chunk_len >= 0),
          PRIMARY KEY(staging_session_id, seq),
          FOREIGN KEY(staging_session_id) REFERENCES governed_staging_sessions(staging_session_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS governed_turn_acceptance (
          install_id TEXT NOT NULL, request_nonce TEXT NOT NULL,
          challenge_handle TEXT NOT NULL, run_id TEXT NOT NULL, task_id TEXT NOT NULL,
          workspace_id TEXT NOT NULL, execution_attempt_id TEXT NOT NULL,
          challenge_accepted_at_ms INTEGER NOT NULL,
          challenge_registry_handle TEXT NOT NULL, challenge_registry_hash TEXT NOT NULL,
          challenge_registry_epoch INTEGER NOT NULL, challenge_registry_root_key_id TEXT NOT NULL,
          lease_payload_sha256 TEXT NOT NULL, lease_payload_bytes BLOB NOT NULL,
          lease_handle TEXT,
          state TEXT NOT NULL CHECK(state IN (
            'ACCEPTED_PREPARED','LEASE_READY','EXECUTION_STARTING','EXECUTING',
            'COMPLETED','BLOCKED','FAILED','EXPIRED','RECOVERY_REQUIRED')),
          execution_started_marker TEXT, cgroup_id TEXT, process_group_id TEXT,
          terminal_record_handle TEXT, result_json TEXT, failure_reason TEXT,
          created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL,
          UNIQUE(install_id, request_nonce),
          UNIQUE(challenge_handle),
          UNIQUE(execution_attempt_id)
        );
        CREATE INDEX IF NOT EXISTS idx_acceptance_recovery
          ON governed_turn_acceptance(state);
        CREATE TABLE IF NOT EXISTS governed_output_streams (
          output_stream_id TEXT PRIMARY KEY, receipt_id TEXT NOT NULL UNIQUE,
          execution_attempt_id TEXT NOT NULL UNIQUE, output_handle TEXT NOT NULL,
          output_bytes INTEGER NOT NULL, output_sha256 TEXT NOT NULL,
          created_at_ms INTEGER NOT NULL, expires_at_ms INTEGER NOT NULL,
          retained_until_ms INTEGER NOT NULL, install_id TEXT NOT NULL,
          tombstone INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_output_retention
          ON governed_output_streams(install_id, retained_until_ms, tombstone);
        """
    )
    return conn


class GovernedSupervisor:
    def __init__(self, *, db_path: os.PathLike[str] | str, store: EvidenceStore,
                 registry: ChallengeRegistry, signer_socket: str,
                 attestation_key: Mapping[str, str], lease_key: Mapping[str, str],
                 evidence_recorder_key: Mapping[str, str],
                 governed_turn_recorder_key: Mapping[str, str], config: SupervisorConfig,
                 clock_ms: Callable[[], int] | None = None,
                 monotonic: Callable[[], float] | None = None) -> None:
        # §8 total authority separation: the two recorder authorities MUST be distinct keys, or a
        # single compromise/misconfig (both keydirs pointing at one file) forges both artifacts.
        # Checked before opening any resource so a misconfig fails fast and clean.
        if (evidence_recorder_key["key_id"] == governed_turn_recorder_key["key_id"]
                or evidence_recorder_key.get("private_key")
                == governed_turn_recorder_key.get("private_key")):
            raise ValueError(
                "evidence-recorder and governed-turn-recorder keys must be distinct (§8)")
        db_path = pathlib.Path(db_path)
        self.conn = _db(db_path)
        self.staging_root = db_path.parent / "governed-staging"
        self.staging_root.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            os.chmod(self.staging_root, 0o700)
        self.store = store
        self.registry = registry
        self.signer_socket = signer_socket
        self.attestation_key = dict(attestation_key)
        self.lease_key = dict(lease_key)
        # §8 authority separation (total): the evidence-recorder key signs the execution receipt +
        # containment + evidence; the governed-turn-recorder key signs ONLY the terminal record.
        # A single key must never sign both classes.
        self.evidence_recorder_key = dict(evidence_recorder_key)
        self.governed_turn_recorder_key = dict(governed_turn_recorder_key)
        self.config = config
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self.monotonic = monotonic or time.monotonic
        self.registry_handle = self.store.publish(registry.document_bytes)
        if self.registry_handle != registry.handle:
            raise ValueError("registry store handle mismatch")
        self.policy_bundle_handle = self.store.publish(config.policy_bundle)

    def close(self) -> None:
        self.conn.close()

    def handle(self, frame: Mapping[str, Any]) -> dict[str, Any]:
        protocol = frame.get("protocol") if isinstance(frame, Mapping) else None
        try:
            if protocol == OPEN:
                return self.open_turn(frame)
            if protocol == STAGING_OPEN:
                return self.staging_open(frame)
            if protocol == STAGING_CHUNK:
                return self.staging_chunk(frame)
            if protocol == STAGING_FINAL:
                return self.staging_final(frame)
            if protocol == EVIDENCE_REQUEST:
                return self.execute(frame)
            if protocol == OUTPUT_READ:
                return self.output_read(frame)
            return self._refused(TURN_RESULT, "malformed")
        except (GovernedProtocolError, KeyError, TypeError, ValueError, sqlite3.DatabaseError, EvidenceStoreError):
            if protocol == OPEN:
                return self._refused(OPEN_RESULT, "malformed")
            if protocol == STAGING_OPEN:
                return self._refused(STAGING_OPEN_RESULT, "malformed")
            if protocol == STAGING_CHUNK:
                return {"protocol": STAGING_CHUNK_RESULT, "status": "refused", "next_seq": 0, "reason": "malformed"}
            if protocol == STAGING_FINAL:
                return self._refused(STAGING_FINAL_RESULT, "malformed")
            if protocol == OUTPUT_READ:
                return self._output_error(None, None, "malformed")
            return self._refused(TURN_RESULT, "malformed")

    @staticmethod
    def _refused(protocol: str, reason: str, *, receipt_id=None) -> dict[str, Any]:
        out: dict[str, Any] = {"protocol": protocol, "status": "refused", "reason": reason}
        if protocol == TURN_RESULT:
            out["receipt_id"] = receipt_id
        return out

    @staticmethod
    def _evidence_request_refused(reason: str) -> dict[str, Any]:
        # §4.10(d): a PRE-ACCEPTANCE evidence-request gate failure (no INPUTS_READY row / peer /
        # corrupt session). These reasons are a DISJOINT namespace from GOVERNED_REFUSAL_REASONS
        # and are carried to the desktop via the §4.10(h) diagnostic (stage evidence-request) —
        # never as a governed verdict. No governed_turn_acceptance row is created.
        return {"protocol": EVIDENCE_REQUEST_RESULT, "status": "refused", "reason": reason}

    def _verify_challenge(self, doc_bytes: bytes, *, now_ms: int, final: bool = False) -> dict[str, Any]:
        if len(doc_bytes) > 4096:
            raise GovernedProtocolError("doc_oversize")
        try:
            document = json.loads(doc_bytes.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise GovernedProtocolError("malformed") from exc
        if not isinstance(document, dict) or set(document) != {"payload", "sig"} or canonical_bytes(document) != doc_bytes:
            raise GovernedProtocolError("noncanonical")
        p = document["payload"]
        fields = {
            "protocol", "challenge_key_id", "run_id", "task_id", "workspace_id", "install_id",
            "supervisor_id", "request_nonce", "system_sha256", "history_sha256",
            "generation_config_sha256", "request_sha256", "requested_at_ms",
            "challenge_issued_at_ms", "challenge_expires_at_ms",
        }
        require_exact_keys(p, fields, "challenge payload")
        if p["protocol"] != "brops.governed-turn-challenge.v1":
            raise GovernedProtocolError("malformed")
        for f in ("challenge_key_id", "run_id", "task_id", "workspace_id", "install_id", "supervisor_id", "request_nonce"):
            require_id(p[f], f)
        for f in ("system_sha256", "history_sha256", "generation_config_sha256", "request_sha256"):
            require_hex64(p[f], f)
        if p["workspace_id"] != self.config.workspace_id or p["install_id"] != self.config.install_id or p["supervisor_id"] != self.config.supervisor_id:
            raise GovernedProtocolError("context_mismatch")
        issued = p["challenge_issued_at_ms"]; expires = p["challenge_expires_at_ms"]
        if not isinstance(issued, int) or not isinstance(expires, int) or expires - issued > CHALLENGE_TTL_MS or issued > expires:
            raise GovernedProtocolError("key_invalid")
        if now_ms > expires:
            raise GovernedProtocolError("challenge_expired")
        entry = self.registry.resolve(p["challenge_key_id"], p["challenge_accepted_at_ms"] if final and "challenge_accepted_at_ms" in p else issued)
        if entry is None:
            raise GovernedProtocolError("key_invalid")
        try:
            _verify_b64_sig(p, document["sig"], b64url_decode(entry["public_key"], max_bytes=32).hex())
        except (InvalidSignature, ValueError, GovernedProtocolError) as exc:
            raise GovernedProtocolError("sig_invalid") from exc
        computed = request_sha256(
            workspace_id=p["workspace_id"], install_id=p["install_id"], request_nonce=p["request_nonce"],
            system_sha256=p["system_sha256"], history_sha256=p["history_sha256"],
            generation_config_sha256=p["generation_config_sha256"], requested_at_ms=p["requested_at_ms"],
        )
        if computed != p["request_sha256"]:
            raise GovernedProtocolError("context_mismatch")
        return dict(p)

    def open_turn(self, frame: Mapping[str, Any]) -> dict[str, Any]:
        require_exact_keys(frame, {"protocol", "install_id", "request_nonce", "challenge_doc_b64"}, "turn open")
        require_id(frame["install_id"], "install_id"); require_id(frame["request_nonce"], "request_nonce")
        doc_bytes = b64url_decode(frame["challenge_doc_b64"], max_bytes=4096)
        now = self.clock_ms()  # rev26 resource-admission clock read
        try:
            payload = self._verify_challenge(doc_bytes, now_ms=now)
        except GovernedProtocolError as exc:
            return self._refused(OPEN_RESULT, str(exc))
        if payload["install_id"] != frame["install_id"] or payload["request_nonce"] != frame["request_nonce"]:
            return self._refused(OPEN_RESULT, "context_mismatch")
        handle = sha256_hex(doc_bytes)
        existing = self.conn.execute(
            "SELECT * FROM governed_turn_staging WHERE install_id=? AND request_nonce=?",
            (frame["install_id"], frame["request_nonce"]),
        ).fetchone()
        if existing is not None:
            if existing["challenge_handle"] == handle and bytes(existing["challenge_document"]) == doc_bytes:
                return {"protocol": OPEN_RESULT, "status": "opened", "challenge_handle": handle}
            return self._refused(OPEN_RESULT, "retry_conflict")
        # Concurrent live turns = pre-accept staging (UPLOADING/INPUTS_READY, bounded by challenge
        # expiry) + non-terminal acceptance rows (ACCEPTED_PREPARED..EXECUTING). Terminal ledger
        # states (COMPLETED/BLOCKED/FAILED/EXPIRED/RECOVERY_REQUIRED) do not count.
        live = self.conn.execute(
            "SELECT COUNT(*) FROM governed_turn_staging WHERE install_id=? "
            "AND challenge_expires_at_ms>=? AND state IN ('UPLOADING','INPUTS_READY')",
            (frame["install_id"], now),
        ).fetchone()[0] + self.conn.execute(
            "SELECT COUNT(*) FROM governed_turn_acceptance WHERE install_id=? "
            "AND state IN ('ACCEPTED_PREPARED','LEASE_READY','EXECUTION_STARTING','EXECUTING')",
            (frame["install_id"],),
        ).fetchone()[0]
        if live >= MAX_CONCURRENT_GOVERNED_TURNS:
            return self._refused(OPEN_RESULT, "quota_turns")
        published = self.store.publish(doc_bytes)
        if published != handle:
            return self._refused(OPEN_RESULT, "handle_mismatch")
        try:
            with self.conn:
                self.conn.execute(
                    """INSERT INTO governed_turn_staging(
                       install_id,request_nonce,challenge_handle,challenge_document,
                       challenge_payload,state,run_id,task_id,challenge_expires_at_ms)
                       VALUES(?,?,?,?,?,'UPLOADING',?,?,?)""",
                    (frame["install_id"], frame["request_nonce"], handle, doc_bytes,
                     canonical_bytes(payload).decode("utf-8"), payload["run_id"], payload["task_id"], payload["challenge_expires_at_ms"]),
                )
        except sqlite3.IntegrityError:
            return self._refused(OPEN_RESULT, "retry_conflict")
        return {"protocol": OPEN_RESULT, "status": "opened", "challenge_handle": handle}

    def _turn(self, install_id: str, nonce: str, challenge_handle: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM governed_turn_staging WHERE install_id=? AND request_nonce=? AND challenge_handle=?",
            (install_id, nonce, challenge_handle),
        ).fetchone()

    @staticmethod
    def _fsync_dir(path: pathlib.Path) -> None:
        if os.name != "posix":
            return
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _session_dir(self, session_id: str) -> pathlib.Path:
        path = self.staging_root / session_id
        path.mkdir(mode=0o700, parents=False, exist_ok=True)
        if os.name == "posix":
            os.chmod(path, 0o700)
        return path

    def _mark_session_corrupt(self, session_id: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE governed_staging_sessions SET state='SESSION_CORRUPT' WHERE staging_session_id=?",
                (session_id,),
            )

    def _publish_chunk_file(self, session_dir: pathlib.Path, seq: int, data: bytes) -> pathlib.Path:
        """Durably create immutable <seq>.chunk without overwriting an existing file."""
        target = session_dir / f"{seq}.chunk"
        fd, tmp_name = tempfile.mkstemp(dir=session_dir, prefix=f".{seq}.", suffix=".part")
        tmp = pathlib.Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as out:
                out.write(data)
                out.flush()
                os.fsync(out.fileno())
            if os.name == "posix":
                os.chmod(tmp, 0o600)
            try:
                os.link(tmp, target)
            except FileExistsError:
                if target.read_bytes() != data:
                    raise GovernedProtocolError("retry_conflict")
            except OSError:
                # Filesystems without hardlink support still get create-if-absent.
                try:
                    out_fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                except FileExistsError:
                    if target.read_bytes() != data:
                        raise GovernedProtocolError("retry_conflict")
                else:
                    with os.fdopen(out_fd, "wb") as out:
                        out.write(data)
                        out.flush()
                        os.fsync(out.fileno())
            self._fsync_dir(session_dir)
            return target
        finally:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass

    def staging_open(self, frame: Mapping[str, Any]) -> dict[str, Any]:
        keys = {"protocol", "install_id", "challenge_handle", "request_nonce", "artifact", "declared_len", "declared_sha256"}
        require_exact_keys(frame, keys, "staging open")
        install = require_id(frame["install_id"], "install_id"); nonce = require_id(frame["request_nonce"], "request_nonce")
        handle = require_hex64(frame["challenge_handle"], "challenge_handle")
        artifact = frame["artifact"]
        if artifact not in _ARTIFACTS:
            return self._refused(STAGING_OPEN_RESULT, "artifact_invalid")
        if isinstance(frame["declared_len"], bool) or not isinstance(frame["declared_len"], int):
            return self._refused(STAGING_OPEN_RESULT, "malformed")
        ceiling, hash_field, _ = _ARTIFACTS[artifact]
        if frame["declared_len"] < 0 or frame["declared_len"] > ceiling:
            return self._refused(STAGING_OPEN_RESULT, "oversize")
        require_hex64(frame["declared_sha256"], "declared_sha256")
        turn = self._turn(install, nonce, handle)
        if turn is None or turn["state"] not in ("UPLOADING", "INPUTS_READY"):
            return self._refused(STAGING_OPEN_RESULT, "no_staging_row")
        payload = json.loads(turn["challenge_payload"])
        if payload[hash_field] != frame["declared_sha256"]:
            return self._refused(STAGING_OPEN_RESULT, "digest_mismatch")
        existing = self.conn.execute(
            "SELECT * FROM governed_staging_sessions WHERE challenge_handle=? AND artifact=?",
            (handle, artifact),
        ).fetchone()
        if existing is not None:
            if existing["state"] == "SESSION_CORRUPT":
                return self._refused(STAGING_OPEN_RESULT, "session_corrupt")
            if existing["declared_len"] == frame["declared_len"] and existing["declared_sha256"] == frame["declared_sha256"]:
                return {"protocol": STAGING_OPEN_RESULT, "status": "opened", "staging_session_id": existing["staging_session_id"], "next_seq": existing["next_seq"]}
            return self._refused(STAGING_OPEN_RESULT, "retry_conflict")
        session = secrets.token_urlsafe(24)
        session_dir = self._session_dir(session)
        try:
            with self.conn:
                self.conn.execute(
                    """INSERT INTO governed_staging_sessions(
                       staging_session_id,challenge_handle,request_nonce,install_id,artifact,
                       declared_len,declared_sha256,next_seq,byte_count,session_dir,state)
                       VALUES(?,?,?,?,?,?,?,0,0,?,'UPLOADING')""",
                    (session, handle, nonce, install, artifact, frame["declared_len"], frame["declared_sha256"], str(session_dir)),
                )
        except Exception:
            try:
                session_dir.rmdir()
            except OSError:
                pass
            raise
        return {"protocol": STAGING_OPEN_RESULT, "status": "opened", "staging_session_id": session, "next_seq": 0}

    def staging_chunk(self, frame: Mapping[str, Any]) -> dict[str, Any]:
        require_exact_keys(frame, {"protocol", "staging_session_id", "seq", "bytes_b64"}, "staging chunk")
        session_id = require_id(frame["staging_session_id"], "staging_session_id")
        if isinstance(frame["seq"], bool) or not isinstance(frame["seq"], int) or frame["seq"] < 0:
            return {"protocol": STAGING_CHUNK_RESULT, "status": "refused", "next_seq": 0, "reason": "malformed"}
        row = self.conn.execute("SELECT * FROM governed_staging_sessions WHERE staging_session_id=?", (session_id,)).fetchone()
        if row is None:
            return {"protocol": STAGING_CHUNK_RESULT, "status": "refused", "next_seq": 0, "reason": "session_unknown"}
        if row["state"] == "SESSION_CORRUPT":
            return {"protocol": STAGING_CHUNK_RESULT, "status": "refused", "next_seq": row["next_seq"], "reason": "session_corrupt"}
        if row["state"] != "UPLOADING":
            return {"protocol": STAGING_CHUNK_RESULT, "status": "refused", "next_seq": row["next_seq"], "reason": "retry_conflict"}
        if frame["seq"] >= MAX_STAGING_CHUNKS:
            return {"protocol": STAGING_CHUNK_RESULT, "status": "refused", "next_seq": row["next_seq"], "reason": "too_many_chunks"}
        try:
            data = b64url_decode(frame["bytes_b64"], max_bytes=STAGING_CHUNK_BYTES)
        except GovernedProtocolError:
            return {"protocol": STAGING_CHUNK_RESULT, "status": "refused", "next_seq": row["next_seq"], "reason": "oversize_chunk"}
        seq = frame["seq"]
        session_dir = pathlib.Path(row["session_dir"])
        target = session_dir / f"{seq}.chunk"
        if seq < row["next_seq"]:
            old = self.conn.execute(
                "SELECT chunk_sha256,chunk_len FROM governed_staging_chunks WHERE staging_session_id=? AND seq=?", (session_id, seq)
            ).fetchone()
            if old is None or not target.is_file():
                self._mark_session_corrupt(session_id)
                return {"protocol": STAGING_CHUNK_RESULT, "status": "refused", "next_seq": row["next_seq"], "reason": "session_corrupt"}
            disk = target.read_bytes()
            if len(disk) != old["chunk_len"] or sha256_hex(disk) != old["chunk_sha256"]:
                self._mark_session_corrupt(session_id)
                return {"protocol": STAGING_CHUNK_RESULT, "status": "refused", "next_seq": row["next_seq"], "reason": "session_corrupt"}
            if disk == data:
                return {"protocol": STAGING_CHUNK_RESULT, "status": "ack", "next_seq": row["next_seq"], "reason": None}
            return {"protocol": STAGING_CHUNK_RESULT, "status": "refused", "next_seq": row["next_seq"], "reason": "retry_conflict"}
        if seq > row["next_seq"]:
            return {"protocol": STAGING_CHUNK_RESULT, "status": "refused", "next_seq": row["next_seq"], "reason": "seq_mismatch"}
        remaining = row["declared_len"] - row["byte_count"]
        expected_len = min(STAGING_CHUNK_BYTES, remaining)
        if expected_len == 0 or len(data) != expected_len:
            return {"protocol": STAGING_CHUNK_RESULT, "status": "refused", "next_seq": row["next_seq"], "reason": "nondeterministic_chunk"}
        if row["byte_count"] + len(data) > row["declared_len"]:
            return {"protocol": STAGING_CHUNK_RESULT, "status": "refused", "next_seq": row["next_seq"], "reason": "over_declared"}
        try:
            self._publish_chunk_file(session_dir, seq, data)
        except GovernedProtocolError as exc:
            return {"protocol": STAGING_CHUNK_RESULT, "status": "refused", "next_seq": row["next_seq"], "reason": str(exc)}
        digest = sha256_hex(data)
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            current = self.conn.execute("SELECT * FROM governed_staging_sessions WHERE staging_session_id=?", (session_id,)).fetchone()
            if current is None or current["state"] != "UPLOADING":
                raise GovernedProtocolError("session_corrupt")
            if current["next_seq"] != seq:
                self.conn.execute("ROLLBACK")
                return self.staging_chunk(frame)
            self.conn.execute(
                "INSERT INTO governed_staging_chunks(staging_session_id,seq,chunk_sha256,chunk_len) VALUES(?,?,?,?)",
                (session_id, seq, digest, len(data)),
            )
            self.conn.execute(
                "UPDATE governed_staging_sessions SET next_seq=next_seq+1,byte_count=byte_count+? WHERE staging_session_id=?",
                (len(data), session_id),
            )
            self.conn.execute("COMMIT")
        except GovernedProtocolError:
            if self.conn.in_transaction:
                self.conn.execute("ROLLBACK")
            self._mark_session_corrupt(session_id)
            return {"protocol": STAGING_CHUNK_RESULT, "status": "refused", "next_seq": row["next_seq"], "reason": "session_corrupt"}
        except Exception:
            if self.conn.in_transaction:
                self.conn.execute("ROLLBACK")
            raise
        return {"protocol": STAGING_CHUNK_RESULT, "status": "ack", "next_seq": seq + 1, "reason": None}

    def staging_final(self, frame: Mapping[str, Any]) -> dict[str, Any]:
        require_exact_keys(frame, {"protocol", "staging_session_id", "seq"}, "staging final")
        session_id = require_id(frame["staging_session_id"], "staging_session_id")
        row = self.conn.execute("SELECT * FROM governed_staging_sessions WHERE staging_session_id=?", (session_id,)).fetchone()
        if row is None:
            return self._refused(STAGING_FINAL_RESULT, "session_unknown")
        if row["state"] == "SESSION_CORRUPT":
            return self._refused(STAGING_FINAL_RESULT, "session_corrupt")
        if frame["seq"] != row["next_seq"]:
            return self._refused(STAGING_FINAL_RESULT, "seq_mismatch")
        if row["state"] == "ARTIFACT_READY":
            turn = self.conn.execute("SELECT * FROM governed_turn_staging WHERE challenge_handle=?", (row["challenge_handle"],)).fetchone()
            return {"protocol": STAGING_FINAL_RESULT, "status": "published", "artifact": row["artifact"], "handle": row["published_handle"], "inputs_ready": turn["state"] == "INPUTS_READY"}
        session_dir = pathlib.Path(row["session_dir"])
        fd, final_name = tempfile.mkstemp(dir=session_dir, prefix=".final-", suffix=".part")
        final_path = pathlib.Path(final_name)
        hasher = hashlib.sha256(); total = 0
        try:
            with os.fdopen(fd, "wb") as out:
                for seq in range(row["next_seq"]):
                    meta = self.conn.execute(
                        "SELECT chunk_sha256,chunk_len FROM governed_staging_chunks WHERE staging_session_id=? AND seq=?",
                        (session_id, seq),
                    ).fetchone()
                    chunk_path = session_dir / f"{seq}.chunk"
                    if meta is None or not chunk_path.is_file():
                        self._mark_session_corrupt(session_id)
                        return self._refused(STAGING_FINAL_RESULT, "session_corrupt")
                    chunk = chunk_path.read_bytes()
                    if len(chunk) != meta["chunk_len"] or sha256_hex(chunk) != meta["chunk_sha256"]:
                        self._mark_session_corrupt(session_id)
                        return self._refused(STAGING_FINAL_RESULT, "session_corrupt")
                    out.write(chunk); hasher.update(chunk); total += len(chunk)
                out.flush(); os.fsync(out.fileno())
            self._fsync_dir(session_dir)
            if total != row["declared_len"]:
                return self._refused(STAGING_FINAL_RESULT, "len_mismatch")
            digest = hasher.hexdigest()
            if digest != row["declared_sha256"]:
                return self._refused(STAGING_FINAL_RESULT, "sha_mismatch")
            data = final_path.read_bytes()
            published = self.store.publish(data)
            if published != digest:
                return self._refused(STAGING_FINAL_RESULT, "publish_divergent")
        finally:
            try:
                final_path.unlink()
            except FileNotFoundError:
                pass
        _, _, handle_field = _ARTIFACTS[row["artifact"]]
        with self.conn:
            self.conn.execute(
                "UPDATE governed_staging_sessions SET state='ARTIFACT_READY',published_handle=? WHERE staging_session_id=?",
                (published, session_id),
            )
            self.conn.execute(
                f"UPDATE governed_turn_staging SET {handle_field}=? WHERE challenge_handle=?",
                (published, row["challenge_handle"]),
            )
            turn = self.conn.execute("SELECT * FROM governed_turn_staging WHERE challenge_handle=?", (row["challenge_handle"],)).fetchone()
            ready = all(turn[k] is not None for k in ("system_handle", "history_handle", "generation_config_handle"))
            if ready:
                self.conn.execute("UPDATE governed_turn_staging SET state='INPUTS_READY' WHERE challenge_handle=?", (row["challenge_handle"],))
        return {"protocol": STAGING_FINAL_RESULT, "status": "published", "artifact": row["artifact"], "handle": published, "inputs_ready": ready}

    def _run_executor(self, *, system_handle: str, history_handle: str, config_handle: str) -> tuple[bytes, int, int]:
        if not self.config.executor_command:
            raise GovernedProtocolError("model_profile_unknown")
        start_ms = self.clock_ms(); start_mono = self.monotonic()
        system_path = self.store.root / system_handle
        history_path = self.store.root / history_handle
        config_path = self.store.root / config_handle
        fds = [os.open(p, os.O_RDONLY) for p in (system_path, history_path, config_path)]
        env = os.environ.copy()
        env.update({
            "BROPS_LAUNCH_SYSTEM_FD": str(fds[0]),
            "BROPS_LAUNCH_HISTORY_FD": str(fds[1]),
            "BROPS_LAUNCH_CONFIG_FD": str(fds[2]),
        })
        launcher = pathlib.Path(__file__).with_name("brops_executor_launcher.py")
        command = (os.environ.get("PYTHON", os.sys.executable), str(launcher), *self.config.executor_command)

        def _preexec() -> None:
            os.setsid()

        try:
            proc = subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=env, pass_fds=tuple(fds), preexec_fn=_preexec if os.name == "posix" else None,
            )
            try:
                output, _stderr = proc.communicate(timeout=EXECUTION_TIMEOUT_MS / 1000)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
                proc.communicate()
                raise GovernedProtocolError("output_timeout")
            if proc.returncode != 0:
                raise GovernedProtocolError("run_binding_invalid")
            if len(output) > MAX_OUTPUT_BYTES:
                raise GovernedProtocolError("output_oversize")
            elapsed = (self.monotonic() - start_mono) * 1000
            if elapsed >= EXECUTION_TIMEOUT_MS:
                raise GovernedProtocolError("output_timeout")
            return output, start_ms, self.clock_ms()
        finally:
            for fd in fds:
                os.close(fd)

    def _attest(self, evidence: Mapping[str, Any]) -> dict[str, Any]:
        private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(self.attestation_key["private_key"]))
        return {
            "protocol": SIGN_REQUEST,
            "attestation": {
                "attestation_protocol": "brops.run-attestation.v1",
                "supervisor_key_id": self.attestation_key["key_id"],
                "sig": b64url_encode(private.sign(canonical_bytes(dict(evidence)))),
            },
            "evidence": dict(evidence),
        }

    def _acceptance_row(self, install: str, nonce: str, handle: str):
        return self.conn.execute(
            "SELECT * FROM governed_turn_acceptance "
            "WHERE install_id=? AND request_nonce=? AND challenge_handle=?",
            (install, nonce, handle),
        ).fetchone()

    def _set_acceptance(self, handle: str, state: str, now_ms: int, *, result_json=None,
                        failure_reason=None, lease_handle=None, process_group_id=None,
                        cgroup_id=None, terminal_record_handle=None) -> None:
        sets = ["state=?", "updated_at_ms=?"]
        vals: list[Any] = [state, now_ms]
        for col, val in (("result_json", result_json), ("failure_reason", failure_reason),
                         ("lease_handle", lease_handle), ("process_group_id", process_group_id),
                         ("cgroup_id", cgroup_id), ("terminal_record_handle", terminal_record_handle)):
            if val is not None:
                sets.append(f"{col}=?"); vals.append(val)
        vals.append(handle)
        with self.conn:
            self.conn.execute(
                f"UPDATE governed_turn_acceptance SET {','.join(sets)} WHERE challenge_handle=?", vals)

    def recover(self) -> None:
        """§5 restart scan. A row left at ACCEPTED_PREPARED (crash after the CAS insert, before the
        lease was published) is deterministically re-signed from the persisted lease bytes and
        advanced to LEASE_READY (idempotent publish; no re-execution, no fresh nonces). Post-launch
        ambiguity (EXECUTION_STARTING/EXECUTING with no terminal proof) is fail-closed to
        RECOVERY_REQUIRED and NEVER auto-relaunched; a LEASE_READY row whose launch gate no longer
        holds becomes EXPIRED. Deterministic, idempotent."""
        now = self.clock_ms()
        with self.conn:
            self.conn.execute(
                "UPDATE governed_turn_acceptance SET state='RECOVERY_REQUIRED',updated_at_ms=? "
                "WHERE state IN ('EXECUTION_STARTING','EXECUTING') "
                "AND terminal_record_handle IS NULL AND result_json IS NULL",
                (now,))
        # §5 crash-resume: re-sign ACCEPTED_PREPARED leases deterministically from lease_payload_bytes.
        for row in self.conn.execute(
                "SELECT challenge_handle,lease_payload_bytes FROM governed_turn_acceptance "
                "WHERE state='ACCEPTED_PREPARED'").fetchall():
            lease_payload = json.loads(bytes(row["lease_payload_bytes"]))
            lease_doc = _sign_document(lease_payload, self.lease_key)
            lease_handle = self.store.publish(canonical_bytes(lease_doc))
            self._set_acceptance(row["challenge_handle"], "LEASE_READY", now, lease_handle=lease_handle)
        for row in self.conn.execute(
                "SELECT challenge_handle,lease_payload_bytes FROM governed_turn_acceptance "
                "WHERE state='LEASE_READY'").fetchall():
            lp = json.loads(bytes(row["lease_payload_bytes"]))
            if not (lp["lease_issued_at_ms"] <= now <= lp["lease_expires_at_ms"]
                    and lp["lease_expires_at_ms"] - now >= MIN_LAUNCH_REMAINING_MS):
                verdict = self._refused(TURN_RESULT, "lease_expired")
                self._set_acceptance(row["challenge_handle"], "EXPIRED", now,
                                     result_json=canonical_bytes(verdict).decode("utf-8"),
                                     failure_reason="lease_expired")

    def execute(self, frame: Mapping[str, Any]) -> dict[str, Any]:
        require_exact_keys(frame, {"protocol", "install_id", "challenge_handle", "request_nonce"}, "evidence request")
        install = require_id(frame["install_id"], "install_id"); nonce = require_id(frame["request_nonce"], "request_nonce")
        handle = require_hex64(frame["challenge_handle"], "challenge_handle")
        # §5 idempotent replay: a durable acceptance verdict is returned verbatim, never re-executed.
        prior = self._acceptance_row(install, nonce, handle)
        if prior is not None and prior["result_json"]:
            return json.loads(prior["result_json"])
        turn = self._turn(install, nonce, handle)
        if turn is None or turn["state"] != "INPUTS_READY":
            # No INPUTS_READY staging row ⇒ pre-acceptance internal refusal (§4.10(d)); no row created.
            return self._evidence_request_refused("no_inputs_ready")
        now = self.clock_ms()  # §5 step 2: the acceptance clock, read exactly once.
        challenge = json.loads(turn["challenge_payload"])
        # §5 step 3 — acceptance-time authoritative verification (as-of challenge_accepted_at_ms).
        # A deterministic refusal here is recorded as a durable BLOCKED row AFTER the CAS insert.
        deterministic = None
        if now > turn["challenge_expires_at_ms"] or self.registry.resolve(challenge["challenge_key_id"], now) is None:
            deterministic = "challenge_invalidated"
        cfg_hash = None
        try:
            cfg_hash = generation_config_sha256(validate_generation_config(
                json.loads(self.store.read(turn["generation_config_handle"]).decode("utf-8"))))
        except Exception:  # noqa: BLE001 — a malformed staged config is a deterministic binding failure
            pass
        if deterministic is None:
            if cfg_hash != challenge["generation_config_sha256"]:
                deterministic = "run_binding_invalid"
            elif cfg_hash not in self.config.generation_config_allowlist:
                deterministic = "model_profile_unknown"
        attempt = str(uuid.uuid4()); lease_id = str(uuid.uuid4()); receipt_id = str(uuid.uuid4())
        profile = model_profile_id(cfg_hash) if cfg_hash else "cfg-sha256:" + "0" * 64
        lease_payload = {
            "artifact_type": "brops.governed-turn-lease.v1", "key_id": self.lease_key["key_id"],
            "schema": 1, "lease_id": lease_id, "nonce": secrets.token_urlsafe(24),
            "run_id": challenge["run_id"], "execution_attempt_id": attempt,
            "task_id": challenge["task_id"], "agent_id": self.config.agent_id,
            "session_id": self.config.session_id, "workspace_id": self.config.workspace_id,
            "install_id": self.config.install_id, "supervisor_id": self.config.supervisor_id,
            "task_class": "governed-model-turn-v1", "allowed_capabilities": ["INVOKE_GOVERNED_MODEL"],
            "max_tool_calls": 0, "launcher_executable_sha256": self.config.launcher_executable_sha256,
            "model_profile_id": profile, "generation_config_sha256": cfg_hash,
            "lease_issued_at_ms": now, "lease_expires_at_ms": now + LEASE_DURATION_MS,
            "challenge_accepted_at_ms": now, "request_nonce": nonce,
            "challenge_handle": handle, "challenge_key_id": challenge["challenge_key_id"],
            "challenge_registry_handle": self.registry.handle,
            "challenge_registry_hash": self.registry.payload_hash,
            "challenge_registry_epoch": self.registry.payload["registry_epoch"],
            "challenge_registry_root_key_id": self.registry.payload["root_key_id"],
        }
        lease_bytes = canonical_bytes(lease_payload)
        # §5 step 4 — CAS insert ACCEPTED_PREPARED: reserve the attempt and persist the EXACT lease
        # bytes to be signed BEFORE any signing (crash → deterministic re-sign). The three UNIQUE
        # constraints make this the acceptance CAS: a concurrent duplicate loses and reads the verdict.
        try:
            with self.conn:
                self.conn.execute(
                    """INSERT INTO governed_turn_acceptance(
                       install_id,request_nonce,challenge_handle,run_id,task_id,workspace_id,
                       execution_attempt_id,challenge_accepted_at_ms,challenge_registry_handle,
                       challenge_registry_hash,challenge_registry_epoch,challenge_registry_root_key_id,
                       lease_payload_sha256,lease_payload_bytes,state,created_at_ms,updated_at_ms)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,'ACCEPTED_PREPARED',?,?)""",
                    (install, nonce, handle, challenge["run_id"], challenge["task_id"],
                     self.config.workspace_id, attempt, now, self.registry.handle,
                     self.registry.payload_hash, self.registry.payload["registry_epoch"],
                     self.registry.payload["root_key_id"], sha256_hex(lease_bytes), lease_bytes, now, now),
                )
        except sqlite3.IntegrityError:
            prior = self._acceptance_row(install, nonce, handle)
            if prior is not None and prior["result_json"]:
                return json.loads(prior["result_json"])
            return self._refused(TURN_RESULT, "acceptance_conflict", receipt_id=receipt_id)
        # §5 — a deterministic post-acceptance refusal ⇒ a durable BLOCKED row (idempotent); no lease/launch.
        if deterministic is not None:
            verdict = self._refused(TURN_RESULT, deterministic, receipt_id=receipt_id)
            self._set_acceptance(handle, "BLOCKED", self.clock_ms(),
                                 result_json=canonical_bytes(verdict).decode("utf-8"),
                                 failure_reason=deterministic)
            return verdict
        # §5 steps 6/7 — sign + publish the lease from the persisted bytes; CAS ACCEPTED_PREPARED->LEASE_READY.
        lease_doc = _sign_document(lease_payload, self.lease_key)
        lease_handle = self.store.publish(canonical_bytes(lease_doc))
        self._set_acceptance(handle, "LEASE_READY", self.clock_ms(), lease_handle=lease_handle)
        # §5 step 8a — launch gate (wall clock read once): (i) not pre-valid / not expired AND
        # (ii) remaining budget >= MIN_LAUNCH_REMAINING_MS. Failure ⇒ deterministic EXPIRED, no launch.
        gate_now = self.clock_ms()
        if not (lease_payload["lease_issued_at_ms"] <= gate_now <= lease_payload["lease_expires_at_ms"]
                and lease_payload["lease_expires_at_ms"] - gate_now >= MIN_LAUNCH_REMAINING_MS):
            verdict = self._refused(TURN_RESULT, "lease_expired", receipt_id=receipt_id)
            self._set_acceptance(handle, "EXPIRED", self.clock_ms(),
                                 result_json=canonical_bytes(verdict).decode("utf-8"),
                                 failure_reason="lease_expired")
            return verdict
        # §5 step 9 — persist EXECUTION_STARTING BEFORE launching (no auto-relaunch past this point).
        self._set_acceptance(handle, "EXECUTION_STARTING", self.clock_ms())
        try:
            output, started_at, finished_at = self._run_executor(
                system_handle=turn["system_handle"], history_handle=turn["history_handle"],
                config_handle=turn["generation_config_handle"],
            )
        except GovernedProtocolError as exc:
            reason = str(exc) if str(exc) in GOVERNED_REFUSAL_REASONS else "run_binding_invalid"
            verdict = self._refused(TURN_RESULT, reason, receipt_id=receipt_id)
            # Deterministic operational failure (timeout/oversize/etc.) ⇒ FAILED + durable verdict; an
            # AMBIGUOUS crash instead leaves the row at EXECUTION_STARTING for recover() → RECOVERY_REQUIRED.
            self._set_acceptance(handle, "FAILED", self.clock_ms(),
                                 result_json=canonical_bytes(verdict).decode("utf-8"),
                                 failure_reason=reason)
            return verdict
        # §5 — child ran; persist process metadata and flip EXECUTION_STARTING -> EXECUTING.
        self._set_acceptance(handle, "EXECUTING", self.clock_ms(),
                             process_group_id=attempt, cgroup_id="process-group:" + attempt)
        output_handle = self.store.publish(output)
        containment = {
            "artifact_type": "brops.governed-turn-containment.v1",
            "run_id": challenge["run_id"], "execution_attempt_id": attempt, "lease_id": lease_id,
            "runner_id": self.config.runner_id, "executor_id": self.config.executor_id,
            "cgroup_id": "process-group:" + attempt, "process_group_id": attempt,
            "contained": True, "teardown_outcome": "contained", "measured_at_ms": finished_at,
        }
        containment_handle = self.store.publish(canonical_bytes(containment))
        execution_receipt_payload = {
            "artifact_type": "brops.governed-turn-execution-receipt.v1",
            "key_id": self.evidence_recorder_key["key_id"], "receipt_id": receipt_id,
            "run_id": challenge["run_id"], "execution_attempt_id": attempt, "lease_id": lease_id,
            "runner_id": self.config.runner_id, "executor_id": self.config.executor_id,
            "exit_code": 0, "contained": True, "output_handle": output_handle,
            "output_sha256": output_handle, "output_bytes": len(output),
            "started_at_ms": started_at, "finished_at_ms": finished_at,
        }
        execution_receipt = _sign_document(execution_receipt_payload, self.evidence_recorder_key)
        execution_receipt_handle = self.store.publish(canonical_bytes(execution_receipt))
        event_hash = sha256_hex(canonical_bytes({"attempt": attempt, "output_handle": output_handle, "finished_at_ms": finished_at}))
        record_payload = {
            "artifact_type": "brops.governed-turn-record.v1", "key_id": self.governed_turn_recorder_key["key_id"],
            "run_id": challenge["run_id"], "execution_attempt_id": attempt,
            "task_id": challenge["task_id"], "agent_id": self.config.agent_id, "session_id": self.config.session_id,
            "workspace_id": self.config.workspace_id, "install_id": self.config.install_id,
            "supervisor_id": self.config.supervisor_id, "executor_id": self.config.executor_id,
            "runner_id": self.config.runner_id, "lease_id": lease_id,
            "lease_nonce": lease_payload["nonce"], "lease_issued_at_ms": lease_payload["lease_issued_at_ms"],
            "lease_expires_at_ms": lease_payload["lease_expires_at_ms"], "lease_handle": lease_handle,
            "request_nonce": nonce, "system_sha256": challenge["system_sha256"],
            "history_sha256": challenge["history_sha256"], "generation_config_sha256": cfg_hash,
            "requested_at_ms": challenge["requested_at_ms"], "request_sha256": challenge["request_sha256"],
            "challenge_handle": handle, "challenge_key_id": challenge["challenge_key_id"],
            "challenge_issued_at_ms": challenge["challenge_issued_at_ms"],
            "challenge_expires_at_ms": challenge["challenge_expires_at_ms"],
            "challenge_accepted_at_ms": now, "challenge_registry_handle": self.registry.handle,
            "challenge_registry_hash": self.registry.payload_hash,
            "challenge_registry_epoch": self.registry.payload["registry_epoch"],
            "challenge_registry_root_key_id": self.registry.payload["root_key_id"],
            "output_sha256": output_handle, "output_bytes": len(output),
            "policy_id": self.config.policy_id, "policy_version": self.config.policy_version,
            "policy_bundle_sha256": self.policy_bundle_handle,
            "containment_evidence_sha256": containment_handle, "containment_event_id": str(uuid.uuid4()),
            "receipt_id": receipt_id, "execution_receipt_handle": execution_receipt_handle,
            "evidence_final_event_hash": event_hash, "evidence_event_count": 1,
            "evidence_last_sequence": 1, "evidence_head_sequence": 1, "completed_at_ms": finished_at,
        }
        record_doc = _sign_document(record_payload, self.governed_turn_recorder_key)
        record_bytes = canonical_bytes(record_doc)
        record_handle = self.store.publish(record_bytes)
        self.config.record_dir.mkdir(parents=True, exist_ok=True)
        mirror = self.config.record_dir / f"{challenge['run_id']}__{attempt}.json"
        tmp = mirror.with_suffix(".tmp")
        tmp.write_bytes(record_bytes)
        os.replace(tmp, mirror)
        evidence = {
            "run_id": challenge["run_id"], "execution_attempt_id": attempt, "lease_id": lease_id,
            "task_id": challenge["task_id"], "request_nonce": nonce, "receipt_id": receipt_id,
            "decision": "completed", "workspace_id": self.config.workspace_id,
            "install_id": self.config.install_id, "supervisor_id": self.config.supervisor_id,
            "executor_id": self.config.executor_id, "runner_id": self.config.runner_id,
            "policy_id": self.config.policy_id, "policy_version": self.config.policy_version,
            "requested_at_ms": challenge["requested_at_ms"], "completed_at_ms": finished_at,
            "challenge_accepted_at_ms": now, "system_handle": turn["system_handle"],
            "history_handle": turn["history_handle"], "generation_config_handle": turn["generation_config_handle"],
            "output_handle": output_handle, "containment_evidence_handle": containment_handle,
            "policy_bundle_handle": self.policy_bundle_handle, "lease_handle": lease_handle,
            "execution_receipt_handle": execution_receipt_handle,
            "challenge_handle": handle, "challenge_key_id": challenge["challenge_key_id"],
            "challenge_registry_handle": self.registry.handle,
            "challenge_registry_hash": self.registry.payload_hash,
            "challenge_registry_epoch": self.registry.payload["registry_epoch"],
            "challenge_registry_root_key_id": self.registry.payload["root_key_id"],
            "evidence_event_count": 1, "evidence_last_sequence": 1, "evidence_head_sequence": 1,
            "evidence_final_event_hash": event_hash,
        }
        sign_request = self._attest(evidence)
        try:
            signed = brops_socket.request(self.signer_socket, sign_request, timeout=30)
        except Exception:
            return self._refused(TURN_RESULT, "attestation_invalid", receipt_id=receipt_id)
        if signed.get("protocol") != SIGN_RESULT or signed.get("status") != "signed":
            reason = signed.get("reason", "malformed")
            return self._refused(TURN_RESULT, reason if reason in GOVERNED_REFUSAL_REASONS else "malformed", receipt_id=receipt_id)
        stream_id = b64url_encode(secrets.token_bytes(32))
        created = self.clock_ms()
        self.sweep_output_streams(created)
        # §4.10(f): a completing turn's stream is ALWAYS created. If admitting it would breach
        # the per-install row or byte quota, FIFO-evict the oldest present rows first.
        self._evict_output_streams_for_admission(install, len(output), created)
        result = {
            "protocol": TURN_RESULT, "status": "signed", "receipt_id": receipt_id,
            "output_stream_id": stream_id, "output_bytes": len(output), "output_sha256": output_handle,
            "envelope_jcs_b64": signed["envelope_jcs_b64"], "signature_b64": signed["signature_b64"],
            "key_id": signed["key_id"],
            "attestation_evidence_jcs_b64": signed["attestation_evidence_jcs_b64"],
            "attestation_signature_b64": signed["attestation_signature_b64"],
            "supervisor_attestation_key_id": signed["supervisor_attestation_key_id"],
            "containment_evidence_b64": b64url_encode(canonical_bytes(containment)),
            "run_id": challenge["run_id"], "execution_attempt_id": attempt, "lease_id": lease_id,
            "challenge_accepted_at_ms": signed["challenge_accepted_at_ms"],
            "challenge_handle": signed["challenge_handle"],
            "challenge_key_id": signed["challenge_key_id"],
            "challenge_registry_handle": signed["challenge_registry_handle"],
            "challenge_registry_hash": signed["challenge_registry_hash"],
            "challenge_registry_epoch": signed["challenge_registry_epoch"],
            "challenge_registry_root_key_id": signed["challenge_registry_root_key_id"],
            "lease_handle": signed["lease_handle"],
            "execution_receipt_handle": signed["execution_receipt_handle"],
            "evidence_event_count": signed["evidence_event_count"],
            "evidence_last_sequence": signed["evidence_last_sequence"],
            "evidence_head_sequence": signed["evidence_head_sequence"],
            "evidence_final_event_hash": signed["evidence_final_event_hash"],
        }
        with self.conn:
            self.conn.execute(
                """INSERT INTO governed_output_streams(
                   output_stream_id,receipt_id,execution_attempt_id,output_handle,output_bytes,
                   output_sha256,created_at_ms,expires_at_ms,retained_until_ms,install_id,tombstone)
                   VALUES(?,?,?,?,?,?,?,?,?,?,0)""",
                (stream_id, receipt_id, attempt, output_handle, len(output), output_handle,
                 created, created + OUTPUT_STREAM_TTL_MS,
                 created + OUTPUT_STREAM_TTL_MS + OUTPUT_STREAM_RETENTION_MS, install),
            )
            self.conn.execute(
                "UPDATE governed_turn_acceptance SET state='COMPLETED',result_json=?,"
                "terminal_record_handle=?,updated_at_ms=? WHERE challenge_handle=?",
                (canonical_bytes(result).decode("utf-8"), record_handle, created, handle),
            )
        return result

    def sweep_output_streams(self, now_ms: int | None = None) -> None:
        now = self.clock_ms() if now_ms is None else now_ms
        with self.conn:
            self.conn.execute(
                "UPDATE governed_output_streams SET tombstone=1 WHERE tombstone=0 AND expires_at_ms < ?",
                (now,),
            )
            self.conn.execute("DELETE FROM governed_output_streams WHERE retained_until_ms < ?", (now,))

    def _evict_output_streams_for_admission(self, install: str, new_bytes: int, now_ms: int) -> None:
        """§4.10(f) FIFO admission: evict oldest present rows (by created_at_ms) for this install
        until BOTH the row-count and byte quotas would hold after inserting one more stream of
        `new_bytes`. Eviction removes only the stream ROW; the content-addressed output bytes are
        never unlinked here (they persist under the store's own retention). A completing turn's
        stream is always admitted — if nothing is left to evict, insertion still proceeds."""
        while True:
            count, total = self.conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(output_bytes),0) FROM governed_output_streams "
                "WHERE install_id=? AND retained_until_ms>=?",
                (install, now_ms),
            ).fetchone()
            if (count + 1 <= MAX_OUTPUT_STREAM_ROWS_PER_INSTALL
                    and total + new_bytes <= MAX_OUTPUT_STREAM_BYTES_PER_INSTALL):
                return
            oldest = self.conn.execute(
                "SELECT output_stream_id FROM governed_output_streams "
                "WHERE install_id=? AND retained_until_ms>=? "
                "ORDER BY created_at_ms ASC, output_stream_id ASC LIMIT 1",
                (install, now_ms),
            ).fetchone()
            if oldest is None:
                return  # nothing left to evict; the completing turn's stream is still created
            with self.conn:
                self.conn.execute(
                    "DELETE FROM governed_output_streams WHERE output_stream_id=?", (oldest[0],)
                )

    @staticmethod
    def _output_error(stream_id, seq, reason):
        return {
            "protocol": OUTPUT_READ_RESULT, "ok": False,
            "output_stream_id": stream_id, "seq": seq, "bytes_b64": None,
            "eof": None, "error": {"reason": reason},
        }

    def output_read(self, frame: Mapping[str, Any]) -> dict[str, Any]:
        try:
            require_exact_keys(frame, {"protocol", "output_stream_id", "receipt_id", "execution_attempt_id", "seq"}, "output read")
            stream_id = frame["output_stream_id"]
            if not isinstance(stream_id, str) or len(stream_id) != 43:
                return self._output_error(None, None, "malformed")
            receipt_id = require_id(frame["receipt_id"], "receipt_id")
            attempt = require_id(frame["execution_attempt_id"], "execution_attempt_id")
            seq = frame["seq"]
            if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
                return self._output_error(stream_id, None, "malformed")
        except GovernedProtocolError:
            return self._output_error(None, None, "malformed")
        now = self.clock_ms(); self.sweep_output_streams(now)
        row = self.conn.execute("SELECT * FROM governed_output_streams WHERE output_stream_id=?", (stream_id,)).fetchone()
        if row is None:
            return self._output_error(stream_id, seq, "stream_unknown")
        if row["tombstone"] or now > row["expires_at_ms"]:
            return self._output_error(stream_id, seq, "stream_expired")
        if row["receipt_id"] != receipt_id or row["execution_attempt_id"] != attempt:
            return self._output_error(stream_id, seq, "stream_binding_mismatch")
        data = self.store.read(row["output_handle"])
        if len(data) != row["output_bytes"] or sha256_hex(data) != row["output_sha256"]:
            return self._output_error(stream_id, seq, "stream_unknown")
        if len(data) == 0:
            if seq != 0:
                return self._output_error(stream_id, seq, "seq_out_of_range")
            chunk = b""; eof = True
        else:
            start = seq * STAGING_CHUNK_BYTES
            if start >= len(data):
                return self._output_error(stream_id, seq, "seq_out_of_range")
            chunk = data[start:start + STAGING_CHUNK_BYTES]
            eof = start + len(chunk) >= len(data)
        return {
            "protocol": OUTPUT_READ_RESULT, "ok": True, "output_stream_id": stream_id,
            "seq": seq, "bytes_b64": b64url_encode(chunk), "eof": eof, "error": None,
        }


def load_supervisor_from_env(env: Mapping[str, str] | None = None) -> GovernedSupervisor:
    e = os.environ if env is None else env
    root_pubkeys = json.loads(pathlib.Path(e["BROPS_CHALLENGE_ROOTS_FILE"]).read_text("utf-8"))
    registry = ChallengeRegistry.load(e["BROPS_CHALLENGE_REGISTRY_FILE"], root_pubkeys)
    config = SupervisorConfig(
        workspace_id=e["BROPS_GOVERNED_WORKSPACE_ID"], install_id=e["BROPS_GOVERNED_INSTALL_ID"],
        supervisor_id=e["BROPS_GOVERNED_SUPERVISOR_ID"], executor_id=e["BROPS_GOVERNED_EXECUTOR_ID"],
        runner_id=e["BROPS_GOVERNED_RUNNER_ID"], agent_id=e.get("BROPS_GOVERNED_AGENT_ID", "Bro"),
        session_id=e.get("BROPS_GOVERNED_SESSION_ID", "brops-local-session"),
        policy_id=e["BROPS_EXPECTED_POLICY_ID"], policy_version=e["BROPS_EXPECTED_POLICY_VERSION"],
        policy_bundle=pathlib.Path(e["BROPS_POLICY_BUNDLE_FILE"]).read_bytes(),
        launcher_executable_sha256=e["BROPS_LAUNCHER_EXECUTABLE_SHA256"],
        executor_command=tuple(shlex.split(e["BROPS_GOVERNED_EXECUTOR_COMMAND"])),
        generation_config_allowlist=frozenset(x for x in e["BROPS_GOVERNED_EXECUTION_ALLOWLIST"].split(",") if x),
        record_dir=pathlib.Path(e["BROPS_GOVERNED_RECORD_DIR"]),
    )
    return GovernedSupervisor(
        db_path=e["BROPS_GOVERNED_DB"], store=EvidenceStore(e["BROPS_EVIDENCE_STORE_DIR"]),
        registry=registry, signer_socket=e["BROPS_SIGNER_SOCKET"],
        attestation_key=load_attestation_key(e["BROPS_SUPERVISOR_ATTESTATION_KEYDIR"]),
        lease_key=_key(e["BROPS_LEASE_ISSUER_KEYDIR"], "brops-governed-lease-issuer.json"),
        evidence_recorder_key=_key(e["BROPS_EVIDENCE_RECORDER_KEYDIR"], "brops-governed-evidence-recorder.json"),
        governed_turn_recorder_key=_key(e["BROPS_GOVERNED_TURN_RECORDER_KEYDIR"], "brops-governed-turn-recorder.json"),
        config=config,
    )
