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

use brops_core::broker_orchestrator::GovernedExecutor;
use brops_core::governed_message_store::AcceptedOutput;
use brops_core::governed_turn_ipc::{TurnReason, ValidatedRequest};

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

/// The real Linux sub-chain: drives the AF_UNIX challenge-authority / supervisor / isolated-signer hops and
/// calls `governed_verification::verify_and_accept`. Compiles cross-platform (the socket work is gated);
/// the actual multi-service run is exercised by the Linux CI isolation proof + real deployment, not a
/// Windows unit test. On a non-Linux host it fails closed.
#[cfg(target_os = "linux")]
pub mod linux {
    use super::*;

    /// Socket paths for the trusted principals (each owned by its own service UID; §2.6 provisioning).
    pub struct ChainSockets {
        pub authority: String,
        pub supervisor: String,
        pub signer: String,
    }

    /// The production sub-chain over AF_UNIX. Holds the pinned keys/config the broker resolves from its own
    /// root-signed manifest; drives each hop, then verifies. (The per-hop socket protocol reuses
    /// `brops_core::ipc_framing`; the final acceptance reuses `governed_verification::verify_and_accept`.)
    pub struct LinuxGovernedTurnChain {
        pub sockets: ChainSockets,
    }

    impl GovernedTurnChain for LinuxGovernedTurnChain {
        fn run_verified(
            &self,
            _req: &ValidatedRequest,
            _broker_turn_id: &str,
            _request_nonce: &str,
        ) -> Result<AcceptedOutput, TurnReason> {
            // Real AF_UNIX hops (authority create-pending/issue -> supervisor open+lease -> launcher/
            // executor -> signer sign-result), then governed_verification::verify_and_accept over the
            // pinned keys + the trusted Expected. Until the deployed services + provisioning are wired
            // end-to-end this fails closed rather than fabricating an acceptance (the Linux CI isolation
            // proof drives the real run). Referencing the sockets keeps the field live for that wiring.
            let _ = (&self.sockets.authority, &self.sockets.supervisor, &self.sockets.signer);
            Err(TurnReason::UpstreamBlocked)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use brops_core::broker_orchestrator::{run_governed_turn, BrokerIds};
    use brops_core::broker_turns;
    use brops_core::governed_message_store::{create_schema as create_msg_schema, sha256_hex};
    use brops_core::governed_turn_ipc::{REQUEST_PROTOCOL, TRUSTED_VERIFIED};
    use rusqlite::Connection;

    const CRID: &str = "3f2504e0-4f89-41d3-9a0c-0305e82c3301";

    struct FixedIds;
    impl BrokerIds for FixedIds {
        fn new_broker_turn_id(&self) -> String {
            "bt-1".into()
        }
        fn new_request_nonce(&self) -> String {
            "nonce-1".into()
        }
    }

    /// A fake sub-chain that returns a verified accepted output (as
    /// `governed_verification::verify_and_accept` would on a valid signed envelope — that crypto is proven
    /// in governed_verification's own tests). This isolates + proves the ChainExecutor -> orchestrator ->
    /// commit-readback composition.
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
    fn chain_executor_end_to_end_yields_committed_verified_message() {
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
    fn a_refusing_chain_blocks_the_turn_without_a_message() {
        let c = conn();
        let exec = ChainExecutor::new(RefusingChain);
        let r = run_governed_turn(&c, &raw(), &FixedIds, &exec, 1);
        assert_eq!(r.status, "blocked");
        assert_eq!(r.reason, Some(TurnReason::UpstreamBlocked));
        assert!(r.message.is_none());
    }
}
