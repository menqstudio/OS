//! Behaviour of the first-launch trust provisioner: idempotence, atomicity, the
//! refusals, and the expiry decision.
//!
//! Byte-compatibility with the Python verifier is NOT proven here — a Rust test that
//! checks Rust's own encoding round-trips proves nothing about the thing that has to
//! accept it. That proof is `python_verifier.rs`, which runs the real
//! `engine/runtime/bro_signature.py` against this output.

use std::fs;
use std::path::Path;

use brops_provision as prov;
use serde_json::Value;

fn read_json(path: &Path) -> Value {
    serde_json::from_slice(&fs::read(path).expect("read")).expect("json")
}

fn sha256_of(path: &Path) -> String {
    prov::sha256_hex(&fs::read(path).expect("read"))
}

/// Rewrite `PROVISIONING.json` so the recorded digest of `relative` matches whatever
/// is on disk now. Used to prove a check is doing its own work rather than riding on
/// the digest map: with the digest repaired, only the later check can catch the change.
fn repair_digest(trust: &Path, relative: &str) {
    let manifest_path = trust.join(prov::MANIFEST_FILE);
    let mut manifest = read_json(&manifest_path);
    let mut path = trust.to_path_buf();
    for part in relative.split('/') {
        path.push(part);
    }
    let digest = sha256_of(&path);
    manifest["files"][relative] = Value::from(digest);
    fs::write(&manifest_path, serde_json::to_vec(&manifest).unwrap()).unwrap();
}

/// Replace a signed document with `payload`, re-signed by the REAL operator-root key,
/// and repair its recorded digest. Every check downstream of the signature then has to
/// catch the change on its own — which is the only way to prove those checks exist.
fn respin(trust: &Path, relative: &str, payload: Value) {
    let operator = prov::load_key(trust, "operator-root").expect("operator key");
    let document = prov::sign_document(&operator.signing, payload).expect("sign");
    let mut path = trust.to_path_buf();
    for part in relative.split('/') {
        path.push(part);
    }
    let mut bytes = serde_json::to_vec(&document).unwrap();
    bytes.push(b'\n');
    fs::write(&path, bytes).unwrap();
    repair_digest(trust, relative);
}

const REGISTRY_REL: &str = "registry/config/trusted-keys.json";
const SESSION_REL: &str = "artifacts/conductor-session.json";

fn payload_of(trust: &Path, relative: &str) -> Value {
    let mut path = trust.to_path_buf();
    for part in relative.split('/') {
        path.push(part);
    }
    read_json(&path)["payload"].clone()
}

fn staging_entries(data_dir: &Path) -> Vec<String> {
    fs::read_dir(data_dir)
        .unwrap()
        .filter_map(|e| e.ok())
        .map(|e| e.file_name().to_string_lossy().to_string())
        .filter(|n| n.starts_with(".trust-staging-"))
        .collect()
}

#[test]
fn first_launch_mints_one_key_per_authority_the_engine_knows() {
    let dir = tempfile::tempdir().unwrap();
    let p = prov::provision(dir.path()).expect("first launch provisions");
    assert!(p.freshly_minted);

    for authority in prov::AUTHORITY_TYPES {
        let key = p.keys_dir.join(format!("{authority}.json"));
        assert!(key.is_file(), "no private key minted for the {authority} authority");
    }

    let registry = read_json(&p.registry_path);
    let keys = registry["payload"]["keys"].as_array().unwrap();
    assert_eq!(
        keys.len(),
        prov::AUTHORITY_TYPES.len(),
        "the registry must carry exactly one key per authority"
    );
    for entry in keys {
        let authority = entry["authority_type"].as_str().unwrap();
        let allowed: Vec<String> = entry["allowed_artifact_types"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap().to_string())
            .collect();
        assert_eq!(
            allowed,
            prov::artifacts_for(authority),
            "the {authority} key must be granted exactly the artifact types bound to it"
        );
    }
}

