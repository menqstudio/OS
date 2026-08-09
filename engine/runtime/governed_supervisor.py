"""governed-supervisor acceptance/lease service core (Wave 3b-1B, rev-30 §5).

PURE, socket-free, key-free service-side decision logic for the supervisor's
governed-turn acceptance path. The DURABLE state machine + outbox + evidence floor
live in :mod:`governed_supervisor_ledger` over the SHARED DDL it loads from
``supervisor_ledger.sql`` (the same SQL the Rust ``brops-core::supervisor_ledger``
compiles in, byte-equality enforced by ``tools/check_ledger_ddl_parity.py``). This
module is the pure *decision* layer that sits in front of that ledger:

**F-01 (independent audit 2026-08-06, P0) — what changed and why.** This module used
to expose ``build_run_attestation(facts, …)``: it shape-validated a caller-supplied
mapping, stamped ``decision="completed"``, and signed it. Combined with a supervisor
that persisted nothing, the broker uid could obtain a signed
``brops.governed-receipt-envelope.v1`` for a run that never happened. The attestation
builder no longer accepts facts at all — it is handed the supervisor's OWN durable
terminal run state (:class:`governed_supervisor_ledger.AttestationState`) plus the
supervisor's pinned identity config, and there is no other way to reach it. A
fabricated run has no ledger row, so it has no evidence and no signature.

  1. **two-phase challenge verify** — given a signed
     ``brops.governed-turn-challenge.v1`` document (the exact shape the
     ``challenge_authority`` issuer mints), verify (phase A) its shape + signature
     and (phase B) that it is unexpired and that ``request_sha256`` re-derives from
     the challenge's own fields;
  2. **lease issuance** — mint the supervisor lease
     (``lease_expires_at_ms = now + LEASE_DURATION_MS``, the pinned launcher /
     executor executable digests from the supervisor's OWN trusted config) TOGETHER
     with the durable acceptance record the ledger CASes into existence, so one
     signed challenge is worth exactly one execution attempt;
  3. **the run attestation** — built from durable terminal run state only.

The step-8a launch gate no longer lives here. It moved into
:func:`governed_supervisor_ledger.gate_and_start`, which judges the lease window the
supervisor itself persisted rather than one the caller hands back (audit F-23).

Everything the OS trust chain would supply is reduced to an injected seam so the
logic runs offline and without a socket, signer, or clock:

  * ``verify_sig(message: bytes, sig: str) -> bool`` — the challenge-key signature
    check. The supervisor hands it ONLY the canonical bytes it reassembled itself
    from the payload it is about to trust (never caller-chosen bytes).
  * ``recompute_request_sha256(payload) -> str`` — re-derives the request digest
    from the challenge's own fields; the supervisor requires equality with the
    ``request_sha256`` the challenge carries, so the two cannot silently diverge.
  * ``SupervisorConfig.id_fn`` — mints the opaque ``lease_id`` /
    ``execution_attempt_id`` (a real deployment uses the ledger's CAS ids).

Fail-closed everywhere: a malformed / oversize / unexpired-but-forged / mismatched
input yields a typed :class:`Refusal` (or, for a supervisor-side programming/config
fault, raises :class:`SupervisorError`) — never a partially-built lease. An
injected verifier that itself throws on hostile input is contained and mapped to a
refusal rather than crashing the acceptance path.

Only the Python standard library is used.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Tuple, Union

from governed_supervisor_ledger import AttestationState, NewAcceptance

# ---------------------------------------------------------------------------
# Constants (rev-30 §5 — mirror supervisor_ledger.rs exactly).
# ---------------------------------------------------------------------------

# The signed document the challenge authority issues (challenge_authority.py).
CHALLENGE_PROTOCOL = "brops.governed-turn-challenge.v1"

# Full lease duration (§5 step 4 / §4.7): ~30000 pre-launch + 180000 in-window.
LEASE_DURATION_MS = 210_000

# Minimum remaining lease budget required to launch (§5 step 8a). Exact-180000
# remaining PROCEEDS; 179999 refuses. Matches supervisor_ledger.rs.
MIN_LAUNCH_REMAINING_MS = 180_000

# Governed challenge TTL is capped at 30000 ms by the issuer; the supervisor
# re-checks the cap so a challenge claiming a longer life than policy is malformed.
MAX_CHALLENGE_TTL_MS = 30_000

# The fixed, exhaustive shape of the challenge payload the supervisor will trust
# — the §4.1 ``brops.governed-turn-challenge.v1`` set (MIRRORS the shape the
# challenge authority builds in ``challenge_authority.issue_challenge``).
# Anything outside this set (extra keys, missing keys, wrong types) is malformed.
CHALLENGE_PAYLOAD_FIELDS: Tuple[str, ...] = (
    "protocol",
    "challenge_key_id",
    "run_id",
    "task_id",
    "workspace_id",
    "install_id",
    "supervisor_id",
    "request_nonce",
    "system_sha256",
    "history_sha256",
    "generation_config_sha256",
    "request_sha256",
    "requested_at_ms",
    "challenge_issued_at_ms",
    "challenge_expires_at_ms",
)

# The canonical request-envelope protocol whose SHA-256 IS ``request_sha256``
# (mirrors ``challenge_authority.REQUEST_ENVELOPE_PROTOCOL`` / §2.2).
REQUEST_ENVELOPE_PROTOCOL = "brops.request.v1"

# The fixed, exhaustive shape of the signed envelope.
CHALLENGE_DOC_FIELDS: Tuple[str, ...] = ("payload", "sig")

# ---------------------------------------------------------------------------
# Supervisor RUN-ATTESTATION (rev-30 §4.1/§4.9 — the ``brops.run-attestation.v1``
# the supervisor produces so the isolated signer can prove the receipt <-> run
# binding). The supervisor builds the §4.9 evidence from its OWN trusted terminal
# run state and signs ``JCS(evidence)``; the isolated signer re-validates the
# identical evidence shape and re-hashes those bytes into
# ``attestation_evidence_sha256`` (isolated_signer._verify_supervisor_attestation).
# ---------------------------------------------------------------------------

# MUST equal isolated_signer.ATTESTATION_PROTOCOL and governed_verification.rs.
ATTESTATION_PROTOCOL = "brops.run-attestation.v1"

# The single authoritative decision the supervisor STAMPS on a completed terminal
# run (the signer refuses anything but "completed", §4.9). Never caller-supplied.
DECISION_COMPLETED = "completed"

# One fixed string cap — mirrors isolated_signer.STRING_CAP (§1.9).
ATTEST_STRING_CAP = 128

# The trusted run/evidence facts the supervisor's OWN terminal run state supplies.
# This is EXACTLY isolated_signer.EVIDENCE_FIELDS MINUS ``decision`` (which the
# supervisor stamps itself). Building the evidence from this fixed set — and
# rejecting any extra key (a smuggled ``decision``/``evidence_jcs``/``sig``) — is
# what keeps this a recompute-then-attest builder, never a sign(caller_bytes)
# oracle (§1.3-§1.4 no-oracle rule).
ATTEST_INPUT_STRING_FIELDS: Tuple[str, ...] = (
    "run_id",
    "execution_attempt_id",
    "task_id",
    "request_nonce",
    "receipt_id",
    "workspace_id",
    "install_id",
    "supervisor_id",
    "executor_id",
    "builder_id",
    "policy_id",
    "policy_version",
)
ATTEST_INPUT_HANDLE_FIELDS: Tuple[str, ...] = (
    "policy_bundle_handle",
    "generation_config_handle",
    "system_handle",
    "history_handle",
    "output_handle",
    "containment_evidence_handle",
    "record_handle",
    "lease_handle",
    "execution_receipt_handle",
)
ATTEST_INPUT_DIGEST_FIELDS: Tuple[str, ...] = ("evidence_final_event_hash",)
ATTEST_INPUT_TS_FIELDS: Tuple[str, ...] = (
    "requested_at",
    "completed_at",
    "challenge_accepted_at_ms",
)
ATTEST_INPUT_COUNT_FIELDS: Tuple[str, ...] = (
    "evidence_event_count",
    "evidence_last_sequence",
    "evidence_head_sequence",
)
ATTEST_INPUT_FIELDS: Tuple[str, ...] = (
    ATTEST_INPUT_STRING_FIELDS
    + ATTEST_INPUT_HANDLE_FIELDS
    + ATTEST_INPUT_DIGEST_FIELDS
    + ATTEST_INPUT_TS_FIELDS
    + ATTEST_INPUT_COUNT_FIELDS
)

# The three-field attestation object the signer verifies
# (isolated_signer.ATTESTATION_FIELDS).
ATTESTATION_FIELDS: Tuple[str, ...] = ("attestation_protocol", "supervisor_key_id", "sig")

# ---- Typed refusal reasons (a refusal is a verdict, never a partial success) --
REFUSE_MALFORMED = "malformed"
REFUSE_SIGNATURE_INVALID = "signature_invalid"
REFUSE_CHALLENGE_EXPIRED = "challenge_expired"
REFUSE_REQUEST_SHA256_MISMATCH = "request_sha256_mismatch"
REFUSE_LEASE_EXPIRED = "lease_expired"
# The challenge names a supervisor that is not this one. Accepting it would let a turn
# issued for another supervisor be leased and attested here (F-01 hardening).
REFUSE_SUPERVISOR_MISMATCH = "supervisor_mismatch"


class SupervisorError(Exception):
    """A supervisor-side programming/config fault (bad config, non-callable seam,
    non-int clock). Fail-closed and distinct from a renderer-facing refusal."""


class _Refuse(Exception):
    """Internal control-flow signal carrying a typed refusal reason + detail.

    Raised inside the acceptance path and converted to a :class:`Refusal` at the
    public boundary, so a rejected input is always a typed verdict — never an
    exception that escapes and never a half-built lease.
    """

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__("%s: %s" % (reason, detail))
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class Refusal:
    """A fail-closed refusal verdict. ``reason`` is one of the ``REFUSE_*`` tokens."""

    reason: str
    detail: str


@dataclass(frozen=True)
class Lease:
    """The supervisor lease issued on a fully-verified challenge (§5 step 4).

    ``lease_expires_at_ms`` is stamped from the supervisor's own clock
    (``now + LEASE_DURATION_MS``); the two executable digests are pinned by the
    supervisor's OWN trusted config, never taken from the challenge/caller.
    """

    lease_id: str
    execution_attempt_id: str
    lease_expires_at_ms: int
    launcher_executable_sha256: str
    executor_executable_sha256: str


@dataclass(frozen=True)
class Accepted:
    """A fully-verified challenge turned into (a) the lease to return to the caller and
    (b) the DURABLE acceptance record the ledger must CAS into existence before that
    lease is worth anything (F-01).

    The two are produced together, from the same signature-verified challenge payload, so
    the lease the caller receives and the row the supervisor will later attest from can
    never describe different turns.
    """

    lease: Lease
    acceptance: NewAcceptance


# accept_open returns an acceptance (lease + durable record) OR a typed refusal.
# Callers ``isinstance``-dispatch on the result.
AcceptResult = Union[Accepted, Refusal]


# ---------------------------------------------------------------------------
# Small type predicates (shared with the issuer's discipline).
# ---------------------------------------------------------------------------


def _is_int(value: Any) -> bool:
    # bool is an int subclass; a boolean is never an acceptable epoch/id here.
    return isinstance(value, int) and not isinstance(value, bool)


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and len(value) > 0


def _is_sha256_hex(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _capped_str(value: Any) -> bool:
    """Non-empty string within the fixed §1.9 cap — mirrors
    isolated_signer._capped_str so an id the supervisor attests is one the signer
    will also accept."""
    return isinstance(value, str) and 0 < len(value) <= ATTEST_STRING_CAP


def _is_lower_sha256_hex(value: Any) -> bool:
    """64 LOWERCASE hex chars — byte-identical to isolated_signer._is_sha256_hex.
    Lowercase-strict because the handle value flows verbatim into ``JCS(evidence)``;
    an uppercased digest would sign different bytes than the signer re-hashes."""
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(c in "0123456789abcdef" for c in value)


def _is_u64_ms(value: Any) -> bool:
    # Epoch-ms timestamp; bool excluded (mirrors isolated_signer._is_u64_ms).
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 2 ** 64


def _is_pos_i63(value: Any) -> bool:
    # Evidence-head counter, strictly positive i63 (mirrors
    # isolated_signer._is_pos_i63 / the ledger's ``>= 1`` CHECK constraints).
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value < 2 ** 63


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    """Deterministic JCS-ish encoding (sorted keys, compact separators) — the EXACT
    encoding ``challenge_authority.issue_challenge`` signs, so the reassembled bytes
    the supervisor verifies match the bytes the authority signed.

    This is ALSO byte-identical to ``isolated_signer._canonical_bytes`` over the
    §4.9 evidence object (both: ``json.dumps(sort_keys=True, separators=(",",":"))``,
    default ``ensure_ascii=True``; evidence carries only strings/ints so the
    ``allow_nan`` difference is unobservable). That equality is what makes the
    ``JCS(evidence)`` the supervisor signs the SAME bytes the signer re-hashes into
    ``attestation_evidence_sha256`` (and the Rust broker checks in
    governed_verification.rs)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def challenge_handle_for(payload: Mapping[str, Any], sig: str) -> str:
    """The ONE definition of ``challenge_handle`` — ``SHA256(JCS({payload, sig}))``.

    **rev-30 correction (2026-08-10).** This used to be ``SHA256(JCS(payload))`` — the
    payload ALONE — inline in :func:`accept_open`, while the §4.10(a0) open path hashed the
    exact signed document bytes. rev-30 contradicted itself about which was right (§3's
    artifact matrix, §4.10(a0) and Appendix B's handle matrix all define the
    ``{payload, sig}`` form; §5's summary table merely *described* the shipped payload-only
    behaviour). The Architect declared §3/§4.10(a0) normative and the addendum's §5 table is
    corrected to match; see ``docs/OWNER_ACTION_REQUIRED.md`` §1c.

    Two independent reasons the payload-only form was the wrong half:

      * §7's challenge predicate fetches the stored document BY this handle and re-hashes the
        exact stored bytes (``SHA256(bytes) == challenge_handle`` AND
        ``bytes == canonical_bytes({payload, sig})``). The stored document is the signed
        ``{payload, sig}`` envelope (§2.1.1 ``issued_challenge_document``, §6 step-1 publish),
        so under the payload-only form that predicate could never pass for ANY turn.
      * §4.10(d) (NOT IMPLEMENTED — a later ordered piece) joins the ``INPUTS_READY``
        staging row to its acceptance row on
        ``(install_id, request_nonce, challenge_handle)``. Two different digests of the same
        turn make that join unsatisfiable.

    The ``{payload, sig}`` form is also the strictly stronger binding: two distinct signatures
    over one payload get two distinct handles. Nothing regresses — a re-signed replay misses
    the handle lookup, then collides on ``UNIQUE(install_id, request_nonce)`` and is refused
    ``nonce_rebound_to_different_turn`` (``governed_supervisor_ledger._prepare_locked``), so it
    still buys zero additional execution attempts; it is refused rather than served the
    original lease, which is the fail-closed direction.

    ``sort_keys=True`` in :func:`_canonical_bytes` sorts recursively and ``"payload" < "sig"``,
    so these bytes are byte-identical to the canonicality-gated ``document_bytes`` that
    ``governed_turn_open`` hashes for the staging row.
    """
    return hashlib.sha256(_canonical_bytes({"payload": payload, "sig": sig})).hexdigest()


