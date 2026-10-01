//! The desktop's half of the approval-REQUEST path: build the ask, read the answer, decide nothing.
//!
//! `T-021c`. The document this builds is defined by `contracts/approval-request.schema.json`, audited in
//! `docs/design/T-021_SCHEMA_AUDIT.md` before either side was written, and the engine that records it is
//! `engine/runtime/bro_approval_requests.py`.
//!
//! WHY IT IS HERE AND NOT IN THE APP CRATE. `ai.rs` says it in its own words about the §4.10(f) pull:
//! "an adapter that ran its own loop would have had its own copy of the `eof` check and of the output
//! gates, and the copy that runs in production is the one no test drives." Same rule. The app crate gets
//! a transport call and a `#[tauri::command]`; every decision about what may be sent and what may be
//! believed is here, where it is unit-tested on every platform.
//!
//! THE TWO RULES THIS MODULE EXISTS FOR
//!
//! 1. **What may be sent.** The document carries the twelve fields the contract declares and nothing
//!    else — no key, lease, nonce, signature or verdict, because `additionalProperties: false` means the
//!    engine would refuse one anyway, and because a desktop that TRIED would be the defect. Built field
//!    by field here rather than by serialising a struct someone could later add a field to.
//!
//! 2. **What may be believed.** A reply is `Recorded` only when it says so in the engine's own
//!    vocabulary AND carries no field that could be read as a decision. An engine that answered
//!    `adjudicated: true`, or `granted`, or a `disposition`, would be breaking invariant 2 on the way
//!    back — and the desktop refuses that reply instead of rendering an approval nobody signed. That is
//!    the obligation the schema audit recorded as unenforceable by a schema, discharged here.

use serde_json::{json, Value};

/// The request protocol, pinned to the contract's `protocol` const.
pub const APPROVAL_REQUEST_PROTOCOL: &str = "brops.approval-request.v1";
/// The op, pinned to the contract's `op` const.
pub const APPROVAL_REQUEST_OP: &str = "approval.request";
/// The reply protocol — a different name, so a reply cannot be replayed as a request.
pub const APPROVAL_REPLY_PROTOCOL: &str = "brops.approval-request-reply.v1";

/// The three asks the contract allows, in the signed command's own vocabulary.
pub const REQUESTABLE_COMMANDS: [&str; 3] = ["approve", "deny", "request-verification"];

/// The one requester type this transport can honestly claim.
pub const REQUESTED_BY_TYPE: &str = "desktop-operator";

/// Field names that must never appear in a reply this side treats as a record.
///
/// Not a heuristic over values: the list of words the repository's own artifacts use for a decision.
/// An engine reply carrying one of them is refused, because the only party that may decide is the
/// holder of a `control-room` key and this path has none.
const DECISION_WORDS: [&str; 8] = [
    "granted", "disposition", "verdict", "decision", "outcome", "approved", "adjudication", "signed",
];

/// What the desktop is allowed to conclude from one round trip.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
#[serde(tag = "state", rename_all = "lowercase")]
pub enum ApprovalOutcome {
    /// The engine recorded the ask. It did NOT decide it, and `adjudicated` is carried through so a
    /// surface cannot lose that on the way to a pixel.
    Recorded {
        request_id: String,
        sequence: u64,
        entry_sha256: String,
        duplicate: bool,
        adjudicated: bool,
        note: String,
    },
    /// The engine refused, with its own reason. A refusal is an answer; it is not an error.
    Refused { reason: String },
    /// Nothing was established: the transport failed, the reply did not parse, or the reply was not one
    /// this side may believe. Deliberately NOT `Refused` — "the engine said no" and "I never heard from
    /// the engine" are different facts and a cockpit must not render them the same.
    Blocked { reason: String },
}

fn bounded(text: &str) -> String {
    const MAX: usize = 400;
    if text.chars().count() <= MAX {
        return text.to_string();
    }
    let head: String = text.chars().take(MAX).collect();
    format!("{head}…")
}

/// A fresh correlation id for one ask.
///
/// A v4 UUID, which satisfies the contract's id pattern (`^[A-Za-z0-9][A-Za-z0-9._-]{1,127}$`) and
/// carries no meaning at all -- it is not a grant, not a nonce and not a capability. The engine
/// treats a repeat as a DUPLICATE ask rather than as a second decision, so a retry that reuses one
/// is safe by the engine's rule and not by this side's care.
pub fn new_request_id() -> String {
    format!("req-{}", uuid::Uuid::new_v4())
}

