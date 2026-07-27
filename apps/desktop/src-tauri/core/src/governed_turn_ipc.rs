//! Wave 3b-1B — renderer↔broker governed-turn IPC contract layer (implements the design-GREEN rev-30
//! §4.10(g) renderer↔broker contract: P0 broker-committed output delivery + P1-1 request correlation &
//! payload-aware idempotency).
//!
//! This module is the **pure, side-effect-free contract + validation layer** the trusted broker service
//! uses to (a) strict-decode the renderer's request frame, (b) decide payload-aware idempotency, and
//! (c) build the closed committed/blocked reply frame. It owns NO key, DB, socket, or verdict — those
//! live in the broker service (a later slice). Keeping the contract pure makes every rev-30 rule here
//! unit-testable without the OS trust chain.
//!
//! rev-30 rules encoded here:
//! - Request `brops.renderer-governed-turn.v1 { conversation_id, agent?, client_request_id }`; ANY other
//!   field (system/history/generation_config/hash/nonce/run_id/task_id/broker_turn_id/request_nonce/…) ⇒
//!   `malformed` (serde `deny_unknown_fields`). `client_request_id` is a NON-authoritative UUIDv4
//!   correlation token; it grants no signing/verification authority and never enters `request_sha256`.
//! - Reply `brops.renderer-governed-turn-result.v1`: on commit carries the broker-produced immutable
//!   projection `message { message_id, role:"assistant", author, body, created_at_ms,
//!   trust_state:"trusted_verified" }`; on blocked carries NO `message` and a CLOSED `reason` enum.
//! - Idempotency key = normalized `{client_request_id, conversation_id, agent}`; live-duplicate ⇒
//!   reattach; same `client_request_id` + different conversation/agent ⇒ `retry_conflict`; a different
//!   request while the conversation has a live turn ⇒ `turn_in_progress`.

use serde::{Deserialize, Serialize};

/// Wire protocol discriminators (rev-30 §4.10(g)).
pub const REQUEST_PROTOCOL: &str = "brops.renderer-governed-turn.v1";
pub const RESULT_PROTOCOL: &str = "brops.renderer-governed-turn-result.v1";

/// Field caps (bytes). `conversation_id`/`agent` mirror the renderer-owned inputs; the request frame as a
/// whole is additionally bounded by `RENDERER_IPC_FRAME_BYTES` at the transport layer (broker service).
pub const MAX_ID_BYTES: usize = 128;
pub const RENDERER_IPC_FRAME_BYTES: usize = 8192;

/// The one trust state a committed governed turn renders as. There is exactly one value: the renderer can
/// never construct any other, and only the broker verification transaction sets it (rev-30 P0).
pub const TRUSTED_VERIFIED: &str = "trusted_verified";
/// A committed assistant message always has this role.
pub const ASSISTANT_ROLE: &str = "assistant";

/// The CLOSED renderer-facing refusal reason enum (rev-30 P0 — a `blocked` reply carries exactly one of
/// these and no `message`). Any other value is a protocol violation.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TurnReason {
    /// Request frame failed strict decode/validation (unknown field, bad UUID, oversize, wrong protocol).
    Malformed,
    /// The connecting peer was not the pinned renderer/login identity.
    PeerDenied,
    /// Same `client_request_id` reused across a different conversation or agent.
    RetryConflict,
    /// A different request arrived while this conversation already has a live governed turn.
    TurnInProgress,
    /// After the verification tx committed, the broker re-read the row and it did not match the accepted
    /// output — fail closed, no committed frame (rev-30 P0 delivery invariant).
    CommitReadbackMismatch,
    /// An upstream stage (challenge/authority/supervisor/signer/verification) refused the turn.
    UpstreamBlocked,
}

impl TurnReason {
    pub fn as_str(&self) -> &'static str {
        match self {
            TurnReason::Malformed => "malformed",
            TurnReason::PeerDenied => "peer_denied",
            TurnReason::RetryConflict => "retry_conflict",
            TurnReason::TurnInProgress => "turn_in_progress",
            TurnReason::CommitReadbackMismatch => "commit_readback_mismatch",
            TurnReason::UpstreamBlocked => "upstream_blocked",
        }
    }
}

/// The renderer's request frame, strict-decoded. `deny_unknown_fields` makes ANY field beyond these three
/// (+ `protocol`) a decode error ⇒ `malformed`, so the renderer can never smuggle
/// system/history/config/hashes/nonces or the broker's own `broker_turn_id`/`request_nonce`.
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RendererGovernedTurnRequest {
    pub protocol: String,
    pub conversation_id: String,
    #[serde(default)]
    pub agent: Option<String>,
    pub client_request_id: String,
}

