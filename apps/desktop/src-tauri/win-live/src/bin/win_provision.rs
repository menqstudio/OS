//! Provision a Windows live-kit deployment to disk: four ed25519 keypairs, the content-addressed store, the
//! root-signed production key manifest + anti-rollback floor, and the shared `config.json`. The Windows twin
//! of `engine/ci/live/provision_keys.py`. Run once before starting the servers + driver.
//!
//!   win_provision --root-dir <dir> --allowed-broker-sid <S-1-5-...>
//!                 --challenge-account <acct> --supervisor-account <acct> --signer-account <acct>
//!                 --root-key <file> --root-provenance <external|kit_generated|demonstration>
//!                 [--executor-path <exe>] [--pipe-prefix <p>]
//!
//! ## Custody (remediation round 3 — findings P1s-1 / P1s-2 / P1s-3)
//!
//! Everything this tool writes is a custody artifact, and it used to treat almost none of it that way:
//! it adopted whatever deployment root it found, gave `config.json` no ACL at all, and wrote the two
//! production signing seeds in plaintext before spawning `icacls` to restrict them. Now:
//!
//! * the deployment root is **measured before anything is written** and refused if it is not a TCB
//!   directory ([`brops_win_live::provision_custody::verify_or_create_deployment_root`]) — it is never
//!   silently repaired;
//! * seeds, `config.json`, `manifest.json` and `manifest.sig` are **created with their restrictive,
//!   protected security descriptor already applied**, so there is no interval during which they carry
//!   the inherited DACL and no `icacls` child process anywhere in the path;
//! * all three principal public keys are in the **root-signed manifest**, so `config.json`'s copies are
//!   bound to it at load time rather than trusted.
//!
//! `floor.json` is the stated exception — see the comment at its write.
//!
//! Exit codes: 2 bad/missing argument · 3 `--root-key` is not the pinned root · 4 a file could not be
//! created under custody (usually: not elevated) · 7 the deployment root was refused.

use serde_json::json;
use std::path::Path;

use brops_core::governed_verification::RECEIPT_ENVELOPE_ARTIFACT_TYPE;
use brops_core::key_manifest::{AntiRollbackFloor, KeyManifest, RootProvenance};
use brops_win_live::config::*;
use brops_win_live::crypto;
use brops_win_live::pipe_acl::SID_ADMINISTRATORS;
use brops_win_live::provision_custody::{create_locked_file, custody_file_dacl, resolve_trustee_sid};
use brops_win_live::tcb;

fn arg(args: &[String], flag: &str) -> Option<String> {
    args.iter().position(|a| a == flag).and_then(|i| args.get(i + 1)).cloned()
}

fn required(args: &[String], flag: &str, why: &str) -> String {
    arg(args, flag).unwrap_or_else(|| {
        eprintln!("win_provision: {flag} required — {why}");
        std::process::exit(2);
    })
}

fn seed_blob(store: &Path, content: &[u8]) -> String {
    let h = crypto::sha256_hex(content);
    std::fs::write(store.join(&h), content).expect("write store blob");
    h
}

/// The owner stamped on every provisioned custody file.
///
/// A file's owner implicitly holds `WRITE_DAC`, so a DACL is only as strong as the owner: leaving the
/// provisioning user as owner would let that user re-open `signer.seed` at any time regardless of the
/// ACEs. `BUILTIN\Administrators` is also what [`brops_win_live::tcb_floor::TCB_OWNER_SIDS`] requires
/// of `config.json` and `manifest.json`, so the §2.5 floor can actually be satisfied afterwards.
///
/// A token that may not assign this owner (i.e. a non-elevated run) makes `CreateFileW` fail with
/// `ERROR_INVALID_OWNER` and provisioning aborts. That is intended: there is no correct way to
/// provision a TCB from a shell that cannot create TCB-owned files.
const CUSTODY_OWNER_SID: &str = SID_ADMINISTRATORS;

