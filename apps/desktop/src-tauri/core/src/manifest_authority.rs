//! Wave 3b — the validated signed-manifest **receipt-key authority** (design §5): the in-crate resolver
//! that [`crate::receipt::ResolvedManifestKey`]'s doc names as the ONLY thing allowed to mint a resolved
//! key. It closes the seam Wave 3a shipped as [`crate::receipt_store::NoTrustedManifest`] (always
//! `Unavailable`): given an operator-provisioned key manifest that has been verified against the
//! **binary-pinned root** + anti-rollback-checked, it resolves a receipt's `key_id` to the pinned
//! production verifying key.
//!
//! FAIL-CLOSED: [`ManifestReceiptKeyAuthority::new`] verifies the manifest root signature AND anti-rollback
//! at construction; on any failure — or via [`ManifestReceiptKeyAuthority::fail_closed`] — it holds NO keys
//! and every `resolve` returns `Unavailable` (identical to `NoTrustedManifest`). It only ever mints a key
//! that `resolve_production_key` classified as **production-class, in-window, non-revoked, protocol-allowed**
//! — never a development or expired/revoked key — so it cannot turn a non-production key into "Verified".
//!
//! NOTE (scope): this resolves the trusted key; whether the Wave-3a `receipt_store` renders `trusted_verified`
//! for a production key is a SEPARATE, audited Wave-3b store change. On its own this authority does not
//! expose "Verified" — a production key still resolves to `Blocked` in the Wave-3a store.

use crate::domain::CoreResult;
use crate::key_manifest::{
    check_and_advance, resolve_production_key, verify_manifest, AntiRollbackFloor, KeyManifest, PinnedRoot,
};
use crate::receipt::{ResolvedManifestKey, TrustClass};
use crate::receipt_store::{KeyResolution, ReceiptKeyAuthority};

/// A receipt-key authority backed by a root-verified, anti-rollback-checked production key manifest.
pub struct ManifestReceiptKeyAuthority {
    /// `(key_id, 32-byte ed25519 public key)` for every manifest key that resolved as a valid production
    /// key at construction time. Empty ⇒ fail-closed (every resolve is `Unavailable`).
    keys: Vec<(String, Vec<u8>)>,
}

fn hex32(s: &str) -> Option<[u8; 32]> {
    if s.len() != 64 {
        return None;
    }
    let b = s.as_bytes();
    let mut out = [0u8; 32];
    for i in 0..32 {
        let hi = (b[2 * i] as char).to_digit(16)?;
        let lo = (b[2 * i + 1] as char).to_digit(16)?;
        out[i] = (hi * 16 + lo) as u8;
    }
    Some(out)
}

impl ManifestReceiptKeyAuthority {
    /// A fail-closed authority: no trusted manifest ⇒ every `resolve` is `Unavailable`.
    pub fn fail_closed() -> Self {
        ManifestReceiptKeyAuthority { keys: Vec::new() }
    }

    /// Build from a provisioned manifest. Verifies the root signature against the binary-pinned root AND
    /// anti-rollback BEFORE resolving any key; on any failure returns the fail-closed authority. Then
    /// resolves every manifest key through `resolve_production_key` (production-class / in-window /
    /// non-revoked / protocol-allowed) at `now_ms` and holds only those. Never mints a non-production key.
    pub fn new(
        manifest: &KeyManifest,
        root_sig_b64: &str,
        pinned: &PinnedRoot,
        floor: &AntiRollbackFloor,
        protocol: &str,
        now_ms: i64,
    ) -> Self {
        if verify_manifest(manifest, root_sig_b64, pinned).is_err() {
            return Self::fail_closed();
        }
        if check_and_advance(floor, manifest).is_err() {
            return Self::fail_closed();
        }
        let mut keys = Vec::new();
        for k in &manifest.keys {
            if let Ok(rk) = resolve_production_key(manifest, &k.key_id, protocol, now_ms) {
                if let Some(bytes) = hex32(&rk.public_key_hex) {
                    keys.push((rk.key_id, bytes.to_vec()));
                }
            }
        }
        ManifestReceiptKeyAuthority { keys }
    }

    /// True iff at least one production key resolved (i.e. a trusted manifest is active).
    pub fn is_trusted(&self) -> bool {
        !self.keys.is_empty()
    }
}

