"""``brops.governed-turn-open.v1`` — the signed-challenge submission (rev-30 §4.10(a0)).

This is the FIRST governed message on the wire. Before it the supervisor has nothing: a
``challenge_handle`` alone can neither be re-hashed nor signature-verified, so the exact
signed document bytes MUST arrive here (§2.4, P0-2). The untrusted sidecar transports those
bytes and nothing else — every authority in this file is either the challenge's own
signature or state the supervisor resolved from itself.

What the message does, and the two things it must not do
--------------------------------------------------------
It ADMITS a turn to upload. It creates the §2.4 ``governed_turn_staging`` row in
``UPLOADING``, and that is the whole grant.

It does **not** mint an ``execution_attempt_id`` and it does **not** stamp
``challenge_accepted_at_ms``. Both belong to §5 acceptance, which happens later, once, on a
different message. The single clock read below is a **resource-admission** read: it is
never persisted, never becomes an acceptance time, and never replaces the §5/§7 as-of-
acceptance predicate — which independently re-reads the acceptance clock and re-checks the
full validity/revocation window. Confusing the two would turn a cheap pre-check into a
binding authorization, which is the whole reason the design names the distinction three
separate times.

**P1-5, the defect this shape exists to prevent.** ``execution_attempt_id`` is minted by the
supervisor, once, at acceptance. A requester that supplies one is trying to name the
identity its own execution will later be judged under. The §4.10(a0) request frame is
therefore an EXACT four-field set — ``{protocol, install_id, request_nonce,
challenge_doc_b64}`` — with unknown-field rejection, so a request carrying
``execution_attempt_id`` (or ``lease_id``, or ``receipt_id``) is refused ``malformed``
before any side effect. The staging table has no column for it either; see
``governed_staging_ledger``.

Verification order (§4.10(a0), LOCKED — each step fail-closed, in this order)
----------------------------------------------------------------------------
  1. peer UID                                    -> ``peer_denied``
  2. request shape (exact keys, bounded strings) -> ``malformed``
  3. base64url decode                            -> ``malformed``
  4. decoded size > 4096                         -> ``doc_oversize``
  5. strict UTF-8 JSON, duplicate-key rejection,
     exact §4.1 envelope + payload shape         -> ``malformed``
  6. canonicality gate                           -> ``noncanonical``
  7. ``challenge_handle = SHA256(decoded bytes)``
  8. resolve the root-signed registry from the
     supervisor's OWN state; root sig + key
     presence                                    -> ``registry_unknown``
     key validity as of ``challenge_issued_at_ms``-> ``key_invalid``
  9. challenge ``sig`` under the resolved key    -> ``sig_invalid``
 10. context: request<->payload ids, this
     supervisor, ``request_sha256`` recompute    -> ``context_mismatch``
 11. resource-admission expiry gate (ONE clock
     read; inclusive boundary)                   -> ``challenge_expired``
 12. publish the EXACT decoded bytes             -> ``handle_mismatch``
 13. CAS ``absent -> VERIFYING -> UPLOADING``    -> ``retry_conflict`` / ``quota_turns``

Steps 8-10 come BEFORE step 11 because ``challenge_expires_at_ms`` is a signed §4.1 field:
reading an expiry off an unverified document and acting on it would be trusting the sidecar
to tell the supervisor when to stop trusting it.

Two places where the tree and the design disagree — resolved here, reported, not papered over
---------------------------------------------------------------------------------------------
**(1) Which ``canonical_bytes``.** §4.10(a0) names ``bro_signature.canonical_bytes``
(``ensure_ascii=False``). The governed chain's signatures are actually produced and verified
over ``challenge_authority._canonical_bytes`` / ``governed_supervisor._canonical_bytes``
(``ensure_ascii=True``). The two encoders agree for every ASCII document and diverge the
moment any id contains a non-ASCII character. Picking either one alone is a real hole in one
direction: the signer's encoder would accept documents the design's gate rejects; the
design's encoder would reject documents whose signature genuinely verifies. So the gate here
requires **both** — the decoded bytes must equal the governed-family canonicalization AND the
two encoders must agree on the document. That is the strict intersection: fail-closed under
either reading, and it never admits bytes that only one of them would call canonical.

**(2) Which bytes the handle covers — RESOLVED 2026-08-10, no longer a divergence.**
§3's artifact matrix and §4.10(a0) both define
``challenge_handle = SHA256(JCS({payload, sig}))``, while the shipped ``accept_open``
computed ``SHA256(JCS(payload))`` — the payload alone — and §5's summary table recorded that
behaviour. Two digests of different byte strings were specified for one field of one turn.
The §3/§4.10(a0) form won and ``accept_open`` was corrected; see the addendum's
``### CORRECTION 2026-08-10`` block at its head. The decisive argument was §7's challenge
predicate, which fetches the stored document BY the handle and re-hashes the exact stored
bytes — and the stored document IS the ``{payload, sig}`` envelope, so the payload-only form
could never have satisfied §7 for any turn.

There is now ONE definition, ``governed_supervisor.challenge_handle_for(payload, sig)``.
Anything that needs a ``challenge_handle`` should call it rather than recompute the digest.
This module still hashes the exact decoded document bytes, which is the same value by
construction: the canonicality gate above has already required those bytes to equal
``canonical_bytes({payload, sig})``, so re-canonicalizing would only add a second way to get
the same number — and hashing what actually arrived is the property §4.10(a0) asks for.

Only the Python standard library is used.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

import challenge_key_registry as registry
import governed_staging_ledger as staging
from brops_protocol import ProtocolError, decode_base64url, strict_loads
from challenge_authority import peer_is_broker
from governed_supervisor import (
    SupervisorConfig,
    SupervisorError,
    _canonical_bytes,
    _validate_challenge_doc,
)
from governed_supervisor import recompute_request_sha256 as default_recompute_request_sha256

# ---------------------------------------------------------------------------
# Wire constants (§4.10(a0), LOCKED literals)
# ---------------------------------------------------------------------------

OPEN_PROTOCOL = "brops.governed-turn-open.v1"
OPEN_RESULT_PROTOCOL = "brops.governed-turn-open-result.v1"

#: The exhaustive request field set. Four fields; nothing else is accepted, ever.
OPEN_REQUEST_FIELDS: Tuple[str, ...] = (
    "protocol",
    "install_id",
    "request_nonce",
    "challenge_doc_b64",
)

#: §4.10(a0): "Frame ≤ 8 KiB". Matches the supervisor front door's existing
#: ``MAX_FRAME_BYTES``, so no frame bound had to move to carry this message.
MAX_OPEN_FRAME_BYTES = 8192

#: §4.10(a0): "decoded ≤ 4096". A larger document is ``doc_oversize``, not ``malformed`` —
#: the size is checked on the DECODED bytes, before any parse, so an oversize document is
#: never handed to the JSON decoder at all.
MAX_CHALLENGE_DOC_BYTES = 4096

#: §2.1/§4.1: all ids ≤ 128.
MAX_ID_LEN = 128

STATUS_OPENED = "opened"
STATUS_REFUSED = "refused"

# ---- The CLOSED §4.10(a0) refusal set ------------------------------------------------
REFUSE_PEER_DENIED = "peer_denied"
REFUSE_DOC_OVERSIZE = "doc_oversize"
REFUSE_MALFORMED = "malformed"
REFUSE_NONCANONICAL = "noncanonical"
REFUSE_HANDLE_MISMATCH = "handle_mismatch"
REFUSE_REGISTRY_UNKNOWN = "registry_unknown"
REFUSE_KEY_INVALID = "key_invalid"
REFUSE_SIG_INVALID = "sig_invalid"
REFUSE_CONTEXT_MISMATCH = "context_mismatch"
REFUSE_CHALLENGE_EXPIRED = "challenge_expired"
REFUSE_RETRY_CONFLICT = "retry_conflict"
REFUSE_QUOTA_TURNS = "quota_turns"

#: Exactly the reasons §4.10(a0) enumerates. A reply carrying anything else is a bug, and
#: :func:`refused` asserts against this set so it cannot become one silently.
OPEN_REFUSAL_REASONS: Tuple[str, ...] = (
    REFUSE_PEER_DENIED,
    REFUSE_DOC_OVERSIZE,
    REFUSE_MALFORMED,
    REFUSE_NONCANONICAL,
    REFUSE_HANDLE_MISMATCH,
    REFUSE_REGISTRY_UNKNOWN,
    REFUSE_KEY_INVALID,
    REFUSE_SIG_INVALID,
    REFUSE_CONTEXT_MISMATCH,
    REFUSE_CHALLENGE_EXPIRED,
    REFUSE_RETRY_CONFLICT,
    REFUSE_QUOTA_TURNS,
)


class _Refuse(Exception):
    """Internal control flow: a typed refusal reason. Never escapes this module."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail


