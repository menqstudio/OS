//! Registration: the elevated steps `audit_signer::install_steps` specifies, made real, plus the
//! one thing that plan did not name — publishing the signer's public half into the trusted-key
//! registry so the engine can verify what it signs.
//!
//! # The order matters and it is not the obvious one
//!
//! 1. **Elevated installer**: create `%ProgramData%\BroPS\audit-signer` with the protected DACL
//!    from `audit_signer::key_dacl_plan` (owner `BUILTIN\Administrators`, the app absent), write
//!    `allowed-app.sid`, `sc.exe create` + `sc.exe sidtype … unrestricted`, `sc.exe start`.
//! 2. **The service, on first start, under its own account**: mints the seed, publishes
//!    `custody.json`. The installer never sees the private half — the point of doing it in this
//!    order rather than the convenient one.
//! 3. **The app, unelevated, afterwards**: reads `custody.json` (public half + key id) and calls
//!    [`register_anchor_key`] to put that key in its own trusted-key registry under the
//!    `evidence-recorder` authority, because `bro_audit_log.verify_signed_payload` resolves the
//!    anchor's `key_id` through `bro_signature.load_trusted_keys` and refuses a key it has never
//!    heard of.
//!
//! Step 3 is what makes the anchor *verifiable*; it is not what makes it *trustworthy*. Read
//! [`REGISTRY_CAVEAT`] before believing otherwise.

use std::path::Path;

use serde_json::{json, Value};

use brops_provision::audit_signer as spec;
use brops_provision::ProvisionError;

/// The file the installer writes into the signer's protected directory naming the one peer SID the
/// pipe will accept.
///
/// It lives beside the key, under the same protected DACL, for a reason: if the **app** could
/// write it, the app could nominate a second account — or a service account it controls — as an
/// accepted peer. Config the defended party can rewrite is not a boundary.
pub const ALLOWED_APP_SID_FILE: &str = "allowed-app.sid";

/// The honest limit of what registering the signer's key buys, stated where the function that does
/// it can be read next to it.
///
/// Putting the signer's public key in the registry lets the engine *verify* an anchor the signer
/// produced. It does not stop anything else in the registry from producing one.
/// `bro_audit_log.ANCHOR_AUTHORITIES` is `("evidence-recorder", "operator-root")` and
/// `verify_signed_payload` accepts **any active registry key under either authority** — it does
/// not consult `allowed_artifact_types`, and says so in its own docstring, because `audit-head` is
/// deliberately not a registry artifact type.
///
/// `brops_provision::provision()` mints one key per `AUTHORITY_TYPES` and writes **every private
/// half** into `<app_data>/trust/keys/`, which the app's own account owns. Two of those —
/// `evidence-recorder.json` and `operator-root.json` — are anchor-capable. So on a stock
/// deployment the ledger's own writer holds a key that signs an anchor the engine accepts, and can
/// truncate the ledger, recompute the chain, rewrite `.head`, mint a fresh `.head.sig` and have
/// `verify(keys=…)` return green. That is the O-2 defect verbatim, and no property of the signer
/// service touches it: the second principal is a second *route* to a signature, not the only one.
///
/// `tests/forgery.rs` demonstrates it against the real `bro_audit_log`. Until the registry stops
/// carrying an anchor-capable key whose private half the app holds, O-2 is not closed and nothing
/// in this crate should be described as closing it.
pub const REGISTRY_CAVEAT: &str = "\
registering the signer's public key makes its anchors VERIFIABLE. It does not make them the only \
verifiable anchors: bro_audit_log accepts any active registry key under the evidence-recorder or \
operator-root authority, and brops_provision::provision() leaves both private halves in the app's \
own trust directory. See REGISTRY_CAVEAT and tests/forgery.rs.";

/// The complete elevated plan: the specification's steps, then this crate's.
pub fn install_plan(paths: &spec::SignerPaths, app_sid: &str) -> Vec<String> {
    let mut steps = spec::install_steps(paths, app_sid);
    steps.extend(crate::additional_install_steps(paths, app_sid));
    steps.push(format!(
        "# then, UNELEVATED and after the service's first start: read {} and call \
         register_anchor_key() so the engine can resolve the anchor's key_id. {}",
        paths.custody_file.display(),
        REGISTRY_CAVEAT
    ));
    steps
}