impl ReceiptKeyAuthority for ManifestReceiptKeyAuthority {
    fn resolve<'a>(&'a self, key_id: &str) -> CoreResult<KeyResolution<'a>> {
        for (kid, bytes) in &self.keys {
            if kid == key_id {
                return Ok(KeyResolution::Trusted(ResolvedManifestKey::manifest_resolved(
                    kid,
                    bytes,
                    TrustClass::Production,
                )));
            }
        }
        Ok(KeyResolution::Unavailable(
            "key_id is not a resolved production key in the trusted manifest",
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::key_manifest::{ManifestKey, TrustClass as MTrustClass};
    use base64::Engine as _;
    use ed25519_dalek::{Signer, SigningKey};

    fn sk(seed: [u8; 32]) -> SigningKey {
        SigningKey::from_bytes(&seed)
    }
    fn hex(b: &[u8]) -> String {
        b.iter().map(|x| format!("{x:02x}")).collect()
    }

    const PROTO: &str = "brops.governed-receipt-envelope.v1";

    fn manifest_with(keys: Vec<ManifestKey>) -> KeyManifest {
        KeyManifest { manifest_epoch: 2, root_key_id: "root-1".into(), keys }
    }
    fn key(id: &str, pk_hex: String, cls: MTrustClass, revoked: bool) -> ManifestKey {
        ManifestKey {
            key_id: id.into(),
            public_key_hex: pk_hex,
            trust_class: cls,
            valid_from_ms: 1,
            valid_to_ms: 9_999_999_999_999,
            key_epoch: 2,
            revoked,
            allowed_protocols: vec![PROTO.to_string()],
        }
    }

    #[test]
    fn resolves_a_production_key_and_rejects_everything_else() {
        let root = sk([9u8; 32]);
        let prod = sk([1u8; 32]);
        let dev = sk([2u8; 32]);
        let revoked = sk([3u8; 32]);
        let manifest = manifest_with(vec![
            key("prod-1", hex(prod.verifying_key().as_bytes()), MTrustClass::Production, false),
            key("dev-1", hex(dev.verifying_key().as_bytes()), MTrustClass::Development, false),
            key("rev-1", hex(revoked.verifying_key().as_bytes()), MTrustClass::Production, true),
        ]);
        let pinned = PinnedRoot { root_key_id: "root-1".into(), public_key_hex: hex(root.verifying_key().as_bytes()) };
        let root_sig = base64::engine::general_purpose::STANDARD.encode(root.sign(&manifest.canonical_bytes()).to_bytes());
        let floor = AntiRollbackFloor { highest_epoch: 2, highest_hash: manifest.content_hash() };
        let auth = ManifestReceiptKeyAuthority::new(&manifest, &root_sig, &pinned, &floor, PROTO, 1000);
        assert!(auth.is_trusted());
        // The production key resolves Trusted with its pinned bytes.
        match auth.resolve("prod-1").unwrap() {
            KeyResolution::Trusted(_) => {}
            KeyResolution::Unavailable(r) => panic!("expected Trusted, got Unavailable({r})"),
        }
        // Development, revoked, and unknown key ids are all fail-closed Unavailable.
        for id in ["dev-1", "rev-1", "nope"] {
            assert!(matches!(auth.resolve(id).unwrap(), KeyResolution::Unavailable(_)), "{id} must be Unavailable");
        }
    }

    #[test]
    fn a_bad_root_signature_is_fail_closed() {
        let root = sk([9u8; 32]);
        let prod = sk([1u8; 32]);
        let manifest = manifest_with(vec![key("prod-1", hex(prod.verifying_key().as_bytes()), MTrustClass::Production, false)]);
        let pinned = PinnedRoot { root_key_id: "root-1".into(), public_key_hex: hex(root.verifying_key().as_bytes()) };
        let floor = AntiRollbackFloor { highest_epoch: 2, highest_hash: manifest.content_hash() };
        // Garbage root signature ⇒ no keys ⇒ every resolve Unavailable.
        let auth = ManifestReceiptKeyAuthority::new(&manifest, "bogus", &pinned, &floor, PROTO, 1000);
        assert!(!auth.is_trusted());
        assert!(matches!(auth.resolve("prod-1").unwrap(), KeyResolution::Unavailable(_)));
        // The explicit fail-closed constructor is also always Unavailable.
        assert!(matches!(ManifestReceiptKeyAuthority::fail_closed().resolve("prod-1").unwrap(), KeyResolution::Unavailable(_)));
    }
}
