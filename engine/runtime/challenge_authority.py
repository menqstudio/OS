"""desktop-challenge-authority service core (Wave 3b-1B, rev-30 §2.1 / §2.1.1).

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
    hashes/ids — never arbitrary bytes and never a caller-chosen payload. A
    caller-supplied ``request_sha256`` is an UNKNOWN field and is REJECTED as
    ``malformed`` (§2.1: "a caller-supplied request_sha256 is an unknown field
    ⇒ malformed, since the authority recomputes it").
  * The authority itself RECOMPUTES ``request_sha256`` from the create-pending
    inputs via the canonical ``brops.request.v1`` request-envelope formula
    (byte-identical to ``isolated_signer._recompute_request_sha256`` /
    ``receipt.rs::request_envelope_sha256``) and stores that value — never a
    caller value.
  * ``issue_challenge`` builds the signed ``brops.governed-turn-challenge.v1``
    document itself from the stored row. It copies the broker-supplied
    ``request_nonce`` VERBATIM and never mints one; it re-derives
    ``request_sha256`` from the row's own facts so the challenge is genuinely
    self-consistent for an independent supervisor recompute (§4.1).

Idempotency + retention (§2.1.1(d)/(f), LOCKED):

  * A repeat ``create-pending`` for the same ``(install_id, request_nonce)`` with
    identical facts re-returns the SAME ``pending_challenge_id`` (lost-reply-safe
    retry); a differing fact ⇒ ``retry_conflict``.
  * Issue performs the ``PENDING → ISSUED`` transition and PERSISTS the exact
    signed ``{payload, sig}`` document in the row. A repeat issue on a live
    ISSUED row re-returns that stored document BYTE-FOR-BYTE — it never re-signs
    and never re-stamps. An unknown id ⇒ ``no_pending_row``; a
    logically-expired (PENDING past its TTL, or ISSUED past its retention) row ⇒
    ``pending_expired``.

Only the Python standard library is used.
"""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from typing import Any, Callable, Dict, Mapping, MutableMapping, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants (§2.1 / §2.1.1 / timestamp discipline)
# ---------------------------------------------------------------------------

CREATE_PENDING_PROTOCOL = "brops.governed-challenge-create-pending.v1"
CHALLENGE_PROTOCOL = "brops.governed-turn-challenge.v1"

# The canonical request-envelope protocol whose SHA-256 IS ``request_sha256``
# (mirrors ``isolated_signer.REQUEST_PROTOCOL`` / receipt.rs ``REQUEST_PROTOCOL``
# / §2.2). The authority RECOMPUTES this digest; it never accepts a transported
# ``request_sha256`` (§2.1).
REQUEST_ENVELOPE_PROTOCOL = "brops.request.v1"

# The fixed, exhaustive shape a create-pending request may carry (§2.1 required
# set, MINUS the wire-level ``protocol``/routing key handled by the server, and
# MINUS ``request_sha256`` which the authority recomputes). Anything outside this
# set (extra keys, missing keys, wrong types) is rejected. Turn facts enter the
# system ONLY here, validated, never as free bytes.
CREATE_PENDING_FIELDS: Tuple[str, ...] = (
    "run_id",
    "task_id",
    "workspace_id",
    "install_id",
    "request_nonce",
    "system_sha256",
    "history_sha256",
    "generation_config_sha256",
    "requested_at_ms",
)

# Max length of any id / nonce string (§2.1 "all ids ≤128").
MAX_ID_LEN = 128

# Governed challenge TTL is capped so an executed turn is never refused as
# stale (§ timestamp discipline: governed challenge TTL <= 30000 ms).
MAX_CHALLENGE_TTL_MS = 30_000

# Pending/issued lifecycle constants (§2.1.1, LOCKED literal values).
PENDING_TTL_MS = 30_000            # PENDING-row life from created_at_ms
AUTHORITY_REPLAY_WINDOW_MS = 30_000  # lost-reply byte-identical issue replay window
ISSUED_RETENTION_MS = 60_000       # = CHALLENGE_TTL + AUTHORITY_REPLAY_WINDOW; from issued_at_ms

