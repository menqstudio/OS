//! Wave 3b-3 — production trust resolution (ties the 3b-2 signed key manifest to the §7 verified turn to
//! render the FIRST production `trusted_verified`, or fail closed to `NoTrustedManifest`).
//!
//! Given a governed turn whose isolated-signer envelope already verified (§7, `governed_verification`) and
//! a root-verified, anti-rollback-checked key manifest (§3b-2, `key_manifest`), this resolves whether the
//! signing key is a PRODUCTION-class, in-window, non-revoked, protocol-allowed key. Only then is the turn
//! `Production` trusted_verified. Absence of a trusted manifest, or any resolution failure, is
//! `NoTrustedManifest` — the fail-closed default that keeps "Verified" honest.

use crate::key_manifest::{resolve_production_key, KeyManifest, ManifestError};

/// The rendered trust state of a verified governed turn.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TrustState {
    /// A production-class manifest key resolved — this turn is a real production `trusted_verified`.
    Production { key_id: String, key_epoch: u64 },
    /// No trusted manifest / no production key resolved — fail closed. Never renders production "Verified".
    NoTrustedManifest(&'static str),
}

impl TrustState {
    /// True ONLY for [`TrustState::Production`]. The single gate the UI consults to show production
    /// "Verified".
    pub fn is_production_verified(&self) -> bool {
        matches!(self, TrustState::Production { .. })
    }
}

/// Resolve the production trust state. `manifest` MUST already be (a) signature-verified against the pinned
/// root and (b) anti-rollback-accepted by the caller (see `key_manifest::verify_manifest` +
/// `check_and_advance`); pass `None` when no trusted manifest is provisioned (the `NoTrustedManifest`
/// slice-3 default). `signer_key_id`/`protocol` come from the already-verified envelope (§7), never from
/// the renderer.
pub fn resolve_trust_state(
    manifest: Option<&KeyManifest>,
    signer_key_id: &str,
    protocol: &str,
    now_ms: i64,
) -> TrustState {
    let manifest = match manifest {
        Some(m) => m,
        None => return TrustState::NoTrustedManifest("no trusted manifest provisioned"),
    };
    match resolve_production_key(manifest, signer_key_id, protocol, now_ms) {
        Ok(k) => TrustState::Production { key_id: k.key_id, key_epoch: k.key_epoch },
        Err(ManifestError::NotProduction) => TrustState::NoTrustedManifest("signing key is not production class"),
        Err(ManifestError::Revoked) => TrustState::NoTrustedManifest("signing key revoked"),
        Err(ManifestError::OutOfWindow) => TrustState::NoTrustedManifest("signing key outside validity window"),
        Err(ManifestError::KeyNotFound) => TrustState::NoTrustedManifest("signing key not in manifest"),
        Err(ManifestError::ProtocolNotAllowed) => TrustState::NoTrustedManifest("signing key not allowed for this protocol"),
        Err(_) => TrustState::NoTrustedManifest("manifest resolution failed"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::key_manifest::{KeyManifest, ManifestKey, TrustClass};

    fn manifest() -> KeyManifest {
        KeyManifest {
            manifest_epoch: 3,
            root_key_id: "root-1".into(),
            keys: vec![ManifestKey {
                key_id: "signer-prod".into(),
                public_key_hex: "00".repeat(32),
                trust_class: TrustClass::Production,
                valid_from_ms: 1000,
                valid_to_ms: 9999,
                key_epoch: 4,
                revoked: false,
                allowed_protocols: vec!["brops.governed-receipt-envelope.v1".into()],
            }],
        }
    }
    const PROTO: &str = "brops.governed-receipt-envelope.v1";

    #[test]
    fn a_production_key_renders_production_verified() {
        let ts = resolve_trust_state(Some(&manifest()), "signer-prod", PROTO, 5000);
        assert!(ts.is_production_verified());
        assert_eq!(ts, TrustState::Production { key_id: "signer-prod".into(), key_epoch: 4 });
    }

    #[test]
    fn no_manifest_is_no_trusted_manifest() {
        let ts = resolve_trust_state(None, "signer-prod", PROTO, 5000);
        assert!(!ts.is_production_verified());
        assert!(matches!(ts, TrustState::NoTrustedManifest(_)));
    }

    #[test]
    fn every_resolution_failure_fails_closed_to_no_trusted_manifest() {
        let m = manifest();
        assert!(!resolve_trust_state(Some(&m), "unknown", PROTO, 5000).is_production_verified());
        assert!(!resolve_trust_state(Some(&m), "signer-prod", PROTO, 500).is_production_verified()); // out of window
        assert!(!resolve_trust_state(Some(&m), "signer-prod", "other", 5000).is_production_verified()); // protocol
        let mut dev = manifest(); dev.keys[0].trust_class = TrustClass::Development;
        assert!(!resolve_trust_state(Some(&dev), "signer-prod", PROTO, 5000).is_production_verified());
        let mut rev = manifest(); rev.keys[0].revoked = true;
        assert!(!resolve_trust_state(Some(&rev), "signer-prod", PROTO, 5000).is_production_verified());
    }
}