/// Read the app SID the installer authorised. Fail-closed: no file, no serving.
pub fn read_allowed_app_sid(signer_dir: &Path) -> Result<String, String> {
    let path = signer_dir.join(ALLOWED_APP_SID_FILE);
    let raw = std::fs::read_to_string(&path).map_err(|e| {
        format!(
            "cannot read {} ({e}). The installer writes the ONE peer SID this signer's pipe \
             accepts; without it there is no allowlist, and a signer that served every local \
             account would be a signing oracle for the whole machine",
            path.display()
        )
    })?;
    let sid = raw.trim().to_string();
    if !spec::looks_like_sid(&sid) {
        return Err(format!("{} does not contain a SID (got {sid:?})", path.display()));
    }
    if spec::WORLD_SIDS.contains(&sid.as_str()) {
        return Err(format!(
            "{} names the world SID {sid}. Granting it is indistinguishable from serving every \
             account on the box",
            path.display()
        ));
    }
    Ok(sid)
}

/// Publish the signer's key into the app's trusted-key registry.
///
/// Takes the **published custody record**, never a key: the only fields read are `key_id` and
/// `public_key`, and [`crate::custody::read_custody`] refuses a record carrying anything secret.
/// The registry is re-signed with the operator-root key (which the app holds — see
/// [`REGISTRY_CAVEAT`]), `registry_version` is raised, the anti-rollback floor file is raised with
/// it, and the provisioning manifest's digests for both files are updated so
/// `brops_provision::verify_existing` still accepts the store on the next launch.
///
/// Idempotent: a registry that already carries this key id is left untouched.
pub fn register_anchor_key(trust_dir: &Path, custody: &Value) -> Result<String, ProvisionError> {
    let key_id = custody
        .get("key_id")
        .and_then(Value::as_str)
        .ok_or_else(|| corrupt("the custody record has no key_id"))?
        .to_string();
    let public_key = custody
        .get("public_key")
        .and_then(Value::as_str)
        .ok_or_else(|| corrupt("the custody record has no public_key"))?
        .to_string();
    if public_key.len() != 64 || !public_key.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err(corrupt("the custody record's public_key is not a 32-byte Ed25519 key"));
    }
    if custody.get("authority").and_then(Value::as_str) != Some(spec::ANCHOR_AUTHORITY) {
        return Err(corrupt(
            "the custody record does not claim the evidence-recorder authority, so registering it \
             would grant a key an authority its own publisher never claimed",
        ));
    }

    let registry_path = trust_dir
        .join(brops_provision::REGISTRY_ROOT_DIR)
        .join("config")
        .join("trusted-keys.json");
    let floor_path =
        trust_dir.join(brops_provision::PIN_DIR).join(brops_provision::REGISTRY_FLOOR_FILE);
    let manifest_path = trust_dir.join(brops_provision::MANIFEST_FILE);

    let document: Value = read_json(&registry_path)?;
    let mut payload = document
        .get("payload")
        .and_then(Value::as_object)
        .ok_or_else(|| corrupt("the trusted-key registry has no payload object"))?
        .clone();

    let entries = payload
        .get("keys")
        .and_then(Value::as_array)
        .ok_or_else(|| corrupt("the trusted-key registry has no keys array"))?
        .clone();
    if entries.iter().any(|e| e.get("key_id").and_then(Value::as_str) == Some(key_id.as_str())) {
        return Ok(key_id);
    }

    let operator = brops_provision::load_key(trust_dir, brops_provision::OPERATOR)?;
    let version = payload.get("registry_version").and_then(Value::as_i64).unwrap_or(1) + 1;

    let mut entries = entries;
    entries.push(json!({
        "key_id": key_id,
        "public_key": public_key,
        "authority_type": spec::ANCHOR_AUTHORITY,
        // The same set every other evidence-recorder key carries. `verify_signed_payload` does not
        // read it for `audit-head` (that binding is the authority type), but
        // `bro_signature.verify_artifact` does for the registry artifact types, and a key with an
        // inconsistent set would make the registry describe two different evidence recorders.
        "allowed_artifact_types": brops_provision::artifacts_for(spec::ANCHOR_AUTHORITY),
        "not_before_epoch": brops_provision::NOT_BEFORE_EPOCH,
        "not_after_epoch": brops_provision::NEVER_EXPIRES_EPOCH,
        "status": "active",
        "issued_by": operator.key_id,
        "provenance": "minted by NT SERVICE\\BroPSAuditSigner on its own first start; this \
                       registry never held the private half",
    }));
    entries.sort_by(|a, b| {
        a["key_id"].as_str().unwrap_or("").cmp(b["key_id"].as_str().unwrap_or(""))
    });
    payload.insert("keys".into(), Value::Array(entries));
    payload.insert("registry_version".into(), json!(version));

    let resigned = brops_provision::sign_document(&operator.signing, Value::Object(payload))?;
    write_canonical(&registry_path, &resigned)?;
    write_bytes(&floor_path, format!("{version}\n").as_bytes())?;

    // The manifest records a digest for every provisioned file; two of them just changed.
    let mut manifest: Value = read_json(&manifest_path)?;
    {
        let files = manifest
            .get_mut("files")
            .and_then(Value::as_object_mut)
            .ok_or_else(|| corrupt("the provisioning manifest has no files map"))?;
        for (relative, path) in [
            (format!("{}/config/trusted-keys.json", brops_provision::REGISTRY_ROOT_DIR), &registry_path),
            (
                format!("{}/{}", brops_provision::PIN_DIR, brops_provision::REGISTRY_FLOOR_FILE),
                &floor_path,
            ),
        ] {
            let bytes = std::fs::read(path).map_err(|e| ProvisionError::Io {
                what: "re-hashing an amended provisioned file".into(),
                path: path.clone(),
                source: e,
            })?;
            files.insert(relative, json!(brops_provision::sha256_hex(&bytes)));
        }
    }
    write_canonical(&manifest_path, &manifest)?;
    Ok(key_id)
}

