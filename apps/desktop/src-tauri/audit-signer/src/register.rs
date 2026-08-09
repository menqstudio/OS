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
//! 3. **The app, on its FIRST launch, unelevated**: reads `custody.json` (public half + key id)
//!    and passes it to `brops_provision::provision_with_anchor`, which admits it to the
//!    trusted-key registry under the dedicated `audit-anchor` authority — because
//!    `bro_audit_log.verify_signed_payload` resolves the anchor's `key_id` through
//!    `bro_signature.load_trusted_keys` and refuses a key it has never heard of.
//!
//! **Step 3 used to be an amendment and no longer can be.** It was
//! [`register_anchor_key`]: read the store, add an entry, re-sign the registry with the
//! `operator-root` private half the app held. `provision()` now destroys that half before it
//! returns, so the registry is sealed the moment it is signed and there is no key left that
//! could amend it. The anchor's public half therefore has to be in hand while the registry is
//! being signed, which is why it is an argument to provisioning and why the install order above
//! is not negotiable: the service must exist and have started before the app's first launch.
//! [`register_anchor_key`] survives as the CONFIRMATION of that — it verifies the key is present
//! and refuses, naming the remedy, when it is not.
//!
//! Step 3 is what makes the anchor *verifiable*; it is not what makes it *trustworthy*. Read
//! [`REGISTRY_CAVEAT`] before believing otherwise.

use std::path::Path;

use serde_json::Value;

use brops_provision::audit_signer as spec;
use brops_provision::ProvisionError;

/// The file the installer writes into the signer's protected directory naming the one peer SID the
/// pipe will accept.
///
/// It lives beside the key, under the same protected DACL, for a reason: if the **app** could
/// write it, the app could nominate a second account — or a service account it controls — as an
/// accepted peer. Config the defended party can rewrite is not a boundary.
pub const ALLOWED_APP_SID_FILE: &str = "allowed-app.sid";

/// The honest limit of what admitting the signer's key buys, stated where the function that does
/// it can be read next to it.
///
/// Putting the signer's public key in the registry lets the engine *verify* an anchor the signer
/// produced. What it does NOT do is decide who else can produce one; that is
/// `bro_audit_log.ANCHOR_AUTHORITIES`, which is hardcoded in the engine and reads
/// `("audit-anchor",)` alone. `verify_signed_payload` accepts any active registry key under that
/// authority — it does not consult `allowed_artifact_types`, and says so in its own docstring,
/// because `audit-head` is deliberately not a registry artifact type.
///
/// **What narrowing the authority closed.** `brops_provision::provision()` mints one key per
/// authority it knows and writes the private halves into `<app_data>/trust/keys/`, which the app's
/// own account owns. While `evidence-recorder` and `operator-root` were anchor authorities, two of
/// those files were anchor-capable: the ledger's own writer could truncate the chain, recompute it,
/// mint a fresh `.head.sig` and have `verify(keys=…)` return green. `audit-anchor` is deliberately
/// absent from what provisioning mints, so the app has nothing to anchor with.
///
/// **What destroying the operator root closed.** The route that narrowing could not reach was the
/// registry itself: `operator-root` signs it, so an account holding that private half could admit
/// an `audit-anchor` key of its own choosing — this very function is the shape of that attack, run
/// with a key of the attacker's choosing. `provision()` now destroys the root at the end of the
/// mint, so no such half exists and no key can be added to the registry by anybody. That is why
/// [`register_anchor_key`] no longer registers anything: it can only CONFIRM that the anchor key is
/// already there, admitted at mint time by a root that no longer exists
/// (`brops_provision::provision_with_anchor`).
///
/// **What is STILL open, stated plainly.** The operator-root PIN — `pin/operator-root.pub` — is a
/// file in the app's own trust directory, honoured under
/// `BRO_OPERATOR_ROOT_PIN_SELF_OWNED=acknowledged`. An account that can rewrite it does not need
/// the destroyed key at all: it generates an operator key of its own, pins it, re-signs the
/// registry under it with an `audit-anchor` entry of its choosing, and raises the floor it also
/// owns. That route is proved open, by running it against the real `bro_audit_log`, in
/// `tests/anchor_end_to_end.py` (`case_pin_rewrite`). Destroying the key removed a key; it did not
/// move the anchor out of the app's reach, and only a second principal holding the pin can.
pub const REGISTRY_CAVEAT: &str = "\
the anchor key makes the signer's anchors VERIFIABLE, and bro_audit_log accepts ONLY the \
audit-anchor authority, whose private half this crate never mints. The key is admitted to the \
registry at PROVISIONING time, by an operator-root private half that is destroyed before \
provisioning returns, so the registry is sealed and no key can be added to it afterwards. The \
residual route is not a key at all: the operator-root PIN is a file in the app's own trust \
directory, so an account that can rewrite it can install a root of its own and re-sign \
everything under it. That is closed only by a second principal holding the pin, which this \
deployment does not have.";