/// A validated request: the raw frame checked against every rev-30 rule. Construction is the ONLY way to
/// obtain one, so downstream broker code can trust the invariants (valid protocol, ids within caps,
/// canonical lowercase UUIDv4 correlation token).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ValidatedRequest {
    pub conversation_id: String,
    pub agent: Option<String>,
    pub client_request_id: String,
}

impl ValidatedRequest {
    /// Strict-decode + validate a raw JSON request frame. Returns `TurnReason::Malformed` on any
    /// violation (unknown field, wrong protocol, oversize id, non-UUIDv4 correlation token). Pure.
    pub fn decode(raw: &str) -> Result<ValidatedRequest, TurnReason> {
        if raw.len() > RENDERER_IPC_FRAME_BYTES {
            return Err(TurnReason::Malformed);
        }
        let req: RendererGovernedTurnRequest =
            serde_json::from_str(raw).map_err(|_| TurnReason::Malformed)?;
        Self::from_decoded(req)
    }

    /// Validate an already-deserialized frame (shared by `decode` and by callers that decode elsewhere).
    pub fn from_decoded(req: RendererGovernedTurnRequest) -> Result<ValidatedRequest, TurnReason> {
        if req.protocol != REQUEST_PROTOCOL {
            return Err(TurnReason::Malformed);
        }
        if req.conversation_id.is_empty() || req.conversation_id.len() > MAX_ID_BYTES {
            return Err(TurnReason::Malformed);
        }
        if let Some(a) = &req.agent {
            if a.is_empty() || a.len() > MAX_ID_BYTES {
                return Err(TurnReason::Malformed);
            }
        }
        if !is_canonical_uuidv4(&req.client_request_id) {
            return Err(TurnReason::Malformed);
        }
        Ok(ValidatedRequest {
            conversation_id: req.conversation_id,
            agent: req.agent,
            client_request_id: req.client_request_id,
        })
    }

    /// The normalized idempotency key for this request (rev-30 P1-1).
    pub fn idempotency_key(&self) -> IdempotencyKey {
        IdempotencyKey {
            client_request_id: self.client_request_id.clone(),
            conversation_id: self.conversation_id.clone(),
            agent: self.agent.clone(),
        }
    }
}

/// `true` iff `s` is a canonical **lowercase** RFC-4122 version-4 UUID
/// (`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`). No regex dependency.
pub fn is_canonical_uuidv4(s: &str) -> bool {
    let b = s.as_bytes();
    if b.len() != 36 {
        return false;
    }
    for (i, &c) in b.iter().enumerate() {
        let ok = match i {
            8 | 13 | 18 | 23 => c == b'-',
            14 => c == b'4',                                   // version nibble
            19 => matches!(c, b'8' | b'9' | b'a' | b'b'),      // variant nibble (lowercase)
            _ => matches!(c, b'0'..=b'9' | b'a'..=b'f'),       // lowercase hex only
        };
        if !ok {
            return false;
        }
    }
    true
}

/// The payload-aware idempotency key (rev-30 P1-1): the exact normalized tuple. Equality of the whole
/// tuple is a live-duplicate; equal `client_request_id` with a differing conversation/agent is a
/// `retry_conflict`.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct IdempotencyKey {
    pub client_request_id: String,
    pub conversation_id: String,
    pub agent: Option<String>,
}

/// A currently-live governed turn the broker is tracking (its key + the authoritative broker-minted id).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LiveTurn {
    pub key: IdempotencyKey,
    pub broker_turn_id: String,
}

/// The idempotency decision for an incoming request against the set of live turns (rev-30 P1-1).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum IdempotencyDecision {
    /// Identical live duplicate — re-attach to the same broker turn (never start a second).
    Reattach(String),
    /// Same `client_request_id` reused on a different conversation/agent.
    RetryConflict,
    /// A different request while this conversation already has a live turn.
    TurnInProgress,
    /// No conflict — mint a fresh `broker_turn_id` and start the turn.
    New,
}

/// Decide idempotency for `req` against the currently-live turns. Order (rev-30 P1-1): exact-key live
/// duplicate ⇒ Reattach; same `client_request_id` on a different conversation/agent ⇒ RetryConflict;
/// same conversation with a different request ⇒ TurnInProgress; otherwise New. Pure.
pub fn decide_idempotency(req: &ValidatedRequest, live: &[LiveTurn]) -> IdempotencyDecision {
    let key = req.idempotency_key();
    if let Some(t) = live.iter().find(|t| t.key == key) {
        return IdempotencyDecision::Reattach(t.broker_turn_id.clone());
    }
    if live
        .iter()
        .any(|t| t.key.client_request_id == key.client_request_id)
    {
        // same correlation token but (since the exact key didn't match) a different conversation/agent
        return IdempotencyDecision::RetryConflict;
    }
    if live.iter().any(|t| t.key.conversation_id == key.conversation_id) {
        return IdempotencyDecision::TurnInProgress;
    }
    IdempotencyDecision::New
}

