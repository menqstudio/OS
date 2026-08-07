//! Wave 3b-1B — the broker's real governed-turn chain executor (design-GREEN rev-30 §4.10(g)/§5/§6/§7).
//!
//! This replaces the interim `UpstreamBlockedExecutor` with a [`GovernedExecutor`] that actually drives the
//! trusted chain. It separates ORCHESTRATION (this module — the ordered hops through
//! challenge-authority → supervisor(+lease) → launcher → executor → isolated-signer → final verification)
//! from CRYPTO VERIFICATION (`brops_core::governed_verification`, which is independently exhaustively
//! tested). The sub-chain is injected as a [`GovernedTurnChain`] so the orchestration wiring is
//! unit-testable without the running services; the real Linux implementation drives the AF_UNIX sockets and
//! calls `governed_verification::verify_and_accept` to produce the [`AcceptedOutput`] — a lost/refusing hop
//! surfaces as a closed [`TurnReason`], never a fabricated acceptance.
//!
//! ## The assembled flow ([`GovernedChain::run_verified`])
//!
//! One governed turn is an ASSEMBLY of already-proven parts — this module invents no crypto:
//!
//!  1. **challenge-authority** (`create-pending` → `issue`) over its socket ⇒ a signed
//!     `brops.governed-turn-challenge.v1` document. The turn facts sent to `create-pending` come from the
//!     broker's OWN trusted resolution ([`TurnResolver`]), never the wire.
//!  2. **supervisor** (`accept-open {challenge_doc}` → lease, then `launch-gate {lease}` → proceed) over its
//!     socket. The lease authorizes exactly one privileged execution.
//!  3. **EXECUTION** — the privileged recorder → setuid launcher → executor chain, abstracted behind
//!     [`GovernedExecution`]. It produces the raw output bytes, the `sign_request` to hand the signer, and
//!     the supervisor attestation (the exact evidence bytes + detached signature). A unit test injects a
//!     fake; the real Linux impl ([`linux::LinuxGovernedExecution`]) spawns the setuid chain and is marked
//!     `LINUX-RUN-PENDING`, failing closed until that chain + protected store are provisioned.
//!  4. **isolated-signer** (`sign-result {sign_request}`) over its socket ⇒ the flat 23-key
//!     `brops.governed-receipt-envelope.v1` payload + its Ed25519 signature.
//!  5. **final acceptance** — `governed_verification::verify_and_accept` over the broker's OWN pinned keys +
//!     its OWN trusted `Expected` (never values from the wire): it reconstructs `JCS(payload)`, re-verifies
//!     the isolated-signer + supervisor signatures, recomputes `request_sha256`, and length+digest-gates the
//!     output. Only its `Ok` yields an [`AcceptedOutput`]; any hop failure / refusal / bad reply / verify
//!     failure ⇒ a closed [`TurnReason`].
//!
//! The pure orchestration types + the trait-driven flow are cross-platform (they compile and unit-test on
//! any host); only the real AF_UNIX transport + the privileged spawn are `#[cfg(target_os = "linux")]`.

use std::sync::Mutex;

use serde_json::{json, Value};

use brops_core::broker_orchestrator::GovernedExecutor;
use brops_core::governed_message_store::AcceptedOutput;
use brops_core::governed_turn_ipc::{TurnReason, ValidatedRequest};
use brops_core::governed_verification::{
    verify_and_accept, AcceptanceLedger, BrokerContext, PinnedKeys, ReceiptEnvelope,
    SupervisorAttestation,
};
use brops_core::receipt::IssuedRequest;

use crate::chain_hops::{hop_roundtrip, HopConn, HopError, Principal};

/// The full authority→supervisor→launcher→executor→signer→verification sub-chain for ONE governed turn,
/// abstracted to its one contract: given the validated request + the broker-minted ids, either produce the
/// cryptographically-verified accepted output or a closed refusal reason. The real impl drives the OS
/// services; a test injects a fake.
pub trait GovernedTurnChain {
    fn run_verified(
        &self,
        req: &ValidatedRequest,
        broker_turn_id: &str,
        request_nonce: &str,
    ) -> Result<AcceptedOutput, TurnReason>;
}

/// The broker's real [`GovernedExecutor`]: it delegates the whole trusted chain to a [`GovernedTurnChain`]
/// and returns exactly what that chain verified. It NEVER fabricates an accepted output — it only relays a
/// chain-verified one or the chain's closed refusal.
pub struct ChainExecutor<C: GovernedTurnChain> {
    chain: C,
}

impl<C: GovernedTurnChain> ChainExecutor<C> {
    pub fn new(chain: C) -> Self {
        ChainExecutor { chain }
    }
}

impl<C: GovernedTurnChain> GovernedExecutor for ChainExecutor<C> {
    fn execute_and_verify(
        &self,
        req: &ValidatedRequest,
        broker_turn_id: &str,
        request_nonce: &str,
    ) -> Result<AcceptedOutput, TurnReason> {
        self.chain.run_verified(req, broker_turn_id, request_nonce)
    }
}

// =================================================================================================
// Injected seams — everything the pure orchestration needs from the outside, each a trait so the flow
// is unit-testable with fakes and the real Linux transport/execution is a separate, clearly-marked impl.
// =================================================================================================

/// A factory that opens ONE fresh single-request/single-response connection to a trusted principal. Each
/// hop (each protocol op) gets its own connection, matching the servers' one-frame-per-connection contract.
/// A bare closure `Fn(Principal) -> Result<Box<dyn HopConn>, HopError>` satisfies this (blanket impl below),
/// so the real Linux transport and a test's canned-reply factory share one seam.
pub trait HopConnector {
    fn connect(&self, principal: Principal) -> Result<Box<dyn HopConn>, HopError>;
}

impl<F> HopConnector for F
where
    F: Fn(Principal) -> Result<Box<dyn HopConn>, HopError>,
{
    fn connect(&self, principal: Principal) -> Result<Box<dyn HopConn>, HopError> {
        self(principal)
    }
}

/// The broker's OWN trusted per-turn resolution (§4.10(g)): the pinned manifest keys + the `Expected`
/// request-envelope facts + the create-pending turn facts + the committed-message author. EVERYTHING the
/// final acceptance trusts comes from here (root-signed manifest + broker config), NEVER from a hop reply —
/// so a compromised principal cannot smuggle a favourable key or request binding. Owned so the borrowed
/// verification structs can point at it for the whole turn.
#[derive(Debug, Clone)]
pub struct ResolvedTurn {
    // --- pinned manifest keys (resolved from the broker's root-signed, anti-rollback-checked manifest) ---
    pub isolated_signer_key_id: String,
    pub isolated_signer_public_key: [u8; 32],
    pub supervisor_attestation_key_id: String,
    pub supervisor_attestation_public_key: [u8; 32],
    // --- Expected request-envelope facts (request_nonce is the broker-minted nonce, passed separately) ---
    pub workspace_id: String,
    pub install_id: String,
    pub system_sha256: String,
    pub history_sha256: String,
    pub generation_config_sha256: String,
    /// `requested_at` as the canonical decimal string of the epoch-ms (matches the §2.2 request envelope).
    pub requested_at: String,
    // --- create-pending turn facts the challenge-authority requires (§2.1) ---
    pub run_id: String,
    pub task_id: String,
    pub requested_at_ms: i64,
    // --- committed-message identity ---
    pub author: String,
}

/// Resolves the broker's OWN trusted turn facts + pinned keys for a request. In production this reads the
/// root-signed key manifest (root-verify + anti-rollback + production-key resolution) and the broker's
/// resolved system/history/generation-config hashes; a test injects a fixed resolution.
pub trait TurnResolver {
    fn resolve(
        &self,
        req: &ValidatedRequest,
        broker_turn_id: &str,
        request_nonce: &str,
    ) -> Result<ResolvedTurn, TurnReason>;
}

/// A supervisor-minted lease (§5): the exhaustive fixed shape the supervisor returns from `accept-open` and
/// the broker forwards verbatim to `launch-gate` + into the privileged execution.
#[derive(Debug, Clone)]
pub struct Lease {
    pub lease_id: String,
    pub execution_attempt_id: String,
    pub lease_expires_at_ms: i64,
    pub launcher_executable_sha256: String,
    pub executor_executable_sha256: String,
    /// The exact lease JSON the supervisor returned, forwarded byte-faithfully to `launch-gate`.
    pub raw: Value,
}

/// The inputs the privileged execution receives: the request + broker-minted ids + the lease that
/// authorizes exactly this execution + the broker's trusted resolution.
pub struct ExecutionPlan<'a> {
    pub req: &'a ValidatedRequest,
    pub broker_turn_id: &'a str,
    pub request_nonce: &'a str,
    pub resolved: &'a ResolvedTurn,
    pub lease: &'a Lease,
}

