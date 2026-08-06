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

    use brops_broker::chain_executor::{ChainExecutor, ExecutionPlan, GovernedChain};

    use brops_core::broker_orchestrator::{run_governed_turn, BrokerIds};
    use brops_core::governed_turn_ipc::{REQUEST_PROTOCOL, TRUSTED_VERIFIED};
    use brops_core::governed_verification::{InMemoryLedger, RECEIPT_ENVELOPE_ARTIFACT_TYPE};
    use brops_core::key_manifest::{
        resolve_production_key, verify_manifest_anchored, KeyManifest, PinnedRoot, RootAnchor,
        RootProvenance,
    };
    use brops_core::production_trust::{resolve_trust_state, verifying_key_hex, TrustState};

    use brops_win_live::config::Config;
    use brops_win_live::execution::{ExecutionParams, GovernedExecutionCore};
    use brops_win_live::pipe::{self, WindowsHopConnector};
    use brops_win_live::resolver::{ManifestResolver, ResolvedFacts, SharedResolver};
    use brops_win_live::tcb;

    fn now_ms() -> i64 {
        SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_millis() as i64).unwrap_or(0)
    }
    fn blocked(reason: &str) -> i32 {
        println!("RESULT: blocked reason={reason} production_verified=false bound=false");
        1
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

        // ---- (0) §2.5 TCB integrity floor (audit R2) ----
        // Before ANY trust anchor is read. The manifest/floor/config this driver is about to pin its whole
        // verdict on are themselves pinned artifacts; if they or the four binaries have moved since the
        // deployment was measured, the turn is `blocked`, not `trusted_verified`. Fail-closed: an
        // unconfigured or unreadable pin manifest blocks too.
        if let Err(why) =
            brops_win_live::tcb_floor::verify_deployment_tcb(cfg.tcb_pin_manifest_path().as_deref())
        {
            eprintln!("win_live_turn: §2.5 TCB integrity floor not satisfied: {why}");
            return blocked("tcb_integrity_floor");
        }

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
        // Audit P1-a: pin the root from the TCB (crate::tcb), NEVER from config. A config-supplied root that
        // disagrees with the compiled-in anchor is refused (an adversary who writes config cannot swap root).
        let pinned_root = PinnedRoot {
            root_key_id: tcb::ROOT_KEY_ID.to_string(),
            public_key_hex: tcb::root_public_key_hex(),
        };
        if !cfg.trust.root_pub_hex.is_empty() && cfg.trust.root_pub_hex != pinned_root.public_key_hex {
            return blocked("config_root_disagrees_with_tcb");
        }
        // The anchor's CUSTODY provenance is the operator's declaration from provisioning. It is typed
        // and closed: absent, empty or misspelled is a REFUSAL, never a silent fall-back to `external`.
        // The key itself is still pinned by the TCB — provenance answers a different question (who could
        // have produced a manifest under this anchor), and no signature check can answer it.
        let anchor_provenance = match RootProvenance::parse(&cfg.trust.root_provenance) {
            Some(p) => p,
            None => return blocked("root_anchor_provenance_unknown"),
        };
        let root_anchor = RootAnchor { pinned: pinned_root.clone(), provenance: anchor_provenance };
        // `verify_manifest_anchored` (not `verify_manifest`): it returns the evidence of WHICH anchor the
        // signature verified under, and that evidence is what `resolve_trust_state` requires before it
        // will render a production verdict.
        let verified_root = match verify_manifest_anchored(&manifest, &root_sig, &root_anchor) {
            Ok(v) => v,
            Err(_) => return blocked("manifest_root_signature_invalid"),
        };
        // Load + TCB-integrity-verify the anti-rollback floor (audit R1): a reset/tampered floor.json is
        // rejected because floor.sig will not verify under the TCB floor key.
        let floor = match brops_win_live::resolver::load_verified_floor(std::path::Path::new(&cfg.trust.floor_path)) {
            Ok(f) => f,
            Err(e) => return blocked(&format!("floor:{e}")),
        };
        // Resolve the production key once for the final trust classification (the resolver re-resolves per
        // turn and is the enforcement path). A keep-alive clone of the manifest backs the classification.
        let manifest_for_trust = manifest.clone();
        // Kept as an EARLY fail-closed check that the production signer key resolves at all; the
        // production VERDICT no longer reads it (F-29 — it now uses the key the chain verified under).
        let _signer_pub_hex =
            match resolve_production_key(&manifest, &cfg.trust.signer_key_id, RECEIPT_ENVELOPE_ARTIFACT_TYPE, now) {
                Ok(k) => k.public_key_hex,
                Err(_) => return blocked("key_resolution"),
            };
        if !manifest.keys.iter().any(|k| k.key_id == cfg.trust.supervisor_attestation_key_id) {
            return blocked("supervisor_attestation_key_missing");
        }

        // ---- (B) production manifest resolver (audit P1-b + P2): verify-manifest-vs-TCB + anti-rollback +
        //         PERSIST floor + resolve keys INSIDE the chain resolution, feeding the pinned keys that
        //         verify_and_accept verifies under. Replaces the inline "verify beside acceptance". ----
        let r = &cfg.resolved;
        let facts = ResolvedFacts {
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
        let resolver = ManifestResolver::new(
            manifest,
            root_sig,
            floor,
            std::path::PathBuf::from(&cfg.trust.floor_path),
            cfg.trust.signer_key_id.clone(),
            cfg.trust.supervisor_attestation_key_id.clone(),
            facts,
        );

        // ---- (C) transport + execution ----
        let connector = WindowsHopConnector {
            authority_pipe: cfg.pipes.authority.clone(),
            supervisor_pipe: cfg.pipes.supervisor.clone(),
            signer_pipe: cfg.pipes.signer.clone(),
        };
        let executor_path = cfg.executor_path.clone();
        let produce = move |_plan: &ExecutionPlan| -> Result<Vec<u8>, ()> {
            let mut cmd = std::process::Command::new(&executor_path);
            #[cfg(windows)]
            {
                use std::os::windows::process::CommandExt;
                cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW — no console flash on spawn
            }
            let out = cmd.output().map_err(|_| ())?;
            if !out.status.success() || out.stdout.is_empty() {
                return Err(());
            }
            Ok(out.stdout)
        };
        let sup_pipe = cfg.pipes.supervisor.clone();
        // One named-pipe hop per §5 lifecycle op (execution-started / complete-run / attest-run).
        let supervisor_op = move |req: &Value| -> Result<Value, ()> {
            let reply = pipe::hop_once(&sup_pipe, req)?;
            if reply.get("ok").and_then(Value::as_bool) == Some(true) {
                Ok(reply)
            } else {
                Err(())
            }
        };
        let params = ExecutionParams {
            store_dir: std::path::PathBuf::from(&cfg.store_dir),
            containment_mode: "windows-live-kit:spawned executor, session-0 containment proven separately"
                .to_string(),
            // F-02/F-01: the four `facts.evidence_*` deployment constants are gone. The execution
            // measures its own chain and the supervisor derives the head from it, so the evidence
            // head describes THIS run instead of naming the same value for every run of the kit.
            evidence_dir: std::path::PathBuf::from(&cfg.store_dir).join("run-evidence"),
            head_sequence: cfg.facts.evidence_head_sequence,
        };
        let exec = GovernedExecutionCore::new(params, produce, supervisor_op, now);

        // ---- (D) run ONE governed turn ----
        // Keep a handle to the SAME resolver the chain drives (F-29).
        let resolver_handle = std::sync::Arc::new(resolver);
        let chain = GovernedChain::new(connector, SharedResolver(resolver_handle.clone()), exec, InMemoryLedger::new());
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

        // F-29: the key the CHAIN verified under, recorded by the resolver.
        let verified_under = match resolver_handle.last_verifying_key() {
            Some(k) => verifying_key_hex(&k),
            None => return blocked("resolver_never_bound_a_verifying_key"),
        };
        let ts = resolve_trust_state(
            Some(&manifest_for_trust),
            Some(&verified_root),
            &cfg.trust.signer_key_id,
            RECEIPT_ENVELOPE_ARTIFACT_TYPE,
            now,
            &verified_under,
        );
        let production_verified = ts.is_production_verified();
        let ts_str = match &ts {
            TrustState::Production { key_id, key_epoch, root_key_id } => {
                format!("trusted_verified(production key={key_id} epoch={key_epoch} root={root_key_id})")
            }
            TrustState::DemonstrationCustody { key_id, key_epoch, root_key_id, root_provenance } => {
                format!(
                    "trusted_verified(demonstration_custody key={key_id} epoch={key_epoch} \
                     root={root_key_id} root_provenance={})",
                    root_provenance.as_str()
                )
            }
            TrustState::NoTrustedManifest(r) => format!("no_trusted_manifest({r})"),
        };
        println!(
            "RESULT: {ts_str} production_verified={production_verified} bound={bound} root_anchor={}",
            anchor_provenance.as_str()
        );
        if production_verified && bound {
            0
        } else {
            1
        }
    }
}
