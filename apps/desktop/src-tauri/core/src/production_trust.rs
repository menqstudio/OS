//! Wave 3b-3 — production trust resolution (ties the 3b-2 signed key manifest to the §7 verified turn to
//! render the FIRST production `trusted_verified`, or fail closed to `NoTrustedManifest`).
//!
//! Given a governed turn whose isolated-signer envelope already verified (§7, `governed_verification`) and
//! a root-verified, anti-rollback-checked key manifest (§3b-2, `key_manifest`), this resolves whether the
//! signing key is a PRODUCTION-class, in-window, non-revoked, protocol-allowed key. Only then is the turn
//! `Production` trusted_verified. Absence of a trusted manifest, or any resolution failure, is
//! `NoTrustedManifest` — the fail-closed default that keeps "Verified" honest.

use crate::key_manifest::{
    resolve_production_key, KeyManifest, ManifestError, RootProvenance, VerifiedManifestRoot,
};

/// The rendered trust state of a verified governed turn.
///
/// **The production variant now names the root anchor.** Before, `Production` meant only "a
/// production-CLASS key in a manifest whose root signature verified" — and a manifest signed by the
/// compiled-in demonstration root satisfies that exactly, because signature arithmetic cannot
/// distinguish an operator's offline root from a key that ships in this repository. So a value that
/// read as production trust was reachable by anyone holding the binary. The anchor's identity and
/// custody provenance are now part of the value, and only an external anchor produces `Production`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TrustState {
    /// A production-class manifest key resolved AND the manifest's root signature was verified under an
    /// anchor whose custody is EXTERNAL to this build/provisioning kit — a real production
    /// `trusted_verified`.
    Production { key_id: String, key_epoch: u64, root_key_id: String },
    /// Every chain and manifest check passed, but the anchor that verified the manifest is kit-generated
    /// or a compiled-in demonstration key. The run is real and completely bound; the CUSTODY claim is
    /// not production, so this must never render as production "Verified".
    DemonstrationCustody {
        key_id: String,
        key_epoch: u64,
        root_key_id: String,
        root_provenance: RootProvenance,
    },
    /// No trusted manifest / no verified anchor / no production key resolved — fail closed. Never
    /// renders production "Verified".
    NoTrustedManifest(&'static str),
}

impl TrustState {
    /// True ONLY for [`TrustState::Production`]. The single gate the UI consults to show production
    /// "Verified". [`TrustState::DemonstrationCustody`] is deliberately false here: the chain ran, but
    /// the root that vouched for the keys is one this build could have minted itself.
    pub fn is_production_verified(&self) -> bool {
        matches!(self, TrustState::Production { .. })
    }

    /// True when the manifest+key resolution fully succeeded, whatever the anchor's custody. This is the
    /// "did the governed chain bind a trusted_verified turn" question, which is separate from — and
    /// weaker than — the production custody claim. Drivers use it to report an honest demonstration run
    /// as a completed run rather than a failure.
    pub fn is_chain_bound(&self) -> bool {
        matches!(self, TrustState::Production { .. } | TrustState::DemonstrationCustody { .. })
    }

    /// The exact string this state may be COMMITTED as, or `None` when it may not be committed.
    ///
    /// `governed_messages.trust_state` used to be the literal `'trusted_verified'` in the INSERT,
    /// behind a CHECK constraint that permitted no other value — so the column asserted full trust
    /// for every row and no code path could ever have made it say otherwise. An independent audit
    /// found the matching hole: nothing in production called [`resolve_trust_state`] at all, so the
    /// custody question was never asked and the answer was stored anyway.
    ///
    /// A demonstration-custody run gets its own label rather than being either promoted or thrown
    /// away. The chain genuinely ran and genuinely bound the body; what is unproven is who controls
    /// the anchor. The renderer keys its badge off this string, so the distinction survives all the
    /// way to what the owner sees.
    pub fn committed_label(&self) -> Option<&'static str> {
        match self {
            TrustState::Production { .. } => Some(crate::governed_turn_ipc::TRUSTED_VERIFIED),
            TrustState::DemonstrationCustody { .. } => Some("demonstration_custody"),
            // Nothing bound. A row here IS the claim that a governed turn produced this body, so
            // there is no weaker row to write — only a refusal.
            TrustState::NoTrustedManifest(_) => None,
        }
    }

    /// The root anchor that verified the manifest, when one did.
    pub fn root_key_id(&self) -> Option<&str> {
        match self {
            TrustState::Production { root_key_id, .. }
            | TrustState::DemonstrationCustody { root_key_id, .. } => Some(root_key_id),
            TrustState::NoTrustedManifest(_) => None,
        }
    }

    /// The custody provenance of the anchor that verified the manifest, when one did.
    pub fn root_provenance(&self) -> Option<RootProvenance> {
        match self {
            TrustState::Production { .. } => Some(RootProvenance::External),
            TrustState::DemonstrationCustody { root_provenance, .. } => Some(*root_provenance),
            TrustState::NoTrustedManifest(_) => None,
        }
    }
}

