//! Wave 3b-2 — signed key manifest + pinned root trust anchor + anti-rollback (implements the 3b-0
//! isolated-signer DESIGN-GREEN manifest contract: an operator-provisioned signed key manifest validated
//! against a **binary-pinned root trust anchor**, per-key trust class / validity / revocation /
//! allowed-protocols, and **anti-rollback** on a durable highest accepted `manifest_epoch` + hash).
//!
//! This is what turns a verified governed turn into a PRODUCTION `trusted_verified`: only a manifest that
//! (a) is signed by the pinned root, (b) is not rolled back, and (c) resolves a **production**-class,
//! in-window, non-revoked, protocol-allowed key renders "Verified". Anything else fails closed
//! (`NoTrustedManifest`-equivalent). Pure + fully unit-tested (the root key + signing appear only in tests).

use ed25519_dalek::{Signature, VerifyingKey};
use serde::{Deserialize, Serialize};

use crate::governed_message_store::sha256_hex;

/// Per-key trust class. Only [`TrustClass::Production`] keys may render production `trusted_verified`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TrustClass {
    Production,
    Development,
}

/// One key entry in the manifest.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ManifestKey {
    pub key_id: String,
    /// lowercase-hex Ed25519 public key (64 hex chars = 32 bytes).
    pub public_key_hex: String,
    pub trust_class: TrustClass,
    pub valid_from_ms: i64,
    pub valid_to_ms: i64,
    pub key_epoch: u64,
    pub revoked: bool,
    /// Protocol audiences this key may sign for (a resolve for a protocol not listed is refused).
    pub allowed_protocols: Vec<String>,
}

/// The operator-provisioned signed key manifest.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct KeyManifest {
    /// Monotonic manifest epoch — the anti-rollback key.
    pub manifest_epoch: u64,
    /// The root key id that must have signed this manifest (selects among pinned roots).
    pub root_key_id: String,
    pub keys: Vec<ManifestKey>,
}

impl KeyManifest {
    /// Canonical bytes the root signs: sorted-key compact JSON (the JCS-ish convention shared with the
    /// receipt/store side). Deterministic — the same manifest always yields the same bytes.
    pub fn canonical_bytes(&self) -> Vec<u8> {
        // serde_json with sorted keys via a BTreeMap round-trip is overkill; the struct field order is
        // fixed, so serde_json::to_vec is deterministic for this closed shape.
        serde_json::to_vec(self).expect("KeyManifest serializes")
    }

    /// The content hash used by the anti-rollback floor (distinguishes two manifests at the same epoch).
    pub fn content_hash(&self) -> String {
        sha256_hex(&self.canonical_bytes())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ManifestError {
    /// The root signature did not verify under the pinned root public key.
    RootSignatureInvalid,
    /// The manifest names a root key id that is not the pinned root.
    UnknownRoot,
    /// No key with the requested id.
    KeyNotFound,
    /// The key exists but is not production class (cannot render production Verified).
    NotProduction,
    /// The key is outside its validity window.
    OutOfWindow,
    /// The key is revoked.
    Revoked,
    /// The key is not allowed for the requested protocol.
    ProtocolNotAllowed,
    /// A malformed public key / signature encoding.
    Malformed,
}

/// A pinned root trust anchor: the binary-pinned root key id + its Ed25519 public key. Provisioned in the
/// TCB (root-owned), never taken from the manifest itself.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PinnedRoot {
    pub root_key_id: String,
    pub public_key_hex: String,
}

fn verify_ed25519(public_key_hex: &str, msg: &[u8], signature_b64: &str) -> Result<(), ManifestError> {
    let key_bytes = decode_hex32(public_key_hex).ok_or(ManifestError::Malformed)?;
    let vk = VerifyingKey::from_bytes(&key_bytes).map_err(|_| ManifestError::Malformed)?;
    let sig_bytes = base64_decode(signature_b64).ok_or(ManifestError::Malformed)?;
    let sig = Signature::from_slice(&sig_bytes).map_err(|_| ManifestError::Malformed)?;
    vk.verify_strict(msg, &sig).map_err(|_| ManifestError::RootSignatureInvalid)
}

/// Verify the manifest is signed by the pinned root (binary-pinned anchor), refusing an unknown root id or
/// a bad signature. The `root_sig_b64` is a detached Ed25519 signature over `manifest.canonical_bytes()`.
pub fn verify_manifest(
    manifest: &KeyManifest,
    root_sig_b64: &str,
    pinned: &PinnedRoot,
) -> Result<(), ManifestError> {
    if manifest.root_key_id != pinned.root_key_id {
        return Err(ManifestError::UnknownRoot);
    }
    verify_ed25519(&pinned.public_key_hex, &manifest.canonical_bytes(), root_sig_b64)
}

/// A resolved production key — the mandatory bind that renders `trusted_verified`. Only produced by
/// [`resolve_production_key`] after every check passes.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResolvedManifestKey {
    pub key_id: String,
    pub public_key_hex: String,
    pub key_epoch: u64,
}

