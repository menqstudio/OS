"""AF_UNIX front door for the governed-supervisor (Wave 3b-1B, rev-30 §5).

The PURE decision logic lives in ``governed_supervisor`` (the ``accept_open`` two-phase
verify and the state-driven ``build_run_attestation``); the DURABLE state lives in
``governed_supervisor_ledger``. This module is the wiring ONLY: it binds a unix-domain
socket, authenticates each connecting peer by ``SO_PEERCRED`` uid, allowlists ONLY the
broker uid (the renderer and sidecar are DENIED, matching the challenge-authority front
door), then reads exactly one length-prefixed JSON frame, dispatches it, and writes the
framed reply.

**§5 v2 op set (F-01).** The five ops walk ONE durable attempt through its lifecycle:
``accept-open`` (verify → CAS an acceptance row → lease), ``launch-gate`` (the step-8a
budget gate against the supervisor's OWN persisted lease window, by attempt id),
``execution-started``, ``complete-run`` (the write-once record of what the run produced +
the evidence-head floor), and ``attest-run`` — which now names only
``{run_id, execution_attempt_id}``. It carries no ``facts``: before the fix this endpoint
signed whatever field values arrived on the wire, so the broker uid could mint a signed
receipt for a run that never happened. Every op's request shape is EXHAUSTIVE, so an
old-protocol ``attest-run {facts}`` is a hard error, never a silently-ignored field.

Trust-boundary properties enforced here (all fail-closed):

  * peer authentication happens at accept time via the OS (``SO_PEERCRED``);
    a non-broker peer is refused BEFORE any frame is read.
  * the request frame is length-prefixed (4-byte big-endian) and hard-bounded
    to ``MAX_FRAME_BYTES`` (8192); an oversize/short/truncated frame is refused.
  * ``now_ms`` is NEVER taken from the wire — the supervisor's own clock
    (``clock_ms``) drives every expiry/budget check, so a caller cannot pick a
    favourable time. All other trust decisions stay inside ``governed_supervisor``:
    this module only marshals bytes and never fabricates a lease or a proceed.
  * the socket loop takes an injectable ``accept_one`` so the deny / bounds /
    dispatch behaviour is testable WITHOUT a real socket.

This is a THIN transport wrapper: it imports and calls the supervisor's real
logic and never re-decides authenticity, freshness, binding, or budget. A
:class:`governed_supervisor.Refusal` verdict is relayed as a fail-closed
``ok:false`` reply carrying the typed ``REFUSE_*`` reason; a supervisor-side
:class:`governed_supervisor.SupervisorError` (bad config / seam) and any framing
or request-shape fault likewise become fail-closed error replies.

Only the Python standard library is used. ``SO_PEERCRED`` is Linux-only and is
gated behind a platform check so importing this module never fails elsewhere.
The broker-allowlist predicate is reused from ``challenge_authority`` (the one
canonical, strict, fail-closed peer match) rather than reimplemented here.
"""

from __future__ import annotations

import base64
import json
import socket
import struct
import sys
from typing import Any, Callable, Dict, Mapping, Optional

import governed_supervisor_ledger as ledger
from challenge_authority import peer_is_broker
from governed_supervisor import (
    Accepted,
    Lease,
    Refusal,
    RunAttestation,
    SupervisorConfig,
    SupervisorError,
    accept_open,
    build_execution_receipt,
    build_run_attestation,
    build_terminal_record,
    recompute_request_sha256 as default_recompute_request_sha256,
)
from governed_evidence_request import (
    EVIDENCE_REQUEST_PROTOCOL,
    REFUSE_PEER_DENIED as EVIDENCE_REFUSE_PEER_DENIED,
    EvidenceRequestService,
    evidence_request_refused,
    frame_cap_refusal as evidence_frame_cap_refusal,
)
from governed_staging_upload import (
    MAX_SIDECAR_FRAME_BYTES,
    STAGING_PROTOCOLS,
    StagingService,
    frame_cap_refusal as staging_frame_cap_refusal,
)
from governed_turn_open import (
    OPEN_PROTOCOL,
    REFUSE_PEER_DENIED,
    OpenService,
    peer_is_sidecar,
    refused as open_refused,
)

#: Every protocol the SIDECAR principal is allowed to speak on this socket: the §4.10(a0)
#: open, the three §4.10(a)(b)(c) staging messages, and the §4.10(d) execute/finalize
#: trigger. It is a closed tuple rather than a prefix match, so widening the sidecar's door
#: is an edit to this line and cannot happen by a new protocol merely being named
#: `brops.governed-*`.
SIDECAR_PROTOCOLS = (OPEN_PROTOCOL,) + STAGING_PROTOCOLS + (EVIDENCE_REQUEST_PROTOCOL,)


def frame_cap_refusal(protocol: Any, frame_len: int) -> Optional[Dict[str, Any]]:
    """The per-protocol frame bound for whichever sidecar protocol this is.

    The transport has to read up to the LARGEST cap any sidecar protocol declares (a
    staging chunk is 240 KiB of base64url), so every tighter bound has to be re-imposed on
    the bytes that actually arrived. Each protocol family owns its own table and its own
    over-cap reason, because the reason has to come from that protocol's published closed
    set; this composes them instead of building a third table that could disagree with both.
    An unknown protocol yields ``None`` — whether the sidecar may send it at all is the
    door's question, not this one's.
    """
    return (staging_frame_cap_refusal(protocol, frame_len)
            or evidence_frame_cap_refusal(protocol, frame_len))

# ---------------------------------------------------------------------------
# Wire framing constants (§5 supervisor front door — same shape as §2.1)
# ---------------------------------------------------------------------------