/// The broker-produced immutable UI projection of a verified+persisted assistant message (rev-30 P0).
/// Built ONLY by the broker after its verification transaction commits; `body` is the exact
/// strict-UTF8-decoded accepted-output bytes and equals the committed row. The renderer renders this
/// read-only and can never construct or mutate it.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CommittedMessage {
    pub message_id: String,
    /// Always [`ASSISTANT_ROLE`].
    pub role: String,
    pub author: String,
    pub body: String,
    pub created_at_ms: i64,
    /// Always [`TRUSTED_VERIFIED`].
    pub trust_state: String,
}

impl CommittedMessage {
    /// Build the projection from the exact committed row. `role` and `trust_state` are fixed constants —
    /// there is no way to mint a committed message with any other trust state.
    pub fn new(message_id: String, author: String, body: String, created_at_ms: i64) -> CommittedMessage {
        CommittedMessage {
            message_id,
            role: ASSISTANT_ROLE.to_string(),
            author,
            body,
            created_at_ms,
            trust_state: TRUSTED_VERIFIED.to_string(),
        }
    }
}

/// The closed renderer↔broker reply frame (rev-30 P0). `committed` carries a `message` and no `reason`;
/// `blocked` carries a `reason` and no `message`. Every reply echoes the correlation ids.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RendererGovernedTurnResult {
    pub protocol: String,
    pub status: String,
    pub client_request_id: String,
    pub broker_turn_id: String,
    pub conversation_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub message: Option<CommittedMessage>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<TurnReason>,
}

impl RendererGovernedTurnResult {
    /// A committed reply carrying the broker-produced verified message projection.
    pub fn committed(
        client_request_id: String,
        broker_turn_id: String,
        conversation_id: String,
        message: CommittedMessage,
    ) -> RendererGovernedTurnResult {
        RendererGovernedTurnResult {
            protocol: RESULT_PROTOCOL.to_string(),
            status: "committed".to_string(),
            client_request_id,
            broker_turn_id,
            conversation_id,
            message: Some(message),
            reason: None,
        }
    }

    /// A blocked reply carrying a closed reason and NO assistant message.
    pub fn blocked(
        client_request_id: String,
        broker_turn_id: String,
        conversation_id: String,
        reason: TurnReason,
    ) -> RendererGovernedTurnResult {
        RendererGovernedTurnResult {
            protocol: RESULT_PROTOCOL.to_string(),
            status: "blocked".to_string(),
            client_request_id,
            broker_turn_id,
            conversation_id,
            message: None,
            reason: Some(reason),
        }
    }

