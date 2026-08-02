//! Production `TurnResolver` — the manifest gate wired INTO the chain's resolution (audit fix P1-b + P2).
//!
//! On every turn, BEFORE any hop, this resolver:
//!   1. verifies the operator-provisioned key manifest against the **TCB-pinned root** ([`crate::tcb`]),
//!      never a config-supplied root;
//!   2. runs anti-rollback (`check_and_advance`) AND **persists the advanced floor atomically** (fix P2);
//!   3. resolves the production receipt-signer key + the supervisor-attestation key from the verified
//!      manifest, and returns the `ResolvedTurn` whose pinned keys `verify_and_accept` then verifies under.
//!
//! Fail-closed: any manifest-signature / anti-rollback / key-resolution failure returns a closed
//! `TurnReason`, so the turn Blocks. This replaces the driver's inline "verify beside acceptance" side-call,
//! so the production verdict is ENFORCED by the same resolution the chain binds to.

use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

use brops_broker::chain_executor::{ResolvedTurn, TurnResolver};
use brops_core::governed_turn_ipc::{TurnReason, ValidatedRequest};
use brops_core::governed_verification::RECEIPT_ENVELOPE_ARTIFACT_TYPE;
use brops_core::key_manifest::{
    check_and_advance, resolve_production_key, verify_manifest, AntiRollbackFloor, KeyManifest, PinnedRoot,
};

use crate::{crypto, tcb};

/// The broker-owned per-turn facts the resolver pairs with the manifest-resolved keys.
#[derive(Clone)]
pub struct ResolvedFacts {
    pub workspace_id: String,
    pub install_id: String,
    pub system_sha256: String,
    pub history_sha256: String,
    pub generation_config_sha256: String,
    pub requested_at: String,
    pub run_id: String,
    pub task_id: String,
    pub requested_at_ms: i64,
    pub author: String,
}

pub struct ManifestResolver {
    manifest: KeyManifest,
    root_sig_b64: String,
    floor_path: PathBuf,
    floor: Mutex<AntiRollbackFloor>,
    signer_key_id: String,
    sup_attest_key_id: String,
    facts: ResolvedFacts,
}

impl ManifestResolver {
    pub fn new(
        manifest: KeyManifest,
        root_sig_b64: String,
        floor: AntiRollbackFloor,
        floor_path: PathBuf,
        signer_key_id: String,
        sup_attest_key_id: String,
        facts: ResolvedFacts,
    ) -> Self {
        ManifestResolver {
            manifest,
            root_sig_b64,
            floor_path,
            floor: Mutex::new(floor),
            signer_key_id,
            sup_attest_key_id,
            facts,
        }
    }

    /// The manifest-resolved production signer public key hex (what the envelope is verified under). Exposed
    /// so the driver classifies the trust state with the SAME key the resolver bound — not a config value.
    pub fn signer_public_key_hex(&self, now_ms: i64) -> Option<String> {
        resolve_production_key(&self.manifest, &self.signer_key_id, RECEIPT_ENVELOPE_ARTIFACT_TYPE, now_ms)
            .ok()
            .map(|k| k.public_key_hex)
    }

    pub fn manifest(&self) -> &KeyManifest {
        &self.manifest
    }
    pub fn signer_key_id(&self) -> &str {
        &self.signer_key_id
    }
}

fn now_ms() -> i64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_millis() as i64).unwrap_or(0)
}

/// The canonical floor body bytes (what gets signed + verified). Stable serialization.
pub fn floor_body(floor: &AntiRollbackFloor) -> Vec<u8> {
    serde_json::to_vec(&serde_json::json!({
        "highest_epoch": floor.highest_epoch,
        "highest_hash": floor.highest_hash,
    }))
    .expect("floor serializes")
}

