//! Phase-2 (Governance Sidecar) — the desktop READ-ONLY governance mirror IPC.
//!
//! "Mirror, never decide." These Tauri commands READ engine governance surfaces —
//! the decision ledger, the evidence chain, the verifier verdicts, and the engine
//! approval QUEUE — by asking the governed engine sidecar (the SAME subprocess the
//! governed AI turn uses, via [`crate::ai::governed_sidecar_read`]). They exist to
//! surface engine truth honestly, not to author it. Concretely, every command here:
//!
//!   * is READ-ONLY. None takes `State<AppState>`, so none can touch the local
//!     database; none takes a key, lease, nonce, verdict, or any decision/mutation
//!     input, so there is no parameter through which the desktop could decide or
//!     cache authority. The ONLY inputs are optional read filters (a `task_id`).
//!   * caches NOTHING. The reply is validated and returned; no key or lease is ever
//!     stored (there is nowhere to store one — see above).
//!   * is FAIL-CLOSED. A command NEVER throws to the renderer and NEVER fabricates
//!     data. Any unreachable engine, non-governed configuration, non-zero exit,
//!     malformed reply, engine refusal, or schema-invalid record becomes a typed
//!     [`GovernanceRead::Unreachable`] or [`GovernanceRead::Blocked`] — the honest
//!     blocked state the Phase-2 DoD requires. A `trusted`/`verified` mirror is only
//!     ever produced from a well-formed, schema-valid engine reply; the desktop
//!     itself never mints one.
//!   * validates engine JSON against the existing engine schemas
//!     (`engine/schemas/verifier-receipt.schema.json`,
//!     `engine/schemas/evidence-event.schema.json`) and rejects anything that does
//!     not conform (fail-closed).
//!
//! # What this mirror does NOT establish (read this before trusting a record)
//!
//! Validation here is SCHEMA-SHAPE ONLY. It is not authentication:
//!
//!   * The engine artifacts have no signature to check. Both schemas declare
//!     `"additionalProperties": false` and neither lists a signature/MAC field, so a
//!     conforming record CANNOT carry one — there is nothing for this module to
//!     verify, and no trusted-key material is reachable from this read path.
//!   * The source is unauthenticated. The reply comes from whatever process
//!     `BROPS_GOVERNED_SIDECAR` names (see [`crate::ai`]); the desktop does not
//!     authenticate that process, so any writer of well-formed JSON on that pipe
//!     produces records that pass every check in this file.
//!
//! Consequence: a `GovernanceRead::Ok` means "well-formed records arrived from the
//! configured sidecar", NOT "these records are genuine engine truth". Every `Ok`
//! therefore carries [`GovernanceRead::Ok::authenticated`] = `false`, which the
//! renderer MUST surface — a GREEN verdict or a satisfied evidence node resting on
//! this data without saying it is unauthenticated is a false claim.
//!
//! # The engine's own explanation travels with the read
//!
//! A three-valued read collapses to a blank page unless the REASON travels with it.
//! The engine answers an empty surface with a sentence about its own store ("the
//! orchestration runtime holds no tasks, so nothing has been recorded"), plus its
//! record count, whether it has ever heard of the filtered task, and which store it
//! read. Those used to be parsed and thrown away here, leaving the owner an empty page
//! with no way to tell "there is nothing to show" from "there is nothing to show
//! BECAUSE …". They are now relayed in [`GovernanceRead::Ok::engine`] as the ENGINE's
//! claims, attributed — the desktop verified none of them and must not restate them as
//! its own findings. The three values (records / empty / blocked) stay exactly as
//! distinct as they were; the explanation sits beside them, never in place of them.
//!
//! # What answers on the other end (corrected 2026-08-15)
//!
//! This paragraph read *"the Phase-2 engine read endpoints do not answer yet, in practice
//! every command below returns `Unreachable`/`Blocked` today"*. **That has stopped being
//! true and nothing noticed** — the repository's signature defect, an honest comment
//! written the moment it was true and never revisited. All four surfaces are served:
//! `bro_control_room_api.GOVERNANCE_SURFACES` names exactly `decisionLedger`,
//! `evidenceChain`, `verdicts` and `approvalQueue` (`:47`), `governance_read` dispatches
//! all four (`:568`, `:616-621`), and `bridge/engine_sidecar.py` relays the reply verbatim
//! (`_op_governance_read`, `:477`, wired at `:808`).
//!
//! What is still true is narrower and is the part that matters: a **shipped** install
//! reaches `Blocked`, because the engine refuses the read until
//! `BROPS_GOVERNANCE_STATE_DIR` names a provisioned mirror and nothing in the app sets it.
//! So the steady state is unchanged; the REASON for it is a deployment input, not a
//! missing endpoint, and a page that says "the engine has not been built yet" would now be
//! telling the owner the wrong thing.
//!
//! # What this module does NOT carry: the approval-REQUEST path
//!
//! Phase 2's Definition of Done pairs the read IPC with *"the approval-**request** path
//! works"* — the desktop POSTing an owner approval **request** that the engine's Ed25519
//! system adjudicates. **No such path exists, on either side.** There is no
//! `approval-request` schema in `engine/schemas/` (21 schemas; none is one), no
//! desktop→engine command, and `read_engine_approval_queue` below is the QUEUE READ ONLY.
//! The grant/deny/escalate buttons on the `approvals` page drive the **desktop's own**
//! approval system (T-010/T-011: `confirm_approval` / `reject_approval` /
//! `escalate_approval` over local SQLite, behind a native dialog the webview cannot forge)
//! — a real authority, but the desktop's, not a request to the engine.
//!
//! That gap is deliberate and Phase 2 pre-authorised it in its own Contracts section: an
//! `approval-request` shape that needs an engine schema change is *"an audited engine
//! task, flagged, not done here"*. It is flagged here rather than left for a reader to
//! infer from an unticked box.

use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Cap on any engine/parse reason string echoed to the UI, so a hostile or huge
/// sidecar error can neither bloat the reply nor let the raw text diverge from a
/// bounded, displayable form.
const MAX_REASON_CHARS: usize = 400;

fn bounded(reason: &str) -> String {
    let cleaned: String = reason.chars().filter(|c| !c.is_control() || *c == ' ').collect();
    let cleaned = cleaned.trim();
    if cleaned.chars().count() <= MAX_REASON_CHARS {
        cleaned.to_string()
    } else {
        let head: String = cleaned.chars().take(MAX_REASON_CHARS).collect();
        format!("{head}…")
    }
}

