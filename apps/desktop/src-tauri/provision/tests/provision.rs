//! Behaviour of the first-launch trust provisioner: idempotence, atomicity, the
//! refusals, and the expiry decision.
//!
//! Byte-compatibility with the Python verifier is NOT proven here — a Rust test that
//! checks Rust's own encoding round-trips proves nothing about the thing that has to
//! accept it. That proof is `python_verifier.rs`, which runs the real
//! `engine/runtime/bro_signature.py` against this output.

use std::fs;
use std::path::{Path, PathBuf};

use brops_provision as prov;
use ed25519_dalek::SigningKey;
use serde_json::Value;

/// Where these tests put the trust anchor: a sibling of the trust directory, inside the same
/// temporary application-data directory.
///
/// # Why these tests use the UNSEALED entry points, and what that costs
///
/// `prov::provision` seals the anchor — it applies a PROTECTED DACL whose OWNER RIGHTS ACE
/// leaves the creating account read and execute and nothing else. That is one-way for the
/// account that applies it, which is the property and not an oversight: this process cannot
/// afterwards write the directory, delete what is in it, or remove it. A test that sealed a
/// fresh anchor on every run would leave a directory on the machine that nothing running as
/// the test's own account could ever clear, and it would have to live under `%ProgramData%`
/// (the ancestor check refuses a temporary directory, correctly).
///
/// So the mint and the verifier are exercised here through
/// `mint_store_without_custody_proof` / `verify_store_without_custody_proof`, which do
/// everything except establish custody. **The custody property is not tested in this file.**
/// It is tested against a real sealed directory, with the real operating system refusing the
/// real writes, in `tests/anchor_custody.rs`, and end to end against the real
/// `bro_audit_log.verify()` in `audit-signer/tests/anchor_end_to_end.rs`. A store produced
/// here carries `custody: None`, and `custody_is_absent_from_the_unsealed_entry_points`
/// asserts that it does, so the two halves cannot be confused for one another.
fn anchor_of(trust: &Path) -> PathBuf {
    trust.parent().expect("the trust directory has a parent").join("anchor")
}

/// `prov::provision`, minus the seal and the proof. See [`anchor_of`].
fn mint_at(app_data: &Path) -> Result<prov::Provisioned, prov::ProvisionError> {
    prov::mint_store_without_custody_proof(app_data, &app_data.join("anchor"), None)
}

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
    // The manifest covers the APP-SIDE half only. A document that lives in the anchor has no
    // digest to repair — the manifest sits beside it, in the same directory the account being
    // policed cannot write, so a digest of its neighbour would prove nothing its location does
    // not already prove. Returning quietly rather than inserting a stray entry matters:
    // `verify_store` refuses a manifest that names a file the mint does not write.
    if !document_root(trust, relative).ends_with(prov::TRUST_DIR) {
        return;
    }
    let manifest_path = anchor_of(trust).join(prov::MANIFEST_FILE);
    let mut manifest = read_json(&manifest_path);
    let mut path = trust.to_path_buf();
    for part in relative.split('/') {
        path.push(part);
    }
    let digest = sha256_of(&path);
    manifest["files"][relative] = Value::from(digest);
    fs::write(&manifest_path, serde_json::to_vec(&manifest).unwrap()).unwrap();
}