/// The self-contained signed floor file: the `{highest_epoch, highest_hash}` body PLUS a TCB signature over
/// exactly that body, in ONE JSON object. A single file → a single atomic rename on write (audit D: no
/// json/sig split that a crash could desync), and the reset/tamper defense of R1 (a config-dir adversary
/// cannot forge `sig` without the TCB floor key).
pub fn signed_floor_file(floor: &AntiRollbackFloor) -> Vec<u8> {
    let sig = crypto::sign_b64url(&tcb::floor_signing_key(), &floor_body(floor));
    serde_json::to_vec(&serde_json::json!({
        "highest_epoch": floor.highest_epoch,
        "highest_hash": floor.highest_hash,
        "sig": sig,
    }))
    .expect("signed floor serializes")
}

/// Atomically persist the advanced anti-rollback floor as ONE self-contained TCB-signed file (fix P2 + R1 +
/// D). A persist failure fails the turn closed.
fn persist_floor(path: &PathBuf, floor: &AntiRollbackFloor) -> Result<(), ()> {
    let tmp = path.with_extension("json.tmp");
    std::fs::write(&tmp, signed_floor_file(floor)).map_err(|_| ())?;
    std::fs::rename(&tmp, path).map_err(|_| ())
}

/// Verify an ed25519 signature (hex pubkey, base64url-nopad sig) over `msg`, `verify_strict` (rejects
/// non-canonical S + small-order keys), matching the rest of the chain.
fn verify_ed25519_hex(public_key_hex: &str, msg: &[u8], sig_b64url: &str) -> bool {
    use base64::engine::general_purpose::URL_SAFE_NO_PAD;
    use base64::Engine as _;
    use ed25519_dalek::{Signature, VerifyingKey};
    let pk = match crypto::hex32(public_key_hex) {
        Some(b) => b,
        None => return false,
    };
    let vk = match VerifyingKey::from_bytes(&pk) {
        Ok(v) => v,
        Err(_) => return false,
    };
    let sig_bytes = match URL_SAFE_NO_PAD.decode(sig_b64url.as_bytes()) {
        Ok(b) => b,
        Err(_) => return false,
    };
    match Signature::from_slice(&sig_bytes) {
        Ok(s) => vk.verify_strict(msg, &s).is_ok(),
        Err(_) => false,
    }
}

/// Load the anti-rollback floor from the self-contained signed `floor.json` and verify its TCB integrity tag
/// (audit R1 + D). Refuses (Err) if `sig` is missing or does not verify under the TCB floor key over the
/// exact `{highest_epoch, highest_hash}` body — i.e. a reset/tampered floor is REJECTED (fail-closed).
pub fn load_verified_floor(floor_path: &Path) -> Result<AntiRollbackFloor, String> {
    let raw = std::fs::read(floor_path).map_err(|e| format!("floor read: {e}"))?;
    let v: serde_json::Value = serde_json::from_slice(&raw).map_err(|e| format!("floor parse: {e}"))?;
    let floor = AntiRollbackFloor {
        highest_epoch: v.get("highest_epoch").and_then(|x| x.as_u64()).ok_or("floor.highest_epoch")?,
        highest_hash: v
            .get("highest_hash")
            .and_then(|x| x.as_str())
            .ok_or("floor.highest_hash")?
            .to_string(),
    };
    let sig = v.get("sig").and_then(|x| x.as_str()).ok_or("floor.sig missing")?;
    if !verify_ed25519_hex(&tcb::floor_public_key_hex(), &floor_body(&floor), sig) {
        return Err("floor_integrity: signature invalid (reset or tampered)".to_string());
    }
    Ok(floor)
}