/// The typed outcome of a governance mirror read. Serialized with an internal
/// `state` tag so the renderer switches on one honest field — there is no shape in
/// which fabricated data can masquerade as `ok`, and `blocked`/`unreachable` are
/// first-class (not errors) so a fail-closed engine reads as an honest state.
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", tag = "state")]
pub enum GovernanceRead {
    /// The engine mirrored these records; every record conforms to its engine
    /// schema. Read-only — the desktop neither authored nor decided any of it.
    ///
    /// `records` MAY be empty: an `ok` reply carrying zero records means the sidecar
    /// had nothing to mirror. That is an EMPTY chain, not a satisfied one — the
    /// renderer must show "no evidence", never a green/verified node.
    ///
    /// `authenticated` reports whether the records' origin was cryptographically
    /// verified. It is `false` in this build and is emitted on every `ok` so the
    /// renderer cannot forget: the engine schemas define no signature field and no
    /// trusted key is reachable here, so nothing on this path is authenticated (see
    /// the module docs). It exists as a field rather than a comment precisely so a
    /// future signature check can flip it and the UI follows.
    ///
    /// `engine` relays what the ENGINE said about its own store alongside the records
    /// — above all the sentence explaining WHY a surface is empty. It is the engine's
    /// claim, attributed, never a desktop finding (see [`EngineAccount`]).
    Ok { surface: String, records: Vec<Value>, authenticated: bool, engine: EngineAccount },
    /// The engine was reached but explicitly refused the read, returned a
    /// malformed/`ok:false` result, or returned a record that fails its schema
    /// (fail-closed). Honest "blocked", never fabricated data.
    Blocked { surface: String, reason: String },
    /// The engine sidecar could not be reached / is not configured / did not
    /// respond (fail-closed). Honest "unreachable", never fabricated data.
    Unreachable { surface: String, reason: String },
}

/// What the ENGINE said about its own store, relayed beside the records it sent.
///
/// Every field here is the engine SPEAKING ABOUT ITSELF. The desktop did not open the
/// engine's state directory, count anything, or check any signature, so it can only
/// attribute — the renderer must present these as the engine's words, never restate
/// them in the app's own voice as if the desktop had established them.
///
/// This exists because the three-valued read was arriving stripped of its reason. The
/// engine distinguishes "the orchestration runtime holds no tasks, so nothing has been
/// recorded" from "the orchestration runtime has no task 't-7'" from "no task is
/// waiting on an owner approval" — three very different empty pages. Dropping the
/// sentence left the owner with a blank surface and no way to tell which one it was,
/// which is the difference between "there is nothing to show" and "there is nothing to
/// show BECAUSE …".
///
/// # What is deliberately NOT here: `record_authentication`
///
/// The engine's reply also carries `record_authentication` (`ed25519-signature-verified`
/// / `runtime-hash-chain-verified`). That is the engine's claim about how ITS store
/// establishes records — it is NOT a desktop-performed check, and it is NOT read here.
/// [`RECORDS_ARE_AUTHENTICATED`] stays `false` regardless of what that field says: the
/// desktop authenticates neither the records (the schemas define no signature field)
/// nor the process on the pipe. Wiring the engine's word into `authenticated` would
/// launder a self-assertion into a verified badge, so the field is dropped on purpose
/// and a test below pins that.
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct EngineAccount {
    /// The engine's own sentence for why this surface came back empty. Carried ONLY
    /// when the mirrored record set is genuinely empty, so an explanation of emptiness
    /// can never appear beside records.
    pub empty_reason: Option<String>,
    /// The engine's own count of the records it read. Kept as the engine's claim; the
    /// number a page shows is always the length of the list the desktop validated.
    pub record_count: Option<u64>,
    /// Only present when the read was filtered to one task: whether the engine's
    /// orchestration runtime has ever heard of that id. Lets a page tell "this task
    /// recorded nothing" from "the engine does not know this task" instead of guessing
    /// from an empty list.
    pub known_task: Option<bool>,
    /// `source.kind` — the engine's name for the store it actually read (e.g.
    /// `orchestration-runtime-transitions`, `signed-evidence-store`). The rest of
    /// `source` (state-dir path, integrity root hash) is deliberately not surfaced: a
    /// hash the desktop never verified reads as proof, and this mirror proves nothing.
    pub source_kind: Option<String>,
}

/// Read the engine's account of a successful (`ok:true`) reply.
///
/// Fail-quiet per field, never fail-open: a missing or wrongly-typed field yields
/// `None` (the explanation is simply absent), and no field here can turn a read into
/// `ok` or upgrade its trust — the account is descriptive only. Strings are bounded
/// like every other engine-supplied text this module echoes.
fn engine_account(doc: &Value, mirrored: usize) -> EngineAccount {
    let text = |v: Option<&Value>| -> Option<String> {
        v.and_then(|v| v.as_str()).map(bounded).filter(|s| !s.is_empty())
    };
    EngineAccount {
        // Only when the surface really is empty. An engine that sent both records and
        // an "it is empty because…" sentence is contradicting itself; the records are
        // what the page shows, so the sentence is dropped rather than displayed under
        // them.
        empty_reason: if mirrored == 0 { text(doc.get("empty_reason")) } else { None },
        record_count: doc.get("record_count").and_then(|v| v.as_u64()),
        known_task: doc.get("known_task").and_then(|v| v.as_bool()),
        source_kind: text(doc.get("source").and_then(|s| s.get("kind"))),
    }
}

/// Refuse a reply whose own record count contradicts the records it sent.
///
/// Nothing on this path filters the list — a validated record is kept or the WHOLE read
/// fails — so the engine's count and the mirrored list must agree. If they do not, the
/// reply is not internally consistent, and relaying that count as the engine's own claim
/// beside a different list would publish the inconsistency as fact. Fail closed instead.
fn count_disagreement(doc: &Value, sent: usize) -> Option<String> {
    let claimed = doc.get("record_count").and_then(|v| v.as_u64())?;
    if claimed == sent as u64 {
        return None;
    }
    Some(format!(
        "inconsistent engine reply: it reports record_count {claimed} but sent {sent} records"
    ))
}

/// A verifier verdict receipt — the read shape of
/// `engine/schemas/verifier-receipt.schema.json`. Parsed + validated read-only;
/// the desktop never issues one (no signing key crosses this boundary).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct VerifierReceipt {
    pub receipt_id: String,
    pub key_id: String,
    pub task_id: String,
    pub builder_agent_id: String,
    pub verifier_agent_id: String,
    pub verifier_role: String,
    pub independence_level: String,
    pub task_contract_sha256: String,
    pub completion_manifest_sha256: String,
    pub candidate_head: String,
    pub candidate_tree: String,
    pub evidence_event_ids: Vec<String>,
    pub verdict: String,
    pub issued_at_epoch: i64,
    pub expires_at_epoch: i64,
}