fn corrupt(what: &str) -> ProvisionError {
    ProvisionError::Corrupt { what: what.to_string(), detail: REGISTRY_CAVEAT.to_string() }
}

fn read_json(path: &Path) -> Result<Value, ProvisionError> {
    let bytes = std::fs::read(path).map_err(|e| ProvisionError::Io {
        what: "reading a trust-store file".into(),
        path: path.to_path_buf(),
        source: e,
    })?;
    serde_json::from_slice(&bytes).map_err(|e| ProvisionError::Corrupt {
        what: format!("{} is not JSON", path.display()),
        detail: e.to_string(),
    })
}

fn write_canonical(path: &Path, value: &Value) -> Result<(), ProvisionError> {
    let mut bytes = brops_provision::canonical::canonical_bytes(value)?;
    bytes.push(b'\n');
    write_bytes(path, &bytes)
}

fn write_bytes(path: &Path, bytes: &[u8]) -> Result<(), ProvisionError> {
    std::fs::write(path, bytes).map_err(|e| ProvisionError::Io {
        what: "writing a trust-store file".into(),
        path: path.to_path_buf(),
        source: e,
    })
}

// =================================================================================================
// Applying the plan, for real, under elevation
// =================================================================================================

/// Run the elevated half of [`install_plan`]: create the signer's directory with the protected
/// DACL, write the peer allowlist, register the service, and **read the descriptor back** to prove
/// what was applied.
///
/// Elevation is checked first and refused by name. `CreateServiceW` needs
/// `SC_MANAGER_CREATE_SERVICE`, which the SCM withholds from a standard user by design, and
/// stamping `BUILTIN\Administrators` as owner needs a token that may assign that owner
/// (`ERROR_INVALID_OWNER` otherwise). There is no unelevated path, and a scheme that avoided this
/// prompt would avoid the second principal with it.
///
/// The key is deliberately **not** minted here: the service does that on its own first start, so
/// the elevated installer never witnesses the private half ([`spec::MINT_LOCATION_NOTE`]).
///
/// Returns the read-back proof, so a caller states the number it computed rather than the fact
/// that it was happy.
#[cfg(windows)]
pub fn apply(paths: &spec::SignerPaths, app_sid: &str) -> Result<spec::ReadbackProof, spec::AnchorRefusal> {
    let signer_sid = spec::service_account_sid(spec::SIGNER_SERVICE_NAME);

    match spec::winimpl::app_token_posture()? {
        spec::AppTokenPosture::ElevatedAdministrator => {}
        _ => {
            return Err(spec::AnchorRefusal::ElevationRequired {
                step: "creating the BroPSAuditSigner service and its protected key directory"
                    .to_string(),
            })
        }
    }

    // The plans are built (and self-checked) before anything is created, so a refusal costs
    // nothing and leaves no half-provisioned directory behind.
    let key_plan = spec::key_dacl_plan(app_sid, &signer_sid)?;
    let _ledger_plan = spec::ledger_dacl_plan(app_sid, &signer_sid)?;

    // 1. The service first: a virtual account's SID does not resolve until the service exists, so
    //    an ACE naming it before registration would be written for an unresolvable trustee.
    for step in [
        vec![
            "create".to_string(),
            spec::SIGNER_SERVICE_NAME.to_string(),
            format!("binPath= {}", paths.service_exe.display()),
            format!("obj= NT SERVICE\\{}", spec::SIGNER_SERVICE_NAME),
            "start= auto".to_string(),
            "DisplayName= BroPS audit-head anchor signer".to_string(),
        ],
        vec![
            "sidtype".to_string(),
            spec::SIGNER_SERVICE_NAME.to_string(),
            "unrestricted".to_string(),
        ],
    ] {
        run_sc(&step)?;
    }

    // 2. The name must resolve to the SID derived from it. Somebody who pre-created a real account
    //    called BroPSAuditSigner would otherwise be handed the key.
    let resolved = spec::winimpl::resolve_service_sid(spec::SIGNER_SERVICE_NAME)?;
    if resolved != signer_sid {
        return Err(spec::AnchorRefusal::SignerSidSubstituted {
            name: spec::SIGNER_SERVICE_NAME.to_string(),
            derived: signer_sid,
            resolved,
        });
    }

    // 3. The directory, then its protected DACL and TCB owner.
    std::fs::create_dir_all(&paths.signer_dir).map_err(|e| spec::AnchorRefusal::Unmeasurable {
        path: paths.signer_dir.display().to_string(),
        why: format!("creating the signer directory: {e}"),
    })?;
    spec::winimpl::apply_dacl(&paths.signer_dir, &key_plan, Some(spec::SID_ADMINISTRATORS))?;

    // 4. The peer allowlist, INSIDE the now-protected directory so the app cannot rewrite it.
    let allowed = paths.signer_dir.join(ALLOWED_APP_SID_FILE);
    std::fs::write(&allowed, format!("{app_sid}\n")).map_err(|e| {
        spec::AnchorRefusal::Unmeasurable {
            path: allowed.display().to_string(),
            why: format!("writing the peer allowlist: {e}"),
        }
    })?;

    // 5. Read the descriptor BACK and compute. Never "we asked for it, so it is so".
    let facts = spec::winimpl::dacl_facts(&paths.signer_dir)?;
    let proof = spec::verify_key_custody(&key_plan, &facts)?;

    // 6. Only now start the service, which mints its own seed inside a directory that has already
    //    been proved to exclude the app.
    run_sc(&["start".to_string(), spec::SIGNER_SERVICE_NAME.to_string()])?;
    Ok(proof)
}