/// What the privileged execution produces for the signer hop + the final acceptance.
pub struct ExecutionArtifacts {
    /// The exact reassembled reply bytes (§4.10(f) pull). The broker length+digest-gates these against the
    /// signed envelope — never a caller-supplied hash.
    pub output: Vec<u8>,
    /// The `brops.sign-request.v1` body `{protocol, attestation, evidence}` handed to the isolated signer
    /// verbatim. The signer strict-validates it, verifies the attestation, and RECOMPUTES every digest.
    pub sign_request: Value,
    /// The EXACT `JCS(evidence)` bytes the supervisor attested — carried through so the final acceptance can
    /// check `SHA256(evidence_jcs) == envelope.attestation_evidence_sha256` against the bytes it holds.
    pub attestation_evidence_jcs: Vec<u8>,
    /// The supervisor's detached Ed25519 signature (base64url) over `attestation_evidence_jcs`.
    pub attestation_signature_b64: String,
}

/// The privileged recorder → setuid launcher → executor chain, abstracted (§6). Given the lease-authorized
/// plan it runs the real execution and returns the output bytes + the attestation/evidence the broker
/// forwards to the isolated signer. A unit test injects a fake; the real Linux impl spawns the setuid chain
/// (see [`linux::LinuxGovernedExecution`], `LINUX-RUN-PENDING`).
pub trait GovernedExecution {
    fn execute(&self, plan: &ExecutionPlan) -> Result<ExecutionArtifacts, TurnReason>;
}

// =================================================================================================
// The pure, cross-platform orchestration.
// =================================================================================================

/// The broker's real governed sub-chain, generic over its injected seams so the whole ordered flow is
/// unit-testable on any host. It sequences the hops, drives the privileged execution, then runs the final
/// crypto acceptance over the broker's OWN pinned keys + trusted `Expected`. It NEVER takes trust from an
/// unsigned hop value — the only path to an [`AcceptedOutput`] is a successful
/// `governed_verification::verify_and_accept`.
pub struct GovernedChain<C, R, E, L>
where
    C: HopConnector,
    R: TurnResolver,
    E: GovernedExecution,
    L: AcceptanceLedger,
{
    connector: C,
    resolver: R,
    execution: E,
    /// The one-time nonce + receipt-id freshness ledger (§7.1(c)(d)). In production a DB transaction; a
    /// test injects an in-memory one. Behind a `Mutex` so `run_verified(&self, …)` can consume it without
    /// two concurrent turns sharing a borrow.
    ledger: Mutex<L>,
}

impl<C, R, E, L> GovernedChain<C, R, E, L>
where
    C: HopConnector,
    R: TurnResolver,
    E: GovernedExecution,
    L: AcceptanceLedger,
{
    pub fn new(connector: C, resolver: R, execution: E, ledger: L) -> Self {
        GovernedChain {
            connector,
            resolver,
            execution,
            ledger: Mutex::new(ledger),
        }
    }

    /// One framed request→reply roundtrip to `principal` over a fresh connection. Fails CLOSED on connect
    /// failure, frame/transport error, malformed reply, or any principal refusal (`ok:false` / a `reason`).
    /// Returns the parsed success reply object.
    fn hop(&self, principal: Principal, request: &Value) -> Result<Value, TurnReason> {
        let bytes = serde_json::to_vec(request).map_err(|_| TurnReason::UpstreamBlocked)?;
        let mut conn = self
            .connector
            .connect(principal)
            .map_err(|e| e.to_turn_reason())?;
        let reply = hop_roundtrip(conn.as_mut(), &bytes).map_err(|e| e.to_turn_reason())?;
        let value: Value = serde_json::from_slice(&reply).map_err(|_| TurnReason::UpstreamBlocked)?;
        // A principal reply is a success ONLY if it says so; `ok:false` (with its typed `reason`) or a
        // missing/false `ok` is a fail-closed refusal — never a fabricated success.
        let ok = value.get("ok").and_then(Value::as_bool).unwrap_or(false);
        if !ok {
            return Err(TurnReason::UpstreamBlocked);
        }
        Ok(value)
    }
}

impl<C, R, E, L> GovernedTurnChain for GovernedChain<C, R, E, L>
where
    C: HopConnector,
    R: TurnResolver,
    E: GovernedExecution,
    L: AcceptanceLedger,
{
    fn run_verified(
        &self,
        req: &ValidatedRequest,
        broker_turn_id: &str,
        request_nonce: &str,
    ) -> Result<AcceptedOutput, TurnReason> {
        // (0) The broker's OWN trusted resolution — pinned keys + Expected facts. Resolved BEFORE any hop so
        //     the trust anchors never depend on a principal reply.
        let resolved = self.resolver.resolve(req, broker_turn_id, request_nonce)?;

        // (1) challenge-authority: create-pending. Turn facts are the broker's own (§2.1 fixed shape).
        let create_pending = json!({
            "op": "create-pending",
            "run_id": resolved.run_id,
            "task_id": resolved.task_id,
            "workspace_id": resolved.workspace_id,
            "install_id": resolved.install_id,
            "request_nonce": request_nonce,
            "system_sha256": resolved.system_sha256,
            "history_sha256": resolved.history_sha256,
            "generation_config_sha256": resolved.generation_config_sha256,
            "requested_at_ms": resolved.requested_at_ms,
        });
        let reply = self.hop(Principal::ChallengeAuthority, &create_pending)?;
        let pending_id = reply
            .get("pending_challenge_id")
            .and_then(Value::as_str)
            .ok_or(TurnReason::UpstreamBlocked)?
            .to_string();

        // (2) challenge-authority: issue ⇒ the signed brops.governed-turn-challenge.v1 document.
        let issue = json!({ "op": "issue", "pending_challenge_id": pending_id });
        let reply = self.hop(Principal::ChallengeAuthority, &issue)?;
        let challenge_doc = reply
            .get("challenge")
            .cloned()
            .ok_or(TurnReason::UpstreamBlocked)?;

        // (3) supervisor: accept-open ⇒ lease.
        let accept_open = json!({ "op": "accept-open", "challenge_doc": challenge_doc });
        let reply = self.hop(Principal::Supervisor, &accept_open)?;
        let lease = parse_lease(reply.get("lease").ok_or(TurnReason::UpstreamBlocked)?)?;

        // (4) supervisor: launch-gate ⇒ proceed (budget re-check) — BY ATTEMPT ID ONLY.
        //     The broker no longer hands the lease back for the supervisor to judge itself
        //     against: the supervisor reads the window it persisted at acceptance and CASes
        //     the attempt LEASE_READY → EXECUTION_STARTING in the same transaction (§5 v2,
        //     independent audit F-01/F-23). We could not choose a favourable expiry if we
        //     wanted to, and a refused gate durably EXPIREs the attempt — no launch follows.
        let launch_gate = json!({
            "op": "launch-gate",
            "execution_attempt_id": lease.execution_attempt_id,
        });
        let reply = self.hop(Principal::Supervisor, &launch_gate)?;
        if !reply.get("proceed").and_then(Value::as_bool).unwrap_or(false) {
            return Err(TurnReason::UpstreamBlocked);
        }

        // (5) EXECUTION — the privileged recorder → launcher → executor chain (abstracted; real Linux spawn
        //     is LINUX-RUN-PENDING). Produces the output bytes + the sign_request + the supervisor
        //     attestation the broker forwards + re-checks.
        let plan = ExecutionPlan {
            req,
            broker_turn_id,
            request_nonce,
            resolved: &resolved,
            lease: &lease,
        };
        let artifacts = self.execution.execute(&plan)?;

        // (6) isolated-signer: sign-result ⇒ the flat 23-key envelope payload + its Ed25519 signature.
        let sign = json!({ "op": "sign-result", "sign_request": artifacts.sign_request });
        let reply = self.hop(Principal::IsolatedSigner, &sign)?;
        let payload = reply.get("payload").ok_or(TurnReason::UpstreamBlocked)?;
        let env_sig = reply
            .get("signature")
            .and_then(Value::as_str)
            .ok_or(TurnReason::UpstreamBlocked)?
            .to_string();
        let env = OwnedEnvelope::from_payload(payload)?;

        // (7) FINAL ACCEPTANCE — the broker-owned predicate over its OWN pinned keys + trusted Expected. The
        //     envelope + its signature came from the wire; EVERY trust anchor (keys, request binding) is the
        //     broker's own. verify_and_accept reconstructs JCS(payload), re-verifies both signatures,
        //     recomputes request_sha256, and length+digest-gates the output. Any mismatch ⇒ closed reason.
        let message_id = format!("m-{broker_turn_id}");
        let envelope = env.as_receipt_envelope();
        let keys = PinnedKeys {
            isolated_signer_key_id: &resolved.isolated_signer_key_id,
            isolated_signer_public_key: &resolved.isolated_signer_public_key,
            supervisor_attestation_key_id: &resolved.supervisor_attestation_key_id,
            supervisor_attestation_public_key: &resolved.supervisor_attestation_public_key,
        };
        let expected = IssuedRequest {
            workspace_id: &resolved.workspace_id,
            install_id: &resolved.install_id,
            request_nonce,
            system_sha256: &resolved.system_sha256,
            history_sha256: &resolved.history_sha256,
            generation_config_sha256: &resolved.generation_config_sha256,
            requested_at: &resolved.requested_at,
        };
        let attestation = SupervisorAttestation {
            evidence_jcs: &artifacts.attestation_evidence_jcs,
            signature_b64: &artifacts.attestation_signature_b64,
        };
        let ctx = BrokerContext {
            broker_turn_id,
            message_id: &message_id,
            conversation_id: &req.conversation_id,
            author: &resolved.author,
            // F-26: the run identity the broker itself authorized — its own resolution for
            // run/task, and the attempt id from the lease the supervisor granted IT. The final
            // acceptance compares the signed envelope against these; a receipt from another
            // attempt no longer passes on a matching nonce + output alone.
            expected_run_id: &resolved.run_id,
            expected_task_id: &resolved.task_id,
            expected_execution_attempt_id: &lease.execution_attempt_id,
        };
        let mut ledger = self.ledger.lock().map_err(|_| TurnReason::UpstreamBlocked)?;
        verify_and_accept(
            &expected,
            &envelope,
            &env_sig,
            &attestation,
            &keys,
            &artifacts.output,
            &ctx,
            &mut *ledger,
        )
    }
}

