"""§5 acceptance — the PRODUCTION supplier for §4.10(d)'s ``drive_acceptance`` seam.

§4.10(d) ends with a sentence and a hole. The sentence: "The supervisor authenticates the
peer UID, requires the ``INPUTS_READY`` staging row for ``(install_id, request_nonce,
challenge_handle)``, then drives §5 acceptance→lease→execution→record and the
isolated-signer flow (§6.1)." The hole: ``governed_evidence_request`` implements everything
up to the comma and hands a frozen :class:`~governed_evidence_request.GatedTurn` to an
injected continuation that, until this module, nothing supplied. Five built protocol pieces
ended at a seam.

This module is that continuation, and only that. It is a CLIENT of the §5 lifecycle, not a
second implementation of it: every rung it climbs is the same function the broker's five
§5 v2 wire ops climb.

  * §5 step 3/4 acceptance      → :func:`governed_supervisor.accept_open` + the
                                  acceptance-time predicate below +
                                  :func:`governed_supervisor_ledger.reuse_or_prepare`
  * §5 step 6/7 lease           → ``publish_artifact`` + ``mark_lease_ready``
  * §5 step 8a launch gate      → :func:`governed_supervisor_ledger.gate_and_start`
  * §5 step 9/10 execution      → the ``execution`` seam + ``mark_executing``
  * §5 step 11 completion       → :func:`governed_supervisor_server.complete_governed_run`
  * §6.1 step 10 attestation    → :func:`governed_supervisor.build_run_attestation`
  * §6.1 steps 11–12 signing    → the ``sign_result`` seam onto the isolated signer
  * §4.10(e) reply              → :func:`governed_turn_result.turn_result_signed` / ``_refused``

The one thing minted here, and the clauses that say so
------------------------------------------------------
**``execution_attempt_id``.** §4.10(d): the trigger "carries **no** ``execution_attempt_id``
(the supervisor reserves it, §5) and grants no authority by itself". §5 step 4: "CAS insert
``absent → ACCEPTED_PREPARED`` …; **reserve ``execution_attempt_id``**". §6.1 step 3 repeats
it. §4.10(a0) and the three staging protocols each refuse a request carrying one, and
``governed_turn_staging`` has no column for it. So the id exists for the first time at the
CAS below, once, and every earlier piece is structurally unable to name it.

**The acceptance clock.** §5 step 2: "Only once the staging row is ``INPUTS_READY``, read the
supervisor clock **exactly once** → ``challenge_accepted_at_ms``." §4.10(a0)'s clock read is
explicitly "a **resource-admission** read only: it is **NOT** persisted, is **NOT**
``challenge_accepted_at_ms``"; §4.10(d) reads no clock at all (``EvidenceRequestService.handle``
has no ``clock_ms`` parameter, deliberately). :meth:`AcceptanceDriver._accept` therefore calls
``clock_ms()`` exactly once and then passes that FROZEN instant to ``accept_open``, so the
value the §5 step-3 predicate is evaluated at and the value persisted in the row are the same
number by construction rather than by two reads happening to agree.

**The nonce.** §4.10(a0): the open "does **NOT** consume the nonce". §5 step 4's CAS is the
consume — ``UNIQUE (install_id, request_nonce)`` on ``governed_turn_acceptance`` is what makes
one signed challenge worth exactly one execution attempt, and §5 says a second attempt
"requires a **new signed challenge + new** ``request_nonce``". (§5's "Relationship to the
desktop nonce" keeps this distinct from the desktop's own one-time consume in
``verify_and_record_receipt``, which governs RECEIPT acceptance; neither substitutes for the
other.) The supervisor-side consume happens here and nowhere else.

What is NOT built, stated rather than implied
---------------------------------------------
**The contained execution.** §6.1 step 5's privileged recorder → setuid launcher → contained
executor needs Linux, six service uids, ``SO_PEERCRED``, cgroups and a setuid binary. It is an
injected, typed seam (:class:`ExecutionService`) and the DEFAULT binding is
:class:`RefusingExecutor`, which refuses. A supervisor with no execution provisioning answers
``platform_unsupported`` and creates no acceptance row — §4.5 makes that reason a "pre-record
Block: no lease is issued (or no exec occurs), no receipt/evidence/terminal record is
produced". Faking an execution to make a green path exist is the one thing this seam must not
do.

**The signer transport (§6.1 steps 11–12 are PARTIAL: the authority exists, the transport
to it does not).** §6.1 steps 11–12 belong to the isolated signer, a real component
(``isolated_signer.IsolatedSigner`` behind ``isolated_signer_server``). Its front door
allowlists ONLY the broker uid (``isolated_signer_server.peer_is_broker``), and the supervisor
is a different principal, so **there is no supervisor→signer transport in this tree**. The
seam here is typed to the signer's OWN frozen contract — it is handed a
``brops.sign-request.v1`` and must return the signer's own
``brops.governed-receipt-envelope.v1`` / ``brops.governed-receipt-refusal.v1`` reply — so a
deployment binds it to the real signer or the turn does not complete. A signer that cannot be
reached raises :class:`~governed_supervisor.SupervisorError`: §4.10(e) publishes no reason for
"the supervisor could not obtain its own signature", and inventing one would put a verdict
outside a closed set.

**The lease is not signed — §5 step 6's signature is NOT IMPLEMENTED anywhere in this
tree.** §5 step 6 and §3's artifact matrix require
``lease_handle = SHA256(JCS({payload, signature}))`` over a lease signed by a lease-issuer key.
No lease-issuer key exists anywhere in this tree, and the shipped ``accept-open`` op records
``lease_handle = lease_payload_sha256 = SHA256(JCS(payload))`` — the payload ALONE. That is the
same shape of contradiction the 2026-08-10 CORRECTION fixed for ``challenge_handle``, still
open for ``lease_handle``. This module does NOT compute a second, different ``lease_handle``:
two accounts of one field is strictly worse than one wrong account. It publishes and addresses
exactly the bytes the ledger persisted, identically to the broker path, and the divergence is
recorded here and in the report rather than papered over.

**Nothing wires this into a live supervisor.** ``engine/ci/live/run_supervisor.py`` constructs
no ``OpenService``/``StagingService``/``EvidenceRequestService``/``OutputReadService``, so the
entire sidecar-facing governed surface is unconfigured there and stays that way. This module
makes the supervisor side CAPABLE; it opens no door.

Only the Python standard library is used, and every clock is the injected ``clock_ms``.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, FrozenSet, Mapping, Optional, Tuple

import challenge_key_registry as registry
import governed_output_stream as output_streams
import governed_supervisor_ledger as ledger
from governed_evidence_request import GatedTurn
from governed_supervisor import (
    Accepted,
    Refusal,
    SupervisorConfig,
    SupervisorError,
    accept_open,
    build_run_attestation,
    recompute_request_sha256 as default_recompute_request_sha256,
)
from governed_supervisor_server import (
    CompletionRefused,
    REFUSE_EVIDENCE_MISMATCH,
    complete_governed_run,
)
from governed_turn_open import OpenConfig, _strict_decode
from governed_turn_result import (
    MAX_CONTAINMENT_EVIDENCE_B64_LEN,
    MAX_ENVELOPE_JCS_B64_LEN,
    turn_result_refused,
    turn_result_signed,
)
from isolated_signer import (
    ENVELOPE_ARTIFACT_TYPE,
    REFUSAL_ARTIFACT_TYPE,
    REASON_CHAIN_DISAGREEMENT,
    SIGN_REQUEST_PROTOCOL,
    _jcs_bytes,
)

# ---------------------------------------------------------------------------
# The §5/§6.1 refusal vocabulary — every mapping named, none inferred
# ---------------------------------------------------------------------------

#: ``governed_supervisor.accept_open``'s typed refusals → the closed §4.5 union.
#:
#: Each row is a decision, not a translation, so each is written out:
#:
#: * ``malformed`` — the stored challenge document does not have the §4.1 shape. Same word,
#:   same meaning, and ``malformed`` is one of the ratified twelve.
#: * ``signature_invalid`` → **``challenge_invalidated``**. The signature is re-checked HERE
#:   under the registry snapshot resolved at ``challenge_accepted_at_ms``, so a failure means
#:   the challenge is not valid *as of acceptance* — which is exactly what §5 step 3 names
#:   ``challenge_invalidated``. There is no ``signature_invalid`` member to relay.
#: * ``challenge_expired`` → **``timestamp_invalid``**. §4.5 is explicit: "``timestamp_invalid``
#:   additionally covers an **acceptance-time challenge-window expiry** … (distinct from the
#:   §4.10(a0) resource-admission ``challenge_expired``, which is pre-row and internal)".
#: * ``request_sha256_mismatch`` → **``hash_mismatch``**. A recomputed digest disagreeing with
#:   the one the document carries is a hash mismatch by the plainest reading.
#:   ``run_binding_invalid`` was the defensible alternative and is recorded as such.
#: * ``supervisor_mismatch`` → **``identity_denied``**. The challenge is authentic and names
#:   another supervisor; refusing to act on another principal's authorization is an identity
#:   denial, not a malformed document.
_ACCEPT_REASONS: Mapping[str, str] = {
    "malformed": "malformed",
    "signature_invalid": "challenge_invalidated",
    "challenge_expired": "timestamp_invalid",
    "request_sha256_mismatch": "hash_mismatch",
    "supervisor_mismatch": "identity_denied",
    # `lease_expired` is a `Refusal` reason `accept_open` declares and never returns (its
    # own launch gate moved to `governed_supervisor_ledger.gate_and_start`). It is mapped
    # anyway, to its identical governed member, so the table is total over the constant set
    # rather than total over the subset that happens to be reachable today.
    "lease_expired": "lease_expired",
}

#: The isolated signer's fixed refusal vocabulary → the closed §4.5 union.
#:
#: Twelve of the thirteen are the RATIFIED twelve and map to themselves — §4.5 built the
#: governed union's first half out of exactly this enum. The thirteenth does not exist in
#: §4.5 at all: ``chain_document_disagrees_with_attested_evidence`` was added to the signer
#: by audit R3-01 (a published chain document disagreeing with the attested evidence about a
#: field they BOTH carry) after rev-30 froze ``GOVERNED_REFUSAL_REASONS``. It is mapped to
#: ``hash_mismatch`` — the union's nearest member, and true of what happened — and the gap is
#: reported rather than closed by widening a frozen design enum from the code.
_SIGNER_REASONS: Mapping[str, str] = {
    REASON_CHAIN_DISAGREEMENT: "hash_mismatch",
}

#: A durable state that is terminal and is NOT ``COMPLETED`` → the verdict for a trigger that
#: arrives after it. ``EXPIRED`` is the §5 step-8a gate's deterministic destination, so it
#: keeps its own member; the other three have no member of their own and become
#: ``not_completed``, the ratified reason for "this run did not produce a governed result".
_TERMINAL_REASONS: Mapping[str, str] = {
    ledger.EXPIRED: "lease_expired",
    ledger.FAILED: "not_completed",
    ledger.RECOVERY_REQUIRED: "not_completed",
}


class _Refuse(Exception):
    """Internal control flow carrying a §4.5 member. Converted at the public boundary."""

    def __init__(self, reason: str, detail: str, receipt_id: Optional[str] = None) -> None:
        super().__init__("%s: %s" % (reason, detail))
        self.reason = reason
        self.detail = detail
        self.receipt_id = receipt_id


# ---------------------------------------------------------------------------
# The execution seam (§6.1 step 5) — typed, and refusing by default
# ---------------------------------------------------------------------------


class GovernedExecutionUnavailable(Exception):
    """This host cannot run a CONTAINED governed execution.

    Raised by :meth:`ExecutionService.preflight` before anything durable happens, so the
    verdict is §4.5's ``platform_unsupported`` — "the §0.1 platform gate /
    ``verify_distinct_principals()`` / ``verify_tcb_integrity()`` refused at start … a
    **pre-record Block**: no lease is issued (or no exec occurs), no receipt/evidence/terminal
    record is produced". Refusing here costs the challenge nothing: no row, no nonce consume,
    no attempt id, so the desktop may re-issue against the same signed challenge until it
    expires.
    """


@dataclass(frozen=True)
class ExecutionRequest:
    """Everything the recorder/launcher needs, and nothing it could choose.

    Every field is read out of the acceptance row the supervisor just wrote or off the
    frozen :class:`~governed_evidence_request.GatedTurn`. In particular the two executable
    digests are the ones the supervisor pinned into the lease from its OWN config (§4.3), not
    values an executor reports about itself.
    """

    execution_attempt_id: str
    run_id: str
    task_id: str
    workspace_id: str
    install_id: str
    lease_id: str
    lease_issued_at_ms: int
    lease_expires_at_ms: int
    system_handle: str
    history_handle: str
    generation_config_handle: str
    launcher_executable_sha256: str
    executor_executable_sha256: str


@dataclass(frozen=True)
class StartedExecution:
    """The §5 ``EXECUTION_STARTING → EXECUTING`` trigger, reported by the launcher.

    §5 locks that edge to one event: "the launcher confirms the child process is running AND
    its process metadata (``process_group_id``/``cgroup_id``) is durably persisted in the
    acceptance row". That is why :meth:`ExecutionService.run` reports the start through a
    CALLBACK rather than returning it with the result — the persist has to happen while the
    child is running, not after it exits, or ``EXECUTING`` would be a state the ledger only
    ever saw in hindsight.
    """

    process_group_id: str
    cgroup_id: str
    execution_started_marker: Optional[str] = None


@dataclass(frozen=True)
class ExecutionOutcome:
    """What the run produced — exactly the three §5 ``complete-run`` ``produced`` fields.

    Nothing else, and that is the F-01 shape: ``produced`` "carries ONLY run-produced values;
    every id, nonce, identity and acceptance timestamp is rejected as an unknown field".
    ``ledger.validate_completion_facts`` enforces it again downstream, so a seam that grew a
    fourth field would be refused rather than trusted.
    """

    output_handle: str
    containment_evidence_handle: str
    completed_at_ms: int


class ExecutionService:
    """The §6.1 step-5 contained execution, as a two-method interface.

    ``preflight()`` answers "can this host contain an execution at all?" and is called BEFORE
    the acceptance clock is read. ``run(request, on_started)`` launches once and returns what
    the run produced, calling ``on_started`` the moment the child is confirmed running.
    """

    def preflight(self) -> None:
        raise NotImplementedError

    def run(self, request: ExecutionRequest,
            on_started: Callable[[StartedExecution], None]) -> ExecutionOutcome:
        raise NotImplementedError


@dataclass(frozen=True)
class RefusingExecutor(ExecutionService):
    """The DEFAULT execution binding: refuse, with the reason in the exception.

    This is the fail-closed direction and it is the honest state of every host in this
    repository. §6.1 step 5's ladder is Linux-only and needs six distinct service uids, a
    root-owned setuid launcher, cgroups and ``SO_PEERCRED``; none of that exists on a
    developer box or on the CI runner, and a stub that returned plausible bytes would make
    every test below prove something about the stub.
    """

    detail: str = ("no contained governed executor is provisioned on this host (§6.1 step 5 "
                   "requires the privileged recorder → setuid launcher → contained executor)")

    def preflight(self) -> None:
        raise GovernedExecutionUnavailable(self.detail)

    def run(self, request: ExecutionRequest,
            on_started: Callable[[StartedExecution], None]) -> ExecutionOutcome:
        # Unreachable through the driver (`preflight` refuses first) and still fail-closed,
        # because "the preflight passed" is not something this class may assume about a
        # caller it does not control.
        raise GovernedExecutionUnavailable(self.detail)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AcceptanceConfig:
    """The supervisor's own §5 provisioning, beside the config it already had.

    ``supervisor`` and ``open_config`` are the EXISTING trusted objects — the identity/pins
    the attestation is built from, and the §4.2 root anchor + epoch floor the registry is
    resolved against. They are reused rather than re-declared so the open-time check and the
    acceptance-time check cannot drift apart about which root they trust.

    ``execution_allowlist`` is §2's ``GOVERNED_EXECUTION_ALLOWLIST``: the set of
    ``generation_config_sha256`` values this supervisor is configured to execute, consulted
    ONCE, at acceptance (§4.5's ``model_profile_unknown``). It is a permission gate and NOT an
    identity: §2 makes ``model_profile_id`` the pure formula ``"cfg-sha256:" +
    generation_config_sha256``, so a config removed from this set later cannot reinterpret a
    record already signed under it. An EMPTY allowlist refuses every turn, which is the
    direction ``SignerConfig.allowed_policies`` already established: a supervisor that has not
    been told which model profile it may run has not been told it may run one.
    """

    supervisor: SupervisorConfig
    open_config: OpenConfig
    execution_allowlist: FrozenSet[str] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.supervisor, SupervisorConfig):
            raise SupervisorError("AcceptanceConfig.supervisor must be a SupervisorConfig")
        if not isinstance(self.open_config, OpenConfig):
            raise SupervisorError("AcceptanceConfig.open_config must be an OpenConfig")
        if self.open_config.supervisor_id != self.supervisor.supervisor_id:
            # Two supervisor identities in one supervisor: the open would admit turns for one
            # and the acceptance would lease them for another, and §5 Phase C's
            # `supervisor_mismatch` would be checked against whichever object was nearer.
            raise SupervisorError(
                "AcceptanceConfig names two supervisor_ids: %r (open) != %r (acceptance)"
                % (self.open_config.supervisor_id, self.supervisor.supervisor_id))
        if not isinstance(self.execution_allowlist, (frozenset, set)):
            raise SupervisorError(
                "AcceptanceConfig.execution_allowlist must be a set of generation_config digests")
        for entry in self.execution_allowlist:
            if not _is_lower_sha256_hex(entry):
                raise SupervisorError(
                    "execution_allowlist entries must be 64 lowercase hex generation_config digests")


def _is_lower_sha256_hex(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(c in "0123456789abcdef" for c in value)


def _b64url(data: bytes) -> str:
    """base64url without padding — the ``*_b64`` transport convention §4.1/§4.10(e) use and
    the encoding ``governed_turn_result._require_b64url`` round-trips to prove canonical."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _registry_bound_config(config: SupervisorConfig,
                           snapshot: registry.RegistrySnapshot) -> SupervisorConfig:
    """The supervisor config with its ``challenge_registry_*`` block replaced by the snapshot
    resolved AT ``challenge_accepted_at_ms``.

    §5 step 3: "Bind this exact **acceptance-time** ``challenge_registry_handle``/``_hash``/
    ``_epoch``/``_root_key_id`` into the acceptance row → lease → record → attestation →
    envelope." The shipped ``SupervisorConfig`` carries those four as deployment CONSTANTS,
    which is a different claim: it says which registry the operator wrote down, not which one
    was in force when this turn was accepted. Under a rotation the two disagree, and the row
    would record the stale epoch — the same epoch ``_BOUND_FIELDS`` compares to decide whether
    a retry is the same turn.

    ``root_key_id`` is not taken from the snapshot: ``resolve_registry`` already refuses any
    document whose ``root_key_id`` is not the pinned anchor, so the snapshot's value IS the
    anchor's, and reading it back from the document would be reading a constant out of an
    input.
    """
    return SupervisorConfig(
        launcher_executable_sha256=config.launcher_executable_sha256,
        executor_executable_sha256=config.executor_executable_sha256,
        id_fn=config.mint_id,
        supervisor_id=config.supervisor_id,
        executor_id=config.executor_id,
        builder_id=config.builder_id,
        policy_id=config.policy_id,
        policy_version=config.policy_version,
        policy_bundle_handle=config.policy_bundle_handle,
        challenge_registry_handle=snapshot.registry_handle,
        challenge_registry_hash=snapshot.registry_hash,
        challenge_registry_epoch=snapshot.registry_epoch,
        challenge_registry_root_key_id=config.challenge_registry_root_key_id,
    )


