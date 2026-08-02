//! The on-disk deployment config shared by the provisioner, the three server bins, and the driver. It is the
//! Windows analogue of the Linux live kit's `config.json`: the broker's OWN side (pinned root, manifest,
//! resolved Expected facts) plus the transport (pipe names + the single allowed broker SID) plus each
//! principal's key seed path. Private key seeds live in their own files (hex-encoded), never inline here.

use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Clone)]
pub struct Config {
    /// The ONLY peer SID every server accepts (the broker principal) — the SO_PEERCRED-equivalent allowlist.
    pub allowed_broker_sid: String,
    /// The content-addressed protected store the isolated signer reads and the execution writes output into.
    pub store_dir: String,
    pub pipes: Pipes,
    /// Hex-encoded 32-byte ed25519 seed file paths (owner-locked in a cross-account deploy).
    pub keys: Keys,
    pub key_ids: KeyIds,
    pub pubs: Pubs,
    pub trust: Trust,
    pub resolved: Resolved,
    pub facts: Facts,
    pub supervisor_cfg: SupervisorCfg,
    pub identities: Identities,
    /// The executor image the driver spawns to produce the governed output.
    pub executor_path: String,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct Pipes {
    pub authority: String,
    pub supervisor: String,
    pub signer: String,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct Keys {
    pub challenge_seed: String,
    pub attest_seed: String,
    pub signer_seed: String,
    pub root_seed: String,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct KeyIds {
    pub challenge: String,
    pub sup_attest: String,
    pub signer: String,
    pub root: String,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct Pubs {
    pub challenge: String,
    pub attest: String,
    pub signer: String,
    pub root: String,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct Trust {
    pub manifest_path: String,
    pub manifest_sig_path: String,
    pub floor_path: String,
    pub root_key_id: String,
    pub root_pub_hex: String,
    pub signer_key_id: String,
    pub supervisor_attestation_key_id: String,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct Resolved {
    pub workspace_id: String,
    pub install_id: String,
    pub system_sha256: String,
    pub history_sha256: String,
    pub generation_config_sha256: String,
    pub requested_at: String,
    pub requested_at_ms: i64,
    pub run_id: String,
    pub task_id: String,
    pub author: String,
    pub conversation_id: String,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct Facts {
    pub receipt_id: String,
    pub supervisor_id: String,
    pub executor_id: String,
    pub builder_id: String,
    pub policy_id: String,
    pub policy_version: String,
    pub policy_bundle_handle: String,
    pub containment_evidence_handle: String,
    pub record_handle: String,
    pub lease_handle: String,
    pub execution_receipt_handle: String,
    pub evidence_final_event_hash: String,
    pub evidence_event_count: i64,
    pub evidence_last_sequence: i64,
    pub evidence_head_sequence: i64,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct SupervisorCfg {
    pub launcher_executable_sha256: String,
    pub executor_executable_sha256: String,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct Identities {
    pub allowed_executors: Vec<String>,
    pub allowed_builders: Vec<String>,
    pub allowed_supervisors: Vec<String>,
}

impl Config {
    pub fn load(path: &str) -> Result<Config, String> {
        let raw = std::fs::read_to_string(path).map_err(|e| format!("config read: {e}"))?;
        serde_json::from_str(&raw).map_err(|e| format!("config parse: {e}"))
    }
}

/// Load a principal's 32-byte seed. On Windows the seed is under DPAPI custody: a sealed blob is unsealed
/// with the CURRENT account's master key (so only the owning service account can recover it); a legacy
/// plaintext-hex file is parsed AND immediately re-sealed in place (trust-on-first-use), so after the first
/// server start the seed is never plaintext at rest again. On non-Windows (Linux CI / in-process proof) only
/// the hex form is used.
pub fn read_seed(path: &str) -> Result<[u8; 32], String> {
    let bytes = std::fs::read(path).map_err(|e| format!("seed read {path}: {e}"))?;

    #[cfg(windows)]
    {
        if crate::seedstore::looks_sealed(&bytes) {
            return crate::seedstore::dpapi_unseal(&bytes);
        }
        // Legacy plaintext hex on first run: parse, then seal to THIS account + atomically replace.
        let hex = String::from_utf8_lossy(&bytes);
        let seed = crate::crypto::hex32(hex.trim()).ok_or_else(|| format!("seed malformed: {path}"))?;
        if let Ok(blob) = crate::seedstore::dpapi_seal(&seed) {
            let tmp = format!("{path}.sealing");
            if std::fs::write(&tmp, &blob).is_ok() {
                let _ = std::fs::rename(&tmp, path); // same dir -> atomic replace, ACL preserved
            }
        }
        return Ok(seed);
    }

    #[cfg(not(windows))]
    {
        let hex = String::from_utf8_lossy(&bytes);
        crate::crypto::hex32(hex.trim()).ok_or_else(|| format!("seed malformed: {path}"))
    }
}