/// The complete elevated plan: the specification's steps, then this crate's.
pub fn install_plan(paths: &spec::SignerPaths, app_sid: &str) -> Vec<String> {
    let mut steps = spec::install_steps(paths, app_sid);
    steps.extend(crate::additional_install_steps(paths, app_sid));
    steps.push(format!(
        "# then, UNELEVATED and after the service's first start, on the app's FIRST launch: \
         read {} and pass it to brops_provision::provision_with_anchor() so the anchor's \
         key_id is admitted while the registry is being signed. It cannot be added later: \
         provisioning destroys the operator root before it returns, which is what seals the \
         registry. register_anchor_key() confirms the result and refuses if the order was \
         not kept. {}",
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

/// Confirm the signer's key is in the app's trusted-key registry — it can no longer put it there.
///
/// Takes the **published custody record**, never a key: the only fields read are `key_id`,
/// `public_key` and `authority`, and [`crate::custody::read_custody`] refuses a record carrying
/// anything secret.
///
/// # Why this stopped being a write
///
/// It used to read the registry, append an `audit-anchor` entry, re-sign the document with the
/// `operator-root` private half out of `<app_data>/trust/keys/`, raise the anti-rollback floor and
/// patch the provisioning manifest's digests. Every one of those steps was available to an
/// attacker who was the app's account, with a key of their choosing — the function WAS the attack,
/// written down. `brops_provision::mint` now destroys the operator root before provisioning
/// returns, so that private half does not exist, the registry cannot be re-signed by anybody, and
/// this can only check.
///
/// The key is admitted at mint time instead, by `brops_provision::provision_with_anchor`, from the
/// same published custody record. That is the whole reason the install order in the module doc has
/// the service starting BEFORE the app's first launch.
///
/// Returns the key id when the registry already carries this key under the `audit-anchor`
/// authority. Refuses, naming the remedy, when it does not — a store minted before the signer
/// existed cannot be amended into one that trusts it, and pretending otherwise would mean keeping
/// a key that can amend the registry, which is exactly what was removed.
pub fn register_anchor_key(anchor_dir: &Path, custody: &Value) -> Result<String, ProvisionError> {
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
            "the custody record does not claim the audit-anchor authority, so confirming it \
            would credit a key with an authority its own publisher never claimed",
        ));
    }

    // The ANCHOR directory, not the trust directory. The registry moved there with the pin and
    // the floor: `bro_signature.resolve_registry_root` refuses a registry root the reading
    // account can write, and this function has to look where the engine looks or it would be
    // confirming a document nothing reads.
    let registry_path = anchor_dir
        .join(brops_provision::REGISTRY_ROOT_DIR)
        .join("config")
        .join("trusted-keys.json");
    let document: Value = read_json(&registry_path)?;
    let entries = document
        .get("payload")
        .and_then(|p| p.get("keys"))
        .and_then(Value::as_array)
        .ok_or_else(|| corrupt("the trusted-key registry has no keys array"))?;

    let found = entries
        .iter()
        .find(|e| e.get("key_id").and_then(Value::as_str) == Some(key_id.as_str()));
    let entry = match found {
        Some(entry) => entry,
        None => {
            return Err(ProvisionError::Corrupt {
                what: format!(
                    "the trusted-key registry does not carry the audit signer's key {key_id}"
                ),
                detail: format!(
                    "The registry is signed by an operator-root private half that provisioning \
                    destroys before it returns, so it cannot be amended — not by this \
                    function, and not by anything that gets hold of the app's account. The \
                    anchor key has to be admitted while the registry is being signed, which \
                    means the signer service must be installed and started BEFORE the app's \
                    first launch (see install_plan). To adopt a signer that arrived later, or \
                    a rotated key, move the trust directory aside and let the next launch mint \
                    a new store. {REGISTRY_CAVEAT}"
                ),
            });
        }
    };
    // The registry could name the key under some other authority — one an attacker who could
    // write the registry would have chosen. Checking the id alone would report success for a key
    // `bro_audit_log` will refuse, which is the failure this whole item is about.
    if entry.get("authority_type").and_then(Value::as_str) != Some(spec::ANCHOR_AUTHORITY) {
        return Err(corrupt(
            "the registry names the audit signer's key under an authority that cannot anchor",
        ));
    }
    if entry.get("public_key").and_then(Value::as_str) != Some(public_key.as_str()) {
        return Err(corrupt(
            "the registry names the audit signer's key id against a DIFFERENT public key than \
            the one the signer published; the anchor it produces will not verify",
        ));
    }
    if entry.get("status").and_then(Value::as_str) != Some("active") {
        return Err(corrupt("the audit signer's key is in the registry but is not active"));
    }
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
