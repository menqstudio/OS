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

use crate::receipt::sha256_hex;

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
    /// Canonical bytes the root signs: compact JSON with the fields in STRUCT-DECLARATION order —
    /// `manifest_epoch`, `root_key_id`, `keys`, and inside each key the order [`ManifestKey`]
    /// declares. Deterministic — the same manifest always yields the same bytes.
    ///
    /// NOT sorted-key JSON, which is what this doc said. `manifest_epoch` < `root_key_id` < `keys`
    /// is not alphabetical, and neither is a key's own field order. The declaration order IS the
    /// signed form: `engine/ci/live/provision_keys.py` writes the manifest by hand in the same
    /// order ("Field order MUST match struct KeyManifest"), and reordering a field here silently
    /// invalidates every root signature ever made. `canonical_bytes_are_pinned_to_declaration_order`
    /// holds the bytes to a literal for that reason.
    pub fn canonical_bytes(&self) -> Vec<u8> {
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

/// A pinned root trust anchor: the root key id + its Ed25519 public key. Provisioned in the TCB
/// (root-owned), never taken from the manifest itself. On Linux the broker reads it from the anchor
/// file its §2.5 pin manifest pins; the Windows kit still compiles it in.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PinnedRoot {
    pub root_key_id: String,
    pub public_key_hex: String,
}

/// Where a pinned root anchor came from — the CUSTODY question that no signature check can answer.
///
/// A manifest signed by an anchor this build (or its provisioning kit, or a compiled-in demonstration
/// key) generated verifies exactly as well as one signed by an operator's offline root: the arithmetic
/// is identical, so "the signature verified" says nothing about who could have produced it. Provenance
/// is therefore asserted by whoever provisioned the anchor and carried, unforgeably, into the trust
/// verdict — see [`VerifiedManifestRoot`]. It is deliberately NOT a field of [`KeyManifest`]: a manifest
/// that could name its own anchor's custody would be certifying itself.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RootProvenance {
    /// The root private key was generated and is held OUTSIDE this build/deployment kit. It supports
    /// a production claim, and since the Owner's decision #78 (2026-08-09: no person holds a key)
    /// nothing can earn it: the Linux readers accept `external` only for the one root compiled into
    /// `broker/src/tcb.rs`, whose private half nobody holds.
    External,
    /// The root keypair was generated by the privileged INSTALL step on this machine, which signed
    /// the key manifest, wrote the public half into the TCB anchor file and destroyed the private
    /// half before it exited (`docs/design/DEBIAN_INSTALL_PROVISIONING.md` section 5).
    ///
    /// Two things have to be true before this word means anything, and neither is established by
    /// the word itself:
    ///
    ///  * the anchor that says it must have been read from the path the section 2.5 pin manifest
    ///    pins for `key-manifest.root-anchor`, after that floor passed. The label is earned by
    ///    WHERE the file sits and WHO can write it, never by what the file says;
    ///  * [`INSTALL_MINTED_CUSTODY_ACCEPTED`] must be `true`. It ships `false`.
    InstallMinted,
    /// The root keypair was generated by the same provisioning kit that signed the manifest — a real,
    /// complete chain run, but the signer and the verifier are the same party.
    KitGenerated,
    /// A compiled-in fixture anchor whose private half ships in the source tree, used to exercise the
    /// chain. Anyone with the binary can mint a manifest under it.
    Demonstration,
}

impl RootProvenance {
    /// Parse the provisioner's declared provenance. Fail-closed: an unknown, misspelled or absent value
    /// is `None`, never silently treated as [`RootProvenance::External`].
    pub fn parse(s: &str) -> Option<RootProvenance> {
        match s {
            "external" => Some(RootProvenance::External),
            "install_minted" => Some(RootProvenance::InstallMinted),
            "kit_generated" => Some(RootProvenance::KitGenerated),
            "demonstration" => Some(RootProvenance::Demonstration),
            _ => None,
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            RootProvenance::External => "external",
            RootProvenance::InstallMinted => "install_minted",
            RootProvenance::KitGenerated => "kit_generated",
            RootProvenance::Demonstration => "demonstration",
        }
    }

