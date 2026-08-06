//! Wave 3b — the LIVE production governed-turn driver (LINUX-RUN).
//!
//! This is the entry point that assembles ONE real governed turn end-to-end and prints a single
//! `RESULT: <trust_state> production_verified=<bool> bound=<bool>` line (or a closed `blocked` reason). It
//! wires the SAME [`brops_broker::chain_executor::linux::LinuxGovernedTurnChain`] the broker binary would
//! use — the real AF_UNIX challenge-authority / supervisor / isolated-signer hops + the real privileged
//! recorder → setuid launcher → executor spawn — over the deployment's `/opt/brops-live` provisioning.
//!
//! It NEVER fabricates a `trusted_verified`: the only path to a committed message is
//! `governed_verification::verify_and_accept` (driven inside `run_governed_turn`), and the production trust
//! verdict is `production_trust::resolve_trust_state` bound to the isolated-signer key the root-signed
//! manifest resolved AND that the envelope was cryptographically verified under. Any hop refusal, launcher/
//! executor refusal, signature/binding mismatch, manifest failure, or anti-rollback failure ⇒ `blocked`.
//!
//! Trust anchors (pinned root public key, the root-signed production key manifest, the anti-rollback floor,
//! and the broker's OWN `Expected` request facts) are read from `/opt/brops-live` — the broker's own side —
//! never from any hop reply. On a non-Linux host the socket + setuid model does not exist ⇒ exit non-zero.

#[cfg(not(target_os = "linux"))]
fn main() {
    eprintln!("live_turn: platform unsupported (Linux-only governed chain: AF_UNIX + setuid launcher)");
    std::process::exit(2);
}

#[cfg(target_os = "linux")]
fn main() {
    let args: Vec<String> = std::env::args().collect();
    let config_path = match args.iter().position(|a| a == "--config").and_then(|i| args.get(i + 1)) {
        Some(p) => p.clone(),
        None => {
            eprintln!("live_turn: usage: live_turn --config <path>");
            std::process::exit(2);
        }
    };
    std::process::exit(linux::run(&config_path));
}

#[cfg(target_os = "linux")]
mod linux {
    use rusqlite::Connection;
    use serde_json::Value;
    use std::time::{SystemTime, UNIX_EPOCH};

    use brops_broker::chain_executor::linux::{
        ChainSockets, ExecutionConfig, LinuxGovernedExecution, LinuxGovernedTurnChain,
    };
    use brops_broker::chain_executor::{ChainExecutor, ResolvedTurn, TurnResolver};

    use brops_core::broker_orchestrator::{run_governed_turn, BrokerIds};
    use brops_core::governed_turn_ipc::{TurnReason, ValidatedRequest, REQUEST_PROTOCOL, TRUSTED_VERIFIED};
    use brops_core::governed_verification::{InMemoryLedger, RECEIPT_ENVELOPE_ARTIFACT_TYPE};
    use brops_core::key_manifest::{
        check_and_advance, resolve_production_key, verify_manifest, AntiRollbackFloor, KeyManifest,
        PinnedRoot,
    };
    use brops_core::production_trust::{resolve_trust_state, verifying_key_hex, TrustState};