/// Resolve the production trust state.
///
/// `manifest` is the provisioned key manifest; `verified_root` is the [`VerifiedManifestRoot`] that
/// `key_manifest::verify_manifest_anchored` issued for THAT manifest. Both are required: a manifest with
/// no accompanying token is `NoTrustedManifest`, because "some root signature verified somewhere" is not
/// an input this function can act on — it has to know WHICH anchor, and the token is the only thing that
/// can say so without the caller simply asserting it. The caller must still have run
/// `check_and_advance` (anti-rollback) itself; that is orthogonal to custody and not represented here.
///
/// `signer_key_id`/`protocol` come from the already-verified envelope (§7), never from the renderer.
/// `envelope_verifying_key_hex` is the raw lowercase hex of the 32-byte Ed25519 public key the §7
/// `verify_and_accept` actually verified the envelope under; the resolved manifest key's
/// `public_key_hex` MUST equal it before any trusted verdict is rendered.
/// Lowercase hex of the 32-byte Ed25519 public key the chain actually verified under. Callers pass
/// the bytes they handed to `governed_verification::verify_and_accept` as
/// `PinnedKeys::isolated_signer_public_key`, so the guard below compares the manifest's key against
/// the VERIFICATION PATH rather than against a second lookup of itself (audit F-29).
pub fn verifying_key_hex(public_key: &[u8; 32]) -> String {
    let mut out = String::with_capacity(64);
    for b in public_key {
        out.push_str(&format!("{b:02x}"));
    }
    out
}