#[test]
fn builder_and_verifier_keys_are_bound_to_distinct_agent_identities() {
    // `bro_completion._require_signer_identity` refuses an unbound builder/verifier
    // signature, and one identity on both keys would make "builder != verifier" a
    // string comparison a single key satisfies.
    let dir = tempfile::tempdir().unwrap();
    let p = prov::provision(dir.path()).unwrap();
    let registry = read_json(&p.registry_path);
    let mut subjects = Vec::new();
    for entry in registry["payload"]["keys"].as_array().unwrap() {
        let authority = entry["authority_type"].as_str().unwrap();
        if authority == "builder" || authority == "verifier" {
            let subject = entry["subject_agent_id"].as_str().unwrap_or_default().to_string();
            assert!(!subject.is_empty(), "{authority} key carries no subject_agent_id");
            subjects.push(subject);
        }
    }
    assert_eq!(subjects.len(), 2);
    assert_ne!(subjects[0], subjects[1], "builder and verifier must not share an identity");
}

#[test]
fn nothing_minted_ever_expires() {
    let dir = tempfile::tempdir().unwrap();
    let p = prov::provision(dir.path()).unwrap();
    let registry = read_json(&p.registry_path);
    for entry in registry["payload"]["keys"].as_array().unwrap() {
        assert_eq!(entry["not_before_epoch"].as_i64(), Some(prov::NOT_BEFORE_EPOCH));
        assert_eq!(
            entry["not_after_epoch"].as_i64(),
            Some(prov::NEVER_EXPIRES_EPOCH),
            "a key that expires is a key whose owner is eventually asked to renew it"
        );
    }
    let session = read_json(&p.conductor_session_path);
    assert_eq!(
        session["payload"]["expires_at_epoch"].as_i64(),
        Some(prov::NEVER_EXPIRES_EPOCH)
    );
}

#[test]
fn the_operator_pin_lives_outside_the_registry_root() {
    // `bro_signature._pin_from_file` refuses a pin lexically inside the root it
    // anchors, so a layout that nested them would fail closed at the engine.
    let dir = tempfile::tempdir().unwrap();
    let p = prov::provision(dir.path()).unwrap();
    assert!(
        !p.operator_pin_path.starts_with(&p.registry_root),
        "the pin {} is inside the registry root {}",
        p.operator_pin_path.display(),
        p.registry_root.display()
    );
    assert!(!p.registry_floor_path.starts_with(&p.registry_root));
}

#[test]
fn a_second_launch_verifies_and_never_re_mints() {
    let dir = tempfile::tempdir().unwrap();
    let first = prov::provision(dir.path()).unwrap();
    let key_before = fs::read(first.keys_dir.join("operator-root.json")).unwrap();
    let registry_before = fs::read(&first.registry_path).unwrap();

    let second = prov::provision(dir.path()).expect("second launch verifies");
    assert!(!second.freshly_minted, "a second launch must not mint");
    assert_eq!(first.install_id, second.install_id);
    assert_eq!(first.operator_public_key, second.operator_public_key);
    assert_eq!(key_before, fs::read(second.keys_dir.join("operator-root.json")).unwrap());
    assert_eq!(registry_before, fs::read(&second.registry_path).unwrap());
    assert!(staging_entries(dir.path()).is_empty());
}

#[test]
fn a_modified_registry_is_refused_by_name_and_nothing_is_repaired() {
    let dir = tempfile::tempdir().unwrap();
    let p = prov::provision(dir.path()).unwrap();
    let mut registry = read_json(&p.registry_path);
    registry["payload"]["issued_at_epoch"] = Value::from(1);
    fs::write(&p.registry_path, serde_json::to_vec(&registry).unwrap()).unwrap();

    let err = prov::provision(dir.path()).expect_err("a modified registry must be refused");
    let text = err.to_string();
    assert!(text.contains("no longer matches the digest recorded at install"), "{text}");
    assert!(text.contains("trusted-keys.json"), "{text}");
    // Refused, not repaired: the modification is still on disk for an operator to see.
    assert_eq!(read_json(&p.registry_path)["payload"]["issued_at_epoch"], Value::from(1));
}