# ---------------------------------------------------------------------------
# Peer authentication
# ---------------------------------------------------------------------------


def peer_is_sidecar(peer_uid: Any, allowed_sidecar_uid: Any) -> bool:
    """True IFF the connecting peer is the dedicated sidecar UID (§2.6).

    This delegates to ``challenge_authority.peer_is_broker`` rather than repeating it. That
    predicate is a strict, fail-closed comparison of two uids — rejecting bools, rejecting
    non-ints, no ranges, no group membership — and "broker" in its name is its first caller,
    not a property of the comparison. Writing a second one here would be a third copy in the
    tree (``isolated_signer_server`` already has one) of four lines that must never disagree.

    ``allowed_sidecar_uid = None`` (an unconfigured sidecar principal) yields False: a
    supervisor that has not been told who the sidecar is serves no sidecar.
    """
    return peer_is_broker(peer_uid, allowed_sidecar_uid)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OpenConfig:
    """Everything the SUPERVISOR — never the caller — contributes to an open.

    ``registry_root_key_id``/``registry_root_public_key`` are the §4.2 binary-pinned
    challenge-root anchor. ``registry_epoch_floor`` is the anti-rollback floor. None of the
    three can be influenced by a message; that is what makes "resolve the registry from its
    own state" true rather than aspirational.
    """

    supervisor_id: str
    registry_root_key_id: str
    registry_root_public_key: str
    registry_epoch_floor: int = 0

    def anchor(self) -> registry.RootAnchor:
        return registry.RootAnchor(
            root_key_id=self.registry_root_key_id,
            public_key=self.registry_root_public_key,
        )

    @classmethod
    def from_supervisor_config(
        cls,
        config: SupervisorConfig,
        *,
        registry_root_public_key: str,
        registry_epoch_floor: int = 0,
    ) -> "OpenConfig":
        """Derive from the supervisor's existing trusted config.

        ``supervisor_id`` and ``challenge_registry_root_key_id`` already live there and are
        already the values the acceptance row records, so the open-time check and the
        acceptance-time record cannot drift apart. Only the root PUBLIC KEY is new: the
        shipped config carried the root's *id* but never its key material, which is why the
        registry could be named in an acceptance row and never actually verified.
        """
        if not isinstance(config, SupervisorConfig):
            raise SupervisorError("config must be a SupervisorConfig")
        return cls(
            supervisor_id=config.supervisor_id,
            registry_root_key_id=config.challenge_registry_root_key_id,
            registry_root_public_key=registry_root_public_key,
            registry_epoch_floor=registry_epoch_floor,
        )