    /// True for [`RootProvenance::External`], and for [`RootProvenance::InstallMinted`] ONLY while
    /// [`INSTALL_MINTED_CUSTODY_ACCEPTED`] is `true` -- which it is not. Everything else can exercise
    /// the chain honestly but can never render a PRODUCTION verdict.
    pub fn supports_production_claim(&self) -> bool {
        self.supports_production_claim_when(INSTALL_MINTED_CUSTODY_ACCEPTED)
    }

    /// The rule itself, with the Owner's line as an ARGUMENT.
    ///
    /// It exists so both values of the rule can be tested without anybody editing
    /// [`INSTALL_MINTED_CUSTODY_ACCEPTED`] to do it: a constant that has to be flipped to be tested
    /// is a constant that gets flipped. `pub(crate)` and not `pub`: outside this crate the only
    /// entry is [`RootProvenance::supports_production_claim`], which reads the shipped constant, so
    /// no other crate can ask the question with a `true` it supplied itself.
    pub(crate) fn supports_production_claim_when(&self, install_minted_custody_accepted: bool) -> bool {
        match self {
            RootProvenance::External => true,
            RootProvenance::InstallMinted => install_minted_custody_accepted,
            RootProvenance::KitGenerated | RootProvenance::Demonstration => false,
        }
    }
}

/// **The Owner's line.** Whether an install-minted root may support a PRODUCTION trust claim.
///
/// It ships `false`, and while it is `false` an install-minted root resolves to
/// `TrustState::DemonstrationCustody { root_provenance: InstallMinted, .. }`: the whole chain runs
/// and binds, a row commits as `demonstration_custody`, and nothing renders
/// `production_verified=true`.
///
/// Flipping it is one line, and it is NOT the Builder's line. It is the Owner's, after the
/// independent audit -- the same rule CLAUDE.md section 6 states for the production gate as a whole.
/// A Builder, human or AI, must never change this value: not to make a test pass (the rule is
/// testable both ways through `RootProvenance::supports_production_claim_when` and
/// `production_trust::resolve_trust_state_when`, with the value injected), not because CI is green,
/// and not because the change "is obviously ready". `the_install_minted_gate_ships_closed` in this
/// file's tests and its twin in `production_trust` fail the moment it is `true`, so the flip cannot
/// land unnoticed.
pub const INSTALL_MINTED_CUSTODY_ACCEPTED: bool = false;

/// A pinned root anchor together with the custody provenance the provisioner declared for it. This — not
/// a bare [`PinnedRoot`] — is what the production trust path verifies against.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RootAnchor {
    pub pinned: PinnedRoot,
    pub provenance: RootProvenance,
}

/// Evidence that ONE specific manifest's root signature verified under ONE specific anchor, carrying
/// that anchor's identity and provenance.
///
/// Every field is private and there is no public constructor: the ONLY way to obtain this value is
/// [`verify_manifest_anchored`] returning `Ok`. That is what makes it different from passing a
/// provenance string alongside a manifest — a caller cannot assemble a token that says `External`
/// without an anchor that actually said so having actually verified the signature.
///
/// LIMIT, stated plainly: this proves which anchor verified the manifest and what that anchor's
/// provisioner CLAIMED about its custody. It cannot prove the claim is true. A provisioner that writes
/// `external` or `install_minted` over a key it generated itself is lying, and no code HERE can
/// detect that. What makes the claim worth anything is where the anchor was read from: the reader
/// must have taken it from the path the §2.5 pin manifest pins, after that floor passed
/// (`broker/src/tcb_probe.rs::VerifiedBrokerTcb`, `broker/src/tcb.rs::parse_root_anchor`), and
/// `external` additionally has to be the one compiled-in root.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VerifiedManifestRoot {
    root_key_id: String,
    provenance: RootProvenance,
    /// Binds the token to the exact manifest bytes it was issued for, so a token obtained for an
    /// externally-anchored manifest cannot be presented alongside a different one.
    manifest_content_hash: String,
}

impl VerifiedManifestRoot {
    pub fn root_key_id(&self) -> &str {
        &self.root_key_id
    }
    pub fn provenance(&self) -> RootProvenance {
        self.provenance
    }
    pub fn manifest_content_hash(&self) -> &str {
        &self.manifest_content_hash
    }
    /// True iff this token was issued for exactly `manifest`.
    pub fn covers(&self, manifest: &KeyManifest) -> bool {
        self.manifest_content_hash == manifest.content_hash()
    }
}