# 4-byte big-endian unsigned length prefix, then the JSON body.
LENGTH_PREFIX_BYTES = 4
# Hard upper bound on a single request/reply body. An accept-open (one signed
# challenge document) / launch-gate (one lease) request is small; anything
# larger is a malformed / hostile frame -> refuse.
MAX_FRAME_BYTES = 8192

OP_ACCEPT_OPEN = "accept-open"
OP_LAUNCH_GATE = "launch-gate"
OP_EXECUTION_STARTED = "execution-started"
OP_COMPLETE_RUN = "complete-run"
OP_ATTEST_RUN = "attest-run"

# The exhaustive field set of a wire lease (mirrors governed_supervisor.Lease). The
# supervisor only ever WRITES this shape now — it is never parsed back off the wire
# (see the §5 v2 note in the module docstring).
LEASE_FIELDS = (
    "lease_id",
    "execution_attempt_id",
    "lease_expires_at_ms",
    "launcher_executable_sha256",
    "executor_executable_sha256",
)

# ---------------------------------------------------------------------------
# Typed refusal reasons this layer adds on top of the pure core's REFUSE_* set.
# Each is a durable-state verdict, so it belongs to the front door, not the core.
# ---------------------------------------------------------------------------

#: The durable CAS refused: a challenge/nonce/attempt/receipt rebound to a different turn.
REFUSE_ACCEPTANCE_CONFLICT = "acceptance_conflict"
#: The reply digest the completion reports is not the digest the recorder captured (audit
#: **F-01**). Typed separately from a malformed chain because the two mean different things: one
#: is a broken deployment, this one is a caller naming output the execution did not produce.
REFUSE_EVIDENCE_MISMATCH = "evidence_mismatch"
#: The named attempt has no acceptance row — a fabricated or already-purged attempt.
REFUSE_UNKNOWN_ATTEMPT = "unknown_attempt"
#: The requested lifecycle move is not legal from the attempt's current durable state.
REFUSE_ILLEGAL_STATE = "illegal_state"
#: A second completion tried to rewrite facts already recorded for this attempt.
REFUSE_COMPLETION_CONFLICT = "completion_conflict"
#: The evidence head is older than, or forks, the durable anti-rollback floor.
REFUSE_STALE_EVIDENCE = "stale_evidence"
REFUSE_EVIDENCE_FORK = "evidence_fork"
#: `attest-run` names a run the supervisor has no COMPLETED terminal state for. This is
#: the F-01 wall: with no durable state there is no evidence and no signature.
REFUSE_NO_TERMINAL_RUN = "no_terminal_run_state"
#: A ledger fault with no more specific typed reason (malformed completion facts, a
#: corrupt stored row). Still a refusal — the supervisor records nothing and signs nothing.
REFUSE_MALFORMED_STATE = "malformed_state"


class ServerError(Exception):
    """A transport-level fault: malformed request body, bad lease shape, or an
    unknown op. Fail-closed, converted to an ``ok:false`` error reply — never a
    fabricated success."""


class FrameError(ServerError):
    """Raised on any framing violation (oversize, short, truncated, non-JSON)."""


# ---------------------------------------------------------------------------
# Peer credential resolution (Linux SO_PEERCRED; fail-closed elsewhere)
# ---------------------------------------------------------------------------


def read_peercred_uid(sock: "socket.socket") -> int:
    """Return the connecting peer's uid via ``SO_PEERCRED``.

    Linux-only: ``SO_PEERCRED`` yields ``struct ucred { pid, uid, gid }`` which
    we unpack as ``=III``. On any non-Linux host this fails closed with a
    ``ServerError`` so the caller can DENY rather than trust an unauthenticated
    peer.
    """
    if sys.platform != "linux":
        raise ServerError(
            "platform unsupported: SO_PEERCRED peer authentication requires Linux"
        )
    # struct ucred is {pid_t pid; uid_t uid; gid_t gid;} == three 32-bit ints.
    ucred = sock.getsockopt(
        socket.SOL_SOCKET,
        socket.SO_PEERCRED,  # type: ignore[attr-defined]
        struct.calcsize("=III"),
    )
    _pid, uid, _gid = struct.unpack("=III", ucred)
    return uid


# ---------------------------------------------------------------------------
# Connection abstraction (real socket + injectable fake share this shape)
# ---------------------------------------------------------------------------


class SocketPeerConn:
    """Adapter around a live accepted socket exposing the duck-typed shape the
    server loop consumes: ``peer_uid``, ``recv_exactly``, ``send_all``,
    ``close``.

    The peer uid is captured ONCE, at accept time, from the kernel — it is not
    caller-supplied and cannot be spoofed over the wire.
    """

    def __init__(self, sock: "socket.socket") -> None:
        self._sock = sock
        self.peer_uid = read_peercred_uid(sock)

    def recv_exactly(self, n: int) -> bytes:
        chunks = []
        remaining = n
        while remaining > 0:
            chunk = self._sock.recv(remaining)
            if not chunk:
                break  # peer closed early; caller detects the short read
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def send_all(self, data: bytes) -> None:
        self._sock.sendall(data)

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Framing (length-prefixed, bounded)
# ---------------------------------------------------------------------------


def read_frame(conn: Any, max_bytes: int = MAX_FRAME_BYTES) -> bytes:
    """Read exactly one length-prefixed frame, bounded to ``max_bytes``.

    Fail-closed on a short header, a zero/oversize declared length, or a
    truncated body.

    The bound is a parameter because the two principals on this socket carry different
    traffic (§2.4/§4.10(b)). The broker's ``op`` frames stay at the deliberately tight
    8 KiB; the sidecar's staging chunk is 240 KiB of base64url by design and cannot be made
    smaller without breaking the design's own frame-sizing proof. Raising the module
    constant instead would have widened the broker's surface to buy the sidecar's, so the
    two are separated rather than merged — and the sidecar's larger read is immediately
    narrowed again per-protocol by ``governed_staging_upload.frame_cap_refusal``.
    """
    header = conn.recv_exactly(LENGTH_PREFIX_BYTES)
    if len(header) != LENGTH_PREFIX_BYTES:
        raise FrameError("short length prefix")
    length = int.from_bytes(header, "big")
    if length == 0:
        raise FrameError("empty frame rejected")
    if length > max_bytes:
        raise FrameError(
            "frame length %d exceeds bound %d" % (length, max_bytes)
        )
    body = conn.recv_exactly(length)
    if len(body) != length:
        raise FrameError("truncated frame body")
    return body


