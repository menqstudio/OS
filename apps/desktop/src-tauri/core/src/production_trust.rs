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
/// the renderer. `envelope_verifying_key_hex` is the raw lowercase hex of the 32-byte Ed25519 public key
/// the §7 `verify_and_accept` actually verified the envelope under; the resolved manifest key's
/// `public_key_hex` MUST equal it before Production is rendered, so the production verdict is bound to the
/// key that cryptographically signed the turn — not merely to a matching `key_id` string.
pub fn resolve_trust_state(
    manifest: Option<&KeyManifest>,
    signer_key_id: &str,
    protocol: &str,
    now_ms: i64,
    envelope_verifying_key_hex: &str,
) -> TrustState {
    let manifest = match manifest {
        Some(m) => m,
        None => return TrustState::NoTrustedManifest("no trusted manifest provisioned"),
    };
    match resolve_production_key(manifest, signer_key_id, protocol, now_ms) {
        Ok(k) => {
            // Bind the production verdict to the key that ACTUALLY verified the envelope. A matching
            // `key_id` is not enough — the resolved key's public key must be the one §7 verified under,
            // else a manifest key_id with an attacker-chosen public_key_hex (or a key_id collision) could
            // decouple "Production" from the signing key. Fail closed on mismatch.
            if k.public_key_hex.to_lowercase() != envelope_verifying_key_hex.to_lowercase() {
                return TrustState::NoTrustedManifest("signing key does not match the verifying key");
            }
            TrustState::Production { key_id: k.key_id, key_epoch: k.key_epoch }
        }
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
    // The key the §7 verify_and_accept actually verified the envelope under. Matches the manifest key's
    // `public_key_hex` for the happy path, so Production still renders.
    fn verifying_key() -> String { "00".repeat(32) }

    #[test]
    fn a_production_key_renders_production_verified() {
        let ts = resolve_trust_state(Some(&manifest()), "signer-prod", PROTO, 5000, &verifying_key());
        assert!(ts.is_production_verified());
        assert_eq!(ts, TrustState::Production { key_id: "signer-prod".into(), key_epoch: 4 });
    }

    #[test]
    fn no_manifest_is_no_trusted_manifest() {
        let ts = resolve_trust_state(None, "signer-prod", PROTO, 5000, &verifying_key());
        assert!(!ts.is_production_verified());
        assert!(matches!(ts, TrustState::NoTrustedManifest(_)));
    }

    #[test]
    fn every_resolution_failure_fails_closed_to_no_trusted_manifest() {
        let m = manifest();
        let vk = verifying_key();
        assert!(!resolve_trust_state(Some(&m), "unknown", PROTO, 5000, &vk).is_production_verified());
        assert!(!resolve_trust_state(Some(&m), "signer-prod", PROTO, 500, &vk).is_production_verified()); // out of window
        assert!(!resolve_trust_state(Some(&m), "signer-prod", "other", 5000, &vk).is_production_verified()); // protocol
        let mut dev = manifest(); dev.keys[0].trust_class = TrustClass::Development;
        assert!(!resolve_trust_state(Some(&dev), "signer-prod", PROTO, 5000, &vk).is_production_verified());
        let mut rev = manifest(); rev.keys[0].revoked = true;
        assert!(!resolve_trust_state(Some(&rev), "signer-prod", PROTO, 5000, &vk).is_production_verified());
    }

    #[test]
    fn manifest_key_not_matching_verifying_key_denies_production() {
        // The manifest lists "signer-prod" as a Production key with public_key_hex = 00..00, but the
        // envelope was actually §7-verified under a DIFFERENT key (11..11). Even though the key_id,
        // protocol, window, class and revocation all resolve, Production MUST be denied because the
        // manifest key is not the key that cryptographically signed the turn. Fail closed.
        let m = manifest();
        let different_verifying_key = "11".repeat(32);
        let ts = resolve_trust_state(Some(&m), "signer-prod", PROTO, 5000, &different_verifying_key);
        assert!(!ts.is_production_verified());
        assert_eq!(
            ts,
            TrustState::NoTrustedManifest("signing key does not match the verifying key")
        );
    }
}
