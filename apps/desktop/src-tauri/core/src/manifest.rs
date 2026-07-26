//! Wave 3b signed desktop key manifest and anti-rollback state.
//!
//! The manifest is operator-provisioned, root-signed and persisted atomically with
//! its epoch/hash floor. Receipt-signing and supervisor-attestation keys are kept in
//! disjoint usages so an attestation key can never authorize rendering and a receipt
//! key can never authenticate supervisor evidence.

use std::collections::{BTreeMap, BTreeSet};

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine as _;
use ed25519_dalek::{Signature, VerifyingKey};
use rusqlite::{Connection, OptionalExtension};
use serde_json::Value;

use crate::domain::{CoreError, CoreResult};
use crate::receipt::sha256_hex;
use crate::strict_json::{
    bool_value, canonical_bytes, exact_object, parse_canonical, string, u64_value,
};

pub const MANIFEST_PROTOCOL: &str = "brops.key-manifest.v1";
pub const GOVERNED_RECEIPT_PROTOCOL: &str = "brops.governed-receipt-envelope.v1";
pub const MAX_MANIFEST_BYTES: usize = 256 * 1024;

fn invalid(value: impl Into<String>) -> CoreError {
    CoreError::Invalid { field: "key_manifest", value: value.into() }
}

fn decode_fixed<const N: usize>(wire: &str, field: &str) -> Result<[u8; N], String> {
    let raw = URL_SAFE_NO_PAD.decode(wire.as_bytes())
        .map_err(|_| format!("`{field}` is not canonical base64url"))?;
    if raw.len() != N || URL_SAFE_NO_PAD.encode(&raw) != wire {
        return Err(format!("`{field}` must be canonical base64url for exactly {N} bytes"));
    }
    raw.try_into().map_err(|_| format!("`{field}` has the wrong length"))
}

#[derive(Debug, Clone, Default)]
pub struct PinnedRoots {
    keys: BTreeMap<String, [u8; 32]>,
}

impl PinnedRoots {
    pub fn new(entries: impl IntoIterator<Item = (String, [u8; 32])>) -> Result<Self, String> {
        let mut keys = BTreeMap::new();
        for (id, key) in entries {
            if id.is_empty() || id.len() > 128 || keys.insert(id.clone(), key).is_some() {
                return Err(format!("invalid or duplicate pinned root `{id}`"));
            }
        }
        Ok(Self { keys })
    }

    /// Parse a build/operator supplied JSON object `{root_key_id: public_key_b64url}`.
    pub fn from_json(bytes: &[u8]) -> Result<Self, String> {
        let value = parse_canonical(bytes, 32 * 1024)?;
        let object = value.as_object().ok_or("pinned roots must be an object")?;
        let mut entries = Vec::with_capacity(object.len());
        for (id, value) in object {
            let wire = value.as_str().ok_or("pinned root value must be a string")?;
            entries.push((id.clone(), decode_fixed::<32>(wire, "pinned_root" )?));
        }
        Self::new(entries)
    }

