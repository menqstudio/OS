//! The three trusted-principal dispatch cores — PURE, host-independent, `serde_json::Value` in/out. They are
//! the Rust twin of `engine/runtime/{challenge_authority,governed_supervisor,isolated_signer}.py`. Each
//! RECOMPUTES every digest it can and signs only its own attested facts; the bytes they sign are exactly what
//! `brops_core::governed_verification::verify_and_accept` verifies. A running Windows bin wraps one of these
//! behind a named pipe (peer-SID authed); the in-process test drives all three directly and asserts
//! `trusted_verified` — the same crypto, no transport.

use crate::crypto;
use brops_core::supervisor_ledger::{
    create_schema, evidence_floor_cas, EvidenceHead, LedgerError,
};
use rusqlite::Connection;
use serde_json::{json, Map, Value};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

/// A uniform dispatch seam so a transport (named pipe / in-process) can route a framed request to whichever
/// core it fronts without knowing the concrete type.
pub trait DispatchCore: Send + Sync {
    fn handle(&self, req: &Value, now_ms: i64) -> Value;
}

pub const CHALLENGE_PROTOCOL: &str = "brops.governed-turn-challenge.v1";
pub const ATTESTATION_PROTOCOL: &str = "brops.run-attestation.v1";
pub const SIGN_REQUEST_PROTOCOL: &str = "brops.sign-request.v1";
pub const ENVELOPE_ARTIFACT_TYPE: &str = "brops.governed-receipt-envelope.v1";

/// The id cap and the lease budget are the SAME constants the Linux broker and the durable ledger use —
/// re-exported from `brops-core`, not re-declared. They used to be three literals here, beside a doc
/// header calling this module "the Rust twin" of the Python principals; a twin that keeps its own copy of
/// the other twin's numbers is two implementations of one rule, and only one of them moves when the rule
/// does. `rustc` now refuses to let this file hold a different value: there is nowhere to put one.
pub use brops_core::governed_prepare::MAX_ID_LEN;
pub use brops_core::supervisor_ledger::{LEASE_DURATION_MS, MIN_LAUNCH_REMAINING_MS};

/// These three have no `brops-core` counterpart to be derived from — the challenge/pending TTLs and the
/// completion clock-skew allowance live only in the Python principals (`challenge_authority.py`), which
/// this crate cannot import. They are pinned against those Python constants by
/// `engine/tests/test_one_standard_pins.py`, which reads this file's source text; that is a weaker
/// mechanism than the `pub use` above and is used only where the stronger one does not exist.
pub const PENDING_TTL_MS: i64 = 30_000;
pub const CHALLENGE_TTL_MS: i64 = 30_000;
pub const COMPLETED_SKEW_MS: i64 = 60_000;

// ---- small validation helpers -----------------------------------------------------------------

fn refuse(op: &str, reason: &str) -> Value {
    json!({ "ok": false, "op": op, "reason": reason })
}

fn obj(v: &Value) -> Option<&Map<String, Value>> {
    v.as_object()
}

/// The object has EXACTLY these keys (no missing, no extra) — fail-closed shape check.
fn exact_keys(o: &Map<String, Value>, keys: &[&str]) -> bool {
    if o.len() != keys.len() {
        return false;
    }
    keys.iter().all(|k| o.contains_key(*k))
}

fn get_str(o: &Map<String, Value>, k: &str) -> Option<String> {
    o.get(k)?.as_str().map(str::to_string)
}
fn get_i64(o: &Map<String, Value>, k: &str) -> Option<i64> {
    o.get(k)?.as_i64()
}

fn is_hex64(s: &str) -> bool {
    s.len() == 64 && s.bytes().all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
}
fn id_ok(s: &str) -> bool {
    !s.is_empty() && s.len() <= MAX_ID_LEN
}

/// Read a content-addressed store blob by handle, verifying `sha256(content) == handle` (the store is
/// integrity-checked by content address, never by path/mode). Returns the bytes or None.
fn store_read(store_dir: &Path, handle: &str) -> Option<Vec<u8>> {
    if !is_hex64(handle) {
        return None;
    }
    let bytes = std::fs::read(store_dir.join(handle)).ok()?;
    if crypto::sha256_hex(&bytes) == handle {
        Some(bytes)
    } else {
        None
    }
}

// =================================================================================================
// Challenge-authority
// =================================================================================================

/// The 9 fixed create-pending facts (rejects any extra incl. a smuggled `request_sha256`).
const CREATE_PENDING_FIELDS: [&str; 9] = [
    "run_id",
    "task_id",
    "workspace_id",
    "install_id",
    "request_nonce",
    "system_sha256",
    "history_sha256",
    "generation_config_sha256",
    "requested_at_ms",
];

pub struct AuthorityConfig {
    pub challenge_key_id: String,
    pub supervisor_id: String,
    pub challenge_signing_seed: [u8; 32],
}

struct PendingRow {
    facts: Map<String, Value>,
    request_sha256: String,
    pending_expires_at_ms: i64,
    issued: Option<Value>, // the {payload, sig} once issued (replayed byte-for-byte)
}

pub struct Authority {
    cfg: AuthorityConfig,
    state: Mutex<AuthorityState>,
}
#[derive(Default)]
struct AuthorityState {
    pending: BTreeMap<String, PendingRow>,        // pending_challenge_id -> row
    by_nonce: BTreeMap<(String, String), String>, // (install_id, request_nonce) -> pending_challenge_id
    counter: u64,
}

impl Authority {
    pub fn new(cfg: AuthorityConfig) -> Self {
        Authority { cfg, state: Mutex::new(AuthorityState::default()) }
    }

    pub fn dispatch(&self, req: &Value, now_ms: i64) -> Value {
        let o = match obj(req) {
            Some(o) => o,
            None => return refuse("?", "malformed"),
        };
        match o.get("op").and_then(Value::as_str) {
            Some("create-pending") => self.create_pending(o, now_ms),
            Some("issue") => self.issue(o, now_ms),
            _ => refuse("?", "malformed"),
        }
    }

    fn create_pending(&self, o: &Map<String, Value>, now_ms: i64) -> Value {
        // op + the 9 fixed facts, nothing else.
        if o.len() != CREATE_PENDING_FIELDS.len() + 1
            || !CREATE_PENDING_FIELDS.iter().all(|k| o.contains_key(*k))
        {
            return refuse("create-pending", "malformed");
        }
        let ids = ["run_id", "task_id", "workspace_id", "install_id", "request_nonce"];
        for k in ids {
            match get_str(o, k) {
                Some(s) if id_ok(&s) => {}
                _ => return refuse("create-pending", "malformed"),
            }
        }
        for k in ["system_sha256", "history_sha256", "generation_config_sha256"] {
            match get_str(o, k) {
                Some(s) if is_hex64(&s) => {}
                _ => return refuse("create-pending", "malformed"),
            }
        }
        let requested_at_ms = match get_i64(o, "requested_at_ms") {
            Some(n) if n > 0 => n,
            _ => return refuse("create-pending", "malformed"),
        };
        let install_id = get_str(o, "install_id").unwrap();
        let request_nonce = get_str(o, "request_nonce").unwrap();

        // Recompute request_sha256 from the validated facts (requested_at = decimal string of the ms).
        let request_sha256 = crypto::request_sha256(
            &get_str(o, "workspace_id").unwrap(),
            &install_id,
            &request_nonce,
            &get_str(o, "system_sha256").unwrap(),
            &get_str(o, "history_sha256").unwrap(),
            &get_str(o, "generation_config_sha256").unwrap(),
            &requested_at_ms.to_string(),
        );

        let mut st = self.state.lock().unwrap();
        let nonce_key = (install_id.clone(), request_nonce.clone());
        // Idempotency: same (install_id, request_nonce) → same id iff facts identical; else retry_conflict.
        if let Some(existing_id) = st.by_nonce.get(&nonce_key).cloned() {
            if let Some(row) = st.pending.get(&existing_id) {
                if &row.facts == o {
                    let exp = row.pending_expires_at_ms;
                    return json!({
                        "ok": true, "op": "create-pending",
                        "pending_challenge_id": existing_id,
                        "pending_expires_at_ms": exp,
                    });
                }
                return refuse("create-pending", "retry_conflict");
            }
        }
        st.counter += 1;
        let pending_challenge_id = format!("pc-{}-{}", now_ms, st.counter);
        let pending_expires_at_ms = now_ms + PENDING_TTL_MS;
        st.pending.insert(
            pending_challenge_id.clone(),
            PendingRow {
                facts: o.clone(),
                request_sha256,
                pending_expires_at_ms,
                issued: None,
            },
        );
        st.by_nonce.insert(nonce_key, pending_challenge_id.clone());
        json!({
            "ok": true, "op": "create-pending",
            "pending_challenge_id": pending_challenge_id,
            "pending_expires_at_ms": pending_expires_at_ms,
        })
    }

    fn issue(&self, o: &Map<String, Value>, now_ms: i64) -> Value {
        let pending_id = match get_str(o, "pending_challenge_id") {
            Some(s) => s,
            None => return refuse("issue", "malformed"),
        };
        let mut st = self.state.lock().unwrap();
        let row = match st.pending.get_mut(&pending_id) {
            Some(r) => r,
            None => return refuse("issue", "no_pending_row"),
        };
        // Replay an already-issued challenge byte-for-byte.
        if let Some(issued) = &row.issued {
            return json!({ "ok": true, "op": "issue", "challenge": issued.clone() });
        }
        if now_ms > row.pending_expires_at_ms {
            return refuse("issue", "pending_expired");
        }
        let f = &row.facts;
        let requested_at_ms = get_i64(f, "requested_at_ms").unwrap();
        let issued_at = now_ms;
        let expires_at = now_ms + CHALLENGE_TTL_MS;
        // Build the 15-field challenge payload (bare integers for the *_ms fields).
        let mut payload = Map::new();
        payload.insert("protocol".into(), json!(CHALLENGE_PROTOCOL));
        payload.insert("challenge_key_id".into(), json!(self.cfg.challenge_key_id));
        payload.insert("run_id".into(), f["run_id"].clone());
        payload.insert("task_id".into(), f["task_id"].clone());
        payload.insert("workspace_id".into(), f["workspace_id"].clone());
        payload.insert("install_id".into(), f["install_id"].clone());
        payload.insert("supervisor_id".into(), json!(self.cfg.supervisor_id));
        payload.insert("request_nonce".into(), f["request_nonce"].clone());
        payload.insert("system_sha256".into(), f["system_sha256"].clone());
        payload.insert("history_sha256".into(), f["history_sha256"].clone());
        payload.insert("generation_config_sha256".into(), f["generation_config_sha256"].clone());
        payload.insert("request_sha256".into(), json!(row.request_sha256));
        payload.insert("requested_at_ms".into(), json!(requested_at_ms));
        payload.insert("challenge_issued_at_ms".into(), json!(issued_at));
        payload.insert("challenge_expires_at_ms".into(), json!(expires_at));

        let sig = crypto::sign_b64url(
            &crypto::signing_key(&self.cfg.challenge_signing_seed),
            &crypto::jcs(&payload),
        );
        let challenge = json!({ "payload": Value::Object(payload), "sig": sig });
        row.issued = Some(challenge.clone());
        json!({ "ok": true, "op": "issue", "challenge": challenge })
    }
}

// =================================================================================================
// Governed-supervisor
// =================================================================================================

const CHALLENGE_PAYLOAD_FIELDS: [&str; 15] = [
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
];

/// The 28 attest-run facts (== signer evidence minus `decision`) — the authoritative list mirrored from
/// `LinuxGovernedExecution` (chain_executor.rs). Any extra key fails closed.
const ATTEST_INPUT_FIELDS: [&str; 28] = [
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
    "policy_bundle_handle",
    "generation_config_handle",
    "system_handle",
    "history_handle",
    "output_handle",
    "containment_evidence_handle",
    "record_handle",
    "lease_handle",
    "execution_receipt_handle",
    "evidence_final_event_hash",
    "requested_at",
    "completed_at",
    "challenge_accepted_at_ms",
    "evidence_event_count",
    "evidence_last_sequence",
    "evidence_head_sequence",
];

/// The EXACT shape of `complete-run`'s `produced` object — the only §4.9 values the supervisor
/// cannot derive itself. Deliberately absent: every id, nonce, identity and acceptance timestamp
/// (F-01: the supervisor already owns those, and taking them here would re-open the oracle).
//
// (audit **F-01**/**F-02**, remediation audit) The four `evidence_*` values are GONE from the
// wire. They were deployment constants here — the original F-02 defect, alive on this platform
// after it had been marked CLOSED on the strength of the Linux fix. They decide the anti-rollback
// floor, so a caller that could name them could also choose the floor it was measured against.
// The supervisor now DERIVES them from the execution's own evidence chain, and refuses a
// completion whose `output_handle` is not the digest that chain recorded.
const COMPLETION_HANDLE_FIELDS: [&str; 2] = ["output_handle", "containment_evidence_handle"];
const COMPLETION_INT_FIELDS: [&str; 1] = ["completed_at_ms"];
const COMPLETION_FIELDS: [&str; 3] =
    ["output_handle", "containment_evidence_handle", "completed_at_ms"];

pub struct SupervisorConfig {
    pub supervisor_id: String,
    pub supervisor_attestation_key_id: String,
    pub challenge_public_key_hex: String,
    pub attest_signing_seed: [u8; 32],
    pub launcher_executable_sha256: String,
    pub executor_executable_sha256: String,
    // ---- the identity block the isolated signer ALLOWLISTS (independent audit F-01) ----
    // These used to reach the signed evidence through `attest-run {facts}` — i.e. the caller chose
    // the values its own allowlist check would be performed against. They are supervisor
    // provisioning now and cross no boundary.
    pub executor_id: String,
    pub builder_id: String,
    pub policy_id: String,
    pub policy_version: String,
    pub policy_bundle_handle: String,
    /// The content-addressed protected store this supervisor PUBLISHES its own terminal
    /// artifacts into (audit F-02) — the same store the isolated signer reads by handle.
    pub store_dir: PathBuf,
    /// Where the EXECUTION writes its per-run evidence chain (audit **F-01**). The supervisor
    /// reads it here rather than accepting the evidence head on the wire: in the cross-account
    /// deployment this directory belongs to the executor principal, so the broker cannot write
    /// what the supervisor is about to attest. In the in-process proof both sides are one
    /// process, which makes it a shape check there — said plainly rather than assumed.
    pub evidence_dir: PathBuf,
    /// The supervisor's OWN durable anti-rollback/anti-fork floor over the shared supervisor DDL
    /// (audit **R-42**/**R-24**). REQUIRED, not optional: an unconfigured floor must refuse, never
    /// pass. See [`Supervisor::new`].
    pub evidence_floor_db: PathBuf,
}

