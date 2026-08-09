//! Wave 3b-1B (design-GREEN rev-30) — **§5 durable supervisor acceptance: state machine + outbox**.
//!
//! A DB transaction cannot atomically include an external private-key signature and a filesystem
//! publish, so acceptance is a **durable state machine with an outbox**, not a single issue-or-prepare
//! step (rev-30 §5). This module owns the three supervisor-side durable primitives for that:
//!
//! 1. **The acceptance ledger** (`governed_turn_acceptance`) — a create-if-absent CAS row per turn
//!    (three `UNIQUE` constraints: `(install_id,request_nonce)`, `challenge_handle`,
//!    `execution_attempt_id`) whose `state` moves through the CLOSED 9-value enum
//!    (`ACCEPTED_PREPARED → LEASE_READY → EXECUTION_STARTING → EXECUTING → COMPLETED`; terminals
//!    `BLOCKED`, `FAILED`, `EXPIRED`, `RECOVERY_REQUIRED`; `UNSEEN` = absent/no-row, never stored).
//!    Every edge is **transition-checked** in Rust (a `WHERE state IN (<legal predecessors>)` guard)
//!    AND at the DB layer by a `BEFORE UPDATE OF state` trigger that RAISEs on any illegal jump and on
//!    any move out of a terminal state — so there is no illegal jump and no path back to a terminal.
//!
//! 2. **The outbox** (`governed_turn_outbox`) — the durable terminal-record row (create-if-absent,
//!    byte-compared on retry) the supervisor drains to publish the atomic `<run_id>__<attempt>.json`
//!    terminal governed-turn record (§5 outbox / §6 step 4).
//!
//! 3. **The signer-owned durable evidence-head floor CAS** (`governed_evidence_head_floor`, §5
//!    step 11 / §7 P1-7) — in ONE `BEGIN IMMEDIATE` it reads the current floor for `(install_id,
//!    task_id)` and, keyed on the re-anchor counter `head_sequence` (the epoch) + `final_event_hash`
//!    (the chain identity), **refuses a lower head** (`stale_evidence`), **refuses an equal head whose
//!    content differs** (`evidence_fork`), and otherwise **advances + commits** (strictly-higher head)
//!    or is an idempotent no-op (equal head + equal content). The floor is committed before any
//!    envelope would be minted, closing the TOCTOU on the `(install_id,task_id)` PK.
//!
//! **Testable without the OS trust chain:** every fn takes a `&rusqlite::Connection`; every clock is an
//! injected `now_ms: i64`. Tests open `Connection::open_in_memory()` and drive the full lifecycle
//! offline — no clock, socket, signer, or filesystem.

use rusqlite::{params, Connection, OptionalExtension};

use crate::governed_message_store::sha256_hex;

// ---------------------------------------------------------------------------
// §5 step-8a lease-expiry launch-gate budget (pure, host-independent constants).
// ---------------------------------------------------------------------------

/// Minimum remaining lease budget required to launch (§5 step 8a): `EXECUTION_TIMEOUT_MS(120000) +
/// grace(5000) + teardown(10000) + post_exec_signing_reserve(40000) = 175000` worst-case critical path
/// **+ 5000** launch/scheduling slack. Exact-`175000` remaining refuses; exact-`180000` proceeds.
pub const MIN_LAUNCH_REMAINING_MS: i64 = 180_000;

/// Full lease duration (§5 step 4 / §4.7): `~30000 pre-launch + 180000` in-window budget.
pub const LEASE_DURATION_MS: i64 = 210_000;

// ---------------------------------------------------------------------------
// Closed acceptance state enum (§5 — mirrors the SQL CHECK domain exactly).
// ---------------------------------------------------------------------------

/// The CLOSED, DB-`CHECK`-enforced acceptance lifecycle (§5, P1-4). `UNSEEN` (absent/no-row) is NOT a
/// variant here because it is never stored — it is the pre-insert absence the create CAS resolves.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AcceptanceState {
    AcceptedPrepared,
    LeaseReady,
    ExecutionStarting,
    Executing,
    Completed,
    Blocked,
    Failed,
    Expired,
    RecoveryRequired,
}

impl AcceptanceState {
    /// The exact uppercase token persisted in the `state` column (matches the SQL CHECK domain).
    pub fn as_str(self) -> &'static str {
        match self {
            AcceptanceState::AcceptedPrepared => "ACCEPTED_PREPARED",
            AcceptanceState::LeaseReady => "LEASE_READY",
            AcceptanceState::ExecutionStarting => "EXECUTION_STARTING",
            AcceptanceState::Executing => "EXECUTING",
            AcceptanceState::Completed => "COMPLETED",
            AcceptanceState::Blocked => "BLOCKED",
            AcceptanceState::Failed => "FAILED",
            AcceptanceState::Expired => "EXPIRED",
            AcceptanceState::RecoveryRequired => "RECOVERY_REQUIRED",
        }
    }

    /// Parse a stored token back to the enum (used when reading the row back). An unknown token is a
    /// corrupt/foreign DB value and yields `None` (callers map that to [`LedgerError::Corrupt`]).
    pub fn from_str(s: &str) -> Option<Self> {
        Some(match s {
            "ACCEPTED_PREPARED" => AcceptanceState::AcceptedPrepared,
            "LEASE_READY" => AcceptanceState::LeaseReady,
            "EXECUTION_STARTING" => AcceptanceState::ExecutionStarting,
            "EXECUTING" => AcceptanceState::Executing,
            "COMPLETED" => AcceptanceState::Completed,
            "BLOCKED" => AcceptanceState::Blocked,
            "FAILED" => AcceptanceState::Failed,
            "EXPIRED" => AcceptanceState::Expired,
            "RECOVERY_REQUIRED" => AcceptanceState::RecoveryRequired,
            _ => return None,
        })
    }

    /// A terminal state: `COMPLETED`, `BLOCKED`, `FAILED`, `EXPIRED`, `RECOVERY_REQUIRED`. No edge
    /// leaves a terminal state (enforced by the DB trigger AND the per-transition predecessor guard).
    pub fn is_terminal(self) -> bool {
        matches!(
            self,
            AcceptanceState::Completed
                | AcceptanceState::Blocked
                | AcceptanceState::Failed
                | AcceptanceState::Expired
                | AcceptanceState::RecoveryRequired
        )
    }
}

// ---------------------------------------------------------------------------
// Errors (kept local — a DB/ledger fault is infrastructure, not a renderer verdict).
// ---------------------------------------------------------------------------

/// Ledger-layer errors. Deliberately distinct from any renderer-facing protocol verdict.
#[derive(Debug)]
pub enum LedgerError {
    /// An underlying rusqlite / SQLite failure.
    Db(rusqlite::Error),
    /// No acceptance (or floor / outbox) row exists for the given key.
    NotFound,
    /// A requested state transition is not a legal §5 edge from the row's current state (or the row is
    /// already terminal). Carries the observed `from` and the requested `to` tokens.
    IllegalTransition { from: &'static str, to: &'static str },
    /// A CAS / uniqueness conflict: a reused `request_nonce`/`challenge_handle`/`execution_attempt_id`
    /// paired with DIFFERENT bindings, or an outbox row whose bytes differ from an existing one.
    Conflict(&'static str),
    /// A function that must OWN its `BEGIN IMMEDIATE` was called inside an open transaction.
    NestedTransaction,
    /// An input evidence head is malformed (bad hex, non-positive counts, `last_sequence != event_count`).
    InvalidHead(&'static str),
    /// The evidence head presents a strictly LOWER `head_sequence` than the durable floor (§7 case A).
    StaleEvidence,
    /// The evidence head forks the durable floor: equal head with differing content (§7 case B).
    EvidenceFork,
    /// A stored row carried a value outside its closed domain (a corrupt/foreign DB), fail-closed.
    Corrupt(&'static str),
}

impl std::fmt::Display for LedgerError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            LedgerError::Db(e) => write!(f, "supervisor_ledger db error: {e}"),
            LedgerError::NotFound => write!(f, "no acceptance ledger row for the given key"),
            LedgerError::IllegalTransition { from, to } => {
                write!(f, "illegal acceptance transition {from} -> {to}")
            }
            LedgerError::Conflict(w) => write!(f, "acceptance ledger conflict: {w}"),
            LedgerError::NestedTransaction => {
                write!(f, "floor CAS must own its BEGIN IMMEDIATE; called inside an open transaction")
            }
            LedgerError::InvalidHead(w) => write!(f, "invalid evidence head: {w}"),
            LedgerError::StaleEvidence => write!(f, "stale_evidence (head_sequence below durable floor)"),
            LedgerError::EvidenceFork => write!(f, "evidence_fork (head content diverges from floor)"),
            LedgerError::Corrupt(w) => write!(f, "corrupt ledger row: {w}"),
        }
    }
}