/// Parse the supervisor lease object (§5 exhaustive shape) into a [`Lease`]; the raw JSON is retained for a
/// byte-faithful `launch-gate` re-check. A missing/mistyped field fails closed.
fn parse_lease(v: &Value) -> Result<Lease, TurnReason> {
    let s = |k: &str| {
        v.get(k)
            .and_then(Value::as_str)
            .map(str::to_string)
            .ok_or(TurnReason::UpstreamBlocked)
    };
    Ok(Lease {
        lease_id: s("lease_id")?,
        execution_attempt_id: s("execution_attempt_id")?,
        lease_expires_at_ms: v
            .get("lease_expires_at_ms")
            .and_then(Value::as_i64)
            .ok_or(TurnReason::UpstreamBlocked)?,
        launcher_executable_sha256: s("launcher_executable_sha256")?,
        executor_executable_sha256: s("executor_executable_sha256")?,
        raw: v.clone(),
    })
}

// =================================================================================================
// Audit **IDX-4** (broker-side half) — the request digests this turn will ATTEST must equal the pins in
// the launcher's §4.3 lease FILE, checked at TURN time.
//
// The privileged half of this lives in the launcher, which compares the same lease against the root-owned
// canonical config from a compile-time path; that is the wall, because the broker cannot steer it. This
// half is deliberately the weaker one and is worth stating precisely:
//
//   * it does NOT constrain a hostile broker BINARY — a modified broker simply would not run it. What it
//     constrains is the broker's INPUT: the deployment installs the driver root-owned under `$LIVE/bin`,
//     so the broker uid picks the `--config` it loads, not the code that loads it;
//   * a hostile config could name a lease file of its own alongside divergent digests, and this comparison
//     would then be self-consistent — but the recorder's root-owned policy pins `--lease`, so a run whose
//     lease is not the canonical one is refused before any execution. Either the lease compared here is
//     the canonical lease, or there is no turn.
//
// Nothing about that argument makes the launcher's check redundant; it is why this one is not the wall.
// =================================================================================================

/// Extract the three governed-request digests from a §4.3 launcher lease body (`key=value`, the exact
/// format `launcher/src/main.rs` parses). Fail-closed: each of the three keys must appear EXACTLY ONCE
/// with a 64-char lowercase-hex value, and a line without `=` is malformed. Keys the launcher owns
/// (uids/gids, the image pin) are not the broker's business and are ignored, not validated twice.
pub fn lease_request_pins(body: &str) -> Option<(String, String, String)> {
    let (mut system, mut history, mut generation_config) = (None, None, None);
    for line in body.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let (k, v) = line.split_once('=')?;
        let (k, v) = (k.trim(), v.trim());
        let slot = match k {
            "system_sha256" => &mut system,
            "history_sha256" => &mut history,
            "generation_config_sha256" => &mut generation_config,
            _ => continue,
        };
        if slot.is_some()
            || v.len() != 64
            || !v.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
        {
            return None; // duplicate or non-canonical digest ⇒ fail closed
        }
        *slot = Some(v.to_string());
    }
    Some((system?, history?, generation_config?))
}

/// Audit **IDX-4**, the broker-side DECISION: the digests this turn resolves — the ones the receipt's
/// `request_sha256` is recomputed from — must equal the lease's request pins, which are the bytes the
/// launcher will let the executor read. Any divergence, or a lease that cannot be read as a pinned
/// request at all, is a closed turn: no spawn, no attestation, no receipt.
///
/// Slot-by-slot, so a transposed pair is a refusal rather than a set that happens to match.
pub fn verify_resolved_matches_lease(
    resolved: &ResolvedTurn,
    lease_body: &str,
) -> Result<(), TurnReason> {
    let (system, history, generation_config) =
        lease_request_pins(lease_body).ok_or(TurnReason::UpstreamBlocked)?;
    if resolved.system_sha256 != system
        || resolved.history_sha256 != history
        || resolved.generation_config_sha256 != generation_config
    {
        return Err(TurnReason::UpstreamBlocked);
    }
    Ok(())
}

/// The isolated-signer's flat 23-key `brops.governed-receipt-envelope.v1` payload parsed into OWNED fields
/// so the borrowed [`ReceiptEnvelope`] can point at it for the verify call. A missing/mistyped key fails
/// closed BEFORE any signature check (verify_and_accept re-checks the identity fields regardless).
struct OwnedEnvelope {
    artifact_type: String,
    key_id: String,
    receipt_id: String,
    run_id: String,
    execution_attempt_id: String,
    task_id: String,
    workspace_id: String,
    install_id: String,
    request_nonce: String,
    request_sha256: String,
    record_handle: String,
    lease_handle: String,
    execution_receipt_handle: String,
    output_sha256: String,
    evidence_final_event_hash: String,
    supervisor_attestation_key_id: String,
    attestation_evidence_sha256: String,
    output_bytes: u64,
    challenge_accepted_at_ms: i64,
    completed_at_ms: i64,
    evidence_event_count: i64,
    evidence_last_sequence: i64,
    evidence_head_sequence: i64,
}

impl OwnedEnvelope {
    fn from_payload(p: &Value) -> Result<Self, TurnReason> {
        let s = |k: &str| {
            p.get(k)
                .and_then(Value::as_str)
                .map(str::to_string)
                .ok_or(TurnReason::UpstreamBlocked)
        };
        let i = |k: &str| {
            p.get(k)
                .and_then(Value::as_i64)
                .ok_or(TurnReason::UpstreamBlocked)
        };
        let u = |k: &str| {
            p.get(k)
                .and_then(Value::as_u64)
                .ok_or(TurnReason::UpstreamBlocked)
        };
        Ok(OwnedEnvelope {
            artifact_type: s("artifact_type")?,
            key_id: s("key_id")?,
            receipt_id: s("receipt_id")?,
            run_id: s("run_id")?,
            execution_attempt_id: s("execution_attempt_id")?,
            task_id: s("task_id")?,
            workspace_id: s("workspace_id")?,
            install_id: s("install_id")?,
            request_nonce: s("request_nonce")?,
            request_sha256: s("request_sha256")?,
            record_handle: s("record_handle")?,
            lease_handle: s("lease_handle")?,
            execution_receipt_handle: s("execution_receipt_handle")?,
            output_sha256: s("output_sha256")?,
            evidence_final_event_hash: s("evidence_final_event_hash")?,
            supervisor_attestation_key_id: s("supervisor_attestation_key_id")?,
            attestation_evidence_sha256: s("attestation_evidence_sha256")?,
            output_bytes: u("output_bytes")?,
            challenge_accepted_at_ms: i("challenge_accepted_at_ms")?,
            completed_at_ms: i("completed_at_ms")?,
            evidence_event_count: i("evidence_event_count")?,
            evidence_last_sequence: i("evidence_last_sequence")?,
            evidence_head_sequence: i("evidence_head_sequence")?,
        })
    }