/// The evidence head DERIVED from the execution's chain, plus the reply digest it recorded
/// (audit **F-01**). `None` when the chain is absent or malformed — the caller fails closed.
struct DerivedEvidence {
    final_event_hash: String,
    event_count: i64,
    last_sequence: i64,
    head_sequence: i64,
    output_sha256: String,
}

/// Read + parse `brops.run-evidence-chain.v1` for one attempt. Byte-compatible with the Linux
/// recorder's chain, so both platforms derive the head the same way from the same document.
fn derive_evidence(dir: &std::path::Path, attempt: &str) -> Option<DerivedEvidence> {
    // The attempt id reaches the filesystem. It is supervisor-minted, but the supervisor does not
    // get to assume its own inputs — a traversal here would let a caller point at any file.
    if attempt.is_empty()
        || !attempt.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
    {
        return None;
    }
    let raw = std::fs::read(dir.join(format!("{attempt}.evidence.json"))).ok()?;
    if raw.len() > 1 << 20 {
        return None; // bounded: a hostile chain must not exhaust the supervisor
    }
    let chain: Value = serde_json::from_slice(&raw).ok()?;
    if chain.get("protocol").and_then(Value::as_str) != Some("brops.run-evidence-chain.v1") {
        return None;
    }
    let events = chain.get("events")?.as_array()?;
    let captured: Vec<&Value> = events
        .iter()
        .filter(|e| e.get("event_type").and_then(Value::as_str) == Some("output-captured"))
        .collect();
    if captured.len() != 1 {
        return None;
    }
    let payload = captured[0].get("payload")?;
    // The event commits to its payload by digest; check that before believing the payload.
    if crypto::sha256_hex(&serde_json::to_vec(payload).ok()?)
        != captured[0].get("payload_sha256").and_then(Value::as_str)?
    {
        return None;
    }
    let i = |k: &str| -> Option<i64> { chain.get(k)?.as_i64().filter(|n| *n > 0) };
    let derived = DerivedEvidence {
        final_event_hash: chain.get("final_event_hash")?.as_str()?.to_string(),
        event_count: i("event_count")?,
        last_sequence: i("last_sequence")?,
        head_sequence: i("head_sequence")?,
        output_sha256: payload.get("output_sha256")?.as_str()?.to_string(),
    };
    if derived.event_count != derived.last_sequence || derived.event_count as usize != events.len()
    {
        return None;
    }
    Some(derived)
}

/// The run-produced half of the §4.9 evidence, reported ONCE via `complete-run`.
///
/// `record_handle` / `lease_handle` / `execution_receipt_handle` are NOT here: the supervisor
/// derives and publishes those itself (F-02), so a caller cannot name them.
#[derive(Clone, Debug, PartialEq, Eq)]
struct Completion {
    output_handle: String,
    containment_evidence_handle: String,
    record_handle: String,
    lease_handle: String,
    execution_receipt_handle: String,
    completed_at_ms: i64,
    evidence_final_event_hash: String,
    evidence_event_count: i64,
    evidence_last_sequence: i64,
    evidence_head_sequence: i64,
}

/// The supervisor's OWN record of one accepted governed turn — the state a run attestation is
/// rebuilt from. Every field is copied out of the signature-verified challenge payload or stamped
/// by the supervisor itself; none is taken from a later caller message.
struct Acceptance {
    run_id: String,
    task_id: String,
    workspace_id: String,
    install_id: String,
    request_nonce: String,
    requested_at_ms: i64,
    challenge_accepted_at_ms: i64,
    system_handle: String,
    history_handle: String,
    generation_config_handle: String,
    receipt_id: String,
    lease_id: String,
    lease_issued_at_ms: i64,
    lease_expires_at_ms: i64,
    lease_payload_bytes: Vec<u8>,
    challenge_handle: String,
    request_sha256: String,
    /// The id of the executed process — EMPTY unless the execution actually observed one running
    /// (audit **IDX-28/IDX-91**). It used to be filled unconditionally from whatever the caller
    /// sent, which on this kit was the driver's own pid.
    process_group_id: String,
    /// WHICH of the closed set of process observations the execution reported. This is the field
    /// that makes `process_group_id` readable: an empty pid beside `driver-process` is an honest
    /// account, an empty pid with no kind beside it is just a hole.
    process_observation: String,
    /// The supervisor's OWN clock at the `execution-started` transition. A completion timestamped
    /// before it is refused, which is only a meaningful check because the execution now reports
    /// the start BEFORE it runs the producer rather than after it exited.
    execution_started_at_ms: i64,
    state: &'static str,
    completion: Option<Completion>,
}

// ---- §5 process-observation reporting (audit IDX-28 / IDX-91) ----------------------------------

/// A separate process was spawned AND this execution held it while it ran, so the reported id is
/// that process's.
pub const OBSERVATION_OBSERVED_CHILD: &str = "observed-child";
/// A separate process is spawned somewhere inside the producer, but this execution never held a
/// handle to it: nothing here confirms it was running and no process id is known.
pub const OBSERVATION_UNOBSERVED_CHILD: &str = "unobserved-child";
/// The reply is produced INSIDE the driver process. There is no separate child at all.
pub const OBSERVATION_IN_DRIVER: &str = "driver-process";

/// PURE — the §5 `execution-started` report the supervisor will accept.
///
/// **audit IDX-28 / IDX-91.** The transition is documented as `EXECUTION_STARTING → EXECUTING on
/// confirmed running process metadata`. On this kit it was neither confirmed nor running: the
/// report was sent AFTER the executor had already exited and carried the DRIVER's own pid, which
/// the supervisor then baked into a signed `brops.execution-receipt.v1` as `process_group_id` —
/// a document that reads as an account of a supervised child.
///
/// So the kind of observation is now named from a CLOSED set, and a process id may accompany
/// exactly the one kind that actually observed a process. An observation that watched nothing can
/// no longer carry a pid, which is precisely how the driver's pid used to get in.
fn admit_process_report(observation: &str, process_id: &str) -> Result<(), &'static str> {
    match observation {
        OBSERVATION_OBSERVED_CHILD => {
            if process_id.is_empty() || !id_ok(process_id) {
                // Claiming to have observed the child and then naming nothing is not an
                // observation; refuse rather than record an empty one under that kind.
                Err("process_id_missing")
            } else {
                Ok(())
            }
        }
        OBSERVATION_UNOBSERVED_CHILD | OBSERVATION_IN_DRIVER => {
            if process_id.is_empty() {
                Ok(())
            } else {
                // The defect, stated as a rule: a report that observed no process must not name
                // one. This is what stopped `std::process::id()` from being attested as the
                // executed child.
                Err("process_id_not_observed")
            }
        }
        _ => Err("process_observation_unknown"),
    }
}