/// Resolve a PRODUCTION key for `protocol` at `now_ms` from a (separately root-verified) manifest. Every
/// failure is fail-closed. Success ⇒ a production-class, in-window, non-revoked, protocol-allowed key that
/// may render production `trusted_verified`.
pub fn resolve_production_key(
    manifest: &KeyManifest,
    key_id: &str,
    protocol: &str,
    now_ms: i64,
) -> Result<ResolvedManifestKey, ManifestError> {
    let k = manifest.keys.iter().find(|k| k.key_id == key_id).ok_or(ManifestError::KeyNotFound)?;
    if k.trust_class != TrustClass::Production {
        return Err(ManifestError::NotProduction);
    }
    if k.revoked {
        return Err(ManifestError::Revoked);
    }
    if now_ms < k.valid_from_ms || now_ms >= k.valid_to_ms {
        return Err(ManifestError::OutOfWindow);
    }
    if !k.allowed_protocols.iter().any(|p| p == protocol) {
        return Err(ManifestError::ProtocolNotAllowed);
    }
    Ok(ResolvedManifestKey { key_id: k.key_id.clone(), public_key_hex: k.public_key_hex.clone(), key_epoch: k.key_epoch })
}

/// The durable anti-rollback floor: the highest accepted `manifest_epoch` + its content hash.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AntiRollbackFloor {
    pub highest_epoch: u64,
    pub highest_hash: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RollbackError {
    /// The new manifest's epoch is below the highest accepted (a rollback).
    EpochBelowFloor,
    /// Same epoch as the floor but a DIFFERENT content hash (a fork/tamper at the same epoch).
    SameEpochDifferentHash,
}

/// Anti-rollback CAS (3b-0 contract): accept `manifest` only if its epoch is strictly higher than the
/// floor, OR equal to the floor with the SAME content hash (idempotent re-accept). Refuse a lower epoch,
/// or an equal epoch with a differing hash. On accept, returns the advanced floor to persist.
pub fn check_and_advance(
    floor: &AntiRollbackFloor,
    manifest: &KeyManifest,
) -> Result<AntiRollbackFloor, RollbackError> {
    let new_hash = manifest.content_hash();
    if manifest.manifest_epoch < floor.highest_epoch {
        return Err(RollbackError::EpochBelowFloor);
    }
    if manifest.manifest_epoch == floor.highest_epoch && new_hash != floor.highest_hash {
        return Err(RollbackError::SameEpochDifferentHash);
    }
    Ok(AntiRollbackFloor { highest_epoch: manifest.manifest_epoch, highest_hash: new_hash })
}

// --- tiny hex/base64 helpers (no extra deps; base64 crate is present but keep this module self-checking) -
fn decode_hex32(s: &str) -> Option<[u8; 32]> {
    if s.len() != 64 {
        return None;
    }
    let mut out = [0u8; 32];
    let b = s.as_bytes();
    for i in 0..32 {
        let hi = (b[2 * i] as char).to_digit(16)?;
        let lo = (b[2 * i + 1] as char).to_digit(16)?;
        out[i] = (hi * 16 + lo) as u8;
    }
    Some(out)
}
fn base64_decode(s: &str) -> Option<Vec<u8>> {
    use base64::Engine;
    base64::engine::general_purpose::STANDARD.decode(s.as_bytes()).ok()
}

#[cfg(test)]
mod tests {
    use super::*;
    use base64::Engine;
    use ed25519_dalek::{Signer, SigningKey};