/// Build the ask. `request_id` is supplied rather than generated here so the caller owns correlation
/// and the function stays pure.
///
/// Returns `Err` for an input this side must not send at all — a command outside the three asks, or an
/// empty reason. Refusing locally is not a substitute for the engine's own validation; it is how a
/// cockpit avoids asking a question it already knows is malformed.
pub fn approval_request_document(
    request_id: &str,
    task_id: &str,
    requested_command: &str,
    expected_task_state: &str,
    reason: &str,
    requested_by: &str,
    requested_at_epoch: i64,
    evidence_refs: &[String],
) -> Result<Value, String> {
    if !REQUESTABLE_COMMANDS.contains(&requested_command) {
        return Err(format!(
            "`{requested_command}` is not one of the three asks this path may make ({}); cancel, \
             retry and reassign are commands, not approvals",
            REQUESTABLE_COMMANDS.join(", ")
        ));
    }
    if reason.trim().is_empty() {
        return Err("an approval request with no reason is not a request".to_string());
    }
    if request_id.is_empty() || task_id.is_empty() || expected_task_state.is_empty()
        || requested_by.is_empty()
    {
        return Err("request_id, task_id, expected_task_state and requested_by are all required"
            .to_string());
    }
    let mut doc = json!({
        "schema": 1,
        "protocol": APPROVAL_REQUEST_PROTOCOL,
        "op": APPROVAL_REQUEST_OP,
        "request_id": request_id,
        "task_id": task_id,
        "requested_command": requested_command,
        "expected_task_state": expected_task_state,
        "reason": reason,
        "requested_by_type": REQUESTED_BY_TYPE,
        "requested_by": requested_by,
        "requested_at_epoch": requested_at_epoch,
    });
    if !evidence_refs.is_empty() {
        doc["evidence_refs"] = json!(evidence_refs);
    }
    Ok(doc)
}