/// The write-once admission decision for a completion — PURE, so the Linux CI runner covers it.
#[derive(Debug, PartialEq, Eq)]
enum CompletionAdmission {
    /// First completion for this attempt: publish the terminal artifacts, then record it.
    Accept,
    /// A byte-identical retry of a completion already published and recorded.
    Idempotent,
    Refuse(&'static str),
}

/// **audit IDX-121 (gate-blocking).** The supervisor used to PUBLISH its three terminal artifacts —
/// record, lease, execution receipt — into the protected store and only THEN consult the state
/// machine. A refused `complete-run` therefore still planted a `brops.governed-turn-record.v1`
/// asserting `"decision":"completed"` into the very store the isolated signer reads by handle, for
/// an attempt the supervisor had just declined to complete.
///
/// The decision is a VALUE now, computed before anything reaches the filesystem; only `Accept`
/// publishes. The order is the check.
fn admit_completion(
    state: &str,
    execution_started_at_ms: i64,
    existing: Option<&Completion>,
    proposed: &Completion,
) -> CompletionAdmission {
    match existing {
        // Write-once: an identical retry is idempotent, any divergence is refused. A second
        // execution cannot rewrite what was already attested.
        Some(e) if e == proposed => CompletionAdmission::Idempotent,
        Some(_) => CompletionAdmission::Refuse("completion_conflict"),
        None if state != ST_EXECUTING => CompletionAdmission::Refuse("illegal_state"),
        // A run cannot have finished before the supervisor observed it start. This is only a real
        // check because `execution-started` is now reported BEFORE the producer runs (IDX-28).
        None if proposed.completed_at_ms < execution_started_at_ms => {
            CompletionAdmission::Refuse("completed_before_execution_started")
        }
        None => CompletionAdmission::Accept,
    }
}

const ST_LEASE_READY: &str = "LEASE_READY";
const ST_EXECUTION_STARTING: &str = "EXECUTION_STARTING";
const ST_EXECUTING: &str = "EXECUTING";
const ST_COMPLETED: &str = "COMPLETED";
const ST_EXPIRED: &str = "EXPIRED";

pub struct Supervisor {
    cfg: SupervisorConfig,
    counter: Mutex<u64>,
    /// The supervisor's acceptance state, keyed by `execution_attempt_id`.
    ///
    /// **F-01.** This replaces a bare set of issued attempt ids. Holding only the ids let
    /// `attest-run` bind to a real lease while still SIGNING the evidence the caller supplied with
    /// it — so a party able to obtain any lease could still describe the run however it liked. The
    /// supervisor now holds the run's identity, request binding, lease window and terminal
    /// completion, and builds the evidence itself. A run it never accepted has no record, and no
    /// request field exists through which the missing facts could be supplied.
    ///
    /// (Proof-kit scope: this state is in-process, matching the rest of the Windows machine-proof.
    /// The production Linux supervisor keeps the equivalent state in a durable SQLite ledger over
    /// the shared DDL — `engine/runtime/supervisor_ledger.sql`.)
    accepted: Mutex<BTreeMap<String, Acceptance>>,
    /// challenge content-address → the attempt it already minted, so a replayed signed challenge
    /// returns the ORIGINAL lease instead of a second execution attempt.
    by_challenge: Mutex<BTreeMap<String, String>>,
    /// **audit R-42 / R-24 — the ledger floor Windows did not have.**
    ///
    /// Everything else this supervisor knows is per-attempt and lives in `accepted`, an in-process
    /// `BTreeMap` keyed by `execution_attempt_id`. Nothing was ever compared ACROSS runs, so a
    /// deployment could complete turn A at head 100 and then turn B at head 1 and the second was
    /// attested and signed without objection — on the only platform the desktop actually ships on,
    /// while `AUDIT_LEDGER.md` described the anti-rollback floor as running "on every `complete-run`"
    /// with no platform qualifier.
    ///
    /// This is that floor: `brops_core::supervisor_ledger`'s durable
    /// [`evidence_floor_cas`], the SAME implementation and the same `BEGIN IMMEDIATE` CAS the Linux
    /// supervisor uses, over the same shared DDL. It is durable on purpose — an in-process floor
    /// would be defeated by restarting the supervisor, which is cheaper than beating it.
    ///
    /// It also gives `brops_core::supervisor_ledger` a real non-test caller from this crate, which
    /// R-24 recorded it as having none of.
    floor: Mutex<Connection>,
}

impl Supervisor {
    /// Open the supervisor's durable floor and build the core.
    ///
    /// Fallible ON PURPOSE. A floor that cannot be opened must stop the supervisor existing, not
    /// degrade to "no floor configured" — the whole class of defect this repository keeps finding is
    /// a control that quietly stops applying. There is no `Option<PathBuf>` and no in-memory
    /// fallback: the only way to run without a floor is to not run.
    pub fn new(cfg: SupervisorConfig) -> Result<Self, String> {
        if cfg.evidence_floor_db.as_os_str().is_empty() {
            return Err("supervisor: evidence_floor_db is required (the anti-rollback floor is not optional)".to_string());
        }
        if let Some(parent) = cfg.evidence_floor_db.parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent).map_err(|e| {
                    format!("supervisor: evidence floor directory unusable at {}: {e}", parent.display())
                })?;
            }
        }
        let conn = Connection::open(&cfg.evidence_floor_db).map_err(|e| {
            format!("supervisor: evidence floor unavailable at {}: {e}", cfg.evidence_floor_db.display())
        })?;
        create_schema(&conn)
            .map_err(|e| format!("supervisor: evidence floor schema unavailable: {e:?}"))?;
        Ok(Supervisor {
            cfg,
            counter: Mutex::new(0),
            accepted: Mutex::new(BTreeMap::new()),
            by_challenge: Mutex::new(BTreeMap::new()),
            floor: Mutex::new(conn),
        })
    }

    pub fn dispatch(&self, req: &Value, now_ms: i64) -> Value {
        let o = match obj(req) {
            Some(o) => o,
            None => return refuse("?", "malformed"),
        };
        match o.get("op").and_then(Value::as_str) {
            Some("accept-open") => self.accept_open(o, now_ms),
            Some("launch-gate") => self.launch_gate(o, now_ms),
            Some("execution-started") => self.execution_started(o, now_ms),
            Some("complete-run") => self.complete_run(o, now_ms),
            Some("attest-run") => self.attest_run(o),
            _ => refuse("?", "malformed"),
        }
    }

    /// The lease object for an attempt, rebuilt from the supervisor's own record.
    fn lease_json(&self, attempt: &str, a: &Acceptance) -> Value {
        json!({
            "lease_id": a.lease_id,
            "execution_attempt_id": attempt,
            "lease_expires_at_ms": a.lease_expires_at_ms,
            "launcher_executable_sha256": self.cfg.launcher_executable_sha256,
            "executor_executable_sha256": self.cfg.executor_executable_sha256,
        })
    }

    fn accept_open(&self, o: &Map<String, Value>, now_ms: i64) -> Value {
        let doc = match o.get("challenge_doc").and_then(Value::as_object) {
            Some(d) => d,
            None => return refuse("accept-open", "malformed"),
        };
        if !exact_keys(doc, &["payload", "sig"]) {
            return refuse("accept-open", "malformed");
        }
        let payload = match doc.get("payload").and_then(Value::as_object) {
            Some(p) => p,
            None => return refuse("accept-open", "malformed"),
        };
        let sig_b64 = match doc.get("sig").and_then(Value::as_str) {
            Some(s) => s,
            None => return refuse("accept-open", "malformed"),
        };
        if !exact_keys(payload, &CHALLENGE_PAYLOAD_FIELDS) {
            return refuse("accept-open", "malformed");
        }
        if payload.get("protocol").and_then(Value::as_str) != Some(CHALLENGE_PROTOCOL) {
            return refuse("accept-open", "malformed");
        }
        for k in ["system_sha256", "history_sha256", "generation_config_sha256", "request_sha256"] {
            match get_str(payload, k) {
                Some(s) if is_hex64(&s) => {}
                _ => return refuse("accept-open", "malformed"),
            }
        }
        // Type-check the three identity fields too, so the get_str(...).unwrap() in the
        // request_sha256 recompute below can never panic on a non-string (e.g. `"workspace_id": 1`).
        // The core re-validates its own inputs and fails CLOSED rather than trusting that the upstream
        // signer only ever emits string identities.
        for k in ["workspace_id", "install_id", "request_nonce"] {
            if get_str(payload, k).is_none() {
                return refuse("accept-open", "malformed");
            }
        }
        let issued_at = match get_i64(payload, "challenge_issued_at_ms") {
            Some(n) => n,
            None => return refuse("accept-open", "malformed"),
        };
        let expires_at = match get_i64(payload, "challenge_expires_at_ms") {
            Some(n) => n,
            None => return refuse("accept-open", "malformed"),
        };
        if expires_at <= issued_at || expires_at - issued_at > CHALLENGE_TTL_MS {
            return refuse("accept-open", "malformed");
        }
        // Phase A — signature over the supervisor-reassembled canonical payload bytes.
        if !crypto::verify_ed25519_hex(&self.cfg.challenge_public_key_hex, &crypto::jcs(payload), sig_b64) {
            return refuse("accept-open", "signature_invalid");
        }
        // Phase B — freshness + request_sha256 recompute must equal the signed value.
        if now_ms > expires_at {
            return refuse("accept-open", "challenge_expired");
        }
        let requested_at_ms = match get_i64(payload, "requested_at_ms") {
            Some(n) => n,
            None => return refuse("accept-open", "malformed"),
        };
        let recomputed = crypto::request_sha256(
            &get_str(payload, "workspace_id").unwrap(),
            &get_str(payload, "install_id").unwrap(),
            &get_str(payload, "request_nonce").unwrap(),
            &get_str(payload, "system_sha256").unwrap(),
            &get_str(payload, "history_sha256").unwrap(),
            &get_str(payload, "generation_config_sha256").unwrap(),
            &requested_at_ms.to_string(),
        );
        if recomputed != get_str(payload, "request_sha256").unwrap() {
            return refuse("accept-open", "request_sha256_mismatch");
        }
        // Phase C — the challenge must be addressed to THIS supervisor. Authentic for another
        // supervisor is not authorization for this one to lease and attest it (F-01).
        if get_str(payload, "supervisor_id").as_deref() != Some(self.cfg.supervisor_id.as_str()) {
            return refuse("accept-open", "supervisor_mismatch");
        }

        // A replay of the SAME signed challenge returns the ORIGINAL lease. The supervisor's own
        // content address of the exact signed DOCUMENT it just verified is the key, so a caller
        // cannot obtain a second execution attempt by resubmitting.
        //
        // rev-30 correction (2026-08-10): this hashed `jcs(payload)` -- the payload ALONE -- which
        // was the half of rev-30 that lost. The normative form is `SHA256(JCS({payload, sig}))`
        // (rev-30 section 3 artifact matrix, 4.10(a0), Appendix B handle matrix); the payload-only
        // form appeared only in section 5's summary table, which merely described the shipped code
        // and is now corrected. `doc` is exactly `{payload, sig}` (exact_keys above), and jcs sorts
        // keys, so this is byte-identical to what the Python supervisor and the 4.10(a0) staging
        // path compute. See engine/runtime/governed_supervisor.py::challenge_handle_for.
        let challenge_handle = crypto::sha256_hex(&crypto::jcs(doc));
        if let Some(existing) = self.by_challenge.lock().unwrap().get(&challenge_handle).cloned() {
            let accepted = self.accepted.lock().unwrap();
            if let Some(a) = accepted.get(&existing) {
                return json!({
                    "ok": true, "op": "accept-open", "lease": self.lease_json(&existing, a)
                });
            }
        }

        // Mint the lease — launcher/executor digests are the supervisor's OWN config, never the wire.
        let mut c = self.counter.lock().unwrap();
        *c += 1;
        let execution_attempt_id = format!("EA-{}-{}", now_ms, *c);
        let acceptance = Acceptance {
            run_id: get_str(payload, "run_id").unwrap_or_default(),
            task_id: get_str(payload, "task_id").unwrap_or_default(),
            workspace_id: get_str(payload, "workspace_id").unwrap(),
            install_id: get_str(payload, "install_id").unwrap(),
            request_nonce: get_str(payload, "request_nonce").unwrap(),
            requested_at_ms,
            challenge_accepted_at_ms: now_ms,
            system_handle: get_str(payload, "system_sha256").unwrap(),
            history_handle: get_str(payload, "history_sha256").unwrap(),
            generation_config_handle: get_str(payload, "generation_config_sha256").unwrap(),
            // Minted per turn by the supervisor: the §7.1(d) replay key must not be a deployment
            // constant (audit F-02).
            receipt_id: format!("R-{}-{}", now_ms, *c),
            lease_id: format!("L-{}-{}", now_ms, *c),
            lease_issued_at_ms: now_ms,
            lease_expires_at_ms: now_ms + LEASE_DURATION_MS,
            lease_payload_bytes: Vec::new(), // filled below from the exact lease object
            challenge_handle: challenge_handle.clone(),
            request_sha256: get_str(payload, "request_sha256").unwrap(),
            process_group_id: String::new(),
            process_observation: String::new(),
            execution_started_at_ms: 0,
            state: ST_LEASE_READY,
            completion: None,
        };
        let lease = self.lease_json(&execution_attempt_id, &acceptance);
        // Persist the EXACT canonical lease bytes: their content address is the `lease_handle`
        // the supervisor publishes at completion (F-02), so the receipt names the real lease.
        let mut acceptance = acceptance;
        acceptance.lease_payload_bytes = crypto::jcs(lease.as_object().unwrap());
        self.by_challenge
            .lock()
            .unwrap()
            .insert(challenge_handle, execution_attempt_id.clone());
        self.accepted.lock().unwrap().insert(execution_attempt_id, acceptance);
        json!({ "ok": true, "op": "accept-open", "lease": lease })
    }

    /// The §5 step-8a gate, BY ATTEMPT ID. The caller no longer hands back the lease it is judged
    /// against (audit F-23) — the supervisor reads the window it stamped at acceptance and moves the
    /// attempt forward, or durably EXPIREs it.
    fn launch_gate(&self, o: &Map<String, Value>, now_ms: i64) -> Value {
        if !exact_keys(o, &["op", "execution_attempt_id"]) {
            return refuse("launch-gate", "malformed");
        }
        let attempt = match get_str(o, "execution_attempt_id") {
            Some(s) => s,
            None => return refuse("launch-gate", "malformed"),
        };
        let mut accepted = self.accepted.lock().unwrap();
        let a = match accepted.get_mut(&attempt) {
            Some(a) => a,
            None => return refuse("launch-gate", "unknown_attempt"),
        };
        if a.state != ST_LEASE_READY {
            return refuse("launch-gate", "illegal_state");
        }
        if now_ms + MIN_LAUNCH_REMAINING_MS > a.lease_expires_at_ms {
            a.state = ST_EXPIRED;
            return refuse("launch-gate", "lease_expired");
        }
        a.state = ST_EXECUTION_STARTING;
        json!({ "ok": true, "op": "launch-gate", "proceed": true, "execution_attempt_id": attempt })
    }

    /// `EXECUTION_STARTING → EXECUTING` on the execution's process report.
    ///
    /// **audit IDX-28 / IDX-91.** The docstring used to say "on confirmed-running process
    /// metadata" and record whatever `process_group_id` / `cgroup_id` the caller sent. On this kit
    /// that was the driver's own pid and the literal string `win-live` (there are no cgroups on
    /// Windows), reported after the executor had already exited. The report now names WHICH kind of
    /// observation it is, from a closed set, and [`admit_process_report`] refuses a process id from
    /// a kind that observed no process.
    fn execution_started(&self, o: &Map<String, Value>, now_ms: i64) -> Value {
        if !exact_keys(
            o,
            &["op", "execution_attempt_id", "process_observation", "process_id",
              "execution_started_marker"],
        ) {
            return refuse("execution-started", "malformed");
        }
        let attempt = match get_str(o, "execution_attempt_id") {
            Some(s) => s,
            None => return refuse("execution-started", "malformed"),
        };
        let observation = match get_str(o, "process_observation") {
            Some(s) => s,
            None => return refuse("execution-started", "malformed"),
        };
        let process_id = match get_str(o, "process_id") {
            Some(s) => s,
            None => return refuse("execution-started", "malformed"),
        };
        if let Err(reason) = admit_process_report(&observation, &process_id) {
            return refuse("execution-started", reason);
        }
        let mut accepted = self.accepted.lock().unwrap();
        let a = match accepted.get_mut(&attempt) {
            Some(a) => a,
            None => return refuse("execution-started", "unknown_attempt"),
        };
        if a.state != ST_EXECUTION_STARTING {
            return refuse("execution-started", "illegal_state");
        }
        // Durably record what the execution reported, INCLUDING the kind of report it was: this is
        // what the execution receipt published at completion is built from (F-02), and it must
        // read as what it is rather than as a supervised child.
        a.process_group_id = process_id;
        a.process_observation = observation;
        a.execution_started_at_ms = now_ms;
        a.state = ST_EXECUTING;
        json!({ "ok": true, "op": "execution-started", "execution_attempt_id": attempt })
    }

    /// The WRITE-ONCE record of what the run produced. `produced` carries ONLY run-produced values —
    /// every id, nonce, identity and acceptance timestamp is an unknown field, because the supervisor
    /// already holds those and accepting them here would re-open F-01 through a second door.
    fn complete_run(&self, o: &Map<String, Value>, now_ms: i64) -> Value {
        if !exact_keys(o, &["op", "execution_attempt_id", "produced"]) {
            return refuse("complete-run", "malformed");
        }
        let attempt = match get_str(o, "execution_attempt_id") {
            Some(s) => s,
            None => return refuse("complete-run", "malformed"),
        };
        let p = match o.get("produced").and_then(Value::as_object) {
            Some(p) => p,
            None => return refuse("complete-run", "malformed"),
        };
        if !exact_keys(p, &COMPLETION_FIELDS) {
            return refuse("complete-run", "malformed");
        }
        for k in COMPLETION_HANDLE_FIELDS {
            match get_str(p, k) {
                Some(s) if is_hex64(&s) => {}
                _ => return refuse("complete-run", "malformed"),
            }
        }
        let mut ints = [0i64; 4];
        for (i, k) in COMPLETION_INT_FIELDS.iter().enumerate() {
            match get_i64(p, k) {
                Some(n) if n >= 0 => ints[i] = n,
                _ => return refuse("complete-run", "malformed"),
            }
        }
        let mut accepted = self.accepted.lock().unwrap();
        let a = match accepted.get_mut(&attempt) {
            Some(a) => a,
            None => return refuse("complete-run", "unknown_attempt"),
        };

        // F-02: the supervisor BUILDS its terminal artifacts from its own record and PUBLISHES
        // them to the protected store, then names their content addresses. These were previously
        // deployment-static constants the execution passed in, which made the isolated signer's
        // protected-chain check a tautology over bytes the provisioner had written once.
        let output_handle = get_str(p, "output_handle").unwrap();
        let containment_evidence_handle = get_str(p, "containment_evidence_handle").unwrap();

        // (audit F-01) Read the EXECUTION's evidence chain and derive the head from it. Refuse
        // outright when the reply digest the completion reports is not the one the chain
        // recorded: that is the reply the desktop is about to commit, and attesting a digest the
        // supervisor never observed is the oracle in its most valuable form.
        let evidence = match derive_evidence(&self.cfg.evidence_dir, &attempt) {
            Some(e) => e,
            None => return refuse("complete-run", "malformed_state"),
        };
        if evidence.output_sha256 != output_handle {
            return refuse("complete-run", "evidence_mismatch");
        }
        let evidence_final_event_hash = evidence.final_event_hash.clone();
        let record_bytes = crypto::jcs(
            json!({
                "protocol": "brops.governed-turn-record.v1",
                "run_id": a.run_id, "task_id": a.task_id,
                "execution_attempt_id": attempt,
                "workspace_id": a.workspace_id, "install_id": a.install_id,
                "request_nonce": a.request_nonce, "receipt_id": a.receipt_id,
                "supervisor_id": self.cfg.supervisor_id,
                "request_sha256": a.request_sha256,
                "system_handle": a.system_handle, "history_handle": a.history_handle,
                "generation_config_handle": a.generation_config_handle,
                "output_handle": output_handle,
                "containment_evidence_handle": containment_evidence_handle,
                "challenge_handle": a.challenge_handle,
                "requested_at_ms": a.requested_at_ms,
                "challenge_accepted_at_ms": a.challenge_accepted_at_ms,
                "completed_at_ms": ints[0],
                "decision": "completed",
            })
            .as_object()
            .unwrap(),
        );
        let receipt_bytes = crypto::jcs(
            json!({
                "protocol": "brops.execution-receipt.v1",
                "run_id": a.run_id, "execution_attempt_id": attempt,
                "lease_id": a.lease_id,
                "lease_issued_at_ms": a.lease_issued_at_ms,
                "lease_expires_at_ms": a.lease_expires_at_ms,
                // IDX-28/IDX-91: `process_group_id` is EMPTY unless a process was actually
                // observed, and `process_observation` says which kind of report this was. The
                // `cgroup_id` key is kept for shape-parity with the Linux twin's
                // `brops.execution-receipt.v1` and is always empty here: Windows has no cgroups,
                // and the constant `"win-live"` that used to sit in it named nothing.
                "process_group_id": a.process_group_id,
                "process_observation": a.process_observation,
                "cgroup_id": "",
                "execution_started_at_ms": a.execution_started_at_ms,
                "completed_at_ms": ints[0], "output_handle": output_handle,
            })
            .as_object()
            .unwrap(),
        );

        // IDX-121: content-address the three artifacts WITHOUT writing them. Nothing reaches the
        // protected store until the state machine has accepted this completion.
        let completion = Completion {
            record_handle: crypto::sha256_hex(&record_bytes),
            lease_handle: crypto::sha256_hex(&a.lease_payload_bytes),
            execution_receipt_handle: crypto::sha256_hex(&receipt_bytes),
            output_handle,
            containment_evidence_handle,
            completed_at_ms: ints[0],
            // F-01: the evidence head comes from the chain the supervisor read, never the wire.
            evidence_final_event_hash,
            evidence_event_count: evidence.event_count,
            evidence_last_sequence: evidence.last_sequence,
            evidence_head_sequence: evidence.head_sequence,
        };

        // IDX-121: DECIDE FIRST. A refusal must leave the store exactly as it found it — a
        // published record asserting `"decision":"completed"` for an attempt the supervisor
        // declined is the artifact the isolated signer resolves handles against.
        match admit_completion(a.state, a.execution_started_at_ms, a.completion.as_ref(), &completion)
        {
            CompletionAdmission::Refuse(reason) => return refuse("complete-run", reason),
            CompletionAdmission::Idempotent => {
                return json!({
                    "ok": true, "op": "complete-run", "execution_attempt_id": attempt,
                    "recorded": "idempotent"
                })
            }
            CompletionAdmission::Accept => {}
        }

        // ---- audit R-42: the CROSS-RUN anti-rollback/anti-fork floor -----------------------------
        //
        // Everything above this line is about ONE attempt. `derive_evidence` proves the head belongs
        // to a chain this execution really wrote and that the reply digest is the one it recorded —
        // but a genuinely-written, genuinely-signed OLDER chain re-presented on a later turn satisfies
        // every one of those checks. `head_sequence` is the only field that orders two runs, and until
        // this call nothing on Windows compared it to anything.
        //
        // Placed AFTER `admit_completion` and BEFORE `publish` on purpose:
        //   * after, so a refused completion cannot burn a head sequence (advancing the floor on a
        //     turn the state machine declined would be a denial-of-service the caller controls);
        //   * before, so a head the floor rejects never reaches the store the isolated signer reads.
        // An `Idempotent` retry returned above never gets here: its head was recorded on the first
        // pass, and `evidence_floor_cas` would call it `Idempotent` too.
        let head = EvidenceHead {
            install_id: a.install_id.clone(),
            task_id: a.task_id.clone(),
            head_sequence: completion.evidence_head_sequence,
            event_count: completion.evidence_event_count,
            last_sequence: completion.evidence_last_sequence,
            final_event_hash: completion.evidence_final_event_hash.clone(),
        };
        {
            let conn = match self.floor.lock() {
                Ok(c) => c,
                // A poisoned floor is an unusable floor. Refusing is the only honest outcome.
                Err(_) => return refuse("complete-run", "evidence_floor_unavailable"),
            };
            match evidence_floor_cas(&conn, &head, now_ms) {
                Ok(_) => {}
                // The head is below one this install has already attested: an older chain,
                // re-presented. This is the rollback the floor exists for.
                Err(LedgerError::StaleEvidence) => {
                    return refuse("complete-run", "stale_evidence")
                }
                // Same head sequence, different content — one install has one counter, so the same
                // number cannot legitimately be minted twice.
                Err(LedgerError::EvidenceFork) => return refuse("complete-run", "evidence_fork"),
                Err(LedgerError::InvalidHead(_)) => {
                    return refuse("complete-run", "evidence_head_invalid")
                }
                // A floor that cannot decide refuses; it never waves the turn through.
                Err(_) => return refuse("complete-run", "evidence_floor_unavailable"),
            }
        }

        // ACCEPTED — only now do the artifacts become visible to the signer.
        let publish = |bytes: &[u8], handle: &str| -> bool {
            let path = self.cfg.store_dir.join(handle);
            path.exists() || std::fs::write(&path, bytes).is_ok()
        };
        if !publish(&record_bytes, &completion.record_handle)
            || !publish(&a.lease_payload_bytes, &completion.lease_handle)
            || !publish(&receipt_bytes, &completion.execution_receipt_handle)
        {
            // A store failure must refuse the completion, never name a handle nothing holds — and
            // must not advance the state machine on a run whose artifacts are not all there.
            return refuse("complete-run", "artifact_publish_failed");
        }
        a.completion = Some(completion);
        a.state = ST_COMPLETED;
        json!({
            "ok": true, "op": "complete-run", "execution_attempt_id": attempt, "recorded": "created"
        })
    }

    /// **F-01.** `attest-run` NAMES the run; it never describes it. The request carries only
    /// `{run_id, execution_attempt_id}` — the old `facts` object does not exist, and because the
    /// shape check is exhaustive an old-protocol caller gets a hard refusal rather than an
    /// attestation over evidence it chose. The evidence is assembled from the supervisor's own
    /// terminal record plus its own provisioning, so a run it did not accept, gate, watch start and
    /// record as completed has nothing to attest.
    fn attest_run(&self, o: &Map<String, Value>) -> Value {
        if !exact_keys(o, &["op", "run_id", "execution_attempt_id"]) {
            return refuse("attest-run", "malformed");
        }
        let run_id = match get_str(o, "run_id") {
            Some(s) if id_ok(&s) => s,
            _ => return refuse("attest-run", "malformed"),
        };
        let attempt = match get_str(o, "execution_attempt_id") {
            Some(s) if id_ok(&s) => s,
            _ => return refuse("attest-run", "malformed"),
        };

        let accepted = self.accepted.lock().unwrap();
        let a = match accepted.get(&attempt) {
            Some(a) => a,
            None => return refuse("attest-run", "no_terminal_run_state"),
        };
        if a.run_id != run_id || a.state != ST_COMPLETED {
            return refuse("attest-run", "no_terminal_run_state");
        }
        let c = match &a.completion {
            Some(c) => c,
            None => return refuse("attest-run", "no_terminal_run_state"),
        };

        // Assemble the §4.9 evidence: the acceptance row (written from the SIGNED challenge), the
        // write-once completion, and the supervisor's OWN provisioned identities.
        let mut evidence = Map::new();
        for (k, v) in [
            ("run_id", a.run_id.clone()),
            ("execution_attempt_id", attempt.clone()),
            ("task_id", a.task_id.clone()),
            ("request_nonce", a.request_nonce.clone()),
            ("receipt_id", a.receipt_id.clone()),
            ("workspace_id", a.workspace_id.clone()),
            ("install_id", a.install_id.clone()),
            ("supervisor_id", self.cfg.supervisor_id.clone()),
            ("executor_id", self.cfg.executor_id.clone()),
            ("builder_id", self.cfg.builder_id.clone()),
            ("policy_id", self.cfg.policy_id.clone()),
            ("policy_version", self.cfg.policy_version.clone()),
            ("policy_bundle_handle", self.cfg.policy_bundle_handle.clone()),
            ("generation_config_handle", a.generation_config_handle.clone()),
            ("system_handle", a.system_handle.clone()),
            ("history_handle", a.history_handle.clone()),
            ("output_handle", c.output_handle.clone()),
            ("containment_evidence_handle", c.containment_evidence_handle.clone()),
            ("record_handle", c.record_handle.clone()),
            ("lease_handle", c.lease_handle.clone()),
            ("execution_receipt_handle", c.execution_receipt_handle.clone()),
            ("evidence_final_event_hash", c.evidence_final_event_hash.clone()),
        ] {
            evidence.insert(k.into(), json!(v));
        }
        for (k, v) in [
            ("requested_at", a.requested_at_ms),
            ("completed_at", c.completed_at_ms),
            ("challenge_accepted_at_ms", a.challenge_accepted_at_ms),
            ("evidence_event_count", c.evidence_event_count),
            ("evidence_last_sequence", c.evidence_last_sequence),
            ("evidence_head_sequence", c.evidence_head_sequence),
        ] {
            evidence.insert(k.into(), json!(v));
        }
        // Defence in depth: the assembled object must still be exactly the signer's input shape, so
        // a supervisor-side assembly bug fails closed instead of signing malformed bytes.
        if !exact_keys(&evidence, &ATTEST_INPUT_FIELDS) {
            return refuse("attest-run", "malformed");
        }
        // Stamp decision=completed, JCS it, sign THOSE bytes.
        evidence.insert("decision".into(), json!("completed"));
        let evidence_jcs = crypto::jcs(&evidence);
        let sig = crypto::sign_b64url(&crypto::signing_key(&self.cfg.attest_signing_seed), &evidence_jcs);
        json!({
            "ok": true, "op": "attest-run",
            "attestation": {
                "attestation_protocol": ATTESTATION_PROTOCOL,
                "supervisor_key_id": self.cfg.supervisor_attestation_key_id,
                "sig": sig,
            },
            "evidence_jcs_b64": crypto::b64url(&evidence_jcs),
            "attestation_evidence_sha256": crypto::sha256_hex(&evidence_jcs),
        })
    }
}