#[test]
fn a_re_signed_registry_under_a_different_root_is_refused_even_with_the_digest_repaired() {
    let dir = tempfile::tempdir().unwrap();
    let p = prov::provision(dir.path()).unwrap();

    // Swap the pinned anchor for a different, perfectly valid Ed25519 public key and
    // repair its digest. Only the signature check can catch this.
    let other = prov::load_key(&p.trust_dir, "issuer").unwrap();
    fs::write(&p.operator_pin_path, format!("{}\n", other.public_key_hex())).unwrap();
    repair_digest(&p.trust_dir, &format!("{}/{}", prov::PIN_DIR, prov::OPERATOR_PIN_FILE));

    let err = prov::provision(dir.path()).expect_err("a swapped anchor must be refused");
    assert!(err.to_string().contains("does not verify against the operator-root pin"), "{err}");
}

#[test]
fn a_registry_signed_by_the_wrong_authority_is_refused_by_the_signature_check_alone() {
    // Everything else about this registry is impeccable: it declares the real pin, its
    // operator entry IS the pinned key, it is marked production, every authority is
    // active, and its recorded digest matches. Only the signature is wrong — signed by
    // the issuer key rather than the operator root. Nothing but the Ed25519 check can
    // catch it, which is what makes this test the one that proves that check exists.
    let dir = tempfile::tempdir().unwrap();
    let p = prov::provision(dir.path()).unwrap();
    let mut payload = payload_of(&p.trust_dir, REGISTRY_REL);
    payload["issued_at_epoch"] = Value::from(payload["issued_at_epoch"].as_i64().unwrap() + 1);
    let impostor = prov::load_key(&p.trust_dir, "issuer").unwrap();
    let document = prov::sign_document(&impostor.signing, payload).unwrap();
    fs::write(&p.registry_path, serde_json::to_vec(&document).unwrap()).unwrap();
    repair_digest(&p.trust_dir, REGISTRY_REL);

    let err = prov::provision(dir.path()).expect_err("a wrongly signed registry must be refused");
    assert!(err.to_string().contains("does not verify against the operator-root pin"), "{err}");
}

#[test]
fn a_registry_whose_operator_entry_is_not_the_pinned_key_is_refused() {
    // The payload still DECLARES the pinned key and is still signed by it, so the
    // declared-root check and the signature check both pass. What is wrong is the
    // operator-root ENTRY: `load_trusted_keys` refuses a registry that does not contain
    // its own signer, and a store that shipped one would fail at the engine instead.
    let dir = tempfile::tempdir().unwrap();
    let p = prov::provision(dir.path()).unwrap();
    let other = prov::load_key(&p.trust_dir, "issuer").unwrap();
    let mut payload = payload_of(&p.trust_dir, REGISTRY_REL);
    for entry in payload["keys"].as_array_mut().unwrap() {
        if entry["authority_type"] == Value::from("operator-root") {
            entry["public_key"] = Value::from(other.public_key_hex());
        }
    }
    respin(&p.trust_dir, REGISTRY_REL, payload);

    let err = prov::provision(dir.path()).expect_err("a registry without its signer must refuse");
    assert!(err.to_string().contains("operator-root key is not the pinned key"), "{err}");
}

#[test]
fn a_registry_that_stops_declaring_production_is_refused() {
    // `load_trusted_keys` refuses a non-production registry whenever the pin comes from
    // BRO_OPERATOR_ROOT_PUBKEY_FILE, which is the only pin path this deployment has. A
    // store that quietly lost the flag would pass here and fail at the engine.
    let dir = tempfile::tempdir().unwrap();
    let p = prov::provision(dir.path()).unwrap();
    let mut payload = payload_of(&p.trust_dir, REGISTRY_REL);
    payload["production"] = Value::from(false);
    respin(&p.trust_dir, REGISTRY_REL, payload);

    let err = prov::provision(dir.path()).expect_err("a non-production registry must be refused");
    assert!(err.to_string().contains("not marked production"), "{err}");
}

#[test]
fn a_registry_naming_an_operator_key_other_than_the_pin_is_refused() {
    let dir = tempfile::tempdir().unwrap();
    let p = prov::provision(dir.path()).unwrap();
    let other = prov::load_key(&p.trust_dir, "issuer").unwrap();
    let mut payload = payload_of(&p.trust_dir, REGISTRY_REL);
    payload["operator_public_key"] = Value::from(other.public_key_hex());
    respin(&p.trust_dir, REGISTRY_REL, payload);

    let err = prov::provision(dir.path()).expect_err("a mismatched declared root must be refused");
    assert!(err.to_string().contains("operator key other than the pinned one"), "{err}");
}

