//! Provision a Windows live-kit deployment to disk: four ed25519 keypairs, the content-addressed store, the
//! root-signed production key manifest + anti-rollback floor, and the shared `config.json`. The Windows twin
//! of `engine/ci/live/provision_keys.py`. Run once before starting the servers + driver.
//!
//!   win_provision --root-dir <dir> --allowed-broker-sid <S-1-5-...> [--executor-path <exe>] [--pipe-prefix <p>]

use serde_json::json;
use std::path::Path;

use brops_core::governed_verification::RECEIPT_ENVELOPE_ARTIFACT_TYPE;
use brops_core::key_manifest::KeyManifest;
use brops_win_live::config::*;
use brops_win_live::crypto;

fn arg(args: &[String], flag: &str) -> Option<String> {
    args.iter().position(|a| a == flag).and_then(|i| args.get(i + 1)).cloned()
}

fn seed_blob(store: &Path, content: &[u8]) -> String {
    let h = crypto::sha256_hex(content);
    std::fs::write(store.join(&h), content).expect("write store blob");
    h
}

fn write_seed(path: &Path, seed: &[u8; 32]) {
    std::fs::write(path, crypto::hex(seed)).expect("write seed");
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

    let root = Path::new(&root);
    let store = root.join("store");
    let keys = root.join("keys");
    for d in [&store, &keys] {
        std::fs::create_dir_all(d).expect("mkdir");
    }

    // ---- keys ----
    let challenge_seed = crypto::gen_seed();
    let attest_seed = crypto::gen_seed();
    let signer_seed = crypto::gen_seed();
    let root_seed = crypto::gen_seed();
    let challenge_pub = crypto::public_key_hex(&crypto::signing_key(&challenge_seed));
    let attest_pub = crypto::public_key_hex(&crypto::signing_key(&attest_seed));
    let signer_pub = crypto::public_key_hex(&crypto::signing_key(&signer_seed));
    let root_pub = crypto::public_key_hex(&crypto::signing_key(&root_seed));
    write_seed(&keys.join("challenge.seed"), &challenge_seed);
    write_seed(&keys.join("attest.seed"), &attest_seed);
    write_seed(&keys.join("signer.seed"), &signer_seed);
    write_seed(&keys.join("root.seed"), &root_seed);

    let challenge_key_id = "brops-live-challenge-1".to_string(); // gitleaks:allow (fake public key-id)
    let sup_attest_key_id = "brops-live-sup-attest-1".to_string(); // gitleaks:allow (fake public key-id)
    let signer_key_id = "brops-live-signer-1".to_string(); // gitleaks:allow (fake public key-id)
    let root_key_id = "brops-live-root-1".to_string(); // gitleaks:allow (fake public key-id)
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
    let manifest_json = json!({
        "manifest_epoch": 2u64,
        "root_key_id": root_key_id,
        "keys": [
            { "key_id": signer_key_id, "public_key_hex": signer_pub, "trust_class": "production",
              "valid_from_ms": 1, "valid_to_ms": 9999999999999i64, "key_epoch": 2u64, "revoked": false,
              "allowed_protocols": [RECEIPT_ENVELOPE_ARTIFACT_TYPE] },
            { "key_id": sup_attest_key_id, "public_key_hex": attest_pub, "trust_class": "production",
              "valid_from_ms": 1, "valid_to_ms": 9999999999999i64, "key_epoch": 2u64, "revoked": false,
              "allowed_protocols": [RECEIPT_ENVELOPE_ARTIFACT_TYPE] }
        ]
    });
    let manifest: KeyManifest = serde_json::from_value(manifest_json).expect("manifest build");
    let manifest_bytes = manifest.canonical_bytes();
    let root_sig = crypto::sign_b64std(&crypto::signing_key(&root_seed), &manifest_bytes);
    let content_hash = manifest.content_hash();
    std::fs::write(root.join("manifest.json"), &manifest_bytes).expect("write manifest");
    std::fs::write(root.join("manifest.sig"), &root_sig).expect("write manifest.sig");
    std::fs::write(
        root.join("floor.json"),
        serde_json::to_vec(&json!({ "highest_epoch": 2u64, "highest_hash": content_hash })).unwrap(),
    )
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
            root_seed: p("root.seed"),
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
    };
    let cfg_path = root.join("config.json");
    std::fs::write(&cfg_path, serde_json::to_vec_pretty(&cfg).unwrap()).expect("write config");
    println!("RESULT: provisioned root={} config={}", root.display(), cfg_path.display());
}