# ---------------------------------------------------------------------------
# The driver
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AcceptanceDriver:
    """§5 acceptance → lease → execution → record → signer, as one callable.

    Constructed with the supervisor's own config and the seams a deployment supplies, and
    then passed straight to ``EvidenceRequestService(drive_acceptance=...)``: the driver IS
    the ``Callable[[GatedTurn], Dict]`` §4.10(d) declares, so no adapter sits between the
    gate and the ladder.

    Every reply it returns is a §4.10(e) frame, built by ``governed_turn_result`` and
    therefore validated by the same code §4.10(d) checks it with. A supervisor-side fault —
    a seam that is missing, a signer that cannot be reached, a store that lost an artifact a
    signed record pins — raises :class:`~governed_supervisor.SupervisorError` instead:
    §4.10(e) is a REPLY and publishes no reason for "the supervisor could not reach a
    verdict", so inventing one would put a verdict outside a closed set.
    """

    config: AcceptanceConfig
    conn: Any
    clock_ms: Callable[[], int]
    #: The content-addressed protected-store read. Production: ``brops_evidence_store.
    #: EvidenceStore.read``, which refuses unless ``sha256(bytes) == handle``. Used for the
    #: challenge document published at §4.10(a0) and for the containment artifact §4.10(e)
    #: carries; both are addressed by digests the supervisor itself recorded.
    read_artifact: Callable[[str], bytes]
    #: The atomic create-if-absent publish into ``store/sup/`` (§6 step 1).
    publish_artifact: Callable[[bytes], str]
    #: The supervisor's OWN registry state (§4.2 root pin + floor). Called FRESH at
    #: acceptance — §5 step 3: "a fresh ``load_trusted_keys``-style reload + floor — do NOT
    #: reuse the open-time snapshot".
    resolve_registry_document: Callable[[], Any]
    verify_root_sig: Callable[[bytes, str, str], bool]
    verify_challenge_sig: Callable[[bytes, str, str], bool]
    #: The RECORDER's evidence chain, read from a directory only the recorder writes (F-01).
    read_run_evidence: Callable[[str], Optional[bytes]]
    #: The supervisor attestation key, behind a seam (§6.1 step 10).
    sign_attestation: Callable[[bytes], str]
    supervisor_attestation_key_id: str
    #: §6.1 steps 11–12. Handed a ``brops.sign-request.v1``; must return the isolated
    #: signer's own reply. See the module docstring for why this has no transport in tree.
    sign_result: Callable[[Mapping[str, Any]], Mapping[str, Any]]
    #: §4.10(f)'s BOTH halves — the mint at completion and the read that serves it. Required,
    #: not optional: §4.10(f) says "a completing turn's stream is **always** created", and a
    #: §4.10(e) ``signed`` frame REQUIRES an ``output_stream_id``, so a supervisor that
    #: cannot mint one cannot answer a completed turn at all.
    output_read_service: Any
    execution: ExecutionService = RefusingExecutor()
    recompute_request_sha256: Callable[[Mapping[str, Any]], str] = default_recompute_request_sha256

    def __post_init__(self) -> None:
        if not isinstance(self.config, AcceptanceConfig):
            raise SupervisorError("AcceptanceDriver.config must be an AcceptanceConfig")
        if self.conn is None:
            raise SupervisorError("AcceptanceDriver requires a durable ledger connection")
        for name in ("clock_ms", "read_artifact", "publish_artifact",
                     "resolve_registry_document", "verify_root_sig", "verify_challenge_sig",
                     "read_run_evidence", "sign_attestation", "sign_result",
                     "recompute_request_sha256"):
            if not callable(getattr(self, name)):
                raise SupervisorError("AcceptanceDriver.%s must be callable" % name)
        if not isinstance(self.supervisor_attestation_key_id, str) or not self.supervisor_attestation_key_id:
            raise SupervisorError(
                "AcceptanceDriver.supervisor_attestation_key_id must be a non-empty string")
        if self.output_read_service is None:
            raise SupervisorError(
                "AcceptanceDriver requires an OutputReadService: §4.10(f) mints the output "
                "stream a §4.10(e) signed frame is required to carry")
        if not isinstance(self.execution, ExecutionService):
            raise SupervisorError("AcceptanceDriver.execution must be an ExecutionService")

    # -- the public seam ----------------------------------------------------

    def __call__(self, gated: GatedTurn) -> Dict[str, Any]:
        """Drive one admitted turn and return its §4.10(e) verdict."""
        if not isinstance(gated, GatedTurn):
            raise SupervisorError("drive_acceptance takes the §4.10(d) GatedTurn")
        try:
            return self._drive(gated)
        except _Refuse as refusal:
            return turn_result_refused(refusal.reason, refusal.receipt_id)

    # -- the ladder ---------------------------------------------------------

    def _drive(self, gated: GatedTurn) -> Dict[str, Any]:
        """Resume-or-start, then climb. The state the ledger is IN decides where the ladder
        is entered, which is what makes a second §4.10(d) trigger for one turn idempotent
        rather than a second execution (§5 steps 10–12)."""
        row = self._locate(gated)
        if row is None:
            row = self._accept(gated)

        state = row["state"]
        if state == ledger.ACCEPTED_PREPARED:
            row = self._publish_lease(row)
            state = row["state"]

        if state in (ledger.EXECUTION_STARTING, ledger.EXECUTING):
            # §5 step 10, LOCKED: "once `EXECUTION_STARTING` is durable the attempt is NEVER
            # automatically relaunched … A restart finding `EXECUTION_STARTING` or
            # `EXECUTING` without complete terminal proof moves to `RECOVERY_REQUIRED`". The
            # child may already have called the model, so "no live child and no output" does
            # not prove non-execution. A repeated trigger is exactly that restart.
            self._advance(row, ledger.RECOVERY_REQUIRED, "no terminal proof for a started attempt")
            raise _Refuse("not_completed",
                          "attempt was already %s; moved to RECOVERY_REQUIRED, never relaunched"
                          % state, row["receipt_id"])

        if state == ledger.LEASE_READY:
            row = self._gate_and_execute(row, gated)
            state = row["state"]

        if state == ledger.BLOCKED:
            raise _Refuse(self._blocked_reason(row), "attempt is durably BLOCKED",
                          row["receipt_id"])
        if state in _TERMINAL_REASONS:
            raise _Refuse(_TERMINAL_REASONS[state], "attempt is durably %s" % state,
                          row["receipt_id"])

        # Everything left is `COMPLETED`. There is deliberately no `state != COMPLETED` fault
        # here: the branches above cover eight of the nine members of the ledger's closed
        # `state` domain and the DDL `CHECK` makes a tenth value unstorable, so such a line
        # could not fire — the class this repository deletes rather than ships. What replaces
        # it is `test_the_state_ladder_is_exhaustive_over_the_closed_enum`, which compares the
        # branch set to `governed_supervisor_ledger.ALL_STATES` and fails the day a state is
        # added without a branch.
        return self._attest_and_sign(row)

    # -- §5 step 3/4: acceptance -------------------------------------------

    def _locate(self, gated: GatedTurn) -> Any:
        """Find this turn's existing attempt, or prove there is none.

        Two lookups, because the acceptance ledger carries two independent UNIQUEs and the
        trigger names both keys:

          * the challenge finds a row bound to a DIFFERENT ``(install_id, request_nonce)``
            ⇒ ``acceptance_conflict``. §4.5: "the §5 ``absent → ACCEPTED_PREPARED`` CAS loses
            to a conflicting existing binding".
          * the challenge finds nothing but the NONCE already has an attempt ⇒
            ``challenge_replay``. §4.5 pins that member to exactly this gate: "the §5
            acceptance CAS finds the ``request_nonce`` already ACCEPTED for a different
            ``challenge_handle`` (a supervisor-side replay)". It is decided here rather than
            inside the CAS because at the CAS the two are indistinguishable — both surface
            as one ``Conflict``.
        """
        row = ledger.load_acceptance_by_challenge(self.conn, gated.challenge_handle)
        if row is not None:
            if (row["install_id"] != gated.install_id
                    or row["request_nonce"] != gated.request_nonce):
                raise _Refuse("acceptance_conflict",
                              "this challenge is already accepted under another install/nonce",
                              row["receipt_id"])
            return row
        if ledger.load_lease_by_nonce(self.conn, gated.install_id,
                                      gated.request_nonce) is not None:
            raise _Refuse("challenge_replay",
                          "this request_nonce is already accepted for a different challenge")
        return None

    def _accept(self, gated: GatedTurn) -> Any:
        """§5 steps 1–5 for a turn with no attempt yet."""
        # §4.5: `platform_unsupported` is a PRE-RECORD block, so the host gate runs before
        # the clock is read and before anything durable exists. A challenge refused here is
        # untouched: no row, no nonce consume, no attempt id, so the desktop may re-issue
        # against the same signed challenge until it expires.
        try:
            self.execution.preflight()
        except GovernedExecutionUnavailable as exc:
            raise _Refuse("platform_unsupported", str(exc))

        document_bytes, payload, sig = self._load_challenge(gated)

        # §5 step 2: "read the supervisor clock EXACTLY ONCE -> challenge_accepted_at_ms".
        accepted_at = self.clock_ms()
        if not isinstance(accepted_at, int) or isinstance(accepted_at, bool):
            raise SupervisorError("clock_ms must return an int (epoch ms)")

        snapshot, key = self._acceptance_time_predicate(payload, accepted_at)

        # `verify_sig` is bound to the key the ACCEPTANCE-TIME snapshot selected, so
        # `accept_open`'s Phase A is not a weaker second opinion: it checks the same
        # signature under the key that is valid now, over the canonical bytes it reassembles
        # from the payload itself.
        result = accept_open(
            {"payload": payload, "sig": sig},
            accepted_at,
            config=_registry_bound_config(self.config.supervisor, snapshot),
            verify_sig=lambda message, signature: self.verify_challenge_sig(
                message, signature, key.public_key),
            recompute_request_sha256=self.recompute_request_sha256,
        )
        if isinstance(result, Refusal):
            raise _Refuse(_ACCEPT_REASONS.get(result.reason, "malformed"), result.detail)
        if not isinstance(result, Accepted):  # pragma: no cover - Accepted | Refusal only
            raise SupervisorError("accept_open returned an unexpected result type")

        # The canonicality gate, stated as the equality that actually matters. `_load_challenge`
        # already proved `sha256(document_bytes) == gated.challenge_handle`;
        # `accept_open` computed `challenge_handle_for(payload, sig) = sha256(JCS({payload,sig}))`.
        # The two agree IFF the stored bytes are canonical, and if they do not, §4.10(d)'s join
        # of the staging row to its acceptance row on `(install_id, request_nonce,
        # challenge_handle)` would be joining two different digests of one turn.
        if result.acceptance.challenge_handle != gated.challenge_handle:
            raise _Refuse("hash_mismatch",
                          "the stored challenge document is not the canonical {payload, sig}")

        try:
            # The CAS outcome (created vs idempotent) is deliberately discarded: this driver
            # decides where to resume from the row's STATE, not from whether this call was
            # the one that wrote it. `reuse_or_prepare` already guarantees a replay gets the
            # ORIGINAL attempt, so both outcomes name the same one turn.
            _outcome, row = ledger.reuse_or_prepare(self.conn, result.acceptance, accepted_at)
        except ledger.Conflict as exc:
            raise _Refuse("acceptance_conflict", str(exc))
        except ledger.LedgerError as exc:
            raise SupervisorError("acceptance ledger fault: %s" % exc)

        # §2 / §4.5 `model_profile_unknown`: the execution-permission allowlist, "consulted
        # once at acceptance", is consulted HERE — after the CAS, because §4.5 makes this a
        # `BLOCKED` verdict and §5's state matrix gives `BLOCKED` only two predecessors,
        # `ACCEPTED_PREPARED` and `LEASE_READY`. There is no acceptance row to block before
        # the CAS, and "no lease is issued, no launch" is satisfied by blocking before
        # `_publish_lease` runs.
        if row["generation_config_handle"] not in self.config.execution_allowlist:
            self._advance(row, ledger.BLOCKED, "model_profile_unknown")
            raise _Refuse("model_profile_unknown",
                          "generation_config cfg-sha256:%s is not in this supervisor's "
                          "execution allowlist" % (row["generation_config_handle"],),
                          row["receipt_id"])
        return row

    def _load_challenge(self, gated: GatedTurn) -> Tuple[bytes, Mapping[str, Any], str]:
        """Re-read the EXACT signed challenge document §4.10(a0) published (§6 step 1).

        The supervisor possesses the bytes because it published them itself at open; it does
        not possess the object, because §4.10(d) carries three identifiers and nothing else.
        The digest is re-derived here rather than trusted from the seam: ``read_artifact`` is
        injected, and a supervisor that took a store's word for which document it returned
        would have replaced a content address with a promise.
        """
        try:
            document_bytes = self.read_artifact(gated.challenge_handle)
        except Exception as exc:  # noqa: BLE001 — one fail-closed verdict for every store failure
            raise _Refuse("handle_missing",
                          "the published challenge document is unreadable: %s" % exc)
        if not isinstance(document_bytes, (bytes, bytearray)):
            raise SupervisorError("read_artifact must return bytes")
        document_bytes = bytes(document_bytes)
        if hashlib.sha256(document_bytes).hexdigest() != gated.challenge_handle:
            raise _Refuse("handle_missing",
                          "the store returned bytes that are not this challenge_handle")
        try:
            document = _strict_decode(document_bytes)
        except Exception as exc:  # noqa: BLE001
            raise _Refuse("malformed", "the stored challenge document does not decode: %s" % exc)
        if not isinstance(document, Mapping) or "payload" not in document or "sig" not in document:
            raise _Refuse("malformed", "the stored challenge document is not {payload, sig}")
        return document_bytes, document["payload"], document["sig"]

    def _acceptance_time_predicate(
        self, payload: Any, accepted_at: int,
    ) -> Tuple[registry.RegistrySnapshot, registry.ChallengeKey]:
        """§5 step 3 — the ACCEPTANCE-TIME AUTHORITATIVE verification (P0-3).

        Three things happen here that did not happen at §4.10(a0), and each is the reason the
        design calls the open's check "preliminary":

          1. the registry is re-resolved from the supervisor's OWN state, FRESH. §5 step 3 is
             explicit — "do NOT reuse the open-time snapshot" — because a registry rotated
             between open and acceptance is precisely how a revoked key comes back.
          2. key validity is applied **as of ``challenge_accepted_at_ms``**, not as of
             ``challenge_issued_at_ms``. ``registry.select_key`` owns both boundary rules
             (window inclusive, revocation strict) and is reused rather than restated.
          3. the two window limbs ``accept_open`` does NOT check are checked, so no limb is
             owned twice: ``accept_open`` owns ``challenge_accepted_at_ms ≤
             challenge_expires_at_ms`` (its ``challenge_expired``, mapped to
             ``timestamp_invalid``), and this owns ``challenge_issued_at_ms ≤
             challenge_accepted_at_ms`` and ``requested_at_ms ≤ challenge_accepted_at_ms``.
             Duplicating the third limb here would leave one of the two checks unable to fail.

        Failure of 1 or 2 is ``challenge_invalidated``, the member §5 step 3 names by that
        name. Failure of 3 is ``timestamp_invalid``, which §4.5 assigns to the acceptance-time
        window.
        """
        if not isinstance(payload, Mapping):
            raise _Refuse("malformed", "the stored challenge payload is not an object")
        try:
            document = self.resolve_registry_document()
        except Exception:  # noqa: BLE001 — a resolver that raises must produce a verdict
            raise _Refuse("challenge_invalidated",
                          "the acceptance-time registry could not be resolved")
        snapshot, _reason = registry.resolve_registry(
            document,
            anchor=self.config.open_config.anchor(),
            epoch_floor=self.config.open_config.registry_epoch_floor,
            verify_root_sig=self.verify_root_sig,
        )
        if snapshot is None:
            raise _Refuse("challenge_invalidated",
                          "no accepted registry snapshot at challenge_accepted_at_ms")
        try:
            key, _reason = registry.select_key(
                snapshot, payload.get("challenge_key_id"), accepted_at)
        except registry.RegistryError as exc:
            raise _Refuse("challenge_invalidated", "key selection refused: %s" % exc)
        if key is None:
            raise _Refuse("challenge_invalidated",
                          "the challenge key is not usable at challenge_accepted_at_ms")

        issued = payload.get("challenge_issued_at_ms")
        requested = payload.get("requested_at_ms")
        if not isinstance(issued, int) or isinstance(issued, bool) or issued > accepted_at:
            raise _Refuse("timestamp_invalid",
                          "challenge_issued_at_ms is not <= challenge_accepted_at_ms")
        if not isinstance(requested, int) or isinstance(requested, bool) or requested > accepted_at:
            raise _Refuse("timestamp_invalid",
                          "requested_at_ms is not <= challenge_accepted_at_ms")
        return snapshot, key

    # -- §5 steps 6/7: the lease -------------------------------------------

    def _publish_lease(self, row: Any) -> Any:
        """§5 steps 6–7 / §6 step 1: publish the persisted lease document, then
        ``ACCEPTED_PREPARED → LEASE_READY`` only once it re-hashes.

        The publish is create-if-absent over the EXACT canonical bytes persisted at
        acceptance, so a crash after the commit and before this re-signs nothing and
        re-publishes idempotently (§5's "after commit before signature → re-sign from
        ``lease_payload_bytes`` (deterministic)").

        The store's own re-derivation of the handle is held against the digest the ledger
        persisted. That check CAN fire — a store that returns a different address for bytes
        it was just given is a store that is not content-addressed — and it is the only thing
        standing between "the lease is published" and "something is published".

        **The lease is NOT signed here, and §5 step 6 says it must be.** See the module
        docstring: no lease-issuer key exists in this tree, so ``lease_handle`` is
        ``SHA256(JCS(payload))`` and not ``SHA256(JCS({payload, signature}))``. This path
        computes the same handle the broker's ``accept-open`` op does rather than a second,
        differently-derived one.
        """
        try:
            handle = self.publish_artifact(bytes(row["lease_payload_bytes"]))
        except Exception as exc:  # noqa: BLE001
            raise _Refuse("lease_not_ready", "the lease document could not be published: %s" % exc,
                          row["receipt_id"])
        if not isinstance(handle, str) or handle.lower() != row["lease_payload_sha256"]:
            raise _Refuse("hash_mismatch",
                          "the published lease does not re-hash to the persisted digest",
                          row["receipt_id"])
        try:
            ledger.mark_lease_ready(self.conn, row["execution_attempt_id"], handle,
                                    self.clock_ms())
        except ledger.LedgerError as exc:
            # §4.5 pins this member to this hop: "`lease_not_ready` = the execute trigger
            # (§4.10(d)) arrives before the row reaches `LEASE_READY`".
            raise _Refuse("lease_not_ready", str(exc), row["receipt_id"])
        return self._reload(row)

    # -- §5 steps 8a–11: gate, execute, record -----------------------------

    def _gate_and_execute(self, row: Any, gated: GatedTurn) -> Any:
        """§5 step 8a's launch gate, the one-time launch, and the completion."""
        attempt = row["execution_attempt_id"]
        try:
            state = ledger.gate_and_start(self.conn, attempt, self.clock_ms())
        except ledger.IllegalTransition:
            # A concurrent trigger already moved this row on. Re-read and let `_drive`'s
            # state ladder decide; this one launches nothing.
            return self._reload(row)
        except ledger.LedgerError as exc:
            raise SupervisorError("launch gate fault: %s" % exc)
        if state == ledger.EXPIRED:
            # §5 step 8a / P1-4: a lease-expiry gate failure is DETERMINISTICALLY `EXPIRED`,
            # never `BLOCKED`, and no launch occurs.
            raise _Refuse("lease_expired",
                          "remaining lease budget below MIN_LAUNCH_REMAINING_MS",
                          row["receipt_id"])

        request = ExecutionRequest(
            execution_attempt_id=attempt,
            run_id=row["run_id"],
            task_id=row["task_id"],
            workspace_id=row["workspace_id"],
            install_id=row["install_id"],
            lease_id=row["lease_id"],
            lease_issued_at_ms=row["lease_issued_at_ms"],
            lease_expires_at_ms=row["lease_expires_at_ms"],
            system_handle=row["system_handle"],
            history_handle=row["history_handle"],
            generation_config_handle=row["generation_config_handle"],
            launcher_executable_sha256=self.config.supervisor.launcher_executable_sha256,
            executor_executable_sha256=self.config.supervisor.executor_executable_sha256,
        )

        def on_started(started: Any) -> None:
            if not isinstance(started, StartedExecution):
                raise SupervisorError("on_started takes a StartedExecution")
            ledger.mark_executing(
                self.conn, attempt,
                process_group_id=started.process_group_id,
                cgroup_id=started.cgroup_id,
                execution_started_marker=started.execution_started_marker,
                now_ms=self.clock_ms(),
            )

        try:
            outcome = self.execution.run(request, on_started)
        except Exception as exc:  # noqa: BLE001 — every launch failure is one durable verdict
            # §5's crash matrix, applied to a failure the supervisor CAN see: "after
            # `EXECUTION_STARTING` commit but before the launcher call → `RECOVERY_REQUIRED`,
            # never relaunch". The supervisor cannot distinguish "never launched" from
            # "launched, called the model, and died", so both take the fail-closed edge.
            self._advance(row, ledger.RECOVERY_REQUIRED, "execution seam failed: %s" % exc)
            raise _Refuse("not_completed",
                          "the contained execution did not produce a governed result: %s" % exc,
                          row["receipt_id"])
        if not isinstance(outcome, ExecutionOutcome):
            raise SupervisorError("the execution seam must return an ExecutionOutcome")

        row = self._reload(row)
        try:
            complete_governed_run(
                self.conn, row,
                {
                    "output_handle": outcome.output_handle,
                    "containment_evidence_handle": outcome.containment_evidence_handle,
                    "completed_at_ms": outcome.completed_at_ms,
                },
                self.clock_ms,
                publish_artifact=self.publish_artifact,
                read_run_evidence=self.read_run_evidence,
                output_read_service=self.output_read_service,
            )
        except CompletionRefused as exc:
            # The one completion refusal with a governed member of its own is the F-01 wall:
            # the reply digest the run reported is not the digest the RECORDER captured.
            raise _Refuse(
                "hash_mismatch" if exc.reason == REFUSE_EVIDENCE_MISMATCH else "malformed",
                exc.detail, row["receipt_id"])
        except ledger.StaleEvidence as exc:
            raise _Refuse("stale_evidence", str(exc), row["receipt_id"])
        except ledger.EvidenceFork as exc:
            raise _Refuse("evidence_fork", str(exc), row["receipt_id"])
        except ledger.Conflict as exc:
            raise _Refuse("acceptance_conflict", str(exc), row["receipt_id"])
        except ledger.IllegalTransition as exc:
            raise _Refuse("not_completed", str(exc), row["receipt_id"])
        except ledger.LedgerError as exc:
            raise _Refuse("malformed", str(exc), row["receipt_id"])
        return self._reload(row)

    # -- §6.1 steps 10–13: attest, sign, reply -----------------------------

    def _attest_and_sign(self, row: Any) -> Dict[str, Any]:
        """§6.1 steps 10–13 over a durably ``COMPLETED`` attempt.

        This is also the whole of §5 step 11's idempotent retry: "A ``COMPLETED`` retry
        returns **only** the same attempt's independently re-verified terminal record/result".
        Nothing here writes; the evidence is rebuilt from the same durable rows and Ed25519 is
        deterministic, so a second trigger for a completed turn produces the byte-identical
        frame rather than a second execution or a second token.
        """
        attempt = row["execution_attempt_id"]
        state = ledger.load_attestation_state(self.conn, row["run_id"], attempt)
        if state is None:
            # `COMPLETED` without a completion row is unreachable through this ladder
            # (`record_completion` writes both in one transaction), so this is tampered or
            # foreign durable state — refused, never worked around.
            raise _Refuse("not_completed", "no terminal run state for a COMPLETED attempt",
                          row["receipt_id"])

        attestation = build_run_attestation(
            state,
            config=self.config.supervisor,
            supervisor_key_id=self.supervisor_attestation_key_id,
            sign_attestation=self.sign_attestation,
        )
        if isinstance(attestation, Refusal):
            raise _Refuse("malformed", attestation.detail, row["receipt_id"])

        # §5(f): the signer sees the ATTESTED bytes. The evidence object is parsed back out
        # of the exact `JCS(evidence)` that was signed rather than rebuilt beside it, so the
        # signer's re-hash and the envelope's `attestation_evidence_sha256` are over
        # identical bytes by construction.
        sign_request = {
            "protocol": SIGN_REQUEST_PROTOCOL,
            "attestation": dict(attestation.attestation),
            "evidence": json.loads(attestation.evidence_jcs.decode("utf-8")),
        }
        reply = self.sign_result(sign_request)
        if not isinstance(reply, Mapping):
            raise SupervisorError("the isolated signer seam must return the signer's reply")
        artifact_type = reply.get("artifact_type")
        if artifact_type == REFUSAL_ARTIFACT_TYPE:
            reason = reply.get("reason")
            raise _Refuse(_SIGNER_REASONS.get(reason, reason if isinstance(reason, str) else "malformed"),
                          "the isolated signer refused", row["receipt_id"])
        if artifact_type != ENVELOPE_ARTIFACT_TYPE or reply.get("status") != "signed":
            raise SupervisorError(
                "the isolated signer seam returned neither a §4.9 envelope nor a typed refusal")

        payload = reply.get("payload")
        signature_b64 = reply.get("signature_b64")
        if not isinstance(payload, Mapping) or not isinstance(signature_b64, str):
            raise SupervisorError("the isolated signer reply carries no signed §4.9 payload")

        stream = output_streams.load_stream_for_attempt(self.conn, attempt)
        if stream is None:
            # §4.10(f): "a completing turn's stream is ALWAYS created", and a §4.10(e)
            # `signed` frame REQUIRES an `output_stream_id`. A completed attempt with no row
            # has had its token swept or evicted, and §4.10(f) names that verdict.
            raise _Refuse("stream_unknown", "no output stream for a COMPLETED attempt",
                          row["receipt_id"])

        envelope_jcs_b64 = _b64url(_jcs_bytes(payload))
        attestation_evidence_jcs_b64 = _b64url(attestation.evidence_jcs)
        containment_b64 = self._containment_b64(state.containment_evidence_handle,
                                                row["receipt_id"])

        # §4.6 freezes `envelope_jcs_b64 <= 2848` as a machine-checked derivation of the §4.9
        # payload "at schema max", and for the payload this tree's signer actually builds
        # that derivation is WRONG: nine of its seventeen string fields are ids capped at 128,
        # and at 125 characters each the encoding is 2852. The frame the design describes is
        # therefore expressible and over its own cap. This bound is enforced as a governed
        # `oversize` REFUSAL rather than left to fault the frame validator, because a
        # supervisor that cannot express its own verdict must still return one. The
        # attestation limb is deliberately absent: the same arithmetic gives 4032 against
        # 4664, so a check there could not fire — see the test that proves it.
        if len(envelope_jcs_b64) > MAX_ENVELOPE_JCS_B64_LEN:
            raise _Refuse("oversize",
                          "the signed envelope is %d base64url chars, over the §4.6 cap of %d"
                          % (len(envelope_jcs_b64), MAX_ENVELOPE_JCS_B64_LEN),
                          row["receipt_id"])
        if len(containment_b64) > MAX_CONTAINMENT_EVIDENCE_B64_LEN:
            raise _Refuse("oversize",
                          "the containment artifact is %d base64url chars, over the §4.10(e) "
                          "cap of %d" % (len(containment_b64), MAX_CONTAINMENT_EVIDENCE_B64_LEN),
                          row["receipt_id"])

        return turn_result_signed(
            receipt_id=row["receipt_id"],
            output_stream_id=stream["output_stream_id"],
            output_bytes=stream["output_bytes"],
            output_sha256=stream["output_sha256"],
            envelope_jcs_b64=envelope_jcs_b64,
            signature_b64=signature_b64,
            key_id=payload.get("key_id"),
            attestation_evidence_jcs_b64=attestation_evidence_jcs_b64,
            attestation_signature_b64=attestation.attestation["sig"],
            supervisor_attestation_key_id=attestation.attestation["supervisor_key_id"],
            containment_evidence_b64=containment_b64,
            run_id=row["run_id"],
            execution_attempt_id=attempt,
            lease_id=row["lease_id"],
        )

    def _containment_b64(self, handle: str, receipt_id: Optional[str]) -> str:
        """The containment artifact, read from the store and carried in the §4.10(e) frame.

        §5(j) is PARTIAL here: the recorder-side WRITER of the containment report is the
        §6.1 step-5 execution seam and is therefore NOT IMPLEMENTED on this host; what IS
        implemented is the half this module owns — the report must exist and be non-empty or
        the turn is refused.

        §4.10(e) makes ``containment_evidence_b64`` nullable and this path never produces the
        null: §5(j) says "a missing or empty report is a REFUSAL, not a fallback", and
        ``containment_missing`` is a ratified member of the closed union. So the nullable arm
        of §4.10(e) has no producer here, deliberately.
        """
        try:
            data = self.read_artifact(handle)
        except Exception as exc:  # noqa: BLE001
            raise _Refuse("containment_missing",
                          "the containment artifact is unreadable: %s" % exc, receipt_id)
        if not isinstance(data, (bytes, bytearray)) or not data:
            raise _Refuse("containment_missing",
                          "the containment artifact is empty", receipt_id)
        return _b64url(bytes(data))

    # -- small shared helpers ----------------------------------------------

    def _reload(self, row: Any) -> Any:
        fresh = ledger.load_acceptance(self.conn, row["execution_attempt_id"])
        if fresh is None:  # pragma: no cover - the row was read one statement ago
            raise SupervisorError("the acceptance row vanished mid-turn")
        return fresh

    def _advance(self, row: Any, target: str, failure_reason: str) -> None:
        """Take a terminal edge, tolerating a concurrent driver that took it first.

        An :class:`~governed_supervisor_ledger.IllegalTransition` here means the row is
        already terminal — which is the state this call was trying to reach — so it is
        swallowed rather than turned into a second verdict about the same turn.
        """
        try:
            ledger.advance(self.conn, row["execution_attempt_id"], target, self.clock_ms(),
                           failure_reason=failure_reason[:512])
        except ledger.IllegalTransition:
            return

    def _blocked_reason(self, row: Any) -> str:
        """A durably ``BLOCKED`` attempt re-serves the reason it was blocked with.

        ``failure_reason`` is written by this module and is always a member of the closed
        union, but it is a free-text column, so a value that is not a member is treated as
        the generic ``not_completed`` rather than relayed — §4.10(e)'s reason must come from
        the published set whatever a tampered row says.
        """
        from governed_turn_result import GOVERNED_REFUSAL_REASONS

        reason = row["failure_reason"]
        return reason if reason in GOVERNED_REFUSAL_REASONS else "not_completed"


__all__ = [
    "AcceptanceConfig",
    "AcceptanceDriver",
    "ExecutionOutcome",
    "ExecutionRequest",
    "ExecutionService",
    "GovernedExecutionUnavailable",
    "RefusingExecutor",
    "StartedExecution",
]