/// Install a NEW operator root over a provisioned store, and return it.
///
/// # Why the tests need this, and what it incidentally proves
///
/// Several checks in `verify_existing` sit DOWNSTREAM of the registry signature — the
/// production flag, the per-authority entries, the operator entry matching the pin, the
/// conductor session's bindings. Reaching them needs a registry that verifies and is
/// wrong in exactly one other way, i.e. a validly re-signed one. There is no longer a key
/// to do that with: `mint` destroys the operator root before it returns.
///
/// So this does what the only remaining party who could do it would do — it rewrites the
/// PIN. A fresh Ed25519 key is minted, `pin/operator-root.pub` is replaced with its public
/// half, the registry's `operator_public_key` and its `operator-root` entry are rebuilt
/// around it, the registry and the conductor session are re-signed under it, and every
/// digest is repaired. The store then verifies again — asserted here, so that when a test
/// mutates one field afterwards and gets a refusal, the refusal can only be about that
/// field.
///
/// That it works at all is the residual this round did not close, exercised in Rust as
/// well as in `audit-signer/tests/anchor_end_to_end.py` (`case_pin_rewrite`): destroying
/// the operator root removed the KEY, not the anchor's custody. The pin is still a file in
/// a directory the app's own account owns.
fn reroot(trust: &Path) -> SigningKey {
    let root = SigningKey::from_bytes(&throwaway_seed());
    let public = prov::hex(root.verifying_key().as_bytes());

    fs::write(anchor_of(trust).join(prov::OPERATOR_PIN_FILE), format!("{public}\n")).unwrap();
    // No digest to repair: the pin is not in the manifest's `files` map any more. It cannot be
    // — the manifest sits BESIDE it, in the same sealed directory, and a digest a document
    // records of its own neighbour proves nothing that the neighbour's location does not
    // already prove. What the manifest covers is the app-writable half.

    let mut payload = payload_of(trust, REGISTRY_REL);
    payload["operator_public_key"] = Value::from(public.clone());
    for entry in payload["keys"].as_array_mut().unwrap() {
        if entry["authority_type"] == Value::from("operator-root") {
            entry["public_key"] = Value::from(public.clone());
        }
    }
    respin(trust, &root, REGISTRY_REL, payload);
    // The session names the operator ENTRY's key_id, which reroot leaves alone, so it
    // only needs a signature under the new root.
    let session = payload_of(trust, SESSION_REL);
    respin(trust, &root, SESSION_REL, session);

    prov::verify_store_without_custody_proof(trust, &anchor_of(trust)).expect(
        "a store re-rooted through the pin must verify — otherwise a later refusal in \
         this test could be about the re-rooting rather than about the mutation",
    );
    root
}

/// A throwaway 32-byte seed. Not key material anyone relies on: these keys exist for one
/// test each, so there is no reason to pull in an RNG crate for them.
fn throwaway_seed() -> [u8; 32] {
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .subsec_nanos();
    let mut seed = [0u8; 32];
    for (i, byte) in seed.iter_mut().enumerate() {
        *byte = (i as u32).wrapping_mul(31).wrapping_add(nanos).to_le_bytes()[i % 4];
    }
    seed[0] |= 1;
    seed
}

