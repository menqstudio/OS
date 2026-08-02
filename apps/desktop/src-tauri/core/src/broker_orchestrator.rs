//! Wave 3b-1B — broker-service governed-turn orchestrator (implements the design-GREEN rev-30 §4.10(g)
//! `governed_turn_execute` broker-service flow: strict request decode → payload-aware idempotency →
//! governed execution+verification (abstracted) → commit-readback persistence → the closed
//! committed/blocked reply).
//!
//! This is the pure control flow that runs INSIDE the trusted broker service (never the renderer). The
//! challenge→authority→supervisor→signer→verification chain is injected via [`GovernedExecutor`] so the
//! whole flow is end-to-end unit-testable with a fake executor, on any host, without the OS trust chain.
//! The broker mints the authoritative `broker_turn_id` + `request_nonce`; the renderer supplies only the
//! closed `{conversation_id, agent?, client_request_id}` request.

use rusqlite::Connection;

use crate::broker_turns::{self, TurnState};
use crate::governed_message_store::{persist_committed, AcceptedOutput};
use crate::governed_turn_ipc::{
    IdempotencyDecision, RendererGovernedTurnResult, TurnReason, ValidatedRequest,
};

/// The governed execution + verification chain (challenge → authority → supervisor → signer →
/// isolated-signer envelope verification), abstracted. A real impl drives the AF_UNIX chain; a test
/// injects a fake. Returns the verified accepted output (whose body length+SHA-256 matched the signed
/// envelope) or a closed [`TurnReason`] on any upstream refusal.
pub trait GovernedExecutor {
    /// Execute + verify the governed turn identified by `broker_turn_id`/`request_nonce` for `req`.
    fn execute_and_verify(
        &self,
        req: &ValidatedRequest,
        broker_turn_id: &str,
        request_nonce: &str,
    ) -> Result<AcceptedOutput, TurnReason>;
}

/// Broker-minted authoritative identities for a turn. In production these come from `brops_core::id()` +
/// the nonce mint; a test injects deterministic values. The renderer can NEVER supply these.
pub trait BrokerIds {
    fn new_broker_turn_id(&self) -> String;
    fn new_request_nonce(&self) -> String;
}