pub fn resolve_trust_state(
    manifest: Option<&KeyManifest>,
    verified_root: Option<&VerifiedManifestRoot>,
    signer_key_id: &str,
    protocol: &str,
    now_ms: i64,
    envelope_verifying_key_hex: &str,
) -> TrustState {
    let manifest = match manifest {
        Some(m) => m,
        None => return TrustState::NoTrustedManifest("no trusted manifest provisioned"),
    };
    // The anchor that verified the manifest is a REQUIRED input, not an optional annotation. Without it
    // this function would be back to "a production-class key exists in some manifest", which the
    // demonstration root satisfies.
    let root = match verified_root {
        Some(r) => r,
        None => {
            return TrustState::NoTrustedManifest("manifest not verified under a pinned root anchor")
        }
    };
    // ...and it must be the token for THIS manifest. Otherwise a token earned by an externally-anchored
    // manifest could be presented next to a locally-minted one — the classic confused-deputy swap.
    if !root.covers(manifest) {
        return TrustState::NoTrustedManifest("verified root anchor does not cover this manifest");
    }
    match resolve_production_key(manifest, signer_key_id, protocol, now_ms) {
        Ok(k) => {
            // Bind the production verdict to the key that ACTUALLY verified the envelope.
            //
            // **F-29, and the remediation audit's R-39.** Two rounds of "fix" left this comparison
            // unable to fail. Callers first passed the `public_key_hex` this same lookup had just
            // returned; the remediation changed them to pass `verifying_key_hex(bytes)` — but those
            // bytes are `hex32(resolve_production_key(...).public_key_hex)` over the SAME manifest
            // value with the SAME key_id, `resolve_production_key` selects by first match and is
            // time-independent for a fixed manifest, and the hex round trip is exact. So the second
            // audit found the same tautology wearing one more indirection, and a guard that cannot
            // fail is worse than no guard: it is a claim of a check that is not happening.
            //
            // The honest form is not a third indirection, and it is not deleting the check
            // either: a cheap fail-closed comparison that protects a FUTURE call site which
            // obtains its key some other way costs nothing and is worth keeping. What has to
            // change is the CLAIM. This is defence in depth against a caller contract being
            // broken later; it is not what binds the trust verdict to the verifying key today,
            // and the AUDIT_LEDGER must not cite it as though it were. The property that
            // actually holds today holds by CONSTRUCTION: every call site derives the key it
            // hands `verify_and_accept` from this same resolution, so there is one source, not
            // two agreeing ones.
            if k.public_key_hex.to_lowercase() != envelope_verifying_key_hex.to_lowercase() {
                return TrustState::NoTrustedManifest("signing key does not match the verifying key");
            }
            // The custody gate. Everything above establishes that a production-CLASS key signed this
            // turn under a manifest whose root signature checks out. None of it establishes that a
            // production ROOT vouched for that key: a compiled-in demonstration anchor produces an
            // identically-valid signature, and its private half is in the source tree. So the verdict
            // splits on the anchor's provenance, which reached this function inside a token only
            // `verify_manifest_anchored` can mint.
            if root.provenance().supports_production_claim() {
                TrustState::Production {
                    key_id: k.key_id,
                    key_epoch: k.key_epoch,
                    root_key_id: root.root_key_id().to_string(),
                }
            } else {
                TrustState::DemonstrationCustody {
                    key_id: k.key_id,
                    key_epoch: k.key_epoch,
                    root_key_id: root.root_key_id().to_string(),
                    root_provenance: root.provenance(),
                }
            }
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
    use crate::key_manifest::{
        verify_manifest_anchored, KeyManifest, ManifestKey, PinnedRoot, RootAnchor, TrustClass,
    };
    use base64::Engine as _;
    use ed25519_dalek::{Signer, SigningKey};

    // A REAL root keypair. The tests below sign the manifest with it and hand the same signature to
    // anchors that differ only in declared provenance — so any difference in verdict comes from the
    // custody gate, never from the arithmetic.
    fn root_key() -> SigningKey {
        SigningKey::from_bytes(&[7u8; 32])
    }
    fn pubhex(k: &SigningKey) -> String {
        k.verifying_key().to_bytes().iter().map(|b| format!("{b:02x}")).collect()
    }
    /// Mint the anchored-verification token the way a driver must: by actually verifying the manifest.
    fn token(m: &KeyManifest, provenance: RootProvenance) -> VerifiedManifestRoot {
        let root = root_key();
        let sig =
            base64::engine::general_purpose::STANDARD.encode(root.sign(&m.canonical_bytes()).to_bytes());
        let anchor = RootAnchor {
            pinned: PinnedRoot { root_key_id: "root-1".into(), public_key_hex: pubhex(&root) },
            provenance,
        };
        verify_manifest_anchored(m, &sig, &anchor).expect("root signature verifies")
    }
    fn ext_token(m: &KeyManifest) -> VerifiedManifestRoot {
        token(m, RootProvenance::External)
    }

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
    fn an_externally_anchored_production_key_renders_production_verified() {
        let m = manifest();
        let ts = resolve_trust_state(
            Some(&m),
            Some(&ext_token(&m)),
            "signer-prod",
            PROTO,
            5000,
            &verifying_key(),
        );
        assert!(ts.is_production_verified());
        assert_eq!(
            ts,
            TrustState::Production {
                key_id: "signer-prod".into(),
                key_epoch: 4,
                root_key_id: "root-1".into()
            }
        );
        assert_eq!(ts.root_provenance(), Some(RootProvenance::External));
    }

    /// **The finding.** Identical manifest, identical production-class key, identical envelope
    /// verifying key, identical valid root signature — the ONLY difference is that the anchor which
    /// verified the manifest declares demonstration custody. Before the provenance gate, this returned
    /// `TrustState::Production` and `is_production_verified() == true`, so a manifest signed by the
    /// compiled-in demonstration key (whose private half is in this repository) read as production
    /// trust. This test fails if the custody gate in `resolve_trust_state` is removed.
    #[test]
    fn a_demonstration_anchored_manifest_is_never_production_verified() {
        let m = manifest();
        let vk = verifying_key();

        let production = resolve_trust_state(Some(&m), Some(&ext_token(&m)), "signer-prod", PROTO, 5000, &vk);
        let demo = resolve_trust_state(
            Some(&m),
            Some(&token(&m, RootProvenance::Demonstration)),
            "signer-prod",
            PROTO,
            5000,
            &vk,
        );

        assert!(production.is_production_verified(), "control: the external anchor DOES render production");
        assert!(!demo.is_production_verified(), "a demonstration anchor must never read as production trust");
        assert_eq!(
            demo,
            TrustState::DemonstrationCustody {
                key_id: "signer-prod".into(),
                key_epoch: 4,
                root_key_id: "root-1".into(),
                root_provenance: RootProvenance::Demonstration,
            }
        );
        // ...and it is still an honest, completed chain run — not a failure.
        assert!(demo.is_chain_bound());
        assert!(production.is_chain_bound());
    }

    #[test]
    fn a_kit_generated_anchor_is_never_production_verified() {
        let m = manifest();
        let ts = resolve_trust_state(
            Some(&m),
            Some(&token(&m, RootProvenance::KitGenerated)),
            "signer-prod",
            PROTO,
            5000,
            &verifying_key(),
        );
        assert!(!ts.is_production_verified());
        assert_eq!(ts.root_provenance(), Some(RootProvenance::KitGenerated));
        assert!(ts.is_chain_bound());
    }

    /// The anchor token is REQUIRED, not decorative: a manifest presented without evidence of which
    /// root verified it cannot reach any trusted verdict. Fails if the `verified_root` requirement is
    /// dropped back to an optional annotation.
    #[test]
    fn a_manifest_with_no_verified_anchor_is_no_trusted_manifest() {
        let m = manifest();
        let ts = resolve_trust_state(Some(&m), None, "signer-prod", PROTO, 5000, &verifying_key());
        assert!(!ts.is_production_verified());
        assert!(!ts.is_chain_bound());
        assert_eq!(ts, TrustState::NoTrustedManifest("manifest not verified under a pinned root anchor"));
    }

    /// A token earned by an externally-anchored manifest must not launder a DIFFERENT manifest. Fails
    /// if the `covers()` binding between token and manifest bytes is removed.
    #[test]
    fn a_token_issued_for_another_manifest_confers_nothing() {
        let good = manifest();
        let good_token = ext_token(&good);
        // A second manifest the external root never signed — it swaps in an attacker-chosen key.
        let mut forged = manifest();
        forged.keys[0].public_key_hex = "22".repeat(32);
        forged.manifest_epoch = 4;

        let ts = resolve_trust_state(
            Some(&forged),
            Some(&good_token),
            "signer-prod",
            PROTO,
            5000,
            &"22".repeat(32),
        );
        assert!(!ts.is_production_verified());
        assert_eq!(
            ts,
            TrustState::NoTrustedManifest("verified root anchor does not cover this manifest")
        );
    }

    #[test]
    fn no_manifest_is_no_trusted_manifest() {
        let m = manifest();
        let ts = resolve_trust_state(None, Some(&ext_token(&m)), "signer-prod", PROTO, 5000, &verifying_key());
        assert!(!ts.is_production_verified());
        assert!(matches!(ts, TrustState::NoTrustedManifest(_)));
    }

    #[test]
    fn every_resolution_failure_fails_closed_to_no_trusted_manifest() {
        let m = manifest();
        let t = ext_token(&m);
        let vk = verifying_key();
        assert!(!resolve_trust_state(Some(&m), Some(&t), "unknown", PROTO, 5000, &vk).is_production_verified());
        // NOTE (F-29 / R-39): there is deliberately no "mismatched verifying key" case here any
        // more. It asserted a state no call site can reach, which is exactly how a guard that
        // could not fail was mistaken twice for a guard that was working.
        assert!(!resolve_trust_state(Some(&m), Some(&t), "signer-prod", PROTO, 500, &vk).is_production_verified()); // out of window
        assert!(!resolve_trust_state(Some(&m), Some(&t), "signer-prod", "other", 5000, &vk).is_production_verified()); // protocol
        let mut dev = manifest(); dev.keys[0].trust_class = TrustClass::Development;
        let dt = ext_token(&dev);
        assert!(!resolve_trust_state(Some(&dev), Some(&dt), "signer-prod", PROTO, 5000, &vk).is_production_verified());
        let mut rev = manifest(); rev.keys[0].revoked = true;
        let rt = ext_token(&rev);
        assert!(!resolve_trust_state(Some(&rev), Some(&rt), "signer-prod", PROTO, 5000, &vk).is_production_verified());
    }

    #[test]
    fn manifest_key_not_matching_verifying_key_denies_production() {
        // The manifest lists "signer-prod" as a Production key with public_key_hex = 00..00, but the
        // envelope was actually §7-verified under a DIFFERENT key (11..11). Even though the key_id,
        // protocol, window, class and revocation all resolve, Production MUST be denied because the
        // manifest key is not the key that cryptographically signed the turn. Fail closed.
        let m = manifest();
        let different_verifying_key = "11".repeat(32);
        let ts = resolve_trust_state(
            Some(&m),
            Some(&ext_token(&m)),
            "signer-prod",
            PROTO,
            5000,
            &different_verifying_key,
        );
        assert!(!ts.is_production_verified());
        assert_eq!(
            ts,
            TrustState::NoTrustedManifest("signing key does not match the verifying key")
        );
    }
}
