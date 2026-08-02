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

use std::path::PathBuf;
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

/// Atomically persist the advanced anti-rollback floor (temp write + rename), so a rollback cannot be
/// replayed across restarts (fix P2). Best-effort durability: a failure fails the turn closed.
fn persist_floor(path: &PathBuf, floor: &AntiRollbackFloor) -> Result<(), ()> {
    let body = serde_json::to_vec(&serde_json::json!({
        "highest_epoch": floor.highest_epoch,
        "highest_hash": floor.highest_hash,
    }))
    .map_err(|_| ())?;
    let tmp = path.with_extension("json.tmp");
    std::fs::write(&tmp, &body).map_err(|_| ())?;
    std::fs::rename(&tmp, path).map_err(|_| ())
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

        // (3) resolve the production keys from the VERIFIED manifest.
        let iso = resolve_production_key(&self.manifest, &self.signer_key_id, RECEIPT_ENVELOPE_ARTIFACT_TYPE, now)
            .map_err(|_| TurnReason::UpstreamBlocked)?;
        let sup_hex = self
            .manifest
            .keys
            .iter()
            .find(|k| k.key_id == self.sup_attest_key_id)
            .map(|k| k.public_key_hex.clone())
            .ok_or(TurnReason::UpstreamBlocked)?;
        let iso_pub = crypto::hex32(&iso.public_key_hex).ok_or(TurnReason::UpstreamBlocked)?;
        let sup_pub = crypto::hex32(&sup_hex).ok_or(TurnReason::UpstreamBlocked)?;

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