    fn get(&self, id: &str) -> Option<&[u8; 32]> { self.keys.get(id) }
    pub fn is_empty(&self) -> bool { self.keys.is_empty() }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ManifestTrustClass { Production, Development }

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ManifestKeyUsage { ReceiptSigning, SupervisorAttestation }

#[derive(Debug, Clone)]
pub struct ManifestKey {
    pub key_id: String,
    pub public_key: [u8; 32],
    pub key_usage: ManifestKeyUsage,
    pub supervisor_id: String,
    pub valid_from: u64,
    pub valid_to: u64,
    pub key_epoch: u64,
    pub revoked: bool,
    pub trust_class: Option<ManifestTrustClass>,
    pub allowed_protocols: Vec<String>,
    pub workspace: Option<String>,
    pub allowed_audiences: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct ManifestSnapshot {
    pub payload_bytes: Vec<u8>,
    pub root_sig: String,
    pub root_key_id: String,
    pub manifest_epoch: u64,
    pub manifest_hash: String,
    pub issued_at: u64,
    pub expires_at: u64,
    pub keys: Vec<ManifestKey>,
}

#[derive(Debug, Clone)]
pub struct ResolvedReceiptKey {
    pub key_id: String,
    pub public_key: [u8; 32],
    pub trust_class: ManifestTrustClass,
    pub key_epoch: u64,
}

#[derive(Debug, Clone)]
pub struct ResolvedAttestationKey {
    pub key_id: String,
    pub public_key: [u8; 32],
    pub key_epoch: u64,
}

fn parse_string_array(value: &Value, field: &str, max_items: usize) -> Result<Vec<String>, String> {
    let values = value.as_array().ok_or_else(|| format!("`{field}` must be an array"))?;
    if values.is_empty() || values.len() > max_items {
        return Err(format!("`{field}` must contain 1..={max_items} values"));
    }
    let mut out = Vec::with_capacity(values.len());
    let mut seen = BTreeSet::new();
    for item in values {
        let s = item.as_str().ok_or_else(|| format!("`{field}` values must be strings"))?;
        if s.is_empty() || s.len() > 128 || s == "*" || !seen.insert(s.to_string()) {
            return Err(format!("`{field}` contains an invalid, wildcard, or duplicate value"));
        }
        out.push(s.to_string());
    }
    Ok(out)
}

fn parse_key(value: &Value) -> Result<ManifestKey, String> {
    let object = value.as_object().ok_or("manifest key must be an object")?;
    let usage = object.get("key_usage").and_then(Value::as_str)
        .ok_or("manifest key missing key_usage")?;
    let receipt_fields = [
        "key_id", "public_key", "key_usage", "trust_class", "allowed_protocols",
        "workspace", "allowed_audiences", "supervisor_id", "valid_from", "valid_to",
        "key_epoch", "revoked",
    ];
    let attestation_fields = [
        "key_id", "public_key", "key_usage", "supervisor_id", "valid_from", "valid_to",
        "key_epoch", "revoked",
    ];
    let (object, key_usage) = match usage {
        "receipt_signing" => (exact_object(value, &receipt_fields, "receipt key")?, ManifestKeyUsage::ReceiptSigning),
        "supervisor_attestation" => (exact_object(value, &attestation_fields, "attestation key")?, ManifestKeyUsage::SupervisorAttestation),
        _ => return Err("unknown key_usage".to_string()),
    };
    let key_id = string(object, "key_id", 128)?.to_string();
    let public_key = decode_fixed::<32>(string(object, "public_key", 64)?, "public_key")?;
    let supervisor_id = string(object, "supervisor_id", 128)?.to_string();
    let valid_from = u64_value(object, "valid_from")?;
    let valid_to = u64_value(object, "valid_to")?;
    if valid_from > valid_to { return Err("valid_from is after valid_to".to_string()); }
    let key_epoch = u64_value(object, "key_epoch")?;
    let revoked = bool_value(object, "revoked")?;

    let (trust_class, allowed_protocols, workspace, allowed_audiences) = match key_usage {
        ManifestKeyUsage::ReceiptSigning => {
            let trust_class = match string(object, "trust_class", 32)? {
                "production" => ManifestTrustClass::Production,
                "development" => ManifestTrustClass::Development,
                _ => return Err("unknown trust_class".to_string()),
            };
            let protocols = parse_string_array(object.get("allowed_protocols").unwrap(), "allowed_protocols", 16)?;
            let workspace = string(object, "workspace", 128)?.to_string();
            if workspace == "*" { return Err("wildcard workspace is forbidden".to_string()); }
            let audiences = parse_string_array(object.get("allowed_audiences").unwrap(), "allowed_audiences", 64)?;
            (Some(trust_class), protocols, Some(workspace), audiences)
        }
        ManifestKeyUsage::SupervisorAttestation => (None, Vec::new(), None, Vec::new()),
    };
    Ok(ManifestKey {
        key_id, public_key, key_usage, supervisor_id, valid_from, valid_to, key_epoch,
        revoked, trust_class, allowed_protocols, workspace, allowed_audiences,
    })
}

fn parse_payload(payload: &Value) -> Result<ManifestSnapshot, String> {
    let fields = [
        "manifest_protocol", "manifest_version", "manifest_epoch", "root_key_id",
        "issued_at", "expires_at", "keys",
    ];
    let object = exact_object(payload, &fields, "manifest payload")?;
    if string(object, "manifest_protocol", 64)? != MANIFEST_PROTOCOL {
        return Err("wrong manifest_protocol".to_string());
    }
    if u64_value(object, "manifest_version")? != 1 { return Err("unsupported manifest_version".to_string()); }
    let manifest_epoch = u64_value(object, "manifest_epoch")?;
    let root_key_id = string(object, "root_key_id", 128)?.to_string();
    let issued_at = u64_value(object, "issued_at")?;
    let expires_at = u64_value(object, "expires_at")?;
    if issued_at > expires_at { return Err("issued_at is after expires_at".to_string()); }
    let key_values = object.get("keys").and_then(Value::as_array).ok_or("keys must be an array")?;
    if key_values.is_empty() || key_values.len() > 256 { return Err("keys must contain 1..=256 entries".to_string()); }
    let mut keys = Vec::with_capacity(key_values.len());
    let mut ids = BTreeSet::new();
    for value in key_values {
        let key = parse_key(value)?;
        if !ids.insert(key.key_id.clone()) { return Err(format!("duplicate key_id `{}`", key.key_id)); }
        keys.push(key);
    }
    let payload_bytes = canonical_bytes(payload)?;
    let manifest_hash = sha256_hex(&payload_bytes);
    Ok(ManifestSnapshot {
        payload_bytes, root_sig: String::new(), root_key_id, manifest_epoch, manifest_hash,
        issued_at, expires_at, keys,
    })
}

pub fn parse_and_verify_manifest(
    document_bytes: &[u8],
    roots: &PinnedRoots,
    now_ms: u64,
) -> Result<ManifestSnapshot, String> {
    if roots.is_empty() { return Err("no binary-pinned manifest root is configured".to_string()); }
    let document = parse_canonical(document_bytes, MAX_MANIFEST_BYTES)?;
    let object = exact_object(&document, &["payload", "root_sig"], "manifest document")?;
    let payload = object.get("payload").unwrap();
    let mut snapshot = parse_payload(payload)?;
    if now_ms > snapshot.expires_at { return Err("manifest is expired".to_string()); }
    let root_sig = string(object, "root_sig", 128)?.to_string();
    let signature = Signature::from_bytes(&decode_fixed::<64>(&root_sig, "root_sig")?);
    let root = roots.get(&snapshot.root_key_id).ok_or("unknown root_key_id")?;
    let verifying = VerifyingKey::from_bytes(root).map_err(|_| "invalid pinned root key")?;
    verifying.verify_strict(&snapshot.payload_bytes, &signature)
        .map_err(|_| "manifest root signature is invalid")?;
    snapshot.root_sig = root_sig;
    Ok(snapshot)
}

fn begin_immediate(conn: &Connection) -> CoreResult<()> {
    if !conn.is_autocommit() {
        return Err(invalid("manifest operation must own its transaction"));
    }
    conn.execute_batch("BEGIN IMMEDIATE;")?;
    Ok(())
}

pub fn accept_manifest(
    conn: &Connection,
    document_bytes: &[u8],
    roots: &PinnedRoots,
    now_ms: u64,
) -> CoreResult<ManifestSnapshot> {
    let snapshot = parse_and_verify_manifest(document_bytes, roots, now_ms).map_err(invalid)?;
    begin_immediate(conn)?;
    let result = (|| -> CoreResult<()> {
        let floor: Option<(u64, String)> = conn.query_row(
            "SELECT highest_epoch, manifest_hash FROM manifest_floor WHERE id=1", [],
            |r| Ok((r.get(0)?, r.get(1)?)),
        ).optional()?;
        if let Some((highest, hash)) = floor {
            if snapshot.manifest_epoch < highest {
                return Err(invalid("manifest epoch rollback"));
            }
            if snapshot.manifest_epoch == highest && snapshot.manifest_hash != hash {
                return Err(invalid("same manifest epoch has a different hash"));
            }
        }
        conn.execute(
            "INSERT INTO manifest_current(id,payload_bytes,root_sig,root_key_id,manifest_epoch,manifest_hash,accepted_at)\n             VALUES(1,?1,?2,?3,?4,?5,?6)\n             ON CONFLICT(id) DO UPDATE SET payload_bytes=excluded.payload_bytes,root_sig=excluded.root_sig,\n             root_key_id=excluded.root_key_id,manifest_epoch=excluded.manifest_epoch,\n             manifest_hash=excluded.manifest_hash,accepted_at=excluded.accepted_at",
            rusqlite::params![snapshot.payload_bytes, snapshot.root_sig, snapshot.root_key_id,
                snapshot.manifest_epoch, snapshot.manifest_hash, now_ms],
        )?;
        conn.execute(
            "INSERT INTO manifest_floor(id,highest_epoch,manifest_hash) VALUES(1,?1,?2)\n             ON CONFLICT(id) DO UPDATE SET highest_epoch=excluded.highest_epoch,manifest_hash=excluded.manifest_hash",
            rusqlite::params![snapshot.manifest_epoch, snapshot.manifest_hash],
        )?;
        Ok(())
    })();
    match result {
        Ok(()) => { conn.execute_batch("COMMIT;")?; Ok(snapshot) }
        Err(e) => { let _ = conn.execute_batch("ROLLBACK;"); Err(e) }
    }
}

pub fn load_snapshot(conn: &Connection) -> CoreResult<Option<ManifestSnapshot>> {
    let row: Option<(Vec<u8>, String, String, u64, String)> = conn.query_row(
        "SELECT payload_bytes,root_sig,root_key_id,manifest_epoch,manifest_hash FROM manifest_current WHERE id=1",
        [], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?)),
    ).optional()?;
    let Some((payload_bytes, root_sig, root_key_id, manifest_epoch, manifest_hash)) = row else { return Ok(None) };
    let payload = parse_canonical(&payload_bytes, MAX_MANIFEST_BYTES).map_err(invalid)?;
    let mut snapshot = parse_payload(&payload).map_err(invalid)?;
    if snapshot.root_key_id != root_key_id || snapshot.manifest_epoch != manifest_epoch || snapshot.manifest_hash != manifest_hash {
        return Err(invalid("durable manifest metadata does not match its payload"));
    }
    snapshot.root_sig = root_sig;
    Ok(Some(snapshot))
}