    fn as_receipt_envelope(&self) -> ReceiptEnvelope<'_> {
        ReceiptEnvelope {
            artifact_type: &self.artifact_type,
            key_id: &self.key_id,
            receipt_id: &self.receipt_id,
            run_id: &self.run_id,
            execution_attempt_id: &self.execution_attempt_id,
            task_id: &self.task_id,
            workspace_id: &self.workspace_id,
            install_id: &self.install_id,
            request_nonce: &self.request_nonce,
            request_sha256: &self.request_sha256,
            record_handle: &self.record_handle,
            lease_handle: &self.lease_handle,
            execution_receipt_handle: &self.execution_receipt_handle,
            output_sha256: &self.output_sha256,
            output_bytes: self.output_bytes,
            challenge_accepted_at_ms: self.challenge_accepted_at_ms,
            completed_at_ms: self.completed_at_ms,
            evidence_final_event_hash: &self.evidence_final_event_hash,
            evidence_event_count: self.evidence_event_count,
            evidence_last_sequence: self.evidence_last_sequence,
            evidence_head_sequence: self.evidence_head_sequence,
            supervisor_attestation_key_id: &self.supervisor_attestation_key_id,
            attestation_evidence_sha256: &self.attestation_evidence_sha256,
        }
    }
}

/// The real Linux sub-chain: drives the AF_UNIX challenge-authority / supervisor / isolated-signer hops via
/// a real socket [`HopConnector`], and (once provisioned) the privileged execution spawn. The pure
/// orchestration above is host-independent; only the socket transport + the setuid spawn live here.
#[cfg(target_os = "linux")]
pub mod linux {
    use super::*;
    use base64::engine::general_purpose::URL_SAFE_NO_PAD;
    use base64::Engine as _;
    use brops_core::governed_message_store::sha256_hex;
    use brops_core::ipc_framing::{encode_frame, LENGTH_PREFIX_BYTES, MAX_FRAME_PAYLOAD_BYTES};
    use std::io::{Read, Write};
    use std::os::unix::net::UnixStream;
    use std::process::Command;
    use std::time::{SystemTime, UNIX_EPOCH};

    /// Socket paths for the trusted principals (each owned by its own service UID; §2.6 provisioning).
    pub struct ChainSockets {
        pub authority: String,
        pub supervisor: String,
        pub signer: String,
    }

    /// Real AF_UNIX connector: one fresh single-request/single-response connection per hop (matching the
    /// servers' one-frame-per-connection contract). A connect/transport failure is a closed [`HopError`].
    pub struct LinuxHopConnector {
        pub sockets: ChainSockets,
    }

    impl HopConnector for LinuxHopConnector {
        fn connect(&self, principal: Principal) -> Result<Box<dyn HopConn>, HopError> {
            let path = match principal {
                Principal::ChallengeAuthority => &self.sockets.authority,
                Principal::Supervisor => &self.sockets.supervisor,
                Principal::IsolatedSigner => &self.sockets.signer,
            };
            let stream = UnixStream::connect(path).map_err(|_| HopError::Unavailable)?;
            Ok(Box::new(UnixHopConn { stream }))
        }
    }

    /// A live AF_UNIX peer as a [`HopConn`]: `send_all` writes the framed request; `recv_all` reads exactly
    /// one length-prefixed reply frame (bounded) and returns it framed for `decode_one`.
    struct UnixHopConn {
        stream: UnixStream,
    }

    impl HopConn for UnixHopConn {
        fn send_all(&mut self, frame: &[u8]) -> Result<(), HopError> {
            self.stream.write_all(frame).map_err(|_| HopError::Io)?;
            self.stream.flush().map_err(|_| HopError::Io)
        }

        fn recv_all(&mut self) -> Result<Vec<u8>, HopError> {
            let mut prefix = [0u8; LENGTH_PREFIX_BYTES];
            self.stream.read_exact(&mut prefix).map_err(|_| HopError::Io)?;
            let declared = u32::from_be_bytes(prefix) as usize;
            if declared == 0 || declared > MAX_FRAME_PAYLOAD_BYTES {
                return Err(HopError::BadReply);
            }
            let mut body = vec![0u8; declared];
            self.stream.read_exact(&mut body).map_err(|_| HopError::Io)?;
            let mut framed = Vec::with_capacity(LENGTH_PREFIX_BYTES + declared);
            framed.extend_from_slice(&prefix);
            framed.extend_from_slice(&body);
            Ok(framed)
        }
    }

    /// Read exactly one length-prefixed reply frame (bounded) from a live AF_UNIX peer; a short/oversize/lost
    /// frame is a closed [`TurnReason`]. Mirrors the servers' 4-byte-big-endian one-frame-per-connection wire.
    fn read_one_reply(stream: &mut UnixStream) -> Result<Vec<u8>, TurnReason> {
        let mut prefix = [0u8; LENGTH_PREFIX_BYTES];
        stream.read_exact(&mut prefix).map_err(|_| TurnReason::UpstreamBlocked)?;
        let declared = u32::from_be_bytes(prefix) as usize;
        if declared == 0 || declared > MAX_FRAME_PAYLOAD_BYTES {
            return Err(TurnReason::UpstreamBlocked);
        }
        let mut body = vec![0u8; declared];
        stream.read_exact(&mut body).map_err(|_| TurnReason::UpstreamBlocked)?;
        Ok(body)
    }

    /// The deployment-static remainder the live privileged execution needs beyond the per-turn plan: the
    /// paths of the setuid chain + protected store, the supervisor `attest-run` socket, and the fixed run
    /// facts (ids, identities, protected-chain + authorization handles, evidence-head counters). The per-turn
    /// facts (`workspace/install/run/task/request_nonce/requested_at` + the granted lease) come from the
    /// plan — never duplicated here — so the attestation is bound to exactly the broker's own resolution.
    #[derive(Debug, Clone)]
    pub struct ExecutionConfig {
        /// The invoker prefix that lands the recorder on its dedicated UID (e.g.
        /// `["sudo","-n","-u","brops-recorder","/opt/brops-live/bin/governed_recorder"]`). The launcher's
        /// §2.7 step-1 invoker gate requires the REAL uid to be the recorder principal, so the broker cannot
        /// spawn the setuid launcher directly — it delegates to the recorder identity here.
        pub recorder_command: Vec<String>,
        /// Directory of the named fd 3/4/5 store inputs (`system`/`history`/`generation_config`) the recorder
        /// opens for the executor.
        pub recorder_store_dir: String,
        /// The TCB-owned setuid (4750) launcher the recorder `execve`s.
        pub launcher_path: String,
        /// The pinned executor image the launcher `fexecve`s.
        pub executor_path: String,
        /// The launcher's §4.3 `key=value` lease FILE (recorder/executor uid/gid + executor image digest).
        pub lease_file: String,
        /// The launcher's third argv token (cgroup path).
        pub cgroup_arg: String,
        /// The content-addressed protected store the isolated signer reads (`<store_dir>/<sha256hex>`).
        pub store_dir: String,
        /// A world-writable staging dir for the recorder's `--out` report (owned by the recorder uid, read by
        /// the broker uid). Trust for the bytes is the isolated-signer envelope, not this path.
        pub report_dir: String,
        /// The supervisor lifecycle socket (the broker's own uid is SO_PEERCRED-allowlisted).
        pub supervisor_sock: String,
        // ---- the §4.9 evidence facts the RUN produces, reported once via `complete-run` ----
        //
        // F-01: this list used to also carry `receipt_id`, `supervisor_id`, `executor_id`,
        // `builder_id`, `policy_id`, `policy_version` and `policy_bundle_handle`. Those are the
        // identities the isolated signer ALLOWLISTS, so the broker naming them meant the party
        // being constrained chose the values it would be checked against — it simply copied
        // them out of the world-readable deployment config. They now live in the SUPERVISOR's
        // own provisioning and never cross this boundary. What remains here is what only the
        // executing chain can know.
        //
        // The four evidence-head counters used to live here as config constants — every receipt of
        // the deployment named the same head, so the supervisor's anti-rollback floor compared a
        // constant against itself. They now come from the recorder's per-run chain (F-02); the
        // recorder writes it to `--evidence-out` and the broker reads it below.
        pub evidence_state_dir: String,
    }

    /// The REAL privileged execution (§6/§2.7): it delegates the recorder → setuid launcher → executor spawn
    /// to the recorder identity, content-addresses the executor's exact output into the signer's protected
    /// store, then drives the supervisor `attest-run` to obtain the `brops.run-attestation.v1` over the run
    /// evidence. It returns the output bytes + the `sign-request` the isolated signer strict-validates + the
    /// EXACT attested evidence JCS + the supervisor's detached signature. Fail-closed on ANY launcher/executor
    /// refusal, missing output, or supervisor refusal — it never fabricates output or an attestation.
    pub struct LinuxGovernedExecution {
        config: ExecutionConfig,
    }

    impl LinuxGovernedExecution {
        pub fn new(config: ExecutionConfig) -> Self {
            LinuxGovernedExecution { config }
        }

        fn now_ms() -> i64 {
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map(|d| d.as_millis() as i64)
                .unwrap_or(0)
        }