// =================================================================================================
// Isolated-signer
// =================================================================================================

const EVIDENCE_FIELDS_LEN: usize = 29; // 28 attest facts + decision

/// The refusal prefix for a protected-chain document that contradicts the attested evidence —
/// the same string the Python signer emits, so an operator reading either platform's refusal is
/// reading the same word.
const REASON_CHAIN_DISAGREEMENT: &str = "chain_document_disagrees_with_attested_evidence";

/// **audit IDX-121.** The fields each protected-chain document must AGREE with the attested
/// evidence on — the Rust twin of `engine/runtime/isolated_signer.py::_CHAIN_AGREEMENT`,
/// field-for-field.
///
/// The Windows signer's chain verification was three existence checks (`store_read(..).is_none()`).
/// That is worth restating plainly: the signer runs as a SEPARATE OS principal for exactly one
/// reason — to re-verify the chain independently of the supervisor — and a presence check
/// re-verifies nothing. Meanwhile the Python signer had gained real cross-document agreement and
/// the Rust twin had not, which is the recurring shape of these findings: hardening lands on one
/// side of the pair and the other keeps the defect while the ledger reads CLOSED.
///
/// What this does NOT do, stated so nobody reads more into it: it cannot detect a supervisor that
/// lies CONSISTENTLY in both the evidence and the documents. A second opinion catches
/// disagreement, not a coherent forgery.
const CHAIN_AGREEMENT: [(&str, Option<&str>, &[&str]); 4] = [
    (
        "record_handle",
        Some("brops.governed-turn-record.v1"),
        &[
            "run_id",
            "task_id",
            "execution_attempt_id",
            "workspace_id",
            "install_id",
            "request_nonce",
            "receipt_id",
            "supervisor_id",
            "request_sha256",
            "system_handle",
            "history_handle",
            "generation_config_handle",
            "output_handle",
            "containment_evidence_handle",
            "decision",
        ],
    ),
    // The lease payload carries no protocol tag of its own.
    ("lease_handle", None, &["execution_attempt_id"]),
    (
        "execution_receipt_handle",
        Some("brops.execution-receipt.v1"),
        &["run_id", "execution_attempt_id", "output_handle"],
    ),
    // **remediation audit (round 2), `servers.rs:1037`.** The containment report was RESOLVED and
    // then thrown away — `let _ = (policy_bundle_sha256, containment_evidence_sha256);`, with a
    // comment claiming it was "bound via request/handles". It was not bound by anything. The
    // execution WRITES this document about itself (`execution.rs`, `brops.containment-evidence.v1`),
    // so it is the one chain document whose author is the party the signer is meant to be a second
    // opinion on, and it was the only one the signer merely counted.
    //
    // It now has to agree with the attested evidence on the run it describes and on the reply
    // digest it claims to have observed. A containment report about another attempt, or about
    // different output bytes, is a refusal instead of a resolved handle.
    (
        "containment_evidence_handle",
        Some("brops.containment-evidence.v1"),
        &["run_id", "execution_attempt_id", "output_handle"],
    ),
];