pub fn ensure_snapshot_current(conn: &Connection, snapshot: &ManifestSnapshot) -> CoreResult<()> {
    let row: Option<(u64, String, u64, String)> = conn.query_row(
        "SELECT f.highest_epoch,f.manifest_hash,c.manifest_epoch,c.manifest_hash\n         FROM manifest_floor f JOIN manifest_current c ON c.id=1 WHERE f.id=1",
        [], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
    ).optional()?;
    match row {
        Some((floor_epoch, floor_hash, current_epoch, current_hash))
            if floor_epoch == snapshot.manifest_epoch
                && current_epoch == snapshot.manifest_epoch
                && floor_hash == snapshot.manifest_hash
                && current_hash == snapshot.manifest_hash => Ok(()),
        _ => Err(invalid("manifest snapshot/floor mismatch")),
    }
}

pub fn resolve_receipt_key(
    snapshot: &ManifestSnapshot,
    key_id: &str,
    workspace_id: &str,
    install_id: &str,
    supervisor_id: &str,
    now_ms: u64,
) -> Result<ResolvedReceiptKey, String> {
    if now_ms > snapshot.expires_at { return Err("manifest is expired".to_string()); }
    let key = snapshot.keys.iter().find(|k| k.key_id == key_id).ok_or("unknown receipt key_id")?;
    if key.key_usage != ManifestKeyUsage::ReceiptSigning { return Err("key usage is not receipt_signing".to_string()); }
    if key.revoked || now_ms < key.valid_from || now_ms > key.valid_to { return Err("receipt key is revoked or out of window".to_string()); }
    if key.supervisor_id != supervisor_id { return Err("receipt key supervisor scope mismatch".to_string()); }
    if key.workspace.as_deref() != Some(workspace_id) { return Err("receipt key workspace scope mismatch".to_string()); }
    if !key.allowed_audiences.iter().any(|v| v == install_id) { return Err("receipt key audience scope mismatch".to_string()); }
    if !key.allowed_protocols.iter().any(|v| v == GOVERNED_RECEIPT_PROTOCOL) {
        return Err("receipt key protocol scope mismatch".to_string());
    }
    Ok(ResolvedReceiptKey {
        key_id: key.key_id.clone(), public_key: key.public_key,
        trust_class: key.trust_class.ok_or("receipt key is missing trust_class")?,
        key_epoch: key.key_epoch,
    })
}