impl std::error::Error for LedgerError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            LedgerError::Db(e) => Some(e),
            _ => None,
        }
    }
}

impl From<rusqlite::Error> for LedgerError {
    fn from(e: rusqlite::Error) -> Self {
        LedgerError::Db(e)
    }
}

// ---------------------------------------------------------------------------
// Schema.
// ---------------------------------------------------------------------------

/// The CANONICAL durable-ledger DDL, compiled in from the mirrored copy of
/// `engine/runtime/supervisor_ledger.sql` (the single normative source — see that file's header).
///
/// The mirror is byte-compared against the canonical file by the fail-closed CI gate
/// `tools/check_ledger_ddl_parity.py`, so the Python supervisor (the production writer of this state)
/// and this Rust library can never drift apart on the constraints that ARE the enforcement: the three
/// `UNIQUE`s that make one signed challenge mint exactly one attempt, the `state` CHECK + transition
/// trigger, the completion table's write-once PK, and the evidence-head floor.
pub const SCHEMA_SQL: &str = include_str!("../schema/supervisor_ledger.sql");

/// Create the durable tables + the transition-enforcing trigger (idempotent — `IF NOT EXISTS`).
/// Also enables `PRAGMA foreign_keys` on this connection so the outbox/completion→acceptance FKs are live.
pub fn create_schema(conn: &Connection) -> Result<(), LedgerError> {
    conn.execute_batch(SCHEMA_SQL)?;
    Ok(())
}

// ---------------------------------------------------------------------------
// Acceptance ledger — create (CAS insert absent → ACCEPTED_PREPARED).
// ---------------------------------------------------------------------------

/// The authoritative bindings persisted in the acceptance row at `ACCEPTED_PREPARED` (§5 step 4). Every
/// field is supervisor-derived; none is a raw caller/renderer input.
#[derive(Debug, Clone)]
pub struct NewAcceptance {
    pub install_id: String,
    pub request_nonce: String,
    pub challenge_handle: String,
    pub run_id: String,
    pub task_id: String,
    pub workspace_id: String,
    pub execution_attempt_id: String,
    pub challenge_accepted_at_ms: i64,
    pub challenge_registry_handle: String,
    pub challenge_registry_hash: String,
    pub challenge_registry_epoch: i64,
    pub challenge_registry_root_key_id: String,
    /// The EXACT canonical lease payload bytes to be signed (`JCS(payload)`); hashed to
    /// `lease_payload_sha256` and stored verbatim so a post-commit crash re-signs deterministically.
    pub lease_payload_bytes: Vec<u8>,

    // ---- F-01: the durable request binding the run-attestation is rebuilt from ----
    // `lease_*` are stamped from the supervisor's own clock; `receipt_id` is minted by the
    // supervisor at acceptance (so the §7.1(d) replay key is per-turn, not deployment-static);
    // the remaining five are copied out of the signature-verified challenge payload. Nothing here
    // is ever accepted from a later caller message — that is what makes the attestation mean
    // something the broker could not have chosen.
    pub lease_id: String,
    pub lease_issued_at_ms: i64,
    pub lease_expires_at_ms: i64,
    pub receipt_id: String,
    pub supervisor_id: String,
    pub requested_at_ms: i64,
    pub request_sha256: String,
    pub system_handle: String,
    pub history_handle: String,
    pub generation_config_handle: String,
}

/// Outcome of [`accept_prepare`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AcceptOutcome {
    /// A fresh `ACCEPTED_PREPARED` row was inserted (this caller won the CAS).
    Created,
    /// An identical row already existed for this `(install_id, request_nonce)` — an idempotent
    /// duplicate submission (§5 negative test: concurrent duplicates get exactly one attempt).
    Idempotent,
}

/// CAS insert `absent → ACCEPTED_PREPARED` (§5 step 4). The three `UNIQUE` constraints ARE the CAS:
/// a reused nonce, challenge, or attempt id collides. On collision this loads the existing row and
/// returns [`AcceptOutcome::Idempotent`] iff it is byte-identical in every bound field (a genuine
/// retry of the same accepted turn); any divergence — same nonce/different challenge, same
/// challenge/different nonce, or a conflicting `run_id`/`task_id`/`workspace_id`/attempt/lease — is
/// [`LedgerError::Conflict`] and creates NO second attempt.
pub fn accept_prepare(
    conn: &Connection,
    a: &NewAcceptance,
    now_ms: i64,
) -> Result<AcceptOutcome, LedgerError> {
    let lease_payload_sha256 = sha256_hex(&a.lease_payload_bytes);
    let res = conn.execute(
        "INSERT INTO governed_turn_acceptance (\
            install_id, request_nonce, challenge_handle, run_id, task_id, workspace_id, \
            execution_attempt_id, challenge_accepted_at_ms, challenge_registry_handle, \
            challenge_registry_hash, challenge_registry_epoch, challenge_registry_root_key_id, \
            lease_payload_sha256, lease_payload_bytes, \
            lease_id, lease_issued_at_ms, lease_expires_at_ms, receipt_id, supervisor_id, \
            requested_at_ms, request_sha256, system_handle, history_handle, \
            generation_config_handle, \
            state, created_at_ms, updated_at_ms) \
         VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,\
                 ?15,?16,?17,?18,?19,?20,?21,?22,?23,?24,'ACCEPTED_PREPARED',?25,?25)",
        params![
            a.install_id,
            a.request_nonce,
            a.challenge_handle,
            a.run_id,
            a.task_id,
            a.workspace_id,
            a.execution_attempt_id,
            a.challenge_accepted_at_ms,
            a.challenge_registry_handle,
            a.challenge_registry_hash,
            a.challenge_registry_epoch,
            a.challenge_registry_root_key_id,
            lease_payload_sha256,
            a.lease_payload_bytes,
            a.lease_id,
            a.lease_issued_at_ms,
            a.lease_expires_at_ms,
            a.receipt_id,
            a.supervisor_id,
            a.requested_at_ms,
            a.request_sha256,
            a.system_handle,
            a.history_handle,
            a.generation_config_handle,
            now_ms,
        ],
    );
    match res {
        Ok(_) => Ok(AcceptOutcome::Created),
        Err(e) if is_unique_violation(&e) => {
            // A UNIQUE fired. Decide idempotent-retry vs true conflict by comparing every bound field.
            reconcile_conflict(conn, a, &lease_payload_sha256)
        }
        Err(e) => Err(LedgerError::Db(e)),
    }
}

/// On a UNIQUE collision, load the existing row for this `(install_id, request_nonce)` and decide
/// idempotent-vs-conflict. If no row is found on `(install_id, request_nonce)` the collision was on
/// `challenge_handle` or `execution_attempt_id` reused with a DIFFERENT nonce ⇒ hard conflict.
fn reconcile_conflict(
    conn: &Connection,
    a: &NewAcceptance,
    lease_payload_sha256: &str,
) -> Result<AcceptOutcome, LedgerError> {
    // ONE row read carrying every bound field, compared as a whole. Adding a binding column to the
    // table without adding it here would silently widen what counts as "the same turn", so the
    // comparison is deliberately exhaustive over the durable request binding.
    type BoundRow = (
        String, String, String, String, String, // challenge_handle, run_id, task_id, workspace_id, attempt
        String,                                 // lease_payload_sha256
        String, i64, i64,                       // lease_id, lease_issued_at_ms, lease_expires_at_ms
        String, String,                         // receipt_id, supervisor_id
        i64, String,                            // requested_at_ms, request_sha256
        String, String, String,                 // system/history/generation_config handles
    );
    let existing: Option<BoundRow> = conn
        .query_row(
            "SELECT challenge_handle, run_id, task_id, workspace_id, execution_attempt_id, \
                    lease_payload_sha256, lease_id, lease_issued_at_ms, lease_expires_at_ms, \
                    receipt_id, supervisor_id, requested_at_ms, request_sha256, \
                    system_handle, history_handle, generation_config_handle \
             FROM governed_turn_acceptance WHERE install_id = ?1 AND request_nonce = ?2",
            params![a.install_id, a.request_nonce],
            |r| {
                Ok((
                    r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?,
                    r.get(5)?, r.get(6)?, r.get(7)?, r.get(8)?, r.get(9)?,
                    r.get(10)?, r.get(11)?, r.get(12)?, r.get(13)?, r.get(14)?,
                    r.get(15)?,
                ))
            },
        )
        .optional()?;
    let Some((
        ch, run, task, ws, attempt, lease_sha, lease_id, lease_issued, lease_expires, receipt_id,
        supervisor_id, requested_at, request_sha, system_h, history_h, gencfg_h,
    )) = existing
    else {
        // Nonce is unused but challenge_handle / execution_attempt_id was reused elsewhere.
        return Err(LedgerError::Conflict("challenge_or_attempt_reused"));
    };
    let identical = ch == a.challenge_handle
        && run == a.run_id
        && task == a.task_id
        && ws == a.workspace_id
        && attempt == a.execution_attempt_id
        && lease_sha == lease_payload_sha256
        && lease_id == a.lease_id
        && lease_issued == a.lease_issued_at_ms
        && lease_expires == a.lease_expires_at_ms
        && receipt_id == a.receipt_id
        && supervisor_id == a.supervisor_id
        && requested_at == a.requested_at_ms
        && request_sha == a.request_sha256
        && system_h == a.system_handle
        && history_h == a.history_handle
        && gencfg_h == a.generation_config_handle;
    if identical {
        Ok(AcceptOutcome::Idempotent)
    } else {
        Err(LedgerError::Conflict("nonce_rebound_to_different_turn"))
    }
}

