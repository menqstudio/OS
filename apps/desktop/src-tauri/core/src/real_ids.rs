//! Wave 3b-1B — the real broker-minted identity generator (design-GREEN rev-30 §4.10(g)/P1-1). The broker
//! mints its OWN authoritative `broker_turn_id` + `request_nonce` (UUIDv4) — the renderer can neither
//! supply nor influence them. This is the production [`crate::broker_orchestrator::BrokerIds`] impl.

use crate::broker_orchestrator::BrokerIds;

/// Production broker identity source: fresh RFC-4122 v4 UUIDs (lowercase canonical) per turn.
pub struct RealBrokerIds;

impl BrokerIds for RealBrokerIds {
    fn new_broker_turn_id(&self) -> String {
        uuid::Uuid::new_v4().to_string()
    }
    fn new_request_nonce(&self) -> String {
        uuid::Uuid::new_v4().to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::governed_turn_ipc::is_canonical_uuidv4;

    #[test]
    fn mints_distinct_canonical_uuidv4_ids() {
        let ids = RealBrokerIds;
        let a = ids.new_broker_turn_id();
        let b = ids.new_broker_turn_id();
        let n = ids.new_request_nonce();
        assert!(is_canonical_uuidv4(&a), "broker_turn_id must be canonical lowercase UUIDv4");
        assert!(is_canonical_uuidv4(&n), "request_nonce must be canonical lowercase UUIDv4");
        assert_ne!(a, b, "each broker_turn_id is fresh");
    }
}