# Pending row lifecycle (issue one-time-consumes: PENDING -> ISSUED).
STATE_PENDING = "PENDING"
STATE_ISSUED = "ISSUED"

# Typed refusal reasons carried on ChallengeAuthorityError.reason (§2.1 schema).
REASON_MALFORMED = "malformed"
REASON_FIELD_INVALID = "field_invalid"
REASON_TIMESTAMP_INVALID = "timestamp_invalid"
REASON_RETRY_CONFLICT = "retry_conflict"
REASON_NO_PENDING_ROW = "no_pending_row"
REASON_PENDING_EXPIRED = "pending_expired"


class ChallengeAuthorityError(Exception):
    """Raised on any authority-policy violation. Fail-closed, never a panic.

    Carries a ``reason`` token from the §2.1 refusal vocabulary so the socket
    front door can surface the exact typed verdict (e.g. ``no_pending_row`` vs
    ``pending_expired``) rather than a bare string.
    """

    def __init__(self, message: str, reason: str = REASON_MALFORMED) -> None:
        super().__init__(message)
        self.reason = reason


# ---------------------------------------------------------------------------
# Small type predicates
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


def _bounded_id(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= MAX_ID_LEN


def _is_int(value: Any) -> bool:
    # bool is an int subclass; a boolean is never an acceptable epoch/id here.
    return isinstance(value, int) and not isinstance(value, bool)


# ---------------------------------------------------------------------------
# create-pending validation (fixed shape ONLY)
# ---------------------------------------------------------------------------


def validate_create_pending(fields: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate a create-pending body against the fixed shape; raise on any
    violation.

    Accepts EXACTLY ``CREATE_PENDING_FIELDS`` — no more, no less. A
    caller-supplied ``request_sha256`` is explicitly rejected as an unknown
    field (§2.1: the authority recomputes it). Any other extra or arbitrary
    field, any missing field, or any wrong-typed value is rejected. Returns a
    normalized copy (the three ``*_sha256`` lowercased). This is the ONLY door
    through which turn facts enter the authority.
    """
    if not isinstance(fields, Mapping):
        raise ChallengeAuthorityError("create-pending body must be a mapping")

    # A caller-supplied request_sha256 is an UNKNOWN field: the authority
    # recomputes it (§2.1). Reject explicitly (clearer than the generic path).
    if "request_sha256" in fields:
        raise ChallengeAuthorityError(
            "create-pending rejected: request_sha256 is caller-supplied and "
            "forbidden; the authority recomputes it (§2.1)"
        )

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

    run_id = fields["run_id"]
    task_id = fields["task_id"]
    workspace_id = fields["workspace_id"]
    install_id = fields["install_id"]
    request_nonce = fields["request_nonce"]
    system_sha256 = fields["system_sha256"]
    history_sha256 = fields["history_sha256"]
    generation_config_sha256 = fields["generation_config_sha256"]
    requested_at_ms = fields["requested_at_ms"]

    for name, value in (
        ("run_id", run_id),
        ("task_id", task_id),
        ("workspace_id", workspace_id),
        ("install_id", install_id),
        ("request_nonce", request_nonce),
    ):
        if not _bounded_id(value):
            raise ChallengeAuthorityError(
                "%s must be a non-empty string of <= %d chars" % (name, MAX_ID_LEN),
                reason=REASON_FIELD_INVALID,
            )

    for name, value in (
        ("system_sha256", system_sha256),
        ("history_sha256", history_sha256),
        ("generation_config_sha256", generation_config_sha256),
    ):
        if not _is_sha256_hex(value):
            raise ChallengeAuthorityError(
                "%s must be 64 hex characters" % name, reason=REASON_FIELD_INVALID
            )

    if not _is_int(requested_at_ms) or requested_at_ms <= 0:
        raise ChallengeAuthorityError(
            "requested_at_ms must be a positive integer (epoch ms)",
            reason=REASON_TIMESTAMP_INVALID,
        )

    return {
        "run_id": run_id,
        "task_id": task_id,
        "workspace_id": workspace_id,
        "install_id": install_id,
        "request_nonce": request_nonce,
        "system_sha256": system_sha256.lower(),
        "history_sha256": history_sha256.lower(),
        "generation_config_sha256": generation_config_sha256.lower(),
        "requested_at_ms": requested_at_ms,
    }


# ---------------------------------------------------------------------------
# request_sha256 recompute (§2.1 — authority derives it, never accepts it)
# ---------------------------------------------------------------------------


def _request_envelope_bytes(facts: Mapping[str, Any]) -> bytes:
    """Canonical ``brops.request.v1`` envelope bytes (the 8-field JCS envelope
    with ``request_nonce`` INSIDE the hashed bytes).

    Byte-identical to ``isolated_signer._recompute_request_sha256`` /
    ``receipt.rs::request_envelope_sha256`` — sorted keys, compact separators,
    raw UTF-8, ``requested_at`` as the decimal-ms STRING. This is the ONE
    canonical formula reused across the chain (never reinvented, §2.1).
    """
    envelope = {
        "protocol": REQUEST_ENVELOPE_PROTOCOL,
        "workspace_id": facts["workspace_id"],
        "install_id": facts["install_id"],
        "request_nonce": facts["request_nonce"],
        "system_sha256": facts["system_sha256"],
        "history_sha256": facts["history_sha256"],
        "generation_config_sha256": facts["generation_config_sha256"],
        # requested_at is a STRING field in the request envelope (§2.2): the
        # canonical decimal of the epoch-ms integer.
        "requested_at": str(facts["requested_at_ms"]),
    }
    return json.dumps(
        envelope,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def recompute_request_sha256(facts: Mapping[str, Any]) -> str:
    """RECOMPUTE the canonical request digest from validated create-pending
    facts. The authority stores/ signs ONLY this value, never a caller one."""
    return hashlib.sha256(_request_envelope_bytes(facts)).hexdigest()


# ---------------------------------------------------------------------------
# Pending store (dict-backed, injectable) — §2.1.1 lifecycle
# ---------------------------------------------------------------------------


class PendingStore:
    """Owner-only pending-challenge store.

    Backed by an injected mapping so tests use a plain ``dict`` fake while a
    real deployment can back it with the authority's protected DB. The store
    only ever holds authority-built rows: the validated fixed-shape facts, the
    authority-RECOMPUTED ``request_sha256``, a fresh opaque
    ``pending_challenge_id``, lifecycle state, and — after issue — the EXACT
    signed challenge document (for byte-identical replay).
    """

    def __init__(
        self,
        backing: Optional[MutableMapping[str, Dict[str, Any]]] = None,
        id_fn: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self._rows: MutableMapping[str, Dict[str, Any]] = backing if backing is not None else {}
        # (install_id, request_nonce) -> pending_challenge_id, the idempotency
        # index (§2.1 "UNIQUE(install_id, request_nonce)").
        self._nonce_index: Dict[Tuple[str, str], str] = {}
        self._id_fn = id_fn

    @staticmethod
    def _facts_match(row: Mapping[str, Any], facts: Mapping[str, Any], request_sha256: str) -> bool:
        for key in CREATE_PENDING_FIELDS:
            if row.get(key) != facts.get(key):
                return False
        return row.get("request_sha256") == request_sha256

    def create_pending(self, validated_fields: Mapping[str, Any], now_ms: int) -> Tuple[str, int]:
        """Store a validated row, mint a FRESH opaque id, and return
        ``(pending_challenge_id, pending_expires_at_ms)``.

        ``validated_fields`` MUST be the output of ``validate_create_pending``
        (it is re-validated defensively). The authority RECOMPUTES
        ``request_sha256`` here and stores it; it never mints the
        ``request_nonce`` (that is the broker's, stored verbatim) and never
        accepts a caller ``request_sha256``.

        Idempotency (§2.1.1(a)): a repeat with the same
        ``(install_id, request_nonce)`` and identical facts re-returns the SAME
        id; a differing fact ⇒ ``retry_conflict``.
        """
        # Re-validate defensively so the store cannot be seeded with junk even
        # if a caller bypasses the top-level validator.
        facts = validate_create_pending(validated_fields)
        if not _is_int(now_ms):
            raise ChallengeAuthorityError("now_ms must be an int (epoch ms)")

        request_sha256 = recompute_request_sha256(facts)
        idem_key = (facts["install_id"], facts["request_nonce"])

        existing_pid = self._nonce_index.get(idem_key)
        if existing_pid is not None:
            existing = self._rows.get(existing_pid)
            if existing is not None:
                if self._facts_match(existing, facts, request_sha256):
                    # Lost-reply-safe idempotent retry: same id, same expiry.
                    return existing_pid, existing["pending_expires_at_ms"]
                raise ChallengeAuthorityError(
                    "create-pending conflict: (install_id, request_nonce) reused "
                    "with differing facts",
                    reason=REASON_RETRY_CONFLICT,
                )

        pending_id = self._id_fn()
        if not isinstance(pending_id, str) or not pending_id:
            raise ChallengeAuthorityError("id_fn produced an invalid pending_challenge_id")
        if pending_id in self._rows:
            raise ChallengeAuthorityError("pending_challenge_id collision")

        row = dict(facts)
        row["request_sha256"] = request_sha256
        row["pending_challenge_id"] = pending_id
        row["state"] = STATE_PENDING
        row["created_at_ms"] = now_ms
        row["pending_expires_at_ms"] = now_ms + PENDING_TTL_MS
        row["issued_at_ms"] = None
        row["issued_challenge_document"] = None
        self._rows[pending_id] = row
        self._nonce_index[idem_key] = pending_id
        return pending_id, row["pending_expires_at_ms"]

    def get(self, pending_id: str) -> Optional[Dict[str, Any]]:
        row = self._rows.get(pending_id)
        return copy.deepcopy(row) if row is not None else None

    def mark_issued(
        self, pending_id: str, document: Mapping[str, Any], issued_at_ms: int
    ) -> None:
        """Atomically transition PENDING -> ISSUED, persisting the EXACT signed
        document + ``issued_at_ms`` in the same step (§2.1.1(d)).

        Raises if the row is missing or not PENDING (a concurrent-CAS loser
        never re-writes an already-ISSUED row).
        """
        row = self._rows.get(pending_id)
        if row is None:
            raise ChallengeAuthorityError(
                "unknown pending_challenge_id", reason=REASON_NO_PENDING_ROW
            )
        if row.get("state") != STATE_PENDING:
            raise ChallengeAuthorityError("pending row is not PENDING")
        if not _is_int(issued_at_ms):
            raise ChallengeAuthorityError("issued_at_ms must be an int (epoch ms)")
        row["state"] = STATE_ISSUED
        row["issued_at_ms"] = issued_at_ms
        row["issued_challenge_document"] = copy.deepcopy(document)


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
    """Deterministic JCS-ish encoding: sorted keys, compact separators. The
    EXACT encoding ``governed_supervisor._canonical_bytes`` reassembles to
    verify the signature."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


class AuthorityConfig:
    """The authority's own trusted config — the fields it (not the caller)
    fills into the challenge document at issue time."""

    def __init__(
        self,
        challenge_key_id: str,
        supervisor_id: str,
        install_id: str,
        challenge_ttl_ms: int = MAX_CHALLENGE_TTL_MS,
        workspace_id: Optional[str] = None,
    ) -> None:
        if not _nonempty_str(challenge_key_id):
            raise ChallengeAuthorityError("challenge_key_id must be a non-empty string")
        if not _nonempty_str(supervisor_id):
            raise ChallengeAuthorityError("supervisor_id must be a non-empty string")
        # ``install_id`` is REQUIRED, and it is required for a security reason rather
        # than a schema one (audit A-01, 2026-08-14).
        #
        # The evidence-head anti-rollback floor is SCOPED by install_id
        # (``governed_supervisor_ledger._install_floor_ceiling``). Until this field
        # existed the caller supplied it: the broker put an install_id in
        # ``create-pending``, this authority signed it, and every downstream check
        # bound the request to the payload -- so the signature laundered the choice
        # rather than replacing it. Driving the repository's own ledger:
        #
        #     install-A / task-1     / head 99  -> BOOTSTRAPPED
        #     install-A / task-FRESH / head 3   -> REFUSED (StaleEvidence)
        #     install-B / task-FRESH / head 3   -> BOOTSTRAPPED   <- same rollback
        #
        # This is the R-07/R-10 defect surviving one level up: the fix that moved the
        # floor off ``task_id`` argued, at ``governed_supervisor_ledger.py:762-765``,
        # that "A defence whose scope the attacker chooses is not a defence" -- and
        # then left the new scope key in the same hands.
        #
        # Made REQUIRED, not optional-with-default: an optional pin is not a pin, and
        # a deployment that forgot it would keep the hole while looking configured.
        if not _nonempty_str(install_id):
            raise ChallengeAuthorityError("install_id must be a non-empty string")
        if not isinstance(challenge_ttl_ms, int) or isinstance(challenge_ttl_ms, bool):
            raise ChallengeAuthorityError("challenge_ttl_ms must be an int")
        if not (0 < challenge_ttl_ms <= MAX_CHALLENGE_TTL_MS):
            raise ChallengeAuthorityError(
                "challenge_ttl_ms must be in (0, %d] ms" % MAX_CHALLENGE_TTL_MS
            )
        # ``workspace_id`` is retained for construction back-compat but is NOT a
        # payload source: the challenge's workspace_id (and the request_sha256
        # recompute) come from the desktop-supplied row so the supervisor's
        # independent recompute over the payload matches (§2.1(B)).
        if workspace_id is not None and not _nonempty_str(workspace_id):
            raise ChallengeAuthorityError("workspace_id must be a non-empty string")
        self.challenge_key_id = challenge_key_id
        self.supervisor_id = supervisor_id
        self.install_id = install_id
        self.challenge_ttl_ms = challenge_ttl_ms
        self.workspace_id = workspace_id


def issue_challenge(
    row: Mapping[str, Any],
    config: AuthorityConfig,
    sign_fn: Callable[[bytes], str],
    clock_ms: Callable[[], int],
) -> Dict[str, Any]:
    """Assemble and sign the ``brops.governed-turn-challenge.v1`` document (§4.1)
    from the authority's OWN stored row.

    The caller supplies no bytes and no payload. The authority:
      * copies the stored ``request_nonce`` VERBATIM (it never mints one),
      * copies the stored ``run_id``/``task_id``/``workspace_id``/``install_id``
        and the three component ``*_sha256`` + ``requested_at_ms``,
      * RE-DERIVES ``request_sha256`` from the row's own facts (never a caller
        value) so the challenge is self-consistent for an independent supervisor
        recompute,
      * fills ``challenge_key_id`` / ``supervisor_id`` from its own trusted
        config,
      * stamps issued/expires from its own clock (TTL <= 30000 ms),
      * signs the canonical bytes exactly once via ``sign_fn``.

    Returns ``{"payload": <doc>, "sig": <str>}``. Raises on a malformed row.
    """
    # A stored row must itself pass the fixed-shape validator (it never carries
    # attacker-chosen extra fields even if the store was tampered).
    facts = validate_create_pending({k: row.get(k) for k in CREATE_PENDING_FIELDS})

    now = clock_ms()
    if not _is_int(now):
        raise ChallengeAuthorityError("clock_ms must return an int (epoch ms)")
    expires = now + config.challenge_ttl_ms

    request_sha256 = recompute_request_sha256(facts)

    payload: Dict[str, Any] = {
        "protocol": CHALLENGE_PROTOCOL,
        "challenge_key_id": config.challenge_key_id,
        # ---- copied verbatim from the stored row (broker/desktop-supplied) ----
        "run_id": facts["run_id"],
        "task_id": facts["task_id"],
        "workspace_id": facts["workspace_id"],
        "install_id": facts["install_id"],
        "request_nonce": facts["request_nonce"],
        "system_sha256": facts["system_sha256"],
        "history_sha256": facts["history_sha256"],
        "generation_config_sha256": facts["generation_config_sha256"],
        # ---- authority-RECOMPUTED (never caller-supplied) ----
        "request_sha256": request_sha256,
        "requested_at_ms": facts["requested_at_ms"],
        # ---- filled from the authority's own trusted config ----
        "supervisor_id": config.supervisor_id,
        # ---- stamped from the authority's own clock ----
        "challenge_issued_at_ms": now,
        "challenge_expires_at_ms": expires,
    }

    sig = sign_fn(_canonical_bytes(payload))
    if not _nonempty_str(sig):
        raise ChallengeAuthorityError("sign_fn must return a non-empty signature string")

    return {"payload": payload, "sig": sig}


def issue_challenge_document(
    store: PendingStore,
    pending_id: str,
    config: AuthorityConfig,
    sign_fn: Callable[[bytes], str],
    clock_ms: Callable[[], int],
) -> Dict[str, Any]:
    """Resolve a pending row and return its signed challenge document, applying
    the §2.1.1(d)/(f) issue lifecycle:

      * unknown id ⇒ ``no_pending_row``;
      * PENDING past its TTL, or ISSUED past its retention ⇒ ``pending_expired``
        (logical expiry — synchronous, evaluated before acting, §2.1.1(b));
      * live PENDING ⇒ sign ONCE, stamp ``issued_at_ms``, PERSIST the exact
        signed document, transition PENDING → ISSUED, and return it;
      * live ISSUED ⇒ re-return the STORED document BYTE-FOR-BYTE (idempotent
        lost-reply replay — never re-signs, never re-stamps).

    Fail-closed: any inconsistency raises a typed ``ChallengeAuthorityError``.
    """
    now = clock_ms()
    if not _is_int(now):
        raise ChallengeAuthorityError("clock_ms must return an int (epoch ms)")

    row = store.get(pending_id)
    if row is None:
        raise ChallengeAuthorityError(
            "no pending row for pending_challenge_id", reason=REASON_NO_PENDING_ROW
        )

    state = row.get("state")

    if state == STATE_ISSUED:
        issued_at = row.get("issued_at_ms")
        if not _is_int(issued_at):
            raise ChallengeAuthorityError("issued row missing issued_at_ms")
        # Synchronous logical retention expiry (§2.1.1(b)/(d)).
        if now > issued_at + ISSUED_RETENTION_MS:
            raise ChallengeAuthorityError(
                "issued row past ISSUED_RETENTION_MS", reason=REASON_PENDING_EXPIRED
            )
        document = row.get("issued_challenge_document")
        if not isinstance(document, Mapping):
            raise ChallengeAuthorityError("issued row missing stored document")
        # Byte-identical replay: the stored document, unchanged.
        return copy.deepcopy(document)

    if state == STATE_PENDING:
        # Synchronous logical PENDING expiry (§2.1.1(b)/(d)).
        if now > row["pending_expires_at_ms"]:
            raise ChallengeAuthorityError(
                "pending row past pending_expires_at_ms", reason=REASON_PENDING_EXPIRED
            )
        # Sign ONCE from the row, stamping challenge time == issued_at == now.
        document = issue_challenge(row, config, sign_fn, clock_ms=lambda: now)
        # Persist the EXACT signed document + issued_at in the PENDING -> ISSUED
        # transition (a hash could not reproduce these bytes, so store the doc).
        store.mark_issued(pending_id, document, issued_at_ms=now)
        return document

    raise ChallengeAuthorityError("pending row in unknown state %r" % (state,))
