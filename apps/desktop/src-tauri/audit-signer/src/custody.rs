//! The anchor key on disk: minted by the service, under the service's own account, on first start.
//!
//! `audit_signer::MINT_LOCATION_NOTE` states the rule this module implements — *neither the
//! installer nor the app ever holds the private half*. The installer runs as a human's elevated
//! token; if it minted the keypair it would have witnessed the secret, which is avoidable here in
//! a way it is not for the operator root. So the installer creates only the directory (with the
//! protected DACL from `audit_signer::key_dacl_plan`) and the service; the seed appears for the
//! first time inside a process that is already running as `NT SERVICE\BroPSAuditSigner`.
//!
//! Three files, all inside `SignerPaths::signer_dir`:
//!
//! * `anchor.key` — the raw 32-byte Ed25519 seed as hex. Never leaves this process.
//! * `custody.json` — `audit_signer::custody_record`: the **public** half, the key id, the
//!   principal. The app reads it to learn which key to name; it can never write it.
//! * `anchor-state.json` — the per-ledger high-water marks. Must be unreadable and unwritable by
//!   the app or the anti-rollback guarantee is a suggestion: a forger who can rewrite the signer's
//!   memory of what it signed can ask it to sign a truncation.
//!
//! # Why `create_new`, and what happens on a second start
//!
//! The mint uses `create_new`, so a seed that already exists is **read, never replaced**. Silently
//! re-minting would be a rotation nobody asked for, and every anchor signed under the old key
//! would stop verifying while the ledger still looked intact — the failure mode this whole feature
//! exists to prevent, arriving from the other direction.

use std::collections::BTreeMap;
use std::path::Path;

use ed25519_dalek::SigningKey;
use serde_json::Value;

use brops_provision::audit_signer as spec;

/// Everything the service needs to sign, and nothing it does not.
pub struct SignerCustody {
    pub key: SigningKey,
    pub key_id: String,
    pub public_key: String,
    /// `true` when THIS start minted the key.
    pub freshly_minted: bool,
}

#[derive(Debug)]
pub enum CustodyError {
    Io { what: String, path: String, source: std::io::Error },
    Corrupt { what: String, detail: String },
    Mint(String),
}

impl std::fmt::Display for CustodyError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            CustodyError::Io { what, path, source } => write!(f, "{what} ({path}): {source}"),
            CustodyError::Corrupt { what, detail } => write!(f, "{what}: {detail}"),
            CustodyError::Mint(why) => write!(f, "minting the anchor key: {why}"),
        }
    }
}

impl std::error::Error for CustodyError {}

fn io<T>(r: std::io::Result<T>, what: &str, path: &Path) -> Result<T, CustodyError> {
    r.map_err(|source| CustodyError::Io {
        what: what.to_string(),
        path: path.display().to_string(),
        source,
    })
}