    // ------------------------------------------------------------------------------------------------
    // small helpers
    // ------------------------------------------------------------------------------------------------
    fn now_ms() -> i64 {
        SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_millis() as i64).unwrap_or(0)
    }

    fn blocked(reason: &str) -> i32 {
        println!("RESULT: blocked reason={reason} production_verified=false bound=false");
        1
    }

    fn hex32(s: &str) -> Option<[u8; 32]> {
        if s.len() != 64 {
            return None;
        }
        let b = s.as_bytes();
        let mut out = [0u8; 32];
        for i in 0..32 {
            let hi = (b[2 * i] as char).to_digit(16)?;
            let lo = (b[2 * i + 1] as char).to_digit(16)?;
            out[i] = (hi * 16 + lo) as u8;
        }
        Some(out)
    }

    fn s(v: &Value, path: &[&str]) -> Option<String> {
        let mut cur = v;
        for k in path {
            cur = cur.get(*k)?;
        }
        cur.as_str().map(|x| x.to_string())
    }
    fn i(v: &Value, path: &[&str]) -> Option<i64> {
        let mut cur = v;
        for k in path {
            cur = cur.get(*k)?;
        }
        cur.as_i64()
    }
    fn str_list(v: &Value, path: &[&str]) -> Option<Vec<String>> {
        let mut cur = v;
        for k in path {
            cur = cur.get(*k)?;
        }
        cur.as_array().map(|a| a.iter().filter_map(|x| x.as_str().map(str::to_string)).collect())
    }

    // A fixed resolver: the broker's OWN trusted per-turn resolution (pinned keys + Expected facts), read
    // from the root-signed manifest + the deployment config — NEVER from a hop reply.
    struct FixedResolver {
        resolved: ResolvedTurn,
    }
    impl TurnResolver for FixedResolver {
        fn resolve(&self, _r: &ValidatedRequest, _bt: &str, _n: &str) -> Result<ResolvedTurn, TurnReason> {
            Ok(self.resolved.clone())
        }
    }

    // Production broker-minted ids (fresh UUID v4 broker_turn_id + one-time request_nonce).
    struct UuidIds;
    impl BrokerIds for UuidIds {
        fn new_broker_turn_id(&self) -> String {
            brops_core::id()
        }
        fn new_request_nonce(&self) -> String {
            brops_core::id()
        }
    }

    fn init_schema(conn: &Connection) -> Result<(), String> {
        brops_core::broker_turns::create_schema(conn).map_err(|e| format!("{e:?}"))?;
        brops_core::governed_message_store::create_schema(conn).map_err(|e| format!("{e}"))?;
        brops_core::governed_output_stream::create_schema(conn).map_err(|e| format!("{e}"))?;
        brops_core::supervisor_ledger::create_schema(conn).map_err(|e| format!("{e:?}"))?;
        Ok(())
    }

    pub fn run(config_path: &str) -> i32 {
        let now = now_ms();

        // ---- load the deployment config (the broker's own side) ----
        let raw = match std::fs::read_to_string(config_path) {
            Ok(r) => r,
            Err(_) => return blocked("config_unreadable"),
        };
        let cfg: Value = match serde_json::from_str(&raw) {
            Ok(v) => v,
            Err(_) => return blocked("config_malformed"),
        };

        // ---- (A) pin the root, verify the production key manifest, anti-rollback, resolve keys ----
        let manifest_path = match s(&cfg, &["trust", "manifest_path"]) {
            Some(p) => p,
            None => return blocked("config_missing_manifest_path"),
        };
        let manifest_sig_path = match s(&cfg, &["trust", "manifest_sig_path"]) {
            Some(p) => p,
            None => return blocked("config_missing_manifest_sig_path"),
        };
        let manifest_bytes = match std::fs::read_to_string(&manifest_path) {
            Ok(b) => b,
            Err(_) => return blocked("manifest_unreadable"),
        };
        let manifest: KeyManifest = match serde_json::from_str(&manifest_bytes) {
            Ok(m) => m,
            Err(_) => return blocked("manifest_malformed"),
        };
        let root_sig_b64 = match std::fs::read_to_string(&manifest_sig_path) {
            Ok(sig) => sig.trim().to_string(),
            Err(_) => return blocked("manifest_sig_unreadable"),
        };
        let root_key_id = s(&cfg, &["trust", "root_key_id"]).unwrap_or_default();
        let root_pub_hex = s(&cfg, &["trust", "root_pub_hex"]).unwrap_or_default();
        let pinned_root = PinnedRoot { root_key_id, public_key_hex: root_pub_hex };
        if verify_manifest(&manifest, &root_sig_b64, &pinned_root).is_err() {
            return blocked("manifest_root_signature_invalid");
        }

        // Anti-rollback: accept only an epoch at/above the durable floor (same-epoch requires the same hash).
        let floor_path = s(&cfg, &["trust", "floor_path"]).unwrap_or_default();
        let floor: AntiRollbackFloor = match std::fs::read_to_string(&floor_path)
            .ok()
            .and_then(|b| serde_json::from_str::<Value>(&b).ok())
            .and_then(|v| {
                Some(AntiRollbackFloor {
                    highest_epoch: v.get("highest_epoch")?.as_u64()?,
                    highest_hash: v.get("highest_hash")?.as_str()?.to_string(),
                })
            }) {
            Some(f) => f,
            None => return blocked("floor_unreadable"),
        };
        if check_and_advance(&floor, &manifest).is_err() {
            return blocked("anti_rollback");
        }

        let signer_key_id = s(&cfg, &["trust", "signer_key_id"]).unwrap_or_default();
        let sup_attest_key_id = s(&cfg, &["trust", "supervisor_attestation_key_id"]).unwrap_or_default();
        let iso = match resolve_production_key(&manifest, &signer_key_id, RECEIPT_ENVELOPE_ARTIFACT_TYPE, now)
        {
            Ok(k) => k,
            Err(_) => return blocked("key_resolution"),
        };
        let sup_hex = match manifest.keys.iter().find(|k| k.key_id == sup_attest_key_id) {
            Some(k) => k.public_key_hex.clone(),
            None => return blocked("supervisor_attestation_key_missing"),
        };
        let iso_pub = match hex32(&iso.public_key_hex) {
            Some(b) => b,
            None => return blocked("signer_pubkey_malformed"),
        };
        let sup_pub = match hex32(&sup_hex) {
            Some(b) => b,
            None => return blocked("supervisor_pubkey_malformed"),
        };

        // ---- (B) the broker's OWN trusted Expected + create-pending facts ----
        let resolved = ResolvedTurn {
            isolated_signer_key_id: signer_key_id.clone(),
            isolated_signer_public_key: iso_pub,
            supervisor_attestation_key_id: sup_attest_key_id.clone(),
            supervisor_attestation_public_key: sup_pub,
            workspace_id: s(&cfg, &["resolved", "workspace_id"]).unwrap_or_default(),
            install_id: s(&cfg, &["resolved", "install_id"]).unwrap_or_default(),
            system_sha256: s(&cfg, &["resolved", "system_sha256"]).unwrap_or_default(),
            history_sha256: s(&cfg, &["resolved", "history_sha256"]).unwrap_or_default(),
            generation_config_sha256: s(&cfg, &["resolved", "generation_config_sha256"]).unwrap_or_default(),
            requested_at: s(&cfg, &["resolved", "requested_at"]).unwrap_or_default(),
            run_id: s(&cfg, &["resolved", "run_id"]).unwrap_or_default(),
            task_id: s(&cfg, &["resolved", "task_id"]).unwrap_or_default(),
            requested_at_ms: i(&cfg, &["resolved", "requested_at_ms"]).unwrap_or(0),
            author: s(&cfg, &["resolved", "author"]).unwrap_or_else(|| "Bro".to_string()),
        };

        // ---- (C) the live privileged-execution config (paths + fixed §4.9 facts) ----
        let sockets = ChainSockets {
            authority: match s(&cfg, &["sockets", "authority"]) {
                Some(x) => x,
                None => return blocked("config_missing_authority_sock"),
            },
            supervisor: match s(&cfg, &["sockets", "supervisor"]) {
                Some(x) => x,
                None => return blocked("config_missing_supervisor_sock"),
            },
            signer: match s(&cfg, &["sockets", "signer"]) {
                Some(x) => x,
                None => return blocked("config_missing_signer_sock"),
            },
        };
        let exec_cfg = ExecutionConfig {
            recorder_command: match str_list(&cfg, &["execution", "recorder_command"]) {
                Some(v) if !v.is_empty() => v,
                _ => return blocked("config_missing_recorder_command"),
            },
            recorder_store_dir: s(&cfg, &["execution", "recorder_store_dir"]).unwrap_or_default(),
            launcher_path: s(&cfg, &["execution", "launcher_path"]).unwrap_or_default(),
            executor_path: s(&cfg, &["execution", "executor_path"]).unwrap_or_default(),
            lease_file: s(&cfg, &["execution", "lease_file"]).unwrap_or_default(),
            cgroup_arg: s(&cfg, &["execution", "cgroup_arg"]).unwrap_or_else(|| "cgroup-live".to_string()),
            store_dir: s(&cfg, &["execution", "store_dir"]).unwrap_or_default(),
            report_dir: s(&cfg, &["execution", "report_dir"]).unwrap_or_default(),
            supervisor_sock: sockets.supervisor.clone(),
            // F-01: `receipt_id` and the supervisor/executor/builder/policy identities are no
            // longer read here. They are the values the isolated signer allowlists, so a broker
            // that named them was choosing what it would be checked against; they now come from
            // the SUPERVISOR's own provisioning (`config.supervisor.*`) and never travel the wire.
            evidence_final_event_hash: s(&cfg, &["facts", "evidence_final_event_hash"]).unwrap_or_default(),
            evidence_event_count: i(&cfg, &["facts", "evidence_event_count"]).unwrap_or(0),
            evidence_last_sequence: i(&cfg, &["facts", "evidence_last_sequence"]).unwrap_or(0),
            evidence_head_sequence: i(&cfg, &["facts", "evidence_head_sequence"]).unwrap_or(0),
        };

        // ---- (D) run ONE governed turn through the real chain ----
        let conn = match Connection::open_in_memory() {
            Ok(c) => c,
            Err(_) => return blocked("db_open"),
        };
        if let Err(e) = init_schema(&conn) {
            eprintln!("live_turn: schema init failed: {e}");
            return blocked("db_schema");
        }

        let chain = LinuxGovernedTurnChain::new(
            sockets,
            FixedResolver { resolved: resolved.clone() },
            LinuxGovernedExecution::new(exec_cfg),
            InMemoryLedger::new(),
        );
        let executor = ChainExecutor::new(chain);

        let conversation_id =
            s(&cfg, &["resolved", "conversation_id"]).unwrap_or_else(|| "conv-live-1".to_string());
        let request = serde_json::json!({
            "protocol": REQUEST_PROTOCOL,
            "conversation_id": conversation_id,
            "agent": "Bro",
            "client_request_id": brops_core::id(),
        })
        .to_string();

        let result = run_governed_turn(&conn, &request, &UuidIds, &executor, now);

        // ---- (E) report: production trust is resolved ONLY after a real committed acceptance ----
        if result.status != "committed" {
            let reason = result.reason.map(|r| format!("{r:?}")).unwrap_or_else(|| "unknown".into());
            return blocked(&format!("chain:{reason}"));
        }
        let message = match result.message {
            Some(m) => m,
            None => return blocked("committed_without_message"),
        };
        // The committed body's trust_state is `trusted_verified` ONLY because verify_and_accept accepted the
        // isolated-signer envelope over this exact output — that IS the binding.
        let bound = message.trust_state == TRUSTED_VERIFIED;

        // F-29: pass the key the CHAIN actually verified under — the exact bytes handed to
        // `verify_and_accept` as `PinnedKeys::isolated_signer_public_key` — not a second lookup of the
        // manifest, which made this guard compare a value against itself and never fail.
        let ts = resolve_trust_state(
            Some(&manifest),
            &signer_key_id,
            RECEIPT_ENVELOPE_ARTIFACT_TYPE,
            now,
            &verifying_key_hex(&resolved.isolated_signer_public_key),
        );
        let production_verified = ts.is_production_verified();
        let ts_str = match &ts {
            TrustState::Production { key_id, key_epoch } => {
                format!("trusted_verified(production key={key_id} epoch={key_epoch})")
            }
            TrustState::NoTrustedManifest(r) => format!("no_trusted_manifest({r})"),
        };
        println!("RESULT: {ts_str} production_verified={production_verified} bound={bound}");
        if production_verified && bound {
            0
        } else {
            1
        }
    }
}