@dataclass(frozen=True)
class VerifiedChallenge:
    """The product of steps 2-11: an authenticated challenge, admitted to be staged.

    Holding this object means the signature verified under a root-signed key that was valid
    when the challenge was issued, the transported bytes are canonical, the context binds to
    this supervisor, and the challenge had not expired at the single admission clock read. It
    does NOT mean the turn is accepted; nothing here is an execution right.
    """

    challenge_handle: str
    document_bytes: bytes
    payload: Mapping[str, Any]
    sig: str
    now_ms: int
    registry_snapshot: registry.RegistrySnapshot
    challenge_key: registry.ChallengeKey


# ---------------------------------------------------------------------------
# Replies
# ---------------------------------------------------------------------------


def opened(challenge_handle: str) -> Dict[str, Any]:
    return {
        "protocol": OPEN_RESULT_PROTOCOL,
        "status": STATUS_OPENED,
        "challenge_handle": challenge_handle,
    }


def refused(reason: str) -> Dict[str, Any]:
    """Build the refusal reply.

    The reason is asserted to be a member of the closed §4.10(a0) set. A refusal carrying an
    off-contract reason is worse than a refusal carrying a wrong one: the sidecar's §4.10(h)
    diagnostic routing table (NOT IMPLEMENTED — a later ordered piece) maps reasons to Blocks
    by name, so an unmapped string would fall through to whatever the default happens to be.
    Fail loudly here instead, while the set is still the only thing that can be checked.

    The reply carries the reason ONLY — no detail string. §4.10(a0)'s reply shape has no
    detail field, and a supervisor volunteering *why* its own registry state rejected a
    document would be answering questions the untrusted sidecar did not get to ask.
    """
    if reason not in OPEN_REFUSAL_REASONS:
        raise SupervisorError("refusal reason %r is not in the §4.10(a0) closed set" % (reason,))
    return {"protocol": OPEN_RESULT_PROTOCOL, "status": STATUS_REFUSED, "reason": reason}