def write_frame(conn: Any, payload: bytes, max_bytes: int = MAX_FRAME_BYTES) -> None:
    """Write one length-prefixed frame. The reply is supervisor-built and small;
    an over-bound reply is a programming error, not attacker input, so we still
    refuse it rather than emit an un-framable blob."""
    if len(payload) > max_bytes:
        raise FrameError("reply exceeds frame bound")
    conn.send_all(len(payload).to_bytes(LENGTH_PREFIX_BYTES, "big") + payload)


def _encode_reply(reply: Mapping[str, Any]) -> bytes:
    return json.dumps(reply, separators=(",", ":")).encode("utf-8")


# ---------------------------------------------------------------------------
# Result marshalling (supervisor verdict -> fail-closed reply, never invented)
# ---------------------------------------------------------------------------


def _lease_to_dict(lease: Lease) -> Dict[str, Any]:
    return {
        "lease_id": lease.lease_id,
        "execution_attempt_id": lease.execution_attempt_id,
        "lease_expires_at_ms": lease.lease_expires_at_ms,
        "launcher_executable_sha256": lease.launcher_executable_sha256,
        "executor_executable_sha256": lease.executor_executable_sha256,
    }


def _b64url_nopad(data: bytes) -> str:
    """base64url WITHOUT padding — the §4.1/§4.2 ``*_b64`` transport convention the
    Rust broker decodes with ``URL_SAFE_NO_PAD``."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _attestation_reply(attn: RunAttestation) -> Dict[str, Any]:
    """Marshal the supervisor-built run-attestation into the wire reply. The
    ``attestation`` object is relayed verbatim (the exact 3-field shape the
    isolated signer verifies); ``evidence_jcs_b64`` carries the EXACT JCS bytes the
    supervisor signed so the signer/broker can re-hash them, and
    ``attestation_evidence_sha256`` echoes ``sha256(evidence_jcs)`` for convenience."""
    return {
        "ok": True,
        "op": OP_ATTEST_RUN,
        "attestation": dict(attn.attestation),
        "evidence_jcs_b64": _b64url_nopad(attn.evidence_jcs),
        "attestation_evidence_sha256": attn.attestation_evidence_sha256,
    }


def _refusal_reply(op: str, refusal: Refusal) -> Dict[str, Any]:
    # A refusal is a fail-closed verdict, NOT a success. It surfaces as ok:false
    # with the typed REFUSE_* reason so the broker sees the exact denial cause.
    return {
        "ok": False,
        "op": op,
        "reason": refusal.reason,
        "detail": refusal.detail,
        "error": refusal.detail,
    }


def _refusal(op: str, reason: str, detail: str) -> Dict[str, Any]:
    """A fail-closed durable-state verdict in the same wire shape as a core refusal."""
    return {"ok": False, "op": op, "reason": reason, "detail": detail, "error": detail}


def _require_exact_fields(request: Mapping[str, Any], op: str, fields: tuple) -> None:
    """Enforce the EXHAUSTIVE request shape for an op.

    Unknown fields are rejected rather than ignored. That is not pedantry: a caller still
    speaking the pre-F-01 protocol sends ``attest-run {facts: {...}}``, and silently
    dropping ``facts`` would let it believe its chosen evidence had been attested. It gets
    a hard ``ServerError`` instead.
    """
    allowed = {"op"} | set(fields)
    keys = set(request.keys())
    extra = keys - allowed
    if extra:
        raise ServerError("%s has unexpected field(s) %s" % (op, sorted(extra)))
    missing = allowed - keys
    if missing:
        raise ServerError("%s is missing field(s) %s" % (op, sorted(missing)))


def _require_str(request: Mapping[str, Any], name: str) -> str:
    value = request.get(name)
    if not isinstance(value, str) or not value:
        raise ServerError("%s must be a non-empty string" % name)
    return value


def _ledger_refusal(op: str, exc: ledger.LedgerError) -> Dict[str, Any]:
    """Map a durable-ledger fault onto its typed wire refusal. Every branch is a REFUSAL,
    never a success — an operation the ledger would not record is an operation that did
    not happen."""
    if isinstance(exc, ledger.NotFound):
        return _refusal(op, REFUSE_UNKNOWN_ATTEMPT, str(exc))
    if isinstance(exc, ledger.IllegalTransition):
        return _refusal(op, REFUSE_ILLEGAL_STATE, str(exc))
    if isinstance(exc, ledger.StaleEvidence):
        return _refusal(op, REFUSE_STALE_EVIDENCE, str(exc))
    if isinstance(exc, ledger.EvidenceFork):
        return _refusal(op, REFUSE_EVIDENCE_FORK, str(exc))
    if isinstance(exc, ledger.Conflict):
        reason = (
            REFUSE_COMPLETION_CONFLICT
            if op == OP_COMPLETE_RUN
            else REFUSE_ACCEPTANCE_CONFLICT
        )
        return _refusal(op, reason, str(exc))
    # InvalidHead / Corrupt / a shape error from validate_completion_facts / anything else.
    return _refusal(op, REFUSE_MALFORMED_STATE, str(exc))


# ---------------------------------------------------------------------------
# Dispatch (thin adapter onto the pure core; no new trust logic)
# ---------------------------------------------------------------------------


def dispatch(
    request: Any,
    config: SupervisorConfig,
    verify_sig: Callable[[bytes, str], bool],
    recompute_request_sha256: Callable[[Mapping[str, Any]], str],
    clock_ms: Callable[[], int],
    *,
    conn: Any,
    publish_artifact: Optional[Callable[[bytes], str]] = None,
    read_run_evidence: Optional[Callable[[str], Optional[bytes]]] = None,
    sign_attestation: Optional[Callable[[bytes], str]] = None,
    supervisor_attestation_key_id: Optional[str] = None,
    open_service: Optional[OpenService] = None,
    staging_service: Optional[StagingService] = None,
    evidence_request_service: Optional[EvidenceRequestService] = None,
    peer_uid: Any = None,
) -> Dict[str, Any]:
    """Route one decoded request into the pure supervisor core + the durable ledger.

    **Two disjoint frame families, discriminated by their own top-level key.** The §5 ops
    below are keyed on ``op`` and come from the BROKER. ``brops.governed-turn-open.v1``
    (§4.10(a0)) is keyed on ``protocol`` and comes from the SIDECAR — a different principal,
    a different reply shape, and a different refusal vocabulary. Routing on the key each
    family actually carries keeps them from ever being confusable: an ``op`` frame can never
    be answered with a governed-turn-open verdict, and vice versa.

    ``open_service`` is the §4.10(a0) binding; without it that protocol is served by nobody
    and every such request is ``peer_denied`` — a supervisor with no configured sidecar
    principal, store publish or registry anchor admits no turn. ``staging_service`` and
    ``evidence_request_service`` are the §4.10(a)(b)(c) and §4.10(d) bindings and fail
    closed the same way.

    The §5 v2 op set, in lifecycle order — each one moves the SAME durable attempt forward:

      * ``accept-open {challenge_doc}`` — two-phase verify, then CAS a durable acceptance
        row into existence and return its lease. A replayed challenge returns the ORIGINAL
        lease; it never mints a second attempt.
      * ``launch-gate {execution_attempt_id}`` — the §5 step-8a budget gate against the
        lease window the SUPERVISOR persisted, then ``LEASE_READY → EXECUTION_STARTING``
        (or ``EXPIRED``). The caller no longer presents a lease, so it can no longer choose
        the expiry it is judged against.
      * ``execution-started {execution_attempt_id, …}`` — ``EXECUTION_STARTING → EXECUTING``.
      * ``complete-run {execution_attempt_id, produced}`` — the WRITE-ONCE record of what the
        run produced, plus the evidence-head anti-rollback floor, then ``→ COMPLETED``.
      * ``attest-run {run_id, execution_attempt_id}`` — build the §4.9 evidence from that
        durable terminal state and sign it.

    **F-01.** ``attest-run`` carries no ``facts``. Its request shape is exhaustive, so the
    old protocol's ``facts`` object is a hard error rather than a silently-ignored field,
    and the evidence is assembled from ledger state the caller never touched. A run that was
    not accepted, leased, gated, started and completed here has no state — and therefore
    gets ``no_terminal_run_state``, not a signature.

    The supervisor's own clock (``clock_ms``) supplies ``now_ms`` everywhere; it is never
    read from the wire, so a caller cannot pick a favourable time.

    ``conn`` is the durable ledger connection and is REQUIRED — a supervisor with no durable
    state must refuse to serve rather than run stateless. ``attest-run`` additionally needs
    the injected ``sign_attestation`` seam + the pinned ``supervisor_attestation_key_id``; a
    request for it without them is a supervisor-side config fault (fail-closed error reply),
    never a fabricated attestation.
    """
    if not isinstance(request, Mapping):
        raise ServerError("request body must be a JSON object")
    if conn is None:
        raise SupervisorError("supervisor requires a durable ledger connection")

    # §4.10(a0) — the sidecar's protocol-keyed frame. Checked FIRST and by its own key, so a
    # frame carrying both `protocol` and `op` is answered as the open it declares itself to
    # be rather than smuggling an op through the sidecar's door.
    if request.get("protocol") == OPEN_PROTOCOL:
        if open_service is None:
            return open_refused(REFUSE_PEER_DENIED)
        return open_service.handle(request, peer_uid=peer_uid, conn=conn, clock_ms=clock_ms)

    # §4.10(a)(b)(c) — the three staging-upload protocols, keyed the same way. Without a
    # `staging_service` they are served by nobody: the handlers are reached through an
    # UNCONFIGURABLE peer uid, so every such request refuses on the peer check rather than
    # this layer inventing a verdict in a vocabulary that is not its own.
    if request.get("protocol") in STAGING_PROTOCOLS:
        if staging_service is None:
            return _staging_unconfigured(request)
        return staging_service.handle(
            request, peer_uid=peer_uid, conn=conn, clock_ms=clock_ms
        )

    # §4.10(d) - the execute/finalize trigger, keyed the same way. Without an
    # `evidence_request_service` it is served by nobody: the supervisor has not been told
    # what happens when a turn is admitted to execute, so it admits none. The reply is that
    # protocol's own `peer_denied`, the §4.10(a0) precedent - an unconfigured principal is
    # not a peer this supervisor serves. It takes no clock: §4.10(d) reads none.
    if request.get("protocol") == EVIDENCE_REQUEST_PROTOCOL:
        if evidence_request_service is None:
            return evidence_request_refused(EVIDENCE_REFUSE_PEER_DENIED)
        return evidence_request_service.handle(request, peer_uid=peer_uid, conn=conn)

    op = request.get("op")

    if op == OP_ATTEST_RUN:
        return _op_attest_run(request, config, conn, sign_attestation,
                              supervisor_attestation_key_id)
    if op == OP_ACCEPT_OPEN:
        return _op_accept_open(request, config, conn, verify_sig,
                               recompute_request_sha256, clock_ms)
    if op == OP_LAUNCH_GATE:
        return _op_launch_gate(request, conn, clock_ms)
    if op == OP_EXECUTION_STARTED:
        return _op_execution_started(request, conn, clock_ms)
    if op == OP_COMPLETE_RUN:
        return _op_complete_run(request, conn, clock_ms, publish_artifact, read_run_evidence)

    raise ServerError("unknown op %r" % (op,))


def _staging_unconfigured(request: Mapping[str, Any]) -> Dict[str, Any]:
    """A staging message on a supervisor with no ``StagingService``.

    The reply is produced by the protocol's OWN handler with an impossible sidecar uid
    (``None``, which ``peer_is_sidecar`` refuses fail-closed), rather than assembled here.
    That way this layer never has to know which reason each of the three closed sets uses
    for "you are not allowed to send this" — it asks the module that owns the set.
    """
    from governed_staging_upload import (
        STAGING_CHUNK_PROTOCOL,
        STAGING_FINAL_PROTOCOL,
        STAGING_OPEN_PROTOCOL,
        staging_open_refused,
        chunk_refused,
        final_refused,
        REFUSE_MALFORMED,
        REFUSE_PEER_DENIED as STAGING_PEER_DENIED,
    )

    protocol = request.get("protocol")
    if protocol == STAGING_OPEN_PROTOCOL:
        return staging_open_refused(STAGING_PEER_DENIED)
    if protocol == STAGING_CHUNK_PROTOCOL:
        return chunk_refused(REFUSE_MALFORMED, 0)
    if protocol == STAGING_FINAL_PROTOCOL:
        return final_refused(REFUSE_MALFORMED)
    raise ServerError("unknown staging protocol %r" % (protocol,))


def _op_accept_open(request, config, conn, verify_sig, recompute_request_sha256, clock_ms):
    _require_exact_fields(request, OP_ACCEPT_OPEN, ("challenge_doc",))
    challenge_doc = request["challenge_doc"]
    if not isinstance(challenge_doc, Mapping):
        raise ServerError("accept-open requires a challenge_doc object")

    # now_ms is the SUPERVISOR's clock, not the caller's (fail-closed).
    now = clock_ms()
    result = accept_open(
        challenge_doc,
        now,
        config=config,
        verify_sig=verify_sig,
        recompute_request_sha256=recompute_request_sha256,
    )
    if isinstance(result, Refusal):
        return _refusal_reply(OP_ACCEPT_OPEN, result)
    if not isinstance(result, Accepted):
        # The pure core only ever returns Accepted | Refusal; anything else is a contract
        # breach -> fail closed rather than relay an unknown object.
        raise SupervisorError("accept_open returned an unexpected result type")

    try:
        outcome, row = ledger.reuse_or_prepare(conn, result.acceptance, now)
    except ledger.LedgerError as exc:
        return _ledger_refusal(OP_ACCEPT_OPEN, exc)

    if outcome == ledger.CREATED:
        lease = result.lease
    else:
        # This exact signed challenge was already accepted: hand back the ORIGINAL lease,
        # rebuilt from durable state. The freshly-minted ids from this call are discarded,
        # so a replay buys the caller nothing — the same one attempt, the same one receipt.
        lease = Lease(
            lease_id=row["lease_id"],
            execution_attempt_id=row["execution_attempt_id"],
            lease_expires_at_ms=row["lease_expires_at_ms"],
            launcher_executable_sha256=config.launcher_executable_sha256,
            executor_executable_sha256=config.executor_executable_sha256,
        )

    # Publish the lease: ACCEPTED_PREPARED -> LEASE_READY, keyed on the content address of
    # the exact lease bytes persisted at acceptance. Idempotent across a crash-retry that
    # committed the row but not the advance.
    if row["state"] == ledger.ACCEPTED_PREPARED:
        try:
            ledger.mark_lease_ready(conn, lease.execution_attempt_id,
                                    row["lease_payload_sha256"], now)
        except ledger.LedgerError as exc:
            return _ledger_refusal(OP_ACCEPT_OPEN, exc)

    return {"ok": True, "op": OP_ACCEPT_OPEN, "lease": _lease_to_dict(lease)}


def _op_launch_gate(request, conn, clock_ms):
    _require_exact_fields(request, OP_LAUNCH_GATE, ("execution_attempt_id",))
    attempt = _require_str(request, "execution_attempt_id")
    try:
        state = ledger.gate_and_start(conn, attempt, clock_ms())
    except ledger.LedgerError as exc:
        return _ledger_refusal(OP_LAUNCH_GATE, exc)
    if state == ledger.EXECUTION_STARTING:
        return {"ok": True, "op": OP_LAUNCH_GATE, "proceed": True,
                "execution_attempt_id": attempt}
    # The gate failed against the supervisor's OWN lease window: the attempt is durably
    # EXPIRED and no launch may follow.
    return _refusal(OP_LAUNCH_GATE, "lease_expired",
                    "remaining lease budget below %d ms" % ledger.MIN_LAUNCH_REMAINING_MS)


def _op_execution_started(request, conn, clock_ms):
    _require_exact_fields(
        request, OP_EXECUTION_STARTED,
        ("execution_attempt_id", "process_group_id", "cgroup_id", "execution_started_marker"),
    )
    attempt = _require_str(request, "execution_attempt_id")
    marker = request["execution_started_marker"]
    if marker is not None and (not isinstance(marker, str) or not marker):
        raise ServerError("execution_started_marker must be a non-empty string or null")
    try:
        ledger.mark_executing(
            conn, attempt,
            process_group_id=_require_str(request, "process_group_id"),
            cgroup_id=_require_str(request, "cgroup_id"),
            execution_started_marker=marker,
            now_ms=clock_ms(),
        )
    except ledger.LedgerError as exc:
        return _ledger_refusal(OP_EXECUTION_STARTED, exc)
    return {"ok": True, "op": OP_EXECUTION_STARTED, "execution_attempt_id": attempt}


def _op_complete_run(request, conn, clock_ms, publish_artifact, read_run_evidence):
    _require_exact_fields(request, OP_COMPLETE_RUN, ("execution_attempt_id", "produced"))
    attempt = _require_str(request, "execution_attempt_id")
    if publish_artifact is None:
        raise SupervisorError(
            "complete-run requires an injected publish_artifact seam (the supervisor must be "
            "able to publish the terminal artifacts it addresses)"
        )
    if read_run_evidence is None:
        raise SupervisorError(
            "complete-run requires an injected read_run_evidence seam: the supervisor must read "
            "the recorder's evidence chain ITSELF (audit F-01) — taking the evidence head, or the "
            "reply digest it commits to, from the caller is the oracle in its most valuable form"
        )
    row = ledger.load_acceptance(conn, attempt)
    if row is None:
        return _refusal(OP_COMPLETE_RUN, REFUSE_UNKNOWN_ATTEMPT,
                        "no acceptance row for attempt %r" % (attempt,))
    try:
        produced = ledger.validate_completion_facts(request["produced"])
    except ledger.LedgerError as exc:
        return _ledger_refusal(OP_COMPLETE_RUN, exc)

    # (audit F-01) Read the RECORDER's evidence chain for this attempt — from a directory only
    # the recorder can write, never from the wire and never from the content-addressed store,
    # because a store handle the caller names addresses bytes the caller can also have written.
    # This is the first point in the protocol where the supervisor looks at something the
    # executing chain did not choose. It yields the evidence head, and it refuses outright if the
    # reply digest the completion reports is not the digest the recorder actually captured.
    try:
        chain_bytes = read_run_evidence(attempt)
    except Exception as exc:
        return _refusal(OP_COMPLETE_RUN, REFUSE_MALFORMED_STATE,
                        "could not read the run evidence chain: %s" % exc)
    if not chain_bytes:
        return _refusal(OP_COMPLETE_RUN, REFUSE_MALFORMED_STATE,
                        "no run evidence chain for attempt %r; a run whose execution the "
                        "supervisor cannot observe must not be recorded" % (attempt,))
    try:
        evidence = ledger.derive_evidence_from_chain(chain_bytes, produced["output_handle"])
    except ledger.EvidenceMismatch as exc:
        return _refusal(OP_COMPLETE_RUN, REFUSE_EVIDENCE_MISMATCH, str(exc))
    except ledger.LedgerError as exc:
        return _ledger_refusal(OP_COMPLETE_RUN, exc)

    # F-02: the supervisor BUILDS its terminal artifacts from its own rows and publishes them
    # to the protected store, then names their content addresses in the evidence. These were
    # deployment-static constants the broker copied out of a world-readable config, which made
    # the isolated signer's protected-chain check a tautology over bytes anyone had written once.
    try:
        derived = dict(evidence)
        derived.update({
            "lease_handle": publish_artifact(bytes(row["lease_payload_bytes"])),
            "record_handle": publish_artifact(build_terminal_record(row, produced)),
            "execution_receipt_handle": publish_artifact(build_execution_receipt(row, produced)),
        })
    except Exception as exc:  # a store failure must refuse the completion, never fake a handle
        return _refusal(OP_COMPLETE_RUN, REFUSE_MALFORMED_STATE,
                        "could not publish terminal artifacts: %s" % exc)

    try:
        outcome = ledger.record_completion(conn, attempt, request["produced"], clock_ms(),
                                           derived=derived)
    except ledger.LedgerError as exc:
        return _ledger_refusal(OP_COMPLETE_RUN, exc)
    return {"ok": True, "op": OP_COMPLETE_RUN, "execution_attempt_id": attempt,
            "recorded": outcome}


def _op_attest_run(request, config, conn, sign_attestation, supervisor_attestation_key_id):
    if sign_attestation is None or supervisor_attestation_key_id is None:
        raise SupervisorError(
            "attest-run requires an injected sign_attestation seam and "
            "supervisor_attestation_key_id"
        )
    # Exhaustive: `facts` is no longer part of this protocol, so an old-protocol caller
    # gets a hard error instead of an attestation over evidence it chose (F-01).
    _require_exact_fields(request, OP_ATTEST_RUN, ("run_id", "execution_attempt_id"))
    run_id = _require_str(request, "run_id")
    attempt = _require_str(request, "execution_attempt_id")

    state = ledger.load_attestation_state(conn, run_id, attempt)
    if state is None:
        # No acceptance, no completion, a mismatched run_id, or a non-terminal/failed run.
        # THE F-01 WALL: the supervisor has nothing to attest, and no argument through which
        # the caller could supply the missing facts.
        return _refusal(
            OP_ATTEST_RUN, REFUSE_NO_TERMINAL_RUN,
            "no COMPLETED terminal run state for run_id/execution_attempt_id",
        )

    result = build_run_attestation(
        state,
        config=config,
        supervisor_key_id=supervisor_attestation_key_id,
        sign_attestation=sign_attestation,
    )
    if isinstance(result, RunAttestation):
        return _attestation_reply(result)
    if isinstance(result, Refusal):
        return _refusal_reply(OP_ATTEST_RUN, result)
    raise SupervisorError("build_run_attestation returned an unexpected result type")


# ---------------------------------------------------------------------------
# Per-connection handling (peer-auth -> frame -> dispatch -> framed reply)
# ---------------------------------------------------------------------------


def handle_connection(
    conn: Any,
    allowed_broker_uid: int,
    config: SupervisorConfig,
    verify_sig: Callable[[bytes, str], bool],
    recompute_request_sha256: Callable[[Mapping[str, Any]], str],
    clock_ms: Callable[[], int],
    *,
    ledger_conn: Any,
    publish_artifact: Optional[Callable[[bytes], str]] = None,
    read_run_evidence: Optional[Callable[[str], Optional[bytes]]] = None,
    sign_attestation: Optional[Callable[[bytes], str]] = None,
    supervisor_attestation_key_id: Optional[str] = None,
    open_service: Optional[OpenService] = None,
    staging_service: Optional[StagingService] = None,
    evidence_request_service: Optional[EvidenceRequestService] = None,
) -> Dict[str, Any]:
    """Authenticate the peer, read one bounded frame, dispatch, and write the
    framed reply. Returns the reply object (also useful for tests). Never raises
    on hostile input — every failure becomes a fail-closed error reply.

    ``ledger_conn`` is the supervisor's durable ledger; every lifecycle op needs it.
    ``sign_attestation`` + ``supervisor_attestation_key_id`` enable the ``attest-run`` op;
    omit them and only the lifecycle ops are served.

    **Two principals, two disjoint surfaces (§2.6 / §4.10(a0)).** The broker uid drives the
    §5 ``op`` lifecycle. The sidecar uid — supplied only via ``open_service`` /
    ``staging_service`` / ``evidence_request_service``, and DENIED entirely when none is
    present — may send exactly the five protocols in ``SIDECAR_PROTOCOLS``: the §4.10(a0)
    open, the three §4.10(a)(b)(c) staging messages, and the §4.10(d) execute/finalize
    trigger. A sidecar-authenticated connection presenting an ``op`` frame is refused as an
    unauthorized peer, so admitting the sidecar to this socket widens the door by exactly
    five protocol names and not by one op.

    **Two frame bounds, not one (§4.10(b)).** The broker's read stays at the tight 8 KiB.
    The sidecar's read is the largest cap any of its five protocols declares (262144, the
    staging chunk), and the exact bytes that arrived are then re-checked against that
    protocol's OWN cap — so a 200 KiB `governed-staging-open` is still refused even though
    the transport was willing to read it, and the §4.10(a0) "frame ≤ 8 KiB" survives the
    widening.

    A configuration where the broker uid EQUALS the sidecar uid is refused outright rather
    than served: that is the §2.6 single-UID collapse, and under it every ACL in this design
    means nothing. It fails closed at the door, before a frame is read, because a supervisor
    cannot detect the collapse later from anything a peer sends.
    """
    peer_uid = getattr(conn, "peer_uid", None)
    configured = [
        service.allowed_sidecar_uid
        for service in (open_service, staging_service, evidence_request_service)
        if service is not None
    ]

    # Two services naming DIFFERENT sidecar uids is a mis-provisioned supervisor, not a
    # richer one: it would mean one principal may open turns, another may upload their
    # inputs and a third may trigger execution, which no part of §2.6 describes. Refuse at
    # the door rather than pick one.
    if len(set(configured)) > 1:
        reply = {"ok": False, "error": "principal split: the sidecar services name different sidecar uids"}
        _try_write(conn, reply)
        return reply
    sidecar_uid = configured[0] if configured else None

    if sidecar_uid is not None and peer_is_broker(sidecar_uid, allowed_broker_uid):
        reply = {"ok": False, "error": "principal collapse: sidecar uid equals broker uid"}
        _try_write(conn, reply)
        return reply

    broker_peer = peer_is_broker(peer_uid, allowed_broker_uid)
    sidecar_peer = sidecar_uid is not None and peer_is_sidecar(peer_uid, sidecar_uid)
    # Refuse an unknown peer BEFORE reading any frame.
    if not (broker_peer or sidecar_peer):
        reply = {"ok": False, "error": "peer not authorized"}
        _try_write(conn, reply)
        return reply

    try:
        raw = read_frame(conn, MAX_FRAME_BYTES if broker_peer else MAX_SIDECAR_FRAME_BYTES)
        request = json.loads(raw.decode("utf-8"))
        # The sidecar's grant is four protocol names wide. Anything else it sends is refused
        # here, in the transport, so the op handlers below never see a non-broker caller.
        if not broker_peer and (
            not isinstance(request, dict) or request.get("protocol") not in SIDECAR_PROTOCOLS
        ):
            reply = {"ok": False, "error": "peer not authorized"}
            _try_write(conn, reply)
            return reply
        # The per-protocol frame cap, applied to the bytes that actually arrived. The
        # transport had to read up to the largest of them to reach this line; this is where
        # the tighter ones are re-imposed.
        if not broker_peer:
            over = frame_cap_refusal(request.get("protocol"), len(raw))
            if over is not None:
                _try_write(conn, over)
                return over
        reply = dispatch(
            request,
            config,
            verify_sig,
            recompute_request_sha256,
            clock_ms,
            conn=ledger_conn,
            publish_artifact=publish_artifact,
            read_run_evidence=read_run_evidence,
            sign_attestation=sign_attestation,
            supervisor_attestation_key_id=supervisor_attestation_key_id,
            open_service=open_service,
            staging_service=staging_service,
            evidence_request_service=evidence_request_service,
            peer_uid=peer_uid,
        )
    except (FrameError, ServerError, SupervisorError, ValueError, UnicodeDecodeError) as exc:
        reply = {"ok": False, "error": _bounded_error(str(exc))}
        # Surface a typed refusal reason if the exception carried one (a Refusal
        # verdict is relayed via dispatch, not raised — this is for completeness).
        reason = getattr(exc, "reason", None)
        if isinstance(reason, str) and reason:
            reply["reason"] = reason

    _try_write(conn, reply)
    return reply


#: Hard cap on the error text echoed back to the peer. The exhaustive per-op shape checks
#: quote the offending field names, and `repr()` of a hostile op expands non-printables
#: ~4x, so an unbounded message is an amplifier: one legal 8 KiB request could produce a
#: reply too large to frame. Bounding it here keeps every reply framable by construction.
MAX_ERROR_CHARS = 512


def _bounded_error(text: str) -> str:
    if len(text) <= MAX_ERROR_CHARS:
        return text
    return text[:MAX_ERROR_CHARS] + "… (truncated)"


def _try_write(conn: Any, reply: Mapping[str, Any]) -> None:
    """Write the framed reply, never letting a reply problem escape.

    A `FrameError` here would otherwise propagate out of `handle_connection` — past the
    try/except above, which has already closed — and out of `serve_forever`, killing the
    process that issues every lease and produces every attestation (independent audit
    F-11). Replies are bounded by construction now; this is the belt for that braces: an
    over-bound reply degrades to a minimal typed refusal, and a dead peer is ignored.
    """
    try:
        write_frame(conn, _encode_reply(reply))
        return
    except OSError:
        return  # peer already gone; nothing to do, connection is closed by loop
    except FrameError:
        pass  # fall through to the minimal reply below
    try:
        write_frame(conn, _encode_reply({"ok": False, "error": "reply exceeded frame bound"}))
    except (OSError, FrameError):
        pass  # nothing further is possible; the loop closes the connection


# ---------------------------------------------------------------------------
# Socket loop (injectable accept_one -> testable without a real socket)
# ---------------------------------------------------------------------------


def serve_forever(
    accept_one: Callable[[], Optional[Any]],
    allowed_broker_uid: int,
    config: SupervisorConfig,
    verify_sig: Callable[[bytes, str], bool],
    recompute_request_sha256: Callable[[Mapping[str, Any]], str],
    clock_ms: Callable[[], int],
    *,
    ledger_conn: Any,
    publish_artifact: Optional[Callable[[bytes], str]] = None,
    read_run_evidence: Optional[Callable[[str], Optional[bytes]]] = None,
    sign_attestation: Optional[Callable[[bytes], str]] = None,
    supervisor_attestation_key_id: Optional[str] = None,
    open_service: Optional[OpenService] = None,
    staging_service: Optional[StagingService] = None,
    evidence_request_service: Optional[EvidenceRequestService] = None,
) -> None:
    """Drive the accept loop. ``accept_one`` returns the next connection (any
    object with ``peer_uid`` / ``recv_exactly`` / ``send_all`` / ``close``) or
    ``None`` to stop. A real deployment passes a socket-backed acceptor; a test
    passes a fake that yields ``SocketPeerConn``-shaped stand-ins.

    A single hostile connection never tears down the loop: each is handled in
    isolation and always closed.
    """
    while True:
        conn = accept_one()
        if conn is None:
            return
        try:
            handle_connection(
                conn,
                allowed_broker_uid,
                config,
                verify_sig,
                recompute_request_sha256,
                clock_ms,
                ledger_conn=ledger_conn,
                publish_artifact=publish_artifact,
                read_run_evidence=read_run_evidence,
                sign_attestation=sign_attestation,
                supervisor_attestation_key_id=supervisor_attestation_key_id,
                open_service=open_service,
                staging_service=staging_service,
                evidence_request_service=evidence_request_service,
            )
        finally:
            try:
                conn.close()
            except OSError:
                pass


def bind_listener(socket_path: str) -> "socket.socket":
    """Bind a fresh AF_UNIX stream listener at ``socket_path`` (Linux path).

    Fail-closed on non-Linux hosts: the peer-credential trust chain this service
    depends on (``SO_PEERCRED``) does not exist there.
    """
    if sys.platform != "linux":
        raise ServerError(
            "platform unsupported: AF_UNIX SO_PEERCRED supervisor front door requires Linux"
        )
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(socket_path)
    listener.listen(64)
    return listener


def accept_socket_conn(listener: "socket.socket") -> SocketPeerConn:
    """Accept one connection and resolve its peer uid from the kernel."""
    sock, _addr = listener.accept()
    return SocketPeerConn(sock)


# ``default_recompute_request_sha256`` is re-exported as the natural default
# binding seam for a real deployment (the supervisor's OWN canonical recompute).
__all__ = [
    "LENGTH_PREFIX_BYTES",
    "MAX_FRAME_BYTES",
    "MAX_SIDECAR_FRAME_BYTES",
    "SIDECAR_PROTOCOLS",
    "frame_cap_refusal",
    "OP_ACCEPT_OPEN",
    "OP_LAUNCH_GATE",
    "OP_EXECUTION_STARTED",
    "OP_COMPLETE_RUN",
    "REFUSE_EVIDENCE_MISMATCH",
    "OP_ATTEST_RUN",
    "REFUSE_ACCEPTANCE_CONFLICT",
    "REFUSE_COMPLETION_CONFLICT",
    "REFUSE_EVIDENCE_FORK",
    "REFUSE_ILLEGAL_STATE",
    "REFUSE_MALFORMED_STATE",
    "REFUSE_NO_TERMINAL_RUN",
    "REFUSE_STALE_EVIDENCE",
    "REFUSE_UNKNOWN_ATTEMPT",
    "FrameError",
    "ServerError",
    "SocketPeerConn",
    "accept_socket_conn",
    "bind_listener",
    "default_recompute_request_sha256",
    "dispatch",
    "handle_connection",
    "read_frame",
    "serve_forever",
    "write_frame",
]