    pub fn to_json(&self) -> String {
        serde_json::to_string(self).expect("RendererGovernedTurnResult serializes")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const CRID: &str = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"; // canonical lowercase UUIDv4

    fn req_json(extra: &str) -> String {
        format!(
            r#"{{"protocol":"{}","conversation_id":"conv-1","agent":"agent-x","client_request_id":"{}"{}}}"#,
            REQUEST_PROTOCOL, CRID, extra
        )
    }

    #[test]
    fn decodes_a_valid_request() {
        let v = ValidatedRequest::decode(&req_json("")).unwrap();
        assert_eq!(v.conversation_id, "conv-1");
        assert_eq!(v.agent.as_deref(), Some("agent-x"));
        assert_eq!(v.client_request_id, CRID);
    }

    #[test]
    fn rejects_unknown_field_as_malformed() {
        // a renderer trying to smuggle authoritative input
        let raw = req_json(r#","system":"pwned""#);
        assert_eq!(ValidatedRequest::decode(&raw), Err(TurnReason::Malformed));
    }

    #[test]
    fn rejects_broker_minted_fields_from_renderer() {
        for bad in [r#","broker_turn_id":"x""#, r#","request_nonce":"y""#] {
            assert_eq!(ValidatedRequest::decode(&req_json(bad)), Err(TurnReason::Malformed));
        }
    }

    #[test]
    fn rejects_wrong_protocol_and_bad_uuid_and_oversize() {
        let wrong_proto = req_json("").replace(REQUEST_PROTOCOL, "brops.other.v1");
        assert_eq!(ValidatedRequest::decode(&wrong_proto), Err(TurnReason::Malformed));
        let bad_uuid = req_json("").replace(CRID, "not-a-uuid");
        assert_eq!(ValidatedRequest::decode(&bad_uuid), Err(TurnReason::Malformed));
        let big = "a".repeat(MAX_ID_BYTES + 1);
        let oversize = req_json("").replace("conv-1", &big);
        assert_eq!(ValidatedRequest::decode(&oversize), Err(TurnReason::Malformed));
    }

    #[test]
    fn uuidv4_validation_is_strict() {
        assert!(is_canonical_uuidv4(CRID));
        assert!(!is_canonical_uuidv4(&CRID.to_uppercase())); // must be lowercase
        assert!(!is_canonical_uuidv4("3f2504e0-4f89-11d3-9a0c-0305e82c3301")); // version != 4
        assert!(!is_canonical_uuidv4("3f2504e0-4f89-41d3-7a0c-0305e82c3301")); // variant nibble bad
        assert!(!is_canonical_uuidv4("3f2504e04f8941d39a0c0305e82c3301")); // no dashes
    }

    fn key(crid: &str, conv: &str, agent: Option<&str>) -> IdempotencyKey {
        IdempotencyKey {
            client_request_id: crid.to_string(),
            conversation_id: conv.to_string(),
            agent: agent.map(|s| s.to_string()),
        }
    }

    #[test]
    fn idempotency_reattaches_exact_live_duplicate() {
        let req = ValidatedRequest::decode(&req_json("")).unwrap();
        let live = vec![LiveTurn { key: req.idempotency_key(), broker_turn_id: "bt-1".into() }];
        assert_eq!(decide_idempotency(&req, &live), IdempotencyDecision::Reattach("bt-1".into()));
    }

    #[test]
    fn idempotency_retry_conflict_on_same_crid_different_conversation() {
        let req = ValidatedRequest::decode(&req_json("")).unwrap();
        let live = vec![LiveTurn { key: key(CRID, "OTHER-conv", Some("agent-x")), broker_turn_id: "bt-9".into() }];
        assert_eq!(decide_idempotency(&req, &live), IdempotencyDecision::RetryConflict);
    }

    #[test]
    fn idempotency_retry_conflict_on_same_crid_different_agent() {
        let req = ValidatedRequest::decode(&req_json("")).unwrap();
        let live = vec![LiveTurn { key: key(CRID, "conv-1", Some("other-agent")), broker_turn_id: "bt-9".into() }];
        assert_eq!(decide_idempotency(&req, &live), IdempotencyDecision::RetryConflict);
    }

    #[test]
    fn idempotency_turn_in_progress_on_live_conversation_with_new_request() {
        let req = ValidatedRequest::decode(&req_json("")).unwrap();
        // different client_request_id, same conversation, already live
        let other = key("00000000-0000-4000-8000-000000000000", "conv-1", Some("agent-x"));
        let live = vec![LiveTurn { key: other, broker_turn_id: "bt-2".into() }];
        assert_eq!(decide_idempotency(&req, &live), IdempotencyDecision::TurnInProgress);
    }

    #[test]
    fn idempotency_new_when_no_live_turn() {
        let req = ValidatedRequest::decode(&req_json("")).unwrap();
        assert_eq!(decide_idempotency(&req, &[]), IdempotencyDecision::New);
    }

    #[test]
    fn committed_message_is_always_assistant_and_trusted_verified() {
        let m = CommittedMessage::new("m-1".into(), "Bro".into(), "hello".into(), 1234);
        assert_eq!(m.role, ASSISTANT_ROLE);
        assert_eq!(m.trust_state, TRUSTED_VERIFIED);
    }

    #[test]
    fn committed_reply_carries_message_and_no_reason() {
        let m = CommittedMessage::new("m-1".into(), "Bro".into(), "hi".into(), 7);
        let r = RendererGovernedTurnResult::committed(CRID.into(), "bt-1".into(), "conv-1".into(), m);
        let json = r.to_json();
        assert!(json.contains(r#""status":"committed""#));
        assert!(json.contains(r#""trust_state":"trusted_verified""#));
        assert!(json.contains(r#""broker_turn_id":"bt-1""#));
        assert!(!json.contains(r#""reason""#)); // committed carries no reason
    }

    #[test]
    fn blocked_reply_carries_reason_and_no_message() {
        let r = RendererGovernedTurnResult::blocked(
            CRID.into(), "bt-1".into(), "conv-1".into(), TurnReason::TurnInProgress);
        let json = r.to_json();
        assert!(json.contains(r#""status":"blocked""#));
        assert!(json.contains(r#""reason":"turn_in_progress""#));
        assert!(!json.contains(r#""message""#)); // blocked carries no assistant message
    }
}
