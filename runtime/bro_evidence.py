"""Evidence chains that cannot be truncated.

`bro_completion.validate_evidence_chain` walks a caller-supplied list of event
ids and checks that each links back to its predecessor. That catches dropping
events from the front, because the first must have no predecessor. It does
nothing about the back.

So a builder holding genuinely signed events `e1, e2, e3(test-failed),
e4(rollback)` submits `["e1", "e2"]`. Every event verifies, every link matches,
and the chain is declared valid. The failure and its rollback are simply not
mentioned. No forgery is involved: it is selective disclosure of a true history.

The fix is an anchor. The evidence recorder signs a head for each task naming the
final event hash, the event count and the last sequence. A submitted chain must
reproduce that head exactly, so a prefix stops being a valid chain and becomes a
short one.

The anchor only works asymmetrically. Under HMAC the verifying key is the signing
key, and the hook verifying the head runs in the builder's own process, so the
builder would simply sign a head describing the prefix it wanted to present.
Ed25519 is what makes the head an authority the builder cannot mint. That is why
this module exists next to the older HMAC path rather than extending it.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass
from typing import Any

from bro_signature import SignatureError, canonical_bytes, verify_artifact
import hashlib

EVENT_FIELDS = {
    "artifact_type", "key_id", "event_id", "sequence", "previous_event_hash",
    "task_id", "event_type", "agent_id", "payload_hash", "issued_at_epoch",
}

HEAD_FIELDS = {
    "artifact_type", "key_id", "task_id", "final_event_hash", "event_count",
    "last_sequence", "issued_at_epoch",
}


class EvidenceError(Exception):
    pass


@dataclass(frozen=True)
class EvidenceHead:
    task_id: str
    final_event_hash: str
    event_count: int
    last_sequence: int


def event_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def _load(store: pathlib.Path, name: str) -> dict:
    try:
        return json.loads((store / name).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EvidenceError(f"evidence artifact not found: {name}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"cannot read evidence artifact {name}: {exc}") from exc


def load_head(store: pathlib.Path, task_id: str, keys: dict,
              *, now: int | None = None) -> EvidenceHead:
    """Load the signed head for a task.

    A missing head is a hard failure, not an empty chain. Treating it as optional
    would hand back the truncation it exists to prevent: omit the head, omit the
    events you dislike.
    """
    document = _load(store, f"{task_id}.head.json")
    try:
        payload = verify_artifact(document, "evidence-head", keys, now=now)
    except SignatureError as exc:
        raise EvidenceError(f"evidence head signature RED: {exc}") from exc
    if set(payload) != HEAD_FIELDS:
        raise EvidenceError(f"evidence head has unexpected shape: {sorted(payload)}")
    if payload["task_id"] != task_id:
        raise EvidenceError("evidence head belongs to a different task")
    for field in ("event_count", "last_sequence"):
        if not isinstance(payload[field], int) or payload[field] < 1:
            raise EvidenceError(f"evidence head {field} must be a positive integer")
    if not isinstance(payload["final_event_hash"], str) or len(payload["final_event_hash"]) != 64:
        raise EvidenceError("evidence head final_event_hash must be a sha256 digest")
    return EvidenceHead(task_id, payload["final_event_hash"],
                        payload["event_count"], payload["last_sequence"])


def validate_chain(task_id: str, event_ids: list[str], keys: dict, *,
                   store: pathlib.Path, now: int | None = None) -> str:
    """Verify a chain and prove it is the whole chain.

    Returns the final event hash. Raises if the submitted list is a prefix, is
    reordered, skips a sequence, or ends anywhere but the signed head.
    """
    if not event_ids:
        raise EvidenceError("evidence chain is empty")
    if len(event_ids) != len(set(event_ids)):
        raise EvidenceError("evidence event ids must be unique")

    head = load_head(store, task_id, keys, now=now)

    previous = None
    digest = ""
    for index, event_id in enumerate(event_ids, start=1):
        try:
            payload = verify_artifact(_load(store, f"{event_id}.json"),
                                      "evidence-event", keys, now=now)
        except SignatureError as exc:
            raise EvidenceError(f"evidence event {event_id} RED: {exc}") from exc
        if set(payload) != EVENT_FIELDS:
            raise EvidenceError(f"evidence event {event_id} has unexpected shape")
        if payload["event_id"] != event_id or payload["task_id"] != task_id:
            raise EvidenceError(f"evidence event {event_id} binding mismatch")
        if payload["sequence"] != index:
            raise EvidenceError(
                f"evidence event {event_id} claims sequence {payload['sequence']} "
                f"at position {index}; the chain is reordered or has a gap")
        if payload["previous_event_hash"] != previous:
            raise EvidenceError(f"evidence chain linkage mismatch at {event_id}")
        digest = event_hash(payload)
        previous = digest

    if len(event_ids) != head.event_count:
        raise EvidenceError(
            f"evidence chain is incomplete: {len(event_ids)} events submitted, "
            f"the signed head records {head.event_count}")
    if head.last_sequence != len(event_ids):
        raise EvidenceError("evidence head last_sequence disagrees with its own count")
    if digest != head.final_event_hash:
        raise EvidenceError(
            "evidence chain does not end at the signed head; a valid prefix is "
            "not a valid chain")
    return digest


def validate_criterion_evidence(task_id: str, criterion_event_ids: list[str],
                                chain_event_ids: list[str]) -> None:
    """Every id a criterion cites must be in the validated chain.

    Without this a criterion cites an event that exists, is signed, and belongs
    to some other chain the completion never proved.
    """
    unknown = sorted(set(criterion_event_ids) - set(chain_event_ids))
    if unknown:
        raise EvidenceError(
            f"criterion cites evidence outside the validated chain: {unknown}")
