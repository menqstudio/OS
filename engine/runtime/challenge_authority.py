"""desktop-challenge-authority service core (Wave 3b-1B, rev-30 §2.1).

PURE authority logic for the create-pending / issue split described in the
Execution-Binding Addendum §2.1 ("Challenge-authority trust boundary +
creation channel"). This module is deliberately socket-free and key-free so it
can be exercised offline and without the OS trust chain:

  * The pending-challenge store is dict-backed and injected (``PendingStore``);
    a real deployment owns it behind the authority's dedicated UID/SID.
  * Peer authentication is reduced to a pure predicate (``peer_is_broker``);
    a real deployment feeds it the ``SO_PEERCRED`` uid.
  * The signing key never appears here; callers pass a ``sign_fn`` and the
    authority hands it ONLY the bytes it assembled from its own row.

The single trust invariant (§2.1, "Single trust invariant (LOCKED)") is
enforced structurally:

  * ``validate_create_pending`` accepts ONLY the fixed shape of validated
    hashes/ids — never arbitrary bytes and never a caller-chosen payload.
  * ``issue_challenge`` builds the signed ``brops.governed-turn-challenge.v1``
    document itself from the stored row. It copies the broker-supplied
    ``request_nonce`` VERBATIM and never mints one.

Only the Python standard library is used.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Callable, Dict, Mapping, MutableMapping, Optional

# ---------------------------------------------------------------------------
# Constants (§2.1 / §2.1.1 / timestamp discipline)
# ---------------------------------------------------------------------------

CREATE_PENDING_PROTOCOL = "brops.governed-challenge-create-pending.v1"
CHALLENGE_PROTOCOL = "brops.governed-turn-challenge.v1"

# The fixed, exhaustive shape a create-pending request may carry. Anything
# outside this set (extra keys, missing keys, wrong types) is rejected. Turn
# facts enter the system ONLY here, validated, never as free bytes.
CREATE_PENDING_FIELDS = ("request_nonce", "request_sha256", "conversation_id", "install_id")

# Governed challenge TTL is capped so an executed turn is never refused as
# stale (§ timestamp discipline: governed challenge TTL <= 30000 ms).
MAX_CHALLENGE_TTL_MS = 30_000

# Pending row lifecycle (issue one-time-consumes: PENDING -> ISSUED).
STATE_PENDING = "PENDING"
STATE_ISSUED = "ISSUED"


class ChallengeAuthorityError(Exception):
    """Raised on any authority-policy violation. Fail-closed, never a panic."""


# ---------------------------------------------------------------------------
# Pending store (dict-backed, injectable)
# ---------------------------------------------------------------------------


class PendingStore:
    """Owner-only pending-challenge store.

    Backed by an injected mapping so tests use a plain ``dict`` fake while a
    real deployment can back it with the authority's protected DB. The store
    only ever holds authority-built rows: the validated fixed-shape fields plus
    a fresh opaque ``pending_challenge_id`` and lifecycle state.
    """

    def __init__(
        self,
        backing: Optional[MutableMapping[str, Dict[str, Any]]] = None,
        id_fn: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self._rows: MutableMapping[str, Dict[str, Any]] = backing if backing is not None else {}
        self._id_fn = id_fn

    def create_pending(self, validated_fields: Mapping[str, Any]) -> str:
        """Store a validated row, mint a FRESH opaque id, and return it.

        ``validated_fields`` MUST be the output of ``validate_create_pending``.
        The authority mints only the ``pending_challenge_id`` here; it never
        mints the ``request_nonce`` (that is the broker's, stored verbatim).
        """
        # Re-validate defensively so the store cannot be seeded with junk even
        # if a caller bypasses the top-level validator.
        row_fields = validate_create_pending(validated_fields)
        pending_id = self._id_fn()
        if not isinstance(pending_id, str) or not pending_id:
            raise ChallengeAuthorityError("id_fn produced an invalid pending_challenge_id")
        if pending_id in self._rows:
            raise ChallengeAuthorityError("pending_challenge_id collision")
        row = dict(row_fields)
        row["pending_challenge_id"] = pending_id
        row["state"] = STATE_PENDING
        self._rows[pending_id] = row
        return pending_id

    def get(self, pending_id: str) -> Optional[Dict[str, Any]]:
        row = self._rows.get(pending_id)
        return dict(row) if row is not None else None

    def consume(self, pending_id: str) -> Dict[str, Any]:
        """One-time-consume a PENDING row (PENDING -> ISSUED).

        Returns a copy of the row as it was at consume time. Raises if the row
        is missing or already consumed (non-reusable).
        """
        row = self._rows.get(pending_id)
        if row is None:
            raise ChallengeAuthorityError("unknown pending_challenge_id")
        if row.get("state") != STATE_PENDING:
            raise ChallengeAuthorityError("pending row already consumed")
        row["state"] = STATE_ISSUED
        return dict(row)


# ---------------------------------------------------------------------------
# create-pending validation (fixed shape ONLY)
# ---------------------------------------------------------------------------


def _is_sha256_hex(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and len(value) > 0


def validate_create_pending(fields: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate a create-pending body against the fixed shape; raise on any
    violation.

    Accepts EXACTLY ``CREATE_PENDING_FIELDS`` — no more, no less. Any extra or
    arbitrary field, any missing field, or any wrong-typed value is rejected.
    Returns a normalized copy (``request_sha256`` lowercased) that is safe to
    store. This is the ONLY door through which turn facts enter the authority.
    """
    if not isinstance(fields, Mapping):
        raise ChallengeAuthorityError("create-pending body must be a mapping")

    keys = set(fields.keys())
    allowed = set(CREATE_PENDING_FIELDS)
    extra = keys - allowed
    if extra:
        raise ChallengeAuthorityError(
            "create-pending rejected: arbitrary field(s) %s" % sorted(extra)
        )
    missing = allowed - keys
    if missing:
        raise ChallengeAuthorityError(
            "create-pending rejected: missing field(s) %s" % sorted(missing)
        )

    request_nonce = fields["request_nonce"]
    request_sha256 = fields["request_sha256"]
    conversation_id = fields["conversation_id"]
    install_id = fields["install_id"]

    if not _nonempty_str(request_nonce):
        raise ChallengeAuthorityError("request_nonce must be a non-empty string")
    if not _is_sha256_hex(request_sha256):
        raise ChallengeAuthorityError("request_sha256 must be 64 hex characters")
    if not _nonempty_str(conversation_id):
        raise ChallengeAuthorityError("conversation_id must be a non-empty string")
    if not _nonempty_str(install_id):
        raise ChallengeAuthorityError("install_id must be a non-empty string")

    return {
        "request_nonce": request_nonce,
        "request_sha256": request_sha256.lower(),
        "conversation_id": conversation_id,
        "install_id": install_id,
    }


# ---------------------------------------------------------------------------
# Peer authentication (§2.1 — allowlist ONLY the broker UID)
# ---------------------------------------------------------------------------


def peer_is_broker(peer_uid: Any, allowed_broker_uid: Any) -> bool:
    """Return True IFF the connecting peer is the trusted verifier/broker UID.

    The authority's only accepted peer is the broker UID; the renderer/login
    UID and the sidecar UID are DENIED on both messages (§2.1). This is a
    strict, fail-closed identity match — no ranges, no group membership.
    """
    if not isinstance(peer_uid, int) or isinstance(peer_uid, bool):
        return False
    if not isinstance(allowed_broker_uid, int) or isinstance(allowed_broker_uid, bool):
        return False
    return peer_uid == allowed_broker_uid


# ---------------------------------------------------------------------------
# issue (§2.1(B) — authority assembles + signs its OWN row)
# ---------------------------------------------------------------------------


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    """Deterministic JCS-ish encoding: sorted keys, compact separators."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


class AuthorityConfig:
    """The authority's own trusted config — the fields it (not the caller)
    fills into the challenge document at issue time."""

    def __init__(
        self,
        challenge_key_id: str,
        workspace_id: str,
        supervisor_id: str,
        challenge_ttl_ms: int = MAX_CHALLENGE_TTL_MS,
    ) -> None:
        if not _nonempty_str(challenge_key_id):
            raise ChallengeAuthorityError("challenge_key_id must be a non-empty string")
        if not _nonempty_str(workspace_id):
            raise ChallengeAuthorityError("workspace_id must be a non-empty string")
        if not _nonempty_str(supervisor_id):
            raise ChallengeAuthorityError("supervisor_id must be a non-empty string")
        if not isinstance(challenge_ttl_ms, int) or isinstance(challenge_ttl_ms, bool):
            raise ChallengeAuthorityError("challenge_ttl_ms must be an int")
        if not (0 < challenge_ttl_ms <= MAX_CHALLENGE_TTL_MS):
            raise ChallengeAuthorityError(
                "challenge_ttl_ms must be in (0, %d] ms" % MAX_CHALLENGE_TTL_MS
            )
        self.challenge_key_id = challenge_key_id
        self.workspace_id = workspace_id
        self.supervisor_id = supervisor_id
        self.challenge_ttl_ms = challenge_ttl_ms


def issue_challenge(
    row: Mapping[str, Any],
    config: AuthorityConfig,
    sign_fn: Callable[[bytes], str],
    clock_ms: Callable[[], int],
) -> Dict[str, Any]:
    """Assemble and sign the ``brops.governed-turn-challenge.v1`` document from
    the authority's OWN stored row.

    The caller supplies no bytes and no payload. The authority:
      * copies the stored ``request_nonce`` VERBATIM (it never mints one),
      * copies the stored ``request_sha256`` / ``conversation_id`` /
        ``install_id``,
      * fills ``challenge_key_id`` / ``workspace_id`` / ``supervisor_id`` from
        its own trusted config,
      * stamps issued/expires from its own clock (TTL <= 30000 ms),
      * signs the canonical bytes exactly once via ``sign_fn``.

    Returns ``{"payload": <doc>, "sig": <str>}``. Raises on a malformed row.
    """
    # A stored row must itself pass the fixed-shape validator (it never carries
    # attacker-chosen extra fields even if the store was tampered).
    facts = validate_create_pending(
        {k: row.get(k) for k in CREATE_PENDING_FIELDS}
    )

    now = clock_ms()
    if not isinstance(now, int) or isinstance(now, bool):
        raise ChallengeAuthorityError("clock_ms must return an int (epoch ms)")
    expires = now + config.challenge_ttl_ms

    payload: Dict[str, Any] = {
        "protocol": CHALLENGE_PROTOCOL,
        "challenge_key_id": config.challenge_key_id,
        # ---- copied verbatim from the stored row (broker-supplied) ----
        "request_nonce": facts["request_nonce"],
        "request_sha256": facts["request_sha256"],
        "conversation_id": facts["conversation_id"],
        "install_id": facts["install_id"],
        # ---- filled from the authority's own trusted config ----
        "workspace_id": config.workspace_id,
        "supervisor_id": config.supervisor_id,
        # ---- stamped from the authority's own clock ----
        "challenge_issued_at_ms": now,
        "challenge_expires_at_ms": expires,
    }

    sig = sign_fn(_canonical_bytes(payload))
    if not _nonempty_str(sig):
        raise ChallengeAuthorityError("sign_fn must return a non-empty signature string")

    return {"payload": payload, "sig": sig}