// ---------------------------------------------------------------------------
// Acceptance ledger — advance (transition-checked edges, keyed by execution_attempt_id).
// ---------------------------------------------------------------------------

/// A requested §5 transition, carrying the columns that edge persists. Each variant maps to exactly ONE
/// target state with a fixed set of legal predecessors (the §5 deterministic state-purpose matrix).
#[derive(Debug, Clone)]
pub enum Advance {
    /// `ACCEPTED_PREPARED → LEASE_READY` — the signed lease published + re-verified (§5 step 7).
    LeaseReady { lease_handle: String },
    /// `LEASE_READY → EXECUTION_STARTING` — the step-8a gate passed; the launcher is about to spawn
    /// (§5 step 9, the last auto-launchable edge).
    ExecutionStarting,
    /// `EXECUTION_STARTING → EXECUTING` — the child is confirmed running AND its process metadata is
    /// durably persisted (§5 — the single event that flips STARTING→EXECUTING).
    Executing {
        process_group_id: String,
        cgroup_id: String,
        execution_started_marker: Option<String>,
    },
    /// `EXECUTING → COMPLETED` — the terminal record exists + re-verifies (§5 step 11).
    Completed { terminal_record_handle: String },
    /// `EXECUTING → FAILED` — authoritative evidence the attempt produced no acceptable governed result.
    Failed { failure_reason: String },
    /// `{ACCEPTED_PREPARED|LEASE_READY} → BLOCKED` — a deterministic post-acceptance pre-execution
    /// security/policy/binding refusal (never a crash-cut, never lease-expiry).
    Blocked { failure_reason: String },
    /// `LEASE_READY → EXPIRED` — the ONLY destination of a pre-launch lease-expiry gate failure
    /// (§5 step 8a); no launch occurred.
    Expired { failure_reason: String },
    /// `{EXECUTION_STARTING|EXECUTING} → RECOVERY_REQUIRED` — an ambiguous post-launch crash where
    /// execution may have occurred but complete terminal proof is unavailable (§5 P0-1; never relaunch).
    RecoveryRequired { failure_reason: String },
}

impl Advance {
    fn target(&self) -> AcceptanceState {
        match self {
            Advance::LeaseReady { .. } => AcceptanceState::LeaseReady,
            Advance::ExecutionStarting => AcceptanceState::ExecutionStarting,
            Advance::Executing { .. } => AcceptanceState::Executing,
            Advance::Completed { .. } => AcceptanceState::Completed,
            Advance::Failed { .. } => AcceptanceState::Failed,
            Advance::Blocked { .. } => AcceptanceState::Blocked,
            Advance::Expired { .. } => AcceptanceState::Expired,
            Advance::RecoveryRequired { .. } => AcceptanceState::RecoveryRequired,
        }
    }

    /// The legal predecessor states for this edge (the SQL `WHERE state IN (...)` guard), matching the
    /// §5 deterministic state-purpose matrix.
    fn predecessors(&self) -> &'static [AcceptanceState] {
        use AcceptanceState::*;
        match self {
            Advance::LeaseReady { .. } => &[AcceptedPrepared],
            Advance::ExecutionStarting => &[LeaseReady],
            Advance::Executing { .. } => &[ExecutionStarting],
            Advance::Completed { .. } => &[Executing],
            Advance::Failed { .. } => &[Executing],
            Advance::Blocked { .. } => &[AcceptedPrepared, LeaseReady],
            Advance::Expired { .. } => &[LeaseReady],
            Advance::RecoveryRequired { .. } => &[ExecutionStarting, Executing],
        }
    }
}

/// Apply a §5 transition to the row identified by `execution_attempt_id`. The `UPDATE` carries a
/// `WHERE state IN (<legal predecessors>)` guard, so an illegal jump matches zero rows and is reported
/// as [`LedgerError::IllegalTransition`] (never a silent overwrite); a missing attempt is
/// [`LedgerError::NotFound`]. The DB `BEFORE UPDATE` trigger is a second, independent wall against any
/// illegal edge or any move out of a terminal state. Returns the new state on success.
pub fn advance(
    conn: &Connection,
    execution_attempt_id: &str,
    adv: &Advance,
    now_ms: i64,
) -> Result<AcceptanceState, LedgerError> {
    let target = adv.target();
    let preds = adv.predecessors();
    let pred_list = preds
        .iter()
        .map(|s| format!("'{}'", s.as_str()))
        .collect::<Vec<_>>()
        .join(",");

    // Each edge sets `state` + its own columns. All share the WHERE guard on attempt id + predecessors.
    let where_clause = format!(
        "WHERE execution_attempt_id = ?1 AND state IN ({pred_list})"
    );
    let affected = match adv {
        Advance::LeaseReady { lease_handle } => conn.execute(
            &format!(
                "UPDATE governed_turn_acceptance SET state='LEASE_READY', lease_handle=?2, \
                 updated_at_ms=?3 {where_clause}"
            ),
            params![execution_attempt_id, lease_handle, now_ms],
        )?,
        Advance::ExecutionStarting => conn.execute(
            &format!(
                "UPDATE governed_turn_acceptance SET state='EXECUTION_STARTING', updated_at_ms=?2 \
                 {where_clause}"
            ),
            params![execution_attempt_id, now_ms],
        )?,
        Advance::Executing {
            process_group_id,
            cgroup_id,
            execution_started_marker,
        } => conn.execute(
            &format!(
                "UPDATE governed_turn_acceptance SET state='EXECUTING', process_group_id=?2, \
                 cgroup_id=?3, execution_started_marker=?4, updated_at_ms=?5 {where_clause}"
            ),
            params![
                execution_attempt_id,
                process_group_id,
                cgroup_id,
                execution_started_marker,
                now_ms
            ],
        )?,
        Advance::Completed {
            terminal_record_handle,
        } => conn.execute(
            &format!(
                "UPDATE governed_turn_acceptance SET state='COMPLETED', terminal_record_handle=?2, \
                 updated_at_ms=?3 {where_clause}"
            ),
            params![execution_attempt_id, terminal_record_handle, now_ms],
        )?,
        Advance::Failed { failure_reason }
        | Advance::Blocked { failure_reason }
        | Advance::Expired { failure_reason }
        | Advance::RecoveryRequired { failure_reason } => conn.execute(
            &format!(
                "UPDATE governed_turn_acceptance SET state=?2, failure_reason=?3, updated_at_ms=?4 \
                 {where_clause}"
            ),
            params![execution_attempt_id, target.as_str(), failure_reason, now_ms],
        )?,
    };

    if affected == 1 {
        return Ok(target);
    }
    // Zero rows: disambiguate a missing attempt from an illegal transition.
    match current_state(conn, execution_attempt_id)? {
        None => Err(LedgerError::NotFound),
        Some(from) => Err(LedgerError::IllegalTransition {
            from: from.as_str(),
            to: target.as_str(),
        }),
    }
}

/// The `LEASE_READY` step-8a lease-expiry launch gate outcome (§5 step 8a). Pure — no DB, no clock.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LaunchGate {
    /// The lease is valid and has ≥ `MIN_LAUNCH_REMAINING_MS` remaining: proceed to launch.
    Proceed,
    /// The gate failed; the carried reason is the deterministic `EXPIRED` cause.
    Expired(&'static str),
}