def recompute_request_sha256(payload: Mapping[str, Any]) -> str:
    """Independently RE-DERIVE ``request_sha256`` from the challenge payload's OWN
    fields via the canonical ``brops.request.v1`` request-envelope formula.

    This is the supervisor's OWN recompute (§2.1 / §4.10(a0)): byte-identical to
    ``challenge_authority.recompute_request_sha256`` /
    ``isolated_signer._recompute_request_sha256`` /
    ``receipt.rs::request_envelope_sha256`` — an 8-field JCS envelope with
    ``request_nonce`` inside the hashed bytes and ``requested_at`` as the
    decimal-ms STRING. Because it reads the component hashes + ids + nonce +
    timestamp straight from the signed payload, a challenge whose transported
    ``request_sha256`` was forged (≠ the digest of its own fields) is caught in
    phase B (``request_sha256_mismatch``). It is passed to ``accept_open`` as the
    ``recompute_request_sha256`` seam.
    """
    envelope = {
        "protocol": REQUEST_ENVELOPE_PROTOCOL,
        "workspace_id": payload["workspace_id"],
        "install_id": payload["install_id"],
        "request_nonce": payload["request_nonce"],
        "system_sha256": payload["system_sha256"],
        "history_sha256": payload["history_sha256"],
        "generation_config_sha256": payload["generation_config_sha256"],
        "requested_at": str(payload["requested_at_ms"]),
    }
    canonical = json.dumps(
        envelope,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


# ---------------------------------------------------------------------------
# Supervisor trusted config (the fields the supervisor, not the caller, fills in).
# ---------------------------------------------------------------------------


class SupervisorConfig:
    """The supervisor's OWN trusted config: everything the supervisor — never the caller —
    contributes to a lease and to a run attestation.

    ``launcher_executable_sha256`` / ``executor_executable_sha256`` are the pinned
    executable digests bound into every lease. ``id_fn`` mints the opaque
    ``lease_id`` / ``execution_attempt_id`` / ``receipt_id`` (injected so tests are
    deterministic).

    The identity block (``supervisor_id``, ``executor_id``, ``builder_id``, ``policy_id``,
    ``policy_version``, ``policy_bundle_handle``) is the F-01 half that used to arrive on
    the wire inside ``attest-run``'s ``facts``. The isolated signer ALLOWLISTS
    ``executor_id`` / ``builder_id`` / ``supervisor_id`` (``isolated_signer._check_identity``),
    so letting the caller choose them made that allowlist a formality — the caller simply
    copied the values out of the world-readable deployment config. They now come from the
    supervisor's own provisioning and nowhere else.

    ``challenge_registry_*`` records WHICH pinned challenge-key registry snapshot authorized
    an acceptance, so a later audit can tell which key material was in force for that turn.
    """

    def __init__(
        self,
        launcher_executable_sha256: str,
        executor_executable_sha256: str,
        id_fn: Callable[[], str],
        *,
        supervisor_id: str,
        executor_id: str,
        builder_id: str,
        policy_id: str,
        policy_version: str,
        policy_bundle_handle: str,
        challenge_registry_handle: str,
        challenge_registry_hash: str,
        challenge_registry_epoch: int,
        challenge_registry_root_key_id: str,
    ) -> None:
        if not _is_sha256_hex(launcher_executable_sha256):
            raise SupervisorError("launcher_executable_sha256 must be 64 hex characters")
        if not _is_sha256_hex(executor_executable_sha256):
            raise SupervisorError("executor_executable_sha256 must be 64 hex characters")
        if not callable(id_fn):
            raise SupervisorError("id_fn must be callable")
        for name, value in (
            ("supervisor_id", supervisor_id),
            ("executor_id", executor_id),
            ("builder_id", builder_id),
            ("policy_id", policy_id),
            ("policy_version", policy_version),
            ("challenge_registry_handle", challenge_registry_handle),
            ("challenge_registry_hash", challenge_registry_hash),
            ("challenge_registry_root_key_id", challenge_registry_root_key_id),
        ):
            if not _capped_str(value):
                raise SupervisorError("%s must be a non-empty capped string" % name)
        if not _is_lower_sha256_hex(policy_bundle_handle):
            raise SupervisorError("policy_bundle_handle must be 64 lowercase hex chars")
        if not _is_int(challenge_registry_epoch) or challenge_registry_epoch < 0:
            raise SupervisorError("challenge_registry_epoch must be a non-negative int")

        self.launcher_executable_sha256 = launcher_executable_sha256.lower()
        self.executor_executable_sha256 = executor_executable_sha256.lower()
        self._id_fn = id_fn
        self.supervisor_id = supervisor_id
        self.executor_id = executor_id
        self.builder_id = builder_id
        self.policy_id = policy_id
        self.policy_version = policy_version
        self.policy_bundle_handle = policy_bundle_handle
        self.challenge_registry_handle = challenge_registry_handle
        self.challenge_registry_hash = challenge_registry_hash
        self.challenge_registry_epoch = challenge_registry_epoch
        self.challenge_registry_root_key_id = challenge_registry_root_key_id

    def mint_id(self) -> str:
        value = self._id_fn()
        if not _nonempty_str(value):
            raise SupervisorError("id_fn produced an invalid id")
        return value


# ---------------------------------------------------------------------------
# Challenge shape validation (fixed shape ONLY -> malformed refusal on any drift).
# ---------------------------------------------------------------------------


def _validate_challenge_doc(challenge_doc: Any) -> Tuple[Mapping[str, Any], str]:
    """Validate the signed envelope + payload against their fixed shapes.

    Returns ``(payload, sig)`` on success. Raises :class:`_Refuse` (``malformed``)
    on ANY drift: a non-mapping, extra/missing keys, a wrong-typed field, a bad
    protocol tag, a non-64-hex ``request_sha256``, non-int timestamps, a
    non-positive / over-cap TTL, or ``issued > expires``.
    """
    if not isinstance(challenge_doc, Mapping):
        raise _Refuse(REFUSE_MALFORMED, "challenge document must be a mapping")

    doc_keys = set(challenge_doc.keys())
    allowed_doc = set(CHALLENGE_DOC_FIELDS)
    if doc_keys - allowed_doc:
        raise _Refuse(REFUSE_MALFORMED, "unexpected envelope field(s) %s" % sorted(doc_keys - allowed_doc))
    if allowed_doc - doc_keys:
        raise _Refuse(REFUSE_MALFORMED, "missing envelope field(s) %s" % sorted(allowed_doc - doc_keys))

    sig = challenge_doc["sig"]
    if not _nonempty_str(sig):
        raise _Refuse(REFUSE_MALFORMED, "sig must be a non-empty string")

    payload = challenge_doc["payload"]
    if not isinstance(payload, Mapping):
        raise _Refuse(REFUSE_MALFORMED, "payload must be a mapping")

    p_keys = set(payload.keys())
    allowed_p = set(CHALLENGE_PAYLOAD_FIELDS)
    if p_keys - allowed_p:
        raise _Refuse(REFUSE_MALFORMED, "unexpected payload field(s) %s" % sorted(p_keys - allowed_p))
    if allowed_p - p_keys:
        raise _Refuse(REFUSE_MALFORMED, "missing payload field(s) %s" % sorted(allowed_p - p_keys))

    if payload["protocol"] != CHALLENGE_PROTOCOL:
        raise _Refuse(REFUSE_MALFORMED, "unexpected protocol %r" % (payload["protocol"],))

    for field in ("challenge_key_id", "run_id", "task_id", "workspace_id",
                  "install_id", "supervisor_id", "request_nonce"):
        if not _nonempty_str(payload[field]):
            raise _Refuse(REFUSE_MALFORMED, "%s must be a non-empty string" % field)

    for field in ("system_sha256", "history_sha256", "generation_config_sha256",
                  "request_sha256"):
        if not _is_sha256_hex(payload[field]):
            raise _Refuse(REFUSE_MALFORMED, "%s must be 64 hex characters" % field)

    if not _is_int(payload["requested_at_ms"]):
        raise _Refuse(REFUSE_MALFORMED, "requested_at_ms must be an int")

    issued = payload["challenge_issued_at_ms"]
    expires = payload["challenge_expires_at_ms"]
    if not _is_int(issued) or not _is_int(expires):
        raise _Refuse(REFUSE_MALFORMED, "challenge timestamps must be ints")
    if expires <= issued:
        raise _Refuse(REFUSE_MALFORMED, "challenge_expires_at_ms must exceed challenge_issued_at_ms")
    if expires - issued > MAX_CHALLENGE_TTL_MS:
        raise _Refuse(REFUSE_MALFORMED, "challenge TTL exceeds %d ms cap" % MAX_CHALLENGE_TTL_MS)

    return payload, sig


# ---------------------------------------------------------------------------
# accept_open — two-phase challenge verify -> lease issuance (§5 step 4).
# ---------------------------------------------------------------------------


def accept_open(
    challenge_doc: Any,
    now_ms: int,
    *,
    config: SupervisorConfig,
    verify_sig: Callable[[bytes], bool],
    recompute_request_sha256: Callable[[Mapping[str, Any]], str],
) -> AcceptResult:
    """Verify a signed governed-turn challenge and, on success, issue a lease.

    Two-phase verify (each phase fail-closed, in order):

      * **Phase A — authenticity.** ``_validate_challenge_doc`` enforces the fixed
        envelope + payload shape (any drift -> ``malformed``); then
        ``verify_sig`` checks the signature over the canonical bytes the supervisor
        reassembled from the payload itself (failure -> ``signature_invalid``).
      * **Phase B — binding.** the challenge must be unexpired
        (``now_ms <= challenge_expires_at_ms`` else ``challenge_expired``) and its
        ``request_sha256`` must re-derive from its own fields via
        ``recompute_request_sha256`` (inequality -> ``request_sha256_mismatch``).

      * **Phase C — addressing.** the challenge's signed ``supervisor_id`` must be THIS
        supervisor (else ``supervisor_mismatch``); a turn issued for another supervisor is
        authentic but is not authorization for this one to lease and attest it.

    Only after ALL phases pass is an :class:`Accepted` produced: the :class:`Lease`
    (``lease_expires_at_ms = now_ms + LEASE_DURATION_MS`` + the two pinned executable
    digests from ``config``) together with the :class:`~governed_supervisor_ledger.NewAcceptance`
    the caller must CAS into the durable ledger. Returns that OR a typed
    :class:`Refusal`; never a partially-built lease.

    ``now_ms`` must be an int (the supervisor's own clock) and the two seams must
    be callable, else :class:`SupervisorError` (a supervisor-side fault, not a
    renderer verdict). An injected seam that raises on hostile input is contained
    and mapped to the corresponding refusal.
    """
    if not isinstance(config, SupervisorConfig):
        raise SupervisorError("config must be a SupervisorConfig")
    if not _is_int(now_ms):
        raise SupervisorError("now_ms must be an int (epoch ms)")
    if not callable(verify_sig):
        raise SupervisorError("verify_sig must be callable")
    if not callable(recompute_request_sha256):
        raise SupervisorError("recompute_request_sha256 must be callable")

    try:
        # ---- Phase A: shape + signature authenticity ----
        payload, sig = _validate_challenge_doc(challenge_doc)

        message = _canonical_bytes(payload)
        try:
            ok = verify_sig(message, sig)
        except Exception as exc:  # a verifier must not crash the acceptance path.
            raise _Refuse(REFUSE_SIGNATURE_INVALID, "verifier raised: %s" % exc)
        if ok is not True:
            raise _Refuse(REFUSE_SIGNATURE_INVALID, "challenge signature rejected")

        # ---- Phase B: freshness + request-binding ----
        if now_ms > payload["challenge_expires_at_ms"]:
            raise _Refuse(REFUSE_CHALLENGE_EXPIRED, "now_ms past challenge_expires_at_ms")

        try:
            recomputed = recompute_request_sha256(payload)
        except Exception as exc:
            raise _Refuse(REFUSE_REQUEST_SHA256_MISMATCH, "recompute raised: %s" % exc)
        if not _is_sha256_hex(recomputed):
            raise _Refuse(REFUSE_REQUEST_SHA256_MISMATCH, "recompute did not yield a sha256 hex")
        if recomputed.lower() != payload["request_sha256"].lower():
            raise _Refuse(REFUSE_REQUEST_SHA256_MISMATCH, "recomputed digest != challenge request_sha256")

        # ---- Phase C: this supervisor is the one the challenge names ----
        # The challenge payload is signed, so `supervisor_id` is authentic; but authentic
        # for ANOTHER supervisor is still not authorization for THIS one to lease + attest.
        if payload["supervisor_id"] != config.supervisor_id:
            raise _Refuse(
                REFUSE_SUPERVISOR_MISMATCH,
                "challenge names supervisor %r, not this supervisor" % (payload["supervisor_id"],),
            )

        # ---- All phases passed: mint the lease AND its durable acceptance record ----
        # `challenge_handle` is the supervisor's OWN content address of the exact signed
        # DOCUMENT it just verified — `SHA256(JCS({payload, sig}))`, §3/§4.10(a0)/Appendix B.
        # The ledger's UNIQUE on it is what makes a replayed challenge unable to mint a
        # second attempt. NOT `sha256(message)`: `message` is `JCS(payload)` ALONE, which is
        # what §5's summary table used to describe and what this line used to compute — see
        # `challenge_handle_for` for which half of rev-30 won and why.
        challenge_handle = challenge_handle_for(payload, sig)
        lease = Lease(
            lease_id=config.mint_id(),
            execution_attempt_id=config.mint_id(),
            lease_expires_at_ms=now_ms + LEASE_DURATION_MS,
            launcher_executable_sha256=config.launcher_executable_sha256,
            executor_executable_sha256=config.executor_executable_sha256,
        )
        acceptance = NewAcceptance(
            install_id=payload["install_id"],
            request_nonce=payload["request_nonce"],
            challenge_handle=challenge_handle,
            run_id=payload["run_id"],
            task_id=payload["task_id"],
            workspace_id=payload["workspace_id"],
            execution_attempt_id=lease.execution_attempt_id,
            challenge_accepted_at_ms=now_ms,
            challenge_registry_handle=config.challenge_registry_handle,
            challenge_registry_hash=config.challenge_registry_hash,
            challenge_registry_epoch=config.challenge_registry_epoch,
            challenge_registry_root_key_id=config.challenge_registry_root_key_id,
            lease_payload_bytes=_canonical_bytes(_lease_payload(lease)),
            lease_id=lease.lease_id,
            lease_issued_at_ms=now_ms,
            lease_expires_at_ms=lease.lease_expires_at_ms,
            # Minted per turn by the supervisor: the §7.1(d) replay key must not be a
            # deployment constant (audit F-02 notes a constant receipt_id defeats it).
            receipt_id=config.mint_id(),
            supervisor_id=config.supervisor_id,
            requested_at_ms=payload["requested_at_ms"],
            request_sha256=payload["request_sha256"].lower(),
            system_handle=payload["system_sha256"].lower(),
            history_handle=payload["history_sha256"].lower(),
            generation_config_handle=payload["generation_config_sha256"].lower(),
        )
        return Accepted(lease=lease, acceptance=acceptance)
    except _Refuse as refusal:
        return Refusal(refusal.reason, refusal.detail)


# ---------------------------------------------------------------------------
# Terminal artifacts the supervisor BUILDS itself (audit F-02).
# ---------------------------------------------------------------------------

#: The two documents the supervisor assembles at completion and publishes to the protected
#: store, so the handles named in the signed evidence address artifacts THIS run produced.
TERMINAL_RECORD_PROTOCOL = "brops.governed-turn-record.v1"
EXECUTION_RECEIPT_PROTOCOL = "brops.execution-receipt.v1"


def build_terminal_record(row: Mapping[str, Any], produced: Mapping[str, Any]) -> bytes:
    """The canonical terminal governed-turn record for one attempt.

    **F-02.** `record_handle` used to be a deployment-static constant copied out of a
    world-readable config, so every receipt this deployment ever produced named the same
    "record" and the isolated signer's protected-chain check only proved that somebody had
    written those constant bytes once. The record is now assembled here from the supervisor's
    OWN acceptance row plus the write-once completion, so its content address is per-run and an
    auditor dereferencing it gets the actual account of the turn.
    """
    return _canonical_bytes({
        "protocol": TERMINAL_RECORD_PROTOCOL,
        "run_id": row["run_id"],
        "task_id": row["task_id"],
        "execution_attempt_id": row["execution_attempt_id"],
        "workspace_id": row["workspace_id"],
        "install_id": row["install_id"],
        "request_nonce": row["request_nonce"],
        "receipt_id": row["receipt_id"],
        "supervisor_id": row["supervisor_id"],
        "request_sha256": row["request_sha256"],
        "system_handle": row["system_handle"],
        "history_handle": row["history_handle"],
        "generation_config_handle": row["generation_config_handle"],
        "output_handle": produced["output_handle"],
        "containment_evidence_handle": produced["containment_evidence_handle"],
        "challenge_handle": row["challenge_handle"],
        "challenge_registry_hash": row["challenge_registry_hash"],
        "challenge_registry_epoch": row["challenge_registry_epoch"],
        "requested_at_ms": row["requested_at_ms"],
        "challenge_accepted_at_ms": row["challenge_accepted_at_ms"],
        "completed_at_ms": produced["completed_at_ms"],
        "decision": DECISION_COMPLETED,
    })


def build_execution_receipt(row: Mapping[str, Any], produced: Mapping[str, Any]) -> bytes:
    """The canonical execution receipt: what the supervisor observed of the run itself.

    **F-02.** Also previously a constant. The process metadata comes from the
    ``execution-started`` transition the supervisor durably recorded, so this addresses a
    document about THIS execution rather than a stub blob the provisioner wrote.
    """
    return _canonical_bytes({
        "protocol": EXECUTION_RECEIPT_PROTOCOL,
        "run_id": row["run_id"],
        "execution_attempt_id": row["execution_attempt_id"],
        "lease_id": row["lease_id"],
        "lease_issued_at_ms": row["lease_issued_at_ms"],
        "lease_expires_at_ms": row["lease_expires_at_ms"],
        "process_group_id": row["process_group_id"] or "",
        "cgroup_id": row["cgroup_id"] or "",
        "execution_started_marker": row["execution_started_marker"] or "",
        "completed_at_ms": produced["completed_at_ms"],
        "output_handle": produced["output_handle"],
    })


def _lease_payload(lease: Lease) -> Mapping[str, Any]:
    """The canonical lease object whose JCS bytes are persisted at acceptance, so a
    post-commit / pre-signature crash re-signs the byte-identical lease (§5 step 6)."""
    return {
        "lease_id": lease.lease_id,
        "execution_attempt_id": lease.execution_attempt_id,
        "lease_expires_at_ms": lease.lease_expires_at_ms,
        "launcher_executable_sha256": lease.launcher_executable_sha256,
        "executor_executable_sha256": lease.executor_executable_sha256,
    }


# ---------------------------------------------------------------------------
# The §5 step-8a launch gate lives in governed_supervisor_ledger.gate_and_start.
#
# It used to live HERE as `launch_gate(lease, now_ms)` — a pure function over a lease the
# CALLER handed back on the wire, so the party being gated chose the expiry it was judged
# against (audit F-23, and the same stateless root cause as F-01). It now judges the lease
# window the supervisor persisted at acceptance, keyed only by `execution_attempt_id`, and
# it CASes the acceptance row forward in the same transaction so the gate cannot be
# smuggled past. Nothing re-implements it here; the boundary behaviour is proven by
# `governed_supervisor_ledger.lease_launch_gate` and its tests.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# build_run_attestation — the supervisor's §4.9 RUN-ATTESTATION (recompute-then-attest).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunAttestation:
    """A produced ``brops.run-attestation.v1`` over the §4.9 evidence.

    ``attestation`` is the exact 3-field object the isolated signer verifies
    (``{attestation_protocol, supervisor_key_id, sig}``); ``evidence_jcs`` is the
    canonical ``JCS(evidence)`` the supervisor built AND signed (the signer
    re-hashes these bytes into ``attestation_evidence_sha256``);
    ``attestation_evidence_sha256`` is that convenience digest
    (``sha256(evidence_jcs)``) the §4.9 envelope binds.
    """

    attestation: dict
    evidence_jcs: bytes
    attestation_evidence_sha256: str


# build_run_attestation returns the produced attestation OR a typed refusal (a
# malformed trusted-fact set fails closed, never a half-built attestation).
AttestResult = Union[RunAttestation, Refusal]


def _validate_run_facts(facts: Any) -> dict:
    """Re-validate the ASSEMBLED evidence against the fixed ``ATTEST_INPUT_FIELDS`` shape
    (byte-compatible with the signer's own evidence validation) immediately before signing.

    Note the changed role: this is no longer a door caller input passes through — after the
    F-01 fix nothing reaches it except the dict :func:`build_run_attestation` assembles from
    durable ledger state plus supervisor config. It is kept as a last defence-in-depth check
    so a supervisor-side assembly bug (a wrong type, a dropped field, a stray key) fails
    closed rather than producing an attestation the isolated signer would then reject — or,
    worse, accept over malformed bytes. Raises :class:`_Refuse` (``malformed``) on ANY drift.
    """
    if not isinstance(facts, Mapping):
        raise _Refuse(REFUSE_MALFORMED, "run facts must be a mapping")

    keys = set(facts.keys())
    allowed = set(ATTEST_INPUT_FIELDS)
    extra = keys - allowed
    if extra:
        raise _Refuse(REFUSE_MALFORMED, "unexpected run-fact field(s) %s" % sorted(extra))
    missing = allowed - keys
    if missing:
        raise _Refuse(REFUSE_MALFORMED, "missing run-fact field(s) %s" % sorted(missing))

    for field in ATTEST_INPUT_STRING_FIELDS:
        if not _capped_str(facts[field]):
            raise _Refuse(REFUSE_MALFORMED, "%s must be a non-empty capped string" % field)
    for field in ATTEST_INPUT_HANDLE_FIELDS:
        if not _is_lower_sha256_hex(facts[field]):
            raise _Refuse(REFUSE_MALFORMED, "%s must be 64 lowercase hex chars" % field)
    for field in ATTEST_INPUT_DIGEST_FIELDS:
        if not _is_lower_sha256_hex(facts[field]):
            raise _Refuse(REFUSE_MALFORMED, "%s must be 64 lowercase hex chars" % field)
    for field in ATTEST_INPUT_TS_FIELDS:
        if not _is_u64_ms(facts[field]):
            raise _Refuse(REFUSE_MALFORMED, "%s must be a u64 epoch-ms int" % field)
    for field in ATTEST_INPUT_COUNT_FIELDS:
        if not _is_pos_i63(facts[field]):
            raise _Refuse(REFUSE_MALFORMED, "%s must be a positive int (>= 1)" % field)

    return {field: facts[field] for field in ATTEST_INPUT_FIELDS}


def evidence_from_state(state: AttestationState, config: SupervisorConfig) -> dict:
    """Assemble the §4.9 evidence facts from the supervisor's OWN durable terminal run
    state plus its OWN pinned identity config. **This is the F-01 fix.**

    Every one of the 25 fields has exactly one origin, and none of them is the caller:

      * ``run_id``/``execution_attempt_id``/``task_id``/``request_nonce``/``receipt_id``/
        ``workspace_id``/``install_id``/``supervisor_id``/``requested_at``/
        ``challenge_accepted_at_ms`` and the three request-component handles come from the
        acceptance row, which was written from the SIGNATURE-VERIFIED challenge payload;
      * ``output_handle``/``containment_evidence_handle``/``record_handle``/``lease_handle``/
        ``execution_receipt_handle``/``completed_at``/the four ``evidence_*`` counters come
        from the WRITE-ONCE completion row of an attempt that reached ``EXECUTING`` through
        the legal §5 edges and passed the evidence-head floor;
      * ``executor_id``/``builder_id``/``policy_id``/``policy_version``/
        ``policy_bundle_handle`` come from supervisor provisioning — the values the isolated
        signer allowlists, which the caller must not be able to choose.

    There is no parameter through which a caller can contribute a value, which is what makes
    the resulting signature a statement about a run the supervisor itself authorized and
    watched terminate.
    """
    return {
        # ---- from the acceptance row (written from the signed challenge) ----
        "run_id": state.run_id,
        "execution_attempt_id": state.execution_attempt_id,
        "task_id": state.task_id,
        "request_nonce": state.request_nonce,
        "receipt_id": state.receipt_id,
        "workspace_id": state.workspace_id,
        "install_id": state.install_id,
        "supervisor_id": state.supervisor_id,
        "requested_at": state.requested_at_ms,
        "challenge_accepted_at_ms": state.challenge_accepted_at_ms,
        "system_handle": state.system_handle,
        "history_handle": state.history_handle,
        "generation_config_handle": state.generation_config_handle,
        # ---- from supervisor provisioning (the signer's allowlisted identities) ----
        "executor_id": config.executor_id,
        "builder_id": config.builder_id,
        "policy_id": config.policy_id,
        "policy_version": config.policy_version,
        "policy_bundle_handle": config.policy_bundle_handle,
        # ---- from the write-once completion row ----
        "output_handle": state.output_handle,
        "containment_evidence_handle": state.containment_evidence_handle,
        "record_handle": state.record_handle,
        "lease_handle": state.lease_handle,
        "execution_receipt_handle": state.execution_receipt_handle,
        "completed_at": state.completed_at_ms,
        "evidence_final_event_hash": state.evidence_final_event_hash,
        "evidence_event_count": state.evidence_event_count,
        "evidence_last_sequence": state.evidence_last_sequence,
        "evidence_head_sequence": state.evidence_head_sequence,
    }


def build_run_attestation(
    state: AttestationState,
    *,
    config: SupervisorConfig,
    supervisor_key_id: str,
    sign_attestation: Callable[[bytes], str],
) -> AttestResult:
    """Build the §4.9 evidence from the supervisor's OWN terminal run state and produce the
    ``brops.run-attestation.v1`` over it (recompute-then-attest).

    **F-01.** This function no longer has a ``facts`` parameter. Before the fix it accepted a
    caller mapping, shape-validated it, stamped ``decision="completed"``, and signed — a
    sign-arbitrary-facts oracle for the one uid that can reach the socket. Now the only way
    to reach it is with a :class:`~governed_supervisor_ledger.AttestationState`, which
    :func:`governed_supervisor_ledger.load_attestation_state` returns ONLY for an attempt
    that this supervisor accepted, leased, gated, watched start, and recorded as completed.
    The no-oracle rule (§1.3-§1.4) is therefore enforced by the type signature, not by
    validation: there is no argument through which caller-chosen evidence can arrive.

    The supervisor STAMPS ``decision="completed"`` itself and BUILDS the canonical
    ``JCS(evidence)`` here. The ``evidence`` it builds is EXACTLY the signer's
    ``EVIDENCE_FIELDS`` shape, so ``JCS(evidence)`` is byte-identical to what
    ``isolated_signer._verify_supervisor_attestation`` re-hashes.

    ``sign_attestation(message: bytes) -> str`` is the injected signing seam: the supervisor
    holds the Ed25519 attestation private key behind it (no key literal lives in this
    module), and it is handed ONLY the ``JCS(evidence)`` bytes the supervisor assembled
    itself. It returns the detached signature as a string (base64url of the 64-byte Ed25519
    signature, per §4.1 ``sig:b64url(64B)`` — the encoding the Rust broker decodes with
    ``URL_SAFE_NO_PAD``).

    Returns a :class:`RunAttestation` on success, or a typed :class:`Refusal` (``malformed``)
    if the assembled evidence somehow fails its own shape re-check (a supervisor-side
    assembly bug — fail closed rather than sign malformed bytes). ``supervisor_key_id`` must
    be a capped string and ``sign_attestation`` callable, else :class:`SupervisorError`; a
    seam that returns a non-string / empty signature is likewise a :class:`SupervisorError` —
    never a half-built attestation.
    """
    if not isinstance(state, AttestationState):
        raise SupervisorError("state must be an AttestationState from the durable ledger")
    if not isinstance(config, SupervisorConfig):
        raise SupervisorError("config must be a SupervisorConfig")
    if not _capped_str(supervisor_key_id):
        raise SupervisorError("supervisor_key_id must be a non-empty capped string")
    if not callable(sign_attestation):
        raise SupervisorError("sign_attestation must be callable")

    try:
        validated = _validate_run_facts(evidence_from_state(state, config))
    except _Refuse as refusal:
        return Refusal(refusal.reason, refusal.detail)

    # The supervisor STAMPS the completed decision — never taken from the caller.
    evidence = dict(validated)
    evidence["decision"] = DECISION_COMPLETED

    # Recompute-then-attest: sign the JCS the supervisor built, never caller bytes.
    evidence_jcs = _canonical_bytes(evidence)
    sig = sign_attestation(evidence_jcs)
    if not _nonempty_str(sig):
        raise SupervisorError("sign_attestation must return a non-empty signature string")

    attestation = {
        "attestation_protocol": ATTESTATION_PROTOCOL,
        "supervisor_key_id": supervisor_key_id,
        "sig": sig,
    }
    return RunAttestation(
        attestation=attestation,
        evidence_jcs=evidence_jcs,
        attestation_evidence_sha256=hashlib.sha256(evidence_jcs).hexdigest(),
    )
