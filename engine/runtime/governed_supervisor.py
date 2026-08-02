"""governed-supervisor acceptance/lease service core (Wave 3b-1B, rev-30 §5).

PURE, socket-free, key-free service-side decision logic for the supervisor's
governed-turn acceptance path. The DURABLE state machine + outbox + evidence
floor live in the Rust ``supervisor_ledger.rs`` (§5); this module is the pure
*decision* layer that sits in front of that ledger:

  1. **two-phase challenge verify** — given a signed
     ``brops.governed-turn-challenge.v1`` document (the exact shape the
     ``challenge_authority`` issuer mints), verify (phase A) its shape + signature
     and (phase B) that it is unexpired and that ``request_sha256`` re-derives from
     the challenge's own fields;
  2. **lease issuance** — mint the supervisor lease
     (``lease_expires_at_ms = now + LEASE_DURATION_MS``, the pinned launcher /
     executor executable digests from the supervisor's OWN trusted config);
  3. **the step-8a launch gate** — refuse a launch whose remaining lease budget is
     below ``MIN_LAUNCH_REMAINING_MS``.

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
class LaunchProceed:
    """The step-8a launch gate passed: this lease may drive one launch."""

    lease: Lease


# accept_open returns a lease OR a typed refusal; launch_gate returns a proceed
# token OR a typed refusal. Callers ``isinstance``-dispatch on the result.
AcceptResult = Union[Lease, Refusal]
GateResult = Union[LaunchProceed, Refusal]


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
    """The supervisor's OWN trusted config for lease issuance.

    ``launcher_executable_sha256`` / ``executor_executable_sha256`` are the pinned
    executable digests the supervisor binds into every lease; they come from here,
    never from the challenge document or any caller input. ``id_fn`` mints the
    opaque lease / execution-attempt ids (injected so tests are deterministic).
    """

    def __init__(
        self,
        launcher_executable_sha256: str,
        executor_executable_sha256: str,
        id_fn: Callable[[], str],
    ) -> None:
        if not _is_sha256_hex(launcher_executable_sha256):
            raise SupervisorError("launcher_executable_sha256 must be 64 hex characters")
        if not _is_sha256_hex(executor_executable_sha256):
            raise SupervisorError("executor_executable_sha256 must be 64 hex characters")
        if not callable(id_fn):
            raise SupervisorError("id_fn must be callable")
        self.launcher_executable_sha256 = launcher_executable_sha256.lower()
        self.executor_executable_sha256 = executor_executable_sha256.lower()
        self._id_fn = id_fn

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

    Only after BOTH phases pass is a :class:`Lease` minted:
    ``lease_expires_at_ms = now_ms + LEASE_DURATION_MS`` and the two pinned
    executable digests from ``config``. Returns the lease OR a typed
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

        # ---- Both phases passed: mint the lease ----
        return Lease(
            lease_id=config.mint_id(),
            execution_attempt_id=config.mint_id(),
            lease_expires_at_ms=now_ms + LEASE_DURATION_MS,
            launcher_executable_sha256=config.launcher_executable_sha256,
            executor_executable_sha256=config.executor_executable_sha256,
        )
    except _Refuse as refusal:
        return Refusal(refusal.reason, refusal.detail)


# ---------------------------------------------------------------------------
# launch_gate — §5 step-8a lease-expiry launch gate (pure).
# ---------------------------------------------------------------------------


def launch_gate(lease: Lease, now_ms: int) -> GateResult:
    """The §5 step-8a lease-expiry launch gate on the wall clock.

    Refuses when the remaining lease budget is below ``MIN_LAUNCH_REMAINING_MS``:
    ``now_ms + MIN_LAUNCH_REMAINING_MS > lease_expires_at_ms`` -> ``lease_expired``.
    Boundary: remaining exactly ``180000`` PROCEEDS; ``179999`` refuses; an already
    past-expiry lease is covered by the same inequality. Pure + host-independent.

    Returns :class:`LaunchProceed` (carrying the lease) OR a typed
    :class:`Refusal`. ``lease`` must be a :class:`Lease` and ``now_ms`` an int,
    else :class:`SupervisorError`.
    """
    if not isinstance(lease, Lease):
        raise SupervisorError("lease must be a Lease")
    if not _is_int(now_ms):
        raise SupervisorError("now_ms must be an int (epoch ms)")

    if now_ms + MIN_LAUNCH_REMAINING_MS > lease.lease_expires_at_ms:
        return Refusal(
            REFUSE_LEASE_EXPIRED,
            "remaining lease budget below %d ms" % MIN_LAUNCH_REMAINING_MS,
        )
    return LaunchProceed(lease=lease)


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
    """Strict-parse the supervisor's trusted run/evidence facts against the fixed
    ``ATTEST_INPUT_FIELDS`` shape (byte-compatible with the signer's evidence
    validation). Raises :class:`_Refuse` (``malformed``) on ANY drift: a
    non-mapping, an extra key (a smuggled ``decision``/``evidence_jcs``/``sig`` or
    an inline ``*_sha256`` claim), a missing key, or a wrong-typed value. This is
    the ONLY door the run facts enter through, and it admits NO pre-built evidence
    bytes and NO caller-chosen digest — every value is a small authoritative fact
    or a 64-hex content-address handle."""
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


def build_run_attestation(
    facts: Any,
    *,
    supervisor_key_id: str,
    sign_attestation: Callable[[bytes], str],
) -> AttestResult:
    """Build the §4.9 evidence from the supervisor's OWN trusted terminal run state
    and produce the ``brops.run-attestation.v1`` over it (recompute-then-attest).

    The no-oracle rule (§1.3-§1.4) is enforced structurally: the supervisor takes
    ONLY the fixed set of small facts + content-address handles
    (``ATTEST_INPUT_FIELDS``), STAMPS ``decision="completed"`` itself, and BUILDS
    the canonical ``JCS(evidence)`` here. It NEVER signs a caller-supplied evidence
    object or pre-built bytes — any attempt to smuggle one (an ``evidence_jcs`` /
    ``sig`` / ``decision`` key) is an unknown field and fails closed as
    ``malformed``. The ``evidence`` it builds is EXACTLY the signer's
    ``EVIDENCE_FIELDS`` shape, so ``JCS(evidence)`` is byte-identical to what
    ``isolated_signer._verify_supervisor_attestation`` re-hashes.

    ``sign_attestation(message: bytes) -> str`` is the injected signing seam: the
    supervisor holds the Ed25519 attestation private key behind it (no key literal
    lives in this module), and it is handed ONLY the ``JCS(evidence)`` bytes the
    supervisor assembled itself. It returns the detached signature as a string
    (base64url of the 64-byte Ed25519 signature, per §4.1 ``sig:b64url(64B)`` — the
    encoding the Rust broker decodes with ``URL_SAFE_NO_PAD``).

    Returns a :class:`RunAttestation` on success, or a typed :class:`Refusal`
    (``malformed``) when the trusted facts are ill-shaped. ``supervisor_key_id``
    must be a capped string and ``sign_attestation`` callable, else
    :class:`SupervisorError` (a supervisor-side config/seam fault, not a renderer
    verdict); a seam that returns a non-string / empty signature is likewise a
    :class:`SupervisorError` — never a half-built attestation.
    """
    if not _capped_str(supervisor_key_id):
        raise SupervisorError("supervisor_key_id must be a non-empty capped string")
    if not callable(sign_attestation):
        raise SupervisorError("sign_attestation must be callable")

    try:
        validated = _validate_run_facts(facts)
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
