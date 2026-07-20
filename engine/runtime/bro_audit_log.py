"""Append-only, hash-chained audit ledger (Execution Surface kind=recorder).

P3 auditability: a human-readable JSONL ledger that sits BESIDE the cryptographic
marker mechanisms (nonce/lease/release), never replacing them. Every record links
to the previous by hash; a sidecar head file records the count and last hash so a
tail truncation is detectable, not just mid-chain tampering.

Machine-local by contract: the ledger path is supplied by the caller and MUST live
outside the repository (enforced here) so task-specific / sensitive runtime state is
never committed to Git. All payload strings are secret-redacted before they are
written (composes with L15).

The hash chain alone cannot resist the party that writes the ledger: whoever can
append can also drop records, recompute the chain and rewrite the plaintext
``.head`` sidecar, and an unkeyed ``verify()`` stays green. The authority against
that forger is an Ed25519 head ANCHOR, mirroring how ``bro_evidence`` anchors its
``evidence-head``: an external recorder/operator signs a payload naming the ledger,
its record count and its tail hash, and ``verify(path, keys=...)`` refuses any chain
that does not reproduce that signed head exactly. This module only ever VERIFIES —
it holds no private key and cannot sign (an enforcement point that could sign is an
enforcement point that could forge), so anchoring happens out-of-band via
``head_anchor_payload`` + ``attach_head_anchor``.

Pure standard library on the append hot path; signature verification lazily imports
``bro_signature`` only when a caller supplies trusted keys.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import time

from bro_secrets import redact_mapping

GENESIS = "0" * 64
# The anchor's artifact type is deliberately NOT a bro_signature.ARTIFACT_AUTHORITY
# type: verify_artifact rejects unknown artifact types and checks the payload's own
# artifact_type field, so a signed audit head can never be replayed as a registry
# artifact (lease, receipt, evidence head, ...) and no registry artifact can be
# presented as an audit head.
ANCHOR_ARTIFACT_TYPE = "audit-head"
# Authorities whose keys may anchor an audit head: the evidence recorder (the same
# external authority that anchors evidence chains) or the offline operator. The
# builder/writer of the ledger holds neither.
ANCHOR_AUTHORITIES = ("evidence-recorder", "operator-root")
# Bound on how long a writer waits for the exclusive append lock before failing
# closed. Appends are short (read tail, hash, append one line, replace head), so a
# wait longer than this means a crashed or wedged holder — surfaced, never ignored.
_LOCK_TIMEOUT = 10.0
_LOCK_POLL = 0.01


class AuditError(ValueError):
    """Raised on a broken/tampered/truncated audit chain (fail-closed)."""


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _record_hash(prev_hash: str, body: dict) -> str:
    return hashlib.sha256((prev_hash + _canonical(body)).encode("utf-8")).hexdigest()


def _head_path(path: pathlib.Path) -> pathlib.Path:
    return path.with_suffix(path.suffix + ".head")


def _lock_path(path: pathlib.Path) -> pathlib.Path:
    return path.with_suffix(path.suffix + ".lock")


def _anchor_path(path: pathlib.Path) -> pathlib.Path:
    return path.with_suffix(path.suffix + ".head.sig")


def _acquire_lock(path: pathlib.Path) -> int:
    """Take an exclusive, cross-process append lock via an O_EXCL lock file.

    O_CREAT|O_EXCL is atomic on POSIX and Windows alike, so exactly one writer holds
    the lock at a time — the ledger's read-modify-write (compute seq/prev_hash from
    the tail, append, replace head) can never interleave and fork the chain. A holder
    that crashes leaves the lock file behind; the next writer waits out the bounded
    timeout and then fails closed, which is the audit ledger's contract."""
    lock = _lock_path(path)
    deadline = time.monotonic() + _LOCK_TIMEOUT
    while True:
        try:
            return os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass  # another writer holds the lock
        except PermissionError:
            # Windows raises PermissionError (not FileExistsError) when the lock file is
            # in the delete-pending window between a releaser's close and its unlink;
            # that is simply "held right now", so retry rather than propagate. A
            # genuinely unwritable directory still resolves to the bounded AuditError.
            pass
        if time.monotonic() >= deadline:
            raise AuditError(f"audit ledger lock not acquired within {_LOCK_TIMEOUT}s: {lock}")
        time.sleep(_LOCK_POLL)