/// An evidence-chain event — the read shape of
/// `engine/schemas/evidence-event.schema.json`. Parsed + validated read-only.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct EvidenceEvent {
    pub event_id: String,
    pub previous_event_hash: Option<String>,
    pub task_id: String,
    pub event_type: String,
    pub agent_id: String,
    pub payload_hash: String,
    pub issued_at_epoch: i64,
    pub key_id: String,
}

// --- schema validators (fail-closed) -----------------------------------------------

fn is_hex_of_len(s: &str, len: usize) -> bool {
    s.len() == len && s.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

/// The schema id pattern `^[a-z0-9][a-z0-9._-]{1,127}$` (receipt/task/event ids).
fn is_engine_id(s: &str) -> bool {
    let n = s.len();
    if !(2..=128).contains(&n) {
        return false;
    }
    let first = s.as_bytes()[0];
    if !(first.is_ascii_lowercase() || first.is_ascii_digit()) {
        return false;
    }
    s.bytes()
        .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'.' || b == b'_' || b == b'-')
}

/// The agent-id pattern `^agt-p[0-9]{2,}-r[0-9]{2,}$`.
fn is_agent_id(s: &str) -> bool {
    let rest = match s.strip_prefix("agt-p") {
        Some(r) => r,
        None => return false,
    };
    let (p, r) = match rest.split_once("-r") {
        Some(pr) => pr,
        None => return false,
    };
    p.len() >= 2 && p.bytes().all(|b| b.is_ascii_digit())
        && r.len() >= 2 && r.bytes().all(|b| b.is_ascii_digit())
}

fn req_str<'a>(o: &'a Value, k: &str) -> Result<&'a str, String> {
    o.get(k)
        .and_then(|v| v.as_str())
        .ok_or_else(|| format!("missing or non-string field '{k}'"))
}

fn req_int(o: &Value, k: &str) -> Result<i64, String> {
    let n = o
        .get(k)
        .and_then(|v| v.as_i64())
        .ok_or_else(|| format!("missing or non-integer field '{k}'"))?;
    if n < 0 {
        return Err(format!("field '{k}' must be >= 0"));
    }
    Ok(n)
}

/// Validate + parse one verifier receipt against verifier-receipt.schema.json. The
/// security-load-bearing constraints (schema==1, artifact_type, verdict==GREEN, the
/// hash/id patterns, a non-empty evidence list) are all enforced; anything off is a
/// hard error (fail-closed).
pub fn parse_verifier_receipt(o: &Value) -> Result<VerifierReceipt, String> {
    if o.get("schema").and_then(|v| v.as_i64()) != Some(1) {
        return Err("verifier-receipt: schema must be 1".to_string());
    }
    if o.get("artifact_type").and_then(|v| v.as_str()) != Some("verifier-receipt") {
        return Err("verifier-receipt: artifact_type must be 'verifier-receipt'".to_string());
    }
    // The engine only signs GREEN verdicts; any other value is not a valid receipt.
    let verdict = req_str(o, "verdict")?;
    if verdict != "GREEN" {
        return Err(format!("verifier-receipt: verdict must be 'GREEN', got '{verdict}'"));
    }
    let receipt_id = req_str(o, "receipt_id")?;
    if !is_engine_id(receipt_id) {
        return Err("verifier-receipt: receipt_id does not match the engine id pattern".to_string());
    }
    let task_id = req_str(o, "task_id")?;
    if !is_engine_id(task_id) {
        return Err("verifier-receipt: task_id does not match the engine id pattern".to_string());
    }
    let key_id = req_str(o, "key_id")?;
    if key_id.is_empty() {
        return Err("verifier-receipt: key_id must be non-empty".to_string());
    }
    let builder_agent_id = req_str(o, "builder_agent_id")?;
    let verifier_agent_id = req_str(o, "verifier_agent_id")?;
    if !is_agent_id(builder_agent_id) || !is_agent_id(verifier_agent_id) {
        return Err("verifier-receipt: agent id does not match the agent pattern".to_string());
    }
    let verifier_role = req_str(o, "verifier_role")?;
    if verifier_role.is_empty() {
        return Err("verifier-receipt: verifier_role must be non-empty".to_string());
    }
    let independence_level = req_str(o, "independence_level")?;
    if !matches!(independence_level, "L1" | "L2" | "L3" | "L4" | "L5") {
        return Err("verifier-receipt: independence_level must be L1..L5".to_string());
    }
    let task_contract_sha256 = req_str(o, "task_contract_sha256")?;
    let completion_manifest_sha256 = req_str(o, "completion_manifest_sha256")?;
    let candidate_tree = req_str(o, "candidate_tree")?;
    for (name, v) in [
        ("task_contract_sha256", task_contract_sha256),
        ("completion_manifest_sha256", completion_manifest_sha256),
        ("candidate_tree", candidate_tree),
    ] {
        if !is_hex_of_len(v, 64) {
            return Err(format!("verifier-receipt: {name} must be 64 lowercase hex chars"));
        }
    }
    let candidate_head = req_str(o, "candidate_head")?;
    if !is_hex_of_len(candidate_head, 40) {
        return Err("verifier-receipt: candidate_head must be 40 lowercase hex chars".to_string());
    }
    let evidence_event_ids: Vec<String> = o
        .get("evidence_event_ids")
        .and_then(|v| v.as_array())
        .ok_or_else(|| "verifier-receipt: evidence_event_ids must be an array".to_string())?
        .iter()
        .map(|v| {
            v.as_str()
                .filter(|s| !s.is_empty())
                .map(|s| s.to_string())
                .ok_or_else(|| "verifier-receipt: evidence_event_ids entries must be non-empty strings".to_string())
        })
        .collect::<Result<_, _>>()?;
    if evidence_event_ids.is_empty() {
        return Err("verifier-receipt: evidence_event_ids must have at least one entry".to_string());
    }
    Ok(VerifierReceipt {
        receipt_id: receipt_id.to_string(),
        key_id: key_id.to_string(),
        task_id: task_id.to_string(),
        builder_agent_id: builder_agent_id.to_string(),
        verifier_agent_id: verifier_agent_id.to_string(),
        verifier_role: verifier_role.to_string(),
        independence_level: independence_level.to_string(),
        task_contract_sha256: task_contract_sha256.to_string(),
        completion_manifest_sha256: completion_manifest_sha256.to_string(),
        candidate_head: candidate_head.to_string(),
        candidate_tree: candidate_tree.to_string(),
        evidence_event_ids,
        verdict: verdict.to_string(),
        issued_at_epoch: req_int(o, "issued_at_epoch")?,
        expires_at_epoch: req_int(o, "expires_at_epoch")?,
    })
}