impl TurnResolver for ManifestResolver {
    fn resolve(
        &self,
        _req: &ValidatedRequest,
        _broker_turn_id: &str,
        _request_nonce: &str,
    ) -> Result<ResolvedTurn, TurnReason> {
        let now = now_ms();
        // (1) TCB-pinned root — never from config.
        let pinned = PinnedRoot {
            root_key_id: tcb::ROOT_KEY_ID.to_string(),
            public_key_hex: tcb::root_public_key_hex(),
        };
        verify_manifest(&self.manifest, &self.root_sig_b64, &pinned)
            .map_err(|_| TurnReason::UpstreamBlocked)?;

        // (2) anti-rollback: advance + persist atomically (fix P2).
        {
            let mut floor = self.floor.lock().map_err(|_| TurnReason::UpstreamBlocked)?;
            let advanced =
                check_and_advance(&floor, &self.manifest).map_err(|_| TurnReason::UpstreamBlocked)?;
            persist_floor(&self.floor_path, &advanced).map_err(|_| TurnReason::UpstreamBlocked)?;
            *floor = advanced;
        }

        // (3) resolve BOTH production keys from the VERIFIED manifest through resolve_production_key, so the
        //     supervisor-attestation key is ALSO subject to trust_class / validity-window / revocation /
        //     allowed-protocol enforcement (audit R2 — no bare key_id lookup that bypasses revocation).
        let iso = resolve_production_key(&self.manifest, &self.signer_key_id, RECEIPT_ENVELOPE_ARTIFACT_TYPE, now)
            .map_err(|_| TurnReason::UpstreamBlocked)?;
        let sup = resolve_production_key(
            &self.manifest,
            &self.sup_attest_key_id,
            RECEIPT_ENVELOPE_ARTIFACT_TYPE,
            now,
        )
        .map_err(|_| TurnReason::UpstreamBlocked)?;
        let iso_pub = crypto::hex32(&iso.public_key_hex).ok_or(TurnReason::UpstreamBlocked)?;
        let sup_pub = crypto::hex32(&sup.public_key_hex).ok_or(TurnReason::UpstreamBlocked)?;

        let f = &self.facts;
        Ok(ResolvedTurn {
            isolated_signer_key_id: self.signer_key_id.clone(),
            isolated_signer_public_key: iso_pub,
            supervisor_attestation_key_id: self.sup_attest_key_id.clone(),
            supervisor_attestation_public_key: sup_pub,
            workspace_id: f.workspace_id.clone(),
            install_id: f.install_id.clone(),
            system_sha256: f.system_sha256.clone(),
            history_sha256: f.history_sha256.clone(),
            generation_config_sha256: f.generation_config_sha256.clone(),
            requested_at: f.requested_at.clone(),
            run_id: f.run_id.clone(),
            task_id: f.task_id.clone(),
            requested_at_ms: f.requested_at_ms,
            author: f.author.clone(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use brops_core::key_manifest::AntiRollbackFloor;

    // Audit R1: a TCB-signed floor loads; a config-dir adversary who RESETS floor.json (to replay an
    // older genuinely-root-signed manifest) cannot forge floor.sig, so load_verified_floor rejects it.
    #[test]
    fn floor_integrity_accepts_tcb_signed_and_rejects_reset() {
        let dir = std::env::temp_dir().join(format!("brops-floor-{}", brops_core::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let floor_path = dir.join("floor.json");
        // A self-contained TCB-signed floor loads with the epoch intact.
        let floor = AntiRollbackFloor { highest_epoch: 5, highest_hash: "a".repeat(64) };
        std::fs::write(&floor_path, signed_floor_file(&floor)).unwrap();
        assert_eq!(load_verified_floor(&floor_path).expect("valid floor loads").highest_epoch, 5);
        // Adversary resets the epoch to 0 (unsigned body, no valid sig) -> REJECTED (fail-closed).
        std::fs::write(&floor_path, floor_body(&AntiRollbackFloor { highest_epoch: 0, highest_hash: "a".repeat(64) })).unwrap();
        assert!(load_verified_floor(&floor_path).is_err(), "a reset floor.json must be rejected (R1)");
        // Adversary writes epoch 0 WITH a bogus sig -> REJECTED (cannot forge without the TCB floor key).
        std::fs::write(&floor_path, serde_json::to_vec(&serde_json::json!({
            "highest_epoch": 0, "highest_hash": "a".repeat(64), "sig": "bogus"
        })).unwrap()).unwrap();
        assert!(load_verified_floor(&floor_path).is_err(), "a forged-sig floor must be rejected (R1)");
        let _ = std::fs::remove_dir_all(&dir);
    }
}
