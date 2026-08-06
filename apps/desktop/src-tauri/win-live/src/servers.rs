//! The three trusted-principal dispatch cores — PURE, host-independent, `serde_json::Value` in/out. They are
//! the Rust twin of `engine/runtime/{challenge_authority,governed_supervisor,isolated_signer}.py`. Each
//! RECOMPUTES every digest it can and signs only its own attested facts; the bytes they sign are exactly what
//! `brops_core::governed_verification::verify_and_accept` verifies. A running Windows bin wraps one of these
//! behind a named pipe (peer-SID authed); the in-process test drives all three directly and asserts
//! `trusted_verified` — the same crypto, no transport.

use crate::crypto;
use ed25519_dalek::{Signature, VerifyingKey};
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

pub const MAX_ID_LEN: usize = 128;
pub const PENDING_TTL_MS: i64 = 30_000;
pub const CHALLENGE_TTL_MS: i64 = 30_000;
pub const LEASE_DURATION_MS: i64 = 210_000;
pub const MIN_LAUNCH_REMAINING_MS: i64 = 180_000;
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
const COMPLETION_HANDLE_FIELDS: [&str; 3] = [
    "output_handle",
    "containment_evidence_handle",
    "evidence_final_event_hash",
];
const COMPLETION_INT_FIELDS: [&str; 4] = [
    "completed_at_ms",
    "evidence_event_count",
    "evidence_last_sequence",
    "evidence_head_sequence",
];
const COMPLETION_FIELDS: [&str; 7] = [
    "output_handle",
    "containment_evidence_handle",
    "evidence_final_event_hash",
    "completed_at_ms",
    "evidence_event_count",
    "evidence_last_sequence",
    "evidence_head_sequence",
];

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
    process_group_id: String,
    cgroup_id: String,
    state: &'static str,
    completion: Option<Completion>,
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
}

impl Supervisor {
    pub fn new(cfg: SupervisorConfig) -> Self {
        Supervisor {
            cfg,
            counter: Mutex::new(0),
            accepted: Mutex::new(BTreeMap::new()),
            by_challenge: Mutex::new(BTreeMap::new()),
        }
    }