        /// One framed request→reply roundtrip to the supervisor over a fresh AF_UNIX connection,
        /// for any of the §5 lifecycle ops. A lost/refusing hop is a closed reason — the broker
        /// never proceeds on an op the supervisor did not accept.
        fn supervisor_op(&self, req: &Value) -> Result<Value, TurnReason> {
            let bytes = serde_json::to_vec(req).map_err(|_| TurnReason::UpstreamBlocked)?;
            let frame = encode_frame(&bytes).map_err(|_| TurnReason::UpstreamBlocked)?;
            let mut stream =
                UnixStream::connect(&self.config.supervisor_sock).map_err(|_| TurnReason::UpstreamBlocked)?;
            stream.write_all(&frame).map_err(|_| TurnReason::UpstreamBlocked)?;
            stream.flush().map_err(|_| TurnReason::UpstreamBlocked)?;
            let reply = read_one_reply(&mut stream)?;
            let value: Value = serde_json::from_slice(&reply).map_err(|_| TurnReason::UpstreamBlocked)?;
            if !value.get("ok").and_then(Value::as_bool).unwrap_or(false) {
                return Err(TurnReason::UpstreamBlocked);
            }
            Ok(value)
        }
    }

    impl GovernedExecution for LinuxGovernedExecution {
        fn execute(&self, plan: &ExecutionPlan) -> Result<ExecutionArtifacts, TurnReason> {
            let cfg = &self.config;
            let r = plan.resolved;

            // (1) Privileged execution — the recorder (its own UID) prepares FDs 0–6 and `execve`s the setuid
            //     launcher, which drops privilege and `fexecve`s the pinned executor. The executor writes its
            //     exact reply bytes to fd 6; the recorder captures them to `--out`. A non-zero exit or empty
            //     capture is a launcher/executor REFUSAL ⇒ fail closed (never a fabricated output).
            if cfg.recorder_command.is_empty() {
                return Err(TurnReason::UpstreamBlocked);
            }

            // (0) IDX-4 — before spawning anything, require that the digests THIS turn will attest are the
            //     digests the lease pins, i.e. the bytes the launcher will let the executor read. This was
            //     asserted once at provisioning time by a shell heredoc and never again; a lease and a
            //     config that drifted apart afterwards produced a receipt naming a request that was never
            //     executed. The launcher performs the same comparison against a root-owned source the
            //     broker cannot redirect — see the module note above for why this half is not the wall.
            let lease_body = std::fs::read_to_string(&cfg.lease_file)
                .map_err(|_| TurnReason::UpstreamBlocked)?;
            verify_resolved_matches_lease(r, &lease_body)?;
            let report_path = format!(
                "{}/live-{}-{}.out",
                cfg.report_dir, plan.broker_turn_id, plan.lease.execution_attempt_id
            );
            let containment_path = format!("{report_path}.containment.json");
            // (audit F-01, second finding) The evidence chain is written into the RECORDER's own
            // state directory, named by the attempt id, because that is where the supervisor reads
            // it from. The broker cannot write there — which is precisely why the supervisor can
            // believe what it finds. It is also why the broker does not clear a stale file here: it
            // has no business touching the recorder's evidence, and a stale chain is caught by the
            // supervisor's own output-digest check rather than by the broker's good manners.
            let evidence_path = format!(
                "{}/{}.evidence.json",
                cfg.evidence_state_dir, plan.lease.execution_attempt_id
            );
            let _ = std::fs::remove_file(&report_path);
            let _ = std::fs::remove_file(&containment_path);
            let mut command = Command::new(&cfg.recorder_command[0]);
            #[cfg(windows)]
            {
                use std::os::windows::process::CommandExt;
                command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW — no console flash on spawn
            }
            command.args(&cfg.recorder_command[1..]);
            command.args([
                "--store",
                cfg.recorder_store_dir.as_str(),
                "--launcher",
                cfg.launcher_path.as_str(),
                "--executor",
                cfg.executor_path.as_str(),
                "--lease",
                cfg.lease_file.as_str(),
                "--cgroup",
                cfg.cgroup_arg.as_str(),
                "--out",
                report_path.as_str(),
                // F-02: the recorder writes the containment evidence for THIS run here; the broker
                // content-addresses it below. It used to be a provisioner stub whose handle every
                // receipt of the deployment named.
                "--containment-out",
                containment_path.as_str(),
                // F-02: the recorder builds the per-run evidence chain here, and advances its own
                // durable head-sequence counter in `--evidence-state`. The four evidence values the
                // supervisor's terminal record carries come from THIS file, not from config.
                "--evidence-out",
                evidence_path.as_str(),
                "--evidence-state",
                cfg.evidence_state_dir.as_str(),
            ]);
            // Spawn (not `status()`) so the child's real pid can be reported to the supervisor
            // BEFORE we block on it: the §5 state machine flips EXECUTION_STARTING → EXECUTING
            // only on confirmed-running process metadata, and the supervisor durably records it.
            let mut child = command.spawn().map_err(|_| TurnReason::UpstreamBlocked)?;
            let pid = child.id();
            let started = self.supervisor_op(&json!({
                "op": "execution-started",
                "execution_attempt_id": plan.lease.execution_attempt_id,
                "process_group_id": pid.to_string(),
                "cgroup_id": cfg.cgroup_arg,
                "execution_started_marker": Value::Null,
            }));
            if started.is_err() {
                // The supervisor refused to record this start (wrong state, unknown attempt).
                // Do not let an unrecorded execution run to completion behind its back.
                let _ = child.kill();
                let _ = child.wait();
                return Err(TurnReason::UpstreamBlocked);
            }
            let status = child.wait().map_err(|_| TurnReason::UpstreamBlocked)?;
            if !status.success() {
                return Err(TurnReason::UpstreamBlocked);
            }
            let output = std::fs::read(&report_path).map_err(|_| TurnReason::UpstreamBlocked)?;
            if output.is_empty() {
                return Err(TurnReason::UpstreamBlocked);
            }

            // (2) Content-address the exact output into the signer's protected store (`<store>/<sha256hex>`),
            //     so the isolated signer RE-DERIVES output_sha256/output_bytes from the bytes THIS run
            //     produced — never a caller-supplied hash.
            let output_handle = sha256_hex(&output);
            let output_blob = format!("{}/{}", cfg.store_dir, output_handle);
            std::fs::write(&output_blob, &output).map_err(|_| TurnReason::UpstreamBlocked)?;
            // The isolated signer (a DIFFERENT uid) reads this blob by handle; make it group/other-readable
            // regardless of the broker's umask. Integrity is the content address, not the mode.
            {
                use std::os::unix::fs::PermissionsExt;
                let _ = std::fs::set_permissions(&output_blob, std::fs::Permissions::from_mode(0o644));
            }

            // (2b) F-02: content-address the recorder's CONTAINMENT REPORT for this run. Its absence
            //      is a refusal, not a fallback — a turn whose containment cannot be evidenced must
            //      not be attested, and the isolated signer's §1.5 containment gate would otherwise
            //      be satisfied by a constant the provisioner wrote once.
            let containment =
                std::fs::read(&containment_path).map_err(|_| TurnReason::UpstreamBlocked)?;
            if containment.is_empty() {
                return Err(TurnReason::UpstreamBlocked);
            }
            let containment_handle = sha256_hex(&containment);
            let containment_blob = format!("{}/{}", cfg.store_dir, containment_handle);
            std::fs::write(&containment_blob, &containment)
                .map_err(|_| TurnReason::UpstreamBlocked)?;
            {
                use std::os::unix::fs::PermissionsExt;
                let _ = std::fs::set_permissions(
                    &containment_blob,
                    std::fs::Permissions::from_mode(0o644),
                );
            }

            // (3) `complete-run` — report ONLY what this run actually produced, once. Every id,
            //     nonce, identity and acceptance timestamp is deliberately absent: the supervisor
            //     already holds those from the signed challenge it accepted, and taking them here
            //     would re-open the F-01 oracle through a different door. The supervisor's
            //     write-once completion row + evidence-head floor decide whether this is
            //     recordable at all; a refusal means no attestation exists to ask for.
            let now = Self::now_ms();
            let complete = json!({
                "op": "complete-run",
                "execution_attempt_id": plan.lease.execution_attempt_id,
                "produced": {
                    "output_handle": output_handle,
                    "containment_evidence_handle": containment_handle,
                    // F-02: `record_handle`, `lease_handle` and `execution_receipt_handle` are
                    // gone from here. The supervisor BUILDS those documents from its own
                    // acceptance + completion rows and publishes them to the protected store, so
                    // the handles the receipt names address artifacts of THIS run instead of
                    // deployment constants the broker copied out of a world-readable config.
                    "completed_at_ms": now,
                    // F-01: the four evidence values are GONE from the wire. The supervisor reads
                    // the recorder's chain ITSELF and derives them, and refuses this completion if
                    // `output_handle` is not the digest the recorder captured — so naming the
                    // output no longer names what gets attested.
                },
            });
            self.supervisor_op(&complete)?;

            // (4) `attest-run` — NAMES the run, never describes it. The supervisor builds the §4.9
            //     evidence from its OWN durable terminal state, stamps `decision=completed`, and
            //     Ed25519-signs those bytes. We carry the EXACT signed bytes + detached signature
            //     through so the final acceptance can re-hash and re-verify them.
            let attn = self.supervisor_op(&json!({
                "op": "attest-run",
                "run_id": r.run_id,
                "execution_attempt_id": plan.lease.execution_attempt_id,
            }))?;
            let attestation = attn.get("attestation").cloned().ok_or(TurnReason::UpstreamBlocked)?;
            let evidence_jcs_b64 = attn
                .get("evidence_jcs_b64")
                .and_then(Value::as_str)
                .ok_or(TurnReason::UpstreamBlocked)?;
            let attestation_evidence_jcs = URL_SAFE_NO_PAD
                .decode(evidence_jcs_b64.as_bytes())
                .map_err(|_| TurnReason::UpstreamBlocked)?;
            let attestation_signature_b64 = attestation
                .get("sig")
                .and_then(Value::as_str)
                .ok_or(TurnReason::UpstreamBlocked)?
                .to_string();

            // (5) The signer's `evidence` is PARSED FROM the exact bytes the supervisor attested,
            //     not rebuilt by us. The broker therefore cannot present the signer a different
            //     object than the one that was signed — the signer's re-hash and the final
            //     acceptance's `attestation_evidence_sha256` check are over identical bytes by
            //     construction. The signer then re-derives every store digest and signs its OWN
            //     recomputed 23-key envelope.
            let evidence: Value = serde_json::from_slice(&attestation_evidence_jcs)
                .map_err(|_| TurnReason::UpstreamBlocked)?;
            if !evidence.is_object() {
                return Err(TurnReason::UpstreamBlocked);
            }
            let sign_request = json!({
                "protocol": "brops.sign-request.v1",
                "attestation": attestation,
                "evidence": evidence,
            });

            Ok(ExecutionArtifacts {
                output,
                sign_request,
                attestation_evidence_jcs,
                attestation_signature_b64,
            })
        }
    }

