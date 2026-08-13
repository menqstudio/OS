//! The on-disk deployment config shared by the provisioner, the three server bins, and the driver. It is the
//! Windows analogue of the Linux live kit's `config.json`: the broker's OWN side (pinned root, manifest,
//! resolved Expected facts) plus the transport (pipe names + the single allowed broker SID) plus each
//! principal's key seed path. Private key seeds live in their own files (hex-encoded), never inline here.

use serde::{Deserialize, Serialize};

use brops_core::governed_verification::RECEIPT_ENVELOPE_ARTIFACT_TYPE;
use brops_core::key_manifest::{resolve_production_key, verify_manifest, KeyManifest, PinnedRoot};

use crate::tcb;

/// The manifest audience label for the challenge-authority key.
///
/// The receipt-envelope protocol constant lives in `brops-core` because `verify_and_accept` checks it.
/// The challenge signature is verified inside this kit (`servers::Supervisor`), so its audience label
/// lives here — it exists so [`resolve_production_key`] can enforce trust class, validity window and
/// revocation on the challenge key too, instead of the challenge key riding in `config.json` with
/// nothing signing over it.
pub const CHALLENGE_ARTIFACT_TYPE: &str = "brops.governed-challenge.v1";

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
    /// Path to the deployment's §2.5 TCB pin manifest (audit R2). `#[serde(default)]` so an older
    /// config still PARSES — but an empty value makes [`crate::tcb_floor::verify_deployment_tcb`]
    /// refuse, so an un-upgraded deployment fails closed rather than serving unmeasured. The env var
    /// [`crate::tcb_floor::WIN_TCB_PIN_MANIFEST_ENV`] overrides it (see [`Config::tcb_pin_manifest_path`]).
    #[serde(default)]
    pub tcb_pin_manifest: String,
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

/// The public keys the servers verify their peers under.
///
/// **These are advisory copies, not the trust anchor.** Until the remediation these were plain config
/// fields with nothing signing over them, and `pubs.attest` in particular is the key the isolated
/// signer verifies supervisor attestations under: whoever could write `config.json` could substitute
/// their own attestation key, hand the signer an attestation it accepted, and get the REAL production
/// signer key to sign a receipt that `verify_and_accept` then verified happily under the compiled-in
/// root. Nothing in the chain was forged; the wrong key was simply asked.
///
/// [`Config::load`] now refuses any config whose `pubs` disagree with the ROOT-SIGNED key manifest
/// (see [`verify_and_bind_pubs`]). The manifest is signed by the offline root whose private half is
/// not on the serving box, so this is a cryptographic bind, not another file to protect.
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
    /// CUSTODY provenance the OPERATOR declared for the root anchor at provisioning time — one of
    /// `external` / `kit_generated` / `demonstration`. It is a declaration, not a proof: no code can
    /// tell where the private key `win_provision --root-key` was handed came from, so the operator
    /// states it and the driver carries it into the trust verdict. `#[serde(default)]` keeps older
    /// configs parseable; an empty or unrecognised value makes the driver refuse (`blocked`), never
    /// default to `external`.
    #[serde(default)]
    pub root_provenance: String,
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