# ---------------------------------------------------------------------------
# Steps 2-6: request shape, decode, size, canonicality
# ---------------------------------------------------------------------------


def _require_exact_request(request: Any) -> Mapping[str, Any]:
    if not isinstance(request, Mapping):
        raise _Refuse(REFUSE_MALFORMED, "request must be a JSON object")
    keys = set(request.keys())
    extra = keys - set(OPEN_REQUEST_FIELDS)
    if extra:
        # This is the P1-5 door. `execution_attempt_id` arrives here, and it leaves here.
        raise _Refuse(REFUSE_MALFORMED, "unexpected field(s) %s" % sorted(extra))
    missing = set(OPEN_REQUEST_FIELDS) - keys
    if missing:
        raise _Refuse(REFUSE_MALFORMED, "missing field(s) %s" % sorted(missing))
    if request["protocol"] != OPEN_PROTOCOL:
        raise _Refuse(REFUSE_MALFORMED, "unexpected protocol %r" % (request["protocol"],))
    for field in ("install_id", "request_nonce"):
        value = request[field]
        if not isinstance(value, str) or not (0 < len(value) <= MAX_ID_LEN):
            raise _Refuse(REFUSE_MALFORMED, "%s must be a 1..128 char string" % field)
    if not isinstance(request["challenge_doc_b64"], str):
        raise _Refuse(REFUSE_MALFORMED, "challenge_doc_b64 must be a string")
    return request