/// Read the seed if it is there, mint it if it is not.
///
/// `signer_sid` is stamped into the custody record so a reader can see which principal the key
/// belongs to without resolving anything. It is **not** trusted as an identity check — that is
/// `AnchorCore`'s `running_as` / `expected_principal` comparison, which happens before this is
/// called in the service and independently inside `audit_signer::anchor_request`.
pub fn load_or_mint(signer_dir: &Path, signer_sid: &str) -> Result<SignerCustody, CustodyError> {
    let key_file = signer_dir.join(spec::KEY_FILE_NAME);
    let custody_file = signer_dir.join(spec::CUSTODY_FILE_NAME);
    // 0755, STATED. `create_dir_all` would have used `0777 & ~umask`, which under a stock
    // Debian `umask 002` is 0775 — a signer directory anyone in the group can add a
    // `custody.json` to. The mode is not the boundary on Windows (the protected DACL is), but
    // on POSIX it is the only one there is, and it must not be decided by the shell that
    // started the service. See `brops_provision::Exposure`.
    io(
        brops_provision::create_dir_all_mode(
            signer_dir,
            brops_provision::Exposure::WorldReadable.dir_mode(),
        ),
        "creating the signer directory",
        signer_dir,
    )?;

    if key_file.is_file() {
        let raw = io(std::fs::read_to_string(&key_file), "reading the anchor key", &key_file)?;
        let seed_hex = raw.trim();
        let seed: [u8; 32] = match brops_provision::unhex(seed_hex).map(<[u8; 32]>::try_from) {
            Some(Ok(s)) => s,
            _ => {
                return Err(CustodyError::Corrupt {
                    what: "the anchor key file does not hold a 32-byte seed".to_string(),
                    detail: format!(
                        "{}: expected 64 hex characters, got {} characters. Refusing to mint over \
                         it — a replaced key silently invalidates every anchor already installed",
                        key_file.display(),
                        seed_hex.len()
                    ),
                })
            }
        };
        let key = SigningKey::from_bytes(&seed);
        let public = brops_provision::hex(key.verifying_key().as_bytes());
        let key_id = spec::anchor_key_id(&public);
        // The custody record is rewritten from the key on every start, so a record that drifted
        // from the key it describes cannot survive a restart.
        write_custody(&custody_file, &key_id, &public, signer_sid)?;
        return Ok(SignerCustody { key, key_id, public_key: public, freshly_minted: false });
    }

    let (key, public, key_id) =
        spec::mint_anchor_key().map_err(|e| CustodyError::Mint(e.to_string()))?;
    let seed_hex = brops_provision::hex(key.as_bytes());

    // `create_new`: if another instance of the service won the race between the `is_file` above
    // and here, its key is the real one — read it back rather than clobber it.
    let mut options = std::fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    match options.open(&key_file) {
        Ok(mut file) => {
            use std::io::Write;
            io(file.write_all(format!("{seed_hex}\n").as_bytes()), "writing the anchor key", &key_file)?;
            io(file.sync_all(), "flushing the anchor key", &key_file)?;
            drop(file);
            io(
                brops_provision::secure_owner_only_file(&key_file),
                "restricting the anchor key to its owner",
                &key_file,
            )?;
        }
        Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {
            return load_or_mint(signer_dir, signer_sid)
        }
        Err(e) => {
            return Err(CustodyError::Io {
                what: "creating the anchor key".to_string(),
                path: key_file.display().to_string(),
                source: e,
            })
        }
    }
    write_custody(&custody_file, &key_id, &public, signer_sid)?;
    Ok(SignerCustody { key, key_id, public_key: public, freshly_minted: true })
}

fn write_custody(
    path: &Path,
    key_id: &str,
    public: &str,
    signer_sid: &str,
) -> Result<(), CustodyError> {
    let record = spec::custody_record(key_id, public, signer_sid);
    let bytes = brops_provision::canonical::canonical_bytes(&record).map_err(|e| {
        CustodyError::Corrupt {
            what: "serialising the custody record".to_string(),
            detail: e.to_string(),
        }
    })?;
    let mut with_newline = bytes;
    with_newline.push(b'\n');
    // 0644, STATED. This record is what provisioning reads — running as the APP's account —
    // to learn the key id and the public half, so it must be world-readable; and it is what
    // binds the anchor key into a registry that can never be re-signed, so it must be
    // writable by nobody else. `fs::write` would have left both to the umask.
    io(
        brops_provision::write_at(
            path,
            &with_newline,
            brops_provision::Exposure::WorldReadable,
        ),
        "writing the custody record",
        path,
    )
}