/// PURE — does one protected-chain document AGREE with the attested evidence on every field they
/// share? `recomputed` supplies the values the signer derived ITSELF (`request_sha256`); those are
/// what the document must match, never a value lifted out of the evidence beside it.
///
/// Returns the refusal reason, which names WHICH document and WHICH field differ: a refusal that
/// does not say that sends the operator to read two documents by hand.
fn chain_document_agrees(
    handle_field: &str,
    doc_bytes: &[u8],
    evidence: &Map<String, Value>,
    recomputed: &Map<String, Value>,
) -> Result<(), String> {
    let entry = match CHAIN_AGREEMENT.iter().find(|(f, _, _)| *f == handle_field) {
        Some(e) => e,
        // An unlisted document is one this signer has no agreement rule for; refusing is the only
        // honest outcome, because accepting it would restore the presence check for that field.
        None => return Err(format!("{REASON_CHAIN_DISAGREEMENT}:{handle_field}.no_agreement_rule")),
    };
    let parsed: Value = match serde_json::from_slice(doc_bytes) {
        Ok(v) => v,
        // A chain document the signer cannot read is one it cannot check.
        Err(_) => return Err("handle_unreadable".to_string()),
    };
    let doc = match parsed.as_object() {
        Some(o) => o,
        None => return Err("handle_unreadable".to_string()),
    };
    if let Some(protocol) = entry.1 {
        if doc.get("protocol").and_then(Value::as_str) != Some(protocol) {
            return Err(format!("{REASON_CHAIN_DISAGREEMENT}:{handle_field}.protocol"));
        }
    }
    for field in entry.2 {
        let expected = match recomputed.get(*field).or_else(|| evidence.get(*field)) {
            Some(v) => v,
            None => {
                return Err(format!("{REASON_CHAIN_DISAGREEMENT}:{handle_field}.{field}_unattested"))
            }
        };
        match doc.get(*field) {
            // REQUIRED, not merely "checked where present". Skipping absent fields would let a
            // document carrying nothing but its protocol tag agree vacuously — a hole exactly the
            // shape of the presence check this replaces.
            None => {
                return Err(format!("{REASON_CHAIN_DISAGREEMENT}:{handle_field}.{field}_missing"))
            }
            Some(v) if v == expected => {}
            Some(_) => return Err(format!("{REASON_CHAIN_DISAGREEMENT}:{handle_field}.{field}")),
        }
    }
    Ok(())
}

pub struct SignerConfig {
    pub receipt_key_id: String,
    pub supervisor_attestation_key_id: String,
    pub supervisor_attestation_public_key_hex: String,
    pub receipt_signing_seed: [u8; 32],
    pub store_dir: PathBuf,
    pub allowed_executors: Vec<String>,
    pub allowed_builders: Vec<String>,
    pub allowed_supervisors: Vec<String>,
}

pub struct Signer {
    cfg: SignerConfig,
    counter: Mutex<u64>,
}

impl Signer {
    pub fn new(cfg: SignerConfig) -> Self {
        Signer { cfg, counter: Mutex::new(0) }
    }

    pub fn dispatch(&self, req: &Value, now_ms: i64) -> Value {
        let o = match obj(req) {
            Some(o) => o,
            None => return refuse("?", "malformed"),
        };
        match o.get("op").and_then(Value::as_str) {
            Some("sign-result") => self.sign_result(o, now_ms),
            _ => refuse("?", "malformed"),
        }
    }

    fn refuse_sign(&self, reason: &str) -> Value {
        json!({
            "ok": false, "op": "sign-result", "error": "signer refused",
            "reason": reason, "artifact_type": "brops.governed-receipt-refusal.v1"
        })
    }

    fn sign_result(&self, o: &Map<String, Value>, now_ms: i64) -> Value {
        let sr = match o.get("sign_request").and_then(Value::as_object) {
            Some(s) => s,
            None => return self.refuse_sign("malformed"),
        };
        if !exact_keys(sr, &["protocol", "attestation", "evidence"]) {
            return self.refuse_sign("malformed");
        }
        if sr.get("protocol").and_then(Value::as_str) != Some(SIGN_REQUEST_PROTOCOL) {
            return self.refuse_sign("malformed");
        }
        let attestation = match sr.get("attestation").and_then(Value::as_object) {
            Some(a) => a,
            None => return self.refuse_sign("malformed"),
        };
        let evidence = match sr.get("evidence").and_then(Value::as_object) {
            Some(e) => e,
            None => return self.refuse_sign("malformed"),
        };
        if evidence.len() != EVIDENCE_FIELDS_LEN {
            return self.refuse_sign("malformed");
        }

        // (2) Attestation FIRST — pinned supervisor id + verify sig over JCS(evidence).
        if attestation.get("supervisor_key_id").and_then(Value::as_str)
            != Some(self.cfg.supervisor_attestation_key_id.as_str())
        {
            return self.refuse_sign("attestation_invalid");
        }
        let att_sig = match attestation.get("sig").and_then(Value::as_str) {
            Some(s) => s,
            None => return self.refuse_sign("attestation_invalid"),
        };
        let evidence_jcs = crypto::jcs(evidence);
        if !crypto::verify_ed25519_hex(&self.cfg.supervisor_attestation_public_key_hex, &evidence_jcs, att_sig) {
            return self.refuse_sign("attestation_invalid");
        }

        // (3) Authorization gates.
        if evidence.get("decision").and_then(Value::as_str) != Some("completed") {
            return self.refuse_sign("not_completed");
        }
        let request_nonce = match get_str(evidence, "request_nonce") {
            Some(s) if !s.is_empty() => s,
            _ => return self.refuse_sign("run_binding_invalid"),
        };
        let executor_id = get_str(evidence, "executor_id").unwrap_or_default();
        let builder_id = get_str(evidence, "builder_id").unwrap_or_default();
        let supervisor_id = get_str(evidence, "supervisor_id").unwrap_or_default();
        if !self.cfg.allowed_executors.contains(&executor_id)
            || !self.cfg.allowed_builders.contains(&builder_id)
            || !self.cfg.allowed_supervisors.contains(&supervisor_id)
        {
            return self.refuse_sign("identity_denied");
        }
        let requested_at = get_i64(evidence, "requested_at").unwrap_or(-1);
        let completed_at = get_i64(evidence, "completed_at").unwrap_or(-1);
        let challenge_accepted_at = get_i64(evidence, "challenge_accepted_at_ms").unwrap_or(-1);
        if requested_at < 0
            || completed_at < requested_at
            || completed_at < challenge_accepted_at
            || completed_at > now_ms + COMPLETED_SKEW_MS
        {
            return self.refuse_sign("timestamp_invalid");
        }

        // (4) RE-DERIVE all six *_sha256 from the content-addressed store + verify the 3 chain handles.
        let store = &self.cfg.store_dir;
        let derive = |handle_field: &str, missing: &str| -> Result<String, Value> {
            let h = get_str(evidence, handle_field).unwrap_or_default();
            match store_read(store, &h) {
                Some(_) => Ok(h),
                None => Err(self.refuse_sign(missing)),
            }
        };
        let policy_bundle_sha256 = match derive("policy_bundle_handle", "handle_missing") {
            Ok(h) => h,
            Err(e) => return e,
        };
        let generation_config_sha256 = match derive("generation_config_handle", "handle_missing") {
            Ok(h) => h,
            Err(e) => return e,
        };
        let system_sha256 = match derive("system_handle", "handle_missing") {
            Ok(h) => h,
            Err(e) => return e,
        };
        let history_sha256 = match derive("history_handle", "handle_missing") {
            Ok(h) => h,
            Err(e) => return e,
        };
        // Resolved here so an ABSENT containment report is refused with its own reason; its
        // CONTENTS are checked below by `CHAIN_AGREEMENT`, which is where the audit found nothing
        // was checking them.
        match derive("containment_evidence_handle", "containment_missing") {
            Ok(_) => {}
            Err(e) => return e,
        };
        let output_handle = get_str(evidence, "output_handle").unwrap_or_default();
        let output_bytes = match store_read(store, &output_handle) {
            Some(b) => b.len() as u64,
            None => return self.refuse_sign("handle_missing"),
        };
        let output_sha256 = output_handle;
        // The policy bundle is resolved by content address and nothing more, and this says so
        // rather than implying otherwise. It is an opaque blob with no schema this signer knows, so
        // there is no field for a second opinion to disagree on; what binds it is that the
        // supervisor's own config chose the handle and the store holds exactly those bytes. The
        // comment this replaces claimed both this and the containment report were "bound via
        // request/handles", which was true of neither.
        let _ = policy_bundle_sha256;

        // request_sha256 recomputed from the signer's OWN derived component hashes. It is computed
        // HERE, before the chain check below, because the terminal record must agree with the
        // signer's own recompute rather than with a digest the supervisor also chose.
        let request_sha256 = crypto::request_sha256(
            &get_str(evidence, "workspace_id").unwrap_or_default(),
            &get_str(evidence, "install_id").unwrap_or_default(),
            &request_nonce,
            &system_sha256,
            &history_sha256,
            &generation_config_sha256,
            &requested_at.to_string(),
        );

        // (4b) IDX-121: RE-VERIFY the three protected-chain documents. This was three existence
        // checks; the signer now READS each document and requires it to agree with the attested
        // evidence on every field they share — the same second opinion the Python signer gained.
        let mut recomputed = Map::new();
        recomputed.insert("request_sha256".into(), json!(request_sha256));
        for (handle_field, _, _) in CHAIN_AGREEMENT {
            let h = get_str(evidence, handle_field).unwrap_or_default();
            let bytes = match store_read(store, &h) {
                Some(b) => b,
                None => return self.refuse_sign("handle_missing"),
            };
            if let Err(reason) = chain_document_agrees(handle_field, &bytes, evidence, &recomputed) {
                return self.refuse_sign(&reason);
            }
        }

        let attestation_evidence_sha256 = crypto::sha256_hex(&evidence_jcs);

        // (5) Build the flat 23-key envelope payload.
        let mut p = Map::new();
        // 17 strings
        p.insert("artifact_type".into(), json!(ENVELOPE_ARTIFACT_TYPE));
        p.insert("key_id".into(), json!(self.cfg.receipt_key_id));
        p.insert("receipt_id".into(), evidence["receipt_id"].clone());
        p.insert("run_id".into(), evidence["run_id"].clone());
        p.insert("execution_attempt_id".into(), evidence["execution_attempt_id"].clone());
        p.insert("task_id".into(), evidence["task_id"].clone());
        p.insert("workspace_id".into(), evidence["workspace_id"].clone());
        p.insert("install_id".into(), evidence["install_id"].clone());
        p.insert("request_nonce".into(), json!(request_nonce));
        p.insert("request_sha256".into(), json!(request_sha256));
        p.insert("record_handle".into(), evidence["record_handle"].clone());
        p.insert("lease_handle".into(), evidence["lease_handle"].clone());
        p.insert("execution_receipt_handle".into(), evidence["execution_receipt_handle"].clone());
        p.insert("output_sha256".into(), json!(output_sha256));
        p.insert("evidence_final_event_hash".into(), evidence["evidence_final_event_hash"].clone());
        p.insert("supervisor_attestation_key_id".into(), json!(self.cfg.supervisor_attestation_key_id));
        p.insert("attestation_evidence_sha256".into(), json!(attestation_evidence_sha256));
        // 6 integers (bare)
        p.insert("output_bytes".into(), json!(output_bytes));
        p.insert("challenge_accepted_at_ms".into(), json!(challenge_accepted_at));
        p.insert("completed_at_ms".into(), json!(completed_at));
        p.insert("evidence_event_count".into(), evidence["evidence_event_count"].clone());
        p.insert("evidence_last_sequence".into(), evidence["evidence_last_sequence"].clone());
        p.insert("evidence_head_sequence".into(), evidence["evidence_head_sequence"].clone());

        // (6) Sign JCS(payload) once with the receipt private key.
        let signature = crypto::sign_b64url(
            &crypto::signing_key(&self.cfg.receipt_signing_seed),
            &crypto::jcs(&p),
        );
        let mut c = self.counter.lock().unwrap();
        *c += 1;
        json!({
            "ok": true, "op": "sign-result",
            "artifact_type": ENVELOPE_ARTIFACT_TYPE,
            "payload": Value::Object(p),
            "signature": signature,
        })
    }
}

impl DispatchCore for Authority {
    fn handle(&self, req: &Value, now_ms: i64) -> Value {
        self.dispatch(req, now_ms)
    }
}
impl DispatchCore for Supervisor {
    fn handle(&self, req: &Value, now_ms: i64) -> Value {
        self.dispatch(req, now_ms)
    }
}
impl DispatchCore for Signer {
    fn handle(&self, req: &Value, now_ms: i64) -> Value {
        self.dispatch(req, now_ms)
    }
}

// The ed25519 verify used by both principals below is `crypto::verify_ed25519_hex` — ONE function
// for the whole crate, beside the signing helpers it inverts. This module used to carry a second copy.


/// (audit **IDX-121**, **IDX-28/IDX-91**) Everything here runs on the LINUX CI runner: the
/// supervisor and signer cores are pure `serde_json` + filesystem, so "Windows-only" was never a
/// reason to leave these properties untested. Each test names the check it is holding down and
/// fails if that check is removed — not merely if the parser beside it breaks.
#[cfg(test)]
mod terminal_artifact_tests {
    use super::*;
    use std::path::Path;

    fn tmp(tag: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("brops-winlive-{tag}-{}", brops_core::id()));
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    struct Kit {
        authority: Authority,
        supervisor: Supervisor,
        store: PathBuf,
        evidence: PathBuf,
        /// The floor database, so a test can stand a SECOND supervisor over the same durable floor
        /// — the restart the in-process `BTreeMap` could never survive (audit R-42).
        floor_db: PathBuf,
    }

    const SUP_ID: &str = "brops-supervisor";

    fn kit() -> Kit {
        kit_over_floor(tmp("floor").join("evidence-floor.db"))
    }

    fn kit_over_floor(floor_db: PathBuf) -> Kit {
        let challenge_seed = crypto::gen_seed();
        let store = tmp("store");
        let evidence = tmp("ev");
        Kit {
            authority: Authority::new(AuthorityConfig {
                challenge_key_id: "ck-1".into(),
                supervisor_id: SUP_ID.into(),
                challenge_signing_seed: challenge_seed,
            }),
            supervisor: Supervisor::new(SupervisorConfig {
                supervisor_id: SUP_ID.into(),
                supervisor_attestation_key_id: "ak-1".into(),
                challenge_public_key_hex: crypto::public_key_hex(&crypto::signing_key(
                    &challenge_seed,
                )),
                attest_signing_seed: crypto::gen_seed(),
                launcher_executable_sha256: "11".repeat(32),
                executor_executable_sha256: "22".repeat(32),
                executor_id: "ex-1".into(),
                builder_id: "bu-1".into(),
                policy_id: "p-1".into(),
                policy_version: "1".into(),
                policy_bundle_handle: "33".repeat(32),
                store_dir: store.clone(),
                evidence_dir: evidence.clone(),
                evidence_floor_db: floor_db.clone(),
            })
            .expect("supervisor floor opens"),
            store,
            evidence,
            floor_db,
        }
    }

