"""Append-only, hash-chained audit ledger (Execution Surface kind=recorder).

P3 auditability: a human-readable JSONL ledger that sits BESIDE the cryptographic
marker mechanisms (nonce/lease/release), never replacing them. Every record links
to the previous by hash; a sidecar head file records the count and last hash so a
tail truncation is detectable, not just mid-chain tampering.

Machine-local by contract: the ledger path is supplied by the caller and MUST live
outside the repository (enforced here) so task-specific / sensitive runtime state is
never committed to Git. All payload strings are secret-redacted before they are
written (composes with L15).

Pure standard library.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import time

from bro_secrets import redact_mapping

GENESIS = "0" * 64
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


def verify(path) -> int:
    """Walk the chain, proving linkage, hashes and (via the head) no tail truncation.

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
    return len(records)