#[cfg(windows)]
fn run_sc(args: &[String]) -> Result<(), spec::AnchorRefusal> {
    let output = std::process::Command::new("sc.exe").args(args).output().map_err(|e| {
        spec::AnchorRefusal::SignerAbsent { why: format!("could not run `sc.exe {args:?}`: {e}") }
    })?;
    // `sc.exe` returns 1073 (service exists) / 1056 (already running) for re-runs, which are the
    // idempotent cases the install plan promises are safe to repeat.
    const ALREADY_EXISTS: i32 = 1073;
    const ALREADY_RUNNING: i32 = 1056;
    match output.status.code() {
        Some(0) | Some(ALREADY_EXISTS) | Some(ALREADY_RUNNING) => Ok(()),
        other => Err(spec::AnchorRefusal::SignerAbsent {
            why: format!(
                "`sc.exe {args:?}` exited {other:?}: {}{}",
                String::from_utf8_lossy(&output.stdout).trim(),
                String::from_utf8_lossy(&output.stderr).trim()
            ),
        }),
    }
}

/// Off Windows there is no SCM and no second principal to create.
#[cfg(not(windows))]
pub fn apply(
    paths: &spec::SignerPaths,
    app_sid: &str,
) -> Result<spec::ReadbackProof, spec::AnchorRefusal> {
    let _ = (paths, app_sid);
    Err(spec::AnchorRefusal::Unsupported {
        platform: brops_provision::platform_name().to_string(),
        what: "registering a Windows service and stamping a protected DACL. On POSIX the audit \
               signer is already a separate uid, provisioned outside this crate"
            .to_string(),
    })
}