#[test]
fn a_revoked_authority_key_leaves_the_store_unusable_rather_than_silently_degraded() {
    let dir = tempfile::tempdir().unwrap();
    let p = prov::provision(dir.path()).unwrap();
    let mut payload = payload_of(&p.trust_dir, REGISTRY_REL);
    for entry in payload["keys"].as_array_mut().unwrap() {
        if entry["authority_type"] == Value::from("release") {
            entry["status"] = Value::from("revoked");
        }
    }
    respin(&p.trust_dir, REGISTRY_REL, payload);

    let err = prov::provision(dir.path()).expect_err("a missing active authority must be refused");
    let text = err.to_string();
    assert!(text.contains("no active key for an authority the engine knows"), "{text}");
    assert!(text.contains("release"), "{text}");
}

#[test]
fn an_expired_conductor_session_is_refused() {
    let dir = tempfile::tempdir().unwrap();
    let p = prov::provision(dir.path()).unwrap();
    let mut payload = payload_of(&p.trust_dir, SESSION_REL);
    payload["expires_at_epoch"] = Value::from(1);
    respin(&p.trust_dir, SESSION_REL, payload);

    let err = prov::provision(dir.path()).expect_err("an expired session token must be refused");
    assert!(err.to_string().contains("has expired"), "{err}");
}

#[test]
fn a_conductor_session_rebound_to_another_identity_is_refused() {
    let dir = tempfile::tempdir().unwrap();
    let p = prov::provision(dir.path()).unwrap();
    let mut payload = payload_of(&p.trust_dir, SESSION_REL);
    payload["role"] = Value::from("owner");
    respin(&p.trust_dir, SESSION_REL, payload);

    let err = prov::provision(dir.path()).expect_err("a rebound session token must be refused");
    let text = err.to_string();
    assert!(text.contains("does not bind what the engine checks"), "{text}");
    assert!(text.contains("role"), "{text}");
}

#[test]
fn a_manifest_of_an_unknown_schema_is_refused() {
    let dir = tempfile::tempdir().unwrap();
    let p = prov::provision(dir.path()).unwrap();
    let manifest_path = p.trust_dir.join(prov::MANIFEST_FILE);
    let mut manifest = read_json(&manifest_path);
    manifest["schema"] = Value::from(2);
    fs::write(&manifest_path, serde_json::to_vec(&manifest).unwrap()).unwrap();

    let err = prov::provision(dir.path()).expect_err("an unknown manifest schema must be refused");
    assert!(err.to_string().contains("not schema 1"), "{err}");
}

#[test]
fn a_deleted_authority_key_is_refused_by_name() {
    let dir = tempfile::tempdir().unwrap();
    let p = prov::provision(dir.path()).unwrap();
    fs::remove_file(p.keys_dir.join("recovery.json")).unwrap();
    let err = prov::provision(dir.path()).expect_err("a missing key must be refused");
    let text = err.to_string();
    assert!(text.contains("re-hashing a provisioned file"), "{text}");
    assert!(text.contains("recovery.json"), "{text}");
}

#[test]
fn dropping_a_manifest_entry_cannot_smuggle_a_file_past_the_digest_check() {
    let dir = tempfile::tempdir().unwrap();
    let p = prov::provision(dir.path()).unwrap();
    let manifest_path = p.trust_dir.join(prov::MANIFEST_FILE);
    let mut manifest = read_json(&manifest_path);
    manifest["files"].as_object_mut().unwrap().remove("keys/verifier.json");
    fs::write(&manifest_path, serde_json::to_vec(&manifest).unwrap()).unwrap();

    let err = prov::provision(dir.path()).expect_err("an uncovered file must be refused");
    let text = err.to_string();
    assert!(text.contains("does not cover every provisioned file"), "{text}");
    assert!(text.contains("keys/verifier.json"), "{text}");
}