/// Validate + parse one evidence event against evidence-event.schema.json (fail-closed).
pub fn parse_evidence_event(o: &Value) -> Result<EvidenceEvent, String> {
    if o.get("schema").and_then(|v| v.as_i64()) != Some(1) {
        return Err("evidence-event: schema must be 1".to_string());
    }
    let event_id = req_str(o, "event_id")?;
    if !is_engine_id(event_id) {
        return Err("evidence-event: event_id does not match the engine id pattern".to_string());
    }
    let task_id = req_str(o, "task_id")?;
    if !is_engine_id(task_id) {
        return Err("evidence-event: task_id does not match the engine id pattern".to_string());
    }
    // `previous_event_hash` is nullable (the genesis event) but, when present, a
    // 64-hex chain link.
    let previous_event_hash = match o.get("previous_event_hash") {
        None | Some(Value::Null) => None,
        Some(Value::String(s)) if is_hex_of_len(s, 64) => Some(s.clone()),
        Some(_) => {
            return Err("evidence-event: previous_event_hash must be null or 64 hex chars".to_string())
        }
    };
    let event_type = req_str(o, "event_type")?;
    if event_type.is_empty() {
        return Err("evidence-event: event_type must be non-empty".to_string());
    }
    let agent_id = req_str(o, "agent_id")?;
    if !is_agent_id(agent_id) {
        return Err("evidence-event: agent_id does not match the agent pattern".to_string());
    }
    let payload_hash = req_str(o, "payload_hash")?;
    if !is_hex_of_len(payload_hash, 64) {
        return Err("evidence-event: payload_hash must be 64 lowercase hex chars".to_string());
    }
    let key_id = req_str(o, "key_id")?;
    if key_id.is_empty() {
        return Err("evidence-event: key_id must be non-empty".to_string());
    }
    Ok(EvidenceEvent {
        event_id: event_id.to_string(),
        previous_event_hash,
        task_id: task_id.to_string(),
        event_type: event_type.to_string(),
        agent_id: agent_id.to_string(),
        payload_hash: payload_hash.to_string(),
        issued_at_epoch: req_int(o, "issued_at_epoch")?,
        key_id: key_id.to_string(),
    })
}

/// A generic ledger/queue record. The decision ledger and the engine approval QUEUE
/// have no dedicated engine schema in this build, so the mirror validates only that
/// each record is an object carrying a non-empty string `id` and passes it through
/// verbatim (fail-closed on anything else). It never invents fields or a verdict.
fn parse_identified_record(o: &Value) -> Result<Value, String> {
    let obj = o.as_object().ok_or_else(|| "record must be a JSON object".to_string())?;
    let id_ok = obj
        .get("id")
        .and_then(|v| v.as_str())
        .map(|s| !s.is_empty())
        .unwrap_or(false);
    if !id_ok {
        return Err("record must carry a non-empty string 'id'".to_string());
    }
    Ok(o.clone())
}

/// Records mirrored by this module are NEVER cryptographically authenticated — the
/// engine schemas carry no signature field (`additionalProperties: false`) and no
/// trusted key is reachable from the read path, so there is nothing to verify and
/// the sidecar's identity is not established. Emitted on every `Ok` so the UI can
/// state it. Flip this only together with a real signature check.
///
/// In particular it is NOT the engine's `record_authentication` field. That field is
/// the engine describing its own store ("ed25519-signature-verified"); binding it here
/// would turn a claim the desktop cannot check into a verified badge the UI lights up.
/// The engine's word travels as an attributed claim or not at all.
const RECORDS_ARE_AUTHENTICATED: bool = false;

/// The two values the engine can send as `record_authentication`, naming how IT established
/// the records in its own store. Held as constants rather than written inline at each test
/// fixture for one boring reason and one real one: the boring one is that a fixture asserting an
/// exact string should not restate it, and the real one is that an inline
/// `"record_authentication": "<long-hyphenated-value>"` is shaped exactly like a leaked
/// credential and the secret scanner says so. The VALUES are the engine's own
/// (`bro_control_room_api._ED25519`) and are not changed to suit a scanner -- a fixture that
/// stops matching production stops testing it.
// Test-only: both are read exclusively from fixtures below. Marked as such rather than left to
// warn — an `unused` warning on a security-vocabulary constant is the kind of noise people learn
// to scroll past, and the next real one scrolls past with it.
#[cfg(test)]
const ENGINE_CLAIM_SIGNED: &str = "ed25519-signature-verified";
#[cfg(test)]
const ENGINE_CLAIM_HASH_CHAIN: &str = "runtime-hash-chain-verified";

/// Pull the `records` array out of a successful (`ok:true`) sidecar reply and validate
/// every entry with `parse_one`, re-serializing each validated record. A single
/// invalid record fails the WHOLE read (fail-closed): a partly-fabricated mirror is
/// never shown as `ok`.
///
/// An EMPTY `records` array is well-formed and yields an empty `Vec` — the read
/// succeeded and there is simply nothing to show. Callers/renderers must not read
/// that as satisfied evidence (see [`GovernanceRead::Ok`]).
fn validate_records<T, F>(doc: &Value, parse_one: F) -> Result<Vec<Value>, String>
where
    T: Serialize,
    F: Fn(&Value) -> Result<T, String>,
{
    let arr = doc
        .get("records")
        .and_then(|v| v.as_array())
        .ok_or_else(|| "engine reply is missing a 'records' array".to_string())?;
    let mut out = Vec::with_capacity(arr.len());
    for (i, rec) in arr.iter().enumerate() {
        let parsed = parse_one(rec).map_err(|e| format!("record #{i}: {e}"))?;
        let value = serde_json::to_value(&parsed)
            .map_err(|e| format!("record #{i}: could not re-serialize ({e})"))?;
        out.push(value);
    }
    Ok(out)
}