pub fn resolve_attestation_key(
    snapshot: &ManifestSnapshot,
    key_id: &str,
    supervisor_id: &str,
    now_ms: u64,
) -> Result<ResolvedAttestationKey, String> {
    if now_ms > snapshot.expires_at { return Err("manifest is expired".to_string()); }
    let key = snapshot.keys.iter().find(|k| k.key_id == key_id).ok_or("unknown attestation key_id")?;
    if key.key_usage != ManifestKeyUsage::SupervisorAttestation { return Err("key usage is not supervisor_attestation".to_string()); }
    if key.revoked || now_ms < key.valid_from || now_ms > key.valid_to { return Err("attestation key is revoked or out of window".to_string()); }
    if key.supervisor_id != supervisor_id { return Err("attestation key supervisor scope mismatch".to_string()); }
    Ok(ResolvedAttestationKey { key_id: key.key_id.clone(), public_key: key.public_key, key_epoch: key.key_epoch })
}

#[cfg(test)]
mod tests {
    use super::*;
    use ed25519_dalek::{Signer, SigningKey};
    use serde_json::json;

    fn canonical(v: &Value) -> Vec<u8> { serde_json::to_vec(v).unwrap() }

    fn manifest(root: &SigningKey, epoch: u64) -> (Vec<u8>, PinnedRoots) {
        let receipt = SigningKey::from_bytes(&[7u8; 32]);
        let attest = SigningKey::from_bytes(&[8u8; 32]);
        let payload = json!({
            "expires_at": 999999u64,
            "issued_at": 1u64,
            "keys": [
                {"allowed_audiences":["install"],"allowed_protocols":[GOVERNED_RECEIPT_PROTOCOL],
                 "key_epoch":1u64,"key_id":"receipt","key_usage":"receipt_signing",
                 "public_key":URL_SAFE_NO_PAD.encode(receipt.verifying_key().as_bytes()),"revoked":false,
                 "supervisor_id":"supervisor","trust_class":"production","valid_from":1u64,"valid_to":999999u64,"workspace":"workspace"},
                {"key_epoch":1u64,"key_id":"attest","key_usage":"supervisor_attestation",
                 "public_key":URL_SAFE_NO_PAD.encode(attest.verifying_key().as_bytes()),"revoked":false,
                 "supervisor_id":"supervisor","valid_from":1u64,"valid_to":999999u64}
            ],
            "manifest_epoch":epoch,"manifest_protocol":MANIFEST_PROTOCOL,"manifest_version":1u64,"root_key_id":"root"
        });
        let payload_bytes = canonical(&payload);
        let doc = json!({"payload": payload, "root_sig": URL_SAFE_NO_PAD.encode(root.sign(&payload_bytes).to_bytes())});
        let roots = PinnedRoots::new(vec![("root".to_string(), root.verifying_key().to_bytes())]).unwrap();
        (canonical(&doc), roots)
    }