    /// The production Linux sub-chain: the pure [`GovernedChain`] wired to the real AF_UNIX socket connector,
    /// the REAL privileged [`LinuxGovernedExecution`], and the broker's injected resolver/ledger. Every hop +
    /// the final `verify_and_accept` are the real code; only a genuinely-verified chain yields an
    /// [`AcceptedOutput`], any refusal/loss/mismatch a closed [`TurnReason`].
    pub struct LinuxGovernedTurnChain<R: TurnResolver, L: AcceptanceLedger> {
        inner: GovernedChain<LinuxHopConnector, R, LinuxGovernedExecution, L>,
    }

    impl<R: TurnResolver, L: AcceptanceLedger> LinuxGovernedTurnChain<R, L> {
        pub fn new(
            sockets: ChainSockets,
            resolver: R,
            execution: LinuxGovernedExecution,
            ledger: L,
        ) -> Self {
            LinuxGovernedTurnChain {
                inner: GovernedChain::new(LinuxHopConnector { sockets }, resolver, execution, ledger),
            }
        }
    }

    impl<R: TurnResolver, L: AcceptanceLedger> GovernedTurnChain for LinuxGovernedTurnChain<R, L> {
        fn run_verified(
            &self,
            req: &ValidatedRequest,
            broker_turn_id: &str,
            request_nonce: &str,
        ) -> Result<AcceptedOutput, TurnReason> {
            self.inner.run_verified(req, broker_turn_id, request_nonce)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;
    use std::collections::{HashMap, VecDeque};
    use std::rc::Rc;

    use base64::engine::general_purpose::URL_SAFE_NO_PAD;
    use base64::Engine as _;
    use ed25519_dalek::{Signer as _, SigningKey};
    use serde_json::{Map, Number};

    use brops_core::broker_orchestrator::{run_governed_turn, BrokerIds};
    use brops_core::broker_turns;
    use brops_core::governed_message_store::{create_schema as create_msg_schema, sha256_hex};
    use brops_core::governed_turn_ipc::{REQUEST_PROTOCOL, TRUSTED_VERIFIED};
    use brops_core::governed_verification::{InMemoryLedger, RECEIPT_ENVELOPE_ARTIFACT_TYPE};
    use brops_core::ipc_framing::{decode_one, encode_frame};
    use brops_core::receipt::request_envelope_sha256;
    use rusqlite::Connection;

    const CRID: &str = "3f2504e0-4f89-41d3-9a0c-0305e82c3301";
    const NONCE: &str = "nonce-1";
    const OUTPUT: &[u8] = b"the exact governed reply bytes";
    const EVIDENCE: &[u8] = br#"{"protocol":"brops.run-attestation.v1","x":1}"#;
    const H64: &str = "1111111111111111111111111111111111111111111111111111111111111111";
    const ISO_KEY_ID: &str = "iso-signer-1";
    const SUP_KEY_ID: &str = "sup-att-1";

    struct FixedIds;
    impl BrokerIds for FixedIds {
        fn new_broker_turn_id(&self) -> String {
            "bt-1".into()
        }
        fn new_request_nonce(&self) -> String {
            NONCE.into()
        }
    }

    // ---- retained composition tests: ChainExecutor relays exactly what a GovernedTurnChain returned ----

    struct FakeChain {
        body: String,
    }
    impl GovernedTurnChain for FakeChain {
        fn run_verified(&self, req: &ValidatedRequest, bt: &str, _n: &str) -> Result<AcceptedOutput, TurnReason> {
            Ok(AcceptedOutput {
                broker_turn_id: bt.to_string(),
                message_id: format!("m-{bt}"),
                conversation_id: req.conversation_id.clone(),
                author: "Bro".into(),
                accepted_body: self.body.clone(),
                envelope_body_sha256: sha256_hex(self.body.as_bytes()),
                created_at_ms: 100,
            })
        }
    }
    struct RefusingChain;
    impl GovernedTurnChain for RefusingChain {
        fn run_verified(&self, _r: &ValidatedRequest, _b: &str, _n: &str) -> Result<AcceptedOutput, TurnReason> {
            Err(TurnReason::UpstreamBlocked)
        }
    }

    fn conn() -> Connection {
        let c = Connection::open_in_memory().unwrap();
        broker_turns::create_schema(&c).unwrap();
        create_msg_schema(&c).unwrap();
        c
    }
    fn raw() -> String {
        format!(
            r#"{{"protocol":"{REQUEST_PROTOCOL}","conversation_id":"conv-1","agent":"a","client_request_id":"{CRID}"}}"#
        )
    }

    #[test]
    fn chain_executor_relays_a_verified_chain_result() {
        let c = conn();
        let exec = ChainExecutor::new(FakeChain { body: "the governed reply".into() });
        let r = run_governed_turn(&c, &raw(), &FixedIds, &exec, 1);
        assert_eq!(r.status, "committed");
        let m = r.message.unwrap();
        assert_eq!(m.body, "the governed reply");
        assert_eq!(m.trust_state, TRUSTED_VERIFIED);
        assert_eq!(r.broker_turn_id, "bt-1");
    }

    #[test]
    fn chain_executor_relays_a_refusal_without_a_message() {
        let c = conn();
        let exec = ChainExecutor::new(RefusingChain);
        let r = run_governed_turn(&c, &raw(), &FixedIds, &exec, 1);
        assert_eq!(r.status, "blocked");
        assert_eq!(r.reason, Some(TurnReason::UpstreamBlocked));
        assert!(r.message.is_none());
    }

    // =============================================================================================
    // Orchestration tests — inject fake hops + fake execution and drive the REAL verify_and_accept.
    // =============================================================================================

    fn signing_key(seed: u8) -> SigningKey {
        SigningKey::from_bytes(&[seed; 32])
    }
    fn sign_b64(k: &SigningKey, msg: &[u8]) -> String {
        URL_SAFE_NO_PAD.encode(k.sign(msg).to_bytes())
    }
    fn hx(n: u8) -> String {
        (0..32).map(|_| format!("{n:02x}")).collect()
    }

    fn expected_request_sha256() -> String {
        request_envelope_sha256(
            "ws-1",
            "install-1",
            NONCE,
            &hx(0x55),
            &hx(0x66),
            &hx(0x44),
            "1000",
        )
    }

    /// Build the flat 23-key envelope payload the isolated signer would return, matching the fixture's
    /// Expected + output + attestation, and sign its JCS with the isolated-signer key. `to_vec` of a sorted
    /// `Map` is byte-identical to `ReceiptEnvelope::payload_jcs`, so the signature verifies in the broker.
    fn signed_payload(out_bytes: u64, out_sha: &str) -> (Value, String) {
        let mut m = Map::new();
        let strings = [
            ("artifact_type", RECEIPT_ENVELOPE_ARTIFACT_TYPE),
            ("key_id", ISO_KEY_ID),
            ("receipt_id", "receipt-abc"),
            ("run_id", "run-1"),
            ("execution_attempt_id", "att-1"),
            ("task_id", "task-1"),
            ("workspace_id", "ws-1"),
            ("install_id", "install-1"),
            ("request_nonce", NONCE),
            ("record_handle", H64),
            ("lease_handle", H64),
            ("execution_receipt_handle", H64),
            ("evidence_final_event_hash", H64),
            ("supervisor_attestation_key_id", SUP_KEY_ID),
        ];
        for (k, v) in strings {
            m.insert(k.to_string(), Value::String(v.to_string()));
        }
        m.insert("request_sha256".to_string(), Value::String(expected_request_sha256()));
        m.insert("output_sha256".to_string(), Value::String(out_sha.to_string()));
        m.insert(
            "attestation_evidence_sha256".to_string(),
            Value::String(sha256_hex(EVIDENCE)),
        );
        let ints: [(&str, u64); 6] = [
            ("output_bytes", out_bytes),
            ("challenge_accepted_at_ms", 1000),
            ("completed_at_ms", 2000),
            ("evidence_event_count", 3),
            ("evidence_last_sequence", 12),
            ("evidence_head_sequence", 12),
        ];
        for (k, v) in ints {
            m.insert(k.to_string(), Value::Number(Number::from(v)));
        }
        let payload = Value::Object(m);
        let jcs = serde_json::to_vec(&payload).unwrap();
        let env_sig = sign_b64(&signing_key(7), &jcs);
        (payload, env_sig)
    }

    // ---- fake connector: canned framed replies per principal, in call order; records sent requests ----

    struct FakeConn {
        principal: Principal,
        reply: Vec<u8>,
        sent: Rc<RefCell<Vec<(Principal, Value)>>>,
    }
    impl HopConn for FakeConn {
        fn send_all(&mut self, frame: &[u8]) -> Result<(), HopError> {
            let payload = decode_one(frame).map_err(HopError::Frame)?;
            let v: Value = serde_json::from_slice(payload).map_err(|_| HopError::BadReply)?;
            self.sent.borrow_mut().push((self.principal, v));
            Ok(())
        }
        fn recv_all(&mut self) -> Result<Vec<u8>, HopError> {
            encode_frame(&self.reply).map_err(HopError::Frame)
        }
    }

    struct FakeConnector {
        replies: RefCell<HashMap<Principal, VecDeque<Vec<u8>>>>,
        sent: Rc<RefCell<Vec<(Principal, Value)>>>,
    }
    impl FakeConnector {
        fn new() -> Self {
            FakeConnector {
                replies: RefCell::new(HashMap::new()),
                sent: Rc::new(RefCell::new(Vec::new())),
            }
        }
        fn push(&self, principal: Principal, reply: Value) {
            self.replies
                .borrow_mut()
                .entry(principal)
                .or_default()
                .push_back(serde_json::to_vec(&reply).unwrap());
        }
    }
    impl HopConnector for FakeConnector {
        fn connect(&self, principal: Principal) -> Result<Box<dyn HopConn>, HopError> {
            let reply = self
                .replies
                .borrow_mut()
                .get_mut(&principal)
                .and_then(VecDeque::pop_front)
                .ok_or(HopError::Unavailable)?;
            Ok(Box::new(FakeConn {
                principal,
                reply,
                sent: self.sent.clone(),
            }))
        }
    }

    // ---- fake resolver: the broker's OWN pinned keys + Expected, matching the fixture ----

    struct FakeResolver;
    impl TurnResolver for FakeResolver {
        fn resolve(&self, _req: &ValidatedRequest, _bt: &str, _n: &str) -> Result<ResolvedTurn, TurnReason> {
            Ok(ResolvedTurn {
                isolated_signer_key_id: ISO_KEY_ID.into(),
                isolated_signer_public_key: signing_key(7).verifying_key().to_bytes(),
                supervisor_attestation_key_id: SUP_KEY_ID.into(),
                supervisor_attestation_public_key: signing_key(9).verifying_key().to_bytes(),
                workspace_id: "ws-1".into(),
                install_id: "install-1".into(),
                system_sha256: hx(0x55),
                history_sha256: hx(0x66),
                generation_config_sha256: hx(0x44),
                requested_at: "1000".into(),
                run_id: "run-1".into(),
                task_id: "task-1".into(),
                requested_at_ms: 1000,
                author: "Bro".into(),
            })
        }
    }

    // ---- fake execution: real output + supervisor attestation; optionally tampers the output ----

    struct FakeExecution {
        tamper: bool,
    }
    impl GovernedExecution for FakeExecution {
        fn execute(&self, plan: &ExecutionPlan) -> Result<ExecutionArtifacts, TurnReason> {
            // A faithful execution acts only on the lease it was actually granted + the broker-minted ids
            // (never fabricating them); asserting here proves the orchestration threads them through.
            assert_eq!(plan.lease.lease_id, "L1");
            assert_eq!(plan.lease.execution_attempt_id, "att-1");
            // The real execution verifies the pinned launcher/executor hashes + budget before it spawns.
            assert_eq!(plan.lease.launcher_executable_sha256, H64);
            assert_eq!(plan.lease.executor_executable_sha256, H64);
            assert_eq!(plan.lease.lease_expires_at_ms, 999_999);
            assert_eq!(plan.request_nonce, NONCE);
            assert_eq!(plan.resolved.workspace_id, "ws-1");
            assert_eq!(plan.req.conversation_id, "conv-1");
            assert_eq!(plan.broker_turn_id, "bt-1");
            let mut output = OUTPUT.to_vec();
            if self.tamper {
                output[0] ^= 0x01; // same length, different bytes ⇒ digest gate fails downstream
            }
            Ok(ExecutionArtifacts {
                output,
                sign_request: json!({
                    "protocol": "brops.sign-request.v1",
                    "attestation": {"attestation_protocol": "brops.run-attestation.v1",
                                    "supervisor_key_id": SUP_KEY_ID, "sig": sign_b64(&signing_key(9), EVIDENCE)},
                    "evidence": {"run_id": "run-1"}
                }),
                attestation_evidence_jcs: EVIDENCE.to_vec(),
                attestation_signature_b64: sign_b64(&signing_key(9), EVIDENCE),
            })
        }
    }

    fn lease_obj() -> Value {
        json!({
            "lease_id": "L1",
            "execution_attempt_id": "att-1",
            "lease_expires_at_ms": 999_999,
            "launcher_executable_sha256": H64,
            "executor_executable_sha256": H64,
        })
    }

    /// A connector primed for a full happy path (create-pending → issue → accept-open → launch-gate →
    /// sign-result). The signer payload binds the given output.
    fn happy_connector() -> FakeConnector {
        let c = FakeConnector::new();
        c.push(
            Principal::ChallengeAuthority,
            json!({"ok": true, "op": "create-pending", "pending_challenge_id": "pc-1", "pending_expires_at_ms": 123}),
        );
        c.push(
            Principal::ChallengeAuthority,
            json!({"ok": true, "op": "issue", "challenge": {"protocol": "brops.governed-turn-challenge.v1", "x": 1}}),
        );
        c.push(
            Principal::Supervisor,
            json!({"ok": true, "op": "accept-open", "lease": lease_obj()}),
        );
        c.push(
            Principal::Supervisor,
            json!({"ok": true, "op": "launch-gate", "proceed": true, "lease": lease_obj()}),
        );
        let (payload, sig) = signed_payload(OUTPUT.len() as u64, &sha256_hex(OUTPUT));
        c.push(
            Principal::IsolatedSigner,
            json!({"ok": true, "op": "sign-result", "artifact_type": RECEIPT_ENVELOPE_ARTIFACT_TYPE,
                   "payload": payload, "signature": sig}),
        );
        c
    }

    fn chain(
        connector: FakeConnector,
        tamper: bool,
    ) -> GovernedChain<FakeConnector, FakeResolver, FakeExecution, InMemoryLedger> {
        GovernedChain::new(connector, FakeResolver, FakeExecution { tamper }, InMemoryLedger::new())
    }

    #[test]
    fn happy_path_produces_a_committed_trusted_verified_message() {
        let c = conn();
        let exec = ChainExecutor::new(chain(happy_connector(), false));
        let r = run_governed_turn(&c, &raw(), &FixedIds, &exec, 1);
        assert_eq!(r.status, "committed", "reason={:?}", r.reason);
        let m = r.message.expect("committed message present");
        assert_eq!(m.body.as_bytes(), OUTPUT);
        assert_eq!(m.trust_state, TRUSTED_VERIFIED);
        assert_eq!(m.created_at_ms, 2000); // envelope completed_at_ms
        assert_eq!(r.broker_turn_id, "bt-1");
    }

    #[test]
    fn happy_path_run_verified_returns_the_exact_verified_output() {
        // Drive the sub-chain directly and assert the AcceptedOutput is bound to the signed envelope.
        let ch = chain(happy_connector(), false);
        let req = ValidatedRequest::decode(&raw()).unwrap();
        let accepted = ch.run_verified(&req, "bt-1", NONCE).expect("verified acceptance");
        assert_eq!(accepted.accepted_body.as_bytes(), OUTPUT);
        assert_eq!(accepted.envelope_body_sha256, sha256_hex(OUTPUT));
        assert_eq!(accepted.message_id, "m-bt-1");
        assert_eq!(accepted.conversation_id, "conv-1");
        assert_eq!(accepted.author, "Bro");
    }

    #[test]
    fn hops_are_sequenced_and_chained_in_order() {
        let connector = happy_connector();
        // Capture the shared sent-log before the connector is moved into the chain.
        let sent = connector.sent.clone();
        let ch = chain(connector, false);
        let req = ValidatedRequest::decode(&raw()).unwrap();
        ch.run_verified(&req, "bt-1", NONCE).unwrap();

        let sent = sent.borrow();
        let ops: Vec<(Principal, String)> = sent
            .iter()
            .map(|(p, v)| (*p, v.get("op").and_then(Value::as_str).unwrap_or("").to_string()))
            .collect();
        assert_eq!(
            ops,
            vec![
                (Principal::ChallengeAuthority, "create-pending".into()),
                (Principal::ChallengeAuthority, "issue".into()),
                (Principal::Supervisor, "accept-open".into()),
                (Principal::Supervisor, "launch-gate".into()),
                (Principal::IsolatedSigner, "sign-result".into()),
            ]
        );
        // Data threads between hops: issue carries the create-pending id; accept-open carries the issued
        // challenge doc; launch-gate names ONLY the granted attempt.
        assert_eq!(sent[1].1.get("pending_challenge_id").and_then(Value::as_str), Some("pc-1"));
        assert!(sent[2].1.get("challenge_doc").is_some());
        assert_eq!(
            sent[3].1.get("execution_attempt_id").and_then(Value::as_str),
            Some("att-1")
        );
        // F-01/F-23: the broker no longer hands the lease back for the supervisor to judge
        // itself against. If this assertion ever fails, the party being gated has regained
        // the ability to choose the expiry it is checked against.
        assert!(
            sent[3].1.get("lease").is_none(),
            "launch-gate must not carry a caller-supplied lease"
        );
    }

    #[test]
    fn a_refusing_authority_blocks_with_no_message() {
        let c = FakeConnector::new();
        c.push(
            Principal::ChallengeAuthority,
            json!({"ok": false, "op": "create-pending", "reason": "retry_conflict", "error": "x"}),
        );
        let db = conn();
        let exec = ChainExecutor::new(chain(c, false));
        let r = run_governed_turn(&db, &raw(), &FixedIds, &exec, 1);
        assert_eq!(r.status, "blocked");
        assert_eq!(r.reason, Some(TurnReason::UpstreamBlocked));
        assert!(r.message.is_none());
    }

    #[test]
    fn a_refusing_supervisor_blocks_with_no_message() {
        let c = FakeConnector::new();
        c.push(
            Principal::ChallengeAuthority,
            json!({"ok": true, "op": "create-pending", "pending_challenge_id": "pc-1", "pending_expires_at_ms": 123}),
        );
        c.push(
            Principal::ChallengeAuthority,
            json!({"ok": true, "op": "issue", "challenge": {"protocol": "brops.governed-turn-challenge.v1"}}),
        );
        c.push(
            Principal::Supervisor,
            json!({"ok": false, "op": "accept-open", "reason": "challenge_expired", "error": "x"}),
        );
        let db = conn();
        let exec = ChainExecutor::new(chain(c, false));
        let r = run_governed_turn(&db, &raw(), &FixedIds, &exec, 1);
        assert_eq!(r.status, "blocked");
        assert_eq!(r.reason, Some(TurnReason::UpstreamBlocked));
        assert!(r.message.is_none());
    }

    #[test]
    fn a_signer_refusal_blocks_with_no_message() {
        let c = happy_connector();
        // Replace the sign-result reply with a typed refusal.
        c.replies.borrow_mut().get_mut(&Principal::IsolatedSigner).unwrap().clear();
        c.push(
            Principal::IsolatedSigner,
            json!({"ok": false, "op": "sign-result", "reason": "attestation_invalid",
                   "artifact_type": "brops.governed-receipt-refusal.v1", "error": "refused"}),
        );
        let db = conn();
        let exec = ChainExecutor::new(chain(c, false));
        let r = run_governed_turn(&db, &raw(), &FixedIds, &exec, 1);
        assert_eq!(r.status, "blocked");
        assert_eq!(r.reason, Some(TurnReason::UpstreamBlocked));
        assert!(r.message.is_none());
    }

    #[test]
    fn a_tampered_output_fails_verification_and_blocks() {
        // The signer bound the REAL output digest; execution returns a byte-flipped output ⇒ the broker's
        // output digest gate fails ⇒ CommitReadbackMismatch, never a fabricated acceptance.
        let db = conn();
        let exec = ChainExecutor::new(chain(happy_connector(), true));
        let r = run_governed_turn(&db, &raw(), &FixedIds, &exec, 1);
        assert_eq!(r.status, "blocked");
        assert_eq!(r.reason, Some(TurnReason::CommitReadbackMismatch));
        assert!(r.message.is_none());
    }

    // =============================================================================================
    // IDX-4 (broker-side half): the digests this turn will ATTEST must equal the lease's request pins.
    // =============================================================================================

    fn resolved_fixture() -> ResolvedTurn {
        FakeResolver
            .resolve(
                &ValidatedRequest {
                    conversation_id: "conv-1".into(),
                    agent: Some("a".into()),
                    client_request_id: CRID.into(),
                },
                "bt-1",
                NONCE,
            )
            .expect("the fake resolver resolves")
    }

    /// A §4.3 lease body carrying the three request pins, in the exact `key=value` shape the launcher
    /// parses (uids and the image pin included, so the scanner has to ignore what is not its business).
    fn lease_body(system: &str, history: &str, generation_config: &str) -> String {
        format!(
            "recorder_uid=5005\nrecorder_gid=5005\nexecutor_uid=5007\nexecutor_gid=5007\n\
             executor_executable_sha256={}\nsystem_sha256={system}\nhistory_sha256={history}\n\
             generation_config_sha256={generation_config}\n",
            hx(0xab)
        )
    }

    #[test]
    fn a_lease_pinning_exactly_the_resolved_digests_is_accepted() {
        let r = resolved_fixture();
        let body = lease_body(&hx(0x55), &hx(0x66), &hx(0x44));
        assert_eq!(verify_resolved_matches_lease(&r, &body), Ok(()));
    }

    #[test]
    fn a_lease_pinning_bytes_this_turn_will_not_attest_blocks_the_execution() {
        // IDX-4 itself: the receipt's request binding would name bytes the executor never ran. One slot at
        // a time, because a check that stopped at the first comparison would let two of these through.
        let r = resolved_fixture();
        let cases = [
            lease_body(&hx(0xff), &hx(0x66), &hx(0x44)),
            lease_body(&hx(0x55), &hx(0xff), &hx(0x44)),
            lease_body(&hx(0x55), &hx(0x66), &hx(0xff)),
        ];
        for body in cases {
            assert_eq!(
                verify_resolved_matches_lease(&r, &body),
                Err(TurnReason::UpstreamBlocked)
            );
        }
        // A transposition: every digest is one this turn resolves, but on the wrong descriptor.
        assert_eq!(
            verify_resolved_matches_lease(&r, &lease_body(&hx(0x66), &hx(0x55), &hx(0x44))),
            Err(TurnReason::UpstreamBlocked)
        );
    }

    #[test]
    fn a_lease_that_does_not_pin_the_request_at_all_blocks_the_execution() {
        // "Unpinned" must not read as "nothing to compare, carry on".
        let r = resolved_fixture();
        for key in ["system_sha256", "history_sha256", "generation_config_sha256"] {
            let without: String = lease_body(&hx(0x55), &hx(0x66), &hx(0x44))
                .lines()
                .filter(|l| !l.trim_start().starts_with(key))
                .map(|l| format!("{l}\n"))
                .collect();
            assert_eq!(
                verify_resolved_matches_lease(&r, &without),
                Err(TurnReason::UpstreamBlocked),
                "{key}"
            );
        }
        // A duplicated pin (which of the two would be authoritative?) and a non-canonical digest.
        let dup = format!(
            "{}system_sha256={}\n",
            lease_body(&hx(0x55), &hx(0x66), &hx(0x44)),
            hx(0x55)
        );
        assert_eq!(
            verify_resolved_matches_lease(&r, &dup),
            Err(TurnReason::UpstreamBlocked)
        );
        assert_eq!(
            verify_resolved_matches_lease(&r, &lease_body("beef", &hx(0x66), &hx(0x44))),
            Err(TurnReason::UpstreamBlocked)
        );
        assert_eq!(
            verify_resolved_matches_lease(&r, "not a lease at all"),
            Err(TurnReason::UpstreamBlocked)
        );
    }
}