/// Replace a signed document with `payload`, re-signed by `root`, and repair its recorded
/// digest. Every check downstream of the signature then has to catch the change on its
/// own — which is the only way to prove those checks exist.
fn respin(trust: &Path, root: &SigningKey, relative: &str, payload: Value) {
    let document = prov::sign_document(root, payload).expect("sign");
    let mut path = document_root(trust, relative);
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

/// Which of the two halves a signed document lives in.
///
/// The registry moved into the ANCHOR with the pin and the floor:
/// `bro_signature.resolve_registry_root` refuses a registry root the reading account can write,
/// and that refusal only became visible once the deployment stopped setting
/// `BRO_OPERATOR_ROOT_PIN_SELF_OWNED`, which short-circuits every custody rule in the runtime
/// at once. The conductor-session artifact stays in the app-side store, where it is bound by a
/// digest the manifest records from the anchor.
fn document_root(trust: &Path, relative: &str) -> PathBuf {
    if relative.starts_with("registry/") {
        anchor_of(trust)
    } else {
        trust.to_path_buf()
    }
}

fn payload_of(trust: &Path, relative: &str) -> Value {
    let mut path = document_root(trust, relative);
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
    let p = mint_at(dir.path()).expect("first launch provisions");
    assert!(p.freshly_minted);

    for authority in prov::RETAINED_AUTHORITIES {
        let key = p.keys_dir.join(format!("{authority}.json"));
        assert!(key.is_file(), "no private key minted for the {authority} authority");
    }
    // The registry names one key per MINTED authority; the key DIRECTORY holds only the
    // retained ones. The difference is exactly `operator-root`, and it is the point.
    assert_eq!(
        fs::read_dir(&p.keys_dir).unwrap().count(),
        prov::RETAINED_AUTHORITIES.len(),
        "the key directory must hold the retained authorities and nothing else"
    );

    let registry = read_json(&p.registry_path);
    let keys = registry["payload"]["keys"].as_array().unwrap();
    assert_eq!(
        keys.len(),
        prov::MINTED_AUTHORITIES.len(),
        "the registry must carry exactly one key per minted authority"
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
    let p = mint_at(dir.path()).unwrap();
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
    let p = mint_at(dir.path()).unwrap();
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
    let p = mint_at(dir.path()).unwrap();
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
    let first = mint_at(dir.path()).unwrap();
    let key_before = fs::read(first.keys_dir.join("issuer.json")).unwrap();
    let registry_before = fs::read(&first.registry_path).unwrap();

    let second = mint_at(dir.path()).expect("second launch verifies");
    assert!(!second.freshly_minted, "a second launch must not mint");
    assert_eq!(first.install_id, second.install_id);
    assert_eq!(first.operator_public_key, second.operator_public_key);
    assert_eq!(key_before, fs::read(second.keys_dir.join("issuer.json")).unwrap());
    assert_eq!(registry_before, fs::read(&second.registry_path).unwrap());
    assert!(staging_entries(dir.path()).is_empty());
}

/// A modified registry is refused — and WHICH check refuses it moved, deliberately.
///
/// It used to be the manifest digest: the registry lived in the app-side store, the manifest
/// recorded its sha256, and `verify_existing` caught the edit before it ever looked at a
/// signature. The registry now lives in the ANCHOR, beside the manifest, because
/// `bro_signature.resolve_registry_root` refuses a registry root the reading account can write.
/// A digest a document records of its own neighbour buys nothing that the neighbour's location
/// does not already buy, so the registry is no longer in the manifest's `files` map and the
/// Ed25519 check against the pin is what refuses.
///
/// That is not a layer lost. The layer it replaced was defence against the ACCOUNT rewriting the
/// registry, and that account can no longer open the file at all — proved by the operating
/// system in `audit-signer/tests/anchor_end_to_end.py`, which attempts exactly this write and is
/// refused with `PermissionError`. What this test now covers is the remaining case: an
/// administrator, or a restore from backup, putting a different document there.
#[test]
fn a_modified_registry_is_refused_by_name_and_nothing_is_repaired() {
    let dir = tempfile::tempdir().unwrap();
    let p = mint_at(dir.path()).unwrap();
    let mut registry = read_json(&p.registry_path);
    registry["payload"]["issued_at_epoch"] = Value::from(1);
    fs::write(&p.registry_path, serde_json::to_vec(&registry).unwrap()).unwrap();

    let err = mint_at(dir.path()).expect_err("a modified registry must be refused");
    let text = err.to_string();
    assert!(text.contains("does not verify against the operator-root pin"), "{text}");
    // Refused, not repaired: the modification is still on disk for an operator to see.
    assert_eq!(read_json(&p.registry_path)["payload"]["issued_at_epoch"], Value::from(1));
}

#[test]
fn a_re_signed_registry_under_a_different_root_is_refused_even_with_the_digest_repaired() {
    let dir = tempfile::tempdir().unwrap();
    let p = mint_at(dir.path()).unwrap();

    // Swap the pinned anchor for a different, perfectly valid Ed25519 public key and
    // repair its digest. Only the signature check can catch this.
    let other = prov::load_key(&p.trust_dir, "issuer").unwrap();
    fs::write(&p.operator_pin_path, format!("{}\n", other.public_key_hex())).unwrap();
    // Nothing to repair: the pin is not in the manifest digest map any more (it lives beside
    // the manifest, in the anchor), so ONLY the signature check stands between a swapped pin
    // and an accepted registry - which is exactly what this test is for.

    let err = mint_at(dir.path()).expect_err("a swapped anchor must be refused");
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
    let p = mint_at(dir.path()).unwrap();
    let mut payload = payload_of(&p.trust_dir, REGISTRY_REL);
    payload["issued_at_epoch"] = Value::from(payload["issued_at_epoch"].as_i64().unwrap() + 1);
    let impostor = prov::load_key(&p.trust_dir, "issuer").unwrap();
    let document = prov::sign_document(&impostor.signing, payload).unwrap();
    fs::write(&p.registry_path, serde_json::to_vec(&document).unwrap()).unwrap();
    repair_digest(&p.trust_dir, REGISTRY_REL);

    let err = mint_at(dir.path()).expect_err("a wrongly signed registry must be refused");
    assert!(err.to_string().contains("does not verify against the operator-root pin"), "{err}");
}

#[test]
fn a_registry_whose_operator_entry_is_not_the_pinned_key_is_refused() {
    // The payload still DECLARES the pinned key and is still signed by it, so the
    // declared-root check and the signature check both pass. What is wrong is the
    // operator-root ENTRY: `load_trusted_keys` refuses a registry that does not contain
    // its own signer, and a store that shipped one would fail at the engine instead.
    let dir = tempfile::tempdir().unwrap();
    let p = mint_at(dir.path()).unwrap();
    let root = reroot(&p.trust_dir);
    let other = prov::load_key(&p.trust_dir, "issuer").unwrap();
    let mut payload = payload_of(&p.trust_dir, REGISTRY_REL);
    for entry in payload["keys"].as_array_mut().unwrap() {
        if entry["authority_type"] == Value::from("operator-root") {
            entry["public_key"] = Value::from(other.public_key_hex());
        }
    }
    respin(&p.trust_dir, &root, REGISTRY_REL, payload);

    let err = mint_at(dir.path()).expect_err("a registry without its signer must refuse");
    assert!(err.to_string().contains("operator-root key is not the pinned key"), "{err}");
}

#[test]
fn a_registry_that_stops_declaring_production_is_refused() {
    // `load_trusted_keys` refuses a non-production registry whenever the pin comes from
    // BRO_OPERATOR_ROOT_PUBKEY_FILE, which is the only pin path this deployment has. A
    // store that quietly lost the flag would pass here and fail at the engine.
    let dir = tempfile::tempdir().unwrap();
    let p = mint_at(dir.path()).unwrap();
    let root = reroot(&p.trust_dir);
    let mut payload = payload_of(&p.trust_dir, REGISTRY_REL);
    payload["production"] = Value::from(false);
    respin(&p.trust_dir, &root, REGISTRY_REL, payload);

    let err = mint_at(dir.path()).expect_err("a non-production registry must be refused");
    assert!(err.to_string().contains("not marked production"), "{err}");
}

#[test]
fn a_registry_naming_an_operator_key_other_than_the_pin_is_refused() {
    let dir = tempfile::tempdir().unwrap();
    let p = mint_at(dir.path()).unwrap();
    let root = reroot(&p.trust_dir);
    let other = prov::load_key(&p.trust_dir, "issuer").unwrap();
    let mut payload = payload_of(&p.trust_dir, REGISTRY_REL);
    payload["operator_public_key"] = Value::from(other.public_key_hex());
    respin(&p.trust_dir, &root, REGISTRY_REL, payload);

    let err = mint_at(dir.path()).expect_err("a mismatched declared root must be refused");
    assert!(err.to_string().contains("operator key other than the pinned one"), "{err}");
}

#[test]
fn a_revoked_authority_key_leaves_the_store_unusable_rather_than_silently_degraded() {
    let dir = tempfile::tempdir().unwrap();
    let p = mint_at(dir.path()).unwrap();
    let root = reroot(&p.trust_dir);
    let mut payload = payload_of(&p.trust_dir, REGISTRY_REL);
    for entry in payload["keys"].as_array_mut().unwrap() {
        if entry["authority_type"] == Value::from("release") {
            entry["status"] = Value::from("revoked");
        }
    }
    respin(&p.trust_dir, &root, REGISTRY_REL, payload);

    let err = mint_at(dir.path()).expect_err("a missing active authority must be refused");
    let text = err.to_string();
    assert!(text.contains("no active key for an authority the engine knows"), "{text}");
    assert!(text.contains("release"), "{text}");
}

#[test]
fn an_expired_conductor_session_is_refused() {
    let dir = tempfile::tempdir().unwrap();
    let p = mint_at(dir.path()).unwrap();
    let root = reroot(&p.trust_dir);
    let mut payload = payload_of(&p.trust_dir, SESSION_REL);
    payload["expires_at_epoch"] = Value::from(1);
    respin(&p.trust_dir, &root, SESSION_REL, payload);

    let err = mint_at(dir.path()).expect_err("an expired session token must be refused");
    assert!(err.to_string().contains("has expired"), "{err}");
}

#[test]
fn a_conductor_session_rebound_to_another_identity_is_refused() {
    let dir = tempfile::tempdir().unwrap();
    let p = mint_at(dir.path()).unwrap();
    let root = reroot(&p.trust_dir);
    let mut payload = payload_of(&p.trust_dir, SESSION_REL);
    payload["role"] = Value::from("owner");
    respin(&p.trust_dir, &root, SESSION_REL, payload);

    let err = mint_at(dir.path()).expect_err("a rebound session token must be refused");
    let text = err.to_string();
    assert!(text.contains("does not bind what the engine checks"), "{text}");
    assert!(text.contains("role"), "{text}");
}

#[test]
fn a_manifest_of_an_unknown_schema_is_refused() {
    let dir = tempfile::tempdir().unwrap();
    let p = mint_at(dir.path()).unwrap();
    let manifest_path = p.anchor_dir.join(prov::MANIFEST_FILE);
    let mut manifest = read_json(&manifest_path);
    manifest["schema"] = Value::from(2);
    fs::write(&manifest_path, serde_json::to_vec(&manifest).unwrap()).unwrap();

    let err = mint_at(dir.path()).expect_err("an unknown manifest schema must be refused");
    assert!(err.to_string().contains("not schema 1"), "{err}");
}

#[test]
fn a_deleted_authority_key_is_refused_by_name() {
    let dir = tempfile::tempdir().unwrap();
    let p = mint_at(dir.path()).unwrap();
    fs::remove_file(p.keys_dir.join("recovery.json")).unwrap();
    let err = mint_at(dir.path()).expect_err("a missing key must be refused");
    let text = err.to_string();
    assert!(text.contains("re-hashing a provisioned file"), "{text}");
    assert!(text.contains("recovery.json"), "{text}");
}

#[test]
fn dropping_a_manifest_entry_cannot_smuggle_a_file_past_the_digest_check() {
    let dir = tempfile::tempdir().unwrap();
    let p = mint_at(dir.path()).unwrap();
    let manifest_path = p.anchor_dir.join(prov::MANIFEST_FILE);
    let mut manifest = read_json(&manifest_path);
    manifest["files"].as_object_mut().unwrap().remove("keys/verifier.json");
    fs::write(&manifest_path, serde_json::to_vec(&manifest).unwrap()).unwrap();

    let err = mint_at(dir.path()).expect_err("an uncovered file must be refused");
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

    let err = mint_at(dir.path()).expect_err("an occupied trust path must be refused");
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
    let p = mint_at(dir.path()).unwrap();
    fs::remove_file(p.anchor_dir.join(prov::MANIFEST_FILE)).unwrap();

    let err = mint_at(dir.path()).expect_err("a manifest-less store must be refused");
    assert!(err.to_string().contains("not a provisioned store"), "{err}");
    assert!(
        p.keys_dir.join("issuer.json").is_file(),
        "the surviving key material must not be minted over"
    );
    assert!(staging_entries(dir.path()).is_empty());
}

#[test]
fn a_successful_mint_leaves_no_staging_directory() {
    let dir = tempfile::tempdir().unwrap();
    mint_at(dir.path()).unwrap();
    assert!(staging_entries(dir.path()).is_empty());
}

#[test]
fn the_floor_anchor_is_minted_only_on_demand_and_refuses_a_non_positive_sequence() {
    let dir = tempfile::tempdir().unwrap();
    let p = mint_at(dir.path()).unwrap();

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
    // The DELEGATED key, not the operator root — which no longer exists. If this ever
    // reads `p.operator_key_id` again, either the root survived provisioning or the
    // artifact moved back onto it, and both undo the whole round.
    let delegated = prov::load_key(&p.trust_dir, prov::EVIDENCE_FLOOR).unwrap();
    assert_eq!(doc["payload"]["key_id"], Value::from(delegated.key_id.clone()));
    assert_ne!(doc["payload"]["key_id"], Value::from(p.operator_key_id.clone()));
    assert!(out.is_file());
}

#[test]
fn the_control_room_command_is_signed_by_its_own_delegated_key_and_binds_the_command() {
    // O-4. `bro_control_room_api._prove_command_actor` verifies the artifact and then
    // requires command_id/task_id/command to equal the command in hand, so an artifact
    // that did not carry all three would be a session credential wearing another name.
    let dir = tempfile::tempdir().unwrap();
    let p = mint_at(dir.path()).unwrap();
    let out = dir.path().join("command.json");

    let expires = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs() as i64
        + 3600;
    let doc = prov::mint_control_room_command(
        &p.trust_dir,
        "cmd-1",
        "t-001",
        "cancel",
        "s-owner",
        expires,
        &out,
    )
    .unwrap();
    assert_eq!(doc["payload"]["artifact_type"], Value::from("control-room-command"));
    for (field, value) in
        [("command_id", "cmd-1"), ("task_id", "t-001"), ("command", "cancel"),
         ("role", "owner"), ("agent_id", "owner-gev")]
    {
        assert_eq!(doc["payload"][field], Value::from(value), "{field}");
    }
    let delegated = prov::load_key(&p.trust_dir, prov::CONTROL_ROOM).unwrap();
    assert_eq!(doc["payload"]["key_id"], Value::from(delegated.key_id.clone()));
    assert_ne!(doc["payload"]["key_id"], Value::from(p.operator_key_id.clone()));

    // An expiry that is not in the future, and an unbound field, are refusals — a
    // never-expiring per-command attestation is a bearer token for that command forever.
    let bad = dir.path().join("bad.json");
    assert!(prov::mint_control_room_command(
        &p.trust_dir, "cmd-1", "t-001", "cancel", "s-owner", 1, &bad
    )
    .is_err());
    assert!(prov::mint_control_room_command(
        &p.trust_dir, "", "t-001", "cancel", "s-owner", expires, &bad
    )
    .is_err());
    assert!(!bad.exists(), "a refused artifact must not be written");
}

#[test]
fn the_two_delegated_keys_are_separate_and_neither_can_reach_the_others_artifact() {
    // One shared "local delegate" key would be strictly more powerful than either
    // delegation, and would leave `verify_artifact`'s authority check with nothing to
    // say. The registry grant is the thing the engine reads, so it is what is asserted.
    let dir = tempfile::tempdir().unwrap();
    let p = mint_at(dir.path()).unwrap();
    let control = prov::load_key(&p.trust_dir, prov::CONTROL_ROOM).unwrap();
    let floor = prov::load_key(&p.trust_dir, prov::EVIDENCE_FLOOR).unwrap();
    assert_ne!(control.public_key_hex(), floor.public_key_hex());

    let registry = read_json(&p.registry_path);
    let mut seen = 0;
    for entry in registry["payload"]["keys"].as_array().unwrap() {
        match entry["authority_type"].as_str().unwrap() {
            "control-room" => {
                seen += 1;
                assert_eq!(entry["allowed_artifact_types"], Value::from(vec!["control-room-command"]));
            }
            "evidence-floor" => {
                seen += 1;
                assert_eq!(entry["allowed_artifact_types"], Value::from(vec!["evidence-floor-anchor"]));
            }
            // And the root itself keeps only what a root should: nothing routine.
            "operator-root" => {
                let allowed = entry["allowed_artifact_types"].as_array().unwrap();
                for forbidden in ["control-room-command", "evidence-floor-anchor"] {
                    assert!(
                        !allowed.iter().any(|v| v == forbidden),
                        "the operator root is still granted {forbidden}"
                    );
                }
            }
            _ => {}
        }
    }
    assert_eq!(seen, 2, "both delegated authorities must be in the registry");
}

/// **Requirement 1**, asked of the filesystem rather than of the code that writes it.
///
/// Every byte of the whole application data directory is enumerated — not just
/// `keys/`, and not just the files the manifest names — and every 32-byte window and
/// every 64-character hex run in each is tried AS AN ED25519 SEED. If any of them
/// derives the pinned operator public key, the private half is on disk somewhere,
/// whatever the file is called and whatever encoding it used.
///
/// A test that looked for `keys/operator-root.json` would pass the day the seed moved
/// to a temp file, a log line or a staging directory nobody cleaned up.
#[test]
fn no_operator_root_private_half_exists_anywhere_on_disk() {
    let dir = tempfile::tempdir().unwrap();
    let p = mint_at(dir.path()).unwrap();
    let target = p.operator_public_key.clone();

    // The control: the same search DOES find every retained key, so a negative result
    // below cannot be the search being broken.
    let mut found_retained = 0;
    for authority in prov::RETAINED_AUTHORITIES {
        let key = prov::load_key(&p.trust_dir, authority).unwrap();
        if seed_for(dir.path(), &key.public_key_hex()).is_some() {
            found_retained += 1;
        }
    }
    assert_eq!(
        found_retained,
        prov::RETAINED_AUTHORITIES.len(),
        "the search did not find the keys that ARE on disk, so finding nothing for the \
         operator root would prove nothing"
    );

    if let Some(where_) = seed_for(dir.path(), &target) {
        panic!(
            "the operator-root private half survived provisioning, in {}. The registry can \
             therefore still be re-signed by whoever holds this directory.",
            where_.display()
        );
    }
}

/// Search every file under `root` for a 32-byte seed deriving `public_key_hex`.
fn seed_for(root: &Path, public_key_hex: &str) -> Option<std::path::PathBuf> {
    let mut stack = vec![root.to_path_buf()];
    while let Some(path) = stack.pop() {
        let meta = match fs::symlink_metadata(&path) {
            Ok(m) => m,
            Err(_) => continue,
        };
        if meta.is_dir() {
            for entry in fs::read_dir(&path).into_iter().flatten().flatten() {
                stack.push(entry.path());
            }
            continue;
        }
        let bytes = match fs::read(&path) {
            Ok(b) => b,
            Err(_) => continue,
        };
        if bytes_hold_seed(&bytes, public_key_hex) {
            return Some(path);
        }
    }
    None
}

fn bytes_hold_seed(bytes: &[u8], public_key_hex: &str) -> bool {
    // Raw: any 32-byte window.
    for window in bytes.windows(32) {
        let seed: [u8; 32] = window.try_into().unwrap();
        if prov::hex(SigningKey::from_bytes(&seed).verifying_key().as_bytes()) == public_key_hex {
            return true;
        }
    }
    // Hex: any 64-character run of hex digits, which is how this module writes seeds.
    let text = String::from_utf8_lossy(bytes);
    let chars: Vec<char> = text.chars().collect();
    for start in 0..chars.len().saturating_sub(63) {
        let run: String = chars[start..start + 64].iter().collect();
        if !run.chars().all(|c| c.is_ascii_hexdigit()) {
            continue;
        }
        if let Some(raw) = prov::unhex(&run) {
            let seed: [u8; 32] = match raw.try_into() {
                Ok(s) => s,
                Err(_) => continue,
            };
            if prov::hex(SigningKey::from_bytes(&seed).verifying_key().as_bytes())
                == public_key_hex
            {
                return true;
            }
        }
    }
    false
}

#[test]
fn a_store_that_grows_an_operator_root_key_file_afterwards_is_refused() {
    // The digest map cannot see this: a file the mint never wrote adds no digest to
    // compare and removes none. Without the key-directory check the store would go on
    // verifying with a registry-signing key sitting beside it.
    let dir = tempfile::tempdir().unwrap();
    let p = mint_at(dir.path()).unwrap();
    let planted = p.keys_dir.join("operator-root.json");
    fs::write(&planted, br#"{"key_id":"planted","private_key":"00"}"#).unwrap();

    let err = mint_at(dir.path()).expect_err("a planted root key must be refused");
    let text = err.to_string();
    assert!(text.contains("private key material provisioning never wrote"), "{text}");
    assert!(text.contains("operator-root.json"), "{text}");
    assert!(planted.is_file(), "refused, not repaired");
}

#[test]
fn the_manifest_states_what_became_of_the_operator_root_without_overclaiming() {
    let dir = tempfile::tempdir().unwrap();
    let p = mint_at(dir.path()).unwrap();
    let manifest = read_json(&p.anchor_dir.join(prov::MANIFEST_FILE));
    let custody = manifest["operator_root_custody"].as_str().unwrap();
    assert_eq!(custody, prov::OPERATOR_ROOT_CUSTODY);
    assert!(custody.contains("destroyed"), "{custody}");
    // And the second half, which matters as much: the anchor did NOT move out of reach.
    assert!(custody.contains("does NOT make the trust root external"), "{custody}");
    let posture = fs::read_to_string(p.trust_dir.join(prov::POSTURE_FILE)).unwrap();
    assert!(posture.contains("OPERATOR-ROOT PRIVATE HALF IS NOT HERE"), "{posture}");
    assert!(posture.contains("did NOT move the trust anchor"), "{posture}");
}

#[test]
fn an_anchor_key_is_admitted_at_mint_time_and_only_when_its_publisher_claims_it() {
    let dir = tempfile::tempdir().unwrap();
    let custody = serde_json::json!({
        "key_id": "brops-anchor-1",
        "public_key": "ab".repeat(32),
        "authority": "audit-anchor",
    });
    let p = prov::mint_store_without_custody_proof(dir.path(), &dir.path().join("anchor"), Some(&custody)).unwrap();
    let registry = read_json(&p.registry_path);
    let entry = registry["payload"]["keys"]
        .as_array()
        .unwrap()
        .iter()
        .find(|e| e["key_id"] == Value::from("brops-anchor-1"))
        .expect("the anchor key must be in the registry the operator root signed");
    assert_eq!(entry["authority_type"], Value::from("audit-anchor"));
    // Empty and necessarily so: `audit-anchor` binds no registry artifact type, and
    // `bro_signature._parse_key` refuses ANY grant given to it.
    assert_eq!(entry["allowed_artifact_types"], Value::from(Vec::<String>::new()));
    assert_eq!(entry["status"], Value::from("active"));
    assert_eq!(
        read_json(&p.anchor_dir.join(prov::MANIFEST_FILE))["anchor_key_id"],
        Value::from("brops-anchor-1")
    );

    // A record claiming some other authority, or carrying a secret, is refused rather
    // than credited with an authority its own publisher never claimed.
    for bad in [
        serde_json::json!({"key_id": "x", "public_key": "ab".repeat(32),
                           "authority": "operator-root"}),
        serde_json::json!({"key_id": "x", "public_key": "ab".repeat(32),
                           "authority": "audit-anchor", "private_key": "00".repeat(32)}),
        serde_json::json!({"key_id": "x", "public_key": "nothex", "authority": "audit-anchor"}),
    ] {
        let other = tempfile::tempdir().unwrap();
        assert!(
            prov::mint_store_without_custody_proof(other.path(), &other.path().join("anchor"), Some(&bad)).is_err(),
            "a custody record {bad} must be refused"
        );
        assert!(!other.path().join(prov::TRUST_DIR).exists(), "and nothing left behind");
    }
}

#[test]
fn the_manifest_records_what_the_platform_actually_did_about_permissions() {
    let dir = tempfile::tempdir().unwrap();
    let p = mint_at(dir.path()).unwrap();
    let manifest = read_json(&p.anchor_dir.join(prov::MANIFEST_FILE));
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
    let p = mint_at(dir.path()).unwrap();
    for authority in prov::RETAINED_AUTHORITIES {
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

/// **The umask defect.** Every provisioned file and directory carries a mode this crate
/// STATES; none carries one the ambient umask decided.
///
/// The first Linux run of this code produced a group-writable `operator-root.pub`, because
/// `File::create` opens at `0666 & ~umask` and Debian's stock `umask` is `002`. The real
/// `bro_signature._pin_from_file` refused it by name — correctly, and the deployment was dead
/// on arrival. `umask 077` breaks it the other way: the anchor becomes one the application's
/// own account cannot READ.
///
/// # What this test does and does not catch on the machine running it
///
/// Stated plainly, because it decides how much this proves here. The assertions are for EXACT
/// modes, so they bite whenever the runner's umask would have produced something else:
///
/// * under `umask 002` the `WorldReadable` assertions bite (0664 vs 0644, 0775 vs 0755);
/// * under `umask 077` they bite the other way (0600 vs 0644, 0700 vs 0755);
/// * under the common `umask 022` they do NOT — `0666 & ~022` is already `0644` — but the
///   `OwnerOnly` assertions do, because `0644` is not `0600`.
///
/// So there is no umask under which the whole test is vacuous, and the `Exposure` assertions at
/// the top are pure and run on every platform including the ones with no modes at all.
#[test]
fn nothing_provisioned_carries_a_mode_the_umask_decided() {
    // The pure half: what the two exposures MEAN. Runs on every platform.
    assert_eq!(prov::Exposure::WorldReadable.file_mode(), 0o644);
    assert_eq!(prov::Exposure::WorldReadable.dir_mode(), 0o755);
    assert_eq!(prov::Exposure::OwnerOnly.file_mode(), 0o600);
    assert_eq!(prov::Exposure::OwnerOnly.dir_mode(), 0o700);
    // The anchor must be readable by the account being policed and writable by nobody but its
    // owner: that is exactly what `_pin_from_file` and `_refuse_writable_registry_root` ask.
    assert_eq!(prov::Exposure::WorldReadable.file_mode() & 0o022, 0, "the anchor would be refused");
    assert_eq!(prov::Exposure::WorldReadable.dir_mode() & 0o022, 0, "the anchor would be refused");
    assert_ne!(prov::Exposure::WorldReadable.file_mode() & 0o044, 0, "the app could not read it");

    // The measured half, where the platform has modes at all.
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;

        fn mode(path: &Path) -> u32 {
            fs::metadata(path)
                .unwrap_or_else(|e| panic!("{}: {e}", path.display()))
                .permissions()
                .mode()
                & 0o7777
        }
        // What the umask on THIS machine would have done, so a failure is legible rather than
        // a bare number mismatch.
        let scratch = tempfile::tempdir().unwrap();
        let witness = scratch.path().join("umask-witness");
        fs::write(&witness, b"x").unwrap();
        let inherited = mode(&witness);

        let dir = tempfile::tempdir().unwrap();
        let p = mint_at(dir.path()).unwrap();
        let anchor = anchor_of(&p.trust_dir);

        for relative in [
            prov::OPERATOR_PIN_FILE,
            prov::REGISTRY_FLOOR_FILE,
            prov::MANIFEST_FILE,
            brops_provision::anchor::CUSTODY_FILE,
        ] {
            assert_eq!(
                mode(&anchor.join(relative)),
                0o644,
                "{relative} carries an inherited mode (a plain create here yields {inherited:04o})"
            );
        }
        // The registry root DIRECTORY is checked by the engine too, not only its file.
        assert_eq!(mode(&anchor.join(prov::REGISTRY_ROOT_DIR)), 0o755);
        assert_eq!(mode(&p.registry_path), 0o644);
        assert_eq!(mode(&anchor), 0o755);

        // And the app-side half stays owner-only, which is what bites under the common
        // `umask 022`: a plain create there yields 0644, not 0600.
        assert_eq!(mode(&p.keys_dir), 0o700);
        for authority in prov::RETAINED_AUTHORITIES {
            assert_eq!(mode(&p.keys_dir.join(format!("{authority}.json"))), 0o600);
        }
        assert_eq!(
            mode(&p.conductor_session_path),
            0o600,
            "an app-side artifact inherited its mode (a plain create here yields {inherited:04o})"
        );
    }
}