/// Map a raw sidecar read (`Result<reply, transport-error>`) into a typed
/// [`GovernanceRead`], fail-closed. PURE — unit-testable without a subprocess.
///
///   * transport `Err`  → `Unreachable` (could not reach/parse the engine at all)
///   * reply `ok:false` → `Blocked` (engine reached but refused the read)
///   * reply `ok:true` but a record fails its schema → `Blocked` (never `Ok`)
///   * reply `ok:true` and every record valid → `Ok`
fn classify<F>(surface: &str, reply: Result<Value, String>, validate: F) -> GovernanceRead
where
    F: Fn(&Value) -> Result<Vec<Value>, String>,
{
    match reply {
        Err(e) => GovernanceRead::Unreachable { surface: surface.to_string(), reason: bounded(&e) },
        Ok(doc) => {
            let ok = doc.get("ok").and_then(|v| v.as_bool()).unwrap_or(false);
            if !ok {
                let reason = doc
                    .get("error")
                    .and_then(|e| e.as_str())
                    .filter(|s| !s.is_empty())
                    .unwrap_or("engine refused the governance read (ok:false)");
                return GovernanceRead::Blocked {
                    surface: surface.to_string(),
                    reason: bounded(reason),
                };
            }
            match validate(&doc) {
                Ok(records) => {
                    if let Some(reason) = count_disagreement(&doc, records.len()) {
                        return GovernanceRead::Blocked { surface: surface.to_string(), reason };
                    }
                    let engine = engine_account(&doc, records.len());
                    GovernanceRead::Ok {
                        surface: surface.to_string(),
                        records,
                        // Schema-shape only. Never claim more than that (module docs).
                        // NOT derived from the engine's `record_authentication` — that is
                        // the engine's word about its own store, not a desktop check.
                        authenticated: RECORDS_ARE_AUTHENTICATED,
                        engine,
                    }
                }
                Err(e) => GovernanceRead::Blocked {
                    surface: surface.to_string(),
                    reason: format!("schema-invalid engine reply: {}", bounded(&e)),
                },
            }
        }
    }
}

/// Build the read-only governance request the sidecar receives on stdin. It carries
/// ONLY the surface name and an optional read filter plus an explicit `read_only`
/// assertion — no key, lease, nonce, or decision. (Data, never authority.)
fn governance_request(surface: &str, task_id: Option<&str>) -> String {
    serde_json::json!({
        "protocol": "brops.governance-read.v1",
        "op": "governance.read",
        "surface": surface,
        "task_id": task_id,
        "read_only": true,
    })
    .to_string()
}

/// Shared mirror path: ask the sidecar for `surface`, then classify the reply.
async fn mirror<F>(surface: &str, task_id: Option<String>, validate: F) -> GovernanceRead
where
    F: Fn(&Value) -> Result<Vec<Value>, String>,
{
    let request = governance_request(surface, task_id.as_deref());
    let reply = crate::ai::governed_sidecar_read(&request).await;
    classify(surface, reply, validate)
}

// --- commands (READ-ONLY; no AppState, no key/lease params) -------------------------

/// Mirror the engine decision LEDGER (read-only). No decision is authored or altered.
#[tauri::command]
pub async fn read_decision_ledger() -> GovernanceRead {
    mirror("decisionLedger", None, |doc| validate_records(doc, parse_identified_record)).await
}

/// Mirror the engine EVIDENCE CHAIN (read-only), optionally filtered to one task.
/// Records are validated against evidence-event.schema.json; a non-conforming chain
/// reads as `Blocked`, never a fabricated "verified" chain.
#[tauri::command]
pub async fn read_evidence_chain(task_id: Option<String>) -> GovernanceRead {
    mirror("evidenceChain", task_id, |doc| validate_records(doc, parse_evidence_event)).await
}

/// Mirror the engine verifier VERDICTS (read-only), optionally filtered to one task.
/// Records are validated against verifier-receipt.schema.json (verdict must be GREEN).
#[tauri::command]
pub async fn read_verifier_verdicts(task_id: Option<String>) -> GovernanceRead {
    mirror("verdicts", task_id, |doc| validate_records(doc, parse_verifier_receipt)).await
}

