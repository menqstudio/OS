//! The Windows LIVE governed-turn driver — assembles ONE real governed turn over named pipes and prints a
//! single `RESULT: <trust_state> production_verified=<bool> bound=<bool>` line. The Windows twin of
//! `proof/src/bin/live_turn.rs`: the SAME `brops_broker` chain + `run_governed_turn` + `verify_and_accept`,
//! but the transport is the named-pipe `WindowsHopConnector` (peer-SID authed at each server) and the
//! execution spawns the executor + drives the supervisor `attest-run` over its pipe. Trust anchors (pinned
//! root, root-signed manifest, anti-rollback floor, the broker's OWN Expected facts) come from the config —
//! never a hop reply. Any refusal / mismatch / manifest failure ⇒ `blocked`. Windows-only.

fn main() {
    #[cfg(not(windows))]
    {
        eprintln!("win_live_turn is Windows-only (named-pipe governed chain)");
        std::process::exit(2);
    }
    #[cfg(windows)]
    std::process::exit(win::run());
}

#[cfg(windows)]
mod win {
    use rusqlite::Connection;
    use serde_json::{json, Value};
    use std::time::{SystemTime, UNIX_EPOCH};

    use brops_broker::chain_executor::{ChainExecutor, ExecutionPlan, GovernedChain, ResolvedTurn, TurnResolver};

    use brops_core::broker_orchestrator::{run_governed_turn, BrokerIds};
    use brops_core::governed_turn_ipc::{TurnReason, ValidatedRequest, REQUEST_PROTOCOL, TRUSTED_VERIFIED};
    use brops_core::governed_verification::{InMemoryLedger, RECEIPT_ENVELOPE_ARTIFACT_TYPE};
    use brops_core::key_manifest::{
        check_and_advance, resolve_production_key, verify_manifest, AntiRollbackFloor, KeyManifest, PinnedRoot,
    };
    use brops_core::production_trust::{resolve_trust_state, TrustState};

    use brops_win_live::config::Config;
    use brops_win_live::crypto;
    use brops_win_live::execution::{ExecutionParams, GovernedExecutionCore};
    use brops_win_live::pipe::{self, WindowsHopConnector};