/// Verify the manifest against a pinned root anchor and, on success, return the [`VerifiedManifestRoot`]
/// naming the anchor that did the verifying. This is the entry point the production trust path requires;
/// [`verify_manifest`] answers only the arithmetic question and cannot say WHICH root was satisfied.
pub fn verify_manifest_anchored(
    manifest: &KeyManifest,
    root_sig_b64: &str,
    anchor: &RootAnchor,
) -> Result<VerifiedManifestRoot, ManifestError> {
    verify_manifest(manifest, root_sig_b64, &anchor.pinned)?;
    Ok(VerifiedManifestRoot {
        root_key_id: anchor.pinned.root_key_id.clone(),
        provenance: anchor.provenance,
        manifest_content_hash: manifest.content_hash(),
    })
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
///
/// This answers ONLY "did the signature verify under this key". It deliberately returns no evidence of
/// WHICH anchor was satisfied, which is why a caller rendering a production verdict must use
/// [`verify_manifest_anchored`] instead: a demonstration root verifies its own manifest just as well as
/// an operator's offline root, and a bare `Ok(())` cannot tell the two apart.
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
///
/// **This function alone is not the anti-rollback control.** It is a comparison; the control is the
/// comparison PLUS a floor that (a) outlives the process and (b) is not derived from the very manifest
/// being checked. The audit found three of four call sites failing one of those: two advanced a floor
/// that was only ever held in memory, and one built the floor from `manifest.content_hash()` seconds
/// before comparing it against the same manifest — a predicate that cannot fail. Prefer
/// [`check_and_persist`], which cannot be called without somewhere durable to put the result.
#[must_use = "the advanced floor MUST be persisted, or the anti-rollback control is in-memory only"]
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

/// Why a durable anti-rollback advance refused. Every variant is a REFUSAL — there is deliberately no
/// "could not persist, carried on anyway" outcome, because that is precisely the state the audit found:
/// a floor that advanced in memory and reset to the provisioned constant on the next process start.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FloorPersistError {
    /// The manifest is a rollback or a same-epoch fork.
    Rollback(RollbackError),
    /// The advanced floor could not be written durably. The turn is refused: a floor that did not
    /// survive is not a floor.
    NotPersisted(String),
}

impl std::fmt::Display for FloorPersistError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            FloorPersistError::Rollback(e) => write!(f, "anti_rollback: {e:?}"),
            FloorPersistError::NotPersisted(why) => {
                write!(f, "anti_rollback_floor_not_persisted: {why}")
            }
        }
    }
}

/// The on-disk `{highest_epoch, highest_hash}` form both Linux drivers read and write.
pub fn floor_json_bytes(floor: &AntiRollbackFloor) -> Vec<u8> {
    serde_json::to_vec(&serde_json::json!({
        "highest_epoch": floor.highest_epoch,
        "highest_hash": floor.highest_hash,
    }))
    .expect("floor serializes")
}

/// Parse the on-disk floor form. `None` for absent/malformed — a caller MUST treat that as a refusal
/// and never as "no floor required" (audit R-06: an absent floor that reads as absent is not a floor).
pub fn parse_floor_json(bytes: &[u8]) -> Option<AntiRollbackFloor> {
    let v: serde_json::Value = serde_json::from_slice(bytes).ok()?;
    Some(AntiRollbackFloor {
        highest_epoch: v.get("highest_epoch")?.as_u64()?,
        highest_hash: v.get("highest_hash")?.as_str()?.to_string(),
    })
}

/// Anti-rollback CAS **plus the durable advance**, as one operation that cannot be half-done.
///
/// The audited defect was not that [`check_and_advance`] was wrong — it is right — but that its result
/// was dropped. Two of the four call sites advanced an in-memory floor and never wrote it back, so a
/// restart reset the floor to whatever the provisioner had written and the "highest accepted epoch"
/// never actually rose. This function writes the advanced floor through a temp file + rename, and a
/// write failure REFUSES the turn rather than proceeding on an unadvanced floor.
///
/// Custody is NOT solved here and this doc does not pretend otherwise: whoever can write `path` can
/// write a lower floor. What this establishes is that the floor the next process reads is the one this
/// process accepted, which is the precondition for any custody control to mean anything.
pub fn check_and_persist(
    floor: &AntiRollbackFloor,
    manifest: &KeyManifest,
    path: &std::path::Path,
) -> Result<AntiRollbackFloor, FloorPersistError> {
    let advanced = check_and_advance(floor, manifest).map_err(FloorPersistError::Rollback)?;
    write_floor_atomically(path, &floor_json_bytes(&advanced))?;
    Ok(advanced)
}