    /// create-pending → issue → accept-open, returning the granted `execution_attempt_id`.
    fn lease(kit: &Kit, now: i64) -> String {
        lease_for_task(kit, now, "task-1")
    }

    /// The same, under a chosen `task_id`. `task_id` arrives on the wire and the authority accepts
    /// any bounded string for it, which is precisely why the floor is scoped to the INSTALL: a
    /// per-task floor would let a caller pick a bucket with no row in it.
    fn lease_for_task(kit: &Kit, now: i64, task_id: &str) -> String {
        let pending = kit.authority.dispatch(
            &json!({
                "op": "create-pending",
                "run_id": "run-1", "task_id": task_id, "workspace_id": "ws-1",
                "install_id": "in-1", "request_nonce": format!("n-{now}-{task_id}"),
                "system_sha256": "aa".repeat(32), "history_sha256": "bb".repeat(32),
                "generation_config_sha256": "cc".repeat(32), "requested_at_ms": now,
            }),
            now,
        );
        assert_eq!(pending["ok"], json!(true), "{pending}");
        let issued = kit.authority.dispatch(
            &json!({ "op": "issue", "pending_challenge_id": pending["pending_challenge_id"] }),
            now,
        );
        let open = kit.supervisor.dispatch(
            &json!({ "op": "accept-open", "challenge_doc": issued["challenge"] }),
            now,
        );
        assert_eq!(open["ok"], json!(true), "{open}");
        open["lease"]["execution_attempt_id"].as_str().unwrap().to_string()
    }

    /// The chain the execution would have written, so `complete-run` can get past `derive_evidence`
    /// and reach the decision this test is actually about.
    fn write_chain(kit: &Kit, attempt: &str, output_handle: &str) {
        write_chain_at(kit, attempt, output_handle, 1);
    }

    /// The same, at a chosen `head_sequence` — the one field that orders two runs (audit R-42).
    fn write_chain_at(kit: &Kit, attempt: &str, output_handle: &str, head_sequence: i64) {
        std::fs::write(
            kit.evidence.join(format!("{attempt}.evidence.json")),
            crate::execution::build_run_evidence(attempt, output_handle, 7, head_sequence),
        )
        .unwrap();
    }

    /// LEASE_READY → EXECUTING, so a test can reach the completion decision.
    fn drive_to_executing(kit: &Kit, attempt: &str, now: i64) {
        let gated = kit
            .supervisor
            .dispatch(&json!({"op":"launch-gate","execution_attempt_id":attempt}), now);
        assert_eq!(gated["ok"], json!(true), "{gated}");
        let started = kit.supervisor.dispatch(
            &json!({"op":"execution-started","execution_attempt_id":attempt,
                    "process_observation": OBSERVATION_IN_DRIVER, "process_id": "",
                    "execution_started_marker": Value::Null}),
            now,
        );
        assert_eq!(started["ok"], json!(true), "{started}");
    }

    /// One whole turn to a completion, at a chosen head sequence and task. Returns the reply.
    fn turn_at(kit: &Kit, now: i64, task_id: &str, output_handle: &str, head: i64) -> Value {
        let attempt = lease_for_task(kit, now, task_id);
        drive_to_executing(kit, &attempt, now);
        write_chain_at(kit, &attempt, output_handle, head);
        complete(kit, &attempt, output_handle, now + 10)
    }

    fn complete(kit: &Kit, attempt: &str, output_handle: &str, completed_at_ms: i64) -> Value {
        kit.supervisor.dispatch(
            &json!({
                "op": "complete-run", "execution_attempt_id": attempt,
                "produced": {
                    "output_handle": output_handle,
                    "containment_evidence_handle": "dd".repeat(32),
                    "completed_at_ms": completed_at_ms,
                },
            }),
            completed_at_ms,
        )
    }

    /// Does the protected store hold a document claiming this protocol?
    fn store_holds(dir: &Path, protocol: &str) -> bool {
        std::fs::read_dir(dir).unwrap().flatten().any(|e| {
            std::fs::read(e.path())
                .ok()
                .and_then(|b| serde_json::from_slice::<Value>(&b).ok())
                .and_then(|v| v.get("protocol").and_then(Value::as_str).map(str::to_string))
                .as_deref()
                == Some(protocol)
        })
    }

    // ---- rev-30 CORRECTION: `challenge_handle` addresses the signed DOCUMENT ------------------

    /// The handle is `SHA256(JCS({payload, sig}))`, NOT `SHA256(JCS(payload))`.
    ///
    /// rev-30 said both. Its section 3 artifact matrix, section 4.10(a0) and Appendix B's handle
    /// matrix define the `{payload, sig}` form; section 5's summary table described the
    /// payload-only form this server used to compute. The Architect declared section 3 normative
    /// (docs/OWNER_ACTION_REQUIRED.md 1c) and section 5's table was corrected. Without this test the
    /// Rust half of the correction had no executable guard at all: every consumer of the handle is
    /// opaque to the formula, so a revert here would break nothing that runs.
    #[test]
    fn challenge_handle_addresses_the_signed_document_not_the_payload_alone() {
        let now = 1_700_000_000_000i64;
        let kit = kit();
        let pending = kit.authority.dispatch(
            &json!({
                "op": "create-pending",
                "run_id": "run-1", "task_id": "task-1", "workspace_id": "ws-1",
                "install_id": "in-1", "request_nonce": format!("n-{now}"),
                "system_sha256": "aa".repeat(32), "history_sha256": "bb".repeat(32),
                "generation_config_sha256": "cc".repeat(32), "requested_at_ms": now,
            }),
            now,
        );
        let issued = kit.authority.dispatch(
            &json!({ "op": "issue", "pending_challenge_id": pending["pending_challenge_id"] }),
            now,
        );
        let doc = issued["challenge"].as_object().unwrap().clone();
        let payload = doc["payload"].as_object().unwrap().clone();

        // The two candidate formulas, computed HERE from the real issued document so neither is
        // taken on the server's word.
        let normative = crypto::sha256_hex(&crypto::jcs(&doc));
        let superseded = crypto::sha256_hex(&crypto::jcs(&payload));
        assert_ne!(
            normative, superseded,
            "the two formulas must be distinguishable or this test proves nothing"
        );

        let open = kit
            .supervisor
            .dispatch(&json!({ "op": "accept-open", "challenge_doc": issued["challenge"] }), now);
        assert_eq!(open["ok"], json!(true), "{open}");
        let attempt = open["lease"]["execution_attempt_id"].as_str().unwrap().to_string();

        // What the supervisor durably keyed the acceptance on.
        let keyed: Vec<String> = kit.supervisor.by_challenge.lock().unwrap().keys().cloned().collect();
        assert_eq!(keyed, vec![normative.clone()], "replay key is not SHA256(JCS({{payload, sig}}))");
        assert!(
            !keyed.contains(&superseded),
            "accept_open regressed to the superseded SHA256(JCS(payload)) form"
        );

        // ...and what it will name in the terminal record an auditor dereferences.
        let recorded = kit.supervisor.accepted.lock().unwrap()[&attempt].challenge_handle.clone();
        assert_eq!(recorded, normative);

        // A different signature over the SAME payload is a DIFFERENT handle. This is the property
        // the payload-only form did not have, and the reason the stronger binding was chosen.
        let mut other = doc.clone();
        let flipped: String = doc["sig"].as_str().unwrap().chars().rev().collect();
        other.insert("sig".into(), json!(flipped));
        assert_ne!(crypto::sha256_hex(&crypto::jcs(&other)), normative);

        let _ = std::fs::remove_dir_all(&kit.store);
        let _ = std::fs::remove_dir_all(&kit.evidence);
    }

    // ---- IDX-121: nothing is published until the state machine has accepted ---------------------

    #[test]
    fn a_refused_completion_publishes_no_terminal_record() {
        let now = 1_700_000_000_000i64;
        let kit = kit();
        let attempt = lease(&kit, now);
        let output_handle = "ee".repeat(32);
        write_chain(&kit, &attempt, &output_handle);
        // LEASE_READY: never gated, never started. The §5 machine must refuse.
        let reply = complete(&kit, &attempt, &output_handle, now + 10);
        assert_eq!(reply["ok"], json!(false), "{reply}");
        assert_eq!(reply["reason"], json!("illegal_state"), "{reply}");
        // THE CHECK: a refusal must leave the store as it found it. Publishing before the decision
        // planted a record asserting `"decision":"completed"` for a run the supervisor declined —
        // and that store is what the isolated signer resolves `record_handle` against.
        assert!(
            !store_holds(&kit.store, "brops.governed-turn-record.v1"),
            "a REFUSED complete-run published a terminal record into the protected store"
        );
        assert!(!store_holds(&kit.store, "brops.execution-receipt.v1"));
        let _ = std::fs::remove_dir_all(&kit.store);
        let _ = std::fs::remove_dir_all(&kit.evidence);
    }

    #[test]
    fn an_accepted_completion_does_publish_all_three() {
        let now = 1_700_000_000_000i64;
        let kit = kit();
        let attempt = lease(&kit, now);
        assert_eq!(
            kit.supervisor
                .dispatch(&json!({"op":"launch-gate","execution_attempt_id":attempt}), now)["ok"],
            json!(true)
        );
        assert_eq!(
            kit.supervisor.dispatch(
                &json!({"op":"execution-started","execution_attempt_id":attempt,
                        "process_observation": OBSERVATION_IN_DRIVER, "process_id": "",
                        "execution_started_marker": Value::Null}),
                now,
            )["ok"],
            json!(true)
        );
        let output_handle = "ee".repeat(32);
        write_chain(&kit, &attempt, &output_handle);
        let reply = complete(&kit, &attempt, &output_handle, now + 10);
        assert_eq!(reply["ok"], json!(true), "{reply}");
        assert_eq!(reply["recorded"], json!("created"));
        assert!(store_holds(&kit.store, "brops.governed-turn-record.v1"));
        assert!(store_holds(&kit.store, "brops.execution-receipt.v1"));
        // Idempotent retry: still accepted, still exactly one record.
        assert_eq!(complete(&kit, &attempt, &output_handle, now + 10)["recorded"], json!("idempotent"));
        let _ = std::fs::remove_dir_all(&kit.store);
        let _ = std::fs::remove_dir_all(&kit.evidence);
    }

    #[test]
    fn the_admission_decision_is_taken_on_state_not_on_arrival() {
        let c = |completed_at_ms: i64| Completion {
            output_handle: "ee".repeat(32),
            containment_evidence_handle: "dd".repeat(32),
            record_handle: "11".repeat(32),
            lease_handle: "22".repeat(32),
            execution_receipt_handle: "33".repeat(32),
            completed_at_ms,
            evidence_final_event_hash: "44".repeat(32),
            evidence_event_count: 3,
            evidence_last_sequence: 3,
            evidence_head_sequence: 1,
        };
        assert_eq!(admit_completion(ST_EXECUTING, 10, None, &c(20)), CompletionAdmission::Accept);
        for state in [ST_LEASE_READY, ST_EXECUTION_STARTING, ST_EXPIRED, ST_COMPLETED] {
            assert_eq!(
                admit_completion(state, 10, None, &c(20)),
                CompletionAdmission::Refuse("illegal_state"),
                "{state}"
            );
        }
        // IDX-28: a run cannot finish before the supervisor observed it start.
        assert_eq!(
            admit_completion(ST_EXECUTING, 30, None, &c(20)),
            CompletionAdmission::Refuse("completed_before_execution_started")
        );
        // Write-once.
        assert_eq!(
            admit_completion(ST_COMPLETED, 10, Some(&c(20)), &c(20)),
            CompletionAdmission::Idempotent
        );
        assert_eq!(
            admit_completion(ST_COMPLETED, 10, Some(&c(20)), &c(21)),
            CompletionAdmission::Refuse("completion_conflict")
        );
    }

    // ---- IDX-28 / IDX-91: the process report says what it is -----------------------------------

    #[test]
    fn a_report_that_observed_nothing_cannot_name_a_process() {
        // The defect: the driver sent `std::process::id()` after the executor had exited and the
        // supervisor recorded it as the executed process.
        for kind in [OBSERVATION_IN_DRIVER, OBSERVATION_UNOBSERVED_CHILD] {
            assert_eq!(admit_process_report(kind, ""), Ok(()));
            assert_eq!(admit_process_report(kind, "4321"), Err("process_id_not_observed"));
        }
        assert_eq!(admit_process_report(OBSERVATION_OBSERVED_CHILD, "4321"), Ok(()));
        assert_eq!(admit_process_report(OBSERVATION_OBSERVED_CHILD, ""), Err("process_id_missing"));
        // Closed set: an unknown kind is refused, never treated as the permissive one.
        for bogus in ["", "win-live", "child", "observed_child", "driver"] {
            assert_eq!(admit_process_report(bogus, ""), Err("process_observation_unknown"), "{bogus}");
        }
    }

    #[test]
    fn the_supervisor_refuses_a_process_id_from_an_unobserving_report() {
        let now = 1_700_000_000_000i64;
        let kit = kit();
        let attempt = lease(&kit, now);
        kit.supervisor.dispatch(&json!({"op":"launch-gate","execution_attempt_id":attempt}), now);
        let reply = kit.supervisor.dispatch(
            &json!({"op":"execution-started","execution_attempt_id":attempt,
                    "process_observation": OBSERVATION_IN_DRIVER, "process_id": "4321",
                    "execution_started_marker": Value::Null}),
            now,
        );
        assert_eq!(reply["ok"], json!(false), "{reply}");
        assert_eq!(reply["reason"], json!("process_id_not_observed"), "{reply}");
        // And the OLD wire shape — the one that carried the driver's pid as `process_group_id`
        // beside a `cgroup_id` of `"win-live"` — is now simply not a message this supervisor knows.
        let old = kit.supervisor.dispatch(
            &json!({"op":"execution-started","execution_attempt_id":attempt,
                    "process_group_id": "4321", "cgroup_id": "win-live",
                    "execution_started_marker": Value::Null}),
            now,
        );
        assert_eq!(old["ok"], json!(false), "{old}");
        let _ = std::fs::remove_dir_all(&kit.store);
        let _ = std::fs::remove_dir_all(&kit.evidence);
    }