    pub fn dispatch(&self, req: &Value, now_ms: i64) -> Value {
        let o = match obj(req) {
            Some(o) => o,
            None => return refuse("?", "malformed"),
        };
        match o.get("op").and_then(Value::as_str) {
            Some("accept-open") => self.accept_open(o, now_ms),
            Some("launch-gate") => self.launch_gate(o, now_ms),
            Some("execution-started") => self.execution_started(o),
            Some("complete-run") => self.complete_run(o),
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
        if !verify_ed25519_hex(&self.cfg.challenge_public_key_hex, &crypto::jcs(payload), sig_b64) {
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
        // content address of the payload it just verified is the key, so a caller cannot obtain a
        // second execution attempt by resubmitting.
        let challenge_handle = crypto::sha256_hex(&crypto::jcs(payload));
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
            cgroup_id: String::new(),
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

    /// `EXECUTION_STARTING → EXECUTING` on confirmed-running process metadata.
    fn execution_started(&self, o: &Map<String, Value>) -> Value {
        if !exact_keys(
            o,
            &["op", "execution_attempt_id", "process_group_id", "cgroup_id",
              "execution_started_marker"],
        ) {
            return refuse("execution-started", "malformed");
        }
        let attempt = match get_str(o, "execution_attempt_id") {
            Some(s) => s,
            None => return refuse("execution-started", "malformed"),
        };
        let mut accepted = self.accepted.lock().unwrap();
        let a = match accepted.get_mut(&attempt) {
            Some(a) => a,
            None => return refuse("execution-started", "unknown_attempt"),
        };
        if a.state != ST_EXECUTION_STARTING {
            return refuse("execution-started", "illegal_state");
        }
        // Durably record what the supervisor observed of the child: this is what the execution
        // receipt it publishes at completion is built from (F-02).
        a.process_group_id = get_str(o, "process_group_id").unwrap_or_default();
        a.cgroup_id = get_str(o, "cgroup_id").unwrap_or_default();
        a.state = ST_EXECUTING;
        json!({ "ok": true, "op": "execution-started", "execution_attempt_id": attempt })
    }

    /// The WRITE-ONCE record of what the run produced. `produced` carries ONLY run-produced values —
    /// every id, nonce, identity and acceptance timestamp is an unknown field, because the supervisor
    /// already holds those and accepting them here would re-open F-01 through a second door.
    fn complete_run(&self, o: &Map<String, Value>) -> Value {
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
        let evidence_final_event_hash = get_str(p, "evidence_final_event_hash").unwrap();
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
                "process_group_id": a.process_group_id, "cgroup_id": a.cgroup_id,
                "completed_at_ms": ints[0], "output_handle": output_handle,
            })
            .as_object()
            .unwrap(),
        );
        let publish = |bytes: &[u8]| -> Option<String> {
            let handle = crypto::sha256_hex(bytes);
            let path = self.cfg.store_dir.join(&handle);
            if !path.exists() {
                std::fs::write(&path, bytes).ok()?;
            }
            Some(handle)
        };
        let (record_handle, lease_handle, execution_receipt_handle) = match (
            publish(&record_bytes),
            publish(&a.lease_payload_bytes),
            publish(&receipt_bytes),
        ) {
            (Some(r), Some(l), Some(e)) => (r, l, e),
            // A store failure must refuse the completion, never name a handle nothing holds.
            _ => return refuse("complete-run", "artifact_publish_failed"),
        };

        let completion = Completion {
            output_handle,
            containment_evidence_handle,
            record_handle,
            lease_handle,
            execution_receipt_handle,
            completed_at_ms: ints[0],
            evidence_final_event_hash,
            evidence_event_count: ints[1],
            evidence_last_sequence: ints[2],
            evidence_head_sequence: ints[3],
        };
        match &a.completion {
            // Write-once: an identical retry is idempotent, any divergence is refused. A second
            // execution cannot rewrite what was already attested.
            Some(existing) => {
                if *existing != completion {
                    return refuse("complete-run", "completion_conflict");
                }
                return json!({
                    "ok": true, "op": "complete-run", "execution_attempt_id": attempt,
                    "recorded": "idempotent"
                });
            }
            None => {
                if a.state != ST_EXECUTING {
                    return refuse("complete-run", "illegal_state");
                }
                a.completion = Some(completion);
                a.state = ST_COMPLETED;
            }
        }
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
        if !verify_ed25519_hex(&self.cfg.supervisor_attestation_public_key_hex, &evidence_jcs, att_sig) {
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
        let containment_evidence_sha256 = match derive("containment_evidence_handle", "containment_missing") {
            Ok(h) => h,
            Err(e) => return e,
        };
        let output_handle = get_str(evidence, "output_handle").unwrap_or_default();
        let output_bytes = match store_read(store, &output_handle) {
            Some(b) => b.len() as u64,
            None => return self.refuse_sign("handle_missing"),
        };
        let output_sha256 = output_handle;
        // Deep-verify the chain handles resolve.
        for k in ["record_handle", "lease_handle", "execution_receipt_handle"] {
            let h = get_str(evidence, k).unwrap_or_default();
            if store_read(store, &h).is_none() {
                return self.refuse_sign("handle_missing");
            }
        }
        let _ = (policy_bundle_sha256, containment_evidence_sha256); // re-derived + resolved (bound via request/handles)

        // request_sha256 recomputed from the signer's OWN derived component hashes.
        let request_sha256 = crypto::request_sha256(
            &get_str(evidence, "workspace_id").unwrap_or_default(),
            &get_str(evidence, "install_id").unwrap_or_default(),
            &request_nonce,
            &system_sha256,
            &history_sha256,
            &generation_config_sha256,
            &requested_at.to_string(),
        );
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

// ---- shared ed25519 verify (hex pubkey, base64url-nopad sig) -----------------------------------

fn verify_ed25519_hex(public_key_hex: &str, msg: &[u8], sig_b64url: &str) -> bool {
    use base64::engine::general_purpose::URL_SAFE_NO_PAD;
    use base64::Engine as _;
    let pk = match crypto::hex32(public_key_hex) {
        Some(b) => b,
        None => return false,
    };
    let vk = match VerifyingKey::from_bytes(&pk) {
        Ok(v) => v,
        Err(_) => return false,
    };
    let sig_bytes = match URL_SAFE_NO_PAD.decode(sig_b64url.as_bytes()) {
        Ok(b) => b,
        Err(_) => return false,
    };
    if sig_bytes.len() != 64 {
        return false;
    }
    let sig = Signature::from_slice(&sig_bytes).ok();
    match sig {
        Some(s) => vk.verify_strict(msg, &s).is_ok(),
        None => false,
    }
}