/// Temp-file + fsync + rename, so a crash mid-write cannot leave a truncated floor that reads as
/// absent, and a crash just AFTER cannot leave a rename that names bytes still in the page cache.
///
/// This used to be `fs::write` then `fs::rename` with no sync at all, under a doc that claimed crash
/// safety. A rename is atomic with respect to other processes; it says nothing about power loss.
/// Without the file sync the new name can survive a crash pointing at an empty or partial file —
/// exactly the "floor that reads as absent" this function exists to rule out. The directory sync
/// makes the rename itself durable; it is attempted wherever a directory can be opened and its
/// failure is a refusal, like every other failure here.
pub fn write_floor_atomically(path: &std::path::Path, bytes: &[u8]) -> Result<(), FloorPersistError> {
    use std::io::Write as _;
    let tmp = path.with_extension("json.tmp");
    let refused = |what: &str, at: &std::path::Path, e: std::io::Error| {
        FloorPersistError::NotPersisted(format!("{what} {}: {e}", at.display()))
    };
    let mut file = std::fs::File::create(&tmp).map_err(|e| refused("write", &tmp, e))?;
    file.write_all(bytes).map_err(|e| refused("write", &tmp, e))?;
    file.sync_all().map_err(|e| refused("sync", &tmp, e))?;
    drop(file);
    std::fs::rename(&tmp, path).map_err(|e| refused("rename", path, e))?;
    #[cfg(unix)]
    {
        let dir = match path.parent() {
            Some(p) if !p.as_os_str().is_empty() => p,
            _ => std::path::Path::new("."),
        };
        std::fs::File::open(dir)
            .and_then(|d| d.sync_all())
            .map_err(|e| refused("sync directory", dir, e))?;
    }
    Ok(())
}

// --- tiny hex/base64 helpers (no extra deps; base64 crate is present but keep this module self-checking) -