#[test]
fn something_already_at_the_trust_path_is_refused_and_never_minted_over() {
    // `std::fs::rename` on Windows carries MOVEFILE_REPLACE_EXISTING, so a staging
    // directory renamed over a FILE lands there — while unix fails with ENOTDIR. The
    // decision is therefore made before anything is minted, identically on both.
    let dir = tempfile::tempdir().unwrap();
    fs::write(dir.path().join(prov::TRUST_DIR), b"in the way").unwrap();

    let err = prov::provision(dir.path()).expect_err("an occupied trust path must be refused");
    assert!(err.to_string().contains("not a provisioned store"), "{err}");
    assert_eq!(
        fs::read(dir.path().join(prov::TRUST_DIR)).unwrap(),
        b"in the way",
        "the occupant must be left exactly as it was"
    );
    assert!(staging_entries(dir.path()).is_empty());
}

#[test]
fn a_half_removed_store_is_refused_rather_than_completed() {
    let dir = tempfile::tempdir().unwrap();
    let p = prov::provision(dir.path()).unwrap();
    fs::remove_file(p.trust_dir.join(prov::MANIFEST_FILE)).unwrap();

    let err = prov::provision(dir.path()).expect_err("a manifest-less store must be refused");
    assert!(err.to_string().contains("not a provisioned store"), "{err}");
    assert!(
        p.keys_dir.join("operator-root.json").is_file(),
        "the surviving key material must not be minted over"
    );
    assert!(staging_entries(dir.path()).is_empty());
}

#[test]
fn a_successful_mint_leaves_no_staging_directory() {
    let dir = tempfile::tempdir().unwrap();
    prov::provision(dir.path()).unwrap();
    assert!(staging_entries(dir.path()).is_empty());
}

#[test]
fn the_floor_anchor_is_minted_only_on_demand_and_refuses_a_non_positive_sequence() {
    let dir = tempfile::tempdir().unwrap();
    let p = prov::provision(dir.path()).unwrap();

    // O-5's anchor is per (task, sequence) and is never a startup side effect.
    let artifacts = fs::read_dir(p.trust_dir.join(prov::ARTIFACTS_DIR)).unwrap().count();
    assert_eq!(artifacts, 1, "provisioning must mint exactly the conductor-session artifact");

    let out = dir.path().join("anchor.json");
    assert!(prov::mint_floor_anchor(&p.trust_dir, "t-001", 0, &out).is_err());
    assert!(!out.exists(), "a refused anchor must not be written");

    let doc = prov::mint_floor_anchor(&p.trust_dir, "t-001", 7, &out).unwrap();
    assert_eq!(doc["payload"]["artifact_type"], Value::from("evidence-floor-anchor"));
    assert_eq!(doc["payload"]["task_id"], Value::from("t-001"));
    assert_eq!(doc["payload"]["head_sequence"], Value::from(7));
    assert_eq!(doc["payload"]["key_id"], Value::from(p.operator_key_id.clone()));
    assert!(out.is_file());
}

#[test]
fn the_manifest_records_what_the_platform_actually_did_about_permissions() {
    let dir = tempfile::tempdir().unwrap();
    let p = prov::provision(dir.path()).unwrap();
    let manifest = read_json(&p.trust_dir.join(prov::MANIFEST_FILE));
    let recorded = manifest["key_file_protection"].as_str().unwrap();
    assert_eq!(recorded, prov::key_file_protection().to_string());
    if cfg!(unix) {
        assert!(recorded.contains("chmod 0600"), "{recorded}");
    } else {
        // Not a skip: the honest statement that no explicit permission was applied.
        assert!(recorded.contains("NO explicit permission"), "{recorded}");
        assert!(recorded.contains(prov::platform_name()), "{recorded}");
    }
}

#[cfg(unix)]
#[test]
fn private_key_material_is_owner_only_on_posix() {
    use std::os::unix::fs::PermissionsExt;
    let dir = tempfile::tempdir().unwrap();
    let p = prov::provision(dir.path()).unwrap();
    for authority in prov::AUTHORITY_TYPES {
        let mode = fs::metadata(p.keys_dir.join(format!("{authority}.json")))
            .unwrap()
            .permissions()
            .mode()
            & 0o777;
        assert_eq!(mode, 0o600, "{authority} key is mode {mode:04o}");
    }
    let dir_mode = fs::metadata(&p.keys_dir).unwrap().permissions().mode() & 0o777;
    assert_eq!(dir_mode, 0o700);
}