    #[test]
    fn a_completion_dated_before_the_observed_start_is_refused() {
        let now = 1_700_000_000_000i64;
        let kit = kit();
        let attempt = lease(&kit, now);
        kit.supervisor.dispatch(&json!({"op":"launch-gate","execution_attempt_id":attempt}), now);
        kit.supervisor.dispatch(
            &json!({"op":"execution-started","execution_attempt_id":attempt,
                    "process_observation": OBSERVATION_IN_DRIVER, "process_id": "",
                    "execution_started_marker": Value::Null}),
            now,
        );
        let output_handle = "ee".repeat(32);
        write_chain(&kit, &attempt, &output_handle);
        let reply = complete(&kit, &attempt, &output_handle, now - 1);
        assert_eq!(reply["reason"], json!("completed_before_execution_started"), "{reply}");
        assert!(!store_holds(&kit.store, "brops.governed-turn-record.v1"));
        let _ = std::fs::remove_dir_all(&kit.store);
        let _ = std::fs::remove_dir_all(&kit.evidence);
    }

    // ---- audit R-42: the CROSS-RUN evidence-head floor Windows did not have --------------------
    //
    // Every test above is about ONE attempt. These are the ones that need TWO, because the defect
    // R-42 recorded was not a missing check inside a run — it was that no state at all survived one
    // run to constrain the next. `accepted` is keyed by `execution_attempt_id`, so turn A at head
    // 100 and turn B at head 1 were both attested without objection.

    #[test]
    fn a_later_run_presenting_an_older_evidence_head_is_refused() {
        let now = 1_700_000_000_000i64;
        let kit = kit();
        let first = turn_at(&kit, now, "task-1", &"e1".repeat(32), 5);
        assert_eq!(first["ok"], json!(true), "{first}");

        // The rollback: a genuinely-written, genuinely-hash-linked chain — just an OLDER one.
        // Everything `derive_evidence` checks still holds; only the floor can tell.
        let rolled_back = turn_at(&kit, now + 1000, "task-1", &"e2".repeat(32), 3);
        assert_eq!(rolled_back["ok"], json!(false), "{rolled_back}");
        assert_eq!(rolled_back["reason"], json!("stale_evidence"), "{rolled_back}");
        cleanup(&kit);
    }

    /// The floor is scoped to the INSTALL, not to `(install_id, task_id)`. `task_id` arrives on the
    /// wire, so a per-task floor would let the caller choose a bucket with no row in it and get the
    /// bootstrap branch for free — which is the same rollback with one extra step.
    #[test]
    fn a_fresh_task_id_does_not_buy_a_bootstrap_past_the_floor() {
        let now = 1_700_000_000_000i64;
        let kit = kit();
        assert_eq!(turn_at(&kit, now, "task-1", &"e1".repeat(32), 5)["ok"], json!(true));
        let under_new_task = turn_at(&kit, now + 1000, "task-FRESH", &"e2".repeat(32), 3);
        assert_eq!(under_new_task["reason"], json!("stale_evidence"), "{under_new_task}");
        cleanup(&kit);
    }

    /// One install has one counter, so the same head sequence cannot honestly be minted twice.
    #[test]
    fn the_same_head_sequence_cannot_be_minted_twice_on_one_install() {
        let now = 1_700_000_000_000i64;
        let kit = kit();
        assert_eq!(turn_at(&kit, now, "task-1", &"e1".repeat(32), 5)["ok"], json!(true));
        // Same head number, DIFFERENT chain content — a fork, not a retry.
        let fork = turn_at(&kit, now + 1000, "task-2", &"e2".repeat(32), 5);
        assert_eq!(fork["reason"], json!("evidence_fork"), "{fork}");
        cleanup(&kit);
    }

    /// The floor must not refuse honest progress, or it would be a blanket denial rather than an
    /// ordering. Without this the three refusals above are also satisfied by `return refuse(..)`.
    #[test]
    fn an_advanced_head_is_accepted_so_the_floor_orders_rather_than_blocks() {
        let now = 1_700_000_000_000i64;
        let kit = kit();
        for (i, head) in [5i64, 6, 7, 12].iter().enumerate() {
            let reply =
                turn_at(&kit, now + i as i64 * 1000, "task-1", &format!("{:02x}", i + 1).repeat(32), *head);
            assert_eq!(reply["ok"], json!(true), "head {head}: {reply}");
        }
        cleanup(&kit);
    }

    /// **The property the in-process `BTreeMap` could never have.** A supervisor process that is
    /// restarted must still refuse a head its predecessor already attested — otherwise the cheapest
    /// attack on the floor is not to beat it but to bounce the service.
    #[test]
    fn the_floor_survives_a_supervisor_restart() {
        let now = 1_700_000_000_000i64;
        let floor_db = tmp("shared-floor").join("evidence-floor.db");
        let first = kit_over_floor(floor_db.clone());
        assert_eq!(turn_at(&first, now, "task-1", &"e1".repeat(32), 9)["ok"], json!(true));

        // A completely fresh supervisor: new keys, new in-process state, new store — same floor.
        let restarted = kit_over_floor(floor_db.clone());
        assert!(
            restarted.supervisor.accepted.lock().unwrap().is_empty(),
            "the restarted supervisor must genuinely have no in-process memory of the first run"
        );
        let rolled_back = turn_at(&restarted, now + 1000, "task-1", &"e2".repeat(32), 4);
        assert_eq!(rolled_back["reason"], json!("stale_evidence"), "{rolled_back}");
        cleanup(&first);
        cleanup(&restarted);
    }

    /// A completion the state machine REFUSES must not consume a head sequence. Advancing the floor
    /// on a declined turn would hand the caller a denial-of-service: present head 999 from an
    /// un-started attempt, get refused, and every honest later turn is now stale.
    #[test]
    fn a_refused_completion_does_not_burn_the_head_sequence() {
        let now = 1_700_000_000_000i64;
        let kit = kit();
        // LEASE_READY, never gated: `admit_completion` refuses before the floor is consulted.
        let attempt = lease_for_task(&kit, now, "task-1");
        write_chain_at(&kit, &attempt, &"e9".repeat(32), 999);
        let refused = complete(&kit, &attempt, &"e9".repeat(32), now + 10);
        assert_eq!(refused["reason"], json!("illegal_state"), "{refused}");

        // If the floor had been advanced to 999, this honest turn would now be `stale_evidence`.
        let honest = turn_at(&kit, now + 1000, "task-1", &"e1".repeat(32), 5);
        assert_eq!(honest["ok"], json!(true), "a refused turn burned the floor: {honest}");
        cleanup(&kit);
    }

    /// A byte-identical retry of an accepted completion stays idempotent with the floor in place —
    /// it must not be read as a same-head fork.
    #[test]
    fn an_identical_retry_is_still_idempotent_with_the_floor_armed() {
        let now = 1_700_000_000_000i64;
        let kit = kit();
        let attempt = lease_for_task(&kit, now, "task-1");
        drive_to_executing(&kit, &attempt, now);
        let handle = "e1".repeat(32);
        write_chain_at(&kit, &attempt, &handle, 5);
        assert_eq!(complete(&kit, &attempt, &handle, now + 10)["recorded"], json!("created"));
        let retry = complete(&kit, &attempt, &handle, now + 10);
        assert_eq!(retry["ok"], json!(true), "{retry}");
        assert_eq!(retry["recorded"], json!("idempotent"), "{retry}");
        cleanup(&kit);
    }

    /// The floor is not optional and there is no in-memory fallback: a supervisor that cannot open
    /// one does not exist. An `Option<PathBuf>` here would reintroduce R-42 as a config default.
    #[test]
    fn a_supervisor_without_a_floor_refuses_to_be_built() {
        let base = kit();
        let mut cfg_db = PathBuf::new();
        assert!(
            Supervisor::new(SupervisorConfig {
                supervisor_id: SUP_ID.into(),
                supervisor_attestation_key_id: "ak-1".into(),
                challenge_public_key_hex: "00".repeat(32),
                attest_signing_seed: crypto::gen_seed(),
                launcher_executable_sha256: "11".repeat(32),
                executor_executable_sha256: "22".repeat(32),
                executor_id: "ex-1".into(),
                builder_id: "bu-1".into(),
                policy_id: "p-1".into(),
                policy_version: "1".into(),
                policy_bundle_handle: "33".repeat(32),
                store_dir: base.store.clone(),
                evidence_dir: base.evidence.clone(),
                evidence_floor_db: std::mem::take(&mut cfg_db),
            })
            .is_err(),
            "an unconfigured evidence floor must refuse, not pass"
        );
        cleanup(&base);
    }

    fn cleanup(kit: &Kit) {
        let _ = std::fs::remove_dir_all(&kit.store);
        let _ = std::fs::remove_dir_all(&kit.evidence);
        let _ = kit.floor_db.parent().map(std::fs::remove_dir_all);
    }
}

/// (audit **IDX-121**) The Windows signer's protected-chain verification. It was three existence
/// checks; these hold down the cross-document agreement that replaced them. Pure + filesystem, so
/// they run on the Linux CI runner.
#[cfg(test)]
mod signer_chain_tests {
    use super::*;