/// Read one reply. Nothing here is believed that the reply does not say in the engine's own words.
///
/// `sent_request_id` is the id of the request THIS reply is supposed to answer. A reply is
/// `Recorded` only if it names that id: this function used to take the reply alone and copy
/// whatever `request_id` it carried — or the empty string, if it carried none — into the outcome,
/// so a record of some other ask, or of no identifiable ask, was rendered as the answer to this
/// one. The engine echoes the id on every record it makes, so a real reply always has it.
pub fn classify(reply: Result<Value, String>, sent_request_id: &str) -> ApprovalOutcome {
    let doc = match reply {
        Ok(doc) => doc,
        Err(e) => {
            return ApprovalOutcome::Blocked {
                reason: format!("the engine was not reached: {}", bounded(&e)),
            }
        }
    };
    let object = match doc.as_object() {
        Some(map) => map,
        None => {
            return ApprovalOutcome::Blocked {
                reason: "the engine reply is not a JSON object".to_string(),
            }
        }
    };
    if object.get("protocol").and_then(Value::as_str) != Some(APPROVAL_REPLY_PROTOCOL) {
        return ApprovalOutcome::Blocked {
            reason: format!(
                "the reply names protocol {:?}, not {APPROVAL_REPLY_PROTOCOL}",
                object.get("protocol")
            ),
        };
    }
    // A reply that carries a decision word is refused whatever else it says. This is invariant 2 on
    // the way back, and it is checked BEFORE `ok`, so an `ok: true` cannot buy its way past it.
    for word in DECISION_WORDS {
        if object.keys().any(|k| k.to_ascii_lowercase().contains(word)) {
            return ApprovalOutcome::Blocked {
                reason: format!(
                    "the engine reply carries a `{word}`-shaped field; only an owner-signed \
                     control-room command decides an approval, so this side will not render a \
                     reply that claims one"
                ),
            };
        }
    }
    match object.get("ok").and_then(Value::as_bool) {
        Some(true) => {}
        Some(false) => {
            let reason = object
                .get("reason")
                .and_then(Value::as_str)
                .unwrap_or("the engine refused and gave no reason");
            // A refusal that wears a record's clothes is the one shape that must never be believed.
            for worn in ["recorded", "sequence", "entry_sha256", "chain_head_sha256"] {
                if object.contains_key(worn) {
                    return ApprovalOutcome::Blocked {
                        reason: format!(
                            "the engine refused AND carried `{worn}`; a refusal that looks like a \
                             record is not readable as either"
                        ),
                    };
                }
            }
            return ApprovalOutcome::Refused { reason: bounded(reason) };
        }
        None => {
            return ApprovalOutcome::Blocked {
                reason: "the engine reply has no `ok` field, so it establishes nothing".to_string(),
            }
        }
    }
    if object.get("recorded").and_then(Value::as_bool) != Some(true) {
        return ApprovalOutcome::Blocked {
            reason: "the engine reply says ok without saying `recorded: true`".to_string(),
        };
    }
    if object.get("adjudicated").and_then(Value::as_bool) != Some(false) {
        return ApprovalOutcome::Blocked {
            reason: "the engine reply does not carry `adjudicated: false`; a recorded ask that does \
                     not say it is unadjudicated is not one this side will show as recorded"
                .to_string(),
        };
    }
    let sequence = match object.get("sequence").and_then(Value::as_u64) {
        Some(n) if n >= 1 => n,
        _ => {
            return ApprovalOutcome::Blocked {
                reason: "the engine reply carries no usable `sequence`".to_string(),
            }
        }
    };
    let digest = object.get("entry_sha256").and_then(Value::as_str).unwrap_or_default();
    if digest.len() != 64 || !digest.chars().all(|c| c.is_ascii_hexdigit()) {
        return ApprovalOutcome::Blocked {
            reason: "the engine reply carries no 64-hex `entry_sha256`, so there is nothing to \
                     correlate the record with"
                .to_string(),
        };
    }
    match object.get("request_id").and_then(Value::as_str) {
        Some(echoed) if !sent_request_id.is_empty() && echoed == sent_request_id => {}
        _ => {
            return ApprovalOutcome::Blocked {
                reason: "the engine reply does not name the request that was sent, so the record \
                         it describes is not shown as the answer to this ask"
                    .to_string(),
            }
        }
    }
    ApprovalOutcome::Recorded {
        request_id: sent_request_id.to_string(),
        sequence,
        entry_sha256: digest.to_string(),
        duplicate: object.get("duplicate").and_then(Value::as_bool).unwrap_or(false),
        adjudicated: false,
        note: bounded(object.get("note").and_then(Value::as_str).unwrap_or("")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The id the fixture request was sent under, and the one [`reply`] echoes.
    const SENT: &str = "req-7f2a91c4";

    fn doc() -> Value {
        approval_request_document(
            "req-7f2a91c4",
            "task-0001",
            "approve",
            "awaiting-owner-approval",
            "the cockpit operator asks the owner to approve this task",
            "gev@cockpit",
            1_758_240_000,
            &[],
        )
        .expect("the fixture must be well formed")
    }

    fn reply(extra: Value) -> Value {
        let mut base = json!({
            "protocol": APPROVAL_REPLY_PROTOCOL,
            "schema": 1,
            "ok": true,
            "op": APPROVAL_REQUEST_OP,
            "request_id": "req-7f2a91c4",
            "recorded": true,
            "duplicate": false,
            "sequence": 1,
            "entry_sha256": "a".repeat(64),
            "chain_head_sha256": "a".repeat(64),
            "requester_authenticated": false,
            "task_state_when_received": "awaiting-owner-approval",
            "adjudicated": false,
            "note": "recorded, not adjudicated",
        });
        for (k, v) in extra.as_object().cloned().unwrap_or_default() {
            base[k] = v;
        }
        base
    }

    // --- what may be sent -------------------------------------------------------------------
    #[test]
    fn nm_scope_the_document_carries_only_the_contract_s_fields() {
        let built = doc();
        let mut sorted: Vec<&str> =
            built.as_object().unwrap().keys().map(String::as_str).collect();
        sorted.sort_unstable();
        assert_eq!(
            sorted,
            vec![
                "expected_task_state",
                "op",
                "protocol",
                "reason",
                "request_id",
                "requested_at_epoch",
                "requested_by",
                "requested_by_type",
                "requested_command",
                "schema",
                "task_id",
            ]
        );
    }

    #[test]
    fn nm_scope_no_field_is_named_after_a_thing_that_may_not_cross() {
        let serialised = doc().to_string().to_ascii_lowercase();
        for word in [
            "key_id", "signature", "nonce", "lease", "verdict", "secret", "token", "credential",
            "private", "password",
        ] {
            assert!(!serialised.contains(word), "the ask carries `{word}`");
        }
    }

    #[test]
    fn nm_scope_the_requester_type_cannot_be_chosen_by_a_caller() {
        assert_eq!(doc()["requested_by_type"], json!(REQUESTED_BY_TYPE));
        assert_eq!(REQUESTED_BY_TYPE, "desktop-operator");
    }

    #[test]
    fn a_command_outside_the_three_asks_is_refused_locally() {
        for verb in ["cancel", "retry", "reassign", "grant", "escalate", ""] {
            let built = approval_request_document(
                "req-1", "task-1", verb, "state", "why", "who", 1, &[],
            );
            assert!(built.is_err(), "`{verb}` was accepted");
        }
    }

    #[test]
    fn an_empty_reason_is_refused_locally() {
        assert!(approval_request_document(
            "req-1", "task-1", "approve", "state", "   ", "who", 1, &[]
        )
        .is_err());
    }

    #[test]
    fn evidence_refs_are_omitted_when_empty_and_carried_when_given() {
        assert!(doc().get("evidence_refs").is_none());
        let with = approval_request_document(
            "req-1", "task-1", "approve", "state", "why", "who", 1,
            &["ev-1".to_string(), "ev-2".to_string()],
        )
        .unwrap();
        assert_eq!(with["evidence_refs"], json!(["ev-1", "ev-2"]));
    }

    // --- what may be believed ---------------------------------------------------------------
    #[test]
    fn a_well_formed_record_is_recorded() {
        match classify(Ok(reply(json!({}))), SENT) {
            ApprovalOutcome::Recorded { sequence, duplicate, adjudicated, .. } => {
                assert_eq!(sequence, 1);
                assert!(!duplicate);
                assert!(!adjudicated);
            }
            other => panic!("expected Recorded, got {other:?}"),
        }
    }

    /// All eight words, written out here and compared with the list, so a word deleted from
    /// `DECISION_WORDS` fails twice: the list no longer equals this one, and a reply carrying
    /// that word is believed. The loop used to cover six literals while the list held eight —
    /// `adjudication` and `signed` could be removed with every test green.
    #[test]
    fn a_reply_claiming_a_decision_is_blocked_even_when_it_says_ok() {
        const EVERY_WORD: [&str; 8] = [
            "granted", "disposition", "verdict", "decision", "outcome", "approved", "adjudication",
            "signed",
        ];
        assert_eq!(DECISION_WORDS, EVERY_WORD, "a word added or removed is a deliberate act");
        for word in EVERY_WORD {
            // `adjudicated` is a field every honest reply carries, and it contains none of the
            // words; the key under test is the bare word and a decorated form of it.
            for key in [word.to_string(), format!("owner_{word}_at"), word.to_uppercase()] {
                let shown = key.clone();
                let out = classify(Ok(reply(json!({ key: true }))), SENT);
                match out {
                    ApprovalOutcome::Blocked { reason } => {
                        assert!(reason.contains(word), "{reason}");
                    }
                    other => panic!("`{shown}` was believed: {other:?}"),
                }
            }
        }
        // Positive control: the same reply without a decision word IS recorded, so the loop
        // above is not passing because everything is blocked.
        assert!(matches!(classify(Ok(reply(json!({}))), SENT), ApprovalOutcome::Recorded { .. }));
    }

    /// The reply must answer the request that was sent. The fixture reply names `req-7f2a91c4`.
    #[test]
    fn a_reply_for_another_request_or_for_none_is_not_recorded() {
        match classify(Ok(reply(json!({}))), SENT) {
            ApprovalOutcome::Recorded { request_id, .. } => assert_eq!(request_id, SENT),
            other => panic!("the matching reply must be recorded, got {other:?}"),
        }
        let unanswering = [
            (reply(json!({})), "req-SOMETHING-ELSE"),          // a record of a different ask
            (reply(json!({ "request_id": Value::Null })), SENT), // a record naming no ask
            (reply(json!({ "request_id": 7 })), SENT),           // not a string
            (reply(json!({ "request_id": "" })), ""),            // empty on both sides is not a match
        ];
        for (doc, sent) in unanswering {
            match classify(Ok(doc.clone()), sent) {
                ApprovalOutcome::Blocked { reason } => assert!(reason.contains("request"), "{reason}"),
                other => panic!("sent {sent:?}, reply {doc} was believed: {other:?}"),
            }
        }
        let mut missing = reply(json!({}));
        missing.as_object_mut().unwrap().remove("request_id");
        assert!(matches!(classify(Ok(missing), SENT), ApprovalOutcome::Blocked { .. }));
    }

    #[test]
    fn a_reply_without_adjudicated_false_is_blocked() {
        for value in [json!(true), json!("no"), Value::Null] {
            match classify(Ok(reply(json!({ "adjudicated": value }))), SENT) {
                ApprovalOutcome::Blocked { .. } => {}
                other => panic!("expected Blocked, got {other:?}"),
            }
        }
    }

    #[test]
    fn a_refusal_is_refused_and_not_blocked() {
        let mut doc = reply(json!({ "ok": false, "reason": "the engine has no task 'task-9999'" }));
        for worn in ["recorded", "sequence", "entry_sha256", "chain_head_sha256"] {
            doc.as_object_mut().unwrap().remove(worn);
        }
        match classify(Ok(doc), SENT) {
            ApprovalOutcome::Refused { reason } => assert!(reason.contains("task-9999")),
            other => panic!("expected Refused, got {other:?}"),
        }
    }

    #[test]
    fn a_refusal_wearing_a_records_clothes_is_blocked() {
        let doc = reply(json!({ "ok": false, "reason": "no", "recorded": false }));
        match classify(Ok(doc), SENT) {
            ApprovalOutcome::Blocked { reason } => assert!(reason.contains("recorded")),
            other => panic!("expected Blocked, got {other:?}"),
        }
    }

    #[test]
    fn a_reply_in_the_wrong_protocol_is_blocked() {
        let doc = reply(json!({ "protocol": APPROVAL_REQUEST_PROTOCOL }));
        match classify(Ok(doc), SENT) {
            ApprovalOutcome::Blocked { reason } => assert!(reason.contains("protocol")),
            other => panic!("expected Blocked, got {other:?}"),
        }
    }

    #[test]
    fn a_transport_failure_is_blocked_and_never_refused() {
        match classify(Err("the sidecar did not start".to_string()), SENT) {
            ApprovalOutcome::Blocked { reason } => assert!(reason.contains("not reached")),
            other => panic!("expected Blocked, got {other:?}"),
        }
    }

    #[test]
    fn a_reply_with_no_ok_field_establishes_nothing() {
        let mut doc = reply(json!({}));
        doc.as_object_mut().unwrap().remove("ok");
        match classify(Ok(doc), SENT) {
            ApprovalOutcome::Blocked { reason } => assert!(reason.contains("`ok`")),
            other => panic!("expected Blocked, got {other:?}"),
        }
    }

    #[test]
    fn a_record_without_a_64_hex_digest_is_blocked() {
        for bad in [json!("abc"), json!(""), json!("z".repeat(64)), Value::Null] {
            match classify(Ok(reply(json!({ "entry_sha256": bad }))), SENT) {
                ApprovalOutcome::Blocked { reason } => assert!(reason.contains("entry_sha256")),
                other => panic!("expected Blocked, got {other:?}"),
            }
        }
    }

    #[test]
    fn a_duplicate_is_recorded_and_says_so() {
        match classify(Ok(reply(json!({ "duplicate": true, "sequence": 2 }))), SENT) {
            ApprovalOutcome::Recorded { duplicate, sequence, .. } => {
                assert!(duplicate);
                assert_eq!(sequence, 2);
            }
            other => panic!("expected Recorded, got {other:?}"),
        }
    }

    #[test]
    fn a_fresh_request_id_satisfies_the_contract_s_id_pattern() {
        // `^[A-Za-z0-9][A-Za-z0-9._-]{1,127}$`, checked without a regex crate.
        for _ in 0..8 {
            let id = new_request_id();
            assert!(id.len() >= 2 && id.len() <= 128, "{id}");
            let mut chars = id.chars();
            assert!(chars.next().unwrap().is_ascii_alphanumeric(), "{id}");
            assert!(
                chars.all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '_' || c == '-'),
                "{id}"
            );
        }
    }

    #[test]
    fn two_fresh_request_ids_differ() {
        assert_ne!(new_request_id(), new_request_id());
    }

    #[test]
    fn the_protocols_are_different_names() {
        assert_ne!(APPROVAL_REQUEST_PROTOCOL, APPROVAL_REPLY_PROTOCOL);
    }
}