/// The supervisor's OWN provisioning — the identities the isolated signer allowlists (audit F-01),
/// which the execution must not be able to choose.
///
/// **audit F-02 / R-42 — nine fields removed 2026-08-10.** `receipt_id`,
/// `containment_evidence_handle`, `record_handle`, `lease_handle`, `execution_receipt_handle`,
/// `evidence_final_event_hash`, `evidence_event_count`, `evidence_last_sequence` and
/// `evidence_head_sequence` used to live here. F-02 removed them from the PROTOCOL — the supervisor
/// mints the receipt id, builds and content-addresses the three terminal artifacts itself, and
/// derives the evidence head from the execution's own chain — but it left the config that used to
/// supply them in place, still written by `win_provision`, still deserialized, still readable in
/// `config.json` as if it configured the deployment's evidence head. Nothing read any of them:
/// the substance was removed and the appearance was kept, which is the shape of defect this
/// repository keeps finding. `win_provision` also stopped seeding the four placeholder store blobs
/// their handles addressed.
///
/// Serde ignores unknown JSON keys, so a config file written by an older provisioner still loads.
#[derive(Serialize, Deserialize, Clone)]
pub struct Facts {
    pub supervisor_id: String,
    pub executor_id: String,
    pub builder_id: String,
    pub policy_id: String,
    pub policy_version: String,
    pub policy_bundle_handle: String,
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

/// The root every deployment config's key manifest MUST verify under: the **compiled-in** TCB anchor
/// from [`crate::tcb`], never `config.json`'s own `trust.root_pub_hex`.
///
/// If the root came from the config, an adversary who could write the config would supply their own
/// root, their own manifest and their own `pubs`, and every check below would agree with itself.
pub fn production_pinned_root() -> PinnedRoot {
    PinnedRoot { root_key_id: tcb::ROOT_KEY_ID.to_string(), public_key_hex: tcb::root_public_key_hex() }
}

/// Bind the config-carried public keys to the root-signed key manifest, and refuse if any of them
/// disagrees.
///
/// Pure over bytes and plain structs so the whole decision is unit-tested on the Linux CI runner (this
/// kit's Windows-only code has no CI coverage at all, which is its own audit finding). `pinned` is a
/// parameter for the same reason [`crate::resolver::ManifestResolver::with_pinned_root`] takes one: a
/// test can exercise the real verification path under a key it generated, while [`Config::load`] — the
/// only production caller — always passes [`production_pinned_root`].
///
/// What is checked, and why each one:
/// * the manifest parses and its detached signature verifies under `pinned` — everything below is
///   worthless otherwise;
/// * `trust.root_key_id` / `trust.root_pub_hex` / `pubs.root` agree with `pinned`, so a config cannot
///   quietly claim a different anchor than the one that just did the verifying;
/// * each of `pubs.signer`, `pubs.attest`, `pubs.challenge` equals the key the manifest resolves for
///   the corresponding key id — through [`resolve_production_key`], so trust class, validity window,
///   revocation and protocol audience are enforced, not just the hex string.
///
/// Honest limits:
/// * This binds the KEYS. `allowed_broker_sid`, `store_dir`, `executor_path` and the identity
///   allowlists have no manifest entry to bind to — the key-manifest schema lives in `brops-core` and
///   admits keys only. Their integrity rests on (a) the explicit DACL `win_provision` now creates
///   `config.json` with, and (b) the §2.5 pin manifest, which content-pins `config.json` as
///   `kit.config` — start-time only, and only once `win_tcb_pin` has run.
/// * A manifest that is genuinely root-signed but STALE still verifies here; epoch/anti-rollback is
///   [`crate::resolver`]'s job, per turn, and is unchanged.
pub fn verify_and_bind_pubs(
    manifest_bytes: &[u8],
    root_sig_b64: &str,
    pinned: &PinnedRoot,
    key_ids: &KeyIds,
    trust: &Trust,
    pubs: &Pubs,
    now_ms: i64,
) -> Result<(), String> {
    let manifest: KeyManifest = serde_json::from_slice(manifest_bytes)
        .map_err(|e| format!("config trust: key manifest does not parse: {e}"))?;
    verify_manifest(&manifest, root_sig_b64, pinned).map_err(|e| {
        format!(
            "config trust: the key manifest is not signed by the TCB-pinned root {} ({e:?})",
            pinned.root_key_id
        )
    })?;

    if trust.root_key_id != pinned.root_key_id {
        return Err(format!(
            "config trust: trust.root_key_id {:?} is not the TCB-pinned root {:?}",
            trust.root_key_id, pinned.root_key_id
        ));
    }
    for (field, value) in [("trust.root_pub_hex", &trust.root_pub_hex), ("pubs.root", &pubs.root)] {
        if value != &pinned.public_key_hex {
            return Err(format!(
                "config trust: {field} does not match the TCB-pinned root public key"
            ));
        }
    }

    for (field, key_id, protocol, config_value) in [
        (
            "pubs.signer",
            &trust.signer_key_id,
            RECEIPT_ENVELOPE_ARTIFACT_TYPE,
            &pubs.signer,
        ),
        (
            "pubs.attest",
            &trust.supervisor_attestation_key_id,
            RECEIPT_ENVELOPE_ARTIFACT_TYPE,
            &pubs.attest,
        ),
        ("pubs.challenge", &key_ids.challenge, CHALLENGE_ARTIFACT_TYPE, &pubs.challenge),
    ] {
        let resolved = resolve_production_key(&manifest, key_id, protocol, now_ms).map_err(|e| {
            format!(
                "config trust: the root-signed manifest does not resolve a production key {key_id:?} \
                 for {protocol} ({e:?}). A deployment provisioned before the manifest covered this key \
                 must be RE-PROVISIONED — the manifest is root-signed and cannot be patched locally."
            )
        })?;
        if &resolved.public_key_hex != config_value {
            return Err(format!(
                "config trust: {field} does not match the root-signed manifest entry for {key_id:?}. \
                 Refusing: a rewritten {field} is how a config-writing adversary gets the real signer \
                 key to sign over material they authored."
            ));
        }
    }
    Ok(())
}

fn now_ms() -> i64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_millis() as i64).unwrap_or(0)
}