/// Write one provisioned file with its restrictive security descriptor **already applied at
/// creation** (remediation round 3, finding P1s-3).
///
/// This replaces `fs::write` followed by a spawned `icacls`. The old sequence was not a small race —
/// Windows grants access at OPEN time, so a handle obtained during the tens of milliseconds a process
/// spawn takes keeps its access after the DACL is replaced, and `attest.seed` / `signer.seed` are the
/// two production signing keys. Holding either does not defeat the governed chain; it makes the chain
/// irrelevant, because the holder signs whatever they like and every downstream check agrees.
///
/// `readers` are account names or SIDs; they are resolved to SIDs FIRST, so the world-SID refusal in
/// `custody_file_dacl` runs on the SID rather than on a locale-dependent name. Any failure deletes the
/// file and aborts: a production seed on disk without custody is worse than no deployment, because
/// provisioning would otherwise print success over it.
fn write_custody_file<S: AsRef<str>>(path: &Path, contents: &[u8], readers: &[S], what: &str) {
    let mut sids = Vec::with_capacity(readers.len());
    for r in readers {
        let r = r.as_ref();
        match resolve_trustee_sid(r) {
            Ok(s) => sids.push(s),
            Err(why) => custody_abort(path, what, &format!("cannot resolve account {r:?}: {why}")),
        }
    }
    let dacl = match custody_file_dacl(&sids) {
        Ok(d) => d,
        Err(why) => custody_abort(path, what, &why),
    };
    if let Err(why) = create_locked_file(path, contents, &dacl, Some(CUSTODY_OWNER_SID)) {
        custody_abort(path, what, &why);
    }
}

fn custody_abort(path: &Path, what: &str, why: &str) -> ! {
    let _ = std::fs::remove_file(path);
    eprintln!("win_provision: cannot create {what} at {} under custody: {why}", path.display());
    eprintln!(
        "win_provision: refusing to leave a {what} on disk without the security descriptor it needs"
    );
    std::process::exit(4);
}

