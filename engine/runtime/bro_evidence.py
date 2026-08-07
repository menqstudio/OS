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

One anchor is not enough against rollback: a builder who RETAINS an older signed
head (and the matching event prefix) presents a self-consistent truncated chain.
Each head therefore carries a strictly increasing ``head_sequence``; callers pass
their high-water mark (``min_head_sequence``, e.g. the sequence bound into the
signed completion manifest — that binding lives with the completion gate) and a
genuinely signed but older head is rejected as stale.
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
    "last_sequence", "head_sequence", "issued_at_epoch",
}


class EvidenceError(Exception):
    pass


@dataclass(frozen=True)
class EvidenceHead:
    task_id: str
    final_event_hash: str
    event_count: int
    last_sequence: int
    # Strictly increasing per re-anchoring of a task's chain. A signed head proves
    # the submitted events reproduce THAT head; head_sequence is what lets a
    # verifier holding a high-water mark reject an OLDER signed head that would
    # bless a self-consistent truncated chain (the recorder bumps it every time it
    # re-signs, so a retained stale head always carries a lower number).
    head_sequence: int


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
              *, now: int | None = None,
              min_head_sequence: int | None = None) -> EvidenceHead:
    """Load the signed head for a task.

    A missing head is a hard failure, not an empty chain. Treating it as optional
    would hand back the truncation it exists to prevent: omit the head, omit the
    events you dislike.

    ``min_head_sequence`` is the caller's high-water mark (e.g. the head sequence
    bound into a signed completion manifest): a genuinely signed but OLDER head is
    rejected, closing the rollback where a retained stale head plus its matching
    event prefix verifies as a complete chain.
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
    for field in ("event_count", "last_sequence", "head_sequence"):
        if not isinstance(payload[field], int) or payload[field] < 1:
            raise EvidenceError(f"evidence head {field} must be a positive integer")
    if not isinstance(payload["final_event_hash"], str) or len(payload["final_event_hash"]) != 64:
        raise EvidenceError("evidence head final_event_hash must be a sha256 digest")
    if min_head_sequence is not None and payload["head_sequence"] < min_head_sequence:
        raise EvidenceError(
            f"evidence head is stale: head_sequence {payload['head_sequence']} is "
            f"below the required high-water mark {min_head_sequence}; an older "
            "signed head cannot anchor the current chain")
    return EvidenceHead(task_id, payload["final_event_hash"],
                        payload["event_count"], payload["last_sequence"],
                        payload["head_sequence"])


def validate_chain(task_id: str, event_ids: list[str], keys: dict, *,
                   store: pathlib.Path, now: int | None = None,
                   min_head_sequence: int | None = None) -> str:
    """Verify a chain and prove it is the whole chain.

    Returns the final event hash. Raises if the submitted list is a prefix, is
    reordered, skips a sequence, ends anywhere but the signed head, or (with
    ``min_head_sequence``) is anchored by a head older than the caller's
    high-water mark.
    """
    if not event_ids:
        raise EvidenceError("evidence chain is empty")
    if len(event_ids) != len(set(event_ids)):
        raise EvidenceError("evidence event ids must be unique")

    head = load_head(store, task_id, keys, now=now,
                     min_head_sequence=min_head_sequence)

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


# --------------------------------------------------------------------------- #
# Enumeration — the read path a viewer needs and a verifier never did.
#
# Everything above is caller-driven: `validate_chain` is handed the ids to check,
# because the completion gate always receives them in a signed manifest. A read-only
# governance surface has no manifest: it must ask the store what is there. That is a
# genuinely different question, and answering it carelessly would reintroduce exactly
# the truncation the anchor exists to prevent — an enumerator that returns whatever
# files it managed to parse hands back a prefix the moment a file goes missing.
#
# So enumeration here only ever DISCOVERS candidate ids; the ids are then put through
# `validate_chain`, which re-derives the linkage and requires the chain to reproduce
# the signed head. A read that cannot be anchored raises rather than returning a
# shorter, plausible history.
# --------------------------------------------------------------------------- #

_HEAD_SUFFIX = ".head.json"


def _store_files(store: pathlib.Path) -> list[pathlib.Path]:
    try:
        return sorted(p for p in pathlib.Path(store).iterdir()
                      if p.is_file() and p.name.endswith(".json"))
    except OSError as exc:
        raise EvidenceError(f"evidence store is unreadable: {exc}") from exc


def list_chain_task_ids(store: pathlib.Path) -> list[str]:
    """Task ids that have a signed head file in ``store``.

    Discovery only. Presence here proves nothing about a chain, and absence proves
    nothing about a task — a deleted head is precisely what an anchor exists to catch.
    `read_chain` is what decides; this only says where to look.
    """
    return sorted({
        p.name[: -len(_HEAD_SUFFIX)]
        for p in _store_files(store)
        if p.name.endswith(_HEAD_SUFFIX) and len(p.name) > len(_HEAD_SUFFIX)
    })


def _scan_events(store: pathlib.Path, keys: dict, wanted: set[str],
                 now: int | None) -> dict[str, list[tuple[int, dict[str, Any]]]]:
    """One pass over the store, collecting verified events for ``wanted`` tasks.

    The store is a flat directory shared with other signed artifacts (heads, execution
    receipts), so this cannot simply verify everything it finds. A file is treated as
    part of a chain only when its payload *claims* to be an ``evidence-event``; a file
    that claims that and then fails verification is a hard error, never a silently
    skipped record — silent skipping is truncation with extra steps.
    """
    found: dict[str, list[tuple[int, dict[str, Any]]]] = {task: [] for task in wanted}
    for path in _store_files(store):
        if path.name.endswith(_HEAD_SUFFIX):
            continue
        document = _load(store, path.name)
        claimed = document.get("payload") if isinstance(document, dict) else None
        if not isinstance(claimed, dict) or claimed.get("artifact_type") != "evidence-event":
            continue  # another signed artifact sharing the directory
        if claimed.get("task_id") not in wanted:
            continue
        try:
            payload = verify_artifact(document, "evidence-event", keys, now=now)
        except SignatureError as exc:
            raise EvidenceError(f"evidence event in {path.name} RED: {exc}") from exc
        if set(payload) != EVENT_FIELDS:
            raise EvidenceError(f"evidence event in {path.name} has unexpected shape")
        sequence = payload["sequence"]
        if not isinstance(sequence, int) or sequence < 1:
            raise EvidenceError(
                f"evidence event {payload['event_id']!r} has a non-positive sequence")
        # The claimed task id is only a routing hint until the signature is checked;
        # bucket on the VERIFIED one so an unsigned claim cannot move an event.
        found.setdefault(payload["task_id"], []).append((sequence, payload))
    return found


def read_chains(store: pathlib.Path, task_ids: list[str], keys: dict, *,
                now: int | None = None,
                min_head_sequence: int | None = None) -> dict[str, list[dict[str, Any]]]:
    """Read several whole chains with a SINGLE pass over the store.

    A governance page asks for every chain at once, and scanning the directory once
    per task turns a page load into quadratic work over a store that also holds every
    execution receipt. The per-chain guarantees are unchanged — each chain still has
    to reproduce its own signed head.
    """
    directory = pathlib.Path(store)
    ordered_ids = list(dict.fromkeys(task_ids))
    scanned = _scan_events(directory, keys, set(ordered_ids), now)
    chains: dict[str, list[dict[str, Any]]] = {}
    for task_id in ordered_ids:
        events = scanned.get(task_id, [])
        head_path = directory / f"{task_id}{_HEAD_SUFFIX}"
        if not events and not head_path.exists():
            chains[task_id] = []  # the honestly empty chain: no anchor, no events
            continue
        if not head_path.exists():
            raise EvidenceError(
                f"the evidence store holds {len(events)} event(s) for {task_id} but no "
                "signed head; an unanchored chain cannot be shown to be complete")
        events.sort(key=lambda item: item[0])
        ordered = [payload for _sequence, payload in events]
        # The authority, not the enumeration: re-derives every link and requires the
        # chain to end exactly at the signed head, with the head's own event count.
        validate_chain(task_id, [payload["event_id"] for payload in ordered], keys,
                       store=directory, now=now, min_head_sequence=min_head_sequence)
        chains[task_id] = ordered
    return chains


def read_chain(store: pathlib.Path, task_id: str, keys: dict, *,
               now: int | None = None,
               min_head_sequence: int | None = None) -> list[dict[str, Any]]:
    """Return one task's whole verified evidence chain, in sequence order.

    Returns ``[]`` only for the honestly empty case: no anchor and no events. Events
    without an anchor raise, because an unanchored set cannot be shown to be whole; so
    does an anchor whose events do not reproduce it (see ``validate_chain``).
    """
    return read_chains(store, [task_id], keys, now=now,
                       min_head_sequence=min_head_sequence)[task_id]