    fn signing_key(seed: u8) -> SigningKey {
        SigningKey::from_bytes(&[seed; 32])
    }
    fn pubhex(k: &SigningKey) -> String {
        k.verifying_key().to_bytes().iter().map(|b| format!("{:02x}", b)).collect()
    }
    fn sign_b64(k: &SigningKey, msg: &[u8]) -> String {
        base64::engine::general_purpose::STANDARD.encode(k.sign(msg).to_bytes())
    }

    fn manifest(epoch: u64, prod_key: &SigningKey) -> KeyManifest {
        KeyManifest {
            manifest_epoch: epoch,
            root_key_id: "root-1".into(),
            keys: vec![ManifestKey {
                key_id: "prod-1".into(),
                public_key_hex: pubhex(prod_key),
                trust_class: TrustClass::Production,
                valid_from_ms: 1000,
                valid_to_ms: 9999,
                key_epoch: 7,
                revoked: false,
                allowed_protocols: vec!["brops.governed-receipt-envelope.v1".into()],
            }],
        }
    }

    #[test]
    fn verifies_a_root_signed_manifest_and_rejects_a_bad_one() {
        let root = signing_key(1);
        let prod = signing_key(2);
        let pinned = PinnedRoot { root_key_id: "root-1".into(), public_key_hex: pubhex(&root) };
        let m = manifest(5, &prod);
        let sig = sign_b64(&root, &m.canonical_bytes());
        assert!(verify_manifest(&m, &sig, &pinned).is_ok());
        // wrong root key
        let other = signing_key(9);
        let badsig = sign_b64(&other, &m.canonical_bytes());
        assert_eq!(verify_manifest(&m, &badsig, &pinned), Err(ManifestError::RootSignatureInvalid));
        // unknown root id
        let m2 = KeyManifest { root_key_id: "root-2".into(), ..m.clone() };
        let sig2 = sign_b64(&root, &m2.canonical_bytes());
        assert_eq!(verify_manifest(&m2, &sig2, &pinned), Err(ManifestError::UnknownRoot));
    }

    #[test]
    fn resolves_a_production_key_and_fails_closed_otherwise() {
        let prod = signing_key(2);
        let m = manifest(5, &prod);
        let proto = "brops.governed-receipt-envelope.v1";
        assert!(resolve_production_key(&m, "prod-1", proto, 5000).is_ok());
        assert_eq!(resolve_production_key(&m, "nope", proto, 5000), Err(ManifestError::KeyNotFound));
        assert_eq!(resolve_production_key(&m, "prod-1", proto, 500), Err(ManifestError::OutOfWindow));
        assert_eq!(resolve_production_key(&m, "prod-1", "other.proto", 5000), Err(ManifestError::ProtocolNotAllowed));
        // revoked
        let mut mr = m.clone(); mr.keys[0].revoked = true;
        assert_eq!(resolve_production_key(&mr, "prod-1", proto, 5000), Err(ManifestError::Revoked));
        // development class
        let mut md = m.clone(); md.keys[0].trust_class = TrustClass::Development;
        assert_eq!(resolve_production_key(&md, "prod-1", proto, 5000), Err(ManifestError::NotProduction));
    }

    #[test]
    fn anti_rollback_accepts_higher_refuses_lower_and_same_epoch_fork() {
        let prod = signing_key(2);
        let floor = AntiRollbackFloor { highest_epoch: 5, highest_hash: manifest(5, &prod).content_hash() };
        // strictly higher epoch => accept + advance
        let m6 = manifest(6, &prod);
        assert_eq!(check_and_advance(&floor, &m6).unwrap().highest_epoch, 6);
        // lower epoch => rollback
        let m4 = manifest(4, &prod);
        assert_eq!(check_and_advance(&floor, &m4), Err(RollbackError::EpochBelowFloor));
        // same epoch, same hash => idempotent accept
        let m5 = manifest(5, &prod);
        assert!(check_and_advance(&floor, &m5).is_ok());
        // same epoch, DIFFERENT hash => fork refused
        let mut m5b = manifest(5, &prod); m5b.keys[0].key_epoch = 8; // changes content hash
        assert_eq!(check_and_advance(&floor, &m5b), Err(RollbackError::SameEpochDifferentHash));
    }
}