    fn tmp() -> PathBuf {
        let d = std::env::temp_dir().join(format!("brops-winlive-sign-{}", brops_core::id()));
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    fn blob(dir: &std::path::Path, bytes: &[u8]) -> String {
        let h = crypto::sha256_hex(bytes);
        std::fs::write(dir.join(&h), bytes).unwrap();
        h
    }

    const NOW: i64 = 1_700_000_000_000;
    const REQUESTED_AT: i64 = 1_699_999_000_000;

    /// A store + the 29-field evidence for one coherent run, with the three chain documents built
    /// so that everything agrees. Each test then perturbs exactly ONE document.
    struct Fixture {
        signer: Signer,
        store: PathBuf,
        evidence: Map<String, Value>,
        attest_seed: [u8; 32],
        /// `record` / `lease` / `receipt` as JSON, so a test can edit one and re-publish it.
        docs: BTreeMap<&'static str, Value>,
    }

    fn fixture() -> Fixture {
        let store = tmp();
        let attest_seed = crypto::gen_seed();
        let signer = Signer::new(SignerConfig {
            receipt_key_id: "rk-1".into(),
            supervisor_attestation_key_id: "ak-1".into(),
            supervisor_attestation_public_key_hex: crypto::public_key_hex(&crypto::signing_key(
                &attest_seed,
            )),
            receipt_signing_seed: crypto::gen_seed(),
            store_dir: store.clone(),
            allowed_executors: vec!["ex-1".into()],
            allowed_builders: vec!["bu-1".into()],
            allowed_supervisors: vec!["sup-1".into()],
        });
        let system_handle = blob(&store, b"system");
        let history_handle = blob(&store, b"history");
        let generation_config_handle = blob(&store, b"gen-config");
        let policy_bundle_handle = blob(&store, b"policy-bundle");
        let output_handle = blob(&store, b"the reply bytes");

        // The digest the SIGNER will recompute for itself — the record has to match this one.
        let request_sha256 = crypto::request_sha256(
            "ws-1",
            "in-1",
            "nonce-1",
            &system_handle,
            &history_handle,
            &generation_config_handle,
            &REQUESTED_AT.to_string(),
        );
        // The execution's own containment report — a real document now, not an opaque blob, because
        // the signer re-verifies its contents (see `CHAIN_AGREEMENT`).
        let containment = json!({
            "protocol": "brops.containment-evidence.v1",
            "containment_mode": "windows-proof-kit:test",
            "execution_attempt_id": "EA-1", "run_id": "run-1",
            "executor_image_binding": crate::execution::IMAGE_BINDING_IN_PROCESS,
            "output_handle": output_handle, "output_bytes": 15, "completed_at_ms": NOW - 1000,
        });
        let containment_evidence_handle = blob(&store, &serde_json::to_vec(&containment).unwrap());
        let record = json!({
            "protocol": "brops.governed-turn-record.v1",
            "run_id": "run-1", "task_id": "task-1", "execution_attempt_id": "EA-1",
            "workspace_id": "ws-1", "install_id": "in-1", "request_nonce": "nonce-1",
            "receipt_id": "R-1", "supervisor_id": "sup-1", "request_sha256": request_sha256,
            "system_handle": system_handle, "history_handle": history_handle,
            "generation_config_handle": generation_config_handle,
            "output_handle": output_handle,
            "containment_evidence_handle": containment_evidence_handle,
            "decision": "completed",
        });
        let lease = json!({
            "lease_id": "L-1", "execution_attempt_id": "EA-1",
            "lease_expires_at_ms": NOW + 1000,
            "launcher_executable_sha256": "11".repeat(32),
            "executor_executable_sha256": "22".repeat(32),
        });
        let receipt = json!({
            "protocol": "brops.execution-receipt.v1",
            "run_id": "run-1", "execution_attempt_id": "EA-1", "output_handle": output_handle,
        });
        let record_handle = blob(&store, &serde_json::to_vec(&record).unwrap());
        let lease_handle = blob(&store, &serde_json::to_vec(&lease).unwrap());
        let execution_receipt_handle = blob(&store, &serde_json::to_vec(&receipt).unwrap());

        let mut evidence = Map::new();
        for (k, v) in [
            ("run_id", "run-1"), ("execution_attempt_id", "EA-1"), ("task_id", "task-1"),
            ("request_nonce", "nonce-1"), ("receipt_id", "R-1"), ("workspace_id", "ws-1"),
            ("install_id", "in-1"), ("supervisor_id", "sup-1"), ("executor_id", "ex-1"),
            ("builder_id", "bu-1"), ("policy_id", "p-1"), ("policy_version", "1"),
            ("policy_bundle_handle", &policy_bundle_handle),
            ("generation_config_handle", &generation_config_handle),
            ("system_handle", &system_handle), ("history_handle", &history_handle),
            ("output_handle", &output_handle),
            ("containment_evidence_handle", &containment_evidence_handle),
            ("record_handle", &record_handle), ("lease_handle", &lease_handle),
            ("execution_receipt_handle", &execution_receipt_handle),
            ("evidence_final_event_hash", &"44".repeat(32)),
            ("decision", "completed"),
        ] {
            evidence.insert(k.into(), json!(v));
        }
        for (k, v) in [
            ("requested_at", REQUESTED_AT), ("completed_at", NOW - 1000),
            ("challenge_accepted_at_ms", REQUESTED_AT + 1), ("evidence_event_count", 3),
            ("evidence_last_sequence", 3), ("evidence_head_sequence", 1),
        ] {
            evidence.insert(k.into(), json!(v));
        }
        assert_eq!(evidence.len(), EVIDENCE_FIELDS_LEN, "fixture must build a full evidence set");

        let mut docs = BTreeMap::new();
        docs.insert("record_handle", record);
        docs.insert("lease_handle", lease);
        docs.insert("execution_receipt_handle", receipt);
        docs.insert("containment_evidence_handle", containment);
        Fixture { signer, store, evidence, attest_seed, docs }
    }

    impl Fixture {
        /// Re-publish `doc` under `handle_field` (its content address changes, so the evidence has
        /// to name the new one) and ask the signer to sign.
        fn sign_with(&self, handle_field: &str, doc: &Value) -> Value {
            let mut evidence = self.evidence.clone();
            let bytes = serde_json::to_vec(doc).unwrap();
            evidence.insert(handle_field.into(), json!(blob(&self.store, &bytes)));
            self.sign(evidence)
        }
        fn sign(&self, evidence: Map<String, Value>) -> Value {
            let jcs = crypto::jcs(&evidence);
            let sig = crypto::sign_b64url(&crypto::signing_key(&self.attest_seed), &jcs);
            self.signer.dispatch(
                &json!({
                    "op": "sign-result",
                    "sign_request": {
                        "protocol": SIGN_REQUEST_PROTOCOL,
                        "attestation": { "supervisor_key_id": "ak-1", "sig": sig },
                        "evidence": Value::Object(evidence),
                    }
                }),
                NOW,
            )
        }
        fn doc(&self, handle_field: &str) -> Value {
            self.docs[handle_field].clone()
        }

        /// Publish acontainment report and make the whole rest of the chain AGREE with it — the
        /// terminal record names `containment_evidence_handle` too, so a test that swapped only the
        /// blob would trip the record's own agreement check first and prove nothing about the
        /// containment document. This is the coherent set a supervisor-side forgery would produce:
        /// evidence and record both naming the new handle, and only the report's CONTENTS wrong.
        fn sign_with_containment(&self, doc: &Value) -> Value {
            let handle = blob(&self.store, &serde_json::to_vec(doc).unwrap());
            let mut record = self.doc("record_handle");
            record["containment_evidence_handle"] = json!(handle);
            let mut evidence = self.evidence.clone();
            evidence.insert("containment_evidence_handle".into(), json!(handle));
            evidence.insert(
                "record_handle".into(),
                json!(blob(&self.store, &serde_json::to_vec(&record).unwrap())),
            );
            self.sign(evidence)
        }
    }

    #[test]
    fn a_coherent_chain_signs() {
        let f = fixture();
        let reply = f.sign(f.evidence.clone());
        assert_eq!(reply["ok"], json!(true), "{reply}");
        let _ = std::fs::remove_dir_all(&f.store);
    }

    #[test]
    fn a_record_that_names_another_run_is_refused() {
        // THE CHECK. Under the existence check this was indistinguishable from the happy path:
        // the blob resolved, so the signer signed. It is a different account of a different run.
        let f = fixture();
        for (field, wrong) in [
            ("run_id", json!("run-2")),
            ("execution_attempt_id", json!("EA-2")),
            ("output_handle", json!("ff".repeat(32))),
            ("receipt_id", json!("R-2")),
            ("supervisor_id", json!("sup-2")),
            ("request_nonce", json!("nonce-2")),
            ("containment_evidence_handle", json!("ff".repeat(32))),
            ("decision", json!("refused")),
        ] {
            let mut record = f.doc("record_handle");
            record[field] = wrong;
            let reply = f.sign_with("record_handle", &record);
            assert_eq!(reply["ok"], json!(false), "{field}: {reply}");
            assert_eq!(
                reply["reason"],
                json!(format!("{REASON_CHAIN_DISAGREEMENT}:record_handle.{field}")),
                "{field}"
            );
        }
        let _ = std::fs::remove_dir_all(&f.store);
    }

    #[test]
    fn a_record_disagreeing_with_the_signers_own_request_digest_is_refused() {
        // `request_sha256` is not in the attested evidence at all — the expected value is the one
        // the signer RECOMPUTED from the store bytes. A record naming any other digest is a
        // different request.
        let f = fixture();
        let mut record = f.doc("record_handle");
        record["request_sha256"] = json!("ab".repeat(32));
        let reply = f.sign_with("record_handle", &record);
        assert_eq!(
            reply["reason"],
            json!(format!("{REASON_CHAIN_DISAGREEMENT}:record_handle.request_sha256")),
            "{reply}"
        );
        let _ = std::fs::remove_dir_all(&f.store);
    }

    #[test]
    fn a_document_that_agrees_vacuously_is_refused() {
        // A blob carrying nothing but its protocol tag resolved fine under the existence check.
        let f = fixture();
        let reply = f.sign_with(
            "record_handle",
            &json!({ "protocol": "brops.governed-turn-record.v1" }),
        );
        assert_eq!(
            reply["reason"],
            json!(format!("{REASON_CHAIN_DISAGREEMENT}:record_handle.run_id_missing")),
            "{reply}"
        );
        // ...and so did a blob that is not the document it claims to be at all.
        let wrong_protocol = f.sign_with("record_handle", &json!({ "protocol": "something.else" }));
        assert_eq!(
            wrong_protocol["reason"],
            json!(format!("{REASON_CHAIN_DISAGREEMENT}:record_handle.protocol")),
            "{wrong_protocol}"
        );
        // ...and so did a blob that is not JSON.
        let mut evidence = f.evidence.clone();
        evidence.insert("record_handle".into(), json!(blob(&f.store, b"not json at all")));
        assert_eq!(f.sign(evidence)["reason"], json!("handle_unreadable"));
        let _ = std::fs::remove_dir_all(&f.store);
    }

    // ---- remediation audit (round 2): the containment report was resolved and discarded --------

    /// The report the EXECUTION wrote about itself must be about the run being attested. It used to
    /// be resolved by content address and never opened, so a containment report describing any other
    /// attempt satisfied the signer's "§1.5 containment gate" completely.
    #[test]
    fn a_containment_report_about_another_run_is_refused() {
        let f = fixture();
        for (field, wrong) in [("run_id", "run-2"), ("execution_attempt_id", "EA-2")] {
            let mut doc = f.doc("containment_evidence_handle");
            doc[field] = json!(wrong);
            assert_eq!(
                f.sign_with_containment(&doc)["reason"],
                json!(format!("{REASON_CHAIN_DISAGREEMENT}:containment_evidence_handle.{field}")),
                "a containment report naming {field}={wrong} was accepted"
            );
        }
        let _ = std::fs::remove_dir_all(&f.store);
    }

    /// And about the same REPLY. This is the field that matters most: the containment report is the
    /// execution's account of what it produced, so a report naming other output bytes beside a
    /// receipt attesting these ones is two documents disagreeing about the answer the desktop is
    /// going to commit.
    #[test]
    fn a_containment_report_naming_other_output_bytes_is_refused() {
        let f = fixture();
        let mut doc = f.doc("containment_evidence_handle");
        doc["output_handle"] = json!(blob(&f.store, b"some other reply entirely"));
        assert_eq!(
            f.sign_with_containment(&doc)["reason"],
            json!(format!("{REASON_CHAIN_DISAGREEMENT}:containment_evidence_handle.output_handle"))
        );
        let _ = std::fs::remove_dir_all(&f.store);
    }

    /// A blob that is not a containment report at all, and one that carries only its protocol tag.
    /// Both resolved fine under the existence check this replaces.
    #[test]
    fn a_containment_report_that_is_vacuous_or_mislabelled_is_refused() {
        let f = fixture();
        assert_eq!(
            f.sign_with_containment(&json!({ "protocol": "something.else" }))["reason"],
            json!(format!("{REASON_CHAIN_DISAGREEMENT}:containment_evidence_handle.protocol"))
        );
        assert_eq!(
            f.sign_with_containment(&json!({ "protocol": "brops.containment-evidence.v1" }))["reason"],
            json!(format!("{REASON_CHAIN_DISAGREEMENT}:containment_evidence_handle.run_id_missing"))
        );
        // The opaque blob the fixture used to publish here — the shape the old existence check
        // waved straight through.
        let opaque = blob(&f.store, b"containment");
        let mut record = f.doc("record_handle");
        record["containment_evidence_handle"] = json!(opaque);
        let mut evidence = f.evidence.clone();
        evidence.insert("containment_evidence_handle".into(), json!(opaque));
        evidence.insert(
            "record_handle".into(),
            json!(blob(&f.store, &serde_json::to_vec(&record).unwrap())),
        );
        assert_eq!(f.sign(evidence)["reason"], json!("handle_unreadable"));
        let _ = std::fs::remove_dir_all(&f.store);
    }

    #[test]
    fn the_lease_and_receipt_must_be_about_this_attempt_too() {
        let f = fixture();
        let mut lease = f.doc("lease_handle");
        lease["execution_attempt_id"] = json!("EA-2");
        assert_eq!(
            f.sign_with("lease_handle", &lease)["reason"],
            json!(format!("{REASON_CHAIN_DISAGREEMENT}:lease_handle.execution_attempt_id"))
        );
        let mut receipt = f.doc("execution_receipt_handle");
        receipt["output_handle"] = json!("ff".repeat(32));
        assert_eq!(
            f.sign_with("execution_receipt_handle", &receipt)["reason"],
            json!(format!("{REASON_CHAIN_DISAGREEMENT}:execution_receipt_handle.output_handle"))
        );
        // A lease with no attempt id at all is not "nothing to check" — it is a missing account.
        let bare = f.sign_with("lease_handle", &json!({ "lease_id": "L-1" }));
        assert_eq!(
            bare["reason"],
            json!(format!("{REASON_CHAIN_DISAGREEMENT}:lease_handle.execution_attempt_id_missing")),
            "{bare}"
        );
        let _ = std::fs::remove_dir_all(&f.store);
    }

    #[test]
    fn a_missing_chain_blob_is_still_refused() {
        let f = fixture();
        let mut evidence = f.evidence.clone();
        evidence.insert("record_handle".into(), json!("ab".repeat(32)));
        assert_eq!(f.sign(evidence)["reason"], json!("handle_missing"));
        let _ = std::fs::remove_dir_all(&f.store);
    }
}

#[cfg(test)]
mod evidence_tests {
    use super::*;

    // (audit F-01/F-02, remediation audit) The Windows twin carried the ORIGINAL F-02 defect —
    // four `evidence_*` deployment constants on the wire — after the ledger had marked F-02
    // CLOSED on the strength of the Linux fix alone. And this kit had no CI coverage of the
    // property at all. These run on the Linux CI runner: `derive_evidence` is pure file + JSON
    // work with no Windows API in it, so "Windows-only" was never a reason not to test it.

    fn chain(dir: &std::path::Path, attempt: &str, output_sha256: &str, head: i64) {
        std::fs::create_dir_all(dir).unwrap();
        let bytes = crate::execution::build_run_evidence(attempt, output_sha256, 42, head);
        std::fs::write(dir.join(format!("{attempt}.evidence.json")), bytes).unwrap();
    }

    fn tmp() -> std::path::PathBuf {
        let d = std::env::temp_dir().join(format!("brops-winlive-ev-{}", brops_core::id()));
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    #[test]
    fn the_head_is_derived_from_the_chain_not_from_a_constant() {
        let dir = tmp();
        chain(&dir, "att-1", &"ab".repeat(32), 9);
        let e = derive_evidence(&dir, "att-1").expect("derives");
        assert_eq!(e.output_sha256, "ab".repeat(32));
        assert_eq!((e.event_count, e.last_sequence, e.head_sequence), (3, 3, 9));
        assert_eq!(e.final_event_hash.len(), 64);
        // Two runs with different output produce different heads — the property a constant cannot
        // have, and the reason the anti-rollback floor was comparing a value against itself.
        chain(&dir, "att-2", &"cd".repeat(32), 10);
        let other = derive_evidence(&dir, "att-2").expect("derives");
        assert_ne!(e.final_event_hash, other.final_event_hash);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn an_absent_or_tampered_chain_yields_nothing() {
        let dir = tmp();
        assert!(derive_evidence(&dir, "att-missing").is_none());
        chain(&dir, "att-3", &"ab".repeat(32), 1);
        // Flip the recorded digest without re-deriving the payload digest: the event commits to
        // its own payload, so this must not parse.
        let path = dir.join("att-3.evidence.json");
        let raw = std::fs::read_to_string(&path).unwrap();
        std::fs::write(&path, raw.replace(&"ab".repeat(32), &"ff".repeat(32))).unwrap();
        assert!(derive_evidence(&dir, "att-3").is_none());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn an_attempt_id_cannot_walk_out_of_the_evidence_directory() {
        let dir = tmp();
        for hostile in ["../secret", "a/b", "..", "att 1"] {
            assert!(derive_evidence(&dir, hostile).is_none(), "{hostile}");
        }
        let _ = std::fs::remove_dir_all(&dir);
    }
}