/// Decode exactly 64 hex characters into 32 bytes; `None` for any other length or any non-hex
/// character. THE one decoder: `manifest_authority`, the broker's resolver, the Windows kit and the
/// two Linux proof drivers each carried a byte-for-byte copy of this body, and all of them now call
/// this.
pub fn decode_hex32(s: &str) -> Option<[u8; 32]> {
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

    fn anchor(root: &SigningKey, provenance: RootProvenance) -> RootAnchor {
        RootAnchor {
            pinned: PinnedRoot { root_key_id: "root-1".into(), public_key_hex: pubhex(root) },
            provenance,
        }
    }

    #[test]
    fn an_anchored_verify_reports_the_anchor_that_verified_and_binds_the_manifest() {
        let root = signing_key(1);
        let prod = signing_key(2);
        let m = manifest(5, &prod);
        let sig = sign_b64(&root, &m.canonical_bytes());

        // The token names the anchor's OWN provenance — nothing in the manifest can influence it.
        let ext = verify_manifest_anchored(&m, &sig, &anchor(&root, RootProvenance::External)).unwrap();
        assert_eq!(ext.provenance(), RootProvenance::External);
        assert_eq!(ext.root_key_id(), "root-1");
        assert!(ext.covers(&m));

        // The SAME manifest and the SAME signature under a demonstration anchor yields a token that says
        // demonstration. If the token took its provenance from anywhere but the anchor, these two would
        // agree.
        let demo = verify_manifest_anchored(&m, &sig, &anchor(&root, RootProvenance::Demonstration)).unwrap();
        assert_eq!(demo.provenance(), RootProvenance::Demonstration);
        assert!(!demo.provenance().supports_production_claim());

        // The token does NOT cover a different manifest, so it cannot be carried across.
        let other = manifest(6, &prod);
        assert!(!ext.covers(&other));
    }

    #[test]
    fn no_token_is_issued_when_the_root_signature_does_not_verify() {
        // The token is the only route to a production verdict, so failing to issue it on a bad signature
        // IS the fail-closed behaviour. A wrong signer and an unknown root id both refuse.
        let root = signing_key(1);
        let prod = signing_key(2);
        let m = manifest(5, &prod);
        let a = anchor(&root, RootProvenance::External);
        let badsig = sign_b64(&signing_key(9), &m.canonical_bytes());
        assert_eq!(
            verify_manifest_anchored(&m, &badsig, &a),
            Err(ManifestError::RootSignatureInvalid)
        );
        let m2 = KeyManifest { root_key_id: "root-2".into(), ..m.clone() };
        let sig2 = sign_b64(&root, &m2.canonical_bytes());
        assert_eq!(verify_manifest_anchored(&m2, &sig2, &a), Err(ManifestError::UnknownRoot));
    }

    #[test]
    fn provenance_parsing_is_fail_closed() {
        assert_eq!(RootProvenance::parse("external"), Some(RootProvenance::External));
        assert_eq!(RootProvenance::parse("kit_generated"), Some(RootProvenance::KitGenerated));
        assert_eq!(RootProvenance::parse("demonstration"), Some(RootProvenance::Demonstration));
        // Anything else — empty, absent, misspelled, or a near-miss — is refused, never upgraded.
        for bad in ["", "External", "EXTERNAL", " external", "external ", "offline", "prod", "true"] {
            assert_eq!(RootProvenance::parse(bad), None, "{bad:?} must not parse");
        }
        assert!(RootProvenance::External.supports_production_claim());
        assert!(!RootProvenance::KitGenerated.supports_production_claim());
        assert!(!RootProvenance::Demonstration.supports_production_claim());
    }

    #[test]
    fn install_minted_parses_and_round_trips_and_near_misses_do_not() {
        assert_eq!(RootProvenance::parse("install_minted"), Some(RootProvenance::InstallMinted));
        assert_eq!(RootProvenance::InstallMinted.as_str(), "install_minted");
        // `as_str` and `parse` are one vocabulary: every variant survives the round trip, so a
        // provenance this build can WRITE into evidence is one it reads back as the same thing.
        for p in [
            RootProvenance::External,
            RootProvenance::InstallMinted,
            RootProvenance::KitGenerated,
            RootProvenance::Demonstration,
        ] {
            assert_eq!(RootProvenance::parse(p.as_str()), Some(p));
        }
        // And serde agrees with both, so a typed document cannot carry a third spelling.
        assert_eq!(
            serde_json::to_string(&RootProvenance::InstallMinted).unwrap(),
            r#""install_minted""#
        );
        for bad in
            ["install-minted", "installminted", "Install_Minted", "install_minted ", "minted", "installed"]
        {
            assert_eq!(RootProvenance::parse(bad), None, "{bad:?} must not parse");
        }
    }

    /// The rule, both ways, with the Owner's line INJECTED -- nobody edits the constant to run this.
    #[test]
    fn install_minted_supports_a_production_claim_only_when_the_owners_line_says_so() {
        // Closed (what ships): install-minted is NOT production.
        assert!(!RootProvenance::InstallMinted.supports_production_claim_when(false));
        // Open (the Owner's future flip): it is.
        assert!(RootProvenance::InstallMinted.supports_production_claim_when(true));
        // The line moves install-minted and NOTHING else: a kit-generated or demonstration root is
        // not production under either value, and external does not depend on it.
        for accepted in [false, true] {
            assert!(RootProvenance::External.supports_production_claim_when(accepted));
            assert!(!RootProvenance::KitGenerated.supports_production_claim_when(accepted));
            assert!(!RootProvenance::Demonstration.supports_production_claim_when(accepted));
        }
    }

    /// The tripwire. The public entry reads the SHIPPED constant, and the shipped constant is closed.
    /// If this fails, somebody flipped the Owner's line: see [`INSTALL_MINTED_CUSTODY_ACCEPTED`].
    #[test]
    fn the_install_minted_gate_ships_closed() {
        // Read through a binding so the assertion is on the VALUE; `assert!(!CONST)` on a literal
        // constant is something a lint may one day fold away.
        let shipped = INSTALL_MINTED_CUSTODY_ACCEPTED;
        assert!(!shipped, "the Owner's line was flipped");
        assert!(!RootProvenance::InstallMinted.supports_production_claim());
        // The public entry IS the rule at the shipped value, for every variant -- so it cannot have
        // been re-pointed at a literal while the constant stayed put.
        for p in [
            RootProvenance::External,
            RootProvenance::InstallMinted,
            RootProvenance::KitGenerated,
            RootProvenance::Demonstration,
        ] {
            assert_eq!(p.supports_production_claim(), p.supports_production_claim_when(shipped));
        }
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
    fn nm_man_01_anti_rollback_accepts_higher_refuses_lower_and_same_epoch_fork() {
        // NM-MAN-01 — a manifest whose epoch is below the anti-rollback floor is refused as EpochBelowFloor (rollback).
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

    #[test]
    fn nm_man_02_same_epoch_different_hash_is_refused() {
        // NM-MAN-02 — a manifest at the floor's epoch whose content hash differs is refused as SameEpochDifferentHash (fork).
        let prod = signing_key(2);
        let floor = AntiRollbackFloor { highest_epoch: 5, highest_hash: manifest(5, &prod).content_hash() };
        let mut m5b = manifest(5, &prod); m5b.keys[0].key_epoch = 8; // changes content hash
        assert_eq!(check_and_advance(&floor, &m5b), Err(RollbackError::SameEpochDifferentHash));
    }

    // ---- the durable half: an advance nobody wrote down is not an advance ----

    #[test]
    fn a_persisted_advance_is_what_the_next_process_reads() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("floor.json");
        let prod = signing_key(2);
        let m5 = manifest(5, &prod);
        std::fs::write(&path, floor_json_bytes(&AntiRollbackFloor { highest_epoch: 5, highest_hash: m5.content_hash() })).unwrap();

        // --- process 1: accept epoch 6 ---
        let floor = parse_floor_json(&std::fs::read(&path).unwrap()).expect("provisioned floor parses");
        let m6 = manifest(6, &prod);
        let advanced = check_and_persist(&floor, &m6, &path).expect("a higher epoch is accepted");
        assert_eq!(advanced.highest_epoch, 6);

        // --- process 2: the SAME rolled-back manifest that process 1 superseded ---
        // This is the whole point. With the advance held only in memory, process 2 re-read epoch 5 from
        // disk and accepted epoch 5 (and every lower-but-genuinely-signed manifest above it) forever.
        let reread = parse_floor_json(&std::fs::read(&path).unwrap()).expect("floor survived");
        assert_eq!(reread.highest_epoch, 6, "the advance must have been written down");
        assert_eq!(
            check_and_persist(&reread, &m5, &path),
            Err(FloorPersistError::Rollback(RollbackError::EpochBelowFloor)),
            "a manifest below the floor a PREVIOUS process accepted must be refused"
        );
    }

    #[test]
    fn a_floor_that_cannot_be_written_refuses_the_turn() {
        let dir = tempfile::tempdir().unwrap();
        // The parent directory does not exist, so the TEMP FILE cannot be created. This is the
        // WRITE branch, and only that: the comment here used to describe a rename failing, which
        // this fixture never reaches. The rename branch has its own test below.
        let path = dir.path().join("nonexistent-subdir").join("floor.json");
        let prod = signing_key(2);
        let m5 = manifest(5, &prod);
        let floor = AntiRollbackFloor { highest_epoch: 1, highest_hash: "x".into() };
        match check_and_persist(&floor, &m5, &path) {
            Err(FloorPersistError::NotPersisted(why)) => assert!(why.starts_with("write "), "{why}"),
            other => panic!("an unwritable floor must refuse, got {other:?}"),
        }
    }

    /// The RENAME branch: the temp file is written and synced, and the final step fails because
    /// the floor path is a non-empty directory. The turn is refused, and nothing has replaced the
    /// path — a refusal that left a half-installed floor would be worse than the failure.
    #[test]
    fn a_floor_whose_rename_fails_refuses_the_turn_and_replaces_nothing() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("floor.json");
        std::fs::create_dir(&path).unwrap();
        std::fs::write(path.join("occupant"), b"x").unwrap();
        let prod = signing_key(2);
        let m5 = manifest(5, &prod);
        let floor = AntiRollbackFloor { highest_epoch: 1, highest_hash: "x".into() };
        match check_and_persist(&floor, &m5, &path) {
            Err(FloorPersistError::NotPersisted(why)) => assert!(why.starts_with("rename "), "{why}"),
            other => panic!("a floor that cannot be renamed into place must refuse, got {other:?}"),
        }
        assert!(path.is_dir() && path.join("occupant").is_file(), "the path was not replaced");
    }

    /// The durable write, read back: what a NEW process would parse is the advanced floor, the
    /// temp file is gone, and a second write over an existing floor replaces it whole.
    #[test]
    fn a_written_floor_is_complete_and_leaves_no_temp_file() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("floor.json");
        let first = AntiRollbackFloor { highest_epoch: 5, highest_hash: "a".repeat(64) };
        write_floor_atomically(&path, &floor_json_bytes(&first)).unwrap();
        assert_eq!(parse_floor_json(&std::fs::read(&path).unwrap()), Some(first));
        let second = AntiRollbackFloor { highest_epoch: 6, highest_hash: "b".repeat(64) };
        write_floor_atomically(&path, &floor_json_bytes(&second)).unwrap();
        assert_eq!(parse_floor_json(&std::fs::read(&path).unwrap()), Some(second));
        assert!(!path.with_extension("json.tmp").exists(), "the temp file was renamed, not copied");
    }

    /// The bytes the root signs, held to a literal. `canonical_bytes` is `serde_json::to_vec` over
    /// the struct, so the signed form is the DECLARATION ORDER of `KeyManifest` and `ManifestKey`
    /// — not sorted keys, whatever the doc used to say. Reordering a field, renaming one, or
    /// changing an enum's spelling changes these bytes and with them every root signature and
    /// every anti-rollback hash; this is where that shows up, instead of at a deployment whose
    /// manifest stopped verifying.
    #[test]
    fn canonical_bytes_are_pinned_to_declaration_order() {
        let m = KeyManifest {
            manifest_epoch: 7,
            root_key_id: "root-1".into(),
            keys: vec![ManifestKey {
                key_id: "prod-1".into(),
                public_key_hex: "ab".repeat(32),
                trust_class: TrustClass::Production,
                valid_from_ms: 1,
                valid_to_ms: 2,
                key_epoch: 3,
                revoked: false,
                allowed_protocols: vec!["p.v1".into()],
            }],
        };
        let expected = format!(
            concat!(
                r#"{{"manifest_epoch":7,"root_key_id":"root-1","keys":[{{"key_id":"prod-1","#,
                r#""public_key_hex":"{}","trust_class":"production","valid_from_ms":1,"#,
                r#""valid_to_ms":2,"key_epoch":3,"revoked":false,"allowed_protocols":["p.v1"]}}]}}"#
            ),
            "ab".repeat(32)
        );
        assert_eq!(String::from_utf8(m.canonical_bytes()).unwrap(), expected);
        // Declaration order is NOT sorted order — the claim the doc used to make.
        let text = String::from_utf8(m.canonical_bytes()).unwrap();
        assert!(text.find("\"manifest_epoch\"").unwrap() < text.find("\"keys\"").unwrap());
        assert!(text.find("\"root_key_id\"").unwrap() < text.find("\"keys\"").unwrap());
    }

    /// NM-SCOPE-04 -- protocol out-of-scope, on the function the broker's resolver calls.
    ///
    /// `allowed_protocols` is the audience a key may sign for, and `resolve_production_key` is
    /// where a protocol outside it is refused: `broker/src/manifest_resolver.rs` resolves both of
    /// a turn's keys through this function with `RECEIPT_ENVELOPE_ARTIFACT_TYPE`. The row used to
    /// be bound to a test of `ManifestReceiptKeyAuthority`, a type nothing constructs outside its
    /// own tests.
    ///
    /// The fixture is built around what the scoped key HAS. It is Production, unrevoked and inside
    /// its validity window — every property a key needs except that this protocol is not one it
    /// may sign for. A key that was also revoked or expired would leave the protocol check
    /// untested, since any of those refuses on its own.
    #[test]
    fn nm_scope_04_a_key_out_of_protocol_scope_does_not_resolve_with_everything_else_right() {
        const PROTO: &str = "brops.governed-receipt-envelope.v1";
        let prod = signing_key(2);
        let mut m = manifest(5, &prod);
        let mut scoped = m.keys[0].clone();
        scoped.key_id = "scoped-1".into();
        scoped.allowed_protocols = vec!["brops.other.v1".into()];
        m.keys.push(scoped);

        assert_eq!(
            resolve_production_key(&m, "scoped-1", PROTO, 5000),
            Err(ManifestError::ProtocolNotAllowed),
            "NM-SCOPE-04: a key whose allowed_protocols exclude {PROTO} must not resolve for it"
        );
        // The same key DOES resolve for the protocol it is scoped to: it is refused for the
        // audience, not for anything else about it.
        assert!(resolve_production_key(&m, "scoped-1", "brops.other.v1", 5000).is_ok());
        // The positive control, in the same manifest: without it this would pass against a
        // manifest that had stopped resolving anything at all.
        assert!(resolve_production_key(&m, "prod-1", PROTO, 5000).is_ok());
        // An EMPTY audience admits nothing, and a prefix is not a match.
        m.keys[1].allowed_protocols.clear();
        assert_eq!(
            resolve_production_key(&m, "scoped-1", PROTO, 5000),
            Err(ManifestError::ProtocolNotAllowed)
        );
        m.keys[1].allowed_protocols = vec!["brops.governed-receipt-envelope".into()];
        assert_eq!(
            resolve_production_key(&m, "scoped-1", PROTO, 5000),
            Err(ManifestError::ProtocolNotAllowed)
        );
    }

    #[test]
    fn an_absent_or_malformed_floor_does_not_parse_as_absent() {
        assert!(parse_floor_json(b"").is_none());
        assert!(parse_floor_json(b"{}").is_none());
        assert!(parse_floor_json(br#"{"highest_epoch":5}"#).is_none());
        assert!(parse_floor_json(br#"{"highest_hash":"a"}"#).is_none());
        assert!(parse_floor_json(br#"{"highest_epoch":"5","highest_hash":"a"}"#).is_none());
        // ...and a well-formed one round-trips.
        let f = AntiRollbackFloor { highest_epoch: 7, highest_hash: "abc".into() };
        assert_eq!(parse_floor_json(&floor_json_bytes(&f)), Some(f));
    }
    #[test]
    fn nm_man_12_a_key_cannot_infer_or_invent_its_trust_class() {
        // NM-MAN-12 -- trust-class inference attempt. `trust_class` decides whether a key may render
        // production `trusted_verified`, so a key that omits it must not be read as anything, and a key
        // that invents a class must not be read as the nearest one. Both are serde properties of a
        // closed shape rather than runtime checks: the field is required (no Option, no
        // #[serde(default)]) and the enum is closed (no #[serde(other)]).
        //
        // Both limbs are asserted because "required" and "closed" can be lost independently.
        let without = r#"{"manifest_epoch":2,"root_key_id":"root-1","keys":[{
            "key_id":"k","public_key_hex":"00","valid_from_ms":1,"valid_to_ms":9,
            "key_epoch":1,"revoked":false,
            "allowed_protocols":["brops.governed-receipt-envelope.v1"]}]}"#;
        let err = serde_json::from_str::<KeyManifest>(without)
            .expect_err("NM-MAN-12: a key with no trust_class must not parse")
            .to_string();
        assert!(
            err.contains("missing field `trust_class`"),
            "NM-MAN-12: expected a missing-field error, got: {err}"
        );

        let invented = r#"{"manifest_epoch":2,"root_key_id":"root-1","keys":[{
            "key_id":"k","public_key_hex":"00","trust_class":"staging",
            "valid_from_ms":1,"valid_to_ms":9,"key_epoch":1,"revoked":false,
            "allowed_protocols":["brops.governed-receipt-envelope.v1"]}]}"#;
        let err = serde_json::from_str::<KeyManifest>(invented)
            .expect_err("NM-MAN-12: an invented trust_class must not parse")
            .to_string();
        assert!(
            err.contains("unknown variant"),
            "NM-MAN-12: expected an unknown-variant error, got: {err}"
        );

        // The positive control: the two accepted classes do parse, so the limbs above are not passing
        // because nothing parses.
        for class in ["production", "development"] {
            let ok = format!(
                r#"{{"manifest_epoch":2,"root_key_id":"root-1","keys":[{{
                "key_id":"k","public_key_hex":"00","trust_class":"{class}",
                "valid_from_ms":1,"valid_to_ms":9,"key_epoch":1,"revoked":false,
                "allowed_protocols":["brops.governed-receipt-envelope.v1"]}}]}}"#
            );
            serde_json::from_str::<KeyManifest>(&ok)
                .unwrap_or_else(|e| panic!("NM-MAN-12: {class} must parse, got {e}"));
        }
    }

}