def _decode_document(challenge_doc_b64: str) -> bytes:
    """base64url (no padding) -> exact document bytes, size-checked on the DECODED form.

    The encoded length is bounded first, purely so a hostile 8 KiB frame cannot make the
    decoder allocate before the ``doc_oversize`` verdict; the verdict itself is always about
    the decoded size, as §4.10(a0) specifies.
    """
    if len(challenge_doc_b64) > 4 * ((MAX_CHALLENGE_DOC_BYTES + 2) // 3) + 4:
        raise _Refuse(REFUSE_DOC_OVERSIZE, "encoded challenge document exceeds the 4096-byte cap")
    # `brops_protocol.decode_base64url` owns the strictness (alphabet + round-trip):
    # `urlsafe_b64decode` silently tolerates stray characters, so a document that does not
    # re-encode to the exact string sent is not the document that was sent. It is shared
    # with §4.10(b)'s chunk decode rather than repeated here.
    try:
        decoded = decode_base64url(challenge_doc_b64)
    except ProtocolError as exc:
        raise _Refuse(REFUSE_MALFORMED, "challenge_doc_b64 is not base64url: %s" % exc)
    if len(decoded) > MAX_CHALLENGE_DOC_BYTES:
        raise _Refuse(REFUSE_DOC_OVERSIZE, "decoded challenge document exceeds 4096 bytes")
    return decoded


def _strict_decode(document_bytes: bytes) -> Mapping[str, Any]:
    """Strict UTF-8 JSON with duplicate-key rejection — ``brops_protocol.strict_loads``.

    Reused rather than re-written: it already rejects non-UTF-8, non-object top levels and
    duplicate keys, and a second decoder that drifted from it would mean the supervisor and
    the signer disagreed about what "strict" is.
    """
    try:
        return strict_loads(document_bytes)
    except ProtocolError as exc:
        raise _Refuse(REFUSE_MALFORMED, "challenge document strict-decode failed: %s" % exc)


def _canonicality_gate(document_bytes: bytes, document: Mapping[str, Any]) -> None:
    """§4.10(a0): the transported bytes, the computed handle and the stored document can
    never diverge.

    Enforced as the STRICT INTERSECTION of the two canonicalizers this repository actually
    contains (see the module docstring): the bytes must equal the governed-family encoding
    of ``{payload, sig}``, and the ``ensure_ascii=False`` encoding must agree with it. A
    document only one of them calls canonical is refused.
    """
    envelope = {"payload": document["payload"], "sig": document["sig"]}
    governed = _canonical_bytes(envelope)
    if document_bytes != governed:
        raise _Refuse(REFUSE_NONCANONICAL, "transported bytes are not the canonical encoding")
    utf8_form = json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    if utf8_form != governed:
        raise _Refuse(
            REFUSE_NONCANONICAL,
            "document is canonical under only one of the two encodings in use",
        )


# ---------------------------------------------------------------------------
# The pure verification pipeline (steps 2-11). No I/O, no DB, no store.
# ---------------------------------------------------------------------------


def verify_open_request(
    request: Any,
    *,
    peer_uid: Any,
    allowed_sidecar_uid: Any,
    config: OpenConfig,
    resolve_registry_document: Callable[[], Any],
    verify_root_sig: Callable[[bytes, str, str], bool],
    verify_challenge_sig: Callable[[bytes, str, str], bool],
    clock_ms: Callable[[], int],
    recompute_request_sha256: Callable[[Mapping[str, Any]], str] = default_recompute_request_sha256,
) -> Tuple[Optional[VerifiedChallenge], Optional[str]]:
    """Run §4.10(a0) steps 1-11. Returns ``(verified, None)`` or ``(None, reason)``.

    Every seam that can raise is contained and mapped to a refusal: a verifier, a registry
    resolver or a recompute that throws on hostile input must produce a verdict, not an
    exception that escapes the protocol. A :class:`SupervisorError` — a non-callable seam, a
    non-int clock — is a supervisor-side fault and DOES propagate, because a misconfigured
    supervisor must not be reported to the peer as a refused document.
    """
    if not isinstance(config, OpenConfig):
        raise SupervisorError("config must be an OpenConfig")
    for name, seam in (
        ("resolve_registry_document", resolve_registry_document),
        ("verify_root_sig", verify_root_sig),
        ("verify_challenge_sig", verify_challenge_sig),
        ("clock_ms", clock_ms),
        ("recompute_request_sha256", recompute_request_sha256),
    ):
        if not callable(seam):
            raise SupervisorError("%s must be callable" % name)

    try:
        # ---- 1. peer authentication, BEFORE anything is parsed --------------------
        if not peer_is_sidecar(peer_uid, allowed_sidecar_uid):
            raise _Refuse(REFUSE_PEER_DENIED, "peer uid is not the sidecar principal")

        # ---- 2-4. request shape, decode, decoded-size bound ----------------------
        request = _require_exact_request(request)
        document_bytes = _decode_document(request["challenge_doc_b64"])

        # ---- 5. strict decode + the exact §4.1 shape ----------------------------
        document = _strict_decode(document_bytes)
        try:
            payload, sig = _validate_challenge_doc(document)
        except Exception as exc:
            # `_validate_challenge_doc` raises the supervisor core's own `_Refuse`
            # (reason `malformed`). Its refusal vocabulary is §5's, not §4.10(a0)'s, so
            # it is re-stated in this protocol's closed set rather than relayed.
            raise _Refuse(REFUSE_MALFORMED, "challenge document shape rejected: %s" % exc)

        # ---- 6. canonicality gate ------------------------------------------------
        _canonicality_gate(document_bytes, document)

        # ---- 7. the handle IS the exact document bytes --------------------------
        challenge_handle = hashlib.sha256(document_bytes).hexdigest()

        # ---- 8. the supervisor's OWN registry -----------------------------------
        try:
            registry_document = resolve_registry_document()
        except Exception:
            raise _Refuse(REFUSE_REGISTRY_UNKNOWN, "registry could not be resolved")
        snapshot, reason = registry.resolve_registry(
            registry_document,
            anchor=config.anchor(),
            epoch_floor=config.registry_epoch_floor,
            verify_root_sig=verify_root_sig,
        )
        if snapshot is None:
            raise _Refuse(reason or REFUSE_REGISTRY_UNKNOWN, "registry not accepted")

        # Key validity AS OF `challenge_issued_at_ms` — the open-time preliminary
        # predicate. NOT as-of-acceptance: that instant does not exist yet, and §5/§7
        # re-run the full window against it independently.
        key, reason = registry.select_key(
            snapshot, payload["challenge_key_id"], payload["challenge_issued_at_ms"]
        )
        if key is None:
            raise _Refuse(reason or REFUSE_REGISTRY_UNKNOWN, "challenge key not usable")

        # ---- 9. the challenge signature under the RESOLVED key ------------------
        message = _canonical_bytes(payload)
        try:
            ok = verify_challenge_sig(message, sig, key.public_key)
        except Exception:
            raise _Refuse(REFUSE_SIG_INVALID, "challenge verifier raised")
        if ok is not True:
            raise _Refuse(REFUSE_SIG_INVALID, "challenge signature rejected")

        # ---- 10. context binding -------------------------------------------------
        # The request's routing fields must be the SIGNED ones. Otherwise a valid
        # challenge could be staged under a nonce or install the signature never covered,
        # and the staging row's UNIQUEs would be protecting the wrong identity.
        if request["install_id"] != payload["install_id"]:
            raise _Refuse(REFUSE_CONTEXT_MISMATCH, "request install_id != signed install_id")
        if request["request_nonce"] != payload["request_nonce"]:
            raise _Refuse(REFUSE_CONTEXT_MISMATCH, "request request_nonce != signed request_nonce")
        if payload["supervisor_id"] != config.supervisor_id:
            raise _Refuse(REFUSE_CONTEXT_MISMATCH, "challenge names another supervisor")
        try:
            recomputed = recompute_request_sha256(payload)
        except Exception:
            raise _Refuse(REFUSE_CONTEXT_MISMATCH, "request_sha256 recompute raised")
        if not isinstance(recomputed, str) or recomputed.lower() != payload["request_sha256"].lower():
            raise _Refuse(REFUSE_CONTEXT_MISMATCH, "request_sha256 does not re-derive")

        # ---- 11. resource-admission expiry gate (ONE clock read) ----------------
        now_ms = clock_ms()
        if not isinstance(now_ms, int) or isinstance(now_ms, bool):
            raise SupervisorError("clock_ms must return an int (epoch ms)")
        # INCLUSIVE boundary, §4.10(a0): `now_ms == challenge_expires_at_ms` is ADMITTED,
        # `+1` is REFUSED. This value is discarded after the comparison and the quota
        # count; it is not persisted and is not `challenge_accepted_at_ms`.
        if now_ms > payload["challenge_expires_at_ms"]:
            raise _Refuse(REFUSE_CHALLENGE_EXPIRED, "now_ms past challenge_expires_at_ms")

        return (
            VerifiedChallenge(
                challenge_handle=challenge_handle,
                document_bytes=document_bytes,
                payload=payload,
                sig=sig,
                now_ms=now_ms,
                registry_snapshot=snapshot,
                challenge_key=key,
            ),
            None,
        )
    except _Refuse as refusal:
        return None, refusal.reason


# ---------------------------------------------------------------------------
# The full operation: verify -> publish -> CAS (steps 1-13)
# ---------------------------------------------------------------------------


def handle_open(
    request: Any,
    *,
    peer_uid: Any,
    allowed_sidecar_uid: Any,
    config: OpenConfig,
    conn: Any,
    publish_document: Callable[[bytes], str],
    resolve_registry_document: Callable[[], Any],
    verify_root_sig: Callable[[bytes, str, str], bool],
    verify_challenge_sig: Callable[[bytes, str, str], bool],
    clock_ms: Callable[[], int],
    recompute_request_sha256: Callable[[Mapping[str, Any]], str] = default_recompute_request_sha256,
) -> Dict[str, Any]:
    """Serve one ``brops.governed-turn-open.v1`` and return the §4.10(a0) reply object.

    ``publish_document`` is the atomic create-if-absent publish into ``store/sup/`` — in
    production ``brops_evidence_store.EvidenceStore.publish``, which already does
    temp -> fsync -> verify -> ``os.link``/``O_EXCL`` -> divergent-refuse -> fsync-dir. It
    is injected rather than constructed here so the store's ownership and location stay a
    deployment decision, and so this path can be driven offline.

    Order note (§4.10(a0)): the publish happens BEFORE the CAS, as the design specifies, so
    a ``quota_turns`` or ``retry_conflict`` refusal may have already published the challenge
    document. That is harmless and deliberate: the document is content-addressed, the
    publish is idempotent, and — critically — the bytes are AUTHENTIC (the signature was
    verified two steps earlier). No row exists, no nonce is consumed, no execution right is
    granted. The one refusal the design requires to publish NOTHING is ``challenge_expired``,
    and that gate is upstream of this point.
    """
    if conn is None:
        raise SupervisorError("governed-turn-open requires a durable ledger connection")
    if not callable(publish_document):
        raise SupervisorError("publish_document must be callable")

    verified, reason = verify_open_request(
        request,
        peer_uid=peer_uid,
        allowed_sidecar_uid=allowed_sidecar_uid,
        config=config,
        resolve_registry_document=resolve_registry_document,
        verify_root_sig=verify_root_sig,
        verify_challenge_sig=verify_challenge_sig,
        clock_ms=clock_ms,
        recompute_request_sha256=recompute_request_sha256,
    )
    if verified is None:
        return refused(reason or REFUSE_MALFORMED)

    payload = verified.payload

    # ---- 12. publish the EXACT decoded bytes (§6 step 1) ------------------------
    # The store re-derives the handle from the bytes it wrote. If that disagrees with the
    # handle computed from the bytes decoded here, the supervisor is not looking at the
    # document it verified — refuse rather than record a handle nothing can resolve.
    try:
        published = publish_document(verified.document_bytes)
    except Exception:
        return refused(REFUSE_HANDLE_MISMATCH)
    if not isinstance(published, str) or published.lower() != verified.challenge_handle:
        return refused(REFUSE_HANDLE_MISMATCH)

    # ---- 13. CAS absent -> VERIFYING -> UPLOADING -------------------------------
    new_row = staging.NewStaging(
        install_id=payload["install_id"],
        request_nonce=payload["request_nonce"],
        challenge_handle=verified.challenge_handle,
        run_id=payload["run_id"],
        task_id=payload["task_id"],
        workspace_id=payload["workspace_id"],
        system_sha256=payload["system_sha256"].lower(),
        history_sha256=payload["history_sha256"].lower(),
        generation_config_sha256=payload["generation_config_sha256"].lower(),
        challenge_expires_at_ms=payload["challenge_expires_at_ms"],
    )
    try:
        _outcome, row = staging.open_staging(conn, new_row, verified.now_ms)
    except staging.StagingQuotaExceeded:
        return refused(REFUSE_QUOTA_TURNS)
    except staging.Conflict:
        return refused(REFUSE_RETRY_CONFLICT)
    except staging.LedgerError as exc:
        # A ledger fault (corrupt row, unknown stored state) is still a REFUSAL: an open
        # the supervisor could not durably record is an open that did not happen.
        raise SupervisorError("staging ledger fault: %s" % exc)

    # Idempotent re-open re-returns the SAME handle from the durable row, never the freshly
    # computed one — so a byte-identical retry and the original are answered from one source.
    return opened(row["challenge_handle"])


@dataclass(frozen=True)
class OpenService:
    """The supervisor-side binding of §4.10(a0): its trusted config plus the four seams a
    real deployment supplies (store publish, registry resolution, two signature verifiers)
    and the sidecar UID it will accept.

    It exists so the front door carries ONE optional object instead of six optional
    parameters, and so the wiring for this protocol lives with the protocol. It is also the
    fail-closed switch: a supervisor constructed without an ``OpenService`` serves no
    ``governed-turn-open`` at all — every such request is ``peer_denied``, because a
    supervisor that has not been told who the sidecar is, where its store is, or which
    registry it accepts cannot admit a turn on any of those grounds.
    """

    config: OpenConfig
    allowed_sidecar_uid: int
    publish_document: Callable[[bytes], str]
    resolve_registry_document: Callable[[], Any]
    verify_root_sig: Callable[[bytes, str, str], bool]
    verify_challenge_sig: Callable[[bytes, str, str], bool]
    recompute_request_sha256: Callable[[Mapping[str, Any]], str] = default_recompute_request_sha256

    def __post_init__(self) -> None:
        if not isinstance(self.config, OpenConfig):
            raise SupervisorError("OpenService.config must be an OpenConfig")
        if not isinstance(self.allowed_sidecar_uid, int) or isinstance(self.allowed_sidecar_uid, bool):
            raise SupervisorError("OpenService.allowed_sidecar_uid must be an int uid")

    def handle(self, request: Any, *, peer_uid: Any, conn: Any,
               clock_ms: Callable[[], int]) -> Dict[str, Any]:
        return handle_open(
            request,
            peer_uid=peer_uid,
            allowed_sidecar_uid=self.allowed_sidecar_uid,
            config=self.config,
            conn=conn,
            publish_document=self.publish_document,
            resolve_registry_document=self.resolve_registry_document,
            verify_root_sig=self.verify_root_sig,
            verify_challenge_sig=self.verify_challenge_sig,
            clock_ms=clock_ms,
            recompute_request_sha256=self.recompute_request_sha256,
        )


__all__ = [
    "MAX_CHALLENGE_DOC_BYTES",
    "MAX_OPEN_FRAME_BYTES",
    "OPEN_PROTOCOL",
    "OPEN_REFUSAL_REASONS",
    "OPEN_REQUEST_FIELDS",
    "OPEN_RESULT_PROTOCOL",
    "OpenConfig",
    "OpenService",
    "REFUSE_CHALLENGE_EXPIRED",
    "REFUSE_CONTEXT_MISMATCH",
    "REFUSE_DOC_OVERSIZE",
    "REFUSE_HANDLE_MISMATCH",
    "REFUSE_KEY_INVALID",
    "REFUSE_MALFORMED",
    "REFUSE_NONCANONICAL",
    "REFUSE_PEER_DENIED",
    "REFUSE_QUOTA_TURNS",
    "REFUSE_REGISTRY_UNKNOWN",
    "REFUSE_RETRY_CONFLICT",
    "REFUSE_SIG_INVALID",
    "STATUS_OPENED",
    "STATUS_REFUSED",
    "VerifiedChallenge",
    "handle_open",
    "opened",
    "peer_is_sidecar",
    "refused",
    "verify_open_request",
]