/// The §5 step-8a lease-expiry launch gate on the WALL clock (compares signed `_ms` fields). Requires
/// (i) `lease_issued_at_ms ≤ now_ms ≤ lease_expires_at_ms` and (ii) remaining budget
/// `lease_expires_at_ms − now_ms ≥ MIN_LAUNCH_REMAINING_MS`. Boundary: remaining `179999` refuses,
/// `180000` proceeds; `now_ms == lease_expires_at_ms` passes (i) but fails (ii). Pure + host-independent.
pub fn lease_launch_gate(now_ms: i64, lease_issued_at_ms: i64, lease_expires_at_ms: i64) -> LaunchGate {
    if now_ms < lease_issued_at_ms {
        return LaunchGate::Expired("lease_not_yet_valid");
    }
    if now_ms > lease_expires_at_ms {
        return LaunchGate::Expired("lease_expired");
    }
    if lease_expires_at_ms - now_ms < MIN_LAUNCH_REMAINING_MS {
        return LaunchGate::Expired("insufficient_remaining_budget");
    }
    LaunchGate::Proceed
}

/// Run the step-8a gate and CAS `LEASE_READY` to its deterministic next state (§5 step 8a/9): on
/// `Proceed` → `EXECUTION_STARTING` (the launcher may now spawn once); on failure → `EXPIRED` with the
/// gate reason (no launch). This is the ONE place a `LEASE_READY` row is auto-driven forward, so the
/// gate cannot be smuggled past. Returns the resulting state.
pub fn gate_and_start(
    conn: &Connection,
    execution_attempt_id: &str,
    now_ms: i64,
    lease_issued_at_ms: i64,
    lease_expires_at_ms: i64,
) -> Result<AcceptanceState, LedgerError> {
    match lease_launch_gate(now_ms, lease_issued_at_ms, lease_expires_at_ms) {
        LaunchGate::Proceed => advance(conn, execution_attempt_id, &Advance::ExecutionStarting, now_ms),
        LaunchGate::Expired(reason) => advance(
            conn,
            execution_attempt_id,
            &Advance::Expired {
                failure_reason: reason.to_string(),
            },
            now_ms,
        ),
    }
}

/// The current state of an attempt, or `None` if no row exists. Fails closed
/// ([`LedgerError::Corrupt`]) on an out-of-domain stored token.
pub fn current_state(
    conn: &Connection,
    execution_attempt_id: &str,
) -> Result<Option<AcceptanceState>, LedgerError> {
    let raw: Option<String> = conn
        .query_row(
            "SELECT state FROM governed_turn_acceptance WHERE execution_attempt_id = ?1",
            params![execution_attempt_id],
            |r| r.get(0),
        )
        .optional()?;
    match raw {
        None => Ok(None),
        Some(s) => AcceptanceState::from_str(&s)
            .map(Some)
            .ok_or(LedgerError::Corrupt("acceptance.state")),
    }
}

/// The exact canonical lease payload bytes persisted at acceptance (for deterministic re-sign after a
/// post-commit / pre-signature crash, §5 step 6). `None` if the attempt is unknown.
pub fn lease_payload_bytes(
    conn: &Connection,
    execution_attempt_id: &str,
) -> Result<Option<Vec<u8>>, LedgerError> {
    let bytes: Option<Vec<u8>> = conn
        .query_row(
            "SELECT lease_payload_bytes FROM governed_turn_acceptance WHERE execution_attempt_id = ?1",
            params![execution_attempt_id],
            |r| r.get(0),
        )
        .optional()?;
    Ok(bytes)
}

// ---------------------------------------------------------------------------
// Outbox — durable terminal record staged for atomic filesystem publish.
// ---------------------------------------------------------------------------

/// A terminal governed-turn record staged in the outbox for the atomic `<run_id>__<attempt>.json`
/// publish (§5 outbox / §6 step 4).
#[derive(Debug, Clone)]
pub struct TerminalRecord {
    pub execution_attempt_id: String,
    pub run_id: String,
    pub terminal_state: AcceptanceState,
    /// The content-addressed terminal-record handle (`64hex`), present for a `COMPLETED` publish.
    pub terminal_record_handle: Option<String>,
    /// The exact record bytes to write (their sha256 is stored + byte-compared on retry).
    pub payload_bytes: Vec<u8>,
}

/// Outcome of [`enqueue_terminal`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum OutboxOutcome {
    /// A fresh outbox row was created.
    Enqueued,
    /// An identical row already existed (crash-retry after a committed enqueue) — idempotent.
    Idempotent,
}

/// Enqueue a terminal record (create-if-absent on the `execution_attempt_id` PK, §5 outbox). Only a
/// terminal state may be enqueued. On a retry that presents byte-identical bytes ⇒
/// [`OutboxOutcome::Idempotent`]; differing bytes for the same attempt ⇒ [`LedgerError::Conflict`]. The
/// filename is the design's atomic terminal path `<run_id>__<execution_attempt_id>.json`.
pub fn enqueue_terminal(
    conn: &Connection,
    rec: &TerminalRecord,
    now_ms: i64,
) -> Result<OutboxOutcome, LedgerError> {
    if !rec.terminal_state.is_terminal() {
        return Err(LedgerError::Conflict("outbox_non_terminal_state"));
    }
    let payload_sha256 = sha256_hex(&rec.payload_bytes);
    let filename = format!("{}__{}.json", rec.run_id, rec.execution_attempt_id);
    let res = conn.execute(
        "INSERT INTO governed_turn_outbox (\
            execution_attempt_id, run_id, terminal_state, terminal_record_handle, record_filename, \
            payload_sha256, payload_bytes, published, created_at_ms) \
         VALUES (?1,?2,?3,?4,?5,?6,?7,0,?8)",
        params![
            rec.execution_attempt_id,
            rec.run_id,
            rec.terminal_state.as_str(),
            rec.terminal_record_handle,
            filename,
            payload_sha256,
            rec.payload_bytes,
            now_ms,
        ],
    );
    match res {
        Ok(_) => Ok(OutboxOutcome::Enqueued),
        Err(e) if is_unique_violation(&e) => {
            let existing: Option<String> = conn
                .query_row(
                    "SELECT payload_sha256 FROM governed_turn_outbox WHERE execution_attempt_id = ?1",
                    params![rec.execution_attempt_id],
                    |r| r.get(0),
                )
                .optional()?;
            match existing {
                Some(h) if h == payload_sha256 => Ok(OutboxOutcome::Idempotent),
                Some(_) => Err(LedgerError::Conflict("outbox_bytes_differ")),
                None => Err(LedgerError::Db(e)),
            }
        }
        Err(e) => Err(LedgerError::Db(e)),
    }
}

/// A pending (unpublished) outbox entry: what the drain loop needs to perform the atomic filesystem
/// write, plus the bytes.
#[derive(Debug, Clone)]
pub struct OutboxEntry {
    pub execution_attempt_id: String,
    pub record_filename: String,
    pub payload_sha256: String,
    pub payload_bytes: Vec<u8>,
}

/// All not-yet-published outbox entries in insertion order (the supervisor drains these to the store).
pub fn pending_outbox(conn: &Connection) -> Result<Vec<OutboxEntry>, LedgerError> {
    let mut stmt = conn.prepare(
        "SELECT execution_attempt_id, record_filename, payload_sha256, payload_bytes \
         FROM governed_turn_outbox WHERE published = 0 ORDER BY created_at_ms, execution_attempt_id",
    )?;
    let rows = stmt.query_map([], |r| {
        Ok(OutboxEntry {
            execution_attempt_id: r.get(0)?,
            record_filename: r.get(1)?,
            payload_sha256: r.get(2)?,
            payload_bytes: r.get(3)?,
        })
    })?;
    let mut out = Vec::new();
    for r in rows {
        out.push(r?);
    }
    Ok(out)
}

/// Mark an outbox entry published after its atomic filesystem write committed. Idempotent: marking an
/// already-published (or unknown) row affects zero rows and returns `false`; a fresh mark returns `true`.
pub fn mark_published(
    conn: &Connection,
    execution_attempt_id: &str,
    now_ms: i64,
) -> Result<bool, LedgerError> {
    let affected = conn.execute(
        "UPDATE governed_turn_outbox SET published = 1, published_at_ms = ?2 \
         WHERE execution_attempt_id = ?1 AND published = 0",
        params![execution_attempt_id, now_ms],
    )?;
    Ok(affected == 1)
}