/// Read the published custody record. Used by provisioning (which must learn the key id and the
/// public half without ever seeing the seed) and by the tests.
pub fn read_custody(signer_dir: &Path) -> Result<Value, CustodyError> {
    let path = signer_dir.join(spec::CUSTODY_FILE_NAME);
    let raw = io(std::fs::read(&path), "reading the custody record", &path)?;
    let value: Value = serde_json::from_slice(&raw).map_err(|e| CustodyError::Corrupt {
        what: "the custody record is not JSON".to_string(),
        detail: e.to_string(),
    })?;
    // The record must not contain a secret. Checked on the READ side too, so a record written by
    // some future edit that leaked the seed is refused by every reader rather than trusted.
    if let Some(obj) = value.as_object() {
        for suspicious in ["private_key", "seed", "secret"] {
            if obj.contains_key(suspicious) {
                return Err(CustodyError::Corrupt {
                    what: "the published custody record contains a private field".to_string(),
                    detail: format!(
                        "{} carries {suspicious:?}. The custody record is world-readable by \
                         design; a secret in it is a secret the app holds",
                        path.display()
                    ),
                });
            }
        }
    }
    Ok(value)
}

// -------------------------------------------------------------------------------------------------
// Anti-rollback state
// -------------------------------------------------------------------------------------------------

/// Load the per-ledger high-water marks. A **missing** file is an empty map (first start); a
/// **corrupt** one is an error, never an empty map — "I cannot read what I signed" must not
/// silently become "I have signed nothing", which would reset the rollback floor to zero.
pub fn load_state(path: &Path) -> Result<BTreeMap<String, spec::AnchorState>, CustodyError> {
    if !path.exists() {
        return Ok(BTreeMap::new());
    }
    let raw = io(std::fs::read(path), "reading the anchor state", path)?;
    let value: Value = serde_json::from_slice(&raw).map_err(|e| CustodyError::Corrupt {
        what: "the anchor state file is not JSON".to_string(),
        detail: format!("{}: {e}", path.display()),
    })?;
    let entries = value.get("ledgers").and_then(Value::as_array).ok_or_else(|| {
        CustodyError::Corrupt {
            what: "the anchor state file has no `ledgers` array".to_string(),
            detail: path.display().to_string(),
        }
    })?;
    let mut out = BTreeMap::new();
    for entry in entries {
        let get = |k: &str| entry.get(k).and_then(Value::as_str).map(str::to_string);
        let (Some(ledger), Some(last_hash), Some(anchor_sha256), Some(count)) = (
            get("ledger"),
            get("last_hash"),
            get("anchor_sha256"),
            entry.get("count").and_then(Value::as_i64),
        ) else {
            return Err(CustodyError::Corrupt {
                what: "an anchor state entry is missing a field".to_string(),
                detail: format!("{}: {entry}", path.display()),
            });
        };
        out.insert(
            ledger.clone(),
            spec::AnchorState { ledger, count, last_hash, anchor_sha256 },
        );
    }
    Ok(out)
}

/// Write the high-water marks, replacing the file atomically.
///
/// `os::replace` semantics: a crash mid-write must not leave a truncated state file, because
/// [`load_state`] would then refuse to start the signer — fail-closed, but needlessly.
pub fn save_state(
    path: &Path,
    state: &BTreeMap<String, spec::AnchorState>,
) -> Result<(), CustodyError> {
    let ledgers: Vec<Value> = state
        .values()
        .map(|s| {
            serde_json::json!({
                "ledger": s.ledger,
                "count": s.count,
                "last_hash": s.last_hash,
                "anchor_sha256": s.anchor_sha256,
            })
        })
        .collect();
    let document = serde_json::json!({ "schema": 1, "ledgers": ledgers });
    let mut bytes = brops_provision::canonical::canonical_bytes(&document).map_err(|e| {
        CustodyError::Corrupt {
            what: "serialising the anchor state".to_string(),
            detail: e.to_string(),
        }
    })?;
    bytes.push(b'\n');
    let tmp = path.with_extension("json.tmp");
    // 0600, STATED. This is the anti-rollback high-water mark: an account that can rewrite it
    // can make the signer bless a count it has already signed past. Nothing outside the signer
    // reads it, so it gets the tightest mode there is rather than whatever the umask allowed.
    io(
        brops_provision::write_at(&tmp, &bytes, brops_provision::Exposure::OwnerOnly),
        "writing the anchor state",
        &tmp,
    )?;
    io(std::fs::rename(&tmp, path), "replacing the anchor state", path)?;
    Ok(())
}