fn now_ms() -> i64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_millis() as i64).unwrap_or(0)
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let root = arg(&args, "--root-dir").unwrap_or_else(|| {
        eprintln!("win_provision: --root-dir required");
        std::process::exit(2);
    });
    let allowed_broker_sid = arg(&args, "--allowed-broker-sid").unwrap_or_else(|| {
        eprintln!("win_provision: --allowed-broker-sid required");
        std::process::exit(2);
    });
    let executor_path = arg(&args, "--executor-path").unwrap_or_default();
    let pipe_prefix = arg(&args, "--pipe-prefix").unwrap_or_else(|| "brops-live".to_string());
    // The three service accounts are REQUIRED, and required HERE rather than at the first seed write.
    // They are not only the seed owners any more: they are also the readers named in `config.json`'s
    // and `manifest.json`'s explicit DACLs, so a missing one has to abort before anything is written,
    // not halfway through. (A same-account deployment passes the same name three times.)
    let challenge_account =
        required(&args, "--challenge-account", "the account that will hold challenge.seed");
    let supervisor_account =
        required(&args, "--supervisor-account", "the account that will hold attest.seed");
    let signer_account =
        required(&args, "--signer-account", "the account that will hold signer.seed");
    // Audit condition 1: the root PRIVATE key is supplied by the OPERATOR from an offline location, never
    // compiled in and never left on the serving box. It signs the manifest here; only the root PUBLIC key is
    // pinned in the TCB (crate::tcb). The offline private MUST match that pinned public.
    let root_key_path = arg(&args, "--root-key").unwrap_or_else(|| {
        eprintln!("win_provision: --root-key <offline root private seed hex> required");
        std::process::exit(2);
    });
    // The CUSTODY declaration. Nothing in this tool can tell whether the seed it was just handed came
    // off airgapped media or was generated on this box thirty seconds ago — the arithmetic is identical
    // either way. So the operator declares it, explicitly, with no default: an unstated provenance would
    // otherwise silently become "external" and the whole production claim would rest on an omission.
    let root_provenance = arg(&args, "--root-provenance")
        .and_then(|s| RootProvenance::parse(&s).map(|_| s))
        .unwrap_or_else(|| {
            eprintln!(
                "win_provision: --root-provenance <external|kit_generated|demonstration> required"
            );
            eprintln!("  external      = the root private was generated and is held OFFLINE, outside this kit");
            eprintln!("  kit_generated = this kit generated the root keypair (a real chain, same party both ends)");
            eprintln!("  demonstration = a fixture anchor whose private half is in the source tree");
            eprintln!("  Only `external` can ever render a production trusted_verified.");
            std::process::exit(2);
        });
    let root_signing = {
        let hex = std::fs::read_to_string(&root_key_path).unwrap_or_else(|e| {
            eprintln!("win_provision: cannot read --root-key {root_key_path}: {e}");
            std::process::exit(2);
        });
        let seed = crypto::hex32(hex.trim()).unwrap_or_else(|| {
            eprintln!("win_provision: --root-key is not a 32-byte hex seed");
            std::process::exit(2);
        });
        let sk = crypto::signing_key(&seed);
        if crypto::public_key_hex(&sk) != tcb::root_public_key_hex() {
            eprintln!("win_provision: --root-key does not match the TCB-pinned root public key");
            std::process::exit(3);
        }
        sk
    };

    let root = Path::new(&root);

    // ---- deployment-root custody (remediation round 3, finding P1s-2) ----
    // BEFORE anything is written. `keys/`, `store/` and `config.json` inherit whatever DACL this
    // directory carries, so an unprivileged account that pre-created the well-known path chose the
    // custody of every secret below it. The provisioner used to `create_dir_all(...).expect("mkdir")`
    // and adopt it silently. It is now measured — TCB owner, no non-TCB writer, no world ACE, the SAME
    // predicate the runtime §2.5 floor applies to config.json's ancestors — and a failure is a refusal
    // with the remediation printed, never a silent repair. See `provision_custody` for why not.
    if let Err(why) = brops_win_live::provision_custody::verify_or_create_deployment_root(root) {
        eprintln!("{why}");
        std::process::exit(7);
    }

    let store = root.join("store");
    let keys = root.join("keys");
    for d in [&store, &keys] {
        // Under a root that has just been verified, so these inherit a TCB-only DACL. The files that
        // matter get their own explicit, protected descriptors below regardless.
        std::fs::create_dir_all(d).expect("mkdir");
    }

    // ---- keys ----
    let challenge_seed = crypto::gen_seed();
    let attest_seed = crypto::gen_seed();
    let signer_seed = crypto::gen_seed();
    let challenge_pub = crypto::public_key_hex(&crypto::signing_key(&challenge_seed));
    let attest_pub = crypto::public_key_hex(&crypto::signing_key(&attest_seed));
    let signer_pub = crypto::public_key_hex(&crypto::signing_key(&signer_seed));
    // Root anchor is the TCB-pinned key (audit fix P1-a) — the manifest is signed with the TCB root, and the
    // driver pins the root PUBLIC key from crate::tcb, NEVER from config.json.
    let root_pub = tcb::root_public_key_hex();
    // Each seed is CREATED already restricted to the single account that will hold it — SYSTEM and
    // Administrators full control, that account read-only, everyone else absent and therefore denied.
    // No plaintext-then-ACL window, and no `icacls` child process in the path at all.
    write_custody_file(
        &keys.join("challenge.seed"),
        crypto::hex(&challenge_seed).as_bytes(),
        &[&challenge_account],
        "challenge seed",
    );
    write_custody_file(
        &keys.join("attest.seed"),
        crypto::hex(&attest_seed).as_bytes(),
        &[&supervisor_account],
        "supervisor attestation seed",
    );
    write_custody_file(
        &keys.join("signer.seed"),
        crypto::hex(&signer_seed).as_bytes(),
        &[&signer_account],
        "production receipt-signing seed",
    );
    // Audit A: the root PRIVATE key is NOT written to the live deployment. The manifest is signed here with
    // the TCB root (crate::tcb); the driver pins only the root PUBLIC key. In production the root private is
    // held offline entirely — nothing about the root private lands on the serving box.

    let challenge_key_id = "brops-live-challenge-1".to_string(); // gitleaks:allow (fake public key-id)
    let sup_attest_key_id = "brops-live-sup-attest-1".to_string(); // gitleaks:allow (fake public key-id)
    let signer_key_id = "brops-live-signer-1".to_string(); // gitleaks:allow (fake public key-id)
    let root_key_id = tcb::ROOT_KEY_ID.to_string();
    let supervisor_id = "brops-supervisor".to_string();
    let executor_id = "brops-executor".to_string();
    let builder_id = "brops-builder".to_string();

    // ---- store blobs ----
    let system_sha256 = seed_blob(&store, b"brops-system-prompt-v1");
    let history_sha256 = seed_blob(&store, b"brops-history-v1");
    let generation_config_sha256 = seed_blob(&store, b"brops-generation-config-v1");
    let policy_bundle_handle = seed_blob(&store, b"brops-policy-bundle-v1");
    let containment_evidence_handle = seed_blob(&store, b"brops-containment-evidence-v1");
    let record_handle = seed_blob(&store, b"brops-record-v1");
    let lease_handle = seed_blob(&store, b"brops-lease-v1");
    let execution_receipt_handle = seed_blob(&store, b"brops-execution-receipt-v1");
    let evidence_final_event_hash = crypto::sha256_hex(b"brops-final-event-v1");

    let launcher_sha = crypto::sha256_hex(b"brops-windows-launcher-v1");
    let executor_sha = std::fs::read(&executor_path)
        .map(|b| crypto::sha256_hex(&b))
        .unwrap_or_else(|_| crypto::sha256_hex(b"brops-windows-executor-v1"));

    // ---- root-signed manifest + floor ----
    // All THREE principal public keys are covered, including the challenge key (remediation round 3,
    // finding P1s-1). Before this, `pubs.challenge` and `pubs.attest` reached the supervisor and the
    // signer from `config.json` alone, with nothing signing over them: whoever could write that file
    // chose the key the isolated signer verified supervisor attestations under, and the REAL signer
    // key then signed a receipt over material the attacker had authored. Putting them in the
    // root-signed manifest makes the substitution arithmetic — `config::verify_and_bind_pubs` refuses
    // any config whose `pubs` disagree — and the root private that could re-sign the manifest is
    // offline, not on this box.
    let manifest_json = json!({
        "manifest_epoch": 2u64,
        "root_key_id": root_key_id,
        "keys": [
            { "key_id": signer_key_id, "public_key_hex": signer_pub, "trust_class": "production",
              "valid_from_ms": 1, "valid_to_ms": 9999999999999i64, "key_epoch": 2u64, "revoked": false,
              "allowed_protocols": [RECEIPT_ENVELOPE_ARTIFACT_TYPE] },
            { "key_id": sup_attest_key_id, "public_key_hex": attest_pub, "trust_class": "production",
              "valid_from_ms": 1, "valid_to_ms": 9999999999999i64, "key_epoch": 2u64, "revoked": false,
              "allowed_protocols": [RECEIPT_ENVELOPE_ARTIFACT_TYPE] },
            // The challenge key signs challenges, not receipt envelopes, so it carries its own audience
            // label. Marking it allowed for the receipt-envelope protocol would be a lie that
            // resolve_production_key would then happily enforce.
            { "key_id": challenge_key_id, "public_key_hex": challenge_pub, "trust_class": "production",
              "valid_from_ms": 1, "valid_to_ms": 9999999999999i64, "key_epoch": 2u64, "revoked": false,
              "allowed_protocols": [CHALLENGE_ARTIFACT_TYPE] }
        ]
    });
    let manifest: KeyManifest = serde_json::from_value(manifest_json).expect("manifest build");
    let manifest_bytes = manifest.canonical_bytes();
    let root_sig = crypto::sign_b64std(&root_signing, &manifest_bytes);
    let content_hash = manifest.content_hash();
    // Every one of the four bins reads these two through `Config::load`, so all four principals plus
    // the broker are readers. They are never rewritten at run time, so nobody outside the TCB needs
    // write — which is exactly what the §2.5 floor demands of `key-manifest.root-anchor` /
    // `key-manifest.root-signature`.
    let deployment_readers: Vec<String> = vec![
        allowed_broker_sid.clone(),
        challenge_account.clone(),
        supervisor_account.clone(),
        signer_account.clone(),
    ];
    write_custody_file(
        &root.join("manifest.json"),
        &manifest_bytes,
        &deployment_readers,
        "root-signed key manifest",
    );
    write_custody_file(
        &root.join("manifest.sig"),
        root_sig.as_bytes(),
        &deployment_readers,
        "root manifest signature",
    );
    // Anti-rollback floor as ONE self-contained signed file (atomic single-file write, audit D). SECURITY
    // REALITY (audit P0): the floor signing key is a PUBLIC source constant, so the embedded signature is a
    // corruption check only, NOT the anti-rollback boundary — a source-reading adversary who can write this
    // dir CAN forge a lowered signed floor. The real boundary is the OS write-ACL that MUST restrict this
    // deployment dir (and floor.json) to the broker service principal only; provisioning/deployment must set
    // that ACL. See WINDOWS_ANTIROLLBACK_HARDENING.md.
    //
    // NOT written through `write_custody_file`, and that is a deliberate, stated gap rather than an
    // oversight: `resolver::persist_floor` REWRITES this file on every turn (tmp + rename in this same
    // directory), so a TCB-only DACL would break anti-rollback persistence in any deployment whose
    // broker is not itself a TCB principal — which is the deployment shape the kit targets. Its custody
    // remains what `tcb::FLOOR_SEED_HEX` already says it is: the deployment-directory ACL the operator
    // sets. This round did not improve that and does not claim to.
    let floor = AntiRollbackFloor { highest_epoch: 2, highest_hash: content_hash };
    std::fs::write(root.join("floor.json"), brops_win_live::resolver::signed_floor_file(&floor))
        .expect("write floor");

    // ---- config.json ----
    let p = |s: &str| root.join("keys").join(s).to_string_lossy().to_string();
    let cfg = Config {
        allowed_broker_sid,
        store_dir: store.to_string_lossy().to_string(),
        pipes: Pipes {
            authority: format!("{pipe_prefix}-authority"),
            supervisor: format!("{pipe_prefix}-supervisor"),
            signer: format!("{pipe_prefix}-signer"),
        },
        keys: Keys {
            challenge_seed: p("challenge.seed"),
            attest_seed: p("attest.seed"),
            signer_seed: p("signer.seed"),
            root_seed: String::new(), // audit A: no root private on the serving box
        },
        key_ids: KeyIds {
            challenge: challenge_key_id,
            sup_attest: sup_attest_key_id.clone(),
            signer: signer_key_id.clone(),
            root: root_key_id.clone(),
        },
        pubs: Pubs { challenge: challenge_pub, attest: attest_pub, signer: signer_pub, root: root_pub.clone() },
        trust: Trust {
            manifest_path: root.join("manifest.json").to_string_lossy().to_string(),
            manifest_sig_path: root.join("manifest.sig").to_string_lossy().to_string(),
            floor_path: root.join("floor.json").to_string_lossy().to_string(),
            root_key_id,
            root_pub_hex: root_pub,
            root_provenance,
            signer_key_id,
            supervisor_attestation_key_id: sup_attest_key_id,
        },
        resolved: Resolved {
            workspace_id: "ws-live-1".to_string(),
            install_id: "install-live-1".to_string(),
            system_sha256,
            history_sha256,
            generation_config_sha256,
            requested_at: now_ms().to_string(),
            requested_at_ms: now_ms(),
            run_id: "run-live-1".to_string(),
            task_id: "task-live-1".to_string(),
            author: "Bro".to_string(),
            conversation_id: "conv-live-1".to_string(),
        },
        facts: Facts {
            receipt_id: "brops-live-receipt-1".to_string(),
            supervisor_id: supervisor_id.clone(),
            executor_id: executor_id.clone(),
            builder_id: builder_id.clone(),
            policy_id: "brops-policy-1".to_string(),
            policy_version: "1".to_string(),
            policy_bundle_handle,
            containment_evidence_handle,
            record_handle,
            lease_handle,
            execution_receipt_handle,
            evidence_final_event_hash,
            evidence_event_count: 3,
            evidence_last_sequence: 3,
            evidence_head_sequence: 3,
        },
        supervisor_cfg: SupervisorCfg {
            launcher_executable_sha256: launcher_sha,
            executor_executable_sha256: executor_sha,
        },
        identities: Identities {
            allowed_executors: vec![executor_id],
            allowed_builders: vec![builder_id],
            allowed_supervisors: vec![supervisor_id],
        },
        executor_path,
        // Audit R2: where the §2.5 pin manifest WILL live. Provisioning only names it; it cannot build
        // it, because the pin must measure config.json itself (which does not exist until the line
        // below) and the binaries in their deployed location. Run `win_tcb_pin` next — until it has,
        // every server bin and the driver refuse to serve, which is the intended fail-closed state.
        tcb_pin_manifest: root.join("tcb-pin.json").to_string_lossy().to_string(),
    };
    // `config.json` gets the SAME custody treatment as the seeds (remediation round 3, finding P1s-1).
    // It used to get none at all — `restrict_to_owner` was only ever called from the seed path — while
    // carrying `allowed_broker_sid`, the identity allowlists, `store_dir`, `executor_path` and the
    // public keys the servers verify their peers under. The key half of that is now bound
    // cryptographically to the root-signed manifest at load time; these other fields have no manifest
    // to bind to, so their integrity is this DACL plus the §2.5 pin (`kit.config`), and nothing else.
    let cfg_path = root.join("config.json");
    write_custody_file(
        &cfg_path,
        &serde_json::to_vec_pretty(&cfg).unwrap(),
        &deployment_readers,
        "deployment config",
    );
    println!("RESULT: provisioned root={} config={}", root.display(), cfg_path.display());
    println!(
        "NEXT: win_tcb_pin --root-dir {} --bin-dir <dir with win_*.exe> --out {}",
        root.display(),
        root.join("tcb-pin.json").display()
    );
    println!("      (the §2.5 TCB integrity floor refuses to serve until that manifest exists)");
}