// ---------------------------------------------------------------------------
// Signer-owned durable evidence-head floor CAS (§5 step 11 / §7 P1-7).
// ---------------------------------------------------------------------------

/// A validated evidence head presented to the floor CAS (§7). `head_sequence` is the re-ANCHOR/re-SIGN
/// counter (the monotonic epoch); the chain-content identity is `final_event_hash` with
/// `event_count`/`last_sequence` (`last_sequence == event_count`, 1-based).
#[derive(Debug, Clone)]
pub struct EvidenceHead {
    pub install_id: String,
    pub task_id: String,
    pub head_sequence: i64,
    pub event_count: i64,
    pub last_sequence: i64,
    pub final_event_hash: String,
}

impl EvidenceHead {
    /// Reject a malformed head (matching the DDL CHECKs + the real `bro_evidence.py` `< 1` rejection):
    /// positive counts, `last_sequence == event_count`, and a 64-hex `final_event_hash`.
    fn validate(&self) -> Result<(), LedgerError> {
        if self.head_sequence < 1 {
            return Err(LedgerError::InvalidHead("head_sequence < 1"));
        }
        if self.event_count < 1 {
            return Err(LedgerError::InvalidHead("event_count < 1"));
        }
        if self.last_sequence < 1 {
            return Err(LedgerError::InvalidHead("last_sequence < 1"));
        }
        if self.last_sequence != self.event_count {
            return Err(LedgerError::InvalidHead("last_sequence != event_count"));
        }
        if self.final_event_hash.len() != 64
            || !self.final_event_hash.bytes().all(|b| b.is_ascii_hexdigit())
        {
            return Err(LedgerError::InvalidHead("final_event_hash not 64-hex"));
        }
        Ok(())
    }
}

/// The floor CAS decision.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FloorDecision {
    /// No prior row for `(install_id, task_id)` — the head was inserted (bootstrap).
    Bootstrapped,
    /// A strictly-higher `head_sequence` — the floor was advanced to the new head + content.
    Advanced,
    /// Equal `head_sequence` with identical content — an idempotent re-sign; the floor is unchanged.
    Idempotent,
}

/// The durable evidence-head-floor CAS (§5 step 11 / §7 P1-7). In ONE `BEGIN IMMEDIATE` (write-lock up
/// front; a nested/outer transaction is refused so the read-then-write cannot be rolled back under it)
/// it decides against the floor for the **install**, keyed on the `head_sequence` epoch +
/// `final_event_hash` identity:
///
/// - **this task already holds this exact `head_sequence`** ⇒ identical content is an idempotent
///   re-sign ([`FloorDecision::Idempotent`]); ANY content difference is a same-head fork
///   ([`LedgerError::EvidenceFork`]). Decided FIRST, so a byte-identical retry is not read as a
///   rollback merely because another task advanced past it;
/// - **`head_sequence` below the highest recorded ANYWHERE on this install** ⇒ refuse
///   [`LedgerError::StaleEvidence`] (a retained older signed head always carries a LOWER re-anchor
///   number);
/// - **`head_sequence` equal to it** ⇒ [`LedgerError::EvidenceFork`]: one install has one counter, so
///   the same value cannot legitimately be minted twice;
/// - otherwise INSERT ([`FloorDecision::Bootstrapped`]) or advance ([`FloorDecision::Advanced`]) the
///   `(install_id, task_id)` row.
///
/// # The scope is the INSTALL, not `(install_id, task_id)`
///
/// This used to read and compare ONLY the `(install_id, task_id)` row, so the `no row ⇒ bootstrap`
/// branch handed a free pass to anyone presenting a rolled-back head under a task_id that had no row
/// yet. `task_id` is not a supervisor secret: it arrives on the wire, the challenge authority accepts
/// any bounded string for it, and the supervisor copies it out of the challenge payload — so the scope
/// of the anti-rollback defence was a value the attacker chose. Driven against the Python twin,
/// `(task-1, head 99)` recorded, `(task-1, head 3)` was refused `StaleEvidence`, and
/// `(task-FRESH, head 3)` — the SAME rolled-back head — recorded and produced attestation state.
///
/// Install scope is also what the number MEANS. `head_sequence` is minted by ONE per-recorder counter
/// (`governed_recorder`'s `next_head_sequence` read-increments a single
/// `<evidence_state_dir>/evidence-head-sequence.json`), so it is monotonic across every run of a
/// deployment regardless of task. A per-task partition could never have matched the counter it
/// polices; it could only create buckets to hide in. The `(install_id, task_id)` row is KEPT (the DDL
/// is unchanged) as the per-task detail record and as the idempotency key.
///
/// The floor is committed BEFORE any envelope is minted, closing the TOCTOU on the `(install_id,
/// task_id)` PK; a crash after commit re-hits the equal-head idempotent branch and re-signs identically.
pub fn evidence_floor_cas(
    conn: &Connection,
    head: &EvidenceHead,
    now_ms: i64,
) -> Result<FloorDecision, LedgerError> {
    head.validate()?;
    if !conn.is_autocommit() {
        return Err(LedgerError::NestedTransaction);
    }
    conn.execute_batch("BEGIN IMMEDIATE;")?;
    match evidence_floor_cas_body(conn, head, now_ms) {
        Ok(decision) => match conn.execute_batch("COMMIT;") {
            Ok(()) => Ok(decision),
            Err(e) => {
                let _ = conn.execute_batch("ROLLBACK;");
                Err(LedgerError::Db(e))
            }
        },
        Err(e) => {
            let _ = conn.execute_batch("ROLLBACK;");
            Err(e)
        }
    }
}

/// The CAS body, run inside the owned `BEGIN IMMEDIATE`. A refuse verdict returns `Err` (⇒ ROLLBACK,
/// no write); bootstrap/advance write then the caller COMMITs; idempotent writes nothing.
fn evidence_floor_cas_body(
    conn: &Connection,
    head: &EvidenceHead,
    now_ms: i64,
) -> Result<FloorDecision, LedgerError> {
    let stored: Option<(i64, i64, i64, String)> = conn
        .query_row(
            "SELECT highest_head_sequence, event_count, last_sequence, final_event_hash \
             FROM governed_evidence_head_floor WHERE install_id = ?1 AND task_id = ?2",
            params![head.install_id, head.task_id],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
        )
        .optional()?;

    // Fail closed on a corrupt stored row (startup-integrity, scoped to the rows we touch).
    fn refuse_corrupt(highest: i64, ec: i64, ls: i64, feh: &str) -> Result<(), LedgerError> {
        if highest < 1 || ec < 1 || ls < 1 || ls != ec || feh.len() != 64 {
            return Err(LedgerError::Corrupt("evidence_head_floor"));
        }
        Ok(())
    }

    // (1) The exact row this task holds decides the idempotent re-sign, BEFORE the install-wide
    // ceiling: a byte-identical retry writes nothing and must not read as a rollback just because
    // another task advanced past it in the meantime.
    if let Some((highest, ec, ls, feh)) = stored.as_ref() {
        refuse_corrupt(*highest, *ec, *ls, feh)?;
        if head.head_sequence == *highest {
            let identical =
                head.event_count == *ec && head.last_sequence == *ls && head.final_event_hash == *feh;
            return if identical {
                Ok(FloorDecision::Idempotent)
            } else {
                Err(LedgerError::EvidenceFork)
            };
        }
    }

    // (2) The FLOOR: the highest head this install has recorded in ANY task bucket. `task_id` is
    // caller-chosen, so it may not select which floor the head is measured against.
    let ceiling: Option<(String, i64, i64, i64, String)> = conn
        .query_row(
            "SELECT task_id, highest_head_sequence, event_count, last_sequence, final_event_hash \
             FROM governed_evidence_head_floor WHERE install_id = ?1 \
             ORDER BY highest_head_sequence DESC, task_id ASC LIMIT 1",
            params![head.install_id],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?)),
        )
        .optional()?;
    if let Some((_, highest, ec, ls, feh)) = ceiling.as_ref() {
        refuse_corrupt(*highest, *ec, *ls, feh)?;
        if head.head_sequence < *highest {
            return Err(LedgerError::StaleEvidence);
        }
        if head.head_sequence == *highest {
            // One install, one counter: the same head_sequence cannot be minted twice. Equal-and-
            // identical for THIS task already returned above, so this is a different task claiming
            // a taken counter value.
            return Err(LedgerError::EvidenceFork);
        }
    }

    if stored.is_none() {
        conn.execute(
            "INSERT INTO governed_evidence_head_floor (\
                install_id, task_id, highest_head_sequence, event_count, last_sequence, \
                final_event_hash, updated_at_ms) VALUES (?1,?2,?3,?4,?5,?6,?7)",
            params![
                head.install_id,
                head.task_id,
                head.head_sequence,
                head.event_count,
                head.last_sequence,
                head.final_event_hash,
                now_ms,
            ],
        )?;
        return Ok(FloorDecision::Bootstrapped);
    }

    // Strictly-higher head_sequence: advance the floor (every field) and commit.
    conn.execute(
        "UPDATE governed_evidence_head_floor SET highest_head_sequence = ?3, event_count = ?4, \
         last_sequence = ?5, final_event_hash = ?6, updated_at_ms = ?7 \
         WHERE install_id = ?1 AND task_id = ?2",
        params![
            head.install_id,
            head.task_id,
            head.head_sequence,
            head.event_count,
            head.last_sequence,
            head.final_event_hash,
            now_ms,
        ],
    )?;
    Ok(FloorDecision::Advanced)
}