    fn now_ms() -> i64 {
        SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_millis() as i64).unwrap_or(0)
    }
    fn blocked(reason: &str) -> i32 {
        println!("RESULT: blocked reason={reason} production_verified=false bound=false");
        1
    }

    struct FixedResolver {
        resolved: ResolvedTurn,
    }
    impl TurnResolver for FixedResolver {
        fn resolve(&self, _r: &ValidatedRequest, _b: &str, _n: &str) -> Result<ResolvedTurn, TurnReason> {
            Ok(self.resolved.clone())
        }
    }
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

    fn arg(flag: &str) -> Option<String> {
        let a: Vec<String> = std::env::args().collect();
        a.iter().position(|x| x == flag).and_then(|i| a.get(i + 1)).cloned()
    }

    pub fn run() -> i32 {
        let now = now_ms();
        let cfg_path = match arg("--config") {
            Some(p) => p,
            None => {
                eprintln!("win_live_turn: --config required");
                return 2;
            }
        };
        let cfg = match Config::load(&cfg_path) {
            Ok(c) => c,
            Err(e) => return blocked(&format!("config:{e}")),
        };

        // ---- (A) pin root, verify manifest, anti-rollback, resolve keys ----
        let manifest_bytes = match std::fs::read_to_string(&cfg.trust.manifest_path) {
            Ok(b) => b,
            Err(_) => return blocked("manifest_unreadable"),
        };
        let manifest: KeyManifest = match serde_json::from_str(&manifest_bytes) {
            Ok(m) => m,
            Err(_) => return blocked("manifest_malformed"),
        };
        let root_sig = match std::fs::read_to_string(&cfg.trust.manifest_sig_path) {
            Ok(s) => s.trim().to_string(),
            Err(_) => return blocked("manifest_sig_unreadable"),
        };
        let pinned_root = PinnedRoot {
            root_key_id: cfg.trust.root_key_id.clone(),
            public_key_hex: cfg.trust.root_pub_hex.clone(),
        };
        if verify_manifest(&manifest, &root_sig, &pinned_root).is_err() {
            return blocked("manifest_root_signature_invalid");
        }
        let floor: AntiRollbackFloor = match std::fs::read_to_string(&cfg.trust.floor_path)
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
        let iso =
            match resolve_production_key(&manifest, &cfg.trust.signer_key_id, RECEIPT_ENVELOPE_ARTIFACT_TYPE, now) {
                Ok(k) => k,
                Err(_) => return blocked("key_resolution"),
            };
        let sup_hex = match manifest.keys.iter().find(|k| k.key_id == cfg.trust.supervisor_attestation_key_id) {
            Some(k) => k.public_key_hex.clone(),
            None => return blocked("supervisor_attestation_key_missing"),
        };
        let iso_pub = match crypto::hex32(&iso.public_key_hex) {
            Some(b) => b,
            None => return blocked("signer_pubkey_malformed"),
        };
        let sup_pub = match crypto::hex32(&sup_hex) {
            Some(b) => b,
            None => return blocked("supervisor_pubkey_malformed"),
        };

        // ---- (B) the broker's OWN trusted resolution ----
        let r = &cfg.resolved;
        let resolved = ResolvedTurn {
            isolated_signer_key_id: cfg.trust.signer_key_id.clone(),
            isolated_signer_public_key: iso_pub,
            supervisor_attestation_key_id: cfg.trust.supervisor_attestation_key_id.clone(),
            supervisor_attestation_public_key: sup_pub,
            workspace_id: r.workspace_id.clone(),
            install_id: r.install_id.clone(),
            system_sha256: r.system_sha256.clone(),
            history_sha256: r.history_sha256.clone(),
            generation_config_sha256: r.generation_config_sha256.clone(),
            requested_at: r.requested_at.clone(),
            run_id: r.run_id.clone(),
            task_id: r.task_id.clone(),
            requested_at_ms: r.requested_at_ms,
            author: r.author.clone(),
        };

        // ---- (C) transport + execution ----
        let connector = WindowsHopConnector {
            authority_pipe: cfg.pipes.authority.clone(),
            supervisor_pipe: cfg.pipes.supervisor.clone(),
            signer_pipe: cfg.pipes.signer.clone(),
        };
        let executor_path = cfg.executor_path.clone();
        let produce = move |_plan: &ExecutionPlan| -> Result<Vec<u8>, ()> {
            let out = std::process::Command::new(&executor_path).output().map_err(|_| ())?;
            if !out.status.success() || out.stdout.is_empty() {
                return Err(());
            }
            Ok(out.stdout)
        };
        let sup_pipe = cfg.pipes.supervisor.clone();
        let attest = move |facts: &Value| -> Result<Value, ()> {
            let req = json!({ "op": "attest-run", "facts": facts });
            let reply = pipe::hop_once(&sup_pipe, &req)?;
            if reply.get("ok").and_then(Value::as_bool) == Some(true) {
                Ok(reply)
            } else {
                Err(())
            }
        };
        let f = &cfg.facts;
        let params = ExecutionParams {
            store_dir: std::path::PathBuf::from(&cfg.store_dir),
            receipt_id: f.receipt_id.clone(),
            supervisor_id: f.supervisor_id.clone(),
            executor_id: f.executor_id.clone(),
            builder_id: f.builder_id.clone(),
            policy_id: f.policy_id.clone(),
            policy_version: f.policy_version.clone(),
            policy_bundle_handle: f.policy_bundle_handle.clone(),
            containment_evidence_handle: f.containment_evidence_handle.clone(),
            record_handle: f.record_handle.clone(),
            lease_handle: f.lease_handle.clone(),
            execution_receipt_handle: f.execution_receipt_handle.clone(),
            evidence_final_event_hash: f.evidence_final_event_hash.clone(),
            evidence_event_count: f.evidence_event_count,
            evidence_last_sequence: f.evidence_last_sequence,
            evidence_head_sequence: f.evidence_head_sequence,
        };
        let exec = GovernedExecutionCore::new(params, produce, attest, now);

        // ---- (D) run ONE governed turn ----
        let chain =
            GovernedChain::new(connector, FixedResolver { resolved }, exec, InMemoryLedger::new());
        let executor = ChainExecutor::new(chain);

        let conn = match Connection::open_in_memory() {
            Ok(c) => c,
            Err(_) => return blocked("db_open"),
        };
        if init_schema(&conn).is_err() {
            return blocked("db_schema");
        }
        let request = json!({
            "protocol": REQUEST_PROTOCOL,
            "conversation_id": cfg.resolved.conversation_id,
            "agent": "Bro",
            "client_request_id": brops_core::id(),
        })
        .to_string();

        let result = run_governed_turn(&conn, &request, &UuidIds, &executor, now);
        if result.status != "committed" {
            let reason = result.reason.map(|r| format!("{r:?}")).unwrap_or_else(|| "unknown".into());
            return blocked(&format!("chain:{reason}"));
        }
        let message = match result.message {
            Some(m) => m,
            None => return blocked("committed_without_message"),
        };
        let bound = message.trust_state == TRUSTED_VERIFIED;

        let ts = resolve_trust_state(
            Some(&manifest),
            &cfg.trust.signer_key_id,
            RECEIPT_ENVELOPE_ARTIFACT_TYPE,
            now,
            &iso.public_key_hex,
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
