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
import pathlib

from bro_secrets import redact_mapping

GENESIS = "0" * 64


class AuditError(ValueError):
    """Raised on a broken/tampered/truncated audit chain (fail-closed)."""


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _record_hash(prev_hash: str, body: dict) -> str:
    return hashlib.sha256((prev_hash + _canonical(body)).encode("utf-8")).hexdigest()


def _head_path(path: pathlib.Path) -> pathlib.Path:
    return path.with_suffix(path.suffix + ".head")


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
            records.append(json.loads(line))
    return records


def append(path, kind: str, payload: dict, *, repo_root: pathlib.Path | None = None) -> dict:
    p = pathlib.Path(path)
    if repo_root is not None:
        _assert_external(p, repo_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = read_all(p)
    prev_hash = existing[-1]["hash"] if existing else GENESIS
    seq = existing[-1]["seq"] + 1 if existing else 0
    body = {"seq": seq, "prev_hash": prev_hash, "kind": kind, "payload": redact_mapping(payload)}
    record = dict(body)
    record["hash"] = _record_hash(prev_hash, body)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
    _head_path(p).write_text(json.dumps({"count": seq + 1, "last_hash": record["hash"]}), encoding="utf-8")
    return record


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
