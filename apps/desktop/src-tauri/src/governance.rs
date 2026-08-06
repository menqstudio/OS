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
//! Because the Phase-2 engine read endpoints do not answer yet, in practice every
//! command below returns `Unreachable`/`Blocked` today — that is expected and is the
//! point: a real read-IPC surface plus an honest blocked state, with zero fabrication.

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
    Ok { surface: String, records: Vec<Value> },
    /// The engine was reached but explicitly refused the read, returned a
    /// malformed/`ok:false` result, or returned a record that fails its schema
    /// (fail-closed). Honest "blocked", never fabricated data.
    Blocked { surface: String, reason: String },
    /// The engine sidecar could not be reached / is not configured / did not
    /// respond (fail-closed). Honest "unreachable", never fabricated data.
    Unreachable { surface: String, reason: String },
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

/// Pull the `records` array out of a successful (`ok:true`) sidecar reply and validate
/// every entry with `parse_one`, re-serializing each validated record. A single
/// invalid record fails the WHOLE read (fail-closed): a partly-fabricated mirror is
/// never shown as `ok`.
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
                Ok(records) => GovernanceRead::Ok { surface: surface.to_string(), records },
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
            GovernanceRead::Ok { records, surface } => {
                assert_eq!(surface, "verdicts");
                assert_eq!(records.len(), 1);
            }
            other => panic!("expected Ok, got {other:?}"),
        }
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
}
