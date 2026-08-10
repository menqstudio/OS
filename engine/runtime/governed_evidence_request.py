"""``brops.governed-evidence-request.v1`` — the §4.10(d) execute/finalize trigger.

This is the message that asks the supervisor to stop staging and start executing. By the
time it arrives the sidecar has done everything §4.10(a0)/(a)/(b)/(c) allow it to do: one
signed challenge was verified and published, three artifacts were uploaded, re-hashed and
published, and the turn's ``governed_turn_staging`` row sits in ``INPUTS_READY``. §4.10(d)
carries no new material at all — three identifiers the supervisor already holds — and its
entire job is to decide whether that durable state exists, and then hand the turn to §5.

What this file is, and the line it does not cross
-------------------------------------------------
It is the **pre-acceptance gate** and nothing else. §4.10(d)'s reply is a tagged union
across two protocols, split exactly where the ``governed_turn_acceptance`` row begins:

  * **before** a row exists, a gate failure answers ``brops.governed-evidence-request-
    result.v1 {status:"refused", reason}`` from a five-literal closed set — an internal
    refusal, carried to the desktop as the §4.10(h) NON-SUCCESS DIAGNOSTIC (stage
    ``evidence-request``; §4.10(h) is **NOT IMPLEMENTED** — a later ordered piece) and
    creating **NO** acceptance row;
  * **once** a row exists, the verdict is §4.10(e)'s ``brops.governed-turn-result.v1``
    (``governed_turn_result``), produced by §5 acceptance.

So this module produces the first arm and *delegates* the second. It mints no
``execution_attempt_id``, reads no acceptance clock, consumes no challenge nonce, issues
no lease, writes no row, and touches no table at all: every statement it runs is a SELECT.
The §5 continuation is an injected seam (``drive_acceptance``); a supervisor with no
continuation configured serves no evidence-request, which is the fail-closed direction —
a gate whose "pass" outcome went nowhere would be an admission with no admitter.

The gate reads a PROPERTY, not a claim
---------------------------------------
§4.10(d) "requires the ``INPUTS_READY`` staging row for ``(install_id, request_nonce,
challenge_handle)``". That sentence is only worth anything if ``INPUTS_READY`` cannot be
declared by a writer that published nothing, so this module relies on the canonical DDL
(``supervisor_ledger.sql``) rather than re-checking in Python what the database refuses to
store. Precisely five guarantees are relied on, all of them triggers:

  1. ``trg_governed_turn_staging_insert_state`` — a row is BORN ``VERIFYING``;
  2. ``trg_governed_turn_staging_insert_handles`` — and born with **no** ``*_handle`` set,
     so a handle can only ever arrive through the §4.10(c) UPDATE that records one;
  3. ``trg_governed_turn_staging_transition`` — the only edges are
     ``VERIFYING → UPLOADING → INPUTS_READY``; nothing skips and nothing goes back;
  4. ``trg_governed_turn_staging_handle_binding`` — a published handle must EQUAL the
     digest the signed challenge committed to for that artifact, and is write-once;
  5. ``trg_governed_turn_staging_inputs_ready`` — ``INPUTS_READY`` is unreachable while any
     of the three handles is NULL.

Together those make "all three declared inputs were published, and each is the digest the
signature authorized" a property of any row this gate accepts. Re-deriving it here would
not add a second opinion — it would read the same three columns the triggers already
constrain — so it is deliberately not done. The one thing the DDL genuinely cannot promise
is that the store still HOLDS those bytes; §5/§6 re-read them from the content-addressed
store before anything is signed, and §4.10(d) has no reason literal for their absence, so
inventing one here would put a verdict outside a closed set.

What this gate deliberately does NOT check
-------------------------------------------
**Expiry.** A staging row carries ``challenge_expires_at_ms``, and this gate ignores it.
That is not an oversight: §4.10(d)'s reason set is CLOSED and contains no expiry literal,
and §5 step 3 re-reads the acceptance clock once and applies the FULL as-of-acceptance
validity predicate (``challenge_issued_at_ms ≤ challenge_accepted_at_ms ≤
challenge_expires_at_ms``, plus key validity and revocation), refusing
``challenge_invalidated``. Refusing expiry here would either duplicate that predicate
against a *different* clock read or force a reason literal the design does not publish.
The consequence is stated rather than hidden: an expired-but-unswept row passes this gate
and is refused one step later, while an expired-and-swept row is simply absent and refused
here as ``no_inputs_ready``. Both are terminal Blocks; only the name differs.

Only the Python standard library is used, and no clock is read anywhere in this file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

import governed_staging_ledger as staging
from governed_staging_upload import (
    _Refuse,
    _checked,
    _require_exact_request,
    _require_id,
    _require_sha256,
)
from governed_supervisor import SupervisorError
from governed_turn_open import peer_is_sidecar
from governed_turn_result import validate_turn_result

# ---------------------------------------------------------------------------
# Wire constants (§4.10(d), LOCKED literals)
# ---------------------------------------------------------------------------

EVIDENCE_REQUEST_PROTOCOL = "brops.governed-evidence-request.v1"

#: The PRE-ACCEPTANCE reply. §4.10(d)/§4.10(h) (NOT IMPLEMENTED) give it its own protocol
#: const precisely so it can never be confused with the post-acceptance §4.10(e) verdict
#: ``brops.governed-turn-result.v1``: the two arms of the
#: union are told apart by their own discriminator, not by inspecting their fields.
EVIDENCE_REQUEST_RESULT_PROTOCOL = "brops.governed-evidence-request-result.v1"

#: §4.10(d): "Frame ≤ 4 KiB". Numerically the same bound §4.10(a)/(c) put on their control
#: frames, but it is written out here rather than imported from them: it is a separate
#: clause about a separate protocol, and sharing the constant would mean a future change to
#: one section silently moved the other.
MAX_EVIDENCE_REQUEST_FRAME_BYTES = 4096

#: The exhaustive request field set. Four fields; nothing else, ever — the same P1-5 door
#: §4.10(a0) and the three staging protocols close. A request carrying an
#: ``execution_attempt_id`` is a requester naming the identity its own execution would
#: later be judged under, and §4.10(d) says in as many words that it "carries **no**
#: ``execution_attempt_id`` (the supervisor reserves it, §5) and grants no authority by
#: itself".
EVIDENCE_REQUEST_FIELDS: Tuple[str, ...] = (
    "protocol",
    "install_id",
    "challenge_handle",
    "request_nonce",
)

STATUS_REFUSED = "refused"

# ---- The CLOSED §4.10(d) pre-acceptance refusal set ----------------------------------
REFUSE_PEER_DENIED = "peer_denied"
REFUSE_NO_INPUTS_READY = "no_inputs_ready"
REFUSE_SESSION_CORRUPT = "session_corrupt"
REFUSE_RETRY_CONFLICT = "retry_conflict"
REFUSE_MALFORMED = "malformed"

#: Exactly the five literals §4.10(d) and the §4.10(h) (NOT IMPLEMENTED) routing table
#: publish for this stage.
#:
#: §4.10(h) (NOT IMPLEMENTED) calls these "a **disjoint** namespace from
#: ``GOVERNED_REFUSAL_REASONS``", and that is true of the NAMESPACE but NOT of the strings:
#: §4.5's closed governed enum — ``governed_turn_result.GOVERNED_REFUSAL_REASONS``, the
#: single list §4.10(e) embeds verbatim — contains ``malformed`` (one of the ratified
#: twelve) and ``retry_conflict`` (a governed addition), so two of the five literals below
#: are spelled the same in both sets. What
#: actually keeps them apart is the DISCRIMINATOR — a pre-acceptance refusal is carried by
#: ``brops.governed-evidence-request-result.v1`` and reaches the desktop as
#: ``governed_internal_refusal:evidence-request:{r}``, while a governed verdict is carried
#: by ``brops.governed-turn-result.v1`` and reaches it as ``governed_verdict_refused:{r}``
#: (§4.10(h), NOT IMPLEMENTED, classifies by top-level ``protocol``, never by the reason
#: string). So a reader
#: must not conclude from a bare ``"retry_conflict"`` which authority produced it; the
#: protocol const is the only thing that answers that, which is why this module never
#: returns a reason without one.
EVIDENCE_REQUEST_REFUSAL_REASONS: Tuple[str, ...] = (
    REFUSE_PEER_DENIED,
    REFUSE_NO_INPUTS_READY,
    REFUSE_SESSION_CORRUPT,
    REFUSE_RETRY_CONFLICT,
    REFUSE_MALFORMED,
)

#: The §4.10(h) diagnostic ``stage`` this protocol's refusals travel under (§4.10(h) is
#: **NOT IMPLEMENTED** — a later ordered piece). It is named here, beside the closed set it
#: labels, so the two cannot drift apart when that piece is built.
DIAGNOSTIC_STAGE = "evidence-request"


# ---------------------------------------------------------------------------
# Replies
# ---------------------------------------------------------------------------


def evidence_request_refused(reason: str) -> Dict[str, Any]:
    """Build the §4.10(d) PRE-ACCEPTANCE refusal.

    ``_checked`` is imported from ``governed_staging_upload`` rather than rewritten: it is
    the one implementation of "a refusal reason must be a member of the set its protocol
    published", and the reason it exists is the same here — the §4.10(h) (NOT IMPLEMENTED)
    routing table maps
    reasons to Blocks BY NAME, so an unmapped string would fall through to whatever the
    default happens to be. A second copy would be a second thing to keep in step.

    The reply carries the reason ONLY. §4.10(d)'s shape has no detail field, and a
    supervisor volunteering *why* its own durable state rejected a turn would be answering
    a question the untrusted sidecar did not get to ask.
    """
    return {
        "protocol": EVIDENCE_REQUEST_RESULT_PROTOCOL,
        "status": STATUS_REFUSED,
        "reason": _checked(reason, EVIDENCE_REQUEST_REFUSAL_REASONS,
                           EVIDENCE_REQUEST_PROTOCOL),
    }


def frame_cap_refusal(protocol: Any, frame_len: int) -> Optional[Dict[str, Any]]:
    """The §4.10(d) frame bound, applied to the bytes that actually ARRIVED.

    Returns the refusal reply, or ``None`` if this is not a §4.10(d) frame or it fits. It
    is shaped exactly like ``governed_staging_upload.frame_cap_refusal`` so the front door
    can consult the two in sequence, and it is a real bound rather than a formality: the
    exhaustive shape below caps a legal request at a few hundred bytes, but the shape check
    runs on the DECODED object, so whitespace and padding a JSON decoder discards are
    invisible to it. This sees the wire.

    Over-cap answers ``malformed`` because §4.10(d)'s closed set has no size literal —
    inventing one outside a published set is precisely what ``_checked`` exists to stop.
    """
    if protocol != EVIDENCE_REQUEST_PROTOCOL:
        return None
    if frame_len <= MAX_EVIDENCE_REQUEST_FRAME_BYTES:
        return None
    return evidence_request_refused(REFUSE_MALFORMED)


# ---------------------------------------------------------------------------
# What passing the gate produces
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GatedTurn:
    """A turn whose inputs are durably ready — the ONLY thing §4.10(d) produces.

    Every field is read off the ``governed_turn_staging`` ROW, never off the request. The
    request's three identifiers are used to FIND the row and are then discarded; what §5
    receives is what the supervisor durably recorded when it verified the signature.

    There is no ``execution_attempt_id``, no lease, no ``challenge_accepted_at_ms`` and no
    clock reading in this object, because §4.10(d) mints none of them. It is a pointer to
    durable state plus the proof that the state is complete — an admission to §5, not a
    right granted by §4.10(d).
    """

    install_id: str
    request_nonce: str
    challenge_handle: str
    run_id: str
    task_id: str
    workspace_id: str
    system_handle: str
    history_handle: str
    generation_config_handle: str
    challenge_expires_at_ms: int


def _gated_turn(row: Any) -> GatedTurn:
    return GatedTurn(
        install_id=row["install_id"],
        request_nonce=row["request_nonce"],
        challenge_handle=row["challenge_handle"],
        run_id=row["run_id"],
        task_id=row["task_id"],
        workspace_id=row["workspace_id"],
        system_handle=row["system_handle"],
        history_handle=row["history_handle"],
        generation_config_handle=row["generation_config_handle"],
        challenge_expires_at_ms=row["challenge_expires_at_ms"],
    )


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def _has_corrupt_session(conn: Any, challenge_handle: str) -> bool:
    """Is any of this turn's three upload sessions terminally ``SESSION_CORRUPT``?

    Read through ``load_session_for_artifact`` — the §2.4 ``UNIQUE (challenge_handle,
    artifact)`` read that already exists — rather than through a new query. A turn has at
    most three sessions, so the loop is bounded by the artifact set and not by anything a
    caller chooses.
    """
    for artifact in staging.STAGING_ARTIFACTS:
        session = staging.load_session_for_artifact(conn, challenge_handle, artifact)
        if session is not None and session["state"] == staging.SESSION_CORRUPT:
            return True
    return False


def gate_evidence_request(
    request: Any,
    *,
    peer_uid: Any,
    allowed_sidecar_uid: Any,
    conn: Any,
) -> Tuple[Optional[GatedTurn], Optional[str]]:
    """Run the §4.10(d) pre-acceptance gate. Returns ``(GatedTurn, None)`` or
    ``(None, reason)`` with ``reason`` in the closed set.

    The order is §4.10(d)'s own: authenticate the peer, then validate the shape, then look
    for the row. Nothing is read from the database until the caller has proved it is the
    sidecar and its message is the exact four-field frame, so a hostile peer never reaches
    a query.

    **How the three identifiers become one verdict.** ``governed_turn_staging`` carries two
    UNIQUEs — ``(install_id, request_nonce)`` and ``challenge_handle`` — so the triple in
    the request names at most one row by each key, and the two keys must name the SAME row
    for the join §4.10(d) describes to hold:

      * neither key finds anything ⇒ ``no_inputs_ready``;
      * the nonce finds nothing but the handle is opened under some OTHER
        ``(install_id, request_nonce)`` ⇒ ``retry_conflict``. This is §5's rule stated one
        step earlier: "a retry that presents a nonce/challenge pairing different from the
        stored row is a conflict and is refused";
      * the nonce finds a row bound to a DIFFERENT challenge ⇒ ``retry_conflict``, the
        mirror image of the same rule.

    Only then is the state read, and only ``INPUTS_READY`` passes. A turn that is not ready
    is diagnosed once more before it is refused: if any of its upload sessions is terminally
    ``SESSION_CORRUPT`` the answer is ``session_corrupt`` — the specific, permanent verdict
    (§2.4: recovery is operator-sweep only, and a corrupt session can never contribute to
    an accepted turn) — otherwise ``no_inputs_ready``, which merely says "not yet".

    A ready turn can never have a corrupt session, so that diagnosis is deliberately made
    only on the not-ready branch rather than unconditionally: ``INPUTS_READY`` requires all
    three handles, a handle is only recorded by ``finalize_session``, ``finalize_session``
    refuses a ``SESSION_CORRUPT`` session, and ``ARTIFACT_READY`` is terminal in the DDL so
    a session cannot rot after it publishes. A check placed where it could not fire would
    read as protection while protecting nothing.
    """
    try:
        # §4.10(d): "The supervisor authenticates the peer UID" — first, before the shape,
        # so a stranger's frame is never parsed on its behalf.
        if not peer_is_sidecar(peer_uid, allowed_sidecar_uid):
            raise _Refuse(REFUSE_PEER_DENIED, "peer is not the sidecar principal")

        body = _require_exact_request(request, EVIDENCE_REQUEST_PROTOCOL,
                                      EVIDENCE_REQUEST_FIELDS)
        install_id = _require_id(body, "install_id")
        request_nonce = _require_id(body, "request_nonce")
        challenge_handle = _require_sha256(body, "challenge_handle")

        if conn is None:
            raise SupervisorError(
                "governed-evidence-request requires a durable ledger connection")

        try:
            row = staging.load_staging(conn, install_id, request_nonce)
            if row is None:
                if staging.load_staging_by_handle(conn, challenge_handle) is not None:
                    raise _Refuse(REFUSE_RETRY_CONFLICT,
                                  "the challenge is open under a different install/nonce")
                raise _Refuse(REFUSE_NO_INPUTS_READY, "no staging row for this turn")
            if row["challenge_handle"] != challenge_handle:
                raise _Refuse(REFUSE_RETRY_CONFLICT,
                              "the nonce is bound to a different challenge")

            if row["state"] != staging.INPUTS_READY:
                if _has_corrupt_session(conn, row["challenge_handle"]):
                    raise _Refuse(REFUSE_SESSION_CORRUPT,
                                  "an upload session for this turn is SESSION_CORRUPT")
                raise _Refuse(REFUSE_NO_INPUTS_READY,
                              "staging row is %s, not INPUTS_READY" % (row["state"],))
        except staging.LedgerError as exc:
            # A durable row the supervisor cannot interpret is a FAULT, not a peer's
            # refusal: answering "no_inputs_ready" would report a clean absence where the
            # truth is that the ledger holds something unreadable.
            raise SupervisorError("staging ledger fault: %s" % exc)

        return _gated_turn(row), None
    except _Refuse as refusal:
        return None, refusal.reason


# ---------------------------------------------------------------------------
# The wire operation
# ---------------------------------------------------------------------------


def handle_evidence_request(
    request: Any,
    *,
    peer_uid: Any,
    allowed_sidecar_uid: Any,
    conn: Any,
    drive_acceptance: Callable[[GatedTurn], Dict[str, Any]],
) -> Dict[str, Any]:
    """Serve one ``brops.governed-evidence-request.v1`` and return the §4.10(d) reply.

    On a gate failure the reply is this protocol's own pre-acceptance refusal and **no**
    acceptance row is created — nothing at all is written.

    On a pass the turn is handed to ``drive_acceptance``, the §5 continuation
    (acceptance → lease → execution → record → isolated signer, §6.1). That continuation is
    **NOT IMPLEMENTED** in this tree — it is a later ordered piece — and it is injected
    rather than called directly for the same reason the store publish is: what §4.10(d)
    owns is the decision, not the machinery on the other side of it.

    The continuation's reply is checked against the OTHER arm of §4.10(d)'s union before it
    is relayed. Two guards, in this order:

      1. it may not answer in the PRE-ACCEPTANCE namespace. Once §5 has been entered the
         verdict belongs to §4.10(e)'s ``brops.governed-turn-result.v1`` union; a
         continuation returning ``brops.governed-evidence-request-result.v1`` would
         collapse the two halves of §4.10(d)'s union into one, and §4.10(h)
         (**NOT IMPLEMENTED** — a later ordered piece) could then not tell an internal
         refusal from a governed verdict. This is worth its own message rather than being folded
         into the general shape check below, because it is a specific and tempting mistake;
      2. it must BE a §4.10(e) frame. §4.10(d) says in as many words that once a row exists
         "the acceptance/signer verdict is ``brops.governed-turn-result.v1``", so a reply
         that is not one is not a verdict this gate may pass on. Until §4.10(e) existed
         that sentence was unenforced and the reply was relayed unexamined.

    Both are supervisor-side faults, not something a peer asked for, so both raise rather
    than refuse. Note what is NOT checked: the §5 continuation is still an INJECTED SEAM
    with **no production supplier** — §5 acceptance is a later ordered piece — so what this
    establishes is the contract any future supplier is held to, not that one exists.
    """
    if not callable(drive_acceptance):
        raise SupervisorError("drive_acceptance must be callable")

    gated, reason = gate_evidence_request(
        request, peer_uid=peer_uid, allowed_sidecar_uid=allowed_sidecar_uid, conn=conn,
    )
    if gated is None:
        return evidence_request_refused(reason or REFUSE_MALFORMED)

    result = drive_acceptance(gated)
    if isinstance(result, Mapping) and result.get("protocol") == EVIDENCE_REQUEST_RESULT_PROTOCOL:
        raise SupervisorError(
            "the §5 continuation answered in the pre-acceptance namespace")
    # "Is this a reply object at all" is NOT re-asked here: `validate_turn_result` owns it,
    # and asking twice would leave one of the two askers unable to fail.
    validate_turn_result(result)
    return dict(result)


@dataclass(frozen=True)
class EvidenceRequestService:
    """The §4.10(d) binding: the sidecar UID this supervisor serves, and the §5 seam.

    Like ``OpenService`` and ``StagingService`` it is also the fail-closed switch. A
    supervisor constructed WITHOUT one serves no evidence-request at all — not because the
    trigger is optional, but because a supervisor that has not been told who the sidecar is,
    or what happens when a turn is admitted to execute, cannot honestly admit one.
    """

    allowed_sidecar_uid: int
    drive_acceptance: Callable[[GatedTurn], Dict[str, Any]]

    def __post_init__(self) -> None:
        if not isinstance(self.allowed_sidecar_uid, int) or isinstance(self.allowed_sidecar_uid, bool):
            raise SupervisorError(
                "EvidenceRequestService.allowed_sidecar_uid must be an int uid")
        if not callable(self.drive_acceptance):
            raise SupervisorError(
                "EvidenceRequestService.drive_acceptance must be callable")

    def handle(self, request: Any, *, peer_uid: Any, conn: Any) -> Dict[str, Any]:
        """Serve one request. There is no ``clock_ms`` parameter, and that is the point:
        §4.10(d) reads no clock. The single admission clock read belongs to §4.10(a0) and
        the single acceptance clock read to §5 step 2; a third one here would be a time
        this turn was judged against that no artifact records."""
        protocol = request.get("protocol") if isinstance(request, Mapping) else None
        if protocol != EVIDENCE_REQUEST_PROTOCOL:
            raise SupervisorError("not the evidence-request protocol: %r" % (protocol,))
        return handle_evidence_request(
            request,
            peer_uid=peer_uid,
            allowed_sidecar_uid=self.allowed_sidecar_uid,
            conn=conn,
            drive_acceptance=self.drive_acceptance,
        )


__all__ = [
    "DIAGNOSTIC_STAGE",
    "EVIDENCE_REQUEST_FIELDS",
    "EVIDENCE_REQUEST_PROTOCOL",
    "EVIDENCE_REQUEST_REFUSAL_REASONS",
    "EVIDENCE_REQUEST_RESULT_PROTOCOL",
    "EvidenceRequestService",
    "GatedTurn",
    "MAX_EVIDENCE_REQUEST_FRAME_BYTES",
    "REFUSE_MALFORMED",
    "REFUSE_NO_INPUTS_READY",
    "REFUSE_PEER_DENIED",
    "REFUSE_RETRY_CONFLICT",
    "REFUSE_SESSION_CORRUPT",
    "STATUS_REFUSED",
    "evidence_request_refused",
    "frame_cap_refusal",
    "gate_evidence_request",
    "handle_evidence_request",
]