/// Run one governed turn end-to-end inside the broker service. `raw_request` is the exact renderer frame
/// bytes. Never panics; every failure path returns a closed `blocked` reply. On success returns a
/// `committed` reply carrying the broker-produced immutable message projection.
pub fn run_governed_turn(
    conn: &Connection,
    raw_request: &str,
    ids: &dyn BrokerIds,
    executor: &dyn GovernedExecutor,
    now_ms: i64,
) -> RendererGovernedTurnResult {
    // 1. Strict-decode + validate the renderer frame. A malformed frame has no correlation id to echo
    //    beyond what little we can salvage, so we echo empty ids on the malformed path.
    let req = match ValidatedRequest::decode(raw_request) {
        Ok(r) => r,
        Err(reason) => {
            return RendererGovernedTurnResult::blocked(
                String::new(),
                String::new(),
                String::new(),
                reason,
            )
        }
    };
    let crid = req.client_request_id.clone();
    let conv = req.conversation_id.clone();

    // 2. Payload-aware idempotency (rev-30 P1-1).
    match broker_turns::decide(conn, &req) {
        Ok(IdempotencyDecision::Reattach(existing)) => {
            // A live exact-duplicate: do not start a second turn. Surface an in-progress reply bound to
            // the SAME broker_turn_id (the original turn's committed result is delivered on its own path).
            return RendererGovernedTurnResult::blocked(crid, existing, conv, TurnReason::TurnInProgress);
        }
        Ok(IdempotencyDecision::RetryConflict) => {
            return RendererGovernedTurnResult::blocked(crid, String::new(), conv, TurnReason::RetryConflict);
        }
        Ok(IdempotencyDecision::TurnInProgress) => {
            return RendererGovernedTurnResult::blocked(crid, String::new(), conv, TurnReason::TurnInProgress);
        }
        Ok(IdempotencyDecision::New) => {}
        Err(_) => {
            return RendererGovernedTurnResult::blocked(crid, String::new(), conv, TurnReason::UpstreamBlocked);
        }
    }

    // 3. Mint the broker-authoritative identities and record the live turn. The INSERT is the atomic
    //    guard behind the (non-atomic) `decide` read above: the partial UNIQUE one-live-per-conversation
    //    index makes a concurrency loser fail here as `TurnInProgress`, which we surface as the SAME
    //    fail-closed `turn_in_progress` reply the `decide` branch returns. Any OTHER store failure stays
    //    fail-closed as `UpstreamBlocked`.
    let broker_turn_id = ids.new_broker_turn_id();
    let request_nonce = ids.new_request_nonce();
    match broker_turns::record_new(conn, &req.idempotency_key(), &broker_turn_id, &request_nonce, now_ms) {
        Ok(()) => {}
        Err(broker_turns::StoreError::TurnInProgress) => {
            return RendererGovernedTurnResult::blocked(crid, String::new(), conv, TurnReason::TurnInProgress);
        }
        Err(_) => {
            return RendererGovernedTurnResult::blocked(crid, broker_turn_id, conv, TurnReason::UpstreamBlocked);
        }
    }

    // 4. Drive the governed execution + verification chain.
    let accepted = match executor.execute_and_verify(&req, &broker_turn_id, &request_nonce) {
        Ok(a) => a,
        Err(reason) => {
            let _ = broker_turns::settle(conn, &broker_turn_id, TurnState::Blocked);
            return RendererGovernedTurnResult::blocked(crid, broker_turn_id, conv, reason);
        }
    };

    // 5. Persist with in-tx commit-readback (rev-30 P0). On any mismatch, fail closed.
    match persist_committed(conn, &accepted) {
        Ok(message) => {
            let _ = broker_turns::settle(conn, &broker_turn_id, TurnState::Committed);
            RendererGovernedTurnResult::committed(crid, broker_turn_id, conv, message)
        }
        Err(reason) => {
            let _ = broker_turns::settle(conn, &broker_turn_id, TurnState::Blocked);
            RendererGovernedTurnResult::blocked(crid, broker_turn_id, conv, reason)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::governed_message_store::{create_schema as create_msg_schema, sha256_hex};
    use crate::governed_turn_ipc::{REQUEST_PROTOCOL, TRUSTED_VERIFIED};

    const CRID: &str = "3f2504e0-4f89-41d3-9a0c-0305e82c3301";

    struct FixedIds;
    impl BrokerIds for FixedIds {
        fn new_broker_turn_id(&self) -> String { "bt-fixed".into() }
        fn new_request_nonce(&self) -> String { "nonce-fixed".into() }
    }

    struct OkExecutor { body: String }
    impl GovernedExecutor for OkExecutor {
        fn execute_and_verify(&self, req: &ValidatedRequest, bt: &str, _n: &str) -> Result<AcceptedOutput, TurnReason> {
            Ok(AcceptedOutput {
                broker_turn_id: bt.to_string(),
                message_id: format!("m-{bt}"),
                conversation_id: req.conversation_id.clone(),
                author: "Bro".into(),
                accepted_body: self.body.clone(),
                envelope_body_sha256: sha256_hex(self.body.as_bytes()),
                created_at_ms: 42,
            })
        }
    }
    struct BlockingExecutor;
    impl GovernedExecutor for BlockingExecutor {
        fn execute_and_verify(&self, _r: &ValidatedRequest, _b: &str, _n: &str) -> Result<AcceptedOutput, TurnReason> {
            Err(TurnReason::UpstreamBlocked)
        }
    }

    fn conn() -> Connection {
        let c = Connection::open_in_memory().unwrap();
        broker_turns::create_schema(&c).unwrap();
        create_msg_schema(&c).unwrap();
        c
    }
    fn raw(conv: &str, crid: &str) -> String {
        format!(r#"{{"protocol":"{REQUEST_PROTOCOL}","conversation_id":"{conv}","agent":"a","client_request_id":"{crid}"}}"#)
    }

    #[test]
    fn happy_path_returns_committed_verified_message() {
        let c = conn();
        let r = run_governed_turn(&c, &raw("conv-1", CRID), &FixedIds, &OkExecutor { body: "hi there".into() }, 1);
        assert_eq!(r.status, "committed");
        let m = r.message.unwrap();
        assert_eq!(m.body, "hi there");
        assert_eq!(m.trust_state, TRUSTED_VERIFIED);
        assert_eq!(r.broker_turn_id, "bt-fixed");
        assert_eq!(r.client_request_id, CRID);
    }

    #[test]
    fn malformed_request_is_blocked_with_no_message() {
        let c = conn();
        let r = run_governed_turn(&c, r#"{"protocol":"x"}"#, &FixedIds, &OkExecutor { body: "z".into() }, 1);
        assert_eq!(r.status, "blocked");
        assert_eq!(r.reason, Some(TurnReason::Malformed));
        assert!(r.message.is_none());
    }

    #[test]
    fn upstream_refusal_is_blocked_and_settles_the_turn() {
        let c = conn();
        let r = run_governed_turn(&c, &raw("conv-1", CRID), &FixedIds, &BlockingExecutor, 1);
        assert_eq!(r.status, "blocked");
        assert_eq!(r.reason, Some(TurnReason::UpstreamBlocked));
        // the turn was settled (not left live) → a later request on the same conversation is NOT
        // turn_in_progress; it starts fresh (New path). We assert by running a fresh request:
        assert!(broker_turns::live_turns(&c).unwrap().is_empty());
    }

    #[test]
    fn second_live_request_same_conversation_is_turn_in_progress() {
        let c = conn();
        // leave a live turn by using an executor that we do NOT run to completion: instead record one.
        let req = ValidatedRequest::decode(&raw("conv-1", CRID)).unwrap();
        broker_turns::record_new(&c, &req.idempotency_key(), "bt-1", "n-1", 1).unwrap();
        let other = "00000000-0000-4000-8000-000000000000";
        let r = run_governed_turn(&c, &raw("conv-1", other), &FixedIds, &OkExecutor { body: "x".into() }, 2);
        assert_eq!(r.status, "blocked");
        assert_eq!(r.reason, Some(TurnReason::TurnInProgress));
    }
}