/// Mirror the engine approval QUEUE (read-only). This is the QUEUE READ ONLY — it
/// carries no approve/deny/request authority (approval-request POST is a separate,
/// gated engine task and is intentionally NOT part of this surface).
#[tauri::command]
pub async fn read_engine_approval_queue() -> GovernanceRead {
    mirror("approvalQueue", None, |doc| validate_records(doc, parse_identified_record)).await
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn valid_receipt() -> Value {
        json!({
            "schema": 1,
            "artifact_type": "verifier-receipt",
            "key_id": "k-1",
            "receipt_id": "r-abc.1",
            "task_id": "t-abc.1",
            "builder_agent_id": "agt-p01-r02",
            "verifier_agent_id": "agt-p03-r04",
            "verifier_role": "independent-verifier",
            "independence_level": "L3",
            "task_contract_sha256": "a".repeat(64),
            "completion_manifest_sha256": "b".repeat(64),
            "candidate_head": "c".repeat(40),
            "candidate_tree": "d".repeat(64),
            "evidence_event_ids": ["ev-1", "ev-2"],
            "verdict": "GREEN",
            "issued_at_epoch": 1000,
            "expires_at_epoch": 2000
        })
    }

    fn valid_event() -> Value {
        json!({
            "schema": 1,
            "event_id": "ev-1",
            "previous_event_hash": null,
            "task_id": "t-abc.1",
            "event_type": "build.completed",
            "agent_id": "agt-p01-r02",
            "payload_hash": "e".repeat(64),
            "issued_at_epoch": 1000,
            "key_id": "k-1"
        })
    }

    // --- schema parse: happy path ---

    #[test]
    fn parses_a_schema_valid_green_receipt() {
        let r = parse_verifier_receipt(&valid_receipt()).expect("valid receipt parses");
        assert_eq!(r.verdict, "GREEN");
        assert_eq!(r.evidence_event_ids, vec!["ev-1", "ev-2"]);
        assert_eq!(r.independence_level, "L3");
    }

    #[test]
    fn parses_a_schema_valid_evidence_event() {
        let e = parse_evidence_event(&valid_event()).expect("valid event parses");
        assert_eq!(e.event_id, "ev-1");
        assert!(e.previous_event_hash.is_none());
    }

    #[test]
    fn evidence_event_accepts_a_64hex_previous_hash() {
        let mut ev = valid_event();
        ev["previous_event_hash"] = json!("f".repeat(64));
        let e = parse_evidence_event(&ev).expect("valid event parses");
        assert_eq!(e.previous_event_hash.as_deref(), Some("f".repeat(64).as_str()));
    }

    // --- schema parse: fail-closed rejections ---

    #[test]
    fn rejects_non_green_verdict() {
        let mut r = valid_receipt();
        r["verdict"] = json!("RED");
        assert!(parse_verifier_receipt(&r).is_err());
    }

    #[test]
    fn rejects_bad_schema_version() {
        let mut r = valid_receipt();
        r["schema"] = json!(2);
        assert!(parse_verifier_receipt(&r).is_err());
    }

    /// The other mirror's discriminator — sixth independent audit, `A-02`.
    ///
    /// `rejects_bad_schema_version` above exercises `parse_verifier_receipt` only, and **no test
    /// fed a bad schema to `parse_evidence_event`**. The auditor deleted that function's
    /// discriminator comparison outright on the real repository, with rebuild proof, and got
    /// `cargo test -p brops --lib governance::` at 29 passed and
    /// `tools/check_schema_mirrors.py` GREEN — because the gate's `validates()` searched the
    /// WHOLE FILE for the substring `get("schema")`, and the receipt's own check still contained
    /// it.
    ///
    /// Failure scenario, verbatim: the engine emits an evidence event with `"schema": 2` — same
    /// field names, different semantics. `parse_evidence_event` accepts it, the Security page
    /// renders it as a v1 event, and the gate prints that both mirrors agree.
    ///
    /// A negative test is the half a static reader cannot fake. `check_schema_mirrors.py` now
    /// requires each mirror to NAME one and refuses if it is missing; this is that test, and it
    /// is what actually catches an inverted or deleted comparison.
    #[test]
    fn rejects_bad_evidence_schema_version() {
        let mut ev = valid_event();
        ev["schema"] = json!(2);
        assert!(
            parse_evidence_event(&ev).is_err(),
            "an evidence event declaring schema 2 must be refused, not parsed as v1"
        );
    }

    #[test]
    fn rejects_wrong_artifact_type() {
        let mut r = valid_receipt();
        r["artifact_type"] = json!("something-else");
        assert!(parse_verifier_receipt(&r).is_err());
    }

    #[test]
    fn rejects_short_candidate_head_hash() {
        let mut r = valid_receipt();
        r["candidate_head"] = json!("abc");
        assert!(parse_verifier_receipt(&r).is_err());
    }

    #[test]
    fn rejects_empty_evidence_list() {
        let mut r = valid_receipt();
        r["evidence_event_ids"] = json!([]);
        assert!(parse_verifier_receipt(&r).is_err());
    }

    #[test]
    fn rejects_bad_agent_id() {
        let mut r = valid_receipt();
        r["verifier_agent_id"] = json!("agt-1-2");
        assert!(parse_verifier_receipt(&r).is_err());
    }

    #[test]
    fn rejects_evidence_event_with_bad_payload_hash() {
        let mut ev = valid_event();
        ev["payload_hash"] = json!("nothex");
        assert!(parse_evidence_event(&ev).is_err());
    }

    #[test]
    fn a_broken_chain_link_blocks_the_whole_read_rather_than_showing_part_of_it() {
        // Phase-2 DoD: "`blocked` + `error` states proven against engine-unreachable and
        // chain-break". Unreachable had a test; the chain-break half had one only for the
        // engine SAYING the chain broke (`ok_false_reply_maps_to_blocked`). This is the
        // other door: a chain arriving with a malformed link.
        //
        // Say plainly what it does NOT establish, because the gap is easy to over-read in
        // the box's favour. This mirror does not WALK the chain — `parse_evidence_event`
        // checks that `previous_event_hash` is null-or-64-hex and nothing more, and it
        // could not do better: the schema carries no signature, no trusted key is reachable
        // here, and re-deriving a head from records the desktop cannot authenticate would
        // be a check that cannot fail. Detecting a genuine fork is the supervisor's, on
        // both platforms (`governed_supervisor_ledger.py`, `win-live/src/servers.rs`).
        // What is proven here is the boundary rule: a link this mirror CAN see is wrong,
        // and the whole read fails closed rather than rendering the valid records beside it.
        let mut broken = valid_event();
        broken["previous_event_hash"] = json!("not-a-hash");
        assert!(parse_evidence_event(&broken).is_err());

        let doc = json!({ "ok": true, "records": [ valid_event(), broken ], "record_count": 2 });
        match classify("evidenceChain", Ok(doc), |d| validate_records(d, parse_evidence_event)) {
            GovernanceRead::Blocked { reason, .. } => {
                assert!(reason.contains("previous_event_hash"), "reason was: {reason}");
                // Record #1, so the FIRST record really was accepted and the read still
                // failed — a partly-valid mirror is never shown as `ok`.
                assert!(reason.contains("record #1"), "reason was: {reason}");
            }
            other => panic!("expected Blocked, got {other:?}"),
        }

        // The positive control: the same two-record read with an intact link is `ok`, so
        // the assertion above cannot be satisfied by an arm that refuses every chain.
        let mut linked = valid_event();
        linked["event_id"] = json!("ev-2");
        linked["previous_event_hash"] = json!("f".repeat(64));
        let doc = json!({ "ok": true, "records": [ valid_event(), linked ], "record_count": 2 });
        match classify("evidenceChain", Ok(doc), |d| validate_records(d, parse_evidence_event)) {
            GovernanceRead::Ok { records, .. } => assert_eq!(records.len(), 2),
            other => panic!("expected Ok, got {other:?}"),
        }
    }

    #[test]
    fn no_governance_command_can_take_a_key_a_lease_or_the_database() {
        // Phase-2 DoD: "No desktop-side decision authority; no cached keys/leases." That
        // holds structurally — none of the four commands takes `State<AppState>`, so there
        // is nowhere to cache anything, and none takes a key/lease/nonce/verdict, so there
        // is no parameter through which the desktop could decide. Structural is not the
        // same as CHECKED, though: the property lives in four signatures a future command
        // can simply not follow, and the module docs above would go on asserting it.
        //
        // So it is read out of this file's own source. The alternative — a runtime test —
        // cannot exist: the thing being asserted is the ABSENCE of a parameter, which has
        // no value to pass.
        let src = include_str!("governance.rs");
        // Split on a needle assembled at compile time. Writing the attribute as a literal
        // here would make this line itself a fifth "command" — the test found that on its
        // first run, which is the small proof that it is reading the real file.
        let attribute = concat!("#[tauri::", "command]");
        let commands: Vec<&str> = src
            .split(attribute)
            .skip(1)
            .map(|after| after.split(" {").next().unwrap_or(""))
            .collect();
        assert_eq!(commands.len(), 4, "the command count moved; re-reason, do not re-run");
        for sig in commands {
            // The scan is over the PARAMETER LIST, not the whole signature. `verdict` is a
            // forbidden input and also half the name of `read_verifier_verdicts`, and a check
            // that cannot tell those apart is a check that fires on an honest command — this
            // one did, on its first run, which is how the distinction got written down.
            let params = sig.split('(').nth(1).unwrap_or("").split(')').next().unwrap_or("");
            for forbidden in ["State<", "AppState", "key", "lease", "nonce", "verdict", "sign"] {
                assert!(
                    !params.contains(forbidden),
                    "a governance command took `{forbidden}`: {params}"
                );
            }
            // And positively: the only input the mirror is allowed is an optional read filter.
            // The negatives above enumerate what is banned today; this one holds when someone
            // invents an authority nobody thought to ban.
            assert!(
                params.trim().is_empty() || params.trim() == "task_id: Option<String>",
                "a governance command grew a parameter that is not a read filter: {params}"
            );
        }
    }

    // --- classify: fail-closed mapping ---

    #[test]
    fn unreachable_transport_maps_to_unreachable() {
        let got = classify("verdicts", Err("connection refused".into()), |doc| {
            validate_records(doc, parse_verifier_receipt)
        });
        assert!(matches!(got, GovernanceRead::Unreachable { .. }));
    }

    #[test]
    fn ok_false_reply_maps_to_blocked() {
        let doc = json!({ "ok": false, "error": "chain integrity not verifiable" });
        let got = classify("evidenceChain", Ok(doc), |d| validate_records(d, parse_evidence_event));
        match got {
            GovernanceRead::Blocked { reason, .. } => assert!(reason.contains("integrity")),
            other => panic!("expected Blocked, got {other:?}"),
        }
    }

    #[test]
    fn ok_true_with_invalid_record_maps_to_blocked_not_ok() {
        // A fabricated/half-valid record must never surface as `Ok`.
        let doc = json!({ "ok": true, "records": [ { "schema": 1, "verdict": "RED" } ] });
        let got = classify("verdicts", Ok(doc), |d| validate_records(d, parse_verifier_receipt));
        assert!(matches!(got, GovernanceRead::Blocked { .. }));
    }

    #[test]
    fn ok_true_with_valid_records_maps_to_ok() {
        let doc = json!({ "ok": true, "records": [ valid_receipt() ] });
        let got = classify("verdicts", Ok(doc), |d| validate_records(d, parse_verifier_receipt));
        match got {
            GovernanceRead::Ok { records, surface, authenticated, .. } => {
                assert_eq!(surface, "verdicts");
                assert_eq!(records.len(), 1);
                // Schema-valid is NOT authenticated: no signature exists to check.
                assert!(!authenticated);
            }
            other => panic!("expected Ok, got {other:?}"),
        }
    }

    // --- honesty: an `ok` mirror is unauthenticated, and empty means EMPTY ---

    #[test]
    fn an_ok_mirror_is_never_reported_as_authenticated() {
        // The engine schemas carry no signature field and no trusted key is reachable
        // from this read path, so `Ok` must always report authenticated:false — the UI
        // relies on this flag to avoid painting a green verdict on unauthenticated data.
        for doc in [
            json!({ "ok": true, "records": [ valid_receipt() ] }),
            json!({ "ok": true, "records": [] }),
        ] {
            match classify("verdicts", Ok(doc), |d| validate_records(d, parse_verifier_receipt)) {
                GovernanceRead::Ok { authenticated, .. } => assert!(!authenticated),
                other => panic!("expected Ok, got {other:?}"),
            }
        }
    }

    #[test]
    fn empty_records_mirror_as_zero_records_not_as_evidence() {
        // An empty chain is a real, honest answer ("nothing to mirror") — it must not
        // be conflated with a satisfied evidence chain by anything downstream.
        let doc = json!({ "ok": true, "records": [] });
        let got = classify("evidenceChain", Ok(doc), |d| validate_records(d, parse_evidence_event));
        match got {
            GovernanceRead::Ok { records, .. } => assert!(records.is_empty()),
            other => panic!("expected Ok, got {other:?}"),
        }
    }

    #[test]
    fn ok_reply_serializes_the_authenticated_flag_for_the_renderer() {
        // The renderer switches on this JSON; if the flag ever stops being emitted the
        // frontend's fail-closed default (false) still holds, but the contract is here.
        let got = GovernanceRead::Ok {
            surface: "evidenceChain".into(),
            records: vec![],
            authenticated: RECORDS_ARE_AUTHENTICATED,
            engine: EngineAccount {
                empty_reason: Some("the orchestration runtime holds no tasks".into()),
                record_count: Some(0),
                known_task: Some(false),
                source_kind: Some("signed-evidence-store".into()),
            },
        };
        let v = serde_json::to_value(&got).expect("serializes");
        assert_eq!(v["state"], json!("ok"));
        assert_eq!(v["authenticated"], json!(false));
        assert_eq!(v["records"], json!([]));
        // camelCase, because the renderer reads this JSON directly.
        assert_eq!(v["engine"]["emptyReason"], json!("the orchestration runtime holds no tasks"));
        assert_eq!(v["engine"]["recordCount"], json!(0));
        assert_eq!(v["engine"]["knownTask"], json!(false));
        assert_eq!(v["engine"]["sourceKind"], json!("signed-evidence-store"));
    }

    #[test]
    fn missing_records_array_maps_to_blocked() {
        let doc = json!({ "ok": true });
        let got = classify("verdicts", Ok(doc), |d| validate_records(d, parse_verifier_receipt));
        assert!(matches!(got, GovernanceRead::Blocked { .. }));
    }

    #[test]
    fn identified_record_requires_non_empty_id() {
        assert!(parse_identified_record(&json!({ "id": "d-1", "title": "x" })).is_ok());
        assert!(parse_identified_record(&json!({ "id": "" })).is_err());
        assert!(parse_identified_record(&json!({ "title": "no id" })).is_err());
        assert!(parse_identified_record(&json!("not an object")).is_err());
    }

    #[test]
    fn reason_is_bounded() {
        let huge = "x".repeat(5000);
        let got = classify("verdicts", Err(huge), |d| validate_records(d, parse_verifier_receipt));
        match got {
            GovernanceRead::Unreachable { reason, .. } => {
                assert!(reason.chars().count() <= MAX_REASON_CHARS + 1);
            }
            other => panic!("expected Unreachable, got {other:?}"),
        }
    }

    // --- the engine's own explanation survives the read -------------------------------

    /// The empty reply the engine actually sends: three-valued `ok:true` + `empty:true`
    /// + the sentence saying why, plus the count, the task it knows about, and the store
    /// it read.
    fn empty_engine_reply() -> Value {
        json!({
            "protocol": "brops.governance-read.v1",
            "schema": 1,
            "ok": true,
            "surface": "evidenceChain",
            "task_id": "t-abc.1",
            "read_at_epoch": 1000,
            "records": [],
            "record_count": 0,
            "empty": true,
            "empty_reason": "the orchestration runtime holds no tasks, so nothing has been recorded",
            "record_authentication": ENGINE_CLAIM_SIGNED,
            "known_task": false,
            "source": {
                "kind": "signed-evidence-store",
                "evidence_store": "/var/lib/bro/evidence",
                "chain_task_ids": []
            }
        })
    }

    #[test]
    fn an_empty_read_carries_the_engine_reason_it_used_to_drop() {
        // The whole point: "there is nothing to show" and "there is nothing to show
        // BECAUSE the runtime holds no tasks" are different answers to the owner.
        let got = classify("evidenceChain", Ok(empty_engine_reply()), |d| {
            validate_records(d, parse_evidence_event)
        });
        match got {
            GovernanceRead::Ok { records, engine, .. } => {
                assert!(records.is_empty());
                assert_eq!(
                    engine.empty_reason.as_deref(),
                    Some("the orchestration runtime holds no tasks, so nothing has been recorded")
                );
                assert_eq!(engine.record_count, Some(0));
                assert_eq!(engine.known_task, Some(false));
                assert_eq!(engine.source_kind.as_deref(), Some("signed-evidence-store"));
            }
            other => panic!("expected Ok, got {other:?}"),
        }
    }

    #[test]
    fn the_engine_reason_never_appears_beside_records() {
        // An engine that sends records AND an "it is empty because..." sentence is
        // contradicting itself. The records are what the page shows, so the
        // explanation-of-emptiness is dropped rather than printed under them.
        let doc = json!({
            "ok": true,
            "records": [ valid_receipt() ],
            "record_count": 1,
            "empty_reason": "no task has completed under independent verification",
            "source": { "kind": "persisted-verifier-receipts" }
        });
        match classify("verdicts", Ok(doc), |d| validate_records(d, parse_verifier_receipt)) {
            GovernanceRead::Ok { engine, .. } => {
                assert_eq!(engine.empty_reason, None);
                // The rest of the account still travels.
                assert_eq!(engine.record_count, Some(1));
                assert_eq!(engine.source_kind.as_deref(), Some("persisted-verifier-receipts"));
            }
            other => panic!("expected Ok, got {other:?}"),
        }
    }

    #[test]
    fn the_engines_record_authentication_claim_never_becomes_authenticated() {
        // The engine's `record_authentication` is the ENGINE's claim about its own
        // store. The desktop checked no signature and does not authenticate the process
        // on the pipe, so this must not flip `authenticated` -- the flag the UI uses to
        // decide whether it may paint a verified affordance.
        for claim in [ENGINE_CLAIM_SIGNED, ENGINE_CLAIM_HASH_CHAIN] {
            let doc = json!({
                "ok": true,
                "records": [ valid_receipt() ],
                "record_count": 1,
                "record_authentication": claim
            });
            match classify("verdicts", Ok(doc), |d| validate_records(d, parse_verifier_receipt)) {
                GovernanceRead::Ok { authenticated, engine, .. } => {
                    assert!(!authenticated, "the engine's word is not a desktop check");
                    // And it is not smuggled in under another name either.
                    let v = serde_json::to_value(&engine).expect("serializes");
                    let text = v.to_string();
                    assert!(!text.contains(claim), "engine account leaked the claim: {text}");
                }
                other => panic!("expected Ok, got {other:?}"),
            }
        }
    }

    #[test]
    fn a_reply_whose_own_count_disagrees_with_its_records_is_blocked() {
        // Nothing here filters records -- a validated record is kept or the whole read
        // fails -- so the engine's count must match what it sent. If it does not, the
        // reply is not internally consistent and is refused rather than half-relayed.
        let doc = json!({ "ok": true, "records": [ valid_receipt() ], "record_count": 7 });
        match classify("verdicts", Ok(doc), |d| validate_records(d, parse_verifier_receipt)) {
            GovernanceRead::Blocked { reason, .. } => assert!(reason.contains("record_count")),
            other => panic!("expected Blocked, got {other:?}"),
        }
    }

    #[test]
    fn a_missing_or_malformed_account_is_simply_absent_never_fabricated() {
        // Fail-quiet, not fail-open: the read is still `ok`, there is just no
        // explanation to attribute, and nothing is invented to fill the gap.
        let doc = json!({
            "ok": true,
            "records": [],
            "empty_reason": 42,
            "known_task": "yes",
            "source": "not an object"
        });
        match classify("approvalQueue", Ok(doc), |d| validate_records(d, parse_identified_record)) {
            GovernanceRead::Ok { engine, .. } => assert_eq!(engine, EngineAccount::default()),
            other => panic!("expected Ok, got {other:?}"),
        }
    }

    #[test]
    fn a_refusal_carries_no_engine_account_at_all() {
        // A refusal has no `records` key by contract, and it must not grow an
        // explanation-of-emptiness either: "I could not look" is not "I looked and
        // found nothing", and the reason it already carries is the engine's refusal.
        let doc = json!({ "ok": false, "error": "BROPS_GOVERNANCE_STATE_DIR is unset" });
        match classify("decisionLedger", Ok(doc), |d| validate_records(d, parse_identified_record)) {
            GovernanceRead::Blocked { reason, .. } => {
                assert!(reason.contains("BROPS_GOVERNANCE_STATE_DIR"));
            }
            other => panic!("expected Blocked, got {other:?}"),
        }
        let v = serde_json::to_value(GovernanceRead::Blocked {
            surface: "decisionLedger".into(),
            reason: "refused".into(),
        })
        .expect("serializes");
        assert!(v.get("engine").is_none());
        assert!(v.get("records").is_none());
    }

    #[test]
    fn a_hostile_engine_reason_is_bounded_like_every_other_echoed_string() {
        let doc = json!({
            "ok": true,
            "records": [],
            "empty_reason": "z".repeat(5000),
            "source": { "kind": "y".repeat(5000) }
        });
        match classify("approvalQueue", Ok(doc), |d| validate_records(d, parse_identified_record)) {
            GovernanceRead::Ok { engine, .. } => {
                assert!(engine.empty_reason.unwrap().chars().count() <= MAX_REASON_CHARS + 1);
                assert!(engine.source_kind.unwrap().chars().count() <= MAX_REASON_CHARS + 1);
            }
            other => panic!("expected Ok, got {other:?}"),
        }
    }
}