// ---------------------------------------------------------------------------
// Shared helpers.
// ---------------------------------------------------------------------------

/// True iff a rusqlite error is a UNIQUE / PRIMARY KEY constraint violation (the CAS-loss signal).
fn is_unique_violation(e: &rusqlite::Error) -> bool {
    matches!(
        e,
        rusqlite::Error::SqliteFailure(
            rusqlite::ffi::Error {
                code: rusqlite::ErrorCode::ConstraintViolation,
                extended_code,
            },
            _,
        ) if *extended_code == rusqlite::ffi::SQLITE_CONSTRAINT_UNIQUE
            || *extended_code == rusqlite::ffi::SQLITE_CONSTRAINT_PRIMARYKEY
    )
}

// ---------------------------------------------------------------------------
// Tests — all offline (in-memory rusqlite, injected clocks).
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    const H64: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    const H64_B: &str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";

    fn store() -> Connection {
        let conn = Connection::open_in_memory().expect("open in-memory");
        create_schema(&conn).expect("create schema");
        conn
    }

    fn new_acceptance(attempt: &str) -> NewAcceptance {
        NewAcceptance {
            install_id: "install-1".into(),
            request_nonce: format!("nonce-{attempt}"),
            challenge_handle: format!("chal-{attempt}"),
            run_id: "run-1".into(),
            task_id: "task-1".into(),
            workspace_id: "ws-1".into(),
            execution_attempt_id: attempt.into(),
            challenge_accepted_at_ms: 1_000_000,
            challenge_registry_handle: "reg-h".into(),
            challenge_registry_hash: "reg-hash".into(),
            challenge_registry_epoch: 7,
            challenge_registry_root_key_id: "root-1".into(),
            lease_payload_bytes: b"lease-payload-bytes".to_vec(),
            lease_id: format!("lease-{attempt}"),
            lease_issued_at_ms: 1_000_000,
            lease_expires_at_ms: 1_210_000,
            receipt_id: format!("receipt-{attempt}"),
            supervisor_id: "supervisor-1".into(),
            requested_at_ms: 999_000,
            request_sha256: H64.into(),
            system_handle: H64.into(),
            history_handle: H64_B.into(),
            generation_config_handle: H64.into(),
        }
    }

    #[test]
    fn schema_create_is_idempotent() {
        let conn = Connection::open_in_memory().unwrap();
        create_schema(&conn).unwrap();
        create_schema(&conn).unwrap();
        assert!(pending_outbox(&conn).unwrap().is_empty());
    }

    /// F-01: the SHARED DDL must carry the durable request binding an attestation is rebuilt from,
    /// plus the write-once completion table. The Python supervisor is the production writer of this
    /// state, so this test pins the contract on the Rust side of the mirror: if a column the
    /// attestation depends on is dropped from the canonical SQL, this fails here too.
    #[test]
    fn schema_carries_the_attestation_binding_and_write_once_completion() {
        let conn = store();
        for col in [
            "lease_id",
            "lease_issued_at_ms",
            "lease_expires_at_ms",
            "receipt_id",
            "supervisor_id",
            "requested_at_ms",
            "request_sha256",
            "system_handle",
            "history_handle",
            "generation_config_handle",
        ] {
            let present: i64 = conn
                .query_row(
                    "SELECT COUNT(*) FROM pragma_table_info('governed_turn_acceptance') WHERE name = ?1",
                    params![col],
                    |r| r.get(0),
                )
                .unwrap();
            assert_eq!(present, 1, "acceptance binding column `{col}` is missing from the shared DDL");
        }

        // The completion table exists and its PK is the write-once gate on the run-produced facts.
        accept_prepare(&conn, &new_acceptance("att-1"), 10).unwrap();
        let insert = "INSERT INTO governed_turn_completion (\
            execution_attempt_id, output_handle, containment_evidence_handle, record_handle, \
            lease_handle, execution_receipt_handle, completed_at_ms, evidence_final_event_hash, \
            evidence_event_count, evidence_last_sequence, evidence_head_sequence, facts_sha256, \
            created_at_ms) VALUES ('att-1',?1,?1,?1,?1,?1,50,?1,3,3,12,?1,50)";
        conn.execute(insert, params![H64]).unwrap();
        // A second completion for the same attempt cannot be written at all — the PK refuses it, so a
        // caller gets exactly one shot at the facts the attestation will carry.
        let second = conn.execute(insert, params![H64_B]);
        assert!(second.is_err(), "a second completion for one attempt must be refused by the PK");

        // The FK is live: a completion for an attempt that was never accepted is refused.
        let orphan = conn.execute(
            "INSERT INTO governed_turn_completion (\
                execution_attempt_id, output_handle, containment_evidence_handle, record_handle, \
                lease_handle, execution_receipt_handle, completed_at_ms, evidence_final_event_hash, \
                evidence_event_count, evidence_last_sequence, evidence_head_sequence, facts_sha256, \
                created_at_ms) VALUES ('ghost',?1,?1,?1,?1,?1,50,?1,3,3,12,?1,50)",
            params![H64],
        );
        assert!(orphan.is_err(), "a completion with no accepted attempt must be refused by the FK");
    }

    /// A `receipt_id` is the §7.1(d) global-unique replay key; two attempts must never share one.
    #[test]
    fn receipt_id_is_unique_across_attempts() {
        let conn = store();
        accept_prepare(&conn, &new_acceptance("att-1"), 10).unwrap();
        let mut clash = new_acceptance("att-2");
        clash.receipt_id = "receipt-att-1".into();
        assert!(matches!(accept_prepare(&conn, &clash, 20), Err(LedgerError::Conflict(_))));
    }

    // ---- Acceptance ledger: create + legal chain --------------------------

    #[test]
    fn legal_transition_chain_succeeds() {
        let conn = store();
        assert_eq!(
            accept_prepare(&conn, &new_acceptance("att-1"), 10).unwrap(),
            AcceptOutcome::Created
        );
        assert_eq!(
            current_state(&conn, "att-1").unwrap(),
            Some(AcceptanceState::AcceptedPrepared)
        );

        // ACCEPTED_PREPARED -> LEASE_READY -> EXECUTION_STARTING -> EXECUTING -> COMPLETED
        assert_eq!(
            advance(
                &conn,
                "att-1",
                &Advance::LeaseReady { lease_handle: "lease-h".into() },
                20
            )
            .unwrap(),
            AcceptanceState::LeaseReady
        );
        assert_eq!(
            advance(&conn, "att-1", &Advance::ExecutionStarting, 30).unwrap(),
            AcceptanceState::ExecutionStarting
        );
        assert_eq!(
            advance(
                &conn,
                "att-1",
                &Advance::Executing {
                    process_group_id: "pg-1".into(),
                    cgroup_id: "cg-1".into(),
                    execution_started_marker: Some("marker".into()),
                },
                40
            )
            .unwrap(),
            AcceptanceState::Executing
        );
        assert_eq!(
            advance(
                &conn,
                "att-1",
                &Advance::Completed { terminal_record_handle: "rec-h".into() },
                50
            )
            .unwrap(),
            AcceptanceState::Completed
        );
        assert!(current_state(&conn, "att-1").unwrap().unwrap().is_terminal());
    }

    #[test]
    fn illegal_jump_is_refused() {
        let conn = store();
        accept_prepare(&conn, &new_acceptance("att-1"), 10).unwrap();
        // ACCEPTED_PREPARED -> EXECUTING is NOT a legal edge (must go via LEASE_READY/STARTING).
        let err = advance(
            &conn,
            "att-1",
            &Advance::Executing {
                process_group_id: "pg".into(),
                cgroup_id: "cg".into(),
                execution_started_marker: None,
            },
            20,
        );
        assert!(matches!(
            err,
            Err(LedgerError::IllegalTransition {
                from: "ACCEPTED_PREPARED",
                to: "EXECUTING"
            })
        ));
        // The row was not mutated.
        assert_eq!(
            current_state(&conn, "att-1").unwrap(),
            Some(AcceptanceState::AcceptedPrepared)
        );
    }

    #[test]
    fn no_path_out_of_a_terminal_state() {
        let conn = store();
        accept_prepare(&conn, &new_acceptance("att-1"), 10).unwrap();
        advance(&conn, "att-1", &Advance::Blocked { failure_reason: "policy".into() }, 20).unwrap();
        assert_eq!(current_state(&conn, "att-1").unwrap(), Some(AcceptanceState::Blocked));
        // No edge leaves BLOCKED (a terminal). Any attempt is IllegalTransition, never a mutation.
        assert!(matches!(
            advance(&conn, "att-1", &Advance::LeaseReady { lease_handle: "x".into() }, 30),
            Err(LedgerError::IllegalTransition { from: "BLOCKED", .. })
        ));
        assert_eq!(current_state(&conn, "att-1").unwrap(), Some(AcceptanceState::Blocked));
    }

    #[test]
    fn advancing_unknown_attempt_is_not_found() {
        let conn = store();
        assert!(matches!(
            advance(&conn, "ghost", &Advance::LeaseReady { lease_handle: "x".into() }, 1),
            Err(LedgerError::NotFound)
        ));
    }

    #[test]
    fn duplicate_submission_is_idempotent_not_a_second_attempt() {
        let conn = store();
        let a = new_acceptance("att-1");
        assert_eq!(accept_prepare(&conn, &a, 10).unwrap(), AcceptOutcome::Created);
        // Same nonce + same bindings again ⇒ idempotent, exactly one row.
        assert_eq!(accept_prepare(&conn, &a, 11).unwrap(), AcceptOutcome::Idempotent);
        let count: i64 = conn
            .query_row("SELECT COUNT(*) FROM governed_turn_acceptance", [], |r| r.get(0))
            .unwrap();
        assert_eq!(count, 1);
    }

    #[test]
    fn same_nonce_different_challenge_is_conflict() {
        let conn = store();
        accept_prepare(&conn, &new_acceptance("att-1"), 10).unwrap();
        let mut clash = new_acceptance("att-2"); // different attempt id...
        clash.request_nonce = "nonce-att-1".into(); // ...but reuses att-1's nonce with a new challenge.
        assert!(matches!(
            accept_prepare(&conn, &clash, 20),
            Err(LedgerError::Conflict(_))
        ));
    }

    #[test]
    fn same_challenge_different_nonce_is_conflict() {
        let conn = store();
        accept_prepare(&conn, &new_acceptance("att-1"), 10).unwrap();
        let mut clash = new_acceptance("att-3");
        clash.challenge_handle = "chal-att-1".into(); // reuse att-1's challenge with a fresh nonce.
        assert!(matches!(
            accept_prepare(&conn, &clash, 20),
            Err(LedgerError::Conflict(_))
        ));
    }

    #[test]
    fn conflicting_run_id_on_retry_is_refused() {
        let conn = store();
        accept_prepare(&conn, &new_acceptance("att-1"), 10).unwrap();
        let mut retry = new_acceptance("att-1"); // same nonce+challenge+attempt...
        retry.run_id = "run-DIFFERENT".into(); // ...but a different run_id ⇒ conflict, not idempotent.
        assert!(matches!(
            accept_prepare(&conn, &retry, 20),
            Err(LedgerError::Conflict(_))
        ));
    }

    // ---- Lease-expiry launch gate (§5 step 8a) ----------------------------

    #[test]
    fn lease_gate_budget_boundary() {
        // remaining == MIN - 1 refuses; remaining == MIN proceeds; over-expiry refuses; pre-valid refuses.
        let issued = 1_000i64;
        let expires = issued + LEASE_DURATION_MS;
        // remaining exactly 179_999 -> refuse
        let now_179999 = expires - (MIN_LAUNCH_REMAINING_MS - 1);
        assert!(matches!(
            lease_launch_gate(now_179999, issued, expires),
            LaunchGate::Expired("insufficient_remaining_budget")
        ));
        // remaining exactly 180_000 -> proceed
        let now_180000 = expires - MIN_LAUNCH_REMAINING_MS;
        assert_eq!(lease_launch_gate(now_180000, issued, expires), LaunchGate::Proceed);
        // now == expires -> passes (i) but fails (ii)
        assert!(matches!(
            lease_launch_gate(expires, issued, expires),
            LaunchGate::Expired("insufficient_remaining_budget")
        ));
        // now == expires + 1 -> expired
        assert!(matches!(
            lease_launch_gate(expires + 1, issued, expires),
            LaunchGate::Expired("lease_expired")
        ));
        // pre-valid
        assert!(matches!(
            lease_launch_gate(issued - 1, issued, expires),
            LaunchGate::Expired("lease_not_yet_valid")
        ));
    }

    #[test]
    fn gate_and_start_proceeds_and_expires_deterministically() {
        let conn = store();
        // Passing gate -> EXECUTION_STARTING.
        accept_prepare(&conn, &new_acceptance("att-ok"), 10).unwrap();
        advance(&conn, "att-ok", &Advance::LeaseReady { lease_handle: "l".into() }, 20).unwrap();
        let issued = 1_000i64;
        let expires = issued + LEASE_DURATION_MS;
        assert_eq!(
            gate_and_start(&conn, "att-ok", expires - MIN_LAUNCH_REMAINING_MS, issued, expires).unwrap(),
            AcceptanceState::ExecutionStarting
        );

        // Failing gate (expired on restart) -> EXPIRED, zero launch.
        accept_prepare(&conn, &new_acceptance("att-exp"), 10).unwrap();
        advance(&conn, "att-exp", &Advance::LeaseReady { lease_handle: "l2".into() }, 20).unwrap();
        assert_eq!(
            gate_and_start(&conn, "att-exp", expires + 1, issued, expires).unwrap(),
            AcceptanceState::Expired
        );
    }

    // ---- Outbox -----------------------------------------------------------

    fn terminal(attempt: &str, bytes: &[u8]) -> TerminalRecord {
        TerminalRecord {
            execution_attempt_id: attempt.into(),
            run_id: "run-1".into(),
            terminal_state: AcceptanceState::Completed,
            terminal_record_handle: Some("rec-h".into()),
            payload_bytes: bytes.to_vec(),
        }
    }

    #[test]
    fn outbox_enqueue_publish_lifecycle_and_idempotency() {
        let conn = store();
        accept_prepare(&conn, &new_acceptance("att-1"), 10).unwrap(); // FK parent
        assert_eq!(
            enqueue_terminal(&conn, &terminal("att-1", b"record-bytes"), 20).unwrap(),
            OutboxOutcome::Enqueued
        );
        // Byte-identical retry ⇒ idempotent.
        assert_eq!(
            enqueue_terminal(&conn, &terminal("att-1", b"record-bytes"), 21).unwrap(),
            OutboxOutcome::Idempotent
        );
        // Differing bytes for the same attempt ⇒ conflict.
        assert!(matches!(
            enqueue_terminal(&conn, &terminal("att-1", b"TAMPERED"), 22),
            Err(LedgerError::Conflict("outbox_bytes_differ"))
        ));

        let pending = pending_outbox(&conn).unwrap();
        assert_eq!(pending.len(), 1);
        assert_eq!(pending[0].record_filename, "run-1__att-1.json");
        assert_eq!(pending[0].payload_sha256, sha256_hex(b"record-bytes"));

        // Mark published: first mark true, second false (idempotent), and it drops out of pending.
        assert!(mark_published(&conn, "att-1", 30).unwrap());
        assert!(!mark_published(&conn, "att-1", 31).unwrap());
        assert!(pending_outbox(&conn).unwrap().is_empty());
    }

    #[test]
    fn outbox_refuses_non_terminal_state() {
        let conn = store();
        accept_prepare(&conn, &new_acceptance("att-1"), 10).unwrap();
        let mut rec = terminal("att-1", b"x");
        rec.terminal_state = AcceptanceState::LeaseReady;
        assert!(matches!(
            enqueue_terminal(&conn, &rec, 20),
            Err(LedgerError::Conflict("outbox_non_terminal_state"))
        ));
    }

    // ---- Evidence-head floor CAS (§5 step 11 / §7 P1-7) -------------------

    fn head(seq: i64, ec: i64, feh: &str) -> EvidenceHead {
        EvidenceHead {
            install_id: "install-1".into(),
            task_id: "task-1".into(),
            head_sequence: seq,
            event_count: ec,
            last_sequence: ec,
            final_event_hash: feh.into(),
        }
    }

    #[test]
    fn floor_bootstrap_then_refuses_lower_and_accepts_strictly_higher() {
        let conn = store();
        // Bootstrap (no row) -> INSERT.
        assert_eq!(
            evidence_floor_cas(&conn, &head(5, 3, H64), 100).unwrap(),
            FloorDecision::Bootstrapped
        );
        // Lower head_sequence -> stale_evidence (refused, floor unchanged).
        assert!(matches!(
            evidence_floor_cas(&conn, &head(4, 3, H64), 110),
            Err(LedgerError::StaleEvidence)
        ));
        // Strictly-higher head_sequence -> advance + commit.
        assert_eq!(
            evidence_floor_cas(&conn, &head(6, 4, H64_B), 120).unwrap(),
            FloorDecision::Advanced
        );
        let (hi, ec, feh): (i64, i64, String) = conn
            .query_row(
                "SELECT highest_head_sequence, event_count, final_event_hash \
                 FROM governed_evidence_head_floor WHERE install_id='install-1' AND task_id='task-1'",
                [],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
            )
            .unwrap();
        assert_eq!((hi, ec, feh.as_str()), (6, 4, H64_B));
    }

    #[test]
    fn floor_refuses_equal_head_with_differing_content() {
        let conn = store();
        evidence_floor_cas(&conn, &head(5, 3, H64), 100).unwrap();
        // Equal head_sequence but a different final_event_hash ⇒ evidence_fork.
        assert!(matches!(
            evidence_floor_cas(&conn, &head(5, 3, H64_B), 110),
            Err(LedgerError::EvidenceFork)
        ));
        // Equal head_sequence but a different event_count ⇒ evidence_fork too.
        assert!(matches!(
            evidence_floor_cas(&conn, &head(5, 4, H64), 111),
            Err(LedgerError::EvidenceFork)
        ));
    }

    #[test]
    fn floor_equal_head_identical_content_is_idempotent() {
        let conn = store();
        evidence_floor_cas(&conn, &head(5, 3, H64), 100).unwrap();
        assert_eq!(
            evidence_floor_cas(&conn, &head(5, 3, H64), 110).unwrap(),
            FloorDecision::Idempotent
        );
        // updated_at_ms is unchanged (no write on the idempotent branch).
        let updated: i64 = conn
            .query_row(
                "SELECT updated_at_ms FROM governed_evidence_head_floor \
                 WHERE install_id='install-1' AND task_id='task-1'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(updated, 100);
    }

    #[test]
    fn floor_rejects_malformed_head() {
        let conn = store();
        assert!(matches!(
            evidence_floor_cas(&conn, &head(0, 3, H64), 1),
            Err(LedgerError::InvalidHead(_))
        ));
        assert!(matches!(
            evidence_floor_cas(&conn, &head(5, 3, "not-hex"), 1),
            Err(LedgerError::InvalidHead(_))
        ));
        let mut mismatched = head(5, 3, H64);
        mismatched.last_sequence = 99; // last_sequence != event_count
        assert!(matches!(
            evidence_floor_cas(&conn, &mismatched, 1),
            Err(LedgerError::InvalidHead(_))
        ));
    }

    #[test]
    fn floor_refuses_nested_transaction() {
        let conn = store();
        conn.execute_batch("BEGIN;").unwrap();
        assert!(matches!(
            evidence_floor_cas(&conn, &head(5, 3, H64), 1),
            Err(LedgerError::NestedTransaction)
        ));
        conn.execute_batch("ROLLBACK;").unwrap();
    }

    /// This test used to assert the DEFECT. It read:
    ///
    /// ```text
    /// // A DIFFERENT task_id is an independent floor — bootstraps, unaffected by task-1's floor.
    /// let mut other = head(1, 1, H64_B);
    /// other.task_id = "task-2".into();
    /// assert_eq!(evidence_floor_cas(&conn, &other, 110).unwrap(), FloorDecision::Bootstrapped);
    /// ```
    ///
    /// — head 1 accepted after head 5 was recorded, because it arrived under another caller-chosen
    /// `task_id`. It passed for four releases while the anti-rollback floor did nothing.
    #[test]
    fn floor_scopes_by_install_not_by_a_caller_chosen_task_id() {
        let conn = store();
        evidence_floor_cas(&conn, &head(5, 3, H64), 100).unwrap();
        // A DIFFERENT task_id is NOT a fresh floor: `head_sequence` comes from one per-recorder
        // counter, so a head below the install's high-water mark is a rollback whatever it is
        // filed under.
        let mut rewound = head(1, 1, H64_B);
        rewound.task_id = "task-2".into();
        assert!(matches!(
            evidence_floor_cas(&conn, &rewound, 110),
            Err(LedgerError::StaleEvidence)
        ));
        // Equal to the install's high-water mark under another task is a fork: one install, one
        // counter, so that value cannot be minted twice.
        let mut taken = head(5, 3, H64_B);
        taken.task_id = "task-2".into();
        assert!(matches!(
            evidence_floor_cas(&conn, &taken, 111),
            Err(LedgerError::EvidenceFork)
        ));
        // A genuinely new task still bootstraps its own row — above the install-wide mark.
        let mut fresh = head(6, 4, H64_B);
        fresh.task_id = "task-2".into();
        assert_eq!(
            evidence_floor_cas(&conn, &fresh, 112).unwrap(),
            FloorDecision::Bootstrapped
        );
        // And an interleaved byte-identical re-sign of task-1's own head is still idempotent.
        assert_eq!(
            evidence_floor_cas(&conn, &head(5, 3, H64), 113).unwrap(),
            FloorDecision::Idempotent
        );
    }

    #[test]
    fn floor_still_scopes_by_install_id() {
        // Narrowed to the install, not below it: another install is another recorder with another
        // counter, and is unaffected.
        let conn = store();
        evidence_floor_cas(&conn, &head(99, 3, H64), 100).unwrap();
        let mut other_install = head(1, 1, H64_B);
        other_install.install_id = "install-2".into();
        assert_eq!(
            evidence_floor_cas(&conn, &other_install, 110).unwrap(),
            FloorDecision::Bootstrapped
        );
    }

    #[test]
    fn floor_refuses_a_corrupt_row_in_another_bucket() {
        // The install-wide ceiling can be a row this task never touches; a corrupt one must
        // refuse rather than be silently skipped.
        let conn = store();
        evidence_floor_cas(&conn, &head(99, 3, H64), 100).unwrap();
        conn.execute_batch(
            "UPDATE governed_evidence_head_floor SET final_event_hash = 'short' \
             WHERE task_id = 'task-1'",
        )
        .unwrap();
        let mut other = head(100, 3, H64_B);
        other.task_id = "task-2".into();
        assert!(matches!(
            evidence_floor_cas(&conn, &other, 110),
            Err(LedgerError::Corrupt("evidence_head_floor"))
        ));
    }

    #[test]
    fn transition_trigger_blocks_direct_illegal_state_write() {
        // Defense-in-depth: even a raw UPDATE that bypasses `advance`'s WHERE guard is aborted by the
        // BEFORE UPDATE trigger (COMPLETED is terminal; COMPLETED -> EXECUTING is not a legal edge).
        let conn = store();
        accept_prepare(&conn, &new_acceptance("att-1"), 10).unwrap();
        advance(&conn, "att-1", &Advance::LeaseReady { lease_handle: "l".into() }, 20).unwrap();
        advance(&conn, "att-1", &Advance::ExecutionStarting, 30).unwrap();
        advance(
            &conn,
            "att-1",
            &Advance::Executing {
                process_group_id: "pg".into(),
                cgroup_id: "cg".into(),
                execution_started_marker: None,
            },
            40,
        )
        .unwrap();
        advance(&conn, "att-1", &Advance::Completed { terminal_record_handle: "r".into() }, 50).unwrap();
        // Raw illegal write is aborted by the trigger.
        let err = conn.execute(
            "UPDATE governed_turn_acceptance SET state='EXECUTING' WHERE execution_attempt_id='att-1'",
            [],
        );
        assert!(err.is_err());
        assert_eq!(current_state(&conn, "att-1").unwrap(), Some(AcceptanceState::Completed));
    }
}