def _release_lock(fd: int, path: pathlib.Path) -> None:
    try:
        os.close(fd)
    finally:
        try:
            os.unlink(_lock_path(path))
        except OSError:
            pass


def _assert_external(path: pathlib.Path, root: pathlib.Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return
    raise AuditError(f"audit ledger must live outside the repository: {path}")


def read_all(path: pathlib.Path) -> list[dict]:
    p = pathlib.Path(path)
    if not p.exists():
        return []
    records = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                # A corrupt line is a broken ledger; verify() documents AuditError, so
                # a tampered record must not surface as a raw JSONDecodeError callers
                # that catch only AuditError would miss.
                raise AuditError(f"unparsable audit record: {exc}") from exc
    return records


def append(path, kind: str, payload: dict, *, repo_root: pathlib.Path | None = None) -> dict:
    p = pathlib.Path(path)
    if repo_root is not None:
        _assert_external(p, repo_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    # The whole read-modify-write is one critical section: two writers that both read
    # the tail before either appended would compute the same seq/prev_hash and fork
    # the chain. The lock serialises them; the tail is re-read inside it.
    lock_fd = _acquire_lock(p)
    try:
        existing = read_all(p)
        prev_hash = existing[-1]["hash"] if existing else GENESIS
        seq = existing[-1]["seq"] + 1 if existing else 0
        body = {"seq": seq, "prev_hash": prev_hash, "kind": kind, "payload": redact_mapping(payload)}
        record = dict(body)
        record["hash"] = _record_hash(prev_hash, body)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        # Replace the head atomically so a crash mid-write can never leave a torn head
        # that verify() would read as a truncation.
        head = _head_path(p)
        tmp = head.with_suffix(head.suffix + ".tmp")
        tmp.write_text(json.dumps({"count": seq + 1, "last_hash": record["hash"]}), encoding="utf-8")
        os.replace(tmp, head)
        return record
    finally:
        _release_lock(lock_fd, p)


def verify_signed_payload(document, artifact_type: str, keys: dict, *,
                          authorities, now: int | None = None) -> dict:
    """Verify an out-of-registry signed document against the trusted key registry.

    ``keys`` is the registry loaded by ``bro_signature.load_trusted_keys`` (anchored
    to the external operator pin); the raw signature check is
    ``bro_signature.verify_detached`` itself. Key policy mirrors
    ``bro_signature.verify_artifact`` — known key id, active status, validity
    window — with the artifact binding enforced by ``authorities`` (the artifact
    types here are intentionally unknown to the registry, so per-key
    ``allowed_artifact_types`` cannot name them; the authority type carries the
    binding instead). Raises AuditError; never returns an unverified payload.
    """
    # Lazy import: the append hot path stays pure standard library; only a caller
    # that supplies trusted keys pays for the cryptography dependency.
    from bro_signature import SignatureError, verify_detached

    if not isinstance(document, dict) or set(document) != {"payload", "signature"}:
        raise AuditError(f"signed {artifact_type} must contain payload and signature only")
    payload = document["payload"]
    if not isinstance(payload, dict):
        raise AuditError(f"signed {artifact_type} payload must be an object")
    if payload.get("artifact_type") != artifact_type:
        raise AuditError(
            f"document claims to be {payload.get('artifact_type')!r} but was "
            f"verified as {artifact_type!r}")
    key_id = payload.get("key_id")
    if not isinstance(key_id, str) or key_id not in keys:
        raise AuditError(f"unknown signing key: {key_id!r}")
    key = keys[key_id]
    if key.status != "active":
        raise AuditError(f"key {key_id} is {key.status}")
    if key.authority_type not in authorities:
        raise AuditError(
            f"key {key_id} ({key.authority_type}) may not sign {artifact_type}; "
            f"requires one of {sorted(authorities)}")
    moment = int(time.time()) if now is None else now
    if moment < key.not_before_epoch:
        raise AuditError(f"key {key_id} is not valid yet")
    if moment >= key.not_after_epoch:
        raise AuditError(f"key {key_id} expired at {key.not_after_epoch}")
    try:
        verify_detached(payload, document["signature"], key.public_key)
    except SignatureError as exc:
        raise AuditError(f"signed {artifact_type} signature RED: {exc}") from exc
    return payload


def head_anchor_payload(path, *, key_id: str, now: int) -> dict:
    """Build the audit-head payload an EXTERNAL recorder/operator signs.

    This module never signs — the returned payload leaves the process, is signed by
    the recorder/operator authority out-of-band, and comes back through
    ``attach_head_anchor``. The chain is structurally verified first so an anchor is
    never minted over an already-broken ledger.
    """
    p = pathlib.Path(path)
    count = verify(p)
    records = read_all(p)
    return {
        "artifact_type": ANCHOR_ARTIFACT_TYPE,
        "key_id": key_id,
        "ledger": p.name,
        "count": count,
        "last_hash": records[-1]["hash"] if records else GENESIS,
        "issued_at_epoch": int(now),
    }


def attach_head_anchor(path, document: dict, keys: dict, *, now: int | None = None) -> dict:
    """Install a signed head anchor beside the ledger, verifying it first.

    The document must verify against the trusted registry AND describe the ledger's
    current chain exactly — a stale or foreign anchor is refused rather than stored.
    """
    p = pathlib.Path(path)
    payload = verify_signed_payload(document, ANCHOR_ARTIFACT_TYPE, keys,
                                    authorities=ANCHOR_AUTHORITIES, now=now)
    _check_anchor_against_chain(p, payload)
    anchor = _anchor_path(p)
    tmp = anchor.with_suffix(anchor.suffix + ".tmp")
    tmp.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    os.replace(tmp, anchor)
    return payload


def _check_anchor_against_chain(p: pathlib.Path, payload: dict) -> None:
    records = read_all(p)
    if payload.get("ledger") != p.name:
        raise AuditError("audit head anchor names a different ledger")
    if payload.get("count") != len(records):
        raise AuditError("audit head anchor count disagrees with chain length")
    tail = records[-1]["hash"] if records else GENESIS
    if payload.get("last_hash") != tail:
        raise AuditError("audit head anchor hash disagrees with chain tail")


def verify(path, *, keys: dict | None = None, now: int | None = None) -> int:
    """Walk the chain, proving linkage, hashes and (via the head) no tail truncation.

    With ``keys`` (the operator-pinned trusted key registry) the check is
    authoritative: a signed head anchor from the recorder/operator authority is
    REQUIRED and the chain must reproduce it exactly, so a writer that drops
    records, recomputes the chain and rewrites the plaintext ``.head`` still fails
    (it cannot re-sign the anchor). Without ``keys`` the check is structural only —
    sufficient against corruption, not against the ledger's own writer.

    Returns the record count. Raises AuditError on any break.
    """
    p = pathlib.Path(path)
    records = read_all(p)
    prev_hash = GENESIS
    for i, rec in enumerate(records):
        if rec.get("seq") != i:
            raise AuditError(f"audit ledger sequence break at index {i}")
        if rec.get("prev_hash") != prev_hash:
            raise AuditError(f"audit ledger linkage break at seq {i}")
        body = {k: rec[k] for k in ("seq", "prev_hash", "kind", "payload")}
        if _record_hash(prev_hash, body) != rec.get("hash"):
            raise AuditError(f"audit ledger record tampered at seq {i}")
        prev_hash = rec["hash"]
    head_file = _head_path(p)
    if head_file.exists():
        head = json.loads(head_file.read_text(encoding="utf-8"))
        if head.get("count") != len(records):
            raise AuditError("audit ledger truncated: head count disagrees with chain length")
        if head.get("last_hash") != (records[-1]["hash"] if records else GENESIS):
            raise AuditError("audit ledger truncated: head hash disagrees with chain tail")
    elif records:
        raise AuditError("audit ledger has records but no head anchor")
    if keys is not None:
        anchor_file = _anchor_path(p)
        if not anchor_file.exists():
            if records:
                raise AuditError(
                    "audit ledger has no signed head anchor; a self-hashed head "
                    "cannot resist the party that writes the log")
            return 0
        try:
            document = json.loads(anchor_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AuditError(f"unreadable audit head anchor: {exc}") from exc
        payload = verify_signed_payload(document, ANCHOR_ARTIFACT_TYPE, keys,
                                        authorities=ANCHOR_AUTHORITIES, now=now)
        _check_anchor_against_chain(p, payload)
    return len(records)