    #[test]
    fn accept_and_resolve_type_separated_keys() {
        let conn = crate::db::open_in_memory().unwrap();
        let root = SigningKey::from_bytes(&[9u8; 32]);
        let (doc, roots) = manifest(&root, 2);
        let snapshot = accept_manifest(&conn, &doc, &roots, 10).unwrap();
        ensure_snapshot_current(&conn, &snapshot).unwrap();
        let receipt = resolve_receipt_key(&snapshot, "receipt", "workspace", "install", "supervisor", 10).unwrap();
        assert_eq!(receipt.trust_class, ManifestTrustClass::Production);
        assert!(resolve_receipt_key(&snapshot, "attest", "workspace", "install", "supervisor", 10).is_err());
        assert!(resolve_attestation_key(&snapshot, "receipt", "supervisor", 10).is_err());
        assert!(resolve_attestation_key(&snapshot, "attest", "supervisor", 10).is_ok());
    }

    #[test]
    fn anti_rollback_rejects_lower_and_same_epoch_different_hash() {
        let conn = crate::db::open_in_memory().unwrap();
        let root = SigningKey::from_bytes(&[9u8; 32]);
        let (doc2, roots) = manifest(&root, 2);
        accept_manifest(&conn, &doc2, &roots, 10).unwrap();
        let (doc1, _) = manifest(&root, 1);
        assert!(accept_manifest(&conn, &doc1, &roots, 10).is_err());
        let mut value: Value = serde_json::from_slice(&doc2).unwrap();
        value["payload"]["expires_at"] = Value::from(999998u64);
        let payload_bytes = canonical(&value["payload"]);
        value["root_sig"] = Value::from(URL_SAFE_NO_PAD.encode(root.sign(&payload_bytes).to_bytes()));
        assert!(accept_manifest(&conn, &canonical(&value), &roots, 10).is_err());
    }
}