impl Config {
    /// Load and parse the deployment config, then REFUSE it unless its public keys are the ones the
    /// root-signed manifest names (see [`verify_and_bind_pubs`]).
    ///
    /// Every Windows bin reaches its keys through this call, so the bind is enforced for all four
    /// principals rather than being an optional extra step one of them might skip.
    pub fn load(path: &str) -> Result<Config, String> {
        let raw = std::fs::read_to_string(path).map_err(|e| format!("config read: {e}"))?;
        let cfg: Config = serde_json::from_str(&raw).map_err(|e| format!("config parse: {e}"))?;

        let manifest_bytes = std::fs::read(&cfg.trust.manifest_path).map_err(|e| {
            format!("config trust: cannot read manifest {}: {e}", cfg.trust.manifest_path)
        })?;
        let sig = std::fs::read_to_string(&cfg.trust.manifest_sig_path).map_err(|e| {
            format!("config trust: cannot read manifest signature {}: {e}", cfg.trust.manifest_sig_path)
        })?;
        verify_and_bind_pubs(
            &manifest_bytes,
            sig.trim(),
            &production_pinned_root(),
            &cfg.key_ids,
            &cfg.trust,
            &cfg.pubs,
            now_ms(),
        )?;
        Ok(cfg)
    }

    /// Where this deployment's §2.5 pin manifest lives: the env var wins (an operator can point a
    /// running deployment at a re-pinned manifest without rewriting a config that is itself pinned),
    /// otherwise the config field. `None` when neither is set — which the floor treats as a refusal,
    /// never as "no floor required".
    pub fn tcb_pin_manifest_path(&self) -> Option<String> {
        std::env::var(crate::tcb_floor::WIN_TCB_PIN_MANIFEST_ENV)
            .ok()
            .filter(|s| !s.is_empty())
            .or_else(|| Some(self.tcb_pin_manifest.clone()).filter(|s| !s.is_empty()))
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

#[cfg(test)]
mod tests {
    //! The `pubs` → root-signed-manifest bind (remediation round 3, finding **P1s-1**).
    //!
    //! These run on the Linux CI runner: the bind is pure over bytes, and the manifest is signed here
    //! with a root this test generates, so nothing needs the operator's offline key.

    use super::*;
    use brops_core::key_manifest::{ManifestKey, TrustClass};

    use crate::crypto;

    const SIGNER_KID: &str = "kid-signer";
    const ATTEST_KID: &str = "kid-attest";
    const CHALLENGE_KID: &str = "kid-challenge";
    const NOW: i64 = 1_000;

    struct Fixture {
        manifest_bytes: Vec<u8>,
        sig: String,
        pinned: PinnedRoot,
        key_ids: KeyIds,
        trust: Trust,
        pubs: Pubs,
    }

    fn key(key_id: &str, pubhex: &str, protocol: &str) -> ManifestKey {
        ManifestKey {
            key_id: key_id.to_string(),
            public_key_hex: pubhex.to_string(),
            trust_class: TrustClass::Production,
            valid_from_ms: 1,
            valid_to_ms: 9_999_999,
            key_epoch: 2,
            revoked: false,
            allowed_protocols: vec![protocol.to_string()],
        }
    }

    /// A consistent deployment: a root we hold, a manifest it signed, and a config whose `pubs` agree.
    fn fixture() -> Fixture {
        let root_sk = crypto::signing_key(&[7u8; 32]);
        let root_pub = crypto::public_key_hex(&root_sk);
        let signer_pub = crypto::public_key_hex(&crypto::signing_key(&[1u8; 32]));
        let attest_pub = crypto::public_key_hex(&crypto::signing_key(&[2u8; 32]));
        let challenge_pub = crypto::public_key_hex(&crypto::signing_key(&[3u8; 32]));

        let manifest = KeyManifest {
            manifest_epoch: 2,
            root_key_id: "test-root".to_string(),
            keys: vec![
                key(SIGNER_KID, &signer_pub, RECEIPT_ENVELOPE_ARTIFACT_TYPE),
                key(ATTEST_KID, &attest_pub, RECEIPT_ENVELOPE_ARTIFACT_TYPE),
                key(CHALLENGE_KID, &challenge_pub, CHALLENGE_ARTIFACT_TYPE),
            ],
        };
        let manifest_bytes = manifest.canonical_bytes();
        Fixture {
            sig: crypto::sign_b64std(&root_sk, &manifest_bytes),
            manifest_bytes,
            pinned: PinnedRoot {
                root_key_id: "test-root".to_string(),
                public_key_hex: root_pub.clone(),
            },
            key_ids: KeyIds {
                challenge: CHALLENGE_KID.to_string(),
                sup_attest: ATTEST_KID.to_string(),
                signer: SIGNER_KID.to_string(),
                root: "test-root".to_string(),
            },
            trust: Trust {
                manifest_path: String::new(),
                manifest_sig_path: String::new(),
                floor_path: String::new(),
                root_key_id: "test-root".to_string(),
                root_pub_hex: root_pub.clone(),
                root_provenance: "external".to_string(),
                signer_key_id: SIGNER_KID.to_string(),
                supervisor_attestation_key_id: ATTEST_KID.to_string(),
            },
            pubs: Pubs {
                challenge: challenge_pub,
                attest: attest_pub,
                signer: signer_pub,
                root: root_pub,
            },
        }
    }

    fn bind(f: &Fixture) -> Result<(), String> {
        verify_and_bind_pubs(
            &f.manifest_bytes,
            &f.sig,
            &f.pinned,
            &f.key_ids,
            &f.trust,
            &f.pubs,
            NOW,
        )
    }

    #[test]
    fn a_consistent_deployment_binds() {
        bind(&fixture()).expect("a config whose pubs match the root-signed manifest must load");
    }

    #[test]
    fn a_swapped_attest_key_is_refused() {
        // THE finding. `pubs.attest` is what the isolated signer verifies supervisor attestations
        // under; substituting it made the REAL signer key sign over attacker-authored facts. It is in
        // the root-signed manifest, so the substitution is now arithmetic, not policy.
        let mut f = fixture();
        f.pubs.attest = crypto::public_key_hex(&crypto::signing_key(&[9u8; 32]));
        let e = bind(&f).unwrap_err();
        assert!(e.contains("pubs.attest"), "{e}");
    }

    #[test]
    fn a_swapped_signer_or_challenge_key_is_refused() {
        let evil = crypto::public_key_hex(&crypto::signing_key(&[9u8; 32]));
        let mut f = fixture();
        f.pubs.signer = evil.clone();
        assert!(bind(&f).unwrap_err().contains("pubs.signer"));
        let mut f = fixture();
        f.pubs.challenge = evil;
        assert!(bind(&f).unwrap_err().contains("pubs.challenge"));
    }

    #[test]
    fn a_key_id_the_manifest_does_not_cover_is_refused() {
        // Redirecting `trust.supervisor_attestation_key_id` at a key id the root never signed must not
        // silently degrade to "unbound"; it must refuse.
        let mut f = fixture();
        f.trust.supervisor_attestation_key_id = "kid-mine".to_string();
        assert!(bind(&f).unwrap_err().contains("does not resolve a production key"));
    }

    #[test]
    fn a_revoked_or_development_class_key_is_refused_even_if_the_hex_matches() {
        // The bind goes through resolve_production_key, so trust class / revocation / window /
        // audience are all enforced. A plain hex comparison would accept all four of these.
        for mutate in [
            (|k: &mut ManifestKey| k.revoked = true) as fn(&mut ManifestKey),
            |k: &mut ManifestKey| k.trust_class = TrustClass::Development,
            |k: &mut ManifestKey| k.valid_to_ms = 2,
            |k: &mut ManifestKey| k.allowed_protocols = vec!["something-else".to_string()],
        ] {
            let f = fixture();
            let mut manifest: KeyManifest = serde_json::from_slice(&f.manifest_bytes).unwrap();
            let k = manifest.keys.iter_mut().find(|k| k.key_id == ATTEST_KID).unwrap();
            mutate(k);
            let bytes = manifest.canonical_bytes();
            let root_sk = crypto::signing_key(&[7u8; 32]);
            let sig = crypto::sign_b64std(&root_sk, &bytes);
            let e = verify_and_bind_pubs(
                &bytes, &sig, &f.pinned, &f.key_ids, &f.trust, &f.pubs, NOW,
            )
            .unwrap_err();
            assert!(e.contains("does not resolve a production key"), "{e}");
        }
    }

    #[test]
    fn an_unsigned_or_foreign_signed_manifest_is_refused() {
        let f = fixture();
        // Tampered body under a genuine signature.
        let mut manifest: KeyManifest = serde_json::from_slice(&f.manifest_bytes).unwrap();
        manifest.manifest_epoch = 3;
        let e = verify_and_bind_pubs(
            &manifest.canonical_bytes(),
            &f.sig,
            &f.pinned,
            &f.key_ids,
            &f.trust,
            &f.pubs,
            NOW,
        )
        .unwrap_err();
        assert!(e.contains("not signed by the TCB-pinned root"), "{e}");

        // A manifest signed by SOME root, presented against the pinned one — the whole substitution
        // attack in one line.
        let other = crypto::signing_key(&[8u8; 32]);
        let sig = crypto::sign_b64std(&other, &f.manifest_bytes);
        let e = verify_and_bind_pubs(
            &f.manifest_bytes, &sig, &f.pinned, &f.key_ids, &f.trust, &f.pubs, NOW,
        )
        .unwrap_err();
        assert!(e.contains("not signed by the TCB-pinned root"), "{e}");
    }

    #[test]
    fn a_config_claiming_a_different_root_than_the_one_that_verified_is_refused() {
        for mutate in [
            (|f: &mut Fixture| f.trust.root_key_id = "some-other-root".to_string())
                as fn(&mut Fixture),
            |f: &mut Fixture| f.trust.root_pub_hex = "ab".repeat(32),
            |f: &mut Fixture| f.pubs.root = "ab".repeat(32),
        ] {
            let mut f = fixture();
            mutate(&mut f);
            assert!(bind(&f).is_err(), "a config must not name a root other than the pinned one");
        }
    }

    #[test]
    fn the_production_pin_is_the_compiled_in_tcb_anchor_not_a_config_value() {
        // If this ever reads from config, every check above becomes a config comparing itself.
        let p = production_pinned_root();
        assert_eq!(p.root_key_id, tcb::ROOT_KEY_ID);
        assert_eq!(p.public_key_hex, tcb::ROOT_PUBLIC_KEY_HEX);
    }

    #[test]
    fn config_load_refuses_a_config_it_cannot_bind() {
        // Guards the WIRING, not the arithmetic: if a future edit drops the bind out of `Config::load`,
        // this config — whose manifest paths do not exist — would parse and load happily.
        let f = fixture();
        let dir = std::env::temp_dir().join(format!("brops-cfgbind-{}", brops_core::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let cfg = Config {
            allowed_broker_sid: "S-1-5-21-1-2-3-1000".to_string(),
            store_dir: dir.join("store").to_string_lossy().to_string(),
            pipes: Pipes {
                authority: "a".to_string(),
                supervisor: "s".to_string(),
                signer: "g".to_string(),
            },
            keys: Keys {
                challenge_seed: String::new(),
                attest_seed: String::new(),
                signer_seed: String::new(),
                root_seed: String::new(),
            },
            key_ids: f.key_ids.clone(),
            pubs: f.pubs.clone(),
            trust: Trust {
                manifest_path: dir.join("manifest.json").to_string_lossy().to_string(),
                manifest_sig_path: dir.join("manifest.sig").to_string_lossy().to_string(),
                ..f.trust.clone()
            },
            resolved: Resolved {
                workspace_id: "w".to_string(),
                install_id: "i".to_string(),
                system_sha256: String::new(),
                history_sha256: String::new(),
                generation_config_sha256: String::new(),
                requested_at: "0".to_string(),
                requested_at_ms: 0,
                run_id: "r".to_string(),
                task_id: "t".to_string(),
                author: "Bro".to_string(),
                conversation_id: "c".to_string(),
            },
            facts: Facts {
                supervisor_id: "sup".to_string(),
                executor_id: "ex".to_string(),
                builder_id: "bu".to_string(),
                policy_id: "p".to_string(),
                policy_version: "1".to_string(),
                policy_bundle_handle: String::new(),
            },
            supervisor_cfg: SupervisorCfg {
                launcher_executable_sha256: String::new(),
                executor_executable_sha256: String::new(),
            },
            identities: Identities {
                allowed_executors: vec!["ex".to_string()],
                allowed_builders: vec!["bu".to_string()],
                allowed_supervisors: vec!["sup".to_string()],
            },
            executor_path: String::new(),
            tcb_pin_manifest: String::new(),
        };
        let cfg_path = dir.join("config.json");
        std::fs::write(&cfg_path, serde_json::to_vec_pretty(&cfg).unwrap()).unwrap();

        // (1) no manifest on disk at all -> refuse.
        let e = Config::load(&cfg_path.to_string_lossy()).err().expect("load must refuse");
        assert!(e.contains("config trust"), "{e}");

        // (2) a manifest + signature that are internally valid but signed by a root that is NOT the
        //     compiled-in TCB anchor -> still refused, because `load` pins tcb::ROOT_PUBLIC_KEY_HEX.
        std::fs::write(dir.join("manifest.json"), &f.manifest_bytes).unwrap();
        std::fs::write(dir.join("manifest.sig"), &f.sig).unwrap();
        let e = Config::load(&cfg_path.to_string_lossy()).err().expect("load must refuse");
        assert!(e.contains("TCB-pinned root"), "{e}");

        let _ = std::fs::remove_dir_all(&dir);
    }
}
