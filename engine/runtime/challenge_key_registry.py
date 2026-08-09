"""The supervisor's OWN challenge-key registry — rev-30 §4.2, artifact #2.

Why this module exists at all
-----------------------------
``brops.governed-turn-open.v1`` (§4.10(a0)) has to answer one question before it will
admit a turn: *is the key that signed this challenge a key I currently accept, and was it
valid at the moment the challenge was issued?* The design is emphatic that the answer may
not travel with the challenge — "the registry is NEVER supplied by the sidecar". So the
registry is resolved from the supervisor's own state, verified under a **binary-pinned
root anchor**, and only then consulted.

Before this module the tree had no registry document at all. ``SupervisorConfig`` carried
four registry *scalars* (``challenge_registry_handle``/``_hash``/``_epoch``/
``_root_key_id``) that were copied into acceptance rows as provenance and never checked
against anything — in the live kit ``challenge_registry_handle`` is literally
``sha256(pub_hex)``. Provenance recorded is not authority exercised, so the two §4.10(a0)
refusals that depend on the registry (``registry_unknown``, ``key_invalid``) had nothing
behind them. This module is that "behind".

What is enforced here, and what is not
--------------------------------------
Enforced, fail-closed, in this order:

  1. **Shape.** The exact §4.2 key set on the document and on every entry;
     ``additionalProperties:false`` in both directions (missing OR extra ⇒ refuse);
     ``keys`` length ≤ 256; the serialized document ≤ 256 KiB; duplicate
     ``challenge_key_id`` entries refused.
  2. **The revocation invariant (P1-3).** ``revoked == false`` ⇒ ``revoked_at_ms`` MUST be
     ``null``; ``revoked == true`` ⇒ ``revoked_at_ms`` MUST be an integer in the canonical
     ms range **and** ``>= valid_from_ms``. A schema that cannot REPRESENT a revoked key
     cannot revoke one, and a schema that lets the two fields disagree lets a revoked key
     read as live.
  3. **Root authority.** ``root_key_id`` must equal the pinned anchor's id, and
     ``root_sig`` must verify over ``JCS(payload)`` under the anchor's public key. An
     unknown root is refused rather than trusted-on-first-use.
  4. **Epoch floor (anti-rollback).** ``registry_epoch`` must be ``>=`` the supervisor's
     stored floor, so a resurrected older snapshot — which is exactly how a revoked key
     comes back to life — is refused.
  5. **As-of-time key selection.** A key is usable at ``t`` iff ``valid_from_ms <= t <=
     valid_to_ms`` (inclusive both ends, §1) and ``revoked_at_ms IS NULL OR revoked_at_ms
     > t``.

NOT enforced here, deliberately:

  * **The signature algorithm.** Verification is an injected seam
    (``verify_root_sig(message, sig, public_key) -> bool``), exactly as
    ``governed_supervisor.accept_open`` takes ``verify_sig``. The pure core stays
    stdlib-only and testable without key material; a seam that raises is contained and
    becomes a refusal, never an exception escaping into the protocol.
  * **Which ``t`` to ask about.** §4.10(a0) checks validity as of
    ``challenge_issued_at_ms``; §5/§7 re-check the FULL window as of
    ``challenge_accepted_at_ms``. Those are different predicates at different times and
    this module refuses to pick one for its caller — it takes ``as_of_ms``.

Only the Python standard library is used.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants (§4.2, LOCKED literals)
# ---------------------------------------------------------------------------

#: The ``artifact_type`` discriminator. A document without EXACTLY this value is not a
#: registry, whatever else it looks like.
REGISTRY_ARTIFACT_TYPE = "brops.challenge-key-registry.v1"

#: §4.2 "``keys`` length ≤ 256".
MAX_REGISTRY_KEYS = 256

#: §4.2 "the full registry document ≤ 256 KiB".
MAX_REGISTRY_DOC_BYTES = 256 * 1024

#: §2.1/§4.1 "all ids ≤ 128".
MAX_ID_LEN = 128

#: §4.2 "``public_key``: b64url 32B → 43 chars".
PUBLIC_KEY_CHARS = 43

_B64URL_ALPHABET = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)

#: The exhaustive §4.2 document / payload / key-entry shapes.
REGISTRY_DOC_FIELDS: Tuple[str, ...] = ("payload", "root_sig")
REGISTRY_PAYLOAD_FIELDS: Tuple[str, ...] = (
    "artifact_type",
    "root_key_id",
    "registry_epoch",
    "registry_issued_at_ms",
    "keys",
)
REGISTRY_KEY_FIELDS: Tuple[str, ...] = (
    "challenge_key_id",
    "public_key",
    "valid_from_ms",
    "valid_to_ms",
    "key_epoch",
    "revoked",
    "revoked_at_ms",
)

# ---------------------------------------------------------------------------
# Typed outcomes. These are the §4.10(a0) refusal reasons, produced HERE so the
# protocol layer relays a verdict rather than inventing one.
# ---------------------------------------------------------------------------

#: No usable registry: unresolvable, malformed, wrong root, bad root signature, below the
#: epoch floor, or naming no such ``challenge_key_id``. All one reason on the wire (§4.10(a0)
#: names exactly ``registry_unknown``), because distinguishing them for the caller would tell
#: an untrusted sidecar which half of the supervisor's own state it had probed.
REGISTRY_UNKNOWN = "registry_unknown"

#: The key EXISTS in the accepted snapshot but was not usable at ``as_of_ms`` — outside its
#: validity window, or revoked at or before that instant.
KEY_INVALID = "key_invalid"


class RegistryError(Exception):
    """A supervisor-side fault (a non-callable seam, a non-int floor). Distinct from a
    refusal: a refusal is a verdict about the caller's document, this is a broken
    deployment, and conflating them would let a misconfigured supervisor look like a
    hostile peer."""


@dataclass(frozen=True)
class RootAnchor:
    """The binary-pinned challenge-root (§4.2: "a root_key_id selects a binary-pinned
    challenge-root anchor baked into the supervisor config; an unknown root is refused").

    It is a value, not a lookup: there is no registry-supplied way to introduce a new root,
    which is the property that stops a forged registry from certifying itself.
    """

    root_key_id: str
    public_key: str

    def __post_init__(self) -> None:
        if not _bounded_id(self.root_key_id):
            raise RegistryError("root anchor root_key_id must be a 1..128 char string")
        if not _is_b64url_public_key(self.public_key):
            raise RegistryError("root anchor public_key must be 43 base64url chars")


@dataclass(frozen=True)
class ChallengeKey:
    """One accepted, root-signed key entry — the object §4.10(a0) verifies a challenge
    signature under."""

    challenge_key_id: str
    public_key: str
    valid_from_ms: int
    valid_to_ms: int
    key_epoch: int
    revoked: bool
    revoked_at_ms: Optional[int]


@dataclass(frozen=True)
class RegistrySnapshot:
    """A verified registry: the root signature checked, the epoch floor cleared, every
    entry shape- and invariant-checked.

    ``registry_hash`` (``SHA256(JCS(payload))``) and ``registry_handle``
    (``SHA256(JCS({payload, root_sig}))``) are the two DISTINCT digests §4.2 requires: the
    first is the fork/epoch identity used for anti-rollback, the second addresses the exact
    stored document bytes. Computing only one and using it for both is the protected-store
    defect §4.2 names explicitly, so both are carried.
    """

    root_key_id: str
    registry_epoch: int
    registry_issued_at_ms: int
    keys: Tuple[ChallengeKey, ...]
    registry_hash: str
    registry_handle: str

    def key(self, challenge_key_id: Any) -> Optional[ChallengeKey]:
        for entry in self.keys:
            if entry.challenge_key_id == challenge_key_id:
                return entry
        return None


# ---------------------------------------------------------------------------
# Small validators (shape-compatible with governed_supervisor / the ledger).
# ---------------------------------------------------------------------------


def _is_ms(value: Any) -> bool:
    # §1: "JSON integer, 1 <= v <= 2^53-1 (fits an f64/i64 both sides; overflow/negative
    # rejected)". Zero is out of range too — the design's lower bound is 1, not 0.
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 2 ** 53 - 1


def _is_epoch(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 2 ** 53 - 1


def _bounded_id(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= MAX_ID_LEN


def _is_b64url_public_key(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != PUBLIC_KEY_CHARS:
        return False
    return all(c in _B64URL_ALPHABET for c in value)


def canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    """The governed family's deterministic encoding — byte-identical to
    ``governed_supervisor._canonical_bytes`` and ``challenge_authority._canonical_bytes``.

    It is that encoding and NOT ``bro_signature.canonical_bytes`` on purpose: the governed
    chain's signatures are produced over THIS encoding end to end, and a verifier that
    canonicalizes differently from the signer verifies nothing. (The two differ only in
    ``ensure_ascii``; see the note in ``governed_turn_open`` where the difference is
    resolved by requiring BOTH to agree.)
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Document validation (pure — no signature, no clock)
# ---------------------------------------------------------------------------


def _exact_keys(obj: Mapping[str, Any], allowed: Tuple[str, ...], what: str) -> None:
    keys = set(obj.keys())
    extra = keys - set(allowed)
    if extra:
        raise _Reject("%s has unexpected field(s) %s" % (what, sorted(extra)))
    missing = set(allowed) - keys
    if missing:
        raise _Reject("%s is missing field(s) %s" % (what, sorted(missing)))


class _Reject(Exception):
    """Internal: a shape/invariant violation, converted to ``registry_unknown``."""


def _validate_key_entry(entry: Any, index: int) -> ChallengeKey:
    if not isinstance(entry, Mapping):
        raise _Reject("keys[%d] must be an object" % index)
    _exact_keys(entry, REGISTRY_KEY_FIELDS, "keys[%d]" % index)

    if not _bounded_id(entry["challenge_key_id"]):
        raise _Reject("keys[%d].challenge_key_id must be a 1..128 char string" % index)
    if not _is_b64url_public_key(entry["public_key"]):
        raise _Reject("keys[%d].public_key must be 43 base64url chars" % index)
    for field in ("valid_from_ms", "valid_to_ms"):
        if not _is_ms(entry[field]):
            raise _Reject("keys[%d].%s must be an epoch-ms int in 1..2^53-1" % (index, field))
    if entry["valid_to_ms"] < entry["valid_from_ms"]:
        raise _Reject("keys[%d] validity window is inverted" % index)
    if not _is_epoch(entry["key_epoch"]):
        raise _Reject("keys[%d].key_epoch must be a non-negative int" % index)

    revoked = entry["revoked"]
    if not isinstance(revoked, bool):
        raise _Reject("keys[%d].revoked must be a boolean" % index)
    revoked_at = entry["revoked_at_ms"]

    # The P1-3 discriminated invariant. Both halves are refusals, not normalizations:
    # "revoked with no time" cannot be compared against any instant, and "not revoked but
    # carrying a time" is a document whose two fields disagree about the same fact.
    if revoked:
        if not _is_ms(revoked_at):
            raise _Reject(
                "keys[%d] is revoked but revoked_at_ms is not an epoch-ms int" % index
            )
        if revoked_at < entry["valid_from_ms"]:
            raise _Reject("keys[%d].revoked_at_ms precedes valid_from_ms" % index)
    else:
        if revoked_at is not None:
            raise _Reject("keys[%d] is not revoked but carries a revoked_at_ms" % index)

    return ChallengeKey(
        challenge_key_id=entry["challenge_key_id"],
        public_key=entry["public_key"],
        valid_from_ms=entry["valid_from_ms"],
        valid_to_ms=entry["valid_to_ms"],
        key_epoch=entry["key_epoch"],
        revoked=revoked,
        revoked_at_ms=revoked_at,
    )


def validate_registry_document(document: Any) -> Tuple[Dict[str, Any], str, Tuple[ChallengeKey, ...]]:
    """Strict §4.2 shape + invariant validation. Returns ``(payload, root_sig, keys)``.

    Raises :class:`_Reject` on any drift. This is the half that runs BEFORE the root
    signature is checked, because a signature over an unparsed blob proves only that
    someone signed a blob.
    """
    if not isinstance(document, Mapping):
        raise _Reject("registry document must be an object")
    _exact_keys(document, REGISTRY_DOC_FIELDS, "registry document")

    root_sig = document["root_sig"]
    if not isinstance(root_sig, str) or not root_sig:
        raise _Reject("root_sig must be a non-empty string")

    payload = document["payload"]
    if not isinstance(payload, Mapping):
        raise _Reject("registry payload must be an object")
    _exact_keys(payload, REGISTRY_PAYLOAD_FIELDS, "registry payload")

    if payload["artifact_type"] != REGISTRY_ARTIFACT_TYPE:
        raise _Reject("unexpected artifact_type %r" % (payload["artifact_type"],))
    if not _bounded_id(payload["root_key_id"]):
        raise _Reject("root_key_id must be a 1..128 char string")
    if not _is_epoch(payload["registry_epoch"]):
        raise _Reject("registry_epoch must be a non-negative int")
    if not _is_ms(payload["registry_issued_at_ms"]):
        raise _Reject("registry_issued_at_ms must be an epoch-ms int in 1..2^53-1")

    entries = payload["keys"]
    if not isinstance(entries, list):
        raise _Reject("keys must be an array")
    if len(entries) > MAX_REGISTRY_KEYS:
        raise _Reject("keys exceeds the %d entry cap" % MAX_REGISTRY_KEYS)

    keys = tuple(_validate_key_entry(entry, i) for i, entry in enumerate(entries))

    seen = set()
    for entry in keys:
        if entry.challenge_key_id in seen:
            raise _Reject("duplicate challenge_key_id %r" % (entry.challenge_key_id,))
        seen.add(entry.challenge_key_id)

    return dict(payload), root_sig, keys


# ---------------------------------------------------------------------------
# Resolution (shape -> root authority -> epoch floor)
# ---------------------------------------------------------------------------


def resolve_registry(
    document: Any,
    *,
    anchor: RootAnchor,
    epoch_floor: int,
    verify_root_sig: Callable[[bytes, str, str], bool],
) -> Tuple[Optional[RegistrySnapshot], Optional[str]]:
    """Verify a registry document into a usable snapshot.

    Returns ``(snapshot, None)`` on success or ``(None, "registry_unknown")`` on ANY
    failure. There is no third outcome and no partially-trusted snapshot: a registry that
    did not fully verify is not a weaker registry, it is no registry.

    ``verify_root_sig(message, sig, public_key) -> bool`` is the injected Ed25519 seam. A
    seam that raises is contained here and becomes ``registry_unknown`` — a crashing
    verifier must not be able to take the supervisor down or, worse, propagate past the
    check.
    """
    if not isinstance(anchor, RootAnchor):
        raise RegistryError("anchor must be a RootAnchor")
    if not isinstance(epoch_floor, int) or isinstance(epoch_floor, bool) or epoch_floor < 0:
        raise RegistryError("epoch_floor must be a non-negative int")
    if not callable(verify_root_sig):
        raise RegistryError("verify_root_sig must be callable")

    try:
        payload, root_sig, keys = validate_registry_document(document)
    except _Reject:
        return None, REGISTRY_UNKNOWN

    # The pinned anchor is the ONLY acceptable root. A document naming a different root is
    # refused before its signature is even considered — otherwise "unknown root" would be
    # decided by whether an attacker's own key verified its own document.
    if payload["root_key_id"] != anchor.root_key_id:
        return None, REGISTRY_UNKNOWN

    message = canonical_bytes(payload)
    try:
        ok = verify_root_sig(message, root_sig, anchor.public_key)
    except Exception:  # a verifier must never crash the open path
        return None, REGISTRY_UNKNOWN
    if ok is not True:
        return None, REGISTRY_UNKNOWN

    # Anti-rollback: an older snapshot is exactly how a revoked key returns.
    if payload["registry_epoch"] < epoch_floor:
        return None, REGISTRY_UNKNOWN

    document_bytes = canonical_bytes({"payload": payload, "root_sig": root_sig})
    if len(document_bytes) > MAX_REGISTRY_DOC_BYTES:
        return None, REGISTRY_UNKNOWN

    return (
        RegistrySnapshot(
            root_key_id=payload["root_key_id"],
            registry_epoch=payload["registry_epoch"],
            registry_issued_at_ms=payload["registry_issued_at_ms"],
            keys=keys,
            registry_hash=_sha256_hex(message),
            registry_handle=_sha256_hex(document_bytes),
        ),
        None,
    )


def select_key(
    snapshot: RegistrySnapshot,
    challenge_key_id: Any,
    as_of_ms: int,
) -> Tuple[Optional[ChallengeKey], Optional[str]]:
    """Return the key usable at ``as_of_ms``, or ``(None, reason)``.

    ``registry_unknown`` = no such ``challenge_key_id`` in the accepted snapshot.
    ``key_invalid`` = present, but not usable at that instant.

    The window is INCLUSIVE at both ends (§1: "a time ``t`` is in a window iff
    ``lo_ms <= t <= hi_ms``"); revocation is STRICT (``revoked_at_ms > t``), so a key
    revoked at exactly ``t`` is already unusable at ``t``. Those two boundaries point in
    opposite directions and that is deliberate — the design fixes each separately, and
    guessing that they match would silently admit a key at the instant of its revocation.
    """
    if not isinstance(snapshot, RegistrySnapshot):
        raise RegistryError("snapshot must be a RegistrySnapshot")
    if not _is_ms(as_of_ms):
        raise RegistryError("as_of_ms must be an epoch-ms int in 1..2^53-1")

    entry = snapshot.key(challenge_key_id)
    if entry is None:
        return None, REGISTRY_UNKNOWN
    if not (entry.valid_from_ms <= as_of_ms <= entry.valid_to_ms):
        return None, KEY_INVALID
    if entry.revoked_at_ms is not None and entry.revoked_at_ms <= as_of_ms:
        return None, KEY_INVALID
    return entry, None


__all__ = [
    "REGISTRY_ARTIFACT_TYPE",
    "MAX_REGISTRY_KEYS",
    "MAX_REGISTRY_DOC_BYTES",
    "PUBLIC_KEY_CHARS",
    "REGISTRY_UNKNOWN",
    "KEY_INVALID",
    "ChallengeKey",
    "RegistryError",
    "RegistrySnapshot",
    "RootAnchor",
    "canonical_bytes",
    "resolve_registry",
    "select_key",
    "validate_registry_document",
]
